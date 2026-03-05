#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-/docker/EA}"
export PYTHONPATH="$ROOT:$ROOT/ea"
export EA_SIM_SCENARIO_DIR="${EA_SIM_SCENARIO_DIR:-$ROOT/qa/scenarios}"
export EA_SIM_RUN_MODE="${EA_SIM_RUN_MODE:-contract_only}"

python3 -m app.sim_user.runner
