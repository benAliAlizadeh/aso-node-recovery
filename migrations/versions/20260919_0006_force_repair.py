"""add durable force-repair metadata and request idempotency

Revision ID: 20260919_0006
Revises: 20260919_0005
Create Date: 2026-09-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260919_0006"
down_revision: str | None = "20260919_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "replacement_jobs",
        sa.Column(
            "trigger_mode",
            sa.String(length=16),
            nullable=False,
            server_default="standard",
        ),
    )
    op.add_column(
        "replacement_jobs",
        sa.Column("request_key", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "replacement_jobs",
        sa.Column("original_node_state", sa.String(length=32), nullable=True),
    )
    op.create_check_constraint(
        "replacement_trigger_mode",
        "replacement_jobs",
        "trigger_mode IN ('standard', 'force')",
    )
    op.create_check_constraint(
        "replacement_original_node_state",
        "replacement_jobs",
        "original_node_state IS NULL OR original_node_state IN "
        "('unknown', 'healthy', 'degraded', 'failed')",
    )
    op.create_unique_constraint(
        "replacement_request_key_unique",
        "replacement_jobs",
        ["request_key"],
    )
    op.alter_column("replacement_jobs", "trigger_mode", server_default=None)


def downgrade() -> None:
    op.drop_constraint(
        "replacement_request_key_unique",
        "replacement_jobs",
        type_="unique",
    )
    op.drop_constraint(
        op.f("ck_replacement_jobs_replacement_original_node_state"),
        "replacement_jobs",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_replacement_jobs_replacement_trigger_mode"),
        "replacement_jobs",
        type_="check",
    )
    op.drop_column("replacement_jobs", "original_node_state")
    op.drop_column("replacement_jobs", "request_key")
    op.drop_column("replacement_jobs", "trigger_mode")
