from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RECEIPT = ROOT / ".codex-studio" / "published" / "whatsapp_audiobook_live_delivery.generated.json"
ALLOWED_STATUSES = {"pass", "blocked", "waiting_voice_choice", "waiting_provider_throttle", "waiting_for_live_epub"}
ALLOWED_CLAIM_SCOPES = {"none", "machine_playable_delivery_only", "machine_playable_delivery_and_human_accepted"}


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
        return [f"whatsapp audiobook live delivery receipt missing or invalid: {path}"]

    if receipt.get("contract_name") != "ea.whatsapp_audiobook_live_delivery_receipt.v1":
        issues.append("contract_name must be ea.whatsapp_audiobook_live_delivery_receipt.v1")
    if receipt.get("generated_by") != "ea/scripts/materialize_whatsapp_audiobook_live_delivery_receipt.py":
        issues.append("generated_by must point at the WhatsApp live delivery materializer")

    status = str(receipt.get("status") or "").strip()
    if status not in ALLOWED_STATUSES:
        issues.append("status must stay within the allowed WhatsApp live-delivery states")

    claim_allowed = bool(receipt.get("live_delivery_claim_allowed"))
    claim_scope = str(receipt.get("live_delivery_claim_scope") or "").strip()
    human_claim_allowed = bool(receipt.get("human_playback_acceptance_claim_allowed"))
    failed_codes = [str(item).strip() for item in list(receipt.get("failed_codes") or []) if str(item).strip()]
    next_action = str(receipt.get("next_action") or "").strip()
    runtime = dict(receipt.get("runtime_readiness") or {})
    audiobook_runtime = dict(receipt.get("audiobook_runtime") or {})
    historical = dict(receipt.get("historical_evidence") or {})
    proof_freshness = dict(receipt.get("proof_freshness") or {})
    human_evidence = dict(receipt.get("human_playback_acceptance_evidence") or {})
    proof_semantics = dict(receipt.get("proof_semantics") or {})
    human_status = str(human_evidence.get("status") or "").strip()
    rejected_claim_observed = bool(human_evidence.get("rejected_claim_observed"))
    feedback_sha256_valid = bool(human_evidence.get("feedback_sha256_valid"))
    operator_grade_rejected = (
        human_status == "rejected"
        and feedback_sha256_valid
        and human_evidence.get("operator_grade") is True
    )
    unhashed_rejected_claim = (
        (human_status == "rejected" and not feedback_sha256_valid)
        or (human_status == "not_human_verified" and rejected_claim_observed and not feedback_sha256_valid)
    )

    if claim_scope not in ALLOWED_CLAIM_SCOPES:
        issues.append("live_delivery_claim_scope must explicitly separate machine delivery from human acceptance")
    if human_status and human_status not in {"accepted", "rejected", "not_human_verified"}:
        issues.append("human_playback_acceptance_evidence.status must be accepted, rejected, or not_human_verified")
    if human_claim_allowed != bool(human_evidence.get("claim_allowed")):
        issues.append("human_playback_acceptance_claim_allowed must match human evidence claim_allowed")
    if proof_semantics.get("live_delivery_claim_scope") != claim_scope:
        issues.append("proof_semantics.live_delivery_claim_scope must match live_delivery_claim_scope")
    if proof_semantics.get("human_acceptance_evidence") != human_status:
        issues.append("proof_semantics.human_acceptance_evidence must match human evidence status")
    if human_status == "rejected":
        if human_evidence.get("rejected") is not True:
            issues.append("rejected human playback evidence must set rejected=true")
        if not bool(human_evidence.get("feedback_sha256_present")):
            issues.append("rejected human playback evidence requires feedback_sha256_present=true")
        if not feedback_sha256_valid:
            issues.append("rejected human playback evidence requires feedback_sha256_valid=true")
        if human_evidence.get("operator_grade") is not True:
            issues.append("rejected human playback evidence must be marked operator_grade=true")
    else:
        if human_evidence.get("rejected") is True:
            issues.append("rejected=true is only allowed for hashed operator-grade rejected playback evidence")
        if rejected_claim_observed and feedback_sha256_valid:
            issues.append("hashed rejected playback claims must be materialized as rejected evidence")

    if status == "pass":
        if not claim_allowed:
            issues.append("pass status requires live_delivery_claim_allowed=true")
        if receipt.get("machine_playback_e2e_verified") is not True:
            issues.append("pass status requires machine_playback_e2e_verified=true")
        if claim_scope not in {"machine_playable_delivery_only", "machine_playable_delivery_and_human_accepted"}:
            issues.append("pass status requires a machine-playable live_delivery_claim_scope")
        if failed_codes:
            issues.append("pass status must not carry failed_codes")
        if receipt.get("fresh_live_job_receipt_proven") is not True:
            issues.append("pass status requires fresh_live_job_receipt_proven=true")
        if receipt.get("historical_or_shadow_proof_only") is True:
            issues.append("pass status cannot be historical_or_shadow_proof_only")
        if proof_freshness.get("fresh_live_job_receipt_passed") is not True:
            issues.append("pass proof_freshness must show a passing fresh live job receipt")
        if not human_status:
            issues.append("pass status requires human_playback_acceptance_evidence.status")
        if human_claim_allowed:
            if receipt.get("real_user_playback_acceptance_verified") is not True:
                issues.append("human acceptance claim requires real_user_playback_acceptance_verified=true")
            if human_status != "accepted":
                issues.append("human acceptance claim requires accepted human evidence")
            if claim_scope != "machine_playable_delivery_and_human_accepted":
                issues.append("accepted human evidence requires machine_playable_delivery_and_human_accepted scope")
            if next_action != "close_operator_loop":
                issues.append("accepted human playback acceptance requires close_operator_loop next_action")
        else:
            if receipt.get("real_user_playback_acceptance_verified") is True:
                issues.append("real_user_playback_acceptance_verified=true requires human_playback_acceptance_claim_allowed=true")
            if claim_scope != "machine_playable_delivery_only":
                issues.append("unverified or rejected human acceptance requires machine_playable_delivery_only scope")
            if operator_grade_rejected and next_action != "review_audiobook_playback_problem":
                issues.append("operator-grade rejected human playback requires review_audiobook_playback_problem next_action")
            if (
                unhashed_rejected_claim
                and next_action != "capture_hashed_audiobook_playback_problem_feedback"
            ):
                issues.append("unhashed rejected human playback claims require hashed playback-problem feedback capture")
            if human_status != "rejected" and "capture_real_user_playback_acceptance" not in next_action:
                if not rejected_claim_observed:
                    issues.append("unverified human playback acceptance requires capture-real-user next_action")
        if proof_semantics.get("machine_playable_delivery_does_not_imply_human_acceptance") is not True:
            issues.append("proof_semantics must state machine delivery does not imply human acceptance")
    else:
        if claim_allowed:
            issues.append("non-pass status must not claim live delivery")
        if claim_scope != "none":
            issues.append("non-pass status requires live_delivery_claim_scope=none")
        if human_claim_allowed:
            issues.append("non-pass status must not claim human playback acceptance")
        if not failed_codes:
            issues.append("non-pass status must carry failed_codes")
        if not next_action:
            issues.append("non-pass status must include next_action")
        if receipt.get("fresh_live_job_receipt_proven") is True:
            issues.append("non-pass status cannot prove fresh live job receipt")

    if status == "waiting_for_live_epub":
        if int(receipt.get("candidate_count") or 0) != 0:
            issues.append("waiting_for_live_epub requires candidate_count=0")
        if not bool(runtime.get("ready")):
            issues.append("waiting_for_live_epub requires runtime_readiness.ready=true")
        if not bool(audiobook_runtime.get("ready_for_live_intake")):
            issues.append("waiting_for_live_epub requires audiobook_runtime.ready_for_live_intake=true")
        if not bool(historical.get("historical_live_path_proven")):
            issues.append("waiting_for_live_epub requires historical_live_path_proven=true")

    if status == "waiting_voice_choice":
        if "choose_whatsapp_audiobook_voice_sample" not in next_action:
            issues.append("waiting_voice_choice must keep the explicit voice-choice next action")
        if "voice_selection_text_fallback_ready" not in receipt:
            issues.append("waiting_voice_choice must expose voice_selection_text_fallback_ready")
        elif not isinstance(receipt.get("voice_selection_text_fallback_ready"), bool):
            issues.append("voice_selection_text_fallback_ready must be a boolean")
        pending = [
            row
            for row in list(receipt.get("pending_user_selected_voice_jobs") or [])
            if isinstance(row, dict) and (row.get("voice_selection_waiting") or row.get("replacement_choice_pending"))
        ]
        if pending and not all("voice_selection_text_fallback_ready" in row for row in pending):
            issues.append("waiting voice-choice pending jobs must expose voice_selection_text_fallback_ready")

    if status == "waiting_provider_throttle" and "wait_until_provider_retry_after" not in next_action:
        issues.append("waiting_provider_throttle must keep the retry-after next action")

    if not isinstance(receipt.get("stage_summary"), dict):
        issues.append("stage_summary must be an object")
    if not isinstance(receipt.get("historical_evidence"), dict):
        issues.append("historical_evidence must be an object")
    if not isinstance(receipt.get("runtime_readiness"), dict):
        issues.append("runtime_readiness must be an object")
    if not isinstance(receipt.get("audiobook_runtime"), dict):
        issues.append("audiobook_runtime must be an object")
    if not isinstance(receipt.get("proof_freshness"), dict):
        issues.append("proof_freshness must be an object")

    if receipt.get("goal_completion_claim_allowed") is not False:
        issues.append("goal_completion_claim_allowed must remain false")

    return issues


def main() -> int:
    import sys

    if any(flag in sys.argv[1:] for flag in ("--help", "-h")):
        print(
            "Usage:\n"
            "  python ea/scripts/verify_whatsapp_audiobook_live_delivery_receipt.py [options]\n\n"
            "Verify the WhatsApp audiobook live delivery receipt."
        )
        return 0
    parser = argparse.ArgumentParser(description="Verify the WhatsApp audiobook live delivery receipt.")
    parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    issues = verify(args.receipt)
    payload = {"status": "pass" if not issues else "blocked", "issues": issues}
    if args.pretty:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(json.dumps(payload))
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
