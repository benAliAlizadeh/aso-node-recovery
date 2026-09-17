"""master client and crash-resumable replacement workflow

Revision ID: 20260917_0002
Revises: 20260917_0001
Create Date: 2026-09-17
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260917_0002"
down_revision: str | None = "20260917_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SECRET_BACKENDS = "'environment','file','external','database_encrypted'"
_CHECKPOINTS = (
    "'created','provisioning','provisioned','checking_ip','temp_cleanup','ip_verified',"
    "'deploying','node_verified','master_updating','master_updated','master_verifying',"
    "'master_verified','final_check','final_verified','old_vps_cleanup','completed','failed','cancelled'"
)


def upgrade() -> None:
    op.add_column("providers", sa.Column("default_region", sa.String(length=96), nullable=True))
    op.add_column(
        "providers", sa.Column("default_server_type", sa.String(length=96), nullable=True)
    )
    op.add_column("providers", sa.Column("default_image", sa.String(length=160), nullable=True))
    op.create_check_constraint(
        op.f("ck_providers_default_region_not_blank"),
        "providers",
        "default_region IS NULL OR char_length(default_region) > 0",
    )
    op.create_check_constraint(
        op.f("ck_providers_default_server_type_not_blank"),
        "providers",
        "default_server_type IS NULL OR char_length(default_server_type) > 0",
    )
    op.create_check_constraint(
        op.f("ck_providers_default_image_not_blank"),
        "providers",
        "default_image IS NULL OR char_length(default_image) > 0",
    )

    op.add_column(
        "node_credentials", sa.Column("ssh_public_key", sa.String(length=1024), nullable=True)
    )
    op.add_column(
        "node_credentials", sa.Column("panel_base_path", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "node_credentials",
        sa.Column("panel_password_backend", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "node_credentials",
        sa.Column("api_token_backend", sa.String(length=32), nullable=True),
    )
    op.create_check_constraint(
        op.f("ck_node_credentials_panel_password_secret_backend"),
        "node_credentials",
        f"panel_password_backend IS NULL OR panel_password_backend IN ({_SECRET_BACKENDS})",
    )
    op.create_check_constraint(
        op.f("ck_node_credentials_api_token_secret_backend"),
        "node_credentials",
        f"api_token_backend IS NULL OR api_token_backend IN ({_SECRET_BACKENDS})",
    )

    op.add_column(
        "replacement_jobs",
        sa.Column(
            "checkpoint",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'created'"),
        ),
    )
    op.create_check_constraint(
        op.f("ck_replacement_jobs_replacement_checkpoint"),
        "replacement_jobs",
        f"checkpoint IN ({_CHECKPOINTS})",
    )
    op.add_column(
        "replacement_jobs",
        sa.Column("is_dry_run", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "replacement_jobs", sa.Column("workflow_lease_token", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "replacement_jobs", sa.Column("workflow_lease_until", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "replacement_jobs",
        sa.Column("provisioning_requested_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("replacement_jobs", sa.Column("master_snapshot", sa.JSON(), nullable=True))
    op.add_column(
        "replacement_jobs", sa.Column("new_ip_verified_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "replacement_jobs",
        sa.Column("deployment_verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "replacement_jobs", sa.Column("master_updated_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "replacement_jobs", sa.Column("master_verified_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "replacement_jobs",
        sa.Column("final_health_verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "replacement_jobs", sa.Column("old_vps_deleted_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.alter_column("replacement_jobs", "checkpoint", server_default=None)
    op.alter_column("replacement_jobs", "is_dry_run", server_default=None)

    op.add_column("deployments", sa.Column("panel_username", sa.String(length=128), nullable=True))
    op.add_column("deployments", sa.Column("panel_port", sa.Integer(), nullable=True))
    op.add_column("deployments", sa.Column("web_base_path", sa.String(length=255), nullable=True))
    op.add_column("deployments", sa.Column("access_url", sa.String(length=1024), nullable=True))
    op.add_column("deployments", sa.Column("api_token_ref", sa.String(length=255), nullable=True))
    op.add_column(
        "deployments", sa.Column("panel_password_ref", sa.String(length=255), nullable=True)
    )
    op.add_column("deployments", sa.Column("db_type", sa.String(length=32), nullable=True))
    op.create_check_constraint(
        op.f("ck_deployments_panel_port_range"),
        "deployments",
        "panel_port IS NULL OR panel_port BETWEEN 1 AND 65535",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_deployments_panel_port_range"), "deployments", type_="check")
    for column in (
        "db_type",
        "panel_password_ref",
        "api_token_ref",
        "access_url",
        "web_base_path",
        "panel_port",
        "panel_username",
    ):
        op.drop_column("deployments", column)

    for column in (
        "old_vps_deleted_at",
        "final_health_verified_at",
        "master_verified_at",
        "master_updated_at",
        "deployment_verified_at",
        "new_ip_verified_at",
        "master_snapshot",
        "provisioning_requested_at",
        "workflow_lease_until",
        "workflow_lease_token",
        "is_dry_run",
    ):
        op.drop_column("replacement_jobs", column)
    op.drop_constraint(
        op.f("ck_replacement_jobs_replacement_checkpoint"),
        "replacement_jobs",
        type_="check",
    )
    op.drop_column("replacement_jobs", "checkpoint")

    op.drop_constraint(
        op.f("ck_node_credentials_api_token_secret_backend"),
        "node_credentials",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_node_credentials_panel_password_secret_backend"),
        "node_credentials",
        type_="check",
    )
    for column in (
        "api_token_backend",
        "panel_password_backend",
        "panel_base_path",
        "ssh_public_key",
    ):
        op.drop_column("node_credentials", column)

    op.drop_constraint(op.f("ck_providers_default_image_not_blank"), "providers", type_="check")
    op.drop_constraint(
        op.f("ck_providers_default_server_type_not_blank"), "providers", type_="check"
    )
    op.drop_constraint(op.f("ck_providers_default_region_not_blank"), "providers", type_="check")
    op.drop_column("providers", "default_image")
    op.drop_column("providers", "default_server_type")
    op.drop_column("providers", "default_region")
