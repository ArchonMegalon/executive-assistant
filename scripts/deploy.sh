#!/usr/bin/env bash
set -euo pipefail

EA_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  cat <<'EOF'
Usage:
  bash scripts/deploy.sh

Environment:
  EA_MEMORY_ONLY=1       Deploy API service using docker-compose.memory.yml override.
  EA_BOOTSTRAP_DB=1      Run db bootstrap after deploy (ignored if EA_MEMORY_ONLY=1).
  EA_ENABLE_FASTESTVPN=1 Layer docker-compose.fastestvpn.yml when FastestVPN *.ovpn profiles are present.
EOF
  exit 0
fi

echo "== EA rewrite deploy: ${EA_ROOT} =="

if [[ ! -f "${EA_ROOT}/.env" ]]; then
  cp "${EA_ROOT}/.env.example" "${EA_ROOT}/.env"
  chmod 600 "${EA_ROOT}/.env"
  echo "Created .env from .env.example. Fill values and rerun."
  exit 1
fi

if docker compose version >/dev/null 2>&1; then
  DC=(docker compose)
else
  DC=(docker-compose)
fi

COMPOSE_ARGS=(-f docker-compose.yml)
FASTESTVPN_OVERLAY_ENABLED=0
if [[ "${EA_ENABLE_FASTESTVPN:-0}" == "1" ]]; then
  if find "${EA_ROOT}/vpn/fastestvpn" -maxdepth 1 -type f -name '*.ovpn' | grep -q .; then
    COMPOSE_ARGS+=(-f docker-compose.fastestvpn.yml)
    FASTESTVPN_OVERLAY_ENABLED=1
  else
    echo "EA_ENABLE_FASTESTVPN=1 but no FastestVPN *.ovpn profiles were found under ${EA_ROOT}/vpn/fastestvpn" >&2
    exit 1
  fi
fi

compose() {
  "${DC[@]}" "${COMPOSE_ARGS[@]}" "$@"
}

service_container_ready() {
  local service="$1"
  local cid
  local running
  local restarting
  local health

  cid="$(compose ps -q "${service}" || true)"
  if [[ -z "${cid}" ]]; then
    return 1
  fi

  running="$(docker inspect -f '{{.State.Running}}' "${cid}" 2>/dev/null || true)"
  restarting="$(docker inspect -f '{{.State.Restarting}}' "${cid}" 2>/dev/null || true)"
  health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "${cid}" 2>/dev/null || true)"

  [[ "${running}" == "true" ]] || return 1
  [[ "${restarting}" != "true" ]] || return 1
  [[ -z "${health}" || "${health}" == "healthy" ]] || return 1
}

cd "${EA_ROOT}"
if [[ "${EA_MEMORY_ONLY:-0}" == "1" ]]; then
  COMPOSE_ARGS=(-f docker-compose.yml -f docker-compose.memory.yml)
  TOPOLOGY_SERVICES=(ea-api)
  FAILURE_LOG_SERVICES=(ea-api)
  "${DC[@]}" -f docker-compose.yml -f docker-compose.memory.yml up -d --build ea-api
else
  TOPOLOGY_SERVICES=(ea-api ea-worker ea-scheduler)
  FAILURE_LOG_SERVICES=(ea-api ea-worker ea-scheduler ea-db)
  if [[ "${FASTESTVPN_OVERLAY_ENABLED}" == "1" ]]; then
    FAILURE_LOG_SERVICES+=(ea-fastestvpn-proxy ea-fastestvpn-proxy-ie ea-fastestvpn-proxy-nl)
  fi
  compose up -d --build
fi

if [[ "${EA_BOOTSTRAP_DB:-0}" == "1" ]]; then
  if [[ "${EA_MEMORY_ONLY:-0}" == "1" ]]; then
    echo "EA_BOOTSTRAP_DB=1 ignored because EA_MEMORY_ONLY=1"
  else
    echo "EA_BOOTSTRAP_DB=1 -> applying kernel migrations"
    bash "${EA_ROOT}/scripts/db_bootstrap.sh"
  fi
fi

HOST_PORT="$(grep -E '^EA_HOST_PORT=' "${EA_ROOT}/.env" | tail -n1 | cut -d= -f2- || true)"
HOST_PORT="${HOST_PORT:-8090}"

for _ in $(seq 1 60); do
  topology_ready=1
  for service in "${TOPOLOGY_SERVICES[@]}"; do
    if ! service_container_ready "${service}"; then
      topology_ready=0
      break
    fi
  done

  if [[ "${topology_ready}" == "1" ]] && curl -fsS "http://localhost:${HOST_PORT}/health" >/dev/null 2>&1; then
    echo "EA rewrite baseline healthy at http://localhost:${HOST_PORT} with ${TOPOLOGY_SERVICES[*]}"
    exit 0
  fi
  sleep 1
done

echo "Health check failed; dumping logs"
compose ps || true
compose logs --tail 200 "${FAILURE_LOG_SERVICES[@]}" || true
exit 1
