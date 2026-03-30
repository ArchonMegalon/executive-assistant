from __future__ import annotations

import urllib.parse

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

from app.api.dependencies import RequestContext, get_container, get_request_context
from app.api.routes.landing import (
    _console_shell_context,
    _evidence_detail_rows,
    _object_detail_row,
    _render_console_object_detail,
    _render_public_template,
    app_shell,
)
from app.api.routes.landing_content import APP_NAV_GROUPS
from app.container import AppContainer
from app.product.service import build_product_service

router = APIRouter(tags=["landing"])


def _google_delivery_action(reason: str, *, return_to: str) -> dict[str, str]:
    normalized = str(reason or "").strip()
    label = "Connect Google" if normalized in {"google_oauth_binding_not_found", "google_account_missing"} else "Reconnect Google"
    return {
        "label": label,
        "href": f"/app/actions/google/connect?return_to={urllib.parse.quote(return_to, safe='/?:=&')}",
        "method": "get",
    }


@router.get("/app/people", response_class=HTMLResponse)
def people_root(
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> HTMLResponse:
    return app_shell("people", request, container, context)


@router.get("/app/people/{person_id}", response_class=HTMLResponse)
def person_detail(
    person_id: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> HTMLResponse:
    status = container.onboarding.status(principal_id=context.principal_id)
    workspace = dict(status.get("workspace") or {})
    product = build_product_service(container)
    detail = product.get_person_detail(
        principal_id=context.principal_id,
        person_id=person_id,
        operator_id=str(context.operator_id or "").strip(),
    )
    if detail is None:
        raise HTTPException(status_code=404, detail="person_not_found")
    product.record_surface_event(
        principal_id=context.principal_id,
        event_type="people_opened",
        surface=f"people:{person_id}",
        actor=str(context.operator_id or context.access_email or context.principal_id or "browser").strip(),
    )
    return _render_public_template(
        request,
        "app/people_detail.html",
        **{
            **_console_shell_context(
                request=request,
                page_title=f"Executive Assistant {detail.profile.display_name}",
                current_nav="people",
                context=context,
                console_title=detail.profile.display_name,
                console_summary="Relationship context, open loops, current drafts, and evidence tied to one person.",
                nav_groups=APP_NAV_GROUPS,
                workspace_label=str(workspace.get("name") or "Executive Workspace"),
                cards=[],
                stats=[
                    {"label": "Open loops", "value": str(detail.profile.open_loops_count)},
                    {"label": "Commitments", "value": str(len(detail.commitments))},
                    {"label": "Drafts", "value": str(len(detail.drafts))},
                    {"label": "Evidence", "value": str(len(detail.evidence_refs))},
                ],
            ),
            "person": detail.profile,
            "detail": detail,
        },
    )


@router.get("/app/commitment-items/{commitment_ref:path}", response_class=HTMLResponse)
def commitment_detail(
    commitment_ref: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> HTMLResponse:
    status = container.onboarding.status(principal_id=context.principal_id)
    workspace = dict(status.get("workspace") or {})
    product = build_product_service(container)
    commitment = product.get_commitment(principal_id=context.principal_id, commitment_ref=commitment_ref)
    if commitment is None:
        raise HTTPException(status_code=404, detail="commitment_not_found")
    history = product.get_commitment_history(principal_id=context.principal_id, commitment_ref=commitment_ref, limit=8)
    product.record_surface_event(
        principal_id=context.principal_id,
        event_type="commitment_opened",
        surface=f"commitment:{commitment_ref}",
        actor=str(context.operator_id or context.access_email or context.principal_id or "browser").strip(),
    )
    return _render_console_object_detail(
        request=request,
        context=context,
        workspace_label=str(workspace.get("name") or "Executive Workspace"),
        page_title=f"Executive Assistant {commitment.statement}",
        current_nav="queue",
        console_title=commitment.statement,
        console_summary="Commitment source, owner, due date, risk, and recent ledger activity.",
        object_kind="Commitment ledger",
        object_title=commitment.statement,
        object_summary=f"{commitment.counterparty or 'Office loop'} · {commitment.status.replace('_', ' ')}",
        object_meta=[
            {"label": "Owner", "value": str(commitment.owner or "office").replace("_", " ").title()},
            {"label": "Counterparty", "value": commitment.counterparty or "Unknown"},
            {"label": "Due", "value": str(commitment.due_at or "")[:10] or "No due date"},
            {"label": "Risk", "value": str(commitment.risk_level or "normal").title()},
        ],
        object_sidebar_title="Commitment posture",
        object_sidebar_copy="A commitment should stay visible until it is closed, deferred, dropped, or reopened with a reason.",
        object_sidebar_rows=[
            _object_detail_row("Source", str(commitment.source_type or "manual").replace("_", " ").title(), "Source"),
            _object_detail_row("Source ref", commitment.source_ref or "No source ref attached.", "Reference"),
            _object_detail_row("Last activity", str(commitment.last_activity_at or "")[:10] or "Unknown", "Activity"),
            _object_detail_row("Resolution code", commitment.resolution_code or "No resolution code recorded.", "Code"),
            _object_detail_row("Resolution reason", commitment.resolution_reason or "No resolution reason recorded.", "Reason"),
        ],
        object_sections=[
            {
                "eyebrow": "Evidence",
                "title": "Supporting proof",
                "items": _evidence_detail_rows(commitment.proof_refs),
            },
            {
                "eyebrow": "History",
                "title": "Recent ledger activity",
                "items": [
                    _object_detail_row(
                        str(item.event_type or "history").replace("_", " ").title(),
                        item.detail or "Ledger event recorded.",
                        str(item.created_at or "")[:10] or "Event",
                    )
                    for item in history
                ] or [_object_detail_row("No history yet", "No commitment history rows were recorded.", "History")],
            },
        ],
        object_sidebar_form={
            "action": f"/app/actions/queue/{commitment_ref}/resolve",
            "method": "post",
            "eyebrow": "Lifecycle",
            "title": "Update commitment state",
            "copy": "Use explicit lifecycle states when the promise is waiting on another party, already scheduled, or needs a dated defer instead of a vague open loop.",
            "submit_label": "Update commitment",
            "fields": [
                {"type": "hidden", "name": "return_to", "value": f"/app/commitment-items/{commitment_ref}"},
                {
                    "type": "select",
                    "name": "action",
                    "label": "Action",
                    "options": [
                        {"value": "close", "label": "Close", "selected": str(commitment.status or "").strip().lower() == "completed"},
                        {"value": "defer", "label": "Defer"},
                        {"value": "wait", "label": "Waiting on external", "selected": str(commitment.status or "").strip().lower() == "waiting_on_external"},
                        {"value": "schedule", "label": "Scheduled", "selected": str(commitment.status or "").strip().lower() == "scheduled"},
                        {"value": "drop", "label": "Drop"},
                        {"value": "reopen", "label": "Reopen", "selected": str(commitment.status or "").strip().lower() == "open"},
                    ],
                },
                {
                    "type": "text",
                    "name": "reason_code",
                    "label": "Reason code",
                    "value": commitment.resolution_code or "",
                    "placeholder": "scheduled, waiting_on_external, deferred",
                },
                {
                    "type": "text",
                    "name": "due_at",
                    "label": "Due at",
                    "value": commitment.due_at or "",
                    "placeholder": "YYYY-MM-DDTHH:MM:SS+00:00",
                },
                {
                    "type": "textarea",
                    "name": "reason",
                    "label": "Reason",
                    "value": commitment.resolution_reason or "",
                    "placeholder": "Why the commitment moved into this lifecycle state.",
                },
            ],
        },
    )


@router.get("/app/decisions/{decision_ref}", response_class=HTMLResponse)
def decision_detail(
    decision_ref: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> HTMLResponse:
    status = container.onboarding.status(principal_id=context.principal_id)
    workspace = dict(status.get("workspace") or {})
    product = build_product_service(container)
    decision = product.get_decision(principal_id=context.principal_id, decision_ref=decision_ref)
    if decision is None:
        raise HTTPException(status_code=404, detail="decision_not_found")
    history = product.get_decision_history(principal_id=context.principal_id, decision_ref=decision_ref, limit=8)
    product.record_surface_event(
        principal_id=context.principal_id,
        event_type="decision_opened",
        surface=f"decision:{decision_ref}",
        actor=str(context.operator_id or context.access_email or context.principal_id or "browser").strip(),
    )
    return _render_console_object_detail(
        request=request,
        context=context,
        workspace_label=str(workspace.get("name") or "Executive Workspace"),
        page_title=f"Executive Assistant {decision.title}",
        current_nav="queue",
        console_title=decision.title,
        console_summary="Decision context, ownership, deadline pressure, and supporting evidence.",
        object_kind="Decision queue",
        object_title=decision.title,
        object_summary=decision.summary or "This decision is open in the office loop.",
        object_meta=[
            {"label": "Priority", "value": str(decision.priority or "normal").title()},
            {"label": "Type", "value": str(decision.decision_type or "office_decision").replace("_", " ").title()},
            {"label": "Owner", "value": str(decision.owner_role or "office").replace("_", " ").title()},
            {"label": "Deadline", "value": str(decision.due_at or "")[:10] or "No due date"},
            {"label": "Status", "value": str(decision.status or "open").replace("_", " ").title()},
            {"label": "SLA", "value": str(decision.sla_status or "unscheduled").replace("_", " ").title()},
        ],
        object_sidebar_title="Decision pressure",
        object_sidebar_copy="A decision should stay tied to ownership, time pressure, and evidence instead of living as a generic card in a queue.",
        object_sidebar_rows=[
            _object_detail_row("Recommendation", decision.recommendation or "No recommendation projected yet.", "Recommend"),
            _object_detail_row("Next action", decision.next_action or "No next action projected yet.", "Next"),
            _object_detail_row("Impact", decision.impact_summary or "Impact has not been projected yet.", "Impact"),
            _object_detail_row("Rationale", decision.rationale or "No rationale projected yet.", "Why"),
            _object_detail_row("Evidence attached", f"{len(decision.evidence_refs or [])} supporting refs attached to this decision.", "Evidence"),
            _object_detail_row("SLA", str(decision.sla_status or "unscheduled").replace("_", " ").title(), "SLA"),
            _object_detail_row("Why now", decision.summary or "This decision is still active in the queue.", "Priority"),
        ],
        object_sections=[
            {
                "eyebrow": "Decision summary",
                "title": "Current recommendation",
                "items": [
                    _object_detail_row(
                        decision.title,
                        decision.recommendation or decision.summary or "Review this decision with its current evidence and owner context.",
                        str(decision.priority or "normal").title(),
                    ),
                    _object_detail_row("Options", ", ".join(decision.options or ()) or "No explicit options projected.", "Options"),
                    _object_detail_row("Next action", decision.next_action or "No next action projected yet.", "Next"),
                    _object_detail_row("Impact", decision.impact_summary or "No projected downstream impact yet.", "Impact"),
                    _object_detail_row("Related commitments", ", ".join(decision.related_commitment_ids or ()) or "No linked commitments.", "Commitment"),
                    _object_detail_row("Related threads", ", ".join(decision.linked_thread_ids or ()) or "No linked threads.", "Thread"),
                    _object_detail_row("Related people", ", ".join(decision.related_people or ()) or "No linked people.", "People"),
                    _object_detail_row("Resolution note", decision.resolution_reason or "No explicit resolution note yet.", "Resolution"),
                ],
            },
            {
                "eyebrow": "Evidence",
                "title": "Supporting evidence",
                "items": _evidence_detail_rows(decision.evidence_refs),
            },
            {
                "eyebrow": "Decision history",
                "title": "Recent decision history",
                "items": [
                    _object_detail_row(
                        str(item.event_type or "history").replace("_", " ").title(),
                        " · ".join(
                            part
                            for part in (
                                str(item.actor or "").strip(),
                                str(item.detail or "").strip(),
                            )
                            if part
                        )
                        or "Decision event recorded.",
                        str(item.created_at or "")[:10] or "History",
                    )
                    for item in history
                ] or [_object_detail_row("No decision history yet", "No decision events were recorded yet.", "History")],
            },
        ],
        object_sidebar_form={
            "action": f"/app/actions/queue/{decision_ref}/resolve",
            "method": "post",
            "eyebrow": "Decision lifecycle",
            "title": "Update decision state",
            "copy": "Resolve the choice, escalate it to the principal, or reopen it without leaving the decision detail surface.",
            "submit_label": "Update decision",
            "fields": [
                {"type": "hidden", "name": "return_to", "value": f"/app/decisions/{decision_ref}"},
                {
                    "type": "select",
                    "name": "action",
                    "label": "Action",
                    "options": [
                        {"value": "resolve", "label": "Resolve", "selected": str(decision.status or "").strip().lower() != "decided"},
                        {"value": "escalate", "label": "Escalate to principal"},
                        {"value": "reopen", "label": "Reopen", "selected": str(decision.status or "").strip().lower() == "decided"},
                    ],
                },
                {
                    "type": "text",
                    "name": "due_at",
                    "label": "Decision deadline",
                    "value": decision.due_at or "",
                    "placeholder": "YYYY-MM-DDTHH:MM:SS+00:00",
                },
                {
                    "type": "textarea",
                    "name": "reason",
                    "label": "Reason",
                    "value": decision.resolution_reason or "",
                    "placeholder": "Why this decision was resolved, escalated, or reopened.",
                },
            ],
        },
    )


@router.get("/app/deadlines/{deadline_ref:path}", response_class=HTMLResponse)
def deadline_detail(
    deadline_ref: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> HTMLResponse:
    status = container.onboarding.status(principal_id=context.principal_id)
    workspace = dict(status.get("workspace") or {})
    product = build_product_service(container)
    deadline = product.get_deadline(principal_id=context.principal_id, deadline_ref=deadline_ref)
    if deadline is None:
        raise HTTPException(status_code=404, detail="deadline_not_found")
    history = product.get_deadline_history(principal_id=context.principal_id, deadline_ref=deadline_ref, limit=8)
    product.record_surface_event(
        principal_id=context.principal_id,
        event_type="deadline_opened",
        surface=f"deadline:{deadline_ref}",
        actor=str(context.operator_id or context.access_email or context.principal_id or "browser").strip(),
    )
    return _render_console_object_detail(
        request=request,
        context=context,
        workspace_label=str(workspace.get("name") or "Executive Workspace"),
        page_title=f"Executive Assistant {deadline.title}",
        current_nav="queue",
        console_title=deadline.title,
        console_summary="Deadline window timing, status, and recent queue movement.",
        object_kind="Deadline window",
        object_title=deadline.title,
        object_summary=deadline.summary or "Deadline window is active in the office loop.",
        object_meta=[
            {"label": "Priority", "value": str(deadline.priority or "normal").title()},
            {"label": "Start", "value": str(deadline.start_at or "")[:10] or "No start time"},
            {"label": "End", "value": str(deadline.end_at or "")[:10] or "No end time"},
            {"label": "Status", "value": str(deadline.status or "open").replace("_", " ").title()},
        ],
        object_sidebar_title="Deadline pressure",
        object_sidebar_copy="Deadline windows should stay explorable and resolvable instead of hiding as generic queue pressure.",
        object_sidebar_rows=[
            _object_detail_row("Current note", deadline.summary or "No deadline note recorded.", "Note"),
            _object_detail_row("Priority", str(deadline.priority or "normal").title(), "Priority"),
            _object_detail_row("Window start", str(deadline.start_at or "")[:10] or "No start time recorded.", "Start"),
            _object_detail_row("Window end", str(deadline.end_at or "")[:10] or "No end time recorded.", "End"),
            _object_detail_row("Status", str(deadline.status or "open").replace("_", " ").title(), "Status"),
        ],
        object_sections=[
            {
                "eyebrow": "Window",
                "title": "Current deadline posture",
                "items": [
                    _object_detail_row(deadline.title, deadline.summary or "Deadline window is active in the office loop.", str(deadline.priority or "normal").title()),
                    _object_detail_row("Start", str(deadline.start_at or "")[:19] or "No start time recorded.", "Start"),
                    _object_detail_row("End", str(deadline.end_at or "")[:19] or "No end time recorded.", "End"),
                    _object_detail_row("Status", str(deadline.status or "open").replace("_", " ").title(), "Status"),
                ],
            },
            {
                "eyebrow": "History",
                "title": "Recent deadline history",
                "items": [
                    _object_detail_row(
                        str(item.event_type or "history").replace("_", " ").title(),
                        " · ".join(
                            part
                            for part in (
                                str(item.actor or "").strip(),
                                str(item.detail or "").strip(),
                            )
                            if part
                        )
                        or "Deadline event recorded.",
                        str(item.created_at or "")[:10] or "History",
                    )
                    for item in history
                ] or [_object_detail_row("No deadline history yet", "No deadline events were recorded yet.", "History")],
            },
        ],
        object_sidebar_form={
            "action": f"/app/actions/queue/{deadline_ref}/resolve",
            "method": "post",
            "eyebrow": "Deadline lifecycle",
            "title": "Update deadline state",
            "copy": "Resolve the current window or reopen it with a new end time without leaving the deadline detail surface.",
            "submit_label": "Update deadline",
            "fields": [
                {"type": "hidden", "name": "return_to", "value": f"/app/deadlines/{deadline_ref}"},
                {
                    "type": "select",
                    "name": "action",
                    "label": "Action",
                    "options": [
                        {"value": "resolve", "label": "Resolve", "selected": str(deadline.status or "").strip().lower() != "elapsed"},
                        {"value": "reopen", "label": "Reopen", "selected": str(deadline.status or "").strip().lower() == "elapsed"},
                    ],
                },
                {
                    "type": "text",
                    "name": "due_at",
                    "label": "Window end",
                    "value": deadline.end_at or "",
                    "placeholder": "YYYY-MM-DDTHH:MM:SS+00:00",
                },
                {
                    "type": "textarea",
                    "name": "reason",
                    "label": "Reason",
                    "value": deadline.summary or "",
                    "placeholder": "Why this deadline window was resolved or reopened.",
                },
            ],
        },
    )


@router.get("/app/handoffs/{handoff_ref:path}", response_class=HTMLResponse)
def handoff_detail(
    handoff_ref: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> HTMLResponse:
    status = container.onboarding.status(principal_id=context.principal_id)
    workspace = dict(status.get("workspace") or {})
    product = build_product_service(container)
    handoff = product.get_handoff(principal_id=context.principal_id, handoff_ref=handoff_ref)
    if handoff is None:
        raise HTTPException(status_code=404, detail="handoff_not_found")
    task_id = handoff.id.split(":", 1)[1] if handoff.id.startswith("human_task:") else handoff.id
    history_rows = container.orchestrator.list_human_task_assignment_history(task_id, principal_id=context.principal_id, limit=8)
    send_error = str(request.query_params.get("send_error") or "").strip()
    send_status = str(request.query_params.get("send_status") or "").strip()
    delivery_followup_open = (
        str(handoff.task_type or "").strip() == "delivery_followup"
        and str(handoff.status or "").strip() in {"pending", "claimed"}
        and str(handoff.resolution or "").strip() != "sent"
    )
    if send_error:
        retry_detail = send_error
    elif send_status == "sent" or str(handoff.resolution or "").strip() == "sent":
        retry_detail = "Retry send completed."
    elif delivery_followup_open:
        retry_detail = "Try the stored approved draft again after reconnecting Google."
    else:
        retry_detail = "Retry send is no longer needed for this handoff."
    google_delivery_action = (
        _google_delivery_action(str(handoff.delivery_reason or ""), return_to=f"/app/handoffs/{handoff_ref}")
        if delivery_followup_open and str(handoff.delivery_reason or "").strip().startswith("google_")
        else {}
    )
    manual_resolution_secondary_value = "reauth_needed" if str(handoff.delivery_reason or "").strip().startswith("google_") else "failed"
    manual_resolution_secondary_label = (
        "Needs reauth" if manual_resolution_secondary_value == "reauth_needed" else "Unable to send"
    )
    resolved_manual_detail = {
        "sent": "Manual send was recorded for this handoff.",
        "reauth_needed": "Google access still needs reauth before this handoff can proceed.",
        "failed": "This handoff was marked unable to send.",
        "waiting_on_principal": "Waiting on principal input before delivery can continue.",
    }.get(str(handoff.resolution or "").strip(), "")
    product.record_surface_event(
        principal_id=context.principal_id,
        event_type="handoff_opened",
        surface=f"handoff:{handoff_ref}",
        actor=str(context.operator_id or context.access_email or context.principal_id or "browser").strip(),
    )
    return _render_console_object_detail(
        request=request,
        context=context,
        workspace_label=str(workspace.get("name") or "Executive Workspace"),
        page_title=f"Executive Assistant {handoff.summary}",
        current_nav="settings",
        console_title=handoff.summary,
        console_summary="Assignment state, escalation pressure, evidence, and recent handoff routing history.",
        object_kind="Handoffs",
        object_title=handoff.summary,
        object_summary=f"{handoff.owner or 'Office'} · {handoff.status.replace('_', ' ')}",
        object_meta=[
            {"label": "Owner", "value": handoff.owner or "Unassigned"},
            {"label": "Due", "value": str(handoff.due_time or "")[:10] or "No due date"},
            {"label": "Task", "value": str(handoff.task_type or "handoff").replace("_", " ").title()},
            {"label": "Escalation", "value": str(handoff.escalation_status or "normal").title()},
            {"label": "Status", "value": str(handoff.status or "pending").replace("_", " ").title()},
        ],
        object_sidebar_title="Operator workflow",
        object_sidebar_copy="A handoff should show who owns it, whether it is waiting on the principal, and what evidence supports the transfer.",
        object_sidebar_rows=[
            _object_detail_row("Queue item", handoff.queue_item_ref or "No queue item ref attached.", "Queue"),
            _object_detail_row("Draft ref", handoff.draft_ref or "No draft is attached to this handoff.", "Draft"),
            _object_detail_row("Recipient", handoff.recipient_email or "No recipient metadata attached.", "Recipient"),
            _object_detail_row("Delivery reason", handoff.delivery_reason or "No delivery blocker is attached.", "Reason"),
            _object_detail_row(
                "Retry send in EA",
                retry_detail,
                "Action",
                href=f"/app/handoffs/{handoff_ref}",
                action_href=f"/app/actions/handoffs/{handoff_ref}/retry-send" if delivery_followup_open else "",
                action_label="Retry send" if delivery_followup_open else "",
                action_method="post" if delivery_followup_open else "",
                return_to=f"/app/handoffs/{handoff_ref}" if delivery_followup_open else "",
            ),
            _object_detail_row(
                str(google_delivery_action.get("label") or "Google delivery action"),
                "Repair Google access for this workspace before retrying delivery."
                if google_delivery_action
                else "No Google reconnect is required for this handoff.",
                "Google",
                href="/app/settings/google" if google_delivery_action else "",
                action_href=str(google_delivery_action.get("href") or ""),
                action_label=str(google_delivery_action.get("label") or ""),
                action_method=str(google_delivery_action.get("method") or ""),
                return_to=f"/app/handoffs/{handoff_ref}" if google_delivery_action else "",
            ),
            _object_detail_row(
                "Manual resolution",
                resolved_manual_detail
                or "Record the real delivery outcome when the operator finished the send outside EA or needs to keep the blocker visible.",
                "Resolution",
                href=f"/app/handoffs/{handoff_ref}",
                action_href=f"/app/actions/handoffs/{handoff_ref}/complete" if delivery_followup_open else "",
                action_label="Mark sent" if delivery_followup_open else "",
                action_value="sent" if delivery_followup_open else "",
                action_method="post" if delivery_followup_open else "",
                return_to=f"/app/handoffs/{handoff_ref}" if delivery_followup_open else "",
                secondary_action_href=f"/app/actions/handoffs/{handoff_ref}/complete" if delivery_followup_open else "",
                secondary_action_label=manual_resolution_secondary_label if delivery_followup_open else "",
                secondary_action_value=manual_resolution_secondary_value if delivery_followup_open else "",
                secondary_action_method="post" if delivery_followup_open else "",
                secondary_return_to=f"/app/handoffs/{handoff_ref}" if delivery_followup_open else "",
                tertiary_action_href=f"/app/actions/handoffs/{handoff_ref}/complete" if delivery_followup_open else "",
                tertiary_action_label="Waiting on principal" if delivery_followup_open else "",
                tertiary_action_value="waiting_on_principal" if delivery_followup_open else "",
                tertiary_action_method="post" if delivery_followup_open else "",
                tertiary_return_to=f"/app/handoffs/{handoff_ref}" if delivery_followup_open else "",
            ),
            _object_detail_row("Evidence attached", f"{len(handoff.evidence_refs or [])} evidence refs attached to this handoff.", "Evidence"),
            _object_detail_row("Assignment state", str(handoff.status or "pending").replace("_", " "), "Status"),
        ],
        object_sections=[
            {
                "eyebrow": "Evidence",
                "title": "Supporting evidence",
                "items": _evidence_detail_rows(handoff.evidence_refs),
            },
            {
                "eyebrow": "Routing history",
                "title": "Recent assignment events",
                "items": [
                    _object_detail_row(
                        str(getattr(item, "event_name", "") or "assignment").replace("_", " ").title(),
                        " · ".join(
                            part
                            for part in (
                                str(getattr(item, "assigned_operator_id", "") or "").strip(),
                                str(getattr(item, "assigned_by_actor_id", "") or "").strip(),
                                str(getattr(item, "assignment_source", "") or "").strip(),
                            )
                            if part
                        ) or "Assignment event recorded.",
                        str(getattr(item, "created_at", "") or "")[:10] or "Event",
                    )
                    for item in history_rows
                ] or [_object_detail_row("No routing history yet", "No assignment changes were recorded yet.", "History")],
            },
        ],
    )


@router.get("/app/threads/{thread_ref}", response_class=HTMLResponse)
def thread_detail(
    thread_ref: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> HTMLResponse:
    status = container.onboarding.status(principal_id=context.principal_id)
    workspace = dict(status.get("workspace") or {})
    product = build_product_service(container)
    thread = product.get_thread(principal_id=context.principal_id, thread_ref=thread_ref)
    if thread is None:
        raise HTTPException(status_code=404, detail="thread_not_found")
    history = product.get_thread_history(principal_id=context.principal_id, thread_ref=thread_ref, limit=8)
    send_error = str(request.query_params.get("send_error") or "").strip()
    send_status = str(request.query_params.get("send_status") or "").strip()
    linked_handoff_ref = next(
        (str(ref.ref_id or "").strip() for ref in thread.evidence_refs if str(ref.ref_id or "").strip().startswith("human_task:")),
        "",
    )
    linked_handoff = (
        product.get_handoff(principal_id=context.principal_id, handoff_ref=linked_handoff_ref)
        if linked_handoff_ref
        else None
    )
    delivery_followup_open = (
        linked_handoff is not None
        and str(linked_handoff.task_type or "").strip() == "delivery_followup"
        and str(linked_handoff.status or "").strip() in {"pending", "claimed"}
        and str(linked_handoff.resolution or "").strip() != "sent"
    )
    resume_followup_available = (
        not delivery_followup_open
        and str(thread.status or "").strip() in {"waiting_on_principal", "reauth_needed", "delivery_failed"}
    )
    delivery_reason = (
        str(linked_handoff.delivery_reason or "").strip()
        if linked_handoff is not None
        else str(thread.summary or "").strip()
    )
    thread_google_action = (
        _google_delivery_action(delivery_reason, return_to=f"/app/threads/{thread_ref}")
        if (delivery_followup_open or str(thread.status or "").strip() in {"delivery_followup", "reauth_needed"})
        and delivery_reason.startswith("google_")
        else {}
    )
    if send_error:
        retry_detail = send_error
    elif send_status == "sent" or str(thread.status or "").strip() == "sent" or str(getattr(linked_handoff, "resolution", "") or "").strip() == "sent":
        retry_detail = "Retry send completed."
    elif send_status == "resumed":
        retry_detail = "Delivery follow-up was reopened for this thread."
    elif delivery_followup_open:
        retry_detail = "Try the stored approved draft again after reconnecting Google."
    elif resume_followup_available:
        retry_detail = "Resume the blocked delivery follow-up so the operator can retry or close it from the thread context."
    else:
        retry_detail = "Retry send is no longer needed for this thread."
    manual_resolution_secondary_value = "reauth_needed" if delivery_reason.startswith("google_") else "failed"
    manual_resolution_secondary_label = (
        "Needs reauth" if manual_resolution_secondary_value == "reauth_needed" else "Unable to send"
    )
    resolved_manual_detail = {
        "sent": "Manual send was recorded for this thread.",
        "reauth_needed": "Google access still needs reauth before this thread can proceed.",
        "failed": "This thread was marked unable to send.",
        "waiting_on_principal": "Waiting on principal input before delivery can continue.",
    }.get(str(getattr(linked_handoff, "resolution", "") or thread.status or "").strip(), "")
    product.record_surface_event(
        principal_id=context.principal_id,
        event_type="thread_opened",
        surface=f"thread:{thread_ref}",
        actor=str(context.operator_id or context.access_email or context.principal_id or "browser").strip(),
    )
    return _render_console_object_detail(
        request=request,
        context=context,
        workspace_label=str(workspace.get("name") or "Executive Workspace"),
        page_title=f"Executive Assistant {thread.title}",
        current_nav="queue",
        console_title=thread.title,
        console_summary="Conversation state, related drafts, linked commitments, and decision context.",
        object_kind="Conversation thread",
        object_title=thread.title,
        object_summary=thread.summary or "This thread is part of the current office loop.",
        object_meta=[
            {"label": "Channel", "value": str(thread.channel or "unknown").title()},
            {"label": "Status", "value": str(thread.status or "open").replace("_", " ").title()},
            {"label": "Last activity", "value": str(thread.last_activity_at or "")[:10] or "Unknown"},
            {"label": "People", "value": str(len(thread.counterparties or []))},
        ],
        object_sidebar_title="Thread context",
        object_sidebar_copy="A conversation should stay connected to the work it creates: drafts, commitments, decisions, and evidence.",
        object_sidebar_rows=[
            _object_detail_row("Counterparties", " · ".join(thread.counterparties or []) or "No counterparties projected.", "People"),
            _object_detail_row("Drafts", ", ".join(thread.draft_ids or []) or "No active draft ids.", "Drafts"),
            _object_detail_row("Commitments", ", ".join(thread.related_commitment_ids or []) or "No linked commitments yet.", "Ledger"),
            _object_detail_row(
                "Delivery follow-up",
                linked_handoff.summary if linked_handoff is not None else "No linked delivery follow-up is attached to this thread.",
                "Handoff",
                href=f"/app/handoffs/{linked_handoff_ref}" if linked_handoff_ref else "",
            ),
            _object_detail_row(
                "Retry send in EA",
                retry_detail,
                "Action",
                href=f"/app/handoffs/{linked_handoff_ref}" if linked_handoff_ref else "",
                action_href=(
                    f"/app/actions/handoffs/{linked_handoff_ref}/retry-send"
                    if delivery_followup_open
                    else f"/app/actions/threads/{thread_ref}/resume-delivery"
                    if resume_followup_available
                    else ""
                ),
                action_label="Retry send" if delivery_followup_open else "Resume follow-up" if resume_followup_available else "",
                action_method="post" if delivery_followup_open or resume_followup_available else "",
                return_to=f"/app/threads/{thread_ref}" if delivery_followup_open or resume_followup_available else "",
                secondary_action_href=f"/app/handoffs/{linked_handoff_ref}" if linked_handoff_ref else "",
                secondary_action_label="Open handoff" if linked_handoff_ref else "",
                secondary_action_method="get" if linked_handoff_ref else "",
            ),
            _object_detail_row(
                str(thread_google_action.get("label") or "Google delivery action"),
                "Repair Google access before retrying the send path attached to this thread."
                if thread_google_action
                else "No Google reconnect is required for this thread.",
                "Google",
                href="/app/settings/google" if thread_google_action else "",
                action_href=str(thread_google_action.get("href") or ""),
                action_label=str(thread_google_action.get("label") or ""),
                action_method=str(thread_google_action.get("method") or ""),
                return_to=f"/app/threads/{thread_ref}" if thread_google_action else "",
            ),
            _object_detail_row(
                "Manual resolution",
                resolved_manual_detail
                or "Record the real delivery outcome when the operator finished the send outside EA or needs to keep the blocker visible.",
                "Resolution",
                href=f"/app/handoffs/{linked_handoff_ref}" if linked_handoff_ref else "",
                action_href=f"/app/actions/handoffs/{linked_handoff_ref}/complete" if delivery_followup_open else "",
                action_label="Mark sent" if delivery_followup_open else "",
                action_value="sent" if delivery_followup_open else "",
                action_method="post" if delivery_followup_open else "",
                return_to=f"/app/threads/{thread_ref}" if delivery_followup_open else "",
                secondary_action_href=f"/app/actions/handoffs/{linked_handoff_ref}/complete" if delivery_followup_open else "",
                secondary_action_label=manual_resolution_secondary_label if delivery_followup_open else "",
                secondary_action_value=manual_resolution_secondary_value if delivery_followup_open else "",
                secondary_action_method="post" if delivery_followup_open else "",
                secondary_return_to=f"/app/threads/{thread_ref}" if delivery_followup_open else "",
                tertiary_action_href=f"/app/actions/handoffs/{linked_handoff_ref}/complete" if delivery_followup_open else "",
                tertiary_action_label="Waiting on principal" if delivery_followup_open else "",
                tertiary_action_value="waiting_on_principal" if delivery_followup_open else "",
                tertiary_action_method="post" if delivery_followup_open else "",
                tertiary_return_to=f"/app/threads/{thread_ref}" if delivery_followup_open else "",
            ),
        ],
        object_sections=[
            {
                "eyebrow": "Decision links",
                "title": "Related office work",
                "items": [
                    _object_detail_row("Related decisions", ", ".join(thread.related_decision_ids or []) or "No linked decisions.", "Decision"),
                    _object_detail_row("Related commitments", ", ".join(thread.related_commitment_ids or []) or "No linked commitments.", "Commitment"),
                    _object_detail_row("Draft queue", ", ".join(thread.draft_ids or []) or "No active drafts.", "Draft"),
                ],
            },
            {
                "eyebrow": "Evidence",
                "title": "Supporting evidence",
                "items": _evidence_detail_rows(thread.evidence_refs),
            },
            {
                "eyebrow": "Thread history",
                "title": "Recent thread history",
                "items": [
                    _object_detail_row(
                        str(item.event_type or "history").replace("_", " ").title(),
                        " · ".join(
                            part
                            for part in (
                                str(item.detail or "").strip(),
                                str(item.created_at or "")[:19] if item.created_at else "",
                            )
                            if part
                        )
                        or "Thread activity was recorded.",
                        str(item.actor or "thread").strip() or "Thread",
                    )
                    for item in history
                ] or [_object_detail_row("No thread history yet", "No thread events were recorded yet.", "History")],
            },
        ],
    )


@router.get("/app/evidence/{evidence_ref}", response_class=HTMLResponse)
def evidence_detail(
    evidence_ref: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> HTMLResponse:
    status = container.onboarding.status(principal_id=context.principal_id)
    workspace = dict(status.get("workspace") or {})
    product = build_product_service(container)
    evidence = product.get_evidence(
        principal_id=context.principal_id,
        evidence_ref=evidence_ref,
        operator_id=str(context.operator_id or "").strip(),
    )
    if evidence is None:
        raise HTTPException(status_code=404, detail="evidence_not_found")
    product.record_surface_event(
        principal_id=context.principal_id,
        event_type="evidence_opened",
        surface=f"evidence:{evidence_ref}",
        actor=str(context.operator_id or context.access_email or context.principal_id or "browser").strip(),
    )
    href_value = str(evidence.href or "").strip()
    return _render_console_object_detail(
        request=request,
        context=context,
        workspace_label=str(workspace.get("name") or "Executive Workspace"),
        page_title=f"Executive Assistant {evidence.label}",
        current_nav="people",
        console_title=evidence.label,
        console_summary="Evidence provenance, source type, and the objects that currently depend on it.",
        object_kind="Evidence",
        object_title=evidence.label,
        object_summary=evidence.summary or "This evidence ref supports one or more projected product objects.",
        object_meta=[
            {"label": "Source type", "value": str(evidence.source_type or "unknown").replace("_", " ").title()},
            {"label": "Linked objects", "value": str(len(evidence.related_object_refs or []))},
            {"label": "Reference", "value": "External link" if href_value else "Embedded"},
            {"label": "Status", "value": "Available"},
        ],
        object_sidebar_title="Provenance",
        object_sidebar_copy="Evidence should explain why the product surfaced something and what objects currently depend on that fact.",
        object_sidebar_rows=[
            _object_detail_row("Reference", href_value or "No external URL attached to this evidence row.", "Link"),
            _object_detail_row("Related objects", ", ".join(evidence.related_object_refs or []) or "No linked objects yet.", "Objects"),
            _object_detail_row("Source label", evidence.label, "Evidence"),
        ],
        object_sections=[
            {
                "eyebrow": "Evidence summary",
                "title": "What this evidence says",
                "items": [_object_detail_row(evidence.label, evidence.summary or "No summary projected.", str(evidence.source_type or "evidence").title())],
            },
            {
                "eyebrow": "Dependencies",
                "title": "Objects linked to this evidence",
                "items": [
                    _object_detail_row(ref, "This product object currently references the evidence row.", "Linked")
                    for ref in (evidence.related_object_refs or [])
                ]
                or [_object_detail_row("No linked objects", "Nothing else points at this evidence yet.", "Pending")],
            },
        ],
    )


@router.get("/app/rules/{rule_id}", response_class=HTMLResponse)
def rule_detail(
    rule_id: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> HTMLResponse:
    status = container.onboarding.status(principal_id=context.principal_id)
    workspace = dict(status.get("workspace") or {})
    product = build_product_service(container)
    rule = product.get_rule(principal_id=context.principal_id, rule_id=rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="rule_not_found")
    product.record_surface_event(
        principal_id=context.principal_id,
        event_type="rules_opened",
        surface=f"rule:{rule_id}",
        actor=str(context.operator_id or context.access_email or context.principal_id or "browser").strip(),
    )
    simulated_effect = str(rule.simulated_effect or "").strip()
    return _render_console_object_detail(
        request=request,
        context=context,
        workspace_label=str(workspace.get("name") or "Executive Workspace"),
        page_title=f"Executive Assistant {rule.label}",
        current_nav="settings",
        console_title=rule.label,
        console_summary="Rule scope, current value, impact, and whether changes need approval.",
        object_kind="Rules",
        object_title=rule.label,
        object_summary=rule.summary or "This rule shapes how the assistant reads, drafts, sends, remembers, or escalates work.",
        object_meta=[
            {"label": "Scope", "value": str(rule.scope or "workspace").replace("_", " ").title()},
            {"label": "Status", "value": str(rule.status or "active").replace("_", " ").title()},
            {"label": "Current value", "value": str(rule.current_value or "Not set")},
            {"label": "Approval", "value": "Required" if rule.requires_approval else "Direct save"},
        ],
        object_sidebar_title="Rule effect",
        object_sidebar_copy="Rules should be legible in product language: what they change, who they affect, and whether the change needs approval.",
        object_sidebar_rows=[
            _object_detail_row("Impact", rule.impact or "No impact summary projected yet.", "Impact"),
            _object_detail_row("Simulation", simulated_effect or "Run a simulation in Settings before changing this rule.", "Simulate"),
            _object_detail_row("Change posture", "Approval gate applies." if rule.requires_approval else "Directly editable in the current plan.", "Governance"),
        ],
        object_sections=[
            {
                "eyebrow": "Rule summary",
                "title": "Current posture",
                "items": [
                    _object_detail_row(rule.label, rule.summary or "No rule summary projected.", str(rule.status or "active").title()),
                    _object_detail_row("Current value", str(rule.current_value or "Not set"), "Value"),
                ],
            },
            {
                "eyebrow": "Simulation",
                "title": "Expected effect",
                "items": [
                    _object_detail_row("Preview", simulated_effect or "Use the rules surface to simulate this rule before saving changes.", "Effect")
                ],
            },
        ],
    )
