#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RELEASE_MANIFEST_PATH="${RELEASE_MANIFEST_PATH:-${APP_ROOT}/.codex-studio/published/release_manifest.generated.json}"
EXTRA_COMPOSE_OVERRIDES=()
DEPLOY_PRIMARY_MODE="${EA_DEPLOY_PRIMARY_MODE:-${EA_DEPLOY_PROJECT_MODE:-EA_CORE}}"
DEPLOY_ENABLED_MODES=()
if [[ "${PROPERTYQUARRY_USE_LEGACY_STACK:-0}" == "1" ]]; then
  export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-ea}"
else
  export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-propertyquarry}"
fi

memory_only="${PROPERTYQUARRY_MEMORY_ONLY:-${EA_MEMORY_ONLY:-0}}"
bootstrap_db="${PROPERTYQUARRY_BOOTSTRAP_DB:-${EA_BOOTSTRAP_DB:-0}}"
enable_fastestvpn="${PROPERTYQUARRY_ENABLE_FASTESTVPN:-${EA_ENABLE_FASTESTVPN:-0}}"
if [[ "${EA_ENABLE_FASTESTVPN:-0}" == "1" ]]; then
  enable_fastestvpn="1"
fi
enable_cloudflared="${PROPERTYQUARRY_ENABLE_CLOUDFLARED:-${EA_ENABLE_CLOUDFLARED:-auto}}"
run_runtime_hard_exit_gates="${PROPERTYQUARRY_RUN_RUNTIME_HARD_EXIT_GATES:-${EA_RUN_RUNTIME_HARD_EXIT_GATES:-1}}"
allow_dirty_worktree="${PROPERTYQUARRY_DEPLOY_ALLOW_DIRTY_WORKTREE:-${EA_DEPLOY_ALLOW_DIRTY_WORKTREE:-0}}"
cf_tunnel_token_name="${PROPERTYQUARRY_CF_TUNNEL_TOKEN:-}"
PYTHON_BIN="${PYTHON_BIN:-}"
if [[ -z "${PYTHON_BIN}" ]]; then
  if [[ -x "${APP_ROOT}/.venv/bin/python" ]]; then
    PYTHON_BIN="${APP_ROOT}/.venv/bin/python"
  else
    PYTHON_BIN="python3"
  fi
fi

while [[ $# -gt 0 ]]; do
  case "$1" in
    --help|-h)
      cat <<'EOF'
Usage:
  bash scripts/deploy.sh [--compose-override <file>]...

Options:
  --compose-override <file>  Layer an extra compose override onto the deploy topology.

Environment:
  PROPERTYQUARRY_MEMORY_ONLY=1            Deploy API service using docker-compose.memory.yml override.
  PROPERTYQUARRY_BOOTSTRAP_DB=1           Run db bootstrap after deploy (ignored if PROPERTYQUARRY_MEMORY_ONLY=1).
  PROPERTYQUARRY_ENABLE_FASTESTVPN=1      Layer docker-compose.fastestvpn.yml when FastestVPN *.ovpn profiles are present.
  PROPERTYQUARRY_ENABLE_CLOUDFLARED=1|0   Force Cloudflare tunnel override on or off (default: auto when PROPERTYQUARRY_CF_TUNNEL_TOKEN is set).
  PROPERTYQUARRY_CF_TUNNEL_TOKEN=<token>  PropertyQuarry Cloudflare tunnel token alias.
  PROPERTYQUARRY_RUN_RUNTIME_HARD_EXIT_GATES=1|0  Run runtime hard exit gates after health goes green (default: 1).
  TEABLE_API_KEY=...                      Verify and recover EA env/config artifacts from Teable before deploy.
  TEABLE_BASE_URL=https://app.teable.ai   Optional non-default Teable host for recovery.

Backward-compatible aliases:
  EA_MEMORY_ONLY, EA_BOOTSTRAP_DB, EA_ENABLE_FASTESTVPN, EA_ENABLE_CLOUDFLARED,
  EA_CF_TUNNEL_TOKEN, EA_RUN_RUNTIME_HARD_EXIT_GATES
  EA_RUN_RUNTIME_HARD_EXIT_GATES=1|0     Alias for PROPERTYQUARRY_RUN_RUNTIME_HARD_EXIT_GATES.
  EA_DEPLOY_ALLOW_DIRTY_WORKTREE=1|0     Allow deploy from a dirty git worktree (default: 0).
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

if [[ "${PROPERTYQUARRY_USE_LEGACY_STACK:-0}" != "1" ]]; then
  cat >&2 <<'EOF'
Refusing to deploy the inherited EA mega-stack from the standalone PropertyQuarry repo.

Use the hardened property-only runtime instead:
  docker compose -f docker-compose.property.yml up -d --build

If you intentionally need the legacy assistant topology for migration work, rerun with:
  PROPERTYQUARRY_USE_LEGACY_STACK=1 bash scripts/deploy.sh
EOF
  exit 2
fi

echo "== PropertyQuarry deploy: ${APP_ROOT} (project=${COMPOSE_PROJECT_NAME}) =="

if [[ -n "${TEABLE_API_KEY:-}" ]]; then
  echo "Ensuring EA env/config recovery artifacts from Teable before deploy."
  bash "${APP_ROOT}/scripts/bootstrap_from_teable.sh" --ensure-local >/dev/null
fi

if [[ ! -f "${APP_ROOT}/.env" ]]; then
  cp "${APP_ROOT}/.env.example" "${APP_ROOT}/.env"
  chmod 600 "${APP_ROOT}/.env"
  echo "Created .env from .env.example. Fill values and rerun."
  exit 1
fi

public_origin_line="$(grep -E '^(EA_PUBLIC_APP_BASE_URL|PROPERTYQUARRY_PUBLIC_BASE_URL)=' "${APP_ROOT}/.env" | tail -n1 || true)"
public_origin_value="${public_origin_line#*=}"
public_origin_value="${public_origin_value%/}"
if [[ -z "${public_origin_value}" ]]; then
  cat >&2 <<'EOF'
Refusing to deploy without a public runtime origin.

Set one of these in .env before deploy:
  EA_PUBLIC_APP_BASE_URL=https://assistant.example.test
  PROPERTYQUARRY_PUBLIC_BASE_URL=https://property.example.test

Release authority requires the deployed runtime to declare its public origin.
EOF
  exit 4
fi

if [[ "${allow_dirty_worktree}" != "1" ]] && [[ -n "$(git -C "${APP_ROOT}" status --short)" ]]; then
  cat >&2 <<'EOF'
Refusing to deploy from a dirty git worktree.

Commit or stash local changes first, or explicitly opt in with:
  EA_DEPLOY_ALLOW_DIRTY_WORKTREE=1 bash scripts/deploy.sh

Release authority requires a clean worktree for deployment claims.
EOF
  exit 5
fi

if [[ -z "${EA_DEPLOYMENT_ID:-${DEPLOYMENT_ID:-${RENDER_GIT_COMMIT:-}}}" ]]; then
  deploy_commit_sha="$(git -C "${APP_ROOT}" rev-parse HEAD 2>/dev/null || true)"
  deploy_commit_fragment="${deploy_commit_sha:0:12}"
  if [[ -z "${deploy_commit_fragment}" ]]; then
    deploy_commit_fragment="unknowncommit"
  fi
  export EA_DEPLOYMENT_ID="deploy-$(date -u +%Y%m%dT%H%M%SZ)-${deploy_commit_fragment}"
fi

database_url_line="$(grep -E '^DATABASE_URL=' "${APP_ROOT}/.env" | tail -n1 || true)"
database_url_value="${database_url_line#DATABASE_URL=}"
if [[ "${database_url_value}" == *"/ea_smoke_runtime" ]]; then
  cat >&2 <<'EOF'
Refusing to deploy with DATABASE_URL pointed at the isolated smoke database.

Fix .env first:
  DATABASE_URL=postgresql://postgres:...@ea-db:5432/ea

The smoke database `ea_smoke_runtime` is only for scripts/smoke_postgres.sh and
must never be used for a real deploy.
EOF
  exit 3
fi

if docker compose version >/dev/null 2>&1; then
  DC=(docker compose)
else
  DC=(docker-compose)
fi

COMPOSE_ARGS=(-f docker-compose.yml -f docker-compose.prod.yml)
FASTESTVPN_OVERLAY_ENABLED=0
CLOUDFLARED_OVERLAY_ENABLED=0
if [[ "${enable_fastestvpn}" == "1" ]]; then
  if find "${APP_ROOT}/vpn/fastestvpn" -maxdepth 1 -type f -name '*.ovpn' | grep -q .; then
    COMPOSE_ARGS+=(-f docker-compose.fastestvpn.yml)
    FASTESTVPN_OVERLAY_ENABLED=1
  else
    echo "EA_ENABLE_FASTESTVPN=1 but no FastestVPN *.ovpn profiles were found under ${APP_ROOT}/vpn/fastestvpn" >&2
    echo "PROPERTYQUARRY_ENABLE_FASTESTVPN=1 but no FastestVPN *.ovpn profiles were found under ${APP_ROOT}/vpn/fastestvpn" >&2
    exit 1
  fi
fi

for override in "${EXTRA_COMPOSE_OVERRIDES[@]}"; do
  if [[ ! -f "${APP_ROOT}/${override}" && ! -f "${override}" ]]; then
    echo "Compose override not found: ${override}" >&2
    exit 1
  fi
  COMPOSE_ARGS+=(-f "${override}")
done

sync_enabled_modes_from_overrides() {
  DEPLOY_ENABLED_MODES=()
  add_enabled_mode "${DEPLOY_PRIMARY_MODE}"
  local override
  local base
  for override in "${EXTRA_COMPOSE_OVERRIDES[@]}"; do
    base="$(basename "${override}")"
    case "${base}" in
      docker-compose.memorial.yml) add_enabled_mode "MEMORIAL" ;;
      docker-compose.provider-lab.yml) add_enabled_mode "PROVIDER_LAB" ;;
      docker-compose.property.yml) add_enabled_mode "PROPERTY" ;;
    esac
  done
}

whatsapp_web_session_overlay_enabled=0
for override in "${EXTRA_COMPOSE_OVERRIDES[@]}"; do
  if [[ "$(basename "${override}")" == "docker-compose.whatsapp-web-session.yml" ]]; then
    whatsapp_web_session_overlay_enabled=1
    break
  fi
done

if [[ "${memory_only}" != "1" ]]; then
  should_enable_cloudflared="${enable_cloudflared}"
  cloudflared_override="docker-compose.cloudflared.yml"
  if [[ "${should_enable_cloudflared}" == "1" || ( "${should_enable_cloudflared}" == "auto" && -n "${cf_tunnel_token_name}" ) || ( "${should_enable_cloudflared}" == "auto" && -n "$(grep -E '^(PROPERTYQUARRY_CF_TUNNEL_TOKEN|EA_CF_TUNNEL_TOKEN)=' "${APP_ROOT}/.env" | tail -n1 | cut -d= -f2- | tr -d '[:space:]')" ) ]]; then
    COMPOSE_ARGS+=(-f "${cloudflared_override}")
    CLOUDFLARED_OVERLAY_ENABLED=1
  fi
fi

compose() {
  COMPOSE_IGNORE_ORPHANS=1 "${DC[@]}" "${COMPOSE_ARGS[@]}" "$@"
}

normalize_mode() {
  printf '%s' "${1:-}" | tr '[:lower:]-' '[:upper:]_'
}

add_enabled_mode() {
  local mode
  mode="$(normalize_mode "$1")"
  [[ -n "${mode}" ]] || return 0
  local existing
  for existing in "${DEPLOY_ENABLED_MODES[@]:-}"; do
    if [[ "${existing}" == "${mode}" ]]; then
      return 0
    fi
  done
  DEPLOY_ENABLED_MODES+=("${mode}")
}

sync_enabled_modes_from_overrides

materialize_release_manifest() {
  local enabled_modes_csv=""
  local compose_files_csv=""
  local compose_overrides_csv=""
  if [[ "${#DEPLOY_ENABLED_MODES[@]}" -gt 0 ]]; then
    enabled_modes_csv="$(IFS=,; printf '%s' "${DEPLOY_ENABLED_MODES[*]}")"
  fi
  compose_files_csv="$(printf '%s\n' "${COMPOSE_ARGS[@]}" | awk 'prev == "-f" { print; } { prev = $0 }' | paste -sd, -)"
  if [[ "${#EXTRA_COMPOSE_OVERRIDES[@]}" -gt 0 ]]; then
    compose_overrides_csv="$(IFS=,; printf '%s' "${EXTRA_COMPOSE_OVERRIDES[*]}")"
  fi
  EA_DEPLOY_PRIMARY_MODE="${DEPLOY_PRIMARY_MODE}" \
  EA_DEPLOY_ENABLED_MODES="${enabled_modes_csv}" \
  EA_DEPLOY_COMPOSE_FILES="${compose_files_csv}" \
  EA_DEPLOY_COMPOSE_OVERRIDES="${compose_overrides_csv}" \
  "${PYTHON_BIN}" "${APP_ROOT}/scripts/materialize_release_manifest.py" --output "${RELEASE_MANIFEST_PATH}" >/dev/null
}

sync_telegram_webhooks() {
  local env_public_base
  local env_property_public_base
  local webhook_public_base
  local env_bot_registry
  local env_bot_token
  env_public_base="$(grep -E '^EA_PUBLIC_APP_BASE_URL=' "${APP_ROOT}/.env" | tail -n1 | cut -d= -f2- || true)"
  env_property_public_base="$(grep -E '^PROPERTYQUARRY_PUBLIC_BASE_URL=' "${APP_ROOT}/.env" | tail -n1 | cut -d= -f2- || true)"
  webhook_public_base="${env_public_base:-${env_property_public_base}}"
  env_bot_registry="$(grep -E '^EA_TELEGRAM_BOT_REGISTRY_JSON=' "${APP_ROOT}/.env" | tail -n1 | cut -d= -f2- || true)"
  env_bot_token="$(grep -E '^EA_TELEGRAM_BOT_TOKEN=' "${APP_ROOT}/.env" | tail -n1 | cut -d= -f2- || true)"
  if [[ -z "${env_public_base}" && -z "${env_property_public_base}" ]]; then
    return 0
  fi
  if [[ -z "${env_bot_registry}" && -z "${env_bot_token}" ]]; then
    return 0
  fi
  echo "Syncing Telegram webhooks to ${webhook_public_base}"
  "${PYTHON_BIN}" "${APP_ROOT}/scripts/bootstrap_telegram_bot.py" --env-file "${APP_ROOT}/.env" --all-bots --set-webhook >/dev/null
}

build_and_recreate_services() {
  local -a build_services=("$@")
  if [[ "${#build_services[@]}" -eq 0 ]]; then
    return 0
  fi

  compose build "${build_services[@]}"
  compose up -d --no-build ea-db
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
  if [[ "${restarting}" == "true" ]]; then
    return 1
  fi
  if [[ -n "${health}" && "${health}" != "healthy" ]]; then
    return 1
  fi
}

cd "${APP_ROOT}"
"${PYTHON_BIN}" "${APP_ROOT}/scripts/materialize_project_mode_manifests.py" >/dev/null
"${PYTHON_BIN}" "${APP_ROOT}/scripts/verify_project_mode_manifests.py" >/dev/null
if [[ "${memory_only}" == "1" ]]; then
  COMPOSE_ARGS=(-f docker-compose.yml -f docker-compose.memory.yml)
  TOPOLOGY_SERVICES=(ea-api)
  FAILURE_LOG_SERVICES=(ea-api)
  COMPOSE_IGNORE_ORPHANS=1 "${DC[@]}" -f docker-compose.yml -f docker-compose.memory.yml up -d --build ea-api
else
  RUNTIME_BUILD_SERVICES=(ea-teable-relay ea-api ea-responses-proxy ea-worker ea-scheduler)
  TOPOLOGY_SERVICES=(ea-teable-relay ea-api ea-responses-proxy ea-worker ea-scheduler ea-db)
  FAILURE_LOG_SERVICES=(ea-teable-relay ea-api ea-responses-proxy ea-worker ea-scheduler ea-db)
  if [[ "${whatsapp_web_session_overlay_enabled}" == "1" ]]; then
    RUNTIME_BUILD_SERVICES+=(ea-whatsapp-web-session ea-whatsapp-web-activator ea-whatsapp-web-action-processor ea-whatsapp-web-teable-sync)
    TOPOLOGY_SERVICES+=(ea-whatsapp-web-session ea-whatsapp-web-activator ea-whatsapp-web-action-processor ea-whatsapp-web-teable-sync)
    FAILURE_LOG_SERVICES+=(ea-whatsapp-web-session ea-whatsapp-web-activator ea-whatsapp-web-action-processor ea-whatsapp-web-teable-sync)
  fi
  if [[ "${CLOUDFLARED_OVERLAY_ENABLED}" == "1" ]]; then
    TOPOLOGY_SERVICES+=(ea-cloudflared)
    FAILURE_LOG_SERVICES+=(ea-cloudflared)
  fi
  if [[ "${FASTESTVPN_OVERLAY_ENABLED}" == "1" ]]; then
    FAILURE_LOG_SERVICES+=(ea-fastestvpn-proxy ea-fastestvpn-proxy-ie ea-fastestvpn-proxy-nl)
  fi
  build_and_recreate_services "${RUNTIME_BUILD_SERVICES[@]}"
  if [[ "${CLOUDFLARED_OVERLAY_ENABLED}" == "1" ]]; then
    echo "Refreshing Cloudflare tunnel after API recreate"
    compose up -d --no-build --no-deps --force-recreate ea-cloudflared
    for _ in $(seq 1 30); do
      if service_container_ready ea-cloudflared; then
        break
      fi
      sleep 1
    done
    if ! service_container_ready ea-cloudflared; then
      echo "Cloudflare tunnel failed to restart cleanly during deploy" >&2
      exit 1
    fi
  fi
fi

if [[ "${bootstrap_db}" == "1" ]]; then
  if [[ "${memory_only}" == "1" ]]; then
    echo "PROPERTYQUARRY_BOOTSTRAP_DB=1 ignored because PROPERTYQUARRY_MEMORY_ONLY=1"
  else
    echo "PROPERTYQUARRY_BOOTSTRAP_DB=1 -> applying kernel migrations"
    bash "${APP_ROOT}/scripts/db_bootstrap.sh"
  fi
fi

HOST_PORT="$(grep -E '^EA_HOST_PORT=' "${APP_ROOT}/.env" | tail -n1 | cut -d= -f2- || true)"
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
    sync_telegram_webhooks
    "${PYTHON_BIN}" "${APP_ROOT}/scripts/materialize_ea_browser_workflow_proof.py" >/dev/null
    "${PYTHON_BIN}" "${APP_ROOT}/scripts/materialize_ea_flagship_release_gate.py" >/dev/null
    "${PYTHON_BIN}" "${APP_ROOT}/scripts/materialize_weekly_product_pulse.py" >/dev/null
    if [[ "${run_runtime_hard_exit_gates}" != "0" ]]; then
      bash "${APP_ROOT}/scripts/runtime_hard_exit_gates.sh"
    fi
    materialize_release_manifest
    verify_mode_args=(--mode "${DEPLOY_PRIMARY_MODE}")
    for enabled_mode in "${DEPLOY_ENABLED_MODES[@]}"; do
      verify_mode_args+=(--enabled-mode "${enabled_mode}")
    done
    for override in "${EXTRA_COMPOSE_OVERRIDES[@]}"; do
      verify_mode_args+=(--compose-override "${override}")
    done
    "${PYTHON_BIN}" "${APP_ROOT}/scripts/verify_release_manifest_runtime_mode.py" "${verify_mode_args[@]}" >/dev/null
    verify_artifact_args=()
    for enabled_mode in "${DEPLOY_ENABLED_MODES[@]}"; do
      verify_artifact_args+=(--enabled-mode "${enabled_mode}")
    done
    "${PYTHON_BIN}" "${APP_ROOT}/scripts/verify_release_manifest_artifact_plane.py" "${verify_artifact_args[@]}" >/dev/null
    if [[ "${CLOUDFLARED_OVERLAY_ENABLED}" == "1" ]]; then
      public_smoke_base_url="${PROPERTYQUARRY_PUBLIC_BASE_URL:-${EA_PUBLIC_APP_BASE_URL:-https://example.test}}"
      public_smoke_base_url="${public_smoke_base_url%/}"
      public_smoke_urls="${PROPERTYQUARRY_CLOUDFLARED_PUBLIC_SMOKE_URLS:-${EA_CLOUDFLARED_PUBLIC_SMOKE_URLS:-${public_smoke_base_url}/sign-in}}"
      for public_url in ${public_smoke_urls}; do
        for _public in $(seq 1 20); do
          if curl -fsS --max-time 10 "${public_url}" >/dev/null 2>&1; then
            break
          fi
          sleep 2
        done
        if ! curl -fsS --max-time 10 "${public_url}" >/dev/null 2>&1; then
          echo "Cloudflare public smoke failed: ${public_url}" >&2
          exit 1
        fi
      done
    fi
    echo "PropertyQuarry runtime healthy at http://localhost:${HOST_PORT} with ${TOPOLOGY_SERVICES[*]}"
    echo "Release manifest written to ${RELEASE_MANIFEST_PATH}"
    exit 0
  fi
  sleep 1
done

echo "Health check failed; dumping logs"
compose ps || true
compose logs --tail 200 "${FAILURE_LOG_SERVICES[@]}" || true
exit 1
