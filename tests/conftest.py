import os

# 화면 없이 Qt 위젯을 만들 수 있게 한다. Qt import보다 먼저 설정해야 한다.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def controller(qapp, monkeypatch):
    """설정 파일도 네트워크도 건드리지 않는 컨트롤러."""
    from app import secrets_store
    from app.config import Config
    from app.controller import AppController

    monkeypatch.setattr(Config, "load", classmethod(lambda cls: cls()))
    monkeypatch.setattr(Config, "save", lambda self: None)
    monkeypatch.setattr(secrets_store, "get_key", lambda: "dummy-key")

    instance = AppController(qapp)
    instance._config.school = {
        "office_code": "B10",
        "school_code": "7010084",
        "school_name": "미림마이스터고등학교",
    }
    yield instance
    instance.note.deleteLater()
    instance.tray.deleteLater()
