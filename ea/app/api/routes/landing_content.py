from __future__ import annotations

PUBLIC_NAV = (
    {"href": "/", "label": "Product", "key": "product"},
    {"href": "/security", "label": "Security", "key": "security"},
    {"href": "/pricing", "label": "Pricing", "key": "pricing"},
    {"href": "/sign-in", "label": "Sign in", "key": "sign-in"},
)

EA_APP_NAV_GROUPS = (
    {
        "label": "Workspace",
        "items": (
            {"href": "/app/today", "label": "Today", "key": "today"},
            {"href": "/app/queue", "label": "Queue", "key": "queue"},
            {"href": "/app/commitments", "label": "Commitments", "key": "commitments"},
            {"href": "/app/people", "label": "People", "key": "people"},
            {"href": "/app/evidence", "label": "Evidence", "key": "evidence"},
            {"href": "/app/settings", "label": "Settings", "key": "settings"},
        ),
    },
)

PROPERTY_APP_NAV_GROUPS = (
    {
        "label": "PropertyQuarry",
        "items": (
            {"href": "/app/properties", "label": "Search", "key": "properties"},
            {"href": "/app/shortlist", "label": "Shortlist", "key": "shortlist"},
            {"href": "/app/research", "label": "Research", "key": "research"},
            {"href": "/app/properties/packets", "label": "Packets", "key": "packets"},
            {"href": "/app/profile", "label": "Profile", "key": "profile"},
            {"href": "/app/alerts", "label": "Alerts", "key": "alerts"},
            {"href": "/app/billing", "label": "Billing", "key": "billing"},
            {"href": "/app/settings", "label": "Settings", "key": "settings"},
        ),
    },
)


def app_nav_groups_for_brand(brand_key: str) -> tuple[dict[str, object], ...]:
    if str(brand_key or "").strip().lower() == "propertyquarry":
        return PROPERTY_APP_NAV_GROUPS
    return EA_APP_NAV_GROUPS


APP_NAV_GROUPS = EA_APP_NAV_GROUPS

ADMIN_NAV_GROUPS = (
    {
        "label": "Operator center",
        "items": (
            {"href": "/admin/office", "label": "Office", "key": "office"},
            {"href": "/admin/providers", "label": "Providers", "key": "providers"},
            {"href": "/admin/audit-trail", "label": "Audit Trail", "key": "audit-trail"},
            {"href": "/admin/operators", "label": "Operators", "key": "operators"},
            {"href": "/admin/community", "label": "Access", "key": "community"},
            {"href": "/admin/api", "label": "Runtime", "key": "api"},
        ),
    },
)

FEATURE_CARDS = (
    {
        "title": "Search across portals in one place",
        "body": "Start with one property brief, one ranked sweep, and one shortlist that is easier to review than raw listing tabs.",
    },
    {
        "title": "Explain why a match is good",
        "body": "Show fit reasons, likely weak spots, and concrete research gaps before the user wastes time opening ten listings.",
    },
    {
        "title": "Learn from each review",
        "body": "Capture likes, dislikes, and hard rules so later searches get sharper instead of repeating the same weak matches.",
    },
)

HOW_STEPS = (
    {"title": "Create the account", "body": "Use email first, then optional Google identity so return access stays simple and narrow."},
    {"title": "Set your search posture", "body": "Define market, budget, household needs, and hard rules before the first sweep runs."},
    {"title": "Review the shortlist", "body": "Keep the first run focused on ranked candidates, research packets, and visible feedback."},
)

PERSONAS = (
    {"title": "Private search first", "body": "Start alone, prove the ranking and research quality quickly, and add shared review only if the buying process really needs it."},
    {"title": "Guided shortlist review", "body": "The first session should end with a useful shortlist and visible fit logic, not with another saved-search graveyard."},
    {"title": "Commercial depth later", "body": "Paid research, broader portal coverage, and heavier agent work should expand only after the first shortlist proves useful."},
)

TRUST_CARDS = (
    {"title": "Tight account permissions", "body": "Google is optional identity and return access, not a hidden demand for broad mailbox permissions."},
    {"title": "Visible research posture", "body": "The product should make clear which portals were scanned, which assumptions were made, and what still needs verification."},
    {"title": "Saved learning loop", "body": "Feedback, property reasons, and shortlist context stay visible so search quality improves instead of drifting."},
)

LANDING_FAQS = (
    {
        "question": "What does it connect to?",
        "answer": "Start with account creation and property preferences. Google is optional for sign-in continuity. Portal coverage and research expand from there.",
    },
    {
        "question": "Does it auto-research every listing?",
        "answer": "No. The product stays explicit about what was scanned, what was enriched, and which deeper research steps still need to run.",
    },
    {
        "question": "Can I start alone and add others later?",
        "answer": "Yes. Start with a private workspace, then add shared review and commercial seats later from the workspace settings.",
    },
)

PRODUCT_MODULES = (
    {"title": "Property brief", "body": "Capture country, search mode, budget, household needs, and hard rules once so every later search starts from the same frame."},
    {"title": "Provider sweep", "body": "Scan the selected portals as one run instead of forcing the user to maintain separate browser rituals for every source."},
    {"title": "Research packet", "body": "Attach fit reasons, missing information, distances, and follow-up cues to each strong candidate."},
    {"title": "Shortlist review", "body": "Keep the best candidates in one place with review links, tours, and clear next actions."},
    {"title": "Learning loop", "body": "Turn likes, dislikes, and hard rules into better ranking on the next run instead of leaving them as forgotten opinions."},
    {"title": "Preferences", "body": "Keep profile, limits, integrations, and billing visible without dragging the user through unrelated assistant tooling."},
)

SIGN_IN_NOTES = (
    "Return through a current session, a secure email link, a workspace invite, or SSO.",
    "Create a property workspace from /register if you are starting fresh.",
    "Google connection is optional identity and return access, not the required center of the product.",
    "Shared review, billing, and broader workspace controls come later from Preferences after the first shortlist proves useful.",
)

PRICING_TIERS = (
    {
        "title": "Free",
        "price": "0",
        "body": "A narrow entry lane for account creation, profile setup, and a first useful shortlist.",
        "facts": (
            "1 workspace",
            "Limited shortlist volume",
            "Google identity optional",
            "Basic saved preferences",
            "Review-first experience",
        ),
    },
    {
        "title": "Plus",
        "price": "Paid",
        "body": "For users who want more searches, deeper packets, and more persistent property review coverage.",
        "facts": (
            "More provider coverage",
            "Deeper research packets",
            "Email alerts and saved runs",
            "Longer shortlist history",
            "Self-serve billing",
        ),
    },
    {
        "title": "Agent",
        "price": "Premium",
        "body": "For users who want heavier research agents, richer enrichment, and more hands-off search coverage.",
        "facts": (
            "Deep research runs",
            "Higher portal and result limits",
            "Stronger enrichment budget",
            "Priority notifications",
            "Priority support",
        ),
    },
)

DOC_LINKS = (
    {"title": "Docs", "href": "/docs", "body": "Product and runtime references for teams that want the detailed operating model."},
    {"title": "Integrations", "href": "/integrations", "body": "Connection details for Google identity, notifications, and later delivery lanes."},
    {"title": "API schema", "href": "/openapi.json", "body": "The machine-readable contract for product and runtime integrations."},
    {"title": "Architecture map", "href": "https://github.com/ArchonMegalon/property/blob/main/ARCHITECTURE_MAP.md", "body": "Route and system documentation for operators and developers."},
)
