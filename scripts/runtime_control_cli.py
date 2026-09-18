from __future__ import annotations

import argparse
import asyncio

from app.core.config import get_settings
from app.database import Database
from app.models import RuntimeExecutionMode
from app.services.operational_settings import OperationalSettingsService


async def _main() -> None:
    parser = argparse.ArgumentParser(description="ASO persistent runtime control helper")
    parser.add_argument("command", choices=(
        "show",
        "monitoring-on",
        "monitoring-off",
        "auto-on",
        "auto-off",
        "dry-run",
        "live",
    ))
    args = parser.parse_args()

    settings = get_settings()
    database = Database.from_settings(settings)
    service = OperationalSettingsService(database)
    try:
        if args.command == "monitoring-on":
            await service.set_monitoring_enabled(True)
        elif args.command == "monitoring-off":
            await service.set_monitoring_enabled(False)
        elif args.command == "auto-on":
            await service.set_replacement_enabled(True)
        elif args.command == "auto-off":
            await service.set_replacement_enabled(False)
        elif args.command == "dry-run":
            await service.set_execution_mode(RuntimeExecutionMode.DRY_RUN, settings)
        elif args.command == "live":
            await service.set_execution_mode(RuntimeExecutionMode.LIVE, settings)

        snapshot = await service.snapshot(settings)
        print(f"monitoring_enabled={snapshot.monitoring_enabled}")
        print(f"auto_repair_enabled={snapshot.replacement_enabled}")
        print(f"execution_mode={snapshot.execution_mode.value}")
        print(f"effective_dry_run={snapshot.effective_dry_run}")
        print(f"live_capable={snapshot.live_capable}")
        if snapshot.live_block_reason:
            print(f"live_block_reason={snapshot.live_block_reason}")
    finally:
        await database.dispose()


if __name__ == "__main__":
    asyncio.run(_main())
