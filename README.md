# ASO Node Recovery

Safety-first control plane for on-demand recovery of remote 3X-UI nodes whose public IPs become
unreachable from Iran.

> Current milestone: **Phase 2 — Registry Core / Patch 01**. Provider APIs, Check-Host, SSH,
> replacement orchestration, master mutation, and database connectivity are not implemented yet.

## Safety status

- `DRY_RUN=true` by default.
- No production VPS operation exists in this patch.
- No production master-panel mutation exists in this patch.
- Secrets are configuration values or secret references; registry models do not add plaintext secret
  columns.
- The permanent-spare-pool model is explicitly out of scope.
- The old VPS deletion workflow does not exist yet and therefore cannot run prematurely.

Read [PROJECT_SCOPE.md](PROJECT_SCOPE.md) for the authoritative scope and safety rules and
[docs/DATA_MODEL.md](docs/DATA_MODEL.md) for the Patch 01 registry design.

## Requirements

- Python 3.12+
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

Example response:

```json
{
  "status": "ok",
  "service": "aso-node-recovery",
  "version": "0.2.0-phase2-registry-core",
  "environment": "development",
  "dry_run": true
}
```

## Patch 01 contents

- deterministic SQLAlchemy metadata/naming conventions
- `Provider` model
- `Node` model
- explicit local node -> master node mapping
- `NodeCredential` secret-reference model
- node state enum and central `NodeStateMachine`
- registry/state-machine tests

No connection/session, migration, or repository code is included yet; those are part of Patch 02.

## Validation

```bash
ruff check .
ruff format --check .
pytest
python scripts/validate_patch01.py
```

## Docker development

```bash
cp .env.example .env
docker compose up --build
```

PostgreSQL is already available in Compose for development. Patch 01 defines metadata but does not
open database connections or mutate the schema.

## Repository layout

```text
app/
  api/          FastAPI routes
  bot/          reserved for Telegram (Phase 7)
  core/         configuration, logging, errors, safety primitives
  database/     SQLAlchemy metadata foundation
  models/       registry models and enums
  schemas/      API/domain schemas
  services/     domain/application services, including node state policy
  providers/    provider adapters (Phase 4)
  monitoring/   monitoring engine (Phase 3)
  deployment/   SSH/3X-UI deployment (Phase 5)
  workers/      background workers
migrations/     Alembic setup begins in Patch 02
scripts/        validation/maintenance scripts
tests/          automated tests
docs/           architecture and data-model documentation
```
