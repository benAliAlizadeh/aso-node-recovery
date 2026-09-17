from __future__ import annotations

from typing import Any

import httpx

from app.deployment.types import ThreeXUiConfig


class ThreeXUiNodeApiVerifier:
    """Verify a newly installed panel using the current token-authenticated server status API."""

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
        headers = {"Authorization": f"Bearer {config.api_token.get_secret_value()}"}
        if self._client is not None:
            response = await self._client.get(
                f"{config.access_url}/panel/api/server/status", headers=headers
            )
        else:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout_seconds), verify=self.verify_tls
            ) as client:
                response = await client.get(
                    f"{config.access_url}/panel/api/server/status", headers=headers
                )
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
