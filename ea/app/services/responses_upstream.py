from __future__ import annotations

from collections import deque
import hashlib
import json
import logging
import inspect
import os
from pathlib import Path
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
FAST_PUBLIC_MODEL = "ea-coder-fast"
GROUNDWORK_PUBLIC_MODEL = "ea-groundwork-gemini"
GROUNDWORK_PUBLIC_MODEL_ALIAS = "ea-groundwork"
REVIEW_LIGHT_PUBLIC_MODEL = "ea-review-light"
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
_ONEMIN_PROBE_EVENTS: deque[OneminProbeEvent] = deque(maxlen=512)
_PROVIDER_BALANCE_SNAPSHOTS: deque[ProviderBalanceSnapshot] = deque(maxlen=512)
_PROVIDER_DISPATCH_EVENTS: deque[ProviderDispatchEvent] = deque(maxlen=1024)
_ONEMIN_USAGE_LOCK = threading.Lock()
_PROVIDER_LEDGER_LOADED = False
_PROVIDER_LEDGER_LOCK = threading.Lock()

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
_LANE_REVIEW_LIGHT = "review_light"

_AUDIT_OUTPUT_TEXT_HEADER = "BrowserAct ChatPlayground audit"

_HARD_MAX_ACTIVE_REQUESTS = 1
_HARD_QUEUE_TIMEOUT_SECONDS = 120.0
_HARD_DOWNSCALE_MAX_OUTPUT_TOKENS = 256
_ONEMIN_AUTH_QUARANTINE_SECONDS = 1800.0
_ONEMIN_DELETED_KEY_QUARANTINE_SECONDS = 86400.0
_ONEMIN_RATE_LIMIT_COOLDOWN_SECONDS = 60.0
_ONEMIN_FAILURE_COOLDOWN_SECONDS = 20.0
_MAGIX_VERIFICATION_TIMEOUT_SECONDS = 5

_ONEMIN_MAX_REQUESTS_PER_HOUR = 0
_ONEMIN_MAX_CREDITS_PER_HOUR = 80000
_ONEMIN_MAX_CREDITS_PER_DAY = 600000
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


def _compact_text_preview(text: object, *, limit: int = 160) -> str:
    normalized = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(limit - 3, 0)].rstrip() + "..."


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
class ProviderBalanceSnapshot:
    happened_at: float
    provider_key: str
    account_name: str
    remaining_credits: int | None
    max_credits: int | None
    basis: str
    source: str
    topup_detected: bool = False
    topup_delta: int | None = None
    detail: str = ""


@dataclass(frozen=True)
class OneminProbeEvent:
    happened_at: float
    account_name: str
    slot: str
    result: str
    detail: str = ""
    model: str = ""
    latency_ms: int = 0
    source: str = "explicit_probe"


@dataclass(frozen=True)
class ProviderDispatchEvent:
    happened_at: float
    provider_key: str
    model: str
    lane: str
    estimated_onemin_credits: int | None


@dataclass(frozen=True)
class ProviderConfig:
    provider_key: str
    display_name: str
    api_keys: tuple[str, ...]
    default_models: tuple[str, ...]
    timeout_seconds: int


def _env(name: str, default: str = "") -> str:
    return str(os.environ.get(name) or default).strip()


def _provider_ledger_dir() -> Path | None:
    raw = _env("EA_RESPONSES_PROVIDER_LEDGER_DIR", "/tmp/ea_provider_ledger")
    if not raw:
        return None
    try:
        path = Path(raw)
        path.mkdir(parents=True, exist_ok=True)
        return path
    except Exception:
        return None


def _provider_ledger_file(name: str) -> Path | None:
    root = _provider_ledger_dir()
    if root is None:
        return None
    return root / name


def _append_provider_ledger_record(name: str, payload: dict[str, object]) -> None:
    target = _provider_ledger_file(name)
    if target is None:
        return
    try:
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=True, separators=(",", ":")))
            handle.write("\n")
    except Exception:
        return


def _load_provider_ledger_records(name: str) -> list[dict[str, object]]:
    target = _provider_ledger_file(name)
    if target is None or not target.exists():
        return []
    rows: list[dict[str, object]] = []
    try:
        for line in target.read_text(encoding="utf-8").splitlines():
            text = str(line or "").strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except Exception:
                continue
            if isinstance(payload, dict):
                rows.append({str(key): value for key, value in payload.items()})
    except Exception:
        return []
    return rows


def _load_provider_ledgers_once() -> None:
    global _PROVIDER_LEDGER_LOADED
    if _PROVIDER_LEDGER_LOADED:
        return
    with _PROVIDER_LEDGER_LOCK:
        if _PROVIDER_LEDGER_LOADED:
            return
        usage_rows = _load_provider_ledger_records("onemin_usage_events.jsonl")
        required_rows = _load_provider_ledger_records("onemin_required_credit_events.jsonl")
        probe_rows = _load_provider_ledger_records("onemin_probe_events.jsonl")
        balance_rows = _load_provider_ledger_records("provider_balance_snapshots.jsonl")
        dispatch_rows = _load_provider_ledger_records("provider_dispatch_events.jsonl")
        with _ONEMIN_USAGE_LOCK:
            for row in usage_rows[-_ONEMIN_USAGE_EVENTS.maxlen :]:
                try:
                    _ONEMIN_USAGE_EVENTS.append(
                        OneminUsageEvent(
                            happened_at=float(row.get("happened_at") or 0.0),
                            api_key=str(row.get("api_key") or ""),
                            model=str(row.get("model") or ""),
                            estimated_credits=int(row.get("estimated_credits") or 0),
                            basis=str(row.get("basis") or "unknown"),
                            tokens_in=int(row.get("tokens_in") or 0),
                            tokens_out=int(row.get("tokens_out") or 0),
                            lane=str(row.get("lane") or "") or None,
                            codex_profile=str(row.get("codex_profile") or "") or None,
                            route=str(row.get("route") or "") or None,
                            principal_id=str(row.get("principal_id") or "") or None,
                            response_id=str(row.get("response_id") or "") or None,
                            task_class=str(row.get("task_class") or "") or None,
                            escalation_reason=str(row.get("escalation_reason") or "") or None,
                        )
                    )
                except Exception:
                    continue
            for row in required_rows[-_ONEMIN_REQUIRED_CREDIT_EVENTS.maxlen :]:
                try:
                    _ONEMIN_REQUIRED_CREDIT_EVENTS.append(
                        OneminRequiredCreditObservation(
                            happened_at=float(row.get("happened_at") or 0.0),
                            api_key=str(row.get("api_key") or ""),
                            required_credits=int(row.get("required_credits") or 0),
                            remaining_credits=int(row.get("remaining_credits") or 0),
                            credit_subject=str(row.get("credit_subject") or ""),
                        )
                    )
                except Exception:
                    continue
            for row in probe_rows[-_ONEMIN_PROBE_EVENTS.maxlen :]:
                try:
                    _ONEMIN_PROBE_EVENTS.append(
                        OneminProbeEvent(
                            happened_at=float(row.get("happened_at") or 0.0),
                            account_name=str(row.get("account_name") or ""),
                            slot=str(row.get("slot") or "unknown"),
                            result=str(row.get("result") or "unknown"),
                            detail=str(row.get("detail") or ""),
                            model=str(row.get("model") or ""),
                            latency_ms=int(row.get("latency_ms") or 0),
                            source=str(row.get("source") or "explicit_probe"),
                        )
                    )
                except Exception:
                    continue
            for row in balance_rows[-_PROVIDER_BALANCE_SNAPSHOTS.maxlen :]:
                try:
                    _PROVIDER_BALANCE_SNAPSHOTS.append(
                        ProviderBalanceSnapshot(
                            happened_at=float(row.get("happened_at") or 0.0),
                            provider_key=str(row.get("provider_key") or ""),
                            account_name=str(row.get("account_name") or ""),
                            remaining_credits=(
                                int(row.get("remaining_credits"))
                                if row.get("remaining_credits") is not None
                                else None
                            ),
                            max_credits=int(row.get("max_credits")) if row.get("max_credits") is not None else None,
                            basis=str(row.get("basis") or "unknown_unprobed"),
                            source=str(row.get("source") or "ledger"),
                            topup_detected=bool(row.get("topup_detected")),
                            topup_delta=(
                                int(row.get("topup_delta"))
                                if row.get("topup_delta") is not None
                                else None
                            ),
                            detail=str(row.get("detail") or ""),
                        )
                    )
                except Exception:
                    continue
            for row in dispatch_rows[-_PROVIDER_DISPATCH_EVENTS.maxlen :]:
                try:
                    _PROVIDER_DISPATCH_EVENTS.append(
                        ProviderDispatchEvent(
                            happened_at=float(row.get("happened_at") or 0.0),
                            provider_key=str(row.get("provider_key") or ""),
                            model=str(row.get("model") or ""),
                            lane=str(row.get("lane") or _LANE_DEFAULT),
                            estimated_onemin_credits=(
                                int(row.get("estimated_onemin_credits"))
                                if row.get("estimated_onemin_credits") is not None
                                else None
                            ),
                        )
                    )
                except Exception:
                    continue
        _PROVIDER_LEDGER_LOADED = True


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


def _review_light_chatplayground_models() -> tuple[str, ...]:
    configured = _csv_values(_env("EA_RESPONSES_REVIEW_LIGHT_CHATPLAYGROUND_MODELS"))
    if configured:
        return configured[:1] or configured
    return ("gpt-4.1",)


def _browserplayground_roles() -> tuple[str, ...]:
    configured = _csv_values(_env("EA_RESPONSES_CHATPLAYGROUND_ROLES"))
    if configured:
        return configured
    return ("factuality", "adversarial", "completeness", "risk")


def _review_light_chatplayground_roles() -> tuple[str, ...]:
    configured = _csv_values(_env("EA_RESPONSES_REVIEW_LIGHT_CHATPLAYGROUND_ROLES"))
    if configured:
        return configured[:1] or configured
    return ("factuality",)


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


def _provider_secret_from_account_name(account_name: str) -> str:
    target = str(account_name or "").strip()
    if not target:
        return ""
    env_value = _env(target)
    if env_value:
        return env_value
    return ""


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def _normalize_sha256_hex(value: object) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if re.fullmatch(r"[0-9a-f]{64}", normalized) else ""


def _onemin_owner_ledger_path() -> Path | None:
    raw = _env("EA_RESPONSES_ONEMIN_OWNER_LEDGER_PATH", "/config/onemin_slot_owners.json")
    if not raw:
        return None
    try:
        path = Path(raw)
    except Exception:
        return None
    return path if path.exists() else None


def _load_onemin_owner_ledger_payload() -> object:
    inline = _env("EA_RESPONSES_ONEMIN_OWNER_LEDGER_JSON")
    if inline:
        try:
            return json.loads(inline)
        except Exception:
            return None
    path = _onemin_owner_ledger_path()
    if path is None:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _onemin_owner_entries() -> list[dict[str, str]]:
    payload = _load_onemin_owner_ledger_payload()
    if isinstance(payload, dict):
        if isinstance(payload.get("slots"), list):
            items = payload.get("slots") or []
        elif isinstance(payload.get("owners"), list):
            items = payload.get("owners") or []
        else:
            items = [
                {"secret_sha256": key, **(value if isinstance(value, dict) else {"owner_label": value})}
                for key, value in payload.items()
            ]
    elif isinstance(payload, list):
        items = payload
    else:
        items = []

    rows: list[dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        secret_sha256 = _normalize_sha256_hex(
            item.get("secret_sha256") or item.get("sha256") or item.get("key_sha256") or item.get("hash")
        )
        account_name = str(item.get("account_name") or item.get("slot_env_name") or "").strip()
        slot = str(item.get("slot") or "").strip()
        owner_email = str(item.get("owner_email") or item.get("email") or "").strip()
        owner_name = str(item.get("owner_name") or item.get("name") or "").strip()
        owner_label = str(item.get("owner_label") or owner_email or owner_name or "").strip()
        notes = str(item.get("notes") or "").strip()
        if not any((secret_sha256, account_name, slot)):
            continue
        rows.append(
            {
                "secret_sha256": secret_sha256,
                "account_name": account_name,
                "slot": slot,
                "owner_email": owner_email,
                "owner_name": owner_name,
                "owner_label": owner_label,
                "notes": notes,
            }
        )
    return rows


def _onemin_owner_record_for_slot(*, api_key: str, account_name: str, slot: str) -> dict[str, str]:
    hashed_secret = _sha256_hex(api_key) if api_key else ""
    direct_slot = str(slot or "").strip().lower()
    direct_account = str(account_name or "").strip()
    fallback_match: dict[str, str] = {}
    for row in _onemin_owner_entries():
        row_hash = str(row.get("secret_sha256") or "").strip().lower()
        if hashed_secret and row_hash and row_hash == hashed_secret:
            return {
                **row,
                "secret_sha256": row_hash,
            }
        if not fallback_match:
            if direct_account and str(row.get("account_name") or "").strip() == direct_account:
                fallback_match = dict(row)
            elif direct_slot and str(row.get("slot") or "").strip().lower() == direct_slot:
                fallback_match = dict(row)
    return fallback_match


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
        _LANE_HARD: _env("EA_RESPONSES_MAX_OUTPUT_TOKENS_HARD", "1536"),
        _LANE_OVERFLOW: _env("EA_RESPONSES_MAX_OUTPUT_TOKENS_OVERFLOW", "1536"),
        _LANE_DEFAULT: _env("EA_RESPONSES_MAX_OUTPUT_TOKENS_HARD", "1536"),
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


def _onemin_slot_role_for_key(api_key: str, *, active_keys: tuple[str, ...], reserve_keys: tuple[str, ...]) -> str:
    if api_key in set(active_keys):
        return "active"
    if api_key in set(reserve_keys):
        return "reserve"
    return "configured"


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


def _onemin_probe_model() -> str:
    configured = str(_env("EA_RESPONSES_ONEMIN_PROBE_MODEL") or "").strip()
    if configured:
        return configured
    preferred = ("gpt-4.1-nano", "gpt-4.1", "deepseek-chat", "gpt-5")
    available = _merge_unique(_onemin_models(), _onemin_code_models())
    lowered = {item.lower(): item for item in available}
    for candidate in preferred:
        if candidate in lowered:
            return lowered[candidate]
    if available:
        return available[0]
    return "gpt-4.1-nano"


def _onemin_probe_timeout_seconds() -> int:
    return _to_int(_env("EA_RESPONSES_ONEMIN_PROBE_TIMEOUT_SECONDS", "15"), 15, minimum=1, maximum=60)


def _onemin_probe_prompt() -> str:
    configured = str(_env("EA_RESPONSES_ONEMIN_PROBE_PROMPT") or "").strip()
    return configured or "Reply with exactly OK."


def _magicx_lane_models() -> tuple[str, ...]:
    configured = _magicx_models()
    desired = (
        "x-ai/grok-code-fast-1",
        "mistralai/codestral-2508",
        "inception/mercury-coder",
    )
    blocked_fast_models = {"openai/gpt-5.1-codex-mini"}
    if _to_bool(_env("EA_RESPONSES_MAGICX_ALLOW_PREMIUM_FAST", "0"), False):
        blocked_fast_models = set()
    filtered = tuple(
        model
        for model in configured
        if str(model or "").strip().lower() not in blocked_fast_models
    )
    if filtered:
        return _merge_unique(filtered, desired)
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
        return _to_int(_env("EA_RESPONSES_MAX_OUTPUT_TOKENS_HARD", "1536"), 1536, minimum=16)
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
    _load_provider_ledgers_once()
    account_name = _provider_account_name("onemin", key_names=_onemin_key_names(), key=state.key)
    latest_snapshot = _latest_provider_balance_snapshot(provider_key="onemin", account_name=account_name)
    if latest_snapshot is not None and latest_snapshot.remaining_credits is not None:
        return int(latest_snapshot.remaining_credits), str(latest_snapshot.basis or "unknown")
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
    return None, "unknown_unprobed"


def _record_onemin_required_credit_observation(*, api_key: str, message: str, happened_at: float | None = None) -> None:
    _load_provider_ledgers_once()
    credit_state = _parse_credit_state(message)
    if credit_state is None:
        return
    effective_time = float(happened_at if happened_at is not None else _now_epoch())
    event = OneminRequiredCreditObservation(
        happened_at=effective_time,
        api_key=api_key,
        required_credits=int(credit_state["required_credits"]),
        remaining_credits=int(credit_state["remaining_credits"]),
        credit_subject=str(credit_state["credit_subject"] or ""),
    )
    with _ONEMIN_USAGE_LOCK:
        _ONEMIN_REQUIRED_CREDIT_EVENTS.append(event)
    _append_provider_ledger_record(
        "onemin_required_credit_events.jsonl",
        {
            "happened_at": event.happened_at,
            "api_key": event.api_key,
            "required_credits": event.required_credits,
            "remaining_credits": event.remaining_credits,
            "credit_subject": event.credit_subject,
        },
    )
    _record_provider_balance_snapshot(
        provider_key="onemin",
        account_name=_provider_account_name("onemin", key_names=_onemin_key_names(), key=api_key),
        remaining_credits=event.remaining_credits,
        max_credits=_onemin_max_credits_per_key(),
        basis="observed_error",
        source="required_credit_error",
        happened_at=effective_time,
        detail=event.credit_subject,
    )


def _recent_provider_balance_snapshots(
    *,
    provider_key: str,
    account_name: str,
) -> list[ProviderBalanceSnapshot]:
    _load_provider_ledgers_once()
    with _ONEMIN_USAGE_LOCK:
        rows = list(_PROVIDER_BALANCE_SNAPSHOTS)
    return [
        item
        for item in rows
        if item.provider_key == provider_key and item.account_name == account_name
    ]


def _latest_provider_balance_snapshot(
    *,
    provider_key: str,
    account_name: str,
) -> ProviderBalanceSnapshot | None:
    snapshots = _recent_provider_balance_snapshots(provider_key=provider_key, account_name=account_name)
    if not snapshots:
        return None
    return max(snapshots, key=lambda item: item.happened_at)


def _observed_spend_since(
    *,
    api_key: str,
    since: float,
) -> int:
    _load_provider_ledgers_once()
    with _ONEMIN_USAGE_LOCK:
        return sum(
            max(0, int(item.estimated_credits))
            for item in _ONEMIN_USAGE_EVENTS
            if item.api_key == api_key and item.happened_at >= since
        )


def _record_provider_balance_snapshot(
    *,
    provider_key: str,
    account_name: str,
    remaining_credits: int | None,
    max_credits: int | None,
    basis: str,
    source: str,
    happened_at: float | None = None,
    detail: str = "",
) -> ProviderBalanceSnapshot:
    _load_provider_ledgers_once()
    effective_time = float(happened_at if happened_at is not None else _now_epoch())
    previous = _latest_provider_balance_snapshot(provider_key=provider_key, account_name=account_name)
    topup_detected = False
    topup_delta = None
    if (
        provider_key == "onemin"
        and previous is not None
        and remaining_credits is not None
        and previous.remaining_credits is not None
    ):
        spent_since_last = _observed_spend_since(api_key=_provider_secret_from_account_name(account_name), since=previous.happened_at)
        threshold = max(100, int(max_credits or 0) // 1000)
        delta = int(remaining_credits) - int(previous.remaining_credits) - int(spent_since_last)
        if delta > threshold:
            topup_detected = True
            topup_delta = delta
    snapshot = ProviderBalanceSnapshot(
        happened_at=effective_time,
        provider_key=provider_key,
        account_name=account_name,
        remaining_credits=remaining_credits,
        max_credits=max_credits,
        basis=str(basis or "unknown_unprobed"),
        source=str(source or "unknown"),
        topup_detected=topup_detected,
        topup_delta=topup_delta,
        detail=str(detail or ""),
    )
    with _ONEMIN_USAGE_LOCK:
        _PROVIDER_BALANCE_SNAPSHOTS.append(snapshot)
    _append_provider_ledger_record(
        "provider_balance_snapshots.jsonl",
        {
            "happened_at": snapshot.happened_at,
            "provider_key": snapshot.provider_key,
            "account_name": snapshot.account_name,
            "remaining_credits": snapshot.remaining_credits,
            "max_credits": snapshot.max_credits,
            "basis": snapshot.basis,
            "source": snapshot.source,
            "topup_detected": snapshot.topup_detected,
            "topup_delta": snapshot.topup_delta,
            "detail": snapshot.detail,
        },
    )
    return snapshot


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
    lane: str | None = None,
    happened_at: float | None = None,
) -> tuple[int, str]:
    _load_provider_ledgers_once()
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
        lane=str(lane or "") or None,
    )
    with _ONEMIN_USAGE_LOCK:
        _ONEMIN_USAGE_EVENTS.append(event)
    _append_provider_ledger_record(
        "onemin_usage_events.jsonl",
        {
            "happened_at": event.happened_at,
            "api_key": event.api_key,
            "model": event.model,
            "estimated_credits": event.estimated_credits,
            "basis": event.basis,
            "tokens_in": event.tokens_in,
            "tokens_out": event.tokens_out,
            "lane": event.lane,
            "codex_profile": event.codex_profile,
            "route": event.route,
            "principal_id": event.principal_id,
            "response_id": event.response_id,
            "task_class": event.task_class,
            "escalation_reason": event.escalation_reason,
        },
    )
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
    raw = _env("EA_RESPONSES_PROVIDER_ORDER", "gemini_vortex,magixai,onemin")
    ordered: list[str] = []
    seen: set[str] = set()
    for item in raw.split(","):
        provider_key = _normalize_provider(item)
        if not provider_key or provider_key in seen:
            continue
        seen.add(provider_key)
        ordered.append(provider_key)
    return tuple(ordered or ("gemini_vortex", "magixai", "onemin"))


def _cheap_provider_order() -> tuple[str, ...]:
    return _merge_unique(("gemini_vortex", "magixai"), tuple(item for item in _provider_order() if item != "onemin"))


def _effective_request_lane(*, requested_model: str, max_output_tokens: int | None = None) -> str:
    normalized = str(requested_model or "").strip().lower()
    if normalized == "":
        return _resolve_default_response_lane()
    if normalized == REVIEW_LIGHT_PUBLIC_MODEL:
        return _LANE_REVIEW_LIGHT
    if normalized in {"ea-review", "ea-critic"}:
        return _LANE_REVIEW
    if normalized == "ea-coder-hard":
        return _LANE_HARD
    if normalized in {AUDIT_PUBLIC_MODEL, AUDIT_PUBLIC_MODEL_ALIAS}:
        return _LANE_AUDIT
    if normalized == GEMINI_VORTEX_PUBLIC_MODEL or normalized in {item.lower() for item in _gemini_vortex_models()}:
        return _LANE_FAST
    if normalized in {GROUNDWORK_PUBLIC_MODEL, GROUNDWORK_PUBLIC_MODEL_ALIAS}:
        return _LANE_FAST
    if normalized == FAST_PUBLIC_MODEL:
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
        if lane == _LANE_REVIEW_LIGHT:
            return _review_light_lane_models()
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


def _groundwork_lane_models() -> tuple[str, ...]:
    models = _browserplayground_models()
    return models[:1] or models


def _review_light_lane_models() -> tuple[str, ...]:
    models = _review_light_chatplayground_models()
    return models[:1] or models


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
        REVIEW_LIGHT_PUBLIC_MODEL,
        ONEMIN_PUBLIC_MODEL,
        GEMINI_VORTEX_PUBLIC_MODEL,
        GROUNDWORK_PUBLIC_MODEL,
        GROUNDWORK_PUBLIC_MODEL_ALIAS,
        SURVIVAL_PUBLIC_MODEL,
        "ea-coder-hard",
        "ea-review",
        "ea-critic",
        FAST_PUBLIC_MODEL,
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


def _chatplayground_audit_max_prompt_chars() -> int:
    raw = _env("EA_CHATPLAYGROUND_AUDIT_MAX_PROMPT_CHARS", "16000")
    try:
        return max(2000, min(120000, int(raw)))
    except Exception:
        return 16000


def _truncate_middle(text: str, *, limit: int) -> str:
    value = str(text or "")
    if limit <= 0 or len(value) <= limit:
        return value
    if limit <= 64:
        return value[:limit]
    spacer = "\n\n[... omitted for BrowserAct audit transport ...]\n\n"
    remaining = limit - len(spacer)
    if remaining <= 32:
        return value[:limit]
    head = remaining // 2
    tail = remaining - head
    return f"{value[:head]}{spacer}{value[-tail:]}".strip()


def _compact_chatplayground_audit_prompt(messages: list[ChatMessage]) -> str:
    if not messages:
        return ""
    keep_system = _env("EA_CHATPLAYGROUND_AUDIT_KEEP_SYSTEM", "0").lower() in {"1", "true", "yes", "on"}
    relevant = list(messages) if keep_system else [message for message in messages if message["role"] != "system"]
    if not relevant:
        relevant = [messages[-1]]
    max_chars = _chatplayground_audit_max_prompt_chars()
    prompt_text = _messages_to_prompt(relevant)
    if len(prompt_text) <= max_chars:
        return prompt_text

    selected: list[ChatMessage] = []
    for message in reversed(relevant):
        candidate = [message, *selected]
        candidate_text = _messages_to_prompt(candidate)
        if not selected and len(candidate_text) > max_chars:
            return _truncate_middle(candidate_text, limit=max_chars)
        if len(candidate_text) > max_chars:
            break
        selected = candidate

    if not selected:
        selected = [relevant[-1]]
    compacted = _messages_to_prompt(selected)
    if len(compacted) <= max_chars:
        return compacted
    return _truncate_middle(compacted, limit=max_chars)


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
        provider_keys_by_lane = _cheap_provider_order()
    elif lane == _LANE_REVIEW_LIGHT:
        provider_keys_by_lane = ("chatplayground",)
    elif lane == _LANE_AUDIT:
        provider_keys_by_lane = ("chatplayground",)
    else:
        provider_keys_by_lane = _provider_order()

    if normalized == DEFAULT_PUBLIC_MODEL or requested == "":
        # Keep the public default biased toward the cheap/fast lane, but never
        # trap it on Magicx-only when the fast lane is degraded or leak into 1min by default.
        if lane in {_LANE_FAST, _LANE_OVERFLOW}:
            provider_keys_by_lane = _cheap_provider_order()
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

    if normalized in {item.lower() for item in _onemin_supported_models()}:
        candidates: list[tuple[ProviderConfig, str]] = [(configs["onemin"], requested)]
        candidates.extend((configs["magixai"], model_name) for model_name in _magicx_lane_models())
        return candidates

    if normalized == GEMINI_VORTEX_PUBLIC_MODEL or normalized in gemini_model_names:
        model_names = _provider_model_order_for_lane("gemini_vortex", lane, requested) or _gemini_vortex_models()
        return [(configs["gemini_vortex"], model_name) for model_name in model_names]

    if normalized in {GROUNDWORK_PUBLIC_MODEL, GROUNDWORK_PUBLIC_MODEL_ALIAS}:
        return [
            (configs["gemini_vortex"], model_name)
            for model_name in _provider_model_order_for_lane("gemini_vortex", lane, requested)
            or _gemini_vortex_models()
        ]

    if normalized == REVIEW_LIGHT_PUBLIC_MODEL:
        return [
            (configs["chatplayground"], model_name)
            for model_name in _review_light_lane_models()
        ]

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

    if normalized in {FAST_PUBLIC_MODEL, "ea-overflow"}:
        candidates: list[tuple[ProviderConfig, str]] = []
        for provider_key in _cheap_provider_order():
            config = configs.get(provider_key)
            if config is None:
                continue
            model_names = _provider_model_order_for_lane(provider_key, lane, requested) or config.default_models
            for model_name in model_names:
                candidates.append((config, model_name))
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
    model_deltas = [
        str(item)
        for item in _normalize_text_list(normalized.get("model_deltas") or normalized.get("model_delta"))
        if str(item).strip()
    ]
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
        "raw_output": {
            "reason": reason,
            "prompt_chars": len(prompt),
            "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "prompt_preview": _compact_text_preview(prompt),
        },
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
    prompt_text = _compact_chatplayground_audit_prompt(normalized_messages)
    if not prompt_text:
        raise ResponsesUpstreamError("chatplayground_prompt_required")

    key_names = tuple(config.api_keys)
    run_url_candidates = _chatplayground_request_urls()

    if lane == _LANE_REVIEW_LIGHT:
        model_candidates = _review_light_lane_models()
        audit_scope = "review_light"
        base_roles = list(_review_light_chatplayground_roles())
    else:
        model_candidates = tuple(config.default_models) or _browserplayground_models()
        audit_scope = "jury"
        base_roles = list(_browserplayground_roles())
    if not model_candidates:
        model_candidates = _browserplayground_models()
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
                if audit_scope == "review_light":
                    roles = list(base_roles)
                    details["roles"] = roles
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
                    fallback_reason=f"callback_success:{_trim_error_payload(details)}",
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
                if audit_scope == "review_light":
                    roles = list(base_roles)
                    details["roles"] = roles
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
                lane=lane,
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
                result: UpstreamResult | None = None
                if config.provider_key == "magixai":
                    result = _call_magicx(
                        config,
                        prompt=prompt_text,
                        messages=normalized_messages,
                        model=model_name,
                        max_output_tokens=resolved_max_output_tokens,
                        lane=lane,
                    )
                elif config.provider_key == "onemin":
                    result = _call_onemin(
                        config,
                        prompt=prompt_text,
                        messages=normalized_messages,
                        model=model_name,
                        max_output_tokens=resolved_max_output_tokens,
                        lane=lane,
                    )
                elif config.provider_key == "chatplayground":
                    result = _call_chatplayground_audit(
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
                elif config.provider_key == "gemini_vortex":
                    result = _call_gemini_vortex(
                        config,
                        prompt=prompt_text,
                        messages=normalized_messages,
                        model=model_name,
                        max_output_tokens=resolved_max_output_tokens,
                        lane=lane,
                    )
                if result is not None:
                    estimated_onemin_credits, _ = _estimate_onemin_request_credits(
                        now=_now_epoch(),
                        tokens_in=result.tokens_in,
                        tokens_out=result.tokens_out,
                    )
                    _record_provider_dispatch_event(
                        provider_key=result.provider_key,
                        model=result.model,
                        lane=lane,
                        estimated_onemin_credits=estimated_onemin_credits if estimated_onemin_credits > 0 else None,
                    )
                    return result
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
    global _ONEMIN_KEY_CURSOR, _PROVIDER_LEDGER_LOADED
    with _ONEMIN_KEY_CURSOR_LOCK:
        _ONEMIN_KEY_STATES.clear()
        _ONEMIN_KEY_CURSOR = 0
    with _ONEMIN_USAGE_LOCK:
        _ONEMIN_USAGE_EVENTS.clear()
        _ONEMIN_REQUIRED_CREDIT_EVENTS.clear()
        _ONEMIN_PROBE_EVENTS.clear()
        _PROVIDER_BALANCE_SNAPSHOTS.clear()
        _PROVIDER_DISPATCH_EVENTS.clear()
    with _MAGIX_HEALTH_LOCK:
        _MAGIX_HEALTH_STATE.update(state="unknown", checked_at=0.0, detail="", provider_key="magixai")
    with _PROVIDER_LEDGER_LOCK:
        _PROVIDER_LEDGER_LOADED = False
    for ledger_name in (
        "onemin_usage_events.jsonl",
        "onemin_required_credit_events.jsonl",
        "onemin_probe_events.jsonl",
        "provider_balance_snapshots.jsonl",
        "provider_dispatch_events.jsonl",
    ):
        target = _provider_ledger_file(ledger_name)
        if target is None:
            continue
        try:
            target.unlink(missing_ok=True)
        except Exception:
            continue


def _status_window_seconds(window: str) -> float:
    normalized = str(window or "1h").strip().lower()
    if normalized == "24h":
        return 86400.0
    if normalized == "7d":
        return 604800.0
    return 3600.0


def _onemin_lane_burn_summary(*, now: float, window_seconds: float) -> dict[str, object]:
    _load_provider_ledgers_once()
    with _ONEMIN_USAGE_LOCK:
        usage_events = [item for item in _ONEMIN_USAGE_EVENTS if now - item.happened_at <= window_seconds]
    lane_requests: dict[str, int] = {}
    lane_credits: dict[str, int] = {}
    for item in usage_events:
        lane = str(item.lane or "unknown")
        lane_requests[lane] = lane_requests.get(lane, 0) + 1
        lane_credits[lane] = lane_credits.get(lane, 0) + max(0, int(item.estimated_credits))
    return {
        "window_seconds": window_seconds,
        "provider_credits": {"onemin": sum(max(0, int(item.estimated_credits)) for item in usage_events)},
        "lane_requests": lane_requests,
        "lane_credits": lane_credits,
    }


def _record_provider_dispatch_event(
    *,
    provider_key: str,
    model: str,
    lane: str,
    estimated_onemin_credits: int | None,
    happened_at: float | None = None,
) -> None:
    _load_provider_ledgers_once()
    event = ProviderDispatchEvent(
        happened_at=float(happened_at if happened_at is not None else _now_epoch()),
        provider_key=str(provider_key or ""),
        model=str(model or ""),
        lane=str(lane or _LANE_DEFAULT),
        estimated_onemin_credits=int(estimated_onemin_credits) if estimated_onemin_credits is not None else None,
    )
    with _ONEMIN_USAGE_LOCK:
        _PROVIDER_DISPATCH_EVENTS.append(event)
    _append_provider_ledger_record(
        "provider_dispatch_events.jsonl",
        {
            "happened_at": event.happened_at,
            "provider_key": event.provider_key,
            "model": event.model,
            "lane": event.lane,
            "estimated_onemin_credits": event.estimated_onemin_credits,
        },
    )


def _avoided_onemin_credit_summary(*, now: float, window_seconds: float) -> dict[str, object]:
    _load_provider_ledgers_once()
    with _ONEMIN_USAGE_LOCK:
        dispatch_events = [item for item in _PROVIDER_DISPATCH_EVENTS if now - item.happened_at <= window_seconds]
    by_lane: dict[str, dict[str, int]] = {}
    for item in dispatch_events:
        lane = str(item.lane or _LANE_DEFAULT)
        if lane not in {"fast", "audit"}:
            continue
        if item.provider_key == "onemin":
            continue
        bucket = by_lane.setdefault(
            lane,
            {"avoided_credits": 0, "requests": 0},
        )
        bucket["requests"] += 1
        bucket["avoided_credits"] += max(0, int(item.estimated_onemin_credits or 0))
    return {
        "window_seconds": window_seconds,
        "easy_lane": by_lane.get("fast", {"avoided_credits": 0, "requests": 0}),
        "jury_lane": by_lane.get("audit", {"avoided_credits": 0, "requests": 0}),
        "total_avoided_credits": sum(bucket["avoided_credits"] for bucket in by_lane.values()),
    }


def _avoided_credit_text(*, actual_onemin_burn: int, avoided: dict[str, object]) -> dict[str, str]:
    lines: dict[str, str] = {}
    actual = max(0, int(actual_onemin_burn))
    for key, lane_name in (("easy_lane", "easy"), ("jury_lane", "jury")):
        bucket = dict(avoided.get(key) or {})
        avoided_credits = max(0, int(bucket.get("avoided_credits") or 0))
        requests = max(0, int(bucket.get("requests") or 0))
        if avoided_credits <= 0 or requests <= 0:
            lines[lane_name] = f"No measurable {lane_name} lane savings yet in this window."
            continue
        percent = round((avoided_credits / float(actual + avoided_credits)) * 100.0, 1) if (actual + avoided_credits) > 0 else 0.0
        lines[lane_name] = (
            f"Without the {lane_name} lane, the 1min pool would be about {percent}% lower "
            f"in this window ({avoided_credits} credits avoided across {requests} requests)."
        )
    return lines


def _recent_topup_events(*, provider_key: str, limit: int = 10) -> list[ProviderBalanceSnapshot]:
    _load_provider_ledgers_once()
    with _ONEMIN_USAGE_LOCK:
        rows = [item for item in _PROVIDER_BALANCE_SNAPSHOTS if item.provider_key == provider_key and item.topup_detected]
    rows.sort(key=lambda item: item.happened_at, reverse=True)
    return rows[: max(1, limit)]


def codex_status_report(*, window: str = "1h") -> dict[str, object]:
    provider_health = _provider_health_report()
    now = _now_epoch()
    window_seconds = _status_window_seconds(window)
    onemin = dict((provider_health.get("providers") or {}).get("onemin") or {})
    slots = list(onemin.get("slots") or [])
    providers_summary: list[dict[str, object]] = []
    for provider_key, provider in dict(provider_health.get("providers") or {}).items():
        provider_dict = dict(provider or {})
        provider_slots = list(provider_dict.get("slots") or [])
        if provider_key == "onemin":
            for slot in provider_slots:
                detail = (
                    str(slot.get("last_probe_detail") or "").strip()
                    or str(slot.get("last_error") or "").strip()
                    or str(slot.get("credit_subject") or "").strip()
                )
                providers_summary.append(
                    {
                        "provider_key": "onemin",
                        "provider_name": "1min",
                        "account_name": slot.get("account_name"),
                        "slot_env_name": slot.get("slot_env_name") or slot.get("account_name"),
                        "slot": slot.get("slot"),
                        "slot_role": slot.get("slot_role"),
                        "owner_label": slot.get("owner_label"),
                        "owner_name": slot.get("owner_name"),
                        "owner_email": slot.get("owner_email"),
                        "state": slot.get("state"),
                        "free_credits": slot.get("estimated_remaining_credits"),
                        "max_credits": slot.get("max_credits"),
                        "used_percent": (
                            round(
                                (1.0 - (float(slot.get("estimated_remaining_credits")) / float(slot.get("max_credits")))) * 100.0,
                                2,
                            )
                            if slot.get("estimated_remaining_credits") is not None and slot.get("max_credits")
                            else None
                        ),
                        "basis": slot.get("estimated_credit_basis"),
                        "detail": detail,
                        "last_error": slot.get("last_error"),
                        "quarantine_until": slot.get("quarantine_until"),
                        "last_probe_at": slot.get("last_probe_at"),
                        "last_probe_result": slot.get("last_probe_result"),
                        "last_probe_detail": slot.get("last_probe_detail"),
                        "last_probe_model": slot.get("last_probe_model"),
                        "last_probe_latency_ms": slot.get("last_probe_latency_ms"),
                        "last_balance_observed_at": slot.get("last_balance_observed_at"),
                        "burn_credits_per_hour": onemin.get("estimated_burn_credits_per_hour"),
                        "hours_remaining_at_current_pace": onemin.get("estimated_hours_remaining_at_current_pace"),
                    }
                )
            continue
        for slot in provider_slots or [{}]:
            providers_summary.append(
                {
                    "provider_key": provider_key,
                    "provider_name": str(provider_dict.get("backend") or provider_key),
                    "account_name": slot.get("account_name"),
                    "slot": slot.get("slot"),
                    "state": slot.get("state") or provider_dict.get("state"),
                    "free_credits": None,
                    "max_credits": None,
                    "used_percent": None,
                    "basis": "no_balance_api",
                    "last_balance_observed_at": None,
                    "burn_credits_per_hour": None,
                    "hours_remaining_at_current_pace": None,
                }
            )
    topups = _recent_topup_events(provider_key="onemin", limit=10)
    burn_1h_summary = _onemin_lane_burn_summary(now=now, window_seconds=3600.0)
    burn_24h_summary = _onemin_lane_burn_summary(now=now, window_seconds=86400.0)
    burn_7d_summary = _onemin_lane_burn_summary(now=now, window_seconds=604800.0)
    selected_window_burn = _onemin_lane_burn_summary(now=now, window_seconds=window_seconds)
    selected_window_avoided = _avoided_onemin_credit_summary(now=now, window_seconds=window_seconds)
    basis_counts = dict(onemin.get("balance_basis_counts") or {})
    state_counts: dict[str, int] = {}
    precomputed_slots: list[dict[str, object]] = []
    for slot in slots:
        state = str(slot.get("state") or "unknown").strip() or "unknown"
        basis = str(slot.get("estimated_credit_basis") or "unknown_unprobed").strip() or "unknown_unprobed"
        state_counts[state] = state_counts.get(state, 0) + 1
        detail = (
            str(slot.get("last_probe_detail") or "").strip()
            or str(slot.get("last_error") or "").strip()
            or str(slot.get("credit_subject") or "").strip()
        )
        revoked_like = bool(
            state in {"deleted", "revoked", "disabled", "expired"}
            or _is_deleted_onemin_key_error(" ".join(filter(None, [detail, str(slot.get("last_error") or "")])))
        )
        precomputed_slots.append(
            {
                "account_name": slot.get("account_name"),
                "slot_env_name": slot.get("slot_env_name") or slot.get("account_name"),
                "slot": slot.get("slot"),
                "slot_role": slot.get("slot_role"),
                "owner_label": slot.get("owner_label"),
                "owner_name": slot.get("owner_name"),
                "owner_email": slot.get("owner_email"),
                "state": state,
                "basis": basis,
                "free_credits": slot.get("estimated_remaining_credits"),
                "max_credits": slot.get("max_credits"),
                "detail": detail,
                "last_error": slot.get("last_error"),
                "quarantine_until": slot.get("quarantine_until"),
                "last_probe_at": slot.get("last_probe_at"),
                "last_probe_result": slot.get("last_probe_result"),
                "last_probe_detail": slot.get("last_probe_detail"),
                "last_probe_model": slot.get("last_probe_model"),
                "last_probe_latency_ms": slot.get("last_probe_latency_ms"),
                "revoked_like": revoked_like,
                "quarantined": bool(slot.get("quarantine_until")),
            }
        )
    seven_day_burn_total = (burn_7d_summary.get("provider_credits") or {}).get("onemin") or 0
    avg_daily_burn_7d = (float(seven_day_burn_total) / 7.0) if seven_day_burn_total else None
    remaining_total = onemin.get("estimated_remaining_credits_total")
    days_remaining_7d = None
    if remaining_total is not None and avg_daily_burn_7d not in (None, 0):
        days_remaining_7d = round(float(remaining_total) / float(avg_daily_burn_7d), 2)
    onemin_aggregate = {
        "slot_count": len(slots),
        "slot_count_with_known_balance": sum(1 for slot in slots if slot.get("estimated_remaining_credits") is not None),
        "slot_count_with_positive_balance": sum(1 for slot in slots if int(slot.get("estimated_remaining_credits") or 0) > 0),
        "sum_max_credits": onemin.get("max_credits_total"),
        "sum_free_credits": onemin.get("estimated_remaining_credits_total"),
        "remaining_percent_total": onemin.get("remaining_percent_of_max"),
        "current_pace_burn_credits_per_hour": onemin.get("estimated_burn_credits_per_hour"),
        "hours_remaining_at_current_pace": onemin.get("estimated_hours_remaining_at_current_pace"),
        "avg_daily_burn_credits_7d": avg_daily_burn_7d,
        "days_remaining_at_7d_avg_burn": days_remaining_7d,
        "basis_summary": onemin.get("balance_basis_summary"),
        "state_summary": ",".join(sorted(state_counts.keys())) if state_counts else "unknown",
        "basis_counts": basis_counts,
        "state_counts": state_counts,
        "unknown_unprobed_slot_count": int(basis_counts.get("unknown_unprobed") or 0),
        "observed_error_slot_count": int(basis_counts.get("observed_error") or 0),
        "revoked_slot_count": sum(1 for slot in precomputed_slots if slot.get("revoked_like")),
        "quarantined_slot_count": sum(1 for slot in precomputed_slots if slot.get("quarantined")),
        "probe_result_counts": dict(onemin.get("probe_result_counts") or {}),
        "owner_mapped_slot_count": onemin.get("owner_mapped_slots"),
        "last_probe_at": onemin.get("last_probe_at"),
        "slots": precomputed_slots,
        "probe_note": "unknown_unprobed means no live evidence yet; run POST /v1/providers/onemin/probe-all or `codexea onemin --probe-all` to classify untouched slots.",
        "status_basis": onemin.get("credit_estimation_mode"),
        "incoming_topups_excluded": True,
    }
    return {
        "generated_at": now,
        "window": str(window or "1h"),
        "default_profile": provider_health.get("provider_config", {}).get("default_profile"),
        "default_lane": provider_health.get("provider_config", {}).get("default_lane"),
        "provider_health": provider_health,
        "providers_summary": providers_summary,
        "onemin_aggregate": onemin_aggregate,
        "fleet_burn": {
            "1h": burn_1h_summary,
            "24h": burn_24h_summary,
            "7d": burn_7d_summary,
            "selected_window": selected_window_burn,
        },
        "avoided_credits": {
            "1h": _avoided_onemin_credit_summary(now=now, window_seconds=3600.0),
            "24h": _avoided_onemin_credit_summary(now=now, window_seconds=86400.0),
            "7d": _avoided_onemin_credit_summary(now=now, window_seconds=604800.0),
            "selected_window": selected_window_avoided,
            "selected_window_text": _avoided_credit_text(
                actual_onemin_burn=int((selected_window_burn.get("provider_credits") or {}).get("onemin") or 0),
                avoided=selected_window_avoided,
            ),
        },
        "topup_summary": {
            "last_actual_balance_check_at": onemin.get("last_actual_balance_at"),
            "last_topup_detected_at": topups[0].happened_at if topups else None,
            "topup_events": [
                {
                    "happened_at": item.happened_at,
                    "account_name": item.account_name,
                    "topup_delta": item.topup_delta,
                    "basis": item.basis,
                    "source": item.source,
                }
                for item in topups
            ],
            "hours_remaining_at_current_pace": onemin.get("estimated_hours_remaining_at_current_pace"),
        },
        "status_basis": onemin.get("credit_estimation_mode"),
    }


def _parse_credit_like_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return max(0, int(value))
    text = str(value or "").strip()
    if not text:
        return None
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        return None
    try:
        return max(0, int(digits))
    except Exception:
        return None


def _parse_onemin_balance_facts(facts: dict[str, object]) -> tuple[int | None, int | None]:
    remaining_keys = (
        "remaining_credits",
        "free_credits",
        "credits_left",
        "available_credits",
        "credits_available",
    )
    max_keys = (
        "max_credits",
        "total_credits",
        "credits_total",
        "plan_credits",
    )
    remaining = None
    max_credits = None
    for key in remaining_keys:
        remaining = _parse_credit_like_int(facts.get(key))
        if remaining is not None:
            break
    for key in max_keys:
        max_credits = _parse_credit_like_int(facts.get(key))
        if max_credits is not None:
            break
    return remaining, max_credits


def record_provider_balance_snapshot(
    *,
    provider_key: str,
    account_name: str,
    remaining_credits: int | None,
    max_credits: int | None,
    basis: str,
    source: str,
    detail: str = "",
) -> dict[str, object]:
    snapshot = _record_provider_balance_snapshot(
        provider_key=provider_key,
        account_name=account_name,
        remaining_credits=remaining_credits,
        max_credits=max_credits,
        basis=basis,
        source=source,
        detail=detail,
    )
    return {
        "provider_key": snapshot.provider_key,
        "account_name": snapshot.account_name,
        "remaining_credits": snapshot.remaining_credits,
        "max_credits": snapshot.max_credits,
        "basis": snapshot.basis,
        "source": snapshot.source,
        "happened_at": snapshot.happened_at,
        "topup_detected": snapshot.topup_detected,
        "topup_delta": snapshot.topup_delta,
        "detail": snapshot.detail,
    }


def record_onemin_balance_from_facts(
    *,
    account_name: str,
    facts: dict[str, object],
    source: str = "browseract_extract",
    basis: str = "actual_ui_probe",
) -> dict[str, object] | None:
    remaining_credits, max_credits = _parse_onemin_balance_facts(facts)
    if remaining_credits is None:
        return None
    return record_provider_balance_snapshot(
        provider_key="onemin",
        account_name=account_name,
        remaining_credits=remaining_credits,
        max_credits=max_credits or _onemin_max_credits_per_key(),
        basis=basis,
        source=source,
        detail="1min_facts_probe",
    )


def _record_onemin_probe_event(
    *,
    account_name: str,
    slot: str,
    result: str,
    detail: str = "",
    model: str = "",
    latency_ms: int = 0,
    source: str = "explicit_probe",
    happened_at: float | None = None,
) -> OneminProbeEvent:
    _load_provider_ledgers_once()
    event = OneminProbeEvent(
        happened_at=float(happened_at if happened_at is not None else _now_epoch()),
        account_name=str(account_name or ""),
        slot=str(slot or "unknown"),
        result=str(result or "unknown"),
        detail=str(detail or ""),
        model=str(model or ""),
        latency_ms=max(0, int(latency_ms or 0)),
        source=str(source or "explicit_probe"),
    )
    with _ONEMIN_USAGE_LOCK:
        _ONEMIN_PROBE_EVENTS.append(event)
    _append_provider_ledger_record(
        "onemin_probe_events.jsonl",
        {
            "happened_at": event.happened_at,
            "account_name": event.account_name,
            "slot": event.slot,
            "result": event.result,
            "detail": event.detail,
            "model": event.model,
            "latency_ms": event.latency_ms,
            "source": event.source,
        },
    )
    return event


def _latest_onemin_probe_event(*, account_name: str) -> OneminProbeEvent | None:
    _load_provider_ledgers_once()
    with _ONEMIN_USAGE_LOCK:
        rows = [item for item in _ONEMIN_PROBE_EVENTS if item.account_name == account_name]
    if not rows:
        return None
    return max(rows, key=lambda item: item.happened_at)


def _onemin_probe_failure_result(detail: str) -> str:
    lowered = str(detail or "").strip().lower()
    if not lowered:
        return "unknown_error"
    if _is_auth_error(lowered) or _is_deleted_onemin_key_error(lowered):
        return "revoked"
    if _is_onemin_key_depleted(lowered):
        return "depleted"
    if "http_429" in lowered or "rate limit" in lowered or "too_many_requests" in lowered:
        return "rate_limited"
    return "unknown_error"


def _probe_onemin_slot(
    *,
    api_key: str,
    key_names: tuple[str, ...],
    active_keys: tuple[str, ...],
    reserve_keys: tuple[str, ...],
    model: str,
    prompt: str,
    timeout_seconds: int,
    source: str = "probe_all_api",
) -> dict[str, object]:
    account_name = _provider_account_name("onemin", key_names=key_names, key=api_key)
    slot = _onemin_key_slot(api_key, key_names=key_names)
    owner = _onemin_owner_record_for_slot(api_key=api_key, account_name=account_name, slot=slot)
    started_at = _now_ms()
    status, payload = _post_json(
        url=_onemin_chat_url(),
        headers={"API-KEY": api_key},
        payload=_onemin_payload_for_mode("chat", prompt=prompt, model=model),
        timeout_seconds=timeout_seconds,
    )
    latency_ms = _now_ms() - started_at
    error_detail = ""

    if 200 <= status < 300 and isinstance(payload, dict):
        onemin_error = _extract_onemin_error(payload)
        if onemin_error:
            error_detail = onemin_error
        else:
            text = _extract_onemin_text(payload)
            if text:
                usage = payload.get("usage") if isinstance(payload, dict) else {}
                tokens_in = int((usage or {}).get("prompt_tokens") or (usage or {}).get("input_tokens") or 0)
                tokens_out = int((usage or {}).get("completion_tokens") or (usage or {}).get("output_tokens") or 0)
                _record_onemin_usage_event(
                    api_key=api_key,
                    model=_extract_onemin_model(payload) or model,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    lane="probe",
                )
                _mark_onemin_success(api_key)
                event = _record_onemin_probe_event(
                    account_name=account_name,
                    slot=slot,
                    result="ok",
                    detail=text[:117] + "..." if len(text) > 120 else text,
                    model=_extract_onemin_model(payload) or model,
                    latency_ms=latency_ms,
                    source=source,
                )
                latest_balance = _latest_provider_balance_snapshot(provider_key="onemin", account_name=account_name)
                estimated_remaining_credits, estimated_credit_basis = _estimated_onemin_remaining_credits(
                    state_label="ready",
                    state=_onemin_states_snapshot((api_key,)).get(api_key, OneminKeyState(key=api_key)),
                )
                return {
                    "slot": slot,
                    "account_name": account_name,
                    "slot_env_name": account_name,
                    "slot_role": _onemin_slot_role_for_key(api_key, active_keys=active_keys, reserve_keys=reserve_keys),
                    "owner_label": str(owner.get("owner_label") or ""),
                    "owner_name": str(owner.get("owner_name") or ""),
                    "owner_email": str(owner.get("owner_email") or ""),
                    "result": "ok",
                    "state": "ready",
                    "detail": event.detail,
                    "model": event.model,
                    "latency_ms": event.latency_ms,
                    "last_probe_at": event.happened_at,
                    "estimated_remaining_credits": estimated_remaining_credits,
                    "estimated_credit_basis": estimated_credit_basis,
                    "last_balance_observed_at": latest_balance.happened_at if latest_balance is not None else None,
                }
            error_detail = "empty_response"
    elif status < 200 or status >= 300:
        error_detail = _trim_error_payload(payload) or f"http_{status}"
    else:
        error_detail = "invalid_payload"

    result = _onemin_probe_failure_result(error_detail)
    if _is_auth_error(error_detail):
        quarantine_seconds = _deleted_onemin_key_quarantine_seconds() if _is_deleted_onemin_key_error(error_detail) else None
        _mark_onemin_failure(
            api_key,
            error_detail,
            temporary_quarantine=True,
            quarantine_seconds=quarantine_seconds,
        )
    else:
        _mark_onemin_failure(api_key, error_detail, temporary_quarantine=False)
    state = _onemin_key_state_label(
        _onemin_states_snapshot((api_key,)).get(api_key, OneminKeyState(key=api_key)),
        now=_now_epoch(),
    )
    event = _record_onemin_probe_event(
        account_name=account_name,
        slot=slot,
        result=result,
        detail=error_detail,
        model=model,
        latency_ms=latency_ms,
        source=source,
    )
    latest_balance = _latest_provider_balance_snapshot(provider_key="onemin", account_name=account_name)
    estimated_remaining_credits, estimated_credit_basis = _estimated_onemin_remaining_credits(
        state_label=state,
        state=_onemin_states_snapshot((api_key,)).get(api_key, OneminKeyState(key=api_key)),
    )
    return {
        "slot": slot,
        "account_name": account_name,
        "slot_env_name": account_name,
        "slot_role": _onemin_slot_role_for_key(api_key, active_keys=active_keys, reserve_keys=reserve_keys),
        "owner_label": str(owner.get("owner_label") or ""),
        "owner_name": str(owner.get("owner_name") or ""),
        "owner_email": str(owner.get("owner_email") or ""),
        "result": result,
        "state": state,
        "detail": error_detail,
        "model": model,
        "latency_ms": latency_ms,
        "last_probe_at": event.happened_at,
        "estimated_remaining_credits": estimated_remaining_credits,
        "estimated_credit_basis": estimated_credit_basis,
        "last_balance_observed_at": latest_balance.happened_at if latest_balance is not None else None,
    }


def probe_all_onemin_slots(*, include_reserve: bool = True) -> dict[str, object]:
    _load_provider_ledgers_once()
    key_names = _onemin_key_names()
    active_keys = _onemin_active_keys()
    reserve_keys = _onemin_reserve_keys()
    selected_keys = key_names if include_reserve else active_keys
    if not selected_keys:
        return {
            "provider_key": "onemin",
            "slot_count": 0,
            "configured_slot_count": len(key_names),
            "include_reserve": include_reserve,
            "probe_model": _onemin_probe_model(),
            "result_counts": {},
            "owner_mapped_slots": 0,
            "slots": [],
            "note": "No configured 1min slots were available to probe.",
        }
    model = _onemin_probe_model()
    prompt = _onemin_probe_prompt()
    timeout_seconds = _onemin_probe_timeout_seconds()
    rows = [
        _probe_onemin_slot(
            api_key=api_key,
            key_names=key_names,
            active_keys=active_keys,
            reserve_keys=reserve_keys,
            model=model,
            prompt=prompt,
            timeout_seconds=timeout_seconds,
        )
        for api_key in selected_keys
    ]
    result_counts: dict[str, int] = {}
    for row in rows:
        result = str(row.get("result") or "unknown")
        result_counts[result] = result_counts.get(result, 0) + 1
    latest_probe_at = max((float(row.get("last_probe_at") or 0.0) for row in rows), default=0.0) or None
    return {
        "provider_key": "onemin",
        "slot_count": len(rows),
        "configured_slot_count": len(key_names),
        "include_reserve": include_reserve,
        "probe_model": model,
        "probe_prompt": prompt,
        "probe_timeout_seconds": timeout_seconds,
        "result_counts": result_counts,
        "owner_mapped_slots": sum(1 for row in rows if row.get("owner_label") or row.get("owner_email") or row.get("owner_name")),
        "last_probe_at": latest_probe_at,
        "note": "Probe-all sends one live low-volume request to each selected 1min slot and updates slot evidence.",
        "slots": rows,
    }


def _provider_health_report() -> dict[str, object]:
    _load_provider_ledgers_once()
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
        account_name = _provider_account_name("onemin", key_names=onemin_key_names, key=key)
        slot_name = _onemin_key_slot_from_snapshot(key, key_names=onemin_key_names)
        slot_role = _onemin_slot_role_for_key(key, active_keys=onemin_active_keys, reserve_keys=onemin_reserve_keys)
        owner = _onemin_owner_record_for_slot(api_key=key, account_name=account_name, slot=slot_name)
        latest_probe = _latest_onemin_probe_event(account_name=account_name)
        estimated_remaining_credits, estimated_credit_basis = _estimated_onemin_remaining_credits(
            state_label=slot_state,
            state=key_state,
        )
        latest_balance = _latest_provider_balance_snapshot(provider_key="onemin", account_name=account_name)
        observed_spend = _observed_onemin_spend(api_key=key)
        observed_success_count = _observed_onemin_request_count(api_key=key)
        next_retry_at = 0.0
        if key_state.quarantine_until > now:
            next_retry_at = float(key_state.quarantine_until)
        elif key_state.cooldown_until > now:
            next_retry_at = float(key_state.cooldown_until)
        onemin_slots.append(
            {
                "slot": slot_name,
                "configured": bool(key),
                "account_name": account_name,
                "slot_env_name": account_name,
                "slot_role": slot_role,
                "owner_label": str(owner.get("owner_label") or ""),
                "owner_name": str(owner.get("owner_name") or ""),
                "owner_email": str(owner.get("owner_email") or ""),
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
                "max_credits": _onemin_max_credits_per_key(),
                "last_balance_observed_at": latest_balance.happened_at if latest_balance is not None else None,
                "last_balance_source": latest_balance.source if latest_balance is not None else None,
                "topup_detected": bool(latest_balance.topup_detected) if latest_balance is not None else False,
                "topup_delta": latest_balance.topup_delta if latest_balance is not None else None,
                "observed_consumed_credits": observed_spend,
                "observed_success_count": observed_success_count,
                "next_retry_at": next_retry_at or None,
                "upstream_reset_unknown": bool(credit_state and credit_state.get("remaining_credits") == 0),
                "last_probe_at": latest_probe.happened_at if latest_probe is not None else None,
                "last_probe_result": latest_probe.result if latest_probe is not None else None,
                "last_probe_detail": latest_probe.detail if latest_probe is not None else "",
                "last_probe_model": latest_probe.model if latest_probe is not None else "",
                "last_probe_latency_ms": latest_probe.latency_ms if latest_probe is not None else None,
                "last_probe_source": latest_probe.source if latest_probe is not None else "",
            }
        )

    onemin_max_total = _onemin_max_credits_total(len(onemin_slots))
    onemin_known_remaining_total = sum(
        int(slot.get("estimated_remaining_credits") or 0)
        for slot in onemin_slots
        if slot.get("estimated_remaining_credits") is not None
    )
    onemin_unknown_slots = sum(1 for slot in onemin_slots if slot.get("estimated_remaining_credits") is None)
    onemin_burn_summary = _onemin_burn_summary(
        now=now,
        estimated_remaining_credits_total=onemin_known_remaining_total,
    )
    onemin_remaining_percent = None
    if onemin_max_total > 0 and onemin_unknown_slots == 0:
        onemin_remaining_percent = round((onemin_known_remaining_total / onemin_max_total) * 100.0, 2)
    actual_snapshots = [
        snapshot
        for snapshot in _recent_topup_events(provider_key="onemin", limit=512)
    ]
    latest_actual_balance_at = None
    with _ONEMIN_USAGE_LOCK:
        for snapshot in _PROVIDER_BALANCE_SNAPSHOTS:
            if snapshot.provider_key != "onemin":
                continue
            if snapshot.basis not in {"actual_ui_probe", "actual_provider_api"}:
                continue
            latest_actual_balance_at = max(latest_actual_balance_at or 0.0, snapshot.happened_at)
    balance_basis_counts: dict[str, int] = {}
    for slot in onemin_slots:
        basis = str(slot.get("estimated_credit_basis") or "unknown_unprobed")
        balance_basis_counts[basis] = balance_basis_counts.get(basis, 0) + 1
    balance_basis_summary = ",".join(sorted(balance_basis_counts.keys())) if balance_basis_counts else "unknown_unprobed"
    probe_result_counts: dict[str, int] = {}
    last_probe_at = None
    owner_mapped_slots = 0
    for slot in onemin_slots:
        if slot.get("owner_label") or slot.get("owner_name") or slot.get("owner_email"):
            owner_mapped_slots += 1
        probe_result = str(slot.get("last_probe_result") or "").strip()
        if probe_result:
            probe_result_counts[probe_result] = probe_result_counts.get(probe_result, 0) + 1
        probe_time = slot.get("last_probe_at")
        if probe_time is not None:
            last_probe_at = max(float(probe_time), float(last_probe_at or 0.0))

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
                "estimated_remaining_credits_total": onemin_known_remaining_total,
                "max_credits_total": onemin_max_total,
                "max_credits_per_key": _onemin_max_credits_per_key(),
                "unknown_balance_slots": onemin_unknown_slots,
                "last_actual_balance_at": latest_actual_balance_at,
                "last_probe_at": last_probe_at,
                "owner_mapped_slots": owner_mapped_slots,
                "balance_basis_summary": balance_basis_summary,
                "balance_basis_counts": balance_basis_counts,
                "probe_result_counts": probe_result_counts,
                "credit_estimation_mode": "actual_or_observed_or_estimated_else_unknown_unprobed",
                "max_requests_per_hour": onemin_max_requests_per_hour,
                "max_credits_per_hour": onemin_max_credits_per_hour,
                "max_credits_per_day": onemin_max_credits_per_day,
                "recent_topup_events": [
                    {
                        "happened_at": item.happened_at,
                        "account_name": item.account_name,
                        "topup_delta": item.topup_delta,
                        "basis": item.basis,
                        "source": item.source,
                    }
                    for item in actual_snapshots[:10]
                ],
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
