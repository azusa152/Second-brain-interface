from fastapi.testclient import TestClient


def test_root_should_redirect_to_dashboard(client: TestClient) -> None:
    # Arrange / Act
    response = client.get("/", follow_redirects=False)

    # Assert
    assert response.status_code == 307


def test_root_redirect_should_point_to_dashboard_url(client: TestClient) -> None:
    # Arrange / Act
    response = client.get("/", follow_redirects=False)

    # Assert
    assert response.headers["location"] == "/dashboard/"
