"""날짜 이동 동작 테스트.

캐시가 있는 날은 네트워크를 타지 않는다는 전제로, 컨트롤러를 직접 만들어
어제/내일 이동과 오늘 복귀를 확인한다.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.config import Config
from app.neis.models import School

SCHOOL = {
    "office_code": "B10",
    "office_name": "서울특별시교육청",
    "school_code": "7010084",
    "school_name": "미림마이스터고등학교",
    "school_kind": "고등학교",
}


def _rows_for(day: date) -> dict:
    return {
        "saved_at": f"{day:%Y-%m-%d}T09:00:00+09:00",
        "meal_rows": [
            {
                "MLSV_YMD": f"{day:%Y%m%d}",
                "MMEAL_SC_CODE": "2",
                "MMEAL_SC_NM": "중식",
                "DDISH_NM": f"{day.day}일의밥<br/>미역국",
                "CAL_INFO": "600 Kcal",
            }
        ],
        "schedule_rows": [],
    }


@pytest.fixture
def controller(qapp, monkeypatch):
    from app import cache, controller as controller_module, secrets_store

    config = Config()
    config.school = dict(SCHOOL)

    monkeypatch.setattr(Config, "load", classmethod(lambda cls: config))
    monkeypatch.setattr(Config, "save", lambda self: None)
    monkeypatch.setattr(secrets_store, "get_key", lambda: "dummy-key")
    # 모든 날짜에 캐시가 있는 상태 → 네트워크 호출이 일어나지 않는다
    monkeypatch.setattr(cache, "load", lambda code, day: _rows_for(day))
    monkeypatch.setattr(cache, "save", lambda *a, **kw: None)

    instance = controller_module.AppController(qapp)
    # force=True 경로가 실제로 NEIS를 호출하지 않도록 막는다
    monkeypatch.setattr(
        instance._client,
        "fetch_day",
        lambda school, day, meal_keys=None: (_rows_for(day)["meal_rows"], []),
    )
    instance.refresh()
    yield instance
    instance.note.deleteLater()
    instance.tray.deleteLater()


def test_starts_on_today(controller):
    assert controller._view_day == date.today()
    # 창 자체가 떠 있지 않으므로 isVisible() 대신 명시적 숨김 여부를 본다
    assert controller.note.today_button.isHidden() is True
    assert f"{date.today().day}일의밥" in controller.note.body.text()


def test_step_to_yesterday_and_tomorrow(controller):
    controller.step_day(-1)
    yesterday = date.today() - timedelta(days=1)
    assert controller._view_day == yesterday
    assert f"{yesterday.day}일의밥" in controller.note.body.text()
    assert "어제" in controller.note.date_label.text()

    controller.step_day(2)
    tomorrow = date.today() + timedelta(days=1)
    assert controller._view_day == tomorrow
    assert "내일" in controller.note.date_label.text()


def test_today_button_appears_only_off_today(controller):
    controller.step_day(1)
    assert controller.note.today_button.isHidden() is False
    controller.go_today()
    assert controller._view_day == date.today()
    assert controller.note.today_button.isHidden() is True


def test_range_is_clamped(controller):
    from app.controller import MAX_DAY_OFFSET

    controller._view_day = date.today() + timedelta(days=MAX_DAY_OFFSET)
    controller.step_day(1)  # 한계를 넘는 이동은 무시된다
    assert controller._view_day == date.today() + timedelta(days=MAX_DAY_OFFSET)

    controller.step_day(-1)
    assert controller._view_day == date.today() + timedelta(
        days=MAX_DAY_OFFSET - 1
    )


def test_midnight_rollover_returns_to_today(controller):
    controller.step_day(-3)
    assert controller._view_day != date.today()
    controller._on_day_changed()
    assert controller._view_day == date.today()


def test_reshowing_note_returns_to_today(controller):
    controller.step_day(-2)
    controller.hide_note()
    controller.show_note()
    assert controller._view_day == date.today()


def test_stale_response_does_not_overwrite_current_day(controller):
    """응답을 기다리는 사이 날짜를 옮기면 늦게 온 결과는 무시한다."""
    controller.step_day(1)
    stale_day = date.today() - timedelta(days=5)
    before = controller.note.body.text()

    controller._on_fetched(
        School.from_config(SCHOOL),
        stale_day,
        (_rows_for(stale_day)["meal_rows"], []),
    )
    assert controller.note.body.text() == before
