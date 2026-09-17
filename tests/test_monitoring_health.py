from datetime import UTC, datetime
from uuid import uuid4

from app.models import EventType, Node, NodeState
from app.monitoring.health import MonitoringPolicy, NodeHealthCalculator, ReachabilityEvaluator
from app.monitoring.types import (
    CheckHostSummary,
    ProbeResult,
    ProbeStatus,
    ReachabilityDecision,
)


def make_node() -> Node:
    return Node(
        name="de-07",
        master_node_id="master-node-42",
        provider_id=uuid4(),
        current_host="203.0.113.10",
        current_port=443,
    )


def summary(*statuses: ProbeStatus) -> CheckHostSummary:
    return CheckHostSummary(
        request_id="r1",
        target="203.0.113.10:443",
        probes=tuple(ProbeResult(node=f"ir{i}", status=status) for i, status in enumerate(statuses)),
    )


def test_reachability_requires_success_quorum() -> None:
    result = ReachabilityEvaluator.evaluate(
        summary(ProbeStatus.SUCCESS, ProbeStatus.SUCCESS, ProbeStatus.SUCCESS, ProbeStatus.FAILURE),
        min_success_nodes=3,
    )
    assert result is ReachabilityDecision.REACHABLE


def test_pending_or_malformed_result_does_not_create_false_failure() -> None:
    result = ReachabilityEvaluator.evaluate(
        summary(
            ProbeStatus.FAILURE,
            ProbeStatus.FAILURE,
            ProbeStatus.PENDING,
            ProbeStatus.MALFORMED,
            ProbeStatus.SUCCESS,
        ),
        min_success_nodes=3,
    )
    assert result is ReachabilityDecision.INDETERMINATE


def test_unreachable_only_when_quorum_is_mathematically_impossible() -> None:
    result = ReachabilityEvaluator.evaluate(
        summary(
            ProbeStatus.FAILURE,
            ProbeStatus.FAILURE,
            ProbeStatus.FAILURE,
            ProbeStatus.SUCCESS,
            ProbeStatus.PENDING,
        ),
        min_success_nodes=3,
    )
    assert result is ReachabilityDecision.UNREACHABLE


def test_failure_threshold_degrades_then_fails_once() -> None:
    node = make_node()
    calculator = NodeHealthCalculator(MonitoringPolicy(failure_threshold=3, recovery_threshold=2))
    at = datetime.now(UTC)

    first = calculator.apply(node, ReachabilityDecision.UNREACHABLE, occurred_at=at)
    assert node.state is NodeState.DEGRADED
    assert first.event_type is EventType.NODE_DEGRADED

    second = calculator.apply(node, ReachabilityDecision.UNREACHABLE, occurred_at=at)
    assert node.state is NodeState.DEGRADED
    assert second.event_type is None

    third = calculator.apply(node, ReachabilityDecision.UNREACHABLE, occurred_at=at)
    assert node.state is NodeState.FAILED
    assert third.event_type is EventType.NODE_FAILED
    assert node.consecutive_failures == 3


def test_recovery_requires_multiple_successes() -> None:
    node = make_node()
    calculator = NodeHealthCalculator(MonitoringPolicy(failure_threshold=2, recovery_threshold=2))
    at = datetime.now(UTC)

    calculator.apply(node, ReachabilityDecision.UNREACHABLE, occurred_at=at)
    calculator.apply(node, ReachabilityDecision.UNREACHABLE, occurred_at=at)
    assert node.state is NodeState.FAILED

    first = calculator.apply(node, ReachabilityDecision.REACHABLE, occurred_at=at)
    assert node.state is NodeState.FAILED
    assert first.event_type is None

    second = calculator.apply(node, ReachabilityDecision.REACHABLE, occurred_at=at)
    assert node.state is NodeState.HEALTHY
    assert second.event_type is EventType.NODE_RECOVERED


def test_indeterminate_does_not_modify_failure_or_success_counters() -> None:
    node = make_node()
    node.consecutive_failures = 2
    node.consecutive_successes = 1
    calculator = NodeHealthCalculator(MonitoringPolicy())

    calculator.apply(node, ReachabilityDecision.INDETERMINATE, occurred_at=datetime.now(UTC))

    assert node.consecutive_failures == 2
    assert node.consecutive_successes == 1
    assert node.state is NodeState.UNKNOWN
