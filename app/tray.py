"""트레이 아이콘.

포스트잇이 숨겨져 있어도 항상 떠 있는 앱의 유일한 상시 진입점이다.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QSystemTrayIcon, QWidget

from . import APP_DISPLAY_NAME
from .resources.icons import app_icon


class Tray(QSystemTrayIcon):
    toggleRequested = Signal()
    refreshRequested = Signal()
    settingsRequested = Signal()
    aboutRequested = Signal()
    quitRequested = Signal()

    def __init__(self, color: str = "yellow", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = color
        self._school_name = ""
        self._error = False

        menu = QMenu()
        self._school_action = QAction(APP_DISPLAY_NAME, menu)
        self._school_action.setEnabled(False)
        menu.addAction(self._school_action)
        menu.addSeparator()

        self._toggle_action = QAction("포스트잇 보이기", menu)
        self._toggle_action.setCheckable(True)
        self._toggle_action.triggered.connect(self.toggleRequested)
        menu.addAction(self._toggle_action)

        refresh_action = QAction("지금 새로고침", menu)
        refresh_action.triggered.connect(self.refreshRequested)
        menu.addAction(refresh_action)
        menu.addSeparator()

        settings_action = QAction("설정...", menu)
        settings_action.triggered.connect(self.settingsRequested)
        menu.addAction(settings_action)

        about_action = QAction(f"{APP_DISPLAY_NAME} 정보", menu)
        about_action.triggered.connect(self.aboutRequested)
        menu.addAction(about_action)
        menu.addSeparator()

        quit_action = QAction("종료", menu)
        quit_action.triggered.connect(self.quitRequested)
        menu.addAction(quit_action)

        self._menu = menu  # 참조를 놓으면 메뉴가 사라진다
        self.setContextMenu(menu)
        self.activated.connect(self._on_activated)
        self.set_error(False)
        self._update_tooltip()

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.toggleRequested.emit()

    # ------------------------------------------------------------------ 상태

    def set_color(self, color: str) -> None:
        self._color = color
        self.set_error(self._error)

    def set_error(self, error: bool) -> None:
        self._error = error
        self.setIcon(app_icon(self._color, error))

    def set_school_name(self, name: str) -> None:
        self._school_name = name
        self._school_action.setText(name or "학교가 설정되지 않았습니다")
        self._update_tooltip()

    def set_note_visible(self, visible: bool) -> None:
        self._toggle_action.setChecked(visible)

    def _update_tooltip(self) -> None:
        if self._school_name:
            self.setToolTip(f"{APP_DISPLAY_NAME} — {self._school_name}")
        else:
            self.setToolTip(APP_DISPLAY_NAME)
