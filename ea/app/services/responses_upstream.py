from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


DEFAULT_PUBLIC_MODEL = "ea-coder-best"
MAGICX_PUBLIC_MODEL = "ea-magicx-coder"
ONEMIN_PUBLIC_MODEL = "ea-onemin-coder"


class ResponsesUpstreamError(RuntimeError):
    pass


@dataclass(frozen=True)
class UpstreamResult:
    text: str
    provider_key: str
    model: str
    tokens_in: int = 0
    tokens_out: int = 0


@dataclass(frozen=True)
class ProviderConfig:
    provider_key: str
    display_name: str
    api_keys: tuple[str, ...]
    default_models: tuple[str, ...]
    timeout_seconds: int


def _env(name: str, default: str = "") -> str:
    return str(os.environ.get(name) or default).strip()


def _csv_values(raw: str) -> tuple[str, ...]:
    values: list[str] = []
    seen: set[str] = set()
    for item in str(raw or "").split(","):
        cleaned = item.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        values.append(cleaned)
    return tuple(values)


def _merge_unique(*groups: tuple[str, ...]) -> tuple[str, ...]:
    values: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for item in group:
            cleaned = str(item or "").strip()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            values.append(cleaned)
    return tuple(values)


def _non_empty_values(*values: str) -> tuple[str, ...]:
    items: list[str] = []
    for value in values:
        cleaned = str(value or "").strip()
        if cleaned:
            items.append(cleaned)
    return tuple(items)


def _magicx_urls() -> tuple[str, ...]:
    configured = _csv_values(_env("EA_RESPONSES_MAGICX_URLS"))
    legacy = _csv_values(_env("EA_RESPONSES_MAGICX_URL"))
    defaults = (
        "https://www.aimagicx.com/api/v1/chat/completions",
        "https://www.aimagicx.com/api/v1/chat",
        "https://beta.aimagicx.com/api/v1/chat/completions",
        "https://beta.aimagicx.com/api/v1/chat",
    )
    if configured:
        return _merge_unique(configured, legacy, defaults)
    return _merge_unique(defaults, legacy)


def _magicx_models() -> tuple[str, ...]:
    configured = _csv_values(_env("EA_RESPONSES_MAGICX_MODELS"))
    legacy = _csv_values(_env("EA_RESPONSES_MAGICX_MODEL"))
    defaults = (
        "inception/mercury-coder",
        "mistralai/codestral-2508",
        "x-ai/grok-code-fast-1",
        "openai/gpt-5.1-codex-mini",
    )
    if configured:
        return _merge_unique(configured, legacy)
    return _merge_unique(defaults, legacy)


def _magicx_max_tokens() -> int:
    raw = _env("EA_RESPONSES_MAGICX_MAX_TOKENS", "128")
    try:
        return max(16, int(raw))
    except Exception:
        return 128


def _onemin_chat_url() -> str:
    return _env(
        "EA_RESPONSES_ONEMIN_CHAT_URL",
        _env("EA_RESPONSES_ONEMIN_URL", "https://api.1min.ai/api/chat-with-ai"),
    )


def _onemin_code_url() -> str:
    return _env("EA_RESPONSES_ONEMIN_CODE_URL", "https://api.1min.ai/api/features")


def _onemin_models() -> tuple[str, ...]:
    configured = _csv_values(_env("EA_RESPONSES_ONEMIN_MODELS"))
    legacy = _csv_values(_env("EA_RESPONSES_ONEMIN_MODEL"))
    defaults = (
        "gpt-5",
        "gpt-4.1",
        "deepseek-chat",
        "gpt-4.1-nano",
    )
    if configured:
        return _merge_unique(configured, legacy)
    return _merge_unique(defaults, legacy)


def _onemin_code_models() -> tuple[str, ...]:
    configured = _csv_values(_env("EA_RESPONSES_ONEMIN_CODE_MODELS"))
    defaults = (
        "gpt-5",
        "gpt-4o",
    )
    return _merge_unique(configured, defaults)


def _onemin_model_supports_code(model: str) -> bool:
    wanted = str(model or "").strip().lower()
    return wanted in {item.lower() for item in _onemin_code_models()}


def _timeout_seconds() -> int:
    raw = _env("EA_RESPONSES_TIMEOUT_SECONDS", "180")
    try:
        return max(15, int(raw))
    except Exception:
        return 180


def _user_agent() -> str:
    return _env(
        "EA_RESPONSES_USER_AGENT",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
    )


def _normalize_provider(value: str) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "1min": "onemin",
        "1min.ai": "onemin",
        "1min_ai": "onemin",
        "ai_magicx": "magixai",
        "aimagicx": "magixai",
        "magicx": "magixai",
        "magicxai": "magixai",
        "onemin": "onemin",
    }
    return aliases.get(normalized, normalized)


def _provider_order() -> tuple[str, ...]:
    raw = _env("EA_RESPONSES_PROVIDER_ORDER", "magicxai,onemin")
    ordered: list[str] = []
    seen: set[str] = set()
    for item in raw.split(","):
        provider_key = _normalize_provider(item)
        if not provider_key or provider_key in seen:
            continue
        seen.add(provider_key)
        ordered.append(provider_key)
    return tuple(ordered or ("magixai", "onemin"))


def _magicx_config() -> ProviderConfig:
    return ProviderConfig(
        provider_key="magixai",
        display_name="AI Magicx",
        api_keys=_non_empty_values(
            _env("EA_RESPONSES_MAGICX_API_KEY"),
            _env("AI_MAGICX_API_KEY"),
        ),
        default_models=_magicx_models(),
        timeout_seconds=_timeout_seconds(),
    )


def _onemin_config() -> ProviderConfig:
    return ProviderConfig(
        provider_key="onemin",
        display_name="1min.AI",
        api_keys=_non_empty_values(
            _env("EA_RESPONSES_ONEMIN_API_KEY"),
            _env("ONEMIN_AI_API_KEY"),
            _env("ONEMIN_AI_API_KEY_FALLBACK_1"),
            _env("ONEMIN_AI_API_KEY_FALLBACK_2"),
        ),
        default_models=_onemin_models(),
        timeout_seconds=_timeout_seconds(),
    )


def _provider_configs() -> dict[str, ProviderConfig]:
    return {
        "magixai": _magicx_config(),
        "onemin": _onemin_config(),
    }


def list_response_models() -> list[dict[str, object]]:
    return [
        {
            "id": DEFAULT_PUBLIC_MODEL,
            "object": "model",
            "created": 0,
            "owned_by": "executive-assistant",
        },
        {
            "id": MAGICX_PUBLIC_MODEL,
            "object": "model",
            "created": 0,
            "owned_by": "executive-assistant",
        },
        {
            "id": ONEMIN_PUBLIC_MODEL,
            "object": "model",
            "created": 0,
            "owned_by": "executive-assistant",
        },
    ]


def _trim_error_payload(payload: Any) -> str:
    raw = str(payload)
    return raw[:400]


def _post_json(
    *,
    url: str,
    headers: dict[str, str],
    payload: dict[str, object],
    timeout_seconds: int,
) -> tuple[int, dict[str, Any] | list[Any] | str]:
    data = json.dumps(payload, ensure_ascii=True).encode("utf-8")
    request = urllib.request.Request(
        url,
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": _user_agent(),
            **headers,
        },
        data=data,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            status = int(getattr(response, "status", 200))
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        status = int(getattr(exc, "code", 500) or 500)
        raw = exc.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as exc:
        raise ResponsesUpstreamError(f"url_error:{exc.reason}") from exc
    except Exception as exc:
        raise ResponsesUpstreamError(f"request_failed:{exc}") from exc

    if not raw.strip():
        return status, {}
    try:
        payload_json = json.loads(raw)
    except Exception:
        return status, raw
    if isinstance(payload_json, (dict, list)):
        return status, payload_json
    return status, raw


def _extract_textish(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts = [_extract_textish(item) for item in value]
        return "\n".join(part for part in parts if part).strip()
    if isinstance(value, dict):
        for key in ("text", "content", "output", "result", "message", "answer"):
            text = _extract_textish(value.get(key))
            if text:
                return text
    return ""


def _extract_openai_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return _extract_textish(payload.get("response") or payload.get("text") or payload.get("message"))
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message")
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str) and item.strip():
                parts.append(item.strip())
                continue
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or "").strip()
            if text:
                parts.append(text)
        return "\n".join(parts).strip()
    return ""


def _extract_openai_usage(payload: dict[str, Any]) -> tuple[int, int]:
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return (0, 0)
    prompt_tokens = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
    completion_tokens = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
    return (prompt_tokens, completion_tokens)


def _extract_onemin_text(payload: dict[str, Any]) -> str:
    ai_record = payload.get("aiRecord")
    if not isinstance(ai_record, dict):
        return ""
    detail = ai_record.get("aiRecordDetail")
    if not isinstance(detail, dict):
        return ""
    for key in ("resultObject", "responseObject"):
        text = _extract_textish(detail.get(key))
        if text:
            return text
    return _extract_textish(detail)


def _extract_onemin_error(payload: dict[str, Any]) -> str:
    if payload.get("success") is False:
        return _trim_error_payload(payload.get("error") or payload)
    ai_record = payload.get("aiRecord")
    if not isinstance(ai_record, dict):
        return ""
    detail = ai_record.get("aiRecordDetail")
    if not isinstance(detail, dict):
        return ""
    for key in ("resultObject", "responseObject"):
        value = detail.get(key)
        if not isinstance(value, dict):
            continue
        code = str(value.get("code") or value.get("name") or "").strip()
        message = str(value.get("message") or value.get("error") or "").strip()
        if code or message:
            return ":".join(part for part in (code, message) if part)
    return ""


def _extract_onemin_model(payload: dict[str, Any]) -> str:
    ai_record = payload.get("aiRecord")
    if not isinstance(ai_record, dict):
        return ""
    direct = str(ai_record.get("model") or "").strip()
    if direct:
        return direct
    model_detail = ai_record.get("modelDetail")
    if isinstance(model_detail, dict):
        return str(model_detail.get("name") or "").strip()
    return ""


def _provider_candidates(requested_model: str) -> list[tuple[ProviderConfig, str]]:
    requested = str(requested_model or "").strip()
    configs = _provider_configs()

    def _with_order(model_override: str = "") -> list[tuple[ProviderConfig, str]]:
        candidates: list[tuple[ProviderConfig, str]] = []
        for provider_key in _provider_order():
            config = configs.get(provider_key)
            if config is None:
                continue
            model_names = (model_override,) if model_override else config.default_models
            for model_name in model_names:
                cleaned_model = str(model_name or "").strip()
                if not cleaned_model:
                    continue
                candidates.append((config, cleaned_model))
        return candidates

    if not requested or requested == DEFAULT_PUBLIC_MODEL or requested.startswith("ea-"):
        if requested == MAGICX_PUBLIC_MODEL:
            return [(configs["magixai"], model_name) for model_name in configs["magixai"].default_models]
        if requested == ONEMIN_PUBLIC_MODEL:
            return [(configs["onemin"], model_name) for model_name in configs["onemin"].default_models]
        return _with_order()

    if ":" in requested:
        provider_hint, model_name = requested.split(":", 1)
        normalized = _normalize_provider(provider_hint)
        config = configs.get(normalized)
        if config is not None:
            explicit_model = str(model_name or "").strip() or next(iter(config.default_models), "")
            return [(config, explicit_model)]

    return _with_order(requested)


def _call_magicx(config: ProviderConfig, *, prompt: str, model: str, max_output_tokens: int | None = None) -> UpstreamResult:
    errors: list[str] = []
    token_limit = int(max_output_tokens or 0) if int(max_output_tokens or 0) > 0 else _magicx_max_tokens()
    for api_key in config.api_keys:
        for url in _magicx_urls():
            status, payload = _post_json(
                url=url,
                headers={"Authorization": f"Bearer {api_key}"},
                payload={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "max_tokens": token_limit,
                },
                timeout_seconds=config.timeout_seconds,
            )
            if status < 200 or status >= 300:
                errors.append(f"http_{status}@{url}:{_trim_error_payload(payload)}")
                if status == 401 and _is_auth_error(payload):
                    break
                continue
            if not isinstance(payload, dict):
                errors.append(f"magicx_invalid_response@{url}")
                continue
            text = _extract_openai_text(payload)
            if not text:
                errors.append(f"magicx_empty_response@{url}")
                continue
            tokens_in, tokens_out = _extract_openai_usage(payload)
            resolved_model = str(payload.get("model") or model).strip() or model
            return UpstreamResult(
                text=text,
                provider_key=config.provider_key,
                model=resolved_model,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
            )
    if not errors:
        raise ResponsesUpstreamError("magicx_unavailable")
    raise ResponsesUpstreamError("; ".join(errors))


def _onemin_payload_for_mode(mode: str, *, prompt: str, model: str) -> dict[str, object]:
    if mode == "code":
        return {
            "type": "CODE_GENERATOR",
            "model": model,
            "promptObject": {"prompt": prompt},
        }
    return {
        "type": "UNIFY_CHAT_WITH_AI",
        "model": model,
        "promptObject": {"prompt": prompt},
    }


def _call_onemin(config: ProviderConfig, *, prompt: str, model: str, max_output_tokens: int | None = None) -> UpstreamResult:
    strategies: list[tuple[str, str]] = []
    if _onemin_model_supports_code(model):
        strategies.append(("code", _onemin_code_url()))
    strategies.append(("chat", _onemin_chat_url()))

    errors: list[str] = []
    for api_key in config.api_keys:
        for mode, url in strategies:
            status, payload = _post_json(
                url=url,
                headers={"API-KEY": api_key},
                payload=_onemin_payload_for_mode(mode, prompt=prompt, model=model),
                timeout_seconds=config.timeout_seconds,
            )
            if status < 200 or status >= 300:
                errors.append(f"http_{status}@{mode}:{_trim_error_payload(payload)}")
                if status == 401 and _is_auth_error(payload):
                    break
                continue
            if not isinstance(payload, dict):
                errors.append(f"onemin_invalid_response@{mode}")
                continue
            onemin_error = _extract_onemin_error(payload)
            if onemin_error:
                errors.append(f"{mode}:{onemin_error}")
                if _is_auth_error(onemin_error):
                    break
                continue
            text = _extract_onemin_text(payload)
            if not text:
                errors.append(f"onemin_empty_response@{mode}")
                continue
            resolved_model = _extract_onemin_model(payload) or model
            return UpstreamResult(
                text=text,
                provider_key=config.provider_key,
                model=resolved_model,
                tokens_in=0,
                tokens_out=0,
            )
    if not errors:
        raise ResponsesUpstreamError("onemin_unavailable")
    raise ResponsesUpstreamError("; ".join(errors))


def _is_provider_fatal_error(message: str) -> bool:
    lowered = str(message or "").lower()
    fatal_markers = (
        "missing_api_key",
        "invalid api key",
        "missing or invalid authorization header",
        "api key is not active",
    )
    recoverable_markers = (
        "insufficient_credits",
        "unsupported_model",
        "http_400",
        "http_406",
        "http_429",
        "http_500",
        "http_503",
    )
    return any(marker in lowered for marker in fatal_markers) and not any(
        marker in lowered for marker in recoverable_markers
    )


def _is_auth_error(payload: Any) -> bool:
    lowered = str(payload or "").lower()
    markers = (
        "invalid api key",
        "missing or invalid authorization header",
        "api key is not active",
    )
    return any(marker in lowered for marker in markers)


def generate_text(*, prompt: str, requested_model: str = "", max_output_tokens: int | None = None) -> UpstreamResult:
    prompt_text = str(prompt or "").strip()
    if not prompt_text:
        raise ResponsesUpstreamError("prompt_required")

    errors: list[str] = []
    blocked_providers: set[str] = set()
    for config, model_name in _provider_candidates(requested_model):
        if config.provider_key in blocked_providers:
            continue
        if not config.api_keys:
            errors.append(f"{config.provider_key}:missing_api_key")
            continue
        try:
            if config.provider_key == "magixai":
                return _call_magicx(config, prompt=prompt_text, model=model_name, max_output_tokens=max_output_tokens)
            if config.provider_key == "onemin":
                return _call_onemin(config, prompt=prompt_text, model=model_name, max_output_tokens=max_output_tokens)
            errors.append(f"{config.provider_key}:unsupported_provider")
        except ResponsesUpstreamError as exc:
            message = str(exc)
            errors.append(f"{config.provider_key}/{model_name}:{message}")
            if _is_provider_fatal_error(message):
                blocked_providers.add(config.provider_key)

    if not errors:
        raise ResponsesUpstreamError("no_upstream_responses_provider")
    raise ResponsesUpstreamError("; ".join(errors))
