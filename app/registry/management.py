from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from pydantic import SecretStr
from sqlalchemy import delete, func, select

from app.core.config import Settings
from app.core.errors import ConfigurationError
from app.core.secrets import RuntimeSecretStore, SecretResolver
from app.database import Database
from app.database.repositories import (
    NodeCredentialRepository,
    NodeRepository,
    ProviderRepository,
    ReplacementJobRepository,
    VpsInstanceRepository,
)
from app.deployment.node_api import ThreeXUiNodeApiVerifier
from app.deployment.ssh import AsyncSshCommandExecutor
from app.deployment.types import SshConnectionSpec
from app.models import (
    Node,
    NodeCredential,
    Provider,
    ProviderType,
    SecretReferenceBackend,
    SshAuthMethod,
    VpsInstance,
)
from app.registry.discovery import SmartNodeDiscovery
from app.registry.smart import SmartRegistryOnboardingService


@dataclass(frozen=True, slots=True)
class ProviderManagementSnapshot:
    id: UUID
    key: str
    display_name: str
    provider_type: ProviderType
    is_active: bool
    node_count: int
    has_credential: bool


@dataclass(frozen=True, slots=True)
class NodeManagementSnapshot:
    id: UUID
    name: str
    provider_id: UUID
    provider_key: str
    provider_type: ProviderType
    master_node_id: str
    monitoring_host: str
    monitoring_port: int
    provider_server_id: str
    provider_ipv4: str | None
    provider_region: str | None
    provider_server_type: str | None
    provider_image: str | None
    ssh_username: str
    ssh_port: int
    ssh_auth_method: SshAuthMethod
    has_node_api_token: bool


class RegistryManagementService:
    """Safe application service for Telegram registry management.

    All discovery and tests are read-only. Removing a record means removing local ASO registry
    metadata only; this service never calls provider delete/reboot/create APIs and never mutates
    Master 3X-UI nodes.
    """

    def __init__(self, database: Database, settings: Settings) -> None:
        self.database = database
        self.settings = settings
        self.secrets = RuntimeSecretStore(settings.runtime_secret_dir)
        self.resolver = SecretResolver()
        self.smart = SmartRegistryOnboardingService(
            database,
            settings,
            secret_resolver=self.resolver,
        )
        self.ssh_executor = AsyncSshCommandExecutor()

    async def list_providers(self) -> list[ProviderManagementSnapshot]:
        async with self.database.session() as session:
            providers = await ProviderRepository(session).list_all()
            result: list[ProviderManagementSnapshot] = []
            for provider in providers:
                node_count = int(
                    await session.scalar(
                        select(func.count()).select_from(Node).where(Node.provider_id == provider.id)
                    )
                    or 0
                )
                result.append(self._provider_snapshot(provider, node_count=node_count))
            return result

    async def get_provider(self, provider_id: UUID) -> ProviderManagementSnapshot | None:
        async with self.database.session() as session:
            provider = await ProviderRepository(session).get(provider_id)
            if provider is None:
                return None
            node_count = int(
                await session.scalar(
                    select(func.count()).select_from(Node).where(Node.provider_id == provider.id)
                )
                or 0
            )
            return self._provider_snapshot(provider, node_count=node_count)

    async def validate_provider_token(
        self,
        provider_type: ProviderType,
        token: SecretStr,
    ) -> None:
        await self.smart.discovery.validate_provider_secret(provider_type, token)

    def stage_secret(self, scope: str, name: str, value: SecretStr) -> str:
        candidate = f"{name}-candidate-{uuid4().hex}"
        return self.secrets.write(scope, candidate, value)

    def discard_staged_secret(self, reference: str | None) -> None:
        if not reference:
            return
        try:
            self.secrets.delete_reference(reference)
        except ConfigurationError:
            # Never delete arbitrary external files. A non-managed reference is simply retained.
            return

    async def commit_provider(
        self,
        *,
        key: str,
        display_name: str,
        provider_type: ProviderType,
        staged_credential_ref: str,
    ) -> ProviderManagementSnapshot:
        token = self.resolver.resolve(SecretReferenceBackend.FILE, staged_credential_ref)
        await self.validate_provider_token(provider_type, token)
        async with self.database.session() as session:
            repo = ProviderRepository(session)
            if await repo.get_by_key(key.strip().lower()) is not None:
                raise ValueError(f"provider key {key!r} already exists")
        provider = await self.smart.validate_and_register_provider(
            key=key,
            display_name=display_name,
            provider_type=provider_type,
            credential_ref=staged_credential_ref,
            credential_backend=SecretReferenceBackend.FILE,
        )
        return self._provider_snapshot(provider, node_count=0)

    async def test_provider(self, provider_id: UUID) -> None:
        async with self.database.session() as session:
            provider = await ProviderRepository(session).get(provider_id)
            if provider is None:
                raise ValueError("provider not found")
            token = self.resolver.resolve(provider.credential_backend, provider.credential_ref)
            provider_type = provider.provider_type
        await self.validate_provider_token(provider_type, token)

    async def replace_provider_token(
        self,
        provider_id: UUID,
        staged_credential_ref: str,
    ) -> None:
        candidate = self.resolver.resolve(SecretReferenceBackend.FILE, staged_credential_ref)
        async with self.database.session() as session:
            provider = await ProviderRepository(session).get(provider_id)
            if provider is None:
                raise ValueError("provider not found")
            provider_type = provider.provider_type
            old_backend = provider.credential_backend
            old_ref = provider.credential_ref
        await self.validate_provider_token(provider_type, candidate)
        async with self.database.session() as session:
            provider = await ProviderRepository(session).get(provider_id)
            if provider is None:
                raise ValueError("provider not found")
            provider.credential_backend = SecretReferenceBackend.FILE
            provider.credential_ref = staged_credential_ref
            await session.commit()
        self._discard_old_managed_secret(old_backend, old_ref, keep=staged_credential_ref)

    async def rename_provider(self, provider_id: UUID, display_name: str) -> None:
        display_name = display_name.strip()
        if not display_name:
            raise ValueError("provider display name cannot be blank")
        async with self.database.session() as session:
            provider = await ProviderRepository(session).get(provider_id)
            if provider is None:
                raise ValueError("provider not found")
            provider.display_name = display_name
            await session.commit()

    async def remove_provider_from_registry(self, provider_id: UUID) -> None:
        """Remove only ASO metadata. Never delete provider infrastructure."""
        async with self.database.session() as session:
            provider = await ProviderRepository(session).get(provider_id)
            if provider is None:
                raise ValueError("provider not found")
            node_count = int(
                await session.scalar(
                    select(func.count()).select_from(Node).where(Node.provider_id == provider_id)
                )
                or 0
            )
            vps_count = int(
                await session.scalar(
                    select(func.count()).select_from(VpsInstance).where(
                        VpsInstance.provider_id == provider_id
                    )
                )
                or 0
            )
            if node_count or vps_count:
                raise ValueError(
                    "provider still has ASO node/VPS registry records; remove those nodes first"
                )
            old_backend = provider.credential_backend
            old_ref = provider.credential_ref
            await session.delete(provider)
            await session.commit()
        self._discard_old_managed_secret(old_backend, old_ref)

    async def discover_node(
        self,
        *,
        provider_id: UUID,
        provider_server_id: str,
        master_node_id: int,
        node_api_token: SecretStr | None,
    ) -> SmartNodeDiscovery:
        async with self.database.session() as session:
            provider = await ProviderRepository(session).get(provider_id)
            if provider is None:
                raise ValueError("provider not found")
        return await self.smart.discovery.discover_existing_node(
            provider,
            provider_server_id=provider_server_id,
            master_node_id=master_node_id,
            node_api_token=node_api_token,
        )

    async def commit_node(
        self,
        *,
        provider_id: UUID,
        provider_server_id: str,
        master_node_id: int,
        name: str | None,
        node_api_token_ref: str | None,
        ssh_username: str,
        ssh_port: int,
        ssh_auth_method: SshAuthMethod,
        ssh_secret_ref: str,
        ssh_public_key: str | None,
    ) -> NodeManagementSnapshot:
        node_token = None
        if node_api_token_ref:
            node_token = self.resolver.resolve(SecretReferenceBackend.FILE, node_api_token_ref)
        discovered = await self.discover_node(
            provider_id=provider_id,
            provider_server_id=provider_server_id,
            master_node_id=master_node_id,
            node_api_token=node_token,
        )
        ssh_secret = self.resolver.resolve(SecretReferenceBackend.FILE, ssh_secret_ref)
        await self._verify_ssh(
            host=discovered.provider_host,
            username=ssh_username,
            port=ssh_port,
            auth_method=ssh_auth_method,
            secret=ssh_secret,
        )
        async with self.database.session() as session:
            provider = await ProviderRepository(session).get(provider_id)
            if provider is None:
                raise ValueError("provider not found")
            provider_key = provider.key
        node = await self.smart.registry.register_node(
            name=(name or "").strip() or discovered.suggested_name,
            provider_key=provider_key,
            master_node_id=str(discovered.master.id),
            current_host=discovered.monitoring_host,
            current_port=discovered.monitoring_port,
            provider_server_id=discovered.server.provider_server_id,
            provider_host=discovered.provider_host,
            region=discovered.server.region,
            server_type=discovered.server.server_type,
            provider_image=discovered.server.image,
            ssh_username=ssh_username,
            ssh_port=ssh_port,
            ssh_auth_method=ssh_auth_method,
            ssh_secret_ref=ssh_secret_ref,
            ssh_public_key=(ssh_public_key or "").strip() or None,
            panel_base_path=discovered.master.base_path,
            api_token_ref=node_api_token_ref,
        )
        snapshot = await self.get_node(node.id)
        if snapshot is None:  # pragma: no cover - commit invariant
            raise RuntimeError("node was persisted but cannot be reloaded")
        return snapshot

    async def list_nodes(self) -> list[NodeManagementSnapshot]:
        async with self.database.session() as session:
            nodes = await NodeRepository(session).list_all(limit=500)
            result: list[NodeManagementSnapshot] = []
            for node in nodes:
                snapshot = await self._node_snapshot(session, node)
                if snapshot is not None:
                    result.append(snapshot)
            return result

    async def get_node(self, node_id: UUID) -> NodeManagementSnapshot | None:
        async with self.database.session() as session:
            node = await NodeRepository(session).get(node_id)
            if node is None:
                return None
            return await self._node_snapshot(session, node)

    async def test_node(self, node_id: UUID) -> SmartNodeDiscovery:
        async with self.database.session() as session:
            node = await NodeRepository(session).get(node_id)
            if node is None:
                raise ValueError("node not found")
            credential = await NodeCredentialRepository(session).get_for_node(node_id)
            current_vps = await VpsInstanceRepository(session).get_current_for_node(node_id)
            if credential is None or current_vps is None:
                raise ValueError("node registry is incomplete")
            provider_id = node.provider_id
            provider_server_id = current_vps.provider_server_id
            master_node_id = int(node.master_node_id)
            api_ref = credential.api_token_ref
            api_backend = credential.api_token_backend
            ssh_ref = credential.ssh_secret_ref
            ssh_backend = credential.secret_backend
            ssh_username = credential.ssh_username
            ssh_port = credential.ssh_port
            ssh_method = credential.ssh_auth_method
            provider_host = current_vps.host
        api_token = None
        if api_ref and api_backend:
            api_token = self.resolver.resolve(api_backend, api_ref)
        discovered = await self.discover_node(
            provider_id=provider_id,
            provider_server_id=provider_server_id,
            master_node_id=master_node_id,
            node_api_token=api_token,
        )
        await self._verify_ssh(
            host=provider_host or discovered.provider_host,
            username=ssh_username,
            port=ssh_port,
            auth_method=ssh_method,
            secret=self.resolver.resolve(ssh_backend, ssh_ref),
        )
        return discovered

    async def rename_node(self, node_id: UUID, name: str) -> None:
        name = name.strip()
        if not name:
            raise ValueError("node name cannot be blank")
        async with self.database.session() as session:
            repo = NodeRepository(session)
            existing = await repo.get_by_name(name)
            if existing is not None and existing.id != node_id:
                raise ValueError("another node already uses that name")
            node = await repo.get(node_id)
            if node is None:
                raise ValueError("node not found")
            node.name = name
            await session.commit()

    async def validate_node_api_token(self, node_id: UUID, token: SecretStr) -> SmartNodeDiscovery:
        async with self.database.session() as session:
            node = await NodeRepository(session).get(node_id)
            current_vps = await VpsInstanceRepository(session).get_current_for_node(node_id)
            if node is None or current_vps is None:
                raise ValueError("node/current VPS registry is missing")
            provider_id = node.provider_id
            provider_server_id = current_vps.provider_server_id
            master_id = int(node.master_node_id)
        return await self.discover_node(
            provider_id=provider_id,
            provider_server_id=provider_server_id,
            master_node_id=master_id,
            node_api_token=token,
        )

    async def validate_ssh(
        self,
        *,
        host: str,
        username: str,
        port: int,
        auth_method: SshAuthMethod,
        secret: SecretStr,
    ) -> None:
        await self._verify_ssh(
            host=host,
            username=username,
            port=port,
            auth_method=auth_method,
            secret=secret,
        )

    async def replace_node_api_token(self, node_id: UUID, staged_ref: str) -> None:
        candidate = self.resolver.resolve(SecretReferenceBackend.FILE, staged_ref)
        async with self.database.session() as session:
            node = await NodeRepository(session).get(node_id)
            credential = await NodeCredentialRepository(session).get_for_node(node_id)
            if node is None or credential is None:
                raise ValueError("node not found or credentials missing")
            old_backend = credential.api_token_backend
            old_ref = credential.api_token_ref
            # Master discovery remains the authoritative source for the scheme/path. Use it to
            # validate identity and then test the candidate token directly against the node.
            current_vps = await VpsInstanceRepository(session).get_current_for_node(node_id)
            if current_vps is None:
                raise ValueError("current VPS registry is missing")
            provider_id = node.provider_id
            provider_server_id = current_vps.provider_server_id
            master_id = int(node.master_node_id)
        discovered = await self.discover_node(
            provider_id=provider_id,
            provider_server_id=provider_server_id,
            master_node_id=master_id,
            node_api_token=candidate,
        )
        verifier = ThreeXUiNodeApiVerifier(
            timeout_seconds=self.settings.master_3xui_timeout_seconds,
            verify_tls=self.settings.three_xui_verify_tls,
        )
        path = discovered.master.base_path.strip()
        if path and not path.startswith("/"):
            path = "/" + path
        access_url = (
            f"{discovered.master.scheme}://{discovered.master.address}:"
            f"{discovered.master.port}{path.rstrip('/')}"
        )
        await verifier.verify_access_url(access_url, candidate)
        async with self.database.session() as session:
            credential = await NodeCredentialRepository(session).get_for_node(node_id)
            if credential is None:
                raise ValueError("node credentials missing")
            credential.api_token_backend = SecretReferenceBackend.FILE
            credential.api_token_ref = staged_ref
            await session.commit()
        if old_backend is not None:
            self._discard_old_managed_secret(old_backend, old_ref, keep=staged_ref)

    async def replace_node_ssh(
        self,
        node_id: UUID,
        *,
        username: str,
        port: int,
        auth_method: SshAuthMethod,
        staged_ref: str,
        public_key: str | None,
    ) -> None:
        secret = self.resolver.resolve(SecretReferenceBackend.FILE, staged_ref)
        async with self.database.session() as session:
            credential = await NodeCredentialRepository(session).get_for_node(node_id)
            current_vps = await VpsInstanceRepository(session).get_current_for_node(node_id)
            if credential is None or current_vps is None or not current_vps.host:
                raise ValueError("node SSH/VPS registry is incomplete")
            old_backend = credential.secret_backend
            old_ref = credential.ssh_secret_ref
            host = current_vps.host
        if auth_method is SshAuthMethod.PRIVATE_KEY and not (public_key or "").strip():
            raise ValueError("public SSH key is required for private-key replacement provisioning")
        await self._verify_ssh(
            host=host,
            username=username,
            port=port,
            auth_method=auth_method,
            secret=secret,
        )
        async with self.database.session() as session:
            credential = await NodeCredentialRepository(session).get_for_node(node_id)
            if credential is None:
                raise ValueError("node credentials missing")
            credential.ssh_username = username.strip()
            credential.ssh_port = port
            credential.ssh_auth_method = auth_method
            credential.secret_backend = SecretReferenceBackend.FILE
            credential.ssh_secret_ref = staged_ref
            credential.ssh_public_key = (public_key or "").strip() or None
            await session.commit()
        self._discard_old_managed_secret(old_backend, old_ref, keep=staged_ref)

    async def remove_node_from_registry(self, node_id: UUID) -> None:
        """Remove local ASO metadata only. Never delete a VPS or mutate the Master node."""
        async with self.database.session() as session:
            node = await NodeRepository(session).get(node_id)
            if node is None:
                raise ValueError("node not found")
            active = await ReplacementJobRepository(session).get_active_for_node(node_id)
            if active is not None:
                raise ValueError("node has an active replacement job")
            any_job = await ReplacementJobRepository(session).latest_for_node(node_id)
            if any_job is not None:
                raise ValueError(
                    "node has replacement history; refusing hard registry removal to preserve audit history"
                )
            credential = await NodeCredentialRepository(session).get_for_node(node_id)
            refs: list[tuple[SecretReferenceBackend | None, str | None]] = []
            if credential is not None:
                refs.extend(
                    [
                        (credential.secret_backend, credential.ssh_secret_ref),
                        (credential.api_token_backend, credential.api_token_ref),
                    ]
                )
            await session.execute(delete(VpsInstance).where(VpsInstance.node_id == node_id))
            await session.delete(node)
            await session.commit()
        for backend, reference in refs:
            if backend is not None:
                self._discard_old_managed_secret(backend, reference)

    async def _node_snapshot(self, session, node: Node) -> NodeManagementSnapshot | None:
        provider = await ProviderRepository(session).get(node.provider_id)
        credential = await NodeCredentialRepository(session).get_for_node(node.id)
        current_vps = await VpsInstanceRepository(session).get_current_for_node(node.id)
        if provider is None or credential is None or current_vps is None:
            return None
        return NodeManagementSnapshot(
            id=node.id,
            name=node.name,
            provider_id=provider.id,
            provider_key=provider.key,
            provider_type=provider.provider_type,
            master_node_id=node.master_node_id,
            monitoring_host=node.current_host,
            monitoring_port=node.current_port,
            provider_server_id=current_vps.provider_server_id,
            provider_ipv4=current_vps.host,
            provider_region=current_vps.region,
            provider_server_type=current_vps.server_type,
            provider_image=current_vps.image,
            ssh_username=credential.ssh_username,
            ssh_port=credential.ssh_port,
            ssh_auth_method=credential.ssh_auth_method,
            has_node_api_token=bool(credential.api_token_ref),
        )

    async def _verify_ssh(
        self,
        *,
        host: str,
        username: str,
        port: int,
        auth_method: SshAuthMethod,
        secret: SecretStr,
    ) -> None:
        if not host.strip():
            raise ValueError("VPS has no provider IPv4 for SSH validation")
        if not username.strip():
            raise ValueError("SSH username cannot be blank")
        if not 1 <= port <= 65535:
            raise ValueError("SSH port must be between 1 and 65535")
        spec = SshConnectionSpec(
            host=host.strip(),
            port=port,
            username=username.strip(),
            auth_method=auth_method,
            secret=secret,
            verify_host_key=self.settings.ssh_verify_host_key,
            known_hosts=self.settings.ssh_known_hosts_path or None,
        )
        result = await self.ssh_executor.run(
            spec,
            "printf ASO_SSH_READY",
            timeout_seconds=min(15.0, self.settings.ssh_ready_timeout_seconds),
        )
        if result.exit_status != 0 or result.stdout != "ASO_SSH_READY":
            raise ValueError("SSH validation failed")

    def _discard_old_managed_secret(
        self,
        backend: SecretReferenceBackend,
        reference: str | None,
        *,
        keep: str | None = None,
    ) -> None:
        if backend is not SecretReferenceBackend.FILE or not reference or reference == keep:
            return
        try:
            self.secrets.delete_reference(reference)
        except ConfigurationError:
            return

    @staticmethod
    def _provider_snapshot(provider: Provider, *, node_count: int) -> ProviderManagementSnapshot:
        return ProviderManagementSnapshot(
            id=provider.id,
            key=provider.key,
            display_name=provider.display_name,
            provider_type=provider.provider_type,
            is_active=provider.is_active,
            node_count=node_count,
            has_credential=bool(provider.credential_ref),
        )
