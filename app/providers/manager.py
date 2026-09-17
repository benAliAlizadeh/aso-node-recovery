from __future__ import annotations

from uuid import UUID

from app.models.provider import Provider
from app.providers.base import ProviderAdapter
from app.providers.factory import ProviderFactory


class ProviderManager:
    """Keep one adapter instance per configured provider during the process lifetime.

    Besides avoiding unnecessary client creation, this preserves DryRunProvider state across create,
    inspect, reboot, and delete operations in development.
    """

    def __init__(self, factory: ProviderFactory) -> None:
        self.factory = factory
        self._adapters: dict[UUID, ProviderAdapter] = {}

    def get(self, provider: Provider) -> ProviderAdapter:
        if provider.id is None:
            raise ValueError("provider must have a persisted id before adapter resolution")
        adapter = self._adapters.get(provider.id)
        if adapter is None:
            adapter = self.factory.create(provider)
            self._adapters[provider.id] = adapter
        return adapter

    async def close(self) -> None:
        adapters = list(self._adapters.values())
        self._adapters.clear()
        for adapter in adapters:
            await adapter.aclose()
