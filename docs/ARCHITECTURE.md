# Architecture

## Dependency direction

```text
API / Telegram / Schedulers
          |
          v
Workers / Application Services / Replacement Orchestrator
          |
          v
Domain policy / persistence contracts
          ^
          |
Provider / Check-Host / SSH / Master adapters
```

Provider-specific code remains outside the replacement workflow. Check-Host parsing remains inside its
adapter/health layer. SSH/3X-UI shell behavior remains isolated inside deployment. Telegram Phase 7
will call application services rather than provider or master APIs directly.

## Phase 6 composition

`ReplacementOrchestrator` coordinates already-isolated components:

- `ProviderManager` / `ProvisioningService`
- `ReplacementReachabilityVerifier`
- `DeploymentService` / `NodeSshSpecFactory`
- `Master3XUiClient`
- SQLAlchemy repositories / durable workflow checkpoints
- `RuntimeSecretStore`
- `OldVpsProtectionGuard`

## Concurrency / idempotency

Three layers protect the workflow:

1. PostgreSQL unique `(node_id, active_slot)` means one active replacement per node.
2. A global PostgreSQL advisory lock serializes short admission/capacity decisions.
3. A persisted per-job lease prevents two workers from resuming the same job concurrently.

Cloud creation uses deterministic names and provider lookup-before-create so a crash after provider
side effects does not automatically create a duplicate VPS. Deployment state is persisted between SSH
substeps. Master update is idempotently rebuildable from the saved snapshot + deployment artifacts.

## Destructive boundary

The orchestrator has exactly one old-VPS cleanup checkpoint. `OldVpsProtectionGuard` requires durable
proof of new IP, deployment, master update, master verification, and final health before provider
deletion is reachable. The old server stays alive through every earlier failure/rollback path.

DRY_RUN simulates the candidate path without mutating the real current-node/current-VPS registry.
