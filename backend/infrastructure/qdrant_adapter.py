import os
import uuid

from qdrant_client import QdrantClient
from qdrant_client.http.exceptions import UnexpectedResponse
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    Fusion,
    FusionQuery,
    MatchAny,
    MatchValue,
    NamedSparseVector,
    NamedVector,
    PointStruct,
    Prefetch,
    SparseVector as QdrantSparseVector,
    SparseVectorParams,
    VectorParams,
)

from backend.domain.constants import (
    EMBEDDING_DIM,
    QDRANT_COLLECTION_NAME,
    QDRANT_LINK_COLLECTION_NAME,
    SIMILARITY_THRESHOLD,
)
from backend.domain.models import IndexedNoteItem, NoteChunk, SearchResultItem, WikiLink
from backend.infrastructure.embedding import SparseVector
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
        """Create the obsidian_chunks collection with dense + sparse vectors.

        If the collection exists but lacks sparse vector config (pre-Phase 6),
        it is deleted and recreated. A full rebuild is required afterward.
        """
        if self._collection_exists(QDRANT_COLLECTION_NAME):
            if not self._has_sparse_vectors(QDRANT_COLLECTION_NAME):
                logger.warning(
                    "Collection %s lacks sparse vector config — recreating. "
                    "A full rebuild (POST /index/rebuild) is required.",
                    QDRANT_COLLECTION_NAME,
                )
                self.client.delete_collection(QDRANT_COLLECTION_NAME)
            else:
                return

        self.client.create_collection(
            collection_name=QDRANT_COLLECTION_NAME,
            vectors_config={
                "dense": VectorParams(
                    size=EMBEDDING_DIM,
                    distance=Distance.COSINE,
                )
            },
            sparse_vectors_config={
                "sparse": SparseVectorParams(),
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

    def _has_sparse_vectors(self, name: str) -> bool:
        """Check if a collection has sparse vector config."""
        try:
            info = self.client.get_collection(name)
            sparse_config = info.config.params.sparse_vectors
            return sparse_config is not None and len(sparse_config) > 0
        except Exception:
            return False

    def bulk_upsert_chunks(
        self,
        chunks: list[NoteChunk],
        sparse_vectors: list[SparseVector] | None = None,
    ) -> None:
        """Insert or update chunks in bulk with dense and optional sparse vectors."""
        if not chunks:
            return

        points = []
        for i, chunk in enumerate(chunks):
            if chunk.embedding is None:
                logger.warning("Skipping chunk without embedding: %s", chunk.chunk_id)
                continue

            point_id = self._deterministic_id(chunk.chunk_id)
            vectors: dict = {"dense": chunk.embedding}

            if sparse_vectors is not None and i < len(sparse_vectors):
                sv = sparse_vectors[i]
                vectors["sparse"] = QdrantSparseVector(
                    indices=sv.indices,
                    values=sv.values,
                )

            points.append(
                PointStruct(
                    id=point_id,
                    vector=vectors,
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

    def is_note_indexed(self, note_path: str) -> bool:
        """Check if a note has any chunks in the index."""
        result = self.client.scroll(
            collection_name=QDRANT_COLLECTION_NAME,
            scroll_filter=Filter(
                must=[
                    FieldCondition(
                        key="note_path",
                        match=MatchValue(value=note_path),
                    )
                ]
            ),
            limit=1,
            with_payload=False,
            with_vectors=False,
        )
        points, _ = result
        return len(points) > 0

    def get_indexed_note_paths(self) -> set[str]:
        """Return all unique note_paths in the chunks collection."""
        rows = self._scroll_chunk_payloads(["note_path"])
        return {
            r["note_path"]
            for r in rows
            if r.get("note_path")
        }

    def get_indexed_notes(self) -> list[IndexedNoteItem]:
        """Return deduplicated list of indexed notes with path and title."""
        rows = self._scroll_chunk_payloads(["note_path", "note_title"])
        seen: dict[str, str] = {}
        for r in rows:
            path = r.get("note_path", "")
            if path and path not in seen:
                seen[path] = r.get("note_title", "")
        return [
            IndexedNoteItem(note_path=path, note_title=title)
            for path, title in sorted(seen.items())
        ]

    def _scroll_chunk_payloads(self, fields: list[str]) -> list[dict]:
        """Scroll the chunks collection and return payload dicts for given fields."""
        results: list[dict] = []
        offset = None

        while True:
            batch = self.client.scroll(
                collection_name=QDRANT_COLLECTION_NAME,
                limit=100,
                offset=offset,
                with_payload=fields,
                with_vectors=False,
            )
            points, next_offset = batch
            for point in points:
                if point.payload:
                    results.append(point.payload)

            if next_offset is None:
                break
            offset = next_offset

        return results

    def hybrid_search(
        self,
        query_vector: list[float],
        sparse_vector: SparseVector,
        top_k: int,
        threshold: float = SIMILARITY_THRESHOLD,
    ) -> list[SearchResultItem]:
        """Hybrid search combining dense + sparse vectors via RRF fusion.

        Uses Qdrant's Prefetch + Fusion query API to run both dense and sparse
        searches in a single request, then merges results using Reciprocal Rank
        Fusion (RRF).
        """
        results = self.client.query_points(
            collection_name=QDRANT_COLLECTION_NAME,
            prefetch=[
                Prefetch(
                    query=NamedVector(name="dense", vector=query_vector),
                    using="dense",
                    limit=top_k * 2,
                    score_threshold=threshold,
                ),
                Prefetch(
                    query=NamedSparseVector(
                        name="sparse",
                        vector=QdrantSparseVector(
                            indices=sparse_vector.indices,
                            values=sparse_vector.values,
                        ),
                    ),
                    using="sparse",
                    limit=top_k * 2,
                ),
            ],
            query=FusionQuery(fusion=Fusion.RRF),
            limit=top_k,
            with_payload=True,
        )

        items: list[SearchResultItem] = []
        for point in results.points:
            payload = point.payload or {}
            items.append(
                SearchResultItem(
                    chunk_id=payload.get("chunk_id", ""),
                    note_path=payload.get("note_path", ""),
                    note_title=payload.get("note_title", ""),
                    content=payload.get("content", ""),
                    score=point.score if point.score is not None else 0.0,
                    heading_context=payload.get("heading_context"),
                )
            )

        return items

    def get_related_notes_batch(
        self, note_paths: set[str]
    ) -> dict[str, list[dict[str, str]]]:
        """Batch-fetch outgoing links and backlinks for a set of note paths.

        Returns a dict keyed by note_path, each value is a list of dicts with
        keys: related_path, relationship ("outgoing" or "backlink").
        Uses two scroll queries (outgoing + backlinks) to avoid N+1.
        """
        if not note_paths:
            return {}

        path_list = list(note_paths)
        relations: dict[str, list[dict[str, str]]] = {p: [] for p in note_paths}

        # 1. Outgoing links: source_path in note_paths
        self._scroll_links(
            field="source_path",
            values=path_list,
            relations=relations,
            key_field="source_path",
            related_field="resolved_target_path",
            relationship="outgoing",
        )

        # 2. Backlinks: resolved_target_path in note_paths
        self._scroll_links(
            field="resolved_target_path",
            values=path_list,
            relations=relations,
            key_field="resolved_target_path",
            related_field="source_path",
            relationship="backlink",
        )

        return relations

    def _scroll_links(
        self,
        field: str,
        values: list[str],
        relations: dict[str, list[dict[str, str]]],
        key_field: str,
        related_field: str,
        relationship: str,
    ) -> None:
        """Scroll the links collection with a MatchAny filter and populate relations."""
        offset = None
        while True:
            result = self.client.scroll(
                collection_name=QDRANT_LINK_COLLECTION_NAME,
                scroll_filter=Filter(
                    must=[
                        FieldCondition(
                            key=field,
                            match=MatchAny(any=values),
                        )
                    ]
                ),
                limit=100,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            points, next_offset = result
            for point in points:
                payload = point.payload or {}
                key = payload.get(key_field, "")
                related = payload.get(related_field)
                if key in relations and related:
                    relations[key].append(
                        {"related_path": related, "relationship": relationship}
                    )

            if next_offset is None:
                break
            offset = next_offset

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
