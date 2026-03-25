from __future__ import annotations

from typing import Any


def humanize(value: str) -> str:
    return str(value or "").strip().replace("_", " ") or "unknown"


def status_tone(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"connected", "ready_to_connect", "ready_for_brief", "completed", "started", "available"}:
        return "good"
    if normalized in {"planned_business", "export_planned", "guided_manual", "bot_link_requested", "export_intake_complete", "import_acknowledged", "in_progress"}:
        return "warn"
    if normalized in {"credentials_missing", "planned_not_available", "not_selected", "anonymous"}:
        return "muted"
    return "muted"


def list_rows(values: object, fallback: tuple[str, ...]) -> list[str]:
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


def channel_cards(channels: dict[str, Any]) -> list[dict[str, str]]:
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
                "status": humanize(str(channel.get("status") or "not_selected")),
                "tone": status_tone(str(channel.get("status") or "not_selected")),
                "detail": str(channel.get("detail") or "Not configured yet."),
                "summary": str(channel.get("bundle_summary") or channel.get("history_import_posture") or ""),
            }
        )
    return cards


def app_section_payload(section: str, status: dict[str, object]) -> dict[str, object]:
    workspace = dict(status.get("workspace") or {})
    privacy = dict(status.get("privacy") or {})
    preview = dict(status.get("brief_preview") or {})
    channels = dict(status.get("channels") or {})
    cards = channel_cards(channels)
    selected = [str(value) for value in (status.get("selected_channels") or []) if str(value).strip()]
    status_label = humanize(str(status.get("status") or "draft"))
    stats = [
        {"label": "Workspace mode", "value": humanize(str(workspace.get("mode") or "personal"))},
        {"label": "Selected channels", "value": str(len(selected))},
        {"label": "Status", "value": status_label},
        {"label": "Approvals", "value": "on" if privacy.get("allow_drafts") else "review first"},
    ]
    first_brief = list_rows(preview.get("first_brief"), ("Connect Google Core to generate the first briefing.",))
    suggested = list_rows(preview.get("suggested_actions"), ("Finish onboarding and request the first brief.",))
    trust_notes = list_rows(preview.get("trust_notes"), ("Keep approvals and memory rules explicit.",))
    contacts = list_rows(preview.get("top_contacts"), ("No contacts surfaced yet.",))
    themes = list_rows(preview.get("top_themes"), ("No themes surfaced yet.",))
    privacy_lines = [
        f"Retention: {humanize(str(privacy.get('retention_mode') or 'not set'))}",
        f"Drafts: {'allowed' if privacy.get('allow_drafts') else 'manual only'}",
        f"Action suggestions: {'allowed' if privacy.get('allow_action_suggestions') else 'off'}",
        f"Automatic briefs: {'allowed' if privacy.get('allow_auto_briefs') else 'off'}",
    ]
    channel_lines = [f"{card['label']}: {card['status']} — {card['detail']}" for card in cards]

    mapping: dict[str, dict[str, object]] = {
        "today": {
            "title": "Today",
            "summary": str(preview.get("headline") or status.get("next_step") or "Start with the brief, clear the review queue, and keep the day moving."),
            "cards": [
                {"eyebrow": "Morning brief", "title": "What matters first", "items": first_brief},
                {"eyebrow": "Review queue", "title": "What to clear next", "items": suggested},
                {"eyebrow": "Channels", "title": "What is shaping the day", "items": channel_lines},
                {"eyebrow": "Why it is here", "title": "Visible trust cues", "items": trust_notes},
            ],
        },
        "briefing": {
            "title": "Briefing",
            "summary": str(preview.get("headline") or "Read the day top-down: priorities first, people and themes second, next actions third."),
            "cards": [
                {"eyebrow": "Brief preview", "title": "What changed", "items": first_brief},
                {"eyebrow": "Themes", "title": "Recurring topics", "items": themes},
                {"eyebrow": "Contacts", "title": "People to watch", "items": contacts},
                {"eyebrow": "Actions", "title": "What to do next", "items": suggested},
            ],
        },
        "inbox": {
            "title": "Inbox",
            "summary": "Use this page to move replies forward, not just to reread the same threads in a prettier shell.",
            "cards": [
                {"eyebrow": "Draft queue", "title": "Replies ready for review", "items": suggested},
                {"eyebrow": "Readiness", "title": "What the assistant can currently use", "items": channel_lines},
                {"eyebrow": "Priorities", "title": "What would bubble up next", "items": first_brief},
            ],
        },
        "follow-ups": {
            "title": "Follow-ups",
            "summary": "Keep promises, deadlines, and unanswered threads visible until they are actually closed.",
            "cards": [
                {"eyebrow": "Follow-up queue", "title": "What needs a nudge", "items": suggested},
                {"eyebrow": "Why it is still open", "title": "Context around the queue", "items": trust_notes},
                {"eyebrow": "Coverage", "title": "Where follow-ups can start", "items": channel_lines},
            ],
        },
        "memory": {
            "title": "Memory",
            "summary": "Memory should feel like a useful workspace asset: people, themes, and commitments that survive beyond one session.",
            "cards": [
                {"eyebrow": "Top themes", "title": "What keeps recurring", "items": themes},
                {"eyebrow": "Contacts", "title": "Who shows up most", "items": contacts},
                {"eyebrow": "Retention policy", "title": "What EA is allowed to keep", "items": privacy_lines},
            ],
        },
        "contacts": {
            "title": "Contacts",
            "summary": "Keep people, recent context, and follow-up pressure attached to the same working view.",
            "cards": [
                {"eyebrow": "People", "title": "Contacts in the current brief", "items": contacts},
                {"eyebrow": "Themes", "title": "Topics around those contacts", "items": themes},
                {"eyebrow": "Channels", "title": "Where those relationships live", "items": channel_lines},
            ],
        },
        "channels": {
            "title": "Channels",
            "summary": "This page should make channel readiness and limits clear without turning into an admin console.",
            "cards": [
                {"eyebrow": "Google", "title": cards[0]["label"], "items": [cards[0]["detail"], cards[0]["summary"] or "Google Core is the recommended first connection."]},
                {"eyebrow": "Telegram", "title": cards[1]["label"], "items": [cards[1]["detail"], cards[1]["summary"] or "Personal identity and bot install stay distinct."]},
                {"eyebrow": "WhatsApp", "title": cards[2]["label"], "items": [cards[2]["detail"], cards[2]["summary"] or "Business onboarding and export intake stay separate."]},
            ],
        },
        "automations": {
            "title": "Automations",
            "summary": "Automation should stay explicit, review-aware, and easy to dial up only after the core workflow already works.",
            "cards": [
                {"eyebrow": "Assistant posture", "title": "Current automation rules", "items": privacy_lines},
                {"eyebrow": "Suggested automations", "title": "What to unlock next", "items": suggested},
                {"eyebrow": "Trust", "title": "Guardrails", "items": trust_notes},
            ],
        },
        "activity": {
            "title": "Activity",
            "summary": "Use activity to understand what changed in the workspace without digging through low-level system detail.",
            "cards": [
                {"eyebrow": "Workspace", "title": "Current state", "items": [f"Status: {status_label}", f"Setup state: {status.get('onboarding_id') or 'not started'}", f"Next step: {status.get('next_step') or 'None'}"]},
                {"eyebrow": "Channels", "title": "Recent changes", "items": channel_lines},
                {"eyebrow": "Trust", "title": "Why this feed matters", "items": trust_notes},
            ],
        },
        "settings": {
            "title": "Settings",
            "summary": "Use settings to shape the workspace after the first real workflow is already working.",
            "cards": [
                {"eyebrow": "Workspace", "title": "Current workspace posture", "items": [f"Name: {workspace.get('name') or 'Executive Assistant'}", f"Mode: {humanize(str(workspace.get('mode') or 'personal'))}", f"Timezone: {workspace.get('timezone') or 'unspecified'}", f"Region: {workspace.get('region') or 'unspecified'}"]},
                {"eyebrow": "Privacy", "title": "Assistant behavior", "items": privacy_lines},
                {"eyebrow": "Channels", "title": "Selected integrations", "items": channel_lines},
            ],
        },
    }
    return {"stats": stats, **mapping[section]}


def admin_section_payload(section: str) -> dict[str, object]:
    mapping: dict[str, dict[str, object]] = {
        "policies": {
            "title": "Policies",
            "summary": "Operator-only controls for approval rules, task contracts, and promoted skills.",
            "cards": [
                {"eyebrow": "Policy", "title": "Runtime policy endpoints", "items": ["/v1/policy", "/v1/tasks/contracts", "/v1/skills"]},
                {"eyebrow": "Why it matters", "title": "Keep the product shell separate", "items": ["Buyers should see the assistant workflow.", "Admins should see the policy plane."]},
            ],
        },
        "providers": {
            "title": "Providers",
            "summary": "Bindings, 1min state, and control-plane views belong here, not in the main buyer navigation.",
            "cards": [
                {"eyebrow": "Provider APIs", "title": "Registry and health", "items": ["/v1/providers/registry", "/v1/providers/states", "/v1/providers/onemin/aggregate"]},
                {"eyebrow": "Operational focus", "title": "What this surface is for", "items": ["Capacity admission", "Binding state", "Runway and burn"]},
            ],
        },
        "audit-trail": {
            "title": "Audit Trail",
            "summary": "Evidence, telemetry, and delivery state should be visible to admins without leaking into the public product story.",
            "cards": [
                {"eyebrow": "Audit", "title": "Trace surfaces", "items": ["/v1/runtime/lanes/telemetry", "/v1/evidence", "/v1/delivery/pending"]},
                {"eyebrow": "Goal", "title": "What this surface needs", "items": ["Receipts", "Execution state", "Delivery confirmations"]},
            ],
        },
        "operators": {
            "title": "Team / Operators",
            "summary": "Admin identity, backlog, and approval work stay in the admin surface.",
            "cards": [
                {"eyebrow": "Human runtime", "title": "Admin endpoints", "items": ["/v1/human/operators", "/v1/human/tasks"]},
                {"eyebrow": "Trust boundary", "title": "Why this is separate", "items": ["Admin identity is not a customer-facing product setting.", "Audit trails depend on trusted admin records."]},
            ],
        },
        "api": {
            "title": "API",
            "summary": "The control-plane contract is part of the admin surface, not the buyer homepage.",
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
            {"label": "Access", "value": "admin-only"},
            {"label": "Audience", "value": "admins"},
            {"label": "Goal", "value": "control plane"},
        ],
        **payload,
    }
