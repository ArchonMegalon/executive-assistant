from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Protocol

from app.domain.models import ApprovalDecision, ApprovalRequest, now_utc_iso


def _expiry(minutes: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=max(1, int(minutes)))).isoformat()


def _is_expired(expires_at: str | None) -> bool:
    raw = str(expires_at or "").strip()
    if not raw:
        return False
    try:
        value = datetime.fromisoformat(raw)
    except ValueError:
        return False
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value <= datetime.now(timezone.utc)


class ApprovalRepository(Protocol):
    def create_request(
        self,
        session_id: str,
        step_id: str,
        reason: str,
        requested_action_json: dict[str, object] | None = None,
        *,
        expires_at: str | None = None,
    ) -> ApprovalRequest:
        ...

    def list_pending(self, limit: int = 50) -> list[ApprovalRequest]:
        ...

    def get_request(self, approval_id: str) -> ApprovalRequest | None:
        ...

    def list_history(self, limit: int = 50, session_id: str | None = None) -> list[ApprovalDecision]:
        ...

    def decide(
        self,
        approval_id: str,
        *,
        decision: str,
        decided_by: str,
        reason: str,
    ) -> tuple[ApprovalRequest, ApprovalDecision] | None:
        ...

    def expire(
        self,
        approval_id: str,
        *,
        decided_by: str,
        reason: str,
    ) -> tuple[ApprovalRequest, ApprovalDecision] | None:
        ...


class InMemoryApprovalRepository:
    def __init__(self, default_ttl_minutes: int = 120) -> None:
        self._default_ttl_minutes = max(1, int(default_ttl_minutes))
        self._requests: Dict[str, ApprovalRequest] = {}
        self._request_order: List[str] = []
        self._decisions: Dict[str, ApprovalDecision] = {}
        self._decision_order: List[str] = []

    def _append_decision(
        self,
        request: ApprovalRequest,
        *,
        decision: str,
        decided_by: str,
        reason: str,
    ) -> ApprovalDecision:
        decision_row = ApprovalDecision(
            decision_id=str(uuid.uuid4()),
            approval_id=request.approval_id,
            session_id=request.session_id,
            step_id=request.step_id,
            decision=str(decision or ""),
            decided_by=str(decided_by or "unknown"),
            reason=str(reason or ""),
            created_at=now_utc_iso(),
        )
        self._decisions[decision_row.decision_id] = decision_row
        self._decision_order.append(decision_row.decision_id)
        return decision_row

    def _auto_expire_pending(self) -> None:
        pending_ids = [i for i in self._request_order if i in self._requests and self._requests[i].status == "pending"]
        for aid in pending_ids:
            found = self._requests.get(aid)
            if not found or not _is_expired(found.expires_at):
                continue
            updated = replace(found, status="expired", updated_at=now_utc_iso())
            self._requests[updated.approval_id] = updated
            self._append_decision(
                updated,
                decision="expired",
                decided_by="system",
                reason="approval_ttl_expired",
            )

    def create_request(
        self,
        session_id: str,
        step_id: str,
        reason: str,
        requested_action_json: dict[str, object] | None = None,
        *,
        expires_at: str | None = None,
    ) -> ApprovalRequest:
        now = now_utc_iso()
        row = ApprovalRequest(
            approval_id=str(uuid.uuid4()),
            session_id=str(session_id or ""),
            step_id=str(step_id or ""),
            reason=str(reason or "approval_required"),
            requested_action_json=dict(requested_action_json or {}),
            status="pending",
            expires_at=str(expires_at or _expiry(self._default_ttl_minutes)),
            created_at=now,
            updated_at=now,
        )
        self._requests[row.approval_id] = row
        self._request_order.append(row.approval_id)
        return row

    def list_pending(self, limit: int = 50) -> list[ApprovalRequest]:
        self._auto_expire_pending()
        n = max(1, min(500, int(limit or 50)))
        ids = list(reversed(self._request_order))
        rows = [self._requests[i] for i in ids if i in self._requests and self._requests[i].status == "pending"]
        return rows[:n]

    def get_request(self, approval_id: str) -> ApprovalRequest | None:
        self._auto_expire_pending()
        return self._requests.get(str(approval_id or ""))

    def list_history(self, limit: int = 50, session_id: str | None = None) -> list[ApprovalDecision]:
        n = max(1, min(500, int(limit or 50)))
        sid = str(session_id or "").strip()
        ids = list(reversed(self._decision_order))
        rows = [self._decisions[i] for i in ids if i in self._decisions]
        if sid:
            rows = [r for r in rows if r.session_id == sid]
        return rows[:n]

    def decide(
        self,
        approval_id: str,
        *,
        decision: str,
        decided_by: str,
        reason: str,
    ) -> tuple[ApprovalRequest, ApprovalDecision] | None:
        self._auto_expire_pending()
        aid = str(approval_id or "")
        found = self._requests.get(aid)
        if not found or found.status != "pending":
            return None
        normalized_decision = str(decision or "").strip().lower()
        if normalized_decision in {"approve", "approved"}:
            status = "approved"
        elif normalized_decision in {"expire", "expired"}:
            status = "expired"
        else:
            status = "denied"
        updated = replace(found, status=status, updated_at=now_utc_iso())
        self._requests[updated.approval_id] = updated
        decision_row = self._append_decision(
            updated,
            decision=status,
            decided_by=decided_by,
            reason=reason,
        )
        return updated, decision_row

    def expire(
        self,
        approval_id: str,
        *,
        decided_by: str,
        reason: str,
    ) -> tuple[ApprovalRequest, ApprovalDecision] | None:
        return self.decide(
            approval_id,
            decision="expired",
            decided_by=decided_by,
            reason=reason,
        )
