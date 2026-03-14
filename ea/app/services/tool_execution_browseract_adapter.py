from __future__ import annotations

import json
import os
import shlex
import subprocess
import urllib.error
import urllib.request
import uuid

from app.domain.models import ToolDefinition, ToolInvocationRequest, ToolInvocationResult, artifact_preview_text, now_utc_iso
from app.services.tool_execution_common import ToolExecutionError
from app.services.tool_execution_connector_dispatch_adapter import ConnectorDispatchToolAdapter


class BrowserActToolAdapter:
    def __init__(self, *, connector_dispatch: ConnectorDispatchToolAdapter) -> None:
        self._connector_dispatch = connector_dispatch

    def execute_extract(self, request: ToolInvocationRequest, definition: ToolDefinition) -> ToolInvocationResult:
        payload = dict(request.payload_json or {})
        service_name = str(payload.get("service_name") or "").strip()
        principal_id, binding = self._resolve_browseract_binding(
            request=request,
            payload=payload,
            required_input_error="connector_binding_required:browseract.extract_account_facts",
            required_scopes=(service_name,) if service_name else None,
        )
        if not service_name:
            raise ToolExecutionError("service_name_required:browseract.extract_account_facts")
        record = self._extract_service_record(
            binding_auth_metadata_json=dict(binding.auth_metadata_json or {}),
            payload=payload,
            service_name=service_name,
            requested_fields=self._requested_fields(payload),
            allow_missing=False,
        )
        action_kind = str(request.action_kind or "account.extract") or "account.extract"
        structured_output_json = dict(record["structured_output_json"])
        structured_output_json.update(
            {"binding_id": binding.binding_id, "connector_name": binding.connector_name, "external_account_ref": binding.external_account_ref}
        )
        return ToolInvocationResult(
            tool_name=definition.tool_name,
            action_kind=action_kind,
            target_ref=f"browseract:{binding.binding_id}:{service_name.lower().replace(' ', '_')}",
            output_json={
                "binding_id": binding.binding_id,
                "connector_name": binding.connector_name,
                "external_account_ref": binding.external_account_ref,
                "service_name": record["service_name"],
                "facts_json": record["facts_json"],
                "requested_fields": record["requested_fields"],
                "missing_fields": record["missing_fields"],
                "account_email": record["account_email"],
                "plan_tier": record["plan_tier"],
                "discovery_status": record["discovery_status"],
                "verification_source": record["verification_source"],
                "last_verified_at": record["last_verified_at"],
                "instructions": record["instructions"],
                "account_hints_json": record["account_hints_json"],
                "requested_run_url": record["requested_run_url"],
                "live_discovery_error": record["live_discovery_error"],
                "normalized_text": record["normalized_text"],
                "preview_text": record["preview_text"],
                "mime_type": record["mime_type"],
                "structured_output_json": structured_output_json,
                "tool_name": definition.tool_name,
                "action_kind": action_kind,
            },
            receipt_json={
                "binding_id": binding.binding_id,
                "connector_name": binding.connector_name,
                "external_account_ref": binding.external_account_ref,
                "handler_key": definition.tool_name,
                "invocation_contract": "tool.v1",
                "principal_id": principal_id,
                "service_name": record["service_name"],
                "requested_fields": record["requested_fields"],
                "missing_fields": record["missing_fields"],
                "discovery_status": record["discovery_status"],
                "verification_source": record["verification_source"],
                "requested_run_url": record["requested_run_url"],
                "live_discovery_error": record["live_discovery_error"],
                "tool_version": definition.version,
            },
        )

    def execute_inventory(self, request: ToolInvocationRequest, definition: ToolDefinition) -> ToolInvocationResult:
        payload = dict(request.payload_json or {})
        service_names = self._requested_service_names(payload)
        principal_id, binding = self._resolve_browseract_binding(
            request=request,
            payload=payload,
            required_input_error="connector_binding_required:browseract.extract_account_inventory",
            required_scopes=service_names,
        )
        if not service_names:
            service_names = self._configured_service_names(
                binding_auth_metadata_json=dict(binding.auth_metadata_json or {}),
                binding_scope_json=dict(binding.scope_json or {}),
            )
        if not service_names:
            raise ToolExecutionError("service_names_required:browseract.extract_account_inventory")
        requested_fields = self._requested_fields(payload)
        services_json = [
            self._extract_service_record(
                binding_auth_metadata_json=dict(binding.auth_metadata_json or {}),
                payload=payload,
                service_name=service_name,
                requested_fields=requested_fields,
                allow_missing=True,
            )
            for service_name in service_names
        ]
        missing_services = [str(row["service_name"]) for row in services_json if str(row["discovery_status"]) == "missing"]
        action_kind = str(request.action_kind or "account.extract_inventory") or "account.extract_inventory"
        normalized_text = self._inventory_summary_text(services_json)
        structured_output_json = {
            "service_names": list(service_names),
            "services_json": services_json,
            "missing_services": missing_services,
            "binding_id": binding.binding_id,
            "connector_name": binding.connector_name,
            "external_account_ref": binding.external_account_ref,
            "instructions": str(payload.get("instructions") or "").strip(),
            "account_hints_json": dict(payload.get("account_hints_json") or {}),
            "requested_run_url": str(payload.get("run_url") or "").strip(),
        }
        return ToolInvocationResult(
            tool_name=definition.tool_name,
            action_kind=action_kind,
            target_ref=f"browseract:{binding.binding_id}:inventory",
            output_json={
                "binding_id": binding.binding_id,
                "connector_name": binding.connector_name,
                "external_account_ref": binding.external_account_ref,
                "service_names": list(service_names),
                "services_json": services_json,
                "missing_services": missing_services,
                "instructions": structured_output_json["instructions"],
                "account_hints_json": structured_output_json["account_hints_json"],
                "requested_run_url": structured_output_json["requested_run_url"],
                "normalized_text": normalized_text,
                "preview_text": artifact_preview_text(normalized_text),
                "mime_type": "text/plain",
                "structured_output_json": structured_output_json,
                "tool_name": definition.tool_name,
                "action_kind": action_kind,
            },
            receipt_json={
                "binding_id": binding.binding_id,
                "connector_name": binding.connector_name,
                "external_account_ref": binding.external_account_ref,
                "handler_key": definition.tool_name,
                "invocation_contract": "tool.v1",
                "principal_id": principal_id,
                "service_names": list(service_names),
                "missing_services": missing_services,
                "requested_run_url": structured_output_json["requested_run_url"],
                "tool_version": definition.version,
            },
        )

    def execute_build_workflow_spec(self, request: ToolInvocationRequest, definition: ToolDefinition) -> ToolInvocationResult:
        payload = dict(request.payload_json or {})
        workflow_name = str(payload.get("workflow_name") or "").strip()
        purpose = str(payload.get("purpose") or "").strip()
        login_url = str(payload.get("login_url") or "").strip()
        tool_url = str(payload.get("tool_url") or "").strip()
        if not workflow_name:
            raise ToolExecutionError("workflow_name_required:browseract.build_workflow_spec")
        if not purpose:
            raise ToolExecutionError("purpose_required:browseract.build_workflow_spec")
        if not login_url:
            raise ToolExecutionError("login_url_required:browseract.build_workflow_spec")
        if not tool_url:
            raise ToolExecutionError("tool_url_required:browseract.build_workflow_spec")
        workflow_kind = str(payload.get("workflow_kind") or "prompt_tool").strip().lower() or "prompt_tool"
        if workflow_kind not in {"prompt_tool", "page_extract"}:
            raise ToolExecutionError(f"workflow_kind_invalid:browseract.build_workflow_spec:{workflow_kind}")
        runtime_input_name = str(payload.get("runtime_input_name") or "").strip()
        prompt_selector = str(payload.get("prompt_selector") or "textarea").strip() or "textarea"
        submit_selector = str(payload.get("submit_selector") or "button").strip() or "button"
        result_selector = str(payload.get("result_selector") or "main, body").strip() or "main, body"
        wait_selector = str(payload.get("wait_selector") or result_selector).strip() or result_selector
        title_selector = str(payload.get("title_selector") or "").strip()
        dismiss_selectors = self._normalize_string_list(payload.get("dismiss_selectors"))
        output_dir = str(payload.get("output_dir") or "/docker/fleet/state/browseract_bootstrap").strip() or "/docker/fleet/state/browseract_bootstrap"
        spec = self._build_workflow_spec(
            workflow_name=workflow_name,
            purpose=purpose,
            login_url=login_url,
            tool_url=tool_url,
            workflow_kind=workflow_kind,
            runtime_input_name=runtime_input_name,
            prompt_selector=prompt_selector,
            submit_selector=submit_selector,
            result_selector=result_selector,
            wait_selector=wait_selector,
            title_selector=title_selector,
            dismiss_selectors=dismiss_selectors,
            output_dir=output_dir,
        )
        slug = str(((spec.get("meta") or {}).get("slug")) or self._slugify(workflow_name))
        action_kind = str(request.action_kind or "workflow.spec_build") or "workflow.spec_build"
        normalized_text = "\n".join(
            [
                f"Workflow: {workflow_name}",
                f"Purpose: {purpose}",
                f"Kind: {workflow_kind}",
                f"Tool URL: {tool_url}",
                f"Runtime input: {runtime_input_name or '<none>'}",
                f"Prompt selector: {prompt_selector}",
                f"Submit selector: {submit_selector}",
                f"Result selector: {result_selector}",
                f"Wait selector: {wait_selector}",
                f"Title selector: {title_selector or '<none>'}",
                f"Dismiss selectors: {len(dismiss_selectors)}",
                f"Node count: {len(spec.get('nodes') or [])}",
                f"Edge count: {len(spec.get('edges') or [])}",
            ]
        )
        return ToolInvocationResult(
            tool_name=definition.tool_name,
            action_kind=action_kind,
            target_ref=f"browseract:workflow-spec:{slug}",
            output_json={
                "workflow_name": workflow_name,
                "workflow_slug": slug,
                "normalized_text": normalized_text,
                "preview_text": artifact_preview_text(normalized_text),
                "mime_type": "application/json",
                "structured_output_json": spec,
                "tool_name": definition.tool_name,
                "action_kind": action_kind,
            },
            receipt_json={
                "handler_key": definition.tool_name,
                "invocation_contract": "tool.v1",
                "workflow_name": workflow_name,
                "workflow_slug": slug,
                "tool_version": definition.version,
            },
        )

    def execute_repair_workflow_spec(self, request: ToolInvocationRequest, definition: ToolDefinition) -> ToolInvocationResult:
        payload = dict(request.payload_json or {})
        workflow_name = str(payload.get("workflow_name") or "").strip()
        purpose = str(payload.get("purpose") or "").strip()
        login_url = str(payload.get("login_url") or "public").strip() or "public"
        tool_url = str(payload.get("tool_url") or "").strip()
        failure_summary = str(payload.get("failure_summary") or payload.get("diagnosis") or "").strip()
        if not workflow_name:
            raise ToolExecutionError("workflow_name_required:browseract.repair_workflow_spec")
        if not purpose:
            raise ToolExecutionError("purpose_required:browseract.repair_workflow_spec")
        if not tool_url:
            raise ToolExecutionError("tool_url_required:browseract.repair_workflow_spec")
        if not failure_summary:
            raise ToolExecutionError("failure_summary_required:browseract.repair_workflow_spec")
        prompt_selector = str(payload.get("prompt_selector") or "textarea").strip() or "textarea"
        submit_selector = str(payload.get("submit_selector") or "button").strip() or "button"
        result_selector = str(payload.get("result_selector") or "main, body").strip() or "main, body"
        workflow_kind = str(payload.get("workflow_kind") or "prompt_tool").strip().lower() or "prompt_tool"
        runtime_input_name = str(payload.get("runtime_input_name") or "prompt").strip() or "prompt"
        wait_selector = str(payload.get("wait_selector") or result_selector).strip() or result_selector
        title_selector = str(payload.get("title_selector") or "").strip()
        dismiss_selectors = self._normalize_string_list(payload.get("dismiss_selectors"))
        output_dir = str(payload.get("output_dir") or "/docker/fleet/state/browseract_bootstrap").strip() or "/docker/fleet/state/browseract_bootstrap"
        scaffold = self._build_workflow_spec(
            workflow_name=workflow_name,
            purpose=purpose,
            login_url=login_url,
            tool_url=tool_url,
            workflow_kind=workflow_kind,
            runtime_input_name=runtime_input_name,
            prompt_selector=prompt_selector,
            submit_selector=submit_selector,
            result_selector=result_selector,
            wait_selector=wait_selector,
            title_selector=title_selector,
            dismiss_selectors=dismiss_selectors,
            output_dir=output_dir,
        )
        failure_goals = self._normalize_string_list(payload.get("failing_step_goals"))
        current_spec = payload.get("current_workflow_spec_json") if isinstance(payload.get("current_workflow_spec_json"), dict) else {}
        repair_prompt = self._build_workflow_repair_prompt(
            workflow_name=workflow_name,
            purpose=purpose,
            login_url=login_url,
            tool_url=tool_url,
            failure_summary=failure_summary,
            failure_goals=failure_goals,
            current_spec=current_spec if isinstance(current_spec, dict) else {},
            scaffold=scaffold,
        )
        envelope, model = self._run_gemini_repair_prompt(repair_prompt)
        packet = self._normalize_workflow_repair_packet(
            envelope,
            workflow_name=workflow_name,
            purpose=purpose,
            scaffold=scaffold,
            failure_summary=failure_summary,
            failure_goals=failure_goals,
        )
        slug = str((((packet.get("workflow_spec") or {}).get("meta") or {}).get("slug")) or self._slugify(workflow_name))
        normalized_text = "\n".join(
            [
                f"Workflow: {workflow_name}",
                f"Failure: {failure_summary}",
                f"Diagnosis: {packet.get('diagnosis', '')}",
                f"Repair strategy: {packet.get('repair_strategy', '')}",
                f"Node count: {len(((packet.get('workflow_spec') or {}).get('nodes') or []))}",
                f"Edge count: {len(((packet.get('workflow_spec') or {}).get('edges') or []))}",
            ]
        )
        action_kind = str(request.action_kind or "workflow.spec_repair") or "workflow.spec_repair"
        return ToolInvocationResult(
            tool_name=definition.tool_name,
            action_kind=action_kind,
            target_ref=f"browseract:workflow-repair:{slug}:{uuid.uuid4()}",
            output_json={
                "workflow_name": workflow_name,
                "workflow_slug": slug,
                "normalized_text": normalized_text,
                "preview_text": artifact_preview_text(normalized_text),
                "mime_type": "application/json",
                "structured_output_json": packet,
                "tool_name": definition.tool_name,
                "action_kind": action_kind,
            },
            receipt_json={
                "handler_key": definition.tool_name,
                "invocation_contract": "tool.v1",
                "workflow_name": workflow_name,
                "workflow_slug": slug,
                "failure_summary": failure_summary,
                "failure_goals": failure_goals,
                "model": model,
                "tool_version": definition.version,
            },
            model_name=model,
            cost_usd=0.0,
        )

    def _resolve_browseract_binding(
        self,
        *,
        request: ToolInvocationRequest,
        payload: dict[str, object],
        required_input_error: str,
        required_scopes: tuple[str, ...] | None,
    ):
        principal_id, binding = self._connector_dispatch.resolve_connector_binding(
            request=request,
            payload=payload,
            required_connector_name="browseract",
            required_input_error=required_input_error,
        )
        requested_scopes = self._connector_dispatch.normalised_scopes(required_scopes or ())
        if requested_scopes:
            configured_scopes = self._connector_dispatch.normalised_scopes(
                self._configured_service_names(
                    binding_auth_metadata_json=dict(binding.auth_metadata_json or {}),
                    binding_scope_json=dict(binding.scope_json or {}),
                )
            )
            if not set(requested_scopes).intersection(configured_scopes):
                raise ToolExecutionError(
                    f"connector_binding_scope_mismatch:{binding.binding_id}:{','.join(requested_scopes)}"
                )
        return principal_id, binding

    def _requested_fields(self, payload: dict[str, object]) -> tuple[str, ...]:
        raw = payload.get("requested_fields")
        if isinstance(raw, (list, tuple)):
            return tuple(str(value or "").strip() for value in raw if str(value or "").strip())
        if isinstance(raw, str) and raw.strip():
            return tuple(value.strip() for value in raw.split(",") if value.strip())
        return ()

    def _requested_service_names(self, payload: dict[str, object]) -> tuple[str, ...]:
        raw = payload.get("service_names")
        values: list[str] = []
        if isinstance(raw, (list, tuple)):
            values.extend(str(value or "").strip() for value in raw if str(value or "").strip())
        elif isinstance(raw, str) and raw.strip():
            values.extend(value.strip() for value in raw.split(",") if value.strip())
        if not values:
            single = str(payload.get("service_name") or "").strip()
            if single:
                values.append(single)
        ordered: list[str] = []
        seen: set[str] = set()
        for value in values:
            key = value.lower()
            if key in seen:
                continue
            seen.add(key)
            ordered.append(value)
        return tuple(ordered)

    def _configured_service_names(
        self,
        *,
        binding_auth_metadata_json: dict[str, object],
        binding_scope_json: dict[str, object],
    ) -> tuple[str, ...]:
        ordered: list[str] = []
        seen: set[str] = set()

        def add(value: object) -> None:
            normalized = str(value or "").strip()
            if not normalized:
                return
            key = normalized.lower()
            if key in seen:
                return
            seen.add(key)
            ordered.append(normalized)

        raw_scope_services = binding_scope_json.get("services")
        if isinstance(raw_scope_services, (list, tuple)):
            for value in raw_scope_services:
                add(value)
        raw_accounts = binding_auth_metadata_json.get("service_accounts_json")
        if isinstance(raw_accounts, dict):
            for key, value in raw_accounts.items():
                if isinstance(value, dict) and any(field in value for field in ("tier", "plan", "account_email", "email", "status")):
                    add(key)
                elif key in {"service_name", "service", "name"}:
                    add(value)
        elif isinstance(raw_accounts, list):
            for value in raw_accounts:
                if isinstance(value, dict):
                    add(value.get("service_name") or value.get("service") or value.get("name"))
        return tuple(ordered)

    def _slugify(self, value: str) -> str:
        cleaned = "".join(ch.lower() if ch.isalnum() else "_" for ch in str(value or ""))
        while "__" in cleaned:
            cleaned = cleaned.replace("__", "_")
        return cleaned.strip("_") or "adapter"

    def _build_workflow_spec(
        self,
        *,
        workflow_name: str,
        purpose: str,
        login_url: str,
        tool_url: str,
        workflow_kind: str,
        runtime_input_name: str,
        prompt_selector: str,
        submit_selector: str,
        result_selector: str,
        wait_selector: str,
        title_selector: str,
        dismiss_selectors: list[str],
        output_dir: str,
    ) -> dict[str, object]:
        slug = self._slugify(workflow_name)
        nodes: list[dict[str, object]] = []
        edges: list[list[str]] = []
        inputs: list[dict[str, str]] = []
        if login_url.lower() not in {"", "none", "public", "noauth"}:
            nodes.extend(
                [
                    {"id": "open_login", "type": "visit_page", "label": "Open Login", "config": {"url": login_url}},
                    {"id": "email", "type": "input_text", "label": "Email", "config": {"selector": "input[type=email]", "value_from_secret": "browseract_username"}},
                    {"id": "password", "type": "input_text", "label": "Password", "config": {"selector": "input[type=password]", "value_from_secret": "browseract_password"}},
                    {"id": "submit", "type": "click", "label": "Submit", "config": {"selector": "button[type=submit]"}},
                    {"id": "wait_dashboard", "type": "wait", "label": "Wait Dashboard", "config": {"selector": "body"}},
                ]
            )
            edges.extend(
                [
                    ["open_login", "email"],
                    ["email", "password"],
                    ["password", "submit"],
                    ["submit", "wait_dashboard"],
                    ["wait_dashboard", "open_tool"],
                ]
            )
        if workflow_kind == "page_extract":
            visit_config: dict[str, str] = {"url": tool_url}
            if runtime_input_name:
                visit_config = {"value_from_input": runtime_input_name}
                inputs.append(
                    {
                        "name": runtime_input_name,
                        "description": f"Target page URL for {workflow_name}.",
                    }
                )
            nodes.append({"id": "open_tool", "type": "visit_page", "label": "Open Target Page", "config": visit_config})
            last_node = "open_tool"
            for index, selector in enumerate(dismiss_selectors, start=1):
                node_id = f"dismiss_{index:02d}"
                nodes.append(
                    {
                        "id": node_id,
                        "type": "click",
                        "label": f"Dismiss Overlay {index}",
                        "config": {"selector": selector},
                    }
                )
                edges.append([last_node, node_id])
                last_node = node_id
            nodes.append({"id": "wait_content", "type": "wait", "label": "Wait Content", "config": {"selector": wait_selector}})
            edges.append([last_node, "wait_content"])
            last_node = "wait_content"
            if title_selector:
                nodes.append({"id": "extract_title", "type": "extract", "label": "Extract Title", "config": {"selector": title_selector}})
                edges.append([last_node, "extract_title"])
                last_node = "extract_title"
            nodes.append({"id": "extract_result", "type": "extract", "label": "Extract Result", "config": {"selector": result_selector}})
            edges.append([last_node, "extract_result"])
        else:
            inputs.append(
                {
                    "name": "prompt",
                    "description": f"Primary runtime prompt for {workflow_name}.",
                }
            )
            nodes.extend(
                [
                    {"id": "open_tool", "type": "visit_page", "label": "Open Tool", "config": {"url": tool_url}},
                    {"id": "input_prompt", "type": "input_text", "label": "Input Prompt", "config": {"selector": prompt_selector, "value_from_input": "prompt"}},
                    {"id": "generate", "type": "click", "label": "Generate", "config": {"selector": submit_selector}},
                    {"id": "extract_result", "type": "extract", "label": "Extract Result", "config": {"selector": result_selector}},
                ]
            )
            edges.extend(
                [
                    ["open_tool", "input_prompt"],
                    ["input_prompt", "generate"],
                    ["generate", "extract_result"],
                ]
            )
        return {
            "workflow_name": workflow_name,
            "description": purpose,
            "publish": True,
            "mcp_ready": False,
            "inputs": inputs,
            "nodes": nodes,
            "edges": edges,
            "meta": {
                "slug": slug,
                "output_dir": output_dir,
                "status": "pending_browseract_seed",
                "workflow_kind": workflow_kind,
            },
        }

    def _normalize_string_list(self, raw: object) -> list[str]:
        values: list[str] = []
        if isinstance(raw, (list, tuple, set)):
            values.extend(str(value or "").strip() for value in raw if str(value or "").strip())
        elif isinstance(raw, str) and raw.strip():
            values.extend(part.strip() for part in raw.split("|") if part.strip())
        deduped: list[str] = []
        seen: set[str] = set()
        for value in values:
            key = value.casefold()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(value)
        return deduped

    def _gemini_command_base(self) -> list[str]:
        raw = str(os.environ.get("EA_GEMINI_VORTEX_COMMAND") or "gemini").strip() or "gemini"
        return shlex.split(raw)

    def _gemini_model(self) -> str:
        return str(os.environ.get("EA_GEMINI_VORTEX_MODEL") or "gemini-3-flash-preview").strip() or "gemini-3-flash-preview"

    def _gemini_timeout_seconds(self) -> int:
        raw = str(os.environ.get("EA_GEMINI_VORTEX_TIMEOUT_SECONDS") or "180").strip() or "180"
        try:
            return max(15, int(raw))
        except Exception:
            return 180

    def _strip_fences(self, text: str) -> str:
        raw = str(text or "").strip()
        if raw.startswith("```"):
            raw = raw.removeprefix("```json").removeprefix("```").strip()
        if raw.endswith("```"):
            raw = raw[:-3].strip()
        return raw

    def _run_gemini_repair_prompt(self, prompt: str) -> tuple[dict[str, object], str]:
        model = self._gemini_model()
        command = self._gemini_command_base() + [
            "-p",
            prompt,
            "--output-format",
            "json",
            "--approval-mode",
            "yolo",
        ]
        if model:
            command.extend(["-m", model])
        try:
            completed = subprocess.run(
                command,
                check=True,
                text=True,
                capture_output=True,
                timeout=self._gemini_timeout_seconds(),
            )
        except FileNotFoundError as exc:
            raise ToolExecutionError("gemini_vortex_cli_missing:browseract.repair_workflow_spec") from exc
        except subprocess.TimeoutExpired as exc:
            raise ToolExecutionError("gemini_vortex_timeout:browseract.repair_workflow_spec") from exc
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or "").strip()
            raise ToolExecutionError(f"gemini_vortex_failed:browseract.repair_workflow_spec:{detail[:400]}") from exc
        raw = str(completed.stdout or "").strip()
        if not raw:
            raise ToolExecutionError("gemini_vortex_empty_output:browseract.repair_workflow_spec")
        try:
            envelope = json.loads(raw)
        except Exception:
            envelope = {"response": raw}
        response = envelope.get("response") if isinstance(envelope, dict) else raw
        cleaned = self._strip_fences(str(response or raw))
        try:
            loaded = json.loads(cleaned)
        except Exception as exc:
            raise ToolExecutionError("gemini_vortex_non_json:browseract.repair_workflow_spec") from exc
        if not isinstance(loaded, dict):
            raise ToolExecutionError("gemini_vortex_non_object:browseract.repair_workflow_spec")
        return loaded, model

    def _build_workflow_repair_prompt(
        self,
        *,
        workflow_name: str,
        purpose: str,
        login_url: str,
        tool_url: str,
        failure_summary: str,
        failure_goals: list[str],
        current_spec: dict[str, object],
        scaffold: dict[str, object],
    ) -> str:
        schema = {
            "type": "object",
            "required": ["diagnosis", "repair_strategy", "workflow_spec"],
            "properties": {
                "diagnosis": {"type": "string"},
                "repair_strategy": {"type": "string"},
                "operator_checks": {"type": "array", "items": {"type": "string"}},
                "workflow_spec": {
                    "type": "object",
                    "required": ["workflow_name", "description", "publish", "mcp_ready", "nodes", "edges", "meta"],
                    "properties": {
                        "workflow_name": {"type": "string"},
                        "description": {"type": "string"},
                        "publish": {"type": "boolean"},
                        "mcp_ready": {"type": "boolean"},
                        "nodes": {"type": "array"},
                        "edges": {"type": "array"},
                        "meta": {"type": "object"},
                    },
                },
            },
        }
        return "\n\n".join(
            [
                "Return JSON only. No markdown fences or commentary.",
                "You are repairing a BrowserAct workflow spec after a runtime failure.",
                "Goal: produce a repaired workflow spec packet that keeps the intended workflow name and purpose but fixes the observed execution failure.",
                "Rules:",
                "- use Gemini judgment, not generic filler",
                "- keep the workflow grounded in actual BrowserAct node types like visit_page, input_text, click, wait, extract",
                "- preserve runtime input bindings when present; do not literalize placeholders like /text",
                "- if the evidence says a value_from_input binding was typed literally, repair the node config so BrowserAct treats it as a runtime input",
                "- keep publish true and mcp_ready false unless evidence clearly requires otherwise",
                "- keep nodes and edges compact and executable",
                "- operator_checks should be 2 to 4 short human verification checks",
                "Schema contract:\n" + json.dumps(schema, ensure_ascii=True),
                "Workflow brief:\n"
                + json.dumps(
                    {
                        "workflow_name": workflow_name,
                        "purpose": purpose,
                        "login_url": login_url,
                        "tool_url": tool_url,
                        "failure_summary": failure_summary,
                        "failing_step_goals": failure_goals,
                        "current_workflow_spec_json": current_spec,
                        "fallback_scaffold_spec_json": scaffold,
                    },
                    ensure_ascii=True,
                ),
            ]
        ).strip()

    def _normalize_workflow_repair_packet(
        self,
        raw: dict[str, object],
        *,
        workflow_name: str,
        purpose: str,
        scaffold: dict[str, object],
        failure_summary: str,
        failure_goals: list[str],
    ) -> dict[str, object]:
        packet = dict(raw)
        diagnosis = str(packet.get("diagnosis") or failure_summary).strip() or failure_summary
        repair_strategy = str(packet.get("repair_strategy") or "Repair the BrowserAct workflow spec to preserve runtime input binding and result extraction.").strip()
        operator_checks = self._normalize_string_list(packet.get("operator_checks"))[:4]
        workflow_spec = packet.get("workflow_spec")
        if not isinstance(workflow_spec, dict):
            workflow_spec = packet if isinstance(packet.get("nodes"), list) and isinstance(packet.get("edges"), list) else {}
        spec = dict(scaffold)
        spec.update({key: value for key, value in dict(workflow_spec).items() if key in {"workflow_name", "description", "publish", "mcp_ready", "nodes", "edges", "meta"}})
        spec["workflow_name"] = str(spec.get("workflow_name") or workflow_name).strip() or workflow_name
        spec["description"] = str(spec.get("description") or purpose).strip() or purpose
        spec["publish"] = bool(spec.get("publish", True))
        spec["mcp_ready"] = bool(spec.get("mcp_ready", False))
        nodes = spec.get("nodes")
        edges = spec.get("edges")
        if not isinstance(nodes, list) or not nodes:
            raise ToolExecutionError("workflow_nodes_required:browseract.repair_workflow_spec")
        if not isinstance(edges, list) or not edges:
            raise ToolExecutionError("workflow_edges_required:browseract.repair_workflow_spec")
        meta = dict(spec.get("meta") or {})
        meta["slug"] = str(meta.get("slug") or self._slugify(spec["workflow_name"])).strip() or self._slugify(spec["workflow_name"])
        meta["status"] = str(meta.get("status") or "pending_browseract_repair").strip() or "pending_browseract_repair"
        meta["repair_failure_summary"] = failure_summary
        meta["repair_failure_goals"] = failure_goals
        meta["repair_generated_at"] = now_utc_iso()
        meta["repair_source"] = "gemini_vortex"
        spec["meta"] = meta
        return {
            "diagnosis": diagnosis,
            "repair_strategy": repair_strategy,
            "operator_checks": operator_checks,
            "workflow_spec": spec,
        }

    def _service_facts(self, *, binding_auth_metadata_json: dict[str, object], service_name: str) -> dict[str, object] | None:
        normalized_service_name = str(service_name or "").strip().lower()
        raw = binding_auth_metadata_json.get("service_accounts_json")
        if isinstance(raw, dict):
            for key, value in raw.items():
                if str(key or "").strip().lower() != normalized_service_name:
                    continue
                if isinstance(value, dict):
                    return {str(entry_key): entry_value for entry_key, entry_value in value.items()}
                return {"value": value}
            if str(raw.get("service_name") or raw.get("service") or raw.get("name") or "").strip().lower() == normalized_service_name:
                return {str(key): value for key, value in raw.items()}
        if isinstance(raw, list):
            for value in raw:
                if not isinstance(value, dict):
                    continue
                candidate_name = str(value.get("service_name") or value.get("service") or value.get("name") or "").strip()
                if candidate_name.lower() != normalized_service_name:
                    continue
                return {str(key): entry_value for key, entry_value in value.items()}
        return None

    def _configured_api_key(self) -> str:
        for key_name in ("BROWSERACT_API_KEY", "BROWSERACT_API_KEY_FALLBACK_1", "BROWSERACT_API_KEY_FALLBACK_2", "BROWSERACT_API_KEY_FALLBACK_3"):
            value = str(os.getenv(key_name) or "").strip()
            if value:
                return value
        return ""

    def _live_extract(
        self,
        *,
        binding_auth_metadata_json: dict[str, object],
        payload: dict[str, object],
        service_name: str,
        requested_fields: tuple[str, ...],
    ) -> dict[str, object] | None:
        run_url = str(payload.get("run_url") or binding_auth_metadata_json.get("browseract_run_url") or binding_auth_metadata_json.get("run_url") or "").strip()
        api_key = self._configured_api_key()
        if not run_url or not api_key:
            return None
        request_body = {
            "service_name": service_name,
            "requested_fields": list(requested_fields),
            "instructions": str(payload.get("instructions") or binding_auth_metadata_json.get("instructions") or ""),
            "account_hints_json": dict(payload.get("account_hints_json") or {}),
        }
        request = urllib.request.Request(
            run_url,
            data=json.dumps(request_body).encode("utf-8"),
            headers={"authorization": f"Bearer {api_key}", "content-type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                body = json.loads(response.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            raise ToolExecutionError(f"browseract_live_http_error:{exc.code}") from exc
        except urllib.error.URLError as exc:
            raise ToolExecutionError(f"browseract_live_transport_error:{exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise ToolExecutionError("browseract_live_response_invalid") from exc
        candidates = (
            body.get("facts_json") if isinstance(body, dict) else None,
            ((body.get("data") or {}).get("facts_json")) if isinstance(body, dict) and isinstance(body.get("data"), dict) else None,
            ((body.get("result") or {}).get("facts_json")) if isinstance(body, dict) and isinstance(body.get("result"), dict) else None,
            ((body.get("output") or {}).get("facts_json")) if isinstance(body, dict) and isinstance(body.get("output"), dict) else None,
        )
        for candidate in candidates:
            if isinstance(candidate, dict):
                return {str(key): value for key, value in candidate.items()} | {"verification_source": "browseract_live"}
        if isinstance(body, dict):
            return {str(key): value for key, value in body.items()} | {"verification_source": "browseract_live"}
        raise ToolExecutionError("browseract_live_response_invalid")

    def _fact_present(self, value: object) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, (list, tuple, dict, set)):
            return bool(value)
        return True

    def _summary_text(
        self,
        *,
        service_name: str,
        facts_json: dict[str, object],
        requested_fields: tuple[str, ...],
        missing_fields: tuple[str, ...],
        verification_source: str,
        last_verified_at: str,
    ) -> str:
        ordered_keys = requested_fields or tuple(key for key in facts_json.keys() if key not in {"service_name", "verification_source"})
        lines = [f"Service: {service_name}", f"Verification source: {verification_source}", f"Last verified at: {last_verified_at}"]
        for key in ordered_keys:
            value = facts_json.get(key)
            lines.append(f"{key}: {value}" if self._fact_present(value) else f"{key}: <missing>")
        if missing_fields:
            lines.append(f"Missing fields: {', '.join(missing_fields)}")
        return "\n".join(lines)

    def _inventory_summary_text(self, services_json: list[dict[str, object]]) -> str:
        summaries = [str((row.get("normalized_text") or "")).strip() for row in services_json if str((row.get("normalized_text") or "")).strip()]
        if not summaries:
            return "No BrowserAct-backed service inventory facts were discovered."
        return "\n\n".join(summaries)

    def _extract_service_record(
        self,
        *,
        binding_auth_metadata_json: dict[str, object],
        payload: dict[str, object],
        service_name: str,
        requested_fields: tuple[str, ...],
        allow_missing: bool,
    ) -> dict[str, object]:
        facts_json = self._service_facts(binding_auth_metadata_json=binding_auth_metadata_json, service_name=service_name)
        live_discovery_error = ""
        if facts_json is None:
            try:
                live_facts_json = self._live_extract(
                    binding_auth_metadata_json=binding_auth_metadata_json,
                    payload=payload,
                    service_name=service_name,
                    requested_fields=requested_fields,
                )
            except ToolExecutionError as exc:
                live_discovery_error = str(exc)
                live_facts_json = None
            if live_facts_json is not None:
                facts_json = dict(live_facts_json)
        elif requested_fields:
            try:
                live_facts_json = self._live_extract(
                    binding_auth_metadata_json=binding_auth_metadata_json,
                    payload=payload,
                    service_name=service_name,
                    requested_fields=requested_fields,
                )
            except ToolExecutionError as exc:
                live_discovery_error = str(exc)
                live_facts_json = None
            if live_facts_json is not None:
                merged_facts_json = {str(key): value for key, value in facts_json.items()}
                for key, value in live_facts_json.items():
                    if self._fact_present(value):
                        merged_facts_json[str(key)] = value
                facts_json = merged_facts_json
        verification_source = "connector_metadata"
        if facts_json is None:
            if not allow_missing:
                raise ToolExecutionError(f"browseract_service_not_found:{service_name}")
            facts_json = {}
            verification_source = "missing"
        else:
            verification_source = str(facts_json.pop("verification_source", "") or "connector_metadata").strip() or "connector_metadata"
        normalized_facts_json = {str(key): value for key, value in facts_json.items()}
        normalized_facts_json.setdefault("service_name", service_name)
        resolved_requested_fields = requested_fields or tuple(key for key in normalized_facts_json.keys() if key != "service_name")
        if not resolved_requested_fields and allow_missing:
            resolved_requested_fields = ("tier", "account_email", "status")
        missing_fields = tuple(key for key in resolved_requested_fields if not self._fact_present(normalized_facts_json.get(key)))
        account_email = str(normalized_facts_json.get("account_email") or normalized_facts_json.get("email") or normalized_facts_json.get("login_email") or "").strip()
        plan_tier = str(normalized_facts_json.get("tier") or normalized_facts_json.get("plan") or normalized_facts_json.get("plan_tier") or normalized_facts_json.get("license_tier") or "").strip()
        last_verified_at = now_utc_iso()
        discovery_status = "missing" if verification_source == "missing" else ("complete" if resolved_requested_fields and not missing_fields else "partial")
        normalized_text = self._summary_text(
            service_name=service_name,
            facts_json=normalized_facts_json,
            requested_fields=resolved_requested_fields,
            missing_fields=missing_fields,
            verification_source=verification_source,
            last_verified_at=last_verified_at,
        )
        instructions = str(payload.get("instructions") or binding_auth_metadata_json.get("instructions") or "").strip()
        account_hints_json = dict(payload.get("account_hints_json") or {})
        requested_run_url = str(payload.get("run_url") or binding_auth_metadata_json.get("browseract_run_url") or binding_auth_metadata_json.get("run_url") or "").strip()
        structured_output_json = {
            "service_name": service_name,
            "facts_json": normalized_facts_json,
            "requested_fields": list(resolved_requested_fields),
            "missing_fields": list(missing_fields),
            "discovery_status": discovery_status,
            "verification_source": verification_source,
            "last_verified_at": last_verified_at,
            "account_email": account_email,
            "plan_tier": plan_tier,
            "instructions": instructions,
            "account_hints_json": account_hints_json,
            "requested_run_url": requested_run_url,
            "live_discovery_error": live_discovery_error,
        }
        return {
            "service_name": service_name,
            "facts_json": normalized_facts_json,
            "requested_fields": list(resolved_requested_fields),
            "missing_fields": list(missing_fields),
            "account_email": account_email,
            "plan_tier": plan_tier,
            "discovery_status": discovery_status,
            "verification_source": verification_source,
            "last_verified_at": last_verified_at,
            "instructions": instructions,
            "account_hints_json": account_hints_json,
            "requested_run_url": requested_run_url,
            "live_discovery_error": live_discovery_error,
            "normalized_text": normalized_text,
            "preview_text": artifact_preview_text(normalized_text),
            "mime_type": "text/plain",
            "structured_output_json": structured_output_json,
        }
