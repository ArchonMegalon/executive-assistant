#!/usr/bin/env bash
set -euo pipefail

EA_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${EA_ROOT}"

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  cat <<'EOF'
Usage:
  bash scripts/operator_summary.sh

Print a compact operator command summary including deploy, smoke, readiness,
release, support, and documentation shortcuts plus current version metadata,
the current mirrored product-control pulse, and grounded help/support/operator
packet guidance plus codex lane governance from the local design mirror.
EOF
  exit 0
fi

print_product_control_summary() {
  python3 - <<'PY'
from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

root = Path.cwd()
pulse_path = root / ".codex-design/product/WEEKLY_PRODUCT_PULSE.generated.json"
default_journey_path = Path(os.environ.get("EA_FLEET_JOURNEY_GATES_PATH") or root / "ea/_completion/fleet/JOURNEY_GATES.generated.json")


def load_json(path: Path) -> dict[str, object] | None:
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def public_guide_projection() -> dict[str, str]:
    manifest_path = root / ".codex-design/product/PUBLIC_GUIDE_EXPORT_MANIFEST.yaml"
    if manifest_path.exists():
        generated_at = datetime.fromtimestamp(manifest_path.stat().st_mtime, tz=UTC).isoformat().replace("+00:00", "Z")
        return {
            "path": str(manifest_path),
            "generated_at": generated_at,
            "detail": "Manifest-backed freshness only; downstream published guide proof is not mirrored in this repo.",
        }
    return {
        "path": "missing",
        "generated_at": "missing",
        "detail": "No public-guide manifest is mirrored locally.",
    }


pulse = load_json(pulse_path) if pulse_path.exists() else None
signals = dict((pulse or {}).get("supporting_signals") or {})
configured_journey = str(signals.get("journey_gate_source") or "").strip()
journey_path = (root / configured_journey).resolve() if configured_journey else default_journey_path
journey = load_json(journey_path) if journey_path.exists() else None
journey_summary = dict((journey or {}).get("summary") or {})
journies = [dict(row) for row in list((journey or {}).get("journeys") or []) if isinstance(row, dict)]
pulse_gate = dict((pulse or {}).get("journey_gate_health") or {})
route = dict(signals.get("provider_route_stewardship") or {})
public_guide = public_guide_projection()
support_closures_waiting = sum(int(dict(row.get("signals") or {}).get("support_closure_waiting_count") or 0) for row in journies)
support_human_responses = sum(int(dict(row.get("signals") or {}).get("support_needs_human_response_count") or 0) for row in journies)

journey_state = str(pulse_gate.get("state") or journey_summary.get("overall_state") or "missing").strip() or "missing"
journey_action = str(journey_summary.get("recommended_action") or pulse_gate.get("reason") or "No published journey action.").strip()
support_fallout = "clear"
if support_closures_waiting or support_human_responses:
    parts = []
    if support_closures_waiting:
        parts.append(f"{support_closures_waiting} closures waiting")
    if support_human_responses:
        parts.append(f"{support_human_responses} human responses needed")
    support_fallout = " · ".join(parts)

print(f"weekly pulse:      {pulse_path if pulse_path.exists() else 'missing'}")
print(f"pulse generated:   {str((pulse or {}).get('generated_at') or 'missing').strip() or 'missing'}")
print(f"active wave:       {str((pulse or {}).get('active_wave') or 'missing').strip() or 'missing'}")
print(f"wave status:       {str((pulse or {}).get('active_wave_status') or 'missing').strip() or 'missing'}")
print(f"launch readiness:  {str(signals.get('launch_readiness') or 'missing').strip() or 'missing'}")
print(f"journey gates:     {journey_path if journey_path.exists() else 'missing'}")
print(f"journey generated: {str((journey or {}).get('generated_at') or 'missing').strip() or 'missing'}")
print(f"journey gate:      {journey_state}")
print(f"journey action:    {journey_action}")
print(f"support fallout:   {support_fallout}")
print(f"route review due:  {str(route.get('review_due') or 'not published').strip() or 'not published'}")
print(f"public guide:      {str(public_guide.get('path') or 'missing').strip() or 'missing'}")
print(f"guide updated:     {str(public_guide.get('generated_at') or 'missing').strip() or 'missing'}")
print(f"guide freshness:   {str(public_guide.get('detail') or 'No public-guide freshness is mirrored.').strip() or 'No public-guide freshness is mirrored.'}")
PY
}

print_grounding_summary() {
  python3 - <<'PY'
from __future__ import annotations

from pathlib import Path

import yaml

root = Path.cwd()
design_root = root / ".codex-design" / "product"


def load_yaml(path: Path) -> dict[str, object]:
    try:
        payload = yaml.safe_load(path.read_text())
    except Exception:
        return {}
    return dict(payload or {}) if isinstance(payload, dict) else {}


def compact(value: object) -> str:
    return " ".join(str(value or "").split()).strip() or "missing"


trust = load_yaml(design_root / "PUBLIC_TRUST_CONTENT.yaml")
release = load_yaml(design_root / "PUBLIC_RELEASE_EXPERIENCE.yaml")
scorecard = load_yaml(design_root / "PRODUCT_HEALTH_SCORECARD.yaml")

help_page = next(
    (dict(row) for row in list(trust.get("trust_pages") or []) if isinstance(row, dict) and str(row.get("id") or "").strip() == "help"),
    {},
)
support_scorecard = next(
    (dict(row) for row in list(scorecard.get("scorecards") or []) if isinstance(row, dict) and str(row.get("id") or "").strip() == "support_and_feedback_closure"),
    {},
)
first_action = next((dict(row) for row in list(help_page.get("actions") or []) if isinstance(row, dict)), {})
first_metric = next((dict(row) for row in list(support_scorecard.get("metrics") or []) if isinstance(row, dict)), {})
cadence = dict(scorecard.get("cadence") or {})

print(f"public help:       {compact(help_page.get('heading') or 'Get help without guessing')}")
print(f"help summary:      {compact(help_page.get('intro') or release.get('release_notes_summary'))}")
if first_action:
    print(f"help first action: {compact(first_action.get('label'))} -> {compact(first_action.get('href'))}")
print(f"support question:  {compact(support_scorecard.get('question'))}")
if first_metric:
    print(f"support target:    {compact(first_metric.get('name'))} target {compact(first_metric.get('target'))}")
print(f"operator cadence:  {compact(cadence.get('review') or 'weekly')}")
print(f"snapshot owner:    {compact(cadence.get('snapshot_owner') or 'product_governor')}")
PY
}

print_codex_governance_summary() {
  python3 - <<'PY'
from __future__ import annotations

from pathlib import Path

root = Path.cwd()


def compact(value: object) -> str:
    return " ".join(str(value or "").split()).strip() or "missing"


lane_summaries = {
    "easy": "Fast lane for cheap, low-stakes drafting and quick steering.",
    "hard coder": "Primary deep implementation and debugging lane for real code work.",
    "groundwork": "Gather evidence, prepare packets, and do cheap bounded prep before deeper execution.",
    "audit/jury": "Review, risk triage, and boundary checking before stronger claims.",
}

for label, summary in lane_summaries.items():
    print(f"{label}:           {compact(summary)}")
print("review cadence:  weekly / product_governor")
print("support/help:    Grounded help lane only; it must not become product canon or support-case truth.")
PY
}

print_memorial_status_summary() {
  python3 - <<'PY'
from __future__ import annotations

import json
from pathlib import Path

root = Path.cwd()
status_path = root / ".codex-design/product/MEMORIAL_OPERATOR_STATUS.generated.json"

def compact(value: object) -> str:
    return " ".join(str(value or "").split()).strip() or "missing"

def receipt_state(payload: dict[str, object], key: str) -> str:
    row = payload.get(key)
    if row is None:
        return "missing"
    if isinstance(row, dict):
        return compact(row.get("status"))
    return compact(row)

if not status_path.exists():
    print("memorial status:   missing")
    print("memorial action:   make materialize-memorial-operator-status")
    raise SystemExit(0)

payload = json.loads(status_path.read_text(encoding="utf-8"))
print(f"memorial status:   {compact(payload.get('current_label'))}")
print(f"local candidate:   {receipt_state(payload, 'local_release_candidate')}")
print(f"public voice:      {receipt_state(payload, 'public_voice_receipt')}")
print(f"public browser:    {receipt_state(payload, 'public_browser_receipt')}")
print(f"meaningful probe:  {receipt_state(payload, 'public_browser_meaningful_receipt')}")
print(f"room audio:        {receipt_state(payload, 'room_audio_receipt')}")
print(f"whole gold:        {receipt_state(payload, 'whole_project_gold')}")
PY
}

print_goal_posture_summary() {
  python3 - <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

root = Path.cwd()
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from scripts.materialize_continuous_improvement_goal_posture import build_goal_posture

def compact(value: object) -> str:
    return " ".join(str(value or "").split()).strip() or "missing"

receipt = build_goal_posture(root=root)
lenses = {str(lens.get("key") or ""): dict(lens) for lens in list(receipt.get("lenses") or []) if isinstance(lens, dict)}
deliver_components = {str(component.get("key") or ""): dict(component) for component in list(lenses.get("deliver", {}).get("components") or []) if isinstance(component, dict)}
print("north star:        dependable executive, conversation, and media operating system")
print(f"detect:            {compact(lenses.get('detect', {}).get('status'))} -> make verify-whole-project-signal-to-decision-receipt")
print(f"decide:            {compact(lenses.get('decide', {}).get('status'))} -> make verify-office-loop-goal-receipt")
print(
    "deliver:           "
    f"media {compact(deliver_components.get('promo_media', {}).get('status'))} / "
    f"speech {compact(deliver_components.get('manfred_speech', {}).get('status'))} / "
    f"tg {compact(deliver_components.get('telegram_audiobook', {}).get('status'))} / "
    f"wa {compact(deliver_components.get('whatsapp_audiobook', {}).get('status'))} -> "
    "make verify-active-media-ltd-goal-bundle / make verify-manfred-realtime-conversation-readiness"
)
print(f"recover:           {compact(lenses.get('recover', {}).get('status'))} -> make env-check-teable / make env-fresh-host-teable")
print(f"prove:             {compact(lenses.get('prove', {}).get('status'))} -> make verify-executive-assistant-quality-readiness")
print(f"detect next:       {compact(lenses.get('detect', {}).get('next_action'))}")
print(f"decide next:       {compact(lenses.get('decide', {}).get('next_action'))}")
print(f"deliver next:      {compact(lenses.get('deliver', {}).get('next_action'))}")
print(f"recover next:      {compact(lenses.get('recover', {}).get('next_action'))}")
print(f"prove next:        {compact(lenses.get('prove', {}).get('next_action'))}")
PY
}

echo "== Operator Summary =="
echo

echo "-- version --"
bash scripts/version_info.sh
echo

echo "-- key commands --"
echo "deploy EA:         make deploy-ea-prod"
echo "deploy property:   make deploy-property"
echo "deploy (memory):   make deploy-memory"
echo "deploy + bootstrap: EA_BOOTSTRAP_DB=1 make deploy-bootstrap"
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
echo "runtime hard gate: make runtime-hard-exit-gates"
echo "full hard gates:   make hard-exit-gates"
echo "ltd gates:         make ltd-release-gates"
echo "ltd critical:      make verify-ltd-critical-entries"
echo "ltd flagship:      make verify-ltd-flagship-subset"
echo "all local:         make all-local"
echo "verify assets:     make verify-release-assets"
echo "release auth:      make verify-release-authority"
echo "flagship ready:    make verify-flagship-release-readiness"
echo "whole gold map:    make verify-whole-project-gold-map"
echo "goal posture:      make verify-continuous-improvement-goal-posture"
echo "office loop:       make verify-office-loop-goal-receipt"
echo "ea quality:        make verify-executive-assistant-quality-readiness"
echo "signal packet:     make verify-whole-project-signal-to-decision-receipt"
echo "scope audit:       make verify-whole-project-scope-gap-audit"
echo "active media:      make verify-active-media-ltd-goal-bundle"
echo "manfred realtime:  make verify-manfred-realtime-conversation-readiness"
echo "tg audio ready:    make verify-telegram-audiobook-live-readiness"
echo "tg audiobook live: make verify-telegram-audiobook-live-delivery-receipt"
echo "wa audio local:    make verify-whatsapp-audiobook-local-intake-proof"
echo "wa action ready:   make verify-whatsapp-web-action-processor-readiness"
echo "wa audio bundle:   make verify-whatsapp-audiobook-operator-proof-bundle"
echo "wa audiobook live: make verify-whatsapp-audiobook-live-delivery-receipt"
echo "wa share play:     make verify-whatsapp-audiobook-public-share-playback"
echo "memorial status:   make materialize-memorial-operator-status"
echo "phrase bank:       make materialize-memorial-phrase-bank"
echo "room gold clean:   make materialize-memorial-room-audio-gold-clean"
echo "tg video proof:    make materialize-telegram-video-delivery-receipts"
echo "tg live verify:    make verify-telegram-video-delivery-live-receipt"
echo "release docs:      make release-docs"
echo "release preflight: make release-preflight"
echo "operator help:     make operator-help"
echo "provider ready:    make provider-readiness"
echo "overlay vision:    make overlay-vision-check"
echo "overlay vision+dl: make overlay-vision-pull"
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

echo "-- goal posture --"
print_goal_posture_summary
echo

echo "-- product control --"
print_product_control_summary
echo

echo "-- grounded packets --"
print_grounding_summary
echo

echo "-- codex governance --"
print_codex_governance_summary
echo

echo "-- memorial status --"
print_memorial_status_summary
echo

echo "-- queued task --"
if [[ -f TASKS_WORK_LOG.md ]]; then
  awk '/^## Queue/{flag=1;next}/^## In Progress/{flag=0}flag' TASKS_WORK_LOG.md | sed -n '1,8p'
else
  echo "local task log not present"
fi
