"""phase 7 control-plane audit events

Revision ID: 20260917_0003
Revises: 20260917_0002
Create Date: 2026-09-17
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260917_0003"
down_revision: str | None = "20260917_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BASE_EVENT_TYPES = (
    "node_failed",
    "node_recovered",
    "node_degraded",
    "monitoring_check_error",
    "replacement_started",
    "vps_created",
    "ip_check_started",
    "ip_check_failed",
    "ip_check_passed",
    "deployment_started",
    "deployment_failed",
    "master_updated",
    "master_verified",
    "old_vps_deleted",
    "replacement_completed",
    "replacement_failed",
)
_PHASE7_EVENT_TYPES = _BASE_EVENT_TYPES + (
    "control_action",
    "setting_changed",
    "system_paused",
    "system_resumed",
    "provider_updated",
)


def _expression(values: tuple[str, ...]) -> str:
    quoted = ",".join(f"'{value}'" for value in values)
    return f"event_type IN ({quoted})"


def upgrade() -> None:
    op.drop_constraint(op.f("ck_events_event_type"), "events", type_="check")
    op.create_check_constraint(
        op.f("ck_events_event_type"),
        "events",
        _expression(_PHASE7_EVENT_TYPES),
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_events_event_type"), "events", type_="check")
    op.create_check_constraint(
        op.f("ck_events_event_type"),
        "events",
        _expression(_BASE_EVENT_TYPES),
    )
