import time

from backend.domain.constants import SIMILARITY_THRESHOLD
from backend.domain.models import SearchRequest, SearchResponse
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

        elapsed_ms = (time.time() - start) * 1000

        logger.info(
            "Search '%s': %d results in %.1fms",
            request.query,
            len(results),
            elapsed_ms,
        )

        return SearchResponse(
            query=request.query,
            results=results,
            related_notes=[],  # Phase 4 will populate this
            # Post-filtering count; true pre-limit count deferred to Phase 6 (hybrid search)
            total_hits=len(results),
            search_time_ms=round(elapsed_ms, 1),
        )
