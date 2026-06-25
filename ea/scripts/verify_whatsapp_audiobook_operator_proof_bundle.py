from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RECEIPT = ROOT / ".codex-studio" / "published" / "whatsapp_audiobook_operator_proof_bundle.generated.json"
ALLOWED_STATUSES = {"pass", "blocked", "waiting_voice_choice", "waiting_provider_throttle", "waiting_for_live_epub"}
ALLOWED_CLAIM_SCOPES = {"none", "machine_playable_delivery_only", "machine_playable_delivery_and_human_accepted"}
ALLOWED_HUMAN_ACCEPTANCE_STATUSES = {"accepted", "rejected", "not_human_verified"}


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
        return [f"whatsapp audiobook operator proof bundle missing or invalid: {path}"]

    if receipt.get("contract_name") != "ea.whatsapp_audiobook_operator_proof_bundle.v1":
        issues.append("contract_name must be ea.whatsapp_audiobook_operator_proof_bundle.v1")
    if receipt.get("generated_by") != "ea/scripts/materialize_whatsapp_audiobook_operator_proof_bundle.py":
        issues.append("generated_by must point at the WhatsApp operator proof bundle materializer")

    status = str(receipt.get("status") or "").strip()
    if status not in ALLOWED_STATUSES:
        issues.append("status must stay within the allowed WhatsApp operator-bundle states")

    recommended_action = str(receipt.get("recommended_action") or "").strip()
    if not recommended_action:
        issues.append("recommended_action must be present")

    checks = dict(receipt.get("checks") or {})
    required_checks = {
        "local_epub_intake_proof_passed",
        "historical_public_share_playback_proven",
        "live_action_processor_ready",
        "live_action_processor_ran",
        "live_action_processor_no_runtime_errors",
        "live_processor_button_callbacks_drained",
        "live_processor_voice_text_drained",
        "live_processor_runtime_alignment_evaluated",
        "live_sidecar_inbox_accessible",
        "live_receipt_materialized",
        "live_receipt_has_explicit_next_action",
        "live_public_share_playback_verified_or_not_required",
        "live_delivery_semantics_from_live_receipt_or_explicit_nonpass_default",
        "live_delivery_claim_scope_explicit",
        "human_playback_acceptance_status_explicit",
        "rejected_playback_feedback_hashed_or_not_operator_grade",
        "machine_delivery_does_not_imply_human_acceptance",
        "live_voice_selection_text_fallback_ready_or_not_required",
        "live_voice_selection_shadow_passed_or_not_required",
    }
    waiting_core_checks = {
        "local_epub_intake_proof_passed",
        "live_action_processor_ready",
        "live_action_processor_ran",
        "live_action_processor_no_runtime_errors",
        "live_processor_button_callbacks_drained",
        "live_processor_voice_text_drained",
        "live_processor_runtime_alignment_evaluated",
        "live_sidecar_inbox_accessible",
        "live_receipt_materialized",
        "live_receipt_has_explicit_next_action",
        "live_delivery_claim_scope_explicit",
        "human_playback_acceptance_status_explicit",
        "rejected_playback_feedback_hashed_or_not_operator_grade",
        "machine_delivery_does_not_imply_human_acceptance",
        "live_voice_selection_text_fallback_ready_or_not_required",
        "live_voice_selection_shadow_passed_or_not_required",
    }
    missing_checks = sorted(required_checks - set(checks))
    if missing_checks:
        issues.append(f"missing required checks: {', '.join(missing_checks)}")

    live_delivery = dict(receipt.get("live_delivery") or {})
    claim_scope = str(live_delivery.get("live_delivery_claim_scope") or "").strip()
    human_evidence = dict(live_delivery.get("human_playback_acceptance_evidence") or {})
    human_status = str(human_evidence.get("status") or "").strip()
    human_claim_allowed = bool(live_delivery.get("human_playback_acceptance_claim_allowed"))
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
    proof_semantics = dict(receipt.get("proof_semantics") or {})
    live_proof_semantics = dict(live_delivery.get("proof_semantics") or {})

    if claim_scope not in ALLOWED_CLAIM_SCOPES:
        issues.append("live_delivery.live_delivery_claim_scope must explicitly separate machine delivery from human acceptance")
    if human_status not in ALLOWED_HUMAN_ACCEPTANCE_STATUSES:
        issues.append("live_delivery.human_playback_acceptance_evidence.status must be accepted, rejected, or not_human_verified")
    if human_claim_allowed != bool(human_evidence.get("claim_allowed")):
        issues.append("live_delivery.human_playback_acceptance_claim_allowed must match human evidence claim_allowed")
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
    if not proof_semantics:
        issues.append("proof_semantics must be present at bundle top level")
    if not live_proof_semantics:
        issues.append("live_delivery.proof_semantics must be present")
    if proof_semantics.get("live_delivery_claim_scope") != claim_scope:
        issues.append("proof_semantics.live_delivery_claim_scope must match live_delivery.live_delivery_claim_scope")
    if proof_semantics.get("human_acceptance_evidence") != human_status:
        issues.append("proof_semantics.human_acceptance_evidence must match live_delivery human evidence status")
    if proof_semantics.get("machine_playable_delivery_does_not_imply_human_acceptance") is not True:
        issues.append("proof_semantics must state machine delivery does not imply human acceptance")
    if live_proof_semantics.get("machine_playable_delivery_does_not_imply_human_acceptance") is not True:
        issues.append("live_delivery.proof_semantics must state machine delivery does not imply human acceptance")
    if live_delivery.get("goal_completion_claim_allowed") is not False:
        issues.append("live_delivery.goal_completion_claim_allowed must remain false")

    if status == "waiting_for_live_epub":
        if not all(bool(checks.get(key)) for key in waiting_core_checks):
            issues.append("waiting_for_live_epub requires all core checks to pass")
        if str(live_delivery.get("status") or "").strip() != "waiting_for_live_epub":
            issues.append("waiting_for_live_epub bundle requires matching live_delivery.status")
        if int(live_delivery.get("candidate_count") or 0) != 0:
            issues.append("waiting_for_live_epub bundle requires live_delivery.candidate_count=0")
        if not bool(live_delivery.get("historical_live_path_proven")):
            issues.append("waiting_for_live_epub bundle requires historical_live_path_proven=true")

    if status == "pass":
        if str(live_delivery.get("status") or "").strip() != "pass":
            issues.append("pass bundle requires live_delivery.status=pass")
        if not bool(live_delivery.get("live_delivery_claim_allowed")):
            issues.append("pass bundle requires live_delivery_claim_allowed=true")
        if claim_scope not in {"machine_playable_delivery_only", "machine_playable_delivery_and_human_accepted"}:
            issues.append("pass bundle requires a machine-playable live_delivery_claim_scope")
        if live_delivery.get("machine_playback_e2e_verified") is not True:
            issues.append("pass bundle requires live_delivery.machine_playback_e2e_verified=true")
        if not bool(live_delivery.get("fresh_live_job_receipt_proven")):
            issues.append("pass bundle requires fresh_live_job_receipt_proven=true")
        if bool(live_delivery.get("historical_or_shadow_proof_only")):
            issues.append("pass bundle cannot rely on historical_or_shadow_proof_only")
        if not bool(checks.get("live_public_share_playback_verified_or_not_required")):
            issues.append("pass bundle requires live public-share playback verification")
        if not bool(checks.get("live_processor_button_callbacks_drained")):
            issues.append("pass bundle requires live processor button callbacks to be drained")
        if not bool(checks.get("live_processor_voice_text_drained")):
            issues.append("pass bundle requires live processor voice text choices to be drained")
        if not bool(checks.get("live_delivery_semantics_from_live_receipt_or_explicit_nonpass_default")):
            issues.append("pass bundle requires playback semantics from the live delivery receipt")
        if not bool(checks.get("rejected_playback_feedback_hashed_or_not_operator_grade")):
            issues.append("pass bundle requires rejected playback evidence to carry hashed feedback")
        if human_claim_allowed:
            if live_delivery.get("real_user_playback_acceptance_verified") is not True:
                issues.append("human acceptance claim requires live_delivery.real_user_playback_acceptance_verified=true")
            if human_status != "accepted":
                issues.append("human acceptance claim requires accepted human evidence")
            if claim_scope != "machine_playable_delivery_and_human_accepted":
                issues.append("accepted human evidence requires machine_playable_delivery_and_human_accepted scope")
            if recommended_action != "close_operator_loop":
                issues.append("accepted human playback acceptance requires close_operator_loop recommended_action")
        else:
            if live_delivery.get("real_user_playback_acceptance_verified") is True:
                issues.append(
                    "live_delivery.real_user_playback_acceptance_verified=true requires human_playback_acceptance_claim_allowed=true"
                )
            if claim_scope != "machine_playable_delivery_only":
                issues.append("unverified or rejected human acceptance requires machine_playable_delivery_only scope")
            if operator_grade_rejected and recommended_action != "review_audiobook_playback_problem":
                issues.append("operator-grade rejected human playback requires review_audiobook_playback_problem recommended_action")
            if (
                unhashed_rejected_claim
                and recommended_action != "capture_hashed_audiobook_playback_problem_feedback"
            ):
                issues.append("unhashed rejected human playback claims require hashed playback-problem feedback capture")
            if human_status == "not_human_verified" and "capture_real_user_playback_acceptance" not in recommended_action:
                if not rejected_claim_observed:
                    issues.append("unverified human playback acceptance requires capture-real-user recommended_action")
    else:
        if bool(live_delivery.get("live_delivery_claim_allowed")):
            issues.append("non-pass bundle must not claim live delivery")
        if claim_scope != "none":
            issues.append("non-pass bundle requires live_delivery.live_delivery_claim_scope=none")
        if human_claim_allowed:
            issues.append("non-pass bundle must not claim human playback acceptance")
        if live_delivery.get("fresh_live_job_receipt_proven") is True:
            issues.append("non-pass bundle cannot prove fresh live job receipt")

    runtime_alignment = dict(receipt.get("runtime_alignment") or {})
    if not bool(runtime_alignment.get("evaluated")):
        issues.append("runtime_alignment.evaluated must remain true")
    if runtime_alignment.get("secret_values_exposed") is not False:
        issues.append("runtime_alignment.secret_values_exposed must remain false")

    live_readiness = dict(receipt.get("live_readiness") or {})
    if "ready" not in live_readiness:
        issues.append("live_readiness.ready missing")
    live_processor = dict(receipt.get("live_processor") or {})
    if "status" not in live_processor:
        issues.append("live_processor.status missing")
    if "status" not in live_delivery:
        issues.append("live_delivery.status missing")
    public_share_playback = dict(receipt.get("public_share_playback") or {})
    if "status" not in public_share_playback:
        issues.append("public_share_playback.status missing")

    return issues


def main() -> int:
    import sys

    if any(flag in sys.argv[1:] for flag in ("--help", "-h")):
        print(
            "Usage:\n"
            "  python ea/scripts/verify_whatsapp_audiobook_operator_proof_bundle.py [options]\n\n"
            "Verify the WhatsApp audiobook operator proof bundle."
        )
        return 0
    parser = argparse.ArgumentParser(description="Verify the WhatsApp audiobook operator proof bundle.")
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
