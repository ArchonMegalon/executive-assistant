from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from app.domain.models import ToolInvocationResult
from app.services.ltd_runtime_catalog import LtdRuntimeCatalogService
from tests.product_test_helpers import build_operator_product_client


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
| `FlipLink.me` | `Tier 10` | `1 account` | `Owned` |  | `Tier 2` | Local `.env` credentials plus bounded PropertyQuarry review-packet flipbook lane | Use only for shareable redacted review packets downstream of PropertyQuarry. |
| `MarkupGo` | `7x code-based` | `7 codes` | `Activated` |  | `Tier 3` | None | BrowserAct workspace reader exists even though the direct provider lane is not executable. |
""".strip()


def _client(*, principal_id: str = "ops-1") -> TestClient:
    os.environ["EA_STORAGE_BACKEND"] = "memory"
    os.environ["PROPERTYQUARRY_ENABLE_LEGACY_RUNTIME_SURFACES"] = "1"
    return build_operator_product_client(principal_id=principal_id, operator_id=f"{principal_id}-operator")


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
    assert {"1min.AI", "Documentation.AI", "Emailit", "FlipLink.me", "MarkupGo"} <= service_names

    documentation = next(row for row in body if row["service_name"] == "Documentation.AI")
    assert documentation["runtime_state"] == "browseract_ui_ready"
    assert {action["action_key"] for action in documentation["actions"]} == {
        "discover_account",
        "inspect_workspace",
    }

    fliplink = next(row for row in body if row["service_name"] == "FlipLink.me")
    assert fliplink["runtime_state"] == "runtime_managed"
    assert {action["action_key"] for action in fliplink["actions"]} == {
        "discover_account",
        "publish_property_flipbook",
    }


def test_ltd_provider_lanes_route_lists_governed_lane_receipts(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(principal_id="ops-ltd-lanes")
    from app.api.routes import ltd_runtime as ltd_runtime_route

    monkeypatch.setattr(
        ltd_runtime_route,
        "build_ltd_provider_governance_receipt",
        lambda: {
            "status": "pass",
            "lane_count": 2,
            "lanes": [
                {
                    "lane_key": "fliplink_document_portal",
                    "status": "pass",
                    "not_source_of_truth": True,
                    "runtime_enabled": False,
                    "missing_checks": ["first_publication_receipt"],
                },
                {
                    "lane_key": "release_quality_gates",
                    "status": "pass",
                    "not_source_of_truth": True,
                    "runtime_enabled": True,
                    "missing_checks": [],
                },
            ],
        },
    )

    response = client.get("/v1/ltds/runtime-catalog/provider-lanes")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "pass"
    assert body["lane_count"] == 2
    assert {lane["lane_key"] for lane in body["lanes"]} == {
        "fliplink_document_portal",
        "release_quality_gates",
    }


def test_ltd_provider_lane_route_returns_one_receipt(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(principal_id="ops-ltd-lane")
    from app.api.routes import ltd_runtime as ltd_runtime_route

    monkeypatch.setattr(
        ltd_runtime_route,
        "build_ltd_provider_governance_receipt",
        lambda: {
            "status": "pass",
            "lanes": [
                {
                    "lane_key": "unmixr_voice_runtime",
                    "status": "pass",
                    "not_source_of_truth": True,
                    "runtime_enabled": False,
                    "missing_checks": ["voice_roundtrip_validation"],
                },
            ],
        },
    )

    response = client.get("/v1/ltds/runtime-catalog/provider-lanes/unmixr-voice-runtime")

    assert response.status_code == 200
    body = response.json()
    assert body["lane_key"] == "unmixr_voice_runtime"
    assert body["not_source_of_truth"] is True
    assert body["runtime_enabled"] is False
    assert body["missing_checks"] == ["voice_roundtrip_validation"]


def test_ltd_provider_contracts_route_returns_operator_status(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(principal_id="ops-provider-contracts")
    from app.api.routes import ltd_runtime as ltd_runtime_route

    monkeypatch.setattr(
        ltd_runtime_route,
        "build_provider_contract_status",
        lambda: {
            "contract_name": "ea.provider_contract_status",
            "status": "pass",
            "contract_receipt_count": 5,
            "contract_receipts_valid": 5,
            "live_provider_runtime_verified": False,
            "gold_claim_allowed": False,
            "not_live_provider_proof": True,
            "not_release_gold_proof": True,
            "operator_label": "Provider contract layer is exercised; live provider receipts and E2E proof are still pending.",
            "rows": [
                {
                    "key": "hedy_meeting_evidence",
                    "status": "contract_pass",
                    "issues": [],
                    "required_next_receipts": ["_completion/hedy/HEDY_PROVIDER_CAPABILITY.generated.json"],
                }
            ],
        },
    )

    response = client.get("/v1/ltds/runtime-catalog/provider-contracts")

    assert response.status_code == 200
    body = response.json()
    assert body["contract_name"] == "ea.provider_contract_status"
    assert body["status"] == "pass"
    assert body["live_provider_runtime_verified"] is False
    assert body["gold_claim_allowed"] is False
    assert body["not_live_provider_proof"] is True
    assert body["rows"][0]["key"] == "hedy_meeting_evidence"


def test_ltd_provider_lane_route_404s_unknown_lane(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(principal_id="ops-ltd-lane-missing")
    from app.api.routes import ltd_runtime as ltd_runtime_route

    monkeypatch.setattr(
        ltd_runtime_route,
        "build_ltd_provider_governance_receipt",
        lambda: {"status": "pass", "lanes": []},
    )

    response = client.get("/v1/ltds/runtime-catalog/provider-lanes/missing")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ltd_provider_lane_not_found"


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
