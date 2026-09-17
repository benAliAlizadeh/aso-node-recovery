# ASO Node Recovery

Safety-first control plane for on-demand recovery of remote 3X-UI nodes whose public IPs become
unreachable from Iran.

> Current milestone: **Phase 4 Providers + Phase 5 Deployment / Patch 03**.
> Monitoring/registry are complete. Master 3X-UI mutation, crash-safe replacement orchestration, and
> Telegram/production control remain deferred to the next phases.

## Safety status

- `ASO_DRY_RUN=true` remains the default.
- `ASO_ALLOW_REAL_INFRASTRUCTURE_MUTATION=false` is a second independent default guard.
- No provider network call occurs through `ProviderFactory` while dry-run is enabled.
- Real provider/SSH mutation requires both guards to be explicitly changed.
- No Master 3X-UI mutation client exists yet.
- No old-VPS deletion path exists yet.
- Provider provisioning code can clean up only the **new temporary VPS** created by its invocation.
- Permanent spare VPS/IP pools remain explicitly out of scope.
- Old VPS deletion will remain forbidden until Phase 6 verifies the full replacement chain.

Read [PROJECT_SCOPE.md](PROJECT_SCOPE.md), [docs/PROVIDERS.md](docs/PROVIDERS.md),
[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md), and [docs/MONITORING.md](docs/MONITORING.md).

## Requirements

- Python 3.12+
- PostgreSQL
- Docker + Docker Compose (optional for local development)

## Local development

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
cp .env.example .env
uvicorn app.main:app --reload
```

Health endpoint:

```text
GET /health
```

Current version:

```text
0.5.0-providers-deployment
```

## Completed architecture

### Phase 2 — Registry / persistence

Providers, nodes, secret references, checks, VPS instances, replacement jobs, deployments, audit
events, settings, repositories, constraints, and Alembic migration foundation.

### Phase 3 — Monitoring

Check-Host client, Iran node discovery, TCP checks, normalized results, quorum health logic,
failure/recovery thresholds, persisted checks/events, duplicate-prevention lease, worker, and scheduler.

### Phase 4 — Providers

- provider-neutral adapter contract/factory
- Hetzner Cloud adapter
- Akamai Cloud/Linode v4 adapter
- provider error normalization
- deterministic provider selection policy
- crash-recovery-friendly split create / persist / wait provisioning lifecycle
- bounded readiness timeout and temporary-VPS-only cleanup
- replacement/temporary/concurrency cost guards
- explicit retry classification without unsafe blind create retries
- dry-run adapter using reserved TEST-NET addresses
- two-switch protection for real infrastructure mutations

### Phase 5 — Deployment

- AsyncSSH command adapter
- SSH readiness retry/timeout
- OS/architecture detection
- minimal remote bootstrap
- isolated 3X-UI unattended installer
- installation verification
- root-only install-result extraction
- runtime credential resolution from references
- token-authenticated node API verification
- deployment state machine
- conservative partial-install rollback
- dry-run deployment path with zero SSH calls

## Database migration

No schema change is introduced by Patch 03. Existing installations remain on:

```text
20260917_0001_registry_and_monitoring
```

Apply it if the Phase 2 database has not yet been initialized:

```bash
alembic upgrade head
```

## Validation

```bash
ruff check .
ruff format --check .
pytest
python scripts/validate_patch03.py
python -m compileall -q app tests scripts
alembic upgrade head --sql > migration.sql
```

## Docker development

```bash
cp .env.example .env
docker compose up --build
```

## Next milestone

Phase 6 will add the Master 3X-UI client and the persisted replacement orchestrator. That is where
provider creation, Check-Host acceptance, deployment, Master switch, final verification, crash
recovery/idempotency, and **only then** old-VPS deletion are connected into one workflow.
