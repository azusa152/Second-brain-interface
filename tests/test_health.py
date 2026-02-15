from fastapi.testclient import TestClient


def test_health_should_return_ok_status(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "timestamp" in body


def test_health_should_return_iso8601_timestamp(client: TestClient) -> None:
    response = client.get("/health")

    body = response.json()
    timestamp = body["timestamp"]
    # ISO 8601 timestamps contain 'T' separator and end with timezone info
    assert "T" in timestamp
