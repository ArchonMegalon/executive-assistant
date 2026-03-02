#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-/docker/EA}"
SQL_FILE="$ROOT/ea/schema/20260302_v1_13_onboarding.sql"

if docker compose version >/dev/null 2>&1; then
  DC=(docker compose)
else
  DC=(docker-compose)
fi

echo "[v1.13] Applying onboarding schema: $SQL_FILE"
docker exec -i ea-db sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < "$SQL_FILE"

echo "[v1.13] Building shared ea-os image and recreating worker/poller"
"${DC[@]}" build ea-api
"${DC[@]}" up -d --force-recreate ea-worker ea-poller

echo "[v1.13] Running smoke checks"
"$ROOT/scripts/run_v113_smoke.sh"
"$ROOT/scripts/run_ssrf_negative_tests.sh"

echo "[v1.13] DONE"
