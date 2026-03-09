from __future__ import annotations

import json
import os
import uuid
import urllib.error
import urllib.request
from typing import Callable

from app.domain.models import (
    Artifact,
    ToolDefinition,
    ToolInvocationRequest,
    ToolInvocationResult,
    artifact_preview_text,
    normalize_artifact,
    now_utc_iso,
)
from app.repositories.artifacts import ArtifactRepository, InMemoryArtifactRepository
from app.repositories.connector_bindings import InMemoryConnectorBindingRepository
from app.repositories.tool_registry import InMemoryToolRegistryRepository
from app.services.channel_runtime import ChannelRuntimeService
from app.services.evidence_runtime import EvidenceRuntimeService
from app.services.tool_runtime import ToolRuntimeService

ToolExecutionHandler = Callable[[ToolInvocationRequest, ToolDefinition], ToolInvocationResult]

CONNECTOR_DISPATCH_REQUIRED_INPUT_FIELDS = ("binding_id", "channel", "recipient", "content")
CONNECTOR_DISPATCH_OPTIONAL_INPUT_FIELDS = ("metadata", "idempotency_key")
CONNECTOR_DISPATCH_ALLOWED_CHANNELS = ("email", "slack", "telegram")
CONNECTOR_DISPATCH_IDEMPOTENCY_POLICY = "optional_passthrough"
CONNECTOR_CHANNEL_SCOPE_REQUIREMENTS = {
    "email": ("mail.send", "email.send", "send.mail"),
    "slack": ("chat.write", "chat.post", "slack.send", "slack.post"),
    "telegram": ("telegram.send", "telegram.post", "send.telegram"),
}


class ToolExecutionError(RuntimeError):
    pass


class ToolExecutionService:
    def __init__(
        self,
        *,
        tool_runtime: ToolRuntimeService | None = None,
        artifacts: ArtifactRepository | None = None,
        channel_runtime: ChannelRuntimeService | None = None,
        evidence_runtime: EvidenceRuntimeService | None = None,
    ) -> None:
        self._artifacts = artifacts or InMemoryArtifactRepository()
        self._channel_runtime = channel_runtime
        self._evidence_runtime = evidence_runtime
        self._tool_runtime = tool_runtime or ToolRuntimeService(
            tool_registry=InMemoryToolRegistryRepository(),
            connector_bindings=InMemoryConnectorBindingRepository(),
        )
        self._handlers: dict[str, ToolExecutionHandler] = {}
        self._register_builtin_artifact_repository()
        self._register_builtin_browseract_extract()
        self._register_builtin_browseract_inventory()
        self._register_builtin_connector_dispatch()

    def register_handler(self, tool_name: str, handler: ToolExecutionHandler) -> None:
        key = str(tool_name or "").strip()
        if not key:
            raise ValueError("tool_name is required")
        self._handlers[key] = handler

    def execute_invocation(self, request: ToolInvocationRequest) -> ToolInvocationResult:
        tool_name = str(request.tool_name or "").strip()
        if not tool_name:
            raise ToolExecutionError("tool_name_required")
        definition = self._tool_runtime.get_tool(tool_name)
        if definition is None:
            self._ensure_builtin_tool_registered(tool_name)
            definition = self._tool_runtime.get_tool(tool_name)
        if definition is None:
            raise ToolExecutionError(f"tool_not_registered:{tool_name}")
        if not definition.enabled:
            raise ToolExecutionError(f"tool_disabled:{tool_name}")
        handler = self._handlers.get(tool_name)
        if handler is None:
            raise ToolExecutionError(f"tool_handler_missing:{tool_name}")
        return handler(request, definition)

    def _ensure_builtin_tool_registered(self, tool_name: str) -> None:
        key = str(tool_name or "").strip()
        if key == "artifact_repository":
            self._register_builtin_artifact_repository()
            return
        if key == "browseract.extract_account_facts":
            self._register_builtin_browseract_extract()
            return
        if key == "browseract.extract_account_inventory":
            self._register_builtin_browseract_inventory()
            return
        if key == "connector.dispatch":
            self._register_builtin_connector_dispatch()

    def _register_builtin_artifact_repository(self) -> None:
        if self._tool_runtime.get_tool("artifact_repository") is None:
            self._tool_runtime.upsert_tool(
                tool_name="artifact_repository",
                version="v1",
                input_schema_json={
                    "type": "object",
                    "required": ["source_text"],
                    "properties": {
                        "source_text": {"type": "string"},
                        "expected_artifact": {"type": "string"},
                        "plan_id": {"type": "string"},
                        "plan_step_key": {"type": "string"},
                    },
                },
                output_schema_json={
                    "type": "object",
                    "required": ["artifact_id", "artifact_kind", "tool_name", "action_kind"],
                },
                policy_json={"builtin": True, "action_kind": "artifact.save"},
                approval_default="none",
                enabled=True,
            )
        self.register_handler("artifact_repository", self._execute_artifact_repository)

    def _register_builtin_browseract_extract(self) -> None:
        if self._tool_runtime.get_tool("browseract.extract_account_facts") is None:
            self._tool_runtime.upsert_tool(
                tool_name="browseract.extract_account_facts",
                version="v1",
                input_schema_json={
                    "type": "object",
                    "required": ["binding_id", "service_name"],
                    "properties": {
                        "binding_id": {"type": "string"},
                        "service_name": {"type": "string"},
                        "requested_fields": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "run_url": {"type": "string"},
                        "instructions": {"type": "string"},
                        "account_hints_json": {"type": "object"},
                    },
                },
                output_schema_json={
                    "type": "object",
                    "required": ["service_name", "facts_json", "missing_fields", "tool_name", "action_kind"],
                },
                policy_json={"builtin": True, "action_kind": "account.extract"},
                approval_default="none",
                enabled=True,
            )
        self.register_handler("browseract.extract_account_facts", self._execute_browseract_extract)

    def _register_builtin_browseract_inventory(self) -> None:
        if self._tool_runtime.get_tool("browseract.extract_account_inventory") is None:
            self._tool_runtime.upsert_tool(
                tool_name="browseract.extract_account_inventory",
                version="v1",
                input_schema_json={
                    "type": "object",
                    "required": ["binding_id"],
                    "properties": {
                        "binding_id": {"type": "string"},
                        "service_names": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "requested_fields": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "run_url": {"type": "string"},
                        "instructions": {"type": "string"},
                        "account_hints_json": {"type": "object"},
                    },
                },
                output_schema_json={
                    "type": "object",
                    "required": ["service_names", "services_json", "tool_name", "action_kind"],
                },
                policy_json={"builtin": True, "action_kind": "account.extract_inventory"},
                approval_default="none",
                enabled=True,
            )
        self.register_handler("browseract.extract_account_inventory", self._execute_browseract_inventory)

    def _register_builtin_connector_dispatch(self) -> None:
        if self._channel_runtime is None:
            return
        if self._tool_runtime.get_tool("connector.dispatch") is None:
            self._tool_runtime.upsert_tool(
                tool_name="connector.dispatch",
                version="v1",
                input_schema_json={
                    "type": "object",
                    "required": list(CONNECTOR_DISPATCH_REQUIRED_INPUT_FIELDS),
                    "properties": {
                        "binding_id": {"type": "string"},
                        "channel": {"type": "string"},
                        "recipient": {"type": "string"},
                        "content": {"type": "string"},
                        "metadata": {"type": "object"},
                        "idempotency_key": {"type": "string"},
                    },
                },
                output_schema_json={
                    "type": "object",
                    "required": ["delivery_id", "status", "tool_name", "action_kind"],
                },
                policy_json={
                    "builtin": True,
                    "action_kind": "delivery.send",
                    "idempotency_key_policy": CONNECTOR_DISPATCH_IDEMPOTENCY_POLICY,
                },
                allowed_channels=CONNECTOR_DISPATCH_ALLOWED_CHANNELS,
                approval_default="manager",
                enabled=True,
            )
        self.register_handler("connector.dispatch", self._execute_connector_dispatch)

    def _browseract_requested_fields(self, payload: dict[str, object]) -> tuple[str, ...]:
        raw = payload.get("requested_fields")
        if isinstance(raw, (list, tuple)):
            return tuple(str(value or "").strip() for value in raw if str(value or "").strip())
        if isinstance(raw, str) and raw.strip():
            return tuple(value.strip() for value in raw.split(",") if value.strip())
        return ()

    def _browseract_requested_service_names(self, payload: dict[str, object]) -> tuple[str, ...]:
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

    def _browseract_configured_service_names(
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
                if isinstance(value, dict) and any(
                    field in value for field in ("tier", "plan", "account_email", "email", "status")
                ):
                    add(key)
                elif key in {"service_name", "service", "name"}:
                    add(value)
        elif isinstance(raw_accounts, list):
            for value in raw_accounts:
                if not isinstance(value, dict):
                    continue
                add(value.get("service_name") or value.get("service") or value.get("name"))
        return tuple(ordered)

    def _browseract_service_facts(
        self,
        *,
        binding_auth_metadata_json: dict[str, object],
        service_name: str,
    ) -> dict[str, object] | None:
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

    def _browseract_configured_api_key(self) -> str:
        for key_name in (
            "BROWSERACT_API_KEY",
            "BROWSERACT_API_KEY_FALLBACK_1",
            "BROWSERACT_API_KEY_FALLBACK_2",
            "BROWSERACT_API_KEY_FALLBACK_3",
        ):
            value = str(os.getenv(key_name) or "").strip()
            if value:
                return value
        return ""

    def _browseract_live_extract(
        self,
        *,
        binding_auth_metadata_json: dict[str, object],
        payload: dict[str, object],
        service_name: str,
        requested_fields: tuple[str, ...],
    ) -> dict[str, object] | None:
        run_url = str(
            payload.get("run_url")
            or binding_auth_metadata_json.get("browseract_run_url")
            or binding_auth_metadata_json.get("run_url")
            or ""
        ).strip()
        api_key = self._browseract_configured_api_key()
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
            headers={
                "authorization": f"Bearer {api_key}",
                "content-type": "application/json",
            },
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

    def _browseract_fact_present(self, value: object) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, (list, tuple, dict, set)):
            return bool(value)
        return True

    def _browseract_summary_text(
        self,
        *,
        service_name: str,
        facts_json: dict[str, object],
        requested_fields: tuple[str, ...],
        missing_fields: tuple[str, ...],
        verification_source: str,
        last_verified_at: str,
    ) -> str:
        ordered_keys = requested_fields or tuple(
            key for key in facts_json.keys() if key not in {"service_name", "verification_source"}
        )
        lines = [
            f"Service: {service_name}",
            f"Verification source: {verification_source}",
            f"Last verified at: {last_verified_at}",
        ]
        for key in ordered_keys:
            value = facts_json.get(key)
            if not self._browseract_fact_present(value):
                lines.append(f"{key}: <missing>")
            else:
                lines.append(f"{key}: {value}")
        if missing_fields:
            lines.append(f"Missing fields: {', '.join(missing_fields)}")
        return "\n".join(lines)

    def _browseract_inventory_summary_text(self, services_json: list[dict[str, object]]) -> str:
        summaries = [str((row.get("normalized_text") or "")).strip() for row in services_json if str((row.get("normalized_text") or "")).strip()]
        if not summaries:
            return "No BrowserAct-backed service inventory facts were discovered."
        return "\n\n".join(summaries)

    def _resolve_browseract_binding(
        self,
        request: ToolInvocationRequest,
        payload: dict[str, object],
        *,
        required_input_error: str = "connector_binding_required:browseract.extract_account_facts",
        required_scopes: tuple[str, ...] | None = None,
    ):
        principal_id, binding = self._resolve_connector_binding(
            request=request,
            payload=payload,
            required_connector_name="browseract",
            required_input_error=required_input_error,
        )
        requested_scopes = self._normalized_connector_scopes(required_scopes or ())
        if requested_scopes:
            configured_scopes = self._normalised_scopes(
                self._browseract_configured_service_names(
                    binding_auth_metadata_json=dict(binding.auth_metadata_json or {}),
                    binding_scope_json=dict(binding.scope_json or {}),
                )
            )
            if not set(requested_scopes).intersection(configured_scopes):
                raise ToolExecutionError(
                    f"connector_binding_scope_mismatch:{binding.binding_id}:{','.join(requested_scopes)}"
                )
        return principal_id, binding

    def _resolve_connector_binding_principal(
        self,
        request: ToolInvocationRequest,
        payload: dict[str, object],
    ) -> str:
        request_principal_id = str((request.context_json or {}).get("principal_id") or "").strip()
        if not request_principal_id:
            raise ToolExecutionError("principal_id_required")
        supplied_principal_id = str(payload.get("principal_id") or "").strip()
        if supplied_principal_id and supplied_principal_id != request_principal_id:
            raise ToolExecutionError("principal_scope_mismatch")
        return request_principal_id

    def _resolve_connector_binding(
        self,
        request: ToolInvocationRequest,
        payload: dict[str, object],
        *,
        required_connector_name: str | None = None,
        required_input_error: str = "connector_binding_required:connector.dispatch",
        required_scopes: tuple[str, ...] | None = None,
    ):
        principal_id = self._resolve_connector_binding_principal(request, payload)
        binding_id = str(payload.get("binding_id") or "").strip()
        if not binding_id:
            raise ToolExecutionError(required_input_error)
        binding = self._tool_runtime.get_connector_binding(binding_id)
        if binding is None:
            raise ToolExecutionError(f"connector_binding_not_found:{binding_id}")
        binding_principal_id = str(binding.principal_id or "").strip()
        if str(binding.status or "").strip().lower() != "enabled":
            raise ToolExecutionError(f"connector_binding_disabled:{binding_id}")
        if binding_principal_id != principal_id:
            raise ToolExecutionError("principal_scope_mismatch")
        if required_connector_name:
            expected = str(required_connector_name or "").strip().lower()
            if str(binding.connector_name or "").strip().lower() != expected:
                raise ToolExecutionError(f"connector_binding_connector_mismatch:{binding_id}")
        requested_scopes = self._normalized_connector_scopes(required_scopes or ())
        if requested_scopes:
            configured_scopes = self._configured_connector_scopes(binding.scope_json)
            if not set(requested_scopes).intersection(configured_scopes):
                raise ToolExecutionError(
                    f"connector_binding_scope_mismatch:{binding_id}:{','.join(requested_scopes)}"
                )
        return principal_id, binding

    def _normalized_connector_scopes(self, scopes: tuple[str, ...] | list[str] | set[str]) -> tuple[str, ...]:
        normalized = {str(scope or "").strip().lower() for scope in scopes}
        return tuple(sorted(value for value in normalized if value))

    def _configured_connector_scopes(self, scope_json: dict[str, object]) -> tuple[str, ...]:
        raw = scope_json.get("scopes")
        values = ()
        if isinstance(raw, (list, tuple)):
            values = tuple(str(value or "").strip() for value in raw)
        return self._normalised_scopes(values)

    def _channel_dispatch_scopes(self, channel: str) -> tuple[str, ...]:
        normalized_channel = str(channel or "").strip().lower()
        return self._normalised_scopes(
            CONNECTOR_CHANNEL_SCOPE_REQUIREMENTS.get(normalized_channel, (normalized_channel + ".send",))
        )

    def _normalised_scopes(self, scopes: tuple[str, ...] | list[str] | set[str]) -> tuple[str, ...]:
        normalized: set[str] = set()
        for scope in scopes:
            value = str(scope or "").strip().lower()
            if not value:
                continue
            normalized.add(value)
            if value.startswith("channel:"):
                normalized.add(value.split(":", 1)[-1])
            if value == "mail.send":
                normalized.update(("email", "email.send"))
            if value == "chat.post":
                normalized.update(("slack", "chat.write"))
            if value == "telegram.send":
                normalized.add("telegram")
            if value.endswith(".send"):
                normalized.add(value.rsplit(".", 1)[0])
        return tuple(sorted(normalized))

    def _normalized_allowed_channels(self, definition: ToolDefinition) -> tuple[str, ...]:
        values = {str(raw or "").strip().lower() for raw in definition.allowed_channels}
        return tuple(sorted(value for value in values if value))

    def _browseract_extract_service_record(
        self,
        *,
        binding_auth_metadata_json: dict[str, object],
        payload: dict[str, object],
        service_name: str,
        requested_fields: tuple[str, ...],
        allow_missing: bool,
    ) -> dict[str, object]:
        facts_json = self._browseract_service_facts(
            binding_auth_metadata_json=binding_auth_metadata_json,
            service_name=service_name,
        )
        live_discovery_error = ""
        should_try_live = facts_json is None
        if not should_try_live and requested_fields:
            should_try_live = any(
                not self._browseract_fact_present((facts_json or {}).get(key))
                for key in requested_fields
            )
        if should_try_live:
            live_facts_json: dict[str, object] | None
            try:
                live_facts_json = self._browseract_live_extract(
                    binding_auth_metadata_json=binding_auth_metadata_json,
                    payload=payload,
                    service_name=service_name,
                    requested_fields=requested_fields,
                )
            except ToolExecutionError as exc:
                live_discovery_error = str(exc or "").strip()
                live_facts_json = None
                if facts_json is None and not allow_missing:
                    raise
            if live_facts_json is not None:
                if facts_json is None:
                    facts_json = live_facts_json
                else:
                    merged_facts_json = {str(key): value for key, value in facts_json.items()}
                    for key, value in live_facts_json.items():
                        if self._browseract_fact_present(value):
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
        resolved_requested_fields = requested_fields or tuple(
            key for key in normalized_facts_json.keys() if key != "service_name"
        )
        if not resolved_requested_fields and allow_missing:
            resolved_requested_fields = ("tier", "account_email", "status")
        missing_fields = tuple(
            key for key in resolved_requested_fields if not self._browseract_fact_present(normalized_facts_json.get(key))
        )
        account_email = str(
            normalized_facts_json.get("account_email")
            or normalized_facts_json.get("email")
            or normalized_facts_json.get("login_email")
            or ""
        ).strip()
        plan_tier = str(
            normalized_facts_json.get("tier")
            or normalized_facts_json.get("plan")
            or normalized_facts_json.get("plan_tier")
            or normalized_facts_json.get("license_tier")
            or ""
        ).strip()
        last_verified_at = now_utc_iso()
        if verification_source == "missing":
            discovery_status = "missing"
        else:
            discovery_status = "complete" if resolved_requested_fields and not missing_fields else "partial"
        live_instructions = str(payload.get("instructions") or binding_auth_metadata_json.get("instructions") or "").strip()
        account_hints_json = dict(payload.get("account_hints_json") or {})
        requested_run_url = str(
            payload.get("run_url")
            or binding_auth_metadata_json.get("browseract_run_url")
            or binding_auth_metadata_json.get("run_url")
            or ""
        ).strip()
        normalized_text = self._browseract_summary_text(
            service_name=service_name,
            facts_json=normalized_facts_json,
            requested_fields=resolved_requested_fields,
            missing_fields=missing_fields,
            verification_source=verification_source,
            last_verified_at=last_verified_at,
        )
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
            "instructions": live_instructions,
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
            "instructions": live_instructions,
            "account_hints_json": account_hints_json,
            "requested_run_url": requested_run_url,
            "live_discovery_error": live_discovery_error,
            "normalized_text": normalized_text,
            "preview_text": artifact_preview_text(normalized_text),
            "mime_type": "text/plain",
            "structured_output_json": structured_output_json,
        }

    def _execute_artifact_repository(
        self,
        request: ToolInvocationRequest,
        definition: ToolDefinition,
    ) -> ToolInvocationResult:
        payload = dict(request.payload_json or {})
        principal_id = str((request.context_json or {}).get("principal_id") or "").strip()
        if not principal_id:
            raise ToolExecutionError("principal_id_required")
        source_text = str(payload.get("normalized_text") or payload.get("source_text") or "").strip()
        artifact_kind = str(payload.get("expected_artifact") or "rewrite_note")
        plan_id = str(payload.get("plan_id") or "")
        plan_step_key = str(payload.get("plan_step_key") or "")
        artifact = normalize_artifact(Artifact(
            artifact_id=str(uuid.uuid4()),
            kind=artifact_kind,
            content=source_text,
            execution_session_id=request.session_id,
            principal_id=principal_id,
            mime_type=str(payload.get("mime_type") or "text/plain") or "text/plain",
            preview_text=str(payload.get("preview_text") or ""),
            body_ref=str(payload.get("body_ref") or ""),
            structured_output_json=dict(payload.get("structured_output_json") or {}),
            attachments_json=dict(payload.get("attachments_json") or {}),
        ))
        self._artifacts.save(artifact)
        evidence_object = self._evidence_runtime.record_artifact(artifact) if self._evidence_runtime is not None else None
        evidence_object_id = str(evidence_object.evidence_id if evidence_object is not None else "")
        citation_handle = str(evidence_object.citation_handle if evidence_object is not None else "")
        return ToolInvocationResult(
            tool_name=definition.tool_name,
            action_kind=str(request.action_kind or "artifact.save") or "artifact.save",
            target_ref=artifact.artifact_id,
            output_json={
                "artifact_id": artifact.artifact_id,
                "artifact_kind": artifact.kind,
                "content_length": len(source_text),
                "mime_type": artifact.mime_type,
                "preview_text": artifact.preview_text,
                "storage_handle": artifact.storage_handle,
                "body_ref": artifact.body_ref,
                "structured_output_json": dict(artifact.structured_output_json or {}),
                "attachments_json": dict(artifact.attachments_json or {}),
                "plan_id": plan_id,
                "plan_step_key": plan_step_key,
                "principal_id": artifact.principal_id,
                "evidence_object_id": evidence_object_id,
                "citation_handle": citation_handle,
                "tool_name": definition.tool_name,
                "action_kind": str(request.action_kind or "artifact.save") or "artifact.save",
            },
            receipt_json={
                "artifact_kind": artifact.kind,
                "content_length": len(source_text),
                "mime_type": artifact.mime_type,
                "body_ref": artifact.body_ref,
                "handler_key": definition.tool_name,
                "invocation_contract": "tool.v1",
                "plan_id": plan_id,
                "plan_step_key": plan_step_key,
                "principal_id": artifact.principal_id,
                "evidence_object_id": evidence_object_id,
                "citation_handle": citation_handle,
                "tool_version": definition.version,
            },
            artifacts=(artifact,),
        )

    def _execute_browseract_extract(
        self,
        request: ToolInvocationRequest,
        definition: ToolDefinition,
    ) -> ToolInvocationResult:
        payload = dict(request.payload_json or {})
        service_name = str(payload.get("service_name") or "").strip()
        principal_id, binding = self._resolve_browseract_binding(
            request,
            payload,
            required_input_error="connector_binding_required:browseract.extract_account_facts",
            required_scopes=(service_name,)
            if service_name
            else None,
        )
        if not service_name:
            raise ToolExecutionError("service_name_required:browseract.extract_account_facts")
        requested_fields = self._browseract_requested_fields(payload)
        record = self._browseract_extract_service_record(
            binding_auth_metadata_json=dict(binding.auth_metadata_json or {}),
            payload=payload,
            service_name=service_name,
            requested_fields=requested_fields,
            allow_missing=False,
        )
        action_kind = str(request.action_kind or "account.extract") or "account.extract"
        structured_output_json = dict(record["structured_output_json"])
        structured_output_json.update(
            {
                "binding_id": binding.binding_id,
                "connector_name": binding.connector_name,
                "external_account_ref": binding.external_account_ref,
            }
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

    def _execute_browseract_inventory(
        self,
        request: ToolInvocationRequest,
        definition: ToolDefinition,
    ) -> ToolInvocationResult:
        payload = dict(request.payload_json or {})
        service_names = self._browseract_requested_service_names(payload)
        principal_id, binding = self._resolve_browseract_binding(
            request,
            payload,
            required_input_error="connector_binding_required:browseract.extract_account_inventory",
            required_scopes=tuple(service_names),
        )
        requested_fields = self._browseract_requested_fields(payload)
        if not service_names:
            service_names = self._browseract_configured_service_names(
                binding_auth_metadata_json=dict(binding.auth_metadata_json or {}),
                binding_scope_json=dict(binding.scope_json or {}),
            )
        if not service_names:
            raise ToolExecutionError("service_names_required:browseract.extract_account_inventory")
        services_json = [
            self._browseract_extract_service_record(
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
        normalized_text = self._browseract_inventory_summary_text(services_json)
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

    def _execute_connector_dispatch(
        self,
        request: ToolInvocationRequest,
        definition: ToolDefinition,
    ) -> ToolInvocationResult:
        if self._channel_runtime is None:
            raise ToolExecutionError("channel_runtime_unavailable:connector.dispatch")
        payload = dict(request.payload_json or {})
        channel = str(payload.get("channel") or "").strip()
        normalized_channel = channel.lower()
        allowed_channels = self._normalized_allowed_channels(definition)
        if not allowed_channels:
            allowed_channels = tuple(sorted(CONNECTOR_DISPATCH_ALLOWED_CHANNELS))
        if not normalized_channel:
            raise ToolExecutionError("connector_dispatch_channel_required")
        if allowed_channels and normalized_channel not in allowed_channels:
            raise ToolExecutionError(
                f"connector_dispatch_channel_not_allowed:{normalized_channel}:{','.join(allowed_channels)}"
            )
        required_scopes = self._channel_dispatch_scopes(normalized_channel)
        _, binding = self._resolve_connector_binding(
            request=request,
            payload=payload,
            required_input_error="connector_binding_required:connector.dispatch",
            required_scopes=required_scopes,
        )
        recipient = str(payload.get("recipient") or "").strip()
        content = str(payload.get("content") or "")
        metadata = dict(payload.get("metadata") or {})
        idempotency_key = str(payload.get("idempotency_key") or "").strip()
        delivery = self._channel_runtime.queue_delivery(
            channel=normalized_channel,
            recipient=recipient,
            content=content,
            metadata=metadata,
            idempotency_key=idempotency_key,
        )
        action_kind = str(request.action_kind or "delivery.send") or "delivery.send"
        return ToolInvocationResult(
            tool_name=definition.tool_name,
            action_kind=action_kind,
            target_ref=delivery.delivery_id,
            output_json={
                "delivery_id": delivery.delivery_id,
                "status": delivery.status,
                "channel": delivery.channel,
                "recipient": delivery.recipient,
                "binding_id": binding.binding_id,
                "connector_name": binding.connector_name,
                "principal_id": binding.principal_id,
                "idempotency_key": delivery.idempotency_key,
                "tool_name": definition.tool_name,
                "action_kind": action_kind,
            },
            receipt_json={
                "binding_id": binding.binding_id,
                "channel": delivery.channel,
                "connector_name": binding.connector_name,
                "delivery_id": delivery.delivery_id,
                "handler_key": definition.tool_name,
                "idempotency_key": delivery.idempotency_key,
                "invocation_contract": "tool.v1",
                "principal_id": binding.principal_id,
                "status": delivery.status,
                "tool_version": definition.version,
            },
        )
