"""학교급식 알레르기 유발식품 표준 코드 (19종).

NEIS 식단의 요리명 뒤에 붙는 괄호 안 번호가 이 코드다.
원산지·재료 문구에는 번호가 없으므로 이름으로 찾는다. 어디까지나 눈에
띄게 해주는 보조 장치이고, 최종 확인은 학교 공지를 따라야 한다.
"""

from __future__ import annotations

import re

#: 번호 → 표시 이름
ALLERGENS: dict[int, str] = {
    1: "난류",
    2: "우유",
    3: "메밀",
    4: "땅콩",
    5: "대두",
    6: "밀",
    7: "고등어",
    8: "게",
    9: "새우",
    10: "돼지고기",
    11: "복숭아",
    12: "토마토",
    13: "아황산류",
    14: "호두",
    15: "닭고기",
    16: "쇠고기",
    17: "오징어",
    18: "조개류",
    19: "잣",
}

#: 번호 → 재료 문구에서 찾을 낱말들
KEYWORDS: dict[int, tuple[str, ...]] = {
    1: ("난류", "계란", "달걀", "메추리알"),
    2: ("우유", "유제품", "치즈", "버터", "생크림", "요구르트"),
    3: ("메밀",),
    4: ("땅콩",),
    5: ("대두", "두부", "된장", "간장", "콩나물", "콩"),
    6: ("밀가루", "밀"),
    7: ("고등어",),
    8: ("꽃게", "게살", "게맛살", "게"),
    9: ("새우",),
    10: ("돼지고기", "돈육", "돼지", "베이컨", "햄"),
    11: ("복숭아",),
    12: ("토마토", "케첩"),
    13: ("아황산",),
    14: ("호두",),
    15: ("닭고기", "계육", "닭"),
    16: ("쇠고기", "소고기", "우육", "사골"),
    17: ("오징어",),
    18: ("조개", "바지락", "굴", "전복", "홍합", "모시조개"),
    19: ("잣",),
}


def label(code: int) -> str:
    return ALLERGENS.get(code, str(code))


def labels(codes) -> str:
    """설정 요약 등에 쓸 '우유, 대두, 새우' 형태의 문자열."""
    return ", ".join(label(code) for code in sorted(codes))


def matched(dish_allergens, alerts: set[int]) -> set[int]:
    """요리에 붙은 번호 중 사용자가 등록한 것과 겹치는 것."""
    if not alerts:
        return set()
    numbers = set()
    for raw in dish_allergens:
        try:
            numbers.add(int(raw))
        except (TypeError, ValueError):
            continue
    return numbers & set(alerts)


def _pattern(alerts: set[int]) -> re.Pattern[str] | None:
    words: list[str] = []
    for code in alerts:
        words.extend(KEYWORDS.get(code, ()))
    if not words:
        return None
    # 긴 낱말을 먼저 맞춰야 '돼지고기'가 '돼지'로 잘리지 않는다
    words.sort(key=len, reverse=True)
    return re.compile("|".join(re.escape(word) for word in words))


def highlight_html(escaped_text: str, alerts: set[int], color: str) -> str:
    """이미 HTML 이스케이프된 문자열에서 알레르기 낱말을 감싼다."""
    pattern = _pattern(set(alerts))
    if pattern is None:
        return escaped_text
    return pattern.sub(
        lambda m: f"<span style='color:{color}; font-weight:600'>{m.group()}</span>",
        escaped_text,
    )


def found_in_text(text: str, alerts: set[int]) -> set[int]:
    """재료 문구에 어떤 알레르기 낱말이 들어 있는지."""
    found = set()
    for code in alerts:
        if any(word in text for word in KEYWORDS.get(code, ())):
            found.add(code)
    return found
