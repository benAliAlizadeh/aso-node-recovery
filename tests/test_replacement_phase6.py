from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import SecretStr

from app.core.errors import SafetyViolationError
from app.core.secrets import RuntimeSecretStore
from app.models import (
    Deployment,
    DeploymentState,
    ReplacementCheckpoint,
    ReplacementJob,
    ReplacementJobState,
    VpsInstance,
    VpsInstanceRole,
    VpsInstanceState,
)
from app.replacement.safety import OldVpsProtectionGuard
from app.replacement.state import InvalidReplacementTransitionError, ReplacementStateMachine


def replacement_job() -> ReplacementJob:
    return ReplacementJob(
        id=uuid4(),
        node_id=uuid4(),
        state=ReplacementJobState.PENDING,
        checkpoint=ReplacementCheckpoint.CREATED,
        active_slot=True,
        is_dry_run=False,
        attempt_count=1,
        max_attempts=5,
    )


def test_full_replacement_checkpoint_path_is_explicit_and_ordered() -> None:
    job = replacement_job()
    machine = ReplacementStateMachine()
    path = (
        ReplacementCheckpoint.PROVISIONING,
        ReplacementCheckpoint.PROVISIONED,
        ReplacementCheckpoint.CHECKING_IP,
        ReplacementCheckpoint.IP_VERIFIED,
        ReplacementCheckpoint.DEPLOYING,
        ReplacementCheckpoint.NODE_VERIFIED,
        ReplacementCheckpoint.MASTER_UPDATING,
        ReplacementCheckpoint.MASTER_UPDATED,
        ReplacementCheckpoint.MASTER_VERIFYING,
        ReplacementCheckpoint.MASTER_VERIFIED,
        ReplacementCheckpoint.FINAL_CHECK,
        ReplacementCheckpoint.FINAL_VERIFIED,
        ReplacementCheckpoint.OLD_VPS_CLEANUP,
        ReplacementCheckpoint.COMPLETED,
    )
    for checkpoint in path:
        assert machine.transition(job, checkpoint) is True

    assert job.state is ReplacementJobState.COMPLETED
    assert job.active_slot is None
    with pytest.raises(InvalidReplacementTransitionError):
        machine.transition(job, ReplacementCheckpoint.PROVISIONING)


def test_any_active_checkpoint_can_fail_without_leaving_active_slot_stuck() -> None:
    for checkpoint in ReplacementCheckpoint:
        if checkpoint in {
            ReplacementCheckpoint.COMPLETED,
            ReplacementCheckpoint.FAILED,
            ReplacementCheckpoint.CANCELLED,
        }:
            continue
        job = replacement_job()
        job.checkpoint = checkpoint
        ReplacementStateMachine.transition(job, ReplacementCheckpoint.FAILED)
        assert job.state is ReplacementJobState.FAILED
        assert job.active_slot is None


def test_bad_ip_path_can_cleanup_and_retry() -> None:
    job = replacement_job()
    machine = ReplacementStateMachine()
    for checkpoint in (
        ReplacementCheckpoint.PROVISIONING,
        ReplacementCheckpoint.PROVISIONED,
        ReplacementCheckpoint.CHECKING_IP,
        ReplacementCheckpoint.TEMP_CLEANUP,
        ReplacementCheckpoint.PROVISIONING,
    ):
        machine.transition(job, checkpoint)
    assert job.checkpoint is ReplacementCheckpoint.PROVISIONING


def test_old_vps_deletion_guard_requires_every_durable_gate() -> None:
    old = VpsInstance(
        id=uuid4(),
        provider_id=uuid4(),
        node_id=uuid4(),
        provider_server_id="old-1",
        role=VpsInstanceRole.CURRENT,
        state=VpsInstanceState.RUNNING,
        host="198.51.100.10",
    )
    new = VpsInstance(
        id=uuid4(),
        provider_id=old.provider_id,
        node_id=old.node_id,
        provider_server_id="new-1",
        role=VpsInstanceRole.REPLACEMENT,
        state=VpsInstanceState.RUNNING,
        host="203.0.113.20",
    )
    job = replacement_job()
    job.old_vps_instance_id = old.id
    job.new_vps_instance_id = new.id
    deployment = Deployment(
        id=uuid4(),
        replacement_job_id=job.id,
        vps_instance_id=new.id,
        attempt_number=1,
        state=DeploymentState.SUCCEEDED,
    )

    with pytest.raises(SafetyViolationError, match="new_ip_verified"):
        OldVpsProtectionGuard.assert_can_delete(job, deployment=deployment, new_vps=new, old_vps=old)

    now = datetime.now(UTC)
    job.new_ip_verified_at = now
    job.deployment_verified_at = now
    job.master_updated_at = now
    job.master_verified_at = now
    job.final_health_verified_at = now
    OldVpsProtectionGuard.assert_can_delete(job, deployment=deployment, new_vps=new, old_vps=old)


def test_runtime_generated_secrets_are_file_references_with_owner_only_permissions(tmp_path: Path) -> None:
    store = RuntimeSecretStore(str(tmp_path / "runtime"))
    reference = store.write("job-1", "node-api-token", SecretStr("super-secret"))
    path = Path(reference)
    assert path.read_text(encoding="utf-8") == "super-secret"
    if os.name == "posix":
        assert path.stat().st_mode & 0o777 == 0o600
        assert path.parent.stat().st_mode & 0o777 == 0o700
    store.delete_reference(reference)
    assert not path.exists()
