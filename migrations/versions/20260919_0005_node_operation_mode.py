"""add per-node monitoring and auto-repair mode

Revision ID: 20260919_0005
Revises: 20260919_0004
Create Date: 2026-09-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260919_0005"
down_revision: str | None = "20260919_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "nodes",
        sa.Column(
            "operation_mode",
            sa.String(length=32),
            nullable=False,
            server_default="monitor_only",
        ),
    )
    # Preserve the intent of installations that had monitoring explicitly disabled.
    op.execute(
        "UPDATE nodes SET operation_mode = 'disabled' WHERE monitoring_enabled = false OR state = 'disabled'"
    )
    op.create_check_constraint(
        "node_operation_mode",
        "nodes",
        "operation_mode IN ('disabled', 'monitor_only', 'auto_repair')",
    )
    op.alter_column("nodes", "operation_mode", server_default=None)


def downgrade() -> None:
    op.drop_constraint(op.f("ck_nodes_node_operation_mode"), "nodes", type_="check")
    op.drop_column("nodes", "operation_mode")
