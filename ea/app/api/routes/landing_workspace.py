from __future__ import annotations

import urllib.parse

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.api.dependencies import RequestContext, get_container, get_request_context
from app.api.routes.landing import (
    _console_shell_context,
    _object_detail_row,
    _render_console_object_detail,
    _render_public_template,
)
from app.api.routes.landing_content import APP_NAV_GROUPS
from app.container import AppContainer
from app.product.service import build_product_service

router = APIRouter(tags=["landing"])


def _search_item_key(item: dict[str, object]) -> tuple[str, str, str]:
    return (
        str(item.get("kind") or "").strip(),
        str(item.get("id") or "").strip(),
        str(item.get("href") or "").strip(),
    )


def _google_connect_action(sync: dict[str, object], *, return_to: str = "/app/settings/google") -> dict[str, str]:
    connected = bool(sync.get("connected"))
    token_status = str(sync.get("token_status") or "missing").strip()
    if not connected:
        return {
            "detail": "Google sync cannot start until the workspace is connected.",
            "label": "Connect Google",
            "href": f"/app/actions/google/connect?return_to={return_to}",
            "method": "get",
        }
    if token_status not in {"active", "unknown"}:
        return {
            "detail": str(sync.get("reauth_required_reason") or "Google access needs attention before the next loop."),
            "label": "Reconnect Google",
            "href": f"/app/actions/google/connect?return_to={return_to}",
            "method": "get",
        }
    return {
        "detail": "Google is connected and ready for another sync.",
        "label": "Run sync now",
        "href": f"/app/actions/signals/google/sync?return_to={return_to}",
        "method": "get",
    }


@router.get("/app/settings/plan", response_class=HTMLResponse)
def settings_plan_detail(
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> HTMLResponse:
    status = container.onboarding.status(principal_id=context.principal_id)
    workspace = dict(status.get("workspace") or {})
    product = build_product_service(container)
    diagnostics = product.workspace_diagnostics(principal_id=context.principal_id)
    product.record_surface_event(
        principal_id=context.principal_id,
        event_type="plan_opened",
        surface="settings_plan",
        actor=str(context.operator_id or context.access_email or context.principal_id or "browser").strip(),
    )
    plan = dict(diagnostics.get("plan") or {})
    billing = dict(diagnostics.get("billing") or {})
    entitlements = dict(diagnostics.get("entitlements") or {})
    operators = dict(diagnostics.get("operators") or {})
    commercial = dict(diagnostics.get("commercial") or {})
    selected_channels = [str(value) for value in (diagnostics.get("selected_channels") or []) if str(value).strip()]
    feature_flags = [str(value).replace("_", " ") for value in (entitlements.get("feature_flags") or []) if str(value).strip()]
    warnings = [str(value) for value in (commercial.get("warnings") or []) if str(value).strip()]
    return _render_console_object_detail(
        request=request,
        context=context,
        workspace_label=str(workspace.get("name") or "Executive Workspace"),
        page_title="Executive Assistant Workspace plan",
        current_nav="settings",
        console_title="Workspace plan",
        console_summary="Plan unit, billing posture, messaging scope, and seat boundaries for this office.",
        object_kind="Commercial boundary",
        object_title=str(plan.get("display_name") or "Pilot"),
        object_summary=str(billing.get("contract_note") or "Commercial posture is not yet set."),
        object_meta=[
            {"label": "Plan unit", "value": str(plan.get("unit_of_sale") or "workspace")},
            {"label": "Billing state", "value": str(billing.get("billing_state") or "unknown")},
            {"label": "Invoice status", "value": str(billing.get("invoice_status") or "unknown")},
            {"label": "Support tier", "value": str(billing.get("support_tier") or "standard")},
            {"label": "Seats remaining", "value": str(operators.get("seats_remaining") or 0)},
        ],
        object_sidebar_title="Why this boundary matters",
        object_sidebar_copy="Commercial scope should explain what the office may connect, how many operators may run the queue, and what support posture applies when something goes wrong.",
        object_sidebar_rows=[
            _object_detail_row("Channels", ", ".join(selected_channels) or "Google-first path", "Channels"),
            _object_detail_row("Messaging scope", "Included" if entitlements.get("messaging_channels_enabled") else "Upgrade required for messaging channels", "Entitlement"),
            _object_detail_row("Billing portal", str(billing.get("billing_portal_state") or "guided").replace("_", " "), "Billing"),
            _object_detail_row("Warnings", "; ".join(warnings) or "No current commercial warnings", "Support"),
        ],
        object_sections=[
            {
                "eyebrow": "Plan",
                "title": "Plan and billing posture",
                "items": [
                    _object_detail_row("Workspace plan", str(plan.get("display_name") or "Pilot"), "Plan"),
                    _object_detail_row("Plan unit", str(plan.get("unit_of_sale") or "workspace"), "Plan"),
                    _object_detail_row("Price label", str(billing.get("price_label") or "Custom"), "Billing"),
                    _object_detail_row("Billing state", str(billing.get("billing_state") or "unknown"), "Billing"),
                    _object_detail_row("Invoice status", str(billing.get("invoice_status") or "unknown"), "Billing"),
                    _object_detail_row("Renewal owner", str(billing.get("renewal_owner_role") or "principal").replace("_", " ").title(), "Billing"),
                    _object_detail_row("Contract note", str(billing.get("contract_note") or "No contract note recorded."), "Contract"),
                ],
            },
            {
                "eyebrow": "Entitlements",
                "title": "What this workspace includes",
                "items": [
                    _object_detail_row("Principal seats", str(entitlements.get("principal_seats") or 0), "Seats"),
                    _object_detail_row("Operator seats", str(entitlements.get("operator_seats") or 0), "Seats"),
                    _object_detail_row("Audit retention", str(entitlements.get("audit_retention") or "standard"), "Retention"),
                    _object_detail_row("Feature flags", ", ".join(feature_flags) or "No enabled features", "Flags"),
                ],
            },
            {
                "eyebrow": "Billing and renewal controls",
                "title": "Invoice window, portal, and upgrade path",
                "items": [
                    _object_detail_row("Billing cadence", str(billing.get("billing_cadence") or "custom").replace("_", " "), "Billing"),
                    _object_detail_row("Invoice window", str(billing.get("invoice_window_label") or "Not recorded"), "Billing"),
                    _object_detail_row("Renewal window", str(billing.get("renewal_window_label") or "Not recorded"), "Billing"),
                    _object_detail_row("Billing portal", str(billing.get("billing_portal_state") or "guided").replace("_", " "), "Portal"),
                    _object_detail_row("Upgrade path", str(commercial.get("upgrade_path_label") or "Stay on current plan"), "Upgrade"),
                    _object_detail_row("Blocked action message", str(commercial.get("blocked_action_message") or "No current commercial blocks."), "Commercial"),
                ],
            },
        ],
    )


@router.get("/app/settings/usage", response_class=HTMLResponse)
def settings_usage_detail(
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> HTMLResponse:
    status = container.onboarding.status(principal_id=context.principal_id)
    workspace = dict(status.get("workspace") or {})
    product = build_product_service(container)
    product.record_surface_event(
        principal_id=context.principal_id,
        event_type="usage_opened",
        surface="settings_usage",
        actor=str(context.operator_id or context.access_email or context.principal_id or "browser").strip(),
    )
    diagnostics = product.workspace_diagnostics(principal_id=context.principal_id)
    usage = {str(key): int(value or 0) for key, value in dict(diagnostics.get("usage") or {}).items()}
    analytics = dict(diagnostics.get("analytics") or {})
    reliability = dict(analytics.get("reliability") or {})
    operators = dict(diagnostics.get("operators") or {})
    readiness = dict(diagnostics.get("readiness") or {})
    queue_health = dict(diagnostics.get("queue_health") or {})
    providers = dict(diagnostics.get("providers") or {})
    counts = {str(key): int(value or 0) for key, value in dict(analytics.get("counts") or {}).items()}
    return _render_console_object_detail(
        request=request,
        context=context,
        workspace_label=str(workspace.get("name") or "Executive Workspace"),
        page_title="Executive Assistant Workspace usage",
        current_nav="settings",
        console_title="Usage and activation",
        console_summary="Queue pressure, memo activity, operator load, and time-to-value should stay visible while shaping rules and support posture.",
        object_kind="Usage state",
        object_title="Current office loop",
        object_summary=f"{usage.get('queue_items', 0)} queue items · {usage.get('commitments', 0)} commitments · {usage.get('handoffs', 0)} handoffs",
        object_meta=[
            {"label": "Memo items", "value": str(usage.get("brief_items", 0))},
            {"label": "Queue items", "value": str(usage.get("queue_items", 0))},
            {"label": "Commitments", "value": str(usage.get("commitments", 0))},
            {"label": "Handoffs", "value": str(usage.get("handoffs", 0))},
        ],
        object_sidebar_title="Activation and readiness",
        object_sidebar_copy="Usage only matters when it stays attached to readiness, operator capacity, and the speed with which the workspace reaches first real value.",
        object_sidebar_rows=[
            _object_detail_row("Active operators", str(operators.get("active_count") or 0), "Operators"),
            _object_detail_row("Time to first value", str(analytics.get("time_to_first_value_seconds") or "pending"), "Analytics"),
            _object_detail_row("Churn risk", str(analytics.get("churn_risk") or "unknown").replace("_", " "), "Analytics"),
            _object_detail_row("Readiness", str(readiness.get("detail") or "Runtime posture not recorded."), "Runtime"),
            _object_detail_row("Workspace health score", str(readiness.get("health_score") or 0), "Runtime"),
            _object_detail_row("Provider risk", str(providers.get("risk_state") or "unknown"), "Support"),
        ],
        object_sections=[
            {
                "eyebrow": "Analytics",
                "title": "Product loop signals",
                "items": [
                    _object_detail_row("Memo opened", str(counts.get("memo_opened") or 0), "Analytics"),
                    _object_detail_row("Queue opened", str(counts.get("queue_opened") or 0), "Analytics"),
                    _object_detail_row("Draft approvals granted", str(counts.get("draft_approved") or 0), "Analytics"),
                    _object_detail_row("Draft sent", str(counts.get("draft_sent") or 0), "Analytics"),
                    _object_detail_row("Commitment closed", str(counts.get("commitment_closed") or 0), "Analytics"),
                    _object_detail_row("First value event", str(analytics.get("first_value_event") or "not reached").replace("_", " "), "Analytics"),
                ],
            },
            {
                "eyebrow": "Capacity",
                "title": "Operator and queue load",
                "items": [
                    _object_detail_row("Seats used", str(operators.get("seats_used") or 0), "Operators"),
                    _object_detail_row("Seats remaining", str(operators.get("seats_remaining") or 0), "Operators"),
                    _object_detail_row("Pending approvals", str(counts.get("approval_requested") or 0), "Approvals"),
                    _object_detail_row("Load score", str(queue_health.get("load_score") or 0), "Queue"),
                    _object_detail_row("Retrying delivery", str(queue_health.get("retrying_delivery") or 0), "Queue"),
                    _object_detail_row("Delivery errors", str(queue_health.get("delivery_errors") or 0), "Queue"),
                    _object_detail_row("Fallback lanes", str(providers.get("lanes_with_fallback") or 0), "Provider"),
                    _object_detail_row("Support bundle opened", str(counts.get("support_bundle_opened") or 0), "Support"),
                ],
            },
            {
                "eyebrow": "Reliability",
                "title": "Delivery reliability and access posture",
                "items": [
                    _object_detail_row("Delivery reliability", str(reliability.get("delivery_reliability_state") or "watch"), "Runtime"),
                    _object_detail_row("Delivery success rate", str(reliability.get("delivery_success_rate") if reliability.get("delivery_success_rate") is not None else "n/a"), "Runtime"),
                    _object_detail_row("Access open rate", str(reliability.get("workspace_access_open_rate") if reliability.get("workspace_access_open_rate") is not None else "n/a"), "Runtime"),
                    _object_detail_row("Google sync reliability", str(reliability.get("sync_reliability_state") or "watch"), "Runtime"),
                    _object_detail_row("Delivery failures", str(reliability.get("delivery_failure_total") or 0), "Runtime"),
                ],
            },
            {
                "eyebrow": "Success metrics",
                "title": "Adoption, closure, and correction signals",
                "items": [
                    _object_detail_row("Memo open rate", str(analytics.get("memo_open_rate") or 0), "Analytics"),
                    _object_detail_row("Approval coverage rate", str(analytics.get("approval_coverage_rate") or 0), "Analytics"),
                    _object_detail_row("Approval send rate", str(analytics.get("approval_action_rate") or 0), "Analytics"),
                    _object_detail_row(
                        "Follow-up closeout rate",
                        str(analytics.get("delivery_followup_resolution_rate") if analytics.get("delivery_followup_resolution_rate") is not None else "n/a"),
                        "Analytics",
                    ),
                    _object_detail_row(
                        "Blocked follow-up rate",
                        str(analytics.get("delivery_followup_blocked_rate") if analytics.get("delivery_followup_blocked_rate") is not None else "n/a"),
                        "Analytics",
                    ),
                    _object_detail_row("Commitment close rate", str(analytics.get("commitment_close_rate") or 0), "Analytics"),
                    _object_detail_row("Correction rate", str(analytics.get("correction_rate") or 0), "Analytics"),
                    _object_detail_row("Churn risk", str(analytics.get("churn_risk") or "unknown").replace("_", " "), "Analytics"),
                    _object_detail_row("Success summary", str(analytics.get("success_summary") or "No summary yet."), "Analytics"),
                ],
            },
        ],
    )


@router.get("/app/settings/support", response_class=HTMLResponse)
def settings_support_detail(
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> HTMLResponse:
    status = container.onboarding.status(principal_id=context.principal_id)
    workspace = dict(status.get("workspace") or {})
    product = build_product_service(container)
    product.record_surface_event(
        principal_id=context.principal_id,
        event_type="support_opened",
        surface="settings_support",
        actor=str(context.operator_id or context.access_email or context.principal_id or "browser").strip(),
    )
    bundle = product.workspace_support_bundle(principal_id=context.principal_id)
    analytics = dict(bundle.get("analytics") or {})
    memo_loop = dict(analytics.get("memo_loop") or {})
    reliability = dict(analytics.get("reliability") or {})
    billing = dict(bundle.get("billing") or {})
    approvals = dict(bundle.get("approvals") or {})
    human_tasks = [dict(value) for value in (bundle.get("human_tasks") or [])]
    pending_delivery = [dict(value) for value in (bundle.get("pending_delivery") or [])]
    providers = dict(bundle.get("providers") or {})
    queue_health = dict(bundle.get("queue_health") or {})
    commercial = dict(bundle.get("commercial") or {})
    readiness = dict(bundle.get("readiness") or {})
    product_control = dict(bundle.get("product_control") or {})
    support_verification = dict(bundle.get("support_verification") or {})
    support_grounding = dict(bundle.get("support_assistant_grounding") or {})
    journey_gate = dict(product_control.get("journey_gate_health") or {})
    journey_freshness = dict(product_control.get("journey_gate_freshness") or {})
    support_fallout = dict(product_control.get("support_fallout") or {})
    public_guide_freshness = dict(product_control.get("public_guide_freshness") or {})
    route_stewardship = dict(product_control.get("provider_route_stewardship") or {})
    journey_highlights = [dict(value) for value in list(product_control.get("journey_highlights") or [])]
    return _render_console_object_detail(
        request=request,
        context=context,
        workspace_label=str(workspace.get("name") or "Executive Workspace"),
        page_title="Executive Assistant Workspace support",
        current_nav="settings",
        console_title="Support and diagnostics",
        console_summary="Support posture should explain what is blocked, what is pending human review, what the providers are doing, and what bundle is ready to export.",
        object_kind="Support bundle",
        object_title=str(billing.get("support_tier") or "standard").title(),
        object_summary=str(billing.get("contract_note") or "Support posture is available for export."),
        object_meta=[
            {"label": "Pending approvals", "value": str(len(list(approvals.get("pending") or [])))},
            {"label": "Human tasks", "value": str(len(human_tasks))},
            {"label": "Pending delivery", "value": str(len(pending_delivery))},
            {"label": "Providers", "value": str(providers.get("provider_count") or 0)},
        ],
        object_sidebar_title="What support should answer",
        object_sidebar_copy="A customer-grade support surface should answer what was blocked, what still needs human review, which providers are in play, and what bundle may be exported without reading raw logs.",
        object_sidebar_rows=[
            _object_detail_row("Support tier", str(billing.get("support_tier") or "standard"), "Support"),
            _object_detail_row("Billing state", str(billing.get("billing_state") or "unknown"), "Billing"),
            _object_detail_row("Invoice status", str(billing.get("invoice_status") or "unknown"), "Billing"),
            _object_detail_row("Churn risk", str(bundle.get("analytics", {}).get("churn_risk") or "unknown").replace("_", " "), "Analytics"),
            _object_detail_row("Provider risk", str(providers.get("risk_state") or "unknown"), "Provider"),
            _object_detail_row("Workspace health score", str(readiness.get("health_score") or 0), "Runtime"),
            _object_detail_row("Last memo issue", str(memo_loop.get("last_issue_reason") or "No current memo blocker"), "Memo"),
            _object_detail_row("Journey gate", str(journey_gate.get("state") or "missing").replace("_", " "), "Product"),
            _object_detail_row("Support fallout", str(support_fallout.get("detail") or "No support fallout is mirrored."), "Support"),
            _object_detail_row("Launch readiness", str(product_control.get("launch_readiness") or "No launch note mirrored."), "Product"),
            _object_detail_row("Public guide freshness", str(public_guide_freshness.get("detail") or "No public-guide freshness is mirrored."), "Guide"),
            _object_detail_row("Route review due", str(route_stewardship.get("review_due") or "No route review due published."), "Route"),
            _object_detail_row(
                "Fix verification",
                str(support_verification.get("state") or "not_requested").replace("_", " "),
                "Support",
                action_href=str(support_verification.get("request_action_href") or ""),
                action_label=str(support_verification.get("request_action_label") or ""),
                action_method=str(support_verification.get("request_action_method") or ""),
                return_to="/app/settings/support" if str(support_verification.get("request_action_href") or "").strip() else "",
            ),
            _object_detail_row(
                "Blocked actions",
                ", ".join(str(value).replace("_", " ") for value in (commercial.get("blocked_actions") or [])[:6]) or "No blocked actions",
                "Support",
            ),
            _object_detail_row(
                "Export bundle",
                "Open the support-ready workspace bundle from Settings or Diagnostics export.",
                "Bundle",
                action_href="/app/api/diagnostics/export",
                action_label="Open bundle",
                action_method="get",
            ),
        ],
        object_sections=[
            {
                "eyebrow": "Fix verification",
                "title": "Did the fix reach the channel and workspace link",
                "items": [
                    _object_detail_row(
                        "Verification summary",
                        str(support_verification.get("summary") or "No support verification request is active."),
                        "Support",
                    ),
                    _object_detail_row("Recipient", str(support_verification.get("recipient_email") or "Recipient missing"), "Recipient"),
                    _object_detail_row("Channel receipt", str(support_verification.get("channel_receipt_detail") or "No channel receipt recorded yet."), "Channel"),
                    _object_detail_row("Install receipt", str(support_verification.get("install_receipt_detail") or "No workspace receipt recorded yet."), "Install"),
                    _object_detail_row("Confirmation", str(support_verification.get("confirmation_detail") or "No explicit confirmation recorded yet."), "Confirmation"),
                    _object_detail_row(
                        "Next action",
                        str(support_verification.get("recommended_action") or "No support verification action is recommended."),
                        "Action",
                        action_href=str(support_verification.get("request_action_href") or ""),
                        action_label=str(support_verification.get("request_action_label") or ""),
                        action_method=str(support_verification.get("request_action_method") or ""),
                        return_to="/app/settings/support" if str(support_verification.get("request_action_href") or "").strip() else "",
                        secondary_action_href=str(support_verification.get("delivery_url") or ""),
                        secondary_action_label="Open delivery link" if str(support_verification.get("delivery_url") or "").strip() else "",
                        secondary_action_method="get" if str(support_verification.get("delivery_url") or "").strip() else "",
                        secondary_return_to="/app/settings/support" if str(support_verification.get("delivery_url") or "").strip() else "",
                        tertiary_action_href=str(support_verification.get("access_url") or ""),
                        tertiary_action_label="Open workspace link" if str(support_verification.get("access_url") or "").strip() else "",
                        tertiary_action_method="get" if str(support_verification.get("access_url") or "").strip() else "",
                        tertiary_return_to="/app/settings/support" if str(support_verification.get("access_url") or "").strip() else "",
                    ),
                ],
            },
            {
                "eyebrow": "Grounded packet",
                "title": str(support_grounding.get("title") or "Grounded support packet"),
                "items": (
                    [
                        _object_detail_row(
                            "Summary",
                            str(support_grounding.get("summary") or "Support posture should stay connected to mirrored trust and scorecard truth."),
                            "Grounding",
                        )
                    ]
                    + [
                        _object_detail_row(f"Point {index}", str(item), "Grounding")
                        for index, item in enumerate(list(support_grounding.get("bullets") or [])[:3], start=1)
                    ]
                    + [
                        _object_detail_row(
                            str(action.get("label") or "Action"),
                            str(action.get("href") or ""),
                            "Action",
                            href=str(action.get("href") or ""),
                            action_href=str(action.get("href") or ""),
                            action_label=str(action.get("label") or ""),
                            action_method=str(action.get("method") or "get"),
                        )
                        for action in list(support_grounding.get("actions") or [])[:2]
                    ]
                    + [
                        _object_detail_row(
                            str(source.get("label") or "Source"),
                            str(source.get("path") or ""),
                            str(source.get("as_of") or "Source"),
                        )
                        for source in list(support_grounding.get("sources") or [])[:2]
                    ]
                ),
            },
            {
                "eyebrow": "Product control",
                "title": "Weekly pulse and journey-gate truth",
                "items": [
                    _object_detail_row("Active wave", str(product_control.get("active_wave") or "No active wave mirrored."), "Wave"),
                    _object_detail_row("Wave status", str(product_control.get("active_wave_status") or "unknown").replace("_", " "), "Wave"),
                    _object_detail_row("Pulse summary", str(product_control.get("summary") or "No weekly pulse summary."), "Pulse"),
                    _object_detail_row("Journey gate health", str(journey_gate.get("state") or "missing").replace("_", " "), "Gate"),
                    _object_detail_row("Journey action", str(journey_gate.get("recommended_action") or journey_gate.get("reason") or "No published action."), "Gate"),
                    _object_detail_row("Support fallout", str(support_fallout.get("detail") or "No support fallout is mirrored."), "Support"),
                    _object_detail_row("Launch readiness", str(product_control.get("launch_readiness") or "No launch-readiness note mirrored."), "Launch"),
                    _object_detail_row("Route default", str(route_stewardship.get("default_status") or "No route default note published."), "Route"),
                    _object_detail_row("Canary posture", str(route_stewardship.get("canary_status") or "No canary note published."), "Route"),
                    _object_detail_row("Route review due", str(route_stewardship.get("review_due") or "No route review due published."), "Route"),
                    _object_detail_row("Next checkpoint", str(product_control.get("next_checkpoint_question") or "No checkpoint question mirrored."), "Checkpoint"),
                    _object_detail_row("Journey proof freshness", str(journey_freshness.get("detail") or "No published journey-gate freshness."), "Proof"),
                    _object_detail_row("Public guide freshness", str(public_guide_freshness.get("detail") or "No public-guide freshness is mirrored."), "Guide"),
                ],
            },
            {
                "eyebrow": "Journey proof",
                "title": "What the published release gate is saying",
                "items": [
                    _object_detail_row(
                        str(item.get("title") or "Journey"),
                        " · ".join(
                            part
                            for part in (
                                str(item.get("state") or "unknown").replace("_", " "),
                                str(item.get("recommended_action") or "").strip(),
                                (
                                    f"{int(item.get('support_closure_waiting_count') or 0)} support closures waiting"
                                    if int(item.get("support_closure_waiting_count") or 0)
                                    else ""
                                ),
                                (
                                    f"{int(item.get('support_needs_human_response_count') or 0)} human responses needed"
                                    if int(item.get("support_needs_human_response_count") or 0)
                                    else ""
                                ),
                            )
                            if str(part or "").strip()
                        )
                        or "Published journey-gate evidence is available.",
                        str(item.get("state") or "gate").replace("_", " ").title(),
                    )
                    for item in journey_highlights
                ]
                or [
                    _object_detail_row(
                        "No journey highlights",
                        str(journey_gate.get("recommended_action") or journey_gate.get("reason") or "No published journey-gate highlights."),
                        "Gate",
                    )
                ],
            },
            {
                "eyebrow": "Approvals",
                "title": "Pending review and recent decisions",
                "items": [
                    _object_detail_row(
                        str(item.get("reason") or "Approval pending"),
                        f"{str(item.get('status') or 'pending').replace('_', ' ')} · expires {str(item.get('expires_at') or '')[:10] or 'n/a'}",
                        "Pending",
                    )
                    for item in list(approvals.get("pending") or [])[:6]
                ] or [_object_detail_row("No pending approvals", "Nothing is blocked on approval right now.", "Clear")],
            },
            {
                "eyebrow": "Support bundle",
                "title": "Human tasks and provider posture",
                "items": (
                    [
                        _object_detail_row(
                            str(item.get("brief") or "Human task"),
                            f"{str(item.get('status') or 'pending').replace('_', ' ')} · {str(item.get('assignment_state') or 'unassigned').replace('_', ' ')}",
                            str(item.get("priority") or "normal").title(),
                        )
                        for item in human_tasks[:4]
                    ]
                    + [
                        _object_detail_row(
                            f"{str(item.get('channel') or 'delivery').title()} delivery",
                            f"{str(item.get('recipient') or 'unknown')} · {str(item.get('status') or 'pending').replace('_', ' ')}",
                            "Delivery",
                        )
                        for item in pending_delivery[:2]
                    ]
                )
                or [_object_detail_row("Support surface is clear", "No human tasks or pending delivery are currently blocking the office loop.", "Clear")],
            },
            {
                "eyebrow": "Commercial escalation",
                "title": "Billing path, upgrade path, and customer-facing blockers",
                "items": [
                    _object_detail_row("Billing portal", str(billing.get("billing_portal_state") or "guided").replace("_", " "), "Billing"),
                    _object_detail_row("Invoice window", str(billing.get("invoice_window_label") or "Not recorded"), "Billing"),
                    _object_detail_row("Upgrade path", str(commercial.get("upgrade_path_label") or "Stay on current plan"), "Upgrade"),
                    _object_detail_row("Seat pressure", str(commercial.get("seat_pressure_label") or "No seat pressure"), "Seats"),
                    _object_detail_row("Blocked action message", str(commercial.get("blocked_action_message") or "No current commercial blocks."), "Support"),
                ],
            },
            {
                "eyebrow": "Operational reliability",
                "title": "Delivery, access, and sync posture",
                "items": [
                    _object_detail_row("Delivery reliability", str(reliability.get("delivery_reliability_state") or "watch"), "Runtime"),
                    _object_detail_row("Delivery success rate", str(reliability.get("delivery_success_rate") if reliability.get("delivery_success_rate") is not None else "n/a"), "Runtime"),
                    _object_detail_row("Last memo issue", str(memo_loop.get("last_issue_reason") or "No current memo blocker"), "Memo"),
                    _object_detail_row("Memo fix detail", str(memo_loop.get("last_issue_fix_detail") or "No memo fix needed"), "Memo"),
                    _object_detail_row(
                        "Memo fix target",
                        str(memo_loop.get("last_issue_fix_label") or "No action needed"),
                        "Memo",
                        href=str(memo_loop.get("last_issue_fix_href") or ""),
                        action_href=str(memo_loop.get("last_issue_fix_href") or ""),
                        action_label=str(memo_loop.get("last_issue_fix_label") or ""),
                        action_method="get" if str(memo_loop.get("last_issue_fix_href") or "").strip() else "",
                    ),
                    _object_detail_row("Access reliability", str(reliability.get("access_reliability_state") or "watch"), "Runtime"),
                    _object_detail_row("Access open rate", str(reliability.get("workspace_access_open_rate") if reliability.get("workspace_access_open_rate") is not None else "n/a"), "Runtime"),
                    _object_detail_row("Sync reliability", str(reliability.get("sync_reliability_state") or "watch"), "Runtime"),
                ],
            },
            {
                "eyebrow": "Workspace health",
                "title": "Success metrics and churn risk",
                "items": [
                    _object_detail_row("Memo open rate", str(analytics.get("memo_open_rate") or 0), "Analytics"),
                    _object_detail_row("Approval coverage rate", str(analytics.get("approval_coverage_rate") or 0), "Analytics"),
                    _object_detail_row("Approval send rate", str(analytics.get("approval_action_rate") or 0), "Analytics"),
                    _object_detail_row(
                        "Follow-up closeout rate",
                        str(analytics.get("delivery_followup_resolution_rate") if analytics.get("delivery_followup_resolution_rate") is not None else "n/a"),
                        "Analytics",
                    ),
                    _object_detail_row(
                        "Blocked follow-up rate",
                        str(analytics.get("delivery_followup_blocked_rate") if analytics.get("delivery_followup_blocked_rate") is not None else "n/a"),
                        "Analytics",
                    ),
                    _object_detail_row("Commitment close rate", str(analytics.get("commitment_close_rate") or 0), "Analytics"),
                    _object_detail_row("Correction rate", str(analytics.get("correction_rate") or 0), "Analytics"),
                    _object_detail_row("Churn risk", str(analytics.get("churn_risk") or "unknown").replace("_", " "), "Analytics"),
                    _object_detail_row("Success summary", str(analytics.get("success_summary") or "No summary yet."), "Analytics"),
                ],
            },
            {
                "eyebrow": "Runtime posture",
                "title": "Queue, delivery, and failover pressure",
                "items": [
                    _object_detail_row("Queue state", str(queue_health.get("state") or "healthy"), "Queue"),
                    _object_detail_row("Load score", str(queue_health.get("load_score") or 0), "Queue"),
                    _object_detail_row("Retrying delivery", str(queue_health.get("retrying_delivery") or 0), "Queue"),
                    _object_detail_row("Delivery errors", str(queue_health.get("delivery_errors") or 0), "Queue"),
                    _object_detail_row("Fallback lanes", str(providers.get("lanes_with_fallback") or 0), "Provider"),
                    _object_detail_row("Failover-ready lanes", str(providers.get("failover_ready_lanes") or 0), "Provider"),
                ],
            },
        ],
    )


@router.get("/app/settings/outcomes", response_class=HTMLResponse)
def settings_outcomes_detail(
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> HTMLResponse:
    status = container.onboarding.status(principal_id=context.principal_id)
    workspace = dict(status.get("workspace") or {})
    product = build_product_service(container)
    product.record_surface_event(
        principal_id=context.principal_id,
        event_type="outcomes_opened",
        surface="settings_outcomes",
        actor=str(context.operator_id or context.access_email or context.principal_id or "browser").strip(),
    )
    outcomes = product.workspace_outcomes(principal_id=context.principal_id)
    diagnostics = product.workspace_diagnostics(principal_id=context.principal_id)
    counts = {str(key): int(value or 0) for key, value in dict(outcomes.get("counts") or {}).items()}
    memo_loop = dict(outcomes.get("memo_loop") or {})
    office_loop_proof = dict(outcomes.get("office_loop_proof") or {})
    product_control = dict(diagnostics.get("product_control") or {})
    journey_gate = dict(product_control.get("journey_gate_health") or {})
    journey_freshness = dict(product_control.get("journey_gate_freshness") or {})
    support_fallout = dict(product_control.get("support_fallout") or {})
    public_guide_freshness = dict(product_control.get("public_guide_freshness") or {})
    route_stewardship = dict(product_control.get("provider_route_stewardship") or {})
    proof_checks = [dict(value) for value in list(office_loop_proof.get("checks") or [])]
    return _render_console_object_detail(
        request=request,
        context=context,
        workspace_label=str(workspace.get("name") or "Executive Workspace"),
        page_title="Executive Assistant Workspace outcomes",
        current_nav="settings",
        console_title="Workspace outcomes",
        console_summary="First value, review activity, commitment closure, and correction signals should explain whether this office is actually getting value.",
        object_kind="Outcome posture",
        object_title=str(outcomes.get("success_summary") or "Workspace outcomes"),
        object_summary=(
            f"Memo open rate {outcomes.get('memo_open_rate') or 0} · "
            f"Commitment close rate {outcomes.get('commitment_close_rate') or 0} · "
            f"Proof {str(office_loop_proof.get('state') or 'watch').replace('_', ' ')}"
        ),
        object_meta=[
            {"label": "First value event", "value": str(outcomes.get("first_value_event") or "pending").replace("_", " ")},
            {"label": "Time to first value", "value": str(outcomes.get("time_to_first_value_seconds") or "pending")},
            {"label": "Memo open rate", "value": str(outcomes.get("memo_open_rate") or 0)},
            {"label": "Useful loop days", "value": str(memo_loop.get("days_with_useful_loop") or 0)},
            {"label": "Proof state", "value": str(office_loop_proof.get("state") or "watch").replace("_", " ")},
            {"label": "Churn risk", "value": str(outcomes.get("churn_risk") or "watch").replace("_", " ")},
        ],
        object_sidebar_title="What a healthy loop should show",
        object_sidebar_copy="A healthy office loop reaches first value quickly, gets the memo opened, turns approvals into actions, and closes commitments at a visible rate.",
        object_sidebar_rows=[
            _object_detail_row("Success summary", str(outcomes.get("success_summary") or "No outcome summary yet."), "Summary"),
            _object_detail_row("Office-loop proof", str(office_loop_proof.get("summary") or "No gate summary yet."), "Gate"),
            _object_detail_row("Approval coverage rate", str(outcomes.get("approval_coverage_rate") or 0), "Review"),
            _object_detail_row("Approval send rate", str(outcomes.get("approval_action_rate") or 0), "Review"),
            _object_detail_row(
                "Follow-up closeout rate",
                str(outcomes.get("delivery_followup_resolution_rate") if outcomes.get("delivery_followup_resolution_rate") is not None else "n/a"),
                "Review",
            ),
            _object_detail_row(
                "Blocked follow-up rate",
                str(outcomes.get("delivery_followup_blocked_rate") if outcomes.get("delivery_followup_blocked_rate") is not None else "n/a"),
                "Review",
            ),
            _object_detail_row("Commitment close rate", str(outcomes.get("commitment_close_rate") or 0), "Closure"),
            _object_detail_row("Correction rate", str(outcomes.get("correction_rate") or 0), "Learning"),
            _object_detail_row("Scheduled memo loop", str(memo_loop.get("state") or "watch").replace("_", " "), "Memo"),
            _object_detail_row(
                "Last memo issue",
                str(memo_loop.get("last_issue_reason") or "No current memo blocker"),
                "Memo",
                href=str(memo_loop.get("last_issue_fix_href") or "/app/settings/outcomes"),
                action_href=str(memo_loop.get("last_issue_fix_href") or ""),
                action_label=str(memo_loop.get("last_issue_fix_label") or ""),
                action_method="get" if str(memo_loop.get("last_issue_fix_href") or "").strip() else "",
            ),
        ],
        object_sections=[
            {
                "eyebrow": "Activation",
                "title": "How quickly the workspace reached first value",
                "items": [
                    _object_detail_row("First value event", str(outcomes.get("first_value_event") or "pending").replace("_", " "), "Activation"),
                    _object_detail_row("Time to first value", str(outcomes.get("time_to_first_value_seconds") or "pending"), "Activation"),
                    _object_detail_row("Memo opened", str(counts.get("memo_opened") or 0), "Memo"),
                    _object_detail_row("Approval requested", str(counts.get("approval_requested") or 0), "Approvals"),
                ],
            },
            {
                "eyebrow": "Loop quality",
                "title": "How the daily loop is performing",
                "items": [
                    _object_detail_row("Memo open rate", str(outcomes.get("memo_open_rate") or 0), "Memo"),
                    _object_detail_row("Approval coverage rate", str(outcomes.get("approval_coverage_rate") or 0), "Approvals"),
                    _object_detail_row("Approval send rate", str(outcomes.get("approval_action_rate") or 0), "Approvals"),
                    _object_detail_row(
                        "Follow-up closeout rate",
                        str(outcomes.get("delivery_followup_resolution_rate") if outcomes.get("delivery_followup_resolution_rate") is not None else "n/a"),
                        "Operators",
                    ),
                    _object_detail_row(
                        "Blocked follow-up rate",
                        str(outcomes.get("delivery_followup_blocked_rate") if outcomes.get("delivery_followup_blocked_rate") is not None else "n/a"),
                        "Operators",
                    ),
                    _object_detail_row("Commitment close rate", str(outcomes.get("commitment_close_rate") or 0), "Commitments"),
                    _object_detail_row("Correction rate", str(outcomes.get("correction_rate") or 0), "Learning"),
                    _object_detail_row("Churn risk", str(outcomes.get("churn_risk") or "watch").replace("_", " "), "Risk"),
                ],
            },
            {
                "eyebrow": "Scheduled memo",
                "title": "How the recurring memo loop is proving itself",
                "items": [
                    _object_detail_row("Enabled", str(memo_loop.get("enabled") or False).lower(), "Memo"),
                    _object_detail_row("Cadence", str(memo_loop.get("cadence") or "daily_morning").replace("_", " "), "Memo"),
                    _object_detail_row("Delivery time", f"{memo_loop.get('delivery_time_local') or '08:00'} {memo_loop.get('timezone') or workspace.get('timezone') or 'UTC'}", "Memo"),
                    _object_detail_row("Recipient", str(memo_loop.get("recipient_email") or "waiting for recipient"), "Memo"),
                    _object_detail_row("Useful loop days", str(memo_loop.get("days_with_useful_loop") or 0), "Memo"),
                    _object_detail_row("Last scheduled send", str(memo_loop.get("last_scheduled_sent_at") or "not yet sent"), "Memo"),
                    _object_detail_row("Blocked sends", str(memo_loop.get("scheduled_blocked") or 0), "Memo"),
                    _object_detail_row("Failed sends", str(memo_loop.get("scheduled_failed") or 0), "Memo"),
                    _object_detail_row("Last memo issue", str(memo_loop.get("last_issue_reason") or "No current memo blocker"), "Memo"),
                    _object_detail_row(
                        "Fix target",
                        str(memo_loop.get("last_issue_fix_label") or "No action needed"),
                        "Memo",
                        href=str(memo_loop.get("last_issue_fix_href") or ""),
                        action_href=str(memo_loop.get("last_issue_fix_href") or ""),
                        action_label=str(memo_loop.get("last_issue_fix_label") or ""),
                        action_method="get" if str(memo_loop.get("last_issue_fix_href") or "").strip() else "",
                    ),
                ],
            },
            {
                "eyebrow": "Release gate",
                "title": "What the office-loop release gate would say right now",
                "items": [
                    _object_detail_row("State", str(office_loop_proof.get("state") or "watch").replace("_", " "), "Gate"),
                    _object_detail_row(
                        "Passed checks",
                        f"{int(office_loop_proof.get('passed_checks') or 0)}/{int(office_loop_proof.get('check_total') or 0)}",
                        "Gate",
                    ),
                    _object_detail_row("Summary", str(office_loop_proof.get("summary") or "No gate summary yet."), "Gate"),
                    _object_detail_row("Active product wave", str(product_control.get("active_wave") or "No active wave mirrored."), "Wave"),
                    _object_detail_row("Journey gate", str(journey_gate.get("state") or "missing").replace("_", " "), "Gate"),
                    _object_detail_row("Support fallout", str(support_fallout.get("detail") or "No support fallout is mirrored."), "Support"),
                    _object_detail_row("Launch readiness", str(product_control.get("launch_readiness") or "No launch note mirrored."), "Launch"),
                    _object_detail_row("Route review due", str(route_stewardship.get("review_due") or "No route review due published."), "Route"),
                    _object_detail_row("Journey proof freshness", str(journey_freshness.get("detail") or "No journey-gate freshness mirrored."), "Proof"),
                    _object_detail_row("Public guide freshness", str(public_guide_freshness.get("detail") or "No public-guide freshness mirrored."), "Guide"),
                    *[
                        _object_detail_row(
                            str(row.get("label") or "Check"),
                            (
                                f"{row.get('actual')} / <= {row.get('target_max')}"
                                if row.get("target_max") is not None
                                else f"{row.get('actual')} / {row.get('target')}"
                            ),
                            str(row.get("state") or "watch").replace("_", " ").title(),
                        )
                        for row in proof_checks
                    ],
                ],
            },
            {
                "eyebrow": "Counts",
                "title": "Signals feeding the outcome posture",
                "items": [
                    _object_detail_row("Draft approvals granted", str(counts.get("draft_approved") or 0), "Drafts"),
                    _object_detail_row("Draft sent", str(counts.get("draft_sent") or 0), "Drafts"),
                    _object_detail_row("Send follow-ups created", str(counts.get("draft_send_followup_created") or 0), "Drafts"),
                    _object_detail_row("Send follow-ups closed", str(outcomes.get("delivery_followup_closeout_count") or 0), "Drafts"),
                    _object_detail_row("Blocked send follow-ups", str(outcomes.get("delivery_followup_blocked_count") or 0), "Drafts"),
                    _object_detail_row("Commitment created", str(counts.get("commitment_created") or 0), "Commitments"),
                    _object_detail_row("Commitment closed", str(counts.get("commitment_closed") or 0), "Commitments"),
                    _object_detail_row("Handoff completed", str(counts.get("handoff_completed") or 0), "Handoffs"),
                    _object_detail_row("Memory corrected", str(counts.get("memory_corrected") or 0), "People"),
                    _object_detail_row("Support bundle opened", str(counts.get("support_bundle_opened") or 0), "Support"),
                ],
            },
        ],
    )


@router.get("/app/settings/google", response_class=HTMLResponse)
def settings_google_detail(
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> HTMLResponse:
    status = container.onboarding.status(principal_id=context.principal_id)
    workspace = dict(status.get("workspace") or {})
    product = build_product_service(container)
    product.record_surface_event(
        principal_id=context.principal_id,
        event_type="google_settings_opened",
        surface="settings_google",
        actor=str(context.operator_id or context.access_email or context.principal_id or "browser").strip(),
    )
    sync = product.google_signal_sync_status(principal_id=context.principal_id)
    sync_error = str(request.query_params.get("sync_error") or "").strip()
    sync_status = str(request.query_params.get("sync_status") or "").strip()
    google_error = str(request.query_params.get("google_error") or "").strip()
    covered_sync_candidates = int(sync.get("covered_signal_candidates") or 0)
    action = _google_connect_action(sync, return_to="/app/settings/google")
    sync_summary = f"{str(sync.get('freshness_state') or 'watch').replace('_', ' ')} freshness · {int(sync.get('pending_commitment_candidates') or 0)} pending candidates"
    if covered_sync_candidates:
        sync_summary = f"{sync_summary} · {covered_sync_candidates} covered by drafts"
    return _render_console_object_detail(
        request=request,
        context=context,
        workspace_label=str(workspace.get("name") or "Executive Workspace"),
        page_title="Executive Assistant Google sync",
        current_nav="settings",
        console_title="Google sync",
        console_summary="Google signal sync should be visible in product language: connection state, freshness, staged work, and whether the office needs reauth before the next loop.",
        object_kind="Sync posture",
        object_title=str(sync.get("account_email") or "Google not connected"),
        object_summary=sync_summary,
        object_meta=[
            {"label": "Connected", "value": "Yes" if sync.get("connected") else "No"},
            {"label": "Token status", "value": str(sync.get("token_status") or "missing").replace("_", " ")},
            {"label": "Freshness", "value": str(sync.get("freshness_state") or "watch").replace("_", " ")},
            {"label": "Sync runs", "value": str(sync.get("sync_completed") or 0)},
        ],
        object_sidebar_title="What this should answer",
        object_sidebar_copy="A workspace should be able to see whether Google is connected, when the last sync completed, what signal volume it produced, and whether a reauth is needed before the next office loop.",
        object_sidebar_rows=[
            _object_detail_row("Account email", str(sync.get("account_email") or "Not connected"), "Google"),
            _object_detail_row("Last sync", str(sync.get("last_completed_at") or "Not yet completed"), "Sync"),
            _object_detail_row("Pending commitment candidates", str(sync.get("pending_commitment_candidates") or 0), "Queue"),
            _object_detail_row("Candidates covered by drafts", str(sync.get("covered_signal_candidates") or 0), "Queue"),
            _object_detail_row("Reauth reason", str(sync.get("reauth_required_reason") or "No reauth required"), "Auth"),
            _object_detail_row(
                "Next Google action",
                action["detail"],
                "Action",
                href="/app/settings/google",
                action_href=action["href"],
                action_label=action["label"],
                action_method=action["method"],
                return_to="/app/settings/google",
            ),
            _object_detail_row("Last manual sync", sync_error or google_error or ("Completed" if sync_status == "completed" else "Not recorded"), "Action"),
        ],
        object_sections=[
            {
                "eyebrow": "Connection",
                "title": "Google binding and token posture",
                "items": [
                    _object_detail_row("Connected", "Yes" if sync.get("connected") else "No", "Google"),
                    _object_detail_row("Account email", str(sync.get("account_email") or "Not connected"), "Google"),
                    _object_detail_row("Token status", str(sync.get("token_status") or "missing").replace("_", " "), "Auth"),
                    _object_detail_row("Last refresh", str(sync.get("last_refresh_at") or "Not recorded"), "Auth"),
                    _object_detail_row("Reauth reason", str(sync.get("reauth_required_reason") or "No reauth required"), "Auth"),
                    _object_detail_row(
                        action["label"],
                        action["detail"],
                        "Action",
                        href="/app/settings/google",
                        action_href=action["href"],
                        action_label=action["label"],
                        action_method=action["method"],
                        return_to="/app/settings/google",
                    ),
                ],
            },
            {
                "eyebrow": "Freshness",
                "title": "Latest sync run and queued follow-up work",
                "items": [
                    _object_detail_row("Freshness", str(sync.get("freshness_state") or "watch").replace("_", " "), "Sync"),
                    _object_detail_row("Last completed", str(sync.get("last_completed_at") or "Not yet completed"), "Sync"),
                    _object_detail_row("Age seconds", str(sync.get("age_seconds") if sync.get("age_seconds") is not None else "n/a"), "Sync"),
                    _object_detail_row("Pending commitment candidates", str(sync.get("pending_commitment_candidates") or 0), "Queue"),
                    _object_detail_row("Candidates covered by drafts", str(sync.get("covered_signal_candidates") or 0), "Queue"),
                    _object_detail_row("Office signals ingested", str(sync.get("office_signal_ingested") or 0), "Signals"),
                ],
            },
            {
                "eyebrow": "Volume",
                "title": "What the latest sync actually pulled in",
                "items": [
                    _object_detail_row("Sync runs", str(sync.get("sync_completed") or 0), "Sync"),
                    _object_detail_row("Last synced total", str(sync.get("last_synced_total") or 0), "Signals"),
                    _object_detail_row("Last deduplicated total", str(sync.get("last_deduplicated_total") or 0), "Signals"),
                    _object_detail_row("Last suppressed total", str(sync.get("last_suppressed_total") or 0), "Signals"),
                    _object_detail_row("Gmail signals", str(sync.get("last_gmail_total") or 0), "Gmail"),
                    _object_detail_row("Calendar signals", str(sync.get("last_calendar_total") or 0), "Calendar"),
                ],
            },
        ],
    )


@router.get("/app/settings/trust", response_class=HTMLResponse)
def settings_trust_detail(
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> HTMLResponse:
    status = container.onboarding.status(principal_id=context.principal_id)
    workspace = dict(status.get("workspace") or {})
    product = build_product_service(container)
    product.record_surface_event(
        principal_id=context.principal_id,
        event_type="trust_opened",
        surface="settings_trust",
        actor=str(context.operator_id or context.access_email or context.principal_id or "browser").strip(),
    )
    trust = product.workspace_trust_summary(principal_id=context.principal_id)
    readiness = dict(trust.get("readiness") or {})
    provider_posture = dict(trust.get("provider_posture") or {})
    reliability = dict(trust.get("reliability") or {})
    public_help_grounding = dict(trust.get("public_help_grounding") or {})
    recent_events = [dict(item) for item in (trust.get("recent_events") or [])]
    return _render_console_object_detail(
        request=request,
        context=context,
        workspace_label=str(workspace.get("name") or "Executive Workspace"),
        page_title="Executive Assistant Workspace trust",
        current_nav="settings",
        console_title="Workspace trust",
        console_summary="Evidence, rules, readiness, provider posture, and recent product events should make the assistant legible when the office asks why something happened.",
        object_kind="Trust posture",
        object_title=str(trust.get("workspace_summary") or "Workspace trust posture"),
        object_summary=f"Health score {trust.get('health_score') or 0} · {trust.get('evidence_count') or 0} evidence items · {trust.get('rule_count') or 0} rules",
        object_meta=[
            {"label": "Health score", "value": str(trust.get("health_score") or 0)},
            {"label": "Audit retention", "value": str(trust.get("audit_retention") or "standard")},
            {"label": "Evidence linked", "value": str(trust.get("evidence_count") or 0)},
            {"label": "Rules", "value": str(trust.get("rule_count") or 0)},
        ],
        object_sidebar_title="What should make this trustworthy",
        object_sidebar_copy="Trust is the product of clear readiness, understandable provider posture, reliable delivery, visible rules, and recent evidence of what the system actually did.",
        object_sidebar_rows=[
            _object_detail_row("Workspace summary", str(trust.get("workspace_summary") or "No trust summary yet."), "Summary"),
            _object_detail_row("Readiness", str(readiness.get("detail") or "No readiness detail recorded."), "Runtime"),
            _object_detail_row("Provider risk", str(provider_posture.get("risk_state") or "unknown"), "Provider"),
            _object_detail_row("Delivery reliability", str(reliability.get("delivery") or "watch"), "Runtime"),
            _object_detail_row("Access reliability", str(reliability.get("access") or "watch"), "Runtime"),
            _object_detail_row("Sync reliability", str(reliability.get("sync") or "watch"), "Runtime"),
        ],
        object_sections=[
            {
                "eyebrow": "Readiness",
                "title": "Runtime and provider posture",
                "items": [
                    _object_detail_row("Workspace status", str(readiness.get("status") or "unknown").replace("_", " "), "Runtime"),
                    _object_detail_row("Readiness detail", str(readiness.get("detail") or "No readiness detail recorded."), "Runtime"),
                    _object_detail_row("Provider risk", str(provider_posture.get("risk_state") or "unknown"), "Provider"),
                    _object_detail_row("Risk detail", str(provider_posture.get("risk_detail") or "No provider risk detail recorded."), "Provider"),
                    _object_detail_row("Fallback lanes", str(provider_posture.get("lanes_with_fallback") or 0), "Provider"),
                ],
            },
            {
                "eyebrow": "Trust controls",
                "title": "Evidence, rules, and retention",
                "items": [
                    _object_detail_row("Evidence linked", str(trust.get("evidence_count") or 0), "Evidence"),
                    _object_detail_row("Rule count", str(trust.get("rule_count") or 0), "Rules"),
                    _object_detail_row("Audit retention", str(trust.get("audit_retention") or "standard"), "Audit"),
                    _object_detail_row("Delivery reliability", str(reliability.get("delivery") or "watch"), "Runtime"),
                    _object_detail_row("Access reliability", str(reliability.get("access") or "watch"), "Runtime"),
                    _object_detail_row("Sync reliability", str(reliability.get("sync") or "watch"), "Runtime"),
                ],
            },
            {
                "eyebrow": "Grounded help",
                "title": str(public_help_grounding.get("title") or "Grounded help packet"),
                "items": (
                    [
                        _object_detail_row(
                            "Summary",
                            str(public_help_grounding.get("summary") or "Help posture should compile from mirrored trust and release canon."),
                            "Grounding",
                        )
                    ]
                    + [
                        _object_detail_row(f"Point {index}", str(item), "Grounding")
                        for index, item in enumerate(list(public_help_grounding.get("bullets") or [])[:3], start=1)
                    ]
                    + [
                        _object_detail_row(
                            str(action.get("label") or "Action"),
                            str(action.get("href") or ""),
                            "Action",
                            href=str(action.get("href") or ""),
                            action_href=str(action.get("href") or ""),
                            action_label=str(action.get("label") or ""),
                            action_method=str(action.get("method") or "get"),
                        )
                        for action in list(public_help_grounding.get("actions") or [])[:2]
                    ]
                    + [
                        _object_detail_row(
                            str(source.get("label") or "Source"),
                            str(source.get("path") or ""),
                            str(source.get("as_of") or "Source"),
                        )
                        for source in list(public_help_grounding.get("sources") or [])[:2]
                    ]
                ),
            },
            {
                "eyebrow": "Recent product events",
                "title": "What the assistant recently did",
                "items": [
                    _object_detail_row(
                        str(item.get("label") or item.get("event_type") or "Product event").replace("_", " "),
                        str(item.get("summary") or item.get("detail") or item.get("object_title") or "No event detail recorded."),
                        str(item.get("event_type") or "event").replace("_", " ").title(),
                    )
                    for item in recent_events[:8]
                ] or [_object_detail_row("No recent product events", "Product event history will appear here as the workspace is used.", "History")],
            },
        ],
    )


@router.get("/app/settings/access", response_class=HTMLResponse)
def settings_access_detail(
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> HTMLResponse:
    status = container.onboarding.status(principal_id=context.principal_id)
    workspace = dict(status.get("workspace") or {})
    product = build_product_service(container)
    product.record_surface_event(
        principal_id=context.principal_id,
        event_type="access_settings_opened",
        surface="settings_access",
        actor=str(context.operator_id or context.access_email or context.principal_id or "browser").strip(),
    )
    active_sessions = [dict(item) for item in product.list_workspace_access_sessions(principal_id=context.principal_id, status="active", limit=50)]
    revoked_sessions = [dict(item) for item in product.list_workspace_access_sessions(principal_id=context.principal_id, status="revoked", limit=20)]
    total_opens = sum(
        1
        for item in product.list_office_events(principal_id=context.principal_id, limit=200)
        if str(item.get("event_type") or "").strip() == "workspace_access_session_opened"
    )
    return _render_console_object_detail(
        request=request,
        context=context,
        workspace_label=str(workspace.get("name") or "Executive Workspace"),
        page_title="Executive Assistant Workspace access",
        current_nav="settings",
        console_title="Workspace access",
        console_summary="Active access sessions should be visible and revocable from the browser, not buried in API payloads or support tooling.",
        object_kind="Access posture",
        object_title=f"{len(active_sessions)} active sessions",
        object_summary=f"{total_opens} access opens recorded · {len(revoked_sessions)} revoked sessions",
        object_meta=[
            {"label": "Active sessions", "value": str(len(active_sessions))},
            {"label": "Access opens", "value": str(total_opens)},
            {"label": "Revoked sessions", "value": str(len(revoked_sessions))},
            {"label": "Role mix", "value": ", ".join(sorted({str(item.get('role') or 'principal') for item in active_sessions} or {'principal'}))},
        ],
        object_sidebar_title="What this should make easy",
        object_sidebar_copy="Access should be reviewable in product language: who still has a live link, where it lands, and whether an old session has been revoked cleanly.",
        object_sidebar_rows=[
            _object_detail_row("Active sessions", str(len(active_sessions)), "Access"),
            _object_detail_row("Access opens", str(total_opens), "Telemetry"),
            _object_detail_row("Revoked sessions", str(len(revoked_sessions)), "Access"),
            _object_detail_row("Default operator target", "/admin/office", "Operators"),
            _object_detail_row("Default principal target", "/app/today", "Principal"),
        ],
        object_sections=[
            {
                "eyebrow": "Active sessions",
                "title": "Live workspace access links",
                "items": [
                    _object_detail_row(
                        str(item.get("email") or "unknown"),
                        f"{str(item.get('role') or 'principal').replace('_', ' ')} · {str(item.get('default_target') or '/app/today')} · expires {str(item.get('expires_at') or '')[:19] or 'n/a'}",
                        str(item.get("source_kind") or "workspace_access").replace("_", " ").title(),
                    )
                    for item in active_sessions[:12]
                ] or [_object_detail_row("No active access sessions", "Issue a workspace access link when someone needs direct entry into the workspace.", "Clear")],
            },
            {
                "eyebrow": "Recently revoked",
                "title": "Sessions that no longer authenticate",
                "items": [
                    _object_detail_row(
                        str(item.get("email") or "unknown"),
                        f"revoked by {str(item.get('revoked_by') or 'workspace')} · {str(item.get('revoked_at') or '')[:19] or 'n/a'}",
                        "Revoked",
                    )
                    for item in revoked_sessions[:8]
                ] or [_object_detail_row("No revoked sessions", "Revoked links and sessions will appear here when access is withdrawn.", "History")],
            },
        ],
    )


@router.get("/app/settings/invitations", response_class=HTMLResponse)
def settings_invitations_detail(
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> HTMLResponse:
    status = container.onboarding.status(principal_id=context.principal_id)
    workspace = dict(status.get("workspace") or {})
    product = build_product_service(container)
    product.record_surface_event(
        principal_id=context.principal_id,
        event_type="invitations_opened",
        surface="settings_invitations",
        actor=str(context.operator_id or context.access_email or context.principal_id or "browser").strip(),
    )
    pending = [dict(item) for item in product.list_workspace_invitations(principal_id=context.principal_id, status="pending", limit=50)]
    accepted = [dict(item) for item in product.list_workspace_invitations(principal_id=context.principal_id, status="accepted", limit=20)]
    revoked = [dict(item) for item in product.list_workspace_invitations(principal_id=context.principal_id, status="revoked", limit=20)]
    delivery_rows = [*pending, *accepted, *revoked]
    delivery_failed = sum(1 for item in delivery_rows if str(item.get("email_delivery_status") or "").strip() == "failed")
    delivery_sent = sum(1 for item in delivery_rows if str(item.get("email_delivery_status") or "").strip() == "sent")
    return _render_console_object_detail(
        request=request,
        context=context,
        workspace_label=str(workspace.get("name") or "Executive Workspace"),
        page_title="Executive Assistant Workspace invitations",
        current_nav="settings",
        console_title="Workspace invitations",
        console_summary="Pending invites, accepted roles, and revoked access should be visible where the workspace decides who joins the office loop.",
        object_kind="Invitation posture",
        object_title=f"{len(pending)} pending invitations",
        object_summary=f"{len(accepted)} accepted · {len(revoked)} revoked",
        object_meta=[
            {"label": "Pending", "value": str(len(pending))},
            {"label": "Accepted", "value": str(len(accepted))},
            {"label": "Revoked", "value": str(len(revoked))},
            {"label": "Delivery failures", "value": str(delivery_failed)},
        ],
        object_sidebar_title="What invitation control should answer",
        object_sidebar_copy="Invitation control should answer who is waiting to join, which role they will enter with, and whether an old invite still needs to be withdrawn.",
        object_sidebar_rows=[
            _object_detail_row("Pending invitations", str(len(pending)), "Invites"),
            _object_detail_row("Accepted invitations", str(len(accepted)), "Access"),
            _object_detail_row("Revoked invitations", str(len(revoked)), "Invites"),
            _object_detail_row("Invite emails sent", str(delivery_sent), "Delivery"),
            _object_detail_row("Invite email failures", str(delivery_failed), "Delivery"),
            _object_detail_row("Operator seat policy", "Operator seats are enforced at acceptance time.", "Seats"),
        ],
        object_sections=[
            {
                "eyebrow": "Pending",
                "title": "Invites waiting for acceptance",
                "items": [
                    _object_detail_row(
                        str(item.get("email") or "unknown"),
                        " · ".join(
                            part
                            for part in (
                                str(item.get("role") or "operator").replace("_", " "),
                                f"delivery {str(item.get('email_delivery_status') or 'not attempted').replace('_', ' ')}",
                                f"expires {str(item.get('expires_at') or '')[:19] or 'n/a'}",
                            )
                            if part
                        ),
                        "Pending",
                    )
                    for item in pending[:12]
                ] or [_object_detail_row("No pending invitations", "Create an invite when the workspace needs another reviewer or operator.", "Clear")],
            },
            {
                "eyebrow": "Accepted",
                "title": "People who already joined through an invite",
                "items": [
                    _object_detail_row(
                        str(item.get("email") or "unknown"),
                        " · ".join(
                            part
                            for part in (
                                str(item.get("role") or "operator").replace("_", " "),
                                f"accepted {str(item.get('accepted_at') or '')[:19] or 'n/a'}",
                                f"delivery {str(item.get('email_delivery_status') or 'not attempted').replace('_', ' ')}",
                            )
                            if part
                        ),
                        "Accepted",
                    )
                    for item in accepted[:8]
                ] or [_object_detail_row("No accepted invitations", "Accepted invitations will appear here after the recipient uses the secure invite link.", "History")],
            },
            {
                "eyebrow": "Revoked",
                "title": "Invitations that no longer grant access",
                "items": [
                    _object_detail_row(
                        str(item.get("email") or "unknown"),
                        " · ".join(
                            part
                            for part in (
                                str(item.get("role") or "operator").replace("_", " "),
                                f"revoked {str(item.get('revoked_at') or '')[:19] or 'n/a'}",
                                f"delivery {str(item.get('email_delivery_status') or 'not attempted').replace('_', ' ')}",
                            )
                            if part
                        ),
                        "Revoked",
                    )
                    for item in revoked[:8]
                ] or [_object_detail_row("No revoked invitations", "Revoked invitations will appear here when a pending invite is withdrawn.", "History")],
            },
        ],
    )


@router.get("/app/actions/signals/google/sync")
def app_google_signal_sync(
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> RedirectResponse:
    product = build_product_service(container)
    actor = str(context.operator_id or context.access_email or context.principal_id or "browser").strip()
    return_to = str(request.query_params.get("return_to") or "/app/settings/google").strip() or "/app/settings/google"
    separator = "&" if "?" in return_to else "?"
    try:
        product.sync_google_workspace_signals(
            principal_id=context.principal_id,
            actor=actor,
            email_limit=5,
            calendar_limit=5,
        )
    except RuntimeError as exc:
        error_value = urllib.parse.quote(str(exc or "google_sync_failed"), safe="")
        return RedirectResponse(f"{return_to}{separator}sync_error={error_value}", status_code=303)
    return RedirectResponse(f"{return_to}{separator}sync_status=completed", status_code=303)


@router.get("/app/actions/google/connect")
def app_google_connect(
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> RedirectResponse:
    return_to = str(request.query_params.get("return_to") or "/app/settings/google").strip() or "/app/settings/google"
    scope_bundle = str(request.query_params.get("scope_bundle") or "core").strip() or "core"
    separator = "&" if "?" in return_to else "?"
    try:
        started = container.onboarding.start_google(principal_id=context.principal_id, scope_bundle=scope_bundle)
    except RuntimeError as exc:
        error_value = urllib.parse.quote(str(exc or "google_connect_failed"), safe="")
        return RedirectResponse(f"{return_to}{separator}google_error={error_value}", status_code=303)
    google_start = dict(started.get("google_start") or {})
    auth_url = str(google_start.get("auth_url") or google_start.get("start_url") or "").strip()
    if bool(google_start.get("ready")) and auth_url:
        return RedirectResponse(auth_url, status_code=303)
    detail = urllib.parse.quote(str(google_start.get("detail") or "google_oauth_not_ready"), safe="")
    return RedirectResponse(f"{return_to}{separator}google_error={detail}", status_code=303)


@router.get("/app/search", response_class=HTMLResponse)
def app_search(
    request: Request,
    query: str = Query(default=""),
    limit: int = Query(default=20, ge=1, le=100),
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> HTMLResponse:
    workspace = dict(container.onboarding.status(principal_id=context.principal_id).get("workspace") or {})
    product = build_product_service(container)
    normalized_query = str(query or "").strip()
    items = list(
        product.search_workspace(
            principal_id=context.principal_id,
            query=normalized_query,
            limit=limit,
            operator_id=str(context.operator_id or "").strip(),
        )
    ) if normalized_query else []
    if normalized_query:
        search_return_to = f"/app/search?{urllib.parse.urlencode({'query': normalized_query, 'limit': limit})}"
        items = [
            {
                **item,
                **({"return_to": search_return_to} if str(item.get("action_href") or "").strip() else {}),
            }
            for item in items
        ]
    if normalized_query:
        product.record_surface_event(
            principal_id=context.principal_id,
            event_type="workspace_search_opened",
            surface="search_browser",
            actor=str(context.operator_id or context.access_email or context.principal_id or "browser").strip(),
            metadata={"query": normalized_query[:80], "result_total": len(items)},
        )
    kind_counts: dict[str, int] = {}
    grouped: dict[str, list[dict[str, object]]] = {}
    for item in items:
        kind = str(item.get("kind") or "workspace").strip() or "workspace"
        kind_counts[kind] = int(kind_counts.get(kind) or 0) + 1
        grouped.setdefault(kind, []).append(item)
    primary_items = items[:12]
    primary_keys = {_search_item_key(item) for item in primary_items}
    stats = [
        {"label": "Results", "value": str(len(items))},
        {"label": "People", "value": str(kind_counts.get("person") or 0)},
        {"label": "Decisions", "value": str(kind_counts.get("decision") or 0)},
        {"label": "Commitments", "value": str(kind_counts.get("commitment") or 0)},
        {"label": "Deadlines", "value": str(kind_counts.get("deadline") or 0)},
    ] if normalized_query else []
    cards = [
        {
            "eyebrow": "Workspace search",
            "title": f"Results for “{normalized_query}”" if normalized_query else "Search the workspace",
            "body": (
                f"{len(items)} results across people, threads, commitments, decisions, deadlines, evidence, and rules."
                if normalized_query
                else "Search across people, threads, commitments, decisions, deadlines, evidence, rules, and handoffs from one browser surface."
            ),
            "items": primary_items if normalized_query else [
                {
                    "title": "Try a person, thread, or obligation",
                    "detail": "Search for Sofia, board, investor, renewal, or a concrete commitment title.",
                    "tag": "Hint",
                },
                {
                    "title": "Results stay actionable",
                    "detail": "Search rows keep their native open/approve/close/claim actions when the underlying object supports them.",
                    "tag": "Action",
                },
            ],
        },
        {
            "eyebrow": "How to use it",
            "title": "Search should collapse navigation, not add to it",
            "body": "Use a concrete name, topic, or object label. The first lane gets you to the object; the action button should finish the next step without another hunt.",
            "items": (
                [
                    {
                        "title": f"{kind.title()} results",
                        "detail": f"{count} matched item{'s' if count != 1 else ''}.",
                        "tag": "Kind",
                    }
                    for kind, count in sorted(kind_counts.items(), key=lambda item: (-item[1], item[0]))[:6]
                ]
                if normalized_query
                else [
                    {"title": "People", "detail": "Search names, roles, themes, or relationship signals.", "tag": "Kind"},
                    {"title": "Decisions, deadlines, and commitments", "detail": "Search a board item, follow-up, due obligation, or review object directly.", "tag": "Kind"},
                    {"title": "Evidence and rules", "detail": "Search the explanation layer when you need to answer why something happened.", "tag": "Kind"},
                ]
            ),
        },
    ]
    if normalized_query:
        for kind, rows in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0]))[:4]:
            overflow_rows = [row for row in rows if _search_item_key(row) not in primary_keys][:6]
            if not overflow_rows:
                continue
            cards.append(
                {
                    "eyebrow": "Kind slice",
                    "title": f"{kind.title()} matches",
                    "body": f"Top {kind} hits for “{normalized_query}”.",
                    "items": overflow_rows,
                }
            )
    return _render_public_template(
        request,
        "console_shell.html",
        **_console_shell_context(
            request=request,
            page_title="Executive Assistant Workspace search",
            current_nav="settings",
            context=context,
            console_title="Workspace search",
            console_summary="Search should be the fastest way to jump across the office object model and execute the next obvious action.",
            nav_groups=APP_NAV_GROUPS,
            workspace_label=str(workspace.get("name") or "Executive Workspace"),
            cards=cards,
            stats=stats,
            console_form={
                "method": "get",
                "action": "/app/search",
                "submit_label": "Search",
                "fields": [
                    {
                        "type": "text",
                        "name": "query",
                        "label": "Search the workspace",
                        "value": normalized_query,
                        "placeholder": "Sofia, board, investor, renewal",
                    },
                    {
                        "type": "number",
                        "name": "limit",
                        "label": "Limit",
                        "value": str(limit),
                        "min": "1",
                        "max": "100",
                    },
                ],
            },
        ),
    )
