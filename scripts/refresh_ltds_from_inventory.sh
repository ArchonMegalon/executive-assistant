#!/usr/bin/env bash
set -euo pipefail

EA_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 "${EA_ROOT}/scripts/refresh_ltds_from_inventory.py" "$@"
