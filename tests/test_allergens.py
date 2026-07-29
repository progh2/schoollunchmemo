"""알레르기 매칭 테스트."""

from __future__ import annotations

from app import allergens


class TestMatched:
    def test_matches_registered_codes(self):
        assert allergens.matched(("5", "6", "16"), {6}) == {6}

    def test_no_alerts_means_no_match(self):
        assert allergens.matched(("5", "6"), set()) == set()

    def test_ignores_non_numeric(self):
        assert allergens.matched(("우유", "2"), {2}) == {2}

    def test_multiple_hits(self):
        assert allergens.matched(("2", "5", "16"), {2, 16}) == {2, 16}


class TestLabels:
    def test_names_in_number_order(self):
        assert allergens.labels({16, 2}) == "우유, 쇠고기"


class TestHighlight:
    def test_wraps_keyword(self):
        html = allergens.highlight_html("쌀 : 국내산, 우유 : 국내산", {2}, "#f00")
        assert "<span style='color:#f00; font-weight:600'>우유</span>" in html

    def test_untouched_without_alerts(self):
        text = "쌀 : 국내산"
        assert allergens.highlight_html(text, set(), "#f00") == text

    def test_longer_keyword_wins(self):
        """'돼지고기'가 '돼지'로 잘려 표시되면 안 된다."""
        html = allergens.highlight_html("돼지고기 : 국내산", {10}, "#f00")
        assert ">돼지고기</span>" in html

    def test_leaves_unrelated_text(self):
        html = allergens.highlight_html("배추 : 국내산", {2}, "#f00")
        assert "span" not in html


class TestFoundInText:
    def test_detects_by_name(self):
        assert allergens.found_in_text("쇠고기 : 호주산", {16, 2}) == {16}

    def test_empty_when_nothing_matches(self):
        assert allergens.found_in_text("배추 : 국내산", {16}) == set()
