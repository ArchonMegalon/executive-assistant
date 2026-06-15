from __future__ import annotations

from typing import Callable

from app.product.models import ProductSnapshot


def build_settings_section(
    *,
    snapshot: ProductSnapshot,
    diagnostics: dict[str, object],
    outcomes: dict[str, object],
    property_brand: bool,
    memo_loop: dict[str, object],
    office_loop_proof: dict[str, object],
    proof_checks: list[dict[str, object]],
    analytics: dict[str, object],
    analytics_delivery: dict[str, object],
    analytics_access: dict[str, object],
    analytics_invitations: dict[str, object],
    analytics_sync: dict[str, object],
    support_verification: dict[str, object],
    blocked_actions: list[str],
    warning_messages: list[str],
    operator_key: str,
    product_control: dict[str, object],
    journey_gate: dict[str, object],
    journey_freshness: dict[str, object],
    support_fallout: dict[str, object],
    public_guide_freshness: dict[str, object],
    route_stewardship: dict[str, object],
    row_builder: Callable[..., dict[str, str]],
    rule_rows_builder: Callable[[tuple[object, ...]], list[dict[str, str]]],
    google_settings_action_row_builder: Callable[[dict[str, object]], dict[str, str]],
) -> dict[str, object]:
    workspace = dict(diagnostics.get("workspace") or {})
    return {
        "title": "Office settings",
        "summary": "Keep the office loop usable: memo timing, what is feeding Today, who can enter, and what still needs review.",
        "console_form": {
            "action": "/app/actions/settings/morning-memo",
            "method": "post",
            "eyebrow": "Office profile",
            "title": "Update office and morning memo rules",
            "copy": "Keep the office name and memo timing editable after onboarding so Today stays aligned with the real office rhythm.",
            "submit_label": "Save workspace rules",
            "fields": [
                {
                    "label": "Workspace name",
                    "name": "workspace_name",
                    "type": "text",
                    "value": str(workspace.get("name") or ""),
                    "placeholder": "Executive Assistant Workspace" if not property_brand else "PropertyQuarry Workspace",
                },
                {
                    "label": "Language",
                    "name": "language",
                    "type": "text",
                    "value": str(workspace.get("language") or "en"),
                    "placeholder": "en",
                },
                {
                    "label": "Timezone",
                    "name": "timezone",
                    "type": "text",
                    "value": str(workspace.get("timezone") or "Europe/Vienna"),
                    "placeholder": "Europe/Vienna",
                },
                {
                    "label": "Enable scheduled memo",
                    "name": "enabled",
                    "type": "checkbox",
                    "value": "true",
                    "checked": bool(memo_loop.get("enabled")),
                },
                {
                    "label": "Cadence",
                    "name": "cadence",
                    "type": "select",
                    "value": str(memo_loop.get("cadence") or "daily_morning"),
                    "options": [
                        {"label": "Every day", "value": "daily_morning"},
                        {"label": "Weekdays", "value": "weekdays_morning"},
                    ],
                },
                {
                    "label": "Recipient email",
                    "name": "recipient_email",
                    "type": "email",
                    "value": str(memo_loop.get("recipient_email") or ""),
                    "placeholder": "Uses the connected Google email when left blank",
                },
                {
                    "label": "Delivery time",
                    "name": "delivery_time_local",
                    "type": "time",
                    "value": str(memo_loop.get("delivery_time_local") or "08:00"),
                },
                {
                    "label": "Quiet hours start",
                    "name": "quiet_hours_start",
                    "type": "time",
                    "value": str(memo_loop.get("quiet_hours_start") or "20:00"),
                },
                {
                    "label": "Quiet hours end",
                    "name": "quiet_hours_end",
                    "type": "time",
                    "value": str(memo_loop.get("quiet_hours_end") or "07:00"),
                },
            ],
        },
        "cards": [
            {
                "eyebrow": "Morning memo",
                "title": "Morning memo delivery",
                "body": "The scheduled memo stays legible: when it lands, who it lands to, and whether it is producing a useful daily loop.",
                "items": [
                    row_builder("Memo state", str(memo_loop.get("state") or "watch").replace("_", " ").title(), "Memo", href="/app/settings/outcomes"),
                    row_builder("Enabled", "Yes" if memo_loop.get("enabled") else "No", "Memo", href="/app/settings/outcomes"),
                    row_builder(
                        "Delivery time",
                        f"{memo_loop.get('delivery_time_local') or '08:00'} {memo_loop.get('timezone') or workspace.get('timezone') or 'UTC'}",
                        "Memo",
                        href="/app/settings/outcomes",
                    ),
                    row_builder("Recipient", str(memo_loop.get("recipient_email") or "waiting for recipient"), "Memo", href="/app/settings/outcomes"),
                    row_builder(
                        "Last memo issue",
                        str(memo_loop.get("last_issue_reason") or "No current memo blocker"),
                        "Memo",
                        href="/app/settings/support" if str(memo_loop.get("last_issue_reason") or "").strip() else "/app/settings/outcomes",
                    ),
                ],
            },
            {
                "eyebrow": "Office-loop proof",
                "title": "How the daily office loop is proving itself",
                "body": "The principal surface says plainly whether the memo is being opened, approvals are moving, and commitments are closing at a believable rate.",
                "items": [
                    row_builder("Gate state", str(office_loop_proof.get("state") or "watch").replace("_", " ").title(), "Gate", href="/app/settings/outcomes"),
                    row_builder("Summary", str(office_loop_proof.get("summary") or "No proof summary yet."), "Gate", href="/app/settings/outcomes"),
                    row_builder("Memo open rate", str(outcomes.get("memo_open_rate") or analytics.get("memo_open_rate") or 0), "Memo", href="/app/settings/outcomes"),
                    row_builder("Approval coverage rate", str(outcomes.get("approval_coverage_rate") or analytics.get("approval_coverage_rate") or 0), "Approvals", href="/app/settings/outcomes"),
                ],
            },
            {
                "eyebrow": "Google connection" if property_brand else "Google signal loop",
                "title": "Connected Google identity posture" if property_brand else "What is feeding the office loop",
                "body": (
                    "PropertyQuarry only needs identity, token health, and reauth posture here."
                    if property_brand
                    else "Gmail and Calendar explain whether fresh signals are entering the queue and whether staged work is ready for review."
                ),
                "items": [
                    google_settings_action_row_builder(analytics_sync),
                    row_builder("Google account", str(analytics_sync.get("google_account_email") or "Not connected"), "Sync", href="/app/settings/google"),
                    row_builder(
                        "Freshness",
                        str(analytics_sync.get("google_sync_freshness_state") or "watch").replace("_", " ").title(),
                        "Sync",
                        href="/app/settings/google",
                        action_href="/app/actions/signals/google/sync?return_to=/app/settings/google" if analytics_sync.get("google_connected") else "",
                        action_label="Run now" if analytics_sync.get("google_connected") else "",
                        action_method="get" if analytics_sync.get("google_connected") else "",
                    ),
                    *(
                        []
                        if property_brand
                        else [
                            row_builder("Last Google sync", str(analytics_sync.get("google_sync_last_completed_at") or "Not yet run"), "Sync", href="/app/settings/google"),
                        ]
                    ),
                ],
            },
            {
                "eyebrow": "Workspace entry",
                "title": "Who can enter and who is waiting",
                "body": "Keep the office reachable without turning the main settings surface into a delivery dashboard.",
                "items": [
                    row_builder("Active access sessions", str(analytics_access.get("active") or 0), "Access", href="/app/settings/access"),
                    row_builder("Pending invitations", str(analytics_invitations.get("pending") or 0), "Invites", href="/app/settings/invitations"),
                    row_builder("Accepted invitations", str(analytics_invitations.get("accepted") or 0), "Invites", href="/app/settings/invitations"),
                ],
            },
            {
                "eyebrow": "Workspace rules",
                "title": "What this office currently allows",
                "body": "Rules explain the review-first posture, channel boundary, and durable controls behind the current loop.",
                "items": rule_rows_builder(snapshot.rules[:8]),
            },
            *(
                [
                    {
                        "eyebrow": "Support and delivery",
                        "title": "What needs support before the loop slips",
                        "body": "Delivery failures, blocked actions, and support verification stay visible before they turn into executive surprise.",
                        "items": [
                            row_builder(
                                "Support state",
                                str(support_verification.get("summary") or support_verification.get("state") or "No support issue is active."),
                                "Support",
                                href="/app/settings/support",
                            ),
                            row_builder(
                                "Support action",
                                str(support_verification.get("recommended_action") or "Open support diagnostics when something stalls."),
                                "Support",
                                href="/app/settings/support",
                            ),
                            row_builder("Blocked actions", str(len(blocked_actions)), "Support", href="/app/settings/support"),
                            row_builder("Warnings", str(len(warning_messages)), "Support", href="/app/settings/support"),
                            row_builder("Registration email failures", str(analytics_delivery.get("registration_failed") or 0), "Email", href="/app/settings/support"),
                            row_builder("Invite email failures", str(analytics_delivery.get("invite_failed") or 0), "Email", href="/app/settings/support"),
                            row_builder("Digest email failures", str(analytics_delivery.get("digest_failed") or 0), "Email", href="/app/settings/support"),
                        ],
                    },
                    {
                        "eyebrow": "Product control",
                        "title": "What the release proof says right now",
                        "body": "This surface mirrors the weekly product pulse and published journey-gate truth without turning the assistant into a second roadmap owner.",
                        "items": [
                            row_builder("Active product wave", str(product_control.get("active_wave") or "No active wave mirrored."), "Wave", href="/app/settings/outcomes"),
                            row_builder("Journey gate health", str(journey_gate.get("state") or "missing").replace("_", " ").title(), "Gate", href="/app/settings/outcomes"),
                            row_builder("Journey gate action", str(journey_gate.get("recommended_action") or journey_gate.get("reason") or "No published action."), "Gate", href="/app/settings/outcomes"),
                            row_builder("Support fallout", str(support_fallout.get("detail") or "No support fallout mirrored."), "Support", href="/app/settings/outcomes"),
                            row_builder("Launch readiness", str(product_control.get("launch_readiness") or "No launch note mirrored."), "Launch", href="/app/settings/outcomes"),
                            row_builder("Route default", str(route_stewardship.get("default_status") or "No route default note published."), "Route", href="/app/settings/outcomes"),
                            row_builder("Canary posture", str(route_stewardship.get("canary_status") or "No canary note published."), "Route", href="/app/settings/outcomes"),
                            row_builder("Route review due", str(route_stewardship.get("review_due") or "No route review due published."), "Route", href="/app/settings/outcomes"),
                            row_builder("Journey proof freshness", str(journey_freshness.get("detail") or "No journey-gate freshness mirrored."), "Proof", href="/app/settings/outcomes"),
                            row_builder("Public guide freshness", str(public_guide_freshness.get("detail") or "No public-guide freshness mirrored."), "Guide", href="/app/settings/outcomes"),
                        ],
                    },
                ]
                if operator_key
                else []
            ),
        ],
    }
