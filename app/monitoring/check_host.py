from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from time import monotonic
from typing import Any

import httpx

from app.core.errors import AsoError
from app.monitoring.types import CheckHostRequest, CheckHostSummary, ProbeResult, ProbeStatus


class CheckHostError(AsoError):
    """Raised for Check-Host transport/protocol failures, not target reachability failures."""


class CheckHostClient:
    """Async adapter for the documented Check-Host API.

    Documentation verified 2026-09-17 against https://check-host.net/about/api.
    """

    def __init__(
        self,
        *,
        base_url: str = "https://check-host.net",
        timeout_seconds: float = 10.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
            headers={"Accept": "application/json"},
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def list_nodes(self, *, country_code: str | None = None) -> tuple[str, ...]:
        payload = await self._get_json("/nodes/hosts")
        nodes_payload = payload.get("nodes")
        if not isinstance(nodes_payload, Mapping):
            raise CheckHostError("Check-Host nodes response did not contain a nodes mapping")

        selected: list[str] = []
        for node_name, details in nodes_payload.items():
            if not isinstance(node_name, str) or not isinstance(details, Mapping):
                continue
            location = details.get("location")
            node_country = None
            if isinstance(location, Sequence) and not isinstance(location, (str, bytes)) and location:
                node_country = str(location[0]).lower()
            if country_code is None or node_country == country_code.lower():
                selected.append(node_name)
        return tuple(sorted(selected))

    async def resolve_nodes(
        self,
        *,
        configured_nodes: Sequence[str] = (),
        country_code: str = "ir",
        max_nodes: int = 5,
    ) -> tuple[str, ...]:
        if configured_nodes:
            unique = tuple(dict.fromkeys(node.strip() for node in configured_nodes if node.strip()))
            if not unique:
                raise CheckHostError("Configured Check-Host node list is empty after normalization")
            return unique[:max_nodes]

        discovered = await self.list_nodes(country_code=country_code)
        if not discovered:
            raise CheckHostError(f"No Check-Host nodes found for country code {country_code!r}")
        return discovered[:max_nodes]

    async def create_tcp_check(
        self,
        host: str,
        port: int,
        *,
        nodes: Sequence[str],
    ) -> CheckHostRequest:
        host = host.strip()
        if not host:
            raise ValueError("host must not be blank")
        if not 1 <= port <= 65535:
            raise ValueError("port must be between 1 and 65535")
        normalized_nodes = tuple(dict.fromkeys(node.strip() for node in nodes if node.strip()))
        if not normalized_nodes:
            raise ValueError("at least one Check-Host node is required")

        target = f"{host}:{port}"
        params: list[tuple[str, str]] = [("host", target)]
        params.extend(("node", node) for node in normalized_nodes)
        payload = await self._get_json("/check-tcp", params=params)

        if payload.get("ok") != 1:
            raise CheckHostError("Check-Host rejected the TCP check request")
        request_id = payload.get("request_id")
        if not isinstance(request_id, (str, int)):
            raise CheckHostError("Check-Host response did not contain request_id")
        response_nodes = payload.get("nodes")
        if not isinstance(response_nodes, Mapping) or not response_nodes:
            raise CheckHostError("Check-Host response did not contain selected nodes")

        return CheckHostRequest(
            request_id=str(request_id),
            permanent_link=(
                str(payload["permanent_link"]) if payload.get("permanent_link") else None
            ),
            nodes=tuple(str(node) for node in response_nodes),
            target=target,
        )

    async def get_result(self, request: CheckHostRequest) -> CheckHostSummary:
        payload = await self._get_json(f"/check-result/{request.request_id}")
        return self.parse_tcp_result(request, payload)

    async def poll_result(
        self,
        request: CheckHostRequest,
        *,
        timeout_seconds: float = 10.0,
        poll_interval_seconds: float = 1.0,
    ) -> CheckHostSummary:
        deadline = monotonic() + timeout_seconds
        last_summary: CheckHostSummary | None = None
        while True:
            last_summary = await self.get_result(request)
            if last_summary.is_complete or monotonic() >= deadline:
                return last_summary
            await asyncio.sleep(poll_interval_seconds)

    @staticmethod
    def parse_tcp_result(
        request: CheckHostRequest,
        payload: Mapping[str, Any],
    ) -> CheckHostSummary:
        probes = tuple(
            CheckHostClient._parse_node_result(node, payload.get(node)) for node in request.nodes
        )
        return CheckHostSummary(request_id=request.request_id, target=request.target, probes=probes)

    @staticmethod
    def _parse_node_result(node: str, raw: Any) -> ProbeResult:
        if raw is None:
            return ProbeResult(node=node, status=ProbeStatus.PENDING, raw=raw)
        if not isinstance(raw, list) or not raw:
            return ProbeResult(node=node, status=ProbeStatus.MALFORMED, raw=raw)

        entries = [entry for entry in raw if isinstance(entry, Mapping)]
        for entry in entries:
            latency = entry.get("time")
            if isinstance(latency, (int, float)) and "error" not in entry:
                return ProbeResult(
                    node=node,
                    status=ProbeStatus.SUCCESS,
                    latency_seconds=float(latency),
                    address=str(entry["address"]) if entry.get("address") else None,
                    raw=raw,
                )
        for entry in entries:
            if entry.get("error"):
                return ProbeResult(
                    node=node,
                    status=ProbeStatus.FAILURE,
                    error=str(entry["error"]),
                    raw=raw,
                )
        return ProbeResult(node=node, status=ProbeStatus.MALFORMED, raw=raw)

    async def _get_json(
        self,
        path: str,
        *,
        params: list[tuple[str, str]] | None = None,
    ) -> dict[str, Any]:
        try:
            response = await self._client.get(path, params=params, headers={"Accept": "application/json"})
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise CheckHostError(f"Check-Host request failed: {type(exc).__name__}") from exc
        if not isinstance(payload, dict):
            raise CheckHostError("Check-Host response was not a JSON object")
        return payload
