import os
import uuid

from qdrant_client import QdrantClient
from qdrant_client.http.exceptions import UnexpectedResponse
from qdrant_client.models import (
    DatetimeRange,
    Distance,
    FieldCondition,
    Filter,
    Fusion,
    FusionQuery,
    MatchAny,
    MatchValue,
    PayloadSchemaType,
    PointStruct,
    Prefetch,
    SparseVectorParams,
    VectorParams,
)
from qdrant_client.models import (
    SparseVector as QdrantSparseVector,
)

from backend.domain.constants import (
    EMBEDDING_DIM,
    QDRANT_COLLECTION_NAME,
    QDRANT_LINK_COLLECTION_NAME,
    SIMILARITY_THRESHOLD,
)
from backend.domain.models import (
    IndexedNoteItem,
    NoteChunk,
    SearchFilter,
    SearchResultItem,
    WikiLink,
)
from backend.infrastructure.embedding import SparseVector
from backend.logging_config import get_logger

logger = get_logger(__name__)

_DEFAULT_URL = "http://localhost:6333"


class QdrantAdapter:
    """All interactions with Qdrant vector database."""

    def __init__(self, url: str | None = None) -> None:
        resolved_url = url or os.getenv("QDRANT_URL", _DEFAULT_URL)
        self.client = QdrantClient(url=resolved_url)
        self._legacy_prefixes_cache: bool | None = None

    def ensure_collections(self) -> None:
        """Create collections if they don't exist."""
        self._ensure_chunks_collection()
        self._ensure_links_collection()
        self._ensure_payload_indexes()

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

    def _ensure_payload_indexes(self) -> None:
        """Create payload indexes used by search metadata filters.

        Qdrant returns HTTP 409 when the index already exists.  We treat that
        as idempotent success and re-raise anything else.
        """
        index_fields: dict[str, PayloadSchemaType] = {
            "tags": PayloadSchemaType.KEYWORD,
            "note_path": PayloadSchemaType.KEYWORD,
            "note_path_prefixes": PayloadSchemaType.KEYWORD,
            "last_modified": PayloadSchemaType.DATETIME,
        }
        for field_name, field_schema in index_fields.items():
            try:
                self.client.create_payload_index(
                    collection_name=QDRANT_COLLECTION_NAME,
                    field_name=field_name,
                    field_schema=field_schema,
                )
            except UnexpectedResponse as err:
                if err.status_code == 409:
                    logger.debug("Payload index already exists: %s", field_name)
                    continue
                logger.exception("Failed to create payload index: %s", field_name)
                raise

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
                        "note_path_prefixes": self._build_note_path_prefixes(chunk.note_path),
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
        return {r["note_path"] for r in rows if r.get("note_path")}

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

    def get_fuzzy_vocabulary_sources(self) -> tuple[list[str], list[str]]:
        """Return note titles and heading contexts used for fuzzy vocabulary."""
        rows = self._scroll_chunk_payloads(["note_title", "heading_context"])
        titles = [r["note_title"] for r in rows if r.get("note_title")]
        headings = [r["heading_context"] for r in rows if r.get("heading_context")]
        return titles, headings

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
        query_filter: Filter | None = None,
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
                    query=query_vector,
                    using="dense",
                    limit=top_k * 2,
                    score_threshold=threshold,
                    filter=query_filter,
                ),
                Prefetch(
                    query=QdrantSparseVector(
                        indices=sparse_vector.indices,
                        values=sparse_vector.values,
                    ),
                    using="sparse",
                    limit=top_k * 2,
                    filter=query_filter,
                ),
            ],
            query=FusionQuery(fusion=Fusion.RRF),
            limit=top_k,
            with_payload=True,
            query_filter=query_filter,
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
                    tags=payload.get("tags") or [],
                )
            )

        return items

    def has_legacy_chunks_without_prefixes(self) -> bool:
        """Check if any indexed chunk in a subfolder is missing note_path_prefixes.

        The result is cached after the first check.  A successful rebuild
        clears the cache via :meth:`mark_prefixes_current`.
        """
        if self._legacy_prefixes_cache is not None:
            return self._legacy_prefixes_cache

        self._legacy_prefixes_cache = self._detect_legacy_prefixes()
        return self._legacy_prefixes_cache

    def mark_prefixes_current(self) -> None:
        """Clear the legacy-prefix cache after a successful rebuild."""
        self._legacy_prefixes_cache = False

    def _detect_legacy_prefixes(self) -> bool:
        """Scroll all chunks to find any subfolder note missing note_path_prefixes."""
        offset = None
        try:
            while True:
                points, next_offset = self.client.scroll(
                    collection_name=QDRANT_COLLECTION_NAME,
                    limit=256,
                    offset=offset,
                    with_payload=["note_path", "note_path_prefixes"],
                    with_vectors=False,
                )
                for point in points:
                    payload = point.payload or {}
                    note_path = payload.get("note_path", "")
                    prefixes = payload.get("note_path_prefixes")
                    if "/" in note_path and not prefixes:
                        return True
                if next_offset is None:
                    break
                offset = next_offset
        except Exception:
            logger.warning(
                "legacy_prefix_check_failed — assuming legacy data may exist; "
                "run POST /index/rebuild to resolve"
            )
            return True

        return False

    @staticmethod
    def build_query_filter(search_filter: SearchFilter) -> Filter | None:
        """Convert SearchFilter model into Qdrant payload filter."""
        must_conditions: list[FieldCondition] = []
        must_not_conditions: list[FieldCondition] = []

        if search_filter.tags:
            must_conditions.append(
                FieldCondition(
                    key="tags",
                    match=MatchAny(any=search_filter.tags),
                )
            )

        if search_filter.exclude_tags:
            must_not_conditions.append(
                FieldCondition(
                    key="tags",
                    match=MatchAny(any=search_filter.exclude_tags),
                )
            )

        if search_filter.path_prefix:
            normalized_prefix = QdrantAdapter._normalize_path_prefix(search_filter.path_prefix)
            if normalized_prefix:
                must_conditions.append(
                    FieldCondition(
                        key="note_path_prefixes",
                        match=MatchAny(any=[normalized_prefix]),
                    )
                )

        if search_filter.modified_after is not None or search_filter.modified_before is not None:
            must_conditions.append(
                FieldCondition(
                    key="last_modified",
                    range=DatetimeRange(
                        gte=search_filter.modified_after,
                        lte=search_filter.modified_before,
                    ),
                )
            )

        if not must_conditions and not must_not_conditions:
            return None

        return Filter(
            must=must_conditions or None,
            must_not=must_not_conditions or None,
        )

    @staticmethod
    def _normalize_path_prefix(path_prefix: str) -> str:
        """Normalize input prefix into vault-relative slash-suffixed format."""
        normalized = path_prefix.strip().replace("\\", "/").lstrip("/")
        if normalized and not normalized.endswith("/"):
            normalized = f"{normalized}/"
        return normalized

    @staticmethod
    def _build_note_path_prefixes(note_path: str) -> list[str]:
        """Build directory-prefix tokens used for strict path_prefix filtering."""
        normalized_path = note_path.strip().replace("\\", "/").lstrip("/")
        if "/" not in normalized_path:
            return []

        parent_path = normalized_path.rsplit("/", 1)[0]
        prefixes: list[str] = []
        current = ""
        for part in parent_path.split("/"):
            current = f"{current}{part}/" if current else f"{part}/"
            prefixes.append(current)
        return prefixes

    def get_related_notes_batch(self, note_paths: set[str]) -> dict[str, list[dict[str, str]]]:
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
                    relations[key].append({"related_path": related, "relationship": relationship})

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
