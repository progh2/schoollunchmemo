"""설정 로드·저장.

설정 파일은 OS별 표준 설정 디렉터리에 둔다.
인증키는 여기에 저장하지 않는다 (secrets_store 참조).
"""

from __future__ import annotations

import copy
import json
import logging
from pathlib import Path
from typing import Any

from PySide6.QtCore import QStandardPaths

from . import APP_NAME

log = logging.getLogger(__name__)

CONFIG_VERSION = 1

DEFAULTS: dict[str, Any] = {
    "version": CONFIG_VERSION,
    "school": None,
    "display": {
        "meal_types": ["lunch"],
        "grade_filter": None,
        "show_allergy": False,
        "show_calorie": True,
        "show_origin": False,
        "always_on_top": True,
        "opacity": 0.95,
        "color": "yellow",
        "start_on_boot": False,
        "show_on_start": True,
    },
    "window": {"x": None, "y": None},
    "state": {"last_sync": None},
}


def config_dir() -> Path:
    """OS별 설정 디렉터리. 없으면 만든다."""
    base = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppConfigLocation
    )
    if not base:  # Qt가 경로를 못 주는 예외적인 환경
        base = str(Path.home() / f".{APP_NAME.lower()}")
    path = Path(base)
    path.mkdir(parents=True, exist_ok=True)
    return path


def data_dir() -> Path:
    """캐시 등 앱 데이터 디렉터리."""
    base = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppDataLocation
    )
    if not base:
        base = str(Path.home() / f".{APP_NAME.lower()}")
    path = Path(base)
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_path() -> Path:
    return config_dir() / "config.json"


def _deep_merge(base: dict, override: dict) -> dict:
    """기본값 위에 저장된 값을 덮어쓴다. 새 버전에서 키가 추가돼도 깨지지 않는다."""
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


class Config:
    """설정 접근자. 항상 기본값과 병합된 상태를 보장한다."""

    def __init__(self, data: dict[str, Any] | None = None) -> None:
        self.data = _deep_merge(DEFAULTS, data or {})

    # ---- 저장소 ----

    @classmethod
    def load(cls) -> Config:
        path = config_path()
        if not path.exists():
            return cls()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("설정 파일을 읽지 못해 기본값으로 시작합니다: %s", exc)
            return cls()
        if not isinstance(raw, dict):
            log.warning("설정 파일 형식이 올바르지 않아 기본값으로 시작합니다.")
            return cls()
        return cls(cls._migrate(raw))

    def save(self) -> None:
        path = config_path()
        tmp = path.with_suffix(".json.tmp")
        try:
            tmp.write_text(
                json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            tmp.replace(path)  # 쓰다 만 파일이 남지 않도록 원자적 교체
        except OSError as exc:
            log.error("설정을 저장하지 못했습니다: %s", exc)

    @staticmethod
    def _migrate(raw: dict[str, Any]) -> dict[str, Any]:
        """설정 스키마 마이그레이션. 지금은 버전 1뿐이라 통과시킨다."""
        raw["version"] = CONFIG_VERSION
        return raw

    # ---- 접근자 ----

    @property
    def display(self) -> dict[str, Any]:
        return self.data["display"]

    @property
    def window(self) -> dict[str, Any]:
        return self.data["window"]

    @property
    def state(self) -> dict[str, Any]:
        return self.data["state"]

    @property
    def school(self) -> dict[str, Any] | None:
        return self.data.get("school")

    @school.setter
    def school(self, value: dict[str, Any] | None) -> None:
        self.data["school"] = value

    @property
    def is_configured(self) -> bool:
        school = self.school
        return bool(school and school.get("office_code") and school.get("school_code"))
