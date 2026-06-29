from __future__ import annotations

import hashlib
import json
import os
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
    PROACTIVE_OODA_GOLD_ACCEPTANCE_RECEIPT as EA_PROACTIVE_OODA_GOLD_ACCEPTANCE_RECEIPT,
    PROACTIVE_OODA_OPERATOR_STATUS_RECEIPT as EA_PROACTIVE_OODA_OPERATOR_STATUS_RECEIPT,
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
from app.services.proactive_ooda_approval_outcomes import (
    default_proactive_ooda_approval_outcome_path,
)
from app.services.proactive_ooda_approval_capture import finalize_proactive_ooda_approval_outcome
from app.services.proactive_ooda_runtime_artifacts import load_runtime_artifact_bundle
from app.services.proactive_ooda_teable_sync import (
    sync_proactive_ooda_approval_outcome_to_teable,
    teable_sync_enabled,
)

router = APIRouter(tags=["landing"])

EA_ROOT = Path(__file__).resolve().parents[4]
EA_QUALITY_READINESS_RECEIPT = EA_ROOT / ".codex-studio" / "published" / "ea_executive_assistant_quality_readiness.generated.json"
EA_PROACTIVE_OODA_APPROVAL_OUTCOME_RECEIPT = default_proactive_ooda_approval_outcome_path(
    root=EA_ROOT,
    state_path=os.getenv("EA_PROACTIVE_OODA_STATE_PATH", "state/proactive_ooda_notified.json"),
    receipt_path=os.getenv("EA_PROACTIVE_OODA_RECEIPT_PATH", ""),
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest() if value else ""


def _load_json(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _default_acceptance_receipt() -> dict[str, object]:
    keys = (
        "real_daily_morning_brief_accepted",
        "real_decision_cleared",
        "real_commitment_recovered_or_closed",
        "real_approved_action_audited",
        "real_provider_failure_recovered",
    )
    return {
        "contract_name": "ea.executive_assistant_acceptance_evidence.v1",
        "status": "blocked_missing_real_world_acceptance_evidence",
        "goal_completion_claim_allowed": False,
        "accepted_keys": [],
        "blocked_keys": list(keys),
        "acceptance_keys": {
            key: {
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
            for key in keys
        },
        "privacy": {
            "raw_private_context_exposed": False,
            "raw_acceptance_text_exposed": False,
            "raw_actor_identity_exposed": False,
            "raw_object_reference_exposed": False,
            "credential_values_exposed": False,
        },
        "remaining_external_proofs": [
            "real daily morning brief acceptance",
            "real decision cleared by the principal or operator",
            "real commitment recovered or closed with an evidence receipt",
            "real approved outbound action with audit trail",
            "real provider failure recovered with operator-grade reason",
        ],
    }


def _default_signal_receipt() -> dict[str, object]:
    return {
        "contract_name": "ea.whole_project_signal_to_decision_receipt.v1",
        "status": "ready_local_packet_pending_operator_acceptance",
        "goal_completion_claim_allowed": False,
        "real_weekly_operator_review_accepted": False,
        "closed_loop_followthrough_receipt_verified": False,
        "remaining_external_proofs": [
            "real weekly signal-to-decision review accepted by the operator",
            "closed-loop signal-to-decision follow-through receipt accepted by the operator",
        ],
    }


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
    accepted = {str(value) for value in list(acceptance.get("accepted_keys") or []) if str(value).strip()}
    blockers = [
        key
        for key in (
            "real_daily_morning_brief_accepted",
            "real_decision_cleared",
            "real_commitment_recovered_or_closed",
            "real_approved_action_audited",
            "real_provider_failure_recovered",
        )
        if key not in accepted
    ]
    quality["status"] = "ready_for_good_executive_assistant_claim_review" if not blockers else "blocked_real_world_acceptance"
    quality["goal_completion_claim_allowed"] = False
    quality["external_acceptance_blockers"] = blockers
    quality["privacy"] = {"raw_acceptance_text_exposed": False}
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

    receipt = _load_json(EA_ACCEPTANCE_EVIDENCE_RECEIPT) or _default_acceptance_receipt()
    acceptance_keys = dict(receipt.get("acceptance_keys") or {})
    row = dict(acceptance_keys.get(proof_key) or {})
    row.update(
        {
            "accepted": True,
            "status": "accepted",
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
    accepted_keys = sorted(key for key, value in acceptance_keys.items() if bool(dict(value).get("accepted")))
    receipt["accepted_keys"] = accepted_keys
    receipt["blocked_keys"] = [key for key in acceptance_keys if key not in accepted_keys]
    receipt["status"] = "ready_real_world_acceptance_evidence" if not receipt["blocked_keys"] else "partial_real_world_acceptance_evidence"
    receipt["goal_completion_claim_allowed"] = False
    receipt["privacy"] = {
        "raw_private_context_exposed": False,
        "raw_acceptance_text_exposed": False,
        "raw_actor_identity_exposed": False,
        "raw_object_reference_exposed": False,
        "credential_values_exposed": False,
    }
    receipt["remaining_external_proofs"] = [
        label
        for key, label in (
            ("real_daily_morning_brief_accepted", "real daily morning brief acceptance"),
            ("real_decision_cleared", "real decision cleared by the principal or operator"),
            ("real_commitment_recovered_or_closed", "real commitment recovered or closed with an evidence receipt"),
            ("real_approved_action_audited", "real approved outbound action with audit trail"),
            ("real_provider_failure_recovered", "real provider failure recovered with operator-grade reason"),
        )
        if key not in accepted_keys
    ]
    _write_json(EA_ACCEPTANCE_EVIDENCE_RECEIPT, receipt)
    _update_quality_receipt_from_acceptance(receipt)
    _update_scope_gap_evidence()
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

    receipt = _load_json(EA_SIGNAL_TO_DECISION_RECEIPT) or _default_signal_receipt()
    if evidence_part == "review":
        receipt["operator_review"] = {
            "accepted": True,
            "source_kind": source_kind,
            "recorded_at": _now_iso(),
            "review_sha256": _sha256(evidence),
            "actor_sha256": _sha256(actor),
            "packet_ref_sha256": _sha256(packet_ref),
        }
        receipt["real_weekly_operator_review_accepted"] = True
    elif evidence_part == "followthrough":
        receipt["followthrough_receipt"] = {
            "accepted": True,
            "source_kind": source_kind,
            "recorded_at": _now_iso(),
            "followthrough_sha256": _sha256(evidence),
            "actor_sha256": _sha256(actor),
            "packet_ref_sha256": _sha256(packet_ref),
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
    actor = str(context.operator_id or context.access_email or context.principal_id or "operator").strip()
    finalize_proactive_ooda_approval_outcome(
        principal_id=context.principal_id,
        outcome=outcome,
        evidence=evidence,
        actor=actor,
        packet_ref=packet_ref,
        staged_artifact_ref=staged_artifact_ref,
        source_kind=source_kind,
        recorded_at=_now_iso(),
        root=EA_ROOT,
        state_path=os.getenv("EA_PROACTIVE_OODA_STATE_PATH", "state/proactive_ooda_notified.json"),
        receipt_path=os.getenv("EA_PROACTIVE_OODA_RECEIPT_PATH", ""),
        stage_packet_dir=os.getenv("EA_PROACTIVE_OODA_STAGE_PACKET_DIR", ""),
        safe_work_result_dir=os.getenv("EA_PROACTIVE_OODA_SAFE_WORK_RESULT_DIR", ""),
        approval_outcome_path=EA_PROACTIVE_OODA_APPROVAL_OUTCOME_RECEIPT,
        operator_status_path=EA_PROACTIVE_OODA_OPERATOR_STATUS_RECEIPT,
        gold_acceptance_path=EA_PROACTIVE_OODA_GOLD_ACCEPTANCE_RECEIPT,
        runtime_artifact_loader=load_runtime_artifact_bundle,
        teable_sync_decider=teable_sync_enabled,
        teable_syncer=sync_proactive_ooda_approval_outcome_to_teable,
    )
    separator = "&" if "?" in return_to else "?"
    return RedirectResponse(f"{return_to}{separator}proactive_ooda_status=recorded", status_code=303)


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
