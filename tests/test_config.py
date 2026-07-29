"""설정 병합·마이그레이션 테스트."""

from __future__ import annotations

from app.config import Config


class TestDefaults:
    def test_missing_keys_fall_back(self):
        config = Config({"display": {"color": "sky"}})
        assert config.display["color"] == "sky"
        assert config.display["meal_types"] == ["lunch"]  # 기본값이 살아 있다
        assert config.display["allergy_alerts"] == []

    def test_is_configured_requires_both_codes(self):
        assert Config().is_configured is False
        assert Config({"school": {"office_code": "B10"}}).is_configured is False
        assert (
            Config(
                {"school": {"office_code": "B10", "school_code": "7010084"}}
            ).is_configured
            is True
        )


class TestMigration:
    def test_show_origin_becomes_expand_details(self):
        raw = {"version": 1, "display": {"show_origin": True}}
        migrated = Config._migrate(raw)
        assert migrated["display"]["expand_details"] is True
        assert "show_origin" not in migrated["display"]

    def test_existing_expand_details_wins(self):
        raw = {"display": {"show_origin": True, "expand_details": False}}
        migrated = Config._migrate(raw)
        assert migrated["display"]["expand_details"] is False
