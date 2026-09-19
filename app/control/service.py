from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.core.config import Settings
from app.database import Database
from app.database.repositories import (
    EventRepository,
    NodeCheckRepository,
    NodeRepository,
    ProviderRepository,
    ReplacementJobRepository,
    VpsInstanceRepository,
)
from app.models import (
    Event,
    EventSeverity,
    EventType,
    NodeCheckOutcome,
    NodeOperationMode,
    NodeState,
    ReplacementCheckpoint,
    ReplacementJobState,
    ReplacementTriggerMode,
    RuntimeExecutionMode,
)
from app.replacement.orchestrator import ReplacementOrchestrator, ReplacementRunResult
from app.services.node_state import NodeStateMachine
from app.services.operational_settings import OperationalSettingsService, RuntimeControlSnapshot
from app.workers.monitoring import MonitoringWorker


@dataclass(frozen=True, slots=True)
class DashboardSnapshot:
    node_counts: dict[str, int]
    active_vps_count: int
    active_replacement_count: int
    paused: bool
    dry_run: bool
    real_mutation_allowed: bool


@dataclass(frozen=True, slots=True)
class NodeSnapshot:
    id: UUID
    name: str
    provider_id: UUID
    host: str
    port: int
    state: NodeState
    operation_mode: NodeOperationMode
    consecutive_failures: int
    last_successful_check_at: datetime | None


@dataclass(frozen=True, slots=True)
class NodeDetailSnapshot:
    node: NodeSnapshot
    master_node_id: str
    monitoring_enabled: bool
    last_checked_at: datetime | None
    latest_check_outcome: NodeCheckOutcome | None
    latest_check_at: datetime | None
    latest_job_id: UUID | None
    latest_job_state: ReplacementJobState | None
    latest_job_checkpoint: ReplacementCheckpoint | None


@dataclass(frozen=True, slots=True)
class JobSnapshot:
    id: UUID
    node_id: UUID
    state: ReplacementJobState
    checkpoint: ReplacementCheckpoint
    attempt_count: int
    max_attempts: int
    is_dry_run: bool
    active: bool
    created_at: datetime
    completed_at: datetime | None
    last_error_message: str | None
    trigger_mode: ReplacementTriggerMode = ReplacementTriggerMode.STANDARD


@dataclass(frozen=True, slots=True)
class ProviderSnapshot:
    id: UUID
    key: str
    display_name: str
    provider_type: str
    is_active: bool
    default_region: str | None
    default_server_type: str | None


@dataclass(frozen=True, slots=True)
class EventSnapshot:
    id: UUID
    node_id: UUID | None
    replacement_job_id: UUID | None
    event_type: EventType
    severity: EventSeverity
    message: str
    payload: dict[str, Any] | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class EventNotificationContext:
    node_id: UUID | None = None
    node_name: str | None = None
    provider_name: str | None = None
    provider_type: str | None = None
    vps_host: str | None = None
    target_host: str | None = None
    target_port: int | None = None
    state: NodeState | None = None
    operation_mode: NodeOperationMode | None = None
    consecutive_failures: int | None = None
    consecutive_successes: int | None = None
    replacement_job_id: UUID | None = None
    trigger_mode: ReplacementTriggerMode | None = None
    is_dry_run: bool | None = None


class ControlService:
    """Application service used by Telegram/UI layers.

    Telegram handlers remain presentation-only. All database reads, manual checks, replacement
    actions, provider toggles, pause/resume, and audit writes are centralized here.
    """

    def __init__(
        self,
        database: Database,
        settings: Settings,
        monitoring: MonitoringWorker,
        orchestrator: ReplacementOrchestrator,
        operational_settings: OperationalSettingsService,
    ) -> None:
        self.database = database
        self.settings = settings
        self.monitoring = monitoring
        self.orchestrator = orchestrator
        self.operational_settings = operational_settings

    async def dashboard(self) -> DashboardSnapshot:
        async with self.database.session() as session:
            node_counts = await NodeRepository(session).count_by_state()
            active_vps = await VpsInstanceRepository(session).count_active()
            active_jobs = await ReplacementJobRepository(session).count_active()
        controls = await self.operational_settings.snapshot(self.settings)
        return DashboardSnapshot(
            node_counts=node_counts,
            active_vps_count=active_vps,
            active_replacement_count=active_jobs,
            paused=controls.paused,
            dry_run=controls.effective_dry_run,
            real_mutation_allowed=self.settings.allow_real_infrastructure_mutation,
        )

    async def list_nodes(self, *, limit: int = 100) -> list[NodeSnapshot]:
        async with self.database.session() as session:
            nodes = await NodeRepository(session).list_all(limit=limit)
            return [self._node_snapshot(node) for node in nodes]

    async def resolve_node(self, identifier: str) -> NodeDetailSnapshot | None:
        raw = identifier.strip()
        async with self.database.session() as session:
            repo = NodeRepository(session)
            node = None
            try:
                node = await repo.get(UUID(raw))
            except ValueError:
                node = await repo.get_by_name(raw)
            if node is None:
                return None

            checks = await NodeCheckRepository(session).recent_for_node(node.id, limit=1)
            latest_job = await ReplacementJobRepository(session).latest_for_node(node.id)
            latest_check = checks[0] if checks else None
            return NodeDetailSnapshot(
                node=self._node_snapshot(node),
                master_node_id=node.master_node_id,
                monitoring_enabled=node.monitoring_enabled,
                last_checked_at=node.last_checked_at,
                latest_check_outcome=latest_check.outcome if latest_check else None,
                latest_check_at=latest_check.checked_at if latest_check else None,
                latest_job_id=latest_job.id if latest_job else None,
                latest_job_state=latest_job.state if latest_job else None,
                latest_job_checkpoint=latest_job.checkpoint if latest_job else None,
            )

    async def manual_check(self, node_id: UUID, *, actor_user_id: int) -> str:
        result = await self.monitoring.run_node(node_id)
        await self._audit(
            EventType.CONTROL_ACTION,
            "Authorized operator requested a manual node check",
            node_id=node_id,
            payload={"actor_user_id": actor_user_id, "result": result},
        )
        return result

    async def trigger_replacement(self, node_id: UUID, *, actor_user_id: int) -> UUID:
        job_id = await self.orchestrator.trigger(node_id)
        await self._audit(
            EventType.CONTROL_ACTION,
            "Authorized operator confirmed manual replacement",
            node_id=node_id,
            replacement_job_id=job_id,
            payload={"actor_user_id": actor_user_id},
        )
        return job_id

    async def trigger_force_repair(
        self,
        node_id: UUID,
        *,
        actor_user_id: int,
        request_key: str,
    ) -> UUID:
        job_id = await self.orchestrator.trigger(
            node_id,
            force=True,
            request_key=request_key,
        )
        await self._audit(
            EventType.CONTROL_ACTION,
            "Authorized operator confirmed FORCE REPAIR",
            node_id=node_id,
            replacement_job_id=job_id,
            payload={
                "actor_user_id": actor_user_id,
                "force": True,
                "request_key": request_key,
            },
        )
        return job_id

    async def resume_job(self, job_id: UUID, *, actor_user_id: int) -> ReplacementRunResult:
        await self._audit(
            EventType.CONTROL_ACTION,
            "Authorized operator resumed replacement job",
            replacement_job_id=job_id,
            payload={"actor_user_id": actor_user_id},
        )
        return await self.orchestrator.resume(job_id)

    async def cancel_job(self, job_id: UUID, *, actor_user_id: int) -> None:
        await self.orchestrator.cancel(job_id)
        await self._audit(
            EventType.CONTROL_ACTION,
            "Authorized operator cancelled replacement job",
            replacement_job_id=job_id,
            payload={"actor_user_id": actor_user_id},
        )

    async def get_job(self, job_id: UUID) -> JobSnapshot | None:
        async with self.database.session() as session:
            job = await ReplacementJobRepository(session).get(job_id)
            return self._job_snapshot(job) if job is not None else None

    async def list_jobs(self, *, limit: int = 20) -> list[JobSnapshot]:
        async with self.database.session() as session:
            jobs = await ReplacementJobRepository(session).list_recent(limit=limit)
            return [self._job_snapshot(job) for job in jobs]

    async def list_events(self, *, limit: int = 20) -> list[EventSnapshot]:
        async with self.database.session() as session:
            events = await EventRepository(session).list_recent(limit=limit)
            return [self._event_snapshot(event) for event in events]

    async def initialize_event_cursor(self) -> bool:
        """Skip historical audit events when notifications are enabled for the first time."""
        created_at, event_id = await self.operational_settings.get_event_cursor()
        if created_at is not None and event_id is not None:
            return False
        async with self.database.session() as session:
            events = await EventRepository(session).list_recent(limit=1)
        if not events:
            return False
        latest = self._event_snapshot(events[0])
        await self.advance_event_cursor(latest)
        return True

    async def list_events_after_cursor(self, *, limit: int = 100) -> list[EventSnapshot]:
        created_at, event_id = await self.operational_settings.get_event_cursor()
        async with self.database.session() as session:
            events = await EventRepository(session).list_after(created_at, event_id, limit=limit)
            return [self._event_snapshot(event) for event in events]

    async def advance_event_cursor(self, event: EventSnapshot) -> None:
        await self.operational_settings.set_event_cursor(event.created_at, event.id)

    async def event_notification_context(
        self, event: EventSnapshot
    ) -> EventNotificationContext:
        """Resolve safe, non-secret context for one Telegram audit notification."""
        node_id = event.node_id
        replacement_job = None
        async with self.database.session() as session:
            if event.replacement_job_id is not None:
                replacement_job = await ReplacementJobRepository(session).get(
                    event.replacement_job_id
                )
                if node_id is None and replacement_job is not None:
                    node_id = replacement_job.node_id

            if node_id is None:
                return EventNotificationContext(
                    replacement_job_id=event.replacement_job_id,
                    trigger_mode=(
                        replacement_job.trigger_mode if replacement_job is not None else None
                    ),
                    is_dry_run=(
                        replacement_job.is_dry_run if replacement_job is not None else None
                    ),
                )

            node = await NodeRepository(session).get(node_id)
            if node is None:
                return EventNotificationContext(
                    node_id=node_id,
                    replacement_job_id=event.replacement_job_id,
                    trigger_mode=(
                        replacement_job.trigger_mode if replacement_job is not None else None
                    ),
                    is_dry_run=(
                        replacement_job.is_dry_run if replacement_job is not None else None
                    ),
                )

            provider = await ProviderRepository(session).get(node.provider_id)
            current_vps = await VpsInstanceRepository(session).get_current_for_node(node.id)
            return EventNotificationContext(
                node_id=node.id,
                node_name=node.name,
                provider_name=provider.display_name if provider is not None else None,
                provider_type=provider.provider_type.value if provider is not None else None,
                vps_host=current_vps.host if current_vps is not None else None,
                target_host=node.current_host,
                target_port=node.current_port,
                state=node.state,
                operation_mode=node.operation_mode or NodeOperationMode.MONITOR_ONLY,
                consecutive_failures=node.consecutive_failures,
                consecutive_successes=node.consecutive_successes,
                replacement_job_id=event.replacement_job_id,
                trigger_mode=(
                    replacement_job.trigger_mode if replacement_job is not None else None
                ),
                is_dry_run=(replacement_job.is_dry_run if replacement_job is not None else None),
            )

    async def list_providers(self) -> list[ProviderSnapshot]:
        async with self.database.session() as session:
            providers = await ProviderRepository(session).list_all()
            return [
                ProviderSnapshot(
                    id=provider.id,
                    key=provider.key,
                    display_name=provider.display_name,
                    provider_type=provider.provider_type.value,
                    is_active=provider.is_active,
                    default_region=provider.default_region,
                    default_server_type=provider.default_server_type,
                )
                for provider in providers
            ]

    async def set_provider_active(
        self,
        provider_id: UUID,
        active: bool,
        *,
        actor_user_id: int,
    ) -> None:
        async with self.database.session() as session:
            provider = await ProviderRepository(session).get(provider_id)
            if provider is None:
                raise ValueError("provider does not exist")
            provider.is_active = active
            await EventRepository(session).add(
                Event(
                    node_id=None,
                    replacement_job_id=None,
                    event_type=EventType.PROVIDER_UPDATED,
                    severity=EventSeverity.WARNING,
                    message=(
                        f"Provider {'enabled' if active else 'disabled'} "
                        "by authorized operator"
                    ),
                    payload={
                        "provider_id": str(provider_id),
                        "provider_key": provider.key,
                        "active": active,
                        "actor_user_id": actor_user_id,
                    },
                    created_at=datetime.now(UTC),
                )
            )
            await session.commit()

    async def runtime_controls(self) -> RuntimeControlSnapshot:
        return await self.operational_settings.snapshot(self.settings)

    async def set_runtime_monitoring(self, enabled: bool, *, actor_user_id: int) -> bool:
        return await self.operational_settings.set_monitoring_enabled(
            enabled, actor_user_id=actor_user_id
        )

    async def set_runtime_replacement(self, enabled: bool, *, actor_user_id: int) -> bool:
        return await self.operational_settings.set_replacement_enabled(
            enabled, actor_user_id=actor_user_id
        )

    async def set_runtime_execution_mode(
        self, mode: RuntimeExecutionMode, *, actor_user_id: int
    ) -> bool:
        return await self.operational_settings.set_execution_mode(
            mode, self.settings, actor_user_id=actor_user_id
        )

    async def set_node_operation_mode(
        self, node_id: UUID, mode: NodeOperationMode, *, actor_user_id: int
    ) -> None:
        async with self.database.session() as session:
            nodes = NodeRepository(session)
            node = await nodes.get(node_id)
            if node is None:
                raise ValueError("node does not exist")
            active = await ReplacementJobRepository(session).get_active_for_node(node_id)
            if active is not None:
                raise ValueError("node operation mode cannot change during an active replacement")

            if mode is NodeOperationMode.AUTO_REPAIR:
                current_vps = await VpsInstanceRepository(session).get_current_for_node(node_id)
                provider = await ProviderRepository(session).get(node.provider_id)
                if current_vps is None or not current_vps.provider_server_id:
                    raise ValueError("auto repair requires a registered current VPS")
                if provider is None or not provider.is_active:
                    raise ValueError("auto repair requires an active provider")

            node.operation_mode = mode
            node.monitoring_enabled = mode is not NodeOperationMode.DISABLED
            if mode is NodeOperationMode.DISABLED:
                node.monitoring_lease_token = None
                node.monitoring_lease_until = None
                NodeStateMachine.transition(node, NodeState.DISABLED)
            elif node.state is NodeState.DISABLED:
                NodeStateMachine.transition(node, NodeState.UNKNOWN)

            await EventRepository(session).add(
                Event(
                    node_id=node.id,
                    replacement_job_id=None,
                    event_type=EventType.SETTING_CHANGED,
                    severity=(
                        EventSeverity.WARNING
                        if mode is NodeOperationMode.AUTO_REPAIR
                        else EventSeverity.INFO
                    ),
                    message=f"Node operation mode changed to {mode.value}",
                    payload={"actor_user_id": actor_user_id, "mode": mode.value},
                    created_at=datetime.now(UTC),
                )
            )
            await session.commit()

    async def set_paused(self, paused: bool, *, actor_user_id: int) -> bool:
        return await self.operational_settings.set_paused(
            paused,
            actor_user_id=actor_user_id,
        )

    async def settings_snapshot(self) -> dict[str, Any]:
        controls = await self.operational_settings.snapshot(self.settings)
        return {
            "environment": self.settings.environment,
            "execution_mode": controls.execution_mode.value,
            "effective_dry_run": controls.effective_dry_run,
            "host_dry_run_lock": self.settings.dry_run,
            "allow_real_infrastructure_mutation": self.settings.allow_real_infrastructure_mutation,
            "system_paused": controls.paused,
            "runtime_monitoring_enabled": controls.monitoring_enabled,
            "check_interval_seconds": self.settings.check_interval_seconds,
            "failure_threshold": self.settings.failure_threshold,
            "recovery_threshold": self.settings.recovery_threshold,
            "runtime_auto_repair_enabled": controls.replacement_enabled,
            "replacement_emergency_stop": self.settings.replacement_emergency_stop,
            "live_capable": controls.live_capable,
            "live_block_reason": controls.live_block_reason or "—",
            "max_replacement_attempts": self.settings.max_replacement_attempts,
            "max_temporary_servers": self.settings.max_temporary_servers,
            "max_concurrent_replacements": self.settings.max_concurrent_replacements,
        }

    async def _audit(
        self,
        event_type: EventType,
        message: str,
        *,
        node_id: UUID | None = None,
        replacement_job_id: UUID | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        async with self.database.session() as session:
            await EventRepository(session).add(
                Event(
                    node_id=node_id,
                    replacement_job_id=replacement_job_id,
                    event_type=event_type,
                    severity=EventSeverity.INFO,
                    message=message,
                    payload=payload,
                    created_at=datetime.now(UTC),
                )
            )
            await session.commit()

    @staticmethod
    def _node_snapshot(node: Any) -> NodeSnapshot:
        return NodeSnapshot(
            id=node.id,
            name=node.name,
            provider_id=node.provider_id,
            host=node.current_host,
            port=node.current_port,
            state=node.state,
            operation_mode=node.operation_mode or NodeOperationMode.MONITOR_ONLY,
            consecutive_failures=node.consecutive_failures,
            last_successful_check_at=node.last_successful_check_at,
        )

    @staticmethod
    def _job_snapshot(job: Any) -> JobSnapshot:
        return JobSnapshot(
            id=job.id,
            node_id=job.node_id,
            state=job.state,
            trigger_mode=job.trigger_mode or ReplacementTriggerMode.STANDARD,
            checkpoint=job.checkpoint,
            attempt_count=job.attempt_count,
            max_attempts=job.max_attempts,
            is_dry_run=job.is_dry_run,
            active=bool(job.active_slot),
            created_at=job.created_at,
            completed_at=job.completed_at,
            last_error_message=job.last_error_message,
        )

    @staticmethod
    def _event_snapshot(event: Any) -> EventSnapshot:
        return EventSnapshot(
            id=event.id,
            node_id=event.node_id,
            replacement_job_id=event.replacement_job_id,
            event_type=event.event_type,
            severity=event.severity,
            message=event.message,
            payload=event.payload,
            created_at=event.created_at,
        )
