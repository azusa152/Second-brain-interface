"""Shared pytest fixtures for the Second Brain Interface test suite.

Service-level mocks use ``app.dependency_overrides`` — the idiomatic FastAPI
way to substitute dependencies in tests without reaching into module-level
globals.  Each fixture restores the override map on teardown so tests remain
isolated.
"""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from backend.api.dependencies import (
    get_augment_service,
    get_index_service,
    get_intent_service,
    get_search_service,
)
from backend.application.augment_service import AugmentService
from backend.application.index_service import IndexService
from backend.application.intent_service import IntentService
from backend.application.search_service import SearchService
from backend.main import app

# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------


@pytest.fixture()
def client() -> TestClient:
    """Provide a FastAPI test client (no lifespan — services are injected via overrides)."""
    return TestClient(app)


# ---------------------------------------------------------------------------
# Shared service mocks — use these in API-layer tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_search_service() -> MagicMock:
    """Inject a mock SearchService for the duration of a test."""
    mock = MagicMock(spec=SearchService)
    app.dependency_overrides[get_search_service] = lambda: mock
    yield mock
    app.dependency_overrides.pop(get_search_service, None)


@pytest.fixture()
def mock_index_service() -> MagicMock:
    """Inject a mock IndexService for the duration of a test."""
    mock = MagicMock(spec=IndexService)
    app.dependency_overrides[get_index_service] = lambda: mock
    yield mock
    app.dependency_overrides.pop(get_index_service, None)


@pytest.fixture()
def mock_intent_service() -> MagicMock:
    """Inject a mock IntentService for the duration of a test."""
    mock = MagicMock(spec=IntentService)
    app.dependency_overrides[get_intent_service] = lambda: mock
    yield mock
    app.dependency_overrides.pop(get_intent_service, None)


@pytest.fixture()
def mock_augment_service() -> MagicMock:
    """Inject a mock AugmentService for the duration of a test."""
    mock = MagicMock(spec=AugmentService)
    app.dependency_overrides[get_augment_service] = lambda: mock
    yield mock
    app.dependency_overrides.pop(get_augment_service, None)
