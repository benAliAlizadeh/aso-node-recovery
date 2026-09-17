from __future__ import annotations

from datetime import UTC, datetime
from types import MappingProxyType

from app.core.errors import AsoError
from app.models import ReplacementCheckpoint, ReplacementJob, ReplacementJobState


class InvalidReplacementTransitionError(AsoError):
    pass


_TERMINAL = frozenset(
    {
        ReplacementCheckpoint.COMPLETED,
        ReplacementCheckpoint.FAILED,
        ReplacementCheckpoint.CANCELLED,
    }
)

_FORWARD: dict[ReplacementCheckpoint, frozenset[ReplacementCheckpoint]] = {
    ReplacementCheckpoint.CREATED: frozenset({ReplacementCheckpoint.PROVISIONING}),
    ReplacementCheckpoint.PROVISIONING: frozenset({ReplacementCheckpoint.PROVISIONED}),
    ReplacementCheckpoint.PROVISIONED: frozenset({ReplacementCheckpoint.CHECKING_IP, ReplacementCheckpoint.TEMP_CLEANUP}),
    ReplacementCheckpoint.CHECKING_IP: frozenset(
        {ReplacementCheckpoint.IP_VERIFIED, ReplacementCheckpoint.TEMP_CLEANUP}
    ),
    ReplacementCheckpoint.TEMP_CLEANUP: frozenset({ReplacementCheckpoint.PROVISIONING}),
    ReplacementCheckpoint.IP_VERIFIED: frozenset({ReplacementCheckpoint.DEPLOYING}),
    ReplacementCheckpoint.DEPLOYING: frozenset({ReplacementCheckpoint.NODE_VERIFIED}),
    ReplacementCheckpoint.NODE_VERIFIED: frozenset({ReplacementCheckpoint.MASTER_UPDATING}),
    ReplacementCheckpoint.MASTER_UPDATING: frozenset({ReplacementCheckpoint.MASTER_UPDATED}),
    ReplacementCheckpoint.MASTER_UPDATED: frozenset({ReplacementCheckpoint.MASTER_VERIFYING}),
    ReplacementCheckpoint.MASTER_VERIFYING: frozenset({ReplacementCheckpoint.MASTER_VERIFIED}),
    ReplacementCheckpoint.MASTER_VERIFIED: frozenset({ReplacementCheckpoint.FINAL_CHECK}),
    ReplacementCheckpoint.FINAL_CHECK: frozenset({ReplacementCheckpoint.FINAL_VERIFIED}),
    ReplacementCheckpoint.FINAL_VERIFIED: frozenset({ReplacementCheckpoint.OLD_VPS_CLEANUP}),
    ReplacementCheckpoint.OLD_VPS_CLEANUP: frozenset({ReplacementCheckpoint.COMPLETED}),
    ReplacementCheckpoint.COMPLETED: frozenset(),
    ReplacementCheckpoint.FAILED: frozenset(),
    ReplacementCheckpoint.CANCELLED: frozenset(),
}

# Every active checkpoint may fail or be explicitly cancelled. This matters for durable workflows:
# configuration/network errors can happen at any stage and must not leave an active_slot stuck forever.
_ALLOWED = MappingProxyType(
    {
        checkpoint: (targets if checkpoint in _TERMINAL else targets | {ReplacementCheckpoint.FAILED, ReplacementCheckpoint.CANCELLED})
        for checkpoint, targets in _FORWARD.items()
    }
)

_STATE_FOR_CHECKPOINT = MappingProxyType(
    {
        ReplacementCheckpoint.CREATED: ReplacementJobState.PENDING,
        ReplacementCheckpoint.PROVISIONING: ReplacementJobState.PROVISIONING,
        ReplacementCheckpoint.PROVISIONED: ReplacementJobState.PROVISIONING,
        ReplacementCheckpoint.CHECKING_IP: ReplacementJobState.CHECKING_IP,
        ReplacementCheckpoint.TEMP_CLEANUP: ReplacementJobState.CLEANING_UP,
        ReplacementCheckpoint.IP_VERIFIED: ReplacementJobState.CHECKING_IP,
        ReplacementCheckpoint.DEPLOYING: ReplacementJobState.DEPLOYING,
        ReplacementCheckpoint.NODE_VERIFIED: ReplacementJobState.VERIFYING,
        ReplacementCheckpoint.MASTER_UPDATING: ReplacementJobState.UPDATING_MASTER,
        ReplacementCheckpoint.MASTER_UPDATED: ReplacementJobState.UPDATING_MASTER,
        ReplacementCheckpoint.MASTER_VERIFYING: ReplacementJobState.VERIFYING,
        ReplacementCheckpoint.MASTER_VERIFIED: ReplacementJobState.VERIFYING,
        ReplacementCheckpoint.FINAL_CHECK: ReplacementJobState.VERIFYING,
        ReplacementCheckpoint.FINAL_VERIFIED: ReplacementJobState.VERIFYING,
        ReplacementCheckpoint.OLD_VPS_CLEANUP: ReplacementJobState.CLEANING_UP,
        ReplacementCheckpoint.COMPLETED: ReplacementJobState.COMPLETED,
        ReplacementCheckpoint.FAILED: ReplacementJobState.FAILED,
        ReplacementCheckpoint.CANCELLED: ReplacementJobState.CANCELLED,
    }
)


class ReplacementStateMachine:
    @staticmethod
    def can_transition(current: ReplacementCheckpoint, target: ReplacementCheckpoint) -> bool:
        return target == current or target in _ALLOWED[current]

    @classmethod
    def transition(
        cls,
        job: ReplacementJob,
        target: ReplacementCheckpoint,
        *,
        occurred_at: datetime | None = None,
    ) -> bool:
        current = job.checkpoint or ReplacementCheckpoint.CREATED
        if target == current:
            return False
        if target not in _ALLOWED[current]:
            raise InvalidReplacementTransitionError(
                f"invalid replacement transition: {current.value} -> {target.value}"
            )
        now = occurred_at or datetime.now(UTC)
        if now.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware")
        job.checkpoint = target
        job.state = _STATE_FOR_CHECKPOINT[target]
        if job.started_at is None and target is not ReplacementCheckpoint.CREATED:
            job.started_at = now
        if target in _TERMINAL:
            job.completed_at = now
            job.active_slot = None
        return True
