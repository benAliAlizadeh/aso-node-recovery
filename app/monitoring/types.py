from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ProbeStatus(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    PENDING = "pending"
    MALFORMED = "malformed"


class ReachabilityDecision(StrEnum):
    REACHABLE = "reachable"
    UNREACHABLE = "unreachable"
    INDETERMINATE = "indeterminate"


@dataclass(frozen=True, slots=True)
class CheckHostRequest:
    request_id: str
    permanent_link: str | None
    nodes: tuple[str, ...]
    target: str


@dataclass(frozen=True, slots=True)
class ProbeResult:
    node: str
    status: ProbeStatus
    latency_seconds: float | None = None
    address: str | None = None
    error: str | None = None
    raw: Any = None


@dataclass(frozen=True, slots=True)
class CheckHostSummary:
    request_id: str
    target: str
    probes: tuple[ProbeResult, ...]

    @property
    def success_count(self) -> int:
        return sum(probe.status is ProbeStatus.SUCCESS for probe in self.probes)

    @property
    def failure_count(self) -> int:
        return sum(probe.status is ProbeStatus.FAILURE for probe in self.probes)

    @property
    def pending_count(self) -> int:
        return sum(probe.status is ProbeStatus.PENDING for probe in self.probes)

    @property
    def malformed_count(self) -> int:
        return sum(probe.status is ProbeStatus.MALFORMED for probe in self.probes)

    @property
    def total_nodes(self) -> int:
        return len(self.probes)

    @property
    def is_complete(self) -> bool:
        return self.pending_count == 0
