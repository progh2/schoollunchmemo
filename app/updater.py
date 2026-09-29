"""GitHub 릴리스 기반 업데이트 (#27).

설정 창 '정보' 탭에서 [업데이트 확인]을 눌렀을 때만 동작한다. 주기적인
백그라운드 확인은 하지 않는다 — 사용자가 요청하지 않은 네트워크 호출을
만들지 않는 것이 이 앱의 방침이다.

    fetch_latest()     최신 릴리스 조회 (워커 스레드에서 호출한다)
    blocked_reason()   자동 설치가 불가능한 이유. 가능하면 None
    download()         새 버전을 교체 대상 '옆에' 준비해 둔다
    launch_replacer()  도우미 스크립트를 띄운다. 호출 뒤 앱은 곧바로 종료한다

교체 단위 (#29)
    Windows  SchoolNote.exe 파일 하나 (onefile)
    Linux    SchoolNote 파일 하나 (onefile)
    macOS    SchoolNote.app 번들 — .dmg를 마운트해 꺼낸다

실행 중인 자기 자신은 덮어쓸 수 없다 (Windows는 파일 잠금 때문에 아예 불가).
그래서 교체는 반드시 앱 바깥의 스크립트가 앱 종료를 기다렸다가 수행하고,
끝나면 새 실행 파일을 다시 띄운다.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import requests

from . import APP_NAME, REPO_URL, VERSION

log = logging.getLogger(__name__)

REPO_SLUG = REPO_URL.rstrip("/").split("github.com/", 1)[-1]
LATEST_URL = f"https://api.github.com/repos/{REPO_SLUG}/releases/latest"
RELEASES_URL = f"{REPO_URL}/releases/latest"

CONNECT_TIMEOUT = 5.0
READ_TIMEOUT = 15.0
DOWNLOAD_READ_TIMEOUT = 60.0
CHUNK = 256 * 1024

_HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": f"{APP_NAME}/{VERSION} (+desktop widget)",
}

#: 릴리스 자산 이름에 들어가는 플랫폼 표시. release.yml의 산출물 이름과 맞춘다.
ASSET_KEYS = {"win32": "windows", "darwin": "macos", "linux": "linux"}

#: 플랫폼별 자산 이름의 끝. 예전 zip/tar.gz 자산을 잘못 집지 않게 한다.
ASSET_SUFFIXES = {"windows": ".exe", "macos": ".dmg", "linux": "-linux-x64"}

#: 받은 파일이 정말 실행 파일인지 보는 첫 바이트. 오류 페이지를 거른다.
_MAGIC = {"windows": b"MZ", "linux": b"\x7fELF"}

#: 도우미 스크립트가 쓰는 작업 폴더 이름. 설치 폴더와 같은 위치에 만든다.
WORKSPACE_NAME = f".{APP_NAME}-update"
BACKUP_NAME = f".{APP_NAME}-old"

_VERSION_RE = re.compile(r"(\d+(?:\.\d+)*)")

ProgressFn = Callable[[int, int], None]


class UpdateError(Exception):
    """사용자에게 그대로 보여줄 수 있는 실패 사유."""


# ------------------------------------------------------------------ 버전 비교


def parse_version(text: str) -> tuple[int, ...]:
    """'v0.3.1', '0.4', '급식쪽지 v1.2.0'에서 숫자만 뽑는다. 없으면 빈 튜플."""
    match = _VERSION_RE.search(text or "")
    if match is None:
        return ()
    return tuple(int(part) for part in match.group(1).split("."))


def is_newer(candidate: str, current: str = VERSION) -> bool:
    """candidate가 current보다 높은 버전인가.

    자리수가 달라도 비교되도록 짧은 쪽을 0으로 채운다 (0.4 == 0.4.0).
    """
    new, old = parse_version(candidate), parse_version(current)
    if not new:
        return False
    width = max(len(new), len(old))
    new += (0,) * (width - len(new))
    old += (0,) * (width - len(old))
    return new > old


def platform_key() -> str | None:
    """이 OS의 릴리스 자산 표시. 모르는 OS면 None."""
    if sys.platform.startswith("linux"):
        return "linux"
    return ASSET_KEYS.get(sys.platform)


# ------------------------------------------------------------------ 릴리스 조회


@dataclass(frozen=True)
class Release:
    tag: str
    notes: str
    page_url: str
    asset_name: str
    asset_url: str
    asset_size: int

    @property
    def is_update(self) -> bool:
        return is_newer(self.tag)

    @property
    def size_text(self) -> str:
        if self.asset_size <= 0:
            return ""
        return f"{self.asset_size / 1024 / 1024:.0f}MB"


def pick_asset(assets: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
    suffix = ASSET_SUFFIXES.get(key, "")
    for asset in assets:
        name = str(asset.get("name", "")).lower()
        if key in name and name.endswith(suffix):
            return asset
    return None


def fetch_latest(session: Any | None = None) -> Release:
    """최신 릴리스 정보를 가져온다. 실패하면 UpdateError.

    GitHub의 releases/latest는 프리릴리스를 제외하므로 베타가 잡히지 않는다.
    """
    key = platform_key()
    if key is None:
        raise UpdateError(f"이 운영체제({sys.platform})용 배포 파일이 없습니다.")

    http = session if session is not None else requests
    try:
        response = http.get(
            LATEST_URL, headers=_HEADERS, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT)
        )
    except requests.RequestException as exc:
        log.info("릴리스 조회 실패: %s", exc)
        raise UpdateError(
            "업데이트 서버에 연결하지 못했습니다. 네트워크를 확인해 주세요."
        ) from exc

    if response.status_code == 404:
        raise UpdateError("아직 공개된 릴리스가 없습니다.")
    if response.status_code >= 400:
        raise UpdateError(
            f"업데이트 정보를 받지 못했습니다 (HTTP {response.status_code})."
        )

    try:
        data = response.json()
    except ValueError as exc:
        raise UpdateError("업데이트 정보를 해석하지 못했습니다.") from exc

    tag = str(data.get("tag_name") or "")
    if not tag:
        raise UpdateError("릴리스에 버전 태그가 없습니다.")

    asset = pick_asset(list(data.get("assets") or []), key)
    if asset is None:
        raise UpdateError(f"최신 릴리스에 {key}용 파일이 없습니다.")

    return Release(
        tag=tag,
        notes=str(data.get("body") or "").strip(),
        page_url=str(data.get("html_url") or RELEASES_URL),
        asset_name=str(asset.get("name") or ""),
        asset_url=str(asset.get("browser_download_url") or ""),
        asset_size=int(asset.get("size") or 0),
    )


# ------------------------------------------------------------------ 설치 위치


def install_target() -> Path | None:
    """교체할 대상. 소스에서 실행 중이면 None.

    Windows/Linux는 onefile이라 실행 파일 하나가 곧 앱 전체이고,
    macOS는 .app 번들 전체가 교체 단위다.
    """
    if not getattr(sys, "frozen", False):
        return None
    executable = Path(sys.executable).resolve()
    if sys.platform == "darwin":
        for parent in executable.parents:
            if parent.suffix == ".app":
                return parent
    return executable


def bundle_executable(bundle: Path) -> Path:
    """macOS .app 번들 안의 실행 파일."""
    return bundle / "Contents" / "MacOS" / APP_NAME


def _writable(path: Path) -> bool:
    """실제로 파일을 만들어 본다. os.access는 Windows에서 믿기 어렵다."""
    probe = path / f".{APP_NAME}-write-test-{os.getpid()}"
    try:
        probe.touch()
    except OSError:
        return False
    probe.unlink(missing_ok=True)
    return True


def blocked_reason(target: Path | None = None) -> str | None:
    """자동 설치를 할 수 없는 이유. 가능하면 None."""
    target = target if target is not None else install_target()
    if target is None:
        return (
            "소스에서 실행 중이라 자동 설치를 할 수 없습니다. "
            "git pull로 최신 코드를 받아 주세요."
        )
    # 새 파일을 옆에 두고 이름을 바꿔 끼우므로 담긴 폴더에 쓸 수 있어야 한다.
    if not _writable(target.parent):
        return (
            f"앱이 있는 폴더에 쓸 수 없습니다 ({target.parent}). 앱을 문서 폴더 등 "
            "쓰기 가능한 위치로 옮긴 뒤 다시 시도하거나, 직접 내려받아 주세요."
        )
    return None


# ------------------------------------------------------------------ 내려받기


def download(
    release: Release,
    target: Path,
    progress: ProgressFn | None = None,
    session: Any | None = None,
) -> Path:
    """새 버전을 받아 교체할 준비를 마치고, 끼워 넣을 경로를 돌려준다.

    교체 대상과 같은 폴더(같은 파일시스템)에 두어야 마지막 교체가 이름
    바꾸기 한 번으로 끝난다. 시스템 임시 폴더를 쓰면 통째 복사가 된다.
    """
    if not release.asset_url:
        raise UpdateError("내려받을 파일 주소가 없습니다.")

    workspace = target.parent / WORKSPACE_NAME
    shutil.rmtree(workspace, ignore_errors=True)
    try:
        workspace.mkdir(parents=True)
    except OSError as exc:
        raise UpdateError(f"작업 폴더를 만들지 못했습니다: {exc}") from exc

    fetched = workspace / (release.asset_name or APP_NAME)
    try:
        _fetch(release, fetched, progress, session)
        if sys.platform == "darwin":
            staged = _stage_from_dmg(fetched, workspace)
        else:
            staged = _stage_binary(fetched, platform_key() or "")
    except UpdateError:
        shutil.rmtree(workspace, ignore_errors=True)
        raise
    return staged


def _fetch(
    release: Release,
    dest: Path,
    progress: ProgressFn | None,
    session: Any | None,
) -> None:
    http = session if session is not None else requests
    try:
        with http.get(
            release.asset_url,
            headers={"User-Agent": _HEADERS["User-Agent"]},
            timeout=(CONNECT_TIMEOUT, DOWNLOAD_READ_TIMEOUT),
            stream=True,
        ) as response:
            if response.status_code >= 400:
                raise UpdateError(
                    f"파일을 내려받지 못했습니다 (HTTP {response.status_code})."
                )
            total = int(response.headers.get("Content-Length") or release.asset_size)
            done = 0
            with open(dest, "wb") as out:
                for chunk in response.iter_content(CHUNK):
                    if not chunk:
                        continue
                    out.write(chunk)
                    done += len(chunk)
                    if progress is not None:
                        progress(done, total)
    except requests.RequestException as exc:
        raise UpdateError(f"내려받는 중 연결이 끊겼습니다: {exc}") from exc

    if release.asset_size > 0 and dest.stat().st_size != release.asset_size:
        raise UpdateError("내려받은 파일 크기가 맞지 않습니다. 다시 시도해 주세요.")


def _stage_binary(path: Path, key: str) -> Path:
    """onefile 실행 파일은 받은 그대로 쓴다. 정말 실행 파일인지만 본다."""
    magic = _MAGIC.get(key)
    if magic is not None:
        with open(path, "rb") as handle:
            if handle.read(len(magic)) != magic:
                raise UpdateError("내려받은 파일이 실행 파일이 아닙니다.")
    if sys.platform != "win32":
        path.chmod(0o755)  # 받은 파일에는 실행 권한이 없다
    return path


def _stage_from_dmg(dmg: Path, workspace: Path) -> Path:
    """.dmg를 마운트해 .app을 작업 폴더로 꺼낸다.

    ditto는 권한·심볼릭 링크·확장 속성을 그대로 옮긴다. 앱이 직접 받은
    파일이라 격리(quarantine) 속성이 없어 Gatekeeper 재검사도 걸리지 않는다.
    """
    mount = Path(tempfile.mkdtemp(prefix=f"{APP_NAME}-dmg-"))
    try:
        _run(
            ["hdiutil", "attach", str(dmg), "-nobrowse", "-readonly",
             "-noautoopen", "-mountpoint", str(mount)],
            "디스크 이미지를 열지 못했습니다.",
        )
        try:
            bundles = [item for item in mount.iterdir() if item.suffix == ".app"]
            if not bundles:
                raise UpdateError("디스크 이미지 안에 앱이 없습니다.")
            staged = workspace / bundles[0].name
            _run(["ditto", str(bundles[0]), str(staged)], "앱을 꺼내지 못했습니다.")
        finally:
            _run(["hdiutil", "detach", str(mount), "-quiet"], None)
    finally:
        shutil.rmtree(mount, ignore_errors=True)
    dmg.unlink(missing_ok=True)

    if not bundle_executable(staged).exists():
        raise UpdateError("내려받은 앱이 온전하지 않습니다.")
    return staged


def _run(command: list[str], failure: str | None) -> None:
    """외부 명령을 실행한다. failure가 None이면 실패를 무시한다."""
    try:
        subprocess.run(command, check=True, capture_output=True, timeout=300)  # noqa: S603
    except (OSError, subprocess.SubprocessError) as exc:
        log.info("명령 실패 %s: %s", command[0], exc)
        if failure is not None:
            raise UpdateError(failure) from exc


# ------------------------------------------------------------------ 교체·재시작


def launch_replacer(staged: Path, target: Path) -> None:
    """앱 종료를 기다렸다가 새 버전을 끼워 넣고 다시 띄우는 스크립트를 실행한다.

    호출한 쪽은 곧바로 앱을 종료해야 한다. 스크립트는 이 프로세스가 사라질
    때까지 기다리므로, 종료하지 않으면 아무 일도 일어나지 않는다.
    """
    if not staged.exists():
        raise UpdateError("내려받은 파일이 없습니다. 다시 시도해 주세요.")

    workspace = target.parent / WORKSPACE_NAME
    try:
        script = _write_script(
            replacer_script(os.getpid(), staged, target, workspace, sys.platform)
        )
    except UnicodeEncodeError as exc:
        # cmd는 CP949로 읽는다. 담을 수 없는 문자가 경로에 있으면 교체가 깨진다.
        raise UpdateError(
            "앱 경로에 쓸 수 없는 문자가 있어 자동 설치를 할 수 없습니다. "
            "직접 내려받아 주세요."
        ) from exc
    log.info("업데이트 스크립트를 실행합니다: %s", script)

    try:
        if sys.platform == "win32":
            _spawn_windows(script)
        else:
            subprocess.Popen(  # noqa: S603 - 우리가 만든 스크립트만 실행한다
                ["/bin/sh", str(script)],
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
    except OSError as exc:
        raise UpdateError(f"업데이트 스크립트를 실행하지 못했습니다: {exc}") from exc


def _spawn_windows(script: Path) -> None:
    """보이지 않는 콘솔로 스크립트를 띄운다.

    DETACHED_PROCESS를 쓰면 cmd에 콘솔이 없어서 tasklist·ping 같은 자식이
    매번 새 콘솔 창을 띄운다. CREATE_NO_WINDOW로 숨은 콘솔 하나를 물려준다.
    앱이 작업 개체(job) 안에 있으면 앱과 함께 죽을 수 있어 먼저 빠져나가 본다.
    """
    no_window = 0x08000000
    new_group = 0x00000200
    breakaway = 0x01000000
    command = ["cmd", "/c", str(script)]
    try:
        subprocess.Popen(command, creationflags=no_window | new_group | breakaway, close_fds=True)  # noqa: S603
    except OSError:
        # 빠져나가기가 허용되지 않는 작업 개체면 그냥 띄운다
        subprocess.Popen(command, creationflags=no_window | new_group, close_fds=True)  # noqa: S603


def _write_script(body: str) -> Path:
    """도우미 스크립트를 시스템 임시 폴더에 쓴다.

    스크립트가 작업 폴더를 지우므로, 스크립트 자신은 작업 폴더 밖에 있어야
    실행 도중 사라지지 않는다.
    """
    windows = sys.platform == "win32"
    handle = tempfile.NamedTemporaryFile(  # noqa: SIM115 - 경로만 쓰고 닫는다
        prefix=f"{APP_NAME}-update-",
        suffix=".cmd" if windows else ".sh",
        delete=False,
        mode="w",
        encoding="cp949" if windows else "utf-8",
        newline="\r\n" if windows else "\n",
    )
    with handle as script:
        script.write(body)
    return Path(handle.name)


def replacer_script(
    pid: int, staged: Path, target: Path, workspace: Path, platform: str
) -> str:
    """플랫폼에 맞는 교체 스크립트 본문."""
    if platform == "win32":
        return _windows_script(pid, staged, target, workspace)
    if platform == "darwin":
        return _macos_script(pid, staged, target, workspace)
    return _linux_script(pid, staged, target, workspace)


def _windows_script(pid: int, staged: Path, target: Path, workspace: Path) -> str:
    # 콘솔이 숨겨져 있으면 timeout 명령은 바로 실패한다. 1초 대기는 ping으로 한다.
    # onefile은 부트로더 프로세스가 앱 종료 뒤에도 잠깐 exe를 잡고 있어서
    # (임시 폴더 정리), 이름 바꾸기를 최대 30초 동안 되풀이한다.
    # 끝내 실패하면 예전 exe를 그대로 다시 띄운다.
    return f"""@echo off
:wait
tasklist /FI "PID eq {pid}" /NH | find "{pid}" >nul
if not errorlevel 1 (
  ping -n 2 127.0.0.1 >nul
  goto wait
)
set tries=0
:swap
move /y "{staged}" "{target}" >nul 2>&1
if not errorlevel 1 goto done
set /a tries+=1
if %tries% geq 30 goto done
ping -n 2 127.0.0.1 >nul
goto swap
:done
start "" "{target}"
rmdir /s /q "{workspace}"
"""


def _linux_script(pid: int, staged: Path, target: Path, workspace: Path) -> str:
    # 리눅스는 실행 중인 파일도 이름 바꾸기로 갈아 끼울 수 있다(inode가 다르다).
    # 그래도 단일 인스턴스 소켓이 풀린 뒤 띄우려고 종료를 기다린다.
    return f"""#!/bin/sh
while kill -0 {pid} 2>/dev/null; do sleep 0.5; done
chmod +x "{staged}"
mv -f "{staged}" "{target}"
"{target}" >/dev/null 2>&1 &
rm -rf "{workspace}"
"""


def _macos_script(pid: int, staged: Path, target: Path, workspace: Path) -> str:
    backup = target.parent / BACKUP_NAME
    # .app은 폴더라 이름 바꾸기 두 번으로 교체한다. 두 번째가 실패하면 되돌린다.
    return f"""#!/bin/sh
while kill -0 {pid} 2>/dev/null; do sleep 0.5; done
rm -rf "{backup}"
if mv "{target}" "{backup}"; then
  if mv "{staged}" "{target}"; then
    rm -rf "{backup}"
  else
    mv "{backup}" "{target}"
  fi
fi
open "{target}"
rm -rf "{workspace}"
"""
