"""UI 스모크 테스트.

화면 없이(offscreen) 위젯을 만들어 렌더까지 통과하는지만 확인한다.
QSS 오타, 잘못된 Qt enum, 시그널 배선 실수처럼 실행해야만 드러나는
오류를 CI에서 잡기 위한 것이다.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.config import Config
from app.neis.parser import parse_meals, parse_schedule
from app.resources.icons import app_icon
from app.resources.theme import PALETTE
from app.sticky import NoteView, StickyNote

MEAL_ROWS = [
    {
        "MLSV_YMD": "20260729",
        "MMEAL_SC_CODE": "2",
        "MMEAL_SC_NM": "중식",
        "DDISH_NM": "기장밥<br/>쇠고기미역국 (5.6.16.)<br/>배추김치 (9.13)",
        "CAL_INFO": "678.3 Kcal",
        "ORPLC_INFO": "쌀 : 국내산",
    }
]
SCHEDULE_ROWS = [
    {
        "AA_YMD": "20260729",
        "EVENT_NM": "여름방학식",
        "SBTR_DD_SC_NM": "휴업일",
        "ONE_GRADE_EVENT_YN": "Y",
    }
]


@pytest.fixture
def note(qapp):
    widget = StickyNote()
    yield widget
    widget.deleteLater()


def test_renders_content(note):
    note.render_view(
        NoteView(
            day=date(2026, 7, 29),
            meals=parse_meals(MEAL_ROWS),
            events=parse_schedule(SCHEDULE_ROWS),
            footer="09:12 갱신됨",
        )
    )
    assert "7월 29일 (수)" in note.date_label.text()
    body = note.body.text()
    assert "쇠고기미역국" in body
    assert "여름방학식" in body
    assert "678.3 kcal" in body
    assert note.footer_label.text() == "09:12 갱신됨"


def test_allergy_toggle(note):
    meals = parse_meals(MEAL_ROWS)
    note.render_view(NoteView(day=date(2026, 7, 29), meals=meals))
    assert "(5.6.16)" not in note.body.text()

    note.render_view(
        NoteView(day=date(2026, 7, 29), meals=meals, show_allergy=True)
    )
    assert "(5.6.16)" in note.body.text()


def test_allergy_alert_marks_dish_red(note):
    from app.sticky import DANGER_COLOR

    # 배추김치 (9.13) 에서 9 = 새우
    note.render_view(
        NoteView(
            day=date(2026, 7, 29),
            meals=parse_meals(MEAL_ROWS),
            allergy_alerts=frozenset({9}),
        )
    )
    body = note.body.text()
    assert DANGER_COLOR in body
    assert "새우" in body  # 왜 빨간지 알려준다
    # 겹치지 않는 요리는 그대로 둔다
    assert f"<span style='color:{DANGER_COLOR}; font-weight:600'>기장밥" not in body


def test_no_allergy_alert_leaves_dishes_plain(note):
    from app.sticky import DANGER_COLOR

    note.render_view(
        NoteView(day=date(2026, 7, 29), meals=parse_meals(MEAL_ROWS))
    )
    assert DANGER_COLOR not in note.body.text()


class TestDetailsToggle:
    def test_hidden_by_default_with_hint(self, note):
        note.render_view(
            NoteView(day=date(2026, 7, 29), meals=parse_meals(MEAL_ROWS))
        )
        body = note.body.text()
        assert "재료·원산지 보기" in body
        assert "국내산" not in body

    def test_click_reveals_and_hides(self, note):
        note.render_view(
            NoteView(day=date(2026, 7, 29), meals=parse_meals(MEAL_ROWS))
        )
        note.toggle_details()
        body = note.body.text()
        assert "국내산" in body
        assert "재료·원산지 숨기기" in body

        note.toggle_details()
        assert "국내산" not in note.body.text()

    def test_no_hint_when_nothing_to_show(self, note):
        rows = [dict(MEAL_ROWS[0])]
        rows[0].pop("ORPLC_INFO")
        note.render_view(NoteView(day=date(2026, 7, 29), meals=parse_meals(rows)))
        assert "재료·원산지" not in note.body.text()

    def test_allergy_highlighted_inside_details(self, note):
        from app.sticky import DANGER_COLOR

        rows = [dict(MEAL_ROWS[0])]
        rows[0]["ORPLC_INFO"] = "쌀 : 국내산<br/>쇠고기 : 호주산"
        note.set_details_default(True)
        note.render_view(
            NoteView(
                day=date(2026, 7, 29),
                meals=parse_meals(rows),
                allergy_alerts=frozenset({16}),  # 쇠고기
            )
        )
        body = note.body.text()
        assert "원산지" in body
        assert f"<span style='color:{DANGER_COLOR}; font-weight:600'>쇠고기</span>" in body


def test_message_state_never_blank(note):
    note.render_view(
        NoteView(day=date(2026, 7, 29), message="설정이 필요해요", message_icon="📌")
    )
    assert "설정이 필요해요" in note.body.text()


def test_meal_note_shown_when_only_schedule(note):
    note.render_view(
        NoteView(
            day=date(2026, 7, 29),
            events=parse_schedule(SCHEDULE_ROWS),
            meal_note="🌙 오늘은 급식이 없어요",
        )
    )
    body = note.body.text()
    assert "오늘은 급식이 없어요" in body
    assert "여름방학식" in body


@pytest.mark.parametrize("color", list(PALETTE))
def test_every_palette_applies(note, color):
    note.apply_color(color)
    note.render_view(NoteView(day=date(2026, 7, 29), meals=parse_meals(MEAL_ROWS)))
    assert note._color == color


def test_icons_render(qapp):
    icon = app_icon("yellow", error=True)
    assert not icon.isNull()
    assert not icon.pixmap(32, 32).isNull()


def test_settings_dialog_builds(qapp, monkeypatch):
    from app import secrets_store
    from app.settings_dialog import SettingsDialog

    monkeypatch.setattr(secrets_store, "get_key", lambda: "dummy-key")
    monkeypatch.setattr(secrets_store, "is_secure", lambda: True)

    config = Config()
    config.school = {
        "office_code": "B10",
        "office_name": "서울특별시교육청",
        "school_code": "7010084",
        "school_name": "미림마이스터고등학교",
        "school_kind": "고등학교",
    }
    dialog = SettingsDialog(config)
    try:
        assert dialog.tabs.count() == 4
        assert dialog.key_edit.text() == "dummy-key"
        assert "미림마이스터고등학교" in dialog.selected_label.text()
        assert dialog.search_edit.isEnabled()
    finally:
        dialog.deleteLater()


def test_settings_dialog_saves_allergy_choices(qapp, monkeypatch):
    from app import secrets_store
    from app.settings_dialog import SettingsDialog

    monkeypatch.setattr(secrets_store, "get_key", lambda: "dummy-key")
    monkeypatch.setattr(secrets_store, "is_secure", lambda: True)
    monkeypatch.setattr(secrets_store, "set_key", lambda key: None)
    monkeypatch.setattr(Config, "save", lambda self: None)

    config = Config()
    config.school = {
        "office_code": "B10",
        "office_name": "서울특별시교육청",
        "school_code": "7010084",
        "school_name": "미림마이스터고등학교",
        "school_kind": "고등학교",
    }
    dialog = SettingsDialog(config)
    try:
        dialog.allergy_checks[2].setChecked(True)
        dialog.allergy_checks[16].setChecked(True)
        dialog.expand_check.setChecked(True)
        dialog._on_save()

        assert config.display["allergy_alerts"] == [2, 16]
        assert config.display["expand_details"] is True
    finally:
        dialog.deleteLater()


def test_settings_dialog_restores_allergy_choices(qapp, monkeypatch):
    from app import secrets_store
    from app.settings_dialog import SettingsDialog

    monkeypatch.setattr(secrets_store, "get_key", lambda: "dummy-key")
    monkeypatch.setattr(secrets_store, "is_secure", lambda: True)

    config = Config()
    config.display["allergy_alerts"] = [5, 9]
    dialog = SettingsDialog(config)
    try:
        checked = {
            code for code, c in dialog.allergy_checks.items() if c.isChecked()
        }
        assert checked == {5, 9}
    finally:
        dialog.deleteLater()


def test_settings_dialog_blocks_search_without_key(qapp, monkeypatch):
    from app import secrets_store
    from app.settings_dialog import SettingsDialog

    monkeypatch.setattr(secrets_store, "get_key", lambda: "")
    monkeypatch.setattr(secrets_store, "is_secure", lambda: True)

    dialog = SettingsDialog(Config())
    try:
        assert not dialog.search_edit.isEnabled()
        assert "인증키" in dialog.search_status.text()
    finally:
        dialog.deleteLater()


def test_tray_builds(qapp):
    from app.tray import Tray

    tray = Tray()
    try:
        tray.set_school_name("미림마이스터고등학교")
        assert "미림마이스터고등학교" in tray.toolTip()
        tray.set_error(True)
        tray.set_color("sky")
        assert not tray.icon().isNull()
    finally:
        tray.deleteLater()
