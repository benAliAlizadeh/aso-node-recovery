from __future__ import annotations

import asyncio
import os
from uuid import UUID

import pytest

from app.core.config import Settings
from app.runtime import RuntimeContainer

pytestmark = pytest.mark.production
_CONFIRM = "RUN_REAL_REPLACEMENT_E2E"


def test_real_replacement_e2e_requires_explicit_authorization() -> None:
    if os.getenv("ASO_PRODUCTION_E2E_CONFIRM") != _CONFIRM:
        pytest.skip("real production replacement E2E is not explicitly authorized")

    raw_node_id = os.getenv("ASO_PRODUCTION_E2E_NODE_ID")
    if not raw_node_id:
        pytest.fail("ASO_PRODUCTION_E2E_NODE_ID is required after E2E authorization")
    node_id = UUID(raw_node_id)

    settings = Settings(_env_file=".env")
    assert settings.environment == "production"
    assert settings.dry_run is False
    assert settings.allow_real_infrastructure_mutation is True

    async def run() -> None:
        runtime = RuntimeContainer.build(settings)
        try:
            job_id = await runtime.control.trigger_replacement(node_id, actor_user_id=0)
            result = await runtime.orchestrator.resume(job_id)
            assert result.terminal is True
            assert result.checkpoint.value == "completed"
        finally:
            await runtime.close()

    asyncio.run(run())
