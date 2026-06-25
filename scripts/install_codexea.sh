#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="${ROOT}/scripts/codexea"
DEST="${HOME}/.local/bin/codexea"
SHARE_ROOT="${HOME}/.local/share/codexea/fleet"
SHIM_DEST="${SHARE_ROOT}/scripts/codexea"
ROUTE_SRC="${ROOT}/scripts/codexea_route.py"
ROUTE_DEST="${SHARE_ROOT}/scripts/codexea_route.py"
LAUNCHER_TMP="$(mktemp)"
trap 'rm -f "${LAUNCHER_TMP}"' EXIT

mkdir -p "$(dirname "${DEST}")"
mkdir -p "$(dirname "${SHIM_DEST}")"
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
  managed_shim="${install_prefix}/share/codexea/fleet/scripts/codexea"
fi

if [ ! -x "${managed_shim}" ]; then
  echo "Missing managed CodexEA shim: ${managed_shim}" >&2
  exit 1
fi

exec "${managed_shim}" "$@"
EOF
install -m 755 "${SRC}" "${SHIM_DEST}"
install -m 755 "${ROUTE_SRC}" "${ROUTE_DEST}"
install -m 755 "${LAUNCHER_TMP}" "${DEST}"
printf 'Installed launcher -> %s\n' "${DEST}"
printf 'Installed %s -> %s\n' "${SRC}" "${SHIM_DEST}"
printf 'Installed %s -> %s\n' "${ROUTE_SRC}" "${ROUTE_DEST}"
