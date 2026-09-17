from __future__ import annotations

from app.providers.base import ProviderAdapter
from app.providers.policy import ProvisioningSafetyPolicy
from app.providers.types import CreateServerRequest, ProviderServer, ProvisioningCapacity


class ProvisioningService:
    """Bounded, crash-recovery-friendly lifecycle for a replacement VPS.

    Creation and readiness are intentionally separate operations. Phase 6 must persist the returned
    provider server identity immediately after ``create_temporary()`` and only then wait for readiness.
    This avoids hiding a real cloud resource inside a long-running create+wait call.

    This service only accepts the newly created temporary provider server ID for deletion. It has no
    old/current VPS identifier and therefore cannot delete the active node by accident.
    """

    def __init__(
        self,
        safety_policy: ProvisioningSafetyPolicy,
        *,
        timeout_seconds: float = 300.0,
        poll_interval_seconds: float = 3.0,
    ) -> None:
        self.safety_policy = safety_policy
        self.timeout_seconds = timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds

    async def create_temporary(
        self,
        adapter: ProviderAdapter,
        request: CreateServerRequest,
        *,
        attempt_number: int,
        capacity: ProvisioningCapacity,
    ) -> ProviderServer:
        self.safety_policy.validate(attempt_number=attempt_number, capacity=capacity)
        return await adapter.create_server(request)

    async def wait_until_ready(
        self, adapter: ProviderAdapter, provider_server_id: str
    ) -> ProviderServer:
        return await adapter.wait_until_ready(
            provider_server_id,
            timeout_seconds=self.timeout_seconds,
            poll_interval_seconds=self.poll_interval_seconds,
        )

    async def delete_temporary(self, adapter: ProviderAdapter, provider_server_id: str) -> None:
        await adapter.delete_server(provider_server_id)
