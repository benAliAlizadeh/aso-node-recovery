from __future__ import annotations

from app.core.errors import SafetyViolationError
from app.models import Deployment, DeploymentState, ReplacementJob, VpsInstance, VpsInstanceState


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
