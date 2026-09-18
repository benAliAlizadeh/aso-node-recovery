from __future__ import annotations

from typing import Any

import httpx
from pydantic import SecretStr

from app.providers.base import ProviderAdapter
from app.providers.http import HttpProviderAdapterMixin
from app.providers.types import CreateServerRequest, ProviderServer, ProviderServerStatus


class HetznerProvider(HttpProviderAdapterMixin, ProviderAdapter):
    """Hetzner Cloud adapter using the documented v1 Cloud API."""

    provider_name = "hetzner"

    def __init__(
        self,
        api_token: SecretStr,
        *,
        base_url: str = "https://api.hetzner.cloud/v1",
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

    async def probe_access(self) -> None:
        await self._request_json(
            self._client, "GET", "/servers", params={"page": 1, "per_page": 1}
        )

    async def create_server(self, request: CreateServerRequest) -> ProviderServer:
        request.validate()
        payload: dict[str, Any] = {
            "name": request.name,
            "server_type": request.server_type,
            "image": request.image,
            "location": request.region,
        }
        if request.ssh_public_keys:
            payload["ssh_keys"] = list(request.ssh_public_keys)
        if request.user_data:
            payload["user_data"] = request.user_data
        if request.labels:
            payload["labels"] = dict(request.labels)

        body = await self._request_json(self._client, "POST", "/servers", json=payload)
        return self._parse_server(body.get("server", {}))

    async def get_server(self, provider_server_id: str) -> ProviderServer:
        body = await self._request_json(
            self._client, "GET", f"/servers/{provider_server_id}"
        )
        return self._parse_server(body.get("server", {}))

    async def find_server_by_name(self, name: str) -> ProviderServer | None:
        body = await self._request_json(self._client, "GET", "/servers", params={"name": name})
        servers = body.get("servers") or []
        exact = [item for item in servers if str(item.get("name") or "") == name]
        if not exact:
            return None
        if len(exact) > 1:
            from app.providers.errors import ProviderError

            raise ProviderError("multiple Hetzner servers matched the recovery name", code="ambiguous_name")
        return self._parse_server(exact[0])

    async def delete_server(self, provider_server_id: str) -> None:
        await self._request_json(self._client, "DELETE", f"/servers/{provider_server_id}")

    async def reboot_server(self, provider_server_id: str) -> None:
        await self._request_json(
            self._client, "POST", f"/servers/{provider_server_id}/actions/reboot"
        )

    def _parse_server(self, data: dict[str, Any]) -> ProviderServer:
        server_id = data.get("id")
        if server_id is None:
            from app.providers.errors import ProviderError

            raise ProviderError("hetzner API response did not contain server id", code="missing_id")
        public_net = data.get("public_net") or {}
        ipv4_data = public_net.get("ipv4") or {}
        server_type = data.get("server_type") or {}
        location = data.get("location") or {}
        image = data.get("image") or {}
        image_ref = None
        if isinstance(image, dict):
            image_ref = str(image.get("id") or image.get("name") or "") or None
        elif image:
            image_ref = str(image)
        return ProviderServer(
            provider_server_id=str(server_id),
            name=str(data.get("name") or server_id),
            status=self._map_status(str(data.get("status") or "unknown")),
            ipv4=ipv4_data.get("ip"),
            region=location.get("name"),
            server_type=server_type.get("name"),
            image=image_ref,
            raw=data,
        )

    @staticmethod
    def _map_status(value: str) -> ProviderServerStatus:
        if value == "running":
            return ProviderServerStatus.RUNNING
        if value == "off":
            return ProviderServerStatus.OFFLINE
        if value in {"initializing", "starting", "stopping", "migrating", "rebuilding"}:
            return ProviderServerStatus.PROVISIONING
        if value == "deleting":
            return ProviderServerStatus.DELETING
        return ProviderServerStatus.UNKNOWN

    def _extract_error(self, response: httpx.Response) -> tuple[str, str]:
        try:
            error = response.json().get("error") or {}
        except ValueError:
            error = {}
        code = str(error.get("code") or response.status_code)
        message = str(error.get("message") or "hetzner API request failed")
        return code, message
