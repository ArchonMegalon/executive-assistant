#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
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
    "memorial_public_origin_gold",
    "ltd_provider_lanes",
}
GENERATED_RECEIPT_PATHS = {
    ".codex-design/product/EA_FLAGSHIP_RELEASE_GATE.generated.json",
    ".codex-design/product/MEMORIAL_OPERATOR_STATUS.generated.json",
    ".codex-design/product/PROJECT_MODES.generated.json",
    ".codex-design/product/SHOW_SURFACE_MANIFEST.generated.json",
    ".codex-design/product/WEEKLY_PRODUCT_PULSE.generated.json",
    ".codex-design/product/WHOLE_PROJECT_GOLD_MAP.generated.json",
    ".codex-studio/published/EA_BROWSER_WORKFLOW_PROOF.generated.json",
    ".codex-studio/published/memorial_voice_roundtrip_exit_gate.generated.json",
    ".codex-studio/published/memorial_voice_roundtrip_public_origin.generated.json",
    ".codex-studio/published/memorial_realtime_browser_public_origin.generated.json",
    ".codex-studio/published/memorial_realtime_browser_meaningful_public_origin.generated.json",
    ".codex-studio/published/memorial_room_audio_public_origin.generated.json",
}


def _is_stable_repo_evidence_path(path_text: str) -> bool:
    normalized = str(path_text or "").strip()
    if normalized.startswith("/tmp/"):
        return False
    return normalized.startswith(".codex-design/") or normalized.startswith(".codex-studio/") or normalized.startswith("/")


def _json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _git_head(path: Path = ROOT) -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
    except Exception:
        return ""


def _recorded_source_head(payload: dict[str, Any]) -> str:
    return str(payload.get("source_git_head") or payload.get("git_head") or "").strip()


def _fresh_enough(recorded_head: str, *, current_head: str) -> bool:
    recorded = str(recorded_head or "").strip()
    if not recorded or not current_head:
        return False
    if recorded == current_head:
        return True
    try:
        proc = subprocess.run(
            ["git", "-C", str(ROOT), "diff", "--name-only", f"{recorded}..{current_head}"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return False
    if proc.returncode != 0:
        return False
    changed = {line.strip() for line in proc.stdout.splitlines() if line.strip()}
    return bool(changed) and changed <= GENERATED_RECEIPT_PATHS


def verify(path: Path = DEFAULT_RECEIPT) -> list[str]:
    issues: list[str] = []
    receipt = _json(path)
    if not receipt:
        return [f"whole-project gold map missing or invalid: {path}"]

    if receipt.get("contract_name") != "ea.whole_project_gold_map":
        issues.append("contract_name must be ea.whole_project_gold_map")
    current_head = _git_head()
    if current_head and not _fresh_enough(_recorded_source_head(receipt), current_head=current_head):
        issues.append("whole-project gold map is stale relative to current HEAD")

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

    memorial_plane = by_key.get("memorial_voice_demo") or {}
    if str(memorial_plane.get("status") or "").strip().lower() == "pass":
        evidence_paths = [str(item) for item in list(memorial_plane.get("evidence") or []) if str(item)]
        for evidence_text in evidence_paths:
            if not _is_stable_repo_evidence_path(evidence_text):
                issues.append("memorial voice evidence path must be repo-relative or generated-artifact relative")
                continue
            evidence_path = Path(evidence_text)
            payload = _json(ROOT / evidence_path)
            if payload and current_head and not _fresh_enough(_recorded_source_head(payload), current_head=current_head):
                issues.append("memorial voice receipt is stale relative to current HEAD")

    memorial_public_plane = by_key.get("memorial_public_origin_gold") or {}
    for evidence_text in [str(item) for item in list(memorial_public_plane.get("evidence") or []) if str(item)]:
        if not _is_stable_repo_evidence_path(evidence_text):
            issues.append("memorial public-origin evidence paths must be repo-relative or generated-artifact relative")

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
    if receipt.get("claim_scope") != "whole_project_plane_set":
        issues.append("claim_scope must be whole_project_plane_set")
    if "memorial public-origin experience" not in str(receipt.get("claim_scope_label") or ""):
        issues.append("claim_scope_label must explicitly include memorial public-origin experience")
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
    if "Whole-project gold requires every listed plane to pass" not in rules:
        issues.append("missing rule: whole-project gold must require every listed plane")

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
