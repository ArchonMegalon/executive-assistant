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


def row_item(title: str, detail: str, tag: str) -> dict[str, str]:
    return {"title": title, "detail": detail, "tag": tag}


def string_rows(values: object, fallback: tuple[str, ...], *, tag: str, detail: str) -> list[dict[str, str]]:
    return [row_item(value, detail, tag) for value in list_rows(values, fallback)]


def _compact_when(value: str | None, fallback: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return fallback
    if "T" in normalized:
        return normalized.split("T", 1)[0]
    return normalized


def approval_rows(values: object) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for value in values if isinstance(values, (list, tuple)) else []:
        reason = str(getattr(value, "reason", "") or "").strip()
        action_json = dict(getattr(value, "requested_action_json", {}) or {})
        action_name = humanize(str(action_json.get("action") or action_json.get("event_type") or "review"))
        title = reason or f"{action_name.capitalize()} needs approval"
        detail = " · ".join(
            part
            for part in (
                "Pending approval",
                action_name if action_name and action_name != "review" else "",
                f"Expires {_compact_when(getattr(value, 'expires_at', None), 'soon')}"
                if getattr(value, "expires_at", None)
                else "",
            )
            if part
        )
        rows.append(row_item(title, detail or "Pending approval", "Approval"))
    return rows


def human_task_rows(values: object) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for value in values if isinstance(values, (list, tuple)) else []:
        raw_title = str(getattr(value, "brief", "") or "").strip()
        task_type = str(getattr(value, "task_type", "") or "follow_up")
        fallback_title = "Commitment" if task_type == "follow_up" else humanize(task_type).capitalize()
        title = raw_title or fallback_title
        priority = humanize(str(getattr(value, "priority", "") or "open"))
        role_required = humanize(str(getattr(value, "role_required", "") or "review"))
        why_human = str(getattr(value, "why_human", "") or "").strip()
        due_label = _compact_when(getattr(value, "sla_due_at", None), "")
        detail = " · ".join(
            part
            for part in (
                f"{priority.capitalize()} priority" if priority else "",
                role_required if role_required and role_required != "review" else "",
                f"Due {due_label}" if due_label else "",
                why_human if why_human else "",
            )
            if part
        )
        rows.append(row_item(title, detail or "Waiting on human review", "Task"))
    return rows


def delivery_rows(values: object) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for value in values if isinstance(values, (list, tuple)) else []:
        recipient = str(getattr(value, "recipient", "") or "").strip()
        channel = humanize(str(getattr(value, "channel", "") or "delivery")).capitalize()
        title = recipient or f"{channel} delivery"
        attempt_count = int(getattr(value, "attempt_count", 0) or 0)
        next_attempt_at = _compact_when(getattr(value, "next_attempt_at", None), "")
        last_error = str(getattr(value, "last_error", "") or "").strip()
        detail = " · ".join(
            part
            for part in (
                channel,
                f"Attempt {attempt_count + 1}",
                f"Retry {next_attempt_at}" if next_attempt_at else "",
                last_error[:80] if last_error else "",
            )
            if part
        )
        rows.append(row_item(title, detail or "Queued for delivery", "Queued"))
    return rows


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


def app_section_payload(
    section: str,
    status: dict[str, object],
    *,
    live_feed: dict[str, object] | None = None,
) -> dict[str, object]:
    workspace = dict(status.get("workspace") or {})
    privacy = dict(status.get("privacy") or {})
    delivery_preferences = dict(status.get("delivery_preferences") or {})
    morning_memo = dict(delivery_preferences.get("morning_memo") or {})
    preview = dict(status.get("brief_preview") or {})
    channels = dict(status.get("channels") or {})
    cards = channel_cards(channels)
    selected = [str(value) for value in (status.get("selected_channels") or []) if str(value).strip()]
    live = dict(live_feed or {})
    approvals = list(live.get("approvals") or [])
    human_tasks = list(live.get("human_tasks") or [])
    pending_delivery = list(live.get("pending_delivery") or [])
    status_label = humanize(str(status.get("status") or "draft"))
    ready_channels = sum(1 for card in cards if card["tone"] == "good")
    selected_count = len(selected) or len([card for card in cards if card["status"] != "not selected"]) or 0
    stats = [
        {"label": "Approvals", "value": str(len(approvals))},
        {"label": "Human tasks", "value": str(len(human_tasks))},
        {"label": "Queued delivery", "value": str(len(pending_delivery))},
        {
            "label": "Channels ready",
            "value": f"{ready_channels}/{selected_count}" if selected_count else str(ready_channels),
        },
    ]
    first_brief = list_rows(
        preview.get("first_brief_preview") or preview.get("first_brief"),
        ("Connect Google Core to generate the first morning memo.",),
    )
    suggested = list_rows(preview.get("suggested_actions"), ("Finish onboarding and request the first memo.",))
    trust_notes = list_rows(preview.get("trust_notes"), ("Keep approvals and retention rules explicit.",))
    people = list_rows(preview.get("top_contacts"), ("No people surfaced yet.",))
    themes = list_rows(preview.get("top_themes"), ("No themes surfaced yet.",))
    approvals_items = approval_rows(approvals)
    human_task_items = human_task_rows(human_tasks)
    pending_delivery_items = delivery_rows(pending_delivery)
    live_queue = (approvals_items + human_task_items)[:6]
    privacy_lines = [
        f"Retention: {humanize(str(privacy.get('retention_mode') or 'not set'))}",
        f"Drafts: {'allowed' if privacy.get('allow_drafts') else 'manual only'}",
        f"Action suggestions: {'allowed' if privacy.get('allow_action_suggestions') else 'off'}",
        f"Automatic briefs: {'allowed' if privacy.get('allow_auto_briefs') else 'off'}",
    ]
    if privacy.get("allow_auto_briefs"):
        privacy_lines.append(
            "Memo schedule: "
            + " · ".join(
                part
                for part in (
                    humanize(str(morning_memo.get("cadence") or "daily_morning")),
                    f"{morning_memo.get('delivery_time_local') or '08:00'} {morning_memo.get('timezone') or workspace.get('timezone') or 'UTC'}",
                    str(morning_memo.get("resolved_recipient_email") or "waiting for recipient"),
                )
                if str(part or "").strip()
            )
        )
    channel_lines = [f"{card['label']}: {card['status']} — {card['detail']}" for card in cards]
    channel_items = [row_item(card["label"], card["detail"], card["status"]) for card in cards]
    identity_posture_items = [
        row_item(
            "Keep identity boring",
            "Return through a secure email link, invite, or SSO before widening channel setup.",
            "Recommended",
        ),
        row_item(
            "Connect Google for workspace context",
            "Treat Google as the first data connection for memo, queue, and people context.",
            "Linked",
        ),
        row_item(
            "Link messaging channels later",
            "Treat Telegram and WhatsApp as optional linked channels, not the workspace core.",
            "Linked",
        ),
        row_item(
            "Keep work bounded",
            "Approvals, human tasks, and queued delivery stay explicit instead of hiding behind automation copy.",
            "Guardrail",
        ),
    ]
    follow_up_context_items = [
        row_item(title, "Keep the underlying promise, thread, or deadline attached to the work item.", "Context")
        for title in trust_notes
    ]

    mapping: dict[str, dict[str, object]] = {
        "today": {
            "title": "Morning Memo",
            "summary": str(
                preview.get("headline")
                or status.get("next_step")
                or "Start with the operating memo, clear the decision queue, and keep commitments from drifting."
            ),
            "cards": [
                {
                    "eyebrow": "Live queue",
                    "title": "What needs action now",
                    "body": "The day opens on real approvals and human tasks instead of a motivational dashboard.",
                    "items": live_queue
                    or string_rows(
                        first_brief,
                        ("Connect Google Core to unlock the first useful memo.",),
                        tag="Next",
                        detail="This is the shortest path to a real working day.",
                    ),
                },
                {
                    "eyebrow": "Outbound work",
                    "title": "What is queued to leave the office loop",
                    "body": "Pending delivery stays visible so drafts, approvals, and sends never blur together.",
                    "items": pending_delivery_items
                    or string_rows(
                        suggested,
                        ("No queued delivery yet.",),
                        tag="Review",
                        detail="Once a draft or action is ready, it will show up here.",
                    ),
                },
                {
                    "eyebrow": "Brief signal",
                    "title": "What is shaping the day",
                    "body": "The memo stays narrative, but it still points at work that exists.",
                    "items": string_rows(first_brief, ("No memo items yet.",), tag="Memo", detail="Use the memo to set the order of operations."),
                },
                {
                    "eyebrow": "Identity and channels",
                    "title": "Keep setup boring and useful",
                    "body": "Identity stays simple. Channels widen coverage only after the first loop works.",
                    "items": identity_posture_items,
                },
            ],
        },
        "queue": {
            "title": "Decision Queue",
            "summary": str(preview.get("headline") or "Turn the day into decisions: approve, assign, defer, or close."),
            "cards": [
                {
                    "eyebrow": "Decision pressure",
                    "title": "What changed",
                    "body": "The queue explains what changed, why it matters, and what decision belongs next.",
                    "items": string_rows(first_brief, ("No memo items yet.",), tag="Memo", detail="This is the current ranked memo item."),
                },
                {
                    "eyebrow": "Themes",
                    "title": "Recurring topics",
                    "body": "Themes help the user understand the day without reopening every thread.",
                    "items": string_rows(themes, ("No themes surfaced yet.",), tag="Theme", detail="This theme is active in the current workspace."),
                },
                {
                    "eyebrow": "Live queue",
                    "title": "What the queue clears",
                    "body": "A useful queue terminates in real approvals, assignments, or outbound actions.",
                    "items": live_queue
                    or string_rows(
                        suggested,
                        ("No live review items yet.",),
                        tag="Queue",
                        detail="Once the office loop starts moving, the memo points here.",
                    ),
                },
                {
                    "eyebrow": "Stakeholders",
                    "title": "People affected by the queue",
                    "body": "Stakeholders only matter if they stay attached to the decisions and commitments in front of the team.",
                    "items": string_rows(people, ("No people surfaced yet.",), tag="Person", detail="This person is active in the current memo."),
                },
            ],
        },
        "commitments": {
            "title": "Commitments",
            "summary": "Messages, meetings, and notes only matter when they update a commitment, create a decision, or close a loop.",
            "cards": [
                {
                    "eyebrow": "Commitment pressure",
                    "title": "What is in motion",
                    "body": "This surface shows which commitments are active, which decisions are waiting, and which drafts are holding things up.",
                    "items": live_queue
                    or string_rows(
                        suggested,
                        ("No live commitment queue yet.",),
                        tag="Draft",
                        detail="Once drafts or approvals exist, they will appear here.",
                    ),
                },
                {
                    "eyebrow": "Queued delivery",
                    "title": "What is waiting to leave",
                    "body": "Outbound work is part of the commitment loop, not hidden afterthought state.",
                    "items": pending_delivery_items
                    or string_rows(
                        channel_lines,
                        ("No delivery queue yet.",),
                        tag="Ready",
                        detail="Connected channels determine what the queue can actually move.",
                    ),
                },
                {
                    "eyebrow": "Decision pressure",
                    "title": "What will bubble up next",
                    "body": "The commitment ledger gets its order from pressure and deadlines, not from unread-count theater.",
                    "items": string_rows(first_brief, ("No priorities surfaced yet.",), tag="Memo", detail="This is the current upstream signal for the commitment queue."),
                },
            ],
        },
        "people": {
            "title": "People Graph",
            "summary": "The product moat lives in the relationship system: people, recurring themes, open loops, and office pressure that survive beyond one session.",
            "cards": [
                {"eyebrow": "Stakeholders", "title": "Who matters right now", "items": string_rows(people, ("No people surfaced yet.",), tag="Person", detail="These people are shaping the current office loop.")},
                {"eyebrow": "Relationship themes", "title": "What keeps recurring", "items": string_rows(themes, ("No themes surfaced yet.",), tag="Theme", detail="Recurring pressure and themes stay durable in the workspace.")},
                {"eyebrow": "Rules", "title": "What the office memory may keep", "items": string_rows(privacy_lines, ("No retention policy set yet.",), tag="Policy", detail="These rules bound what the workspace retains.")},
            ],
        },
        "evidence": {
            "title": "Evidence",
            "summary": "Evidence explains why something surfaced: which signal, which channel, which context, and which rule put it in front of the team.",
            "cards": [
                {"eyebrow": "Memo evidence", "title": "Why items surfaced", "items": string_rows(first_brief, ("No evidence rows surfaced yet.",), tag="Evidence", detail="This is one of the signals behind the current operating view.")},
                {"eyebrow": "Trust notes", "title": "What keeps the surface explainable", "items": string_rows(trust_notes, ("No trust notes yet.",), tag="Rule", detail="These constraints explain why the assistant behaved this way.")},
                {"eyebrow": "Channel sources", "title": "Where the evidence came from", "items": channel_items},
            ],
        },
        "channels": {
            "title": "Channels",
            "summary": "Channels widen coverage. They never redefine the product core or become the main story of the workspace.",
            "cards": [
                {"eyebrow": "Google", "title": cards[0]["label"], "items": [cards[0]["detail"], cards[0]["summary"] or "Google Core is the recommended first connection."]},
                {"eyebrow": "Telegram", "title": cards[1]["label"], "items": [cards[1]["detail"], cards[1]["summary"] or "Personal identity and bot install stay distinct."]},
                {"eyebrow": "WhatsApp", "title": cards[2]["label"], "items": [cards[2]["detail"], cards[2]["summary"] or "Business onboarding and export intake stay separate."]},
            ],
        },
        "automations": {
            "title": "Policies",
            "summary": "Policies stay understandable: what the assistant may read, draft, send, remember, and escalate.",
            "cards": [
                {"eyebrow": "Assistant posture", "title": "Current rules", "items": privacy_lines},
                {"eyebrow": "Suggested changes", "title": "What to unlock next", "items": suggested},
                {"eyebrow": "Guardrails", "title": "Why these rules exist", "items": trust_notes},
            ],
        },
        "activity": {
            "title": "Audit",
            "summary": "Audit explains what changed, what left the system, and which rule or review point allowed it.",
            "cards": [
                {"eyebrow": "Workspace", "title": "Current state", "items": string_rows([f"Status: {status_label}", f"Setup state: {status.get('onboarding_id') or 'not started'}", f"Next step: {status.get('next_step') or 'None'}"], ("No workspace state yet.",), tag="State", detail="This is the current workspace status.")},
                {"eyebrow": "Channels", "title": "Recent changes", "items": channel_items},
                {"eyebrow": "Trust", "title": "Why this feed matters", "items": string_rows(trust_notes, ("No trust notes yet.",), tag="Context", detail="This keeps the activity feed understandable.")},
            ],
        },
        "settings": {
            "title": "Rules",
            "summary": "Rules stay boring and explicit once the first working loop already exists.",
            "cards": [
                {"eyebrow": "Workspace", "title": "Current workspace posture", "items": string_rows([f"Name: {workspace.get('name') or 'Executive Assistant'}", f"Mode: {humanize(str(workspace.get('mode') or 'personal'))}", f"Timezone: {workspace.get('timezone') or 'unspecified'}", f"Region: {workspace.get('region') or 'unspecified'}"], ("No workspace posture yet.",), tag="Workspace", detail="These are the current office defaults.")},
                {"eyebrow": "Policy", "title": "Assistant behavior", "items": string_rows(privacy_lines, ("No privacy posture set yet.",), tag="Rule", detail="These controls shape what the assistant may do.")},
                {"eyebrow": "Channels", "title": "Selected linked channels", "items": channel_items},
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
                {"eyebrow": "Why it matters", "title": "Keep the product shell separate", "items": ["Buyers see the assistant workflow.", "Admins see the policy plane."]},
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
            "summary": "Evidence, telemetry, and delivery state stay visible to admins without leaking into the public product story.",
            "cards": [
                {"eyebrow": "Audit", "title": "Trace surfaces", "items": ["/v1/runtime/lanes/telemetry", "/v1/evidence", "/v1/delivery/pending"]},
                {"eyebrow": "Goal", "title": "What this surface needs", "items": ["Receipts", "Execution state", "Delivery confirmations"]},
            ],
        },
        "operators": {
            "title": "Operators",
            "summary": "Admin identity, backlog, and approval work stay in the admin surface.",
            "cards": [
                {"eyebrow": "Human runtime", "title": "Admin endpoints", "items": ["/v1/human/operators", "/v1/human/tasks"]},
                {"eyebrow": "Trust boundary", "title": "Why this is separate", "items": ["Admin identity is separate from the customer workspace surface.", "Audit trails depend on trusted admin records."]},
            ],
        },
        "api": {
            "title": "Runtime",
            "summary": "The operator-center contract belongs in the admin surface, not on the public product pages.",
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
            {"label": "Goal", "value": "operator center"},
        ],
        **payload,
    }
