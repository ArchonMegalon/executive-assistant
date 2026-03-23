#!/bin/sh
set -eu

LEDGER_DIR="${EA_RESPONSES_PROVIDER_LEDGER_DIR:-/data/provider-ledger}"
ARTIFACTS_DIR="${EA_ARTIFACTS_DIR:-/tmp/ea_artifacts}"
TARGET_UID="${EA_RUN_AS_UID:-}"
TARGET_GID="${EA_RUN_AS_GID:-}"
TARGET_USER="ea"
TARGET_GROUP="ea"

if [ "$(id -u)" = "0" ]; then
  if [ -n "${TARGET_GID}" ]; then
    TARGET_GROUP="$(getent group "${TARGET_GID}" | cut -d: -f1 || true)"
    if [ -z "${TARGET_GROUP}" ]; then
      TARGET_GROUP="ea-runtime"
      addgroup --gid "${TARGET_GID}" "${TARGET_GROUP}" >/dev/null 2>&1 || true
    fi
  fi
  if [ -n "${TARGET_UID}" ]; then
    TARGET_USER="$(getent passwd "${TARGET_UID}" | cut -d: -f1 || true)"
    if [ -z "${TARGET_USER}" ]; then
      TARGET_USER="ea-runtime"
      if [ -n "${TARGET_GID}" ]; then
        adduser --system --uid "${TARGET_UID}" --gid "${TARGET_GID}" --home /home/ea --shell /bin/sh "${TARGET_USER}" >/dev/null 2>&1 || true
      else
        adduser --system --uid "${TARGET_UID}" --ingroup "${TARGET_GROUP}" --home /home/ea --shell /bin/sh "${TARGET_USER}" >/dev/null 2>&1 || true
      fi
    fi
  fi
  mkdir -p "${LEDGER_DIR}"
  mkdir -p "${ARTIFACTS_DIR}"
  chown -R "${TARGET_USER}:${TARGET_GROUP}" "${LEDGER_DIR}"
  chown -R "${TARGET_USER}:${TARGET_GROUP}" "${ARTIFACTS_DIR}"
  if [ -S /var/run/docker.sock ]; then
    DOCKER_GID="$(stat -c '%g' /var/run/docker.sock 2>/dev/null || true)"
    if [ -n "${DOCKER_GID}" ]; then
      DOCKER_GROUP="$(getent group "${DOCKER_GID}" | cut -d: -f1 || true)"
      if [ -z "${DOCKER_GROUP}" ]; then
        DOCKER_GROUP="dockerhost"
        addgroup --gid "${DOCKER_GID}" "${DOCKER_GROUP}" >/dev/null 2>&1 || true
      fi
      if [ -n "${DOCKER_GROUP}" ]; then
        adduser "${TARGET_USER}" "${DOCKER_GROUP}" >/dev/null 2>&1 || true
      fi
    fi
  fi
  exec runuser -u "${TARGET_USER}" -- "$@"
fi

exec "$@"
