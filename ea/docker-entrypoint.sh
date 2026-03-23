#!/bin/sh
set -eu

LEDGER_DIR="${EA_RESPONSES_PROVIDER_LEDGER_DIR:-/data/provider-ledger}"
ARTIFACTS_DIR="${EA_ARTIFACTS_DIR:-/tmp/ea_artifacts}"

if [ "$(id -u)" = "0" ]; then
  mkdir -p "${LEDGER_DIR}"
  mkdir -p "${ARTIFACTS_DIR}"
  chown -R ea:ea "${LEDGER_DIR}"
  chown -R ea:ea "${ARTIFACTS_DIR}"
  if [ -S /var/run/docker.sock ]; then
    DOCKER_GID="$(stat -c '%g' /var/run/docker.sock 2>/dev/null || true)"
    if [ -n "${DOCKER_GID}" ]; then
      DOCKER_GROUP="$(getent group "${DOCKER_GID}" | cut -d: -f1 || true)"
      if [ -z "${DOCKER_GROUP}" ]; then
        DOCKER_GROUP="dockerhost"
        addgroup --gid "${DOCKER_GID}" "${DOCKER_GROUP}" >/dev/null 2>&1 || true
      fi
      if [ -n "${DOCKER_GROUP}" ]; then
        adduser ea "${DOCKER_GROUP}" >/dev/null 2>&1 || true
      fi
    fi
  fi
  exec runuser -u ea -- "$@"
fi

exec "$@"
