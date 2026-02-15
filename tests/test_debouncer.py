"""Unit tests for the Debouncer."""

import threading
import time

from backend.infrastructure.debouncer import Debouncer


class TestDebouncerBasic:
    def test_debouncer_should_fire_callback_after_delay(self) -> None:
        results: list[str] = []
        event = threading.Event()

        def callback(key: str) -> None:
            results.append(key)
            event.set()

        debouncer = Debouncer(callback=callback, delay=0.1)
        debouncer.trigger("note.md")

        event.wait(timeout=2)
        assert results == ["note.md"]

    def test_debouncer_should_coalesce_rapid_triggers_into_one(self) -> None:
        results: list[str] = []
        event = threading.Event()

        def callback(key: str) -> None:
            results.append(key)
            event.set()

        debouncer = Debouncer(callback=callback, delay=0.2)

        # Trigger 5 times rapidly for the same key
        for _ in range(5):
            debouncer.trigger("note.md")
            time.sleep(0.03)

        event.wait(timeout=2)
        # Only one callback should have fired
        assert len(results) == 1
        assert results[0] == "note.md"

    def test_debouncer_should_handle_different_keys_independently(self) -> None:
        results: list[str] = []
        all_done = threading.Event()
        expected_count = 2

        def callback(key: str) -> None:
            results.append(key)
            if len(results) >= expected_count:
                all_done.set()

        debouncer = Debouncer(callback=callback, delay=0.1)
        debouncer.trigger("a.md")
        debouncer.trigger("b.md")

        all_done.wait(timeout=2)
        assert sorted(results) == ["a.md", "b.md"]

    def test_debouncer_should_reset_timer_on_retrigger(self) -> None:
        results: list[str] = []
        event = threading.Event()

        def callback(key: str) -> None:
            results.append(key)
            event.set()

        debouncer = Debouncer(callback=callback, delay=0.2)

        debouncer.trigger("note.md")
        time.sleep(0.1)
        # Re-trigger before the first timer fires
        debouncer.trigger("note.md")

        # Wait enough for the reset timer to fire
        event.wait(timeout=2)
        assert len(results) == 1


class TestDebouncerCancellation:
    def test_cancel_all_should_prevent_pending_callbacks(self) -> None:
        results: list[str] = []

        def callback(key: str) -> None:
            results.append(key)

        debouncer = Debouncer(callback=callback, delay=0.2)
        debouncer.trigger("note.md")
        debouncer.cancel_all()

        # Wait longer than the delay to confirm callback never fires
        time.sleep(0.4)
        assert results == []

    def test_cancel_all_should_clear_pending_count(self) -> None:
        debouncer = Debouncer(callback=lambda k: None, delay=1.0)
        debouncer.trigger("a.md")
        debouncer.trigger("b.md")

        assert debouncer.pending_count == 2
        debouncer.cancel_all()
        assert debouncer.pending_count == 0


class TestDebouncerEdgeCases:
    def test_pending_count_should_reflect_active_timers(self) -> None:
        event = threading.Event()

        def callback(key: str) -> None:
            event.set()

        debouncer = Debouncer(callback=callback, delay=0.1)
        assert debouncer.pending_count == 0

        debouncer.trigger("note.md")
        assert debouncer.pending_count == 1

        event.wait(timeout=2)
        # Small sleep to allow _fire to complete and remove from dict
        time.sleep(0.05)
        assert debouncer.pending_count == 0

    def test_debouncer_should_survive_callback_exception(self) -> None:
        results: list[str] = []
        second_done = threading.Event()

        call_count = 0

        def callback(key: str) -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("Intentional test error")
            results.append(key)
            second_done.set()

        debouncer = Debouncer(callback=callback, delay=0.1)

        # First trigger will raise — debouncer should not break
        debouncer.trigger("fail.md")
        time.sleep(0.2)

        # Second trigger should still work
        debouncer.trigger("ok.md")
        second_done.wait(timeout=2)
        assert results == ["ok.md"]
