from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from materialize_manfred_realtime_conversation_readiness import REQUIRED_LIVE_PROOF_AFTER_READINESS
from materialize_manfred_realtime_conversation_readiness import ACTION_METHOD
from materialize_manfred_realtime_conversation_readiness import MANFRED_PROOF_LABEL
from materialize_manfred_realtime_conversation_readiness import MANFRED_PROOF_PATH
from materialize_manfred_realtime_conversation_readiness import MANFRED_VOICE_GOLD_LABEL
from materialize_manfred_realtime_conversation_readiness import MANFRED_VOICE_GOLD_PATH
from scripts.source_state_head import resolve_source_state_head
from scripts.source_state_head import resolve_source_worktree_fingerprint


DEFAULT_RECEIPT = REPO_ROOT / ".codex-studio" / "published" / "manfred_realtime_conversation_readiness.generated.json"


def verify_manfred_realtime_conversation_readiness(receipt_path: str | Path) -> dict[str, Any]:
    receipt = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
    issues: list[str] = []
    current_head = resolve_source_state_head(REPO_ROOT)
    current_fingerprint = resolve_source_worktree_fingerprint(REPO_ROOT)
    recorded_head = str(receipt.get("source_git_head") or "").strip()
    recorded_fingerprint = str(receipt.get("source_state_fingerprint") or "").strip()
    fingerprint_matches = bool(current_fingerprint and recorded_fingerprint and current_fingerprint == recorded_fingerprint)
    if receipt.get("head_semantics") != "source_state":
        issues.append("manfred_realtime_head_semantics_missing")
    if receipt.get("source_state_fingerprint_semantics") != "worktree_source_files_sha256_excluding_generated_only_paths":
        issues.append("manfred_realtime_source_fingerprint_semantics_missing")
    if not recorded_head:
        issues.append("manfred_realtime_source_git_head_missing")
    elif current_head and recorded_head != current_head and not fingerprint_matches:
        issues.append("manfred_realtime_source_head_stale")
    if not recorded_fingerprint:
        issues.append("manfred_realtime_source_fingerprint_missing")
    elif current_fingerprint and recorded_fingerprint != current_fingerprint:
        issues.append("manfred_realtime_source_fingerprint_stale")
    next_action = str(receipt.get("next_action") or "").strip()
    next_action_href = str(receipt.get("next_action_href") or "").strip()
    next_action_label = str(receipt.get("next_action_label") or "").strip()
    next_action_method = str(receipt.get("next_action_method") or "").strip().lower()
    if receipt.get("goal_completion_claim_allowed") is True:
        issues.append("manfred_realtime_goal_completion_overclaim")
    if receipt.get("realtime_conversation_claim_allowed") is True and receipt.get("blocked_checks"):
        issues.append("manfred_realtime_claim_overclaim")
    if dict(receipt.get("captured_candidate_diagnostic") or {}).get("promotion_allowed") is True and receipt.get("blocked_checks"):
        issues.append("manfred_realtime_captured_diagnostic_overclaim")
    for key, value in dict(receipt.get("privacy") or {}).items():
        if key != "redacted_text_fields" and value is not False:
            issues.append(f"manfred_realtime_privacy_flag_not_false:{key}")
    proofs = set(receipt.get("required_live_proof_after_readiness") or [])
    if not set(REQUIRED_LIVE_PROOF_AFTER_READINESS) <= proofs:
        issues.append("manfred_realtime_required_live_proof_incomplete")
    if not next_action:
        issues.append("manfred_realtime_next_action_missing")
    if next_action_method != ACTION_METHOD:
        issues.append("manfred_realtime_next_action_method_missing")
    blocked_checks = [str(item or "").strip() for item in list(receipt.get("blocked_checks") or []) if str(item or "").strip()]
    if receipt.get("status") == "ready_for_realtime_conversation_review":
        if next_action_href != MANFRED_PROOF_PATH:
            issues.append("manfred_realtime_ready_next_action_href_drift")
        if next_action_label != MANFRED_PROOF_LABEL:
            issues.append("manfred_realtime_ready_next_action_label_drift")
    elif blocked_checks:
        room_audio_blocked = bool({"room_audio_receipt_passed", "manual_room_checks_confirmed"}.intersection(blocked_checks))
        expected_href = MANFRED_PROOF_PATH if room_audio_blocked else MANFRED_VOICE_GOLD_PATH
        expected_label = MANFRED_PROOF_LABEL if room_audio_blocked else MANFRED_VOICE_GOLD_LABEL
        if next_action_href != expected_href:
            issues.append("manfred_realtime_blocked_next_action_href_drift")
        if next_action_label != expected_label:
            issues.append("manfred_realtime_blocked_next_action_label_drift")
    return {"contract_name": "ea.manfred_realtime_conversation_readiness.verify.v1", "status": "pass" if not issues else "fail", "issues": issues}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify Manfred realtime conversation readiness.")
    parser.add_argument("--receipt", default=str(DEFAULT_RECEIPT))
    args = parser.parse_args(argv)
    result = verify_manfred_realtime_conversation_readiness(args.receipt)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
