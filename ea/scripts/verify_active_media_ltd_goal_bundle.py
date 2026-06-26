from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


CONTRACT_NAME = "ea.active_media_ltd_goal_bundle.verify.v1"
SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[2]
DEFAULT_RECEIPT = REPO_ROOT / ".codex-studio" / "published" / "active_media_ltd_goal_bundle.generated.json"


def _load(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def verify_active_media_ltd_goal_bundle(receipt_path: str | Path) -> dict[str, Any]:
    receipt = _load(receipt_path)
    issues: list[str] = []
    if receipt.get("goal_completion_claim_allowed") is True or receipt.get("gold_claim_allowed") is True:
        issues.append("active_bundle_goal_completion_overclaim")
    if receipt.get("provider_ready") is True or receipt.get("live_provider_runtime_verified") is True:
        issues.append("active_bundle_provider_ready_overclaim")
    if receipt.get("verified_provider_claim_allowed") is True or receipt.get("provider_output_truth_allowed") is True:
        issues.append("active_bundle_provider_truth_overclaim")
    if receipt.get("public_route_claim_allowed") is True and receipt.get("public_route_deployment_verified") is not True:
        issues.append("active_bundle_public_route_overclaim")
    for key, row in dict(receipt.get("verifications") or {}).items():
        if dict(row).get("status") != "pass":
            issues.append(f"active_bundle_verification_status_not_pass:{key}")
        if dict(row).get("issues"):
            issues.append(f"active_bundle_verification_issues_not_empty:{key}")
        receipt_row = dict(dict(row).get("receipt") or {})
        if receipt_row and receipt_row.get("exists") is not True:
            issues.append(f"active_bundle_receipt_missing:{key}")
    posture = dict(receipt.get("external_proof_posture") or {})
    spoken = dict(posture.get("manfred_spoken_conversation") or {})
    if spoken.get("premium_spoken_claim_allowed") is True and spoken.get("status") != "ready_for_premium_review":
        issues.append("active_bundle_manfred_spoken_claim_overclaim")
    stt = dict(spoken.get("stt") or {})
    tts = dict(spoken.get("tts") or {})
    diagnostic = dict(spoken.get("captured_candidate_diagnostic") or {})
    if (
        stt.get("real_captured_fixture_required") is True
        and tts.get("premium_status") != "pass"
        and diagnostic.get("promotion_allowed") is True
    ):
        issues.append("active_bundle_manfred_captured_diagnostic_overclaim")
    audiobook = dict(posture.get("audiobook_live_delivery") or {})
    privacy = dict(audiobook.get("privacy") or {})
    if privacy.get("raw_public_share_url_included") is True:
        issues.append("active_bundle_audiobook_raw_public_share_url")
    if dict(spoken.get("privacy") or {}).get("raw_private_context_exposed") is True:
        issues.append("active_bundle_manfred_raw_private_context")
    return {"contract_name": CONTRACT_NAME, "status": "pass" if not issues else "fail", "issues": issues}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the Active Media LTD local evidence bundle.")
    parser.add_argument("--receipt", default=str(DEFAULT_RECEIPT))
    args = parser.parse_args(argv)
    result = verify_active_media_ltd_goal_bundle(args.receipt)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
