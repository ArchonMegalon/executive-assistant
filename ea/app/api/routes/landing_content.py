from __future__ import annotations

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
        "title": "Draft queue",
        "body": "Prepare replies with the right context and keep review visible before anything leaves the workspace.",
    },
    {
        "title": "Follow-ups",
        "body": "Track promises, deadlines, and pending decisions without rebuilding your reminders manually.",
    },
    {
        "title": "Contact memory",
        "body": "Keep people, themes, commitments, and channel context attached to the right workspace over time.",
    },
    {
        "title": "Approval controls",
        "body": "Keep review explicit for sensitive sends, edits, and escalations.",
    },
    {
        "title": "Honest channel support",
        "body": "Connect only the channels you actually use and keep the support contract explicit.",
    },
)

HOW_STEPS = (
    {"title": "Choose the workspace fit", "body": "Pick the workspace shape that matches the daily workload, not the org chart."},
    {"title": "Connect Google first", "body": "Start with Google Core so the assistant can produce a useful brief quickly."},
    {"title": "Review one real loop", "body": "Use the first brief, one reviewed draft, and one follow-up as the product proof."},
    {"title": "Add more only when it helps", "body": "Bring in Telegram, WhatsApp, and deeper settings only when they clearly improve the workflow."},
)

PERSONAS = (
    {"title": "Founders", "body": "Stay ahead of investor, recruiting, vendor, and team follow-ups without losing context."},
    {"title": "Chiefs of staff", "body": "Keep leadership communication, handoffs, and commitments visible across channels."},
    {"title": "Executive teams", "body": "Organize shared channels, triage requests, and manage approvals in one assistant workspace."},
)

TRUST_CARDS = (
    {"title": "Scoped workspace memory", "body": "Context belongs to the right workspace instead of floating around in stateless prompts."},
    {"title": "Visible review points", "body": "Drafts and suggestions stay reviewable so the product feels safe in real work."},
    {"title": "Clear channel boundaries", "body": "Each connection spells out what the assistant can really read, draft, verify, or import."},
)

PRODUCT_MODULES = (
    {"title": "Morning Brief", "body": "See the day as a ranked set of actions instead of five disconnected inboxes."},
    {"title": "Inbox Triage", "body": "Turn raw message traffic into reply recommendations, handoffs, and follow-up decisions."},
    {"title": "Draft Queue", "body": "Prepare messages with context, approvals, and clear provenance before sending."},
    {"title": "Follow-up Tracker", "body": "Keep commitments and promised next steps visible until they are actually closed."},
    {"title": "Memory", "body": "Retain people, patterns, and context in a durable assistant workspace."},
    {"title": "Approvals", "body": "Keep the user in control for outbound actions, edits, and high-trust workflows."},
)

SIGN_IN_NOTES = (
    "Use the identity your workspace already trusts so the assistant opens in the right account context.",
    "Company SSO or access-gateway deployments should hand you into the workspace without another setup loop.",
    "Private deployments can still enforce host-level rules, but those checks should feel invisible when the deployment is configured correctly.",
)

PRICING_TIERS = (
    {"title": "Starter", "price": "Pilot", "body": "One workspace, Google first, and the daily brief loop for one person or one executive workflow."},
    {"title": "Growth", "price": "Core", "body": "Shared reviews, broader channel coverage, and a stronger operating loop for a small team."},
    {"title": "Executive ops", "price": "Custom", "body": "Higher-trust review, admin visibility, and a heavier operating model for executive support."},
)

DOC_LINKS = (
    {"title": "API schema", "href": "/openapi.json", "body": "The machine-readable contract for teams integrating with the product."},
    {"title": "Architecture map", "href": "https://github.com/ArchonMegalon/executive-assistant/blob/main/ARCHITECTURE_MAP.md", "body": "A technical route map for admins and developers who need implementation detail."},
    {"title": "Repository overview", "href": "https://github.com/ArchonMegalon/executive-assistant", "body": "Source, deployment notes, and the broader implementation context."},
)
