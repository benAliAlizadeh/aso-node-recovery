from __future__ import annotations

from datetime import UTC, datetime
from types import MappingProxyType

from app.core.errors import AsoError
from app.models.enums import NodeState
from app.models.node import Node


class InvalidNodeStateTransitionError(AsoError):
    """Raised when code attempts a transition outside the approved node state graph."""


_ALLOWED_TRANSITIONS = MappingProxyType(
    {
        NodeState.UNKNOWN: frozenset(
            {NodeState.HEALTHY, NodeState.DEGRADED, NodeState.FAILED, NodeState.DISABLED}
        ),
        NodeState.HEALTHY: frozenset({NodeState.DEGRADED, NodeState.DISABLED}),
        NodeState.DEGRADED: frozenset(
            {NodeState.HEALTHY, NodeState.FAILED, NodeState.DISABLED}
        ),
        NodeState.FAILED: frozenset(
            {NodeState.HEALTHY, NodeState.REPLACING, NodeState.DISABLED}
        ),
        NodeState.REPLACING: frozenset(
            {NodeState.DEPLOYING, NodeState.FAILED, NodeState.DISABLED}
        ),
        NodeState.DEPLOYING: frozenset(
            {NodeState.VERIFYING, NodeState.REPLACING, NodeState.FAILED, NodeState.DISABLED}
        ),
        NodeState.VERIFYING: frozenset(
            {NodeState.HEALTHY, NodeState.REPLACING, NodeState.FAILED, NodeState.DISABLED}
        ),
        NodeState.DISABLED: frozenset({NodeState.UNKNOWN}),
    }
)


class NodeStateMachine:
    """Single authority for node state transitions.

    Re-applying the current state is intentionally idempotent and does not move
    ``state_changed_at``. This makes retries safe without weakening transition validation.
    """

    @staticmethod
    def allowed_targets(current: NodeState) -> frozenset[NodeState]:
        return _ALLOWED_TRANSITIONS[current]

    @classmethod
    def can_transition(cls, current: NodeState, target: NodeState) -> bool:
        return target == current or target in cls.allowed_targets(current)

    @classmethod
    def transition(
        cls,
        node: Node,
        target: NodeState,
        *,
        occurred_at: datetime | None = None,
    ) -> bool:
        current = node.state
        if target == current:
            return False
        if target not in cls.allowed_targets(current):
            raise InvalidNodeStateTransitionError(
                f"Invalid node state transition: {current.value} -> {target.value}"
            )

        transition_time = occurred_at or datetime.now(UTC)
        if transition_time.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware")

        node._apply_state_transition(target, transition_time)
        return True
