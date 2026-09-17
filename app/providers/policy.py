from __future__ import annotations

from uuid import UUID

from app.core.errors import ConfigurationError, SafetyViolationError
from app.models.provider import Provider
from app.providers.errors import ProviderError
from app.providers.types import ProvisioningCapacity


class ProviderSelectionPolicy:
    """Deterministic provider choice without leaking provider-specific behavior."""

    def select(self, providers: list[Provider], *, preferred_id: UUID | None = None) -> Provider:
        active = [provider for provider in providers if provider.is_active is not False]
        if preferred_id is not None:
            for provider in active:
                if provider.id == preferred_id:
                    return provider
            raise ConfigurationError("preferred provider is not active or does not exist")
        if not active:
            raise ConfigurationError("no active provider is configured")
        return sorted(active, key=lambda provider: provider.key)[0]


class ProvisioningSafetyPolicy:
    def __init__(
        self,
        *,
        max_replacement_attempts: int,
        max_temporary_servers: int,
        max_concurrent_replacements: int,
    ) -> None:
        self.max_replacement_attempts = max_replacement_attempts
        self.max_temporary_servers = max_temporary_servers
        self.max_concurrent_replacements = max_concurrent_replacements

    def validate(self, *, attempt_number: int, capacity: ProvisioningCapacity) -> None:
        if attempt_number < 1 or attempt_number > self.max_replacement_attempts:
            raise SafetyViolationError("replacement attempt limit reached")
        if capacity.active_temporary_servers >= self.max_temporary_servers:
            raise SafetyViolationError("temporary VPS limit reached")
        if capacity.active_replacements >= self.max_concurrent_replacements:
            raise SafetyViolationError("concurrent replacement limit reached")


class ProviderRetryPolicy:
    """Classify provider errors for the persisted Phase 6 retry workflow.

    This policy deliberately does not retry create-server calls by itself. A timeout after a POST may
    be ambiguous (the cloud can create the server even if ASO did not receive the response). The
    crash-safe orchestrator must reconcile provider state before issuing another create.
    """

    def __init__(self, *, max_attempts: int) -> None:
        self.max_attempts = max_attempts

    def should_retry(self, error: ProviderError, *, attempt_number: int) -> bool:
        return error.retryable and attempt_number < self.max_attempts
