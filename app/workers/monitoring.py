from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from app.core.config import Settings
from app.database import Database
from app.database.repositories import EventRepository, NodeCheckRepository, NodeRepository
from app.models import Event, EventSeverity, EventType, NodeCheck, NodeCheckOutcome
from app.monitoring.check_host import CheckHostClient, CheckHostError
from app.monitoring.health import MonitoringPolicy, NodeHealthCalculator, ReachabilityEvaluator
from app.monitoring.types import CheckHostSummary, ReachabilityDecision
from app.services.operational_settings import OperationalSettingsService

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class MonitoringCycleResult:
    total_nodes: int
    checked_nodes: int
    skipped_nodes: int
    error_nodes: int


class MonitoringWorker:
    """Runs persisted Check-Host monitoring with a per-node database lease."""

    def __init__(
        self,
        database: Database,
        check_host: CheckHostClient,
        settings: Settings,
        operational_settings: OperationalSettingsService | None = None,
    ) -> None:
        self.database = database
        self.check_host = check_host
        self.settings = settings
        self.operational_settings = operational_settings
        self.policy = MonitoringPolicy(
            failure_threshold=settings.failure_threshold,
            recovery_threshold=settings.recovery_threshold,
            min_success_nodes=settings.check_host_min_success_nodes,
        )
        self.health_calculator = NodeHealthCalculator(self.policy)

    async def run_cycle(self) -> MonitoringCycleResult:
        if self.operational_settings is not None:
            if await self.operational_settings.is_paused():
                return MonitoringCycleResult(0, 0, 0, 0)
            if not await self.operational_settings.monitoring_enabled(
                default=self.settings.monitoring_scheduler_enabled
            ):
                return MonitoringCycleResult(0, 0, 0, 0)

        async with self.database.session() as session:
            nodes = await NodeRepository(session).list_monitoring_enabled()
            node_ids = tuple(node.id for node in nodes)

        if not node_ids:
            return MonitoringCycleResult(0, 0, 0, 0)

        try:
            check_nodes = await self.check_host.resolve_nodes(
                configured_nodes=self.settings.check_host_nodes,
                country_code=self.settings.check_host_country_code,
                max_nodes=self.settings.check_host_max_nodes,
            )
        except CheckHostError:
            logger.exception("check_host_node_resolution_failed")
            return MonitoringCycleResult(len(node_ids), 0, 0, len(node_ids))

        checked = 0
        skipped = 0
        errors = 0
        for node_id in node_ids:
            status = await self.run_node(node_id, check_nodes=check_nodes)
            if status == "checked":
                checked += 1
            elif status == "skipped":
                skipped += 1
            else:
                errors += 1
        return MonitoringCycleResult(len(node_ids), checked, skipped, errors)

    async def run_node(self, node_id: UUID, *, check_nodes: tuple[str, ...] | None = None) -> str:
        if self.operational_settings is not None and await self.operational_settings.is_paused():
            return "skipped"

        now = datetime.now(UTC)
        lease_token = uuid4().hex
        lease_until = now + timedelta(seconds=self.settings.monitoring_lease_seconds)

        async with self.database.session() as session:
            repository = NodeRepository(session)
            acquired = await repository.try_acquire_monitoring_lease(
                node_id,
                token=lease_token,
                now=now,
                lease_until=lease_until,
            )
            await session.commit()
        if not acquired:
            return "skipped"

        try:
            selected_nodes = check_nodes or await self.check_host.resolve_nodes(
                configured_nodes=self.settings.check_host_nodes,
                country_code=self.settings.check_host_country_code,
                max_nodes=self.settings.check_host_max_nodes,
            )
            await self._check_and_persist(node_id, selected_nodes)
            return "checked"
        except CheckHostError as exc:
            logger.warning("monitoring_check_host_error", extra={"node_id": str(node_id)})
            await self._persist_adapter_error(node_id, exc)
            return "error"
        except Exception:
            logger.exception("monitoring_unexpected_error", extra={"node_id": str(node_id)})
            return "error"
        finally:
            async with self.database.session() as session:
                await NodeRepository(session).release_monitoring_lease(node_id, token=lease_token)
                await session.commit()

    async def _check_and_persist(self, node_id: UUID, check_nodes: tuple[str, ...]) -> None:
        async with self.database.session() as session:
            node = await NodeRepository(session).get(node_id)
            if node is None:
                return
            host = node.current_host
            port = node.current_port

        request = await self.check_host.create_tcp_check(host, port, nodes=check_nodes)
        summary = await self.check_host.poll_result(
            request,
            timeout_seconds=self.settings.check_host_result_timeout_seconds,
            poll_interval_seconds=self.settings.check_host_poll_interval_seconds,
        )
        decision = ReachabilityEvaluator.evaluate(
            summary,
            min_success_nodes=self.policy.min_success_nodes,
        )
        timestamp = datetime.now(UTC)

        async with self.database.session() as session:
            node_repo = NodeRepository(session)
            node = await node_repo.get(node_id)
            if node is None:
                return
            result = self.health_calculator.apply(node, decision, occurred_at=timestamp)
            await NodeCheckRepository(session).add(
                self._build_check(node_id, host, port, summary, decision, timestamp)
            )
            if result.event_type is not None:
                severity = (
                    EventSeverity.ERROR
                    if result.event_type is EventType.NODE_FAILED
                    else EventSeverity.WARNING
                    if result.event_type is EventType.NODE_DEGRADED
                    else EventSeverity.INFO
                )
                await EventRepository(session).add(
                    Event(
                        node_id=node_id,
                        replacement_job_id=None,
                        event_type=result.event_type,
                        severity=severity,
                        message=(
                            f"Node health changed: {result.previous_state.value} -> "
                            f"{result.current_state.value}"
                        ),
                        payload={
                            "decision": decision.value,
                            "success_count": summary.success_count,
                            "failure_count": summary.failure_count,
                            "total_nodes": summary.total_nodes,
                            "previous_state": result.previous_state.value,
                            "current_state": result.current_state.value,
                            "consecutive_failures": node.consecutive_failures,
                            "consecutive_successes": node.consecutive_successes,
                            "operation_mode": (
                                node.operation_mode.value if node.operation_mode is not None else None
                            ),
                        },
                        created_at=timestamp,
                    )
                )
            await session.commit()

    async def _persist_adapter_error(self, node_id: UUID, exc: CheckHostError) -> None:
        timestamp = datetime.now(UTC)
        async with self.database.session() as session:
            node = await NodeRepository(session).get(node_id)
            if node is None:
                return
            node.last_checked_at = timestamp
            await NodeCheckRepository(session).add(
                NodeCheck(
                    node_id=node_id,
                    request_id=None,
                    target_host=node.current_host,
                    target_port=node.current_port,
                    outcome=NodeCheckOutcome.ERROR,
                    success_count=0,
                    failure_count=0,
                    pending_count=0,
                    malformed_count=0,
                    total_nodes=0,
                    details=None,
                    error_code="check_host_error",
                    error_message=str(exc),
                    checked_at=timestamp,
                    completed_at=timestamp,
                )
            )
            await EventRepository(session).add(
                Event(
                    node_id=node_id,
                    replacement_job_id=None,
                    event_type=EventType.MONITORING_CHECK_ERROR,
                    severity=EventSeverity.WARNING,
                    message="Check-Host monitoring request failed; node health counters unchanged",
                    payload=None,
                    created_at=timestamp,
                )
            )
            await session.commit()

    @staticmethod
    def _build_check(
        node_id: UUID,
        host: str,
        port: int,
        summary: CheckHostSummary,
        decision: ReachabilityDecision,
        timestamp: datetime,
    ) -> NodeCheck:
        outcome = {
            ReachabilityDecision.REACHABLE: NodeCheckOutcome.REACHABLE,
            ReachabilityDecision.UNREACHABLE: NodeCheckOutcome.UNREACHABLE,
            ReachabilityDecision.INDETERMINATE: NodeCheckOutcome.INDETERMINATE,
        }[decision]
        return NodeCheck(
            node_id=node_id,
            request_id=summary.request_id,
            target_host=host,
            target_port=port,
            outcome=outcome,
            success_count=summary.success_count,
            failure_count=summary.failure_count,
            pending_count=summary.pending_count,
            malformed_count=summary.malformed_count,
            total_nodes=summary.total_nodes,
            details={
                "target": summary.target,
                "probes": [
                    {
                        "node": probe.node,
                        "status": probe.status.value,
                        "latency_seconds": probe.latency_seconds,
                        "address": probe.address,
                        "error": probe.error,
                    }
                    for probe in summary.probes
                ],
            },
            checked_at=timestamp,
            completed_at=timestamp,
        )
