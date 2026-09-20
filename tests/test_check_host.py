from __future__ import annotations

import json

import httpx
import pytest

from app.monitoring.check_host import CheckHostClient
from app.monitoring.types import CheckHostRequest, ProbeStatus


@pytest.mark.asyncio
async def test_discovers_only_requested_country_nodes() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/nodes/hosts"
        return httpx.Response(
            200,
            json={
                "nodes": {
                    "ir5.node.check-host.net": {"location": ["ir", "Iran", "Tehran"]},
                    "de1.node.check-host.net": {"location": ["de", "Germany", "Falkenstein"]},
                    "ir4.node.check-host.net": {"location": ["ir", "Iran", "Shiraz"]},
                }
            },
        )

    async with httpx.AsyncClient(
        base_url="https://check-host.net", transport=httpx.MockTransport(handler)
    ) as http_client:
        client = CheckHostClient(client=http_client)
        nodes = await client.list_nodes(country_code="ir")

    assert nodes == ("ir4.node.check-host.net", "ir5.node.check-host.net")


@pytest.mark.asyncio
async def test_tcp_check_uses_repeated_node_parameters_from_official_api_shape() -> None:
    captured_nodes: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_nodes
        assert request.url.path == "/check-tcp"
        assert request.url.params["host"] == "203.0.113.10:443"
        captured_nodes = request.url.params.get_list("node")
        return httpx.Response(
            200,
            json={
                "ok": 1,
                "request_id": "abc123",
                "permanent_link": "https://check-host.net/check-report/abc123",
                "nodes": {node: ["ir", "Iran", "Test", "127.0.0.1", "AS0"] for node in captured_nodes},
            },
        )

    nodes = ("ir4.node.check-host.net", "ir5.node.check-host.net")
    async with httpx.AsyncClient(
        base_url="https://check-host.net", transport=httpx.MockTransport(handler)
    ) as http_client:
        client = CheckHostClient(client=http_client)
        result = await client.create_tcp_check("203.0.113.10", 443, nodes=nodes)

    assert captured_nodes == list(nodes)
    assert result.request_id == "abc123"
    assert result.nodes == nodes


def test_tcp_result_parser_normalizes_success_failure_pending_and_malformed() -> None:
    request = CheckHostRequest(
        request_id="r1",
        permanent_link=None,
        nodes=("ir1", "ir2", "ir3", "ir4"),
        target="203.0.113.10:443",
    )
    payload = {
        "ir1": [{"time": 0.03, "address": "203.0.113.10"}],
        "ir2": [{"error": "Connection timed out"}],
        "ir3": None,
        "ir4": json.loads('{"unexpected": true}'),
    }

    summary = CheckHostClient.parse_tcp_result(request, payload)

    assert [probe.status for probe in summary.probes] == [
        ProbeStatus.SUCCESS,
        ProbeStatus.FAILURE,
        ProbeStatus.PENDING,
        ProbeStatus.MALFORMED,
    ]
    assert summary.success_count == 1
    assert summary.failure_count == 1
    assert summary.pending_count == 1
    assert summary.malformed_count == 1


@pytest.mark.asyncio
async def test_can_discover_external_nodes_while_excluding_iran() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/nodes/hosts"
        return httpx.Response(
            200,
            json={
                "nodes": {
                    "ir1.node.check-host.net": {"location": ["ir", "Iran", "Tehran"]},
                    "de1.node.check-host.net": {"location": ["de", "Germany", "Falkenstein"]},
                    "us1.node.check-host.net": {"location": ["us", "USA", "New York"]},
                }
            },
        )

    async with httpx.AsyncClient(
        base_url="https://check-host.net", transport=httpx.MockTransport(handler)
    ) as http_client:
        client = CheckHostClient(client=http_client)
        nodes = await client.resolve_nodes(
            country_code=None,
            exclude_country_codes=("ir",),
            max_nodes=5,
        )

    assert nodes == ("de1.node.check-host.net", "us1.node.check-host.net")
