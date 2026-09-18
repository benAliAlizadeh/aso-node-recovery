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
        if not self.settings.worker_scheduler_enabled:
            raise RuntimeError("ASO_WORKER_SCHEDULER_ENABLED must be true to start workers")

        from apscheduler.schedulers.asyncio import AsyncIOScheduler

        scheduler = AsyncIOScheduler(timezone="UTC")
        if self.settings.monitoring_scheduler_enabled:
            scheduler.add_job(
                self.monitoring.run_cycle,
                "interval",
                seconds=self.settings.check_interval_seconds,
                id="aso-monitoring-cycle",
                replace_existing=True,
                coalesce=True,
                max_instances=1,
            )
        if self.settings.replacement_worker_enabled:
            scheduler.add_job(
                self.replacement.run_cycle,
                "interval",
                seconds=self.settings.replacement_worker_interval_seconds,
                id="aso-replacement-cycle",
                replace_existing=True,
                coalesce=True,
                max_instances=1,
            )
        if not scheduler.get_jobs():
            raise RuntimeError("no worker is enabled; enable monitoring and/or replacement worker")
        scheduler.start()
        self._scheduler = scheduler

    def shutdown(self) -> None:
        if self._scheduler is None:
            return
        self._scheduler.shutdown(wait=False)
        self._scheduler = None
