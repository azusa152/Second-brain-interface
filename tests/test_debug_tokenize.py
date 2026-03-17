import importlib
import os

from fastapi.testclient import TestClient

import backend.main as main_module
from backend import config as config_module


def _new_client_with_debug_enabled(enabled: bool) -> TestClient:
    if enabled:
        os.environ["DEBUG_ENDPOINTS"] = "true"
    else:
        os.environ["DEBUG_ENDPOINTS"] = "false"
    config_module.get_settings.cache_clear()
    importlib.reload(main_module)
    return TestClient(main_module.app)


def test_debug_tokenize_should_return_404_when_disabled() -> None:
    client = _new_client_with_debug_enabled(enabled=False)

    response = client.post("/debug/tokenize", json={"text": "データベース設計について"})

    assert response.status_code == 404
    config_module.get_settings.cache_clear()


def test_debug_tokenize_should_return_details_when_enabled() -> None:
    client = _new_client_with_debug_enabled(enabled=True)

    response = client.post(
        "/debug/tokenize",
        json={"text": "\uFF21\uFF29\u200b設計について\ufeff"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["original"] == "\uFF21\uFF29\u200b設計について\ufeff"
    assert body["normalized"].startswith("AI")
    assert body["sanitized"] == "AI設計について"
    assert body["detected_language"] in {"japanese", "chinese", "other"}
    assert isinstance(body["segments"], list)
    assert isinstance(body["tokens"], list)
    assert isinstance(body["sparse_output"], str)
    assert set(body.keys()) == {
        "original",
        "normalized",
        "sanitized",
        "detected_language",
        "segments",
        "sparse_output",
        "tokens",
    }
    if body["segments"]:
        segment = body["segments"][0]
        assert set(segment.keys()) == {"text", "is_cjk", "language"}
        assert isinstance(segment["text"], str)
        assert isinstance(segment["is_cjk"], bool)
        assert segment["language"] in {"japanese", "chinese", "other"}
    if body["tokens"]:
        token = body["tokens"][0]
        assert {"surface", "pos", "kept", "language"}.issubset(set(token.keys()))
        assert isinstance(token["surface"], str)
        assert isinstance(token["pos"], str)
        assert isinstance(token["kept"], bool)
        assert token["language"] in {"japanese", "chinese"}

    config_module.get_settings.cache_clear()
