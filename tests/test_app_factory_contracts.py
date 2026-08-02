from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[1]


def _client(
    *,
    principal_id: str = "exec-app-factory",
    public_results_enabled: bool = False,
    public_tours_enabled: bool = False,
    runtime_mode: str = "dev",
    legacy_runtime_surfaces_enabled: bool | None = None,
) -> TestClient:
    os.environ["EA_STORAGE_BACKEND"] = "memory"
    os.environ.pop("EA_LEDGER_BACKEND", None)
    os.environ["EA_RUNTIME_MODE"] = runtime_mode
    if runtime_mode == "prod":
        os.environ["EA_API_TOKEN"] = "prod-app-factory-token"
        os.environ["EA_SIGNING_SECRET"] = "prod-app-factory-signing-secret"
        os.environ["DATABASE_URL"] = "postgresql://example.invalid/ea"
        os.environ["EA_PUBLIC_APP_BASE_URL"] = "https://assistant.example.test"
    else:
        os.environ["EA_API_TOKEN"] = ""
        os.environ.pop("EA_SIGNING_SECRET", None)
        os.environ.pop("DATABASE_URL", None)
        os.environ.pop("EA_PUBLIC_APP_BASE_URL", None)
    os.environ["EA_ENABLE_PUBLIC_RESULTS"] = "1" if public_results_enabled else "0"
    os.environ["EA_ENABLE_PUBLIC_TOURS"] = "1" if public_tours_enabled else "0"
    os.environ["EA_ENABLE_PUBLIC_SIDE_SURFACES"] = "1" if (public_results_enabled or public_tours_enabled) else "0"
    if legacy_runtime_surfaces_enabled is None:
        os.environ.pop("EA_ENABLE_LEGACY_RUNTIME_SURFACES", None)
    else:
        os.environ["EA_ENABLE_LEGACY_RUNTIME_SURFACES"] = "1" if legacy_runtime_surfaces_enabled else "0"
    from app.api.app import create_app

    client = TestClient(create_app())
    client.headers.update({"X-EA-Principal-ID": principal_id})
    return client


def test_app_factory_uses_helper_mount_functions() -> None:
    source = (REPO_ROOT / "ea/app/api/app.py").read_text(encoding="utf-8")

    assert "def _include_public_routes(" in source
    assert "def _include_authenticated_routes(" in source
    assert "def _include_secret_verified_ingress_routes(" in source
    assert "_include_public_routes(" in source
    assert "_include_authenticated_routes(" in source
    assert "_include_secret_verified_ingress_routes(" in source


def test_app_factory_omits_optional_public_routes_by_default() -> None:
    client = _client()
    route_paths = {route.path for route in client.app.routes}

    assert "/results/{slug}" not in route_paths
    assert "/results/{slug}.json" not in route_paths
    assert "/tours/{slug}.json" not in route_paths
    assert "/tours/files/{slug}/{asset_path:path}" not in route_paths
    assert not any(path.startswith("/memorials") for path in route_paths)


def test_app_factory_mounts_only_owned_optional_public_routes_when_enabled() -> None:
    client = _client(public_results_enabled=True, public_tours_enabled=True)
    route_paths = {route.path for route in client.app.routes}

    assert "/results/{slug}" in route_paths
    assert "/results/{slug}.json" in route_paths
    assert "/results/files/{slug}/{asset_path:path}" in route_paths
    assert "/tours/{slug}.json" in route_paths
    assert "/tours/files/{slug}/{asset_path:path}" in route_paths
    assert not any(path.startswith("/memorials") for path in route_paths)


def test_app_factory_keeps_secret_verified_telegram_ingress_when_legacy_routes_are_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EA_TELEGRAM_BOT_TOKEN", "telegram-test-token")
    monkeypatch.setenv("EA_TELEGRAM_INGEST_SECRET", "telegram-test-secret")
    client = _client(runtime_mode="dev", legacy_runtime_surfaces_enabled=False)
    route_paths = {route.path for route in client.app.routes}

    assert "/v1/memory/candidates" not in route_paths
    assert "/v1/rewrite/artifact" not in route_paths
    assert "/v1/channels/telegram/ingest" in route_paths
    assert "/v1/responses" not in route_paths
    rejected = client.post(
        "/v1/channels/telegram/ingest",
        headers={"X-Telegram-Bot-Api-Secret-Token": "wrong-secret"},
        json={"update_id": 1},
    )
    assert rejected.status_code == 403
    assert rejected.json()["error"]["details"] == "telegram_secret_invalid"


def test_app_factory_mounts_legacy_authenticated_routes_when_explicitly_enabled() -> None:
    client = _client(runtime_mode="dev", legacy_runtime_surfaces_enabled=True)
    route_paths = {route.path for route in client.app.routes}

    assert "/v1/memory/candidates" in route_paths
    assert "/v1/rewrite/artifact" in route_paths
    assert "/v1/channels/telegram/ingest" in route_paths
    assert "/v1/responses" in route_paths


def test_telegram_ingress_fails_closed_when_secret_is_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EA_TELEGRAM_BOT_TOKEN", "telegram-test-token")
    monkeypatch.delenv("EA_TELEGRAM_INGEST_SECRET", raising=False)
    monkeypatch.delenv("EA_TELEGRAM_BOT_REGISTRY_JSON", raising=False)
    client = _client(runtime_mode="dev", legacy_runtime_surfaces_enabled=False)

    response = client.post(
        "/v1/channels/telegram/ingest",
        json={"update_id": 1},
    )

    assert response.status_code == 503
    assert response.json()["error"]["details"] == "telegram_ingest_secret_not_configured"
