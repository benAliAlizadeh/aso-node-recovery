#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$PROJECT_ROOT/.env"
COMPOSE_FILE="$PROJECT_ROOT/docker-compose.prod.yml"

[[ -f "$ENV_FILE" ]] || { echo "Missing $ENV_FILE. Run ./install.sh first." >&2; exit 1; }

compose() {
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

get_env() {
  local key="$1"
  awk -v key="$key" 'index($0, key "=") == 1 { sub("^[^=]*=", ""); print; exit }' "$ENV_FILE"
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
  chmod 600 "$ENV_FILE"
}

prompt_default() {
  local prompt="$1"
  local default="$2"
  local value
  read -r -p "$prompt [$default]: " value
  printf '%s' "${value:-$default}"
}

prompt_required() {
  local prompt="$1"
  local value
  while true; do
    read -r -p "$prompt: " value
    if [[ -n "${value//[[:space:]]/}" ]]; then
      printf '%s' "$value"
      return
    fi
    echo "Value is required." >&2
  done
}

prompt_yes_no() {
  local prompt="$1"
  local default="${2:-N}"
  local suffix="[y/N]"
  [[ "$default" == "Y" ]] && suffix="[Y/n]"
  local answer
  read -r -p "$prompt $suffix: " answer
  if [[ -z "$answer" ]]; then
    [[ "$default" == "Y" ]]
    return
  fi
  [[ "$answer" =~ ^[Yy]$ ]]
}

import_secret_file() {
  local scope="$1"
  local name="$2"
  local path="$3"
  [[ -r "$path" ]] || { echo "Cannot read secret file: $path" >&2; return 1; }
  compose run --rm --no-deps -T api \
    python scripts/registry_cli.py secret-write --scope "$scope" --name "$name" \
    < "$path" | tail -n 1
}

import_secret_value() {
  local scope="$1"
  local name="$2"
  local value="$3"
  printf '%s' "$value" | compose run --rm --no-deps -T api \
    python scripts/registry_cli.py secret-write --scope "$scope" --name "$name" | tail -n 1
}

setup_registry() {
  echo "[ASO] Initial registry setup (non-destructive)."
  echo "This records existing providers/nodes only. It does NOT create/delete VPSs or mutate Master."
  compose up -d postgres >/dev/null
  compose run --rm api alembic upgrade head >/dev/null

  if [[ -z "$(get_env ASO_MASTER_3XUI_BASE_URL)" ]]; then
    if prompt_yes_no "Configure Master 3X-UI connection now?" "Y"; then
      local master_url master_token master_username master_password
      master_url="$(prompt_required 'Master 3X-UI base URL (https://...)')"
      read -r -s -p "Master API token (preferred; Enter for username/password): " master_token
      printf '\n'
      set_env ASO_MASTER_3XUI_BASE_URL "$master_url"
      if [[ -n "$master_token" ]]; then
        set_env ASO_MASTER_3XUI_API_TOKEN "$master_token"
      else
        master_username="$(prompt_required 'Master username')"
        read -r -s -p "Master password (hidden): " master_password
        printf '\n'
        set_env ASO_MASTER_3XUI_USERNAME "$master_username"
        set_env ASO_MASTER_3XUI_PASSWORD "$master_password"
      fi
    fi
  fi

  echo
  compose run --rm api python scripts/registry_cli.py list

  while prompt_yes_no "Add or update a provider?" "Y"; do
    local provider_type key display_name credential_ref token region server_type image
    provider_type="$(prompt_default 'Provider type (hetzner/linode)' 'hetzner')"
    case "$provider_type" in
      hetzner)
        credential_ref="ASO_HETZNER_API_TOKEN"
        ;;
      linode)
        credential_ref="ASO_LINODE_API_TOKEN"
        ;;
      *)
        echo "Unsupported provider type: $provider_type" >&2
        continue
        ;;
    esac
    key="$(prompt_required 'Provider key (example: hetzner-main)')"
    display_name="$(prompt_default 'Display name' "$key")"
    region="$(prompt_required 'Default provider region/location code')"
    server_type="$(prompt_required 'Default server type/plan code')"
    image="$(prompt_required 'Default image code')"

    if [[ -z "$(get_env "$credential_ref")" ]]; then
      read -r -s -p "$provider_type API token (stored in .env, hidden): " token
      printf '\n'
      [[ -n "$token" ]] || { echo "API token cannot be blank." >&2; continue; }
      set_env "$credential_ref" "$token"
    fi

    compose run --rm api python scripts/registry_cli.py add-provider \
      --key "$key" \
      --display-name "$display_name" \
      --type "$provider_type" \
      --credential-ref "$credential_ref" \
      --region "$region" \
      --server-type "$server_type" \
      --image "$image"
    echo
    prompt_yes_no "Add another provider?" "N" || break
  done

  while prompt_yes_no "Register an existing node/VPS?" "Y"; do
    local node_name provider_key master_id host port provider_server_id current_region current_server_type
    local ssh_username ssh_port auth_method ssh_secret_ref ssh_public_key private_key_path public_key_path
    local ssh_password panel_base_path current_api_token api_token_ref

    node_name="$(prompt_required 'Node name')"
    provider_key="$(prompt_required 'Provider key')"
    master_id="$(prompt_required 'Existing Master 3X-UI Node ID')"
    host="$(prompt_required 'Current node IP/host')"
    port="$(prompt_required 'Current node panel/API port')"
    provider_server_id="$(prompt_required 'Current VPS provider server/instance ID')"
    read -r -p "Current VPS region (Enter = provider default): " current_region
    read -r -p "Current VPS server type (Enter = provider default): " current_server_type

    ssh_username="$(prompt_default 'SSH username' 'root')"
    ssh_port="$(prompt_default 'SSH port' '22')"
    auth_method="$(prompt_default 'SSH auth (private_key/password)' 'private_key')"
    case "$auth_method" in
      private_key)
        private_key_path="$(prompt_required 'Path to SSH PRIVATE key on this server')"
        public_key_path="$(prompt_default 'Path to matching SSH PUBLIC key' "${private_key_path}.pub")"
        [[ -r "$public_key_path" ]] || { echo "Cannot read public key: $public_key_path" >&2; continue; }
        ssh_public_key="$(tr -d '\r\n' < "$public_key_path")"
        ssh_secret_ref="$(import_secret_file "node-$node_name" ssh-private-key "$private_key_path")"
        ;;
      password)
        read -r -s -p "SSH password (hidden): " ssh_password
        printf '\n'
        [[ -n "$ssh_password" ]] || { echo "SSH password cannot be blank." >&2; continue; }
        ssh_secret_ref="$(import_secret_value "node-$node_name" ssh-password "$ssh_password")"
        ssh_public_key=""
        unset ssh_password
        ;;
      *)
        echo "Unsupported SSH auth method: $auth_method" >&2
        continue
        ;;
    esac

    read -r -p "Current node base path (optional, example /abc/): " panel_base_path
    api_token_ref=""
    if prompt_yes_no "Store the CURRENT node API token for safe Master rollback?" "Y"; then
      read -r -s -p "Current node API token (hidden): " current_api_token
      printf '\n'
      if [[ -n "$current_api_token" ]]; then
        api_token_ref="$(import_secret_value "node-$node_name" current-api-token "$current_api_token")"
      fi
      unset current_api_token
    fi

    node_args=(
      python scripts/registry_cli.py add-node
      --name "$node_name"
      --provider-key "$provider_key"
      --master-node-id "$master_id"
      --host "$host"
      --port "$port"
      --provider-server-id "$provider_server_id"
      --ssh-username "$ssh_username"
      --ssh-port "$ssh_port"
      --ssh-auth-method "$auth_method"
      --ssh-secret-ref "$ssh_secret_ref"
    )
    [[ -z "$current_region" ]] || node_args+=(--region "$current_region")
    [[ -z "$current_server_type" ]] || node_args+=(--server-type "$current_server_type")
    [[ -z "$ssh_public_key" ]] || node_args+=(--ssh-public-key "$ssh_public_key")
    [[ -z "$panel_base_path" ]] || node_args+=(--panel-base-path "$panel_base_path")
    [[ -z "$api_token_ref" ]] || node_args+=(--api-token-ref "$api_token_ref")

    compose run --rm api "${node_args[@]}"
    echo
    prompt_yes_no "Register another node?" "N" || break
  done

  echo
  echo "[ASO] Registry status:"
  compose run --rm api python scripts/registry_cli.py list
  echo
  if compose run --rm api python scripts/registry_cli.py readiness; then
    echo "[ASO] Registry onboarding is ready."
  else
    echo "[ASO][WARN] Registry is still incomplete. Add the missing provider/node/VPS/credential records."
  fi

  echo
  echo "Reloading application containers so .env changes are picked up."
  compose up -d --force-recreate api worker
  if [[ "$(get_env ASO_TELEGRAM_BOT_ENABLED)" == "true" ]]; then
    compose --profile telegram up -d --force-recreate --no-deps bot
  fi
  echo
  echo "Next safe checks:"
  echo "  ./asoctl health"
  echo "  ./asoctl registry"
  echo "  Telegram: /start, /nodes, /providers, /check <node-name>"
  echo "Automatic replacement remains disabled."
}

cmd="${1:-help}"
shift || true

case "$cmd" in
  status)
    compose --profile telegram ps
    ;;
  health)
    port="$(get_env ASO_PORT)"
    [[ -n "$port" ]] || port=8000
    curl -fsS "http://127.0.0.1:${port}/health"
    printf '\n'
    ;;
  logs)
    compose --profile telegram logs --tail="${1:-200}" -f api worker bot
    ;;
  start)
    compose up -d postgres api worker
    if [[ "$(get_env ASO_TELEGRAM_BOT_ENABLED)" == "true" ]]; then
      compose --profile telegram up -d --no-deps bot
    fi
    ;;
  stop)
    # Intentionally does not remove named volumes.
    compose --profile telegram stop bot >/dev/null 2>&1 || true
    compose down
    ;;
  restart)
    # `docker compose restart` does not reload changed environment variables.
    compose up -d --force-recreate api worker
    if [[ "$(get_env ASO_TELEGRAM_BOT_ENABLED)" == "true" ]]; then
      compose --profile telegram up -d --force-recreate --no-deps bot
    fi
    ;;
  migrate)
    compose run --rm api alembic upgrade head
    ;;
  backup)
    compose --profile ops run --rm backup
    ;;
  validate)
    compose config >/dev/null
    compose run --rm api python scripts/security_review.py
    compose run --rm api python scripts/validate_patch11.py
    echo "ASO validation passed."
    ;;
  safety)
    printf 'ASO_DRY_RUN=%s\n' "$(get_env ASO_DRY_RUN)"
    printf 'ASO_ALLOW_REAL_INFRASTRUCTURE_MUTATION=%s\n' "$(get_env ASO_ALLOW_REAL_INFRASTRUCTURE_MUTATION)"
    printf 'ASO_ALLOW_OLD_VPS_DELETION=%s\n' "$(get_env ASO_ALLOW_OLD_VPS_DELETION)"
    printf 'ASO_REPLACEMENT_WORKER_ENABLED=%s\n' "$(get_env ASO_REPLACEMENT_WORKER_ENABLED)"
    printf 'ASO_WORKER_SCHEDULER_ENABLED=%s\n' "$(get_env ASO_WORKER_SCHEDULER_ENABLED)"
    printf 'ASO_MONITORING_SCHEDULER_ENABLED=%s\n' "$(get_env ASO_MONITORING_SCHEDULER_ENABLED)"
    printf 'ASO_REPLACEMENT_EMERGENCY_STOP=%s\n' "$(get_env ASO_REPLACEMENT_EMERGENCY_STOP)"
    ;;
  setup)
    setup_registry
    ;;
  registry)
    compose run --rm api python scripts/registry_cli.py list
    echo
    compose run --rm api python scripts/registry_cli.py readiness || true
    ;;
  telegram-check)
    if [[ "$(get_env ASO_TELEGRAM_BOT_ENABLED)" != "true" ]]; then
      echo "Telegram bot is disabled in .env" >&2
      exit 1
    fi
    compose --profile telegram run --rm --no-deps bot python scripts/telegram_probe.py
    compose --profile telegram ps bot
    ;;
  monitoring-dry-run)
    set_env ASO_DRY_RUN true
    set_env ASO_ALLOW_REAL_INFRASTRUCTURE_MUTATION false
    set_env ASO_ALLOW_OLD_VPS_DELETION false
    set_env ASO_REPLACEMENT_WORKER_ENABLED false
    set_env ASO_REPLACEMENT_EMERGENCY_STOP true
    set_env ASO_WORKER_SCHEDULER_ENABLED true
    set_env ASO_MONITORING_SCHEDULER_ENABLED true
    compose up -d --force-recreate worker
    echo "Monitoring scheduler enabled in safe DRY_RUN mode. Replacement remains disabled."
    ;;
  monitoring-off)
    set_env ASO_MONITORING_SCHEDULER_ENABLED false
    set_env ASO_WORKER_SCHEDULER_ENABLED false
    compose up -d --force-recreate worker
    echo "Monitoring scheduler disabled."
    ;;
  help|-h|--help)
    cat <<'HELP'
Usage: ./asoctl <command>

Commands:
  status               Show service status (including Telegram profile)
  health               Query the local API health endpoint
  logs [N]             Follow API/worker/bot logs (default last 200 lines)
  start                Start PostgreSQL, API, worker and enabled Telegram bot
  stop                 Stop the stack without deleting named volumes
  restart              Recreate app containers and reload .env
  migrate              Apply Alembic migrations
  backup               Create a PostgreSQL backup
  validate             Validate Compose + production security + release structure
  safety               Print non-secret safety switches
  setup                Interactive non-destructive Provider/Node/VPS onboarding
  registry             Show Provider/Node registry and readiness
  telegram-check       Verify Telegram API token and bot container
  monitoring-dry-run   Enable automatic monitoring only, with destructive paths locked
  monitoring-off       Disable the automatic monitoring scheduler
HELP
    ;;
  *)
    echo "Unknown command: $cmd" >&2
    exit 2
    ;;
esac
