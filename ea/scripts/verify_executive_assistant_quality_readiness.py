from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from materialize_executive_assistant_acceptance_evidence import ACCEPTANCE_CAPTURE_LABEL
from materialize_executive_assistant_acceptance_evidence import ACCEPTANCE_CAPTURE_FORM_FIELDS
from materialize_executive_assistant_acceptance_evidence import ACCEPTANCE_CAPTURE_METHOD
from materialize_executive_assistant_acceptance_evidence import ACCEPTANCE_CAPTURE_PATH
from materialize_executive_assistant_acceptance_evidence import REMAINING_PROOF_LABELS
from materialize_executive_assistant_acceptance_evidence import REQUIRED_ACCEPTANCE_KEYS
from materialize_executive_assistant_quality_readiness import REQUIRED_REAL_WORLD_PROOF
from materialize_executive_assistant_quality_readiness import LOCAL_REVIEW_LABEL
from materialize_executive_assistant_quality_readiness import LOCAL_REVIEW_PATH


SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[2]
DEFAULT_RECEIPT = REPO_ROOT / ".codex-studio" / "published" / "ea_executive_assistant_quality_readiness.generated.json"


def verify_executive_assistant_quality_readiness(receipt_path: str | Path) -> dict[str, Any]:
    receipt = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
    issues: list[str] = []
    next_action_href = str(receipt.get("next_action_href") or "").strip()
    next_action_label = str(receipt.get("next_action_label") or "").strip()
    next_action_method = str(receipt.get("next_action_method") or "").strip().lower()
    next_action_proof_key = str(receipt.get("next_action_proof_key") or "").strip()
    next_action_context = dict(receipt.get("next_action_context") or {})
    if receipt.get("goal_completion_claim_allowed") is True:
        issues.append("ea_quality_completion_overclaim")
    if receipt.get("ea_is_product_truth") is True:
        issues.append("ea_quality_product_truth_overclaim")
    if receipt.get("good_executive_assistant_claim_allowed") is True and receipt.get("blocked_checks"):
        issues.append("ea_quality_good_claim_flag_mismatch")
    privacy = dict(receipt.get("privacy") or {})
    for key, value in privacy.items():
        if value is not False:
            issues.append(f"ea_quality_privacy_flag_not_false:{key}")
    required = set(receipt.get("required_real_world_proof") or [])
    for proof in REQUIRED_REAL_WORLD_PROOF:
        if proof not in required:
            issues.append(f"ea_quality_required_proof_missing:{proof}")
    surface = dict(receipt.get("acceptance_capture_surface") or {})
    if surface.get("method") != ACCEPTANCE_CAPTURE_METHOD:
        issues.append("ea_quality_acceptance_capture_surface_method_missing")
    if surface.get("path") != ACCEPTANCE_CAPTURE_PATH:
        issues.append("ea_quality_acceptance_capture_surface_path_missing")
    for key in ("admin_only", "operator_context_required", "raw_input_not_persisted"):
        if surface.get(key) is not True:
            issues.append(f"ea_quality_acceptance_capture_surface_flag_not_true:{key}")
    if surface.get("stored_evidence_shape") != "sha256_only":
        issues.append("ea_quality_acceptance_capture_surface_not_hash_only")
    for field in ACCEPTANCE_CAPTURE_FORM_FIELDS:
        if field not in list(surface.get("required_form_fields") or []):
            issues.append(f"ea_quality_acceptance_capture_surface_field_missing:{field}")
    surface_privacy = dict(surface.get("privacy_contract") or {})
    for key in (
        "raw_acceptance_text_persisted",
        "raw_actor_identity_persisted",
        "raw_object_reference_persisted",
        "credential_values_persisted",
    ):
        if surface_privacy.get(key) is not False:
            issues.append(f"ea_quality_acceptance_capture_surface_privacy_not_false:{key}")

    requirements = receipt.get("acceptance_capture_requirements") or []
    requirements_by_key = {
        str(dict(item).get("key") or ""): dict(item)
        for item in requirements
        if isinstance(item, dict)
    }
    accepted_keys = set(dict(receipt.get("acceptance_evidence") or {}).get("accepted_keys") or [])
    for key in REQUIRED_ACCEPTANCE_KEYS:
        requirement = requirements_by_key.get(key)
        if not requirement:
            issues.append(f"ea_quality_acceptance_capture_requirement_missing:{key}")
            continue
        if requirement.get("label") != REMAINING_PROOF_LABELS[key]:
            issues.append(f"ea_quality_acceptance_capture_requirement_label_mismatch:{key}")
        if requirement.get("capture_method") != ACCEPTANCE_CAPTURE_METHOD:
            issues.append(f"ea_quality_acceptance_capture_requirement_method_missing:{key}")
        if requirement.get("capture_path") != ACCEPTANCE_CAPTURE_PATH:
            issues.append(f"ea_quality_acceptance_capture_requirement_path_missing:{key}")
        if requirement.get("proof_key") != key:
            issues.append(f"ea_quality_acceptance_capture_requirement_proof_key_mismatch:{key}")
        for field in ACCEPTANCE_CAPTURE_FORM_FIELDS:
            if field not in list(requirement.get("required_form_fields") or []):
                issues.append(f"ea_quality_acceptance_capture_requirement_field_missing:{key}:{field}")
        if requirement.get("raw_input_not_persisted") is not True:
            issues.append(f"ea_quality_acceptance_capture_requirement_raw_input_not_persisted_missing:{key}")
        if requirement.get("stored_evidence_shape") != "sha256_only":
            issues.append(f"ea_quality_acceptance_capture_requirement_not_hash_only:{key}")
        for raw_key in ("raw_evidence_exposed", "raw_actor_exposed", "raw_object_ref_exposed"):
            if requirement.get(raw_key) is not False:
                issues.append(f"ea_quality_acceptance_capture_requirement_raw_flag_not_false:{key}:{raw_key}")
        expected_status = "accepted_redacted" if key in accepted_keys else "pending_real_world_evidence"
        if requirement.get("status") != expected_status:
            issues.append(f"ea_quality_acceptance_capture_requirement_status_mismatch:{key}")
    status = str(receipt.get("status") or "").strip()
    if status == "blocked_real_world_acceptance":
        if next_action_href != ACCEPTANCE_CAPTURE_PATH:
            issues.append("ea_quality_next_action_href_missing")
        if next_action_label != ACCEPTANCE_CAPTURE_LABEL:
            issues.append("ea_quality_next_action_label_missing")
        if next_action_method != ACCEPTANCE_CAPTURE_METHOD.lower():
            issues.append("ea_quality_next_action_method_missing")
        if not next_action_proof_key:
            issues.append("ea_quality_next_action_proof_key_missing")
        if next_action_context.get("kind") != "redacted_acceptance_capture":
            issues.append("ea_quality_next_action_context_kind_missing")
        if next_action_context.get("proof_key") != next_action_proof_key:
            issues.append("ea_quality_next_action_context_proof_key_mismatch")
        if next_action_context.get("proof_label") != REMAINING_PROOF_LABELS.get(next_action_proof_key):
            issues.append("ea_quality_next_action_context_label_mismatch")
        if next_action_context.get("capture_path") != ACCEPTANCE_CAPTURE_PATH:
            issues.append("ea_quality_next_action_context_capture_path_missing")
        if str(next_action_context.get("capture_method") or "").lower() != ACCEPTANCE_CAPTURE_METHOD.lower():
            issues.append("ea_quality_next_action_context_capture_method_missing")
        for field in ACCEPTANCE_CAPTURE_FORM_FIELDS:
            if field not in list(next_action_context.get("required_form_fields") or []):
                issues.append(f"ea_quality_next_action_context_field_missing:{field}")
        if next_action_context.get("stored_evidence_shape") != "sha256_only":
            issues.append("ea_quality_next_action_context_not_hash_only")
        for key in (
            "raw_acceptance_text_persisted",
            "raw_actor_identity_persisted",
            "raw_object_reference_persisted",
        ):
            if next_action_context.get(key) is not False:
                issues.append(f"ea_quality_next_action_context_privacy_not_false:{key}")
    elif status == "blocked_local_quality_evidence":
        if next_action_href != LOCAL_REVIEW_PATH:
            issues.append("ea_quality_local_next_action_href_drift")
        if next_action_label != LOCAL_REVIEW_LABEL:
            issues.append("ea_quality_local_next_action_label_drift")
        if next_action_method != "get":
            issues.append("ea_quality_local_next_action_method_drift")
    else:
        if next_action_href or next_action_label or next_action_method or next_action_proof_key:
            issues.append("ea_quality_ready_next_action_should_be_empty")
        if next_action_context:
            issues.append("ea_quality_ready_next_action_context_should_be_empty")
    return {"contract_name": "ea.executive_assistant_quality_readiness.verify.v1", "status": "pass" if not issues else "fail", "issues": issues}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify EA quality readiness.")
    parser.add_argument("--receipt", default=str(DEFAULT_RECEIPT))
    args = parser.parse_args(argv)
    result = verify_executive_assistant_quality_readiness(args.receipt)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
