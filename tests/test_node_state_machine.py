from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.models import Node, NodeState
from app.services import InvalidNodeStateTransitionError, NodeStateMachine


def make_node() -> Node:
    return Node(
        name="de-07",
        master_node_id="master-node-42",
        provider_id=uuid4(),
        current_host="203.0.113.10",
        current_port=443,
    )


def test_expected_replacement_path_is_allowed() -> None:
    node = make_node()
    assert node.state == NodeState.UNKNOWN

    path = [
        NodeState.HEALTHY,
        NodeState.DEGRADED,
        NodeState.FAILED,
        NodeState.REPLACING,
        NodeState.DEPLOYING,
        NodeState.VERIFYING,
        NodeState.HEALTHY,
    ]

    for target in path:
        assert NodeStateMachine.transition(node, target) is True
        assert node.state == target


def test_arbitrary_transition_is_rejected() -> None:
    node = make_node()

    with pytest.raises(InvalidNodeStateTransitionError):
        NodeStateMachine.transition(node, NodeState.DEPLOYING)

    assert node.state == NodeState.UNKNOWN


def test_public_state_property_cannot_be_assigned_directly() -> None:
    node = make_node()

    with pytest.raises(AttributeError):
        node.state = NodeState.FAILED  # type: ignore[misc]


def test_same_state_transition_is_idempotent() -> None:
    node = make_node()
    original_changed_at = node.state_changed_at

    assert NodeStateMachine.transition(node, NodeState.UNKNOWN) is False
    assert node.state_changed_at == original_changed_at


def test_transition_records_explicit_timestamp() -> None:
    node = make_node()
    transition_time = datetime.now(UTC) + timedelta(seconds=1)

    NodeStateMachine.transition(node, NodeState.HEALTHY, occurred_at=transition_time)

    assert node.state_changed_at == transition_time


def test_naive_transition_timestamp_is_rejected() -> None:
    node = make_node()

    with pytest.raises(ValueError, match="timezone-aware"):
        NodeStateMachine.transition(
            node,
            NodeState.HEALTHY,
            occurred_at=datetime(2026, 9, 17, 12, 0, 0),
        )
