from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings
from app.monitoring.check_host import CheckHostClient
from app.monitoring.health import ReachabilityEvaluator
from app.monitoring.types import CheckHostSummary, ReachabilityDecision


@dataclass(frozen=True, slots=True)
class ReplacementReachabilityResult:
    decision: ReachabilityDecision
    summary: CheckHostSummary

    @property
    def reachable(self) -> bool:
        return self.decision is ReachabilityDecision.REACHABLE


class ReplacementReachabilityVerifier:
    """Check a newly provisioned IP from the configured Iran Check-Host nodes."""

    def __init__(self, client: CheckHostClient, settings: Settings) -> None:
        self.client = client
        self.settings = settings

    async def verify(self, host: str) -> ReplacementReachabilityResult:
        """Verify the candidate from Iran Check-Host nodes."""
        nodes = await self.client.resolve_nodes(
            configured_nodes=self.settings.check_host_nodes,
            country_code=self.settings.check_host_country_code,
            max_nodes=self.settings.check_host_max_nodes,
        )
        return await self._verify_with_nodes(
            host,
            nodes=nodes,
            min_success_nodes=self.settings.check_host_min_success_nodes,
        )

    async def verify_external(self, host: str) -> ReplacementReachabilityResult:
        """Confirm outside-Iran reachability before interpreting an Iran-side failure."""
        nodes = await self.client.resolve_nodes(
            configured_nodes=(),
            country_code=None,
            max_nodes=self.settings.replacement_external_check_max_nodes,
            exclude_country_codes=(self.settings.check_host_country_code,),
        )
        return await self._verify_with_nodes(
            host,
            nodes=nodes,
            min_success_nodes=self.settings.replacement_external_check_min_success_nodes,
        )

    async def _verify_with_nodes(
        self,
        host: str,
        *,
        nodes: tuple[str, ...],
        min_success_nodes: int,
    ) -> ReplacementReachabilityResult:
        request = await self.client.create_tcp_check(
            host, self.settings.replacement_ip_check_port, nodes=nodes
        )
        summary = await self.client.poll_result(
            request,
            timeout_seconds=self.settings.check_host_result_timeout_seconds,
            poll_interval_seconds=self.settings.check_host_poll_interval_seconds,
        )
        decision = ReachabilityEvaluator.evaluate(
            summary,
            min_success_nodes=min_success_nodes,
        )
        return ReplacementReachabilityResult(decision=decision, summary=summary)
