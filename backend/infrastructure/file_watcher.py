"""File system watcher for Obsidian vault using watchdog."""

import os
from collections.abc import Callable

from watchdog.events import (
    FileCreatedEvent,
    FileDeletedEvent,
    FileModifiedEvent,
    FileMovedEvent,
    FileSystemEventHandler,
)
from watchdog.observers import Observer

from backend.domain.constants import WATCH_EXTENSIONS
from backend.logging_config import get_logger

logger = get_logger(__name__)


class _VaultEventHandler(FileSystemEventHandler):
    """Handle file system events for .md files in the vault."""

    def __init__(
        self,
        vault_path: str,
        on_changed: Callable[[str], None],
        on_deleted: Callable[[str], None],
        on_moved: Callable[[str, str], None],
    ) -> None:
        self._vault_path = vault_path
        self._on_changed = on_changed
        self._on_deleted = on_deleted
        self._on_moved = on_moved

    def _is_watched(self, path: str) -> bool:
        """Check if the file has a watched extension."""
        return any(path.endswith(ext) for ext in WATCH_EXTENSIONS)

    def _rel_path(self, abs_path: str) -> str:
        """Convert absolute path to vault-relative path."""
        return os.path.relpath(abs_path, self._vault_path)

    def on_created(self, event: FileCreatedEvent) -> None:
        if event.is_directory or not self._is_watched(event.src_path):
            return
        rel = self._rel_path(event.src_path)
        logger.info("File created: %s", rel)
        self._on_changed(rel)

    def on_modified(self, event: FileModifiedEvent) -> None:
        if event.is_directory or not self._is_watched(event.src_path):
            return
        rel = self._rel_path(event.src_path)
        logger.info("File modified: %s", rel)
        self._on_changed(rel)

    def on_deleted(self, event: FileDeletedEvent) -> None:
        if event.is_directory or not self._is_watched(event.src_path):
            return
        rel = self._rel_path(event.src_path)
        logger.info("File deleted: %s", rel)
        self._on_deleted(rel)

    def on_moved(self, event: FileMovedEvent) -> None:
        if event.is_directory:
            return

        old_watched = self._is_watched(event.src_path)
        new_watched = self._is_watched(event.dest_path)

        if old_watched and new_watched:
            old_rel = self._rel_path(event.src_path)
            new_rel = self._rel_path(event.dest_path)
            logger.info("File moved: %s -> %s", old_rel, new_rel)
            self._on_moved(old_rel, new_rel)
        elif old_watched and not new_watched:
            # Renamed to a non-.md extension — treat as delete
            old_rel = self._rel_path(event.src_path)
            logger.info("File moved out of watch scope (delete): %s", old_rel)
            self._on_deleted(old_rel)
        elif not old_watched and new_watched:
            # Renamed from non-.md to .md — treat as create
            new_rel = self._rel_path(event.dest_path)
            logger.info("File moved into watch scope (create): %s", new_rel)
            self._on_changed(new_rel)


class FileWatcher:
    """Monitor an Obsidian vault directory for .md file changes."""

    def __init__(
        self,
        vault_path: str,
        on_changed: Callable[[str], None],
        on_deleted: Callable[[str], None],
        on_moved: Callable[[str, str], None],
    ) -> None:
        self._vault_path = vault_path
        self._handler = _VaultEventHandler(
            vault_path=vault_path,
            on_changed=on_changed,
            on_deleted=on_deleted,
            on_moved=on_moved,
        )
        self._observer = Observer()
        self._running = False

    def start(self) -> None:
        """Start watching the vault directory."""
        if self._running:
            return
        self._observer.schedule(self._handler, self._vault_path, recursive=True)
        self._observer.start()
        self._running = True
        logger.info("File watcher started for: %s", self._vault_path)

    def stop(self) -> None:
        """Stop watching the vault directory."""
        if not self._running:
            return
        self._observer.stop()
        self._observer.join(timeout=5)
        self._running = False
        logger.info("File watcher stopped")

    @property
    def is_running(self) -> bool:
        """Return whether the watcher is currently active."""
        return self._running
