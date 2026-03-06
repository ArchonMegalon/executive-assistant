#!/usr/bin/env bash
set -euo pipefail

EA_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${EA_ROOT}"

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  cat <<'EOF'
Usage:
  bash scripts/support_bundle.sh

Environment:
  SUPPORT_BUNDLE_PREFIX=<name>          Bundle filename prefix (default: support_bundle)
  SUPPORT_BUNDLE_TIMESTAMP_FMT=<fmt>    UTC timestamp format for filename (date format)
  SUPPORT_LOG_TAIL_LINES=<n>            Number of log lines to capture (default: 300)
  SUPPORT_INCLUDE_API=0|1               Include ea-api logs (default: 1)
  SUPPORT_INCLUDE_DB=0|1                Include ea-db logs (default: 1)
  SUPPORT_INCLUDE_DB_VOLUME=0|1         Include ea-db mount/volume attribution (default: 1)
  SUPPORT_INCLUDE_DB_SIZE=0|1           Include DB size snapshot via db_size.sh (default: 1)
  SUPPORT_DB_SIZE_LIMIT=<n>             Top table count for DB size snapshot (default: 10)
  SUPPORT_INCLUDE_QUEUE=0|1             Include queued task snapshot (default: 1)
EOF
  exit 0
fi

if docker compose version >/dev/null 2>&1; then
  DC=(docker compose)
else
  DC=(docker-compose)
fi

OUT_DIR="${EA_ROOT}/artifacts"
mkdir -p "${OUT_DIR}"
STAMP_FMT="${SUPPORT_BUNDLE_TIMESTAMP_FMT:-%Y%m%dT%H%M%SZ}"
STAMP="$(date -u +"${STAMP_FMT}")"
PREFIX="${SUPPORT_BUNDLE_PREFIX:-support_bundle}"
OUT_FILE="${OUT_DIR}/${PREFIX}_${STAMP}.txt"
TAIL_LINES="${SUPPORT_LOG_TAIL_LINES:-300}"
INCLUDE_DB="${SUPPORT_INCLUDE_DB:-1}"
INCLUDE_API="${SUPPORT_INCLUDE_API:-1}"
INCLUDE_DB_VOLUME="${SUPPORT_INCLUDE_DB_VOLUME:-1}"
INCLUDE_DB_SIZE="${SUPPORT_INCLUDE_DB_SIZE:-1}"
DB_SIZE_LIMIT="${SUPPORT_DB_SIZE_LIMIT:-10}"
INCLUDE_QUEUE="${SUPPORT_INCLUDE_QUEUE:-1}"
DB_CONTAINER="${EA_DB_CONTAINER:-ea-db}"

redact() {
  sed -E \
    -e 's#(postgresql://[^:]+:)[^@]+@#\1REDACTED@#g' \
    -e 's#([Pp][Aa][Ss][Ss][Ww][Oo][Rr][Dd][^=:\n]{0,40}[=:])[^\n ]+#\1REDACTED#g' \
    -e 's#([Pp][Aa][Ss][Ss][Ww][Dd][^=:\n]{0,40}[=:])[^\n ]+#\1REDACTED#g' \
    -e 's#([Tt][Oo][Kk][Ee][Nn][^=:\n]{0,40}[=:])[^\n ]+#\1REDACTED#g' \
    -e 's#([Ss][Ee][Cc][Rr][Ee][Tt][^=:\n]{0,40}[=:])[^\n ]+#\1REDACTED#g' \
    -e 's#([Aa][Pp][Ii][_-]?[Kk][Ee][Yy][^=:\n]{0,40}[=:])[^\n ]+#\1REDACTED#g'
}

{
  echo "== Support Bundle =="
  echo "generated_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo

  echo "-- version info --"
  bash scripts/version_info.sh || true
  echo

  echo "-- compose ps --"
  "${DC[@]}" ps || true
  echo

  if [[ "${INCLUDE_API}" == "1" ]]; then
    echo "-- ea-api logs (tail ${TAIL_LINES}) --"
    "${DC[@]}" logs --tail "${TAIL_LINES}" ea-api 2>&1 | redact || true
    echo
  else
    echo "-- ea-api logs --"
    echo "skipped (SUPPORT_INCLUDE_API=${INCLUDE_API})"
    echo
  fi

  if [[ "${INCLUDE_DB}" == "1" ]]; then
    echo "-- ea-db logs (tail ${TAIL_LINES}) --"
    "${DC[@]}" logs --tail "${TAIL_LINES}" ea-db 2>&1 | redact || true
    echo
  else
    echo "-- ea-db logs --"
    echo "skipped (SUPPORT_INCLUDE_DB=${INCLUDE_DB})"
    echo
  fi

  if [[ "${INCLUDE_DB_VOLUME}" == "1" ]]; then
    echo "-- ea-db volume attribution --"
    echo "expected_runtime_volume=ea_pgdata"
    echo "expected_container_mount=/var/lib/postgresql/data"
    echo "compose_declared_volumes=$("${DC[@]}" config --volumes 2>/dev/null | tr '\n' ' ' | sed 's/[[:space:]]\+/ /g' | sed 's/^ *//; s/ *$//')"
    if docker inspect "${DB_CONTAINER}" >/dev/null 2>&1; then
      docker inspect "${DB_CONTAINER}" --format '{{range .Mounts}}{{println .Name "|" .Source "|" .Destination "|" .Type}}{{end}}' 2>/dev/null | redact || true
    else
      echo "ea-db mount inspection unavailable"
    fi
    echo
  else
    echo "-- ea-db volume attribution --"
    echo "skipped (SUPPORT_INCLUDE_DB_VOLUME=${INCLUDE_DB_VOLUME})"
    echo
  fi

  if [[ "${INCLUDE_DB_SIZE}" == "1" ]]; then
    echo "-- db size snapshot --"
    EA_DB_SIZE_LIMIT="${DB_SIZE_LIMIT}" bash scripts/db_size.sh 2>&1 | redact || true
    echo
  else
    echo "-- db size snapshot --"
    echo "skipped (SUPPORT_INCLUDE_DB_SIZE=${INCLUDE_DB_SIZE})"
    echo
  fi

  if [[ "${INCLUDE_QUEUE}" == "1" ]]; then
    echo "-- queued task snapshot --"
    if [[ -f TASKS_WORK_LOG.md ]]; then
      awk '/^## Queue/{flag=1;next}/^## In Progress/{flag=0}flag' TASKS_WORK_LOG.md || true
    else
      echo "local task log not present"
    fi
  else
    echo "-- queued task snapshot --"
    echo "skipped (SUPPORT_INCLUDE_QUEUE=${INCLUDE_QUEUE})"
  fi
} > "${OUT_FILE}"

echo "support bundle written: ${OUT_FILE}"
