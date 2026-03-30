#!/usr/bin/env bash
set -euo pipefail

EA_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${EA_ROOT}"

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  cat <<'EOF'
Usage:
  bash scripts/operator_summary.sh

Print a compact operator command summary including deploy, smoke, readiness,
release, support, and documentation shortcuts plus current version metadata
and the current mirrored product-control pulse.
EOF
  exit 0
fi

print_product_control_summary() {
  python3 - <<'PY'
from __future__ import annotations

import json
from pathlib import Path

root = Path.cwd()
pulse_path = root / ".codex-design/product/WEEKLY_PRODUCT_PULSE.generated.json"
default_journey_path = Path("/docker/fleet/.codex-studio/published/JOURNEY_GATES.generated.json")


def load_json(path: Path) -> dict[str, object] | None:
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


pulse = load_json(pulse_path) if pulse_path.exists() else None
signals = dict((pulse or {}).get("supporting_signals") or {})
configured_journey = str(signals.get("journey_gate_source") or "").strip()
journey_path = (root / configured_journey).resolve() if configured_journey else default_journey_path
journey = load_json(journey_path) if journey_path.exists() else None
journey_summary = dict((journey or {}).get("summary") or {})
pulse_gate = dict((pulse or {}).get("journey_gate_health") or {})
route = dict(signals.get("provider_route_stewardship") or {})

journey_state = str(pulse_gate.get("state") or journey_summary.get("overall_state") or "missing").strip() or "missing"
journey_action = str(journey_summary.get("recommended_action") or pulse_gate.get("reason") or "No published journey action.").strip()

print(f"weekly pulse:      {pulse_path if pulse_path.exists() else 'missing'}")
print(f"pulse generated:   {str((pulse or {}).get('generated_at') or 'missing').strip() or 'missing'}")
print(f"active wave:       {str((pulse or {}).get('active_wave') or 'missing').strip() or 'missing'}")
print(f"wave status:       {str((pulse or {}).get('active_wave_status') or 'missing').strip() or 'missing'}")
print(f"launch readiness:  {str(signals.get('launch_readiness') or 'missing').strip() or 'missing'}")
print(f"journey gates:     {journey_path if journey_path.exists() else 'missing'}")
print(f"journey generated: {str((journey or {}).get('generated_at') or 'missing').strip() or 'missing'}")
print(f"journey gate:      {journey_state}")
print(f"journey action:    {journey_action}")
print(f"route review due:  {str(route.get('review_due') or 'not published').strip() or 'not published'}")
PY
}

echo "== Operator Summary =="
echo

echo "-- version --"
bash scripts/version_info.sh
echo

echo "-- key commands --"
echo "deploy:            make deploy"
echo "deploy (memory):   make deploy-memory"
echo "deploy + bootstrap: EA_BOOTSTRAP_DB=1 make deploy"
echo "bootstrap only:    make bootstrap"
echo "db status:         make db-status"
echo "db size:           make db-size"
echo "db retention:      make db-retention"
echo "smoke api:         make smoke-api"
echo "smoke postgres:    make smoke-postgres"
echo "smoke pg legacy:   make smoke-postgres-legacy"
echo "pg contracts:      make test-postgres-contracts"
echo "release smoke:     make release-smoke"
echo "ci gates:          make ci-gates"
echo "ci gates pg:       make ci-gates-postgres"
echo "ci gates pg leg:   make ci-gates-postgres-legacy"
echo "all local:         make all-local"
echo "verify assets:     make verify-release-assets"
echo "release docs:      make release-docs"
echo "release preflight: make release-preflight"
echo "operator help:     make operator-help"
echo "support bundle:    make support-bundle"
echo "tasks archive:     make tasks-archive"
echo "tasks archive dry: make tasks-archive-dry-run"
echo "tasks archive prn: make tasks-archive-prune"
echo "endpoints:         make endpoints"
echo "openapi export:    make openapi-export"
echo "openapi diff:      make openapi-diff"
echo "openapi prune:     make openapi-prune"
echo

echo "-- docs --"
echo "runbook:           RUNBOOK.md"
echo "architecture:      ARCHITECTURE_MAP.md"
echo "http examples:     HTTP_EXAMPLES.http"
echo "changelog:         CHANGELOG.md"
echo "env matrix:        ENVIRONMENT_MATRIX.md"
echo "release checklist: RELEASE_CHECKLIST.md"
echo

echo "-- product control --"
print_product_control_summary
echo

echo "-- queued task --"
if [[ -f TASKS_WORK_LOG.md ]]; then
  awk '/^## Queue/{flag=1;next}/^## In Progress/{flag=0}flag' TASKS_WORK_LOG.md | sed -n '1,8p'
else
  echo "local task log not present"
fi
