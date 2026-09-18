from __future__ import annotations

from typing import Any

import httpx
from pydantic import SecretStr

from app.deployment.types import ThreeXUiConfig


class ThreeXUiNodeApiVerifier:
    """Verify a 3X-UI node using the token-authenticated server status API."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 15.0,
        verify_tls: bool = True,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.verify_tls = verify_tls
        self._client = client

    async def verify(self, config: ThreeXUiConfig) -> dict[str, Any]:
        return await self.verify_access_url(config.access_url, config.api_token)

    async def verify_access_url(
        self,
        access_url: str,
        api_token: SecretStr,
    ) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {api_token.get_secret_value()}"}
        url = f"{access_url.rstrip('/')}/panel/api/server/status"
        if self._client is not None:
            response = await self._client.get(url, headers=headers)
        else:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout_seconds), verify=self.verify_tls
            ) as client:
                response = await client.get(url, headers=headers)
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or body.get("success") is not True:
            raise RuntimeError("3X-UI node API did not return a successful status envelope")
        obj = body.get("obj")
        if not isinstance(obj, dict):
            raise RuntimeError("3X-UI node API status payload is missing")
        xray = obj.get("xray")
        if not isinstance(xray, dict) or str(xray.get("state", "")).lower() != "running":
            raise RuntimeError("3X-UI node API reports Xray is not running")
        return obj
