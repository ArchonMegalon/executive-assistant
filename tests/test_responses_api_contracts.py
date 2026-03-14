from __future__ import annotations

import os

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient


def _client(*, principal_id: str) -> TestClient:
    os.environ["EA_STORAGE_BACKEND"] = "memory"
    os.environ.pop("EA_LEDGER_BACKEND", None)
    os.environ.pop("EA_DEFAULT_PRINCIPAL_ID", None)
    os.environ["EA_API_TOKEN"] = ""
    from app.api.app import create_app

    client = TestClient(create_app())
    client.headers.update({"X-EA-Principal-ID": principal_id})
    return client


def test_responses_non_stream_returns_response_object() -> None:
    client = _client(principal_id="codex-test")
    container = client.app.state.container

    tool_name = "provider.gemini_vortex.structured_generate"
    container.tool_runtime.upsert_tool(tool_name=tool_name, version="v1")

    from app.domain.models import ToolInvocationResult

    def fake_handler(request, definition):
        return ToolInvocationResult(
            tool_name=definition.tool_name,
            action_kind=request.action_kind,
            target_ref="fake:1",
            output_json={
                "structured_output_json": {"text": "hello from ea"},
                "normalized_text": '{"text":"hello from ea"}',
                "mime_type": "application/json",
            },
            receipt_json={"handler_key": "fake"},
            model_name="fake",
            tokens_in=11,
            tokens_out=7,
            cost_usd=0.0,
        )

    container.tool_execution.register_handler(tool_name, fake_handler)

    resp = client.post("/v1/responses", json={"model": "ea-coder-small", "input": "say hi"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["object"] == "response"
    assert body["status"] == "completed"
    assert body["output_text"] == "hello from ea"
    assert body["output"][0]["type"] == "message"
    assert body["output"][0]["role"] == "assistant"
    assert body["output"][0]["content"][0]["type"] == "output_text"
    assert body["output"][0]["content"][0]["text"] == "hello from ea"
    assert body["usage"]["input_tokens"] == 11
    assert body["usage"]["output_tokens"] == 7


def test_responses_stream_emits_sse_events() -> None:
    client = _client(principal_id="codex-test")
    container = client.app.state.container

    tool_name = "provider.gemini_vortex.structured_generate"
    container.tool_runtime.upsert_tool(tool_name=tool_name, version="v1")

    from app.domain.models import ToolInvocationResult

    def fake_handler(request, definition):
        return ToolInvocationResult(
            tool_name=definition.tool_name,
            action_kind=request.action_kind,
            target_ref="fake:1",
            output_json={
                "structured_output_json": {"text": "stream me"},
                "normalized_text": '{"text":"stream me"}',
                "mime_type": "application/json",
            },
            receipt_json={"handler_key": "fake"},
            model_name="fake",
            tokens_in=1,
            tokens_out=2,
            cost_usd=0.0,
        )

    container.tool_execution.register_handler(tool_name, fake_handler)

    with client.stream("POST", "/v1/responses", json={"model": "ea-coder-small", "input": "stream", "stream": True}) as resp:
        assert resp.status_code == 200
        assert "text/event-stream" in (resp.headers.get("content-type") or "")
        body = "".join(resp.iter_text())
    assert "event: response.created" in body
    assert "event: response.output_text.delta" in body
    assert "event: response.completed" in body

