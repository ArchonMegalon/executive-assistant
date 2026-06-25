#!/usr/bin/env bash
set -euo pipefail

EA_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  cat <<'EOF'
Usage:
  bash scripts/release_authority_probe.sh [--raw]

Fetch the live /health/release-authority payload from the local runtime and
print a compact release-authority summary. Uses EA_HOST_PORT, then .env,
then 8090. Pass --raw to print the full JSON payload.
EOF
  exit 0
fi

RAW=0
if [[ "${1:-}" == "--raw" ]]; then
  RAW=1
fi

HOST_PORT="${EA_HOST_PORT:-}"
if [[ -z "${HOST_PORT}" && -f "${EA_ROOT}/.env" ]]; then
  HOST_PORT="$(grep -E '^EA_HOST_PORT=' "${EA_ROOT}/.env" | tail -n1 | cut -d= -f2- || true)"
fi
HOST_PORT="${HOST_PORT:-8090}"
BASE="http://localhost:${HOST_PORT}"
PAYLOAD_URL=""
payload=""
for candidate in \
  "${BASE}/health/release-authority" \
  "${BASE}/app/health/release-authority"
do
  if payload="$(curl -fsS "${candidate}" 2>/dev/null)"; then
    PAYLOAD_URL="${candidate}"
    break
  fi
done

if [[ -z "${PAYLOAD_URL}" ]]; then
  version_payload="$(curl -fsS "${BASE}/version" 2>/dev/null || true)"
  >&2 echo "release authority endpoint unavailable at ${BASE}"
  if [[ -n "${version_payload}" ]]; then
    >&2 echo "live /version:"
    >&2 printf '%s\n' "${version_payload}"
  fi
  exit 22
fi

if [[ "${RAW}" == "1" ]]; then
  printf '%s\n' "${payload}" | python3 -m json.tool
  exit 0
fi

PAYLOAD_JSON="${payload}" python3 - <<'PY'
from __future__ import annotations

import json
import os


def compact(value: object) -> str:
    return " ".join(str(value or "").split()).strip() or "missing"


payload = json.loads(os.environ["PAYLOAD_JSON"])
release = dict(payload.get("release_authority") or {})
gate = dict(payload.get("release_authority_gate") or {})
deploy_context_gate = dict(payload.get("deploy_context_gate") or {})
supply = dict(payload.get("runtime_supply_chain") or {})
supply_gate = dict(payload.get("runtime_supply_chain_gate") or {})

print(f"release_state={compact(release.get('state') or 'missing')}")
print(f"release_posture={compact(release.get('authority_posture') or 'missing_manifest')}")
print(f"release_summary={compact(release.get('summary'))}")
print(f"release_next_action={compact(release.get('next_action'))}")
print(f"branch={compact(release.get('branch'))}")
print(f"tracking_branch={compact(release.get('tracking_branch'))}")
print(f"commit_sha={compact(release.get('commit_sha'))}")
print(f"deployment_id={compact(release.get('deployment_id'))}")
print(f"deployment_id_source={compact(release.get('deployment_id_source'))}")
print(f"public_origin={compact(release.get('public_origin'))}")
print(f"public_origin_source={compact(release.get('public_origin_source'))}")
print(f"project_mode={compact(release.get('project_mode'))}")
print(f"generated_at={compact(release.get('generated_at'))}")
print(f"release_gate_status={compact(gate.get('status') or 'fail')}")
print(f"release_gate_issues={compact(', '.join(str(item) for item in list(gate.get('issues') or []) if str(item).strip()) or 'none')}")
print(f"deploy_context_gate_status={compact(deploy_context_gate.get('status') or 'fail')}")
print(f"deploy_context_gate_issues={compact(', '.join(str(item) for item in list(deploy_context_gate.get('issues') or []) if str(item).strip()) or 'none')}")
print(f"runtime_supply_state={compact(supply.get('state') or 'watch')}")
print(f"runtime_supply_summary={compact(supply.get('summary'))}")
print(f"runtime_supply_next_action={compact(supply.get('next_action'))}")
print(f"runtime_supply_gate_status={compact(supply_gate.get('status') or 'fail')}")
print(f"runtime_supply_gate_issues={compact(', '.join(str(item) for item in list(supply_gate.get('issues') or []) if str(item).strip()) or 'none')}")
PY
