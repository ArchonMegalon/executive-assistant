from __future__ import annotations

from datetime import datetime
from typing import Any

from app.domain.models import OneminAccount, OneminAllocationLease, OneminCredential


def _to_iso(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "") or None


class PostgresOneminManagerRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = str(database_url or "").strip()
        if not self._database_url:
            raise ValueError("database_url is required for PostgresOneminManagerRepository")
        self._ensure_schema()

    def _connect(self):  # type: ignore[no-untyped-def]
        try:
            import psycopg
        except Exception as exc:  # pragma: no cover - import guard
            raise RuntimeError("psycopg is required for postgres onemin-manager backend") from exc
        return psycopg.connect(self._database_url, autocommit=True)

    def _json_value(self, value: Any):  # type: ignore[no-untyped-def]
        from psycopg.types.json import Json

        return Json(value)

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS onemin_accounts (
                        account_id TEXT PRIMARY KEY,
                        provider_key TEXT NOT NULL,
                        account_label TEXT NOT NULL,
                        owner_email TEXT NOT NULL,
                        owner_name TEXT NOT NULL,
                        browseract_binding_id TEXT NOT NULL,
                        workspace_id TEXT NOT NULL,
                        status TEXT NOT NULL,
                        remaining_credits DOUBLE PRECISION NULL,
                        max_credits DOUBLE PRECISION NULL,
                        core_floor_credits DOUBLE PRECISION NULL,
                        image_spendable_credits DOUBLE PRECISION NULL,
                        reserve_credits DOUBLE PRECISION NULL,
                        slot_count INTEGER NOT NULL,
                        ready_slot_count INTEGER NOT NULL,
                        last_billing_snapshot_at TIMESTAMPTZ NULL,
                        last_member_reconciliation_at TIMESTAMPTZ NULL,
                        details_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS onemin_credentials (
                        credential_id TEXT PRIMARY KEY,
                        account_id TEXT NOT NULL,
                        slot_name TEXT NOT NULL,
                        secret_env_name TEXT NOT NULL,
                        owner_email TEXT NOT NULL,
                        active_role TEXT NOT NULL,
                        state TEXT NOT NULL,
                        remaining_credits DOUBLE PRECISION NULL,
                        max_credits DOUBLE PRECISION NULL,
                        last_probe_at TIMESTAMPTZ NULL,
                        last_success_at TIMESTAMPTZ NULL,
                        last_error TEXT NOT NULL,
                        quarantine_until TIMESTAMPTZ NULL,
                        details_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS onemin_allocation_leases (
                        lease_id TEXT PRIMARY KEY,
                        request_id TEXT NOT NULL,
                        principal_id TEXT NOT NULL,
                        lane TEXT NOT NULL,
                        capability TEXT NOT NULL,
                        account_id TEXT NOT NULL,
                        credential_id TEXT NOT NULL,
                        estimated_credits INTEGER NULL,
                        actual_credits_delta INTEGER NULL,
                        status TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        expires_at TIMESTAMPTZ NULL,
                        finished_at TIMESTAMPTZ NULL,
                        error TEXT NOT NULL,
                        metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_onemin_credentials_account
                    ON onemin_credentials(account_id, state, updated_at DESC)
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_onemin_leases_status_account
                    ON onemin_allocation_leases(status, account_id, created_at DESC)
                    """
                )

    def _account_from_row(self, row: tuple[Any, ...]) -> OneminAccount:
        return OneminAccount(
            account_id=str(row[0]),
            provider_key=str(row[1]),
            account_label=str(row[2]),
            owner_email=str(row[3]),
            owner_name=str(row[4]),
            browseract_binding_id=str(row[5]),
            workspace_id=str(row[6]),
            status=str(row[7]),
            remaining_credits=float(row[8]) if row[8] is not None else None,
            max_credits=float(row[9]) if row[9] is not None else None,
            core_floor_credits=float(row[10]) if row[10] is not None else None,
            image_spendable_credits=float(row[11]) if row[11] is not None else None,
            reserve_credits=float(row[12]) if row[12] is not None else None,
            slot_count=int(row[13] or 0),
            ready_slot_count=int(row[14] or 0),
            last_billing_snapshot_at=_to_iso(row[15]),
            last_member_reconciliation_at=_to_iso(row[16]),
            details_json=dict(row[17] or {}),
        )

    def _credential_from_row(self, row: tuple[Any, ...]) -> OneminCredential:
        return OneminCredential(
            credential_id=str(row[0]),
            account_id=str(row[1]),
            slot_name=str(row[2]),
            secret_env_name=str(row[3]),
            owner_email=str(row[4]),
            active_role=str(row[5]),
            state=str(row[6]),
            remaining_credits=float(row[7]) if row[7] is not None else None,
            max_credits=float(row[8]) if row[8] is not None else None,
            last_probe_at=_to_iso(row[9]),
            last_success_at=_to_iso(row[10]),
            last_error=str(row[11] or ""),
            quarantine_until=_to_iso(row[12]),
            details_json=dict(row[13] or {}),
        )

    def _lease_from_row(self, row: tuple[Any, ...]) -> OneminAllocationLease:
        return OneminAllocationLease(
            lease_id=str(row[0]),
            request_id=str(row[1]),
            principal_id=str(row[2]),
            lane=str(row[3]),
            capability=str(row[4]),
            account_id=str(row[5]),
            credential_id=str(row[6]),
            estimated_credits=int(row[7]) if row[7] is not None else None,
            actual_credits_delta=int(row[8]) if row[8] is not None else None,
            status=str(row[9]),
            created_at=str(_to_iso(row[10]) or ""),
            expires_at=_to_iso(row[11]),
            finished_at=_to_iso(row[12]),
            error=str(row[13] or ""),
            metadata_json=dict(row[14] or {}),
        )

    def replace_state(self, *, accounts: list[OneminAccount], credentials: list[OneminCredential]) -> None:
        account_ids = [row.account_id for row in accounts]
        credential_ids = [row.credential_id for row in credentials]
        with self._connect() as conn:
            with conn.cursor() as cur:
                for row in accounts:
                    cur.execute(
                        """
                        INSERT INTO onemin_accounts (
                            account_id, provider_key, account_label, owner_email, owner_name,
                            browseract_binding_id, workspace_id, status, remaining_credits, max_credits,
                            core_floor_credits, image_spendable_credits, reserve_credits, slot_count, ready_slot_count,
                            last_billing_snapshot_at, last_member_reconciliation_at, details_json, updated_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                        ON CONFLICT (account_id) DO UPDATE SET
                            provider_key = EXCLUDED.provider_key,
                            account_label = EXCLUDED.account_label,
                            owner_email = EXCLUDED.owner_email,
                            owner_name = EXCLUDED.owner_name,
                            browseract_binding_id = EXCLUDED.browseract_binding_id,
                            workspace_id = EXCLUDED.workspace_id,
                            status = EXCLUDED.status,
                            remaining_credits = EXCLUDED.remaining_credits,
                            max_credits = EXCLUDED.max_credits,
                            core_floor_credits = EXCLUDED.core_floor_credits,
                            image_spendable_credits = EXCLUDED.image_spendable_credits,
                            reserve_credits = EXCLUDED.reserve_credits,
                            slot_count = EXCLUDED.slot_count,
                            ready_slot_count = EXCLUDED.ready_slot_count,
                            last_billing_snapshot_at = EXCLUDED.last_billing_snapshot_at,
                            last_member_reconciliation_at = EXCLUDED.last_member_reconciliation_at,
                            details_json = EXCLUDED.details_json,
                            updated_at = NOW()
                        """,
                        (
                            row.account_id,
                            row.provider_key,
                            row.account_label,
                            row.owner_email,
                            row.owner_name,
                            row.browseract_binding_id,
                            row.workspace_id,
                            row.status,
                            row.remaining_credits,
                            row.max_credits,
                            row.core_floor_credits,
                            row.image_spendable_credits,
                            row.reserve_credits,
                            row.slot_count,
                            row.ready_slot_count,
                            row.last_billing_snapshot_at,
                            row.last_member_reconciliation_at,
                            self._json_value(dict(row.details_json or {})),
                        ),
                    )
                for row in credentials:
                    cur.execute(
                        """
                        INSERT INTO onemin_credentials (
                            credential_id, account_id, slot_name, secret_env_name, owner_email, active_role, state,
                            remaining_credits, max_credits, last_probe_at, last_success_at, last_error, quarantine_until,
                            details_json, updated_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                        ON CONFLICT (credential_id) DO UPDATE SET
                            account_id = EXCLUDED.account_id,
                            slot_name = EXCLUDED.slot_name,
                            secret_env_name = EXCLUDED.secret_env_name,
                            owner_email = EXCLUDED.owner_email,
                            active_role = EXCLUDED.active_role,
                            state = EXCLUDED.state,
                            remaining_credits = EXCLUDED.remaining_credits,
                            max_credits = EXCLUDED.max_credits,
                            last_probe_at = EXCLUDED.last_probe_at,
                            last_success_at = EXCLUDED.last_success_at,
                            last_error = EXCLUDED.last_error,
                            quarantine_until = EXCLUDED.quarantine_until,
                            details_json = EXCLUDED.details_json,
                            updated_at = NOW()
                        """,
                        (
                            row.credential_id,
                            row.account_id,
                            row.slot_name,
                            row.secret_env_name,
                            row.owner_email,
                            row.active_role,
                            row.state,
                            row.remaining_credits,
                            row.max_credits,
                            row.last_probe_at,
                            row.last_success_at,
                            row.last_error,
                            row.quarantine_until,
                            self._json_value(dict(row.details_json or {})),
                        ),
                    )
                if account_ids:
                    cur.execute("DELETE FROM onemin_accounts WHERE account_id <> ALL(%s)", (account_ids,))
                else:
                    cur.execute("DELETE FROM onemin_accounts")
                if credential_ids:
                    cur.execute("DELETE FROM onemin_credentials WHERE credential_id <> ALL(%s)", (credential_ids,))
                else:
                    cur.execute("DELETE FROM onemin_credentials")

    def list_accounts(self) -> list[OneminAccount]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT account_id, provider_key, account_label, owner_email, owner_name, browseract_binding_id,
                           workspace_id, status, remaining_credits, max_credits, core_floor_credits,
                           image_spendable_credits, reserve_credits, slot_count, ready_slot_count,
                           last_billing_snapshot_at, last_member_reconciliation_at, details_json
                    FROM onemin_accounts
                    ORDER BY remaining_credits DESC NULLS LAST, account_id ASC
                    """
                )
                rows = cur.fetchall()
        return [self._account_from_row(row) for row in rows]

    def list_credentials(self, *, account_id: str | None = None) -> list[OneminCredential]:
        normalized_account = str(account_id or "").strip()
        with self._connect() as conn:
            with conn.cursor() as cur:
                if normalized_account:
                    cur.execute(
                        """
                        SELECT credential_id, account_id, slot_name, secret_env_name, owner_email, active_role, state,
                               remaining_credits, max_credits, last_probe_at, last_success_at, last_error, quarantine_until,
                               details_json
                        FROM onemin_credentials
                        WHERE account_id = %s
                        ORDER BY slot_name ASC, credential_id ASC
                        """,
                        (normalized_account,),
                    )
                else:
                    cur.execute(
                        """
                        SELECT credential_id, account_id, slot_name, secret_env_name, owner_email, active_role, state,
                               remaining_credits, max_credits, last_probe_at, last_success_at, last_error, quarantine_until,
                               details_json
                        FROM onemin_credentials
                        ORDER BY account_id ASC, slot_name ASC, credential_id ASC
                        """
                    )
                rows = cur.fetchall()
        return [self._credential_from_row(row) for row in rows]

    def upsert_lease(self, lease: OneminAllocationLease) -> OneminAllocationLease:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO onemin_allocation_leases (
                        lease_id, request_id, principal_id, lane, capability, account_id, credential_id,
                        estimated_credits, actual_credits_delta, status, created_at, expires_at, finished_at, error, metadata_json
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (lease_id) DO UPDATE SET
                        request_id = EXCLUDED.request_id,
                        principal_id = EXCLUDED.principal_id,
                        lane = EXCLUDED.lane,
                        capability = EXCLUDED.capability,
                        account_id = EXCLUDED.account_id,
                        credential_id = EXCLUDED.credential_id,
                        estimated_credits = EXCLUDED.estimated_credits,
                        actual_credits_delta = EXCLUDED.actual_credits_delta,
                        status = EXCLUDED.status,
                        created_at = EXCLUDED.created_at,
                        expires_at = EXCLUDED.expires_at,
                        finished_at = EXCLUDED.finished_at,
                        error = EXCLUDED.error,
                        metadata_json = EXCLUDED.metadata_json
                    RETURNING lease_id, request_id, principal_id, lane, capability, account_id, credential_id,
                              estimated_credits, actual_credits_delta, status, created_at, expires_at, finished_at, error,
                              metadata_json
                    """,
                    (
                        lease.lease_id,
                        lease.request_id,
                        lease.principal_id,
                        lease.lane,
                        lease.capability,
                        lease.account_id,
                        lease.credential_id,
                        lease.estimated_credits,
                        lease.actual_credits_delta,
                        lease.status,
                        lease.created_at,
                        lease.expires_at,
                        lease.finished_at,
                        lease.error,
                        self._json_value(dict(lease.metadata_json or {})),
                    ),
                )
                row = cur.fetchone()
        if row is None:
            raise RuntimeError("onemin_manager_lease_upsert_failed")
        return self._lease_from_row(row)

    def get_lease(self, lease_id: str) -> OneminAllocationLease | None:
        normalized = str(lease_id or "").strip()
        if not normalized:
            return None
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT lease_id, request_id, principal_id, lane, capability, account_id, credential_id,
                           estimated_credits, actual_credits_delta, status, created_at, expires_at, finished_at, error,
                           metadata_json
                    FROM onemin_allocation_leases
                    WHERE lease_id = %s
                    """,
                    (normalized,),
                )
                row = cur.fetchone()
        if row is None:
            return None
        return self._lease_from_row(row)

    def list_leases(self, *, limit: int = 500, statuses: tuple[str, ...] = ()) -> list[OneminAllocationLease]:
        bounded_limit = max(1, min(5000, int(limit or 500)))
        status_values = tuple(str(item or "").strip() for item in statuses if str(item or "").strip())
        with self._connect() as conn:
            with conn.cursor() as cur:
                if status_values:
                    cur.execute(
                        """
                        SELECT lease_id, request_id, principal_id, lane, capability, account_id, credential_id,
                               estimated_credits, actual_credits_delta, status, created_at, expires_at, finished_at, error,
                               metadata_json
                        FROM onemin_allocation_leases
                        WHERE status = ANY(%s)
                        ORDER BY created_at DESC, lease_id DESC
                        LIMIT %s
                        """,
                        (list(status_values), bounded_limit),
                    )
                else:
                    cur.execute(
                        """
                        SELECT lease_id, request_id, principal_id, lane, capability, account_id, credential_id,
                               estimated_credits, actual_credits_delta, status, created_at, expires_at, finished_at, error,
                               metadata_json
                        FROM onemin_allocation_leases
                        ORDER BY created_at DESC, lease_id DESC
                        LIMIT %s
                        """,
                        (bounded_limit,),
                    )
                rows = cur.fetchall()
        return [self._lease_from_row(row) for row in rows]
