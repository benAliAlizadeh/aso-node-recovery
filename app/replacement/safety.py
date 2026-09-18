from __future__ import annotations

from app.core.errors import SafetyViolationError
from app.models import (
    Deployment,
    DeploymentState,
    ReplacementJob,
    VpsInstance,
    VpsInstanceRole,
    VpsInstanceState,
)


class OldVpsProtectionGuard:
    """Hard gate around the only old-VPS deletion path."""

    @staticmethod
    def assert_can_delete(
        job: ReplacementJob,
        *,
        deployment: Deployment,
        new_vps: VpsInstance,
        old_vps: VpsInstance,
    ) -> None:
        missing: list[str] = []
        if job.old_vps_instance_id != old_vps.id:
            missing.append("old_vps_job_identity")
        if old_vps.node_id != job.node_id:
            missing.append("old_vps_node_identity")
        if old_vps.role is not VpsInstanceRole.CURRENT:
            missing.append("old_vps_current_role")
        if old_vps.state is VpsInstanceState.DELETED:
            missing.append("old_vps_not_deleted")
        if new_vps.node_id != job.node_id:
            missing.append("new_vps_node_identity")
        if new_vps.role is not VpsInstanceRole.REPLACEMENT:
            missing.append("new_vps_replacement_role")
        if deployment.replacement_job_id != job.id:
            missing.append("deployment_job_identity")
        if deployment.vps_instance_id != new_vps.id:
            missing.append("deployment_vps_identity")
        if (
            new_vps.provider_id == old_vps.provider_id
            and new_vps.provider_server_id == old_vps.provider_server_id
        ):
            missing.append("distinct_provider_identity")
        if job.new_vps_instance_id is None or job.new_vps_instance_id != new_vps.id:
            missing.append("new_vps")
        if new_vps.id == old_vps.id:
            missing.append("distinct_new_vps")
        if new_vps.state is not VpsInstanceState.RUNNING or not new_vps.host:
            missing.append("new_vps_running")
        if job.new_ip_verified_at is None:
            missing.append("new_ip_verified")
        if deployment.state is not DeploymentState.SUCCEEDED:
            missing.append("deployment_succeeded")
        if job.deployment_verified_at is None:
            missing.append("deployment_verified")
        if job.master_updated_at is None:
            missing.append("master_updated")
        if job.master_verified_at is None:
            missing.append("master_verified")
        if job.final_health_verified_at is None:
            missing.append("final_health_verified")
        if missing:
            raise SafetyViolationError(
                "old VPS deletion denied; missing durable gates: " + ", ".join(missing)
            )
