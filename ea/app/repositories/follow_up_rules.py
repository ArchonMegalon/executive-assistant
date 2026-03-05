from __future__ import annotations

import uuid
from typing import Dict, List, Protocol

from app.domain.models import FollowUpRule, now_utc_iso


class FollowUpRuleRepository(Protocol):
    def upsert_rule(
        self,
        *,
        principal_id: str,
        name: str,
        trigger_kind: str,
        channel_scope: tuple[str, ...] = (),
        delay_minutes: int = 60,
        max_attempts: int = 3,
        escalation_policy: str = "notify_exec",
        conditions_json: dict[str, object] | None = None,
        action_json: dict[str, object] | None = None,
        status: str = "active",
        notes: str = "",
        rule_id: str | None = None,
    ) -> FollowUpRule:
        ...

    def get(self, rule_id: str) -> FollowUpRule | None:
        ...

    def list_rules(
        self,
        *,
        principal_id: str,
        limit: int = 100,
        status: str | None = None,
    ) -> list[FollowUpRule]:
        ...


def _normalize_status(value: str) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"active", "paused", "archived"}:
        return raw
    return "active"


class InMemoryFollowUpRuleRepository:
    def __init__(self) -> None:
        self._rows: Dict[str, FollowUpRule] = {}
        self._order: List[str] = []

    def upsert_rule(
        self,
        *,
        principal_id: str,
        name: str,
        trigger_kind: str,
        channel_scope: tuple[str, ...] = (),
        delay_minutes: int = 60,
        max_attempts: int = 3,
        escalation_policy: str = "notify_exec",
        conditions_json: dict[str, object] | None = None,
        action_json: dict[str, object] | None = None,
        status: str = "active",
        notes: str = "",
        rule_id: str | None = None,
    ) -> FollowUpRule:
        now = now_utc_iso()
        key = str(rule_id or "").strip()
        existing = self._rows.get(key) if key else None
        if existing and existing.principal_id != str(principal_id or "").strip():
            existing = None
        if existing:
            updated = FollowUpRule(
                rule_id=existing.rule_id,
                principal_id=existing.principal_id,
                name=str(name or existing.name).strip() or existing.name,
                trigger_kind=str(trigger_kind or existing.trigger_kind).strip() or existing.trigger_kind,
                channel_scope=tuple(str(v).strip() for v in (channel_scope or ()) if str(v).strip()),
                delay_minutes=max(0, int(delay_minutes if delay_minutes is not None else existing.delay_minutes)),
                max_attempts=max(1, int(max_attempts if max_attempts is not None else existing.max_attempts)),
                escalation_policy=str(escalation_policy or existing.escalation_policy).strip()
                or existing.escalation_policy,
                conditions_json=dict(conditions_json or {}),
                action_json=dict(action_json or {}),
                status=_normalize_status(status),
                notes=str(notes or "").strip(),
                created_at=existing.created_at,
                updated_at=now,
            )
            self._rows[existing.rule_id] = updated
            return updated
        row = FollowUpRule(
            rule_id=key or str(uuid.uuid4()),
            principal_id=str(principal_id or "").strip(),
            name=str(name or "").strip(),
            trigger_kind=str(trigger_kind or "").strip(),
            channel_scope=tuple(str(v).strip() for v in (channel_scope or ()) if str(v).strip()),
            delay_minutes=max(0, int(delay_minutes or 0)),
            max_attempts=max(1, int(max_attempts or 1)),
            escalation_policy=str(escalation_policy or "notify_exec").strip() or "notify_exec",
            conditions_json=dict(conditions_json or {}),
            action_json=dict(action_json or {}),
            status=_normalize_status(status),
            notes=str(notes or "").strip(),
            created_at=now,
            updated_at=now,
        )
        self._rows[row.rule_id] = row
        self._order.append(row.rule_id)
        return row

    def get(self, rule_id: str) -> FollowUpRule | None:
        return self._rows.get(str(rule_id or ""))

    def list_rules(
        self,
        *,
        principal_id: str,
        limit: int = 100,
        status: str | None = None,
    ) -> list[FollowUpRule]:
        n = max(1, min(500, int(limit or 100)))
        principal = str(principal_id or "").strip()
        status_filter = str(status or "").strip().lower()
        rows = [self._rows[rid] for rid in reversed(self._order) if rid in self._rows]
        rows = [row for row in rows if row.principal_id == principal]
        if status_filter:
            rows = [row for row in rows if row.status == status_filter]
        return rows[:n]
