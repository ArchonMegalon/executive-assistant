from __future__ import annotations

import uuid
from typing import Dict, List, Protocol

from app.domain.models import Stakeholder, now_utc_iso


class StakeholderRepository(Protocol):
    def upsert_stakeholder(
        self,
        *,
        principal_id: str,
        display_name: str,
        channel_ref: str = "",
        authority_level: str = "manager",
        importance: str = "medium",
        response_cadence: str = "normal",
        tone_pref: str = "neutral",
        sensitivity: str = "internal",
        escalation_policy: str = "none",
        open_loops_json: dict[str, object] | None = None,
        friction_points_json: dict[str, object] | None = None,
        last_interaction_at: str | None = None,
        status: str = "active",
        notes: str = "",
        stakeholder_id: str | None = None,
    ) -> Stakeholder:
        ...

    def get(self, stakeholder_id: str) -> Stakeholder | None:
        ...

    def list_stakeholders(
        self,
        *,
        principal_id: str,
        limit: int = 100,
        status: str | None = None,
    ) -> list[Stakeholder]:
        ...


def _normalize_status(value: str) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"active", "archived", "inactive"}:
        return raw
    return "active"


class InMemoryStakeholderRepository:
    def __init__(self) -> None:
        self._rows: Dict[str, Stakeholder] = {}
        self._order: List[str] = []

    def upsert_stakeholder(
        self,
        *,
        principal_id: str,
        display_name: str,
        channel_ref: str = "",
        authority_level: str = "manager",
        importance: str = "medium",
        response_cadence: str = "normal",
        tone_pref: str = "neutral",
        sensitivity: str = "internal",
        escalation_policy: str = "none",
        open_loops_json: dict[str, object] | None = None,
        friction_points_json: dict[str, object] | None = None,
        last_interaction_at: str | None = None,
        status: str = "active",
        notes: str = "",
        stakeholder_id: str | None = None,
    ) -> Stakeholder:
        now = now_utc_iso()
        key = str(stakeholder_id or "").strip()
        existing = self._rows.get(key) if key else None
        if existing and existing.principal_id != str(principal_id or "").strip():
            existing = None
        if existing:
            updated = Stakeholder(
                stakeholder_id=existing.stakeholder_id,
                principal_id=existing.principal_id,
                display_name=str(display_name or existing.display_name).strip() or existing.display_name,
                channel_ref=str(channel_ref or existing.channel_ref).strip(),
                authority_level=str(authority_level or existing.authority_level).strip() or existing.authority_level,
                importance=str(importance or existing.importance).strip() or existing.importance,
                response_cadence=str(response_cadence or existing.response_cadence).strip() or existing.response_cadence,
                tone_pref=str(tone_pref or existing.tone_pref).strip() or existing.tone_pref,
                sensitivity=str(sensitivity or existing.sensitivity).strip() or existing.sensitivity,
                escalation_policy=str(escalation_policy or existing.escalation_policy).strip() or existing.escalation_policy,
                open_loops_json=dict(open_loops_json or {}),
                friction_points_json=dict(friction_points_json or {}),
                last_interaction_at=str(last_interaction_at or "").strip() or None,
                status=_normalize_status(status),
                notes=str(notes or "").strip(),
                created_at=existing.created_at,
                updated_at=now,
            )
            self._rows[existing.stakeholder_id] = updated
            return updated
        row = Stakeholder(
            stakeholder_id=key or str(uuid.uuid4()),
            principal_id=str(principal_id or "").strip(),
            display_name=str(display_name or "").strip(),
            channel_ref=str(channel_ref or "").strip(),
            authority_level=str(authority_level or "manager").strip() or "manager",
            importance=str(importance or "medium").strip() or "medium",
            response_cadence=str(response_cadence or "normal").strip() or "normal",
            tone_pref=str(tone_pref or "neutral").strip() or "neutral",
            sensitivity=str(sensitivity or "internal").strip() or "internal",
            escalation_policy=str(escalation_policy or "none").strip() or "none",
            open_loops_json=dict(open_loops_json or {}),
            friction_points_json=dict(friction_points_json or {}),
            last_interaction_at=str(last_interaction_at or "").strip() or None,
            status=_normalize_status(status),
            notes=str(notes or "").strip(),
            created_at=now,
            updated_at=now,
        )
        self._rows[row.stakeholder_id] = row
        self._order.append(row.stakeholder_id)
        return row

    def get(self, stakeholder_id: str) -> Stakeholder | None:
        return self._rows.get(str(stakeholder_id or ""))

    def list_stakeholders(
        self,
        *,
        principal_id: str,
        limit: int = 100,
        status: str | None = None,
    ) -> list[Stakeholder]:
        n = max(1, min(500, int(limit or 100)))
        principal = str(principal_id or "").strip()
        status_filter = str(status or "").strip().lower()
        rows = [self._rows[sid] for sid in reversed(self._order) if sid in self._rows]
        rows = [row for row in rows if row.principal_id == principal]
        if status_filter:
            rows = [row for row in rows if row.status == status_filter]
        return rows[:n]
