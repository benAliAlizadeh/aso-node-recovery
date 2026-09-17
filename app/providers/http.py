from __future__ import annotations

from typing import Any

import httpx

from app.providers.errors import (
    ProviderAuthenticationError,
    ProviderConflictError,
    ProviderError,
    ProviderNotFoundError,
    ProviderRateLimitError,
    ProviderTransientError,
)


class HttpProviderAdapterMixin:
    provider_name = "provider"

    async def _request_json(
        self,
        client: httpx.AsyncClient,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        try:
            response = await client.request(
                method, path, json=json, params=params, headers=headers
            )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise ProviderTransientError(
                f"{self.provider_name} API network request failed", code="network_error"
            ) from exc

        if response.status_code in {200, 201, 202, 204}:
            if not response.content:
                return {}
            try:
                payload = response.json()
            except ValueError as exc:
                raise ProviderError(
                    f"{self.provider_name} API returned invalid JSON", code="invalid_json"
                ) from exc
            return payload if isinstance(payload, dict) else {"data": payload}

        code, message = self._extract_error(response)
        if response.status_code in {401, 403}:
            raise ProviderAuthenticationError(message, code=code)
        if response.status_code == 404:
            raise ProviderNotFoundError(message, code=code)
        if response.status_code == 409:
            raise ProviderConflictError(message, code=code)
        if response.status_code == 429:
            raise ProviderRateLimitError(message, code=code)
        if response.status_code >= 500:
            raise ProviderTransientError(message, code=code)
        raise ProviderError(message, code=code)

    def _extract_error(self, response: httpx.Response) -> tuple[str, str]:
        return str(response.status_code), f"{self.provider_name} API request failed"
