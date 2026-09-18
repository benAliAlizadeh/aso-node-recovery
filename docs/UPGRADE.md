# In-place upgrades

Use this workflow for an already-installed ASO host. Do not reinstall the stack for normal releases.

```bash
cd /opt/aso/aso-node-recovery
git config core.fileMode false
git pull --ff-only
./asoctl upgrade
```

`./asoctl upgrade` performs these stages in order:

1. validates Docker Compose and the existing `.env`;
2. starts/checks PostgreSQL without replacing its named volume;
3. creates a pre-upgrade PostgreSQL backup;
4. rebuilds Docker images from the newly pulled source;
5. applies `alembic upgrade head`;
6. recreates API/worker and the Telegram bot when enabled;
7. checks API health;
8. runs the production security review and the newest release validator;
9. prints final container status.

The command preserves the existing `.env`, PostgreSQL volume, runtime secret volume, backup volume,
Provider/Node registry and safety switches. It never runs `docker compose down -v`, `docker volume
prune`, a database reset, or the quick installer.

If a stage fails, the command stops with a non-zero exit code, prints the failed stage and recent
application logs, and explicitly leaves named volumes untouched. Docker image building happens while
existing application containers are still running; they are recreated only after the image builds and
database migration succeeds.

### Optional backup bypass

The backup is intentionally mandatory by default. For an exceptional case only:

```bash
./asoctl upgrade --skip-backup
```

This option does not weaken any VPS/Master safety switch.

### Git executable-bit noise

The installer makes launchers executable on Linux. `asoctl upgrade` configures this checkout with
`core.fileMode=false` so a chmod-only difference cannot block later `git pull` operations. Git still
protects actual file-content changes.
