from __future__ import annotations

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
    operator_key = str(operator_id or "").strip()
    owner = str(handoff.owner or "").strip()
    if not operator_key or owner != operator_key:
        return {"kind": "assign", "label": "Claim", "value": "assign"}
    if str(handoff.task_type or "").strip() == "delivery_followup":
        delivery_reason = str(handoff.delivery_reason or "").strip()
        secondary_value = "reauth_needed" if delivery_reason.startswith("google_") else "failed"
        secondary_label = "Needs reauth" if secondary_value == "reauth_needed" else "Unable to send"
        return {
            "kind": "complete",
            "label": "Mark sent",
            "value": "sent",
            "secondary_label": secondary_label,
            "secondary_value": secondary_value,
        }
    return {"kind": "complete", "label": "Complete", "value": "completed"}
