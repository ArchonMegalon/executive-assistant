from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse

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
                    _object_detail_row("Draft approved", str(counts.get("draft_approved") or 0), "Analytics"),
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
                    _object_detail_row("Approval action rate", str(analytics.get("approval_action_rate") or 0), "Analytics"),
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
    reliability = dict(analytics.get("reliability") or {})
    billing = dict(bundle.get("billing") or {})
    approvals = dict(bundle.get("approvals") or {})
    human_tasks = [dict(value) for value in (bundle.get("human_tasks") or [])]
    pending_delivery = [dict(value) for value in (bundle.get("pending_delivery") or [])]
    providers = dict(bundle.get("providers") or {})
    queue_health = dict(bundle.get("queue_health") or {})
    commercial = dict(bundle.get("commercial") or {})
    readiness = dict(bundle.get("readiness") or {})
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
            _object_detail_row(
                "Blocked actions",
                ", ".join(str(value).replace("_", " ") for value in (commercial.get("blocked_actions") or [])[:6]) or "No blocked actions",
                "Support",
            ),
            _object_detail_row("Export bundle", "Open the support-ready workspace bundle from Settings or Diagnostics export.", "Bundle"),
        ],
        object_sections=[
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
                    _object_detail_row("Approval action rate", str(analytics.get("approval_action_rate") or 0), "Analytics"),
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
    stats = [
        {"label": "Results", "value": str(len(items))},
        {"label": "People", "value": str(kind_counts.get("person") or 0)},
        {"label": "Decisions", "value": str(kind_counts.get("decision") or 0)},
        {"label": "Commitments", "value": str(kind_counts.get("commitment") or 0)},
    ] if normalized_query else []
    cards = [
        {
            "eyebrow": "Workspace search",
            "title": f"Results for “{normalized_query}”" if normalized_query else "Search the workspace",
            "body": (
                f"{len(items)} results across people, threads, commitments, decisions, evidence, and rules."
                if normalized_query
                else "Search across people, threads, commitments, decisions, evidence, rules, and handoffs from one browser surface."
            ),
            "items": items[:12] if normalized_query else [
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
                    {"title": "Decisions and commitments", "detail": "Search a board item, follow-up, due obligation, or review object directly.", "tag": "Kind"},
                    {"title": "Evidence and rules", "detail": "Search the explanation layer when you need to answer why something happened.", "tag": "Kind"},
                ]
            ),
        },
    ]
    if normalized_query:
        for kind, rows in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0]))[:4]:
            cards.append(
                {
                    "eyebrow": "Kind slice",
                    "title": f"{kind.title()} matches",
                    "body": f"Top {kind} hits for “{normalized_query}”.",
                    "items": rows[:6],
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
