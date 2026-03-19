from __future__ import annotations

import uuid
from typing import Dict, List, Protocol

from app.domain.models import ObservationEvent, now_utc_iso


class ObservationEventRepository(Protocol):
    def append(
        self,
        principal_id: str,
        channel: str,
        event_type: str,
        payload: dict[str, object] | None = None,
        *,
        source_id: str = "",
        external_id: str = "",
        dedupe_key: str = "",
        auth_context_json: dict[str, object] | None = None,
        raw_payload_uri: str = "",
    ) -> ObservationEvent:
        ...

    def list_recent(self, limit: int = 50) -> list[ObservationEvent]:
        ...

    def get_by_dedupe(self, dedupe_key: str) -> ObservationEvent | None:
        ...

    def count_recent_for_principal(self, principal_id: str, *, since: str) -> int:
        ...


class InMemoryObservationEventRepository:
    def __init__(self) -> None:
        self._rows: Dict[str, ObservationEvent] = {}
        self._order: List[str] = []
        self._dedupe_to_id: Dict[str, str] = {}

    def append(
        self,
        principal_id: str,
        channel: str,
        event_type: str,
        payload: dict[str, object] | None = None,
        *,
        source_id: str = "",
        external_id: str = "",
        dedupe_key: str = "",
        auth_context_json: dict[str, object] | None = None,
        raw_payload_uri: str = "",
    ) -> ObservationEvent:
        dedupe = str(dedupe_key or "").strip()
        if dedupe:
            found_id = self._dedupe_to_id.get(dedupe)
            if found_id and found_id in self._rows:
                return self._rows[found_id]
        row = ObservationEvent(
            observation_id=str(uuid.uuid4()),
            principal_id=str(principal_id or "").strip(),
            channel=str(channel or "unknown").strip(),
            event_type=str(event_type or "unknown").strip(),
            payload=dict(payload or {}),
            created_at=now_utc_iso(),
            source_id=str(source_id or "").strip(),
            external_id=str(external_id or "").strip(),
            dedupe_key=dedupe,
            auth_context_json=dict(auth_context_json or {}),
            raw_payload_uri=str(raw_payload_uri or "").strip(),
        )
        self._rows[row.observation_id] = row
        self._order.append(row.observation_id)
        if dedupe:
            self._dedupe_to_id[dedupe] = row.observation_id
        return row

    def list_recent(self, limit: int = 50) -> list[ObservationEvent]:
        n = max(1, min(500, int(limit or 50)))
        ids = list(reversed(self._order[-n:]))
        return [self._rows[i] for i in ids if i in self._rows]

    def get_by_dedupe(self, dedupe_key: str) -> ObservationEvent | None:
        key = str(dedupe_key or "").strip()
        if not key:
            return None
        found_id = self._dedupe_to_id.get(key)
        if not found_id:
            return None
        return self._rows.get(found_id)

    def count_recent_for_principal(self, principal_id: str, *, since: str) -> int:
        principal = str(principal_id or "").strip()
        cutoff = str(since or "").strip()
        if not principal or not cutoff:
            return 0
        return sum(
            1
            for observation_id in self._order
            if observation_id in self._rows
            and self._rows[observation_id].principal_id == principal
            and str(self._rows[observation_id].created_at or "") >= cutoff
        )
