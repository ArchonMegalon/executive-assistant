#!/usr/bin/env bash
set -euo pipefail

EA_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${EA_ROOT}"
export EA_ROOT

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

root = Path(os.environ["EA_ROOT"])
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

import os
from pathlib import Path

import yaml

root = Path(os.environ["EA_ROOT"])
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

import os
from pathlib import Path

root = Path(os.environ["EA_ROOT"])


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
import os
from pathlib import Path

root = Path(os.environ["EA_ROOT"])
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

def memorial_next_command(payload: dict[str, object]) -> str:
    explicit = compact(payload.get("memorial_public_gold_next_command"))
    if explicit != "missing":
        return explicit
    action = compact(payload.get("memorial_public_gold_next_action"))
    if action == "clear_release_authority_for_memorial_deploy":
        return "python3 scripts/verify_release_authority.py --pretty"
    if action == "deploy_ea_memorial":
        return "make deploy-ea-memorial"
    if action in {
        "allow_anonymous_public_memorial_origin_access",
        "republish_public_memorial_bundle_or_fix_slug",
        "inspect_public_memorial_origin_http_failure",
    }:
        return "GET /memorials/manfred and /memorials/manfred.json on the configured public origin"
    if action == "refresh_memorial_public_auto_receipts_clean":
        return "scripts/materialize_memorial_public_auto_receipts_clean.py"
    return "missing"

def source_dirty_groups(payload: dict[str, object]) -> list[str]:
    summary = dict(payload.get("source_dirty_summary") or {})
    categories = [dict(item) for item in list(summary.get("categories") or []) if isinstance(item, dict)]
    lines: list[str] = []
    for row in categories[:5]:
        category = compact(row.get("category"))
        count = int(row.get("visible_count") or 0)
        samples = [str(item).strip() for item in list(row.get("sample_files") or []) if str(item).strip()]
        sample_text = ", ".join(samples[:2]) if samples else "no samples"
        if len(samples) > 2:
            sample_text += ", ..."
        lines.append(f"{category}:{count} [{sample_text}]")
    omitted = int(summary.get("omitted_count") or payload.get("source_dirty_omitted_count") or 0)
    if omitted:
        lines.append(f"omitted:{omitted} [run git status --short for the full list]")
    return lines

def room_missing_inputs(payload: dict[str, object], *, limit: int = 10) -> str:
    detail = dict(payload.get("room_audio_receipt_detail") or {})
    hints = [dict(item) for item in list(detail.get("missing_input_hints") or []) if isinstance(item, dict)]
    labels: list[str] = []
    for hint in hints[:limit]:
        kind = compact(hint.get("kind"))
        name = compact(hint.get("name"))
        if kind == "missing" or name == "missing":
            continue
        labels.append(f"{kind}:{name}")
    if len(hints) > limit:
        labels.append(f"more:{len(hints) - limit}")
    return "; ".join(labels) if labels else "none"

def room_packet_state(payload: dict[str, object]) -> str:
    packet = dict(payload.get("room_audio_attestation_packet") or {})
    status = compact(packet.get("status"))
    command = compact(packet.get("operator_command"))
    if command == "missing":
        command = "make materialize-memorial-room-audio-gold-clean"
    return f"{status} -> {command}"

def room_command_template(payload: dict[str, object]) -> str:
    packet = dict(payload.get("room_audio_attestation_packet") or {})
    return compact(packet.get("receipt_command_template"))

def blocker_commands(payload: dict[str, object], *, limit: int = 8) -> str:
    summary = dict(payload.get("memorial_public_gold_blocker_summary") or {})
    commands = [str(item).strip() for item in list(summary.get("blocked_commands") or []) if str(item).strip()]
    if not commands:
        components = [dict(item) for item in list(summary.get("blocked_components") or []) if isinstance(item, dict)]
        commands = [str(item.get("next_command") or "").strip() for item in components if str(item.get("next_command") or "").strip()]
    deduped: list[str] = []
    for command in commands:
        if command not in deduped:
            deduped.append(command)
    if len(deduped) > limit:
        return " | ".join(deduped[:limit]) + f" | more:{len(deduped) - limit}"
    return " | ".join(deduped) if deduped else "none"

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
print(f"public runtime:    {receipt_state(payload, 'public_runtime_mode')}")
print(f"public access:     {receipt_state(payload, 'public_origin_access')}")
print(f"surface contract:  {receipt_state(payload, 'memorial_surface_contract')}")
print(f"room audio:        {receipt_state(payload, 'room_audio_receipt')}")
print(f"room packet:       {room_packet_state(payload)}")
print(f"room command:      {room_command_template(payload)}")
print(f"room missing:      {room_missing_inputs(payload)}")
print(f"whole gold:        {receipt_state(payload, 'whole_project_gold')}")
summary = dict(payload.get("source_dirty_summary") or {})
source_dirty_line = compact("; ".join(source_dirty_groups(payload)) or "none")
print(f"source groups:     {source_dirty_line}")
print("source categories: scripts/inspect_source_dirty_groups.py --list-categories")
print(f"source hint:       {compact(summary.get('operator_hint'))}")
print(f"next action:       {compact(payload.get('memorial_public_gold_next_action'))}")
print(f"next command:      {memorial_next_command(payload)}")
print(f"blocker commands: {blocker_commands(payload)}")
PY
}

print_goal_posture_summary() {
  python3 - <<'PY'
from __future__ import annotations

import os
import sys
from pathlib import Path

root = Path(os.environ["EA_ROOT"])
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

print_release_authority_summary() {
  python3 - <<'PY'
from __future__ import annotations

import json
import os
from pathlib import Path

root = Path(os.environ["EA_ROOT"])
status_path = root / ".codex-studio/published/release_authority_status.generated.json"
manifest_path = root / ".codex-studio/published/release_manifest.generated.json"
project_modes_path = root / ".codex-design/product/PROJECT_MODES.generated.json"

def compact(value: object) -> str:
    return " ".join(str(value or "").split()).strip() or "missing"

def load_json(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload or {}) if isinstance(payload, dict) else {}

manifest = load_json(manifest_path)
project_modes = load_json(project_modes_path)
status = load_json(status_path)
if status:
    issues = [str(item).strip() for item in list(status.get("issues") or []) if str(item).strip()]
    deployment_id = compact(status.get("deployment_id"))
    deployment_source = compact(status.get("deployment_id_source")).replace("_", " ")
    origin = compact(status.get("public_origin"))
    origin_source = compact(status.get("public_origin_source")).replace("_", " ")
    deploy_context_generated_at = compact(status.get("deploy_context_generated_at"))
    deploy_context_branch = compact(status.get("deploy_context_branch"))
    deploy_context_tracking_branch = compact(status.get("deploy_context_tracking_branch"))
    deploy_context_commit_sha = compact(status.get("deploy_context_commit_sha"))
    source_dirty = bool(status.get("source_worktree_dirty", status.get("dirty_worktree")))
    source_dirty_count = int(status.get("source_dirty_count") or 0)
    source_dirty_files = [str(item).strip() for item in list(status.get("source_dirty_files") or []) if str(item).strip()]
    source_dirty_preview = ", ".join(source_dirty_files[:3]) if source_dirty_files else "none"
    deploy_context_gate = dict(status.get("deploy_context_gate") or {})
    deploy_context_gate_status = compact(deploy_context_gate.get("status"))
    deploy_context_gate_issues = [
        str(item).strip() for item in list(deploy_context_gate.get("issues") or []) if str(item).strip()
    ]
    if len(source_dirty_files) > 3:
        source_dirty_preview += ", ..."
    print(f"release posture:   {compact(status.get('authority_posture'))}")
    print(f"release issues:    {compact(', '.join(issues) if issues else 'none')}")
    print(f"release next:      {compact(status.get('next_action'))}")
    print(f"deployment id:     {deployment_id} ({deployment_source})")
    print(f"public origin:     {origin} ({origin_source})")
    print(f"deploy ctx at:     {deploy_context_generated_at}")
    print(f"deploy ctx ref:    {deploy_context_branch}@{deploy_context_tracking_branch}")
    print(f"deploy ctx commit: {deploy_context_commit_sha[:12] if deploy_context_commit_sha != 'missing' else 'missing'}")
    print(f"deploy ctx gate:   {deploy_context_gate_status}")
    print(f"deploy ctx issues: {compact(', '.join(deploy_context_gate_issues) if deploy_context_gate_issues else 'none')}")
    print(f"source worktree:   {'dirty' if source_dirty else 'clean'}")
    print(f"source dirty:      {source_dirty_count} -> {source_dirty_preview}")
    raise SystemExit(0)

if not manifest:
    print("release posture:   missing_manifest")
    print("release issues:    release_manifest_missing")
    print("release action:    materialize the runtime release manifest before trusting shipping claims")
    raise SystemExit(0)

from scripts.verify_release_authority import validate_release_authority, _derive_authority_posture

issues = validate_release_authority(release_manifest=manifest, project_modes=project_modes)
posture = _derive_authority_posture(issues)
deployment_id = compact(manifest.get("deployment_id"))
deployment_source = compact(manifest.get("deployment_id_source")).replace("_", " ")
origin = compact(manifest.get("public_origin"))
origin_source = compact(manifest.get("public_origin_source")).replace("_", " ")
deploy_context_generated_at = compact(manifest.get("deploy_context_generated_at"))
deploy_context_branch = compact(manifest.get("deploy_context_branch"))
deploy_context_tracking_branch = compact(manifest.get("deploy_context_tracking_branch"))
deploy_context_commit_sha = compact(manifest.get("deploy_context_commit_sha"))
source_dirty = bool(manifest.get("source_worktree_dirty", manifest.get("dirty_worktree")))
source_dirty_count = int(manifest.get("source_dirty_count") or 0)
source_dirty_files = [str(item).strip() for item in list(manifest.get("source_dirty_files") or []) if str(item).strip()]
source_dirty_preview = ", ".join(source_dirty_files[:3]) if source_dirty_files else "none"
if len(source_dirty_files) > 3:
    source_dirty_preview += ", ..."

print(f"release posture:   {posture}")
print(f"release issues:    {compact(', '.join(issues) if issues else 'none')}")
print(f"deployment id:     {deployment_id} ({deployment_source})")
print(f"public origin:     {origin} ({origin_source})")
print(f"deploy ctx at:     {deploy_context_generated_at}")
print(f"deploy ctx ref:    {deploy_context_branch}@{deploy_context_tracking_branch}")
print(f"deploy ctx commit: {deploy_context_commit_sha[:12] if deploy_context_commit_sha != 'missing' else 'missing'}")
print(f"source worktree:   {'dirty' if source_dirty else 'clean'}")
print(f"source dirty:      {source_dirty_count} -> {source_dirty_preview}")
PY
}

print_runtime_supply_chain_summary() {
  python3 - <<'PY'
from __future__ import annotations

def compact(value: object) -> str:
    return " ".join(str(value or "").split()).strip() or "missing"

try:
    from scripts.verify_runtime_supply_chain import verify
    payload = dict(verify() or {})
except Exception as exc:
    payload = {
        "contract_name": "ea.runtime_supply_chain.v1",
        "status": "error",
        "issues": ["runtime_supply_chain_verifier_error"],
        "error": str(exc),
        "checked": {},
    }

issues = [str(item).strip() for item in list(payload.get("issues") or []) if str(item).strip()]
checked = dict(payload.get("checked") or {})
dockerfiles = ", ".join(str(item) for item in list(checked.get("dockerfiles") or [])[:4]) or "missing"
compose_services = ", ".join(str(item) for item in list(checked.get("compose_services") or [])[:8]) or "missing"
compose_images = dict(checked.get("compose_images") or {})
compose_images_text = ", ".join(
    f"{key}={value}" for key, value in sorted(compose_images.items()) if str(key).strip() and str(value).strip()
) or "missing"

print(f"supply status:     {compact(payload.get('status') or 'fail')}")
print(f"supply issues:     {compact(', '.join(issues) if issues else 'none')}")
print(f"requirements txt:  {compact(checked.get('requirements_txt'))}")
print(f"requirements lock: {compact(checked.get('requirements_lock'))}")
print(f"dockerfiles:       {dockerfiles}")
print(f"compose services:  {compose_services}")
print(f"compose images:    {compose_images_text}")
PY
}

print_codexea_runtime_summary() {
  python3 - <<'PY'
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

root = Path(os.environ["EA_ROOT"])
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from scripts.verify_codexea_fleet_shim_parity import verify as verify_codexea_fleet_shim_parity


def compact(value: object) -> str:
    return " ".join(str(value or "").split()).strip() or "missing"


def codexea_status_command() -> list[str]:
    explicit = compact(os.environ.get("CODEXEA_STATUS_COMMAND"))
    if explicit != "missing":
        return explicit.split()
    launcher = compact(os.environ.get("CODEXEA_LAUNCHER") or shutil.which("codexea"))
    if launcher != "missing":
        return [launcher, "status"]
    return ["codexea", "status"]

def provider_ready(row: dict[str, object]) -> bool:
    state = str(row.get("state") or "").strip().lower()
    if state == "ready":
        return True
    slots = [dict(item) for item in list(row.get("slots") or []) if isinstance(item, dict)]
    return any(str(slot.get("state") or "").strip().lower() == "ready" for slot in slots)

def provider_ready_from_payload(payload: dict[str, object], provider_key: str) -> bool:
    providers = dict((payload.get("provider_health") or {}).get("providers") or {})
    provider_row = dict(providers.get(provider_key) or {})
    if provider_row and provider_ready(provider_row):
        return True
    provider_rows = [
        dict(item)
        for item in list(payload.get("providers_summary") or [])
        if isinstance(item, dict) and str(item.get("provider_key") or "").strip() == provider_key
    ]
    return any(str(row.get("state") or "").strip().lower() == "ready" for row in provider_rows)

def derive_fast_lane_route(payload: dict[str, object]) -> dict[str, str]:
    route = dict(payload.get("fast_lane_route") or {})
    configured = [str(item).strip() for item in list(route.get("configured_order") or []) if str(item).strip()]
    effective = [str(item).strip() for item in list(route.get("effective_order") or []) if str(item).strip()]
    posture = str(route.get("posture") or "").strip()
    reason = str(route.get("reason") or "").strip()
    if configured and effective and posture:
        return {
            "posture": compact(posture),
            "reason": compact(reason or "configured_order"),
            "effective_order": compact(", ".join(effective)),
        }
    configured = ["onemin", "magixai", "gemini_vortex"]
    pressure = compact(((payload.get("onemin_aggregate") or {}).get("attempt_throttle_pressure_15m"))).lower()
    effective = list(configured)
    if pressure in {"medium", "high"}:
        preferred: list[str] = []
        if provider_ready_from_payload(payload, "gemini_vortex"):
            preferred.append("gemini_vortex")
        if provider_ready_from_payload(payload, "magixai"):
            preferred.append("magixai")
        if preferred:
            merged: list[str] = []
            for item in [*preferred, *configured]:
                if item not in merged:
                    merged.append(item)
            effective = merged
    posture = "pressure_spillover" if effective != configured else "configured_order"
    reason = f"onemin_pressure_{pressure}" if posture == "pressure_spillover" and pressure != "missing" else "configured_order"
    return {
        "posture": compact(posture),
        "reason": compact(reason),
        "effective_order": compact(", ".join(effective)),
    }


parity = dict(verify_codexea_fleet_shim_parity() or {})
issues = [str(item).strip() for item in list(parity.get("issues") or []) if str(item).strip()]
details = dict(parity.get("details") or {})
shared_defaults = dict(details.get("shared_defaults") or {})
connect_timeout = dict(shared_defaults.get("CODEXEA_STATUS_CONNECT_TIMEOUT_SECONDS") or {})
status_timeout = dict(shared_defaults.get("CODEXEA_STATUS_MAX_TIME_SECONDS") or {})
startup_niceness = dict(details.get("startup_niceness_default") or {})

status_command = codexea_status_command()
status_timeout_text = compact(status_timeout.get("fleet") or "30")
try:
    status_timeout_seconds = max(int(status_timeout_text) + 5, 10)
except ValueError:
    status_timeout_seconds = 35

status_summary = {
    "status": "missing",
    "issues": ["codexea_status_unavailable"],
    "throttle_pressure": "missing",
    "p95_latency_ms": "missing",
    "max_latency_ms": "missing",
    "peak_parallel_total": "missing",
    "peak_parallel_same_proxy": "missing",
    "peak_parallel_same_account": "missing",
    "busiest_proxy": "missing",
}

try:
    completed = subprocess.run(
        status_command,
        cwd=root,
        capture_output=True,
        text=True,
        timeout=status_timeout_seconds,
        check=False,
    )
except subprocess.TimeoutExpired:
    status_summary["status"] = "timeout"
    status_summary["issues"] = ["codexea_status_timeout"]
else:
    if completed.returncode == 0:
        try:
            payload = json.loads(completed.stdout)
        except Exception:
            status_summary["status"] = "parse_error"
            status_summary["issues"] = ["codexea_status_parse_error"]
        else:
            fast_lane_route = derive_fast_lane_route(payload)
            telemetry = dict(payload.get("onemin_attempt_telemetry") or {})
            selected = dict(telemetry.get("selected_window") or telemetry.get("15m") or telemetry.get("1h") or {})
            busiest_proxy_row = next(
                (
                    dict(row)
                    for row in list(selected.get("busiest_proxy_services") or [])
                    if isinstance(row, dict)
                ),
                {},
            )
            status_summary = {
                "status": "pass",
                "issues": [],
                "throttle_pressure": compact(selected.get("throttle_pressure")),
                "p95_latency_ms": compact(selected.get("p95_latency_ms")),
                "max_latency_ms": compact(selected.get("max_latency_ms")),
                "peak_parallel_total": compact(selected.get("peak_parallel_total")),
                "peak_parallel_same_proxy": compact(selected.get("peak_parallel_same_proxy")),
                "peak_parallel_same_account": compact(selected.get("peak_parallel_same_account")),
                "busiest_proxy": compact(busiest_proxy_row.get("proxy_service")),
                "fast_lane_posture": compact(fast_lane_route.get("posture")),
                "fast_lane_reason": compact(fast_lane_route.get("reason")),
                "fast_lane_effective_order": compact(fast_lane_route.get("effective_order")),
            }
    else:
        status_summary["status"] = f"exit_{completed.returncode}"
        stderr_text = compact(completed.stderr)
        status_summary["issues"] = [stderr_text if stderr_text != "missing" else "codexea_status_failed"]

print(f"launcher parity:   {compact(parity.get('status') or 'fail')}")
print(f"parity issues:     {compact(', '.join(issues) if issues else 'none')}")
print(
    "launcher defaults: "
    f"connect {compact(connect_timeout.get('fleet'))}s / "
    f"status {compact(status_timeout.get('fleet'))}s / "
    f"nice {compact(startup_niceness.get('fleet'))}"
)
print(f"status command:    {' '.join(status_command)}")
print(f"status posture:    {compact(status_summary.get('status'))}")
print(f"status issues:     {compact(', '.join(status_summary.get('issues') or []) if status_summary.get('issues') else 'none')}")
print(f"throttle pressure: {compact(status_summary.get('throttle_pressure'))}")
print(
    "parallel pressure: "
    f"total {compact(status_summary.get('peak_parallel_total'))} / "
    f"proxy {compact(status_summary.get('peak_parallel_same_proxy'))} / "
    f"account {compact(status_summary.get('peak_parallel_same_account'))}"
)
print(
    "latency envelope:  "
    f"p95 {compact(status_summary.get('p95_latency_ms'))} ms / "
    f"max {compact(status_summary.get('max_latency_ms'))} ms"
)
print(
    "fast lane route:   "
    f"{compact(status_summary.get('fast_lane_posture'))}"
    f" | reason {compact(status_summary.get('fast_lane_reason'))}"
    f" | effective {compact(status_summary.get('fast_lane_effective_order'))}"
)
print(f"busiest proxy:     {compact(status_summary.get('busiest_proxy'))}")
print("codexea next:      make verify-codexea-e2e-exit-gate")
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
echo "codexea parity:    make verify-codexea-fleet-shim-parity"
echo "codexea e2e:       make verify-codexea-e2e-exit-gate"
echo "ltd gates:         make ltd-release-gates"
echo "ltd critical:      make verify-ltd-critical-entries"
echo "ltd flagship:      make verify-ltd-flagship-subset"
echo "all local:         make all-local"
echo "release manifest:  make materialize-release-manifest"
echo "release bundle:    make materialize-release-assets"
echo "verify assets:     make verify-release-assets"
echo "runtime supply:    make verify-runtime-supply-chain"
echo "release auth:      make verify-release-authority"
echo "release runtime:   make verify-release-authority-runtime"
echo "release ready:     make verify-release-authority-runtime-authoritative"
echo "deploy context:    make materialize-deploy-context"
echo "deploy verify:     make verify-deploy-context"
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
echo "wa pairing:        make probe-whatsapp-pairing"
echo "wa pairing tg:     make send-whatsapp-pairing-telegram"
echo "wa audio bundle:   make verify-whatsapp-audiobook-operator-proof-bundle"
echo "wa audiobook live: make verify-whatsapp-audiobook-live-delivery-receipt"
echo "wa share play:     make verify-whatsapp-audiobook-public-share-playback"
echo "teable recovery:   make probe-teable-recovery"
echo "memorial status:   make materialize-memorial-operator-status"
echo "source groups:     make inspect-source-dirty-groups"
echo "source verify:     make verify-source-dirty-groups"
echo "source categories: scripts/inspect_source_dirty_groups.py --list-categories"
echo "memorial ready:    make verify-memorial-deploy-readiness"
echo "memorial runtime:  make verify-memorial-runtime-overlay"
echo "memorial surface:  make verify-project-mode-runtime-memorial"
echo "phrase bank:       make materialize-memorial-phrase-bank"
echo "room gold clean:   make materialize-memorial-room-audio-gold-clean"
echo "tg video proof:    make materialize-telegram-video-delivery-receipts"
echo "tg live verify:    make verify-telegram-video-delivery-live-receipt"
echo "release docs:      make release-docs"
echo "release preflight: make release-preflight"
echo "deploy memorial:   make deploy-ea-memorial"
echo "operator help:     make operator-help"
echo "provider ready:    make provider-readiness"
echo "overlay vision:    make overlay-vision-check"
echo "overlay vision+dl: make overlay-vision-pull"
echo "support bundle:    make support-bundle"
echo "tasks archive:     make tasks-archive"
echo "tasks archive dry: make tasks-archive-dry-run"
echo "tasks archive prn: make tasks-archive-prune"
echo "endpoints:         make endpoints"
echo "release probe:     make release-authority-probe"
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
echo "hosted CI:         intentionally absent; use local gate bundles below"
echo

echo "-- goal posture --"
print_goal_posture_summary
echo

echo "-- release authority --"
print_release_authority_summary
echo

echo "-- runtime supply chain --"
print_runtime_supply_chain_summary
echo

echo "-- codexea runtime --"
print_codexea_runtime_summary
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
