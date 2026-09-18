from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from time import monotonic

from app.providers.errors import ProviderTimeoutError
from app.providers.types import CreateServerRequest, ProviderServer, ProviderServerStatus


class ProviderAdapter(ABC):
    """Provider-neutral infrastructure contract used by later orchestration."""

    @abstractmethod
    async def probe_access(self) -> None:
        """Validate read access without mutating provider infrastructure."""
        raise NotImplementedError

    @abstractmethod
    async def create_server(self, request: CreateServerRequest) -> ProviderServer:
        raise NotImplementedError

    @abstractmethod
    async def get_server(self, provider_server_id: str) -> ProviderServer:
        raise NotImplementedError

    @abstractmethod
    async def delete_server(self, provider_server_id: str) -> None:
        raise NotImplementedError

    @abstractmethod
    async def reboot_server(self, provider_server_id: str) -> None:
        raise NotImplementedError

    @abstractmethod
    async def find_server_by_name(self, name: str) -> ProviderServer | None:
        """Find an exact server name/label for crash reconciliation."""
        raise NotImplementedError

    async def aclose(self) -> None:
        """Release adapter-owned resources. Stateless adapters may keep the default no-op."""
        return None

    async def get_server_ip(self, provider_server_id: str) -> str | None:
        return (await self.get_server(provider_server_id)).ipv4

    async def wait_until_ready(
        self,
        provider_server_id: str,
        *,
        timeout_seconds: float,
        poll_interval_seconds: float,
    ) -> ProviderServer:
        deadline = monotonic() + timeout_seconds
        last_status: ProviderServerStatus | None = None
        while monotonic() < deadline:
            server = await self.get_server(provider_server_id)
            last_status = server.status
            if server.status is ProviderServerStatus.RUNNING and server.ipv4:
                return server
            if server.status in {ProviderServerStatus.ERROR, ProviderServerStatus.DELETED}:
                raise ProviderTimeoutError(
                    f"provider server entered terminal state {server.status.value}",
                    code="terminal_state",
                )
            await asyncio.sleep(poll_interval_seconds)

        suffix = f"; last status={last_status.value}" if last_status else ""
        raise ProviderTimeoutError(
            f"provider server did not become ready within {timeout_seconds:.0f}s{suffix}",
            code="ready_timeout",
        )
