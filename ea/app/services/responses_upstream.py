from __future__ import annotations

from collections import deque
import json
import logging
import inspect
import os
import re
import shutil
import threading
import time
import urllib.error
import urllib.request
import uuid
from urllib.parse import urlparse, urlunparse
from dataclasses import dataclass, replace
from typing import Any, Callable

from app.domain.models import ToolDefinition, ToolInvocationRequest
from app.services.tool_execution_common import ToolExecutionError
from app.services.tool_execution_gemini_vortex_adapter import GeminiVortexToolAdapter


DEFAULT_PUBLIC_MODEL = "ea-coder-best"
MAGICX_PUBLIC_MODEL = "ea-magicx-coder"
ONEMIN_PUBLIC_MODEL = "ea-onemin-coder"
SURVIVAL_PUBLIC_MODEL = "ea-coder-survival"
AUDIT_PUBLIC_MODEL = "ea-audit-jury"
AUDIT_PUBLIC_MODEL_ALIAS = "ea-audit"
GEMINI_VORTEX_PUBLIC_MODEL = "ea-gemini-flash"
ChatMessage = dict[str, str]

_LOG = logging.getLogger("ea.responses.upstream")

_ONEMIN_KEY_CONFIG_HASH = ""
_ONEMIN_KEY_CURSOR = 0
_ONEMIN_KEY_CURSOR_LOCK = threading.Lock()
_ONEMIN_KEY_STATES: dict[str, OneminKeyState] = {}
_ONEMIN_USAGE_EVENTS: deque[OneminUsageEvent] = deque(maxlen=512)
_ONEMIN_REQUIRED_CREDIT_EVENTS: deque[OneminRequiredCreditObservation] = deque(maxlen=128)
_ONEMIN_USAGE_LOCK = threading.Lock()

_HARD_CONCURRENCY_LOCK = threading.Condition(threading.Lock())
_HARD_ACTIVE_REQUESTS = 0
_HARD_WAITING_REQUESTS = 0

_MAGIX_HEALTH_STATE: dict[str, object] = {
    "state": "unknown",
    "checked_at": 0.0,
    "detail": "",
    "provider_key": "magixai",
}
_MAGIX_HEALTH_LOCK = threading.Lock()

_LANE_HARD = "hard"
_LANE_REVIEW = "review"
_LANE_FAST = "fast"
_LANE_OVERFLOW = "overflow"
_LANE_DEFAULT = "default"
_LANE_AUDIT = "audit"

_AUDIT_OUTPUT_TEXT_HEADER = "BrowserAct ChatPlayground audit"

_HARD_MAX_ACTIVE_REQUESTS = 2
_HARD_QUEUE_TIMEOUT_SECONDS = 1.0
_HARD_DOWNSCALE_MAX_OUTPUT_TOKENS = 256
_ONEMIN_AUTH_QUARANTINE_SECONDS = 1800.0
_ONEMIN_DELETED_KEY_QUARANTINE_SECONDS = 86400.0
_ONEMIN_RATE_LIMIT_COOLDOWN_SECONDS = 60.0
_ONEMIN_FAILURE_COOLDOWN_SECONDS = 20.0
_MAGIX_VERIFICATION_TIMEOUT_SECONDS = 5

_ONEMIN_MAX_REQUESTS_PER_HOUR = 0
_ONEMIN_MAX_CREDITS_PER_HOUR = 0
_ONEMIN_MAX_CREDITS_PER_DAY = 0
_DEFAULT_LANE_PROFILE = "easy"


def _resolve_default_response_lane() -> str:
    raw = _env("EA_RESPONSES_DEFAULT_PROFILE", _DEFAULT_LANE_PROFILE).strip().lower()
    if raw in {"default", "auto"}:
        raw = _DEFAULT_LANE_PROFILE
    if raw in {_LANE_FAST, _LANE_REVIEW, _LANE_HARD, _LANE_OVERFLOW, _LANE_AUDIT}:
        return raw
    if raw in {"easy"}:
        return _LANE_FAST
    if raw in {"hard", "review", "overflow", "audit"}:
        return raw
    if raw in {"cheap"}:
        return _LANE_FAST
    if raw in {"expensive", "strong", "premium"}:
        return _LANE_HARD
    return _DEFAULT_LANE_PROFILE


def _to_float(
    value: object,
    default: float,
    minimum: float = 0.0,
    maximum: float | None = None,
) -> float:
    try:
        parsed = float(str(value))
    except Exception:
        return default
    if parsed < minimum:
        return minimum
    if maximum is not None:
        parsed = min(parsed, maximum)
    return parsed


def _to_int(value: object, default: int, minimum: int = 0, maximum: int | None = None) -> int:
    try:
        parsed = int(float(str(value)))
    except Exception:
        return default
    if parsed < minimum:
        parsed = minimum
    if maximum is not None:
        parsed = min(parsed, maximum)
    return parsed


def _to_bool(value: object, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    normalized = str(value or "").strip().lower()
    if not normalized:
        return default
    if normalized in {"1", "true", "yes", "on", "y"}:
        return True
    if normalized in {"0", "false", "off", "no", "n"}:
        return False
    return default


def _normalize_text_list(raw: object) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        cleaned = raw.strip()
        if not cleaned:
            return []
        if "," not in cleaned:
            return [cleaned]
        values: list[str] = []
        for item in cleaned.split(","):
            part = str(item or "").strip()
            if part:
                values.append(part)
        return values
    if not isinstance(raw, (list, tuple, set)):
        return []
    values: list[str] = []
    for value in raw:
        cleaned = str(value or "").strip()
        if not cleaned:
            continue
        values.append(cleaned)
    return values


class ResponsesUpstreamError(RuntimeError):
    pass


@dataclass(frozen=True)
class UpstreamResult:
    text: str
    provider_key: str
    model: str
    provider_key_slot: str | None = None
    provider_backend: str | None = None
    provider_account_name: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    upstream_model: str | None = None
    latency_ms: int = 0
    fallback_reason: str | None = None
    model_call_index: int | None = None
    model_call_total: int | None = None


@dataclass(frozen=True)
class _ModelCallContext:
    model_call_index: int | None = None
    model_call_total: int | None = None
    lane: str | None = None
    route: str | None = None
    codex_profile: str | None = None
    principal_id: str | None = None
    response_id: str | None = None
    task_class: str | None = None
    escalation_reason: str | None = None


@dataclass(frozen=True)
class OneminKeyState:
    key: str
    last_used_at: float = 0.0
    last_success_at: float = 0.0
    last_failure_at: float = 0.0
    failure_count: int = 0
    cooldown_until: float = 0.0
    quarantine_until: float = 0.0
    last_error: str = ""


@dataclass(frozen=True)
class OneminUsageEvent:
    happened_at: float
    api_key: str
    model: str
    estimated_credits: int
    basis: str
    tokens_in: int = 0
    tokens_out: int = 0
    lane: str | None = None
    codex_profile: str | None = None
    route: str | None = None
    principal_id: str | None = None
    response_id: str | None = None
    task_class: str | None = None
    escalation_reason: str | None = None


@dataclass(frozen=True)
class OneminRequiredCreditObservation:
    happened_at: float
    api_key: str
    required_credits: int
    remaining_credits: int
    credit_subject: str


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


_ONEMIN_FALLBACK_ENV_RE = re.compile(r"^ONEMIN_AI_API_KEY_FALLBACK_(\d+)$")
_ONEMIN_FALLBACK_SLOT_RE = re.compile(r"^fallback_?(\d+)$")


def _onemin_fallback_slot_number(raw: object) -> int | None:
    match = _ONEMIN_FALLBACK_SLOT_RE.match(str(raw or "").strip().lower().replace(" ", "_").replace("-", "_"))
    if match is None:
        return None
    try:
        slot_number = int(match.group(1))
    except Exception:
        return None
    return slot_number if slot_number >= 1 else None


def _onemin_secret_env_names() -> tuple[str, ...]:
    fallback_numbers: set[int] = set()
    for env_name in os.environ:
        match = _ONEMIN_FALLBACK_ENV_RE.match(str(env_name or "").strip())
        if match is None:
            continue
        try:
            fallback_numbers.add(int(match.group(1)))
        except Exception:
            continue
    for slot_name in _merge_unique(
        _csv_values(_env("EA_RESPONSES_ONEMIN_ACTIVE_SLOTS")),
        _csv_values(_env("EA_RESPONSES_ONEMIN_RESERVE_SLOTS")),
    ):
        slot_number = _onemin_fallback_slot_number(slot_name)
        if slot_number is not None:
            fallback_numbers.add(slot_number)
    names = ["ONEMIN_AI_API_KEY"]
    for slot_number in sorted(fallback_numbers):
        names.append(f"ONEMIN_AI_API_KEY_FALLBACK_{slot_number}")
    return tuple(names)


def _browserplayground_url() -> str:
    return _env(
        "BROWSERACT_CHATPLAYGROUND_URL",
        "https://web.chatplayground.ai/",
    )


def _chatplayground_request_urls() -> tuple[str, ...]:
    base_url = _browserplayground_url()
    custom_urls = _csv_values(_env("EA_RESPONSES_CHATPLAYGROUND_URLS"))
    seen: set[str] = set()
    candidates: list[str] = []

    def _add_url(raw: str) -> None:
        url = str(raw or "").strip()
        if not url:
            return
        parsed = urlparse(url)
        scheme = str(parsed.scheme or "https").lower()
        netloc = parsed.netloc
        path = parsed.path or "/"
        if path != "/" and path:
            path = path.rstrip("/")
        query = parsed.query or ""
        fragment = parsed.fragment or ""
        if not netloc and "://" in url:
            return
        if not scheme:
            url = f"https://{url}"
            parsed = urlparse(url)
            scheme = "https"
            netloc = parsed.netloc
            path = parsed.path or ""
            query = parsed.query or ""
            fragment = parsed.fragment or ""
        if not netloc:
            return
        normalized = urlunparse((scheme, netloc, path, "", query, fragment))
        normalized = normalized or url
        if normalized in seen:
            return
        seen.add(normalized)
        candidates.append(normalized)

    for url in custom_urls:
        _add_url(url)

    if base_url:
        parsed = urlparse(base_url)
        if not parsed.scheme:
            parsed = urlparse(f"https://{base_url}")
        if parsed.netloc:
            parsed_path = (parsed.path or "").rstrip("/")
            netloc = parsed.netloc

            # Prefer API endpoints first; keep raw page URL as fallback.
            api_prefixes = (
                "/api/chat/lmsys",
                "/api/chat",
                "/api/chat/completions",
                "/api/v1/chat/lmsys",
                "/api/v1/chat/completions",
            )
            for suffix in api_prefixes:
                if not parsed_path or parsed_path == "/":
                    candidate_path = suffix
                elif parsed_path.startswith(suffix):
                    candidate_path = parsed_path
                else:
                    candidate_path = f"{parsed_path}{suffix}"
                _add_url(urlunparse((parsed.scheme or "https", netloc, candidate_path, "", "", "")))

            _add_url(base_url)

            if parsed.netloc.lower() == "web.chatplayground.ai":
                _add_url("https://app.chatplayground.ai/api/chat/lmsys")
                _add_url("https://app.chatplayground.ai/api/v1/chat/lmsys")
        else:
            _add_url(base_url)

    if not custom_urls and not base_url:
        _add_url("https://app.chatplayground.ai/api/chat/lmsys")
        _add_url("https://app.chatplayground.ai/api/v1/chat/lmsys")

    if not candidates:
        return ()
    return tuple(candidates)


def _browserplayground_api_keys() -> tuple[str, ...]:
    return _non_empty_values(
        _env("BROWSERACT_API_KEY"),
        _env("BROWSERACT_API_KEY_FALLBACK_1"),
        _env("BROWSERACT_API_KEY_FALLBACK_2"),
        _env("BROWSERACT_API_KEY_FALLBACK_3"),
    )


def _browserplayground_models() -> tuple[str, ...]:
    configured = _csv_values(_env("EA_RESPONSES_CHATPLAYGROUND_MODELS"))
    if configured:
        return configured
    return ("gpt-5", "gpt-4.1")


def _browserplayground_roles() -> tuple[str, ...]:
    configured = _csv_values(_env("EA_RESPONSES_CHATPLAYGROUND_ROLES"))
    if configured:
        return configured
    return ("factuality", "adversarial", "completeness", "risk")


def _browserplayground_auth_names() -> tuple[str, ...]:
    return (
        "BROWSERACT_API_KEY",
        "BROWSERACT_API_KEY_FALLBACK_1",
        "BROWSERACT_API_KEY_FALLBACK_2",
        "BROWSERACT_API_KEY_FALLBACK_3",
    )


def _provider_account_name(provider_key: str, key_names: tuple[str, ...], key: str) -> str:
    providers_env = _provider_account_names(provider_key)
    for index, candidate in enumerate(key_names):
        if candidate != key:
            continue
        if index < len(providers_env):
            return providers_env[index]
        return f"{provider_key}_slot_{index}"
    return f"{provider_key}_unknown"


def _provider_account_names(provider_key: str) -> tuple[str, ...]:
    normalized = str(provider_key or "").strip().lower()
    if normalized == "onemin":
        return _onemin_secret_env_names()
    if normalized in {"magixai", "magicxai", "aimagicx"}:
        return ("EA_RESPONSES_MAGICX_API_KEY", "AI_MAGICX_API_KEY")
    if normalized == "chatplayground":
        return _browserplayground_auth_names()
    if normalized == "gemini_vortex":
        return ("EA_GEMINI_VORTEX_COMMAND",)
    return tuple()


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
    )
    if configured:
        return _merge_unique(configured, legacy)
    return _merge_unique(defaults, legacy)


def _magicx_max_tokens() -> int:
    legacy = _env("EA_RESPONSES_MAGICX_MAX_TOKENS")
    if legacy:
        try:
            return max(16, int(legacy))
        except Exception:
            return 2048
    return 2048


def _magicx_lane_default_max_tokens(lane: str) -> int:
    lane = (lane or _LANE_DEFAULT).lower()
    defaults = {
        _LANE_FAST: _env("EA_RESPONSES_MAX_OUTPUT_TOKENS_FAST", "2048"),
        _LANE_REVIEW: _env("EA_RESPONSES_MAX_OUTPUT_TOKENS_REVIEW", "2048"),
        _LANE_HARD: _env("EA_RESPONSES_MAX_OUTPUT_TOKENS_HARD", "8192"),
        _LANE_OVERFLOW: _env("EA_RESPONSES_MAX_OUTPUT_TOKENS_OVERFLOW", "1536"),
        _LANE_DEFAULT: _env("EA_RESPONSES_MAX_OUTPUT_TOKENS_HARD", "8192"),
    }
    return _to_int(defaults.get(lane) or defaults[_LANE_DEFAULT], 2048, minimum=16)


def _magicx_max_tokens_for_lane(lane: str, requested_max_output_tokens: int | None) -> int:
    lane = (lane or _LANE_DEFAULT).lower()
    legacy_max_tokens = _magicx_max_tokens()
    base = _magicx_lane_default_max_tokens(lane)
    if requested_max_output_tokens is None and legacy_max_tokens > 0:
        requested = min(legacy_max_tokens, base)
    else:
        requested = _to_int(requested_max_output_tokens, base, minimum=16)
    return min(10000, requested, _magicx_lane_default_max_tokens(lane))


def _magicx_token_limits(lane: str, requested_max_output_tokens: int | None) -> tuple[int, ...]:
    requested = int(requested_max_output_tokens or 0)
    if requested > 0:
        requested_tokens = max(16, requested)
    else:
        requested_tokens = _magicx_max_tokens_for_lane(lane, requested_max_output_tokens)
    if requested_tokens > 10000:
        requested_tokens = 10000
    candidates = (
        requested_tokens,
        min(requested_tokens, 1536),
        min(requested_tokens, 1024),
        min(requested_tokens, 768),
        min(requested_tokens, 512),
        16,
    )
    deduped: list[int] = []
    for item in candidates:
        value = max(16, int(item))
        if value not in deduped:
            deduped.append(value)
    return tuple(deduped)


def _onemin_key_names() -> tuple[str, ...]:
    return _merge_unique(
        _non_empty_values(
            _env("EA_RESPONSES_ONEMIN_API_KEY"),
            *(_env(env_name) for env_name in _onemin_secret_env_names()),
        )
    )


def _normalize_slot_name(raw: object) -> str:
    value = str(raw or "").strip().lower().replace(" ", "_").replace("-", "_")
    if value == "0":
        value = "primary"
    if value == "1":
        value = "primary"
    if value in {"primary", "fallback", "fallback_1", "fallback_1st"}:
        return value if value == "primary" else "fallback_1"
    fallback_slot = _onemin_fallback_slot_number(value)
    if fallback_slot is not None:
        return f"fallback_{fallback_slot}"
    if value.isdigit():
        return f"fallback_{value}"
    return value


def _slot_to_key_index(slot_name: str) -> int | None:
    normalized = _normalize_slot_name(slot_name)
    if normalized == "primary":
        return 0
    match = re.fullmatch(r"fallback_(\d+)", normalized)
    if not match:
        return None
    index = int(match.group(1))
    if index < 1:
        return None
    return index


def _default_active_slots() -> tuple[int, ...]:
    return (0, 1)


def _configured_slot_names() -> tuple[str, ...]:
    configured = _normalize_text_list(_env("EA_RESPONSES_ONEMIN_ACTIVE_SLOTS"))
    if configured:
        return _merge_unique(configured)
    return tuple()


def _configured_reserve_slot_names() -> tuple[str, ...]:
    configured = _normalize_text_list(_env("EA_RESPONSES_ONEMIN_RESERVE_SLOTS"))
    if configured:
        return _merge_unique(configured)
    return tuple()


def _onemin_slot_key_names(raw_slot_names: tuple[str, ...], all_keys: tuple[str, ...], *, fallback_default: bool = False) -> tuple[str, ...]:
    keys: list[str] = []
    seen: set[str] = set()
    for raw_name in raw_slot_names:
        index = _slot_to_key_index(raw_name)
        if index is None:
            continue
        if index >= len(all_keys):
            continue
        key = all_keys[index]
        if not key:
            continue
        if key in seen:
            continue
        keys.append(key)
        seen.add(key)

    if keys:
        return tuple(keys)
    if not fallback_default:
        return tuple()

    defaults: list[str] = []
    for index in _default_active_slots():
        if index < len(all_keys):
            key = all_keys[index]
            if key and key not in seen:
                defaults.append(key)
                seen.add(key)
    return tuple(defaults)


def _onemin_active_keys() -> tuple[str, ...]:
    all_keys = _onemin_key_names()
    return _onemin_slot_key_names(_configured_slot_names(), all_keys, fallback_default=True)


def _onemin_reserve_keys() -> tuple[str, ...]:
    all_keys = _onemin_key_names()
    configured_reserve = _onemin_slot_key_names(_configured_reserve_slot_names(), all_keys, fallback_default=False)
    if configured_reserve:
        return configured_reserve
    active_keys = set(_onemin_active_keys())
    return tuple(key for key in all_keys[len(active_keys) :] if key)


def _ordered_onemin_keys() -> tuple[str, ...]:
    keys = _onemin_key_names()
    if not keys:
        return ()

    return _ordered_onemin_keys_for_keys(keys, cursor=_onemin_key_cursor(len(keys)))


def _onemin_key_cursor(key_count: int) -> int:
    if key_count <= 0:
        return 0
    with _ONEMIN_KEY_CURSOR_LOCK:
        return _ONEMIN_KEY_CURSOR % key_count


def _ordered_onemin_keys_for_keys(keys: tuple[str, ...], *, allow_reserve: bool = False, cursor: int | None = None) -> tuple[str, ...]:
    if not keys:
        return ()
    active_keys = set(_onemin_active_keys())
    reserve_keys = set(_onemin_reserve_keys()) if allow_reserve else set()

    if not active_keys and not reserve_keys:
        candidate_keys = tuple(keys)
    else:
        ordered_keys = tuple(keys) if cursor is None else _rotate_list(tuple(keys), cursor)
        if allow_reserve:
            candidate_keys = ordered_keys
        else:
            candidate_keys = tuple(key for key in ordered_keys if key in active_keys)
            if not candidate_keys and active_keys:
                candidate_keys = tuple(key for key in ordered_keys if key in active_keys.union(reserve_keys))

        if not candidate_keys:
            candidate_keys = ordered_keys

    return tuple(candidate_keys)


def _rotate_list(values: tuple[str, ...], cursor: int) -> tuple[str, ...]:
    if not values:
        return ()
    count = len(values)
    if count <= 1:
        return values
    start = cursor % count
    return values[start:] + values[:start]


def _ordered_onemin_keys_allow_reserve(allow_reserve: bool) -> tuple[str, ...]:
    keys = _onemin_key_names()
    if not keys:
        return ()
    return _ordered_onemin_keys_for_keys(keys, allow_reserve=allow_reserve, cursor=_onemin_key_cursor(len(keys)))


def _rotate_onemin_cursor_after_key_usage(api_key: str) -> None:
    global _ONEMIN_KEY_CURSOR
    keys = _onemin_key_names()
    if not keys:
        return
    try:
        index = list(keys).index(api_key)
    except ValueError:
        return
    with _ONEMIN_KEY_CURSOR_LOCK:
        if len(keys) <= 1:
            _ONEMIN_KEY_CURSOR = 0
        else:
            _ONEMIN_KEY_CURSOR = (index + 1) % len(keys)


def _is_onemin_key_depleted(message: str) -> bool:
    lowered = str(message or "").lower()
    depletion_markers = (
        "insufficient_credits",
        "credit",
        "quota",
        "too many credits",
        "no credits",
    )
    return any(marker in lowered for marker in depletion_markers)


def _parse_credit_state(message: object) -> dict[str, object] | None:
    raw = str(message or "").strip()
    if not raw:
        return None
    match = re.search(
        r"requires\s+(?P<required>\d+)\s+credits,\s+but the\s+(?P<subject>.+?)\s+only has\s+(?P<remaining>\d+)\s+credits",
        raw,
        flags=re.IGNORECASE,
    )
    if match is None:
        return None
    return {
        "required_credits": int(match.group("required")),
        "remaining_credits": int(match.group("remaining")),
        "credit_subject": str(match.group("subject") or "").strip(),
    }


def _is_retryable_onemin_error(message: str) -> bool:
    lowered = str(message or "").lower()
    retry_markers = (
        "http_429",
        "http_500",
        "http_502",
        "http_503",
        "http_504",
        "too_many_requests",
        "insufficient_credits",
        "quota",
        "rate limit",
        "requires more credits",
    )
    return any(marker in lowered for marker in retry_markers)


def _is_deleted_onemin_key_error(payload: Any) -> bool:
    lowered = str(payload or "").lower()
    markers = (
        "api key is not active",
        "api key has been deleted",
        "key has been deleted",
        "api key deleted",
        "revoked api key",
        "api key revoked",
        "deactivated api key",
        "api key disabled",
        "api key expired",
    )
    return any(marker in lowered for marker in markers)


def _clean_onemin_states(keys: tuple[str, ...]) -> None:
    key_set = set(keys)
    with _ONEMIN_KEY_CURSOR_LOCK:
        for key in list(_ONEMIN_KEY_STATES.keys()):
            if key not in key_set:
                _ONEMIN_KEY_STATES.pop(key, None)


def _pick_onemin_key(*, allow_reserve: bool = False) -> tuple[str, float, float] | None:
    key_names = _ordered_onemin_keys_allow_reserve(allow_reserve)
    if not key_names:
        return None
    _clean_onemin_states(key_names)
    states = _onemin_states_snapshot(key_names)
    now = _now_epoch()
    candidates: list[tuple[str, float, float]] = []
    blocked: list[tuple[str, float, float]] = []
    for index, api_key in enumerate(key_names):
        state = states.get(api_key) or OneminKeyState(key=api_key)
        if now < state.quarantine_until:
            blocked.append((api_key, state.quarantine_until, index))
            continue
        if now < state.cooldown_until:
            blocked.append((api_key, state.cooldown_until, index))
            continue
        candidates.append((api_key, state.last_used_at, index))
    if candidates:
        candidates.sort(key=lambda item: (item[1], item[2]))
        return candidates[0][0], 0.0, float(candidates[0][2])
    if not blocked:
        return key_names[0], 0.0, 0.0
    blocked.sort(key=lambda item: (item[1], item[2]))
    return blocked[0][0], blocked[0][1], max(0.0, blocked[0][1] - now)


def _mark_onemin_success(api_key: str) -> None:
    now = _now_epoch()
    _set_onemin_state(
        api_key,
        {
            "last_used_at": now,
            "last_success_at": now,
            "last_failure_at": 0.0,
            "failure_count": 0,
            "cooldown_until": 0.0,
            "quarantine_until": 0.0,
            "last_error": "",
        },
    )


def _mark_onemin_failure(
    api_key: str,
    message: str,
    *,
    temporary_quarantine: bool = False,
    quarantine_seconds: float | None = None,
) -> None:
    now = _now_epoch()
    rate_cooldown_seconds, failure_cooldown_seconds, auth_quarantine_seconds = _resolve_onemin_cooldowns()
    state = _onemin_states_snapshot(_onemin_key_names()).get(api_key, OneminKeyState(key=api_key))
    failure_count = int(state.failure_count or 0) + 1
    effective_quarantine_seconds = auth_quarantine_seconds if quarantine_seconds is None else max(1.0, float(quarantine_seconds))
    cooldown = now + (
        effective_quarantine_seconds if temporary_quarantine else
        (rate_cooldown_seconds if _is_onemin_key_depleted(message) else failure_cooldown_seconds)
    )
    quarantine = 0.0
    if temporary_quarantine:
        quarantine = now + effective_quarantine_seconds
    _set_onemin_state(
        api_key,
        {
            "last_used_at": now,
            "last_failure_at": now,
            "failure_count": failure_count,
            "cooldown_until": cooldown,
            "quarantine_until": quarantine,
            "last_error": str(message or ""),
        },
    )
    _record_onemin_required_credit_observation(api_key=api_key, message=message, happened_at=now)
    _rotate_onemin_cursor_after_key_usage(api_key)


def _mark_onemin_request_start(api_key: str) -> None:
    now = _now_epoch()
    _set_onemin_state(api_key, {"last_used_at": now})


def _test_reset_onemin_key_cursor() -> None:
    global _ONEMIN_KEY_CURSOR
    with _ONEMIN_KEY_CURSOR_LOCK:
        _ONEMIN_KEY_CURSOR = 0


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


def _onemin_supported_models() -> tuple[str, ...]:
    return _merge_unique(_onemin_models(), _onemin_code_models())


def _onemin_model_supports_code(model: str) -> bool:
    wanted = str(model or "").strip().lower()
    return wanted in {item.lower() for item in _onemin_code_models()}


def _magicx_lane_models() -> tuple[str, ...]:
    configured = _magicx_models()
    desired = (
        "x-ai/grok-code-fast-1",
        "mistralai/codestral-2508",
        "inception/mercury-coder",
    )
    if configured:
        return _merge_unique(configured, desired)
    return desired


def _onemin_hard_models() -> tuple[str, ...]:
    configured = _csv_values(_env("EA_RESPONSES_ONEMIN_HARD_MODELS"))
    defaults = ("gpt-5", "gpt-4o")
    if configured:
        return _merge_unique(configured, defaults)
    return defaults


def _onemin_review_models() -> tuple[str, ...]:
    configured = _csv_values(_env("EA_RESPONSES_ONEMIN_REVIEW_MODELS"))
    defaults = ("deepseek-chat", "gpt-4.1-nano", "gpt-4.1")
    if configured:
        return _merge_unique(configured, defaults)
    return defaults


def _gemini_vortex_models() -> tuple[str, ...]:
    configured = _csv_values(_env("EA_RESPONSES_GEMINI_VORTEX_MODELS"))
    default_model = _env("EA_GEMINI_VORTEX_MODEL", "gemini-3-flash-preview")
    defaults = (default_model,) if default_model else ("gemini-3-flash-preview",)
    return _merge_unique(configured, defaults)


def _onemin_max_requests_per_hour() -> int:
    return _to_int(_env("EA_RESPONSES_ONEMIN_MAX_REQUESTS_PER_HOUR", str(_ONEMIN_MAX_REQUESTS_PER_HOUR)), 0, minimum=0)


def _onemin_max_credits_per_hour() -> int:
    return _to_int(_env("EA_RESPONSES_ONEMIN_MAX_CREDITS_PER_HOUR", str(_ONEMIN_MAX_CREDITS_PER_HOUR)), 0, minimum=0)


def _onemin_max_credits_per_day() -> int:
    return _to_int(_env("EA_RESPONSES_ONEMIN_MAX_CREDITS_PER_DAY", str(_ONEMIN_MAX_CREDITS_PER_DAY)), 0, minimum=0)


def _lane_max_output_tokens(lane: str) -> int | None:
    if lane == _LANE_HARD:
        return _to_int(_env("EA_RESPONSES_MAX_OUTPUT_TOKENS_HARD", "8192"), 8192, minimum=16)
    if lane == _LANE_REVIEW:
        return _to_int(_env("EA_RESPONSES_MAX_OUTPUT_TOKENS_REVIEW", "2048"), 2048, minimum=16)
    if lane == _LANE_AUDIT:
        return _to_int(_env("EA_RESPONSES_MAX_OUTPUT_TOKENS_REVIEW", "2048"), 2048, minimum=16)
    if lane == _LANE_FAST:
        return _to_int(_env("EA_RESPONSES_MAX_OUTPUT_TOKENS_FAST", "2048"), 2048, minimum=16)
    if lane == _LANE_OVERFLOW:
        return _to_int(_env("EA_RESPONSES_MAX_OUTPUT_TOKENS_OVERFLOW", "1536"), 1536, minimum=16)
    return None


def _resolve_hard_defaults() -> tuple[float, float, int]:
    max_active = _to_int(_env("EA_RESPONSES_HARD_MAX_ACTIVE_REQUESTS", str(_HARD_MAX_ACTIVE_REQUESTS)), 1, minimum=1, maximum=8)
    queue_timeout = _to_float(
        _env("EA_RESPONSES_HARD_QUEUE_TIMEOUT_SECONDS", str(_HARD_QUEUE_TIMEOUT_SECONDS)),
        0.0,
        minimum=0.0,
        maximum=120.0,
    )
    return max_active, queue_timeout, _to_int(
        _env(
            "EA_RESPONSES_HARD_DOWNSCALE_OUTPUT_TOKENS",
            str(_HARD_DOWNSCALE_MAX_OUTPUT_TOKENS),
        ),
        256,
        minimum=16,
        maximum=4096,
    )


def _resolve_onemin_cooldowns() -> tuple[float, float, float]:
    return (
        _to_float(_env("EA_RESPONSES_ONEMIN_RATE_LIMIT_COOLDOWN_SECONDS", str(_ONEMIN_RATE_LIMIT_COOLDOWN_SECONDS)), 1.0, minimum=1.0),
        _to_float(_env("EA_RESPONSES_ONEMIN_FAILURE_COOLDOWN_SECONDS", str(_ONEMIN_FAILURE_COOLDOWN_SECONDS)), 1.0, minimum=1.0),
        _to_float(_env("EA_RESPONSES_ONEMIN_AUTH_QUARANTINE_SECONDS", str(_ONEMIN_AUTH_QUARANTINE_SECONDS)), 1.0, minimum=1.0),
    )


def _deleted_onemin_key_quarantine_seconds() -> float:
    return _to_float(
        _env(
            "EA_RESPONSES_ONEMIN_DELETED_KEY_QUARANTINE_SECONDS",
            str(_ONEMIN_DELETED_KEY_QUARANTINE_SECONDS),
        ),
        _ONEMIN_DELETED_KEY_QUARANTINE_SECONDS,
        minimum=60.0,
        maximum=2592000.0,
    )


def _onemin_included_credits_per_key() -> int:
    return _to_int(
        _env("EA_RESPONSES_ONEMIN_INCLUDED_CREDITS_PER_KEY", "4000000"),
        4000000,
        minimum=0,
        maximum=100000000,
    )


def _onemin_bonus_credits_per_key() -> int:
    return _to_int(
        _env("EA_RESPONSES_ONEMIN_BONUS_CREDITS_PER_KEY", "450000"),
        450000,
        minimum=0,
        maximum=100000000,
    )


def _onemin_max_credits_per_key() -> int:
    return _onemin_included_credits_per_key() + _onemin_bonus_credits_per_key()


def _onemin_max_credits_total(configured_slots: int) -> int:
    explicit_total = _env("EA_RESPONSES_ONEMIN_MAX_CREDITS_TOTAL")
    if explicit_total:
        return _to_int(explicit_total, max(0, configured_slots) * _onemin_max_credits_per_key(), minimum=0, maximum=1000000000)
    return max(0, configured_slots) * _onemin_max_credits_per_key()


def _estimated_onemin_remaining_credits(*, state_label: str, state: OneminKeyState) -> tuple[int | None, str]:
    credit_state = _parse_credit_state(state.last_error)
    if credit_state is not None:
        return int(credit_state["remaining_credits"]), "observed_error"
    if _is_deleted_onemin_key_error(state.last_error):
        return 0, "inactive_key"
    if _is_onemin_key_depleted(state.last_error):
        return 0, "depleted_error"
    observed_spend = _observed_onemin_spend(api_key=state.key)
    if observed_spend > 0:
        return max(0, _onemin_max_credits_per_key() - observed_spend), "max_minus_observed_usage"
    if state_label in {"ready", "cooldown"}:
        return _onemin_max_credits_per_key(), "assumed_full_unobserved"
    return 0, "unknown_unobserved"


def _record_onemin_required_credit_observation(*, api_key: str, message: str, happened_at: float | None = None) -> None:
    credit_state = _parse_credit_state(message)
    if credit_state is None:
        return
    event = OneminRequiredCreditObservation(
        happened_at=float(happened_at if happened_at is not None else _now_epoch()),
        api_key=api_key,
        required_credits=int(credit_state["required_credits"]),
        remaining_credits=int(credit_state["remaining_credits"]),
        credit_subject=str(credit_state["credit_subject"] or ""),
    )
    with _ONEMIN_USAGE_LOCK:
        _ONEMIN_REQUIRED_CREDIT_EVENTS.append(event)


def _observed_onemin_spend(*, api_key: str) -> int:
    with _ONEMIN_USAGE_LOCK:
        return sum(
            max(0, int(item.estimated_credits))
            for item in _ONEMIN_USAGE_EVENTS
            if item.api_key == api_key
        )


def _observed_onemin_request_count(*, api_key: str) -> int:
    with _ONEMIN_USAGE_LOCK:
        return sum(1 for item in _ONEMIN_USAGE_EVENTS if item.api_key == api_key)


def _recent_onemin_required_credit_observations(*, now: float, horizon_seconds: float) -> list[OneminRequiredCreditObservation]:
    with _ONEMIN_USAGE_LOCK:
        items = list(_ONEMIN_REQUIRED_CREDIT_EVENTS)
    return [item for item in items if now - item.happened_at <= horizon_seconds]


def _median_int(values: list[int]) -> int | None:
    if not values:
        return None
    ordered = sorted(int(value) for value in values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[midpoint]
    return int(round((ordered[midpoint - 1] + ordered[midpoint]) / 2))


def _estimate_onemin_request_credits(
    *,
    now: float,
    tokens_in: int,
    tokens_out: int,
) -> tuple[int, str]:
    recent_required = _recent_onemin_required_credit_observations(now=now, horizon_seconds=21600.0)
    observed_required = [item.required_credits for item in recent_required if item.required_credits > 0]
    median_required = _median_int(observed_required)
    if median_required is not None and median_required > 0:
        return int(median_required), "recent_required_credit_median"
    token_total = max(0, int(tokens_in or 0) + int(tokens_out or 0))
    if token_total > 0:
        return token_total, "token_usage_fallback"
    return 0, "unknown"


def _record_onemin_usage_event(
    *,
    api_key: str,
    model: str,
    tokens_in: int,
    tokens_out: int,
    happened_at: float | None = None,
) -> tuple[int, str]:
    now = float(happened_at if happened_at is not None else _now_epoch())
    estimated_credits, basis = _estimate_onemin_request_credits(
        now=now,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
    )
    if estimated_credits <= 0:
        return 0, basis
    event = OneminUsageEvent(
        happened_at=now,
        api_key=api_key,
        model=str(model or ""),
        estimated_credits=int(estimated_credits),
        basis=basis,
        tokens_in=int(tokens_in or 0),
        tokens_out=int(tokens_out or 0),
    )
    with _ONEMIN_USAGE_LOCK:
        _ONEMIN_USAGE_EVENTS.append(event)
    return int(estimated_credits), basis


def _onemin_burn_window_seconds() -> float:
    return _to_float(
        _env("EA_RESPONSES_ONEMIN_BURN_WINDOW_SECONDS", "3600"),
        3600.0,
        minimum=300.0,
        maximum=86400.0,
    )


def _onemin_burn_min_observation_seconds() -> float:
    return _to_float(
        _env("EA_RESPONSES_ONEMIN_BURN_MIN_OBSERVATION_SECONDS", "900"),
        900.0,
        minimum=60.0,
        maximum=14400.0,
    )


def _onemin_burn_summary(*, now: float, estimated_remaining_credits_total: int) -> dict[str, object]:
    horizon_seconds = _onemin_burn_window_seconds()
    min_observation_seconds = _onemin_burn_min_observation_seconds()
    with _ONEMIN_USAGE_LOCK:
        usage_events = [item for item in _ONEMIN_USAGE_EVENTS if now - item.happened_at <= horizon_seconds]
    if not usage_events:
        return {
            "estimated_burn_credits_per_hour": None,
            "estimated_requests_per_hour": None,
            "estimated_hours_remaining_at_current_pace": None,
            "burn_observation_window_seconds": horizon_seconds,
            "burn_observation_span_seconds": 0.0,
            "burn_event_count": 0,
            "burn_estimate_basis": "insufficient_observations",
        }

    total_credits = sum(max(0, int(item.estimated_credits)) for item in usage_events)
    earliest = min(item.happened_at for item in usage_events)
    span_seconds = max(min_observation_seconds, now - earliest)
    estimated_burn_credits_per_hour = round((total_credits * 3600.0) / span_seconds, 2) if total_credits > 0 else 0.0
    estimated_requests_per_hour = round((len(usage_events) * 3600.0) / span_seconds, 2)
    estimated_hours_remaining = None
    if estimated_burn_credits_per_hour > 0:
        estimated_hours_remaining = round(float(estimated_remaining_credits_total) / float(estimated_burn_credits_per_hour), 2)

    basis_counts: dict[str, int] = {}
    for item in usage_events:
        basis_counts[item.basis] = basis_counts.get(item.basis, 0) + 1
    basis = max(basis_counts.items(), key=lambda item: item[1])[0] if basis_counts else "unknown"
    if len(basis_counts) > 1:
        basis = ",".join(sorted(basis_counts.keys()))

    return {
        "estimated_burn_credits_per_hour": estimated_burn_credits_per_hour,
        "estimated_requests_per_hour": estimated_requests_per_hour,
        "estimated_hours_remaining_at_current_pace": estimated_hours_remaining,
        "burn_observation_window_seconds": horizon_seconds,
        "burn_observation_span_seconds": round(span_seconds, 2),
        "burn_event_count": len(usage_events),
        "burn_estimate_basis": basis,
    }


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
    raw = _env("EA_RESPONSES_PROVIDER_ORDER", "onemin,magixai")
    ordered: list[str] = []
    seen: set[str] = set()
    for item in raw.split(","):
        provider_key = _normalize_provider(item)
        if not provider_key or provider_key in seen:
            continue
        seen.add(provider_key)
        ordered.append(provider_key)
    return tuple(ordered or ("onemin", "magixai"))


def _effective_request_lane(*, requested_model: str, max_output_tokens: int | None = None) -> str:
    normalized = str(requested_model or "").strip().lower()
    if normalized == "":
        return _resolve_default_response_lane()
    if normalized in {"ea-review", "ea-critic"}:
        return _LANE_REVIEW
    if normalized == "ea-coder-hard":
        return _LANE_HARD
    if normalized in {AUDIT_PUBLIC_MODEL, AUDIT_PUBLIC_MODEL_ALIAS}:
        return _LANE_AUDIT
    if normalized == GEMINI_VORTEX_PUBLIC_MODEL or normalized in {item.lower() for item in _gemini_vortex_models()}:
        return _LANE_FAST
    if normalized == "ea-coder-fast":
        return _LANE_FAST
    if normalized == "ea-overflow":
        return _LANE_OVERFLOW
    if normalized == DEFAULT_PUBLIC_MODEL:
        return _resolve_default_response_lane()
    return _LANE_DEFAULT


def _provider_model_order_for_lane(
    provider_key: str,
    lane: str,
    requested_model: str,
) -> tuple[str, ...]:
    requested = str(requested_model or "").strip()
    normalized = requested.lower()

    if provider_key == "magixai":
        if normalized in {item.lower() for item in _magicx_lane_models()}:
            return (requested,)
        if normalized in {AUDIT_PUBLIC_MODEL, AUDIT_PUBLIC_MODEL_ALIAS, "chatplayground", "browseract"}:
            return ()
        return _magicx_lane_models()

    if provider_key == "gemini_vortex":
        if normalized in {item.lower() for item in _gemini_vortex_models()}:
            return (requested,)
        if normalized == GEMINI_VORTEX_PUBLIC_MODEL:
            return _gemini_vortex_models()
        if lane in {_LANE_FAST, _LANE_OVERFLOW}:
            return _gemini_vortex_models()
        return ()

    if provider_key == "chatplayground":
        return _browserplayground_models()

    if provider_key != "onemin":
        return ()

    requested = str(requested_model or "").strip()
    normalized = requested.lower()
    if normalized in {item.lower() for item in _onemin_supported_models()}:
        return (requested,)
    if normalized in {item.lower() for item in _magicx_lane_models()}:
        return ()
    if normalized in {AUDIT_PUBLIC_MODEL, AUDIT_PUBLIC_MODEL_ALIAS, "chatplayground", "browseract"}:
        return _onemin_review_models()
    if normalized in {"ea-review", "ea-critic"}:
        return _onemin_review_models()
    if normalized == "ea-coder-hard":
        return _onemin_hard_models()
    if lane == _LANE_HARD:
        return _onemin_hard_models()
    if lane == _LANE_REVIEW:
        return _onemin_review_models()
    if lane in {_LANE_FAST, _LANE_OVERFLOW}:
        return _onemin_review_models()
    if normalized in {ONEMIN_PUBLIC_MODEL, DEFAULT_PUBLIC_MODEL} or not normalized:
        return _onemin_models()
    return _onemin_models()


def _audit_lane_models() -> tuple[str, ...]:
    return _browserplayground_models()


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
        api_keys=_ordered_onemin_keys(),
        default_models=_onemin_models(),
        timeout_seconds=_timeout_seconds(),
    )


def _chatplayground_config() -> ProviderConfig:
    return ProviderConfig(
        provider_key="chatplayground",
        display_name="BrowserAct ChatPlayground",
        api_keys=_browserplayground_api_keys(),
        default_models=_browserplayground_models(),
        timeout_seconds=_to_int(_env("EA_RESPONSES_CHATPLAYGROUND_TIMEOUT_SECONDS", "180"), 180, minimum=1, maximum=600),
    )


def _gemini_vortex_config() -> ProviderConfig:
    command = _env("EA_GEMINI_VORTEX_COMMAND") or "gemini"
    return ProviderConfig(
        provider_key="gemini_vortex",
        display_name="Gemini Vortex",
        api_keys=(command,),
        default_models=_gemini_vortex_models(),
        timeout_seconds=_to_int(_env("EA_GEMINI_VORTEX_TIMEOUT_SECONDS", "180"), 180, minimum=15, maximum=1800),
    )


def _provider_configs() -> dict[str, ProviderConfig]:
    return {
        "magixai": _magicx_config(),
        "onemin": _onemin_config(),
        "chatplayground": _chatplayground_config(),
        "gemini_vortex": _gemini_vortex_config(),
    }


def _gemini_vortex_health_state() -> tuple[str, str]:
    command = _env("EA_GEMINI_VORTEX_COMMAND") or "gemini"
    adapter = GeminiVortexToolAdapter()
    command_base = adapter._command_base()
    binary = command_base[0] if command_base else ""
    if not binary:
        return ("missing", "gemini_vortex_command_missing")
    if os.path.sep in binary:
        ready = os.path.exists(binary) and os.access(binary, os.X_OK)
    else:
        ready = shutil.which(binary) is not None
    if ready:
        return ("ready", command)
    return ("missing", f"command_not_found:{command}")


def _acquire_hard_slot() -> bool:
    global _HARD_ACTIVE_REQUESTS
    global _HARD_WAITING_REQUESTS
    max_active, queue_timeout, _ = _resolve_hard_defaults()
    if max_active <= 1:
        return True
    deadline = _now_epoch() + queue_timeout
    with _HARD_CONCURRENCY_LOCK:
        while _HARD_ACTIVE_REQUESTS >= max_active:
            _HARD_WAITING_REQUESTS += 1
            try:
                wait = max(0.0, deadline - _now_epoch())
                if wait <= 0.0:
                    return False
                _HARD_CONCURRENCY_LOCK.wait(wait)
                if _now_epoch() >= deadline:
                    return False
            finally:
                _HARD_WAITING_REQUESTS = max(0, _HARD_WAITING_REQUESTS - 1)
        _HARD_ACTIVE_REQUESTS += 1
        return True


def _release_hard_slot() -> None:
    global _HARD_ACTIVE_REQUESTS
    with _HARD_CONCURRENCY_LOCK:
        if _HARD_ACTIVE_REQUESTS > 0:
            _HARD_ACTIVE_REQUESTS -= 1
        _HARD_CONCURRENCY_LOCK.notify_all()


def _now_epoch() -> float:
    return time.time()


def _now_ms() -> int:
    return int(time.perf_counter() * 1000.0)


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(_now_epoch()))


def _onemin_states_snapshot(keys: tuple[str, ...]) -> dict[str, OneminKeyState]:
    states: dict[str, OneminKeyState] = {}
    with _ONEMIN_KEY_CURSOR_LOCK:
        for key in keys:
            state = _ONEMIN_KEY_STATES.get(key)
            if state is None:
                state = OneminKeyState(key=key)
                _ONEMIN_KEY_STATES[key] = state
            if state.key != key:
                state = replace(state, key=key)
                _ONEMIN_KEY_STATES[key] = state
            states[key] = state
    return states


def _set_onemin_state(key: str, update: dict[str, object]) -> None:
    with _ONEMIN_KEY_CURSOR_LOCK:
        current = _ONEMIN_KEY_STATES.get(key, OneminKeyState(key=key))
        if current.key != key:
            current = replace(current, key=key)
        _ONEMIN_KEY_STATES[key] = replace(current, **update)


def _onemin_key_slot(api_key: str, *, key_names: tuple[str, ...]) -> str:
    for index, candidate in enumerate(key_names, start=1):
        if candidate == api_key:
            if index == 1:
                return "primary"
            return f"fallback_{index - 1}"
    return "unknown"


def _onemin_key_slot_from_snapshot(api_key: str, *, key_names: tuple[str, ...]) -> str:
    return _onemin_key_slot(api_key, key_names=key_names)


def _onemin_key_state_label(state: OneminKeyState, *, now: float) -> str:
    if state.last_error and _is_deleted_onemin_key_error(state.last_error):
        return "deleted"
    if now < state.quarantine_until:
        return "quarantine"
    if now < state.cooldown_until:
        return "cooldown"
    if state.last_error:
        return "degraded"
    return "ready"


def list_response_models() -> list[dict[str, object]]:
    catalog = (
        DEFAULT_PUBLIC_MODEL,
        MAGICX_PUBLIC_MODEL,
        AUDIT_PUBLIC_MODEL,
        AUDIT_PUBLIC_MODEL_ALIAS,
        ONEMIN_PUBLIC_MODEL,
        GEMINI_VORTEX_PUBLIC_MODEL,
        SURVIVAL_PUBLIC_MODEL,
        "ea-coder-hard",
        "ea-review",
        "ea-critic",
        "ea-coder-fast",
        "ea-overflow",
    )
    dynamic = _merge_unique(
        _onemin_models(),
        _onemin_code_models(),
        _magicx_lane_models(),
        _gemini_vortex_models(),
        _browserplayground_models(),
    )
    return [
        {
            "id": model_id,
            "object": "model",
            "created": 0,
            "owned_by": "executive-assistant",
        }
        for model_id in _merge_unique(catalog, dynamic)
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


def _normalize_chat_role(value: object) -> str:
    lowered = str(value or "").strip().lower()
    if lowered in {"developer", "system"}:
        return "system"
    if lowered == "assistant":
        return "assistant"
    return "user"


def _normalize_messages(*, prompt: str = "", messages: list[dict[str, str]] | None = None) -> list[ChatMessage]:
    normalized: list[ChatMessage] = []

    def _append(role: object, content: object) -> None:
        cleaned = str(content or "").strip()
        if not cleaned:
            return
        normalized_role = _normalize_chat_role(role)
        if normalized and normalized[-1]["role"] == normalized_role:
            normalized[-1]["content"] = f"{normalized[-1]['content']}\n\n{cleaned}".strip()
            return
        normalized.append({"role": normalized_role, "content": cleaned})

    for message in messages or []:
        if not isinstance(message, dict):
            continue
        _append(message.get("role"), message.get("content"))

    if not normalized:
        _append("user", prompt)
    return normalized


def _messages_to_prompt(messages: list[ChatMessage]) -> str:
    if not messages:
        return ""
    if len(messages) == 1 and messages[0]["role"] == "user":
        return messages[0]["content"]
    labels = {
        "system": "System",
        "assistant": "Assistant",
        "user": "User",
    }
    parts: list[str] = []
    for message in messages:
        label = labels.get(message["role"], "User")
        parts.append(f"{label}:\n{message['content']}")
    return "\n\n".join(parts).strip()


def _provider_candidates(
    requested_model: str,
    *,
    lane: str = _LANE_DEFAULT,
) -> list[tuple[ProviderConfig, str]]:
    requested = str(requested_model or "").strip()
    normalized = requested.lower()
    configs = _provider_configs()
    gemini_model_names = {item.lower() for item in _gemini_vortex_models()}

    if lane == _LANE_DEFAULT:
        lane = _effective_request_lane(requested_model=requested, max_output_tokens=None)

    if ":" in requested:
        provider_hint, model_name = requested.split(":", 1)
        normalized_hint = _normalize_provider(provider_hint)
        config = configs.get(normalized_hint)
        if config is None:
            return []
        explicit = str(model_name or "").strip() or next(iter(config.default_models), "")
        return [(config, explicit)] if explicit else []

    provider_keys_by_lane: tuple[str, ...]
    if lane in {_LANE_FAST, _LANE_OVERFLOW}:
        provider_keys_by_lane = _merge_unique(("magixai", "gemini_vortex"), _provider_order())
    elif lane == _LANE_AUDIT:
        provider_keys_by_lane = ("chatplayground",)
    else:
        provider_keys_by_lane = _provider_order()

    if normalized == DEFAULT_PUBLIC_MODEL or requested == "":
        # Keep the public default biased toward the cheap/fast lane, but never
        # trap it on Magicx-only when the fast lane is degraded.
        if lane in {_LANE_FAST, _LANE_OVERFLOW}:
            provider_keys_by_lane = _merge_unique(("magixai", "gemini_vortex"), _provider_order())
        candidates: list[tuple[ProviderConfig, str]] = []
        for provider_key in provider_keys_by_lane:
            config = configs.get(provider_key)
            if config is None:
                continue
            model_names = (
                _provider_model_order_for_lane(provider_key, lane, requested)
                or config.default_models
            )
            for model_name in model_names:
                candidates.append((config, model_name))
        return candidates

    if normalized == MAGICX_PUBLIC_MODEL:
        return [
            (configs["magixai"], model_name)
            for model_name in _magicx_lane_models()
        ]

    if normalized == ONEMIN_PUBLIC_MODEL:
        model_names = _provider_model_order_for_lane("onemin", lane, requested) or _onemin_models()
        return [(configs["onemin"], model_name) for model_name in model_names]

    if normalized == GEMINI_VORTEX_PUBLIC_MODEL or normalized in gemini_model_names:
        model_names = _provider_model_order_for_lane("gemini_vortex", lane, requested) or _gemini_vortex_models()
        return [(configs["gemini_vortex"], model_name) for model_name in model_names]

    if normalized in {AUDIT_PUBLIC_MODEL, AUDIT_PUBLIC_MODEL_ALIAS}:
        candidates: list[tuple[ProviderConfig, str]] = [
            (configs["chatplayground"], model_name)
            for model_name in _provider_model_order_for_lane("chatplayground", lane, requested)
            or _audit_lane_models()
        ]
        onemin_config = configs.get("onemin")
        if onemin_config and onemin_config.api_keys:
            candidates.extend(
                (
                    onemin_config,
                    model_name,
                )
                for model_name in _provider_model_order_for_lane("onemin", lane, requested)
                or _onemin_models()
            )
        return candidates

    if normalized in {"ea-review", "ea-critic"}:
        return [
            (configs["onemin"], model_name)
            for model_name in _provider_model_order_for_lane("onemin", lane, requested)
            or _onemin_review_models()
        ]

    if normalized == "ea-coder-hard":
        return [
            (configs["onemin"], model_name)
            for model_name in _provider_model_order_for_lane("onemin", lane, requested)
            or _onemin_hard_models()
        ]

    if normalized in {"ea-coder-fast", "ea-overflow"}:
        candidates: list[tuple[ProviderConfig, str]] = [
            (configs["magixai"], model_name) for model_name in _magicx_lane_models()
        ]
        candidates.extend(
            (configs["gemini_vortex"], model_name)
            for model_name in _provider_model_order_for_lane("gemini_vortex", lane, requested)
            or _gemini_vortex_models()
        )
        candidates.extend(
            (configs["onemin"], model_name)
            for model_name in _provider_model_order_for_lane("onemin", lane, requested)
            or _onemin_review_models()
        )
        return candidates

    if normalized in {"chatplayground", "browseract", AUDIT_PUBLIC_MODEL, AUDIT_PUBLIC_MODEL_ALIAS}:
        return [
            (configs["chatplayground"], model_name)
            for model_name in _provider_model_order_for_lane("chatplayground", lane, requested)
            or _audit_lane_models()
        ]

    candidates: list[tuple[ProviderConfig, str]] = []
    for provider_key in provider_keys_by_lane:
        config = configs.get(provider_key)
        if config is None:
            continue
        model_names = _provider_model_order_for_lane(provider_key, lane, requested)
        for model_name in model_names:
            candidates.append((config, model_name))
    if not candidates and requested in {MAGICX_PUBLIC_MODEL, ONEMIN_PUBLIC_MODEL}:
        candidates = [
            (configs[provider_key], requested)
            for provider_key in provider_keys_by_lane
            if provider_key in configs
        ]
    return candidates


def _magix_health_probe_interval_seconds() -> float:
    return _to_float(
        _env("EA_RESPONSES_MAGICX_HEALTH_INTERVAL_SECONDS", "300"),
        300.0,
        minimum=30.0,
        maximum=1800.0,
    )


def _magix_health_probe_enabled() -> bool:
    return _to_int(_env("EA_RESPONSES_MAGICX_HEALTH_CHECK", "0"), 0, minimum=0, maximum=1) == 1


def _magicx_model_for_probe() -> str:
    models = _magicx_lane_models()
    if models:
        return models[0]
    return "openai/gpt-5.1-codex-mini"


def _set_magix_health_state(*, state: str, detail: str) -> None:
    with _MAGIX_HEALTH_LOCK:
        _MAGIX_HEALTH_STATE.update(
            state=state,
            detail=str(detail or ""),
            checked_at=_now_epoch(),
        )


def _mark_magix_unavailable(detail: str) -> None:
    _set_magix_health_state(state="degraded", detail=detail)


def _mark_magix_ready() -> None:
    _set_magix_health_state(state="ready", detail="")


def _magix_health_state() -> tuple[str, str]:
    with _MAGIX_HEALTH_LOCK:
        return (str(_MAGIX_HEALTH_STATE.get("state") or ""), str(_MAGIX_HEALTH_STATE.get("detail") or ""))


def _magix_health_state_snapshot() -> tuple[str, str, float]:
    with _MAGIX_HEALTH_LOCK:
        return (
            str(_MAGIX_HEALTH_STATE.get("state") or ""),
            str(_MAGIX_HEALTH_STATE.get("detail") or ""),
            float(_MAGIX_HEALTH_STATE.get("checked_at") or 0.0),
        )


def _magix_is_ready() -> bool:
    if not _magicx_config().api_keys:
        _set_magix_health_state(state="missing", detail="missing_api_key")
        return False

    if not _magix_health_probe_enabled():
        return True

    state, _ = _magix_health_state()
    with _MAGIX_HEALTH_LOCK:
        checked_at = float(_MAGIX_HEALTH_STATE.get("checked_at") or 0.0)
        now = _now_epoch()
        if checked_at > 0 and state == "ready" and (now - checked_at) < _magix_health_probe_interval_seconds():
            return True
        if checked_at > 0 and state == "degraded" and (now - checked_at) < _magix_health_probe_interval_seconds():
            return False

    return _probe_magicx_health()


def _probe_magicx_health() -> bool:
    probe_payload = _trim_error_payload(_magicx_model_for_probe())
    errors: list[str] = []
    for api_key in _magicx_config().api_keys:
        for url in _magicx_urls():
            try:
                status, payload = _post_json(
                    url=url,
                    headers={"Authorization": f"Bearer {api_key}"},
                    payload={
                        "model": _magicx_model_for_probe(),
                        "messages": [{"role": "user", "content": "probe"}],
                        "stream": False,
                        "max_tokens": 16,
                    },
                    timeout_seconds=_to_int(
                        _env("EA_RESPONSES_MAGICX_HEALTH_TIMEOUT_SECONDS", str(_MAGIX_VERIFICATION_TIMEOUT_SECONDS)),
                        5,
                        minimum=1,
                        maximum=30,
                    ),
                )
            except ResponsesUpstreamError as exc:
                errors.append(f"{url}:{_trim_error_payload(exc)}")
                continue
            if status >= 200 and status < 300 and isinstance(payload, dict):
                _mark_magix_ready()
                return True
            if _is_auth_error(payload):
                _mark_magix_unavailable(f"auth_error:{_trim_error_payload(payload)}")
                return False
            if status >= 500:
                errors.append(f"{url}:http_{status}:{_trim_error_payload(payload)}")
                continue
            errors.append(f"{url}:http_{status}:{_trim_error_payload(payload)}")
    _mark_magix_unavailable(f"probe_failed:{'; '.join(errors) or probe_payload}")
    return False


def _call_magicx(
    config: ProviderConfig,
    *,
    prompt: str,
    messages: list[ChatMessage] | None = None,
    model: str,
    max_output_tokens: int | None = None,
    lane: str = _LANE_DEFAULT,
) -> UpstreamResult:
    if not _magix_is_ready():
        raise ResponsesUpstreamError("magicx_unavailable")

    key_names = tuple(config.api_keys)
    if not key_names:
        raise ResponsesUpstreamError("magicx_missing_api_key")

    urls = _magicx_urls()
    if not urls:
        raise ResponsesUpstreamError("magicx_no_url")

    errors: list[str] = []
    failures: list[str] = []
    normalized_messages = _normalize_messages(prompt=prompt, messages=messages)
    if not normalized_messages:
        raise ResponsesUpstreamError("magicx_prompt_required")
    for index, api_key in enumerate(key_names, start=1):
        if not api_key:
            continue
        key_slot = _onemin_key_slot(api_key, key_names=key_names)
        account_name = _provider_account_name("magixai", key_names=key_names, key=api_key)
        for url in urls:
            for token_limit in _magicx_token_limits(lane, max_output_tokens):
                started_at = _now_ms()
                status, payload = _post_json(
                    url=url,
                    headers={"Authorization": f"Bearer {api_key}"},
                    payload={
                        "model": model,
                        "messages": normalized_messages,
                        "stream": False,
                        "max_tokens": token_limit,
                    },
                    timeout_seconds=config.timeout_seconds,
                )
                latency_ms = _now_ms() - started_at
                if status < 200 or status >= 300:
                    detail = _trim_error_payload(payload)
                    candidate_error = f"{key_slot}:{index}@{url}:http_{status}:{detail}"
                    errors.append(candidate_error)
                    if _is_auth_error(payload):
                        failures.append(candidate_error)
                        _mark_magix_unavailable(f"auth_error:{detail}")
                        _log_provider_selection(
                            provider="magixai",
                            event="auth_error",
                            key_slot=key_slot,
                            model=model,
                            latency_ms=latency_ms,
                            reason=detail,
                        )
                        break
                    if _requires_smaller_max_tokens(payload):
                        failures.append(candidate_error)
                        continue
                    break
                if not isinstance(payload, dict):
                    candidate_error = f"{key_slot}:{index}@{url}:invalid_payload"
                    errors.append(candidate_error)
                    failures.append(candidate_error)
                    continue
                text = _extract_openai_text(payload)
                if not text:
                    candidate_error = f"{key_slot}:{index}@{url}:empty_text"
                    errors.append(candidate_error)
                    failures.append(candidate_error)
                    continue
                tokens_in, tokens_out = _extract_openai_usage(payload)
                resolved_model = str(payload.get("model") or model).strip() or model
                _mark_magix_ready()
                fallback_reason = "; ".join(
                    {str(item) for item in failures}
                )
                _log_provider_selection(
                    provider="magixai",
                    event="success",
                    key_slot=key_slot,
                    model=resolved_model,
                    latency_ms=latency_ms,
                    reason=fallback_reason or None,
                )
                return UpstreamResult(
                    text=text,
                    provider_key=config.provider_key,
                    model=resolved_model,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    provider_key_slot=key_slot,
                    provider_backend="aimagicx",
                    provider_account_name=account_name,
                    upstream_model=model,
                    latency_ms=max(0, latency_ms),
                    fallback_reason=fallback_reason or None,
                )
    if not errors:
        raise ResponsesUpstreamError("magicx_unavailable")
    _mark_magix_unavailable("; ".join(errors))
    _log_provider_selection(
        provider="magixai",
        event="failure",
        key_slot="unavailable",
        model=model,
        latency_ms=0,
        reason="; ".join(errors),
    )
    raise ResponsesUpstreamError("; ".join(errors))


def _chatplayground_roles(normalized_roles: object) -> list[str]:
    roles = _normalize_text_list(normalized_roles)
    if not roles:
        return list(_browserplayground_roles())
    return [role.strip().lower() for role in roles if role.strip()]


def _normalize_chatplayground_audit_payload(payload: dict[str, Any] | None) -> tuple[str, str, list[str], list[str], list[str], list[str], dict[str, object]]:
    root = dict(payload or {})
    body = root.get("data") if isinstance(root.get("data"), dict) else root
    if not isinstance(body, dict):
        body = {}
    normalized = dict(body)
    consensus = str(
        normalized.get("consensus")
        or normalized.get("recommendation")
        or normalized.get("summary")
        or ""
    ).strip()
    recommendation = str(normalized.get("recommendation") or consensus or "").strip()
    disagreements = [str(item) for item in _normalize_text_list(normalized.get("disagreements")) if str(item).strip()]
    risks = [str(item) for item in _normalize_text_list(normalized.get("risks")) if str(item).strip()]
    model_deltas = [str(item) for item in _normalize_text_list(normalized.get("model_deltas")) if str(item).strip()]
    instruction_trace = [str(item) for item in _normalize_text_list(normalized.get("instruction_trace")) if str(item).strip()]
    roles = _chatplayground_roles(normalized.get("roles"))
    return (
        consensus,
        recommendation,
        roles,
        disagreements,
        risks,
        model_deltas,
        {
            "consensus": consensus,
            "recommendation": recommendation,
            "disagreements": disagreements,
            "risks": risks,
            "model_deltas": model_deltas,
            "instruction_trace": instruction_trace,
            "roles": roles,
            "audit_scope": str(normalized.get("audit_scope") or "jury").strip() or "jury",
            "requested_models": _normalize_text_list(normalized.get("requested_models")),
            "requested_at": str(normalized.get("requested_at") or "").strip() or _now_iso(),
            "raw_response": root,
            "parsed_at": _now_iso(),
        },
    )


def _normalize_chatplayground_audit_callback_payload(payload: Any) -> dict[str, Any] | None:
    if isinstance(payload, dict):
        return dict(payload)
    if payload is None:
        return None
    if isinstance(payload, str):
        text = payload.strip()
        if not text:
            return None
        return {
            "raw_response_text": text,
            "recommendation": text,
            "consensus": text,
            "roles": [],
            "disagreements": [],
            "risks": [],
            "model_deltas": [],
            "raw_output_json": payload,
        }
    payload_json = getattr(payload, "output_json", None)
    if isinstance(payload_json, dict):
        if not payload_json:
            payload_json = {}
        normalized = dict(payload_json)
        if "structured_output_json" in payload_json and isinstance(payload_json.get("structured_output_json"), dict):
            normalized = dict(payload_json.get("structured_output_json"))
        structured_output_json = getattr(payload, "structured_output_json", None)
        if isinstance(structured_output_json, dict):
            structured = dict(structured_output_json)
            structured.update(normalized)
            normalized = structured
        return normalized
    payload_output = getattr(payload, "output", None)
    if isinstance(payload_output, dict):
        return dict(payload_output)
    return None


def _chatplayground_audit_disabled_payload(
    *,
    prompt: str,
    model: str,
    roles: list[str],
    audit_scope: str,
    requested_models: tuple[str, ...],
    reason: str,
) -> dict[str, object]:
    return {
        "provider": "chatplayground",
        "scope": audit_scope,
        "roles": roles,
        "requested_roles": roles,
        "model": model,
        "consensus": "unavailable",
        "recommendation": "audit unavailable in this environment",
        "disagreements": [],
        "risks": ["chatplayground_unavailable", reason],
        "model_deltas": [],
        "requested_models": list(requested_models),
        "requested_at": _now_iso(),
        "raw_output": {"prompt": prompt, "reason": reason},
    }


def _chatplayground_audit_disabled_result(
    *,
    config: ProviderConfig,
    prompt: str,
    model: str,
    roles: list[str],
    audit_scope: str,
    requested_models: tuple[str, ...],
    reason: str,
    key_slot: str = "unavailable",
) -> UpstreamResult:
    account_name = _provider_account_name("chatplayground", key_names=tuple(config.api_keys), key="")
    payload = _chatplayground_audit_disabled_payload(
        prompt=prompt,
        model=model,
        roles=roles,
        audit_scope=audit_scope,
        requested_models=requested_models,
        reason=reason,
    )
    output_text = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    return UpstreamResult(
        text=output_text,
        provider_key=config.provider_key,
        model=model,
        tokens_in=0,
        tokens_out=0,
        provider_key_slot=key_slot,
        provider_backend="browseract",
        provider_account_name=account_name,
        upstream_model=model,
        latency_ms=0,
        fallback_reason=reason,
    )


def _chatplayground_audit_callback_candidates(
    *,
    callback: Callable[..., Any],
    prompt: str,
    roles: list[str],
    model: str,
    audit_scope: str,
    run_url: str,
    principal_id: str,
    requested_models: tuple[str, ...],
) -> list[dict[str, Any]]:
    request_payload = {
        "prompt": prompt,
        "roles": roles,
        "requested_roles": roles,
        "audit_scope": audit_scope,
        "model": model,
        "run_url": run_url,
        "requested_models": list(requested_models),
        "principal_id": principal_id,
    }
    candidates = [
        {"prompt": prompt, "roles": roles, "audit_scope": audit_scope, "model": model, "requested_models": list(requested_models), "run_url": run_url, "principal_id": principal_id},
        {"request_payload": request_payload},
        {"payload": request_payload},
        {"run_url": run_url, "request_payload": request_payload},
        {"run_url": run_url, "prompt": prompt, "roles": roles},
        {"prompt": prompt, "roles": roles, "requested_roles": roles, "model": model, "audit_scope": audit_scope, "run_url": run_url},
        {"run_url": run_url, "scope": audit_scope, "prompt": prompt, "roles": roles},
        {},
    ]

    try:
        signatures = inspect.signature(callback)
    except Exception:
        signatures = tuple()
    else:
        accepts_var_kw = any(
            getattr(parameter, "kind", None) == inspect.Parameter.VAR_KEYWORD
            for parameter in signatures.parameters.values()
        )
        if accepts_var_kw:
            return candidates
        allowed = set(signatures.parameters.keys())
        normalized: list[dict[str, Any]] = []
        for candidate in candidates:
            normalized_candidate = {
                key: value for key, value in candidate.items() if key in allowed
            }
            if normalized_candidate:
                normalized.append(normalized_candidate)
        return normalized
    return candidates


def _chatplayground_audit_text_payload(
    *,
    prompt: str,
    roles: list[str],
    model: str,
    audit_scope: str,
    requested_models: tuple[str, ...],
) -> dict[str, object]:
    requested_models_payload = [model]
    if model:
        requested_models_payload = [model]
    elif requested_models:
        requested_models_payload = list(requested_models)
    return {
        "prompt": prompt,
        "roles": roles,
        "audit_scope": audit_scope,
        "requested_models": requested_models_payload,
        "requested_at": _now_iso(),
    }


def _call_chatplayground_audit(
    config: ProviderConfig,
    *,
    prompt: str,
    messages: list[ChatMessage] | None = None,
    model: str,
    max_output_tokens: int | None = None,
    lane: str = _LANE_DEFAULT,
    chatplayground_audit_callback: Callable[..., Any] | None = None,
    chatplayground_audit_callback_only: bool = False,
    chatplayground_audit_principal_id: str = "",
) -> UpstreamResult:
    normalized_messages = _normalize_messages(prompt=prompt, messages=messages)
    prompt_text = _messages_to_prompt(normalized_messages)
    if not prompt_text:
        raise ResponsesUpstreamError("chatplayground_prompt_required")

    key_names = tuple(config.api_keys)
    run_url_candidates = _chatplayground_request_urls()

    model_candidates = tuple(config.default_models) or _browserplayground_models()
    if not model_candidates:
        model_candidates = _browserplayground_models()

    audit_scope = "jury"
    base_roles = list(_browserplayground_roles())
    if chatplayground_audit_callback_only and chatplayground_audit_callback is None:
        _log_provider_selection(
            provider="chatplayground",
            event="callback_unavailable",
            key_slot="unavailable",
            model=model_candidates[0] if model_candidates else model,
            latency_ms=0,
            reason="audit_callback_missing",
        )
        return _chatplayground_audit_disabled_result(
            config=config,
            prompt=prompt_text,
            model=model_candidates[0] if model_candidates else model,
            roles=base_roles,
            audit_scope=audit_scope,
            requested_models=tuple(config.default_models),
            reason="audit_callback_missing",
            key_slot="unavailable",
        )

    if not chatplayground_audit_callback_only and not key_names:
        raise ResponsesUpstreamError("chatplayground_missing_api_key")

    if not run_url_candidates and not (chatplayground_audit_callback_only and chatplayground_audit_callback is not None):
        raise ResponsesUpstreamError("chatplayground_run_url_missing")

    errors: list[str] = []
    tested: set[str] = set()
    for model_name in model_candidates:
        if chatplayground_audit_callback is not None:
            for candidate in _chatplayground_audit_callback_candidates(
                callback=chatplayground_audit_callback,
                prompt=prompt_text,
                roles=base_roles,
                model=model_name,
                audit_scope=audit_scope,
                run_url=run_url_candidates[0] if run_url_candidates else "",
                principal_id=chatplayground_audit_principal_id,
                requested_models=tuple(config.default_models),
            ):
                callback_started_at = _now_ms()
                try:
                    callback_response = chatplayground_audit_callback(**candidate)
                except TypeError:
                    continue
                except Exception as exc:
                    _log_provider_selection(
                        provider="chatplayground",
                        event="callback_error",
                        key_slot="callback",
                        model=model_name,
                        latency_ms=0,
                        reason=str(exc),
                    )
                    if not chatplayground_audit_callback_only:
                        continue
                    return _chatplayground_audit_disabled_result(
                        config=config,
                        prompt=prompt_text,
                        model=model_name,
                        roles=base_roles,
                        audit_scope=audit_scope,
                        requested_models=tuple(config.default_models),
                        reason=str(exc),
                        key_slot="callback_error",
                    )

                callback_payload = _normalize_chatplayground_audit_callback_payload(callback_response)
                if not callback_payload:
                    continue

                binding_id = str(callback_payload.get("binding_id") or "").strip()
                external_account_ref = str(callback_payload.get("external_account_ref") or "").strip()
                callback_key_name = str(callback_payload.get("chatplayground_key") or "").strip()
                if not callback_key_name and binding_id:
                    callback_key_name = binding_id

                (
                    consensus,
                    recommendation,
                    roles,
                    disagreements,
                    risks,
                    model_deltas,
                    details,
                ) = _normalize_chatplayground_audit_payload(callback_payload)
                if not consensus and not recommendation:
                    if chatplayground_audit_callback_only:
                        return _chatplayground_audit_disabled_result(
                            config=config,
                            prompt=prompt_text,
                            model=model_name,
                            roles=base_roles,
                            audit_scope=audit_scope,
                            requested_models=tuple(config.default_models),
                            reason="chatplayground_callback_no_result",
                            key_slot="callback_empty",
                        )
                    continue
                callback_latency = _now_ms() - callback_started_at
                account_name = external_account_ref
                key_slot = "callback"
                if binding_id:
                    key_slot = f"binding_{binding_id}"
                if not account_name and callback_key_name:
                    if key_names:
                        key_slot = callback_key_name if callback_key_name in key_names else "callback"
                    account_name = _provider_account_name("chatplayground", key_names=key_names, key=callback_key_name)
                elif not account_name:
                    account_name = _provider_account_name("chatplayground", key_names=key_names, key="")
                _log_provider_selection(
                    provider="chatplayground",
                    event="callback_success",
                    key_slot=key_slot,
                    model=model_name,
                    latency_ms=max(0, callback_latency),
                    reason=None,
                )
                text_payload = {
                    "provider": "chatplayground",
                    "scope": audit_scope,
                    "roles": roles,
                    "model": model_name,
                    "consensus": consensus,
                    "recommendation": recommendation,
                    "disagreements": disagreements,
                    "risks": risks,
                    "model_deltas": model_deltas,
                    "binding_id": binding_id,
                    "external_account_ref": external_account_ref,
                    "requested_at": details.get("requested_at"),
                    "callback_payload": callback_payload,
                    "raw_output": details,
                }
                output_text = json.dumps(text_payload, ensure_ascii=True, separators=(",", ":"))
                return UpstreamResult(
                    text=output_text,
                    provider_key=config.provider_key,
                    model=model_name,
                    tokens_in=0,
                    tokens_out=0,
                    provider_key_slot=key_slot,
                    provider_backend="browseract",
                    provider_account_name=account_name,
                    upstream_model=model,
                    latency_ms=max(0, callback_latency),
                    fallback_reason=f"callback_success:{_format_error_payload(details)}",
                )
        if chatplayground_audit_callback_only:
            return _chatplayground_audit_disabled_result(
                config=config,
                prompt=prompt_text,
                model=model_name,
                roles=base_roles,
                audit_scope=audit_scope,
                requested_models=tuple(config.default_models),
                reason="chatplayground_callback_unavailable",
                key_slot="callback_missing",
            )

        for api_key in key_names:
            if not api_key or api_key in tested:
                continue
            tested.add(api_key)
            key_slot = _onemin_key_slot(api_key, key_names=key_names)
            account_name = _provider_account_name("chatplayground", key_names=key_names, key=api_key)
            payload = _chatplayground_audit_text_payload(
                prompt=prompt_text,
                roles=base_roles,
                model=model_name,
                audit_scope=audit_scope,
                requested_models=tuple(config.default_models),
            )
            for run_url in run_url_candidates:
                endpoint_reason_prefix = f"{account_name}:{key_slot}:{audit_scope}:{run_url}:"
                started_at = _now_ms()
                status, api_response = _post_json(
                    url=run_url,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    payload=payload,
                    timeout_seconds=config.timeout_seconds,
                )
                latency_ms = _now_ms() - started_at
                if status < 200 or status >= 300:
                    detail = _trim_error_payload(api_response)
                    failures = f"{endpoint_reason_prefix}http_{status}:{detail}"
                    errors.append(failures)
                    _log_provider_selection(
                        provider="chatplayground",
                        event="failure",
                        key_slot=key_slot,
                        model=model_name,
                        latency_ms=latency_ms,
                        reason=failures,
                    )
                    if status in {401, 403}:
                        continue
                    if status in {405, 408, 429, 500, 502, 503, 504}:
                        continue
                    if status >= 500:
                        continue
                    break

                if not isinstance(api_response, dict):
                    errors.append(f"{account_name}:{key_slot}:{audit_scope}:invalid_payload")
                    _log_provider_selection(
                        provider="chatplayground",
                        event="invalid_payload",
                        key_slot=key_slot,
                        model=model_name,
                        latency_ms=latency_ms,
                        reason="invalid_payload",
                    )
                    continue

                (
                    consensus,
                    recommendation,
                    roles,
                    disagreements,
                    risks,
                    model_deltas,
                    details,
                ) = _normalize_chatplayground_audit_payload(api_response)
                if not consensus and not recommendation:
                    errors.append(f"{account_name}:{key_slot}:{audit_scope}:empty_audit")
                    continue

                text_payload = {
                    "provider": "chatplayground",
                    "scope": audit_scope,
                    "roles": roles,
                    "model": model_name,
                    "consensus": consensus,
                    "recommendation": recommendation,
                    "disagreements": disagreements,
                    "risks": risks,
                    "model_deltas": model_deltas,
                    "requested_at": details.get("requested_at"),
                }
                output_text = json.dumps(text_payload, ensure_ascii=True, separators=(",", ":"))
                _log_provider_selection(
                    provider="chatplayground",
                    event="success",
                    key_slot=key_slot,
                    model=model_name,
                    latency_ms=latency_ms,
                    reason=None,
                )
                return UpstreamResult(
                    text=output_text,
                    provider_key=config.provider_key,
                    model=model_name,
                    tokens_in=0,
                    tokens_out=0,
                    provider_key_slot=key_slot,
                    provider_backend="browseract",
                    provider_account_name=account_name,
                    upstream_model=model,
                    latency_ms=max(0, latency_ms),
                )
    if not errors:
        raise ResponsesUpstreamError("chatplayground_unavailable")
    _log_provider_selection(
        provider="chatplayground",
        event="failure",
        key_slot="unavailable",
        model=model,
        latency_ms=0,
        reason="; ".join(errors),
    )
    raise ResponsesUpstreamError("; ".join(errors))


def _call_gemini_vortex(
    config: ProviderConfig,
    *,
    prompt: str,
    messages: list[ChatMessage] | None = None,
    model: str,
    max_output_tokens: int | None = None,
    lane: str = _LANE_DEFAULT,
) -> UpstreamResult:
    normalized_messages = _normalize_messages(prompt=prompt, messages=messages)
    prompt_text = _messages_to_prompt(normalized_messages)
    if not prompt_text:
        raise ResponsesUpstreamError("gemini_vortex:prompt_required")
    adapter = GeminiVortexToolAdapter()
    definition = ToolDefinition(
        tool_name="provider.gemini_vortex.structured_generate",
        version="builtin",
        input_schema_json={},
        output_schema_json={},
        policy_json={},
        allowed_channels=("commentary",),
        approval_default="never",
        enabled=True,
        updated_at=_now_iso(),
    )
    request = ToolInvocationRequest(
        session_id=f"responses:{uuid.uuid4().hex}",
        step_id=f"responses-step:{uuid.uuid4().hex}",
        tool_name=definition.tool_name,
        action_kind="content.generate",
        payload_json={
            "source_text": prompt_text,
            "generation_instruction": (
                "Answer the user's request. Return JSON with a single top-level `text` field only."
            ),
            "response_schema_json": {
                "type": "object",
                "required": ["text"],
                "properties": {"text": {"type": "string"}},
            },
            "model": model,
            "lane": lane,
            "max_output_tokens": max_output_tokens,
        },
    )
    started_at = _now_ms()
    try:
        result = adapter.execute(request, definition)
    except ToolExecutionError as exc:
        detail = str(exc).strip() or "gemini_vortex_failed"
        _log_provider_selection(
            provider="gemini_vortex",
            event="failure",
            key_slot="primary",
            model=model,
            latency_ms=max(0, _now_ms() - started_at),
            reason=detail,
        )
        raise ResponsesUpstreamError(f"gemini_vortex:{detail}") from exc
    output_json = dict(result.output_json or {})
    structured = output_json.get("structured_output_json")
    text = str(((structured or {}).get("text") if isinstance(structured, dict) else "") or "").strip()
    if not text:
        text = str(output_json.get("normalized_text") or "").strip()
    if not text:
        raise ResponsesUpstreamError("gemini_vortex:empty_text")
    account_key = config.api_keys[0] if config.api_keys else ""
    account_name = _provider_account_name("gemini_vortex", key_names=tuple(config.api_keys), key=account_key)
    latency_ms = max(0, _now_ms() - started_at)
    _log_provider_selection(
        provider="gemini_vortex",
        event="success",
        key_slot="primary",
        model=str(result.model_name or model or "").strip() or model,
        latency_ms=latency_ms,
        reason=None,
    )
    return UpstreamResult(
        text=text,
        provider_key="gemini_vortex",
        model=str(result.model_name or output_json.get("model") or model or "gemini").strip() or "gemini",
        tokens_in=int(result.tokens_in or 0),
        tokens_out=int(result.tokens_out or 0),
        provider_key_slot="primary",
        provider_backend="gemini_vortex_cli",
        provider_account_name=account_name,
        upstream_model=str(output_json.get("model") or model or "").strip() or model,
        latency_ms=latency_ms,
    )


def _call_onemin(
    config: ProviderConfig,
    *,
    prompt: str,
    messages: list[ChatMessage] | None = None,
    model: str,
    max_output_tokens: int | None = None,
    lane: str = _LANE_DEFAULT,
) -> UpstreamResult:
    normalized_messages = _normalize_messages(prompt=prompt, messages=messages)
    prompt_text = _messages_to_prompt(normalized_messages)
    if not prompt_text:
        raise ResponsesUpstreamError("onemin_prompt_required")

    key_names = tuple(config.api_keys)
    if not key_names:
        raise ResponsesUpstreamError("onemin_missing_api_key")

    urls = [
        (_onemin_code_url(), "code"),
        (_onemin_chat_url(), "chat"),
    ]
    if not _onemin_model_supports_code(model):
        urls = [
            (url, "chat")
            for url, mode in urls
            if mode == "chat" and url == _onemin_chat_url()
        ]

    errors: list[str] = []
    failures: list[str] = []
    tested: set[str] = set()
    active_key_names = _ordered_onemin_keys_allow_reserve(False)
    all_key_names = _ordered_onemin_keys_allow_reserve(True)
    allow_reserve = False
    while len(tested) < len(all_key_names):
        key_pick = _pick_onemin_key(allow_reserve=allow_reserve)
        if key_pick is None:
            if not allow_reserve and len(all_key_names) > len(active_key_names):
                allow_reserve = True
                continue
            break
        api_key, wait_until, _ = key_pick
        if api_key in tested:
            if (
                not allow_reserve
                and len(all_key_names) > len(active_key_names)
                and all(key in tested for key in active_key_names)
            ):
                allow_reserve = True
            _rotate_onemin_cursor_after_key_usage(api_key)
            continue
        tested.add(api_key)

        if wait_until > 0:
            failures.append(f"{api_key}:cooldown_until_{int(wait_until)}")
            _rotate_onemin_cursor_after_key_usage(api_key)
            continue

        _mark_onemin_request_start(api_key)
        key_slot = _onemin_key_slot(api_key, key_names=key_names)
        account_name = _provider_account_name("onemin", key_names=key_names, key=api_key)
        key_fallback_reason: list[str] = []
        key_depleted = False
        key_auth_failed = False

        for index, (url, mode) in enumerate(urls):
            started_at = _now_ms()
            status, payload = _post_json(
                url=url,
                headers={"API-KEY": api_key},
                payload=_onemin_payload_for_mode(mode, prompt=prompt_text, model=model),
                timeout_seconds=config.timeout_seconds,
            )
            latency_ms = _now_ms() - started_at
            if status < 200 or status >= 300:
                error_detail = _trim_error_payload(payload)
                reason = f"{key_slot}:{mode}:http_{status}:{error_detail}"
                errors.append(reason)
                key_fallback_reason.append(reason)
                if _is_auth_error(error_detail):
                    key_auth_failed = True
                    quarantine_seconds = (
                        _deleted_onemin_key_quarantine_seconds()
                        if _is_deleted_onemin_key_error(error_detail)
                        else None
                    )
                    _mark_onemin_failure(
                        api_key,
                        error_detail,
                        temporary_quarantine=True,
                        quarantine_seconds=quarantine_seconds,
                    )
                    break
                if _is_retryable_onemin_error(error_detail):
                    _mark_onemin_failure(api_key, error_detail, temporary_quarantine=False)
                    if _is_onemin_key_depleted(error_detail):
                        key_depleted = True
                    if mode == "code" and index == 0:
                        continue
                    break
                _mark_onemin_failure(api_key, error_detail, temporary_quarantine=False)
                break

            if not isinstance(payload, dict):
                reason = f"{key_slot}:{mode}:invalid_payload"
                errors.append(reason)
                key_fallback_reason.append(reason)
                _mark_onemin_failure(api_key, reason)
                break

            onemin_error = _extract_onemin_error(payload)
            if onemin_error:
                reason = f"{key_slot}:{mode}:{onemin_error}"
                errors.append(reason)
                key_fallback_reason.append(reason)
                if _is_auth_error(onemin_error):
                    key_auth_failed = True
                    quarantine_seconds = (
                        _deleted_onemin_key_quarantine_seconds()
                        if _is_deleted_onemin_key_error(onemin_error)
                        else None
                    )
                    _mark_onemin_failure(
                        api_key,
                        onemin_error,
                        temporary_quarantine=True,
                        quarantine_seconds=quarantine_seconds,
                    )
                    break
                if _is_retryable_onemin_error(onemin_error):
                    _mark_onemin_failure(api_key, onemin_error, temporary_quarantine=False)
                    if _is_onemin_key_depleted(onemin_error):
                        key_depleted = True
                    if mode == "code" and index == 0:
                        continue
                    break
                _mark_onemin_failure(api_key, onemin_error)
                break

            text = _extract_onemin_text(payload)
            if not text:
                reason = f"{key_slot}:{mode}:empty_response"
                errors.append(reason)
                key_fallback_reason.append(reason)
                _mark_onemin_failure(api_key, reason)
                break

            resolved_model = _extract_onemin_model(payload) or model
            tokens_in, tokens_out = (0, 0)
            usage = payload.get("usage") if isinstance(payload, dict) else {}
            if isinstance(usage, dict):
                tokens_in = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
                tokens_out = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
            _record_onemin_usage_event(
                api_key=api_key,
                model=resolved_model,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
            )
            _mark_onemin_success(api_key)
            fallback_reason = None
            if failures or key_fallback_reason:
                fallback_reason = "; ".join(failures + key_fallback_reason)
            _log_provider_selection(
                provider="onemin",
                event="success",
                key_slot=key_slot,
                model=resolved_model,
                latency_ms=latency_ms,
                reason=fallback_reason,
            )
            return UpstreamResult(
                text=text,
                provider_key=config.provider_key,
                model=resolved_model,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                provider_key_slot=key_slot,
                provider_backend="1min",
                provider_account_name=account_name,
                upstream_model=model,
                latency_ms=max(0, latency_ms),
                fallback_reason=fallback_reason,
            )

        if key_depleted:
            _rotate_onemin_cursor_after_key_usage(api_key)
            _log_provider_selection(
                provider="onemin",
                event="depletion",
                key_slot=key_slot,
                model=model,
                latency_ms=0,
                reason="; ".join(failures + key_fallback_reason),
            )
        elif key_auth_failed:
            _rotate_onemin_cursor_after_key_usage(api_key)
        elif failures or key_fallback_reason:
            _rotate_onemin_cursor_after_key_usage(api_key)
        if (
            not allow_reserve
            and len(all_key_names) > len(active_key_names)
            and all(key in tested for key in active_key_names)
        ):
            allow_reserve = True
    if not errors:
        raise ResponsesUpstreamError("onemin_unavailable")
    _log_provider_selection(
        provider="onemin",
        event="failure",
        key_slot="unavailable",
        model=model,
        latency_ms=0,
        reason="; ".join(errors),
    )
    raise ResponsesUpstreamError("; ".join(errors))


def _log_provider_selection(
    *,
    provider: str,
    event: str,
    key_slot: str,
    model: str,
    latency_ms: int,
    reason: str | None = None,
) -> None:
    _LOG.info(
        "responses_provider",
        extra={
            "provider": provider,
            "event": event,
            "provider_key_slot": key_slot,
            "upstream_model": model,
            "latency_ms": latency_ms,
            "fallback_reason": reason,
        },
    )


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
        "api key has been deleted",
        "key has been deleted",
        "api key deleted",
        "api key revoked",
        "revoked api key",
        "deactivated api key",
        "api key disabled",
        "api key expired",
    )
    return any(marker in lowered for marker in markers)


def _requires_smaller_max_tokens(payload: Any) -> bool:
    lowered = str(payload or "").lower()
    markers = (
        "fewer max_tokens",
        "requires more credits",
        "can only afford",
    )
    return all(marker in lowered for marker in markers)


def generate_text(
    *,
    prompt: str = "",
    messages: list[dict[str, str]] | None = None,
    requested_model: str = "",
    max_output_tokens: int | None = None,
    chatplayground_audit_callback: Callable[..., Any] | None = None,
    chatplayground_audit_callback_only: bool = False,
    chatplayground_audit_principal_id: str = "",
) -> UpstreamResult:
    normalized_messages = _normalize_messages(prompt=prompt, messages=messages)
    prompt_text = _messages_to_prompt(normalized_messages)
    if not prompt_text and not normalized_messages:
        raise ResponsesUpstreamError("prompt_required")

    lane = _effective_request_lane(requested_model=requested_model, max_output_tokens=max_output_tokens)
    lane_cap = _lane_max_output_tokens(lane)
    resolved_max_output_tokens = (
        lane_cap
        if lane_cap is not None and max_output_tokens is None
        else max_output_tokens
    )
    if lane_cap is not None and resolved_max_output_tokens is not None:
        resolved_max_output_tokens = _to_int(
            resolved_max_output_tokens,
            lane_cap,
            minimum=16,
            maximum=100000,
        )
    elif lane_cap is not None and resolved_max_output_tokens is None:
        resolved_max_output_tokens = lane_cap
    hold_hard_slot = False
    _, _, hard_downscale = _resolve_hard_defaults()
    if lane == _LANE_HARD:
        hold_hard_slot = _acquire_hard_slot()
        if not hold_hard_slot:
            resolved_max_output_tokens = _to_int(
                resolved_max_output_tokens,
                hard_downscale,
                minimum=16,
                maximum=100000,
            )
            _LOG.warning(
                "responses_hard_lane_throttled",
                extra={"requested_model": requested_model, "event": "hard_slot_wait_timeout"},
            )

    errors: list[str] = []
    blocked_providers: set[str] = set()
    try:
        for config, model_name in _provider_candidates(requested_model, lane=lane):
            if config.provider_key in blocked_providers:
                continue
            if not config.api_keys:
                # Chatplayground can run in callback-only mode without environment
                # API key storage when audit execution is delegated to local tool calls.
                if config.provider_key == "chatplayground" and chatplayground_audit_callback_only:
                    pass
                else:
                    errors.append(f"{config.provider_key}:missing_api_key")
                    continue
            try:
                if config.provider_key == "magixai":
                    return _call_magicx(
                        config,
                        prompt=prompt_text,
                        messages=normalized_messages,
                        model=model_name,
                        max_output_tokens=resolved_max_output_tokens,
                        lane=lane,
                    )
                if config.provider_key == "onemin":
                    return _call_onemin(
                        config,
                        prompt=prompt_text,
                        messages=normalized_messages,
                        model=model_name,
                        max_output_tokens=resolved_max_output_tokens,
                        lane=lane,
                    )
                if config.provider_key == "chatplayground":
                    return _call_chatplayground_audit(
                        config,
                        prompt=prompt_text,
                        messages=normalized_messages,
                        model=model_name,
                        max_output_tokens=resolved_max_output_tokens,
                        lane=lane,
                        chatplayground_audit_callback=chatplayground_audit_callback,
                        chatplayground_audit_callback_only=chatplayground_audit_callback_only,
                        chatplayground_audit_principal_id=chatplayground_audit_principal_id,
                    )
                if config.provider_key == "gemini_vortex":
                    return _call_gemini_vortex(
                        config,
                        prompt=prompt_text,
                        messages=normalized_messages,
                        model=model_name,
                        max_output_tokens=resolved_max_output_tokens,
                        lane=lane,
                    )
                errors.append(f"{config.provider_key}:unsupported_provider")
            except ResponsesUpstreamError as exc:
                message = str(exc)
                errors.append(f"{config.provider_key}/{model_name}:{message}")
                if _is_provider_fatal_error(message):
                    blocked_providers.add(config.provider_key)
    finally:
        if hold_hard_slot:
            _release_hard_slot()

    if not errors:
        raise ResponsesUpstreamError("no_upstream_responses_provider")
    raise ResponsesUpstreamError("; ".join(errors))


def _test_reset_onemin_states() -> None:
    global _ONEMIN_KEY_CURSOR
    with _ONEMIN_KEY_CURSOR_LOCK:
        _ONEMIN_KEY_STATES.clear()
        _ONEMIN_KEY_CURSOR = 0
    with _ONEMIN_USAGE_LOCK:
        _ONEMIN_USAGE_EVENTS.clear()
        _ONEMIN_REQUIRED_CREDIT_EVENTS.clear()
    with _MAGIX_HEALTH_LOCK:
        _MAGIX_HEALTH_STATE.update(state="unknown", checked_at=0.0, detail="", provider_key="magixai")


def _provider_health_report() -> dict[str, object]:
    now = _now_epoch()
    onemin_key_names = _onemin_key_names()
    onemin_active_keys = _onemin_active_keys()
    onemin_reserve_keys = _onemin_reserve_keys()
    onemin_key_states = _onemin_states_snapshot(onemin_key_names)
    onemin_slots: list[dict[str, object]] = []
    if _magix_health_probe_enabled():
        _magix_is_ready()

    for key in onemin_key_names:
        key_state = onemin_key_states.get(key, OneminKeyState(key=key))
        slot_state = _onemin_key_state_label(key_state, now=now)
        credit_state = _parse_credit_state(key_state.last_error)
        estimated_remaining_credits, estimated_credit_basis = _estimated_onemin_remaining_credits(
            state_label=slot_state,
            state=key_state,
        )
        observed_spend = _observed_onemin_spend(api_key=key)
        observed_success_count = _observed_onemin_request_count(api_key=key)
        next_retry_at = 0.0
        if key_state.quarantine_until > now:
            next_retry_at = float(key_state.quarantine_until)
        elif key_state.cooldown_until > now:
            next_retry_at = float(key_state.cooldown_until)
        onemin_slots.append(
            {
                "slot": _onemin_key_slot_from_snapshot(key, key_names=onemin_key_names),
                "configured": bool(key),
                "account_name": _provider_account_name("onemin", key_names=onemin_key_names, key=key),
                "state": slot_state,
                "last_used_at": float(key_state.last_used_at),
                "last_success_at": float(key_state.last_success_at),
                "last_failure_at": float(key_state.last_failure_at),
                "cooldown_until": float(key_state.cooldown_until),
                "quarantine_until": float(key_state.quarantine_until),
                "failure_count": int(key_state.failure_count),
                "last_error": str(key_state.last_error),
                "remaining_credits": credit_state.get("remaining_credits") if credit_state else None,
                "required_credits": credit_state.get("required_credits") if credit_state else None,
                "credit_subject": credit_state.get("credit_subject") if credit_state else None,
                "estimated_remaining_credits": estimated_remaining_credits,
                "estimated_credit_basis": estimated_credit_basis,
                "observed_consumed_credits": observed_spend,
                "observed_success_count": observed_success_count,
                "next_retry_at": next_retry_at or None,
                "upstream_reset_unknown": bool(credit_state and credit_state.get("remaining_credits") == 0),
            }
        )

    onemin_max_total = _onemin_max_credits_total(len(onemin_slots))
    onemin_estimated_remaining_total = sum(
        int(slot.get("estimated_remaining_credits") or 0)
        for slot in onemin_slots
    )
    onemin_burn_summary = _onemin_burn_summary(
        now=now,
        estimated_remaining_credits_total=onemin_estimated_remaining_total,
    )
    onemin_remaining_percent = None
    if onemin_max_total > 0:
        onemin_remaining_percent = round((onemin_estimated_remaining_total / onemin_max_total) * 100.0, 2)

    magix_state, magix_detail, magix_checked_at = _magix_health_state_snapshot()
    magix_key_names = tuple(_magicx_config().api_keys)
    magix_slots = [
        {
            "slot": _onemin_key_slot(api_key, key_names=magix_key_names),
            "configured": bool(api_key),
            "account_name": _provider_account_name("magixai", key_names=magix_key_names, key=api_key),
            "state": "ready" if api_key and magix_state == "ready" else ("degraded" if api_key else "missing"),
        }
        for api_key in magix_key_names
    ]
    chatplayground_key_names = _browserplayground_api_keys()
    chatplayground_slots = [
        {
            "slot": _onemin_key_slot(api_key, key_names=chatplayground_key_names),
            "configured": bool(api_key),
            "account_name": _provider_account_name("chatplayground", key_names=chatplayground_key_names, key=api_key),
            "state": "ready" if api_key else "missing",
        }
        for api_key in chatplayground_key_names
    ]
    gemini_command = _env("EA_GEMINI_VORTEX_COMMAND") or "gemini"
    gemini_state, gemini_detail = _gemini_vortex_health_state()
    gemini_key_names = (gemini_command,)
    gemini_slots = [
        {
            "slot": "primary",
            "configured": bool(gemini_command),
            "account_name": _provider_account_name("gemini_vortex", key_names=gemini_key_names, key=gemini_command),
            "state": gemini_state,
        }
    ]
    hard_max_active, hard_queue_timeout, _ = _resolve_hard_defaults()
    onemin_max_requests_per_hour = _onemin_max_requests_per_hour()
    onemin_max_credits_per_hour = _onemin_max_credits_per_hour()
    onemin_max_credits_per_day = _onemin_max_credits_per_day()
    return {
        "providers": {
            "onemin": {
                "provider_key": "onemin",
                "configured_slots": len(onemin_slots),
                "backend": "1min",
                "slots": onemin_slots,
                "health_check_enabled": False,
                "provider_order": list(_provider_order()),
                "observed_remaining_credits": {
                    slot["account_name"]: slot["remaining_credits"]
                    for slot in onemin_slots
                    if slot.get("remaining_credits") is not None
                },
                "remaining_percent_of_max": onemin_remaining_percent,
                "estimated_remaining_credits_total": onemin_estimated_remaining_total,
                "max_credits_total": onemin_max_total,
                "max_credits_per_key": _onemin_max_credits_per_key(),
                "credit_estimation_mode": "observed_error_or_observed_usage_or_ready_assumed_full",
                "max_requests_per_hour": onemin_max_requests_per_hour,
                "max_credits_per_hour": onemin_max_credits_per_hour,
                "max_credits_per_day": onemin_max_credits_per_day,
                **onemin_burn_summary,
            },
            "magixai": {
                "provider_key": "magixai",
                "configured_slots": len(magix_slots),
                "backend": "aimagicx",
                "slots": magix_slots,
                "state": magix_state,
                "detail": magix_detail,
                "checked_at": magix_checked_at,
                "health_check_enabled": bool(_magix_health_probe_enabled()),
            },
            "chatplayground": {
                "provider_key": "chatplayground",
                "backend": "browseract",
                "provider_url": _browserplayground_url(),
                "configured_slots": len(chatplayground_slots),
                "slots": chatplayground_slots,
            },
            "gemini_vortex": {
                "provider_key": "gemini_vortex",
                "backend": "gemini_vortex_cli",
                "configured_slots": len(gemini_slots),
                "slots": gemini_slots,
                "state": gemini_state,
                "detail": gemini_detail,
                "models": list(_gemini_vortex_models()),
            },
        },
        "provider_config": {
            "default_profile": _env("EA_RESPONSES_DEFAULT_PROFILE", _DEFAULT_LANE_PROFILE) or _DEFAULT_LANE_PROFILE,
            "default_lane": _resolve_default_response_lane(),
            "provider_order": list(_provider_order()),
            "onemin_accounts": [
                _provider_account_name("onemin", key_names=onemin_key_names, key=key)
                for key in onemin_key_names
            ],
            "onemin_active_accounts": [
                _provider_account_name("onemin", key_names=onemin_key_names, key=key)
                for key in onemin_active_keys
            ],
            "onemin_reserve_accounts": [
                _provider_account_name("onemin", key_names=onemin_key_names, key=key)
                for key in onemin_reserve_keys
            ],
            "onemin_max_slots": len(_onemin_secret_env_names()),
            "onemin_included_credits_per_key": _onemin_included_credits_per_key(),
            "onemin_bonus_credits_per_key": _onemin_bonus_credits_per_key(),
            "onemin_max_requests_per_hour": onemin_max_requests_per_hour,
            "onemin_max_credits_per_hour": onemin_max_credits_per_hour,
            "onemin_max_credits_per_day": onemin_max_credits_per_day,
            "chatplayground_accounts": [
                _provider_account_name("chatplayground", key_names=chatplayground_key_names, key=key)
                for key in chatplayground_key_names
            ],
            "chatplayground_url": _browserplayground_url(),
            "gemini_vortex_command": gemini_command,
            "gemini_vortex_models": list(_gemini_vortex_models()),
            "hard_max_active_requests": hard_max_active,
            "hard_queue_timeout_seconds": hard_queue_timeout,
            "lane_caps": {
                _LANE_FAST: _lane_max_output_tokens(_LANE_FAST),
                _LANE_REVIEW: _lane_max_output_tokens(_LANE_REVIEW),
                _LANE_HARD: _lane_max_output_tokens(_LANE_HARD),
                _LANE_OVERFLOW: _lane_max_output_tokens(_LANE_OVERFLOW),
                "default": _lane_max_output_tokens(_LANE_DEFAULT),
            },
        },
        "magicx": {
            "urls": list(_magicx_urls()),
            "models": list(_magicx_models()),
            "health": magix_state,
        },
    }
