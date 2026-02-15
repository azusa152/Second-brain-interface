from fastapi import APIRouter, HTTPException, Query

from backend.api.dependencies import get_index_service
from backend.domain.models import (
    IndexedNotesResponse,
    IndexRebuildResponse,
    IndexStatus,
    WatcherEventItem,
    WatcherEventsResponse,
)

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


@router.get(
    "/events",
    response_model=WatcherEventsResponse,
    summary="Get recent file watcher events",
)
def get_watcher_events(
    limit: int = Query(default=50, ge=1, le=100),
) -> WatcherEventsResponse:
    """Return the most recent file watcher events, newest first."""
    service = get_index_service()
    events = service.get_recent_events(limit)
    return WatcherEventsResponse(
        events=[
            WatcherEventItem(
                event_type=e.event_type,
                file_path=e.file_path,
                timestamp=e.timestamp,
                dest_path=e.dest_path,
            )
            for e in events
        ],
        total=len(events),
    )


@router.get(
    "/notes",
    response_model=IndexedNotesResponse,
    summary="List all indexed notes",
)
def get_indexed_notes() -> IndexedNotesResponse:
    """Return all indexed notes with path and title."""
    service = get_index_service()
    notes = service.get_indexed_notes()
    return IndexedNotesResponse(notes=notes, total=len(notes))
