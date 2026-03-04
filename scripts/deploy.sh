#!/usr/bin/env bash
set -euo pipefail

EA_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "== EA deploy: ${EA_ROOT} =="

# Resolve the *real* operator (avoid sudo trap).
OWNER_UID="${SUDO_UID:-$(id -u)}"
OWNER_GID="${SUDO_GID:-$(id -g)}"

mkdir -p "${EA_ROOT}/logs" "${EA_ROOT}/attachments"

# Default perms: readable only for owner (keeps tokens private)
umask 077

if [[ ! -f "${EA_ROOT}/.env" ]]; then
  echo "!! Missing .env. Creating from .env.example"
  cp "${EA_ROOT}/.env.example" "${EA_ROOT}/.env"
  chmod 600 "${EA_ROOT}/.env"
  echo ">> Edit ${EA_ROOT}/.env and set secrets before running again."
  exit 1
fi

# Ownership to avoid EACCES when editing from the host
if [[ "$(id -u)" -eq 0 ]]; then
  chown -R "${OWNER_UID}:${OWNER_GID}" "${EA_ROOT}" || true
elif command -v sudo >/dev/null 2>&1; then
  sudo chown -R "${OWNER_UID}:${OWNER_GID}" "${EA_ROOT}" || true
else
  echo "⚠️ sudo not available; skipping chown. If you hit EACCES, run: chown -R ${OWNER_UID}:${OWNER_GID} ${EA_ROOT}"
fi

echo "== Docker sanity checks =="
docker info >/dev/null

echo "== Bring up stack =="
cd "${EA_ROOT}"
docker compose up -d --build

echo "== Waiting for health =="
HOST_PORT="$(grep -E '^EA_HOST_PORT=' "${EA_ROOT}/.env" | tail -n1 | cut -d= -f2- || true)"
HOST_PORT="${HOST_PORT:-8090}"
for i in $(seq 1 60); do
  if curl -fsS "http://localhost:${HOST_PORT}/health" >/dev/null 2>&1; then
    echo "✅ EA is healthy on http://localhost:${HOST_PORT}"
    exit 0
  fi
  sleep 1
done

echo "❌ EA did not become healthy. Showing logs:"
docker compose logs --tail 200 ea-api ea-worker ea-poller ea-outbox ea-event-worker || true
exit 1
