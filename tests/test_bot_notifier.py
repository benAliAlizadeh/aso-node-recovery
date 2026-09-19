from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from app.bot.notifier import TelegramEventNotifier
from app.control import EventNotificationContext, EventSnapshot
from app.models import (
    EventSeverity,
    EventType,
    NodeOperationMode,
    NodeState,
    ReplacementTriggerMode,
)


@pytest.mark.asyncio
async def test_notifier_skips_historical_events_on_first_run() -> None:
    control = SimpleNamespace(
        initialize_event_cursor=AsyncMock(return_value=True),
        list_events_after_cursor=AsyncMock(),
        advance_event_cursor=AsyncMock(),
    )
    bot = SimpleNamespace(send_message=AsyncMock())
    notifier = TelegramEventNotifier(control, chat_id=100)

    assert await notifier.run_once(bot) == 0
    control.list_events_after_cursor.assert_not_awaited()
    bot.send_message.assert_not_awaited()


def _failed_event() -> EventSnapshot:
    return EventSnapshot(
        id=UUID("11111111-1111-1111-1111-111111111111"),
        node_id=UUID("c158bb3a-1111-1111-1111-111111111111"),
        replacement_job_id=None,
        event_type=EventType.NODE_FAILED,
        severity=EventSeverity.ERROR,
        message="Node health changed: degraded -> failed",
        payload={
            "previous_state": "degraded",
            "current_state": "failed",
            "success_count": 0,
            "failure_count": 5,
            "total_nodes": 5,
        },
        created_at=datetime(2026, 9, 19, 10, 28, 0, tzinfo=UTC),
    )


def _node_context() -> EventNotificationContext:
    return EventNotificationContext(
        node_id=UUID("c158bb3a-1111-1111-1111-111111111111"),
        node_name="france linode",
        provider_name="Linode",
        provider_type="linode",
        vps_host="172.239.4.64",
        target_host="france.example.test",
        target_port=2053,
        state=NodeState.FAILED,
        operation_mode=NodeOperationMode.MONITOR_ONLY,
        consecutive_failures=3,
        consecutive_successes=0,
    )


def test_node_failed_notification_contains_actionable_node_identity() -> None:
    text = TelegramEventNotifier._format(_failed_event(), _node_context())

    assert "🚨 ASO Node Failed" in text
    assert "Node: france linode" in text
    assert "Node ID: c158bb3a" in text
    assert "Provider: Linode" in text
    assert "VPS IP/Host: 172.239.4.64" in text
    assert "Monitor target: france.example.test:2053" in text
    assert "State: degraded → failed" in text
    assert "Consecutive failures: 3" in text
    assert "Mode: Monitor Only" in text


def test_replacement_notification_contains_job_execution_context() -> None:
    event = EventSnapshot(
        id=UUID("22222222-2222-2222-2222-222222222222"),
        node_id=_failed_event().node_id,
        replacement_job_id=UUID("8dfb75c3-2222-2222-2222-222222222222"),
        event_type=EventType.REPLACEMENT_STARTED,
        severity=EventSeverity.INFO,
        message="Force repair workflow started",
        payload=None,
        created_at=datetime(2026, 9, 19, 10, 30, 0, tzinfo=UTC),
    )
    context = EventNotificationContext(
        **{
            name: getattr(_node_context(), name)
            for name in _node_context().__dataclass_fields__
            if name not in {"replacement_job_id", "trigger_mode", "is_dry_run"}
        },
        replacement_job_id=event.replacement_job_id,
        trigger_mode=ReplacementTriggerMode.FORCE,
        is_dry_run=True,
    )

    text = TelegramEventNotifier._format(event, context)

    assert "Job: 8dfb75c3" in text
    assert "Trigger: Force Repair" in text
    assert "Execution: DRY RUN" in text


@pytest.mark.asyncio
async def test_notifier_resolves_context_before_sending() -> None:
    event = _failed_event()
    context = _node_context()
    control = SimpleNamespace(
        initialize_event_cursor=AsyncMock(return_value=False),
        list_events_after_cursor=AsyncMock(return_value=[event]),
        event_notification_context=AsyncMock(return_value=context),
        advance_event_cursor=AsyncMock(),
    )
    bot = SimpleNamespace(send_message=AsyncMock())
    notifier = TelegramEventNotifier(control, chat_id=100)

    assert await notifier.run_once(bot) == 1
    control.event_notification_context.assert_awaited_once_with(event)
    sent_text = bot.send_message.await_args.kwargs["text"]
    assert "Node: france linode" in sent_text
    control.advance_event_cursor.assert_awaited_once_with(event)
