from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select

from app.database import Database
from app.database.repositories import NodeCredentialRepository, NodeRepository, ProviderRepository, VpsInstanceRepository
from app.models import (
    Node,
    NodeCredential,
    NodeState,
    Provider,
    ProviderType,
    SecretReferenceBackend,
    SshAuthMethod,
    VpsInstance,
    VpsInstanceRole,
    VpsInstanceState,
)


@dataclass(frozen=True, slots=True)
class RegistryReadiness:
    provider_count: int
    node_count: int
    current_vps_count: int
    credential_count: int

    @property
    def ready(self) -> bool:
        return (
            self.provider_count > 0
            and self.node_count > 0
            and self.current_vps_count >= self.node_count
            and self.credential_count >= self.node_count
        )


class RegistryOnboardingService:
    """Non-destructive bootstrap service for the initial provider/node registry.

    This service never calls provider APIs, never mutates the Master panel and never starts a
    replacement. It only records operator-supplied identities and secret references and never starts a replacement.
    """

    def __init__(self, database: Database) -> None:
        self.database = database

    async def readiness(self) -> RegistryReadiness:
        async with self.database.session() as session:
            providers = int(await session.scalar(select(func.count()).select_from(Provider)) or 0)
            nodes = int(await session.scalar(select(func.count()).select_from(Node)) or 0)
            current_vps = int(
                await session.scalar(
                    select(func.count()).select_from(VpsInstance).where(
                        VpsInstance.role == VpsInstanceRole.CURRENT,
                        VpsInstance.state != VpsInstanceState.DELETED,
                    )
                )
                or 0
            )
            credentials = int(
                await session.scalar(select(func.count()).select_from(NodeCredential)) or 0
            )
        return RegistryReadiness(
            provider_count=providers,
            node_count=nodes,
            current_vps_count=current_vps,
            credential_count=credentials,
        )

    async def list_providers(self) -> list[Provider]:
        async with self.database.session() as session:
            return await ProviderRepository(session).list_all()

    async def list_nodes(self) -> list[Node]:
        async with self.database.session() as session:
            return await NodeRepository(session).list_all(limit=500)

    async def register_provider(
        self,
        *,
        key: str,
        display_name: str,
        provider_type: ProviderType,
        credential_ref: str,
        default_region: str | None,
        default_server_type: str | None,
        default_image: str | None,
        credential_backend: SecretReferenceBackend = SecretReferenceBackend.ENVIRONMENT,
    ) -> Provider:
        key = key.strip().lower()
        display_name = display_name.strip()
        credential_ref = credential_ref.strip()
        default_region = (default_region or "").strip() or None
        default_server_type = (default_server_type or "").strip() or None
        default_image = (default_image or "").strip() or None
        if not all((key, display_name, credential_ref)):
            raise ValueError("provider key/name/credential are required")

        async with self.database.session() as session:
            repo = ProviderRepository(session)
            existing = await repo.get_by_key(key)
            if existing is not None:
                if existing.provider_type is not provider_type:
                    raise ValueError(
                        f"provider {key!r} already exists with type {existing.provider_type.value!r}"
                    )
                existing.display_name = display_name
                existing.credential_backend = credential_backend
                existing.credential_ref = credential_ref
                if default_region is not None:
                    existing.default_region = default_region
                if default_server_type is not None:
                    existing.default_server_type = default_server_type
                if default_image is not None:
                    existing.default_image = default_image
                existing.is_active = True
                await session.commit()
                return existing

            provider = Provider(
                key=key,
                display_name=display_name,
                provider_type=provider_type,
                is_active=True,
                credential_backend=credential_backend,
                credential_ref=credential_ref,
                default_region=default_region,
                default_server_type=default_server_type,
                default_image=default_image,
            )
            await repo.add(provider)
            await session.commit()
            return provider

    async def register_node(
        self,
        *,
        name: str,
        provider_key: str,
        master_node_id: str,
        current_host: str,
        current_port: int,
        provider_server_id: str,
        ssh_username: str,
        ssh_port: int,
        ssh_auth_method: SshAuthMethod,
        ssh_secret_ref: str,
        ssh_public_key: str | None,
        provider_host: str | None = None,
        region: str | None = None,
        server_type: str | None = None,
        provider_image: str | None = None,
        panel_base_path: str | None = None,
        api_token_ref: str | None = None,
    ) -> Node:
        name = name.strip()
        provider_key = provider_key.strip().lower()
        master_node_id = master_node_id.strip()
        current_host = current_host.strip()
        provider_server_id = provider_server_id.strip()
        provider_host = (provider_host or current_host).strip()
        ssh_username = ssh_username.strip()
        ssh_secret_ref = ssh_secret_ref.strip()
        if not all(
            (name, provider_key, master_node_id, current_host, provider_server_id, provider_host, ssh_username, ssh_secret_ref)
        ):
            raise ValueError("node identity, provider server ID and SSH fields are required")
        if not 1 <= current_port <= 65535 or not 1 <= ssh_port <= 65535:
            raise ValueError("node/SSH ports must be between 1 and 65535")
        if ssh_auth_method is SshAuthMethod.PRIVATE_KEY and not (ssh_public_key or "").strip():
            raise ValueError("private-key SSH requires the matching public key")

        async with self.database.session() as session:
            providers = ProviderRepository(session)
            nodes = NodeRepository(session)
            credentials = NodeCredentialRepository(session)
            vps_instances = VpsInstanceRepository(session)

            provider = await providers.get_by_key(provider_key)
            if provider is None:
                raise ValueError(f"provider {provider_key!r} is not registered")

            if (region or "").strip():
                provider.default_region = str(region).strip()
            if (server_type or "").strip():
                provider.default_server_type = str(server_type).strip()
            if (provider_image or "").strip():
                provider.default_image = str(provider_image).strip()

            existing = await nodes.get_by_name(name)
            if existing is not None:
                existing_current = await vps_instances.get_current_for_node(existing.id)
                existing_credential = await credentials.get_for_node(existing.id)
                stable_identity = (
                    existing.provider_id == provider.id
                    and existing.master_node_id == master_node_id
                    and existing_current is not None
                    and existing_current.provider_server_id == provider_server_id
                    and existing_credential is not None
                )
                if stable_identity:
                    # Re-running smart onboarding is an idempotent metadata/credential refresh.
                    # Stable provider/master/server IDs are the identity boundary; discovered host,
                    # port, region, type and image may safely be refreshed from read-only APIs.
                    existing.current_host = current_host
                    existing.current_port = current_port
                    existing_current.host = provider_host
                    existing_current.region = (region or "").strip() or existing_current.region
                    existing_current.server_type = (
                        (server_type or "").strip() or existing_current.server_type
                    )
                    existing_current.image = (
                        (provider_image or "").strip() or existing_current.image
                    )
                    existing_credential.ssh_username = ssh_username
                    existing_credential.ssh_port = ssh_port
                    existing_credential.ssh_auth_method = ssh_auth_method
                    existing_credential.secret_backend = SecretReferenceBackend.FILE
                    existing_credential.ssh_secret_ref = ssh_secret_ref
                    existing_credential.ssh_public_key = (ssh_public_key or "").strip() or None
                    existing_credential.panel_base_path = (
                        (panel_base_path or "").strip() or None
                    )
                    if (api_token_ref or "").strip():
                        existing_credential.api_token_ref = str(api_token_ref).strip()
                        existing_credential.api_token_backend = SecretReferenceBackend.FILE
                    await session.commit()
                    return existing
                raise ValueError(
                    f"node {name!r} already exists with different provider/master/server identity; "
                    "refusing to overwrite it"
                )

            duplicate_master = await session.scalar(
                select(Node).where(Node.master_node_id == master_node_id)
            )
            if duplicate_master is not None:
                raise ValueError(f"Master node ID {master_node_id!r} is already mapped")

            duplicate_vps = await vps_instances.get_by_provider_identity(provider.id, provider_server_id)
            if duplicate_vps is not None:
                raise ValueError("provider server ID is already registered to another VPS record")

            node = Node(
                name=name,
                master_node_id=master_node_id,
                provider_id=provider.id,
                current_host=current_host,
                current_port=current_port,
                _state=NodeState.UNKNOWN,
                monitoring_enabled=True,
                consecutive_failures=0,
                consecutive_successes=0,
            )
            await nodes.add(node)

            credential = NodeCredential(
                node_id=node.id,
                ssh_username=ssh_username,
                ssh_port=ssh_port,
                ssh_auth_method=ssh_auth_method,
                secret_backend=SecretReferenceBackend.FILE,
                ssh_secret_ref=ssh_secret_ref,
                ssh_public_key=(ssh_public_key or "").strip() or None,
                panel_base_path=(panel_base_path or "").strip() or None,
                api_token_ref=(api_token_ref or "").strip() or None,
                api_token_backend=(
                    SecretReferenceBackend.FILE if (api_token_ref or "").strip() else None
                ),
            )
            await credentials.add(credential)

            current_vps = VpsInstance(
                provider_id=provider.id,
                node_id=node.id,
                provider_server_id=provider_server_id,
                role=VpsInstanceRole.CURRENT,
                state=VpsInstanceState.RUNNING,
                host=provider_host,
                region=(region or "").strip() or provider.default_region,
                server_type=(server_type or "").strip() or provider.default_server_type,
                image=(provider_image or "").strip() or provider.default_image,
            )
            await vps_instances.add(current_vps)
            await session.commit()
            return node
