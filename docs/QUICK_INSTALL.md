# Quick installation

The production release includes a safety-first installer intended for a fresh Ubuntu or Debian host.
It automates Docker/Compose installation when needed, `.env` bootstrap, image build, PostgreSQL startup,
Alembic migration, production security review, application startup, and the local `/health` check.

## Fast path

Unpack the ASO Node Recovery release, enter the project directory, and run:

```bash
chmod +x install.sh asoctl scripts/*.sh
sudo ./install.sh
```

The installer is interactive and can optionally collect Telegram, Master 3X-UI, Hetzner, and Linode
credentials. Press Enter / answer `N` to defer any optional integration.

For a completely unattended **safe** bootstrap:

```bash
sudo ./install.sh --non-interactive
```

This starts the local production stack but does not configure real external credentials.

## Safety guarantees

The quick installer deliberately forces these values and offers no installer flag to override them:

```env
ASO_DRY_RUN=true
ASO_ALLOW_REAL_INFRASTRUCTURE_MUTATION=false
ASO_REPLACEMENT_WORKER_ENABLED=false
ASO_WORKER_SCHEDULER_ENABLED=false
ASO_MONITORING_SCHEDULER_ENABLED=false
ASO_ALLOW_DATABASE_RESTORE=false
```

Successful installation is therefore **not** authorization to create/delete VPSs or update the Master
3X-UI panel.

If `.env` already exists, the installer makes a timestamped backup before modifying it. It does not
uninstall existing Docker/container packages. If conflicting packages are detected while Docker is
missing, installation stops and asks the operator to reconcile them manually.

## Docker behavior

If Docker Engine and the Compose plugin are already available, they are reused. Otherwise, on supported
Ubuntu/Debian hosts, Docker is installed from Docker's official apt repository. Use
`--skip-docker-install` to require a preinstalled Docker environment.

## Day-to-day helper

After installation:

```bash
./asoctl status
./asoctl health
./asoctl logs
./asoctl safety
./asoctl backup
./asoctl migrate
./asoctl validate
```

`./asoctl stop` uses normal Compose shutdown and never adds `-v`, so named PostgreSQL/secrets/backup
volumes are preserved.

## After quick installation

The software is installed, but production onboarding still requires operator-owned data:

1. register the real providers and nodes,
2. configure Master 3X-UI and SSH credentials/host keys,
3. validate Iran monitoring while still in DRY_RUN,
4. test Telegram controls if enabled,
5. take a backup and perform an isolated restore drill,
6. explicitly authorize one production replacement E2E test.

Only after that controlled process should real-infrastructure mutation be considered.


## Runtime volume permissions

The installer initializes the persistent runtime secret and backup Docker volumes with owner-only
permissions before migrations or the production security review run. This prevents Docker's default
named-volume root directory permissions from blocking startup or exposing runtime secret metadata.
The application services never run this initialization as an unrestricted long-lived root process.
