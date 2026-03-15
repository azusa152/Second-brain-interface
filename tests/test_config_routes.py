from fastapi.testclient import TestClient

from backend import config as config_module


def test_vault_config_should_return_explicit_vault_name(
    client: TestClient, monkeypatch
) -> None:
    monkeypatch.setenv("OBSIDIAN_VAULT_NAME", "My Vault")
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", "/Users/test/ignored")
    config_module.get_settings.cache_clear()

    response = client.get("/config/vault")

    assert response.status_code == 200
    body = response.json()
    assert body["vault_name"] == "My Vault"
    assert body["is_configured"] is True
    assert body["message"] is None
    config_module.get_settings.cache_clear()


def test_vault_config_should_derive_name_from_vault_path(
    client: TestClient, monkeypatch, tmp_path
) -> None:
    vault_dir = tmp_path / "MySecondBrain"
    vault_dir.mkdir()
    monkeypatch.delenv("OBSIDIAN_VAULT_NAME", raising=False)
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(vault_dir))
    config_module.get_settings.cache_clear()

    response = client.get("/config/vault")

    assert response.status_code == 200
    body = response.json()
    assert body["vault_name"] == "MySecondBrain"
    assert body["is_configured"] is True
    assert body["message"] is None
    config_module.get_settings.cache_clear()


def test_vault_config_should_derive_name_from_host_vault_path_in_docker(
    client: TestClient, monkeypatch
) -> None:
    monkeypatch.delenv("OBSIDIAN_VAULT_NAME", raising=False)
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", "/vault")
    monkeypatch.setenv("OBSIDIAN_HOST_VAULT_PATH", "/Users/test/MyBrain")
    config_module.get_settings.cache_clear()

    response = client.get("/config/vault")

    assert response.status_code == 200
    body = response.json()
    assert body["vault_name"] == "MyBrain"
    assert body["is_configured"] is True
    assert body["message"] is None
    config_module.get_settings.cache_clear()


def test_vault_config_should_prefer_explicit_name_over_host_path(
    client: TestClient, monkeypatch
) -> None:
    monkeypatch.setenv("OBSIDIAN_VAULT_NAME", "ExplicitVault")
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", "/vault")
    monkeypatch.setenv("OBSIDIAN_HOST_VAULT_PATH", "/Users/test/HostDerivedVault")
    config_module.get_settings.cache_clear()

    response = client.get("/config/vault")

    assert response.status_code == 200
    body = response.json()
    assert body["vault_name"] == "ExplicitVault"
    assert body["is_configured"] is True
    assert body["message"] is None
    config_module.get_settings.cache_clear()


def test_vault_config_should_derive_name_from_windows_style_host_path(
    client: TestClient, monkeypatch
) -> None:
    monkeypatch.delenv("OBSIDIAN_VAULT_NAME", raising=False)
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", "/vault")
    monkeypatch.setenv("OBSIDIAN_HOST_VAULT_PATH", "C:\\Users\\test\\MyWindowsVault")
    config_module.get_settings.cache_clear()

    response = client.get("/config/vault")

    assert response.status_code == 200
    body = response.json()
    assert body["vault_name"] == "MyWindowsVault"
    assert body["is_configured"] is True
    assert body["message"] is None
    config_module.get_settings.cache_clear()


def test_vault_config_should_return_not_configured_for_nonexistent_path(
    client: TestClient, monkeypatch
) -> None:
    monkeypatch.delenv("OBSIDIAN_VAULT_NAME", raising=False)
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", "/path/that/does/not/exist")
    config_module.get_settings.cache_clear()

    response = client.get("/config/vault")

    assert response.status_code == 200
    body = response.json()
    assert body["vault_name"] == ""
    assert body["is_configured"] is False
    assert "OBSIDIAN_VAULT_PATH" in body["message"]
    config_module.get_settings.cache_clear()


def test_vault_config_should_return_not_configured_when_path_is_root(
    client: TestClient, monkeypatch
) -> None:
    monkeypatch.delenv("OBSIDIAN_VAULT_NAME", raising=False)
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", "/")
    config_module.get_settings.cache_clear()

    response = client.get("/config/vault")

    assert response.status_code == 200
    body = response.json()
    assert body["vault_name"] == ""
    assert body["is_configured"] is False
    assert "OBSIDIAN_VAULT_NAME" in body["message"]
    config_module.get_settings.cache_clear()
