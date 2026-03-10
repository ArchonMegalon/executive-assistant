from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

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
