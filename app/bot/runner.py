from __future__ import annotations

from app.bot.application import build_telegram_application
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.runtime import RuntimeContainer


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, json_logs=settings.log_json)
    runtime = RuntimeContainer.build(settings)
    application = build_telegram_application(runtime)
    application.run_polling(
        poll_interval=1.0,
        timeout=settings.telegram_poll_timeout_seconds,
        drop_pending_updates=False,
    )


if __name__ == "__main__":
    main()
