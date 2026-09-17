# Architecture

## Dependency direction

External systems are adapters around application/domain logic. Provider-specific code, Check-Host
protocol details, SSH commands, master API details, and Telegram transport behavior must not leak into
the replacement orchestration core.

Conceptual dependency direction:

```text
API / Telegram / Workers
          |
          v
Application Services / Orchestrator
          |
          v
Domain policy / persistence contracts
          ^
          |
Provider / Check-Host / SSH / Master adapters
```

## Current milestone

The repository now contains Phase 1 foundation plus **Phase 2 / Patch 01 registry core**:

- SQLAlchemy declarative metadata and naming conventions
- Provider registry model
- Node registry model with explicit master-node mapping
- Node credential references without plaintext secret columns
- Central node state machine

Database sessions, Alembic migrations, repositories, monitoring records, replacement jobs, VPS
instances, deployments, events, and settings remain deferred to Patch 02.

## Safety boundary

No provider adapter, Check-Host client, SSH implementation, 3X-UI installer, or master mutation client
exists in this patch. `DRY_RUN=true` remains the default, and Patch 01 performs no infrastructure side
effects.
