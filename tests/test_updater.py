"""업데이트 모듈 테스트 (#27).

네트워크·파일 교체는 건드리지 않는다. 버전 비교, 자산 고르기, 압축 풀기처럼
혼자 검증할 수 있는 부분만 본다.
"""

from __future__ import annotations

import stat
import sys
import tarfile
import zipfile

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
        {"name": "SchoolNote-v0.4.0-linux-x64.tar.gz"},
        {"name": "SchoolNote-v0.4.0-macos.zip"},
        {"name": "SchoolNote-v0.4.0-windows-x64.zip"},
    ]

    @pytest.mark.parametrize(
        "key, expected",
        [
            ("windows", "SchoolNote-v0.4.0-windows-x64.zip"),
            ("macos", "SchoolNote-v0.4.0-macos.zip"),
            ("linux", "SchoolNote-v0.4.0-linux-x64.tar.gz"),
        ],
    )
    def test_picks_matching_platform(self, key, expected):
        assert updater.pick_asset(self.ASSETS, key)["name"] == expected

    def test_unknown_platform_gets_nothing(self):
        assert updater.pick_asset(self.ASSETS, "freebsd") is None


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


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
                "name": f"SchoolNote-{tag}-{key}.zip",
                "browser_download_url": f"https://example.invalid/{key}.zip",
                "size": 42 * 1024 * 1024,
            }
            for key in ("windows", "macos", "linux")
        ],
    }


class TestFetchLatest:
    def test_returns_release_for_this_platform(self):
        session = _FakeSession(_FakeResponse(_release_payload()))
        release = updater.fetch_latest(session=session)

        assert release.tag == "v9.9.9"
        assert release.is_update is True
        assert updater.platform_key() in release.asset_name
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


class TestExtract:
    @pytest.mark.skipif(sys.platform == "win32", reason="Windows에는 실행 비트가 없다")
    def test_zip_keeps_executable_bit(self, tmp_path):
        """zipfile 기본 동작은 권한을 버린다. 잃으면 새 앱이 실행되지 않는다."""
        archive = tmp_path / "app.zip"
        with zipfile.ZipFile(archive, "w") as bundle:
            info = zipfile.ZipInfo("SchoolNote")
            info.external_attr = (stat.S_IFREG | 0o755) << 16
            bundle.writestr(info, "binary")

        dest = tmp_path / "out"
        updater.extract(archive, dest)
        assert (dest / "SchoolNote").stat().st_mode & stat.S_IXUSR

    def test_zip_cannot_escape_destination(self, tmp_path):
        archive = tmp_path / "evil.zip"
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("../escaped.txt", "nope")

        with pytest.raises(updater.UpdateError, match="폴더 밖"):
            updater.extract(archive, tmp_path / "out")
        assert not (tmp_path / "escaped.txt").exists()

    def test_tar_cannot_escape_destination(self, tmp_path):
        payload = tmp_path / "payload.txt"
        payload.write_text("nope", encoding="utf-8")
        archive = tmp_path / "evil.tar.gz"
        with tarfile.open(archive, "w:gz") as bundle:
            bundle.add(payload, arcname="../escaped.txt")

        with pytest.raises(updater.UpdateError, match="폴더 밖"):
            updater.extract(archive, tmp_path / "out")

    def test_unknown_archive_is_rejected(self, tmp_path):
        archive = tmp_path / "plain.bin"
        archive.write_bytes(b"not an archive")
        with pytest.raises(updater.UpdateError, match="압축 형식"):
            updater.extract(archive, tmp_path / "out")


class TestPayloadRoot:
    def test_single_folder_is_unwrapped(self, tmp_path):
        """macOS/Linux 자산은 폴더 하나로 감싸여 있다."""
        inner = tmp_path / "SchoolNote"
        inner.mkdir()
        assert updater.payload_root(tmp_path) == inner

    def test_macos_metadata_folder_is_ignored(self, tmp_path):
        inner = tmp_path / "SchoolNote.app"
        inner.mkdir()
        (tmp_path / "__MACOSX").mkdir()
        assert updater.payload_root(tmp_path) == inner

    def test_flat_contents_stay_put(self, tmp_path):
        """Windows 자산은 내용물이 최상위에 흩어져 있다."""
        (tmp_path / "SchoolNote.exe").write_text("x", encoding="utf-8")
        (tmp_path / "_internal").mkdir()
        assert updater.payload_root(tmp_path) == tmp_path


class TestInstallLocation:
    def test_source_run_has_no_install_root(self):
        """테스트는 소스에서 돈다. 자동 설치 대상이 아니다."""
        assert updater.install_root() is None

    def test_source_run_is_blocked_with_a_reason(self):
        reason = updater.blocked_reason()
        assert reason is not None
        assert "소스" in reason

    @pytest.mark.skipif(
        sys.platform == "win32", reason="Windows에서는 chmod로 폴더를 잠글 수 없다"
    )
    def test_readonly_folder_is_blocked(self, tmp_path):
        root = tmp_path / "SchoolNote"
        root.mkdir()
        root.chmod(0o500)
        try:
            reason = updater.blocked_reason(root)
        finally:
            root.chmod(0o700)

        assert reason is not None
        assert "쓸 수 없습니다" in reason

    def test_writable_folder_is_allowed(self, tmp_path):
        root = tmp_path / "SchoolNote"
        root.mkdir()
        assert updater.blocked_reason(root) is None

    def test_executable_path_matches_platform(self, tmp_path):
        found = updater.executable_in(tmp_path)
        if sys.platform == "darwin":
            assert found == tmp_path / "Contents" / "MacOS" / "SchoolNote"
        elif sys.platform == "win32":
            assert found == tmp_path / "SchoolNote.exe"
        else:
            assert found == tmp_path / "SchoolNote"


class TestReplacerScript:
    def test_refuses_payload_without_executable(self, tmp_path):
        staged = tmp_path / "staged"
        staged.mkdir()
        with pytest.raises(updater.UpdateError, match="온전하지"):
            updater.launch_replacer(staged, tmp_path / "SchoolNote")

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX 스크립트 전용")
    def test_posix_script_waits_then_swaps_and_restores(self, tmp_path):
        root = tmp_path / "SchoolNote"
        staged = tmp_path / ".SchoolNote-update" / "payload" / "SchoolNote"
        script = updater._posix_script(4242, staged, root, staged.parent.parent)

        assert "kill -0 4242" in script  # 앱이 죽을 때까지 기다린다
        assert f'mv "{root}"' in script
        assert f'mv "{staged}" "{root}"' in script
        assert f'mv "{tmp_path / ".SchoolNote-old"}" "{root}"' in script  # 실패 시 복구

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows 스크립트 전용")
    def test_windows_script_waits_then_mirrors(self, tmp_path):
        root = tmp_path / "SchoolNote"
        workspace = tmp_path / ".SchoolNote-update"
        script = updater._windows_script(4242, workspace / "payload", root, workspace)

        assert "PID eq 4242" in script
        assert "/MIR" in script
        assert str(updater.executable_in(root)) in script


class TestDownload:
    def test_missing_url_fails_before_touching_disk(self, tmp_path):
        release = updater.Release(
            tag="v9.9.9",
            notes="",
            page_url="",
            asset_name="SchoolNote.zip",
            asset_url="",
            asset_size=0,
        )
        with pytest.raises(updater.UpdateError, match="주소가 없습니다"):
            updater.download(release, tmp_path / "SchoolNote")
        assert not (tmp_path / updater.WORKSPACE_NAME).exists()


def test_repo_slug_points_at_this_project():
    assert updater.REPO_SLUG == "progh2/schoollunchmemo"
    assert updater.LATEST_URL.endswith("/repos/progh2/schoollunchmemo/releases/latest")
