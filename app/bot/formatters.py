from __future__ import annotations

from datetime import datetime

from app.control import (
    DashboardSnapshot,
    EventSnapshot,
    JobSnapshot,
    NodeDetailSnapshot,
    NodeSnapshot,
    ProviderSnapshot,
)
from app.models import ReplacementCheckpoint


def _dt(value: datetime | None) -> str:
    return value.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z") if value else "—"


def short_id(value: object) -> str:
    return str(value).split("-")[0]


def format_dashboard(snapshot: DashboardSnapshot) -> str:
    counts = snapshot.node_counts
    return "\n".join(
        [
            "ASO Node Recovery",
            "",
            f"Healthy: {counts.get('healthy', 0)}",
            f"Degraded: {counts.get('degraded', 0)}",
            f"Failed: {counts.get('failed', 0)}",
            f"Replacing: {counts.get('replacing', 0)}",
            f"Deploying: {counts.get('deploying', 0)}",
            f"Verifying: {counts.get('verifying', 0)}",
            f"Disabled: {counts.get('disabled', 0)}",
            f"Active VPS: {snapshot.active_vps_count}",
            f"Active replacement jobs: {snapshot.active_replacement_count}",
            "",
            f"System: {'PAUSED' if snapshot.paused else 'RUNNING'}",
            f"DRY_RUN: {snapshot.dry_run}",
            f"Real mutations allowed: {snapshot.real_mutation_allowed}",
        ]
    )


def format_nodes(nodes: list[NodeSnapshot]) -> str:
    if not nodes:
        return "No nodes are registered. On the server run: ./asoctl setup"
    lines = ["Nodes:"]
    for node in nodes:
        lines.append(
            f"- {node.name} [{node.state.value}/{node.operation_mode.value}] {node.host}:{node.port} "
            f"(id {short_id(node.id)})"
        )
    return "\n".join(lines)


def format_node_detail(detail: NodeDetailSnapshot) -> str:
    node = detail.node
    return "\n".join(
        [
            f"Node: {node.name}",
            f"ID: {node.id}",
            f"State: {node.state.value}",
            f"Operation mode: {node.operation_mode.value}",
            f"Endpoint: {node.host}:{node.port}",
            f"Master Node ID: {detail.master_node_id}",
            f"Monitoring: {'on' if detail.monitoring_enabled else 'off'}",
            f"Consecutive failures: {node.consecutive_failures}",
            f"Last check: {_dt(detail.last_checked_at)}",
            f"Last success: {_dt(node.last_successful_check_at)}",
            f"Latest check result: "
            f"{detail.latest_check_outcome.value if detail.latest_check_outcome else '—'}",
            f"Latest job: {detail.latest_job_state.value if detail.latest_job_state else '—'}",
            f"Latest checkpoint: "
            f"{detail.latest_job_checkpoint.value if detail.latest_job_checkpoint else '—'}",
        ]
    )


def format_jobs(jobs: list[JobSnapshot]) -> str:
    if not jobs:
        return "No replacement jobs found."
    lines = ["Recent replacement jobs:"]
    for job in jobs:
        lines.append(
            f"- {short_id(job.id)} node={short_id(job.node_id)} "
            f"{job.state.value}/{job.checkpoint.value} "
            f"attempt={job.attempt_count}/{job.max_attempts}"
        )
    return "\n".join(lines)


_PROGRESS = (
    (
        "Creating VPS",
        {
            ReplacementCheckpoint.CREATED,
            ReplacementCheckpoint.PROVISIONING,
            ReplacementCheckpoint.PROVISIONED,
        },
    ),
    (
        "Checking IP",
        {
            ReplacementCheckpoint.CHECKING_IP,
            ReplacementCheckpoint.TEMP_CLEANUP,
            ReplacementCheckpoint.IP_VERIFIED,
        },
    ),
    ("Installing 3X-UI", {ReplacementCheckpoint.DEPLOYING}),
    ("Verifying node", {ReplacementCheckpoint.NODE_VERIFIED}),
    (
        "Updating Master",
        {ReplacementCheckpoint.MASTER_UPDATING, ReplacementCheckpoint.MASTER_UPDATED},
    ),
    (
        "Verifying Master",
        {ReplacementCheckpoint.MASTER_VERIFYING, ReplacementCheckpoint.MASTER_VERIFIED},
    ),
    ("Final Check", {ReplacementCheckpoint.FINAL_CHECK, ReplacementCheckpoint.FINAL_VERIFIED}),
    ("Cleanup", {ReplacementCheckpoint.OLD_VPS_CLEANUP, ReplacementCheckpoint.COMPLETED}),
)


def format_job_progress(job: JobSnapshot) -> str:
    if job.checkpoint is ReplacementCheckpoint.FAILED:
        suffix = f"\nError: {job.last_error_message}" if job.last_error_message else ""
        return f"Replacement {short_id(job.id)}: FAILED{suffix}"
    if job.checkpoint is ReplacementCheckpoint.CANCELLED:
        return f"Replacement {short_id(job.id)}: CANCELLED"

    current_index = 0
    for index, (_, checkpoints) in enumerate(_PROGRESS):
        if job.checkpoint in checkpoints:
            current_index = index
            break

    lines = [f"Replacement {short_id(job.id)}", ""]
    for index, (label, _) in enumerate(_PROGRESS):
        if job.checkpoint is ReplacementCheckpoint.COMPLETED or index < current_index:
            icon = "✅"
        elif index == current_index:
            icon = "🔄"
        else:
            icon = "⏳"
        lines.append(f"{index + 1}/8 {label:<18} {icon}")
    if job.checkpoint is ReplacementCheckpoint.COMPLETED:
        lines.append("\nCOMPLETED")
    return "\n".join(lines)


def format_events(events: list[EventSnapshot]) -> str:
    if not events:
        return "No audit events found."
    lines = ["Recent events:"]
    for event in events:
        lines.append(
            f"- {_dt(event.created_at)} [{event.severity.value}] "
            f"{event.event_type.value}: {event.message}"
        )
    return "\n".join(lines)


def format_providers(providers: list[ProviderSnapshot]) -> str:
    if not providers:
        return "No providers are configured. On the server run: ./asoctl setup"
    lines = ["Providers:"]
    for provider in providers:
        lines.append(
            f"- {provider.display_name} ({provider.provider_type}) "
            f"{'ACTIVE' if provider.is_active else 'DISABLED'} id={short_id(provider.id)}"
        )
    return "\n".join(lines)


def format_settings(values: dict[str, object]) -> str:
    lines = ["Effective operational settings:"]
    for key in sorted(values):
        lines.append(f"- {key}: {values[key]}")
    return "\n".join(lines)
