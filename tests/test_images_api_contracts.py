from __future__ import annotations

import os

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from app.domain.models import ToolInvocationResult
from app.services.tool_execution_common import ToolExecutionError


def _client(*, principal_id: str) -> TestClient:
    os.environ["EA_STORAGE_BACKEND"] = "memory"
    os.environ.pop("EA_LEDGER_BACKEND", None)
    os.environ.pop("EA_DEFAULT_PRINCIPAL_ID", None)
    os.environ["EA_API_TOKEN"] = ""
    os.environ.pop("EA_TRUST_AUTHENTICATED_PRINCIPAL_HEADER", None)
    os.environ.pop("EA_OPERATOR_PRINCIPAL_IDS", None)
    from app.api.app import create_app

    client = TestClient(create_app())
    client.headers.update({"X-EA-Principal-ID": principal_id})
    return client


def test_images_generation_route_prefers_comfyui_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COMFYUI_URL", "https://images.example")
    client = _client(principal_id="exec-images")
    from app.api.routes import images

    def _fake_execute_tool(*, container, context, tool_name: str, payload_json: dict[str, object]) -> ToolInvocationResult:
        assert tool_name == "provider.comfyui.image_generate"
        assert payload_json["prompt"] == "Render a hero image."
        return ToolInvocationResult(
            tool_name=tool_name,
            action_kind="image.generate",
            target_ref="comfyui:test",
            output_json={
                "asset_urls": ["https://images.example/view?filename=hero.png&type=output"],
                "provider_backend": "comfyui",
            },
            receipt_json={"provider_key": "comfyui"},
            model_name="SDXL-Lightning-4step",
            tokens_in=0,
            tokens_out=0,
            cost_usd=0.0,
        )

    monkeypatch.setattr(images, "_execute_tool", _fake_execute_tool)

    response = client.post(
        "/v1/images/generations",
        json={
            "prompt": "Render a hero image.",
            "size": "1024x1024",
            "response_format": "url",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "comfyui"
    assert body["fallback_used"] is False
    assert body["data"] == [{"url": "https://images.example/view?filename=hero.png&type=output"}]


def test_images_generation_route_falls_back_to_onemin_when_comfyui_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COMFYUI_URL", "https://images.example")
    client = _client(principal_id="exec-images")
    from app.api.routes import images

    calls: list[str] = []

    def _fake_execute_tool(*, container, context, tool_name: str, payload_json: dict[str, object]) -> ToolInvocationResult:
        calls.append(tool_name)
        if tool_name == "provider.comfyui.image_generate":
            raise ToolExecutionError("comfyui_connection_failed:timeout")
        assert tool_name == "provider.onemin.image_generate"
        assert payload_json["prompt"] == "Render a fallback image."
        return ToolInvocationResult(
            tool_name=tool_name,
            action_kind="image.generate",
            target_ref="onemin:test",
            output_json={
                "asset_urls": ["https://cdn.1min.ai/generated/fallback.png"],
                "provider_backend": "1min",
            },
            receipt_json={"provider_key": "onemin"},
            model_name="gpt-image-1-mini",
            tokens_in=0,
            tokens_out=0,
            cost_usd=0.0,
        )

    monkeypatch.setattr(images, "_execute_tool", _fake_execute_tool)

    response = client.post(
        "/api/v1/images/generations",
        json={
            "prompt": "Render a fallback image.",
            "size": "1024x1024",
            "response_format": "url",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert calls == ["provider.comfyui.image_generate", "provider.onemin.image_generate"]
    assert body["provider"] == "onemin"
    assert body["fallback_used"] is True
    assert body["data"] == [{"url": "https://cdn.1min.ai/generated/fallback.png"}]
