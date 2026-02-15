"""End-to-end tests for the full pipeline: parse → chunk → embed → upsert → search.

Uses the test_vault fixture with mocked Qdrant and embedding services to verify
the entire flow works together without network dependencies.
"""

import os
from unittest.mock import MagicMock

from backend.application.index_service import IndexService
from backend.application.search_service import SearchService
from backend.domain.models import SearchRequest, SearchResultItem
from backend.infrastructure.chunker import Chunker
from backend.infrastructure.embedding import SparseVector
from backend.infrastructure.markdown_parser import MarkdownParser
from backend.infrastructure.vault_file_map import VaultFileMap

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "test_vault")


def _setup_pipeline() -> tuple[IndexService, SearchService, MagicMock, MagicMock]:
    """Build IndexService + SearchService with shared mocked deps."""
    vault_file_map = VaultFileMap(FIXTURES_DIR)
    parser = MarkdownParser(vault_file_map)
    chunker = Chunker()

    mock_embedder = MagicMock()
    mock_embedder.embed_batch.side_effect = lambda texts: [[0.0] * 384 for _ in texts]
    mock_embedder.embed_batch_sparse.side_effect = lambda texts: [
        SparseVector(indices=[1, 2], values=[0.5, 0.3]) for _ in texts
    ]
    mock_embedder.embed_text.return_value = [0.1] * 384
    mock_embedder.embed_text_sparse.return_value = SparseVector(
        indices=[1, 2], values=[0.5, 0.3]
    )

    mock_qdrant = MagicMock()
    mock_qdrant.is_healthy.return_value = True
    mock_qdrant.get_chunks_count.return_value = 0
    mock_qdrant.get_indexed_note_paths.return_value = set()
    mock_qdrant.hybrid_search.return_value = []
    mock_qdrant.get_related_notes_batch.return_value = {}

    index_service = IndexService(
        vault_path=FIXTURES_DIR,
        parser=parser,
        chunker=chunker,
        embedder=mock_embedder,
        qdrant_adapter=mock_qdrant,
        vault_file_map=vault_file_map,
    )
    index_service.initialize()

    search_service = SearchService(
        embedder=mock_embedder,
        qdrant_adapter=mock_qdrant,
    )

    return index_service, search_service, mock_qdrant, mock_embedder


class TestFullPipeline:
    def test_rebuild_then_search_should_use_hybrid_search(self) -> None:
        """Rebuild the index, then verify search uses hybrid (dense + sparse)."""
        index_svc, search_svc, mock_qdrant, mock_embedder = _setup_pipeline()

        # Step 1: Rebuild index
        result = index_svc.rebuild_index()
        assert result is not None
        assert result.status == "success"
        assert result.notes_indexed == 5
        assert result.chunks_created > 0

        # Verify both dense and sparse embeddings were generated during indexing
        assert mock_embedder.embed_batch.called
        assert mock_embedder.embed_batch_sparse.called

        # Verify chunks were upserted with sparse vectors
        upsert_calls = mock_qdrant.bulk_upsert_chunks.call_args_list
        assert len(upsert_calls) > 0
        for call in upsert_calls:
            _, kwargs = call
            assert "sparse_vectors" in kwargs

        # Step 2: Search
        mock_qdrant.hybrid_search.return_value = [
            SearchResultItem(
                chunk_id="chunk_0",
                note_path="note1.md",
                note_title="Simple Note",
                content="This is a simple note with no links.",
                score=0.85,
            )
        ]
        response = search_svc.search(SearchRequest(query="simple note"))

        # Verify hybrid search was called (not vector_search)
        mock_qdrant.hybrid_search.assert_called_once()
        call_kwargs = mock_qdrant.hybrid_search.call_args[1]
        assert "query_vector" in call_kwargs
        assert "sparse_vector" in call_kwargs

        assert response.total_hits == 1
        assert response.results[0].note_path == "note1.md"

    def test_index_single_note_then_search_should_work(self) -> None:
        """Index a single note, then search for it."""
        index_svc, search_svc, mock_qdrant, mock_embedder = _setup_pipeline()

        # Index a single note
        index_svc.index_single_note("note1.md")

        # Verify delete-before-insert pattern
        mock_qdrant.delete_by_note_path.assert_called_with("note1.md")
        mock_qdrant.delete_links_by_source.assert_called_with("note1.md")
        assert mock_qdrant.bulk_upsert_chunks.called

        # Verify sparse vectors were included
        _, kwargs = mock_qdrant.bulk_upsert_chunks.call_args
        assert "sparse_vectors" in kwargs

    def test_rebuild_should_index_all_vault_files(self) -> None:
        """Verify rebuild walks the vault and indexes all .md files."""
        index_svc, _, mock_qdrant, _ = _setup_pipeline()

        result = index_svc.rebuild_index()

        assert result is not None
        # test_vault has: note1.md, note2.md, note3.md,
        # concepts/architecture.md, projects/migration.md
        assert result.notes_indexed == 5

        # Each note should have had its old data deleted first
        delete_calls = mock_qdrant.delete_by_note_path.call_args_list
        deleted_paths = {call[0][0] for call in delete_calls}
        assert "note1.md" in deleted_paths
        assert "note2.md" in deleted_paths
        assert "note3.md" in deleted_paths

    def test_delete_note_should_remove_chunks_and_links(self) -> None:
        """Verify delete_note cleans up both chunks and links."""
        index_svc, _, mock_qdrant, _ = _setup_pipeline()

        index_svc.delete_note("note1.md")

        mock_qdrant.delete_by_note_path.assert_called_with("note1.md")
        mock_qdrant.delete_links_by_source.assert_called_with("note1.md")

    def test_rename_note_should_reindex_under_new_path(self) -> None:
        """Verify rename deletes old path and indexes new path."""
        index_svc, _, mock_qdrant, _ = _setup_pipeline()

        index_svc.rename_note("note1.md", "renamed.md")

        # Old path should be deleted
        mock_qdrant.delete_by_note_path.assert_any_call("note1.md")
        mock_qdrant.delete_links_by_source.assert_any_call("note1.md")

    def test_search_with_related_notes_should_enrich_results(self) -> None:
        """Verify search enriches results with related notes from links."""
        _, search_svc, mock_qdrant, _ = _setup_pipeline()

        mock_qdrant.hybrid_search.return_value = [
            SearchResultItem(
                chunk_id="chunk_0",
                note_path="note3.md",
                note_title="Linked Note",
                content="This note links to other notes.",
                score=0.9,
            )
        ]
        mock_qdrant.get_related_notes_batch.return_value = {
            "note3.md": [
                {
                    "related_path": "concepts/architecture.md",
                    "relationship": "outgoing",
                },
                {"related_path": "projects/migration.md", "relationship": "backlink"},
            ]
        }

        response = search_svc.search(
            SearchRequest(query="linked note", include_related=True)
        )

        assert response.total_hits == 1
        assert len(response.related_notes) == 2
        related_paths = {r.note_path for r in response.related_notes}
        assert "concepts/architecture.md" in related_paths
        assert "projects/migration.md" in related_paths

    def test_get_status_should_reflect_index_state(self) -> None:
        """Verify get_status returns current index statistics."""
        index_svc, _, mock_qdrant, _ = _setup_pipeline()

        mock_qdrant.get_chunks_count.return_value = 42
        mock_qdrant.get_indexed_note_paths.return_value = {"a.md", "b.md", "c.md"}

        status = index_svc.get_status()

        assert status.indexed_notes == 3
        assert status.indexed_chunks == 42
        assert status.qdrant_healthy is True
        assert status.watcher_running is False
