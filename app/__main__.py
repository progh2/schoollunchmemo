"""진입점.

python -m app 로 실행한다.
"""

from __future__ import annotations

import logging
import logging.handlers
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
    QCoreApplication.setApplicationName(APP_NAME)
    QCoreApplication.setApplicationVersion(VERSION)

    app = QApplication(sys.argv)
    app.setApplicationDisplayName(APP_DISPLAY_NAME)
    app.setWindowIcon(app_icon())
    # 포스트잇을 닫아도 앱은 트레이에 살아 있어야 한다
    app.setQuitOnLastWindowClosed(False)

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
