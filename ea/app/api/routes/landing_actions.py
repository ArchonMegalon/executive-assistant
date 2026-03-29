from __future__ import annotations

import urllib.parse

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.api.dependencies import RequestContext, get_container, get_request_context
from app.api.routes.landing import _default_operator_id_for_browser, _form_value
from app.container import AppContainer
from app.product.service import build_product_service

router = APIRouter(tags=["landing"])


@router.post("/app/actions/drafts/{draft_ref}")
@router.post("/app/actions/drafts/{draft_ref}/approve")
async def app_approve_draft(
    draft_ref: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> RedirectResponse:
    body = urllib.parse.parse_qs((await request.body()).decode("utf-8", errors="ignore"), keep_blank_values=True)
    return_to = _form_value(body, "return_to", "/app/inbox")
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
    return_to = _form_value(body, "return_to", "/app/inbox")
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
    return_to = _form_value(body, "return_to", "/app/briefing")
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
    return RedirectResponse(_form_value(body, "return_to", "/app/follow-ups"), status_code=303)


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
    return RedirectResponse(_form_value(body, "return_to", "/app/inbox"), status_code=303)


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
    return RedirectResponse(_form_value(body, "return_to", "/app/inbox"), status_code=303)


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
    return RedirectResponse(_form_value(body, "return_to", "/app/inbox"), status_code=303)


@router.post("/app/actions/handoffs/{handoff_ref:path}/assign")
async def app_assign_handoff(
    handoff_ref: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> RedirectResponse:
    body = urllib.parse.parse_qs((await request.body()).decode("utf-8", errors="ignore"), keep_blank_values=True)
    return_to = _form_value(body, "return_to", "/app/follow-ups")
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
    return_to = _form_value(body, "return_to", "/app/follow-ups")
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
    return_to = _form_value(body, "return_to", f"/app/handoffs/{handoff_ref}")
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


@router.post("/app/actions/people/{person_id}/correct")
async def app_correct_person(
    person_id: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> RedirectResponse:
    body = urllib.parse.parse_qs((await request.body()).decode("utf-8", errors="ignore"), keep_blank_values=True)
    return_to = _form_value(body, "return_to", f"/app/people/{person_id}")
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
    return_to = _form_value(body, "return_to", "/app/settings")
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
