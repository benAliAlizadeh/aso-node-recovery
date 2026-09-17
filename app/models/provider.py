from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, Enum, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import ProviderType, SecretReferenceBackend

if TYPE_CHECKING:
    from app.models.node import Node
    from app.models.operations import VpsInstance


def _enum_values(enum_type: type[ProviderType] | type[SecretReferenceBackend]) -> list[str]:
    return [item.value for item in enum_type]


class Provider(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Configured infrastructure provider account/adapter registration.

    Provider API credentials are never stored directly in this table. ``credential_ref`` points to
    a configured secret source that a later provider adapter can resolve.
    """

    __tablename__ = "providers"
    __table_args__ = (
        CheckConstraint("char_length(key) > 0", name="key_not_blank"),
        CheckConstraint("char_length(display_name) > 0", name="display_name_not_blank"),
        CheckConstraint("char_length(credential_ref) > 0", name="credential_ref_not_blank"),
    )

    key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    provider_type: Mapped[ProviderType] = mapped_column(
        Enum(
            ProviderType,
            values_callable=_enum_values,
            native_enum=False,
            create_constraint=True,
            name="provider_type",
            length=32,
        ),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    credential_backend: Mapped[SecretReferenceBackend] = mapped_column(
        Enum(
            SecretReferenceBackend,
            values_callable=_enum_values,
            native_enum=False,
            create_constraint=True,
            name="secret_reference_backend",
            length=32,
        ),
        nullable=False,
        default=SecretReferenceBackend.ENVIRONMENT,
    )
    credential_ref: Mapped[str] = mapped_column(String(255), nullable=False)

    nodes: Mapped[list[Node]] = relationship(back_populates="provider")
    vps_instances: Mapped[list[VpsInstance]] = relationship(back_populates="provider")
