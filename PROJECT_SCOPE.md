# ASO Node Recovery — Project Scope

## Problem statement

ASO operates a master 3X-UI panel outside Iran and multiple remote 3X-UI nodes. A remote
node can remain healthy from the master's network while its public IP becomes unreachable
from Iran. Recovery is currently a manual, multi-step infrastructure procedure with a real
risk of deleting the old server too early or losing the mapping to the existing master node.

## Current manual workflow

1. Detect that a node is unreachable from Iran.
2. Identify its cloud VPS.
3. Keep enough information to rebuild the node.
4. Create a replacement VPS.
5. Test the replacement IP from Iran using Check-Host.
6. If the IP is bad, destroy only the temporary replacement and retry.
7. If the IP is good, wait for SSH and install/configure 3X-UI.
8. Read the generated node configuration.
9. Update the existing node entry on the master 3X-UI panel.
10. Verify the replacement node and master-side update.
11. Delete the old VPS only after all replacement verification succeeds.

## Target automated workflow

The system will persist and orchestrate an on-demand replacement workflow:

`failure detected -> replacement job -> temporary VPS -> IP validation -> SSH -> 3X-UI
installation -> node verification -> existing master node update -> master verification ->
final health validation -> old VPS deletion -> complete`

A bad replacement IP causes only the temporary VPS to be deleted, followed by a bounded
retry. The old VPS is not part of that retry cleanup.

## Goals

- Detect sustained node reachability failures from Iran without reacting to one transient check.
- Provision replacement VPS instances on demand through provider adapters.
- Validate candidate IPs before deployment.
- Deploy and verify 3X-UI through an isolated deployment component.
- Update the explicitly mapped existing node in the master panel rather than creating duplicates.
- Persist every replacement step so jobs can resume safely after process restarts.
- Enforce idempotency, per-node exclusivity, concurrency limits, retry limits, and audit events.
- Provide Telegram administration only after the recovery engine is independently safe and usable.
- Keep ordinary development and tests independent from real infrastructure.

## Non-goals

- Maintaining a permanent spare VPS or spare IP pool.
- Deleting or modifying production infrastructure during ordinary development or automated tests.
- Guessing undocumented Check-Host, provider, or 3X-UI API behavior.
- Using IP addresses as the identity mapping between local nodes and master nodes.
- Embedding provider-specific behavior into the replacement orchestrator.
- Embedding business logic in Telegram handlers.
- Treating a single failed reachability check as proof that a node must be replaced.

## Safety requirements

1. `DRY_RUN` defaults to `true`.
2. Development must not create, delete, reboot, or mutate real VPS instances without explicit
   authorization for a specific production test.
3. Development must not modify a real master 3X-UI node without explicit authorization.
4. Retry loops must be bounded by configurable attempt and concurrency limits.
5. Secrets must come from configuration/environment and must never be emitted to logs.
6. Destructive provider actions must pass centralized safety checks before execution.
7. Only one active replacement job may exist for a node.
8. Replacement state must be persisted before and after external side effects as appropriate.
9. The old VPS is protected by a hard deletion guard.

## Replacement lifecycle

1. Node reaches a configured failure threshold.
2. Create or resume its single active replacement job.
3. Provision one temporary replacement VPS.
4. Obtain its candidate public IP.
5. Test the candidate IP from Iran.
6. If the candidate fails, delete only that temporary VPS and retry within configured limits.
7. Wait for SSH readiness on a good candidate.
8. Bootstrap and install 3X-UI.
9. Extract required node configuration and verify the replacement node API/panel.
10. Update the explicitly mapped existing master node.
11. Read back and verify the master-side state.
12. Perform final health/reachability validation.
13. Delete the old VPS only when every required verification has succeeded.
14. Mark the replacement job completed and retain its audit history.

## Hard old-VPS protection rule

The old VPS **must never be deleted** before all of the following are true:

- replacement VPS exists;
- replacement IP passed reachability validation;
- SSH connectivity succeeded;
- 3X-UI installation succeeded;
- replacement node API/panel verification succeeded;
- master node update succeeded;
- master node update was read back/verified;
- final health check succeeded.

Any missing or uncertain condition blocks old-VPS deletion.

## Assumptions

- The master panel and provider APIs are reachable from the control plane.
- Check-Host or an equivalent verified mechanism can provide Iran-side reachability evidence.
- Provider credentials permit the required lifecycle operations when production mode is later enabled.
- The existing master node has a stable identifier that can be explicitly stored locally.
- Supported replacement hosts expose SSH and run an OS/architecture supported by the approved
  3X-UI installation process.
- External API behavior will be implemented only after verifying current official documentation/source.

## Terminology

- **Node**: A remote 3X-UI node represented locally and mapped to one master node identifier.
- **Master**: The authoritative 3X-UI panel that holds the existing node entry used by clients.
- **Old VPS**: The currently associated server being replaced; it remains protected until cutover succeeds.
- **Temporary VPS**: A newly provisioned candidate server created on demand for one replacement attempt.
- **Replacement Job**: Persisted workflow coordinating safe replacement of one node.
- **Candidate IP**: Public IP of a temporary VPS before it has passed all acceptance checks.
- **Deployment**: SSH/bootstrap/install/configuration/verification work performed on a replacement VPS.
- **Dry run**: Safety mode in which destructive external infrastructure actions are forbidden.

## High-level success criteria

The project is successful when it can, under production authorization:

- detect sustained Iran-side node failure;
- start exactly one replacement job for that node;
- create replacement capacity only on demand;
- discard bad temporary candidates safely and within bounded retry limits;
- deploy and verify a good candidate;
- update and verify the existing mapped master node;
- survive a process restart without duplicating infrastructure work;
- refuse unsafe cleanup when prerequisites are incomplete;
- delete the old VPS only after successful end-to-end replacement verification;
- expose traceable audit events without leaking secrets.

## Explicit capacity policy

ASO Node Recovery does **not** maintain permanent spare VPS or IP pools. Replacement capacity
is created only after a node requires recovery and is cleaned up after the workflow finishes.
## Runtime control extension (v1.4)

Per-node operating modes are explicit: disabled, monitor-only, or auto-repair. Telegram can change
runtime monitoring, automatic-repair, and dry-run/live intent without editing database records by
hand. Persisted runtime intent never bypasses environment safety gates; when the host is not
live-capable the effective execution mode is always dry-run.
