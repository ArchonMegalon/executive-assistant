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
        "label": "Core workflow",
        "items": (
            {"href": "/app/today", "label": "Morning memo", "key": "today"},
            {"href": "/app/briefing", "label": "Decision queue", "key": "briefing"},
            {"href": "/app/inbox", "label": "Commitments", "key": "inbox"},
            {"href": "/app/follow-ups", "label": "Handoffs", "key": "follow-ups"},
            {"href": "/app/memory", "label": "People graph", "key": "memory"},
            {"href": "/app/contacts", "label": "Evidence", "key": "contacts"},
        ),
    },
    {
        "label": "Controls",
        "items": (
            {"href": "/app/channels", "label": "Channels", "key": "channels"},
            {"href": "/app/automations", "label": "Policies", "key": "automations"},
            {"href": "/app/activity", "label": "Audit", "key": "activity"},
            {"href": "/app/settings", "label": "Rules", "key": "settings"},
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
            {"href": "/admin/api", "label": "Diagnostics", "key": "api"},
        ),
    },
)

FEATURE_CARDS = (
    {
        "title": "Morning memo",
        "body": "Start the day with a compiled operating memo: what changed, what is blocked, and what demands attention first.",
    },
    {
        "title": "Decision queue",
        "body": "Turn approvals, assignments, memory changes, and choices into one bounded queue instead of scattering them across inboxes.",
    },
    {
        "title": "Commitment ledger",
        "body": "Every message, meeting, or note either updates a commitment, creates a decision, or is discarded.",
    },
    {
        "title": "People graph",
        "body": "Keep stakeholders, relationship context, open loops, and recurring pressure visible in one durable graph.",
    },
    {
        "title": "Handoffs",
        "body": "Support one executive and one operator with a clean lane for drafts, follow-ups, and unresolved decisions.",
    },
    {
        "title": "Rules",
        "body": "Make reading, drafting, sending, remembering, and approval rules explicit instead of leaving them buried in safety copy.",
    },
)

HOW_STEPS = (
    {"title": "Choose the office shape", "body": "Start with one executive, one operator, or one personal loop. Do not overfit the org chart on day one."},
    {"title": "Connect Google first", "body": "Use Google Core to unlock the first useful memo, the first draft, and the first visible follow-up."},
    {"title": "Prove one loop", "body": "Generate the first memo, approve one draft, and close one commitment before adding more channel complexity."},
    {"title": "Add more only when it earns its keep", "body": "Bring in Telegram, WhatsApp, and deeper rules only when they clearly improve the daily operating loop."},
)

PERSONAS = (
    {"title": "One executive + one operator", "body": "The cleanest wedge: one person making decisions and one person keeping the office loop tight."},
    {"title": "Chiefs of staff", "body": "Keep leadership communication, commitments, and handoffs visible without babysitting a generic dashboard."},
    {"title": "Founders", "body": "Run stakeholder follow-ups, recruiting loops, and vendor pressure through one commitment system."},
)

TRUST_CARDS = (
    {"title": "Scoped workspace memory", "body": "Context belongs to the right workspace instead of floating around in stateless prompts."},
    {"title": "Visible review points", "body": "Drafts and suggestions stay reviewable so the product feels safe in real work."},
    {"title": "Clear channel boundaries", "body": "Each connection spells out what the assistant can really read, draft, verify, or import."},
)

PRODUCT_MODULES = (
    {"title": "Morning memo", "body": "Compile changes, pressure, commitments, and decisions into one memo that deserves the executive attention first."},
    {"title": "Decision queue", "body": "Route approvals, assignments, memory updates, and next moves through one bounded review surface."},
    {"title": "Commitment ledger", "body": "Keep every promise, deadline, and open loop visible until it is either closed or explicitly deferred."},
    {"title": "People graph", "body": "Store stakeholder temperature, context, and recurring pressure as a durable relationship system."},
    {"title": "Handoffs", "body": "Support operator review, executive approval, and office collaboration without turning the product into a control-plane catalog."},
    {"title": "Rules", "body": "Expose reading, drafting, sending, memory, and approval boundaries as first-class product behavior."},
)

SIGN_IN_NOTES = (
    "Executive Assistant does not create a separate email-and-password account inside the product.",
    "Workspace access should come from company SSO, an access gateway, or another deployment-level identity layer.",
    "Google connection happens after access is established; it binds Gmail, Calendar, and contacts to the workspace rather than acting as app login.",
    "API tokens are for API and operator automation flows, not a browser sign-in screen.",
)

PRICING_TIERS = (
    {"title": "One executive", "price": "Pilot", "body": "One principal, one memo, one decision queue, and one commitment loop."},
    {"title": "Executive + operator", "price": "Core", "body": "Shared review, handoffs, and stronger rules for one executive office pair."},
    {"title": "Office team", "price": "Custom", "body": "Broader review, audit, and channel policy for a multi-operator executive support model."},
)

DOC_LINKS = (
    {"title": "API schema", "href": "/openapi.json", "body": "The machine-readable contract for teams integrating with the runtime and product surfaces."},
    {"title": "Architecture map", "href": "https://github.com/ArchonMegalon/executive-assistant/blob/main/ARCHITECTURE_MAP.md", "body": "A technical route map for admins and developers who need implementation detail."},
    {"title": "Product brief v2", "href": "https://github.com/ArchonMegalon/executive-assistant/blob/main/PRODUCT_BRIEF_V2.md", "body": "The narrower product promise: one executive, one operator, one memo, one decision queue, one commitment system."},
)
