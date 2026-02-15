"""Tests for the FileWatcher and watcher integration with IndexService."""

import os
import shutil
import tempfile
import time
from unittest.mock import MagicMock

import pytest

from backend.infrastructure.file_watcher import FileWatcher


@pytest.fixture()
def temp_vault():
    """Create a temporary vault directory for watcher tests."""
    vault_dir = tempfile.mkdtemp(prefix="test_vault_")
    yield vault_dir
    shutil.rmtree(vault_dir, ignore_errors=True)


def _write_file(vault: str, rel_path: str, content: str = "# Test") -> str:
    """Write a file to the vault, creating parent dirs as needed."""
    abs_path = os.path.join(vault, rel_path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    with open(abs_path, "w", encoding="utf-8") as f:
        f.write(content)
    return abs_path


class TestFileWatcherLifecycle:
    def test_watcher_should_start_and_report_running(self, temp_vault: str) -> None:
        watcher = FileWatcher(
            vault_path=temp_vault,
            on_changed=lambda p: None,
            on_deleted=lambda p: None,
            on_moved=lambda o, n: None,
        )
        assert not watcher.is_running

        watcher.start()
        assert watcher.is_running

        watcher.stop()
        assert not watcher.is_running

    def test_watcher_start_should_be_idempotent(self, temp_vault: str) -> None:
        watcher = FileWatcher(
            vault_path=temp_vault,
            on_changed=lambda p: None,
            on_deleted=lambda p: None,
            on_moved=lambda o, n: None,
        )
        watcher.start()
        watcher.start()  # Should not raise
        assert watcher.is_running
        watcher.stop()

    def test_watcher_stop_should_be_idempotent(self, temp_vault: str) -> None:
        watcher = FileWatcher(
            vault_path=temp_vault,
            on_changed=lambda p: None,
            on_deleted=lambda p: None,
            on_moved=lambda o, n: None,
        )
        watcher.stop()  # Not started — should not raise
        assert not watcher.is_running


class TestFileWatcherEvents:
    def test_watcher_should_detect_file_creation(self, temp_vault: str) -> None:
        on_changed = MagicMock()
        watcher = FileWatcher(
            vault_path=temp_vault,
            on_changed=on_changed,
            on_deleted=lambda p: None,
            on_moved=lambda o, n: None,
        )
        watcher.start()

        try:
            _write_file(temp_vault, "new_note.md")
            # Wait for watchdog to deliver event
            time.sleep(1)
            on_changed.assert_called()
            # Check that the relative path was passed
            args_list = [c.args[0] for c in on_changed.call_args_list]
            assert any("new_note.md" in arg for arg in args_list)
        finally:
            watcher.stop()

    def test_watcher_should_detect_file_modification(self, temp_vault: str) -> None:
        # Create file before starting watcher
        _write_file(temp_vault, "existing.md", "# Original")

        on_changed = MagicMock()
        watcher = FileWatcher(
            vault_path=temp_vault,
            on_changed=on_changed,
            on_deleted=lambda p: None,
            on_moved=lambda o, n: None,
        )
        watcher.start()

        try:
            # Small sleep so watcher is fully ready
            time.sleep(0.5)
            on_changed.reset_mock()

            # Modify the file
            _write_file(temp_vault, "existing.md", "# Modified content")
            time.sleep(1)

            on_changed.assert_called()
            args_list = [c.args[0] for c in on_changed.call_args_list]
            assert any("existing.md" in arg for arg in args_list)
        finally:
            watcher.stop()

    def test_watcher_should_detect_file_deletion(self, temp_vault: str) -> None:
        abs_path = _write_file(temp_vault, "to_delete.md")

        on_deleted = MagicMock()
        watcher = FileWatcher(
            vault_path=temp_vault,
            on_changed=lambda p: None,
            on_deleted=on_deleted,
            on_moved=lambda o, n: None,
        )
        watcher.start()

        try:
            time.sleep(0.5)
            os.remove(abs_path)
            time.sleep(1)

            on_deleted.assert_called()
            args_list = [c.args[0] for c in on_deleted.call_args_list]
            assert any("to_delete.md" in arg for arg in args_list)
        finally:
            watcher.stop()

    def test_watcher_should_detect_file_move(self, temp_vault: str) -> None:
        _write_file(temp_vault, "old_name.md")

        on_moved = MagicMock()
        watcher = FileWatcher(
            vault_path=temp_vault,
            on_changed=lambda p: None,
            on_deleted=lambda p: None,
            on_moved=on_moved,
        )
        watcher.start()

        try:
            time.sleep(0.5)
            os.rename(
                os.path.join(temp_vault, "old_name.md"),
                os.path.join(temp_vault, "new_name.md"),
            )
            time.sleep(1)

            on_moved.assert_called()
            move_args = on_moved.call_args_list[-1].args
            assert "old_name.md" in move_args[0]
            assert "new_name.md" in move_args[1]
        finally:
            watcher.stop()

    def test_watcher_should_ignore_non_md_files(self, temp_vault: str) -> None:
        on_changed = MagicMock()
        watcher = FileWatcher(
            vault_path=temp_vault,
            on_changed=on_changed,
            on_deleted=lambda p: None,
            on_moved=lambda o, n: None,
        )
        watcher.start()

        try:
            time.sleep(0.5)
            on_changed.reset_mock()

            _write_file(temp_vault, "image.png", "fake image data")
            _write_file(temp_vault, "config.json", '{"key": "value"}')
            time.sleep(1)

            # on_changed should not be called for non-.md files
            for c in on_changed.call_args_list:
                assert ".md" in c.args[0], f"Non-.md file triggered callback: {c.args[0]}"
        finally:
            watcher.stop()

    def test_watcher_should_detect_nested_directory_file(self, temp_vault: str) -> None:
        on_changed = MagicMock()
        watcher = FileWatcher(
            vault_path=temp_vault,
            on_changed=on_changed,
            on_deleted=lambda p: None,
            on_moved=lambda o, n: None,
        )
        watcher.start()

        try:
            time.sleep(0.5)
            _write_file(temp_vault, "projects/deep/nested.md")
            time.sleep(1)

            on_changed.assert_called()
            args_list = [c.args[0] for c in on_changed.call_args_list]
            assert any("nested.md" in arg for arg in args_list)
        finally:
            watcher.stop()


class TestIndexServiceWatcherIntegration:
    """Test IndexService watcher start/stop and status reporting."""

    def test_index_service_should_report_watcher_running_true(self) -> None:
        from backend.application.index_service import IndexService

        service = IndexService.__new__(IndexService)
        service._vault_path = "/fake"
        service._qdrant = MagicMock()
        service._qdrant.get_chunks_count.return_value = 0
        service._qdrant.get_indexed_note_paths.return_value = []
        service._qdrant.is_healthy.return_value = True
        service._last_indexed = None
        service._rebuilding = False

        # Simulate watcher running
        mock_watcher = MagicMock()
        mock_watcher.is_running = True
        service._watcher = mock_watcher
        service._debouncer = MagicMock()

        status = service.get_status()
        assert status.watcher_running is True

    def test_index_service_should_report_watcher_running_false_when_no_watcher(
        self,
    ) -> None:
        from backend.application.index_service import IndexService

        service = IndexService.__new__(IndexService)
        service._vault_path = "/fake"
        service._qdrant = MagicMock()
        service._qdrant.get_chunks_count.return_value = 0
        service._qdrant.get_indexed_note_paths.return_value = []
        service._qdrant.is_healthy.return_value = True
        service._last_indexed = None
        service._rebuilding = False
        service._watcher = None
        service._debouncer = None

        status = service.get_status()
        assert status.watcher_running is False

    def test_stop_watcher_should_cancel_debouncer_and_stop_watcher(self) -> None:
        from backend.application.index_service import IndexService

        service = IndexService.__new__(IndexService)
        service._watcher = MagicMock()
        service._debouncer = MagicMock()

        service.stop_watcher()

        service._debouncer.cancel_all.assert_called_once()
        service._watcher.stop.assert_called_once()
