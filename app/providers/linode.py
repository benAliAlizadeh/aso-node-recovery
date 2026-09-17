from __future__ import annotations

from typing import Any

import httpx
from pydantic import SecretStr

from app.core.errors import ConfigurationError
from app.providers.base import ProviderAdapter
from app.providers.http import HttpProviderAdapterMixin
from app.providers.types import CreateServerRequest, ProviderServer, ProviderServerStatus


class LinodeProvider(HttpProviderAdapterMixin, ProviderAdapter):
    """Akamai Cloud/Linode adapter using the documented v4 API."""

    provider_name = "linode"

    def __init__(
        self,
        api_token: SecretStr,
        *,
        base_url: str = "https://api.linode.com/v4",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(30.0),
            headers={
                "Authorization": f"Bearer {api_token.get_secret_value()}",
                "Content-Type": "application/json",
            },
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def create_server(self, request: CreateServerRequest) -> ProviderServer:
        request.validate()
        if not request.ssh_public_keys and request.root_password is None:
            raise ConfigurationError(
                "linode create requires at least one SSH public key or a root password"
            )

        payload: dict[str, Any] = {
            "label": request.name,
            "region": request.region,
            "type": request.server_type,
            "image": request.image,
            "booted": True,
        }
        if request.ssh_public_keys:
            payload["authorized_keys"] = list(request.ssh_public_keys)
        if request.root_password is not None:
            payload["root_pass"] = request.root_password.get_secret_value()
        if request.user_data:
            import base64

            payload["metadata"] = {
                "user_data": base64.b64encode(request.user_data.encode()).decode()
            }
        if request.labels:
            payload["tags"] = [f"{key}:{value}" for key, value in sorted(request.labels.items())]

        body = await self._request_json(
            self._client, "POST", "/linode/instances", json=payload
        )
        return self._parse_server(body)

    async def get_server(self, provider_server_id: str) -> ProviderServer:
        body = await self._request_json(
            self._client, "GET", f"/linode/instances/{provider_server_id}"
        )
        return self._parse_server(body)

    async def delete_server(self, provider_server_id: str) -> None:
        await self._request_json(
            self._client, "DELETE", f"/linode/instances/{provider_server_id}"
        )

    async def reboot_server(self, provider_server_id: str) -> None:
        await self._request_json(
            self._client, "POST", f"/linode/instances/{provider_server_id}/reboot"
        )

    def _parse_server(self, data: dict[str, Any]) -> ProviderServer:
        server_id = data.get("id")
        if server_id is None:
            from app.providers.errors import ProviderError

            raise ProviderError("linode API response did not contain instance id", code="missing_id")
        ipv4 = data.get("ipv4") or []
        return ProviderServer(
            provider_server_id=str(server_id),
            name=str(data.get("label") or server_id),
            status=self._map_status(str(data.get("status") or "unknown")),
            ipv4=str(ipv4[0]) if ipv4 else None,
            region=data.get("region"),
            server_type=data.get("type"),
            raw=data,
        )

    @staticmethod
    def _map_status(value: str) -> ProviderServerStatus:
        if value == "running":
            return ProviderServerStatus.RUNNING
        if value == "offline":
            return ProviderServerStatus.OFFLINE
        if value in {"provisioning", "booting", "rebooting", "shutting_down", "migrating"}:
            return ProviderServerStatus.PROVISIONING
        if value == "deleting":
            return ProviderServerStatus.DELETING
        return ProviderServerStatus.UNKNOWN

    def _extract_error(self, response: httpx.Response) -> tuple[str, str]:
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        errors = payload.get("errors") if isinstance(payload, dict) else None
        if isinstance(errors, list) and errors:
            first = errors[0] if isinstance(errors[0], dict) else {}
            field = first.get("field")
            reason = str(first.get("reason") or "linode API request failed")
            return str(field or response.status_code), reason
        return str(response.status_code), "linode API request failed"
