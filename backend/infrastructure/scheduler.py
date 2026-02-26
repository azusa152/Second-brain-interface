"""APScheduler wrapper for daily incremental vault rebuild."""

import asyncio
from collections.abc import Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from backend.logging_config import get_logger

logger = get_logger(__name__)


class Scheduler:
    """Thin wrapper around APScheduler's AsyncIOScheduler.

    The job_fn is a synchronous blocking function (IndexService.incremental_rebuild).
    It is run in the default thread pool executor so the asyncio event loop is
    never blocked during a rebuild.
    """

    def __init__(self, cron_hour: int, cron_minute: int, job_fn: Callable) -> None:
        self._job_fn = job_fn
        self._cron_hour = cron_hour
        self._cron_minute = cron_minute
        self._scheduler = AsyncIOScheduler()
        self._scheduler.add_job(
            self._run_job,
            CronTrigger(hour=cron_hour, minute=cron_minute),
            id="incremental_rebuild",
            replace_existing=True,
        )

    async def _run_job(self) -> None:
        """Run the synchronous job_fn in a thread pool to avoid blocking the event loop."""
        logger.info(
            "Scheduler: triggering incremental rebuild (cron %02d:%02d)",
            self._cron_hour,
            self._cron_minute,
        )
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._job_fn)

    async def start(self) -> None:
        """Start the scheduler. No-op if already running."""
        if self._scheduler.running:
            return
        self._scheduler.start()
        logger.info(
            "Scheduler started: daily incremental rebuild at %02d:%02d UTC",
            self._cron_hour,
            self._cron_minute,
        )

    async def stop(self) -> None:
        """Shut down the scheduler gracefully. No-op if not running."""
        if not self._scheduler.running:
            return
        self._scheduler.shutdown(wait=True)
        logger.info("Scheduler stopped")
