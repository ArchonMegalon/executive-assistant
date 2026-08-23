#!/usr/bin/env bash
set -euo pipefail
umask 077

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="${ROOT}/scripts/codexea"
ROUTE_SRC="${ROOT}/scripts/codexea_route.py"
DEST="${HOME}/.local/bin/codexea"
INSTALL_ROOT="${HOME}/.local/share/codexea"
RELEASES_ROOT="${INSTALL_ROOT}/releases"
CURRENT_LINK="${INSTALL_ROOT}/current"
PREVIOUS_LINK="${INSTALL_ROOT}/previous"
RELEASE_ID="$({
  sha256sum "${SRC}" | awk '{print $1}'
  sha256sum "${ROUTE_SRC}" | awk '{print $1}'
} | sha256sum | awk '{print $1}')"
RELEASE_DIR="${RELEASES_ROOT}/${RELEASE_ID}"
MANAGED_SHIM="${CURRENT_LINK}/scripts/codexea"
MANAGED_ROUTE="${CURRENT_LINK}/scripts/codexea_route.py"

STAGING_DIR=""
LAUNCHER_TMP=""
CURRENT_TMP=""
PREVIOUS_TMP=""
PREVIOUS_CURRENT_TARGET=""
CURRENT_SWITCHED=0
INSTALL_COMMITTED=0
RELEASE_CREATED=0

cleanup_install_transaction() {
  local status=$?
  local rollback_tmp=""

  if [ "${status}" -ne 0 ] && [ "${CURRENT_SWITCHED}" -eq 1 ] && [ "${INSTALL_COMMITTED}" -eq 0 ]; then
    if [ -n "${PREVIOUS_CURRENT_TARGET}" ]; then
      rollback_tmp="${INSTALL_ROOT}/.current-rollback.$$"
      unlink "${rollback_tmp}" 2>/dev/null || true
      ln -s "${PREVIOUS_CURRENT_TARGET}" "${rollback_tmp}"
      mv -Tf "${rollback_tmp}" "${CURRENT_LINK}"
    else
      unlink "${CURRENT_LINK}" 2>/dev/null || true
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

if [ "${1:-}" = "--rollback" ]; then
  if [ ! -L "${CURRENT_LINK}" ] || [ ! -L "${PREVIOUS_LINK}" ]; then
    echo "CodexEA rollback requires both current and previous release pointers" >&2
    exit 1
  fi
  current_target="$(readlink "${CURRENT_LINK}")"
  previous_target="$(readlink "${PREVIOUS_LINK}")"
  if ! [[ "${current_target}" =~ ^releases/[0-9a-f]{64}$ ]] ||
    ! [[ "${previous_target}" =~ ^releases/[0-9a-f]{64}$ ]]; then
    echo "CodexEA rollback pointers are not managed release targets" >&2
    exit 1
  fi
  if [ ! -x "${INSTALL_ROOT}/${previous_target}/scripts/codexea" ]; then
    echo "CodexEA previous release is not executable: ${previous_target}" >&2
    exit 1
  fi
  CURRENT_TMP="${INSTALL_ROOT}/.current-rollback.$$"
  PREVIOUS_TMP="${INSTALL_ROOT}/.previous-rollback.$$"
  ln -s "${previous_target}" "${CURRENT_TMP}"
  ln -s "${current_target}" "${PREVIOUS_TMP}"
  mv -Tf "${CURRENT_TMP}" "${CURRENT_LINK}"
  CURRENT_TMP=""
  mv -Tf "${PREVIOUS_TMP}" "${PREVIOUS_LINK}"
  PREVIOUS_TMP=""
  printf 'Rolled back CodexEA current -> %s\n' "${previous_target}"
  exit 0
elif [ "$#" -gt 0 ]; then
  echo "Unknown CodexEA install argument: $1" >&2
  exit 2
fi

if [ -e "${CURRENT_LINK}" ] && [ ! -L "${CURRENT_LINK}" ]; then
  echo "Refusing to replace non-symlink CodexEA current pointer: ${CURRENT_LINK}" >&2
  exit 1
fi
if [ -L "${CURRENT_LINK}" ]; then
  PREVIOUS_CURRENT_TARGET="$(readlink "${CURRENT_LINK}")"
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
  mv "${STAGING_DIR}" "${RELEASE_DIR}"
  STAGING_DIR=""
  RELEASE_CREATED=1
fi

if [ "$(sha256sum "${RELEASE_DIR}/scripts/codexea" | awk '{print $1}')" != "$(sha256sum "${SRC}" | awk '{print $1}')" ] ||
  [ "$(sha256sum "${RELEASE_DIR}/scripts/codexea_route.py" | awk '{print $1}')" != "$(sha256sum "${ROUTE_SRC}" | awk '{print $1}')" ]; then
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

if [ -n "${PREVIOUS_CURRENT_TARGET}" ] && [ "${PREVIOUS_CURRENT_TARGET}" != "releases/${RELEASE_ID}" ]; then
  PREVIOUS_TMP="${INSTALL_ROOT}/.previous.${RELEASE_ID}.$$"
  ln -s "${PREVIOUS_CURRENT_TARGET}" "${PREVIOUS_TMP}"
  mv -Tf "${PREVIOUS_TMP}" "${PREVIOUS_LINK}"
  PREVIOUS_TMP=""
else
  unlink "${PREVIOUS_LINK}" 2>/dev/null || true
fi
INSTALL_COMMITTED=1

# Releases are content-addressed and the current pointer is already live. Drop
# inactive releases so repeated installs cannot accumulate checkpoints.
for candidate in "${RELEASES_ROOT}"/*; do
  [ -d "${candidate}" ] || continue
  candidate_name="${candidate##*/}"
  if [ "${candidate_name}" = "${RELEASE_ID}" ]; then
    continue
  fi
  if [ -n "${PREVIOUS_CURRENT_TARGET}" ] && [ "${candidate_name}" = "${PREVIOUS_CURRENT_TARGET##*/}" ]; then
    continue
  fi
  if [[ "${candidate_name}" =~ ^[0-9a-f]{64}$ ]]; then
    find "${candidate}" -depth -delete 2>/dev/null ||
      printf 'Warning: could not clean inactive CodexEA release %s\n' "${candidate}" >&2
  fi
done

printf 'Installed launcher -> %s\n' "${DEST}"
printf 'Activated release -> %s\n' "${RELEASE_DIR}"
printf 'Installed %s -> %s\n' "${SRC}" "${MANAGED_SHIM}"
printf 'Installed %s -> %s\n' "${ROUTE_SRC}" "${MANAGED_ROUTE}"
