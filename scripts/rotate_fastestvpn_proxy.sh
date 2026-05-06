#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

compose_available=0
if docker compose version >/dev/null 2>&1; then
  compose_available=1
fi

compose_cmd=(
  docker compose
  -f docker-compose.yml
  -f docker-compose.fastestvpn.yml
)

service_name="${FASTESTVPN_ROTATE_SERVICE_NAME:-ea-fastestvpn-proxy}"
config_file_arg=""

while (( "$#" > 0 )); do
  case "${1:-}" in
    --service)
      service_name="${2:-}"
      if [[ -z "${service_name}" ]]; then
        printf '[rotate-fastestvpn-proxy] --service requires a compose service name\n' >&2
        exit 2
      fi
      shift 2
      ;;
    --help|-h)
      cat <<'EOF'
Usage: rotate_fastestvpn_proxy.sh [--service SERVICE] [--list|OVPN_CONFIG_PATH]

Without an argument, recreate the selected FastestVPN proxy with the configured
selection policy. With OVPN_CONFIG_PATH, pin that OpenVPN config for this run.
EOF
      exit 0
      ;;
    --list)
      find "${ROOT_DIR}/vpn/fastestvpn" -maxdepth 1 -type f -name "${FASTESTVPN_CONFIG_GLOB:-*.ovpn}" | sort
      exit 0
      ;;
    *)
      if [[ -n "${config_file_arg}" ]]; then
        printf '[rotate-fastestvpn-proxy] only one OVPN_CONFIG_PATH may be provided\n' >&2
        exit 2
      fi
      config_file_arg="$1"
      shift
      ;;
  esac
done

wait_for_proxy_healthy() {
  local timeout_seconds="${FASTESTVPN_PROXY_HEALTH_TIMEOUT_SECONDS:-180}"
  local start_ts
  start_ts="$(date +%s)"
  while true; do
    local health
    if (( compose_available == 1 )); then
      local cid
      cid="$("${compose_cmd[@]}" ps -q "${service_name}" 2>/dev/null || true)"
      if [[ -n "${cid}" ]]; then
        health="$(docker inspect "${cid}" --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' 2>/dev/null || true)"
      else
        health=""
      fi
    else
      health="$(docker inspect "${service_name}" --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' 2>/dev/null || true)"
    fi
    if [[ "${health,,}" == "healthy" ]]; then
      return 0
    fi
    if (( "$(date +%s)" - start_ts >= timeout_seconds )); then
      printf '[rotate-fastestvpn-proxy] proxy did not become healthy within %ss\n' "${timeout_seconds}" >&2
      if (( compose_available == 1 )); then
        "${compose_cmd[@]}" ps "${service_name}" >&2 || true
      else
        docker ps --filter "name=^/${service_name}$" >&2 || true
      fi
      return 1
    fi
    sleep 2
  done
}

if [[ -n "${config_file_arg}" ]]; then
  export FASTESTVPN_CONFIG_FILE="${config_file_arg}"
  printf '[rotate-fastestvpn-proxy] pinned config: %s\n' "${FASTESTVPN_CONFIG_FILE}"
else
  unset FASTESTVPN_CONFIG_FILE || true
  printf '[rotate-fastestvpn-proxy] selecting config via FASTESTVPN_CONFIG_SELECT_MODE=%s\n' "${FASTESTVPN_CONFIG_SELECT_MODE:-random}"
fi

if (( compose_available == 1 )); then
  "${compose_cmd[@]}" up -d --build --force-recreate --no-deps "${service_name}"
elif [[ -n "${FASTESTVPN_CONFIG_FILE:-}" ]]; then
  printf '[rotate-fastestvpn-proxy] pinned config rotation requires docker compose support\n' >&2
  exit 1
else
  docker restart "${service_name}" >/dev/null
fi
wait_for_proxy_healthy

if (( compose_available == 1 )); then
  "${compose_cmd[@]}" ps "${service_name}"
else
  docker ps --filter "name=^/${service_name}$"
fi
