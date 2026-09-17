from __future__ import annotations

import hashlib

from app.models.enums import ProviderType
from app.providers.base import ProviderAdapter
from app.providers.errors import ProviderNotFoundError
from app.providers.types import CreateServerRequest, ProviderServer, ProviderServerStatus


class DryRunProvider(ProviderAdapter):
    """In-memory adapter used whenever DRY_RUN is enabled.

    It never contacts a cloud provider and uses TEST-NET-3 addresses which are reserved for
    documentation and cannot accidentally point at a real provisioned host.
    """

    def __init__(self, provider_type: ProviderType) -> None:
        self.provider_type = provider_type
        self._servers: dict[str, ProviderServer] = {}

    async def create_server(self, request: CreateServerRequest) -> ProviderServer:
        request.validate()
        digest = hashlib.sha256(
            f"{self.provider_type.value}:{request.name}:{len(self._servers)}".encode()
        ).hexdigest()[:12]
        server_id = f"dry-{self.provider_type.value}-{digest}"
        octet = 10 + (len(self._servers) % 200)
        server = ProviderServer(
            provider_server_id=server_id,
            name=request.name,
            status=ProviderServerStatus.RUNNING,
            ipv4=f"203.0.113.{octet}",
            region=request.region,
            server_type=request.server_type,
        )
        self._servers[server_id] = server
        return server

    async def get_server(self, provider_server_id: str) -> ProviderServer:
        try:
            return self._servers[provider_server_id]
        except KeyError as exc:
            raise ProviderNotFoundError("dry-run server does not exist", code="not_found") from exc

    async def find_server_by_name(self, name: str) -> ProviderServer | None:
        matches = [server for server in self._servers.values() if server.name == name and server.status is not ProviderServerStatus.DELETED]
        if not matches:
            return None
        if len(matches) > 1:
            raise RuntimeError("dry-run provider has duplicate server names")
        return matches[0]

    async def delete_server(self, provider_server_id: str) -> None:
        server = await self.get_server(provider_server_id)
        self._servers[provider_server_id] = ProviderServer(
            provider_server_id=server.provider_server_id,
            name=server.name,
            status=ProviderServerStatus.DELETED,
            ipv4=server.ipv4,
            region=server.region,
            server_type=server.server_type,
        )

    async def reboot_server(self, provider_server_id: str) -> None:
        await self.get_server(provider_server_id)
