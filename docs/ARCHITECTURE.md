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

Phases 2-5 are implemented: persistence/registry, monitoring, provider adapters/provisioning, and the
SSH/3X-UI deployment engine. Phase 6 Master mutation and replacement orchestration remain absent.

Provider responsibilities are split into:

- `ProviderAdapter`: provider-neutral lifecycle contract.
- `HetznerProvider` / `LinodeProvider`: current documented API formats only.
- `ProviderFactory`: dry-run/real adapter selection behind a double safety guard.
- `ProvisioningSafetyPolicy`: attempts, temporary server count, and concurrency limits.
- `ProvisioningService`: bounded lifecycle for the newly created temporary VPS only.

Deployment responsibilities are split into:

- `AsyncSshCommandExecutor`: transport only.
- `SshReadinessProbe`: bounded SSH readiness retry.
- `RemoteOsDetector` / `RemoteBootstrapper`: host preparation.
- `ThreeXUiInstaller`: all upstream 3X-UI shell/install behavior.
- `ThreeXUiNodeApiVerifier`: Bearer-token `/panel/api/server/status` verification.
- `DeploymentStateMachine` / `DeploymentService`: ordered deployment workflow.

## Duplicate prevention

A database-backed per-node monitoring lease prevents overlapping checks across worker instances.
Replacement jobs retain the `(node_id, active_slot)` unique constraint created in Phase 2. Phase 6
will add persisted reconciliation/locks around the provider and deployment components rather than
adding blind create retries here.

## Safety boundary

`DRY_RUN=true` and `ALLOW_REAL_INFRASTRUCTURE_MUTATION=false` are independent defaults. Provider and
SSH/deployment mutation require explicit opt-in. The project still contains no Master mutation client,
no replacement orchestrator, and no old-VPS deletion path.
