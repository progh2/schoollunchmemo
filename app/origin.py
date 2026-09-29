"""원산지 목록에서 오늘 메뉴에 쓰인 재료를 가려낸다 (#47).

학교가 올리는 원산지(ORPLC_INFO)는 대개 매일 같은 고정 목록이다. 오늘
식재료가 아니라 급식 전체의 원산지 표시라서, 그대로 알레르기 낱말을
칠하면 쓰지도 않은 꽃게가 매일 빨갛게 뜬다.

NEIS에는 요리별 재료가 없으므로 **근거가 있을 때만** '쓰였다'고 본다.

    1. 메뉴 알레르기 번호에 그 재료가 있다   돼지고기=10, 콩=5, 꽃게=8 …
    2. 메뉴 이름에 그 재료가 보인다         낙지볶음 → 낙지, 제육 → 돼지고기

근거가 없다고 안 쓰였다는 뜻은 아니다. 화면에서는 흐리게만 하고 숨기지 않는다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import allergens
from .neis.models import Dish

#: 원산지 재료 이름 → 메뉴 이름에서 찾을 낱말. 없으면 재료 이름 자체로 찾는다.
NAME_HINTS: dict[str, tuple[str, ...]] = {
    "쇠고기": ("쇠고기", "소고기", "우육", "한우", "불고기", "갈비", "사골", "육개장", "장조림"),
    "돼지고기": (
        "돼지", "돈육", "제육", "삼겹", "목살", "돈까스", "돈가스", "수육",
        "햄", "소시지", "베이컨", "탕수육", "비엔나",
    ),
    "닭고기": ("닭", "치킨", "계육", "너겟", "삼계"),
    "오리고기": ("오리",),
    "쌀": ("밥", "쌀", "죽", "떡", "누룽", "미음"),
    "배추": ("배추", "김치", "겉절이"),
    "고춧가루": ("김치", "깍두기", "석박지", "겉절이", "고추", "매콤", "매운", "떡볶이", "제육", "짬뽕", "육개장"),
    "콩": ("콩", "두부", "두유"),
    "낙지": ("낙지",),
    "고등어": ("고등어",),
    "갈치": ("갈치",),
    "오징어": ("오징어",),
    "꽃게": ("꽃게", "게살", "게장"),
    "참조기": ("조기", "굴비"),
    "명태": ("명태", "동태", "황태", "코다리", "북어"),
}

#: 재료 이름 끝에 붙어 구분만 하는 말. '쇠고기 식육가공품' → '쇠고기'
_QUALIFIERS = re.compile(r"\(.*?\)|식육가공품|가공품|\s+")


@dataclass(frozen=True)
class OriginLine:
    text: str  # 원래 한 줄. 예: "꽃게 : 국내산"
    ingredient: str  # 재료 이름. 예: "꽃게"
    used: bool  # 오늘 메뉴에 쓰였다는 근거가 있는지
    alert: bool  # 쓰였고, 내가 등록한 알레르기 재료인지


def ingredient_of(line: str) -> str:
    return line.split(":", 1)[0].strip()


def core_name(ingredient: str) -> str:
    """'쇠고기(종류)', '쇠고기 식육가공품' → '쇠고기'."""
    return _QUALIFIERS.sub("", ingredient)


def codes_of(ingredient: str) -> set[int]:
    """재료 이름이 가리키는 알레르기 번호. '꽃게' → {8}, '쌀' → {}."""
    return allergens.found_in_text(core_name(ingredient), set(allergens.ALLERGENS))


def _mentioned(ingredient: str, dish_names: list[str]) -> bool:
    core = core_name(ingredient)
    if not core:
        return False
    hints = NAME_HINTS.get(core, (core,))
    return any(hint in name for name in dish_names for hint in hints)


def classify(origin: str, dishes: tuple[Dish, ...] | list[Dish], alerts: set[int]) -> list[OriginLine]:
    """원산지 목록 한 줄씩 쓰였는지, 알레르기 경고할지 정한다."""
    meal_codes: set[int] = set()
    for dish in dishes:
        meal_codes |= {int(n) for n in dish.allergens if str(n).isdigit()}
    dish_names = [dish.name for dish in dishes]

    lines: list[OriginLine] = []
    for raw in origin.splitlines():
        text = raw.strip()
        if not text:
            continue
        if ":" in text and not text.split(":", 1)[1].strip():
            continue  # '비고 :'처럼 값이 빈 줄
        ingredient = ingredient_of(text)
        codes = codes_of(ingredient)
        used = bool(codes & meal_codes) or _mentioned(ingredient, dish_names)
        lines.append(
            OriginLine(
                text=text,
                ingredient=ingredient,
                used=used,
                alert=used and bool(codes & set(alerts)),
            )
        )
    return lines
