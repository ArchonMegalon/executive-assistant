from __future__ import annotations

from dataclasses import dataclass

from app.domain.models import ExecutionQueueItem, ExecutionSession, ExecutionStep
from app.services.provider_registry import ProviderRegistryService
from app.services.tool_execution_common import ToolExecutionError


@dataclass(frozen=True)
class ReplanResult:
    new_step_id: str
    replacement_tool_name: str
    capability_key: str
    replan_attempts: int


class ReplanningService:
    def __init__(
        self,
        *,
        get_session,
        get_step,
        start_step,
        enqueue_step,
        set_session_status,
        append_event,
        provider_registry: ProviderRegistryService,
    ) -> None:
        self._get_session = get_session
        self._get_step = get_step
        self._start_step = start_step
        self._enqueue_step = enqueue_step
        self._set_session_status = set_session_status
        self._append_event = append_event
        self._provider_registry = provider_registry

    def request_replan(self, queue_item: ExecutionQueueItem, rewrite_step: ExecutionStep, exc: Exception) -> ReplanResult | None:
        session = self._get_session(queue_item.session_id)
        if session is None or rewrite_step.step_kind != "tool_call":
            return None
        input_json = dict(rewrite_step.input_json or {})
        replan_attempts = max(0, int(input_json.get("replan_attempts") or 0))
        replan_max_attempts = max(1, int(input_json.get("replan_max_attempts") or 2))
        if replan_attempts >= replan_max_attempts:
            self._append_event(
                session.session_id,
                "step_replan_exhausted",
                {
                    "step_id": rewrite_step.step_id,
                    "plan_step_key": str(input_json.get("plan_step_key") or ""),
                    "replan_attempts": replan_attempts,
                    "replan_max_attempts": replan_max_attempts,
                },
            )
            return None
        failed_tool_name = str(input_json.get("tool_name") or "").strip()
        if not failed_tool_name:
            return None
        capability_key = self._capability_key_for_step(session=session, rewrite_step=rewrite_step, failed_tool_name=failed_tool_name)
        if not capability_key:
            return None
        replacement_tool_name = self._replacement_tool_name(
            session=session,
            capability_key=capability_key,
            failed_tool_name=failed_tool_name,
        )
        if not replacement_tool_name:
            self._append_event(
                session.session_id,
                "step_replan_unavailable",
                {
                    "step_id": rewrite_step.step_id,
                    "failed_tool_name": failed_tool_name,
                    "capability_key": capability_key,
                },
            )
            return None
        replacement_input_json = dict(input_json)
        replacement_input_json["tool_name"] = replacement_tool_name
        replacement_input_json["capability_key"] = capability_key
        replacement_input_json["replan_attempts"] = replan_attempts + 1
        replacement_input_json["replan_max_attempts"] = replan_max_attempts
        replacement_input_json["replan_from_step_id"] = rewrite_step.step_id
        replacement_input_json["replan_from_tool_name"] = failed_tool_name
        replacement_input_json["replan_last_error"] = str(exc)
        self._set_session_status(session.session_id, "replanning")
        self._append_event(
            session.session_id,
            "session_replanning",
            {
                "queue_id": queue_item.queue_id,
                "failed_step_id": rewrite_step.step_id,
                "failed_tool_name": failed_tool_name,
                "replacement_tool_name": replacement_tool_name,
                "capability_key": capability_key,
            },
        )
        replacement_step = self._start_step(
            session.session_id,
            rewrite_step.step_kind,
            parent_step_id=rewrite_step.parent_step_id,
            input_json=replacement_input_json,
            correlation_id=rewrite_step.correlation_id,
            causation_id=rewrite_step.step_id,
            actor_type="system",
            actor_id="replanner",
            state="queued",
        )
        self._enqueue_step(
            session.session_id,
            replacement_step.step_id,
            idempotency_key=f"rewrite:{session.session_id}:{replacement_step.step_id}",
        )
        self._set_session_status(session.session_id, "queued")
        self._append_event(
            session.session_id,
            "step_replanned",
            {
                "queue_id": queue_item.queue_id,
                "failed_step_id": rewrite_step.step_id,
                "replacement_step_id": replacement_step.step_id,
                "failed_tool_name": failed_tool_name,
                "replacement_tool_name": replacement_tool_name,
                "capability_key": capability_key,
                "replan_attempts": replan_attempts + 1,
            },
        )
        return ReplanResult(
            new_step_id=replacement_step.step_id,
            replacement_tool_name=replacement_tool_name,
            capability_key=capability_key,
            replan_attempts=replan_attempts + 1,
        )

    def _capability_key_for_step(
        self,
        *,
        session: ExecutionSession,
        rewrite_step: ExecutionStep,
        failed_tool_name: str,
    ) -> str:
        explicit = str((rewrite_step.input_json or {}).get("capability_key") or "").strip()
        if explicit:
            return explicit
        try:
            route = self._provider_registry.route_tool_with_context(
                failed_tool_name,
                principal_id=session.intent.principal_id,
            )
        except ToolExecutionError:
            return ""
        return str(route.capability_key or "").strip()

    def _replacement_tool_name(
        self,
        *,
        session: ExecutionSession,
        capability_key: str,
        failed_tool_name: str,
    ) -> str:
        candidate_routes = self._provider_registry.candidate_routes_by_capability_with_context(
            capability_key=capability_key,
            principal_id=session.intent.principal_id,
            allowed_tools=tuple(session.intent.allowed_tools or ()),
            require_executable=True,
        )
        for route in candidate_routes:
            tool_name = str(route.tool_name or "").strip()
            if tool_name and tool_name != failed_tool_name:
                return tool_name
        return ""
