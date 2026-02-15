import os
import time
from datetime import datetime, timezone

from backend.domain.constants import WATCH_EXTENSIONS
from backend.domain.models import IndexRebuildResponse, IndexStatus
from backend.infrastructure.chunker import Chunker
from backend.infrastructure.embedding import EmbeddingService
from backend.infrastructure.markdown_parser import MarkdownParser
from backend.infrastructure.qdrant_adapter import QdrantAdapter
from backend.infrastructure.vault_file_map import VaultFileMap
from backend.logging_config import get_logger

logger = get_logger(__name__)


class IndexService:
    """Orchestrate the indexing pipeline."""

    def __init__(
        self,
        vault_path: str,
        parser: MarkdownParser,
        chunker: Chunker,
        embedder: EmbeddingService,
        qdrant_adapter: QdrantAdapter,
        vault_file_map: VaultFileMap,
    ) -> None:
        self._vault_path = vault_path
        self._parser = parser
        self._chunker = chunker
        self._embedder = embedder
        self._qdrant = qdrant_adapter
        self._file_map = vault_file_map
        self._last_indexed: datetime | None = None
        self._rebuilding = False

    def initialize(self) -> None:
        """Scan the vault file map and ensure Qdrant collections exist."""
        self._file_map.scan()
        self._qdrant.ensure_collections()

    def rebuild_index(self) -> IndexRebuildResponse | None:
        """Full re-index of all .md files in vault. Returns None if already running."""
        if self._rebuilding:
            return None

        self._rebuilding = True
        start_time = time.time()
        notes_indexed = 0
        chunks_created = 0

        try:
            self._file_map.scan()
            self._qdrant.ensure_collections()

            md_files = self._collect_md_files()

            for rel_path in md_files:
                abs_path = os.path.join(self._vault_path, rel_path)
                # Delete stale chunks + links before re-indexing each note
                self._qdrant.delete_by_note_path(rel_path)
                self._qdrant.delete_links_by_source(rel_path)
                n_chunks = self._index_file(abs_path, rel_path)
                notes_indexed += 1
                chunks_created += n_chunks

            elapsed = time.time() - start_time
            self._last_indexed = datetime.now(tz=timezone.utc)

            logger.info(
                "Rebuild complete: %d notes, %d chunks in %.1fs",
                notes_indexed,
                chunks_created,
                elapsed,
            )
            return IndexRebuildResponse(
                status="success",
                notes_indexed=notes_indexed,
                chunks_created=chunks_created,
                time_taken_seconds=round(elapsed, 1),
            )
        finally:
            self._rebuilding = False

    def index_single_note(self, note_path: str) -> None:
        """Index or update a single note."""
        abs_path = os.path.join(self._vault_path, note_path)
        if not os.path.exists(abs_path):
            logger.warning("File not found, skipping: %s", note_path)
            return

        # Delete old chunks + links for this note
        self._qdrant.delete_by_note_path(note_path)
        self._qdrant.delete_links_by_source(note_path)

        self._index_file(abs_path, note_path)

    def delete_note(self, note_path: str) -> None:
        """Remove a note from the index."""
        self._qdrant.delete_by_note_path(note_path)
        self._qdrant.delete_links_by_source(note_path)
        self._file_map.remove_file(note_path)
        logger.info("Deleted note from index: %s", note_path)

    def rename_note(self, old_path: str, new_path: str) -> None:
        """Handle file rename/move operation."""
        self._qdrant.delete_by_note_path(old_path)
        self._qdrant.delete_links_by_source(old_path)
        self._file_map.update_file(old_path, new_path)
        self.index_single_note(new_path)
        logger.info("Renamed note in index: %s -> %s", old_path, new_path)

    def get_status(self) -> IndexStatus:
        """Return current index statistics."""
        chunks_count = self._qdrant.get_chunks_count()
        note_paths = self._qdrant.get_indexed_note_paths()

        return IndexStatus(
            indexed_notes=len(note_paths),
            indexed_chunks=chunks_count,
            last_indexed=self._last_indexed,
            watcher_running=False,  # Phase 5 will update this
            qdrant_healthy=self._qdrant.is_healthy(),
        )

    def _collect_md_files(self) -> list[str]:
        """Walk vault and collect all .md file relative paths."""
        md_files: list[str] = []
        for root, _dirs, files in os.walk(self._vault_path):
            for filename in files:
                if not any(filename.endswith(ext) for ext in WATCH_EXTENSIONS):
                    continue
                abs_path = os.path.join(root, filename)
                rel_path = os.path.relpath(abs_path, self._vault_path)
                md_files.append(rel_path)
        return sorted(md_files)

    def _index_file(self, abs_path: str, rel_path: str) -> int:
        """Parse, chunk, embed, and store a single file. Returns chunk count."""
        content = self._read_file(abs_path)
        if content is None:
            return 0

        stat = os.stat(abs_path)
        last_modified = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)

        metadata, links = self._parser.parse(rel_path, content, last_modified)

        body = self._parser.get_body(content)
        chunks = self._chunker.chunk(rel_path, body)

        if not chunks:
            return 0

        # Enrich chunks with note-level metadata for Qdrant payload
        for chunk in chunks:
            chunk.note_title = metadata.title
            chunk.tags = metadata.tags
            chunk.last_modified = metadata.last_modified

        texts = [c.content for c in chunks]
        embeddings = self._embedder.embed_batch(texts)

        for chunk, embedding in zip(chunks, embeddings):
            chunk.embedding = embedding

        self._qdrant.bulk_upsert_chunks(chunks)
        self._qdrant.bulk_upsert_links(links)

        return len(chunks)

    @staticmethod
    def _read_file(path: str) -> str | None:
        """Read file content, returning None on error."""
        try:
            with open(path, encoding="utf-8") as f:
                return f.read()
        except OSError:
            logger.warning("Failed to read file: %s", path)
            return None
