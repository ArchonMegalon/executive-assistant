from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.services.hedy_meeting_evidence import HedyMeetingEvidenceService


class _HedyReviewTask(Protocol):
    human_task_id: str
    task_type: str
    priority: str
    authority_required: str


class _HedyReviewQueue(Protocol):
    def find_human_task_by_dedupe(self, dedupe_key: str, *, principal_id: str) -> _HedyReviewTask | None: ...

    def create_human_task(
        self,
        *,
        principal_id: str,
        task_type: str,
        priority: str,
        authority_required: str,
        input_json: dict[str, object],
        dedupe_key: str,
    ) -> _HedyReviewTask: ...


@dataclass(frozen=True)
class HedyMeetingReviewIntakeResult:
    payload: dict[str, object]

    def as_dict(self) -> dict[str, object]:
        return dict(self.payload)


class HedyMeetingReviewIntakeService:
    def __init__(self, *, orchestrator: _HedyReviewQueue, webhook_secret: str, clock=None) -> None:
        self._orchestrator = orchestrator
        self._evidence = HedyMeetingEvidenceService(webhook_secret=webhook_secret, clock=clock)

    def ingest_webhook_to_review_queue(
        self,
        *,
        body: bytes,
        headers: dict[str, object],
        principal_id: str,
        workspace_id: str = "",
    ) -> HedyMeetingReviewIntakeResult:
        packet = self._evidence.ingest_webhook(
            body=body,
            headers=headers,
            principal_id=principal_id,
            workspace_id=workspace_id,
        )
        counts = {
            "evidence": len(list(packet.get("evidence_candidates") or [])),
            "commitments": len(list(packet.get("commitment_candidates") or [])),
            "decisions": len(list(packet.get("decision_candidates") or [])),
            "people_memory": len(list(packet.get("people_memory_candidates") or [])),
            "drafts": len(list(packet.get("draft_candidates") or [])),
        }
        if str(packet.get("status") or "").strip() != "review_required":
            return HedyMeetingReviewIntakeResult(
                {
                    "contract_name": "ea.hedy_meeting_review_intake.v1",
                    "status": str(packet.get("status") or "").strip(),
                    "created_review_task": False,
                    "duplicate": False,
                    "human_task": {},
                    "packet": packet,
                    "candidate_counts": counts,
                }
            )
        dedupe_key = str(packet.get("idempotency_key") or "").strip()
        existing = self._orchestrator.find_human_task_by_dedupe(dedupe_key, principal_id=principal_id)
        duplicate = existing is not None or str(packet.get("ingest_status") or "").strip() == "duplicate"
        task = existing or self._orchestrator.create_human_task(
            principal_id=principal_id,
            task_type="hedy_meeting_review",
            priority="high" if counts["decisions"] else "normal",
            authority_required="principal_or_operator_review",
            input_json={"hedy_idempotency_key": dedupe_key, "hedy_packet": packet},
            dedupe_key=dedupe_key,
        )
        return HedyMeetingReviewIntakeResult(
            {
                "contract_name": "ea.hedy_meeting_review_intake.v1",
                "status": "review_required",
                "created_review_task": not duplicate,
                "duplicate": duplicate,
                "human_task": {
                    "human_task_id": task.human_task_id,
                    "task_type": task.task_type,
                    "priority": task.priority,
                    "authority_required": task.authority_required,
                },
                "packet": packet,
                "candidate_counts": counts,
            }
        )
