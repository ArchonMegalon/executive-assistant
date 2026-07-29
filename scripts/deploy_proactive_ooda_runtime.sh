#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-}"
if [[ -z "${PYTHON_BIN}" ]]; then
  if [[ -x "${APP_ROOT}/.venv/bin/python" ]]; then
    PYTHON_BIN="${APP_ROOT}/.venv/bin/python"
  else
    PYTHON_BIN="python3"
  fi
fi

usage() {
  cat <<'EOF'
Usage:
  bash scripts/deploy_proactive_ooda_runtime.sh

Recreate only the bind-mounted proactive OODA runtime services without building
the heavyweight EA/browser images. This is for OODA policy, signal, Teable, and
receipt changes that are already committed and visible through the repo mount.

Environment:
  COMPOSE_PROJECT_NAME=ea                 Compose project name (default: ea).
  EA_OODA_DEPLOY_ALLOW_DIRTY_WORKTREE=1   Allow dirty worktree rollout (default: 0).
  EA_OODA_DEPLOY_RESYNC_TEABLE=0          Skip latest-run Teable resync (default: 1).
  EA_OODA_DEPLOY_CLEANUP_APPROVAL_CALLBACKS=0
                                            Skip stale callback cleanup (default: 1).
  EA_OODA_DEPLOY_DOCKER_EXEC_TIMEOUT_SECONDS=180
                                            Bound each container-side verifier.
  EA_OODA_DEPLOY_CALLBACK_CLEANUP_TIMEOUT_SECONDS=600
                                            Bound governed callback cleanup.
  EA_OODA_DEPLOY_GOLD_TIMEOUT_SECONDS=600 Bound the heavier gold evidence scan.
EOF
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi

cd "${APP_ROOT}"

if [[ ! -f "${APP_ROOT}/.env" ]]; then
  echo "Refusing OODA runtime deploy without .env." >&2
  exit 1
fi

if [[ "${EA_OODA_DEPLOY_ALLOW_DIRTY_WORKTREE:-0}" != "1" ]] && [[ -n "$(git -C "${APP_ROOT}" status --short)" ]]; then
  cat >&2 <<'EOF'
Refusing OODA runtime deploy from a dirty git worktree.

Commit or stash local changes first, or explicitly opt in with:
  EA_OODA_DEPLOY_ALLOW_DIRTY_WORKTREE=1 bash scripts/deploy_proactive_ooda_runtime.sh
EOF
  exit 5
fi

export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-ea}"

if docker compose version >/dev/null 2>&1; then
  DC=(docker compose)
else
  DC=(docker-compose)
fi

COMPOSE_ARGS=(-f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.whatsapp-web-session.yml)

compose() {
  COMPOSE_IGNORE_ORPHANS=1 "${DC[@]}" "${COMPOSE_ARGS[@]}" "$@"
}

repair_ooda_runtime_output_permissions() {
  local output_dirs=(
    "${APP_ROOT}/.codex-studio/published"
    "${APP_ROOT}/.runtime"
  )
  local host_uid
  host_uid="$(id -u)"
  mkdir -p "${output_dirs[@]}"

  # The runtime user is added to host group 1000 by Compose. Keep generated
  # outputs writable by that shared group and make directories setgid so files
  # created by UID 10001 inherit the host-writable group. Do not make runtime
  # receipts or dedupe state world-writable. Restrict the host-side repair to
  # host-owned paths; container-owned paths are repaired by the runtime user.
  find "${output_dirs[@]}" -type d -user "${host_uid}" -exec chmod g+rwX,g+s {} +
  find "${output_dirs[@]}" -type f -user "${host_uid}" -exec chmod g+rw {} +
}

run_bounded() {
  local label="$1"
  shift

  local timeout_seconds="${EA_OODA_DEPLOY_DOCKER_EXEC_TIMEOUT_SECONDS:-180}"
  local status=0
  if command -v timeout >/dev/null 2>&1; then
    timeout --kill-after=10s "${timeout_seconds}s" "$@" || status=$?
  else
    "$@" || status=$?
  fi
  if [[ "${status}" -ne 0 ]]; then
    echo "OODA runtime deploy command failed (${label}) with status ${status}." >&2
    return "${status}"
  fi
}

run_ooda_exec() {
  local label="$1"
  shift
  run_bounded "${label}" docker exec ea-proactive-ooda "$@"
}

repair_ooda_runtime_container_output_permissions() {
  run_ooda_exec repair-output-permissions sh -ec '
    runtime_uid="$(id -u)"
    for output_dir in /app/.codex-studio/published /app/.runtime; do
      [ -d "${output_dir}" ] || continue
      find "${output_dir}" -type d -user "${runtime_uid}" -exec chmod g+rwX,g+s {} +
      find "${output_dir}" -type f -user "${runtime_uid}" -exec chmod g+rw {} +
    done
  '
}

env_file_value() {
  local key="$1"
  local line=""
  line="$(grep -E "^${key}=" "${APP_ROOT}/.env" | tail -n1 || true)"
  printf '%s' "${line#*=}"
}

normalize_value() {
  local value="$1"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  if [[ "${#value}" -ge 2 && "${value:0:1}" == "${value: -1}" && ( "${value:0:1}" == "'" || "${value:0:1}" == '"' ) ]]; then
    value="${value:1:${#value}-2}"
  fi
  printf '%s' "${value}"
}

service_container_ready() {
  local service="$1"
  local cid
  local running
  local restarting
  local health

  cid="$(compose ps -q "${service}" || true)"
  [[ -n "${cid}" ]] || return 1
  running="$(docker inspect -f '{{.State.Running}}' "${cid}" 2>/dev/null || true)"
  restarting="$(docker inspect -f '{{.State.Restarting}}' "${cid}" 2>/dev/null || true)"
  health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "${cid}" 2>/dev/null || true)"

  [[ "${running}" == "true" ]] || return 1
  [[ "${restarting}" != "true" ]] || return 1
  [[ -z "${health}" || "${health}" == "healthy" ]] || return 1
}

wait_ready() {
  local service="$1"
  local tries="${2:-60}"
  for _ in $(seq 1 "${tries}"); do
    if service_container_ready "${service}"; then
      return 0
    fi
    sleep 1
  done
  echo "Service failed to become ready during OODA runtime deploy: ${service}" >&2
  return 1
}

teable_api_key="$(normalize_value "${TEABLE_API_KEY:-$(env_file_value TEABLE_API_KEY)}")"
teable_base_id="$(normalize_value "${EA_ENV_TEABLE_BASE_ID:-$(env_file_value EA_ENV_TEABLE_BASE_ID)}")"
if [[ -n "${teable_api_key}" && -n "${teable_base_id}" ]]; then
  echo "Reconciling proactive OODA Teable projection tables."
  "${PYTHON_BIN}" "${APP_ROOT}/scripts/bootstrap_proactive_ooda_teable_tables.py" --create-missing --write-config >/dev/null
fi

repair_ooda_runtime_output_permissions

compose up -d --no-build ea-db ea-teable-relay
wait_ready ea-db 60
wait_ready ea-teable-relay 60

compose up -d --no-build --no-deps --force-recreate ea-proactive-ooda ea-telegram-teable-sync
wait_ready ea-proactive-ooda 180
wait_ready ea-telegram-teable-sync 60
repair_ooda_runtime_container_output_permissions

run_ooda_exec property-scout-disabled python -c "from app.runner import _scheduler_property_scout_enabled; raise SystemExit(1 if _scheduler_property_scout_enabled() else 0)"
run_ooda_exec teable-table-sync-config python -c "import json, os; expected={'proactive_ooda_runs','proactive_ooda_items','proactive_ooda_safe_work'}; enabled=os.environ.get('EA_PROACTIVE_OODA_TEABLE_SYNC_ENABLED','0') == '1'; data=json.loads(os.environ.get('TEABLE_TABLE_SYNC_CONFIG_JSON','{}') or '{}'); missing=sorted(expected-set(data)); raise SystemExit(1 if enabled and missing else 0)"

if [[ "${EA_OODA_DEPLOY_CLEANUP_APPROVAL_CALLBACKS:-1}" == "1" ]]; then
  callback_cleanup_timeout="${EA_OODA_DEPLOY_CALLBACK_CLEANUP_TIMEOUT_SECONDS:-600}"
  EA_OODA_DEPLOY_DOCKER_EXEC_TIMEOUT_SECONDS="${callback_cleanup_timeout}" \
    run_bounded cleanup-approval-callbacks \
      "${PYTHON_BIN}" "${APP_ROOT}/scripts/ea_live_ops.py" \
      cleanup-proactive-approval-callbacks \
      --execute \
      --format operator \
      --timeout-seconds "${callback_cleanup_timeout}"
fi

if [[ "${EA_OODA_DEPLOY_RESYNC_TEABLE:-1}" == "1" ]]; then
  run_ooda_exec teable-resync sh -ec 'if [ "${EA_PROACTIVE_OODA_TEABLE_SYNC_ENABLED:-0}" = "1" ]; then python /app/scripts/resync_proactive_ooda_teable_projection.py --principal-id "$EA_PROACTIVE_OODA_PRINCIPAL_ID" --state-path /data/provider-ledger/proactive_ooda_notified.json --receipt-path /data/provider-ledger/proactive_ooda_latest_run.generated.json --stage-packet-dir /data/provider-ledger/proactive_ooda_stage_packets --safe-work-result-dir /data/provider-ledger/proactive_ooda_safe_work_results --write-receipt --require-enabled; fi'
fi

run_ooda_exec materialize-operator-status python /app/scripts/materialize_proactive_ooda_operator_status.py --output /tmp/ea_proactive_ooda_operator_status.deploy.json >/dev/null
run_ooda_exec operator-status-summary python -c "import json,pathlib; d=json.loads(pathlib.Path('/tmp/ea_proactive_ooda_operator_status.deploy.json').read_text()); print(json.dumps({'gate':'operator-runtime-posture','status':d.get('status'),'reason':d.get('reason'),'next_action':d.get('next_action'),'source_git_head':d.get('source_git_head')}, sort_keys=True))"
run_ooda_exec verify-operator-status python /app/scripts/verify_proactive_ooda_operator_status.py --receipt /tmp/ea_proactive_ooda_operator_status.deploy.json --pretty
EA_OODA_DEPLOY_DOCKER_EXEC_TIMEOUT_SECONDS="${EA_OODA_DEPLOY_GOLD_TIMEOUT_SECONDS:-600}" \
  run_ooda_exec materialize-gold-acceptance \
    python /app/scripts/materialize_proactive_ooda_gold_acceptance.py \
    --output /tmp/ea_proactive_ooda_gold_acceptance.deploy.json \
    --run-receipt /data/provider-ledger/proactive_ooda_latest_run.generated.json \
    --stage-packet-dir /data/provider-ledger/proactive_ooda_stage_packets \
    --safe-work-result-dir /data/provider-ledger/proactive_ooda_safe_work_results \
    >/dev/null
run_ooda_exec gold-status-summary python -c "import json,pathlib; d=json.loads(pathlib.Path('/tmp/ea_proactive_ooda_gold_acceptance.deploy.json').read_text()); print(json.dumps({'gate':'proactive-gold-acceptance','status':d.get('status'),'reason':d.get('reason'),'next_action':d.get('next_action'),'source_git_head':d.get('source_git_head')}, sort_keys=True))"
run_ooda_exec verify-gold-acceptance python /app/scripts/verify_proactive_ooda_gold_acceptance.py --receipt /tmp/ea_proactive_ooda_gold_acceptance.deploy.json --pretty

run_ooda_exec latest-run-summary python -c "import json,pathlib; p=pathlib.Path('/data/provider-ledger/proactive_ooda_latest_run.generated.json'); d=json.loads(p.read_text()) if p.exists() else {}; r=d.get('receipt') if isinstance(d.get('receipt'),dict) else d; ts=d.get('teable_sync') or r.get('teable_sync') or {}; print(json.dumps({'status':'ok','notification_status':r.get('notification_status'),'error_code':r.get('error_code'),'telegram_message_count':len(r.get('telegram_message_ids') or []),'teable_status':ts.get('status'),'teable_missing_tables':ts.get('missing_tables')}, sort_keys=True))"
