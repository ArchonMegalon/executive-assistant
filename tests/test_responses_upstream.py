from __future__ import annotations

import pytest

from app.services import responses_upstream as upstream


def test_provider_candidates_expand_coding_model_chains(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EA_RESPONSES_PROVIDER_ORDER", "magicxai,onemin")
    monkeypatch.setenv("EA_RESPONSES_MAGICX_MODELS", "mx-best,mx-fallback")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_MODELS", "om-best,om-fallback")

    candidates = [
        (config.provider_key, model)
        for config, model in upstream._provider_candidates(upstream.DEFAULT_PUBLIC_MODEL)
    ]

    assert candidates == [
        ("magixai", "mx-best"),
        ("magixai", "mx-fallback"),
        ("onemin", "om-best"),
        ("onemin", "om-fallback"),
    ]


def test_provider_prefixed_request_uses_explicit_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EA_RESPONSES_MAGICX_MODELS", "mx-best,mx-fallback")

    candidates = [
        (config.provider_key, model)
        for config, model in upstream._provider_candidates("magicx:claude-sonnet-4.5")
    ]

    assert candidates == [("magixai", "claude-sonnet-4.5")]


def test_call_magicx_uses_bearer_auth_and_url_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_MAGICX_API_KEY", "magicx-key")
    monkeypatch.setenv(
        "EA_RESPONSES_MAGICX_URLS",
        "https://bad.magicx.local/api/v1/chat,https://good.magicx.local/api/v1/chat",
    )
    monkeypatch.setenv("EA_RESPONSES_MAGICX_MODELS", "openai/gpt-5.1-codex-mini")
    monkeypatch.setenv("EA_RESPONSES_MAGICX_MAX_TOKENS", "48")

    calls: list[tuple[str, dict[str, str], dict[str, object]]] = []

    def fake_post_json(*, url: str, headers: dict[str, str], payload: dict[str, object], timeout_seconds: int) -> tuple[int, dict[str, object]]:
        calls.append((url, headers, payload))
        if "bad.magicx.local" in url:
            return (405, {"error": "method_not_allowed"})
        return (
            200,
            {
                "model": "openai/gpt-5.1-codex-mini",
                "choices": [
                    {
                        "message": {
                            "content": "ok",
                        }
                    }
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 3},
            },
        )

    monkeypatch.setattr(upstream, "_post_json", fake_post_json)

    result = upstream.generate_text(prompt="say ok", requested_model=upstream.MAGICX_PUBLIC_MODEL)

    assert result.provider_key == "magixai"
    assert result.model == "openai/gpt-5.1-codex-mini"
    assert result.text == "ok"
    assert [url for url, _, _ in calls] == [
        "https://bad.magicx.local/api/v1/chat",
        "https://good.magicx.local/api/v1/chat",
    ]
    assert calls[0][1]["Authorization"] == "Bearer magicx-key"
    assert calls[0][2]["messages"] == [{"role": "user", "content": "say ok"}]
    assert calls[0][2]["max_tokens"] == 48


def test_call_onemin_retries_keys_and_falls_back_from_code_to_chat(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "inactive-key")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_1", "active-key")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_CODE_MODELS", "gpt-5")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_MODELS", "gpt-5")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_CODE_URL", "https://api.1min.ai/api/features")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_CHAT_URL", "https://api.1min.ai/api/chat-with-ai")

    calls: list[tuple[str, str, dict[str, object]]] = []

    def fake_post_json(*, url: str, headers: dict[str, str], payload: dict[str, object], timeout_seconds: int) -> tuple[int, dict[str, object]]:
        key = headers["API-KEY"]
        calls.append((url, key, payload))
        if key == "inactive-key":
            return (401, {"errorCode": "HTTP_EXCEPTION", "message": "API Key is not active. Please contact your team administrator to be unblocked"})
        if url.endswith("/api/features"):
            return (
                200,
                {
                    "aiRecord": {
                        "aiRecordDetail": {
                            "resultObject": {
                                "code": "INSUFFICIENT_CREDITS",
                                "message": "Top-tier code credits are exhausted",
                            }
                        }
                    }
                },
            )
        return (
            200,
            {
                "aiRecord": {
                    "model": "gpt-5",
                    "aiRecordDetail": {
                        "resultObject": ["chat fallback answer"],
                    },
                }
            },
        )

    monkeypatch.setattr(upstream, "_post_json", fake_post_json)

    result = upstream.generate_text(prompt="write code", requested_model=upstream.ONEMIN_PUBLIC_MODEL)

    assert result.provider_key == "onemin"
    assert result.model == "gpt-5"
    assert result.text == "chat fallback answer"
    assert calls == [
        (
            "https://api.1min.ai/api/features",
            "inactive-key",
            {"type": "CODE_GENERATOR", "model": "gpt-5", "promptObject": {"prompt": "write code"}},
        ),
        (
            "https://api.1min.ai/api/features",
            "active-key",
            {"type": "CODE_GENERATOR", "model": "gpt-5", "promptObject": {"prompt": "write code"}},
        ),
        (
            "https://api.1min.ai/api/chat-with-ai",
            "active-key",
            {"type": "UNIFY_CHAT_WITH_AI", "model": "gpt-5", "promptObject": {"prompt": "write code"}},
        ),
    ]
