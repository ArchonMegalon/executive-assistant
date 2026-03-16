from __future__ import annotations

import json
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
        **_: object,
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
    assert body["store"] is True
    assert body["parallel_tool_calls"] is None
    assert body["tool_choice"] is None
    assert body["tools"] is None
    assert body["previous_response_id"] is None


def test_responses_stream_emits_sse_events(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(principal_id="codex-test")
    from app.api.routes import responses

    def fake_generate(
        *,
        prompt: str,
        messages: list[dict[str, str]] | None = None,
        requested_model: str,
        max_output_tokens: int | None = None,
        **_: object,
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
        **_: object,
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

    assert 'event: response.in_progress' in body
    assert '"heartbeat":true' in body
    assert "event: response.completed" in body


def test_responses_stream_emits_heartbeat_events_while_tool_decision_waits(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(principal_id="codex-test")
    from app.api.routes import responses

    def fake_tool_decision(
        *,
        model: str,
        max_output_tokens: int | None,
        instructions: str | None,
        tools: list[dict[str, object]],
        history_items: list[dict[str, object]],
        **_: object,
    ) -> responses._ToolShimDecision:
        time.sleep(0.03)
        return responses._ToolShimDecision(
            kind="function_call",
            tool_name="exec_command",
            arguments={"cmd": "pwd"},
            upstream_result=UpstreamResult(
                text='{"decision":"function_call","name":"exec_command","arguments":{"cmd":"pwd"}}',
                provider_key="onemin",
                model="gpt-5",
                tokens_in=2,
                tokens_out=2,
            ),
        )

    monkeypatch.setattr(responses, "_tool_shim_decision", fake_tool_decision)
    monkeypatch.setattr(responses, "STREAM_HEARTBEAT_SECONDS", 0.01)

    with client.stream(
        "POST",
        "/v1/responses",
        json={
            "model": "ea-coder-best",
            "input": "inspect repo",
            "stream": True,
            "tools": [
                {
                    "type": "function",
                    "name": "exec_command",
                    "description": "run shell",
                    "parameters": {
                        "type": "object",
                        "properties": {"cmd": {"type": "string"}},
                        "required": ["cmd"],
                    },
                }
            ],
        },
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers["cache-control"] == "no-cache, no-transform"
        assert resp.headers["x-accel-buffering"] == "no"
        body = "".join(resp.iter_text())

    assert '"heartbeat":true' in body
    assert "event: response.function_call_arguments.done" in body
    assert '"arguments":"{\\"cmd\\":\\"pwd\\"}"' in body


def test_models_list_returns_responses_aliases() -> None:
    client = _client(principal_id="codex-test")

    resp = client.get("/v1/models")
    assert resp.status_code == 200
    body = resp.json()
    model_ids = {item["id"] for item in body["data"]}
    assert "ea-coder-best" in model_ids
    assert "ea-magicx-coder" in model_ids
    assert "ea-audit-jury" in model_ids
    assert "ea-audit" in model_ids
    assert "ea-onemin-coder" in model_ids
    assert "ea-gemini-flash" in model_ids
    assert "ea-coder-survival" in model_ids
    assert "gpt-5" in model_ids
    assert "gemini-3-flash-preview" in model_ids
    assert "x-ai/grok-code-fast-1" in model_ids


def test_responses_openapi_publishes_explicit_request_and_response_schema() -> None:
    client = _client(principal_id="codex-test")

    openapi = client.get("/openapi.json")
    assert openapi.status_code == 200
    body = openapi.json()
    post_op = body["paths"]["/v1/responses"]["post"]

    request_schema = post_op["requestBody"]["content"]["application/json"]["schema"]
    assert request_schema["type"] == "object"
    assert request_schema["additionalProperties"] is False
    assert set(request_schema["properties"].keys()) == {
        "model",
        "input",
        "instructions",
        "metadata",
        "max_output_tokens",
        "stream",
        "tools",
        "tool_choice",
        "parallel_tool_calls",
        "reasoning",
        "store",
        "include",
        "service_tier",
        "prompt_cache_key",
        "previous_response_id",
    }

    json_response_schema = post_op["responses"]["200"]["content"]["application/json"]["schema"]
    assert "$ref" in json_response_schema
    response_schema_name = json_response_schema["$ref"].split("/")[-1]
    response_props = body["components"]["schemas"][response_schema_name]["properties"]
    assert "store" in response_props
    assert "parallel_tool_calls" in response_props
    assert "tool_choice" in response_props
    assert "tools" in response_props
    assert "previous_response_id" in response_props
    assert "text/event-stream" in post_op["responses"]["200"]["content"]


def test_responses_forwards_max_output_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(principal_id="codex-test")
    from app.api.routes import responses

    def fake_generate(
        *,
        prompt: str,
        messages: list[dict[str, str]] | None = None,
        requested_model: str,
        max_output_tokens: int | None = None,
        **_: object,
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
        **_: object,
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


def test_responses_accepts_prior_assistant_output_text_parts(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(principal_id="codex-test")
    from app.api.routes import responses

    def fake_generate(
        *,
        prompt: str,
        messages: list[dict[str, str]] | None = None,
        requested_model: str,
        max_output_tokens: int | None = None,
        **_: object,
    ) -> UpstreamResult:
        assert prompt == "system rules\n\nuser asks\n\nassistant answers\n\nfollow up"
        assert messages == [
            {"role": "system", "content": "system rules"},
            {"role": "user", "content": "user asks"},
            {"role": "assistant", "content": "assistant answers"},
            {"role": "user", "content": "follow up"},
        ]
        assert requested_model == "ea-coder-best"
        assert max_output_tokens is None
        return UpstreamResult(
            text="continued",
            provider_key="onemin",
            model="gpt-5",
            tokens_in=4,
            tokens_out=1,
        )

    monkeypatch.setattr(responses, "_generate_upstream_text", fake_generate)

    resp = client.post(
        "/v1/responses",
        json={
            "model": "ea-coder-best",
            "input": [
                {"role": "developer", "content": [{"type": "input_text", "text": "system rules"}]},
                {"role": "user", "content": [{"type": "input_text", "text": "user asks"}]},
                {"role": "assistant", "content": [{"type": "output_text", "text": "assistant answers"}]},
                {"role": "user", "content": [{"type": "input_text", "text": "follow up"}]},
            ],
        },
    )

    assert resp.status_code == 200
    assert resp.json()["output_text"] == "continued"


def test_responses_accepts_codex_client_compat_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(principal_id="codex-test")
    from app.api.routes import responses

    def fake_generate(
        *,
        prompt: str,
        messages: list[dict[str, str]] | None = None,
        requested_model: str,
        max_output_tokens: int | None = None,
        **_: object,
    ) -> UpstreamResult:
        assert prompt == "say hi"
        assert messages == [{"role": "user", "content": "say hi"}]
        assert requested_model == "ea-coder-best"
        assert max_output_tokens is None
        return UpstreamResult(
            text="compat-ok",
            provider_key="onemin",
            model="gpt-5",
            tokens_in=10,
            tokens_out=5,
        )

    monkeypatch.setattr(responses, "_generate_upstream_text", fake_generate)

    resp = client.post(
        "/v1/responses",
        json={
            "model": "ea-coder-best",
            "input": "say hi",
            "tools": [],
            "tool_choice": "auto",
            "parallel_tool_calls": False,
            "reasoning": {"effort": "medium"},
            "store": True,
            "include": ["reasoning.encrypted_content"],
            "service_tier": "fast",
            "prompt_cache_key": "cache-key-1",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["output_text"] == "compat-ok"
    assert body["metadata"]["accepted_client_fields"] == [
        "tool_choice",
        "parallel_tool_calls",
        "reasoning",
        "store",
        "include",
        "service_tier",
        "prompt_cache_key",
    ]
    assert body["store"] is True
    assert body["tool_choice"] == "auto"
    assert body["parallel_tool_calls"] is False
    assert body["tools"] == []
    assert body["reasoning"] == {"effort": "medium"}


def test_responses_rejects_unsupported_top_level_fields() -> None:
    client = _client(principal_id="codex-test")

    resp = client.post(
        "/v1/responses",
        json={"input": "say hi", "conversation": "ignored"},
    )
    assert resp.status_code == 400
    assert "unsupported_fields" in resp.text


def test_responses_rejects_more_unsupported_top_level_fields() -> None:
    client = _client(principal_id="codex-test")

    resp = client.post(
        "/v1/responses",
        json={
            "input": "say hi",
            "background": True,
        },
    )
    assert resp.status_code == 400
    assert "unsupported_fields" in resp.text


def test_responses_store_false_skips_retrieval_state(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(principal_id="codex-test")
    from app.api.routes import responses

    def fake_generate(
        *,
        prompt: str,
        messages: list[dict[str, str]] | None = None,
        requested_model: str,
        max_output_tokens: int | None = None,
        **_: object,
    ) -> UpstreamResult:
        return UpstreamResult(
            text="no-store",
            provider_key="magixai",
            model="openai/gpt-5.1-codex-mini",
            tokens_in=1,
            tokens_out=1,
        )

    monkeypatch.setattr(responses, "_generate_upstream_text", fake_generate)

    created = client.post("/v1/responses", json={"input": "ephemeral", "store": False})
    assert created.status_code == 200
    response_id = created.json()["id"]

    fetched = client.get(f"/v1/responses/{response_id}")
    assert fetched.status_code == 404


def test_responses_non_stream_can_return_function_call_items(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(principal_id="codex-tools")
    from app.api.routes import responses

    def fake_tool_decision(**kwargs: object) -> object:
        tools = kwargs["tools"]
        assert isinstance(tools, list)
        assert tools[0]["name"] == "exec_command"
        return responses._ToolShimDecision(
            kind="function_call",
            tool_name="exec_command",
            arguments={"cmd": "pwd", "workdir": "/docker/fleet"},
            upstream_result=UpstreamResult(
                text='{"decision":"function_call","name":"exec_command","arguments":{"cmd":"pwd","workdir":"/docker/fleet"}}',
                provider_key="onemin",
                model="gpt-5",
                tokens_in=12,
                tokens_out=8,
            ),
        )

    monkeypatch.setattr(responses, "_tool_shim_decision", fake_tool_decision)

    response = client.post(
        "/v1/responses",
        json={
            "model": "gpt-5",
            "input": "Inspect the repo",
            "tool_choice": "auto",
            "parallel_tool_calls": False,
            "tools": [
                {
                    "type": "function",
                    "name": "exec_command",
                    "description": "Run a shell command",
                    "parameters": {
                        "type": "object",
                        "properties": {"cmd": {"type": "string"}},
                        "required": ["cmd"],
                        "additionalProperties": False,
                    },
                }
            ],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["output_text"] == ""
    assert body["output"][0]["type"] == "function_call"
    assert body["output"][0]["name"] == "exec_command"
    assert json.loads(body["output"][0]["arguments"]) == {"cmd": "pwd", "workdir": "/docker/fleet"}
    assert body["tool_choice"] == "auto"
    assert body["parallel_tool_calls"] is False


def test_responses_stream_can_emit_function_call_events(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(principal_id="codex-tools")
    from app.api.routes import responses

    def fake_tool_decision(**_: object) -> object:
        return responses._ToolShimDecision(
            kind="function_call",
            tool_name="exec_command",
            arguments={"cmd": "pwd"},
            upstream_result=UpstreamResult(
                text='{"decision":"function_call","name":"exec_command","arguments":{"cmd":"pwd"}}',
                provider_key="onemin",
                model="gpt-5",
                tokens_in=9,
                tokens_out=6,
            ),
        )

    monkeypatch.setattr(responses, "_tool_shim_decision", fake_tool_decision)

    with client.stream(
        "POST",
        "/v1/responses",
        json={
            "model": "gpt-5",
            "input": "Inspect the repo",
            "stream": True,
            "tool_choice": "auto",
            "parallel_tool_calls": False,
            "tools": [
                {
                    "type": "function",
                    "name": "exec_command",
                    "description": "Run a shell command",
                    "parameters": {
                        "type": "object",
                        "properties": {"cmd": {"type": "string"}},
                        "required": ["cmd"],
                        "additionalProperties": False,
                    },
                }
            ],
        },
    ) as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())

    assert "event: response.output_item.added" in body
    assert "event: response.function_call_arguments.delta" in body
    assert "event: response.function_call_arguments.done" in body
    assert "event: response.completed" in body


def test_responses_previous_response_id_chains_function_call_output(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(principal_id="codex-tools")
    from app.api.routes import responses

    calls: list[list[dict[str, object]]] = []

    def fake_tool_decision(**kwargs: object) -> object:
        history_items = kwargs["history_items"]
        assert isinstance(history_items, list)
        calls.append(history_items)
        if len(calls) == 1:
            return responses._ToolShimDecision(
                kind="function_call",
                tool_name="exec_command",
                arguments={"cmd": "pwd"},
                upstream_result=UpstreamResult(
                    text='{"decision":"function_call","name":"exec_command","arguments":{"cmd":"pwd"}}',
                    provider_key="onemin",
                    model="gpt-5",
                    tokens_in=9,
                    tokens_out=6,
                ),
            )
        assert any(item.get("type") == "function_call" for item in history_items)
        assert any(item.get("type") == "function_call_output" for item in history_items)
        return responses._ToolShimDecision(
            kind="final",
            text="done",
            upstream_result=UpstreamResult(
                text='{"decision":"final","text":"done"}',
                provider_key="onemin",
                model="gpt-5",
                tokens_in=7,
                tokens_out=3,
            ),
        )

    monkeypatch.setattr(responses, "_tool_shim_decision", fake_tool_decision)

    created = client.post(
        "/v1/responses",
        json={
            "model": "gpt-5",
            "input": "Inspect the repo",
            "tool_choice": "auto",
            "parallel_tool_calls": False,
            "tools": [
                {
                    "type": "function",
                    "name": "exec_command",
                    "description": "Run a shell command",
                    "parameters": {
                        "type": "object",
                        "properties": {"cmd": {"type": "string"}},
                        "required": ["cmd"],
                        "additionalProperties": False,
                    },
                }
            ],
        },
    )
    assert created.status_code == 200
    created_body = created.json()
    call_id = created_body["output"][0]["call_id"]

    followup = client.post(
        "/v1/responses",
        json={
            "model": "gpt-5",
            "previous_response_id": created_body["id"],
            "input": [
                {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": "{\"stdout\":\"/docker/fleet\\n\",\"exit_code\":0}",
                }
            ],
            "tool_choice": "auto",
            "parallel_tool_calls": False,
            "tools": [
                {
                    "type": "function",
                    "name": "exec_command",
                    "description": "Run a shell command",
                    "parameters": {
                        "type": "object",
                        "properties": {"cmd": {"type": "string"}},
                        "required": ["cmd"],
                        "additionalProperties": False,
                    },
                }
            ],
        },
    )
    assert followup.status_code == 200
    assert followup.json()["output_text"] == "done"


def test_responses_rejects_unsupported_non_text_input_item(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(principal_id="codex-test")

    resp = client.post(
        "/v1/responses",
        json={
            "input": [
                {"type": "input_image", "url": "https://example.invalid/image.png"},
            ],
        },
    )
    assert resp.status_code == 400
    assert "unsupported_input_item" in resp.text or "unsupported_input_part_type" in resp.text


def test_response_retrieval_endpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(principal_id="codex-test")
    from app.api.routes import responses

    def fake_generate(
        *,
        prompt: str,
        messages: list[dict[str, str]] | None = None,
        requested_model: str,
        max_output_tokens: int | None = None,
        **_: object,
    ) -> UpstreamResult:
        return UpstreamResult(
            text="stored output",
            provider_key="magixai",
            model="openai/gpt-5.1-codex-mini",
            tokens_in=2,
            tokens_out=3,
        )

    monkeypatch.setattr(responses, "_generate_upstream_text", fake_generate)

    created = client.post(
        "/v1/responses",
        json={"input": "snapshot", "instructions": "keep concise"},
    )
    assert created.status_code == 200
    response_id = created.json()["id"]

    fetched = client.get(f"/v1/responses/{response_id}")
    assert fetched.status_code == 200
    fetched_body = fetched.json()
    assert fetched_body["id"] == response_id
    assert fetched_body["instructions"] == "keep concise"
    assert fetched_body["store"] is True
    assert fetched_body["parallel_tool_calls"] is None

    items = client.get(f"/v1/responses/{response_id}/input_items")
    assert items.status_code == 200
    items_body = items.json()
    assert items_body["object"] == "list"
    assert items_body["response_id"] == response_id
    assert items_body["data"] == [{"type": "input_text", "text": "snapshot"}]

    other_client = _client(principal_id="other-principal")
    forbidden = other_client.get(f"/v1/responses/{response_id}")
    assert forbidden.status_code == 403


def test_codex_core_easy_and_audit_endpoints_force_profiles(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(principal_id="codex-profile")
    from app.api.routes import responses

    calls: list[str] = []
    def fake_generate(
        *,
        prompt: str,
        messages: list[dict[str, str]] | None = None,
        requested_model: str,
        max_output_tokens: int | None = None,
        **_: object,
    ) -> UpstreamResult:
        calls.append(requested_model)
        assert messages == [{"role": "user", "content": "lane-check"}]
        assert max_output_tokens is None
        if requested_model == "ea-coder-hard":
            provider_account = "ONEMIN_AI_API_KEY"
            provider_key = "onemin"
            provider_model = "gpt-5"
        elif requested_model == "ea-coder-fast":
            provider_account = "EA_RESPONSES_MAGICX_API_KEY"
            provider_key = "magixai"
            provider_model = "openai/gpt-5.1-codex-mini"
        else:
            provider_account = "BROWSERACT_API_KEY"
            provider_key = "chatplayground"
            provider_model = "judge-model"
        return UpstreamResult(
            text=f"handled-{requested_model}",
            provider_key=provider_key,
            model=provider_model,
            tokens_in=2,
            tokens_out=3,
            provider_account_name=provider_account,
        )

    monkeypatch.setattr(responses, "_generate_upstream_text", fake_generate)
    monkeypatch.setenv("EA_RESPONSES_MAGICX_API_KEY", "magicx-key")

    core = client.post("/v1/codex/core", json={"input": "lane-check"})
    easy = client.post("/v1/codex/easy", json={"input": "lane-check"})
    audit = client.post(
        "/v1/codex/audit",
        json={"input": "lane-check"},
    )

    assert core.status_code == 200
    assert easy.status_code == 200
    assert audit.status_code == 200
    assert calls == ["ea-coder-hard", "ea-coder-fast", "ea-audit-jury"]
    assert core.json()["metadata"]["codex_profile"] == "core"
    assert easy.json()["metadata"]["codex_profile"] == "easy"
    assert audit.json()["metadata"]["codex_profile"] == "audit"
    assert core.json()["metadata"]["codex_lane"] == "hard"
    assert easy.json()["metadata"]["codex_lane"] == "fast"
    assert audit.json()["metadata"]["codex_lane"] == "audit"
    assert core.json()["metadata"]["codex_review_required"] is True
    assert easy.json()["metadata"]["codex_review_required"] is False
    assert audit.json()["metadata"]["codex_review_required"] is True
    assert core.json()["metadata"]["codex_merge_policy"] == "require_review"
    assert easy.json()["metadata"]["codex_merge_policy"] == "auto"
    assert audit.json()["metadata"]["codex_merge_policy"] == "require_review"
    assert core.json()["metadata"]["provider_account_name"] == "ONEMIN_AI_API_KEY"
    assert easy.json()["metadata"]["provider_account_name"] == "EA_RESPONSES_MAGICX_API_KEY"
    assert audit.json()["metadata"]["provider_account_name"] == "BROWSERACT_API_KEY"


def test_codex_survival_endpoint_returns_in_progress_then_completed(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(principal_id="codex-survival")
    from app.api.routes import responses
    from app.services.survival_lane import SurvivalAttempt, SurvivalResult

    def fake_execute(
        self,
        *,
        instructions: str | None,
        history_items: list[dict[str, object]],
        current_input: str,
        desired_format: str | None = None,
        prompt_cache_key: str | None = None,
        previous_response_id: str | None = None,
    ) -> SurvivalResult:
        assert current_input == "keep going"
        assert desired_format == "plain_text"
        return SurvivalResult(
            text="survival output",
            provider_key="gemini_vortex",
            provider_backend="gemini_vortex_cli",
            model="gemini-3-flash-preview",
            latency_ms=12,
            attempts=(
                SurvivalAttempt(
                    backend="gemini_vortex",
                    started_at=time.time(),
                    completed_at=time.time(),
                    status="completed",
                    detail="ok",
                ),
            ),
        )

    monkeypatch.setattr(responses.SurvivalLaneService, "execute", fake_execute)

    created = client.post("/v1/codex/survival", json={"input": "keep going"})
    assert created.status_code == 202
    created_body = created.json()
    assert created_body["status"] == "in_progress"
    assert created_body["model"] == "ea-coder-survival"
    assert created_body["metadata"]["codex_profile"] == "survival"
    assert created_body["metadata"]["codex_lane"] == "survival"

    response_id = created_body["id"]
    completed_body: dict[str, object] | None = None
    for _ in range(50):
        fetched = client.get(f"/v1/responses/{response_id}")
        assert fetched.status_code == 200
        candidate = fetched.json()
        if candidate["status"] == "completed":
            completed_body = candidate
            break
        time.sleep(0.01)

    assert completed_body is not None
    assert completed_body["output_text"] == "survival output"
    assert completed_body["metadata"]["survival_backend"] == "gemini_vortex_cli"
    assert completed_body["metadata"]["survival_provider"] == "gemini_vortex"
    assert completed_body["metadata"]["survival_attempts"][0]["backend"] == "gemini_vortex"

    items = client.get(f"/v1/responses/{response_id}/input_items")
    assert items.status_code == 200
    assert items.json()["data"] == [{"type": "input_text", "text": "keep going"}]


def test_codex_survival_rejects_streaming() -> None:
    client = _client(principal_id="codex-survival-stream")
    response = client.post("/v1/codex/survival", json={"input": "keep going", "stream": True})
    assert response.status_code == 400
    assert "survival_stream_not_supported_yet" in response.text


def test_codex_survival_rejects_client_tools() -> None:
    client = _client(principal_id="codex-survival-tools")
    response = client.post(
        "/v1/codex/survival",
        json={
            "input": "keep going",
            "tools": [
                {
                    "type": "function",
                    "name": "exec_command",
                    "description": "run shell",
                    "parameters": {"type": "object", "properties": {"cmd": {"type": "string"}}},
                }
            ],
        },
    )
    assert response.status_code == 400
    assert "survival_unsupported_fields:tools" in response.text


def test_codex_audit_path_degrades_without_tool_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(principal_id="codex-audit-fallback")
    from app.api.routes import responses
    from app.services import responses_upstream as upstream

    class _NoToolContainer:
        tool_execution = None

    def fail_post_json(
        *,
        url: str,
        headers: dict[str, str],
        payload: dict[str, object],
        timeout_seconds: int,
    ) -> tuple[int, dict[str, object]]:
        raise AssertionError("http path should not be used for callback-only audit lane")

    monkeypatch.setattr(upstream, "_post_json", fail_post_json)
    monkeypatch.setattr(responses, "get_container", lambda: _NoToolContainer())

    response = client.post("/v1/codex/audit", json={"input": "review this change"})
    assert response.status_code == 200

    body = response.json()
    output_text = body["output"][0]["content"][0]["text"]
    payload = json.loads(output_text)
    assert payload["provider"] == "chatplayground"
    assert payload["consensus"] == "unavailable"
    assert body["metadata"]["codex_profile"] == "audit"
    assert body["metadata"]["codex_review_required"] is True
    assert body["metadata"]["provider_account_name"].startswith("chatplayground_")


def test_codex_audit_smoke_uses_chatplayground_callback_path(monkeypatch: pytest.MonkeyPatch) -> None:
    os.environ["EA_STORAGE_BACKEND"] = "memory"
    os.environ.pop("EA_LEDGER_BACKEND", None)
    os.environ.pop("EA_DEFAULT_PRINCIPAL_ID", None)
    os.environ["EA_API_TOKEN"] = ""
    from app.api.app import create_app

    app = create_app()
    container = app.state.container
    binding = container.tool_runtime.upsert_connector_binding(
        principal_id="codex-audit-smoke",
        connector_name="browseract",
        external_account_ref="browseract-main",
        scope_json={},
        status="enabled",
    )

    def _fake_audit(*, request_payload: dict[str, object], run_url: str) -> dict[str, object]:
        assert run_url == "https://web.chatplayground.ai/api/chat/lmsys"
        assert request_payload["prompt"] == "review the release plan"
        assert request_payload["audit_scope"] == "jury"
        assert request_payload["roles"] == ["factuality", "adversarial", "completeness", "risk"]
        assert request_payload["binding_id"] == binding.binding_id
        return {
            "binding_id": binding.binding_id,
            "external_account_ref": binding.external_account_ref,
            "requested_url": run_url,
            "requested_roles": request_payload["roles"],
            "audit_scope": request_payload["audit_scope"],
            "consensus": "pass",
            "recommendation": "ship it",
            "disagreements": [],
            "risks": [],
            "model_deltas": [],
        }

    monkeypatch.setattr(container.tool_execution, "_browseract_chatplayground_audit", _fake_audit)

    client = TestClient(app)
    client.headers.update({"X-EA-Principal-ID": "codex-audit-smoke"})

    response = client.post("/v1/codex/audit", json={"input": "review the release plan"})
    assert response.status_code == 200

    body = response.json()
    payload = json.loads(body["output"][0]["content"][0]["text"])
    assert body["metadata"]["codex_profile"] == "audit"
    assert body["metadata"]["codex_lane"] == "audit"
    assert body["metadata"]["codex_review_required"] is True
    assert body["metadata"]["provider_backend"] == "browseract"
    assert body["metadata"]["provider_account_name"] == "browseract-main"
    assert payload["provider"] == "chatplayground"
    assert payload["consensus"] == "pass"
    assert payload["recommendation"] == "ship it"
    assert payload["external_account_ref"] == "browseract-main"


def test_codex_profiles_endpoint_exposes_lane_provider_state(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(principal_id="codex-profile")

    monkeypatch.setenv("EA_RESPONSES_MAGICX_API_KEY", "magicx-key")
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "onemin-key")
    monkeypatch.setenv("BROWSERACT_API_KEY", "browseract-key")

    response = client.get("/v1/codex/profiles")
    assert response.status_code == 200
    body = response.json()
    assert body["profiles"][0]["lane"] == "hard"
    assert body["profiles"][0]["provider_hint_order"] == ["onemin"]
    easy_profile = next(profile for profile in body["profiles"] if profile["profile"] == "easy")
    assert easy_profile["provider_hint_order"] == ["magixai", "gemini_vortex", "onemin"]
    assert any(profile["profile"] == "survival" and profile["lane"] == "survival" for profile in body["profiles"])
    assert body["provider_health"]["providers"]["onemin"]["backend"] == "1min"
    assert body["provider_health"]["providers"]["magixai"]["slots"][0]["account_name"] == "EA_RESPONSES_MAGICX_API_KEY"
    assert body["provider_health"]["providers"]["onemin"]["slots"][0]["account_name"] == "ONEMIN_AI_API_KEY"
    assert body["provider_health"]["providers"]["chatplayground"]["slots"][0]["account_name"] == "BROWSERACT_API_KEY"
    assert body["provider_health"]["provider_config"]["onemin_accounts"] == ["ONEMIN_AI_API_KEY"]
    assert body["provider_health"]["provider_config"]["chatplayground_accounts"] == ["BROWSERACT_API_KEY"]


def test_responses_provider_health_endpoint_exposes_slots(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(principal_id="codex-health")
    from app.services import responses_upstream as upstream
    from app.api.routes import responses

    upstream._test_reset_onemin_states()

    monkeypatch.setenv("ONEMIN_AI_API_KEY", "health-key-a")
    for index in range(1, 34):
        monkeypatch.setenv(f"ONEMIN_AI_API_KEY_FALLBACK_{index}", f"health-key-{index}")
    monkeypatch.setenv("EA_RESPONSES_DEFAULT_PROFILE", "easy")
    monkeypatch.setenv("EA_RESPONSES_PROVIDER_ORDER", "magixai,onemin")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_ACTIVE_SLOTS", "primary,fallback_1")
    monkeypatch.setenv(
        "EA_RESPONSES_ONEMIN_RESERVE_SLOTS",
        ",".join(f"fallback_{index}" for index in range(2, 34)),
    )
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_MAX_REQUESTS_PER_HOUR", "120")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_MAX_CREDITS_PER_HOUR", "80000")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_MAX_CREDITS_PER_DAY", "600000")
    monkeypatch.setenv("EA_RESPONSES_HARD_MAX_ACTIVE_REQUESTS", "1")
    monkeypatch.setenv("EA_RESPONSES_HARD_QUEUE_TIMEOUT_SECONDS", "120")
    monkeypatch.setenv("BROWSERACT_API_KEY", "browseract-health-key")
    monkeypatch.setenv("BROWSERACT_API_KEY_FALLBACK_1", "browseract-health-fallback")
    monkeypatch.setenv("AI_MAGICX_API_KEY", "health-magicx-key")
    monkeypatch.setattr(responses, "_generate_upstream_text", lambda **_: None)

    response = client.get("/v1/responses/_provider_health")
    assert response.status_code == 200
    body = response.json()

    providers = body["providers"]
    assert providers["onemin"]["configured_slots"] == 34
    assert len(providers["onemin"]["slots"]) == 34
    assert [slot["slot"] for slot in providers["onemin"]["slots"]] == [
        "primary",
        *[f"fallback_{index}" for index in range(1, 34)],
    ]
    assert providers["chatplayground"]["provider_key"] == "chatplayground"
    assert providers["chatplayground"]["backend"] == "browseract"
    assert providers["chatplayground"]["configured_slots"] == 2
    assert [slot["slot"] for slot in providers["chatplayground"]["slots"]] == [
        "primary",
        "fallback_1",
    ]
    assert [slot["account_name"] for slot in providers["chatplayground"]["slots"]] == [
        "BROWSERACT_API_KEY",
        "BROWSERACT_API_KEY_FALLBACK_1",
    ]
    assert providers["magixai"]["configured_slots"] == 1
    assert providers["magixai"]["state"] in {"ready", "unknown", "degraded"}
    assert body["provider_config"]["onemin_accounts"] == [
        "ONEMIN_AI_API_KEY",
        *[f"ONEMIN_AI_API_KEY_FALLBACK_{index}" for index in range(1, 34)],
    ]
    assert body["provider_config"]["default_profile"] == "easy"
    assert body["provider_config"]["default_lane"] == "fast"
    assert body["provider_config"]["provider_order"] == ["magixai", "onemin"]
    assert body["provider_config"]["onemin_active_accounts"] == [
        "ONEMIN_AI_API_KEY",
        "ONEMIN_AI_API_KEY_FALLBACK_1",
    ]
    assert body["provider_config"]["onemin_reserve_accounts"] == [
        *[f"ONEMIN_AI_API_KEY_FALLBACK_{index}" for index in range(2, 34)],
    ]
    assert body["provider_config"]["onemin_max_requests_per_hour"] == 120
    assert body["provider_config"]["onemin_max_credits_per_hour"] == 80000
    assert body["provider_config"]["onemin_max_credits_per_day"] == 600000
    assert body["provider_config"]["hard_max_active_requests"] == 1
    assert body["provider_config"]["hard_queue_timeout_seconds"] == 120.0
    assert body["provider_config"]["chatplayground_accounts"] == [
        "BROWSERACT_API_KEY",
        "BROWSERACT_API_KEY_FALLBACK_1",
    ]
    assert providers["onemin"]["slots"][0]["next_retry_at"] is None
    assert providers["onemin"]["slots"][0]["upstream_reset_unknown"] is False
    assert providers["onemin"]["slots"][0]["observed_consumed_credits"] == 0
    assert providers["onemin"]["slots"][0]["observed_success_count"] == 0
    assert "estimated_burn_credits_per_hour" in providers["onemin"]
    assert "estimated_hours_remaining_at_current_pace" in providers["onemin"]
    assert "burn_estimate_basis" in providers["onemin"]
    assert providers["onemin"]["max_requests_per_hour"] == 120
    assert providers["onemin"]["max_credits_per_hour"] == 80000
    assert providers["onemin"]["max_credits_per_day"] == 600000


def test_responses_provider_health_reports_observed_credit_balance_without_leaking_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import responses_upstream as upstream

    upstream._test_reset_onemin_states()
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "secret-primary-key")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_CHAT_URL", "https://api.1min.ai/api/chat-with-ai")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_MODELS", "gpt-4.1")

    def fake_post_json(*, url: str, headers: dict[str, str], payload: dict[str, object], timeout_seconds: int) -> tuple[int, dict[str, object]]:
        return (
            200,
            {
                "aiRecord": {
                    "model": "gpt-4.1",
                    "aiRecordDetail": {
                        "resultObject": {
                            "code": "INSUFFICIENT_CREDITS",
                            "message": "The feature requires 35194 credits, but the Example Team only has 0 credits",
                        }
                    },
                }
            },
        )

    monkeypatch.setattr(upstream, "_post_json", fake_post_json)

    with pytest.raises(upstream.ResponsesUpstreamError):
        upstream.generate_text(prompt="check credits", requested_model="gpt-4.1")

    health = upstream._provider_health_report()
    slot = health["providers"]["onemin"]["slots"][0]
    assert slot["account_name"] == "ONEMIN_AI_API_KEY"
    assert slot["remaining_credits"] == 0
    assert slot["required_credits"] == 35194
    assert slot["credit_subject"] == "Example Team"
    assert slot["estimated_remaining_credits"] == 0
    assert slot["next_retry_at"] is not None
    assert slot["upstream_reset_unknown"] is True
    assert health["providers"]["onemin"]["remaining_percent_of_max"] == 0.0
    assert "secret-primary-key" not in json.dumps(health)


def test_responses_provider_health_aggregates_onemin_remaining_percent_of_max(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import responses_upstream as upstream

    upstream._test_reset_onemin_states()
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "healthy-primary")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_1", "empty-a")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_2", "empty-b")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_INCLUDED_CREDITS_PER_KEY", "4000000")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_BONUS_CREDITS_PER_KEY", "450000")

    upstream._mark_onemin_failure(
        "empty-a",
        "INSUFFICIENT_CREDITS:The feature requires 35194 credits, but the A team only has 0 credits",
    )
    upstream._mark_onemin_failure(
        "empty-b",
        "INSUFFICIENT_CREDITS:The feature requires 35194 credits, but the B team only has 0 credits",
    )

    health = upstream._provider_health_report()
    onemin = health["providers"]["onemin"]

    assert onemin["max_credits_total"] == 13350000
    assert onemin["estimated_remaining_credits_total"] == 4450000
    assert onemin["remaining_percent_of_max"] == 33.33


def test_responses_provider_health_reflects_magicx_probe_degradation(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(principal_id="codex-health")
    from app.services import responses_upstream as upstream

    upstream._test_reset_onemin_states()

    monkeypatch.setenv("EA_RESPONSES_MAGICX_HEALTH_CHECK", "1")
    monkeypatch.setenv("EA_RESPONSES_MAGICX_HEALTH_TIMEOUT_SECONDS", "1")
    monkeypatch.setenv("EA_RESPONSES_PROVIDER_ORDER", "magixai")
    monkeypatch.setenv("AI_MAGICX_API_KEY", "expired-key")
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "")

    calls: list[tuple[str, str]] = []

    def fake_post_json(*, url: str, headers: dict[str, str], payload: dict[str, object], timeout_seconds: int) -> tuple[int, dict[str, object]]:
        calls.append((url, headers["Authorization"]))
        return (401, {"error": "invalid api key"})

    monkeypatch.setattr(upstream, "_post_json", fake_post_json)

    failed = client.post("/v1/responses", json={"model": "ea-magicx-coder", "input": "probe now"})
    assert failed.status_code == 502
    assert calls

    health = client.get("/v1/responses/_provider_health")
    assert health.status_code == 200
    body = health.json()
    assert body["providers"]["magixai"]["state"] == "degraded"


def test_responses_provider_health_reflects_magicx_probe_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(principal_id="codex-health")
    from app.services import responses_upstream as upstream

    upstream._test_reset_onemin_states()

    monkeypatch.setenv("EA_RESPONSES_MAGICX_HEALTH_CHECK", "1")
    monkeypatch.setenv("EA_RESPONSES_MAGICX_HEALTH_TIMEOUT_SECONDS", "1")
    monkeypatch.setenv("EA_RESPONSES_PROVIDER_ORDER", "magixai")
    monkeypatch.setenv("AI_MAGICX_API_KEY", "healthy-key")
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "")

    def fake_post_json(*, url: str, headers: dict[str, str], payload: dict[str, object], timeout_seconds: int) -> tuple[int, dict[str, object]]:
        return (
            200,
            {
                "model": payload["model"],
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    monkeypatch.setattr(upstream, "_post_json", fake_post_json)

    health = client.get("/v1/responses/_provider_health")
    assert health.status_code == 200
    body = health.json()
    assert body["providers"]["magixai"]["state"] == "ready"
    assert body["providers"]["magixai"]["health_check_enabled"] is True


def test_responses_provider_health_exposes_gemini_vortex(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(principal_id="codex-gemini-health")

    monkeypatch.setenv("EA_GEMINI_VORTEX_COMMAND", "sh")
    monkeypatch.setenv("EA_GEMINI_VORTEX_MODEL", "gemini-3-flash-preview")

    response = client.get("/v1/responses/_provider_health")
    assert response.status_code == 200
    body = response.json()
    assert body["providers"]["gemini_vortex"]["state"] == "ready"
    assert "gemini-3-flash-preview" in body["providers"]["gemini_vortex"]["models"]
    assert body["provider_config"]["gemini_vortex_command"] == "sh"


def test_stream_events_include_sequence_number_and_failed_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(principal_id="codex-test")
    from app.api.routes import responses

    def fake_generate(*_, **__) -> None:
        raise RuntimeError("upstream_failure")

    monkeypatch.setattr(responses, "_generate_upstream_text", fake_generate)

    with client.stream("POST", "/v1/responses", json={"input": "stream", "stream": True}) as resp:
        assert resp.status_code == 200
        body = "".join(resp.iter_text())

    assert "event: response.failed" in body
    assert "event: error" in body
    assert '\"sequence_number\":1' in body
    assert '\"sequence_number\":2' in body
    assert '\"sequence_number\":3' in body


def test_end_to_end_responses_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(principal_id="codex-endpoint")
    from app.api.routes import responses

    def fake_generate(
        *,
        prompt: str,
        messages: list[dict[str, str]] | None = None,
        requested_model: str,
        max_output_tokens: int | None = None,
        **_: object,
    ) -> UpstreamResult:
        if prompt == "sync check":
            assert messages == [{"role": "system", "content": "audit first"}, {"role": "user", "content": "sync check"}]
            assert max_output_tokens == 42
        else:
            assert prompt == "stream check"
            assert messages == [{"role": "user", "content": "stream check"}]
            assert max_output_tokens is None
        assert requested_model == "ea-coder-best"
        return UpstreamResult(
            text="contract-ok",
            provider_key="magixai",
            model="openai/gpt-5.1-codex-mini",
            tokens_in=3,
            tokens_out=2,
        )

    monkeypatch.setattr(responses, "_generate_upstream_text", fake_generate)

    models = client.get("/v1/models")
    assert models.status_code == 200
    model_ids = {item["id"] for item in models.json()["data"]}
    assert "ea-coder-best" in model_ids

    created = client.post(
        "/v1/responses",
        json={"model": "ea-coder-best", "instructions": "audit first", "input": "sync check", "max_output_tokens": 42},
    )
    assert created.status_code == 200
    body = created.json()
    assert body["status"] == "completed"
    assert body["instructions"] == "audit first"
    assert body["output_text"] == "contract-ok"
    response_id = body["id"]

    read = client.get(f"/v1/responses/{response_id}")
    assert read.status_code == 200
    assert read.json()["metadata"]["principal_id"] == "codex-endpoint"

    items = client.get(f"/v1/responses/{response_id}/input_items")
    assert items.status_code == 200
    assert items.json()["data"] == [{"type": "input_text", "text": "sync check"}]

    with client.stream(
        "POST",
        "/v1/responses",
        json={
            "model": "ea-coder-best",
            "input": "stream check",
            "stream": True,
        },
    ) as streaming:
        assert streaming.status_code == 200
        stream_body = "".join(streaming.iter_text())

    assert "event: response.created" in stream_body
    assert "event: response.completed" in stream_body
    assert "event: response.failed" not in stream_body
