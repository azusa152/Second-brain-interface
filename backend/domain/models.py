from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.domain.constants import (
    AUGMENT_TOP_K_DEFAULT,
    MAX_TOP_K,
    SUGGEST_LINKS_MAX_SUGGESTIONS_DEFAULT,
    TOP_K_DEFAULT,
)

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
    tags: list[str] = []


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
    search_time_ms: float
    did_you_mean: str | None = Field(
        default=None,
        description="Suggested corrected query when fuzzy matching detects likely typos.",
    )


# --- Note Links ---


class NoteLinkItem(BaseModel):
    """A single link relationship for a note."""

    note_path: str
    note_title: str


class NoteLinksResponse(BaseModel):
    """Response from GET /note/{path}/links."""

    note_path: str
    outlinks: list[NoteLinkItem]
    backlinks: list[NoteLinkItem]


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


# --- Config ---


class VaultConfig(BaseModel):
    """Response from GET /config/vault."""

    vault_name: str
    is_configured: bool
    message: str | None = None


# --- Index Status ---


class IndexStatus(BaseModel):
    """Response from GET /index/status."""

    indexed_notes: int
    indexed_chunks: int
    last_indexed: datetime | None = None
    watcher_running: bool
    qdrant_healthy: bool
    watcher_mode: Literal["polling", "event"] = "event"
    last_scheduled_rebuild: datetime | None = None


# --- Watcher Events ---


class WatcherEventItem(BaseModel):
    """A single watcher event for API responses."""

    event_type: str
    file_path: str
    timestamp: datetime
    dest_path: str | None = None


class WatcherEventsResponse(BaseModel):
    """Response from GET /index/events."""

    events: list[WatcherEventItem]
    total: int


# --- Indexed Notes ---


class IndexedNoteItem(BaseModel):
    """A single indexed note for API responses."""

    note_path: str
    note_title: str


class IndexedNotesResponse(BaseModel):
    """Response from GET /index/notes."""

    notes: list[IndexedNoteItem]
    total: int


# --- Suggest Links ---


class SuggestLinksRequest(BaseModel):
    """Request body for POST /note/suggest-links."""

    content: str = Field(min_length=1, description="Draft note content in markdown")
    title: str | None = Field(None, description="Optional note title for better semantic matching")
    max_suggestions: int = Field(
        default=SUGGEST_LINKS_MAX_SUGGESTIONS_DEFAULT,
        ge=1,
        le=MAX_TOP_K,
        description="Maximum number of wikilink suggestions to return",
    )


class SuggestedLink(BaseModel):
    """A single wikilink suggestion for a draft note."""

    display_text: str = Field(description="Note title to use as [[wikilink]] text")
    target_path: str = Field(description="Vault-relative path of the suggested note")
    score: float = Field(description="Relevance score from hybrid search (0-1)")


class SuggestLinksResponse(BaseModel):
    """Response from POST /note/suggest-links."""

    suggested_wikilinks: list[SuggestedLink]
    suggested_tags: list[str]
    related_notes: list[NoteLinkItem]


# --- Intent Classification ---


class IntentRequest(BaseModel):
    """Request body for POST /intent/classify."""

    message: str = Field(min_length=1)


class IntentClassification(BaseModel):
    """Result of intent classification."""

    requires_personal_context: bool
    confidence: float
    triggered_signals: list[str]
    suggested_query: str | None


# --- Debug Tokenization ---


class TokenizeRequest(BaseModel):
    """Request body for POST /debug/tokenize."""

    text: str = Field(min_length=1)


class TokenizeSegmentItem(BaseModel):
    """A segmented text span used during debug tokenization."""

    text: str
    is_cjk: bool
    language: Literal["japanese", "chinese", "other"]


class TokenizeTokenItem(BaseModel):
    """A token-level debug record from the tokenizer pipeline."""

    surface: str
    pos: str
    kept: bool
    language: Literal["japanese", "chinese"]
    normalized: str | None = None


class TokenizeResponse(BaseModel):
    """Response from POST /debug/tokenize."""

    original: str
    normalized: str
    sanitized: str
    detected_language: Literal["japanese", "chinese", "other"]
    segments: list[TokenizeSegmentItem]
    sparse_output: str
    tokens: list[TokenizeTokenItem]


# --- Context Augmentation ---


class AugmentRequest(BaseModel):
    """Request body for POST /augment."""

    message: str = Field(min_length=1)
    top_k: int = Field(default=AUGMENT_TOP_K_DEFAULT, ge=1, le=MAX_TOP_K)
    include_sources: bool = True


class SourceCitation(BaseModel):
    """A single source note cited in the augmented context."""

    note_path: str
    note_title: str
    heading_context: str | None
    score: float


class ContextBlock(BaseModel):
    """Formatted context retrieved from the vault, ready for LLM injection."""

    xml_content: str
    sources: list[SourceCitation]
    total_chars: int = Field(
        description="Total characters of note content placed inside the context block."
    )


class AugmentResponse(BaseModel):
    """Response from POST /augment."""

    retrieval_attempted: bool
    context_injected: bool
    intent_confidence: float
    triggered_signals: list[str]
    context_block: ContextBlock | None
    augmented_prompt: str | None
    search_time_ms: float | None
