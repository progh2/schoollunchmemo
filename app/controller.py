"""앱 전체를 엮는 컨트롤러.

포스트잇·트레이·설정 창·스케줄러를 소유하고, 조회 흐름과 상태 표시를 결정한다.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from PySide6.QtCore import QObject, QPoint, Qt
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from . import autostart, cache, secrets_store
from .calendar_popup import CalendarPopup, DayMarks
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

#: 앞뒤로 이동할 수 있는 최대 일수. 이보다 멀면 NEIS에도 자료가 없다.
MAX_DAY_OFFSET = 365


class AppController(QObject):
    def __init__(self, app: QApplication) -> None:
        super().__init__()
        self._app = app
        self._config = Config.load()
        self._client = NeisClient(secrets_store.get_key)
        self._dialog: SettingsDialog | None = None
        self._calendar: CalendarPopup | None = None
        self._view_day = date.today()  # 지금 보고 있는 날
        self._inflight: set[date] = set()
        self._month_inflight: set[tuple[int, int]] = set()

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
        self.note.dateStepped.connect(self.step_day)
        self.note.todayRequested.connect(self.go_today)
        self.note.calendarRequested.connect(self.open_calendar)

        self.tray.toggleRequested.connect(self.toggle_note)
        self.tray.refreshRequested.connect(lambda: self.refresh(force=True))
        self.tray.settingsRequested.connect(self.open_settings)
        self.tray.aboutRequested.connect(self.show_about)
        self.tray.quitRequested.connect(self.quit)

        self.scheduler.dayChanged.connect(self._on_day_changed)

    # ---------------------------------------------------------------- 시작

    def start(self) -> None:
        cache.prune()
        self._apply_display()
        self._sync_autostart()

        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()
        else:
            # 트레이가 없으면 앱에 접근할 방법이 사라진다 (PRD T-07)
            log.warning("시스템 트레이를 쓸 수 없습니다. 포스트잇을 항상 표시합니다.")
            self._config.display["show_on_start"] = True

        # 내용을 먼저 채운 뒤 띄운다. 빈 창이 떴다가 커지는 것을 막는다.
        self.scheduler.start()
        self.refresh()

        window = self._config.window
        self.note.restore_position(window.get("x"), window.get("y"))
        if self._config.display.get("show_on_start", True):
            self.show_note()

        if not self._is_ready():
            self.open_settings()

    def _is_ready(self) -> bool:
        return bool(secrets_store.get_key()) and self._config.is_configured

    def _sync_autostart(self) -> None:
        """설정과 OS의 자동 시작 등록을 맞춘다.

        실행 파일을 옮겼거나 다른 도구가 항목을 지웠을 수 있으므로
        실행할 때마다 확인한다. 이미 맞으면 아무것도 쓰지 않는다.
        """
        if not autostart.is_supported():
            return
        if not autostart.set_enabled(
            bool(self._config.display.get("start_on_boot", False))
        ):
            log.info("자동 시작 상태를 맞추지 못했습니다.")

    def _apply_display(self) -> None:
        display = self._config.display
        color = display.get("color", "yellow")
        self.note.apply_color(color)
        self.note.setWindowOpacity(float(display.get("opacity", 0.95)))
        self.note.set_always_on_top(bool(display.get("always_on_top", True)))
        self.note.set_details_default(bool(display.get("expand_details", False)))
        self.tray.set_color(color)
        school = self._config.school
        self.tray.set_school_name(school.get("school_name", "") if school else "")

    # ---------------------------------------------------------------- 날짜 이동

    def step_day(self, delta: int) -> None:
        target = self._view_day + timedelta(days=delta)
        if abs((target - date.today()).days) > MAX_DAY_OFFSET:
            return
        self._view_day = target
        self.refresh()

    def go_today(self) -> None:
        if self._view_day == date.today():
            return
        self._view_day = date.today()
        self.refresh()

    def go_day(self, day: date) -> None:
        """달력에서 고른 날로 옮긴다."""
        if abs((day - date.today()).days) > MAX_DAY_OFFSET or day == self._view_day:
            return
        self._view_day = day
        self.refresh()

    def _on_day_changed(self) -> None:
        # 자정을 넘겼으면 무엇을 보고 있었든 오늘로 되돌린다
        self._view_day = date.today()
        self.refresh(force=True)

    # ---------------------------------------------------------------- 창 조작

    def show_note(self) -> None:
        # 다시 꺼낼 때는 언제나 오늘부터 본다
        if self._view_day != date.today():
            self._view_day = date.today()
            self.refresh()
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

        school = School.from_config(self._config.school or {})
        day = self._view_day
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
        else:
            self._show_message("불러오는 중...", "⏳", footer="")

        if day in self._inflight:  # 같은 날을 두 번 부르지 않는다
            return
        self._inflight.add(day)
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
        self._inflight.discard(day)
        meal_rows, schedule_rows = result
        cache.save(school.school_code, day, meal_rows, schedule_rows)

        self._config.state["last_sync"] = (
            datetime.now().astimezone().isoformat(timespec="seconds")
        )
        self._config.save()

        self.tray.set_error(False)
        if day != self._view_day:
            # 응답을 기다리는 사이 다른 날로 옮겨갔다. 화면은 건드리지 않는다.
            return

        self._render_rows(
            day,
            meal_rows,
            schedule_rows,
            footer=f"{datetime.now():%H:%M} 갱신됨",
        )

    def _on_fetch_failed(self, school: School, day: date, error: Exception) -> None:
        self._inflight.discard(day)
        kind = error.kind if isinstance(error, NeisError) else ResultKind.UNKNOWN
        log.info("조회 실패 (%s): %s", kind.value, error)
        self.tray.set_error(True)
        if day != self._view_day:
            return

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

    # ---------------------------------------------------------------- 달력

    def open_calendar(self, anchor: QPoint) -> None:
        if not self._is_ready():
            # 학교도 인증키도 없으면 표시할 것이 없다. 설정으로 안내한다.
            self.open_settings()
            return

        color = self._config.display.get("color", "yellow")
        if self._calendar is None:
            popup = CalendarPopup(color, self.note)
            popup.dateSelected.connect(self.go_day)
            popup.monthShown.connect(self.load_month)
            self._calendar = popup
        else:
            self._calendar.apply_color(color)

        self._calendar.show_at(self._view_day, anchor)
        # setCurrentPage가 같은 달이면 신호를 내지 않으므로 여기서도 부른다.
        self.load_month(self._view_day.year, self._view_day.month)

    def load_month(self, year: int, month: int) -> None:
        """달력에 찍을 한 달치 표시를 준비한다. 캐시가 있으면 부르지 않는다."""
        if self._calendar is None or not self._is_ready():
            return

        school = School.from_config(self._config.school or {})
        cached = cache.load_month(school.school_code, year, month)
        if cached:
            self._calendar.set_marks(self._marks_from_cached(cached))
            # 다 지나간 달은 자료가 더 바뀌지 않는다. 이번 달과 앞날은 하루에 한 번만.
            if self._month_is_past(year, month) or cache.saved_today(cached):
                return

        key = (year, month)
        if key in self._month_inflight:
            return
        self._month_inflight.add(key)
        if not cached:
            self._calendar.set_status("표시를 불러오는 중...")
        submit(
            self._client.fetch_month_rows,
            school,
            year,
            month,
            on_ok=lambda result: self._on_month_fetched(school, year, month, result),
            on_err=lambda exc: self._on_month_failed(year, month, exc),
        )

    def _on_month_fetched(
        self, school: School, year: int, month: int, result: tuple[list, list]
    ) -> None:
        self._month_inflight.discard((year, month))
        meal_rows, schedule_rows = result
        cache.save_month(school.school_code, year, month, meal_rows, schedule_rows)
        if self._calendar is None:
            return
        # 응답을 기다리는 사이 다른 달로 넘겼으면 화면은 건드리지 않는다
        if (self._calendar.year_shown(), self._calendar.month_shown()) != (year, month):
            return
        self._calendar.set_status("")
        self._calendar.set_marks(self._marks_from_rows(meal_rows, schedule_rows))

    def _on_month_failed(self, year: int, month: int, error: Exception) -> None:
        self._month_inflight.discard((year, month))
        log.info("달력 표시를 가져오지 못했습니다 (%d-%02d): %s", year, month, error)
        if self._calendar is None:
            return
        if (self._calendar.year_shown(), self._calendar.month_shown()) == (year, month):
            self._calendar.set_status("표시를 가져오지 못했어요")

    @staticmethod
    def _month_is_past(year: int, month: int) -> bool:
        today = date.today()
        return (year, month) < (today.year, today.month)

    def _marks_from_cached(self, cached: dict) -> dict[date, DayMarks]:
        return self._marks_from_rows(
            cached.get("meal_rows", []), cached.get("schedule_rows", [])
        )

    def _marks_from_rows(
        self, meal_rows: list[dict], schedule_rows: list[dict]
    ) -> dict[date, DayMarks]:
        """달력 표시를 만든다.

        급식은 표시 설정으로 걸러내지 않는다. 달력의 목적이 "그날 무엇이
        나오는지" 알려주는 것이므로, 중식만 보도록 해 둔 사람에게도 조식·석식이
        있다는 사실은 알려 주어야 한다. 일정은 포스트잇과 같은 학년 필터를 쓴다.
        """
        grade = self._config.display.get("grade_filter")

        meals: dict[date, set[str]] = {}
        for meal in parse_meals(meal_rows):
            meals.setdefault(meal.day, set()).add(meal.meal_key)

        events: dict[date, list[str]] = {}
        holidays: set[date] = set()
        for event in parse_schedule(schedule_rows):
            if not event.applies_to(grade):
                continue
            events.setdefault(event.day, []).append(event.name)
            if event.is_holiday:
                holidays.add(event.day)

        return {
            day: DayMarks(
                meal_keys=frozenset(meals.get(day, ())),
                events=tuple(events.get(day, ())),
                is_holiday=day in holidays,
            )
            for day in set(meals) | set(events)
        }

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

        # 급식이 없는 날인지 학교가 아직 안 올린 것인지 NEIS는 구분해 주지
        # 않는다. "급식이 없다"고 단정하면 오해를 부르므로 미등록으로 알린다.
        no_meal = "급식 정보가 등록되지 않았어요"

        if not meals and not events:
            self._show_message(
                no_meal,
                "📭",
                detail="학교에서 아직 올리지 않았을 수 있어요.",
                footer=footer,
                day=day,
            )
            return

        self.note.render_view(
            NoteView(
                day=day,
                is_today=day == date.today(),
                meals=meals,
                events=events,
                meal_note=f"📭 {no_meal}",
                footer=footer,
                show_allergy=bool(display.get("show_allergy", False)),
                show_calorie=bool(display.get("show_calorie", True)),
                allergy_alerts=frozenset(
                    int(code)
                    for code in display.get("allergy_alerts", [])
                    if str(code).isdigit()
                ),
            )
        )

    def _show_message(
        self,
        message: str,
        icon: str = "📌",
        detail: str = "",
        footer: str = "",
        error: bool = False,
        day: date | None = None,
    ) -> None:
        shown = day or self._view_day
        text = f"{message}\n{detail}" if detail else message
        self.note.render_view(
            NoteView(
                day=shown,
                is_today=shown == date.today(),
                message=text,
                message_icon=icon,
                footer=footer,
            )
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

    def open_settings(self, tab: str = "") -> None:
        if self._dialog is not None and self._dialog.isVisible():
            self._dialog.show_tab(tab)
            self._dialog.raise_()
            self._dialog.activateWindow()
            return

        dialog = SettingsDialog(self._config)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dialog.saved.connect(self._on_settings_saved)
        dialog.destroyed.connect(self._on_dialog_closed)
        self._dialog = dialog
        dialog.show_tab(tab)
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
        """정보는 설정 창의 '정보' 탭에 모아 둔다. 같은 내용을 두 곳에 두지 않는다."""
        self.open_settings("info")

    # ---------------------------------------------------------------- 종료

    def quit(self) -> None:
        self.scheduler.stop()
        if self.note.isVisible():
            self._config.window["x"] = self.note.x()
            self._config.window["y"] = self.note.y()
        self._config.save()
        self.tray.hide()
        self._app.quit()
