#!/usr/bin/env bash
set -euo pipefail

EA_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
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
  bash scripts/verify_codexea_e2e_exit_gate.sh

Spawns real local `codexea` subprocesses inside the pytest harness and fails
closed unless the worker-lane smoke tasks launch successfully end to end
through both the repo shim and the installed launcher wrapper, and the
installed launcher startup-status and compact-pretty status paths render
successfully too. After that, it runs live spawned `codexea easy exec`
and `codexea core exec` probes against the current EA runtime. The easy
probe must return `READY`; the core probe must complete a tiny semantic task
and return `TASK_OK:12`.

Environment:
  CODEXEA_E2E_EXIT_GATE_TIMEOUT_SECONDS
      Bound the spawned-gate verification runtime. Default: 300.
  CODEXEA_E2E_LIVE_PROMPT
      Override the live spawned `codexea` smoke prompt. Default:
      `Reply with exactly READY and nothing else.`
  CODEXEA_E2E_LIVE_PROBE_COMMAND
      Override the live spawned probe command for focused harness testing.
  CODEXEA_E2E_CORE_LIVE_PROMPT
      Override the live spawned core smoke prompt. Default:
      `Reply with exactly TASK_OK:12 and nothing else.`
  CODEXEA_E2E_CORE_LIVE_PROBE_COMMAND
      Override the live spawned core probe command for focused harness testing.
EOF
  exit 0
fi

if [[ "$#" -gt 0 ]]; then
  echo "Unknown arguments: $*" >&2
  exit 2
fi

TIMEOUT_SECONDS_RAW="${CODEXEA_E2E_EXIT_GATE_TIMEOUT_SECONDS:-300}"
if [[ ! "${TIMEOUT_SECONDS_RAW}" =~ ^[0-9]+$ ]] || [[ "${TIMEOUT_SECONDS_RAW}" -lt 1 ]]; then
  echo "Invalid CODEXEA_E2E_EXIT_GATE_TIMEOUT_SECONDS: ${TIMEOUT_SECONDS_RAW}" >&2
  exit 2
fi
TIMEOUT_SECONDS="${TIMEOUT_SECONDS_RAW}"
PYTEST_K_EXPR="spawned_codexea_exit_gate_runs_smoke_task_through_worker_lane or installed_launcher_spawned_codexea_exit_gate_runs_smoke_task_through_worker_lane or installed_launcher_startup_status_prints_pending_route_instead_of_error or installed_launcher_status_pretty_output_surfaces_onemin_host_hotspots_outside_repo"
LIVE_PROMPT="${CODEXEA_E2E_LIVE_PROMPT:-Reply with exactly READY and nothing else.}"
LIVE_PROBE_COMMAND="${CODEXEA_E2E_LIVE_PROBE_COMMAND:-}"
CORE_LIVE_PROMPT="${CODEXEA_E2E_CORE_LIVE_PROMPT:-Reply with exactly TASK_OK:12 and nothing else.}"
CORE_LIVE_PROBE_COMMAND="${CODEXEA_E2E_CORE_LIVE_PROBE_COMMAND:-}"

cd "${EA_ROOT}"
set +e
if command -v timeout >/dev/null 2>&1; then
  PYTHONPATH=ea timeout --foreground "${TIMEOUT_SECONDS}s" \
    "${PYTHON_BIN}" -m pytest -q tests/test_codexea_shim.py \
    -k "${PYTEST_K_EXPR}"
  status=$?
else
  PYTHONPATH=ea "${PYTHON_BIN}" - <<PY
from __future__ import annotations

import os
import subprocess
import sys

try:
    completed = subprocess.run(
        [
            ${PYTHON_BIN@Q},
            "-m",
            "pytest",
            "-q",
            "tests/test_codexea_shim.py",
            "-k",
            ${PYTEST_K_EXPR@Q},
        ],
        check=False,
        timeout=${TIMEOUT_SECONDS},
        env={**os.environ, "PYTHONPATH": "ea"},
    )
except subprocess.TimeoutExpired:
    sys.exit(124)
sys.exit(completed.returncode)
PY
  status=$?
fi
set -e

if [[ "${status}" -eq 124 ]]; then
  echo "CodexEA E2E exit gate timed out after ${TIMEOUT_SECONDS}s." >&2
fi
if [[ "${status}" -ne 0 ]]; then
  exit "${status}"
fi

set +e
if [[ -n "${LIVE_PROBE_COMMAND}" ]]; then
  live_output="$(
    timeout --foreground "${TIMEOUT_SECONDS}s" \
      bash -lc "${LIVE_PROBE_COMMAND}" 2>&1
  )"
else
  live_output="$(
    timeout --foreground "${TIMEOUT_SECONDS}s" \
      bash /docker/fleet/scripts/codex-shims/codexea \
        easy exec \
        --json \
        -C /docker/EA/ea \
        --skip-git-repo-check \
        --dangerously-bypass-approvals-and-sandbox \
        --color never \
        "${LIVE_PROMPT}" 2>&1
  )"
fi
status=$?
set -e

if [[ "${status}" -eq 124 ]]; then
  echo "CodexEA live spawned exec probe timed out after ${TIMEOUT_SECONDS}s." >&2
  exit "${status}"
fi
if [[ "${status}" -ne 0 ]]; then
  printf '%s\n' "${live_output}" >&2
  exit "${status}"
fi
if ! printf '%s\n' "${live_output}" | grep -qx 'READY'; then
  echo "CodexEA live spawned exec probe did not return a clean READY closeout." >&2
  printf '%s\n' "${live_output}" >&2
  exit 1
fi

printf '%s\n' "${live_output}"

set +e
if [[ -n "${CORE_LIVE_PROBE_COMMAND}" ]]; then
  core_output="$(
    timeout --foreground "${TIMEOUT_SECONDS}s" \
      bash -lc "${CORE_LIVE_PROBE_COMMAND}" 2>&1
  )"
else
  core_output="$(
    timeout --foreground "${TIMEOUT_SECONDS}s" \
      bash /docker/fleet/scripts/codex-shims/codexea \
        core exec \
        --json \
        -C /docker/EA/ea \
        --skip-git-repo-check \
        --dangerously-bypass-approvals-and-sandbox \
        --color never \
        "${CORE_LIVE_PROMPT}" 2>&1
  )"
fi
status=$?
set -e

if [[ "${status}" -eq 124 ]]; then
  echo "CodexEA live spawned core exec probe timed out after ${TIMEOUT_SECONDS}s." >&2
  exit "${status}"
fi
if [[ "${status}" -ne 0 ]]; then
  printf '%s\n' "${core_output}" >&2
  exit "${status}"
fi
if ! printf '%s\n' "${core_output}" | grep -qx 'TASK_OK:12'; then
  echo "CodexEA live spawned core exec probe did not return a clean TASK_OK:12 closeout." >&2
  printf '%s\n' "${core_output}" >&2
  exit 1
fi

printf '%s\n' "${core_output}"
exit 0
