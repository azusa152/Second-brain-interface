"""Tests for GET /index/events and GET /index/notes endpoints."""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from backend.api.dependencies import set_index_service
from backend.application.index_service import IndexService
from backend.domain.models import IndexedNoteItem
from backend.infrastructure.event_log import WatcherEvent


@pytest.fixture()
def mock_index_service() -> MagicMock:
    """Create and inject a mock IndexService."""
    mock = MagicMock(spec=IndexService)
    set_index_service(mock)
    yield mock
    set_index_service(None)  # type: ignore[arg-type]


class TestGetWatcherEvents:
    def test_events_should_return_200_with_events(
        self, client: TestClient, mock_index_service: MagicMock
    ) -> None:
        ts = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        mock_index_service.get_recent_events.return_value = [
            WatcherEvent(event_type="modified", file_path="note.md", timestamp=ts),
            WatcherEvent(event_type="created", file_path="new.md", timestamp=ts),
        ]

        resp = client.get("/index/events")

        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        assert len(body["events"]) == 2
        assert body["events"][0]["event_type"] == "modified"
        assert body["events"][0]["file_path"] == "note.md"

    def test_events_should_return_200_with_empty_list(
        self, client: TestClient, mock_index_service: MagicMock
    ) -> None:
        mock_index_service.get_recent_events.return_value = []

        resp = client.get("/index/events")

        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 0
        assert body["events"] == []

    def test_events_should_pass_limit_parameter(
        self, client: TestClient, mock_index_service: MagicMock
    ) -> None:
        mock_index_service.get_recent_events.return_value = []

        client.get("/index/events?limit=10")

        mock_index_service.get_recent_events.assert_called_once_with(10)

    def test_events_should_use_default_limit_of_50(
        self, client: TestClient, mock_index_service: MagicMock
    ) -> None:
        mock_index_service.get_recent_events.return_value = []

        client.get("/index/events")

        mock_index_service.get_recent_events.assert_called_once_with(50)

    def test_events_should_return_422_for_limit_zero(
        self, client: TestClient, mock_index_service: MagicMock
    ) -> None:
        resp = client.get("/index/events?limit=0")

        assert resp.status_code == 422

    def test_events_should_return_422_for_limit_over_100(
        self, client: TestClient, mock_index_service: MagicMock
    ) -> None:
        resp = client.get("/index/events?limit=101")

        assert resp.status_code == 422

    def test_events_should_include_dest_path_for_moved_events(
        self, client: TestClient, mock_index_service: MagicMock
    ) -> None:
        ts = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        mock_index_service.get_recent_events.return_value = [
            WatcherEvent(
                event_type="moved",
                file_path="old.md",
                dest_path="new.md",
                timestamp=ts,
            ),
        ]

        resp = client.get("/index/events")

        event = resp.json()["events"][0]
        assert event["dest_path"] == "new.md"

    def test_events_should_have_null_dest_path_for_non_move_events(
        self, client: TestClient, mock_index_service: MagicMock
    ) -> None:
        ts = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        mock_index_service.get_recent_events.return_value = [
            WatcherEvent(event_type="deleted", file_path="gone.md", timestamp=ts),
        ]

        resp = client.get("/index/events")

        assert resp.json()["events"][0]["dest_path"] is None


class TestGetIndexedNotes:
    def test_notes_should_return_200_with_notes(
        self, client: TestClient, mock_index_service: MagicMock
    ) -> None:
        mock_index_service.get_indexed_notes.return_value = [
            IndexedNoteItem(note_path="docs/api.md", note_title="API Reference"),
            IndexedNoteItem(note_path="notes/daily.md", note_title="Daily Note"),
        ]

        resp = client.get("/index/notes")

        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        assert len(body["notes"]) == 2
        assert body["notes"][0]["note_path"] == "docs/api.md"
        assert body["notes"][0]["note_title"] == "API Reference"

    def test_notes_should_return_200_with_empty_list(
        self, client: TestClient, mock_index_service: MagicMock
    ) -> None:
        mock_index_service.get_indexed_notes.return_value = []

        resp = client.get("/index/notes")

        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 0
        assert body["notes"] == []

    def test_notes_should_call_service_get_indexed_notes(
        self, client: TestClient, mock_index_service: MagicMock
    ) -> None:
        mock_index_service.get_indexed_notes.return_value = []

        client.get("/index/notes")

        mock_index_service.get_indexed_notes.assert_called_once()
