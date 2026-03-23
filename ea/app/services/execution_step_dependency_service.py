from __future__ import annotations

import difflib
from typing import Callable

from app.domain.models import ExecutionStep


class ExecutionStepDependencyService:
    def __init__(
        self,
        *,
        get_step: Callable[[str], ExecutionStep | None],
        steps_for_session: Callable[[str], list[ExecutionStep]],
    ) -> None:
        self._get_step = get_step
        self._steps_for_session = steps_for_session

    def step_dependency_keys(self, row: ExecutionStep) -> tuple[str, ...]:
        raw = (row.input_json or {}).get("depends_on") or ()
        if isinstance(raw, (list, tuple)):
            values = tuple(str(value or "").strip() for value in raw if str(value or "").strip())
            if values:
                return values
        if row.parent_step_id:
            return (f"step-id:{row.parent_step_id}",)
        return ()

    def dependency_lookup(self, steps: list[ExecutionStep]) -> dict[str, ExecutionStep]:
        lookup: dict[str, ExecutionStep] = {}
        for row in steps:
            step_key = str((row.input_json or {}).get("plan_step_key") or "").strip()
            if step_key:
                lookup[step_key] = row
            lookup[f"step-id:{row.step_id}"] = row
        return lookup

    def dependency_steps_for_step(self, session_id: str, rewrite_step: ExecutionStep) -> list[ExecutionStep]:
        steps = self._steps_for_session(session_id)
        lookup = self.dependency_lookup(steps)
        resolved: list[ExecutionStep] = []
        seen: set[str] = set()
        for key in self.step_dependency_keys(rewrite_step):
            row = lookup.get(key)
            if row is None or row.step_id in seen:
                continue
            resolved.append(row)
            seen.add(row.step_id)
        if not resolved and rewrite_step.parent_step_id:
            parent_step = self._get_step(rewrite_step.parent_step_id)
            if parent_step is not None:
                resolved.append(parent_step)
        return resolved

    def approval_target_step_for_session(self, session_id: str) -> ExecutionStep | None:
        steps = self._steps_for_session(session_id)
        return next(
            (
                row
                for row in reversed(steps)
                if bool((row.input_json or {}).get("approval_required")) or row.step_kind == "tool_call"
            ),
            steps[0] if steps else None,
        )

    def declared_step_input_keys(self, rewrite_step: ExecutionStep) -> tuple[str, ...]:
        raw = (rewrite_step.input_json or {}).get("input_keys") or ()
        if isinstance(raw, (list, tuple)):
            values = tuple(str(value or "").strip() for value in raw if str(value or "").strip())
            if values:
                return values
        return ()

    def declared_step_output_keys(self, rewrite_step: ExecutionStep) -> tuple[str, ...]:
        raw = (rewrite_step.input_json or {}).get("output_keys") or ()
        if isinstance(raw, (list, tuple)):
            values = tuple(str(value or "").strip() for value in raw if str(value or "").strip())
            if values:
                return values
        return ()

    def validate_step_input_contract(
        self,
        rewrite_step: ExecutionStep,
        input_json: dict[str, object],
    ) -> dict[str, object]:
        plan_step_key = str((rewrite_step.input_json or {}).get("plan_step_key") or rewrite_step.step_kind or "")
        for key in self.declared_step_input_keys(rewrite_step):
            if key not in input_json:
                raise RuntimeError(f"missing_step_input:{plan_step_key}:{key}")
        return input_json

    def validate_step_output_contract(
        self,
        rewrite_step: ExecutionStep,
        output_json: dict[str, object],
    ) -> dict[str, object]:
        plan_step_key = str((rewrite_step.input_json or {}).get("plan_step_key") or rewrite_step.step_kind or "")
        for key in self.declared_step_output_keys(rewrite_step):
            if key not in output_json:
                raise RuntimeError(f"missing_step_output:{plan_step_key}:{key}")
        return output_json

    def merged_step_input_json(self, session_id: str, rewrite_step: ExecutionStep) -> dict[str, object]:
        input_json = dict(rewrite_step.input_json or {})
        declared_input_keys = set(self.declared_step_input_keys(rewrite_step))
        for dependency in self.dependency_steps_for_step(session_id, rewrite_step):
            for key, value in dict(dependency.output_json or {}).items():
                if not declared_input_keys or key in declared_input_keys:
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
        if "diff_text" in declared_input_keys and "diff_text" not in input_json:
            normalized_text = str(input_json.get("normalized_text") or "").strip()
            diff_lines = list(
                difflib.unified_diff(
                    source_text.splitlines(),
                    normalized_text.splitlines(),
                    fromfile="source",
                    tofile="normalized",
                    lineterm="",
                )
            )
            input_json["diff_text"] = "\n".join(diff_lines)
        optional_defaults: dict[str, object] = {
            "requested_fields": [],
            "service_names": [],
            "instructions": "",
            "account_hints_json": {},
            "run_url": "",
        }
        for key, default in optional_defaults.items():
            if key in declared_input_keys and key not in input_json:
                input_json[key] = list(default) if isinstance(default, list) else dict(default) if isinstance(default, dict) else default
        if not str(input_json.get("content") or "").strip():
            content = str(input_json.get("normalized_text") or input_json.get("source_text") or "").strip()
            if content:
                input_json["content"] = content
        return self.validate_step_input_contract(rewrite_step, input_json)
