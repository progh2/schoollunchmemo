"""달력 표시 테스트.

한 달치 응답이 달력 표시로 옳게 옮겨지는지, 그리고 캐시 규칙이 호출을
얼마나 아끼는지를 본다.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.calendar_popup import MEAL_COLORS, MEAL_SLOTS, DayMarks
from app.neis.models import MEAL_TYPES

MONTH_MEAL_ROWS = [
    {
        "MLSV_YMD": "20260706",
        "MMEAL_SC_CODE": "2",
        "MMEAL_SC_NM": "중식",
        "DDISH_NM": "기장밥<br/>미역국",
    },
    {
        "MLSV_YMD": "20260707",
        "MMEAL_SC_CODE": "1",
        "MMEAL_SC_NM": "조식",
        "DDISH_NM": "토스트",
    },
    {
        "MLSV_YMD": "20260707",
        "MMEAL_SC_CODE": "2",
        "MMEAL_SC_NM": "중식",
        "DDISH_NM": "비빔밥",
    },
    {
        "MLSV_YMD": "20260707",
        "MMEAL_SC_CODE": "3",
        "MMEAL_SC_NM": "석식",
        "DDISH_NM": "국수",
    },
]
MONTH_SCHEDULE_ROWS = [
    {"AA_YMD": "20260707", "EVENT_NM": "체육대회"},
    {"AA_YMD": "20260717", "EVENT_NM": "여름방학식", "SBTR_DD_SC_NM": "휴업일"},
    {
        "AA_YMD": "20260720",
        "EVENT_NM": "1학년 캠프",
        "ONE_GRADE_EVENT_YN": "Y",
    },
]


class TestMealSlots:
    def test_slots_cover_every_meal_type(self):
        """자리가 고정이므로 급식 구분과 하나씩 대응해야 한다."""
        assert set(MEAL_SLOTS) == set(MEAL_TYPES)
        assert set(MEAL_COLORS) == set(MEAL_SLOTS)

    def test_slot_order_is_fixed(self):
        assert MEAL_SLOTS == ("breakfast", "lunch", "dinner")


class TestDayMarks:
    def test_empty_marks_are_not_drawn(self):
        assert DayMarks().is_empty is True
        assert DayMarks(meal_keys=frozenset({"lunch"})).is_empty is False
        assert DayMarks(events=("체육대회",)).is_empty is False


class TestMarksFromRows:
    @pytest.fixture
    def marks(self, controller):
        return controller._marks_from_rows(MONTH_MEAL_ROWS, MONTH_SCHEDULE_ROWS)

    def test_only_days_with_something_appear(self, marks):
        assert set(marks) == {
            date(2026, 7, 6),
            date(2026, 7, 7),
            date(2026, 7, 17),
            date(2026, 7, 20),
        }

    def test_meal_types_are_kept_separate(self, marks):
        assert marks[date(2026, 7, 6)].meal_keys == frozenset({"lunch"})
        assert marks[date(2026, 7, 7)].meal_keys == frozenset(
            {"breakfast", "lunch", "dinner"}
        )

    def test_events_are_listed(self, marks):
        assert marks[date(2026, 7, 7)].events == ("체육대회",)
        assert marks[date(2026, 7, 7)].meal_keys  # 급식과 일정이 함께 있는 날

    def test_holiday_is_flagged(self, marks):
        assert marks[date(2026, 7, 17)].is_holiday is True
        assert marks[date(2026, 7, 7)].is_holiday is False

    def test_meal_filter_does_not_hide_other_meals(self, controller):
        """중식만 보도록 해 두었어도 조식·석식이 있다는 사실은 알려야 한다."""
        controller._config.display["meal_types"] = ["lunch"]
        marks = controller._marks_from_rows(MONTH_MEAL_ROWS, [])
        assert marks[date(2026, 7, 7)].meal_keys == frozenset(
            {"breakfast", "lunch", "dinner"}
        )

    def test_grade_filter_applies_to_events(self, controller):
        controller._config.display["grade_filter"] = 3
        marks = controller._marks_from_rows([], MONTH_SCHEDULE_ROWS)
        # 1학년 캠프는 3학년에게 보이지 않는다
        assert date(2026, 7, 20) not in marks
        assert date(2026, 7, 17) in marks  # 학년 정보 없는 일정은 남는다


class TestMonthCacheRules:
    def test_past_month_is_settled(self, controller):
        today = date.today()
        past = (today.year - 1, today.month)
        assert controller._month_is_past(*past) is True

    def test_current_month_is_not_settled(self, controller):
        today = date.today()
        assert controller._month_is_past(today.year, today.month) is False

    def test_future_month_is_not_settled(self, controller):
        today = date.today()
        assert controller._month_is_past(today.year + 1, today.month) is False
