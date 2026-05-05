#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import yaml

PACKAGE_ID = "next90-m129-ea-compile-contribution-participation-entitlement-channel-a"
TITLE = "Compile contribution, participation, entitlement, channel, and reward followthrough packets from Hub/Fleet receipts only."
MILESTONE_ID = 129
FRONTIER_ID = 8620875598
ALLOWED_PATHS = ["scripts", "feedback", "docs"]
OWNED_SURFACES = ["compile_contribution_participation_entitlement_channel:executive_assistant"]
FORBIDDEN_PROOF_MARKERS = [
    "TASK_LOCAL_TELEMETRY",
    "ACTIVE_RUN_HANDOFF",
    "/var/lib/codex-fleet",
    "supervisor status",
    "supervisor eta",
    "operator telemetry",
    "codexea status",
    "codexea eta",
]

ROOT = Path(__file__).resolve().parents[1]
PACK_PATH = ROOT / "docs" / "chummer_participation_followthrough_packets" / "CHUMMER_PARTICIPATION_FOLLOWTHROUGH_PACKET_PACK.yaml"
SPECIMENS_PATH = ROOT / "docs" / "chummer_participation_followthrough_packets" / "PARTICIPATION_FOLLOWTHROUGH_PACKET_SPECIMENS.yaml"
PROOF_PATH = ROOT / ".codex-studio" / "published" / "NEXT90_M129_EA_PARTICIPATION_FOLLOWTHROUGH_PACKETS.generated.json"
MATERIALIZER_PATH = ROOT / "scripts" / "materialize_next90_m129_ea_participation_followthrough_packets.py"
HANDOFF_CLOSEOUT_PATH = ROOT / "docs" / "chummer_participation_followthrough_packets" / "SUCCESSOR_HANDOFF_CLOSEOUT.yaml"
FEEDBACK_PROGRESS_PATH = ROOT / "feedback" / "2026-05-05-next90-m129-ea-participation-followthrough-progress.md"
QUEUE_STAGING_PATH = Path("/docker/fleet/.codex-studio/published/NEXT_90_DAY_QUEUE_STAGING.generated.yaml")
DESIGN_QUEUE_STAGING_PATH = Path("/docker/chummercomplete/chummer-design-m114/products/chummer/NEXT_90_DAY_QUEUE_STAGING.generated.yaml")
SUCCESSOR_REGISTRY_PATH = Path("/docker/chummercomplete/chummer-design-m114/products/chummer/NEXT_90_DAY_PRODUCT_ADVANCE_REGISTRY.yaml")

def load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return dict(payload) if isinstance(payload, dict) else {}

def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8")) or {}
    return dict(payload) if isinstance(payload, dict) else {}

def materializer_module():
    spec = importlib.util.spec_from_file_location("ea_next90_m129_materializer", MATERIALIZER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load materializer from {MATERIALIZER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def _find_queue_row(path: Path) -> dict[str, Any] | None:
    payload = load_yaml(path)
    for row in payload.get("items") or []:
        if isinstance(row, dict) and row.get("package_id") == PACKAGE_ID:
            return dict(row)
    return None

def _find_registry_task(path: Path) -> dict[str, Any] | None:
    payload = load_yaml(path)
    for milestone in payload.get("milestones") or []:
        if not isinstance(milestone, dict) or int(milestone.get("id") or 0) != MILESTONE_ID:
            continue
        for task in milestone.get("work_tasks") or []:
            if isinstance(task, dict) and str(task.get("id")) == "129.5":
                return dict(task)
    return None

def main() -> int:
    issues: list[str] = []
    for path, label in (
        (PACK_PATH, "pack"),
        (SPECIMENS_PATH, "specimens"),
        (PROOF_PATH, "generated proof"),
        (HANDOFF_CLOSEOUT_PATH, "handoff closeout"),
        (FEEDBACK_PROGRESS_PATH, "feedback progress"),
    ):
        if not path.is_file():
            issues.append(f"missing {label}: {path}")
    if issues:
        print("\n".join(issues), file=sys.stderr)
        return 1

    pack = load_yaml(PACK_PATH)
    specimens = load_yaml(SPECIMENS_PATH)
    proof = load_json(PROOF_PATH)
    handoff = load_yaml(HANDOFF_CLOSEOUT_PATH)

    if pack.get("package_id") != PACKAGE_ID:
        issues.append("pack package_id drifted")
    if str(pack.get("title") or "") != TITLE:
        issues.append("pack title drifted")
    if int(pack.get("milestone_id") or 0) != MILESTONE_ID:
        issues.append("pack milestone drifted")
    if list(pack.get("owned_surfaces") or []) != OWNED_SURFACES:
        issues.append("pack owned_surfaces drifted")
    if specimens.get("package_id") != PACKAGE_ID:
        issues.append("specimens package_id drifted")
    if handoff.get("package_id") != PACKAGE_ID or handoff.get("status") != "active_package_proven":
        issues.append("handoff closeout identity drifted")
    if list(handoff.get("active_surfaces") or []) != OWNED_SURFACES:
        issues.append("handoff active_surfaces drifted")
    if proof.get("package_proof") != {
        "package_id": PACKAGE_ID,
        "title": TITLE,
        "task": TITLE,
        "milestone_id": MILESTONE_ID,
        "frontier_id": FRONTIER_ID,
        "allowed_paths": ALLOWED_PATHS,
        "owned_surfaces": OWNED_SURFACES,
    }:
        issues.append("generated package_proof drifted")

    try:
        module = materializer_module()
        rebuilt = module.build_payload()
        existing = module.without_generated_at(proof)
        if rebuilt != existing:
            issues.append("generated proof drifted from materializer output")
    except Exception as exc:
        issues.append(f"materializer rebuild failed: {exc}")

    packets = proof.get("packets")
    if not isinstance(packets, dict):
        issues.append("generated packets block missing")
    else:
        for packet_name in (
            "contribution_followthrough:participant",
            "participation_entitlement_followthrough",
            "channel_reward_followthrough",
        ):
            packet = dict(packets.get(packet_name) or {})
            if packet.get("state") != "hold":
                issues.append(f"{packet_name} should stay hold until upstream proof clears")
            if not list(packet.get("hold_reasons") or []):
                issues.append(f"{packet_name} hold reasons missing")

    source_truth_status = dict(proof.get("source_truth_status") or {})
    if not dict(source_truth_status.get("hub_reusable_account_flows_receipt") or {}).get("present"):
        issues.append("hub reusable account source is missing")
    if not dict(source_truth_status.get("fleet_participation_lane_receipts") or {}).get("present"):
        issues.append("fleet participation source is missing")
    if dict(source_truth_status.get("fleet_participation_lane_receipts") or {}).get("participation_status") != "blocked":
        issues.append("fleet participation proof is expected to remain blocked in the current window")

    gap_ids = [str(dict(item).get("gap_id") or "") for item in proof.get("projection_gaps") or [] if isinstance(item, dict)]
    for required_gap in (
        "fleet_participation_receipt_window_blocked",
        "missing_hub_or_fleet_channel_ref_projection",
        "missing_hub_or_fleet_reward_publication_projection",
    ):
        if required_gap not in gap_ids:
            issues.append(f"projection gap missing: {required_gap}")

    for queue_path in (QUEUE_STAGING_PATH, DESIGN_QUEUE_STAGING_PATH):
        row = _find_queue_row(queue_path)
        if row is None:
            issues.append(f"queue row missing in {queue_path}")
            continue
        if int(row.get("frontier_id") or 0) != FRONTIER_ID:
            issues.append(f"{queue_path}: frontier_id drifted")
        if list(row.get("allowed_paths") or []) != ALLOWED_PATHS:
            issues.append(f"{queue_path}: allowed_paths drifted")
        if list(row.get("owned_surfaces") or []) != OWNED_SURFACES:
            issues.append(f"{queue_path}: owned_surfaces drifted")

    registry_task = _find_registry_task(SUCCESSOR_REGISTRY_PATH)
    if registry_task is None:
        issues.append("registry work task 129.5 missing")
    elif registry_task.get("owner") != "executive-assistant":
        issues.append("registry work task owner drifted")

    encoded = json.dumps(
        {
            "pack": {key: value for key, value in pack.items() if key != "proof_guardrails"},
            "specimens": specimens,
            "proof": {key: value for key, value in proof.items() if key != "guardrails"},
            "handoff": {key: value for key, value in handoff.items() if key != "runtime_safety_posture"},
            "feedback": FEEDBACK_PROGRESS_PATH.read_text(encoding="utf-8"),
        },
        sort_keys=True,
    ).lower()
    for marker in FORBIDDEN_PROOF_MARKERS:
        if marker.lower() in encoded:
            issues.append(f"forbidden proof marker present: {marker}")

    if issues:
        print("\n".join(issues), file=sys.stderr)
        return 1

    print("ok: next90 m129 ea participation followthrough packets")
    print(f"ok: {PROOF_PATH}")
    print(f"ok: {HANDOFF_CLOSEOUT_PATH}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
