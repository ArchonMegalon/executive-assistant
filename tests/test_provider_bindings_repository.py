from __future__ import annotations

from app.repositories.provider_bindings import InMemoryProviderBindingRepository, build_provider_binding_repo
from app.settings import get_settings


def test_inmemory_provider_binding_repo_updates_probe_state() -> None:
    repo = InMemoryProviderBindingRepository()
    record = repo.upsert(principal_id="exec-1", provider_key="browseract", status="enabled")

    updated = repo.set_probe(record.binding_id, "ready", {"latency_ms": 120})

    assert updated is not None
    assert updated.probe_state == "ready"
    assert updated.probe_details_json == {"latency_ms": 120}


def test_build_provider_binding_repo_defaults_to_memory(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("EA_STORAGE_BACKEND", raising=False)

    repo = build_provider_binding_repo(get_settings())

    assert isinstance(repo, InMemoryProviderBindingRepository)


def test_build_provider_binding_repo_uses_postgres_when_database_url_is_configured(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://example.invalid/ea")
    monkeypatch.delenv("EA_STORAGE_BACKEND", raising=False)

    class FakePostgresProviderBindingRepository:
        def __init__(self, database_url: str) -> None:
            self.database_url = database_url

    monkeypatch.setattr(
        "app.repositories.provider_bindings_postgres.PostgresProviderBindingRepository",
        FakePostgresProviderBindingRepository,
    )

    repo = build_provider_binding_repo(get_settings())

    assert isinstance(repo, FakePostgresProviderBindingRepository)
    assert repo.database_url == "postgresql://example.invalid/ea"


def test_inmemory_provider_binding_repo_upsert_reuses_binding_id_for_same_principal_provider() -> None:
    repo = InMemoryProviderBindingRepository()

    created = repo.upsert(principal_id="exec-1", provider_key="browseract", status="enabled")
    updated = repo.upsert(principal_id="exec-1", provider_key="browseract", status="disabled")

    assert updated.binding_id == created.binding_id
    assert updated.status == "disabled"
    assert len(repo.list_for_principal("exec-1")) == 1
