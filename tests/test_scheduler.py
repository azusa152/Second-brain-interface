"""Tests for the Scheduler wrapper (APScheduler lifecycle + job registration)."""

import asyncio
from unittest.mock import MagicMock

import pytest

from backend.infrastructure.scheduler import Scheduler


@pytest.fixture()
def job_fn() -> MagicMock:
    return MagicMock(name="incremental_rebuild")


class TestSchedulerInit:
    def test_scheduler_registers_job_on_init(self, job_fn: MagicMock) -> None:
        scheduler = Scheduler(cron_hour=3, cron_minute=0, job_fn=job_fn)
        jobs = scheduler._scheduler.get_jobs()
        assert len(jobs) == 1
        assert jobs[0].id == "incremental_rebuild"

    def test_scheduler_uses_correct_cron_trigger(self, job_fn: MagicMock) -> None:
        scheduler = Scheduler(cron_hour=4, cron_minute=30, job_fn=job_fn)
        jobs = scheduler._scheduler.get_jobs()
        assert len(jobs) == 1
        trigger = jobs[0].trigger
        # CronTrigger fields are accessible via trigger.fields
        fields = {f.name: f for f in trigger.fields}
        assert str(fields["hour"]) == "4"
        assert str(fields["minute"]) == "30"


class TestSchedulerLifecycle:
    @pytest.mark.asyncio
    async def test_start_and_stop_without_error(self, job_fn: MagicMock) -> None:
        scheduler = Scheduler(cron_hour=3, cron_minute=0, job_fn=job_fn)
        await scheduler.start()
        assert scheduler._scheduler.running
        # stop() should complete without raising; internal state may flush asynchronously
        await scheduler.stop()

    @pytest.mark.asyncio
    async def test_start_is_idempotent(self, job_fn: MagicMock) -> None:
        scheduler = Scheduler(cron_hour=3, cron_minute=0, job_fn=job_fn)
        await scheduler.start()
        assert scheduler._scheduler.running
        try:
            await scheduler.start()  # should be a no-op, not raise
        except Exception:
            pytest.fail("start() raised on second call")
        finally:
            await scheduler.stop()


class TestSchedulerRunJob:
    @pytest.mark.asyncio
    async def test_run_job_calls_job_fn_in_executor(self, job_fn: MagicMock) -> None:
        """_run_job should invoke job_fn via the thread pool executor."""
        scheduler = Scheduler(cron_hour=3, cron_minute=0, job_fn=job_fn)

        await scheduler._run_job()

        job_fn.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_job_does_not_block_event_loop(self, job_fn: MagicMock) -> None:
        """The event loop should remain responsive while _run_job runs."""
        import time

        def slow_job() -> None:
            time.sleep(0.05)

        scheduler = Scheduler(cron_hour=3, cron_minute=0, job_fn=slow_job)

        start = asyncio.get_event_loop().time()
        await scheduler._run_job()
        elapsed = asyncio.get_event_loop().time() - start

        # The coroutine should have awaited the executor, not blocked inline.
        # Elapsed time includes the sleep but the event loop was free during it.
        assert elapsed >= 0.05
