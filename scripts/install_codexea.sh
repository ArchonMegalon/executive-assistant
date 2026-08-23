#!/usr/bin/env bash
set -euo pipefail
umask 077

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="${ROOT}/scripts/codexea"
DEST="${HOME}/.local/bin/codexea"
SHARE_ROOT="${HOME}/.local/share/codexea/fleet"
SHIM_DEST="${SHARE_ROOT}/scripts/codexea"
ROUTE_SRC="${ROOT}/scripts/codexea_route.py"
ROUTE_DEST="${SHARE_ROOT}/scripts/codexea_route.py"

mkdir -p "$(dirname "${DEST}")"
install -d -m 700 "$(dirname "${SHIM_DEST}")"
LAUNCHER_TMP="$(mktemp "$(dirname "${DEST}")/.codexea-launcher.XXXXXX")"
SHIM_TMP="$(mktemp "$(dirname "${SHIM_DEST}")/.codexea-shim.XXXXXX")"
ROUTE_TMP="$(mktemp "$(dirname "${ROUTE_DEST}")/.codexea-route.XXXXXX")"
trap 'rm -f "${LAUNCHER_TMP}" "${SHIM_TMP}" "${ROUTE_TMP}"' EXIT
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
install -m 755 "${SRC}" "${SHIM_TMP}"
install -m 755 "${ROUTE_SRC}" "${ROUTE_TMP}"
chmod 755 "${LAUNCHER_TMP}"
mv -f "${SHIM_TMP}" "${SHIM_DEST}"
mv -f "${ROUTE_TMP}" "${ROUTE_DEST}"
mv -f "${LAUNCHER_TMP}" "${DEST}"
printf 'Installed launcher -> %s\n' "${DEST}"
printf 'Installed %s -> %s\n' "${SRC}" "${SHIM_DEST}"
printf 'Installed %s -> %s\n' "${ROUTE_SRC}" "${ROUTE_DEST}"
