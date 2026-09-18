from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.control import ControlService, EventSnapshot
from app.models import EventType

if TYPE_CHECKING:
    from telegram import Bot

logger = logging.getLogger(__name__)

_NOTIFIABLE = frozenset(
    {
        EventType.NODE_FAILED,
        EventType.NODE_RECOVERED,
        EventType.REPLACEMENT_STARTED,
        EventType.REPLACEMENT_COMPLETED,
        EventType.REPLACEMENT_FAILED,
    }
)


class TelegramEventNotifier:
    def __init__(self, control: ControlService, *, chat_id: int) -> None:
        self.control = control
        self.chat_id = chat_id

    async def run_once(self, bot: "Bot") -> int:
        if await self.control.initialize_event_cursor():
            logger.info("telegram notifier cursor initialized at latest audit event")
            return 0
        events = await self.control.list_events_after_cursor(limit=100)
        sent = 0
        for event in events:
            if event.event_type in _NOTIFIABLE:
                await bot.send_message(chat_id=self.chat_id, text=self._format(event))
                sent += 1
            await self.control.advance_event_cursor(event)
        return sent

    @staticmethod
    def _format(event: EventSnapshot) -> str:
        return (
            f"ASO event: {event.event_type.value}\n"
            f"Severity: {event.severity.value}\n"
            f"{event.message}"
        )
