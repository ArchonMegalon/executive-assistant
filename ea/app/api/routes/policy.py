from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.services.orchestrator import build_default_orchestrator

router = APIRouter(prefix="/v1/policy", tags=["policy"])
_orchestrator = build_default_orchestrator()


class PolicyDecisionOut(BaseModel):
    decision_id: str
    session_id: str
    allow: bool
    requires_approval: bool
    reason: str
    retention_policy: str
    memory_write_allowed: bool
    created_at: str


@router.get("/decisions/recent")
def list_recent_policy_decisions(
    limit: int = Query(default=50, ge=1, le=500),
    session_id: str | None = Query(default=None),
) -> list[PolicyDecisionOut]:
    rows = _orchestrator.list_policy_decisions(limit=limit, session_id=session_id)
    return [
        PolicyDecisionOut(
            decision_id=r.decision_id,
            session_id=r.session_id,
            allow=r.allow,
            requires_approval=r.requires_approval,
            reason=r.reason,
            retention_policy=r.retention_policy,
            memory_write_allowed=r.memory_write_allowed,
            created_at=r.created_at,
        )
        for r in rows
    ]
