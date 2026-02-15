"""Unit tests for the SearchService."""

from unittest.mock import MagicMock

from backend.application.search_service import SearchService
from backend.domain.constants import SIMILARITY_THRESHOLD
from backend.domain.models import SearchRequest, SearchResultItem
from backend.infrastructure.embedding import SparseVector


def _make_search_service() -> tuple[SearchService, MagicMock, MagicMock]:
    """Create a SearchService with mocked dependencies."""
    mock_embedder = MagicMock()
    mock_embedder.embed_text.return_value = [0.1] * 384
    mock_embedder.embed_text_sparse.return_value = SparseVector(
        indices=[1, 2, 3], values=[0.5, 0.3, 0.1]
    )

    mock_qdrant = MagicMock()
    mock_qdrant.hybrid_search.return_value = []
    mock_qdrant.get_related_notes_batch.return_value = {}

    service = SearchService(
        embedder=mock_embedder,
        qdrant_adapter=mock_qdrant,
    )
    return service, mock_embedder, mock_qdrant


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
        service, mock_embedder, mock_qdrant = _make_search_service()
        request = SearchRequest(query="database migration")

        service.search(request)

        mock_embedder.embed_text.assert_called_once_with("database migration")
        mock_embedder.embed_text_sparse.assert_called_once_with("database migration")
        mock_qdrant.hybrid_search.assert_called_once()
        call_kwargs = mock_qdrant.hybrid_search.call_args[1]
        assert call_kwargs["query_vector"] == [0.1] * 384
        assert call_kwargs["top_k"] == request.top_k
        assert call_kwargs["threshold"] == SIMILARITY_THRESHOLD

    def test_search_should_return_results_from_hybrid_search(self) -> None:
        service, _, mock_qdrant = _make_search_service()
        mock_qdrant.hybrid_search.return_value = _make_result_items(3)
        request = SearchRequest(query="test query")

        response = service.search(request)

        assert len(response.results) == 3
        assert response.total_hits == 3
        assert response.query == "test query"

    def test_search_should_return_empty_results_for_no_matches(self) -> None:
        service, _, mock_qdrant = _make_search_service()
        mock_qdrant.hybrid_search.return_value = []
        request = SearchRequest(query="nonexistent topic")

        response = service.search(request)

        assert len(response.results) == 0
        assert response.total_hits == 0

    def test_search_should_include_search_time_ms(self) -> None:
        service, _, _ = _make_search_service()
        request = SearchRequest(query="test")

        response = service.search(request)

        assert response.search_time_ms >= 0


class TestSearchParameters:
    def test_search_should_use_default_threshold(self) -> None:
        service, _, mock_qdrant = _make_search_service()
        request = SearchRequest(query="test")

        service.search(request)

        _, kwargs = mock_qdrant.hybrid_search.call_args
        assert kwargs["threshold"] == SIMILARITY_THRESHOLD

    def test_search_should_use_custom_threshold(self) -> None:
        service, _, mock_qdrant = _make_search_service()
        request = SearchRequest(query="test", threshold=0.7)

        service.search(request)

        _, kwargs = mock_qdrant.hybrid_search.call_args
        assert kwargs["threshold"] == 0.7

    def test_search_should_respect_top_k(self) -> None:
        service, _, mock_qdrant = _make_search_service()
        request = SearchRequest(query="test", top_k=10)

        service.search(request)

        _, kwargs = mock_qdrant.hybrid_search.call_args
        assert kwargs["top_k"] == 10


class TestSearchResponseFormat:
    def test_search_response_should_have_empty_related_when_no_links(self) -> None:
        service, _, mock_qdrant = _make_search_service()
        mock_qdrant.hybrid_search.return_value = _make_result_items(2)
        request = SearchRequest(query="test")

        response = service.search(request)

        assert response.related_notes == []

    def test_search_results_should_preserve_score_order(self) -> None:
        service, _, mock_qdrant = _make_search_service()
        items = _make_result_items(3, base_score=0.95)
        mock_qdrant.hybrid_search.return_value = items
        request = SearchRequest(query="test")

        response = service.search(request)

        scores = [r.score for r in response.results]
        assert scores == sorted(scores, reverse=True)

    def test_search_results_should_include_heading_context(self) -> None:
        service, _, mock_qdrant = _make_search_service()
        mock_qdrant.hybrid_search.return_value = _make_result_items(1)
        request = SearchRequest(query="test")

        response = service.search(request)

        assert response.results[0].heading_context == "Section 0"

    def test_search_should_skip_enrichment_when_include_related_false(self) -> None:
        service, _, mock_qdrant = _make_search_service()
        mock_qdrant.hybrid_search.return_value = _make_result_items(1)

        response = service.search(SearchRequest(query="test", include_related=False))

        assert response.related_notes == []
        mock_qdrant.get_related_notes_batch.assert_not_called()
