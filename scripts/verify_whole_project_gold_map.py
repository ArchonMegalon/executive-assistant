#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RECEIPT = ROOT / ".codex-design/product/WHOLE_PROJECT_GOLD_MAP.generated.json"
BLOCKING_STATUSES = {
    "unknown_missing_receipt",
    "blocked",
    "fail",
    "draft_operator",
    "candidate_only",
    "separate_risk_zone",
}
REQUIRED_PLANES = {
    "ea_release_control",
    "fleet_journey_gates",
    "design_surface",
    "chummer_core_rules",
    "chummer_desktop_ui",
    "chummer_hub_public_web",
    "mobile_and_second_device",
    "media_factory_publication",
    "memorial_voice_demo",
    "ltd_provider_lanes",
}


def _json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def verify(path: Path = DEFAULT_RECEIPT) -> list[str]:
    issues: list[str] = []
    receipt = _json(path)
    if not receipt:
        return [f"whole-project gold map missing or invalid: {path}"]

    if receipt.get("contract_name") != "ea.whole_project_gold_map":
        issues.append("contract_name must be ea.whole_project_gold_map")

    planes = receipt.get("planes")
    if not isinstance(planes, list):
        return issues + ["planes must be a list"]

    by_key = {str(plane.get("key")): plane for plane in planes if isinstance(plane, dict)}
    missing_planes = sorted(REQUIRED_PLANES - set(by_key))
    if missing_planes:
        issues.append("required whole-project planes missing: " + ", ".join(missing_planes))

    ea_plane = by_key.get("ea_release_control") or {}
    if ea_plane.get("status") != "pass":
        issues.append("EA release-control plane must be pass before this map can pass")

    blocking_planes = [
        key
        for key, plane in by_key.items()
        if str(plane.get("status") or "").strip().lower() in BLOCKING_STATUSES
    ]
    receipt_blocking = [str(item) for item in list(receipt.get("blocking_planes") or [])]
    if sorted(blocking_planes) != sorted(receipt_blocking):
        issues.append("blocking_planes does not match plane statuses")

    gold_claim_allowed = bool(receipt.get("gold_claim_allowed"))
    overall_status = str(receipt.get("overall_status") or "").strip().lower()
    if receipt.get("claim_scope") != "ea_controlled_receipt_set":
        issues.append("claim_scope must be ea_controlled_receipt_set")
    if "not a blanket authority claim" not in str(receipt.get("claim_scope_label") or ""):
        issues.append("claim_scope_label must explicitly avoid blanket authority claims")
    if blocking_planes and gold_claim_allowed:
        issues.append("gold_claim_allowed cannot be true while blocking planes exist")
    if blocking_planes and overall_status == "gold":
        issues.append("overall_status cannot be gold while blocking planes exist")
    if not blocking_planes and overall_status != "gold":
        issues.append("overall_status should be gold only when no blocking planes exist")

    ltd_summary = receipt.get("ltd_provider_lane_summary")
    if not isinstance(ltd_summary, dict):
        issues.append("ltd_provider_lane_summary missing")
    else:
        if ltd_summary.get("poppy_runtime_enabled") is not False:
            issues.append("Poppy must remain runtime_enabled=false in the whole-project map")
        if ltd_summary.get("poppy_lane_state") != "verified_draft_operator_lane":
            issues.append("Poppy must be represented as verified_draft_operator_lane")

    rules = "\n".join(str(item) for item in list(receipt.get("rules") or []))
    if "EA flagship readiness does not imply whole Chummer project readiness" not in rules:
        issues.append("missing rule: EA flagship readiness does not imply whole Chummer project readiness")
    if "Unknown external planes block whole-project gold claims" not in rules:
        issues.append("missing rule: unknown external planes block whole-project gold claims")
    if "Gold here means EA-controlled receipt-set gold" not in rules:
        issues.append("missing rule: gold scope must be EA-controlled receipt-set gold")

    return issues


def main() -> int:
    if any(arg in {"--help", "-h"} for arg in sys.argv[1:]):
        print(
            "Usage:\n"
            "  python3 scripts/verify_whole_project_gold_map.py [--receipt PATH]\n\n"
            "Verify the conservative whole-project gold map and fail closed on overclaims."
        )
        return 0
    parser = argparse.ArgumentParser(description="Verify the conservative whole-project gold map.")
    parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    args = parser.parse_args()
    issues = verify(args.receipt)
    if issues:
        print(json.dumps({"status": "blocked", "issues": issues}, indent=2), file=sys.stderr)
        return 1
    print(json.dumps({"status": "pass", "message": "whole-project gold map is honest and fail-closed."}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
