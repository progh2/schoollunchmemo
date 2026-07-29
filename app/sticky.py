"""포스트잇 위젯.

제목표시줄 없는 창을 바탕화면에 붙여둔다. 어느 상황에서도 빈 화면을 보이지
않는 것이 이 위젯의 계약이다 (PRD 4.2). 표시할 내용이 없으면 상태 문구를 띄운다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from html import escape

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QAction, QGuiApplication, QMouseEvent
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .neis.models import MealMenu, ScheduleEvent
from .resources.theme import colors

NOTE_WIDTH = 280
MAX_DISHES = 15
_WEEKDAYS = ("월", "화", "수", "목", "금", "토", "일")
_RELATIVE_LABELS = {-2: "그저께", -1: "어제", 0: "오늘", 1: "내일", 2: "모레"}


def _relative_label(day: date) -> str:
    """오늘 기준 며칠 차이인지. 멀리 떨어진 날은 날짜만으로 충분하다."""
    return _RELATIVE_LABELS.get((day - date.today()).days, "")


@dataclass
class NoteView:
    """포스트잇에 그릴 내용. 컨트롤러가 만들어 넘긴다."""

    day: date
    meals: list[MealMenu] = field(default_factory=list)
    events: list[ScheduleEvent] = field(default_factory=list)
    message: str = ""
    message_icon: str = "📌"
    meal_note: str = ""  # 급식만 없을 때 일정 위에 덧붙이는 한 줄
    footer: str = ""
    is_today: bool = True
    show_allergy: bool = False
    show_calorie: bool = True
    show_origin: bool = False


class StickyNote(QWidget):
    refreshRequested = Signal()
    settingsRequested = Signal()
    hideRequested = Signal()
    quitRequested = Signal()
    positionChanged = Signal(int, int)
    dateStepped = Signal(int)  # -1 = 이전 날, +1 = 다음 날
    todayRequested = Signal()

    def __init__(self, color: str = "yellow", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = color
        self._drag_offset: QPoint | None = None

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool  # 작업표시줄·Alt+Tab에 뜨지 않게
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedWidth(NOTE_WIDTH)

        self._build_ui()
        self.apply_color(color)

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 14, 14)  # 그림자 여백

        self.card = QFrame(self)
        self.card.setObjectName("card")
        shadow = QGraphicsDropShadowEffect(self.card)
        shadow.setBlurRadius(24)
        shadow.setOffset(2, 4)
        shadow.setColor(Qt.GlobalColor.darkGray)
        self.card.setGraphicsEffect(shadow)
        outer.addWidget(self.card)

        inner = QVBoxLayout(self.card)
        inner.setContentsMargins(16, 12, 16, 12)
        inner.setSpacing(6)

        header = QHBoxLayout()
        header.setSpacing(2)

        self.prev_button = self._tool_button("‹", "이전 날 (휠을 굴려도 됩니다)")
        self.prev_button.clicked.connect(lambda: self.dateStepped.emit(-1))
        header.addWidget(self.prev_button)

        self.date_label = QLabel(self.card)
        self.date_label.setObjectName("date")
        self.date_label.setTextFormat(Qt.TextFormat.RichText)
        header.addWidget(self.date_label)

        self.next_button = self._tool_button("›", "다음 날")
        self.next_button.clicked.connect(lambda: self.dateStepped.emit(1))
        header.addWidget(self.next_button)

        header.addStretch(1)

        # 다른 날을 보고 있을 때만 나타난다. 돌아올 길을 항상 열어둔다.
        self.today_button = QPushButton("오늘", self.card)
        self.today_button.setObjectName("chip")
        self.today_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.today_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.today_button.setFlat(True)
        self.today_button.setFixedHeight(22)
        self.today_button.clicked.connect(self.todayRequested)
        self.today_button.hide()
        header.addWidget(self.today_button)

        self.refresh_button = self._tool_button("⟳", "지금 새로고침")
        self.refresh_button.clicked.connect(self.refreshRequested)
        header.addWidget(self.refresh_button)

        self.hide_button = self._tool_button("✕", "숨기기 (트레이에 남아 있어요)")
        self.hide_button.clicked.connect(self.hideRequested)
        header.addWidget(self.hide_button)
        inner.addLayout(header)

        self.rule = QFrame(self.card)
        self.rule.setObjectName("rule")
        self.rule.setFixedHeight(1)
        inner.addWidget(self.rule)

        self.body = QLabel(self.card)
        self.body.setObjectName("body")
        self.body.setWordWrap(True)
        self.body.setTextFormat(Qt.TextFormat.RichText)
        self.body.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        inner.addWidget(self.body)

        self.footer_label = QLabel(self.card)
        self.footer_label.setObjectName("footer")
        self.footer_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        inner.addWidget(self.footer_label)

        self._set_buttons_visible(False)

    def _tool_button(self, text: str, tooltip: str) -> QPushButton:
        button = QPushButton(text, self.card)
        button.setObjectName("tool")
        button.setToolTip(tooltip)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFixedSize(22, 22)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setFlat(True)
        return button

    def _set_buttons_visible(self, visible: bool) -> None:
        self.prev_button.setVisible(visible)
        self.next_button.setVisible(visible)
        self.refresh_button.setVisible(visible)
        self.hide_button.setVisible(visible)

    def apply_color(self, color: str) -> None:
        self._color = color
        palette = colors(color)
        self.card.setStyleSheet(
            f"""
            QFrame#card {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {palette['bg']}, stop:1 {palette['bg_bottom']});
                border: 1px solid {palette['line']};
                border-radius: 10px;
            }}
            QLabel#date {{
                color: {palette['text']};
                font-size: 11pt;
                font-weight: 600;
            }}
            QFrame#rule {{ background: {palette['line']}; border: none; }}
            QLabel#body {{ color: {palette['text']}; font-size: 10pt; }}
            QLabel#footer {{ color: {palette['muted']}; font-size: 8pt; }}
            QPushButton#tool {{
                color: {palette['muted']};
                border: none;
                background: transparent;
                font-size: 11pt;
            }}
            QPushButton#tool:hover {{ color: {palette['accent']}; }}
            QPushButton#chip {{
                color: {palette['accent']};
                border: 1px solid {palette['line']};
                border-radius: 9px;
                background: transparent;
                padding: 0 8px;
                font-size: 8pt;
            }}
            QPushButton#chip:hover {{ border-color: {palette['accent']}; }}
            """
        )

    # -------------------------------------------------------------- 내용 렌더

    def render_view(self, view: NoteView) -> None:
        palette = colors(self._color)
        text = (
            f"{view.day.month}월 {view.day.day}일 "
            f"({_WEEKDAYS[view.day.weekday()]})"
        )
        relative = _relative_label(view.day)
        if relative and not view.is_today:
            text += (
                f"<span style='color:{palette['accent']}; font-size:9pt'>"
                f" · {relative}</span>"
            )
        self.date_label.setText(text)
        self.today_button.setVisible(not view.is_today)
        self.body.setText(self._build_html(view))
        self.footer_label.setText(view.footer)
        self.footer_label.setVisible(bool(view.footer))
        self.body.adjustSize()
        self.adjustSize()

    def _build_html(self, view: NoteView) -> str:
        palette = colors(self._color)
        blocks: list[str] = []

        if view.message:
            blocks.append(
                f"<p style='margin:8px 0 4px 0; font-size:14pt'>"
                f"{escape(view.message_icon)}</p>"
                f"<p style='margin:0; color:{palette['text']}'>"
                f"{escape(view.message)}</p>"
            )
            return "".join(blocks)

        for meal in view.meals:
            blocks.append(self._meal_html(meal, view, palette))

        if not view.meals and view.meal_note:
            blocks.append(
                f"<p style='margin:6px 0 0 0; color:{palette['muted']}'>"
                f"{escape(view.meal_note)}</p>"
            )

        if view.events:
            blocks.append(
                f"<p style='margin:10px 0 2px 0; font-weight:600;"
                f" color:{palette['muted']}'>📌 오늘 일정</p>"
            )
            for event in view.events:
                color = palette["accent"] if event.is_holiday else palette["text"]
                line = f"<span style='color:{color}'>{escape(event.name)}</span>"
                grade = event.grade_label
                if grade:
                    line += (
                        f"<span style='color:{palette['muted']}'>"
                        f" · {escape(grade)}</span>"
                    )
                blocks.append(f"<p style='margin:0 0 1px 0'>{line}</p>")

        if not blocks:
            blocks.append(
                f"<p style='margin:8px 0 0 0; color:{palette['muted']}'>"
                f"오늘은 표시할 내용이 없어요.</p>"
            )
        return "".join(blocks)

    def _meal_html(
        self, meal: MealMenu, view: NoteView, palette: dict[str, str]
    ) -> str:
        parts = [
            f"<p style='margin:6px 0 2px 0; font-weight:600;"
            f" color:{palette['muted']}'>🍚 {escape(meal.label)}</p>"
        ]
        dishes = meal.dishes[:MAX_DISHES]
        for dish in dishes:
            parts.append(
                f"<p style='margin:0 0 1px 0'>"
                f"{escape(dish.display(view.show_allergy))}</p>"
            )
        if len(meal.dishes) > MAX_DISHES:
            parts.append(
                f"<p style='margin:0; color:{palette['muted']}'>"
                f"외 {len(meal.dishes) - MAX_DISHES}가지</p>"
            )
        if view.show_calorie and meal.calorie:
            parts.append(
                f"<p style='margin:2px 0 0 0; color:{palette['muted']}'>"
                f"{meal.calorie:g} kcal</p>"
            )
        if view.show_origin and meal.origin:
            origin = escape(meal.origin).replace("\n", "<br/>")
            parts.append(
                f"<p style='margin:4px 0 0 0; font-size:8pt;"
                f" color:{palette['muted']}'>{origin}</p>"
            )
        return "".join(parts)

    # -------------------------------------------------------------- 창 동작

    def set_always_on_top(self, on_top: bool) -> None:
        was_visible = self.isVisible()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, on_top)
        if was_visible:
            self.show()  # 플래그 변경 후에는 다시 show 해야 반영된다

    def restore_position(self, x: int | None, y: int | None) -> None:
        if x is None or y is None:
            self._move_to_default()
        else:
            self.move(self._clamp(QPoint(int(x), int(y))))

    def _move_to_default(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        self.move(area.right() - self.width() - 40, area.top() + 60)

    def _clamp(self, point: QPoint) -> QPoint:
        """해상도·모니터 구성이 바뀌어도 화면 밖으로 나가지 않게 보정한다."""
        for screen in QGuiApplication.screens():
            if screen.availableGeometry().contains(point):
                area = screen.availableGeometry()
                break
        else:
            screen = QGuiApplication.primaryScreen()
            if screen is None:
                return point
            area = screen.availableGeometry()
            point = QPoint(area.left() + 40, area.top() + 60)

        x = max(area.left(), min(point.x(), area.right() - self.width()))
        y = max(area.top(), min(point.y(), area.bottom() - self.height()))
        return QPoint(x, y)

    def ensure_on_screen(self) -> None:
        self.move(self._clamp(self.pos()))

    # -------------------------------------------------------------- 이벤트

    def enterEvent(self, event) -> None:  # noqa: N802 - Qt 시그니처
        self._set_buttons_visible(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._set_buttons_visible(False)
        super().leaveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag_offset is not None:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag_offset is not None:
            self._drag_offset = None
            self.ensure_on_screen()
            self.positionChanged.emit(self.x(), self.y())
            event.accept()

    def wheelEvent(self, event) -> None:  # noqa: N802
        # 위로 굴리면 과거, 아래로 굴리면 미래
        delta = event.angleDelta().y()
        if delta:
            self.dateStepped.emit(-1 if delta > 0 else 1)
            event.accept()

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        menu = QMenu(self)

        previous = QAction("이전 날", menu)
        previous.triggered.connect(lambda: self.dateStepped.emit(-1))
        next_day = QAction("다음 날", menu)
        next_day.triggered.connect(lambda: self.dateStepped.emit(1))
        today = QAction("오늘로", menu)
        today.triggered.connect(self.todayRequested)
        menu.addAction(previous)
        menu.addAction(next_day)
        menu.addAction(today)
        menu.addSeparator()

        refresh = QAction("지금 새로고침", menu)
        refresh.triggered.connect(self.refreshRequested)
        settings = QAction("설정...", menu)
        settings.triggered.connect(self.settingsRequested)
        hide = QAction("숨기기", menu)
        hide.triggered.connect(self.hideRequested)
        quit_action = QAction("종료", menu)
        quit_action.triggered.connect(self.quitRequested)
        menu.addAction(refresh)
        menu.addAction(settings)
        menu.addSeparator()
        menu.addAction(hide)
        menu.addAction(quit_action)
        menu.exec(event.globalPos())

    def closeEvent(self, event) -> None:  # noqa: N802
        # 창을 닫아도 앱은 살아 있어야 한다 (T-06). 숨기기로 바꾼다.
        event.ignore()
        self.hideRequested.emit()
