from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from app.database import Database
from app.database.repositories import EventRepository, SettingRepository
from app.models import Event, EventSeverity, EventType

SYSTEM_PAUSED_KEY = "system.paused"
TELEGRAM_EVENT_CURSOR_KEY = "telegram.event_cursor"


class OperationalSettingsService:
    """Persist small runtime control settings without storing secrets."""

    def __init__(self, database: Database) -> None:
        self.database = database

    async def is_paused(self) -> bool:
        async with self.database.session() as session:
            setting = await SettingRepository(session).get_by_key(SYSTEM_PAUSED_KEY)
            return bool(setting.value) if setting is not None else False

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
