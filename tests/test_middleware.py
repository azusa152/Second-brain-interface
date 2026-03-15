import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.middleware import AccessLogMiddleware, RequestIDMiddleware
from backend.logging_config import setup_logging


def _build_test_app(request_id_header: str = "X-Request-ID") -> FastAPI:
    app = FastAPI()
    app.add_middleware(AccessLogMiddleware, skip_paths={"/health"})
    app.add_middleware(RequestIDMiddleware, header_name=request_id_header)

    @app.get("/hello")
    def hello() -> dict[str, str]:
        return {"ok": "true"}

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


def test_request_id_middleware_should_generate_response_header() -> None:
    # Arrange
    app = _build_test_app()
    client = TestClient(app)

    # Act
    response = client.get("/hello")

    # Assert
    assert response.status_code == 200
    assert response.headers["X-Request-ID"]


def test_request_id_middleware_should_propagate_incoming_header() -> None:
    # Arrange
    app = _build_test_app()
    client = TestClient(app)

    # Act
    response = client.get("/hello", headers={"X-Request-ID": "req-123"})

    # Assert
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "req-123"


def test_request_id_middleware_should_support_custom_header_name() -> None:
    # Arrange
    app = _build_test_app(request_id_header="X-Correlation-ID")
    client = TestClient(app)

    # Act
    response = client.get("/hello", headers={"X-Correlation-ID": "corr-123"})

    # Assert
    assert response.status_code == 200
    assert response.headers["X-Correlation-ID"] == "corr-123"


def test_request_id_middleware_should_not_duplicate_header_if_already_present() -> None:
    # Arrange
    app = _build_test_app()
    client = TestClient(app)

    # Act
    response = client.get("/hello", headers={"X-Request-ID": "req-dup"})

    # Assert
    assert response.status_code == 200
    header_values = response.headers.get_list("X-Request-ID")
    assert header_values == ["req-dup"]


def test_access_log_middleware_should_log_http_request_with_context(capsys) -> None:
    # Arrange
    setup_logging(log_level="INFO", json_output=True)
    app = _build_test_app()
    client = TestClient(app)

    # Act
    response = client.get("/hello", headers={"X-Request-ID": "req-456"})
    captured = capsys.readouterr()

    # Assert
    assert response.status_code == 200
    log_lines = [
        json.loads(line)
        for line in captured.out.splitlines()
        if line.strip() and line.lstrip().startswith("{")
    ]
    request_logs = [line for line in log_lines if line.get("event") == "http_request"]
    assert request_logs
    access_event = request_logs[-1]
    assert access_event["method"] == "GET"
    assert access_event["path"] == "/hello"
    assert access_event["status_code"] == 200
    assert access_event["request_id"] == "req-456"
    assert "duration_ms" in access_event


def test_access_log_middleware_should_skip_health_endpoint(capsys) -> None:
    # Arrange
    setup_logging(log_level="INFO", json_output=True)
    app = _build_test_app()
    client = TestClient(app)

    # Act
    response = client.get("/health", headers={"X-Request-ID": "req-health"})
    captured = capsys.readouterr()

    # Assert
    assert response.status_code == 200
    log_lines = [
        json.loads(line)
        for line in captured.out.splitlines()
        if line.strip() and line.lstrip().startswith("{")
    ]
    request_logs = [line for line in log_lines if line.get("event") == "http_request"]
    assert all(line.get("path") != "/health" for line in request_logs)
