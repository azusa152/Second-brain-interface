"""Tests for link graph queries and the GET /note/{path}/links endpoint."""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from backend.api.dependencies import set_search_service
from backend.application.search_service import SearchService
from backend.main import app


@pytest.fixture()
def mock_search_service() -> MagicMock:
    """Create and inject a mock SearchService."""
    mock = MagicMock(spec=SearchService)
    set_search_service(mock)
    yield mock
    set_search_service(None)  # type: ignore[arg-type]


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


class TestGetNoteLinksEndpoint:
    """Test GET /note/{path}/links endpoint."""

    def test_get_note_links_should_return_outlinks_and_backlinks(
        self, client: TestClient, mock_search_service: MagicMock
    ) -> None:
        mock_search_service.is_note_indexed.return_value = True
        mock_search_service.get_note_links.return_value = [
            {"related_path": "concepts/architecture.md", "relationship": "outgoing"},
            {"related_path": "projects/migration.md", "relationship": "outgoing"},
            {"related_path": "note1.md", "relationship": "backlink"},
        ]

        resp = client.get("/note/note3.md/links")

        assert resp.status_code == 200
        body = resp.json()
        assert body["note_path"] == "note3.md"
        assert len(body["outlinks"]) == 2
        assert len(body["backlinks"]) == 1
        assert body["backlinks"][0]["note_path"] == "note1.md"

    def test_get_note_links_should_return_empty_for_isolated_note(
        self, client: TestClient, mock_search_service: MagicMock
    ) -> None:
        mock_search_service.is_note_indexed.return_value = True
        mock_search_service.get_note_links.return_value = []

        resp = client.get("/note/isolated.md/links")

        assert resp.status_code == 200
        body = resp.json()
        assert body["outlinks"] == []
        assert body["backlinks"] == []

    def test_get_note_links_should_handle_nested_path(
        self, client: TestClient, mock_search_service: MagicMock
    ) -> None:
        mock_search_service.is_note_indexed.return_value = True
        mock_search_service.get_note_links.return_value = [
            {"related_path": "note3.md", "relationship": "backlink"},
        ]

        resp = client.get("/note/projects/migration.md/links")

        assert resp.status_code == 200
        body = resp.json()
        assert body["note_path"] == "projects/migration.md"
        assert len(body["backlinks"]) == 1

    def test_get_note_links_should_derive_title_from_path(
        self, client: TestClient, mock_search_service: MagicMock
    ) -> None:
        mock_search_service.is_note_indexed.return_value = True
        mock_search_service.get_note_links.return_value = [
            {
                "related_path": "concepts/system-architecture.md",
                "relationship": "outgoing",
            },
        ]

        resp = client.get("/note/note3.md/links")

        body = resp.json()
        assert body["outlinks"][0]["note_title"] == "system-architecture"

    def test_get_note_links_should_return_404_for_unindexed_note(
        self, client: TestClient, mock_search_service: MagicMock
    ) -> None:
        mock_search_service.is_note_indexed.return_value = False

        resp = client.get("/note/nonexistent.md/links")

        assert resp.status_code == 404
        body = resp.json()
        assert body["detail"]["error_code"] == "NOTE_NOT_FOUND"

    def test_get_note_links_response_should_not_include_relationship_field(
        self, client: TestClient, mock_search_service: MagicMock
    ) -> None:
        mock_search_service.is_note_indexed.return_value = True
        mock_search_service.get_note_links.return_value = [
            {"related_path": "other.md", "relationship": "outgoing"},
        ]

        resp = client.get("/note/note3.md/links")

        body = resp.json()
        assert "relationship" not in body["outlinks"][0]


class TestGetRelatedNotesBatch:
    """Unit tests for QdrantAdapter.get_related_notes_batch (mocked Qdrant client)."""

    def test_batch_should_return_empty_for_no_paths(self) -> None:
        from backend.infrastructure.qdrant_adapter import QdrantAdapter

        adapter = QdrantAdapter.__new__(QdrantAdapter)
        adapter.client = MagicMock()

        result = adapter.get_related_notes_batch(set())

        assert result == {}
        adapter.client.scroll.assert_not_called()

    def test_batch_should_collect_outgoing_and_backlinks(self) -> None:
        from qdrant_client.models import Record

        from backend.infrastructure.qdrant_adapter import QdrantAdapter

        adapter = QdrantAdapter.__new__(QdrantAdapter)
        adapter.client = MagicMock()

        # First scroll call (outgoing): returns one link from note3.md → architecture.md
        # Second scroll call (backlinks): returns one link migration.md → note3.md
        outgoing_point = MagicMock(spec=Record)
        outgoing_point.payload = {
            "source_path": "note3.md",
            "resolved_target_path": "concepts/architecture.md",
        }

        backlink_point = MagicMock(spec=Record)
        backlink_point.payload = {
            "source_path": "projects/migration.md",
            "resolved_target_path": "note3.md",
        }

        # scroll is called twice (outgoing then backlinks), each returns one page
        adapter.client.scroll.side_effect = [
            ([outgoing_point], None),  # outgoing scroll
            ([backlink_point], None),  # backlink scroll
        ]

        result = adapter.get_related_notes_batch({"note3.md"})

        assert len(result["note3.md"]) == 2
        relationships = {r["relationship"] for r in result["note3.md"]}
        assert relationships == {"outgoing", "backlink"}

    def test_batch_should_handle_pagination(self) -> None:
        from qdrant_client.models import Record

        from backend.infrastructure.qdrant_adapter import QdrantAdapter

        adapter = QdrantAdapter.__new__(QdrantAdapter)
        adapter.client = MagicMock()

        point1 = MagicMock(spec=Record)
        point1.payload = {
            "source_path": "a.md",
            "resolved_target_path": "b.md",
        }
        point2 = MagicMock(spec=Record)
        point2.payload = {
            "source_path": "a.md",
            "resolved_target_path": "c.md",
        }

        # Outgoing: two pages
        # Backlinks: empty
        adapter.client.scroll.side_effect = [
            ([point1], "next-page-id"),  # outgoing page 1
            ([point2], None),            # outgoing page 2
            ([], None),                  # backlinks (empty)
        ]

        result = adapter.get_related_notes_batch({"a.md"})

        assert len(result["a.md"]) == 2
        assert adapter.client.scroll.call_count == 3
