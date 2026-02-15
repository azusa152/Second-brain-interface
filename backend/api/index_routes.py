from fastapi import APIRouter, HTTPException

from backend.api.dependencies import get_index_service
from backend.domain.models import IndexRebuildResponse, IndexStatus

router = APIRouter(prefix="/index", tags=["index"])


@router.post(
    "/rebuild",
    response_model=IndexRebuildResponse,
    summary="Trigger full vault re-index",
    responses={409: {"description": "Re-index already in progress"}},
)
def rebuild_index() -> IndexRebuildResponse:
    """Force a full re-index of the vault (manual trigger)."""
    service = get_index_service()
    result = service.rebuild_index()

    if result is None:
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "REINDEX_IN_PROGRESS",
                "detail": "A re-index operation is already running.",
            },
        )

    return result


@router.get(
    "/status",
    response_model=IndexStatus,
    summary="Get index health and statistics",
)
def get_index_status() -> IndexStatus:
    """Return current index statistics."""
    service = get_index_service()
    return service.get_status()
