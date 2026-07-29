"""앱 전체를 엮는 컨트롤러.

포스트잇·트레이·설정 창·스케줄러를 소유하고, 조회 흐름과 상태 표시를 결정한다.
"""

from __future__ import annotations

import logging
from datetime import date, datetime

from PySide6.QtCore import QObject, Qt
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from . import APP_DISPLAY_NAME, VERSION, cache, secrets_store
from .config import Config
from .neis import NeisClient, NeisError, ResultKind
from .neis.models import MealMenu, School, ScheduleEvent
from .neis.parser import parse_meals, parse_schedule
from .scheduler import DayScheduler
from .settings_dialog import SettingsDialog
from .sticky import NoteView, StickyNote
from .tray import Tray
from .workers import submit

log = logging.getLogger(__name__)

#: 조회 실패 시 포스트잇에 띄울 문구 (PRD 4.2)
_FAILURE_TEXT: dict[ResultKind, str] = {
    ResultKind.BAD_KEY: "인증키를 확인해 주세요",
    ResultKind.QUOTA: "오늘 호출 한도를 초과했어요",
    ResultKind.NETWORK: "정보를 가져오지 못했어요",
    ResultKind.SERVER: "NEIS 서버에 문제가 있어요",
    ResultKind.BAD_REQUEST: "요청이 올바르지 않아요",
    ResultKind.UNKNOWN: "정보를 가져오지 못했어요",
}


class AppController(QObject):
    def __init__(self, app: QApplication) -> None:
        super().__init__()
        self._app = app
        self._config = Config.load()
        self._client = NeisClient(secrets_store.get_key)
        self._dialog: SettingsDialog | None = None
        self._fetching = False

        self.note = StickyNote(color=self._config.display.get("color", "yellow"))
        self.tray = Tray(color=self._config.display.get("color", "yellow"))
        self.scheduler = DayScheduler(self)

        self._connect()

    # ---------------------------------------------------------------- 배선

    def _connect(self) -> None:
        self.note.refreshRequested.connect(lambda: self.refresh(force=True))
        self.note.settingsRequested.connect(self.open_settings)
        self.note.hideRequested.connect(self.hide_note)
        self.note.quitRequested.connect(self.quit)
        self.note.positionChanged.connect(self._on_position_changed)

        self.tray.toggleRequested.connect(self.toggle_note)
        self.tray.refreshRequested.connect(lambda: self.refresh(force=True))
        self.tray.settingsRequested.connect(self.open_settings)
        self.tray.aboutRequested.connect(self.show_about)
        self.tray.quitRequested.connect(self.quit)

        self.scheduler.dayChanged.connect(lambda: self.refresh(force=True))

    # ---------------------------------------------------------------- 시작

    def start(self) -> None:
        cache.prune()
        self._apply_display()

        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()
        else:
            # 트레이가 없으면 앱에 접근할 방법이 사라진다 (PRD T-07)
            log.warning("시스템 트레이를 쓸 수 없습니다. 포스트잇을 항상 표시합니다.")
            self._config.display["show_on_start"] = True

        window = self._config.window
        self.note.restore_position(window.get("x"), window.get("y"))

        if self._config.display.get("show_on_start", True):
            self.show_note()

        self.scheduler.start()
        self.refresh()

        if not self._is_ready():
            self.open_settings()

    def _is_ready(self) -> bool:
        return bool(secrets_store.get_key()) and self._config.is_configured

    def _apply_display(self) -> None:
        display = self._config.display
        color = display.get("color", "yellow")
        self.note.apply_color(color)
        self.note.setWindowOpacity(float(display.get("opacity", 0.95)))
        self.note.set_always_on_top(bool(display.get("always_on_top", True)))
        self.tray.set_color(color)
        school = self._config.school
        self.tray.set_school_name(school.get("school_name", "") if school else "")

    # ---------------------------------------------------------------- 창 조작

    def show_note(self) -> None:
        self.note.show()
        self.note.raise_()
        self.note.ensure_on_screen()
        self.tray.set_note_visible(True)

    def hide_note(self) -> None:
        self.note.hide()
        self.tray.set_note_visible(False)

    def toggle_note(self) -> None:
        if self.note.isVisible():
            self.hide_note()
        else:
            self.show_note()

    def _on_position_changed(self, x: int, y: int) -> None:
        self._config.window["x"] = x
        self._config.window["y"] = y
        self._config.save()

    # ---------------------------------------------------------------- 조회

    def refresh(self, force: bool = False) -> None:
        if not self._is_ready():
            self._show_message(
                "설정이 필요해요",
                "📌",
                detail="트레이 아이콘을 눌러 학교와 인증키를 등록해 주세요.",
                error=True,
            )
            return
        if self._fetching:
            return

        school = School.from_config(self._config.school or {})
        day = date.today()
        cached = cache.load(school.school_code, day)

        # 같은 날 캐시가 있으면 호출하지 않는다. 트래픽 한도를 아끼는 핵심 규칙이다.
        if cached and not force:
            self._render_rows(
                day,
                cached.get("meal_rows", []),
                cached.get("schedule_rows", []),
                footer=self._cache_footer(cached, stale=False),
            )
            self.tray.set_error(False)
            return

        if cached:  # 새로 받아오는 동안 빈 화면을 보이지 않는다
            self._render_rows(
                day,
                cached.get("meal_rows", []),
                cached.get("schedule_rows", []),
                footer="새로고침 중...",
            )

        self._fetching = True
        meal_keys = list(self._config.display.get("meal_types", ["lunch"]))
        submit(
            self._client.fetch_day,
            school,
            day,
            meal_keys,
            on_ok=lambda result: self._on_fetched(school, day, result),
            on_err=lambda exc: self._on_fetch_failed(school, day, exc),
        )

    def _on_fetched(
        self, school: School, day: date, result: tuple[list[dict], list[dict]]
    ) -> None:
        self._fetching = False
        meal_rows, schedule_rows = result
        cache.save(school.school_code, day, meal_rows, schedule_rows)

        self._config.state["last_sync"] = (
            datetime.now().astimezone().isoformat(timespec="seconds")
        )
        self._config.save()

        self._render_rows(
            day,
            meal_rows,
            schedule_rows,
            footer=f"{datetime.now():%H:%M} 갱신됨",
        )
        self.tray.set_error(False)

    def _on_fetch_failed(self, school: School, day: date, error: Exception) -> None:
        self._fetching = False
        kind = error.kind if isinstance(error, NeisError) else ResultKind.UNKNOWN
        log.info("조회 실패 (%s): %s", kind.value, error)

        cached = cache.load(school.school_code, day)
        if cached:
            # 마지막으로 성공한 내용을 계속 보여준다 (PRD F-08)
            self._render_rows(
                day,
                cached.get("meal_rows", []),
                cached.get("schedule_rows", []),
                footer=self._cache_footer(cached, stale=True),
            )
        else:
            self._show_message(
                _FAILURE_TEXT.get(kind, _FAILURE_TEXT[ResultKind.UNKNOWN]),
                "⚠️",
                detail=str(error),
                error=True,
            )
        self.tray.set_error(True)

    # ---------------------------------------------------------------- 렌더링

    def _render_rows(
        self,
        day: date,
        meal_rows: list[dict],
        schedule_rows: list[dict],
        footer: str = "",
    ) -> None:
        display = self._config.display
        wanted = set(display.get("meal_types", ["lunch"]))
        grade = display.get("grade_filter")

        meals: list[MealMenu] = [
            meal for meal in parse_meals(meal_rows) if meal.meal_key in wanted
        ]
        events: list[ScheduleEvent] = [
            event for event in parse_schedule(schedule_rows) if event.applies_to(grade)
        ]

        if not meals and not events:
            self._show_message("오늘은 급식이 없어요", "🌙", footer=footer)
            return

        self.note.render_view(
            NoteView(
                day=day,
                meals=meals,
                events=events,
                meal_note="🌙 오늘은 급식이 없어요",
                footer=footer,
                show_allergy=bool(display.get("show_allergy", False)),
                show_calorie=bool(display.get("show_calorie", True)),
                show_origin=bool(display.get("show_origin", False)),
            )
        )

    def _show_message(
        self,
        message: str,
        icon: str = "📌",
        detail: str = "",
        footer: str = "",
        error: bool = False,
    ) -> None:
        text = f"{message}\n{detail}" if detail else message
        self.note.render_view(
            NoteView(day=date.today(), message=text, message_icon=icon, footer=footer)
        )
        if error:
            self.tray.set_error(True)

    @staticmethod
    def _cache_footer(cached: dict, stale: bool) -> str:
        saved_at = cached.get("saved_at", "")
        try:
            stamp = datetime.fromisoformat(saved_at)
            when = f"{stamp:%m-%d %H:%M}"
        except (TypeError, ValueError):
            when = "이전"
        return f"오프라인 · {when} 기준" if stale else f"{when} 기준"

    # ---------------------------------------------------------------- 설정 창

    def open_settings(self) -> None:
        if self._dialog is not None and self._dialog.isVisible():
            self._dialog.raise_()
            self._dialog.activateWindow()
            return

        dialog = SettingsDialog(self._config)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dialog.saved.connect(self._on_settings_saved)
        dialog.destroyed.connect(self._on_dialog_closed)
        self._dialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _on_dialog_closed(self) -> None:
        self._dialog = None

    def _on_settings_saved(self) -> None:
        self._apply_display()
        self.show_note()
        self.refresh(force=True)

    def show_about(self) -> None:
        QMessageBox.information(
            None,
            f"{APP_DISPLAY_NAME} 정보",
            f"<b>{APP_DISPLAY_NAME}</b> (SchoolNote) v{VERSION}<br><br>"
            "오늘의 급식과 학사일정을 포스트잇처럼 보여주는 위젯입니다.<br><br>"
            "데이터 출처: 교육부 NEIS 교육정보 개방 포털<br>"
            "<a href='https://open.neis.go.kr'>open.neis.go.kr</a>",
        )

    # ---------------------------------------------------------------- 종료

    def quit(self) -> None:
        self.scheduler.stop()
        if self.note.isVisible():
            self._config.window["x"] = self.note.x()
            self._config.window["y"] = self.note.y()
        self._config.save()
        self.tray.hide()
        self._app.quit()
