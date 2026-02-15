import time
from collections import Counter

from backend.domain.constants import SIMILARITY_THRESHOLD
from backend.domain.models import (
    RelatedNote,
    SearchRequest,
    SearchResponse,
    SearchResultItem,
)
from backend.infrastructure.embedding import EmbeddingService
from backend.infrastructure.qdrant_adapter import QdrantAdapter
from backend.logging_config import get_logger

logger = get_logger(__name__)


class SearchService:
    """Orchestrate semantic search: embed query → vector search → rank."""

    def __init__(
        self,
        embedder: EmbeddingService,
        qdrant_adapter: QdrantAdapter,
    ) -> None:
        self._embedder = embedder
        self._qdrant = qdrant_adapter

    def search(self, request: SearchRequest) -> SearchResponse:
        """Execute a semantic search over indexed chunks."""
        start = time.time()

        threshold = (
            request.threshold if request.threshold is not None else SIMILARITY_THRESHOLD
        )

        # 1. Embed the query
        query_vector = self._embedder.embed_text(request.query)

        # 2. Vector search with threshold filtering (Qdrant handles score_threshold)
        results = self._qdrant.vector_search(
            query_vector=query_vector,
            top_k=request.top_k,
            threshold=threshold,
        )

        # 3. Graph enrichment: fetch related notes via wikilinks
        related_notes: list[RelatedNote] = []
        if request.include_related and results:
            related_notes = self._enrich_with_related_notes(results)

        elapsed_ms = (time.time() - start) * 1000

        logger.info(
            "Search '%s': %d results, %d related in %.1fms",
            request.query,
            len(results),
            len(related_notes),
            elapsed_ms,
        )

        return SearchResponse(
            query=request.query,
            results=results,
            related_notes=related_notes,
            # Post-filtering count; true pre-limit count deferred to Phase 6 (hybrid search)
            total_hits=len(results),
            search_time_ms=round(elapsed_ms, 1),
        )

    def _enrich_with_related_notes(
        self, results: list[SearchResultItem],
    ) -> list[RelatedNote]:
        """Fetch outgoing links and backlinks for all result note paths (batch)."""
        result_paths = {r.note_path for r in results}

        # Single batch query for all links (no N+1)
        relations = self._qdrant.get_related_notes_batch(result_paths)

        # Aggregate: count links per (related_path, relationship), excluding self-links
        # and paths already in the search results
        counter: Counter[tuple[str, str]] = Counter()
        for note_path, link_list in relations.items():
            for link in link_list:
                related_path = link["related_path"]
                relationship = link["relationship"]
                if related_path not in result_paths:
                    counter[(related_path, relationship)] += 1

        # Build RelatedNote list, sorted by link_count descending
        related_notes: list[RelatedNote] = []
        for (related_path, relationship), count in counter.most_common():
            # Derive title from path (filename without extension)
            title = related_path.rsplit("/", 1)[-1].removesuffix(".md")
            related_notes.append(
                RelatedNote(
                    note_path=related_path,
                    note_title=title,
                    relationship=relationship,
                    link_count=count,
                )
            )

        return related_notes

    def get_note_links(self, note_path: str) -> list[dict[str, str]]:
        """Return all outgoing links and backlinks for a single note."""
        relations = self._qdrant.get_related_notes_batch({note_path})
        return relations.get(note_path, [])

    def is_note_indexed(self, note_path: str) -> bool:
        """Check if a note exists in the index."""
        return self._qdrant.is_note_indexed(note_path)
