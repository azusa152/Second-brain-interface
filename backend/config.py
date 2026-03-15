"""Centralised application settings backed by pydantic-settings.

All environment variables are read here. Callers should import ``get_settings``
and access configuration via the returned ``Settings`` instance rather than
calling ``os.getenv`` directly.
"""

import logging
from functools import lru_cache
from typing import Any

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from backend.domain.constants import (
    POLLING_INTERVAL_MIN_SECONDS,
    POLLING_INTERVAL_SECONDS,
    REBUILD_CRON_HOUR,
    REBUILD_CRON_MINUTE,
)

_logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """Application-wide configuration derived from environment variables.

    A ``.env`` file in the working directory is loaded automatically when
    present, but environment variables always take precedence.

    Invalid numeric values for cron and interval fields are logged as warnings
    and replaced with their defaults rather than raising a validation error, to
    preserve the graceful degradation behaviour of the original implementation.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Vault
    obsidian_vault_path: str = "/vault"
    obsidian_vault_name: str = ""

    # Qdrant
    qdrant_url: str = "http://localhost:6333"

    # File watcher
    use_polling_observer: bool = False
    polling_interval_seconds: float = POLLING_INTERVAL_SECONDS

    # Persistence
    hash_registry_data_path: str = "/data"

    # Scheduler
    scheduled_rebuild_enabled: bool = True
    startup_incremental_rebuild: bool = True
    rebuild_cron_hour: int = REBUILD_CRON_HOUR
    rebuild_cron_minute: int = REBUILD_CRON_MINUTE

    # Intent classification — comma-separated keyword overrides (empty → use defaults)
    intent_personal_keywords: str = ""

    @field_validator("polling_interval_seconds", mode="before")
    @classmethod
    def _coerce_polling_interval(cls, v: Any) -> float:
        try:
            parsed = float(v)
        except (ValueError, TypeError):
            _logger.warning(
                "Invalid POLLING_INTERVAL_SECONDS value %r; using default %.1fs",
                v,
                POLLING_INTERVAL_SECONDS,
            )
            return POLLING_INTERVAL_SECONDS
        if parsed < POLLING_INTERVAL_MIN_SECONDS:
            _logger.warning(
                "POLLING_INTERVAL_SECONDS %.2f is below minimum %.2fs; clamping to minimum",
                parsed,
                POLLING_INTERVAL_MIN_SECONDS,
            )
            return POLLING_INTERVAL_MIN_SECONDS
        return parsed

    @field_validator("rebuild_cron_hour", mode="before")
    @classmethod
    def _coerce_cron_hour(cls, v: Any) -> int:
        try:
            return int(v)
        except (ValueError, TypeError):
            _logger.warning(
                "Invalid REBUILD_CRON_HOUR value %r; using default %d", v, REBUILD_CRON_HOUR
            )
            return REBUILD_CRON_HOUR

    @field_validator("rebuild_cron_minute", mode="before")
    @classmethod
    def _coerce_cron_minute(cls, v: Any) -> int:
        try:
            return int(v)
        except (ValueError, TypeError):
            _logger.warning(
                "Invalid REBUILD_CRON_MINUTE value %r; using default %d", v, REBUILD_CRON_MINUTE
            )
            return REBUILD_CRON_MINUTE


@lru_cache
def get_settings() -> Settings:
    """Return the cached application settings singleton."""
    return Settings()
