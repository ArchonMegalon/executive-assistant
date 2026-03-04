#!/usr/bin/env bash
set -euo pipefail
EA_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOST_PORT="$(grep -E '^EA_HOST_PORT=' "${EA_ROOT}/.env" | tail -n1 | cut -d= -f2- || true)"
HOST_PORT="${HOST_PORT:-8090}"
OP_TOKEN="$(grep -E '^EA_OPERATOR_TOKEN=' "${EA_ROOT}/.env" | tail -n1 | cut -d= -f2- || true)"
SCAN_MINUTES="${EA_LOG_SCAN_MINUTES:-20}"
SCAN_PATTERN='error|exception|traceback|fatal|deadlock|panic|failed|sentinel|api_key_invalid|api key expired|permission denied'
IGNORE_CONTAINERS="${EA_LOG_SCAN_IGNORE_CONTAINERS:-tautulli}"

echo "== ps =="
docker compose ps

echo -e "\n== ea-db logs =="
docker logs --since "${SCAN_MINUTES}m" ea-db

echo -e "\n== EA service logs =="
docker compose logs --tail 240 ea-api ea-worker ea-poller ea-outbox ea-event-worker || true

echo -e "\n== /health =="
curl -s "http://localhost:${HOST_PORT}/health" || true
echo

echo -e "\n== /debug/audit (50) =="
if [[ -z "${OP_TOKEN}" || "${OP_TOKEN}" == "CHANGE_ME_LONG_RANDOM_OPERATOR" ]]; then
  echo "EA_OPERATOR_TOKEN not set; skipping /debug/audit."
else
  curl -s -H "Authorization: Bearer ${OP_TOKEN}" "http://localhost:${HOST_PORT}/debug/audit?limit=50" | head -c 8000 || true
  echo
fi

echo -e "\n== EA stack: error scan (last ${SCAN_MINUTES}m) =="
for c in ea-api ea-worker ea-poller ea-outbox ea-event-worker ea-teable-sync ea-db; do
  hits="$(docker logs --since "${SCAN_MINUTES}m" "${c}" 2>&1 | grep -Ei "${SCAN_PATTERN}" || true)"
  if [[ -n "${hits}" ]]; then
    echo
    echo "----- ${c} -----"
    echo "${hits}" | tail -n 60
  fi
done

echo -e "\n== all running containers: error scan (last ${SCAN_MINUTES}m) =="
for c in $(docker ps --format '{{.Names}}'); do
  if [[ " ${IGNORE_CONTAINERS} " == *" ${c} "* ]]; then
    continue
  fi
  hits="$(docker logs --since "${SCAN_MINUTES}m" "${c}" 2>&1 | grep -Ei "${SCAN_PATTERN}" || true)"
  if [[ -n "${hits}" ]]; then
    echo
    echo "----- ${c} -----"
    echo "${hits}" | tail -n 40
  fi
done
