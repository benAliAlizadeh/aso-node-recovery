# Registry Data Model — Patch 01

Patch 01 establishes the core registry schema definitions only. Database connectivity, Alembic
migrations, repositories, checks, replacement jobs, VPS instances, deployments, events, and settings
are intentionally deferred to Patch 02.

## Design rules

- Local IDs are application-generated UUIDs.
- `Node.master_node_id` is the explicit durable mapping to the master 3X-UI node.
- A master mapping is never inferred from IP address.
- Provider-specific API behavior does not appear in the registry model.
- Raw provider API tokens, SSH passwords/private keys, panel passwords, and node API tokens are not
  plaintext database columns. Registry rows contain secret references only.
- Foreign keys and constraints use deterministic names so Alembic can generate stable migrations.
- Node state mutation is centralized in `NodeStateMachine`.

## Tables introduced

### `providers`

Represents one configured provider account/adapter registration.

Key fields:

- `id`
- `key` — stable unique local key
- `display_name`
- `provider_type` — currently `hetzner` or `linode`
- `is_active`
- `credential_backend`
- `credential_ref`
- timestamps

`credential_ref` identifies a secret source; it is not the API token itself.

### `nodes`

Represents one remote 3X-UI node known to ASO.

Key fields:

- `id` — local UUID
- `name`
- `master_node_id` — unique explicit mapping to master 3X-UI
- `provider_id`
- `current_host` / `current_port`
- `state`
- `state_changed_at`
- monitoring enablement and consecutive success/failure counters
- last check timestamps
- timestamps

The provider relationship is `RESTRICT` on delete so a provider cannot disappear while nodes still
reference it.

### `node_credentials`

One-to-one connection metadata for a node.

Key fields:

- `node_id`
- `ssh_username` / `ssh_port`
- `ssh_auth_method`
- `secret_backend`
- `ssh_secret_ref`
- optional panel username
- optional panel password/API token references
- timestamps

Deleting a node cascades to this metadata row. Secret material itself is not stored in plaintext.

## Node state machine

Approved states:

```text
UNKNOWN
HEALTHY
DEGRADED
FAILED
REPLACING
DEPLOYING
VERIFYING
DISABLED
```

Primary recovery path:

```text
UNKNOWN -> HEALTHY -> DEGRADED -> FAILED -> REPLACING
        -> DEPLOYING -> VERIFYING -> HEALTHY
```

The state graph also permits bounded recovery/retry paths where operationally necessary, for example
`DEGRADED -> HEALTHY`, `FAILED -> HEALTHY`, and deployment/verification failure back to replacement or
failed state. `DISABLED` may only re-enter service through `UNKNOWN`.

Re-applying the current state is an idempotent no-op. Invalid jumps raise
`InvalidNodeStateTransitionError`. Public `Node.state` is read-only; state changes go through
`NodeStateMachine`.

## Deferred to Patch 02

Patch 02 will add the remaining Phase 2 persistence layer:

- node checks
- replacement jobs
- VPS instances
- deployments
- events
- settings
- cross-table constraints for replacement safety/idempotency
- async database session/transaction management
- Alembic configuration and initial migration
- repositories
- database-focused tests
