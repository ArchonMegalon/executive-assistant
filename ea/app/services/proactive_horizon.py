from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.domain.models import TaskExecutionRequest
from app.services.channel_runtime import ChannelRuntimeService
from app.services.memory_runtime import MemoryRuntimeService
from app.services.orchestrator import RewriteOrchestrator
from app.services.task_contracts import TaskContractService


@dataclass(frozen=True)
class HorizonCandidate:
    kind: str
    record_id: str
    principal_id: str
    due_at: str
    task_key: str
    goal: str
    source_text: str
    context_refs: tuple[str, ...]
    dedupe_key: str


class ProactiveHorizonService:
    def __init__(
        self,
        *,
        memory_runtime: MemoryRuntimeService,
        orchestrator: RewriteOrchestrator,
        task_contracts: TaskContractService,
        channel_runtime: ChannelRuntimeService,
        scan_window_hours: int = 24,
    ) -> None:
        self._memory_runtime = memory_runtime
        self._orchestrator = orchestrator
        self._task_contracts = task_contracts
        self._channel_runtime = channel_runtime
        self._scan_window_hours = max(1, int(scan_window_hours or 24))
        self._log = logging.getLogger("ea.proactive_horizon")

    def scan(self, *, now: datetime | None = None) -> tuple[HorizonCandidate, ...]:
        observed_at = now or datetime.now(timezone.utc)
        horizon_end = observed_at + timedelta(hours=self._scan_window_hours)
        candidates: list[HorizonCandidate] = []
        candidates.extend(self._decision_window_candidates(closes_before=horizon_end.isoformat()))
        candidates.extend(self._deadline_window_candidates(ends_before=horizon_end.isoformat()))
        candidates.extend(self._commitment_candidates(due_before=horizon_end.isoformat()))
        candidates.sort(key=lambda row: (row.due_at, row.principal_id, row.kind, row.record_id))
        return tuple(candidates)

    def run_once(self, *, now: datetime | None = None) -> tuple[HorizonCandidate, ...]:
        launched: list[HorizonCandidate] = []
        for candidate in self.scan(now=now):
            if self._channel_runtime.find_observation_by_dedupe(candidate.dedupe_key) is not None:
                continue
            try:
                _ = self._orchestrator.execute_task_artifact(
                    TaskExecutionRequest(
                        task_key=candidate.task_key,
                        principal_id=candidate.principal_id,
                        goal=candidate.goal,
                        input_json={
                            "source_text": candidate.source_text,
                            "normalized_text": candidate.source_text,
                            "text_length": len(candidate.source_text),
                            "proactive_horizon_kind": candidate.kind,
                            "proactive_horizon_due_at": candidate.due_at,
                            "context_refs": list(candidate.context_refs),
                        },
                        context_refs=candidate.context_refs,
                    )
                )
            except Exception:
                self._log.exception(
                    "failed to enqueue proactive horizon candidate kind=%s principal=%s record=%s",
                    candidate.kind,
                    candidate.principal_id,
                    candidate.record_id,
                )
                continue
            self._channel_runtime.ingest_observation(
                principal_id=candidate.principal_id,
                channel="system",
                event_type="system.proactive_horizon_enqueued",
                payload={
                    "kind": candidate.kind,
                    "record_id": candidate.record_id,
                    "due_at": candidate.due_at,
                    "task_key": candidate.task_key,
                    "context_refs": list(candidate.context_refs),
                },
                dedupe_key=candidate.dedupe_key,
                auth_context_json={"actor_type": "system", "principal_originated": False},
            )
            launched.append(candidate)
        return tuple(launched)

    def _preferred_task_key(self, *task_keys: str) -> str:
        for task_key in task_keys:
            normalized = str(task_key or "").strip()
            if normalized and self._task_contracts.get_contract(normalized) is not None:
                return normalized
        return "rewrite_text"

    def _decision_window_candidates(self, *, closes_before: str) -> list[HorizonCandidate]:
        rows = self._memory_runtime.list_open_decision_windows_closing_before(closes_before=closes_before)
        task_key = self._preferred_task_key("meeting_prep", "decision_briefing", "rewrite_text")
        candidates: list[HorizonCandidate] = []
        for row in rows:
            due_at = str(row.closes_at or "").strip()
            if not due_at:
                continue
            source_text = (
                f"Prepare a concise decision brief for '{row.title}'. "
                f"Decision context: {str(row.context or '').strip() or 'No extra context provided.'} "
                f"Authority required: {str(row.authority_required or '').strip() or 'unspecified'}. "
                f"Close time: {due_at}. "
                "Focus on the decisions that must be made next, the missing facts, and the shortest recommended path."
            )
            candidates.append(
                HorizonCandidate(
                    kind="decision_window",
                    record_id=row.decision_window_id,
                    principal_id=row.principal_id,
                    due_at=due_at,
                    task_key=task_key,
                    goal=f"prepare a proactive decision brief before '{row.title}' closes",
                    source_text=source_text,
                    context_refs=(f"decision_window:{row.decision_window_id}",),
                    dedupe_key=f"proactive_horizon:decision_window:{row.decision_window_id}",
                )
            )
        return candidates

    def _deadline_window_candidates(self, *, ends_before: str) -> list[HorizonCandidate]:
        rows = self._memory_runtime.list_open_deadline_windows_ending_before(ends_before=ends_before)
        task_key = self._preferred_task_key("stakeholder_briefing", "meeting_prep", "rewrite_text")
        candidates: list[HorizonCandidate] = []
        for row in rows:
            due_at = str(row.end_at or "").strip()
            if not due_at:
                continue
            source_text = (
                f"Prepare a deadline briefing for '{row.title}'. "
                f"Window closes at {due_at}. "
                f"Priority: {str(row.priority or '').strip() or 'medium'}. "
                f"Notes: {str(row.notes or '').strip() or 'No extra notes provided.'} "
                "Surface the next actions, what could slip, and what should be communicated before the deadline."
            )
            candidates.append(
                HorizonCandidate(
                    kind="deadline_window",
                    record_id=row.window_id,
                    principal_id=row.principal_id,
                    due_at=due_at,
                    task_key=task_key,
                    goal=f"prepare a proactive deadline briefing before '{row.title}' ends",
                    source_text=source_text,
                    context_refs=(f"deadline_window:{row.window_id}",),
                    dedupe_key=f"proactive_horizon:deadline_window:{row.window_id}",
                )
            )
        return candidates

    def _commitment_candidates(self, *, due_before: str) -> list[HorizonCandidate]:
        rows = self._memory_runtime.list_open_commitments_due_before(due_before=due_before)
        task_key = self._preferred_task_key("stakeholder_briefing", "meeting_prep", "rewrite_text")
        candidates: list[HorizonCandidate] = []
        for row in rows:
            due_at = str(row.due_at or "").strip()
            if not due_at:
                continue
            source_text = (
                f"Prepare a commitment follow-through brief for '{row.title}'. "
                f"Due at {due_at}. "
                f"Priority: {str(row.priority or '').strip() or 'medium'}. "
                f"Details: {str(row.details or '').strip() or 'No extra details provided.'} "
                "Summarize what must happen next, who should be informed, and the fastest credible completion path."
            )
            candidates.append(
                HorizonCandidate(
                    kind="commitment",
                    record_id=row.commitment_id,
                    principal_id=row.principal_id,
                    due_at=due_at,
                    task_key=task_key,
                    goal=f"prepare a proactive commitment brief before '{row.title}' is due",
                    source_text=source_text,
                    context_refs=(f"commitment:{row.commitment_id}",),
                    dedupe_key=f"proactive_horizon:commitment:{row.commitment_id}",
                )
            )
        return candidates
