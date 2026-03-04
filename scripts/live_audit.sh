#!/usr/bin/env bash
set -euo pipefail

EA_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${EA_ROOT}"

echo "== Live Audit: docker_e2e =="
bash scripts/docker_e2e.sh

echo
echo "== Live Audit: runbook (all container logs) =="
bash scripts/runbook.sh

echo
echo "== Live Audit: EA-focused last-5m error gate =="
EA_DB_ERRS="$(docker logs ea-db --since 5m 2>&1 | grep -Ei 'undefinedcolumn|updated_at.*does not exist|relation \".*\" does not exist|fatal|deadlock' || true)"
EA_WORKER_ERRS="$(docker logs ea-worker --since 5m 2>&1 | grep -Ei 'traceback|worker error|undefinedcolumn|fatal|deadlock' || true)"
EA_OUTBOX_ERRS="$(docker logs ea-outbox --since 5m 2>&1 | grep -Ei \"can't parse entities|unsupported start tag|http 400|traceback|fatal\" || true)"
EA_API_ERRS="$(docker logs ea-api --since 5m 2>&1 | grep -Ei 'sentinel|deadlock|traceback|fatal' || true)"

if [[ -n "${EA_DB_ERRS}" || -n "${EA_WORKER_ERRS}" || -n "${EA_OUTBOX_ERRS}" || -n "${EA_API_ERRS}" ]]; then
  echo "FAIL: EA-focused log gate found recent errors"
  [[ -n "${EA_DB_ERRS}" ]] && echo "--- ea-db ---" && echo "${EA_DB_ERRS}"
  [[ -n "${EA_WORKER_ERRS}" ]] && echo "--- ea-worker ---" && echo "${EA_WORKER_ERRS}"
  [[ -n "${EA_OUTBOX_ERRS}" ]] && echo "--- ea-outbox ---" && echo "${EA_OUTBOX_ERRS}"
  [[ -n "${EA_API_ERRS}" ]] && echo "--- ea-api ---" && echo "${EA_API_ERRS}"
  exit 1
fi

echo "PASS: live audit completed with clean EA-focused recent logs"
