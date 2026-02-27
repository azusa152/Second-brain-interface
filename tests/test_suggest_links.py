"""Tests for POST /note/suggest-links endpoint and SearchService.suggest_links()."""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from backend.application.search_service import SearchService
from backend.domain.models import (
    NoteLinkItem,
    SearchResultItem,
    SuggestedLink,
    SuggestLinksRequest,
    SuggestLinksResponse,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_result(
    note_path: str = "notes/note.md",
    note_title: str = "Note",
    score: float = 0.85,
    tags: list[str] | None = None,
) -> SearchResultItem:
    return SearchResultItem(
        chunk_id=f"{note_path}::0",
        note_path=note_path,
        note_title=note_title,
        content="Some content",
        score=score,
        tags=tags or [],
    )


def _make_suggest_response(num_links: int = 2) -> SuggestLinksResponse:
    return SuggestLinksResponse(
        suggested_wikilinks=[
            SuggestedLink(
                display_text=f"Note {i}",
                target_path=f"notes/note{i}.md",
                score=round(0.9 - i * 0.1, 2),
            )
            for i in range(num_links)
        ],
        suggested_tags=["#architecture", "#decision"],
        related_notes=[NoteLinkItem(note_path="concepts/related.md", note_title="related")],
    )


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------


class TestSuggestLinksEndpoint:
    def test_suggest_links_should_return_200_with_suggestions(
        self, client: TestClient, mock_search_service: MagicMock
    ) -> None:
        mock_search_service.suggest_links.return_value = _make_suggest_response(2)

        resp = client.post(
            "/note/suggest-links",
            json={"content": "We decided to use Flyway for database migrations."},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["suggested_wikilinks"]) == 2
        assert body["suggested_wikilinks"][0]["display_text"] == "Note 0"
        assert "suggested_tags" in body
        assert "related_notes" in body

    def test_suggest_links_should_pass_request_to_service(
        self, client: TestClient, mock_search_service: MagicMock
    ) -> None:
        mock_search_service.suggest_links.return_value = _make_suggest_response()

        client.post(
            "/note/suggest-links",
            json={
                "content": "Draft content here.",
                "title": "My Draft",
                "max_suggestions": 3,
            },
        )

        call_args = mock_search_service.suggest_links.call_args[0][0]
        assert isinstance(call_args, SuggestLinksRequest)
        assert call_args.content == "Draft content here."
        assert call_args.title == "My Draft"
        assert call_args.max_suggestions == 3

    def test_suggest_links_should_return_200_with_empty_results(
        self, client: TestClient, mock_search_service: MagicMock
    ) -> None:
        mock_search_service.suggest_links.return_value = SuggestLinksResponse(
            suggested_wikilinks=[],
            suggested_tags=[],
            related_notes=[],
        )

        resp = client.post(
            "/note/suggest-links",
            json={"content": "Content with no vault matches."},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["suggested_wikilinks"] == []
        assert body["suggested_tags"] == []
        assert body["related_notes"] == []

    def test_suggest_links_should_return_422_for_empty_content(
        self, client: TestClient, mock_search_service: MagicMock
    ) -> None:
        resp = client.post("/note/suggest-links", json={"content": ""})

        assert resp.status_code == 422

    def test_suggest_links_should_return_422_for_missing_content(
        self, client: TestClient, mock_search_service: MagicMock
    ) -> None:
        resp = client.post("/note/suggest-links", json={})

        assert resp.status_code == 422

    def test_suggest_links_should_return_422_for_max_suggestions_exceeding_limit(
        self, client: TestClient, mock_search_service: MagicMock
    ) -> None:
        resp = client.post(
            "/note/suggest-links",
            json={"content": "Some content.", "max_suggestions": 100},
        )

        assert resp.status_code == 422

    def test_suggest_links_should_return_503_on_any_exception(
        self, client: TestClient, mock_search_service: MagicMock
    ) -> None:
        """Any unhandled exception in suggest_links is caught and surfaced as 503."""
        mock_search_service.suggest_links.side_effect = RuntimeError("Qdrant unreachable")

        resp = client.post("/note/suggest-links", json={"content": "Some content."})

        assert resp.status_code == 503
        body = resp.json()
        assert body["error_code"] == "SUGGEST_LINKS_UNAVAILABLE"

    def test_suggest_links_response_should_include_score_in_wikilinks(
        self, client: TestClient, mock_search_service: MagicMock
    ) -> None:
        mock_search_service.suggest_links.return_value = _make_suggest_response(1)

        resp = client.post("/note/suggest-links", json={"content": "Some content."})

        link = resp.json()["suggested_wikilinks"][0]
        assert "display_text" in link
        assert "target_path" in link
        assert "score" in link
        assert isinstance(link["score"], float)


# ---------------------------------------------------------------------------
# SearchService.suggest_links() unit tests
# ---------------------------------------------------------------------------


class TestSuggestLinksService:
    @pytest.fixture()
    def embedder(self) -> MagicMock:
        mock = MagicMock()
        mock.embed_text.return_value = [0.1] * 384
        mock.embed_text_sparse.return_value = MagicMock(indices=[0], values=[1.0])
        return mock

    @pytest.fixture()
    def qdrant(self) -> MagicMock:
        return MagicMock()

    @pytest.fixture()
    def service(self, embedder: MagicMock, qdrant: MagicMock) -> SearchService:
        return SearchService(embedder=embedder, qdrant_adapter=qdrant)

    def test_suggest_links_should_deduplicate_chunks_by_note_path(
        self, service: SearchService, qdrant: MagicMock
    ) -> None:
        # Two chunks from the same note — only the highest-score one should appear
        qdrant.hybrid_search.return_value = [
            _make_result("notes/adr.md", "ADR-001", score=0.9),
            _make_result("notes/adr.md", "ADR-001", score=0.7),
            _make_result("notes/other.md", "Other Note", score=0.8),
        ]
        qdrant.get_related_notes_batch.return_value = {}

        result = service.suggest_links(SuggestLinksRequest(content="ADR decision"))

        paths = [link.target_path for link in result.suggested_wikilinks]
        assert paths.count("notes/adr.md") == 1

    def test_suggest_links_should_keep_highest_score_on_dedup(
        self, service: SearchService, qdrant: MagicMock
    ) -> None:
        qdrant.hybrid_search.return_value = [
            _make_result("notes/adr.md", "ADR", score=0.7),
            _make_result("notes/adr.md", "ADR", score=0.95),
        ]
        qdrant.get_related_notes_batch.return_value = {}

        result = service.suggest_links(SuggestLinksRequest(content="some content"))

        assert result.suggested_wikilinks[0].score == 0.95

    def test_suggest_links_should_collect_tags_sorted_by_frequency(
        self, service: SearchService, qdrant: MagicMock
    ) -> None:
        qdrant.hybrid_search.return_value = [
            _make_result("notes/a.md", tags=["#arch", "#db"]),
            _make_result("notes/b.md", tags=["#arch", "#decision"]),
            _make_result("notes/c.md", tags=["#db"]),
        ]
        qdrant.get_related_notes_batch.return_value = {}

        result = service.suggest_links(SuggestLinksRequest(content="architecture"))

        # #arch appears 2 times, #db appears 2 times, #decision appears 1 time
        assert "#arch" in result.suggested_tags[:2]
        assert "#db" in result.suggested_tags[:2]
        assert "#decision" in result.suggested_tags

    def test_suggest_links_should_respect_max_suggestions(
        self, service: SearchService, qdrant: MagicMock
    ) -> None:
        qdrant.hybrid_search.return_value = [
            _make_result(f"notes/note{i}.md", f"Note {i}", score=1.0 - i * 0.05) for i in range(10)
        ]
        qdrant.get_related_notes_batch.return_value = {}

        result = service.suggest_links(SuggestLinksRequest(content="query", max_suggestions=3))

        assert len(result.suggested_wikilinks) == 3

    def test_suggest_links_should_include_related_notes_from_graph(
        self, service: SearchService, qdrant: MagicMock
    ) -> None:
        qdrant.hybrid_search.return_value = [
            _make_result("notes/adr.md", "ADR"),
        ]
        qdrant.get_related_notes_batch.return_value = {
            "notes/adr.md": [{"related_path": "concepts/flyway.md", "relationship": "outgoing"}]
        }

        result = service.suggest_links(SuggestLinksRequest(content="migration"))

        related_paths = [r.note_path for r in result.related_notes]
        assert "concepts/flyway.md" in related_paths

    def test_suggest_links_should_exclude_suggestion_paths_from_related_notes(
        self, service: SearchService, qdrant: MagicMock
    ) -> None:
        qdrant.hybrid_search.return_value = [
            _make_result("notes/adr.md", "ADR"),
        ]
        # Backlink points back to the suggestion itself
        qdrant.get_related_notes_batch.return_value = {
            "notes/adr.md": [{"related_path": "notes/adr.md", "relationship": "backlink"}]
        }

        result = service.suggest_links(SuggestLinksRequest(content="migration"))

        related_paths = [r.note_path for r in result.related_notes]
        assert "notes/adr.md" not in related_paths


# ---------------------------------------------------------------------------
# SearchService._extract_query_from_content() unit tests
# ---------------------------------------------------------------------------


class TestExtractQueryFromContent:
    def test_extract_should_combine_title_and_body(self) -> None:
        content = "We decided to use Flyway for migrations."
        result = SearchService._extract_query_from_content(content, title="ADR-005")

        assert result.startswith("ADR-005.")
        assert "Flyway" in result

    def test_extract_should_use_title_alone_when_body_is_empty(self) -> None:
        result = SearchService._extract_query_from_content(
            content="   \n\n   ", title="My Note Title"
        )

        assert result == "My Note Title"

    def test_extract_should_skip_yaml_frontmatter(self) -> None:
        content = "---\ntitle: Test\ndate: 2026-01-01\n---\nActual body content here."
        result = SearchService._extract_query_from_content(content, title=None)

        assert "title: Test" not in result
        assert "Actual body content here." in result

    def test_extract_should_skip_heading_lines(self) -> None:
        content = "# My Heading\n## Sub heading\nThis is the real content."
        result = SearchService._extract_query_from_content(content, title=None)

        assert "# My Heading" not in result
        assert "This is the real content." in result

    def test_extract_should_cap_at_max_chars(self) -> None:
        long_content = "word " * 500  # ~2500 chars
        result = SearchService._extract_query_from_content(long_content, title=None)

        assert len(result) <= 400

    def test_extract_should_fall_back_to_content_truncation_when_no_body_lines(
        self,
    ) -> None:
        content = "#" * 500  # Only heading-like content, no body lines
        result = SearchService._extract_query_from_content(content, title=None)

        # Falls back to direct truncation
        assert len(result) <= 400

    def test_extract_should_return_title_when_no_title_and_no_body(self) -> None:
        result = SearchService._extract_query_from_content(content="plain text", title=None)

        assert result == "plain text"
