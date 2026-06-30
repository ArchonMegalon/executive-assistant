from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.source_state_head import resolve_source_state_head  # noqa: E402
from scripts.source_state_head import resolve_source_worktree_fingerprint  # noqa: E402
DEFAULT_RECEIPT = REPO_ROOT / ".codex-studio" / "published" / "ea_executive_assistant_acceptance_evidence.generated.json"

REQUIRED_ACCEPTANCE_KEYS = [
    "real_daily_morning_brief_accepted",
    "real_decision_cleared",
    "real_commitment_recovered_or_closed",
    "real_approved_action_audited",
    "real_provider_failure_recovered",
]

REMAINING_PROOF_LABELS = {
    "real_daily_morning_brief_accepted": "real daily morning brief acceptance",
    "real_decision_cleared": "real decision cleared by the principal or operator",
    "real_commitment_recovered_or_closed": "real commitment recovered or closed with an evidence receipt",
    "real_approved_action_audited": "real approved outbound action with audit trail",
    "real_provider_failure_recovered": "real provider failure recovered with operator-grade reason",
}

ACCEPTANCE_CAPTURE_PATH = "/admin/actions/acceptance-evidence"
ACCEPTANCE_CAPTURE_METHOD = "POST"
ACCEPTANCE_CAPTURE_FORM_FIELDS = ["proof_key", "source_kind", "evidence", "object_ref"]
ACCEPTANCE_CAPTURE_LABEL = "Record a real-use outcome"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest() if value else ""


def _source_state_fields() -> dict[str, str]:
    return {
        "source_git_head": resolve_source_state_head(REPO_ROOT),
        "head_semantics": "source_state",
        "source_state_fingerprint": resolve_source_worktree_fingerprint(REPO_ROOT),
        "source_state_fingerprint_semantics": "worktree_source_files_sha256_excluding_generated_only_paths",
    }


def _write(path: str | Path, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _empty_row() -> dict[str, Any]:
    return {
        "accepted": False,
        "status": "missing_or_invalid",
        "source_kind": "unknown",
        "recorded_at": "",
        "evidence_sha256": "",
        "actor_sha256": "",
        "object_ref_sha256": "",
        "raw_evidence_exposed": False,
        "raw_actor_exposed": False,
        "raw_object_ref_exposed": False,
    }


def _normalized_existing_row(row: dict[str, Any]) -> dict[str, Any]:
    normalized = _empty_row()
    normalized.update(dict(row or {}))
    if normalized.get("accepted") is True:
        normalized["status"] = "accepted_redacted"
    normalized["raw_evidence_exposed"] = False
    normalized["raw_actor_exposed"] = False
    normalized["raw_object_ref_exposed"] = False
    return normalized


def _row_from_proof(proof: dict[str, Any]) -> dict[str, Any]:
    accepted = bool(proof.get("accepted"))
    evidence = str(proof.get("evidence") or "")
    actor = str(proof.get("actor") or "")
    object_ref = str(proof.get("object_ref") or "")
    valid = accepted and bool(evidence and actor and object_ref)
    return {
        "accepted": valid,
        "status": "accepted_redacted" if valid else "missing_or_invalid",
        "source_kind": str(proof.get("source") or "unknown"),
        "recorded_at": str(proof.get("recorded_at") or ""),
        "evidence_sha256": _hash(evidence),
        "actor_sha256": _hash(actor),
        "object_ref_sha256": _hash(object_ref),
        "raw_evidence_exposed": False,
        "raw_actor_exposed": False,
        "raw_object_ref_exposed": False,
    }


def _acceptance_capture_surface() -> dict[str, Any]:
    return {
        "method": ACCEPTANCE_CAPTURE_METHOD,
        "path": ACCEPTANCE_CAPTURE_PATH,
        "admin_only": True,
        "operator_context_required": True,
        "required_form_fields": ACCEPTANCE_CAPTURE_FORM_FIELDS,
        "server_actor_source": "authenticated_operator_context",
        "raw_input_not_persisted": True,
        "stored_evidence_shape": "sha256_only",
        "privacy_contract": {
            "raw_acceptance_text_persisted": False,
            "raw_actor_identity_persisted": False,
            "raw_object_reference_persisted": False,
            "credential_values_persisted": False,
        },
        "claim_boundary": "capture_surface_collects_redacted_acceptance_evidence_only_not_goal_completion",
    }


def _acceptance_capture_requirement(key: str, row: dict[str, Any]) -> dict[str, Any]:
    accepted = dict(row or {}).get("accepted") is True
    user_action_required = not accepted
    return {
        "key": key,
        "label": REMAINING_PROOF_LABELS[key],
        "status": "accepted_redacted" if accepted else "pending_real_world_evidence",
        "accepted": accepted,
        "capture_method": ACCEPTANCE_CAPTURE_METHOD,
        "capture_path": ACCEPTANCE_CAPTURE_PATH,
        "proof_key": key,
        "required_form_fields": ACCEPTANCE_CAPTURE_FORM_FIELDS,
        "server_actor_source": "authenticated_operator_context",
        "raw_input_not_persisted": True,
        "stored_evidence_shape": "sha256_only",
        "raw_evidence_exposed": False,
        "raw_actor_exposed": False,
        "raw_object_ref_exposed": False,
        "user_action_required": user_action_required,
        "delivery_policy": "action_required_only" if user_action_required else "queue_only",
        "telegram_push_allowed": user_action_required,
        "interruption_budget": "action_required" if user_action_required else "none",
        "quiet_hours_respected": True,
        "non_action_progress_push_allowed": False,
        "irreversible_actions_consent_gated": True,
        "next_action": (
            f"review_redacted_acceptance_evidence:{key}"
            if accepted
            else f"record_redacted_acceptance_evidence:{key}"
        ),
        "claim_boundary": "does_not_prove_good_executive_assistant_until_all_required_acceptance_keys_are_accepted",
    }


def acceptance_capture_requirements(rows: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [_acceptance_capture_requirement(key, dict(rows.get(key) or {})) for key in REQUIRED_ACCEPTANCE_KEYS]


def _existing_rows(receipt_path: Path, preserve_existing: bool) -> dict[str, dict[str, Any]]:
    if not preserve_existing or not receipt_path.is_file():
        return {}
    try:
        existing = _load(receipt_path)
    except Exception:
        return {}
    rows = existing.get("acceptance_keys")
    return dict(rows) if isinstance(rows, dict) else {}


def materialize_executive_assistant_acceptance_evidence(
    *,
    receipt_path: str | Path,
    input_payload: dict[str, Any] | None = None,
    generated_at: str = "",
    preserve_existing: bool = True,
) -> dict[str, Any]:
    target = Path(receipt_path)
    rows: dict[str, dict[str, Any]] = {key: _empty_row() for key in REQUIRED_ACCEPTANCE_KEYS}
    for key, row in _existing_rows(target, preserve_existing).items():
        if key in rows and dict(row).get("accepted") is True:
            rows[key] = _normalized_existing_row(dict(row))
    for proof in list((input_payload or {}).get("proofs") or []):
        if not isinstance(proof, dict):
            continue
        key = str(proof.get("key") or "")
        if key in rows:
            rows[key] = _row_from_proof(proof)
    accepted_keys = [key for key in REQUIRED_ACCEPTANCE_KEYS if rows[key].get("accepted") is True]
    blocked_keys = [key for key in REQUIRED_ACCEPTANCE_KEYS if key not in accepted_keys]
    status = (
        "ready_real_world_acceptance_evidence"
        if not blocked_keys
        else "partial_real_world_acceptance_evidence"
        if accepted_keys
        else "blocked_missing_real_world_acceptance_evidence"
    )
    next_proof_key = blocked_keys[0] if blocked_keys else ""
    next_action = "collect_redacted_real_world_acceptance_evidence" if blocked_keys else "review_good_executive_assistant_claim"
    receipt = {
        "contract_name": "ea.executive_assistant_acceptance_evidence.v1",
        "status": status,
        "generated_at": generated_at or _now(),
        "generated_by": "ea/scripts/materialize_executive_assistant_acceptance_evidence.py",
        **_source_state_fields(),
        "goal_completion_claim_allowed": False,
        "public_or_premium_claim_allowed": False,
        "acceptance_keys": rows,
        "acceptance_capture_surface": _acceptance_capture_surface(),
        "acceptance_capture_requirements": acceptance_capture_requirements(rows),
        "accepted_keys": accepted_keys,
        "blocked_keys": blocked_keys,
        "real_daily_use_verified": not blocked_keys,
        "real_principal_acceptance_verified": rows["real_daily_morning_brief_accepted"].get("accepted") is True,
        "real_operator_acceptance_verified": any(rows[key].get("accepted") is True for key in REQUIRED_ACCEPTANCE_KEYS if key != "real_daily_morning_brief_accepted"),
        "real_provider_recovery_verified": rows["real_provider_failure_recovered"].get("accepted") is True,
        "remaining_external_proofs": [REMAINING_PROOF_LABELS[key] for key in blocked_keys],
        "privacy": {
            "credential_values_exposed": False,
            "raw_acceptance_text_exposed": False,
            "raw_actor_identity_exposed": False,
            "raw_object_reference_exposed": False,
            "raw_private_context_exposed": False,
        },
        "source_input": {"provided": input_payload is not None},
        "rejected_input_count": 0,
        "next_action": next_action,
        "next_action_href": ACCEPTANCE_CAPTURE_PATH if blocked_keys else "",
        "next_action_label": ACCEPTANCE_CAPTURE_LABEL if blocked_keys else "",
        "next_action_method": ACCEPTANCE_CAPTURE_METHOD.lower() if blocked_keys else "",
        "next_action_proof_key": next_proof_key,
        "operator_delivery_policy": {
            "action_required_only": True,
            "telegram_push_allowed_for_next_action": bool(blocked_keys),
            "next_action_requires_user": bool(blocked_keys),
            "next_action_delivery_policy": "action_required_only" if blocked_keys else "queue_only",
            "non_action_progress_push_allowed": False,
            "quiet_hours_respected": True,
            "irreversible_actions_consent_gated": True,
        },
    }
    _write(target, receipt)
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Materialize redacted Executive Assistant acceptance evidence.")
    parser.add_argument("--receipt", default=str(DEFAULT_RECEIPT))
    parser.add_argument("--input")
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args(argv)
    input_payload = _load(args.input) if args.input else None
    receipt = materialize_executive_assistant_acceptance_evidence(
        receipt_path=args.receipt,
        input_payload=input_payload,
        generated_at=args.generated_at,
        preserve_existing=not args.reset,
    )
    print(json.dumps({"status": receipt["status"], "receipt": str(args.receipt)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
