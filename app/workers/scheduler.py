from __future__ import annotations

from typing import Any

from app.core.config import Settings
from app.workers.monitoring import MonitoringWorker
from app.workers.replacement import ReplacementWorker


class SystemWorkerScheduler:
    """Single-process APScheduler wiring; workers retain all business rules and DB leases."""

    def __init__(
        self,
        settings: Settings,
        monitoring: MonitoringWorker,
        replacement: ReplacementWorker,
    ) -> None:
        self.settings = settings
        self.monitoring = monitoring
        self.replacement = replacement
        self._scheduler: Any = None

    def start(self) -> None:
        if self._scheduler is not None:
            return
        from apscheduler.schedulers.asyncio import AsyncIOScheduler

        scheduler = AsyncIOScheduler(timezone="UTC")
        # Both lightweight cycles stay scheduled while the worker process is enabled. Persisted
        # runtime switches decide whether each cycle actually does work, allowing Telegram to
        # enable/disable monitoring and automatic repair without recreating containers.
        scheduler.add_job(
            self.monitoring.run_cycle,
            "interval",
            seconds=self.settings.check_interval_seconds,
            id="aso-monitoring-cycle",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )
        scheduler.add_job(
            self.replacement.run_cycle,
            "interval",
            seconds=self.settings.replacement_worker_interval_seconds,
            id="aso-replacement-cycle",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )
        scheduler.start()
        self._scheduler = scheduler

    def shutdown(self) -> None:
        if self._scheduler is None:
            return
        self._scheduler.shutdown(wait=False)
        self._scheduler = None
