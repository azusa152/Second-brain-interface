import hashlib
import re
import time
from collections import Counter

from backend.domain.constants import SIMILARITY_THRESHOLD, SUGGEST_LINKS_QUERY_MAX_CHARS
from backend.domain.models import (
    NoteLinkItem,
    RelatedNote,
    SearchRequest,
    SearchResponse,
    SearchResultItem,
    SuggestedLink,
    SuggestLinksRequest,
    SuggestLinksResponse,
)
from backend.infrastructure.embedding import EmbeddingService
from backend.infrastructure.fuzzy_matcher import FuzzyMatcher
from backend.infrastructure.qdrant_adapter import QdrantAdapter
from backend.logging_config import get_logger

logger = get_logger(__name__)
_HIGHLIGHT_TERM_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")


class SearchService:
    """Orchestrate hybrid search: embed query → dense + sparse search → RRF fusion → rank."""

    def __init__(
        self,
        embedder: EmbeddingService,
        qdrant_adapter: QdrantAdapter,
        fuzzy_matcher: FuzzyMatcher | None = None,
        include_query_text_in_logs: bool = False,
    ) -> None:
        self._embedder = embedder
        self._qdrant = qdrant_adapter
        self._fuzzy_matcher = fuzzy_matcher
        self._include_query_text_in_logs = include_query_text_in_logs

    def refresh_fuzzy_vocabulary(self) -> None:
        """Rebuild in-memory fuzzy vocabulary from indexed title and heading text."""
        if self._fuzzy_matcher is None:
            return

        titles, headings = self._qdrant.get_fuzzy_vocabulary_sources()
        self._fuzzy_matcher.rebuild_vocabulary(titles=titles, headings=headings)
        logger.info(
            "fuzzy_vocabulary_refreshed",
            title_count=len(titles),
            heading_count=len(headings),
        )

    def search(self, request: SearchRequest) -> SearchResponse:
        """Execute a hybrid search (dense + sparse) over indexed chunks."""
        start = time.time()

        threshold = request.threshold if request.threshold is not None else SIMILARITY_THRESHOLD

        sparse_query_used = request.query
        did_you_mean: str | None = None

        # 1. Embed and search with original query first
        query_vector = self._embedder.embed_text(request.query)
        sparse_vector = self._embedder.embed_text_sparse(request.query)
        results = self._qdrant.hybrid_search(
            query_vector=query_vector,
            sparse_vector=sparse_vector,
            top_k=request.top_k,
            threshold=threshold,
        )

        # 2. Fuzzy fallback for sparse query only when original query yields no hits
        if not results and self._fuzzy_matcher is not None:
            corrected_sparse_query, suggestion = self._fuzzy_matcher.correct_query(request.query)
            if suggestion is not None and corrected_sparse_query != request.query:
                sparse_query_used = corrected_sparse_query
                sparse_vector = self._embedder.embed_text_sparse(corrected_sparse_query)
                results = self._qdrant.hybrid_search(
                    query_vector=query_vector,
                    sparse_vector=sparse_vector,
                    top_k=request.top_k,
                    threshold=threshold,
                )
                if results:
                    did_you_mean = suggestion

        self._apply_highlights(results, request.query, sparse_query_used)

        # 3. Graph enrichment: fetch related notes via wikilinks
        related_notes: list[RelatedNote] = []
        if request.include_related and results:
            related_notes = self._enrich_with_related_notes(results)

        elapsed_ms = (time.time() - start) * 1000

        logger.info(
            "search_completed",
            top_k=request.top_k,
            include_related=request.include_related,
            results=len(results),
            related=len(related_notes),
            duration_ms=round(elapsed_ms, 1),
            **self._query_logging_fields(request.query),
        )

        return SearchResponse(
            query=request.query,
            results=results,
            related_notes=related_notes,
            total_hits=len(results),
            search_time_ms=round(elapsed_ms, 1),
            did_you_mean=did_you_mean,
        )

    def _enrich_with_related_notes(
        self,
        results: list[SearchResultItem],
    ) -> list[RelatedNote]:
        """Fetch outgoing links and backlinks for all result note paths (batch)."""
        result_paths = {r.note_path for r in results}

        # Single batch query for all links (no N+1)
        relations = self._qdrant.get_related_notes_batch(result_paths)

        # Aggregate: count links per (related_path, relationship), excluding self-links
        # and paths already in the search results
        counter: Counter[tuple[str, str]] = Counter()
        for _note_path, link_list in relations.items():
            for link in link_list:
                related_path = link["related_path"]
                relationship = link["relationship"]
                if related_path not in result_paths:
                    counter[(related_path, relationship)] += 1

        # Build RelatedNote list, sorted by link_count descending
        related_notes: list[RelatedNote] = []
        for (related_path, relationship), count in counter.most_common():
            # Derive title from path (filename without extension)
            title = related_path.rsplit("/", 1)[-1].removesuffix(".md")
            related_notes.append(
                RelatedNote(
                    note_path=related_path,
                    note_title=title,
                    relationship=relationship,
                    link_count=count,
                )
            )

        return related_notes

    def get_note_links(self, note_path: str) -> list[dict[str, str]]:
        """Return all outgoing links and backlinks for a single note."""
        relations = self._qdrant.get_related_notes_batch({note_path})
        return relations.get(note_path, [])

    def is_note_indexed(self, note_path: str) -> bool:
        """Check if a note exists in the index."""
        return self._qdrant.is_note_indexed(note_path)

    def suggest_links(self, request: SuggestLinksRequest) -> SuggestLinksResponse:
        """Suggest wikilinks and tags for draft note content.

        Extracts a focused query from the draft title and first meaningful
        sentences (respecting the embedding model's input limit), runs hybrid
        search, deduplicates results by note path, and aggregates tags by
        frequency across matched chunks.
        """
        query = self._extract_query_from_content(request.content, request.title)

        # Over-fetch to ensure enough unique notes after deduplication.
        # Fetch at least 20 chunks to handle vaults where many chunks come from
        # the same few notes.
        fetch_k = max(request.max_suggestions * 3, 20)
        query_vector = self._embedder.embed_text(query)
        sparse_vector = self._embedder.embed_text_sparse(query)

        raw_results = self._qdrant.hybrid_search(
            query_vector=query_vector,
            sparse_vector=sparse_vector,
            top_k=fetch_k,
        )

        # Deduplicate by note_path: keep highest-score chunk per note
        seen_paths: dict[str, SearchResultItem] = {}
        for item in raw_results:
            if item.note_path not in seen_paths or item.score > seen_paths[item.note_path].score:
                seen_paths[item.note_path] = item

        # Build suggested wikilinks from top-scoring deduplicated notes
        top_results = sorted(seen_paths.values(), key=lambda r: r.score, reverse=True)
        top_results = top_results[: request.max_suggestions]

        suggested_wikilinks = [
            SuggestedLink(
                display_text=item.note_title,
                target_path=item.note_path,
                score=round(item.score, 4),
            )
            for item in top_results
        ]

        # Collect tags only from the notes that are actually being suggested,
        # so tag recommendations are coherent with the wikilink suggestions.
        tag_counter: Counter[str] = Counter()
        for item in top_results:
            tag_counter.update(item.tags)
        suggested_tags = [tag for tag, _ in tag_counter.most_common()]

        # Build related notes from graph enrichment (exclude the suggestions themselves)
        suggestion_paths = {item.note_path for item in top_results}
        related_notes: list[NoteLinkItem] = []
        if top_results:
            relations = self._qdrant.get_related_notes_batch(suggestion_paths)
            seen_related: set[str] = set()
            for link_list in relations.values():
                for link in link_list:
                    related_path = link["related_path"]
                    if related_path not in suggestion_paths and related_path not in seen_related:
                        seen_related.add(related_path)
                        title = related_path.rsplit("/", 1)[-1].removesuffix(".md")
                        related_notes.append(NoteLinkItem(note_path=related_path, note_title=title))

        logger.info(
            "suggest_links_completed",
            max_suggestions=request.max_suggestions,
            wikilinks=len(suggested_wikilinks),
            tags=len(suggested_tags),
            related=len(related_notes),
            **self._query_logging_fields(query, preview_length=60),
        )

        return SuggestLinksResponse(
            suggested_wikilinks=suggested_wikilinks,
            suggested_tags=suggested_tags,
            related_notes=related_notes,
        )

    @staticmethod
    def _extract_query_from_content(content: str, title: str | None) -> str:
        """Extract a focused query string from draft note content.

        Skips YAML frontmatter and heading lines, then concatenates the first
        non-empty lines up to SUGGEST_LINKS_QUERY_MAX_CHARS. This keeps the
        input within the embedding model's effective range (~256 tokens / 512 chars).
        Falls back to a direct truncation if no meaningful body lines are found.
        """
        lines = content.strip().splitlines()

        # Skip YAML frontmatter block
        if lines and lines[0].strip() == "---":
            for i, line in enumerate(lines[1:], 1):
                if line.strip() == "---":
                    lines = lines[i + 1 :]
                    break

        # Collect first non-empty, non-heading lines up to the char budget.
        # Track the joined length (including separating spaces) so the early-exit
        # condition matches what " ".join() actually produces.
        body_parts: list[str] = []
        joined_len = 0
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            # Account for the space separator between parts
            added = len(stripped) + (1 if body_parts else 0)
            if joined_len + added > SUGGEST_LINKS_QUERY_MAX_CHARS:
                break
            body_parts.append(stripped)
            joined_len += added

        body = " ".join(body_parts)

        if title:
            return f"{title}. {body}" if body else title
        return body or content[:SUGGEST_LINKS_QUERY_MAX_CHARS]

    def _query_logging_fields(
        self, query: str, preview_length: int | None = None
    ) -> dict[str, str | int]:
        """Return privacy-safe query logging fields."""
        fields: dict[str, str | int] = {
            "query_len": len(query),
            "query_hash": hashlib.sha256(query.encode("utf-8")).hexdigest()[:12],
        }
        if self._include_query_text_in_logs:
            fields["query"] = query if preview_length is None else query[:preview_length]
        return fields

    @staticmethod
    def _apply_highlights(
        results: list[SearchResultItem],
        original_query: str,
        corrected_query: str,
    ) -> None:
        """Attach query-term snippet highlights to each search result."""
        terms = SearchService._extract_highlight_terms(original_query, corrected_query)
        if not terms:
            return

        for result in results:
            result.highlights = SearchService._build_highlights(result.content, terms)

    @staticmethod
    def _extract_highlight_terms(original_query: str, corrected_query: str) -> list[str]:
        """Extract deduplicated searchable terms from query text."""
        terms: set[str] = set()
        for text in (original_query, corrected_query):
            for term in _HIGHLIGHT_TERM_PATTERN.findall(text):
                normalized = term.casefold()
                if len(normalized) >= 2:
                    terms.add(normalized)
        return sorted(terms, key=len, reverse=True)

    @staticmethod
    def _build_highlights(content: str, terms: list[str]) -> list[str]:
        """Build compact text snippets around matched terms."""
        if not content:
            return []

        content_folded = content.casefold()
        snippets: list[str] = []
        seen_ranges: set[tuple[int, int]] = set()
        max_snippets = 2
        window = 60

        for term in terms:
            if len(snippets) >= max_snippets:
                break
            start_index = content_folded.find(term)
            if start_index == -1:
                continue

            start = max(0, start_index - window)
            end = min(len(content), start_index + len(term) + window)
            key = (start, end)
            if key in seen_ranges:
                continue
            seen_ranges.add(key)

            prefix = "... " if start > 0 else ""
            suffix = " ..." if end < len(content) else ""
            snippets.append(f"{prefix}{content[start:end].strip()}{suffix}")

        return snippets
