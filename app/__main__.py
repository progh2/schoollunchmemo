"""진입점.

python -m app 로 실행한다.
"""

from __future__ import annotations

import logging
import logging.handlers
import signal
import sys
from pathlib import Path

from PySide6.QtCore import QCoreApplication
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from . import APP_DISPLAY_NAME, APP_NAME, VERSION
from .config import data_dir
from .controller import AppController
from .resources.icons import app_icon

_SERVER_NAME = "SchoolNote.singleton"

log = logging.getLogger(__name__)


def _fix_macos_app_name(name: str) -> None:
    """macOS 메뉴바에 표시되는 앱 이름을 'python' 대신 실제 이름으로 바꾼다.

    개발 실행 시 Python 인터프리터 번들의 CFBundleName이 그대로 노출되는 문제를 해결한다.
    패키징된 .app은 Info.plist로 처리되므로 이 함수는 무해하게 덮어쓴다.
    """
    try:
        import ctypes
        import ctypes.util

        objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))

        GetClass = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_char_p)(
            ("objc_getClass", objc)
        )
        RegSel = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_char_p)(
            ("sel_registerName", objc)
        )
        Send0 = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(
            ("objc_msgSend", objc)
        )
        Send1s = ctypes.CFUNCTYPE(
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p
        )(("objc_msgSend", objc))
        Send2 = ctypes.CFUNCTYPE(
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        )(("objc_msgSend", objc))

        bundle = Send0(GetClass(b"NSBundle"), RegSel(b"mainBundle"))
        info = Send0(bundle, RegSel(b"infoDictionary"))
        ns_str = GetClass(b"NSString")
        key = Send1s(ns_str, RegSel(b"stringWithUTF8String:"), b"CFBundleName")
        val = Send1s(
            ns_str, RegSel(b"stringWithUTF8String:"), name.encode("utf-8")
        )
        Send2(info, RegSel(b"setValue:forKey:"), val, key)
    except Exception as exc:
        log.debug("macOS 앱 이름 설정 실패: %s", exc)


def _hide_from_dock() -> None:
    """개발 실행 시 Dock에서 Python 아이콘을 숨긴다.

    패키징된 .app은 Info.plist의 LSUIElement=True로 처리되고,
    개발 모드에서는 이 함수가 동일한 효과를 낸다.
    NSApplicationActivationPolicyAccessory = 1
    """
    try:
        import ctypes
        import ctypes.util

        objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))

        GetClass = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_char_p)(
            ("objc_getClass", objc)
        )
        RegSel = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_char_p)(
            ("sel_registerName", objc)
        )
        Send0 = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(
            ("objc_msgSend", objc)
        )
        Send1i = ctypes.CFUNCTYPE(
            ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long
        )(("objc_msgSend", objc))

        ns_app = GetClass(b"NSApplication")
        shared = Send0(ns_app, RegSel(b"sharedApplication"))
        Send1i(shared, RegSel(b"setActivationPolicy:"), 1)
    except Exception as exc:
        log.debug("macOS Dock 숨기기 실패: %s", exc)


def _setup_logging() -> None:
    log_dir = Path(data_dir()) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        log_dir / "schoolnote.log",
        maxBytes=512_000,
        backupCount=2,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    )
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    root.addHandler(logging.StreamHandler(sys.stderr))


def _claim_single_instance() -> QLocalServer | None:
    """이미 실행 중이면 그쪽 포스트잇을 띄우고 None을 돌려준다."""
    socket = QLocalSocket()
    socket.connectToServer(_SERVER_NAME)
    if socket.waitForConnected(300):
        socket.write(b"show")
        socket.flush()
        socket.waitForBytesWritten(300)
        socket.disconnectFromServer()
        return None

    QLocalServer.removeServer(_SERVER_NAME)  # 비정상 종료로 남은 소켓 정리
    server = QLocalServer()
    if not server.listen(_SERVER_NAME):
        log.warning("단일 인스턴스 서버를 열지 못했습니다: %s", server.errorString())
    return server


def main() -> int:
    # Qt 이벤트 루프가 SIGINT를 소비하지 않도록 기본 핸들러로 복원한다.
    # 이렇게 해야 터미널에서 Ctrl+C로 앱을 종료할 수 있다.
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    if sys.platform == "darwin":
        _fix_macos_app_name(APP_DISPLAY_NAME)

    QCoreApplication.setApplicationName(APP_NAME)
    QCoreApplication.setApplicationVersion(VERSION)

    app = QApplication(sys.argv)
    app.setApplicationDisplayName(APP_DISPLAY_NAME)
    app.setWindowIcon(app_icon())
    # 포스트잇을 닫아도 앱은 트레이에 살아 있어야 한다
    app.setQuitOnLastWindowClosed(False)

    if sys.platform == "darwin":
        _hide_from_dock()

    _setup_logging()

    server = _claim_single_instance()
    if server is None:
        print("급식쪽지가 이미 실행 중입니다.", file=sys.stderr)
        return 0

    controller = AppController(app)
    server.newConnection.connect(
        lambda: (server.nextPendingConnection(), controller.show_note())
    )
    controller.start()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
