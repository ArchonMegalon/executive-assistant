from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.source_state_head import resolve_source_state_head  # noqa: E402
from scripts.source_state_head import resolve_source_worktree_fingerprint  # noqa: E402

PUBLISHED_ROOT = REPO_ROOT / ".codex-studio" / "published"
DEFAULT_RECEIPT = PUBLISHED_ROOT / "ea_whole_project_signal_to_decision.generated.json"
DEFAULT_OFFICE_RECEIPT = PUBLISHED_ROOT / "ea_office_loop_goal.generated.json"
DEFAULT_ACCEPTANCE_RECEIPT = PUBLISHED_ROOT / "ea_executive_assistant_acceptance_evidence.generated.json"
DEFAULT_QUALITY_RECEIPT = PUBLISHED_ROOT / "ea_executive_assistant_quality_readiness.generated.json"
REQUIRED_SIGNAL_SOURCES = [
    "real_usage_telemetry",
    "support_and_recovery_cases",
    "feedback_and_crash_reports",
    "public_or_premium_publication_reactions",
    "provider_runtime_failures",
    "audiobook_and_media_acceptance",
    "telegram_whatsapp_email_channel_friction",
    "release_install_update_friction",
    "privacy_or_boundary_incidents",
]
SIGNAL_EVIDENCE_CAPTURE_PATH = "/admin/actions/signal-to-decision-evidence"
SIGNAL_EVIDENCE_CAPTURE_METHOD = "POST"
SIGNAL_EVIDENCE_CAPTURE_FORM_FIELDS = ["evidence_part", "source_kind", "evidence", "packet_ref"]
SIGNAL_EVIDENCE_CAPTURE_LABEL = "Record a signal-loop outcome"
SIGNAL_EVIDENCE_CAPTURE_FORM_METHOD = "GET"
SIGNAL_OPERATOR_ACTION_KEY = "weekly_signal_to_decision_review_acceptance"
SIGNAL_EVIDENCE_PARTS = {
    "review": {
        "label": "real weekly signal-to-decision review accepted by the operator",
        "accepted_field": "real_weekly_operator_review_accepted",
        "receipt_field": "operator_review",
        "hash_field": "review_sha256",
        "input_field": "review",
        "next_action": "record_redacted_signal_review_acceptance",
    },
    "followthrough": {
        "label": "closed-loop signal-to-decision follow-through receipt accepted by the operator",
        "accepted_field": "closed_loop_followthrough_receipt_verified",
        "receipt_field": "followthrough_receipt",
        "hash_field": "followthrough_sha256",
        "input_field": "followthrough",
        "next_action": "record_redacted_signal_followthrough_acceptance",
    },
}


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


def _source_state_fields() -> dict[str, str]:
    return {
        "source_git_head": resolve_source_state_head(REPO_ROOT),
        "head_semantics": "source_state",
        "source_state_fingerprint": resolve_source_worktree_fingerprint(REPO_ROOT),
        "source_state_fingerprint_semantics": "worktree_source_files_sha256_excluding_generated_only_paths",
    }


def _empty_signal_evidence_row(*, hash_field: str, raw_field: str) -> dict[str, Any]:
    return {
        "accepted": False,
        "status": "missing_or_invalid",
        "source_kind": "",
        hash_field: "",
        "actor_sha256": "",
        "packet_ref_sha256": "",
        "recorded_at": "",
        raw_field: False,
        "raw_actor_exposed": False,
        "raw_packet_ref_exposed": False,
    }


def _normalized_existing_signal_evidence_row(
    row: dict[str, Any],
    *,
    hash_field: str,
    raw_field: str,
) -> dict[str, Any]:
    normalized = _empty_signal_evidence_row(hash_field=hash_field, raw_field=raw_field)
    normalized.update(dict(row or {}))
    if normalized.get("accepted") is True:
        normalized["status"] = "accepted_redacted"
    normalized[raw_field] = False
    normalized["raw_actor_exposed"] = False
    normalized["raw_packet_ref_exposed"] = False
    return normalized


def _signal_evidence_row_from_input(
    payload: dict[str, Any],
    *,
    input_field: str,
    hash_field: str,
    raw_field: str,
) -> dict[str, Any]:
    accepted = bool(payload.get("accepted"))
    evidence = str(payload.get(input_field) or "")
    actor = str(payload.get("actor") or "")
    packet_ref = str(payload.get("packet_ref") or "")
    valid = accepted and bool(evidence and actor and packet_ref)
    return {
        "accepted": valid,
        "status": "accepted_redacted" if valid else "missing_or_invalid",
        "source_kind": str(payload.get("source_kind") or ""),
        hash_field: _hash(evidence),
        "actor_sha256": _hash(actor),
        "packet_ref_sha256": _hash(packet_ref),
        "recorded_at": str(payload.get("recorded_at") or ""),
        raw_field: False,
        "raw_actor_exposed": False,
        "raw_packet_ref_exposed": False,
    }


def _existing_signal_evidence_rows(receipt_path: Path, preserve_existing: bool) -> tuple[dict[str, Any], dict[str, Any]]:
    review = _empty_signal_evidence_row(hash_field="review_sha256", raw_field="raw_review_exposed")
    follow = _empty_signal_evidence_row(hash_field="followthrough_sha256", raw_field="raw_followthrough_exposed")
    if not preserve_existing or not receipt_path.is_file():
        return review, follow
    try:
        existing = _load(receipt_path)
    except Exception:
        return review, follow
    existing_review = dict(existing.get("operator_review") or {})
    existing_follow = dict(existing.get("followthrough_receipt") or {})
    if existing_review.get("accepted") is True:
        review = _normalized_existing_signal_evidence_row(
            existing_review,
            hash_field="review_sha256",
            raw_field="raw_review_exposed",
        )
    if existing_follow.get("accepted") is True:
        follow = _normalized_existing_signal_evidence_row(
            existing_follow,
            hash_field="followthrough_sha256",
            raw_field="raw_followthrough_exposed",
        )
    return review, follow


def _source_row(key: str) -> dict[str, Any]:
    return {
        "key": key,
        "status": "mapped_from_sources",
        "owner_truth_plane": "operator_review_required",
        "journey_or_release_gate_mapping": "weekly_signal_to_decision_packet",
    }


def _signal_evidence_capture_surface() -> dict[str, Any]:
    return {
        "method": SIGNAL_EVIDENCE_CAPTURE_METHOD,
        "path": SIGNAL_EVIDENCE_CAPTURE_PATH,
        "form_method": SIGNAL_EVIDENCE_CAPTURE_FORM_METHOD,
        "form_path": SIGNAL_EVIDENCE_CAPTURE_PATH,
        "admin_only": True,
        "operator_context_required": True,
        "required_form_fields": SIGNAL_EVIDENCE_CAPTURE_FORM_FIELDS,
        "prefill_query_fields": ["evidence_part", "return_to"],
        "valid_evidence_parts": list(SIGNAL_EVIDENCE_PARTS),
        "server_actor_source": "authenticated_operator_context",
        "raw_input_not_persisted": True,
        "stored_evidence_shape": "sha256_only",
        "privacy_contract": {
            "raw_review_text_persisted": False,
            "raw_followthrough_text_persisted": False,
            "raw_actor_identity_persisted": False,
            "raw_packet_reference_persisted": False,
            "credential_values_persisted": False,
        },
        "claim_boundary": "captures_redacted_signal_to_decision_acceptance_only_not_queue_or_release_truth",
    }


def _signal_evidence_form_href(evidence_part: str, *, return_to: str = "/admin/goals") -> str:
    query = {"return_to": return_to}
    if evidence_part:
        query["evidence_part"] = evidence_part
    return f"{SIGNAL_EVIDENCE_CAPTURE_PATH}?{urllib.parse.urlencode(query)}"


def _signal_evidence_capture_requirements(*, review_accepted: bool, follow_accepted: bool) -> list[dict[str, Any]]:
    accepted_by_part = {"review": review_accepted, "followthrough": follow_accepted}
    rows: list[dict[str, Any]] = []
    for part, spec in SIGNAL_EVIDENCE_PARTS.items():
        accepted = bool(accepted_by_part[part])
        rows.append(
            {
                "evidence_part": part,
                "label": spec["label"],
                "status": "accepted_redacted" if accepted else "pending_real_world_evidence",
                "accepted": accepted,
                "capture_method": SIGNAL_EVIDENCE_CAPTURE_METHOD,
                "capture_path": SIGNAL_EVIDENCE_CAPTURE_PATH,
                "form_method": SIGNAL_EVIDENCE_CAPTURE_FORM_METHOD,
                "form_href": _signal_evidence_form_href(part),
                "required_form_fields": SIGNAL_EVIDENCE_CAPTURE_FORM_FIELDS,
                "server_actor_source": "authenticated_operator_context",
                "raw_input_not_persisted": True,
                "stored_evidence_shape": "sha256_only",
                "raw_evidence_exposed": False,
                "raw_actor_exposed": False,
                "raw_packet_ref_exposed": False,
                "next_action": (
                    f"review_redacted_signal_to_decision_evidence:{part}"
                    if accepted
                    else str(spec["next_action"])
                ),
                "next_action_form_href": _signal_evidence_form_href(part),
                "next_action_form_label": SIGNAL_EVIDENCE_CAPTURE_LABEL,
                "next_action_form_method": SIGNAL_EVIDENCE_CAPTURE_FORM_METHOD.lower(),
                "claim_boundary": "does_not_prove_closed_signal_to_decision_loop_until_review_and_followthrough_are_accepted",
            }
        )
    return rows


def _operator_action_packet(
    *,
    next_action: str,
    next_action_evidence_part: str,
    review_accepted: bool,
    follow_accepted: bool,
) -> dict[str, Any]:
    if not next_action_evidence_part:
        return {
            "status": "not_required",
            "user_action_required": False,
            "action_required_reason": "",
            "next_action": "review_closed_signal_to_decision_claim",
            "next_action_href": "",
            "next_action_label": "",
            "next_action_method": "",
            "next_action_form_href": "",
            "next_action_form_label": "",
            "next_action_form_method": "",
            "instruction": "Both redacted weekly review and follow-through evidence are recorded; review the closed signal-to-decision claim before widening product claims.",
            "delivery_policy": "queue_only",
            "telegram_push_allowed": False,
            "interruption_budget": "none",
            "quiet_hours_respected": True,
            "non_action_progress_push_allowed": False,
            "irreversible_actions_consent_gated": True,
            "raw_acceptance_text_exposed": False,
            "raw_actor_identity_exposed": False,
            "raw_object_reference_exposed": False,
            "raw_private_context_exposed": False,
        }
    requirement = SIGNAL_EVIDENCE_PARTS[next_action_evidence_part]
    instruction = (
        "Record redacted evidence that the weekly signal-to-decision review was actually reviewed."
        if next_action_evidence_part == "review"
        else "Record redacted evidence that one reviewed signal led to a verified follow-through receipt."
    )
    return {
        "status": "action_required",
        "user_action_required": True,
        "action_required_reason": "real_world_acceptance_missing",
        "next_action": next_action,
        "next_action_href": SIGNAL_EVIDENCE_CAPTURE_PATH,
        "next_action_label": SIGNAL_EVIDENCE_CAPTURE_LABEL,
        "next_action_method": SIGNAL_EVIDENCE_CAPTURE_METHOD.lower(),
        "next_action_form_href": _signal_evidence_form_href(next_action_evidence_part),
        "next_action_form_label": SIGNAL_EVIDENCE_CAPTURE_LABEL,
        "next_action_form_method": SIGNAL_EVIDENCE_CAPTURE_FORM_METHOD.lower(),
        "next_action_evidence_part": next_action_evidence_part,
        "instruction": instruction,
        "required_next_receipt": str(requirement["label"]),
        "required_form_fields": SIGNAL_EVIDENCE_CAPTURE_FORM_FIELDS,
        "accepted_parts": {
            "review": review_accepted,
            "followthrough": follow_accepted,
        },
        "delivery_policy": "action_required_only",
        "telegram_push_allowed": True,
        "interruption_budget": "action_required",
        "quiet_hours_respected": True,
        "non_action_progress_push_allowed": False,
        "irreversible_actions_consent_gated": True,
        "claim_boundary": "does_not_prove_closed_signal_to_decision_loop_until_review_and_followthrough_are_accepted",
        "raw_acceptance_text_exposed": False,
        "raw_actor_identity_exposed": False,
        "raw_object_reference_exposed": False,
        "raw_private_context_exposed": False,
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
    active_media_receipt_path: str | Path | None = None,
    input_payload: dict[str, Any] | None = None,
    generated_at: str = "",
    preserve_existing: bool = True,
) -> dict[str, Any]:
    office = _load(office_loop_receipt_path)
    acceptance = _load(acceptance_evidence_receipt_path)
    quality = _load(ea_quality_receipt_path)
    active_media = _load(active_media_receipt_path) if active_media_receipt_path else {}
    target = Path(receipt_path)
    payload = input_payload or {}
    stored_review, stored_follow = _existing_signal_evidence_rows(target, preserve_existing)
    review = dict(payload.get("review") or {})
    follow = dict(payload.get("followthrough") or {})
    review_row = (
        _signal_evidence_row_from_input(
            review,
            input_field="review",
            hash_field="review_sha256",
            raw_field="raw_review_exposed",
        )
        if review
        else stored_review
    )
    follow_row = (
        _signal_evidence_row_from_input(
            follow,
            input_field="followthrough",
            hash_field="followthrough_sha256",
            raw_field="raw_followthrough_exposed",
        )
        if follow
        else stored_follow
    )
    review_accepted = bool(review_row.get("accepted"))
    follow_accepted = bool(follow_row.get("accepted"))
    if not review_accepted:
        next_action = str(SIGNAL_EVIDENCE_PARTS["review"]["next_action"])
        next_action_evidence_part = "review"
    elif not follow_accepted:
        next_action = str(SIGNAL_EVIDENCE_PARTS["followthrough"]["next_action"])
        next_action_evidence_part = "followthrough"
    else:
        next_action = "review_closed_signal_to_decision_claim"
        next_action_evidence_part = ""
    receipt = {
        "contract_name": "ea.whole_project_signal_to_decision_receipt.v1",
        "generated_by": "ea/scripts/materialize_whole_project_signal_to_decision_receipt.py",
        **_source_state_fields(),
        "status": "ready_real_signal_to_decision_closure"
        if review_accepted and follow_accepted
        else "partial_real_signal_to_decision_closure"
        if review_accepted or follow_accepted
        else "ready_local_packet_pending_operator_acceptance",
        "generated_at": generated_at or _now(),
        "goal_completion_claim_allowed": False,
        "queue_truth_claim_allowed": False,
        "release_authority_claim_allowed": False,
        "next_action": next_action,
        "operator_action_key": SIGNAL_OPERATOR_ACTION_KEY if next_action_evidence_part else "",
        "next_action_href": SIGNAL_EVIDENCE_CAPTURE_PATH if next_action_evidence_part else "",
        "next_action_label": SIGNAL_EVIDENCE_CAPTURE_LABEL if next_action_evidence_part else "",
        "next_action_method": SIGNAL_EVIDENCE_CAPTURE_METHOD.lower() if next_action_evidence_part else "",
        "next_action_form_href": _signal_evidence_form_href(next_action_evidence_part) if next_action_evidence_part else "",
        "next_action_form_label": SIGNAL_EVIDENCE_CAPTURE_LABEL if next_action_evidence_part else "",
        "next_action_form_method": SIGNAL_EVIDENCE_CAPTURE_FORM_METHOD.lower() if next_action_evidence_part else "",
        "next_action_evidence_part": next_action_evidence_part,
        "operator_action_packet": _operator_action_packet(
            next_action=next_action,
            next_action_evidence_part=next_action_evidence_part,
            review_accepted=review_accepted,
            follow_accepted=follow_accepted,
        ),
        "real_weekly_operator_review_accepted": review_accepted,
        "closed_loop_followthrough_receipt_verified": follow_accepted,
        "signal_evidence_capture_surface": _signal_evidence_capture_surface(),
        "signal_evidence_capture_requirements": _signal_evidence_capture_requirements(
            review_accepted=review_accepted,
            follow_accepted=follow_accepted,
        ),
        "boundary_posture": {
            "ea_is_product_truth": False,
            "local_signal_synthesis_not_canonical_queue_or_release_truth": True,
        },
        "signal_sources": [_source_row(key) for key in REQUIRED_SIGNAL_SOURCES],
        "decision_packet": {
            "decision_items": [
                {"key": "provider_runtime_recovery", "source": "provider_runtime_failures"},
                {"key": "audiobook_acceptance", "source": "audiobook_and_media_acceptance"},
                {"key": "privacy_boundary_review", "source": "privacy_or_boundary_incidents"},
            ]
        },
        "operator_review": review_row,
        "followthrough_receipt": follow_row,
        "privacy": {
            "raw_review_text_exposed": False,
            "raw_followthrough_text_exposed": False,
            "raw_actor_identity_exposed": False,
            "raw_packet_reference_exposed": False,
            "raw_private_context_exposed": False,
        },
        "evidence_receipts": {
            "office_loop": {"contract_name": office.get("contract_name"), "status": office.get("status")},
            "executive_assistant_acceptance_evidence": {
                "contract_name": acceptance.get("contract_name"),
                "status": acceptance.get("status"),
            },
            "executive_assistant_quality": {"contract_name": quality.get("contract_name"), "status": quality.get("status")},
            "active_media": {
                "contract_name": active_media.get("contract_name"),
                "status": active_media.get("status"),
            },
        },
        "remaining_external_proofs": _remaining(
            office,
            acceptance,
            quality,
            active_media,
            accepted=review_accepted,
            followed=follow_accepted,
        ),
    }
    _write(target, receipt)
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Materialize the whole-project signal-to-decision receipt.")
    parser.add_argument("--receipt", default=str(DEFAULT_RECEIPT))
    parser.add_argument("--office-loop-receipt", default=str(DEFAULT_OFFICE_RECEIPT))
    parser.add_argument("--acceptance-evidence-receipt", default=str(DEFAULT_ACCEPTANCE_RECEIPT))
    parser.add_argument("--ea-quality-receipt", default=str(DEFAULT_QUALITY_RECEIPT))
    parser.add_argument("--active-media-receipt", default="")
    parser.add_argument("--input")
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args(argv)
    input_payload = _load(args.input) if args.input else None
    receipt = materialize_whole_project_signal_to_decision_receipt(
        receipt_path=args.receipt,
        office_loop_receipt_path=args.office_loop_receipt,
        acceptance_evidence_receipt_path=args.acceptance_evidence_receipt,
        ea_quality_receipt_path=args.ea_quality_receipt,
        active_media_receipt_path=args.active_media_receipt,
        input_payload=input_payload,
        generated_at=args.generated_at,
        preserve_existing=not args.reset,
    )
    print(json.dumps({"status": receipt["status"], "receipt": str(args.receipt)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
