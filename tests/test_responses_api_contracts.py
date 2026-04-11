from __future__ import annotations

import hashlib
import json
import os
import re
import time

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from app.services.responses_upstream import UpstreamResult
from app.services.tool_execution_browseract_adapter import BrowserActToolAdapter


@pytest.fixture(autouse=True)
def _reset_responses_runtime_state(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ.keys()):
        if key.startswith(
            (
                "EA_TRUST_AUTHENTICATED_PRINCIPAL_HEADER",
                "EA_ALLOW_AUTHENTICATED_PRINCIPAL_HEADER",
                "EA_TRUST_BROWSER_PRINCIPAL_OVERRIDE",
                "EA_ALLOW_BROWSER_PRINCIPAL_OVERRIDE",
                "EA_OPERATOR_PRINCIPAL_IDS",
                "EA_OPERATOR_PRINCIPALS",
                "EA_OPERATOR_EMAILS",
                "EA_OPERATOR_ACCESS_EMAILS",
                "EA_PRINCIPAL_",
                "EA_GEMINI_VORTEX_SLOT_",
                "ONEMIN_AI_API_KEY",
                "BROWSERACT_API_KEY",
                "GOOGLE_API_KEY_FALLBACK_",
                "EA_FLEET_STATUS_BASE_URL",
            )
        ):
            monkeypatch.delenv(key, raising=False)
    from app.services import responses_upstream as upstream
    from app.api.routes import responses

    upstream._test_reset_onemin_states()
    upstream._test_reset_fleet_jury_cache()
    responses._test_reset_responses_runtime_state()
    yield
    responses._test_reset_responses_runtime_state()
    upstream._test_reset_onemin_states()
    upstream._test_reset_fleet_jury_cache()


def _client(*, principal_id: str, operator: bool = False) -> TestClient:
    os.environ["EA_STORAGE_BACKEND"] = "memory"
    os.environ.pop("EA_LEDGER_BACKEND", None)
    os.environ.pop("EA_DEFAULT_PRINCIPAL_ID", None)
    if operator:
        os.environ["EA_API_TOKEN"] = "test-token"
        os.environ["EA_TRUST_AUTHENTICATED_PRINCIPAL_HEADER"] = "1"
        os.environ["EA_OPERATOR_PRINCIPAL_IDS"] = principal_id
    else:
        os.environ["EA_API_TOKEN"] = ""
        os.environ.pop("EA_TRUST_AUTHENTICATED_PRINCIPAL_HEADER", None)
        os.environ.pop("EA_OPERATOR_PRINCIPAL_IDS", None)
    from app.api.app import create_app

    client = TestClient(create_app())
    if operator:
        client.headers.update({"Authorization": "Bearer test-token"})
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


def test_responses_stream_persists_in_progress_state_for_retrieval(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(principal_id="codex-stream-retrieval")
    read_client = _client(principal_id="codex-stream-retrieval")
    from app.api.routes import responses

    def fake_generate(
        *,
        prompt: str,
        messages: list[dict[str, str]] | None = None,
        requested_model: str,
        max_output_tokens: int | None = None,
        **_: object,
    ) -> UpstreamResult:
        time.sleep(0.05)
        return UpstreamResult(
            text="stream lifecycle",
            provider_key="magixai",
            model="openai/gpt-5.1-codex-mini",
            tokens_in=2,
            tokens_out=1,
        )

    monkeypatch.setattr(responses, "_generate_upstream_text", fake_generate)
    monkeypatch.setattr(responses, "STREAM_HEARTBEAT_SECONDS", 0.01)

    with client.stream("POST", "/v1/responses", json={"input": "stream lifecycle", "stream": True}) as resp:
        assert resp.status_code == 200
        buffer = ""
        response_id = ""
        stream_iter = resp.iter_text()
        for chunk in stream_iter:
            buffer += chunk
            if "event: response.created" not in buffer:
                continue
            match = re.search(r'"id":"(resp_[^"]+)"', buffer)
            if match:
                response_id = match.group(1)
                break
        assert response_id
        retrieved = read_client.get(f"/v1/responses/{response_id}")
        assert retrieved.status_code == 200
        assert retrieved.json()["status"] == "in_progress"
        # Drain remaining SSE payload to let the stream complete cleanly.
        _ = "".join(stream_iter)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("store", False),
        ("tools", [{"type": "function", "name": "exec_command"}]),
        ("tool_choice", "auto"),
        ("parallel_tool_calls", False),
        ("previous_response_id", "resp_seeded"),
    ],
)
def test_responses_rejects_unsupported_codex_compat_fields(field: str, value: object) -> None:
    client = _client(principal_id="codex-test")

    resp = client.post(
        "/v1/responses",
        json={"model": "ea-coder-fast", "input": "inspect repo", field: value},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == f"unsupported_fields:{field}"


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
    assert "ea-review-light" in model_ids
    assert "ea-groundwork-gemini" in model_ids
    assert "ea-groundwork" in model_ids
    assert "ea-onemin-coder" in model_ids
    assert "ea-gemini-flash" in model_ids
    assert "ea-coder-survival" in model_ids
    assert "gpt-5" in model_ids
    assert "gemini-2.5-flash" in model_ids
    assert "x-ai/grok-code-fast-1" in model_ids


def test_codex_profiles_helper_without_container_keeps_governance_expectations() -> None:
    from app.api.routes import responses

    profiles = responses._codex_profiles()
    easy = next(item for item in profiles if item["profile"] == "easy")
    audit = next(item for item in profiles if item["profile"] == "audit")

    assert easy["work_class"] == "easy"
    assert "Easy lane" in easy["expectation_summary"]
    assert easy["review_cadence"]["review"] == "weekly"
    assert audit["work_class"] == "audit_jury"
    assert "Audit/jury lane" in audit["expectation_summary"]


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
        "text",
        "metadata",
        "max_output_tokens",
        "stream",
        "reasoning",
        "include",
        "service_tier",
        "prompt_cache_key",
    }

    json_response_schema = post_op["responses"]["200"]["content"]["application/json"]["schema"]
    assert "$ref" in json_response_schema
    response_schema_name = json_response_schema["$ref"].split("/")[-1]
    response_props = body["components"]["schemas"][response_schema_name]["properties"]
    assert "reasoning" in response_props
    assert "store" not in response_props
    assert "parallel_tool_calls" not in response_props
    assert "tool_choice" not in response_props
    assert "tools" not in response_props
    assert "previous_response_id" not in response_props
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


def test_responses_accepts_supported_optional_fields(monkeypatch: pytest.MonkeyPatch) -> None:
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
            "reasoning": {"effort": "medium"},
            "include": ["reasoning.encrypted_content"],
            "service_tier": "fast",
            "prompt_cache_key": "cache-key-1",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["output_text"] == "compat-ok"
    assert body["metadata"]["accepted_client_fields"] == [
        "reasoning",
        "include",
        "service_tier",
        "prompt_cache_key",
    ]
    assert body["reasoning"] == {"effort": "medium"}


def test_responses_accepts_text_output_config_field(monkeypatch: pytest.MonkeyPatch) -> None:
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
            text="text-config-ok",
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
            "text": {"format": {"type": "text"}},
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["output_text"] == "text-config-ok"
    assert body["metadata"]["accepted_client_fields"] == ["text"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("conversation", "ignored"),
        ("background", True),
    ],
)
def test_responses_rejects_unsupported_top_level_fields(field: str, value: object) -> None:
    client = _client(principal_id="codex-test")

    resp = client.post(
        "/v1/responses",
        json={"input": "say hi", field: value},
    )
    assert resp.status_code == 400
    assert "unsupported_fields" in resp.text


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


def test_responses_ignores_non_dict_resume_state_items(monkeypatch: pytest.MonkeyPatch) -> None:
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
            text="resume ok",
            provider_key="magixai",
            model="x-ai/grok-code-fast-1",
            tokens_in=3,
            tokens_out=2,
        )

    monkeypatch.setattr(responses, "_generate_upstream_text", fake_generate)

    resp = client.post(
        "/v1/responses",
        json={
            "input": [
                {"type": "input_text", "text": "keep going"},
                ["resume-state", {"ignored": True}],
                None,
            ],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["output_text"] == "resume ok"
    assert body["input"] == [{"type": "input_text", "text": "keep going"}]


def test_responses_accepts_unknown_textish_resume_items(monkeypatch: pytest.MonkeyPatch) -> None:
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
        assert "assistant summary from resume" in prompt
        assert "resume trace payload" in prompt
        assert messages
        return UpstreamResult(
            text="resume ok",
            provider_key="magixai",
            model="x-ai/grok-code-fast-1",
            tokens_in=3,
            tokens_out=2,
        )

    monkeypatch.setattr(responses, "_generate_upstream_text", fake_generate)

    resp = client.post(
        "/v1/responses",
        json={
            "model": "ea-coder-fast",
            "input": [
                {"type": "reasoning", "summary": "assistant summary from resume"},
                {"type": "custom_debug_blob", "content": [{"type": "output_text", "text": "resume trace payload"}]},
            ],
        },
    )
    assert resp.status_code == 200
    assert resp.json()["output_text"] == "resume ok"


def test_responses_accepts_codex_tool_history_items(monkeypatch: pytest.MonkeyPatch) -> None:
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
        assert prompt == "thinking\n\nfollow up"
        assert messages == [
            {"role": "assistant", "content": "thinking"},
            {"role": "user", "content": "follow up"},
        ]
        assert requested_model == "ea-coder-fast"
        return UpstreamResult(
            text="tool resume ok",
            provider_key="magixai",
            model="x-ai/grok-code-fast-1",
            tokens_in=4,
            tokens_out=2,
        )

    monkeypatch.setattr(responses, "_generate_upstream_text", fake_generate)

    resp = client.post(
        "/v1/responses",
        json={
            "model": "ea-coder-fast",
            "input": [
                {"type": "reasoning", "summary": [{"type": "summary_text", "text": "thinking"}]},
                {"type": "local_shell_call", "call_id": "call_123", "name": "exec_command", "arguments": "{\"cmd\":\"pwd\"}"},
                {"type": "local_shell_call_output", "call_id": "call_123", "output": "{\"stdout\":\"/docker/fleet\\n\"}"},
                {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "follow up"}]},
            ],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["output_text"] == "tool resume ok"
    input_items = body["input"]
    assert input_items[0]["type"] == "reasoning"
    assert input_items[1]["type"] == "local_shell_call"
    assert input_items[2]["type"] == "local_shell_call_output"


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

    items = client.get(f"/v1/responses/{response_id}/input_items")
    assert items.status_code == 200
    items_body = items.json()
    assert items_body["object"] == "list"
    assert items_body["response_id"] == response_id
    assert items_body["data"] == [{"type": "input_text", "text": "snapshot"}]

    other_client = _client(principal_id="other-principal")
    forbidden = other_client.get(f"/v1/responses/{response_id}")
    assert forbidden.status_code == 403


def test_codex_core_easy_repair_groundwork_review_light_and_audit_endpoints_force_profiles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
        elif requested_model == "ea-groundwork-gemini":
            provider_account = "EA_GEMINI_VORTEX_API_KEY"
            provider_key = "gemini_vortex"
            provider_model = "gemini-2.5-flash"
        elif requested_model == "ea-repair-gemini":
            provider_account = "EA_GEMINI_VORTEX_API_KEY"
            provider_key = "gemini_vortex"
            provider_model = "gemini-2.5-flash"
        elif requested_model == "ea-review-light":
            provider_account = "BROWSERACT_API_KEY"
            provider_key = "chatplayground"
            provider_model = "gpt-4.1"
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
    repair = client.post("/v1/codex/repair", json={"input": "lane-check"})
    groundwork = client.post("/v1/codex/groundwork", json={"input": "lane-check"})
    review_light = client.post("/v1/codex/review-light", json={"input": "lane-check"})
    audit = client.post(
        "/v1/codex/audit",
        json={"input": "lane-check"},
    )

    assert core.status_code == 200
    assert easy.status_code == 200
    assert repair.status_code == 200
    assert groundwork.status_code == 200
    assert review_light.status_code == 200
    assert audit.status_code == 200
    assert calls == [
        "ea-coder-hard",
        "ea-coder-fast",
        "ea-repair-gemini",
        "ea-groundwork-gemini",
        "ea-review-light",
        "ea-audit-jury",
    ]
    assert core.json()["metadata"]["codex_profile"] == "core"
    assert easy.json()["metadata"]["codex_profile"] == "easy"
    assert repair.json()["metadata"]["codex_profile"] == "repair"
    assert groundwork.json()["metadata"]["codex_profile"] == "groundwork"
    assert review_light.json()["metadata"]["codex_profile"] == "review_light"
    assert audit.json()["metadata"]["codex_profile"] == "audit"
    assert core.json()["metadata"]["codex_lane"] == "hard"
    assert easy.json()["metadata"]["codex_lane"] == "fast"
    assert repair.json()["metadata"]["codex_lane"] == "repair"
    assert groundwork.json()["metadata"]["codex_lane"] == "groundwork"
    assert review_light.json()["metadata"]["codex_lane"] == "review"
    assert audit.json()["metadata"]["codex_lane"] == "audit"
    assert core.json()["metadata"]["codex_review_required"] is True
    assert easy.json()["metadata"]["codex_review_required"] is False
    assert repair.json()["metadata"]["codex_review_required"] is False
    assert groundwork.json()["metadata"]["codex_review_required"] is False
    assert review_light.json()["metadata"]["codex_review_required"] is False
    assert audit.json()["metadata"]["codex_review_required"] is True
    assert core.json()["metadata"]["codex_merge_policy"] == "require_review"
    assert easy.json()["metadata"]["codex_merge_policy"] == "auto"
    assert repair.json()["metadata"]["codex_merge_policy"] == "auto_if_low_risk"
    assert groundwork.json()["metadata"]["codex_merge_policy"] == "auto"
    assert review_light.json()["metadata"]["codex_merge_policy"] == "auto_if_low_risk"
    assert audit.json()["metadata"]["codex_merge_policy"] == "require_review"
    assert core.json()["metadata"]["codex_work_class"] == "hard_coder"
    assert easy.json()["metadata"]["codex_work_class"] == "easy"
    assert groundwork.json()["metadata"]["codex_work_class"] == "groundwork"
    assert audit.json()["metadata"]["codex_work_class"] == "audit_jury"
    assert "Hard coder lane" in core.json()["metadata"]["codex_expectation_summary"]
    assert "Easy lane" in easy.json()["metadata"]["codex_expectation_summary"]
    assert "Groundwork lane" in groundwork.json()["metadata"]["codex_expectation_summary"]
    assert "Audit/jury lane" in audit.json()["metadata"]["codex_expectation_summary"]
    assert core.json()["metadata"]["codex_review_cadence"]["review"] == "weekly"
    assert core.json()["metadata"]["codex_review_cadence"]["snapshot_owner"] == "product_governor"
    assert easy.json()["metadata"]["codex_support_help_boundary"]["owner"] == "chummer6-hub"
    assert core.json()["metadata"]["provider_account_name"] == "ONEMIN_AI_API_KEY"
    assert easy.json()["metadata"]["provider_account_name"] == "EA_RESPONSES_MAGICX_API_KEY"
    assert repair.json()["metadata"]["provider_account_name"] == "EA_GEMINI_VORTEX_API_KEY"
    assert groundwork.json()["metadata"]["provider_account_name"] == "EA_GEMINI_VORTEX_API_KEY"
    assert review_light.json()["metadata"]["provider_account_name"] == "BROWSERACT_API_KEY"
    assert audit.json()["metadata"]["provider_account_name"] == "BROWSERACT_API_KEY"


def test_codex_profile_endpoints_resolve_profile_model_with_current_principal_and_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(principal_id="codex-dynamic-profile")
    from app.api.routes import responses

    seen: list[tuple[str, bool, str]] = []

    def fake_codex_profile(
        profile: str,
        *,
        container=None,
        principal_id: str = "",
        provider_health: dict[str, object] | None = None,
    ) -> dict[str, object]:
        assert isinstance(provider_health, dict)
        seen.append((profile, container is not None, principal_id))
        return {
            "profile": profile,
            "lane": "hard",
            "model": "ea-coder-hard-custom",
            "provider_hint_order": ["onemin"],
            "review_required": True,
            "needs_review": True,
            "risk_labels": ["high_impact"],
            "merge_policy": "require_review",
            "work_class": "hard_coder",
            "expectation_summary": "Hard coder lane for substantive implementation.",
            "review_posture": "Require review.",
            "best_for": "Blocking repo work.",
            "review_cadence": {"review": "weekly", "snapshot_owner": "product_governor", "publication": "internal_canon_first"},
            "support_help_boundary": {"owner": "chummer6-hub"},
        }

    def fake_generate(
        *,
        requested_model: str,
        **_: object,
    ) -> UpstreamResult:
        assert requested_model == "ea-coder-hard-custom"
        return UpstreamResult(
            text="dynamic",
            provider_key="onemin",
            model="gpt-5",
            tokens_in=2,
            tokens_out=1,
            provider_account_name="ONEMIN_AI_API_KEY",
        )

    monkeypatch.setattr(responses, "_codex_profile", fake_codex_profile)
    monkeypatch.setattr(responses, "_generate_upstream_text", fake_generate)

    response = client.post("/v1/codex/core", json={"input": "lane-check"})
    assert response.status_code == 200
    assert response.json()["model"] == "ea-coder-hard-custom"
    assert seen == [("core", True, "codex-dynamic-profile"), ("core", True, "codex-dynamic-profile")]


def test_responses_upstream_defaults_to_easy_fast_lane(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import responses_upstream

    monkeypatch.delenv("EA_RESPONSES_DEFAULT_PROFILE", raising=False)

    assert responses_upstream._resolve_default_response_lane() == "fast"


def test_prompt_router_demotes_default_public_model_for_lightweight_ops_queries() -> None:
    from app.api.routes import responses

    decision = responses._resolve_prompt_route(
        prompt="how many codexes are running?",
        model="ea-coder-best",
        codex_profile=None,
    )

    assert decision.applied is True
    assert decision.effective_profile == "easy"
    assert decision.effective_model == "ea-onemin-coder"
    assert decision.reason == "lightweight_ops_query"


def test_prompt_router_promotes_default_public_model_coding_task_to_core() -> None:
    from app.api.routes import responses

    decision = responses._resolve_prompt_route(
        prompt="fix the routing bug in /docker/EA/ea/app/api/routes/responses.py",
        model="ea-coder-best",
        codex_profile=None,
    )

    assert decision.applied is True
    assert decision.effective_profile == "core"
    assert decision.effective_model == "ea-coder-hard"
    assert decision.reason == "coding_task_requires_core"


def test_prompt_router_keeps_explicit_repair_profile_on_coding_task() -> None:
    from app.api.routes import responses

    decision = responses._resolve_prompt_route(
        prompt="fix the routing bug in /docker/EA/ea/app/api/routes/responses.py",
        model="ea-coder-fast",
        codex_profile="repair",
    )

    assert decision.applied is False
    assert decision.effective_profile == "repair"
    assert decision.effective_model == "ea-coder-fast"


def test_responses_upstream_provider_order_prefers_onemin_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import responses_upstream

    monkeypatch.delenv("EA_RESPONSES_PROVIDER_ORDER", raising=False)

    assert responses_upstream._provider_order() == ("onemin", "gemini_vortex", "magixai")


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
            model="gemini-2.5-flash",
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
    assert created_body["metadata"]["survival_route_order"] == "onemin,gemini_vortex,gemini_web,chatplayground"

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


def test_codex_survival_stream_returns_completed_sse(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(principal_id="codex-survival-stream")
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
            text="survival stream output",
            provider_key="gemini_vortex",
            provider_backend="gemini_vortex_cli",
            model="gemini-2.5-flash",
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
    monkeypatch.setattr(responses, "STREAM_HEARTBEAT_SECONDS", 0.01)

    with client.stream("POST", "/v1/codex/survival", json={"input": "keep going", "stream": True}) as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())

    assert "event: response.created" in body
    assert "event: response.in_progress" in body
    assert "event: response.completed" in body
    assert "survival stream output" in body


def test_codex_survival_ignores_client_tools_for_codex_compat(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(principal_id="codex-survival-tools")
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
        return SurvivalResult(
            text="survival tools ok",
            provider_key="gemini_vortex",
            provider_backend="gemini_vortex_cli",
            model="gemini-2.5-flash",
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
            "tool_choice": "auto",
            "parallel_tool_calls": False,
        },
    )
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "in_progress"
    assert body["metadata"]["codex_profile"] == "survival"


def test_core_batch_header_returns_in_progress_then_completed(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(principal_id="codex-core-batch")
    from app.api.routes import responses

    def fake_generate(
        *,
        prompt: str,
        messages: list[dict[str, str]] | None = None,
        requested_model: str,
        max_output_tokens: int | None = None,
        **_: object,
    ) -> UpstreamResult:
        assert prompt == "finish the desktop lane"
        assert messages == [{"role": "user", "content": "finish the desktop lane"}]
        assert requested_model == "ea-coder-hard-batch"
        assert max_output_tokens is None
        time.sleep(0.02)
        return UpstreamResult(
            text="batch complete",
            provider_key="onemin",
            model="gpt-5",
            tokens_in=13,
            tokens_out=21,
        )

    monkeypatch.setattr(responses, "_generate_upstream_text", fake_generate)

    created = client.post(
        "/v1/responses",
        headers={"X-EA-Codex-Profile": "core_batch"},
        json={"input": "finish the desktop lane"},
    )
    assert created.status_code == 202
    created_body = created.json()
    assert created_body["status"] == "in_progress"
    assert created_body["model"] == "ea-coder-hard-batch"
    assert created_body["metadata"]["codex_profile"] == "core_batch"
    assert created_body["metadata"]["background_response"] is True
    assert created_body["metadata"]["background_poll_url"] == f"/v1/responses/{created_body['id']}"

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
    assert completed_body["output_text"] == "batch complete"
    assert completed_body["metadata"]["upstream_provider"] == "onemin"
    assert completed_body["metadata"]["background_response"] is True


def test_core_batch_route_preserves_explicit_batch_profile_for_ops_queries(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(principal_id="codex-core-batch-preserved")
    from app.api.routes import responses

    def fake_generate(
        *,
        prompt: str,
        messages: list[dict[str, str]] | None = None,
        requested_model: str,
        max_output_tokens: int | None = None,
        **_: object,
    ) -> UpstreamResult:
        assert prompt == "what is the current desktop status?"
        assert requested_model == "ea-coder-hard-batch"
        time.sleep(0.02)
        return UpstreamResult(
            text="still batch",
            provider_key="onemin",
            model="gpt-5",
            tokens_in=8,
            tokens_out=5,
        )

    monkeypatch.setattr(responses, "_generate_upstream_text", fake_generate)

    created = client.post("/v1/codex/core-batch", json={"input": "what is the current desktop status?"})
    assert created.status_code == 202
    created_body = created.json()
    assert created_body["metadata"]["codex_effective_profile"] == "core_batch"
    assert created_body["metadata"]["codex_prompt_route_reason"] == "explicit_core_batch_profile"

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
    assert completed_body["output_text"] == "still batch"


def test_codex_core_batch_endpoint_returns_in_progress_then_completed(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(principal_id="codex-core-batch-route")
    from app.api.routes import responses

    def fake_generate(
        *,
        prompt: str,
        messages: list[dict[str, str]] | None = None,
        requested_model: str,
        max_output_tokens: int | None = None,
        **_: object,
    ) -> UpstreamResult:
        assert prompt == "repair the release proof"
        assert requested_model == "ea-coder-hard-batch"
        return UpstreamResult(
            text="route ok",
            provider_key="onemin",
            model="gpt-5",
            tokens_in=5,
            tokens_out=8,
        )

    monkeypatch.setattr(responses, "_generate_upstream_text", fake_generate)

    created = client.post("/v1/codex/core-batch", json={"input": "repair the release proof"})
    assert created.status_code == 202
    body = created.json()
    assert body["status"] == "in_progress"
    assert body["metadata"]["codex_profile"] == "core_batch"

    response_id = body["id"]
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
    assert completed_body["output_text"] == "route ok"


def test_codex_repair_endpoint_keeps_explicit_repair_lane_for_coding_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(principal_id="codex-repair-coding")
    from app.api.routes import responses

    def fake_generate(
        *,
        prompt: str,
        messages: list[dict[str, str]] | None = None,
        requested_model: str,
        max_output_tokens: int | None = None,
        **_: object,
    ) -> UpstreamResult:
        assert prompt == "fix the routing bug in /docker/EA/ea/app/api/routes/responses.py"
        assert requested_model == "ea-repair-gemini"
        return UpstreamResult(
            text="repair stayed repair",
            provider_key="gemini_vortex",
            model="gemini-2.5-flash",
            tokens_in=5,
            tokens_out=7,
        )

    monkeypatch.setattr(responses, "_generate_upstream_text", fake_generate)

    response = client.post(
        "/v1/codex/repair",
        json={"input": "fix the routing bug in /docker/EA/ea/app/api/routes/responses.py"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["output_text"] == "repair stayed repair"
    assert body["metadata"]["codex_profile"] == "repair"
    assert body["metadata"]["codex_effective_profile"] == "repair"
    assert body["metadata"]["codex_prompt_route_applied"] is False


def test_codex_repair_endpoint_uses_onemin_model_when_cheap_repair_backends_are_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(principal_id="codex-repair-onemin")
    from app.api.routes import responses

    monkeypatch.setenv("ONEMIN_AI_API_KEY", "onemin-key")
    monkeypatch.setattr(
        responses,
        "_provider_health_report",
        lambda: {
            "providers": {
                "gemini_vortex": {"state": "degraded"},
                "magixai": {"state": "degraded"},
                "onemin": {"state": "ready"},
            }
        },
    )

    def fake_generate(
        *,
        prompt: str,
        messages: list[dict[str, str]] | None = None,
        requested_model: str,
        max_output_tokens: int | None = None,
        **_: object,
    ) -> UpstreamResult:
        assert prompt == "repair fallback"
        assert messages == [{"role": "user", "content": "repair fallback"}]
        assert requested_model == "ea-onemin-coder"
        assert max_output_tokens is None
        return UpstreamResult(
            text="repair via onemin",
            provider_key="onemin",
            model="gpt-5",
            tokens_in=2,
            tokens_out=1,
            provider_account_name="ONEMIN_AI_API_KEY",
        )

    monkeypatch.setattr(responses, "_generate_upstream_text", fake_generate)

    response = client.post("/v1/codex/repair", json={"input": "repair fallback"})

    assert response.status_code == 200
    body = response.json()
    assert body["output_text"] == "repair via onemin"
    assert body["metadata"]["codex_profile"] == "repair"
    assert body["metadata"]["codex_effective_profile"] == "repair"
    assert body["metadata"]["codex_effective_model"] == "ea-onemin-coder"
    assert body["metadata"]["provider_account_name"] == "ONEMIN_AI_API_KEY"


def test_core_batch_get_response_resumes_in_progress_job_after_worker_loss(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(principal_id="codex-core-batch-resume")
    from app.api.routes import responses

    def fake_generate(
        *,
        prompt: str,
        messages: list[dict[str, str]] | None = None,
        requested_model: str,
        max_output_tokens: int | None = None,
        **_: object,
    ) -> UpstreamResult:
        assert prompt == "resume the hard batch"
        assert requested_model == "ea-coder-hard-batch"
        return UpstreamResult(
            text="resumed cleanly",
            provider_key="onemin",
            model="gpt-5",
            tokens_in=9,
            tokens_out=11,
        )

    monkeypatch.setattr(responses, "_generate_upstream_text", fake_generate)

    response_id = "resp_resumehardbatch000001"
    created_at = responses._now_unix()
    input_items = [{"type": "input_text", "text": "resume the hard batch"}]
    history_items = [{"type": "input_text", "text": "resume the hard batch"}]
    metadata = {
        "principal_id": "codex-core-batch-resume",
        "codex_profile": "core_batch",
        "codex_effective_profile": "core_batch",
        "background_response": True,
        "background_poll_url": f"/v1/responses/{response_id}",
        "background_timeout_seconds": 60,
    }
    response_obj = responses._response_object(
        response_id=response_id,
        model="ea-coder-hard-batch",
        created_at=created_at,
        status="in_progress",
        output=[],
        output_text="",
        tokens_in=0,
        tokens_out=0,
        max_output_tokens=None,
        metadata=metadata,
        instructions=None,
        input_items=input_items,
        reasoning=None,
    )
    responses._store_response(
        response_id=response_id,
        response_obj=response_obj,
        input_items=input_items,
        history_items=history_items,
        principal_id="codex-core-batch-resume",
        background_job=responses._background_replay_payload(
            prompt="resume the hard batch",
            messages=[{"role": "user", "content": "resume the hard batch"}],
            supported_tools=[],
            effective_codex_profile="core_batch",
            chatplayground_audit_callback_enabled=False,
            chatplayground_audit_callback_only=False,
        ),
    )

    first_fetch = client.get(f"/v1/responses/{response_id}")
    assert first_fetch.status_code == 200
    assert first_fetch.json()["status"] in {"in_progress", "completed"}

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
    assert completed_body["output_text"] == "resumed cleanly"
    assert completed_body["metadata"]["background_response"] is True


def test_core_batch_get_response_fails_expired_in_progress_job() -> None:
    client = _client(principal_id="codex-core-batch-expired")
    from app.api.routes import responses

    response_id = "resp_expiredhardbatch0001"
    input_items = [{"type": "input_text", "text": "expired batch"}]
    history_items = [{"type": "input_text", "text": "expired batch"}]
    response_obj = responses._response_object(
        response_id=response_id,
        model="ea-coder-hard-batch",
        created_at=responses._now_unix() - 10,
        status="in_progress",
        output=[],
        output_text="",
        tokens_in=0,
        tokens_out=0,
        max_output_tokens=None,
        metadata={
            "principal_id": "codex-core-batch-expired",
            "codex_profile": "core_batch",
            "codex_effective_profile": "core_batch",
            "background_response": True,
            "background_poll_url": f"/v1/responses/{response_id}",
            "background_timeout_seconds": 1,
        },
        instructions=None,
        input_items=input_items,
        reasoning=None,
    )
    responses._store_response(
        response_id=response_id,
        response_obj=response_obj,
        input_items=input_items,
        history_items=history_items,
        principal_id="codex-core-batch-expired",
        background_job=responses._background_replay_payload(
            prompt="expired batch",
            messages=[{"role": "user", "content": "expired batch"}],
            supported_tools=[],
            effective_codex_profile="core_batch",
            chatplayground_audit_callback_enabled=False,
            chatplayground_audit_callback_only=False,
        ),
    )

    fetched = client.get(f"/v1/responses/{response_id}")
    assert fetched.status_code == 200
    body = fetched.json()
    assert body["status"] == "failed"
    assert body["error"]["message"] == "background_timeout:1s"


def test_core_batch_stream_emits_heartbeats_until_completion(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(principal_id="codex-core-batch-stream")
    from app.api.routes import responses

    def fake_generate(
        *,
        prompt: str,
        messages: list[dict[str, str]] | None = None,
        requested_model: str,
        max_output_tokens: int | None = None,
        **_: object,
    ) -> UpstreamResult:
        assert prompt == "stream the batch lane"
        assert requested_model == "ea-coder-hard-batch"
        time.sleep(0.03)
        return UpstreamResult(
            text="stream batch done",
            provider_key="onemin",
            model="gpt-5",
            tokens_in=7,
            tokens_out=9,
        )

    monkeypatch.setattr(responses, "_generate_upstream_text", fake_generate)
    monkeypatch.setattr(responses, "STREAM_HEARTBEAT_SECONDS", 0.01)

    with client.stream(
        "POST",
        "/v1/responses",
        headers={"X-EA-Codex-Profile": "core_batch"},
        json={"input": "stream the batch lane", "stream": True},
    ) as resp:
        assert resp.status_code == 200
        body = "".join(resp.iter_text())

    assert "event: response.created" in body
    assert '"heartbeat":true' in body
    assert "event: response.completed" in body
    assert "stream batch done" in body


def test_core_batch_late_completion_stays_failed_after_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(principal_id="codex-core-batch-timeout-final")
    from app.api.routes import responses

    def fake_generate(
        *,
        prompt: str,
        messages: list[dict[str, str]] | None = None,
        requested_model: str,
        max_output_tokens: int | None = None,
        **_: object,
    ) -> UpstreamResult:
        time.sleep(0.05)
        return UpstreamResult(
            text="too late",
            provider_key="onemin",
            model="gpt-5",
            tokens_in=4,
            tokens_out=4,
        )

    monkeypatch.setattr(responses, "_generate_upstream_text", fake_generate)

    response_id = "resp_resumehardbatchtimeout"
    input_items = [{"type": "input_text", "text": "timeout should fail"}]
    history_items = [{"type": "input_text", "text": "timeout should fail"}]
    response_obj = responses._response_object(
        response_id=response_id,
        model="ea-coder-hard-batch",
        created_at=responses._now_unix(),
        status="in_progress",
        output=[],
        output_text="",
        tokens_in=0,
        tokens_out=0,
        max_output_tokens=None,
        metadata={
            "principal_id": "codex-core-batch-timeout-final",
            "codex_profile": "core_batch",
            "codex_effective_profile": "core_batch",
            "background_response": True,
            "background_poll_url": f"/v1/responses/{response_id}",
            "background_timeout_seconds": 0.01,
        },
        instructions=None,
        input_items=input_items,
        reasoning=None,
    )
    responses._store_response(
        response_id=response_id,
        response_obj=response_obj,
        input_items=input_items,
        history_items=history_items,
        principal_id="codex-core-batch-timeout-final",
        background_job=responses._background_replay_payload(
            prompt="timeout should fail",
            messages=[{"role": "user", "content": "timeout should fail"}],
            supported_tools=[],
            effective_codex_profile="core_batch",
            chatplayground_audit_callback_enabled=False,
            chatplayground_audit_callback_only=False,
        ),
    )

    starter = client.get(f"/v1/responses/{response_id}")
    assert starter.status_code == 200

    time.sleep(0.08)
    first = client.get(f"/v1/responses/{response_id}")
    assert first.status_code == 200
    assert first.json()["status"] == "failed"
    assert first.json()["error"]["message"] == "background_timeout"

    time.sleep(0.03)
    second = client.get(f"/v1/responses/{response_id}")
    assert second.status_code == 200
    assert second.json()["status"] == "failed"
    assert second.json()["error"]["message"] == "background_timeout"


def test_core_batch_resume_spawns_only_one_worker_for_concurrent_polls(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.routes import responses
    import threading

    clients = [_client(principal_id="codex-core-batch-race"), _client(principal_id="codex-core-batch-race")]
    calls: list[str] = []
    calls_lock = threading.Lock()

    def fake_generate(
        *,
        prompt: str,
        messages: list[dict[str, str]] | None = None,
        requested_model: str,
        max_output_tokens: int | None = None,
        **_: object,
    ) -> UpstreamResult:
        with calls_lock:
            calls.append(prompt)
        time.sleep(0.05)
        return UpstreamResult(
            text="single worker",
            provider_key="onemin",
            model="gpt-5",
            tokens_in=3,
            tokens_out=3,
        )

    monkeypatch.setattr(responses, "_generate_upstream_text", fake_generate)

    response_id = "resp_resumehardbatchrace01"
    input_items = [{"type": "input_text", "text": "race resume"}]
    history_items = [{"type": "input_text", "text": "race resume"}]
    response_obj = responses._response_object(
        response_id=response_id,
        model="ea-coder-hard-batch",
        created_at=responses._now_unix(),
        status="in_progress",
        output=[],
        output_text="",
        tokens_in=0,
        tokens_out=0,
        max_output_tokens=None,
        metadata={
            "principal_id": "codex-core-batch-race",
            "codex_profile": "core_batch",
            "codex_effective_profile": "core_batch",
            "background_response": True,
            "background_poll_url": f"/v1/responses/{response_id}",
            "background_timeout_seconds": 60,
        },
        instructions=None,
        input_items=input_items,
        reasoning=None,
    )
    responses._store_response(
        response_id=response_id,
        response_obj=response_obj,
        input_items=input_items,
        history_items=history_items,
        principal_id="codex-core-batch-race",
        background_job=responses._background_replay_payload(
            prompt="race resume",
            messages=[{"role": "user", "content": "race resume"}],
            supported_tools=[],
            effective_codex_profile="core_batch",
            chatplayground_audit_callback_enabled=False,
            chatplayground_audit_callback_only=False,
        ),
    )

    start = threading.Barrier(3)
    results: list[int] = []

    def fetch(client: TestClient) -> None:
        start.wait()
        response = client.get(f"/v1/responses/{response_id}")
        results.append(response.status_code)

    threads = [threading.Thread(target=fetch, args=(client,)) for client in clients]
    for thread in threads:
        thread.start()
    start.wait()
    for thread in threads:
        thread.join()

    assert results == [200, 200]

    completed_body: dict[str, object] | None = None
    for _ in range(60):
        fetched = clients[0].get(f"/v1/responses/{response_id}")
        assert fetched.status_code == 200
        candidate = fetched.json()
        if candidate["status"] == "completed":
            completed_body = candidate
            break
        time.sleep(0.01)

    assert completed_body is not None
    assert completed_body["output_text"] == "single worker"
    assert calls == ["race resume"]


def test_core_batch_resume_rebuilds_audit_callback(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(principal_id="codex-core-batch-replay-callback")
    from app.api.routes import responses

    sentinel = object()

    def fake_build_chatplayground_audit_callback(*, container: object | None, principal_id: str):
        assert principal_id == "codex-core-batch-replay-callback"
        return sentinel

    def fake_generate(
        *,
        prompt: str,
        messages: list[dict[str, str]] | None = None,
        requested_model: str,
        max_output_tokens: int | None = None,
        chatplayground_audit_callback=None,
        chatplayground_audit_callback_only: bool = False,
        **_: object,
    ) -> UpstreamResult:
        assert chatplayground_audit_callback is sentinel
        assert chatplayground_audit_callback_only is True
        return UpstreamResult(
            text="callback rebuilt",
            provider_key="onemin",
            model="gpt-5",
            tokens_in=2,
            tokens_out=2,
        )

    monkeypatch.setattr(responses, "_build_chatplayground_audit_callback", fake_build_chatplayground_audit_callback)
    monkeypatch.setattr(responses, "_generate_upstream_text", fake_generate)

    response_id = "resp_resumehardbatchaudit01"
    input_items = [{"type": "input_text", "text": "rebuild callback"}]
    history_items = [{"type": "input_text", "text": "rebuild callback"}]
    response_obj = responses._response_object(
        response_id=response_id,
        model="ea-coder-hard-batch",
        created_at=responses._now_unix(),
        status="in_progress",
        output=[],
        output_text="",
        tokens_in=0,
        tokens_out=0,
        max_output_tokens=None,
        metadata={
            "principal_id": "codex-core-batch-replay-callback",
            "codex_profile": "core_batch",
            "codex_effective_profile": "core_batch",
            "background_response": True,
            "background_poll_url": f"/v1/responses/{response_id}",
            "background_timeout_seconds": 60,
        },
        instructions=None,
        input_items=input_items,
        reasoning=None,
    )
    responses._store_response(
        response_id=response_id,
        response_obj=response_obj,
        input_items=input_items,
        history_items=history_items,
        principal_id="codex-core-batch-replay-callback",
        background_job=responses._background_replay_payload(
            prompt="rebuild callback",
            messages=[{"role": "user", "content": "rebuild callback"}],
            supported_tools=[],
            effective_codex_profile="core_batch",
            chatplayground_audit_callback_enabled=True,
            chatplayground_audit_callback_only=True,
        ),
    )

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
    assert completed_body["output_text"] == "callback rebuilt"


def test_core_batch_forces_internal_store_when_client_disables_store(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(principal_id="codex-core-batch-store")
    from app.api.routes import responses

    def fake_generate(
        *,
        prompt: str,
        messages: list[dict[str, str]] | None = None,
        requested_model: str,
        max_output_tokens: int | None = None,
        **_: object,
    ) -> UpstreamResult:
        assert prompt == "keep it ephemeral"
        assert requested_model == "ea-coder-hard-batch"
        return UpstreamResult(
            text="forced storage ok",
            provider_key="onemin",
            model="gpt-5",
            tokens_in=4,
            tokens_out=6,
        )

    monkeypatch.setattr(responses, "_generate_upstream_text", fake_generate)

    created = client.post(
        "/v1/codex/core-batch",
        json={"input": "keep it ephemeral", "store": False},
    )
    assert created.status_code == 202
    body = created.json()
    assert body["metadata"]["background_store_forced"] is True
    assert body["metadata"]["background_requested_store"] is False

    response_id = body["id"]
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
    assert completed_body["output_text"] == "forced storage ok"


def test_core_rescue_route_uses_rescue_model_and_longer_background_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(principal_id="codex-core-rescue")
    from app.api.routes import responses

    monkeypatch.setenv("EA_RESPONSES_BACKGROUND_TIMEOUT_CORE_RESCUE_SECONDS", "14400")

    def fake_generate(
        *,
        prompt: str,
        messages: list[dict[str, str]] | None = None,
        requested_model: str,
        max_output_tokens: int | None = None,
        **_: object,
    ) -> UpstreamResult:
        assert prompt == "finish the long-running desktop slice"
        assert requested_model == "ea-coder-hard-rescue"
        return UpstreamResult(
            text="rescue lane complete",
            provider_key="onemin",
            model="gpt-4o",
            tokens_in=9,
            tokens_out=11,
        )

    monkeypatch.setattr(responses, "_generate_upstream_text", fake_generate)

    created = client.post(
        "/v1/responses",
        headers={"X-EA-Codex-Profile": "core_rescue"},
        json={"input": "finish the long-running desktop slice", "store": False},
    )
    assert created.status_code == 202
    body = created.json()
    assert body["model"] == "ea-coder-hard-rescue"
    assert body["metadata"]["codex_profile"] == "core_rescue"
    assert body["metadata"]["background_store_forced"] is True
    assert body["metadata"]["background_timeout_seconds"] == 14400.0



def test_core_batch_route_defaults_to_long_background_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(principal_id="codex-core-batch-timeout")
    from app.api.routes import responses

    monkeypatch.delenv("EA_RESPONSES_BACKGROUND_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("EA_RESPONSES_BACKGROUND_TIMEOUT_HARD_BATCH_SECONDS", raising=False)

    def fake_generate(
        *,
        prompt: str,
        messages: list[dict[str, str]] | None = None,
        requested_model: str,
        max_output_tokens: int | None = None,
        **_: object,
    ) -> UpstreamResult:
        assert prompt == "finish the long-running flagship slice"
        assert requested_model == "ea-coder-hard-batch"
        return UpstreamResult(
            text="core batch complete",
            provider_key="onemin",
            model="gpt-5",
            tokens_in=9,
            tokens_out=11,
        )

    monkeypatch.setattr(responses, "_generate_upstream_text", fake_generate)

    created = client.post(
        "/v1/responses",
        headers={"X-EA-Codex-Profile": "core_batch"},
        json={"input": "finish the long-running flagship slice", "store": False},
    )
    assert created.status_code == 202
    body = created.json()
    assert body["model"] == "ea-coder-hard-batch"
    assert body["metadata"]["codex_profile"] == "core_batch"
    assert body["metadata"]["background_store_forced"] is True
    assert body["metadata"]["background_timeout_seconds"] == 21600.0


def test_previous_response_id_rejects_in_progress_background_response() -> None:
    client = _client(principal_id="codex-previous-response-progress")
    from app.api.routes import responses

    response_id = "resp_previousresponseprogress"
    input_items = [{"type": "input_text", "text": "background still running"}]
    history_items = [{"type": "input_text", "text": "background still running"}]
    response_obj = responses._response_object(
        response_id=response_id,
        model="ea-coder-hard-batch",
        created_at=responses._now_unix(),
        status="in_progress",
        output=[],
        output_text="",
        tokens_in=0,
        tokens_out=0,
        max_output_tokens=None,
        metadata={
            "principal_id": "codex-previous-response-progress",
            "codex_profile": "core_batch",
            "codex_effective_profile": "core_batch",
            "background_response": True,
            "background_poll_url": f"/v1/responses/{response_id}",
            "background_timeout_seconds": 60,
        },
        instructions=None,
        input_items=input_items,
        reasoning=None,
    )
    responses._store_response(
        response_id=response_id,
        response_obj=response_obj,
        input_items=input_items,
        history_items=history_items,
        principal_id="codex-previous-response-progress",
        background_job=responses._background_replay_payload(
            prompt="background still running",
            messages=[{"role": "user", "content": "background still running"}],
            supported_tools=[],
            effective_codex_profile="core_batch",
            chatplayground_audit_callback_enabled=False,
            chatplayground_audit_callback_only=False,
        ),
    )

    response = client.post(
        "/v1/codex/core-batch",
        json={"input": "follow up too early", "previous_response_id": response_id},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "previous_response_in_progress"


def test_previous_response_id_rejects_failed_background_response() -> None:
    client = _client(principal_id="codex-previous-response-failed")
    from app.api.routes import responses

    response_id = "resp_previousresponsefailed00"
    input_items = [{"type": "input_text", "text": "background already failed"}]
    history_items = [{"type": "input_text", "text": "background already failed"}]
    response_obj = responses._response_object(
        response_id=response_id,
        model="ea-coder-hard-batch",
        created_at=responses._now_unix() - 10,
        status="in_progress",
        output=[],
        output_text="",
        tokens_in=0,
        tokens_out=0,
        max_output_tokens=None,
        metadata={
            "principal_id": "codex-previous-response-failed",
            "codex_profile": "core_batch",
            "codex_effective_profile": "core_batch",
            "background_response": True,
            "background_poll_url": f"/v1/responses/{response_id}",
            "background_timeout_seconds": 1,
        },
        instructions=None,
        input_items=input_items,
        reasoning=None,
    )
    responses._store_response(
        response_id=response_id,
        response_obj=response_obj,
        input_items=input_items,
        history_items=history_items,
        principal_id="codex-previous-response-failed",
        background_job=responses._background_replay_payload(
            prompt="background already failed",
            messages=[{"role": "user", "content": "background already failed"}],
            supported_tools=[],
            effective_codex_profile="core_batch",
            chatplayground_audit_callback_enabled=False,
            chatplayground_audit_callback_only=False,
        ),
    )

    response = client.post(
        "/v1/codex/core-batch",
        json={"input": "follow up after failure", "previous_response_id": response_id},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "previous_response_failed:background_timeout:1s"


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


def test_codex_audit_smoke_uses_env_backed_backend_without_binding(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BROWSERACT_API_KEY", "judge-key")
    monkeypatch.setenv("BROWSERACT_CHATPLAYGROUND_URL", "https://web.chatplayground.ai/")
    monkeypatch.setattr(
        BrowserActToolAdapter,
        "_resolve_chatplayground_workflow",
        lambda self, *, payload, binding_metadata: ("", ""),
    )

    from app.api.app import create_app

    app = create_app()
    calls: list[tuple[str, dict[str, object], int]] = []

    def _fake_post_browseract_json(
        self,
        *,
        run_url: str,
        request_payload: dict[str, object],
        timeout_seconds: int,
    ) -> dict[str, object]:
        calls.append((run_url, dict(request_payload), timeout_seconds))
        assert run_url == "https://web.chatplayground.ai/api/chat/lmsys"
        assert request_payload["prompt"] == "review the release plan"
        assert request_payload["audit_scope"] == "jury"
        assert request_payload["principal_id"] == "codex-audit-env"
        assert request_payload["binding_id"] == ""
        return {
            "consensus": "pass",
            "recommendation": "ship it",
            "disagreements": [],
            "risks": [],
            "model_deltas": [],
            "roles": request_payload["roles"],
            "requested_at": "2026-03-18T00:00:00Z",
        }

    monkeypatch.setattr(BrowserActToolAdapter, "_post_browseract_json", _fake_post_browseract_json)

    client = TestClient(app)
    client.headers.update({"X-EA-Principal-ID": "codex-audit-env"})

    response = client.post("/v1/codex/audit", json={"input": "review the release plan"})
    assert response.status_code == 200

    body = response.json()
    payload = json.loads(body["output"][0]["content"][0]["text"])
    assert body["metadata"]["codex_profile"] == "audit"
    assert body["metadata"]["provider_backend"] == "browseract"
    assert payload["provider"] == "chatplayground"
    assert payload["consensus"] == "pass"
    assert calls[0][0] == "https://web.chatplayground.ai/api/chat/lmsys"


def test_codex_audit_smoke_uses_browseract_workflow_api_without_binding(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BROWSERACT_API_KEY", "judge-key")

    from app.api.app import create_app

    app = create_app()
    calls: list[tuple[str, str, dict[str, object] | None, dict[str, str] | None]] = []

    def _fake_browseract_api_request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, object] | None = None,
        query: dict[str, str] | None = None,
        timeout_seconds: int = 120,
    ) -> dict[str, object]:
        calls.append((method, path, dict(payload or {}), dict(query or {})))
        if path == "/run-task":
            return {"task_id": "task-audit-1"}
        if path == "/get-task-status":
            return {"status": "finished"}
        if path == "/get-task":
            return {
                "status": "finished",
                "output": {
                    "string": json.dumps(
                        [
                            {
                                "audit_response": json.dumps(
                                    {
                                        "consensus": "pass",
                                        "recommendation": "ship it",
                                        "disagreements": [],
                                        "risks": [],
                                        "model_deltas": [],
                                        "roles": ["factuality", "adversarial", "completeness", "risk"],
                                    }
                                )
                            }
                        ]
                    )
                },
            }
        raise AssertionError(f"unexpected BrowserAct API path: {path}")

    monkeypatch.setattr(
        BrowserActToolAdapter,
        "_resolve_chatplayground_workflow",
        lambda self, *, payload, binding_metadata: ("workflow-audit-1", "test-fixture"),
    )
    monkeypatch.setattr(BrowserActToolAdapter, "_browseract_api_request", _fake_browseract_api_request)

    client = TestClient(app)
    client.headers.update({"X-EA-Principal-ID": "codex-audit-workflow"})

    response = client.post("/v1/codex/audit", json={"input": "review the release plan"})
    assert response.status_code == 200

    body = response.json()
    payload = json.loads(body["output"][0]["content"][0]["text"])
    run_task_payload = calls[0][2] or {}
    rendered_prompt = str(((run_task_payload.get("input_parameters") or [{}])[0]).get("value") or "")
    assert body["metadata"]["codex_profile"] == "audit"
    assert body["metadata"]["provider_backend"] == "browseract"
    assert payload["provider"] == "chatplayground"
    assert payload["consensus"] == "pass"
    assert payload["workflow_id"] == "workflow-audit-1"
    assert payload["task_id"] == "task-audit-1"
    assert calls[0][1] == "/run-task"
    assert "review the release plan" in rendered_prompt
    assert "return exactly one json object" in rendered_prompt.lower()


def test_codex_profiles_endpoint_exposes_lane_provider_state(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(principal_id="codex-profile")
    from app.services import responses_upstream as upstream

    for key in list(os.environ.keys()):
        if key.startswith("ONEMIN_AI_API_KEY"):
            monkeypatch.delenv(key, raising=False)

    monkeypatch.setenv("EA_RESPONSES_MAGICX_API_KEY", "magicx-key")
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "onemin-key")
    monkeypatch.setenv("BROWSERACT_API_KEY", "browseract-key")
    monkeypatch.setenv("GOOGLE_API_KEY_FALLBACK_1", "vertex-fallback")
    monkeypatch.setenv("EA_GEMINI_VORTEX_SLOT_DEFAULT_OWNER", "fleet-primary")
    monkeypatch.setenv("EA_GEMINI_VORTEX_SLOT_FALLBACK_1_OWNER", "fleet-shadow")
    monkeypatch.setenv("EA_PRINCIPAL_HUB_USER_OVERRIDES_JSON", json.dumps({"codex-profile": "usr_codex"}))
    monkeypatch.setenv("EA_PRINCIPAL_HUB_GROUP_OVERRIDES_JSON", json.dumps({"codex-profile": "grp_codex"}))
    monkeypatch.setenv("EA_PRINCIPAL_SPONSOR_SESSION_OVERRIDES_JSON", json.dumps({"codex-profile": "sps_codex"}))
    monkeypatch.setenv("EA_PRINCIPAL_LANE_ROLE_OVERRIDES_JSON", json.dumps({"codex-profile": "review"}))
    monkeypatch.setattr(
        upstream,
        "gemini_vortex_slot_status",
        lambda: [
            {
                "slot": "primary",
                "account_name": "EA_GEMINI_VORTEX_DEFAULT_AUTH",
                "slot_owner": "fleet-primary",
                "lease_holder": "codex-profile",
                "last_used_principal_id": "codex-profile",
                "last_used_at": "2026-03-19T10:00:00Z",
                "state": "ready",
            },
            {
                "slot": "fallback_1",
                "account_name": "GOOGLE_API_KEY_FALLBACK_1",
                "slot_owner": "fleet-shadow",
                "state": "ready",
            },
        ],
    )

    response = client.get("/v1/codex/profiles")
    assert response.status_code == 200
    body = response.json()
    assert body["governance"]["summary"]
    assert body["governance"]["review_cadence"]["review"] == "weekly"
    assert body["governance"]["review_cadence"]["snapshot_owner"] == "product_governor"
    assert body["governance"]["support_help_boundary"]["owner"] == "chummer6-hub"
    assert any(item["label"] == "PRODUCT_HEALTH_SCORECARD.yaml" for item in body["governance"]["sources"])
    assert body["profiles"][0]["lane"] == "hard"
    assert body["profiles"][0]["provider_hint_order"] == ["onemin"]
    assert body["profiles"][0]["work_class"] == "hard_coder"
    assert "Hard coder lane" in body["profiles"][0]["expectation_summary"]
    easy_profile = next(profile for profile in body["profiles"] if profile["profile"] == "easy")
    assert easy_profile["provider_hint_order"][0] == "gemini_vortex"
    assert "onemin" in easy_profile["provider_hint_order"]
    assert easy_profile["backend"] == "gemini_vortex"
    assert easy_profile["health_provider_key"] == "gemini_vortex"
    assert easy_profile["work_class"] == "easy"
    assert "Easy lane" in easy_profile["expectation_summary"]
    assert easy_profile["review_cadence"]["review"] == "weekly"
    assert easy_profile["support_help_boundary"]["owner"] == "chummer6-hub"
    repair_profile = next(profile for profile in body["profiles"] if profile["profile"] == "repair")
    assert repair_profile["lane"] == "repair"
    assert repair_profile["provider_hint_order"][0] == "gemini_vortex"
    assert "onemin" in repair_profile["provider_hint_order"]
    assert repair_profile["model"] == "ea-repair-gemini"
    assert repair_profile["backend"] == "gemini_vortex"
    assert repair_profile["health_provider_key"] == "gemini_vortex"
    groundwork_profile = next(profile for profile in body["profiles"] if profile["profile"] == "groundwork")
    assert groundwork_profile["lane"] == "groundwork"
    assert groundwork_profile["provider_hint_order"] == ["gemini_vortex"]
    assert groundwork_profile["model"] == "ea-groundwork-gemini"
    assert groundwork_profile["backend"] == "gemini_vortex"
    assert groundwork_profile["health_provider_key"] == "gemini_vortex"
    assert groundwork_profile["provider_slot_pool"]["selection_mode"] in {"fallback", "round_robin"}
    assert [slot["slot_owner"] for slot in groundwork_profile["provider_slots"]] == ["", ""]
    assert groundwork_profile["provider_slot_pool"]["last_used_hub_user_id"] == ""
    assert groundwork_profile["provider_slot_pool"]["last_used_hub_group_id"] == ""
    assert groundwork_profile["provider_slot_pool"]["last_used_sponsor_session_id"] == ""
    assert groundwork_profile["provider_slot_pool"]["last_used_lane_role"] == ""
    assert groundwork_profile["work_class"] == "groundwork"
    assert "Groundwork lane" in groundwork_profile["expectation_summary"]
    review_light_profile = next(profile for profile in body["profiles"] if profile["profile"] == "review_light")
    assert review_light_profile["lane"] == "review"
    assert review_light_profile["provider_hint_order"] == ["browseract"]
    assert review_light_profile["backend"] == "chatplayground"
    assert review_light_profile["health_provider_key"] == "chatplayground"
    survival_profile = next(profile for profile in body["profiles"] if profile["profile"] == "survival")
    assert survival_profile["lane"] == "survival"
    assert survival_profile["provider_hint_order"] == ["onemin", "gemini_vortex", "browseract"]
    assert survival_profile["backend"] == "onemin"
    assert survival_profile["health_provider_key"] == "onemin"
    assert body["provider_health"]["providers"]["onemin"]["backend"] == "1min"
    assert body["provider_health"]["providers"]["magixai"]["slots"][0]["account_name"] == ""
    assert body["provider_health"]["providers"]["onemin"]["slots"][0]["account_name"] == ""
    assert body["provider_health"]["providers"]["chatplayground"]["slots"][0]["account_name"] == ""
    assert body["provider_health"]["provider_config"]["onemin_accounts"] == []
    assert body["provider_health"]["provider_config"]["chatplayground_accounts"] == []
    assert body["provider_registry"]["contract_name"] == "ea.provider_registry"
    groundwork_lane = next(item for item in body["provider_registry"]["lanes"] if item["profile"] == "groundwork")
    assert groundwork_lane["backend"] == "gemini_vortex"
    assert groundwork_lane["capacity_summary"]["configured_slots"] == 2
    assert groundwork_lane["capacity_summary"]["slot_owners"] == []
    assert groundwork_lane["capacity_summary"]["last_used_hub_user_id"] == ""
    assert groundwork_lane["capacity_summary"]["last_used_hub_group_id"] == ""
    assert groundwork_lane["capacity_summary"]["last_used_sponsor_session_id"] == ""
    assert groundwork_lane["capacity_summary"]["last_used_lane_role"] == ""
    review_light_lane = next(item for item in body["provider_registry"]["lanes"] if item["profile"] == "review_light")
    assert review_light_lane["health_provider_key"] == "chatplayground"


def test_stabilize_codex_profile_promotes_repair_model_to_onemin_backend() -> None:
    from app.api.routes import responses

    profile = responses._stabilize_codex_profile(
        {
            "profile": "repair",
            "lane": "repair",
            "model": "ea-coder-fast",
            "provider_hint_order": ["onemin"],
            "backend": "onemin",
            "health_provider_key": "onemin",
        }
    )

    assert profile["model"] == "ea-onemin-coder"


def test_stabilize_codex_profile_promotes_repair_model_when_onemin_only_reports_ready_slots() -> None:
    from app.api.routes import responses

    profile = responses._stabilize_codex_profile(
        {
            "profile": "repair",
            "lane": "repair",
            "model": "ea-coder-fast",
            "provider_hint_order": ["magixai", "onemin"],
            "backend": "magixai",
            "health_provider_key": "magixai",
        },
        provider_health={
            "providers": {
                "magixai": {"state": "degraded"},
                "onemin": {"slots": [{"state": "ready"}]},
            }
        },
    )

    assert profile["backend"] == "onemin"
    assert profile["health_provider_key"] == "onemin"
    assert profile["provider_hint_order"][0] == "onemin"
    assert profile["model"] == "ea-onemin-coder"


def test_codex_profile_index_promotes_repair_to_onemin_when_live_provider_health_prefers_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(principal_id="codex-repair-fallback")
    from app.api.routes import responses

    monkeypatch.setenv("ONEMIN_AI_API_KEY", "onemin-key")
    monkeypatch.setattr(
        responses,
        "_provider_health_report",
        lambda: {
            "providers": {
                "gemini_vortex": {"state": "degraded"},
                "magixai": {"state": "degraded"},
                "onemin": {"state": "ready"},
            }
        },
    )

    response = client.get("/v1/codex/profiles")

    assert response.status_code == 200
    body = response.json()
    repair_profile = next(profile for profile in body["profiles"] if profile["profile"] == "repair")
    assert repair_profile["provider_hint_order"][0] == "onemin"
    assert repair_profile["backend"] == "onemin"
    assert repair_profile["health_provider_key"] == "onemin"
    assert repair_profile["model"] == "ea-onemin-coder"


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
    assert [slot["account_name"] for slot in providers["chatplayground"]["slots"]] == ["", ""]
    assert providers["magixai"]["configured_slots"] == 1
    assert providers["magixai"]["state"] in {"ready", "unknown", "degraded"}
    assert body["provider_config"]["onemin_accounts"] == []
    assert body["provider_config"]["default_profile"] == "easy"
    assert body["provider_config"]["default_lane"] == "fast"
    assert body["provider_config"]["provider_order"] == ["magixai", "onemin"]
    assert body["provider_config"]["onemin_active_accounts"] == []
    assert body["provider_config"]["onemin_reserve_accounts"] == []
    assert body["provider_config"]["onemin_max_requests_per_hour"] == 120
    assert body["provider_config"]["onemin_max_credits_per_hour"] == 80000
    assert body["provider_config"]["onemin_max_credits_per_day"] == 600000
    assert body["provider_config"]["hard_max_active_requests"] == 1
    assert body["provider_config"]["hard_queue_timeout_seconds"] == 120.0
    assert body["provider_config"]["chatplayground_accounts"] == []
    assert providers["onemin"]["slots"][0]["next_retry_at"] is None
    assert providers["onemin"]["slots"][0]["upstream_reset_unknown"] is False
    assert providers["onemin"]["slots"][0]["observed_consumed_credits"] == 0
    assert providers["onemin"]["slots"][0]["observed_success_count"] == 0
    assert providers["onemin"]["slots"][0]["slot_env_name"] == "ONEMIN_AI_API_KEY"
    assert providers["onemin"]["slots"][0]["slot_role"] == "active"
    assert providers["onemin"]["slots"][0]["owner_label"] == ""
    assert providers["onemin"]["slots"][0]["last_probe_result"] is None
    assert providers["onemin"]["slots"][2]["slot_role"] == "reserve"
    assert "estimated_burn_credits_per_hour" in providers["onemin"]
    assert "estimated_hours_remaining_at_current_pace" in providers["onemin"]
    assert "burn_estimate_basis" in providers["onemin"]
    assert providers["onemin"]["max_requests_per_hour"] == 120
    assert providers["onemin"]["max_credits_per_hour"] == 80000
    assert providers["onemin"]["max_credits_per_day"] == 600000
    assert body["provider_registry"]["contract_name"] == "ea.provider_registry"
    onemin_provider = next(item for item in body["provider_registry"]["providers"] if item["provider_key"] == "onemin")
    assert onemin_provider["slot_pool"]["configured_slots"] == 34
    assert onemin_provider["backend"] == "1min"
    core_lane = next(item for item in body["provider_registry"]["lanes"] if item["profile"] == "core")
    assert core_lane["backend"] == "onemin"
    assert core_lane["primary_provider_key"] == "onemin"


def test_responses_provider_health_endpoint_supports_lightweight_query(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(principal_id="codex-health-operator", operator=True)
    from app.api.routes import responses

    calls: list[bool] = []

    def fake_provider_health_report(*, lightweight: bool = False) -> dict[str, object]:
        calls.append(lightweight)
        return {
            "providers": {
                "onemin": {
                    "provider_key": "onemin",
                    "backend": "1min",
                    "configured_slots": 1,
                    "slots": [{"slot": "primary", "account_name": "slot-a"}],
                }
            },
            "provider_config": {"provider_order": ["onemin"]},
        }

    monkeypatch.setattr(responses, "_provider_health_report", fake_provider_health_report)
    monkeypatch.setattr(
        responses,
        "_provider_registry_payload",
        lambda **_: {"lanes": [{"profile": "core", "state": "ready"}]},
    )

    response = client.get("/v1/responses/_provider_health?lightweight=1")

    assert response.status_code == 200
    assert calls == [True]
    body = response.json()
    assert body["providers"]["onemin"]["configured_slots"] == 1
    assert body["provider_registry"]["lanes"][0]["profile"] == "core"


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

    for key in list(os.environ.keys()):
        if key.startswith("ONEMIN_AI_API_KEY") or key.startswith("EA_RESPONSES_ONEMIN_"):
            monkeypatch.delenv(key, raising=False)

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
    assert onemin["estimated_remaining_credits_total"] == 0
    assert onemin["remaining_percent_of_max"] is None
    assert onemin["unknown_balance_slots"] == 1
    healthy_slot = next(slot for slot in onemin["slots"] if slot["account_name"] == "ONEMIN_AI_API_KEY")
    assert healthy_slot["estimated_remaining_credits"] is None
    assert healthy_slot["estimated_credit_basis"] == "unknown_unprobed"


def test_responses_provider_health_keeps_fresh_onemin_slots_unknown_until_observed(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import responses_upstream as upstream

    upstream._test_reset_onemin_states()
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "fresh-primary")

    health = upstream._provider_health_report()
    slot = health["providers"]["onemin"]["slots"][0]

    assert slot["estimated_remaining_credits"] is None
    assert slot["estimated_credit_basis"] == "unknown_unprobed"
    assert health["providers"]["onemin"]["remaining_percent_of_max"] is None


def test_codex_status_endpoint_reports_savings_text(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(principal_id="codex-status")
    from app.services import responses_upstream as upstream

    upstream._test_reset_onemin_states()
    upstream._test_reset_fleet_jury_cache()
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "savings-key")

    upstream._record_onemin_usage_event(
        api_key="savings-key",
        model="gpt-5",
        tokens_in=100,
        tokens_out=50,
        lane="hard",
    )
    upstream._record_provider_dispatch_event(
        provider_key="gemini_vortex",
        model="gemini-2.5-flash",
        lane="fast",
        estimated_onemin_credits=300,
    )
    upstream._record_provider_dispatch_event(
        provider_key="chatplayground",
        model="judge-model",
        lane="audit",
        estimated_onemin_credits=150,
    )

    response = client.get("/v1/codex/status?window=1h")
    assert response.status_code == 200
    body = response.json()
    assert body["governance"]["review_cadence"]["review"] == "weekly"
    assert body["governance"]["support_help_boundary"]["owner"] == "chummer6-hub"
    avoided = body["avoided_credits"]["selected_window"]
    assert avoided["easy_lane"]["avoided_credits"] == 0
    assert avoided["jury_lane"]["avoided_credits"] == 0
    assert body["avoided_credits"]["selected_window_text"]["easy"] == "No measurable easy lane savings yet in this window."
    assert body["avoided_credits"]["selected_window_text"]["jury"] == "No measurable jury lane savings yet in this window."


def test_codex_status_endpoint_exposes_fleet_jury_service(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(principal_id="codex-status")
    from app.services import responses_upstream as upstream

    upstream._test_reset_onemin_states()
    upstream._test_reset_fleet_jury_cache()
    monkeypatch.setenv("EA_FLEET_STATUS_BASE_URL", "http://fleet.example")

    def fake_get_json(*, url: str, headers: dict[str, str], timeout_seconds: float):
        assert url == "http://fleet.example/api/cockpit/jury-telemetry"
        return (
            200,
            {
                "active_jury_jobs": 2,
                "queued_jury_jobs": 1,
                "blocked_total_workers": 4,
            },
        )

    monkeypatch.setattr(upstream, "_get_json", fake_get_json)

    response = client.get("/v1/codex/status?window=1h")
    assert response.status_code == 200
    body = response.json()
    assert body["jury_service"] == {}
    assert body["provider_health"] == {}


def test_codex_status_endpoint_exposes_onemin_probe_aggregate(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(principal_id="codex-status")
    from app.services import responses_upstream as upstream

    upstream._test_reset_onemin_states()
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "status-primary")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_1", "status-deleted")
    monkeypatch.setenv(
        "EA_RESPONSES_ONEMIN_OWNER_LEDGER_JSON",
        json.dumps(
            {
                "slots": [
                    {
                        "secret_sha256": hashlib.sha256(b"status-primary").hexdigest(),
                        "owner_email": "status@example.com",
                    }
                ]
            }
        ),
    )

    def fake_post_json(*, url: str, headers: dict[str, str], payload: dict[str, object], timeout_seconds: int) -> tuple[int, dict[str, object]]:
        if headers["API-KEY"] == "status-primary":
            return (
                200,
                {
                    "aiRecord": {
                        "model": "gpt-4.1",
                        "aiRecordDetail": {"resultObject": "OK"},
                    }
                },
            )
        return (401, {"errorCode": "HTTP_EXCEPTION", "message": "API Key has been deleted"})

    monkeypatch.setattr(upstream, "_post_json", fake_post_json)
    upstream.probe_all_onemin_slots()

    response = client.get("/v1/codex/status?window=7d&refresh=1")
    assert response.status_code == 200
    body = response.json()
    assert body["onemin_aggregate"] == {}


def test_codex_status_endpoint_exposes_onemin_billing_aggregate(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("EA_RESPONSES_PROVIDER_LEDGER_DIR", str(tmp_path))
    client = _client(principal_id="codex-status-billing")
    from app.services import responses_upstream as upstream

    upstream._test_reset_onemin_states()
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "billing-primary")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_1", "billing-fallback")

    upstream.record_onemin_billing_snapshot(
        account_name="ONEMIN_AI_API_KEY",
        snapshot_json={
            "observed_at": "2026-03-18T09:00:00Z",
            "remaining_credits": 800000,
            "max_credits": 1000000,
            "used_percent": 20.0,
            "next_topup_at": "2026-03-31T00:00:00Z",
            "topup_amount": 1000000,
            "rollover_enabled": True,
            "basis": "actual_billing_usage_page",
            "source_url": "https://app.1min.ai/billing-usage",
            "structured_output_json": {
                "raw_text": "Remaining credits: 800000",
                "billing_overview_json": {
                    "plan_name": "BUSINESS",
                    "billing_cycle": "LIFETIME",
                    "subscription_status": "Active",
                    "daily_bonus_cta_text": "Unlock Free Credits",
                    "daily_bonus_available": True,
                    "daily_bonus_credits": 500,
                },
                "usage_summary_json": {
                    "usage_history_count": 10,
                    "latest_usage_at": "2026-03-18T09:04:00Z",
                    "earliest_usage_at": "2026-03-18T07:04:00Z",
                    "observed_usage_credits_total": 2400,
                    "observed_usage_window_hours": 2.0,
                    "observed_usage_burn_credits_per_hour": 1200.0,
                },
            },
        },
    )
    upstream.record_onemin_billing_snapshot(
        account_name="ONEMIN_AI_API_KEY_FALLBACK_1",
        snapshot_json={
            "observed_at": "2026-03-18T09:05:00Z",
            "remaining_credits": 200000,
            "max_credits": 1000000,
            "used_percent": 80.0,
            "next_topup_at": "2026-03-31T00:00:00Z",
            "topup_amount": 1000000,
            "rollover_enabled": True,
            "basis": "actual_billing_usage_page",
            "source_url": "https://app.1min.ai/billing-usage",
            "structured_output_json": {
                "raw_text": "Remaining credits: 200000",
                "billing_overview_json": {
                    "plan_name": "BUSINESS",
                    "billing_cycle": "LIFETIME",
                    "subscription_status": "Active",
                    "daily_bonus_available": False,
                },
                "usage_summary_json": {
                    "usage_history_count": 4,
                    "latest_usage_at": "2026-03-18T08:55:00Z",
                    "earliest_usage_at": "2026-03-18T07:55:00Z",
                    "observed_usage_credits_total": 300,
                    "observed_usage_window_hours": 1.0,
                    "observed_usage_burn_credits_per_hour": 300.0,
                },
            },
        },
    )
    upstream.record_onemin_member_reconciliation_snapshot(
        account_name="ONEMIN_AI_API_KEY",
        snapshot_json={
            "observed_at": "2026-03-18T09:10:00Z",
            "basis": "actual_members_page",
            "source_url": "https://app.1min.ai/members",
            "members_json": [{"email": "billing@example.com", "status": "active"}],
            "structured_output_json": {"raw_text": "billing@example.com"},
        },
    )

    response = client.get("/v1/codex/status?window=7d&refresh=1")
    assert response.status_code == 200
    body = response.json()
    assert body["onemin_billing_aggregate"] == {}
    assert body["topup_summary"] == {}
    assert body["providers_summary"] == []


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
    monkeypatch.setenv("EA_GEMINI_VORTEX_MODEL", "gemini-2.5-flash")
    monkeypatch.setenv("GOOGLE_API_KEY_FALLBACK_1", "vertex-fallback")
    monkeypatch.setenv("EA_GEMINI_VORTEX_SELECTION_MODE", "round_robin")
    monkeypatch.setenv("EA_GEMINI_VORTEX_SLOT_DEFAULT_OWNER", "fleet-primary")
    monkeypatch.setenv("EA_GEMINI_VORTEX_SLOT_FALLBACK_1_OWNER", "fleet-shadow")

    response = client.get("/v1/responses/_provider_health")
    assert response.status_code == 200
    body = response.json()
    assert body["providers"]["gemini_vortex"]["state"] == "ready"
    assert "gemini-2.5-flash" in body["providers"]["gemini_vortex"]["models"]
    assert body["providers"]["gemini_vortex"]["selection_mode"] == "round_robin"
    assert [slot["account_name"] for slot in body["providers"]["gemini_vortex"]["slots"]] == ["", ""]
    assert [slot["slot_owner"] for slot in body["providers"]["gemini_vortex"]["slots"]] == ["", ""]
    assert body["provider_config"]["gemini_vortex_command"] == "sh"
    assert body["provider_config"]["gemini_vortex_accounts"] == []


def test_operator_provider_health_keeps_sensitive_slot_labels(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(principal_id="codex-health-operator", operator=True)

    monkeypatch.setenv("EA_GEMINI_VORTEX_COMMAND", "sh")
    monkeypatch.setenv("EA_GEMINI_VORTEX_MODEL", "gemini-2.5-flash")
    monkeypatch.setenv("GOOGLE_API_KEY_FALLBACK_1", "vertex-fallback")
    monkeypatch.setenv("EA_GEMINI_VORTEX_SLOT_DEFAULT_OWNER", "fleet-primary")
    monkeypatch.setenv("EA_GEMINI_VORTEX_SLOT_FALLBACK_1_OWNER", "fleet-shadow")

    response = client.get("/v1/responses/_provider_health")
    assert response.status_code == 200
    body = response.json()
    assert [slot["account_name"] for slot in body["providers"]["gemini_vortex"]["slots"]] == [
        "EA_GEMINI_VORTEX_DEFAULT_AUTH",
        "GOOGLE_API_KEY_FALLBACK_1",
    ]


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
