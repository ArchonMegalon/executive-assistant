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
from app.services.tool_runtime import ToolRuntimeService

ToolExecutionHandler = Callable[[ToolInvocationRequest, ToolDefinition], ToolInvocationResult]


class ToolExecutionError(RuntimeError):
    pass


class ToolExecutionService:
    def __init__(
        self,
        *,
        tool_runtime: ToolRuntimeService | None = None,
        artifacts: ArtifactRepository | None = None,
        channel_runtime: ChannelRuntimeService | None = None,
    ) -> None:
        self._artifacts = artifacts or InMemoryArtifactRepository()
        self._channel_runtime = channel_runtime
        self._tool_runtime = tool_runtime or ToolRuntimeService(
            tool_registry=InMemoryToolRegistryRepository(),
            connector_bindings=InMemoryConnectorBindingRepository(),
        )
        self._handlers: dict[str, ToolExecutionHandler] = {}
        self._register_builtin_artifact_repository()
        self._register_builtin_browseract_extract()
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

    def _register_builtin_connector_dispatch(self) -> None:
        if self._channel_runtime is None:
            return
        if self._tool_runtime.get_tool("connector.dispatch") is None:
            self._tool_runtime.upsert_tool(
                tool_name="connector.dispatch",
                version="v1",
                input_schema_json={
                    "type": "object",
                    "required": ["channel", "recipient", "content"],
                    "properties": {
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
                policy_json={"builtin": True, "action_kind": "delivery.send"},
                allowed_channels=("email", "slack", "telegram"),
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
        principal_id = str((request.context_json or {}).get("principal_id") or "").strip()
        if not principal_id:
            raise ToolExecutionError("principal_id_required")
        binding_id = str(payload.get("binding_id") or "").strip()
        if not binding_id:
            raise ToolExecutionError("connector_binding_required:browseract.extract_account_facts")
        binding = self._tool_runtime.get_connector_binding(binding_id)
        if binding is None:
            raise ToolExecutionError(f"connector_binding_not_found:{binding_id}")
        if str(binding.status or "").strip().lower() != "enabled":
            raise ToolExecutionError(f"connector_binding_disabled:{binding_id}")
        if binding.principal_id != principal_id:
            raise ToolExecutionError("principal_scope_mismatch")
        if str(binding.connector_name or "").strip().lower() != "browseract":
            raise ToolExecutionError(f"connector_binding_connector_mismatch:{binding_id}")
        service_name = str(payload.get("service_name") or "").strip()
        if not service_name:
            raise ToolExecutionError("service_name_required:browseract.extract_account_facts")
        requested_fields = self._browseract_requested_fields(payload)
        facts_json = self._browseract_service_facts(
            binding_auth_metadata_json=dict(binding.auth_metadata_json or {}),
            service_name=service_name,
        )
        if facts_json is None:
            facts_json = self._browseract_live_extract(
                binding_auth_metadata_json=dict(binding.auth_metadata_json or {}),
                payload=payload,
                service_name=service_name,
                requested_fields=requested_fields,
            )
        if facts_json is None:
            raise ToolExecutionError(f"browseract_service_not_found:{service_name}")
        verification_source = str(facts_json.pop("verification_source", "") or "connector_metadata").strip() or "connector_metadata"
        facts_json = {str(key): value for key, value in facts_json.items()}
        facts_json.setdefault("service_name", service_name)
        requested_fields = requested_fields or tuple(key for key in facts_json.keys() if key != "service_name")
        missing_fields = tuple(key for key in requested_fields if not self._browseract_fact_present(facts_json.get(key)))
        account_email = str(
            facts_json.get("account_email")
            or facts_json.get("email")
            or facts_json.get("login_email")
            or ""
        ).strip()
        plan_tier = str(
            facts_json.get("tier")
            or facts_json.get("plan")
            or facts_json.get("plan_tier")
            or facts_json.get("license_tier")
            or ""
        ).strip()
        last_verified_at = now_utc_iso()
        discovery_status = "complete" if requested_fields and not missing_fields else "partial"
        normalized_text = self._browseract_summary_text(
            service_name=service_name,
            facts_json=facts_json,
            requested_fields=requested_fields,
            missing_fields=missing_fields,
            verification_source=verification_source,
            last_verified_at=last_verified_at,
        )
        action_kind = str(request.action_kind or "account.extract") or "account.extract"
        structured_output_json = {
            "service_name": service_name,
            "facts_json": facts_json,
            "requested_fields": list(requested_fields),
            "missing_fields": list(missing_fields),
            "discovery_status": discovery_status,
            "verification_source": verification_source,
            "last_verified_at": last_verified_at,
            "binding_id": binding.binding_id,
            "connector_name": binding.connector_name,
            "external_account_ref": binding.external_account_ref,
            "account_email": account_email,
            "plan_tier": plan_tier,
        }
        return ToolInvocationResult(
            tool_name=definition.tool_name,
            action_kind=action_kind,
            target_ref=f"browseract:{binding.binding_id}:{service_name.lower().replace(' ', '_')}",
            output_json={
                "binding_id": binding.binding_id,
                "connector_name": binding.connector_name,
                "external_account_ref": binding.external_account_ref,
                "service_name": service_name,
                "facts_json": facts_json,
                "requested_fields": list(requested_fields),
                "missing_fields": list(missing_fields),
                "account_email": account_email,
                "plan_tier": plan_tier,
                "discovery_status": discovery_status,
                "verification_source": verification_source,
                "last_verified_at": last_verified_at,
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
                "service_name": service_name,
                "requested_fields": list(requested_fields),
                "missing_fields": list(missing_fields),
                "discovery_status": discovery_status,
                "verification_source": verification_source,
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
        binding_id = str(payload.get("binding_id") or "").strip()
        if not binding_id:
            raise ToolExecutionError("connector_binding_required:connector.dispatch")
        binding = self._tool_runtime.get_connector_binding(binding_id)
        if binding is None:
            raise ToolExecutionError(f"connector_binding_not_found:{binding_id}")
        if str(binding.status or "").strip().lower() != "enabled":
            raise ToolExecutionError(f"connector_binding_disabled:{binding_id}")
        principal_id = str((request.context_json or {}).get("principal_id") or "").strip()
        if principal_id and binding.principal_id != principal_id:
            raise ToolExecutionError("principal_scope_mismatch")
        channel = str(payload.get("channel") or "").strip()
        recipient = str(payload.get("recipient") or "").strip()
        content = str(payload.get("content") or "")
        metadata = dict(payload.get("metadata") or {})
        idempotency_key = str(payload.get("idempotency_key") or "").strip()
        delivery = self._channel_runtime.queue_delivery(
            channel=channel,
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
