from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.workers.monitoring import MonitoringWorker


class MonitoringScheduler:
    """Thin APScheduler adapter; business rules stay in MonitoringWorker."""

    def __init__(self, worker: MonitoringWorker, *, interval_seconds: int) -> None:
        self.worker = worker
        self.interval_seconds = interval_seconds
        self._scheduler: AsyncIOScheduler | None = None

    def start(self) -> None:
        if self._scheduler is not None:
            return
        try:
            from apscheduler.schedulers.asyncio import AsyncIOScheduler
        except ImportError as exc:  # pragma: no cover - dependency is required in installed package
            raise RuntimeError("APScheduler is required to start monitoring") from exc

        scheduler: Any = AsyncIOScheduler()
        scheduler.add_job(
            self.worker.run_cycle,
            "interval",
            seconds=self.interval_seconds,
            id="aso-monitoring-cycle",
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
