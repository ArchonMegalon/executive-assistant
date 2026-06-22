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
  export TEABLE_API_KEY=...
  # Optional when using a non-default Teable host:
  export TEABLE_BASE_URL=https://app.teable.ai
  scripts/bootstrap_from_teable.sh
  scripts/bootstrap_from_teable.sh --check
  scripts/bootstrap_from_teable.sh --drill
  scripts/bootstrap_from_teable.sh --ensure-local
  scripts/bootstrap_from_teable.sh --fresh-host
  scripts/bootstrap_from_teable.sh --probe

If the executable bit was not preserved by your transfer method, use:
  bash scripts/bootstrap_from_teable.sh
  bash scripts/bootstrap_from_teable.sh --check
  bash scripts/bootstrap_from_teable.sh --drill
  bash scripts/bootstrap_from_teable.sh --ensure-local
  bash scripts/bootstrap_from_teable.sh --fresh-host
  bash scripts/bootstrap_from_teable.sh --probe

Restore EA root/service env files and referenced secret files from the Teable
environment recovery table, then verify the restored state by hash. Existing
files are preserved as timestamped .bak files before restored values are written.

Use --check to verify the Teable table and run a non-destructive drill with
automatic cleanup. Use --drill to restore into a private temporary directory
without overwriting live env files. The drill output contains secret material;
delete it after inspection. Use --ensure-local to verify local env/config
artifacts against Teable and recover only when they are missing or mismatched.
Use --fresh-host to require a shell-seeded TEABLE_API_KEY, discover the table
by name, and recover the live env/config artifacts with the same assumptions as
a new host. Use --probe to require the same shell-seeded TEABLE_API_KEY,
exercise table discovery, perform full recovery into a throwaway private
directory, then clean that directory up.
EOF
  exit 0
fi

if [[ -z "${TEABLE_API_KEY:-}" && ! -f "${EA_ROOT}/.env" ]]; then
  cat >&2 <<'EOF'
TEABLE_API_KEY is required when no local .env exists.

Seed it first:
  export TEABLE_API_KEY=...
  # Optional when using a non-default Teable host:
  export TEABLE_BASE_URL=https://app.teable.ai
EOF
  exit 2
fi

if [[ "${1:-}" == "--check" ]]; then
  "${PYTHON_BIN}" "${EA_ROOT}/scripts/sync_env_to_teable.py" check
  exit 0
fi

if [[ "${1:-}" == "--drill" ]]; then
  "${PYTHON_BIN}" "${EA_ROOT}/scripts/sync_env_to_teable.py" drill
  exit 0
fi

if [[ "${1:-}" == "--ensure-local" ]]; then
  "${PYTHON_BIN}" "${EA_ROOT}/scripts/sync_env_to_teable.py" ensure-local
  exit 0
fi

if [[ "${1:-}" == "--fresh-host" ]]; then
  if [[ -z "${TEABLE_API_KEY:-}" ]]; then
    cat >&2 <<'EOF'
TEABLE_API_KEY must be seeded in the shell for fresh-host recovery.

Seed it first:
  export TEABLE_API_KEY=...
  # Optional when using a non-default Teable host:
  export TEABLE_BASE_URL=https://app.teable.ai
EOF
    exit 2
  fi
  "${PYTHON_BIN}" "${EA_ROOT}/scripts/sync_env_to_teable.py" recover \
    --require-seeded-api-key \
    --table-id ""
  exit 0
fi

if [[ "${1:-}" == "--probe" ]]; then
  if [[ -z "${TEABLE_API_KEY:-}" ]]; then
    cat >&2 <<'EOF'
TEABLE_API_KEY must be seeded in the shell for fresh-host probe recovery.

Seed it first:
  export TEABLE_API_KEY=...
  # Optional when using a non-default Teable host:
  export TEABLE_BASE_URL=https://app.teable.ai
EOF
    exit 2
  fi
  probe_dir="$(mktemp -d "${TMPDIR:-/tmp}/ea-teable-recover-probe-XXXXXX")"
  cleanup_probe() {
    rm -rf "${probe_dir}"
  }
  trap cleanup_probe EXIT
  "${PYTHON_BIN}" "${EA_ROOT}/scripts/sync_env_to_teable.py" recover \
    --require-seeded-api-key \
    --table-id "" \
    --root-output-path "${probe_dir}/.env" \
    --local-output-path "${probe_dir}/.env.local" \
    --service-output-path "${probe_dir}/ea/.env" \
    --no-backup-existing
  exit 0
fi

if [[ -n "${1:-}" ]]; then
  echo "Unknown argument: ${1}" >&2
  echo "Use --help for usage." >&2
  exit 2
fi

"${PYTHON_BIN}" "${EA_ROOT}/scripts/sync_env_to_teable.py" recover
