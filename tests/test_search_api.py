"""Integration tests for the POST /search API endpoint."""

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from backend.domain.exceptions import IndexRebuildRequiredError
from backend.domain.models import SearchFilter, SearchRequest, SearchResponse, SearchResultItem


def _make_search_response(query: str = "test", num_results: int = 2) -> SearchResponse:
    """Build a SearchResponse for mocking."""
    results = [
        SearchResultItem(
            chunk_id=f"chunk_{i}",
            note_path=f"notes/note{i}.md",
            note_title=f"Note {i}",
            content=f"Content {i}",
            score=round(0.9 - i * 0.1, 2),
        )
        for i in range(num_results)
    ]
    return SearchResponse(
        query=query,
        results=results,
        related_notes=[],
        total_hits=num_results,
        search_time_ms=12.3,
        did_you_mean=None,
        applied_filters=None,
    )


class TestSearchEndpoint:
    def test_search_should_return_200_with_results(
        self, client: TestClient, mock_search_service: MagicMock
    ) -> None:
        mock_search_service.search.return_value = _make_search_response("database migration", 3)

        resp = client.post("/search", json={"query": "database migration"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["query"] == "database migration"
        assert len(body["results"]) == 3
        assert body["total_hits"] == 3

    def test_search_should_return_200_with_empty_results(
        self, client: TestClient, mock_search_service: MagicMock
    ) -> None:
        mock_search_service.search.return_value = _make_search_response("no match", 0)

        resp = client.post("/search", json={"query": "no match"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["results"] == []
        assert body["total_hits"] == 0

    def test_search_should_pass_top_k_to_service(
        self, client: TestClient, mock_search_service: MagicMock
    ) -> None:
        mock_search_service.search.return_value = _make_search_response()

        client.post("/search", json={"query": "test", "top_k": 10})

        call_args = mock_search_service.search.call_args[0][0]
        assert isinstance(call_args, SearchRequest)
        assert call_args.top_k == 10

    def test_search_should_pass_custom_threshold_to_service(
        self, client: TestClient, mock_search_service: MagicMock
    ) -> None:
        mock_search_service.search.return_value = _make_search_response()

        client.post("/search", json={"query": "test", "threshold": 0.7})

        call_args = mock_search_service.search.call_args[0][0]
        assert call_args.threshold == 0.7

    def test_search_should_return_422_for_missing_query(
        self, client: TestClient, mock_search_service: MagicMock
    ) -> None:
        resp = client.post("/search", json={})

        assert resp.status_code == 422

    def test_search_should_return_422_for_top_k_exceeding_max(
        self, client: TestClient, mock_search_service: MagicMock
    ) -> None:
        resp = client.post("/search", json={"query": "test", "top_k": 100})

        assert resp.status_code == 422

    def test_search_should_return_422_for_top_k_zero(
        self, client: TestClient, mock_search_service: MagicMock
    ) -> None:
        resp = client.post("/search", json={"query": "test", "top_k": 0})

        assert resp.status_code == 422

    def test_search_should_return_422_for_invalid_filter_date_range(
        self, client: TestClient, mock_search_service: MagicMock
    ) -> None:
        resp = client.post(
            "/search",
            json={
                "query": "test",
                "filters": {
                    "modified_after": "2026-01-01T00:00:00Z",
                    "modified_before": "2025-01-01T00:00:00Z",
                },
            },
        )

        assert resp.status_code == 422
        mock_search_service.search.assert_not_called()

    def test_search_should_return_503_on_service_error(
        self, client: TestClient, mock_search_service: MagicMock
    ) -> None:
        mock_search_service.search.side_effect = RuntimeError("Qdrant unreachable")

        resp = client.post("/search", json={"query": "test"})

        assert resp.status_code == 503
        body = resp.json()
        assert body["error_code"] == "SEARCH_UNAVAILABLE"

    def test_search_response_should_include_search_time(
        self, client: TestClient, mock_search_service: MagicMock
    ) -> None:
        mock_search_service.search.return_value = _make_search_response()

        resp = client.post("/search", json={"query": "test"})

        body = resp.json()
        assert "search_time_ms" in body
        assert isinstance(body["search_time_ms"], float)

    def test_search_results_should_include_note_metadata(
        self, client: TestClient, mock_search_service: MagicMock
    ) -> None:
        mock_search_service.search.return_value = _make_search_response("test", 1)

        resp = client.post("/search", json={"query": "test"})

        result = resp.json()["results"][0]
        assert "chunk_id" in result
        assert "note_path" in result
        assert "note_title" in result
        assert "content" in result
        assert "score" in result

    def test_search_response_should_include_did_you_mean_field(
        self, client: TestClient, mock_search_service: MagicMock
    ) -> None:
        mock_search_service.search.return_value = _make_search_response()

        resp = client.post("/search", json={"query": "test"})

        body = resp.json()
        assert "did_you_mean" in body

    def test_search_should_pass_filters_to_service(
        self, client: TestClient, mock_search_service: MagicMock
    ) -> None:
        mock_search_service.search.return_value = _make_search_response("deployment", 1)
        request_payload = {
            "query": "deployment",
            "filters": {
                "tags": ["devops"],
                "exclude_tags": ["archive"],
                "path_prefix": "projects/",
                "modified_after": "2025-01-01T00:00:00Z",
                "modified_before": "2026-01-01T00:00:00Z",
            },
        }

        resp = client.post("/search", json=request_payload)

        assert resp.status_code == 200
        call_args = mock_search_service.search.call_args[0][0]
        assert isinstance(call_args, SearchRequest)
        assert isinstance(call_args.filters, SearchFilter)
        assert call_args.filters.tags == ["devops"]
        assert call_args.filters.exclude_tags == ["archive"]
        assert call_args.filters.path_prefix == "projects/"
        assert call_args.filters.modified_after is not None
        assert call_args.filters.modified_before is not None

    def test_search_should_return_409_when_rebuild_required(
        self, client: TestClient, mock_search_service: MagicMock
    ) -> None:
        mock_search_service.search.side_effect = IndexRebuildRequiredError(
            "path_prefix filter requires a full rebuild. Run POST /index/rebuild first."
        )

        resp = client.post(
            "/search",
            json={
                "query": "test",
                "filters": {"path_prefix": "projects/"},
            },
        )

        assert resp.status_code == 409
        body = resp.json()
        assert body["error_code"] == "INDEX_REBUILD_REQUIRED"
        assert "rebuild" in body["message"].lower()

    def test_search_should_return_applied_filters_field(
        self, client: TestClient, mock_search_service: MagicMock
    ) -> None:
        mock_search_service.search.return_value = SearchResponse(
            query="deployment",
            results=[],
            related_notes=[],
            total_hits=0,
            search_time_ms=9.1,
            did_you_mean=None,
            applied_filters=SearchFilter(tags=["devops"], path_prefix="projects/"),
        )

        resp = client.post("/search", json={"query": "deployment"})

        assert resp.status_code == 200
        body = resp.json()
        assert "applied_filters" in body
        assert body["applied_filters"]["tags"] == ["devops"]
        assert body["applied_filters"]["path_prefix"] == "projects/"
