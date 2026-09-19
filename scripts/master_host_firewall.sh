#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$PROJECT_ROOT/.env"
COMPOSE_FILE="$PROJECT_ROOT/docker-compose.prod.yml"
MODE="${1:---apply}"

case "$MODE" in
  --apply|--check) ;;
  -h|--help)
    cat <<'HELP'
Usage: scripts/master_host_firewall.sh [--apply|--check]

Verify Docker-to-host connectivity for a same-server 3X-UI Master.
--apply may add one narrow UFW rule for the ASO Docker bridge/subnet -> Master port.
--check never changes firewall rules.
Remote Master deployments are detected and left untouched.
HELP
    exit 0
    ;;
  *) echo "Unknown argument: $MODE" >&2; exit 2 ;;
esac

log() { printf '[ASO][MASTER-NET] %s\n' "$*"; }
warn() { printf '[ASO][MASTER-NET][WARN] %s\n' "$*" >&2; }

[[ -f "$ENV_FILE" ]] || { warn "Missing $ENV_FILE; skipping Master network guard."; exit 0; }

get_env() {
  local key="$1"
  awk -v key="$key" 'index($0, key "=") == 1 { sub("^[^=]*=", ""); print; exit }' "$ENV_FILE"
}

compose() {
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

run_privileged() {
  if [[ ${EUID:-$(id -u)} -eq 0 ]]; then
    "$@"
  elif command -v sudo >/dev/null 2>&1; then
    sudo "$@"
  else
    return 77
  fi
}

parse_master_url() {
  local url="$1" rest authority scheme
  [[ "$url" == *"://"* ]] || return 1
  scheme="${url%%://*}"
  rest="${url#*://}"
  authority="${rest%%/*}"
  authority="${authority##*@}"

  # Do not auto-edit firewall rules for IPv6 literals; require explicit operator review.
  [[ "$authority" != \[* ]] || return 2

  if [[ "$authority" == *:* ]]; then
    MASTER_HOST="${authority%%:*}"
    MASTER_PORT="${authority##*:}"
  else
    MASTER_HOST="$authority"
    case "$scheme" in
      http) MASTER_PORT=80 ;;
      https) MASTER_PORT=443 ;;
      *) return 1 ;;
    esac
  fi

  [[ -n "$MASTER_HOST" && "$MASTER_PORT" =~ ^[0-9]+$ && "$MASTER_PORT" -ge 1 && "$MASTER_PORT" -le 65535 ]]
}

host_resolves_local() {
  local host="$1" resolved local_ips ip
  case "$host" in
    localhost|127.0.0.1|host.docker.internal) return 0 ;;
  esac

  command -v getent >/dev/null 2>&1 || return 1
  command -v ip >/dev/null 2>&1 || return 1

  resolved="$(getent ahostsv4 "$host" 2>/dev/null | awk '{print $1}' | sort -u || true)"
  [[ -n "$resolved" ]] || return 1
  local_ips="$(ip -4 -o addr show 2>/dev/null | awk '{split($4,a,"/"); print a[1]}' | sort -u || true)"

  while IFS= read -r ip; do
    [[ -n "$ip" ]] || continue
    if grep -Fxq "$ip" <<<"$local_ips"; then
      return 0
    fi
  done <<<"$resolved"
  return 1
}

host_port_is_listening() {
  local port="$1"
  command -v ss >/dev/null 2>&1 || return 0
  ss -H -lnt 2>/dev/null | awk -v suffix=":${port}" '$4 ~ (suffix "$") { found=1 } END { exit found ? 0 : 1 }'
}

api_container_id() {
  compose ps -q api 2>/dev/null | head -n 1
}

api_network_details() {
  local cid="$1" network network_id subnet bridge
  network="$(docker inspect -f '{{range $name, $cfg := .NetworkSettings.Networks}}{{$name}}{{"\n"}}{{end}}' "$cid" 2>/dev/null | head -n 1)"
  [[ -n "$network" ]] || return 1
  network_id="$(docker network inspect -f '{{.Id}}' "$network" 2>/dev/null)"
  subnet="$(docker network inspect -f '{{range .IPAM.Config}}{{if .Subnet}}{{.Subnet}}{{"\n"}}{{end}}{{end}}' "$network" 2>/dev/null | head -n 1)"
  [[ -n "$network_id" && -n "$subnet" ]] || return 1

  if [[ "$network" == "bridge" ]]; then
    bridge="docker0"
  else
    bridge="br-${network_id:0:12}"
  fi

  printf '%s|%s|%s\n' "$network" "$subnet" "$bridge"
}

container_can_reach_host_master() {
  local port="$1"
  compose exec -T api python - "$port" <<'PY' >/dev/null 2>&1
import socket
import sys

port = int(sys.argv[1])
with socket.create_connection(("host.docker.internal", port), timeout=4):
    pass
PY
}

ufw_active() {
  command -v ufw >/dev/null 2>&1 || return 1
  run_privileged ufw status 2>/dev/null | head -n 1 | grep -q '^Status: active$'
}

master_url="$(get_env ASO_MASTER_3XUI_BASE_URL)"
connection_mode="$(get_env ASO_MASTER_3XUI_CONNECTION_MODE)"
[[ -n "$connection_mode" ]] || connection_mode=auto

if [[ -z "$master_url" ]]; then
  log "Master URL is not configured; no host firewall work is required."
  exit 0
fi

case "$connection_mode" in
  remote)
    log "Master connection mode is remote; host firewall is intentionally untouched."
    exit 0
    ;;
  auto|local-host) ;;
  *)
    warn "Unknown ASO_MASTER_3XUI_CONNECTION_MODE=$connection_mode; refusing to modify the firewall."
    exit 0
    ;;
esac

if ! parse_master_url "$master_url"; then
  warn "Could not safely parse Master URL; refusing to modify the firewall."
  exit 0
fi

if [[ "$connection_mode" == "auto" ]] && ! host_resolves_local "$MASTER_HOST"; then
  log "Master host $MASTER_HOST does not resolve to this server; treating it as remote and leaving the firewall untouched."
  exit 0
fi

if ! host_port_is_listening "$MASTER_PORT"; then
  warn "Master appears local, but no local listener was detected on TCP/$MASTER_PORT; no firewall rule was added."
  exit 1
fi

cid="$(api_container_id)"
if [[ -z "$cid" ]]; then
  warn "API container is not running; start/recreate the app before checking local Master connectivity."
  exit 1
fi

if container_can_reach_host_master "$MASTER_PORT"; then
  log "Docker can already reach the local 3X-UI Master on TCP/$MASTER_PORT; no firewall change required."
  exit 0
fi

IFS='|' read -r network subnet bridge < <(api_network_details "$cid") || {
  warn "Could not determine the API container Docker subnet; firewall was not modified."
  exit 1
}

if ! ip link show "$bridge" >/dev/null 2>&1; then
  warn "Expected Docker bridge $bridge for network $network was not found; firewall was not modified."
  exit 1
fi

log "Detected same-server Master: host=$MASTER_HOST port=$MASTER_PORT network=$network subnet=$subnet bridge=$bridge"
log "Required access is limited to: $subnet via $bridge -> this host TCP/$MASTER_PORT"

if [[ "$MODE" == "--check" ]]; then
  warn "Connectivity is blocked. Check mode never changes firewall rules."
  exit 1
fi

if ! ufw_active; then
  warn "UFW is not active/available. No firewall rule was changed automatically."
  warn "If another firewall blocks Docker-to-host traffic, allow only $subnet via $bridge to TCP/$MASTER_PORT."
  exit 1
fi

if run_privileged ufw status 2>/dev/null | grep -F "$subnet" | grep -F "${MASTER_PORT}/tcp" | grep -F "ALLOW IN" >/dev/null 2>&1; then
  log "Equivalent narrow UFW rule already exists for $subnet -> TCP/$MASTER_PORT; no duplicate rule added."
else
  log "Applying narrow UFW rule at highest priority; no existing firewall rule is removed or globally opened."
  if run_privileged ufw insert 1 allow in on "$bridge" from "$subnet" to any port "$MASTER_PORT" proto tcp comment 'ASO Docker to local 3X-UI Master'; then
    :
  else
  rc=$?
  if [[ $rc -eq 77 ]]; then
    warn "Root privileges are required to adjust UFW. Re-run: sudo ./asoctl master-network-check"
  else
    warn "UFW rule could not be applied."
    fi
    exit 1
  fi
  run_privileged ufw reload >/dev/null 2>&1 || true
fi

if container_can_reach_host_master "$MASTER_PORT"; then
  log "Verified Docker -> local 3X-UI Master connectivity on TCP/$MASTER_PORT."
  exit 0
fi

warn "The narrow UFW rule was applied, but Docker still cannot reach TCP/$MASTER_PORT."
warn "Another firewall chain (for example fail2ban/raw iptables) may be blocking the path."
exit 1
