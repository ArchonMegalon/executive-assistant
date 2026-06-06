#!/usr/bin/env bash
set -euo pipefail

EA_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-}"
if [[ -z "${PYTHON_BIN}" ]]; then
  if [[ -x "${EA_ROOT}/.venv/bin/python" ]]; then
    PYTHON_BIN="${EA_ROOT}/.venv/bin/python"
  else
    PYTHON_BIN="python3"
  fi
fi

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  cat <<'EOF'
Usage:
  bash scripts/property_release_gates.sh

Runs the focused PropertyQuarry release bundle:
  - property workspace redesign browser contracts
  - FlipLink packet privacy, publication, and webhook contracts
  - property workspace real-browser greenfield checks
  - property search run contracts
  - property market catalog contracts
  - property browser journey contracts
EOF
  exit 0
fi

cd "${EA_ROOT}"
PYTHONPATH=ea "${PYTHON_BIN}" scripts/check_docs_links.py
PYTHONPATH=ea "${PYTHON_BIN}" scripts/check_property_security_posture.py
PYTHONPATH=ea "${PYTHON_BIN}" scripts/check_property_repo_isolation.py
PYTHONPATH=ea "${PYTHON_BIN}" -m pytest -q \
  tests/test_fliplink_packet_privacy.py \
  tests/test_property_packet_publications.py \
  tests/test_fliplink_webhook_contracts.py \
  tests/test_property_missing_facts_ooda.py \
  tests/test_property_search_runs.py::test_property_search_run_surfaces_and_updates_missing_fact_research_tasks
PYTHONPATH=ea "${PYTHON_BIN}" -m pytest -q \
  tests/test_propertyquarry_workspace_redesign.py \
  tests/e2e/test_propertyquarry_greenfield_browser.py
PYTHONPATH=ea "${PYTHON_BIN}" -m pytest -q \
  tests/test_property_search_runs.py \
  tests/test_property_market_catalog.py \
  tests/test_product_browser_journeys.py -k 'properties_workspace_surface or propertyquarry_settings_hide_generic_google_sync_metrics'
