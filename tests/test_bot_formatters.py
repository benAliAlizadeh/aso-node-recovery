from datetime import UTC, datetime
from uuid import uuid4

from app.bot.formatters import format_dashboard, format_job_progress
from app.control import DashboardSnapshot, JobSnapshot
from app.models import ReplacementCheckpoint, ReplacementJobState


def test_dashboard_exposes_safety_state() -> None:
    text = format_dashboard(
        DashboardSnapshot(
            node_counts={"healthy": 2, "failed": 1},
            active_vps_count=3,
            active_replacement_count=1,
            paused=True,
            dry_run=True,
            real_mutation_allowed=False,
        )
    )
    assert "Healthy: 2" in text
    assert "Failed: 1" in text
    assert "System: PAUSED" in text
    assert "DRY_RUN: True" in text


def test_progress_has_eight_guarded_steps() -> None:
    job = JobSnapshot(
        id=uuid4(),
        node_id=uuid4(),
        state=ReplacementJobState.VERIFYING,
        checkpoint=ReplacementCheckpoint.MASTER_VERIFYING,
        attempt_count=1,
        max_attempts=5,
        is_dry_run=True,
        active=True,
        created_at=datetime.now(UTC),
        completed_at=None,
        last_error_message=None,
    )
    text = format_job_progress(job)
    assert "1/8" in text
    assert "8/8" in text
    assert "Verifying Master" in text
