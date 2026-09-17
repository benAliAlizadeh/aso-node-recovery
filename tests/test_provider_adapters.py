from __future__ import annotations

from uuid import uuid4

import json
import httpx
import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.core.errors import SafetyViolationError
from app.models import Provider, ProviderType, SecretReferenceBackend
from app.providers import (
    CreateServerRequest,
    DryRunProvider,
    HetznerProvider,
    LinodeProvider,
    ProviderFactory,
    ProviderManager,
    ProviderRateLimitError,
    ProviderRetryPolicy,
    ProviderSelectionPolicy,
    ProviderServerStatus,
    ProvisioningCapacity,
    ProvisioningSafetyPolicy,
    ProvisioningService,
)


def create_request() -> CreateServerRequest:
    return CreateServerRequest(
        name="aso-de-07-r1",
        region="fsn1",
        server_type="cx23",
        image="ubuntu-24.04",
        ssh_public_keys=("ssh-ed25519 AAAATEST aso",),
        labels={"managed-by": "aso"},
    )


@pytest.mark.asyncio
async def test_hetzner_create_uses_documented_server_shape() -> None:
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = __import__("json").loads(request.content)
        return httpx.Response(
            201,
            json={
                "server": {
                    "id": 123,
                    "name": "aso-de-07-r1",
                    "status": "running",
                    "public_net": {"ipv4": {"ip": "203.0.113.50"}},
                    "location": {"name": "fsn1"},
                    "server_type": {"name": "cx23"},
                }
            },
        )

    async with httpx.AsyncClient(
        base_url="https://api.hetzner.test/v1", transport=httpx.MockTransport(handler)
    ) as client:
        provider = HetznerProvider(SecretStr("token"), client=client)
        server = await provider.create_server(create_request())

    assert captured["path"] == "/v1/servers"
    assert captured["body"] == {
        "name": "aso-de-07-r1",
        "server_type": "cx23",
        "image": "ubuntu-24.04",
        "location": "fsn1",
        "ssh_keys": ["ssh-ed25519 AAAATEST aso"],
        "labels": {"managed-by": "aso"},
    }
    assert server.provider_server_id == "123"
    assert server.status is ProviderServerStatus.RUNNING
    assert server.ipv4 == "203.0.113.50"


@pytest.mark.asyncio
async def test_linode_create_uses_documented_auth_and_instance_fields() -> None:
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = __import__("json").loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": 456,
                "label": "aso-de-07-r1",
                "status": "running",
                "ipv4": ["203.0.113.60"],
                "region": "eu-central",
                "type": "g6-nanode-1",
            },
        )

    request = CreateServerRequest(
        name="aso-de-07-r1",
        region="eu-central",
        server_type="g6-nanode-1",
        image="linode/ubuntu24.04",
        ssh_public_keys=("ssh-ed25519 AAAATEST aso",),
    )
    async with httpx.AsyncClient(
        base_url="https://api.linode.test/v4", transport=httpx.MockTransport(handler)
    ) as client:
        provider = LinodeProvider(SecretStr("token"), client=client)
        server = await provider.create_server(request)

    body = captured["body"]
    assert captured["path"] == "/v4/linode/instances"
    assert body["region"] == "eu-central"  # type: ignore[index]
    assert body["type"] == "g6-nanode-1"  # type: ignore[index]
    assert body["image"] == "linode/ubuntu24.04"  # type: ignore[index]
    assert body["authorized_keys"] == ["ssh-ed25519 AAAATEST aso"]  # type: ignore[index]
    assert "root_pass" not in body  # type: ignore[operator]
    assert server.provider_server_id == "456"
    assert server.ipv4 == "203.0.113.60"


@pytest.mark.asyncio
async def test_provider_error_mapping_marks_429_retryable() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"code": "rate_limit", "message": "slow"}})

    async with httpx.AsyncClient(
        base_url="https://api.hetzner.test/v1", transport=httpx.MockTransport(handler)
    ) as client:
        provider = HetznerProvider(SecretStr("token"), client=client)
        with pytest.raises(ProviderRateLimitError) as exc:
            await provider.get_server("123")

    assert exc.value.retryable is True
    assert exc.value.code == "rate_limit"


@pytest.mark.asyncio
async def test_dry_run_provider_never_needs_credentials_and_uses_test_net() -> None:
    provider = Provider(
        id=uuid4(),
        key="hetzner-main",
        display_name="Hetzner",
        provider_type=ProviderType.HETZNER,
        credential_backend=SecretReferenceBackend.ENVIRONMENT,
        credential_ref="MISSING_TOKEN_ON_PURPOSE",
    )
    adapter = ProviderFactory(Settings(dry_run=True)).create(provider)
    assert isinstance(adapter, DryRunProvider)

    server = await adapter.create_server(create_request())
    assert server.status is ProviderServerStatus.RUNNING
    assert server.ipv4 is not None and server.ipv4.startswith("203.0.113.")



def test_real_provider_requires_second_explicit_safety_switch() -> None:
    provider = Provider(
        id=uuid4(),
        key="hetzner-main",
        display_name="Hetzner",
        provider_type=ProviderType.HETZNER,
        credential_backend=SecretReferenceBackend.ENVIRONMENT,
        credential_ref="ASO_HETZNER_API_TOKEN",
    )
    factory = ProviderFactory(
        Settings(dry_run=False, allow_real_infrastructure_mutation=False)
    )
    with pytest.raises(SafetyViolationError):
        factory.create(provider)



def test_provider_selection_is_deterministic_and_honors_preference() -> None:
    first = Provider(
        id=uuid4(),
        key="b-linode",
        display_name="B",
        provider_type=ProviderType.LINODE,
        credential_ref="B",
    )
    second = Provider(
        id=uuid4(),
        key="a-hetzner",
        display_name="A",
        provider_type=ProviderType.HETZNER,
        credential_ref="A",
    )
    policy = ProviderSelectionPolicy()
    assert policy.select([first, second]) is second
    assert policy.select([first, second], preferred_id=first.id) is first


@pytest.mark.asyncio
async def test_provisioning_service_enforces_capacity_before_create() -> None:
    adapter = DryRunProvider(ProviderType.HETZNER)
    policy = ProvisioningSafetyPolicy(
        max_replacement_attempts=5,
        max_temporary_servers=2,
        max_concurrent_replacements=2,
    )
    service = ProvisioningService(policy, timeout_seconds=1, poll_interval_seconds=0.01)

    with pytest.raises(SafetyViolationError, match="temporary VPS limit"):
        await service.create_temporary(
            adapter,
            create_request(),
            attempt_number=1,
            capacity=ProvisioningCapacity(active_temporary_servers=2, active_replacements=1),
        )


def test_retry_policy_classifies_but_does_not_execute_blind_create_retry() -> None:
    policy = ProviderRetryPolicy(max_attempts=3)
    error = ProviderRateLimitError("rate limited", code="rate_limit")
    assert policy.should_retry(error, attempt_number=1) is True
    assert policy.should_retry(error, attempt_number=3) is False


def test_provider_manager_reuses_adapter_for_same_persisted_provider() -> None:
    provider = Provider(
        id=uuid4(),
        key="hetzner-main",
        display_name="Hetzner",
        provider_type=ProviderType.HETZNER,
        credential_ref="MISSING_DRY_RUN_TOKEN",
    )
    manager = ProviderManager(ProviderFactory(Settings(dry_run=True)))
    assert manager.get(provider) is manager.get(provider)

@pytest.mark.asyncio
async def test_hetzner_reconciles_exact_server_name_before_create_retry() -> None:
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["query"] = request.url.query.decode()
        return httpx.Response(
            200,
            json={
                "servers": [
                    {
                        "id": 789,
                        "name": "aso-de-07-r1",
                        "status": "running",
                        "public_net": {"ipv4": {"ip": "203.0.113.70"}},
                        "location": {"name": "fsn1"},
                        "server_type": {"name": "cx23"},
                    }
                ]
            },
        )

    async with httpx.AsyncClient(
        base_url="https://api.hetzner.test/v1", transport=httpx.MockTransport(handler)
    ) as client:
        server = await HetznerProvider(SecretStr("token"), client=client).find_server_by_name(
            "aso-de-07-r1"
        )

    assert captured["path"] == "/v1/servers"
    assert "name=aso-de-07-r1" in str(captured["query"])
    assert server is not None and server.provider_server_id == "789"


@pytest.mark.asyncio
async def test_linode_reconciles_exact_label_with_x_filter() -> None:
    captured: dict[str, str] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["filter"] = request.headers["X-Filter"]
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": 999,
                        "label": "aso-de-07-r1",
                        "status": "running",
                        "ipv4": ["203.0.113.80"],
                        "region": "eu-central",
                        "type": "g6-nanode-1",
                    }
                ]
            },
        )

    async with httpx.AsyncClient(
        base_url="https://api.linode.test/v4", transport=httpx.MockTransport(handler)
    ) as client:
        server = await LinodeProvider(SecretStr("token"), client=client).find_server_by_name(
            "aso-de-07-r1"
        )

    assert json.loads(captured["filter"]) == {"label": "aso-de-07-r1"}
    assert server is not None and server.provider_server_id == "999"
