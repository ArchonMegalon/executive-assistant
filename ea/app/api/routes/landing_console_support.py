from __future__ import annotations

import json
import os
import urllib.parse

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.api.dependencies import RequestContext, is_operator_context
from app.api.routes.admin_view_models import build_admin_section_payload as _build_admin_section_payload
from app.api.routes.landing_content import ADMIN_NAV_GROUPS, app_nav_groups_for_brand
from app.api.routes.landing_object_support import _object_detail_row, _render_console_object_detail
from app.api.routes.landing_property_support import property_console_context
from app.api.routes.landing_public_support import _console_shell_context, _render_public_template, _today_activation_banner
from app.api.routes.landing_shared_support import (
    _app_live_feed,
    _default_operator_id_for_browser,
    _repo_root,
    operator_bootstrap_defaults,
    operator_bootstrap_needed,
)
from app.api.routes.landing_view_models import (
    app_section_payload as _app_section_payload,
    property_workspace_payload as _property_workspace_payload,
)
from app.api.routes.workspace_view_models import workspace_section_payload as _workspace_section_payload
from app.container import AppContainer
from app.product.service import build_product_service
from app.services.proactive_ooda_approval_capture import (
    default_proactive_ooda_gold_acceptance_path,
    default_proactive_ooda_operator_status_path,
)
from app.services.proactive_ooda_runtime_artifacts import load_runtime_artifact_bundle
from app.services.public_branding import request_brand


def app_root(request: Request) -> RedirectResponse:
    return RedirectResponse(str(request_brand(request).get("app_home") or "/app/today"), status_code=307)


def _load_json_receipt(path) -> dict[str, object]:  # type: ignore[no-untyped-def]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _load_proactive_ooda_control_receipts() -> tuple[dict[str, object], dict[str, object]]:
    root = _repo_root()
    return (
        _load_json_receipt(default_proactive_ooda_operator_status_path(root=root)),
        _load_json_receipt(default_proactive_ooda_gold_acceptance_path(root=root)),
    )


def _humanize_runtime_value(value: object) -> str:
    return str(value or "").strip().replace("_", " ") or "unknown"


def app_shell(
    *,
    section: str,
    request: Request,
    container: AppContainer,
    context: RequestContext,
    run_id: str = "",
) -> HTMLResponse:
    brand = request_brand(request)
    property_brand = brand["key"] == "propertyquarry"
    nav_groups = app_nav_groups_for_brand(brand["key"])
    legacy_redirects = {
        "briefing": "/app/queue",
        "inbox": "/app/queue",
        "follow-ups": "/app/commitments",
        "memory": "/app/people",
        "contacts": "/app/evidence",
        "activity": "/admin/office",
        "channels": "/app/settings",
        "automations": "/app/settings",
    }
    if section in legacy_redirects:
        target = legacy_redirects[section]
        query = str(request.url.query or "").strip()
        if query:
            target = f"{target}?{query}"
        return RedirectResponse(target, status_code=307)
    allowed = {row["key"] for group in nav_groups for row in group["items"]}
    if property_brand:
        allowed.update({"today", "queue", "commitments", "people", "evidence", "activity"})
    else:
        allowed.update(
            {
                "today",
                "queue",
                "commitments",
                "people",
                "evidence",
                "properties",
                "settings",
                "search",
                "channel-loop",
                "briefing",
                "inbox",
                "follow-ups",
                "memory",
                "contacts",
                "activity",
                "channels",
                "automations",
            }
        )
    if section not in allowed:
        raise HTTPException(status_code=404, detail="app_section_not_found")
    resolved_section = section
    current_nav = section
    status = container.onboarding.status(principal_id=context.principal_id)
    if resolved_section == "channel-loop":
        workspace = dict(status.get("workspace") or {})
        product = build_product_service(container)
        pack = product.channel_loop_pack(
            principal_id=context.principal_id,
            operator_id=str(context.operator_id or "").strip(),
        )
        product.record_surface_event(
            principal_id=context.principal_id,
            event_type="channel_loop_opened",
            surface="channel_loop",
            actor=str(context.operator_id or context.access_email or context.principal_id or "browser").strip(),
        )
        stats = [
            {"label": "Memo items", "value": str(int(dict(pack.get("stats") or {}).get("memo_items") or 0))},
            {"label": "Pending drafts", "value": str(int(dict(pack.get("stats") or {}).get("pending_drafts") or 0))},
            {"label": "Commitments", "value": str(int(dict(pack.get("stats") or {}).get("open_commitments") or 0))},
            {"label": "Handoffs", "value": str(int(dict(pack.get("stats") or {}).get("open_handoffs") or 0))},
            {"label": "Decisions", "value": str(int(dict(pack.get("stats") or {}).get("open_decisions") or 0))},
        ]
        return _render_public_template(
            request,
            "console_shell.html",
            **_console_shell_context(
                request=request,
                page_title=f"{brand['name']} Inline Loop",
                current_nav="today",
                context=context,
                console_title=str(pack.get("headline") or "Inline loop"),
                console_summary=str(pack.get("summary") or "Clear the compact office loop."),
                nav_groups=nav_groups,
                workspace_label=str(workspace.get("name") or ("Executive Assistant Workspace" if brand["key"] == "ea" else "PropertyQuarry Workspace")),
                cards=[
                    {
                        "eyebrow": "Inline loop",
                        "title": str(pack.get("headline") or "Inline loop"),
                        "body": str(pack.get("summary") or "Clear the compact office loop."),
                        "items": list(pack.get("items") or []),
                    },
                    *[
                        {
                            "eyebrow": "Channel digest",
                            "title": str(digest.get("headline") or "Channel digest"),
                            "body": " ".join(
                                part
                                for part in (
                                    str(digest.get("summary") or "").strip(),
                                    str(digest.get("preview_text") or "").strip(),
                                )
                                if part
                            ),
                            "items": list(digest.get("items") or []),
                        }
                        for digest in list(pack.get("digests") or [])
                    ],
                ],
                stats=stats,
            ),
        )
    property_sections = {"properties", "shortlist", "research", "profile", "alerts", "billing", "settings"} if property_brand else set()
    core_sections = {"today", "queue", "commitments", "people", "evidence", "activity", "settings"} - property_sections
    if resolved_section in core_sections:
        product = build_product_service(container)
        surface_event = {
            "today": "memo_opened",
            "queue": "queue_opened",
            "commitments": "commitment_ledger_opened",
            "people": "people_graph_opened",
            "evidence": "evidence_opened",
            "activity": "operator_queue_opened",
            "settings": "rules_opened",
        }.get(resolved_section)
        if surface_event:
            product.record_surface_event(
                principal_id=context.principal_id,
                event_type=surface_event,
                surface=resolved_section,
                actor=str(context.operator_id or context.access_email or context.principal_id or "browser").strip(),
            )
        diagnostics = product.workspace_diagnostics(principal_id=context.principal_id)
        outcomes = product.workspace_outcomes(principal_id=context.principal_id) if resolved_section == "settings" else None
        payload = _workspace_section_payload(
            resolved_section,
            product.workspace_snapshot(
                principal_id=context.principal_id,
                operator_id=str(context.operator_id or "").strip(),
            ),
            diagnostics,
            outcomes,
            operator_id=str(context.operator_id or "").strip(),
            brand_key=brand["key"],
        )
    else:
        property_context = (
            property_console_context(
                container=container,
                principal_id=context.principal_id,
                status=status,
                run_id=run_id,
            )
            if resolved_section in property_sections or resolved_section == "properties"
            else None
        )
        if resolved_section in property_sections or resolved_section == "properties":
            build_product_service(container).record_surface_event(
                principal_id=context.principal_id,
                event_type=f"{resolved_section}_opened",
                surface=resolved_section,
                actor=str(context.operator_id or context.access_email or context.principal_id or "browser").strip(),
            )
        if property_brand and resolved_section in property_sections:
            payload = _property_workspace_payload(
                resolved_section,
                status=status,
                property_state=property_context or {},
            )
        else:
            payload = _app_section_payload(
                resolved_section,
                status,
                live_feed=_app_live_feed(container, principal_id=context.principal_id),
                property_context=property_context,
            )
    workspace = dict(status.get("workspace") or {})
    if property_brand and resolved_section in property_sections:
        property_template = "app/property_decision_workbench.html" if resolved_section == "properties" else "app/property_workspace.html"
        return _render_public_template(
            request,
            property_template,
            **{
                **_console_shell_context(
                    request=request,
                    page_title=f"{brand['name']} {payload['title']}",
                    current_nav=current_nav,
                    context=context,
                    console_title=str(payload["title"]),
                    console_summary=str(payload["summary"]),
                    nav_groups=nav_groups,
                    workspace_label=str(workspace.get("name") or "PropertyQuarry Workspace"),
                    cards=list(payload.get("cards") or []),
                    stats=list(payload["stats"]),
                    console_form=dict(payload.get("console_form") or {}),
                ),
                **payload,
            },
        )
    return _render_public_template(
        request,
        "console_shell.html",
        **_console_shell_context(
            request=request,
            page_title=f"{brand['name']} {payload['title']}",
            current_nav=current_nav,
            context=context,
            console_title=str(payload["title"]),
            console_summary=str(payload["summary"]),
            nav_groups=nav_groups,
            workspace_label=str(workspace.get("name") or ("Executive Assistant Workspace" if brand["key"] == "ea" else "PropertyQuarry Workspace")),
            cards=list(payload["cards"]),
            stats=list(payload["stats"]),
            console_form=dict(payload.get("console_form") or {}),
            activation_banner=_today_activation_banner(request=request, status=status) if current_nav == "today" else None,
        ),
    )


def admin_root(
    *,
    request: Request,
    container: AppContainer,
    context: RequestContext,
) -> RedirectResponse:
    redirect = _admin_operator_bootstrap_redirect(
        request=request,
        container=container,
        context=context,
        return_to="/admin/policies",
    )
    if redirect is not None:
        return redirect
    return RedirectResponse("/admin/policies", status_code=307)


def admin_shell(
    *,
    section: str,
    request: Request,
    container: AppContainer,
    context: RequestContext,
) -> HTMLResponse:
    redirect = _admin_operator_bootstrap_redirect(
        request=request,
        container=container,
        context=context,
        return_to=f"/admin/{section}",
    )
    if redirect is not None:
        return redirect
    allowed = {row["key"] for group in ADMIN_NAV_GROUPS for row in group["items"]}
    if section not in allowed:
        raise HTTPException(status_code=404, detail="admin_section_not_found")
    operator_id = str(context.operator_id or "").strip()
    if not operator_id and context.auth_source == "loopback_no_auth":
        operator_id = _default_operator_id_for_browser(container, principal_id=context.principal_id)
    payload = _build_admin_section_payload(
        section,
        container=container,
        principal_id=context.principal_id,
        operator_id=operator_id,
    )
    return _render_public_template(
        request,
        "console_shell.html",
        **_console_shell_context(
            request=request,
            page_title=f"{request_brand(request)['name']} Admin {payload['title']}",
            current_nav=section,
            context=context,
            console_title=str(payload["title"]),
            console_summary=str(payload["summary"]),
            nav_groups=ADMIN_NAV_GROUPS,
            workspace_label="Operator Center",
            cards=list(payload["cards"]),
            stats=list(payload["stats"]),
        ),
    )


def admin_operator_bootstrap(
    *,
    request: Request,
    container: AppContainer,
    context: RequestContext,
):
    return_to = str(request.query_params.get("return_to") or "/admin/policies").strip() or "/admin/policies"
    if is_operator_context(context):
        return RedirectResponse(return_to, status_code=303)
    if not context.authenticated:
        raise HTTPException(status_code=403, detail="auth_required")
    if not operator_bootstrap_needed(container, principal_id=context.principal_id):
        raise HTTPException(status_code=409, detail="operator_profile_bootstrap_not_allowed")
    defaults = operator_bootstrap_defaults(
        principal_id=context.principal_id,
        access_email=str(context.access_email or "").strip().lower(),
    )
    email_hint = str(defaults.get("email_hint") or "").strip()
    return _render_console_object_detail(
        request=request,
        context=context,
        workspace_label="Operator Center",
        page_title=f"{request_brand(request)['name']} Operator Bootstrap",
        current_nav="policies",
        console_title="Create the first operator profile",
        console_summary="Admin surfaces need one active operator profile before operator-grade actions can run.",
        object_kind="Operator bootstrap",
        object_title="Enable operator access for this workspace",
        object_summary="This creates the first active operator profile for the current principal so admin review, approval capture, and handoff actions can authenticate cleanly.",
        object_meta=[
            {"label": "Principal", "value": context.principal_id},
            {"label": "Suggested operator ID", "value": str(defaults.get("operator_id") or "")},
            {"label": "Email hint", "value": email_hint or "None"},
            {"label": "Roles", "value": "operator, reviewer"},
        ],
        object_ooda_title="Why this exists",
        object_ooda_copy="The runtime can auto-authorize loopback operator access once an active operator profile exists. Without that first profile, admin pages and approval capture stay blocked.",
        object_ooda_rows=[
            _object_detail_row(
                "What gets created",
                "One active operator profile bound to this principal with operator and reviewer roles.",
                "Bootstrap",
            ),
            _object_detail_row(
                "What changes next",
                "The next admin request can resolve operator context automatically on loopback and reach the approval surfaces.",
                "Ready",
            ),
        ],
        object_sidebar_title="Bootstrap action",
        object_sidebar_copy="Review the suggested identity, then create the first operator profile for this workspace.",
        object_sidebar_rows=[
            _object_detail_row("Return after create", return_to, "Route"),
            _object_detail_row("Trust tier", "standard", "Policy"),
        ],
        object_sidebar_form={
            "eyebrow": "Bootstrap",
            "title": "Create operator profile",
            "copy": "This is the only path needed before admin pages can accept operator actions for this principal.",
            "method": "post",
            "action": "/admin/actions/bootstrap-operator",
            "submit_label": "Create operator profile",
            "fields": [
                {"type": "hidden", "name": "return_to", "value": return_to},
                {"type": "text", "name": "display_name", "label": "Display name", "value": str(defaults.get("display_name") or "")},
                {"type": "text", "name": "operator_id", "label": "Operator ID", "value": str(defaults.get("operator_id") or "")},
            ],
        },
    )


def admin_proactive_ooda_approval_capture(
    *,
    request: Request,
    container: AppContainer,
    context: RequestContext,
):
    redirect = _admin_operator_bootstrap_redirect(
        request=request,
        container=container,
        context=context,
        return_to="/admin/proactive-ooda/approval",
    )
    if redirect is not None:
        return redirect
    bundle = load_runtime_artifact_bundle(
        root=_repo_root(),
        state_path=os.getenv("EA_PROACTIVE_OODA_STATE_PATH", "state/proactive_ooda_notified.json"),
        receipt_path=os.getenv("EA_PROACTIVE_OODA_RECEIPT_PATH", ""),
    )
    stage_packet = dict(bundle.get("stage_packet") or {})
    safe_work_result = dict(bundle.get("safe_work_result") or {})
    approval_outcome = dict(bundle.get("approval_outcome") or {})
    run_receipt = dict(bundle.get("run_receipt") or {})
    operator_receipt, gold_receipt = _load_proactive_ooda_control_receipts()
    packet_ref = str(stage_packet.get("packet_ref") or "").strip()
    staged_artifact_ref = str(safe_work_result.get("result_ref") or "").strip()
    staged_action_url = str(safe_work_result.get("staged_action_url") or "").strip()
    recommended = _admin_proactive_recommended_label(safe_work_result.get("recommended_option_or_draft"))
    approval_recorded = bool(approval_outcome.get("approval_outcome_recorded"))
    approval_status = str(approval_outcome.get("status") or "").strip() if approval_recorded else "missing"
    evidence_rows = _admin_proactive_evidence_rows(safe_work_result)
    operator_status = str(operator_receipt.get("status") or "").strip()
    operator_summary = str(operator_receipt.get("summary") or "").strip()
    operator_next_action_href = str(operator_receipt.get("next_action_href") or "").strip()
    operator_next_action_label = str(operator_receipt.get("next_action_label") or "").strip()
    operator_next_action_method = str(operator_receipt.get("next_action_method") or "").strip()
    gold_status = str(gold_receipt.get("status") or "").strip()
    gold_summary = str(gold_receipt.get("summary") or "").strip()
    gold_next_action_href = str(gold_receipt.get("next_action_href") or "").strip()
    gold_next_action_label = str(gold_receipt.get("next_action_label") or "").strip()
    gold_next_action_method = str(gold_receipt.get("next_action_method") or "").strip()
    approval_capture_surface = dict(operator_receipt.get("approval_capture_surface") or {})
    control_rows: list[dict[str, str]] = []
    if operator_receipt:
        control_rows.append(
            _object_detail_row(
                "Operator runtime posture",
                " · ".join(part for part in (operator_status, operator_summary) if part) or "No operator runtime posture mirrored.",
                _humanize_runtime_value(operator_receipt.get("operator_action_state") or operator_status).title(),
                action_href=operator_next_action_href,
                action_label=operator_next_action_label,
                action_method=operator_next_action_method,
            )
        )
    if gold_receipt:
        control_rows.append(
            _object_detail_row(
                "Gold proof posture",
                " · ".join(part for part in (gold_status, gold_summary) if part) or "No gold-proof posture mirrored.",
                _humanize_runtime_value(gold_status).title(),
                action_href=gold_next_action_href,
                action_label=gold_next_action_label,
                action_method=gold_next_action_method,
            )
        )
    if approval_capture_surface:
        approval_surface_detail = " · ".join(
            part
            for part in (
                str(approval_capture_surface.get("selected_channel") or "").strip(),
                (
                    f"pending {int(approval_capture_surface.get('current_packet_live_pending_count') or 0)}"
                    if int(approval_capture_surface.get("current_packet_live_pending_count") or 0) > 0
                    else ""
                ),
                str(approval_capture_surface.get("current_packet_callback_latest_status") or "").strip(),
            )
            if part
        ) or "No approval capture surface detail is mirrored."
        control_rows.append(
            _object_detail_row(
                "Telegram approval surface",
                approval_surface_detail,
                "Ready" if bool(approval_capture_surface.get("ready")) else "Pending",
            )
        )
    return _render_console_object_detail(
        request=request,
        context=context,
        workspace_label="Operator Center",
        page_title=f"{request_brand(request)['name']} Proactive OODA Approval",
        current_nav="goals",
        console_title="Record proactive OODA outcome",
        console_summary="Capture the redacted human approval outcome for the current staged packet.",
        object_kind="Proactive OODA",
        object_title="Approval capture",
        object_summary="Use this form after reviewing the staged packet and its safe-work result. The runtime stores only redacted hashes for the evidence note, actor, packet ref, and staged artifact ref.",
        object_meta=[
            {"label": "Notification status", "value": str(run_receipt.get("notification_status") or "unknown")},
            {"label": "Packet ref", "value": packet_ref or "Missing"},
            {"label": "Staged artifact", "value": staged_artifact_ref or "Missing"},
            {"label": "Recorded outcome", "value": approval_status},
            *(
                [{"label": "Operator runtime", "value": operator_status}]
                if operator_status
                else []
            ),
            *(
                [{"label": "Gold posture", "value": gold_status}]
                if gold_status
                else []
            ),
        ],
        object_ooda_title="Current staged decision",
        object_ooda_copy="This surface is grounded in the latest runtime packet, safe-work result, and redacted approval-outcome artifact on disk.",
        object_ooda_rows=[
            _object_detail_row("Recommended result", recommended or "No recommended option is staged yet.", "Decision"),
            _object_detail_row(
                "Staged action URL",
                staged_action_url or "No staged action URL is present for the current packet.",
                "Link",
                href=staged_action_url,
            ),
            _object_detail_row(
                "Approval receipt",
                str(bundle.get("approval_outcome_path") or "") or "No approval receipt path resolved.",
                "Runtime",
            ),
        ],
        object_sidebar_title="Capture form",
        object_sidebar_copy="Record the decision outcome with a short redacted note. Do not paste secrets, full private packet text, or raw identifiers.",
        object_sidebar_rows=[
            _object_detail_row("Run receipt", str(bundle.get("run_receipt_path") or "") or "Missing", "Runtime"),
            _object_detail_row("Stage packet", str(bundle.get("stage_packet_path") or "") or "Missing", "Runtime"),
            _object_detail_row("Safe-work result", str(bundle.get("safe_work_result_path") or "") or "Missing", "Runtime"),
        ],
        object_sections=[
            *(
                [
                    {
                        "eyebrow": "Controls",
                        "title": "Runtime and approval controls",
                        "items": control_rows,
                    }
                ]
                if control_rows
                else []
            ),
            {
                "eyebrow": "Evidence",
                "title": "Live packet evidence",
                "items": evidence_rows
                or [_object_detail_row("No live evidence rows", "The current safe-work result did not expose evidence refs.", "Waiting")],
            }
        ],
        object_sidebar_form={
            "eyebrow": "Approval",
            "title": "Record outcome",
            "copy": "This writes a redacted runtime artifact and rematerializes the proactive OODA gold receipt.",
            "method": "post",
            "action": "/admin/actions/proactive-ooda-evidence",
            "submit_label": "Record proactive outcome",
            "fields": [
                {"type": "hidden", "name": "return_to", "value": "/admin/goals"},
                {
                    "type": "select",
                    "name": "outcome",
                    "label": "Outcome",
                    "options": [
                        {"value": "approved", "label": "Approved", "selected": not approval_recorded or str(approval_outcome.get("outcome") or "").strip() == "approved"},
                        {"value": "rejected", "label": "Rejected", "selected": str(approval_outcome.get("outcome") or "").strip() == "rejected"},
                        {"value": "deferred", "label": "Deferred", "selected": str(approval_outcome.get("outcome") or "").strip() == "deferred"},
                        {"value": "dismissed", "label": "Dismissed", "selected": str(approval_outcome.get("outcome") or "").strip() == "dismissed"},
                    ],
                },
                {
                    "type": "select",
                    "name": "source_kind",
                    "label": "Source",
                    "options": [
                        {"value": "operator", "label": "Operator", "selected": str(approval_outcome.get("source_kind") or "operator").strip() in {"", "operator"}},
                        {"value": "principal", "label": "Principal", "selected": str(approval_outcome.get("source_kind") or "").strip() == "principal"},
                        {"value": "channel_link", "label": "Channel link", "selected": str(approval_outcome.get("source_kind") or "").strip() == "channel_link"},
                    ],
                },
                {
                    "type": "textarea",
                    "name": "evidence",
                    "label": "Redacted note",
                    "value": "",
                    "placeholder": "Short redacted reason, for example: Approved after reviewing the staged shortlist and live comparison.",
                },
                {"type": "text", "name": "packet_ref", "label": "Packet ref", "value": packet_ref},
                {"type": "text", "name": "staged_artifact_ref", "label": "Staged artifact ref", "value": staged_artifact_ref},
            ],
        },
    )


def legacy_setup_redirect() -> RedirectResponse:
    return RedirectResponse("/get-started", status_code=307)


def legacy_privacy_redirect() -> RedirectResponse:
    return RedirectResponse("/security", status_code=307)


def legacy_brief_redirect() -> RedirectResponse:
    return RedirectResponse("/app/queue", status_code=307)


def legacy_google_channel_redirect() -> RedirectResponse:
    return RedirectResponse("/integrations/google", status_code=307)


def legacy_telegram_channel_redirect() -> RedirectResponse:
    return RedirectResponse("/integrations/telegram", status_code=307)


def legacy_whatsapp_channel_redirect() -> RedirectResponse:
    return RedirectResponse("/integrations/whatsapp", status_code=307)


def commitment_candidate_review(
    *,
    candidate_id: str,
    request: Request,
    container: AppContainer,
    context: RequestContext,
) -> HTMLResponse:
    brand = request_brand(request)
    nav_groups = app_nav_groups_for_brand(brand["key"])
    status = container.onboarding.status(principal_id=context.principal_id)
    workspace = dict(status.get("workspace") or {})
    product = build_product_service(container)
    candidate = product.get_commitment_candidate(principal_id=context.principal_id, candidate_id=candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="commitment_candidate_not_found")
    product.record_surface_event(
        principal_id=context.principal_id,
        event_type="commitment_candidate_opened",
        surface=f"candidate:{candidate_id}",
        actor=str(context.operator_id or context.access_email or context.principal_id or "browser").strip(),
    )
    return _render_public_template(
        request,
        "app/commitment_candidate_review.html",
        **{
            **_console_shell_context(
                request=request,
                page_title=f"{brand['name']} Review {candidate.title}",
                current_nav="queue",
                context=context,
                console_title="Review extracted commitment",
                console_summary="Edit the wording, due date, or ownership before this enters the commitment ledger.",
                nav_groups=nav_groups,
                workspace_label=str(workspace.get("name") or brand["workspace_label"]),
                cards=[],
                stats=[
                    {"label": "Confidence", "value": f"{int(candidate.confidence * 100)}%"},
                    {"label": "Counterparty", "value": candidate.counterparty or "None"},
                    {"label": "Suggested due", "value": candidate.suggested_due_at[:10] if candidate.suggested_due_at else "Open"},
                    {"label": "Status", "value": candidate.status.title()},
                ],
            ),
            "candidate": candidate,
        },
    )


def _admin_operator_bootstrap_redirect(
    *,
    request: Request,
    container: AppContainer,
    context: RequestContext,
    return_to: str,
) -> RedirectResponse | None:
    if is_operator_context(context):
        return None
    if operator_bootstrap_needed(container, principal_id=context.principal_id):
        target = f"/admin/bootstrap-operator?return_to={urllib.parse.quote(return_to, safe='')}"
        return RedirectResponse(target, status_code=303)
    raise HTTPException(status_code=403, detail="operator_scope_required")


def _admin_proactive_recommended_label(value: object) -> str:
    if not isinstance(value, dict):
        return str(value or "").strip()
    kind = str(value.get("kind") or "result").replace("_", " ").strip()
    raw = value.get("value")
    if isinstance(raw, dict):
        parts = [
            str(raw.get("label") or raw.get("title") or "").strip(),
            str(raw.get("page_title") or "").strip(),
            str(raw.get("url") or raw.get("link") or raw.get("href") or "").strip(),
        ]
        detail = " | ".join(part for part in parts if part)
        return f"{kind}: {detail}" if detail else kind
    detail = str(raw or "").strip()
    return f"{kind}: {detail}" if detail else kind


def _admin_proactive_evidence_rows(safe_work_result: dict[str, object]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for ref in list(safe_work_result.get("evidence_refs") or []):
        if not isinstance(ref, dict):
            continue
        label = str(ref.get("label") or ref.get("kind") or "Evidence").strip()
        detail_parts = [
            str(ref.get("url") or "").strip(),
            str(ref.get("page_title") or "").strip(),
            "reachable" if ref.get("reachable") is True else "",
        ]
        rows.append(
            _object_detail_row(
                label,
                " · ".join(part for part in detail_parts if part) or "No detail",
                str(ref.get("kind") or "Evidence").strip() or "Evidence",
                href=str(ref.get("final_url") or ref.get("url") or "").strip(),
            )
        )
    return rows
