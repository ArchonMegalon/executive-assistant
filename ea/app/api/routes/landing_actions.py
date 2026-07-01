from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
import urllib.parse

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.api.dependencies import RequestContext, get_container, get_request_context, require_operator_context
from app.api.routes.admin_view_models import (
    ACTIVE_MEDIA_LTD_GOAL_RECEIPT as EA_ACTIVE_MEDIA_LTD_GOAL_RECEIPT,
    EXECUTIVE_ASSISTANT_ACCEPTANCE_EVIDENCE_RECEIPT as EA_ACCEPTANCE_EVIDENCE_RECEIPT,
    OFFICE_LOOP_GOAL_RECEIPT as EA_OFFICE_LOOP_GOAL_RECEIPT,
    WHOLE_PROJECT_SCOPE_GAP_AUDIT_RECEIPT as EA_SCOPE_GAP_AUDIT_RECEIPT,
    WHOLE_PROJECT_SIGNAL_TO_DECISION_RECEIPT as EA_SIGNAL_TO_DECISION_RECEIPT,
)
from app.api.routes.landing_browser import _form_value, _normalize_browser_return_to
from app.api.routes.landing_shared_support import (
    _default_operator_id_for_browser,
    bootstrap_initial_operator_profile,
)
from app.container import AppContainer
from app.product.service import build_product_service
from app.services.proactive_ooda_approval_capture import finalize_proactive_ooda_approval_outcome
from app.services.proactive_ooda_runtime_artifacts import load_runtime_artifact_bundle
from app.services.proactive_ooda_teable_sync import (
    sync_proactive_ooda_approval_outcome_to_teable,
    teable_sync_enabled,
)

_REPO_ROOT_FOR_SOURCE_STATE = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT_FOR_SOURCE_STATE) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT_FOR_SOURCE_STATE))
_EA_SCRIPTS_FOR_SOURCE_STATE = Path(__file__).resolve().parents[3] / "scripts"
if str(_EA_SCRIPTS_FOR_SOURCE_STATE) not in sys.path:
    sys.path.insert(0, str(_EA_SCRIPTS_FOR_SOURCE_STATE))

try:
    from scripts.source_state_head import resolve_source_state_head
    from scripts.source_state_head import resolve_source_worktree_fingerprint
except Exception:  # pragma: no cover - app runtime may not include repo scripts on sys.path
    resolve_source_state_head = None
    resolve_source_worktree_fingerprint = None

router = APIRouter(tags=["landing"])

EA_ROOT = _REPO_ROOT_FOR_SOURCE_STATE
EA_QUALITY_READINESS_RECEIPT = EA_ROOT / ".codex-studio" / "published" / "ea_executive_assistant_quality_readiness.generated.json"
EA_PROACTIVE_OODA_GOLD_ACCEPTANCE_RECEIPT = (
    EA_ROOT / ".codex-studio" / "published" / "ea_proactive_ooda_gold_acceptance.generated.json"
)
EA_PROACTIVE_OODA_OPERATOR_STATUS_RECEIPT = (
    EA_ROOT / ".codex-studio" / "published" / "ea_proactive_ooda_operator_status.generated.json"
)
EA_PROACTIVE_OODA_APPROVAL_OUTCOME_RECEIPT = (
    EA_ROOT / "state" / "proactive_ooda_latest_approval_outcome.generated.json"
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest() if value else ""


def _source_state_fields() -> dict[str, str]:
    source_head = ""
    source_fingerprint = ""
    if resolve_source_state_head is not None:
        try:
            source_head = str(resolve_source_state_head(EA_ROOT) or "").strip()
        except Exception:
            source_head = ""
    if resolve_source_worktree_fingerprint is not None:
        try:
            source_fingerprint = str(resolve_source_worktree_fingerprint(EA_ROOT) or "").strip()
        except Exception:
            source_fingerprint = ""
    return {
        "source_git_head": source_head,
        "head_semantics": "source_state",
        "source_state_fingerprint": source_fingerprint,
        "source_state_fingerprint_semantics": "worktree_source_files_sha256_excluding_generated_only_paths",
    }


_ACCEPTANCE_KEYS = (
    "real_daily_morning_brief_accepted",
    "real_decision_cleared",
    "real_commitment_recovered_or_closed",
    "real_approved_action_audited",
    "real_provider_failure_recovered",
)
_ACCEPTANCE_PROOF_LABELS = {
    "real_daily_morning_brief_accepted": "real daily morning brief acceptance",
    "real_decision_cleared": "real decision cleared by the principal or operator",
    "real_commitment_recovered_or_closed": "real commitment recovered or closed with an evidence receipt",
    "real_approved_action_audited": "real approved outbound action with audit trail",
    "real_provider_failure_recovered": "real provider failure recovered with operator-grade reason",
}
_ACCEPTANCE_CAPTURE_PATH = "/admin/actions/acceptance-evidence"
_ACCEPTANCE_CAPTURE_METHOD = "POST"
_ACCEPTANCE_CAPTURE_LABEL = "Record a real-use outcome"
_ACCEPTANCE_CAPTURE_FORM_FIELDS = ["proof_key", "source_kind", "evidence", "object_ref"]
_LOCAL_REVIEW_PATH = "/app/today"
_LOCAL_REVIEW_LABEL = "Open Today"
_SIGNAL_EVIDENCE_CAPTURE_PATH = "/admin/actions/signal-to-decision-evidence"
_SIGNAL_EVIDENCE_CAPTURE_METHOD = "POST"
_SIGNAL_EVIDENCE_CAPTURE_FORM_FIELDS = ["evidence_part", "source_kind", "evidence", "packet_ref"]
_REQUIRED_SIGNAL_SOURCES = [
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
_SIGNAL_EVIDENCE_PARTS = {
    "review": {
        "label": "real weekly signal-to-decision review accepted by the operator",
        "accepted_field": "real_weekly_operator_review_accepted",
        "next_action": "record_redacted_signal_review_acceptance",
    },
    "followthrough": {
        "label": "closed-loop signal-to-decision follow-through receipt accepted by the operator",
        "accepted_field": "closed_loop_followthrough_receipt_verified",
        "next_action": "record_redacted_signal_followthrough_acceptance",
    },
}


def _load_json(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _quality_next_action_context(proof_key: str) -> dict[str, object]:
    if not proof_key:
        return {}
    return {
        "kind": "redacted_acceptance_capture",
        "proof_key": proof_key,
        "proof_label": _ACCEPTANCE_PROOF_LABELS.get(proof_key, ""),
        "capture_path": _ACCEPTANCE_CAPTURE_PATH,
        "capture_method": _ACCEPTANCE_CAPTURE_METHOD,
        "required_form_fields": list(_ACCEPTANCE_CAPTURE_FORM_FIELDS),
        "stored_evidence_shape": "sha256_only",
        "raw_acceptance_text_persisted": False,
        "raw_actor_identity_persisted": False,
        "raw_object_reference_persisted": False,
    }


def _acceptance_capture_surface() -> dict[str, object]:
    return {
        "method": _ACCEPTANCE_CAPTURE_METHOD,
        "path": _ACCEPTANCE_CAPTURE_PATH,
        "admin_only": True,
        "operator_context_required": True,
        "required_form_fields": list(_ACCEPTANCE_CAPTURE_FORM_FIELDS),
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


def _empty_acceptance_row() -> dict[str, object]:
    return {
        "accepted": False,
        "status": "missing_or_invalid",
        "source_kind": "unknown",
        "evidence_sha256": "",
        "actor_sha256": "",
        "object_ref_sha256": "",
        "raw_evidence_exposed": False,
        "raw_actor_exposed": False,
        "raw_object_ref_exposed": False,
    }


def _acceptance_capture_requirements(acceptance_keys: dict[str, object]) -> list[dict[str, object]]:
    requirements: list[dict[str, object]] = []
    for key in _ACCEPTANCE_KEYS:
        row = dict(acceptance_keys.get(key) or {})
        accepted = row.get("accepted") is True
        requirements.append(
            {
                "key": key,
                "label": _ACCEPTANCE_PROOF_LABELS[key],
                "status": "accepted_redacted" if accepted else "pending_real_world_evidence",
                "accepted": accepted,
                "capture_method": _ACCEPTANCE_CAPTURE_METHOD,
                "capture_path": _ACCEPTANCE_CAPTURE_PATH,
                "proof_key": key,
                "required_form_fields": list(_ACCEPTANCE_CAPTURE_FORM_FIELDS),
                "server_actor_source": "authenticated_operator_context",
                "raw_input_not_persisted": True,
                "stored_evidence_shape": "sha256_only",
                "raw_evidence_exposed": False,
                "raw_actor_exposed": False,
                "raw_object_ref_exposed": False,
                "user_action_required": not accepted,
                "delivery_policy": "action_required_only" if not accepted else "queue_only",
                "telegram_push_allowed": not accepted,
                "interruption_budget": "action_required" if not accepted else "none",
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
        )
    return requirements


def _signal_evidence_capture_surface() -> dict[str, object]:
    return {
        "method": _SIGNAL_EVIDENCE_CAPTURE_METHOD,
        "path": _SIGNAL_EVIDENCE_CAPTURE_PATH,
        "admin_only": True,
        "operator_context_required": True,
        "required_form_fields": list(_SIGNAL_EVIDENCE_CAPTURE_FORM_FIELDS),
        "valid_evidence_parts": list(_SIGNAL_EVIDENCE_PARTS),
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


def _signal_evidence_capture_requirements(receipt: dict[str, object]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for part, spec in _SIGNAL_EVIDENCE_PARTS.items():
        accepted = bool(receipt.get(str(spec["accepted_field"])))
        rows.append(
            {
                "evidence_part": part,
                "label": str(spec["label"]),
                "status": "accepted_redacted" if accepted else "pending_real_world_evidence",
                "accepted": accepted,
                "capture_method": _SIGNAL_EVIDENCE_CAPTURE_METHOD,
                "capture_path": _SIGNAL_EVIDENCE_CAPTURE_PATH,
                "required_form_fields": list(_SIGNAL_EVIDENCE_CAPTURE_FORM_FIELDS),
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
                "claim_boundary": "does_not_prove_closed_signal_to_decision_loop_until_review_and_followthrough_are_accepted",
            }
        )
    return rows


def _signal_source_row(key: str) -> dict[str, object]:
    return {
        "key": key,
        "status": "mapped_from_sources",
        "owner_truth_plane": "operator_review_required",
        "journey_or_release_gate_mapping": "weekly_signal_to_decision_packet",
    }


def _refresh_signal_evidence_contract(receipt: dict[str, object]) -> None:
    review_accepted = bool(receipt.get("real_weekly_operator_review_accepted"))
    follow_accepted = bool(receipt.get("closed_loop_followthrough_receipt_verified"))
    receipt.update(_source_state_fields())
    receipt["contract_name"] = "ea.whole_project_signal_to_decision_receipt.v1"
    receipt["status"] = (
        "ready_real_signal_to_decision_closure"
        if review_accepted and follow_accepted
        else "partial_real_signal_to_decision_closure"
        if review_accepted or follow_accepted
        else "ready_local_packet_pending_operator_acceptance"
    )
    if not review_accepted:
        receipt["next_action"] = str(_SIGNAL_EVIDENCE_PARTS["review"]["next_action"])
        receipt["next_action_evidence_part"] = "review"
    elif not follow_accepted:
        receipt["next_action"] = str(_SIGNAL_EVIDENCE_PARTS["followthrough"]["next_action"])
        receipt["next_action_evidence_part"] = "followthrough"
    else:
        receipt["next_action"] = "review_closed_signal_to_decision_claim"
        receipt["next_action_evidence_part"] = ""
    if receipt["next_action_evidence_part"]:
        receipt["next_action_href"] = _SIGNAL_EVIDENCE_CAPTURE_PATH
        receipt["next_action_label"] = "Record a signal-loop outcome"
        receipt["next_action_method"] = _SIGNAL_EVIDENCE_CAPTURE_METHOD.lower()
    else:
        receipt["next_action_href"] = ""
        receipt["next_action_label"] = ""
        receipt["next_action_method"] = ""
    receipt["goal_completion_claim_allowed"] = False
    receipt["queue_truth_claim_allowed"] = False
    receipt["release_authority_claim_allowed"] = False
    receipt["boundary_posture"] = {
        "ea_is_product_truth": False,
        "local_signal_synthesis_not_canonical_queue_or_release_truth": True,
    }
    receipt["signal_sources"] = [_signal_source_row(key) for key in _REQUIRED_SIGNAL_SOURCES]
    receipt["decision_packet"] = {
        "decision_items": [
            {"key": "provider_runtime_recovery", "source": "provider_runtime_failures"},
            {"key": "audiobook_acceptance", "source": "audiobook_and_media_acceptance"},
            {"key": "spoken_conversation_acceptance", "source": "manfred_spoken_conversation_acceptance"},
            {"key": "privacy_boundary_review", "source": "privacy_or_boundary_incidents"},
        ]
    }
    receipt["signal_evidence_capture_surface"] = _signal_evidence_capture_surface()
    receipt["signal_evidence_capture_requirements"] = _signal_evidence_capture_requirements(receipt)
    receipt["privacy"] = {
        "raw_review_text_exposed": False,
        "raw_followthrough_text_exposed": False,
        "raw_actor_identity_exposed": False,
        "raw_packet_reference_exposed": False,
        "raw_private_context_exposed": False,
    }


def _proactive_ooda_operator_status_path_for_gold(gold_path: Path) -> Path:
    if gold_path != EA_PROACTIVE_OODA_GOLD_ACCEPTANCE_RECEIPT:
        return gold_path.with_name("ea_proactive_ooda_operator_status.generated.json")
    return EA_PROACTIVE_OODA_OPERATOR_STATUS_RECEIPT


def _proactive_ooda_approval_outcome_path_for_gold(gold_path: Path) -> Path:
    if (
        gold_path != EA_PROACTIVE_OODA_GOLD_ACCEPTANCE_RECEIPT
        and EA_PROACTIVE_OODA_APPROVAL_OUTCOME_RECEIPT
        == EA_ROOT / "state" / "proactive_ooda_latest_approval_outcome.generated.json"
    ):
        return gold_path.parent / "proactive_ooda_latest_approval_outcome.generated.json"
    return EA_PROACTIVE_OODA_APPROVAL_OUTCOME_RECEIPT


def _materialize_admin_proactive_ooda_operator_status(
    *,
    output_path: Path,
    live_receipt_path: Path | None = None,
) -> None:
    from scripts.materialize_proactive_ooda_operator_status import build_proactive_ooda_operator_status

    build_proactive_ooda_operator_status(
        output_path=output_path,
        live_receipt_path=live_receipt_path,
        allow_live_route_probe=False,
    )


def _materialize_admin_proactive_ooda_gold_acceptance(
    *,
    output_path: Path,
    operator_status_path: Path,
    run_receipt_path: Path | None,
    stage_packet_dir: Path | None,
    safe_work_result_dir: Path | None,
    approval_outcome_path: Path,
) -> None:
    from scripts.materialize_proactive_ooda_gold_acceptance import materialize_proactive_ooda_gold_acceptance

    materialize_proactive_ooda_gold_acceptance(
        output_path=output_path,
        operator_status_path=operator_status_path,
        run_receipt_path=run_receipt_path,
        stage_packet_dir=stage_packet_dir,
        safe_work_result_dir=safe_work_result_dir,
        approval_outcome_path=approval_outcome_path,
        allow_live_runtime_probe=False,
    )


def _record_admin_proactive_ooda_approval_outcome(
    *,
    principal_id: str,
    outcome: str,
    evidence: str,
    actor: str,
    source_kind: str,
    packet_ref: str,
    staged_artifact_ref: str,
    dry_run: bool,
) -> dict[str, object]:
    if dry_run:
        return {"status": "dry_run", "recorded": False, "error": ""}
    gold_path = Path(EA_PROACTIVE_OODA_GOLD_ACCEPTANCE_RECEIPT)
    try:
        finalized = finalize_proactive_ooda_approval_outcome(
            principal_id=principal_id,
            outcome=outcome,
            evidence=evidence,
            actor=actor,
            packet_ref=packet_ref,
            staged_artifact_ref=staged_artifact_ref,
            source_kind=source_kind,
            root=EA_ROOT,
            approval_outcome_path=_proactive_ooda_approval_outcome_path_for_gold(gold_path),
            operator_status_path=_proactive_ooda_operator_status_path_for_gold(gold_path),
            gold_acceptance_path=gold_path,
            runtime_artifact_loader=load_runtime_artifact_bundle,
            teable_sync_decider=teable_sync_enabled,
            teable_syncer=sync_proactive_ooda_approval_outcome_to_teable,
            operator_status_materializer=_materialize_admin_proactive_ooda_operator_status,
            gold_materializer=_materialize_admin_proactive_ooda_gold_acceptance,
        )
    except Exception as exc:
        return {
            "status": "record_failed",
            "recorded": False,
            "error": type(exc).__name__,
        }
    approval_outcome = dict(finalized.get("approval_outcome") or {})
    recorded = bool(approval_outcome.get("approval_outcome_recorded"))
    followthrough_refresh = _refresh_admin_proactive_ooda_followthrough_receipts() if recorded else {}
    return {
        **finalized,
        "status": "recorded" if recorded else "record_failed",
        "recorded": recorded,
        "error": "" if recorded else str(approval_outcome.get("reason") or "approval_outcome_not_recorded"),
        "followthrough_refresh": followthrough_refresh,
    }


def _default_acceptance_receipt() -> dict[str, object]:
    acceptance_keys = {key: _empty_acceptance_row() for key in _ACCEPTANCE_KEYS}
    receipt = {
        "contract_name": "ea.executive_assistant_acceptance_evidence.v1",
        "status": "blocked_missing_real_world_acceptance_evidence",
        "goal_completion_claim_allowed": False,
        "accepted_keys": [],
        "blocked_keys": list(_ACCEPTANCE_KEYS),
        "acceptance_keys": acceptance_keys,
        "acceptance_capture_surface": _acceptance_capture_surface(),
        "acceptance_capture_requirements": _acceptance_capture_requirements(acceptance_keys),
        "privacy": {
            "raw_private_context_exposed": False,
            "raw_acceptance_text_exposed": False,
            "raw_actor_identity_exposed": False,
            "raw_object_reference_exposed": False,
            "credential_values_exposed": False,
        },
        "remaining_external_proofs": [_ACCEPTANCE_PROOF_LABELS[key] for key in _ACCEPTANCE_KEYS],
    }
    _refresh_acceptance_receipt_summary(receipt, acceptance_keys)
    return receipt


def _default_signal_receipt() -> dict[str, object]:
    receipt = {
        "contract_name": "ea.whole_project_signal_to_decision_receipt.v1",
        "status": "ready_local_packet_pending_operator_acceptance",
        "goal_completion_claim_allowed": False,
        "real_weekly_operator_review_accepted": False,
        "closed_loop_followthrough_receipt_verified": False,
        "operator_review": {
            "accepted": False,
            "source_kind": "",
            "recorded_at": "",
            "review_sha256": "",
            "actor_sha256": "",
            "packet_ref_sha256": "",
            "raw_review_exposed": False,
            "raw_actor_exposed": False,
            "raw_packet_ref_exposed": False,
        },
        "followthrough_receipt": {
            "accepted": False,
            "source_kind": "",
            "recorded_at": "",
            "followthrough_sha256": "",
            "actor_sha256": "",
            "packet_ref_sha256": "",
            "raw_followthrough_exposed": False,
            "raw_actor_exposed": False,
            "raw_packet_ref_exposed": False,
        },
        "signal_evidence_capture_surface": _signal_evidence_capture_surface(),
        "privacy": {
            "raw_review_text_exposed": False,
            "raw_followthrough_text_exposed": False,
            "raw_actor_identity_exposed": False,
            "raw_packet_reference_exposed": False,
            "raw_private_context_exposed": False,
        },
        "remaining_external_proofs": [
            "real weekly signal-to-decision review accepted by the operator",
            "closed-loop signal-to-decision follow-through receipt accepted by the operator",
        ],
    }
    receipt["signal_evidence_capture_requirements"] = _signal_evidence_capture_requirements(receipt)
    receipt.update(_source_state_fields())
    return receipt


def _acceptance_operator_delivery_policy(*, expected_blocked: tuple[str, ...]) -> dict[str, object]:
    blocked = bool(expected_blocked)
    return {
        "action_required_only": True,
        "telegram_push_allowed_for_next_action": blocked,
        "next_action_requires_user": blocked,
        "next_action_delivery_policy": "action_required_only" if blocked else "queue_only",
        "non_action_progress_push_allowed": False,
        "quiet_hours_respected": True,
        "irreversible_actions_consent_gated": True,
    }


def _refresh_acceptance_receipt_summary(
    receipt: dict[str, object],
    acceptance_keys: dict[str, object] | None = None,
) -> None:
    rows = dict(acceptance_keys or receipt.get("acceptance_keys") or {})
    for key in _ACCEPTANCE_KEYS:
        row = _empty_acceptance_row()
        row.update(dict(rows.get(key) or {}))
        if row.get("accepted") is True:
            row["status"] = "accepted_redacted"
        row["raw_evidence_exposed"] = False
        row["raw_actor_exposed"] = False
        row["raw_object_ref_exposed"] = False
        rows[key] = row
    accepted_keys = [key for key in _ACCEPTANCE_KEYS if dict(rows.get(key) or {}).get("accepted") is True]
    blocked_keys = [key for key in _ACCEPTANCE_KEYS if key not in accepted_keys]
    receipt["contract_name"] = "ea.executive_assistant_acceptance_evidence.v1"
    receipt.update(_source_state_fields())
    receipt["status"] = (
        "ready_real_world_acceptance_evidence"
        if not blocked_keys
        else "partial_real_world_acceptance_evidence"
        if accepted_keys
        else "blocked_missing_real_world_acceptance_evidence"
    )
    receipt["goal_completion_claim_allowed"] = False
    receipt["public_or_premium_claim_allowed"] = False
    receipt["acceptance_keys"] = rows
    receipt["accepted_keys"] = accepted_keys
    receipt["blocked_keys"] = blocked_keys
    receipt["real_daily_use_verified"] = not blocked_keys
    receipt["real_principal_acceptance_verified"] = rows["real_daily_morning_brief_accepted"].get("accepted") is True
    receipt["real_operator_acceptance_verified"] = any(
        rows[key].get("accepted") is True
        for key in _ACCEPTANCE_KEYS
        if key != "real_daily_morning_brief_accepted"
    )
    receipt["real_provider_recovery_verified"] = rows["real_provider_failure_recovered"].get("accepted") is True
    receipt["acceptance_capture_surface"] = _acceptance_capture_surface()
    receipt["acceptance_capture_requirements"] = _acceptance_capture_requirements(rows)
    blocked_keys_tuple = tuple(blocked_keys)
    receipt["operator_delivery_policy"] = _acceptance_operator_delivery_policy(
        expected_blocked=blocked_keys_tuple,
    )
    receipt["privacy"] = {
        "credential_values_exposed": False,
        "raw_acceptance_text_exposed": False,
        "raw_actor_identity_exposed": False,
        "raw_object_reference_exposed": False,
        "raw_private_context_exposed": False,
    }
    receipt["remaining_external_proofs"] = [_ACCEPTANCE_PROOF_LABELS[key] for key in blocked_keys]
    receipt["next_action"] = (
        "collect_redacted_real_world_acceptance_evidence"
        if blocked_keys
        else "review_good_executive_assistant_claim"
    )
    receipt["next_action_href"] = _ACCEPTANCE_CAPTURE_PATH if blocked_keys else ""
    receipt["next_action_label"] = _ACCEPTANCE_CAPTURE_LABEL if blocked_keys else ""
    receipt["next_action_method"] = _ACCEPTANCE_CAPTURE_METHOD.lower() if blocked_keys else ""
    receipt["next_action_proof_key"] = blocked_keys[0] if blocked_keys else ""


def _update_quality_receipt_from_acceptance(acceptance: dict[str, object]) -> None:
    quality = _load_json(EA_QUALITY_READINESS_RECEIPT)
    if not quality:
        quality = {
            "contract_name": "ea.executive_assistant_quality_readiness.v1",
            "status": "blocked_real_world_acceptance",
            "goal_completion_claim_allowed": False,
            "external_acceptance_blockers": [
                "real_daily_morning_brief_accepted",
                "real_decision_cleared",
                "real_commitment_recovered_or_closed",
                "real_approved_action_audited",
                "real_provider_failure_recovered",
            ],
            "privacy": {
                "raw_acceptance_text_exposed": False,
            },
        }
    normalized_acceptance = dict(acceptance)
    acceptance_keys = dict(normalized_acceptance.get("acceptance_keys") or {})
    _refresh_acceptance_receipt_summary(normalized_acceptance, acceptance_keys)
    blockers = list(normalized_acceptance.get("blocked_keys") or [])
    local_ready = bool(quality.get("local_quality_evidence_ready", True))
    if not local_ready:
        status = "blocked_local_quality_evidence"
    elif blockers:
        status = "blocked_real_world_acceptance"
    else:
        status = "ready_for_good_executive_assistant_claim_review"
    quality["status"] = status
    quality.update(_source_state_fields())
    quality["goal_completion_claim_allowed"] = False
    quality["good_executive_assistant_claim_allowed"] = bool(local_ready and not blockers)
    quality["public_or_premium_claim_allowed"] = False
    quality["local_quality_evidence_ready"] = local_ready
    quality["blocked_checks"] = [] if not blockers else blockers
    quality["external_acceptance_blockers"] = blockers
    quality["live_daily_use_verified"] = not blockers
    quality["real_principal_acceptance_verified"] = bool(normalized_acceptance.get("real_principal_acceptance_verified"))
    quality["real_operator_acceptance_verified"] = bool(normalized_acceptance.get("real_operator_acceptance_verified"))
    quality["real_provider_recovery_verified"] = bool(normalized_acceptance.get("real_provider_recovery_verified"))
    quality["ea_is_product_truth"] = False
    quality["ea_owns_canonical_queue_truth"] = False
    quality["ea_owns_release_authority"] = False
    quality["provider_telemetry_is_product_authority"] = False
    quality["acceptance_evidence"] = normalized_acceptance
    quality["acceptance_capture_surface"] = _acceptance_capture_surface()
    quality["acceptance_capture_requirements"] = _acceptance_capture_requirements(
        dict(normalized_acceptance.get("acceptance_keys") or {})
    )
    quality["required_real_world_proof"] = [_ACCEPTANCE_PROOF_LABELS[key] for key in _ACCEPTANCE_KEYS]
    quality["remaining_external_proofs"] = [_ACCEPTANCE_PROOF_LABELS[key] for key in blockers]
    quality["privacy"] = {
        "credential_values_exposed": False,
        "env_values_exposed": False,
        "raw_acceptance_actor_exposed": False,
        "raw_acceptance_object_ref_exposed": False,
        "raw_acceptance_text_exposed": False,
        "raw_private_context_exposed": False,
        "seeded_fixture_raw_private_context_exposed": False,
    }
    if status == "blocked_local_quality_evidence":
        quality["next_action"] = "inspect_local_office_loop_quality_regression"
        quality["next_action_href"] = _LOCAL_REVIEW_PATH
        quality["next_action_label"] = _LOCAL_REVIEW_LABEL
        quality["next_action_method"] = "get"
        quality["next_action_proof_key"] = ""
        quality["next_action_context"] = {}
    elif status == "blocked_real_world_acceptance":
        next_action_proof_key = blockers[0] if blockers else ""
        quality["next_action"] = "collect_redacted_real_world_acceptance_evidence"
        quality["next_action_href"] = _ACCEPTANCE_CAPTURE_PATH
        quality["next_action_label"] = _ACCEPTANCE_CAPTURE_LABEL
        quality["next_action_method"] = _ACCEPTANCE_CAPTURE_METHOD.lower()
        quality["next_action_proof_key"] = next_action_proof_key
        quality["next_action_context"] = _quality_next_action_context(next_action_proof_key)
    else:
        quality["next_action"] = "review_good_executive_assistant_claim"
        quality["next_action_href"] = ""
        quality["next_action_label"] = ""
        quality["next_action_method"] = ""
        quality["next_action_proof_key"] = ""
        quality["next_action_context"] = {}
    _write_json(EA_QUALITY_READINESS_RECEIPT, quality)


def _update_scope_gap_evidence() -> None:
    signal = _load_json(EA_SIGNAL_TO_DECISION_RECEIPT)
    if not signal:
        signal = _default_signal_receipt()
        _write_json(EA_SIGNAL_TO_DECISION_RECEIPT, signal)
    scope_gap = _load_json(EA_SCOPE_GAP_AUDIT_RECEIPT)
    if not scope_gap:
        scope_gap = {
            "contract_name": "ea.whole_project_scope_gap_audit.v1",
            "status": "ready_local_audit",
            "goal_completion_claim_allowed": False,
        }
    scope_gap["evidence_receipts"] = {
        "executive_assistant_acceptance_evidence": _load_json(EA_ACCEPTANCE_EVIDENCE_RECEIPT),
        "signal_to_decision": signal,
    }
    scope_gap["goal_completion_claim_allowed"] = False
    _write_json(EA_SCOPE_GAP_AUDIT_RECEIPT, scope_gap)


def _materialize_admin_acceptance_evidence_from_sources() -> dict[str, object]:
    from scripts.materialize_executive_assistant_acceptance_evidence import (
        materialize_executive_assistant_acceptance_evidence,
    )

    return materialize_executive_assistant_acceptance_evidence(
        receipt_path=EA_ACCEPTANCE_EVIDENCE_RECEIPT,
        preserve_existing=True,
        proactive_ooda_gold_receipt_path=EA_PROACTIVE_OODA_GOLD_ACCEPTANCE_RECEIPT,
    )


def _materialize_admin_quality_readiness_from_sources() -> dict[str, object]:
    from scripts.materialize_executive_assistant_quality_readiness import (
        materialize_executive_assistant_quality_readiness,
    )

    return materialize_executive_assistant_quality_readiness(
        receipt_path=EA_QUALITY_READINESS_RECEIPT,
        office_loop_receipt_path=EA_OFFICE_LOOP_GOAL_RECEIPT,
        acceptance_evidence_receipt_path=EA_ACCEPTANCE_EVIDENCE_RECEIPT,
    )


def _materialize_admin_office_loop_goal_from_sources() -> dict[str, object]:
    from scripts.materialize_office_loop_goal_receipt import materialize_office_loop_goal_receipt

    return materialize_office_loop_goal_receipt(
        receipt_path=EA_OFFICE_LOOP_GOAL_RECEIPT,
        acceptance_evidence_receipt_path=EA_ACCEPTANCE_EVIDENCE_RECEIPT,
        signal_to_decision_receipt_path=EA_SIGNAL_TO_DECISION_RECEIPT,
        proactive_operator_status_receipt_path=EA_PROACTIVE_OODA_OPERATOR_STATUS_RECEIPT,
        proactive_gold_acceptance_receipt_path=EA_PROACTIVE_OODA_GOLD_ACCEPTANCE_RECEIPT,
        scope_gap_audit_receipt_path=EA_SCOPE_GAP_AUDIT_RECEIPT,
    )


def _materialize_admin_scope_gap_audit_from_sources() -> dict[str, object]:
    from scripts.materialize_whole_project_scope_gap_audit import materialize_whole_project_scope_gap_audit

    return materialize_whole_project_scope_gap_audit(
        receipt_path=EA_SCOPE_GAP_AUDIT_RECEIPT,
        office_loop_receipt_path=EA_OFFICE_LOOP_GOAL_RECEIPT,
        acceptance_evidence_receipt_path=EA_ACCEPTANCE_EVIDENCE_RECEIPT,
        ea_quality_receipt_path=EA_QUALITY_READINESS_RECEIPT,
        active_media_receipt_path=EA_ACTIVE_MEDIA_LTD_GOAL_RECEIPT,
        signal_to_decision_receipt_path=EA_SIGNAL_TO_DECISION_RECEIPT,
    )


def _refresh_admin_proactive_ooda_followthrough_receipts() -> dict[str, object]:
    if not _load_json(EA_SIGNAL_TO_DECISION_RECEIPT):
        _write_json(EA_SIGNAL_TO_DECISION_RECEIPT, _default_signal_receipt())

    results: dict[str, object] = {}

    def _run(label: str, materializer) -> None:
        try:
            receipt = materializer()
        except Exception as exc:
            results[label] = {"status": "failed", "error": type(exc).__name__}
            return
        results[label] = {
            "status": "materialized",
            "receipt_status": str(dict(receipt or {}).get("status") or "").strip(),
        }

    _run("acceptance_evidence", _materialize_admin_acceptance_evidence_from_sources)
    _run("quality_readiness", _materialize_admin_quality_readiness_from_sources)
    _run("office_loop_pre_scope", _materialize_admin_office_loop_goal_from_sources)
    _run("scope_gap_audit", _materialize_admin_scope_gap_audit_from_sources)
    _run("office_loop", _materialize_admin_office_loop_goal_from_sources)
    return results


def _record_acceptance_evidence_receipt(
    *,
    proof_key: str,
    source_kind: str,
    evidence: str,
    object_ref: str,
    actor: str,
) -> dict[str, object]:
    if proof_key not in _ACCEPTANCE_KEYS:
        raise ValueError("acceptance_proof_key_invalid")
    if not evidence.strip() or not object_ref.strip():
        raise ValueError("acceptance_evidence_and_object_ref_required")

    receipt = _load_json(EA_ACCEPTANCE_EVIDENCE_RECEIPT) or _default_acceptance_receipt()
    acceptance_keys = dict(receipt.get("acceptance_keys") or {})
    for key in _ACCEPTANCE_KEYS:
        acceptance_keys.setdefault(key, _empty_acceptance_row())
    row = dict(acceptance_keys.get(proof_key) or {})
    row.update(
        {
            "accepted": True,
            "status": "accepted_redacted",
            "source_kind": source_kind,
            "recorded_at": _now_iso(),
            "evidence_sha256": _sha256(evidence),
            "actor_sha256": _sha256(actor),
            "object_ref_sha256": _sha256(object_ref),
            "raw_evidence_exposed": False,
            "raw_actor_exposed": False,
            "raw_object_ref_exposed": False,
        }
    )
    acceptance_keys[proof_key] = row
    receipt["acceptance_keys"] = acceptance_keys
    _refresh_acceptance_receipt_summary(receipt, acceptance_keys)
    _write_json(EA_ACCEPTANCE_EVIDENCE_RECEIPT, receipt)
    _update_quality_receipt_from_acceptance(receipt)
    _update_scope_gap_evidence()
    return receipt


@router.post("/admin/actions/bootstrap-operator")
async def admin_bootstrap_operator(
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> RedirectResponse:
    if not context.authenticated:
        raise HTTPException(status_code=403, detail="auth_required")
    body = urllib.parse.parse_qs((await request.body()).decode("utf-8", errors="ignore"), keep_blank_values=True)
    return_to = _normalize_browser_return_to(_form_value(body, "return_to", "/admin/policies"), default="/admin/policies")
    if str(context.operator_id or "").strip():
        separator = "&" if "?" in return_to else "?"
        return RedirectResponse(f"{return_to}{separator}operator_bootstrap=already_ready", status_code=303)
    try:
        bootstrap_initial_operator_profile(
            container,
            principal_id=context.principal_id,
            access_email=str(context.access_email or "").strip().lower(),
            operator_id=_form_value(body, "operator_id", ""),
            display_name=_form_value(body, "display_name", ""),
            notes="Bootstrapped from the admin setup surface.",
        )
    except ValueError as exc:
        detail = str(exc or "").strip() or "operator_profile_bootstrap_failed"
        if detail in {"operator_profile_bootstrap_not_allowed", "operator_seat_limit_reached"}:
            raise HTTPException(status_code=409, detail=detail) from exc
        raise HTTPException(status_code=400, detail=detail) from exc
    separator = "&" if "?" in return_to else "?"
    return RedirectResponse(f"{return_to}{separator}operator_bootstrap=ready", status_code=303)


@router.post("/app/actions/drafts/{draft_ref}")
@router.post("/app/actions/drafts/{draft_ref}/approve")
async def app_approve_draft(
    draft_ref: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> RedirectResponse:
    body = urllib.parse.parse_qs((await request.body()).decode("utf-8", errors="ignore"), keep_blank_values=True)
    return_to = _normalize_browser_return_to(_form_value(body, "return_to", "/app/queue"), default="/app/queue")
    reason = _form_value(body, "reason", "Approved from browser workflow.")
    product = build_product_service(container)
    actor = str(context.operator_id or context.access_email or context.principal_id or "product").strip()
    approved = product.approve_draft(
        principal_id=context.principal_id,
        draft_ref=draft_ref,
        decided_by=actor,
        reason=reason,
    )
    if approved is None:
        raise HTTPException(status_code=404, detail="draft_not_found")
    return RedirectResponse(return_to, status_code=303)


@router.post("/app/actions/drafts/{draft_ref}/reject")
async def app_reject_draft(
    draft_ref: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> RedirectResponse:
    body = urllib.parse.parse_qs((await request.body()).decode("utf-8", errors="ignore"), keep_blank_values=True)
    return_to = _normalize_browser_return_to(_form_value(body, "return_to", "/app/queue"), default="/app/queue")
    reason = _form_value(body, "reason", "Rejected from browser workflow.")
    product = build_product_service(container)
    actor = str(context.operator_id or context.access_email or context.principal_id or "product").strip()
    rejected = product.reject_draft(
        principal_id=context.principal_id,
        draft_ref=draft_ref,
        decided_by=actor,
        reason=reason,
    )
    if rejected is None:
        raise HTTPException(status_code=404, detail="draft_not_found")
    return RedirectResponse(return_to, status_code=303)


@router.post("/app/actions/queue/{item_ref}")
@router.post("/app/actions/queue/{item_ref}/resolve")
async def app_resolve_queue_item(
    item_ref: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> RedirectResponse:
    body = urllib.parse.parse_qs((await request.body()).decode("utf-8", errors="ignore"), keep_blank_values=True)
    return_to = _normalize_browser_return_to(_form_value(body, "return_to", "/app/queue"), default="/app/queue")
    action = _form_value(body, "action", "resolve")
    reason = _form_value(body, "reason", "Resolved from browser workflow.")
    product = build_product_service(container)
    actor = str(context.operator_id or context.access_email or context.principal_id or "product").strip()
    updated = product.resolve_queue_item(
        principal_id=context.principal_id,
        item_ref=item_ref,
        action=action,
        actor=actor,
        reason=reason,
        reason_code=_form_value(body, "reason_code", ""),
        due_at=_form_value(body, "due_at", "") or None,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="queue_item_not_found")
    return RedirectResponse(return_to, status_code=303)


@router.post("/app/actions/commitments/create")
async def app_create_commitment(
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> RedirectResponse:
    body = urllib.parse.parse_qs((await request.body()).decode("utf-8", errors="ignore"), keep_blank_values=True)
    title = _form_value(body, "title", "")
    if title:
        product = build_product_service(container)
        product.create_commitment(
            principal_id=context.principal_id,
            title=title,
            details=_form_value(body, "details", ""),
            due_at=_form_value(body, "due_at", "") or None,
            counterparty=_form_value(body, "counterparty", ""),
            owner="office",
            kind=_form_value(body, "kind", "follow_up"),
            stakeholder_id=_form_value(body, "stakeholder_id", ""),
            channel_hint=_form_value(body, "channel_hint", "email"),
        )
    return RedirectResponse(
        _normalize_browser_return_to(_form_value(body, "return_to", "/app/commitments"), default="/app/commitments"),
        status_code=303,
    )


@router.post("/admin/actions/acceptance-evidence")
async def admin_record_acceptance_evidence(
    request: Request,
    context: RequestContext = Depends(get_request_context),
    _: None = Depends(require_operator_context),
) -> RedirectResponse:
    body = urllib.parse.parse_qs((await request.body()).decode("utf-8", errors="ignore"), keep_blank_values=True)
    return_to = _normalize_browser_return_to(_form_value(body, "return_to", "/admin/goals"), default="/admin/goals")
    proof_key = _form_value(body, "proof_key", "")
    source_kind = _form_value(body, "source_kind", "unknown")
    evidence = _form_value(body, "evidence", "")
    object_ref = _form_value(body, "object_ref", "")
    actor = str(context.operator_id or context.access_email or context.principal_id or "operator").strip()
    try:
        _record_acceptance_evidence_receipt(
            proof_key=proof_key,
            source_kind=source_kind,
            evidence=evidence,
            object_ref=object_ref,
            actor=actor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    separator = "&" if "?" in return_to else "?"
    return RedirectResponse(f"{return_to}{separator}acceptance_status=recorded", status_code=303)


@router.post("/admin/actions/signal-to-decision-evidence")
async def admin_record_signal_to_decision_evidence(
    request: Request,
    context: RequestContext = Depends(get_request_context),
    _: None = Depends(require_operator_context),
) -> RedirectResponse:
    body = urllib.parse.parse_qs((await request.body()).decode("utf-8", errors="ignore"), keep_blank_values=True)
    return_to = _normalize_browser_return_to(_form_value(body, "return_to", "/admin/goals"), default="/admin/goals")
    evidence_part = _form_value(body, "evidence_part", "")
    source_kind = _form_value(body, "source_kind", "unknown")
    evidence = _form_value(body, "evidence", "")
    packet_ref = _form_value(body, "packet_ref", "")
    actor = str(context.operator_id or context.access_email or context.principal_id or "operator").strip()
    if evidence_part not in _SIGNAL_EVIDENCE_PARTS:
        raise HTTPException(status_code=400, detail="signal_evidence_part_invalid")
    if not evidence.strip() or not packet_ref.strip():
        raise HTTPException(status_code=400, detail="signal_evidence_and_packet_ref_required")

    receipt = _load_json(EA_SIGNAL_TO_DECISION_RECEIPT) or _default_signal_receipt()
    if evidence_part == "review":
        receipt["operator_review"] = {
            "accepted": True,
            "status": "accepted_redacted",
            "source_kind": source_kind,
            "recorded_at": _now_iso(),
            "review_sha256": _sha256(evidence),
            "actor_sha256": _sha256(actor),
            "packet_ref_sha256": _sha256(packet_ref),
            "raw_review_exposed": False,
            "raw_actor_exposed": False,
            "raw_packet_ref_exposed": False,
        }
        receipt["real_weekly_operator_review_accepted"] = True
    elif evidence_part == "followthrough":
        receipt["followthrough_receipt"] = {
            "accepted": True,
            "status": "accepted_redacted",
            "source_kind": source_kind,
            "recorded_at": _now_iso(),
            "followthrough_sha256": _sha256(evidence),
            "actor_sha256": _sha256(actor),
            "packet_ref_sha256": _sha256(packet_ref),
            "raw_followthrough_exposed": False,
            "raw_actor_exposed": False,
            "raw_packet_ref_exposed": False,
        }
        receipt["closed_loop_followthrough_receipt_verified"] = True
    receipt["status"] = (
        "ready_real_signal_to_decision_closure"
        if receipt.get("real_weekly_operator_review_accepted") and receipt.get("closed_loop_followthrough_receipt_verified")
        else "partial_real_signal_to_decision_closure"
        if receipt.get("real_weekly_operator_review_accepted") or receipt.get("closed_loop_followthrough_receipt_verified")
        else "ready_local_packet_pending_operator_acceptance"
    )
    receipt["goal_completion_claim_allowed"] = False
    remaining = []
    if not receipt.get("real_weekly_operator_review_accepted"):
        remaining.append("real weekly signal-to-decision review accepted by the operator")
    if not receipt.get("closed_loop_followthrough_receipt_verified"):
        remaining.append("closed-loop signal-to-decision follow-through receipt accepted by the operator")
    receipt["remaining_external_proofs"] = remaining
    _refresh_signal_evidence_contract(receipt)
    _write_json(EA_SIGNAL_TO_DECISION_RECEIPT, receipt)
    _update_scope_gap_evidence()
    separator = "&" if "?" in return_to else "?"
    return RedirectResponse(f"{return_to}{separator}signal_status=recorded", status_code=303)


@router.post("/admin/actions/proactive-ooda-evidence")
async def admin_record_proactive_ooda_evidence(
    request: Request,
    context: RequestContext = Depends(get_request_context),
    _: None = Depends(require_operator_context),
) -> RedirectResponse:
    body = urllib.parse.parse_qs((await request.body()).decode("utf-8", errors="ignore"), keep_blank_values=True)
    return_to = _normalize_browser_return_to(_form_value(body, "return_to", "/admin/goals"), default="/admin/goals")
    outcome = _form_value(body, "outcome", "approved")
    source_kind = _form_value(body, "source_kind", "unknown")
    evidence = _form_value(body, "evidence", "")
    packet_ref = _form_value(body, "packet_ref", "")
    staged_artifact_ref = _form_value(body, "staged_artifact_ref", "")
    dry_run = _form_value(body, "dry_run", "").strip().lower() in {"1", "true", "yes", "on"}
    actor = str(context.operator_id or context.access_email or context.principal_id or "operator").strip()
    result = _record_admin_proactive_ooda_approval_outcome(
        principal_id=context.principal_id,
        outcome=outcome,
        evidence=evidence,
        actor=actor,
        source_kind=source_kind,
        packet_ref=packet_ref,
        staged_artifact_ref=staged_artifact_ref,
        dry_run=dry_run,
    )
    separator = "&" if "?" in return_to else "?"
    status = str(result.get("status") or "failed").strip() or "failed"
    query = {"proactive_ooda_status": status}
    error = str(result.get("error") or "").strip()
    if error:
        query["proactive_ooda_error"] = error
    return RedirectResponse(f"{return_to}{separator}{urllib.parse.urlencode(query)}", status_code=303)


@router.post("/app/actions/commitments/extract")
async def app_extract_commitment(
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> RedirectResponse:
    body = urllib.parse.parse_qs((await request.body()).decode("utf-8", errors="ignore"), keep_blank_values=True)
    source_text = _form_value(body, "source_text", "")
    if source_text:
        product = build_product_service(container)
        product.stage_extracted_commitments(
            principal_id=context.principal_id,
            text=source_text,
            counterparty=_form_value(body, "counterparty", ""),
            due_at=_form_value(body, "due_at", "") or None,
            kind=_form_value(body, "kind", "commitment"),
            stakeholder_id=_form_value(body, "stakeholder_id", ""),
        )
    return RedirectResponse(
        _normalize_browser_return_to(_form_value(body, "return_to", "/app/queue"), default="/app/queue"),
        status_code=303,
    )


@router.post("/app/actions/commitments/candidates/{candidate_id}/accept")
async def app_accept_commitment_candidate(
    candidate_id: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> RedirectResponse:
    body = urllib.parse.parse_qs((await request.body()).decode("utf-8", errors="ignore"), keep_blank_values=True)
    product = build_product_service(container)
    reviewer = str(context.operator_id or context.access_email or context.principal_id or "product").strip()
    created = product.accept_commitment_candidate(
        principal_id=context.principal_id,
        candidate_id=candidate_id,
        reviewer=reviewer,
        title=_form_value(body, "title", ""),
        details=_form_value(body, "details", ""),
        due_at=_form_value(body, "due_at", "") or None,
        counterparty=_form_value(body, "counterparty", ""),
        kind=_form_value(body, "kind", ""),
        stakeholder_id=_form_value(body, "stakeholder_id", ""),
    )
    if created is None:
        raise HTTPException(status_code=404, detail="commitment_candidate_not_found")
    return RedirectResponse(
        _normalize_browser_return_to(_form_value(body, "return_to", "/app/queue"), default="/app/queue"),
        status_code=303,
    )


@router.post("/app/actions/commitments/candidates/{candidate_id}/reject")
async def app_reject_commitment_candidate(
    candidate_id: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> RedirectResponse:
    body = urllib.parse.parse_qs((await request.body()).decode("utf-8", errors="ignore"), keep_blank_values=True)
    product = build_product_service(container)
    reviewer = str(context.operator_id or context.access_email or context.principal_id or "product").strip()
    rejected = product.reject_commitment_candidate(principal_id=context.principal_id, candidate_id=candidate_id, reviewer=reviewer)
    if rejected is None:
        raise HTTPException(status_code=404, detail="commitment_candidate_not_found")
    return RedirectResponse(
        _normalize_browser_return_to(_form_value(body, "return_to", "/app/queue"), default="/app/queue"),
        status_code=303,
    )


@router.post("/app/actions/handoffs/{handoff_ref:path}/assign")
async def app_assign_handoff(
    handoff_ref: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> RedirectResponse:
    body = urllib.parse.parse_qs((await request.body()).decode("utf-8", errors="ignore"), keep_blank_values=True)
    return_to = _normalize_browser_return_to(_form_value(body, "return_to", "/app/commitments"), default="/app/commitments")
    operator_id = (
        _form_value(body, "operator_id", "")
        or str(context.operator_id or "").strip()
        or _default_operator_id_for_browser(container, principal_id=context.principal_id)
    )
    if not operator_id:
        raise HTTPException(status_code=409, detail="operator_required")
    product = build_product_service(container)
    actor = str(context.operator_id or context.access_email or context.principal_id or operator_id).strip()
    assigned = product.assign_handoff(
        principal_id=context.principal_id,
        handoff_ref=handoff_ref,
        operator_id=operator_id,
        actor=actor,
    )
    if assigned is None:
        raise HTTPException(status_code=404, detail="handoff_not_found")
    return RedirectResponse(return_to, status_code=303)


@router.post("/app/actions/handoffs/{handoff_ref:path}/complete")
async def app_complete_handoff(
    handoff_ref: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> RedirectResponse:
    body = urllib.parse.parse_qs((await request.body()).decode("utf-8", errors="ignore"), keep_blank_values=True)
    return_to = _normalize_browser_return_to(_form_value(body, "return_to", "/app/commitments"), default="/app/commitments")
    resolution = _form_value(body, "action", "completed")
    operator_id = (
        _form_value(body, "operator_id", "")
        or str(context.operator_id or "").strip()
        or _default_operator_id_for_browser(container, principal_id=context.principal_id)
    )
    if not operator_id:
        raise HTTPException(status_code=409, detail="operator_required")
    product = build_product_service(container)
    actor = str(context.operator_id or context.access_email or context.principal_id or operator_id).strip()
    completed = product.complete_handoff(
        principal_id=context.principal_id,
        handoff_ref=handoff_ref,
        operator_id=operator_id,
        actor=actor,
        resolution=resolution,
    )
    if completed is None:
        raise HTTPException(status_code=404, detail="handoff_not_found")
    return RedirectResponse(return_to, status_code=303)


@router.post("/app/actions/handoffs/{handoff_ref:path}/retry-send")
async def app_retry_handoff_send(
    handoff_ref: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> RedirectResponse:
    body = urllib.parse.parse_qs((await request.body()).decode("utf-8", errors="ignore"), keep_blank_values=True)
    return_to = _normalize_browser_return_to(
        _form_value(body, "return_to", f"/app/handoffs/{handoff_ref}"),
        default=f"/app/handoffs/{handoff_ref}",
    )
    operator_id = (
        _form_value(body, "operator_id", "")
        or str(context.operator_id or "").strip()
        or _default_operator_id_for_browser(container, principal_id=context.principal_id)
    )
    if not operator_id:
        raise HTTPException(status_code=409, detail="operator_required")
    product = build_product_service(container)
    actor = str(context.operator_id or context.access_email or context.principal_id or operator_id).strip()
    separator = "&" if "?" in return_to else "?"
    try:
        retried = product.retry_delivery_followup_send(
            principal_id=context.principal_id,
            handoff_ref=handoff_ref,
            operator_id=operator_id,
            actor=actor,
        )
    except RuntimeError as exc:
        error_value = urllib.parse.quote(str(exc or "draft_send_retry_failed"), safe="")
        return RedirectResponse(f"{return_to}{separator}send_error={error_value}", status_code=303)
    if retried is None:
        raise HTTPException(status_code=404, detail="handoff_not_found")
    return RedirectResponse(f"{return_to}{separator}send_status=sent", status_code=303)


@router.post("/app/actions/handoffs/{handoff_ref:path}/recreate")
async def app_recreate_handoff(
    handoff_ref: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> RedirectResponse:
    body = urllib.parse.parse_qs((await request.body()).decode("utf-8", errors="ignore"), keep_blank_values=True)
    return_to = _normalize_browser_return_to(
        _form_value(body, "return_to", f"/app/handoffs/{handoff_ref}"),
        default=f"/app/handoffs/{handoff_ref}",
    )
    operator_id = (
        _form_value(body, "operator_id", "")
        or str(context.operator_id or "").strip()
        or _default_operator_id_for_browser(container, principal_id=context.principal_id)
    )
    if not operator_id:
        raise HTTPException(status_code=409, detail="operator_required")
    product = build_product_service(container)
    actor = str(context.operator_id or context.access_email or context.principal_id or operator_id).strip()
    separator = "&" if "?" in return_to else "?"
    try:
        recreated = product.recreate_property_tour_followup(
            principal_id=context.principal_id,
            handoff_ref=handoff_ref,
            operator_id=operator_id,
            actor=actor,
        )
    except RuntimeError as exc:
        error_value = urllib.parse.quote(str(exc or "handoff_recreate_failed"), safe="")
        return RedirectResponse(f"{return_to}{separator}recreate_error={error_value}", status_code=303)
    if recreated is None:
        raise HTTPException(status_code=404, detail="handoff_not_found")
    return RedirectResponse(f"{return_to}{separator}recreate_status={str(recreated.resolution or 'completed')}", status_code=303)


@router.post("/app/actions/threads/{thread_ref:path}/resume-delivery")
async def app_resume_thread_delivery_followup(
    thread_ref: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> RedirectResponse:
    body = urllib.parse.parse_qs((await request.body()).decode("utf-8", errors="ignore"), keep_blank_values=True)
    return_to = _normalize_browser_return_to(
        _form_value(body, "return_to", f"/app/threads/{thread_ref}"),
        default=f"/app/threads/{thread_ref}",
    )
    operator_id = (
        _form_value(body, "operator_id", "")
        or str(context.operator_id or "").strip()
        or _default_operator_id_for_browser(container, principal_id=context.principal_id)
    )
    product = build_product_service(container)
    actor = str(context.operator_id or context.access_email or context.principal_id or operator_id or "product").strip()
    separator = "&" if "?" in return_to else "?"
    try:
        reopened = product.resume_thread_delivery_followup(
            principal_id=context.principal_id,
            thread_ref=thread_ref,
            actor=actor,
            operator_id=operator_id,
        )
    except RuntimeError as exc:
        error_value = urllib.parse.quote(str(exc or "thread_delivery_followup_not_resumable"), safe="")
        return RedirectResponse(f"{return_to}{separator}send_error={error_value}", status_code=303)
    if reopened is None:
        raise HTTPException(status_code=404, detail="thread_not_found")
    return RedirectResponse(f"{return_to}{separator}send_status=resumed", status_code=303)


@router.post("/app/actions/support/fix-verification/request")
async def app_request_support_fix_verification(
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> RedirectResponse:
    body = urllib.parse.parse_qs((await request.body()).decode("utf-8", errors="ignore"), keep_blank_values=True)
    return_to = _normalize_browser_return_to(_form_value(body, "return_to", "/app/settings/support"), default="/app/settings/support")
    product = build_product_service(container)
    actor = str(context.operator_id or context.access_email or context.principal_id or "support").strip()
    separator = "&" if "?" in return_to else "?"
    try:
        product.request_support_fix_verification(
            principal_id=context.principal_id,
            actor=actor,
            base_url=str(request.base_url),
        )
    except (RuntimeError, ValueError) as exc:
        error_value = urllib.parse.quote(str(exc or "support_fix_verification_request_failed"), safe="")
        return RedirectResponse(f"{return_to}{separator}support_verification_error={error_value}", status_code=303)
    return RedirectResponse(f"{return_to}{separator}support_verification=requested", status_code=303)


@router.post("/app/actions/people/{person_id}/correct")
async def app_correct_person(
    person_id: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> RedirectResponse:
    body = urllib.parse.parse_qs((await request.body()).decode("utf-8", errors="ignore"), keep_blank_values=True)
    return_to = _normalize_browser_return_to(_form_value(body, "return_to", f"/app/people/{person_id}"), default=f"/app/people/{person_id}")
    product = build_product_service(container)
    corrected = product.correct_person_profile(
        principal_id=context.principal_id,
        person_id=person_id,
        preferred_tone=_form_value(body, "preferred_tone", ""),
        add_theme=_form_value(body, "add_theme", ""),
        remove_theme=_form_value(body, "remove_theme", ""),
        add_risk=_form_value(body, "add_risk", ""),
        remove_risk=_form_value(body, "remove_risk", ""),
    )
    if corrected is None:
        raise HTTPException(status_code=404, detail="person_not_found")
    return RedirectResponse(return_to, status_code=303)


@router.post("/app/actions/settings/morning-memo")
async def app_update_morning_memo_settings(
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> RedirectResponse:
    body = urllib.parse.parse_qs((await request.body()).decode("utf-8", errors="ignore"), keep_blank_values=True)
    return_to = _normalize_browser_return_to(_form_value(body, "return_to", "/app/settings"), default="/app/settings")
    status = container.onboarding.status(principal_id=context.principal_id)
    workspace = dict(status.get("workspace") or {})
    container.onboarding.start_workspace(
        principal_id=context.principal_id,
        workspace_name=_form_value(body, "workspace_name", str(workspace.get("name") or "PropertyQuarry Workspace")),
        workspace_mode=str(workspace.get("mode") or "personal"),
        region=str(workspace.get("region") or ""),
        language=_form_value(body, "language", str(workspace.get("language") or "en") or "en"),
        timezone=_form_value(body, "timezone", str(workspace.get("timezone") or "Europe/Vienna") or "Europe/Vienna"),
        selected_channels=tuple(str(value) for value in (status.get("selected_channels") or []) if str(value).strip()),
    )
    status = container.onboarding.status(principal_id=context.principal_id)
    privacy = dict(status.get("privacy") or {})
    morning_memo = dict(dict(status.get("delivery_preferences") or {}).get("morning_memo") or {})
    container.onboarding.finalize(
        principal_id=context.principal_id,
        retention_mode=str(privacy.get("retention_mode") or "full_bodies"),
        metadata_only_channels=tuple(str(value) for value in (privacy.get("metadata_only_channels") or []) if str(value).strip()),
        allow_drafts=bool(privacy.get("allow_drafts")),
        allow_action_suggestions=bool(privacy.get("allow_action_suggestions", True)),
        allow_auto_briefs=_form_value(body, "enabled", "").lower() in {"true", "1", "yes", "on"},
        auto_brief_cadence=_form_value(body, "cadence", str(morning_memo.get("cadence") or "daily_morning")),
        auto_brief_delivery_time_local=_form_value(body, "delivery_time_local", str(morning_memo.get("delivery_time_local") or "08:00")),
        auto_brief_quiet_hours_start=_form_value(body, "quiet_hours_start", str(morning_memo.get("quiet_hours_start") or "20:00")),
        auto_brief_quiet_hours_end=_form_value(body, "quiet_hours_end", str(morning_memo.get("quiet_hours_end") or "07:00")),
        auto_brief_recipient_email=_form_value(body, "recipient_email", str(morning_memo.get("recipient_email") or "")),
        auto_brief_delivery_channel=str(morning_memo.get("delivery_channel") or "email"),
    )
    return RedirectResponse(return_to, status_code=303)
