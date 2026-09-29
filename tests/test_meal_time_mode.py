"""식사 시간 모드에서 컨트롤러가 홈 화면을 시계에 맞추는지 (#37).

시각을 고정해 두고, 캐시에 조·중·석식이 모두 있는 상태에서 확인한다.
"""

from __future__ import annotations

from datetime import date, datetime, time

import pytest

from app.config import Config

TUESDAY = date(2026, 9, 29)
WEDNESDAY = date(2026, 9, 30)
SCHOOL = {
    "office_code": "B10",
    "office_name": "서울특별시교육청",
    "school_code": "7011569",
    "school_name": "미림마이스터고등학교",
    "school_kind": "고등학교",
}


def _rows_for(day: date) -> dict:
    def meal(code: str, label: str) -> dict:
        return {
            "MLSV_YMD": f"{day:%Y%m%d}",
            "MMEAL_SC_CODE": code,
            "MMEAL_SC_NM": label,
            "DDISH_NM": f"{day.day}일{label}밥<br/>국",
        }

    return {
        "saved_at": f"{day:%Y-%m-%d}T06:00:00+09:00",
        "meal_rows": [meal("1", "조식"), meal("2", "중식"), meal("3", "석식")],
        "schedule_rows": [],
    }


class _Clock:
    """테스트가 바꿀 수 있는 '지금'."""

    def __init__(self) -> None:
        self.now = datetime.combine(TUESDAY, time(9, 0))

    def set(self, hhmm: str, day: date = TUESDAY) -> None:
        hours, minutes = map(int, hhmm.split(":"))
        self.now = datetime.combine(day, time(hours, minutes))


@pytest.fixture
def clock(monkeypatch):
    import app.controller as controller_module
    import app.sticky as sticky_module

    state = _Clock()

    class FakeDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return state.now

    class FakeDate(date):
        @classmethod
        def today(cls):
            return state.now.date()

    monkeypatch.setattr(controller_module, "datetime", FakeDatetime)
    monkeypatch.setattr(controller_module, "date", FakeDate)
    monkeypatch.setattr(sticky_module, "date", FakeDate)
    return state


def _make(qapp, monkeypatch, meal_types, mode=True):
    from app import cache
    from app import controller as controller_module

    config = Config()
    config.school = dict(SCHOOL)
    config.display["meal_types"] = list(meal_types)
    config.display["meal_time_mode"] = mode

    monkeypatch.setattr(Config, "load", classmethod(lambda cls: config))
    monkeypatch.setattr(Config, "save", lambda self: None)
    monkeypatch.setattr(cache, "load", lambda code, day: _rows_for(day))
    monkeypatch.setattr(cache, "save", lambda *a, **kw: None)

    instance = controller_module.AppController(qapp)
    monkeypatch.setattr(
        instance._client,
        "fetch_day",
        lambda school, day, meal_keys=None: (_rows_for(day)["meal_rows"], []),
    )
    return instance


@pytest.fixture
def make(qapp, monkeypatch, clock):
    made = []

    def factory(meal_types, mode=True):
        instance = _make(qapp, monkeypatch, meal_types, mode)
        made.append(instance)
        return instance

    yield factory
    for instance in made:
        instance.note.deleteLater()
        instance.tray.deleteLater()


def _body(controller) -> str:
    return controller.note.body.text()


class TestLunchOnly:
    def test_before_lunch_shows_today(self, make, clock):
        clock.set("10:00")
        controller = make(["lunch"])
        controller.refresh()
        assert controller._view_day == TUESDAY
        assert "29일중식밥" in _body(controller)

    def test_after_lunch_shows_tomorrow_without_today_button(self, make, clock):
        clock.set("14:00")
        controller = make(["lunch"])
        controller.refresh()

        assert controller._view_day == WEDNESDAY
        assert "30일중식밥" in _body(controller)
        assert "다음 급식" in _body(controller)  # 왜 내일인지 알려 준다
        # 홈 화면이므로 '오늘로' 버튼은 필요 없다
        assert controller.note.today_button.isHidden()
        assert "내일" in controller.note.footer_label.text()

    def test_moves_on_by_itself_when_lunch_ends(self, make, clock):
        clock.set("13:00")
        controller = make(["lunch"])
        controller.refresh()
        assert controller._view_day == TUESDAY
        assert "지금" in _body(controller)

        clock.set("13:31")
        controller.scheduler.ticked.emit()
        assert controller._view_day == WEDNESDAY


class TestAllMeals:
    def test_past_meals_hidden_and_current_marked(self, make, clock):
        clock.set("12:45")
        controller = make(["breakfast", "lunch", "dinner"])
        controller.refresh()
        body = _body(controller)

        assert "29일조식밥" not in body  # 아침은 지났다
        assert "29일중식밥" in body and "29일석식밥" in body
        assert "지금" in body


class TestBrowsingOtherDays:
    def test_stepping_away_shows_whole_day_and_ignores_clock(self, make, clock):
        clock.set("12:45")
        controller = make(["breakfast", "lunch", "dinner"])
        controller.refresh()

        controller.step_day(1)
        assert controller._view_day == WEDNESDAY
        body = _body(controller)
        assert "30일조식밥" in body  # 다른 날은 전체를 보여준다
        assert "지금" not in body
        assert not controller.note.today_button.isHidden()

        clock.set("19:00")
        controller.scheduler.ticked.emit()
        assert controller._view_day == WEDNESDAY  # 보고 있던 날을 빼앗지 않는다

    def test_today_button_returns_to_clock_home(self, make, clock):
        clock.set("14:00")
        controller = make(["lunch"])
        controller.refresh()
        controller.step_day(-1)
        assert controller._view_day == TUESDAY

        controller.go_today()
        assert controller._view_day == WEDNESDAY  # 홈 = 점심 뒤라 내일


class TestModeOff:
    def test_off_means_plain_today(self, make, clock):
        clock.set("20:00")
        controller = make(["breakfast", "lunch", "dinner"], mode=False)
        controller.refresh()
        body = _body(controller)
        assert controller._view_day == TUESDAY
        assert "29일조식밥" in body and "29일석식밥" in body
        assert "지금" not in body
