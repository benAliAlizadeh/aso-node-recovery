from __future__ import annotations

from uuid import UUID

from app.models.provider import Provider
from app.providers.base import ProviderAdapter
from app.providers.factory import ProviderFactory


class ProviderManager:
    """Keep adapter instances per provider and execution mode.

    A live-capable host may still run an individual replacement in DRY_RUN. Keeping dry-run and live
    adapters in separate cache slots prevents a previously cached adapter from crossing that safety
    boundary.
    """

    def __init__(self, factory: ProviderFactory) -> None:
        self.factory = factory
        self._adapters: dict[tuple[UUID, bool], ProviderAdapter] = {}

    def get(self, provider: Provider, *, dry_run: bool | None = None) -> ProviderAdapter:
        if provider.id is None:
            raise ValueError("provider must have a persisted id before adapter resolution")
        effective_dry_run = self.factory.settings.dry_run if dry_run is None else bool(dry_run)
        key = (provider.id, effective_dry_run)
        adapter = self._adapters.get(key)
        if adapter is None:
            adapter = self.factory.create(provider, dry_run=effective_dry_run)
            self._adapters[key] = adapter
        return adapter

    async def close(self) -> None:
        adapters = list(self._adapters.values())
        self._adapters.clear()
        for adapter in adapters:
            await adapter.aclose()
