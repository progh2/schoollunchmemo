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

#: 달력용 월 캐시 파일 이름 앞에 붙인다. 날짜 캐시와 한 폴더에 섞여 있으므로
#: 파일 이름만 보고 구분할 수 있어야 한다.
MONTH_PREFIX = "month-"


def _cache_root() -> Path:
    return data_dir() / "cache"


def _path(school_code: str, day: date) -> Path:
    return _cache_root() / school_code / f"{day:%Y%m%d}.json"


def _month_path(school_code: str, year: int, month: int) -> Path:
    return _cache_root() / school_code / f"{MONTH_PREFIX}{year:04d}{month:02d}.json"


def _read(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.debug("캐시를 읽지 못했습니다: %s", exc)
        return None
    return data if isinstance(data, dict) else None


def _write(path: Path, meal_rows: list[dict], schedule_rows: list[dict]) -> None:
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


def load(school_code: str, day: date) -> dict[str, Any] | None:
    return _read(_path(school_code, day))


def save(
    school_code: str,
    day: date,
    meal_rows: list[dict],
    schedule_rows: list[dict],
) -> None:
    _write(_path(school_code, day), meal_rows, schedule_rows)


def load_month(school_code: str, year: int, month: int) -> dict[str, Any] | None:
    return _read(_month_path(school_code, year, month))


def save_month(
    school_code: str,
    year: int,
    month: int,
    meal_rows: list[dict],
    schedule_rows: list[dict],
) -> None:
    _write(_month_path(school_code, year, month), meal_rows, schedule_rows)


def saved_today(cached: dict[str, Any] | None) -> bool:
    """오늘 받아 둔 캐시인지. 아직 지나지 않은 달을 다시 받을지 판단한다."""
    if not cached:
        return False
    try:
        return datetime.fromisoformat(cached.get("saved_at", "")).date() == date.today()
    except (TypeError, ValueError):
        return False


def _covers_until(stem: str) -> date | None:
    """캐시 파일이 담고 있는 마지막 날. 이름 규칙을 모르는 파일은 None."""
    if stem.startswith(MONTH_PREFIX):
        try:
            first = datetime.strptime(stem[len(MONTH_PREFIX):], "%Y%m").date()
        except ValueError:
            return None
        # 그 달의 마지막 날. 달이 다 지나야 버릴 수 있다.
        return date(
            first.year + first.month // 12, first.month % 12 + 1, 1
        ) - timedelta(days=1)
    try:
        return datetime.strptime(stem, "%Y%m%d").date()
    except ValueError:
        return None


def prune(retention_days: int = RETENTION_DAYS) -> None:
    """오래된 캐시 파일을 지운다. 앱 시작 시 한 번 호출한다."""
    root = _cache_root()
    if not root.exists():
        return
    cutoff = date.today() - timedelta(days=retention_days)
    for file in root.glob("*/*.json"):
        covers_until = _covers_until(file.stem)
        if covers_until is not None and covers_until < cutoff:
            try:
                file.unlink()
            except OSError:
                pass
