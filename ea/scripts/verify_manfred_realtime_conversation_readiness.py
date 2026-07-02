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
from materialize_manfred_realtime_conversation_readiness import MANFRED_OPERATOR_ACTION_KEY
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
    operator_action_key = str(receipt.get("operator_action_key") or "").strip()
    operator_action = dict(receipt.get("operator_action") or {})
    if receipt.get("generated_by") != "ea/scripts/materialize_manfred_realtime_conversation_readiness.py":
        issues.append("manfred_realtime_generated_by_mismatch")
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
    if not operator_action:
        issues.append("manfred_realtime_operator_action_missing")
    else:
        for raw_key in (
            "raw_private_context_exposed",
            "raw_chat_ids_exposed",
            "raw_token_exposed",
            "raw_secret_exposed",
            "raw_transcript_fields_exposed",
            "candidate_raw_text_fields_exposed",
            "raw_voice_ids_exposed",
        ):
            if operator_action.get(raw_key) is not False:
                issues.append(f"manfred_realtime_operator_action_raw_flag_not_false:{raw_key}")
        if operator_action.get("quiet_hours_respected") is not True:
            issues.append("manfred_realtime_operator_action_quiet_hours_missing")
        if operator_action.get("non_action_progress_push_allowed") is not False:
            issues.append("manfred_realtime_operator_action_non_action_push_allowed")
        if operator_action.get("irreversible_actions_consent_gated") is not True:
            issues.append("manfred_realtime_operator_action_consent_gate_missing")
        if operator_action.get("next_action") != next_action:
            issues.append("manfred_realtime_operator_action_next_action_mismatch")
        if operator_action.get("next_action_href") != next_action_href:
            issues.append("manfred_realtime_operator_action_href_mismatch")
        if operator_action.get("next_action_label") != next_action_label:
            issues.append("manfred_realtime_operator_action_label_mismatch")
        if str(operator_action.get("next_action_method") or "").lower() != next_action_method:
            issues.append("manfred_realtime_operator_action_method_mismatch")
    blocked_checks = [str(item or "").strip() for item in list(receipt.get("blocked_checks") or []) if str(item or "").strip()]
    if receipt.get("status") == "ready_for_realtime_conversation_review":
        if operator_action_key:
            issues.append("manfred_realtime_operator_action_key_should_be_empty_when_ready")
        if operator_action and operator_action.get("status") != "not_required":
            issues.append("manfred_realtime_operator_action_ready_status_mismatch")
        if operator_action and operator_action.get("user_action_required") is not False:
            issues.append("manfred_realtime_operator_action_ready_user_required")
        if operator_action and operator_action.get("delivery_policy") != "queue_only":
            issues.append("manfred_realtime_operator_action_ready_delivery_policy")
        if operator_action and operator_action.get("telegram_push_allowed") is not False:
            issues.append("manfred_realtime_operator_action_ready_push_allowed")
        if next_action_href != MANFRED_PROOF_PATH:
            issues.append("manfred_realtime_ready_next_action_href_drift")
        if next_action_label != MANFRED_PROOF_LABEL:
            issues.append("manfred_realtime_ready_next_action_label_drift")
    elif blocked_checks:
        if operator_action_key != MANFRED_OPERATOR_ACTION_KEY:
            issues.append("manfred_realtime_operator_action_key_missing")
        if operator_action and operator_action.get("operator_action_key") != MANFRED_OPERATOR_ACTION_KEY:
            issues.append("manfred_realtime_operator_action_packet_key_missing")
        if operator_action and operator_action.get("status") != "action_required":
            issues.append("manfred_realtime_operator_action_status_mismatch")
        if operator_action and operator_action.get("user_action_required") is not True:
            issues.append("manfred_realtime_operator_action_must_require_user")
        if operator_action and operator_action.get("delivery_policy") != "action_required_only":
            issues.append("manfred_realtime_operator_action_delivery_policy_mismatch")
        if operator_action and operator_action.get("telegram_push_allowed") is not True:
            issues.append("manfred_realtime_operator_action_push_flag_mismatch")
        if operator_action and operator_action.get("interruption_budget") != "action_required":
            issues.append("manfred_realtime_operator_action_budget_mismatch")
        if operator_action and operator_action.get("manual_only") is not True:
            issues.append("manfred_realtime_operator_action_manual_only_missing")
        if operator_action and operator_action.get("ci_must_not_auto_assert") is not True:
            issues.append("manfred_realtime_operator_action_ci_guard_missing")
        if operator_action and int(operator_action.get("required_check_count") or 0) <= 0:
            issues.append("manfred_realtime_operator_action_required_checks_missing")
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
