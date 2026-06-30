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

from materialize_executive_assistant_acceptance_evidence import (
    ACCEPTANCE_CAPTURE_LABEL,
    ACCEPTANCE_CAPTURE_FORM_FIELDS,
    ACCEPTANCE_CAPTURE_METHOD,
    ACCEPTANCE_CAPTURE_PATH,
    REMAINING_PROOF_LABELS,
    REQUIRED_ACCEPTANCE_KEYS,
)
from scripts.source_state_head import resolve_source_state_head  # noqa: E402
from scripts.source_state_head import resolve_source_worktree_fingerprint  # noqa: E402


DEFAULT_RECEIPT = REPO_ROOT / ".codex-studio" / "published" / "ea_executive_assistant_acceptance_evidence.generated.json"


def _verify_source_state(receipt: dict[str, Any], issues: list[str]) -> None:
    if receipt.get("head_semantics") != "source_state":
        issues.append("ea_acceptance_head_semantics_missing")
    if receipt.get("source_state_fingerprint_semantics") != "worktree_source_files_sha256_excluding_generated_only_paths":
        issues.append("ea_acceptance_source_state_fingerprint_semantics_missing")
    recorded_head = str(receipt.get("source_git_head") or "").strip()
    recorded_fingerprint = str(receipt.get("source_state_fingerprint") or "").strip()
    current_head = resolve_source_state_head(REPO_ROOT)
    current_fingerprint = resolve_source_worktree_fingerprint(REPO_ROOT)
    fingerprint_matches = bool(current_fingerprint and recorded_fingerprint and current_fingerprint == recorded_fingerprint)
    if not recorded_head:
        issues.append("ea_acceptance_source_git_head_missing")
    elif current_head and recorded_head != current_head and not fingerprint_matches:
        issues.append("ea_acceptance_source_git_head_stale")
    if not recorded_fingerprint:
        issues.append("ea_acceptance_source_state_fingerprint_missing")
    elif current_fingerprint and recorded_fingerprint != current_fingerprint:
        issues.append("ea_acceptance_source_state_fingerprint_stale")


def verify_executive_assistant_acceptance_evidence(receipt_path: str | Path) -> dict[str, Any]:
    receipt = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
    issues: list[str] = []
    _verify_source_state(receipt, issues)
    if receipt.get("goal_completion_claim_allowed") is True:
        issues.append("ea_acceptance_completion_overclaim")
    privacy = dict(receipt.get("privacy") or {})
    for key in ("raw_acceptance_text_exposed", "raw_actor_identity_exposed", "raw_object_reference_exposed", "raw_private_context_exposed"):
        if privacy.get(key) is not False:
            issues.append(f"ea_acceptance_privacy_flag_not_false:{key}")
    rows = dict(receipt.get("acceptance_keys") or {})
    for key in REQUIRED_ACCEPTANCE_KEYS:
        if key not in rows:
            issues.append(f"ea_acceptance_key_missing:{key}")
    accepted_keys = {key for key, row in rows.items() if dict(row).get("accepted") is True}
    expected_blocked = [key for key in REQUIRED_ACCEPTANCE_KEYS if key not in accepted_keys]
    if list(receipt.get("blocked_keys") or []) != expected_blocked:
        issues.append("ea_acceptance_blocked_keys_mismatch")
    if list(receipt.get("remaining_external_proofs") or []) != [REMAINING_PROOF_LABELS[key] for key in expected_blocked]:
        issues.append("ea_acceptance_remaining_external_proofs_mismatch")
    next_action = str(receipt.get("next_action") or "").strip()
    next_action_href = str(receipt.get("next_action_href") or "").strip()
    next_action_label = str(receipt.get("next_action_label") or "").strip()
    next_action_method = str(receipt.get("next_action_method") or "").strip().lower()
    next_action_proof_key = str(receipt.get("next_action_proof_key") or "").strip()
    if expected_blocked:
        if next_action != "collect_redacted_real_world_acceptance_evidence":
            issues.append("ea_acceptance_next_action_missing")
        if next_action_href != ACCEPTANCE_CAPTURE_PATH:
            issues.append("ea_acceptance_next_action_href_missing")
        if next_action_label != ACCEPTANCE_CAPTURE_LABEL:
            issues.append("ea_acceptance_next_action_label_missing")
        if next_action_method != ACCEPTANCE_CAPTURE_METHOD.lower():
            issues.append("ea_acceptance_next_action_method_missing")
        if next_action_proof_key != expected_blocked[0]:
            issues.append("ea_acceptance_next_action_proof_key_mismatch")
    else:
        if next_action != "review_good_executive_assistant_claim":
            issues.append("ea_acceptance_next_action_review_missing")
        for key, value in (
            ("href", next_action_href),
            ("label", next_action_label),
            ("method", next_action_method),
            ("proof_key", next_action_proof_key),
        ):
            if value:
                issues.append(f"ea_acceptance_next_action_{key}_should_be_empty_after_acceptance")
    operator_delivery_policy = dict(receipt.get("operator_delivery_policy") or {})
    if operator_delivery_policy.get("action_required_only") is not True:
        issues.append("ea_acceptance_operator_delivery_policy_action_required_only_missing")
    if operator_delivery_policy.get("telegram_push_allowed_for_next_action") is not bool(expected_blocked):
        issues.append("ea_acceptance_operator_delivery_policy_telegram_push_mismatch")
    if operator_delivery_policy.get("next_action_requires_user") is not bool(expected_blocked):
        issues.append("ea_acceptance_operator_delivery_policy_user_action_mismatch")
    expected_next_policy = "action_required_only" if expected_blocked else "queue_only"
    if operator_delivery_policy.get("next_action_delivery_policy") != expected_next_policy:
        issues.append("ea_acceptance_operator_delivery_policy_next_action_mismatch")
    for key in ("non_action_progress_push_allowed", "irreversible_actions_consent_gated", "quiet_hours_respected"):
        expected = False if key == "non_action_progress_push_allowed" else True
        if operator_delivery_policy.get(key) is not expected:
            issues.append(f"ea_acceptance_operator_delivery_policy_flag_mismatch:{key}")
    for key, row in rows.items():
        row_dict = dict(row)
        if row_dict.get("accepted") is True:
            if row_dict.get("status") != "accepted_redacted":
                issues.append(f"ea_acceptance_status_not_redacted:{key}")
            for hash_key in ("evidence_sha256", "actor_sha256", "object_ref_sha256"):
                if not row_dict.get(hash_key):
                    issues.append(f"ea_acceptance_hash_missing:{key}:{hash_key}")
        for raw_key in ("raw_evidence_exposed", "raw_actor_exposed", "raw_object_ref_exposed"):
            if row_dict.get(raw_key) is not False:
                issues.append(f"ea_acceptance_raw_field_flag_not_false:{key}:{raw_key}")

    surface = dict(receipt.get("acceptance_capture_surface") or {})
    if surface.get("method") != ACCEPTANCE_CAPTURE_METHOD:
        issues.append("ea_acceptance_capture_surface_method_missing")
    if surface.get("path") != ACCEPTANCE_CAPTURE_PATH:
        issues.append("ea_acceptance_capture_surface_path_missing")
    for key in ("admin_only", "operator_context_required", "raw_input_not_persisted"):
        if surface.get(key) is not True:
            issues.append(f"ea_acceptance_capture_surface_flag_not_true:{key}")
    if surface.get("stored_evidence_shape") != "sha256_only":
        issues.append("ea_acceptance_capture_surface_not_hash_only")
    for field in ACCEPTANCE_CAPTURE_FORM_FIELDS:
        if field not in list(surface.get("required_form_fields") or []):
            issues.append(f"ea_acceptance_capture_surface_field_missing:{field}")
    surface_privacy = dict(surface.get("privacy_contract") or {})
    for key in (
        "raw_acceptance_text_persisted",
        "raw_actor_identity_persisted",
        "raw_object_reference_persisted",
        "credential_values_persisted",
    ):
        if surface_privacy.get(key) is not False:
            issues.append(f"ea_acceptance_capture_surface_privacy_not_false:{key}")

    requirements = receipt.get("acceptance_capture_requirements") or []
    requirements_by_key = {
        str(dict(item).get("key") or ""): dict(item)
        for item in requirements
        if isinstance(item, dict)
    }
    for key in REQUIRED_ACCEPTANCE_KEYS:
        requirement = requirements_by_key.get(key)
        if not requirement:
            issues.append(f"ea_acceptance_capture_requirement_missing:{key}")
            continue
        if requirement.get("label") != REMAINING_PROOF_LABELS[key]:
            issues.append(f"ea_acceptance_capture_requirement_label_mismatch:{key}")
        if requirement.get("capture_method") != ACCEPTANCE_CAPTURE_METHOD:
            issues.append(f"ea_acceptance_capture_requirement_method_missing:{key}")
        if requirement.get("capture_path") != ACCEPTANCE_CAPTURE_PATH:
            issues.append(f"ea_acceptance_capture_requirement_path_missing:{key}")
        if requirement.get("proof_key") != key:
            issues.append(f"ea_acceptance_capture_requirement_proof_key_mismatch:{key}")
        for field in ACCEPTANCE_CAPTURE_FORM_FIELDS:
            if field not in list(requirement.get("required_form_fields") or []):
                issues.append(f"ea_acceptance_capture_requirement_field_missing:{key}:{field}")
        if requirement.get("raw_input_not_persisted") is not True:
            issues.append(f"ea_acceptance_capture_requirement_raw_input_not_persisted_missing:{key}")
        if requirement.get("stored_evidence_shape") != "sha256_only":
            issues.append(f"ea_acceptance_capture_requirement_not_hash_only:{key}")
        for raw_key in ("raw_evidence_exposed", "raw_actor_exposed", "raw_object_ref_exposed"):
            if requirement.get(raw_key) is not False:
                issues.append(f"ea_acceptance_capture_requirement_raw_flag_not_false:{key}:{raw_key}")
        expected_status = "accepted_redacted" if key in accepted_keys else "pending_real_world_evidence"
        if requirement.get("status") != expected_status:
            issues.append(f"ea_acceptance_capture_requirement_status_mismatch:{key}")
        user_action_required = key not in accepted_keys
        if requirement.get("user_action_required") is not user_action_required:
            issues.append(f"ea_acceptance_capture_requirement_user_action_mismatch:{key}")
        expected_delivery_policy = "action_required_only" if user_action_required else "queue_only"
        if requirement.get("delivery_policy") != expected_delivery_policy:
            issues.append(f"ea_acceptance_capture_requirement_delivery_policy_mismatch:{key}")
        if requirement.get("telegram_push_allowed") is not user_action_required:
            issues.append(f"ea_acceptance_capture_requirement_telegram_push_mismatch:{key}")
        expected_interruption_budget = "action_required" if user_action_required else "none"
        if requirement.get("interruption_budget") != expected_interruption_budget:
            issues.append(f"ea_acceptance_capture_requirement_interruption_budget_mismatch:{key}")
        if requirement.get("quiet_hours_respected") is not True:
            issues.append(f"ea_acceptance_capture_requirement_quiet_hours_missing:{key}")
        if requirement.get("non_action_progress_push_allowed") is not False:
            issues.append(f"ea_acceptance_capture_requirement_progress_push_allowed:{key}")
        if requirement.get("irreversible_actions_consent_gated") is not True:
            issues.append(f"ea_acceptance_capture_requirement_consent_gate_missing:{key}")
    return {"contract_name": "ea.executive_assistant_acceptance_evidence.verify.v1", "status": "pass" if not issues else "fail", "issues": issues}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify redacted Executive Assistant acceptance evidence.")
    parser.add_argument("--receipt", default=str(DEFAULT_RECEIPT))
    args = parser.parse_args(argv)
    result = verify_executive_assistant_acceptance_evidence(args.receipt)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
