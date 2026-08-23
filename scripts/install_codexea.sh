#!/usr/bin/env bash
set -euo pipefail
umask 077

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="${ROOT}/scripts/codexea"
ROUTE_SRC="${ROOT}/scripts/codexea_route.py"

release_id_for_files() {
  local shim_path="${1:-}"
  local route_path="${2:-}"
  local shim_digest=""
  local route_digest=""

  [ -f "${shim_path}" ] || return 1
  [ -f "${route_path}" ] || return 1
  shim_digest="$(sha256sum "${shim_path}" | awk '{print $1}')" || return 1
  route_digest="$(sha256sum "${route_path}" | awk '{print $1}')" || return 1
  printf '%s\n%s\n' "${shim_digest}" "${route_digest}" | sha256sum | awk '{print $1}'
}

DEST="${HOME}/.local/bin/codexea"
INSTALL_ROOT="${HOME}/.local/share/codexea"
RELEASES_ROOT="${INSTALL_ROOT}/releases"
CURRENT_LINK="${INSTALL_ROOT}/current"
PREVIOUS_LINK="${INSTALL_ROOT}/previous"
INSTALL_LOCK="${INSTALL_ROOT}/install.lock"
RELEASE_ID="$(release_id_for_files "${SRC}" "${ROUTE_SRC}")"
RELEASE_DIR="${RELEASES_ROOT}/${RELEASE_ID}"
MANAGED_SHIM="${CURRENT_LINK}/scripts/codexea"
MANAGED_ROUTE="${CURRENT_LINK}/scripts/codexea_route.py"

STAGING_DIR=""
LAUNCHER_TMP=""
CURRENT_TMP=""
PREVIOUS_TMP=""
PREVIOUS_CURRENT_TARGET=""
ORIGINAL_CURRENT_TARGET=""
ORIGINAL_PREVIOUS_TARGET=""
ORIGINAL_CURRENT_PRESENT=0
ORIGINAL_PREVIOUS_PRESENT=0
CURRENT_SWITCHED=0
PREVIOUS_SWITCHED=0
ROLLBACK_EXCHANGED=0
INSTALL_COMMITTED=0
RELEASE_CREATED=0
INSTALL_LOCK_FD=""

validate_release_target() {
  local target="${1:-}"
  local expected_id=""
  local release_path=""
  local shim_path=""
  local route_path=""
  local actual_id=""

  [[ "${target}" =~ ^releases/[0-9a-f]{64}$ ]] || return 1
  expected_id="${target##*/}"
  release_path="${INSTALL_ROOT}/${target}"
  shim_path="${release_path}/scripts/codexea"
  route_path="${release_path}/scripts/codexea_route.py"

  [ -d "${release_path}" ] && [ ! -L "${release_path}" ] || return 1
  [ -f "${shim_path}" ] && [ ! -L "${shim_path}" ] && [ -x "${shim_path}" ] || return 1
  [ -f "${route_path}" ] && [ ! -L "${route_path}" ] && [ -x "${route_path}" ] || return 1
  bash -n "${shim_path}" >/dev/null 2>&1 || return 1
  python3 - "${route_path}" >/dev/null 2>&1 <<'PY' || return 1
from pathlib import Path
import sys

path = Path(sys.argv[1])
compile(path.read_text(encoding="utf-8"), str(path), "exec")
PY
  actual_id="$(release_id_for_files "${shim_path}" "${route_path}")" || return 1
  [ "${actual_id}" = "${expected_id}" ]
}

cleanup_staging_checkpoints() {
  local staged=""
  while IFS= read -r -d '' staged; do
    [ -d "${staged}" ] || continue
    find "${staged}" -depth -delete 2>/dev/null || true
  done < <(find "${RELEASES_ROOT}" -mindepth 1 -maxdepth 2 -type d -name '.staging.*' -print0)
}

prune_inactive_releases() {
  local current_target="${1:-}"
  local previous_target="${2:-}"
  local current_id="${current_target##*/}"
  local previous_id="${previous_target##*/}"
  local candidate=""
  local candidate_name=""

  for candidate in "${RELEASES_ROOT}"/*; do
    [ -d "${candidate}" ] || continue
    candidate_name="${candidate##*/}"
    if [ "${candidate_name}" = "${current_id}" ] ||
      { [ -n "${previous_target}" ] && [ "${candidate_name}" = "${previous_id}" ]; }; then
      continue
    fi
    if [[ "${candidate_name}" =~ ^[0-9a-f]{64}$ ]]; then
      find "${candidate}" -depth -delete 2>/dev/null ||
        printf 'Warning: could not clean inactive CodexEA release %s\n' "${candidate}" >&2
    fi
  done
}

restore_managed_link() {
  local link_path="${1:-}"
  local was_present="${2:-0}"
  local target="${3:-}"
  local label="${4:-link}"
  local restore_tmp="${INSTALL_ROOT}/.${label}-restore.$$"

  unlink "${restore_tmp}" 2>/dev/null || true
  if [ "${was_present}" -eq 1 ]; then
    if ! ln -s "${target}" "${restore_tmp}" || ! mv -Tf "${restore_tmp}" "${link_path}"; then
      printf 'Warning: could not restore CodexEA %s pointer\n' "${label}" >&2
      unlink "${restore_tmp}" 2>/dev/null || true
    fi
  else
    unlink "${link_path}" 2>/dev/null || true
  fi
}

exchange_managed_links() {
  local first_path="${1:-}"
  local second_path="${2:-}"

  python3 - "${first_path}" "${second_path}" <<'PY'
import ctypes
import os
import sys

AT_FDCWD = -100
RENAME_EXCHANGE = 2
libc = ctypes.CDLL(None, use_errno=True)
renameat2 = libc.renameat2
renameat2.argtypes = (
    ctypes.c_int,
    ctypes.c_char_p,
    ctypes.c_int,
    ctypes.c_char_p,
    ctypes.c_uint,
)
renameat2.restype = ctypes.c_int
first = os.fsencode(sys.argv[1])
second = os.fsencode(sys.argv[2])
if renameat2(AT_FDCWD, first, AT_FDCWD, second, RENAME_EXCHANGE) != 0:
    error = ctypes.get_errno()
    raise OSError(error, os.strerror(error), (sys.argv[1], sys.argv[2]))
PY
}

cleanup_install_transaction() {
  local status=$?
  set +e

  if [ "${status}" -ne 0 ] && [ "${INSTALL_COMMITTED}" -eq 0 ]; then
    if [ "${ROLLBACK_EXCHANGED}" -eq 1 ]; then
      if ! exchange_managed_links "${CURRENT_LINK}" "${PREVIOUS_LINK}"; then
        echo "Warning: could not atomically restore CodexEA rollback pointers" >&2
      fi
    else
      if [ "${PREVIOUS_SWITCHED}" -eq 1 ]; then
        restore_managed_link "${PREVIOUS_LINK}" "${ORIGINAL_PREVIOUS_PRESENT}" "${ORIGINAL_PREVIOUS_TARGET}" "previous"
      fi
      if [ "${CURRENT_SWITCHED}" -eq 1 ]; then
        restore_managed_link "${CURRENT_LINK}" "${ORIGINAL_CURRENT_PRESENT}" "${ORIGINAL_CURRENT_TARGET}" "current"
      fi
    fi
  fi
  if [ "${status}" -ne 0 ] && [ "${INSTALL_COMMITTED}" -eq 0 ] && [ "${RELEASE_CREATED}" -eq 1 ] && [ -d "${RELEASE_DIR}" ]; then
    find "${RELEASE_DIR}" -depth -delete 2>/dev/null || true
  fi

  for path in "${LAUNCHER_TMP}" "${CURRENT_TMP}" "${PREVIOUS_TMP}"; do
    if [ -n "${path}" ] && { [ -e "${path}" ] || [ -L "${path}" ]; }; then
      unlink "${path}" 2>/dev/null || true
    fi
  done
  if [ -n "${STAGING_DIR}" ] && [ -d "${STAGING_DIR}" ]; then
    find "${STAGING_DIR}" -depth -delete 2>/dev/null || true
  fi
  return "${status}"
}
trap cleanup_install_transaction EXIT

mkdir -p "$(dirname "${DEST}")"
install -d -m 700 "${INSTALL_ROOT}" "${RELEASES_ROOT}"

if ! command -v flock >/dev/null 2>&1; then
  echo "CodexEA installer requires flock for transaction serialization" >&2
  exit 1
fi
exec {INSTALL_LOCK_FD}>"${INSTALL_LOCK}"
flock -x "${INSTALL_LOCK_FD}"
cleanup_staging_checkpoints

if [ -e "${CURRENT_LINK}" ] && [ ! -L "${CURRENT_LINK}" ]; then
  echo "Refusing to replace non-symlink CodexEA current pointer: ${CURRENT_LINK}" >&2
  exit 1
fi
if [ -e "${PREVIOUS_LINK}" ] && [ ! -L "${PREVIOUS_LINK}" ]; then
  echo "Refusing to replace non-symlink CodexEA previous pointer: ${PREVIOUS_LINK}" >&2
  exit 1
fi
if [ -L "${CURRENT_LINK}" ]; then
  ORIGINAL_CURRENT_PRESENT=1
  ORIGINAL_CURRENT_TARGET="$(readlink "${CURRENT_LINK}")"
fi
if [ -L "${PREVIOUS_LINK}" ]; then
  ORIGINAL_PREVIOUS_PRESENT=1
  ORIGINAL_PREVIOUS_TARGET="$(readlink "${PREVIOUS_LINK}")"
fi
PREVIOUS_CURRENT_TARGET="${ORIGINAL_CURRENT_TARGET}"

if [ "${1:-}" = "--rollback" ]; then
  if [ "${ORIGINAL_CURRENT_PRESENT}" -ne 1 ] || [ "${ORIGINAL_PREVIOUS_PRESENT}" -ne 1 ]; then
    echo "CodexEA rollback requires both current and previous release pointers" >&2
    exit 1
  fi
  current_target="${ORIGINAL_CURRENT_TARGET}"
  previous_target="${ORIGINAL_PREVIOUS_TARGET}"
  if ! [[ "${current_target}" =~ ^releases/[0-9a-f]{64}$ ]] ||
    ! [[ "${previous_target}" =~ ^releases/[0-9a-f]{64}$ ]]; then
    echo "CodexEA rollback pointers are not managed release targets" >&2
    exit 1
  fi
  if [ "${current_target}" = "${previous_target}" ]; then
    echo "CodexEA rollback pointers identify the same release" >&2
    exit 1
  fi
  if ! validate_release_target "${previous_target}"; then
    echo "CodexEA previous release is incomplete or fails its content digest: ${previous_target}" >&2
    exit 1
  fi
  exchange_managed_links "${CURRENT_LINK}" "${PREVIOUS_LINK}"
  CURRENT_SWITCHED=1
  PREVIOUS_SWITCHED=1
  ROLLBACK_EXCHANGED=1
  if [ "${CODEXEA_INSTALL_FAILPOINT:-}" = "rollback_after_current_switch" ]; then
    echo "CodexEA install failpoint rollback_after_current_switch" >&2
    exit 98
  fi
  if [ "${CODEXEA_INSTALL_FAILPOINT:-}" = "rollback_after_previous_switch" ]; then
    echo "CodexEA install failpoint rollback_after_previous_switch" >&2
    exit 99
  fi
  INSTALL_COMMITTED=1
  cleanup_staging_checkpoints
  prune_inactive_releases "${previous_target}" "${current_target}"
  printf 'Rolled back CodexEA current -> %s\n' "${previous_target}"
  exit 0
elif [ "$#" -gt 0 ]; then
  echo "Unknown CodexEA install argument: $1" >&2
  exit 2
fi

if [ "${ORIGINAL_CURRENT_PRESENT}" -eq 1 ]; then
  if ! [[ "${PREVIOUS_CURRENT_TARGET}" =~ ^releases/[0-9a-f]{64}$ ]]; then
    echo "Refusing unmanaged CodexEA current target: ${PREVIOUS_CURRENT_TARGET}" >&2
    exit 1
  fi
fi

if [ ! -d "${RELEASE_DIR}" ]; then
  STAGING_DIR="$(mktemp -d "${RELEASES_ROOT}/.staging.XXXXXX")"
  install -d -m 700 "${STAGING_DIR}/scripts"
  install -m 755 "${SRC}" "${STAGING_DIR}/scripts/codexea"
  install -m 755 "${ROUTE_SRC}" "${STAGING_DIR}/scripts/codexea_route.py"
  bash -n "${STAGING_DIR}/scripts/codexea"
  python3 - "${STAGING_DIR}/scripts/codexea_route.py" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
compile(path.read_text(encoding="utf-8"), str(path), "exec")
PY
  mv -T "${STAGING_DIR}" "${RELEASE_DIR}"
  STAGING_DIR=""
  RELEASE_CREATED=1
fi

if ! validate_release_target "releases/${RELEASE_ID}"; then
  echo "Refusing incoherent CodexEA release directory: ${RELEASE_DIR}" >&2
  exit 1
fi

CURRENT_TMP="${INSTALL_ROOT}/.current.${RELEASE_ID}.$$"
ln -s "releases/${RELEASE_ID}" "${CURRENT_TMP}"
mv -Tf "${CURRENT_TMP}" "${CURRENT_LINK}"
CURRENT_TMP=""
CURRENT_SWITCHED=1

if [ "${CODEXEA_INSTALL_FAILPOINT:-}" = "after_current_switch" ]; then
  echo "CodexEA install failpoint after_current_switch" >&2
  exit 97
fi

LAUNCHER_TMP="$(mktemp "$(dirname "${DEST}")/.codexea-launcher.XXXXXX")"
cat > "${LAUNCHER_TMP}" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

launcher_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
install_prefix="$(cd "${launcher_dir}/.." && pwd)"

if [ -n "${CODEXEA_MANAGED_SHIM:-}" ]; then
  managed_shim="${CODEXEA_MANAGED_SHIM}"
elif [ -n "${CODEXEA_FLEET_ROOT:-}" ]; then
  managed_shim="${CODEXEA_FLEET_ROOT%/}/scripts/codexea"
else
  managed_shim="${install_prefix}/share/codexea/current/scripts/codexea"
fi

if [ ! -x "${managed_shim}" ]; then
  echo "Missing managed CodexEA shim: ${managed_shim}" >&2
  exit 1
fi

exec "${managed_shim}" "$@"
EOF
chmod 755 "${LAUNCHER_TMP}"
mv -f "${LAUNCHER_TMP}" "${DEST}"
LAUNCHER_TMP=""

DESIRED_PREVIOUS_TARGET=""
if [ -n "${PREVIOUS_CURRENT_TARGET}" ] && [ "${PREVIOUS_CURRENT_TARGET}" != "releases/${RELEASE_ID}" ]; then
  if validate_release_target "${PREVIOUS_CURRENT_TARGET}"; then
    DESIRED_PREVIOUS_TARGET="${PREVIOUS_CURRENT_TARGET}"
  else
    printf 'Warning: not retaining invalid prior CodexEA release %s\n' "${PREVIOUS_CURRENT_TARGET}" >&2
  fi
elif [ "${PREVIOUS_CURRENT_TARGET}" = "releases/${RELEASE_ID}" ] &&
  [ "${ORIGINAL_PREVIOUS_PRESENT}" -eq 1 ] &&
  [ "${ORIGINAL_PREVIOUS_TARGET}" != "releases/${RELEASE_ID}" ] &&
  validate_release_target "${ORIGINAL_PREVIOUS_TARGET}"; then
  DESIRED_PREVIOUS_TARGET="${ORIGINAL_PREVIOUS_TARGET}"
fi

if [ -n "${DESIRED_PREVIOUS_TARGET}" ] &&
  { [ "${ORIGINAL_PREVIOUS_PRESENT}" -ne 1 ] || [ "${ORIGINAL_PREVIOUS_TARGET}" != "${DESIRED_PREVIOUS_TARGET}" ]; }; then
  PREVIOUS_TMP="${INSTALL_ROOT}/.previous.${RELEASE_ID}.$$"
  ln -s "${DESIRED_PREVIOUS_TARGET}" "${PREVIOUS_TMP}"
  mv -Tf "${PREVIOUS_TMP}" "${PREVIOUS_LINK}"
  PREVIOUS_TMP=""
  PREVIOUS_SWITCHED=1
elif [ -z "${DESIRED_PREVIOUS_TARGET}" ] && [ "${ORIGINAL_PREVIOUS_PRESENT}" -eq 1 ]; then
  unlink "${PREVIOUS_LINK}" 2>/dev/null || true
  PREVIOUS_SWITCHED=1
fi
INSTALL_COMMITTED=1

# Keep exactly the active release and one validated rollback release. The lock
# serializes this cleanup with staging, activation, and rollback.
cleanup_staging_checkpoints
prune_inactive_releases "releases/${RELEASE_ID}" "${DESIRED_PREVIOUS_TARGET}"

printf 'Installed launcher -> %s\n' "${DEST}"
printf 'Activated release -> %s\n' "${RELEASE_DIR}"
printf 'Installed %s -> %s\n' "${SRC}" "${MANAGED_SHIM}"
printf 'Installed %s -> %s\n' "${ROUTE_SRC}" "${MANAGED_ROUTE}"
