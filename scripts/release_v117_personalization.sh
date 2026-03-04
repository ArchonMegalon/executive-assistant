#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-/docker/EA}"
SQL_FILE="$ROOT/ea/schema/20260303_v1_17_personalization.sql"

if docker compose version >/dev/null 2>&1; then
  DC=(docker compose)
else
  DC=(docker-compose)
fi

echo "[v1.17] Applying personalization schema: $SQL_FILE"
docker exec -i ea-db sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < "$SQL_FILE"

echo "[v1.17] Building shared ea-os image and recreating services"
"${DC[@]}" build ea-api
"${DC[@]}" up -d --force-recreate ea-api ea-worker ea-poller ea-outbox ea-event-worker

echo "[v1.17] Running smoke checks"
python3 "$ROOT/tests/smoke_v1_17.py"

echo "[v1.17] DONE"
