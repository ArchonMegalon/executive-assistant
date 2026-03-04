#!/usr/bin/env bash
set -euo pipefail

MAX_BROWSERS="${MAX_BROWSERS:-4}"
COUNT="$(pgrep -fa 'chrome|chromium|playwright|puppeteer' | wc -l || true)"

echo "Browser process count: $COUNT"
if [[ "$COUNT" -gt "$MAX_BROWSERS" ]]; then
  echo "FAIL: Too many browser workers"
  exit 1
fi
echo "PASS"
