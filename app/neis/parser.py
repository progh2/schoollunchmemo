"""NEIS 응답 정규화.

NEIS는 상황에 따라 응답 JSON의 최상위 구조가 통째로 달라진다.

정상::

    {"mealServiceDietInfo": [
        {"head": [{"list_total_count": 1}, {"RESULT": {"CODE": "INFO-000", ...}}]},
        {"row": [{...}, ...]}
    ]}

데이터 없음/오류::

    {"RESULT": {"CODE": "INFO-200", "MESSAGE": "해당하는 데이터가 없습니다."}}

따라서 봉투를 벗기는 unwrap()에서 이 분기를 최우선으로 처리한다.
"""

from __future__ import annotations

import html
import logging
import re
from datetime import date, datetime
from typing import Any

from .codes import ResultKind, classify
from .models import MEAL_CODE_TO_KEY, Dish, MealMenu, ScheduleEvent, School

log = logging.getLogger(__name__)

_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_ALLERGEN_RE = re.compile(r"[（(]\s*([\d][\d\s.,]*)\s*[)）]\s*$")
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
_GRADE_KEYS = {
    "ONE_GRADE_EVENT_YN": 1,
    "TW_GRADE_EVENT_YN": 2,
    "THREE_GRADE_EVENT_YN": 3,
    "FR_GRADE_EVENT_YN": 4,
    "FIV_GRADE_EVENT_YN": 5,
    "SIX_GRADE_EVENT_YN": 6,
}
# 포털 문서와 실제 응답에서 학년 필드명 표기가 갈리는 사례가 있어 별칭도 함께 본다.
_GRADE_ALIASES = {
    "TWO_GRADE_EVENT_YN": 2,
    "FOUR_GRADE_EVENT_YN": 4,
    "FIVE_GRADE_EVENT_YN": 5,
}


def unwrap(payload: Any, service: str) -> tuple[ResultKind, str, str, list[dict]]:
    """응답 봉투를 벗겨 (분류, 코드, 메시지, row 목록)을 돌려준다."""
    if not isinstance(payload, dict):
        return ResultKind.UNKNOWN, "", "응답 형식이 올바르지 않습니다.", []

    # 오류·데이터 없음: RESULT가 최상위로 온다
    if "RESULT" in payload and service not in payload:
        result = payload.get("RESULT") or {}
        code = str(result.get("CODE", ""))
        message = str(result.get("MESSAGE", ""))
        return classify(code, message), code, message, []

    blocks = payload.get(service)
    if not isinstance(blocks, list):
        # 서비스명이 예상과 다를 때를 대비해 row를 가진 블록을 직접 찾는다
        blocks = next(
            (
                v
                for v in payload.values()
                if isinstance(v, list)
                and any(isinstance(b, dict) and "row" in b for b in v)
            ),
            None,
        )
    if not isinstance(blocks, list):
        return ResultKind.UNKNOWN, "", "응답 구조를 해석하지 못했습니다.", []

    code, message = "", ""
    rows: list[dict] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        for head_item in block.get("head") or []:
            if isinstance(head_item, dict) and "RESULT" in head_item:
                result = head_item["RESULT"] or {}
                code = str(result.get("CODE", ""))
                message = str(result.get("MESSAGE", ""))
        if isinstance(block.get("row"), list):
            rows.extend(r for r in block["row"] if isinstance(r, dict))

    kind = classify(code, message) if code else ResultKind.OK
    if kind is ResultKind.OK and not rows:
        kind = ResultKind.NO_DATA
    return kind, code, message, rows


# ---------------------------------------------------------------- 값 정규화


def _text(row: dict, key: str) -> str:
    value = row.get(key)
    if value is None:
        return ""
    return html.unescape(str(value)).strip()


def _parse_date(value: str) -> date | None:
    value = (value or "").strip()
    if len(value) != 8 or not value.isdigit():
        return None
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError:
        return None


def parse_dishes(raw: str) -> tuple[Dish, ...]:
    """'기장밥<br/>쇠고기미역국 (5.6.16.)' → Dish 목록."""
    dishes: list[Dish] = []
    for line in _BR_RE.split(html.unescape(raw or "")):
        name = re.sub(r"\s+", " ", line).strip().strip("*").strip()
        if not name:
            continue
        allergens: tuple[str, ...] = ()
        match = _ALLERGEN_RE.search(name)
        if match:
            numbers = [n for n in re.split(r"[.,\s]+", match.group(1)) if n.isdigit()]
            if numbers:
                allergens = tuple(numbers)
                name = name[: match.start()].strip()
        if name:
            dishes.append(Dish(name=name, allergens=allergens))
    return tuple(dishes)


def _parse_calorie(raw: str) -> float | None:
    match = _NUMBER_RE.search(raw or "")
    if not match:
        return None
    try:
        return float(match.group())
    except ValueError:
        return None


# ---------------------------------------------------------------- row → 모델


def parse_schools(rows: list[dict]) -> list[School]:
    schools: list[School] = []
    for row in rows:
        office_code = _text(row, "ATPT_OFCDC_SC_CODE")
        school_code = _text(row, "SD_SCHUL_CODE")
        if not office_code or not school_code:
            continue
        schools.append(
            School(
                office_code=office_code,
                office_name=_text(row, "ATPT_OFCDC_SC_NM"),
                school_code=school_code,
                school_name=_text(row, "SCHUL_NM"),
                school_kind=_text(row, "SCHUL_KND_SC_NM"),
                location=_text(row, "LCTN_SC_NM"),
                address=_text(row, "ORG_RDNMA"),
            )
        )
    return schools


def parse_meals(rows: list[dict]) -> list[MealMenu]:
    meals: list[MealMenu] = []
    for row in rows:
        day = _parse_date(_text(row, "MLSV_YMD"))
        if day is None:
            continue
        code = _text(row, "MMEAL_SC_CODE")
        meals.append(
            MealMenu(
                day=day,
                meal_key=MEAL_CODE_TO_KEY.get(code, code),
                meal_name=_text(row, "MMEAL_SC_NM"),
                dishes=parse_dishes(_text(row, "DDISH_NM")),
                calorie=_parse_calorie(_text(row, "CAL_INFO")),
                origin=_BR_RE.sub("\n", _text(row, "ORPLC_INFO")),
                nutrition=_BR_RE.sub("\n", _text(row, "NTR_INFO")),
            )
        )
    order = {"breakfast": 0, "lunch": 1, "dinner": 2}
    meals.sort(key=lambda m: (order.get(m.meal_key, 9), m.label))
    return meals


def parse_schedule(rows: list[dict]) -> list[ScheduleEvent]:
    events: list[ScheduleEvent] = []
    for row in rows:
        day = _parse_date(_text(row, "AA_YMD"))
        name = _text(row, "EVENT_NM")
        if day is None or not name:
            continue
        grades = {
            grade
            for key, grade in {**_GRADE_KEYS, **_GRADE_ALIASES}.items()
            if _text(row, key).upper() == "Y"
        }
        events.append(
            ScheduleEvent(
                day=day,
                name=name,
                content=_BR_RE.sub(" ", _text(row, "EVENT_CNTNT")),
                is_holiday="휴업" in _text(row, "SBTR_DD_SC_NM"),
                grades=frozenset(grades),
            )
        )
    return events
