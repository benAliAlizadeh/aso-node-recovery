#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$PROJECT_ROOT/.env"
COMPOSE_FILE="$PROJECT_ROOT/docker-compose.prod.yml"
NON_INTERACTIVE=false
SKIP_DOCKER_INSTALL=false

for arg in "$@"; do
  case "$arg" in
    --non-interactive) NON_INTERACTIVE=true ;;
    --skip-docker-install) SKIP_DOCKER_INSTALL=true ;;
    -h|--help)
      cat <<'HELP'
ASO Node Recovery quick installer

Usage:
  sudo ./install.sh [--non-interactive] [--skip-docker-install]

Options:
  --non-interactive       Install with safe defaults and no Telegram/Master/provider secrets.
  --skip-docker-install   Require Docker + Compose to already be installed.

The installer NEVER enables real VPS/Master mutations. It always leaves:
  ASO_DRY_RUN=true
  ASO_ALLOW_REAL_INFRASTRUCTURE_MUTATION=false
  ASO_ALLOW_OLD_VPS_DELETION=false
  ASO_REPLACEMENT_WORKER_ENABLED=false
  ASO_WORKER_SCHEDULER_ENABLED=false
HELP
      exit 0
      ;;
    *)
      echo "Unknown argument: $arg" >&2
      exit 2
      ;;
  esac
done

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  if command -v sudo >/dev/null 2>&1; then
    exec sudo -E bash "$0" "$@"
  fi
  echo "This installer needs root privileges. Re-run as root." >&2
  exit 1
fi

log() { printf '\n[ASO] %s\n' "$*"; }
warn() { printf '\n[ASO][WARN] %s\n' "$*" >&2; }
die() { printf '\n[ASO][ERROR] %s\n' "$*" >&2; exit 1; }

read_os() {
  [[ -r /etc/os-release ]] || die "/etc/os-release not found"
  # shellcheck disable=SC1091
  . /etc/os-release
  OS_ID="${ID:-}"
  OS_CODENAME="${VERSION_CODENAME:-${UBUNTU_CODENAME:-}}"
  case "$OS_ID" in
    ubuntu|debian) ;;
    *) die "Automatic Docker installation supports Ubuntu/Debian only (detected: ${OS_ID:-unknown}). Install Docker manually, then rerun with --skip-docker-install." ;;
  esac
  [[ -n "$OS_CODENAME" ]] || die "Could not determine distribution codename"
}

have_docker() {
  command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1
}

install_docker() {
  if have_docker; then
    log "Docker Engine and Compose plugin already available."
    return
  fi
  if [[ "$SKIP_DOCKER_INSTALL" == true ]]; then
    die "Docker Engine + Compose plugin are required but not available."
  fi

  read_os
  log "Installing Docker Engine from Docker's official apt repository for $OS_ID/$OS_CODENAME."

  local conflicts=(docker.io docker-compose docker-compose-v2 docker-doc podman-docker containerd runc)
  local found=()
  local pkg
  for pkg in "${conflicts[@]}"; do
    if dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q 'install ok installed'; then
      found+=("$pkg")
    fi
  done
  if ((${#found[@]} > 0)); then
    die "Conflicting container packages detected: ${found[*]}. Remove/reconcile them manually first; the quick installer will not uninstall existing software automatically."
  fi

  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y ca-certificates curl openssl
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL "https://download.docker.com/linux/$OS_ID/gpg" -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc

  cat > /etc/apt/sources.list.d/docker.sources <<APT
Types: deb
URIs: https://download.docker.com/linux/$OS_ID
Suites: $OS_CODENAME
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
APT

  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y \
    docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  systemctl enable --now docker
  have_docker || die "Docker installation completed but 'docker compose' is not usable"
}

set_env() {
  local key="$1"
  local value="$2"
  local tmp
  tmp="$(mktemp)"
  if grep -qE "^${key}=" "$ENV_FILE"; then
    awk -v key="$key" -v value="$value" '
      index($0, key "=") == 1 { print key "=" value; next }
      { print }
    ' "$ENV_FILE" > "$tmp"
  else
    cat "$ENV_FILE" > "$tmp"
    printf '%s=%s\n' "$key" "$value" >> "$tmp"
  fi
  cat "$tmp" > "$ENV_FILE"
  rm -f "$tmp"
}

get_env() {
  local key="$1"
  awk -v key="$key" '
    index($0, key "=") == 1 { sub("^[^=]*=", ""); print; exit }
  ' "$ENV_FILE"
}

is_blank() {
  [[ -z "${1//[[:space:]]/}" ]]
}

prompt_yes_no() {
  local prompt="$1"
  local answer
  if [[ "$NON_INTERACTIVE" == true ]]; then
    return 1
  fi
  read -r -p "$prompt [y/N]: " answer
  [[ "$answer" =~ ^[Yy]$ ]]
}

prompt_secret() {
  local prompt="$1"
  local value
  read -r -s -p "$prompt: " value
  printf '\n' >&2
  printf '%s' "$value"
}

configure_env() {
  log "Preparing production .env with safe defaults."
  if [[ -f "$ENV_FILE" ]]; then
    cp -a "$ENV_FILE" "$ENV_FILE.backup.$(date +%Y%m%d-%H%M%S)"
    log "Existing .env preserved and backed up."
  else
    cp "$PROJECT_ROOT/.env.example" "$ENV_FILE"
  fi

  chmod 600 "$ENV_FILE"

  local pg_password
  pg_password="$(get_env POSTGRES_PASSWORD)"
  if is_blank "$pg_password"; then
    pg_password="$(openssl rand -hex 24)"
  fi

  local callback_secret
  callback_secret="$(get_env ASO_TELEGRAM_CALLBACK_SECRET)"
  if is_blank "$callback_secret"; then
    callback_secret="$(openssl rand -hex 32)"
  fi

  set_env ASO_ENVIRONMENT production
  set_env POSTGRES_DB aso
  set_env POSTGRES_USER aso
  set_env POSTGRES_PASSWORD "$pg_password"
  set_env ASO_DATABASE_URL "postgresql+asyncpg://aso:${pg_password}@postgres:5432/aso"
  set_env ASO_TELEGRAM_CALLBACK_SECRET "$callback_secret"

  # Hard safety defaults. The quick installer intentionally has no switch that turns these on.
  set_env ASO_DRY_RUN true
  set_env ASO_ALLOW_REAL_INFRASTRUCTURE_MUTATION false
  set_env ASO_ALLOW_OLD_VPS_DELETION false
  set_env ASO_OLD_VPS_DELETE_CONFIRMATION ""
  set_env ASO_REPLACEMENT_WORKER_ENABLED false
  set_env ASO_WORKER_SCHEDULER_ENABLED false
  set_env ASO_MONITORING_SCHEDULER_ENABLED false
  set_env ASO_REPLACEMENT_EMERGENCY_STOP true
  set_env ASO_ALLOW_DATABASE_RESTORE false

  if prompt_yes_no "Configure Telegram bot now?"; then
    local tg_token tg_ids tg_chat
    tg_token="$(prompt_secret 'Telegram bot token')"
    read -r -p "Authorized Telegram user IDs (comma-separated numbers): " tg_ids
    tg_ids="${tg_ids// /}"
    [[ "$tg_ids" =~ ^[0-9]+(,[0-9]+)*$ ]] || die "Telegram user IDs must be comma-separated integers"
    read -r -p "Notification chat ID (optional; Enter to skip): " tg_chat
    if [[ -n "$tg_chat" && ! "$tg_chat" =~ ^-?[0-9]+$ ]]; then
      die "Telegram notification chat ID must be an integer"
    fi
    set_env ASO_TELEGRAM_BOT_TOKEN "$tg_token"
    set_env ASO_TELEGRAM_AUTHORIZED_USER_IDS "[$tg_ids]"
    set_env ASO_TELEGRAM_NOTIFICATION_CHAT_ID "$tg_chat"
    set_env ASO_TELEGRAM_BOT_ENABLED true
  else
    set_env ASO_TELEGRAM_BOT_ENABLED false
  fi

  if prompt_yes_no "Configure Master 3X-UI connection now?"; then
    local master_url master_token master_username master_password
    read -r -p "Master 3X-UI base URL (https://...): " master_url
    master_token="$(prompt_secret 'Master 3X-UI API token (preferred; Enter for username/password fallback)')"
    set_env ASO_MASTER_3XUI_BASE_URL "$master_url"
    if [[ -n "$master_token" ]]; then
      set_env ASO_MASTER_3XUI_API_TOKEN "$master_token"
    else
      read -r -p "Master 3X-UI username: " master_username
      master_password="$(prompt_secret 'Master 3X-UI password')"
      set_env ASO_MASTER_3XUI_USERNAME "$master_username"
      set_env ASO_MASTER_3XUI_PASSWORD "$master_password"
    fi
  fi

  if prompt_yes_no "Configure provider API tokens now?"; then
    local hetzner_token linode_token
    hetzner_token="$(prompt_secret 'Hetzner API token (Enter to skip)')"
    linode_token="$(prompt_secret 'Linode API token (Enter to skip)')"
    [[ -z "$hetzner_token" ]] || set_env ASO_HETZNER_API_TOKEN "$hetzner_token"
    [[ -z "$linode_token" ]] || set_env ASO_LINODE_API_TOKEN "$linode_token"
  fi

  chmod 600 "$ENV_FILE"
}

compose() {
  # Compose gives exported host variables precedence over --env-file values.
  # Strip the database credential variables so the installer's protected .env
  # is the single source of truth even when invoked through `sudo -E`.
  env \
    -u POSTGRES_DB \
    -u POSTGRES_USER \
    -u POSTGRES_PASSWORD \
    -u ASO_DATABASE_URL \
    docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

wait_for_postgres() {
  local pg_user pg_db i
  pg_user="$(get_env POSTGRES_USER)"
  pg_db="$(get_env POSTGRES_DB)"

  for i in $(seq 1 60); do
    if compose exec -T postgres pg_isready -U "$pg_user" -d "$pg_db" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done

  compose logs --tail=100 postgres || true
  die "PostgreSQL did not become ready"
}

postgres_password_matches_env() {
  compose exec -T postgres sh -ec '
    PGPASSWORD="$POSTGRES_PASSWORD" \
      psql -X -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
      -v ON_ERROR_STOP=1 -Atqc "SELECT 1"
  ' 2>/dev/null | grep -qx '1'
}

reconcile_postgres_password() {
  local pg_user pg_db
  pg_user="$(get_env POSTGRES_USER)"
  pg_db="$(get_env POSTGRES_DB)"

  [[ "$pg_user" == "aso" && "$pg_db" == "aso" ]] || \
    die "Quick installer expects POSTGRES_USER=aso and POSTGRES_DB=aso"

  if postgres_password_matches_env; then
    log "PostgreSQL application credentials verified."
    return 0
  fi

  warn "PostgreSQL volume password differs from the protected .env; synchronizing the ASO role password without deleting data."

  # The official PostgreSQL image uses local socket trust for the initialized
  # cluster. Read the target password from the container's own environment via
  # psql \getenv, so the secret is never placed in SQL text or process args.
  if ! printf '%s\n' \
      '\getenv aso_target_password POSTGRES_PASSWORD' \
      "SELECT format('ALTER ROLE %I WITH PASSWORD %L', current_user, :'aso_target_password') \gexec" \
      | compose exec -T -u postgres postgres \
          psql -X -v ON_ERROR_STOP=1 -U "$pg_user" -d "$pg_db" >/dev/null; then
    die "Could not synchronize PostgreSQL credentials. The database volume was NOT deleted."
  fi

  if ! postgres_password_matches_env; then
    die "PostgreSQL credential verification still failed after synchronization. The database volume was NOT deleted."
  fi

  log "PostgreSQL application credentials synchronized and verified."
}

wait_for_health() {
  local port
  port="$(get_env ASO_PORT)"
  [[ -n "$port" ]] || port=8000
  local url="http://127.0.0.1:${port}/health"
  local i
  for i in $(seq 1 30); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      log "API health check passed: $url"
      return 0
    fi
    sleep 2
  done
  compose ps
  compose logs --tail=100 api || true
  die "API did not become healthy at $url"
}

install_stack() {
  log "Validating Docker Compose configuration."
  compose config >/dev/null

  log "Building ASO application image."
  compose build

  log "Starting PostgreSQL."
  compose up -d postgres
  wait_for_postgres
  reconcile_postgres_password

  log "Securing persistent runtime secret and backup volumes."
  compose run --rm --no-deps runtime-init

  log "Applying Alembic migrations."
  compose run --rm api alembic upgrade head

  log "Running production security review before startup."
  compose run --rm api python scripts/security_review.py

  log "Starting API and worker (worker scheduler remains disabled by default)."
  compose up -d api worker

  if [[ "$(get_env ASO_TELEGRAM_BOT_ENABLED)" == "true" ]]; then
    log "Starting Telegram bot profile."
    compose --profile telegram up -d bot
  fi

  wait_for_health
}

print_summary() {
  cat <<SUMMARY

============================================================
ASO Node Recovery quick installation completed.
Version: $(cat "$PROJECT_ROOT/VERSION")
Project: $PROJECT_ROOT
Config:  $ENV_FILE

SAFETY STATUS (intentionally locked by installer):
  ASO_DRY_RUN=true
  ASO_ALLOW_REAL_INFRASTRUCTURE_MUTATION=false
  ASO_ALLOW_OLD_VPS_DELETION=false
  ASO_REPLACEMENT_WORKER_ENABLED=false
  ASO_WORKER_SCHEDULER_ENABLED=false
  ASO_ALLOW_DATABASE_RESTORE=false

Useful commands:
  ./asoctl status
  ./asoctl health
  ./asoctl logs
  ./asoctl backup
  ./asoctl migrate
  ./asoctl validate

Next operational work:
  1. Add real provider/node/Master/SSH configuration.
  2. Validate monitoring in DRY_RUN.
  3. Run a backup + isolated restore drill.
  4. Authorize a specific real E2E test before changing any real-mutation safety flags.

Do NOT enable real infrastructure mutation merely because installation succeeded.
============================================================
SUMMARY
}

main() {
  cd "$PROJECT_ROOT"
  [[ -f "$PROJECT_ROOT/VERSION" && -f "$COMPOSE_FILE" ]] || die "Run this installer from the ASO Node Recovery source tree"
  install_docker
  command -v openssl >/dev/null 2>&1 || die "openssl is required"
  command -v curl >/dev/null 2>&1 || die "curl is required"
  configure_env
  install_stack
  print_summary
}

main "$@"
