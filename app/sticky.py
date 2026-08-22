"""포스트잇 위젯.

제목표시줄 없는 창을 바탕화면에 붙여둔다. 어느 상황에서도 빈 화면을 보이지
않는 것이 이 위젯의 계약이다 (PRD 4.2). 표시할 내용이 없으면 상태 문구를 띄운다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from html import escape

import sys

from PySide6.QtCore import QPoint, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QGuiApplication,
    QMouseEvent,
    QPainter,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from . import allergens
from .neis.models import MealMenu, ScheduleEvent
from .resources.theme import colors

#: 알레르기 경고 색. 파스텔 배경 어디에서도 눈에 띈다.
DANGER_COLOR = "#C0261C"

NOTE_WIDTH = 280
MAX_DISHES = 15
MIN_NOTE_HEIGHT = 90
MAX_HEIGHT_RATIO = 0.5  # 화면 높이 대비 상한. 넘으면 스크롤한다 (W-07)

CARD_RADIUS = 10
CARD_BORDER = 1  # QSS의 카드 테두리 두께
SHADOW_STEPS = 8  # 그림자 번짐 폭(px)
SHADOW_DROP = 3  # 아래로 내린 정도(px)
SHADOW_MARGIN = SHADOW_STEPS + SHADOW_DROP + 1
CLICK_SLOP = 4  # 이보다 적게 움직였으면 끌기가 아니라 클릭
QWIDGETSIZE_MAX = 16777215  # Qt가 쓰는 크기 상한
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
    allergy_alerts: frozenset[int] = frozenset()


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
        self._font_size = 10
        self._drag_offset: QPoint | None = None
        self._press_pos: QPoint | None = None
        self._details_open = False  # 재료·원산지 펼침 여부
        self._has_details = False
        self._view: NoteView | None = None
        self._screen_hooked = False

        # macOS에서 Tool 플래그는 앱 포커스를 잃으면 창을 자동으로 숨긴다.
        # Windows에서는 Tool이 작업표시줄·Alt+Tab 제외 역할만 하므로 유지한다.
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
        if sys.platform != "darwin":
            flags |= Qt.WindowType.Tool
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedWidth(NOTE_WIDTH)

        self._build_ui()
        self.apply_color(color)

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        # 그림자를 그릴 여백. QGraphicsDropShadowEffect는 쓰지 않는다.
        # 반투명 최상위 창에 이펙트를 걸면 Windows에서 레이어드 창 갱신이
        # 실패하고(UpdateLayeredWindowIndirect), 창 높이도 어긋난다.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(
            SHADOW_MARGIN, SHADOW_MARGIN - SHADOW_DROP,
            SHADOW_MARGIN, SHADOW_MARGIN + SHADOW_DROP,
        )

        self.card = QFrame(self)
        self.card.setObjectName("card")
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

        self.settings_button = self._tool_button("⚙", "설정")
        self.settings_button.clicked.connect(self.settingsRequested)
        header.addWidget(self.settings_button)

        self.hide_button = self._tool_button("✕", "숨기기 (트레이에 남아 있어요)")
        self.hide_button.clicked.connect(self.hideRequested)
        header.addWidget(self.hide_button)
        inner.addLayout(header)

        self.rule = QFrame(self.card)
        self.rule.setObjectName("rule")
        self.rule.setFixedHeight(1)
        inner.addWidget(self.rule)

        # 내용이 길면 창을 늘리는 대신 스크롤한다. 창을 늘리면 화면 상한과
        # 레이아웃 요구 높이가 충돌해 Qt가 리사이즈를 반복하다 멈춘다.
        self.body = QLabel()
        self.body.setObjectName("body")
        self.body.setWordWrap(True)
        self.body.setTextFormat(Qt.TextFormat.RichText)
        self.body.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        # 본문에서도 끌기와 클릭이 통하도록 마우스를 통과시킨다
        self.body.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )

        self.scroll = QScrollArea(self.card)
        self.scroll.setObjectName("scroll")
        self.scroll.setWidgetResizable(False)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.scroll.setWidget(self.body)
        # 스크롤바는 살려두고 뷰포트만 통과시킨다
        self.scroll.viewport().setAutoFillBackground(False)
        self.scroll.viewport().setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )
        inner.addWidget(self.scroll)

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
        self.settings_button.setVisible(visible)
        self.hide_button.setVisible(visible)

    def set_font_size(self, size: int) -> None:
        self._font_size = max(8, min(16, size))
        self.apply_color(self._color)
        if self._view is not None:
            self.render_view(self._view)

    def apply_color(self, color: str) -> None:
        self._color = color
        palette = colors(color)
        fs = self._font_size
        fs_sm = max(8, fs - 2)
        self.card.setStyleSheet(
            f"""
            QFrame#card {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {palette['bg']}, stop:1 {palette['bg_bottom']});
                border: 1px solid {palette['line']};
                border-radius: {CARD_RADIUS}px;
            }}
            QLabel#date {{
                color: {palette['text']};
                font-size: {fs + 1}pt;
                font-weight: 600;
            }}
            QFrame#rule {{ background: {palette['line']}; border: none; }}
            QLabel#body {{
                color: {palette['text']};
                font-size: {fs}pt;
                background: transparent;
            }}
            QScrollArea#scroll {{ background: transparent; border: none; }}
            QScrollBar:vertical {{
                background: transparent;
                width: 8px;
                margin: 0;
            }}
            QScrollBar::handle:vertical {{
                background: {palette['line']};
                border-radius: 4px;
                min-height: 24px;
            }}
            QScrollBar::handle:vertical:hover {{ background: {palette['muted']}; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: transparent;
            }}
            QLabel#footer {{ color: {palette['muted']}; font-size: {fs_sm}pt; }}
            QPushButton#tool {{
                color: {palette['muted']};
                border: none;
                background: transparent;
                font-size: {fs + 1}pt;
            }}
            QPushButton#tool:hover {{ color: {palette['accent']}; }}
            QPushButton#chip {{
                color: {palette['accent']};
                border: 1px solid {palette['line']};
                border-radius: 9px;
                background: transparent;
                padding: 0 8px;
                font-size: {fs_sm}pt;
            }}
            QPushButton#chip:hover {{ border-color: {palette['accent']}; }}
            """
        )

    # -------------------------------------------------------------- 내용 렌더

    def set_details_default(self, expanded: bool) -> None:
        """설정에서 정한 기본 펼침 상태. 이후 클릭으로 사용자가 바꿀 수 있다."""
        self._details_open = expanded
        if self._view is not None:
            self.render_view(self._view)

    def toggle_details(self) -> None:
        if not self._has_details or self._view is None:
            return
        self._details_open = not self._details_open
        self.render_view(self._view)

    def render_view(self, view: NoteView) -> None:
        self._view = view
        self._has_details = any(
            meal.origin or meal.nutrition for meal in view.meals
        )
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
        self._refit()

    def _chrome_height(self) -> int:
        """본문을 뺀 나머지(날짜줄·구분선·꼬리말·여백)가 차지하는 높이."""
        outer = self.layout()
        inner = self.card.layout()
        if outer is None or inner is None:
            return 0
        _, outer_top, _, outer_bottom = outer.getContentsMargins()
        _, inner_top, _, inner_bottom = inner.getContentsMargins()
        spacing = inner.spacing()

        height = outer_top + outer_bottom + inner_top + inner_bottom
        height += CARD_BORDER * 2
        height += self.date_label.sizeHint().height()
        height += self.rule.height()
        height += spacing * 2
        if self.footer_label.text():
            height += self.footer_label.sizeHint().height() + spacing
        return height

    def _refit(self) -> None:
        """내용에 맞춰 창 높이를 다시 잡는다.

        창 자체에는 최소·최대를 걸지 않는다. 걸어두면 레이아웃이 요구하는
        높이와 충돌해 Qt가 리사이즈를 반복하다 멈춘다. 대신 본문 영역의
        높이만 제한하고, 넘치는 만큼은 스크롤로 넘긴다.
        """
        outer = self.layout()
        inner = self.card.layout()
        if outer is None or inner is None:
            return

        outer_left, _, outer_right, _ = outer.getContentsMargins()
        inner_left, _, inner_right, _ = inner.getContentsMargins()
        full_width = (
            NOTE_WIDTH
            - outer_left - outer_right
            - inner_left - inner_right
            - CARD_BORDER * 2
        )

        screen = self.screen() or QGuiApplication.primaryScreen()
        available = screen.availableGeometry().height() if screen else 900
        body_limit = max(
            MIN_NOTE_HEIGHT, int(available * MAX_HEIGHT_RATIO) - self._chrome_height()
        )

        width = full_width
        needed = self._body_height(width)
        if needed > body_limit:
            # 스크롤바가 생기면 그만큼 글줄이 좁아지므로 다시 잰다
            width = full_width - self.scroll.verticalScrollBar().sizeHint().width()
            needed = self._body_height(width)

        self.body.resize(width, needed)
        self.scroll.setFixedHeight(min(needed, body_limit))

        inner.invalidate()
        outer.invalidate()
        inner.activate()
        outer.activate()
        self.adjustSize()

    def _body_height(self, width: int) -> int:
        """주어진 폭에서 본문이 실제로 필요한 높이.

        재는 동안에는 크기 제약을 풀어 둔다. 제약이 걸린 채로 물으면 이전에
        고정해 둔 값이 그대로 돌아와, 재료를 접어도 높이가 줄지 않는다.
        """
        self.body.setMinimumSize(0, 0)
        self.body.setMaximumSize(QWIDGETSIZE_MAX, QWIDGETSIZE_MAX)
        height = self.body.heightForWidth(width)
        if height <= 0:
            height = self.body.sizeHint().height()
        return max(height, 1)

    def _build_html(self, view: NoteView) -> str:
        palette = colors(self._color)
        fs = self._font_size
        fs_sm = max(7, fs - 2)
        blocks: list[str] = []

        if view.message:
            blocks.append(
                f"<p style='margin:8px 0 4px 0; font-size:{fs + 4}pt'>"
                f"{escape(view.message_icon)}</p>"
                f"<p style='margin:0; color:{palette['text']}'>"
                f"{escape(view.message)}</p>"
            )
            return "".join(blocks)

        for meal in view.meals:
            blocks.append(self._meal_html(meal, view, palette, fs, fs_sm))

        if self._has_details:
            hint = (
                "재료·원산지 숨기기 ▴" if self._details_open else "재료·원산지 보기 ▾"
            )
            blocks.append(
                f"<p style='margin:4px 0 0 0; font-size:{fs_sm}pt;"
                f" color:{palette['muted']}'>{hint}</p>"
            )

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
        self,
        meal: MealMenu,
        view: NoteView,
        palette: dict[str, str],
        fs: int,
        fs_sm: int,
    ) -> str:
        alerts = set(view.allergy_alerts)
        parts = [
            f"<p style='margin:6px 0 2px 0; font-weight:600;"
            f" color:{palette['muted']}'>🍚 {escape(meal.label)}</p>"
        ]
        for dish in meal.dishes[:MAX_DISHES]:
            parts.append(
                f"<p style='margin:0 0 1px 0'>"
                f"{self._dish_html(dish, view, palette, alerts, fs_sm)}</p>"
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
        if self._details_open:
            parts.append(self._details_html(meal, palette, alerts, fs_sm))
        return "".join(parts)

    def _dish_html(
        self,
        dish,
        view: NoteView,
        palette: dict[str, str],
        alerts: set[int],
        fs_sm: int,
    ) -> str:
        hits = allergens.matched(dish.allergens, alerts)
        name = escape(dish.name)
        if hits:
            return (
                f"<span style='color:{DANGER_COLOR}; font-weight:600'>{name}</span>"
                f"<span style='color:{DANGER_COLOR}; font-size:{fs_sm}pt'>"
                f" · {escape(allergens.labels(hits))}</span>"
            )
        if view.show_allergy and dish.allergens:
            return (
                f"{name}<span style='color:{palette['muted']}; font-size:{fs_sm}pt'>"
                f" ({'.'.join(dish.allergens)})</span>"
            )
        return name

    def _details_html(
        self, meal: MealMenu, palette: dict[str, str], alerts: set[int], fs_sm: int
    ) -> str:
        sections: list[str] = []
        for title, text in (("원산지", meal.origin), ("영양", meal.nutrition)):
            if not text:
                continue
            body = allergens.highlight_html(escape(text), alerts, DANGER_COLOR)
            sections.append(
                f"<p style='margin:4px 0 0 0; font-size:{fs_sm}pt;"
                f" color:{palette['muted']}'>"
                f"<b>{title}</b><br/>{body.replace(chr(10), '<br/>')}</p>"
            )
        return "".join(sections)

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

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        # 창이 실제 모니터에 올라간 뒤 다시 재본다. 모니터마다 DPI가 달라
        # 표시 전에 계산한 글자 높이가 어긋날 수 있다.
        QTimer.singleShot(0, self._refit)
        handle = self.windowHandle()
        if handle is not None and not self._screen_hooked:
            handle.screenChanged.connect(lambda _: self._refit())
            self._screen_hooked = True

    def paintEvent(self, event) -> None:  # noqa: N802
        """카드 뒤에 그림자를 직접 그린다.

        바깥쪽일수록 겹치는 층이 적어 자연스럽게 옅어진다.
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(60, 50, 30, 6))
        base = QRectF(self.card.geometry())
        for step in range(SHADOW_STEPS, 0, -1):
            painter.drawRoundedRect(
                base.adjusted(-step, -step + SHADOW_DROP, step, step + SHADOW_DROP),
                CARD_RADIUS + step,
                CARD_RADIUS + step,
            )
        painter.end()

    def enterEvent(self, event) -> None:  # noqa: N802 - Qt 시그니처
        self._set_buttons_visible(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._set_buttons_visible(False)
        super().leaveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.globalPosition().toPoint()
            self._drag_offset = self._press_pos - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag_offset is not None:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag_offset is None:
            return
        self._drag_offset = None
        moved = CLICK_SLOP + 1
        if self._press_pos is not None:
            moved = (
                event.globalPosition().toPoint() - self._press_pos
            ).manhattanLength()
        self._press_pos = None

        if moved <= CLICK_SLOP:
            # 끌지 않고 눌렀다 뗀 것은 클릭으로 본다
            self.toggle_details()
        else:
            self.ensure_on_screen()
            self.positionChanged.emit(self.x(), self.y())
        event.accept()

    def wheelEvent(self, event) -> None:  # noqa: N802
        delta = event.angleDelta().y()
        if not delta:
            return
        bar = self.scroll.verticalScrollBar()
        if bar.maximum() > 0:
            # 읽을 내용이 남아 있으면 스크롤이 먼저다.
            # 여기서 날짜까지 넘기면 읽던 중에 화면이 바뀌어 버린다.
            bar.setValue(bar.value() - delta)
        else:
            # 위로 굴리면 과거, 아래로 굴리면 미래
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
