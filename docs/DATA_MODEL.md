# Data Model — Phase 2 Complete

## Design rules

- Application-generated UUID primary keys.
- Explicit `Node.master_node_id`; never infer master mapping from IP.
- Secret references only for provider/SSH/panel credentials.
- Deterministic constraint/index names for Alembic.
- Node state changes go through `NodeStateMachine`.
- One active replacement job per node is enforced in the database.
- Monitoring duplicate prevention uses a persisted lease on the node row.
- `events` are append-only audit records and must not contain secrets.
- `settings` is for operational values only, never credentials.

## Tables

### `providers`
Provider registration, adapter type, active flag, and credential reference.

### `nodes`
Local node identity, explicit master mapping, current endpoint, health state/counters, last checks, and
monitoring lease.

### `node_credentials`
One-to-one SSH/panel connection metadata with secret references instead of raw secrets.

### `node_checks`
Normalized monitoring observations including request ID, target, outcome, quorum counts, safe
per-probe details, and error metadata.

### `vps_instances`
Provider-neutral representation of the current or replacement VPS. Provider server identity is unique
within a provider.

### `replacement_jobs`
Persisted recovery workflow checkpoint. Stores state, attempt counters, and explicit old/new VPS
references. `(node_id, active_slot)` prevents concurrent active replacement jobs for one node.

### `deployments`
Per-job deployment attempts associated with a concrete VPS.

### `events`
Audit/event stream for node and replacement lifecycle events.

### `settings`
Non-secret operational settings that may later be managed from Telegram/administration.

## Migrations

The initial Alembic revision is:

```text
20260917_0001_registry_and_monitoring
```

All future schema changes must be delivered through new Alembic revisions.
