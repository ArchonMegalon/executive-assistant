#!/usr/bin/env bash
set -euo pipefail

CONFIG_DIR="${FASTESTVPN_CONFIG_DIR:-/vpn/fastestvpn}"
CONFIG_GLOB="${FASTESTVPN_CONFIG_GLOB:-*.ovpn}"
CONFIG_SELECT_MODE="${FASTESTVPN_CONFIG_SELECT_MODE:-random}"
CONFIG_FILE="${FASTESTVPN_CONFIG_FILE:-}"
STATE_DIR="${FASTESTVPN_STATE_DIR:-/state}"
PROXY_PORT="${FASTESTVPN_PROXY_PORT:-3128}"
PROXY_LISTEN="${FASTESTVPN_PROXY_LISTEN:-0.0.0.0}"
USERNAME="${FASTESTVPN_USERNAME:-}"
PASSWORD="${FASTESTVPN_PASSWORD:-}"
AUTH_FILE="${STATE_DIR}/fastestvpn-auth.txt"
SELECTION_FILE="${STATE_DIR}/selected-config.txt"
ROUND_ROBIN_FILE="${STATE_DIR}/round-robin-index.txt"
OPENVPN_LOG="/tmp/openvpn.log"
OPENVPN_STATUS="/tmp/openvpn-status.log"
TINYPROXY_CONF="/tmp/tinyproxy.conf"

log() {
  printf '[fastestvpn-proxy] %s\n' "$*"
}

die() {
  log "ERROR: $*"
  exit 1
}

cleanup() {
  if [[ -n "${OPENVPN_PID:-}" ]] && kill -0 "${OPENVPN_PID}" 2>/dev/null; then
    kill "${OPENVPN_PID}" 2>/dev/null || true
    wait "${OPENVPN_PID}" 2>/dev/null || true
  fi
}

trap cleanup EXIT INT TERM

mkdir -p "${STATE_DIR}"

[[ -n "${USERNAME}" ]] || die "FASTESTVPN_USERNAME is required"
[[ -n "${PASSWORD}" ]] || die "FASTESTVPN_PASSWORD is required"
[[ -d "${CONFIG_DIR}" ]] || die "FASTESTVPN_CONFIG_DIR not found: ${CONFIG_DIR}"

printf '%s\n%s\n' "${USERNAME}" "${PASSWORD}" > "${AUTH_FILE}"
chmod 600 "${AUTH_FILE}"

resolve_config() {
  local chosen=""
  if [[ -n "${CONFIG_FILE}" ]]; then
    if [[ -f "${CONFIG_FILE}" ]]; then
      chosen="${CONFIG_FILE}"
    elif [[ -f "${CONFIG_DIR}/${CONFIG_FILE}" ]]; then
      chosen="${CONFIG_DIR}/${CONFIG_FILE}"
    else
      die "FASTESTVPN_CONFIG_FILE not found: ${CONFIG_FILE}"
    fi
  else
    mapfile -t configs < <(find "${CONFIG_DIR}" -maxdepth 1 -type f -name "${CONFIG_GLOB}" | sort)
    [[ "${#configs[@]}" -gt 0 ]] || die "No FastestVPN OpenVPN configs found in ${CONFIG_DIR} matching ${CONFIG_GLOB}"
    case "${CONFIG_SELECT_MODE}" in
      first)
        chosen="${configs[0]}"
        ;;
      round_robin)
        local idx=0
        if [[ -f "${ROUND_ROBIN_FILE}" ]]; then
          idx="$(cat "${ROUND_ROBIN_FILE}" 2>/dev/null || printf '0')"
        fi
        idx="$(( idx % ${#configs[@]} ))"
        chosen="${configs[$idx]}"
        printf '%s' "$(( (idx + 1) % ${#configs[@]} ))" > "${ROUND_ROBIN_FILE}"
        ;;
      random|*)
        chosen="${configs[RANDOM % ${#configs[@]}]}"
        ;;
    esac
  fi
  printf '%s' "${chosen}" > "${SELECTION_FILE}"
  printf '%s' "${chosen}"
}

render_tinyproxy() {
  sed \
    -e "s/__PROXY_PORT__/${PROXY_PORT}/g" \
    -e "s/__PROXY_LISTEN__/${PROXY_LISTEN}/g" \
    /etc/tinyproxy/tinyproxy.conf.template > "${TINYPROXY_CONF}"
}

wait_for_openvpn() {
  local waited=0
  while (( waited < 90 )); do
    if grep -q "Initialization Sequence Completed" "${OPENVPN_LOG}" 2>/dev/null; then
      return 0
    fi
    if ! kill -0 "${OPENVPN_PID}" 2>/dev/null; then
      log "OpenVPN exited early."
      cat "${OPENVPN_LOG}" 2>/dev/null || true
      return 1
    fi
    sleep 1
    waited=$((waited + 1))
  done
  log "OpenVPN did not become ready within 90s."
  cat "${OPENVPN_LOG}" 2>/dev/null || true
  return 1
}

chosen_config="$(resolve_config)"
log "Selected OpenVPN config: ${chosen_config}"

: > "${OPENVPN_LOG}"
: > "${OPENVPN_STATUS}"

openvpn \
  --config "${chosen_config}" \
  --auth-user-pass "${AUTH_FILE}" \
  --log "${OPENVPN_LOG}" \
  --status "${OPENVPN_STATUS}" 10 \
  --script-security 2 \
  --verb 3 &
OPENVPN_PID=$!

wait_for_openvpn || die "OpenVPN startup failed"

render_tinyproxy
log "Starting local HTTP proxy on ${PROXY_LISTEN}:${PROXY_PORT}"
exec tinyproxy -d -c "${TINYPROXY_CONF}"
