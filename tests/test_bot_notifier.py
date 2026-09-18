from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.bot.notifier import TelegramEventNotifier


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
