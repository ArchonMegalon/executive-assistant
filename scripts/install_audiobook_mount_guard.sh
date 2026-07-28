#!/usr/bin/env bash
set -Eeuo pipefail

umask 022

if (( EUID != 0 )); then
  printf 'run this installer with sudo\n' >&2
  exit 2
fi

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
repo_root="$(cd -- "${script_dir}/.." && pwd -P)"
guard_source="${repo_root}/scripts/audiobook_mount_guard.sh"
service_source="${repo_root}/ops/systemd/ea-audiobook-mount-guard.service"
timer_source="${repo_root}/ops/systemd/ea-audiobook-mount-guard.timer"
guard_target="/usr/local/libexec/ea-audiobook-mount-guard"
checksum_target="/etc/ea-audiobook-mount-guard.sha256"
service_target="/etc/systemd/system/ea-audiobook-mount-guard.service"
timer_target="/etc/systemd/system/ea-audiobook-mount-guard.timer"
memorial_url="${EA_MEMORIAL_LIVE_URL:-https://myexternalbrain.com/memorials/manfred}"
health_url="${EA_HEALTH_LIVE_URL:-https://myexternalbrain.com/health}"
invoking_uid="${SUDO_UID:-0}"
temporary_paths=()

cleanup() {
  local path=""
  for path in "${temporary_paths[@]}"; do
    rm -f -- "${path}" || true
  done
}
trap cleanup EXIT

for command_name in bash curl install jq mktemp sha256sum stat systemctl; do
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    printf 'missing required command: %s\n' "${command_name}" >&2
    exit 2
  fi
done

trusted_source_file() {
  local path="$1"
  local owner=""
  local permissions=""

  [[ "${path}" == "${repo_root}/"* ]] || return 1
  [[ -f "${path}" && ! -L "${path}" && -r "${path}" ]] || return 1
  owner="$(stat -c '%u' -- "${path}")"
  permissions="$(stat -c '%A' -- "${path}")"
  [[ "${owner}" == "0" || "${owner}" == "${invoking_uid}" ]] || return 1
  [[ "${permissions}" =~ ^-[rwxStTs-]{9}$ ]] || return 1
  [[ "${permissions:5:1}" != "w" && "${permissions:8:1}" != "w" ]] || return 1
}

for source_path in "${guard_source}" "${service_source}" "${timer_source}"; do
  if ! trusted_source_file "${source_path}"; then
    printf 'refusing untrusted installer input: %s\n' "${source_path}" >&2
    exit 2
  fi
done

bash -n "${guard_source}"
if command -v shellcheck >/dev/null 2>&1; then
  shellcheck "${guard_source}"
fi

atomic_install() {
  local source_path="$1"
  local destination="$2"
  local mode="$3"
  local temporary=""

  temporary="$(mktemp "${destination}.tmp.XXXXXX")"
  temporary_paths+=("${temporary}")
  install -o root -g root -m "${mode}" "${source_path}" "${temporary}"
  mv -fT -- "${temporary}" "${destination}"
}

install -d -o root -g root -m 0755 /usr/local/libexec
atomic_install "${guard_source}" "${guard_target}" 0755
atomic_install "${service_source}" "${service_target}" 0644
atomic_install "${timer_source}" "${timer_target}" 0644

checksum_temporary="$(mktemp "${checksum_target}.tmp.XXXXXX")"
temporary_paths+=("${checksum_temporary}")
sha256sum "${guard_target}" >"${checksum_temporary}"
chown root:root "${checksum_temporary}"
chmod 0644 "${checksum_temporary}"
mv -fT -- "${checksum_temporary}" "${checksum_target}"
sha256sum --check --strict --status "${checksum_target}"

systemctl daemon-reload
systemctl enable --now ea-audiobook-mount-guard.timer
systemctl start ea-audiobook-mount-guard.service

timer_state="$(systemctl is-active ea-audiobook-mount-guard.timer)"
service_result="$(systemctl show --property=Result --value ea-audiobook-mount-guard.service)"
service_status="$(systemctl show --property=ExecMainStatus --value ea-audiobook-mount-guard.service)"
[[ "${timer_state}" == "active" ]]
[[ "${service_result}" == "success" ]]
[[ "${service_status}" == "0" ]]

health_payload="$(curl --fail --silent --show-error --max-time 20 "${health_url}")"
jq -e '.status == "ok"' >/dev/null <<<"${health_payload}"
memorial_status="$(
  curl \
    --fail \
    --silent \
    --show-error \
    --max-time 20 \
    --output /dev/null \
    --write-out '%{http_code}' \
    "${memorial_url}"
)"
[[ "${memorial_status}" == "200" ]]

printf 'guard_install=ok\n'
printf 'timer_state=%s\n' "${timer_state}"
printf 'service_result=%s\n' "${service_result}"
printf 'live_health=ok\n'
printf 'memorial_http_status=%s\n' "${memorial_status}"
