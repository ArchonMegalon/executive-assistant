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
and memory candidate/item/entity/relationship/commitment/authority-binding/delivery-preference/follow-up/deadline-window/stakeholder/decision-window/communication-policy/follow-up-rule/interruption-budget endpoints.

Auth:
  If EA_API_TOKEN is set, the script sends Authorization: Bearer <token>.
  Principal-scoped connector/memory checks send X-EA-Principal-ID from EA_PRINCIPAL_ID
  (default: exec-1) and verify mismatches against EA_MISMATCH_PRINCIPAL_ID
  (default: exec-2) return principal_scope_mismatch.

Exit codes:
  11 missing execution_session_id
  12 policy contract mismatch
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
PRINCIPAL_ID="${EA_PRINCIPAL_ID:-exec-1}"
MISMATCH_PRINCIPAL_ID="${EA_MISMATCH_PRINCIPAL_ID:-exec-2}"
PRINCIPAL_ARGS=(-H "X-EA-Principal-ID: ${PRINCIPAL_ID}")
APPROVAL_THRESHOLD_CHARS="${EA_APPROVAL_THRESHOLD_CHARS:-}"
if [[ -z "${APPROVAL_THRESHOLD_CHARS}" && -f "${EA_ROOT}/.env" ]]; then
  APPROVAL_THRESHOLD_CHARS="$(grep -E '^EA_APPROVAL_THRESHOLD_CHARS=' "${EA_ROOT}/.env" | tail -n1 | cut -d= -f2- || true)"
fi
APPROVAL_THRESHOLD_CHARS="${APPROVAL_THRESHOLD_CHARS:-5000}"
MAX_REWRITE_CHARS="${EA_MAX_REWRITE_CHARS:-}"
if [[ -z "${MAX_REWRITE_CHARS}" && -f "${EA_ROOT}/.env" ]]; then
  MAX_REWRITE_CHARS="$(grep -E '^EA_MAX_REWRITE_CHARS=' "${EA_ROOT}/.env" | tail -n1 | cut -d= -f2- || true)"
fi
MAX_REWRITE_CHARS="${MAX_REWRITE_CHARS:-20000}"

echo "== smoke: health =="
curl -fsS "${BASE}/health" >/dev/null
curl -fsS "${BASE}/health/live" >/dev/null
curl -fsS "${BASE}/health/ready" >/dev/null
curl -fsS "${BASE}/version" >/dev/null
echo "health/version ok"

echo "== smoke: rewrite =="
REWRITE_JSON="$(curl -fsS -X POST "${BASE}/v1/rewrite/artifact" "${AUTH_ARGS[@]}" -H 'content-type: application/json' -d '{"text":"smoke run"}')"
echo "${REWRITE_JSON}"
ARTIFACT_ID="$(python3 -c 'import json,sys; print(json.loads(sys.stdin.read()).get("artifact_id",""))' <<<"${REWRITE_JSON}")"
SESSION_ID="$(python3 -c 'import json,sys; print(json.loads(sys.stdin.read()).get("execution_session_id",""))' <<<"${REWRITE_JSON}")"
if [[ -z "${ARTIFACT_ID}" ]]; then
  fail 13 "missing artifact_id from rewrite response"
fi
if [[ -z "${SESSION_ID}" ]]; then
  fail 11 "missing execution_session_id from rewrite response"
fi

echo "== smoke: session + policy =="
curl -fsS "${BASE}/v1/rewrite/artifacts/${ARTIFACT_ID}" "${AUTH_ARGS[@]}" >/dev/null
SESSION_JSON="$(curl -fsS "${BASE}/v1/rewrite/sessions/${SESSION_ID}" "${AUTH_ARGS[@]}")"
SESSION_RUNTIME_FIELDS="$(python3 -c "import json,sys; body=json.loads(sys.stdin.read() or '{}'); events={e.get('name','') for e in (body.get('events') or [])}; queues=body.get('queue_items') or []; steps=body.get('steps') or []; history=body.get('human_task_assignment_history') or []; print('{}|{}|{}|{}|{}|{}|{}'.format(body.get('status',''), len(steps) >= 3, len(queues) >= 3 and all((q or {}).get('state','') == 'done' for q in queues), 'input_prepared' in events, 'policy_step_completed' in events, 'tool_execution_completed' in events, len(history) == 0))" <<<"${SESSION_JSON}")"
if [[ "${SESSION_RUNTIME_FIELDS}" != "completed|True|True|True|True|True|True" ]]; then
  echo "expected initial rewrite session to complete with three steps, done queue items, input_prepared, policy_step_completed, tool_execution_completed, and empty human-task assignment history; got ${SESSION_RUNTIME_FIELDS}" >&2
  echo "${SESSION_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
RECEIPT_ID="$(python3 -c 'import json,sys; body=json.loads(sys.stdin.read() or "{}"); rows=body.get("receipts") or []; print(((rows[0] or {}).get("receipt_id")) if rows else "")' <<<"${SESSION_JSON}")"
COST_ID="$(python3 -c 'import json,sys; body=json.loads(sys.stdin.read() or "{}"); rows=body.get("run_costs") or []; print(((rows[0] or {}).get("cost_id")) if rows else "")' <<<"${SESSION_JSON}")"
if [[ -z "${RECEIPT_ID}" ]]; then
  fail 13 "missing receipt_id from session response"
fi
if [[ -z "${COST_ID}" ]]; then
  fail 13 "missing cost_id from session response"
fi
RECEIPT_JSON="$(curl -fsS "${BASE}/v1/rewrite/receipts/${RECEIPT_ID}" "${AUTH_ARGS[@]}")"
RECEIPT_FIELDS="$(python3 -c "import json,sys; body=json.loads(sys.stdin.read() or '{}'); receipt=body.get('receipt_json') or {}; print('{}|{}'.format(receipt.get('handler_key',''), receipt.get('invocation_contract','')))" <<<"${RECEIPT_JSON}")"
if [[ "${RECEIPT_FIELDS}" != "artifact_repository|tool.v1" ]]; then
  echo "expected normalized receipt contract for artifact_repository; got ${RECEIPT_FIELDS}" >&2
  echo "${RECEIPT_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
curl -fsS "${BASE}/v1/rewrite/run-costs/${COST_ID}" "${AUTH_ARGS[@]}" >/dev/null
curl -fsS "${BASE}/v1/policy/decisions/recent?session_id=${SESSION_ID}&limit=5" "${AUTH_ARGS[@]}" >/dev/null
curl -fsS "${BASE}/v1/policy/approvals/pending?limit=5" "${AUTH_ARGS[@]}" >/dev/null
curl -fsS "${BASE}/v1/policy/approvals/history?limit=5" "${AUTH_ARGS[@]}" >/dev/null
echo "session/policy ok"

echo "== smoke: human tasks =="
SESSION_STEP_ID="$(python3 -c 'import json,sys; body=json.loads(sys.stdin.read() or "{}"); rows=body.get("steps") or []; print(((rows[-1] or {}).get("step_id")) if rows else "")' <<<"${SESSION_JSON}")"
if [[ -z "${SESSION_STEP_ID}" ]]; then
  fail 13 "missing step_id from session response"
fi
HUMAN_CREATE_JSON="$(curl -fsS -X POST "${BASE}/v1/human/tasks" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" -H 'content-type: application/json' \
  -d "{\"session_id\":\"${SESSION_ID}\",\"step_id\":\"${SESSION_STEP_ID}\",\"task_type\":\"communications_review\",\"role_required\":\"communications_reviewer\",\"brief\":\"Review the draft before external send.\",\"authority_required\":\"send_on_behalf_review\",\"why_human\":\"External executive communication needs human tone review.\",\"quality_rubric_json\":{\"checks\":[\"tone\",\"accuracy\",\"stakeholder_sensitivity\"]},\"input_json\":{\"artifact_id\":\"${ARTIFACT_ID}\"},\"desired_output_json\":{\"format\":\"review_packet\"},\"priority\":\"high\",\"sla_due_at\":\"2000-01-01T00:00:00+00:00\",\"resume_session_on_return\":true}")"
HUMAN_TASK_ID="$(python3 -c 'import json,sys; print(json.loads(sys.stdin.read() or "{}").get("human_task_id",""))' <<<"${HUMAN_CREATE_JSON}")"
HUMAN_CREATE_FIELDS="$(python3 -c 'import json,sys; body=json.loads(sys.stdin.read() or "{}"); checks=(body.get("quality_rubric_json") or {}).get("checks") or []; print("{}|{}|{}|{}|{}|{}|{}|{}|{}".format(body.get("status",""), body.get("assignment_state",""), body.get("assignment_source",""), body.get("assigned_at") is None, body.get("assigned_by_actor_id",""), body.get("resume_session_on_return", False), body.get("authority_required",""), body.get("why_human",""), checks[0] if checks else ""))' <<<"${HUMAN_CREATE_JSON}")"
if [[ -z "${HUMAN_TASK_ID}" ]]; then
  fail 13 "missing human_task_id from human task create response"
fi
if [[ "${HUMAN_CREATE_FIELDS}" != "pending|unassigned||True||True|send_on_behalf_review|External executive communication needs human tone review.|tone" ]]; then
  echo "expected pending human task with explicit review-contract metadata after creation; got ${HUMAN_CREATE_FIELDS}" >&2
  echo "${HUMAN_CREATE_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
HUMAN_CREATE_SUMMARY_FIELDS="$(python3 -c 'import json,sys; body=json.loads(sys.stdin.read() or "{}"); print("{}|{}|{}|{}|{}|{}".format(body.get("last_transition_event_name",""), bool(body.get("last_transition_at","")), body.get("last_transition_assignment_state",""), body.get("last_transition_operator_id",""), body.get("last_transition_assignment_source",""), body.get("last_transition_by_actor_id","")))' <<<"${HUMAN_CREATE_JSON}")"
if [[ "${HUMAN_CREATE_SUMMARY_FIELDS}" != "human_task_created|True|unassigned|||" ]]; then
  echo "expected create response to expose compact last-transition summary after human_task_created; got ${HUMAN_CREATE_SUMMARY_FIELDS}" >&2
  echo "${HUMAN_CREATE_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
SESSION_HUMAN_WAITING_JSON="$(curl -fsS "${BASE}/v1/rewrite/sessions/${SESSION_ID}" "${AUTH_ARGS[@]}")"
SESSION_HUMAN_WAITING_FIELDS="$(python3 -c "import json,sys; body=json.loads(sys.stdin.read() or '{}'); events={e.get('name','') for e in (body.get('events') or [])}; steps=body.get('steps') or []; step_id='${SESSION_STEP_ID}'; print('{}|{}|{}'.format(body.get('status',''), 'session_paused_for_human_task' in events, any((row or {}).get('step_id') == step_id and (row or {}).get('state') == 'waiting_human' for row in steps)))" <<<"${SESSION_HUMAN_WAITING_JSON}")"
if [[ "${SESSION_HUMAN_WAITING_FIELDS}" != "awaiting_human|True|True" ]]; then
  echo "expected session to reopen into awaiting_human with waiting_human step after human task creation; got ${SESSION_HUMAN_WAITING_FIELDS}" >&2
  echo "${SESSION_HUMAN_WAITING_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
SESSION_HUMAN_WAITING_SUMMARY_FIELDS="$(python3 -c "import json,sys; body=json.loads(sys.stdin.read() or '{}'); task_id='${HUMAN_TASK_ID}'; task=next((row for row in (body.get('human_tasks') or []) if (row or {}).get('human_task_id') == task_id), {}); print('{}|{}|{}|{}|{}|{}'.format(task.get('last_transition_event_name',''), bool(task.get('last_transition_at','')), task.get('last_transition_assignment_state',''), task.get('last_transition_operator_id',''), task.get('last_transition_assignment_source',''), task.get('last_transition_by_actor_id','')))" <<<"${SESSION_HUMAN_WAITING_JSON}")"
if [[ "${SESSION_HUMAN_WAITING_SUMMARY_FIELDS}" != "human_task_created|True|unassigned|||" ]]; then
  echo "expected awaiting_human session row to expose human_task_created transition summary; got ${SESSION_HUMAN_WAITING_SUMMARY_FIELDS}" >&2
  echo "${SESSION_HUMAN_WAITING_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
HUMAN_ROLE_FILTER_JSON="$(curl -fsS "${BASE}/v1/human/tasks?role_required=communications_reviewer&overdue_only=true&limit=10" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}")"
HUMAN_ROLE_FILTER_MATCH="$(python3 -c "import json,sys; rows=json.loads(sys.stdin.read() or '[]'); task_id='${HUMAN_TASK_ID}'; print(any((row or {}).get('human_task_id') == task_id for row in rows))" <<<"${HUMAN_ROLE_FILTER_JSON}")"
if [[ "${HUMAN_ROLE_FILTER_MATCH}" != "True" ]]; then
  echo "expected role/overdue human task queue filter to include ${HUMAN_TASK_ID}" >&2
  echo "${HUMAN_ROLE_FILTER_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
HUMAN_BACKLOG_JSON="$(curl -fsS "${BASE}/v1/human/tasks/backlog?role_required=communications_reviewer&overdue_only=true&limit=10" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}")"
HUMAN_BACKLOG_MATCH="$(python3 -c "import json,sys; rows=json.loads(sys.stdin.read() or '[]'); task_id='${HUMAN_TASK_ID}'; print(any((row or {}).get('human_task_id') == task_id for row in rows))" <<<"${HUMAN_BACKLOG_JSON}")"
if [[ "${HUMAN_BACKLOG_MATCH}" != "True" ]]; then
  echo "expected human task backlog endpoint to include ${HUMAN_TASK_ID}" >&2
  echo "${HUMAN_BACKLOG_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
HUMAN_UNASSIGNED_JSON="$(curl -fsS "${BASE}/v1/human/tasks/unassigned?role_required=communications_reviewer&overdue_only=true&limit=10" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}")"
HUMAN_UNASSIGNED_MATCH="$(python3 -c "import json,sys; rows=json.loads(sys.stdin.read() or '[]'); task_id='${HUMAN_TASK_ID}'; print(any((row or {}).get('human_task_id') == task_id for row in rows))" <<<"${HUMAN_UNASSIGNED_JSON}")"
if [[ "${HUMAN_UNASSIGNED_MATCH}" != "True" ]]; then
  echo "expected human task unassigned endpoint to include ${HUMAN_TASK_ID}" >&2
  echo "${HUMAN_UNASSIGNED_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
HUMAN_OPERATOR_SPECIALIST_JSON="$(curl -fsS -X POST "${BASE}/v1/human/tasks/operators" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" -H 'content-type: application/json' -d '{"operator_id":"operator-specialist","display_name":"Senior Comms Reviewer","roles":["communications_reviewer"],"skill_tags":["tone","accuracy","stakeholder_sensitivity"],"trust_tier":"senior","status":"active","notes":"Specialist in external executive communication."}')"
HUMAN_OPERATOR_SPECIALIST_FIELDS="$(python3 -c 'import json,sys; body=json.loads(sys.stdin.read() or "{}"); tags=body.get("skill_tags") or []; print("{}|{}|{}".format(body.get("operator_id",""), body.get("trust_tier",""), tags[0] if tags else ""))' <<<"${HUMAN_OPERATOR_SPECIALIST_JSON}")"
if [[ "${HUMAN_OPERATOR_SPECIALIST_FIELDS}" != "operator-specialist|senior|tone" ]]; then
  echo "expected specialist operator profile to persist role/skill/trust metadata; got ${HUMAN_OPERATOR_SPECIALIST_FIELDS}" >&2
  echo "${HUMAN_OPERATOR_SPECIALIST_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
curl -fsS -X POST "${BASE}/v1/human/tasks/operators" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" -H 'content-type: application/json' \
  -d '{"operator_id":"operator-junior","display_name":"Junior Reviewer","roles":["communications_reviewer"],"skill_tags":["tone"],"trust_tier":"standard","status":"active"}' >/dev/null
HUMAN_ROUTING_HINT_JSON="$(curl -fsS "${BASE}/v1/human/tasks/${HUMAN_TASK_ID}" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}")"
HUMAN_ROUTING_HINT_FIELDS="$(python3 -c 'import json,sys; body=json.loads(sys.stdin.read() or "{}"); hints=body.get("routing_hints_json") or {}; suggested=hints.get("suggested_operator_ids") or []; print("{}|{}|{}|{}".format((hints.get("required_skill_tags") or [None])[0], hints.get("required_trust_tier",""), suggested[0] if suggested else "", hints.get("auto_assign_operator_id","")))' <<<"${HUMAN_ROUTING_HINT_JSON}")"
if [[ "${HUMAN_ROUTING_HINT_FIELDS}" != "accuracy|senior|operator-specialist|operator-specialist" ]]; then
  echo "expected human task operator auto-assignment hint after specialist profile creation; got ${HUMAN_ROUTING_HINT_FIELDS}" >&2
  echo "${HUMAN_ROUTING_HINT_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
HUMAN_ASSIGN_JSON="$(curl -fsS -X POST "${BASE}/v1/human/tasks/${HUMAN_TASK_ID}/assign" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" -H 'content-type: application/json' -d '{}')"
HUMAN_ASSIGN_FIELDS="$(python3 -c 'import json,sys; body=json.loads(sys.stdin.read() or "{}"); print("{}|{}|{}|{}|{}|{}".format(body.get("status",""), body.get("assignment_state",""), body.get("assigned_operator_id",""), body.get("assignment_source",""), bool(body.get("assigned_at","")), body.get("assigned_by_actor_id","")))' <<<"${HUMAN_ASSIGN_JSON}")"
if [[ "${HUMAN_ASSIGN_FIELDS}" != "pending|assigned|operator-specialist|recommended|True|exec-1" ]]; then
  echo "expected assigned human task to stay pending with explicit assigned state and operator ownership; got ${HUMAN_ASSIGN_FIELDS}" >&2
  echo "${HUMAN_ASSIGN_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
HUMAN_ASSIGN_SUMMARY_FIELDS="$(python3 -c 'import json,sys; body=json.loads(sys.stdin.read() or "{}"); print("{}|{}|{}|{}|{}|{}".format(body.get("last_transition_event_name",""), bool(body.get("last_transition_at","")), body.get("last_transition_assignment_state",""), body.get("last_transition_operator_id",""), body.get("last_transition_assignment_source",""), body.get("last_transition_by_actor_id","")))' <<<"${HUMAN_ASSIGN_JSON}")"
if [[ "${HUMAN_ASSIGN_SUMMARY_FIELDS}" != "human_task_assigned|True|assigned|operator-specialist|recommended|exec-1" ]]; then
  echo "expected assigned response to expose recommended last-transition summary; got ${HUMAN_ASSIGN_SUMMARY_FIELDS}" >&2
  echo "${HUMAN_ASSIGN_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
HUMAN_OWNERLESS_JSON="$(curl -fsS -X POST "${BASE}/v1/human/tasks" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" -H 'content-type: application/json' \
  -d "{\"session_id\":\"${SESSION_ID}\",\"step_id\":\"${SESSION_STEP_ID}\",\"task_type\":\"communications_review\",\"role_required\":\"communications_reviewer\",\"brief\":\"Ownerless pending task.\",\"priority\":\"low\",\"resume_session_on_return\":false}")"
HUMAN_OWNERLESS_ID="$(python3 -c 'import json,sys; print(json.loads(sys.stdin.read() or "{}").get("human_task_id",""))' <<<"${HUMAN_OWNERLESS_JSON}")"
if [[ -z "${HUMAN_OWNERLESS_ID}" ]]; then
  fail 13 "missing human_task_id from ownerless human task response"
fi
PRIORITY_SUMMARY_NONE_JSON="$(curl -fsS "${BASE}/v1/human/tasks/priority-summary?status=pending&assignment_state=unassigned&assignment_source=none" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}")"
PRIORITY_SUMMARY_NONE_FIELDS="$(python3 -c "import json,sys; body=json.loads(sys.stdin.read() or '{}'); counts=body.get('counts_json') or {}; print('{}|{}|{}|{}|{}|{}|{}'.format(body.get('assignment_source',''), body.get('total',''), body.get('highest_priority',''), counts.get('urgent',''), counts.get('high',''), counts.get('normal',''), counts.get('low','')))" <<<"${PRIORITY_SUMMARY_NONE_JSON}")"
if [[ "${PRIORITY_SUMMARY_NONE_FIELDS}" != "none|1|low|0|0|0|1" ]]; then
  echo "expected assignment_source=none summary to isolate ownerless pending work; got ${PRIORITY_SUMMARY_NONE_FIELDS}" >&2
  echo "${PRIORITY_SUMMARY_NONE_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
HUMAN_OWNERLESS_LIST_JSON="$(curl -fsS "${BASE}/v1/human/tasks?status=pending&assignment_state=unassigned&assignment_source=none&limit=10" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}")"
HUMAN_OWNERLESS_LIST_FIELDS="$(python3 -c "import json,sys; rows=json.loads(sys.stdin.read() or '[]'); wanted='${HUMAN_OWNERLESS_ID}'; blocked='${HUMAN_TASK_ID}'; print('{}|{}'.format(any((row or {}).get('human_task_id') == wanted for row in rows), all((row or {}).get('human_task_id') != blocked for row in rows)))" <<<"${HUMAN_OWNERLESS_LIST_JSON}")"
if [[ "${HUMAN_OWNERLESS_LIST_FIELDS}" != "True|True" ]]; then
  echo "expected assignment_source=none list filter to isolate ownerless pending work; got ${HUMAN_OWNERLESS_LIST_FIELDS}" >&2
  echo "${HUMAN_OWNERLESS_LIST_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
HUMAN_UNASSIGNED_NONE_JSON="$(curl -fsS "${BASE}/v1/human/tasks/unassigned?assignment_source=none&limit=10" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}")"
HUMAN_UNASSIGNED_NONE_FIELDS="$(python3 -c "import json,sys; rows=json.loads(sys.stdin.read() or '[]'); wanted='${HUMAN_OWNERLESS_ID}'; blocked='${HUMAN_TASK_ID}'; print('{}|{}'.format(any((row or {}).get('human_task_id') == wanted for row in rows), all((row or {}).get('human_task_id') != blocked for row in rows)))" <<<"${HUMAN_UNASSIGNED_NONE_JSON}")"
if [[ "${HUMAN_UNASSIGNED_NONE_FIELDS}" != "True|True" ]]; then
  echo "expected assignment_source=none unassigned queue to isolate ownerless pending work; got ${HUMAN_UNASSIGNED_NONE_FIELDS}" >&2
  echo "${HUMAN_UNASSIGNED_NONE_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
HUMAN_OWNERLESS_BACKLOG_JSON="$(curl -fsS "${BASE}/v1/human/tasks/backlog?assignment_state=unassigned&assignment_source=none&limit=10" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}")"
HUMAN_OWNERLESS_BACKLOG_FIELDS="$(python3 -c "import json,sys; rows=json.loads(sys.stdin.read() or '[]'); wanted='${HUMAN_OWNERLESS_ID}'; blocked='${HUMAN_TASK_ID}'; print('{}|{}'.format(any((row or {}).get('human_task_id') == wanted for row in rows), all((row or {}).get('human_task_id') != blocked for row in rows)))" <<<"${HUMAN_OWNERLESS_BACKLOG_JSON}")"
if [[ "${HUMAN_OWNERLESS_BACKLOG_FIELDS}" != "True|True" ]]; then
  echo "expected assignment_source=none backlog queue to isolate ownerless pending work; got ${HUMAN_OWNERLESS_BACKLOG_FIELDS}" >&2
  echo "${HUMAN_OWNERLESS_BACKLOG_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
SESSION_HUMAN_NONE_JSON="$(curl -fsS "${BASE}/v1/rewrite/sessions/${SESSION_ID}?human_task_assignment_source=none" "${AUTH_ARGS[@]}")"
SESSION_HUMAN_NONE_FIELDS="$(python3 -c "import json,sys; body=json.loads(sys.stdin.read() or '{}'); tasks=body.get('human_tasks') or []; history=body.get('human_task_assignment_history') or []; wanted='${HUMAN_OWNERLESS_ID}'; print('{}|{}|{}|{}|{}'.format(len(tasks), (tasks[0].get('human_task_id','') if tasks else ''), all((row or {}).get('assignment_source','') == '' for row in history), all((row or {}).get('event_name','') == 'human_task_created' for row in history), any((row or {}).get('human_task_id','') == wanted for row in history)))" <<<"${SESSION_HUMAN_NONE_JSON}")"
if [[ "${SESSION_HUMAN_NONE_FIELDS}" != "1|${HUMAN_OWNERLESS_ID}|True|True|True" ]]; then
  echo "expected session assignment_source=none filter to isolate current ownerless rows and created-only history; got ${SESSION_HUMAN_NONE_FIELDS}" >&2
  echo "${SESSION_HUMAN_NONE_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
HUMAN_ASSIGNED_BACKLOG_JSON="$(curl -fsS "${BASE}/v1/human/tasks/backlog?role_required=communications_reviewer&overdue_only=true&assignment_state=assigned&limit=10" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}")"
HUMAN_ASSIGNED_BACKLOG_MATCH="$(python3 -c "import json,sys; rows=json.loads(sys.stdin.read() or '[]'); task_id='${HUMAN_TASK_ID}'; print(any((row or {}).get('human_task_id') == task_id for row in rows))" <<<"${HUMAN_ASSIGNED_BACKLOG_JSON}")"
if [[ "${HUMAN_ASSIGNED_BACKLOG_MATCH}" != "True" ]]; then
  echo "expected assigned-only backlog endpoint to include ${HUMAN_TASK_ID}" >&2
  echo "${HUMAN_ASSIGNED_BACKLOG_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
HUMAN_UNASSIGNED_AFTER_JSON="$(curl -fsS "${BASE}/v1/human/tasks/unassigned?role_required=communications_reviewer&overdue_only=true&limit=10" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}")"
HUMAN_UNASSIGNED_AFTER_MATCH="$(python3 -c "import json,sys; rows=json.loads(sys.stdin.read() or '[]'); task_id='${HUMAN_TASK_ID}'; print(all((row or {}).get('human_task_id') != task_id for row in rows))" <<<"${HUMAN_UNASSIGNED_AFTER_JSON}")"
if [[ "${HUMAN_UNASSIGNED_AFTER_MATCH}" != "True" ]]; then
  echo "expected human task unassigned endpoint to drop ${HUMAN_TASK_ID} after assignment" >&2
  echo "${HUMAN_UNASSIGNED_AFTER_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
HUMAN_OPERATOR_BACKLOG_JSON="$(curl -fsS "${BASE}/v1/human/tasks/backlog?operator_id=operator-specialist&overdue_only=true&limit=10" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}")"
HUMAN_OPERATOR_BACKLOG_MATCH="$(python3 -c "import json,sys; rows=json.loads(sys.stdin.read() or '[]'); task_id='${HUMAN_TASK_ID}'; print(any((row or {}).get('human_task_id') == task_id for row in rows))" <<<"${HUMAN_OPERATOR_BACKLOG_JSON}")"
if [[ "${HUMAN_OPERATOR_BACKLOG_MATCH}" != "True" ]]; then
  echo "expected operator-specialized backlog endpoint to include ${HUMAN_TASK_ID}" >&2
  echo "${HUMAN_OPERATOR_BACKLOG_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
HUMAN_OPERATOR_BACKLOG_LOW_JSON="$(curl -fsS "${BASE}/v1/human/tasks/backlog?operator_id=operator-junior&overdue_only=true&limit=10" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}")"
HUMAN_OPERATOR_BACKLOG_LOW_MATCH="$(python3 -c "import json,sys; rows=json.loads(sys.stdin.read() or '[]'); task_id='${HUMAN_TASK_ID}'; print(all((row or {}).get('human_task_id') != task_id for row in rows))" <<<"${HUMAN_OPERATOR_BACKLOG_LOW_JSON}")"
if [[ "${HUMAN_OPERATOR_BACKLOG_LOW_MATCH}" != "True" ]]; then
  echo "expected operator-specialized backlog endpoint to exclude ${HUMAN_TASK_ID} for low-trust or under-skilled operators" >&2
  echo "${HUMAN_OPERATOR_BACKLOG_LOW_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
HUMAN_MINE_ASSIGNED_JSON="$(curl -fsS "${BASE}/v1/human/tasks/mine?operator_id=operator-specialist&limit=10" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}")"
HUMAN_MINE_ASSIGNED_MATCH="$(python3 -c "import json,sys; rows=json.loads(sys.stdin.read() or '[]'); task_id='${HUMAN_TASK_ID}'; print(any((row or {}).get('human_task_id') == task_id for row in rows))" <<<"${HUMAN_MINE_ASSIGNED_JSON}")"
if [[ "${HUMAN_MINE_ASSIGNED_MATCH}" != "True" ]]; then
  echo "expected human task mine endpoint to include pre-assigned task ${HUMAN_TASK_ID}" >&2
  echo "${HUMAN_MINE_ASSIGNED_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
HUMAN_REASSIGN_JSON="$(curl -fsS -X POST "${BASE}/v1/human/tasks/${HUMAN_TASK_ID}/assign" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" -H 'content-type: application/json' -d '{"operator_id":"operator-junior"}')"
HUMAN_REASSIGN_FIELDS="$(python3 -c 'import json,sys; body=json.loads(sys.stdin.read() or "{}"); print("{}|{}|{}|{}|{}|{}".format(body.get("status",""), body.get("assignment_state",""), body.get("assigned_operator_id",""), body.get("assignment_source",""), bool(body.get("assigned_at","")), body.get("assigned_by_actor_id","")))' <<<"${HUMAN_REASSIGN_JSON}")"
if [[ "${HUMAN_REASSIGN_FIELDS}" != "pending|assigned|operator-junior|manual|True|exec-1" ]]; then
  echo "expected manual reassignment to overwrite current owner but preserve explicit provenance fields; got ${HUMAN_REASSIGN_FIELDS}" >&2
  echo "${HUMAN_REASSIGN_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
HUMAN_REASSIGN_SUMMARY_FIELDS="$(python3 -c 'import json,sys; body=json.loads(sys.stdin.read() or "{}"); print("{}|{}|{}|{}|{}|{}".format(body.get("last_transition_event_name",""), bool(body.get("last_transition_at","")), body.get("last_transition_assignment_state",""), body.get("last_transition_operator_id",""), body.get("last_transition_assignment_source",""), body.get("last_transition_by_actor_id","")))' <<<"${HUMAN_REASSIGN_JSON}")"
if [[ "${HUMAN_REASSIGN_SUMMARY_FIELDS}" != "human_task_assigned|True|assigned|operator-junior|manual|exec-1" ]]; then
  echo "expected reassigned response to expose manual last-transition summary; got ${HUMAN_REASSIGN_SUMMARY_FIELDS}" >&2
  echo "${HUMAN_REASSIGN_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
HUMAN_CLAIM_JSON="$(curl -fsS -X POST "${BASE}/v1/human/tasks/${HUMAN_TASK_ID}/claim" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" -H 'content-type: application/json' -d '{"operator_id":"operator-junior"}')"
HUMAN_CLAIM_FIELDS="$(python3 -c 'import json,sys; body=json.loads(sys.stdin.read() or "{}"); print("{}|{}|{}|{}|{}".format(body.get("status",""), body.get("assignment_state",""), body.get("assignment_source",""), bool(body.get("assigned_at","")), body.get("assigned_by_actor_id","")))' <<<"${HUMAN_CLAIM_JSON}")"
if [[ "${HUMAN_CLAIM_FIELDS}" != "claimed|claimed|manual|True|operator-junior" ]]; then
  echo "expected claimed human task after claim; got ${HUMAN_CLAIM_FIELDS}" >&2
  echo "${HUMAN_CLAIM_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
HUMAN_CLAIM_SUMMARY_FIELDS="$(python3 -c 'import json,sys; body=json.loads(sys.stdin.read() or "{}"); print("{}|{}|{}|{}|{}|{}".format(body.get("last_transition_event_name",""), bool(body.get("last_transition_at","")), body.get("last_transition_assignment_state",""), body.get("last_transition_operator_id",""), body.get("last_transition_assignment_source",""), body.get("last_transition_by_actor_id","")))' <<<"${HUMAN_CLAIM_JSON}")"
if [[ "${HUMAN_CLAIM_SUMMARY_FIELDS}" != "human_task_claimed|True|claimed|operator-junior|manual|operator-junior" ]]; then
  echo "expected claim response to expose claimed last-transition summary; got ${HUMAN_CLAIM_SUMMARY_FIELDS}" >&2
  echo "${HUMAN_CLAIM_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
HUMAN_OPERATOR_FILTER_JSON="$(curl -fsS "${BASE}/v1/human/tasks?assigned_operator_id=operator-junior&status=claimed&limit=10" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}")"
HUMAN_OPERATOR_FILTER_MATCH="$(python3 -c "import json,sys; rows=json.loads(sys.stdin.read() or '[]'); task_id='${HUMAN_TASK_ID}'; print(any((row or {}).get('human_task_id') == task_id for row in rows))" <<<"${HUMAN_OPERATOR_FILTER_JSON}")"
if [[ "${HUMAN_OPERATOR_FILTER_MATCH}" != "True" ]]; then
  echo "expected assigned-operator human task queue filter to include ${HUMAN_TASK_ID}" >&2
  echo "${HUMAN_OPERATOR_FILTER_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
HUMAN_MINE_JSON="$(curl -fsS "${BASE}/v1/human/tasks/mine?operator_id=operator-junior&limit=10" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}")"
HUMAN_MINE_MATCH="$(python3 -c "import json,sys; rows=json.loads(sys.stdin.read() or '[]'); task_id='${HUMAN_TASK_ID}'; print(any((row or {}).get('human_task_id') == task_id for row in rows))" <<<"${HUMAN_MINE_JSON}")"
if [[ "${HUMAN_MINE_MATCH}" != "True" ]]; then
  echo "expected human task mine endpoint to include ${HUMAN_TASK_ID}" >&2
  echo "${HUMAN_MINE_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
HUMAN_RETURN_JSON="$(curl -fsS -X POST "${BASE}/v1/human/tasks/${HUMAN_TASK_ID}/return" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" -H 'content-type: application/json' \
  -d '{"operator_id":"operator-junior","resolution":"ready_for_send","returned_payload_json":{"summary":"Reviewed and ready."},"provenance_json":{"review_mode":"human"}}')"
HUMAN_RETURN_FIELDS="$(python3 -c 'import json,sys; body=json.loads(sys.stdin.read() or "{}"); print("{}|{}|{}|{}|{}|{}".format(body.get("status",""), body.get("assignment_state",""), body.get("assignment_source",""), body.get("resolution",""), bool(body.get("assigned_at","")), body.get("assigned_by_actor_id","")))' <<<"${HUMAN_RETURN_JSON}")"
if [[ "${HUMAN_RETURN_FIELDS}" != "returned|returned|manual|ready_for_send|True|operator-junior" ]]; then
  echo "expected returned human task after return; got ${HUMAN_RETURN_FIELDS}" >&2
  echo "${HUMAN_RETURN_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
HUMAN_RETURN_SUMMARY_FIELDS="$(python3 -c 'import json,sys; body=json.loads(sys.stdin.read() or "{}"); print("{}|{}|{}|{}|{}|{}".format(body.get("last_transition_event_name",""), bool(body.get("last_transition_at","")), body.get("last_transition_assignment_state",""), body.get("last_transition_operator_id",""), body.get("last_transition_assignment_source",""), body.get("last_transition_by_actor_id","")))' <<<"${HUMAN_RETURN_JSON}")"
if [[ "${HUMAN_RETURN_SUMMARY_FIELDS}" != "human_task_returned|True|returned|operator-junior|manual|operator-junior" ]]; then
  echo "expected return response to expose returned last-transition summary; got ${HUMAN_RETURN_SUMMARY_FIELDS}" >&2
  echo "${HUMAN_RETURN_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
HUMAN_HISTORY_JSON="$(curl -fsS "${BASE}/v1/human/tasks/${HUMAN_TASK_ID}/assignment-history?limit=10" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}")"
HUMAN_HISTORY_FIELDS="$(python3 -c "import json,sys; rows=json.loads(sys.stdin.read() or '[]'); names=[(row or {}).get('event_name','') for row in rows]; operators=[(row or {}).get('assigned_operator_id','') for row in rows]; sources=[(row or {}).get('assignment_source','') for row in rows]; actors=[(row or {}).get('assigned_by_actor_id','') for row in rows]; print('{}|{}|{}|{}'.format(','.join(names), ','.join(operators), ','.join(sources), ','.join(actors)))" <<<"${HUMAN_HISTORY_JSON}")"
if [[ "${HUMAN_HISTORY_FIELDS}" != "human_task_created,human_task_assigned,human_task_assigned,human_task_claimed,human_task_returned|,operator-specialist,operator-junior,operator-junior,operator-junior|,recommended,manual,manual,manual|,exec-1,exec-1,operator-junior,operator-junior" ]]; then
  echo "expected task-scoped assignment-history endpoint to preserve both recommended and later manual owner transitions; got ${HUMAN_HISTORY_FIELDS}" >&2
  echo "${HUMAN_HISTORY_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
HUMAN_HISTORY_ASSIGNED_JSON="$(curl -fsS "${BASE}/v1/human/tasks/${HUMAN_TASK_ID}/assignment-history?limit=10&event_name=human_task_assigned&assigned_by_actor_id=exec-1" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}")"
HUMAN_HISTORY_ASSIGNED_FIELDS="$(python3 -c "import json,sys; rows=json.loads(sys.stdin.read() or '[]'); print(','.join((row or {}).get('assigned_operator_id','') for row in rows))" <<<"${HUMAN_HISTORY_ASSIGNED_JSON}")"
if [[ "${HUMAN_HISTORY_ASSIGNED_FIELDS}" != "operator-specialist,operator-junior" ]]; then
  echo "expected filtered assignment-history route to isolate recommended and manual assignment transitions; got ${HUMAN_HISTORY_ASSIGNED_FIELDS}" >&2
  echo "${HUMAN_HISTORY_ASSIGNED_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
HUMAN_HISTORY_RETURN_JSON="$(curl -fsS "${BASE}/v1/human/tasks/${HUMAN_TASK_ID}/assignment-history?limit=10&event_name=human_task_returned&assigned_operator_id=operator-junior" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}")"
HUMAN_HISTORY_RETURN_FIELDS="$(python3 -c "import json,sys; rows=json.loads(sys.stdin.read() or '[]'); first=(rows[0] if rows else {}); print('{}|{}'.format(len(rows), (first or {}).get('assigned_by_actor_id','')))" <<<"${HUMAN_HISTORY_RETURN_JSON}")"
if [[ "${HUMAN_HISTORY_RETURN_FIELDS}" != "1|operator-junior" ]]; then
  echo "expected filtered assignment-history route to isolate returned transitions for a specific operator; got ${HUMAN_HISTORY_RETURN_FIELDS}" >&2
  echo "${HUMAN_HISTORY_RETURN_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
HUMAN_HISTORY_RECOMMENDED_JSON="$(curl -fsS "${BASE}/v1/human/tasks/${HUMAN_TASK_ID}/assignment-history?limit=10&assignment_source=recommended" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}")"
HUMAN_HISTORY_RECOMMENDED_FIELDS="$(python3 -c "import json,sys; rows=json.loads(sys.stdin.read() or '[]'); first=(rows[0] if rows else {}); print('{}|{}|{}'.format(len(rows), (first or {}).get('event_name',''), (first or {}).get('assigned_operator_id','')))" <<<"${HUMAN_HISTORY_RECOMMENDED_JSON}")"
if [[ "${HUMAN_HISTORY_RECOMMENDED_FIELDS}" != "1|human_task_assigned|operator-specialist" ]]; then
  echo "expected filtered assignment-history route to isolate recommended assignment transitions by assignment_source; got ${HUMAN_HISTORY_RECOMMENDED_FIELDS}" >&2
  echo "${HUMAN_HISTORY_RECOMMENDED_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
HUMAN_HISTORY_NONE_JSON="$(curl -fsS "${BASE}/v1/human/tasks/${HUMAN_TASK_ID}/assignment-history?limit=10&assignment_source=none" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}")"
HUMAN_HISTORY_NONE_FIELDS="$(python3 -c "import json,sys; rows=json.loads(sys.stdin.read() or '[]'); first=(rows[0] if rows else {}); print('{}|{}|{}'.format(len(rows), (first or {}).get('event_name',''), (first or {}).get('assignment_source','')))" <<<"${HUMAN_HISTORY_NONE_JSON}")"
if [[ "${HUMAN_HISTORY_NONE_FIELDS}" != "1|human_task_created|" ]]; then
  echo "expected filtered assignment-history route to isolate ownerless creation transitions by assignment_source=none; got ${HUMAN_HISTORY_NONE_FIELDS}" >&2
  echo "${HUMAN_HISTORY_NONE_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
SESSION_HUMAN_JSON="$(curl -fsS "${BASE}/v1/rewrite/sessions/${SESSION_ID}" "${AUTH_ARGS[@]}")"
SESSION_HUMAN_FIELDS="$(python3 -c "import json,sys; body=json.loads(sys.stdin.read() or '{}'); events={e.get('name','') for e in (body.get('events') or [])}; tasks=body.get('human_tasks') or []; steps=body.get('steps') or []; history=body.get('human_task_assignment_history') or []; task_id='${HUMAN_TASK_ID}'; step_id='${SESSION_STEP_ID}'; names=[(row or {}).get('event_name','') for row in history if (row or {}).get('human_task_id') == task_id]; operators=[(row or {}).get('assigned_operator_id','') for row in history if (row or {}).get('human_task_id') == task_id]; print('{}|{}|{}|{}|{}|{}|{}|{}|{}|{}'.format(body.get('status',''), 'human_task_created' in events and 'human_task_assigned' in events, 'human_task_claimed' in events, 'human_task_returned' in events and 'session_resumed_from_human_task' in events, any((row or {}).get('human_task_id') == task_id and (row or {}).get('status') == 'returned' and (row or {}).get('assignment_state') == 'returned' and (row or {}).get('assignment_source') == 'manual' and bool((row or {}).get('assigned_at','')) and (row or {}).get('assigned_by_actor_id') == 'operator-junior' for row in tasks), any((row or {}).get('step_id') == step_id and (row or {}).get('state') == 'completed' and ((row or {}).get('output_json') or {}).get('human_task_id') == task_id for row in steps), any((row or {}).get('assignment_source') == 'manual' for row in tasks if (row or {}).get('human_task_id') == task_id), any((row or {}).get('assigned_by_actor_id') == 'operator-junior' for row in tasks if (row or {}).get('human_task_id') == task_id), ','.join(names), ','.join(operators)))" <<<"${SESSION_HUMAN_JSON}")"
if [[ "${SESSION_HUMAN_FIELDS}" != "completed|True|True|True|True|True|True|True|human_task_created,human_task_assigned,human_task_assigned,human_task_claimed,human_task_returned|,operator-specialist,operator-junior,operator-junior,operator-junior" ]]; then
  echo "expected resumed session projection to expose returned row, completed resumed step, and inline assignment history; got ${SESSION_HUMAN_FIELDS}" >&2
  echo "${SESSION_HUMAN_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
SESSION_HUMAN_SUMMARY_FIELDS="$(python3 -c "import json,sys; body=json.loads(sys.stdin.read() or '{}'); task_id='${HUMAN_TASK_ID}'; task=next((row for row in (body.get('human_tasks') or []) if (row or {}).get('human_task_id') == task_id), {}); print('{}|{}|{}|{}|{}|{}'.format(task.get('last_transition_event_name',''), bool(task.get('last_transition_at','')), task.get('last_transition_assignment_state',''), task.get('last_transition_operator_id',''), task.get('last_transition_assignment_source',''), task.get('last_transition_by_actor_id','')))" <<<"${SESSION_HUMAN_JSON}")"
if [[ "${SESSION_HUMAN_SUMMARY_FIELDS}" != "human_task_returned|True|returned|operator-junior|manual|operator-junior" ]]; then
  echo "expected resumed session task row to expose returned last-transition summary; got ${SESSION_HUMAN_SUMMARY_FIELDS}" >&2
  echo "${SESSION_HUMAN_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
SESSION_HUMAN_MANUAL_JSON="$(curl -fsS "${BASE}/v1/rewrite/sessions/${SESSION_ID}?human_task_assignment_source=manual" "${AUTH_ARGS[@]}")"
SESSION_HUMAN_MANUAL_FIELDS="$(python3 -c "import json,sys; body=json.loads(sys.stdin.read() or '{}'); tasks=body.get('human_tasks') or []; history=body.get('human_task_assignment_history') or []; print('{}|{}|{}'.format(len(tasks), (tasks[0].get('human_task_id','') if tasks else ''), ','.join((row or {}).get('event_name','') for row in history)))" <<<"${SESSION_HUMAN_MANUAL_JSON}")"
if [[ "${SESSION_HUMAN_MANUAL_FIELDS}" != "1|${HUMAN_TASK_ID}|human_task_assigned,human_task_claimed,human_task_returned" ]]; then
  echo "expected session assignment-source filter to isolate manual ownership rows and transitions; got ${SESSION_HUMAN_MANUAL_FIELDS}" >&2
  echo "${SESSION_HUMAN_MANUAL_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
echo "human tasks ok"

echo "== smoke: human task last-transition sort =="
SORT_REWRITE_JSON="$(curl -fsS -X POST "${BASE}/v1/rewrite/artifact" "${AUTH_ARGS[@]}" -H 'content-type: application/json' -d '{"text":"sort seed"}')"
SORT_SESSION_ID="$(python3 -c 'import json,sys; body=json.loads(sys.stdin.read() or "{}"); print(body.get("execution_session_id",""))' <<<"${SORT_REWRITE_JSON}")"
SORT_SESSION_JSON="$(curl -fsS "${BASE}/v1/rewrite/sessions/${SORT_SESSION_ID}" "${AUTH_ARGS[@]}")"
SORT_STEP_ID="$(python3 -c 'import json,sys; body=json.loads(sys.stdin.read() or "{}"); rows=body.get("steps") or []; print(((rows[-1] or {}).get("step_id")) if rows else "")' <<<"${SORT_SESSION_JSON}")"
if [[ -z "${SORT_STEP_ID}" ]]; then
  fail 13 "missing sort step_id from session response"
fi
SORT_TASK_OLDER_JSON="$(curl -fsS -X POST "${BASE}/v1/human/tasks" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" -H 'content-type: application/json' \
  -d "{\"session_id\":\"${SORT_SESSION_ID}\",\"step_id\":\"${SORT_STEP_ID}\",\"task_type\":\"communications_review\",\"role_required\":\"communications_reviewer\",\"brief\":\"Older pending task.\",\"resume_session_on_return\":false}")"
SORT_TASK_OLDER_ID="$(python3 -c 'import json,sys; body=json.loads(sys.stdin.read() or "{}"); print(body.get("human_task_id",""))' <<<"${SORT_TASK_OLDER_JSON}")"
SORT_TASK_NEWER_JSON="$(curl -fsS -X POST "${BASE}/v1/human/tasks" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" -H 'content-type: application/json' \
  -d "{\"session_id\":\"${SORT_SESSION_ID}\",\"step_id\":\"${SORT_STEP_ID}\",\"task_type\":\"communications_review\",\"role_required\":\"communications_reviewer\",\"brief\":\"Newer untouched task.\",\"resume_session_on_return\":false}")"
SORT_TASK_NEWER_ID="$(python3 -c 'import json,sys; body=json.loads(sys.stdin.read() or "{}"); print(body.get("human_task_id",""))' <<<"${SORT_TASK_NEWER_JSON}")"
if [[ -z "${SORT_TASK_OLDER_ID}" || -z "${SORT_TASK_NEWER_ID}" ]]; then
  fail 13 "missing human task ids from sort smoke setup"
fi
SORT_ASSIGN_JSON="$(curl -fsS -X POST "${BASE}/v1/human/tasks/${SORT_TASK_OLDER_ID}/assign" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" -H 'content-type: application/json' -d '{"operator_id":"operator-sorter"}')"
SORT_ASSIGN_FIELDS="$(python3 -c 'import json,sys; body=json.loads(sys.stdin.read() or "{}"); print("{}|{}".format(body.get("human_task_id",""), body.get("last_transition_event_name","")))' <<<"${SORT_ASSIGN_JSON}")"
if [[ "${SORT_ASSIGN_FIELDS}" != "${SORT_TASK_OLDER_ID}|human_task_assigned" ]]; then
  echo "expected sort-smoke assignment to mark the older task as recently assigned; got ${SORT_ASSIGN_FIELDS}" >&2
  echo "${SORT_ASSIGN_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
SORT_LIST_JSON="$(curl -fsS "${BASE}/v1/human/tasks?status=pending&sort=last_transition_desc&limit=10" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}")"
SORT_LIST_FIELDS="$(python3 -c "import json,sys; rows=json.loads(sys.stdin.read() or '[]'); wanted=['${SORT_TASK_OLDER_ID}','${SORT_TASK_NEWER_ID}']; filtered=[row for row in rows if (row or {}).get('human_task_id') in wanted]; first=(filtered[0] if len(filtered) > 0 else {}); second=(filtered[1] if len(filtered) > 1 else {}); print('{}|{}|{}|{}'.format(first.get('human_task_id',''), first.get('last_transition_event_name',''), second.get('human_task_id',''), second.get('last_transition_event_name','')))" <<<"${SORT_LIST_JSON}")"
if [[ "${SORT_LIST_FIELDS}" != "${SORT_TASK_OLDER_ID}|human_task_assigned|${SORT_TASK_NEWER_ID}|human_task_created" ]]; then
  echo "expected sort=last_transition_desc to order general human task list by freshest ownership change; got ${SORT_LIST_FIELDS}" >&2
  echo "${SORT_LIST_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
SORT_BACKLOG_JSON="$(curl -fsS "${BASE}/v1/human/tasks/backlog?sort=last_transition_desc&limit=10" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}")"
SORT_BACKLOG_FIELDS="$(python3 -c "import json,sys; rows=json.loads(sys.stdin.read() or '[]'); wanted=['${SORT_TASK_OLDER_ID}','${SORT_TASK_NEWER_ID}']; filtered=[row for row in rows if (row or {}).get('human_task_id') in wanted]; first=(filtered[0] if len(filtered) > 0 else {}); second=(filtered[1] if len(filtered) > 1 else {}); print('{}|{}|{}|{}'.format(first.get('human_task_id',''), first.get('last_transition_event_name',''), second.get('human_task_id',''), second.get('last_transition_event_name','')))" <<<"${SORT_BACKLOG_JSON}")"
if [[ "${SORT_BACKLOG_FIELDS}" != "${SORT_TASK_OLDER_ID}|human_task_assigned|${SORT_TASK_NEWER_ID}|human_task_created" ]]; then
  echo "expected backlog sort=last_transition_desc to order pending work by freshest ownership change; got ${SORT_BACKLOG_FIELDS}" >&2
  echo "${SORT_BACKLOG_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
echo "human task last-transition sort ok"

echo "== smoke: human task created-asc sort =="
CREATED_ASC_REWRITE_JSON="$(curl -fsS -X POST "${BASE}/v1/rewrite/artifact" "${AUTH_ARGS[@]}" -H 'content-type: application/json' -d '{"text":"created asc seed"}')"
CREATED_ASC_SESSION_ID="$(python3 -c 'import json,sys; body=json.loads(sys.stdin.read() or "{}"); print(body.get("execution_session_id",""))' <<<"${CREATED_ASC_REWRITE_JSON}")"
CREATED_ASC_SESSION_JSON="$(curl -fsS "${BASE}/v1/rewrite/sessions/${CREATED_ASC_SESSION_ID}" "${AUTH_ARGS[@]}")"
CREATED_ASC_STEP_ID="$(python3 -c 'import json,sys; body=json.loads(sys.stdin.read() or "{}"); rows=body.get("steps") or []; print(((rows[-1] or {}).get("step_id")) if rows else "")' <<<"${CREATED_ASC_SESSION_JSON}")"
if [[ -z "${CREATED_ASC_STEP_ID}" ]]; then
  fail 13 "missing created-asc sort step_id from session response"
fi
CREATED_ASC_OLDEST_JSON="$(curl -fsS -X POST "${BASE}/v1/human/tasks" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" -H 'content-type: application/json' \
  -d "{\"session_id\":\"${CREATED_ASC_SESSION_ID}\",\"step_id\":\"${CREATED_ASC_STEP_ID}\",\"task_type\":\"communications_review\",\"role_required\":\"communications_reviewer\",\"brief\":\"Oldest unassigned task.\",\"resume_session_on_return\":false}")"
CREATED_ASC_OLDEST_ID="$(python3 -c 'import json,sys; body=json.loads(sys.stdin.read() or "{}"); print(body.get("human_task_id",""))' <<<"${CREATED_ASC_OLDEST_JSON}")"
CREATED_ASC_OLDER_MINE_JSON="$(curl -fsS -X POST "${BASE}/v1/human/tasks" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" -H 'content-type: application/json' \
  -d "{\"session_id\":\"${CREATED_ASC_SESSION_ID}\",\"step_id\":\"${CREATED_ASC_STEP_ID}\",\"task_type\":\"communications_review\",\"role_required\":\"communications_reviewer\",\"brief\":\"Older assigned task.\",\"resume_session_on_return\":false}")"
CREATED_ASC_OLDER_MINE_ID="$(python3 -c 'import json,sys; body=json.loads(sys.stdin.read() or "{}"); print(body.get("human_task_id",""))' <<<"${CREATED_ASC_OLDER_MINE_JSON}")"
CREATED_ASC_MIDDLE_JSON="$(curl -fsS -X POST "${BASE}/v1/human/tasks" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" -H 'content-type: application/json' \
  -d "{\"session_id\":\"${CREATED_ASC_SESSION_ID}\",\"step_id\":\"${CREATED_ASC_STEP_ID}\",\"task_type\":\"communications_review\",\"role_required\":\"communications_reviewer\",\"brief\":\"Middle unassigned task.\",\"resume_session_on_return\":false}")"
CREATED_ASC_MIDDLE_ID="$(python3 -c 'import json,sys; body=json.loads(sys.stdin.read() or "{}"); print(body.get("human_task_id",""))' <<<"${CREATED_ASC_MIDDLE_JSON}")"
CREATED_ASC_NEWER_MINE_JSON="$(curl -fsS -X POST "${BASE}/v1/human/tasks" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" -H 'content-type: application/json' \
  -d "{\"session_id\":\"${CREATED_ASC_SESSION_ID}\",\"step_id\":\"${CREATED_ASC_STEP_ID}\",\"task_type\":\"communications_review\",\"role_required\":\"communications_reviewer\",\"brief\":\"Newer assigned task.\",\"resume_session_on_return\":false}")"
CREATED_ASC_NEWER_MINE_ID="$(python3 -c 'import json,sys; body=json.loads(sys.stdin.read() or "{}"); print(body.get("human_task_id",""))' <<<"${CREATED_ASC_NEWER_MINE_JSON}")"
if [[ -z "${CREATED_ASC_OLDEST_ID}" || -z "${CREATED_ASC_OLDER_MINE_ID}" || -z "${CREATED_ASC_MIDDLE_ID}" || -z "${CREATED_ASC_NEWER_MINE_ID}" ]]; then
  fail 13 "missing human task ids from created-asc sort smoke setup"
fi
CREATED_ASC_ASSIGN_OLDER_JSON="$(curl -fsS -X POST "${BASE}/v1/human/tasks/${CREATED_ASC_OLDER_MINE_ID}/assign" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" -H 'content-type: application/json' -d '{"operator_id":"operator-sorter"}')"
CREATED_ASC_ASSIGN_NEWER_JSON="$(curl -fsS -X POST "${BASE}/v1/human/tasks/${CREATED_ASC_NEWER_MINE_ID}/assign" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" -H 'content-type: application/json' -d '{"operator_id":"operator-sorter"}')"
CREATED_ASC_ASSIGN_FIELDS="$(python3 -c "import json,sys; first=json.loads(sys.argv[1] or '{}'); second=json.loads(sys.argv[2] or '{}'); print('{}|{}|{}|{}'.format(first.get('human_task_id',''), first.get('last_transition_event_name',''), second.get('human_task_id',''), second.get('last_transition_event_name','')))" "${CREATED_ASC_ASSIGN_OLDER_JSON}" "${CREATED_ASC_ASSIGN_NEWER_JSON}")"
if [[ "${CREATED_ASC_ASSIGN_FIELDS}" != "${CREATED_ASC_OLDER_MINE_ID}|human_task_assigned|${CREATED_ASC_NEWER_MINE_ID}|human_task_assigned" ]]; then
  echo "expected created-asc setup assignments to preserve assigned task ownership metadata; got ${CREATED_ASC_ASSIGN_FIELDS}" >&2
  echo "${CREATED_ASC_ASSIGN_OLDER_JSON}" >&2
  echo "${CREATED_ASC_ASSIGN_NEWER_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
CREATED_ASC_LIST_JSON="$(curl -fsS "${BASE}/v1/human/tasks?status=pending&sort=created_asc&limit=10" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}")"
CREATED_ASC_LIST_FIELDS="$(python3 -c "import json,sys; rows=json.loads(sys.stdin.read() or '[]'); wanted=['${CREATED_ASC_OLDEST_ID}','${CREATED_ASC_OLDER_MINE_ID}','${CREATED_ASC_MIDDLE_ID}','${CREATED_ASC_NEWER_MINE_ID}']; filtered=[row for row in rows if (row or {}).get('human_task_id') in wanted]; ids=[(row or {}).get('human_task_id','') for row in filtered[:4]]; print('|'.join(ids))" <<<"${CREATED_ASC_LIST_JSON}")"
if [[ "${CREATED_ASC_LIST_FIELDS}" != "${CREATED_ASC_OLDEST_ID}|${CREATED_ASC_OLDER_MINE_ID}|${CREATED_ASC_MIDDLE_ID}|${CREATED_ASC_NEWER_MINE_ID}" ]]; then
  echo "expected sort=created_asc to order the general pending queue by oldest created task first; got ${CREATED_ASC_LIST_FIELDS}" >&2
  echo "${CREATED_ASC_LIST_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
CREATED_ASC_BACKLOG_JSON="$(curl -fsS "${BASE}/v1/human/tasks/backlog?sort=created_asc&limit=10" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}")"
CREATED_ASC_BACKLOG_FIELDS="$(python3 -c "import json,sys; rows=json.loads(sys.stdin.read() or '[]'); wanted=['${CREATED_ASC_OLDEST_ID}','${CREATED_ASC_OLDER_MINE_ID}','${CREATED_ASC_MIDDLE_ID}','${CREATED_ASC_NEWER_MINE_ID}']; filtered=[row for row in rows if (row or {}).get('human_task_id') in wanted]; ids=[(row or {}).get('human_task_id','') for row in filtered[:4]]; print('|'.join(ids))" <<<"${CREATED_ASC_BACKLOG_JSON}")"
if [[ "${CREATED_ASC_BACKLOG_FIELDS}" != "${CREATED_ASC_OLDEST_ID}|${CREATED_ASC_OLDER_MINE_ID}|${CREATED_ASC_MIDDLE_ID}|${CREATED_ASC_NEWER_MINE_ID}" ]]; then
  echo "expected backlog sort=created_asc to order pending work by oldest created task first; got ${CREATED_ASC_BACKLOG_FIELDS}" >&2
  echo "${CREATED_ASC_BACKLOG_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
CREATED_ASC_UNASSIGNED_JSON="$(curl -fsS "${BASE}/v1/human/tasks/unassigned?sort=created_asc&limit=10" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}")"
CREATED_ASC_UNASSIGNED_FIELDS="$(python3 -c "import json,sys; rows=json.loads(sys.stdin.read() or '[]'); wanted=['${CREATED_ASC_OLDEST_ID}','${CREATED_ASC_MIDDLE_ID}']; filtered=[row for row in rows if (row or {}).get('human_task_id') in wanted]; ids=[(row or {}).get('human_task_id','') for row in filtered[:2]]; print('|'.join(ids))" <<<"${CREATED_ASC_UNASSIGNED_JSON}")"
if [[ "${CREATED_ASC_UNASSIGNED_FIELDS}" != "${CREATED_ASC_OLDEST_ID}|${CREATED_ASC_MIDDLE_ID}" ]]; then
  echo "expected unassigned sort=created_asc to keep oldest unassigned work first; got ${CREATED_ASC_UNASSIGNED_FIELDS}" >&2
  echo "${CREATED_ASC_UNASSIGNED_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
CREATED_ASC_MINE_JSON="$(curl -fsS "${BASE}/v1/human/tasks/mine?operator_id=operator-sorter&status=pending&sort=created_asc&limit=10" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}")"
CREATED_ASC_MINE_FIELDS="$(python3 -c "import json,sys; rows=json.loads(sys.stdin.read() or '[]'); wanted=['${CREATED_ASC_OLDER_MINE_ID}','${CREATED_ASC_NEWER_MINE_ID}']; filtered=[row for row in rows if (row or {}).get('human_task_id') in wanted]; ids=[(row or {}).get('human_task_id','') for row in filtered[:2]]; print('|'.join(ids))" <<<"${CREATED_ASC_MINE_JSON}")"
if [[ "${CREATED_ASC_MINE_FIELDS}" != "${CREATED_ASC_OLDER_MINE_ID}|${CREATED_ASC_NEWER_MINE_ID}" ]]; then
  echo "expected mine sort=created_asc to keep the operator queue in oldest-created order; got ${CREATED_ASC_MINE_FIELDS}" >&2
  echo "${CREATED_ASC_MINE_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
echo "human task created-asc sort ok"

echo "== smoke: human task priority-desc-created-asc sort =="
PRIORITY_SORT_REWRITE_JSON="$(curl -fsS -X POST "${BASE}/v1/rewrite/artifact" "${AUTH_ARGS[@]}" -H 'content-type: application/json' -d '{"text":"priority sort seed"}')"
PRIORITY_SORT_SESSION_ID="$(python3 -c 'import json,sys; body=json.loads(sys.stdin.read() or "{}"); print(body.get("execution_session_id",""))' <<<"${PRIORITY_SORT_REWRITE_JSON}")"
PRIORITY_SORT_SESSION_JSON="$(curl -fsS "${BASE}/v1/rewrite/sessions/${PRIORITY_SORT_SESSION_ID}" "${AUTH_ARGS[@]}")"
PRIORITY_SORT_STEP_ID="$(python3 -c 'import json,sys; body=json.loads(sys.stdin.read() or "{}"); rows=body.get("steps") or []; print(((rows[-1] or {}).get("step_id")) if rows else "")' <<<"${PRIORITY_SORT_SESSION_JSON}")"
if [[ -z "${PRIORITY_SORT_STEP_ID}" ]]; then
  fail 13 "missing priority sort step_id from session response"
fi
PRIORITY_SORT_OLDEST_NORMAL_JSON="$(curl -fsS -X POST "${BASE}/v1/human/tasks" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" -H 'content-type: application/json' \
  -d "{\"session_id\":\"${PRIORITY_SORT_SESSION_ID}\",\"step_id\":\"${PRIORITY_SORT_STEP_ID}\",\"task_type\":\"communications_review\",\"role_required\":\"communications_reviewer\",\"brief\":\"Oldest normal task.\",\"priority\":\"normal\",\"resume_session_on_return\":false}")"
PRIORITY_SORT_OLDEST_NORMAL_ID="$(python3 -c 'import json,sys; body=json.loads(sys.stdin.read() or "{}"); print(body.get("human_task_id",""))' <<<"${PRIORITY_SORT_OLDEST_NORMAL_JSON}")"
PRIORITY_SORT_OLDER_HIGH_MINE_JSON="$(curl -fsS -X POST "${BASE}/v1/human/tasks" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" -H 'content-type: application/json' \
  -d "{\"session_id\":\"${PRIORITY_SORT_SESSION_ID}\",\"step_id\":\"${PRIORITY_SORT_STEP_ID}\",\"task_type\":\"communications_review\",\"role_required\":\"communications_reviewer\",\"brief\":\"Older high-priority assigned task.\",\"priority\":\"high\",\"resume_session_on_return\":false}")"
PRIORITY_SORT_OLDER_HIGH_MINE_ID="$(python3 -c 'import json,sys; body=json.loads(sys.stdin.read() or "{}"); print(body.get("human_task_id",""))' <<<"${PRIORITY_SORT_OLDER_HIGH_MINE_JSON}")"
PRIORITY_SORT_MIDDLE_HIGH_JSON="$(curl -fsS -X POST "${BASE}/v1/human/tasks" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" -H 'content-type: application/json' \
  -d "{\"session_id\":\"${PRIORITY_SORT_SESSION_ID}\",\"step_id\":\"${PRIORITY_SORT_STEP_ID}\",\"task_type\":\"communications_review\",\"role_required\":\"communications_reviewer\",\"brief\":\"Middle high-priority unassigned task.\",\"priority\":\"high\",\"resume_session_on_return\":false}")"
PRIORITY_SORT_MIDDLE_HIGH_ID="$(python3 -c 'import json,sys; body=json.loads(sys.stdin.read() or "{}"); print(body.get("human_task_id",""))' <<<"${PRIORITY_SORT_MIDDLE_HIGH_JSON}")"
PRIORITY_SORT_NEWER_URGENT_MINE_JSON="$(curl -fsS -X POST "${BASE}/v1/human/tasks" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" -H 'content-type: application/json' \
  -d "{\"session_id\":\"${PRIORITY_SORT_SESSION_ID}\",\"step_id\":\"${PRIORITY_SORT_STEP_ID}\",\"task_type\":\"communications_review\",\"role_required\":\"communications_reviewer\",\"brief\":\"Newer urgent assigned task.\",\"priority\":\"urgent\",\"resume_session_on_return\":false}")"
PRIORITY_SORT_NEWER_URGENT_MINE_ID="$(python3 -c 'import json,sys; body=json.loads(sys.stdin.read() or "{}"); print(body.get("human_task_id",""))' <<<"${PRIORITY_SORT_NEWER_URGENT_MINE_JSON}")"
PRIORITY_SORT_NEWEST_NORMAL_JSON="$(curl -fsS -X POST "${BASE}/v1/human/tasks" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" -H 'content-type: application/json' \
  -d "{\"session_id\":\"${PRIORITY_SORT_SESSION_ID}\",\"step_id\":\"${PRIORITY_SORT_STEP_ID}\",\"task_type\":\"communications_review\",\"role_required\":\"communications_reviewer\",\"brief\":\"Newest normal task.\",\"priority\":\"normal\",\"resume_session_on_return\":false}")"
PRIORITY_SORT_NEWEST_NORMAL_ID="$(python3 -c 'import json,sys; body=json.loads(sys.stdin.read() or "{}"); print(body.get("human_task_id",""))' <<<"${PRIORITY_SORT_NEWEST_NORMAL_JSON}")"
if [[ -z "${PRIORITY_SORT_OLDEST_NORMAL_ID}" || -z "${PRIORITY_SORT_OLDER_HIGH_MINE_ID}" || -z "${PRIORITY_SORT_MIDDLE_HIGH_ID}" || -z "${PRIORITY_SORT_NEWER_URGENT_MINE_ID}" || -z "${PRIORITY_SORT_NEWEST_NORMAL_ID}" ]]; then
  fail 13 "missing human task ids from priority sort smoke setup"
fi
PRIORITY_SORT_ASSIGN_OLDER_JSON="$(curl -fsS -X POST "${BASE}/v1/human/tasks/${PRIORITY_SORT_OLDER_HIGH_MINE_ID}/assign" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" -H 'content-type: application/json' -d '{"operator_id":"operator-sorter"}')"
PRIORITY_SORT_ASSIGN_URGENT_JSON="$(curl -fsS -X POST "${BASE}/v1/human/tasks/${PRIORITY_SORT_NEWER_URGENT_MINE_ID}/assign" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" -H 'content-type: application/json' -d '{"operator_id":"operator-sorter"}')"
PRIORITY_SORT_ASSIGN_FIELDS="$(python3 -c "import json,sys; first=json.loads(sys.argv[1] or '{}'); second=json.loads(sys.argv[2] or '{}'); print('{}|{}|{}|{}'.format(first.get('human_task_id',''), first.get('last_transition_event_name',''), second.get('human_task_id',''), second.get('last_transition_event_name','')))" "${PRIORITY_SORT_ASSIGN_OLDER_JSON}" "${PRIORITY_SORT_ASSIGN_URGENT_JSON}")"
if [[ "${PRIORITY_SORT_ASSIGN_FIELDS}" != "${PRIORITY_SORT_OLDER_HIGH_MINE_ID}|human_task_assigned|${PRIORITY_SORT_NEWER_URGENT_MINE_ID}|human_task_assigned" ]]; then
  echo "expected priority-sort setup assignments to preserve assigned task ownership metadata; got ${PRIORITY_SORT_ASSIGN_FIELDS}" >&2
  echo "${PRIORITY_SORT_ASSIGN_OLDER_JSON}" >&2
  echo "${PRIORITY_SORT_ASSIGN_URGENT_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
PRIORITY_SORT_LIST_JSON="$(curl -fsS "${BASE}/v1/human/tasks?status=pending&sort=priority_desc_created_asc&limit=10" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}")"
PRIORITY_SORT_LIST_FIELDS="$(python3 -c "import json,sys; rows=json.loads(sys.stdin.read() or '[]'); wanted=['${PRIORITY_SORT_OLDEST_NORMAL_ID}','${PRIORITY_SORT_OLDER_HIGH_MINE_ID}','${PRIORITY_SORT_MIDDLE_HIGH_ID}','${PRIORITY_SORT_NEWER_URGENT_MINE_ID}','${PRIORITY_SORT_NEWEST_NORMAL_ID}']; filtered=[row for row in rows if (row or {}).get('human_task_id') in wanted]; ids=[(row or {}).get('human_task_id','') for row in filtered[:5]]; print('|'.join(ids))" <<<"${PRIORITY_SORT_LIST_JSON}")"
if [[ "${PRIORITY_SORT_LIST_FIELDS}" != "${PRIORITY_SORT_NEWER_URGENT_MINE_ID}|${PRIORITY_SORT_OLDER_HIGH_MINE_ID}|${PRIORITY_SORT_MIDDLE_HIGH_ID}|${PRIORITY_SORT_OLDEST_NORMAL_ID}|${PRIORITY_SORT_NEWEST_NORMAL_ID}" ]]; then
  echo "expected sort=priority_desc_created_asc to order pending work by priority first and oldest-created within each band; got ${PRIORITY_SORT_LIST_FIELDS}" >&2
  echo "${PRIORITY_SORT_LIST_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
PRIORITY_SORT_BACKLOG_JSON="$(curl -fsS "${BASE}/v1/human/tasks/backlog?sort=priority_desc_created_asc&limit=10" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}")"
PRIORITY_SORT_BACKLOG_FIELDS="$(python3 -c "import json,sys; rows=json.loads(sys.stdin.read() or '[]'); wanted=['${PRIORITY_SORT_OLDEST_NORMAL_ID}','${PRIORITY_SORT_OLDER_HIGH_MINE_ID}','${PRIORITY_SORT_MIDDLE_HIGH_ID}','${PRIORITY_SORT_NEWER_URGENT_MINE_ID}','${PRIORITY_SORT_NEWEST_NORMAL_ID}']; filtered=[row for row in rows if (row or {}).get('human_task_id') in wanted]; ids=[(row or {}).get('human_task_id','') for row in filtered[:5]]; print('|'.join(ids))" <<<"${PRIORITY_SORT_BACKLOG_JSON}")"
if [[ "${PRIORITY_SORT_BACKLOG_FIELDS}" != "${PRIORITY_SORT_NEWER_URGENT_MINE_ID}|${PRIORITY_SORT_OLDER_HIGH_MINE_ID}|${PRIORITY_SORT_MIDDLE_HIGH_ID}|${PRIORITY_SORT_OLDEST_NORMAL_ID}|${PRIORITY_SORT_NEWEST_NORMAL_ID}" ]]; then
  echo "expected backlog sort=priority_desc_created_asc to order pending work by priority first and oldest-created within each band; got ${PRIORITY_SORT_BACKLOG_FIELDS}" >&2
  echo "${PRIORITY_SORT_BACKLOG_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
PRIORITY_SORT_UNASSIGNED_JSON="$(curl -fsS "${BASE}/v1/human/tasks/unassigned?sort=priority_desc_created_asc&limit=10" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}")"
PRIORITY_SORT_UNASSIGNED_FIELDS="$(python3 -c "import json,sys; rows=json.loads(sys.stdin.read() or '[]'); wanted=['${PRIORITY_SORT_MIDDLE_HIGH_ID}','${PRIORITY_SORT_OLDEST_NORMAL_ID}','${PRIORITY_SORT_NEWEST_NORMAL_ID}']; filtered=[row for row in rows if (row or {}).get('human_task_id') in wanted]; ids=[(row or {}).get('human_task_id','') for row in filtered[:3]]; print('|'.join(ids))" <<<"${PRIORITY_SORT_UNASSIGNED_JSON}")"
if [[ "${PRIORITY_SORT_UNASSIGNED_FIELDS}" != "${PRIORITY_SORT_MIDDLE_HIGH_ID}|${PRIORITY_SORT_OLDEST_NORMAL_ID}|${PRIORITY_SORT_NEWEST_NORMAL_ID}" ]]; then
  echo "expected unassigned sort=priority_desc_created_asc to keep higher-priority work ahead of older normal tasks; got ${PRIORITY_SORT_UNASSIGNED_FIELDS}" >&2
  echo "${PRIORITY_SORT_UNASSIGNED_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
PRIORITY_SORT_MINE_JSON="$(curl -fsS "${BASE}/v1/human/tasks/mine?operator_id=operator-sorter&status=pending&sort=priority_desc_created_asc&limit=10" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}")"
PRIORITY_SORT_MINE_FIELDS="$(python3 -c "import json,sys; rows=json.loads(sys.stdin.read() or '[]'); wanted=['${PRIORITY_SORT_OLDER_HIGH_MINE_ID}','${PRIORITY_SORT_NEWER_URGENT_MINE_ID}']; filtered=[row for row in rows if (row or {}).get('human_task_id') in wanted]; ids=[(row or {}).get('human_task_id','') for row in filtered[:2]]; print('|'.join(ids))" <<<"${PRIORITY_SORT_MINE_JSON}")"
if [[ "${PRIORITY_SORT_MINE_FIELDS}" != "${PRIORITY_SORT_NEWER_URGENT_MINE_ID}|${PRIORITY_SORT_OLDER_HIGH_MINE_ID}" ]]; then
  echo "expected mine sort=priority_desc_created_asc to keep urgent assigned work ahead of older high-priority work; got ${PRIORITY_SORT_MINE_FIELDS}" >&2
  echo "${PRIORITY_SORT_MINE_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
echo "human task priority-desc-created-asc sort ok"

echo "== smoke: human task priority filter =="
PRIORITY_FILTER_REWRITE_JSON="$(curl -fsS -X POST "${BASE}/v1/rewrite/artifact" "${AUTH_ARGS[@]}" -H 'content-type: application/json' -d '{"text":"priority filter seed"}')"
PRIORITY_FILTER_SESSION_ID="$(python3 -c 'import json,sys; body=json.loads(sys.stdin.read() or "{}"); print(body.get("execution_session_id",""))' <<<"${PRIORITY_FILTER_REWRITE_JSON}")"
PRIORITY_FILTER_SESSION_JSON="$(curl -fsS "${BASE}/v1/rewrite/sessions/${PRIORITY_FILTER_SESSION_ID}" "${AUTH_ARGS[@]}")"
PRIORITY_FILTER_STEP_ID="$(python3 -c 'import json,sys; body=json.loads(sys.stdin.read() or "{}"); rows=body.get("steps") or []; print(((rows[-1] or {}).get("step_id")) if rows else "")' <<<"${PRIORITY_FILTER_SESSION_JSON}")"
PRIORITY_FILTER_ROLE="priority_filter_reviewer"
PRIORITY_FILTER_OPERATOR="operator-priority-filter"
if [[ -z "${PRIORITY_FILTER_STEP_ID}" ]]; then
  fail 13 "missing priority filter step_id from session response"
fi
PRIORITY_FILTER_NORMAL_JSON="$(curl -fsS -X POST "${BASE}/v1/human/tasks" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" -H 'content-type: application/json' \
  -d "{\"session_id\":\"${PRIORITY_FILTER_SESSION_ID}\",\"step_id\":\"${PRIORITY_FILTER_STEP_ID}\",\"task_type\":\"communications_review\",\"role_required\":\"${PRIORITY_FILTER_ROLE}\",\"brief\":\"Normal unassigned task.\",\"priority\":\"normal\",\"resume_session_on_return\":false}")"
PRIORITY_FILTER_NORMAL_ID="$(python3 -c 'import json,sys; body=json.loads(sys.stdin.read() or "{}"); print(body.get("human_task_id",""))' <<<"${PRIORITY_FILTER_NORMAL_JSON}")"
PRIORITY_FILTER_HIGH_MINE_JSON="$(curl -fsS -X POST "${BASE}/v1/human/tasks" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" -H 'content-type: application/json' \
  -d "{\"session_id\":\"${PRIORITY_FILTER_SESSION_ID}\",\"step_id\":\"${PRIORITY_FILTER_STEP_ID}\",\"task_type\":\"communications_review\",\"role_required\":\"${PRIORITY_FILTER_ROLE}\",\"brief\":\"High assigned task.\",\"priority\":\"high\",\"resume_session_on_return\":false}")"
PRIORITY_FILTER_HIGH_MINE_ID="$(python3 -c 'import json,sys; body=json.loads(sys.stdin.read() or "{}"); print(body.get("human_task_id",""))' <<<"${PRIORITY_FILTER_HIGH_MINE_JSON}")"
PRIORITY_FILTER_HIGH_UNASSIGNED_JSON="$(curl -fsS -X POST "${BASE}/v1/human/tasks" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" -H 'content-type: application/json' \
  -d "{\"session_id\":\"${PRIORITY_FILTER_SESSION_ID}\",\"step_id\":\"${PRIORITY_FILTER_STEP_ID}\",\"task_type\":\"communications_review\",\"role_required\":\"${PRIORITY_FILTER_ROLE}\",\"brief\":\"High unassigned task.\",\"priority\":\"high\",\"resume_session_on_return\":false}")"
PRIORITY_FILTER_HIGH_UNASSIGNED_ID="$(python3 -c 'import json,sys; body=json.loads(sys.stdin.read() or "{}"); print(body.get("human_task_id",""))' <<<"${PRIORITY_FILTER_HIGH_UNASSIGNED_JSON}")"
PRIORITY_FILTER_URGENT_MINE_JSON="$(curl -fsS -X POST "${BASE}/v1/human/tasks" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" -H 'content-type: application/json' \
  -d "{\"session_id\":\"${PRIORITY_FILTER_SESSION_ID}\",\"step_id\":\"${PRIORITY_FILTER_STEP_ID}\",\"task_type\":\"communications_review\",\"role_required\":\"${PRIORITY_FILTER_ROLE}\",\"brief\":\"Urgent assigned task.\",\"priority\":\"urgent\",\"resume_session_on_return\":false}")"
PRIORITY_FILTER_URGENT_MINE_ID="$(python3 -c 'import json,sys; body=json.loads(sys.stdin.read() or "{}"); print(body.get("human_task_id",""))' <<<"${PRIORITY_FILTER_URGENT_MINE_JSON}")"
if [[ -z "${PRIORITY_FILTER_NORMAL_ID}" || -z "${PRIORITY_FILTER_HIGH_MINE_ID}" || -z "${PRIORITY_FILTER_HIGH_UNASSIGNED_ID}" || -z "${PRIORITY_FILTER_URGENT_MINE_ID}" ]]; then
  fail 13 "missing human task ids from priority filter smoke setup"
fi
curl -fsS -X POST "${BASE}/v1/human/tasks/${PRIORITY_FILTER_HIGH_MINE_ID}/assign" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" -H 'content-type: application/json' -d "{\"operator_id\":\"${PRIORITY_FILTER_OPERATOR}\"}" >/dev/null
curl -fsS -X POST "${BASE}/v1/human/tasks/${PRIORITY_FILTER_URGENT_MINE_ID}/assign" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" -H 'content-type: application/json' -d "{\"operator_id\":\"${PRIORITY_FILTER_OPERATOR}\"}" >/dev/null
PRIORITY_FILTER_LIST_JSON="$(curl -fsS "${BASE}/v1/human/tasks?session_id=${PRIORITY_FILTER_SESSION_ID}&status=pending&role_required=${PRIORITY_FILTER_ROLE}&priority=high&sort=created_asc&limit=10" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}")"
PRIORITY_FILTER_LIST_FIELDS="$(python3 -c "import json,sys; rows=json.loads(sys.stdin.read() or '[]'); ids=[(row or {}).get('human_task_id','') for row in rows]; print('{}|{}|{}|{}'.format('|'.join([row for row in ids if row in ['${PRIORITY_FILTER_HIGH_MINE_ID}','${PRIORITY_FILTER_HIGH_UNASSIGNED_ID}']]), '${PRIORITY_FILTER_NORMAL_ID}' in ids, '${PRIORITY_FILTER_URGENT_MINE_ID}' in ids, len(ids)))" <<<"${PRIORITY_FILTER_LIST_JSON}")"
if [[ "${PRIORITY_FILTER_LIST_FIELDS}" != "${PRIORITY_FILTER_HIGH_MINE_ID}|${PRIORITY_FILTER_HIGH_UNASSIGNED_ID}|False|False|2" ]]; then
  echo "expected list priority filter to isolate only high-priority tasks in oldest-created order; got ${PRIORITY_FILTER_LIST_FIELDS}" >&2
  echo "${PRIORITY_FILTER_LIST_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
PRIORITY_FILTER_BACKLOG_JSON="$(curl -fsS "${BASE}/v1/human/tasks/backlog?role_required=${PRIORITY_FILTER_ROLE}&priority=high&sort=created_asc&limit=10" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}")"
PRIORITY_FILTER_BACKLOG_FIELDS="$(python3 -c "import json,sys; rows=json.loads(sys.stdin.read() or '[]'); ids=[(row or {}).get('human_task_id','') for row in rows]; print('{}|{}|{}|{}'.format('|'.join([row for row in ids if row in ['${PRIORITY_FILTER_HIGH_MINE_ID}','${PRIORITY_FILTER_HIGH_UNASSIGNED_ID}']]), '${PRIORITY_FILTER_NORMAL_ID}' in ids, '${PRIORITY_FILTER_URGENT_MINE_ID}' in ids, len(ids)))" <<<"${PRIORITY_FILTER_BACKLOG_JSON}")"
if [[ "${PRIORITY_FILTER_BACKLOG_FIELDS}" != "${PRIORITY_FILTER_HIGH_MINE_ID}|${PRIORITY_FILTER_HIGH_UNASSIGNED_ID}|False|False|2" ]]; then
  echo "expected backlog priority filter to isolate only high-priority tasks in oldest-created order; got ${PRIORITY_FILTER_BACKLOG_FIELDS}" >&2
  echo "${PRIORITY_FILTER_BACKLOG_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
PRIORITY_FILTER_UNASSIGNED_JSON="$(curl -fsS "${BASE}/v1/human/tasks/unassigned?role_required=${PRIORITY_FILTER_ROLE}&priority=high&sort=created_asc&limit=10" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}")"
PRIORITY_FILTER_UNASSIGNED_FIELDS="$(python3 -c "import json,sys; rows=json.loads(sys.stdin.read() or '[]'); ids=[(row or {}).get('human_task_id','') for row in rows]; print('{}|{}|{}'.format('|'.join([row for row in ids if row == '${PRIORITY_FILTER_HIGH_UNASSIGNED_ID}']), '${PRIORITY_FILTER_HIGH_MINE_ID}' in ids, len(ids)))" <<<"${PRIORITY_FILTER_UNASSIGNED_JSON}")"
if [[ "${PRIORITY_FILTER_UNASSIGNED_FIELDS}" != "${PRIORITY_FILTER_HIGH_UNASSIGNED_ID}|False|1" ]]; then
  echo "expected unassigned priority filter to isolate only unassigned high-priority work; got ${PRIORITY_FILTER_UNASSIGNED_FIELDS}" >&2
  echo "${PRIORITY_FILTER_UNASSIGNED_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
PRIORITY_FILTER_MINE_JSON="$(curl -fsS "${BASE}/v1/human/tasks/mine?operator_id=${PRIORITY_FILTER_OPERATOR}&status=pending&priority=urgent&sort=created_asc&limit=10" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}")"
PRIORITY_FILTER_MINE_FIELDS="$(python3 -c "import json,sys; rows=json.loads(sys.stdin.read() or '[]'); ids=[(row or {}).get('human_task_id','') for row in rows]; print('{}|{}|{}'.format('|'.join([row for row in ids if row == '${PRIORITY_FILTER_URGENT_MINE_ID}']), '${PRIORITY_FILTER_HIGH_MINE_ID}' in ids, len(ids)))" <<<"${PRIORITY_FILTER_MINE_JSON}")"
if [[ "${PRIORITY_FILTER_MINE_FIELDS}" != "${PRIORITY_FILTER_URGENT_MINE_ID}|False|1" ]]; then
  echo "expected mine priority filter to isolate only urgent assigned work; got ${PRIORITY_FILTER_MINE_FIELDS}" >&2
  echo "${PRIORITY_FILTER_MINE_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
echo "human task priority filter ok"

echo "== smoke: human task multi-priority filter =="
MULTI_PRIORITY_LIST_JSON="$(curl -fsS "${BASE}/v1/human/tasks?session_id=${PRIORITY_FILTER_SESSION_ID}&status=pending&role_required=${PRIORITY_FILTER_ROLE}&priority=urgent,high&sort=priority_desc_created_asc&limit=10" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}")"
MULTI_PRIORITY_LIST_FIELDS="$(python3 -c "import json,sys; rows=json.loads(sys.stdin.read() or '[]'); wanted=['${PRIORITY_FILTER_URGENT_MINE_ID}','${PRIORITY_FILTER_HIGH_MINE_ID}','${PRIORITY_FILTER_HIGH_UNASSIGNED_ID}']; filtered=[row for row in rows if (row or {}).get('human_task_id') in wanted]; ids=[(row or {}).get('human_task_id','') for row in filtered[:3]]; print('{}|{}|{}'.format('|'.join(ids), '${PRIORITY_FILTER_NORMAL_ID}' in [row.get('human_task_id','') for row in rows], len(rows)))" <<<"${MULTI_PRIORITY_LIST_JSON}")"
if [[ "${MULTI_PRIORITY_LIST_FIELDS}" != "${PRIORITY_FILTER_URGENT_MINE_ID}|${PRIORITY_FILTER_HIGH_MINE_ID}|${PRIORITY_FILTER_HIGH_UNASSIGNED_ID}|False|3" ]]; then
  echo "expected multi-priority list filter to return urgent and high tasks in priority-band order; got ${MULTI_PRIORITY_LIST_FIELDS}" >&2
  echo "${MULTI_PRIORITY_LIST_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
MULTI_PRIORITY_BACKLOG_JSON="$(curl -fsS "${BASE}/v1/human/tasks/backlog?role_required=${PRIORITY_FILTER_ROLE}&priority=urgent,high&sort=priority_desc_created_asc&limit=10" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}")"
MULTI_PRIORITY_BACKLOG_FIELDS="$(python3 -c "import json,sys; rows=json.loads(sys.stdin.read() or '[]'); wanted=['${PRIORITY_FILTER_URGENT_MINE_ID}','${PRIORITY_FILTER_HIGH_MINE_ID}','${PRIORITY_FILTER_HIGH_UNASSIGNED_ID}']; filtered=[row for row in rows if (row or {}).get('human_task_id') in wanted]; ids=[(row or {}).get('human_task_id','') for row in filtered[:3]]; print('{}|{}|{}'.format('|'.join(ids), '${PRIORITY_FILTER_NORMAL_ID}' in [row.get('human_task_id','') for row in rows], len(rows)))" <<<"${MULTI_PRIORITY_BACKLOG_JSON}")"
if [[ "${MULTI_PRIORITY_BACKLOG_FIELDS}" != "${PRIORITY_FILTER_URGENT_MINE_ID}|${PRIORITY_FILTER_HIGH_MINE_ID}|${PRIORITY_FILTER_HIGH_UNASSIGNED_ID}|False|3" ]]; then
  echo "expected multi-priority backlog filter to return urgent and high tasks in priority-band order; got ${MULTI_PRIORITY_BACKLOG_FIELDS}" >&2
  echo "${MULTI_PRIORITY_BACKLOG_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
MULTI_PRIORITY_UNASSIGNED_JSON="$(curl -fsS "${BASE}/v1/human/tasks/unassigned?role_required=${PRIORITY_FILTER_ROLE}&priority=urgent,high&sort=priority_desc_created_asc&limit=10" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}")"
MULTI_PRIORITY_UNASSIGNED_FIELDS="$(python3 -c "import json,sys; rows=json.loads(sys.stdin.read() or '[]'); ids=[(row or {}).get('human_task_id','') for row in rows]; print('{}|{}|{}'.format('|'.join([row for row in ids if row == '${PRIORITY_FILTER_HIGH_UNASSIGNED_ID}']), '${PRIORITY_FILTER_URGENT_MINE_ID}' in ids, len(ids)))" <<<"${MULTI_PRIORITY_UNASSIGNED_JSON}")"
if [[ "${MULTI_PRIORITY_UNASSIGNED_FIELDS}" != "${PRIORITY_FILTER_HIGH_UNASSIGNED_ID}|False|1" ]]; then
  echo "expected multi-priority unassigned filter to keep only high unassigned work when urgent tasks are assigned elsewhere; got ${MULTI_PRIORITY_UNASSIGNED_FIELDS}" >&2
  echo "${MULTI_PRIORITY_UNASSIGNED_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
MULTI_PRIORITY_MINE_JSON="$(curl -fsS "${BASE}/v1/human/tasks/mine?operator_id=${PRIORITY_FILTER_OPERATOR}&status=pending&priority=urgent,high&sort=priority_desc_created_asc&limit=10" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}")"
MULTI_PRIORITY_MINE_FIELDS="$(python3 -c "import json,sys; rows=json.loads(sys.stdin.read() or '[]'); wanted=['${PRIORITY_FILTER_URGENT_MINE_ID}','${PRIORITY_FILTER_HIGH_MINE_ID}']; filtered=[row for row in rows if (row or {}).get('human_task_id') in wanted]; ids=[(row or {}).get('human_task_id','') for row in filtered[:2]]; print('{}|{}|{}'.format('|'.join(ids), '${PRIORITY_FILTER_NORMAL_ID}' in [row.get('human_task_id','') for row in rows], len(rows)))" <<<"${MULTI_PRIORITY_MINE_JSON}")"
if [[ "${MULTI_PRIORITY_MINE_FIELDS}" != "${PRIORITY_FILTER_URGENT_MINE_ID}|${PRIORITY_FILTER_HIGH_MINE_ID}|False|2" ]]; then
  echo "expected multi-priority mine filter to return urgent and high assigned work in priority-band order; got ${MULTI_PRIORITY_MINE_FIELDS}" >&2
  echo "${MULTI_PRIORITY_MINE_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
echo "human task multi-priority filter ok"

echo "== smoke: human task priority summary =="
PRIORITY_SUMMARY_REWRITE_JSON="$(curl -fsS -X POST "${BASE}/v1/rewrite/artifact" "${AUTH_ARGS[@]}" -H 'content-type: application/json' -d '{"text":"priority summary seed"}')"
PRIORITY_SUMMARY_SESSION_ID="$(python3 -c 'import json,sys; body=json.loads(sys.stdin.read() or "{}"); print(body.get("execution_session_id",""))' <<<"${PRIORITY_SUMMARY_REWRITE_JSON}")"
PRIORITY_SUMMARY_SESSION_JSON="$(curl -fsS "${BASE}/v1/rewrite/sessions/${PRIORITY_SUMMARY_SESSION_ID}" "${AUTH_ARGS[@]}")"
PRIORITY_SUMMARY_STEP_ID="$(python3 -c 'import json,sys; body=json.loads(sys.stdin.read() or "{}"); rows=body.get("steps") or []; print(((rows[-1] or {}).get("step_id")) if rows else "")' <<<"${PRIORITY_SUMMARY_SESSION_JSON}")"
PRIORITY_SUMMARY_ROLE="priority_summary_reviewer"
if [[ -z "${PRIORITY_SUMMARY_STEP_ID}" ]]; then
  fail 13 "missing priority summary step_id from session response"
fi
curl -fsS -X POST "${BASE}/v1/human/tasks" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" -H 'content-type: application/json' \
  -d "{\"session_id\":\"${PRIORITY_SUMMARY_SESSION_ID}\",\"step_id\":\"${PRIORITY_SUMMARY_STEP_ID}\",\"task_type\":\"communications_review\",\"role_required\":\"${PRIORITY_SUMMARY_ROLE}\",\"brief\":\"Urgent task.\",\"priority\":\"urgent\",\"resume_session_on_return\":false}" >/tmp/ea_priority_summary_urgent.json
PRIORITY_SUMMARY_HIGH_ASSIGNED_JSON="$(curl -fsS -X POST "${BASE}/v1/human/tasks" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" -H 'content-type: application/json' \
  -d "{\"session_id\":\"${PRIORITY_SUMMARY_SESSION_ID}\",\"step_id\":\"${PRIORITY_SUMMARY_STEP_ID}\",\"task_type\":\"communications_review\",\"role_required\":\"${PRIORITY_SUMMARY_ROLE}\",\"brief\":\"High assigned task.\",\"priority\":\"high\",\"resume_session_on_return\":false}")"
PRIORITY_SUMMARY_HIGH_ASSIGNED_ID="$(python3 -c 'import json,sys; body=json.loads(sys.stdin.read() or "{}"); print(body.get("human_task_id",""))' <<<"${PRIORITY_SUMMARY_HIGH_ASSIGNED_JSON}")"
curl -fsS -X POST "${BASE}/v1/human/tasks" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" -H 'content-type: application/json' \
  -d "{\"session_id\":\"${PRIORITY_SUMMARY_SESSION_ID}\",\"step_id\":\"${PRIORITY_SUMMARY_STEP_ID}\",\"task_type\":\"communications_review\",\"role_required\":\"${PRIORITY_SUMMARY_ROLE}\",\"brief\":\"High unassigned task.\",\"priority\":\"high\",\"resume_session_on_return\":false}" >/tmp/ea_priority_summary_high_unassigned.json
curl -fsS -X POST "${BASE}/v1/human/tasks" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" -H 'content-type: application/json' \
  -d "{\"session_id\":\"${PRIORITY_SUMMARY_SESSION_ID}\",\"step_id\":\"${PRIORITY_SUMMARY_STEP_ID}\",\"task_type\":\"communications_review\",\"role_required\":\"${PRIORITY_SUMMARY_ROLE}\",\"brief\":\"Normal task.\",\"priority\":\"normal\",\"resume_session_on_return\":false}" >/tmp/ea_priority_summary_normal.json
PRIORITY_SUMMARY_OPERATOR="operator-priority-summary"
curl -fsS -X POST "${BASE}/v1/human/tasks/${PRIORITY_SUMMARY_HIGH_ASSIGNED_ID}/assign" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" -H 'content-type: application/json' -d "{\"operator_id\":\"${PRIORITY_SUMMARY_OPERATOR}\"}" >/dev/null
PRIORITY_SUMMARY_JSON="$(curl -fsS "${BASE}/v1/human/tasks/priority-summary?status=pending&role_required=${PRIORITY_SUMMARY_ROLE}" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}")"
PRIORITY_SUMMARY_FIELDS="$(python3 -c "import json,sys; body=json.loads(sys.stdin.read() or '{}'); counts=body.get('counts_json') or {}; print('{}|{}|{}|{}|{}|{}'.format(body.get('total',''), body.get('highest_priority',''), counts.get('urgent',''), counts.get('high',''), counts.get('normal',''), counts.get('low','')))" <<<"${PRIORITY_SUMMARY_JSON}")"
if [[ "${PRIORITY_SUMMARY_FIELDS}" != "4|urgent|1|2|1|0" ]]; then
  echo "expected priority summary to expose urgent/high/normal queue counts; got ${PRIORITY_SUMMARY_FIELDS}" >&2
  echo "${PRIORITY_SUMMARY_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
PRIORITY_SUMMARY_UNASSIGNED_JSON="$(curl -fsS "${BASE}/v1/human/tasks/priority-summary?status=pending&role_required=${PRIORITY_SUMMARY_ROLE}&assignment_state=unassigned" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}")"
PRIORITY_SUMMARY_UNASSIGNED_FIELDS="$(python3 -c "import json,sys; body=json.loads(sys.stdin.read() or '{}'); counts=body.get('counts_json') or {}; print('{}|{}|{}|{}|{}|{}'.format(body.get('total',''), body.get('highest_priority',''), counts.get('urgent',''), counts.get('high',''), counts.get('normal',''), counts.get('low','')))" <<<"${PRIORITY_SUMMARY_UNASSIGNED_JSON}")"
if [[ "${PRIORITY_SUMMARY_UNASSIGNED_FIELDS}" != "3|urgent|1|1|1|0" ]]; then
  echo "expected unassigned priority summary to remove the assigned high-priority task while preserving band counts; got ${PRIORITY_SUMMARY_UNASSIGNED_FIELDS}" >&2
  echo "${PRIORITY_SUMMARY_UNASSIGNED_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
PRIORITY_SUMMARY_ASSIGNED_JSON="$(curl -fsS "${BASE}/v1/human/tasks/priority-summary?status=pending&role_required=${PRIORITY_SUMMARY_ROLE}&assigned_operator_id=${PRIORITY_SUMMARY_OPERATOR}" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}")"
PRIORITY_SUMMARY_ASSIGNED_FIELDS="$(python3 -c "import json,sys; body=json.loads(sys.stdin.read() or '{}'); counts=body.get('counts_json') or {}; print('{}|{}|{}|{}|{}|{}|{}'.format(body.get('assigned_operator_id',''), body.get('total',''), body.get('highest_priority',''), counts.get('urgent',''), counts.get('high',''), counts.get('normal',''), counts.get('low','')))" <<<"${PRIORITY_SUMMARY_ASSIGNED_JSON}")"
if [[ "${PRIORITY_SUMMARY_ASSIGNED_FIELDS}" != "${PRIORITY_SUMMARY_OPERATOR}|1|high|0|1|0|0" ]]; then
  echo "expected assigned-operator priority summary to isolate only the assigned reviewer queue; got ${PRIORITY_SUMMARY_ASSIGNED_FIELDS}" >&2
  echo "${PRIORITY_SUMMARY_ASSIGNED_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
PRIORITY_SUMMARY_MANUAL_JSON="$(curl -fsS "${BASE}/v1/human/tasks/priority-summary?status=pending&role_required=${PRIORITY_SUMMARY_ROLE}&assignment_source=manual" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}")"
PRIORITY_SUMMARY_MANUAL_FIELDS="$(python3 -c "import json,sys; body=json.loads(sys.stdin.read() or '{}'); counts=body.get('counts_json') or {}; print('{}|{}|{}|{}|{}|{}|{}'.format(body.get('assignment_source',''), body.get('total',''), body.get('highest_priority',''), counts.get('urgent',''), counts.get('high',''), counts.get('normal',''), counts.get('low','')))" <<<"${PRIORITY_SUMMARY_MANUAL_JSON}")"
if [[ "${PRIORITY_SUMMARY_MANUAL_FIELDS}" != "manual|1|high|0|1|0|0" ]]; then
  echo "expected assignment-source priority summary to isolate manually assigned pending work; got ${PRIORITY_SUMMARY_MANUAL_FIELDS}" >&2
  echo "${PRIORITY_SUMMARY_MANUAL_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
PRIORITY_SUMMARY_MANUAL_LIST_JSON="$(curl -fsS "${BASE}/v1/human/tasks?status=pending&role_required=${PRIORITY_SUMMARY_ROLE}&assignment_source=manual&limit=10" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}")"
PRIORITY_SUMMARY_MANUAL_LIST_FIELDS="$(python3 -c "import json,sys; rows=json.loads(sys.stdin.read() or '[]'); wanted='${PRIORITY_SUMMARY_HIGH_ASSIGNED_ID}'; print(any((row or {}).get('human_task_id') == wanted for row in rows))" <<<"${PRIORITY_SUMMARY_MANUAL_LIST_JSON}")"
if [[ "${PRIORITY_SUMMARY_MANUAL_LIST_FIELDS}" != "True" ]]; then
  echo "expected assignment-source list filter to expose manually assigned pending work" >&2
  echo "${PRIORITY_SUMMARY_MANUAL_LIST_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
PRIORITY_SUMMARY_MANUAL_MINE_JSON="$(curl -fsS "${BASE}/v1/human/tasks/mine?operator_id=${PRIORITY_SUMMARY_OPERATOR}&assignment_source=manual&limit=10" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}")"
PRIORITY_SUMMARY_MANUAL_MINE_FIELDS="$(python3 -c "import json,sys; rows=json.loads(sys.stdin.read() or '[]'); wanted='${PRIORITY_SUMMARY_HIGH_ASSIGNED_ID}'; print(any((row or {}).get('human_task_id') == wanted for row in rows))" <<<"${PRIORITY_SUMMARY_MANUAL_MINE_JSON}")"
if [[ "${PRIORITY_SUMMARY_MANUAL_MINE_FIELDS}" != "True" ]]; then
  echo "expected assignment-source mine filter to expose manually assigned pending reviewer work" >&2
  echo "${PRIORITY_SUMMARY_MANUAL_MINE_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
PRIORITY_SUMMARY_MANUAL_SESSION_JSON="$(curl -fsS "${BASE}/v1/human/tasks?session_id=${PRIORITY_SUMMARY_SESSION_ID}&assignment_source=manual&limit=10" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}")"
PRIORITY_SUMMARY_MANUAL_SESSION_FIELDS="$(python3 -c "import json,sys; rows=json.loads(sys.stdin.read() or '[]'); wanted='${PRIORITY_SUMMARY_HIGH_ASSIGNED_ID}'; print(any((row or {}).get('human_task_id') == wanted for row in rows))" <<<"${PRIORITY_SUMMARY_MANUAL_SESSION_JSON}")"
if [[ "${PRIORITY_SUMMARY_MANUAL_SESSION_FIELDS}" != "True" ]]; then
  echo "expected session-scoped assignment-source list filter to expose manually assigned pending reviewer work" >&2
  echo "${PRIORITY_SUMMARY_MANUAL_SESSION_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
PRIORITY_SUMMARY_MATCH_ROLE="matched_priority_summary_reviewer"
PRIORITY_SUMMARY_SCHED_ROLE="matched_priority_summary_scheduler"
curl -fsS -X POST "${BASE}/v1/human/tasks/operators" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" -H 'content-type: application/json' \
  -d "{\"operator_id\":\"operator-specialist-summary\",\"display_name\":\"Senior Comms Reviewer\",\"roles\":[\"${PRIORITY_SUMMARY_MATCH_ROLE}\"],\"skill_tags\":[\"tone\",\"accuracy\",\"stakeholder_sensitivity\"],\"trust_tier\":\"senior\",\"status\":\"active\"}" >/dev/null
curl -fsS -X POST "${BASE}/v1/human/tasks/operators" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" -H 'content-type: application/json' \
  -d "{\"operator_id\":\"operator-junior-summary\",\"display_name\":\"Junior Reviewer\",\"roles\":[\"${PRIORITY_SUMMARY_MATCH_ROLE}\"],\"skill_tags\":[\"tone\"],\"trust_tier\":\"standard\",\"status\":\"active\"}" >/dev/null
curl -fsS -X POST "${BASE}/v1/human/tasks/operators" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" -H 'content-type: application/json' \
  -d "{\"operator_id\":\"operator-scheduler-summary\",\"display_name\":\"Scheduler\",\"roles\":[\"${PRIORITY_SUMMARY_SCHED_ROLE}\"],\"skill_tags\":[\"calendar\"],\"trust_tier\":\"standard\",\"status\":\"active\"}" >/dev/null
curl -fsS -X POST "${BASE}/v1/human/tasks" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" -H 'content-type: application/json' \
  -d "{\"session_id\":\"${PRIORITY_SUMMARY_SESSION_ID}\",\"step_id\":\"${PRIORITY_SUMMARY_STEP_ID}\",\"task_type\":\"communications_review\",\"role_required\":\"${PRIORITY_SUMMARY_MATCH_ROLE}\",\"brief\":\"Urgent specialist-only task.\",\"authority_required\":\"send_on_behalf_review\",\"quality_rubric_json\":{\"checks\":[\"tone\",\"accuracy\",\"stakeholder_sensitivity\"]},\"priority\":\"urgent\",\"resume_session_on_return\":false}" >/tmp/ea_priority_summary_match_urgent.json
curl -fsS -X POST "${BASE}/v1/human/tasks" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" -H 'content-type: application/json' \
  -d "{\"session_id\":\"${PRIORITY_SUMMARY_SESSION_ID}\",\"step_id\":\"${PRIORITY_SUMMARY_STEP_ID}\",\"task_type\":\"communications_review\",\"role_required\":\"${PRIORITY_SUMMARY_MATCH_ROLE}\",\"brief\":\"High specialist-only task.\",\"authority_required\":\"send_on_behalf_review\",\"quality_rubric_json\":{\"checks\":[\"tone\",\"accuracy\",\"stakeholder_sensitivity\"]},\"priority\":\"high\",\"resume_session_on_return\":false}" >/tmp/ea_priority_summary_match_high.json
curl -fsS -X POST "${BASE}/v1/human/tasks" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" -H 'content-type: application/json' \
  -d "{\"session_id\":\"${PRIORITY_SUMMARY_SESSION_ID}\",\"step_id\":\"${PRIORITY_SUMMARY_STEP_ID}\",\"task_type\":\"schedule_review\",\"role_required\":\"${PRIORITY_SUMMARY_SCHED_ROLE}\",\"brief\":\"Normal scheduler task.\",\"priority\":\"normal\",\"resume_session_on_return\":false}" >/tmp/ea_priority_summary_match_scheduler.json
PRIORITY_SUMMARY_MATCHED_JSON="$(curl -fsS "${BASE}/v1/human/tasks/priority-summary?status=pending&assignment_state=unassigned&operator_id=operator-specialist-summary" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}")"
PRIORITY_SUMMARY_MATCHED_FIELDS="$(python3 -c "import json,sys; body=json.loads(sys.stdin.read() or '{}'); counts=body.get('counts_json') or {}; print('{}|{}|{}|{}|{}|{}|{}'.format(body.get('operator_id',''), body.get('total',''), body.get('highest_priority',''), counts.get('urgent',''), counts.get('high',''), counts.get('normal',''), counts.get('low','')))" <<<"${PRIORITY_SUMMARY_MATCHED_JSON}")"
if [[ "${PRIORITY_SUMMARY_MATCHED_FIELDS}" != "operator-specialist-summary|2|urgent|1|1|0|0" ]]; then
  echo "expected operator-matched priority summary to count only specialist-ready unclaimed work; got ${PRIORITY_SUMMARY_MATCHED_FIELDS}" >&2
  echo "${PRIORITY_SUMMARY_MATCHED_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
PRIORITY_SUMMARY_MATCHED_LOW_JSON="$(curl -fsS "${BASE}/v1/human/tasks/priority-summary?status=pending&assignment_state=unassigned&operator_id=operator-junior-summary" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}")"
PRIORITY_SUMMARY_MATCHED_LOW_FIELDS="$(python3 -c "import json,sys; body=json.loads(sys.stdin.read() or '{}'); counts=body.get('counts_json') or {}; print('{}|{}|{}|{}|{}|{}|{}'.format(body.get('operator_id',''), body.get('total',''), body.get('highest_priority',''), counts.get('urgent',''), counts.get('high',''), counts.get('normal',''), counts.get('low','')))" <<<"${PRIORITY_SUMMARY_MATCHED_LOW_JSON}")"
if [[ "${PRIORITY_SUMMARY_MATCHED_LOW_FIELDS}" != "operator-junior-summary|0||0|0|0|0" ]]; then
  echo "expected operator-matched priority summary to exclude under-skilled or under-trust reviewers; got ${PRIORITY_SUMMARY_MATCHED_LOW_FIELDS}" >&2
  echo "${PRIORITY_SUMMARY_MATCHED_LOW_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
PRIORITY_SUMMARY_MATCHED_SCHED_JSON="$(curl -fsS "${BASE}/v1/human/tasks/priority-summary?status=pending&assignment_state=unassigned&operator_id=operator-scheduler-summary" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}")"
PRIORITY_SUMMARY_MATCHED_SCHED_FIELDS="$(python3 -c "import json,sys; body=json.loads(sys.stdin.read() or '{}'); counts=body.get('counts_json') or {}; print('{}|{}|{}|{}|{}|{}|{}'.format(body.get('operator_id',''), body.get('total',''), body.get('highest_priority',''), counts.get('urgent',''), counts.get('high',''), counts.get('normal',''), counts.get('low','')))" <<<"${PRIORITY_SUMMARY_MATCHED_SCHED_JSON}")"
if [[ "${PRIORITY_SUMMARY_MATCHED_SCHED_FIELDS}" != "operator-scheduler-summary|1|normal|0|0|1|0" ]]; then
  echo "expected operator-matched priority summary to isolate scheduler-role work separately from comms review packets; got ${PRIORITY_SUMMARY_MATCHED_SCHED_FIELDS}" >&2
  echo "${PRIORITY_SUMMARY_MATCHED_SCHED_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
rm -f /tmp/ea_priority_summary_urgent.json /tmp/ea_priority_summary_high_unassigned.json /tmp/ea_priority_summary_normal.json /tmp/ea_priority_summary_match_urgent.json /tmp/ea_priority_summary_match_high.json /tmp/ea_priority_summary_match_scheduler.json
echo "human task priority summary ok"

echo "== smoke: human task SLA sort =="
SLA_REWRITE_JSON="$(curl -fsS -X POST "${BASE}/v1/rewrite/artifact" "${AUTH_ARGS[@]}" -H 'content-type: application/json' -d '{"text":"sla sort seed"}')"
SLA_SESSION_ID="$(python3 -c 'import json,sys; body=json.loads(sys.stdin.read() or "{}"); print(body.get("execution_session_id",""))' <<<"${SLA_REWRITE_JSON}")"
SLA_SESSION_JSON="$(curl -fsS "${BASE}/v1/rewrite/sessions/${SLA_SESSION_ID}" "${AUTH_ARGS[@]}")"
SLA_STEP_ID="$(python3 -c 'import json,sys; body=json.loads(sys.stdin.read() or "{}"); rows=body.get("steps") or []; print(((rows[-1] or {}).get("step_id")) if rows else "")' <<<"${SLA_SESSION_JSON}")"
if [[ -z "${SLA_STEP_ID}" ]]; then
  fail 13 "missing sla sort step_id from session response"
fi
SLA_TASK_LATE_JSON="$(curl -fsS -X POST "${BASE}/v1/human/tasks" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" -H 'content-type: application/json' \
  -d "{\"session_id\":\"${SLA_SESSION_ID}\",\"step_id\":\"${SLA_STEP_ID}\",\"task_type\":\"communications_review\",\"role_required\":\"communications_reviewer\",\"brief\":\"Later due task.\",\"sla_due_at\":\"2100-01-02T00:00:00+00:00\",\"resume_session_on_return\":false}")"
SLA_TASK_LATE_ID="$(python3 -c 'import json,sys; body=json.loads(sys.stdin.read() or "{}"); print(body.get("human_task_id",""))' <<<"${SLA_TASK_LATE_JSON}")"
SLA_TASK_SOON_JSON="$(curl -fsS -X POST "${BASE}/v1/human/tasks" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" -H 'content-type: application/json' \
  -d "{\"session_id\":\"${SLA_SESSION_ID}\",\"step_id\":\"${SLA_STEP_ID}\",\"task_type\":\"communications_review\",\"role_required\":\"communications_reviewer\",\"brief\":\"Sooner due task.\",\"sla_due_at\":\"2100-01-01T00:00:00+00:00\",\"resume_session_on_return\":false}")"
SLA_TASK_SOON_ID="$(python3 -c 'import json,sys; body=json.loads(sys.stdin.read() or "{}"); print(body.get("human_task_id",""))' <<<"${SLA_TASK_SOON_JSON}")"
if [[ -z "${SLA_TASK_LATE_ID}" || -z "${SLA_TASK_SOON_ID}" ]]; then
  fail 13 "missing human task ids from sla sort smoke setup"
fi
SLA_LIST_JSON="$(curl -fsS "${BASE}/v1/human/tasks?status=pending&sort=sla_due_at_asc&limit=10" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}")"
SLA_LIST_FIELDS="$(python3 -c "import json,sys; rows=json.loads(sys.stdin.read() or '[]'); wanted=['${SLA_TASK_SOON_ID}','${SLA_TASK_LATE_ID}']; filtered=[row for row in rows if (row or {}).get('human_task_id') in wanted]; first=(filtered[0] if len(filtered) > 0 else {}); second=(filtered[1] if len(filtered) > 1 else {}); print('{}|{}'.format(first.get('human_task_id',''), second.get('human_task_id','')))" <<<"${SLA_LIST_JSON}")"
if [[ "${SLA_LIST_FIELDS}" != "${SLA_TASK_SOON_ID}|${SLA_TASK_LATE_ID}" ]]; then
  echo "expected sort=sla_due_at_asc to order general human task list by earliest SLA first; got ${SLA_LIST_FIELDS}" >&2
  echo "${SLA_LIST_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
SLA_BACKLOG_JSON="$(curl -fsS "${BASE}/v1/human/tasks/backlog?sort=sla_due_at_asc&limit=10" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}")"
SLA_BACKLOG_FIELDS="$(python3 -c "import json,sys; rows=json.loads(sys.stdin.read() or '[]'); wanted=['${SLA_TASK_SOON_ID}','${SLA_TASK_LATE_ID}']; filtered=[row for row in rows if (row or {}).get('human_task_id') in wanted]; first=(filtered[0] if len(filtered) > 0 else {}); second=(filtered[1] if len(filtered) > 1 else {}); print('{}|{}'.format(first.get('human_task_id',''), second.get('human_task_id','')))" <<<"${SLA_BACKLOG_JSON}")"
if [[ "${SLA_BACKLOG_FIELDS}" != "${SLA_TASK_SOON_ID}|${SLA_TASK_LATE_ID}" ]]; then
  echo "expected backlog sort=sla_due_at_asc to order pending work by earliest SLA first; got ${SLA_BACKLOG_FIELDS}" >&2
  echo "${SLA_BACKLOG_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
echo "human task SLA sort ok"

echo "== smoke: human task combined SLA + transition sort =="
COMBINED_REWRITE_JSON="$(curl -fsS -X POST "${BASE}/v1/rewrite/artifact" "${AUTH_ARGS[@]}" -H 'content-type: application/json' -d '{"text":"combined sort seed"}')"
COMBINED_SESSION_ID="$(python3 -c 'import json,sys; body=json.loads(sys.stdin.read() or "{}"); print(body.get("execution_session_id",""))' <<<"${COMBINED_REWRITE_JSON}")"
COMBINED_SESSION_JSON="$(curl -fsS "${BASE}/v1/rewrite/sessions/${COMBINED_SESSION_ID}" "${AUTH_ARGS[@]}")"
COMBINED_STEP_ID="$(python3 -c 'import json,sys; body=json.loads(sys.stdin.read() or "{}"); rows=body.get("steps") or []; print(((rows[-1] or {}).get("step_id")) if rows else "")' <<<"${COMBINED_SESSION_JSON}")"
if [[ -z "${COMBINED_STEP_ID}" ]]; then
  fail 13 "missing combined sort step_id from session response"
fi
COMBINED_TASK_STALE_JSON="$(curl -fsS -X POST "${BASE}/v1/human/tasks" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" -H 'content-type: application/json' \
  -d "{\"session_id\":\"${COMBINED_SESSION_ID}\",\"step_id\":\"${COMBINED_STEP_ID}\",\"task_type\":\"communications_review\",\"role_required\":\"communications_reviewer\",\"brief\":\"Earlier due stale task.\",\"sla_due_at\":\"2100-01-01T00:00:00+00:00\",\"resume_session_on_return\":false}")"
COMBINED_TASK_STALE_ID="$(python3 -c 'import json,sys; body=json.loads(sys.stdin.read() or "{}"); print(body.get("human_task_id",""))' <<<"${COMBINED_TASK_STALE_JSON}")"
COMBINED_TASK_RECENT_JSON="$(curl -fsS -X POST "${BASE}/v1/human/tasks" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" -H 'content-type: application/json' \
  -d "{\"session_id\":\"${COMBINED_SESSION_ID}\",\"step_id\":\"${COMBINED_STEP_ID}\",\"task_type\":\"communications_review\",\"role_required\":\"communications_reviewer\",\"brief\":\"Earlier due recently touched task.\",\"sla_due_at\":\"2100-01-01T00:00:00+00:00\",\"resume_session_on_return\":false}")"
COMBINED_TASK_RECENT_ID="$(python3 -c 'import json,sys; body=json.loads(sys.stdin.read() or "{}"); print(body.get("human_task_id",""))' <<<"${COMBINED_TASK_RECENT_JSON}")"
COMBINED_TASK_LATE_JSON="$(curl -fsS -X POST "${BASE}/v1/human/tasks" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" -H 'content-type: application/json' \
  -d "{\"session_id\":\"${COMBINED_SESSION_ID}\",\"step_id\":\"${COMBINED_STEP_ID}\",\"task_type\":\"communications_review\",\"role_required\":\"communications_reviewer\",\"brief\":\"Later due task.\",\"sla_due_at\":\"2100-01-02T00:00:00+00:00\",\"resume_session_on_return\":false}")"
COMBINED_TASK_LATE_ID="$(python3 -c 'import json,sys; body=json.loads(sys.stdin.read() or "{}"); print(body.get("human_task_id",""))' <<<"${COMBINED_TASK_LATE_JSON}")"
if [[ -z "${COMBINED_TASK_STALE_ID}" || -z "${COMBINED_TASK_RECENT_ID}" || -z "${COMBINED_TASK_LATE_ID}" ]]; then
  fail 13 "missing human task ids from combined sort smoke setup"
fi
COMBINED_ASSIGN_JSON="$(curl -fsS -X POST "${BASE}/v1/human/tasks/${COMBINED_TASK_RECENT_ID}/assign" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" -H 'content-type: application/json' -d '{"operator_id":"operator-sorter"}')"
COMBINED_ASSIGN_FIELDS="$(python3 -c 'import json,sys; body=json.loads(sys.stdin.read() or "{}"); print("{}|{}".format(body.get("human_task_id",""), body.get("last_transition_event_name","")))' <<<"${COMBINED_ASSIGN_JSON}")"
if [[ "${COMBINED_ASSIGN_FIELDS}" != "${COMBINED_TASK_RECENT_ID}|human_task_assigned" ]]; then
  echo "expected combined-sort setup assignment to mark the tied-SLA task as recently touched; got ${COMBINED_ASSIGN_FIELDS}" >&2
  echo "${COMBINED_ASSIGN_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
COMBINED_LIST_JSON="$(curl -fsS "${BASE}/v1/human/tasks?status=pending&sort=sla_due_at_asc_last_transition_desc&limit=10" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}")"
COMBINED_LIST_FIELDS="$(python3 -c "import json,sys; rows=json.loads(sys.stdin.read() or '[]'); wanted=['${COMBINED_TASK_RECENT_ID}','${COMBINED_TASK_STALE_ID}','${COMBINED_TASK_LATE_ID}']; filtered=[row for row in rows if (row or {}).get('human_task_id') in wanted]; ids=[(row or {}).get('human_task_id','') for row in filtered[:3]]; print('|'.join(ids))" <<<"${COMBINED_LIST_JSON}")"
if [[ "${COMBINED_LIST_FIELDS}" != "${COMBINED_TASK_RECENT_ID}|${COMBINED_TASK_STALE_ID}|${COMBINED_TASK_LATE_ID}" ]]; then
  echo "expected sort=sla_due_at_asc_last_transition_desc to break SLA ties by freshest transition in the general list; got ${COMBINED_LIST_FIELDS}" >&2
  echo "${COMBINED_LIST_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
COMBINED_BACKLOG_JSON="$(curl -fsS "${BASE}/v1/human/tasks/backlog?sort=sla_due_at_asc_last_transition_desc&limit=10" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}")"
COMBINED_BACKLOG_FIELDS="$(python3 -c "import json,sys; rows=json.loads(sys.stdin.read() or '[]'); wanted=['${COMBINED_TASK_RECENT_ID}','${COMBINED_TASK_STALE_ID}','${COMBINED_TASK_LATE_ID}']; filtered=[row for row in rows if (row or {}).get('human_task_id') in wanted]; ids=[(row or {}).get('human_task_id','') for row in filtered[:3]]; print('|'.join(ids))" <<<"${COMBINED_BACKLOG_JSON}")"
if [[ "${COMBINED_BACKLOG_FIELDS}" != "${COMBINED_TASK_RECENT_ID}|${COMBINED_TASK_STALE_ID}|${COMBINED_TASK_LATE_ID}" ]]; then
  echo "expected backlog sort=sla_due_at_asc_last_transition_desc to break SLA ties by freshest transition; got ${COMBINED_BACKLOG_FIELDS}" >&2
  echo "${COMBINED_BACKLOG_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
echo "human task combined sort ok"

echo "== smoke: human task unscheduled fallback sort =="
UNSCHED_REWRITE_JSON="$(curl -fsS -X POST "${BASE}/v1/rewrite/artifact" "${AUTH_ARGS[@]}" -H 'content-type: application/json' -d '{"text":"unscheduled fallback seed"}')"
UNSCHED_SESSION_ID="$(python3 -c 'import json,sys; body=json.loads(sys.stdin.read() or "{}"); print(body.get("execution_session_id",""))' <<<"${UNSCHED_REWRITE_JSON}")"
UNSCHED_SESSION_JSON="$(curl -fsS "${BASE}/v1/rewrite/sessions/${UNSCHED_SESSION_ID}" "${AUTH_ARGS[@]}")"
UNSCHED_STEP_ID="$(python3 -c 'import json,sys; body=json.loads(sys.stdin.read() or "{}"); rows=body.get("steps") or []; print(((rows[-1] or {}).get("step_id")) if rows else "")' <<<"${UNSCHED_SESSION_JSON}")"
if [[ -z "${UNSCHED_STEP_ID}" ]]; then
  fail 13 "missing unscheduled fallback step_id from session response"
fi
UNSCHED_DUE_JSON="$(curl -fsS -X POST "${BASE}/v1/human/tasks" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" -H 'content-type: application/json' \
  -d "{\"session_id\":\"${UNSCHED_SESSION_ID}\",\"step_id\":\"${UNSCHED_STEP_ID}\",\"task_type\":\"communications_review\",\"role_required\":\"communications_reviewer\",\"brief\":\"Scheduled task.\",\"sla_due_at\":\"2100-01-01T00:00:00+00:00\",\"resume_session_on_return\":false}")"
UNSCHED_DUE_ID="$(python3 -c 'import json,sys; body=json.loads(sys.stdin.read() or "{}"); print(body.get("human_task_id",""))' <<<"${UNSCHED_DUE_JSON}")"
UNSCHED_OLDER_JSON="$(curl -fsS -X POST "${BASE}/v1/human/tasks" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" -H 'content-type: application/json' \
  -d "{\"session_id\":\"${UNSCHED_SESSION_ID}\",\"step_id\":\"${UNSCHED_STEP_ID}\",\"task_type\":\"communications_review\",\"role_required\":\"communications_reviewer\",\"brief\":\"Older unscheduled task.\",\"resume_session_on_return\":false}")"
UNSCHED_OLDER_ID="$(python3 -c 'import json,sys; body=json.loads(sys.stdin.read() or "{}"); print(body.get("human_task_id",""))' <<<"${UNSCHED_OLDER_JSON}")"
UNSCHED_NEWER_JSON="$(curl -fsS -X POST "${BASE}/v1/human/tasks" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" -H 'content-type: application/json' \
  -d "{\"session_id\":\"${UNSCHED_SESSION_ID}\",\"step_id\":\"${UNSCHED_STEP_ID}\",\"task_type\":\"communications_review\",\"role_required\":\"communications_reviewer\",\"brief\":\"Newer unscheduled task.\",\"resume_session_on_return\":false}")"
UNSCHED_NEWER_ID="$(python3 -c 'import json,sys; body=json.loads(sys.stdin.read() or "{}"); print(body.get("human_task_id",""))' <<<"${UNSCHED_NEWER_JSON}")"
if [[ -z "${UNSCHED_DUE_ID}" || -z "${UNSCHED_OLDER_ID}" || -z "${UNSCHED_NEWER_ID}" ]]; then
  fail 13 "missing human task ids from unscheduled fallback smoke setup"
fi
UNSCHED_ASSIGN_JSON="$(curl -fsS -X POST "${BASE}/v1/human/tasks/${UNSCHED_NEWER_ID}/assign" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" -H 'content-type: application/json' -d '{"operator_id":"operator-sorter"}')"
UNSCHED_ASSIGN_FIELDS="$(python3 -c 'import json,sys; body=json.loads(sys.stdin.read() or "{}"); print("{}|{}".format(body.get("human_task_id",""), body.get("last_transition_event_name","")))' <<<"${UNSCHED_ASSIGN_JSON}")"
if [[ "${UNSCHED_ASSIGN_FIELDS}" != "${UNSCHED_NEWER_ID}|human_task_assigned" ]]; then
  echo "expected unscheduled fallback setup assignment to mark the newer no-SLA task as recently touched; got ${UNSCHED_ASSIGN_FIELDS}" >&2
  echo "${UNSCHED_ASSIGN_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
UNSCHED_SLA_LIST_JSON="$(curl -fsS "${BASE}/v1/human/tasks?status=pending&sort=sla_due_at_asc&limit=10" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}")"
UNSCHED_SLA_LIST_FIELDS="$(python3 -c "import json,sys; rows=json.loads(sys.stdin.read() or '[]'); wanted=['${UNSCHED_DUE_ID}','${UNSCHED_OLDER_ID}','${UNSCHED_NEWER_ID}']; filtered=[row for row in rows if (row or {}).get('human_task_id') in wanted]; ids=[(row or {}).get('human_task_id','') for row in filtered[:3]]; print('|'.join(ids))" <<<"${UNSCHED_SLA_LIST_JSON}")"
if [[ "${UNSCHED_SLA_LIST_FIELDS}" != "${UNSCHED_DUE_ID}|${UNSCHED_OLDER_ID}|${UNSCHED_NEWER_ID}" ]]; then
  echo "expected sort=sla_due_at_asc to keep unscheduled work in oldest-created order after scheduled work; got ${UNSCHED_SLA_LIST_FIELDS}" >&2
  echo "${UNSCHED_SLA_LIST_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
UNSCHED_COMBINED_LIST_JSON="$(curl -fsS "${BASE}/v1/human/tasks?status=pending&sort=sla_due_at_asc_last_transition_desc&limit=10" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}")"
UNSCHED_COMBINED_LIST_FIELDS="$(python3 -c "import json,sys; rows=json.loads(sys.stdin.read() or '[]'); wanted=['${UNSCHED_DUE_ID}','${UNSCHED_OLDER_ID}','${UNSCHED_NEWER_ID}']; filtered=[row for row in rows if (row or {}).get('human_task_id') in wanted]; ids=[(row or {}).get('human_task_id','') for row in filtered[:3]]; print('|'.join(ids))" <<<"${UNSCHED_COMBINED_LIST_JSON}")"
if [[ "${UNSCHED_COMBINED_LIST_FIELDS}" != "${UNSCHED_DUE_ID}|${UNSCHED_OLDER_ID}|${UNSCHED_NEWER_ID}" ]]; then
  echo "expected combined sort to keep unscheduled work in oldest-created order after scheduled work; got ${UNSCHED_COMBINED_LIST_FIELDS}" >&2
  echo "${UNSCHED_COMBINED_LIST_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
UNSCHED_COMBINED_BACKLOG_JSON="$(curl -fsS "${BASE}/v1/human/tasks/backlog?sort=sla_due_at_asc_last_transition_desc&limit=10" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}")"
UNSCHED_COMBINED_BACKLOG_FIELDS="$(python3 -c "import json,sys; rows=json.loads(sys.stdin.read() or '[]'); wanted=['${UNSCHED_DUE_ID}','${UNSCHED_OLDER_ID}','${UNSCHED_NEWER_ID}']; filtered=[row for row in rows if (row or {}).get('human_task_id') in wanted]; ids=[(row or {}).get('human_task_id','') for row in filtered[:3]]; print('|'.join(ids))" <<<"${UNSCHED_COMBINED_BACKLOG_JSON}")"
if [[ "${UNSCHED_COMBINED_BACKLOG_FIELDS}" != "${UNSCHED_DUE_ID}|${UNSCHED_OLDER_ID}|${UNSCHED_NEWER_ID}" ]]; then
  echo "expected combined backlog sort to keep unscheduled work in oldest-created order after scheduled work; got ${UNSCHED_COMBINED_BACKLOG_FIELDS}" >&2
  echo "${UNSCHED_COMBINED_BACKLOG_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
echo "human task unscheduled fallback sort ok"

echo "== smoke: approval resume path =="
if (( APPROVAL_THRESHOLD_CHARS >= MAX_REWRITE_CHARS )); then
  fail 12 "approval smoke misconfigured: threshold must be below max rewrite chars"
fi
APPROVAL_PAYLOAD="$(mktemp)"
printf '{"text":"%s"}' "$(python3 - "${APPROVAL_THRESHOLD_CHARS}" <<'PY'
import sys

threshold = int(sys.argv[1])
print("a" * (threshold + 10))
PY
)" > "${APPROVAL_PAYLOAD}"
APPROVAL_CODE="$(curl -sS -o /tmp/ea_approval_required_resp.json -w '%{http_code}' -X POST "${BASE}/v1/rewrite/artifact" "${AUTH_ARGS[@]}" -H 'content-type: application/json' --data-binary @"${APPROVAL_PAYLOAD}")"
rm -f "${APPROVAL_PAYLOAD}"
if [[ "${APPROVAL_CODE}" != "202" ]]; then
  echo "expected 202 for approval-required path; got ${APPROVAL_CODE}" >&2
  cat /tmp/ea_approval_required_resp.json >&2 || true
  fail 12 "policy contract mismatch"
fi
APPROVAL_FIELDS="$(python3 - <<'PY'
import json
from pathlib import Path

path = Path("/tmp/ea_approval_required_resp.json")
if not path.exists():
    print("")
    raise SystemExit(0)
try:
    body = json.loads(path.read_text())
except Exception:
    print("")
    raise SystemExit(0)
print("{}|{}|{}|{}".format(body.get("status",""), body.get("next_action",""), body.get("session_id",""), body.get("approval_id","")))
PY
)"
APPROVAL_SESSION_ID="$(python3 - <<'PY'
import json
from pathlib import Path

path = Path("/tmp/ea_approval_required_resp.json")
if not path.exists():
    print("")
    raise SystemExit(0)
try:
    body = json.loads(path.read_text())
except Exception:
    print("")
    raise SystemExit(0)
print(body.get("session_id",""))
PY
)"
APPROVAL_ID="$(python3 - <<'PY'
import json
from pathlib import Path

path = Path("/tmp/ea_approval_required_resp.json")
if not path.exists():
    print("")
    raise SystemExit(0)
try:
    body = json.loads(path.read_text())
except Exception:
    print("")
    raise SystemExit(0)
print(body.get("approval_id",""))
PY
)"
if [[ "${APPROVAL_FIELDS}" != "awaiting_approval|poll_or_subscribe|${APPROVAL_SESSION_ID}|${APPROVAL_ID}" ]]; then
  echo "expected approval-required acceptance contract; got ${APPROVAL_FIELDS}" >&2
  cat /tmp/ea_approval_required_resp.json >&2 || true
  fail 12 "policy contract mismatch"
fi
if [[ -z "${APPROVAL_ID}" || -z "${APPROVAL_SESSION_ID}" ]]; then
  fail 13 "missing approval metadata from acceptance response"
fi
PENDING_APPROVALS_JSON="$(curl -fsS "${BASE}/v1/policy/approvals/pending?limit=5" "${AUTH_ARGS[@]}")"
PENDING_MATCH="$(python3 -c "import json,sys; rows=json.loads(sys.stdin.read() or '[]'); approval_id='${APPROVAL_ID}'; session_id='${APPROVAL_SESSION_ID}'; print(any((row or {}).get('approval_id') == approval_id and (row or {}).get('session_id') == session_id for row in rows))" <<<"${PENDING_APPROVALS_JSON}")"
if [[ "${PENDING_MATCH}" != "True" ]]; then
  echo "expected pending approvals to contain acceptance response ids approval_id=${APPROVAL_ID} session_id=${APPROVAL_SESSION_ID}" >&2
  echo "${PENDING_APPROVALS_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
curl -fsS -X POST "${BASE}/v1/policy/approvals/${APPROVAL_ID}/approve" "${AUTH_ARGS[@]}" -H 'content-type: application/json' \
  -d '{"decided_by":"smoke-operator","reason":"resume execution"}' >/dev/null
APPROVED_SESSION_JSON="$(curl -fsS "${BASE}/v1/rewrite/sessions/${APPROVAL_SESSION_ID}" "${AUTH_ARGS[@]}")"
APPROVED_FIELDS="$(python3 -c "import json,sys; body=json.loads(sys.stdin.read() or '{}'); queues=body.get('queue_items') or []; steps=body.get('steps') or []; events={e.get('name','') for e in (body.get('events') or [])}; print('{}|{}|{}|{}|{}|{}|{}|{}'.format(body.get('status',''), len(body.get('artifacts') or []) >= 1, len(body.get('receipts') or []) >= 1, len(body.get('run_costs') or []) >= 1, len(steps) >= 3 and len(queues) >= 3 and all((q or {}).get('state','') == 'done' for q in queues), 'input_prepared' in events, 'policy_step_completed' in events, 'tool_execution_completed' in events))" <<<"${APPROVED_SESSION_JSON}")"
if [[ "${APPROVED_FIELDS}" != "completed|True|True|True|True|True|True|True" ]]; then
  echo "expected resumed session to complete with artifacts/receipts/run_costs, a three-step queue, input_prepared, policy_step_completed, and tool_execution_completed; got ${APPROVED_FIELDS}" >&2
  echo "${APPROVED_SESSION_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
echo "approval resume path ok"

echo "== smoke: external-send policy path =="
POLICY_EVAL_JSON="$(curl -fsS -X POST "${BASE}/v1/policy/evaluate" "${AUTH_ARGS[@]}" -H 'content-type: application/json' \
  -d '{"content":"Send the board update to the distribution list.","tool_name":"connector.dispatch","action_kind":"delivery.send","channel":"email"}')"
POLICY_EVAL_FIELDS="$(python3 -c 'import json,sys; body=json.loads(sys.stdin.read() or "{}"); print("{}|{}|{}".format(body.get("allow", False), body.get("requires_approval", False), body.get("reason", "")))' <<<"${POLICY_EVAL_JSON}")"
if [[ "${POLICY_EVAL_FIELDS}" != "True|True|allowed" ]]; then
  echo "expected policy evaluate response True|True|allowed; got ${POLICY_EVAL_FIELDS}" >&2
  echo "${POLICY_EVAL_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
echo "external-send policy path ok"

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
  fail 12 "policy contract mismatch"
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
  fail 12 "policy contract mismatch"
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
TOOLS_JSON="$(curl -fsS "${BASE}/v1/tools/registry?limit=10" "${AUTH_ARGS[@]}")"
TOOL_FIELDS="$(python3 -c "import json,sys; rows=json.loads(sys.stdin.read() or '[]'); names={row.get('tool_name','') for row in rows}; print('{}|{}|{}'.format('artifact_repository' in names, 'connector.dispatch' in names, 'email.send' in names))" <<<"${TOOLS_JSON}")"
if [[ "${TOOL_FIELDS}" != "True|True|True" ]]; then
  echo "expected tool registry to expose builtin artifact_repository, builtin connector.dispatch, and upserted email.send; got ${TOOL_FIELDS}" >&2
  echo "${TOOLS_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
CONNECTOR_JSON="$(curl -fsS -X POST "${BASE}/v1/connectors/bindings" "${AUTH_ARGS[@]}" -H 'content-type: application/json' \
  "${PRINCIPAL_ARGS[@]}" \
  -d '{"connector_name":"gmail","external_account_ref":"acct-1","scope_json":{"scopes":["mail.readonly"]},"auth_metadata_json":{"provider":"google"},"status":"enabled"}')"
BINDING_ID="$(python3 -c 'import json,sys; print(json.loads(sys.stdin.read()).get("binding_id",""))' <<<"${CONNECTOR_JSON}")"
if [[ -z "${BINDING_ID}" ]]; then
  fail 13 "missing binding_id from connector response"
fi
TOOL_EXEC_JSON="$(curl -fsS -X POST "${BASE}/v1/tools/execute" "${AUTH_ARGS[@]}" -H 'content-type: application/json' \
  "${PRINCIPAL_ARGS[@]}" \
  -d "{\"tool_name\":\"connector.dispatch\",\"action_kind\":\"delivery.send\",\"payload_json\":{\"binding_id\":\"${BINDING_ID}\",\"channel\":\"email\",\"recipient\":\"ops@example.com\",\"content\":\"tool-runtime smoke dispatch\",\"metadata\":{\"source\":\"tool-execute\"},\"idempotency_key\":\"tool-dispatch-smoke-1\"}}")"
TOOL_EXEC_FIELDS="$(python3 -c "import json,sys; body=json.loads(sys.stdin.read() or '{}'); receipt=body.get('receipt_json') or {}; out=body.get('output_json') or {}; print('{}|{}|{}|{}|{}'.format(body.get('tool_name',''), out.get('status',''), out.get('binding_id',''), receipt.get('handler_key',''), receipt.get('invocation_contract','')))" <<<"${TOOL_EXEC_JSON}")"
if [[ "${TOOL_EXEC_FIELDS}" != "connector.dispatch|queued|${BINDING_ID}|connector.dispatch|tool.v1" ]]; then
  echo "expected connector.dispatch execute route to queue delivery with scoped binding and normalized receipt contract; got ${TOOL_EXEC_FIELDS}" >&2
  echo "${TOOL_EXEC_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
TOOL_EXEC_DELIVERY_ID="$(python3 -c 'import json,sys; print(json.loads(sys.stdin.read() or "{}").get("target_ref",""))' <<<"${TOOL_EXEC_JSON}")"
if [[ -z "${TOOL_EXEC_DELIVERY_ID}" ]]; then
  fail 13 "missing target_ref from tool execute response"
fi
DELIVERY_PENDING_JSON="$(curl -fsS "${BASE}/v1/delivery/outbox/pending?limit=10" "${AUTH_ARGS[@]}")"
DELIVERY_PENDING_MATCH="$(python3 -c "import json,sys; rows=json.loads(sys.stdin.read() or '[]'); target='${TOOL_EXEC_DELIVERY_ID}'; print(any((row or {}).get('delivery_id') == target for row in rows))" <<<"${DELIVERY_PENDING_JSON}")"
if [[ "${DELIVERY_PENDING_MATCH}" != "True" ]]; then
  echo "expected tool-executed connector dispatch to appear in pending outbox; delivery_id=${TOOL_EXEC_DELIVERY_ID}" >&2
  echo "${DELIVERY_PENDING_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
TOOL_EXEC_MISMATCH_CODE="$(curl -sS -o /tmp/ea_tool_exec_mismatch_resp.json -w '%{http_code}' -X POST "${BASE}/v1/tools/execute" "${AUTH_ARGS[@]}" -H 'content-type: application/json' \
  -H "X-EA-Principal-ID: ${MISMATCH_PRINCIPAL_ID}" \
  -d "{\"tool_name\":\"connector.dispatch\",\"action_kind\":\"delivery.send\",\"payload_json\":{\"binding_id\":\"${BINDING_ID}\",\"channel\":\"email\",\"recipient\":\"ops@example.com\",\"content\":\"blocked dispatch\"}}")"
if [[ "${TOOL_EXEC_MISMATCH_CODE}" != "403" ]]; then
  echo "expected 403 for foreign principal tool execution; got ${TOOL_EXEC_MISMATCH_CODE}" >&2
  cat /tmp/ea_tool_exec_mismatch_resp.json >&2 || true
  fail 12 "policy contract mismatch"
fi
TOOL_EXEC_MISMATCH_REASON="$(python3 - <<'PY'
import json
from pathlib import Path

path = Path("/tmp/ea_tool_exec_mismatch_resp.json")
if not path.exists():
    print("")
    raise SystemExit(0)
try:
    body = json.loads(path.read_text())
except Exception:
    print("")
    raise SystemExit(0)
print(((body.get("error") or {}).get("code")) or "")
PY
)"
if [[ "${TOOL_EXEC_MISMATCH_REASON}" != "principal_scope_mismatch" ]]; then
  echo "expected foreign principal tool execution code principal_scope_mismatch; got ${TOOL_EXEC_MISMATCH_REASON}" >&2
  cat /tmp/ea_tool_exec_mismatch_resp.json >&2 || true
  fail 12 "policy contract mismatch"
fi
if [[ -n "${BINDING_ID}" ]]; then
  FOREIGN_BINDING_CODE="$(curl -sS -o /tmp/ea_foreign_binding_resp.json -w '%{http_code}' -X POST "${BASE}/v1/connectors/bindings/${BINDING_ID}/status" "${AUTH_ARGS[@]}" -H 'content-type: application/json' \
    -H "X-EA-Principal-ID: ${MISMATCH_PRINCIPAL_ID}" -d '{"status":"disabled"}')"
  if [[ "${FOREIGN_BINDING_CODE}" != "404" ]]; then
    echo "expected 404 for foreign principal binding status update; got ${FOREIGN_BINDING_CODE}" >&2
    cat /tmp/ea_foreign_binding_resp.json >&2 || true
    fail 12 "policy contract mismatch"
  fi
  curl -fsS -X POST "${BASE}/v1/connectors/bindings/${BINDING_ID}/status" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" -H 'content-type: application/json' -d '{"status":"disabled"}' >/dev/null
fi
curl -fsS "${BASE}/v1/connectors/bindings?limit=5" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" >/dev/null
CONNECTOR_MISMATCH_CODE="$(curl -sS -o /tmp/ea_connector_mismatch_resp.json -w '%{http_code}' "${BASE}/v1/connectors/bindings?principal_id=${MISMATCH_PRINCIPAL_ID}&limit=5" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}")"
if [[ "${CONNECTOR_MISMATCH_CODE}" != "403" ]]; then
  echo "expected 403 for connector principal mismatch; got ${CONNECTOR_MISMATCH_CODE}" >&2
  cat /tmp/ea_connector_mismatch_resp.json >&2 || true
  fail 12 "policy contract mismatch"
fi
CONNECTOR_MISMATCH_REASON="$(python3 - <<'PY'
import json
from pathlib import Path

path = Path("/tmp/ea_connector_mismatch_resp.json")
if not path.exists():
    print("")
    raise SystemExit(0)
try:
    body = json.loads(path.read_text())
except Exception:
    print("")
    raise SystemExit(0)
print(((body.get("error") or {}).get("code")) or "")
PY
)"
if [[ "${CONNECTOR_MISMATCH_REASON}" != "principal_scope_mismatch" ]]; then
  echo "expected connector principal mismatch code principal_scope_mismatch; got ${CONNECTOR_MISMATCH_REASON}" >&2
  cat /tmp/ea_connector_mismatch_resp.json >&2 || true
  fail 12 "policy contract mismatch"
fi
echo "tools/connectors ok"

echo "== smoke: task contracts =="
curl -fsS -X POST "${BASE}/v1/tasks/contracts" "${AUTH_ARGS[@]}" -H 'content-type: application/json' \
  -d '{"task_key":"rewrite_text","deliverable_type":"rewrite_note","default_risk_class":"low","default_approval_class":"none","allowed_tools":["artifact_repository"],"evidence_requirements":[],"memory_write_policy":"reviewed_only","budget_policy_json":{"class":"low"}}' >/dev/null
curl -fsS "${BASE}/v1/tasks/contracts?limit=5" "${AUTH_ARGS[@]}" >/dev/null
curl -fsS "${BASE}/v1/tasks/contracts/rewrite_text" "${AUTH_ARGS[@]}" >/dev/null
echo "task contracts ok"

echo "== smoke: plans =="
PLAN_JSON="$(curl -fsS -X POST "${BASE}/v1/plans/compile" "${AUTH_ARGS[@]}" -H 'content-type: application/json' \
  -d '{"task_key":"rewrite_text","principal_id":"exec-1","goal":"rewrite this text"}')"
PLAN_FIELDS="$(python3 -c "import json,sys; body=json.loads(sys.stdin.read() or '{}'); steps=body.get('plan',{}).get('steps') or []; print('{}|{}|{}|{}|{}'.format(len(steps), (steps[0] or {}).get('step_key','') if steps else '', (steps[1] or {}).get('step_key','') if len(steps) > 1 else '', ','.join((steps[1] or {}).get('depends_on') or []) if len(steps) > 1 else '', (steps[2] or {}).get('tool_name','') if len(steps) > 2 else ''))" <<<"${PLAN_JSON}")"
if [[ "${PLAN_FIELDS}" != "3|step_input_prepare|step_policy_evaluate|step_input_prepare|artifact_repository" ]]; then
  echo "expected three-step plan compile response with an explicit policy step; got ${PLAN_FIELDS}" >&2
  echo "${PLAN_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
curl -fsS -X POST "${BASE}/v1/tasks/contracts" "${AUTH_ARGS[@]}" -H 'content-type: application/json' \
  -d '{"task_key":"rewrite_review","deliverable_type":"rewrite_note","default_risk_class":"low","default_approval_class":"none","allowed_tools":["artifact_repository"],"evidence_requirements":["stakeholder_context"],"memory_write_policy":"reviewed_only","budget_policy_json":{"class":"low","human_review_role":"communications_reviewer","human_review_task_type":"communications_review","human_review_brief":"Review the rewrite before finalizing it.","human_review_priority":"high","human_review_sla_minutes":45,"human_review_auto_assign_if_unique":true,"human_review_desired_output_json":{"format":"review_packet","escalation_policy":"manager_review"},"human_review_authority_required":"send_on_behalf_review","human_review_why_human":"Executive-facing rewrite needs human judgment before finalization.","human_review_quality_rubric_json":{"checks":["tone","accuracy","stakeholder_sensitivity"]}}}' >/dev/null
REVIEW_PLAN_JSON="$(curl -fsS -X POST "${BASE}/v1/plans/compile" "${AUTH_ARGS[@]}" -H 'content-type: application/json' \
  -d '{"task_key":"rewrite_review","principal_id":"exec-1","goal":"review this rewrite"}')"
REVIEW_PLAN_FIELDS="$(python3 -c "import json,sys; body=json.loads(sys.stdin.read() or '{}'); steps=body.get('plan',{}).get('steps') or []; review=(steps[2] if len(steps) > 2 else {}); checks=(review.get('quality_rubric_json') or {}).get('checks') or []; print('{}|{}|{}|{}|{}|{}|{}|{}|{}|{}'.format(len(steps), review.get('step_kind',''), review.get('role_required',''), review.get('priority',''), review.get('sla_minutes',''), review.get('auto_assign_if_unique', False), (review.get('desired_output_json') or {}).get('escalation_policy',''), review.get('authority_required',''), checks[0] if checks else '', ','.join((steps[3] or {}).get('depends_on') or []) if len(steps) > 3 else ''))" <<<"${REVIEW_PLAN_JSON}")"
if [[ "${REVIEW_PLAN_FIELDS}" != "4|human_task|communications_reviewer|high|45|True|manager_review|send_on_behalf_review|tone|step_human_review" ]]; then
  echo "expected compiled human-review branch in plan response; got ${REVIEW_PLAN_FIELDS}" >&2
  echo "${REVIEW_PLAN_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
echo "plans ok"

echo "== smoke: compiled human review runtime =="
curl -fsS -X POST "${BASE}/v1/tasks/contracts" "${AUTH_ARGS[@]}" -H 'content-type: application/json' \
  -d '{"task_key":"rewrite_text","deliverable_type":"rewrite_note","default_risk_class":"low","default_approval_class":"none","allowed_tools":["artifact_repository"],"evidence_requirements":["stakeholder_context"],"memory_write_policy":"reviewed_only","budget_policy_json":{"class":"low","human_review_role":"communications_reviewer","human_review_task_type":"communications_review","human_review_brief":"Review the rewrite before finalizing it.","human_review_priority":"high","human_review_sla_minutes":45,"human_review_auto_assign_if_unique":true,"human_review_desired_output_json":{"format":"review_packet","escalation_policy":"manager_review"},"human_review_authority_required":"send_on_behalf_review","human_review_why_human":"Executive-facing rewrite needs human judgment before finalization.","human_review_quality_rubric_json":{"checks":["tone","accuracy","stakeholder_sensitivity"]}}}' >/dev/null
curl -fsS -X POST "${BASE}/v1/human/tasks/operators" "${AUTH_ARGS[@]}" -H 'content-type: application/json' \
  -d '{"operator_id":"operator-specialist","display_name":"Senior Comms Reviewer","roles":["communications_reviewer"],"skill_tags":["tone","accuracy","stakeholder_sensitivity"],"trust_tier":"senior","status":"active"}' >/dev/null
HUMAN_REWRITE_JSON="$(curl -fsS -X POST "${BASE}/v1/rewrite/artifact" "${AUTH_ARGS[@]}" -H 'content-type: application/json' -d '{"text":"rewrite with human review"}')"
HUMAN_REWRITE_FIELDS="$(python3 -c 'import json,sys; body=json.loads(sys.stdin.read() or "{}"); print("{}|{}|{}|{}".format(body.get("status",""), body.get("next_action",""), bool(body.get("human_task_id","")), body.get("approval_id","")))' <<<"${HUMAN_REWRITE_JSON}")"
if [[ "${HUMAN_REWRITE_FIELDS}" != "awaiting_human|poll_or_subscribe|True|" ]]; then
  echo "expected awaiting_human rewrite acceptance contract with human_task_id; got ${HUMAN_REWRITE_FIELDS}" >&2
  echo "${HUMAN_REWRITE_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
HUMAN_REWRITE_SESSION_ID="$(python3 -c 'import json,sys; body=json.loads(sys.stdin.read() or "{}"); print(body.get("session_id",""))' <<<"${HUMAN_REWRITE_JSON}")"
HUMAN_REWRITE_TASK_ID="$(python3 -c 'import json,sys; body=json.loads(sys.stdin.read() or "{}"); print(body.get("human_task_id",""))' <<<"${HUMAN_REWRITE_JSON}")"
HUMAN_REWRITE_SESSION_JSON="$(curl -fsS "${BASE}/v1/rewrite/sessions/${HUMAN_REWRITE_SESSION_ID}" "${AUTH_ARGS[@]}")"
HUMAN_REWRITE_SESSION_FIELDS="$(python3 -c "import json,sys; body=json.loads(sys.stdin.read() or '{}'); tasks=body.get('human_tasks') or []; queues=body.get('queue_items') or []; steps=body.get('steps') or []; history=body.get('human_task_assignment_history') or []; review=next((row for row in tasks if (row or {}).get('human_task_id') == '${HUMAN_REWRITE_TASK_ID}'), {}); checks=(review.get('quality_rubric_json') or {}).get('checks') or []; names=[(row or {}).get('event_name','') for row in history if (row or {}).get('human_task_id') == '${HUMAN_REWRITE_TASK_ID}']; fields=[body.get('status',''), len(steps) == 4, len(queues) == 3 and all((q or {}).get('state','') == 'done' for q in queues), bool(review.get('human_task_id','')) and review.get('status') == 'pending', any((row or {}).get('step_id') and (row or {}).get('input_json',{}).get('plan_step_key') == 'step_human_review' and (row or {}).get('state') == 'waiting_human' for row in steps), review.get('priority',''), bool(review.get('sla_due_at','')), (review.get('desired_output_json') or {}).get('escalation_policy',''), review.get('authority_required',''), review.get('why_human',''), checks[0] if checks else '', review.get('assignment_state',''), review.get('assigned_operator_id',''), review.get('assignment_source',''), bool(review.get('assigned_at','')), review.get('assigned_by_actor_id',''), ','.join(names)]; print('|'.join(str(v) for v in fields))" <<<"${HUMAN_REWRITE_SESSION_JSON}")"
if [[ "${HUMAN_REWRITE_SESSION_FIELDS}" != "awaiting_human|True|True|True|True|high|True|manager_review|send_on_behalf_review|Executive-facing rewrite needs human judgment before finalization.|tone|assigned|operator-specialist|auto_preselected|True|orchestrator:auto_preselected|human_task_created,human_task_assigned" ]]; then
  echo "expected awaiting_human session with queued human review step; got ${HUMAN_REWRITE_SESSION_FIELDS}" >&2
  echo "${HUMAN_REWRITE_SESSION_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
HUMAN_REWRITE_SUMMARY_FIELDS="$(python3 -c "import json,sys; body=json.loads(sys.stdin.read() or '{}'); review=next((row for row in (body.get('human_tasks') or []) if (row or {}).get('human_task_id') == '${HUMAN_REWRITE_TASK_ID}'), {}); print('{}|{}|{}|{}|{}|{}'.format(review.get('last_transition_event_name',''), bool(review.get('last_transition_at','')), review.get('last_transition_assignment_state',''), review.get('last_transition_operator_id',''), review.get('last_transition_assignment_source',''), review.get('last_transition_by_actor_id','')))" <<<"${HUMAN_REWRITE_SESSION_JSON}")"
if [[ "${HUMAN_REWRITE_SUMMARY_FIELDS}" != "human_task_assigned|True|assigned|operator-specialist|auto_preselected|orchestrator:auto_preselected" ]]; then
  echo "expected planner-native human review row to expose compact auto-preselected transition summary; got ${HUMAN_REWRITE_SUMMARY_FIELDS}" >&2
  echo "${HUMAN_REWRITE_SESSION_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
HUMAN_REWRITE_AUTO_SESSION_JSON="$(curl -fsS "${BASE}/v1/rewrite/sessions/${HUMAN_REWRITE_SESSION_ID}?human_task_assignment_source=auto_preselected" "${AUTH_ARGS[@]}")"
HUMAN_REWRITE_AUTO_SESSION_FIELDS="$(python3 -c "import json,sys; body=json.loads(sys.stdin.read() or '{}'); tasks=body.get('human_tasks') or []; history=body.get('human_task_assignment_history') or []; print('{}|{}|{}'.format(len(tasks), (tasks[0].get('human_task_id','') if tasks else ''), ','.join((row or {}).get('event_name','') for row in history)))" <<<"${HUMAN_REWRITE_AUTO_SESSION_JSON}")"
if [[ "${HUMAN_REWRITE_AUTO_SESSION_FIELDS}" != "1|${HUMAN_REWRITE_TASK_ID}|human_task_assigned" ]]; then
  echo "expected session assignment-source filter to isolate planner auto-preselected pending rows and transitions; got ${HUMAN_REWRITE_AUTO_SESSION_FIELDS}" >&2
  echo "${HUMAN_REWRITE_AUTO_SESSION_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
HUMAN_REWRITE_AUTO_LIST_JSON="$(curl -fsS "${BASE}/v1/human/tasks?session_id=${HUMAN_REWRITE_SESSION_ID}&assignment_source=auto_preselected&limit=10" "${AUTH_ARGS[@]}")"
HUMAN_REWRITE_AUTO_LIST_FIELDS="$(python3 -c "import json,sys; rows=json.loads(sys.stdin.read() or '[]'); wanted='${HUMAN_REWRITE_TASK_ID}'; print(any((row or {}).get('human_task_id') == wanted for row in rows))" <<<"${HUMAN_REWRITE_AUTO_LIST_JSON}")"
if [[ "${HUMAN_REWRITE_AUTO_LIST_FIELDS}" != "True" ]]; then
  echo "expected session-scoped assignment-source list filter to expose planner auto-preselected pending work" >&2
  echo "${HUMAN_REWRITE_AUTO_LIST_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
HUMAN_REWRITE_AUTO_SUMMARY_JSON="$(curl -fsS "${BASE}/v1/human/tasks/priority-summary?status=pending&role_required=communications_reviewer&assigned_operator_id=operator-specialist&assignment_source=auto_preselected" "${AUTH_ARGS[@]}")"
HUMAN_REWRITE_AUTO_SUMMARY_FIELDS="$(python3 -c "import json,sys; body=json.loads(sys.stdin.read() or '{}'); counts=body.get('counts_json') or {}; print('{}|{}|{}|{}|{}|{}|{}'.format(body.get('assignment_source',''), body.get('total',''), body.get('highest_priority',''), counts.get('urgent',''), counts.get('high',''), counts.get('normal',''), counts.get('low','')))" <<<"${HUMAN_REWRITE_AUTO_SUMMARY_JSON}")"
if [[ "${HUMAN_REWRITE_AUTO_SUMMARY_FIELDS}" != "auto_preselected|1|high|0|1|0|0" ]]; then
  echo "expected assignment-source priority summary to isolate planner auto-preselected pending work; got ${HUMAN_REWRITE_AUTO_SUMMARY_FIELDS}" >&2
  echo "${HUMAN_REWRITE_AUTO_SUMMARY_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
HUMAN_REWRITE_AUTO_BACKLOG_JSON="$(curl -fsS "${BASE}/v1/human/tasks/backlog?operator_id=operator-specialist&assignment_source=auto_preselected&limit=10" "${AUTH_ARGS[@]}")"
HUMAN_REWRITE_AUTO_BACKLOG_FIELDS="$(python3 -c "import json,sys; rows=json.loads(sys.stdin.read() or '[]'); wanted='${HUMAN_REWRITE_TASK_ID}'; print(any((row or {}).get('human_task_id') == wanted for row in rows))" <<<"${HUMAN_REWRITE_AUTO_BACKLOG_JSON}")"
if [[ "${HUMAN_REWRITE_AUTO_BACKLOG_FIELDS}" != "True" ]]; then
  echo "expected assignment-source backlog filter to expose planner auto-preselected pending work" >&2
  echo "${HUMAN_REWRITE_AUTO_BACKLOG_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
HUMAN_REWRITE_RETURN_JSON="$(curl -fsS -X POST "${BASE}/v1/human/tasks/${HUMAN_REWRITE_TASK_ID}/return" "${AUTH_ARGS[@]}" -H 'content-type: application/json' \
  -d '{"operator_id":"reviewer-1","resolution":"ready_for_send","returned_payload_json":{"final_text":"rewrite with human review, edited by reviewer"},"provenance_json":{"review_mode":"human"}}')"
HUMAN_REWRITE_RETURN_FIELDS="$(python3 -c 'import json,sys; body=json.loads(sys.stdin.read() or "{}"); print("{}|{}|{}|{}|{}|{}".format(body.get("last_transition_event_name",""), bool(body.get("last_transition_at","")), body.get("last_transition_assignment_state",""), body.get("last_transition_operator_id",""), body.get("last_transition_assignment_source",""), body.get("last_transition_by_actor_id","")))' <<<"${HUMAN_REWRITE_RETURN_JSON}")"
if [[ "${HUMAN_REWRITE_RETURN_FIELDS}" != "human_task_returned|True|returned|reviewer-1|manual|reviewer-1" ]]; then
  echo "expected human-review return response to expose compact returned transition summary; got ${HUMAN_REWRITE_RETURN_FIELDS}" >&2
  echo "${HUMAN_REWRITE_RETURN_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
HUMAN_REWRITE_DONE_JSON="$(curl -fsS "${BASE}/v1/rewrite/sessions/${HUMAN_REWRITE_SESSION_ID}" "${AUTH_ARGS[@]}")"
HUMAN_REWRITE_DONE_FIELDS="$(python3 -c "import json,sys; body=json.loads(sys.stdin.read() or '{}'); events={e.get('name','') for e in (body.get('events') or [])}; queues=body.get('queue_items') or []; steps=body.get('steps') or []; artifacts=body.get('artifacts') or []; print('{}|{}|{}|{}|{}|{}|{}'.format(body.get('status',''), len(artifacts) >= 1, (artifacts[0] or {}).get('content','') if artifacts else '', 'human_task_step_started' in events, 'session_resumed_from_human_task' in events, len(queues) == 4 and all((q or {}).get('state','') == 'done' for q in queues), len(steps) == 4 and all((row or {}).get('state') == 'completed' for row in steps)))" <<<"${HUMAN_REWRITE_DONE_JSON}")"
if [[ "${HUMAN_REWRITE_DONE_FIELDS}" != "completed|True|rewrite with human review, edited by reviewer|True|True|True|True" ]]; then
  echo "expected resumed human-review rewrite to complete with reviewer-edited artifact and fully drained queue; got ${HUMAN_REWRITE_DONE_FIELDS}" >&2
  echo "${HUMAN_REWRITE_DONE_JSON}" >&2
  fail 12 "policy contract mismatch"
fi
echo "compiled human review runtime ok"

echo "== smoke: memory =="
MEMORY_CANDIDATE_JSON="$(curl -fsS -X POST "${BASE}/v1/memory/candidates" "${AUTH_ARGS[@]}" -H 'content-type: application/json' \
  "${PRINCIPAL_ARGS[@]}" \
  -d '{"category":"stakeholder_pref","summary":"CEO prefers concise updates","fact_json":{"tone":"concise"},"source_session_id":"session-1","source_event_id":"event-1","source_step_id":"step-1","confidence":0.72,"sensitivity":"internal"}')"
MEMORY_CANDIDATE_ID="$(python3 -c 'import json,sys; print(json.loads(sys.stdin.read()).get("candidate_id",""))' <<<"${MEMORY_CANDIDATE_JSON}")"
if [[ -z "${MEMORY_CANDIDATE_ID}" ]]; then
  fail 13 "missing candidate_id from memory candidate response"
fi
MEMORY_PROMOTE_JSON="$(curl -fsS -X POST "${BASE}/v1/memory/candidates/${MEMORY_CANDIDATE_ID}/promote" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" -H 'content-type: application/json' \
  -d '{"reviewer":"smoke-operator","sharing_policy":"private"}')"
MEMORY_ITEM_ID="$(python3 -c 'import json,sys; body=json.loads(sys.stdin.read() or "{}"); print(((body.get("item") or {}).get("item_id")) or "")' <<<"${MEMORY_PROMOTE_JSON}")"
if [[ -z "${MEMORY_ITEM_ID}" ]]; then
  fail 13 "missing item_id from memory promote response"
fi
curl -fsS "${BASE}/v1/memory/candidates?limit=5&status=promoted" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" >/dev/null
curl -fsS "${BASE}/v1/memory/items?limit=5" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" >/dev/null
MEMORY_MISMATCH_CODE="$(curl -sS -o /tmp/ea_memory_mismatch_resp.json -w '%{http_code}' "${BASE}/v1/memory/items?limit=5&principal_id=${MISMATCH_PRINCIPAL_ID}" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}")"
if [[ "${MEMORY_MISMATCH_CODE}" != "403" ]]; then
  echo "expected 403 for memory principal mismatch; got ${MEMORY_MISMATCH_CODE}" >&2
  cat /tmp/ea_memory_mismatch_resp.json >&2 || true
  fail 12 "policy contract mismatch"
fi
MEMORY_MISMATCH_REASON="$(python3 - <<'PY'
import json
from pathlib import Path

path = Path("/tmp/ea_memory_mismatch_resp.json")
if not path.exists():
    print("")
    raise SystemExit(0)
try:
    body = json.loads(path.read_text())
except Exception:
    print("")
    raise SystemExit(0)
print(((body.get("error") or {}).get("code")) or "")
PY
)"
if [[ "${MEMORY_MISMATCH_REASON}" != "principal_scope_mismatch" ]]; then
  echo "expected memory principal mismatch code principal_scope_mismatch; got ${MEMORY_MISMATCH_REASON}" >&2
  cat /tmp/ea_memory_mismatch_resp.json >&2 || true
  fail 12 "policy contract mismatch"
fi
curl -fsS "${BASE}/v1/memory/items/${MEMORY_ITEM_ID}" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" >/dev/null
ENTITY_EXEC_JSON="$(curl -fsS -X POST "${BASE}/v1/memory/entities" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" -H 'content-type: application/json' \
  -d '{"principal_id":"exec-1","entity_type":"person","canonical_name":"Alex Executive","attributes_json":{"role":"executive"},"confidence":0.9,"status":"active"}')"
ENTITY_EXEC_ID="$(python3 -c 'import json,sys; print(json.loads(sys.stdin.read()).get("entity_id",""))' <<<"${ENTITY_EXEC_JSON}")"
if [[ -z "${ENTITY_EXEC_ID}" ]]; then
  fail 13 "missing entity_id from memory entity response"
fi
ENTITY_STAKE_JSON="$(curl -fsS -X POST "${BASE}/v1/memory/entities" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" -H 'content-type: application/json' \
  -d '{"principal_id":"exec-1","entity_type":"person","canonical_name":"Sam Stakeholder","attributes_json":{"role":"board_member"},"confidence":0.88,"status":"active"}')"
ENTITY_STAKE_ID="$(python3 -c 'import json,sys; print(json.loads(sys.stdin.read()).get("entity_id",""))' <<<"${ENTITY_STAKE_JSON}")"
if [[ -z "${ENTITY_STAKE_ID}" ]]; then
  fail 13 "missing entity_id from second memory entity response"
fi
REL_JSON="$(curl -fsS -X POST "${BASE}/v1/memory/relationships" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" -H 'content-type: application/json' \
  -d "{\"principal_id\":\"exec-1\",\"from_entity_id\":\"${ENTITY_EXEC_ID}\",\"to_entity_id\":\"${ENTITY_STAKE_ID}\",\"relationship_type\":\"reports_to\",\"attributes_json\":{\"strength\":\"high\"},\"confidence\":0.75}")"
REL_ID="$(python3 -c 'import json,sys; print(json.loads(sys.stdin.read()).get("relationship_id",""))' <<<"${REL_JSON}")"
if [[ -z "${REL_ID}" ]]; then
  fail 13 "missing relationship_id from memory relationship response"
fi
COMMITMENT_JSON="$(curl -fsS -X POST "${BASE}/v1/memory/commitments" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" -H 'content-type: application/json' \
  -d '{"principal_id":"exec-1","title":"Send board follow-up","details":"Draft and send by Friday","status":"open","priority":"high","due_at":"2026-03-06T10:00:00+00:00","source_json":{"source":"smoke"}}')"
COMMITMENT_ID="$(python3 -c 'import json,sys; print(json.loads(sys.stdin.read()).get("commitment_id",""))' <<<"${COMMITMENT_JSON}")"
if [[ -z "${COMMITMENT_ID}" ]]; then
  fail 13 "missing commitment_id from memory commitment response"
fi
BINDING_JSON="$(curl -fsS -X POST "${BASE}/v1/memory/authority-bindings" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" -H 'content-type: application/json' \
  -d '{"principal_id":"exec-1","subject_ref":"assistant","action_scope":"calendar.write","approval_level":"manager","channel_scope":["email","slack"],"policy_json":{"quiet_hours_enforced":true},"status":"active"}')"
BINDING_ID="$(python3 -c 'import json,sys; print(json.loads(sys.stdin.read()).get("binding_id",""))' <<<"${BINDING_JSON}")"
if [[ -z "${BINDING_ID}" ]]; then
  fail 13 "missing binding_id from authority binding response"
fi
PREF_JSON="$(curl -fsS -X POST "${BASE}/v1/memory/delivery-preferences" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" -H 'content-type: application/json' \
  -d '{"principal_id":"exec-1","channel":"email","recipient_ref":"ceo@example.com","cadence":"urgent_only","quiet_hours_json":{"start":"22:00","end":"07:00"},"format_json":{"style":"concise"},"status":"active"}')"
PREF_ID="$(python3 -c 'import json,sys; print(json.loads(sys.stdin.read()).get("preference_id",""))' <<<"${PREF_JSON}")"
if [[ -z "${PREF_ID}" ]]; then
  fail 13 "missing preference_id from delivery preference response"
fi
curl -fsS "${BASE}/v1/memory/entities?limit=5&principal_id=exec-1" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" >/dev/null
curl -fsS "${BASE}/v1/memory/entities/${ENTITY_EXEC_ID}" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" >/dev/null
curl -fsS "${BASE}/v1/memory/relationships?limit=5&principal_id=exec-1" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" >/dev/null
curl -fsS "${BASE}/v1/memory/relationships/${REL_ID}" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" >/dev/null
curl -fsS "${BASE}/v1/memory/commitments?principal_id=exec-1&limit=5" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" >/dev/null
curl -fsS "${BASE}/v1/memory/commitments/${COMMITMENT_ID}?principal_id=exec-1" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" >/dev/null
curl -fsS "${BASE}/v1/memory/authority-bindings?principal_id=exec-1&limit=5" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" >/dev/null
curl -fsS "${BASE}/v1/memory/authority-bindings/${BINDING_ID}?principal_id=exec-1" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" >/dev/null
curl -fsS "${BASE}/v1/memory/delivery-preferences?principal_id=exec-1&limit=5" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" >/dev/null
curl -fsS "${BASE}/v1/memory/delivery-preferences/${PREF_ID}?principal_id=exec-1" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" >/dev/null
DEADLINE_JSON="$(curl -fsS -X POST "${BASE}/v1/memory/deadline-windows" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" -H 'content-type: application/json' \
  -d '{"principal_id":"exec-1","title":"Board prep delivery window","start_at":"2026-03-07T08:30:00+00:00","end_at":"2026-03-07T10:00:00+00:00","status":"open","priority":"high","notes":"Draft must be ready before board sync","source_json":{"source":"smoke"}}')"
WINDOW_ID="$(python3 -c 'import json,sys; print(json.loads(sys.stdin.read()).get("window_id",""))' <<<"${DEADLINE_JSON}")"
if [[ -z "${WINDOW_ID}" ]]; then
  fail 13 "missing window_id from deadline-window response"
fi
curl -fsS "${BASE}/v1/memory/deadline-windows?principal_id=exec-1&limit=5" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" >/dev/null
curl -fsS "${BASE}/v1/memory/deadline-windows/${WINDOW_ID}?principal_id=exec-1" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" >/dev/null
STAKEHOLDER_JSON="$(curl -fsS -X POST "${BASE}/v1/memory/stakeholders" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" -H 'content-type: application/json' \
  -d '{"principal_id":"exec-1","display_name":"Sam Stakeholder","channel_ref":"email:sam@example.com","authority_level":"approver","importance":"high","response_cadence":"fast","tone_pref":"diplomatic","sensitivity":"confidential","escalation_policy":"notify_exec","open_loops_json":{"board_follow_up":"open"},"friction_points_json":{"scheduling":"tight"},"last_interaction_at":"2026-03-06T15:30:00+00:00","status":"active","notes":"Needs concise summaries"}')"
STAKEHOLDER_ID="$(python3 -c 'import json,sys; print(json.loads(sys.stdin.read()).get("stakeholder_id",""))' <<<"${STAKEHOLDER_JSON}")"
if [[ -z "${STAKEHOLDER_ID}" ]]; then
  fail 13 "missing stakeholder_id from stakeholder response"
fi
curl -fsS "${BASE}/v1/memory/stakeholders?principal_id=exec-1&limit=5" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" >/dev/null
curl -fsS "${BASE}/v1/memory/stakeholders/${STAKEHOLDER_ID}?principal_id=exec-1" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" >/dev/null
DECISION_JSON="$(curl -fsS -X POST "${BASE}/v1/memory/decision-windows" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" -H 'content-type: application/json' \
  -d '{"principal_id":"exec-1","title":"Board response decision","context":"Choose timing and channel for reply","opens_at":"2026-03-06T08:00:00+00:00","closes_at":"2026-03-06T12:00:00+00:00","urgency":"high","authority_required":"exec","status":"open","notes":"Needs decision before board prep","source_json":{"source":"smoke"}}')"
DECISION_WINDOW_ID="$(python3 -c 'import json,sys; print(json.loads(sys.stdin.read()).get("decision_window_id",""))' <<<"${DECISION_JSON}")"
if [[ -z "${DECISION_WINDOW_ID}" ]]; then
  fail 13 "missing decision_window_id from decision-window response"
fi
curl -fsS "${BASE}/v1/memory/decision-windows?principal_id=exec-1&limit=5" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" >/dev/null
curl -fsS "${BASE}/v1/memory/decision-windows/${DECISION_WINDOW_ID}?principal_id=exec-1" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" >/dev/null
COMM_POLICY_JSON="$(curl -fsS -X POST "${BASE}/v1/memory/communication-policies" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" -H 'content-type: application/json' \
  -d '{"principal_id":"exec-1","scope":"board_threads","preferred_channel":"email","tone":"concise_diplomatic","max_length":1200,"quiet_hours_json":{"start":"22:00","end":"07:00"},"escalation_json":{"on_high_urgency":"notify_exec"},"status":"active","notes":"Board-facing communication defaults"}')"
COMM_POLICY_ID="$(python3 -c 'import json,sys; print(json.loads(sys.stdin.read()).get("policy_id",""))' <<<"${COMM_POLICY_JSON}")"
if [[ -z "${COMM_POLICY_ID}" ]]; then
  fail 13 "missing policy_id from communication-policy response"
fi
curl -fsS "${BASE}/v1/memory/communication-policies?principal_id=exec-1&limit=5" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" >/dev/null
curl -fsS "${BASE}/v1/memory/communication-policies/${COMM_POLICY_ID}?principal_id=exec-1" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" >/dev/null
FOLLOW_RULE_JSON="$(curl -fsS -X POST "${BASE}/v1/memory/follow-up-rules" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" -H 'content-type: application/json' \
  -d '{"principal_id":"exec-1","name":"Board reminder escalation","trigger_kind":"deadline_risk","channel_scope":["email","slack"],"delay_minutes":120,"max_attempts":3,"escalation_policy":"notify_exec","conditions_json":{"priority":"high"},"action_json":{"action":"draft_follow_up"},"status":"active","notes":"Escalate if follow-up is late"}')"
FOLLOW_RULE_ID="$(python3 -c 'import json,sys; print(json.loads(sys.stdin.read()).get("rule_id",""))' <<<"${FOLLOW_RULE_JSON}")"
if [[ -z "${FOLLOW_RULE_ID}" ]]; then
  fail 13 "missing rule_id from follow-up-rule response"
fi
curl -fsS "${BASE}/v1/memory/follow-up-rules?principal_id=exec-1&limit=5" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" >/dev/null
curl -fsS "${BASE}/v1/memory/follow-up-rules/${FOLLOW_RULE_ID}?principal_id=exec-1" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" >/dev/null
INTERRUPTION_BUDGET_JSON="$(curl -fsS -X POST "${BASE}/v1/memory/interruption-budgets" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" -H 'content-type: application/json' \
  -d '{"principal_id":"exec-1","scope":"workday","window_kind":"daily","budget_minutes":120,"used_minutes":30,"reset_at":"2026-03-07T00:00:00+00:00","quiet_hours_json":{"start":"22:00","end":"07:00"},"status":"active","notes":"Keep non-critical interruptions bounded"}')"
INTERRUPTION_BUDGET_ID="$(python3 -c 'import json,sys; print(json.loads(sys.stdin.read()).get("budget_id",""))' <<<"${INTERRUPTION_BUDGET_JSON}")"
if [[ -z "${INTERRUPTION_BUDGET_ID}" ]]; then
  fail 13 "missing budget_id from interruption-budget response"
fi
curl -fsS "${BASE}/v1/memory/interruption-budgets?principal_id=exec-1&limit=5" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" >/dev/null
curl -fsS "${BASE}/v1/memory/interruption-budgets/${INTERRUPTION_BUDGET_ID}?principal_id=exec-1" "${AUTH_ARGS[@]}" "${PRINCIPAL_ARGS[@]}" >/dev/null
echo "memory ok"

echo "smoke complete"
