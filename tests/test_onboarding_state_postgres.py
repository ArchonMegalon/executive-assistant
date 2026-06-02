from __future__ import annotations

from app.domain.models import OnboardingState
from app.repositories.onboarding_state_postgres import PostgresOnboardingStateRepository


class _FakeCursor:
    def __init__(self) -> None:
        self.executions: list[tuple[str, tuple[object, ...] | None]] = []

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def execute(self, query: str, params: tuple[object, ...] | None = None) -> None:
        self.executions.append((query, params))
        if "INSERT INTO onboarding_states" in query:
            assert params is not None
            assert query.count("%s") == len(params)

    def fetchone(self):
        return (
            "onb-1",
            "principal-1",
            "Workspace",
            "personal",
            "AT",
            "en",
            "Europe/Vienna",
            ["google"],
            {"selected_platforms": ["willhaben"], "preference_person_id": "elisabeth", "max_results_per_source": 3},
            {},
            {},
            {},
            "started",
            "2026-06-02T00:00:00+00:00",
            "2026-06-02T00:00:00+00:00",
        )


class _FakeConnection:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor

    def __enter__(self) -> _FakeConnection:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def cursor(self) -> _FakeCursor:
        return self._cursor


def test_postgres_onboarding_upsert_matches_placeholder_count(monkeypatch) -> None:
    schema_cursor = _FakeCursor()
    write_cursor = _FakeCursor()
    connections = [_FakeConnection(schema_cursor), _FakeConnection(write_cursor)]

    def _fake_connect(self):
        return connections.pop(0)

    monkeypatch.setattr(PostgresOnboardingStateRepository, "_connect", _fake_connect)
    repo = PostgresOnboardingStateRepository("postgresql://example")
    monkeypatch.setattr(repo, "get_for_principal", lambda principal_id: None)
    monkeypatch.setattr(repo, "_json_value", lambda value: value)

    row = repo.upsert_state(
        principal_id="principal-1",
        workspace_name="Workspace",
        workspace_mode="personal",
        region="AT",
        language="en",
        timezone="Europe/Vienna",
        selected_channels=("google",),
        property_search_preferences_json={
            "selected_platforms": ["willhaben"],
            "preference_person_id": "elisabeth",
            "max_results_per_source": 3,
        },
        status="started",
    )

    assert isinstance(row, OnboardingState)
    insert_queries = [query for query, _params in write_cursor.executions if "INSERT INTO onboarding_states" in query]
    assert insert_queries
