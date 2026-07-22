#!/usr/bin/env bash
set -euo pipefail
umask 077

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source_path="${root}/scripts/codex_host_shim.sh"
destination="${CODEX_HOST_SHIM_DEST:-${HOME}/.local/bin/codex}"
temporary="${destination}.tmp.$$"
maintenance_source="${root}/scripts/codex_log_maintenance.py"
maintenance_destination="${CODEX_LOG_MAINTENANCE_DEST:-${HOME}/.local/libexec/codex-log-maintenance}"
maintenance_temporary="${maintenance_destination}.tmp.$$"

cleanup() {
  rm -f "$temporary" "$maintenance_temporary"
}
trap cleanup EXIT

install -d -m 700 "$(dirname "$destination")"
install -d -m 700 "$(dirname "$maintenance_destination")"
install -m 755 "$maintenance_source" "$maintenance_temporary"
python3 -m py_compile "$maintenance_temporary"
install -m 755 "$source_path" "$temporary"
bash -n "$temporary"
mv -f "$maintenance_temporary" "$maintenance_destination"
mv -f "$temporary" "$destination"
trap - EXIT

printf 'Installed Codex host shim: %s\n' "$destination"
printf 'Installed Codex log maintainer: %s\n' "$maintenance_destination"
