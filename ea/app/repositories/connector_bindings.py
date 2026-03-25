from __future__ import annotations

import uuid
from dataclasses import replace
from typing import Dict, List, Protocol

from app.domain.models import ConnectorBinding, now_utc_iso


class ConnectorBindingRepository(Protocol):
    def upsert(
        self,
        principal_id: str,
        connector_name: str,
        external_account_ref: str,
        *,
        scope_json: dict[str, object] | None = None,
        auth_metadata_json: dict[str, object] | None = None,
        status: str = "enabled",
    ) -> ConnectorBinding:
        ...

    def list_for_principal(self, principal_id: str, limit: int = 100) -> list[ConnectorBinding]:
        ...

    def list_for_connector(self, connector_name: str, limit: int = 100) -> list[ConnectorBinding]:
        ...

    def get(self, binding_id: str) -> ConnectorBinding | None:
        ...

    def set_status(self, binding_id: str, status: str) -> ConnectorBinding | None:
        ...


class InMemoryConnectorBindingRepository:
    def __init__(self) -> None:
        self._rows: Dict[str, ConnectorBinding] = {}
        self._order: List[str] = []
        self._natural_key_to_id: Dict[str, str] = {}

    def _key(self, principal_id: str, connector_name: str, external_account_ref: str) -> str:
        return "|".join(
            [
                str(principal_id or "").strip().lower(),
                str(connector_name or "").strip().lower(),
                str(external_account_ref or "").strip().lower(),
            ]
        )

    def upsert(
        self,
        principal_id: str,
        connector_name: str,
        external_account_ref: str,
        *,
        scope_json: dict[str, object] | None = None,
        auth_metadata_json: dict[str, object] | None = None,
        status: str = "enabled",
    ) -> ConnectorBinding:
        key = self._key(principal_id, connector_name, external_account_ref)
        now = now_utc_iso()
        existing_id = self._natural_key_to_id.get(key)
        if existing_id and existing_id in self._rows:
            found = self._rows[existing_id]
            updated = replace(
                found,
                scope_json=dict(scope_json or found.scope_json),
                auth_metadata_json=dict(auth_metadata_json or found.auth_metadata_json),
                status=str(status or found.status),
                updated_at=now,
            )
            self._rows[updated.binding_id] = updated
            return updated

        row = ConnectorBinding(
            binding_id=str(uuid.uuid4()),
            principal_id=str(principal_id or "").strip(),
            connector_name=str(connector_name or "").strip(),
            external_account_ref=str(external_account_ref or "").strip(),
            scope_json=dict(scope_json or {}),
            auth_metadata_json=dict(auth_metadata_json or {}),
            status=str(status or "enabled"),
            created_at=now,
            updated_at=now,
        )
        self._rows[row.binding_id] = row
        self._order.append(row.binding_id)
        self._natural_key_to_id[key] = row.binding_id
        return row

    def list_for_principal(self, principal_id: str, limit: int = 100) -> list[ConnectorBinding]:
        n = max(1, min(500, int(limit or 100)))
        principal = str(principal_id or "").strip()
        ids = list(reversed(self._order))
        rows = [self._rows[i] for i in ids if i in self._rows and self._rows[i].principal_id == principal]
        return rows[:n]

    def list_for_connector(self, connector_name: str, limit: int = 100) -> list[ConnectorBinding]:
        n = max(1, min(500, int(limit or 100)))
        normalized = str(connector_name or "").strip().lower()
        ids = list(reversed(self._order))
        rows = [
            self._rows[i]
            for i in ids
            if i in self._rows and str(self._rows[i].connector_name or "").strip().lower() == normalized
        ]
        return rows[:n]

    def get(self, binding_id: str) -> ConnectorBinding | None:
        return self._rows.get(str(binding_id or "").strip())

    def set_status(self, binding_id: str, status: str) -> ConnectorBinding | None:
        found = self._rows.get(str(binding_id or "").strip())
        if not found:
            return None
        updated = replace(found, status=str(status or found.status), updated_at=now_utc_iso())
        self._rows[updated.binding_id] = updated
        return updated
