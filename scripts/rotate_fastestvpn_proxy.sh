#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

compose_cmd=(
  docker compose
  -f docker-compose.yml
  -f docker-compose.fastestvpn.yml
)

wait_for_proxy_healthy() {
  local timeout_seconds="${FASTESTVPN_PROXY_HEALTH_TIMEOUT_SECONDS:-180}"
  local start_ts
  start_ts="$(date +%s)"
  while true; do
    local health
    health="$("${compose_cmd[@]}" ps --format json ea-fastestvpn-proxy 2>/dev/null | python3 -c '
import json, sys
raw = sys.stdin.read().strip()
if not raw:
    raise SystemExit(0)
rows = []
try:
    loaded = json.loads(raw)
    rows = loaded if isinstance(loaded, list) else [loaded]
except Exception:
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            pass
for row in rows:
    if not isinstance(row, dict):
        continue
    service = str(row.get("Service") or row.get("Name") or "")
    if service == "ea-fastestvpn-proxy" or service.endswith("ea-fastestvpn-proxy"):
        print(str(row.get("Health") or row.get("State") or ""))
        break
'
)" || health=""
    if [[ "${health,,}" == "healthy" ]]; then
      return 0
    fi
    if (( "$(date +%s)" - start_ts >= timeout_seconds )); then
      printf '[rotate-fastestvpn-proxy] proxy did not become healthy within %ss\n' "${timeout_seconds}" >&2
      "${compose_cmd[@]}" ps ea-fastestvpn-proxy >&2 || true
      return 1
    fi
    sleep 2
  done
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  cat <<'EOF'
Usage: rotate_fastestvpn_proxy.sh [--list|OVPN_CONFIG_PATH]

Without an argument, recreate the FastestVPN proxy with the configured random
selection policy. With OVPN_CONFIG_PATH, pin that OpenVPN config for this run.
EOF
  exit 0
fi

if [[ "${1:-}" == "--list" ]]; then
  find "${ROOT_DIR}/vpn/fastestvpn" -maxdepth 1 -type f -name "${FASTESTVPN_CONFIG_GLOB:-*.ovpn}" | sort
  exit 0
fi

if [[ -n "${1:-}" ]]; then
  export FASTESTVPN_CONFIG_FILE="$1"
  printf '[rotate-fastestvpn-proxy] pinned config: %s\n' "${FASTESTVPN_CONFIG_FILE}"
else
  unset FASTESTVPN_CONFIG_FILE || true
  printf '[rotate-fastestvpn-proxy] selecting config via FASTESTVPN_CONFIG_SELECT_MODE=%s\n' "${FASTESTVPN_CONFIG_SELECT_MODE:-random}"
fi

"${compose_cmd[@]}" up -d --build --force-recreate --no-deps ea-fastestvpn-proxy
wait_for_proxy_healthy

"${compose_cmd[@]}" ps ea-fastestvpn-proxy
