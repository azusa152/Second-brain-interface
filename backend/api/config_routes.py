import os

from fastapi import APIRouter

from backend.config import get_settings
from backend.domain.models import VaultConfig

router = APIRouter(prefix="/config", tags=["config"])


def _derive_vault_name(path_value: str) -> str:
    """Derive vault name from path-like input across host/container separators."""
    normalized_path = path_value.strip().rstrip("/\\")
    if not normalized_path:
        return ""
    return os.path.basename(normalized_path.replace("\\", "/"))


@router.get("/vault", response_model=VaultConfig, summary="Get Obsidian vault configuration")
def get_vault_config() -> VaultConfig:
    """Return the vault name used for Obsidian deep links."""
    settings = get_settings()
    explicit_vault_name = settings.obsidian_vault_name.strip()
    if explicit_vault_name:
        return VaultConfig(vault_name=explicit_vault_name, is_configured=True)

    host_derived_name = _derive_vault_name(settings.obsidian_host_vault_path)
    if host_derived_name:
        return VaultConfig(vault_name=host_derived_name, is_configured=True)

    normalized_path = settings.obsidian_vault_path.strip().rstrip("/\\")
    derived_name = os.path.basename(normalized_path) if normalized_path else ""
    if derived_name and os.path.isdir(normalized_path):
        return VaultConfig(vault_name=derived_name, is_configured=True)

    return VaultConfig(
        vault_name="",
        is_configured=False,
        message=(
            "Obsidian deep links are unavailable. Set OBSIDIAN_VAULT_NAME or "
            "configure OBSIDIAN_VAULT_PATH to a valid vault directory."
        ),
    )
