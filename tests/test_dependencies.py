"""Tests for environment variable parsing in backend.api.dependencies."""

import os
from unittest.mock import patch

import pytest

from backend.api.dependencies import _parse_watcher_config, get_scheduler, set_scheduler
from backend.domain.constants import POLLING_INTERVAL_SECONDS, REBUILD_CRON_HOUR, REBUILD_CRON_MINUTE


class TestParseWatcherConfig:
    def test_defaults_when_env_vars_unset(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("USE_POLLING_OBSERVER", None)
            os.environ.pop("POLLING_INTERVAL_SECONDS", None)

            use_polling, polling_interval = _parse_watcher_config()

        assert use_polling is False
        assert polling_interval == POLLING_INTERVAL_SECONDS

    @pytest.mark.parametrize("value", ["true", "True", "TRUE"])
    def test_use_polling_is_true_for_truthy_values(self, value: str) -> None:
        with patch.dict(os.environ, {"USE_POLLING_OBSERVER": value}):
            use_polling, _ = _parse_watcher_config()
        assert use_polling is True

    @pytest.mark.parametrize("value", ["false", "False", "FALSE", "0", ""])
    def test_use_polling_is_false_for_non_true_values(self, value: str) -> None:
        with patch.dict(os.environ, {"USE_POLLING_OBSERVER": value}):
            use_polling, _ = _parse_watcher_config()
        assert use_polling is False

    def test_valid_polling_interval_is_parsed(self) -> None:
        with patch.dict(os.environ, {"POLLING_INTERVAL_SECONDS": "7.5"}):
            _, polling_interval = _parse_watcher_config()
        assert polling_interval == pytest.approx(7.5)

    def test_invalid_polling_interval_falls_back_to_default(self) -> None:
        with patch.dict(os.environ, {"POLLING_INTERVAL_SECONDS": "not-a-number"}):
            _, polling_interval = _parse_watcher_config()
        assert polling_interval == POLLING_INTERVAL_SECONDS

    def test_empty_polling_interval_falls_back_to_default(self) -> None:
        with patch.dict(os.environ, {"POLLING_INTERVAL_SECONDS": ""}):
            _, polling_interval = _parse_watcher_config()
        assert polling_interval == POLLING_INTERVAL_SECONDS


class TestGetScheduler:
    """Tests for get_scheduler() env var parsing and memoization."""

    def setup_method(self) -> None:
        """Reset the scheduler singleton before each test."""
        set_scheduler(None)

    def teardown_method(self) -> None:
        """Reset the scheduler singleton after each test."""
        set_scheduler(None)

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
        # Now env var is unset/reset, but memoized state should still return None
        with patch.dict(os.environ, {"SCHEDULED_REBUILD_ENABLED": "true"}):
            second = get_scheduler()
        assert first is None
        assert second is None  # memoized as disabled

    def test_set_scheduler_resets_disabled_flag(self) -> None:
        """set_scheduler() must clear the disabled flag so future calls work correctly."""
        with patch.dict(os.environ, {"SCHEDULED_REBUILD_ENABLED": "false"}):
            get_scheduler()  # memoize disabled

        set_scheduler(None)  # reset both singleton and disabled flag

        # After reset, a new call with enabled=true should be able to create scheduler
        # (we can't easily instantiate a real Scheduler without DI, so just verify
        # the disabled flag was cleared by checking get_scheduler is re-entered)
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
