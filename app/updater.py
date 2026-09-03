"""GitHub 릴리스 기반 업데이트 (#27).

설정 창 '정보' 탭에서 [업데이트 확인]을 눌렀을 때만 동작한다. 주기적인
백그라운드 확인은 하지 않는다 — 사용자가 요청하지 않은 네트워크 호출을
만들지 않는 것이 이 앱의 방침이다.

    fetch_latest()     최신 릴리스 조회 (워커 스레드에서 호출한다)
    blocked_reason()   자동 설치가 불가능한 이유. 가능하면 None
    download()         플랫폼 자산을 받아 설치 폴더 '옆에' 풀어 둔다
    launch_replacer()  도우미 스크립트를 띄운다. 호출 뒤 앱은 곧바로 종료한다

실행 중인 자기 자신은 덮어쓸 수 없다 (Windows는 파일 잠금 때문에 아예 불가).
그래서 폴더 교체는 반드시 앱 바깥의 스크립트가 앱 종료를 기다렸다가 수행하고,
끝나면 새 실행 파일을 다시 띄운다.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import zipfile
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

#: 릴리스 자산 이름에 들어가는 플랫폼 표시. release.yml의 압축 단계와 맞춘다.
ASSET_KEYS = {"win32": "windows", "darwin": "macos", "linux": "linux"}

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
    for asset in assets:
        if key in str(asset.get("name", "")).lower():
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


def install_root() -> Path | None:
    """실행 파일이 설치된 폴더. 소스에서 실행 중이면 None.

    onedir 빌드라 Windows/Linux는 실행 파일이 있는 폴더가 곧 설치 폴더이고,
    macOS는 .app 번들 전체가 교체 단위다.
    """
    if not getattr(sys, "frozen", False):
        return None
    executable = Path(sys.executable).resolve()
    if sys.platform == "darwin":
        for parent in executable.parents:
            if parent.suffix == ".app":
                return parent
    return executable.parent


def executable_in(root: Path) -> Path:
    """설치 폴더 안의 실행 파일 경로."""
    if sys.platform == "darwin":
        return root / "Contents" / "MacOS" / APP_NAME
    return root / (f"{APP_NAME}.exe" if sys.platform == "win32" else APP_NAME)


def _writable(path: Path) -> bool:
    """실제로 파일을 만들어 본다. os.access는 Windows에서 믿기 어렵다."""
    probe = path / f".{APP_NAME}-write-test-{os.getpid()}"
    try:
        probe.touch()
    except OSError:
        return False
    probe.unlink(missing_ok=True)
    return True


def blocked_reason(root: Path | None = None) -> str | None:
    """자동 설치를 할 수 없는 이유. 가능하면 None."""
    root = root if root is not None else install_root()
    if root is None:
        return (
            "소스에서 실행 중이라 자동 설치를 할 수 없습니다. "
            "git pull로 최신 코드를 받아 주세요."
        )
    # 설치 폴더 자체(교체)와 그 상위(작업 폴더·이름 바꾸기) 모두 필요하다.
    if not _writable(root) or not _writable(root.parent):
        return (
            f"설치 폴더에 쓸 수 없습니다 ({root}). 앱을 문서 폴더 등 "
            "쓰기 가능한 위치로 옮긴 뒤 다시 시도하거나, 직접 내려받아 주세요."
        )
    return None


# ------------------------------------------------------------------ 내려받기


def download(
    release: Release,
    root: Path,
    progress: ProgressFn | None = None,
    session: Any | None = None,
) -> Path:
    """자산을 받아 압축을 풀고, 새 설치 폴더가 될 경로를 돌려준다.

    설치 폴더와 같은 파일시스템(바로 옆)에 풀어야 마지막 교체가 이름 바꾸기
    한 번으로 끝난다. 임시 폴더를 쓰면 파일시스템을 넘나들며 복사하게 된다.
    """
    if not release.asset_url:
        raise UpdateError("내려받을 파일 주소가 없습니다.")

    workspace = root.parent / WORKSPACE_NAME
    shutil.rmtree(workspace, ignore_errors=True)
    try:
        workspace.mkdir(parents=True)
    except OSError as exc:
        raise UpdateError(f"작업 폴더를 만들지 못했습니다: {exc}") from exc

    archive = workspace / (release.asset_name or "update.zip")
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
            with open(archive, "wb") as out:
                for chunk in response.iter_content(CHUNK):
                    if not chunk:
                        continue
                    out.write(chunk)
                    done += len(chunk)
                    if progress is not None:
                        progress(done, total)
    except requests.RequestException as exc:
        shutil.rmtree(workspace, ignore_errors=True)
        raise UpdateError(f"내려받는 중 연결이 끊겼습니다: {exc}") from exc

    payload = workspace / "payload"
    try:
        extract(archive, payload)
    except UpdateError:
        shutil.rmtree(workspace, ignore_errors=True)
        raise
    archive.unlink(missing_ok=True)

    staged = payload_root(payload)
    if not executable_in(staged).exists():
        shutil.rmtree(workspace, ignore_errors=True)
        raise UpdateError("내려받은 파일에 실행 파일이 없습니다.")
    return staged


def payload_root(payload: Path) -> Path:
    """압축을 푼 결과에서 실제 설치 폴더가 될 자리를 찾는다.

    Windows 자산은 내용물이 최상위에 흩어져 있고, macOS/Linux 자산은
    SchoolNote.app / SchoolNote 폴더 하나로 감싸여 있다.
    """
    entries = [item for item in payload.iterdir() if item.name != "__MACOSX"]
    if len(entries) == 1 and entries[0].is_dir():
        return entries[0]
    return payload


# ------------------------------------------------------------------ 압축 풀기


def _safe_target(dest: Path, name: str) -> Path:
    """압축 안의 경로가 dest 밖(../)을 가리키지 못하게 막는다."""
    root = dest.resolve()
    target = (dest / name).resolve()
    if target != root and root not in target.parents:
        raise UpdateError(f"압축 파일이 폴더 밖을 가리킵니다: {name}")
    return target


def extract(archive: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    if zipfile.is_zipfile(archive):
        _extract_zip(archive, dest)
    elif tarfile.is_tarfile(archive):
        _extract_tar(archive, dest)
    else:
        raise UpdateError(f"알 수 없는 압축 형식입니다: {archive.name}")


def _extract_zip(archive: Path, dest: Path) -> None:
    """zip을 풀면서 실행 권한과 심볼릭 링크를 되살린다.

    zipfile.extractall은 유닉스 권한 비트를 버린다. 그대로 두면 새로 푼
    실행 파일에 +x가 없어 macOS/Linux에서 앱이 다시 뜨지 않는다.
    """
    with zipfile.ZipFile(archive) as bundle:
        for info in bundle.infolist():
            target = _safe_target(dest, info.filename)
            mode = info.external_attr >> 16

            if stat.S_ISLNK(mode):
                link = bundle.read(info).decode("utf-8")
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.is_symlink() or target.exists():
                    target.unlink()
                target.symlink_to(link)
                continue

            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue

            target.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(info) as source, open(target, "wb") as out:
                shutil.copyfileobj(source, out)
            if mode & 0o777:
                target.chmod(mode & 0o777)


def _extract_tar(archive: Path, dest: Path) -> None:
    with tarfile.open(archive) as bundle:
        for member in bundle.getmembers():
            _safe_target(dest, member.name)
        try:
            # 'tar' 필터는 setuid 같은 위험한 비트만 걷어내고 권한은 지킨다.
            bundle.extractall(dest, filter="tar")
        except TypeError:  # Python 3.11 이하에는 filter 인자가 없다
            bundle.extractall(dest)


# ------------------------------------------------------------------ 교체·재시작


def launch_replacer(staged: Path, root: Path) -> None:
    """앱 종료를 기다렸다 폴더를 교체하고 다시 띄우는 스크립트를 실행한다.

    호출한 쪽은 곧바로 앱을 종료해야 한다. 스크립트는 이 프로세스가 사라질
    때까지 기다리므로, 종료하지 않으면 아무 일도 일어나지 않는다.
    """
    if not executable_in(staged).exists():
        raise UpdateError("내려받은 파일이 온전하지 않습니다.")

    workspace = root.parent / WORKSPACE_NAME
    script = _write_script(staged, root, workspace)
    log.info("업데이트 스크립트를 실행합니다: %s", script)

    try:
        if sys.platform == "win32":
            detached = 0x00000008 | 0x00000200 | 0x08000000  # DETACHED|NEW_GROUP|NO_WINDOW
            subprocess.Popen(  # noqa: S603 - 우리가 만든 스크립트만 실행한다
                ["cmd", "/c", str(script)],
                creationflags=detached,
                close_fds=True,
            )
        else:
            subprocess.Popen(  # noqa: S603
                ["/bin/sh", str(script)],
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
    except OSError as exc:
        raise UpdateError(f"업데이트 스크립트를 실행하지 못했습니다: {exc}") from exc


def _write_script(staged: Path, root: Path, workspace: Path) -> Path:
    """도우미 스크립트를 시스템 임시 폴더에 쓴다.

    스크립트가 작업 폴더를 지우므로, 스크립트 자신은 작업 폴더 밖에 있어야
    실행 도중 사라지지 않는다.
    """
    pid = os.getpid()
    handle = tempfile.NamedTemporaryFile(  # noqa: SIM115 - 경로만 쓰고 닫는다
        prefix=f"{APP_NAME}-update-",
        suffix=".cmd" if sys.platform == "win32" else ".sh",
        delete=False,
        mode="w",
        encoding="utf-8" if sys.platform != "win32" else "cp949",
        newline="\r\n" if sys.platform == "win32" else "\n",
    )
    with handle as script:
        script.write(
            _windows_script(pid, staged, root, workspace)
            if sys.platform == "win32"
            else _posix_script(pid, staged, root, workspace)
        )
    return Path(handle.name)


def _windows_script(pid: int, staged: Path, root: Path, workspace: Path) -> str:
    # robocopy /MIR은 설치 폴더를 staged와 똑같이 맞춘다(없어진 파일도 정리).
    # 종료 코드 0~7은 정상이므로 확인하지 않는다.
    return f"""@echo off
:wait
tasklist /FI "PID eq {pid}" /NH | find "{pid}" >nul
if not errorlevel 1 (
  timeout /t 1 /nobreak >nul
  goto wait
)
robocopy "{staged}" "{root}" /MIR /R:2 /W:1 /NFL /NDL /NJH /NJS /NP >nul
start "" "{executable_in(root)}"
rmdir /s /q "{workspace}"
"""


def _posix_script(pid: int, staged: Path, root: Path, workspace: Path) -> str:
    backup = root.parent / BACKUP_NAME
    if sys.platform == "darwin":
        relaunch = f'open "{root}"'
    else:
        relaunch = f'"{executable_in(root)}" >/dev/null 2>&1 &'
    # 교체는 이름 바꾸기 두 번. 두 번째가 실패하면 원래 폴더를 되돌린다.
    return f"""#!/bin/sh
while kill -0 {pid} 2>/dev/null; do sleep 0.5; done
rm -rf "{backup}"
mv "{root}" "{backup}" || exit 1
if ! mv "{staged}" "{root}"; then
  mv "{backup}" "{root}"
  exit 1
fi
rm -rf "{backup}"
{relaunch}
rm -rf "{workspace}"
"""
