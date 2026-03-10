from __future__ import annotations

from typing import Callable

from app.domain.models import (
    Artifact,
    ExecutionSession,
    ExecutionStep,
    PolicyDecision,
    ToolInvocationRequest,
    artifact_preview_text,
)
from app.services.execution_approval_pause_service import ExecutionApprovalPauseService
from app.services.execution_human_task_step_service import ExecutionHumanTaskStepService
from app.services.execution_step_dependency_service import ExecutionStepDependencyService
from app.services.memory_runtime import MemoryRuntimeService
from app.services.policy import PolicyDecisionService
from app.services.tool_execution import ToolExecutionService


class ExecutionStepRuntimeService:
    def __init__(
        self,
        *,
        get_session: Callable[[str], ExecutionSession | None],
        get_artifact: Callable[[str], Artifact | None],
        update_step: Callable[[str, ...], ExecutionStep | None],
        append_event: Callable[[str, str, dict[str, object]], object],
        append_policy_decision: Callable[[str, PolicyDecision], object],
        append_tool_receipt: Callable[..., object],
        append_run_cost: Callable[..., object],
        set_session_status: Callable[[str, str], object],
        approval_target_step_for_session: Callable[[str], ExecutionStep | None],
        step_dependency_service: ExecutionStepDependencyService,
        approval_pause_service: ExecutionApprovalPauseService,
        human_task_step_service: ExecutionHumanTaskStepService,
        policy: PolicyDecisionService,
        tool_execution: ToolExecutionService,
        memory_runtime: MemoryRuntimeService | None,
    ) -> None:
        self._get_session = get_session
        self._get_artifact = get_artifact
        self._update_step = update_step
        self._append_event = append_event
        self._append_policy_decision = append_policy_decision
        self._append_tool_receipt = append_tool_receipt
        self._append_run_cost = append_run_cost
        self._set_session_status = set_session_status
        self._approval_target_step_for_session = approval_target_step_for_session
        self._step_dependency_service = step_dependency_service
        self._approval_pause_service = approval_pause_service
        self._human_task_step_service = human_task_step_service
        self._policy = policy
        self._tool_execution = tool_execution
        self._memory_runtime = memory_runtime

    def complete_input_prepare_step(self, session_id: str, rewrite_step: ExecutionStep) -> None:
        input_json = self._step_dependency_service.merged_step_input_json(session_id, rewrite_step)
        source_text = str(input_json.get("source_text") or "").strip()
        plan_id = str(input_json.get("plan_id") or "")
        plan_step_key = str(input_json.get("plan_step_key") or "")
        desired_output_json = dict((rewrite_step.input_json or {}).get("desired_output_json") or {})
        output_json = {
            "normalized_text": source_text,
            "text_length": len(source_text),
            "plan_id": plan_id,
            "plan_step_key": plan_step_key,
        }
        artifact_output_template = str(
            desired_output_json.get("artifact_output_template")
            or input_json.get("artifact_output_template")
            or ""
        ).strip()
        if artifact_output_template == "evidence_pack":
            claims = [str(value or "").strip() for value in (input_json.get("claims") or []) if str(value or "").strip()]
            evidence_refs = [
                str(value or "").strip()
                for value in (input_json.get("evidence_refs") or input_json.get("context_refs") or [])
                if str(value or "").strip()
            ]
            open_questions = [
                str(value or "").strip()
                for value in (input_json.get("open_questions") or [])
                if str(value or "").strip()
            ]
            confidence_value = input_json.get("confidence")
            if confidence_value is None:
                confidence_value = desired_output_json.get("default_confidence")
            try:
                confidence = float(confidence_value if confidence_value is not None else 0.5)
            except (TypeError, ValueError):
                confidence = 0.5
            confidence = min(max(confidence, 0.0), 1.0)
            output_json.update(
                {
                    "structured_output_json": {
                        "format": "evidence_pack",
                        "claims": claims,
                        "evidence_refs": evidence_refs,
                        "open_questions": open_questions,
                        "confidence": confidence,
                    },
                    "preview_text": artifact_preview_text(source_text),
                    "mime_type": str(input_json.get("mime_type") or "text/plain") or "text/plain",
                }
            )
        output_json = self._step_dependency_service.validate_step_output_contract(rewrite_step, output_json)
        self._update_step(
            rewrite_step.step_id,
            state="completed",
            output_json=output_json,
            error_json={},
        )
        self._append_event(
            session_id,
            "input_prepared",
            {
                "step_id": rewrite_step.step_id,
                "text_length": len(source_text),
                "plan_id": plan_id,
                "plan_step_key": plan_step_key,
            },
        )

    def complete_policy_evaluate_step(self, session_id: str, rewrite_step: ExecutionStep) -> None:
        session = self._get_session(session_id)
        if session is None:
            raise RuntimeError(f"session missing for policy step: {session_id}")
        input_json = self._step_dependency_service.merged_step_input_json(session_id, rewrite_step)
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
        self._append_policy_decision(session_id, decision)
        self._append_event(
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
        for key in ("structured_output_json", "preview_text", "mime_type"):
            if key in input_json:
                output_json[key] = input_json[key]
        output_json = self._step_dependency_service.validate_step_output_contract(rewrite_step, output_json)
        self._update_step(
            rewrite_step.step_id,
            state="completed",
            output_json=output_json,
            error_json={},
        )
        self._append_event(
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
                self._update_step(
                    rewrite_step.step_id,
                    state="blocked",
                    output_json=output_json,
                    error_json={"reason": decision.reason},
                )
            else:
                self._update_step(
                    target_step.step_id,
                    state="blocked",
                    output_json=target_step.output_json,
                    error_json={"reason": decision.reason},
                )
            self._set_session_status(session_id, "blocked")
            self._append_event(session_id, "session_blocked", {"reason": decision.reason})
            return
        if decision.requires_approval and target_step is not None and target_step.step_id != rewrite_step.step_id:
            self._approval_pause_service.pause_for_approval(
                session_id=session_id,
                target_step=target_step,
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

    def start_human_task_step(self, session_id: str, rewrite_step: ExecutionStep):
        return self._human_task_step_service.start_human_task_step(session_id, rewrite_step)

    def complete_tool_step(self, session_id: str, rewrite_step: ExecutionStep) -> Artifact | None:
        input_json = self._step_dependency_service.merged_step_input_json(session_id, rewrite_step)
        session = self._get_session(session_id)
        tool_name = str(input_json.get("tool_name") or "artifact_repository") or "artifact_repository"
        action_kind = str(input_json.get("action_kind") or "artifact.save") or "artifact.save"
        self._append_event(
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
        receipt = self._append_tool_receipt(
            session_id,
            rewrite_step.step_id,
            tool_name=result.tool_name,
            action_kind=result.action_kind,
            target_ref=result.target_ref,
            receipt_json=result.receipt_json,
        )
        cost = self._append_run_cost(
            session_id,
            model_name=result.model_name,
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
            cost_usd=result.cost_usd,
        )
        output_json = dict(result.output_json or {})
        output_json.setdefault("receipt_id", receipt.receipt_id)
        output_json.setdefault("cost_id", cost.cost_id)
        output_json = self._step_dependency_service.validate_step_output_contract(rewrite_step, output_json)
        self._update_step(
            rewrite_step.step_id,
            state="completed",
            output_json=output_json,
            error_json={},
        )
        self._append_event(
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
            self._append_event(
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

    def complete_memory_candidate_step(self, session_id: str, rewrite_step: ExecutionStep) -> None:
        session = self._get_session(session_id)
        if session is None:
            raise RuntimeError(f"session missing for memory step: {session_id}")
        if self._memory_runtime is None:
            raise RuntimeError("memory_runtime_unavailable")
        input_json = self._step_dependency_service.merged_step_input_json(session_id, rewrite_step)
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
        artifact_structured_output_json: dict[str, object] = {}
        if artifact_id:
            artifact = self._get_artifact(artifact_id)
            artifact_content = str((artifact.content if artifact is not None else "") or "").strip()
            if artifact_content:
                normalized_text = artifact_content
            artifact_structured_output_json = dict(((artifact.structured_output_json if artifact is not None else {}) or {}))
        delivery_id = str(input_json.get("delivery_id") or "").strip()
        delivery_status = str(input_json.get("status") or "").strip()
        binding_id = str(input_json.get("binding_id") or "").strip()
        channel = str(input_json.get("channel") or "").strip()
        recipient = str(input_json.get("recipient") or "").strip()
        if not memory_write_allowed or session.intent.memory_write_policy == "none":
            output_json = self._step_dependency_service.validate_step_output_contract(
                rewrite_step,
                {
                    "candidate_id": "",
                    "candidate_status": "skipped",
                    "candidate_category": category,
                },
            )
            self._update_step(
                rewrite_step.step_id,
                state="completed",
                output_json=output_json,
                error_json={},
            )
            self._append_event(
                session_id,
                "memory_candidate_skipped",
                {"step_id": rewrite_step.step_id, "candidate_category": category},
            )
            return
        summary = normalized_text[:4000]
        fact_json = {
            "artifact_id": artifact_id,
            "deliverable_type": session.intent.deliverable_type,
            "task_key": session.intent.task_type,
            "normalized_text": normalized_text,
            "delivery_id": delivery_id,
            "delivery_status": delivery_status,
            "binding_id": binding_id,
            "channel": channel,
            "recipient": recipient,
        }
        if str(artifact_structured_output_json.get("format") or "").strip() == "evidence_pack":
            fact_json.update(
                {
                    "evidence_pack": artifact_structured_output_json,
                    "claims": list(artifact_structured_output_json.get("claims") or []),
                    "evidence_refs": list(artifact_structured_output_json.get("evidence_refs") or []),
                    "open_questions": list(artifact_structured_output_json.get("open_questions") or []),
                }
            )
        evidence_object_id = str(input_json.get("evidence_object_id") or "").strip()
        citation_handle = str(input_json.get("citation_handle") or "").strip()
        if evidence_object_id:
            fact_json["evidence_object_id"] = evidence_object_id
        if citation_handle:
            fact_json["citation_handle"] = citation_handle
        candidate = self._memory_runtime.stage_candidate(
            principal_id=session.intent.principal_id,
            category=category,
            summary=summary,
            fact_json=fact_json,
            source_session_id=session_id,
            source_step_id=rewrite_step.step_id,
            confidence=confidence,
            sensitivity=sensitivity,
        )
        output_json = self._step_dependency_service.validate_step_output_contract(
            rewrite_step,
            {
                "candidate_id": candidate.candidate_id,
                "candidate_status": candidate.status,
                "candidate_category": candidate.category,
            },
        )
        self._update_step(
            rewrite_step.step_id,
            state="completed",
            output_json=output_json,
            error_json={},
        )
        self._append_event(
            session_id,
            "memory_candidate_staged",
            {
                "step_id": rewrite_step.step_id,
                "candidate_id": candidate.candidate_id,
                "candidate_category": candidate.category,
            },
        )

    def execute_step(self, session_id: str, rewrite_step: ExecutionStep) -> Artifact | None:
        plan_step_key = str((rewrite_step.input_json or {}).get("plan_step_key") or "")
        if plan_step_key == "step_input_prepare":
            self.complete_input_prepare_step(session_id, rewrite_step)
            return None
        if plan_step_key == "step_policy_evaluate" or rewrite_step.step_kind == "policy_check":
            self.complete_policy_evaluate_step(session_id, rewrite_step)
            return None
        if plan_step_key == "step_human_review" or rewrite_step.step_kind == "human_task":
            self.start_human_task_step(session_id, rewrite_step)
            return None
        if plan_step_key == "step_memory_candidate_stage" or rewrite_step.step_kind == "memory_write":
            self.complete_memory_candidate_step(session_id, rewrite_step)
            return None
        if rewrite_step.step_kind == "tool_call":
            return self.complete_tool_step(session_id, rewrite_step)
        raise RuntimeError(f"unsupported_step_handler:{plan_step_key or rewrite_step.step_kind}")
