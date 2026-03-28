from __future__ import annotations

PUBLIC_NAV = (
    {"href": "/", "label": "Product", "key": "product"},
    {"href": "/security", "label": "Security", "key": "security"},
    {"href": "/pricing", "label": "Pricing", "key": "pricing"},
    {"href": "/sign-in", "label": "Sign in", "key": "sign-in"},
)

APP_NAV_GROUPS = (
    {
        "label": "Workspace",
        "items": (
            {"href": "/app/today", "label": "Today", "key": "today"},
            {"href": "/app/queue", "label": "Queue", "key": "queue"},
            {"href": "/app/people", "label": "People", "key": "people"},
            {"href": "/app/settings", "label": "Rules", "key": "settings"},
        ),
    },
)

ADMIN_NAV_GROUPS = (
    {
        "label": "Operator control plane",
        "items": (
            {"href": "/admin/office", "label": "Office", "key": "office"},
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
        "title": "See what changed",
        "body": "Start with one morning brief that explains what moved overnight and where today already feels tight.",
    },
    {
        "title": "Decide what matters next",
        "body": "Turn inbox noise into a bounded queue of decisions, drafts, and follow-ups that can actually be cleared.",
    },
    {
        "title": "Keep commitments visible",
        "body": "Make every promise and open loop visible until it is closed, deferred, or deliberately dropped.",
    },
)

HOW_STEPS = (
    {"title": "Connect Google", "body": "Start with the narrowest useful Google bundle so the product can read calendar pressure and recent email signals."},
    {"title": "Get your first brief", "body": "Build a morning brief, a review queue, and a visible follow-up list before introducing more setup complexity."},
    {"title": "Review drafts and follow-ups", "body": "Prove one useful daily loop before adding operators, messaging channels, or broader workspace rules."},
)

PERSONAS = (
    {"title": "Personal workspace first", "body": "Start alone, prove value quickly, and add shared review only when the office actually needs it."},
    {"title": "Executive support later", "body": "Operator review and team workflows stay available, but they should not be the first thing a new customer has to learn."},
    {"title": "Product before control plane", "body": "The first screens should sell clarity, queue discipline, and follow-through, not system posture."},
)

TRUST_CARDS = (
    {"title": "Review before send", "body": "Nothing sends without your review, so the first useful loop stays safe and explainable."},
    {"title": "Clear permissions", "body": "Google is a workspace data connection with visible scope choices, not a hidden identity shortcut."},
    {"title": "Exportable workspace history", "body": "The office loop stays legible because decisions, follow-ups, and history remain visible and exportable."},
)

LANDING_FAQS = (
    {
        "question": "What does it connect to?",
        "answer": "Start with Gmail and Calendar. Add broader channels and team workflows only after the personal workspace is already useful.",
    },
    {
        "question": "Does it send anything automatically?",
        "answer": "No. The personal-first loop is review-first. Drafts and suggested actions stay visible until you approve them.",
    },
    {
        "question": "Can I start alone and add others later?",
        "answer": "Yes. Start with a personal workspace, then add an operator or move into a shared setup from Settings after first value.",
    },
)

PRODUCT_MODULES = (
    {"title": "Morning brief", "body": "Show the day as a clear brief instead of a wall of messages and half-remembered obligations."},
    {"title": "Queue", "body": "Keep decisions, drafts, and commitments inside one review lane instead of spreading them across separate product nouns."},
    {"title": "People", "body": "Keep relationship memory, recent context, and open loops visible where the office actually needs them."},
    {"title": "Rules", "body": "Keep memo timing, review posture, Google capture, and outcome proof visible without leading with support tooling."},
)

SIGN_IN_NOTES = (
    "Use sign in only if you already have a workspace access link, a trusted deployment identity, or an existing session.",
    "Create a personal workspace from /register if you are starting fresh.",
    "Google connection is workspace data setup, not the primary app identity method.",
    "Operator invites, shared review, and broader workspace controls come later from Rules and the operator center.",
)

PRICING_TIERS = (
    {"title": "Personal workspace", "price": "Starter", "body": "One person, one morning brief, one queue, and one follow-up loop to prove value quickly."},
    {"title": "Shared review", "price": "Growth", "body": "Add operator review and shared workflow after the personal workspace is already working."},
    {"title": "Executive office", "price": "Custom", "body": "Expand into broader office support, audit posture, and team workflow only when the product has earned it."},
)

DOC_LINKS = (
    {"title": "Docs", "href": "/docs", "body": "Product and runtime references for teams who need implementation detail after the first visit."},
    {"title": "Integrations", "href": "/integrations", "body": "Connection details for Google and other channels once the personal workspace is already underway."},
    {"title": "API schema", "href": "/openapi.json", "body": "The machine-readable contract for product and runtime integrations."},
    {"title": "Architecture map", "href": "https://github.com/ArchonMegalon/executive-assistant/blob/main/ARCHITECTURE_MAP.md", "body": "Route and system documentation for operators and developers."},
)
