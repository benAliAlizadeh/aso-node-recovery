from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from app.models import EventType, Node, NodeState
from app.monitoring.types import CheckHostSummary, ReachabilityDecision
from app.services.node_state import NodeStateMachine


@dataclass(frozen=True, slots=True)
class MonitoringPolicy:
    failure_threshold: int = 3
    recovery_threshold: int = 2
    min_success_nodes: int = 3

    def __post_init__(self) -> None:
        if self.failure_threshold < 1:
            raise ValueError("failure_threshold must be positive")
        if self.recovery_threshold < 1:
            raise ValueError("recovery_threshold must be positive")
        if self.min_success_nodes < 1:
            raise ValueError("min_success_nodes must be positive")


@dataclass(frozen=True, slots=True)
class HealthApplicationResult:
    decision: ReachabilityDecision
    previous_state: NodeState
    current_state: NodeState
    event_type: EventType | None = None


class ReachabilityEvaluator:
    @staticmethod
    def evaluate(summary: CheckHostSummary, *, min_success_nodes: int) -> ReachabilityDecision:
        if min_success_nodes < 1:
            raise ValueError("min_success_nodes must be positive")
        if summary.total_nodes < min_success_nodes:
            return ReachabilityDecision.INDETERMINATE
        if summary.success_count >= min_success_nodes:
            return ReachabilityDecision.REACHABLE

        # Only declare unreachable when the remaining pending/malformed probes can no longer satisfy
        # the success quorum. Provider/API ambiguity therefore never becomes a target failure.
        maximum_possible_successes = summary.total_nodes - summary.failure_count
        if maximum_possible_successes < min_success_nodes:
            return ReachabilityDecision.UNREACHABLE
        return ReachabilityDecision.INDETERMINATE


class NodeHealthCalculator:
    """Applies debounced reachability results to node counters/state."""

    MUTABLE_STATES = frozenset(
        {NodeState.UNKNOWN, NodeState.HEALTHY, NodeState.DEGRADED, NodeState.FAILED}
    )

    def __init__(self, policy: MonitoringPolicy) -> None:
        self.policy = policy

    def apply(
        self,
        node: Node,
        decision: ReachabilityDecision,
        *,
        occurred_at: datetime | None = None,
    ) -> HealthApplicationResult:
        timestamp = occurred_at or datetime.now(UTC)
        if timestamp.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware")

        previous = node.state
        node.last_checked_at = timestamp
        if previous not in self.MUTABLE_STATES or decision is ReachabilityDecision.INDETERMINATE:
            return HealthApplicationResult(decision, previous, node.state)

        event_type: EventType | None = None
        if decision is ReachabilityDecision.REACHABLE:
            node.consecutive_failures = 0
            node.consecutive_successes = (node.consecutive_successes or 0) + 1
            node.last_successful_check_at = timestamp
            recovered = (
                previous is not NodeState.HEALTHY
                and node.consecutive_successes >= self.policy.recovery_threshold
            )
            if recovered:
                NodeStateMachine.transition(node, NodeState.HEALTHY, occurred_at=timestamp)
                if previous in {NodeState.DEGRADED, NodeState.FAILED}:
                    event_type = EventType.NODE_RECOVERED
        else:
            node.consecutive_successes = 0
            node.consecutive_failures = (node.consecutive_failures or 0) + 1
            if node.consecutive_failures >= self.policy.failure_threshold:
                if previous is not NodeState.FAILED:
                    NodeStateMachine.transition(node, NodeState.FAILED, occurred_at=timestamp)
                    event_type = EventType.NODE_FAILED
            elif previous in {NodeState.UNKNOWN, NodeState.HEALTHY}:
                NodeStateMachine.transition(node, NodeState.DEGRADED, occurred_at=timestamp)
                event_type = EventType.NODE_DEGRADED

        return HealthApplicationResult(decision, previous, node.state, event_type)
