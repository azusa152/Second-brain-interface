import os
import uuid

from qdrant_client import QdrantClient
from qdrant_client.http.exceptions import UnexpectedResponse
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

from backend.domain.constants import (
    EMBEDDING_DIM,
    QDRANT_COLLECTION_NAME,
    QDRANT_LINK_COLLECTION_NAME,
)
from backend.domain.models import NoteChunk, WikiLink
from backend.logging_config import get_logger

logger = get_logger(__name__)

_DEFAULT_URL = "http://localhost:6333"


class QdrantAdapter:
    """All interactions with Qdrant vector database."""

    def __init__(self, url: str | None = None) -> None:
        resolved_url = url or os.getenv("QDRANT_URL", _DEFAULT_URL)
        self.client = QdrantClient(url=resolved_url)

    def ensure_collections(self) -> None:
        """Create collections if they don't exist."""
        self._ensure_chunks_collection()
        self._ensure_links_collection()

    def _ensure_chunks_collection(self) -> None:
        """Create the obsidian_chunks collection."""
        if self._collection_exists(QDRANT_COLLECTION_NAME):
            return

        self.client.create_collection(
            collection_name=QDRANT_COLLECTION_NAME,
            vectors_config={
                "dense": VectorParams(
                    size=EMBEDDING_DIM,
                    distance=Distance.COSINE,
                )
            },
        )
        logger.info("Created collection: %s", QDRANT_COLLECTION_NAME)

    def _ensure_links_collection(self) -> None:
        """Create the obsidian_links collection (no vectors, payload only)."""
        if self._collection_exists(QDRANT_LINK_COLLECTION_NAME):
            return

        self.client.create_collection(
            collection_name=QDRANT_LINK_COLLECTION_NAME,
            vectors_config={},
        )
        logger.info("Created collection: %s", QDRANT_LINK_COLLECTION_NAME)

    def _collection_exists(self, name: str) -> bool:
        """Check if a collection exists."""
        try:
            self.client.get_collection(name)
            return True
        except UnexpectedResponse:
            return False

    def bulk_upsert_chunks(self, chunks: list[NoteChunk]) -> None:
        """Insert or update chunks in bulk."""
        if not chunks:
            return

        points = []
        for chunk in chunks:
            if chunk.embedding is None:
                logger.warning("Skipping chunk without embedding: %s", chunk.chunk_id)
                continue

            point_id = self._deterministic_id(chunk.chunk_id)
            points.append(
                PointStruct(
                    id=point_id,
                    vector={"dense": chunk.embedding},
                    payload={
                        "chunk_id": chunk.chunk_id,
                        "note_path": chunk.note_path,
                        "note_title": chunk.note_title,
                        "content": chunk.content,
                        "chunk_index": chunk.chunk_index,
                        "heading_context": chunk.heading_context,
                        "tags": chunk.tags,
                        "last_modified": chunk.last_modified.isoformat()
                        if chunk.last_modified
                        else None,
                    },
                )
            )

        if points:
            self.client.upsert(
                collection_name=QDRANT_COLLECTION_NAME,
                points=points,
            )
            logger.info("Upserted %d chunks", len(points))

    def bulk_upsert_links(self, links: list[WikiLink]) -> None:
        """Insert or update wikilinks in bulk."""
        if not links:
            return

        points = []
        for link in links:
            link_key = f"{link.source_path}::{link.link_text}"
            point_id = self._deterministic_id(link_key)
            points.append(
                PointStruct(
                    id=point_id,
                    vector={},
                    payload={
                        "source_path": link.source_path,
                        "link_text": link.link_text,
                        "resolved_target_path": link.resolved_target_path,
                        "link_type": link.link_type,
                    },
                )
            )

        self.client.upsert(
            collection_name=QDRANT_LINK_COLLECTION_NAME,
            points=points,
        )
        logger.info("Upserted %d links", len(points))

    def delete_by_note_path(self, note_path: str) -> None:
        """Remove all chunks for a given note."""
        self.client.delete(
            collection_name=QDRANT_COLLECTION_NAME,
            points_selector=Filter(
                must=[
                    FieldCondition(
                        key="note_path",
                        match=MatchValue(value=note_path),
                    )
                ]
            ),
        )
        logger.info("Deleted chunks for note: %s", note_path)

    def delete_links_by_source(self, source_path: str) -> None:
        """Remove all outgoing links for a given note."""
        self.client.delete(
            collection_name=QDRANT_LINK_COLLECTION_NAME,
            points_selector=Filter(
                must=[
                    FieldCondition(
                        key="source_path",
                        match=MatchValue(value=source_path),
                    )
                ]
            ),
        )

    def get_chunks_count(self) -> int:
        """Return total number of chunks in the index."""
        try:
            info = self.client.get_collection(QDRANT_COLLECTION_NAME)
            return info.points_count or 0
        except Exception:
            return 0

    def get_indexed_note_paths(self) -> set[str]:
        """Return all unique note_paths in the chunks collection."""
        note_paths: set[str] = set()
        offset = None

        while True:
            result = self.client.scroll(
                collection_name=QDRANT_COLLECTION_NAME,
                limit=100,
                offset=offset,
                with_payload=["note_path"],
                with_vectors=False,
            )
            points, next_offset = result
            for point in points:
                if point.payload and "note_path" in point.payload:
                    note_paths.add(point.payload["note_path"])

            if next_offset is None:
                break
            offset = next_offset

        return note_paths

    def is_healthy(self) -> bool:
        """Check if Qdrant is reachable."""
        try:
            self.client.get_collections()
            return True
        except Exception:
            return False

    @staticmethod
    def _deterministic_id(key: str) -> str:
        """Generate a deterministic UUID from a string key."""
        return str(uuid.uuid5(uuid.NAMESPACE_URL, key))
