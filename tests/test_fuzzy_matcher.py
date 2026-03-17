"""Unit tests for fuzzy query correction."""

from backend.infrastructure.fuzzy_matcher import FuzzyMatcher


class TestFuzzyMatcher:
    def test_correct_query_should_fix_typo_against_vocabulary(self) -> None:
        # Arrange
        matcher = FuzzyMatcher(min_score=80)
        matcher.rebuild_vocabulary(
            titles=["Deployment Pipeline", "Database Migration Strategy"],
            headings=["Rollout Plan", "Rollback Checklist"],
        )

        # Act
        corrected, did_you_mean = matcher.correct_query("deploiment pipline")

        # Assert
        assert corrected == "Deployment Pipeline"
        assert did_you_mean == "Deployment Pipeline"

    def test_correct_query_should_skip_cjk_terms(self) -> None:
        # Arrange
        matcher = FuzzyMatcher(min_score=80)
        matcher.rebuild_vocabulary(
            titles=["Deployment Pipeline", "Database Migration Strategy"],
            headings=["Rollout Plan"],
        )

        # Act
        corrected, did_you_mean = matcher.correct_query("デプロイ パイプライン")

        # Assert
        assert corrected == "デプロイ パイプライン"
        assert did_you_mean is None

    def test_correct_query_should_respect_score_threshold(self) -> None:
        # Arrange
        matcher = FuzzyMatcher(min_score=95)
        matcher.rebuild_vocabulary(
            titles=["deployment"],
            headings=[],
        )

        # Act
        corrected, did_you_mean = matcher.correct_query("deploiment")

        # Assert
        assert corrected == "deploiment"
        assert did_you_mean is None
