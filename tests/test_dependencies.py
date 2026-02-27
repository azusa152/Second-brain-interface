"""Tests for settings parsing in backend.config and scheduler wiring in backend.api.dependencies."""

import os
from unittest.mock import patch

import pytest

from backend.api.dependencies import get_scheduler, set_scheduler
from backend.config import Settings, get_settings
from backend.domain.constants import (
    POLLING_INTERVAL_SECONDS,
    REBUILD_CRON_HOUR,
    REBUILD_CRON_MINUTE,
)


class TestSettingsWatcherConfig:
    """Tests for USE_POLLING_OBSERVER and POLLING_INTERVAL_SECONDS via Settings."""

    def test_defaults_are_applied(self) -> None:
        # Pass _env_file=None so the local .env file is not loaded; pure defaults only.
        settings = Settings(_env_file=None)  # type: ignore[call-arg]
        assert settings.use_polling_observer is False
        assert settings.polling_interval_seconds == POLLING_INTERVAL_SECONDS

    def test_use_polling_observer_can_be_set_to_true(self) -> None:
        settings = Settings(_env_file=None, use_polling_observer=True)  # type: ignore[call-arg]
        assert settings.use_polling_observer is True

    def test_polling_interval_accepts_float(self) -> None:
        settings = Settings(_env_file=None, polling_interval_seconds=7.5)  # type: ignore[call-arg]
        assert settings.polling_interval_seconds == pytest.approx(7.5)

    @pytest.mark.parametrize("value", ["true", "True", "TRUE", "1"])
    def test_use_polling_parsed_from_env_truthy(self, value: str) -> None:
        with patch.dict(os.environ, {"USE_POLLING_OBSERVER": value}):
            settings = Settings(_env_file=None)  # type: ignore[call-arg]
        assert settings.use_polling_observer is True

    @pytest.mark.parametrize("value", ["false", "False", "FALSE", "0"])
    def test_use_polling_parsed_from_env_falsy(self, value: str) -> None:
        with patch.dict(os.environ, {"USE_POLLING_OBSERVER": value}):
            settings = Settings(_env_file=None)  # type: ignore[call-arg]
        assert settings.use_polling_observer is False


class TestGetScheduler:
    """Tests for get_scheduler() env var parsing and memoization."""

    def setup_method(self) -> None:
        """Reset the scheduler singleton before each test."""
        set_scheduler(None)
        get_settings.cache_clear()

    def teardown_method(self) -> None:
        """Reset the scheduler singleton after each test."""
        set_scheduler(None)
        get_settings.cache_clear()

    def test_returns_none_when_disabled(self) -> None:
        with patch.dict(os.environ, {"SCHEDULED_REBUILD_ENABLED": "false"}):
            result = get_scheduler()
        assert result is None

    @pytest.mark.parametrize("value", ["false", "False", "FALSE", "0"])
    def test_disabled_for_non_true_values(self, value: str) -> None:
        with patch.dict(os.environ, {"SCHEDULED_REBUILD_ENABLED": value}):
            result = get_scheduler()
        assert result is None

    def test_disabled_state_is_memoized(self) -> None:
        """get_scheduler() should return None on subsequent calls without re-reading env var."""
        with patch.dict(os.environ, {"SCHEDULED_REBUILD_ENABLED": "false"}):
            first = get_scheduler()
        # Even with env var changed, the memoised disabled flag stays True
        with patch.dict(os.environ, {"SCHEDULED_REBUILD_ENABLED": "true"}):
            second = get_scheduler()
        assert first is None
        assert second is None  # memoised as disabled

    def test_set_scheduler_resets_disabled_flag(self) -> None:
        """set_scheduler() must clear the disabled flag so future calls work correctly."""
        with patch.dict(os.environ, {"SCHEDULED_REBUILD_ENABLED": "false"}):
            get_scheduler()  # memoize disabled

        set_scheduler(None)  # reset both singleton and disabled flag

        from backend.api import dependencies
        assert not dependencies._scheduler_disabled

    def test_invalid_cron_hour_falls_back_to_default(self) -> None:
        with (
            patch.dict(
                os.environ,
                {
                    "SCHEDULED_REBUILD_ENABLED": "true",
                    "REBUILD_CRON_HOUR": "not-a-number",
                    "REBUILD_CRON_MINUTE": "0",
                },
            ),
            patch("backend.api.dependencies.get_index_service") as mock_svc,
        ):
            mock_index = mock_svc.return_value
            mock_index.incremental_rebuild = lambda: None
            scheduler = get_scheduler()

        assert scheduler is not None
        jobs = scheduler._scheduler.get_jobs()
        fields = {f.name: f for f in jobs[0].trigger.fields}
        assert str(fields["hour"]) == str(REBUILD_CRON_HOUR)

    def test_invalid_cron_minute_falls_back_to_default(self) -> None:
        with (
            patch.dict(
                os.environ,
                {
                    "SCHEDULED_REBUILD_ENABLED": "true",
                    "REBUILD_CRON_HOUR": "3",
                    "REBUILD_CRON_MINUTE": "bad",
                },
            ),
            patch("backend.api.dependencies.get_index_service") as mock_svc,
        ):
            mock_index = mock_svc.return_value
            mock_index.incremental_rebuild = lambda: None
            scheduler = get_scheduler()

        assert scheduler is not None
        jobs = scheduler._scheduler.get_jobs()
        fields = {f.name: f for f in jobs[0].trigger.fields}
        assert str(fields["minute"]) == str(REBUILD_CRON_MINUTE)

    def test_valid_cron_overrides_are_forwarded(self) -> None:
        with (
            patch.dict(
                os.environ,
                {
                    "SCHEDULED_REBUILD_ENABLED": "true",
                    "REBUILD_CRON_HOUR": "6",
                    "REBUILD_CRON_MINUTE": "30",
                },
            ),
            patch("backend.api.dependencies.get_index_service") as mock_svc,
        ):
            mock_index = mock_svc.return_value
            mock_index.incremental_rebuild = lambda: None
            scheduler = get_scheduler()

        assert scheduler is not None
        jobs = scheduler._scheduler.get_jobs()
        fields = {f.name: f for f in jobs[0].trigger.fields}
        assert str(fields["hour"]) == "6"
        assert str(fields["minute"]) == "30"
