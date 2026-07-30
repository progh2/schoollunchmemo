"""자동 시작 등록 테스트.

파일 기반 백엔드(Linux·macOS)는 어느 OS에서도 경로를 주고 직접 만들 수
있으므로 항상 검증한다. 레지스트리 백엔드는 Windows에서만 돌리고,
실제 자동 시작 항목을 건드리지 않도록 시험용 키에 쓴다.
"""

from __future__ import annotations

import plistlib
import sys
from pathlib import Path

import pytest

from app import autostart


class TestLaunchCommand:
    def test_frozen_uses_the_executable_itself(self, monkeypatch):
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", str(Path.cwd() / "SchoolNote.exe"))
        assert autostart.launch_command() == [
            str((Path.cwd() / "SchoolNote.exe").resolve())
        ]

    def test_dev_mode_points_at_run_py(self):
        """작업 디렉터리에 기대지 않도록 -m 대신 절대 경로를 쓴다."""
        command = autostart.launch_command()
        assert len(command) == 2
        assert command[1].endswith("run.py")
        assert Path(command[1]).is_absolute()
        assert Path(command[1]).exists()


class TestQuoting:
    def test_plain_arguments_stay_bare(self):
        assert autostart._quote_for_exec(["/usr/bin/python3", "-m", "app"]) == (
            "/usr/bin/python3 -m app"
        )

    def test_spaces_get_quoted(self):
        quoted = autostart._quote_for_exec(["/opt/My Apps/python", "run.py"])
        assert quoted == '"/opt/My Apps/python" run.py'


class TestXdgBackend:
    @pytest.fixture
    def backend(self, tmp_path):
        return autostart.XdgBackend(tmp_path / "autostart" / "schoolnote.desktop")

    def test_write_creates_desktop_entry(self, backend):
        backend.write(backend.render(["/usr/bin/python3", "/app/run.py"]))
        text = backend.path.read_text(encoding="utf-8")
        assert text.startswith("[Desktop Entry]")
        assert "Exec=/usr/bin/python3 /app/run.py" in text
        assert "Type=Application" in text

    def test_missing_file_reads_as_not_registered(self, backend):
        assert backend.current() is None

    def test_remove_is_forgiving(self, backend):
        backend.remove()  # 없는 파일을 지워도 예외가 없어야 한다
        backend.write("x")
        backend.remove()
        assert backend.current() is None


class TestLaunchAgentBackend:
    @pytest.fixture
    def backend(self, tmp_path):
        return autostart.LaunchAgentBackend(tmp_path / "com.schoolnote.app.plist")

    def test_render_is_a_valid_plist(self, backend):
        argv = ["/Applications/SchoolNote.app/Contents/MacOS/SchoolNote"]
        parsed = plistlib.loads(backend.render(argv).encode("utf-8"))
        assert parsed["ProgramArguments"] == argv
        assert parsed["RunAtLoad"] is True
        assert parsed["Label"] == autostart.BUNDLE_ID

    def test_round_trip(self, backend):
        payload = backend.render(["/bin/true"])
        backend.write(payload)
        assert backend.current() == payload


@pytest.mark.skipif(sys.platform != "win32", reason="레지스트리는 Windows 전용")
class TestRegistryBackend:
    @pytest.fixture
    def backend(self):
        # 실제 Run 키가 아니라 시험용 키를 쓴다
        import winreg

        key_path = r"Software\SchoolNote\AutostartTest"
        target = autostart.RegistryBackend(key_path, "SchoolNoteTest")
        yield target
        target.remove()
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key_path)
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, r"Software\SchoolNote")
        except OSError:
            pass

    def test_missing_value_reads_as_not_registered(self, backend):
        assert backend.current() is None

    def test_round_trip(self, backend):
        payload = backend.render([r"C:\Program Files\SchoolNote\SchoolNote.exe"])
        assert payload == r'"C:\Program Files\SchoolNote\SchoolNote.exe"'
        backend.write(payload)
        assert backend.current() == payload
        backend.remove()
        assert backend.current() is None


class _FakeBackend(autostart._Backend):
    """쓰기 횟수를 세는 백엔드. OS를 건드리지 않는지 확인하는 데 쓴다."""

    def __init__(self) -> None:
        self.payload: str | None = None
        self.writes = 0
        self.removes = 0

    def render(self, argv):
        return " ".join(argv)

    def current(self):
        return self.payload

    def write(self, payload):
        self.payload = payload
        self.writes += 1

    def remove(self):
        self.payload = None
        self.removes += 1


class TestSetEnabled:
    @pytest.fixture
    def fake(self, monkeypatch):
        target = _FakeBackend()
        monkeypatch.setattr(autostart, "backend", lambda: target)
        return target

    def test_enable_then_disable(self, fake):
        assert autostart.set_enabled(True) is True
        assert autostart.is_enabled() is True
        assert fake.writes == 1

        assert autostart.set_enabled(False) is True
        assert autostart.is_enabled() is False
        assert fake.removes == 1

    def test_enabling_twice_writes_once(self, fake):
        autostart.set_enabled(True)
        autostart.set_enabled(True)
        assert fake.writes == 1  # 이미 맞는 상태면 건드리지 않는다

    def test_disabling_when_absent_does_nothing(self, fake):
        assert autostart.set_enabled(False) is True
        assert fake.removes == 0

    def test_moved_executable_gets_rewritten(self, fake, monkeypatch):
        autostart.set_enabled(True)
        monkeypatch.setattr(autostart, "launch_command", lambda: ["/new/path/app"])
        autostart.set_enabled(True)
        assert fake.writes == 2
        assert fake.payload == "/new/path/app"

    def test_write_failure_is_reported(self, fake, monkeypatch):
        def boom(_payload):
            raise OSError("권한이 없습니다")

        monkeypatch.setattr(fake, "write", boom)
        assert autostart.set_enabled(True) is False

    def test_unsupported_platform_reports_false(self, monkeypatch):
        monkeypatch.setattr(autostart, "backend", lambda: None)
        assert autostart.is_supported() is False
        assert autostart.is_enabled() is False
        assert autostart.set_enabled(True) is False


class TestBackendSelection:
    def test_this_platform_is_supported(self):
        assert autostart.is_supported() is True

    def test_unknown_platform_has_no_backend(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "sunos5")
        assert autostart.backend() is None

    def test_linux_uses_xdg_config_home(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        target = autostart.backend()
        assert isinstance(target, autostart.XdgBackend)
        assert target.path == tmp_path / "autostart" / "schoolnote.desktop"
