"""Persistent SHA-256 hash registry for incremental vault indexing."""

import hashlib
import json
import os

from backend.domain.constants import HASH_REGISTRY_FILENAME
from backend.logging_config import get_logger

logger = get_logger(__name__)


def compute_sha256(content: str) -> str:
    """Return the SHA-256 hex digest of a UTF-8 string."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class HashRegistry:
    """Track per-file SHA-256 hashes to detect content changes.

    Mutations (set_hash, remove) are in-memory only. The caller must invoke
    save() explicitly — typically once at the end of incremental_rebuild() —
    to avoid O(N) disk writes during a large vault scan.
    """

    def __init__(self, data_path: str) -> None:
        self._registry_path = os.path.join(data_path, HASH_REGISTRY_FILENAME)
        self._hashes: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        """Load registry from disk, initializing an empty dict on first run."""
        if not os.path.exists(self._registry_path):
            logger.info("Hash registry not found; starting fresh: %s", self._registry_path)
            return
        try:
            with open(self._registry_path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                self._hashes = data
                logger.info("Loaded hash registry: %d entries", len(self._hashes))
            else:
                logger.warning("Hash registry has unexpected format; starting fresh")
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to load hash registry: %s; starting fresh", exc)

    def get_hash(self, file_path: str) -> str | None:
        """Return the stored SHA-256 hex for file_path, or None if untracked."""
        return self._hashes.get(file_path)

    def set_hash(self, file_path: str, sha256_hex: str) -> None:
        """Update hash in memory only. Call save() when the rebuild batch is done."""
        self._hashes[file_path] = sha256_hex

    def remove(self, file_path: str) -> None:
        """Remove a path from the registry in memory. Call save() to persist."""
        self._hashes.pop(file_path, None)

    def get_all_known_paths(self) -> set[str]:
        """Return all file paths currently tracked in the registry."""
        return set(self._hashes.keys())

    def save(self) -> None:
        """Persist the in-memory registry to disk as JSON.

        Creates parent directories if necessary. Safe to call even if data_path
        does not exist yet (e.g., first startup before the volume is created).
        """
        try:
            os.makedirs(os.path.dirname(self._registry_path), exist_ok=True)
            tmp_path = self._registry_path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self._hashes, f, indent=2)
            os.replace(tmp_path, self._registry_path)
            logger.debug("Hash registry saved: %d entries", len(self._hashes))
        except OSError as exc:
            logger.warning("Failed to save hash registry: %s", exc)
