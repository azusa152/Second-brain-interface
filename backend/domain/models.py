from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from backend.domain.constants import MAX_TOP_K, TOP_K_DEFAULT


# --- Core Entities ---


class NoteMetadata(BaseModel):
    """Metadata extracted from an Obsidian note."""

    file_path: str
    title: str
    last_modified: datetime
    frontmatter: dict[str, Any]
    tags: list[str] = []
    word_count: int


class NoteChunk(BaseModel):
    """A segment of a note for indexing."""

    chunk_id: str
    note_path: str
    content: str
    chunk_index: int
    heading_context: str | None = None
    note_title: str = ""
    tags: list[str] = []
    last_modified: datetime | None = None
    embedding: list[float] | None = None


class WikiLink(BaseModel):
    """A wikilink relationship between two notes."""

    source_path: str
    link_text: str
    resolved_target_path: str | None = None
    link_type: str = "wikilink"


# --- Search Models ---


class SearchRequest(BaseModel):
    """Request body for POST /search."""

    query: str
    top_k: int = Field(default=TOP_K_DEFAULT, ge=1, le=MAX_TOP_K)
    include_related: bool = True
    threshold: float | None = None


class SearchResultItem(BaseModel):
    """A single search result."""

    chunk_id: str
    note_path: str
    note_title: str
    content: str
    score: float
    heading_context: str | None = None
    highlights: list[str] = []


class RelatedNote(BaseModel):
    """A note related to search results via wikilinks."""

    note_path: str
    note_title: str
    relationship: str
    link_count: int


class SearchResponse(BaseModel):
    """Response from POST /search."""

    query: str
    results: list[SearchResultItem]
    related_notes: list[RelatedNote]
    total_hits: int = Field(
        description="Number of results returned after top-k and threshold filtering. "
        "Does not represent the total number of matches in the index."
    )
    # TODO: Phase 6 — implement true total_hits via count query when hybrid search is added.
    search_time_ms: float


# --- Index Rebuild ---


class IndexRebuildResponse(BaseModel):
    """Response from POST /index/rebuild."""

    status: str
    notes_indexed: int
    chunks_created: int
    time_taken_seconds: float


# --- Health ---


class HealthResponse(BaseModel):
    """Response from GET /health."""

    status: str
    timestamp: str


# --- Index Status ---


class IndexStatus(BaseModel):
    """Response from GET /index/status."""

    indexed_notes: int
    indexed_chunks: int
    last_indexed: datetime | None = None
    watcher_running: bool
    qdrant_healthy: bool
