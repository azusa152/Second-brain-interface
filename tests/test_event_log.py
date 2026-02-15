from datetime import timezone

import pytest

from backend.infrastructure.event_log import EventLog, WatcherEvent


class TestEventLogRecord:
    def test_record_should_store_event(self) -> None:
        log = EventLog()

        log.record(WatcherEvent(event_type="created", file_path="note.md"))

        events = log.get_recent()
        assert len(events) == 1
        assert events[0].event_type == "created"
        assert events[0].file_path == "note.md"

    def test_record_should_auto_set_timestamp(self) -> None:
        log = EventLog()

        log.record(WatcherEvent(event_type="modified", file_path="note.md"))

        events = log.get_recent()
        assert events[0].timestamp.tzinfo == timezone.utc

    def test_record_should_preserve_dest_path_for_moves(self) -> None:
        log = EventLog()

        log.record(
            WatcherEvent(
                event_type="moved", file_path="old.md", dest_path="new.md"
            )
        )

        events = log.get_recent()
        assert events[0].dest_path == "new.md"

    def test_record_should_default_dest_path_to_none(self) -> None:
        log = EventLog()

        log.record(WatcherEvent(event_type="deleted", file_path="gone.md"))

        assert log.get_recent()[0].dest_path is None


class TestEventLogGetRecent:
    def test_get_recent_should_return_newest_first(self) -> None:
        log = EventLog()
        log.record(WatcherEvent(event_type="created", file_path="first.md"))
        log.record(WatcherEvent(event_type="modified", file_path="second.md"))
        log.record(WatcherEvent(event_type="deleted", file_path="third.md"))

        events = log.get_recent()

        assert events[0].file_path == "third.md"
        assert events[1].file_path == "second.md"
        assert events[2].file_path == "first.md"

    def test_get_recent_should_respect_limit(self) -> None:
        log = EventLog()
        for i in range(10):
            log.record(WatcherEvent(event_type="modified", file_path=f"note{i}.md"))

        events = log.get_recent(limit=3)

        assert len(events) == 3
        assert events[0].file_path == "note9.md"

    def test_get_recent_should_return_empty_list_when_no_events(self) -> None:
        log = EventLog()

        assert log.get_recent() == []


class TestEventLogRingBuffer:
    def test_ring_buffer_should_evict_oldest_when_full(self) -> None:
        log = EventLog(maxlen=3)
        for i in range(5):
            log.record(WatcherEvent(event_type="modified", file_path=f"note{i}.md"))

        events = log.get_recent(limit=10)

        assert len(events) == 3
        # Oldest two (note0, note1) should be evicted
        paths = [e.file_path for e in events]
        assert "note0.md" not in paths
        assert "note1.md" not in paths
        assert events[0].file_path == "note4.md"

    def test_ring_buffer_should_use_constant_default_maxlen(self) -> None:
        from backend.domain.constants import EVENT_LOG_MAXLEN

        log = EventLog()

        assert log._buffer.maxlen == EVENT_LOG_MAXLEN


class TestWatcherEventImmutability:
    def test_watcher_event_should_be_frozen(self) -> None:
        event = WatcherEvent(event_type="created", file_path="note.md")
        with pytest.raises(AttributeError):
            event.file_path = "other.md"  # type: ignore[misc]
