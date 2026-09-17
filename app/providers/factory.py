from __future__ import annotations

from app.core.config import Settings
from app.core.errors import SafetyViolationError
from app.core.secrets import SecretResolver
from app.models.enums import ProviderType
from app.models.provider import Provider
from app.providers.base import ProviderAdapter
from app.providers.dry_run import DryRunProvider
from app.providers.hetzner import HetznerProvider
from app.providers.linode import LinodeProvider


class ProviderFactory:
    def __init__(self, settings: Settings, secret_resolver: SecretResolver | None = None) -> None:
        self.settings = settings
        self.secret_resolver = secret_resolver or SecretResolver()

    def create(self, provider: Provider) -> ProviderAdapter:
        if self.settings.dry_run:
            return DryRunProvider(provider.provider_type)
        if not self.settings.allow_real_infrastructure_mutation:
            raise SafetyViolationError(
                "real provider mutations require ASO_ALLOW_REAL_INFRASTRUCTURE_MUTATION=true"
            )

        token = self.secret_resolver.resolve(provider.credential_backend, provider.credential_ref)
        if provider.provider_type is ProviderType.HETZNER:
            return HetznerProvider(token, base_url=self.settings.hetzner_api_base_url)
        if provider.provider_type is ProviderType.LINODE:
            return LinodeProvider(token, base_url=self.settings.linode_api_base_url)
        raise ValueError(f"unsupported provider type: {provider.provider_type}")
