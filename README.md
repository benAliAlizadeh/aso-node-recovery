# ASO Node Recovery

Safety-first control plane for on-demand recovery of remote 3X-UI nodes whose public IPs become
unreachable from Iran.

> Current milestone: **Phase 6 Master + Replacement / Patch 04**.
> Phases 1-6 are implemented. Telegram control and production hardening remain Phase 7.

## Safety status

- `ASO_DRY_RUN=true` remains the default.
- `ASO_ALLOW_REAL_INFRASTRUCTURE_MUTATION=false` remains the independent real-mutation guard.
- `ASO_REPLACEMENT_WORKER_ENABLED=false` keeps automatic replacement opt-in.
- `ASO_REPLACEMENT_EMERGENCY_STOP=false` can be switched on to defer workflow mutations.
- Provider create is reconciled by deterministic name before retrying an ambiguous request.
- Check-Host `INDETERMINATE` is never treated as a bad replacement IP.
- Generated 3X-UI secrets are persisted as owner-only file references, not plaintext DB columns.
- The existing Master node is updated by explicit `master_node_id`; IP is never used as identity.
- The old VPS deletion path is hard-gated by durable IP/deployment/master/final-check evidence.
- DRY_RUN never marks a real old VPS deleted or promotes a simulated replacement.
- Permanent spare VPS/IP pools are explicitly out of scope.

Read [PROJECT_SCOPE.md](PROJECT_SCOPE.md), [docs/REPLACEMENT.md](docs/REPLACEMENT.md),
[docs/MASTER_3XUI.md](docs/MASTER_3XUI.md), [docs/PROVIDERS.md](docs/PROVIDERS.md),
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

Health endpoint: `GET /health`

Current version:

```text
0.6.0-master-replacement
```

## Implemented phases

- **Phase 1:** application/config/logging/testing/Docker foundation.
- **Phase 2:** PostgreSQL registry, models, constraints, repositories, Alembic.
- **Phase 3:** Iran-scoped Check-Host monitoring, thresholds, leases, events, scheduler adapter.
- **Phase 4:** provider-neutral provisioning, Hetzner/Linode adapters, cost guards, DRY_RUN.
- **Phase 5:** AsyncSSH, bootstrap, isolated 3X-UI installer, verification, resumable deployment.
- **Phase 6:** current 3X-UI master adapter, durable replacement checkpoints, provider reconciliation,
  bounded bad-IP retry, master rollback, job/global locks, emergency stop, crash recovery, and hard
  old-VPS protection.

## Database migration

Patch 04 adds a second migration for replacement/master persistence:

```bash
alembic upgrade head
```

Current head: `20260917_0002`.

## Validation

```bash
ruff check .
ruff format --check .
pytest
python scripts/validate_patch04.py
python -m compileall -q app tests scripts migrations
alembic upgrade head --sql > migration.sql
```

## Production boundary

Phase 7 still owns Telegram administration, production scheduler wiring, backup/restore drills,
container hardening/resource limits, security review, production E2E authorization, and release.
No real production replacement should be enabled merely because Patch 04 is present.
