from __future__ import annotations

"""Runtime support for EA audiobook synthesis through Unmixr short TTS.

This module owns no clone, persona, remembrance, or publication behavior.
"""

import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time

import requests
from fastapi import HTTPException


_OPENVOICE_TIMEOUT_ENV = "OPENVOICE_TIMEOUT_SECONDS"

_OPENVOICE_DEFAULT_TIMEOUT_SECONDS = 180

_UNMIXR_API_KEY_ENV = "UNMIXR_API_KEY"

_UNMIXR_API_KEY_FALLBACK_PREFIX = "UNMIXR_API_KEY_FALLBACK_"

_UNMIXR_API_KEYS_ENV = "UNMIXR_API_KEYS"

_UNMIXR_SLOT_SELECTOR_ENABLED_ENV = "EA_UNMIXR_SLOT_SELECTOR_ENABLED"

_UNMIXR_SLOT_SELECTOR_STATE_FILE_ENV = "EA_UNMIXR_SLOT_SELECTOR_STATE_FILE"

_UNMIXR_SLOT_COOLDOWN_DEFAULT_SECONDS_ENV = "EA_UNMIXR_SLOT_COOLDOWN_DEFAULT_SECONDS"

_UNMIXR_SLOT_COOLDOWN_MAX_SECONDS_ENV = "EA_UNMIXR_SLOT_COOLDOWN_MAX_SECONDS"

_UNMIXR_VOICE_ID_ENV = "UNMIXR_VOICE_ID"

_UNMIXR_LANGUAGE_ENV = "UNMIXR_LANGUAGE"

_UNMIXR_SPEAKING_RATE_ENV = "UNMIXR_SPEAKING_RATE"

_UNMIXR_SPEAKING_PITCH_ENV = "UNMIXR_SPEAKING_PITCH"

_UNMIXR_SPEAKING_VOLUME_ENV = "UNMIXR_SPEAKING_VOLUME"

_UNMIXR_PRONUNCIATION_DICT_ENV = "EA_AUDIOBOOK_UNMIXR_PRONUNCIATION_DICT_JSON"

_UNMIXR_BASE_URL = "https://unmixr.com/api/v1"

_UNMIXR_RETRY_AFTER_RE = re.compile(
    r"(?:available|retry|try again)[^0-9]{0,40}(\d{1,6})\s*seconds?",
    re.IGNORECASE,
)

_UNMIXR_PUBLIC_ERROR_OPERATIONS = frozenset({"clone", "clone_delete", "request", "tts", "voice_lookup"})

def openvoice_timeout_seconds() -> int:
    raw = str(os.environ.get(_OPENVOICE_TIMEOUT_ENV) or "").strip()
    try:
        value = int(raw) if raw else _OPENVOICE_DEFAULT_TIMEOUT_SECONDS
    except ValueError:
        value = _OPENVOICE_DEFAULT_TIMEOUT_SECONDS
    return max(15, min(value, 900))

def unmixr_api_key() -> str:
    return str(os.environ.get(_UNMIXR_API_KEY_ENV) or "").strip()

def _split_unmixr_api_keys(value: object) -> tuple[str, ...]:
    return tuple(item.strip() for item in re.split(r"[\s,;]+", str(value or "")) if item.strip())

def _unmixr_api_key_slots() -> tuple[tuple[str, str], ...]:
    rows: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add_slot(name: str, value: object) -> None:
        key = str(value or "").strip()
        if not key or key in seen:
            return
        seen.add(key)
        rows.append((name, key))

    primary = unmixr_api_key()
    add_slot(_UNMIXR_API_KEY_ENV, primary)

    fallback_names = sorted(
        (
            name
            for name in os.environ
            if name.startswith(_UNMIXR_API_KEY_FALLBACK_PREFIX)
            and name[len(_UNMIXR_API_KEY_FALLBACK_PREFIX):].isdigit()
        ),
        key=lambda name: int(name[len(_UNMIXR_API_KEY_FALLBACK_PREFIX):]),
    )
    for env_name in fallback_names:
        add_slot(env_name, os.environ.get(env_name))

    for index, key in enumerate(_split_unmixr_api_keys(os.environ.get(_UNMIXR_API_KEYS_ENV)), start=1):
        add_slot(f"{_UNMIXR_API_KEYS_ENV}_{index}", key)
    return tuple(rows)

def unmixr_api_key_slot_count() -> int:
    return len(_unmixr_api_key_slots())

def _normalize_unmixr_account_slot(value: object) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    if normalized == _UNMIXR_API_KEY_ENV:
        return normalized
    if re.fullmatch(r"UNMIXR_API_KEY_FALLBACK_[1-9][0-9]*", normalized):
        return normalized
    if re.fullmatch(r"UNMIXR_API_KEYS_[1-9][0-9]*", normalized):
        return normalized
    raise HTTPException(status_code=409, detail="unmixr_account_slot_invalid")

def _env_bool(name: str, default: bool) -> bool:
    raw = str(os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default

def _env_int(name: str, default: int, *, minimum: int = 0, maximum: int = 86_400) -> int:
    try:
        parsed = int(str(os.environ.get(name) or "").strip() or default)
    except ValueError:
        parsed = default
    return max(minimum, min(int(parsed), maximum))

def _unmixr_slot_selector_enabled() -> bool:
    return _env_bool(_UNMIXR_SLOT_SELECTOR_ENABLED_ENV, True)

def _unmixr_slot_state_file() -> Path:
    configured = str(os.environ.get(_UNMIXR_SLOT_SELECTOR_STATE_FILE_ENV) or "").strip()
    if configured:
        return Path(configured).expanduser()
    ledger_dir = str(os.environ.get("EA_RESPONSES_PROVIDER_LEDGER_DIR") or "").strip()
    if ledger_dir:
        return Path(ledger_dir).expanduser() / "unmixr_slot_selector.json"
    return Path(tempfile.gettempdir()) / "ea_unmixr_slot_selector.json"

def _load_unmixr_slot_state() -> dict[str, object]:
    if not _unmixr_slot_selector_enabled():
        return {}
    path = _unmixr_slot_state_file()
    if not path.is_file():
        return {}
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}

def _write_unmixr_slot_state(state: dict[str, object]) -> None:
    if not _unmixr_slot_selector_enabled():
        return
    path = _unmixr_slot_state_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp_path.replace(path)
    except OSError:
        return

def _unmixr_slot_cooldown_max_seconds() -> int:
    return _env_int(_UNMIXR_SLOT_COOLDOWN_MAX_SECONDS_ENV, 3600, minimum=0, maximum=86_400)

def _unmixr_retry_after_seconds_from_response(response: requests.Response) -> int:
    retry_after = str(getattr(response, "headers", {}).get("Retry-After") or "").strip()
    if retry_after.isdigit():
        return int(retry_after)
    detail = _unmixr_response_error_detail(response)
    match = _UNMIXR_RETRY_AFTER_RE.search(detail)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            return 0
    return 0

def _unmixr_slot_cooldown_seconds(response: requests.Response | None = None, *, exception: BaseException | None = None) -> int:
    max_seconds = _unmixr_slot_cooldown_max_seconds()
    if max_seconds <= 0:
        return 0
    if response is not None:
        retry_after = _unmixr_retry_after_seconds_from_response(response)
        if retry_after > 0:
            return max(1, min(retry_after, max_seconds))
        status_code = int(getattr(response, "status_code", 0) or 0)
        detail = _unmixr_response_error_detail(response).lower()
        if status_code == 429 or "throttle" in detail or "rate" in detail:
            return min(_env_int(_UNMIXR_SLOT_COOLDOWN_DEFAULT_SECONDS_ENV, 900, minimum=1, maximum=max_seconds), max_seconds)
        if status_code in {401, 402, 403} or any(
            marker in detail
            for marker in ("insufficient", "balance", "quota", "credit", "billing", "payment")
        ):
            return min(_env_int(_UNMIXR_SLOT_COOLDOWN_DEFAULT_SECONDS_ENV, 900, minimum=1, maximum=max_seconds), max_seconds)
        if status_code in {500, 502, 503, 504}:
            return min(60, max_seconds)
    if exception is not None:
        return min(60, max_seconds)
    return 0

def _rotate_unmixr_slots(slots: list[tuple[str, str]], last_slot_name: str) -> list[tuple[str, str]]:
    if not slots or not last_slot_name:
        return slots
    names = [name for name, _key in slots]
    if last_slot_name not in names:
        return slots
    index = names.index(last_slot_name) + 1
    return slots[index:] + slots[:index]

def _selected_unmixr_slots(slots: tuple[tuple[str, str], ...]) -> list[tuple[str, str]]:
    if not _unmixr_slot_selector_enabled():
        return list(slots)
    state = _load_unmixr_slot_state()
    slot_state = dict(state.get("slots") or {})
    now = time.time()
    available: list[tuple[str, str]] = []
    cooling: list[tuple[float, tuple[str, str]]] = []
    for slot in slots:
        name = slot[0]
        item = dict(slot_state.get(name) or {})
        cooldown_until = float(item.get("cooldown_until_epoch") or 0)
        if cooldown_until > now:
            cooling.append((cooldown_until, slot))
        else:
            available.append(slot)
    if available:
        return _rotate_unmixr_slots(available, str(state.get("last_slot_name") or ""))
    if cooling:
        wait_seconds = max(1, int(min(item[0] for item in cooling) - now))
        raise HTTPException(status_code=429, detail=f"unmixr_slots_cooling_down:{wait_seconds}")
    return list(slots)

def _record_unmixr_slot_result(
    slot_name: str,
    *,
    ok: bool,
    response: requests.Response | None = None,
    exception: BaseException | None = None,
) -> None:
    if not _unmixr_slot_selector_enabled() or not slot_name:
        return
    state = _load_unmixr_slot_state()
    slots = dict(state.get("slots") or {})
    item = dict(slots.get(slot_name) or {})
    now = time.time()
    item["updated_at_epoch"] = now
    item["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
    if ok:
        item.pop("cooldown_until_epoch", None)
        item.pop("cooldown_until", None)
        item.pop("last_error", None)
        item.pop("last_error_body_sha256", None)
        item.pop("last_error_code", None)
        item["last_status"] = "ok"
        state["last_slot_name"] = slot_name
    else:
        cooldown_seconds = _unmixr_slot_cooldown_seconds(response, exception=exception)
        if cooldown_seconds > 0:
            cooldown_until = now + cooldown_seconds
            item["cooldown_until_epoch"] = cooldown_until
            item["cooldown_until"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(cooldown_until))
        item["last_status"] = "error"
        if response is not None:
            item["last_status_code"] = int(getattr(response, "status_code", 0) or 0)
            item.pop("last_error", None)
            item["last_error_code"] = _unmixr_response_public_error(response)
            body_sha256 = _unmixr_response_error_sha256(response)
            if body_sha256:
                item["last_error_body_sha256"] = body_sha256
        elif exception is not None:
            item.pop("last_error", None)
            item.pop("last_error_body_sha256", None)
            item["last_error_code"] = "unmixr_upstream_unreachable"
    slots[slot_name] = item
    state["slots"] = slots
    state["updated_at"] = item["updated_at"]
    _write_unmixr_slot_state(state)

def unmixr_default_voice_id() -> str:
    return str(os.environ.get(_UNMIXR_VOICE_ID_ENV) or "").strip()

def unmixr_language(default: str = "de") -> str:
    preferred = str(default or "").strip()
    configured = str(os.environ.get(_UNMIXR_LANGUAGE_ENV) or "").strip()
    selected = preferred or configured or "de"
    normalized = selected.replace("_", "-").strip()
    if not normalized:
        return "de"
    # Unmixr's short-TTS and cloned-voice metadata use ISO 639 language
    # identifiers (for example ``de``), while EA audiobook configuration values are
    # BCP-47 locales (for example ``de-AT``). Sending the locale through made
    # clone renders materially less stable, so keep the regional locale in the
    # product config and project only its base language to the provider.
    language = normalized.split("-", 1)[0].strip().lower()
    return language or "de"

def unmixr_speaking_rate() -> str:
    return str(os.environ.get(_UNMIXR_SPEAKING_RATE_ENV) or "medium").strip() or "medium"

def unmixr_speaking_pitch() -> str:
    return str(os.environ.get(_UNMIXR_SPEAKING_PITCH_ENV) or "low").strip() or "low"

def unmixr_speaking_volume() -> str:
    return str(os.environ.get(_UNMIXR_SPEAKING_VOLUME_ENV) or "medium").strip() or "medium"

def unmixr_pronunciation_dict(value: object | None = None) -> dict[str, str]:
    source = value
    if source is None:
        raw = str(os.environ.get(_UNMIXR_PRONUNCIATION_DICT_ENV) or "").strip()
        if not raw:
            return {}
        try:
            source = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=409, detail="unmixr_pronunciation_dict_invalid") from exc
    if not isinstance(source, dict):
        raise HTTPException(status_code=409, detail="unmixr_pronunciation_dict_invalid")
    normalized: dict[str, str] = {}
    for raw_term, raw_pronunciation in source.items():
        term = " ".join(str(raw_term or "").split()).strip()
        pronunciation = " ".join(str(raw_pronunciation or "").split()).strip()
        if not term or not pronunciation:
            raise HTTPException(status_code=409, detail="unmixr_pronunciation_dict_invalid")
        if len(term) > 160 or len(pronunciation) > 320:
            raise HTTPException(status_code=409, detail="unmixr_pronunciation_dict_entry_too_long")
        normalized[term] = pronunciation
        if len(normalized) > 256:
            raise HTTPException(status_code=409, detail="unmixr_pronunciation_dict_too_large")
    return normalized

def _unmixr_headers(api_key: str | None = None) -> dict[str, str]:
    api_key = str(api_key or unmixr_api_key()).strip()
    if not api_key:
        raise HTTPException(status_code=503, detail="unmixr_api_key_missing")
    return {"Authorization": f"Bearer {api_key}"}

def _unmixr_response_error_detail(response: requests.Response) -> str:
    try:
        payload = response.json()
    except Exception:
        payload = {}
    if isinstance(payload, dict):
        if response.ok and str(payload.get("audio_url") or "").strip():
            return ""
        detail = str(payload.get("detail") or payload.get("error") or payload.get("message") or "").strip()
        if detail:
            return detail
    return str(getattr(response, "text", "") or "").strip()

def _unmixr_response_error_sha256(response: requests.Response) -> str:
    detail = _unmixr_response_error_detail(response)
    if not detail:
        return ""
    return hashlib.sha256(detail.encode("utf-8")).hexdigest()

def _unmixr_response_error_class(response: requests.Response) -> str:
    status_code = int(getattr(response, "status_code", 0) or 0)
    detail = _unmixr_response_error_detail(response).lower()
    if status_code == 429 or any(
        marker in detail
        for marker in ("rate limit", "rate-limit", "too many requests", "throttl")
    ):
        return "rate_limited"
    if status_code == 402 or any(
        marker in detail
        for marker in (
            "insufficient api balance",
            "insufficient balance",
            "not enough credit",
            "credit balance",
            "quota exceeded",
            "billing required",
            "payment required",
        )
    ):
        return "balance_exhausted"
    if status_code == 413 or any(
        marker in detail
        for marker in (
            "character limit",
            "ensure this value has at most",
            "exceeds maximum",
            "input too long",
            "max text",
            "maximum text",
            "payload too large",
            "request entity too large",
            "string should have at most",
            "text too long",
            "too many characters",
        )
    ):
        return "input_too_long"
    if status_code == 401:
        return "authentication_failed"
    if status_code == 403:
        return "access_denied"
    if status_code in {400, 404, 409, 422}:
        return "invalid_request"
    if status_code in {500, 502, 503, 504}:
        return "upstream_unavailable"
    return "failed"

def _unmixr_should_try_next_slot(response: requests.Response) -> bool:
    status_code = int(response.status_code or 0)
    if status_code in {401, 402, 403, 429, 500, 502, 503, 504}:
        return True
    try:
        payload = response.json()
    except Exception:
        payload = {}
    if response.ok and isinstance(payload, dict) and str(payload.get("audio_url") or "").strip():
        return False
    detail = _unmixr_response_error_detail(response).lower()
    return any(
        marker in detail
        for marker in (
            "insufficient api balance",
            "insufficient balance",
            "prebuilt character",
            "quota",
            "credit",
            "billing",
            "payment",
        )
    )

def _unmixr_response_public_error(response: requests.Response, *, operation: str = "request") -> str:
    normalized_operation = operation if operation in _UNMIXR_PUBLIC_ERROR_OPERATIONS else "request"
    error_class = _unmixr_response_error_class(response)
    public_error = f"unmixr_{normalized_operation}_{error_class}"
    if error_class == "rate_limited":
        retry_after = _unmixr_retry_after_seconds_from_response(response)
        if retry_after > 0:
            public_error = f"{public_error}:retry_after_{retry_after}_seconds"
    return public_error

def _unmixr_request(
    *,
    method: str,
    path: str,
    json_payload: dict[str, object] | None = None,
    files: list[tuple[str, object]] | None = None,
    data: dict[str, str] | None = None,
    account_slot: str | None = None,
) -> requests.Response:
    slots = _unmixr_api_key_slots()
    if not slots:
        raise HTTPException(status_code=503, detail="unmixr_api_key_missing")
    requested_slot = _normalize_unmixr_account_slot(account_slot)
    last_response: requests.Response | None = None
    last_exception: requests.RequestException | None = None
    if requested_slot:
        selected_slots = [
            slot for slot in slots if slot[0] == requested_slot
        ]
        if not selected_slots:
            raise HTTPException(status_code=503, detail="unmixr_account_slot_missing")
    else:
        selected_slots = _selected_unmixr_slots(slots)
    for index, (slot_name, api_key) in enumerate(selected_slots, start=1):
        try:
            response = requests.request(
                method=method,
                url=f"{_UNMIXR_BASE_URL}{path}",
                headers=_unmixr_headers(api_key),
                json=json_payload,
                files=files,
                data=data,
                timeout=openvoice_timeout_seconds(),
            )
        except requests.RequestException as exc:
            last_exception = exc
            _record_unmixr_slot_result(slot_name, ok=False, exception=exc)
            if index < len(selected_slots):
                continue
            break
        last_response = response
        if _unmixr_should_try_next_slot(response):
            _record_unmixr_slot_result(slot_name, ok=False, response=response)
            if index < len(selected_slots):
                continue
            return response
        if response.ok:
            _record_unmixr_slot_result(slot_name, ok=True, response=response)
            return response
        if index < len(selected_slots) and _unmixr_should_try_next_slot(response):
            continue
        return response
    if last_response is not None:
        return last_response
    detail = type(last_exception).__name__ if last_exception else "unknown"
    raise HTTPException(status_code=502, detail=f"unmixr_upstream_unreachable:{detail}")

def piper_fast_synthesize_request(*, text: str, lang: str, base_voice_variant: str) -> tuple[bytes, str]:
    raise HTTPException(status_code=410, detail="openvoice_tts_pipeline_removed")

def _downloaded_audio_content_type(*, payload: bytes, declared_content_type: object) -> str:
    normalized = (
        str(declared_content_type or "audio/mpeg").split(";", 1)[0].strip().lower()
        or "audio/mpeg"
    )
    if normalized.startswith("audio/"):
        return normalized
    if payload.startswith(b"RIFF") and payload[8:12] == b"WAVE":
        return "audio/wav"
    if payload.startswith(b"ID3") or (
        len(payload) >= 2
        and payload[0] == 0xFF
        and payload[1] & 0xE0 == 0xE0
    ):
        return "audio/mpeg"
    if payload.startswith(b"OggS"):
        return "audio/ogg"
    if payload.startswith(b"fLaC"):
        return "audio/flac"
    return normalized

def unmixr_synthesize_request(
    *,
    text: str,
    voice_id: str,
    lang: str,
    speaking_rate: str | None = None,
    speaking_pitch: str | None = None,
    speaking_volume: str | None = None,
    pronunciation_dict: dict[str, str] | None = None,
    account_slot: str | None = None,
) -> tuple[bytes, str]:
    normalized_voice_id = str(voice_id or "").strip()
    if not normalized_voice_id:
        raise HTTPException(status_code=409, detail="tts_voice_id_missing")
    request_payload: dict[str, object] = {
        "text": text,
        "voice_id": normalized_voice_id,
        "language": unmixr_language(lang),
        "response_type": "url",
        "speaking_rate": str(speaking_rate or unmixr_speaking_rate()).strip() or unmixr_speaking_rate(),
        "speaking_pitch": str(speaking_pitch or unmixr_speaking_pitch()).strip() or unmixr_speaking_pitch(),
        "speaking_volume": str(speaking_volume or unmixr_speaking_volume()).strip() or unmixr_speaking_volume(),
    }
    effective_pronunciation_dict = (
        unmixr_pronunciation_dict(pronunciation_dict)
        if pronunciation_dict is not None
        else {}
    )
    if effective_pronunciation_dict:
        request_payload["pronunciation_dict"] = effective_pronunciation_dict
    response = _unmixr_request(
        method="POST",
        path="/short-tts/",
        json_payload=request_payload,
        account_slot=account_slot,
    )
    try:
        payload = response.json()
    except Exception:
        payload = {}
    if response.status_code >= 400 or not response.ok:
        detail = _unmixr_response_public_error(response, operation="tts")
        raise HTTPException(status_code=502, detail=f"{detail}:{response.status_code}")
    audio_url = str(payload.get("audio_url") or "").strip()
    if not audio_url:
        error_class = _unmixr_response_error_class(response)
        if error_class in {"balance_exhausted", "input_too_long", "rate_limited"}:
            detail = _unmixr_response_public_error(response, operation="tts")
            raise HTTPException(status_code=502, detail=f"{detail}:{response.status_code}")
        raise HTTPException(status_code=502, detail=f"unmixr_tts_no_audio_url:{response.status_code}")
    try:
        audio_response = requests.get(audio_url, timeout=openvoice_timeout_seconds())
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"unmixr_audio_fetch_failed:{type(exc).__name__}") from exc
    if audio_response.status_code >= 400 or not audio_response.ok or not audio_response.content:
        raise HTTPException(status_code=502, detail=f"unmixr_audio_fetch_failed:{audio_response.status_code}")
    content_type = _downloaded_audio_content_type(
        payload=audio_response.content,
        declared_content_type=audio_response.headers.get("Content-Type"),
    )
    return audio_response.content, content_type
