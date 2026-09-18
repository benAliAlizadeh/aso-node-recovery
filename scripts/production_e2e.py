from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import get_settings  # noqa: E402
from app.runtime import RuntimeContainer  # noqa: E402

_CONFIRM = "RUN_REAL_REPLACEMENT_E2E"


async def _run() -> None:
    settings = get_settings()
    if settings.environment != "production":
        raise SystemExit("production E2E requires ASO_ENVIRONMENT=production")
    if settings.dry_run or not settings.allow_real_infrastructure_mutation:
        raise SystemExit("production E2E requires both real-infrastructure guards enabled")
    if os.getenv("ASO_PRODUCTION_E2E_CONFIRM") != _CONFIRM:
        raise SystemExit(f"set ASO_PRODUCTION_E2E_CONFIRM={_CONFIRM}")
    raw_node_id = os.getenv("ASO_PRODUCTION_E2E_NODE_ID")
    if not raw_node_id:
        raise SystemExit("ASO_PRODUCTION_E2E_NODE_ID is required")
    node_id = UUID(raw_node_id)

    runtime = RuntimeContainer.build(settings)
    try:
        job_id = await runtime.control.trigger_replacement(node_id, actor_user_id=0)
        result = await runtime.orchestrator.resume(job_id)
        if not result.terminal or result.checkpoint.value != "completed":
            raise SystemExit(f"replacement did not complete: {result}")
        print(f"Production replacement E2E completed: {job_id}")
    finally:
        await runtime.close()


if __name__ == "__main__":
    asyncio.run(_run())
