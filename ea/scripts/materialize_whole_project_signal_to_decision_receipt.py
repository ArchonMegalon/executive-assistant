from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[2]
PUBLISHED_ROOT = REPO_ROOT / ".codex-studio" / "published"
DEFAULT_RECEIPT = PUBLISHED_ROOT / "ea_whole_project_signal_to_decision.generated.json"
DEFAULT_OFFICE_RECEIPT = PUBLISHED_ROOT / "ea_office_loop_goal.generated.json"
DEFAULT_ACCEPTANCE_RECEIPT = PUBLISHED_ROOT / "ea_executive_assistant_acceptance_evidence.generated.json"
DEFAULT_QUALITY_RECEIPT = PUBLISHED_ROOT / "ea_executive_assistant_quality_readiness.generated.json"
DEFAULT_ACTIVE_MEDIA_RECEIPT = PUBLISHED_ROOT / "active_media_ltd_goal_bundle.generated.json"

REQUIRED_SIGNAL_SOURCES = [
    "real_usage_telemetry",
    "support_and_recovery_cases",
    "feedback_and_crash_reports",
    "public_or_premium_publication_reactions",
    "provider_runtime_failures",
    "audiobook_and_media_acceptance",
    "manfred_spoken_conversation_acceptance",
    "telegram_whatsapp_email_channel_friction",
    "release_install_update_friction",
    "privacy_or_boundary_incidents",
]


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write(path: str | Path, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest() if value else ""


def _source_row(key: str) -> dict[str, Any]:
    return {
        "key": key,
        "status": "mapped_from_sources",
        "owner_truth_plane": "operator_review_required",
        "journey_or_release_gate_mapping": "weekly_signal_to_decision_packet",
    }


def _remaining(*receipts: dict[str, Any], accepted: bool, followed: bool) -> list[str]:
    values: list[str] = []
    for receipt in receipts:
        for item in receipt.get("remaining_external_proofs") or []:
            if item not in values:
                values.append(str(item))
    if not accepted and "real weekly signal-to-decision review accepted by the operator" not in values:
        values.append("real weekly signal-to-decision review accepted by the operator")
    if not followed and "closed-loop signal-to-decision follow-through receipt accepted by the operator" not in values:
        values.append("closed-loop signal-to-decision follow-through receipt accepted by the operator")
    return values


def materialize_whole_project_signal_to_decision_receipt(
    *,
    receipt_path: str | Path,
    office_loop_receipt_path: str | Path,
    acceptance_evidence_receipt_path: str | Path,
    ea_quality_receipt_path: str | Path,
    active_media_receipt_path: str | Path,
    input_payload: dict[str, Any] | None = None,
    generated_at: str = "",
) -> dict[str, Any]:
    office = _load(office_loop_receipt_path)
    acceptance = _load(acceptance_evidence_receipt_path)
    quality = _load(ea_quality_receipt_path)
    active = _load(active_media_receipt_path)
    payload = input_payload or {}
    review = dict(payload.get("review") or {})
    follow = dict(payload.get("followthrough") or {})
    review_accepted = bool(review.get("accepted"))
    follow_accepted = bool(follow.get("accepted"))
    receipt = {
        "contract_name": "ea.whole_project_signal_to_decision_receipt.v1",
        "status": "ready_real_signal_to_decision_closure"
        if review_accepted and follow_accepted
        else "ready_local_packet_pending_operator_acceptance",
        "generated_at": generated_at or _now(),
        "goal_completion_claim_allowed": False,
        "queue_truth_claim_allowed": False,
        "release_authority_claim_allowed": False,
        "real_weekly_operator_review_accepted": review_accepted,
        "closed_loop_followthrough_receipt_verified": follow_accepted,
        "boundary_posture": {
            "ea_is_product_truth": False,
            "local_signal_synthesis_not_canonical_queue_or_release_truth": True,
        },
        "signal_sources": [_source_row(key) for key in REQUIRED_SIGNAL_SOURCES],
        "decision_packet": {
            "decision_items": [
                {"key": "provider_runtime_recovery", "source": "provider_runtime_failures"},
                {"key": "audiobook_acceptance", "source": "audiobook_and_media_acceptance"},
                {"key": "spoken_conversation_acceptance", "source": "manfred_spoken_conversation_acceptance"},
                {"key": "privacy_boundary_review", "source": "privacy_or_boundary_incidents"},
            ]
        },
        "operator_review": {
            "accepted": review_accepted,
            "source_kind": review.get("source_kind", ""),
            "review_sha256": _hash(str(review.get("review") or "")),
            "actor_sha256": _hash(str(review.get("actor") or "")),
            "packet_ref_sha256": _hash(str(review.get("packet_ref") or "")),
            "recorded_at": review.get("recorded_at", ""),
        },
        "followthrough_receipt": {
            "accepted": follow_accepted,
            "source_kind": follow.get("source_kind", ""),
            "followthrough_sha256": _hash(str(follow.get("followthrough") or "")),
            "actor_sha256": _hash(str(follow.get("actor") or "")),
            "packet_ref_sha256": _hash(str(follow.get("packet_ref") or "")),
            "recorded_at": follow.get("recorded_at", ""),
        },
        "evidence_receipts": {
            "office_loop": {"contract_name": office.get("contract_name"), "status": office.get("status")},
            "executive_assistant_acceptance_evidence": {
                "contract_name": acceptance.get("contract_name"),
                "status": acceptance.get("status"),
            },
            "executive_assistant_quality": {"contract_name": quality.get("contract_name"), "status": quality.get("status")},
            "active_media_ltd": {"contract_name": active.get("contract_name"), "status": active.get("status")},
        },
        "remaining_external_proofs": _remaining(
            office,
            acceptance,
            quality,
            active,
            accepted=review_accepted,
            followed=follow_accepted,
        ),
    }
    _write(receipt_path, receipt)
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Materialize the whole-project signal-to-decision receipt.")
    parser.add_argument("--receipt", default=str(DEFAULT_RECEIPT))
    parser.add_argument("--office-loop-receipt", default=str(DEFAULT_OFFICE_RECEIPT))
    parser.add_argument("--acceptance-evidence-receipt", default=str(DEFAULT_ACCEPTANCE_RECEIPT))
    parser.add_argument("--ea-quality-receipt", default=str(DEFAULT_QUALITY_RECEIPT))
    parser.add_argument("--active-media-receipt", default=str(DEFAULT_ACTIVE_MEDIA_RECEIPT))
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args(argv)
    receipt = materialize_whole_project_signal_to_decision_receipt(
        receipt_path=args.receipt,
        office_loop_receipt_path=args.office_loop_receipt,
        acceptance_evidence_receipt_path=args.acceptance_evidence_receipt,
        ea_quality_receipt_path=args.ea_quality_receipt,
        active_media_receipt_path=args.active_media_receipt,
        generated_at=args.generated_at,
    )
    print(json.dumps({"status": receipt["status"], "receipt": str(args.receipt)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
