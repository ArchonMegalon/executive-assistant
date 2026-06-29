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
  bash scripts/smoke_help.sh

Run the script-help smoke contract by checking that key operator scripts return
a Usage header for their --help output.
EOF
  exit 0
fi

SCRIPTS=(
  scripts/deploy.sh
  scripts/db_bootstrap.sh
  scripts/db_status.sh
  scripts/db_size.sh
  scripts/db_retention.sh
  scripts/smoke_api.sh
  scripts/smoke_api_runtime.sh
  scripts/smoke_help.sh
  scripts/bootstrap_from_teable.sh
  scripts/smoke_postgres.sh
  scripts/test_postgres_contracts.sh
  scripts/hard_exit_gates.sh
  scripts/runtime_hard_exit_gates.sh
  scripts/verify_codexea_fleet_shim_parity.py
  scripts/verify_ltd_critical_entries.py
  scripts/verify_ltd_flagship_subset.py
  scripts/verify_ltd_provider_lanes.py
  scripts/materialize_poppy_draft_packet.py
  scripts/materialize_whole_project_gold_map.py
  scripts/verify_whole_project_gold_map.py
  scripts/materialize_whatsapp_web_action_processor_readiness.py
  scripts/verify_whatsapp_web_action_processor_readiness.py
  scripts/materialize_proactive_ooda_operator_status.py
  scripts/verify_proactive_ooda_operator_status.py
  scripts/materialize_proactive_ooda_gold_acceptance.py
  scripts/verify_proactive_ooda_gold_acceptance.py
  ea/scripts/verify_whatsapp_audiobook_live_delivery_receipt.py
  ea/scripts/verify_whatsapp_audiobook_operator_proof_bundle.py
  ea/scripts/verify_whatsapp_audiobook_public_share_playback.py
  scripts/list_endpoints.sh
  scripts/version_info.sh
  scripts/materialize_deploy_context.py
  scripts/materialize_release_manifest.py
  scripts/verify_memorial_deploy_readiness.py
  scripts/verify_deploy_context.py
  scripts/release_authority_probe.sh
  scripts/verify_release_authority_runtime.py
  scripts/export_openapi.sh
  scripts/diff_openapi.sh
  scripts/prune_openapi.sh
  scripts/operator_summary.sh
  scripts/support_bundle.sh
  scripts/archive_tasks.sh
  scripts/bootstrap_payfunnels_propertyquarry.py
  scripts/bootstrap_emailit_propertyquarry.py
  scripts/verify_release_assets.sh
)

for s in "${SCRIPTS[@]}"; do
  echo "== help smoke: ${s} =="
  case "${s}" in
    *.py)
      out="$(PYTHONPATH="${EA_ROOT}/ea:${EA_ROOT}:${PYTHONPATH:-}" "${PYTHON_BIN}" "${EA_ROOT}/${s}" --help)"
      ;;
    *)
      out="$(bash "${EA_ROOT}/${s}" --help)"
      ;;
  esac
  if [[ "${out}" != *"Usage:"* ]]; then
    echo "missing Usage header in ${s} --help output" >&2
    exit 21
  fi
done

echo "== help smoke: scripts/verify_release_authority_runtime.py --require-authoritative =="
out="$(PYTHONPATH="${EA_ROOT}/ea:${EA_ROOT}:${PYTHONPATH:-}" "${PYTHON_BIN}" "${EA_ROOT}/scripts/verify_release_authority_runtime.py" --help)"
if [[ "${out}" != *"Usage:"* ]]; then
  echo "missing Usage header in scripts/verify_release_authority_runtime.py --help output" >&2
  exit 21
fi

echo "help smoke complete"
