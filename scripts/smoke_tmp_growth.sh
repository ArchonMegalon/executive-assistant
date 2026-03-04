#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${EA_HEAVY_JOB_CMD:-}" ]]; then
  echo "Set EA_HEAVY_JOB_CMD to the command to execute."
  exit 2
fi

MAX_TMP_DELTA_MB="${MAX_TMP_DELTA_MB:-500}"

BEFORE="$(du -sm /tmp | awk '{print $1}')"
set +e
timeout 20m bash -lc "${EA_HEAVY_JOB_CMD}" >/dev/null 2>&1
RC=$?
set -e
AFTER="$(du -sm /tmp | awk '{print $1}')"

DELTA=$((AFTER - BEFORE))
echo "TMP delta: ${DELTA}MB (command rc=${RC})"

if [[ "$DELTA" -gt "$MAX_TMP_DELTA_MB" ]]; then
  echo "FAIL: temp-file leak suspected"
  exit 1
fi
echo "PASS"
