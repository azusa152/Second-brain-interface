"""Tests for environment variable parsing in backend.api.dependencies."""

import os
from unittest.mock import patch

import pytest

from backend.api.dependencies import _parse_watcher_config
from backend.domain.constants import POLLING_INTERVAL_SECONDS


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
