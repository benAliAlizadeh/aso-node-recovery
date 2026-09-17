# Architecture

## Dependency direction

External systems are adapters around application/domain logic. Provider-specific code, Check-Host
protocol details, SSH commands, master API details, and Telegram transport behavior must not leak into
the replacement orchestration core.

```text
API / Telegram / Schedulers
          |
          v
Workers / Application Services / Orchestrator
          |
          v
Domain policy / persistence contracts
          ^
          |
Provider / Check-Host / SSH / Master adapters
```

## Current milestone

Phase 2 persistence is complete and Phase 3 monitoring is implemented.

The persistence layer now covers providers, nodes, credential references, checks, VPS instances,
replacement jobs, deployments, events, and operational settings. Alembic owns schema evolution.

Monitoring is split into distinct concerns:

- `CheckHostClient`: Check-Host HTTP protocol only.
- `ReachabilityEvaluator`: provider-independent quorum calculation.
- `NodeHealthCalculator`: failure/recovery counters and state policy.
- `MonitoringWorker`: persistence + lease + one monitoring iteration.
- `MonitoringScheduler`: timing only; no health business logic.

## Duplicate prevention

A database-backed per-node monitoring lease prevents overlapping checks across worker instances.
APScheduler additionally uses `max_instances=1` for the cycle job. The database lease is the durable
control; the scheduler option is only a local guard.

Replacement jobs also have a `(node_id, active_slot)` unique constraint. Active jobs use
`active_slot=true`; terminal jobs will clear it to NULL in the Phase 6 workflow, allowing history while
preventing two active replacements for one node.

## Safety boundary

No provider adapter, SSH implementation, 3X-UI installer, master mutation client, or replacement
orchestrator exists yet. Monitoring failure only persists state/events; it cannot touch infrastructure.
`DRY_RUN=true` remains the default.
