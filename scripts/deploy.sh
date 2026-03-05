#!/usr/bin/env bash
set -euo pipefail

EA_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "== EA rewrite deploy: ${EA_ROOT} =="

if [[ ! -f "${EA_ROOT}/.env" ]]; then
  cp "${EA_ROOT}/.env.example" "${EA_ROOT}/.env"
  chmod 600 "${EA_ROOT}/.env"
  echo "Created .env from .env.example. Fill values and rerun."
  exit 1
fi

cd "${EA_ROOT}"
docker compose up -d --build

if [[ "${EA_BOOTSTRAP_DB:-0}" == "1" ]]; then
  echo "EA_BOOTSTRAP_DB=1 -> applying kernel migrations"
  bash "${EA_ROOT}/scripts/db_bootstrap.sh"
fi

HOST_PORT="$(grep -E '^EA_HOST_PORT=' "${EA_ROOT}/.env" | tail -n1 | cut -d= -f2- || true)"
HOST_PORT="${HOST_PORT:-8090}"

for _ in $(seq 1 60); do
  if curl -fsS "http://localhost:${HOST_PORT}/health" >/dev/null 2>&1; then
    echo "EA rewrite baseline healthy at http://localhost:${HOST_PORT}"
    exit 0
  fi
  sleep 1
done

echo "Health check failed; dumping logs"
docker compose logs --tail 200 ea-api ea-db || true
exit 1
