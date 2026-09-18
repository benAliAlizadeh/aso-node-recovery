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
    def transition_forced_replacement(
        cls,
        node: Node,
        *,
        occurred_at: datetime | None = None,
    ) -> bool:
        """Enter replacement from a non-disabled operational state for an explicit force repair.

        This is intentionally separate from the normal transition graph so ordinary monitoring
        cannot move a healthy node into replacement.
        """
        if node.state is NodeState.DISABLED:
            raise InvalidNodeStateTransitionError(
                "Force repair is not allowed while the node is disabled"
            )
        if node.state in {NodeState.REPLACING, NodeState.DEPLOYING, NodeState.VERIFYING}:
            raise InvalidNodeStateTransitionError(
                f"Force repair cannot start from active workflow state: {node.state.value}"
            )
        if node.state is NodeState.REPLACING:
            return False
        transition_time = occurred_at or datetime.now(UTC)
        if transition_time.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware")
        node._apply_state_transition(NodeState.REPLACING, transition_time)
        return True

    @classmethod
    def restore_after_forced_replacement(
        cls,
        node: Node,
        original_state: NodeState,
        *,
        occurred_at: datetime | None = None,
    ) -> bool:
        """Restore a pre-switch forced repair to its original state.

        Only active replacement workflow states may be restored and DISABLED is never synthesized.
        """
        if original_state not in {
            NodeState.UNKNOWN,
            NodeState.HEALTHY,
            NodeState.DEGRADED,
            NodeState.FAILED,
        }:
            raise InvalidNodeStateTransitionError(
                f"Invalid forced-repair restore target: {original_state.value}"
            )
        if node.state not in {NodeState.REPLACING, NodeState.DEPLOYING, NodeState.VERIFYING}:
            if node.state is original_state:
                return False
            raise InvalidNodeStateTransitionError(
                f"Cannot restore forced repair from state: {node.state.value}"
            )
        transition_time = occurred_at or datetime.now(UTC)
        if transition_time.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware")
        node._apply_state_transition(original_state, transition_time)
        return True

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
