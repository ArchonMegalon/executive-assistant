from __future__ import annotations

import concurrent.futures
import threading
from contextlib import AbstractContextManager
from types import SimpleNamespace
from typing import Any

from app.api.routes.landing_shared_support import bootstrap_initial_operator_profile
from app.repositories.operator_profiles import InMemoryOperatorProfileRepository
from app.repositories.operator_profiles_postgres import (
    PostgresOperatorProfileRepository,
)
from app.services.orchestrator import RewriteOrchestrator


class _OnboardingStub:
    def status(self, *, principal_id: str) -> dict[str, object]:
        assert principal_id
        return {"workspace": {"mode": "personal"}}


def test_memory_operator_bootstrap_allows_exactly_one_concurrent_winner() -> None:
    repository = InMemoryOperatorProfileRepository()
    container = SimpleNamespace(
        orchestrator=RewriteOrchestrator(operator_profiles=repository),
        onboarding=_OnboardingStub(),
    )
    contender_count = 16
    start = threading.Barrier(contender_count)

    def contend(index: int) -> tuple[str, str]:
        start.wait(timeout=10)
        try:
            profile = bootstrap_initial_operator_profile(
                container,
                principal_id="principal-concurrent-bootstrap",
                operator_id=f"operator-{index}",
                display_name=f"Operator {index}",
            )
        except ValueError as exc:
            return "blocked", str(exc)
        return "created", profile.operator_id

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=contender_count
    ) as executor:
        results = list(executor.map(contend, range(contender_count)))

    created = [detail for status, detail in results if status == "created"]
    blocked = [detail for status, detail in results if status == "blocked"]
    assert len(created) == 1
    assert blocked == ["operator_profile_bootstrap_not_allowed"] * (
        contender_count - 1
    )
    stored = repository.list_for_principal(
        principal_id="principal-concurrent-bootstrap",
        status="active",
        limit=100,
    )
    assert [row.operator_id for row in stored] == created


class _FakeTransaction(AbstractContextManager[None]):
    def __init__(self, events: list[str]) -> None:
        self._events = events

    def __enter__(self) -> None:
        self._events.append("transaction_enter")
        return None

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self._events.append("transaction_exit")
        return None


class _FakeCursor(AbstractContextManager["_FakeCursor"]):
    def __init__(self, *, existing: bool, existing_role: str = "operator") -> None:
        self.existing = existing
        self.existing_role = existing_role
        self.executions: list[tuple[str, tuple[object, ...]]] = []
        self._last_sql = ""

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        return None

    def execute(self, sql: str, params: tuple[object, ...] = ()) -> None:
        normalized_sql = " ".join(str(sql).split())
        self._last_sql = normalized_sql
        self.executions.append((normalized_sql, tuple(params)))

    def fetchone(self) -> tuple[Any, ...] | None:
        if self._last_sql.startswith("SELECT operator_id FROM operator_profiles"):
            if self.existing and self.existing_role != self.existing_role.lower():
                assert "LOWER(BTRIM(access_role.role_name))" in self._last_sql
            return ("operator-existing",) if self.existing else None
        if self._last_sql.startswith("INSERT INTO operator_profiles"):
            params = self.executions[-1][1]
            return (
                params[0],
                params[1],
                params[2],
                params[3],
                params[4],
                params[5],
                params[6],
                params[7],
                params[8],
                params[9],
            )
        raise AssertionError(f"unexpected fetchone after {self._last_sql}")


class _FakeConnection(AbstractContextManager["_FakeConnection"]):
    def __init__(
        self,
        *,
        existing: bool,
        existing_role: str = "operator",
    ) -> None:
        self.events: list[str] = []
        self.cursor_instance = _FakeCursor(
            existing=existing,
            existing_role=existing_role,
        )

    def __enter__(self) -> "_FakeConnection":
        self.events.append("connection_enter")
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.events.append("connection_exit")
        return None

    def transaction(self) -> _FakeTransaction:
        return _FakeTransaction(self.events)

    def cursor(self) -> _FakeCursor:
        return self.cursor_instance


def _postgres_repository_contract(
    *,
    existing: bool,
    existing_role: str = "operator",
) -> tuple[PostgresOperatorProfileRepository, _FakeConnection]:
    connection = _FakeConnection(
        existing=existing,
        existing_role=existing_role,
    )
    repository = object.__new__(PostgresOperatorProfileRepository)
    repository._database_url = "postgresql://contract-only"  # type: ignore[attr-defined]
    repository._connect = lambda: connection  # type: ignore[method-assign]
    repository._json_value = lambda values: values  # type: ignore[method-assign]
    return repository, connection


def test_postgres_operator_bootstrap_locks_and_checks_inside_one_transaction() -> None:
    repository, connection = _postgres_repository_contract(existing=False)

    profile = repository.bootstrap_profile_if_none(
        principal_id="principal-postgres-bootstrap",
        operator_id="operator-created",
        display_name="Created Operator",
        roles=("operator", "reviewer"),
    )

    assert profile is not None
    assert profile.operator_id == "operator-created"
    assert connection.events == [
        "connection_enter",
        "transaction_enter",
        "transaction_exit",
        "connection_exit",
    ]
    executions = connection.cursor_instance.executions
    assert "pg_advisory_xact_lock" in executions[0][0]
    assert executions[0][1] == (
        "ea:operator-profile-bootstrap:v1:principal-postgres-bootstrap",
    )
    assert executions[1][0].startswith("SELECT operator_id FROM operator_profiles")
    assert "jsonb_array_elements_text" in executions[1][0]
    assert "LOWER(BTRIM(access_role.role_name))" in executions[1][0]
    assert executions[2][0].startswith("INSERT INTO operator_profiles")


def test_postgres_operator_bootstrap_returns_none_without_second_insert() -> None:
    repository, connection = _postgres_repository_contract(existing=True)

    profile = repository.bootstrap_profile_if_none(
        principal_id="principal-postgres-bootstrap",
        operator_id="operator-loser",
        display_name="Losing Operator",
        roles=("operator", "reviewer"),
    )

    assert profile is None
    executions = connection.cursor_instance.executions
    assert len(executions) == 2
    assert "pg_advisory_xact_lock" in executions[0][0]
    assert executions[1][0].startswith("SELECT operator_id FROM operator_profiles")
    assert all(not sql.startswith("INSERT") for sql, _params in executions)


def test_postgres_operator_bootstrap_casefolds_existing_access_roles() -> None:
    repository, connection = _postgres_repository_contract(
        existing=True,
        existing_role="Operator",
    )

    profile = repository.bootstrap_profile_if_none(
        principal_id="principal-with-mixed-case-operator",
        operator_id="operator-loser",
        display_name="Losing Operator",
        roles=("operator",),
    )

    assert profile is None
    select_sql = connection.cursor_instance.executions[1][0]
    assert "LOWER(BTRIM(access_role.role_name))" in select_sql
    assert "ARRAY['operator', 'admin', 'reviewer', 'cloudflare_access']" in select_sql
    assert all(
        not sql.startswith("INSERT")
        for sql, _params in connection.cursor_instance.executions
    )
