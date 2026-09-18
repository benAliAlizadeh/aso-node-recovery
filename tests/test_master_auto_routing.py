from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.master import Master3XUiClient, MasterNodeMutation
from app.master.errors import MasterAuthenticationError
from app.master.routing import MasterRoute, build_master_routes, derive_local_host_base_url


def _list_payload() -> dict[str, object]:
    return {"success": True, "obj": []}


def test_local_route_preserves_scheme_port_and_base_path() -> None:
    assert (
        derive_local_host_base_url("http://forigen.kilashin.info:2053/QAZ")
        == "http://host.docker.internal:2053/QAZ"
    )
    routes = build_master_routes(
        "https://master.example.test:8443/secret/",
        mode="auto",
    )
    assert routes[0].base_url == "https://master.example.test:8443/secret"
    assert routes[1].base_url == "https://host.docker.internal:8443/secret"
    assert routes[1].host_header == "master.example.test:8443"


@pytest.mark.asyncio
async def test_auto_mode_keeps_remote_when_remote_tcp_is_reachable() -> None:
    requested: list[str] = []

    async def probe(route: MasterRoute, _: float) -> bool:
        return route.label == "remote"

    async def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(200, json=_list_payload())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = Master3XUiClient(
            "http://remote.example.test:2053/QAZ",
            api_token=SecretStr("token"),
            connection_mode="auto",
            route_probe=probe,
            client=http,
        )
        await client.list_nodes()
        assert client.connection_route == "remote"

    assert requested == ["http://remote.example.test:2053/QAZ/panel/api/nodes/list"]


@pytest.mark.asyncio
async def test_auto_mode_uses_local_host_when_remote_tcp_is_unreachable() -> None:
    requested: list[tuple[str, str | None]] = []

    async def probe(route: MasterRoute, _: float) -> bool:
        return route.label == "local-host"

    async def handler(request: httpx.Request) -> httpx.Response:
        requested.append((str(request.url), request.headers.get("Host")))
        return httpx.Response(200, json=_list_payload())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = Master3XUiClient(
            "http://forigen.kilashin.info:2053/QAZ",
            api_token=SecretStr("token"),
            connection_mode="auto",
            route_probe=probe,
            client=http,
        )
        await client.list_nodes()
        assert client.connection_route == "local-host"
        assert client.base_url == "http://forigen.kilashin.info:2053/QAZ"
        assert client.effective_base_url == "http://host.docker.internal:2053/QAZ"

    assert requested == [
        (
            "http://host.docker.internal:2053/QAZ/panel/api/nodes/list",
            "forigen.kilashin.info:2053",
        )
    ]


@pytest.mark.asyncio
async def test_authentication_error_never_triggers_local_fallback() -> None:
    requested: list[str] = []

    async def probe(route: MasterRoute, _: float) -> bool:
        return route.label == "remote"

    async def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(401, json={"success": False})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = Master3XUiClient(
            "http://remote.example.test:2053/QAZ",
            api_token=SecretStr("bad-token"),
            connection_mode="auto",
            route_probe=probe,
            client=http,
        )
        with pytest.raises(MasterAuthenticationError):
            await client.list_nodes()
        assert client.connection_route == "remote"

    assert len(requested) == 1
    assert "host.docker.internal" not in requested[0]


@pytest.mark.asyncio
async def test_network_error_can_fallback_but_does_not_mutate_logical_url() -> None:
    requested: list[str] = []

    async def probe(_: MasterRoute, __: float) -> bool:
        return True

    async def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if request.url.host == "remote.example.test":
            raise httpx.ConnectError("unreachable", request=request)
        return httpx.Response(200, json=_list_payload())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = Master3XUiClient(
            "http://remote.example.test:2053/QAZ",
            api_token=SecretStr("token"),
            connection_mode="auto",
            route_probe=probe,
            client=http,
        )
        await client.list_nodes()

    assert client.base_url == "http://remote.example.test:2053/QAZ"
    assert client.connection_route == "local-host"
    assert requested == [
        "http://remote.example.test:2053/QAZ/panel/api/nodes/list",
        "http://host.docker.internal:2053/QAZ/panel/api/nodes/list",
    ]


def test_settings_default_master_connection_mode_is_auto() -> None:
    settings = Settings(_env_file=None)
    assert settings.master_3xui_connection_mode == "auto"


def test_production_compose_exposes_docker_host_gateway() -> None:
    root = Path(__file__).resolve().parents[1]
    compose = (root / "docker-compose.prod.yml").read_text(encoding="utf-8")
    assert '"host.docker.internal:host-gateway"' in compose


@pytest.mark.asyncio
async def test_local_fallback_verifies_credentials_read_only_before_mutation() -> None:
    requested: list[tuple[str, str]] = []

    async def probe(route: MasterRoute, _: float) -> bool:
        return route.label == "local-host"

    async def handler(request: httpx.Request) -> httpx.Response:
        requested.append((request.method, request.url.path))
        if request.url.path.endswith("/nodes/list"):
            return httpx.Response(401, json={"success": False})
        raise AssertionError("mutating Master request must not run before local fallback auth check")

    mutation = MasterNodeMutation(
        name="DE-07",
        remark="",
        scheme="http",
        address="203.0.113.10",
        port=2053,
        base_path="/QAZ/",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = Master3XUiClient(
            "http://master.example.test:2053/QAZ",
            api_token=SecretStr("token"),
            connection_mode="auto",
            route_probe=probe,
            client=http,
        )
        with pytest.raises(MasterAuthenticationError):
            await client.update_node(7, mutation)

    assert requested == [("GET", "/QAZ/panel/api/nodes/list")]
