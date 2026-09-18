from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.models  # noqa: E402,F401
from sqlalchemy.dialects import postgresql  # noqa: E402
from sqlalchemy.schema import CreateTable  # noqa: E402

from app.core.config import Settings  # noqa: E402
from app.database import metadata  # noqa: E402
from app.models import ReplacementCheckpoint  # noqa: E402
from app.replacement.state import ReplacementStateMachine  # noqa: E402

REQUIRED_FILES = {
    "app/master/client.py",
    "app/master/types.py",
    "app/replacement/orchestrator.py",
    "app/replacement/reachability.py",
    "app/replacement/safety.py",
    "app/replacement/state.py",
    "app/replacement/locks.py",
    "app/workers/replacement.py",
    "migrations/versions/20260917_0002_master_replacement.py",
    "docs/MASTER_3XUI.md",
    "docs/REPLACEMENT.md",
}


def main() -> int:
    missing = sorted(path for path in REQUIRED_FILES if not (ROOT / path).exists())
    if missing:
        raise SystemExit(f"Patch 04 validation failed; missing files: {missing}")

    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if not version:
        raise SystemExit("Patch 04 validation failed; VERSION is empty")

    settings = Settings(_env_file=None)
    assert settings.dry_run is True
    assert settings.allow_real_infrastructure_mutation is False
    assert settings.replacement_worker_enabled is False
    assert settings.replacement_emergency_stop is False
    assert settings.replacement_job_lease_seconds >= settings.provisioning_timeout_seconds

    jobs = metadata.tables["replacement_jobs"].c
    for name in (
        "checkpoint",
        "is_dry_run",
        "workflow_lease_token",
        "workflow_lease_until",
        "master_snapshot",
        "final_health_verified_at",
        "old_vps_deleted_at",
    ):
        assert name in jobs

    deployments = metadata.tables["deployments"].c
    assert "api_token_ref" in deployments
    assert "panel_password_ref" in deployments
    assert "panel_port" in deployments
    assert "api_token" not in deployments
    assert "panel_password" not in deployments

    assert ReplacementStateMachine.can_transition(
        ReplacementCheckpoint.CHECKING_IP, ReplacementCheckpoint.TEMP_CLEANUP
    )
    assert ReplacementStateMachine.can_transition(
        ReplacementCheckpoint.MASTER_VERIFYING, ReplacementCheckpoint.FAILED
    )
    assert not ReplacementStateMachine.can_transition(
        ReplacementCheckpoint.COMPLETED, ReplacementCheckpoint.PROVISIONING
    )

    dialect = postgresql.dialect()
    for table in metadata.sorted_tables:
        str(CreateTable(table).compile(dialect=dialect))

    if version == "0.6.0-master-replacement":
        bot_files = sorted(path.name for path in (ROOT / "app" / "bot").glob("*.py"))
        if bot_files != ["__init__.py"]:
            raise SystemExit(
                "Patch 04 validation failed; Telegram Phase 7 was implemented too early"
            )

    print("Patch 04 validation: PASS")
    print("Phase 6: master client + crash-resumable replacement orchestrator")
    print("Safety: dry-run, emergency stop, durable gates, old-VPS protection")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
