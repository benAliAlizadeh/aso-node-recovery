from __future__ import annotations

import json

import httpx
import pytest
from pydantic import SecretStr

from app.master import Master3XUiClient, MasterNodeMutation
from app.master.errors import MasterNodeVerificationError, MasterTransientError


def node_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": 7,
        "name": "DE-07",
        "remark": "edge",
        "scheme": "https",
        "address": "old.example.test",
        "port": 2053,
        "basePath": "/panel/",
        "hasApiToken": True,
        "enable": True,
        "allowPrivateAddress": False,
        "tlsVerifyMode": "verify",
        "pinnedCertSha256": "",
        "inboundSyncMode": "all",
        "inboundTags": [],
        "outboundTag": "direct",
        "guid": "node-guid",
        "status": "online",
        "xrayState": "running",
        "transitive": False,
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_master_client_uses_bearer_and_current_node_endpoints() -> None:
    captured: list[tuple[str, str, dict[str, object] | None]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        captured.append((request.method, request.url.path, body))
        assert request.headers["Authorization"] == "Bearer master-token"
        if request.url.path.endswith("/update/7"):
            return httpx.Response(200, json={"success": True, "obj": True})
        return httpx.Response(200, json={"success": True, "obj": node_payload(address="203.0.113.20")})

    mutation = MasterNodeMutation(
        name="DE-07",
        remark="edge",
        scheme="https",
        address="203.0.113.20",
        port=2053,
        base_path="/panel/",
        api_token=SecretStr("new-node-token"),
        outbound_tag="direct",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = Master3XUiClient(
            "https://master.example.test/base",
            api_token=SecretStr("master-token"),
            client=http,
        )
        node = await client.update_node(7, mutation)

    assert node.address == "203.0.113.20"
    assert captured[0][0:2] == ("POST", "/base/panel/api/nodes/update/7")
    assert captured[1][0:2] == ("GET", "/base/panel/api/nodes/get/7")
    assert captured[0][2]["apiToken"] == "new-node-token"  # type: ignore[index]


def test_master_read_contract_does_not_expose_node_api_token() -> None:
    from app.master.types import MasterNode

    node = MasterNode.from_payload(node_payload(apiToken="should-never-be-returned"))
    snapshot = node.safe_snapshot()
    assert "apiToken" not in snapshot
    assert "should-never-be-returned" not in repr(node)


@pytest.mark.asyncio
async def test_master_verification_rejects_mismatched_switch() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/probe/7"):
            return httpx.Response(
                200, json={"success": True, "obj": {"status": "online", "xrayState": "running"}}
            )
        return httpx.Response(200, json={"success": True, "obj": node_payload(address="old")})

    expected = MasterNodeMutation(
        name="DE-07",
        remark="edge",
        scheme="https",
        address="203.0.113.20",
        port=2053,
        base_path="/panel/",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = Master3XUiClient("https://master.test", api_token=SecretStr("x"), client=http)
        with pytest.raises(MasterNodeVerificationError, match="address"):
            await client.verify_node(7, expected)


@pytest.mark.asyncio
async def test_master_5xx_is_retryable_transient_error() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "busy"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = Master3XUiClient("https://master.test", api_token=SecretStr("x"), client=http)
        with pytest.raises(MasterTransientError):
            await client.get_node(7)
