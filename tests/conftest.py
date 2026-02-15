import pytest
from fastapi.testclient import TestClient

from backend.main import app


@pytest.fixture()
def client() -> TestClient:
    """Provide a FastAPI test client."""
    return TestClient(app)
