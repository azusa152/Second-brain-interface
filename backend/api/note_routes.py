from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from backend.api.dependencies import get_search_service
from backend.application.search_service import SearchService
from backend.domain.models import (
    NoteLinkItem,
    NoteLinksResponse,
    SuggestLinksRequest,
    SuggestLinksResponse,
)
from backend.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/note", tags=["note"])


@router.post(
    "/suggest-links",
    response_model=SuggestLinksResponse,
    summary="Suggest wikilinks and tags for draft note content",
    responses={
        503: {"description": "Search service or embedding model not ready"},
    },
)
def suggest_links(
    request: SuggestLinksRequest,
    service: Annotated[SearchService, Depends(get_search_service)],
) -> SuggestLinksResponse | JSONResponse:
    """Analyze draft note content and return suggested wikilinks, tags, and related notes.

    Extracts a focused query from the title and first meaningful sentences
    (respecting the embedding model's token limit), runs hybrid search over
    the indexed vault, and returns deduplicated suggestions ready to incorporate
    into a new Obsidian note.
    """
    try:
        return service.suggest_links(request)
    except Exception:
        logger.exception("suggest_links failed for title: %.80s", request.title or "(no title)")
        return JSONResponse(
            status_code=503,
            content={
                "error_code": "SUGGEST_LINKS_UNAVAILABLE",
                "message": "Suggest links service is temporarily unavailable. "
                "Ensure the index has been built.",
            },
        )


@router.get(
    "/{note_path:path}/links",
    response_model=NoteLinksResponse,
    summary="Get backlinks and outgoing links for a note",
    responses={404: {"description": "Note not found in index"}},
)
def get_note_links(
    note_path: str,
    service: Annotated[SearchService, Depends(get_search_service)],
) -> NoteLinksResponse | JSONResponse:
    """Return the link neighbourhood (backlinks + outlinks) for a specific note."""
    if not service.is_note_indexed(note_path):
        return JSONResponse(
            status_code=404,
            content={
                "error_code": "NOTE_NOT_FOUND",
                "message": f"Note not found in index: {note_path}",
            },
        )

    relations = service.get_note_links(note_path)

    outlinks: list[NoteLinkItem] = []
    backlinks: list[NoteLinkItem] = []

    for link in relations:
        title = link["related_path"].rsplit("/", 1)[-1].removesuffix(".md")
        item = NoteLinkItem(
            note_path=link["related_path"],
            note_title=title,
        )
        if link["relationship"] == "outgoing":
            outlinks.append(item)
        else:
            backlinks.append(item)

    return NoteLinksResponse(
        note_path=note_path,
        outlinks=outlinks,
        backlinks=backlinks,
    )
