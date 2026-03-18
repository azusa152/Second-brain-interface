from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from backend.api.dependencies import get_search_service
from backend.application.search_service import SearchService
from backend.domain.exceptions import IndexRebuildRequiredError
from backend.domain.models import SearchRequest, SearchResponse
from backend.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/search", tags=["search"])


@router.post(
    "",
    response_model=SearchResponse,
    summary="Semantic search over Obsidian vault",
    responses={
        409: {"description": "Index rebuild required for the requested filter"},
        503: {"description": "Index or embedding service not ready"},
    },
)
def search_notes(
    request: SearchRequest,
    service: Annotated[SearchService, Depends(get_search_service)],
) -> SearchResponse | JSONResponse:
    """Accept a natural language query and return ranked results."""
    try:
        return service.search(request)
    except IndexRebuildRequiredError as err:
        logger.warning("Rebuild required: %s", err)
        return JSONResponse(
            status_code=409,
            content={
                "error_code": "INDEX_REBUILD_REQUIRED",
                "message": str(err),
            },
        )
    except Exception:
        logger.exception("Search failed for query: %s", request.query)
        return JSONResponse(
            status_code=503,
            content={
                "error_code": "SEARCH_UNAVAILABLE",
                "message": "Search service is temporarily unavailable. "
                "Ensure the index has been built.",
            },
        )
