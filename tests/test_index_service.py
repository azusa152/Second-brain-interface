import os
import shutil
import tempfile
from unittest.mock import MagicMock

import pytest

from backend.application.index_service import IndexService
from backend.domain.exceptions import RebuildInProgressError
from backend.infrastructure.chunker import Chunker
from backend.infrastructure.event_log import EventLog
from backend.infrastructure.hash_registry import HashRegistry
from backend.infrastructure.markdown_parser import MarkdownParser
from backend.infrastructure.vault_file_map import VaultFileMap

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "test_vault")


def _make_service(
    vault_path: str = FIXTURES_DIR,
    event_log: EventLog | None = None,
) -> tuple[IndexService, MagicMock, MagicMock]:
    """Create an IndexService with mocked Qdrant and embedding."""
    vault_file_map = VaultFileMap(vault_path)
    parser = MarkdownParser(vault_file_map)
    chunker = Chunker()
    mock_embedder = MagicMock()
    mock_embedder.embed_batch.return_value = []
    mock_embedder.embed_batch_sparse.return_value = []
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
        event_log=event_log,
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
        mock_embedder.embed_batch_sparse.side_effect = lambda texts: [
            MagicMock(indices=[1], values=[0.5]) for _ in texts
        ]

        result = service.rebuild_index()

        assert result is not None
        assert result.status == "success"
        assert result.notes_indexed == 5
        assert result.chunks_created > 0
        assert mock_qdrant.bulk_upsert_chunks.called

    def test_rebuild_should_raise_if_already_running(self) -> None:
        service, _, _ = _make_service()

        # Simulate concurrent rebuild by holding the lock
        service._rebuild_lock.acquire()
        try:
            with pytest.raises(RebuildInProgressError):
                service.rebuild_index()
        finally:
            service._rebuild_lock.release()


def _make_service_with_registry(
    vault_path: str,
    data_dir: str,
) -> tuple[IndexService, MagicMock, MagicMock, HashRegistry]:
    """Create an IndexService wired with a real HashRegistry for incremental rebuild tests."""
    vault_file_map = VaultFileMap(vault_path)
    parser = MarkdownParser(vault_file_map)
    chunker = Chunker()
    mock_embedder = MagicMock()
    mock_embedder.embed_batch.side_effect = lambda texts: [[0.0] * 384 for _ in texts]
    mock_embedder.embed_batch_sparse.side_effect = lambda texts: [
        MagicMock(indices=[1], values=[0.5]) for _ in texts
    ]
    mock_qdrant = MagicMock()
    mock_qdrant.is_healthy.return_value = True
    mock_qdrant.get_chunks_count.return_value = 0
    mock_qdrant.get_indexed_note_paths.return_value = set()

    hash_registry = HashRegistry(data_dir)

    service = IndexService(
        vault_path=vault_path,
        parser=parser,
        chunker=chunker,
        embedder=mock_embedder,
        qdrant_adapter=mock_qdrant,
        vault_file_map=vault_file_map,
        hash_registry=hash_registry,
    )
    service.initialize()
    return service, mock_qdrant, mock_embedder, hash_registry


@pytest.fixture()
def temp_vault():
    """Temporary vault directory pre-populated with two .md files."""
    d = tempfile.mkdtemp(prefix="test_vault_")
    _write(d, "a.md", "# Note A\n\nContent A.")
    _write(d, "b.md", "# Note B\n\nContent B.")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture()
def data_dir():
    """Temporary data directory for the hash registry."""
    d = tempfile.mkdtemp(prefix="test_data_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


def _write(vault: str, rel_path: str, content: str) -> str:
    abs_path = os.path.join(vault, rel_path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    with open(abs_path, "w", encoding="utf-8") as f:
        f.write(content)
    return abs_path


class TestIncrementalRebuild:
    def test_first_run_indexes_all_files(self, temp_vault: str, data_dir: str) -> None:
        """On the first run (empty registry) every file is treated as new."""
        service, mock_qdrant, _, _ = _make_service_with_registry(temp_vault, data_dir)

        service.incremental_rebuild()

        assert mock_qdrant.bulk_upsert_chunks.call_count == 2

    def test_unchanged_files_are_skipped(self, temp_vault: str, data_dir: str) -> None:
        """Second run with no file changes should not call bulk_upsert_chunks."""
        service, mock_qdrant, _, _ = _make_service_with_registry(temp_vault, data_dir)
        service.incremental_rebuild()
        mock_qdrant.reset_mock()

        service.incremental_rebuild()

        mock_qdrant.bulk_upsert_chunks.assert_not_called()

    def test_changed_file_is_reindexed(self, temp_vault: str, data_dir: str) -> None:
        """Only the file whose content changed should be re-indexed on second run."""
        service, mock_qdrant, _, _ = _make_service_with_registry(temp_vault, data_dir)
        service.incremental_rebuild()
        mock_qdrant.reset_mock()

        _write(temp_vault, "a.md", "# Note A\n\nUpdated content.")
        service.incremental_rebuild()

        assert mock_qdrant.bulk_upsert_chunks.call_count == 1
        mock_qdrant.delete_by_note_path.assert_any_call("a.md")

    def test_deleted_file_is_removed_from_qdrant(
        self, temp_vault: str, data_dir: str
    ) -> None:
        """A file removed from the vault should be deleted from Qdrant and the registry."""
        service, mock_qdrant, _, hash_registry = _make_service_with_registry(
            temp_vault, data_dir
        )
        service.incremental_rebuild()
        mock_qdrant.reset_mock()

        os.remove(os.path.join(temp_vault, "b.md"))
        service.incremental_rebuild()

        mock_qdrant.delete_by_note_path.assert_any_call("b.md")
        mock_qdrant.delete_links_by_source.assert_any_call("b.md")
        assert hash_registry.get_hash("b.md") is None

    def test_last_scheduled_rebuild_is_set_after_run(
        self, temp_vault: str, data_dir: str
    ) -> None:
        """last_scheduled_rebuild timestamp should be set after a successful run."""
        service, _, _, _ = _make_service_with_registry(temp_vault, data_dir)
        assert service.get_status().last_scheduled_rebuild is None

        service.incremental_rebuild()

        assert service.get_status().last_scheduled_rebuild is not None

    def test_second_concurrent_call_is_skipped(
        self, temp_vault: str, data_dir: str
    ) -> None:
        """If the lock is held, a concurrent incremental_rebuild call returns immediately."""
        service, mock_qdrant, _, _ = _make_service_with_registry(temp_vault, data_dir)

        service._rebuild_lock.acquire()
        try:
            service.incremental_rebuild()
        finally:
            service._rebuild_lock.release()

        mock_qdrant.bulk_upsert_chunks.assert_not_called()

    def test_falls_back_to_full_rebuild_when_no_registry(self) -> None:
        """With no HashRegistry, incremental_rebuild delegates to rebuild_index."""
        service, mock_qdrant, mock_embedder = _make_service()
        mock_embedder.embed_batch.side_effect = lambda texts: [
            [0.0] * 384 for _ in texts
        ]
        mock_embedder.embed_batch_sparse.side_effect = lambda texts: [
            MagicMock(indices=[1], values=[0.5]) for _ in texts
        ]
        assert service._hash_registry is None

        service.incremental_rebuild()

        assert mock_qdrant.bulk_upsert_chunks.called

    def test_registry_is_persisted_after_run(self, temp_vault: str, data_dir: str) -> None:
        """hash_registry.json should exist on disk after a completed incremental rebuild."""
        service, _, _, _ = _make_service_with_registry(temp_vault, data_dir)
        service.incremental_rebuild()

        registry_path = os.path.join(data_dir, "hash_registry.json")
        assert os.path.exists(registry_path)

    def test_file_map_is_refreshed_before_processing(
        self, temp_vault: str, data_dir: str
    ) -> None:
        """New files added after initialize() should be known to VaultFileMap during rebuild."""
        service, _, _, _ = _make_service_with_registry(temp_vault, data_dir)
        new_file = _write(temp_vault, "c.md", "# Note C\n\nNew file.")

        service.incremental_rebuild()

        # c.md was not present at initialize() time; the rebuild should have scanned
        # and added it to the file map
        assert service._file_map.has_file("c.md")
        os.remove(new_file)


class TestIndexSingleNote:
    def test_index_single_note_should_delete_old_and_insert_new(self) -> None:
        service, mock_qdrant, mock_embedder = _make_service()
        mock_embedder.embed_batch.return_value = [[0.0] * 384]
        mock_embedder.embed_batch_sparse.return_value = [
            MagicMock(indices=[1], values=[0.5])
        ]

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
        mock_embedder.embed_batch_sparse.return_value = [
            MagicMock(indices=[1], values=[0.5])
        ]

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
        assert status.watcher_mode == "event"

    def test_get_status_should_default_to_event_mode(self) -> None:
        service, _, _ = _make_service()

        status = service.get_status()

        assert status.watcher_mode == "event"

    def test_get_status_should_report_polling_mode_when_configured(self) -> None:
        service, mock_qdrant, _ = _make_service()
        mock_qdrant.get_chunks_count.return_value = 0
        mock_qdrant.get_indexed_note_paths.return_value = set()
        service._use_polling = True

        status = service.get_status()

        assert status.watcher_mode == "polling"


class TestStartWatcher:
    def test_start_watcher_should_pass_polling_config_to_file_watcher(self) -> None:
        from unittest.mock import patch

        service, _, _ = _make_service()
        service._use_polling = True
        service._polling_interval = 5.0

        with patch(
            "backend.application.index_service.FileWatcher"
        ) as mock_file_watcher_cls:
            mock_watcher_instance = MagicMock()
            mock_watcher_instance.is_running = False
            mock_file_watcher_cls.return_value = mock_watcher_instance

            service.start_watcher()

            _, kwargs = mock_file_watcher_cls.call_args
            assert kwargs["use_polling"] is True
            assert kwargs["polling_interval"] == 5.0

    def test_start_watcher_should_pass_event_mode_defaults(self) -> None:
        from unittest.mock import patch

        service, _, _ = _make_service()

        with patch(
            "backend.application.index_service.FileWatcher"
        ) as mock_file_watcher_cls:
            mock_watcher_instance = MagicMock()
            mock_watcher_instance.is_running = False
            mock_file_watcher_cls.return_value = mock_watcher_instance

            service.start_watcher()

            _, kwargs = mock_file_watcher_cls.call_args
            assert kwargs["use_polling"] is False


class TestGetIndexedNotes:
    def test_get_indexed_notes_should_delegate_to_qdrant(self) -> None:
        from backend.domain.models import IndexedNoteItem

        service, mock_qdrant, _ = _make_service()
        mock_qdrant.get_indexed_notes.return_value = [
            IndexedNoteItem(note_path="notes/a.md", note_title="A"),
            IndexedNoteItem(note_path="notes/b.md", note_title="B"),
        ]

        notes = service.get_indexed_notes()

        mock_qdrant.get_indexed_notes.assert_called_once()
        assert len(notes) == 2
        assert notes[0].note_path == "notes/a.md"
        assert notes[0].note_title == "A"
        assert notes[1].note_path == "notes/b.md"

    def test_get_indexed_notes_should_return_empty_list(self) -> None:
        service, mock_qdrant, _ = _make_service()
        mock_qdrant.get_indexed_notes.return_value = []

        notes = service.get_indexed_notes()

        assert notes == []


class TestEventRecording:
    def test_on_file_changed_should_record_created_event_for_new_file(self) -> None:
        event_log = EventLog()
        service, _, mock_embedder = _make_service(event_log=event_log)
        mock_embedder.embed_batch.return_value = [[0.0] * 384]
        mock_embedder.embed_batch_sparse.return_value = [
            MagicMock(indices=[1], values=[0.5])
        ]

        # note1.md exists on disk but hasn't been added to file map yet
        # (file map was scanned in initialize(), so it IS known)
        # Use a truly new filename to get "created"
        service._on_file_changed("brand_new_note.md")

        events = event_log.get_recent()
        assert len(events) == 1
        assert events[0].event_type == "created"
        assert events[0].file_path == "brand_new_note.md"

    def test_on_file_changed_should_record_modified_event_for_existing_file(
        self,
    ) -> None:
        event_log = EventLog()
        service, _, mock_embedder = _make_service(event_log=event_log)
        mock_embedder.embed_batch.return_value = [[0.0] * 384]
        mock_embedder.embed_batch_sparse.return_value = [
            MagicMock(indices=[1], values=[0.5])
        ]

        # note1.md is in the fixture vault and was scanned into the file map
        service._on_file_changed("note1.md")

        events = event_log.get_recent()
        assert len(events) == 1
        assert events[0].event_type == "modified"
        assert events[0].file_path == "note1.md"

    def test_on_file_deleted_should_record_deleted_event(self) -> None:
        event_log = EventLog()
        service, _, _ = _make_service(event_log=event_log)

        service._on_file_deleted("removed.md")

        events = event_log.get_recent()
        assert len(events) == 1
        assert events[0].event_type == "deleted"
        assert events[0].file_path == "removed.md"

    def test_on_file_moved_should_record_moved_event_with_dest_path(self) -> None:
        event_log = EventLog()
        service, _, mock_embedder = _make_service(event_log=event_log)
        mock_embedder.embed_batch.return_value = [[0.0] * 384]
        mock_embedder.embed_batch_sparse.return_value = [
            MagicMock(indices=[1], values=[0.5])
        ]

        service._on_file_moved("old.md", "new.md")

        events = event_log.get_recent()
        assert len(events) == 1
        assert events[0].event_type == "moved"
        assert events[0].file_path == "old.md"
        assert events[0].dest_path == "new.md"

    def test_get_recent_events_should_delegate_to_event_log(self) -> None:
        event_log = EventLog()
        service, _, _ = _make_service(event_log=event_log)

        service._on_file_deleted("a.md")
        service._on_file_deleted("b.md")
        service._on_file_deleted("c.md")

        events = service.get_recent_events(limit=2)
        assert len(events) == 2
        assert events[0].file_path == "c.md"
        assert events[1].file_path == "b.md"
