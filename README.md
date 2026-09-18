# ASO Node Recovery

Production-oriented, safety-first controller that replaces remote 3X-UI nodes on demand when their
public IP becomes unreachable from Iran.

Current release: **1.0.7-health-readiness-hotfix** — all seven planned phases are implemented, with a safety-first production quick installer.

## Core replacement invariant

There is no permanent spare VPS/IP pool. A replacement VPS is created only after a node reaches the
configured failure threshold. The old VPS stays alive until the replacement has passed:

1. provider provisioning,
2. Iran reachability check,
3. SSH readiness,
4. 3X-UI install/config extraction,
5. node API verification,
6. Master 3X-UI update,
7. Master verification,
8. final Iran health check.

Only then may the old VPS be deleted.

## Implemented architecture

- FastAPI health/control process
- PostgreSQL + SQLAlchemy 2 + Alembic
- Check-Host monitoring from Iran nodes
- central Node state machine and persisted replacement state machine
- Hetzner and Linode provider adapters
- DRY_RUN + independent real-mutation guard + capacity/cost guards
- AsyncSSH deployment and isolated 3X-UI installer
- current 3X-UI Master API integration
- crash recovery, deterministic provider reconciliation, DB leases and advisory lock
- Telegram control plane with allow-list and signed destructive confirmations
- persistent pause/resume
- audit/event notifications
- PostgreSQL backup/restore tooling
- hardened production Docker Compose
- separated explicitly-authorized production replacement E2E test

## Safety defaults

```env
ASO_DRY_RUN=true
ASO_ALLOW_REAL_INFRASTRUCTURE_MUTATION=false
ASO_ALLOW_OLD_VPS_DELETION=false
ASO_REPLACEMENT_EMERGENCY_STOP=true
ASO_REPLACEMENT_WORKER_ENABLED=false
ASO_WORKER_SCHEDULER_ENABLED=false
ASO_TELEGRAM_BOT_ENABLED=false
ASO_ALLOW_DATABASE_RESTORE=false
```

Installing the release does **not** authorize real VPS creation/deletion or Master mutation.

## Development

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
cp .env.example .env

pytest
ruff check .
ruff format --check .
python scripts/validate_patch11.py
python -m compileall -q app tests scripts migrations
alembic upgrade head --sql > migration.sql
```

Development API:

```bash
uvicorn app.main:app --reload
```

Health endpoint: `GET /health`.

## Database

Apply all migrations before starting worker/bot processes:

```bash
alembic upgrade head
```

Current Alembic head: `20260917_0003`.

## Quick installation

For a fresh Ubuntu/Debian production host, the simplest safe bootstrap is:

```bash
chmod +x install.sh asoctl scripts/*.sh
sudo ./install.sh
```

The installer provisions Docker/Compose when required, creates a protected `.env`, generates local
secrets, starts PostgreSQL, applies migrations, runs the security review, starts the safe production
stack, and verifies `/health`. It **always** leaves real infrastructure mutation and replacement workers
disabled. See [Quick installation](docs/QUICK_INSTALL.md).

## Operational onboarding

A fresh installation intentionally starts with an empty provider/node registry. Register the existing infrastructure before expecting Telegram `/nodes` or `/providers` to show anything:

```bash
./asoctl setup
./asoctl registry
./asoctl telegram-check
```

Then open the bot and send `/start`. See [Operational onboarding](docs/ONBOARDING.md).

## Production

See:

- [Operational onboarding](docs/ONBOARDING.md)
- [Production deployment](docs/PRODUCTION.md)
- [Telegram control](docs/TELEGRAM.md)
- [Backup/restore](docs/BACKUP_RESTORE.md)
- [Security controls](docs/SECURITY.md)
- [Release checklist](docs/RELEASE.md)
- [Replacement workflow](docs/REPLACEMENT.md)
- [Master 3X-UI](docs/MASTER_3XUI.md)

Start the hardened stack only after `.env` is populated:

```bash
docker compose -f docker-compose.prod.yml up -d postgres
docker compose -f docker-compose.prod.yml run --rm api alembic upgrade head
docker compose -f docker-compose.prod.yml up -d api worker
docker compose -f docker-compose.prod.yml --profile telegram up -d bot
```

Keep real-infrastructure guards disabled through initial monitoring, Telegram, backup, restore-drill,
and DRY_RUN verification.
