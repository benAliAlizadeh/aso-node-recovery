from __future__ import annotations

import asyncio
import signal

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.runtime import RuntimeContainer
from app.workers.scheduler import SystemWorkerScheduler


async def _run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, json_logs=settings.log_json)
    runtime = RuntimeContainer.build(settings)
    scheduler = SystemWorkerScheduler(
        settings,
        runtime.monitoring_worker,
        runtime.replacement_worker,
    )
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass

    try:
        scheduler.start()
        await stop.wait()
    finally:
        scheduler.shutdown()
        await runtime.close()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
