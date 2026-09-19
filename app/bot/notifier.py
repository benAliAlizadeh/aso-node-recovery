from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.control import ControlService, EventNotificationContext, EventSnapshot
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

_TITLES = {
    EventType.NODE_FAILED: "🚨 ASO Node Failed",
    EventType.NODE_RECOVERED: "✅ ASO Node Recovered",
    EventType.REPLACEMENT_STARTED: "🛠 ASO Replacement Started",
    EventType.REPLACEMENT_COMPLETED: "✅ ASO Replacement Completed",
    EventType.REPLACEMENT_FAILED: "❌ ASO Replacement Failed",
}


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
                context = await self.control.event_notification_context(event)
                await bot.send_message(
                    chat_id=self.chat_id,
                    text=self._format(event, context),
                )
                sent += 1
            await self.control.advance_event_cursor(event)
        return sent

    @classmethod
    def _format(
        cls,
        event: EventSnapshot,
        context: EventNotificationContext,
    ) -> str:
        title = _TITLES.get(event.event_type, f"ASO event: {event.event_type.value}")
        lines = [title, ""]

        if context.node_name:
            lines.append(f"Node: {context.node_name}")
        if context.node_id:
            lines.append(f"Node ID: {cls._short_id(context.node_id)}")

        provider = cls._provider_label(context)
        if provider:
            lines.append(f"Provider: {provider}")

        if context.vps_host:
            lines.append(f"VPS IP/Host: {context.vps_host}")

        if context.target_host:
            target = context.target_host
            if context.target_port:
                target = f"{target}:{context.target_port}"
            if target != context.vps_host:
                lines.append(f"Monitor target: {target}")

        transition = cls._state_transition(event, context)
        if transition:
            lines.append(f"State: {transition}")
        elif context.state:
            lines.append(f"State: {context.state.value}")

        if event.event_type is EventType.NODE_FAILED and context.consecutive_failures is not None:
            lines.append(f"Consecutive failures: {context.consecutive_failures}")
        elif (
            event.event_type is EventType.NODE_RECOVERED
            and context.consecutive_successes is not None
        ):
            lines.append(f"Consecutive successes: {context.consecutive_successes}")

        if context.operation_mode:
            lines.append(f"Mode: {context.operation_mode.value.replace('_', ' ').title()}")

        if context.replacement_job_id:
            lines.append(f"Job: {cls._short_id(context.replacement_job_id)}")
        if context.trigger_mode:
            lines.append(
                "Trigger: "
                + ("Force Repair" if context.trigger_mode.value == "force" else "Automatic/Standard")
            )
        if context.is_dry_run is not None:
            lines.append(f"Execution: {'DRY RUN' if context.is_dry_run else 'LIVE'}")

        lines.extend(
            [
                f"Time: {event.created_at.strftime('%Y-%m-%d %H:%M:%S UTC')}",
                "",
                event.message,
            ]
        )
        return "\n".join(lines)

    @staticmethod
    def _short_id(value: object) -> str:
        return str(value).split("-", maxsplit=1)[0]

    @staticmethod
    def _provider_label(context: EventNotificationContext) -> str | None:
        if context.provider_name and context.provider_type:
            if context.provider_name.casefold() == context.provider_type.casefold():
                return context.provider_name
            return f"{context.provider_name} ({context.provider_type})"
        return context.provider_name or context.provider_type

    @staticmethod
    def _state_transition(
        event: EventSnapshot,
        context: EventNotificationContext,
    ) -> str | None:
        payload = event.payload or {}
        previous = payload.get("previous_state")
        current = payload.get("current_state")
        if previous and current:
            return f"{previous} → {current}"
        if context.state:
            return context.state.value
        return None
