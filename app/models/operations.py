from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import (
    DeploymentState,
    EventSeverity,
    EventType,
    NodeCheckOutcome,
    ReplacementCheckpoint,
    ReplacementJobState,
    VpsInstanceRole,
    VpsInstanceState,
)

if TYPE_CHECKING:
    from app.models.node import Node
    from app.models.provider import Provider


def _enum_values(enum_type: type) -> list[str]:
    return [item.value for item in enum_type]


class NodeCheck(UUIDPrimaryKeyMixin, Base):
    """One normalized reachability observation for a node."""

    __tablename__ = "node_checks"
    __table_args__ = (
        CheckConstraint("target_port BETWEEN 1 AND 65535", name="target_port_range"),
        CheckConstraint("success_count >= 0", name="success_count_nonnegative"),
        CheckConstraint("failure_count >= 0", name="failure_count_nonnegative"),
        CheckConstraint("pending_count >= 0", name="pending_count_nonnegative"),
        CheckConstraint("malformed_count >= 0", name="malformed_count_nonnegative"),
        CheckConstraint("total_nodes >= 0", name="total_nodes_nonnegative"),
        Index("ix_node_checks_node_checked_at", "node_id", "checked_at"),
    )

    node_id: Mapped[UUID] = mapped_column(
        ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    target_host: Mapped[str] = mapped_column(String(255), nullable=False)
    target_port: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome: Mapped[NodeCheckOutcome] = mapped_column(
        Enum(
            NodeCheckOutcome,
            values_callable=_enum_values,
            native_enum=False,
            create_constraint=True,
            name="node_check_outcome",
            length=32,
        ),
        nullable=False,
    )
    success_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pending_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    malformed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_nodes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    node: Mapped[Node] = relationship(back_populates="checks")


class VpsInstance(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Provider-neutral record for a current or temporary VPS."""

    __tablename__ = "vps_instances"
    __table_args__ = (
        UniqueConstraint("provider_id", "provider_server_id", name="provider_server_identity"),
        CheckConstraint("host IS NULL OR char_length(host) > 0", name="host_not_blank"),
        Index("ix_vps_instances_node_state", "node_id", "state"),
    )

    provider_id: Mapped[UUID] = mapped_column(
        ForeignKey("providers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    node_id: Mapped[UUID] = mapped_column(
        ForeignKey("nodes.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    provider_server_id: Mapped[str] = mapped_column(String(160), nullable=False)
    role: Mapped[VpsInstanceRole] = mapped_column(
        Enum(
            VpsInstanceRole,
            values_callable=_enum_values,
            native_enum=False,
            create_constraint=True,
            name="vps_instance_role",
            length=32,
        ),
        nullable=False,
    )
    state: Mapped[VpsInstanceState] = mapped_column(
        Enum(
            VpsInstanceState,
            values_callable=_enum_values,
            native_enum=False,
            create_constraint=True,
            name="vps_instance_state",
            length=32,
        ),
        nullable=False,
        default=VpsInstanceState.PROVISIONING,
    )
    host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    region: Mapped[str | None] = mapped_column(String(96), nullable=True)
    server_type: Mapped[str | None] = mapped_column(String(96), nullable=True)

    provider: Mapped[Provider] = relationship(back_populates="vps_instances")
    node: Mapped[Node] = relationship(back_populates="vps_instances")


class ReplacementJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Persisted replacement workflow identity and recovery checkpoint."""

    __tablename__ = "replacement_jobs"
    __table_args__ = (
        UniqueConstraint("node_id", "active_slot", name="one_active_replacement_per_node"),
        CheckConstraint("attempt_count >= 0", name="attempt_count_nonnegative"),
        CheckConstraint("max_attempts > 0", name="max_attempts_positive"),
        Index("ix_replacement_jobs_node_state", "node_id", "state"),
    )

    node_id: Mapped[UUID] = mapped_column(
        ForeignKey("nodes.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    state: Mapped[ReplacementJobState] = mapped_column(
        Enum(
            ReplacementJobState,
            values_callable=_enum_values,
            native_enum=False,
            create_constraint=True,
            name="replacement_job_state",
            length=32,
        ),
        nullable=False,
        default=ReplacementJobState.PENDING,
    )
    checkpoint: Mapped[ReplacementCheckpoint] = mapped_column(
        Enum(
            ReplacementCheckpoint,
            values_callable=_enum_values,
            native_enum=False,
            create_constraint=True,
            name="replacement_checkpoint",
            length=32,
        ),
        nullable=False,
        default=ReplacementCheckpoint.CREATED,
    )
    active_slot: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=True)
    is_dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    old_vps_instance_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("vps_instances.id", ondelete="RESTRICT"), nullable=True
    )
    new_vps_instance_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("vps_instances.id", ondelete="RESTRICT"), nullable=True
    )
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    workflow_lease_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    workflow_lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provisioning_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    master_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    new_ip_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deployment_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    master_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    master_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    final_health_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    old_vps_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    node: Mapped[Node] = relationship(back_populates="replacement_jobs")
    old_vps_instance: Mapped[VpsInstance | None] = relationship(
        foreign_keys=[old_vps_instance_id]
    )
    new_vps_instance: Mapped[VpsInstance | None] = relationship(
        foreign_keys=[new_vps_instance_id]
    )
    deployments: Mapped[list[Deployment]] = relationship(
        back_populates="replacement_job", cascade="all, delete-orphan"
    )


class Deployment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One deployment attempt for a replacement VPS."""

    __tablename__ = "deployments"
    __table_args__ = (
        UniqueConstraint(
            "replacement_job_id", "attempt_number", name="deployment_attempt_per_job"
        ),
        CheckConstraint("attempt_number > 0", name="attempt_number_positive"),
        CheckConstraint(
            "panel_port IS NULL OR panel_port BETWEEN 1 AND 65535",
            name="panel_port_range",
        ),
    )

    replacement_job_id: Mapped[UUID] = mapped_column(
        ForeignKey("replacement_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    vps_instance_id: Mapped[UUID] = mapped_column(
        ForeignKey("vps_instances.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[DeploymentState] = mapped_column(
        Enum(
            DeploymentState,
            values_callable=_enum_values,
            native_enum=False,
            create_constraint=True,
            name="deployment_state",
            length=32,
        ),
        nullable=False,
        default=DeploymentState.PENDING,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    panel_username: Mapped[str | None] = mapped_column(String(128), nullable=True)
    panel_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    web_base_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    access_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    api_token_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    panel_password_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    db_type: Mapped[str | None] = mapped_column(String(32), nullable=True)

    replacement_job: Mapped[ReplacementJob] = relationship(back_populates="deployments")
    vps_instance: Mapped[VpsInstance] = relationship()


class Event(UUIDPrimaryKeyMixin, Base):
    """Append-only audit/event record. Payloads must never contain secret material."""

    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_node_created_at", "node_id", "created_at"),
        Index("ix_events_job_created_at", "replacement_job_id", "created_at"),
    )

    node_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("nodes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    replacement_job_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("replacement_jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    event_type: Mapped[EventType] = mapped_column(
        Enum(
            EventType,
            values_callable=_enum_values,
            native_enum=False,
            create_constraint=True,
            name="event_type",
            length=64,
        ),
        nullable=False,
    )
    severity: Mapped[EventSeverity] = mapped_column(
        Enum(
            EventSeverity,
            values_callable=_enum_values,
            native_enum=False,
            create_constraint=True,
            name="event_severity",
            length=16,
        ),
        nullable=False,
        default=EventSeverity.INFO,
    )
    message: Mapped[str] = mapped_column(String(500), nullable=False)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SystemSetting(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Operational setting. Secret values are explicitly out of scope for this table."""

    __tablename__ = "settings"
    __table_args__ = (CheckConstraint("char_length(key) > 0", name="key_not_blank"),)

    key: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    value: Mapped[Any] = mapped_column(JSON, nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
