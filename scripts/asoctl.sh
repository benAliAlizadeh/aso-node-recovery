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
  echo "[ASO] Smart registry onboarding (read-only discovery first)."
  echo "Provider/Master/Node APIs are validated before DB registration."
  echo "No VPS is created/deleted and Master is never mutated by this setup flow."
  compose up -d postgres >/dev/null
  compose run --rm api alembic upgrade head >/dev/null

  if [[ -z "$(get_env ASO_MASTER_3XUI_BASE_URL)" ]]; then
    echo
    echo "Master 3X-UI connection is required for automatic Node discovery."
    local master_url master_token master_username master_password
    master_url="$(prompt_required 'Master 3X-UI base URL (https://...)')"
    read -r -s -p "Master API token (preferred; Enter for username/password): " master_token
    printf '\n'
    set_env ASO_MASTER_3XUI_BASE_URL "$master_url"
    if [[ -n "$master_token" ]]; then
      set_env ASO_MASTER_3XUI_API_TOKEN "$master_token"
      set_env ASO_MASTER_3XUI_USERNAME ""
      set_env ASO_MASTER_3XUI_PASSWORD ""
    else
      master_username="$(prompt_required 'Master username')"
      read -r -s -p "Master password (hidden): " master_password
      printf '\n'
      [[ -n "$master_password" ]] || { echo "Master password cannot be blank." >&2; return 1; }
      set_env ASO_MASTER_3XUI_USERNAME "$master_username"
      set_env ASO_MASTER_3XUI_PASSWORD "$master_password"
      set_env ASO_MASTER_3XUI_API_TOKEN ""
    fi
    unset master_token master_password
  fi

  echo
  compose run --rm api python scripts/registry_cli.py list

  while prompt_yes_no "Add or update a provider?" "Y"; do
    local provider_type key display_name credential_ref credential_backend token env_token_key candidate_id
    provider_type="$(prompt_default 'Provider type (hetzner/linode)' 'linode')"
    case "$provider_type" in
      hetzner) env_token_key="ASO_HETZNER_API_TOKEN" ;;
      linode) env_token_key="ASO_LINODE_API_TOKEN" ;;
      *) echo "Unsupported provider type: $provider_type" >&2; continue ;;
    esac

    key="$(prompt_required 'Provider key (example: linode-main)')"
    display_name="$(prompt_default 'Display name' "$key")"
    read -r -s -p "$provider_type API token (Enter = reuse configured $env_token_key): " token
    printf '\n'

    if [[ -n "$token" ]]; then
      candidate_id="$(date +%s)-$$-$RANDOM"
      credential_ref="$(import_secret_value "provider-${key}-candidate-${candidate_id}" api-token "$token")"
      credential_backend="file"
    elif [[ -n "$(get_env "$env_token_key")" ]]; then
      credential_ref="$env_token_key"
      credential_backend="environment"
    else
      echo "No provider API token supplied/configured; provider was not saved." >&2
      continue
    fi
    unset token

    echo "[ASO] Verifying read access to $provider_type before saving..."
    if ! compose run --rm api python scripts/registry_cli.py smart-add-provider \
      --key "$key" \
      --display-name "$display_name" \
      --type "$provider_type" \
      --credential-ref "$credential_ref" \
      --credential-backend "$credential_backend"; then
      echo "[ASO][FAIL] Provider validation failed. Nothing was registered in the DB." >&2
      continue
    fi
    echo
    prompt_yes_no "Add another provider?" "N" || break
  done

  while prompt_yes_no "Discover and register an existing Node/VPS?" "Y"; do
    local provider_key provider_server_id master_id node_name current_api_token api_token_ref candidate_id
    local ssh_username ssh_port auth_method ssh_secret_ref ssh_public_key private_key_path public_key_path ssh_password
    local preview_output region_override server_type_override image_override

    provider_key="$(prompt_required 'Provider key')"
    provider_server_id="$(prompt_required 'Provider server/instance ID')"
    master_id="$(prompt_required 'Existing Master 3X-UI Node ID')"

    api_token_ref=""
    read -r -s -p "Current 3X-UI Node API token (hidden; required when Master says token is configured): " current_api_token
    printf '\n'
    if [[ -n "$current_api_token" ]]; then
      candidate_id="$(date +%s)-$$-$RANDOM"
      api_token_ref="$(import_secret_value "node-${provider_key}-${provider_server_id}-candidate-${candidate_id}" current-api-token "$current_api_token")"
    fi
    unset current_api_token

    echo
    echo "[ASO] Discovering VPS metadata from Provider and Node metadata from Master..."
    preview_args=(
      python scripts/registry_cli.py smart-preview-node
      --provider-key "$provider_key"
      --provider-server-id "$provider_server_id"
      --master-node-id "$master_id"
    )
    [[ -z "$api_token_ref" ]] || preview_args+=(--api-token-ref "$api_token_ref")
    region_override=""
    server_type_override=""
    image_override=""
    if ! preview_output="$(compose run --rm api "${preview_args[@]}" 2>&1)"; then
      printf '%s
' "$preview_output" >&2
      if [[ "$preview_output" == *"provider API could not discover required replacement metadata"* ]]         && prompt_yes_no "Provider could not expose all replacement metadata. Enter only the missing values manually?" "Y"; then
        read -r -p "Region/location override (Enter = keep auto): " region_override
        read -r -p "Server type/plan override (Enter = keep auto): " server_type_override
        read -r -p "Image override (Enter = keep auto): " image_override
        [[ -z "$region_override" ]] || preview_args+=(--region-override "$region_override")
        [[ -z "$server_type_override" ]] || preview_args+=(--server-type-override "$server_type_override")
        [[ -z "$image_override" ]] || preview_args+=(--image-override "$image_override")
        if ! preview_output="$(compose run --rm api "${preview_args[@]}" 2>&1)"; then
          printf '%s
' "$preview_output" >&2
          echo "[ASO][FAIL] Discovery/validation still failed. Node was not registered." >&2
          continue
        fi
      else
        echo "[ASO][FAIL] Discovery/validation failed. Node was not registered." >&2
        continue
      fi
    fi
    printf '%s
' "$preview_output"

    echo
    if ! prompt_yes_no "The discovered Provider/Master/Node API data above is correct. Register it?" "Y"; then
      echo "Node registration cancelled."
      continue
    fi

    read -r -p "Local ASO node name (Enter = discovered Master node name): " node_name
    ssh_username="$(prompt_default 'SSH username for replacement VPSs' 'root')"
    ssh_port="$(prompt_default 'SSH port' '22')"
    auth_method="$(prompt_default 'SSH auth (private_key/password)' 'private_key')"
    case "$auth_method" in
      private_key)
        private_key_path="$(prompt_required 'Path to SSH PRIVATE key on this server')"
        public_key_path="$(prompt_default 'Path to matching SSH PUBLIC key' "${private_key_path}.pub")"
        [[ -r "$public_key_path" ]] || { echo "Cannot read public key: $public_key_path" >&2; continue; }
        ssh_public_key="$(tr -d '\r\n' < "$public_key_path")"
        candidate_id="$(date +%s)-$$-$RANDOM"
        ssh_secret_ref="$(import_secret_file "node-${provider_key}-${provider_server_id}-candidate-${candidate_id}" ssh-private-key "$private_key_path")"
        ;;
      password)
        read -r -s -p "SSH password for replacement VPSs (hidden): " ssh_password
        printf '\n'
        [[ -n "$ssh_password" ]] || { echo "SSH password cannot be blank." >&2; continue; }
        candidate_id="$(date +%s)-$$-$RANDOM"
        ssh_secret_ref="$(import_secret_value "node-${provider_key}-${provider_server_id}-candidate-${candidate_id}" ssh-password "$ssh_password")"
        ssh_public_key=""
        unset ssh_password
        ;;
      *)
        echo "Unsupported SSH auth method: $auth_method" >&2
        continue
        ;;
    esac

    node_args=(
      python scripts/registry_cli.py smart-add-node
      --provider-key "$provider_key"
      --provider-server-id "$provider_server_id"
      --master-node-id "$master_id"
      --ssh-username "$ssh_username"
      --ssh-port "$ssh_port"
      --ssh-auth-method "$auth_method"
      --ssh-secret-ref "$ssh_secret_ref"
    )
    [[ -z "$node_name" ]] || node_args+=(--name "$node_name")
    [[ -z "$ssh_public_key" ]] || node_args+=(--ssh-public-key "$ssh_public_key")
    [[ -z "$api_token_ref" ]] || node_args+=(--api-token-ref "$api_token_ref")
    [[ -z "$region_override" ]] || node_args+=(--region-override "$region_override")
    [[ -z "$server_type_override" ]] || node_args+=(--server-type-override "$server_type_override")
    [[ -z "$image_override" ]] || node_args+=(--image-override "$image_override")

    echo "[ASO] Re-validating discovery immediately before DB commit..."
    if ! compose run --rm api "${node_args[@]}"; then
      echo "[ASO][FAIL] Final validation failed. Node was not registered." >&2
      continue
    fi
    echo
    prompt_yes_no "Register another node?" "N" || break
  done

  echo
  echo "[ASO] Registry status:"
  compose run --rm api python scripts/registry_cli.py list
  echo
  if compose run --rm api python scripts/registry_cli.py readiness; then
    echo "[ASO] Smart onboarding is ready."
  else
    echo "[ASO][WARN] Registry is still incomplete. Run ./asoctl setup again to add missing records."
  fi

  echo
  echo "Reloading application containers so current .env settings are picked up."
  compose up -d --force-recreate api worker
  if [[ "$(get_env ASO_TELEGRAM_BOT_ENABLED)" == "true" ]]; then
    compose --profile telegram up -d --force-recreate --no-deps bot
  fi
  echo
  echo "Safe next checks:"
  echo "  ./asoctl health"
  echo "  ./asoctl registry"
  echo "  Telegram: /start, /nodes, /providers"
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
    compose run --rm api python scripts/validate_patch16.py
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
  controls)
    compose run --rm api python scripts/runtime_control_cli.py show
    ;;
  monitoring-dry-run)
    compose run --rm api python scripts/runtime_control_cli.py dry-run
    compose run --rm api python scripts/runtime_control_cli.py auto-off
    compose run --rm api python scripts/runtime_control_cli.py monitoring-on
    compose up -d worker
    echo "Monitoring enabled with effective DRY_RUN; automatic repair disabled."
    ;;
  monitoring-off)
    compose run --rm api python scripts/runtime_control_cli.py monitoring-off
    echo "Runtime monitoring disabled. No container recreation required."
    ;;
  auto-repair-on)
    compose run --rm api python scripts/runtime_control_cli.py auto-on
    compose up -d worker
    echo "Automatic repair worker enabled. Node AUTO REPAIR modes and execution safety gates still apply."
    ;;
  auto-repair-off)
    compose run --rm api python scripts/runtime_control_cli.py auto-off
    echo "Automatic repair worker disabled."
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
  controls             Show persisted runtime monitoring/repair controls
  monitoring-dry-run   Enable automatic monitoring only, with destructive paths locked
  monitoring-off       Disable the automatic monitoring scheduler
HELP
    ;;
  *)
    echo "Unknown command: $cmd" >&2
    exit 2
    ;;
esac
