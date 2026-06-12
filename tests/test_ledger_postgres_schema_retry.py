from __future__ import annotations

from app.repositories import ledger_postgres


class _FakeDeadlock(Exception):
    sqlstate = "40P01"


def test_postgres_ledger_schema_bootstrap_retries_deadlocks(monkeypatch) -> None:
    calls = {"count": 0}
    sleeps: list[float] = []

    def fake_ensure_schema(self) -> None:
        calls["count"] += 1
        if calls["count"] == 1:
            raise _FakeDeadlock("startup race")

    monkeypatch.setattr(ledger_postgres.PostgresExecutionLedgerRepository, "_ensure_schema", fake_ensure_schema)
    monkeypatch.setattr(ledger_postgres.time, "sleep", lambda delay: sleeps.append(delay))

    ledger_postgres.PostgresExecutionLedgerRepository("postgresql://example.invalid/ea")

    assert calls["count"] == 2
    assert sleeps == [0.05]


def test_postgres_ledger_schema_bootstrap_does_not_retry_non_transient_errors(monkeypatch) -> None:
    calls = {"count": 0}
    sleeps: list[float] = []

    def fake_ensure_schema(self) -> None:
        calls["count"] += 1
        raise ValueError("bad schema")

    monkeypatch.setattr(ledger_postgres.PostgresExecutionLedgerRepository, "_ensure_schema", fake_ensure_schema)
    monkeypatch.setattr(ledger_postgres.time, "sleep", lambda delay: sleeps.append(delay))

    try:
        ledger_postgres.PostgresExecutionLedgerRepository("postgresql://example.invalid/ea")
    except ValueError:
        pass
    else:  # pragma: no cover - defensive assertion clarity
        raise AssertionError("expected non-transient schema errors to propagate")

    assert calls["count"] == 1
    assert sleeps == []
