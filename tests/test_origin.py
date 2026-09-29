"""원산지에서 오늘 메뉴에 쓰인 재료 가려내기 (#47). 원본은 NEIS 실제 응답."""

from __future__ import annotations

import pytest

from app.neis.parser import parse_dishes
from app.origin import classify, codes_of, core_name

#: 미림마이스터고가 매일 올리는 고정 원산지 목록
ORIGIN = "\n".join(
    [
        "쇠고기(종류) : 국내산(한우)",
        "쇠고기 식육가공품 : 국내산",
        "돼지고기 : 국내산",
        "닭고기 : 국내산",
        "오리고기 : 국내산",
        "쌀 : 국내산",
        "배추 : 국내산",
        "고춧가루 : 국내산",
        "콩 : 국내산",
        "낙지 : 국내산",
        "꽃게 : 국내산",
        "비고 : ",
    ]
)

#: 2026-09-30 중식 — 게(8)가 든 요리가 없다
PASTA_DAY = parse_dishes(
    "햄로제파스타(j) (1.2.5.6.9.10.12.13.15.16)<br/>마늘바게트(j) (2.5.6)"
    "<br/>양송이스프(j) (2.5.6.13.16)<br/>오이피클(jn)<br/>시저샐러드 (1.2.5.6.10.12)"
)


def _by_name(lines):
    return {line.ingredient: line for line in lines}


class TestCrabFalseAlarm:
    """질문의 발단: 쓰지 않은 꽃게가 빨갛게 뜨면 안 된다."""

    def test_unused_crab_is_not_an_alert(self):
        lines = _by_name(classify(ORIGIN, PASTA_DAY, {8}))
        assert lines["꽃게"].used is False
        assert lines["꽃게"].alert is False

    def test_crab_alerts_when_a_dish_carries_number_8(self):
        dishes = parse_dishes("콘치즈구이 (1.2.5.6.8.13)")
        lines = _by_name(classify(ORIGIN, dishes, {8}))
        assert lines["꽃게"].used and lines["꽃게"].alert

    def test_crab_alerts_when_named_even_without_number(self):
        """번호를 빠뜨린 학교도 있다. 이름에 보이면 쓰인 것으로 본다."""
        lines = _by_name(classify(ORIGIN, parse_dishes("꽃게탕"), {8}))
        assert lines["꽃게"].alert


class TestUsage:
    def test_allergen_numbers_mark_meats_and_beans(self):
        lines = _by_name(classify(ORIGIN, PASTA_DAY, set()))
        for used in ("쇠고기(종류)", "쇠고기 식육가공품", "돼지고기", "닭고기", "콩"):
            assert lines[used].used, used
        for unused in ("오리고기", "쌀", "배추", "고춧가루", "낙지", "꽃게"):
            assert not lines[unused].used, unused

    @pytest.mark.parametrize(
        "dish, ingredient",
        [
            ("현미밥", "쌀"),
            ("배추겉절이 (9)", "배추"),
            ("깍두기 (9)", "고춧가루"),
            ("낙지볶음", "낙지"),
            ("훈제오리구이", "오리고기"),
        ],
    )
    def test_dish_names_are_evidence(self, dish, ingredient):
        lines = _by_name(classify(ORIGIN, parse_dishes(dish), set()))
        assert lines[ingredient].used

    def test_alert_needs_both_use_and_registration(self):
        lines = _by_name(classify(ORIGIN, PASTA_DAY, {10}))
        assert lines["돼지고기"].alert
        assert not lines["닭고기"].alert  # 쓰였지만 등록 안 함

    def test_empty_values_are_dropped(self):
        assert "비고" not in _by_name(classify(ORIGIN, PASTA_DAY, set()))


class TestNames:
    @pytest.mark.parametrize(
        "raw, core",
        [("쇠고기(종류)", "쇠고기"), ("쇠고기 식육가공품", "쇠고기"), ("오리고기 가공품", "오리고기")],
    )
    def test_core_name(self, raw, core):
        assert core_name(raw) == core

    def test_codes(self):
        assert codes_of("꽃게") == {8}
        assert codes_of("돼지고기 식육가공품") == {10}
        assert codes_of("쌀") == set()
