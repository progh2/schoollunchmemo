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
        assert dialog.tabs.count() == 3
        assert dialog.key_edit.text() == "dummy-key"
        assert "미림마이스터고등학교" in dialog.selected_label.text()
        assert dialog.search_edit.isEnabled()
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
