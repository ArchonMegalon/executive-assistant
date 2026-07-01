from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from materialize_whole_project_scope_gap_audit import REQUIRED_SCOPE_AXES
from materialize_whole_project_scope_gap_audit import SCOPE_GAP_NEXT_ACTION
from materialize_whole_project_scope_gap_audit import SCOPE_GAP_NEXT_ACTION_HREF
from materialize_whole_project_scope_gap_audit import SCOPE_GAP_NEXT_ACTION_LABEL
from materialize_whole_project_scope_gap_audit import SCOPE_GAP_NEXT_ACTION_METHOD
from materialize_whole_project_scope_gap_audit import SCOPE_GAP_REVIEW_LABEL
from scripts.source_state_head import resolve_source_state_head
from scripts.source_state_head import resolve_source_worktree_fingerprint


DEFAULT_RECEIPT = REPO_ROOT / ".codex-studio" / "published" / "ea_whole_project_scope_gap_audit.generated.json"


def _load(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _verify_source_state(receipt: dict[str, Any], issues: list[str]) -> None:
    if receipt.get("head_semantics") != "source_state":
        issues.append("scope_gap_head_semantics_missing")
    if receipt.get("source_state_fingerprint_semantics") != "worktree_source_files_sha256_excluding_generated_only_paths":
        issues.append("scope_gap_source_state_fingerprint_semantics_missing")
    recorded_head = str(receipt.get("source_git_head") or "").strip()
    recorded_fingerprint = str(receipt.get("source_state_fingerprint") or "").strip()
    current_head = resolve_source_state_head(REPO_ROOT)
    current_fingerprint = resolve_source_worktree_fingerprint(REPO_ROOT)
    if not recorded_head:
        issues.append("scope_gap_source_git_head_missing")
    elif recorded_head != current_head and recorded_fingerprint != current_fingerprint:
        issues.append("scope_gap_source_git_head_stale")
    if not recorded_fingerprint:
        issues.append("scope_gap_source_state_fingerprint_missing")
    elif recorded_fingerprint != current_fingerprint:
        issues.append("scope_gap_source_state_fingerprint_stale")


def verify_whole_project_scope_gap_audit(receipt_path: str | Path) -> dict[str, Any]:
    receipt = _load(receipt_path)
    issues: list[str] = []
    _verify_source_state(receipt, issues)
    if receipt.get("goal_completion_claim_allowed") is True:
        issues.append("scope_gap_completion_overclaim")
    if dict(receipt.get("boundary_posture") or {}).get("ea_is_product_truth") is True:
        issues.append("scope_gap_ea_product_truth_overclaim")
    if not str(receipt.get("summary") or "").strip():
        issues.append("scope_gap_summary_missing")
    if str(receipt.get("next_action") or "").strip() != SCOPE_GAP_NEXT_ACTION:
        issues.append("scope_gap_next_action_drifted")
    if str(receipt.get("next_action_href") or "").strip() != SCOPE_GAP_NEXT_ACTION_HREF:
        issues.append("scope_gap_next_action_href_drifted")
    if str(receipt.get("next_action_label") or "").strip() != SCOPE_GAP_NEXT_ACTION_LABEL:
        issues.append("scope_gap_next_action_label_drifted")
    if str(receipt.get("next_action_method") or "").strip().lower() != SCOPE_GAP_NEXT_ACTION_METHOD:
        issues.append("scope_gap_next_action_method_drifted")
    if receipt.get("reviewed_against_current_product_spine") is True:
        if receipt.get("operator_review_accepted") is not True:
            issues.append("scope_gap_reviewed_requires_operator_review_accepted")
        if SCOPE_GAP_REVIEW_LABEL in list(receipt.get("remaining_external_proofs") or []):
            issues.append("scope_gap_reviewed_receipt_must_not_keep_review_remaining")
    else:
        if SCOPE_GAP_REVIEW_LABEL not in list(receipt.get("remaining_external_proofs") or []):
            issues.append("scope_gap_unreviewed_receipt_must_keep_review_remaining")
    review_surface = dict(receipt.get("review_capture_surface") or {})
    if review_surface.get("raw_input_not_persisted") is not True:
        issues.append("scope_gap_review_capture_raw_input_policy_missing")
    privacy = dict(review_surface.get("privacy_contract") or {})
    for key in ("raw_review_text_persisted", "raw_actor_identity_persisted", "raw_object_reference_persisted"):
        if privacy.get(key) is not False:
            issues.append(f"scope_gap_review_capture_privacy_drifted:{key}")
    axes = {dict(row).get("key"): row for row in receipt.get("scope_axes") or []}
    for key in REQUIRED_SCOPE_AXES:
        if key not in axes:
            issues.append(f"scope_gap_axis_missing:{key}")
    protected = set(dict(receipt.get("project_learning_goal") or {}).get("protected_signal_sources") or [])
    if "provider_runtime_failures" not in protected:
        issues.append("scope_gap_signal_to_decision_source_missing:provider_runtime_failures")
    return {"contract_name": "ea.whole_project_scope_gap_audit.verify.v1", "status": "pass" if not issues else "fail", "issues": issues}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the whole-project scope gap audit.")
    parser.add_argument("--receipt", default=str(DEFAULT_RECEIPT))
    args = parser.parse_args(argv)
    result = verify_whole_project_scope_gap_audit(args.receipt)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
