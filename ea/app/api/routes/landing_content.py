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
            {"href": "/app/commitments", "label": "Commitments", "key": "commitments"},
            {"href": "/app/people", "label": "People", "key": "people"},
            {"href": "/app/evidence", "label": "Evidence", "key": "evidence"},
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
            {"href": "/admin/community", "label": "Access / Rollout", "key": "community"},
            {"href": "/admin/api", "label": "Workspace review", "key": "api"},
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
        "body": "Turn inbox noise into a bounded queue of decisions, drafts, and captured work that can actually be cleared.",
    },
    {
        "title": "Keep commitments visible",
        "body": "Make every promise and open loop visible until it is closed, deferred, or deliberately dropped.",
    },
)

HOW_STEPS = (
    {"title": "Connect Google", "body": "Start with the narrowest useful Google bundle so EA can read calendar pressure and recent email signals."},
    {"title": "Get your first brief", "body": "See one morning brief, one real queue, and one visible commitment list before adding anything broader."},
    {"title": "Review queue work", "body": "Clear one draft, one decision, or one captured commitment before you add operators, messaging channels, or wider office rules."},
)

PERSONAS = (
    {"title": "Personal workspace first", "body": "Start alone, prove value quickly, and add shared review only when the office actually needs it."},
    {"title": "Executive support later", "body": "Operator review and team workflows stay available, but they do not need to lead the first visit."},
    {"title": "Calm first day", "body": "The first screens show a brief, a queue, commitments that matter, and what needs approval next."},
)

TRUST_CARDS = (
    {"title": "Review before send", "body": "Nothing sends without your review, so the first useful loop stays safe and explainable."},
    {"title": "Clear permissions", "body": "Google is a workspace data connection with visible scope choices, not a hidden identity shortcut."},
    {"title": "Exportable workspace history", "body": "The office loop stays legible because decisions, commitments, evidence, and history remain visible and exportable."},
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
    {"title": "Commitments", "body": "Keep open promises, due work, and handoffs visible until they are closed, deferred, or deliberately dropped."},
    {"title": "People", "body": "Keep relationship memory, recent context, and open loops visible where the office actually needs them."},
    {"title": "Evidence", "body": "Keep source trail and proof attached to the work so approvals and commitments stay explainable."},
    {"title": "Rules", "body": "Keep memo timing, review posture, Google capture, and outcome proof visible without leading with support tooling."},
)

SIGN_IN_NOTES = (
    "Return through a current session, a secure email link, a workspace invite, or your managed access layer.",
    "Create a personal workspace from /register if you are starting fresh.",
    "Google connection is workspace data setup, not the primary app identity method.",
    "Operator invites, shared review, and broader workspace controls come later from Rules and the operator center.",
)

PRICING_TIERS = (
    {
        "title": "Personal workspace",
        "price": "Pilot",
        "body": "One executive workspace proving the memo, queue, and commitment loop before anything broader is added.",
        "facts": (
            "1 principal workspace",
            "1 included operator seat",
            "Google-first capture",
            "30-day audit retention",
            "Guided pilot conversion after first value",
        ),
    },
    {
        "title": "Shared review",
        "price": "Core",
        "body": "A shared executive-plus-operator loop with broader review, messaging coverage, and a clearer commercial boundary.",
        "facts": (
            "1 principal workspace",
            "2 included operator seats",
            "Google plus messaging channels",
            "90-day audit retention",
            "Self-serve monthly billing",
        ),
    },
    {
        "title": "Executive office",
        "price": "Executive Ops",
        "body": "Managed office deployment for heavier operator coverage, deeper audit posture, and tighter rollout support.",
        "facts": (
            "1 principal workspace",
            "Expanded operator coverage",
            "Messaging channels included",
            "180-day audit retention",
            "Account-managed contract and priority support",
        ),
    },
)

DOC_LINKS = (
    {"title": "Docs", "href": "/docs", "body": "Product and runtime references for teams that want the detailed operating model."},
    {"title": "Integrations", "href": "/integrations", "body": "Connection details for Google and other channels once the workspace is already useful."},
    {"title": "API schema", "href": "/openapi.json", "body": "The machine-readable contract for product and runtime integrations."},
    {"title": "Architecture map", "href": "https://github.com/ArchonMegalon/executive-assistant/blob/main/ARCHITECTURE_MAP.md", "body": "Route and system documentation for operators and developers."},
)
