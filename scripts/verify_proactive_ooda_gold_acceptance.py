#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
EA_ROOT = ROOT / "ea"
for candidate in (str(ROOT), str(EA_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from app.services.proactive_ooda_operator_actions import proactive_next_action_surface

try:
    from scripts.source_state_head import resolve_source_state_head
    from scripts.source_state_head import resolve_source_worktree_fingerprint
except ModuleNotFoundError:  # pragma: no cover - script execution path
    from source_state_head import resolve_source_state_head
    from source_state_head import resolve_source_worktree_fingerprint

DEFAULT_RECEIPT = ROOT / ".codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json"
EXPECTED_RULES = {
    "This receipt proves proactive OODA gold only when routed delivery, assistant-grade source intent, and, when the selected packet depends on website research or browser work, live browse evidence are present alongside a chosen candidate, a staged reversible artifact, mirrored Teable projection, and a redacted approval outcome.",
    "Irreversible purchases, bookings, cancellations, sent messages, posts, and commitments remain consent-gated even when proactive staging is automated.",
    "Website browser work must produce a redacted browser-action receipt; CAPTCHA, Cloudflare, MFA, passkey, or credential blockers require a human handoff and must not be counted as completed work.",
    "Raw packet text, private links, actor identity, packet refs, and staged artifact refs must stay out of this published receipt; only hashes and coarse status may appear.",
    "Teable remains an admin projection and audit mirror rather than canonical queue or product truth.",
}
KNOWN_STATUSES = {
    "blocked_operator_runtime_posture",
    "blocked_low_quality_packet_evidence",
    "blocked_approval_capture_not_current",
    "blocked_missing_proactive_packet_evidence",
    "blocked_not_accepted_under_ordinary_use",
    "ready_for_approval_outcome_capture",
    "pass",
}
EXPECTED_PROOF_KEYS = {
    "operator_runtime_posture",
    "routed_delivery",
    "action_required_only_delivery",
    "assistant_grade_packet_quality",
    "browser_action_contract",
    "live_browse_evidence",
    "chosen_candidate",
    "staged_reversible_artifact",
    "teable_projection",
    "approval_capture_readiness",
    "approval_followthrough_notification",
    "approval_outcome",
}

EXPECTED_NEXT_ACTION_SURFACE_TARGETS = {
    "collect_live_browse_backed_safe_work_result": "Queue",
    "improve_proactive_packet_quality_and_collect_a_new_acceptance_outcome": "Queue",
    "inspect_teable_projection": "Goals",
    "maintain_proactive_ooda_gold_acceptance_evidence": "Goals",
    "persist_one_reversible_staged_artifact": "Queue",
    "probe_proactive_source_coverage": "Goals",
    "prove_proactive_delivery_only_notifies_for_user_action": "Goals",
    "reauthorize_google_workspace_binding": "the Google auth recovery surface",
    "reauthorize_or_sync_google_workspace_sources": "the Google sync action",
    "repair_proactive_browser_action_handoff_contract": "Queue",
    "repair_proactive_context_grounding": "Today",
    "repair_proactive_operator_runtime_posture": "Goals",
    "repair_proactive_safe_work_audit": "Queue",
    "reissue_proactive_approval": "the proactive approval reissue surface",
    "send_or_mirror_one_real_proactive_packet_with_routed_delivery_proof": "Goals",
    "stage_fresh_assistant_grade_proactive_packet": "Queue",
    "stage_one_chosen_candidate_for_user_decision": "Queue",
    "sync_calendar_and_renewal_sources": "the Google sync action",
    "verify_postgres_observation_source": "Goals",
}


def _verify_next_action_surface(payload: Mapping[str, Any], issues: list[str], *, prefix: str = "") -> None:
    next_action = str(payload.get("next_action") or "").strip()
    expected = proactive_next_action_surface(next_action)
    expected_href = str(expected.get("href") or "").strip()
    expected_label = str(expected.get("label") or "").strip()
    expected_method = str(expected.get("method") or "").strip().lower()
    if not expected_href:
        return
    href = str(payload.get("next_action_href") or "").strip()
    label = str(payload.get("next_action_label") or "").strip()
    method = str(payload.get("next_action_method") or "").strip().lower()
    context = f"{prefix} " if prefix else ""
    if not href:
        issues.append(f"{context}{next_action} requires next_action_href")
    elif href != expected_href:
        target = EXPECTED_NEXT_ACTION_SURFACE_TARGETS.get(next_action, expected_label or "the mapped action surface")
        issues.append(f"{context}{next_action} next_action_href must target {target}")
    if not label:
        issues.append(f"{context}{next_action} requires next_action_label")
    elif label != expected_label:
        issues.append(f"{context}{next_action} next_action_label drifted")
    if method != expected_method:
        issues.append(f"{context}{next_action} requires next_action_method={expected_method}")


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _verify_approval_capture(
    approval_capture: Mapping[str, Any],
    issues: list[str],
    *,
    required: bool,
    manual_ready: bool = False,
) -> None:
    if not approval_capture:
        if required and not manual_ready:
            issues.append("ready approval_capture_surface requires redacted approval_capture readiness proof")
        return
    privacy = dict(approval_capture.get("privacy") or {})
    for flag in (
        "raw_callback_token_exposed",
        "raw_principal_id_exposed",
        "raw_chat_ref_exposed",
        "raw_packet_ref_exposed",
        "raw_staged_artifact_ref_exposed",
    ):
        if bool(privacy.get(flag)):
            issues.append(f"approval_capture.privacy.{flag} must remain false")
    if not required:
        return
    if manual_ready:
        return
    if bool(approval_capture.get("checked")) is not True:
        issues.append("ready approval_capture_surface requires approval_capture.checked=true")
    if bool(approval_capture.get("ready")) is not True:
        if not str(approval_capture.get("blocking_reason") or "").strip():
            issues.append("blocked approval_capture requires blocking_reason")
        if not str(approval_capture.get("next_action") or "").strip():
            issues.append("blocked approval_capture requires next_action")
        return
    if bool(approval_capture.get("probe_ok")) is not True:
        issues.append("ready approval_capture_surface requires approval_capture.probe_ok=true")
    if str(approval_capture.get("status") or "").strip() != "ready":
        issues.append("ready approval_capture_surface requires approval_capture.status=ready")
    if bool(approval_capture.get("current_packet_refs_present")) is not True:
        issues.append("ready approval_capture_surface requires approval_capture.current_packet_refs_present=true")
    if int(approval_capture.get("current_packet_callback_record_count") or 0) <= 0:
        issues.append("ready approval_capture_surface requires approval_capture.current_packet_callback_record_count>0")
    if int(approval_capture.get("current_packet_live_pending_count") or 0) != 1:
        issues.append("ready approval_capture_surface requires approval_capture.current_packet_live_pending_count=1")
    if str(approval_capture.get("current_packet_callback_latest_status") or "").strip() != "pending":
        issues.append("ready approval_capture_surface requires approval_capture.current_packet_callback_latest_status=pending")
    if bool(approval_capture.get("callback_principal_hash_present")) is not True:
        issues.append("ready approval_capture_surface requires approval_capture.callback_principal_hash_present=true")
    if int(approval_capture.get("candidate_principal_hash_count") or 0) <= 0:
        issues.append("ready approval_capture_surface requires approval_capture.candidate_principal_hash_count>0")
    if bool(approval_capture.get("principal_match_ready")) is not True:
        issues.append("ready approval_capture_surface requires approval_capture.principal_match_ready=true")
    if bool(approval_capture.get("telegram_binding_ready")) is not True:
        issues.append("ready approval_capture_surface requires approval_capture.telegram_binding_ready=true")
    if bool(approval_capture.get("telegram_chat_ref_present")) is not True:
        issues.append("ready approval_capture_surface requires approval_capture.telegram_chat_ref_present=true")
    if bool(approval_capture.get("telegram_bot_token_present")) is not True:
        issues.append("ready approval_capture_surface requires approval_capture.telegram_bot_token_present=true")


def _verify_action_required_only_delivery(proof: Mapping[str, Any], issues: list[str], *, required: bool) -> None:
    if not proof:
        if required:
            issues.append("action_required_only_delivery proof missing")
        return
    if not required and not bool(proof.get("present")):
        return
    if proof.get("raw_policy_prompt_exposed") is not False:
        issues.append("action_required_only_delivery.raw_policy_prompt_exposed must remain false")
    if proof.get("policy_probe_checked") is not True:
        issues.append("action_required_only_delivery requires policy_probe_checked=true")
    if str(proof.get("policy_probe_status") or "").strip() != "pass":
        issues.append("action_required_only_delivery requires policy_probe_status=pass")
    if proof.get("low_value_research_prompt_requires_user_action") is not False:
        issues.append("low-value research approval prompts must not require Telegram user action")
    if proof.get("internal_proof_packet_requires_user_action") is not False:
        issues.append("internal proof packets must not require Telegram user action")
    if proof.get("executable_draft_prompt_requires_user_action") is not True:
        issues.append("executable draft approval prompts must require Telegram user action")


def _verify_approval_followthrough_notification(proof: Mapping[str, Any], issues: list[str]) -> None:
    if not proof:
        return
    if proof.get("raw_chat_ids_exposed") is not False:
        issues.append("approval_followthrough_notification.raw_chat_ids_exposed must remain false")
    if proof.get("raw_private_context_exposed") is not False:
        issues.append("approval_followthrough_notification.raw_private_context_exposed must remain false")
    if proof.get("raw_token_exposed") is not False:
        issues.append("approval_followthrough_notification.raw_token_exposed must remain false")
    if bool(proof.get("approval_followthrough_prompt_sent")):
        notification_status = str(proof.get("notification_status") or "").strip()
        if notification_status == "sent":
            if int(proof.get("message_count") or 0) <= 0:
                issues.append("approval_followthrough_notification sent proof requires message_count>0")
        elif notification_status == "suppressed_duplicate":
            if proof.get("approval_followthrough_prompt_covered_by_prior_send") is not True:
                issues.append(
                    "approval_followthrough_notification suppressed_duplicate proof requires prior-send coverage"
                )
            if str(proof.get("dedupe_proof_status") or "").strip() != "pass":
                issues.append("approval_followthrough_notification suppressed_duplicate proof requires dedupe_proof_status=pass")
            if proof.get("current_actions_covered_by_prior_state") is not True:
                issues.append(
                    "approval_followthrough_notification suppressed_duplicate proof requires current_actions_covered_by_prior_state=true"
                )
            if int(proof.get("dedupe_state_message_id_count") or 0) <= 0:
                issues.append(
                    "approval_followthrough_notification suppressed_duplicate proof requires dedupe_state_message_id_count>0"
                )
        else:
            issues.append(
                "approval_followthrough_notification sent proof requires notification_status=sent or suppressed_duplicate"
            )


def _git_head(path: Path = ROOT) -> str:
    return resolve_source_state_head(path)


def _source_fingerprint(path: Path = ROOT) -> str:
    return resolve_source_worktree_fingerprint(path)


def _path_from_text(root: Path, value: object) -> Path | None:
    text = str(value or "").strip()
    if not text:
        return None
    path = Path(text)
    return path if path.is_absolute() else root / path


def verify(path: Path = DEFAULT_RECEIPT, *, root: Path = ROOT) -> list[str]:
    issues: list[str] = []
    receipt = _load_json(path)
    if not receipt:
        return [f"proactive OODA gold acceptance missing or invalid: {path}"]

    if receipt.get("contract_name") != "ea.proactive_ooda_gold_acceptance.v1":
        issues.append("contract_name must be ea.proactive_ooda_gold_acceptance.v1")
    if receipt.get("generated_by") != "scripts/materialize_proactive_ooda_gold_acceptance.py":
        issues.append("generated_by must point at the proactive OODA gold-acceptance materializer")
    if receipt.get("head_semantics") != "source_state":
        issues.append("head_semantics must remain source_state")
    if receipt.get("source_state_fingerprint_semantics") != "worktree_source_files_sha256_excluding_generated_only_paths":
        issues.append("source_state_fingerprint_semantics must describe the source worktree fingerprint")

    current_head = _git_head(root)
    recorded_head = str(receipt.get("source_git_head") or "").strip()
    current_fingerprint = _source_fingerprint(root)
    recorded_fingerprint = str(receipt.get("source_state_fingerprint") or "").strip()
    fingerprint_matches = bool(current_fingerprint and recorded_fingerprint and current_fingerprint == recorded_fingerprint)
    if not recorded_head:
        issues.append("source_git_head missing")
    elif current_head and current_head != recorded_head and not fingerprint_matches:
        issues.append("receipt is stale relative to current source HEAD")
    if not recorded_fingerprint:
        issues.append("source_state_fingerprint missing")
    elif current_fingerprint and recorded_fingerprint != current_fingerprint:
        issues.append("receipt is stale relative to current source fingerprint")

    status = str(receipt.get("status") or "").strip()
    if status not in KNOWN_STATUSES:
        issues.append(f"status must stay within known proactive OODA gold states: {status or 'missing'}")
    if receipt.get("goal_completion_claim_allowed") is not False:
        issues.append("goal_completion_claim_allowed must remain false")
    if bool(receipt.get("gold_claim_allowed")) != (status == "pass"):
        issues.append("gold_claim_allowed must only be true when status=pass")
    if not str(receipt.get("summary") or "").strip():
        issues.append("summary must be present")
    if not str(receipt.get("next_action") or "").strip():
        issues.append("next_action must be present")
    _verify_next_action_surface(receipt, issues)

    proofs = receipt.get("proofs")
    if not isinstance(proofs, dict):
        issues.append("proofs must be a mapping")
        return issues
    if set(proofs) != EXPECTED_PROOF_KEYS:
        issues.append("proof keys drifted")
        return issues

    packet_runtime_proofs = [
        str(proofs[key].get("present")).lower() == "true"
        for key in (
            "operator_runtime_posture",
            "routed_delivery",
            "assistant_grade_packet_quality",
            "browser_action_contract",
            "live_browse_evidence",
            "chosen_candidate",
            "staged_reversible_artifact",
            "teable_projection",
        )
        if isinstance(proofs.get(key), dict)
    ]
    pass_runtime_proofs = packet_runtime_proofs + [
        str(dict(proofs.get("action_required_only_delivery") or {}).get("present")).lower() == "true"
    ]
    approval = dict(proofs.get("approval_outcome") or {})
    action_required_delivery = dict(proofs.get("action_required_only_delivery") or {})
    _verify_action_required_only_delivery(
        action_required_delivery,
        issues,
        required=bool(action_required_delivery.get("present")) or status == "pass",
    )
    _verify_approval_followthrough_notification(dict(proofs.get("approval_followthrough_notification") or {}), issues)
    if approval.get("raw_evidence_exposed") is not False:
        issues.append("approval_outcome.raw_evidence_exposed must remain false")
    if approval.get("raw_actor_exposed") is not False:
        issues.append("approval_outcome.raw_actor_exposed must remain false")
    if approval.get("raw_packet_ref_exposed") is not False:
        issues.append("approval_outcome.raw_packet_ref_exposed must remain false")
    if approval.get("raw_staged_artifact_exposed") is not False:
        issues.append("approval_outcome.raw_staged_artifact_exposed must remain false")

    approval_recorded = bool(approval.get("approval_outcome_recorded"))
    approval_accepted = bool(approval.get("accepted"))
    if approval_recorded:
        for key in ("evidence_sha256", "actor_sha256", "packet_ref_sha256", "staged_artifact_sha256"):
            if not str(approval.get(key) or "").strip():
                issues.append(f"approval_outcome missing hash field: {key}")

    rules = set(str(item).strip() for item in list(receipt.get("rules") or []) if str(item).strip())
    if rules != EXPECTED_RULES:
        issues.append("rules drifted")

    commands = [str(item).strip() for item in list(receipt.get("verifier_commands") or []) if str(item).strip()]
    for expected in (
        "make verify-proactive-ooda",
        "make verify-proactive-ooda-live-receipt",
        "make verify-proactive-ooda-operator-status",
        "make verify-proactive-ooda-gold-acceptance",
    ):
        if expected not in commands:
            issues.append(f"verifier_commands missing: {expected}")

    if status == "pass":
        if not all(pass_runtime_proofs):
            issues.append("pass requires all runtime proofs present")
        operator_runtime = dict(proofs.get("operator_runtime_posture") or {})
        if operator_runtime.get("source_coverage_ready") is not True:
            issues.append("pass requires operator_runtime_posture.source_coverage_ready=true")
        if list(operator_runtime.get("source_coverage_missing_lane_keys") or []):
            issues.append("pass requires no operator_runtime_posture.source_coverage_missing_lane_keys")
        if list(operator_runtime.get("source_coverage_missing_required_event_types") or []):
            issues.append("pass requires no operator_runtime_posture.source_coverage_missing_required_event_types")
        if operator_runtime.get("safe_work_audit_ready") is not True:
            issues.append("pass requires operator_runtime_posture.safe_work_audit_ready=true")
        if operator_runtime.get("current_artifact_filter_ready", True) is not True:
            issues.append("pass requires operator_runtime_posture.current_artifact_filter_ready=true")
        if operator_runtime.get("suppressed_projection_ready") is not True:
            issues.append("pass requires operator_runtime_posture.suppressed_projection_ready=true")
        if not approval_accepted:
            issues.append("pass requires approval_outcome.accepted=true")
        if list(receipt.get("remaining_external_proofs") or []):
            issues.append("pass must not retain remaining_external_proofs")
    if status == "ready_for_approval_outcome_capture" and not all(packet_runtime_proofs):
        issues.append("ready_for_approval_outcome_capture requires the runtime proofs to be present")
    if status == "ready_for_approval_outcome_capture":
        approval_capture = dict(proofs.get("approval_capture_readiness") or {})
        if approval_capture.get("ready") is not True:
            issues.append("ready_for_approval_outcome_capture requires approval_capture_readiness.ready=true")
    if status == "ready_for_approval_outcome_capture" and approval_recorded:
        issues.append("ready_for_approval_outcome_capture must not already have a recorded approval outcome")
    if status == "blocked_approval_capture_not_current":
        if not all(packet_runtime_proofs):
            issues.append("blocked_approval_capture_not_current requires the runtime packet proofs to be present")
        approval_capture = dict(proofs.get("approval_capture_readiness") or {})
        if approval_capture.get("approval_capture_surface_present") is not True:
            issues.append("blocked_approval_capture_not_current requires approval_capture_surface_present=true")
        if approval_capture.get("approval_capture_surface_mismatch_present") is not True:
            issues.append("blocked_approval_capture_not_current requires approval_capture_surface_mismatch_present=true")
        if approval_capture.get("current_packet_matches_packet_artifacts") is not False:
            issues.append("blocked_approval_capture_not_current requires current_packet_matches_packet_artifacts=false")
        if approval_recorded and not approval.get("stale_for_current_packet"):
            issues.append("blocked_approval_capture_not_current may only keep recorded approval evidence when it is stale for the current packet")
    if status == "blocked_not_accepted_under_ordinary_use":
        if not all(packet_runtime_proofs):
            issues.append("blocked_not_accepted_under_ordinary_use requires the runtime proofs to be present")
        if not approval_recorded or approval_accepted:
            issues.append("blocked_not_accepted_under_ordinary_use requires a recorded non-accepted approval outcome")
    if status == "blocked_operator_runtime_posture":
        operator_runtime = dict(proofs.get("operator_runtime_posture") or {})
        if bool(operator_runtime.get("present")):
            issues.append("blocked_operator_runtime_posture requires operator_runtime_posture.present=false")
        if "source_coverage_ready" not in operator_runtime and not str(operator_runtime.get("reason") or "").strip():
            issues.append("blocked_operator_runtime_posture requires source_coverage_ready detail")
        _verify_next_action_surface(operator_runtime, issues, prefix="operator_runtime_posture")
    if status == "blocked_low_quality_packet_evidence":
        quality = dict(proofs.get("assistant_grade_packet_quality") or {})
        if bool(quality.get("present")):
            issues.append("blocked_low_quality_packet_evidence requires assistant_grade_packet_quality.present=false")
        if not list(quality.get("issues") or []):
            issues.append("blocked_low_quality_packet_evidence requires assistant_grade_packet_quality.issues")

    evidence_receipts = receipt.get("evidence_receipts")
    if not isinstance(evidence_receipts, dict):
        issues.append("evidence_receipts must be a mapping")
        return issues
    approval_capture_surface = dict(evidence_receipts.get("approval_capture_surface") or {})
    approval_capture = dict(evidence_receipts.get("approval_capture") or {})
    if approval_capture_surface:
        callback_hygiene_ready = bool(approval_capture_surface.get("callback_hygiene_ready", True))
        if callback_hygiene_ready:
            if int(approval_capture_surface.get("callback_noncurrent_pending_count") or 0) != 0:
                issues.append("ready approval_capture_surface requires callback_noncurrent_pending_count=0")
            if int(approval_capture_surface.get("callback_stale_pending_count") or 0) != 0:
                issues.append("ready approval_capture_surface requires callback_stale_pending_count=0")
            if int(approval_capture_surface.get("current_packet_callback_stale_pending_count") or 0) != 0:
                issues.append("ready approval_capture_surface requires current_packet_callback_stale_pending_count=0")
            if int(approval_capture_surface.get("current_packet_duplicate_live_pending_count") or 0) != 0:
                issues.append("ready approval_capture_surface requires current_packet_duplicate_live_pending_count=0")
        else:
            if not str(approval_capture_surface.get("callback_hygiene_blocking_reason") or "").strip():
                issues.append("approval_capture_surface callback_hygiene_ready=false requires callback_hygiene_blocking_reason")
            if not str(approval_capture_surface.get("callback_hygiene_next_action") or "").strip():
                issues.append("approval_capture_surface callback_hygiene_ready=false requires callback_hygiene_next_action")
    if approval_capture_surface and bool(approval_capture_surface.get("ready")):
        telegram_ready = bool(approval_capture_surface.get("telegram_approval_surface_ready"))
        manual_ready = bool(approval_capture_surface.get("manual_outcome_capture_ready"))
        if str(approval_capture_surface.get("selected_channel") or "").strip() != "telegram":
            issues.append("ready approval_capture_surface requires selected_channel=telegram")
        if not bool(approval_capture_surface.get("callback_dir_writable")):
            issues.append("ready approval_capture_surface requires callback_dir_writable=true")
        if not str(approval_capture_surface.get("approval_outcome_path") or "").strip():
            issues.append("ready approval_capture_surface requires approval_outcome_path")
        if not str(approval_capture_surface.get("callback_dir") or "").strip():
            issues.append("ready approval_capture_surface requires callback_dir")
        if not telegram_ready and not manual_ready:
            issues.append("ready approval_capture_surface requires telegram or manual capture readiness")
        if bool(approval_capture_surface.get("current_packet_matches_packet_artifacts")) is not True:
            issues.append("ready approval_capture_surface requires current_packet_matches_packet_artifacts=true")
        if telegram_ready and int(approval_capture_surface.get("current_packet_live_pending_count") or 0) != 1:
            issues.append("ready approval_capture_surface requires current_packet_live_pending_count=1")
        if manual_ready and bool(approval_capture_surface.get("current_packet_approval_request_recordable")) is not True:
            issues.append("manual approval_capture_surface requires current_packet_approval_request_recordable=true")
        _verify_approval_capture(approval_capture, issues, required=True, manual_ready=manual_ready and not telegram_ready)
    elif approval_capture:
        _verify_approval_capture(approval_capture, issues, required=False)
    operator_status_evidence = dict(evidence_receipts.get("operator_status") or {})
    if bool(operator_status_evidence.get("present")):
        operator_status_path = _path_from_text(root, operator_status_evidence.get("path"))
        if operator_status_path is None or not operator_status_path.is_file():
            issues.append("linked operator_status receipt missing on disk")
        else:
            linked_operator_status = _load_json(operator_status_path)
            if not linked_operator_status:
                issues.append("linked operator_status receipt invalid")
            else:
                expected_contract = str(operator_status_evidence.get("contract_name") or "").strip()
                actual_contract = str(linked_operator_status.get("contract_name") or "").strip()
                if expected_contract and expected_contract != actual_contract:
                    issues.append("linked operator_status contract_name drifted")
                linked_head = str(linked_operator_status.get("source_git_head") or "").strip()
                linked_fingerprint = str(linked_operator_status.get("source_state_fingerprint") or "").strip()
                if recorded_head and linked_head and linked_head != recorded_head:
                    issues.append("linked operator_status is stale relative to gold receipt source HEAD")
                if recorded_fingerprint and linked_fingerprint and linked_fingerprint != recorded_fingerprint:
                    issues.append("linked operator_status is stale relative to gold receipt source fingerprint")
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the proactive OODA gold-acceptance receipt.")
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
