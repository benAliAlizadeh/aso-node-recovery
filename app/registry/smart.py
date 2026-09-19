from __future__ import annotations

from pydantic import SecretStr

from app.core.config import Settings
from app.core.secrets import SecretResolver
from app.database import Database
from app.database.repositories import ProviderRepository
from app.deployment.ssh import AsyncSshCommandExecutor
from app.deployment.types import SshConnectionSpec
from app.models import SecretReferenceBackend, SshAuthMethod
from app.registry.discovery import SmartNodeDiscovery, SmartOnboardingDiscoveryService
from app.registry.service import RegistryOnboardingService
from app.models.enums import ProviderType


class SmartRegistryOnboardingService:
    """High-level, non-destructive onboarding with discovery before persistence."""

    def __init__(
        self,
        database: Database,
        settings: Settings,
        *,
        secret_resolver: SecretResolver | None = None,
    ) -> None:
        self.database = database
        self.settings = settings
        self.secret_resolver = secret_resolver or SecretResolver()
        self.registry = RegistryOnboardingService(database)
        self.discovery = SmartOnboardingDiscoveryService(
            settings,
            secret_resolver=self.secret_resolver,
        )

    async def validate_and_register_provider(
        self,
        *,
        key: str,
        display_name: str,
        provider_type: ProviderType,
        credential_ref: str,
        credential_backend: SecretReferenceBackend = SecretReferenceBackend.FILE,
    ):
        token = self.secret_resolver.resolve(credential_backend, credential_ref)
        await self.discovery.validate_provider_secret(provider_type, token)
        return await self.registry.register_provider(
            key=key,
            display_name=display_name,
            provider_type=provider_type,
            credential_ref=credential_ref,
            credential_backend=credential_backend,
            default_region=None,
            default_server_type=None,
            default_image=None,
        )

    async def discover_node(
        self,
        *,
        provider_key: str,
        provider_server_id: str,
        master_node_id: int,
        api_token_ref: str | None,
        region_override: str | None = None,
        server_type_override: str | None = None,
        image_override: str | None = None,
    ) -> SmartNodeDiscovery:
        async with self.database.session() as session:
            provider = await ProviderRepository(session).get_by_key(provider_key.strip().lower())
            if provider is None:
                raise ValueError(f"provider {provider_key!r} is not registered")

        node_api_token: SecretStr | None = None
        if (api_token_ref or "").strip():
            node_api_token = self.secret_resolver.resolve(
                SecretReferenceBackend.FILE,
                str(api_token_ref).strip(),
            )
        return await self.discovery.discover_existing_node(
            provider,
            provider_server_id=provider_server_id,
            master_node_id=master_node_id,
            node_api_token=node_api_token,
            region_override=region_override,
            server_type_override=server_type_override,
            image_override=image_override,
        )

    async def validate_and_register_node(
        self,
        *,
        name: str | None,
        provider_key: str,
        provider_server_id: str,
        master_node_id: int,
        ssh_username: str,
        ssh_port: int,
        ssh_auth_method: SshAuthMethod,
        ssh_secret_ref: str,
        ssh_public_key: str | None,
        api_token_ref: str | None,
        region_override: str | None = None,
        server_type_override: str | None = None,
        image_override: str | None = None,
    ):
        discovered = await self.discover_node(
            provider_key=provider_key,
            provider_server_id=provider_server_id,
            master_node_id=master_node_id,
            api_token_ref=api_token_ref,
            region_override=region_override,
            server_type_override=server_type_override,
            image_override=image_override,
        )
        ssh_secret = self.secret_resolver.resolve(SecretReferenceBackend.FILE, ssh_secret_ref)
        ssh_result = await AsyncSshCommandExecutor().run(
            SshConnectionSpec(
                host=discovered.provider_host,
                port=ssh_port,
                username=ssh_username,
                auth_method=ssh_auth_method,
                secret=ssh_secret,
                verify_host_key=self.settings.ssh_verify_host_key,
                known_hosts=self.settings.effective_ssh_known_hosts_path,
            ),
            "printf ASO_SSH_READY",
            timeout_seconds=min(15.0, self.settings.ssh_ready_timeout_seconds),
        )
        if ssh_result.exit_status != 0 or ssh_result.stdout != "ASO_SSH_READY":
            raise ValueError("SSH validation failed")

        chosen_name = (name or "").strip() or discovered.suggested_name
        node = await self.registry.register_node(
            name=chosen_name,
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
            ssh_public_key=ssh_public_key,
            panel_base_path=discovered.master.base_path,
            api_token_ref=api_token_ref,
        )
        return node, discovered
