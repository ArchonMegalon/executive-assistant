from __future__ import annotations

import difflib
from dataclasses import dataclass

from app.domain.models import MemoryCandidate
from app.services.memory_runtime import MemoryRuntimeService


@dataclass(frozen=True)
class ReflectionRequest:
    principal_id: str
    source_session_id: str
    source_step_id: str
    human_task_id: str
    original_text: str
    edited_text: str
    context_refs: tuple[str, ...] = ()
    stakeholder_hint: str = ""


def edit_distance_ratio(a: str, b: str) -> float:
    left = str(a or "")
    right = str(b or "")
    if not left and not right:
        return 0.0
    return 1.0 - difflib.SequenceMatcher(a=left, b=right).ratio()


class StyleReflectionService:
    def __init__(self, memory_runtime: MemoryRuntimeService, *, minimum_delta: float = 0.10) -> None:
        self._memory_runtime = memory_runtime
        self._minimum_delta = max(0.01, float(minimum_delta or 0.10))

    def maybe_stage_reflection(self, request: ReflectionRequest) -> MemoryCandidate | None:
        original_text = str(request.original_text or "").strip()
        edited_text = str(request.edited_text or "").strip()
        if not original_text or not edited_text:
            return None
        delta = edit_distance_ratio(original_text, edited_text)
        if delta < self._minimum_delta:
            return None
        heuristic = self._heuristic(original_text=original_text, edited_text=edited_text)
        summary = self._summary_for_heuristic(heuristic, stakeholder_hint=request.stakeholder_hint)
        fact_json = {
            "source_kind": "human_edit_reflection",
            "human_task_id": request.human_task_id,
            "delta_ratio": round(delta, 4),
            "heuristic": heuristic,
            "original_text": original_text,
            "edited_text": edited_text,
            "context_refs": list(request.context_refs),
            "stakeholder_hint": str(request.stakeholder_hint or "").strip(),
        }
        return self._memory_runtime.stage_candidate(
            principal_id=request.principal_id,
            category="communication_policy",
            summary=summary,
            fact_json=fact_json,
            source_session_id=request.source_session_id,
            source_step_id=request.source_step_id,
            confidence=min(0.95, max(0.55, delta)),
            sensitivity="internal",
        )

    def _heuristic(self, *, original_text: str, edited_text: str) -> str:
        original_bullets = self._bullet_count(original_text)
        edited_bullets = self._bullet_count(edited_text)
        if edited_bullets >= 2 and edited_bullets > original_bullets:
            return "prefer_bullets"
        if len(edited_text) <= max(40, int(len(original_text) * 0.8)):
            return "prefer_shorter_copy"
        if self._heading_count(edited_text) > self._heading_count(original_text):
            return "prefer_structured_sections"
        return "preserve_human_revision_pattern"

    def _summary_for_heuristic(self, heuristic: str, *, stakeholder_hint: str) -> str:
        hint = str(stakeholder_hint or "").strip()
        if heuristic == "prefer_bullets":
            summary = "Prefer concise bullet summaries over dense paragraphs when humans revise the draft."
        elif heuristic == "prefer_shorter_copy":
            summary = "Prefer tighter, shorter phrasing when a human significantly compresses the draft."
        elif heuristic == "prefer_structured_sections":
            summary = "Prefer explicit sections and headings when a human restructures the draft for clarity."
        else:
            summary = "Preserve the human-edited phrasing and tone pattern for similar future output."
        if hint:
            return f"{summary} Stakeholder hint: {hint}."
        return summary

    def _bullet_count(self, text: str) -> int:
        count = 0
        for raw_line in str(text or "").splitlines():
            line = raw_line.strip()
            if line.startswith(("- ", "* ", "1. ", "2. ", "3. ")):
                count += 1
        return count

    def _heading_count(self, text: str) -> int:
        count = 0
        for raw_line in str(text or "").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("#") or line.endswith(":"):
                count += 1
        return count
