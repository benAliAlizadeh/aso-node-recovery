from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import inspect

from app.bot.callbacks import CallbackSigner
from app.models import (
    Node,
    NodeState,
    ReplacementJob,
    ReplacementTriggerMode,
)
from app.services import InvalidNodeStateTransitionError, NodeStateMachine

ROOT = Path(__file__).resolve().parents[1]


def make_node(state: NodeState) -> Node:
    node = Node(
        name="force-node",
        master_node_id="42",
        provider_id=uuid4(),
        current_host="203.0.113.10",
        current_port=443,
    )
    if state is not NodeState.UNKNOWN:
        NodeStateMachine.transition(node, state)
    return node


@pytest.mark.parametrize(
    "state",
    [NodeState.UNKNOWN, NodeState.HEALTHY, NodeState.DEGRADED, NodeState.FAILED],
)
def test_force_repair_can_enter_replacing_from_operational_states(state: NodeState) -> None:
    node = make_node(state)
    assert NodeStateMachine.transition_forced_replacement(node) is True
    assert node.state is NodeState.REPLACING


def test_force_repair_refuses_disabled_node() -> None:
    node = make_node(NodeState.DISABLED)
    with pytest.raises(InvalidNodeStateTransitionError, match="disabled"):
        NodeStateMachine.transition_forced_replacement(node)


def test_pre_switch_force_failure_can_restore_original_state() -> None:
    node = make_node(NodeState.HEALTHY)
    NodeStateMachine.transition_forced_replacement(node)
    assert NodeStateMachine.restore_after_forced_replacement(node, NodeState.HEALTHY) is True
    assert node.state is NodeState.HEALTHY


def test_force_metadata_is_durable_and_request_key_is_unique() -> None:
    table = inspect(ReplacementJob).local_table
    assert table.c.trigger_mode.nullable is False
    assert table.c.request_key.nullable is True
    assert table.c.original_node_state.nullable is True
    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("request_key",) in unique_columns
    job = ReplacementJob(node_id=uuid4(), trigger_mode=ReplacementTriggerMode.FORCE)
    assert job.trigger_mode is ReplacementTriggerMode.FORCE


def test_force_confirmation_callback_fits_telegram_limit() -> None:
    signer = CallbackSigner(SecretStr("s" * 32))
    payload = signer.encode("fc", uuid4(), 100, now=6000)
    assert len(payload.encode("utf-8")) <= 64
    verified = signer.verify(payload, 100, expected_action="fc", now=6000)
    assert verified.action == "fc"


def test_force_repair_ui_and_orchestrator_keep_downstream_safety_gates() -> None:
    bot = (ROOT / "app" / "bot" / "application.py").read_text(encoding="utf-8")
    orchestrator = (ROOT / "app" / "replacement" / "orchestrator.py").read_text(
        encoding="utf-8"
    )
    safety = (ROOT / "app" / "replacement" / "safety.py").read_text(encoding="utf-8")

    assert "⚠️ Force Repair" in bot
    assert 'self.signer.encode("fc"' in bot
    assert "trigger_force_repair" in bot
    assert "request_key = self._force_request_key" in bot
    assert "force: bool = False" in orchestrator
    assert "replacement requires FAILED node" in orchestrator
    assert "NodeStateMachine.transition_forced_replacement" in orchestrator
    assert "ReplacementCheckpoint.FINAL_CHECK" in orchestrator
    assert "allow_old_vps_deletion" in orchestrator
    assert "final_health_verified" in safety
    assert "master_verified" in safety
