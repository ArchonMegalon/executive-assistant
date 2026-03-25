from __future__ import annotations

import logging

from app.domain.models import ConnectorBinding, ToolDefinition, now_utc_iso
from app.repositories.connector_bindings import ConnectorBindingRepository, InMemoryConnectorBindingRepository
from app.repositories.connector_bindings_postgres import PostgresConnectorBindingRepository
from app.repositories.tool_registry import InMemoryToolRegistryRepository, ToolRegistryRepository
from app.repositories.tool_registry_postgres import PostgresToolRegistryRepository
from app.settings import Settings, ensure_storage_fallback_allowed, get_settings


class ToolRuntimeService:
    def __init__(
        self,
        tool_registry: ToolRegistryRepository,
        connector_bindings: ConnectorBindingRepository,
    ) -> None:
        self._tool_registry = tool_registry
        self._connector_bindings = connector_bindings

    def upsert_tool(
        self,
        *,
        tool_name: str,
        version: str,
        input_schema_json: dict[str, object] | None = None,
        output_schema_json: dict[str, object] | None = None,
        policy_json: dict[str, object] | None = None,
        allowed_channels: tuple[str, ...] = (),
        approval_default: str = "none",
        enabled: bool = True,
    ) -> ToolDefinition:
        row = ToolDefinition(
            tool_name=str(tool_name or "").strip(),
            version=str(version or "v1"),
            input_schema_json=dict(input_schema_json or {}),
            output_schema_json=dict(output_schema_json or {}),
            policy_json=dict(policy_json or {}),
            allowed_channels=tuple(str(v) for v in allowed_channels),
            approval_default=str(approval_default or "none"),
            enabled=bool(enabled),
            updated_at=now_utc_iso(),
        )
        return self._tool_registry.upsert(row)

    def get_tool(self, tool_name: str) -> ToolDefinition | None:
        return self._tool_registry.get(tool_name)

    def list_enabled_tools(self, limit: int = 100) -> list[ToolDefinition]:
        return self._tool_registry.list_enabled(limit=limit)

    def upsert_connector_binding(
        self,
        *,
        principal_id: str,
        connector_name: str,
        external_account_ref: str,
        scope_json: dict[str, object] | None = None,
        auth_metadata_json: dict[str, object] | None = None,
        status: str = "enabled",
    ) -> ConnectorBinding:
        return self._connector_bindings.upsert(
            principal_id=principal_id,
            connector_name=connector_name,
            external_account_ref=external_account_ref,
            scope_json=scope_json,
            auth_metadata_json=auth_metadata_json,
            status=status,
        )

    def list_connector_bindings(self, principal_id: str, limit: int = 100) -> list[ConnectorBinding]:
        return self._connector_bindings.list_for_principal(principal_id, limit=limit)

    def list_connector_bindings_for_connector(self, connector_name: str, limit: int = 100) -> list[ConnectorBinding]:
        return self._connector_bindings.list_for_connector(connector_name, limit=limit)

    def get_connector_binding(self, binding_id: str) -> ConnectorBinding | None:
        return self._connector_bindings.get(binding_id)

    def set_connector_binding_status(self, binding_id: str, status: str) -> ConnectorBinding | None:
        return self._connector_bindings.set_status(binding_id, status)


def _backend_mode(settings: Settings) -> str:
    return str(settings.storage.backend or "auto").strip().lower()


def _build_tool_registry(settings: Settings) -> ToolRegistryRepository:
    backend = _backend_mode(settings)
    log = logging.getLogger("ea.tools")
    if backend == "memory":
        ensure_storage_fallback_allowed(settings, "tool registry configured for memory")
        return InMemoryToolRegistryRepository()
    if backend == "postgres":
        if not settings.database_url:
            raise RuntimeError("EA_STORAGE_BACKEND=postgres requires DATABASE_URL")
        return PostgresToolRegistryRepository(settings.database_url)
    if settings.database_url:
        try:
            return PostgresToolRegistryRepository(settings.database_url)
        except Exception as exc:
            ensure_storage_fallback_allowed(settings, "tool registry auto fallback", exc)
            log.warning("postgres tool registry unavailable in auto mode; falling back to memory: %s", exc)
    ensure_storage_fallback_allowed(settings, "tool registry auto backend without DATABASE_URL")
    return InMemoryToolRegistryRepository()


def _build_connector_bindings(settings: Settings) -> ConnectorBindingRepository:
    backend = _backend_mode(settings)
    log = logging.getLogger("ea.connectors")
    if backend == "memory":
        ensure_storage_fallback_allowed(settings, "connector bindings configured for memory")
        return InMemoryConnectorBindingRepository()
    if backend == "postgres":
        if not settings.database_url:
            raise RuntimeError("EA_STORAGE_BACKEND=postgres requires DATABASE_URL")
        return PostgresConnectorBindingRepository(settings.database_url)
    if settings.database_url:
        try:
            return PostgresConnectorBindingRepository(settings.database_url)
        except Exception as exc:
            ensure_storage_fallback_allowed(settings, "connector bindings auto fallback", exc)
            log.warning("postgres connector bindings unavailable in auto mode; falling back to memory: %s", exc)
    ensure_storage_fallback_allowed(settings, "connector bindings auto backend without DATABASE_URL")
    return InMemoryConnectorBindingRepository()


def build_tool_runtime(settings: Settings | None = None) -> ToolRuntimeService:
    resolved = settings or get_settings()
    return ToolRuntimeService(
        tool_registry=_build_tool_registry(resolved),
        connector_bindings=_build_connector_bindings(resolved),
    )
