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
        ("magixai", "x-ai/grok-code-fast-1"),
        ("magixai", "mistralai/codestral-2508"),
        ("magixai", "openai/gpt-5.1-codex-mini"),
        ("magixai", "inception/mercury-coder"),
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


def test_normalize_provider_aliases_for_magicx_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EA_RESPONSES_MAGICX_MODELS", "mx-best")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_MODELS", "gpt-5")

    for alias in ("magicxai", "aimagicx", "ai_magicx"):
        candidates = [
            (config.provider_key, model)
            for config, model in upstream._provider_candidates(f"{alias}:grok")
        ]
        assert candidates == [("magixai", "grok")]


def test_audit_model_candidates_route_to_chatplayground(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EA_RESPONSES_CHATPLAYGROUND_MODELS", "judge-model,jury-model")
    monkeypatch.setenv("BROWSERACT_API_KEY", "chatplayground-key")
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_1", "")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_2", "")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_3", "")
    monkeypatch.setenv("AI_MAGICX_API_KEY", "")

    candidates = [
        (config.provider_key, model)
        for config, model in upstream._provider_candidates(upstream.AUDIT_PUBLIC_MODEL)
    ]
    assert candidates == [("chatplayground", "judge-model"), ("chatplayground", "jury-model")]


def test_audit_alias_candidates_route_to_chatplayground(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EA_RESPONSES_CHATPLAYGROUND_MODELS", "judge-model")
    monkeypatch.setenv("BROWSERACT_API_KEY", "chatplayground-key")
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_1", "")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_2", "")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_3", "")
    monkeypatch.setenv("AI_MAGICX_API_KEY", "")

    candidates = [
        (config.provider_key, model)
        for config, model in upstream._provider_candidates(upstream.AUDIT_PUBLIC_MODEL_ALIAS)
    ]
    assert candidates == [("chatplayground", "judge-model")]


def test_audit_model_candidates_include_onemin_if_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EA_RESPONSES_CHATPLAYGROUND_MODELS", "judge-model")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_MODELS", "deepseek-chat")
    monkeypatch.setenv("BROWSERACT_API_KEY", "chatplayground-key")
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "onemin-primary")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_1", "onemin-fallback")

    candidates = [
        (config.provider_key, model)
        for config, model in upstream._provider_candidates(upstream.AUDIT_PUBLIC_MODEL)
    ]
    assert candidates == [
        ("chatplayground", "judge-model"),
        ("onemin", "deepseek-chat"),
        ("onemin", "gpt-4.1-nano"),
        ("onemin", "gpt-4.1"),
    ]


def test_normalize_provider_aliases_for_onemin_in_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EA_RESPONSES_PROVIDER_ORDER", "1min,magicx")
    monkeypatch.setenv("EA_RESPONSES_MAGICX_MODELS", "mx-best")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_MODELS", "om-best")

    assert upstream._provider_order() == ("onemin", "magixai")


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


def test_call_magicx_preserves_system_and_user_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_MAGICX_API_KEY", "magicx-key")
    monkeypatch.setenv("EA_RESPONSES_MAGICX_URLS", "https://good.magicx.local/api/v1/chat/completions")
    monkeypatch.setenv("EA_RESPONSES_MAGICX_MODELS", "openai/gpt-5.1-codex-mini")

    calls: list[dict[str, object]] = []

    def fake_post_json(*, url: str, headers: dict[str, str], payload: dict[str, object], timeout_seconds: int) -> tuple[int, dict[str, object]]:
        calls.append(payload)
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
            },
        )

    monkeypatch.setattr(upstream, "_post_json", fake_post_json)

    upstream.generate_text(
        requested_model=upstream.MAGICX_PUBLIC_MODEL,
        messages=[
            {"role": "system", "content": "follow repo rules"},
            {"role": "developer", "content": "keep it short"},
            {"role": "user", "content": "say ok"},
        ],
    )

    assert calls[0]["messages"] == [
        {"role": "system", "content": "follow repo rules\n\nkeep it short"},
        {"role": "user", "content": "say ok"},
    ]


def test_call_magicx_populates_provider_account_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_MAGICX_API_KEY", "magicx-primary")
    monkeypatch.setenv("EA_RESPONSES_MAGICX_URLS", "https://good.magicx.local/api/v1/chat/completions")
    monkeypatch.setenv("EA_RESPONSES_MAGICX_MODELS", "openai/gpt-5.1-codex-mini")

    def fake_post_json(*, url: str, headers: dict[str, str], payload: dict[str, object], timeout_seconds: int) -> tuple[int, dict[str, object]]:
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
            },
        )

    monkeypatch.setattr(upstream, "_post_json", fake_post_json)

    result = upstream.generate_text(requested_model=upstream.MAGICX_PUBLIC_MODEL, prompt="ping")
    assert result.provider_backend == "aimagicx"
    assert result.provider_account_name == "EA_RESPONSES_MAGICX_API_KEY"


def test_call_onemin_populates_provider_account_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "onemin-primary")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_1", "onemin-secondary")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_MODELS", "gpt-4.1")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_CHAT_URL", "https://api.1min.ai/api/chat-with-ai")

    def fake_post_json(*, url: str, headers: dict[str, str], payload: dict[str, object], timeout_seconds: int) -> tuple[int, dict[str, object]]:
        assert headers["API-KEY"] == "onemin-primary"
        return (
            200,
            {
                "aiRecord": {
                    "model": "gpt-4.1",
                    "aiRecordDetail": {
                        "resultObject": ["ok"],
                    },
                },
            },
        )

    monkeypatch.setattr(upstream, "_post_json", fake_post_json)

    result = upstream.generate_text(requested_model=upstream.ONEMIN_PUBLIC_MODEL, prompt="ping")
    assert result.provider_backend == "1min"
    assert result.provider_account_name == "ONEMIN_AI_API_KEY"


def test_call_magicx_retries_with_smaller_token_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_MAGICX_API_KEY", "magicx-key")
    monkeypatch.setenv("EA_RESPONSES_MAGICX_URLS", "https://good.magicx.local/api/v1/chat/completions")
    monkeypatch.setenv("EA_RESPONSES_MAGICX_MODELS", "openai/gpt-5.1-codex-mini")

    calls: list[dict[str, object]] = []

    def fake_post_json(*, url: str, headers: dict[str, str], payload: dict[str, object], timeout_seconds: int) -> tuple[int, dict[str, object]]:
        calls.append(payload)
        if payload["max_tokens"] == 128:
            return (
                500,
                {
                    "error": (
                        "This request requires more credits, or fewer max_tokens. "
                        "You requested up to 128 tokens, but can only afford 127."
                    )
                },
            )
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
            },
        )

    monkeypatch.setattr(upstream, "_post_json", fake_post_json)

    result = upstream.generate_text(
        prompt="say ok",
        requested_model=upstream.MAGICX_PUBLIC_MODEL,
        max_output_tokens=128,
    )

    assert result.text == "ok"
    assert [payload["max_tokens"] for payload in calls] == [128, 16]


def test_call_onemin_fully_depletes_rotation_keys_and_fallbacks_to_magicx(monkeypatch: pytest.MonkeyPatch) -> None:
    upstream._test_reset_onemin_key_cursor()
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "depleted-key-1")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_1", "depleted-key-2")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_2", "depleted-key-3")
    monkeypatch.setenv("AI_MAGICX_API_KEY", "magicx-key")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_CHAT_URL", "https://api.1min.ai/api/chat-with-ai")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_MODELS", "gpt-4.1")
    monkeypatch.setenv("EA_RESPONSES_MAGICX_URLS", "https://good.magicx.local/api/v1/chat/completions")
    monkeypatch.setenv("EA_RESPONSES_MAGICX_MODELS", "openai/gpt-5.1-codex-mini")

    calls: list[tuple[str, str]] = []

    def fake_post_json(*, url: str, headers: dict[str, str], payload: dict[str, object], timeout_seconds: int) -> tuple[int, dict[str, object]]:
        if headers.get("API-KEY"):
            calls.append((url, headers["API-KEY"]))
            return (
                200,
                {
                    "aiRecord": {
                        "model": "gpt-4.1",
                        "aiRecordDetail": {
                            "resultObject": {
                                "code": "INSUFFICIENT_CREDITS",
                                "message": "Top-tier chat credits are exhausted",
                            },
                        },
                    },
                },
            )
        calls.append((url, headers["Authorization"]))
        return (
            200,
            {
                "model": "openai/gpt-5.1-codex-mini",
                "choices": [{"message": {"content": "magicx answer"}}],
            },
        )

    monkeypatch.setattr(upstream, "_post_json", fake_post_json)

    result = upstream.generate_text(prompt="write fix", requested_model="gpt-4.1")

    assert result.provider_key == "magixai"
    assert result.text == "magicx answer"
    assert calls == [
        ("https://api.1min.ai/api/chat-with-ai", "depleted-key-1"),
        ("https://api.1min.ai/api/chat-with-ai", "depleted-key-2"),
        ("https://api.1min.ai/api/chat-with-ai", "depleted-key-3"),
        ("https://good.magicx.local/api/v1/chat/completions", "Bearer magicx-key"),
    ]


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


def test_call_onemin_flattens_structured_messages_into_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "active-key")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_MODELS", "gpt-4.1")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_CHAT_URL", "https://api.1min.ai/api/chat-with-ai")

    calls: list[dict[str, object]] = []

    def fake_post_json(*, url: str, headers: dict[str, str], payload: dict[str, object], timeout_seconds: int) -> tuple[int, dict[str, object]]:
        calls.append(payload)
        return (
            200,
            {
                "aiRecord": {
                    "model": "gpt-4.1",
                    "aiRecordDetail": {
                        "resultObject": ["ok"],
                    },
                }
            },
        )

    monkeypatch.setattr(upstream, "_post_json", fake_post_json)

    upstream.generate_text(
        requested_model=upstream.ONEMIN_PUBLIC_MODEL,
        messages=[
            {"role": "system", "content": "follow repo rules"},
            {"role": "user", "content": "say ok"},
        ],
    )

    assert calls[0]["promptObject"]["prompt"] == "System:\nfollow repo rules\n\nUser:\nsay ok"


def test_onemin_depletion_rotates_cursor_for_future_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    upstream._test_reset_onemin_key_cursor()
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "depleted-key")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_1", "fallback-key")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_2", "unused-key")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_MODELS", "gpt-4.1")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_CHAT_URL", "https://api.1min.ai/api/chat-with-ai")

    calls: list[tuple[str, str]] = []

    def fake_post_json(*, url: str, headers: dict[str, str], payload: dict[str, object], timeout_seconds: int) -> tuple[int, dict[str, object]]:
        api_key = headers["API-KEY"]
        calls.append((url, api_key))
        if api_key == "depleted-key":
            return (
                200,
                {
                    "aiRecord": {
                        "model": "gpt-4.1",
                        "aiRecordDetail": {
                            "resultObject": {
                                "code": "INSUFFICIENT_CREDITS",
                                "message": "Top-tier code and chat credits are exhausted",
                            }
                        },
                    }
                },
            )
        return (
            200,
            {
                "aiRecord": {
                    "model": "gpt-4.1",
                    "aiRecordDetail": {
                        "resultObject": ["depleted-key rotated"],
                    },
                }
            },
        )

    monkeypatch.setattr(upstream, "_post_json", fake_post_json)

    first = upstream.generate_text(prompt="first", requested_model=upstream.ONEMIN_PUBLIC_MODEL)
    assert first.text == "depleted-key rotated"
    assert calls == [
        ("https://api.1min.ai/api/chat-with-ai", "depleted-key"),
        ("https://api.1min.ai/api/chat-with-ai", "fallback-key"),
    ]


def test_call_onemin_429_rotates_to_next_key(monkeypatch: pytest.MonkeyPatch) -> None:
    upstream._test_reset_onemin_states()
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "burst-key-1")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_1", "burst-key-2")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_2", "burst-key-3")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_CHAT_URL", "https://api.1min.ai/api/chat-with-ai")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_MODELS", "gpt-4.1")

    calls: list[tuple[str, str]] = []

    def fake_post_json(*, url: str, headers: dict[str, str], payload: dict[str, object], timeout_seconds: int) -> tuple[int, dict[str, object]]:
        api_key = headers["API-KEY"]
        calls.append((url, api_key))
        if api_key == "burst-key-1":
            return (429, {"error": "too many requests"})
        return (
            200,
            {
                "aiRecord": {
                    "model": "gpt-4.1",
                    "aiRecordDetail": {
                        "resultObject": ["rotated response"],
                    },
                }
            },
        )

    monkeypatch.setattr(upstream, "_post_json", fake_post_json)

    result = upstream.generate_text(prompt="rate check", requested_model=upstream.ONEMIN_PUBLIC_MODEL)
    assert result.provider_key == "onemin"
    assert result.text == "rotated response"
    assert calls == [
        ("https://api.1min.ai/api/chat-with-ai", "burst-key-1"),
        ("https://api.1min.ai/api/chat-with-ai", "burst-key-2"),
    ]


def test_call_magicx_probe_marks_degraded_when_api_not_available(monkeypatch: pytest.MonkeyPatch) -> None:
    upstream._test_reset_onemin_states()
    monkeypatch.setenv("EA_RESPONSES_PROVIDER_ORDER", "magixai")
    monkeypatch.setenv("EA_RESPONSES_MAGICX_HEALTH_CHECK", "1")
    monkeypatch.setenv("EA_RESPONSES_MAGICX_HEALTH_TIMEOUT_SECONDS", "1")
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "unused-key")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_MODELS", "gpt-4.1")
    monkeypatch.setenv("AI_MAGICX_API_KEY", "disabled-key")
    monkeypatch.setenv("EA_RESPONSES_MAGICX_MODELS", "openai/gpt-5.1-codex-mini")

    calls: list[tuple[str, str]] = []

    def fake_post_json(*, url: str, headers: dict[str, str], payload: dict[str, object], timeout_seconds: int) -> tuple[int, dict[str, object]]:
        calls.append((url, headers.get("Authorization", headers.get("API-KEY", ""))))
        if headers.get("Authorization"):
            return (401, {"error": "invalid api key"})
        return (
            200,
            {
                "aiRecord": {
                    "model": "gpt-4.1",
                    "aiRecordDetail": {"resultObject": "depleted-key rotated"},
                },
            },
        )

    monkeypatch.setattr(upstream, "_post_json", fake_post_json)

    with pytest.raises(upstream.ResponsesUpstreamError, match="magicx_unavailable"):
        upstream.generate_text(prompt="probe", requested_model=upstream.MAGICX_PUBLIC_MODEL)

    magix_state, magix_detail, _ = upstream._magix_health_state_snapshot()
    assert magix_state == "degraded"
    assert "auth_error" in magix_detail
    assert calls

    calls.clear()
    second = upstream.generate_text(prompt="second", requested_model=upstream.ONEMIN_PUBLIC_MODEL)
    assert second.text == "depleted-key rotated"
    assert calls == [("https://api.1min.ai/api/chat-with-ai", "unused-key")]


def test_call_onemin_uses_fourth_key_when_first_three_429(monkeypatch: pytest.MonkeyPatch) -> None:
    upstream._test_reset_onemin_key_cursor()
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "key-1")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_1", "key-2")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_2", "key-3")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_3", "key-4")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_MODELS", "gpt-4.1")

    calls: list[tuple[str, str]] = []

    def fake_post_json(*, url: str, headers: dict[str, str], payload: dict[str, object], timeout_seconds: int) -> tuple[int, dict[str, object]]:
        api_key = headers["API-KEY"]
        calls.append((url, api_key))
        if api_key in {"key-1", "key-2", "key-3"}:
            return (429, {"error": "too many requests"})
        return (
            200,
            {
                "aiRecord": {
                    "model": "gpt-4.1",
                    "aiRecordDetail": {"resultObject": "fourth-key-success"},
                },
            },
        )

    monkeypatch.setattr(upstream, "_post_json", fake_post_json)

    result = upstream.generate_text(prompt="rotating", requested_model=upstream.ONEMIN_PUBLIC_MODEL)
    assert result.text == "fourth-key-success"
    assert [item[1] for item in calls] == ["key-1", "key-2", "key-3", "key-4"]


def test_generate_text_routes_audit_lane_to_chatplayground(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BROWSERACT_API_KEY", "judge-key")
    monkeypatch.setenv("BROWSERACT_CHATPLAYGROUND_URL", "https://web.chatplayground.ai/")
    monkeypatch.setenv("EA_RESPONSES_CHATPLAYGROUND_MODELS", "judge-model")

    calls: list[tuple[str, dict[str, str], dict[str, object]]] = []

    def fake_post_json(*, url: str, headers: dict[str, str], payload: dict[str, object], timeout_seconds: int) -> tuple[int, dict[str, object]]:
        calls.append((url, headers, payload))
        return (
            200,
            {
                "consensus": "pass",
                "recommendation": "approved",
                "roles": ["factuality", "adversarial"],
                "disagreements": [],
                "risks": ["none"],
                "model_deltas": [],
            },
        )

    monkeypatch.setattr(upstream, "_post_json", fake_post_json)

    result = upstream.generate_text(
        requested_model=upstream.AUDIT_PUBLIC_MODEL,
        prompt="should run full review?",
    )

    assert result.provider_key == "chatplayground"
    assert result.provider_backend == "browseract"
    assert result.provider_account_name == "BROWSERACT_API_KEY"
    assert result.model == "judge-model"
    assert "consensus" in result.text
    assert calls[0][0] == "https://web.chatplayground.ai/api/chat/lmsys"
    assert calls[0][1]["Authorization"] == "Bearer judge-key"


def test_chatplayground_request_urls_prefers_web_with_app_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BROWSERACT_CHATPLAYGROUND_URL", "https://web.chatplayground.ai/")
    monkeypatch.delenv("EA_RESPONSES_CHATPLAYGROUND_URLS", raising=False)

    urls = upstream._chatplayground_request_urls()

    assert urls[0] == "https://web.chatplayground.ai/api/chat/lmsys"
    assert urls[1] == "https://web.chatplayground.ai/api/chat"
    assert "https://app.chatplayground.ai/api/chat/lmsys" in urls
    assert "https://app.chatplayground.ai/api/v1/chat/lmsys" in urls
    assert urls[-1] in {
        "https://app.chatplayground.ai/api/v1/chat/lmsys",
        "https://app.chatplayground.ai/",
    }
