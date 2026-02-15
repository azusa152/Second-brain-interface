import os
from unittest.mock import MagicMock

from backend.application.index_service import IndexService
from backend.infrastructure.chunker import Chunker
from backend.infrastructure.markdown_parser import MarkdownParser
from backend.infrastructure.vault_file_map import VaultFileMap

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "test_vault")


def _make_service(
    vault_path: str = FIXTURES_DIR,
) -> tuple[IndexService, MagicMock, MagicMock]:
    """Create an IndexService with mocked Qdrant and embedding."""
    vault_file_map = VaultFileMap(vault_path)
    parser = MarkdownParser(vault_file_map)
    chunker = Chunker()
    mock_embedder = MagicMock()
    mock_embedder.embed_batch.return_value = []
    mock_qdrant = MagicMock()
    mock_qdrant.is_healthy.return_value = True
    mock_qdrant.get_chunks_count.return_value = 0
    mock_qdrant.get_indexed_note_paths.return_value = set()

    service = IndexService(
        vault_path=vault_path,
        parser=parser,
        chunker=chunker,
        embedder=mock_embedder,
        qdrant_adapter=mock_qdrant,
        vault_file_map=vault_file_map,
    )
    service.initialize()
    return service, mock_qdrant, mock_embedder


class TestRebuildIndex:
    def test_rebuild_should_index_all_md_files(self) -> None:
        service, mock_qdrant, mock_embedder = _make_service()

        # Make embed_batch return fake vectors matching chunk count
        mock_embedder.embed_batch.side_effect = lambda texts: [
            [0.0] * 384 for _ in texts
        ]

        result = service.rebuild_index()

        assert result is not None
        assert result.status == "success"
        assert result.notes_indexed == 5
        assert result.chunks_created > 0
        assert mock_qdrant.bulk_upsert_chunks.called

    def test_rebuild_should_return_error_if_already_running(self) -> None:
        service, _, mock_embedder = _make_service()
        mock_embedder.embed_batch.side_effect = lambda texts: [
            [0.0] * 384 for _ in texts
        ]

        # Simulate concurrent rebuild
        service._rebuilding = True
        result = service.rebuild_index()

        assert result is None


class TestIndexSingleNote:
    def test_index_single_note_should_delete_old_and_insert_new(self) -> None:
        service, mock_qdrant, mock_embedder = _make_service()
        mock_embedder.embed_batch.return_value = [[0.0] * 384]

        service.index_single_note("note1.md")

        mock_qdrant.delete_by_note_path.assert_called_once_with("note1.md")
        mock_qdrant.delete_links_by_source.assert_called_once_with("note1.md")
        assert mock_qdrant.bulk_upsert_chunks.called

    def test_index_single_note_should_skip_missing_file(self) -> None:
        service, mock_qdrant, _ = _make_service()

        service.index_single_note("nonexistent.md")

        mock_qdrant.bulk_upsert_chunks.assert_not_called()


class TestDeleteNote:
    def test_delete_note_should_remove_chunks_and_links(self) -> None:
        service, mock_qdrant, _ = _make_service()

        service.delete_note("note1.md")

        mock_qdrant.delete_by_note_path.assert_called_once_with("note1.md")
        mock_qdrant.delete_links_by_source.assert_called_once_with("note1.md")


class TestRenameNote:
    def test_rename_should_delete_old_and_index_new(self) -> None:
        service, mock_qdrant, mock_embedder = _make_service()
        mock_embedder.embed_batch.return_value = [[0.0] * 384]

        service.rename_note("note1.md", "renamed.md")

        mock_qdrant.delete_by_note_path.assert_any_call("note1.md")
        mock_qdrant.delete_links_by_source.assert_any_call("note1.md")


class TestGetStatus:
    def test_get_status_should_return_index_status(self) -> None:
        service, mock_qdrant, _ = _make_service()
        mock_qdrant.get_chunks_count.return_value = 42
        mock_qdrant.get_indexed_note_paths.return_value = {"a.md", "b.md"}

        status = service.get_status()

        assert status.indexed_notes == 2
        assert status.indexed_chunks == 42
        assert status.qdrant_healthy is True
        assert status.watcher_running is False
