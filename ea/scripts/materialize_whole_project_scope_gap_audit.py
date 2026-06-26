from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[2]
PUBLISHED_ROOT = REPO_ROOT / ".codex-studio" / "published"
DEFAULT_RECEIPT = PUBLISHED_ROOT / "ea_whole_project_scope_gap_audit.generated.json"
DEFAULT_OFFICE_RECEIPT = PUBLISHED_ROOT / "ea_office_loop_goal.generated.json"
DEFAULT_ACCEPTANCE_RECEIPT = PUBLISHED_ROOT / "ea_executive_assistant_acceptance_evidence.generated.json"
DEFAULT_QUALITY_RECEIPT = PUBLISHED_ROOT / "ea_executive_assistant_quality_readiness.generated.json"
DEFAULT_ACTIVE_MEDIA_RECEIPT = PUBLISHED_ROOT / "active_media_ltd_goal_bundle.generated.json"
DEFAULT_SIGNAL_RECEIPT = PUBLISHED_ROOT / "ea_whole_project_signal_to_decision.generated.json"

REQUIRED_SCOPE_AXES = [
    "build_character_and_rules",
    "run_session",
    "privacy_retention",
]


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write(path: str | Path, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _goal(office: dict[str, Any], key: str, fallback: dict[str, Any]) -> dict[str, Any]:
    for row in office.get("additional_goals") or []:
        if dict(row).get("key") == key:
            return dict(row)
    return fallback


def _remaining(*receipts: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for receipt in receipts:
        for item in receipt.get("remaining_external_proofs") or []:
            if item not in values:
                values.append(str(item))
    for item in (
        "real whole-project scope gap audit reviewed against the current product spine",
        "real weekly signal-to-decision review accepted by the operator",
        "closed-loop signal-to-decision follow-through receipt accepted by the operator",
    ):
        if item not in values:
            values.append(item)
    return values


def materialize_whole_project_scope_gap_audit(
    *,
    receipt_path: str | Path,
    office_loop_receipt_path: str | Path,
    acceptance_evidence_receipt_path: str | Path,
    ea_quality_receipt_path: str | Path,
    active_media_receipt_path: str | Path,
    signal_to_decision_receipt_path: str | Path,
    generated_at: str = "",
) -> dict[str, Any]:
    office = _load(office_loop_receipt_path)
    acceptance = _load(acceptance_evidence_receipt_path)
    quality = _load(ea_quality_receipt_path)
    active = _load(active_media_receipt_path)
    signal = _load(signal_to_decision_receipt_path)
    scope_goal = _goal(
        office,
        "whole_project_scope_gap_audit",
        {"key": "whole_project_scope_gap_audit", "requires": [], "protected_scope_axes": REQUIRED_SCOPE_AXES},
    )
    learning_goal = _goal(
        office,
        "whole_project_signal_to_decision_closure",
        {
            "key": "whole_project_signal_to_decision_closure",
            "requires": ["weekly_operator_decision_packet"],
            "protected_signal_sources": ["provider_runtime_failures"],
        },
    )
    receipt = {
        "contract_name": "ea.whole_project_scope_gap_audit.v1",
        "status": "ready_local_audit",
        "generated_at": generated_at or _now(),
        "goal_completion_claim_allowed": False,
        "public_or_premium_claim_allowed": False,
        "boundary_posture": {
            "ea_is_product_truth": False,
            "local_scope_audit_not_canonical_product_truth": True,
        },
        "scope_goal": scope_goal,
        "project_learning_goal": learning_goal,
        "scope_axes": [
            {
                "key": key,
                "status": "mapped_from_mirrored_sources",
                "source_files": [".codex-design/product/README.md", ".codex-design/repo/IMPLEMENTATION_SCOPE.md"],
                "next_external_or_human_proof": "operator_review_against_current_product_spine",
            }
            for key in REQUIRED_SCOPE_AXES
        ],
        "evidence_receipts": {
            "office_loop": {"contract_name": office.get("contract_name"), "status": office.get("status")},
            "executive_assistant_acceptance_evidence": {
                "contract_name": acceptance.get("contract_name"),
                "status": acceptance.get("status"),
            },
            "executive_assistant_quality": {"contract_name": quality.get("contract_name"), "status": quality.get("status")},
            "active_media_ltd": {"contract_name": active.get("contract_name"), "status": active.get("status")},
            "signal_to_decision": {"contract_name": signal.get("contract_name"), "status": signal.get("status")},
        },
        "remaining_external_proofs": _remaining(office, acceptance, quality, active, signal),
    }
    _write(receipt_path, receipt)
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Materialize the whole-project scope gap audit.")
    parser.add_argument("--receipt", default=str(DEFAULT_RECEIPT))
    parser.add_argument("--office-loop-receipt", default=str(DEFAULT_OFFICE_RECEIPT))
    parser.add_argument("--acceptance-evidence-receipt", default=str(DEFAULT_ACCEPTANCE_RECEIPT))
    parser.add_argument("--ea-quality-receipt", default=str(DEFAULT_QUALITY_RECEIPT))
    parser.add_argument("--active-media-receipt", default=str(DEFAULT_ACTIVE_MEDIA_RECEIPT))
    parser.add_argument("--signal-to-decision-receipt", default=str(DEFAULT_SIGNAL_RECEIPT))
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args(argv)
    receipt = materialize_whole_project_scope_gap_audit(
        receipt_path=args.receipt,
        office_loop_receipt_path=args.office_loop_receipt,
        acceptance_evidence_receipt_path=args.acceptance_evidence_receipt,
        ea_quality_receipt_path=args.ea_quality_receipt,
        active_media_receipt_path=args.active_media_receipt,
        signal_to_decision_receipt_path=args.signal_to_decision_receipt,
        generated_at=args.generated_at,
    )
    print(json.dumps({"status": receipt["status"], "receipt": str(args.receipt)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
