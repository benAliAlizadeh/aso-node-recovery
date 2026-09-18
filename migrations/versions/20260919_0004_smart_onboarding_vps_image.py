"""store node-specific VPS image for smart onboarding

Revision ID: 20260919_0004
Revises: 20260917_0003
Create Date: 2026-09-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260919_0004"
down_revision: str | None = "20260917_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("vps_instances", sa.Column("image", sa.String(length=160), nullable=True))


def downgrade() -> None:
    op.drop_column("vps_instances", "image")
