"""File system watcher for Obsidian vault using watchdog."""

import os
from collections.abc import Callable
from typing import Literal

from watchdog.events import (
    FileCreatedEvent,
    FileDeletedEvent,
    FileModifiedEvent,
    FileMovedEvent,
    FileSystemEventHandler,
)
from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver

from backend.domain.constants import (
    POLLING_INTERVAL_SECONDS,
    POLLING_INTERVAL_MIN_SECONDS,
    WATCH_EXTENSIONS,
)
from backend.logging_config import get_logger

logger = get_logger(__name__)


def _create_observer(
    use_polling: bool, polling_interval: float
) -> Observer | PollingObserver:
    if use_polling:
        safe_interval = max(POLLING_INTERVAL_MIN_SECONDS, polling_interval)
        if safe_interval != polling_interval:
            logger.warning(
                "polling_interval %.2fs is below minimum; clamped to %.2fs",
                polling_interval,
                safe_interval,
            )
        return PollingObserver(timeout=safe_interval)
    return Observer()


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
        use_polling: bool = False,
        polling_interval: float = POLLING_INTERVAL_SECONDS,
    ) -> None:
        self._vault_path = vault_path
        self._handler = _VaultEventHandler(
            vault_path=vault_path,
            on_changed=on_changed,
            on_deleted=on_deleted,
            on_moved=on_moved,
        )
        self._observer = _create_observer(use_polling, polling_interval)
        self._mode: Literal["polling", "event"] = (
            "polling" if use_polling else "event"
        )
        self._running = False

    def start(self) -> None:
        """Start watching the vault directory."""
        if self._running:
            return
        self._observer.schedule(self._handler, self._vault_path, recursive=True)
        self._observer.start()
        self._running = True
        logger.info(
            "File watcher started for: %s (mode=%s)", self._vault_path, self._mode
        )

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

    @property
    def observer_mode(self) -> Literal["polling", "event"]:
        """Return the observer mode for status reporting."""
        return self._mode
