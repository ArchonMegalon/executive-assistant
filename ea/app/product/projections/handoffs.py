from __future__ import annotations

from app.domain.models import HumanTask
from app.product.models import EvidenceRef, HandoffNote


def handoff_from_human_task(task: HumanTask) -> HandoffNote:
    return HandoffNote(
        id=f"human_task:{task.human_task_id}",
        queue_item_ref=f"human_task:{task.human_task_id}",
        summary=task.brief,
        owner=task.assigned_operator_id or task.role_required or "operator",
        due_time=task.sla_due_at,
        escalation_status=task.priority,
        status=task.status,
        evidence_refs=(
            EvidenceRef(ref_id=f"human_task:{task.human_task_id}", label="Human task", source_type="human_task", note=task.why_human),
            EvidenceRef(ref_id=f"session:{task.session_id}", label="Session", source_type="session", note=task.step_id or ""),
        ),
    )
