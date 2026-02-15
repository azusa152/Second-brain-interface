"""Debouncer that groups rapid file-system events into a single callback."""

import threading
from collections.abc import Callable

from backend.domain.constants import DEBOUNCE_SECONDS
from backend.logging_config import get_logger

logger = get_logger(__name__)


class Debouncer:
    """Coalesce rapid events per key into a single callback after a quiet period.

    When `trigger(key)` is called, the callback is scheduled to run after
    `delay` seconds. If `trigger(key)` is called again before the timer
    fires, the timer resets. This prevents rapid saves from causing
    multiple re-index operations.
    """

    def __init__(
        self,
        callback: Callable[[str], None],
        delay: float = DEBOUNCE_SECONDS,
    ) -> None:
        self._callback = callback
        self._delay = delay
        self._timers: dict[str, threading.Timer] = {}
        self._lock = threading.Lock()

    def trigger(self, key: str) -> None:
        """Schedule (or reschedule) the callback for the given key."""
        with self._lock:
            existing = self._timers.get(key)
            if existing is not None:
                existing.cancel()
                logger.debug("Debounce reset for: %s", key)

            timer = threading.Timer(self._delay, self._fire, args=(key,))
            timer.daemon = True
            self._timers[key] = timer
            timer.start()

    def _fire(self, key: str) -> None:
        """Execute the callback and clean up the timer entry."""
        with self._lock:
            self._timers.pop(key, None)

        logger.info("Debounce fired for: %s", key)
        try:
            self._callback(key)
        except Exception:
            logger.exception("Debounce callback failed for: %s", key)

    def cancel_all(self) -> None:
        """Cancel all pending timers. Called during shutdown."""
        with self._lock:
            for timer in self._timers.values():
                timer.cancel()
            self._timers.clear()
        logger.info("All debounce timers cancelled")

    @property
    def pending_count(self) -> int:
        """Return the number of keys with pending timers."""
        with self._lock:
            return len(self._timers)
