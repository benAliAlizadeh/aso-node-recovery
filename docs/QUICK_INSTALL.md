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

## Existing PostgreSQL volume credentials

The installer treats the protected `.env` as the source of truth for the ASO PostgreSQL password.
Before Alembic runs, it performs a real authenticated TCP connection check. If an existing ASO named
volume was initialized with an older password, the installer updates only the `aso` database role
password through the container-local PostgreSQL socket and verifies the new credential. It never
deletes or recreates the PostgreSQL volume to repair a password mismatch. Exported host database
variables are also ignored during Compose calls so `sudo -E` cannot silently override `.env`.


## First operational use

After installation completes, register the existing infrastructure before using the bot:

```bash
./asoctl setup
./asoctl registry
./asoctl telegram-check
```

Then send `/start` to the authorized Telegram bot. Real mutation remains disabled.


## Same-server Master firewall guard

When ASO runs in Docker on the same Linux host as the central 3X-UI panel, host firewall policy may
block Docker bridge addresses even while the 3X-UI port is public and reachable from the Internet.
The installer detects this case only when the Master connection mode is `auto`/`local-host` and the
configured Master hostname resolves to this server. It discovers the API container's actual Docker
network, subnet, and bridge, then verifies `host.docker.internal:<master-port>`.

If the path is blocked and UFW is active, the installer inserts one highest-priority rule limited to:

```text
<ASO Docker subnet> on <ASO Docker bridge> -> this host TCP/<Master port>
```

It does not remove existing rules, does not open the port globally, and does not change any firewall
for a remote Master. The check is idempotent. If another firewall chain still blocks the path, the
installer prints a warning instead of weakening unrelated firewall policy. Re-run the focused guard with:

```bash
sudo ./asoctl master-network-check
```

## Same-server 3X-UI Master firewall guard

If the configured Master resolves to the ASO host, the installer checks Docker-to-host connectivity. With active UFW, it may insert one high-priority allow rule limited to the actual ASO Docker bridge/subnet and the Master TCP port. It does not remove firewall rules or make the Master port globally accessible. Remote Masters are never changed by this guard.

## SSH host identity during onboarding

SSH host-key verification is configurable. For ephemeral replacement VPS instances it is disabled by default, so recycled provider IPs with a new host key do not block onboarding or recovery. Set `ASO_SSH_VERIFY_HOST_KEY=true` to enable strict fingerprint confirmation and the managed `known_hosts` trust store.
