from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from app.domain.models import (
    ApprovalDecision,
    ApprovalRequest,
    Artifact,
    ExecutionEvent,
    ExecutionSession,
    ExecutionStep,
    IntentSpecV3,
    RewriteRequest,
    RunCost,
    ToolReceipt,
)
from app.repositories.approvals import ApprovalRepository, InMemoryApprovalRepository
from app.repositories.approvals_postgres import PostgresApprovalRepository
from app.repositories.artifacts import ArtifactRepository, InMemoryArtifactRepository
from app.repositories.artifacts_postgres import PostgresArtifactRepository
from app.repositories.ledger import ExecutionLedgerRepository, InMemoryExecutionLedgerRepository
from app.repositories.ledger_postgres import PostgresExecutionLedgerRepository
from app.repositories.policy_decisions import InMemoryPolicyDecisionRepository, PolicyDecisionRepository
from app.repositories.policy_decisions_postgres import PostgresPolicyDecisionRepository
from app.settings import Settings, get_settings
from app.services.policy import PolicyDecisionService, PolicyDeniedError


@dataclass(frozen=True)
class ExecutionSessionSnapshot:
    session: ExecutionSession
    events: list[ExecutionEvent]
    steps: list[ExecutionStep]
    receipts: list[ToolReceipt]
    artifacts: list[Artifact]
    run_costs: list[RunCost]


class RewriteOrchestrator:
    def __init__(
        self,
        artifacts: ArtifactRepository | None = None,
        ledger: ExecutionLedgerRepository | None = None,
        policy_repo: PolicyDecisionRepository | None = None,
        approvals: ApprovalRepository | None = None,
        policy: PolicyDecisionService | None = None,
    ) -> None:
        self._artifacts = artifacts or InMemoryArtifactRepository()
        self._ledger = ledger or InMemoryExecutionLedgerRepository()
        self._policy_repo = policy_repo or InMemoryPolicyDecisionRepository()
        self._approvals = approvals or InMemoryApprovalRepository()
        self._policy = policy or PolicyDecisionService()

    def build_artifact(self, req: RewriteRequest) -> Artifact:
        intent = IntentSpecV3(
            principal_id="local-user",
            goal="rewrite supplied text into an artifact",
            task_type="rewrite",
            deliverable_type="rewrite_note",
            risk_class="low",
            approval_class="none",
            budget_class="low",
            allowed_tools=("rewrite_store",),
            desired_artifact="rewrite_note",
            memory_write_policy="reviewed_only",
        )
        session = self._ledger.start_session(intent)
        correlation_id = str(uuid.uuid4())
        self._ledger.append_event(
            session.session_id,
            "intent_compiled",
            {"task_type": intent.task_type, "risk_class": intent.risk_class},
        )
        normalized_text = str(req.text or "").strip()
        rewrite_step = self._ledger.start_step(
            session.session_id,
            "rewrite_flow",
            input_json={"text_length": len(normalized_text)},
            correlation_id=correlation_id,
            causation_id="rewrite_request",
            actor_type="assistant",
            actor_id="orchestrator",
        )
        policy_decision = self._policy.evaluate_rewrite(intent, normalized_text)
        self._policy_repo.append(session.session_id, policy_decision)
        self._ledger.append_event(
            session.session_id,
            "policy_decision",
            {
                "allow": policy_decision.allow,
                "requires_approval": policy_decision.requires_approval,
                "reason": policy_decision.reason,
                "retention_policy": policy_decision.retention_policy,
            },
        )
        if not policy_decision.allow:
            self._ledger.update_step(
                rewrite_step.step_id,
                state="blocked",
                error_json={"reason": policy_decision.reason},
            )
            self._ledger.complete_session(session.session_id, status="blocked")
            self._ledger.append_event(
                session.session_id,
                "session_blocked",
                {"reason": policy_decision.reason},
            )
            raise PolicyDeniedError(policy_decision.reason)
        if policy_decision.requires_approval:
            approval_request = self._approvals.create_request(
                session.session_id,
                rewrite_step.step_id,
                reason="approval_required",
                requested_action_json={
                    "action": "artifact.save",
                    "artifact_kind": "rewrite_note",
                    "text_length": len(normalized_text),
                },
            )
            self._ledger.update_step(
                rewrite_step.step_id,
                state="waiting_approval",
                error_json={"reason": "approval_required", "approval_id": approval_request.approval_id},
            )
            self._ledger.complete_session(session.session_id, status="awaiting_approval")
            self._ledger.append_event(
                session.session_id,
                "session_paused_for_approval",
                {"reason": "approval_required", "approval_id": approval_request.approval_id},
            )
            raise PolicyDeniedError("approval_required")
        self._ledger.append_event(
            session.session_id,
            "input_validated",
            {"text_length": len(normalized_text)},
        )
        artifact = Artifact(
            artifact_id=str(uuid.uuid4()),
            kind="rewrite_note",
            content=normalized_text,
            execution_session_id=session.session_id,
        )
        self._artifacts.save(artifact)
        self._ledger.append_tool_receipt(
            session.session_id,
            rewrite_step.step_id,
            tool_name="artifact_repository",
            action_kind="artifact.save",
            target_ref=artifact.artifact_id,
            receipt_json={"artifact_kind": artifact.kind},
        )
        self._ledger.append_run_cost(
            session.session_id,
            model_name="none",
            tokens_in=0,
            tokens_out=0,
            cost_usd=0.0,
        )
        self._ledger.update_step(
            rewrite_step.step_id,
            state="completed",
            output_json={"artifact_id": artifact.artifact_id, "artifact_kind": artifact.kind},
        )
        self._ledger.append_event(
            session.session_id,
            "artifact_persisted",
            {"artifact_id": artifact.artifact_id, "artifact_kind": artifact.kind},
        )
        self._ledger.complete_session(session.session_id, status="completed")
        self._ledger.append_event(session.session_id, "session_completed", {"status": "completed"})
        return artifact

    def fetch_artifact(self, artifact_id: str) -> Artifact | None:
        return self._artifacts.get(artifact_id)

    def fetch_session(self, session_id: str) -> ExecutionSessionSnapshot | None:
        session = self._ledger.get_session(session_id)
        if not session:
            return None
        sid = session.session_id
        return ExecutionSessionSnapshot(
            session=session,
            events=self._ledger.events_for(sid),
            steps=self._ledger.steps_for(sid),
            receipts=self._ledger.receipts_for(sid),
            artifacts=self._artifacts.list_for_session(sid),
            run_costs=self._ledger.run_costs_for(sid),
        )

    def list_policy_decisions(self, limit: int = 50, session_id: str | None = None):
        return self._policy_repo.list_recent(limit=limit, session_id=session_id)

    def list_pending_approvals(self, limit: int = 50) -> list[ApprovalRequest]:
        return self._approvals.list_pending(limit=limit)

    def list_approval_history(self, limit: int = 50, session_id: str | None = None) -> list[ApprovalDecision]:
        return self._approvals.list_history(limit=limit, session_id=session_id)

    def decide_approval(
        self,
        approval_id: str,
        *,
        decision: str,
        decided_by: str,
        reason: str,
    ) -> tuple[ApprovalRequest, ApprovalDecision] | None:
        found = self._approvals.decide(
            approval_id,
            decision=decision,
            decided_by=decided_by,
            reason=reason,
        )
        if not found:
            return None
        request, decision_row = found
        self._ledger.append_event(
            request.session_id,
            "approval_decided",
            {
                "approval_id": request.approval_id,
                "step_id": request.step_id,
                "decision": decision_row.decision,
                "decided_by": decision_row.decided_by,
                "reason": decision_row.reason,
            },
        )
        if decision_row.decision == "approved":
            self._ledger.update_step(
                request.step_id,
                state="queued",
                output_json={"approval_id": request.approval_id, "decision": "approved"},
                error_json={},
            )
            self._ledger.complete_session(request.session_id, status="approved_pending_execution")
        else:
            self._ledger.update_step(
                request.step_id,
                state="blocked",
                error_json={"approval_id": request.approval_id, "decision": decision_row.decision},
            )
            self._ledger.complete_session(request.session_id, status="blocked")
            self._ledger.append_event(
                request.session_id,
                "session_blocked",
                {"reason": f"approval_{decision_row.decision}", "approval_id": request.approval_id},
            )
        return request, decision_row

    def expire_approval(
        self,
        approval_id: str,
        *,
        decided_by: str,
        reason: str,
    ) -> tuple[ApprovalRequest, ApprovalDecision] | None:
        return self.decide_approval(
            approval_id,
            decision="expired",
            decided_by=decided_by,
            reason=reason,
        )


def _backend_mode(settings: Settings) -> str:
    return str(settings.storage.backend or "auto").strip().lower()


def build_execution_ledger(settings: Settings) -> ExecutionLedgerRepository:
    backend = _backend_mode(settings)
    log = logging.getLogger("ea.ledger")
    if backend == "memory":
        return InMemoryExecutionLedgerRepository()
    if backend == "postgres":
        if not settings.database_url:
            raise RuntimeError("EA_STORAGE_BACKEND=postgres requires DATABASE_URL")
        return PostgresExecutionLedgerRepository(settings.database_url)

    if settings.database_url:
        try:
            return PostgresExecutionLedgerRepository(settings.database_url)
        except Exception as exc:
            log.warning("postgres ledger unavailable in auto mode; falling back to memory: %s", exc)
    return InMemoryExecutionLedgerRepository()


def build_policy_repo(settings: Settings) -> PolicyDecisionRepository:
    backend = _backend_mode(settings)
    log = logging.getLogger("ea.policy_repo")
    if backend == "memory":
        return InMemoryPolicyDecisionRepository()
    if backend == "postgres":
        if not settings.database_url:
            raise RuntimeError("EA_STORAGE_BACKEND=postgres requires DATABASE_URL")
        return PostgresPolicyDecisionRepository(settings.database_url)
    if settings.database_url:
        try:
            return PostgresPolicyDecisionRepository(settings.database_url)
        except Exception as exc:
            log.warning("postgres policy backend unavailable in auto mode; falling back to memory: %s", exc)
    return InMemoryPolicyDecisionRepository()


def build_approval_repo(settings: Settings) -> ApprovalRepository:
    backend = _backend_mode(settings)
    log = logging.getLogger("ea.approvals")
    if backend == "memory":
        return InMemoryApprovalRepository(default_ttl_minutes=settings.policy.approval_ttl_minutes)
    if backend == "postgres":
        if not settings.database_url:
            raise RuntimeError("EA_STORAGE_BACKEND=postgres requires DATABASE_URL")
        return PostgresApprovalRepository(
            settings.database_url,
            default_ttl_minutes=settings.policy.approval_ttl_minutes,
        )
    if settings.database_url:
        try:
            return PostgresApprovalRepository(
                settings.database_url,
                default_ttl_minutes=settings.policy.approval_ttl_minutes,
            )
        except Exception as exc:
            log.warning("postgres approval backend unavailable in auto mode; falling back to memory: %s", exc)
    return InMemoryApprovalRepository(default_ttl_minutes=settings.policy.approval_ttl_minutes)


def build_artifact_repo(settings: Settings) -> ArtifactRepository:
    backend = _backend_mode(settings)
    log = logging.getLogger("ea.artifacts")
    if backend == "memory":
        return InMemoryArtifactRepository()
    if backend == "postgres":
        if not settings.database_url:
            raise RuntimeError("EA_STORAGE_BACKEND=postgres requires DATABASE_URL")
        return PostgresArtifactRepository(
            settings.database_url,
            artifacts_dir=settings.storage.artifacts_dir,
            tenant_id=settings.tenant_id,
        )
    if settings.database_url:
        try:
            return PostgresArtifactRepository(
                settings.database_url,
                artifacts_dir=settings.storage.artifacts_dir,
                tenant_id=settings.tenant_id,
            )
        except Exception as exc:
            log.warning("postgres artifact backend unavailable in auto mode; falling back to memory: %s", exc)
    return InMemoryArtifactRepository()


def build_default_orchestrator(settings: Settings | None = None) -> RewriteOrchestrator:
    resolved = settings or get_settings()
    ledger = build_execution_ledger(resolved)
    policy_repo = build_policy_repo(resolved)
    approvals = build_approval_repo(resolved)
    artifacts = build_artifact_repo(resolved)
    policy = PolicyDecisionService(
        max_rewrite_chars=resolved.policy.max_rewrite_chars,
        approval_required_chars=resolved.policy.approval_required_chars,
    )
    return RewriteOrchestrator(
        artifacts=artifacts,
        ledger=ledger,
        policy_repo=policy_repo,
        approvals=approvals,
        policy=policy,
    )
