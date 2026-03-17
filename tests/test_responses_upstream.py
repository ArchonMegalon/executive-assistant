from __future__ import annotations

import json
import pytest

from app.domain.models import ToolInvocationResult
from app.services import responses_upstream as upstream


def test_default_public_model_uses_easy_lane_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EA_RESPONSES_PROVIDER_ORDER", "magicxai,onemin")
    monkeypatch.setenv("EA_RESPONSES_MAGICX_MODELS", "mx-best,mx-fallback")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_REVIEW_MODELS", "review-best,review-fallback")

    candidates = [
        (config.provider_key, model)
        for config, model in upstream._provider_candidates(upstream.DEFAULT_PUBLIC_MODEL)
    ]

    assert candidates == [
        ("magixai", "mx-best"),
        ("magixai", "mx-fallback"),
        ("magixai", "x-ai/grok-code-fast-1"),
        ("magixai", "mistralai/codestral-2508"),
        ("magixai", "inception/mercury-coder"),
        ("gemini_vortex", "gemini-3-flash-preview"),
        ("onemin", "review-best"),
        ("onemin", "review-fallback"),
        ("onemin", "deepseek-chat"),
        ("onemin", "gpt-4.1-nano"),
        ("onemin", "gpt-4.1"),
    ]


def test_blank_requested_model_uses_easy_lane_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EA_RESPONSES_PROVIDER_ORDER", "onemin,magicxai")
    monkeypatch.setenv("EA_RESPONSES_MAGICX_MODELS", "mx-best")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_REVIEW_MODELS", "review-best")

    candidates = [
        (config.provider_key, model)
        for config, model in upstream._provider_candidates("")
    ]

    assert candidates == [
        ("magixai", "mx-best"),
        ("magixai", "x-ai/grok-code-fast-1"),
        ("magixai", "mistralai/codestral-2508"),
        ("magixai", "inception/mercury-coder"),
        ("gemini_vortex", "gemini-3-flash-preview"),
        ("onemin", "review-best"),
        ("onemin", "deepseek-chat"),
        ("onemin", "gpt-4.1-nano"),
        ("onemin", "gpt-4.1"),
    ]


def test_default_public_model_can_fall_back_to_onemin_when_magicx_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_MAGICX_API_KEY", "magicx-key")
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "onemin-key")
    monkeypatch.setenv("EA_RESPONSES_PROVIDER_ORDER", "onemin,magicxai")
    monkeypatch.setenv("EA_RESPONSES_MAGICX_MODELS", "mx-best")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_REVIEW_MODELS", "review-best")

    def fake_call_magicx(*args: object, **kwargs: object) -> upstream.UpstreamResult:
        raise upstream.ResponsesUpstreamError("magicx_unavailable")

    def fake_call_gemini_vortex(*args: object, **kwargs: object) -> upstream.UpstreamResult:
        raise upstream.ResponsesUpstreamError("gemini_vortex_unavailable")

    def fake_call_onemin(
        config: upstream.ProviderConfig,
        *,
        prompt: str,
        messages: list[dict[str, str]],
        model: str,
        max_output_tokens: int | None,
        lane: str,
    ) -> upstream.UpstreamResult:
        assert config.provider_key == "onemin"
        assert model == "review-best"
        assert lane == upstream._LANE_FAST
        return upstream.UpstreamResult(
            text="fallback ok",
            provider_key="onemin",
            model=model,
            tokens_in=3,
            tokens_out=2,
        )

    monkeypatch.setattr(upstream, "_call_magicx", fake_call_magicx)
    monkeypatch.setattr(upstream, "_call_gemini_vortex", fake_call_gemini_vortex)
    monkeypatch.setattr(upstream, "_call_onemin", fake_call_onemin)

    result = upstream.generate_text(prompt="fallback please", requested_model=upstream.DEFAULT_PUBLIC_MODEL)

    assert result.provider_key == "onemin"
    assert result.text == "fallback ok"


def test_fast_public_model_candidates_prefer_magicx_then_gemini_then_onemin_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EA_RESPONSES_MAGICX_MODELS", "mx-best")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_REVIEW_MODELS", "review-best")

    candidates = [
        (config.provider_key, model)
        for config, model in upstream._provider_candidates("ea-coder-fast")
    ]

    assert candidates == [
        ("magixai", "mx-best"),
        ("magixai", "x-ai/grok-code-fast-1"),
        ("magixai", "mistralai/codestral-2508"),
        ("magixai", "inception/mercury-coder"),
        ("gemini_vortex", "gemini-3-flash-preview"),
        ("onemin", "review-best"),
        ("onemin", "deepseek-chat"),
        ("onemin", "gpt-4.1-nano"),
        ("onemin", "gpt-4.1"),
    ]


def test_hard_lane_code_defaults_are_safe_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EA_RESPONSES_HARD_MAX_ACTIVE_REQUESTS", raising=False)
    monkeypatch.delenv("EA_RESPONSES_HARD_QUEUE_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("EA_RESPONSES_MAX_OUTPUT_TOKENS_HARD", raising=False)
    monkeypatch.delenv("EA_RESPONSES_ONEMIN_MAX_CREDITS_PER_HOUR", raising=False)
    monkeypatch.delenv("EA_RESPONSES_ONEMIN_MAX_CREDITS_PER_DAY", raising=False)

    assert upstream._resolve_hard_defaults() == (1, 120.0, 256)
    assert upstream._lane_max_output_tokens(upstream._LANE_HARD) == 1536
    assert upstream._onemin_max_credits_per_hour() == 80000
    assert upstream._onemin_max_credits_per_day() == 600000


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
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_4", "")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_5", "")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_6", "")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_7", "")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_8", "")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_9", "")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_10", "")
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
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_4", "")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_5", "")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_6", "")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_7", "")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_8", "")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_9", "")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_10", "")
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


def test_plain_onemin_model_routes_onemin_first_with_magicx_fallback_lane(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EA_RESPONSES_PROVIDER_ORDER", "onemin,magicxai")
    monkeypatch.setenv("EA_RESPONSES_MAGICX_MODELS", "mx-best,mx-fallback")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_MODELS", "gpt-5,gpt-4.1")

    candidates = [
        (config.provider_key, model)
        for config, model in upstream._provider_candidates("gpt-5")
    ]

    assert candidates == [
        ("onemin", "gpt-5"),
        ("magixai", "mx-best"),
        ("magixai", "mx-fallback"),
        ("magixai", "x-ai/grok-code-fast-1"),
        ("magixai", "mistralai/codestral-2508"),
        ("magixai", "inception/mercury-coder"),
    ]


def test_plain_magicx_model_skips_onemin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EA_RESPONSES_PROVIDER_ORDER", "onemin,magicxai")
    monkeypatch.setenv("EA_RESPONSES_MAGICX_MODELS", "x-ai/grok-code-fast-1")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_MODELS", "gpt-5")

    candidates = [
        (config.provider_key, model)
        for config, model in upstream._provider_candidates("x-ai/grok-code-fast-1")
    ]

    assert candidates == [("magixai", "x-ai/grok-code-fast-1")]


def test_gemini_public_model_routes_to_gemini_vortex(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EA_GEMINI_VORTEX_COMMAND", "sh")
    monkeypatch.setenv("EA_GEMINI_VORTEX_MODEL", "gemini-3-flash-preview")

    candidates = [
        (config.provider_key, model)
        for config, model in upstream._provider_candidates(upstream.GEMINI_VORTEX_PUBLIC_MODEL)
    ]

    assert candidates == [("gemini_vortex", "gemini-3-flash-preview")]


def test_call_gemini_vortex_uses_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EA_GEMINI_VORTEX_COMMAND", "sh")
    monkeypatch.setenv("EA_GEMINI_VORTEX_MODEL", "gemini-3-flash-preview")

    def fake_execute(self, request, definition):  # type: ignore[no-untyped-def]
        assert definition.tool_name == "provider.gemini_vortex.structured_generate"
        assert request.payload_json["model"] == "gemini-3-flash-preview"
        assert "say ok" in str(request.payload_json["source_text"])
        return ToolInvocationResult(
            tool_name=definition.tool_name,
            action_kind=request.action_kind,
            target_ref="gemini-vortex:test",
            output_json={
                "normalized_text": '{\n  "text": "gemini ok"\n}',
                "structured_output_json": {"text": "gemini ok"},
                "model": "gemini-3-flash-preview",
            },
            receipt_json={},
            model_name="gemini-3-flash-preview",
            tokens_in=5,
            tokens_out=3,
        )

    monkeypatch.setattr(upstream.GeminiVortexToolAdapter, "execute", fake_execute)

    result = upstream.generate_text(prompt="say ok", requested_model=upstream.GEMINI_VORTEX_PUBLIC_MODEL)

    assert result.provider_key == "gemini_vortex"
    assert result.provider_backend == "gemini_vortex_cli"
    assert result.model == "gemini-3-flash-preview"
    assert result.text == "gemini ok"
    assert result.tokens_in == 5
    assert result.tokens_out == 3


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


def test_provider_health_estimates_onemin_remaining_from_observed_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    upstream._test_reset_onemin_states()
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "observed-key")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_INCLUDED_CREDITS_PER_KEY", "100")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_BONUS_CREDITS_PER_KEY", "0")

    upstream._record_onemin_usage_event(
        api_key="observed-key",
        model="gpt-4.1",
        tokens_in=20,
        tokens_out=10,
    )

    health = upstream._provider_health_report()
    slot = health["providers"]["onemin"]["slots"][0]

    assert slot["estimated_remaining_credits"] == 70
    assert slot["estimated_credit_basis"] == "max_minus_observed_usage"
    assert slot["observed_consumed_credits"] == 30
    assert slot["observed_success_count"] == 1


def test_magicx_probe_marks_ready_when_probe_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    upstream._test_reset_onemin_states()
    monkeypatch.setenv("EA_RESPONSES_PROVIDER_ORDER", "magixai")
    monkeypatch.setenv("EA_RESPONSES_MAGICX_HEALTH_CHECK", "1")
    monkeypatch.setenv("AI_MAGICX_API_KEY", "good-key")
    monkeypatch.setenv("EA_RESPONSES_MAGICX_MODELS", "openai/gpt-5.1-codex-mini")

    def fake_post_json(*, url: str, headers: dict[str, str], payload: dict[str, object], timeout_seconds: int) -> tuple[int, dict[str, object]]:
        return (
            200,
            {
                "model": "openai/gpt-5.1-codex-mini",
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 1},
            },
        )

    monkeypatch.setattr(upstream, "_post_json", fake_post_json)

    assert upstream._magix_is_ready() is True
    state, detail, checked_at = upstream._magix_health_state_snapshot()
    assert state == "ready"
    assert detail == ""
    assert checked_at > 0


def test_magicx_probe_timeout_degrades_without_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    upstream._test_reset_onemin_states()
    monkeypatch.setenv("EA_RESPONSES_MAGICX_HEALTH_CHECK", "1")
    monkeypatch.setenv("AI_MAGICX_API_KEY", "slow-key")

    def fake_post_json(*, url: str, headers: dict[str, str], payload: dict[str, object], timeout_seconds: int) -> tuple[int, dict[str, object]]:
        raise upstream.ResponsesUpstreamError("request_failed:timeout")

    monkeypatch.setattr(upstream, "_post_json", fake_post_json)

    assert upstream._magix_is_ready() is False
    state, detail, checked_at = upstream._magix_health_state_snapshot()
    assert state == "degraded"
    assert "request_failed:timeout" in detail
    assert checked_at > 0


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


def test_deleted_onemin_key_rotates_and_hard_quarantines(monkeypatch: pytest.MonkeyPatch) -> None:
    upstream._test_reset_onemin_states()
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "deleted-key")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_1", "healthy-key")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_CHAT_URL", "https://api.1min.ai/api/chat-with-ai")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_MODELS", "gpt-4.1")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_DELETED_KEY_QUARANTINE_SECONDS", "86400")

    calls: list[str] = []

    def fake_post_json(*, url: str, headers: dict[str, str], payload: dict[str, object], timeout_seconds: int) -> tuple[int, dict[str, object]]:
        api_key = headers["API-KEY"]
        calls.append(api_key)
        if api_key == "deleted-key":
            return (401, {"errorCode": "HTTP_EXCEPTION", "message": "API Key has been deleted"})
        return (
            200,
            {
                "aiRecord": {
                    "model": "gpt-4.1",
                    "aiRecordDetail": {"resultObject": ["healthy answer"]},
                }
            },
        )

    monkeypatch.setattr(upstream, "_post_json", fake_post_json)

    result = upstream.generate_text(prompt="rotate after delete", requested_model=upstream.ONEMIN_PUBLIC_MODEL)
    assert result.text == "healthy answer"
    assert calls == ["deleted-key", "healthy-key"]

    health = upstream._provider_health_report()
    deleted_slot = next(slot for slot in health["providers"]["onemin"]["slots"] if slot["account_name"] == "ONEMIN_AI_API_KEY")
    assert deleted_slot["state"] == "deleted"
    assert deleted_slot["quarantine_until"] > deleted_slot["last_failure_at"] + 86000


def test_onemin_provider_health_reports_burn_rate_from_recent_successes(monkeypatch: pytest.MonkeyPatch) -> None:
    upstream._test_reset_onemin_states()
    monkeypatch.setenv("ONEMIN_AI_API_KEY", "primary")
    monkeypatch.setenv("ONEMIN_AI_API_KEY_FALLBACK_1", "healthy")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_BURN_WINDOW_SECONDS", "3600")
    monkeypatch.setenv("EA_RESPONSES_ONEMIN_BURN_MIN_OBSERVATION_SECONDS", "60")

    now = {"value": 1000.0}

    def fake_now() -> float:
        return float(now["value"])

    monkeypatch.setattr(upstream, "_now_epoch", fake_now)

    upstream._mark_onemin_failure(
        "primary",
        "INSUFFICIENT_CREDITS:The feature requires 30000 credits, but the Team only has 0 credits",
    )

    now["value"] = 1060.0
    upstream._record_onemin_usage_event(
        api_key="primary",
        model="gpt-5",
        tokens_in=100,
        tokens_out=50,
    )

    now["value"] = 1120.0
    upstream._record_onemin_usage_event(
        api_key="primary",
        model="gpt-5",
        tokens_in=120,
        tokens_out=55,
    )

    now["value"] = 1180.0
    health = upstream._provider_health_report()
    onemin = health["providers"]["onemin"]

    assert onemin["estimated_burn_credits_per_hour"] == 1800000.0
    assert onemin["estimated_requests_per_hour"] == 60.0
    assert onemin["estimated_hours_remaining_at_current_pace"] == 2.47
    assert onemin["burn_event_count"] == 2
    assert onemin["burn_estimate_basis"] == "recent_required_credit_median"


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


def test_chatplayground_audit_callback_only_falls_back_without_http(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BROWSERACT_API_KEY", "judge-key")
    monkeypatch.setenv("EA_RESPONSES_CHATPLAYGROUND_MODELS", "judge-model")
    monkeypatch.setenv("EA_RESPONSES_CHATPLAYGROUND_URLS", "https://web.chatplayground.ai/api/chat/lmsys")

    def fail_post_json(
        *,
        url: str,
        headers: dict[str, str],
        payload: dict[str, object],
        timeout_seconds: int,
    ) -> tuple[int, dict[str, object]]:
        raise AssertionError("http path should not be used when callback-only mode is enabled")

    monkeypatch.setattr(upstream, "_post_json", fail_post_json)

    result = upstream.generate_text(
        requested_model=upstream.AUDIT_PUBLIC_MODEL,
        prompt="should use callback",
        chatplayground_audit_callback_only=True,
    )

    payload = json.loads(result.text)
    assert result.provider_key == "chatplayground"
    assert result.provider_backend == "browseract"
    assert result.provider_key_slot == "unavailable"
    assert payload["consensus"] == "unavailable"
    assert "audit_callback_missing" in payload["risks"]


def test_chatplayground_audit_callback_errors_return_unavailable_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BROWSERACT_API_KEY", "judge-key")
    monkeypatch.setenv("EA_RESPONSES_CHATPLAYGROUND_MODELS", "judge-model")
    monkeypatch.setenv("EA_RESPONSES_CHATPLAYGROUND_URLS", "https://web.chatplayground.ai/api/chat/lmsys")

    def bad_callback(**kwargs: object) -> object:
        raise RuntimeError("tool-unavailable")

    def fail_post_json(
        *,
        url: str,
        headers: dict[str, str],
        payload: dict[str, object],
        timeout_seconds: int,
    ) -> tuple[int, dict[str, object]]:
        raise AssertionError("http path should be skipped when callback raises in audit-only mode")

    monkeypatch.setattr(upstream, "_post_json", fail_post_json)

    result = upstream.generate_text(
        requested_model=upstream.AUDIT_PUBLIC_MODEL,
        prompt="audit now",
        chatplayground_audit_callback=bad_callback,
        chatplayground_audit_callback_only=True,
    )

    payload = json.loads(result.text)
    assert result.provider_key == "chatplayground"
    assert result.provider_key_slot == "callback_error"
    assert payload["consensus"] == "unavailable"
    assert "tool-unavailable" in payload["risks"]


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
