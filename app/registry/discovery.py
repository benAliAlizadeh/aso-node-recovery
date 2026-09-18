from __future__ import annotations

import ipaddress
from dataclasses import dataclass, replace

from pydantic import SecretStr

from app.core.config import Settings
from app.core.secrets import SecretResolver
from app.deployment.node_api import ThreeXUiNodeApiVerifier
from app.master.factory import Master3XUiClientFactory
from app.master.types import MasterNode
from app.models import Provider, ProviderType
from app.providers.base import ProviderAdapter
from app.providers.hetzner import HetznerProvider
from app.providers.linode import LinodeProvider
from app.providers.types import ProviderServer, ProviderServerStatus


class ReadOnlyProviderFactory:
    """Build provider clients for discovery without enabling mutation paths.

    This factory intentionally ignores DRY_RUN and mutation switches because it only exposes the
    read-only provider adapter through SmartOnboardingDiscoveryService. It never returns the client
    to the replacement orchestrator.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def create(self, provider_type: ProviderType, token: SecretStr) -> ProviderAdapter:
        if provider_type is ProviderType.HETZNER:
            return HetznerProvider(token, base_url=self.settings.hetzner_api_base_url)
        if provider_type is ProviderType.LINODE:
            return LinodeProvider(token, base_url=self.settings.linode_api_base_url)
        raise ValueError(f"unsupported provider type: {provider_type.value}")


@dataclass(frozen=True, slots=True)
class SmartNodeDiscovery:
    provider_key: str
    provider_type: ProviderType
    server: ProviderServer
    master: MasterNode
    warnings: tuple[str, ...] = ()

    @property
    def suggested_name(self) -> str:
        return self.master.name.strip() or self.server.name.strip() or f"node-{self.master.id}"

    @property
    def monitoring_host(self) -> str:
        return self.master.address.strip()

    @property
    def monitoring_port(self) -> int:
        return self.master.port

    @property
    def provider_host(self) -> str:
        if not self.server.ipv4:
            raise ValueError("provider server has no public IPv4 address")
        return self.server.ipv4

    def safe_summary(self) -> dict[str, object]:
        return {
            "provider_key": self.provider_key,
            "provider_type": self.provider_type.value,
            "provider_server_id": self.server.provider_server_id,
            "provider_server_name": self.server.name,
            "provider_status": self.server.status.value,
            "provider_ipv4": self.server.ipv4,
            "provider_region": self.server.region,
            "provider_server_type": self.server.server_type,
            "provider_image": self.server.image,
            "master_node_id": self.master.id,
            "master_name": self.master.name,
            "master_scheme": self.master.scheme,
            "master_address": self.master.address,
            "master_port": self.master.port,
            "master_base_path": self.master.base_path,
            "master_status": self.master.status,
            "master_xray_state": self.master.xray_state,
            "master_has_api_token": self.master.has_api_token,
            "warnings": list(self.warnings),
        }


class SmartOnboardingDiscoveryService:
    """Read-only discovery and validation for existing infrastructure onboarding."""

    def __init__(
        self,
        settings: Settings,
        *,
        secret_resolver: SecretResolver | None = None,
        provider_factory: ReadOnlyProviderFactory | None = None,
    ) -> None:
        self.settings = settings
        self.secret_resolver = secret_resolver or SecretResolver()
        self.provider_factory = provider_factory or ReadOnlyProviderFactory(settings)

    async def validate_provider_secret(
        self,
        provider_type: ProviderType,
        credential: SecretStr,
    ) -> None:
        adapter = self.provider_factory.create(provider_type, credential)
        try:
            await adapter.probe_access()
        finally:
            await adapter.aclose()

    async def discover_existing_node(
        self,
        provider: Provider,
        *,
        provider_server_id: str,
        master_node_id: int,
        node_api_token: SecretStr | None,
        region_override: str | None = None,
        server_type_override: str | None = None,
        image_override: str | None = None,
    ) -> SmartNodeDiscovery:
        provider_server_id = provider_server_id.strip()
        if not provider_server_id:
            raise ValueError("provider server/instance ID is required")
        if master_node_id < 1:
            raise ValueError("Master node ID must be positive")

        provider_token = self.secret_resolver.resolve(
            provider.credential_backend,
            provider.credential_ref,
        )
        adapter = self.provider_factory.create(provider.provider_type, provider_token)
        try:
            await adapter.probe_access()
            server = await adapter.get_server(provider_server_id)
        finally:
            await adapter.aclose()

        if any((region_override, server_type_override, image_override)):
            server = replace(
                server,
                region=(region_override or "").strip() or server.region,
                server_type=(server_type_override or "").strip() or server.server_type,
                image=(image_override or "").strip() or server.image,
            )
        self._validate_provider_server(server)

        master_client = Master3XUiClientFactory.create(self.settings)
        try:
            master = await master_client.get_node(master_node_id)
            probe = await master_client.probe_node(master_node_id)
        finally:
            await master_client.aclose()

        self._validate_master_node(master, probe)
        warnings = list(self._identity_warnings(server, master))

        if master.has_api_token:
            if node_api_token is None:
                raise ValueError(
                    "this Master node uses an API token; provide the current node API token "
                    "so ASO can verify it and safely rollback a future replacement"
                )
            verifier = ThreeXUiNodeApiVerifier(
                timeout_seconds=self.settings.master_3xui_timeout_seconds,
                verify_tls=self.settings.three_xui_verify_tls,
            )
            await verifier.verify_access_url(
                self._node_access_url(master),
                node_api_token,
            )
        elif node_api_token is not None:
            verifier = ThreeXUiNodeApiVerifier(
                timeout_seconds=self.settings.master_3xui_timeout_seconds,
                verify_tls=self.settings.three_xui_verify_tls,
            )
            await verifier.verify_access_url(
                self._node_access_url(master),
                node_api_token,
            )
        else:
            warnings.append(
                "Master reports no node API token; direct node-token validation was skipped"
            )

        return SmartNodeDiscovery(
            provider_key=provider.key,
            provider_type=provider.provider_type,
            server=server,
            master=master,
            warnings=tuple(warnings),
        )

    @staticmethod
    def _validate_provider_server(server: ProviderServer) -> None:
        if server.status in {ProviderServerStatus.DELETED, ProviderServerStatus.ERROR}:
            raise ValueError(f"provider server is not usable: status={server.status.value}")
        missing: list[str] = []
        if not server.ipv4:
            missing.append("public IPv4")
        if not server.region:
            missing.append("region/location")
        if not server.server_type:
            missing.append("server type/plan")
        if not server.image:
            missing.append("image")
        if missing:
            raise ValueError(
                "provider API could not discover required replacement metadata: "
                + ", ".join(missing)
            )

    @staticmethod
    def _validate_master_node(master: MasterNode, probe: dict[str, object]) -> None:
        if master.transitive:
            raise ValueError("transitive 3X-UI nodes are read-only and cannot be managed")
        if master.tls_verify_mode == "mtls":
            raise ValueError(
                "mTLS-managed 3X-UI nodes are not supported by the replacement workflow yet"
            )
        if not master.address.strip():
            raise ValueError("Master node has no address")
        if not 1 <= master.port <= 65535:
            raise ValueError("Master node has an invalid panel/API port")
        status = str(probe.get("status") or master.status or "").lower()
        xray_state = str(probe.get("xrayState") or master.xray_state or "").lower()
        if status and status != "online":
            raise ValueError(f"Master probe reports node status={status!r}")
        if xray_state and xray_state != "running":
            raise ValueError(f"Master probe reports Xray state={xray_state!r}")

    @staticmethod
    def _identity_warnings(server: ProviderServer, master: MasterNode) -> tuple[str, ...]:
        try:
            master_ip = str(ipaddress.ip_address(master.address.strip()))
        except ValueError:
            return (
                "Master uses a hostname; ASO keeps that hostname for monitoring while the "
                "provider IPv4 is stored separately for VPS identity/deletion safety",
            )
        if server.ipv4 and master_ip != server.ipv4:
            raise ValueError(
                "Master node address is a literal IP that does not match the provider instance IPv4; "
                "check the Provider Instance ID and Master Node ID"
            )
        return ()

    @staticmethod
    def _node_access_url(master: MasterNode) -> str:
        scheme = master.scheme.strip().lower() or "http"
        base_path = master.base_path.strip()
        if base_path and not base_path.startswith("/"):
            base_path = "/" + base_path
        base_path = base_path.rstrip("/")
        return f"{scheme}://{master.address.strip()}:{master.port}{base_path}"
