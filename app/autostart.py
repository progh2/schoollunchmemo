"""부팅 시 자동 시작 등록.

OS마다 자동 시작을 등록하는 자리가 다르다.

    Windows  레지스트리 HKCU\\...\\CurrentVersion\\Run 값
    macOS    ~/Library/LaunchAgents/com.schoolnote.app.plist
    Linux    ~/.config/autostart/schoolnote.desktop

세 가지 모두 "무엇을 실행할지"를 문자열 하나로 적어 두는 구조라,
백엔드는 저장된 문구(payload)를 읽고 쓰고 지우는 세 가지 일만 한다.
덕분에 원하는 상태와 실제 상태를 문자열 비교로 맞출 수 있고,
실행 파일을 옮겨 경로가 바뀌었을 때도 같은 경로로 고쳐 쓸 수 있다.

쓸 수 없는 환경에서는 조용히 실패하고
그 사실을 is_supported()로 UI에 알린다. 자동 시작이 안 된다고 앱이
멈출 이유는 없다.
"""

from __future__ import annotations

import logging
import os
import plistlib
import subprocess
import sys
from pathlib import Path

from . import APP_DISPLAY_NAME, APP_NAME

log = logging.getLogger(__name__)

#: Windows 자동 시작 레지스트리 위치
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

#: macOS LaunchAgent 식별자. schoolnote.spec의 bundle_identifier와 맞춘다.
BUNDLE_ID = "com.schoolnote.app"

_DESKTOP_FILENAME = "schoolnote.desktop"


# ---------------------------------------------------------------- 실행 명령

def launch_command() -> list[str]:
    """자동 시작이 실행할 명령.

    개발 중에는 `-m app` 대신 run.py의 절대 경로를 쓴다. 자동 시작은
    작업 디렉터리를 보장해 주지 않으므로, `-m`으로는 저장소 최상위가
    import 경로에 들어오지 않아 실패한다.
    """
    if getattr(sys, "frozen", False):  # PyInstaller로 묶인 실행 파일
        return [str(Path(sys.executable).resolve())]

    python = Path(sys.executable)
    if os.name == "nt":
        # 콘솔 창이 딸려 오지 않게 창 없는 인터프리터를 쓴다
        windowed = python.with_name("pythonw.exe")
        if windowed.exists():
            python = windowed

    entry = Path(__file__).resolve().parent.parent / "run.py"
    if entry.exists():
        return [str(python.resolve()), str(entry)]
    return [str(python.resolve()), "-m", __package__ or "app"]


def _quote_for_exec(argv: list[str]) -> str:
    """Desktop Entry의 Exec= 한 줄로 만든다.

    공백이나 따옴표가 든 인수만 큰따옴표로 감싼다 (Desktop Entry 규격).
    """
    parts = []
    for arg in argv:
        if any(ch in arg for ch in ' \t"\'\\$`'):
            escaped = arg.replace("\\", "\\\\").replace('"', '\\"')
            parts.append(f'"{escaped}"')
        else:
            parts.append(arg)
    return " ".join(parts)


# ------------------------------------------------------------------ 백엔드

class _Backend:
    """자동 시작 등록 한 곳. payload는 OS별 저장 형식의 문자열이다."""

    def render(self, argv: list[str]) -> str:
        raise NotImplementedError

    def current(self) -> str | None:
        """등록되어 있으면 저장된 payload, 없으면 None."""
        raise NotImplementedError

    def write(self, payload: str) -> None:
        raise NotImplementedError

    def remove(self) -> None:
        raise NotImplementedError


class _FileBackend(_Backend):
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def current(self) -> str | None:
        try:
            return self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except OSError as exc:
            log.warning("자동 시작 파일을 읽지 못했습니다: %s", exc)
            return None

    def write(self, payload: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(payload, encoding="utf-8")

    def remove(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


class XdgBackend(_FileBackend):
    """Linux — XDG autostart 디렉터리의 .desktop 파일."""

    def render(self, argv: list[str]) -> str:
        return (
            "[Desktop Entry]\n"
            "Type=Application\n"
            f"Name={APP_DISPLAY_NAME}\n"
            f"Exec={_quote_for_exec(argv)}\n"
            "Terminal=false\n"
            "X-GNOME-Autostart-enabled=true\n"
        )


class LaunchAgentBackend(_FileBackend):
    """macOS — 로그인 시 실행되는 LaunchAgent plist."""

    def render(self, argv: list[str]) -> str:
        return plistlib.dumps(
            {
                "Label": BUNDLE_ID,
                "ProgramArguments": argv,
                "RunAtLoad": True,
            }
        ).decode("utf-8")


class RegistryBackend(_Backend):
    """Windows — HKCU Run 키의 문자열 값."""

    def __init__(self, key_path: str = RUN_KEY, value_name: str = APP_NAME) -> None:
        self.key_path = key_path
        self.value_name = value_name

    def render(self, argv: list[str]) -> str:
        # Windows는 명령 한 줄로 저장한다. 경로에 공백이 있으면 깨지므로
        # 따옴표 처리는 표준 규칙을 쓰는 list2cmdline에 맡긴다.
        return subprocess.list2cmdline(argv)

    def current(self) -> str | None:
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.key_path) as key:
                value, _ = winreg.QueryValueEx(key, self.value_name)
        except FileNotFoundError:  # 키나 값이 없다 = 등록 안 됨
            return None
        except OSError as exc:
            log.warning("자동 시작 레지스트리를 읽지 못했습니다: %s", exc)
            return None
        return str(value)

    def write(self, payload: str) -> None:
        import winreg

        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, self.key_path, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.SetValueEx(key, self.value_name, 0, winreg.REG_SZ, payload)

    def remove(self) -> None:
        import winreg

        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, self.key_path, 0, winreg.KEY_SET_VALUE
            ) as key:
                winreg.DeleteValue(key, self.value_name)
        except FileNotFoundError:
            pass


def _xdg_config_home() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME", "").strip()
    return Path(base) if base else Path.home() / ".config"


def backend() -> _Backend | None:
    """이 OS의 백엔드. 다룰 수 없는 환경에서는 None."""
    if sys.platform.startswith("win"):
        return RegistryBackend()
    if sys.platform == "darwin":
        return LaunchAgentBackend(
            Path.home() / "Library" / "LaunchAgents" / f"{BUNDLE_ID}.plist"
        )
    if sys.platform.startswith("linux"):
        return XdgBackend(_xdg_config_home() / "autostart" / _DESKTOP_FILENAME)
    return None


# -------------------------------------------------------------------- 공개 API

def is_supported() -> bool:
    """이 환경에서 자동 시작을 등록할 수 있는지 여부."""
    return backend() is not None


def is_enabled() -> bool:
    """실제로 등록되어 있는지. 설정 파일이 아니라 OS 쪽을 본다."""
    target = backend()
    return target is not None and target.current() is not None


def set_enabled(enabled: bool) -> bool:
    """자동 시작을 켜고 끈다. 성공하면 True.

    이미 원하는 상태면 아무것도 쓰지 않는다. 다만 등록된 명령이
    지금 실행 파일과 다르면(설치 위치를 옮긴 경우) 다시 쓴다.
    """
    target = backend()
    if target is None:
        log.info("이 환경에서는 자동 시작을 등록할 수 없습니다: %s", sys.platform)
        return False

    try:
        current = target.current()
        if enabled:
            payload = target.render(launch_command())
            if current != payload:
                target.write(payload)
        elif current is not None:
            target.remove()
    except OSError as exc:
        log.error("자동 시작 설정을 바꾸지 못했습니다: %s", exc)
        return False
    return True
