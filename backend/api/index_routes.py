from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from backend.api.dependencies import get_index_service
from backend.application.index_service import IndexService
from backend.domain.exceptions import RebuildInProgressError
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
def rebuild_index(
    service: Annotated[IndexService, Depends(get_index_service)],
) -> IndexRebuildResponse | JSONResponse:
    """Force a full re-index of the vault (manual trigger)."""
    try:
        return service.rebuild_index()
    except RebuildInProgressError:
        return JSONResponse(
            status_code=409,
            content={
                "error_code": "REBUILD_IN_PROGRESS",
                "message": "A re-index operation is already running.",
            },
        )


@router.get(
    "/status",
    response_model=IndexStatus,
    summary="Get index health and statistics",
)
def get_index_status(
    service: Annotated[IndexService, Depends(get_index_service)],
) -> IndexStatus:
    """Return current index statistics."""
    return service.get_status()


@router.get(
    "/events",
    response_model=WatcherEventsResponse,
    summary="Get recent file watcher events",
)
def get_watcher_events(
    service: Annotated[IndexService, Depends(get_index_service)],
    limit: int = Query(default=50, ge=1, le=100),
) -> WatcherEventsResponse:
    """Return the most recent file watcher events, newest first."""
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
def get_indexed_notes(
    service: Annotated[IndexService, Depends(get_index_service)],
) -> IndexedNotesResponse:
    """Return all indexed notes with path and title."""
    notes = service.get_indexed_notes()
    return IndexedNotesResponse(notes=notes, total=len(notes))
