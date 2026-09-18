from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from app.core.config import Settings
from app.core.errors import SafetyViolationError
from app.database import Database
from app.database.repositories import EventRepository, SettingRepository
from app.models import Event, EventSeverity, EventType, RuntimeExecutionMode

SYSTEM_PAUSED_KEY = "system.paused"
TELEGRAM_EVENT_CURSOR_KEY = "telegram.event_cursor"
RUNTIME_MONITORING_ENABLED_KEY = "runtime.monitoring_enabled"
RUNTIME_REPLACEMENT_ENABLED_KEY = "runtime.replacement_enabled"
RUNTIME_EXECUTION_MODE_KEY = "runtime.execution_mode"


@dataclass(frozen=True, slots=True)
class RuntimeControlSnapshot:
    paused: bool
    monitoring_enabled: bool
    replacement_enabled: bool
    execution_mode: RuntimeExecutionMode
    effective_dry_run: bool
    worker_scheduler_available: bool
    live_capable: bool
    live_block_reason: str | None


class OperationalSettingsService:
    """Persist runtime operator controls while preserving environment-level safety gates.

    Telegram can make the system *more* restrictive at runtime. It can select LIVE only when the
    host environment was explicitly configured as live-capable. It can never override DRY_RUN,
    mutation guards, or the emergency stop from persisted settings.
    """

    def __init__(self, database: Database) -> None:
        self.database = database

    async def is_paused(self) -> bool:
        return await self._get_bool(SYSTEM_PAUSED_KEY, False)

    async def set_paused(self, paused: bool, *, actor_user_id: int | None = None) -> bool:
        async with self.database.session() as session:
            settings = SettingRepository(session)
            current = await settings.get_by_key(SYSTEM_PAUSED_KEY)
            previous = bool(current.value) if current is not None else False
            if previous == paused:
                return False

            await settings.set_value(
                SYSTEM_PAUSED_KEY,
                paused,
                description="Global runtime pause flag controlled by authorized operators",
            )
            await EventRepository(session).add(
                Event(
                    node_id=None,
                    replacement_job_id=None,
                    event_type=EventType.SYSTEM_PAUSED if paused else EventType.SYSTEM_RESUMED,
                    severity=EventSeverity.WARNING if paused else EventSeverity.INFO,
                    message="System paused by authorized operator"
                    if paused
                    else "System resumed by authorized operator",
                    payload={"actor_user_id": actor_user_id} if actor_user_id is not None else None,
                    created_at=datetime.now(UTC),
                )
            )
            await session.commit()
            return True

    async def monitoring_enabled(self, *, default: bool) -> bool:
        return await self._get_bool(RUNTIME_MONITORING_ENABLED_KEY, default)

    async def replacement_enabled(self, *, default: bool) -> bool:
        return await self._get_bool(RUNTIME_REPLACEMENT_ENABLED_KEY, default)

    async def execution_mode(self, *, default_dry_run: bool) -> RuntimeExecutionMode:
        async with self.database.session() as session:
            setting = await SettingRepository(session).get_by_key(RUNTIME_EXECUTION_MODE_KEY)
            if setting is None:
                # A newly introduced runtime control always starts conservative, even on a host
                # whose environment is live-capable. Operators must explicitly confirm LIVE.
                return RuntimeExecutionMode.DRY_RUN
            try:
                return RuntimeExecutionMode(str(setting.value))
            except ValueError:
                return RuntimeExecutionMode.DRY_RUN

    async def effective_dry_run(self, settings: Settings) -> bool:
        # Environment safety switches are hard upper boundaries. If the host is not live-capable,
        # runtime execution safely collapses to DRY_RUN even if a stale DB value says LIVE.
        capable, _ = self.live_capability(settings)
        if not capable:
            return True
        mode = await self.execution_mode(default_dry_run=settings.dry_run)
        return mode is RuntimeExecutionMode.DRY_RUN

    async def set_monitoring_enabled(
        self,
        enabled: bool,
        *,
        actor_user_id: int | None = None,
    ) -> bool:
        return await self._set_runtime_value(
            RUNTIME_MONITORING_ENABLED_KEY,
            enabled,
            description="Runtime monitoring scheduler switch controlled by authorized operators",
            actor_user_id=actor_user_id,
            message=f"Runtime monitoring {'enabled' if enabled else 'disabled'}",
        )

    async def set_replacement_enabled(
        self,
        enabled: bool,
        *,
        actor_user_id: int | None = None,
    ) -> bool:
        return await self._set_runtime_value(
            RUNTIME_REPLACEMENT_ENABLED_KEY,
            enabled,
            description="Runtime automatic replacement switch controlled by authorized operators",
            actor_user_id=actor_user_id,
            message=f"Runtime automatic replacement {'enabled' if enabled else 'disabled'}",
        )

    async def set_execution_mode(
        self,
        mode: RuntimeExecutionMode,
        settings: Settings,
        *,
        actor_user_id: int | None = None,
    ) -> bool:
        if mode is RuntimeExecutionMode.LIVE:
            capable, reason = self.live_capability(settings)
            if not capable:
                raise SafetyViolationError(
                    reason or "live execution is blocked by host safety gates"
                )

        return await self._set_runtime_value(
            RUNTIME_EXECUTION_MODE_KEY,
            mode.value,
            description=(
                "Runtime replacement execution mode. Environment safety gates always take priority."
            ),
            actor_user_id=actor_user_id,
            message=f"Runtime replacement mode changed to {mode.value}",
        )

    async def snapshot(self, settings: Settings) -> RuntimeControlSnapshot:
        capable, reason = self.live_capability(settings)
        selected = await self.execution_mode(default_dry_run=settings.dry_run)
        effective_dry = (not capable) or selected is RuntimeExecutionMode.DRY_RUN
        return RuntimeControlSnapshot(
            paused=await self.is_paused(),
            monitoring_enabled=await self.monitoring_enabled(
                default=settings.monitoring_scheduler_enabled
            ),
            replacement_enabled=await self.replacement_enabled(
                default=settings.replacement_worker_enabled
            ),
            execution_mode=selected,
            effective_dry_run=effective_dry,
            worker_scheduler_available=settings.worker_scheduler_enabled,
            live_capable=capable,
            live_block_reason=reason,
        )

    @staticmethod
    def live_capability(settings: Settings) -> tuple[bool, str | None]:
        if settings.dry_run:
            return False, "Host is locked by ASO_DRY_RUN=true"
        if not settings.allow_real_infrastructure_mutation:
            return False, "Host is locked by ASO_ALLOW_REAL_INFRASTRUCTURE_MUTATION=false"
        if settings.replacement_emergency_stop:
            return False, "Host is locked by ASO_REPLACEMENT_EMERGENCY_STOP=true"
        return True, None

    async def get_event_cursor(self) -> tuple[datetime | None, UUID | None]:
        async with self.database.session() as session:
            setting = await SettingRepository(session).get_by_key(TELEGRAM_EVENT_CURSOR_KEY)
            if setting is None or not isinstance(setting.value, dict):
                return None, None
            raw_time = setting.value.get("created_at")
            raw_id = setting.value.get("event_id")
            try:
                created_at = datetime.fromisoformat(str(raw_time)) if raw_time else None
                event_id = UUID(str(raw_id)) if raw_id else None
            except (ValueError, TypeError):
                return None, None
            if created_at is not None and created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=UTC)
            return created_at, event_id

    async def set_event_cursor(self, created_at: datetime, event_id: UUID) -> None:
        async with self.database.session() as session:
            await SettingRepository(session).set_value(
                TELEGRAM_EVENT_CURSOR_KEY,
                {"created_at": created_at.astimezone(UTC).isoformat(), "event_id": str(event_id)},
                description="Last audit event processed by Telegram notifier",
            )
            await session.commit()

    async def _get_bool(self, key: str, default: bool) -> bool:
        async with self.database.session() as session:
            setting = await SettingRepository(session).get_by_key(key)
            return bool(setting.value) if setting is not None else default

    async def _set_runtime_value(
        self,
        key: str,
        value: object,
        *,
        description: str,
        actor_user_id: int | None,
        message: str,
    ) -> bool:
        async with self.database.session() as session:
            repo = SettingRepository(session)
            current = await repo.get_by_key(key)
            if current is not None and current.value == value:
                return False
            await repo.set_value(key, value, description=description)
            await EventRepository(session).add(
                Event(
                    node_id=None,
                    replacement_job_id=None,
                    event_type=EventType.SETTING_CHANGED,
                    severity=EventSeverity.WARNING,
                    message=message,
                    payload={"key": key, "actor_user_id": actor_user_id},
                    created_at=datetime.now(UTC),
                )
            )
            await session.commit()
            return True
