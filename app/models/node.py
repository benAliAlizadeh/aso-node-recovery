from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import NodeState, SecretReferenceBackend, SshAuthMethod

if TYPE_CHECKING:
    from app.models.operations import NodeCheck, ReplacementJob, VpsInstance
    from app.models.provider import Provider


def _enum_values(
    enum_type: type[NodeState] | type[SecretReferenceBackend] | type[SshAuthMethod],
) -> list[str]:
    return [item.value for item in enum_type]


class Node(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Local registry record for one remote 3X-UI node.

    ``master_node_id`` is the explicit durable mapping to the master 3X-UI record. The mapping must
    never be inferred from the current IP address.
    """

    __tablename__ = "nodes"
    __table_args__ = (
        CheckConstraint("char_length(name) > 0", name="name_not_blank"),
        CheckConstraint("char_length(master_node_id) > 0", name="master_node_id_not_blank"),
        CheckConstraint("char_length(current_host) > 0", name="current_host_not_blank"),
        CheckConstraint("current_port BETWEEN 1 AND 65535", name="current_port_range"),
        CheckConstraint("consecutive_failures >= 0", name="consecutive_failures_nonnegative"),
        CheckConstraint("consecutive_successes >= 0", name="consecutive_successes_nonnegative"),
        Index("ix_nodes_provider_state", "provider_id", "state"),
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    master_node_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    provider_id: Mapped[UUID] = mapped_column(
        ForeignKey("providers.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    current_host: Mapped[str] = mapped_column(String(255), nullable=False)
    current_port: Mapped[int] = mapped_column(Integer, nullable=False)

    _state: Mapped[NodeState] = mapped_column(
        "state",
        Enum(
            NodeState,
            values_callable=_enum_values,
            native_enum=False,
            create_constraint=True,
            name="node_state",
            length=32,
        ),
        nullable=False,
        default=NodeState.UNKNOWN,
    )
    state_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    monitoring_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    consecutive_successes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_successful_check_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    monitoring_lease_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    monitoring_lease_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    provider: Mapped[Provider] = relationship(back_populates="nodes")
    checks: Mapped[list[NodeCheck]] = relationship(
        back_populates="node", cascade="all, delete-orphan"
    )
    replacement_jobs: Mapped[list[ReplacementJob]] = relationship(back_populates="node")
    vps_instances: Mapped[list[VpsInstance]] = relationship(back_populates="node")
    credentials: Mapped[NodeCredential | None] = relationship(
        back_populates="node",
        cascade="all, delete-orphan",
        single_parent=True,
        uselist=False,
    )

    @property
    def state(self) -> NodeState:
        """Read-only public state; mutations must go through ``NodeStateMachine``."""
        return self._state or NodeState.UNKNOWN

    def _apply_state_transition(self, state: NodeState, occurred_at: datetime) -> None:
        """Internal mutation hook reserved for the central state machine."""
        self._state = state
        self.state_changed_at = occurred_at


class NodeCredential(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Connection metadata and secret references for a node.

    Raw passwords, private keys, panel passwords, and API tokens are intentionally not modeled as
    plaintext columns. A later credential resolver is responsible for resolving these references.
    """

    __tablename__ = "node_credentials"
    __table_args__ = (
        CheckConstraint("char_length(ssh_username) > 0", name="ssh_username_not_blank"),
        CheckConstraint("ssh_port BETWEEN 1 AND 65535", name="ssh_port_range"),
        CheckConstraint("char_length(ssh_secret_ref) > 0", name="ssh_secret_ref_not_blank"),
    )

    node_id: Mapped[UUID] = mapped_column(
        ForeignKey("nodes.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    ssh_username: Mapped[str] = mapped_column(String(64), nullable=False, default="root")
    ssh_port: Mapped[int] = mapped_column(Integer, nullable=False, default=22)
    ssh_auth_method: Mapped[SshAuthMethod] = mapped_column(
        Enum(
            SshAuthMethod,
            values_callable=_enum_values,
            native_enum=False,
            create_constraint=True,
            name="ssh_auth_method",
            length=32,
        ),
        nullable=False,
        default=SshAuthMethod.PRIVATE_KEY,
    )
    secret_backend: Mapped[SecretReferenceBackend] = mapped_column(
        Enum(
            SecretReferenceBackend,
            values_callable=_enum_values,
            native_enum=False,
            create_constraint=True,
            name="node_secret_reference_backend",
            length=32,
        ),
        nullable=False,
        default=SecretReferenceBackend.FILE,
    )
    ssh_secret_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    ssh_public_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    panel_username: Mapped[str | None] = mapped_column(String(128), nullable=True)
    panel_password_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    panel_password_backend: Mapped[SecretReferenceBackend | None] = mapped_column(
        Enum(
            SecretReferenceBackend,
            values_callable=_enum_values,
            native_enum=False,
            create_constraint=True,
            name="panel_password_secret_backend",
            length=32,
        ),
        nullable=True,
    )
    panel_base_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    api_token_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    api_token_backend: Mapped[SecretReferenceBackend | None] = mapped_column(
        Enum(
            SecretReferenceBackend,
            values_callable=_enum_values,
            native_enum=False,
            create_constraint=True,
            name="api_token_secret_backend",
            length=32,
        ),
        nullable=True,
    )

    node: Mapped[Node] = relationship(back_populates="credentials")
