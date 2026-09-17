# ASO Node Recovery

Safety-first control plane for on-demand recovery of remote 3X-UI nodes whose public IPs become
unreachable from Iran.

> Current milestone: **Phase 1 — Foundation**. No provider, Check-Host, SSH, master 3X-UI, or
> database business logic is implemented yet.

## Safety status

- `DRY_RUN=true` by default.
- No production VPS operation exists in Phase 1.
- No production master-panel mutation exists in Phase 1.
- Secrets are configuration values and are redacted from structured logs.
- The permanent-spare-pool model is explicitly out of scope.

Read [PROJECT_SCOPE.md](PROJECT_SCOPE.md) for the authoritative scope and safety rules.

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
  "version": "0.1.0-phase1-foundation",
  "environment": "development",
  "dry_run": true
}
```

## Validation

```bash
ruff check .
ruff format --check .
pytest
python scripts/validate_phase1.py
```

## Docker development

```bash
cp .env.example .env
docker compose up --build
```

The Compose file includes PostgreSQL because it is part of the required project platform, but Phase 1
application code deliberately does not connect to or model the database. Database implementation begins
in Phase 2.

## Repository layout

```text
app/
  api/          FastAPI routes
  bot/          reserved for Telegram (Phase 7)
  core/         configuration, logging, errors, safety primitives
  database/     reserved for persistence implementation (Phase 2)
  models/       reserved for domain/database models (Phase 2)
  schemas/      API/domain schemas
  services/     application services
  providers/    provider adapters (Phase 4)
  monitoring/   monitoring engine (Phase 3)
  deployment/   SSH/3X-UI deployment (Phase 5)
  workers/      background workers
migrations/     Alembic migrations from Phase 2
scripts/        validation/maintenance scripts
tests/          automated tests
docs/           development documentation
```
