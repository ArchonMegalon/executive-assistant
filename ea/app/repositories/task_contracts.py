from __future__ import annotations

from dataclasses import replace
from typing import Dict, List, Protocol

from app.domain.models import TaskContract, now_utc_iso


class TaskContractRepository(Protocol):
    def upsert(self, row: TaskContract) -> TaskContract:
        ...

    def get(self, task_key: str) -> TaskContract | None:
        ...

    def list_all(self, limit: int = 100) -> list[TaskContract]:
        ...


class InMemoryTaskContractRepository:
    def __init__(self) -> None:
        self._rows: Dict[str, TaskContract] = {}
        self._order: List[str] = []

    def upsert(self, row: TaskContract) -> TaskContract:
        key = str(row.task_key or "").strip()
        if not key:
            raise ValueError("task_key is required")
        updated = replace(row, task_key=key, updated_at=now_utc_iso())
        self._rows[key] = updated
        self._order = [existing for existing in self._order if existing != key]
        self._order.append(key)
        return updated

    def get(self, task_key: str) -> TaskContract | None:
        return self._rows.get(str(task_key or "").strip())

    def list_all(self, limit: int = 100) -> list[TaskContract]:
        n = max(1, min(500, int(limit or 100)))
        keys = list(reversed(self._order))
        rows = [self._rows[k] for k in keys if k in self._rows]
        return rows[:n]
