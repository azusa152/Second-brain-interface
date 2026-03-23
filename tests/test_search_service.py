"""Unit tests for the SearchService."""

from unittest.mock import MagicMock

import pytest
from qdrant_client.models import FieldCondition, Filter, MatchAny

from backend.application.search_service import SearchService
from backend.domain.constants import SIMILARITY_THRESHOLD
from backend.domain.exceptions import IndexRebuildRequiredError
from backend.domain.models import SearchFilter, SearchRequest, SearchResultItem
from backend.infrastructure.embedding import SparseVector
from backend.infrastructure.fuzzy_matcher import FuzzyMatcher


def _make_search_service() -> tuple[SearchService, MagicMock, MagicMock, MagicMock]:
    """Create a SearchService with mocked dependencies."""
    mock_embedder = MagicMock()
    mock_embedder.embed_text.return_value = [0.1] * 384
    mock_embedder.embed_text_sparse.return_value = SparseVector(
        indices=[1, 2, 3], values=[0.5, 0.3, 0.1]
    )

    mock_qdrant = MagicMock()
    mock_qdrant.hybrid_search.return_value = []
    mock_qdrant.get_related_notes_batch.return_value = {}
    mock_qdrant.get_fuzzy_vocabulary_sources.return_value = ([], [])
    mock_qdrant.build_query_filter.return_value = None
    mock_qdrant.has_legacy_chunks_without_prefixes.return_value = False

    mock_fuzzy = MagicMock(spec=FuzzyMatcher)
    mock_fuzzy.correct_query.return_value = ("database migration", None)

    service = SearchService(
        embedder=mock_embedder,
        qdrant_adapter=mock_qdrant,
        fuzzy_matcher=mock_fuzzy,
    )
    return service, mock_embedder, mock_qdrant, mock_fuzzy


def _make_result_items(count: int, base_score: float = 0.9) -> list[SearchResultItem]:
    """Create a list of mock search result items."""
    return [
        SearchResultItem(
            chunk_id=f"chunk_{i}",
            note_path=f"notes/note{i}.md",
            note_title=f"Note {i}",
            content=f"Content of chunk {i}",
            score=round(base_score - i * 0.1, 2),
            heading_context=f"Section {i}",
        )
        for i in range(count)
    ]


class TestSearchBasic:
    def test_search_should_embed_query_and_call_hybrid_search(self) -> None:
        service, mock_embedder, mock_qdrant, mock_fuzzy = _make_search_service()
        request = SearchRequest(query="database migration")

        service.search(request)

        mock_fuzzy.correct_query.assert_called_once_with("database migration")
        mock_embedder.embed_text.assert_called_once_with("database migration")
        mock_embedder.embed_text_sparse.assert_called_once_with("database migration")
        mock_qdrant.hybrid_search.assert_called_once()
        call_kwargs = mock_qdrant.hybrid_search.call_args[1]
        assert call_kwargs["query_vector"] == [0.1] * 384
        assert call_kwargs["top_k"] == request.top_k
        assert call_kwargs["threshold"] == SIMILARITY_THRESHOLD

    def test_search_should_return_results_from_hybrid_search(self) -> None:
        service, _, mock_qdrant, mock_fuzzy = _make_search_service()
        mock_qdrant.hybrid_search.return_value = _make_result_items(3)
        request = SearchRequest(query="test query")

        response = service.search(request)

        assert len(response.results) == 3
        assert response.total_hits == 3
        assert response.query == "test query"
        mock_fuzzy.correct_query.assert_not_called()

    def test_search_should_return_empty_results_for_no_matches(self) -> None:
        service, _, mock_qdrant, _ = _make_search_service()
        mock_qdrant.hybrid_search.return_value = []
        request = SearchRequest(query="nonexistent topic")

        response = service.search(request)

        assert len(response.results) == 0
        assert response.total_hits == 0

    def test_search_should_include_search_time_ms(self) -> None:
        service, _, _, _ = _make_search_service()
        request = SearchRequest(query="test")

        response = service.search(request)

        assert response.search_time_ms >= 0


class TestSearchParameters:
    def test_search_should_use_default_threshold(self) -> None:
        service, _, mock_qdrant, _ = _make_search_service()
        request = SearchRequest(query="test")

        service.search(request)

        _, kwargs = mock_qdrant.hybrid_search.call_args
        assert kwargs["threshold"] == SIMILARITY_THRESHOLD

    def test_search_should_use_custom_threshold(self) -> None:
        service, _, mock_qdrant, _ = _make_search_service()
        request = SearchRequest(query="test", threshold=0.7)

        service.search(request)

        _, kwargs = mock_qdrant.hybrid_search.call_args
        assert kwargs["threshold"] == 0.7

    def test_search_should_respect_top_k(self) -> None:
        service, _, mock_qdrant, _ = _make_search_service()
        request = SearchRequest(query="test", top_k=10)

        service.search(request)

        _, kwargs = mock_qdrant.hybrid_search.call_args
        assert kwargs["top_k"] == 10


class TestSearchResponseFormat:
    def test_search_response_should_have_empty_related_when_no_links(self) -> None:
        service, _, mock_qdrant, _ = _make_search_service()
        mock_qdrant.hybrid_search.return_value = _make_result_items(2)
        request = SearchRequest(query="test")

        response = service.search(request)

        assert response.related_notes == []

    def test_search_results_should_preserve_score_order(self) -> None:
        service, _, mock_qdrant, _ = _make_search_service()
        items = _make_result_items(3, base_score=0.95)
        mock_qdrant.hybrid_search.return_value = items
        request = SearchRequest(query="test")

        response = service.search(request)

        scores = [r.score for r in response.results]
        assert scores == sorted(scores, reverse=True)

    def test_search_results_should_include_heading_context(self) -> None:
        service, _, mock_qdrant, _ = _make_search_service()
        mock_qdrant.hybrid_search.return_value = _make_result_items(1)
        request = SearchRequest(query="test")

        response = service.search(request)

        assert response.results[0].heading_context == "Section 0"

    def test_search_should_skip_enrichment_when_include_related_false(self) -> None:
        service, _, mock_qdrant, _ = _make_search_service()
        mock_qdrant.hybrid_search.return_value = _make_result_items(1)

        response = service.search(SearchRequest(query="test", include_related=False))

        assert response.related_notes == []
        mock_qdrant.get_related_notes_batch.assert_not_called()

    def test_search_should_return_did_you_mean_when_fuzzy_corrected(self) -> None:
        service, _, mock_qdrant, mock_fuzzy = _make_search_service()
        mock_fuzzy.correct_query.return_value = ("deployment pipeline", "deployment pipeline")
        mock_qdrant.hybrid_search.side_effect = [
            [],
            _make_result_items(1),
        ]

        response = service.search(SearchRequest(query="deploiment pipline"))

        assert response.did_you_mean == "deployment pipeline"

    def test_search_should_use_corrected_query_for_sparse_embedding(self) -> None:
        service, mock_embedder, mock_qdrant, mock_fuzzy = _make_search_service()
        mock_fuzzy.correct_query.return_value = ("deployment pipeline", "deployment pipeline")
        mock_qdrant.hybrid_search.side_effect = [
            [],
            _make_result_items(1),
        ]

        service.search(SearchRequest(query="deploiment pipline"))

        mock_embedder.embed_text.assert_called_once_with("deploiment pipline")
        assert mock_embedder.embed_text_sparse.call_count == 2
        assert mock_embedder.embed_text_sparse.call_args_list[0].args[0] == "deploiment pipline"
        assert mock_embedder.embed_text_sparse.call_args_list[1].args[0] == "deployment pipeline"

    def test_search_should_not_set_did_you_mean_when_fuzzy_fallback_has_no_hits(self) -> None:
        service, _, mock_qdrant, mock_fuzzy = _make_search_service()
        mock_fuzzy.correct_query.return_value = ("deployment pipeline", "deployment pipeline")
        mock_qdrant.hybrid_search.side_effect = [[], []]

        response = service.search(SearchRequest(query="deploiment pipline"))

        assert response.did_you_mean is None

    def test_search_should_generate_highlights_for_matching_results(self) -> None:
        service, _, mock_qdrant, _ = _make_search_service()
        mock_qdrant.hybrid_search.return_value = [
            SearchResultItem(
                chunk_id="c1",
                note_path="notes/deploy.md",
                note_title="Deploy",
                content="The deployment pipeline uses canary rollout for production changes.",
                score=0.9,
            )
        ]

        response = service.search(SearchRequest(query="deployment pipeline"))

        assert response.results[0].highlights
        assert "deployment pipeline" in response.results[0].highlights[0].lower()


class TestSearchFilters:
    def test_search_with_filters_should_build_and_pass_query_filter(self) -> None:
        service, _, mock_qdrant, _ = _make_search_service()
        built_filter = Filter(
            must=[FieldCondition(key="tags", match=MatchAny(any=["devops"]))],
        )
        mock_qdrant.build_query_filter.return_value = built_filter

        request = SearchRequest(
            query="deployment pipeline",
            filters=SearchFilter(tags=["devops"]),
        )
        service.search(request)

        mock_qdrant.build_query_filter.assert_called_once_with(request.filters)
        _, kwargs = mock_qdrant.hybrid_search.call_args
        assert kwargs["query_filter"] == built_filter

    def test_search_without_filters_should_pass_none_query_filter(self) -> None:
        service, _, mock_qdrant, _ = _make_search_service()

        service.search(SearchRequest(query="deployment pipeline"))

        mock_qdrant.build_query_filter.assert_not_called()
        _, kwargs = mock_qdrant.hybrid_search.call_args
        assert kwargs["query_filter"] is None

    def test_search_response_should_echo_applied_filters(self) -> None:
        service, _, mock_qdrant, _ = _make_search_service()
        mock_qdrant.hybrid_search.return_value = _make_result_items(1)
        filters = SearchFilter(
            tags=["devops"],
            exclude_tags=["archive"],
            path_prefix="projects/",
        )

        response = service.search(SearchRequest(query="deployment", filters=filters))

        assert response.applied_filters == filters

    def test_search_should_raise_rebuild_required_when_legacy_data_exists(self) -> None:
        service, _, mock_qdrant, _ = _make_search_service()
        mock_qdrant.has_legacy_chunks_without_prefixes.return_value = True

        with pytest.raises(
            IndexRebuildRequiredError, match="path_prefix filter requires a full rebuild"
        ):
            service.search(
                SearchRequest(query="test", filters=SearchFilter(path_prefix="projects/"))
            )

    def test_search_should_skip_rebuild_check_when_no_path_prefix_filter(self) -> None:
        service, _, mock_qdrant, _ = _make_search_service()

        service.search(SearchRequest(query="test", filters=SearchFilter(tags=["devops"])))

        mock_qdrant.has_legacy_chunks_without_prefixes.assert_not_called()


class TestQueryLoggingFields:
    def test_query_logging_fields_should_hide_raw_query_by_default(self) -> None:
        service, _, _, _ = _make_search_service()

        fields = service._query_logging_fields("sensitive query text")

        assert "query" not in fields
        assert fields["query_len"] == len("sensitive query text")
        assert "query_hash" in fields

    def test_query_logging_fields_should_include_query_when_enabled(self) -> None:
        service, mock_embedder, mock_qdrant, mock_fuzzy = _make_search_service()
        service = SearchService(
            embedder=mock_embedder,
            qdrant_adapter=mock_qdrant,
            fuzzy_matcher=mock_fuzzy,
            include_query_text_in_logs=True,
        )

        fields = service._query_logging_fields("hello world", preview_length=5)

        assert fields["query"] == "hello"
