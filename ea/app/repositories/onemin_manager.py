from __future__ import annotations

from dataclasses import replace
from typing import Dict, List, Protocol

from app.domain.models import OneminAccount, OneminAllocationLease, OneminCredential
from app.settings import Settings, ensure_storage_fallback_allowed, get_settings


class OneminManagerRepository(Protocol):
    def replace_state(self, *, accounts: list[OneminAccount], credentials: list[OneminCredential]) -> None:
        ...

    def list_accounts(self) -> List[OneminAccount]:
        ...

    def list_credentials(self, *, account_id: str | None = None) -> List[OneminCredential]:
        ...

    def upsert_lease(self, lease: OneminAllocationLease) -> OneminAllocationLease:
        ...

    def get_lease(self, lease_id: str) -> OneminAllocationLease | None:
        ...

    def list_leases(self, *, limit: int = 500, statuses: tuple[str, ...] = ()) -> List[OneminAllocationLease]:
        ...


class InMemoryOneminManagerRepository:
    def __init__(self) -> None:
        self._accounts: Dict[str, OneminAccount] = {}
        self._credentials: Dict[str, OneminCredential] = {}
        self._leases: Dict[str, OneminAllocationLease] = {}

    def replace_state(self, *, accounts: list[OneminAccount], credentials: list[OneminCredential]) -> None:
        self._accounts = {row.account_id: row for row in accounts}
        self._credentials = {row.credential_id: row for row in credentials}

    def list_accounts(self) -> List[OneminAccount]:
        return sorted(self._accounts.values(), key=lambda row: (-(row.remaining_credits or 0.0), row.account_id))

    def list_credentials(self, *, account_id: str | None = None) -> List[OneminCredential]:
        normalized_account = str(account_id or "").strip()
        rows = list(self._credentials.values())
        if normalized_account:
            rows = [row for row in rows if row.account_id == normalized_account]
        return sorted(rows, key=lambda row: (row.account_id, row.slot_name, row.credential_id))

    def upsert_lease(self, lease: OneminAllocationLease) -> OneminAllocationLease:
        current = self._leases.get(lease.lease_id)
        self._leases[lease.lease_id] = lease if current is None else replace(current, **lease.__dict__)
        return self._leases[lease.lease_id]

    def get_lease(self, lease_id: str) -> OneminAllocationLease | None:
        return self._leases.get(str(lease_id or "").strip())

    def list_leases(self, *, limit: int = 500, statuses: tuple[str, ...] = ()) -> List[OneminAllocationLease]:
        rows = list(self._leases.values())
        if statuses:
            allowed = {str(item or "").strip() for item in statuses if str(item or "").strip()}
            rows = [row for row in rows if row.status in allowed]
        rows.sort(key=lambda row: (str(row.created_at or ""), row.lease_id), reverse=True)
        return rows[: max(1, min(5000, int(limit or 500)))]


def build_onemin_manager_repo(settings: Settings):
    backend = str(settings.storage.backend or "auto").strip().lower()
    if backend == "memory":
        ensure_storage_fallback_allowed(settings, "onemin manager configured for memory")
        return InMemoryOneminManagerRepository()
    if backend == "postgres":
        if not settings.database_url:
            raise RuntimeError("EA_STORAGE_BACKEND=postgres requires DATABASE_URL")
        from app.repositories.onemin_manager_postgres import PostgresOneminManagerRepository

        return PostgresOneminManagerRepository(settings.database_url)
    if settings.database_url:
        try:
            from app.repositories.onemin_manager_postgres import PostgresOneminManagerRepository

            return PostgresOneminManagerRepository(settings.database_url)
        except Exception as exc:
            ensure_storage_fallback_allowed(settings, "onemin manager auto fallback", exc)
    ensure_storage_fallback_allowed(settings, "onemin manager auto backend without DATABASE_URL")
    return InMemoryOneminManagerRepository()


def build_onemin_manager_service_repo(settings: Settings | None = None):
    resolved = settings or get_settings()
    return build_onemin_manager_repo(resolved)
