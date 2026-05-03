from __future__ import annotations

import urllib.parse

from app.domain.models import HumanTask
from app.product.models import EvidenceRef, HandoffNote


def handoff_from_human_task(task: HumanTask) -> HandoffNote:
    input_json = dict(task.input_json or {})
    return HandoffNote(
        id=f"human_task:{task.human_task_id}",
        queue_item_ref=f"human_task:{task.human_task_id}",
        summary=task.brief,
        owner=task.assigned_operator_id or task.role_required or "operator",
        due_time=task.sla_due_at,
        escalation_status=task.priority,
        status=task.status,
        task_type=str(task.task_type or "").strip(),
        resolution=str(task.resolution or "").strip(),
        property_url=str(input_json.get("property_url") or "").strip(),
        listing_id=str(input_json.get("listing_id") or "").strip(),
        variant_key=str(input_json.get("variant_key") or "").strip(),
        blocked_reason=str(input_json.get("blocked_reason") or "").strip(),
        tour_url=str(input_json.get("tour_url") or "").strip(),
        connector_binding_id=str(input_json.get("connector_binding_id") or "").strip(),
        vendor_tour_url=str(input_json.get("vendor_tour_url") or "").strip(),
        editor_url=str(input_json.get("editor_url") or "").strip(),
        source_ref=str(input_json.get("source_ref") or "").strip(),
        external_id=str(input_json.get("external_id") or "").strip(),
        draft_ref=str(input_json.get("draft_ref") or "").strip(),
        recipient_email=str(input_json.get("recipient_email") or "").strip(),
        subject=str(input_json.get("subject") or "").strip(),
        delivery_reason=str(input_json.get("reason") or "").strip(),
        evidence_refs=(
            EvidenceRef(ref_id=f"human_task:{task.human_task_id}", label="Human task", source_type="human_task", note=task.why_human),
            EvidenceRef(ref_id=f"session:{task.session_id}", label="Session", source_type="session", note=task.step_id or ""),
        ),
    )


def handoff_action_plan(handoff: HandoffNote, *, operator_id: str = "") -> dict[str, str]:
    options = handoff_action_options(handoff, operator_id=operator_id)
    return dict(options[0]) if options else {}


def handoff_action_options(
    handoff: HandoffNote,
    *,
    operator_id: str = "",
    return_to: str = "",
) -> tuple[dict[str, str], ...]:
    operator_key = str(operator_id or "").strip()
    owner = str(handoff.owner or "").strip()
    if not operator_key or owner != operator_key:
        return (
            {
                "kind": "assign",
                "label": "Claim",
                "value": "assign",
                "route": "assign",
                "method": "post",
                "channel_action": "assign",
            },
        )
    if _property_tour_followup_open(handoff):
        options: list[dict[str, str]] = [
            {
                "kind": "recreate",
                "label": "Recreate tour",
                "route": "recreate",
                "method": "post",
                "channel_action": "recreate",
            },
            {
                "kind": "complete",
                "label": "Mark sent",
                "value": "sent",
                "route": "complete",
                "method": "post",
                "channel_action": "sent",
            },
            {
                "kind": "complete",
                "label": "Unable to process",
                "value": "failed",
                "route": "complete",
                "method": "post",
                "channel_action": "failed",
            },
            {
                "kind": "complete",
                "label": "Waiting on principal",
                "value": "waiting_on_principal",
                "route": "complete",
                "method": "post",
                "channel_action": "waiting_on_principal",
            },
        ]
        return tuple(options)
    if _delivery_followup_open(handoff):
        delivery_reason = str(handoff.delivery_reason or "").strip()
        resolved_return_to = str(return_to or f"/app/handoffs/{handoff.id}").strip() or f"/app/handoffs/{handoff.id}"
        options: list[dict[str, str]] = [
            {
                "kind": "retry_send",
                "label": "Retry send",
                "route": "retry-send",
                "method": "post",
                "channel_action": "retry_send",
            }
        ]
        if delivery_reason.startswith("google_"):
            options.append(
                {
                    "kind": "connect_google",
                    "label": _google_connect_label(delivery_reason),
                    "href": (
                        "/app/actions/google/connect?return_to="
                        + urllib.parse.quote(resolved_return_to, safe="/:?=&")
                    ),
                    "method": "get",
                }
            )
        else:
            options.append(
                {
                    "kind": "complete",
                    "label": "Unable to send",
                    "value": "failed",
                    "route": "complete",
                    "method": "post",
                    "channel_action": "failed",
                }
            )
        options.append(
            {
                "kind": "complete",
                "label": "Mark sent",
                "value": "sent",
                "route": "complete",
                "method": "post",
                "channel_action": "sent",
            }
        )
        options.append(
            {
                "kind": "complete",
                "label": "Waiting on principal",
                "value": "waiting_on_principal",
                "route": "complete",
                "method": "post",
                "channel_action": "waiting_on_principal",
            }
        )
        return tuple(options)
    return (
        {
            "kind": "complete",
            "label": "Complete",
            "value": "completed",
            "route": "complete",
            "method": "post",
            "channel_action": "completed",
        },
    )


def _delivery_followup_open(handoff: HandoffNote) -> bool:
    return (
        str(handoff.task_type or "").strip() == "delivery_followup"
        and str(handoff.status or "").strip() in {"open", "pending", "claimed"}
        and str(handoff.resolution or "").strip() != "sent"
    )


def _property_tour_followup_open(handoff: HandoffNote) -> bool:
    return (
        str(handoff.task_type or "").strip() == "property_tour_followup"
        and str(handoff.status or "").strip() in {"open", "pending", "claimed"}
    )


def _google_connect_label(reason: str) -> str:
    normalized = str(reason or "").strip().lower()
    if normalized in {"google_oauth_binding_not_found", "google_account_missing"}:
        return "Connect Google"
    return "Reconnect Google"
