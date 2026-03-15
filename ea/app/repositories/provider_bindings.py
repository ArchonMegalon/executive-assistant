from __future__ import annotations

from dataclasses import replace
from typing import Dict, List, Protocol

from app.domain.models import ProviderBindingRecord, now_utc_iso


class ProviderBindingRepository(Protocol):
    def get(self, binding_id: str) -> ProviderBindingRecord | None:
        ...

    def get_for_provider(
        self,
        principal_id: str,
        provider_key: str,
    ) -> ProviderBindingRecord | None:
        ...

    def list_for_principal(self, principal_id: str, limit: int = 100) -> List[ProviderBindingRecord]:
        ...

    def upsert(
        self,
        *,
        principal_id: str,
        provider_key: str,
        status: str,
        priority: int = 100,
        probe_state: str = "unknown",
        probe_details_json: dict[str, object] | None = None,
        scope_json: dict[str, object] | None = None,
        auth_metadata_json: dict[str, object] | None = None,
    ) -> ProviderBindingRecord:
        ...

    def set_status(self, binding_id: str, status: str) -> ProviderBindingRecord | None:
        ...

    def set_probe(
        self,
        binding_id: str,
        probe_state: str,
        probe_details_json: dict[str, object] | None = None,
    ) -> ProviderBindingRecord | None:
        ...


class InMemoryProviderBindingRepository:
    def __init__(self) -> None:
        self._rows: Dict[str, ProviderBindingRecord] = {}
        self._order: List[str] = []

    def get(self, binding_id: str) -> ProviderBindingRecord | None:
        return self._rows.get(str(binding_id or "").strip())

    def get_for_provider(
        self,
        principal_id: str,
        provider_key: str,
    ) -> ProviderBindingRecord | None:
        normalized_principal = str(principal_id or "").strip()
        normalized_provider = str(provider_key or "").strip().lower()
        if not normalized_principal or not normalized_provider:
            return None
        for key in reversed(self._order):
            row = self._rows.get(key)
            if (
                row is not None
                and row.principal_id == normalized_principal
                and row.provider_key == normalized_provider
            ):
                return row
        return None

    def list_for_principal(self, principal_id: str, limit: int = 100) -> List[ProviderBindingRecord]:
        normalized_principal = str(principal_id or "").strip()
        if not normalized_principal:
            return []
        limit_n = max(1, min(500, int(limit or 100)))
        rows: List[ProviderBindingRecord] = []
        for key in reversed(self._order):
            row = self._rows.get(key)
            if row is not None and row.principal_id == normalized_principal:
                rows.append(row)
        return rows[:limit_n]

    def upsert(
        self,
        *,
        principal_id: str,
        provider_key: str,
        status: str,
        priority: int = 100,
        probe_state: str = "unknown",
        probe_details_json: dict[str, object] | None = None,
        scope_json: dict[str, object] | None = None,
        auth_metadata_json: dict[str, object] | None = None,
    ) -> ProviderBindingRecord:
        normalized_principal = str(principal_id or "").strip()
        normalized_provider = str(provider_key or "").strip().lower()
        if not normalized_principal:
            raise ValueError("principal_id_required")
        if not normalized_provider:
            raise ValueError("provider_key_required")

        binding_id = (
            f"{normalized_principal}:{normalized_provider}"
            if f"{normalized_principal}:{normalized_provider}" in self._rows
            else f"{normalized_principal}:{normalized_provider}:{len(self._rows) + 1}"
        )

        existing = self._rows.get(binding_id)
        timestamp = now_utc_iso()
        normalized_status = str(status or "enabled").strip().lower() or "enabled"
        normalized_probe_state = str(probe_state or "unknown").strip() or "unknown"
        payload = ProviderBindingRecord(
            binding_id=binding_id,
            principal_id=normalized_principal,
            provider_key=normalized_provider,
            status=normalized_status,
            priority=int(priority or 100),
            probe_state=normalized_probe_state,
            probe_details_json=dict(probe_details_json or {}),
            scope_json=dict(scope_json or {}),
            auth_metadata_json=dict(auth_metadata_json or {}),
            created_at=existing.created_at if existing is not None else timestamp,
            updated_at=timestamp,
        )
        if binding_id not in self._rows:
            self._order.append(binding_id)
        self._rows[binding_id] = payload
        return payload

    def set_status(self, binding_id: str, status: str) -> ProviderBindingRecord | None:
        normalized_id = str(binding_id or "").strip()
        current = self._rows.get(normalized_id)
        if current is None:
            return None
        updated = replace(
            current,
            status=str(status or current.status).strip().lower() or current.status,
            updated_at=now_utc_iso(),
        )
        self._rows[normalized_id] = updated
        return updated

    def set_probe(
        self,
        binding_id: str,
        probe_state: str,
        probe_details_json: dict[str, object] | None = None,
    ) -> ProviderBindingRecord | None:
        normalized_id = str(binding_id or "").strip()
        current = self._rows.get(normalized_id)
        if current is None:
            return None
        updated = replace(
            current,
            probe_state=str(probe_state or current.probe_state).strip() or current.probe_state,
            probe_details_json=dict(probe_details_json or {}),
            updated_at=now_utc_iso(),
        )
        self._rows[normalized_id] = updated
        return updated
