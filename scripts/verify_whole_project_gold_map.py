#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from scripts.materialize_project_mode_manifests import _fresh_enough, _recorded_source_head
    from scripts.materialize_whole_project_gold_map import BLOCKING_STATUSES
    from scripts.source_state_head import resolve_source_state_head
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from materialize_project_mode_manifests import _fresh_enough, _recorded_source_head
    from materialize_whole_project_gold_map import BLOCKING_STATUSES
    from source_state_head import resolve_source_state_head


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RECEIPT = ROOT / ".codex-design/product/WHOLE_PROJECT_GOLD_MAP.generated.json"
REQUIRED_PLANES = {
    "ea_release_control",
    "fleet_journey_gates",
    "design_surface",
    "chummer_core_rules",
    "chummer_desktop_ui",
    "chummer_hub_public_web",
    "mobile_and_second_device",
    "media_factory_publication",
    "telegram_video_delivery",
    "ltd_provider_lanes",
}


def _json(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def verify(path: Path = DEFAULT_RECEIPT) -> list[str]:
    receipt = _json(path)
    if not receipt:
        return [f"whole-project gold map missing or invalid: {path}"]
    issues: list[str] = []
    if receipt.get("contract_name") != "ea.whole_project_gold_map":
        issues.append("contract_name must be ea.whole_project_gold_map")
    current_head = resolve_source_state_head(ROOT)
    if current_head and not _fresh_enough(
        _recorded_source_head(receipt), current_head=current_head
    ):
        issues.append("whole-project gold map is stale relative to current HEAD")
    planes = receipt.get("planes")
    if not isinstance(planes, list):
        return [*issues, "planes must be a list"]
    by_key = {str(row.get("key")): row for row in planes if isinstance(row, dict)}
    if set(by_key) != REQUIRED_PLANES:
        issues.append("required whole-project plane set does not match")
    blocking = sorted(
        key
        for key, row in by_key.items()
        if str(row.get("status") or "").strip().lower() in BLOCKING_STATUSES
    )
    if blocking != sorted(str(item) for item in list(receipt.get("blocking_planes") or [])):
        issues.append("blocking_planes does not match plane statuses")
    gold_allowed = receipt.get("gold_claim_allowed") is True
    overall = str(receipt.get("overall_status") or "").strip().lower()
    if blocking and gold_allowed:
        issues.append("gold_claim_allowed cannot be true while blocking planes exist")
    if blocking and overall == "gold":
        issues.append("overall_status cannot be gold while blocking planes exist")
    if not blocking and (not gold_allowed or overall != "gold"):
        issues.append("gold requires no blocking planes and an explicit claim allowance")
    if receipt.get("claim_scope") != "whole_project_plane_set":
        issues.append("claim_scope must be whole_project_plane_set")
    rules = "\n".join(str(item) for item in list(receipt.get("rules") or []))
    for required in (
        "EA flagship readiness does not imply whole Chummer project readiness",
        "Unknown external planes block whole-project gold claims",
        "Whole-project gold requires every listed plane to pass",
        "Telegram video delivery requires a dedicated live delivery receipt",
    ):
        if required not in rules:
            issues.append(f"missing rule: {required}")
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the conservative whole-project gold map.")
    parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    args = parser.parse_args()
    issues = verify(args.receipt)
    if issues:
        print(json.dumps({"status": "blocked", "issues": issues}, indent=2))
        return 1
    print(json.dumps({"status": "pass"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
