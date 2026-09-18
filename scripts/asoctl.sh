#!/usr/bin/env bash
set -Eeuo pipefail

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

cmd="${1:-help}"
shift || true

case "$cmd" in
  status)
    compose ps
    ;;
  health)
    port="$(get_env ASO_PORT)"
    [[ -n "$port" ]] || port=8000
    curl -fsS "http://127.0.0.1:${port}/health"
    printf '\n'
    ;;
  logs)
    compose logs --tail="${1:-200}" -f api worker bot
    ;;
  start)
    compose up -d postgres api worker
    if [[ "$(get_env ASO_TELEGRAM_BOT_ENABLED)" == "true" ]]; then
      compose --profile telegram up -d bot
    fi
    ;;
  stop)
    # Intentionally does not remove named volumes.
    compose down
    ;;
  restart)
    compose restart api worker
    if [[ "$(get_env ASO_TELEGRAM_BOT_ENABLED)" == "true" ]]; then
      compose --profile telegram restart bot
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
    compose run --rm api python scripts/validate_patch05.py
    echo "ASO validation passed."
    ;;
  safety)
    printf 'ASO_DRY_RUN=%s\n' "$(get_env ASO_DRY_RUN)"
    printf 'ASO_ALLOW_REAL_INFRASTRUCTURE_MUTATION=%s\n' "$(get_env ASO_ALLOW_REAL_INFRASTRUCTURE_MUTATION)"
    printf 'ASO_REPLACEMENT_WORKER_ENABLED=%s\n' "$(get_env ASO_REPLACEMENT_WORKER_ENABLED)"
    printf 'ASO_WORKER_SCHEDULER_ENABLED=%s\n' "$(get_env ASO_WORKER_SCHEDULER_ENABLED)"
    printf 'ASO_REPLACEMENT_EMERGENCY_STOP=%s\n' "$(get_env ASO_REPLACEMENT_EMERGENCY_STOP)"
    ;;
  help|-h|--help)
    cat <<'HELP'
Usage: ./asoctl <command>

Commands:
  status      Show Compose service status
  health      Query the local API health endpoint
  logs [N]    Follow API/worker/bot logs (default last 200 lines)
  start       Start PostgreSQL, API, worker and enabled Telegram bot
  stop        Stop the stack without deleting named volumes
  restart     Restart application processes
  migrate     Apply Alembic migrations
  backup      Create a PostgreSQL backup
  validate    Validate Compose + production security + release structure
  safety      Print non-secret safety switches
HELP
    ;;
  *)
    echo "Unknown command: $cmd" >&2
    exit 2
    ;;
esac
