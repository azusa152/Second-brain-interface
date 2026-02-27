from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from backend.api.dependencies import get_search_service
from backend.application.search_service import SearchService
from backend.domain.models import NoteLinkItem, NoteLinksResponse

router = APIRouter(prefix="/note", tags=["note"])


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
