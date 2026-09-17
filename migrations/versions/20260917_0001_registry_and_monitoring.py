"""registry and monitoring schema

Revision ID: 20260917_0001
Revises:
Create Date: 2026-09-17
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260917_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _enum(name: str, *values: str, length: int = 32) -> sa.Enum:
    return sa.Enum(
        *values,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=length,
    )


def upgrade() -> None:
    op.create_table(
        "providers",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column(
            "provider_type",
            _enum("provider_type", "hetzner", "linode"),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column(
            "credential_backend",
            _enum(
                "secret_reference_backend",
                "environment",
                "file",
                "external",
                "database_encrypted",
            ),
            nullable=False,
        ),
        sa.Column("credential_ref", sa.String(length=255), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("char_length(key) > 0", name=op.f("ck_providers_key_not_blank")),
        sa.CheckConstraint("char_length(display_name) > 0", name=op.f("ck_providers_display_name_not_blank")),
        sa.CheckConstraint("char_length(credential_ref) > 0", name=op.f("ck_providers_credential_ref_not_blank")),
        sa.PrimaryKeyConstraint("id", name="pk_providers"),
        sa.UniqueConstraint("key", name="uq_providers_key"),
    )

    op.create_table(
        "settings",
        sa.Column("key", sa.String(length=160), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("char_length(key) > 0", name=op.f("ck_settings_key_not_blank")),
        sa.PrimaryKeyConstraint("id", name="pk_settings"),
        sa.UniqueConstraint("key", name="uq_settings_key"),
    )

    op.create_table(
        "nodes",
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("master_node_id", sa.String(length=128), nullable=False),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("current_host", sa.String(length=255), nullable=False),
        sa.Column("current_port", sa.Integer(), nullable=False),
        sa.Column(
            "state",
            _enum(
                "node_state",
                "unknown",
                "healthy",
                "degraded",
                "failed",
                "replacing",
                "deploying",
                "verifying",
                "disabled",
            ),
            nullable=False,
        ),
        sa.Column("state_changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("monitoring_enabled", sa.Boolean(), nullable=False),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False),
        sa.Column("consecutive_successes", sa.Integer(), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_successful_check_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("monitoring_lease_token", sa.String(length=64), nullable=True),
        sa.Column("monitoring_lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("char_length(name) > 0", name=op.f("ck_nodes_name_not_blank")),
        sa.CheckConstraint("char_length(master_node_id) > 0", name=op.f("ck_nodes_master_node_id_not_blank")),
        sa.CheckConstraint("char_length(current_host) > 0", name=op.f("ck_nodes_current_host_not_blank")),
        sa.CheckConstraint("current_port BETWEEN 1 AND 65535", name=op.f("ck_nodes_current_port_range")),
        sa.CheckConstraint("consecutive_failures >= 0", name=op.f("ck_nodes_consecutive_failures_nonnegative")),
        sa.CheckConstraint("consecutive_successes >= 0", name=op.f("ck_nodes_consecutive_successes_nonnegative")),
        sa.ForeignKeyConstraint(["provider_id"], ["providers.id"], name="fk_nodes_provider_id_providers", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_nodes"),
        sa.UniqueConstraint("master_node_id", name="uq_nodes_master_node_id"),
        sa.UniqueConstraint("name", name="uq_nodes_name"),
    )
    op.create_index("ix_nodes_provider_id", "nodes", ["provider_id"], unique=False)
    op.create_index("ix_nodes_provider_state", "nodes", ["provider_id", "state"], unique=False)

    op.create_table(
        "node_credentials",
        sa.Column("node_id", sa.Uuid(), nullable=False),
        sa.Column("ssh_username", sa.String(length=64), nullable=False),
        sa.Column("ssh_port", sa.Integer(), nullable=False),
        sa.Column("ssh_auth_method", _enum("ssh_auth_method", "private_key", "password"), nullable=False),
        sa.Column(
            "secret_backend",
            _enum(
                "node_secret_reference_backend",
                "environment",
                "file",
                "external",
                "database_encrypted",
            ),
            nullable=False,
        ),
        sa.Column("ssh_secret_ref", sa.String(length=255), nullable=False),
        sa.Column("panel_username", sa.String(length=128), nullable=True),
        sa.Column("panel_password_ref", sa.String(length=255), nullable=True),
        sa.Column("api_token_ref", sa.String(length=255), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("char_length(ssh_username) > 0", name=op.f("ck_node_credentials_ssh_username_not_blank")),
        sa.CheckConstraint("ssh_port BETWEEN 1 AND 65535", name=op.f("ck_node_credentials_ssh_port_range")),
        sa.CheckConstraint("char_length(ssh_secret_ref) > 0", name=op.f("ck_node_credentials_ssh_secret_ref_not_blank")),
        sa.ForeignKeyConstraint(["node_id"], ["nodes.id"], name="fk_node_credentials_node_id_nodes", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_node_credentials"),
        sa.UniqueConstraint("node_id", name="uq_node_credentials_node_id"),
    )

    op.create_table(
        "node_checks",
        sa.Column("node_id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column("target_host", sa.String(length=255), nullable=False),
        sa.Column("target_port", sa.Integer(), nullable=False),
        sa.Column("outcome", _enum("node_check_outcome", "reachable", "unreachable", "indeterminate", "error"), nullable=False),
        sa.Column("success_count", sa.Integer(), nullable=False),
        sa.Column("failure_count", sa.Integer(), nullable=False),
        sa.Column("pending_count", sa.Integer(), nullable=False),
        sa.Column("malformed_count", sa.Integer(), nullable=False),
        sa.Column("total_nodes", sa.Integer(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("target_port BETWEEN 1 AND 65535", name=op.f("ck_node_checks_target_port_range")),
        sa.CheckConstraint("success_count >= 0", name=op.f("ck_node_checks_success_count_nonnegative")),
        sa.CheckConstraint("failure_count >= 0", name=op.f("ck_node_checks_failure_count_nonnegative")),
        sa.CheckConstraint("pending_count >= 0", name=op.f("ck_node_checks_pending_count_nonnegative")),
        sa.CheckConstraint("malformed_count >= 0", name=op.f("ck_node_checks_malformed_count_nonnegative")),
        sa.CheckConstraint("total_nodes >= 0", name=op.f("ck_node_checks_total_nodes_nonnegative")),
        sa.ForeignKeyConstraint(["node_id"], ["nodes.id"], name="fk_node_checks_node_id_nodes", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_node_checks"),
    )
    op.create_index("ix_node_checks_node_id", "node_checks", ["node_id"], unique=False)
    op.create_index("ix_node_checks_node_checked_at", "node_checks", ["node_id", "checked_at"], unique=False)

    op.create_table(
        "vps_instances",
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("node_id", sa.Uuid(), nullable=False),
        sa.Column("provider_server_id", sa.String(length=160), nullable=False),
        sa.Column("role", _enum("vps_instance_role", "current", "replacement"), nullable=False),
        sa.Column("state", _enum("vps_instance_state", "provisioning", "running", "deleting", "deleted", "error"), nullable=False),
        sa.Column("host", sa.String(length=255), nullable=True),
        sa.Column("region", sa.String(length=96), nullable=True),
        sa.Column("server_type", sa.String(length=96), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("host IS NULL OR char_length(host) > 0", name=op.f("ck_vps_instances_host_not_blank")),
        sa.ForeignKeyConstraint(["node_id"], ["nodes.id"], name="fk_vps_instances_node_id_nodes", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["provider_id"], ["providers.id"], name="fk_vps_instances_provider_id_providers", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_vps_instances"),
        sa.UniqueConstraint("provider_id", "provider_server_id", name="provider_server_identity"),
    )
    op.create_index("ix_vps_instances_node_id", "vps_instances", ["node_id"], unique=False)
    op.create_index("ix_vps_instances_provider_id", "vps_instances", ["provider_id"], unique=False)
    op.create_index("ix_vps_instances_node_state", "vps_instances", ["node_id", "state"], unique=False)

    op.create_table(
        "replacement_jobs",
        sa.Column("node_id", sa.Uuid(), nullable=False),
        sa.Column(
            "state",
            _enum(
                "replacement_job_state",
                "pending",
                "provisioning",
                "checking_ip",
                "deploying",
                "updating_master",
                "verifying",
                "cleaning_up",
                "completed",
                "failed",
                "cancelled",
            ),
            nullable=False,
        ),
        sa.Column("active_slot", sa.Boolean(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("old_vps_instance_id", sa.Uuid(), nullable=True),
        sa.Column("new_vps_instance_id", sa.Uuid(), nullable=True),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("attempt_count >= 0", name=op.f("ck_replacement_jobs_attempt_count_nonnegative")),
        sa.CheckConstraint("max_attempts > 0", name=op.f("ck_replacement_jobs_max_attempts_positive")),
        sa.ForeignKeyConstraint(["new_vps_instance_id"], ["vps_instances.id"], name="fk_replacement_jobs_new_vps_instance_id_vps_instances", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["node_id"], ["nodes.id"], name="fk_replacement_jobs_node_id_nodes", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["old_vps_instance_id"], ["vps_instances.id"], name="fk_replacement_jobs_old_vps_instance_id_vps_instances", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_replacement_jobs"),
        sa.UniqueConstraint("node_id", "active_slot", name="one_active_replacement_per_node"),
    )
    op.create_index("ix_replacement_jobs_node_id", "replacement_jobs", ["node_id"], unique=False)
    op.create_index("ix_replacement_jobs_node_state", "replacement_jobs", ["node_id", "state"], unique=False)

    op.create_table(
        "deployments",
        sa.Column("replacement_job_id", sa.Uuid(), nullable=False),
        sa.Column("vps_instance_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("state", _enum("deployment_state", "pending", "waiting_ssh", "bootstrapping", "installing", "verifying", "succeeded", "failed"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("attempt_number > 0", name=op.f("ck_deployments_attempt_number_positive")),
        sa.ForeignKeyConstraint(["replacement_job_id"], ["replacement_jobs.id"], name="fk_deployments_replacement_job_id_replacement_jobs", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["vps_instance_id"], ["vps_instances.id"], name="fk_deployments_vps_instance_id_vps_instances", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_deployments"),
        sa.UniqueConstraint("replacement_job_id", "attempt_number", name="deployment_attempt_per_job"),
    )
    op.create_index("ix_deployments_replacement_job_id", "deployments", ["replacement_job_id"], unique=False)
    op.create_index("ix_deployments_vps_instance_id", "deployments", ["vps_instance_id"], unique=False)

    op.create_table(
        "events",
        sa.Column("node_id", sa.Uuid(), nullable=True),
        sa.Column("replacement_job_id", sa.Uuid(), nullable=True),
        sa.Column(
            "event_type",
            _enum(
                "event_type",
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
                length=64,
            ),
            nullable=False,
        ),
        sa.Column("severity", _enum("event_severity", "info", "warning", "error", "critical", length=16), nullable=False),
        sa.Column("message", sa.String(length=500), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["node_id"], ["nodes.id"], name="fk_events_node_id_nodes", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["replacement_job_id"], ["replacement_jobs.id"], name="fk_events_replacement_job_id_replacement_jobs", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_events"),
    )
    op.create_index("ix_events_node_id", "events", ["node_id"], unique=False)
    op.create_index("ix_events_replacement_job_id", "events", ["replacement_job_id"], unique=False)
    op.create_index("ix_events_node_created_at", "events", ["node_id", "created_at"], unique=False)
    op.create_index("ix_events_job_created_at", "events", ["replacement_job_id", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_table("events")
    op.drop_table("deployments")
    op.drop_table("replacement_jobs")
    op.drop_table("vps_instances")
    op.drop_table("node_checks")
    op.drop_table("node_credentials")
    op.drop_table("nodes")
    op.drop_table("settings")
    op.drop_table("providers")
