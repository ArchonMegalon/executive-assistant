#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-/docker/EA}"

if docker compose version >/dev/null 2>&1; then
  DC=(docker compose)
else
  DC=(docker-compose)
fi

echo "[SMOKE][v1.12.6] Schema table presence"
docker exec -i ea-db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT tablename FROM pg_tables WHERE schemaname='\''public'\'' AND tablename IN ('\''travel_place_history'\'','\''travel_video_specs'\'','\''avomap_jobs'\'','\''avomap_assets'\'','\''avomap_credit_ledger'\'') ORDER BY tablename"'

echo "[SMOKE][v1.12.6] Host compile + smoke"
python3 -m py_compile \
  "$ROOT/ea/app/integrations/avomap/specs.py" \
  "$ROOT/ea/app/integrations/avomap/detector.py" \
  "$ROOT/ea/app/integrations/avomap/sanitizer.py" \
  "$ROOT/ea/app/integrations/avomap/security.py" \
  "$ROOT/ea/app/integrations/avomap/service.py" \
  "$ROOT/ea/app/integrations/avomap/finalize.py" \
  "$ROOT/ea/app/integrations/routing/service.py" \
  "$ROOT/ea/app/telegram/media.py" \
  "$ROOT/ea/app/intake/browseract.py" \
  "$ROOT/ea/app/workers/event_worker.py" \
  "$ROOT/tests/smoke_v1_12_6.py"
python3 "$ROOT/tests/smoke_v1_12_6.py"

echo "[SMOKE][v1.12.6] Container E2E"
docker cp "$ROOT/tests/e2e_v1_12_6_avomap.py" ea-api:/tmp/e2e_v1_12_6_avomap.py
docker cp "$ROOT/tests/e2e_browseract_http_ingress.py" ea-api:/tmp/e2e_browseract_http_ingress.py
docker cp "$ROOT/tests/e2e_browseract_http_to_ready_asset.py" ea-api:/tmp/e2e_browseract_http_to_ready_asset.py
"${DC[@]}" exec -T ea-api sh -lc "PYTHONPATH=/app python /tmp/e2e_v1_12_6_avomap.py"
"${DC[@]}" exec -T ea-api sh -lc "PYTHONPATH=/app python /tmp/e2e_browseract_http_ingress.py"
"${DC[@]}" exec -T ea-api sh -lc "PYTHONPATH=/app python /tmp/e2e_browseract_http_to_ready_asset.py"

echo "[SMOKE][v1.12.6] PASS"
