"""Thread-safe ring buffer for watcher events."""

import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone

from backend.domain.constants import EVENT_LOG_MAXLEN


@dataclass(frozen=True)
class WatcherEvent:
    """A single file-watcher event."""

    event_type: str  # "created", "modified", "deleted", "moved"
    file_path: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))
    dest_path: str | None = None


class EventLog:
    """Thread-safe ring buffer that stores the most recent watcher events."""

    def __init__(self, maxlen: int = EVENT_LOG_MAXLEN) -> None:
        self._buffer: deque[WatcherEvent] = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def record(self, event: WatcherEvent) -> None:
        """Append an event to the ring buffer."""
        with self._lock:
            self._buffer.append(event)

    def get_recent(self, limit: int = 50) -> list[WatcherEvent]:
        """Return the most recent events, newest first."""
        with self._lock:
            items = list(self._buffer)
        # Return newest-first, capped at limit
        return list(reversed(items))[:limit]
