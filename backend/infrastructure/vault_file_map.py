import os

from backend.domain.constants import WATCH_EXTENSIONS
from backend.logging_config import get_logger

logger = get_logger(__name__)


class VaultFileMap:
    """Maintains a filename -> full_path mapping for wikilink resolution."""

    def __init__(self, vault_path: str) -> None:
        self._vault_path = vault_path
        self._map: dict[str, str] = {}  # lowercase filename (no ext) -> relative path

    @property
    def file_count(self) -> int:
        """Return the number of files tracked."""
        return len(self._map)

    def scan(self) -> None:
        """Walk vault directory and build the map."""
        self._map.clear()
        for root, _dirs, files in os.walk(self._vault_path):
            for filename in files:
                if not any(filename.endswith(ext) for ext in WATCH_EXTENSIONS):
                    continue
                abs_path = os.path.join(root, filename)
                rel_path = os.path.relpath(abs_path, self._vault_path)
                stem = os.path.splitext(filename)[0].lower()
                if stem in self._map:
                    logger.warning(
                        "VaultFileMap name collision: '%s' resolves to both "
                        "'%s' and '%s' (keeping latter)",
                        stem,
                        self._map[stem],
                        rel_path,
                    )
                self._map[stem] = rel_path
        logger.info("VaultFileMap scanned %d files", len(self._map))

    def resolve(self, link_text: str) -> str | None:
        """Resolve [[Link]] to actual file path. Returns None if not found."""
        # Strip any heading anchors: [[note#heading]] -> "note"
        key = link_text.split("#")[0].strip().lower()
        return self._map.get(key)

    def update_file(self, old_path: str | None, new_path: str) -> None:
        """Update map when file is created/moved/renamed."""
        # Remove old entry if present
        if old_path is not None:
            old_stem = os.path.splitext(os.path.basename(old_path))[0].lower()
            self._map.pop(old_stem, None)

        # Add new entry
        new_stem = os.path.splitext(os.path.basename(new_path))[0].lower()
        self._map[new_stem] = new_path

    def has_file(self, path: str) -> bool:
        """Check whether a file (by relative path basename) is tracked."""
        stem = os.path.splitext(os.path.basename(path))[0].lower()
        return stem in self._map

    def remove_file(self, path: str) -> None:
        """Remove a file from the map."""
        stem = os.path.splitext(os.path.basename(path))[0].lower()
        self._map.pop(stem, None)
