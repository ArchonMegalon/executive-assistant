#!/usr/bin/env bash
set -euo pipefail

EA_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${EA_ROOT}"
PYTHON_BIN="${PYTHON_BIN:-}"
if [[ -z "${PYTHON_BIN}" ]]; then
  if [[ -x "${EA_ROOT}/.venv/bin/python" ]]; then
    PYTHON_BIN="${EA_ROOT}/.venv/bin/python"
  else
    PYTHON_BIN="python3"
  fi
fi

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  cat <<'EOF'
Usage:
  bash scripts/support_bundle.sh

Environment:
  SUPPORT_BUNDLE_PREFIX=<name>          Bundle filename prefix (default: support_bundle)
  SUPPORT_BUNDLE_TIMESTAMP_FMT=<fmt>    UTC timestamp format for filename (date format)
  SUPPORT_LOG_TAIL_LINES=<n>            Number of log lines to capture (default: 300)
  SUPPORT_INCLUDE_API=0|1               Include ea-api logs (default: 1)
  SUPPORT_INCLUDE_DB=0|1                Include ea-db logs (default: 1)
  SUPPORT_INCLUDE_DB_VOLUME=0|1         Include ea-db mount/volume attribution (default: 1)
  SUPPORT_INCLUDE_DB_SIZE=0|1           Include DB size snapshot via db_size.sh (default: 1)
  SUPPORT_INCLUDE_PRODUCT_CONTROL=0|1   Include mirrored weekly pulse and journey-gate summary (default: 1)
  SUPPORT_INCLUDE_GROUNDING=0|1         Include mirrored help/support/operator grounding summary (default: 1)
                                        and codex governance guidance (default: 1)
  Source-dirty group evidence is always included with its verifier as redacted JSON
                                        so clean-receipt blockers survive handoff and incident review.
  SUPPORT_DB_SIZE_LIMIT=<n>             Top table count for DB size snapshot (default: 10)
  SUPPORT_INCLUDE_QUEUE=0|1             Include queued task snapshot (default: 1)
EOF
  exit 0
fi

if docker compose version >/dev/null 2>&1; then
  DC=(docker compose)
else
  DC=(docker-compose)
fi

# Keep optional FastestVPN operator-lane vars from leaking compose warnings into generic bundles.
export FASTESTVPN_PROXY_PORT="${FASTESTVPN_PROXY_PORT:-3128}"

OUT_DIR="${EA_ROOT}/artifacts"
mkdir -p "${OUT_DIR}"
STAMP_FMT="${SUPPORT_BUNDLE_TIMESTAMP_FMT:-%Y%m%dT%H%M%SZ}"
STAMP="$(date -u +"${STAMP_FMT}")"
PREFIX="${SUPPORT_BUNDLE_PREFIX:-support_bundle}"
UNIQUE_SUFFIX="${SUPPORT_BUNDLE_UNIQUE_SUFFIX:-$$}"
if [[ -n "${UNIQUE_SUFFIX}" ]]; then
  OUT_FILE="${OUT_DIR}/${PREFIX}_${STAMP}_${UNIQUE_SUFFIX}.txt"
else
  OUT_FILE="${OUT_DIR}/${PREFIX}_${STAMP}.txt"
fi
TAIL_LINES="${SUPPORT_LOG_TAIL_LINES:-300}"
INCLUDE_DB="${SUPPORT_INCLUDE_DB:-1}"
INCLUDE_API="${SUPPORT_INCLUDE_API:-1}"
INCLUDE_DB_VOLUME="${SUPPORT_INCLUDE_DB_VOLUME:-1}"
INCLUDE_DB_SIZE="${SUPPORT_INCLUDE_DB_SIZE:-1}"
INCLUDE_PRODUCT_CONTROL="${SUPPORT_INCLUDE_PRODUCT_CONTROL:-1}"
INCLUDE_GROUNDING="${SUPPORT_INCLUDE_GROUNDING:-1}"
DB_SIZE_LIMIT="${SUPPORT_DB_SIZE_LIMIT:-10}"
INCLUDE_QUEUE="${SUPPORT_INCLUDE_QUEUE:-1}"
API_SERVICE="${PROPERTYQUARRY_API_SERVICE:-${EA_API_SERVICE:-ea-api}}"
DB_SERVICE="${PROPERTYQUARRY_DB_SERVICE:-${EA_DB_SERVICE:-ea-db}}"
DB_CONTAINER="${EA_DB_CONTAINER:-${DB_SERVICE}}"
SUPPORT_TMP_FILES=()

cleanup_support_tmp_files() {
  local path
  for path in "${SUPPORT_TMP_FILES[@]:-}"; do
    if [[ -n "${path}" ]]; then
      rm -f "${path}"
    fi
  done
}
trap cleanup_support_tmp_files EXIT

redact() {
  sed -E \
    -e 's#(postgresql://[^:]+:)[^@]+@#\1REDACTED@#g' \
    -e 's#([Pp][Aa][Ss][Ss][Ww][Oo][Rr][Dd][^=:\n]{0,40}[=:])[^\n ]+#\1REDACTED#g' \
    -e 's#([Pp][Aa][Ss][Ss][Ww][Dd][^=:\n]{0,40}[=:])[^\n ]+#\1REDACTED#g' \
    -e 's#([Tt][Oo][Kk][Ee][Nn][^=:\n]{0,40}[=:])[^\n ]+#\1REDACTED#g' \
    -e 's#([Ss][Ee][Cc][Rr][Ee][Tt][^=:\n]{0,40}[=:])[^\n ]+#\1REDACTED#g' \
    -e 's#([Aa][Pp][Ii][_-]?[Kk][Ee][Yy][^=:\n]{0,40}[=:])[^\n ]+#\1REDACTED#g'
}

print_product_control_summary() {
  python3 - <<'PY'
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

root = Path.cwd()
sys.path.insert(0, str(root / "ea"))
pulse_path = root / ".codex-design/product/WEEKLY_PRODUCT_PULSE.generated.json"
default_journey_path = Path(os.environ.get("EA_FLEET_JOURNEY_GATES_PATH") or root / "ea/_completion/fleet/JOURNEY_GATES.generated.json")

from app.product.service import _public_guide_freshness_projection


def load_json(path: Path) -> dict[str, object] | None:
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


pulse = load_json(pulse_path) if pulse_path.exists() else None
signals = dict((pulse or {}).get("supporting_signals") or {})
configured_journey = str(signals.get("journey_gate_source") or "").strip()
journey_path = (root / configured_journey).resolve() if configured_journey else default_journey_path
journey = load_json(journey_path) if journey_path.exists() else None
journey_summary = dict((journey or {}).get("summary") or {})
journies = [dict(row) for row in list((journey or {}).get("journeys") or []) if isinstance(row, dict)]
pulse_gate = dict((pulse or {}).get("journey_gate_health") or {})
route = dict(signals.get("provider_route_stewardship") or {})
public_guide = _public_guide_freshness_projection()
support_closures_waiting = sum(int(dict(row.get("signals") or {}).get("support_closure_waiting_count") or 0) for row in journies)
support_human_responses = sum(int(dict(row.get("signals") or {}).get("support_needs_human_response_count") or 0) for row in journies)

journey_state = str(pulse_gate.get("state") or journey_summary.get("overall_state") or "missing").strip() or "missing"
journey_action = str(journey_summary.get("recommended_action") or pulse_gate.get("reason") or "No published journey action.").strip()
support_fallout_state = "watch" if (support_closures_waiting or support_human_responses) else "clear"

print(f"pulse_path={pulse_path if pulse_path.exists() else 'missing'}")
print(f"pulse_generated_at={str((pulse or {}).get('generated_at') or 'missing').strip() or 'missing'}")
print(f"active_wave={str((pulse or {}).get('active_wave') or 'missing').strip() or 'missing'}")
print(f"active_wave_status={str((pulse or {}).get('active_wave_status') or 'missing').strip() or 'missing'}")
print(f"launch_readiness={str(signals.get('launch_readiness') or 'missing').strip() or 'missing'}")
print(f"journey_gates_path={journey_path if journey_path.exists() else 'missing'}")
print(f"journey_generated_at={str((journey or {}).get('generated_at') or 'missing').strip() or 'missing'}")
print(f"journey_gate_state={journey_state}")
print(f"journey_gate_action={journey_action}")
print(f"support_fallout_state={support_fallout_state}")
print(f"support_closures_waiting={support_closures_waiting}")
print(f"support_human_responses_needed={support_human_responses}")
print(f"route_review_due={str(route.get('review_due') or 'not published').strip() or 'not published'}")
print(f"public_guide_path={str(public_guide.get('path') or 'missing').strip() or 'missing'}")
print(f"public_guide_generated_at={str(public_guide.get('generated_at') or 'missing').strip() or 'missing'}")
print(f"public_guide_freshness={str(public_guide.get('state') or 'missing').strip() or 'missing'}")
print(f"public_guide_detail={str(public_guide.get('detail') or 'No public-guide freshness is mirrored.').strip() or 'No public-guide freshness is mirrored.'}")
PY
}

print_grounding_summary() {
  python3 - <<'PY'
from __future__ import annotations

from pathlib import Path

import yaml

root = Path.cwd()
design_root = root / ".codex-design" / "product"


def load_yaml(path: Path) -> dict[str, object]:
    try:
        payload = yaml.safe_load(path.read_text())
    except Exception:
        return {}
    return dict(payload or {}) if isinstance(payload, dict) else {}


def compact(value: object) -> str:
    return " ".join(str(value or "").split()).strip() or "missing"


trust = load_yaml(design_root / "PUBLIC_TRUST_CONTENT.yaml")
release = load_yaml(design_root / "PUBLIC_RELEASE_EXPERIENCE.yaml")
scorecard = load_yaml(design_root / "PRODUCT_HEALTH_SCORECARD.yaml")

help_page = next(
    (dict(row) for row in list(trust.get("trust_pages") or []) if isinstance(row, dict) and str(row.get("id") or "").strip() == "help"),
    {},
)
support_scorecard = next(
    (dict(row) for row in list(scorecard.get("scorecards") or []) if isinstance(row, dict) and str(row.get("id") or "").strip() == "support_and_feedback_closure"),
    {},
)
first_action = next((dict(row) for row in list(help_page.get("actions") or []) if isinstance(row, dict)), {})
first_metric = next((dict(row) for row in list(support_scorecard.get("metrics") or []) if isinstance(row, dict)), {})
cadence = dict(scorecard.get("cadence") or {})

print(f"public_help_heading={compact(help_page.get('heading') or 'Get help without guessing')}")
print(f"public_help_summary={compact(help_page.get('intro') or release.get('release_notes_summary'))}")
if first_action:
    print(f"public_help_primary_action={compact(first_action.get('label'))} -> {compact(first_action.get('href'))}")
print(f"support_scorecard_question={compact(support_scorecard.get('question'))}")
if first_metric:
    print(f"support_scorecard_target={compact(first_metric.get('name'))} target {compact(first_metric.get('target'))}")
print(f"operator_review_cadence={compact(cadence.get('review') or 'weekly')}")
print(f"operator_snapshot_owner={compact(cadence.get('snapshot_owner') or 'product_governor')}")
PY
}

print_codex_governance_summary() {
  python3 - <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

root = Path.cwd()
sys.path.insert(0, str(root / "ea"))

from app.api.routes.responses import _codex_governance_payload, _codex_profiles


def compact(value: object) -> str:
    return " ".join(str(value or "").split()).strip() or "missing"


profiles = {
    str(item.get("profile") or "").strip(): dict(item)
    for item in _codex_profiles()
    if isinstance(item, dict)
}
governance = _codex_governance_payload()
cadence = dict(governance.get("review_cadence") or {})
support = dict(governance.get("support_help_boundary") or {})

print(f"codex_review_cadence={compact(cadence.get('review') or 'weekly')}")
print(f"codex_snapshot_owner={compact(cadence.get('snapshot_owner') or 'product_governor')}")
print(f"codex_easy_expectation={compact(dict(profiles.get('easy') or {}).get('expectation_summary'))}")
print(f"codex_core_expectation={compact(dict(profiles.get('core') or {}).get('expectation_summary'))}")
print(f"codex_groundwork_expectation={compact(dict(profiles.get('groundwork') or {}).get('expectation_summary'))}")
print(f"codex_audit_expectation={compact(dict(profiles.get('audit') or {}).get('expectation_summary'))}")
print(f"codex_support_help_boundary={compact(support.get('summary'))}")
PY
}

print_runtime_supply_chain_summary() {
  python3 - <<'PY'
from __future__ import annotations

def compact(value: object) -> str:
    return " ".join(str(value or "").split()).strip() or "missing"

try:
    from scripts.verify_runtime_supply_chain import verify
    payload = dict(verify() or {})
except Exception as exc:
    payload = {
        "contract_name": "ea.runtime_supply_chain.v1",
        "status": "error",
        "issues": ["runtime_supply_chain_verifier_error"],
        "error": str(exc),
        "checked": {},
    }

issues = [str(item).strip() for item in list(payload.get("issues") or []) if str(item).strip()]
checked = dict(payload.get("checked") or {})
dockerfiles = ", ".join(str(item) for item in list(checked.get("dockerfiles") or [])[:4]) or "missing"
compose_services = ", ".join(str(item) for item in list(checked.get("compose_services") or [])[:8]) or "missing"
compose_images = dict(checked.get("compose_images") or {})
compose_images_text = ", ".join(
    f"{key}={value}" for key, value in sorted(compose_images.items()) if str(key).strip() and str(value).strip()
) or "missing"

print(f"contract_name={compact(payload.get('contract_name') or 'ea.runtime_supply_chain.v1')}")
print(f"status={compact(payload.get('status') or 'fail')}")
print(f"issues={compact(', '.join(issues) if issues else 'none')}")
print(f"requirements_txt={compact(checked.get('requirements_txt'))}")
print(f"requirements_lock={compact(checked.get('requirements_lock'))}")
print(f"dockerfiles={dockerfiles}")
print(f"compose_services={compose_services}")
print(f"compose_images={compose_images_text}")
PY
}

{
  echo "== Support Bundle =="
  echo "generated_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo

  echo "-- version info --"
  bash scripts/version_info.sh || true
  echo

  echo "-- release authority --"
  "${PYTHON_BIN}" scripts/materialize_release_authority_status.py >/dev/null 2>&1 || true
  "${PYTHON_BIN}" scripts/verify_release_authority.py --pretty 2>&1 | redact || true
  echo
  "${PYTHON_BIN}" - <<'PY' 2>&1 | redact || true
from __future__ import annotations

import json
from pathlib import Path

root = Path.cwd()
status_path = root / ".codex-studio" / "published" / "release_authority_status.generated.json"
deploy_context_path = root / ".codex-studio" / "published" / "deploy_context.generated.json"
try:
    payload = json.loads(status_path.read_text(encoding="utf-8"))
except Exception:
    payload = {}
print(f"deploy_context_path={deploy_context_path}")
print(json.dumps(payload, indent=2, sort_keys=True))
PY
  echo
  "${PYTHON_BIN}" - <<'PY' 2>&1 | redact || true
from __future__ import annotations

import json
from pathlib import Path

root = Path.cwd()
status_path = root / ".codex-studio" / "published" / "release_authority_status.generated.json"
try:
    payload = json.loads(status_path.read_text(encoding="utf-8"))
except Exception:
    payload = {}

issues = [str(item).strip() for item in list(payload.get("issues") or []) if str(item).strip()]
deploy_context_gate = dict(payload.get("deploy_context_gate") or {})
deploy_context_gate_issues = [
    str(item).strip() for item in list(deploy_context_gate.get("issues") or []) if str(item).strip()
]
print(f"release_next_action={str(payload.get('next_action') or '').strip() or 'missing'}")
print(f"release_issues={', '.join(issues) if issues else 'none'}")
print(f"deploy_context_gate_status={str(deploy_context_gate.get('status') or '').strip() or 'missing'}")
print(f"deploy_context_gate_issues={', '.join(deploy_context_gate_issues) if deploy_context_gate_issues else 'none'}")
PY
  echo
  bash scripts/release_authority_probe.sh 2>&1 | redact || true
  echo
  "${PYTHON_BIN}" scripts/verify_release_authority_runtime.py --pretty 2>&1 | redact || true
  echo
  "${PYTHON_BIN}" scripts/verify_release_authority_runtime.py --pretty --require-authoritative 2>&1 | redact || true
  echo
  "${PYTHON_BIN}" - <<'PY' 2>&1 | redact || true
from __future__ import annotations

import json
from pathlib import Path

root = Path.cwd()
manifest_path = root / ".codex-studio" / "published" / "release_manifest.generated.json"

try:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
except Exception:
    payload = {}

def emit(key: str) -> None:
    value = str(payload.get(key) or "").strip() or "missing"
    print(f"{key}={value}")

emit("deploy_context_generated_at")
emit("deploy_context_branch")
emit("deploy_context_tracking_branch")
emit("deploy_context_commit_sha")
PY
  echo

  echo "-- runtime supply chain --"
  print_runtime_supply_chain_summary | redact || true
  echo

  echo "-- memorial readiness --"
  memorial_readiness_tmp="$(mktemp)"
  SUPPORT_TMP_FILES+=("${memorial_readiness_tmp}")
  "${PYTHON_BIN}" scripts/verify_memorial_gold_readiness.py --pretty >"${memorial_readiness_tmp}" 2>&1 || true
  cat "${memorial_readiness_tmp}" | redact || true
  echo
  "${PYTHON_BIN}" - "${memorial_readiness_tmp}" <<'PY' 2>&1 | redact || true
from __future__ import annotations

import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
try:
    payload = json.loads(path.read_text(encoding="utf-8").strip() or "{}")
except Exception:
    payload = {"status": "error", "next_action": "inspect_memorial_gold_readiness_output", "next_command": "python3 scripts/verify_memorial_gold_readiness.py --pretty"}
operator_status_path = Path(".codex-design/product/MEMORIAL_OPERATOR_STATUS.generated.json")
try:
    operator_status = json.loads(operator_status_path.read_text(encoding="utf-8").strip() or "{}")
except Exception:
    operator_status = {}
print(f"memorial_status={str(payload.get('status') or '').strip() or 'missing'}")
print(f"memorial_next_action={str(payload.get('next_action') or '').strip() or 'missing'}")
print(f"memorial_next_command={str(payload.get('next_command') or '').strip() or 'missing'}")
blocker_summary = dict(payload.get("blocker_summary") or {})
blocked_commands = [
    str(item).strip()
    for item in list(blocker_summary.get("blocked_commands") or [])
    if str(item).strip()
]
if not blocked_commands:
    blocked_commands = [
        str(item.get("next_command") or "").strip()
        for item in list(blocker_summary.get("blocked_components") or [])
        if isinstance(item, dict) and str(item.get("next_command") or "").strip()
    ]
deduped_blocked_commands = []
for command in blocked_commands:
    if command not in deduped_blocked_commands:
        deduped_blocked_commands.append(command)
print(f"memorial_blocker_commands={' | '.join(deduped_blocked_commands[:8]) if deduped_blocked_commands else 'none'}")
print(f"memorial_source_dirty={bool(payload.get('source_worktree_dirty'))}")
print(f"memorial_source_dirty_count={int(payload.get('source_dirty_count') or 0)}")
cleanup = dict(payload.get("source_cleanup") or {})
print(f"memorial_source_cleanup_status={str(cleanup.get('status') or 'missing').strip() or 'missing'}")
cleanup_commands = [
    str(item).strip()
    for item in list(cleanup.get("handoff_commands") or [])
    if str(item).strip()
]
print(f"memorial_source_cleanup_commands={' | '.join(cleanup_commands[:6]) if cleanup_commands else 'none'}")
verifier = dict(payload.get("source_dirty_verifier") or {})
print(f"memorial_source_dirty_verifier_status={str(verifier.get('status') or 'missing').strip() or 'missing'}")
verifier_issues = [str(item).strip() for item in list(verifier.get("issues") or []) if str(item).strip()]
print(f"memorial_source_dirty_verifier_issues={', '.join(verifier_issues[:6]) if verifier_issues else 'none'}")
summary = dict(payload.get("source_dirty_summary") or {})
categories = [
    f"{str(item.get('category') or '').strip()}:{int(item.get('visible_count') or 0)}"
    for item in list(summary.get("categories") or [])
    if isinstance(item, dict) and str(item.get("category") or "").strip()
]
print(f"memorial_source_dirty_categories={', '.join(categories[:6]) if categories else 'none'}")
room_packet = dict(operator_status.get("room_audio_attestation_packet") or payload.get("room_audio_attestation_packet") or {})
room_detail = dict(operator_status.get("room_audio_receipt_detail") or payload.get("room_audio_receipt_detail") or {})
print(f"memorial_room_packet_status={str(room_packet.get('status') or 'missing').strip() or 'missing'}")
print(f"memorial_room_packet_command={str(room_packet.get('operator_command') or 'make materialize-memorial-room-audio-gold-clean').strip() or 'make materialize-memorial-room-audio-gold-clean'}")
print(f"memorial_room_receipt_command={str(room_packet.get('receipt_command_template') or 'missing').strip() or 'missing'}")
room_hints = []
for item in list(room_detail.get("missing_input_hints") or []):
    if not isinstance(item, dict):
        continue
    kind = str(item.get("kind") or "").strip()
    name = str(item.get("name") or "").strip()
    if kind and name:
        room_hints.append(f"{kind}:{name}")
print(f"memorial_room_missing_inputs={'; '.join(room_hints[:10]) if room_hints else 'none'}")
failed_codes = [str(item).strip() for item in list(room_detail.get("failed_codes") or []) if str(item).strip()]
print(f"memorial_room_failed_codes={', '.join(failed_codes[:10]) if failed_codes else 'none'}")
PY
  rm -f "${memorial_readiness_tmp}"
  SUPPORT_TMP_FILES=("${SUPPORT_TMP_FILES[@]/${memorial_readiness_tmp}/}")
  echo

  echo "-- source dirty groups --"
  "${PYTHON_BIN}" scripts/inspect_source_dirty_groups.py --json --limit 5 2>&1 | redact || true
  echo

  echo "-- source dirty verifier --"
  "${PYTHON_BIN}" scripts/verify_source_dirty_groups.py 2>&1 | redact || true
  echo

  if [[ "${INCLUDE_PRODUCT_CONTROL}" == "1" ]]; then
    echo "-- product control --"
    print_product_control_summary | redact || true
    echo
  else
    echo "-- product control --"
    echo "skipped (SUPPORT_INCLUDE_PRODUCT_CONTROL=${INCLUDE_PRODUCT_CONTROL})"
    echo
  fi

  if [[ "${INCLUDE_GROUNDING}" == "1" ]]; then
    echo "-- grounding --"
    print_grounding_summary | redact || true
    echo
    echo "-- codex governance --"
    print_codex_governance_summary | redact || true
    echo
  else
    echo "-- grounding --"
    echo "skipped (SUPPORT_INCLUDE_GROUNDING=${INCLUDE_GROUNDING})"
    echo
    echo "-- codex governance --"
    echo "skipped (SUPPORT_INCLUDE_GROUNDING=${INCLUDE_GROUNDING})"
    echo
  fi

  echo "-- compose ps --"
  "${DC[@]}" ps || true
  echo

  if [[ "${INCLUDE_API}" == "1" ]]; then
    echo "-- ea-api logs (tail ${TAIL_LINES}) --"
    "${DC[@]}" logs --tail "${TAIL_LINES}" "${API_SERVICE}" 2>&1 | redact || true
    echo
  else
    echo "-- ea-api logs --"
    echo "skipped (SUPPORT_INCLUDE_API=${INCLUDE_API})"
    echo
  fi

  if [[ "${INCLUDE_DB}" == "1" ]]; then
    echo "-- ea-db logs (tail ${TAIL_LINES}) --"
    "${DC[@]}" logs --tail "${TAIL_LINES}" "${DB_SERVICE}" 2>&1 | redact || true
    echo
  else
    echo "-- ea-db logs --"
    echo "skipped (SUPPORT_INCLUDE_DB=${INCLUDE_DB})"
    echo
  fi

  if [[ "${INCLUDE_DB_VOLUME}" == "1" ]]; then
    echo "-- ea-db volume attribution --"
    echo "expected_runtime_volume=ea_pgdata"
    echo "expected_container_mount=/var/lib/postgresql/data"
    echo "compose_declared_volumes=$("${DC[@]}" config --volumes 2>/dev/null | tr '\n' ' ' | sed 's/[[:space:]]\+/ /g' | sed 's/^ *//; s/ *$//')"
    if docker inspect "${DB_CONTAINER}" >/dev/null 2>&1; then
      docker inspect "${DB_CONTAINER}" --format '{{range .Mounts}}{{println .Name "|" .Source "|" .Destination "|" .Type}}{{end}}' 2>/dev/null | redact || true
    else
      echo "ea-db mount inspection unavailable"
    fi
    echo
  else
    echo "-- ea-db volume attribution --"
    echo "skipped (SUPPORT_INCLUDE_DB_VOLUME=${INCLUDE_DB_VOLUME})"
    echo
  fi

  if [[ "${INCLUDE_DB_SIZE}" == "1" ]]; then
    echo "-- db size snapshot --"
    EA_DB_SIZE_LIMIT="${DB_SIZE_LIMIT}" bash scripts/db_size.sh 2>&1 | redact || true
    echo
  else
    echo "-- db size snapshot --"
    echo "skipped (SUPPORT_INCLUDE_DB_SIZE=${INCLUDE_DB_SIZE})"
    echo
  fi

  if [[ "${INCLUDE_QUEUE}" == "1" ]]; then
    echo "-- queued task snapshot --"
    if [[ -f TASKS_WORK_LOG.md ]]; then
      awk '/^## Queue/{flag=1;next}/^## In Progress/{flag=0}flag' TASKS_WORK_LOG.md || true
    else
      echo "local task log not present"
    fi
  else
    echo "-- queued task snapshot --"
    echo "skipped (SUPPORT_INCLUDE_QUEUE=${INCLUDE_QUEUE})"
  fi
} > "${OUT_FILE}"

echo "support bundle written: ${OUT_FILE}"
