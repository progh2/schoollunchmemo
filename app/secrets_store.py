"""NEIS 인증키 보관.

기본은 OS 자격증명 저장소(keyring).
사용할 수 없는 환경에서는 설정 디렉터리의 파일로 폴백하고,
그 사실을 UI가 사용자에게 알릴 수 있도록 is_secure()로 노출한다.
"""

from __future__ import annotations

import logging
import os
import stat

from .config import config_dir

log = logging.getLogger(__name__)

SERVICE = "SchoolNote"
ACCOUNT = "neis-api-key"
_FALLBACK_FILENAME = "neis_key.txt"

try:  # keyring이 아예 없거나 import 단계에서 실패할 수 있다
    import keyring
    import keyring.errors
except Exception as exc:  # noqa: BLE001 - 어떤 이유로든 폴백해야 한다
    keyring = None  # type: ignore[assignment]
    log.info("keyring을 사용할 수 없습니다 (%s). 파일 폴백을 사용합니다.", exc)

_secure: bool | None = None


def _fallback_path():
    return config_dir() / _FALLBACK_FILENAME


def _probe_keyring() -> bool:
    """keyring 백엔드가 실제로 동작하는지 한 번만 확인한다."""
    global _secure
    if _secure is not None:
        return _secure
    if keyring is None:
        _secure = False
        return _secure
    try:
        keyring.get_password(SERVICE, ACCOUNT)
        _secure = True
    except Exception as exc:  # noqa: BLE001 - 백엔드 부재/잠금 등
        log.info("keyring 백엔드를 쓸 수 없습니다 (%s). 파일 폴백을 사용합니다.", exc)
        _secure = False
    return _secure


def is_secure() -> bool:
    """인증키가 OS 자격증명 저장소에 안전하게 보관되는지 여부."""
    return _probe_keyring()


def get_key() -> str:
    if _probe_keyring():
        try:
            return (keyring.get_password(SERVICE, ACCOUNT) or "").strip()
        except Exception as exc:  # noqa: BLE001
            log.warning("keyring에서 인증키를 읽지 못했습니다: %s", exc)
            return ""
    path = _fallback_path()
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        log.warning("인증키 파일을 읽지 못했습니다: %s", exc)
        return ""


def set_key(key: str) -> None:
    key = (key or "").strip()
    if not key:
        delete_key()
        return
    if _probe_keyring():
        try:
            keyring.set_password(SERVICE, ACCOUNT, key)
            return
        except Exception as exc:  # noqa: BLE001
            log.warning("keyring에 저장하지 못해 파일로 폴백합니다: %s", exc)
    path = _fallback_path()
    try:
        path.write_text(key, encoding="utf-8")
        if os.name != "nt":  # 소유자만 읽을 수 있게
            path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError as exc:
        log.error("인증키를 저장하지 못했습니다: %s", exc)


def delete_key() -> None:
    if keyring is not None and _probe_keyring():
        try:
            keyring.delete_password(SERVICE, ACCOUNT)
        except Exception:  # noqa: BLE001 - 없으면 그만이다
            pass
    path = _fallback_path()
    if path.exists():
        try:
            path.unlink()
        except OSError:
            pass
