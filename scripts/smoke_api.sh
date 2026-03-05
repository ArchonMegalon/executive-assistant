#!/usr/bin/env bash
set -euo pipefail

EA_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  cat <<'EOF'
Usage:
  bash scripts/smoke_api.sh

Runs end-to-end HTTP smoke checks for liveness/readiness/version,
rewrite/session/policy/approvals, observations, delivery outbox, and telegram adapter.

Auth:
  If EA_API_TOKEN is set, the script sends Authorization: Bearer <token>.

Exit codes:
  11 missing execution_session_id
  12 blocked-policy contract mismatch
  13 missing delivery_id
EOF
  exit 0
fi

fail() {
  local code="$1"
  local msg="$2"
  echo "${msg}" >&2
  exit "${code}"
}

HOST_PORT="${EA_HOST_PORT:-}"
if [[ -z "${HOST_PORT}" && -f "${EA_ROOT}/.env" ]]; then
  HOST_PORT="$(grep -E '^EA_HOST_PORT=' "${EA_ROOT}/.env" | tail -n1 | cut -d= -f2- || true)"
fi
HOST_PORT="${HOST_PORT:-8090}"
BASE="http://localhost:${HOST_PORT}"
AUTH_ARGS=()
if [[ -n "${EA_API_TOKEN:-}" ]]; then
  AUTH_ARGS=(-H "Authorization: Bearer ${EA_API_TOKEN}")
fi

echo "== smoke: health =="
curl -fsS "${BASE}/health" >/dev/null
curl -fsS "${BASE}/health/live" >/dev/null
curl -fsS "${BASE}/health/ready" >/dev/null
curl -fsS "${BASE}/version" >/dev/null
echo "health/version ok"

echo "== smoke: rewrite =="
REWRITE_JSON="$(curl -fsS -X POST "${BASE}/v1/rewrite/artifact" "${AUTH_ARGS[@]}" -H 'content-type: application/json' -d '{"text":"smoke run"}')"
echo "${REWRITE_JSON}"
SESSION_ID="$(python3 -c 'import json,sys; print(json.loads(sys.stdin.read()).get("execution_session_id",""))' <<<"${REWRITE_JSON}")"
if [[ -z "${SESSION_ID}" ]]; then
  fail 11 "missing execution_session_id from rewrite response"
fi

echo "== smoke: session + policy =="
curl -fsS "${BASE}/v1/rewrite/sessions/${SESSION_ID}" "${AUTH_ARGS[@]}" >/dev/null
curl -fsS "${BASE}/v1/policy/decisions/recent?session_id=${SESSION_ID}&limit=5" "${AUTH_ARGS[@]}" >/dev/null
curl -fsS "${BASE}/v1/policy/approvals/pending?limit=5" "${AUTH_ARGS[@]}" >/dev/null
curl -fsS "${BASE}/v1/policy/approvals/history?limit=5" "${AUTH_ARGS[@]}" >/dev/null
echo "session/policy ok"

echo "== smoke: blocked policy path =="
BLOCKED_PAYLOAD="$(mktemp)"
printf '{"text":"%s"}' "$(python3 - <<'PY'
print("x" * 20001)
PY
)" > "${BLOCKED_PAYLOAD}"
BLOCKED_CODE="$(curl -sS -o /tmp/ea_blocked_policy_resp.json -w '%{http_code}' -X POST "${BASE}/v1/rewrite/artifact" "${AUTH_ARGS[@]}" -H 'content-type: application/json' --data-binary @"${BLOCKED_PAYLOAD}")"
rm -f "${BLOCKED_PAYLOAD}"
if [[ "${BLOCKED_CODE}" != "403" ]]; then
  echo "expected 403 for blocked policy path; got ${BLOCKED_CODE}" >&2
  cat /tmp/ea_blocked_policy_resp.json >&2 || true
  fail 12 "blocked policy contract mismatch"
fi
BLOCKED_REASON="$(python3 - <<'PY'
import json
from pathlib import Path
path = Path("/tmp/ea_blocked_policy_resp.json")
if not path.exists():
    print("")
    raise SystemExit(0)
try:
    body = json.loads(path.read_text())
except Exception:
    print("")
    raise SystemExit(0)
print(((body.get("error") or {}).get("code") or ""))
PY
)"
if [[ "${BLOCKED_REASON}" != "policy_denied:input_too_large" ]]; then
  echo "expected blocked policy code policy_denied:input_too_large; got ${BLOCKED_REASON}" >&2
  cat /tmp/ea_blocked_policy_resp.json >&2 || true
  fail 12 "blocked policy contract mismatch"
fi
echo "blocked policy path ok"

echo "== smoke: observations =="
curl -fsS -X POST "${BASE}/v1/observations/ingest" "${AUTH_ARGS[@]}" -H 'content-type: application/json' \
  -d '{"principal_id":"exec-1","channel":"email","event_type":"thread.opened","payload":{"subject":"Board prep"}}' >/dev/null
curl -fsS "${BASE}/v1/observations/recent?limit=5" "${AUTH_ARGS[@]}" >/dev/null
echo "observations ok"

echo "== smoke: outbox =="
DELIVERY_JSON="$(curl -fsS -X POST "${BASE}/v1/delivery/outbox" "${AUTH_ARGS[@]}" -H 'content-type: application/json' -d '{"channel":"slack","recipient":"U1","content":"Draft ready","metadata":{"priority":"high"}}')"
DELIVERY_ID="$(python3 -c 'import json,sys; print(json.loads(sys.stdin.read()).get("delivery_id",""))' <<<"${DELIVERY_JSON}")"
if [[ -z "${DELIVERY_ID}" ]]; then
  fail 13 "missing delivery_id from outbox response"
fi
curl -fsS "${BASE}/v1/delivery/outbox/pending?limit=5" "${AUTH_ARGS[@]}" >/dev/null
curl -fsS -X POST "${BASE}/v1/delivery/outbox/${DELIVERY_ID}/sent" "${AUTH_ARGS[@]}" >/dev/null
echo "outbox ok"

echo "== smoke: telegram adapter =="
curl -fsS -X POST "${BASE}/v1/channels/telegram/ingest" "${AUTH_ARGS[@]}" -H 'content-type: application/json' \
  -d '{"update":{"message":{"chat":{"id":42},"text":"hello","message_id":7,"date":123}}}' >/dev/null
echo "telegram adapter ok"

echo "smoke complete"
