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

from materialize_whole_project_signal_to_decision_receipt import (
    REQUIRED_SIGNAL_SOURCES,
    SIGNAL_EVIDENCE_CAPTURE_LABEL,
    SIGNAL_EVIDENCE_CAPTURE_FORM_FIELDS,
    SIGNAL_EVIDENCE_CAPTURE_METHOD,
    SIGNAL_EVIDENCE_CAPTURE_PATH,
    SIGNAL_EVIDENCE_PARTS,
)
from scripts.source_state_head import resolve_source_state_head
from scripts.source_state_head import resolve_source_worktree_fingerprint


DEFAULT_RECEIPT = REPO_ROOT / ".codex-studio" / "published" / "ea_whole_project_signal_to_decision.generated.json"


def _load(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _verify_source_state(receipt: dict[str, Any], issues: list[str]) -> None:
    if receipt.get("head_semantics") != "source_state":
        issues.append("signal_decision_head_semantics_missing")
    if receipt.get("source_state_fingerprint_semantics") != "worktree_source_files_sha256_excluding_generated_only_paths":
        issues.append("signal_decision_source_state_fingerprint_semantics_missing")
    recorded_head = str(receipt.get("source_git_head") or "").strip()
    recorded_fingerprint = str(receipt.get("source_state_fingerprint") or "").strip()
    current_head = resolve_source_state_head(REPO_ROOT)
    current_fingerprint = resolve_source_worktree_fingerprint(REPO_ROOT)
    if not recorded_head:
        issues.append("signal_decision_source_git_head_missing")
    elif recorded_head != current_head and recorded_fingerprint != current_fingerprint:
        issues.append("signal_decision_source_git_head_stale")
    if not recorded_fingerprint:
        issues.append("signal_decision_source_state_fingerprint_missing")
    elif recorded_fingerprint != current_fingerprint:
        issues.append("signal_decision_source_state_fingerprint_stale")


def verify_whole_project_signal_to_decision_receipt(receipt_path: str | Path) -> dict[str, Any]:
    receipt = _load(receipt_path)
    issues: list[str] = []
    _verify_source_state(receipt, issues)
    if receipt.get("goal_completion_claim_allowed") is True:
        issues.append("signal_decision_completion_overclaim")
    if receipt.get("queue_truth_claim_allowed") is True:
        issues.append("signal_decision_queue_truth_overclaim")
    if dict(receipt.get("boundary_posture") or {}).get("ea_is_product_truth") is True:
        issues.append("signal_decision_ea_product_truth_overclaim")
    next_action = str(receipt.get("next_action") or "").strip()
    next_action_href = str(receipt.get("next_action_href") or "").strip()
    next_action_label = str(receipt.get("next_action_label") or "").strip()
    next_action_method = str(receipt.get("next_action_method") or "").strip().lower()
    next_action_evidence_part = str(receipt.get("next_action_evidence_part") or "").strip()
    rows = {dict(row).get("key"): row for row in receipt.get("signal_sources") or []}
    for key in REQUIRED_SIGNAL_SOURCES:
        if key not in rows:
            issues.append(f"signal_decision_source_row_missing:{key}")
    privacy = dict(receipt.get("privacy") or {})
    for key in (
        "raw_review_text_exposed",
        "raw_followthrough_text_exposed",
        "raw_actor_identity_exposed",
        "raw_packet_reference_exposed",
        "raw_private_context_exposed",
    ):
        if privacy.get(key) is not False:
            issues.append(f"signal_decision_privacy_flag_not_false:{key}")

    surface = dict(receipt.get("signal_evidence_capture_surface") or {})
    if surface.get("method") != SIGNAL_EVIDENCE_CAPTURE_METHOD:
        issues.append("signal_decision_capture_surface_method_missing")
    if surface.get("path") != SIGNAL_EVIDENCE_CAPTURE_PATH:
        issues.append("signal_decision_capture_surface_path_missing")
    for key in ("admin_only", "operator_context_required", "raw_input_not_persisted"):
        if surface.get(key) is not True:
            issues.append(f"signal_decision_capture_surface_flag_not_true:{key}")
    if surface.get("stored_evidence_shape") != "sha256_only":
        issues.append("signal_decision_capture_surface_not_hash_only")
    for field in SIGNAL_EVIDENCE_CAPTURE_FORM_FIELDS:
        if field not in list(surface.get("required_form_fields") or []):
            issues.append(f"signal_decision_capture_surface_field_missing:{field}")
    for part in SIGNAL_EVIDENCE_PARTS:
        if part not in list(surface.get("valid_evidence_parts") or []):
            issues.append(f"signal_decision_capture_surface_part_missing:{part}")
    surface_privacy = dict(surface.get("privacy_contract") or {})
    for key in (
        "raw_review_text_persisted",
        "raw_followthrough_text_persisted",
        "raw_actor_identity_persisted",
        "raw_packet_reference_persisted",
        "credential_values_persisted",
    ):
        if surface_privacy.get(key) is not False:
            issues.append(f"signal_decision_capture_surface_privacy_not_false:{key}")

    requirements = receipt.get("signal_evidence_capture_requirements") or []
    requirements_by_part = {
        str(dict(item).get("evidence_part") or ""): dict(item)
        for item in requirements
        if isinstance(item, dict)
    }
    for part, spec in SIGNAL_EVIDENCE_PARTS.items():
        requirement = requirements_by_part.get(part)
        accepted = bool(receipt.get(str(spec["accepted_field"])))
        if not requirement:
            issues.append(f"signal_decision_capture_requirement_missing:{part}")
            continue
        if requirement.get("label") != spec["label"]:
            issues.append(f"signal_decision_capture_requirement_label_mismatch:{part}")
        if requirement.get("capture_method") != SIGNAL_EVIDENCE_CAPTURE_METHOD:
            issues.append(f"signal_decision_capture_requirement_method_missing:{part}")
        if requirement.get("capture_path") != SIGNAL_EVIDENCE_CAPTURE_PATH:
            issues.append(f"signal_decision_capture_requirement_path_missing:{part}")
        for field in SIGNAL_EVIDENCE_CAPTURE_FORM_FIELDS:
            if field not in list(requirement.get("required_form_fields") or []):
                issues.append(f"signal_decision_capture_requirement_field_missing:{part}:{field}")
        if requirement.get("raw_input_not_persisted") is not True:
            issues.append(f"signal_decision_capture_requirement_raw_input_not_persisted_missing:{part}")
        if requirement.get("stored_evidence_shape") != "sha256_only":
            issues.append(f"signal_decision_capture_requirement_not_hash_only:{part}")
        for raw_key in ("raw_evidence_exposed", "raw_actor_exposed", "raw_packet_ref_exposed"):
            if requirement.get(raw_key) is not False:
                issues.append(f"signal_decision_capture_requirement_raw_flag_not_false:{part}:{raw_key}")
        expected_status = "accepted_redacted" if accepted else "pending_real_world_evidence"
        if requirement.get("status") != expected_status:
            issues.append(f"signal_decision_capture_requirement_status_mismatch:{part}")

        evidence_row = dict(receipt.get(str(spec["receipt_field"])) or {})
        if accepted:
            if evidence_row.get("status") != "accepted_redacted":
                issues.append(f"signal_decision_status_not_redacted:{part}")
            for hash_key in (str(spec["hash_field"]), "actor_sha256", "packet_ref_sha256"):
                if not evidence_row.get(hash_key):
                    issues.append(f"signal_decision_hash_missing:{part}:{hash_key}")
        raw_field = "raw_review_exposed" if part == "review" else "raw_followthrough_exposed"
        for raw_key in (raw_field, "raw_actor_exposed", "raw_packet_ref_exposed"):
            if evidence_row.get(raw_key) is not False:
                issues.append(f"signal_decision_raw_field_flag_not_false:{part}:{raw_key}")
    if not bool(receipt.get("real_weekly_operator_review_accepted")):
        if next_action != str(SIGNAL_EVIDENCE_PARTS["review"]["next_action"]):
            issues.append("signal_decision_next_action_review_missing")
        if next_action_evidence_part != "review":
            issues.append("signal_decision_next_action_evidence_part_mismatch:review")
        if next_action_href != SIGNAL_EVIDENCE_CAPTURE_PATH:
            issues.append("signal_decision_next_action_href_missing")
        if next_action_label != SIGNAL_EVIDENCE_CAPTURE_LABEL:
            issues.append("signal_decision_next_action_label_missing")
        if next_action_method != SIGNAL_EVIDENCE_CAPTURE_METHOD.lower():
            issues.append("signal_decision_next_action_method_missing")
    elif not bool(receipt.get("closed_loop_followthrough_receipt_verified")):
        if next_action != str(SIGNAL_EVIDENCE_PARTS["followthrough"]["next_action"]):
            issues.append("signal_decision_next_action_followthrough_missing")
        if next_action_evidence_part != "followthrough":
            issues.append("signal_decision_next_action_evidence_part_mismatch:followthrough")
        if next_action_href != SIGNAL_EVIDENCE_CAPTURE_PATH:
            issues.append("signal_decision_next_action_href_missing")
        if next_action_label != SIGNAL_EVIDENCE_CAPTURE_LABEL:
            issues.append("signal_decision_next_action_label_missing")
        if next_action_method != SIGNAL_EVIDENCE_CAPTURE_METHOD.lower():
            issues.append("signal_decision_next_action_method_missing")
    else:
        if next_action != "review_closed_signal_to_decision_claim":
            issues.append("signal_decision_next_action_review_closed_claim_missing")
        for key, value in (
            ("href", next_action_href),
            ("label", next_action_label),
            ("method", next_action_method),
            ("evidence_part", next_action_evidence_part),
        ):
            if value:
                issues.append(f"signal_decision_next_action_{key}_should_be_empty_after_acceptance")
    return {"contract_name": "ea.whole_project_signal_to_decision_receipt.verify.v1", "status": "pass" if not issues else "fail", "issues": issues}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the whole-project signal-to-decision receipt.")
    parser.add_argument("--receipt", default=str(DEFAULT_RECEIPT))
    args = parser.parse_args(argv)
    result = verify_whole_project_signal_to_decision_receipt(args.receipt)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
