import os

# 화면 없이 Qt 위젯을 만들 수 있게 한다. Qt import보다 먼저 설정해야 한다.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app
