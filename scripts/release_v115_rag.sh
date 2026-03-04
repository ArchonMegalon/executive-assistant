#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-/docker/EA}"
SQL_FILE="$ROOT/ea/schema/20260303_v1_15_rag.sql"

if docker compose version >/dev/null 2>&1; then
  DC=(docker compose)
else
  DC=(docker-compose)
fi

echo "[v1.15] Applying RAG schema: $SQL_FILE"
docker exec -i ea-db sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < "$SQL_FILE"

echo "[v1.15] Building shared ea-os image and recreating worker/poller"
"${DC[@]}" build ea-api
"${DC[@]}" up -d --force-recreate ea-worker ea-poller

echo "[v1.15] Running retrieval and prompt-safety tests"
"$ROOT/scripts/run_v115_retrieval_security_tests.sh"
"$ROOT/scripts/run_v115_prompt_injection_tests.sh"
if [[ "${EA_SKIP_FULL_GATES:-0}" != "1" ]]; then
  echo "[v1.15] Running full docker gate suite"
  "$ROOT/scripts/docker_e2e.sh"
else
  echo "[v1.15] Skipping full docker gate suite (EA_SKIP_FULL_GATES=1)"
fi

echo "[v1.15] DONE"
