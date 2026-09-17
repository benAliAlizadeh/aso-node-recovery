# ASO Node Recovery

Safety-first control plane for on-demand recovery of remote 3X-UI nodes whose public IPs become
unreachable from Iran.

> Current milestone: **Phase 2 complete + Phase 3 monitoring / Patch 02**.
> Provider provisioning, SSH/3X-UI deployment, master mutation, and replacement orchestration remain
> intentionally deferred.

## Safety status

- `DRY_RUN=true` remains the default.
- No provider create/delete implementation exists yet.
- No SSH or 3X-UI installation implementation exists yet.
- No master 3X-UI mutation implementation exists yet.
- Monitoring can mark a node failed, but it cannot provision or delete infrastructure in this patch.
- Check-Host errors, pending results, and malformed/insufficient responses do **not** count as target
  failures.
- Permanent spare VPS/IP pools remain explicitly out of scope.
- Old VPS deletion is still impossible because cleanup/orchestration is not implemented.

Read [PROJECT_SCOPE.md](PROJECT_SCOPE.md), [docs/DATA_MODEL.md](docs/DATA_MODEL.md), and
[docs/MONITORING.md](docs/MONITORING.md).

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
0.3.0-registry-monitoring
```

## Patch 02 contents

### Phase 2 completion

- async SQLAlchemy engine/session foundation
- `NodeCheck`, `VpsInstance`, `ReplacementJob`, `Deployment`, `Event`, and `SystemSetting`
- explicit persisted old/new VPS references on replacement jobs
- one-active-replacement-per-node database constraint
- per-node monitoring lease fields for duplicate prevention
- repository layer
- Alembic configuration and initial schema migration
- PostgreSQL DDL validation

### Phase 3 monitoring

- dedicated `CheckHostClient`
- current documented TCP request/result formats
- Check-Host node discovery filtered by country code (`ir` by default)
- normalized TCP probe results
- quorum-based reachability evaluation
- configurable failure/recovery thresholds
- debounced node state changes
- failure/degraded/recovery events
- persisted node checks
- database-backed monitoring lease
- monitoring worker
- APScheduler adapter with `max_instances=1`

The monitoring scheduler adapter is implemented but is **not automatically started** by FastAPI in
this milestone. This prevents an API startup from unexpectedly generating external monitoring traffic.
Production wiring is enabled deliberately in later hardening work.

## Database migration

```bash
alembic upgrade head
```

Offline SQL inspection (does not connect to PostgreSQL):

```bash
alembic upgrade head --sql
```

## Validation

```bash
ruff check .
ruff format --check .
pytest
python scripts/validate_patch02.py
alembic upgrade head --sql > migration.sql
```

## Docker development

```bash
cp .env.example .env
docker compose up --build
```

## Repository layout

```text
app/
  api/          FastAPI routes
  bot/          reserved for Telegram (Phase 7)
  core/         configuration, logging, errors, safety settings
  database/     SQLAlchemy metadata, async sessions, repositories
  models/       registry/audit/job persistence models
  schemas/      API/domain schemas
  services/     domain/application services
  providers/    provider adapters (Phase 4)
  monitoring/   Check-Host adapter, health policy, scheduler
  deployment/   SSH/3X-UI deployment (Phase 5)
  workers/      monitoring/background workers
migrations/     Alembic configuration and revisions
scripts/        validation/maintenance scripts
tests/          automated tests
docs/           architecture/data-model/monitoring documentation
```
