from __future__ import annotations

import logging
from dataclasses import dataclass

from app.core.config import Settings
from app.database import Database
from app.database.repositories import NodeRepository, ReplacementJobRepository
from app.models import ReplacementJobState
from app.replacement.errors import ReplacementBusyError, ReplacementDeferredError
from app.replacement.orchestrator import ReplacementOrchestrator
from app.services.operational_settings import OperationalSettingsService

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ReplacementCycleResult:
    resumed_jobs: int
    triggered_jobs: int
    deferred_jobs: int
    failed_operations: int


class ReplacementWorker:
    """Crash-recovery worker for persisted replacement jobs.

    Active jobs are always resumed first. Automatic creation of new replacement jobs is disabled in
    DRY_RUN to avoid repeatedly simulating the same still-failed production node; dry-run jobs
    can be
    triggered explicitly through the service/control layer.
    """

    def __init__(
        self,
        database: Database,
        orchestrator: ReplacementOrchestrator,
        settings: Settings,
        operational_settings: OperationalSettingsService | None = None,
    ) -> None:
        self.database = database
        self.orchestrator = orchestrator
        self.settings = settings
        self.operational_settings = operational_settings

    async def run_cycle(self) -> ReplacementCycleResult:
        if self.operational_settings is not None:
            if await self.operational_settings.is_paused():
                return ReplacementCycleResult(0, 0, 0, 0)
            if not await self.operational_settings.replacement_enabled(
                default=self.settings.replacement_worker_enabled
            ):
                return ReplacementCycleResult(0, 0, 0, 0)

        resumed = 0
        triggered = 0
        deferred = 0
        failed = 0

        async with self.database.session() as session:
            active_jobs = await ReplacementJobRepository(session).list_active()
            active_ids = tuple(job.id for job in active_jobs)

        for job_id in active_ids:
            try:
                result = await self.orchestrator.resume(job_id)
                resumed += 1
                if result.deferred:
                    deferred += 1
            except (ReplacementBusyError, ReplacementDeferredError):
                deferred += 1
            except Exception:
                failed += 1
                logger.exception("replacement_worker_resume_failed", extra={"job_id": str(job_id)})

        effective_dry_run = (
            await self.operational_settings.effective_dry_run(self.settings)
            if self.operational_settings is not None
            else self.settings.dry_run
        )
        # Automatic repair never fires in DRY_RUN. Operators can still trigger an explicit safe
        # simulation, while monitoring continues to record real reachability state.
        if effective_dry_run or self.settings.replacement_emergency_stop:
            return ReplacementCycleResult(resumed, triggered, deferred, failed)

        async with self.database.session() as session:
            failed_nodes = await NodeRepository(session).list_auto_repair_failed(limit=100)
            jobs = ReplacementJobRepository(session)
            eligible_nodes = []
            for node in failed_nodes:
                latest = await jobs.latest_for_node(node.id)
                if latest is not None and latest.state in {
                    ReplacementJobState.FAILED,
                    ReplacementJobState.CANCELLED,
                }:
                    # A bounded job must not become an unbounded series of fresh jobs. Operators may
                    # explicitly trigger a new job after fixing the root cause.
                    continue
                eligible_nodes.append(node)
                if len(eligible_nodes) >= self.settings.max_concurrent_replacements:
                    break

        for node in eligible_nodes:
            try:
                job_id = await self.orchestrator.trigger(node.id)
                triggered += 1
                result = await self.orchestrator.resume(job_id)
                if result.deferred:
                    deferred += 1
            except ReplacementBusyError:
                deferred += 1
                break
            except ReplacementDeferredError:
                deferred += 1
            except Exception:
                failed += 1
                logger.exception(
                    "replacement_worker_trigger_failed", extra={"node_id": str(node.id)}
                )

        return ReplacementCycleResult(resumed, triggered, deferred, failed)
