#!/usr/bin/env bash
set -euo pipefail

EA_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

HOST_PORT="${EA_HOST_PORT:-}"
if [[ -z "${HOST_PORT}" && -f "${EA_ROOT}/.env" ]]; then
  HOST_PORT="$(grep -E '^EA_HOST_PORT=' "${EA_ROOT}/.env" | tail -n1 | cut -d= -f2- || true)"
fi
HOST_PORT="${HOST_PORT:-8090}"
BASE="http://localhost:${HOST_PORT}"

curl -fsS "${BASE}/openapi.json" | python3 - <<'PY'
import json
import sys

doc = json.load(sys.stdin)
rows = []
for path, ops in (doc.get("paths") or {}).items():
    if not isinstance(ops, dict):
        continue
    for method in ops.keys():
        rows.append((str(method).upper(), str(path)))

for method, path in sorted(rows, key=lambda r: (r[1], r[0])):
    print(f"{method:7} {path}")
PY
