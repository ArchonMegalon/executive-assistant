#!/usr/bin/env bash
set -euo pipefail

EA_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${EA_ROOT}"

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
INCLUDE_QUEUE="${SUPPORT_INCLUDE_QUEUE:-1}"

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

  if [[ "${INCLUDE_QUEUE}" == "1" ]]; then
    echo "-- queued task snapshot --"
    awk '/^## Queue/{flag=1;next}/^## In Progress/{flag=0}flag' TASKS_WORK_LOG.md || true
  else
    echo "-- queued task snapshot --"
    echo "skipped (SUPPORT_INCLUDE_QUEUE=${INCLUDE_QUEUE})"
  fi
} > "${OUT_FILE}"

echo "support bundle written: ${OUT_FILE}"
