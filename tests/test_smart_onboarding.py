from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.master.types import MasterNode
from app.models import Provider, ProviderType, SecretReferenceBackend
from app.providers.base import ProviderAdapter
from app.providers.types import ProviderServer, ProviderServerStatus
from app.registry.discovery import SmartOnboardingDiscoveryService

ROOT = Path(__file__).resolve().parents[1]


class FakeProvider(ProviderAdapter):
    def __init__(self, server: ProviderServer) -> None:
        self.server = server
        self.probed = False

    async def probe_access(self) -> None:
        self.probed = True

    async def get_server(self, provider_server_id: str) -> ProviderServer:
        assert provider_server_id == self.server.provider_server_id
        return self.server

    async def create_server(self, request):  # pragma: no cover - destructive path guard
        raise AssertionError("smart onboarding must not create servers")

    async def delete_server(self, provider_server_id: str) -> None:  # pragma: no cover
        raise AssertionError("smart onboarding must not delete servers")

    async def reboot_server(self, provider_server_id: str) -> None:  # pragma: no cover
        raise AssertionError("smart onboarding must not reboot servers")

    async def find_server_by_name(self, name: str):  # pragma: no cover
        raise AssertionError("smart onboarding does not reconcile by name")


class FakeFactory:
    def __init__(self, adapter: FakeProvider) -> None:
        self.adapter = adapter

    def create(self, provider_type: ProviderType, token: SecretStr) -> ProviderAdapter:
        assert token.get_secret_value() == "provider-secret"
        return self.adapter


class FakeMaster:
    def __init__(self, node: MasterNode) -> None:
        self.node = node

    async def get_node(self, node_id: int) -> MasterNode:
        assert node_id == self.node.id
        return self.node

    async def probe_node(self, node_id: int):
        assert node_id == self.node.id
        return {"status": "online", "xrayState": "running"}

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_smart_discovery_uses_provider_ip_separately_from_master_hostname(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PROVIDER_TOKEN", "provider-secret")
    server = ProviderServer(
        provider_server_id="123",
        name="linode-a",
        status=ProviderServerStatus.RUNNING,
        ipv4="192.0.2.44",
        region="de-fra-2",
        server_type="g6-standard-2",
        image="linode/ubuntu24.04",
    )
    master = MasterNode(
        id=9,
        name="de-09",
        remark="",
        scheme="https",
        address="node.example.com",
        port=2053,
        base_path="/secret/",
        has_api_token=False,
        enable=True,
        allow_private_address=False,
        tls_verify_mode="verify",
        pinned_cert_sha256="",
        inbound_sync_mode="all",
        inbound_tags=(),
        outbound_tag="",
        guid="g",
        status="online",
        xray_state="running",
    )
    monkeypatch.setattr(
        "app.registry.discovery.Master3XUiClientFactory.create",
        lambda settings: FakeMaster(master),
    )
    service = SmartOnboardingDiscoveryService(
        Settings(environment="test"),
        provider_factory=FakeFactory(FakeProvider(server)),
    )
    provider = Provider(
        key="linode-main",
        display_name="Linode",
        provider_type=ProviderType.LINODE,
        credential_backend=SecretReferenceBackend.ENVIRONMENT,
        credential_ref="PROVIDER_TOKEN",
    )
    result = await service.discover_existing_node(
        provider,
        provider_server_id="123",
        master_node_id=9,
        node_api_token=None,
    )
    assert result.monitoring_host == "node.example.com"
    assert result.provider_host == "192.0.2.44"
    assert result.server.region == "de-fra-2"
    assert result.server.server_type == "g6-standard-2"
    assert result.server.image == "linode/ubuntu24.04"
    assert result.warnings


def test_literal_master_ip_must_match_provider_instance() -> None:
    server = ProviderServer(
        provider_server_id="1",
        name="vps",
        status=ProviderServerStatus.RUNNING,
        ipv4="192.0.2.10",
        region="x",
        server_type="y",
        image="z",
    )
    master = MasterNode(
        id=1,
        name="n",
        remark="",
        scheme="http",
        address="192.0.2.11",
        port=2053,
        base_path="",
        has_api_token=False,
        enable=True,
        allow_private_address=False,
        tls_verify_mode="verify",
        pinned_cert_sha256="",
        inbound_sync_mode="all",
        inbound_tags=(),
        outbound_tag="",
        guid="",
        status="online",
        xray_state="running",
    )
    with pytest.raises(ValueError, match="does not match"):
        SmartOnboardingDiscoveryService._identity_warnings(server, master)


def test_asoctl_smart_setup_no_longer_prompts_for_discoverable_node_fields() -> None:
    source = (ROOT / "scripts" / "asoctl.sh").read_text(encoding="utf-8")
    assert "smart-add-provider" in source
    assert "smart-preview-node" in source
    assert "smart-add-node" in source
    assert "Current node IP/host" not in source
    assert "Current node panel/API port" not in source
    assert "Current VPS region" not in source
    assert "Current VPS server type" not in source
    assert "Default provider region/location code" not in source
    assert "Default server type/plan code" not in source
    assert "Default image code" not in source


def test_replacement_template_prefers_node_specific_vps_metadata() -> None:
    source = (ROOT / "app" / "replacement" / "orchestrator.py").read_text(encoding="utf-8")
    assert "region = old_vps.region or provider.default_region" in source
    assert "server_type = old_vps.server_type or provider.default_server_type" in source
    assert "image = old_vps.image or provider.default_image" in source
    assert "node replacement template is incomplete" in source
