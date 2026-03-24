from __future__ import annotations

import html
import urllib.parse
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.api.dependencies import (
    RequestContext,
    browser_principal_override_allowed,
    get_cloudflare_access_identity,
    get_container,
    get_request_context,
    require_operator_context,
)
from app.container import AppContainer
from app.services.cloudflare_access import CloudflareAccessIdentity
from app.services.google_oauth import complete_google_oauth_callback

router = APIRouter(tags=["landing"])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[2] / "templates"))

PUBLIC_NAV = (
    {"href": "/product", "label": "Product", "key": "product"},
    {"href": "/integrations", "label": "Integrations", "key": "integrations"},
    {"href": "/security", "label": "Security", "key": "security"},
    {"href": "/pricing", "label": "Pricing", "key": "pricing"},
    {"href": "/docs", "label": "Docs", "key": "docs"},
)

APP_NAV_GROUPS = (
    {
        "label": "Workspace",
        "items": (
            {"href": "/app/today", "label": "Today", "key": "today"},
            {"href": "/app/briefing", "label": "Briefing", "key": "briefing"},
            {"href": "/app/inbox", "label": "Inbox", "key": "inbox"},
            {"href": "/app/follow-ups", "label": "Follow-ups", "key": "follow-ups"},
            {"href": "/app/memory", "label": "Memory", "key": "memory"},
            {"href": "/app/contacts", "label": "Contacts", "key": "contacts"},
        ),
    },
    {
        "label": "Administration",
        "items": (
            {"href": "/app/channels", "label": "Channels", "key": "channels"},
            {"href": "/app/automations", "label": "Automations", "key": "automations"},
            {"href": "/app/activity", "label": "Activity", "key": "activity"},
            {"href": "/app/settings", "label": "Settings", "key": "settings"},
        ),
    },
)

ADMIN_NAV_GROUPS = (
    {
        "label": "Operator control plane",
        "items": (
            {"href": "/admin/policies", "label": "Policies", "key": "policies"},
            {"href": "/admin/providers", "label": "Providers", "key": "providers"},
            {"href": "/admin/audit-trail", "label": "Audit Trail", "key": "audit-trail"},
            {"href": "/admin/operators", "label": "Team / Operators", "key": "operators"},
            {"href": "/admin/api", "label": "API", "key": "api"},
        ),
    },
)

FEATURE_CARDS = (
    {
        "title": "Morning Brief",
        "body": "Start with the ranked brief: what changed overnight, what is blocked, and what needs a reply first.",
    },
    {
        "title": "Draft Replies",
        "body": "Generate source-aware drafts with approvals and receipts instead of generic assistant text.",
    },
    {
        "title": "Follow-ups",
        "body": "Track promises, deadlines, and pending decisions without rebuilding your reminders manually.",
    },
    {
        "title": "Memory",
        "body": "Keep people, themes, commitments, and channel context in a principal-scoped workspace.",
    },
    {
        "title": "Approvals",
        "body": "Human review stays explicit for sensitive sends, edits, and escalations.",
    },
    {
        "title": "Integrations",
        "body": "Connect only the channels you actually use and keep the support contract honest.",
    },
)

HOW_STEPS = (
    {"title": "Create workspace", "body": "Choose the working mode, timezone, and operating posture for this assistant workspace."},
    {"title": "Connect channels", "body": "Start with Google Core, then add Telegram or WhatsApp based on the real operating loop."},
    {"title": "Set privacy & approvals", "body": "Decide what EA can store, draft, and automate before it starts acting on your behalf."},
    {"title": "Get your first brief", "body": "Use the first briefing as the product proof instead of treating setup as the finish line."},
)

PERSONAS = (
    {"title": "Founders", "body": "Stay ahead of investor, recruiting, vendor, and team follow-ups without losing context."},
    {"title": "Chiefs of staff", "body": "Keep leadership communication, handoffs, and commitments visible across channels."},
    {"title": "Small teams", "body": "Organize shared channels, triage requests, and manage approvals in one assistant workspace."},
)

TRUST_CARDS = (
    {"title": "Principal-scoped memory", "body": "Context belongs to the right workspace instead of floating around in stateless prompts."},
    {"title": "Receipts and reasoning", "body": "Drafts and suggestions keep their source trail so operators know why something surfaced."},
    {"title": "Human approvals", "body": "Critical actions remain reviewable. The assistant supports execution without pretending to replace judgment."},
)

PRODUCT_MODULES = (
    {"title": "Morning Brief", "body": "See the day as a ranked set of actions instead of five disconnected inboxes."},
    {"title": "Inbox Triage", "body": "Turn raw message traffic into reply recommendations, handoffs, and follow-up decisions."},
    {"title": "Draft Queue", "body": "Prepare messages with context, approvals, and clear provenance before sending."},
    {"title": "Follow-up Tracker", "body": "Keep commitments and promised next steps visible until they are actually closed."},
    {"title": "Memory", "body": "Retain people, patterns, and context in a durable assistant workspace."},
    {"title": "Approvals", "body": "Keep the operator in control for outbound actions, edits, and high-trust workflows."},
)

PRICING_TIERS = (
    {"title": "Starter", "price": "Pilot", "body": "Single workspace, Google Core first, and the daily brief loop for one operator."},
    {"title": "Executive", "price": "Core", "body": "Inbox, follow-ups, approvals, and multi-channel operating rhythms for active leaders."},
    {"title": "Team", "price": "Custom", "body": "Shared operators, policies, admin controls, and durable workspace memory across a team."},
)

DOC_LINKS = (
    {"title": "API schema", "href": "/openapi.json", "body": "The machine-readable contract for the EA control plane."},
    {"title": "Architecture map", "href": "https://github.com/ArchonMegalon/executive-assistant/blob/main/ARCHITECTURE_MAP.md", "body": "Route map, subsystems, and operator-facing boundaries."},
    {"title": "Runtime overview", "href": "https://github.com/ArchonMegalon/executive-assistant", "body": "Repository overview, deployment notes, and current runtime framing."},
)



def _expected_api_token(container: AppContainer) -> str:
    return str(container.settings.auth.api_token or "").strip()



def _default_principal_id(container: AppContainer) -> str:
    return str(container.settings.auth.default_principal_id or "").strip() or "local-user"



def _token_required(container: AppContainer) -> bool:
    mode = str(getattr(getattr(container.settings, "runtime", None), "mode", "dev") or "dev").strip().lower() or "dev"
    return mode == "prod" or bool(_expected_api_token(container))



def _status_tone(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"connected", "ready_to_connect", "ready_for_brief", "completed", "started", "available"}:
        return "good"
    if normalized in {"planned_business", "export_planned", "guided_manual", "bot_link_requested", "export_intake_complete", "import_acknowledged", "in_progress"}:
        return "warn"
    if normalized in {"credentials_missing", "planned_not_available", "not_selected", "anonymous"}:
        return "muted"
    return "muted"



def _humanize(value: str) -> str:
    return str(value or "").strip().replace("_", " ") or "unknown"



def _form_value(form_data: dict[str, list[str]], key: str, default: str = "") -> str:
    values = form_data.get(key) or []
    return str(values[0] if values else default).strip()



def _form_values(form_data: dict[str, list[str]], key: str) -> tuple[str, ...]:
    return tuple(str(value).strip() for value in (form_data.get(key) or []) if str(value).strip())



def _list_rows(values: object, fallback: tuple[str, ...]) -> list[str]:
    rows: list[str] = []
    if isinstance(values, (list, tuple, set)):
        for value in values:
            normalized = str(value or "").strip()
            if normalized:
                rows.append(normalized)
    elif values:
        normalized = str(values).strip()
        if normalized:
            rows.append(normalized)
    return rows or [str(row) for row in fallback]



def _principal_for_page(
    *,
    container: AppContainer,
    access_identity: CloudflareAccessIdentity | None,
) -> str:
    if access_identity is not None:
        return access_identity.principal_id
    return ""



def _anonymous_onboarding_status() -> dict[str, object]:
    return {
        "principal_id": "",
        "status": "anonymous",
        "workspace": {"name": "Executive Assistant"},
        "selected_channels": [],
        "privacy": {},
        "assistant_modes": [],
        "featured_domains": [],
        "storage_posture": {},
        "channels": {},
        "brief_preview": {},
        "next_step": "Authenticate to view or change onboarding state.",
        "onboarding_id": "",
    }



def _load_status(
    *,
    container: AppContainer,
    access_identity: CloudflareAccessIdentity | None,
) -> tuple[str, dict[str, object]]:
    principal_id = _principal_for_page(container=container, access_identity=access_identity)
    if not principal_id:
        return "", _anonymous_onboarding_status()
    return principal_id, container.onboarding.status(principal_id=principal_id)



def _shared_browser_fields(
    *,
    principal_id: str,
    access_identity: CloudflareAccessIdentity | None,
    container: AppContainer,
) -> str:
    token_field = ""
    if access_identity is None and _token_required(container):
        token_field = """
        <label for=\"api_token\">API token</label>
        <input id=\"api_token\" name=\"api_token\" type=\"password\" placeholder=\"required for browser setup on this host\">
        """
    if access_identity is not None:
        return f"""
        <input type=\"hidden\" name=\"principal_id\" value=\"{html.escape(principal_id)}\">
        {token_field}
        """
    if not browser_principal_override_allowed():
        return f"""
        {token_field}
        <p class=\"helper-note\">Browser setup is bound to the server default principal unless browser principal override is explicitly enabled.</p>
        """
    return f"""
    <label for=\"principal_id\">Principal ID</label>
    <input id=\"principal_id\" name=\"principal_id\" value=\"{html.escape(principal_id)}\" required>
    {token_field}
    """



def _browser_form_context(
    *,
    form_data: dict[str, list[str]],
    container: AppContainer,
    access_identity: CloudflareAccessIdentity | None,
) -> str:
    expected = _expected_api_token(container)
    if access_identity is None and _token_required(container):
        api_token = _form_value(form_data, "api_token", "")
        if not expected or api_token != expected:
            raise HTTPException(status_code=401, detail="auth_required")
    if access_identity is not None:
        requested = _form_value(form_data, "principal_id", access_identity.principal_id)
        if requested and requested != access_identity.principal_id:
            raise HTTPException(status_code=403, detail="principal_scope_mismatch")
        return access_identity.principal_id
    default_principal = _default_principal_id(container)
    requested = _form_value(form_data, "principal_id", "")
    if browser_principal_override_allowed():
        return requested or default_principal
    if requested and requested != default_principal:
        raise HTTPException(status_code=403, detail="principal_override_not_allowed")
    return default_principal



def _channel_cards(channels: dict[str, Any]) -> list[dict[str, str]]:
    ordered = (
        ("google", "Google Core", "/integrations/google"),
        ("telegram", "Telegram", "/integrations/telegram"),
        ("whatsapp", "WhatsApp", "/integrations/whatsapp"),
    )
    cards: list[dict[str, str]] = []
    for key, label, href in ordered:
        channel = dict(channels.get(key) or {})
        cards.append(
            {
                "label": label,
                "href": href,
                "status": _humanize(str(channel.get("status") or "not_selected")),
                "tone": _status_tone(str(channel.get("status") or "not_selected")),
                "detail": str(channel.get("detail") or "Not configured yet."),
                "summary": str(channel.get("bundle_summary") or channel.get("history_import_posture") or ""),
            }
        )
    return cards



def _public_context(
    *,
    request: Request,
    current_nav: str,
    page_title: str,
    principal_id: str,
    status: dict[str, object],
    access_identity: CloudflareAccessIdentity | None,
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    workspace = dict(status.get("workspace") or {})
    channels = dict(status.get("channels") or {})
    preview = dict(status.get("brief_preview") or {})
    selected_channels = [str(row) for row in (status.get("selected_channels") or []) if str(row).strip()]
    context: dict[str, object] = {
        "page_title": page_title,
        "public_nav": PUBLIC_NAV,
        "current_nav": current_nav,
        "access_identity": access_identity,
        "principal_id": principal_id,
        "status": status,
        "workspace": workspace,
        "privacy": dict(status.get("privacy") or {}),
        "channels": channels,
        "channel_cards": _channel_cards(channels),
        "selected_channels_label": ", ".join(selected_channels) if selected_channels else "Google Core recommended",
        "workspace_mode_label": _humanize(str(workspace.get("mode") or "personal")),
        "brief_headline": str(preview.get("headline") or "Turn your channels into a prioritized day."),
        "first_brief_items": _list_rows(
            preview.get("first_brief"),
            (
                "Connect Google Core for the fastest useful morning brief.",
                "Add Telegram or WhatsApp only when the real workflow needs them.",
                "Keep approvals and memory rules explicit before automating actions.",
            ),
        ),
        "suggested_actions": _list_rows(
            preview.get("suggested_actions"),
            (
                "Save the workspace posture and connect your first real channel.",
                "Generate the first brief before widening the integration footprint.",
            ),
        ),
        "trust_notes": _list_rows(
            preview.get("trust_notes"),
            (
                "The public product says what each channel can actually do today.",
                "Approvals and principal-scoped memory are visible product features, not hidden operator facts.",
            ),
        ),
        "top_contacts": _list_rows(preview.get("top_contacts"), ("No contact memory yet.",)),
        "top_themes": _list_rows(preview.get("top_themes"), ("No themes yet.",)),
    }
    if extra:
        context.update(extra)
    return context



def _console_shell_context(
    *,
    request: Request,
    page_title: str,
    current_nav: str,
    context: RequestContext,
    console_title: str,
    console_summary: str,
    nav_groups: tuple[dict[str, object], ...],
    workspace_label: str,
    cards: list[dict[str, object]],
    stats: list[dict[str, str]],
) -> dict[str, object]:
    return {
        "page_title": page_title,
        "current_nav": current_nav,
        "nav_groups": nav_groups,
        "console_title": console_title,
        "console_summary": console_summary,
        "workspace_label": workspace_label,
        "cards": cards,
        "stats": stats,
        "principal_id": context.principal_id,
        "access_email": context.access_email,
        "operator_id": context.operator_id,
    }



def _app_section_payload(section: str, status: dict[str, object]) -> dict[str, object]:
    workspace = dict(status.get("workspace") or {})
    privacy = dict(status.get("privacy") or {})
    preview = dict(status.get("brief_preview") or {})
    channels = dict(status.get("channels") or {})
    channel_cards = _channel_cards(channels)
    selected = [str(value) for value in (status.get("selected_channels") or []) if str(value).strip()]
    status_label = _humanize(str(status.get("status") or "draft"))
    stats = [
        {"label": "Workspace mode", "value": _humanize(str(workspace.get("mode") or "personal"))},
        {"label": "Selected channels", "value": str(len(selected))},
        {"label": "Status", "value": status_label},
        {"label": "Approvals", "value": "on" if privacy.get("allow_drafts") else "review first"},
    ]
    first_brief = _list_rows(preview.get("first_brief"), ("Connect Google Core to generate the first briefing.",))
    suggested = _list_rows(preview.get("suggested_actions"), ("Finish onboarding and request the first brief.",))
    trust_notes = _list_rows(preview.get("trust_notes"), ("Keep approvals and memory rules explicit.",))
    contacts = _list_rows(preview.get("top_contacts"), ("No contacts surfaced yet.",))
    themes = _list_rows(preview.get("top_themes"), ("No themes surfaced yet.",))
    privacy_lines = [
        f"Retention: {_humanize(str(privacy.get('retention_mode') or 'not set'))}",
        f"Drafts: {'allowed' if privacy.get('allow_drafts') else 'manual only'}",
        f"Action suggestions: {'allowed' if privacy.get('allow_action_suggestions') else 'off'}",
        f"Automatic briefs: {'allowed' if privacy.get('allow_auto_briefs') else 'off'}",
    ]
    channel_lines = [f"{card['label']}: {card['status']} — {card['detail']}" for card in channel_cards]

    mapping: dict[str, dict[str, object]] = {
        "today": {
            "title": "Today",
            "summary": str(preview.get("headline") or status.get("next_step") or "Your operating day starts with the morning brief."),
            "cards": [
                {"eyebrow": "Morning brief", "title": "What matters first", "items": first_brief},
                {"eyebrow": "Suggested actions", "title": "Next moves", "items": suggested},
                {"eyebrow": "Channels", "title": "Connected posture", "items": channel_lines},
                {"eyebrow": "Trust", "title": "Why the system surfaced this", "items": trust_notes},
            ],
        },
        "briefing": {
            "title": "Briefing",
            "summary": str(preview.get("headline") or "Briefings summarize priorities, drafts, and follow-ups from the channels you actually connected."),
            "cards": [
                {"eyebrow": "Brief preview", "title": "Morning brief", "items": first_brief},
                {"eyebrow": "Themes", "title": "Recurring topics", "items": themes},
                {"eyebrow": "Contacts", "title": "People in the loop", "items": contacts},
                {"eyebrow": "Actions", "title": "Recommended next steps", "items": suggested},
            ],
        },
        "inbox": {
            "title": "Inbox",
            "summary": "This surface should lead with drafts, reply priorities, and channel-aware follow-up suggestions.",
            "cards": [
                {"eyebrow": "Draft queue", "title": "Operator review posture", "items": ["Drafts are explicit when approvals are enabled.", "Source-aware replies belong here instead of on the marketing homepage."]},
                {"eyebrow": "Readiness", "title": "What the assistant can currently see", "items": channel_lines},
                {"eyebrow": "Priorities", "title": "What would bubble up next", "items": first_brief},
            ],
        },
        "follow-ups": {
            "title": "Follow-ups",
            "summary": "Follow-ups turn commitments and missed responses into a visible operating list.",
            "cards": [
                {"eyebrow": "Follow-up queue", "title": "What needs a nudge", "items": suggested},
                {"eyebrow": "Why this works", "title": "Memory + approvals", "items": trust_notes},
                {"eyebrow": "Channel coverage", "title": "Where follow-ups can start", "items": channel_lines},
            ],
        },
        "memory": {
            "title": "Memory",
            "summary": "Memory should feel like a workspace asset, not a hidden implementation detail.",
            "cards": [
                {"eyebrow": "Top themes", "title": "What keeps recurring", "items": themes},
                {"eyebrow": "Contacts", "title": "Who shows up most", "items": contacts},
                {"eyebrow": "Retention policy", "title": "What EA is allowed to keep", "items": privacy_lines},
            ],
        },
        "contacts": {
            "title": "Contacts",
            "summary": "Contacts should organize people, thread history, and follow-up posture around the real operator loop.",
            "cards": [
                {"eyebrow": "People", "title": "Contacts in the current brief", "items": contacts},
                {"eyebrow": "Themes", "title": "Topics around those contacts", "items": themes},
                {"eyebrow": "Channels", "title": "Where those relationships live", "items": channel_lines},
            ],
        },
        "channels": {
            "title": "Channels",
            "summary": "Integrations belong in the product, but they should read like contracts and readiness, not a developer admin page.",
            "cards": [
                {"eyebrow": "Google", "title": channel_cards[0]["label"], "items": [channel_cards[0]["detail"], channel_cards[0]["summary"] or "Google Core is the recommended first connection."]},
                {"eyebrow": "Telegram", "title": channel_cards[1]["label"], "items": [channel_cards[1]["detail"], channel_cards[1]["summary"] or "Personal identity and bot install stay distinct." ]},
                {"eyebrow": "WhatsApp", "title": channel_cards[2]["label"], "items": [channel_cards[2]["detail"], channel_cards[2]["summary"] or "Business onboarding and export intake stay separate." ]},
            ],
        },
        "automations": {
            "title": "Automations",
            "summary": "Automations should stay explicit, approval-aware, and scoped by the privacy posture you already saved.",
            "cards": [
                {"eyebrow": "Assistant posture", "title": "Current automation rules", "items": privacy_lines},
                {"eyebrow": "Suggested automations", "title": "What to unlock next", "items": suggested},
                {"eyebrow": "Trust", "title": "Guardrails", "items": trust_notes},
            ],
        },
        "activity": {
            "title": "Activity",
            "summary": "Activity should summarize the operator-visible state changes without exposing the runtime internals to buyers.",
            "cards": [
                {"eyebrow": "Onboarding", "title": "Current state", "items": [f"Status: {status_label}", f"Onboarding id: {status.get('onboarding_id') or 'not started'}", f"Next step: {status.get('next_step') or 'None'}"]},
                {"eyebrow": "Channels", "title": "Recent surface state", "items": channel_lines},
                {"eyebrow": "Trust", "title": "Why activity matters", "items": trust_notes},
            ],
        },
        "settings": {
            "title": "Settings",
            "summary": "Workspace settings should stay in the authenticated product shell, not in the public marketing layer.",
            "cards": [
                {"eyebrow": "Workspace", "title": "Current workspace posture", "items": [f"Name: {workspace.get('name') or 'Executive Assistant'}", f"Mode: {_humanize(str(workspace.get('mode') or 'personal'))}", f"Timezone: {workspace.get('timezone') or 'unspecified'}", f"Region: {workspace.get('region') or 'unspecified'}"]},
                {"eyebrow": "Privacy", "title": "Assistant behavior", "items": privacy_lines},
                {"eyebrow": "Channels", "title": "Selected integrations", "items": channel_lines},
            ],
        },
    }
    return {"stats": stats, **mapping[section]}



def _admin_section_payload(section: str) -> dict[str, object]:
    mapping: dict[str, dict[str, object]] = {
        "policies": {
            "title": "Policies",
            "summary": "Operator-only controls for approval rules, task contracts, and promoted skills.",
            "cards": [
                {"eyebrow": "Policy", "title": "Runtime policy endpoints", "items": ["/v1/policy", "/v1/tasks/contracts", "/v1/skills"]},
                {"eyebrow": "Why it matters", "title": "Keep the product shell separate", "items": ["Buyers should see the assistant workflow.", "Operators should see the policy plane."]},
            ],
        },
        "providers": {
            "title": "Providers",
            "summary": "Bindings, 1min state, and operator-only control-plane views belong here, not in the main buyer navigation.",
            "cards": [
                {"eyebrow": "Provider APIs", "title": "Registry and health", "items": ["/v1/providers/registry", "/v1/providers/states", "/v1/providers/onemin/aggregate"]},
                {"eyebrow": "Operational focus", "title": "What this surface is for", "items": ["Capacity admission", "Binding state", "Runway and burn"]},
            ],
        },
        "audit-trail": {
            "title": "Audit Trail",
            "summary": "Evidence, telemetry, and delivery state should be visible to operators without leaking into the public marketing story.",
            "cards": [
                {"eyebrow": "Audit", "title": "Trace surfaces", "items": ["/v1/runtime/lanes/telemetry", "/v1/evidence", "/v1/delivery/pending"]},
                {"eyebrow": "Goal", "title": "What the operator needs", "items": ["Receipts", "Execution state", "Delivery confirmations"]},
            ],
        },
        "operators": {
            "title": "Team / Operators",
            "summary": "Operator identity, backlog, and approval work stay in the admin surface.",
            "cards": [
                {"eyebrow": "Human runtime", "title": "Operator endpoints", "items": ["/v1/human/operators", "/v1/human/tasks"]},
                {"eyebrow": "Trust boundary", "title": "Why this is separate", "items": ["Operator identity is not a tenant-facing product setting.", "Audit trails depend on trusted operator records."]},
            ],
        },
        "api": {
            "title": "API",
            "summary": "The control-plane contract is part of the operator surface, not the buyer homepage.",
            "cards": [
                {"eyebrow": "OpenAPI", "title": "Schemas and runtime entrypoints", "items": ["/openapi.json", "/v1/plans/compile", "/v1/rewrite", "/v1/responses"]},
                {"eyebrow": "Docs", "title": "Reference material", "items": ["README", "ARCHITECTURE_MAP", "CI smoke suite"]},
            ],
        },
    }
    payload = mapping[section]
    return {
        "stats": [
            {"label": "Surface", "value": "admin"},
            {"label": "Access", "value": "operator-only"},
            {"label": "Audience", "value": "operators"},
            {"label": "Goal", "value": "control plane"},
        ],
        **payload,
    }



def _render_public_template(request: Request, template_name: str, **context: Any) -> HTMLResponse:
    context.setdefault("request", request)
    return templates.TemplateResponse(request, template_name, context)


@router.get("/", response_class=HTMLResponse)
def landing(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> HTMLResponse:
    principal_id, status = _load_status(container=container, access_identity=access_identity)
    return _render_public_template(
        request,
        "marketing_home.html",
        **_public_context(
            request=request,
            current_nav="product",
            page_title="Executive Assistant",
            principal_id=principal_id,
            status=status,
            access_identity=access_identity,
            extra={
                "feature_cards": FEATURE_CARDS,
                "how_steps": HOW_STEPS,
                "personas": PERSONAS,
                "trust_cards": TRUST_CARDS,
            },
        ),
    )


@router.get("/product", response_class=HTMLResponse)
def product_page(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> HTMLResponse:
    principal_id, status = _load_status(container=container, access_identity=access_identity)
    return _render_public_template(
        request,
        "product_page.html",
        **_public_context(
            request=request,
            current_nav="product",
            page_title="Executive Assistant Product",
            principal_id=principal_id,
            status=status,
            access_identity=access_identity,
            extra={"product_modules": PRODUCT_MODULES, "app_nav_groups": APP_NAV_GROUPS},
        ),
    )


@router.get("/integrations", response_class=HTMLResponse)
def integrations_page(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> HTMLResponse:
    principal_id, status = _load_status(container=container, access_identity=access_identity)
    return _render_public_template(
        request,
        "integrations_page.html",
        **_public_context(
            request=request,
            current_nav="integrations",
            page_title="Executive Assistant Integrations",
            principal_id=principal_id,
            status=status,
            access_identity=access_identity,
        ),
    )


@router.get("/integrations/{channel_name}", response_class=HTMLResponse)
def integration_detail(
    channel_name: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> HTMLResponse:
    principal_id, status = _load_status(container=container, access_identity=access_identity)
    channels = dict(status.get("channels") or {})
    mapping = {
        "google": {
            "title": "Google Core",
            "eyebrow": "Google",
            "detail_points": (
                "Start with Google Core unless you already know you need wider inbox actions.",
                "Google Core is enough for drafts, delivery verification, calendar context, contacts context, and a useful first brief.",
                "Full Workspace is the explicit upgrade path when you need broader inbox or Drive context.",
            ),
            "body_points": (
                "Explain permissions in plain language first and raw scopes second.",
                "Show a real connected account and a real first success instead of treating consent as the finish line.",
                "Keep Google as the recommended first connection in the public product flow.",
            ),
        },
        "telegram": {
            "title": "Telegram",
            "eyebrow": "Telegram",
            "detail_points": (
                "Personal identity linking and official bot installation are separate decisions.",
                "Login alone does not imply generic history import.",
                "Future-only, import-later, and manual-forward are distinct promises and should stay distinct in the UI.",
            ),
            "body_points": (
                "Ask first whether this is a personal Telegram setup or a bot rollout.",
                "Record where EA will operate: DM, groups, or channels.",
                "Treat the bot as the durable operating surface once installed and verified.",
            ),
        },
        "whatsapp": {
            "title": "WhatsApp",
            "eyebrow": "WhatsApp",
            "detail_points": (
                "Business onboarding and export intake are separate supported paths.",
                "The assistant should not promise generic automated history download outside those paths.",
                "Live messaging and manual history intake should stay visibly distinct in the product contract.",
            ),
            "body_points": (
                "Use Business onboarding for the long-term live assistant path.",
                "Use export intake for personal or unsupported cases without pretending it is live sync.",
                "Keep media inclusion, history source, and future live sync as separate explicit choices.",
            ),
        },
    }
    current = mapping.get(channel_name)
    if current is None:
        raise HTTPException(status_code=404, detail="integration_not_found")
    channel = dict(channels.get(channel_name) or {})
    return _render_public_template(
        request,
        "channel_detail.html",
        **_public_context(
            request=request,
            current_nav="integrations",
            page_title=f"Executive Assistant {current['title']}",
            principal_id=principal_id,
            status=status,
            access_identity=access_identity,
            extra={
                "channel": channel,
                "channel_title": current["title"],
                "channel_eyebrow": current["eyebrow"],
                "detail_points": current["detail_points"],
                "body_points": current["body_points"],
            },
        ),
    )


@router.get("/security", response_class=HTMLResponse)
def security_page(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> HTMLResponse:
    principal_id, status = _load_status(container=container, access_identity=access_identity)
    return _render_public_template(
        request,
        "security_page.html",
        **_public_context(
            request=request,
            current_nav="security",
            page_title="Executive Assistant Security",
            principal_id=principal_id,
            status=status,
            access_identity=access_identity,
            extra={"trust_cards": TRUST_CARDS},
        ),
    )


@router.get("/pricing", response_class=HTMLResponse)
def pricing_page(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> HTMLResponse:
    principal_id, status = _load_status(container=container, access_identity=access_identity)
    return _render_public_template(
        request,
        "pricing_page.html",
        **_public_context(
            request=request,
            current_nav="pricing",
            page_title="Executive Assistant Pricing",
            principal_id=principal_id,
            status=status,
            access_identity=access_identity,
            extra={"pricing_tiers": PRICING_TIERS},
        ),
    )


@router.get("/docs", response_class=HTMLResponse)
def docs_page(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> HTMLResponse:
    principal_id, status = _load_status(container=container, access_identity=access_identity)
    return _render_public_template(
        request,
        "docs_page.html",
        **_public_context(
            request=request,
            current_nav="docs",
            page_title="Executive Assistant Docs",
            principal_id=principal_id,
            status=status,
            access_identity=access_identity,
            extra={"doc_links": DOC_LINKS},
        ),
    )


@router.get("/get-started", response_class=HTMLResponse)
def get_started(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> HTMLResponse:
    principal_id, status = _load_status(container=container, access_identity=access_identity)
    channels = dict(status.get("channels") or {})
    workspace = dict(status.get("workspace") or {})
    privacy = dict(status.get("privacy") or {})
    selected_channels = {str(value) for value in (status.get("selected_channels") or []) if str(value).strip()}
    google = dict(channels.get("google") or {})
    return _render_public_template(
        request,
        "get_started.html",
        **_public_context(
            request=request,
            current_nav="product",
            page_title="Get started with Executive Assistant",
            principal_id=principal_id,
            status=status,
            access_identity=access_identity,
            extra={
                "workspace": workspace,
                "privacy": privacy,
                "channels": channels,
                "selected_channels": selected_channels,
                "google": google,
                "shared_browser_fields": _shared_browser_fields(
                    principal_id=principal_id,
                    access_identity=access_identity,
                    container=container,
                ),
            },
        ),
    )


@router.get("/app", response_class=HTMLResponse)
def app_root() -> RedirectResponse:
    return RedirectResponse("/app/today", status_code=307)


@router.get("/app/{section}", response_class=HTMLResponse)
def app_shell(
    section: str,
    request: Request,
    container: AppContainer = Depends(get_container),
    context: RequestContext = Depends(get_request_context),
) -> HTMLResponse:
    allowed = {row["key"] for group in APP_NAV_GROUPS for row in group["items"]}
    if section not in allowed:
        raise HTTPException(status_code=404, detail="app_section_not_found")
    status = container.onboarding.status(principal_id=context.principal_id)
    payload = _app_section_payload(section, status)
    workspace = dict(status.get("workspace") or {})
    return _render_public_template(
        request,
        "console_shell.html",
        **_console_shell_context(
            request=request,
            page_title=f"Executive Assistant {payload['title']}",
            current_nav=section,
            context=context,
            console_title=str(payload["title"]),
            console_summary=str(payload["summary"]),
            nav_groups=APP_NAV_GROUPS,
            workspace_label=str(workspace.get("name") or "Executive Workspace"),
            cards=list(payload["cards"]),
            stats=list(payload["stats"]),
        ),
    )


@router.get("/admin", response_class=HTMLResponse)
def admin_root() -> RedirectResponse:
    return RedirectResponse("/admin/policies", status_code=307)


@router.get("/admin/{section}", response_class=HTMLResponse)
def admin_shell(
    section: str,
    request: Request,
    context: RequestContext = Depends(get_request_context),
    _: None = Depends(require_operator_context),
) -> HTMLResponse:
    allowed = {row["key"] for group in ADMIN_NAV_GROUPS for row in group["items"]}
    if section not in allowed:
        raise HTTPException(status_code=404, detail="admin_section_not_found")
    payload = _admin_section_payload(section)
    return _render_public_template(
        request,
        "console_shell.html",
        **_console_shell_context(
            request=request,
            page_title=f"Executive Assistant Admin {payload['title']}",
            current_nav=section,
            context=context,
            console_title=str(payload["title"]),
            console_summary=str(payload["summary"]),
            nav_groups=ADMIN_NAV_GROUPS,
            workspace_label="Operator Control Plane",
            cards=list(payload["cards"]),
            stats=list(payload["stats"]),
        ),
    )


@router.get("/setup")
def legacy_setup_redirect() -> RedirectResponse:
    return RedirectResponse("/get-started", status_code=307)


@router.get("/privacy")
def legacy_privacy_redirect() -> RedirectResponse:
    return RedirectResponse("/security", status_code=307)


@router.get("/demo/brief")
def legacy_brief_redirect() -> RedirectResponse:
    return RedirectResponse("/app/briefing", status_code=307)


@router.get("/channels/google")
def legacy_google_channel_redirect() -> RedirectResponse:
    return RedirectResponse("/integrations/google", status_code=307)


@router.get("/channels/telegram")
def legacy_telegram_channel_redirect() -> RedirectResponse:
    return RedirectResponse("/integrations/telegram", status_code=307)


@router.get("/channels/whatsapp")
def legacy_whatsapp_channel_redirect() -> RedirectResponse:
    return RedirectResponse("/integrations/whatsapp", status_code=307)


@router.post("/setup/start")
async def setup_start(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> RedirectResponse:
    form_data = urllib.parse.parse_qs((await request.body()).decode("utf-8", errors="ignore"), keep_blank_values=True)
    principal_id = _browser_form_context(form_data=form_data, container=container, access_identity=access_identity)
    container.onboarding.start_workspace(
        principal_id=principal_id,
        workspace_name=_form_value(form_data, "workspace_name", "Executive Workspace"),
        workspace_mode=_form_value(form_data, "workspace_mode", "personal"),
        region=_form_value(form_data, "region", ""),
        language=_form_value(form_data, "language", ""),
        timezone=_form_value(form_data, "timezone", ""),
        selected_channels=_form_values(form_data, "selected_channels"),
    )
    return RedirectResponse("/get-started", status_code=303)


@router.post("/setup/telegram")
async def setup_telegram(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> RedirectResponse:
    form_data = urllib.parse.parse_qs((await request.body()).decode("utf-8", errors="ignore"), keep_blank_values=True)
    principal_id = _browser_form_context(form_data=form_data, container=container, access_identity=access_identity)
    container.onboarding.start_telegram(
        principal_id=principal_id,
        telegram_ref=_form_value(form_data, "telegram_ref", ""),
        identity_mode=_form_value(form_data, "identity_mode", "login_widget"),
        history_mode=_form_value(form_data, "history_mode", "future_only"),
        assistant_surfaces=_form_values(form_data, "assistant_surfaces"),
    )
    return RedirectResponse("/get-started", status_code=303)


@router.post("/setup/telegram/link-bot")
async def setup_telegram_link_bot(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> RedirectResponse:
    form_data = urllib.parse.parse_qs((await request.body()).decode("utf-8", errors="ignore"), keep_blank_values=True)
    principal_id = _browser_form_context(form_data=form_data, container=container, access_identity=access_identity)
    container.onboarding.link_telegram_bot(
        principal_id=principal_id,
        bot_handle=_form_value(form_data, "bot_handle", ""),
        install_surfaces=_form_values(form_data, "install_surfaces"),
        default_chat_ref=_form_value(form_data, "default_chat_ref", ""),
    )
    return RedirectResponse("/get-started", status_code=303)


@router.post("/setup/whatsapp/business")
async def setup_whatsapp_business(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> RedirectResponse:
    form_data = urllib.parse.parse_qs((await request.body()).decode("utf-8", errors="ignore"), keep_blank_values=True)
    principal_id = _browser_form_context(form_data=form_data, container=container, access_identity=access_identity)
    container.onboarding.start_whatsapp_business(
        principal_id=principal_id,
        phone_number=_form_value(form_data, "phone_number", ""),
        business_name=_form_value(form_data, "business_name", ""),
        import_history_now=_form_value(form_data, "import_history_now", "").lower() == "true",
    )
    return RedirectResponse("/get-started", status_code=303)


@router.post("/setup/whatsapp/export")
async def setup_whatsapp_export(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> RedirectResponse:
    form_data = urllib.parse.parse_qs((await request.body()).decode("utf-8", errors="ignore"), keep_blank_values=True)
    principal_id = _browser_form_context(form_data=form_data, container=container, access_identity=access_identity)
    chats = tuple(chunk.strip() for chunk in _form_value(form_data, "selected_chat_labels_csv", "").split(",") if chunk.strip())
    container.onboarding.import_whatsapp_export(
        principal_id=principal_id,
        export_label=_form_value(form_data, "export_label", ""),
        selected_chat_labels=chats,
        include_media=_form_value(form_data, "include_media", "").lower() == "true",
    )
    return RedirectResponse("/get-started", status_code=303)


@router.post("/setup/finalize")
async def setup_finalize(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> RedirectResponse:
    form_data = urllib.parse.parse_qs((await request.body()).decode("utf-8", errors="ignore"), keep_blank_values=True)
    principal_id = _browser_form_context(form_data=form_data, container=container, access_identity=access_identity)
    container.onboarding.finalize(
        principal_id=principal_id,
        retention_mode=_form_value(form_data, "retention_mode", "full_bodies"),
        metadata_only_channels=_form_values(form_data, "metadata_only_channels"),
        allow_drafts=_form_value(form_data, "allow_drafts", "").lower() == "true",
        allow_action_suggestions=_form_value(form_data, "allow_action_suggestions", "").lower() == "true",
        allow_auto_briefs=_form_value(form_data, "allow_auto_briefs", "").lower() == "true",
    )
    return RedirectResponse("/app/briefing", status_code=303)


@router.post("/google/connect", response_model=None)
async def google_connect_browser(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> RedirectResponse | HTMLResponse:
    form_data = urllib.parse.parse_qs((await request.body()).decode("utf-8", errors="ignore"), keep_blank_values=True)
    principal_id = _browser_form_context(form_data=form_data, container=container, access_identity=access_identity)
    result = container.onboarding.start_google(
        principal_id=principal_id,
        scope_bundle=_form_value(form_data, "scope_bundle", "core"),
        redirect_uri_override=str(request.url_for("google_oauth_browser_callback")),
    )
    google_start = dict(result.get("google_start") or {})
    if bool(google_start.get("ready")) and str(google_start.get("auth_url") or "").strip():
        return RedirectResponse(str(google_start["auth_url"]), status_code=303)
    return _render_public_template(
        request,
        "channel_detail.html",
        page_title="Google onboarding status",
        public_nav=PUBLIC_NAV,
        current_nav="integrations",
        access_identity=access_identity,
        principal_id=principal_id,
        status=result,
        workspace=dict(result.get("workspace") or {}),
        channels=dict(result.get("channels") or {}),
        channel_cards=_channel_cards(dict(result.get("channels") or {})),
        selected_channels_label=", ".join(result.get("selected_channels") or []) or "Google Core recommended",
        workspace_mode_label=_humanize(str(dict(result.get("workspace") or {}).get("mode") or "personal")),
        brief_headline=str(dict(result.get("brief_preview") or {}).get("headline") or "Turn your channels into a prioritized day."),
        first_brief_items=[],
        suggested_actions=[],
        trust_notes=[],
        top_contacts=[],
        top_themes=[],
        channel_title="Google onboarding",
        channel_eyebrow="Google",
        channel={"status": google_start.get("detail") or "not_ready", "detail": google_start.get("detail") or "Google onboarding could not start.", "capabilities": [], "limitations": []},
        detail_points=("Google consent could not start on this host.",),
        body_points=("Check OAuth credentials, redirect URI, and provider configuration.",),
    )


@router.get("/google/callback", response_class=HTMLResponse, name="google_oauth_browser_callback")
def google_oauth_browser_callback(
    request: Request,
    code: str,
    state: str,
    container: AppContainer = Depends(get_container),
) -> HTMLResponse:
    try:
        account = complete_google_oauth_callback(container=container, code=code, state=state)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _render_public_template(
        request,
        "google_connected.html",
        page_title="Google connected",
        public_nav=PUBLIC_NAV,
        current_nav="integrations",
        access_identity=None,
        principal_id=account.binding.principal_id,
        account=account,
        scopes=list(account.granted_scopes),
    )
