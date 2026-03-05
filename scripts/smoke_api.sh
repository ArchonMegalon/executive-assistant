#!/usr/bin/env bash
set -euo pipefail

EA_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  cat <<'EOF'
Usage:
  bash scripts/smoke_api.sh

Runs end-to-end HTTP smoke checks for liveness/readiness/version,
rewrite/session/policy/approvals, observations, delivery outbox, channel adapters,
tool/connector registry endpoints, task-contract endpoints, plan compile endpoint,
and memory candidate/item/entity/relationship/commitment/authority-binding/delivery-preference/follow-up/deadline-window/stakeholder/decision-window endpoints.

Auth:
  If EA_API_TOKEN is set, the script sends Authorization: Bearer <token>.

Exit codes:
  11 missing execution_session_id
  12 blocked-policy contract mismatch
  13 missing resource id from runtime response
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
DELIVERY_JSON="$(curl -fsS -X POST "${BASE}/v1/delivery/outbox" "${AUTH_ARGS[@]}" -H 'content-type: application/json' -d '{"channel":"slack","recipient":"U1","content":"Draft ready","metadata":{"priority":"high"},"idempotency_key":"smoke-delivery-1"}')"
DELIVERY_ID="$(python3 -c 'import json,sys; print(json.loads(sys.stdin.read()).get("delivery_id",""))' <<<"${DELIVERY_JSON}")"
if [[ -z "${DELIVERY_ID}" ]]; then
  fail 13 "missing delivery_id from outbox response"
fi
curl -fsS -X POST "${BASE}/v1/delivery/outbox/${DELIVERY_ID}/failed" "${AUTH_ARGS[@]}" -H 'content-type: application/json' \
  -d '{"error":"temporary smoke failure","retry_in_seconds":0,"dead_letter":false}' >/dev/null
curl -fsS "${BASE}/v1/delivery/outbox/pending?limit=5" "${AUTH_ARGS[@]}" >/dev/null
curl -fsS -X POST "${BASE}/v1/delivery/outbox/${DELIVERY_ID}/sent" "${AUTH_ARGS[@]}" >/dev/null
echo "outbox ok"

echo "== smoke: telegram adapter =="
curl -fsS -X POST "${BASE}/v1/channels/telegram/ingest" "${AUTH_ARGS[@]}" -H 'content-type: application/json' \
  -d '{"update":{"message":{"chat":{"id":42},"text":"hello","message_id":7,"date":123}}}' >/dev/null
echo "telegram adapter ok"

echo "== smoke: tools and connectors =="
curl -fsS -X POST "${BASE}/v1/tools/registry" "${AUTH_ARGS[@]}" -H 'content-type: application/json' \
  -d '{"tool_name":"email.send","version":"v1","input_schema_json":{"type":"object"},"output_schema_json":{"type":"object"},"policy_json":{"risk":"medium"},"allowed_channels":["email"],"approval_default":"manager","enabled":true}' >/dev/null
curl -fsS "${BASE}/v1/tools/registry?limit=5" "${AUTH_ARGS[@]}" >/dev/null
CONNECTOR_JSON="$(curl -fsS -X POST "${BASE}/v1/connectors/bindings" "${AUTH_ARGS[@]}" -H 'content-type: application/json' \
  -d '{"principal_id":"exec-1","connector_name":"gmail","external_account_ref":"acct-1","scope_json":{"scopes":["mail.readonly"]},"auth_metadata_json":{"provider":"google"},"status":"enabled"}')"
BINDING_ID="$(python3 -c 'import json,sys; print(json.loads(sys.stdin.read()).get("binding_id",""))' <<<"${CONNECTOR_JSON}")"
if [[ -n "${BINDING_ID}" ]]; then
  curl -fsS -X POST "${BASE}/v1/connectors/bindings/${BINDING_ID}/status" "${AUTH_ARGS[@]}" -H 'content-type: application/json' -d '{"status":"disabled"}' >/dev/null
fi
curl -fsS "${BASE}/v1/connectors/bindings?principal_id=exec-1&limit=5" "${AUTH_ARGS[@]}" >/dev/null
echo "tools/connectors ok"

echo "== smoke: task contracts =="
curl -fsS -X POST "${BASE}/v1/tasks/contracts" "${AUTH_ARGS[@]}" -H 'content-type: application/json' \
  -d '{"task_key":"rewrite_text","deliverable_type":"rewrite_note","default_risk_class":"low","default_approval_class":"none","allowed_tools":["rewrite_store"],"evidence_requirements":[],"memory_write_policy":"reviewed_only","budget_policy_json":{"class":"low"}}' >/dev/null
curl -fsS "${BASE}/v1/tasks/contracts?limit=5" "${AUTH_ARGS[@]}" >/dev/null
curl -fsS "${BASE}/v1/tasks/contracts/rewrite_text" "${AUTH_ARGS[@]}" >/dev/null
echo "task contracts ok"

echo "== smoke: plans =="
curl -fsS -X POST "${BASE}/v1/plans/compile" "${AUTH_ARGS[@]}" -H 'content-type: application/json' \
  -d '{"task_key":"rewrite_text","principal_id":"exec-1","goal":"rewrite this text"}' >/dev/null
echo "plans ok"

echo "== smoke: memory =="
MEMORY_CANDIDATE_JSON="$(curl -fsS -X POST "${BASE}/v1/memory/candidates" "${AUTH_ARGS[@]}" -H 'content-type: application/json' \
  -d '{"principal_id":"exec-1","category":"stakeholder_pref","summary":"CEO prefers concise updates","fact_json":{"tone":"concise"},"source_session_id":"session-1","source_event_id":"event-1","source_step_id":"step-1","confidence":0.72,"sensitivity":"internal"}')"
MEMORY_CANDIDATE_ID="$(python3 -c 'import json,sys; print(json.loads(sys.stdin.read()).get("candidate_id",""))' <<<"${MEMORY_CANDIDATE_JSON}")"
if [[ -z "${MEMORY_CANDIDATE_ID}" ]]; then
  fail 13 "missing candidate_id from memory candidate response"
fi
MEMORY_PROMOTE_JSON="$(curl -fsS -X POST "${BASE}/v1/memory/candidates/${MEMORY_CANDIDATE_ID}/promote" "${AUTH_ARGS[@]}" -H 'content-type: application/json' \
  -d '{"reviewer":"smoke-operator","sharing_policy":"private"}')"
MEMORY_ITEM_ID="$(python3 -c 'import json,sys; body=json.loads(sys.stdin.read() or "{}"); print(((body.get("item") or {}).get("item_id")) or "")' <<<"${MEMORY_PROMOTE_JSON}")"
if [[ -z "${MEMORY_ITEM_ID}" ]]; then
  fail 13 "missing item_id from memory promote response"
fi
curl -fsS "${BASE}/v1/memory/candidates?limit=5&status=promoted" "${AUTH_ARGS[@]}" >/dev/null
curl -fsS "${BASE}/v1/memory/items?limit=5&principal_id=exec-1" "${AUTH_ARGS[@]}" >/dev/null
curl -fsS "${BASE}/v1/memory/items/${MEMORY_ITEM_ID}" "${AUTH_ARGS[@]}" >/dev/null
ENTITY_EXEC_JSON="$(curl -fsS -X POST "${BASE}/v1/memory/entities" "${AUTH_ARGS[@]}" -H 'content-type: application/json' \
  -d '{"principal_id":"exec-1","entity_type":"person","canonical_name":"Alex Executive","attributes_json":{"role":"executive"},"confidence":0.9,"status":"active"}')"
ENTITY_EXEC_ID="$(python3 -c 'import json,sys; print(json.loads(sys.stdin.read()).get("entity_id",""))' <<<"${ENTITY_EXEC_JSON}")"
if [[ -z "${ENTITY_EXEC_ID}" ]]; then
  fail 13 "missing entity_id from memory entity response"
fi
ENTITY_STAKE_JSON="$(curl -fsS -X POST "${BASE}/v1/memory/entities" "${AUTH_ARGS[@]}" -H 'content-type: application/json' \
  -d '{"principal_id":"exec-1","entity_type":"person","canonical_name":"Sam Stakeholder","attributes_json":{"role":"board_member"},"confidence":0.88,"status":"active"}')"
ENTITY_STAKE_ID="$(python3 -c 'import json,sys; print(json.loads(sys.stdin.read()).get("entity_id",""))' <<<"${ENTITY_STAKE_JSON}")"
if [[ -z "${ENTITY_STAKE_ID}" ]]; then
  fail 13 "missing entity_id from second memory entity response"
fi
REL_JSON="$(curl -fsS -X POST "${BASE}/v1/memory/relationships" "${AUTH_ARGS[@]}" -H 'content-type: application/json' \
  -d "{\"principal_id\":\"exec-1\",\"from_entity_id\":\"${ENTITY_EXEC_ID}\",\"to_entity_id\":\"${ENTITY_STAKE_ID}\",\"relationship_type\":\"reports_to\",\"attributes_json\":{\"strength\":\"high\"},\"confidence\":0.75}")"
REL_ID="$(python3 -c 'import json,sys; print(json.loads(sys.stdin.read()).get("relationship_id",""))' <<<"${REL_JSON}")"
if [[ -z "${REL_ID}" ]]; then
  fail 13 "missing relationship_id from memory relationship response"
fi
COMMITMENT_JSON="$(curl -fsS -X POST "${BASE}/v1/memory/commitments" "${AUTH_ARGS[@]}" -H 'content-type: application/json' \
  -d '{"principal_id":"exec-1","title":"Send board follow-up","details":"Draft and send by Friday","status":"open","priority":"high","due_at":"2026-03-06T10:00:00+00:00","source_json":{"source":"smoke"}}')"
COMMITMENT_ID="$(python3 -c 'import json,sys; print(json.loads(sys.stdin.read()).get("commitment_id",""))' <<<"${COMMITMENT_JSON}")"
if [[ -z "${COMMITMENT_ID}" ]]; then
  fail 13 "missing commitment_id from memory commitment response"
fi
BINDING_JSON="$(curl -fsS -X POST "${BASE}/v1/memory/authority-bindings" "${AUTH_ARGS[@]}" -H 'content-type: application/json' \
  -d '{"principal_id":"exec-1","subject_ref":"assistant","action_scope":"calendar.write","approval_level":"manager","channel_scope":["email","slack"],"policy_json":{"quiet_hours_enforced":true},"status":"active"}')"
BINDING_ID="$(python3 -c 'import json,sys; print(json.loads(sys.stdin.read()).get("binding_id",""))' <<<"${BINDING_JSON}")"
if [[ -z "${BINDING_ID}" ]]; then
  fail 13 "missing binding_id from authority binding response"
fi
PREF_JSON="$(curl -fsS -X POST "${BASE}/v1/memory/delivery-preferences" "${AUTH_ARGS[@]}" -H 'content-type: application/json' \
  -d '{"principal_id":"exec-1","channel":"email","recipient_ref":"ceo@example.com","cadence":"urgent_only","quiet_hours_json":{"start":"22:00","end":"07:00"},"format_json":{"style":"concise"},"status":"active"}')"
PREF_ID="$(python3 -c 'import json,sys; print(json.loads(sys.stdin.read()).get("preference_id",""))' <<<"${PREF_JSON}")"
if [[ -z "${PREF_ID}" ]]; then
  fail 13 "missing preference_id from delivery preference response"
fi
curl -fsS "${BASE}/v1/memory/entities?limit=5&principal_id=exec-1" "${AUTH_ARGS[@]}" >/dev/null
curl -fsS "${BASE}/v1/memory/entities/${ENTITY_EXEC_ID}" "${AUTH_ARGS[@]}" >/dev/null
curl -fsS "${BASE}/v1/memory/relationships?limit=5&principal_id=exec-1" "${AUTH_ARGS[@]}" >/dev/null
curl -fsS "${BASE}/v1/memory/relationships/${REL_ID}" "${AUTH_ARGS[@]}" >/dev/null
curl -fsS "${BASE}/v1/memory/commitments?principal_id=exec-1&limit=5" "${AUTH_ARGS[@]}" >/dev/null
curl -fsS "${BASE}/v1/memory/commitments/${COMMITMENT_ID}?principal_id=exec-1" "${AUTH_ARGS[@]}" >/dev/null
curl -fsS "${BASE}/v1/memory/authority-bindings?principal_id=exec-1&limit=5" "${AUTH_ARGS[@]}" >/dev/null
curl -fsS "${BASE}/v1/memory/authority-bindings/${BINDING_ID}?principal_id=exec-1" "${AUTH_ARGS[@]}" >/dev/null
curl -fsS "${BASE}/v1/memory/delivery-preferences?principal_id=exec-1&limit=5" "${AUTH_ARGS[@]}" >/dev/null
curl -fsS "${BASE}/v1/memory/delivery-preferences/${PREF_ID}?principal_id=exec-1" "${AUTH_ARGS[@]}" >/dev/null
DEADLINE_JSON="$(curl -fsS -X POST "${BASE}/v1/memory/deadline-windows" "${AUTH_ARGS[@]}" -H 'content-type: application/json' \
  -d '{"principal_id":"exec-1","title":"Board prep delivery window","start_at":"2026-03-07T08:30:00+00:00","end_at":"2026-03-07T10:00:00+00:00","status":"open","priority":"high","notes":"Draft must be ready before board sync","source_json":{"source":"smoke"}}')"
WINDOW_ID="$(python3 -c 'import json,sys; print(json.loads(sys.stdin.read()).get("window_id",""))' <<<"${DEADLINE_JSON}")"
if [[ -z "${WINDOW_ID}" ]]; then
  fail 13 "missing window_id from deadline-window response"
fi
curl -fsS "${BASE}/v1/memory/deadline-windows?principal_id=exec-1&limit=5" "${AUTH_ARGS[@]}" >/dev/null
curl -fsS "${BASE}/v1/memory/deadline-windows/${WINDOW_ID}?principal_id=exec-1" "${AUTH_ARGS[@]}" >/dev/null
STAKEHOLDER_JSON="$(curl -fsS -X POST "${BASE}/v1/memory/stakeholders" "${AUTH_ARGS[@]}" -H 'content-type: application/json' \
  -d '{"principal_id":"exec-1","display_name":"Sam Stakeholder","channel_ref":"email:sam@example.com","authority_level":"approver","importance":"high","response_cadence":"fast","tone_pref":"diplomatic","sensitivity":"confidential","escalation_policy":"notify_exec","open_loops_json":{"board_follow_up":"open"},"friction_points_json":{"scheduling":"tight"},"last_interaction_at":"2026-03-06T15:30:00+00:00","status":"active","notes":"Needs concise summaries"}')"
STAKEHOLDER_ID="$(python3 -c 'import json,sys; print(json.loads(sys.stdin.read()).get("stakeholder_id",""))' <<<"${STAKEHOLDER_JSON}")"
if [[ -z "${STAKEHOLDER_ID}" ]]; then
  fail 13 "missing stakeholder_id from stakeholder response"
fi
curl -fsS "${BASE}/v1/memory/stakeholders?principal_id=exec-1&limit=5" "${AUTH_ARGS[@]}" >/dev/null
curl -fsS "${BASE}/v1/memory/stakeholders/${STAKEHOLDER_ID}?principal_id=exec-1" "${AUTH_ARGS[@]}" >/dev/null
DECISION_JSON="$(curl -fsS -X POST "${BASE}/v1/memory/decision-windows" "${AUTH_ARGS[@]}" -H 'content-type: application/json' \
  -d '{"principal_id":"exec-1","title":"Board response decision","context":"Choose timing and channel for reply","opens_at":"2026-03-06T08:00:00+00:00","closes_at":"2026-03-06T12:00:00+00:00","urgency":"high","authority_required":"exec","status":"open","notes":"Needs decision before board prep","source_json":{"source":"smoke"}}')"
DECISION_WINDOW_ID="$(python3 -c 'import json,sys; print(json.loads(sys.stdin.read()).get("decision_window_id",""))' <<<"${DECISION_JSON}")"
if [[ -z "${DECISION_WINDOW_ID}" ]]; then
  fail 13 "missing decision_window_id from decision-window response"
fi
curl -fsS "${BASE}/v1/memory/decision-windows?principal_id=exec-1&limit=5" "${AUTH_ARGS[@]}" >/dev/null
curl -fsS "${BASE}/v1/memory/decision-windows/${DECISION_WINDOW_ID}?principal_id=exec-1" "${AUTH_ARGS[@]}" >/dev/null
echo "memory ok"

echo "smoke complete"
