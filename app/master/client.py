from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlsplit

import httpx
from pydantic import SecretStr

from app.master.errors import (
    Master3XUiError,
    MasterAuthenticationError,
    MasterNodeVerificationError,
    MasterTransientError,
)
from app.master.routing import MasterConnectionMode, MasterRoute, build_master_routes
from app.master.types import MasterNode, MasterNodeMutation


class Master3XUiClient:
    """Current documented 3X-UI master-node API client.

    API tokens are preferred. Username/password login is supported for compatibility and relies on
    the session cookie returned by POST /login. Node API tokens are write-only and never parsed from
    master responses.
    """

    def __init__(
        self,
        base_url: str,
        *,
        api_token: SecretStr | None = None,
        username: str | None = None,
        password: SecretStr | None = None,
        verify_tls: bool = True,
        timeout_seconds: float = 20.0,
        connection_mode: MasterConnectionMode = "remote",
        local_base_url: str | None = None,
        auto_probe_timeout_seconds: float = 2.0,
        route_probe: Callable[[MasterRoute, float], Awaitable[bool]] | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._routes = build_master_routes(
            base_url,
            mode=connection_mode,
            local_base_url=local_base_url,
        )
        self.base_url = base_url.rstrip("/")
        self.logical_base_url = self.base_url
        self.connection_mode = connection_mode
        self._active_route_index = 0
        self._route_selected = connection_mode != "auto"
        self._auto_probe_timeout_seconds = auto_probe_timeout_seconds
        self._route_probe = route_probe or self._probe_tcp_route
        self._local_route_verified = False
        self.api_token = api_token
        self.username = username
        self.password = password
        self._authenticated = api_token is not None
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds),
            verify=verify_tls,
            follow_redirects=True,
        )

    @property
    def connection_route(self) -> str:
        return self._routes[self._active_route_index].label

    @property
    def effective_base_url(self) -> str:
        return self._routes[self._active_route_index].base_url

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def authenticate(self) -> None:
        if self.api_token is not None:
            self._authenticated = True
            return
        if not self.username or self.password is None:
            raise MasterAuthenticationError(
                "master authentication requires API token or username/password"
            )
        payload = await self._raw_request(
            "POST",
            "/login",
            json={
                "username": self.username,
                "password": self.password.get_secret_value(),
            },
            authenticated=False,
        )
        if isinstance(payload, dict) and payload.get("success") is False:
            raise MasterAuthenticationError(str(payload.get("msg") or "master login failed"))
        self._authenticated = True

    async def list_nodes(self) -> list[MasterNode]:
        obj = await self._request_obj("GET", "/panel/api/nodes/list")
        if not isinstance(obj, list):
            raise Master3XUiError("master node list response is not an array")
        return [MasterNode.from_payload(item) for item in obj if isinstance(item, dict)]

    async def get_node(self, node_id: int) -> MasterNode:
        obj = await self._request_obj("GET", f"/panel/api/nodes/get/{node_id}")
        if not isinstance(obj, dict):
            raise Master3XUiError("master node response is not an object")
        return MasterNode.from_payload(obj)

    async def test_node(self, mutation: MasterNodeMutation) -> dict[str, Any]:
        obj = await self._request_obj(
            "POST", "/panel/api/nodes/test", json=mutation.as_payload()
        )
        return obj if isinstance(obj, dict) else {"value": obj}

    async def update_node(self, node_id: int, mutation: MasterNodeMutation) -> MasterNode:
        await self._request_obj(
            "POST",
            f"/panel/api/nodes/update/{node_id}",
            json=mutation.as_payload(),
        )
        return await self.get_node(node_id)

    async def probe_node(self, node_id: int) -> dict[str, Any]:
        obj = await self._request_obj("POST", f"/panel/api/nodes/probe/{node_id}")
        return obj if isinstance(obj, dict) else {"value": obj}

    async def certificate_fingerprint(self, mutation: MasterNodeMutation) -> str:
        obj = await self._request_obj(
            "POST", "/panel/api/nodes/certFingerprint", json=mutation.as_payload()
        )
        if isinstance(obj, str):
            return obj
        if isinstance(obj, dict):
            for key in ("fingerprint", "sha256", "certFingerprint"):
                value = obj.get(key)
                if value:
                    return str(value)
        raise Master3XUiError("master certificate fingerprint response did not contain a fingerprint")

    async def verify_node(self, node_id: int, expected: MasterNodeMutation) -> MasterNode:
        probe = await self.probe_node(node_id)
        node = await self.get_node(node_id)
        mismatches: list[str] = []
        for field_name, actual, wanted in (
            ("scheme", node.scheme, expected.scheme),
            ("address", node.address, expected.address),
            ("port", node.port, expected.port),
            ("basePath", node.base_path, expected.base_path),
            ("enable", node.enable, expected.enable),
            ("tlsVerifyMode", node.tls_verify_mode, expected.tls_verify_mode),
            ("pinnedCertSha256", node.pinned_cert_sha256, expected.pinned_cert_sha256),
        ):
            if actual != wanted:
                mismatches.append(f"{field_name}={actual!r}, expected {wanted!r}")

        if expected.api_token is not None and not node.has_api_token:
            mismatches.append("hasApiToken=false")

        status = str(probe.get("status") or node.status or "").lower()
        xray_state = str(probe.get("xrayState") or node.xray_state or "").lower()
        if status and status != "online":
            mismatches.append(f"status={status!r}")
        if xray_state and xray_state != "running":
            mismatches.append(f"xrayState={xray_state!r}")
        if mismatches:
            raise MasterNodeVerificationError(
                "master node verification failed: " + "; ".join(mismatches)
            )
        return node

    async def _request_obj(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
    ) -> Any:
        if not self._authenticated:
            await self.authenticate()
        payload = await self._raw_request(method, path, json=json, authenticated=True)
        if isinstance(payload, dict) and "success" in payload:
            if payload.get("success") is not True:
                raise Master3XUiError(str(payload.get("msg") or "master API request failed"))
            return payload.get("obj")
        return payload

    async def _raw_request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None,
        authenticated: bool,
    ) -> Any:
        await self._select_auto_route()
        headers: dict[str, str] = {}
        if authenticated and self.api_token is not None:
            headers["Authorization"] = f"Bearer {self.api_token.get_secret_value()}"

        route = self._routes[self._active_route_index]
        if (
            route.label == "local-host"
            and authenticated
            and not self._local_route_verified
            and method.upper() != "GET"
        ):
            await self._verify_local_authenticated_route(route, headers)
        try:
            response = await self._request_route(route, method, path, json=json, headers=headers)
        except (httpx.TimeoutException, httpx.NetworkError) as first_exc:
            # Auto mode falls back only for transport failures. Authentication, HTTP, and API
            # errors never switch endpoints, preventing a bad credential from being hidden by a
            # different local panel. Once the fallback succeeds it is sticky for this client.
            next_index = self._active_route_index + 1
            if self.connection_mode != "auto" or next_index >= len(self._routes):
                raise MasterTransientError("master 3X-UI network request failed") from first_exc
            fallback = self._routes[next_index]
            try:
                if (
                    authenticated
                    and not self._local_route_verified
                    and method.upper() != "GET"
                ):
                    await self._verify_local_authenticated_route(fallback, headers)
                response = await self._request_route(
                    fallback, method, path, json=json, headers=headers
                )
            except (httpx.TimeoutException, httpx.NetworkError) as fallback_exc:
                raise MasterTransientError("master 3X-UI network request failed") from fallback_exc
            self._active_route_index = next_index
        if response.status_code in {401, 403}:
            raise MasterAuthenticationError("master 3X-UI authentication failed")
        if response.status_code >= 500:
            raise MasterTransientError(f"master 3X-UI HTTP {response.status_code}")
        if response.status_code >= 400:
            raise Master3XUiError(f"master 3X-UI HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise Master3XUiError("master 3X-UI returned invalid JSON") from exc
        active_route = self._routes[self._active_route_index]
        if active_route.label == "local-host" and authenticated and method.upper() == "GET":
            self._local_route_verified = True
        return payload

    async def _select_auto_route(self) -> None:
        if self._route_selected or self.connection_mode != "auto":
            return
        self._route_selected = True
        if len(self._routes) < 2:
            return

        remote, local = self._routes[0], self._routes[1]
        if await self._route_probe(remote, self._auto_probe_timeout_seconds):
            self._active_route_index = 0
            return
        if await self._route_probe(local, self._auto_probe_timeout_seconds):
            self._active_route_index = 1
            return
        # Preserve the configured remote URL as the final source of truth when neither TCP probe
        # succeeds. Its normal request error is more useful than silently selecting another host.
        self._active_route_index = 0

    @staticmethod
    async def _probe_tcp_route(route: MasterRoute, timeout_seconds: float) -> bool:
        parsed = urlsplit(route.base_url)
        if not parsed.hostname:
            return False
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        writer: asyncio.StreamWriter | None = None
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(parsed.hostname, port),
                timeout=timeout_seconds,
            )
            return True
        except (TimeoutError, OSError):
            return False
        finally:
            if writer is not None:
                writer.close()
                try:
                    await writer.wait_closed()
                except OSError:
                    pass

    async def _verify_local_authenticated_route(
        self,
        route: MasterRoute,
        headers: dict[str, str],
    ) -> None:
        """Authenticate a local-host fallback with a read-only request before any caller action."""

        response = await self._request_route(
            route,
            "GET",
            "/panel/api/nodes/list",
            json=None,
            headers=headers,
        )
        if response.status_code in {401, 403}:
            raise MasterAuthenticationError("master 3X-UI authentication failed")
        if response.status_code >= 500:
            raise MasterTransientError(f"master 3X-UI HTTP {response.status_code}")
        if response.status_code >= 400:
            raise Master3XUiError(f"master 3X-UI HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise Master3XUiError("master 3X-UI returned invalid JSON") from exc
        if isinstance(payload, dict) and payload.get("success") is not True:
            raise Master3XUiError(str(payload.get("msg") or "master API request failed"))
        self._local_route_verified = True

    async def _request_route(
        self,
        route: MasterRoute,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None,
        headers: dict[str, str],
    ) -> httpx.Response:
        route_headers = dict(headers)
        if route.host_header:
            route_headers["Host"] = route.host_header
        return await self._client.request(
            method,
            route.base_url + path,
            json=json,
            headers=route_headers,
        )
