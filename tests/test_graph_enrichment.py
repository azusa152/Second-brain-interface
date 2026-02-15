"""Tests for search result graph enrichment (Phase 4)."""

from unittest.mock import MagicMock

from backend.application.search_service import SearchService
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


def _make_result_items(
    paths: list[str], base_score: float = 0.9
) -> list[SearchResultItem]:
    """Create search result items for given note paths."""
    return [
        SearchResultItem(
            chunk_id=f"chunk_{i}",
            note_path=path,
            note_title=path.rsplit("/", 1)[-1].removesuffix(".md"),
            content=f"Content from {path}",
            score=round(base_score - i * 0.05, 2),
        )
        for i, path in enumerate(paths)
    ]


class TestSearchEnrichment:
    def test_search_should_include_related_notes_when_links_exist(self) -> None:
        service, _, mock_qdrant = _make_search_service()
        results = _make_result_items(["note3.md"])
        mock_qdrant.hybrid_search.return_value = results
        mock_qdrant.get_related_notes_batch.return_value = {
            "note3.md": [
                {
                    "related_path": "concepts/architecture.md",
                    "relationship": "outgoing",
                },
                {"related_path": "projects/migration.md", "relationship": "outgoing"},
            ]
        }

        response = service.search(SearchRequest(query="test"))

        assert len(response.related_notes) == 2
        related_paths = {r.note_path for r in response.related_notes}
        assert "concepts/architecture.md" in related_paths
        assert "projects/migration.md" in related_paths

    def test_search_should_not_include_result_paths_in_related(self) -> None:
        service, _, mock_qdrant = _make_search_service()
        results = _make_result_items(["note3.md", "concepts/architecture.md"])
        mock_qdrant.hybrid_search.return_value = results
        mock_qdrant.get_related_notes_batch.return_value = {
            "note3.md": [
                # architecture.md is already in results — should be excluded
                {
                    "related_path": "concepts/architecture.md",
                    "relationship": "outgoing",
                },
                {"related_path": "projects/migration.md", "relationship": "outgoing"},
            ],
            "concepts/architecture.md": [
                {"related_path": "note3.md", "relationship": "backlink"},
            ],
        }

        response = service.search(SearchRequest(query="test"))

        related_paths = {r.note_path for r in response.related_notes}
        # architecture.md and note3.md are in results — only migration.md is related
        assert "concepts/architecture.md" not in related_paths
        assert "note3.md" not in related_paths
        assert "projects/migration.md" in related_paths

    def test_search_should_skip_enrichment_when_include_related_false(self) -> None:
        service, _, mock_qdrant = _make_search_service()
        mock_qdrant.hybrid_search.return_value = _make_result_items(["note3.md"])

        response = service.search(SearchRequest(query="test", include_related=False))

        assert response.related_notes == []
        mock_qdrant.get_related_notes_batch.assert_not_called()

    def test_search_should_skip_enrichment_when_no_results(self) -> None:
        service, _, mock_qdrant = _make_search_service()
        mock_qdrant.hybrid_search.return_value = []

        response = service.search(SearchRequest(query="nothing"))

        assert response.related_notes == []
        mock_qdrant.get_related_notes_batch.assert_not_called()

    def test_search_should_use_batch_query_not_n_plus_1(self) -> None:
        service, _, mock_qdrant = _make_search_service()
        results = _make_result_items(["a.md", "b.md", "c.md"])
        mock_qdrant.hybrid_search.return_value = results
        mock_qdrant.get_related_notes_batch.return_value = {
            "a.md": [],
            "b.md": [],
            "c.md": [],
        }

        service.search(SearchRequest(query="test"))

        # Should be called once with all paths, not 3 times
        mock_qdrant.get_related_notes_batch.assert_called_once()
        call_args = mock_qdrant.get_related_notes_batch.call_args[0][0]
        assert call_args == {"a.md", "b.md", "c.md"}


class TestRelatedNoteAggregation:
    def test_related_notes_should_aggregate_link_counts(self) -> None:
        service, _, mock_qdrant = _make_search_service()
        results = _make_result_items(["a.md", "b.md"])
        mock_qdrant.hybrid_search.return_value = results
        # Both a.md and b.md link to external.md
        mock_qdrant.get_related_notes_batch.return_value = {
            "a.md": [
                {"related_path": "external.md", "relationship": "outgoing"},
            ],
            "b.md": [
                {"related_path": "external.md", "relationship": "outgoing"},
            ],
        }

        response = service.search(SearchRequest(query="test"))

        assert len(response.related_notes) == 1
        assert response.related_notes[0].note_path == "external.md"
        assert response.related_notes[0].link_count == 2

    def test_related_notes_should_sort_by_link_count_descending(self) -> None:
        service, _, mock_qdrant = _make_search_service()
        results = _make_result_items(["a.md", "b.md", "c.md"])
        mock_qdrant.hybrid_search.return_value = results
        mock_qdrant.get_related_notes_batch.return_value = {
            "a.md": [
                {"related_path": "popular.md", "relationship": "outgoing"},
                {"related_path": "rare.md", "relationship": "outgoing"},
            ],
            "b.md": [
                {"related_path": "popular.md", "relationship": "outgoing"},
            ],
            "c.md": [
                {"related_path": "popular.md", "relationship": "backlink"},
            ],
        }

        response = service.search(SearchRequest(query="test"))

        # popular.md has 3 links (2 outgoing + 1 backlink counted separately),
        # but outgoing and backlink are separate keys
        assert response.related_notes[0].note_path == "popular.md"
        assert response.related_notes[0].link_count >= 2

    def test_related_notes_should_derive_title_from_filename(self) -> None:
        service, _, mock_qdrant = _make_search_service()
        results = _make_result_items(["a.md"])
        mock_qdrant.hybrid_search.return_value = results
        mock_qdrant.get_related_notes_batch.return_value = {
            "a.md": [
                {
                    "related_path": "concepts/system-architecture.md",
                    "relationship": "outgoing",
                },
            ],
        }

        response = service.search(SearchRequest(query="test"))

        assert response.related_notes[0].note_title == "system-architecture"

    def test_related_notes_should_include_relationship_type(self) -> None:
        service, _, mock_qdrant = _make_search_service()
        results = _make_result_items(["a.md"])
        mock_qdrant.hybrid_search.return_value = results
        mock_qdrant.get_related_notes_batch.return_value = {
            "a.md": [
                {"related_path": "outgoing-target.md", "relationship": "outgoing"},
                {"related_path": "backlink-source.md", "relationship": "backlink"},
            ],
        }

        response = service.search(SearchRequest(query="test"))

        relationships = {r.relationship for r in response.related_notes}
        assert "outgoing" in relationships
        assert "backlink" in relationships
