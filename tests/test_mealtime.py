"""식사 시간 계획 테스트 (#37)."""

from __future__ import annotations

from datetime import date, datetime, time

import pytest

from app import mealtime

# 2026-09-29은 화요일, 10-02는 금요일, 10-03은 토요일
TUESDAY = date(2026, 9, 29)
FRIDAY = date(2026, 10, 2)
SATURDAY = date(2026, 10, 3)
TIMES = {
    "breakfast": ["07:30", "08:30"],
    "lunch": ["12:30", "13:30"],
    "dinner": ["17:30", "18:30"],
}
ALL = ["breakfast", "lunch", "dinner"]


def at(day: date, hhmm: str) -> datetime:
    hours, minutes = map(int, hhmm.split(":"))
    return datetime.combine(day, time(hours, minutes))


class TestLunchOnly:
    """요청에 나온 예: 중식만 보면 점심 전엔 오늘, 점심 뒤엔 내일."""

    def test_before_lunch_shows_today(self):
        result = mealtime.plan(at(TUESDAY, "09:00"), ["lunch"], TIMES)
        assert result.day == TUESDAY
        assert result.meal_keys == ("lunch",)
        assert result.current is None
        assert result.notice == ""

    def test_during_lunch_marks_it_current(self):
        result = mealtime.plan(at(TUESDAY, "12:45"), ["lunch"], TIMES)
        assert result.day == TUESDAY
        assert result.current == "lunch"

    def test_lunch_ends_exactly_at_end_time(self):
        result = mealtime.plan(at(TUESDAY, "13:30"), ["lunch"], TIMES)
        assert result.day == date(2026, 9, 30)
        assert result.meal_keys == ("lunch",)
        assert "점심" in result.notice


class TestAllMeals:
    @pytest.mark.parametrize(
        "clock, expected, current",
        [
            ("06:00", ("breakfast", "lunch", "dinner"), None),
            ("08:00", ("breakfast", "lunch", "dinner"), "breakfast"),
            ("10:00", ("lunch", "dinner"), None),  # 아침은 지나서 숨김
            ("13:00", ("lunch", "dinner"), "lunch"),
            ("15:00", ("dinner",), None),
            ("18:00", ("dinner",), "dinner"),
        ],
    )
    def test_past_meals_are_hidden(self, clock, expected, current):
        result = mealtime.plan(at(TUESDAY, clock), ALL, TIMES)
        assert result.day == TUESDAY
        assert result.meal_keys == expected
        assert result.current == current

    def test_after_dinner_shows_next_day_in_full(self):
        result = mealtime.plan(at(TUESDAY, "19:00"), ALL, TIMES)
        assert result.day == date(2026, 9, 30)
        assert result.meal_keys == ("breakfast", "lunch", "dinner")
        assert "저녁" in result.notice


class TestWeekend:
    def test_friday_evening_jumps_to_monday(self):
        result = mealtime.plan(at(FRIDAY, "14:00"), ["lunch"], TIMES)
        assert result.day == date(2026, 10, 5)

    def test_saturday_goes_straight_to_monday(self):
        result = mealtime.plan(at(SATURDAY, "09:00"), ["lunch"], TIMES)
        assert result.day == date(2026, 10, 5)
        assert "주말" in result.notice


class TestTimes:
    def test_custom_times_are_used(self):
        custom = {**TIMES, "lunch": ["11:50", "12:40"]}
        assert mealtime.plan(at(TUESDAY, "12:45"), ["lunch"], custom).day != TUESDAY
        assert mealtime.plan(at(TUESDAY, "12:45"), ["lunch"], TIMES).day == TUESDAY

    @pytest.mark.parametrize(
        "broken",
        [None, "garbage", {"lunch": ["25:00", "13:00"]}, {"lunch": ["13:30", "12:30"]}],
    )
    def test_broken_settings_fall_back_to_defaults(self, broken):
        times = mealtime.normalize_times(broken)
        assert times["lunch"] == (time(12, 30), time(13, 30))

    def test_order_follows_the_day_not_the_setting(self):
        result = mealtime.plan(at(TUESDAY, "06:00"), ["dinner", "breakfast"], TIMES)
        assert result.meal_keys == ("breakfast", "dinner")

    def test_nothing_chosen_means_lunch(self):
        assert mealtime.plan(at(TUESDAY, "06:00"), [], TIMES).meal_keys == ("lunch",)
