"""설정 병합·마이그레이션 테스트."""

from __future__ import annotations

from app.config import CONFIG_VERSION, Config


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
    def test_show_origin_is_dropped_without_expanding(self):
        """구버전 '원산지 표시'는 '처음부터 펼침'과 다른 값이다."""
        raw = {"version": 1, "display": {"show_origin": True}}
        migrated = Config._migrate(raw)
        assert "show_origin" not in migrated["display"]
        assert Config(migrated).display["expand_details"] is False

    def test_v1_expand_details_is_reset(self):
        """v1에서 잘못 켜진 펼침 상태를 한 번 되돌린다."""
        raw = {"version": 1, "display": {"expand_details": True}}
        assert Config(Config._migrate(raw)).display["expand_details"] is False

    def test_version_is_stamped(self):
        assert Config._migrate({"version": 1})["version"] == CONFIG_VERSION

    def test_v2_choice_is_kept(self):
        """되돌리기는 일회성이다. v2 이후 사용자가 켠 값은 지킨다."""
        raw = {"version": 2, "display": {"expand_details": True}}
        assert Config(Config._migrate(raw)).display["expand_details"] is True
