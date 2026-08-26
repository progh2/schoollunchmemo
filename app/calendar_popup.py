"""달력 팝업.

포스트잇의 날짜를 누르면 열린다. `‹ ›` 로 하루씩 넘기는 것만으로는 며칠 뒤를
보려면 여러 번 눌러야 하므로, 한 달을 펼쳐 놓고 바로 고르게 한다.

달력에는 그 달에 급식이 있는 날과 일정이 있는 날을 표시한다. 급식은 조식·중식·
석식 중 무엇이 나오는지까지 보인다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from PySide6.QtCore import QDate, QPoint, Qt, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QTextCharFormat
from PySide6.QtWidgets import (
    QCalendarWidget,
    QFrame,
    QLabel,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from .neis.models import MEAL_TYPE_LABELS
from .resources.theme import colors

#: 급식 표시 색. 검증된 범주 팔레트의 1~3번 색이다. 네 가지 종이색 배경
#: 모두에서 색약 구분(ΔE 9.2 ≥ 8)과 정상시야 구분(ΔE 24.0 ≥ 15)을 통과한다.
#: 배경 대비는 3:1 아래이므로 자리 고정과 범례로 보완한다.
MEAL_COLORS: dict[str, str] = {
    "breakfast": "#2a78d6",
    "lunch": "#eb6834",
    "dinner": "#1baf7a",
}

#: 점을 찍는 자리는 고정이다. 첫 칸이 조식, 둘째가 중식, 셋째가 석식.
#: 빈 칸은 그 급식이 없다는 뜻이라, 색을 구별하지 못해도 자리로 읽을 수 있다.
MEAL_SLOTS: tuple[str, ...] = ("breakfast", "lunch", "dinner")

#: 휴업일. 상태를 뜻하는 색이므로 급식 범주색과 섞어 쓰지 않는다.
HOLIDAY_COLOR = "#d03b3b"

DOT_SIZE = 5
DOT_GAP = 3
BAR_WIDTH = 13
BAR_HEIGHT = 2
#: 기본 칸 높이(24px)로는 숫자 아래에 표시를 넣을 자리가 없어 표시가 숫자를
#: 관통한다. 칸을 늘려서 가운데 정렬된 숫자와 아래쪽 표시를 갈라 놓는다.
ROW_HEIGHT = 38
WEEK_ROWS = 6  # 달력에 늘 그려지는 주 수


@dataclass(frozen=True)
class DayMarks:
    """달력 한 칸에 그릴 것. 컨트롤러가 한 달치를 만들어 넘긴다."""

    meal_keys: frozenset[str] = frozenset()
    events: tuple[str, ...] = ()
    is_holiday: bool = False

    @property
    def is_empty(self) -> bool:
        return not self.meal_keys and not self.events


class MarkedCalendar(QCalendarWidget):
    """급식·일정 표시를 칸마다 그리는 달력.

    `setDateTextFormat`으로는 글자 서식만 바꿀 수 있어 점을 찍을 수 없다.
    그래서 휴업일 글자색만 서식으로 두고, 표시는 `paintCell`에서 직접 그린다.
    """

    def __init__(self, color: str = "yellow", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._marks: dict[date, DayMarks] = {}
        self._palette = colors(color)

        self.setGridVisible(False)
        self.setVerticalHeaderFormat(
            QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader
        )
        self.setFirstDayOfWeek(Qt.DayOfWeek.Sunday)

        view = self.findChild(QTableView)
        if view is not None:
            # 칸 높이는 직접 정할 수 없다. 내부 표는 세로 헤더가 Stretch라
            # defaultSectionSize를 무시하고 뷰 높이를 주 수로 나눠 쓴다.
            # 그래서 6주치가 들어갈 최소 높이를 잡아 칸을 키운다.
            view.setMinimumHeight(
                view.horizontalHeader().sizeHint().height() + WEEK_ROWS * ROW_HEIGHT
            )
            # 달력 자신의 최소 높이도 같이 올린다. QCalendarWidget은 내부 표의
            # 최소 높이를 자기 크기 힌트에 반영하지 않아, 이걸 빼먹으면 표가
            # 잘린 채로 팝업이 뜬다.
            navbar = self.findChild(QWidget, "qt_calendar_navigationbar")
            self.setMinimumHeight(
                view.minimumHeight()
                + (navbar.sizeHint().height() if navbar is not None else 0)
            )

        self.apply_color(color)

    def set_marks(self, marks: dict[date, DayMarks]) -> None:
        self._marks = dict(marks)

        # 휴업일은 글자색으로도 알린다. 점만으로는 쉬는 날인지 알 수 없다.
        self.setDateTextFormat(QDate(), QTextCharFormat())  # 빈 날짜 = 전체 초기화
        holiday = QTextCharFormat()
        holiday.setForeground(QColor(HOLIDAY_COLOR))
        holiday.setFontWeight(QFont.Weight.Bold)
        for day, mark in self._marks.items():
            if mark.is_holiday:
                self.setDateTextFormat(QDate(day.year, day.month, day.day), holiday)

        self.updateCells()

    def marks_for(self, day: date) -> DayMarks | None:
        return self._marks.get(day)

    def apply_color(self, color: str) -> None:
        self._palette = colors(color)
        # 주말은 Qt 기본값이 빨강이라 휴업일 빨강과 헷갈린다. 빨강은 휴업일
        # 몫으로 남기고, 주말은 옅은 글자색으로만 구분한다.
        weekend = QTextCharFormat()
        weekend.setForeground(QColor(self._palette["muted"]))
        for weekday in (Qt.DayOfWeek.Saturday, Qt.DayOfWeek.Sunday):
            self.setWeekdayTextFormat(weekday, weekend)
        self.updateCells()

    def paintCell(self, painter: QPainter, rect, qdate: QDate) -> None:  # noqa: N802
        super().paintCell(painter, rect, qdate)

        # 앞뒤 달에서 넘어온 칸에는 표시하지 않는다. 그 달 자료가 아니다.
        if qdate.month() != self.monthShown() or qdate.year() != self.yearShown():
            return
        mark = self._marks.get(qdate.toPython())
        if mark is None or mark.is_empty:
            return

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)

        dot_y = rect.bottom() - DOT_SIZE - 1
        span = len(MEAL_SLOTS) * DOT_SIZE + (len(MEAL_SLOTS) - 1) * DOT_GAP
        x = rect.center().x() - span // 2
        for key in MEAL_SLOTS:
            if key in mark.meal_keys:
                painter.setBrush(QColor(MEAL_COLORS[key]))
                painter.drawEllipse(x, dot_y, DOT_SIZE, DOT_SIZE)
            x += DOT_SIZE + DOT_GAP

        if mark.events:
            # 일정은 색이 아니라 모양으로 구분한다. 숫자 아래 짧은 밑줄.
            painter.setBrush(
                QColor(HOLIDAY_COLOR if mark.is_holiday else self._palette["accent"])
            )
            painter.drawRoundedRect(
                rect.center().x() - BAR_WIDTH // 2,
                dot_y - BAR_HEIGHT - 2,
                BAR_WIDTH,
                BAR_HEIGHT,
                1,
                1,
            )

        painter.restore()


class CalendarPopup(QWidget):
    """달력을 담은 팝업. 바깥을 누르면 닫힌다."""

    dateSelected = Signal(object)  # datetime.date
    monthShown = Signal(int, int)  # 연, 월 — 그 달 자료가 필요하다는 뜻

    def __init__(self, color: str = "yellow", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self.card = QFrame(self)
        self.card.setObjectName("calendarCard")
        outer.addWidget(self.card)

        inner = QVBoxLayout(self.card)
        inner.setContentsMargins(8, 8, 8, 6)
        inner.setSpacing(4)

        self.calendar = MarkedCalendar(color, self.card)
        self.calendar.clicked.connect(self._on_clicked)
        self.calendar.currentPageChanged.connect(self.monthShown)
        inner.addWidget(self.calendar)

        self.legend = QLabel(self.card)
        self.legend.setObjectName("legend")
        self.legend.setTextFormat(Qt.TextFormat.RichText)
        inner.addWidget(self.legend)

        self._legend_html = ""
        self.apply_color(color)

    # ------------------------------------------------------------------ 표시

    def apply_color(self, color: str) -> None:
        palette = colors(color)
        self.calendar.apply_color(color)
        self.card.setStyleSheet(
            f"""
            QFrame#calendarCard {{
                background: {palette['bg']};
                border: 1px solid {palette['line']};
                border-radius: 8px;
            }}
            QLabel#legend {{ color: {palette['muted']}; font-size: 8pt; }}
            QCalendarWidget QAbstractItemView:enabled {{
                background: {palette['bg']};
                color: {palette['text']};
                selection-background-color: {palette['line']};
                selection-color: {palette['text']};
                outline: none;
            }}
            QCalendarWidget QWidget#qt_calendar_navigationbar {{
                background: {palette['bg']};
            }}
            QCalendarWidget QToolButton {{
                color: {palette['text']};
                background: transparent;
                border: none;
                font-size: 9pt;
            }}
            QCalendarWidget QToolButton:hover {{ color: {palette['accent']}; }}
            QCalendarWidget QSpinBox {{ color: {palette['text']}; }}
            """
        )
        # 색만으로 구분하지 않도록 범례를 항상 함께 둔다 (자리 + 색 + 이름)
        dots = " ".join(
            f"<span style='color:{MEAL_COLORS[key]}'>●</span>"
            f" {MEAL_TYPE_LABELS[key]}"
            for key in MEAL_SLOTS
        )
        self._legend_html = (
            f"{dots} &nbsp;<span style='color:{palette['accent']}'>▬</span> 일정"
        )
        self.legend.setText(self._legend_html)

    def set_marks(self, marks: dict[date, DayMarks]) -> None:
        self.calendar.set_marks(marks)

    def set_status(self, text: str) -> None:
        """범례 자리에 상황을 알린다. 빈 문자열이면 범례로 되돌린다."""
        self.legend.setText(text or self._legend_html)

    def year_shown(self) -> int:
        return self.calendar.yearShown()

    def month_shown(self) -> int:
        return self.calendar.monthShown()

    # ------------------------------------------------------------------ 열기

    def show_at(self, day: date, anchor: QPoint) -> None:
        """anchor(전역 좌표) 아래에 펼친다. 화면을 벗어나면 안쪽으로 당긴다."""
        self.calendar.setSelectedDate(QDate(day.year, day.month, day.day))
        self.calendar.setCurrentPage(day.year, day.month)

        self.adjustSize()
        target = QPoint(anchor)
        screen = QGuiApplication.screenAt(anchor) or QGuiApplication.primaryScreen()
        if screen is not None:
            bounds = screen.availableGeometry()
            target.setX(
                max(bounds.left(), min(target.x(), bounds.right() - self.width()))
            )
            if target.y() + self.height() > bounds.bottom():
                # 아래가 좁으면 위로 뒤집는다
                target.setY(max(bounds.top(), anchor.y() - self.height()))
        self.move(target)
        self.show()
        self.raise_()

    def _on_clicked(self, qdate: QDate) -> None:
        self.hide()
        self.dateSelected.emit(qdate.toPython())
