from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from app.services.memory_runtime import MemoryRuntimeService


def _parse_datetime(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    normalized = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _normalize_key(value: object) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _serialize_row(row: object, *, fields: tuple[str, ...]) -> dict[str, Any]:
    return {field: getattr(row, field) for field in fields}


@dataclass(frozen=True)
class MemoryPromotionSignal:
    candidate_id: str
    category: str
    summary: str
    confidence: float
    score: float
    reasons: tuple[str, ...] = ()
    overlapping_item_ids: tuple[str, ...] = ()
    conflict_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class MemoryConflict:
    conflict_id: str
    conflict_type: str
    severity: str
    summary: str
    left_ref: str
    right_ref: str
    fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class CommitmentRisk:
    risk_id: str
    risk_type: str
    severity: str
    reference_kind: str
    reference_id: str
    title: str
    due_at: str | None
    summary: str
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class ContextPack:
    principal_id: str
    task_key: str
    goal: str
    context_refs: tuple[str, ...] = ()
    summary: str = ""
    memory_items: tuple[dict[str, Any], ...] = ()
    stakeholders: tuple[dict[str, Any], ...] = ()
    commitments: tuple[dict[str, Any], ...] = ()
    deadlines: tuple[dict[str, Any], ...] = ()
    decision_windows: tuple[dict[str, Any], ...] = ()
    follow_ups: tuple[dict[str, Any], ...] = ()
    authority_bindings: tuple[dict[str, Any], ...] = ()
    delivery_preferences: tuple[dict[str, Any], ...] = ()
    communication_policies: tuple[dict[str, Any], ...] = ()
    interruption_budgets: tuple[dict[str, Any], ...] = ()
    promotion_signals: tuple[MemoryPromotionSignal, ...] = ()
    conflicts: tuple[MemoryConflict, ...] = ()
    commitment_risks: tuple[CommitmentRisk, ...] = ()
    unresolved_refs: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "principal_id": self.principal_id,
            "task_key": self.task_key,
            "goal": self.goal,
            "context_refs": list(self.context_refs),
            "summary": self.summary,
            "memory_items": [dict(row) for row in self.memory_items],
            "stakeholders": [dict(row) for row in self.stakeholders],
            "commitments": [dict(row) for row in self.commitments],
            "deadlines": [dict(row) for row in self.deadlines],
            "decision_windows": [dict(row) for row in self.decision_windows],
            "follow_ups": [dict(row) for row in self.follow_ups],
            "authority_bindings": [dict(row) for row in self.authority_bindings],
            "delivery_preferences": [dict(row) for row in self.delivery_preferences],
            "communication_policies": [dict(row) for row in self.communication_policies],
            "interruption_budgets": [dict(row) for row in self.interruption_budgets],
            "promotion_signals": [
                {
                    "candidate_id": row.candidate_id,
                    "category": row.category,
                    "summary": row.summary,
                    "confidence": row.confidence,
                    "score": row.score,
                    "reasons": list(row.reasons),
                    "overlapping_item_ids": list(row.overlapping_item_ids),
                    "conflict_refs": list(row.conflict_refs),
                }
                for row in self.promotion_signals
            ],
            "conflicts": [
                {
                    "conflict_id": row.conflict_id,
                    "conflict_type": row.conflict_type,
                    "severity": row.severity,
                    "summary": row.summary,
                    "left_ref": row.left_ref,
                    "right_ref": row.right_ref,
                    "fields": list(row.fields),
                }
                for row in self.conflicts
            ],
            "commitment_risks": [
                {
                    "risk_id": row.risk_id,
                    "risk_type": row.risk_type,
                    "severity": row.severity,
                    "reference_kind": row.reference_kind,
                    "reference_id": row.reference_id,
                    "title": row.title,
                    "due_at": row.due_at,
                    "summary": row.summary,
                    "reasons": list(row.reasons),
                }
                for row in self.commitment_risks
            ],
            "unresolved_refs": list(self.unresolved_refs),
        }


class MemoryReasoningService:
    def __init__(self, memory_runtime: MemoryRuntimeService) -> None:
        self._memory_runtime = memory_runtime

    def build_context_pack(
        self,
        *,
        principal_id: str,
        task_key: str,
        goal: str = "",
        context_refs: tuple[str, ...] = (),
        limit: int = 5,
    ) -> ContextPack:
        capped_limit = max(1, min(20, int(limit or 5)))
        memory_items = self._memory_runtime.list_items(limit=100, principal_id=principal_id)
        stakeholders = self._memory_runtime.list_stakeholders(principal_id=principal_id, status="active", limit=100)
        commitments = self._memory_runtime.list_commitments(principal_id=principal_id, status="open", limit=100)
        commitments += self._memory_runtime.list_commitments(principal_id=principal_id, status="in_progress", limit=100)
        deadlines = self._memory_runtime.list_deadline_windows(principal_id=principal_id, limit=100)
        decision_windows = self._memory_runtime.list_decision_windows(principal_id=principal_id, limit=100)
        follow_ups = self._memory_runtime.list_follow_ups(principal_id=principal_id, limit=100)
        authority_bindings = self._memory_runtime.list_authority_bindings(principal_id=principal_id, limit=100)
        delivery_preferences = self._memory_runtime.list_delivery_preferences(principal_id=principal_id, limit=100)
        communication_policies = self._memory_runtime.list_communication_policies(principal_id=principal_id, limit=100)
        interruption_budgets = self._memory_runtime.list_interruption_budgets(principal_id=principal_id, limit=100)
        pending_candidates = self._memory_runtime.list_candidates(
            limit=100,
            status="pending",
            principal_id=principal_id,
        )

        selected_memory_items, unresolved_refs = self._select_memory_items(
            memory_items=memory_items,
            context_refs=context_refs,
            limit=capped_limit,
        )
        selected_stakeholders = stakeholders[:capped_limit]
        selected_commitments = commitments[:capped_limit]
        selected_deadlines = deadlines[:capped_limit]
        selected_decision_windows = decision_windows[:capped_limit]
        selected_follow_ups = follow_ups[:capped_limit]
        selected_authority_bindings = authority_bindings[:capped_limit]
        selected_delivery_preferences = delivery_preferences[:capped_limit]
        selected_communication_policies = communication_policies[:capped_limit]
        selected_interruption_budgets = interruption_budgets[:capped_limit]

        conflicts = self._detect_conflicts(memory_items=selected_memory_items, candidates=pending_candidates)
        promotion_signals = self._build_promotion_signals(
            candidates=pending_candidates,
            memory_items=selected_memory_items,
            conflicts=conflicts,
        )[:capped_limit]
        commitment_risks = self._build_commitment_risks(
            commitments=selected_commitments,
            deadlines=selected_deadlines,
            decision_windows=selected_decision_windows,
            follow_ups=selected_follow_ups,
            interruption_budgets=selected_interruption_budgets,
            authority_bindings=selected_authority_bindings,
        )[:capped_limit]

        summary_parts = []
        if selected_commitments:
            summary_parts.append(f"{len(selected_commitments)} active commitments")
        if selected_stakeholders:
            summary_parts.append(f"{len(selected_stakeholders)} active stakeholders")
        if commitment_risks:
            summary_parts.append(f"{len(commitment_risks)} commitment risks")
        if conflicts:
            summary_parts.append(f"{len(conflicts)} memory conflicts")
        if promotion_signals:
            summary_parts.append(f"{len(promotion_signals)} promotion candidates")
        summary = ", ".join(summary_parts) or "No relevant memory context found."

        return ContextPack(
            principal_id=principal_id,
            task_key=task_key,
            goal=str(goal or "").strip(),
            context_refs=tuple(context_refs),
            summary=summary,
            memory_items=tuple(
                _serialize_row(
                    row,
                    fields=(
                        "item_id",
                        "category",
                        "summary",
                        "fact_json",
                        "confidence",
                        "sensitivity",
                        "sharing_policy",
                        "last_verified_at",
                        "updated_at",
                    ),
                )
                for row in selected_memory_items
            ),
            stakeholders=tuple(
                _serialize_row(
                    row,
                    fields=(
                        "stakeholder_id",
                        "display_name",
                        "channel_ref",
                        "authority_level",
                        "importance",
                        "response_cadence",
                        "tone_pref",
                        "open_loops_json",
                        "friction_points_json",
                        "last_interaction_at",
                    ),
                )
                for row in selected_stakeholders
            ),
            commitments=tuple(
                _serialize_row(
                    row,
                    fields=("commitment_id", "title", "details", "status", "priority", "due_at", "source_json", "updated_at"),
                )
                for row in selected_commitments
            ),
            deadlines=tuple(
                _serialize_row(
                    row,
                    fields=("window_id", "title", "start_at", "end_at", "status", "priority", "notes", "source_json"),
                )
                for row in selected_deadlines
            ),
            decision_windows=tuple(
                _serialize_row(
                    row,
                    fields=(
                        "decision_window_id",
                        "title",
                        "context",
                        "opens_at",
                        "closes_at",
                        "urgency",
                        "authority_required",
                        "status",
                        "notes",
                    ),
                )
                for row in selected_decision_windows
            ),
            follow_ups=tuple(
                _serialize_row(
                    row,
                    fields=("follow_up_id", "stakeholder_ref", "topic", "status", "due_at", "channel_hint", "notes"),
                )
                for row in selected_follow_ups
            ),
            authority_bindings=tuple(
                _serialize_row(
                    row,
                    fields=("binding_id", "subject_ref", "action_scope", "approval_level", "channel_scope", "status"),
                )
                for row in selected_authority_bindings
            ),
            delivery_preferences=tuple(
                _serialize_row(
                    row,
                    fields=("preference_id", "channel", "recipient_ref", "cadence", "quiet_hours_json", "format_json"),
                )
                for row in selected_delivery_preferences
            ),
            communication_policies=tuple(
                _serialize_row(
                    row,
                    fields=("policy_id", "scope", "preferred_channel", "tone", "max_length", "quiet_hours_json"),
                )
                for row in selected_communication_policies
            ),
            interruption_budgets=tuple(
                _serialize_row(
                    row,
                    fields=("budget_id", "scope", "window_kind", "budget_minutes", "used_minutes", "reset_at", "status"),
                )
                for row in selected_interruption_budgets
            ),
            promotion_signals=tuple(promotion_signals),
            conflicts=tuple(conflicts[:capped_limit]),
            commitment_risks=tuple(commitment_risks),
            unresolved_refs=tuple(unresolved_refs),
        )

    def _select_memory_items(
        self,
        *,
        memory_items: list[object],
        context_refs: tuple[str, ...],
        limit: int,
    ) -> tuple[list[object], list[str]]:
        selected: list[object] = []
        unresolved: list[str] = []
        seen_ids: set[str] = set()
        items_by_ref = {f"memory:item:{row.item_id}": row for row in memory_items}
        for ref in context_refs:
            row = items_by_ref.get(ref)
            if row is None:
                unresolved.append(ref)
                continue
            row_id = str(getattr(row, "item_id", ""))
            if row_id and row_id not in seen_ids:
                selected.append(row)
                seen_ids.add(row_id)
        for row in memory_items:
            row_id = str(getattr(row, "item_id", ""))
            if row_id and row_id not in seen_ids:
                selected.append(row)
                seen_ids.add(row_id)
            if len(selected) >= limit:
                break
        return selected[:limit], unresolved

    def _detect_conflicts(
        self,
        *,
        memory_items: list[object],
        candidates: list[object],
    ) -> list[MemoryConflict]:
        conflicts: list[MemoryConflict] = []
        for candidate in candidates:
            candidate_summary = _normalize_key(getattr(candidate, "summary", ""))
            candidate_category = str(getattr(candidate, "category", "") or "").strip()
            candidate_facts = dict(getattr(candidate, "fact_json", {}) or {})
            for item in memory_items:
                if candidate_category != str(getattr(item, "category", "") or "").strip():
                    continue
                item_summary = _normalize_key(getattr(item, "summary", ""))
                if candidate_summary and candidate_summary != item_summary:
                    continue
                item_facts = dict(getattr(item, "fact_json", {}) or {})
                differing_fields = tuple(
                    key
                    for key in (
                        "normalized_text",
                        "recipient",
                        "channel",
                        "status",
                        "priority",
                        "due_at",
                        "stakeholder_ref",
                    )
                    if str(candidate_facts.get(key) or "").strip()
                    and str(item_facts.get(key) or "").strip()
                    and _normalize_key(candidate_facts.get(key)) != _normalize_key(item_facts.get(key))
                )
                if not differing_fields:
                    continue
                conflicts.append(
                    MemoryConflict(
                        conflict_id=f"candidate:{candidate.candidate_id}:item:{item.item_id}",
                        conflict_type="candidate_item_mismatch",
                        severity="high" if "due_at" in differing_fields or "status" in differing_fields else "medium",
                        summary=f"Pending memory candidate conflicts with promoted memory item for {candidate.summary}",
                        left_ref=f"memory:candidate:{candidate.candidate_id}",
                        right_ref=f"memory:item:{item.item_id}",
                        fields=differing_fields,
                    )
                )
        return conflicts

    def _build_promotion_signals(
        self,
        *,
        candidates: list[object],
        memory_items: list[object],
        conflicts: list[MemoryConflict],
    ) -> list[MemoryPromotionSignal]:
        ranked: list[MemoryPromotionSignal] = []
        for candidate in candidates:
            confidence = float(getattr(candidate, "confidence", 0.5) or 0.5)
            score = max(0.0, min(1.0, confidence))
            reasons: list[str] = []
            facts = dict(getattr(candidate, "fact_json", {}) or {})
            if getattr(candidate, "source_session_id", ""):
                score += 0.1
                reasons.append("has_session_provenance")
            if getattr(candidate, "source_step_id", ""):
                score += 0.1
                reasons.append("has_step_provenance")
            if facts:
                score += 0.1
                reasons.append("has_structured_facts")
            if facts.get("evidence_pack") or facts.get("evidence_object_id"):
                score += 0.15
                reasons.append("has_evidence_support")
            overlapping_item_ids = tuple(
                str(item.item_id)
                for item in memory_items
                if str(item.category or "") == str(getattr(candidate, "category", "") or "")
                and _normalize_key(item.summary) == _normalize_key(getattr(candidate, "summary", ""))
            )
            if overlapping_item_ids:
                score += 0.05
                reasons.append("matches_existing_context")
            conflict_refs = tuple(
                row.conflict_id for row in conflicts if row.left_ref == f"memory:candidate:{candidate.candidate_id}"
            )
            if conflict_refs:
                score -= 0.25
                reasons.append("requires_conflict_review")
            ranked.append(
                MemoryPromotionSignal(
                    candidate_id=str(candidate.candidate_id),
                    category=str(candidate.category),
                    summary=str(candidate.summary),
                    confidence=confidence,
                    score=max(0.0, min(1.0, round(score, 2))),
                    reasons=tuple(reasons),
                    overlapping_item_ids=overlapping_item_ids,
                    conflict_refs=conflict_refs,
                )
            )
        ranked.sort(key=lambda row: (-row.score, -row.confidence, row.candidate_id))
        return ranked

    def _build_commitment_risks(
        self,
        *,
        commitments: list[object],
        deadlines: list[object],
        decision_windows: list[object],
        follow_ups: list[object],
        interruption_budgets: list[object],
        authority_bindings: list[object],
    ) -> list[CommitmentRisk]:
        now = datetime.now(timezone.utc)
        risks: list[CommitmentRisk] = []
        for row in commitments:
            due_at = _parse_datetime(getattr(row, "due_at", None))
            reasons: list[str] = []
            severity = "low"
            if due_at is not None and due_at <= now:
                severity = "high"
                reasons.append("overdue")
            elif due_at is not None and due_at <= now + timedelta(hours=24):
                severity = "high"
                reasons.append("due_within_24h")
            elif due_at is not None and due_at <= now + timedelta(days=3):
                severity = "medium"
                reasons.append("due_within_72h")
            if str(getattr(row, "priority", "") or "").strip().lower() == "high":
                severity = "high" if severity != "high" else severity
                reasons.append("high_priority")
            if reasons:
                risks.append(
                    CommitmentRisk(
                        risk_id=f"commitment:{row.commitment_id}",
                        risk_type="commitment_deadline",
                        severity=severity,
                        reference_kind="commitment",
                        reference_id=str(row.commitment_id),
                        title=str(row.title),
                        due_at=str(getattr(row, "due_at", None) or "") or None,
                        summary=f"Commitment '{row.title}' needs attention.",
                        reasons=tuple(reasons),
                    )
                )
        for row in follow_ups:
            due_at = _parse_datetime(getattr(row, "due_at", None))
            if due_at is None or due_at > now + timedelta(days=2):
                continue
            severity = "high" if due_at <= now else "medium"
            risks.append(
                CommitmentRisk(
                    risk_id=f"follow_up:{row.follow_up_id}",
                    risk_type="follow_up_due",
                    severity=severity,
                    reference_kind="follow_up",
                    reference_id=str(row.follow_up_id),
                    title=str(row.topic),
                    due_at=str(row.due_at or "") or None,
                    summary=f"Follow-up '{row.topic}' is due soon.",
                    reasons=("follow_up_due",),
                )
            )
        for row in deadlines:
            end_at = _parse_datetime(getattr(row, "end_at", None))
            if end_at is None or end_at > now + timedelta(days=3):
                continue
            risks.append(
                CommitmentRisk(
                    risk_id=f"deadline:{row.window_id}",
                    risk_type="deadline_window",
                    severity="high" if end_at <= now + timedelta(hours=24) else "medium",
                    reference_kind="deadline_window",
                    reference_id=str(row.window_id),
                    title=str(row.title),
                    due_at=str(row.end_at or "") or None,
                    summary=f"Deadline window '{row.title}' is closing soon.",
                    reasons=("deadline_window_closing",),
                )
            )
        binding_levels = {str(row.approval_level or "").strip().lower() for row in authority_bindings if str(row.status or "") == "active"}
        for row in decision_windows:
            closes_at = _parse_datetime(getattr(row, "closes_at", None))
            if closes_at is None or closes_at > now + timedelta(days=2):
                continue
            reasons = ["decision_window_closing"]
            severity = "high" if closes_at <= now + timedelta(hours=24) else "medium"
            required = str(getattr(row, "authority_required", "") or "").strip().lower()
            if required and required not in {"", "none"} and required not in binding_levels:
                reasons.append("authority_binding_missing")
                severity = "high"
            risks.append(
                CommitmentRisk(
                    risk_id=f"decision_window:{row.decision_window_id}",
                    risk_type="decision_window",
                    severity=severity,
                    reference_kind="decision_window",
                    reference_id=str(row.decision_window_id),
                    title=str(row.title),
                    due_at=str(row.closes_at or "") or None,
                    summary=f"Decision window '{row.title}' is nearing closure.",
                    reasons=tuple(reasons),
                )
            )
        for row in interruption_budgets:
            budget_minutes = int(getattr(row, "budget_minutes", 0) or 0)
            used_minutes = int(getattr(row, "used_minutes", 0) or 0)
            if budget_minutes <= 0 or used_minutes < budget_minutes:
                continue
            risks.append(
                CommitmentRisk(
                    risk_id=f"interruption_budget:{row.budget_id}",
                    risk_type="interruption_budget_exhausted",
                    severity="medium",
                    reference_kind="interruption_budget",
                    reference_id=str(row.budget_id),
                    title=str(row.scope),
                    due_at=str(getattr(row, "reset_at", None) or "") or None,
                    summary=f"Interruption budget for '{row.scope}' is exhausted.",
                    reasons=("budget_exhausted",),
                )
            )
        risks.sort(key=lambda row: ({"high": 0, "medium": 1, "low": 2}.get(row.severity, 3), row.title))
        return risks
