#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-/docker/EA}"
SQL_FILE="$ROOT/ea/schema/20260303_v1_14_trust.sql"

if docker compose version >/dev/null 2>&1; then
  DC=(docker compose)
else
  DC=(docker-compose)
fi

echo "[v1.14] Applying trust-layer schema: $SQL_FILE"
docker exec -i ea-db sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < "$SQL_FILE"

echo "[v1.14] Building shared ea-os image and recreating worker/poller"
"${DC[@]}" build ea-api
"${DC[@]}" up -d --force-recreate ea-worker ea-poller

echo "[v1.14] Running trust-layer tests"
"$ROOT/scripts/run_v114_replay_and_dlq_tests.sh"
if [[ "${EA_SKIP_FULL_GATES:-0}" != "1" ]]; then
  echo "[v1.14] Running full docker gate suite"
  "$ROOT/scripts/docker_e2e.sh"
else
  echo "[v1.14] Skipping full docker gate suite (EA_SKIP_FULL_GATES=1)"
fi

echo "[v1.14] DONE"
