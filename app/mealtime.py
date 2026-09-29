"""식사 시간에 맞춰 무엇을 보여줄지 정한다 (#37).

'식사 시간에 맞춰 보기'를 켜면 포스트잇의 기본 화면('홈')이 시계를 따라간다.

    - 오늘 식사 중 이미 끝난 것은 숨긴다
    - 지금 먹는 중인 식사에는 '지금' 표시를 단다
    - 오늘 고른 식사가 모두 끝났으면 다음 등교일 식사를 보여준다
    - 주말에는 곧장 다음 등교일로 간다

예) 중식만 보는 경우: 점심이 끝나기 전에는 오늘 메뉴, 끝난 뒤에는 내일 메뉴.

위젯·설정 파일과 무관한 순수 계산만 둔다. 시각을 인자로 받으므로 시험하기 쉽다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from .neis.models import MEAL_TYPE_LABELS

#: 하루 안의 식사 순서
MEAL_ORDER: tuple[str, ...] = ("breakfast", "lunch", "dinner")

#: 학교 급식 시간 기본값. 설정 창에서 바꿀 수 있다.
DEFAULT_TIMES: dict[str, tuple[str, str]] = {
    "breakfast": ("07:30", "08:30"),
    "lunch": ("12:30", "13:30"),
    "dinner": ("17:30", "18:30"),
}

#: '점심이 끝나서'처럼 말할 때 쓰는 이름
_SPOKEN = {"breakfast": "아침", "lunch": "점심", "dinner": "저녁"}


@dataclass(frozen=True)
class Plan:
    """지금 홈 화면에 보여줄 것."""

    day: date
    meal_keys: tuple[str, ...]  # 그날 보여줄 식사 (순서대로)
    current: str | None = None  # 지금 먹는 중인 식사
    notice: str = ""  # 오늘이 아닌 날을 보여주는 이유


def parse_hhmm(text: str) -> time | None:
    """'12:30' → time(12, 30). 형식이 틀리면 None."""
    try:
        hours, minutes = str(text).strip().split(":")
        return time(int(hours), int(minutes))
    except (ValueError, TypeError):
        return None


def normalize_times(raw: object) -> dict[str, tuple[time, time]]:
    """설정 값을 (시작, 끝) 시각으로 바꾼다. 틀린 값은 기본값으로 메운다."""
    source = raw if isinstance(raw, dict) else {}
    times: dict[str, tuple[time, time]] = {}
    for key, (default_start, default_end) in DEFAULT_TIMES.items():
        pair = source.get(key)
        start = end = None
        if isinstance(pair, (list, tuple)) and len(pair) == 2:
            start, end = parse_hhmm(pair[0]), parse_hhmm(pair[1])
        if start is None or end is None or end <= start:
            start, end = parse_hhmm(default_start), parse_hhmm(default_end)
        times[key] = (start, end)
    return times


def next_school_day(day: date) -> date:
    """다음 날. 토·일은 건너뛴다. 공휴일은 알 수 없어 그대로 둔다."""
    following = day + timedelta(days=1)
    while following.weekday() >= 5:
        following += timedelta(days=1)
    return following


def plan(now: datetime, wanted: list[str] | tuple[str, ...], raw_times: object) -> Plan:
    """지금 시각에 홈 화면에 보여줄 날과 식사를 정한다."""
    times = normalize_times(raw_times)
    chosen = tuple(key for key in MEAL_ORDER if key in wanted) or ("lunch",)
    today = now.date()
    clock = now.time()

    if today.weekday() >= 5:  # 주말
        return Plan(
            day=next_school_day(today),
            meal_keys=chosen,
            notice="주말이라 다음 등교일 급식이에요",
        )

    remaining = tuple(key for key in chosen if clock < times[key][1])
    if remaining:
        current = next(
            (key for key in remaining if times[key][0] <= clock < times[key][1]),
            None,
        )
        return Plan(day=today, meal_keys=remaining, current=current)

    last = _SPOKEN.get(chosen[-1], MEAL_TYPE_LABELS.get(chosen[-1], "급식"))
    return Plan(
        day=next_school_day(today),
        meal_keys=chosen,
        notice=f"오늘 {last}까지 끝나서 다음 급식을 보여줘요",
    )
