from __future__ import annotations

import asyncio

from telegram import Bot

from app.core.config import get_settings


async def main() -> None:
    settings = get_settings()
    if not settings.telegram_bot_enabled or settings.telegram_bot_token is None:
        raise SystemExit("Telegram bot is not enabled/configured")
    async with Bot(settings.telegram_bot_token.get_secret_value()) as bot:
        me = await bot.get_me()
    username = f"@{me.username}" if me.username else f"id={me.id}"
    print(f"Telegram API OK: {username}")


if __name__ == "__main__":
    asyncio.run(main())
