from __future__ import annotations

import asyncio
from types import SimpleNamespace

from fastapi import FastAPI
from starlette.requests import Request

from app.api.routes import health


def _request(*, client_host: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/health",
            "headers": [],
            "client": (client_host, 49152),
        }
    )


def test_health_live_redacts_memorial_probe_for_non_loopback(monkeypatch) -> None:
    monkeypatch.setenv("EA_HEALTHCHECK_MEMORIAL_SLUG", "manfred")
    monkeypatch.setattr(
        health,
        "_probe_public_memorial_surface",
        lambda slug: {"slug": slug, "voice_plugin": "unmixr_clone", "audio_clip_count": 3, "elapsed_ms": 8.4},
    )

    response = asyncio.run(health.health_live(_request(client_host="198.51.100.10")))

    assert response == {"status": "live"}


def test_health_live_loopback_reports_enabled_unmounted_memorial_runtime(monkeypatch) -> None:
    monkeypatch.setenv("EA_HEALTHCHECK_MEMORIAL_SLUG", "manfred")
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    monkeypatch.setenv("EA_ENABLE_PUBLIC_SIDE_SURFACES", "1")

    response = asyncio.run(health.health_live(_request(client_host="127.0.0.1")))

    assert response["status"] == "live"
    assert response["memorial_runtime"]["state"] == "enabled_unmounted"
    assert response["memorial_runtime"]["configured_enabled"] is True
    assert response["memorial_runtime"]["route_mounted"] is False
    assert response["memorial_runtime"]["next_action"] == "start_runtime_with_memorial_overlay"


def test_version_redacts_runtime_metadata_for_non_loopback(monkeypatch) -> None:
    summary = {
        "state": "clear",
        "authority_posture": "authoritative_runtime",
        "source": "published_status_artifact",
        "repository": "ArchonMegalon/executive-assistant",
        "branch": "main",
        "tracking_branch": "origin/main",
        "commit_sha": "a" * 40,
        "source_remote_ref": "refs/remotes/origin/main",
        "source_remote_ref_commit_sha": "a" * 40,
        "source_remote_ref_evidence": "local_remote_tracking_ref",
        "source_commit_reachable_from_remote_ref": True,
        "deployment_id": "deploy-123",
        "deployment_id_source": "explicit",
        "public_origin": "https://ea.example.test",
        "public_origin_source": "EA_PUBLIC_APP_BASE_URL",
        "project_mode": "ea-core",
        "generated_at": "2026-06-23T00:00:00Z",
    }
    product = SimpleNamespace(release_authority_summary=lambda: dict(summary))
    monkeypatch.setattr(health, "build_product_service", lambda container: product)
    container = SimpleNamespace(settings=SimpleNamespace(app_name="EA", app_version="1.0", role="api", storage_backend="postgres"))

    payload = asyncio.run(health.version(_request(client_host="198.51.100.10"), container))

    assert payload["app_name"] == "EA"
    assert payload["release_authority_state"] == "clear"
    assert payload["release_authority_posture"] == "authoritative_runtime"
    assert payload["release_authority_source"] == "published_status_artifact"
    assert payload["release_manifest_generated_at"] == "2026-06-23T00:00:00Z"
    assert "commit_sha" not in payload
    assert "deployment_id" not in payload
    assert "public_origin" not in payload
    assert "branch" not in payload
    assert "source_remote_ref" not in payload
    assert "source_commit_reachable_from_remote_ref" not in payload


def test_version_loopback_projects_remote_source_binding(monkeypatch) -> None:
    summary = {
        "state": "clear",
        "authority_posture": "authoritative_runtime",
        "source": "published_status_artifact",
        "tracking_branch": "origin/main",
        "commit_sha": "a" * 40,
        "source_remote_ref": "refs/remotes/origin/main",
        "source_remote_ref_commit_sha": "b" * 40,
        "source_remote_ref_evidence": "local_remote_tracking_ref",
        "source_commit_reachable_from_remote_ref": True,
    }
    product = SimpleNamespace(release_authority_summary=lambda: dict(summary))
    monkeypatch.setattr(health, "build_product_service", lambda container: product)
    container = SimpleNamespace(
        settings=SimpleNamespace(
            app_name="EA",
            app_version="1.0",
            role="api",
            storage_backend="postgres",
        )
    )

    payload = asyncio.run(health.version(_request(client_host="127.0.0.1"), container))

    assert payload["source_remote_ref"] == "refs/remotes/origin/main"
    assert payload["source_remote_ref_commit_sha"] == "b" * 40
    assert payload["source_remote_ref_evidence"] == "local_remote_tracking_ref"
    assert payload["source_commit_reachable_from_remote_ref"] is True


def test_version_openapi_precisely_allows_string_and_boolean_values() -> None:
    app = FastAPI()
    app.include_router(health.router)

    schema = app.openapi()["paths"]["/version"]["get"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]

    assert schema["type"] == "object"
    assert schema["additionalProperties"] == {
        "anyOf": [{"type": "string"}, {"type": "boolean"}]
    }


def test_release_authority_redacts_internal_metadata_for_non_loopback(monkeypatch) -> None:
    release_summary = {
        "state": "clear",
        "authority_posture": "authoritative_runtime",
        "source": "published_status_artifact",
        "manifest_path": "/app/.codex-studio/published/release_manifest.generated.json",
        "deploy_context_path": "/app/.codex-studio/published/deploy_context.generated.json",
        "branch": "main",
        "tracking_branch": "origin/main",
        "commit_sha": "b" * 40,
        "source_remote_ref": "refs/remotes/origin/main",
        "source_remote_ref_commit_sha": "b" * 40,
        "source_remote_ref_evidence": "local_remote_tracking_ref",
        "source_commit_reachable_from_remote_ref": True,
        "gate": {"contract_name": "ea.release_authority_gate.v1", "status": "pass", "issues": []},
        "deploy_context_gate": {"contract_name": "ea.deploy_context_gate.v1", "status": "pass", "issues": []},
    }
    supply_summary = {
        "state": "clear",
        "requirements_lock_path": "/app/requirements.lock",
        "gate": {"contract_name": "ea.runtime_supply_chain.v1", "status": "pass", "issues": []},
    }
    product = SimpleNamespace(
        release_authority_summary=lambda: dict(release_summary),
        runtime_supply_chain_summary=lambda: dict(supply_summary),
    )
    monkeypatch.setattr(health, "build_product_service", lambda container: product)

    payload = asyncio.run(health.health_release_authority(_request(client_host="198.51.100.10"), SimpleNamespace()))

    assert payload["release_authority"]["state"] == "clear"
    assert payload["release_authority"]["authority_posture"] == "authoritative_runtime"
    assert payload["release_authority"]["source"] == "published_status_artifact"
    assert payload["release_authority_gate"]["contract_name"] == "ea.release_authority_gate.v1"
    assert payload["deploy_context_gate"]["contract_name"] == "ea.deploy_context_gate.v1"
    assert payload["runtime_supply_chain"]["state"] == "clear"
    assert payload["runtime_supply_chain_gate"]["contract_name"] == "ea.runtime_supply_chain.v1"
    assert "manifest_path" not in payload["release_authority"]
    assert "deploy_context_path" not in payload["release_authority"]
    assert "commit_sha" not in payload["release_authority"]
    assert "source_remote_ref" not in payload["release_authority"]
    assert "source_commit_reachable_from_remote_ref" not in payload["release_authority"]
    assert "requirements_lock_path" not in payload["runtime_supply_chain"]
