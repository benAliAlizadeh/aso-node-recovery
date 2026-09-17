from __future__ import annotations

from datetime import UTC, datetime

from app.core.errors import AsoError
from app.models.enums import DeploymentState
from app.models.operations import Deployment


class InvalidDeploymentTransitionError(AsoError):
    pass


class DeploymentStateMachine:
    _ALLOWED: dict[DeploymentState, frozenset[DeploymentState]] = {
        DeploymentState.PENDING: frozenset(
            {DeploymentState.WAITING_SSH, DeploymentState.FAILED}
        ),
        DeploymentState.WAITING_SSH: frozenset(
            {DeploymentState.BOOTSTRAPPING, DeploymentState.FAILED}
        ),
        DeploymentState.BOOTSTRAPPING: frozenset(
            {DeploymentState.INSTALLING, DeploymentState.FAILED}
        ),
        DeploymentState.INSTALLING: frozenset(
            {DeploymentState.VERIFYING, DeploymentState.FAILED}
        ),
        DeploymentState.VERIFYING: frozenset(
            {DeploymentState.SUCCEEDED, DeploymentState.FAILED}
        ),
        DeploymentState.SUCCEEDED: frozenset(),
        DeploymentState.FAILED: frozenset(),
    }

    def transition(
        self,
        deployment: Deployment,
        target: DeploymentState,
        *,
        occurred_at: datetime | None = None,
    ) -> None:
        current = deployment.state or DeploymentState.PENDING
        if target not in self._ALLOWED[current]:
            raise InvalidDeploymentTransitionError(
                f"invalid deployment transition: {current.value} -> {target.value}"
            )
        now = occurred_at or datetime.now(UTC)
        if deployment.started_at is None and target is not DeploymentState.PENDING:
            deployment.started_at = now
        deployment.state = target
        if target in {DeploymentState.SUCCEEDED, DeploymentState.FAILED}:
            deployment.completed_at = now
