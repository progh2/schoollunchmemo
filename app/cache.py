"""날짜 단위 응답 캐시.

정규화 이전의 원본 row 목록을 그대로 보관한다.
파서가 바뀌어도 캐시를 버릴 필요가 없고, 모델 직렬화 코드도 필요 없다.
네트워크가 끊겼을 때 마지막으로 성공한 내용을 계속 보여주는 근거가 된다.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .config import data_dir

log = logging.getLogger(__name__)

RETENTION_DAYS = 30


def _cache_root() -> Path:
    return data_dir() / "cache"


def _path(school_code: str, day: date) -> Path:
    return _cache_root() / school_code / f"{day:%Y%m%d}.json"


def load(school_code: str, day: date) -> dict[str, Any] | None:
    path = _path(school_code, day)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.debug("캐시를 읽지 못했습니다: %s", exc)
        return None
    return data if isinstance(data, dict) else None


def save(
    school_code: str,
    day: date,
    meal_rows: list[dict],
    schedule_rows: list[dict],
) -> None:
    path = _path(school_code, day)
    payload = {
        "saved_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "meal_rows": meal_rows,
        "schedule_rows": schedule_rows,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
    except OSError as exc:
        log.debug("캐시를 저장하지 못했습니다: %s", exc)


def prune(retention_days: int = RETENTION_DAYS) -> None:
    """오래된 캐시 파일을 지운다. 앱 시작 시 한 번 호출한다."""
    root = _cache_root()
    if not root.exists():
        return
    cutoff = date.today() - timedelta(days=retention_days)
    for file in root.glob("*/*.json"):
        try:
            day = datetime.strptime(file.stem, "%Y%m%d").date()
        except ValueError:
            continue
        if day < cutoff:
            try:
                file.unlink()
            except OSError:
                pass
