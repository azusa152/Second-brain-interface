from fastapi import APIRouter, HTTPException

from backend.api.dependencies import get_search_service
from backend.domain.models import SearchRequest, SearchResponse
from backend.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/search", tags=["search"])


@router.post(
    "",
    response_model=SearchResponse,
    summary="Semantic search over Obsidian vault",
    responses={
        503: {"description": "Index or embedding service not ready"},
    },
)
def search_notes(request: SearchRequest) -> SearchResponse:
    """Accept a natural language query and return ranked results."""
    service = get_search_service()

    try:
        return service.search(request)
    except Exception:
        logger.exception("Search failed for query: %s", request.query)
        raise HTTPException(
            status_code=503,
            detail={
                "error_code": "SEARCH_UNAVAILABLE",
                "detail": "Search service is temporarily unavailable. "
                "Ensure the index has been built.",
            },
        )
