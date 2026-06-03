#!/usr/bin/env bash
set -euo pipefail

EA_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXTRA_COMPOSE_OVERRIDES=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --help|-h)
      cat <<'EOF'
Usage:
  bash scripts/deploy.sh [--compose-override <file>]...

Options:
  --compose-override <file>  Layer an extra compose override onto the deploy topology.

Environment:
  EA_MEMORY_ONLY=1       Deploy API service using docker-compose.memory.yml override.
  EA_BOOTSTRAP_DB=1      Run db bootstrap after deploy (ignored if EA_MEMORY_ONLY=1).
  EA_ENABLE_FASTESTVPN=1 Layer docker-compose.fastestvpn.yml when FastestVPN *.ovpn profiles are present.
  EA_ENABLE_CLOUDFLARED=1|0  Force Cloudflare tunnel override on or off (default: auto when EA_CF_TUNNEL_TOKEN is set).
  EA_RUN_RUNTIME_HARD_EXIT_GATES=1|0  Run runtime hard exit gates after health goes green (default: 1).
EOF
      exit 0
      ;;
    --compose-override)
      if [[ $# -lt 2 ]]; then
        echo "--compose-override requires a compose file path" >&2
        exit 1
      fi
      EXTRA_COMPOSE_OVERRIDES+=("$2")
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

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

COMPOSE_ARGS=(-f docker-compose.yml -f docker-compose.prod.yml)
FASTESTVPN_OVERLAY_ENABLED=0
CLOUDFLARED_OVERLAY_ENABLED=0
if [[ "${EA_ENABLE_FASTESTVPN:-0}" == "1" ]]; then
  if find "${EA_ROOT}/vpn/fastestvpn" -maxdepth 1 -type f -name '*.ovpn' | grep -q .; then
    COMPOSE_ARGS+=(-f docker-compose.fastestvpn.yml)
    FASTESTVPN_OVERLAY_ENABLED=1
  else
    echo "EA_ENABLE_FASTESTVPN=1 but no FastestVPN *.ovpn profiles were found under ${EA_ROOT}/vpn/fastestvpn" >&2
    exit 1
  fi
fi

for override in "${EXTRA_COMPOSE_OVERRIDES[@]}"; do
  if [[ ! -f "${EA_ROOT}/${override}" && ! -f "${override}" ]]; then
    echo "Compose override not found: ${override}" >&2
    exit 1
  fi
  COMPOSE_ARGS+=(-f "${override}")
done

if [[ "${EA_MEMORY_ONLY:-0}" != "1" ]]; then
  should_enable_cloudflared="${EA_ENABLE_CLOUDFLARED:-auto}"
  cloudflared_override="docker-compose.cloudflared.yml"
  if [[ "${should_enable_cloudflared}" == "1" || ( "${should_enable_cloudflared}" == "auto" && -n "$(grep -E '^EA_CF_TUNNEL_TOKEN=' "${EA_ROOT}/.env" | tail -n1 | cut -d= -f2- | tr -d '[:space:]')" ) ]]; then
    COMPOSE_ARGS+=(-f "${cloudflared_override}")
    CLOUDFLARED_OVERLAY_ENABLED=1
  fi
fi

compose() {
  COMPOSE_IGNORE_ORPHANS=1 "${DC[@]}" "${COMPOSE_ARGS[@]}" "$@"
}

build_and_recreate_services() {
  local -a build_services=("$@")
  if [[ "${#build_services[@]}" -eq 0 ]]; then
    return 0
  fi

  compose build "${build_services[@]}"
  compose up -d --no-build ea-db ea-openvoice
  local service
  for service in "${build_services[@]}"; do
    compose up -d --no-build --no-deps --force-recreate "${service}"
    for _ in $(seq 1 30); do
      if service_container_ready "${service}"; then
        break
      fi
      sleep 1
    done
    if ! service_container_ready "${service}"; then
      echo "Service failed to become ready during deploy: ${service}" >&2
      return 1
    fi
  done
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
  COMPOSE_IGNORE_ORPHANS=1 "${DC[@]}" -f docker-compose.yml -f docker-compose.memory.yml up -d --build ea-api
else
  RUNTIME_BUILD_SERVICES=(ea-teable-relay ea-api ea-responses-proxy ea-worker ea-scheduler)
  TOPOLOGY_SERVICES=(ea-teable-relay ea-api ea-responses-proxy ea-worker ea-scheduler ea-db)
  FAILURE_LOG_SERVICES=(ea-teable-relay ea-api ea-responses-proxy ea-worker ea-scheduler ea-db ea-openvoice)
  if [[ "${CLOUDFLARED_OVERLAY_ENABLED}" == "1" ]]; then
    TOPOLOGY_SERVICES+=(ea-cloudflared)
    FAILURE_LOG_SERVICES+=(ea-cloudflared)
  fi
  if [[ "${FASTESTVPN_OVERLAY_ENABLED}" == "1" ]]; then
    FAILURE_LOG_SERVICES+=(ea-fastestvpn-proxy ea-fastestvpn-proxy-ie ea-fastestvpn-proxy-nl)
  fi
  build_and_recreate_services "${RUNTIME_BUILD_SERVICES[@]}"
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
    stable_checks=1
    for _stable in $(seq 1 5); do
      sleep 1
      if ! curl -fsS "http://localhost:${HOST_PORT}/health" >/dev/null 2>&1; then
        stable_checks=0
        break
      fi
    done
    if [[ "${stable_checks}" != "1" ]]; then
      continue
    fi
    python3 "${EA_ROOT}/scripts/materialize_ea_browser_workflow_proof.py" >/dev/null
    python3 "${EA_ROOT}/scripts/materialize_ea_flagship_release_gate.py" >/dev/null
    python3 "${EA_ROOT}/scripts/materialize_weekly_product_pulse.py" >/dev/null
    if [[ "${EA_RUN_RUNTIME_HARD_EXIT_GATES:-1}" != "0" ]]; then
      bash "${EA_ROOT}/scripts/runtime_hard_exit_gates.sh"
    fi
    echo "EA rewrite baseline healthy at http://localhost:${HOST_PORT} with ${TOPOLOGY_SERVICES[*]}"
    exit 0
  fi
  sleep 1
done

echo "Health check failed; dumping logs"
compose ps || true
compose logs --tail 200 "${FAILURE_LOG_SERVICES[@]}" || true
exit 1
