from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

from app.domain.models import (
    ApprovalDecision,
    ApprovalRequest,
    Artifact,
    ExecutionEvent,
    ExecutionQueueItem,
    ExecutionSession,
    ExecutionStep,
    HumanTask,
    IntentSpecV3,
    OperatorProfile,
    PlanSpec,
    PlanStepSpec,
    PolicyDecision,
    RewriteRequest,
    RunCost,
    TaskExecutionRequest,
    ToolInvocationRequest,
    ToolReceipt,
    PlanValidationError,
    validate_plan_spec,
    now_utc_iso,
)
from app.repositories.approvals import ApprovalRepository, InMemoryApprovalRepository
from app.repositories.approvals_postgres import PostgresApprovalRepository
from app.repositories.artifacts import ArtifactRepository, InMemoryArtifactRepository
from app.repositories.artifacts_postgres import PostgresArtifactRepository
from app.repositories.human_tasks import (
    HumanTaskRepository,
    InMemoryHumanTaskRepository,
    _parse_assignment_source_filter,
)
from app.repositories.human_tasks_postgres import PostgresHumanTaskRepository
from app.repositories.ledger import ExecutionLedgerRepository, InMemoryExecutionLedgerRepository
from app.repositories.ledger_postgres import PostgresExecutionLedgerRepository
from app.repositories.operator_profiles import InMemoryOperatorProfileRepository, OperatorProfileRepository
from app.repositories.operator_profiles_postgres import PostgresOperatorProfileRepository
from app.repositories.policy_decisions import InMemoryPolicyDecisionRepository, PolicyDecisionRepository
from app.repositories.policy_decisions_postgres import PostgresPolicyDecisionRepository
from app.settings import Settings, ensure_storage_fallback_allowed, get_settings
from app.services.planner import PlannerService
from app.services.memory_runtime import MemoryRuntimeService, build_memory_runtime
from app.services.policy import ApprovalRequiredError, PolicyDecisionService, PolicyDeniedError
from app.services.task_contracts import TaskContractService, build_task_contract_service
from app.services.tool_execution import ToolExecutionService


@dataclass(frozen=True)
class ExecutionSessionSnapshot:
    session: ExecutionSession
    events: list[ExecutionEvent]
    steps: list[ExecutionStep]
    queue_items: list[ExecutionQueueItem]
    receipts: list[ToolReceipt]
    artifacts: list[Artifact]
    run_costs: list[RunCost]
    human_tasks: list[HumanTask]


class HumanTaskRequiredError(RuntimeError):
    def __init__(self, *, session_id: str, human_task_id: str, status: str = "awaiting_human") -> None:
        super().__init__(status)
        self.session_id = session_id
        self.human_task_id = human_task_id
        self.status = status


class AsyncExecutionQueuedError(RuntimeError):
    def __init__(
        self,
        *,
        session_id: str,
        status: str = "queued",
        next_attempt_at: str | None = None,
    ) -> None:
        super().__init__(status)
        self.session_id = session_id
        self.status = status
        self.next_attempt_at = next_attempt_at


class RewriteOrchestrator:
    _TRUST_RANK = {
        "junior": 0,
        "standard": 1,
        "senior": 2,
        "exec_delegate": 3,
        "principal_delegate": 3,
    }
    _HUMAN_TASK_ASSIGNMENT_EVENT_NAMES = {
        "human_task_created",
        "human_task_assigned",
        "human_task_claimed",
        "human_task_returned",
    }
    _AUTHORITY_RANK = {
        "": 0,
        "review": 0,
        "draft_review": 0,
        "send_on_behalf_review": 2,
        "principal_sensitive_review": 3,
        "principal_review": 3,
    }
    _RANK_TO_TIER = {
        0: "junior",
        1: "standard",
        2: "senior",
        3: "principal_delegate",
    }
    _HUMAN_TASK_PRIORITY_RANK = {
        "urgent": 3,
        "high": 2,
        "normal": 1,
        "medium": 1,
        "low": 0,
    }

    def __init__(
        self,
        artifacts: ArtifactRepository | None = None,
        ledger: ExecutionLedgerRepository | None = None,
        policy_repo: PolicyDecisionRepository | None = None,
        approvals: ApprovalRepository | None = None,
        human_tasks: HumanTaskRepository | None = None,
        operator_profiles: OperatorProfileRepository | None = None,
        policy: PolicyDecisionService | None = None,
        task_contracts: TaskContractService | None = None,
        planner: PlannerService | None = None,
        memory_runtime: MemoryRuntimeService | None = None,
        tool_execution: ToolExecutionService | None = None,
    ) -> None:
        self._artifacts = artifacts or InMemoryArtifactRepository()
        self._ledger = ledger or InMemoryExecutionLedgerRepository()
        self._policy_repo = policy_repo or InMemoryPolicyDecisionRepository()
        self._approvals = approvals or InMemoryApprovalRepository()
        self._human_tasks = human_tasks or InMemoryHumanTaskRepository()
        self._operator_profiles = operator_profiles or InMemoryOperatorProfileRepository()
        self._policy = policy or PolicyDecisionService()
        self._task_contracts = task_contracts
        self._planner = planner
        self._memory_runtime = memory_runtime
        self._tool_execution = tool_execution or ToolExecutionService(artifacts=self._artifacts)

    def _required_skill_tags(self, row: HumanTask) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    str(v).strip().lower()
                    for v in ((row.quality_rubric_json or {}).get("checks") or [])
                    if str(v).strip()
                }
            )
        )

    def _required_trust_rank(self, authority_required: str) -> int:
        return self._AUTHORITY_RANK.get(str(authority_required or "").strip().lower(), 0)

    def _required_trust_tier(self, authority_required: str) -> str:
        return self._RANK_TO_TIER.get(self._required_trust_rank(authority_required), "standard")

    def _operator_match_details(self, profile: OperatorProfile, row: HumanTask) -> dict[str, object]:
        roles = {str(v).strip() for v in profile.roles if str(v).strip()}
        role_required = str(row.role_required or "").strip()
        role_match = not role_required or not roles or role_required in roles
        required_skill_tags = set(self._required_skill_tags(row))
        operator_skill_tags = {str(v).strip().lower() for v in profile.skill_tags if str(v).strip()}
        matched_skill_tags = tuple(sorted(required_skill_tags & operator_skill_tags))
        missing_skill_tags = tuple(sorted(required_skill_tags - operator_skill_tags))
        trust_rank = self._TRUST_RANK.get(str(profile.trust_tier or "").strip().lower(), 1)
        required_rank = self._required_trust_rank(row.authority_required)
        authority_ok = trust_rank >= required_rank
        exact_match = role_match and authority_ok and not missing_skill_tags
        score = (
            (100 if exact_match else 0)
            + (20 if role_match else 0)
            + (len(matched_skill_tags) * 10)
            - (len(missing_skill_tags) * 5)
            + trust_rank
        )
        return {
            "role_match": role_match,
            "matched_skill_tags": matched_skill_tags,
            "missing_skill_tags": missing_skill_tags,
            "authority_ok": authority_ok,
            "exact_match": exact_match,
            "score": score,
        }

    def _build_human_task_routing_hints(self, row: HumanTask) -> dict[str, object]:
        profiles = self._operator_profiles.list_for_principal(
            principal_id=row.principal_id,
            status="active",
            limit=200,
        )
        suggestions: list[dict[str, object]] = []
        exact_matches: list[dict[str, object]] = []
        for profile in profiles:
            details = self._operator_match_details(profile, row)
            if not bool(details["role_match"]) or not bool(details["authority_ok"]):
                continue
            suggestion = {
                "operator_id": profile.operator_id,
                "display_name": profile.display_name,
                "trust_tier": profile.trust_tier,
                "score": int(details["score"]),
                "matched_skill_tags": list(details["matched_skill_tags"]),
                "missing_skill_tags": list(details["missing_skill_tags"]),
            }
            suggestions.append(suggestion)
            if bool(details["exact_match"]):
                exact_matches.append(suggestion)
        suggestions.sort(
            key=lambda item: (
                len(item["missing_skill_tags"]),  # type: ignore[arg-type]
                -int(item["score"]),
                str(item["display_name"]),
                str(item["operator_id"]),
            )
        )
        exact_matches.sort(
            key=lambda item: (
                -int(item["score"]),
                str(item["display_name"]),
                str(item["operator_id"]),
            )
        )
        suggested_operator_ids = [str(item["operator_id"]) for item in suggestions[:3]]
        recommended_operator_id = str(suggested_operator_ids[0]) if suggested_operator_ids else ""
        auto_assign_operator_id = ""
        if (
            row.status == "pending"
            and row.assignment_state == "unassigned"
            and len(exact_matches) == 1
            and exact_matches[0]["operator_id"] == recommended_operator_id
        ):
            auto_assign_operator_id = recommended_operator_id
        return {
            "required_skill_tags": list(self._required_skill_tags(row)),
            "required_trust_tier": self._required_trust_tier(row.authority_required),
            "candidate_count": len(suggestions),
            "suggested_operator_ids": suggested_operator_ids,
            "recommended_operator_id": recommended_operator_id,
            "auto_assign_operator_id": auto_assign_operator_id,
            "suggestions": suggestions[:3],
        }

    def _human_task_assignment_events(self, row: HumanTask) -> list[ExecutionEvent]:
        return [
            event
            for event in self._ledger.events_for(row.session_id)
            if event.name in self._HUMAN_TASK_ASSIGNMENT_EVENT_NAMES
            and str((event.payload or {}).get("human_task_id") or "") == row.human_task_id
        ]

    def _build_human_task_last_transition_summary(self, row: HumanTask) -> dict[str, object]:
        events = self._human_task_assignment_events(row)
        if not events:
            return {
                "last_transition_event_name": "",
                "last_transition_at": None,
                "last_transition_assignment_state": "",
                "last_transition_operator_id": "",
                "last_transition_assignment_source": "",
                "last_transition_by_actor_id": "",
            }
        last = events[-1]
        payload = dict(last.payload or {})
        return {
            "last_transition_event_name": last.name,
            "last_transition_at": str(last.created_at or "") or None,
            "last_transition_assignment_state": str(payload.get("assignment_state") or row.assignment_state or ""),
            "last_transition_operator_id": str(
                payload.get("assigned_operator_id") or payload.get("operator_id") or row.assigned_operator_id or ""
            ),
            "last_transition_assignment_source": str(payload.get("assignment_source") or row.assignment_source or ""),
            "last_transition_by_actor_id": str(payload.get("assigned_by_actor_id") or row.assigned_by_actor_id or ""),
        }

    def _decorate_human_task(self, row: HumanTask) -> HumanTask:
        return replace(
            row,
            routing_hints_json=self._build_human_task_routing_hints(row),
            **self._build_human_task_last_transition_summary(row),
        )

    def _sort_human_tasks(self, rows: list[HumanTask], *, sort: str | None = None) -> list[HumanTask]:
        sort_key = str(sort or "").strip().lower()
        if sort_key == "priority_desc_created_asc":
            return sorted(
                rows,
                key=lambda row: (
                    -self._HUMAN_TASK_PRIORITY_RANK.get(str(row.priority or "").strip().lower(), 1),
                    str(row.created_at or ""),
                    str(row.human_task_id or ""),
                ),
            )
        if sort_key == "created_asc":
            return sorted(
                rows,
                key=lambda row: (str(row.created_at or ""), str(row.human_task_id or "")),
            )
        if sort_key == "created_desc":
            return sorted(
                rows,
                key=lambda row: (str(row.created_at or ""), str(row.human_task_id or "")),
                reverse=True,
            )
        if sort_key == "last_transition_desc":
            return sorted(
                rows,
                key=lambda row: (
                    str(row.last_transition_at or ""),
                    str(row.created_at or ""),
                    str(row.human_task_id or ""),
                ),
                reverse=True,
            )
        if sort_key == "sla_due_at_asc":
            with_sla = sorted(
                [row for row in rows if row.sla_due_at],
                key=lambda row: (
                    str(row.sla_due_at or ""),
                    str(row.created_at or ""),
                    str(row.human_task_id or ""),
                ),
            )
            without_sla = sorted(
                [row for row in rows if not row.sla_due_at],
                key=lambda row: (
                    str(row.created_at or ""),
                    str(row.human_task_id or ""),
                ),
            )
            return with_sla + without_sla
        if sort_key == "sla_due_at_asc_last_transition_desc":
            with_sla = sorted(
                self._sort_human_tasks([row for row in rows if row.sla_due_at], sort="last_transition_desc"),
                key=lambda row: str(row.sla_due_at or ""),
            )
            without_sla = sorted(
                [row for row in rows if not row.sla_due_at],
                key=lambda row: (
                    str(row.created_at or ""),
                    str(row.human_task_id or ""),
                ),
            )
            return with_sla + without_sla
        return rows

    def _filter_human_task_rows(
        self,
        rows: list[HumanTask],
        *,
        principal_id: str,
        status: str | None = None,
        role_required: str | None = None,
        priority: str | None = None,
        assigned_operator_id: str | None = None,
        assignment_state: str | None = None,
        assignment_source: str | None = None,
        overdue_only: bool = False,
    ) -> list[HumanTask]:
        principal = str(principal_id or "").strip()
        status_filter = str(status or "").strip()
        role_filter = str(role_required or "").strip()
        priority_filters = {
            value.strip().lower()
            for value in str(priority or "").split(",")
            if value.strip()
        }
        operator_filter = str(assigned_operator_id or "").strip()
        assignment_filter = str(assignment_state or "").strip().lower()
        has_source_filter, source_filter = _parse_assignment_source_filter(assignment_source)
        filtered = [row for row in rows if row.principal_id == principal]
        if status_filter:
            filtered = [row for row in filtered if row.status == status_filter]
        if role_filter:
            filtered = [row for row in filtered if row.role_required == role_filter]
        if priority_filters:
            filtered = [row for row in filtered if str(row.priority or "").strip().lower() in priority_filters]
        if operator_filter:
            filtered = [row for row in filtered if row.assigned_operator_id == operator_filter]
        if assignment_filter:
            filtered = [row for row in filtered if row.assignment_state == assignment_filter]
        if has_source_filter:
            filtered = [row for row in filtered if row.assignment_source == source_filter]
        if overdue_only:
            now = datetime.now(timezone.utc)
            overdue_rows: list[HumanTask] = []
            for row in filtered:
                raw = str(row.sla_due_at or "").strip()
                if not raw:
                    continue
                try:
                    due = datetime.fromisoformat(raw)
                except ValueError:
                    continue
                if due.tzinfo is None:
                    due = due.replace(tzinfo=timezone.utc)
                if due <= now:
                    overdue_rows.append(row)
            filtered = overdue_rows
        return filtered

    def _default_goal_for_task(self, task_key: str) -> str:
        key = str(task_key or "").strip() or "rewrite_text"
        if key == "rewrite_text":
            return "rewrite supplied text into an artifact"
        return f"execute {key} into an artifact"

    def _normalized_task_input_json(self, req: TaskExecutionRequest) -> dict[str, object]:
        payload = {str(key): value for key, value in dict(req.input_json or {}).items() if str(key).strip()}
        context_refs = tuple(str(value or "").strip() for value in (req.context_refs or ()) if str(value or "").strip())
        text_alias = str(req.text or "").strip()
        structured_text = str(
            payload.get("normalized_text") or payload.get("source_text") or payload.get("text") or ""
        ).strip()
        effective_text = text_alias or structured_text
        if effective_text:
            payload.setdefault("source_text", effective_text)
            payload.setdefault("normalized_text", effective_text)
        if "text_length" not in payload and effective_text:
            payload["text_length"] = len(effective_text)
        if context_refs:
            payload["context_refs"] = list(context_refs)
        return payload

    def _legacy_parent_step_id(
        self,
        plan_step: PlanStepSpec,
        *,
        step_ids_by_key: dict[str, str],
    ) -> str | None:
        dependencies = tuple(
            key
            for key in (plan_step.depends_on or ())
            if str(key or "").strip() and str(key or "").strip() in step_ids_by_key
        )
        if len(dependencies) == 1:
            return step_ids_by_key[dependencies[0]]
        return None

    def _require_effective_principal(self, principal_id: str) -> str:
        resolved = str(principal_id or "").strip()
        if resolved:
            return resolved
        raise ValueError("principal_id_required")

    def _fallback_intent(self, *, task_key: str, principal_id: str, goal: str) -> IntentSpecV3:
        key = str(task_key or "").strip() or "rewrite_text"
        resolved_principal = self._require_effective_principal(principal_id)
        if key == "rewrite_text":
            return IntentSpecV3(
                principal_id=resolved_principal,
                goal=str(goal or self._default_goal_for_task(key)),
                task_type="rewrite_text",
                deliverable_type="rewrite_note",
                risk_class="low",
                approval_class="none",
                budget_class="low",
                allowed_tools=("artifact_repository",),
                desired_artifact="rewrite_note",
                memory_write_policy="reviewed_only",
            )
        contract = self._task_contracts.contract_or_default(key) if self._task_contracts else None
        deliverable_type = str(contract.deliverable_type if contract is not None else "generic_artifact") or "generic_artifact"
        default_risk_class = str(contract.default_risk_class if contract is not None else "low") or "low"
        default_approval_class = str(contract.default_approval_class if contract is not None else "none") or "none"
        budget_class = str((contract.budget_policy_json if contract is not None else {}).get("class") or "low")
        allowed_tools = (
            tuple(str(value) for value in contract.allowed_tools) if contract is not None else ("artifact_repository",)
        )
        if not allowed_tools:
            allowed_tools = ("artifact_repository",)
        evidence_requirements = tuple(str(value) for value in (contract.evidence_requirements if contract is not None else ()))
        memory_write_policy = str(contract.memory_write_policy if contract is not None else "reviewed_only") or "reviewed_only"
        return IntentSpecV3(
            principal_id=resolved_principal,
            goal=str(goal or self._default_goal_for_task(key)),
            task_type=key,
            deliverable_type=deliverable_type,
            risk_class=default_risk_class,
            approval_class=default_approval_class,
            budget_class=budget_class,
            allowed_tools=allowed_tools,
            evidence_requirements=evidence_requirements,
            desired_artifact=deliverable_type,
            memory_write_policy=memory_write_policy,
        )

    def _fallback_plan(self, intent: IntentSpecV3) -> PlanSpec:
        prepare_step = PlanStepSpec(
            step_key="step_input_prepare",
            step_kind="system_task",
            tool_name="",
            evidence_required=(),
            approval_required=False,
            reversible=False,
            expected_artifact="",
            fallback="request_human_intervention",
            owner="system",
            authority_class="observe",
            review_class="none",
            failure_strategy="fail",
            timeout_budget_seconds=30,
            max_attempts=1,
            retry_backoff_seconds=0,
            input_keys=("source_text",),
            output_keys=("normalized_text", "text_length"),
        )
        policy_step = PlanStepSpec(
            step_key="step_policy_evaluate",
            step_kind="policy_check",
            tool_name="",
            evidence_required=(),
            approval_required=False,
            reversible=False,
            expected_artifact="",
            fallback="pause_for_approval_or_block",
            owner="system",
            authority_class="observe",
            review_class="none",
            failure_strategy="fail",
            timeout_budget_seconds=30,
            max_attempts=1,
            retry_backoff_seconds=0,
            depends_on=("step_input_prepare",),
            input_keys=("normalized_text", "text_length"),
            output_keys=("allow", "requires_approval", "reason", "retention_policy", "memory_write_allowed"),
        )
        step = PlanStepSpec(
            step_key="step_artifact_save",
            step_kind="tool_call",
            tool_name="artifact_repository",
            evidence_required=intent.evidence_requirements,
            approval_required=intent.approval_class not in {"", "none"},
            reversible=False,
            expected_artifact=intent.deliverable_type,
            fallback="request_human_intervention",
            owner="tool",
            authority_class="draft",
            review_class="none",
            failure_strategy="fail",
            timeout_budget_seconds=60,
            max_attempts=1,
            retry_backoff_seconds=0,
            depends_on=("step_policy_evaluate",),
            input_keys=("normalized_text",),
            output_keys=("artifact_id", "receipt_id", "cost_id"),
        )
        return PlanSpec(
            plan_id=str(uuid.uuid4()),
            task_key=intent.task_type,
            principal_id=intent.principal_id,
            created_at=now_utc_iso(),
            steps=(prepare_step, policy_step, step),
        )

    def _default_action_kind_for_step(self, plan_step: PlanStepSpec) -> str:
        if plan_step.step_kind != "tool_call":
            return ""
        tool_name = str(plan_step.tool_name or "").strip()
        if tool_name == "connector.dispatch":
            return "delivery.send"
        if tool_name == "browseract.extract_account_facts":
            return "account.extract"
        if tool_name == "artifact_repository":
            return "artifact.save"
        return tool_name or "artifact.save"

    def _queue_idempotency_key(self, session_id: str, step_id: str) -> str:
        return f"rewrite:{session_id}:{step_id}"

    def _delayed_retry_queue_item(
        self,
        snapshot: ExecutionSessionSnapshot,
    ) -> ExecutionQueueItem | None:
        if str(snapshot.session.status or "") != "queued":
            return None
        now = datetime.now(timezone.utc)
        delayed_items: list[tuple[datetime, ExecutionQueueItem]] = []
        for row in snapshot.queue_items:
            if str(row.state or "") != "queued":
                continue
            raw_next_attempt_at = str(row.next_attempt_at or "").strip()
            if not raw_next_attempt_at:
                continue
            try:
                parsed = datetime.fromisoformat(raw_next_attempt_at)
            except ValueError:
                continue
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            if parsed > now:
                delayed_items.append((parsed, row))
        if not delayed_items:
            return None
        delayed_items.sort(key=lambda item: (item[0], str(item[1].queue_id or "")))
        return delayed_items[0][1]

    def _raise_for_async_snapshot_state(self, snapshot: ExecutionSessionSnapshot) -> None:
        if snapshot.session.status == "awaiting_human":
            human_task_id = snapshot.human_tasks[-1].human_task_id if snapshot.human_tasks else ""
            raise HumanTaskRequiredError(
                session_id=snapshot.session.session_id,
                human_task_id=human_task_id,
                status=snapshot.session.status,
            )
        if snapshot.session.status == "awaiting_approval":
            approval_request = next(
                (row for row in self._approvals.list_pending(limit=100) if row.session_id == snapshot.session.session_id),
                None,
            )
            raise ApprovalRequiredError(
                session_id=snapshot.session.session_id,
                approval_id=approval_request.approval_id if approval_request is not None else "",
                status=snapshot.session.status,
            )
        if snapshot.session.status == "blocked":
            decision = next(iter(self._policy_repo.list_recent(limit=1, session_id=snapshot.session.session_id)), None)
            reason = str(decision.reason if decision is not None else "") or "policy_denied"
            raise PolicyDeniedError(reason)
        delayed_retry = self._delayed_retry_queue_item(snapshot)
        if delayed_retry is not None:
            raise AsyncExecutionQueuedError(
                session_id=snapshot.session.session_id,
                status="queued",
                next_attempt_at=delayed_retry.next_attempt_at,
            )

    def _step_failure_strategy(self, rewrite_step: ExecutionStep) -> str:
        return str((rewrite_step.input_json or {}).get("failure_strategy") or "fail").strip().lower() or "fail"

    def _step_max_attempts(self, rewrite_step: ExecutionStep) -> int:
        try:
            value = int((rewrite_step.input_json or {}).get("max_attempts") or 1)
        except (TypeError, ValueError):
            return 1
        return max(1, value)

    def _step_retry_backoff_seconds(self, rewrite_step: ExecutionStep) -> int:
        try:
            value = int((rewrite_step.input_json or {}).get("retry_backoff_seconds") or 0)
        except (TypeError, ValueError):
            return 0
        return max(0, value)

    def _schedule_step_retry(
        self,
        queue_item: ExecutionQueueItem,
        rewrite_step: ExecutionStep,
        exc: Exception,
    ) -> bool:
        if self._step_failure_strategy(rewrite_step) != "retry":
            return False
        max_attempts = self._step_max_attempts(rewrite_step)
        if queue_item.attempt_count >= max_attempts:
            return False
        next_attempt_at = (
            datetime.now(timezone.utc) + timedelta(seconds=self._step_retry_backoff_seconds(rewrite_step))
        ).isoformat()
        self._ledger.retry_queue_item(
            queue_item.queue_id,
            last_error=str(exc),
            next_attempt_at=next_attempt_at,
        )
        self._ledger.update_step(
            rewrite_step.step_id,
            state="queued",
            error_json={
                "reason": "retry_scheduled",
                "detail": str(exc),
                "next_attempt_at": next_attempt_at,
                "attempt_count": queue_item.attempt_count,
                "max_attempts": max_attempts,
            },
            attempt_count=queue_item.attempt_count,
        )
        self._ledger.complete_session(queue_item.session_id, status="queued")
        self._ledger.append_event(
            queue_item.session_id,
            "step_retry_scheduled",
            {
                "queue_id": queue_item.queue_id,
                "step_id": queue_item.step_id,
                "attempt_count": queue_item.attempt_count,
                "max_attempts": max_attempts,
                "next_attempt_at": next_attempt_at,
                "reason": str(exc),
            },
        )
        return True

    def _enqueue_rewrite_step(self, session_id: str, step_id: str) -> ExecutionQueueItem:
        queue_item = self._ledger.enqueue_step(
            session_id,
            step_id,
            idempotency_key=self._queue_idempotency_key(session_id, step_id),
        )
        self._ledger.append_event(
            session_id,
            "step_enqueued",
            {
                "queue_id": queue_item.queue_id,
                "step_id": step_id,
                "state": queue_item.state,
            },
        )
        return queue_item

    def _complete_input_prepare_step(self, session_id: str, rewrite_step: ExecutionStep) -> None:
        input_json = self._merged_step_input_json(session_id, rewrite_step)
        source_text = str(input_json.get("source_text") or "").strip()
        plan_id = str(input_json.get("plan_id") or "")
        plan_step_key = str(input_json.get("plan_step_key") or "")
        output_json = self._validate_step_output_contract(
            rewrite_step,
            {
                "normalized_text": source_text,
                "text_length": len(source_text),
                "plan_id": plan_id,
                "plan_step_key": plan_step_key,
            },
        )
        self._ledger.update_step(
            rewrite_step.step_id,
            state="completed",
            output_json=output_json,
            error_json={},
        )
        self._ledger.append_event(
            session_id,
            "input_prepared",
            {
                "step_id": rewrite_step.step_id,
                "text_length": len(source_text),
                "plan_id": plan_id,
                "plan_step_key": plan_step_key,
            },
        )

    def _dependency_steps_for_step(self, session_id: str, rewrite_step: ExecutionStep) -> list[ExecutionStep]:
        steps = self._ledger.steps_for(session_id)
        lookup = self._dependency_lookup(steps)
        resolved: list[ExecutionStep] = []
        seen: set[str] = set()
        for key in self._step_dependency_keys(rewrite_step):
            row = lookup.get(key)
            if row is None or row.step_id in seen:
                continue
            resolved.append(row)
            seen.add(row.step_id)
        if not resolved and rewrite_step.parent_step_id:
            parent_step = self._ledger.get_step(rewrite_step.parent_step_id)
            if parent_step is not None:
                resolved.append(parent_step)
        return resolved

    def _declared_step_input_keys(self, rewrite_step: ExecutionStep) -> tuple[str, ...]:
        raw = (rewrite_step.input_json or {}).get("input_keys") or ()
        if isinstance(raw, (list, tuple)):
            values = tuple(str(value or "").strip() for value in raw if str(value or "").strip())
            if values:
                return values
        return ()

    def _declared_step_output_keys(self, rewrite_step: ExecutionStep) -> tuple[str, ...]:
        raw = (rewrite_step.input_json or {}).get("output_keys") or ()
        if isinstance(raw, (list, tuple)):
            values = tuple(str(value or "").strip() for value in raw if str(value or "").strip())
            if values:
                return values
        return ()

    def _validate_step_input_contract(self, rewrite_step: ExecutionStep, input_json: dict[str, object]) -> dict[str, object]:
        plan_step_key = str((rewrite_step.input_json or {}).get("plan_step_key") or rewrite_step.step_kind or "")
        for key in self._declared_step_input_keys(rewrite_step):
            if key not in input_json:
                raise RuntimeError(f"missing_step_input:{plan_step_key}:{key}")
        return input_json

    def _validate_step_output_contract(
        self, rewrite_step: ExecutionStep, output_json: dict[str, object]
    ) -> dict[str, object]:
        plan_step_key = str((rewrite_step.input_json or {}).get("plan_step_key") or rewrite_step.step_kind or "")
        for key in self._declared_step_output_keys(rewrite_step):
            if key not in output_json:
                raise RuntimeError(f"missing_step_output:{plan_step_key}:{key}")
        return output_json

    def _merged_step_input_json(self, session_id: str, rewrite_step: ExecutionStep) -> dict[str, object]:
        input_json = dict(rewrite_step.input_json or {})
        declared_input_keys = set(self._declared_step_input_keys(rewrite_step))
        for dependency in self._dependency_steps_for_step(session_id, rewrite_step):
            for key, value in dict(dependency.output_json or {}).items():
                if key not in input_json and (not declared_input_keys or key in declared_input_keys):
                    input_json[key] = value
            human_payload = (dependency.output_json or {}).get("human_returned_payload_json")
            if isinstance(human_payload, dict):
                final_text = str(human_payload.get("final_text") or human_payload.get("content") or "").strip()
                if final_text:
                    if not declared_input_keys or "source_text" in declared_input_keys:
                        input_json["source_text"] = final_text
                    if not declared_input_keys or "normalized_text" in declared_input_keys:
                        input_json["normalized_text"] = final_text
                    input_json["human_task_id"] = str((dependency.output_json or {}).get("human_task_id") or "")
        normalized_text = str(input_json.get("normalized_text") or "").strip()
        if normalized_text and not str(input_json.get("source_text") or "").strip():
            input_json["source_text"] = normalized_text
        source_text = str(input_json.get("source_text") or "").strip()
        if source_text and not str(input_json.get("normalized_text") or "").strip():
            input_json["normalized_text"] = source_text
        if "text_length" not in input_json and source_text:
            input_json["text_length"] = len(source_text)
        if not str(input_json.get("content") or "").strip():
            content = str(input_json.get("normalized_text") or input_json.get("source_text") or "").strip()
            if content:
                input_json["content"] = content
        return self._validate_step_input_contract(rewrite_step, input_json)

    def _approval_target_step_for_session(self, session_id: str) -> ExecutionStep | None:
        steps = self._ledger.steps_for(session_id)
        return next(
            (
                row
                for row in reversed(steps)
                if bool((row.input_json or {}).get("approval_required")) or row.step_kind == "tool_call"
            ),
            steps[0] if steps else None,
        )

    def _complete_policy_evaluate_step(self, session_id: str, rewrite_step: ExecutionStep) -> None:
        session = self._ledger.get_session(session_id)
        if session is None:
            raise RuntimeError(f"session missing for policy step: {session_id}")
        input_json = self._merged_step_input_json(session_id, rewrite_step)
        target_step = self._approval_target_step_for_session(session_id)
        target_tool_name = (
            str(((target_step.input_json if target_step is not None else {}) or {}).get("tool_name") or "").strip()
            or "artifact_repository"
        )
        target_action_kind = (
            str(((target_step.input_json if target_step is not None else {}) or {}).get("action_kind") or "").strip()
            or "artifact.save"
        )
        target_step_kind = (
            str(((target_step.input_json if target_step is not None else {}) or {}).get("plan_step_kind") or "").strip()
            or str(target_step.step_kind if target_step is not None else "").strip()
            or "tool_call"
        )
        target_authority_class = (
            str(((target_step.input_json if target_step is not None else {}) or {}).get("authority_class") or "").strip()
            or "observe"
        )
        target_review_class = (
            str(((target_step.input_json if target_step is not None else {}) or {}).get("review_class") or "").strip()
            or "none"
        )
        target_channel = str(((target_step.input_json if target_step is not None else {}) or {}).get("channel") or "").strip()
        normalized_text = str(input_json.get("normalized_text") or input_json.get("source_text") or "").strip()
        decision = self._policy.evaluate_step(
            session.intent,
            normalized_text,
            tool_name=target_tool_name,
            action_kind=target_action_kind,
            channel=target_channel,
            step_kind=target_step_kind,
            authority_class=target_authority_class,
            review_class=target_review_class,
        )
        self._policy_repo.append(session_id, decision)
        self._ledger.append_event(
            session_id,
            "policy_decision",
            {
                "allow": decision.allow,
                "requires_approval": decision.requires_approval,
                "reason": decision.reason,
                "retention_policy": decision.retention_policy,
                "memory_write_allowed": decision.memory_write_allowed,
            },
        )
        output_json = {
            "plan_id": str((rewrite_step.input_json or {}).get("plan_id") or ""),
            "plan_step_key": str((rewrite_step.input_json or {}).get("plan_step_key") or ""),
            "tool_name": target_tool_name,
            "action_kind": target_action_kind,
            "channel": target_channel,
            "step_kind": target_step_kind,
            "authority_class": target_authority_class,
            "review_class": target_review_class,
            "normalized_text": normalized_text,
            "text_length": int(input_json.get("text_length") or len(normalized_text)),
            "allow": decision.allow,
            "requires_approval": decision.requires_approval,
            "reason": decision.reason,
            "retention_policy": decision.retention_policy,
            "memory_write_allowed": decision.memory_write_allowed,
        }
        output_json = self._validate_step_output_contract(rewrite_step, output_json)
        self._ledger.update_step(
            rewrite_step.step_id,
            state="completed",
            output_json=output_json,
            error_json={},
        )
        self._ledger.append_event(
            session_id,
            "policy_step_completed",
            {
                "step_id": rewrite_step.step_id,
                "allow": bool(output_json.get("allow", False)),
                "requires_approval": bool(output_json.get("requires_approval", False)),
                "reason": str(output_json.get("reason") or ""),
            },
        )
        if not decision.allow:
            if target_step is None or target_step.step_id == rewrite_step.step_id:
                self._ledger.update_step(
                    rewrite_step.step_id,
                    state="blocked",
                    output_json=output_json,
                    error_json={"reason": decision.reason},
                )
            else:
                self._ledger.update_step(
                    target_step.step_id,
                    state="blocked",
                    output_json=target_step.output_json,
                    error_json={"reason": decision.reason},
                )
            self._ledger.complete_session(session_id, status="blocked")
            self._ledger.append_event(
                session_id,
                "session_blocked",
                {"reason": decision.reason},
            )
            return
        if decision.requires_approval and target_step is not None and target_step.step_id != rewrite_step.step_id:
            approval_request = self._approvals.create_request(
                session_id,
                target_step.step_id,
                reason="approval_required",
                requested_action_json={
                    "action": target_action_kind,
                    "artifact_kind": str((target_step.input_json or {}).get("expected_artifact") or ""),
                    "text_length": len(normalized_text),
                    "plan_id": str((rewrite_step.input_json or {}).get("plan_id") or ""),
                    "plan_step_key": str((target_step.input_json or {}).get("plan_step_key") or ""),
                    "tool_name": target_tool_name,
                    "channel": target_channel,
                    "step_kind": target_step_kind,
                    "authority_class": target_authority_class,
                    "review_class": target_review_class,
                },
            )
            self._ledger.update_step(
                target_step.step_id,
                state="waiting_approval",
                output_json=target_step.output_json,
                error_json={"reason": "approval_required", "approval_id": approval_request.approval_id},
            )
            self._ledger.complete_session(session_id, status="awaiting_approval")
            self._ledger.append_event(
                session_id,
                "session_paused_for_approval",
                {"reason": "approval_required", "approval_id": approval_request.approval_id},
            )

    def _start_human_task_step(self, session_id: str, rewrite_step: ExecutionStep) -> HumanTask:
        session = self._ledger.get_session(session_id)
        if session is None:
            raise RuntimeError(f"session missing for human-task step: {session_id}")
        input_json = self._merged_step_input_json(session_id, rewrite_step)
        desired_output_json = dict(input_json.get("desired_output_json") or {})
        if not str(desired_output_json.get("format") or "").strip():
            desired_output_json["format"] = str(input_json.get("expected_artifact") or "review_packet")
        priority = str(input_json.get("priority") or "normal").strip() or "normal"
        sla_due_at = str(input_json.get("sla_due_at") or "").strip()
        if not sla_due_at:
            try:
                sla_minutes = int(input_json.get("sla_minutes") or 0)
            except (TypeError, ValueError):
                sla_minutes = 0
            if sla_minutes > 0:
                sla_due_at = (datetime.now(timezone.utc) + timedelta(minutes=sla_minutes)).isoformat()
        row = self.create_human_task(
            session_id=session_id,
            step_id=rewrite_step.step_id,
            principal_id=session.intent.principal_id,
            task_type=str(input_json.get("task_type") or "communications_review"),
            role_required=str(input_json.get("role_required") or "communications_reviewer"),
            brief=str(input_json.get("brief") or "Review the prepared rewrite before finalizing the artifact."),
            authority_required=str(input_json.get("authority_required") or ""),
            why_human=str(input_json.get("why_human") or ""),
            quality_rubric_json=dict(input_json.get("quality_rubric_json") or {}),
            input_json={
                "source_text": str(input_json.get("source_text") or ""),
                "normalized_text": str(input_json.get("normalized_text") or input_json.get("source_text") or ""),
                "text_length": int(input_json.get("text_length") or 0),
                "plan_id": str(input_json.get("plan_id") or ""),
                "plan_step_key": str(input_json.get("plan_step_key") or ""),
            },
            desired_output_json=desired_output_json,
            priority=priority,
            sla_due_at=sla_due_at or None,
            resume_session_on_return=True,
        )
        if bool(input_json.get("auto_assign_if_unique")):
            auto_assign_operator_id = str((row.routing_hints_json or {}).get("auto_assign_operator_id") or "").strip()
            if auto_assign_operator_id:
                updated = self.assign_human_task(
                    row.human_task_id,
                    principal_id=session.intent.principal_id,
                    operator_id=auto_assign_operator_id,
                    assignment_source="auto_preselected",
                    assigned_by_actor_id="orchestrator:auto_preselected",
                )
                if updated is not None:
                    row = updated
        self._ledger.append_event(
            session_id,
            "human_task_step_started",
            {
                "step_id": rewrite_step.step_id,
                "human_task_id": row.human_task_id,
                "task_type": row.task_type,
                "role_required": row.role_required,
                "authority_required": row.authority_required,
                "priority": row.priority,
                "sla_due_at": row.sla_due_at or "",
                "assignment_state": row.assignment_state,
                "assigned_operator_id": row.assigned_operator_id,
                "assignment_source": row.assignment_source,
                "assigned_at": row.assigned_at or "",
                "assigned_by_actor_id": row.assigned_by_actor_id,
            },
        )
        return self._decorate_human_task(row)

    def _complete_tool_step(self, session_id: str, rewrite_step: ExecutionStep) -> Artifact | None:
        input_json = self._merged_step_input_json(session_id, rewrite_step)
        session = self._ledger.get_session(session_id)
        tool_name = str(input_json.get("tool_name") or "artifact_repository") or "artifact_repository"
        action_kind = str(input_json.get("action_kind") or "artifact.save") or "artifact.save"
        self._ledger.append_event(
            session_id,
            "tool_execution_started",
            {
                "step_id": rewrite_step.step_id,
                "tool_name": tool_name,
                "action_kind": action_kind,
            },
        )
        result = self._tool_execution.execute_invocation(
            ToolInvocationRequest(
                session_id=session_id,
                step_id=rewrite_step.step_id,
                tool_name=tool_name,
                action_kind=action_kind,
                payload_json=input_json,
                context_json={
                    "principal_id": session.intent.principal_id if session is not None else "",
                    "correlation_id": rewrite_step.correlation_id,
                    "causation_id": rewrite_step.causation_id,
                },
            )
        )
        receipt = self._ledger.append_tool_receipt(
            session_id,
            rewrite_step.step_id,
            tool_name=result.tool_name,
            action_kind=result.action_kind,
            target_ref=result.target_ref,
            receipt_json=result.receipt_json,
        )
        cost = self._ledger.append_run_cost(
            session_id,
            model_name=result.model_name,
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
            cost_usd=result.cost_usd,
        )
        output_json = dict(result.output_json or {})
        output_json.setdefault("receipt_id", receipt.receipt_id)
        output_json.setdefault("cost_id", cost.cost_id)
        output_json = self._validate_step_output_contract(rewrite_step, output_json)
        self._ledger.update_step(
            rewrite_step.step_id,
            state="completed",
            output_json=output_json,
            error_json={},
        )
        self._ledger.append_event(
            session_id,
            "tool_execution_completed",
            {
                "step_id": rewrite_step.step_id,
                "tool_name": result.tool_name,
                "action_kind": result.action_kind,
                "target_ref": result.target_ref,
            },
        )
        artifact = result.artifacts[0] if result.artifacts else None
        if artifact is not None:
            self._ledger.append_event(
                session_id,
                "artifact_persisted",
                {
                    "artifact_id": artifact.artifact_id,
                    "artifact_kind": artifact.kind,
                    "plan_id": str((result.output_json or {}).get("plan_id") or ""),
                    "plan_step_key": str((result.output_json or {}).get("plan_step_key") or ""),
                },
            )
        return artifact

    def _execute_step_handler(self, session_id: str, rewrite_step: ExecutionStep) -> Artifact | None:
        plan_step_key = str((rewrite_step.input_json or {}).get("plan_step_key") or "")
        if plan_step_key == "step_input_prepare":
            self._complete_input_prepare_step(session_id, rewrite_step)
            return None
        if plan_step_key == "step_policy_evaluate" or rewrite_step.step_kind == "policy_check":
            self._complete_policy_evaluate_step(session_id, rewrite_step)
            return None
        if plan_step_key == "step_human_review" or rewrite_step.step_kind == "human_task":
            self._start_human_task_step(session_id, rewrite_step)
            return None
        if plan_step_key == "step_memory_candidate_stage" or rewrite_step.step_kind == "memory_write":
            self._complete_memory_candidate_step(session_id, rewrite_step)
            return None
        if rewrite_step.step_kind == "tool_call":
            return self._complete_tool_step(session_id, rewrite_step)
        raise RuntimeError(f"unsupported_step_handler:{plan_step_key or rewrite_step.step_kind}")

    def _complete_memory_candidate_step(self, session_id: str, rewrite_step: ExecutionStep) -> None:
        session = self._ledger.get_session(session_id)
        if session is None:
            raise RuntimeError(f"session missing for memory step: {session_id}")
        if self._memory_runtime is None:
            raise RuntimeError("memory_runtime_unavailable")
        input_json = self._merged_step_input_json(session_id, rewrite_step)
        desired_output_json = dict((rewrite_step.input_json or {}).get("desired_output_json") or {})
        category = str(desired_output_json.get("category") or session.intent.deliverable_type or "artifact_fact").strip()
        sensitivity = str(desired_output_json.get("sensitivity") or "internal").strip() or "internal"
        confidence_value = desired_output_json.get("confidence")
        try:
            confidence = float(confidence_value if confidence_value is not None else 0.5)
        except (TypeError, ValueError):
            confidence = 0.5
        confidence = min(max(confidence, 0.0), 1.0)
        memory_write_allowed = bool(input_json.get("memory_write_allowed", session.intent.memory_write_policy != "none"))
        artifact_id = str(input_json.get("artifact_id") or "").strip()
        normalized_text = str(input_json.get("normalized_text") or input_json.get("source_text") or "").strip()
        if artifact_id:
            artifact = self._artifacts.get(artifact_id)
            artifact_content = str((artifact.content if artifact is not None else "") or "").strip()
            if artifact_content:
                normalized_text = artifact_content
        delivery_id = str(input_json.get("delivery_id") or "").strip()
        delivery_status = str(input_json.get("status") or "").strip()
        binding_id = str(input_json.get("binding_id") or "").strip()
        channel = str(input_json.get("channel") or "").strip()
        recipient = str(input_json.get("recipient") or "").strip()
        if not memory_write_allowed or session.intent.memory_write_policy == "none":
            output_json = self._validate_step_output_contract(
                rewrite_step,
                {
                    "candidate_id": "",
                    "candidate_status": "skipped",
                    "candidate_category": category,
                },
            )
            self._ledger.update_step(
                rewrite_step.step_id,
                state="completed",
                output_json=output_json,
                error_json={},
            )
            self._ledger.append_event(
                session_id,
                "memory_candidate_skipped",
                {"step_id": rewrite_step.step_id, "candidate_category": category},
            )
            return
        summary = normalized_text[:4000]
        candidate = self._memory_runtime.stage_candidate(
            principal_id=session.intent.principal_id,
            category=category,
            summary=summary,
            fact_json={
                "artifact_id": artifact_id,
                "deliverable_type": session.intent.deliverable_type,
                "task_key": session.intent.task_type,
                "normalized_text": normalized_text,
                "delivery_id": delivery_id,
                "delivery_status": delivery_status,
                "binding_id": binding_id,
                "channel": channel,
                "recipient": recipient,
            },
            source_session_id=session_id,
            source_step_id=rewrite_step.step_id,
            confidence=confidence,
            sensitivity=sensitivity,
        )
        output_json = self._validate_step_output_contract(
            rewrite_step,
            {
                "candidate_id": candidate.candidate_id,
                "candidate_status": candidate.status,
                "candidate_category": candidate.category,
            },
        )
        self._ledger.update_step(
            rewrite_step.step_id,
            state="completed",
            output_json=output_json,
            error_json={},
        )
        self._ledger.append_event(
            session_id,
            "memory_candidate_staged",
            {
                "step_id": rewrite_step.step_id,
                "candidate_id": candidate.candidate_id,
                "candidate_category": candidate.category,
            },
        )

    def _step_dependency_keys(self, row: ExecutionStep) -> tuple[str, ...]:
        raw = (row.input_json or {}).get("depends_on") or ()
        if isinstance(raw, (list, tuple)):
            values = tuple(str(value or "").strip() for value in raw if str(value or "").strip())
            if values:
                return values
        if row.parent_step_id:
            return (f"step-id:{row.parent_step_id}",)
        return ()

    def _dependency_lookup(self, steps: list[ExecutionStep]) -> dict[str, ExecutionStep]:
        lookup: dict[str, ExecutionStep] = {}
        for row in steps:
            step_key = str((row.input_json or {}).get("plan_step_key") or "").strip()
            if step_key:
                lookup[step_key] = row
            lookup[f"step-id:{row.step_id}"] = row
        return lookup

    def _active_queue_step_ids(self, session_id: str) -> set[str]:
        return {
            row.step_id
            for row in self._ledger.queue_for_session(session_id)
            if str(row.state or "") in {"queued", "leased"}
        }

    def _queue_item_is_eligible_now(self, row: ExecutionQueueItem) -> bool:
        now = datetime.now(timezone.utc)
        state = str(row.state or "")
        if state == "queued":
            if row.next_attempt_at:
                try:
                    if datetime.fromisoformat(row.next_attempt_at) > now:
                        return False
                except ValueError:
                    return False
            return True
        if state == "leased" and row.lease_expires_at:
            try:
                return datetime.fromisoformat(row.lease_expires_at) <= now
            except ValueError:
                return False
        return False

    def _next_eligible_queue_item_for_session(self, session_id: str) -> ExecutionQueueItem | None:
        session = self._ledger.get_session(session_id)
        if session is None or str(session.status or "") not in {"queued", "running"}:
            return None
        eligible = sorted(
            (
                row
                for row in self._ledger.queue_for_session(session_id)
                if self._queue_item_is_eligible_now(row)
            ),
            key=lambda row: (str(row.created_at or ""), str(row.queue_id or "")),
        )
        return eligible[0] if eligible else None

    def _drain_session_inline(
        self,
        session_id: str,
        *,
        stop_before_step_id: str | None = None,
    ) -> Artifact | None:
        artifact: Artifact | None = None
        while True:
            queue_item = self._next_eligible_queue_item_for_session(session_id)
            if queue_item is None:
                return artifact
            result = self.run_queue_item(
                queue_item.queue_id,
                lease_owner="inline",
                stop_before_step_id=stop_before_step_id,
            )
            if result is not None:
                artifact = result

    def _ready_steps(
        self,
        session_id: str,
        *,
        stop_before_step_id: str | None = None,
    ) -> list[ExecutionStep]:
        steps = self._ledger.steps_for(session_id)
        if not steps:
            return []
        dependency_lookup = self._dependency_lookup(steps)
        active_queue_step_ids = self._active_queue_step_ids(session_id)
        blocked_step_id = str(stop_before_step_id or "").strip()
        ready_steps: list[ExecutionStep] = []
        for row in steps:
            if row.state != "queued":
                continue
            if blocked_step_id and row.step_id == blocked_step_id:
                continue
            if row.step_id in active_queue_step_ids:
                continue
            dependency_keys = self._step_dependency_keys(row)
            if not dependency_keys:
                ready_steps.append(row)
                continue
            if all(
                (dependency_lookup.get(key) is not None and dependency_lookup[key].state == "completed")
                for key in dependency_keys
            ):
                ready_steps.append(row)
        return ready_steps

    def _next_ready_step(
        self,
        session_id: str,
        *,
        stop_before_step_id: str | None = None,
    ) -> ExecutionStep | None:
        ready_steps = self._ready_steps(session_id, stop_before_step_id=stop_before_step_id)
        if not ready_steps:
            return None
        return ready_steps[0]

    def _queue_next_step_after(
        self,
        session_id: str,
        step_id: str,
        *,
        lease_owner: str,
        stop_before_step_id: str | None = None,
    ) -> Artifact | None:
        steps = self._ledger.steps_for(session_id)
        if not any(row.step_id == step_id for row in steps):
            raise RuntimeError(f"step missing from session order: {step_id}")
        session = self._ledger.get_session(session_id)
        if session is not None and str(session.status or "") in {"awaiting_approval", "awaiting_human", "blocked"}:
            return None
        ready_steps = self._ready_steps(session_id, stop_before_step_id=stop_before_step_id)
        if not ready_steps:
            if steps and all(row.state == "completed" for row in steps):
                self._ledger.complete_session(session_id, status="completed")
                self._ledger.append_event(session_id, "session_completed", {"status": "completed"})
            return None
        queue_items = [self._enqueue_rewrite_step(session_id, row.step_id) for row in ready_steps]
        if lease_owner == "inline":
            artifact: Artifact | None = None
            for queue_item in queue_items:
                result = self.run_queue_item(
                    queue_item.queue_id,
                    lease_owner="inline",
                    stop_before_step_id=stop_before_step_id,
                )
                if result is not None:
                    artifact = result
                session = self._ledger.get_session(session_id)
                if session is not None and str(session.status or "") in {"awaiting_approval", "awaiting_human", "blocked"}:
                    break
            return artifact
        return None

    def _execute_leased_queue_item(
        self,
        queue_item: ExecutionQueueItem,
        *,
        stop_before_step_id: str | None = None,
    ) -> Artifact | None:
        step = self._ledger.get_step(queue_item.step_id)
        if step is None:
            self._ledger.fail_queue_item(queue_item.queue_id, last_error="step_not_found")
            raise RuntimeError(f"queued step missing: {queue_item.step_id}")
        self._ledger.complete_session(queue_item.session_id, status="running")
        running_step = self._ledger.update_step(
            step.step_id,
            state="running",
            error_json={},
            attempt_count=queue_item.attempt_count,
        )
        if running_step is None:
            self._ledger.fail_queue_item(queue_item.queue_id, last_error="step_not_found")
            raise RuntimeError(f"unable to mark step running: {queue_item.step_id}")
        self._ledger.append_event(
            queue_item.session_id,
            "step_execution_started",
            {
                "queue_id": queue_item.queue_id,
                "step_id": queue_item.step_id,
                "lease_owner": queue_item.lease_owner,
                "attempt_count": queue_item.attempt_count,
            },
        )
        try:
            artifact = self._execute_step_handler(queue_item.session_id, running_step)
        except Exception as exc:
            if self._schedule_step_retry(queue_item, running_step, exc):
                return None
            self._ledger.fail_queue_item(queue_item.queue_id, last_error=str(exc))
            self._ledger.update_step(
                queue_item.step_id,
                state="failed",
                error_json={"reason": "execution_failed", "detail": str(exc)},
                attempt_count=queue_item.attempt_count,
            )
            self._ledger.complete_session(queue_item.session_id, status="failed")
            self._ledger.append_event(
                queue_item.session_id,
                "session_failed",
                {"queue_id": queue_item.queue_id, "step_id": queue_item.step_id, "reason": "execution_failed"},
            )
            raise
        refreshed_step = self._ledger.get_step(queue_item.step_id)
        self._ledger.complete_queue_item(queue_item.queue_id, state="done")
        self._ledger.append_event(
            queue_item.session_id,
            "queue_item_completed",
            {"queue_id": queue_item.queue_id, "step_id": queue_item.step_id},
        )
        if refreshed_step is not None and refreshed_step.state == "waiting_human":
            return None
        next_artifact = self._queue_next_step_after(
            queue_item.session_id,
            running_step.step_id,
            lease_owner=queue_item.lease_owner,
            stop_before_step_id=stop_before_step_id,
        )
        if next_artifact is not None:
            return next_artifact
        return artifact

    def run_queue_item(
        self,
        queue_id: str,
        *,
        lease_owner: str = "inline",
        stop_before_step_id: str | None = None,
    ) -> Artifact | None:
        queue_item = self._ledger.lease_queue_item(queue_id, lease_owner=lease_owner)
        if queue_item is None:
            return None
        return self._execute_leased_queue_item(queue_item, stop_before_step_id=stop_before_step_id)

    def run_next_queue_item(self, *, lease_owner: str = "worker") -> Artifact | None:
        queue_item = self._ledger.lease_next_queue_item(lease_owner=lease_owner)
        if queue_item is None:
            return None
        return self._execute_leased_queue_item(queue_item)

    def execute_task_artifact(self, req: TaskExecutionRequest) -> Artifact:
        task_key = str(req.task_key or "").strip() or "rewrite_text"
        principal_id = self._require_effective_principal(req.principal_id)
        goal = str(req.goal or "").strip() or self._default_goal_for_task(task_key)
        if self._planner:
            intent, plan = self._planner.build_plan(
                task_key=task_key,
                principal_id=principal_id,
                goal=goal,
            )
        elif self._task_contracts:
            intent = self._fallback_intent(task_key=task_key, principal_id=principal_id, goal=goal)
            plan = self._fallback_plan(intent)
        else:
            intent = self._fallback_intent(task_key=task_key, principal_id=principal_id, goal=goal)
            plan = self._fallback_plan(intent)
        validate_plan_spec(plan)
        session = self._ledger.start_session(intent)
        correlation_id = str(uuid.uuid4())
        self._ledger.append_event(
            session.session_id,
            "intent_compiled",
            {
                "task_type": intent.task_type,
                "risk_class": intent.risk_class,
                "approval_class": intent.approval_class,
            },
        )
        self._ledger.append_event(
            session.session_id,
            "plan_compiled",
            {
                "plan_id": plan.plan_id,
                "task_key": plan.task_key,
                "step_count": len(plan.steps),
                "primary_step": plan.steps[0].step_key if plan.steps else "",
                "step_keys": [step.step_key for step in plan.steps],
                "step_semantics": [
                    {
                        "step_key": step.step_key,
                        "owner": step.owner,
                        "authority_class": step.authority_class,
                        "review_class": step.review_class,
                        "failure_strategy": step.failure_strategy,
                        "timeout_budget_seconds": step.timeout_budget_seconds,
                        "max_attempts": step.max_attempts,
                        "retry_backoff_seconds": step.retry_backoff_seconds,
                    }
                    for step in plan.steps
                ],
            },
        )
        task_input_json = self._normalized_task_input_json(req)
        normalized_text = str(task_input_json.get("source_text") or "").strip()
        plan_steps = tuple(plan.steps) or (
            PlanStepSpec(
                step_key="step_input_prepare",
                step_kind="system_task",
                tool_name="",
                evidence_required=(),
                approval_required=False,
                reversible=False,
                expected_artifact="",
                fallback="request_human_intervention",
                owner="system",
                authority_class="observe",
                review_class="none",
                failure_strategy="fail",
                timeout_budget_seconds=30,
                max_attempts=1,
                retry_backoff_seconds=0,
                input_keys=("source_text",),
                output_keys=("normalized_text", "text_length"),
            ),
            PlanStepSpec(
                step_key="step_policy_evaluate",
                step_kind="policy_check",
                tool_name="",
                evidence_required=(),
                approval_required=False,
                reversible=False,
                expected_artifact="",
                fallback="pause_for_approval_or_block",
                owner="system",
                authority_class="observe",
                review_class="none",
                failure_strategy="fail",
                timeout_budget_seconds=30,
                max_attempts=1,
                retry_backoff_seconds=0,
                depends_on=("step_input_prepare",),
                input_keys=("normalized_text", "text_length"),
                output_keys=("allow", "requires_approval", "reason", "retention_policy", "memory_write_allowed"),
            ),
            PlanStepSpec(
                step_key="step_artifact_save",
                step_kind="tool_call",
                tool_name="artifact_repository",
                evidence_required=(),
                approval_required=False,
                reversible=False,
                expected_artifact=intent.deliverable_type,
                fallback="request_human_intervention",
                owner="tool",
                authority_class="draft",
                review_class="none",
                failure_strategy="fail",
                timeout_budget_seconds=60,
                max_attempts=1,
                retry_backoff_seconds=0,
                depends_on=("step_policy_evaluate",),
                input_keys=("normalized_text",),
                output_keys=("artifact_id", "receipt_id", "cost_id"),
            ),
        )
        created_steps: list[ExecutionStep] = []
        step_ids_by_key: dict[str, str] = {}
        for index, plan_step in enumerate(plan_steps):
            created_steps.append(
                self._ledger.start_step(
                    session.session_id,
                    plan_step.step_kind or "tool_call",
                    parent_step_id=self._legacy_parent_step_id(plan_step, step_ids_by_key=step_ids_by_key),
                    input_json={
                        **task_input_json,
                        "plan_id": plan.plan_id,
                        "plan_step_key": plan_step.step_key,
                        "plan_step_kind": plan_step.step_kind,
                        "tool_name": plan_step.tool_name,
                        "owner": plan_step.owner,
                        "authority_class": plan_step.authority_class,
                        "review_class": plan_step.review_class,
                        "failure_strategy": plan_step.failure_strategy,
                        "timeout_budget_seconds": plan_step.timeout_budget_seconds,
                        "max_attempts": plan_step.max_attempts,
                        "retry_backoff_seconds": plan_step.retry_backoff_seconds,
                        "action_kind": self._default_action_kind_for_step(plan_step),
                        "approval_required": plan_step.approval_required,
                        "expected_artifact": plan_step.expected_artifact,
                        "fallback": plan_step.fallback,
                        "depends_on": list(plan_step.depends_on),
                        "input_keys": list(plan_step.input_keys),
                        "output_keys": list(plan_step.output_keys),
                        "task_type": plan_step.task_type,
                        "role_required": plan_step.role_required,
                        "brief": plan_step.brief,
                        "priority": plan_step.priority,
                        "sla_minutes": plan_step.sla_minutes,
                        "auto_assign_if_unique": plan_step.auto_assign_if_unique,
                        "desired_output_json": dict(plan_step.desired_output_json),
                        "authority_required": plan_step.authority_required,
                        "why_human": plan_step.why_human,
                        "quality_rubric_json": dict(plan_step.quality_rubric_json),
                        "step_index": index,
                        "step_count": len(plan_steps),
                    },
                    correlation_id=correlation_id,
                    causation_id=plan.plan_id,
                    actor_type="assistant",
                    actor_id="orchestrator",
                )
            )
            step_ids_by_key[str(plan_step.step_key or "")] = created_steps[-1].step_id
        next_step = self._next_ready_step(session.session_id)
        if next_step is None:
            raise RuntimeError(f"task queue did not resolve a ready step: {session.session_id}")
        queue_item = self._enqueue_rewrite_step(session.session_id, next_step.step_id)
        artifact = self.run_queue_item(queue_item.queue_id, lease_owner="inline")
        drained_artifact = self._drain_session_inline(session.session_id)
        if drained_artifact is not None:
            artifact = drained_artifact
        snapshot = self.fetch_session(session.session_id)
        if snapshot is not None:
            self._raise_for_async_snapshot_state(snapshot)
            if snapshot.session.status == "completed":
                if artifact is not None:
                    return artifact
                if snapshot.artifacts:
                    return snapshot.artifacts[-1]
        if artifact is not None:
            return artifact
        raise RuntimeError(f"queued task did not execute: {queue_item.queue_id}")

    def build_artifact(self, req: RewriteRequest) -> Artifact:
        return self.execute_task_artifact(
            TaskExecutionRequest(
                task_key="rewrite_text",
                text=req.text,
                principal_id=req.principal_id,
                goal=req.goal,
            )
        )

    def fetch_session_for_principal(
        self,
        session_id: str,
        *,
        principal_id: str,
    ) -> ExecutionSessionSnapshot | None:
        found = self.fetch_session(session_id)
        if found is None:
            return None
        self._require_session_principal_alignment(found.session, principal_id=principal_id)
        return found

    def fetch_artifact(self, artifact_id: str) -> Artifact | None:
        return self._artifacts.get(artifact_id)

    def fetch_artifact_for_principal(
        self,
        artifact_id: str,
        *,
        principal_id: str,
    ) -> tuple[Artifact, ExecutionSessionSnapshot] | None:
        artifact = self.fetch_artifact(artifact_id)
        if artifact is None:
            return None
        requested_principal = self._require_effective_principal(principal_id)
        artifact_principal = str(artifact.principal_id or "").strip()
        if artifact_principal:
            if artifact_principal != requested_principal:
                raise PermissionError("principal_scope_mismatch")
        else:
            # Legacy rows created before explicit artifact ownership still fall back to the
            # linked session scope until the migration/backfill has touched them.
            session = self.fetch_session_for_principal(artifact.execution_session_id, principal_id=principal_id)
            if session is None:
                return None
            return artifact, session
        session = self.fetch_session_for_principal(artifact.execution_session_id, principal_id=principal_id)
        if session is None:
            return None
        return artifact, session

    def fetch_receipt(self, receipt_id: str) -> ToolReceipt | None:
        return self._ledger.get_receipt(receipt_id)

    def fetch_receipt_for_principal(
        self,
        receipt_id: str,
        *,
        principal_id: str,
    ) -> tuple[ToolReceipt, ExecutionSessionSnapshot] | None:
        receipt = self.fetch_receipt(receipt_id)
        if receipt is None:
            return None
        session = self.fetch_session_for_principal(receipt.session_id, principal_id=principal_id)
        if session is None:
            return None
        return receipt, session

    def fetch_run_cost(self, cost_id: str) -> RunCost | None:
        return self._ledger.get_run_cost(cost_id)

    def fetch_run_cost_for_principal(
        self,
        cost_id: str,
        *,
        principal_id: str,
    ) -> tuple[RunCost, ExecutionSessionSnapshot] | None:
        run_cost = self.fetch_run_cost(cost_id)
        if run_cost is None:
            return None
        session = self.fetch_session_for_principal(run_cost.session_id, principal_id=principal_id)
        if session is None:
            return None
        return run_cost, session

    def fetch_approval_request(self, approval_id: str) -> ApprovalRequest | None:
        return self._approvals.get_request(approval_id)

    def fetch_approval_request_for_principal(
        self,
        approval_id: str,
        *,
        principal_id: str,
    ) -> ApprovalRequest | None:
        request = self.fetch_approval_request(approval_id)
        if request is None:
            return None
        session = self.fetch_session_for_principal(request.session_id, principal_id=principal_id)
        if session is None:
            return None
        return request

    def _require_session_principal_alignment(self, session: ExecutionSession, *, principal_id: str) -> None:
        session_principal = self._require_effective_principal(session.intent.principal_id)
        requested_principal = self._require_effective_principal(principal_id)
        if session_principal != requested_principal:
            raise PermissionError("principal_scope_mismatch")

    def create_human_task(
        self,
        *,
        session_id: str,
        principal_id: str,
        task_type: str,
        role_required: str,
        brief: str,
        authority_required: str = "",
        why_human: str = "",
        quality_rubric_json: dict[str, object] | None = None,
        input_json: dict[str, object] | None = None,
        desired_output_json: dict[str, object] | None = None,
        priority: str = "normal",
        sla_due_at: str | None = None,
        step_id: str | None = None,
        resume_session_on_return: bool = False,
    ) -> HumanTask:
        session = self._ledger.get_session(session_id)
        if session is None:
            raise KeyError("session_not_found")
        self._require_session_principal_alignment(session, principal_id=principal_id)
        step: ExecutionStep | None = None
        if resume_session_on_return and not step_id:
            raise KeyError("step_id_required")
        if step_id:
            step = self._ledger.get_step(step_id)
            if step is None or step.session_id != session.session_id:
                raise KeyError("step_not_found")
        row = self._human_tasks.create(
            session_id=session.session_id,
            step_id=step_id,
            principal_id=principal_id,
            task_type=task_type,
            role_required=role_required,
            brief=brief,
            authority_required=authority_required,
            why_human=why_human,
            quality_rubric_json=quality_rubric_json,
            input_json=input_json,
            desired_output_json=desired_output_json,
            priority=priority,
            sla_due_at=sla_due_at,
            resume_session_on_return=resume_session_on_return,
        )
        if row.resume_session_on_return and step is not None:
            self._ledger.update_step(
                step.step_id,
                state="waiting_human",
                output_json=step.output_json,
                error_json={"reason": "human_task_required", "human_task_id": row.human_task_id},
                attempt_count=step.attempt_count,
            )
            self._ledger.complete_session(session.session_id, status="awaiting_human")
            self._ledger.append_event(
                session.session_id,
                "session_paused_for_human_task",
                {
                    "human_task_id": row.human_task_id,
                    "step_id": step.step_id,
                    "role_required": row.role_required,
                },
            )
        self._ledger.append_event(
            session.session_id,
            "human_task_created",
            {
                "human_task_id": row.human_task_id,
                "step_id": row.step_id or "",
                "task_type": row.task_type,
                "role_required": row.role_required,
                "authority_required": row.authority_required,
                "why_human": row.why_human,
                "quality_rubric_json": row.quality_rubric_json,
                "priority": row.priority,
                "sla_due_at": row.sla_due_at or "",
                "desired_output_json": row.desired_output_json,
                "assignment_state": row.assignment_state,
                "assigned_operator_id": row.assigned_operator_id,
                "assignment_source": row.assignment_source,
                "assigned_at": row.assigned_at or "",
                "assigned_by_actor_id": row.assigned_by_actor_id,
                "resume_session_on_return": row.resume_session_on_return,
            },
        )
        return self._decorate_human_task(row)

    def fetch_human_task(self, human_task_id: str, *, principal_id: str) -> HumanTask | None:
        row = self._human_tasks.get(human_task_id)
        if row is None or row.principal_id != str(principal_id or ""):
            return None
        return self._decorate_human_task(row)

    def list_human_tasks(
        self,
        *,
        principal_id: str,
        session_id: str | None = None,
        status: str | None = None,
        role_required: str | None = None,
        priority: str | None = None,
        assigned_operator_id: str | None = None,
        assignment_state: str | None = None,
        assignment_source: str | None = None,
        operator_id: str | None = None,
        overdue_only: bool = False,
        limit: int = 50,
        sort: str | None = None,
    ) -> list[HumanTask]:
        session = str(session_id or "").strip()
        if session:
            found = self._ledger.get_session(session)
            if found is None:
                return []
            self._require_session_principal_alignment(found, principal_id=principal_id)
            rows = self._human_tasks.list_for_session(session, limit=max(limit, 1))
            rows = self._filter_human_task_rows(
                rows,
                principal_id=principal_id,
                status=status,
                role_required=role_required,
                priority=priority,
                assigned_operator_id=assigned_operator_id,
                assignment_state=assignment_state,
                assignment_source=assignment_source,
                overdue_only=overdue_only,
            )
            decorated = [self._decorate_human_task(row) for row in rows]
            resolved_operator_id = str(operator_id or "").strip()
            if not resolved_operator_id:
                return self._sort_human_tasks(decorated, sort=sort)
            profile = self.fetch_operator_profile(resolved_operator_id, principal_id=principal_id)
            if profile is None:
                return []
            return self._sort_human_tasks(
                [row for row in decorated if self._operator_matches_human_task(profile, row)],
                sort=sort,
            )
        rows = self._human_tasks.list_for_principal(
            principal_id,
            status=status,
            role_required=role_required,
            priority=priority,
            assigned_operator_id=assigned_operator_id,
            assignment_state=assignment_state,
            assignment_source=assignment_source,
            overdue_only=overdue_only,
            limit=limit,
        )
        resolved_operator_id = str(operator_id or "").strip()
        if not resolved_operator_id:
            return self._sort_human_tasks([self._decorate_human_task(row) for row in rows], sort=sort)
        profile = self.fetch_operator_profile(resolved_operator_id, principal_id=principal_id)
        if profile is None:
            return []
        return self._sort_human_tasks(
            [self._decorate_human_task(row) for row in rows if self._operator_matches_human_task(profile, row)],
            sort=sort,
        )

    def summarize_human_task_priorities(
        self,
        *,
        principal_id: str,
        status: str = "pending",
        role_required: str | None = None,
        operator_id: str | None = None,
        assigned_operator_id: str | None = None,
        assignment_state: str | None = None,
        assignment_source: str | None = None,
        overdue_only: bool = False,
    ) -> dict[str, object]:
        resolved_operator_id = str(operator_id or "").strip()
        requested_assignment_source = str(assignment_source or "").strip()
        if resolved_operator_id:
            profile = self.fetch_operator_profile(resolved_operator_id, principal_id=principal_id)
            if profile is None:
                counts: dict[str, int] = {}
            else:
                rows = self._human_tasks.list_for_principal(
                    principal_id,
                    status=status,
                    role_required=role_required,
                    assigned_operator_id=assigned_operator_id,
                    assignment_state=assignment_state,
                    assignment_source=assignment_source,
                    overdue_only=overdue_only,
                    limit=0,
                )
                counts = {}
                for row in rows:
                    if not self._operator_matches_human_task(profile, row):
                        continue
                    key = str(row.priority or "").strip().lower() or "normal"
                    counts[key] = counts.get(key, 0) + 1
        else:
            counts = self._human_tasks.count_by_priority_for_principal(
                principal_id,
                status=status,
                role_required=role_required,
                assigned_operator_id=assigned_operator_id,
                assignment_state=assignment_state,
                assignment_source=assignment_source,
                overdue_only=overdue_only,
            )
        normalized = {
            "urgent": int(counts.get("urgent", 0)),
            "high": int(counts.get("high", 0)),
            "normal": int(counts.get("normal", 0)),
            "low": int(counts.get("low", 0)),
        }
        extra = {
            key: int(value)
            for key, value in counts.items()
            if key not in normalized
        }
        ordered = {**normalized, **dict(sorted(extra.items()))}
        highest_priority = next((key for key in ("urgent", "high", "normal", "low") if ordered.get(key, 0) > 0), "")
        return {
            "status": status,
            "role_required": str(role_required or ""),
            "operator_id": resolved_operator_id,
            "assigned_operator_id": str(assigned_operator_id or ""),
            "assignment_state": str(assignment_state or ""),
            "assignment_source": requested_assignment_source,
            "overdue_only": bool(overdue_only),
            "counts_json": ordered,
            "total": sum(ordered.values()),
            "highest_priority": highest_priority,
        }

    def list_human_task_assignment_history(
        self,
        human_task_id: str,
        *,
        principal_id: str,
        event_name: str | None = None,
        assigned_operator_id: str | None = None,
        assigned_by_actor_id: str | None = None,
        assignment_source: str | None = None,
        limit: int = 100,
    ) -> list[ExecutionEvent]:
        found = self.fetch_human_task(human_task_id, principal_id=principal_id)
        if found is None:
            return []
        n = max(1, min(500, int(limit or 100)))
        event_filter = str(event_name or "").strip()
        operator_filter = str(assigned_operator_id or "").strip()
        actor_filter = str(assigned_by_actor_id or "").strip()
        has_source_filter, source_filter = _parse_assignment_source_filter(assignment_source)
        rows = self._human_task_assignment_events(found)
        if event_filter:
            rows = [event for event in rows if event.name == event_filter]
        if operator_filter:
            rows = [
                event
                for event in rows
                if str((event.payload or {}).get("assigned_operator_id") or (event.payload or {}).get("operator_id") or "")
                == operator_filter
            ]
        if actor_filter:
            rows = [
                event
                for event in rows
                if str((event.payload or {}).get("assigned_by_actor_id") or "") == actor_filter
            ]
        if has_source_filter:
            rows = [
                event
                for event in rows
                if str((event.payload or {}).get("assignment_source") or "") == source_filter
            ]
        if len(rows) <= n:
            return rows
        return rows[-n:]

    def _operator_matches_human_task(self, profile: OperatorProfile, row: HumanTask) -> bool:
        details = self._operator_match_details(profile, row)
        return bool(details["exact_match"])

    def upsert_operator_profile(
        self,
        *,
        principal_id: str,
        operator_id: str | None = None,
        display_name: str,
        roles: tuple[str, ...] = (),
        skill_tags: tuple[str, ...] = (),
        trust_tier: str = "standard",
        status: str = "active",
        notes: str = "",
    ) -> OperatorProfile:
        row = self._operator_profiles.upsert_profile(
            principal_id=principal_id,
            operator_id=operator_id,
            display_name=display_name,
            roles=roles,
            skill_tags=skill_tags,
            trust_tier=trust_tier,
            status=status,
            notes=notes,
        )
        return row

    def fetch_operator_profile(self, operator_id: str, *, principal_id: str) -> OperatorProfile | None:
        row = self._operator_profiles.get(operator_id)
        if row is None or row.principal_id != str(principal_id or ""):
            return None
        return row

    def list_operator_profiles(
        self,
        *,
        principal_id: str,
        status: str | None = None,
        limit: int = 100,
    ) -> list[OperatorProfile]:
        return self._operator_profiles.list_for_principal(
            principal_id=principal_id,
            status=status,
            limit=limit,
        )

    def claim_human_task(
        self,
        human_task_id: str,
        *,
        principal_id: str,
        operator_id: str,
        assigned_by_actor_id: str | None = None,
    ) -> HumanTask | None:
        found = self.fetch_human_task(human_task_id, principal_id=principal_id)
        if found is None:
            return None
        updated = self._human_tasks.claim(
            human_task_id,
            operator_id=operator_id,
            assigned_by_actor_id=assigned_by_actor_id,
        )
        if updated is None:
            return None
        self._ledger.append_event(
            updated.session_id,
            "human_task_claimed",
            {
                "human_task_id": updated.human_task_id,
                "operator_id": updated.assigned_operator_id,
                "assigned_operator_id": updated.assigned_operator_id,
                "assignment_state": updated.assignment_state,
                "assignment_source": "manual",
                "assigned_at": updated.assigned_at or "",
                "assigned_by_actor_id": str(assigned_by_actor_id or operator_id or ""),
                "step_id": updated.step_id or "",
            },
        )
        return self._decorate_human_task(updated)

    def assign_human_task(
        self,
        human_task_id: str,
        *,
        principal_id: str,
        operator_id: str,
        assignment_source: str = "manual",
        assigned_by_actor_id: str | None = None,
    ) -> HumanTask | None:
        found = self.fetch_human_task(human_task_id, principal_id=principal_id)
        if found is None:
            return None
        updated = self._human_tasks.assign(
            human_task_id,
            operator_id=operator_id,
            assignment_source=assignment_source,
            assigned_by_actor_id=assigned_by_actor_id,
        )
        if updated is None:
            return None
        self._ledger.append_event(
            updated.session_id,
            "human_task_assigned",
            {
                "human_task_id": updated.human_task_id,
                "operator_id": updated.assigned_operator_id,
                "assigned_operator_id": updated.assigned_operator_id,
                "assignment_state": updated.assignment_state,
                "assignment_source": updated.assignment_source,
                "assigned_at": updated.assigned_at or "",
                "assigned_by_actor_id": updated.assigned_by_actor_id,
                "step_id": updated.step_id or "",
            },
        )
        return self._decorate_human_task(updated)

    def return_human_task(
        self,
        human_task_id: str,
        *,
        principal_id: str,
        operator_id: str,
        resolution: str,
        returned_payload_json: dict[str, object] | None = None,
        provenance_json: dict[str, object] | None = None,
    ) -> HumanTask | None:
        found = self.fetch_human_task(human_task_id, principal_id=principal_id)
        if found is None:
            return None
        updated = self._human_tasks.return_task(
            human_task_id,
            operator_id=operator_id,
            resolution=resolution,
            returned_payload_json=returned_payload_json,
            provenance_json=provenance_json,
        )
        if updated is None:
            return None
        self._ledger.append_event(
            updated.session_id,
            "human_task_returned",
            {
                "human_task_id": updated.human_task_id,
                "operator_id": updated.assigned_operator_id,
                "assigned_operator_id": updated.assigned_operator_id,
                "resolution": updated.resolution,
                "assignment_state": updated.assignment_state,
                "assignment_source": "manual",
                "assigned_at": updated.assigned_at or "",
                "assigned_by_actor_id": operator_id,
                "step_id": updated.step_id or "",
            },
        )
        if updated.resume_session_on_return and updated.step_id:
            step = self._ledger.get_step(updated.step_id)
            if step is not None:
                output_json = dict(step.output_json or {})
                output_json.update(
                    {
                        "human_task_id": updated.human_task_id,
                        "human_resolution": updated.resolution,
                        "human_returned_payload_json": updated.returned_payload_json,
                        "human_provenance_json": updated.provenance_json,
                    }
                )
                output_json = self._validate_step_output_contract(step, output_json)
                self._ledger.update_step(
                    updated.step_id,
                    state="completed",
                    output_json=output_json,
                    error_json={},
                    attempt_count=step.attempt_count,
                )
                self._ledger.complete_session(updated.session_id, status="running")
                self._ledger.append_event(
                    updated.session_id,
                    "session_resumed_from_human_task",
                    {
                        "human_task_id": updated.human_task_id,
                        "step_id": updated.step_id,
                        "resolution": updated.resolution,
                    },
                )
                _ = self._queue_next_step_after(updated.session_id, updated.step_id, lease_owner="inline")
                _ = self._drain_session_inline(updated.session_id)
        return self._decorate_human_task(updated)

    def fetch_session(self, session_id: str) -> ExecutionSessionSnapshot | None:
        session = self._ledger.get_session(session_id)
        if not session:
            return None
        sid = session.session_id
        return ExecutionSessionSnapshot(
            session=session,
            events=self._ledger.events_for(sid),
            steps=self._ledger.steps_for(sid),
            queue_items=self._ledger.queue_for_session(sid),
            receipts=self._ledger.receipts_for(sid),
            artifacts=self._artifacts.list_for_session(sid),
            run_costs=self._ledger.run_costs_for(sid),
            human_tasks=[self._decorate_human_task(row) for row in self._human_tasks.list_for_session(sid)],
        )

    def list_policy_decisions(self, limit: int = 50, session_id: str | None = None):
        return self._policy_repo.list_recent(limit=limit, session_id=session_id)

    def list_policy_decisions_for_principal(
        self,
        *,
        principal_id: str,
        limit: int = 50,
        session_id: str | None = None,
    ) -> list[PolicyDecision]:
        n = max(1, min(500, int(limit or 50)))
        rows = self._policy_repo.list_recent(limit=500, session_id=session_id)
        filtered: list[PolicyDecision] = []
        for row in rows:
            try:
                session = self.fetch_session_for_principal(row.session_id, principal_id=principal_id)
            except PermissionError:
                continue
            if session is None:
                continue
            filtered.append(row)
            if len(filtered) >= n:
                break
        return filtered

    def list_pending_approvals(self, limit: int = 50) -> list[ApprovalRequest]:
        return self._approvals.list_pending(limit=limit)

    def list_pending_approvals_for_principal(
        self,
        *,
        principal_id: str,
        limit: int = 50,
    ) -> list[ApprovalRequest]:
        n = max(1, min(500, int(limit or 50)))
        rows = self._approvals.list_pending(limit=500)
        filtered: list[ApprovalRequest] = []
        for row in rows:
            try:
                session = self.fetch_session_for_principal(row.session_id, principal_id=principal_id)
            except PermissionError:
                continue
            if session is None:
                continue
            filtered.append(row)
            if len(filtered) >= n:
                break
        return filtered

    def list_approval_history(self, limit: int = 50, session_id: str | None = None) -> list[ApprovalDecision]:
        return self._approvals.list_history(limit=limit, session_id=session_id)

    def list_approval_history_for_principal(
        self,
        *,
        principal_id: str,
        limit: int = 50,
        session_id: str | None = None,
    ) -> list[ApprovalDecision]:
        n = max(1, min(500, int(limit or 50)))
        rows = self._approvals.list_history(limit=500, session_id=session_id)
        filtered: list[ApprovalDecision] = []
        for row in rows:
            try:
                session = self.fetch_session_for_principal(row.session_id, principal_id=principal_id)
            except PermissionError:
                continue
            if session is None:
                continue
            filtered.append(row)
            if len(filtered) >= n:
                break
        return filtered

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
            updated_step = self._ledger.update_step(
                request.step_id,
                state="queued",
                output_json={"approval_id": request.approval_id, "decision": "approved"},
                error_json={},
            )
            self._ledger.complete_session(request.session_id, status="running")
            self._ledger.append_event(
                request.session_id,
                "session_resumed_from_approval",
                {"approval_id": request.approval_id, "step_id": request.step_id},
            )
            if updated_step is not None:
                next_step = self._next_ready_step(request.session_id)
                if next_step is None:
                    raise RuntimeError(f"approved queue item did not resolve a ready step: {request.session_id}")
                queue_item = self._enqueue_rewrite_step(request.session_id, next_step.step_id)
                artifact = self.run_queue_item(queue_item.queue_id, lease_owner="inline")
                drained_artifact = self._drain_session_inline(request.session_id)
                if drained_artifact is not None:
                    artifact = drained_artifact
                if artifact is None:
                    snapshot = self.fetch_session(request.session_id)
                    if snapshot is not None:
                        if snapshot.session.status in {"awaiting_human", "awaiting_approval", "completed"}:
                            return request, decision_row
                        if self._delayed_retry_queue_item(snapshot) is not None:
                            return request, decision_row
                    raise RuntimeError(f"approved queue item did not execute: {queue_item.queue_id}")
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
        ensure_storage_fallback_allowed(settings, "execution ledger configured for memory")
        return InMemoryExecutionLedgerRepository()
    if backend == "postgres":
        if not settings.database_url:
            raise RuntimeError("EA_STORAGE_BACKEND=postgres requires DATABASE_URL")
        return PostgresExecutionLedgerRepository(settings.database_url)

    if settings.database_url:
        try:
            return PostgresExecutionLedgerRepository(settings.database_url)
        except Exception as exc:
            ensure_storage_fallback_allowed(settings, "execution ledger auto fallback", exc)
            log.warning("postgres ledger unavailable in auto mode; falling back to memory: %s", exc)
    ensure_storage_fallback_allowed(settings, "execution ledger auto backend without DATABASE_URL")
    return InMemoryExecutionLedgerRepository()


def build_policy_repo(settings: Settings) -> PolicyDecisionRepository:
    backend = _backend_mode(settings)
    log = logging.getLogger("ea.policy_repo")
    if backend == "memory":
        ensure_storage_fallback_allowed(settings, "policy repo configured for memory")
        return InMemoryPolicyDecisionRepository()
    if backend == "postgres":
        if not settings.database_url:
            raise RuntimeError("EA_STORAGE_BACKEND=postgres requires DATABASE_URL")
        return PostgresPolicyDecisionRepository(settings.database_url)
    if settings.database_url:
        try:
            return PostgresPolicyDecisionRepository(settings.database_url)
        except Exception as exc:
            ensure_storage_fallback_allowed(settings, "policy repo auto fallback", exc)
            log.warning("postgres policy backend unavailable in auto mode; falling back to memory: %s", exc)
    ensure_storage_fallback_allowed(settings, "policy repo auto backend without DATABASE_URL")
    return InMemoryPolicyDecisionRepository()


def build_approval_repo(settings: Settings) -> ApprovalRepository:
    backend = _backend_mode(settings)
    log = logging.getLogger("ea.approvals")
    if backend == "memory":
        ensure_storage_fallback_allowed(settings, "approvals configured for memory")
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
            ensure_storage_fallback_allowed(settings, "approvals auto fallback", exc)
            log.warning("postgres approval backend unavailable in auto mode; falling back to memory: %s", exc)
    ensure_storage_fallback_allowed(settings, "approvals auto backend without DATABASE_URL")
    return InMemoryApprovalRepository(default_ttl_minutes=settings.policy.approval_ttl_minutes)


def build_human_task_repo(settings: Settings) -> HumanTaskRepository:
    backend = _backend_mode(settings)
    log = logging.getLogger("ea.human_tasks")
    if backend == "memory":
        ensure_storage_fallback_allowed(settings, "human tasks configured for memory")
        return InMemoryHumanTaskRepository()
    if backend == "postgres":
        if not settings.database_url:
            raise RuntimeError("EA_STORAGE_BACKEND=postgres requires DATABASE_URL")
        return PostgresHumanTaskRepository(settings.database_url)
    if settings.database_url:
        try:
            return PostgresHumanTaskRepository(settings.database_url)
        except Exception as exc:
            ensure_storage_fallback_allowed(settings, "human tasks auto fallback", exc)
            log.warning("postgres human-task backend unavailable in auto mode; falling back to memory: %s", exc)
    ensure_storage_fallback_allowed(settings, "human tasks auto backend without DATABASE_URL")
    return InMemoryHumanTaskRepository()


def build_operator_profile_repo(settings: Settings) -> OperatorProfileRepository:
    backend = _backend_mode(settings)
    log = logging.getLogger("ea.operator_profiles")
    if backend == "memory":
        ensure_storage_fallback_allowed(settings, "operator profiles configured for memory")
        return InMemoryOperatorProfileRepository()
    if backend == "postgres":
        if not settings.database_url:
            raise RuntimeError("EA_STORAGE_BACKEND=postgres requires DATABASE_URL")
        return PostgresOperatorProfileRepository(settings.database_url)
    if settings.database_url:
        try:
            return PostgresOperatorProfileRepository(settings.database_url)
        except Exception as exc:
            ensure_storage_fallback_allowed(settings, "operator profiles auto fallback", exc)
            log.warning("postgres operator-profile backend unavailable in auto mode; falling back to memory: %s", exc)
    ensure_storage_fallback_allowed(settings, "operator profiles auto backend without DATABASE_URL")
    return InMemoryOperatorProfileRepository()


def build_artifact_repo(settings: Settings) -> ArtifactRepository:
    backend = _backend_mode(settings)
    log = logging.getLogger("ea.artifacts")
    if backend == "memory":
        ensure_storage_fallback_allowed(settings, "artifacts configured for memory")
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
            ensure_storage_fallback_allowed(settings, "artifacts auto fallback", exc)
            log.warning("postgres artifact backend unavailable in auto mode; falling back to memory: %s", exc)
    ensure_storage_fallback_allowed(settings, "artifacts auto backend without DATABASE_URL")
    return InMemoryArtifactRepository()


def build_default_orchestrator(
    settings: Settings | None = None,
    *,
    artifacts: ArtifactRepository | None = None,
    task_contracts: TaskContractService | None = None,
    planner: PlannerService | None = None,
    memory_runtime: MemoryRuntimeService | None = None,
    tool_execution: ToolExecutionService | None = None,
) -> RewriteOrchestrator:
    resolved = settings or get_settings()
    ledger = build_execution_ledger(resolved)
    policy_repo = build_policy_repo(resolved)
    approvals = build_approval_repo(resolved)
    human_tasks = build_human_task_repo(resolved)
    operator_profiles = build_operator_profile_repo(resolved)
    artifact_repo = artifacts or build_artifact_repo(resolved)
    task_contract_service = task_contracts or build_task_contract_service(resolved)
    planner_service = planner or PlannerService(task_contract_service)
    memory_service = memory_runtime or build_memory_runtime(resolved)
    policy = PolicyDecisionService(
        max_rewrite_chars=resolved.policy.max_rewrite_chars,
        approval_required_chars=resolved.policy.approval_required_chars,
    )
    return RewriteOrchestrator(
        artifacts=artifact_repo,
        ledger=ledger,
        policy_repo=policy_repo,
        approvals=approvals,
        human_tasks=human_tasks,
        operator_profiles=operator_profiles,
        policy=policy,
        task_contracts=task_contract_service,
        planner=planner_service,
        memory_runtime=memory_service,
        tool_execution=tool_execution or ToolExecutionService(artifacts=artifact_repo),
    )
