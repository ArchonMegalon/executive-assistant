#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

if docker compose version >/dev/null 2>&1; then
  DC=(docker compose -f docker-compose.property.yml)
else
  DC=(docker-compose -f docker-compose.property.yml)
fi

export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-propertyquarry_ci_postgres}"
export EA_HOST_PORT="${EA_HOST_PORT:-8090}"
base="http://localhost:${EA_HOST_PORT}"
created_env=0
env_had_file=0
env_backup=""

if [[ ! -f "${ROOT}/.env" ]]; then
  cp "${ROOT}/.env.example" "${ROOT}/.env"
  chmod 600 "${ROOT}/.env"
  created_env=1
else
  env_had_file=1
  env_backup="$(mktemp)"
  cp "${ROOT}/.env" "${env_backup}"
fi

cleanup() {
  "${DC[@]}" down -v >/dev/null 2>&1 || true
  if [[ "${env_had_file}" == "1" && -n "${env_backup}" && -f "${env_backup}" ]]; then
    cp "${env_backup}" "${ROOT}/.env"
    rm -f "${env_backup}"
  fi
  if [[ "${created_env}" == "1" ]]; then
    rm -f "${ROOT}/.env"
  fi
}
trap cleanup EXIT

set_env_value() {
  local key="$1"
  local value="$2"
  if grep -q "^${key}=" "${ROOT}/.env"; then
    sed -i "s|^${key}=.*$|${key}=${value}|" "${ROOT}/.env"
  else
    echo "${key}=${value}" >> "${ROOT}/.env"
  fi
}

set_env_value "POSTGRES_PASSWORD" "${POSTGRES_PASSWORD}"
set_env_value "DATABASE_URL" ""
set_env_value "EA_RUNTIME_MODE" "prod"
set_env_value "EA_ALLOW_LOOPBACK_NO_AUTH" "0"
set_env_value "EA_API_TOKEN" "propertyquarry-ci-api-token"
set_env_value "EA_SIGNING_SECRET" "propertyquarry-ci-signing-secret"
set_env_value "PROPERTYQUARRY_ENABLE_PUBLIC_SIDE_SURFACES" "0"
set_env_value "PROPERTYQUARRY_ENABLE_PUBLIC_RESULTS" "0"
set_env_value "PROPERTYQUARRY_ENABLE_PUBLIC_TOURS" "0"
set_env_value "PROPERTYQUARRY_ENABLE_LEGACY_RUNTIME_SURFACES" "0"

echo "== property-postgres-smoke: boot property compose =="
"${DC[@]}" up -d --build propertyquarry-db propertyquarry-api

echo "== property-postgres-smoke: wait for readiness =="
ready_reason=""
for _ in $(seq 1 90); do
  ready_json="$(curl -sS --connect-timeout 2 --max-time 5 "${base}/health/ready" 2>/dev/null || true)"
  ready_reason="$(python3 -c 'import json,sys
raw=(sys.argv[1] if len(sys.argv)>1 else "").strip()
try:
    payload=json.loads(raw)
except Exception:
    print("")
    raise SystemExit(0)
print(str(payload.get("reason") or "")) if isinstance(payload, dict) else print("")' "${ready_json}")"
  if [[ "${ready_reason}" == "postgres_ready" ]]; then
    break
  fi
  sleep 1
done

if [[ "${ready_reason}" != "postgres_ready" ]]; then
  echo "expected postgres_ready, got ${ready_reason:-empty}" >&2
  docker logs --tail 160 propertyquarry-api >&2 || true
  exit 31
fi

echo "== property-postgres-smoke: verify public brand and auth boundary =="
landing="$(curl -sS --connect-timeout 2 --max-time 5 "${base}/")"
if ! grep -q "PropertyQuarry" <<<"${landing}"; then
  echo "landing page did not render PropertyQuarry branding" >&2
  exit 32
fi

app_code="$(curl -sS --connect-timeout 2 --max-time 5 -o /tmp/propertyquarry_app_probe.html -w '%{http_code}' "${base}/app/properties" || true)"
if [[ "${app_code}" != "401" && "${app_code}" != "303" ]]; then
  echo "expected authenticated app boundary, got HTTP ${app_code}" >&2
  cat /tmp/propertyquarry_app_probe.html >&2 || true
  exit 33
fi

version_json="$(curl -sS --connect-timeout 2 --max-time 5 "${base}/version")"
storage_backend="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("storage_backend",""))' "${version_json}")"
if [[ "${storage_backend}" != "postgres" ]]; then
  echo "expected postgres storage backend, got ${storage_backend}" >&2
  exit 34
fi

echo "property-postgres-smoke complete"
