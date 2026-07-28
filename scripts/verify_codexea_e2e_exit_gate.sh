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
successfully too. After that, it runs one live spawned `codexea easy exec`
and one live spawned `codexea core exec` probe against the current EA runtime. The easy
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
  CODEXEA_E2E_RUNTIME_ROOT
      Root of the currently deployed EA runtime. Default: `/docker/EA`.
  CODEXEA_E2E_RUNTIME_EA_ENV_PATH
      Credential env file used by the currently deployed EA runtime. Default:
      `${CODEXEA_E2E_RUNTIME_ROOT}/.env`.
  CODEXEA_E2E_RUNTIME_BASE_URL
      Dedicated EA responses-proxy origin. Defaults to the published Docker
      port for `ea-responses-proxy`, then EA_RESPONSES_PROXY_HOST_PORT, then
      `http://127.0.0.1:8092`. The public EA API is never used as fallback.
  CODEXEA_E2E_RESPONSES_PROXY_CONTAINER
      Responses-proxy container used for local published-port discovery.
      Default: `ea-responses-proxy`.
  CODEXEA_E2E_LAUNCHER
      CodexEA launcher path. Default:
      `/docker/fleet/scripts/codex-shims/codexea`.
  CODEXEA_E2E_RUNTIME_READY_PROBE_COMMAND
      Override the responses-proxy readiness probe for focused harness tests.
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
LIVE_RUNTIME_ROOT="${CODEXEA_E2E_RUNTIME_ROOT:-/docker/EA}"
LIVE_RUNTIME_ENV_PATH="${CODEXEA_E2E_RUNTIME_EA_ENV_PATH:-${LIVE_RUNTIME_ROOT}/.env}"
LIVE_RUNTIME_BASE_URL="${CODEXEA_E2E_RUNTIME_BASE_URL:-}"
RESPONSES_PROXY_CONTAINER="${CODEXEA_E2E_RESPONSES_PROXY_CONTAINER:-ea-responses-proxy}"
CODEXEA_LAUNCHER="${CODEXEA_E2E_LAUNCHER:-/docker/fleet/scripts/codex-shims/codexea}"
RUNTIME_READY_PROBE_COMMAND="${CODEXEA_E2E_RUNTIME_READY_PROBE_COMMAND:-}"
CORE_LIVE_PROMPT="${CODEXEA_E2E_CORE_LIVE_PROMPT:-Reply with exactly TASK_OK:12 and nothing else.}"
CORE_LIVE_PROBE_COMMAND="${CODEXEA_E2E_CORE_LIVE_PROBE_COMMAND:-}"

runtime_env_file_value() {
  local file="$1"
  local target="$2"
  local line=""
  local key=""
  local value=""
  [[ -f "${file}" ]] || return 1
  while IFS= read -r line || [[ -n "${line}" ]]; do
    line="${line%$'\r'}"
    case "${line}" in
      ''|\#*) continue ;;
      export\ *) line="${line#export }" ;;
    esac
    [[ "${line}" == *=* ]] || continue
    key="${line%%=*}"
    value="${line#*=}"
    if [[ "${key}" == "${target}" && -n "${value}" ]]; then
      value="${value%\"}"
      value="${value#\"}"
      value="${value%\'}"
      value="${value#\'}"
      printf '%s' "${value}"
      return 0
    fi
  done < "${file}"
  return 1
}

resolve_runtime_base_url() {
  local configured_port="${EA_RESPONSES_PROXY_HOST_PORT:-}"
  local published_binding=""
  local published_port=""
  if [[ -n "${LIVE_RUNTIME_BASE_URL}" ]]; then
    printf '%s' "${LIVE_RUNTIME_BASE_URL%/}"
    return 0
  fi
  if command -v docker >/dev/null 2>&1; then
    published_binding="$(docker port "${RESPONSES_PROXY_CONTAINER}" 8091/tcp 2>/dev/null | head -n1 || true)"
    published_port="${published_binding##*:}"
    if [[ "${published_port}" =~ ^[0-9]+$ ]]; then
      printf 'http://127.0.0.1:%s' "${published_port}"
      return 0
    fi
  fi
  if [[ -z "${configured_port}" ]]; then
    configured_port="$(runtime_env_file_value "${LIVE_RUNTIME_ROOT}/.env.local" "EA_RESPONSES_PROXY_HOST_PORT" || true)"
  fi
  if [[ -z "${configured_port}" ]]; then
    configured_port="$(runtime_env_file_value "${LIVE_RUNTIME_ROOT}/.env" "EA_RESPONSES_PROXY_HOST_PORT" || true)"
  fi
  configured_port="${configured_port:-8092}"
  if [[ ! "${configured_port}" =~ ^[0-9]+$ ]] || [[ "${configured_port}" -lt 1 ]] || [[ "${configured_port}" -gt 65535 ]]; then
    echo "Invalid EA responses-proxy host port: ${configured_port}" >&2
    return 1
  fi
  printf 'http://127.0.0.1:%s' "${configured_port}"
}

probe_runtime_ready() {
  if [[ -n "${RUNTIME_READY_PROBE_COMMAND}" ]]; then
    bash -lc "${RUNTIME_READY_PROBE_COMMAND}"
    return $?
  fi
  if command -v curl >/dev/null 2>&1; then
    curl -fsS --connect-timeout 2 --max-time 10 \
      "${LIVE_RUNTIME_BASE_URL}/health/ready" >/dev/null
    return $?
  fi
  "${PYTHON_BIN}" - "${LIVE_RUNTIME_BASE_URL}/health/ready" <<'PY'
import sys
import urllib.request

with urllib.request.urlopen(sys.argv[1], timeout=10) as response:
    raise SystemExit(0 if response.status == 200 else 1)
PY
}

LIVE_RUNTIME_BASE_URL="$(resolve_runtime_base_url)"

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
  if [[ ! -x "${CODEXEA_LAUNCHER}" ]]; then
    echo "CodexEA launcher is missing or not executable: ${CODEXEA_LAUNCHER}" >&2
    exit 1
  fi
  if ! probe_runtime_ready; then
    echo "EA responses proxy is not ready at ${LIVE_RUNTIME_BASE_URL}/health/ready." >&2
    exit 1
  fi
  live_output="$(
    EA_API_TOKEN='' \
      EA_MCP_API_TOKEN='' \
      EA_BASE_URL="${LIVE_RUNTIME_BASE_URL}" \
      EA_MCP_BASE_URL="${LIVE_RUNTIME_BASE_URL}" \
      CODEXEA_RUNTIME_EA_ENV_PATH="${LIVE_RUNTIME_ENV_PATH}" \
      timeout --foreground "${TIMEOUT_SECONDS}s" \
      bash "${CODEXEA_LAUNCHER}" \
        easy exec \
        --json \
        -C "${LIVE_RUNTIME_ROOT}/ea" \
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

if [[ -n "${LIVE_PROBE_COMMAND}" && -z "${CORE_LIVE_PROBE_COMMAND}" ]]; then
  exit 0
fi

set +e
if [[ -n "${CORE_LIVE_PROBE_COMMAND}" ]]; then
  core_output="$(
    timeout --foreground "${TIMEOUT_SECONDS}s" \
      bash -lc "${CORE_LIVE_PROBE_COMMAND}" 2>&1
  )"
else
  core_output="$(
    EA_API_TOKEN='' \
      EA_MCP_API_TOKEN='' \
      EA_BASE_URL="${LIVE_RUNTIME_BASE_URL}" \
      EA_MCP_BASE_URL="${LIVE_RUNTIME_BASE_URL}" \
      CODEXEA_RUNTIME_EA_ENV_PATH="${LIVE_RUNTIME_ENV_PATH}" \
      timeout --foreground "${TIMEOUT_SECONDS}s" \
      bash "${CODEXEA_LAUNCHER}" \
        core exec \
        --json \
        -C "${LIVE_RUNTIME_ROOT}/ea" \
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
