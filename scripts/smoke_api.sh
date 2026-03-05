#!/usr/bin/env bash
set -euo pipefail

EA_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

HOST_PORT="${EA_HOST_PORT:-}"
if [[ -z "${HOST_PORT}" && -f "${EA_ROOT}/.env" ]]; then
  HOST_PORT="$(grep -E '^EA_HOST_PORT=' "${EA_ROOT}/.env" | tail -n1 | cut -d= -f2- || true)"
fi
HOST_PORT="${HOST_PORT:-8090}"
BASE="http://localhost:${HOST_PORT}"

echo "== smoke: health =="
curl -fsS "${BASE}/health" >/dev/null
echo "health ok"

echo "== smoke: rewrite =="
REWRITE_JSON="$(curl -fsS -X POST "${BASE}/v1/rewrite/artifact" -H 'content-type: application/json' -d '{"text":"smoke run"}')"
echo "${REWRITE_JSON}"
SESSION_ID="$(python3 -c 'import json,sys; print(json.loads(sys.stdin.read()).get("execution_session_id",""))' <<<"${REWRITE_JSON}")"
if [[ -z "${SESSION_ID}" ]]; then
  echo "missing execution_session_id from rewrite response" >&2
  exit 1
fi

echo "== smoke: session + policy =="
curl -fsS "${BASE}/v1/rewrite/sessions/${SESSION_ID}" >/dev/null
curl -fsS "${BASE}/v1/policy/decisions/recent?session_id=${SESSION_ID}&limit=5" >/dev/null
echo "session/policy ok"

echo "== smoke: blocked policy path =="
BLOCKED_PAYLOAD="$(mktemp)"
printf '{"text":"%s"}' "$(python3 - <<'PY'
print("x" * 20001)
PY
)" > "${BLOCKED_PAYLOAD}"
BLOCKED_CODE="$(curl -sS -o /tmp/ea_blocked_policy_resp.json -w '%{http_code}' -X POST "${BASE}/v1/rewrite/artifact" -H 'content-type: application/json' --data-binary @"${BLOCKED_PAYLOAD}")"
rm -f "${BLOCKED_PAYLOAD}"
if [[ "${BLOCKED_CODE}" != "403" ]]; then
  echo "expected 403 for blocked policy path; got ${BLOCKED_CODE}" >&2
  cat /tmp/ea_blocked_policy_resp.json >&2 || true
  exit 1
fi
echo "blocked policy path ok"

echo "== smoke: observations =="
curl -fsS -X POST "${BASE}/v1/observations/ingest" -H 'content-type: application/json' \
  -d '{"principal_id":"exec-1","channel":"email","event_type":"thread.opened","payload":{"subject":"Board prep"}}' >/dev/null
curl -fsS "${BASE}/v1/observations/recent?limit=5" >/dev/null
echo "observations ok"

echo "== smoke: outbox =="
DELIVERY_JSON="$(curl -fsS -X POST "${BASE}/v1/delivery/outbox" -H 'content-type: application/json' -d '{"channel":"slack","recipient":"U1","content":"Draft ready","metadata":{"priority":"high"}}')"
DELIVERY_ID="$(python3 -c 'import json,sys; print(json.loads(sys.stdin.read()).get("delivery_id",""))' <<<"${DELIVERY_JSON}")"
if [[ -z "${DELIVERY_ID}" ]]; then
  echo "missing delivery_id from outbox response" >&2
  exit 1
fi
curl -fsS "${BASE}/v1/delivery/outbox/pending?limit=5" >/dev/null
curl -fsS -X POST "${BASE}/v1/delivery/outbox/${DELIVERY_ID}/sent" >/dev/null
echo "outbox ok"

echo "== smoke: telegram adapter =="
curl -fsS -X POST "${BASE}/v1/channels/telegram/ingest" -H 'content-type: application/json' \
  -d '{"update":{"message":{"chat":{"id":42},"text":"hello","message_id":7,"date":123}}}' >/dev/null
echo "telegram adapter ok"

echo "smoke complete"
