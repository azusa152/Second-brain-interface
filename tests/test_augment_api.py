"""Integration tests for POST /augment endpoint."""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from backend.api.dependencies import set_augment_service
from backend.application.augment_service import AugmentService
from backend.domain.models import AugmentResponse, ContextBlock, SourceCitation


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_augment_service() -> MagicMock:
    """Inject a mock AugmentService into the DI container."""
    mock = MagicMock(spec=AugmentService)
    set_augment_service(mock)
    yield mock
    set_augment_service(None)  # type: ignore[arg-type]


def _context_response() -> AugmentResponse:
    return AugmentResponse(
        retrieval_attempted=True,
        context_injected=True,
        intent_confidence=0.72,
        triggered_signals=["keyword:investment", "temporal:last_year"],
        context_block=ContextBlock(
            xml_content="<context>\n  <note title='Note A' path='a.md' score='0.87'>\n    content\n  </note>\n</context>",
            sources=[
                SourceCitation(
                    note_path="a.md",
                    note_title="Note A",
                    heading_context="Background",
                    score=0.87,
                )
            ],
            total_chars=7,
        ),
        augmented_prompt="[System: ...]\n<context>...</context>\n[User]: my question",
        search_time_ms=48.3,
    )


def _pass_through_response() -> AugmentResponse:
    return AugmentResponse(
        retrieval_attempted=False,
        context_injected=False,
        intent_confidence=0.04,
        triggered_signals=[],
        context_block=None,
        augmented_prompt=None,
        search_time_ms=None,
    )


def _no_results_response() -> AugmentResponse:
    return AugmentResponse(
        retrieval_attempted=True,
        context_injected=False,
        intent_confidence=0.65,
        triggered_signals=["keyword:journal"],
        context_block=None,
        augmented_prompt=None,
        search_time_ms=32.1,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestAugmentEndpoint:
    def test_returns_200_with_context_for_personal_query(
        self, client: TestClient, mock_augment_service: MagicMock
    ) -> None:
        mock_augment_service.augment.return_value = _context_response()

        resp = client.post("/augment", json={"message": "my investment notes last year"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["retrieval_attempted"] is True
        assert body["context_injected"] is True
        assert body["augmented_prompt"] is not None
        assert body["context_block"] is not None
        assert len(body["context_block"]["sources"]) == 1
        assert body["context_block"]["sources"][0]["note_path"] == "a.md"

    def test_returns_200_for_general_query_no_context(
        self, client: TestClient, mock_augment_service: MagicMock
    ) -> None:
        mock_augment_service.augment.return_value = _pass_through_response()

        resp = client.post("/augment", json={"message": "what is a binary tree?"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["retrieval_attempted"] is False
        assert body["context_injected"] is False
        assert body["augmented_prompt"] is None
        assert body["context_block"] is None
        assert body["search_time_ms"] is None

    def test_returns_200_when_retrieval_attempted_but_no_results(
        self, client: TestClient, mock_augment_service: MagicMock
    ) -> None:
        mock_augment_service.augment.return_value = _no_results_response()

        resp = client.post("/augment", json={"message": "my obscure journal entry"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["retrieval_attempted"] is True
        assert body["context_injected"] is False
        assert body["augmented_prompt"] is None

    def test_returns_422_for_empty_message(self, client: TestClient) -> None:
        resp = client.post("/augment", json={"message": ""})
        assert resp.status_code == 422

    def test_returns_422_for_missing_message(self, client: TestClient) -> None:
        resp = client.post("/augment", json={})
        assert resp.status_code == 422

    def test_returns_422_for_invalid_top_k(self, client: TestClient) -> None:
        resp = client.post("/augment", json={"message": "my notes", "top_k": 0})
        assert resp.status_code == 422

    def test_returns_503_on_service_exception(
        self, client: TestClient, mock_augment_service: MagicMock
    ) -> None:
        mock_augment_service.augment.side_effect = RuntimeError("qdrant unavailable")

        resp = client.post("/augment", json={"message": "my investment notes"})

        assert resp.status_code == 503
        assert resp.json()["detail"]["error_code"] == "AUGMENT_UNAVAILABLE"

    def test_delegates_full_request_to_service(
        self, client: TestClient, mock_augment_service: MagicMock
    ) -> None:
        mock_augment_service.augment.return_value = _pass_through_response()

        client.post(
            "/augment",
            json={"message": "my career decisions", "top_k": 4, "include_sources": False},
        )

        call_args = mock_augment_service.augment.call_args[0][0]
        assert call_args.message == "my career decisions"
        assert call_args.top_k == 4
        assert call_args.include_sources is False

    def test_intent_confidence_and_signals_in_response(
        self, client: TestClient, mock_augment_service: MagicMock
    ) -> None:
        mock_augment_service.augment.return_value = _context_response()

        resp = client.post("/augment", json={"message": "my investment last year"})

        body = resp.json()
        assert body["intent_confidence"] == pytest.approx(0.72)
        assert "keyword:investment" in body["triggered_signals"]
