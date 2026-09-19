# ASO Node Recovery

Production-oriented, safety-first controller that replaces remote 3X-UI nodes on demand when their
public IP becomes unreachable from Iran.

Current release: **1.5.5-upgrade-validator-ssh-trust** — in-place validation fix plus resilient SSH host-key trust onboarding.

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
- Telegram control plane with allow-list, inline Node/Provider management, validated secret rotation, and signed destructive confirmations
- persistent pause/resume
- signed/idempotent Force Repair that bypasses only the initial FAILED-state admission check
- audit/event notifications
- PostgreSQL backup/restore tooling
- hardened production Docker Compose
- separated explicitly-authorized production replacement E2E test

## Runtime monitoring and repair controls

Authorized Telegram operators can manage runtime behavior without rebuilding containers:

- each node: `DISABLED`, `MONITOR ONLY`, or `AUTO REPAIR`,
- global monitoring on/off,
- global automatic-repair worker on/off,
- runtime `DRY RUN` / `LIVE` selection.

Telegram controls can only make the process as permissive as the host allows. `LIVE` is refused unless
server-side DRY_RUN, mutation, and emergency-stop gates already permit real infrastructure changes.
Automatic repair only considers nodes explicitly set to `AUTO REPAIR`; `MONITOR ONLY` never triggers
automatic replacement. Old-VPS deletion remains independently protected.

Force Repair is available from the node Telegram UI or `/force <id|name>`. It does not skip new-IP,
SSH/3X-UI, Master, final-health, concurrency, or old-VPS deletion safety gates. See
[Force Repair](docs/FORCE_REPAIR.md).

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
python scripts/validate_patch17.py
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

Current Alembic head: `20260919_0006`.

## Quick installation

For a fresh Ubuntu/Debian production host, the simplest safe bootstrap is:

```bash
chmod +x install.sh asoctl scripts/*.sh
sudo ./install.sh
```

The installer provisions Docker/Compose when required, creates a protected `.env`, generates local
secrets, starts PostgreSQL, applies migrations, runs the security review, starts the safe production
stack, and verifies `/health`. It **always** leaves real infrastructure mutation and replacement workers
disabled. For a same-server 3X-UI Master, the installer also checks Docker-to-host connectivity and, only when UFW is active and the configured Master resolves to this host, inserts a narrow source-subnet/bridge/port rule before verifying the connection. Remote Master firewall policy is never modified. See [Quick installation](docs/QUICK_INSTALL.md).

## Operational onboarding

A fresh installation intentionally starts with an empty provider/node registry. Register the existing infrastructure before expecting Telegram `/nodes` or `/providers` to show anything:

```bash
./asoctl setup
./asoctl registry
./asoctl telegram-check
```

Then open the bot and send `/start`. See [Operational onboarding](docs/ONBOARDING.md).

## Smart onboarding

After installation, register existing infrastructure with read-only discovery:

```bash
./asoctl setup
```

Provider region/type/image and Node host/port/basePath are discovered from the provider API and
Master 3X-UI rather than typed manually. Provider access, Master probe, and the current Node API
token are validated before registry persistence. See [Smart onboarding](docs/SMART_ONBOARDING.md).

## Telegram registry management

The same smart onboarding is available from Telegram `/start` → **Nodes** / **Providers**. Operators
can add, inspect, test, rename, rotate provider/Node API credentials, rotate SSH credentials and
remove local ASO registry records through inline buttons. Provider/Master/VPS discovery and access
validation run before persistence. Registry removal never deletes provider infrastructure and never
modifies the Master node.

## In-place upgrades

Once ASO is installed, do **not** rerun the installer for routine releases. Update the checkout and let
`asoctl` rebuild the Docker image, migrate the existing database, recreate the application containers,
and validate the new release while preserving `.env` and every named volume:

```bash
git config core.fileMode false
git pull --ff-only
./asoctl upgrade
```

A pre-upgrade PostgreSQL backup is created by default. Use `--skip-backup` only when you intentionally
accept proceeding without that backup. The upgrade command never runs `down -v`, prunes volumes,
resets PostgreSQL, regenerates `.env`, or enables destructive VPS/Master operations. See
[In-place upgrades](docs/UPGRADE.md).


### Same-host Master and SSH trust

When ASO and the central 3X-UI panel share one server, the installer/upgrade path detects the actual ASO Docker subnet and may add only a narrow UFW allow rule from that subnet to the configured Master TCP port. Remote-Master deployments are left untouched.

Node onboarding keeps strict SSH host-key verification enabled. Before ASO accepts SSH credentials for an existing node, it fetches the server host key without authenticating, shows the SHA256 fingerprint, requires explicit operator confirmation, re-fetches the key to detect races/changes, and only then stores the exact host/port key in the persistent runtime trust store.

## Production

See:

- [Operational onboarding](docs/ONBOARDING.md)
- [Production deployment](docs/PRODUCTION.md)
- [Telegram control](docs/TELEGRAM.md)
- [API health diagnostics](docs/API_HEALTH.md)
- [Backup/restore](docs/BACKUP_RESTORE.md)
- [Security controls](docs/SECURITY.md)
- [Release checklist](docs/RELEASE.md)
- [Replacement workflow](docs/REPLACEMENT.md)
- [Force Repair](docs/FORCE_REPAIR.md)
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

### In-place validation and SSH trust

`./asoctl upgrade` validates the checked-out source through a read-only bind mount, so production images remain lean and do not need `tests/` copied into `/app`. If an SSH credential check encounters an untrusted host key, Telegram shows the observed SHA256 fingerprint and requires explicit confirmation before retrying with strict host-key verification still enabled.

### SSH host-key confirmation hardening

ASO now enforces explicitly confirmed SSH SHA256 host-key fingerprints directly at runtime. The
managed `known_hosts` file remains persistent, but SSH command execution pins the presented key to
that confirmed fingerprint instead of depending on ambient host matching behavior. Unknown or
changed keys still require an explicit Telegram/CLI confirmation and are never auto-accepted.
