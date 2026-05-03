from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from app.domain.models import ToolInvocationResult
from app.services.ltd_runtime_catalog import LtdRuntimeCatalogService


def _sample_ltd_markdown() -> str:
    return """
# LTDs

Updated: 2026-05-02

## Non-AppSumo / Other LTDs

| Service | Plan / Tier | Holding | Status | Redeem By | Workspace Integration Tier | Local Integration | Notes |
|---|---|---|---|---|---|---|---|
| `1min.AI` | `Advanced Business Plan` | `12 licenses` | `Owned` |  | `Tier 1` | Local `.env` key rotation slots | Primary API-key lane is already wired. |
| `Emailit` | `Tier 5` | `1 key` | `Owned` |  | `Tier 1` | Local `.env` key plus sender-domain wiring | Transactional delivery already runs through EA. |

## AppSumo LTDs

| Service | Plan / Tier | Holding | Status | Redeem By | Workspace Integration Tier | Local Integration | Notes |
|---|---|---|---|---|---|---|---|
| `Documentation.AI` | `License Tier 3` | `1 license` | `Activated` |  | `Tier 4` | Local `.env` username/password only | Owned for operator docs and cited answers. |
| `MarkupGo` | `7x code-based` | `7 codes` | `Activated` |  | `Tier 3` | None | BrowserAct workspace reader exists even though the direct provider lane is not executable. |
""".strip()


def _client(*, principal_id: str = "ops-1") -> TestClient:
    os.environ["EA_STORAGE_BACKEND"] = "memory"
    os.environ["EA_API_TOKEN"] = "test-token"
    os.environ["EA_TRUST_AUTHENTICATED_PRINCIPAL_HEADER"] = "1"
    os.environ["EA_OPERATOR_PRINCIPAL_IDS"] = principal_id
    from app.api.app import create_app

    client = TestClient(create_app())
    client.headers.update({"Authorization": "Bearer test-token"})
    client.headers.update({"X-EA-Principal-ID": principal_id})
    return client


def _patch_catalog(monkeypatch: pytest.MonkeyPatch, client: TestClient, tmp_path: Path) -> None:
    markdown_path = tmp_path / "LTDs.md"
    markdown_path.write_text(_sample_ltd_markdown(), encoding="utf-8")
    from app.api.routes import ltd_runtime as ltd_runtime_route

    monkeypatch.setattr(
        ltd_runtime_route,
        "_catalog",
        lambda container: LtdRuntimeCatalogService(
            provider_registry=container.provider_registry,
            markdown_path=markdown_path,
        ),
    )


def test_ltd_runtime_catalog_route_lists_profiles(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = _client()
    _patch_catalog(monkeypatch, client, tmp_path)

    response = client.get("/v1/ltds/runtime-catalog")
    assert response.status_code == 200
    body = response.json()
    service_names = {row["service_name"] for row in body}
    assert {"1min.AI", "Documentation.AI", "Emailit", "MarkupGo"} <= service_names

    documentation = next(row for row in body if row["service_name"] == "Documentation.AI")
    assert documentation["runtime_state"] == "browseract_ui_ready"
    assert {action["action_key"] for action in documentation["actions"]} == {
        "discover_account",
        "inspect_workspace",
    }


def test_ltd_runtime_discover_account_executes_browseract_extract(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = _client(principal_id="ops-discover")
    _patch_catalog(monkeypatch, client, tmp_path)

    captured: list[object] = []

    def _fake_execute(request):  # noqa: ANN001
        captured.append(request)
        return ToolInvocationResult(
            tool_name=request.tool_name,
            action_kind=request.action_kind,
            target_ref="browseract://markupgo",
            output_json={"service_name": request.payload_json["service_name"]},
            receipt_json={"principal_id": request.context_json["principal_id"]},
        )

    monkeypatch.setattr(client.app.state.container.tool_execution, "execute_invocation", _fake_execute)

    response = client.post(
        "/v1/ltds/runtime-catalog/MarkupGo/discover-account",
        json={
            "binding_id": "binding-browseract-1",
            "requested_fields": ["tier", "account_email"],
            "instructions": "Verify account facts",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["tool_name"] == "browseract.extract_account_facts"
    assert body["output_json"]["service_name"] == "MarkupGo"
    request = captured[0]
    assert request.tool_name == "browseract.extract_account_facts"
    assert request.payload_json["binding_id"] == "binding-browseract-1"
    assert request.payload_json["requested_fields"] == ["tier", "account_email"]
    assert request.payload_json["service_name"] == "MarkupGo"
    assert request.context_json["principal_id"] == "ops-discover"


def test_ltd_runtime_inspect_workspace_executes_browseract_ui_reader(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = _client(principal_id="ops-inspect")
    _patch_catalog(monkeypatch, client, tmp_path)

    captured: list[object] = []

    def _fake_execute(request):  # noqa: ANN001
        captured.append(request)
        return ToolInvocationResult(
            tool_name=request.tool_name,
            action_kind=request.action_kind,
            target_ref="browseract://documentation-ai",
            output_json={"requested_url": request.payload_json["page_url"]},
            receipt_json={"principal_id": request.context_json["principal_id"]},
        )

    monkeypatch.setattr(client.app.state.container.tool_execution, "execute_invocation", _fake_execute)

    response = client.post(
        "/v1/ltds/runtime-catalog/Documentation.AI/inspect-workspace",
        json={
            "binding_id": "binding-browseract-2",
            "page_url": "https://docs.example/workspace",
            "result_title": "Documentation AI Workspace",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["tool_name"] == "browseract.documentation_ai_workspace_reader"
    assert body["action_key"] == "inspect_workspace"
    request = captured[0]
    assert request.tool_name == "browseract.documentation_ai_workspace_reader"
    assert request.payload_json["page_url"] == "https://docs.example/workspace"
    assert request.context_json["principal_id"] == "ops-inspect"


def test_ltd_runtime_rejects_non_executable_runtime_managed_action(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = _client()
    _patch_catalog(monkeypatch, client, tmp_path)

    response = client.post(
        "/v1/ltds/runtime-catalog/Emailit/actions/delivery_outbox",
        json={},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ltd_runtime_action_not_executable"


def test_ltd_runtime_executes_direct_provider_action(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = _client(principal_id="ops-onemin")
    _patch_catalog(monkeypatch, client, tmp_path)

    captured: list[object] = []

    def _fake_execute(request):  # noqa: ANN001
        captured.append(request)
        return ToolInvocationResult(
            tool_name=request.tool_name,
            action_kind=request.action_kind,
            target_ref="provider://onemin/code",
            output_json={"language": request.payload_json["language"]},
            receipt_json={"principal_id": request.context_json["principal_id"]},
        )

    monkeypatch.setattr(client.app.state.container.tool_execution, "execute_invocation", _fake_execute)

    response = client.post(
        "/v1/ltds/runtime-catalog/1min.AI/actions/code_generate",
        json={
            "prompt": "Create a small CLI",
            "language": "python",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["tool_name"] == "provider.onemin.code_generate"
    request = captured[0]
    assert request.tool_name == "provider.onemin.code_generate"
    assert request.payload_json["prompt"] == "Create a small CLI"
    assert request.payload_json["language"] == "python"
    assert request.context_json["principal_id"] == "ops-onemin"


def test_ltd_runtime_executes_specialized_onemin_background_remove_action(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = _client(principal_id="ops-onemin-media")
    _patch_catalog(monkeypatch, client, tmp_path)

    captured: list[object] = []

    def _fake_execute(request):  # noqa: ANN001
        captured.append(request)
        return ToolInvocationResult(
            tool_name=request.tool_name,
            action_kind=request.action_kind,
            target_ref="provider://onemin/background-remove",
            output_json={"feature_type": request.payload_json["feature_type"]},
            receipt_json={"principal_id": request.context_json["principal_id"]},
        )

    monkeypatch.setattr(client.app.state.container.tool_execution, "execute_invocation", _fake_execute)

    response = client.post(
        "/v1/ltds/runtime-catalog/1min.AI/actions/background_remove",
        json={
            "image_url": "https://example.invalid/notebook.png",
            "output_format": "png",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["tool_name"] == "provider.onemin.media_transform"
    request = captured[0]
    assert request.tool_name == "provider.onemin.media_transform"
    assert request.payload_json["feature_type"] == "BACKGROUND_REMOVER"
    assert request.payload_json["image_url"] == "https://example.invalid/notebook.png"
    assert request.payload_json["action_key"] == "background_remove"
    assert request.context_json["principal_id"] == "ops-onemin-media"
