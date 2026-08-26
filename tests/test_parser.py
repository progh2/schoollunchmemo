"""NEIS 응답 파서 테스트.

응답 구조가 상황에 따라 달라지는 것이 이 앱에서 가장 깨지기 쉬운 지점이라
봉투 해석과 값 정규화를 집중적으로 확인한다.
"""

from __future__ import annotations

from datetime import date

from app.neis.codes import ResultKind, classify
from app.neis.parser import (
    parse_dishes,
    parse_meals,
    parse_schedule,
    parse_schools,
    unwrap,
)

MEAL_OK = {
    "mealServiceDietInfo": [
        {
            "head": [
                {"list_total_count": 1},
                {"RESULT": {"CODE": "INFO-000", "MESSAGE": "정상 처리되었습니다."}},
            ]
        },
        {
            "row": [
                {
                    "ATPT_OFCDC_SC_CODE": "B10",
                    "SD_SCHUL_CODE": "7010084",
                    "MMEAL_SC_CODE": "2",
                    "MMEAL_SC_NM": "중식",
                    "MLSV_YMD": "20260729",
                    "DDISH_NM": "기장밥<br/>쇠고기미역국 (5.6.16.)<br/>배추김치 (9.13)",
                    "CAL_INFO": "678.3 Kcal",
                    "ORPLC_INFO": "쌀 : 국내산<br/>김치 : 국내산",
                }
            ]
        },
    ]
}

NO_DATA = {
    "RESULT": {"CODE": "INFO-200", "MESSAGE": "해당하는 데이터가 없습니다."}
}

BAD_KEY = {
    "RESULT": {"CODE": "ERROR-290", "MESSAGE": "인증키가 유효하지 않습니다."}
}

SCHEDULE_OK = {
    "SchoolSchedule": [
        {"head": [{"list_total_count": 2}, {"RESULT": {"CODE": "INFO-000"}}]},
        {
            "row": [
                {
                    "AA_YMD": "20260729",
                    "EVENT_NM": "여름방학식",
                    "EVENT_CNTNT": "1학기 종업",
                    "SBTR_DD_SC_NM": "휴업일",
                    "ONE_GRADE_EVENT_YN": "Y",
                    "TW_GRADE_EVENT_YN": "Y",
                    "THREE_GRADE_EVENT_YN": "N",
                },
                {
                    "AA_YMD": "20260729",
                    "EVENT_NM": "안전교육",
                    "SBTR_DD_SC_NM": "수업일",
                },
            ]
        },
    ]
}

SCHOOL_OK = {
    "schoolInfo": [
        {"head": [{"list_total_count": 1}, {"RESULT": {"CODE": "INFO-000"}}]},
        {
            "row": [
                {
                    "ATPT_OFCDC_SC_CODE": "B10",
                    "ATPT_OFCDC_SC_NM": "서울특별시교육청",
                    "SD_SCHUL_CODE": "7010084",
                    "SCHUL_NM": "미림마이스터고등학교",
                    "SCHUL_KND_SC_NM": "고등학교",
                    "LCTN_SC_NM": "서울특별시",
                    "ORG_RDNMA": "서울특별시 관악구 시흥대로",
                }
            ]
        },
    ]
}


class TestUnwrap:
    def test_normal_response(self):
        kind, code, _, rows = unwrap(MEAL_OK, "mealServiceDietInfo")
        assert kind is ResultKind.OK
        assert code == "INFO-000"
        assert len(rows) == 1

    def test_no_data_uses_top_level_result(self):
        kind, code, message, rows = unwrap(NO_DATA, "mealServiceDietInfo")
        assert kind is ResultKind.NO_DATA
        assert code == "INFO-200"
        assert message
        assert rows == []

    def test_bad_key(self):
        kind, _, _, _ = unwrap(BAD_KEY, "schoolInfo")
        assert kind is ResultKind.BAD_KEY

    def test_garbage_payload(self):
        kind, _, _, rows = unwrap("<html>점검중</html>", "schoolInfo")
        assert kind is ResultKind.UNKNOWN
        assert rows == []

    def test_ok_head_without_rows_is_no_data(self):
        payload = {"schoolInfo": [{"head": [{"RESULT": {"CODE": "INFO-000"}}]}]}
        kind, _, _, rows = unwrap(payload, "schoolInfo")
        assert kind is ResultKind.NO_DATA
        assert rows == []


class TestClassify:
    def test_known_code(self):
        assert classify("ERROR-337") is ResultKind.QUOTA

    def test_unknown_code_falls_back_to_message(self):
        assert classify("ERROR-999", "인증키가 유효하지 않습니다") is ResultKind.BAD_KEY

    def test_unknown_stays_unknown(self):
        assert classify("ERROR-999", "알 수 없는 문제") is ResultKind.UNKNOWN


class TestDishes:
    def test_splits_and_extracts_allergens(self):
        dishes = parse_dishes("기장밥<br/>쇠고기미역국 (5.6.16.)<br />배추김치 (9.13)")
        assert [d.name for d in dishes] == ["기장밥", "쇠고기미역국", "배추김치"]
        assert dishes[0].allergens == ()
        assert dishes[1].allergens == ("5", "6", "16")
        assert dishes[2].allergens == ("9", "13")

    def test_display_respects_toggle(self):
        dish = parse_dishes("배추김치 (9.13)")[0]
        assert dish.display(False) == "배추김치"
        assert dish.display(True) == "배추김치 (9.13)"

    def test_ignores_empty_segments(self):
        assert parse_dishes("<br/><br/>  <br/>우유") == parse_dishes("우유")

    def test_does_not_eat_numbers_inside_name(self):
        dish = parse_dishes("우유200ml")[0]
        assert dish.name == "우유200ml"
        assert dish.allergens == ()


class TestMeals:
    def test_parses_row(self):
        _, _, _, rows = unwrap(MEAL_OK, "mealServiceDietInfo")
        meal = parse_meals(rows)[0]
        assert meal.day == date(2026, 7, 29)
        assert meal.meal_key == "lunch"
        assert meal.label == "중식"
        assert meal.calorie == 678.3
        assert "국내산" in meal.origin

    def test_sorted_by_meal_order(self):
        rows = [
            {"MLSV_YMD": "20260729", "MMEAL_SC_CODE": "3", "MMEAL_SC_NM": "석식", "DDISH_NM": "비빔밥"},
            {"MLSV_YMD": "20260729", "MMEAL_SC_CODE": "1", "MMEAL_SC_NM": "조식", "DDISH_NM": "토스트"},
            {"MLSV_YMD": "20260729", "MMEAL_SC_CODE": "2", "MMEAL_SC_NM": "중식", "DDISH_NM": "국밥"},
        ]
        assert [m.meal_key for m in parse_meals(rows)] == [
            "breakfast",
            "lunch",
            "dinner",
        ]

    def test_skips_rows_without_date(self):
        assert parse_meals([{"MMEAL_SC_CODE": "2"}]) == []

    def test_skips_rows_with_empty_dishes(self):
        """DDISH_NM이 비어 있으면 shell row로 간주해 제외한다 (이슈 #12)."""
        base = {"MLSV_YMD": "20260729", "MMEAL_SC_CODE": "2", "MMEAL_SC_NM": "중식"}
        assert parse_meals([{**base, "DDISH_NM": ""}]) == []
        assert parse_meals([{**base, "DDISH_NM": "   "}]) == []
        assert parse_meals([{**base, "DDISH_NM": "<br/>"}]) == []
        assert parse_meals([{**base, "DDISH_NM": "<br/><br/>"}]) == []
        # 실제 메뉴가 있으면 통과
        assert len(parse_meals([{**base, "DDISH_NM": "비빔밥"}])) == 1


class TestSchedule:
    def test_parses_grades_and_holiday(self):
        _, _, _, rows = unwrap(SCHEDULE_OK, "SchoolSchedule")
        events = parse_schedule(rows)
        assert len(events) == 2
        assert events[0].name == "여름방학식"
        assert events[0].is_holiday is True
        assert events[0].grades == frozenset({1, 2})
        assert events[0].grade_label == "1·2학년"
        assert events[1].is_holiday is False

    def test_grade_filter(self):
        _, _, _, rows = unwrap(SCHEDULE_OK, "SchoolSchedule")
        events = parse_schedule(rows)
        assert events[0].applies_to(1) is True
        assert events[0].applies_to(3) is False
        # 학년 정보가 없는 일정은 모든 학년에 표시한다
        assert events[1].applies_to(3) is True
        assert events[0].applies_to(None) is True


class TestSchools:
    def test_parses_and_builds_subtitle(self):
        _, _, _, rows = unwrap(SCHOOL_OK, "schoolInfo")
        school = parse_schools(rows)[0]
        assert school.school_name == "미림마이스터고등학교"
        assert school.office_code == "B10"
        assert "서울특별시교육청" in school.subtitle

    def test_skips_rows_without_codes(self):
        assert parse_schools([{"SCHUL_NM": "이름만있는학교"}]) == []

    def test_config_roundtrip(self):
        _, _, _, rows = unwrap(SCHOOL_OK, "schoolInfo")
        school = parse_schools(rows)[0]
        restored = type(school).from_config(school.to_config())
        assert restored.school_code == school.school_code
        assert restored.office_code == school.office_code
