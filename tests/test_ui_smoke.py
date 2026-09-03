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


LONG_ROWS = [
    {
        "MLSV_YMD": "20260724",
        "MMEAL_SC_CODE": "1",
        "MMEAL_SC_NM": "조식",
        "DDISH_NM": "<br/>".join(
            [
                "칼슘찹쌀밥",
                "김치찌개 (5.9.10.13)",
                "모듬버섯불고기 (5.6.10.13)",
                "어묵볶음 (1.5.6.13.18)",
                "열무김치 (9)",
                "김자반",
                "요구르트 (2.13)",
            ]
        ),
        "CAL_INFO": "1228.3 Kcal",
        "ORPLC_INFO": "<br/>".join(
            [
                "쌀 : 국내산",
                "돼지고기 : 국내산",
                "쇠고기 : 호주산",
                "배추김치 : 국내산",
                "고춧가루 : 중국산",
            ]
        ),
    },
    {
        "MLSV_YMD": "20260724",
        "MMEAL_SC_CODE": "2",
        "MMEAL_SC_NM": "중식",
        "DDISH_NM": "<br/>".join(
            [
                "땡초고기볶음밥 (5.6.10.13.18)",
                "미소장국 (5.6.8.9.10.13.15.16.17.18)",
                "상추겉절이 (13)",
                "바사삭양념마리치킨 (1.2.5.12.15)",
                "치킨무 (13)",
                "수박",
                "양배추샐러드 (1.5.12)",
            ]
        ),
        "CAL_INFO": "2602.9 Kcal",
        "ORPLC_INFO": "닭고기 : 국내산<br/>양배추 : 국내산",
    },
]


def test_long_content_scrolls_instead_of_growing_window(note, qapp, monkeypatch):
    """실제 급식처럼 내용이 길어도 창이 화면 상한을 넘어서면 안 된다."""
    import app.sticky as sticky

    # 테스트 화면 크기에 좌우되지 않도록 상한을 직접 정한다
    monkeypatch.setattr(sticky, "MAX_HEIGHT_RATIO", 0.3)
    limit = qapp.primaryScreen().availableGeometry().height() * 0.3

    note.set_details_default(True)
    note.render_view(
        NoteView(
            day=date(2026, 7, 24),
            meals=parse_meals(LONG_ROWS),
            show_allergy=True,
        )
    )

    assert note.height() <= limit
    # 넘치는 만큼은 스크롤로 넘어간다
    assert note.scroll.height() < note.body.height()


def test_short_content_needs_no_scroll(note):
    note.render_view(
        NoteView(day=date(2026, 7, 29), meals=parse_meals(MEAL_ROWS))
    )
    assert note.scroll.height() == note.body.height()


def test_toggling_details_repeatedly_stays_stable(note):
    """클릭을 반복해도 크기가 발산하지 않아야 한다 (리사이즈 루프 방지)."""
    note.render_view(
        NoteView(day=date(2026, 7, 24), meals=parse_meals(LONG_ROWS))
    )
    collapsed = note.height()
    note.toggle_details()
    expanded = note.height()
    note.toggle_details()
    assert note.height() == collapsed
    note.toggle_details()
    assert note.height() == expanded


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


def test_settings_dialog_builds(qapp):
    from app.settings_dialog import SettingsDialog

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
        assert dialog.tabs.tabText(dialog._tab_index["info"]) == "정보"
        assert "미림마이스터고등학교" in dialog.selected_label.text()
        assert dialog.search_edit.isEnabled()
    finally:
        dialog.deleteLater()


def test_settings_dialog_saves_allergy_choices(qapp, monkeypatch):
    from app.settings_dialog import SettingsDialog

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


def test_settings_dialog_restores_allergy_choices(qapp):
    from app.settings_dialog import SettingsDialog

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


class TestAutostartCheckbox:
    """자동 시작 체크박스는 OS에 실제로 등록된 상태를 따라야 한다."""

    @pytest.fixture
    def dialog_factory(self, qapp, monkeypatch):
        from app import autostart
        from app.settings_dialog import SettingsDialog

        monkeypatch.setattr(Config, "save", lambda self: None)

        calls: list[bool] = []
        monkeypatch.setattr(
            autostart, "set_enabled", lambda on: calls.append(on) or True
        )

        created = []

        def make(enabled: bool, supported: bool = True):
            monkeypatch.setattr(autostart, "is_supported", lambda: supported)
            monkeypatch.setattr(autostart, "is_enabled", lambda: enabled)
            config = Config()
            # 학교가 없으면 저장할 때 확인 대화상자가 떠서 테스트가 멈춘다
            config.school = {
                "office_code": "B10",
                "school_code": "7010084",
                "school_name": "미림마이스터고등학교",
            }
            dialog = SettingsDialog(config)
            created.append(dialog)
            return dialog

        yield make, calls
        for dialog in created:
            dialog.deleteLater()

    def test_reflects_registered_state(self, dialog_factory):
        make, _ = dialog_factory
        assert make(True).boot_check.isChecked() is True
        assert make(False).boot_check.isChecked() is False

    def test_disabled_where_unsupported(self, dialog_factory):
        make, _ = dialog_factory
        assert not make(False, supported=False).boot_check.isEnabled()

    def test_saving_without_changing_leaves_os_alone(self, dialog_factory):
        make, calls = dialog_factory
        dialog = make(False)
        dialog._on_save()
        assert calls == []  # 레지스트리를 괜히 건드리지 않는다

    def test_turning_on_registers_and_records(self, dialog_factory):
        make, calls = dialog_factory
        dialog = make(False)
        dialog.boot_check.setChecked(True)
        dialog._on_save()
        assert calls == [True]
        assert dialog._config.display["start_on_boot"] is True

    def test_failure_is_not_recorded_as_enabled(self, dialog_factory, monkeypatch):
        from app import autostart

        make, _ = dialog_factory
        dialog = make(False)
        monkeypatch.setattr(autostart, "set_enabled", lambda on: False)
        monkeypatch.setattr(
            "app.settings_dialog.QMessageBox.warning", lambda *a, **k: None
        )
        dialog.boot_check.setChecked(True)
        dialog._on_save()
        assert dialog._config.display["start_on_boot"] is False
        assert dialog.boot_check.isChecked() is False


def test_settings_dialog_search_always_enabled(qapp):
    from app.settings_dialog import SettingsDialog

    dialog = SettingsDialog(Config())
    try:
        assert dialog.search_edit.isEnabled()
        assert dialog.search_button.isEnabled()
    finally:
        dialog.deleteLater()


class TestDateLabelClick:
    """날짜를 누르면 달력, 나머지를 누르면 재료 펼침."""

    @pytest.fixture
    def shown(self, note):
        note.render_view(
            NoteView(day=date(2026, 7, 29), meals=parse_meals(MEAL_ROWS))
        )
        note.show()
        yield note
        note.hide()

    def test_date_label_is_hit_tested(self, shown):
        from PySide6.QtCore import QPoint

        center = shown.date_label.mapToGlobal(shown.date_label.rect().center())
        assert shown._on_date_label(center) is True
        assert shown._on_date_label(shown.mapToGlobal(QPoint(2, 2))) is False

    def test_clicking_the_date_asks_for_the_calendar(self, shown):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        seen = []
        shown.calendarRequested.connect(seen.append)
        pos = shown.date_label.mapTo(shown, shown.date_label.rect().center())
        QTest.mouseClick(shown, Qt.MouseButton.LeftButton, pos=pos)

        assert len(seen) == 1
        assert "국내산" not in shown.body.text()  # 재료는 그대로 접혀 있다

    def test_clicking_elsewhere_still_toggles_details(self, shown):
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest

        seen = []
        shown.calendarRequested.connect(seen.append)
        QTest.mouseClick(shown, Qt.MouseButton.LeftButton, pos=QPoint(20, 100))

        assert seen == []
        assert "국내산" in shown.body.text()


class TestCalendarPopup:
    @pytest.fixture
    def popup(self, qapp):
        from app.calendar_popup import CalendarPopup

        widget = CalendarPopup()
        yield widget
        widget.deleteLater()

    def test_legend_names_every_meal(self, popup):
        from app.calendar_popup import MEAL_COLORS, MEAL_SLOTS

        html = popup.legend.text()
        for key in MEAL_SLOTS:
            assert MEAL_COLORS[key] in html
        for label in ("조식", "중식", "석식", "일정"):
            assert label in html

    def test_status_replaces_then_restores_the_legend(self, popup):
        legend = popup.legend.text()
        popup.set_status("표시를 가져오지 못했어요")
        assert popup.legend.text() == "표시를 가져오지 못했어요"
        popup.set_status("")
        assert popup.legend.text() == legend

    def test_clicking_a_day_reports_a_python_date(self, popup):
        from PySide6.QtCore import QDate

        seen = []
        popup.dateSelected.connect(seen.append)
        popup.calendar.clicked.emit(QDate(2026, 7, 9))
        assert seen == [date(2026, 7, 9)]

    def test_marks_paint_without_error(self, popup):
        """paintCell은 실제로 그려 봐야 오류가 드러난다."""
        from app.calendar_popup import DayMarks

        popup.set_marks(
            {
                date(2026, 7, 6): DayMarks(meal_keys=frozenset({"lunch"})),
                date(2026, 7, 7): DayMarks(
                    meal_keys=frozenset({"breakfast", "lunch", "dinner"}),
                    events=("체육대회",),
                ),
                date(2026, 7, 17): DayMarks(
                    events=("여름방학식",), is_holiday=True
                ),
            }
        )
        popup.calendar.setCurrentPage(2026, 7)
        assert not popup.calendar.grab().isNull()

    @pytest.mark.parametrize("color", list(PALETTE))
    def test_every_palette_applies(self, popup, color):
        popup.apply_color(color)
        assert not popup.calendar.grab().isNull()


def test_about_tab_links_to_project_and_author(qapp):
    from PySide6.QtWidgets import QLabel

    from app import AUTHOR_URL, ISSUES_URL, LICENSE_NAME, REPO_URL
    from app.settings_dialog import SettingsDialog

    dialog = SettingsDialog(Config())
    try:
        dialog.show_tab("info")
        assert dialog.tabs.currentIndex() == dialog._tab_index["info"]

        tab = dialog.tabs.currentWidget()
        html = " ".join(label.text() for label in tab.findChildren(QLabel))
        assert REPO_URL in html
        assert ISSUES_URL in html
        assert AUTHOR_URL in html
        assert LICENSE_NAME in html
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


class TestAlwaysOnTop:
    """'항상 위에 표시'를 끄면 힌트가 실제로 빠져야 한다 (#26)."""

    def test_default_is_on_top(self, note):
        from PySide6.QtCore import Qt

        assert note.windowFlags() & Qt.WindowType.WindowStaysOnTopHint

    def test_turning_off_clears_the_hint(self, note):
        from PySide6.QtCore import Qt

        note.set_always_on_top(False)
        assert not (note.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)

    def test_toggling_back_restores_the_hint(self, note):
        from PySide6.QtCore import Qt

        note.set_always_on_top(False)
        note.set_always_on_top(True)
        assert note.windowFlags() & Qt.WindowType.WindowStaysOnTopHint

    def test_other_flags_survive_the_toggle(self, note):
        """플래그를 통째로 다시 세우므로 Frameless/Tool이 날아가면 안 된다."""
        from PySide6.QtCore import Qt

        had_tool = bool(note.windowFlags() & Qt.WindowType.Tool)
        note.set_always_on_top(False)

        flags = note.windowFlags()
        assert flags & Qt.WindowType.FramelessWindowHint
        assert bool(flags & Qt.WindowType.Tool) is had_tool


def _run_task_now(fn, *args, on_ok=None, on_err=None, **kwargs):
    """워커 대신 그 자리에서 실행한다. 테스트에서 스레드를 기다리지 않으려고."""
    try:
        result = fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001 - 실패 경로도 확인한다
        if on_err is not None:
            on_err(exc)
    else:
        if on_ok is not None:
            on_ok(result)


def _fake_release(tag):
    from app import updater

    return updater.Release(
        tag=tag,
        notes="바뀐 것",
        page_url="https://example.invalid/release",
        asset_name="SchoolNote.zip",
        asset_url="https://example.invalid/SchoolNote.zip",
        asset_size=1024,
    )


class TestUpdateCheck:
    """정보 탭의 [업데이트 확인] (#27)."""

    def _dialog(self, monkeypatch):
        from app.settings_dialog import SettingsDialog

        monkeypatch.setattr("app.settings_dialog.submit", _run_task_now)
        dialog = SettingsDialog(Config())
        dialog.show_tab("info")
        return dialog

    def test_button_exists_and_does_not_check_on_open(self, qapp, monkeypatch):
        from app import updater

        calls = []
        monkeypatch.setattr(
            updater, "fetch_latest", lambda *a, **k: calls.append(1) or _fake_release("v0.0.1")
        )
        dialog = self._dialog(monkeypatch)
        try:
            assert dialog.update_button.text() == "업데이트 확인"
            assert calls == []  # 눌러야만 조회한다
        finally:
            dialog.deleteLater()

    def test_same_version_reports_up_to_date(self, qapp, monkeypatch):
        from app import VERSION, updater

        monkeypatch.setattr(updater, "fetch_latest", lambda *a, **k: _fake_release(f"v{VERSION}"))
        dialog = self._dialog(monkeypatch)
        try:
            dialog._on_check_update()
            assert "최신 버전입니다" in dialog.update_status.text()
            assert dialog.update_button.isEnabled()
        finally:
            dialog.deleteLater()

    def test_new_version_from_source_run_points_at_releases(self, qapp, monkeypatch):
        """소스에서 돌 때는 자동 설치 대신 릴리스 페이지로 보낸다."""
        from app import updater

        monkeypatch.setattr(updater, "fetch_latest", lambda *a, **k: _fake_release("v99.9.9"))
        dialog = self._dialog(monkeypatch)
        try:
            dialog._on_check_update()
            text = dialog.update_status.text()
            assert "v99.9.9" in text
            assert "릴리스 페이지" in text
            assert dialog.update_button.isEnabled()
        finally:
            dialog.deleteLater()

    def test_failure_shows_reason_and_reenables_button(self, qapp, monkeypatch):
        from app import updater

        def boom(*_args, **_kwargs):
            raise updater.UpdateError("업데이트 서버에 연결하지 못했습니다.")

        monkeypatch.setattr(updater, "fetch_latest", boom)
        dialog = self._dialog(monkeypatch)
        try:
            dialog._on_check_update()
            assert "연결하지 못했습니다" in dialog.update_status.text()
            assert dialog.update_button.isEnabled()
            assert dialog.update_progress.isHidden() or not dialog.update_progress.isVisible()
        finally:
            dialog.deleteLater()
