#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env"
POOL_SIZE="${1:-${FASTESTVPN_PROXY_POOL_SIZE:-20}}"
POOL_NETWORK="${EA_PROXY_POOL_NETWORK:-ea_default}"
POOL_PROXY_PORT="${FASTESTVPN_PROXY_PORT:-3128}"
STATE_ROOT="${ROOT_DIR}/state/fastestvpn-proxy-pool"
IMAGE_NAME="${FASTESTVPN_PROXY_IMAGE:-ea-fastestvpn-proxy:latest}"

[[ -f "${ENV_FILE}" ]] || {
  printf '[ensure-fastestvpn-proxy-pool] missing env file: %s\n' "${ENV_FILE}" >&2
  exit 1
}

env_value() {
  python3 - "$ENV_FILE" "$1" <<'PY'
from pathlib import Path
import sys

env_path = Path(sys.argv[1])
target = sys.argv[2]
for line in env_path.read_text().splitlines():
    if not line or line.lstrip().startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    if key.strip() == target:
        print(value.strip())
        break
PY
}

FASTESTVPN_USERNAME="${FASTESTVPN_USERNAME:-$(env_value FASTESTVPN_USERNAME)}"
FASTESTVPN_PASSWORD="${FASTESTVPN_PASSWORD:-$(env_value FASTESTVPN_PASSWORD)}"
POOL_PROXY_PORT="${FASTESTVPN_PROXY_PORT:-$(env_value FASTESTVPN_PROXY_PORT)}"
POOL_PROXY_PORT="${POOL_PROXY_PORT:-3128}"

[[ -n "${FASTESTVPN_USERNAME:-}" ]] || {
  printf '[ensure-fastestvpn-proxy-pool] FASTESTVPN_USERNAME is required\n' >&2
  exit 1
}
[[ -n "${FASTESTVPN_PASSWORD:-}" ]] || {
  printf '[ensure-fastestvpn-proxy-pool] FASTESTVPN_PASSWORD is required\n' >&2
  exit 1
}

mapfile -t CONFIG_FILES < <(
  python3 - <<'PY'
from pathlib import Path

root = Path("/docker/EA/vpn/fastestvpn")
selected = []
seen = set()
for path in sorted(root.glob("*-tcp.ovpn")):
    stem = path.stem
    key = stem[:-4] if stem.endswith("-tcp") else stem
    if key in seen:
        continue
    seen.add(key)
    selected.append(path.name)
print("\n".join(selected))
PY
)

if (( ${#CONFIG_FILES[@]} < POOL_SIZE )); then
  printf '[ensure-fastestvpn-proxy-pool] only %s configs available for pool size %s\n' "${#CONFIG_FILES[@]}" "${POOL_SIZE}" >&2
  exit 1
fi

docker build -t "${IMAGE_NAME}" -f "${ROOT_DIR}/docker/fastestvpn-proxy/Dockerfile" "${ROOT_DIR}" >/dev/null

mkdir -p "${STATE_ROOT}"

pool_urls=()
for (( i=1; i<=POOL_SIZE; i++ )); do
  idx=$(( i - 1 ))
  container_name="$(printf 'ea-fastestvpn-proxy-%02d' "${i}")"
  config_file="${CONFIG_FILES[$idx]}"
  state_dir="${STATE_ROOT}/${container_name}"
  mkdir -p "${state_dir}"
  docker rm -f "${container_name}" >/dev/null 2>&1 || true
  docker run -d \
    --name "${container_name}" \
    --restart unless-stopped \
    --network "${POOL_NETWORK}" \
    --cap-add NET_ADMIN \
    --device /dev/net/tun \
    -e FASTESTVPN_USERNAME="${FASTESTVPN_USERNAME}" \
    -e FASTESTVPN_PASSWORD="${FASTESTVPN_PASSWORD}" \
    -e FASTESTVPN_CONFIG_DIR=/vpn/fastestvpn \
    -e FASTESTVPN_CONFIG_FILE="${config_file}" \
    -e FASTESTVPN_PROXY_PORT="${POOL_PROXY_PORT}" \
    -e FASTESTVPN_PROXY_LISTEN=0.0.0.0 \
    -v "${ROOT_DIR}/vpn/fastestvpn:/vpn/fastestvpn:ro" \
    -v "${state_dir}:/state" \
    "${IMAGE_NAME}" >/dev/null
  pool_urls+=("http://${container_name}:${POOL_PROXY_PORT}")
done

for (( i=1; i<=POOL_SIZE; i++ )); do
  container_name="$(printf 'ea-fastestvpn-proxy-%02d' "${i}")"
  for _ in $(seq 1 90); do
    status="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}unknown{{end}}' "${container_name}" 2>/dev/null || true)"
    if [[ "${status}" == "healthy" ]]; then
      break
    fi
    sleep 2
  done
  status="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}unknown{{end}}' "${container_name}" 2>/dev/null || true)"
  if [[ "${status}" != "healthy" ]]; then
    printf '[ensure-fastestvpn-proxy-pool] proxy %s failed health\n' "${container_name}" >&2
    docker logs "${container_name}" >&2 || true
    exit 1
  fi
done

printf '%s\n' "$(IFS=,; echo "${pool_urls[*]}")"
