from __future__ import annotations

from app.services.office_surface_rows import (
    _brief_rows,
    _calendar_pressure_rows,
    _candidate_rows,
    _commitment_rows,
    _commitments_by_status,
    _commitments_due_now,
    _decision_rows,
    _diagnostic_rows,
    _draft_queue_rows,
    _evidence_rows,
    _google_settings_action_row,
    _handoff_rows,
    _people_rows,
    _queue_rows,
    _rule_rows,
    _row,
    _sorted_open_commitments,
    _sorted_people,
    _stale_commitments,
    _suggested_sequence_rows,
    _thread_rows,
)
from app.api.routes.workspace_settings_section import build_settings_section
from app.domain.office.surfaces import OfficeSurfacePayload
from app.product.models import ProductSnapshot
from app.product.projections.common import due_bonus, status_open


def build_workspace_section_payload(
    section: str,
    snapshot: ProductSnapshot,
    diagnostics: dict[str, object] | None = None,
    outcomes: dict[str, object] | None = None,
    *,
    operator_id: str = "",
    brand_key: str = "",
) -> dict[str, object]:
    diagnostics = diagnostics or {}
    outcomes = outcomes or {}
    operator_key = str(operator_id or "").strip()
    property_brand = str(brand_key or "").strip().lower() == "propertyquarry"
    queue_health = dict(diagnostics.get("queue_health") or {})
    provider_posture = dict(diagnostics.get("providers") or {})
    commercial = dict(diagnostics.get("commercial") or {})
    readiness = dict(diagnostics.get("readiness") or {})
    product_control = dict(diagnostics.get("product_control") or {})
    analytics = dict(diagnostics.get("analytics") or {})
    analytics_delivery = dict(analytics.get("delivery") or {})
    analytics_access = dict(analytics.get("access") or {})
    analytics_invitations = dict(analytics.get("invitations") or {})
    analytics_sync = dict(analytics.get("sync") or {})
    support_verification = dict(diagnostics.get("support_verification") or {})
    journey_gate = dict(product_control.get("journey_gate_health") or {})
    journey_freshness = dict(product_control.get("journey_gate_freshness") or {})
    support_fallout = dict(product_control.get("support_fallout") or {})
    public_guide_freshness = dict(product_control.get("public_guide_freshness") or {})
    route_stewardship = dict(product_control.get("provider_route_stewardship") or {})
    memo_loop = dict(outcomes.get("memo_loop") or analytics.get("memo_loop") or {})
    office_loop_proof = dict(outcomes.get("office_loop_proof") or {})
    proof_checks = [dict(value) for value in list(office_loop_proof.get("checks") or [])]
    assignment_suggestions = [dict(value) for value in (queue_health.get("assignment_suggestions") or [])]
    assigned_handoffs = tuple(row for row in snapshot.handoffs if operator_key and row.owner == operator_key)
    unclaimed_handoffs = tuple(row for row in snapshot.handoffs if not operator_key or row.owner != operator_key)
    clearable_queue_items = tuple(row for row in snapshot.queue_items if not bool(row.requires_principal))
    suggested_handoff_ids = {
        str(item.get("id") or "").strip()
        for item in assignment_suggestions
        if str(item.get("id") or "").strip()
    }
    remaining_unclaimed_handoffs = tuple(row for row in unclaimed_handoffs if row.id not in suggested_handoff_ids)
    blocked_actions = [str(value).replace("_", " ") for value in list(commercial.get("blocked_actions") or []) if str(value).strip()]
    warning_messages = [str(value) for value in list(commercial.get("warnings") or []) if str(value).strip()]
    active_memo_delivery_blocker = 1 if str(memo_loop.get("last_issue_reason") or "").strip() else 0
    active_delivery_issue_total = int(queue_health.get("delivery_errors") or 0) + active_memo_delivery_blocker
    exception_rows = [
        _row(
            "Delivery issues",
            (
                f"{int(queue_health.get('delivery_errors') or 0)} queue delivery errors · "
                f"{active_memo_delivery_blocker} active memo blockers"
            ),
            "Support",
            href="/app/settings/support",
        )
        for _ in [0]
        if active_delivery_issue_total
    ] + [
        _row(
            "SLA breaches",
            f"{int(queue_health.get('sla_breaches') or 0)} handoffs already breached their SLA.",
            "Queue",
            href="/admin/office",
        )
        for _ in [0]
        if int(queue_health.get("sla_breaches") or 0)
    ] + [
        _row(
            "Blocked actions",
            ", ".join(blocked_actions[:4]),
            "Plan",
            href="/app/settings/support",
        )
        for _ in [0]
        if blocked_actions
    ] + [
        _row(
            "Commercial warnings",
            "; ".join(warning_messages[:2]),
            "Support",
            href="/app/settings/support",
        )
        for _ in [0]
        if warning_messages
    ] + [
        _row(
            "Provider risk",
            str(provider_posture.get("risk_state") or "unknown").replace("_", " ").title(),
            "Provider",
            href="/app/settings/support",
        )
        for _ in [0]
        if str(provider_posture.get("risk_state") or "").strip().lower() in {"degraded", "critical", "failed"}
    ]
    stats = [
        {"label": "Memo items", "value": str(snapshot.stats_json.get("brief_items", 0))},
        {"label": "Queue items", "value": str(snapshot.stats_json.get("queue_items", 0))},
        {"label": "Commitments", "value": str(snapshot.stats_json.get("commitments", 0))},
        {"label": "Decisions", "value": str(snapshot.stats_json.get("decisions", 0))},
        {"label": "People", "value": str(snapshot.stats_json.get("people", 0))},
    ]
    open_commitments = _sorted_open_commitments(snapshot.commitments)
    due_now_commitments = _commitments_due_now(snapshot.commitments)
    stale_commitments = _stale_commitments(snapshot.commitments)
    waiting_commitments = _commitments_by_status(snapshot.commitments, "waiting_on_external", "scheduled")
    sorted_people = _sorted_people(snapshot.people)
    open_decisions = tuple(value for value in snapshot.decisions if status_open(value.status))
    clearable_queue_items = tuple(row for row in snapshot.queue_items if not bool(row.requires_principal))
    principal_queue = tuple(value for value in snapshot.queue_items if value.requires_principal)
    mapping: dict[str, dict[str, object]] = {
        "today": {
            "title": "Morning Memo",
            "summary": "What changed, what is blocked, and what deserves attention before the day drifts.",
            "cards": [
                {
                    "eyebrow": "Top priorities",
                    "title": "What deserves attention first",
                    "body": "Start on the ranked work that already has evidence, risk, and a visible next move.",
                    "items": _brief_rows(snapshot.brief_items[:6], tag="Priority")
                    or [_row("No top priorities", "The memo has not surfaced any ranked work yet.", "Clear")],
                },
                {
                    "eyebrow": "Blocked decisions",
                    "title": "What needs an explicit call",
                    "body": "Decisions are first-class product objects, not just queue summaries.",
                    "items": _decision_rows(open_decisions[:6], return_to="/app/today")
                    or [_row("No blocked decisions", "Nothing currently needs a decision call from this workspace.", "Clear")],
                },
                {
                    "eyebrow": "At-risk commitments",
                    "title": "What is most likely to slip today",
                    "body": "Promises, deadlines, and commitments stay visible before they silently roll into tomorrow.",
                    "items": _commitment_rows((due_now_commitments or open_commitments)[:6], return_to="/app/today")
                    or [_row("No commitments at risk", "Nothing open is currently due now or overdue.", "Clear")],
                },
                {
                    "eyebrow": "Pending approvals",
                    "title": "What is waiting for review",
                    "body": "Draft approvals remain visible product work instead of leaking into hidden runtime state.",
                    "items": _draft_queue_rows(snapshot.drafts[:6]),
                },
                {
                    "eyebrow": "Stakeholder changes",
                    "title": "Who moved overnight",
                    "body": "People pressure is part of the office loop, not an afterthought.",
                    "items": _people_rows(sorted_people[:6])
                    or [_row("No stakeholder movement", "No people changes are shaping the current workspace view.", "Clear")],
                },
            ],
        },
        "queue": {
            "title": "Queue",
            "summary": "Decisions, drafts, captured work, and active commitments stay inside one bounded review lane.",
            "cards": [
                {
                    "eyebrow": "Decision Queue",
                    "title": "What needs an explicit call",
                    "body": "Decisions and deadlines stay visible before the day fragments into separate tools.",
                    "items": _decision_rows(open_decisions[:8], return_to="/app/queue")
                    or [_row("No blocked decisions", "No unresolved decisions are currently shaping the queue.", "Clear")],
                },
                {
                    "eyebrow": "Draft Queue",
                    "title": "What can be approved right now",
                    "body": "Drafts stay beside the work they affect instead of hiding in a separate mail-only concept.",
                    "items": _draft_queue_rows(snapshot.drafts[:8]),
                },
                {
                    "eyebrow": "Commitment review",
                    "title": "What still needs human judgment",
                    "body": "Captured commitments stay reviewable before they enter the live ledger.",
                    "items": _candidate_rows(snapshot.commitment_candidates[:6])
                    or [_row("No pending captures", "Nothing is waiting to be reviewed into the commitment ledger.", "Clear")],
                },
                {
                    "eyebrow": "Open commitments",
                    "title": "What the queue is protecting",
                    "body": "Queue work matters because it prevents real promises from slipping.",
                    "items": _commitment_rows((due_now_commitments or open_commitments)[:6], return_to="/app/queue")
                    or [_row("No commitments at risk", "No current commitments are pressing on the day.", "Clear")],
                },
                {
                    "eyebrow": "Calendar pressure",
                    "title": "What gets tight first",
                    "body": "Decision and deadline windows read as day pressure, not buried metadata.",
                    "items": _calendar_pressure_rows(snapshot.queue_items),
                },
                {
                    "eyebrow": "People to respond to",
                    "title": "Who is shaping the queue",
                    "body": "Threads and stakeholder context stay attached to the next move.",
                    "items": _thread_rows(snapshot.threads[:6]) or _people_rows(sorted_people[:6]),
                },
                {
                    "eyebrow": "Suggested sequence",
                    "title": "What to clear in order",
                    "body": "Use one explicit sequence for the next moves instead of reconstructing it by hand.",
                    "items": _suggested_sequence_rows(
                        decisions=open_decisions,
                        drafts=snapshot.drafts,
                        commitments=due_now_commitments or open_commitments,
                        people=sorted_people,
                    ),
                },
            ],
        },
        "commitments": {
            "title": "Commitments",
            "summary": "Keep due work, handoffs, unresolved promises, and recent closures visible in one durable commitment lane.",
            "cards": [
                {
                    "eyebrow": "Due now",
                    "title": "What is due today or already overdue",
                    "body": "The commitment lane opens on the work most likely to miss today.",
                    "items": _commitment_rows((due_now_commitments or open_commitments)[:8], return_to="/app/commitments")
                    or [_row("No due commitments", "Nothing open is due now or overdue.", "Clear")],
                },
                {
                    "eyebrow": "Waiting on others",
                    "title": "What is blocked outside the office loop",
                    "body": "Use explicit waiting and scheduled states instead of leaving external dependencies hidden inside open promises.",
                    "items": (
                        _commitment_rows(waiting_commitments[:8], return_to="/app/commitments")
                        + _handoff_rows(snapshot.handoffs[:8], operator_id=operator_key, return_to="/app/commitments")
                    )[:8]
                    or [_row("No external waits", "Nothing is currently waiting on another party or operator handoff.", "Clear")],
                },
                {
                    "eyebrow": "Unresolved promises",
                    "title": "What still needs a close or defer",
                    "body": "Open promises stay clear even when the queue is noisy.",
                    "items": _commitment_rows(open_commitments[:8], return_to="/app/commitments")
                    or [_row("No unresolved promises", "The commitment lane does not currently have open promises.", "Clear")],
                },
                {
                    "eyebrow": "Stale work",
                    "title": "What has drifted too long",
                    "body": "Overdue or untouched commitments are obvious instead of hiding in the ledger.",
                    "items": _commitment_rows(stale_commitments[:8], return_to="/app/commitments")
                    or [_row("No stale commitments", "Open commitments are still moving inside an acceptable window.", "Clear")],
                },
                {
                    "eyebrow": "Recently closed",
                    "title": "What just moved through the loop",
                    "body": "Recently completed commitments and handoffs stay visible long enough to confirm the loop actually closed.",
                    "items": (
                        _commitment_rows(snapshot.recently_closed_commitments[:6], return_to="/app/commitments")
                        + _handoff_rows(snapshot.completed_handoffs[:6], actionable=False, return_to="/app/commitments")
                    )[:6]
                    or [_row("Nothing recently closed", "Completed handoffs will appear here once the loop closes.", "Clear")],
                },
                {
                    "eyebrow": "Stakeholders",
                    "title": "Who the commitment lane affects",
                    "body": "The office loop stays legible when people stay attached to the work.",
                    "items": _people_rows(sorted_people[:6])
                    or [_row("No stakeholder pressure", "No people records are currently attached to this commitment lane.", "Clear")],
                },
            ],
        },
        "people": {
            "title": "People",
            "summary": "People, relationship temperature, open loops, and recurring themes live in one durable relationship system.",
            "cards": [
                {
                    "eyebrow": "People graph",
                    "title": "Who matters right now",
                    "body": "This surface is now backed by stakeholder records and open loops instead of memo hints alone.",
                    "items": _people_rows(snapshot.people[:8]),
                },
                {
                    "eyebrow": "Open loops",
                    "title": "What still hangs off those relationships",
                    "body": "Relationship value comes from the loops still attached to each person.",
                    "items": _commitment_rows(snapshot.commitments[:6]),
                },
                {
                    "eyebrow": "Office pressure",
                    "title": "Which people are shaping the queue",
                    "body": "The queue stays attached to the people who make it matter.",
                    "items": _queue_rows(snapshot.queue_items[:6]),
                },
            ],
        },
        "evidence": {
            "title": "Evidence",
            "summary": "Evidence explains why something surfaced, what supports it, and what action it is driving.",
            "cards": [
                {
                    "eyebrow": "Evidence refs",
                    "title": "What supports the memo",
                    "body": "Evidence is now a first-class product object instead of buried inside row notes.",
                    "items": _evidence_rows(snapshot.evidence[:8]),
                },
                {
                    "eyebrow": "Conversation threads",
                    "title": "Which threads produced the current pressure",
                    "body": "Evidence matters most when it stays connected to active conversations and commitments.",
                    "items": _thread_rows(snapshot.threads[:8]),
                },
                {
                    "eyebrow": "Relationship context",
                    "title": "Who the evidence touches",
                    "body": "Evidence is useful when it stays connected to the right people and commitments.",
                    "items": _people_rows(snapshot.people[:6]),
                },
            ],
        },
        "activity": {
            "title": "Operator Queue",
            "summary": "Assignments, open handoffs, and principal waiting items stay visible as a real operating lane.",
            "cards": [
                {
                    "eyebrow": "Queue health",
                    "title": "Queue health",
                    "body": "SLA breaches, unclaimed work, approvals, and delivery backlog stay visible in one operational view.",
                    "items": [
                        _row("Queue state", str(queue_health.get("state") or "healthy").title(), str(queue_health.get("state") or "healthy").title()),
                        _row("SLA breaches", str(queue_health.get("sla_breaches") or 0), "Queue"),
                        _row("Unclaimed handoffs", str(queue_health.get("unclaimed_handoffs") or 0), "Queue"),
                        _row("Pending approvals", str(queue_health.get("pending_approvals") or 0), "Queue"),
                        _row("Waiting on principal", str(queue_health.get("waiting_on_principal") or 0), "Queue"),
                        _row("Queued delivery", str(queue_health.get("pending_delivery") or 0), "Queue"),
                        _row("Retrying delivery", str(queue_health.get("retrying_delivery") or 0), "Queue"),
                        _row("Delivery errors", str(queue_health.get("delivery_errors") or 0), "Queue"),
                        _row("Load score", str(queue_health.get("load_score") or 0), "Queue"),
                        _row("Oldest handoff age", f"{queue_health.get('oldest_handoff_age_hours') or 0}h", "Queue"),
                        _row("Oldest queued delivery age", f"{queue_health.get('oldest_pending_delivery_age_hours') or 0}h", "Queue"),
                    ],
                },
                {
                    "eyebrow": "Provider posture",
                    "title": "Provider posture",
                    "body": "The operator lane is only trustworthy when provider risk, fallback coverage, and workspace health stay visible.",
                    "items": [
                        _row("Provider risk", str(provider_posture.get("risk_state") or "unknown").replace("_", " ").title(), "Provider"),
                        _row("Ready providers", str(provider_posture.get("ready_count") or 0), "Provider"),
                        _row("Degraded providers", str(provider_posture.get("degraded_count") or 0), "Provider"),
                        _row("Failed providers", str(provider_posture.get("failed_count") or 0), "Provider"),
                        _row("Fallback lanes", str(provider_posture.get("lanes_with_fallback") or 0), "Provider"),
                        _row("Failover-ready lanes", str(provider_posture.get("failover_ready_lanes") or 0), "Provider"),
                        _row("Workspace health score", str(readiness.get("health_score") or 0), "Runtime"),
                        *(
                            [
                                _row("Google account", str(analytics_sync.get("google_account_email") or "Not connected"), "Sync", href="/app/settings/usage"),
                                _row("Google token status", str(analytics_sync.get("google_token_status") or "missing").replace("_", " ").title(), "Sync", href="/app/settings/usage"),
                            ]
                            if property_brand
                            else [
                                _row("Google account", str(analytics_sync.get("google_account_email") or "Not connected"), "Sync", href="/app/settings/usage"),
                                _row("Google token status", str(analytics_sync.get("google_token_status") or "missing").replace("_", " ").title(), "Sync", href="/app/settings/usage"),
                                _row("Google sync runs", str(analytics_sync.get("google_sync_completed") or 0), "Sync", href="/app/settings/usage"),
                                _row("Last Google sync", str(analytics_sync.get("google_sync_last_completed_at") or "Not yet run"), "Sync", href="/app/settings/usage"),
                                _row("Office signals ingested", str(analytics_sync.get("office_signal_ingested") or 0), "Sync", href="/app/settings/usage"),
                                _row("Pending sync candidates", str(analytics_sync.get("pending_commitment_candidates") or 0), "Sync", href="/app/queue"),
                            ]
                        ),
                    ],
                },
                {
                    "eyebrow": "Delivery and access",
                    "title": "Registration, invite, and digest delivery",
                    "body": "The operator lane shows whether people can actually enter the workspace and receive the compact loop.",
                    "items": [
                        _row("Registration emails sent", str(analytics_delivery.get("registration_sent") or 0), "Email", href="/app/settings/usage"),
                        _row("Registration email failures", str(analytics_delivery.get("registration_failed") or 0), "Email", href="/app/settings/support"),
                        _row("Invite emails sent", str(analytics_delivery.get("invite_sent") or 0), "Email", href="/app/settings/support"),
                        _row("Invite email failures", str(analytics_delivery.get("invite_failed") or 0), "Email", href="/app/settings/support"),
                        _row("Digest emails sent", str(analytics_delivery.get("digest_sent") or 0), "Email", href="/app/channel-loop"),
                        _row("Digest email failures", str(analytics_delivery.get("digest_failed") or 0), "Email", href="/app/settings/support"),
                        _row("Active access sessions", str(analytics_access.get("active") or 0), "Access", href="/app/settings/support"),
                        _row("Access links opened", str(analytics_access.get("opened") or 0), "Access", href="/app/settings/support"),
                        _row("Access sessions revoked", str(analytics_access.get("revoked") or 0), "Access", href="/app/settings/support"),
                    ],
                },
                {
                    "eyebrow": "Suggested next claims",
                    "title": "Suggested next claims",
                    "body": "Claim suggestions rank unclaimed work before it ages into a visible office miss.",
                    "items": [
                        _row(
                            str(item.get("summary") or item.get("id") or "Suggested claim"),
                            " · ".join(
                                part
                                for part in (
                                    str(item.get("owner") or "").strip() or "Unclaimed",
                                    f"Due {str(item.get('due_time') or '')[:10]}" if str(item.get("due_time") or "").strip() else "",
                                    str(item.get("escalation_status") or "").replace("_", " ").title(),
                                )
                                if part
                            )
                            or "Claim this handoff before it misses the office loop.",
                            "Suggestion",
                            href=f"/app/handoffs/{str(item.get('id') or '')}" if str(item.get("id") or "").strip() else "",
                            action_href=f"/app/actions/handoffs/{str(item.get('id') or '')}/assign" if str(item.get("id") or "").strip() else "",
                            action_label="Claim" if str(item.get("id") or "").strip() else "",
                            action_value="assign" if str(item.get("id") or "").strip() else "",
                            return_to="/admin/office" if str(item.get("id") or "").strip() else "",
                        )
                        for item in assignment_suggestions[:3]
                    ]
                    or [_row("No claim suggestions", "The unclaimed operator lane is currently clear.", "Clear")],
                },
                {
                    "eyebrow": "Pre-clear",
                    "title": "Clear before principal",
                    "body": "These queue items can be closed, resolved, or approved inside the operator lane before they become principal noise.",
                    "items": _queue_rows(clearable_queue_items[:8])
                    or [_row("Nothing to pre-clear", "The remaining queue currently depends on the principal.", "Clear")],
                },
                {
                    "eyebrow": "Assigned to me",
                    "title": "What already belongs to this operator lane",
                    "body": "Assigned work stays separate from the claimable backlog.",
                    "items": _handoff_rows(assigned_handoffs[:8], operator_id=operator_key, return_to="/admin/office"),
                },
                {
                    "eyebrow": "Unclaimed handoffs",
                    "title": "What can be claimed next",
                    "body": "Operator work stays explicit, claimable, and closable from the same queue.",
                    "items": _handoff_rows(remaining_unclaimed_handoffs[:8], operator_id=operator_key, return_to="/admin/office")
                    or [_row("No unclaimed handoffs", "Suggested claims already cover the current claimable backlog.", "Clear")],
                },
                {
                    "eyebrow": "Waiting on principal",
                    "title": "What still needs executive clearance",
                    "body": "Approval-backed drafts and decision windows do not disappear into admin surfaces.",
                    "items": _queue_rows(principal_queue[:8]),
                },
                {
                    "eyebrow": "Exceptions",
                    "title": "Exception queue",
                    "body": "Failures, breaches, provider risk, and plan blockers belong in one exception lane instead of leaking into normal work.",
                    "items": exception_rows
                    or [_row("No active exceptions", "The operator lane is clear of delivery, SLA, provider, and commercial exceptions.", "Clear")],
                },
                {
                    "eyebrow": "Recently completed",
                    "title": "What just moved through the operator lane",
                    "body": "Returned handoffs and recently closed commitments stay visible long enough to confirm the office loop actually closed.",
                    "items": (
                        _commitment_rows(snapshot.recently_closed_commitments[:6], return_to="/admin/office")
                        + _handoff_rows(snapshot.completed_handoffs[:6], actionable=False)
                    )[:6],
                },
                {
                    "eyebrow": "Commitment pressure",
                    "title": "What operator work is protecting",
                    "body": "Operator tasks are only useful when they keep the right commitments from slipping.",
                    "items": _commitment_rows(snapshot.commitments[:8], return_to="/admin/office"),
                },
                {
                    "eyebrow": "Affected stakeholders",
                    "title": "Who the office control surface is serving",
                    "body": "The operator lane stays tied to the people and relationships it serves.",
                    "items": _people_rows(snapshot.people[:6]),
                },
                {
                    "eyebrow": "Commercial pressure",
                    "title": "What the plan boundary is blocking",
                    "body": "Operator work gets noisy when seat limits, messaging scope, or support posture are out of sync with the office loop.",
                    "items": [
                        _row("Recommended plan", str(commercial.get("recommended_plan_label") or "Current plan"), "Plan", href="/app/settings/plan"),
                        _row(
                            "Blocked actions",
                            ", ".join(str(value).replace("_", " ") for value in (commercial.get("blocked_actions") or [])[:6]) or "No blocked actions",
                            "Support",
                            href="/app/settings/support",
                        ),
                        _row(
                            "Warnings",
                            "; ".join(str(value) for value in (commercial.get("warnings") or []) if str(value).strip()) or "No current warnings",
                            "Support",
                            href="/app/settings/support",
                        ),
                    ],
                },
            ],
        },
        "settings": build_settings_section(
            snapshot=snapshot,
            diagnostics=diagnostics,
            outcomes=outcomes,
            property_brand=property_brand,
            memo_loop=memo_loop,
            office_loop_proof=office_loop_proof,
            proof_checks=proof_checks,
            analytics=analytics,
            analytics_delivery=analytics_delivery,
            analytics_access=analytics_access,
            analytics_invitations=analytics_invitations,
            analytics_sync=analytics_sync,
            support_verification=support_verification,
            blocked_actions=blocked_actions,
            warning_messages=warning_messages,
            operator_key=operator_key,
            product_control=product_control,
            journey_gate=journey_gate,
            journey_freshness=journey_freshness,
            support_fallout=support_fallout,
            public_guide_freshness=public_guide_freshness,
            route_stewardship=route_stewardship,
            row_builder=_row,
            rule_rows_builder=_rule_rows,
            google_settings_action_row_builder=lambda sync: _google_settings_action_row(sync, return_to="/app/settings/google"),
        ),
    }
    return OfficeSurfacePayload.from_mapping({"stats": stats, **mapping[section]}).as_template_payload()
