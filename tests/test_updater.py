"""업데이트 모듈 테스트 (#27).

네트워크·파일 교체는 건드리지 않는다. 버전 비교, 자산 고르기, 압축 풀기처럼
혼자 검증할 수 있는 부분만 본다.
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
import time

import pytest
import requests

from app import updater


class TestVersionCompare:
    @pytest.mark.parametrize(
        "text, expected",
        [
            ("v0.3.1", (0, 3, 1)),
            ("0.4", (0, 4)),
            ("급식쪽지 v1.2.0", (1, 2, 0)),
            ("", ()),
            ("nightly", ()),
        ],
    )
    def test_parse(self, text, expected):
        assert updater.parse_version(text) == expected

    @pytest.mark.parametrize(
        "candidate, current, expected",
        [
            ("v0.4.0", "0.3.1", True),
            ("v0.3.2", "0.3.1", True),
            ("v1.0", "0.9.9", True),
            ("v0.3.1", "0.3.1", False),
            ("v0.3.0", "0.3.1", False),
            ("v0.4", "0.4.0", False),  # 자리수만 다른 같은 버전
            ("v0.4.1", "0.4", True),
            ("nightly", "0.3.1", False),  # 버전을 못 읽으면 올리지 않는다
        ],
    )
    def test_is_newer(self, candidate, current, expected):
        assert updater.is_newer(candidate, current) is expected


class TestAssetPick:
    ASSETS = [
        {"name": "SchoolNote-v0.4.0-linux-x64"},
        {"name": "SchoolNote-v0.4.0-macos.dmg"},
        {"name": "SchoolNote-v0.4.0-windows-x64.exe"},
    ]

    @pytest.mark.parametrize(
        "key, expected",
        [
            ("windows", "SchoolNote-v0.4.0-windows-x64.exe"),
            ("macos", "SchoolNote-v0.4.0-macos.dmg"),
            ("linux", "SchoolNote-v0.4.0-linux-x64"),
        ],
    )
    def test_picks_matching_platform(self, key, expected):
        assert updater.pick_asset(self.ASSETS, key)["name"] == expected

    def test_unknown_platform_gets_nothing(self):
        assert updater.pick_asset(self.ASSETS, "freebsd") is None

    @pytest.mark.parametrize(
        "legacy, key",
        [
            ("SchoolNote-v0.3.1-windows-x64.zip", "windows"),
            ("SchoolNote-v0.3.1-macos.zip", "macos"),
            ("SchoolNote-v0.3.1-linux-x64.tar.gz", "linux"),
        ],
    )
    def test_legacy_archives_are_not_picked(self, legacy, key):
        """예전 압축 자산을 받아 실행 파일 자리에 끼우면 앱이 깨진다 (#29)."""
        assert updater.pick_asset([{"name": legacy}], key) is None


_ASSET_NAMES = {
    "windows": "SchoolNote-{tag}-windows-x64.exe",
    "macos": "SchoolNote-{tag}-macos.dmg",
    "linux": "SchoolNote-{tag}-linux-x64",
}


class _FakeResponse:
    def __init__(self, payload=None, status_code=200, body=b""):
        self._payload = payload
        self.status_code = status_code
        self._body = body
        self.headers = {"Content-Length": str(len(body))} if body else {}

    def json(self):
        return self._payload

    def iter_content(self, size):
        for start in range(0, len(self._body), size):
            yield self._body[start : start + size]

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


class _FakeSession:
    def __init__(self, response=None, error=None):
        self._response = response
        self._error = error
        self.calls: list[str] = []

    def get(self, url, **_kwargs):
        self.calls.append(url)
        if self._error is not None:
            raise self._error
        return self._response


def _release_payload(tag="v9.9.9"):
    return {
        "tag_name": tag,
        "body": "이번 버전에서 바뀐 것",
        "html_url": f"https://example.invalid/{tag}",
        "assets": [
            {
                "name": pattern.format(tag=tag),
                "browser_download_url": f"https://example.invalid/{key}",
                "size": 42 * 1024 * 1024,
            }
            for key, pattern in _ASSET_NAMES.items()
        ],
    }


class TestFetchLatest:
    def test_returns_release_for_this_platform(self):
        session = _FakeSession(_FakeResponse(_release_payload()))
        release = updater.fetch_latest(session=session)

        assert release.tag == "v9.9.9"
        assert release.is_update is True
        assert release.asset_name == _ASSET_NAMES[updater.platform_key()].format(
            tag="v9.9.9"
        )
        assert release.size_text == "42MB"
        assert session.calls == [updater.LATEST_URL]

    def test_older_tag_is_not_an_update(self):
        session = _FakeSession(_FakeResponse(_release_payload("v0.0.1")))
        assert updater.fetch_latest(session=session).is_update is False

    def test_network_error_becomes_user_message(self):
        session = _FakeSession(error=requests.ConnectionError("boom"))
        with pytest.raises(updater.UpdateError, match="네트워크"):
            updater.fetch_latest(session=session)

    def test_missing_release_is_reported(self):
        session = _FakeSession(_FakeResponse({}, status_code=404))
        with pytest.raises(updater.UpdateError, match="릴리스"):
            updater.fetch_latest(session=session)

    def test_release_without_our_asset_is_reported(self):
        payload = _release_payload()
        payload["assets"] = [{"name": "SOURCE.tar.gz"}]
        session = _FakeSession(_FakeResponse(payload))
        with pytest.raises(updater.UpdateError, match="파일이 없습니다"):
            updater.fetch_latest(session=session)


def _binary_release(body: bytes) -> updater.Release:
    return updater.Release(
        tag="v9.9.9",
        notes="",
        page_url="",
        asset_name="SchoolNote-v9.9.9-new",
        asset_url="https://example.invalid/new",
        asset_size=len(body),
    )


@pytest.mark.skipif(sys.platform == "darwin", reason="macOS는 .dmg를 마운트한다")
class TestDownloadBinary:
    """Windows/Linux onefile: 받은 파일이 곧 새 실행 파일이다."""

    MAGIC = updater._MAGIC.get(updater.platform_key(), b"")

    def test_staged_next_to_target_and_executable(self, tmp_path):
        body = self.MAGIC + b"-new-binary"
        target = tmp_path / "SchoolNote"
        seen = []

        staged = updater.download(
            _binary_release(body),
            target,
            progress=lambda done, total: seen.append((done, total)),
            session=_FakeSession(_FakeResponse(body=body)),
        )

        # 같은 폴더(같은 파일시스템)에 두어야 이름 바꾸기 한 번으로 끝난다
        assert staged.parent == tmp_path / updater.WORKSPACE_NAME
        assert staged.read_bytes() == body
        assert seen[-1] == (len(body), len(body))
        if sys.platform != "win32":
            assert staged.stat().st_mode & stat.S_IXUSR

    def test_error_page_is_not_mistaken_for_a_binary(self, tmp_path):
        body = b"<html>rate limited</html>"
        with pytest.raises(updater.UpdateError, match="실행 파일이 아닙니다"):
            updater.download(
                _binary_release(body),
                tmp_path / "SchoolNote",
                session=_FakeSession(_FakeResponse(body=body)),
            )
        assert not (tmp_path / updater.WORKSPACE_NAME).exists()

    def test_truncated_download_is_rejected(self, tmp_path):
        body = self.MAGIC + b"-new-binary"
        release = _binary_release(body)
        short = _FakeResponse(body=body[:-3])
        with pytest.raises(updater.UpdateError, match="크기"):
            updater.download(release, tmp_path / "SchoolNote", session=_FakeSession(short))

    def test_http_error_is_reported(self, tmp_path):
        with pytest.raises(updater.UpdateError, match="HTTP 503"):
            updater.download(
                _binary_release(b"x"),
                tmp_path / "SchoolNote",
                session=_FakeSession(_FakeResponse(status_code=503)),
            )


class TestInstallLocation:
    def test_source_run_has_no_target(self):
        """테스트는 소스에서 돈다. 자동 설치 대상이 아니다."""
        assert updater.install_target() is None

    def test_source_run_is_blocked_with_a_reason(self):
        reason = updater.blocked_reason()
        assert reason is not None
        assert "소스" in reason

    @pytest.mark.skipif(
        sys.platform == "win32", reason="Windows에서는 chmod로 폴더를 잠글 수 없다"
    )
    def test_readonly_folder_is_blocked(self, tmp_path):
        folder = tmp_path / "apps"
        folder.mkdir()
        target = folder / "SchoolNote"
        target.write_bytes(b"old")
        folder.chmod(0o500)
        try:
            reason = updater.blocked_reason(target)
        finally:
            folder.chmod(0o700)

        assert reason is not None
        assert "쓸 수 없습니다" in reason

    def test_writable_folder_is_allowed(self, tmp_path):
        target = tmp_path / "SchoolNote.exe"
        target.write_bytes(b"old")
        assert updater.blocked_reason(target) is None

    def test_bundle_executable_path(self, tmp_path):
        bundle = tmp_path / "SchoolNote.app"
        assert updater.bundle_executable(bundle) == (
            bundle / "Contents" / "MacOS" / "SchoolNote"
        )


class TestReplacerScript:
    def test_refuses_missing_download(self, tmp_path):
        with pytest.raises(updater.UpdateError, match="다시 시도"):
            updater.launch_replacer(tmp_path / "nope", tmp_path / "SchoolNote")

    def test_windows_script_waits_retries_and_relaunches(self, tmp_path):
        target = tmp_path / "SchoolNote.exe"
        workspace = tmp_path / updater.WORKSPACE_NAME
        staged = workspace / "SchoolNote-v9-windows-x64.exe"
        script = updater.replacer_script(4242, staged, target, workspace, "win32")

        assert 'tasklist /FI "PID eq 4242"' in script  # 앱이 죽을 때까지 기다린다
        assert f'move /y "{staged}" "{target}"' in script
        assert "geq 30" in script  # 부트로더가 exe를 놓을 때까지 되풀이
        assert f'start "" "{target}"' in script
        # 숨은 콘솔에서 timeout은 즉시 실패해 대기 없이 헛돈다
        assert "timeout " not in script
        assert "ping -n 2 127.0.0.1" in script


def _dead_pid() -> int:
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait()
    return process.pid


def _wait_for(path, seconds=10.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if path.exists() and path.stat().st_size:
            return True
        time.sleep(0.1)
    return False


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX 셸 스크립트를 실제로 돌린다")
class TestReplacerEndToEnd:
    """스크립트를 실제로 실행해 교체·재실행·정리까지 확인한다."""

    def test_linux_swaps_single_file_and_relaunches(self, tmp_path):
        marker = tmp_path / "relaunched"
        target = tmp_path / "SchoolNote"
        target.write_text("#!/bin/sh\necho old > /dev/null\n", encoding="utf-8")
        workspace = tmp_path / updater.WORKSPACE_NAME
        workspace.mkdir()
        staged = workspace / "SchoolNote-v9-linux-x64"
        staged.write_text(f"#!/bin/sh\necho new > '{marker}'\n", encoding="utf-8")

        script = tmp_path / "update.sh"
        script.write_text(
            updater.replacer_script(_dead_pid(), staged, target, workspace, "linux"),
            encoding="utf-8",
        )
        subprocess.run(["/bin/sh", str(script)], check=True, timeout=30)

        assert "echo new" in target.read_text(encoding="utf-8")
        assert target.stat().st_mode & stat.S_IXUSR
        assert not workspace.exists()
        assert _wait_for(marker), "새 실행 파일이 다시 뜨지 않았다"

    def test_macos_swaps_bundle_and_relaunches(self, tmp_path):
        marker = tmp_path / "opened"
        fake_bin = tmp_path / "bin"
        fake_bin.mkdir()
        fake_open = fake_bin / "open"
        fake_open.write_text(f"#!/bin/sh\necho \"$1\" > '{marker}'\n", encoding="utf-8")
        fake_open.chmod(0o755)

        target = tmp_path / "SchoolNote.app"
        (target / "Contents").mkdir(parents=True)
        (target / "Contents" / "old").write_text("old", encoding="utf-8")
        workspace = tmp_path / updater.WORKSPACE_NAME
        staged = workspace / "SchoolNote.app"
        (staged / "Contents").mkdir(parents=True)
        (staged / "Contents" / "new").write_text("new", encoding="utf-8")

        script = tmp_path / "update.sh"
        script.write_text(
            updater.replacer_script(_dead_pid(), staged, target, workspace, "darwin"),
            encoding="utf-8",
        )
        env = {**os.environ, "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}"}
        subprocess.run(["/bin/sh", str(script)], check=True, timeout=30, env=env)

        assert (target / "Contents" / "new").exists()
        assert not (target / "Contents" / "old").exists()
        assert not (tmp_path / updater.BACKUP_NAME).exists()
        assert not workspace.exists()
        assert _wait_for(marker)
        assert marker.read_text(encoding="utf-8").strip() == str(target)


class TestDownloadGuards:
    def test_missing_url_fails_before_touching_disk(self, tmp_path):
        release = updater.Release(
            tag="v9.9.9",
            notes="",
            page_url="",
            asset_name="SchoolNote.exe",
            asset_url="",
            asset_size=0,
        )
        with pytest.raises(updater.UpdateError, match="주소가 없습니다"):
            updater.download(release, tmp_path / "SchoolNote")
        assert not (tmp_path / updater.WORKSPACE_NAME).exists()


def test_repo_slug_points_at_this_project():
    assert updater.REPO_SLUG == "progh2/schoollunchmemo"
    assert updater.LATEST_URL.endswith("/repos/progh2/schoollunchmemo/releases/latest")
