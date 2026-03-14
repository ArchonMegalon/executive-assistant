from __future__ import annotations

import os
import time

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from app.services.responses_upstream import UpstreamResult


def _client(*, principal_id: str) -> TestClient:
    os.environ["EA_STORAGE_BACKEND"] = "memory"
    os.environ.pop("EA_LEDGER_BACKEND", None)
    os.environ.pop("EA_DEFAULT_PRINCIPAL_ID", None)
    os.environ["EA_API_TOKEN"] = ""
    from app.api.app import create_app

    client = TestClient(create_app())
    client.headers.update({"X-EA-Principal-ID": principal_id})
    return client


def test_responses_non_stream_returns_response_object(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(principal_id="codex-test")
    from app.api.routes import responses

    def fake_generate(
        *,
        prompt: str,
        messages: list[dict[str, str]] | None = None,
        requested_model: str,
        max_output_tokens: int | None = None,
    ) -> UpstreamResult:
        assert prompt == "say hi"
        assert messages == [{"role": "user", "content": "say hi"}]
        assert requested_model == "ea-coder-small"
        assert max_output_tokens is None
        return UpstreamResult(
            text="hello from ea",
            provider_key="magixai",
            model="anthropic/claude-3.5-sonnet",
            tokens_in=11,
            tokens_out=7,
        )

    monkeypatch.setattr(responses, "_generate_upstream_text", fake_generate)

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
    assert body["metadata"]["principal_id"] == "codex-test"
    assert body["metadata"]["upstream_provider"] == "magixai"
    assert body["metadata"]["upstream_model"] == "anthropic/claude-3.5-sonnet"


def test_responses_stream_emits_sse_events(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(principal_id="codex-test")
    from app.api.routes import responses

    def fake_generate(
        *,
        prompt: str,
        messages: list[dict[str, str]] | None = None,
        requested_model: str,
        max_output_tokens: int | None = None,
    ) -> UpstreamResult:
        assert prompt == "stream"
        assert messages == [{"role": "user", "content": "stream"}]
        assert requested_model == "ea-coder-small"
        assert max_output_tokens is None
        return UpstreamResult(
            text="stream me",
            provider_key="onemin",
            model="gpt-5",
            tokens_in=1,
            tokens_out=2,
        )

    monkeypatch.setattr(responses, "_generate_upstream_text", fake_generate)

    with client.stream("POST", "/v1/responses", json={"model": "ea-coder-small", "input": "stream", "stream": True}) as resp:
        assert resp.status_code == 200
        assert "text/event-stream" in (resp.headers.get("content-type") or "")
        body = "".join(resp.iter_text())
    assert "event: response.created" in body
    assert "event: response.output_text.delta" in body
    assert "event: response.completed" in body
    assert "event: response.done" in body
    assert "data: [DONE]" in body


def test_responses_stream_emits_keepalive_while_waiting(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(principal_id="codex-test")
    from app.api.routes import responses

    def fake_generate(
        *,
        prompt: str,
        messages: list[dict[str, str]] | None = None,
        requested_model: str,
        max_output_tokens: int | None = None,
    ) -> UpstreamResult:
        time.sleep(0.03)
        return UpstreamResult(
            text="ok",
            provider_key="magixai",
            model="openai/gpt-5.1-codex-mini",
            tokens_in=2,
            tokens_out=1,
        )

    monkeypatch.setattr(responses, "_generate_upstream_text", fake_generate)
    monkeypatch.setattr(responses, "STREAM_HEARTBEAT_SECONDS", 0.01)

    with client.stream("POST", "/v1/responses", json={"model": "ea-coder-small", "input": "stream", "stream": True}) as resp:
        assert resp.status_code == 200
        body = "".join(resp.iter_text())

    assert ": keep-alive" in body
    assert "event: response.completed" in body


def test_models_list_returns_responses_aliases() -> None:
    client = _client(principal_id="codex-test")

    resp = client.get("/v1/models")
    assert resp.status_code == 200
    body = resp.json()
    model_ids = {item["id"] for item in body["data"]}
    assert "ea-coder-best" in model_ids
    assert "ea-magicx-coder" in model_ids
    assert "ea-onemin-coder" in model_ids


def test_responses_forwards_max_output_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(principal_id="codex-test")
    from app.api.routes import responses

    def fake_generate(
        *,
        prompt: str,
        messages: list[dict[str, str]] | None = None,
        requested_model: str,
        max_output_tokens: int | None = None,
    ) -> UpstreamResult:
        assert prompt == "cap me"
        assert messages == [{"role": "user", "content": "cap me"}]
        assert requested_model == "ea-coder-small"
        assert max_output_tokens == 64
        return UpstreamResult(
            text="bounded",
            provider_key="magixai",
            model="openai/gpt-5.1-codex-mini",
            tokens_in=5,
            tokens_out=2,
        )

    monkeypatch.setattr(responses, "_generate_upstream_text", fake_generate)

    resp = client.post(
        "/v1/responses",
        json={"model": "ea-coder-small", "input": "cap me", "max_output_tokens": 64},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["output_text"] == "bounded"
    assert body["max_output_tokens"] == 64


def test_responses_builds_structured_messages_for_codex_style_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(principal_id="codex-test")
    from app.api.routes import responses

    def fake_generate(
        *,
        prompt: str,
        messages: list[dict[str, str]] | None = None,
        requested_model: str,
        max_output_tokens: int | None = None,
    ) -> UpstreamResult:
        assert prompt == "stay concise\n\nrepo rules\n\nsay ok"
        assert messages == [
            {"role": "system", "content": "base instructions\n\nstay concise"},
            {"role": "user", "content": "repo rules\n\nsay ok"},
        ]
        assert requested_model == "ea-coder-best"
        assert max_output_tokens is None
        return UpstreamResult(
            text="ok",
            provider_key="magixai",
            model="openai/gpt-5.1-codex-mini",
            tokens_in=3,
            tokens_out=1,
        )

    monkeypatch.setattr(responses, "_generate_upstream_text", fake_generate)

    resp = client.post(
        "/v1/responses",
        json={
            "model": "ea-coder-best",
            "instructions": "base instructions",
            "input": [
                {
                    "role": "developer",
                    "content": [{"type": "input_text", "text": "stay concise"}],
                },
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": "repo rules"}],
                },
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": "say ok"}],
                },
            ],
        },
    )

    assert resp.status_code == 200
    assert resp.json()["output_text"] == "ok"
