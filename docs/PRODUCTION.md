# Production deployment

## 1. Prepare configuration

Copy `.env.example` to `.env`, use strong secrets, keep `ASO_DRY_RUN=true`, and leave
`ASO_ALLOW_REAL_INFRASTRUCTURE_MUTATION=false` for the initial production deployment.

Set a strong `POSTGRES_PASSWORD` and an URL-encoded `ASO_DATABASE_URL` pointing to the Compose PostgreSQL service. Configure provider secret references, Master 3X-UI, node registry, SSH host keys, and Telegram allow-list as required.

## 2. Build and migrate

```bash
docker compose -f docker-compose.prod.yml build
docker compose -f docker-compose.prod.yml up -d postgres
docker compose -f docker-compose.prod.yml run --rm api alembic upgrade head
```

Current migration head: `20260919_0005`.

## 3. Start safely

```bash
docker compose -f docker-compose.prod.yml up -d api worker
docker compose -f docker-compose.prod.yml --profile telegram up -d bot
```

The worker container keeps monitoring and replacement scheduler ticks registered. Persisted runtime controls decide whether each cycle performs work, so Telegram toggles do not require container recreation. Keep the replacement worker disabled during initial monitoring-only validation.

## 4. Validate

```bash
python scripts/security_review.py
python scripts/validate_patch14.py
```

Exercise Telegram `/status`, `/nodes`, `/check`, pause/resume, audit logs, database backup, and a
restore drill to an isolated database.

## 5. Real infrastructure authorization

A real replacement requires both:

```env
ASO_DRY_RUN=false
ASO_ALLOW_REAL_INFRASTRUCTURE_MUTATION=true
```

Changing these is an operational authorization decision, not a deployment default. Do not enable
them merely because version 1.0.0 is installed.

The production replacement E2E script has an additional explicit confirmation gate and node ID. It
must only be run for a specifically authorized production test.

## Operations

Backup:

```bash
docker compose -f docker-compose.prod.yml --profile ops run --rm backup
```

Logs are Docker `json-file` logs capped at 10 MB x 5 files per container. PostgreSQL data, runtime
secrets, and backups are separate named volumes.
