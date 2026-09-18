from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from pydantic import SecretStr


class ProviderServerStatus(StrEnum):
    PROVISIONING = "provisioning"
    RUNNING = "running"
    OFFLINE = "offline"
    DELETING = "deleting"
    DELETED = "deleted"
    ERROR = "error"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class CreateServerRequest:
    name: str
    region: str
    server_type: str
    image: str
    ssh_public_keys: tuple[str, ...] = ()
    root_password: SecretStr | None = field(default=None, repr=False)
    user_data: str | None = field(default=None, repr=False)
    labels: dict[str, str] = field(default_factory=dict)

    def validate(self) -> None:
        for field_name, value in (
            ("name", self.name),
            ("region", self.region),
            ("server_type", self.server_type),
            ("image", self.image),
        ):
            if not value.strip():
                raise ValueError(f"{field_name} cannot be blank")


@dataclass(frozen=True, slots=True)
class ProviderServer:
    provider_server_id: str
    name: str
    status: ProviderServerStatus
    ipv4: str | None
    region: str | None
    server_type: str | None
    image: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class ProvisioningCapacity:
    active_temporary_servers: int
    active_replacements: int
