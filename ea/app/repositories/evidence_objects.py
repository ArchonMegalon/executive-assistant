from __future__ import annotations

from typing import Dict, Protocol

from app.domain.models import (
    Artifact,
    EvidenceObject,
    evidence_citation_handle,
    evidence_object_id,
    normalize_artifact,
    now_utc_iso,
)


class EvidenceObjectRepository(Protocol):
    def upsert_from_artifact(self, artifact: Artifact) -> EvidenceObject | None:
        ...

    def get(self, evidence_id: str) -> EvidenceObject | None:
        ...

    def get_by_artifact(self, artifact_id: str) -> EvidenceObject | None:
        ...

    def list_objects(
        self,
        *,
        limit: int = 100,
        principal_id: str | None = None,
        artifact_id: str | None = None,
        session_id: str | None = None,
        evidence_ref: str | None = None,
    ) -> list[EvidenceObject]:
        ...


def clamp_evidence_confidence(value: object) -> float:
    try:
        numeric = float(value if value is not None else 0.5)
    except (TypeError, ValueError):
        numeric = 0.5
    return min(max(numeric, 0.0), 1.0)


def normalize_evidence_strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    ordered: list[str] = []
    seen: set[str] = set()
    for entry in value:
        normalized = str(entry or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return tuple(ordered)


def evidence_object_from_artifact(
    artifact: Artifact,
    *,
    created_at: str | None = None,
) -> EvidenceObject | None:
    normalized = normalize_artifact(artifact)
    structured = dict(normalized.structured_output_json or {})
    if str(structured.get("format") or "").strip() != "evidence_pack":
        return None
    stamp = now_utc_iso()
    evidence_id = evidence_object_id(normalized.artifact_id)
    return EvidenceObject(
        evidence_id=evidence_id,
        principal_id=normalized.principal_id,
        artifact_id=normalized.artifact_id,
        execution_session_id=normalized.execution_session_id,
        artifact_kind=normalized.kind,
        summary=str(normalized.preview_text or "").strip(),
        claims=normalize_evidence_strings(structured.get("claims")),
        evidence_refs=normalize_evidence_strings(structured.get("evidence_refs")),
        open_questions=normalize_evidence_strings(structured.get("open_questions")),
        confidence=clamp_evidence_confidence(structured.get("confidence")),
        citation_handle=evidence_citation_handle(evidence_id),
        created_at=str(created_at or stamp),
        updated_at=stamp,
    )


class InMemoryEvidenceObjectRepository:
    def __init__(self) -> None:
        self._rows: Dict[str, EvidenceObject] = {}
        self._artifact_index: Dict[str, str] = {}
        self._order: list[str] = []

    def upsert_from_artifact(self, artifact: Artifact) -> EvidenceObject | None:
        existing = self.get_by_artifact(artifact.artifact_id)
        row = evidence_object_from_artifact(artifact, created_at=existing.created_at if existing is not None else None)
        if row is None:
            return None
        self._rows[row.evidence_id] = row
        self._artifact_index[row.artifact_id] = row.evidence_id
        if row.evidence_id not in self._order:
            self._order.append(row.evidence_id)
        return row

    def get(self, evidence_id: str) -> EvidenceObject | None:
        return self._rows.get(str(evidence_id or "").strip())

    def get_by_artifact(self, artifact_id: str) -> EvidenceObject | None:
        evidence_id = self._artifact_index.get(str(artifact_id or "").strip())
        if not evidence_id:
            return None
        return self._rows.get(evidence_id)

    def list_objects(
        self,
        *,
        limit: int = 100,
        principal_id: str | None = None,
        artifact_id: str | None = None,
        session_id: str | None = None,
        evidence_ref: str | None = None,
    ) -> list[EvidenceObject]:
        n = max(1, min(500, int(limit or 100)))
        principal_filter = str(principal_id or "").strip()
        artifact_filter = str(artifact_id or "").strip()
        session_filter = str(session_id or "").strip()
        evidence_ref_filter = str(evidence_ref or "").strip()
        rows = [self._rows[evidence_id] for evidence_id in reversed(self._order) if evidence_id in self._rows]
        if principal_filter:
            rows = [row for row in rows if row.principal_id == principal_filter]
        if artifact_filter:
            rows = [row for row in rows if row.artifact_id == artifact_filter]
        if session_filter:
            rows = [row for row in rows if row.execution_session_id == session_filter]
        if evidence_ref_filter:
            rows = [row for row in rows if evidence_ref_filter in row.evidence_refs]
        return rows[:n]
