"""Unit tests for Qdrant metadata filter construction."""

from datetime import UTC, datetime

from qdrant_client.models import DatetimeRange, MatchAny

from backend.domain.models import SearchFilter
from backend.infrastructure.qdrant_adapter import QdrantAdapter


class TestQdrantFilterBuilder:
    def test_filter_builder_should_map_tags_to_match_any(self) -> None:
        result = QdrantAdapter.build_query_filter(SearchFilter(tags=["devops", "infra"]))

        assert result is not None
        assert result.must is not None
        assert result.must[0].key == "tags"
        assert isinstance(result.must[0].match, MatchAny)
        assert result.must[0].match.any == ["devops", "infra"]
        assert result.must_not is None

    def test_filter_builder_should_map_exclude_tags_to_must_not(self) -> None:
        result = QdrantAdapter.build_query_filter(SearchFilter(exclude_tags=["private"]))

        assert result is not None
        assert result.must is None
        assert result.must_not is not None
        assert result.must_not[0].key == "tags"
        assert isinstance(result.must_not[0].match, MatchAny)
        assert result.must_not[0].match.any == ["private"]

    def test_filter_builder_should_map_path_prefix_and_date_range(self) -> None:
        after = datetime(2025, 1, 1, tzinfo=UTC)
        before = datetime(2026, 1, 1, tzinfo=UTC)

        result = QdrantAdapter.build_query_filter(
            SearchFilter(
                path_prefix="projects/",
                modified_after=after,
                modified_before=before,
            )
        )

        assert result is not None
        assert result.must is not None
        assert len(result.must) == 2

        path_condition = result.must[0]
        date_condition = result.must[1]

        assert path_condition.key == "note_path_prefixes"
        assert isinstance(path_condition.match, MatchAny)
        assert path_condition.match.any == ["projects/"]

        assert date_condition.key == "last_modified"
        assert isinstance(date_condition.range, DatetimeRange)
        assert date_condition.range.gte == after
        assert date_condition.range.lte == before

    def test_filter_builder_should_return_none_for_empty_filter(self) -> None:
        result = QdrantAdapter.build_query_filter(SearchFilter())

        assert result is None

    def test_filter_builder_should_normalize_path_prefix(self) -> None:
        result = QdrantAdapter.build_query_filter(SearchFilter(path_prefix="/projects\\infra"))

        assert result is not None
        assert result.must is not None
        assert result.must[0].key == "note_path_prefixes"
        assert isinstance(result.must[0].match, MatchAny)
        assert result.must[0].match.any == ["projects/infra/"]


class TestPathPrefixPayload:
    def test_build_note_path_prefixes_should_generate_hierarchy(self) -> None:
        prefixes = QdrantAdapter._build_note_path_prefixes("projects/infra/plan.md")

        assert prefixes == ["projects/", "projects/infra/"]

    def test_build_note_path_prefixes_should_return_empty_for_root_note(self) -> None:
        prefixes = QdrantAdapter._build_note_path_prefixes("inbox.md")

        assert prefixes == []
