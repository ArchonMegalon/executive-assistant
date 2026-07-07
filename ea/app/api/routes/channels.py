from __future__ import annotations

import ast
import concurrent.futures
import contextlib
import hashlib
import hmac
import json
import mimetypes
import os
import re
import subprocess
import tempfile
import time
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta
from importlib import import_module
from pathlib import Path
from typing import Mapping
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Body, Depends, Request
from fastapi import HTTPException
from pydantic import BaseModel, Field

from app.api.dependencies import RequestContext
from app.api.dependencies import get_container
from app.channels.telegram.adapter import TelegramObservationAdapter
from app.container import AppContainer
from app.domain.models import ToolInvocationRequest
from app.product.projections.common import compact_text
from app.product import service as product_service_module
from app.product.service import build_product_service
from app.services import audiobook_access_approval
from app.services import google_oauth as google_oauth_service
from app.services import telegram_business_signal_ingest
from app.services import whatsapp_inbound_actions
from app.services import whatsapp_delivery_router
from app.services.audiobook_epub_pipeline import (
    _record_audiobookshelf_public_share_telegram_delivery,
    _telegram_audiobook_voice_samples_pending_delivery,
    apply_audiobook_voice_audition_action,
    audiobook_jobs_root,
    audiobook_runtime_preflight,
    audiobook_voice_audition_sample_messages,
    create_job_from_epub,
    download_telegram_epub,
    prepare_audiobook_voice_audition,
    ensure_audiobook_playback_acceptance_callback,
    is_epub_document,
    is_telegram_epub_download_url_allowed,
    process_telegram_epub_audiobook_job,
    record_audiobook_playback_acceptance_by_callback_token,
    record_audiobook_voice_sample_delivery,
    telegram_epub_reply_text,
    telegram_epub_skill_enabled,
)
from app.services.ltd_runtime_catalog import LtdRuntimeCatalogService
from app.services.ltd_runtime_skill_projection import projected_task_key, projected_task_key_for_request
from app.services.property_billing import property_commercial_snapshot
from app.services.public_urls import ea_public_app_base_url
from app.services.proactive_ooda_approval_outcomes import default_proactive_ooda_artifact_dir
from app.services.proactive_ooda_context_grounding import ground_digest_for_principal
from app.services.proactive_ooda_flat_search_policy import text_mentions_flat_property_search
from app.services.proactive_ooda_receipts import persist_proactive_ooda_receipt
from app.services.proactive_ooda_safe_work import (
    build_safe_work_result,
    default_safe_work_result_dir,
    persist_safe_work_results_from_paths,
)
from app.services.proactive_ooda_telegram_policy import (
    approval_request_needs_telegram_user_action,
    telegram_ooda_text_is_internal_noise,
)
from app.services.proactive_ooda_service import ProactiveOodaService, build_run_receipt
from app.services.proactive_ooda_stage_packets import build_stage_packets, default_stage_packet_dir, persist_stage_packets
from app.services.proactive_ooda_teable_sync import sync_proactive_ooda_to_teable, teable_sync_enabled
from app.services.proactive_signal_discovery import observation_row_to_signal
from app.services.telegram_video_effects import render_local_source_video_edit
from app.services.telegram_video_effects import extract_source_video_reference_packet
from app.services.telegram_video_effects import source_video_edit_enabled
from app.services.telegram_video_effects import source_video_edit_supported
from app.services.telegram_video_effects import supported_source_video_edit_summary
from app.services.telegram_session_service import (
    TelegramLocalResolver,
    TelegramReplyMemoryState,
    TelegramTurnContext,
    TelegramTurnDecision,
    _telegram_file_download_url,
    _hydrate_instructional_video_transcript,
    build_turn_context,
    resolve_telegram_message_payload,
    run_local_resolvers,
)
from app.services.telegram_onboarding_service import TELEGRAM_IDENTITY_CONNECTOR, TELEGRAM_OFFICIAL_BOT_CONNECTOR
from app.services.telegram_delivery import send_telegram_video_for_principal
from app.services.telegram_delivery import decode_telegram_feedback_callback_data
from app.services.telegram_delivery import record_telegram_video_delivery_receipt as shared_record_telegram_video_delivery_receipt
from app.services.telegram_delivery import telegram_video_source_receipt_context
from app.services.proactive_ooda_telegram_approval import (
    apply_proactive_ooda_telegram_approval_callback,
    build_reversible_execution_approval_prompt,
    decode_proactive_ooda_telegram_callback,
    execute_proactive_ooda_action,
    prepare_proactive_ooda_telegram_approval,
    record_proactive_ooda_telegram_approval_delivery,
)

router = APIRouter(prefix="/v1/channels", tags=["channels"])
_telegram = TelegramObservationAdapter()
_SAFE_MATH_RE = re.compile(r"^[0-9\.\+\-\*\/\(\)\s=\?]+$")
_TELEGRAM_ASSISTANT_ACK = "Let me check that and get back to you here."


def _telegram_env_int(env_key: str, fallback: int) -> int:
    raw = str(os.getenv(env_key) or "").strip()
    try:
        return max(int(raw or str(fallback)), 1)
    except Exception:
        return max(fallback, 1)


_TELEGRAM_ASYNC_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="telegram-ea")
_TELEGRAM_PAID_RENDER_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=_telegram_env_int("EA_TELEGRAM_PAID_RENDER_WORKERS", 2),
    thread_name_prefix="telegram-ea-paid-render",
)
_TELEGRAM_FREE_RENDER_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=_telegram_env_int("EA_TELEGRAM_FREE_RENDER_WORKERS", 1),
    thread_name_prefix="telegram-ea-free-render",
)
_TELEGRAM_WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
_URL_RE = re.compile(r"https?://[^\s<>\"]+")
_EA_ROOT = Path(__file__).resolve().parents[3]
_MATH_WORD_NUMBERS = {
    "zero": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "ten": "10",
    "eleven": "11",
    "twelve": "12",
}


def _assistant_owner_label() -> str:
    for env_key in (
        "EA_ASSISTANT_OWNER_LABEL",
        "EA_WHATSAPP_WEB_DEFAULT_TENANT_NAME",
        "EA_WHATSAPP_DEFAULT_TENANT_NAME",
        "EA_WHATSAPP_WEB_DEFAULT_DISPLAY_NAME",
        "EA_WHATSAPP_DEFAULT_DISPLAY_NAME",
    ):
        value = str(os.getenv(env_key) or "").strip()
        if value:
            return value
    return "the principal"


def _assistant_owner_possessive_label() -> str:
    owner = _assistant_owner_label()
    if owner == "the principal":
        return "the principal's"
    return f"{owner}'" if owner.endswith("s") else f"{owner}'s"


def _telegram_saved_flow_reply_prefix() -> str:
    return f"I got it. I saved this in {_assistant_owner_possessive_label()} assistant flow"
_TELEGRAM_MONTH_ALIASES = {
    "jan": 1,
    "january": 1,
    "jänner": 1,
    "jaenner": 1,
    "januar": 1,
    "feb": 2,
    "february": 2,
    "februar": 2,
    "mar": 3,
    "march": 3,
    "märz": 3,
    "maerz": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "mai": 5,
    "jun": 6,
    "june": 6,
    "juni": 6,
    "jul": 7,
    "july": 7,
    "juli": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "okt": 10,
    "october": 10,
    "oktober": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "dez": 12,
    "december": 12,
    "dezember": 12,
}

def _responses_route_module():
    return import_module("app.api.routes.responses")


responses_route = _responses_route_module()


def _telegram_bot_registry() -> dict[str, dict[str, object]]:
    registry: dict[str, dict[str, object]] = {}
    raw_registry = str(os.getenv("EA_TELEGRAM_BOT_REGISTRY_JSON") or "").strip()
    if raw_registry:
        try:
            parsed = json.loads(raw_registry)
        except json.JSONDecodeError:
            parsed = {}
        if isinstance(parsed, dict):
            for raw_key, raw_value in parsed.items():
                key = str(raw_key or "").strip()
                if not key or not isinstance(raw_value, dict):
                    continue
                token = str(raw_value.get("token") or "").strip()
                if not token:
                    continue
                registry[key] = {
                    "bot_key": key,
                    "token": token,
                    "handle": str(raw_value.get("handle") or "").strip(),
                    "secret": str(raw_value.get("secret") or "").strip(),
                    "default_principal_id": str(raw_value.get("default_principal_id") or "").strip(),
                    "auto_bind_unknown_chat": bool(raw_value.get("auto_bind_unknown_chat")),
                    "preferred_onemin_labels": tuple(
                        str(item or "").strip()
                        for item in list(raw_value.get("preferred_onemin_labels") or [])
                        if str(item or "").strip()
                    ),
                }
    default_token = str(os.getenv("EA_TELEGRAM_BOT_TOKEN") or "").strip()
    if default_token:
        registry.setdefault(
            "default",
            {
                "bot_key": "default",
                "token": default_token,
                "handle": str(os.getenv("EA_TELEGRAM_BOT_HANDLE") or "").strip(),
                "secret": str(os.getenv("EA_TELEGRAM_INGEST_SECRET") or "").strip(),
                "default_principal_id": str(os.getenv("EA_TELEGRAM_DEFAULT_PRINCIPAL_ID") or "").strip(),
                "auto_bind_unknown_chat": _telegram_auto_bind_unknown_chat_enabled(),
                "preferred_onemin_labels": (),
            },
        )
    return registry


def _telegram_default_preferred_onemin_labels() -> tuple[str, ...]:
    raw = str(os.getenv("EA_TELEGRAM_RESPONSES_PREFERRED_ONEMIN_LABELS") or "").strip()
    if not raw:
        return ()
    labels: list[str] = []
    for item in raw.split(","):
        normalized = str(item or "").strip()
        if normalized and normalized not in labels:
            labels.append(normalized)
    return tuple(labels)


def _resolve_telegram_bot_config(*, bot_key: str = "", provided_secret: str = "", header_secret: str = "") -> dict[str, object]:
    registry = _telegram_bot_registry()
    normalized_key = str(bot_key or "").strip()
    if normalized_key:
        config = dict(registry.get(normalized_key) or {})
        if not config:
            raise HTTPException(status_code=404, detail="telegram_bot_not_found")
        return config
    if not registry:
        return {}
    for config in registry.values():
        secret = str(config.get("secret") or "").strip()
        if not secret:
            continue
        for candidate in (str(header_secret or "").strip(), str(provided_secret or "").strip()):
            if candidate and hmac.compare_digest(candidate, secret):
                return dict(config)
    return dict(registry.get("default") or next(iter(registry.values())))


def _require_telegram_ingest_secret(*, config: dict[str, object], provided: str, header_value: str) -> None:
    expected = str(config.get("secret") or os.getenv("EA_TELEGRAM_INGEST_SECRET") or "").strip()
    if not expected:
        return
    candidates = (str(header_value or "").strip(), str(provided or "").strip())
    for candidate in candidates:
        if candidate and hmac.compare_digest(candidate, expected):
            return
    raise HTTPException(status_code=403, detail="telegram_secret_invalid")


def _resolve_telegram_principal(container: AppContainer, chat_id: str, *, bot_key: str = "", bot_handle: str = "") -> str:
    normalized_chat_id = str(chat_id or "").strip()
    if not normalized_chat_id:
        return ""
    matches: list[str] = []
    for connector_name in (TELEGRAM_OFFICIAL_BOT_CONNECTOR, TELEGRAM_IDENTITY_CONNECTOR):
        for binding in container.tool_runtime.list_connector_bindings_for_connector(connector_name, limit=500):
            normalized_status = str(binding.status or "").strip().lower()
            if normalized_status in {"disabled", "inactive", "archived"}:
                continue
            metadata = dict(binding.auth_metadata_json or {})
            metadata_bot_key = str(metadata.get("bot_key") or "").strip()
            metadata_bot_handle = str(metadata.get("bot_handle") or "").strip()
            if bot_key and metadata_bot_key and metadata_bot_key != bot_key:
                continue
            if bot_handle and metadata_bot_handle and metadata_bot_handle != bot_handle:
                continue
            default_chat_ref = str(metadata.get("default_chat_ref") or "").strip()
            external_account_ref = str(binding.external_account_ref or "").strip()
            if normalized_chat_id in {default_chat_ref, external_account_ref}:
                matches.append(
                    _canonical_telegram_principal_id(container, str(binding.principal_id or "").strip())
                    or str(binding.principal_id or "").strip()
                )
    principals = sorted({principal_id for principal_id in matches if str(principal_id or "").strip()})
    if len(principals) == 1:
        return principals[0]
    if len(principals) > 1:
        raise HTTPException(status_code=409, detail="telegram_binding_ambiguous")
    return ""


def _telegram_principal_is_registered_user(container: AppContainer, principal_id: str) -> bool:
    normalized = str(principal_id or "").strip()
    if not normalized:
        return False
    default_principals = {
        value
        for value in (
            _telegram_default_principal_id(),
            _canonical_telegram_principal_id(container, _telegram_default_principal_id()),
        )
        if str(value or "").strip()
    }
    if normalized in default_principals:
        return True
    for connector_name in (TELEGRAM_OFFICIAL_BOT_CONNECTOR, TELEGRAM_IDENTITY_CONNECTOR):
        for binding in container.tool_runtime.list_connector_bindings_for_connector(connector_name, limit=500):
            if str(binding.principal_id or "").strip() != normalized:
                continue
            if str(binding.status or "").strip().lower() not in {"disabled", "inactive", "archived"}:
                return True
    with contextlib.suppress(Exception):
        status = container.onboarding.status(principal_id=normalized)
        normalized_status = str(status.get("status") or "").strip().lower()
        return bool(normalized_status) and normalized_status != "draft"
    return False


def _telegram_property_render_plan_key(container: AppContainer, principal_id: str) -> str:
    normalized_principal = str(principal_id or "").strip()
    if not normalized_principal:
        return "free"
    with contextlib.suppress(Exception):
        status = container.onboarding.status(principal_id=normalized_principal)
        preferences = dict(status.get("property_search_preferences") or {})
        snapshot = property_commercial_snapshot(preferences)
        return str(snapshot.get("current_plan_key") or "free").strip().lower() or "free"
    return "free"


def _telegram_property_render_priority(container: AppContainer, principal_id: str) -> str:
    return "paid" if _telegram_property_render_plan_key(container=container, principal_id=principal_id) in {"plus", "agent"} else "free"


def _canonical_telegram_principal_id(container: AppContainer, principal_id: str) -> str:
    normalized = str(principal_id or "").strip()
    if not normalized:
        return ""
    for candidate in google_oauth_service._principal_alias_candidates(
        container=container,
        principal_ids=(normalized,),
        include_local_user=False,
    ):
        resolved = str(candidate or "").strip()
        if resolved and resolved != normalized and not resolved.startswith("cf-email:"):
            return resolved
    return normalized


def _telegram_default_principal_id() -> str:
    return str(os.getenv("EA_TELEGRAM_DEFAULT_PRINCIPAL_ID") or "").strip()


def _telegram_bot_handle() -> str:
    return str(os.getenv("EA_TELEGRAM_BOT_HANDLE") or "").strip()


def _telegram_auto_bind_unknown_chat_enabled() -> bool:
    normalized = str(os.getenv("EA_TELEGRAM_AUTO_BIND_UNKNOWN_CHAT") or "").strip().lower()
    return normalized in {"1", "true", "yes", "on"}


def _telegram_inline_async_accelerator_enabled() -> bool:
    normalized = str(os.getenv("EA_TELEGRAM_INLINE_ASYNC_ACCELERATOR") or "1").strip().lower()
    return normalized in {"1", "true", "yes", "on"}


def _auto_bind_telegram_chat(container: AppContainer, chat_id: str, *, config: dict[str, object]) -> str:
    normalized_chat_id = str(chat_id or "").strip()
    configured_principal_id = str(config.get("default_principal_id") or _telegram_default_principal_id() or "").strip()
    principal_id = _canonical_telegram_principal_id(container, configured_principal_id) or configured_principal_id
    auto_bind = config.get("auto_bind_unknown_chat")
    if auto_bind is None:
        auto_bind_enabled = _telegram_auto_bind_unknown_chat_enabled()
    else:
        auto_bind_enabled = bool(auto_bind)
    if not normalized_chat_id or not principal_id or not auto_bind_enabled:
        return ""
    registry_principals: set[str] = set()
    for raw_principal_id in (
        str(config.get("default_principal_id") or "").strip(),
        _telegram_default_principal_id(),
    ):
        normalized = str(raw_principal_id or "").strip()
        if not normalized:
            continue
        registry_principals.add(normalized)
        canonical = _canonical_telegram_principal_id(container, normalized)
        if canonical:
            registry_principals.add(canonical)
    if principal_id not in registry_principals and not _telegram_principal_is_registered_user(container=container, principal_id=principal_id):
        return ""
    connector = container.tool_runtime.upsert_connector_binding(
        principal_id=principal_id,
        connector_name=TELEGRAM_IDENTITY_CONNECTOR,
        external_account_ref=normalized_chat_id,
        scope_json={"assistant_surfaces": ["dm"]},
        auth_metadata_json={
            "identity_mode": "bot_webhook",
            "history_mode": "future_only",
            "default_chat_ref": normalized_chat_id,
            "status": "enabled",
            "bot_handle": str(config.get("handle") or _telegram_bot_handle() or "").strip(),
            "bot_key": str(config.get("bot_key") or "").strip(),
            "auto_bound": True,
        },
        status="enabled",
    )
    return str(connector.principal_id or "").strip()


def _telegram_inline_keyboard(button_rows: list[list[tuple[str, str]]]) -> dict[str, object]:
    return {
        "inline_keyboard": [
            [{"text": str(label or "").strip(), "callback_data": str(callback_data or "").strip()} for label, callback_data in row if str(label or "").strip() and str(callback_data or "").strip()]
            for row in button_rows
            if row
        ]
    }


def _telegram_callback_secret(*, bot_config: dict[str, object]) -> str:
    return (
        str(os.getenv("EA_TELEGRAM_CALLBACK_SECRET") or "").strip()
        or str(bot_config.get("secret") or "").strip()
        or str(bot_config.get("token") or "").strip()
    )


def _telegram_callback_ttl_seconds() -> int:
    raw = str(os.getenv("EA_TELEGRAM_CALLBACK_TTL_SECONDS") or "3600").strip()
    try:
        return max(int(float(raw or "3600")), 60)
    except Exception:
        return 3600


def _telegram_audiobook_voice_callback_ttl_seconds() -> int:
    raw = str(os.getenv("EA_TELEGRAM_AUDIOBOOK_VOICE_CALLBACK_TTL_SECONDS") or "604800").strip()
    try:
        return max(int(float(raw or "604800")), 3600)
    except Exception:
        return 604800


def _telegram_callback_signature(
    *,
    secret: str,
    action: str,
    current_message_id: str,
    chat_id: str,
    expires_at: int,
) -> str:
    payload = "|".join(
        (
            str(action or "").strip(),
            str(current_message_id or "").strip(),
            str(chat_id or "").strip(),
            str(int(expires_at)),
        )
    )
    return hmac.new(
        str(secret or "").encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:12]


def _telegram_encode_callback_data(
    *,
    bot_config: dict[str, object],
    action: str,
    current_message_id: str,
    chat_id: str,
) -> str:
    secret = _telegram_callback_secret(bot_config=bot_config)
    normalized_action = str(action or "").strip().lower()
    normalized_message_id = str(current_message_id or "").strip()
    normalized_chat_id = str(chat_id or "").strip()
    if not secret or not normalized_action or not normalized_message_id or not normalized_chat_id:
        return ""
    expires_at = int(time.time()) + _telegram_callback_ttl_seconds()
    signature = _telegram_callback_signature(
        secret=secret,
        action=normalized_action,
        current_message_id=normalized_message_id,
        chat_id=normalized_chat_id,
        expires_at=expires_at,
    )
    return f"ea|{normalized_action}|{normalized_message_id}|{normalized_chat_id}|{expires_at}|{signature}"


def _telegram_decode_callback_data(
    *,
    bot_config: dict[str, object],
    callback_data: str,
    chat_id: str,
) -> dict[str, object]:
    normalized = str(callback_data or "").strip()
    parts = normalized.split("|")
    if len(parts) != 6 or parts[0] != "ea":
        return {"ok": False, "reason": "invalid_format"}
    _, action, current_message_id, encoded_chat_id, expires_at_raw, signature = parts
    if str(encoded_chat_id or "").strip() != str(chat_id or "").strip():
        return {"ok": False, "reason": "chat_mismatch"}
    try:
        expires_at = int(str(expires_at_raw or "").strip())
    except Exception:
        return {"ok": False, "reason": "invalid_expiry"}
    if expires_at < int(time.time()):
        return {"ok": False, "reason": "expired", "action": str(action or "").strip().lower()}
    secret = _telegram_callback_secret(bot_config=bot_config)
    if not secret:
        return {"ok": False, "reason": "missing_secret"}
    expected_signature = _telegram_callback_signature(
        secret=secret,
        action=str(action or "").strip().lower(),
        current_message_id=str(current_message_id or "").strip(),
        chat_id=str(chat_id or "").strip(),
        expires_at=expires_at,
    )
    if not hmac.compare_digest(str(signature or "").strip(), expected_signature):
        return {"ok": False, "reason": "invalid_signature"}
    return {
        "ok": True,
        "action": str(action or "").strip().lower(),
        "current_message_id": str(current_message_id or "").strip(),
        "chat_id": str(chat_id or "").strip(),
        "expires_at": expires_at,
    }


def _telegram_send_message(
    *,
    bot_token: str,
    chat_id: str,
    text: str,
    inline_buttons: list[list[tuple[str, str]]] | None = None,
) -> dict[str, object]:
    normalized_token = str(bot_token or "").strip()
    normalized_chat_id = str(chat_id or "").strip()
    normalized_text = str(text or "").strip()
    if not normalized_token or not normalized_chat_id or not normalized_text:
        return {}
    payload_dict: dict[str, object] = {"chat_id": normalized_chat_id, "text": normalized_text}
    if inline_buttons:
        payload_dict["reply_markup"] = _telegram_inline_keyboard(inline_buttons)
    payload = json.dumps(payload_dict).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{normalized_token}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        timeout_seconds = max(float(str(os.getenv("EA_TELEGRAM_SEND_TIMEOUT_SECONDS") or "10").strip() or "10"), 1.0)
    except Exception:
        timeout_seconds = 10.0
    return _telegram_post_json_with_retries(request=request, timeout_seconds=timeout_seconds)


def _base36_encode(value: int) -> str:
    alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"
    normalized = max(int(value), 0)
    if normalized == 0:
        return "0"
    chars: list[str] = []
    while normalized:
        normalized, remainder = divmod(normalized, 36)
        chars.append(alphabet[remainder])
    return "".join(reversed(chars))


def _base36_decode(value: str) -> int:
    return int(str(value or "0").strip().lower(), 36)


def _telegram_audiobook_voice_callback_signature(
    *,
    secret: str,
    action: str,
    token: str,
    chat_id: str,
    expires_at: int,
) -> str:
    payload = "|".join(
        (
            "ab",
            str(action or "").strip().lower(),
            str(token or "").strip(),
            str(chat_id or "").strip(),
            str(int(expires_at)),
        )
    )
    return hmac.new(str(secret or "").encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()[:10]


def _telegram_encode_audiobook_voice_callback(
    *,
    bot_config: dict[str, object],
    action: str,
    token: str,
    chat_id: str,
) -> str:
    secret = _telegram_callback_secret(bot_config=bot_config)
    normalized_action = str(action or "").strip().lower()[:1]
    normalized_token = str(token or "").strip()
    normalized_chat_id = str(chat_id or "").strip()
    if normalized_action not in {"u", "d"} or not normalized_token or not normalized_chat_id or not secret:
        return ""
    expires_at = int(time.time()) + _telegram_audiobook_voice_callback_ttl_seconds()
    signature = _telegram_audiobook_voice_callback_signature(
        secret=secret,
        action=normalized_action,
        token=normalized_token,
        chat_id=normalized_chat_id,
        expires_at=expires_at,
    )
    return f"ab|{normalized_action}|{normalized_token}|{_base36_encode(expires_at)}|{signature}"


def _telegram_decode_audiobook_voice_callback(
    *,
    bot_config: dict[str, object],
    callback_data: str,
    chat_id: str,
) -> dict[str, object]:
    parts = str(callback_data or "").strip().split("|")
    if len(parts) != 5 or parts[0] != "ab":
        return {"ok": False, "reason": "invalid_format"}
    _prefix, action, token, expires_raw, signature = parts
    normalized_action = str(action or "").strip().lower()
    if normalized_action not in {"u", "d"}:
        return {"ok": False, "reason": "invalid_action"}
    try:
        expires_at = _base36_decode(expires_raw)
    except Exception:
        return {"ok": False, "reason": "invalid_expiry"}
    if expires_at < int(time.time()):
        return {"ok": False, "reason": "expired"}
    secret = _telegram_callback_secret(bot_config=bot_config)
    if not secret:
        return {"ok": False, "reason": "missing_secret"}
    expected = _telegram_audiobook_voice_callback_signature(
        secret=secret,
        action=normalized_action,
        token=str(token or "").strip(),
        chat_id=str(chat_id or "").strip(),
        expires_at=expires_at,
    )
    if not hmac.compare_digest(str(signature or "").strip(), expected):
        return {"ok": False, "reason": "invalid_signature"}
    return {
        "ok": True,
        "action": "use" if normalized_action == "u" else "dismiss",
        "token": str(token or "").strip(),
        "expires_at": expires_at,
    }


def _telegram_audiobook_playback_callback_signature(
    *,
    secret: str,
    action: str,
    token: str,
    chat_id: str,
    expires_at: int,
) -> str:
    payload = "|".join(
        (
            "ap",
            str(action or "").strip().lower(),
            str(token or "").strip(),
            str(chat_id or "").strip(),
            str(int(expires_at)),
        )
    )
    return hmac.new(str(secret or "").encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()[:10]


def _telegram_encode_audiobook_playback_callback(
    *,
    bot_config: dict[str, object],
    action: str,
    token: str,
    chat_id: str,
) -> str:
    normalized_action = str(action or "").strip().lower()[:1]
    normalized_token = str(token or "").strip()
    normalized_chat_id = str(chat_id or "").strip()
    secret = _telegram_callback_secret(bot_config=bot_config)
    if normalized_action not in {"a", "r"} or not normalized_token or not normalized_chat_id or not secret:
        return ""
    expires_at = int(time.time()) + _telegram_callback_ttl_seconds()
    signature = _telegram_audiobook_playback_callback_signature(
        secret=secret,
        action=normalized_action,
        token=normalized_token,
        chat_id=normalized_chat_id,
        expires_at=expires_at,
    )
    return f"ap|{normalized_action}|{normalized_token}|{expires_at}|{signature}"


def _telegram_decode_audiobook_playback_callback(
    *,
    bot_config: dict[str, object],
    callback_data: str,
    chat_id: str,
) -> dict[str, object]:
    parts = str(callback_data or "").strip().split("|")
    if len(parts) != 5 or parts[0] != "ap":
        return {"ok": False, "reason": "invalid_format"}
    _prefix, action, token, expires_raw, signature = parts
    normalized_action = str(action or "").strip().lower()
    if normalized_action not in {"a", "r"}:
        return {"ok": False, "reason": "invalid_action"}
    try:
        expires_at = int(str(expires_raw or "").strip())
    except Exception:
        return {"ok": False, "reason": "invalid_expiry"}
    if expires_at < int(time.time()):
        return {"ok": False, "reason": "expired"}
    secret = _telegram_callback_secret(bot_config=bot_config)
    if not secret:
        return {"ok": False, "reason": "missing_secret"}
    expected = _telegram_audiobook_playback_callback_signature(
        secret=secret,
        action=normalized_action,
        token=str(token or "").strip(),
        chat_id=str(chat_id or "").strip(),
        expires_at=expires_at,
    )
    if not hmac.compare_digest(str(signature or "").strip(), expected):
        return {"ok": False, "reason": "invalid_signature"}
    return {
        "ok": True,
        "action": "accepted" if normalized_action == "a" else "problem",
        "token": str(token or "").strip(),
        "expires_at": expires_at,
    }


def _telegram_audiobook_playback_acceptance_buttons(
    *,
    bot_config: dict[str, object],
    chat_id: str,
    job: dict[str, object],
) -> tuple[dict[str, object], list[list[tuple[str, str]]]]:
    updated_job = ensure_audiobook_playback_acceptance_callback(job)
    imported = dict(updated_job.get("audiobookshelf_import") or {})
    public_share = dict(imported.get("public_share") or {})
    callback = dict(public_share.get("playback_acceptance_callback") or {})
    token = str(callback.get("token") or "").strip()
    if str(public_share.get("status") or "").strip() != "public_share_ready" or not token:
        return updated_job, []
    accepted_callback = _telegram_encode_audiobook_playback_callback(
        bot_config=bot_config,
        action="a",
        token=token,
        chat_id=chat_id,
    )
    rejected_callback = _telegram_encode_audiobook_playback_callback(
        bot_config=bot_config,
        action="r",
        token=token,
        chat_id=chat_id,
    )
    if not accepted_callback or not rejected_callback:
        return updated_job, []
    return updated_job, [[("Playback works", accepted_callback), ("Problem", rejected_callback)]]


def _telegram_send_audio(
    *,
    bot_token: str,
    chat_id: str,
    audio_path: str,
    caption: str,
    inline_buttons: list[list[tuple[str, str]]] | None = None,
) -> dict[str, object]:
    normalized_token = str(bot_token or "").strip()
    normalized_chat_id = str(chat_id or "").strip()
    path = Path(str(audio_path or "")).expanduser()
    if not normalized_token or not normalized_chat_id or not path.is_file():
        return {}
    boundary = f"----ea-telegram-audio-{uuid.uuid4().hex}"
    fields: dict[str, object] = {"chat_id": normalized_chat_id, "caption": str(caption or "").strip()[:1024]}
    if inline_buttons:
        fields["reply_markup"] = json.dumps(_telegram_inline_keyboard(inline_buttons), separators=(",", ":"))
    body = bytearray()
    for key, value in fields.items():
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"))
        body.extend(str(value or "").encode("utf-8"))
        body.extend(b"\r\n")
    content_type = mimetypes.guess_type(path.name)[0] or "audio/wav"
    body.extend(f"--{boundary}\r\n".encode("utf-8"))
    body.extend(
        (
            f'Content-Disposition: form-data; name="audio"; filename="{path.name}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode("utf-8")
    )
    body.extend(path.read_bytes())
    body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode("utf-8"))
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{normalized_token}/sendAudio",
        data=bytes(body),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        timeout_seconds = max(float(str(os.getenv("EA_TELEGRAM_SEND_TIMEOUT_SECONDS") or "10").strip() or "10"), 1.0)
    except Exception:
        timeout_seconds = 10.0
    return _telegram_post_json_with_retries(request=request, timeout_seconds=timeout_seconds)


def _telegram_send_audiobook_voice_samples(
    *,
    bot_config: dict[str, object],
    chat_id: str,
    job: dict[str, object],
) -> list[dict[str, object]]:
    bot_token = str(bot_config.get("token") or "").strip()
    receipts: list[dict[str, object]] = []
    pending_samples = _telegram_audiobook_voice_samples_pending_delivery(job)
    for sample in pending_samples:
        token = str(sample.get("token") or "").strip()
        use_callback = _telegram_encode_audiobook_voice_callback(
            bot_config=bot_config,
            action="u",
            token=token,
            chat_id=chat_id,
        )
        dismiss_callback = _telegram_encode_audiobook_voice_callback(
            bot_config=bot_config,
            action="d",
            token=token,
            chat_id=chat_id,
        )
        caption = str(sample.get("label") or "Voice sample").strip()
        author_gender_signal = str(sample.get("author_gender_signal") or "").strip().lower()
        candidate_gender = str(sample.get("gender") or "").strip().lower()
        if (
            str(sample.get("voice_selection_reason") or "").strip() == "selected_voice_author_gender_mismatch"
            and bool(sample.get("author_gender_match"))
            and author_gender_signal in {"male", "female"}
        ):
            caption = f"{caption} · {author_gender_signal} author match"
        elif candidate_gender in {"male", "female"}:
            caption = f"{caption} · {candidate_gender}"
        matched_tags = [str(item).strip() for item in list(sample.get("matched_tags") or []) if str(item).strip()]
        if matched_tags:
            caption = f"{caption} · {', '.join(matched_tags[:4])}"
        try:
            receipt = _telegram_send_audio(
                bot_token=bot_token,
                chat_id=chat_id,
                audio_path=str(sample.get("audio_path") or ""),
                caption=caption,
                inline_buttons=[[("Use this", use_callback), ("Dismiss", dismiss_callback)]],
            )
        except Exception as exc:
            receipts.append({"token": token, "status": "failed", "reason": type(exc).__name__})
            continue
        sent = bool(receipt) and bool(dict(receipt).get("ok", True))
        reason = str(dict(receipt).get("description") or "").strip() if receipt else "telegram_audio_send_skipped"
        result = dict(dict(receipt).get("result") or {}) if isinstance(receipt, dict) else {}
        media_message_id = str(result.get("message_id") or "").strip()
        controls_ready = bool(use_callback and dismiss_callback)
        receipts.append(
            {
                "token": token,
                "status": "sent" if sent else "skipped",
                "reason": "" if sent else reason,
                "media_message_id_sha256": hashlib.sha256(media_message_id.encode("utf-8")).hexdigest()
                if media_message_id
                else "",
                "button_count": 2 if controls_ready else 0,
                "buttons_fallback": False,
                "control_kind": "inline_keyboard" if controls_ready else "",
            }
        )
    return receipts


def _whatsapp_send_audiobook_voice_samples(
    *,
    tool_runtime,
    principal_id: str,
    recipient: str,
    job: dict[str, object],
    binding_id: str = "",
    binding: object | None = None,
) -> list[dict[str, object]]:
    receipts: list[dict[str, object]] = []
    for sample in audiobook_voice_audition_sample_messages(job):
        token = str(sample.get("token") or "").strip()
        use_callback = whatsapp_inbound_actions.encode_whatsapp_audiobook_voice_callback(
            action="u",
            token=token,
            sender_ref=recipient,
        )
        dismiss_callback = whatsapp_inbound_actions.encode_whatsapp_audiobook_voice_callback(
            action="d",
            token=token,
            sender_ref=recipient,
        )
        if not use_callback or not dismiss_callback:
            receipts.append(
                {
                    "token": token,
                    "status": "failed",
                    "reason": (
                        "EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET or "
                        "EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET_FILE missing "
                        "(/run/secrets/whatsapp_audiobook_callback_secret or "
                        "/config/whatsapp_audiobook_callback_secret); whatsapp_callback_encoding_failed"
                    ),
                    "transport": "whatsapp",
                }
            )
            continue
        caption = str(sample.get("label") or "Voice sample").strip()
        matched_tags = [str(item).strip() for item in list(sample.get("matched_tags") or []) if str(item).strip()]
        if matched_tags:
            caption = f"{caption} · {', '.join(matched_tags[:4])}"
        try:
            receipt = whatsapp_delivery_router.send_whatsapp_delivery_text(
                tool_runtime=tool_runtime,
                principal_id=principal_id,
                recipient=recipient,
                text=caption,
                binding_id=binding_id,
                binding=binding,
                buttons=[[("Use this", use_callback), ("Dismiss", dismiss_callback)]],
            )
        except Exception as exc:
            receipts.append({"token": token, "status": "failed", "reason": type(exc).__name__})
            continue
        sent = bool(getattr(receipt, "message_ids", ()))
        receipts.append(
            {
                "token": token,
                "status": "sent" if sent else "skipped",
                "reason": "" if sent else "whatsapp_message_id_missing",
                "transport": str(getattr(receipt, "delivery_transport", "") or "whatsapp").strip(),
            }
        )
    return receipts


def _telegram_refill_audiobook_voice_audition_if_needed(
    *,
    job: dict[str, object],
) -> dict[str, object]:
    storage = dict(job.get("storage") or {})
    job_dir_raw = str(storage.get("job_dir") or "").strip()
    if not job_dir_raw:
        return job
    try:
        refreshed_job = prepare_audiobook_voice_audition(job_dir=Path(job_dir_raw), refill_pending=True)
    except Exception:
        return job
    return refreshed_job if isinstance(refreshed_job, dict) else job


def _extract_audiobook_voice_replacement_keys(
    *,
    voice_selection: dict[str, object],
    last_action: dict[str, object],
) -> set[str]:
    return {
        str(item or "").strip()
        for item in list(
            last_action.get("replacement_candidate_keys")
            or voice_selection.get("replacement_candidate_keys")
            or []
        )
        if str(item or "").strip()
    }


def _telegram_audiobook_voice_sample_subset(job: dict[str, object], candidate_keys: set[str]) -> dict[str, object]:
    if not candidate_keys:
        return dict(job)
    subset = dict(job)
    provider = dict(subset.get("provider") or {})
    voice_selection = dict(provider.get("voice_selection") or {})
    voice_selection["pending_batch"] = [
        row
        for row in list(voice_selection.get("pending_batch") or [])
        if isinstance(row, dict) and str(row.get("preset_key") or "").strip() in candidate_keys
    ]
    provider["voice_selection"] = voice_selection
    subset["provider"] = provider
    return subset


def _telegram_answer_callback_query(*, bot_token: str, callback_query_id: str, text: str = "") -> None:
    normalized_token = str(bot_token or "").strip()
    normalized_query_id = str(callback_query_id or "").strip()
    if not normalized_token or not normalized_query_id:
        return
    payload = json.dumps(
        {
            "callback_query_id": normalized_query_id,
            "text": str(text or "").strip()[:180],
            "show_alert": False,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{normalized_token}/answerCallbackQuery",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        timeout_seconds = max(float(str(os.getenv("EA_TELEGRAM_SEND_TIMEOUT_SECONDS") or "10").strip() or "10"), 1.0)
    except Exception:
        timeout_seconds = 10.0
    _telegram_post_json_with_retries(request=request, timeout_seconds=timeout_seconds, expect_json=False)
    return


def _telegram_transport_retry_attempts() -> int:
    raw = str(os.getenv("EA_TELEGRAM_TRANSPORT_RETRY_ATTEMPTS") or "3").strip()
    try:
        return max(int(float(raw or "3")), 1)
    except Exception:
        return 3


def _telegram_transport_retry_backoff_seconds() -> float:
    raw = str(os.getenv("EA_TELEGRAM_TRANSPORT_RETRY_BACKOFF_SECONDS") or "1.0").strip()
    try:
        return max(float(raw or "1.0"), 0.0)
    except Exception:
        return 1.0


def _telegram_property_link_bundle_poll_attempts() -> int:
    raw = str(os.getenv("EA_TELEGRAM_PROPERTY_LINK_BUNDLE_POLL_ATTEMPTS") or "8").strip()
    try:
        return max(int(float(raw or "8")), 0)
    except Exception:
        return 8


def _telegram_property_link_bundle_poll_backoff_seconds() -> float:
    raw = str(os.getenv("EA_TELEGRAM_PROPERTY_LINK_BUNDLE_POLL_BACKOFF_SECONDS") or "6.0").strip()
    try:
        return max(float(raw or "6.0"), 0.0)
    except Exception:
        return 6.0


def _telegram_post_json_with_retries(
    *,
    request: urllib.request.Request,
    timeout_seconds: float,
    expect_json: bool = True,
) -> dict[str, object]:
    attempts = _telegram_transport_retry_attempts()
    backoff_seconds = _telegram_transport_retry_backoff_seconds()
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                if not expect_json:
                    return {}
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code not in {408, 409, 425, 429, 500, 502, 503, 504} or attempt >= attempts:
                raise
            last_error = exc
        except urllib.error.URLError as exc:
            if attempt >= attempts:
                raise
            last_error = exc
        except Exception:
            raise
        if backoff_seconds > 0:
            time.sleep(backoff_seconds * attempt)
    if last_error is not None:
        raise last_error
    return {}


def _safe_math_answer(text: str) -> str:
    normalized = str(text or "").strip()
    if not normalized:
        return ""
    candidate = normalized.replace("?", "").replace("=", "").strip()
    if not candidate:
        return ""
    if not _SAFE_MATH_RE.fullmatch(normalized):
        lowered = " ".join(candidate.lower().split())
        if lowered.startswith("what is "):
            lowered = lowered[8:].strip()
        elif lowered.startswith("what's "):
            lowered = lowered[7:].strip()
        elif lowered.startswith("calculate "):
            lowered = lowered[10:].strip()
        elif lowered.startswith("compute "):
            lowered = lowered[8:].strip()
        for word, value in _MATH_WORD_NUMBERS.items():
            lowered = re.sub(rf"\\b{re.escape(word)}\\b", value, lowered)
        replacements = (
            ("divided by", "/"),
            ("multiplied by", "*"),
            ("times", "*"),
            ("plus", "+"),
            ("minus", "-"),
            ("x", "*"),
        )
        for src, dest in replacements:
            lowered = lowered.replace(src, f" {dest} ")
        lowered = re.sub(r"[^0-9\.\+\-\*\/\(\)\s]", " ", lowered)
        lowered = " ".join(lowered.split())
        if not lowered or not _SAFE_MATH_RE.fullmatch(lowered):
            return ""
        candidate = lowered

    def _eval_node(node):  # type: ignore[no-untyped-def]
        if isinstance(node, ast.Expression):
            return _eval_node(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = _eval_node(node.operand)
            return value if isinstance(node.op, ast.UAdd) else -value
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            left = _eval_node(node.left)
            right = _eval_node(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            return left / right
        raise ValueError("unsupported_math_expression")

    try:
        parsed = ast.parse(candidate, mode="eval")
        value = _eval_node(parsed)
    except Exception:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return f"{candidate} = {value}"


def _recent_telegram_texts(container: AppContainer, *, principal_id: str, limit: int = 12) -> list[str]:
    rows = container.channel_runtime.list_recent_observations(limit=limit, principal_id=principal_id)
    texts: list[str] = []
    for row in rows:
        if str(row.channel or "").strip() != "telegram":
            continue
        payload = dict(row.payload or {})
        text = str(payload.get("text") or "").strip()
        if text:
            texts.append(text)
    return texts


def _recent_telegram_reply_texts(container: AppContainer, *, principal_id: str, limit: int = 12) -> list[str]:
    rows = container.channel_runtime.list_recent_observations(limit=limit, principal_id=principal_id)
    texts: list[str] = []
    for row in rows:
        if str(row.channel or "").strip() != "telegram":
            continue
        if str(row.event_type or "").strip() != "telegram.reply_sent":
            continue
        payload = dict(row.payload or {})
        text = str(payload.get("reply_text") or "").strip()
        if text:
            texts.append(text)
    return texts


def _telegram_reply_marker_dedupe_key(dedupe_key: str) -> str:
    normalized = str(dedupe_key or "").strip()
    return f"{normalized}:reply_sent" if normalized else ""


def _telegram_async_marker_dedupe_key(dedupe_key: str) -> str:
    normalized = str(dedupe_key or "").strip()
    return f"{normalized}:assistant_async_started" if normalized else ""


def _telegram_callback_marker_dedupe_key(dedupe_key: str) -> str:
    normalized = str(dedupe_key or "").strip()
    return f"{normalized}:callback_processed" if normalized else ""


def _telegram_reply_already_sent(container: AppContainer, *, principal_id: str, dedupe_key: str) -> bool:
    marker = _telegram_reply_marker_dedupe_key(dedupe_key)
    if not marker:
        return False
    return container.channel_runtime.find_observation_by_dedupe(marker, principal_id=principal_id) is not None


def _record_telegram_reply_sent(
    container: AppContainer,
    *,
    principal_id: str,
    chat_id: str,
    dedupe_key: str,
    reply_text: str,
    message_id: str,
    active_object_map: dict[str, str] | None = None,
    intent_state: dict[str, str] | None = None,
    comparison_state: dict[str, str] | None = None,
) -> None:
    marker = _telegram_reply_marker_dedupe_key(dedupe_key)
    if not marker:
        return
    container.channel_runtime.ingest_observation(
        principal_id=principal_id,
        channel="telegram",
        event_type="telegram.reply_sent",
        payload={
            "chat_id": chat_id,
            "reply_text": reply_text,
            "message_id": message_id,
            "dedupe_key": dedupe_key,
            "active_object_map": dict(active_object_map or {}),
            "intent_state": dict(intent_state or {}),
            "comparison_state": dict(comparison_state or {}),
        },
        source_id=f"telegram:{chat_id}" if chat_id else "telegram",
        external_id=str(message_id or "").strip(),
        dedupe_key=marker,
    )


def _telegram_async_already_started(container: AppContainer, *, principal_id: str, dedupe_key: str) -> bool:
    marker = _telegram_async_marker_dedupe_key(dedupe_key)
    if not marker:
        return False
    return container.channel_runtime.find_observation_by_dedupe(marker, principal_id=principal_id) is not None


def _telegram_callback_already_processed(container: AppContainer, *, principal_id: str, dedupe_key: str) -> bool:
    marker = _telegram_callback_marker_dedupe_key(dedupe_key)
    if not marker:
        return False
    return container.channel_runtime.find_observation_by_dedupe(marker, principal_id=principal_id) is not None


def _record_telegram_callback_processed(
    container: AppContainer,
    *,
    principal_id: str,
    chat_id: str,
    dedupe_key: str,
    callback_query_id: str,
    callback_kind: str,
    reply_text: str = "",
    current_message_id: str = "",
    source_text: str = "",
) -> None:
    marker = _telegram_callback_marker_dedupe_key(dedupe_key)
    if not marker:
        return
    container.channel_runtime.ingest_observation(
        principal_id=principal_id,
        channel="telegram",
        event_type="telegram.callback_processed",
        payload={
            "chat_id": str(chat_id or "").strip(),
            "callback_query_id": str(callback_query_id or "").strip(),
            "callback_kind": str(callback_kind or "").strip(),
            "reply_text": str(reply_text or "").strip(),
            "current_message_id": str(current_message_id or "").strip(),
            "source_text": str(source_text or "").strip(),
            "dedupe_key": str(dedupe_key or "").strip(),
        },
        source_id=f"telegram:{chat_id}" if chat_id else "telegram",
        external_id=str(callback_query_id or current_message_id or "").strip(),
        dedupe_key=marker,
    )


def _telegram_similar_async_prompt_pending(
    container: AppContainer,
    *,
    principal_id: str,
    chat_id: str,
    text: str,
    window_seconds: int = 120,
) -> bool:
    normalized_text = " ".join(str(text or "").strip().lower().split())
    if not normalized_text:
        return False
    cutoff = datetime.now(ZoneInfo("UTC")).timestamp() - max(int(window_seconds), 1)
    for row in container.channel_runtime.list_recent_observations(limit=80, principal_id=principal_id):
        if str(row.channel or "").strip() != "telegram":
            continue
        if str(row.event_type or "").strip() != "telegram.reply_async_started":
            continue
        payload = dict(row.payload or {})
        if str(payload.get("chat_id") or "").strip() != str(chat_id or "").strip():
            continue
        prompt_text = " ".join(str(payload.get("prompt_text") or "").strip().lower().split())
        if prompt_text != normalized_text:
            continue
        created_at = _parse_isoish_datetime(getattr(row, "created_at", "") or "")
        if created_at is None:
            continue
        if created_at.timestamp() >= cutoff:
            return True
    return False


def _telegram_reply_fingerprint(reply_text: str) -> str:
    normalized = " ".join(str(reply_text or "").strip().split())
    if not normalized:
        return ""
    normalized = re.sub(r"https?://\S+", "<url>", normalized)
    reconnect_markers = (
        "Reconnect here if needed:",
        "Reconnect with Photos Picker here, once per Google account:",
        "Start here:",
    )
    for marker in reconnect_markers:
        if marker in normalized:
            normalized = normalized.split(marker, 1)[0].strip()
    return normalized


def _telegram_is_google_photos_picker_block_reply(reply_text: str) -> bool:
    lowered = _telegram_reply_fingerprint(reply_text).lower()
    return lowered.startswith("google photos picker access is connected for ") and (
        "google is still refusing picker sessions" in lowered
        or "i could not start a picker session right now" in lowered
    )


def _telegram_same_reply_recently_sent(
    container: AppContainer,
    *,
    principal_id: str,
    chat_id: str,
    reply_text: str,
    window_seconds: int = 180,
) -> bool:
    normalized_reply = _telegram_reply_fingerprint(reply_text)
    if not normalized_reply:
        return False
    cutoff = datetime.now(ZoneInfo("UTC")).timestamp() - max(int(window_seconds), 1)
    for row in container.channel_runtime.list_recent_observations(limit=80, principal_id=principal_id):
        if str(row.channel or "").strip() != "telegram":
            continue
        if str(row.event_type or "").strip() != "telegram.reply_sent":
            continue
        payload = dict(row.payload or {})
        if str(payload.get("chat_id") or "").strip() != str(chat_id or "").strip():
            continue
        prior_reply = _telegram_reply_fingerprint(str(payload.get("reply_text") or "").strip())
        if prior_reply != normalized_reply:
            continue
        created_at = _parse_isoish_datetime(getattr(row, "created_at", "") or "")
        if created_at is None:
            continue
        if created_at.timestamp() >= cutoff:
            return True
    return False


def _record_telegram_async_started(
    container: AppContainer,
    *,
    principal_id: str,
    chat_id: str,
    dedupe_key: str,
    prompt_text: str,
    current_message_id: str = "",
    bot_key: str = "",
    bot_handle: str = "",
    async_payload: dict[str, object] | None = None,
) -> None:
    marker = _telegram_async_marker_dedupe_key(dedupe_key)
    if not marker:
        return
    container.channel_runtime.ingest_observation(
        principal_id=principal_id,
        channel="telegram",
        event_type="telegram.reply_async_started",
        payload={
            "chat_id": chat_id,
            "prompt_text": prompt_text,
            "dedupe_key": dedupe_key,
            "current_message_id": str(current_message_id or "").strip(),
            "bot_key": str(bot_key or "").strip(),
            "bot_handle": str(bot_handle or "").strip(),
            "async_payload": dict(async_payload or {}),
            "turn_state": "queued",
            "delivery_mode": "durable_observation_outbox",
        },
        source_id=f"telegram:{chat_id}" if chat_id else "telegram",
        external_id=str(dedupe_key or "").strip(),
        dedupe_key=marker,
    )


def _record_telegram_async_processing(
    container: AppContainer,
    *,
    principal_id: str,
    chat_id: str,
    current_message_id: str,
    prompt_text: str,
) -> None:
    external_id = str(current_message_id or "").strip()
    if not external_id:
        return
    container.channel_runtime.ingest_observation(
        principal_id=principal_id,
        channel="telegram",
        event_type="telegram.reply_async_processing",
        payload={
            "chat_id": str(chat_id or "").strip(),
            "prompt_text": str(prompt_text or "").strip(),
            "turn_state": "processing",
        },
        source_id=f"telegram:{chat_id}" if chat_id else "telegram",
        external_id=external_id,
        dedupe_key=f"{external_id}:assistant_async_processing",
    )


def _record_telegram_async_failed(
    container: AppContainer,
    *,
    principal_id: str,
    chat_id: str,
    current_message_id: str,
    prompt_text: str,
    stage: str,
    error: str,
) -> None:
    external_id = str(current_message_id or "").strip()
    container.channel_runtime.ingest_observation(
        principal_id=principal_id,
        channel="telegram",
        event_type="telegram.reply_async_failed",
        payload={
            "chat_id": str(chat_id or "").strip(),
            "prompt_text": str(prompt_text or "").strip(),
            "stage": str(stage or "").strip(),
            "error": str(error or "").strip(),
            "turn_state": "failed",
        },
        source_id=f"telegram:{chat_id}" if chat_id else "telegram",
        external_id=external_id,
        dedupe_key=f"{external_id}:assistant_async_failed" if external_id else "",
    )


def _telegram_video_source_receipt_context(payload: dict[str, object]) -> dict[str, object]:
    return telegram_video_source_receipt_context(payload)


def _record_telegram_video_delivery_receipt(
    container: AppContainer,
    *,
    principal_id: str,
    chat_id: str,
    current_message_id: str,
    provider: str,
    status: str,
    payload: dict[str, object],
    message_ids: list[object] | tuple[object, ...] | None = None,
    error: str = "",
    sidecar: dict[str, object] | None = None,
) -> None:
    shared_record_telegram_video_delivery_receipt(
        container.channel_runtime,
        principal_id=principal_id,
        chat_id=chat_id,
        source_message_id=current_message_id,
        provider=provider,
        status=status,
        source_payload=payload,
        message_ids=message_ids,
        error=error,
        sidecar=sidecar,
    )


def _record_telegram_async_sent(
    container: AppContainer,
    *,
    principal_id: str,
    chat_id: str,
    current_message_id: str,
    prompt_text: str,
    reply_text: str,
    used_fallback_only: bool,
) -> None:
    external_id = str(current_message_id or "").strip()
    container.channel_runtime.ingest_observation(
        principal_id=principal_id,
        channel="telegram",
        event_type="telegram.reply_async_sent",
        payload={
            "chat_id": str(chat_id or "").strip(),
            "prompt_text": str(prompt_text or "").strip(),
            "reply_text": str(reply_text or "").strip(),
            "used_fallback_only": bool(used_fallback_only),
            "turn_state": "sent",
        },
        source_id=f"telegram:{chat_id}" if chat_id else "telegram",
        external_id=external_id,
        dedupe_key=f"{external_id}:assistant_async_sent" if external_id else "",
    )


def _telegram_general_reply_text(*, container: AppContainer, principal_id: str, text: str) -> str:
    normalized = str(text or "").strip()
    lower = normalized.lower()
    alpha = "".join(ch for ch in lower if ch.isalpha() or ch.isspace()).strip()
    if alpha in {"again", "repeat", "say that again", "repeat that", "once more"}:
        for previous_reply in _recent_telegram_reply_texts(container, principal_id=principal_id):
            previous_normalized = str(previous_reply or "").strip()
            if not previous_normalized:
                continue
            previous_lower = previous_normalized.lower()
            if previous_lower in {
                "let me check that and get back to you here.",
                "i am still working on that last message.",
            }:
                continue
            if previous_lower.startswith(_telegram_saved_flow_reply_prefix().lower()):
                continue
            return previous_normalized
        return "I do not have a useful previous answer to repeat yet."
    if lower in {"really", "really?"}:
        for previous in _recent_telegram_texts(container, principal_id=principal_id):
            previous_normalized = str(previous or "").strip()
            if previous_normalized.lower() in {"really", "really?"}:
                continue
            math_answer = _safe_math_answer(previous_normalized)
            if math_answer:
                return f"Yes. {math_answer}"
            if "http://" in previous_normalized or "https://" in previous_normalized:
                return f"Yes. I captured the link and kept it in {_assistant_owner_possessive_label()} assistant inbox."
            break
        return f"Yes. I captured your message and kept it in {_assistant_owner_possessive_label()} assistant flow."
    if ("today" in lower and "day" in lower) or alpha in {"day", "today", "what day", "weekday"}:
        now = datetime.now(ZoneInfo("Europe/Vienna"))
        return f"Today is {now.strftime('%A, %d %B %Y')} in Vienna."
    if ("today" in lower and "date" in lower) or alpha in {"date", "today date", "what date"}:
        now = datetime.now(ZoneInfo("Europe/Vienna"))
        return f"Today's date is {now.strftime('%A, %d %B %Y')} in Vienna."
    if ("time" in lower and "what" in lower) or alpha in {"time", "current time", "what time"}:
        now = datetime.now(ZoneInfo("Europe/Vienna"))
        return f"It is {now.strftime('%H:%M')} in Vienna."
    weather_reply = _telegram_weather_reply_text(text=normalized)
    if weather_reply:
        return weather_reply
    return ""


def _telegram_photo_reply_text(payload: dict[str, object] | None = None) -> str:
    payload_dict = dict(payload or {})
    if str(payload_dict.get("kind") or "").strip().lower() != "photo":
        return ""
    analysis = dict(payload_dict.get("photo_analysis") or {})
    status = str(payload_dict.get("photo_analysis_status") or "").strip().lower()
    summary = str(payload_dict.get("analysis_summary") or analysis.get("summary") or "").strip()
    notable_details = [
        str(value).strip()
        for value in list(analysis.get("notable_details") or [])
        if str(value).strip()
    ]
    suggestions = [
        str(value).strip()
        for value in list(analysis.get("suggestions") or [])
        if str(value).strip()
    ]
    if summary:
        parts = [f"I got the photo. {summary}"]
        if notable_details:
            parts.append("Notable details: " + "; ".join(notable_details[:3]) + ".")
        if suggestions:
            parts.append(suggestions[0].rstrip(".") + ".")
        return " ".join(part.strip() for part in parts if part.strip()).strip()
    if status == "failed":
        return "I got the photo, but the image analysis failed on my side. Send it again or add a short caption and I’ll retry."
    return "I got the photo and saved it, but I do not have enough analyzed detail yet to say something useful about it."


def _telegram_media_acknowledgement_reply(
    payload: dict[str, object] | None = None,
    *,
    text: str = "",
) -> str:
    payload_dict = dict(payload or {})
    kind = str(payload_dict.get("kind") or "").strip().lower()
    normalized_text = " ".join(str(text or payload_dict.get("text") or "").strip().lower().split())
    if kind == "video" or normalized_text in {"video", "video message"}:
        return (
            "Got the video. Add one short instruction (summarize it, look for risks, pull key points), "
            "and I will run it in the next assistant step."
        )
    if kind == "document" or normalized_text in {"document", "doc", "document upload", "my pdf"}:
        return (
            "Got the document. Add a short note (extract text, summarize, or flag action items), "
            "and I will proceed."
        )
    return ""


_WHATSAPP_PAIRING_CONTEXT_MARKERS = (
    "ea whatsapp web pairing is required",
    "whatsapp web pairing is required",
    "whatsapp_pairing status=",
    "pair_url=",
    "qr_required",
)
_WHATSAPP_PAIRING_FOLLOWUP_MARKERS = (
    "couldn't link device",
    "couldnt link device",
    "could not link device",
    "can't link device",
    "cant link device",
    "link device try again later",
    "try again later",
)
_WHATSAPP_PAIRING_STRONG_FOLLOWUP_MARKERS = tuple(
    marker
    for marker in _WHATSAPP_PAIRING_FOLLOWUP_MARKERS
    if marker != "try again later"
)


def _telegram_observation_matches_chat(row: object, *, chat_id: str, payload: Mapping[str, object] | None = None) -> bool:
    normalized_chat = str(chat_id or "").strip()
    if not normalized_chat:
        return True
    payload_dict = dict(payload or getattr(row, "payload", {}) or {})
    candidate_chat = str(payload_dict.get("chat_id") or getattr(row, "chat_id", "") or "").strip()
    if candidate_chat == normalized_chat:
        return True
    source_id = str(getattr(row, "source_id", "") or "").strip()
    if source_id == f"telegram:{normalized_chat}":
        return True
    return False


def _telegram_recent_whatsapp_pairing_context(
    container: AppContainer,
    *,
    principal_id: str,
    chat_id: str,
    window_seconds: int = 900,
) -> bool:
    cutoff = datetime.now(ZoneInfo("UTC")).timestamp() - max(int(window_seconds), 1)
    try:
        rows = container.channel_runtime.list_recent_observations(limit=80, principal_id=principal_id)
    except Exception:
        return False
    for row in rows:
        if str(getattr(row, "channel", "") or "").strip() != "telegram":
            continue
        if str(getattr(row, "event_type", "") or "").strip() not in {"telegram.reply_sent", "telegram.reply_async_sent"}:
            continue
        payload = dict(getattr(row, "payload", {}) or {})
        if not _telegram_observation_matches_chat(row, chat_id=chat_id, payload=payload):
            continue
        created_at = _parse_isoish_datetime(getattr(row, "created_at", "") or "")
        if created_at is not None and created_at.timestamp() < cutoff:
            continue
        reply_text = " ".join(str(payload.get("reply_text") or "").strip().lower().split())
        if any(marker in reply_text for marker in _WHATSAPP_PAIRING_CONTEXT_MARKERS):
            return True
    return False


def _telegram_whatsapp_pairing_followup_text(text: str) -> bool:
    normalized = " ".join(str(text or "").strip().lower().split())
    if not normalized:
        return False
    return any(marker in normalized for marker in _WHATSAPP_PAIRING_FOLLOWUP_MARKERS)


def _telegram_strong_whatsapp_pairing_followup_text(text: str) -> bool:
    normalized = " ".join(str(text or "").strip().lower().split())
    if not normalized:
        return False
    if "link device" in normalized and "try again later" in normalized:
        return True
    if not any(marker in normalized for marker in ("whatsapp", "qr", "pairing", "wa web", "whatsapp web")):
        return False
    return any(marker in normalized for marker in _WHATSAPP_PAIRING_STRONG_FOLLOWUP_MARKERS)


def _telegram_recent_whatsapp_pairing_followup_signal(
    container: AppContainer,
    *,
    principal_id: str,
    chat_id: str,
    window_seconds: int = 900,
) -> bool:
    cutoff = datetime.now(ZoneInfo("UTC")).timestamp() - max(int(window_seconds), 1)
    try:
        rows = container.channel_runtime.list_recent_observations(limit=80, principal_id=principal_id)
    except Exception:
        return False
    for row in rows:
        if str(getattr(row, "channel", "") or "").strip() != "telegram":
            continue
        if str(getattr(row, "event_type", "") or "").strip() != "telegram.message":
            continue
        payload = dict(getattr(row, "payload", {}) or {})
        if not _telegram_observation_matches_chat(row, chat_id=chat_id, payload=payload):
            continue
        created_at = _parse_isoish_datetime(getattr(row, "created_at", "") or "")
        if created_at is not None and created_at.timestamp() < cutoff:
            continue
        if _telegram_strong_whatsapp_pairing_followup_text(str(payload.get("text") or "")):
            return True
    return False


def _telegram_should_suppress_whatsapp_pairing_followup(ctx: TelegramTurnContext) -> bool:
    has_recent_pairing_context = _telegram_recent_whatsapp_pairing_context(
        ctx.container,
        principal_id=ctx.principal_id,
        chat_id=ctx.chat_id,
    )
    has_current_strong_followup = _telegram_strong_whatsapp_pairing_followup_text(ctx.normalized)
    has_recent_followup_signal = _telegram_recent_whatsapp_pairing_followup_signal(
        ctx.container,
        principal_id=ctx.principal_id,
        chat_id=ctx.chat_id,
    )
    kind = str(dict(ctx.payload or {}).get("kind") or "").strip().lower()
    if has_current_strong_followup:
        return True
    if has_recent_pairing_context and _telegram_whatsapp_pairing_followup_text(ctx.normalized):
        return True
    if (
        kind in {"photo", "video"}
        and ctx.normalized.lower() in {"", "photo", "video", "video message"}
        and (has_recent_pairing_context or has_current_strong_followup or has_recent_followup_signal)
    ):
        return True
    return False


def _record_telegram_whatsapp_pairing_followup_suppressed(
    container: AppContainer,
    *,
    principal_id: str,
    chat_id: str,
    dedupe_key: str,
    current_message_id: str,
    source_text: str,
    source_kind: str,
) -> None:
    fallback_marker = ""
    if str(chat_id or "").strip() and str(current_message_id or "").strip():
        fallback_marker = f"telegram:{chat_id}:{current_message_id}"
    marker_base = str(dedupe_key or "").strip() or fallback_marker
    marker = f"{marker_base}:whatsapp_pairing_followup_suppressed" if marker_base else ""
    ingest = getattr(getattr(container, "channel_runtime", None), "ingest_observation", None)
    if not callable(ingest):
        return
    try:
        ingest(
            principal_id=principal_id,
            channel="telegram",
            event_type="telegram.reply_suppressed",
            payload={
                "chat_id": str(chat_id or "").strip(),
                "prompt_text": str(source_text or "").strip(),
                "source_kind": str(source_kind or "").strip(),
                "stage": "whatsapp_pairing_followup_suppressed",
                "reason": "whatsapp_pairing_followup_retry_later",
                "user_action_required": False,
                "prior_context": "whatsapp_web_pairing_qr_required",
                "next_operator_action": "retry_whatsapp_pairing_prompt_after_cooldown",
            },
            source_id=f"telegram:{chat_id}" if chat_id else "telegram",
            external_id=str(current_message_id or "").strip(),
            dedupe_key=marker,
        )
    except Exception:
        pass


_TELEGRAM_RENDERED_VIDEO_DIRECT_MARKERS = (
    "send me a video",
    "send a video",
    "reply with a video",
    "answer with a video",
    "make a video",
    "create a video",
    "render a video",
    "record a video",
    "video back",
    "teaser",
    "reel",
    "clip",
    "movie",
)

_TELEGRAM_RENDERED_VIDEO_RESULT_BACK_MARKERS = (
    "send me the result back",
    "send the result back",
    "send the result back here",
    "send it back here",
    "send me the result here",
)

_TELEGRAM_RENDERED_VIDEO_EDIT_MARKERS = (
    "edit this video",
    "edit the video",
    "replace ",
    "exchange ",
    "swap ",
    "make the ",
    "turn the ",
    "make this on fire",
    "on fire",
    "look like ",
    "real flames",
    "real fire",
    "photorealistic",
    "photorealisticly",
)

_TELEGRAM_NON_RENDER_VIDEO_ANALYSIS_MARKERS = (
    "summarize",
    "summary",
    "action items",
    "key points",
    "risks",
    "flag risks",
    "transcript",
)


def _telegram_video_placeholder_text(text: str) -> bool:
    normalized = " ".join(str(text or "").strip().lower().split())
    return normalized in {"", "video", "video message"}


def _telegram_generic_video_followup_text(text: str) -> bool:
    normalized = " ".join(str(text or "").strip().lower().split())
    if not normalized:
        return False
    return normalized in {
        "do it",
        "go",
        "go ahead",
        "yes",
        "yes please",
        "ok",
        "okay",
        "done",
        "continue",
        "make it",
        "please do it",
        "send it",
    }


def _telegram_video_instruction_candidate(text: str) -> bool:
    normalized = " ".join(str(text or "").strip().lower().split())
    if not normalized or _telegram_video_placeholder_text(normalized):
        return False
    if normalized.startswith("/"):
        return False
    if "http://" in normalized or "https://" in normalized:
        return False
    if _safe_math_answer(normalized):
        return False
    return True


def _telegram_video_caption_task_text(*, followup_text: str, caption: str) -> str:
    normalized_caption = str(caption or "").strip()
    if not normalized_caption:
        return str(followup_text or "").strip()
    if not _telegram_generic_video_followup_text(followup_text):
        return str(followup_text or "").strip()
    if not _telegram_video_instruction_candidate(normalized_caption):
        return str(followup_text or "").strip()
    if _telegram_instructional_video_prefers_rendered_video(normalized_caption):
        return normalized_caption
    lowered_caption = " ".join(normalized_caption.lower().split())
    if any(marker in lowered_caption for marker in _TELEGRAM_NON_RENDER_VIDEO_ANALYSIS_MARKERS):
        return normalized_caption
    return str(followup_text or "").strip()


def _telegram_recent_video_message_payload(
    container: AppContainer,
    *,
    principal_id: str,
    chat_id: str = "",
    current_message_id: str = "",
) -> dict[str, object]:
    rows = list(container.channel_runtime.list_recent_observations(limit=30, principal_id=principal_id))
    rows.sort(key=lambda row: (str(row.created_at or ""), str(row.observation_id or "")), reverse=True)
    normalized_chat_id = str(chat_id or "").strip()
    normalized_current_message_id = str(current_message_id or "").strip()
    for row in rows:
        if str(row.channel or "").strip() != "telegram":
            continue
        if str(row.event_type or "").strip().lower() != "telegram.message":
            continue
        if normalized_current_message_id and str(row.external_id or "").strip() == normalized_current_message_id:
            continue
        if normalized_chat_id and str(row.source_id or "").strip() not in {f"telegram:{normalized_chat_id}", "telegram"}:
            continue
        payload = dict(row.payload or {})
        if str(payload.get("kind") or "").strip().lower() == "video":
            return payload
        continue
    return {}


def _telegram_reply_to_video_message_payload(ctx: TelegramTurnContext) -> dict[str, object]:
    payload = dict(ctx.payload or {})
    raw = dict(payload.get("raw") or {})
    message = dict(raw.get("message") or {})
    reply_to = dict(message.get("reply_to_message") or {})
    if not reply_to:
        return {}
    video = dict(reply_to.get("video") or {})
    if not video:
        return {}
    caption = str(reply_to.get("caption") or "").strip()
    return {
        "kind": "video",
        "message_id": str(reply_to.get("message_id") or "").strip(),
        "message_metadata": {
            "file_id": str(video.get("file_id") or "").strip(),
            "duration": video.get("duration"),
            "caption": caption,
            "download_url": "",
        },
        "video_transcript_text": "",
        "transcription_status": "",
    }


def _telegram_build_instructional_video_payload(
    *,
    instruction_text: str,
    payload: dict[str, object],
    fallback_message_id: str,
) -> dict[str, object]:
    metadata = dict(payload.get("message_metadata") or {})
    return {
        "kind": "instructional_video",
        "instruction_text": str(instruction_text or "").strip(),
        "video_message_id": str(payload.get("message_id") or fallback_message_id or "").strip(),
        "video_file_id": str(metadata.get("file_id") or "").strip(),
        "video_download_url": str(metadata.get("download_url") or "").strip(),
        "video_duration_seconds": metadata.get("duration"),
        "video_caption": str(metadata.get("caption") or "").strip(),
        "video_transcript_text": str(payload.get("video_transcript_text") or "").strip(),
        "video_transcription_status": str(payload.get("transcription_status") or "").strip(),
    }


def _telegram_instructional_video_payload(ctx: TelegramTurnContext) -> dict[str, object]:
    payload = dict(ctx.payload or {})
    kind = str(payload.get("kind") or "").strip().lower()
    if kind == "video":
        metadata = dict(payload.get("message_metadata") or {})
        caption = str(metadata.get("caption") or ctx.text or "").strip()
        if not _telegram_video_instruction_candidate(caption):
            return {}
        payload["message_metadata"] = {**metadata, "caption": caption}
        return _telegram_build_instructional_video_payload(
            instruction_text=caption,
            payload=payload,
            fallback_message_id=ctx.current_message_id,
        )
    if kind != "text":
        return {}
    if not _telegram_video_instruction_candidate(ctx.normalized):
        return {}
    recent_video_payload = _telegram_reply_to_video_message_payload(ctx) or _telegram_recent_video_message_payload(
        ctx.container,
        principal_id=ctx.principal_id,
        chat_id=ctx.chat_id,
        current_message_id=ctx.current_message_id,
    )
    if not recent_video_payload:
        return {}
    recent_metadata = dict(recent_video_payload.get("message_metadata") or {})
    instruction_text = _telegram_video_caption_task_text(
        followup_text=ctx.normalized,
        caption=str(recent_metadata.get("caption") or "").strip(),
    )
    return _telegram_build_instructional_video_payload(
        instruction_text=instruction_text,
        payload=recent_video_payload,
        fallback_message_id="",
    )


def _telegram_instructional_video_turn_decision(ctx: TelegramTurnContext) -> TelegramTurnDecision:
    video_payload = _telegram_instructional_video_payload(ctx)
    if not video_payload:
        return TelegramTurnDecision()
    instruction_text = str(video_payload.get("instruction_text") or ctx.normalized or ctx.text or "").strip()
    return TelegramTurnDecision(
        schedule_async=True,
        async_text=instruction_text,
        async_message_id=ctx.current_message_id or str(video_payload.get("video_message_id") or "").strip(),
        async_payload=video_payload,
    )


def _telegram_instructional_video_prompt(payload: dict[str, object]) -> str:
    instruction_text = str(payload.get("instruction_text") or "").strip()
    video_caption = str(payload.get("video_caption") or "").strip()
    video_transcript_text = str(payload.get("video_transcript_text") or "").strip()
    video_transcription_status = str(payload.get("video_transcription_status") or "").strip()
    video_duration_seconds = str(payload.get("video_duration_seconds") or "").strip()
    lines = [
        "The user sent a Telegram video and wants EA to help from that video input.",
        f"User instruction: {instruction_text or 'Help with this video.'}",
    ]
    if video_caption:
        lines.append(f"Video caption: {video_caption}")
    if video_transcript_text:
        lines.append(f"Recovered audio transcript from the video: {video_transcript_text}")
    elif video_transcription_status:
        lines.append(f"Video transcription status: {video_transcription_status}")
    if video_duration_seconds:
        lines.append(f"Video duration seconds: {video_duration_seconds}")
    if str(payload.get("video_download_url") or "").strip():
        lines.append("A Telegram video download URL exists in runtime metadata for downstream tools, but do not claim frame-level analysis unless the supplied transcript/caption supports it.")
    lines.append(
        "Use every available signal above. Be explicit about what is grounded in the transcript or caption and what still needs a clearer instruction or visual review."
    )
    return "\n".join(line for line in lines if line).strip()


def _telegram_instructional_video_prefers_rendered_video(text: str) -> bool:
    normalized = " ".join(str(text or "").strip().lower().split())
    if not normalized:
        return False
    if any(marker in normalized for marker in _TELEGRAM_RENDERED_VIDEO_DIRECT_MARKERS):
        return True
    if any(marker in normalized for marker in _TELEGRAM_RENDERED_VIDEO_RESULT_BACK_MARKERS):
        return True
    if "edit this video" in normalized and "send" in normalized and "back" in normalized:
        return True
    if any(marker in normalized for marker in _TELEGRAM_NON_RENDER_VIDEO_ANALYSIS_MARKERS):
        return False
    if any(marker in normalized for marker in _TELEGRAM_RENDERED_VIDEO_EDIT_MARKERS):
        return True
    return False


def _telegram_is_generic_render_capability_reply(text: str) -> bool:
    normalized = " ".join(str(text or "").strip().lower().split())
    if not normalized:
        return False
    return (
        "mootion is available in ea" in normalized
        or "browseract_ui_ready" in normalized
        or "actions: discover_account, create_movie" in normalized
        or "magicfit is available in ea" in normalized
    )


def _telegram_browseract_binding_available(container: AppContainer, *, principal_id: str) -> bool:
    return bool(_telegram_browseract_binding_id(container, principal_id=principal_id))


def _telegram_browseract_binding_id(container: AppContainer, *, principal_id: str) -> str:
    normalized_principal = str(principal_id or "").strip()
    if not normalized_principal:
        return ""
    for binding in container.tool_runtime.list_connector_bindings_for_connector("browseract", limit=100):
        if str(binding.principal_id or "").strip() != normalized_principal:
            continue
        if str(binding.status or "").strip().lower() in {"disabled", "inactive", "archived"}:
            continue
        return str(binding.binding_id or "").strip()
    return ""


def _telegram_instructional_video_render_request(
    *,
    container: AppContainer,
    principal_id: str,
    payload: dict[str, object],
    script_text: str,
) -> ToolInvocationRequest:
    instruction_text = str(payload.get("instruction_text") or "").strip()
    title = str(payload.get("video_caption") or instruction_text or "Telegram Video Reply").strip() or "Telegram Video Reply"
    binding_id = _telegram_browseract_binding_id(container, principal_id=principal_id)
    return ToolInvocationRequest(
        session_id=f"telegram-instructional-video:{uuid.uuid4()}",
        step_id=f"telegram-instructional-video-step:{uuid.uuid4()}",
        tool_name="browseract.mootion_movie",
        action_kind="movie.render",
        payload_json={
            "binding_id": binding_id,
            "principal_id": principal_id,
            "script_text": script_text,
            "source_video_reference_summary": str(payload.get("source_video_reference_summary") or "").strip(),
            "source_video_reference_board_path": str(payload.get("source_video_reference_board_path") or "").strip(),
            "source_video_reference_frame_paths": list(payload.get("source_video_reference_frame_paths") or []),
            "title": title[:120],
            "visual_style": "grounded_executive_briefing",
            "aspect_ratio": "9:16",
            "duration_seconds": 30,
            "voiceover_style": "calm_direct",
            "caption_mode": "burned_in",
            "language": "de",
            "scene_count": 4,
            "shot_pacing": "concise",
            "platform_target": "telegram_dm",
        },
        context_json={"principal_id": principal_id},
    )


def _telegram_instructional_video_render_script(
    *,
    payload: dict[str, object],
    instruction_text: str,
    reply_text: str,
) -> str:
    grounded_instruction = str(instruction_text or "").strip()
    transcript_text = str(payload.get("video_transcript_text") or "").strip()
    caption_text = str(payload.get("video_caption") or "").strip()
    normalized_reply = " ".join(str(reply_text or "").strip().split()).lower()
    generic_reply_markers = {
        "i'm here. give me a concrete task.",
        "ask directly.",
        "i'm here. ask directly.",
    }
    if reply_text and normalized_reply not in generic_reply_markers:
        return (
            "Create a short Telegram-ready video reply in German. "
            "Keep it grounded in this answer and do not add unsupported claims.\n\n"
            f"{reply_text.strip()}"
        ).strip()
    lines = [
        "Create a short Telegram-ready German video reply from the user's instruction.",
        "Do not claim frame-level knowledge beyond the supplied instruction, caption, or recovered transcript.",
        f"User instruction: {grounded_instruction or 'Create a concise video reply.'}",
    ]
    if caption_text and caption_text != grounded_instruction:
        lines.append(f"Video caption: {caption_text}")
    if transcript_text:
        lines.append(f"Recovered transcript: {transcript_text}")
    reference_summary = str(payload.get("source_video_reference_summary") or "").strip()
    reference_board_path = str(payload.get("source_video_reference_board_path") or "").strip()
    if reference_summary:
        lines.append(reference_summary)
    if reference_board_path:
        lines.append(f"Local operator reference board: {reference_board_path}")
    lines.append(
        "Return a concise, directly useful video reply that follows the requested effect as closely as possible within the available signals."
    )
    return "\n".join(line for line in lines if line).strip()


def _telegram_enrich_payload_with_source_video_references(payload: dict[str, object]) -> dict[str, object]:
    resolved = dict(payload or {})
    if not str(resolved.get("video_download_url") or "").strip():
        return resolved
    if resolved.get("source_video_reference_board_path"):
        return resolved
    try:
        reference = extract_source_video_reference_packet(video_url=str(resolved.get("video_download_url") or "").strip())
    except Exception:
        return resolved
    resolved["source_video_reference_summary"] = str(reference.get("reference_summary") or "").strip()
    resolved["source_video_reference_board_path"] = str(reference.get("reference_board_path") or "").strip()
    resolved["source_video_reference_frame_paths"] = list(reference.get("reference_frame_paths") or [])
    return resolved


def _telegram_hydrate_instructional_video_download_url(
    payload: dict[str, object],
    *,
    bot_token: str,
) -> dict[str, object]:
    resolved = dict(payload or {})
    if str(resolved.get("kind") or "").strip().lower() != "instructional_video":
        return resolved
    if str(resolved.get("video_download_url") or "").strip():
        return resolved
    file_id = str(resolved.get("video_file_id") or "").strip()
    token = str(bot_token or "").strip()
    if not file_id or not token:
        return resolved
    try:
        resolved["video_download_url"] = _telegram_file_download_url(bot_token=token, file_id=file_id)
        resolved["video_resolve_status"] = "ok"
    except Exception as exc:
        raw_error = str(exc or "").strip()
        error_code = raw_error.split(":", 1)[0].strip().lower().replace(" ", "_") or "video_resolve_failed"
        resolved["video_resolve_status"] = "failed"
        resolved["video_resolve_error_code"] = error_code[:80]
    return resolved


def _telegram_hydrate_audiobook_epub_download_url(
    payload: dict[str, object],
    *,
    bot_token: str,
) -> dict[str, object]:
    resolved = dict(payload or {})
    if str(resolved.get("kind") or "").strip().lower() not in {
        "audiobook_epub_document",
        "audiobook_access_approval_request",
    }:
        return resolved
    if str(resolved.get("source_epub_url") or "").strip():
        return resolved
    file_id = str(resolved.get("telegram_file_id") or "").strip()
    token = str(bot_token or "").strip()
    if not file_id or not token:
        return resolved
    try:
        resolved["source_epub_url"] = _telegram_file_download_url(bot_token=token, file_id=file_id)
        resolved["source_epub_resolve_status"] = "ok"
    except Exception as exc:
        raw_error = str(exc or "").strip()
        error_code = raw_error.split(":", 1)[0].strip().lower().replace(" ", "_") or "epub_resolve_failed"
        resolved["source_epub_resolve_status"] = "failed"
        resolved["source_epub_resolve_error_code"] = error_code[:80]
    return resolved


def _telegram_magicfit_video_fallback_enabled() -> bool:
    raw = str(os.getenv("EA_TELEGRAM_MAGICFIT_VIDEO_FALLBACK_ENABLED") or "0").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _telegram_magicfit_runtime_lane_approved() -> bool:
    raw = str(os.getenv("EA_TELEGRAM_MAGICFIT_RUNTIME_LANE_APPROVED") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _telegram_magicfit_video_credentials_available() -> bool:
    email = str(os.getenv("CHUMMER_EA_MAGICFIT_EMAIL") or os.getenv("MAGICFIT_EMAIL") or "").strip()
    password = str(os.getenv("CHUMMER_EA_MAGICFIT_PASSWORD") or os.getenv("MAGICFIT_PASSWORD") or "").strip()
    return bool(email and password)


def _telegram_magicfit_video_script_path() -> Path:
    return (Path(product_service_module._repo_root()) / "scripts" / "render_magicfit_property_flythrough.py").resolve()


def _telegram_magicfit_docker_repo_root() -> Path:
    configured = str(
        os.getenv("EA_TELEGRAM_MAGICFIT_DOCKER_REPO_ROOT")
        or os.getenv("EA_HOST_REPO_ROOT")
        or ""
    ).strip()
    if configured:
        return Path(configured).expanduser()
    repo_root = Path(product_service_module._repo_root()).resolve()
    return repo_root


def _telegram_magicfit_docker_image() -> str:
    return str(os.getenv("EA_TELEGRAM_MAGICFIT_DOCKER_IMAGE") or "").strip()


def _telegram_magicfit_docker_image_pinned(image: str) -> bool:
    normalized = str(image or "").strip().lower()
    if "@sha256:" not in normalized:
        return False
    digest = normalized.rsplit("@sha256:", 1)[-1]
    return len(digest) == 64 and all(ch in "0123456789abcdef" for ch in digest)


def _telegram_magicfit_playwright_browsers_host_path() -> Path:
    raw = str(
        os.getenv("EA_TELEGRAM_MAGICFIT_PLAYWRIGHT_BROWSERS_PATH")
        or os.getenv("PLAYWRIGHT_BROWSERS_HOST_PATH")
        or (Path.home() / ".cache" / "ms-playwright")
    ).strip()
    return Path(raw).expanduser()


def _telegram_magicfit_shared_temp_root() -> Path:
    candidate = str(
        os.getenv("EA_TELEGRAM_MAGICFIT_SHARED_TEMP_ROOT")
        or os.getenv("EA_UI_SERVICE_SHARED_TEMP_ROOT")
        or (Path(product_service_module._repo_root()) / ".runtime-temp" / "telegram-magicfit")
    ).strip()
    return Path(candidate).expanduser()


def _telegram_magicfit_docker_available() -> bool:
    image = _telegram_magicfit_docker_image()
    browser_cache = _telegram_magicfit_playwright_browsers_host_path()
    return bool(image and _telegram_magicfit_docker_image_pinned(image) and str(browser_cache).strip())


def _telegram_magicfit_video_fallback_available() -> bool:
    return (
        _telegram_magicfit_video_fallback_enabled()
        and _telegram_magicfit_runtime_lane_approved()
        and _telegram_magicfit_docker_available()
        and _telegram_magicfit_video_credentials_available()
        and _telegram_magicfit_video_script_path().exists()
    )


def _telegram_instructional_video_magicfit_model_label(text: str) -> str:
    normalized = " ".join(str(text or "").strip().lower().split())
    if "photoreal" in normalized or "realistic" in normalized:
        return "Realistic"
    return ""


def _telegram_instructional_video_prefers_magicfit(text: str) -> bool:
    normalized = " ".join(str(text or "").strip().lower().split())
    if "whatever is best" in normalized or "whatever works best" in normalized or "or whatever is best" in normalized:
        return False
    return "magicfit" in normalized


def _telegram_local_source_video_fallback_available(payload: dict[str, object], instruction_text: str) -> bool:
    return (
        source_video_edit_enabled()
        and source_video_edit_supported(instruction_text)
        and bool(str(payload.get("video_download_url") or "").strip())
    )


def _telegram_render_local_source_video_reply(
    *,
    container: AppContainer,
    principal_id: str,
    payload: dict[str, object],
    instruction_text: str,
) -> dict[str, object]:
    rendered = render_local_source_video_edit(
        video_url=str(payload.get("video_download_url") or "").strip(),
        instruction_text=instruction_text,
    )
    video_path = str(rendered.get("video_file_path") or "").strip()
    if not video_path:
        raise RuntimeError("source_video_edit_output_missing")
    caption = str(payload.get("video_caption") or instruction_text or "Telegram video reply").strip()
    receipt = send_telegram_video_for_principal(
        container.tool_runtime,
        principal_id=principal_id,
        video_ref=video_path,
        audio_probe_ref=video_path,
        fallback_audio_text=caption or instruction_text,
        caption=caption,
    )
    return {
        "status": "sent",
        "kind": "video",
        "provider": str(rendered.get("provider") or "local_source_video_fx").strip() or "local_source_video_fx",
        "video_file_path": video_path,
        "message_ids": list(receipt.message_ids),
    }


def _telegram_source_video_specialized_fallback_text() -> str:
    return (
        "I have the source video, but this local edit lane does not cover that edit yet. "
        f"Right now it handles {supported_source_video_edit_summary()}."
    )


def _telegram_render_success_reply_text() -> str:
    return "I rendered and sent a short video reply here."


def _telegram_video_delivery_message_ids(delivery: dict[str, object]) -> list[str]:
    return [
        str(item or "").strip()
        for item in list(dict(delivery or {}).get("message_ids") or [])
        if str(item or "").strip()
    ]


def _telegram_video_delivery_sent(delivery: dict[str, object]) -> bool:
    delivery_dict = dict(delivery or {})
    kind = str(delivery_dict.get("kind") or "").strip().lower()
    provider = str(delivery_dict.get("provider") or "").strip().lower()
    return (
        str(delivery_dict.get("status") or "").strip().lower() == "sent"
        and (kind == "video" or (not kind and provider in {"magicfit", "local_source_video_fx"}))
        and bool(_telegram_video_delivery_message_ids(delivery_dict))
    )


def _telegram_video_delivery_error(delivery: dict[str, object], fallback: str) -> str:
    delivery_dict = dict(delivery or {})
    status = str(delivery_dict.get("status") or "").strip().lower()
    if status == "sent" and not _telegram_video_delivery_message_ids(delivery_dict):
        return "video_delivery_message_ids_missing"
    return str(delivery_dict.get("error") or "").strip() or fallback


def _telegram_video_lane_status_reply(
    *,
    payload: dict[str, object],
    instruction_text: str,
    video_render_error: str,
    prefers_magicfit: bool,
    browseract_available: bool,
    magicfit_available: bool,
) -> str:
    eta_text = "about 2 to 4 minutes" if prefers_magicfit else "about 3 to 8 minutes"
    status_text = compact_text(
        video_render_error,
        fallback="render_not_completed",
        limit=160,
    )
    has_source_video = bool(str(payload.get("video_download_url") or "").strip())
    local_supported = _telegram_local_source_video_fallback_available(payload, instruction_text)
    if has_source_video and not local_supported and not browseract_available and not magicfit_available:
        return (
            f"{_telegram_source_video_specialized_fallback_text()} "
            "No verified external render lane is available for this request right now."
        )
    if has_source_video and not local_supported:
        return (
            f"{_telegram_source_video_specialized_fallback_text()} "
            f"Current external render status: {status_text}. "
            f"Estimated render time for the external lane is {eta_text}."
        )
    if not browseract_available and not magicfit_available:
        return (
            "I have the edit request, but no verified render lane is available right now. "
            f"Current video-lane status: {status_text}."
        )
    return (
        "I have the edit request, but the rendered video is not back yet. "
        f"Estimated render time for this lane is {eta_text}. "
        f"Current video-lane status: {status_text}."
    )


def _telegram_render_magicfit_video_reply(
    *,
    container: AppContainer,
    principal_id: str,
    prompt_text: str,
    caption: str,
    instruction_text: str,
) -> dict[str, object]:
    if not _telegram_magicfit_runtime_lane_approved():
        raise RuntimeError("magicfit_runtime_lane_not_approved")
    if not _telegram_magicfit_docker_available():
        raise RuntimeError("magicfit_docker_runtime_unavailable")
    script_path = _telegram_magicfit_video_script_path()
    if not script_path.exists():
        raise RuntimeError("magicfit_render_script_missing")
    timeout_minutes = max(
        1,
        min(18, int(str(os.getenv("EA_TELEGRAM_MAGICFIT_TIMEOUT_MINUTES") or "3").strip() or "3")),
    )
    duration_seconds = max(
        4,
        min(15, int(str(os.getenv("EA_TELEGRAM_MAGICFIT_DURATION_SECONDS") or "10").strip() or "10")),
    )
    aspect_label = str(os.getenv("EA_TELEGRAM_MAGICFIT_ASPECT_LABEL") or "Portrait (9:16)").strip() or "Portrait (9:16)"
    model_label = _telegram_instructional_video_magicfit_model_label(instruction_text)
    shared_temp_root = _telegram_magicfit_shared_temp_root()
    shared_temp_root.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(Exception):
        shared_temp_root.chmod(0o700)
    docker_repo_root = _telegram_magicfit_docker_repo_root()
    with tempfile.TemporaryDirectory(prefix="telegram-magicfit-video-", dir=str(shared_temp_root)) as tmp_dir:
        with contextlib.suppress(Exception):
            Path(tmp_dir).chmod(0o700)
        out_path = (Path(tmp_dir) / "reply.mp4").resolve()
        state_path = (Path(tmp_dir) / "reply.magicfit.json").resolve()
        base_command = [
            "python3",
            str(script_path),
            "--prompt",
            str(prompt_text or "").strip(),
            "--out",
            str(out_path),
            "--state-json",
            str(state_path),
            "--duration",
            str(duration_seconds),
            "--aspect-label",
            aspect_label,
            "--timeout-minutes",
            str(timeout_minutes),
        ]
        if model_label:
            base_command.extend(["--model-label", model_label])
        command = list(base_command)
        if _telegram_magicfit_docker_available():
            browser_cache = _telegram_magicfit_playwright_browsers_host_path().resolve()
            docker_script_path = (docker_repo_root / "scripts" / script_path.name).resolve()
            docker_command = list(base_command)
            docker_command[1] = str(docker_script_path)
            env_file = (Path(tmp_dir) / "magicfit.env").resolve()
            magicfit_email = str(os.getenv("CHUMMER_EA_MAGICFIT_EMAIL") or os.getenv("MAGICFIT_EMAIL") or "").strip()
            magicfit_password = str(
                os.getenv("CHUMMER_EA_MAGICFIT_PASSWORD") or os.getenv("MAGICFIT_PASSWORD") or ""
            ).strip()
            if "\n" in magicfit_email or "\r" in magicfit_email or "\n" in magicfit_password or "\r" in magicfit_password:
                raise RuntimeError("magicfit_credentials_invalid")
            env_file.write_text(
                "\n".join(
                    [
                        f"PLAYWRIGHT_BROWSERS_PATH={browser_cache}",
                        f"CHUMMER_EA_MAGICFIT_EMAIL={magicfit_email}",
                        f"CHUMMER_EA_MAGICFIT_PASSWORD={magicfit_password}",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            with contextlib.suppress(Exception):
                env_file.chmod(0o600)
            uid = os.getuid() if hasattr(os, "getuid") else 1000
            gid = os.getgid() if hasattr(os, "getgid") else 1000
            command = [
                "docker",
                "run",
                "--rm",
                "--user",
                f"{uid}:{gid}",
                "--cpus",
                str(os.getenv("EA_TELEGRAM_MAGICFIT_DOCKER_CPUS") or "2"),
                "--memory",
                str(os.getenv("EA_TELEGRAM_MAGICFIT_DOCKER_MEMORY") or "3g"),
                "--pids-limit",
                str(os.getenv("EA_TELEGRAM_MAGICFIT_DOCKER_PIDS_LIMIT") or "256"),
                "--security-opt",
                "no-new-privileges",
                "--read-only",
                "--tmpfs",
                "/tmp:rw,nosuid,nodev,size=512m",
                "--env-file",
                str(env_file),
                "-v",
                f"{docker_repo_root.resolve()}:{docker_repo_root.resolve()}:ro",
                "-v",
                f"{shared_temp_root.resolve()}:{shared_temp_root.resolve()}:rw",
                "-v",
                f"{browser_cache}:{browser_cache}:ro",
                _telegram_magicfit_docker_image(),
                *docker_command,
            ]
        completed = subprocess.run(
            command,
            cwd=str(product_service_module._repo_root()),
            capture_output=True,
            text=True,
            timeout=(timeout_minutes + 2) * 60,
            check=False,
        )
        if completed.returncode != 0 or not out_path.exists():
            raise RuntimeError(
                compact_text(
                    str(completed.stderr or completed.stdout or "").strip(),
                    fallback="magicfit_render_failed",
                    limit=240,
                )
            )
        receipt = send_telegram_video_for_principal(
            container.tool_runtime,
            principal_id=principal_id,
            video_ref=str(out_path),
            fallback_audio_text=caption or prompt_text or instruction_text,
            caption=caption,
        )
        sidecar: dict[str, object] = {}
        if state_path.exists():
            with contextlib.suppress(Exception):
                loaded = json.loads(state_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    sidecar = loaded
        return {
            "status": "sent",
            "kind": "video",
            "provider": "magicfit",
            "message_ids": list(receipt.message_ids),
            "chat_id": receipt.chat_id,
            "sidecar": sidecar,
        }


def _telegram_weather_code_label(code: int) -> str:
    mapping = {
        0: "clear",
        1: "mostly clear",
        2: "partly cloudy",
        3: "overcast",
        45: "foggy",
        48: "foggy",
        51: "light drizzle",
        53: "drizzle",
        55: "heavy drizzle",
        61: "light rain",
        63: "rain",
        65: "heavy rain",
        71: "light snow",
        73: "snow",
        75: "heavy snow",
        80: "rain showers",
        81: "rain showers",
        82: "heavy rain showers",
        95: "thunderstorms",
    }
    return mapping.get(int(code), "mixed conditions")


def _telegram_weather_reply_text(*, text: str) -> str:
    normalized = str(text or "").strip()
    lower = normalized.lower()
    if "weather" not in lower:
        return ""
    target_index = 1 if "tomorrow" in lower else 0 if "today" in lower else None
    if target_index is None:
        return ""
    try:
        query = urllib.parse.urlencode(
            {
                "latitude": "48.2082",
                "longitude": "16.3738",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                "timezone": "Europe/Vienna",
                "forecast_days": "2",
            }
        )
        request = urllib.request.Request(f"{_TELEGRAM_WEATHER_URL}?{query}", headers={"User-Agent": "EA-Telegram/1.0"})
        with urllib.request.urlopen(request, timeout=6) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return "I could not fetch the Vienna forecast right now."
    daily = dict(payload.get("daily") or {}) if isinstance(payload, dict) else {}
    dates = list(daily.get("time") or [])
    codes = list(daily.get("weather_code") or [])
    highs = list(daily.get("temperature_2m_max") or [])
    lows = list(daily.get("temperature_2m_min") or [])
    precipitation = list(daily.get("precipitation_probability_max") or [])
    if target_index >= len(dates):
        return "I could not read the forecast for that day."
    label = "Tomorrow" if target_index == 1 else "Today"
    code = int(codes[target_index]) if target_index < len(codes) else 0
    high = highs[target_index] if target_index < len(highs) else None
    low = lows[target_index] if target_index < len(lows) else None
    rain = precipitation[target_index] if target_index < len(precipitation) else None
    parts = [f"{label} in Vienna looks {_telegram_weather_code_label(code)}"]
    if high is not None and low is not None:
        parts.append(f"with about {int(round(low))} to {int(round(high))}°C")
    if rain is not None:
        parts.append(f"and up to {int(round(rain))}% precipitation probability")
    return " ".join(parts) + "."


def _telegram_pocket_audio_query_candidate(text: str) -> bool:
    normalized = " ".join(str(text or "").strip().lower().split())
    if not normalized:
        return False
    if _telegram_audiobook_text_intent(normalized):
        return False
    direct_markers = (
        "pocket",
        "audio",
        "recording",
        "aufnahme",
        "file",
        "datei",
        "hanusch",
        "hospital",
        "krankenhaus",
        "spital",
        "conversation",
        "gespräch",
        "gespraech",
        "transcript",
    )
    if any(marker in normalized for marker in direct_markers):
        return True
    if ("before " in normalized or "after " in normalized) and any(
        marker in normalized
        for marker in ("father", "vater", "mother", "mutter", "brother", "bruder", "family", "familie")
    ):
        return True
    return False


def _telegram_audiobook_text_intent(text: str) -> bool:
    normalized = " ".join(str(text or "").strip().lower().split())
    if not normalized:
        return False
    return any(
        marker in normalized
        for marker in (
            "audiobook",
            "audio book",
            "hörbuch",
            "hoerbuch",
            "ebook to audio",
            "kindle audiobook",
            "azw audiobook",
            "azw3 audiobook",
            "mobi audiobook",
            "epub to audio",
            "epub audiobook",
            "make audiobook",
            "make an audiobook",
            "generate audiobook",
            "generate an audiobook",
            "narrate this book",
            "narrate the book",
        )
    )


def _telegram_audiobook_text_request_reply_text(text: str) -> str:
    if not _telegram_audiobook_text_intent(text):
        return ""
    return (
        "Send the EPUB, AZW, AZW3, or MOBI file here in Telegram. I will extract the chapters, detect language and topic, "
        "send voice samples with Use this/Dismiss buttons, then generate the audiobook after a voice is chosen."
    )


def _telegram_audiobook_status_intent(text: str) -> bool:
    normalized = " ".join(str(text or "").strip().lower().split())
    if not normalized:
        return False
    sample_reference = any(
        marker in normalized
        for marker in (
            "voice sample",
            "voice samples",
            "3 samples",
            "three samples",
        )
    )
    if not _telegram_audiobook_text_intent(text) and not sample_reference:
        return False
    return any(
        marker in normalized
        for marker in (
            "status",
            "ready",
            "configured",
            "preflight",
            "why",
            "voice sample",
            "voice samples",
            "3 samples",
            "three samples",
            "not get",
            "don't get",
            "dont get",
            "did not get",
            "didn't get",
        )
    )


def _telegram_audiobook_voice_sample_resend_intent(text: str) -> bool:
    normalized = " ".join(str(text or "").strip().lower().split())
    if not normalized:
        return False
    sample_reference = any(marker in normalized for marker in ("voice sample", "voice samples", "sample", "samples"))
    missing_reference = any(
        marker in normalized
        for marker in (
            "not get",
            "don't get",
            "dont get",
            "did not get",
            "didn't get",
            "missing",
            "resend",
            "send again",
        )
    )
    return sample_reference and missing_reference


def _telegram_audiobook_check_label(check_key: str) -> str:
    labels = {
        "telegram_audiobook_enabled": "Telegram audiobook intake is disabled",
        "telegram_epub_enabled": "Telegram audiobook intake is disabled",
        "jobs_root_durable": "audiobook job storage is not durable-storage-backed",
        "jobs_root_writable": "audiobook job storage is not writable",
        "external_tts_enabled": "external audiobook TTS is disabled",
        "unmixr_auto_render_enabled": "audio generation is disabled",
        "voice_catalog_configured": "no audiobook voices are configured",
        "voice_catalog_audition_ready": "fewer than three audiobook voices are available",
        "unmixr_api_key_slot_present": "no owned audio generation account slot is configured",
        "player_access_signing_secret_present": "player-scoped playback signing is not configured",
        "player_access_base_url_present": "player-scoped playback base URL is not configured",
        "audiobookshelf_import_root_durable": "Audiobookshelf import storage is not durable-storage-backed",
        "audiobookshelf_import_root_writable": "Audiobookshelf import storage is not writable",
        "audiobookshelf_public_share_configured": "Audiobookshelf public-share API is not configured",
    }
    return labels.get(check_key, check_key.replace("_", " "))


def _telegram_latest_active_audiobook_job_for_chat(chat_id: str) -> dict[str, object]:
    normalized_chat_id = str(chat_id or "").strip()
    if not normalized_chat_id:
        return {}
    try:
        root = audiobook_jobs_root()
    except Exception:
        return {}
    candidates: list[tuple[float, dict[str, object]]] = []
    for manifest_path in sorted(root.glob("*/job.json")):
        try:
            job = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        telegram = dict(job.get("telegram") or {})
        if str(telegram.get("chat_id") or "").strip() != normalized_chat_id:
            continue
        status = str(job.get("status") or "").strip()
        if status in {"audiobookshelf_imported", "failed_m4b_merge"}:
            continue
        try:
            mtime = manifest_path.stat().st_mtime
        except OSError:
            mtime = 0.0
        candidates.append((mtime, job))
    if not candidates:
        return {}
    candidates.sort(key=lambda row: row[0], reverse=True)
    return dict(candidates[0][1])


def _telegram_active_audiobook_status_reply_text(
    *,
    chat_id: str,
    text: str = "",
    bot_config: dict[str, object] | None = None,
) -> str:
    job = _telegram_latest_active_audiobook_job_for_chat(chat_id)
    if not job:
        return ""
    metadata = dict(job.get("metadata") or {})
    title = str(metadata.get("title") or metadata.get("source_filename") or "the audiobook").strip()
    voice_selection = dict(dict(job.get("provider") or {}).get("voice_selection") or {})
    reason = str(voice_selection.get("reason") or "").strip()
    if (
        str(job.get("status") or "").strip() == "waiting_voice_selection"
        and str(voice_selection.get("status") or "").strip() == "waiting_user_choice"
        and reason == "selected_voice_provider_balance_blocked"
    ):
        pending = [row for row in list(voice_selection.get("pending_batch") or []) if isinstance(row, dict)]
        label = str(dict(pending[0]).get("label") or "the replacement voice").strip() if pending else "the replacement voice"
        delivery = dict(dict(job.get("telegram") or {}).get("voice_sample_delivery") or {})
        sent = str(delivery.get("status") or "").strip() == "sent"
        selected_voice = str(dict(voice_selection.get("selected") or {}).get("label") or "").strip()
        selected_line = f" The originally selected voice is {selected_voice}." if selected_voice else ""
        sample_line = ""
        if pending and _telegram_audiobook_voice_sample_resend_intent(text):
            sample_receipts = _telegram_send_audiobook_voice_samples(
                bot_config=dict(bot_config or {}),
                chat_id=chat_id,
                job=job,
            )
            if sample_receipts:
                job = record_audiobook_voice_sample_delivery(job=job, sample_receipts=sample_receipts)
                sent_count = sum(1 for item in sample_receipts if str(dict(item).get("status") or "").strip() == "sent")
                if sent_count:
                    sample_word = "sample" if sent_count == 1 else "samples"
                    sample_line = f"I resent {sent_count} audiobook voice {sample_word}."
        if not sample_line:
            sample_line = (
                f"I already sent the replacement sample for {label} with Use this/Dismiss buttons."
                if sent
                else f"The replacement sample for {label} is prepared but Telegram delivery is not confirmed."
            )
        return (
            f"Audiobook status for {title}: waiting for your explicit voice choice. "
            "The selected provider voice is blocked by credits/balance, so I stopped before publishing with a different voice."
            f"{selected_line} {sample_line}"
        )
    if (
        str(job.get("status") or "").strip() == "waiting_voice_selection"
        and str(voice_selection.get("status") or "").strip() == "waiting_user_choice"
        and reason == "selected_voice_author_gender_mismatch"
    ):
        pending = [row for row in list(voice_selection.get("pending_batch") or []) if isinstance(row, dict)]
        profile = dict(voice_selection.get("book_profile") or {})
        author_gender_signal = str(profile.get("author_gender_signal") or "").strip().lower()
        label = str(dict(pending[0]).get("label") or "the replacement voice").strip() if pending else "the replacement voice"
        delivery = dict(dict(job.get("telegram") or {}).get("voice_sample_delivery") or {})
        sent = str(delivery.get("status") or "").strip() == "sent"
        selected_voice = str(dict(voice_selection.get("selected") or {}).get("label") or "").strip()
        selected_line = f" The stale selected voice was {selected_voice}." if selected_voice else ""
        gender_line = (
            f"I inferred a {author_gender_signal} author signal"
            if author_gender_signal in {"male", "female"}
            else "The selected voice does not match the author gender signal"
        )
        sample_line = ""
        if pending and _telegram_audiobook_voice_sample_resend_intent(text):
            sample_receipts = _telegram_send_audiobook_voice_samples(
                bot_config=dict(bot_config or {}),
                chat_id=chat_id,
                job=job,
            )
            if sample_receipts:
                job = record_audiobook_voice_sample_delivery(job=job, sample_receipts=sample_receipts)
                sent_count = sum(1 for item in sample_receipts if str(dict(item).get("status") or "").strip() == "sent")
                if sent_count:
                    sample_word = "sample" if sent_count == 1 else "samples"
                    sample_line = f"I resent {sent_count} matching audiobook voice {sample_word}."
        if not sample_line:
            sample_line = (
                f"I already sent the matching replacement sample for {label} with Use this/Dismiss buttons."
                if sent
                else f"The matching replacement sample for {label} is prepared but Telegram delivery is not confirmed."
            )
        return (
            f"Audiobook status for {title}: waiting for your explicit voice choice. "
            f"{gender_line}, so I stopped before continuing with a mismatched voice."
            f"{selected_line} {sample_line}"
        )
    return telegram_epub_reply_text(job)


def _telegram_audiobook_runtime_status_reply_text(
    text: str,
    *,
    chat_id: str = "",
    bot_config: dict[str, object] | None = None,
) -> str:
    if not _telegram_audiobook_status_intent(text):
        return ""
    active_job_reply = _telegram_active_audiobook_status_reply_text(
        chat_id=chat_id,
        text=text,
        bot_config=bot_config,
    )
    if active_job_reply:
        return active_job_reply
    receipt = audiobook_runtime_preflight()
    provider = dict(receipt.get("provider") or {})
    access = dict(receipt.get("access") or {})
    failed = [str(item) for item in list(receipt.get("failed_checks") or []) if str(item).strip()]
    warned = [str(item) for item in list(receipt.get("warned_checks") or []) if str(item).strip()]
    voice_count = int(provider.get("voice_catalog_count") or 0)
    min_voices = int(provider.get("voice_audition_min_candidates") or 3)
    sample_blockers = [
        key
        for key in (
            "telegram_audiobook_enabled",
            "jobs_root_durable",
            "jobs_root_writable",
            "external_tts_enabled",
            "unmixr_auto_render_enabled",
            "voice_catalog_configured",
        )
        if key in failed
    ]
    if voice_count < min_voices and "voice_catalog_audition_ready" not in sample_blockers:
        sample_blockers.append("voice_catalog_audition_ready")
    if int(provider.get("api_key_slot_count") or 0) <= 0 and "unmixr_api_key_slot_present" not in sample_blockers:
        sample_blockers.append("unmixr_api_key_slot_present")
    completion_blockers = [
        key
        for key in (
            "player_access_signing_secret_present",
            "player_access_base_url_present",
            "audiobookshelf_import_root_durable",
            "audiobookshelf_import_root_writable",
            "audiobookshelf_public_share_configured",
        )
        if key in failed or key in warned
    ]
    if sample_blockers:
        blocker_text = "; ".join(_telegram_audiobook_check_label(key) for key in sample_blockers[:5])
        return (
            "Audiobook voice samples are not live-ready yet. "
            f"Current blockers: {blocker_text}. "
            f"Voice catalog: {voice_count}/{min_voices}; audio generation account slots configured: {int(provider.get('api_key_slot_count') or 0)}. "
            "After those blockers clear, send the source ebook again and I should return three voice samples with Use this/Dismiss buttons. "
            f"Completion blockers still tracked: {len(completion_blockers)}."
        )
    if completion_blockers:
        blocker_text = "; ".join(_telegram_audiobook_check_label(key) for key in completion_blockers[:4])
        return (
            "Audiobook voice samples are ready, but full delivery is not complete-ready yet. "
            f"Voice catalog: {voice_count}/{min_voices}. Remaining completion blockers: {blocker_text}."
        )
    public_share = "enabled" if access.get("audiobookshelf_public_share_enabled") else "disabled"
    return (
        "Audiobook intake and voice samples are ready. "
        f"Voice catalog: {voice_count}/{min_voices}; Audiobookshelf public share is {public_share}. "
        "Send an EPUB, AZW, AZW3, or MOBI file here in Telegram to get the three voice samples."
    )


def _telegram_latest_audiobook_playback_buttons_for_chat(
    *,
    bot_config: dict[str, object],
    chat_id: str,
) -> tuple[str, list[list[tuple[str, str]]]]:
    normalized_chat_id = str(chat_id or "").strip()
    if not normalized_chat_id:
        return "", []
    try:
        root = audiobook_jobs_root()
    except Exception:
        return "", []
    candidates: list[tuple[str, Path, dict[str, object]]] = []
    for manifest_path in sorted(root.glob("*/job.json")):
        try:
            job = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        telegram = dict(job.get("telegram") or {})
        if str(telegram.get("chat_id") or "").strip() != normalized_chat_id:
            continue
        imported = dict(job.get("audiobookshelf_import") or {})
        public_share = dict(imported.get("public_share") or {})
        delivery = dict(public_share.get("telegram_delivery") or {})
        if str(public_share.get("status") or "").strip() != "public_share_ready":
            continue
        if str(delivery.get("status") or "").strip() != "sent":
            continue
        if str(dict(job.get("playback_acceptance") or {}).get("status") or "").strip() == "accepted":
            continue
        candidates.append((str(job.get("updated_at") or ""), manifest_path.parent, job))
    if not candidates:
        return "", []
    _updated_at, _job_dir, job = sorted(candidates, key=lambda row: (row[0], row[1].name))[-1]
    updated_job, buttons = _telegram_audiobook_playback_acceptance_buttons(
        bot_config=bot_config,
        chat_id=normalized_chat_id,
        job=job,
    )
    if not buttons:
        return "", []
    metadata = dict(updated_job.get("metadata") or {})
    title = str(metadata.get("title") or metadata.get("source_filename") or "the latest audiobook").strip()
    return title, buttons


def _telegram_audio_upload_announcement_reply_text(text: str) -> str:
    normalized = " ".join(str(text or "").strip().lower().split())
    if not normalized:
        return ""
    upload_verbs = (
        "ich schicke",
        "ich sende",
        "ich lade",
        "i am sending",
        "i'm sending",
        "i will send",
        "i upload",
        "i am uploading",
        "i'm uploading",
    )
    audio_markers = ("audio", "aufnahme", "recording", "voice", "sprachmemo", "sprachnachricht")
    if not any(phrase in normalized for phrase in upload_verbs):
        return ""
    if not any(marker in normalized for marker in audio_markers):
        return ""
    if any(marker in normalized for marker in ("ich ", "schicke", "sende", "aufnahme", "gespräch", "vater")):
        return (
            "Ja, schick die Audioaufnahme hier in Telegram. Wenn sie von dir und deinem Vater ist, kann EA sie "
            "entgegennehmen, transkribieren und als private Gesprächsnotiz einordnen."
        )
    return "Yes, send the audio recording here in Telegram. EA can receive it, transcribe it, and file it as a private conversation note."


def _telegram_parse_relative_date_filter(text: str, *, keyword: str) -> str:
    normalized = " ".join(str(text or "").strip().lower().split())
    month_names = "|".join(sorted((re.escape(name) for name in _TELEGRAM_MONTH_ALIASES.keys()), key=len, reverse=True))
    patterns = (
        rf"\b{re.escape(keyword)}\s+(\d{{4}}-\d{{2}}-\d{{2}})\b",
        rf"\b{re.escape(keyword)}\s+({month_names})\s+(\d{{1,2}})(?:,?\s+(\d{{4}}))?\b",
        rf"\b{re.escape(keyword)}\s+(\d{{1,2}})\.(\d{{1,2}})\.(\d{{4}})?\b",
    )
    for pattern in patterns:
        match = re.search(pattern, normalized, flags=re.IGNORECASE)
        if not match:
            continue
        groups = [str(group or "").strip() for group in match.groups()]
        if len(groups) >= 1 and re.fullmatch(r"\d{4}-\d{2}-\d{2}", groups[0]):
            return groups[0]
        if len(groups) >= 2 and groups[0].lower() in _TELEGRAM_MONTH_ALIASES:
            month = _TELEGRAM_MONTH_ALIASES[groups[0].lower()]
            day = int(groups[1])
            year = int(groups[2]) if len(groups) >= 3 and groups[2] else datetime.now(ZoneInfo("Europe/Vienna")).year
            try:
                return datetime(year, month, day, tzinfo=ZoneInfo("UTC")).date().isoformat()
            except Exception:
                return ""
        if len(groups) >= 2 and groups[0].isdigit() and groups[1].isdigit():
            day = int(groups[0])
            month = int(groups[1])
            year = int(groups[2]) if len(groups) >= 3 and groups[2] else datetime.now(ZoneInfo("Europe/Vienna")).year
            try:
                return datetime(year, month, day, tzinfo=ZoneInfo("UTC")).date().isoformat()
            except Exception:
                return ""
    return ""


def _telegram_pocket_audio_query_text(text: str) -> str:
    normalized = " ".join(str(text or "").strip().split())
    if not normalized:
        return ""
    stripped = re.sub(
        r"\b(before|after)\s+([A-Za-zÄÖÜäöüß]+|\d{1,2}\.\d{1,2}\.?\d{0,4}|\d{4}-\d{2}-\d{2})(?:\s+\d{1,4})?\b",
        " ",
        normalized,
        flags=re.IGNORECASE,
    )
    fillers = (
        "please",
        "summarize",
        "summary",
        "tell me",
        "why it matches",
        "send me",
        "show me",
        "best",
        "pocket audio",
        "pocket recording",
        "audio file",
        "audio",
        "recording",
        "file",
    )
    lowered = " ".join(stripped.lower().split())
    for filler in fillers:
        lowered = lowered.replace(filler, " ")
    cleaned = re.sub(r"[^a-z0-9äöüß\s\-]", " ", lowered, flags=re.IGNORECASE)
    return " ".join(cleaned.split())


def _telegram_format_pocket_audio_match(item: dict[str, object], *, before: str = "", after: str = "") -> str:
    title = str(item.get("title") or "").strip() or "Pocket recording"
    recorded = str(item.get("recording_at") or "").strip()
    location = str(item.get("location_name") or "").strip() or str(item.get("location_address") or "").strip() or "location unknown"
    summary = str(item.get("summary_markdown") or "").strip() or str(item.get("transcript_excerpt") or "").strip()
    summary = re.sub(r"\s+", " ", summary).strip()
    confidence = float(item.get("location_confidence") or 0.0)
    lines = [f"Best match: {title}."]
    if recorded:
        lines.append(f"Recorded: {recorded}.")
    if before or after:
        window_bits = []
        if before:
            window_bits.append(f"before {before}")
        if after:
            window_bits.append(f"after {after}")
        lines.append(f"Date filter: {' and '.join(window_bits)}.")
    lines.append(f"Place match: {location} (confidence {confidence:.2f}).")
    if summary:
        lines.append(f"Why it matches: {summary[:280]}.")
    return " ".join(lines)


def _telegram_extract_json_object(text: str) -> dict[str, object]:
    normalized = str(text or "").strip()
    if not normalized:
        return {}
    try:
        parsed = json.loads(normalized)
    except Exception:
        parsed = None
    if isinstance(parsed, dict):
        return parsed
    start = normalized.find("{")
    end = normalized.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        parsed = json.loads(normalized[start : end + 1])
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _telegram_recent_pocket_candidate_suggestions(
    container: AppContainer,
    *,
    principal_id: str,
) -> dict[str, object] | None:
    for row in container.channel_runtime.list_recent_observations(limit=60, principal_id=principal_id):
        if str(row.channel or "").strip() != "telegram":
            continue
        if str(row.event_type or "").strip() != "telegram.pocket_candidate_suggestions_sent":
            continue
        return dict(row.payload or {})
    return None


def _telegram_pocket_candidate_selection(text: str) -> int:
    normalized = " ".join(str(text or "").strip().lower().split())
    match = re.fullmatch(r"(?:send|schick|sende|deliver|open|play)\s+(?:candidate\s+|kandidat\s+)?([1-3])", normalized)
    if match is None:
        return 0
    try:
        return int(match.group(1))
    except Exception:
        return 0


def _telegram_record_pocket_candidate_suggestions(
    container: AppContainer,
    *,
    principal_id: str,
    query: str,
    before: str,
    after: str,
    candidates: list[dict[str, object]],
) -> None:
    if not candidates:
        return
    payload = {
        "query": str(query or "").strip(),
        "before": str(before or "").strip(),
        "after": str(after or "").strip(),
        "candidates": [
            {
                "index": index + 1,
                "recording_id": str(item.get("recording_id") or "").strip(),
                "title": str(item.get("title") or "").strip(),
                "recording_at": str(item.get("recording_at") or "").strip(),
                "location_name": str(item.get("location_name") or "").strip(),
                "reason": str(item.get("reason") or "").strip(),
            }
            for index, item in enumerate(candidates[:3])
        ],
    }
    dedupe_material = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    container.channel_runtime.ingest_observation(
        principal_id=principal_id,
        channel="telegram",
        event_type="telegram.pocket_candidate_suggestions_sent",
        payload=payload,
        source_id="telegram-pocket-semantic-fallback",
        dedupe_key=f"{principal_id}|telegram-pocket-candidates|{hashlib.sha256(dedupe_material.encode('utf-8')).hexdigest()}",
    )


def _telegram_pocket_audio_semantic_candidates(
    *,
    container: AppContainer,
    principal_id: str,
    query: str,
    before: str,
    after: str,
) -> list[dict[str, object]]:
    service = build_product_service(container)
    search = service.search_pocket_recordings(
        principal_id=principal_id,
        actor="telegram-semantic-fallback",
        query="",
        before=before,
        after=after,
        limit=18,
    )
    items = list(search.get("items") or [])
    if not items:
        return []
    candidates = [
        {
            "recording_id": str(item.get("recording_id") or "").strip(),
            "title": str(item.get("title") or "").strip(),
            "recording_at": str(item.get("recording_at") or "").strip(),
            "location_name": str(item.get("location_name") or "").strip(),
            "location_address": str(item.get("location_address") or "").strip(),
            "summary_markdown": str(item.get("summary_markdown") or "").strip(),
            "transcript_text": str(item.get("transcript_text") or "").strip(),
            "transcript_excerpt": str(item.get("transcript_excerpt") or "").strip(),
        }
        for item in items[:12]
    ]
    messages = [
        {
            "role": "system",
            "content": (
                "Choose the most likely Pocket audio recordings for the user's memory query. "
                "Use only the provided candidates. "
                "Return strict JSON: {\"candidates\":[{\"recording_id\":\"...\",\"reason\":\"...\"}]}. "
                "Prefer up to 3 candidates. Respect place/date hints in the query."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "query": str(query or "").strip(),
                    "before": str(before or "").strip(),
                    "after": str(after or "").strip(),
                    "candidates": candidates,
                },
                ensure_ascii=False,
            ),
        },
    ]
    try:
        result = _responses_route_module()._generate_upstream_text(
            prompt=str(query or "").strip(),
            messages=messages,
            requested_model=str(os.getenv("EA_TELEGRAM_RESPONSES_MODEL") or "ea-coder-fast").strip() or "ea-coder-fast",
            max_output_tokens=220,
            chatplayground_audit_callback=None,
            chatplayground_audit_callback_only=False,
            chatplayground_audit_principal_id=principal_id,
            preferred_onemin_labels=(),
            request_deadline_monotonic=time.monotonic() + 8.0,
        )
    except Exception:
        return []
    payload = _telegram_extract_json_object(str(getattr(result, "text", "") or ""))
    raw_candidates = list(payload.get("candidates") or []) if isinstance(payload.get("candidates"), list) else []
    candidate_by_id = {str(item.get("recording_id") or "").strip(): item for item in candidates if str(item.get("recording_id") or "").strip()}
    verified: list[dict[str, object]] = []
    for row in raw_candidates:
        if not isinstance(row, dict):
            continue
        recording_id = str(row.get("recording_id") or "").strip()
        if not recording_id or recording_id not in candidate_by_id:
            continue
        verified.append(
            {
                **candidate_by_id[recording_id],
                "reason": str(row.get("reason") or "").strip(),
            }
        )
        if len(verified) >= 3:
            break
    return verified


def _telegram_pocket_audio_reply_text(*, container: AppContainer, principal_id: str, text: str) -> str:
    selection = _telegram_pocket_candidate_selection(text)
    if selection > 0:
        suggestions = _telegram_recent_pocket_candidate_suggestions(container, principal_id=principal_id)
        if not suggestions:
            return "I do not have a recent Pocket candidate list to pick from yet."
        candidates = list(suggestions.get("candidates") or [])
        if selection > len(candidates):
            return f"I only have {len(candidates)} recent Pocket candidates to choose from."
        selected = dict(candidates[selection - 1] or {})
        recording_id = str(selected.get("recording_id") or "").strip()
        if not recording_id:
            return "That Pocket candidate is missing a recording id."
        service = build_product_service(container)
        delivered = service.deliver_pocket_recording_to_telegram(
            principal_id=principal_id,
            actor="telegram",
            recording_id=recording_id,
        )
        return f"Sent: {str(delivered.get('title') or 'Pocket recording').strip()}."
    if not _telegram_pocket_audio_query_candidate(text):
        return ""
    service = build_product_service(container)
    before = _telegram_parse_relative_date_filter(text, keyword="before")
    after = _telegram_parse_relative_date_filter(text, keyword="after")
    query = _telegram_pocket_audio_query_text(text) or str(text or "").strip()
    search = service.search_pocket_recordings(
        principal_id=principal_id,
        actor="telegram",
        query=query,
        before=before,
        after=after,
        limit=3,
    )
    items = list(search.get("items") or [])
    if not items:
        semantic_candidates = _telegram_pocket_audio_semantic_candidates(
            container=container,
            principal_id=principal_id,
            query=query,
            before=before,
            after=after,
        )
        if not semantic_candidates:
            return "I could not find a matching Pocket recording for that place/date query."
        if len(semantic_candidates) == 1:
            return _telegram_format_pocket_audio_match(dict(semantic_candidates[0] or {}), before=before, after=after)
        _telegram_record_pocket_candidate_suggestions(
            container,
            principal_id=principal_id,
            query=query,
            before=before,
            after=after,
            candidates=semantic_candidates,
        )
        lines = ["I found these likely Pocket candidates:"]
        for index, item in enumerate(semantic_candidates[:3], start=1):
            detail = f"{index}. {str(item.get('title') or '').strip()} | {str(item.get('recording_at') or '').strip()}"
            location = str(item.get("location_name") or "").strip()
            if location:
                detail += f" | {location}"
            reason = str(item.get("reason") or "").strip()
            if reason:
                detail += f" | {reason}"
            lines.append(detail)
        lines.append("Reply with `send 1`, `send 2`, or `send 3` to get one on Telegram.")
        return "\n".join(lines)
    return _telegram_format_pocket_audio_match(dict(items[0] or {}), before=before, after=after)


def _telegram_probe_reply_text(text: str) -> str:
    normalized = " ".join(str(text or "").strip().split())
    if not normalized:
        return ""
    if normalized in {"?", "??", "???"}:
        return "Ask directly."
    alpha = "".join(ch for ch in normalized.lower() if ch.isalpha() or ch.isspace()).strip()
    if alpha in {"test", "ping", "hello", "hi", "hey", "are you there", "you there", "check"}:
        return "I'm here. Ask directly."
    return ""


def _telegram_low_signal_followup_cue(text: str) -> bool:
    normalized = " ".join(str(text or "").strip().lower().split())
    if not normalized:
        return False
    alpha = "".join(ch for ch in normalized if ch.isalpha() or ch.isspace()).strip()
    alpha_words = [word for word in alpha.split() if word]
    if alpha and all(word in {"done", "finished", "complete", "completed", "ok", "okay"} for word in alpha.split() if word):
        return True
    if alpha_words and len(alpha_words) <= 3 and all(
        word in {"well", "score", "and", "why", "again", "the", "other", "that", "one"}
        for word in alpha_words
    ):
        return True
    return normalized in {
        "again",
        "again?",
        "well",
        "well?",
        "and",
        "and?",
        "why",
        "why?",
        "the other",
        "the other?",
        "that one",
        "that one?",
    }


def _telegram_last_resort_reply_text(text: str) -> str:
    normalized = " ".join(str(text or "").strip().split())
    if not normalized:
        return ""
    probe_reply = _telegram_probe_reply_text(normalized)
    if probe_reply:
        return probe_reply
    alpha = "".join(ch for ch in normalized.lower() if ch.isalpha() or ch.isspace()).strip()
    words = [part for part in alpha.split() if part]
    word_count = len(words)
    if (
        any(marker in words for marker in {"check", "receiver", "working", "alive", "there"})
        or "reply with one short line" in normalized.lower()
    ):
        return "I'm here. Ask directly."
    if word_count <= 2:
        return "Ask directly."
    return "I'm here. Give me a concrete task."


def _telegram_action_required_only_mode() -> bool:
    raw = str(os.getenv("EA_TELEGRAM_ACTION_REQUIRED_ONLY", "1") or "1").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _telegram_processing_acks_enabled() -> bool:
    raw = str(os.getenv("EA_TELEGRAM_SEND_PROCESSING_ACKS", "0") or "0").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _telegram_should_suppress_async_fallback_reply(
    *,
    reply_text: str,
    used_fallback_only: bool,
    probe_reply: str,
    last_resort_reply: str,
) -> bool:
    if not _telegram_action_required_only_mode() or not used_fallback_only:
        return False
    normalized = " ".join(str(reply_text or "").strip().split())
    if not normalized:
        return False
    fallback_texts = {
        " ".join(str(probe_reply or "").strip().split()),
        " ".join(str(last_resort_reply or "").strip().split()),
        "Ask directly.",
    }
    if normalized in fallback_texts:
        return True
    return _telegram_reply_is_low_value_nonaction(normalized)


def _telegram_should_suppress_sync_nonaction_reply(*, reply_text: str, has_action_surface: bool) -> bool:
    if not _telegram_action_required_only_mode():
        return False
    if telegram_ooda_text_is_internal_noise(reply_text):
        return True
    if has_action_surface:
        return False
    normalized = " ".join(str(reply_text or "").strip().split())
    if not normalized:
        return False
    return _telegram_reply_is_low_value_nonaction(normalized)


def _telegram_reply_is_low_value_nonaction(reply_text: str) -> bool:
    normalized = " ".join(str(reply_text or "").strip().split())
    if not normalized:
        return False
    lowered = normalized.lower()
    if lowered in {
        "ask directly.",
        "i'm here. ask directly.",
        "i'm here. give me a concrete task.",
        "let me check that and get back to you here.",
    }:
        return True
    if lowered.startswith("got the document. add a short note "):
        return True
    if lowered.startswith("got the video. add one short instruction "):
        return True
    if lowered.startswith("got it") and any(
        marker in lowered
        for marker in (
            "transcription is deferred",
            "i can't see or hear it right now",
            "i can't see their visual content",
            "i see you sent",
        )
    ):
        return True
    if lowered.startswith("from what's grounded:") and any(
        marker in lowered for marker in ("transcription is deferred", "photos:", "video message")
    ):
        return True
    return (
        lowered.startswith("i'm here.")
        or lowered.startswith("working on it.")
        or lowered.startswith("saved. ea is processing")
        or lowered.startswith("saved. i staged")
    )


def _record_telegram_sync_reply_suppressed(
    container: AppContainer,
    *,
    principal_id: str,
    chat_id: str,
    dedupe_key: str,
    current_message_id: str,
    source_text: str,
    reply_text: str,
) -> None:
    marker = f"{str(dedupe_key or '').strip()}:reply_suppressed_no_user_action" if str(dedupe_key or "").strip() else ""
    container.channel_runtime.ingest_observation(
        principal_id=principal_id,
        channel="telegram",
        event_type="telegram.reply_suppressed",
        payload={
            "chat_id": str(chat_id or "").strip(),
            "prompt_text": str(source_text or "").strip(),
            "suppressed_reply_text": str(reply_text or "").strip(),
            "stage": "sync_fallback_suppressed_no_user_action",
            "reason": "telegram_action_required_only",
        },
        source_id=f"telegram:{chat_id}" if chat_id else "telegram",
        external_id=str(current_message_id or "").strip(),
        dedupe_key=marker,
    )


def _telegram_meta_assistant_reply_text(text: str) -> str:
    normalized = " ".join(str(text or "").strip().split())
    if not normalized:
        return ""
    lower = normalized.lower()
    schedule_markers = (
        "next appointment",
        "next meeting",
        "next calendar",
        "my calendar",
        "my schedule",
        "next event",
        "what's next",
        "whats next",
        "what is next",
        "appointment",
    )
    if any(
        phrase in lower
        for phrase in (
            "finally work",
            "are you working",
            "can you work",
            "do you work",
            "work properly",
            "work now",
            "help me",
        )
    ):
        return "I'm here. Give me a concrete task."
    if (
        any(phrase in lower for phrase in ("can u answer everything now", "can you answer everything now"))
        and not any(marker in lower for marker in schedule_markers)
    ):
        return (
            "I can answer from grounded EA state when the workspace has the context: schedule, inbox, links, and follow-ups."
        )
    if any(
        phrase in lower
        for phrase in (
            "what can you do",
            "what do you do",
            "how can you help",
            "what are you able to do",
        )
    ):
        return "I can help with schedule, inbox, links, and grounded EA follow-ups. Ask directly."
    return ""


def _telegram_recent_messages_include_google_photos_context(
    container: AppContainer,
    *,
    principal_id: str,
    limit: int = 8,
) -> bool:
    messages = _telegram_recent_conversation_messages(
        container,
        principal_id=principal_id,
        current_message_id="",
        limit=limit,
    )
    for item in reversed(messages):
        role = str(item.get("role") or "").strip().lower()
        if role != "user":
            continue
        for part in list(item.get("content") or []):
            if not isinstance(part, dict):
                continue
            text_part = str(part.get("text") or "").strip().lower()
            if not text_part:
                continue
            if "google photos" in text_part or "picture" in text_part or "photo" in text_part:
                return True
    return False


def _telegram_google_photos_accounts(
    container: AppContainer,
    *,
    principal_id: str,
) -> tuple[list[object], list[object], str]:
    try:
        accounts = list(google_oauth_service.list_google_accounts(container=container, principal_id=principal_id))
    except Exception:
        accounts = []
    reconnect_url = ""
    try:
        reconnect_url = str(
            google_oauth_service.build_google_oauth_start(
                principal_id=principal_id,
                scope_bundle="full_workspace_photos",
            ).auth_url
            or ""
        ).strip()
    except Exception:
        reconnect_url = ""
    enabled_accounts = [
        account
        for account in accounts
        if str(account.token_status or "").strip().lower() != "revoked"
        and str(account.binding.status or "").strip().lower() == "enabled"
    ]
    photo_accounts = [
        account
        for account in enabled_accounts
        if google_oauth_service.GOOGLE_SCOPE_PHOTOS_PICKER in set(account.granted_scopes or ())
    ]
    return enabled_accounts, photo_accounts, reconnect_url


def _telegram_google_photos_status_reply_text(
    container: AppContainer,
    *,
    principal_id: str,
    include_next_step: bool = True,
) -> str:
    enabled_accounts, photo_accounts, reconnect_url = _telegram_google_photos_accounts(
        container,
        principal_id=principal_id,
    )
    if not enabled_accounts:
        reply = (
            "Not yet. I do not see a connected Google account for this EA principal. "
            "And even with Google Photos access, I can only analyze photos you explicitly select through Google Photos Picker."
        )
        if include_next_step and reconnect_url:
            reply += f" Start here: {reconnect_url}"
        return reply
    if not photo_accounts:
        account_labels = ", ".join(
            str(account.google_email or "").strip()
            for account in enabled_accounts[:2]
            if str(account.google_email or "").strip()
        )
        if account_labels:
            reply = (
                f"Not yet. I can see Google connected for {account_labels}, but not with Google Photos Picker access. "
                "I also cannot silently search the whole library; I can only inspect photos you explicitly select."
            )
            if include_next_step and reconnect_url:
                reply += f" Reconnect with Photos Picker here, once per Google account: {reconnect_url}"
            return reply
        reply = (
            "Not yet. Google is connected, but I do not have Google Photos Picker access on this EA principal. "
            "I can only inspect photos you explicitly select."
        )
        if include_next_step and reconnect_url:
            reply += f" Start here: {reconnect_url}"
        return reply
    account_labels = ", ".join(
        str(account.google_email or "").strip()
        for account in photo_accounts[:2]
        if str(account.google_email or "").strip()
    )
    if not account_labels:
        account_labels = "the connected Google Photos account"
    return (
        f"Partly. I can work with Google Photos for {account_labels}, but only on photos you explicitly select in the picker. "
        "I cannot silently search the whole library yet. If you select likely photos, I can help identify the Noah mattress picture."
    )


def _telegram_google_photos_picker_action_reply_text(
    container: AppContainer,
    *,
    principal_id: str,
) -> str:
    enabled_accounts, photo_accounts, reconnect_url = _telegram_google_photos_accounts(
        container,
        principal_id=principal_id,
    )
    if not enabled_accounts or not photo_accounts:
        return _telegram_google_photos_status_reply_text(
            container,
            principal_id=principal_id,
            include_next_step=True,
        )
    account_email = str(photo_accounts[0].google_email or "").strip()
    product_service = build_product_service(container)
    try:
        session = product_service.create_google_photos_picker_session(
            principal_id=principal_id,
            actor="telegram",
            account_email=account_email,
            max_item_count=50,
            autoclose=True,
        )
    except Exception as exc:
        detail = str(exc or "").strip().lower()
        if detail.startswith("google_photos_service_disabled"):
            activation_url = ""
            raw_detail = str(exc or "").strip()
            if ":" in raw_detail:
                activation_url = raw_detail.split(":", 1)[1].strip()
            reply = (
                f"Google Photos Picker access is connected for {account_email or 'the connected account'}, "
                "but the Google Photos Picker API is disabled in the Google Cloud project for this app."
            )
            if activation_url:
                reply += f" Enable it here: {activation_url}"
            return reply
        if detail == "google_photos_forbidden":
            reply = (
                f"Google Photos Picker access is connected for {account_email or 'the connected account'}, "
                "but Google is still refusing picker sessions for this app with a 403."
            )
        else:
            reply = (
                f"Google Photos Picker access is connected for {account_email or 'the connected account'}, "
                "but I could not start a picker session right now."
            )
        if reconnect_url:
            reply += f" Reconnect here if needed: {reconnect_url}"
        return reply
    picker_uri = str(session.get("picker_uri") or "").strip()
    if not picker_uri:
        return (
            f"Google Photos Picker access is connected for {account_email or 'the connected account'}, "
            "but Google did not return a picker link right now."
        )
    return (
        f"Google Photos Picker is ready for {account_email or 'the connected account'}. "
        f"Open this picker link and select the likely photos: {picker_uri}"
    )


def _telegram_google_photos_reply_text(
    container: AppContainer,
    *,
    principal_id: str,
    text: str,
) -> str:
    normalized = str(text or "").strip()
    if not normalized:
        return ""
    lower = normalized.lower()
    if "google photos" not in lower and "picture" not in lower and "photo" not in lower:
        return ""
    discovery_markers = (
        "find me",
        "find ",
        "can you find",
        "look for",
        "search",
        "where is",
        "do you have access",
        "you should have access",
    )
    if not any(marker in lower for marker in discovery_markers):
        return ""
    return _telegram_google_photos_status_reply_text(
        container,
        principal_id=principal_id,
        include_next_step=True,
    )


def _answerly_document_qa_configs() -> list[dict[str, str]]:
    shared_base_url = str(os.getenv("EA_ANSWERLY_BASE_URL") or "https://ai.api.answerly.io").strip().rstrip("/")
    configs: list[dict[str, str]] = []

    def _append_config(scope: str, *, api_key_env: str, agent_id_env: str, label_env: str, default_label: str) -> None:
        api_key = str(os.getenv(api_key_env) or "").strip()
        agent_id = str(os.getenv(agent_id_env) or "").strip()
        if not api_key or not agent_id or not shared_base_url:
            return
        configs.append(
            {
                "scope": scope,
                "api_key": api_key,
                "agent_id": agent_id,
                "label": str(os.getenv(label_env) or default_label).strip(),
                "base_url": shared_base_url,
            }
        )

    _append_config(
        "onedrive",
        api_key_env="EA_ANSWERLY_ONEDRIVE_API_KEY",
        agent_id_env="EA_ANSWERLY_ONEDRIVE_AGENT_ID",
        label_env="EA_ANSWERLY_ONEDRIVE_LABEL",
        default_label="OneDrive documents",
    )
    _append_config(
        "shareone",
        api_key_env="EA_ANSWERLY_SHAREONE_API_KEY",
        agent_id_env="EA_ANSWERLY_SHAREONE_AGENT_ID",
        label_env="EA_ANSWERLY_SHAREONE_LABEL",
        default_label="ShareOne documents",
    )
    if not configs:
        api_key = str(os.getenv("EA_ANSWERLY_API_KEY") or "").strip()
        agent_id = str(os.getenv("EA_ANSWERLY_AGENT_ID") or "").strip()
        if api_key and agent_id and shared_base_url:
            configs.append(
                {
                    "scope": "generic",
                    "api_key": api_key,
                    "agent_id": agent_id,
                    "label": str(os.getenv("EA_ANSWERLY_DOCUMENT_QA_LABEL") or "Document knowledge").strip(),
                    "base_url": shared_base_url,
                }
            )
    return configs


def _answerly_document_qa_ready() -> bool:
    return bool(_answerly_document_qa_configs())


def _telegram_answerly_document_query_candidate(text: str) -> bool:
    normalized = " ".join(str(text or "").strip().lower().split())
    if not normalized:
        return False
    explicit_markers = (
        "answerly",
        "document qa",
        "document q&a",
        "use the documents",
        "search the documents",
        "search the scans",
        "search scanned documents",
        "look in the documents",
        "look in scanned documents",
        "what does the latest",
        "what does the letter say",
        "what does the report say",
        "what does the pdf say",
        "what does the document say",
        "find the document",
        "find that document",
        "find the letter",
        "find the report",
        "find the scan",
        "find the pdf",
        "send me the birth certificate",
        "schick mir",
        "schicke mir",
        "sende mir",
        "where is my medication",
    )
    if any(marker in normalized for marker in explicit_markers):
        return True
    doc_nouns = (
        "document",
        "documents",
        "scan",
        "scans",
        "pdf",
        "letter",
        "report",
        "approval",
        "brief",
        "arztbrief",
        "befund",
        "rechnung",
        "statement",
        "passport",
        "patientsbrief",
        "certificate",
        "birth certificate",
        "medication",
        "medicine",
    )
    ask_markers = (
        "what does",
        "where is",
        "find",
        "look for",
        "search",
        "do we have",
        "can you find",
        "can you check",
        "send me",
        "schick mir",
        "schicke mir",
        "sende mir",
        "show me",
        "get me",
    )
    return any(noun in normalized for noun in doc_nouns) and any(marker in normalized for marker in ask_markers)


def _answerly_chat(
    *,
    config: dict[str, str],
    message: str,
    conversation_id: str = "",
) -> dict[str, object]:
    payload = json.dumps(
        {
            "APIKey": config["api_key"],
            "agentId": config["agent_id"],
            "conversationId": str(conversation_id or "").strip(),
            "message": str(message or "").strip(),
            "channel": "web",
            "responseStyle": "plaintext",
            "actionRequest": {"name": "conversational"},
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{config['base_url']}/chat/",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    timeout_seconds = 20.0
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        return json.loads(response.read().decode("utf-8"))


def _telegram_answerly_scope_for_text(text: str) -> str:
    normalized = " ".join(str(text or "").strip().lower().split())
    if not normalized:
        return ""
    if "onewife" in normalized:
        return "onedrive"
    if "shareone" in normalized or "share one" in normalized:
        return "shareone"
    if "onedrive" in normalized or "one drive" in normalized:
        return "onedrive"
    onedrive_markers = (
        "birth certificate",
        "certificate",
        "passport",
        "medication",
        "medicine",
    )
    shareone_markers = (
        "share packet",
        "workspace",
        "team doc",
        "share folder",
    )
    if any(marker in normalized for marker in onedrive_markers):
        return "onedrive"
    if any(marker in normalized for marker in shareone_markers):
        return "shareone"
    return ""


def _telegram_answerly_document_send_request(text: str) -> bool:
    normalized = " ".join(str(text or "").strip().lower().split())
    if not normalized:
        return False
    send_markers = ("send me", "schick mir", "schicke mir", "sende mir", "send the", "send that")
    document_markers = ("pdf", "document", "scan", "scanned", "letter", "report", "birth certificate", "certificate")
    return any(marker in normalized for marker in send_markers) and any(marker in normalized for marker in document_markers)


def _telegram_answerly_document_reply_text(
    *,
    container: AppContainer,
    principal_id: str,
    text: str,
) -> str:
    normalized = str(text or "").strip()
    if not normalized:
        return ""
    if not _telegram_answerly_document_query_candidate(normalized):
        return ""
    configs = _answerly_document_qa_configs()
    if not configs:
        if "answerly" in normalized.lower():
            return "Answerly document Q&A is not configured yet in EA."
        return ""
    requested_scope = _telegram_answerly_scope_for_text(normalized)
    if requested_scope:
        for candidate in configs:
            if str(candidate.get("scope") or "").strip() == requested_scope:
                configs = [candidate]
                break
        else:
            label = "ShareOne" if requested_scope == "shareone" else "OneDrive"
            return f"{label} document Q&A is not configured yet in EA."
    elif len(configs) > 1 and all(str(candidate.get("scope") or "").strip() in {"onedrive", "shareone"} for candidate in configs):
        labels = [str(candidate.get("label") or "").strip() for candidate in configs if str(candidate.get("label") or "").strip()]
        joined = " or ".join(labels[:2]) if labels else "OneDrive or ShareOne"
        return f"Your document backends stay separated. Please say whether to search {joined}."
    config = configs[0]
    try:
        response = _answerly_chat(config=config, message=normalized)
    except Exception as exc:
        return f"{config['label']} document Q&A is configured, but the lookup failed: {str(exc or '').strip() or 'answerly_request_failed'}."
    if not bool(response.get("status")):
        detail = str(response.get("data") or "").strip() or "answerly_request_failed"
        return f"{config['label']} document Q&A could not answer that request: {detail}."
    data = response.get("data")
    if not isinstance(data, dict):
        return "Answerly document Q&A returned an invalid response."
    messages = [
        " ".join(str(item or "").strip().split())
        for item in list(data.get("messages") or [])
        if str(item or "").strip()
    ]
    action_response = data.get("actionResponse")
    action_name = ""
    if isinstance(action_response, dict):
        action_name = str(action_response.get("name") or "").strip().lower()
    elif isinstance(action_response, str):
        action_name = str(action_response or "").strip().lower()
    if action_name in {"hallucination", "unrelated-query"} and not messages:
        return f"I checked {config['label']} in Answerly, but it did not find a grounded document answer for that yet."
    answer = " ".join(messages).strip()
    if not answer:
        if action_name in {"hallucination", "unrelated-query"}:
            return f"I checked {config['label']} in Answerly, but it did not find a grounded document answer for that yet."
        return "Answerly document Q&A did not return a usable answer."
    source_rows = data.get("meta", {}).get("source", []) if isinstance(data.get("meta"), dict) else []
    source_ids = [
        str(row.get("dataItemId") or "").strip()
        for row in list(source_rows or [])
        if isinstance(row, dict) and str(row.get("dataItemId") or "").strip()
    ]
    if source_ids and _telegram_answerly_document_send_request(normalized):
        service = build_product_service(container)
        try:
            delivered = service.deliver_onedrive_document_search_to_telegram(
                principal_id=principal_id,
                actor="telegram_local_assistant",
                query=normalized,
                answerly_source_ids=tuple(source_ids),
                limit=10,
            )
            filename = str(delivered.get("filename") or "document").strip()
            answer += f" Sent {filename} on Telegram."
        except RuntimeError as exc:
            answer += f" I matched the document, but Telegram delivery failed: {str(exc or '').strip() or 'onedrive_document_delivery_failed'}."
    if source_ids:
        answer += f" Matched {config['label']} Answerly items: {', '.join(source_ids[:3])}."
    return answer


def _telegram_ltd_runtime_profiles(container: AppContainer) -> list[object]:
    try:
        catalog = LtdRuntimeCatalogService(provider_registry=container.provider_registry)
        return list(catalog.list_profiles())
    except Exception:
        return []


def _telegram_first_url(text: str) -> str:
    match = re.search(r"https?://\S+", str(text or "").strip())
    if not match:
        return ""
    return str(match.group(0) or "").strip().rstrip(").,;")


def _telegram_try_execute_ltd_action(
    container: AppContainer,
    *,
    principal_id: str,
    service_name: str,
    action: object,
    text: str,
) -> str:
    action_key = str(getattr(action, "action_key", "") or "").strip()
    tool_name = str(getattr(action, "tool_name", "") or "").strip()
    action_kind = str(getattr(action, "action_kind", "") or "").strip()
    route_path = str(getattr(action, "route_path", "") or "").strip()
    if tool_name != "provider.onemin.media_transform":
        return ""
    image_url = _telegram_first_url(text)
    if not image_url:
        return ""
    feature_type = ""
    if action_key == "background_remove":
        feature_type = "BACKGROUND_REMOVER"
    elif action_key == "image_upscale":
        feature_type = "IMAGE_UPSCALER"
    else:
        return ""
    request = ToolInvocationRequest(
        session_id=f"telegram-ltd:{uuid.uuid4()}",
        step_id=f"telegram-ltd-step:{uuid.uuid4()}",
        tool_name=tool_name,
        action_kind=action_kind,
        payload_json={
            "action_key": action_key,
            "feature_type": feature_type,
            "image_url": image_url,
        },
        context_json={"principal_id": principal_id},
    )
    try:
        result = container.tool_execution.execute_invocation(request)
    except Exception as exc:
        return f"I would use {service_name} {action_key}, but execution failed: {str(exc or '').strip() or 'tool_execution_failed'}."
    target_ref = str(getattr(result, "target_ref", "") or "").strip()
    answer = f"Executed {service_name} {action_key}."
    if target_ref:
        answer += f" Target: {target_ref}."
    if route_path:
        answer += f" Route: {route_path}."
    return answer


def _telegram_ltd_reply_text(
    container: AppContainer,
    *,
    principal_id: str,
    text: str,
) -> str:
    normalized = str(text or "").strip()
    if not normalized:
        return ""
    lowered = " ".join(normalized.lower().split())
    profiles = _telegram_ltd_runtime_profiles(container)
    if not profiles:
        return ""
    runtime_catalog = LtdRuntimeCatalogService(provider_registry=container.provider_registry)
    wants_catalog = any(
        phrase in lowered
        for phrase in (
            "what ltd",
            "which ltd",
            "which tool",
            "which service",
            "what service should",
            "what can ea use",
            "what can you use",
            "available ltd",
            "runtime catalog",
        )
    )
    matched_profile = None
    for profile in profiles:
        service_name = str(getattr(profile, "service_name", "") or "").strip()
        aliases = [str(item or "").strip() for item in list(getattr(profile, "aliases", ()) or ()) if str(item or "").strip()]
        tokens = [service_name.lower(), *(alias.lower() for alias in aliases)]
        if any(token and token in lowered for token in tokens):
            matched_profile = profile
            break
    if matched_profile is not None:
        service_name = str(getattr(matched_profile, "service_name", "") or "").strip()
        runtime_state = str(getattr(matched_profile, "runtime_state", "") or "").strip()
        tier = str(getattr(matched_profile, "workspace_integration_tier", "") or "").strip()
        actions = list(getattr(matched_profile, "actions", ()) or ())
        explicit_use_request = any(
            phrase in lowered
            for phrase in (
                "use ",
                "run ",
                "open ",
                "inspect ",
                "read ",
                "create ",
                "send ",
                "generate ",
                "remove the background",
                "upscale ",
            )
        )
        if explicit_use_request:
            inferred_task_key = projected_task_key_for_request(
                goal=normalized,
                input_json={"service_name": service_name},
                catalog=runtime_catalog,
            )
            if inferred_task_key:
                for action in actions:
                    action_task_key = projected_task_key(service_name, str(getattr(action, "action_key", "") or "").strip())
                    if inferred_task_key != action_task_key:
                        continue
                    action_key = str(getattr(action, "action_key", "") or "").strip()
                    if action_key == "discover_account" and any(
                        str(getattr(candidate, "action_key", "") or "").strip() not in {"", "discover_account"}
                        for candidate in actions
                    ):
                        break
                    executed_reply = _telegram_try_execute_ltd_action(
                        container,
                        principal_id=principal_id,
                        service_name=service_name,
                        action=action,
                        text=normalized,
                    )
                    if executed_reply:
                        return executed_reply
                    route_path = str(getattr(action, "route_path", "") or "").strip()
                    executable = bool(getattr(action, "executable", False))
                    description = str(getattr(action, "description", "") or "").strip()
                    answer = f"For {service_name}, I would use {action_key}."
                    if description:
                        answer += f" {description}"
                    if route_path:
                        answer += f" Route: {route_path}."
                    answer += " Executable now." if executable else " Not executable yet."
                    return answer
        action_labels = [
            str(getattr(action, "action_key", "") or "").strip()
            for action in actions
            if str(getattr(action, "action_key", "") or "").strip()
        ]
        action_text = ", ".join(action_labels[:4]) if action_labels else "no runtime actions"
        return f"{service_name} is available in EA as {runtime_state} ({tier}). Actions: {action_text}."
    if not wants_catalog:
        return ""
    actionable = []
    for profile in profiles:
        actions = [action for action in list(getattr(profile, "actions", ()) or ()) if str(getattr(action, "action_key", "") or "").strip()]
        if not actions:
            continue
        actionable.append(
            (
                str(getattr(profile, "workspace_integration_tier", "") or "").strip().lower(),
                str(getattr(profile, "service_name", "") or "").strip(),
                profile,
            )
        )
    actionable.sort(key=lambda item: item[1].lower())
    if not actionable:
        return ""
    top = [row[2] for row in actionable[:5]]
    summary = []
    for profile in top:
        service_name = str(getattr(profile, "service_name", "") or "").strip()
        runtime_state = str(getattr(profile, "runtime_state", "") or "").strip()
        actions = list(getattr(profile, "actions", ()) or ())
        first_action = str(getattr(actions[0], "action_key", "") or "").strip() if actions else ""
        if service_name:
            chunk = service_name
            if runtime_state:
                chunk += f" ({runtime_state})"
            if first_action:
                chunk += f" -> {first_action}"
            summary.append(chunk)
    if not summary:
        return ""
    return "EA can use these LTD/runtime lanes right now: " + " | ".join(summary[:5]) + "."


def _telegram_google_photos_context_reply(
    container: AppContainer,
    *,
    principal_id: str,
    normalized: str,
    lower: str,
    alpha_words: list[str],
) -> str:
    if any(
        phrase in lower
        for phrase in (
            "start google photos picker",
            "start the google photos picker",
            "open google photos picker",
            "open the google photos picker",
            "start photo picker",
            "start the photo picker",
            "open photo picker",
            "open the photo picker",
            "start picker",
            "open picker",
        )
    ):
        return _telegram_google_photos_picker_action_reply_text(
            container,
            principal_id=principal_id,
        )
    if alpha_words and all(word in {"done", "finished", "complete", "completed", "ok", "okay"} for word in alpha_words):
        if _telegram_recent_messages_include_google_photos_context(
            container,
            principal_id=principal_id,
        ):
            return _telegram_google_photos_picker_action_reply_text(
                container,
                principal_id=principal_id,
            )
    if alpha_words and all(word in {"voice", "message"} for word in alpha_words):
        if _telegram_recent_messages_include_google_photos_context(
            container,
            principal_id=principal_id,
        ):
            return _telegram_google_photos_picker_action_reply_text(
                container,
                principal_id=principal_id,
            )
    return _telegram_google_photos_reply_text(
        container,
        principal_id=principal_id,
        text=normalized,
    )


def _telegram_property_alert_policy_reply(
    container: AppContainer,
    *,
    principal_id: str,
    lower: str,
) -> str:
    if not (
        ("do all of that by itself" in lower or "do that by itself" in lower or "handle property alerts by itself" in lower)
        or ("if it's good" in lower and "notification here" in lower)
    ):
        return ""
    return _telegram_property_boundary_reply_text()


def _telegram_property_boundary_reply_text() -> str:
    return "Wohnungssuche und Property-Alerts laufen nicht über EA."


def _telegram_is_low_signal_summary(value: object) -> bool:
    summary = str(value or "").strip().lower()
    if not summary:
        return True
    low_signal_markers = (
        "signal from ",
        "signal sync completed",
        "workspace signal sync completed",
        "google workspace signal sync completed",
        "sync completed",
        "google sync completed",
        "office signal ingested",
    )
    return any(marker in summary for marker in low_signal_markers)


def _telegram_is_actionable_focus_summary(value: object) -> bool:
    summary = str(value or "").strip().lower()
    if not summary or _telegram_is_low_signal_summary(summary):
        return False
    if text_mentions_flat_property_search(summary):
        return False
    actionable_markers = (
        "approve",
        "review",
        "reply",
        "follow up",
        "follow-up",
        "send",
        "book",
        "call",
        "prepare",
        "shortlist",
        "property",
        "apartment",
        "tour",
    )
    return any(marker in summary for marker in actionable_markers)


def _telegram_compact_focus_text(value: object, *, limit: int = 120) -> str:
    text_value = " ".join(str(value or "").strip().split())
    if not text_value:
        return ""
    if text_mentions_flat_property_search(text_value):
        return ""
    if text_value.lower().startswith("review apartment alert:"):
        suffix = text_value.split(":", 1)[1].strip()
        suffix = suffix.strip("\"")
        text_value = f"Apartment alert: {suffix}" if suffix else "Apartment alert"
    if text_value.lower().startswith("apartment alert:"):
        prefix, _, suffix = text_value.partition(":")
        cleaned_suffix = suffix.strip().replace('"', "").replace("“", "").replace("”", "")
        listing_match = re.match(r"^(?P<label>.+?) hat (?P<count>\d+) neue Anzeige(?:n)? für dich gefunden\.?$", cleaned_suffix, re.IGNORECASE)
        if listing_match:
            label = " ".join(str(listing_match.group("label") or "").split()).strip(" ,;:")
            count = int(str(listing_match.group("count") or "0") or "0")
            noun = "listing" if count == 1 else "listings"
            cleaned_suffix = f"{label} ({count} new {noun})"
        text_value = f"{prefix}: {cleaned_suffix}".strip()
    if text_value.lower().startswith("reply to ") and " | " in text_value:
        _, _, remainder = text_value.partition(" | ")
        if remainder.strip():
            text_value = remainder.strip()
    if text_value.lower().startswith("re:"):
        text_value = text_value[3:].strip()
    lowered = text_value.lower()
    noisy_markers = (
        "stage 1 commitment candidate.",
        "prepare a reply draft for approval before send.",
        "no additional ltd lane is recommended",
        "office signal ingested.",
        "recent mail from",
        " hi ",
    )
    for marker in noisy_markers:
        idx = lowered.find(marker)
        if idx >= 0:
            text_value = text_value[:idx].strip()
            lowered = text_value.lower()
    greeting_idx = lowered.find(". hi ")
    if greeting_idx >= 0:
        text_value = text_value[: greeting_idx + 1].strip()
    if ". " in text_value:
        first_sentence = text_value.split(". ", 1)[0].strip()
        if 0 < len(first_sentence) <= limit:
            text_value = first_sentence.rstrip(".") + "."
    while ".." in text_value:
        text_value = text_value.replace("..", ".")
    if len(text_value) <= limit:
        return text_value
    clipped = text_value[: limit - 1].rstrip()
    if " " in clipped:
        clipped = clipped.rsplit(" ", 1)[0]
    return clipped.rstrip(" ,;:.") + "..."


def _telegram_tomorrow_focus_reply(
    container: AppContainer,
    *,
    principal_id: str,
    lower: str,
) -> str:
    if not any(
        phrase in lower
        for phrase in (
            "focus on tomorrow",
            "what should i focus on tomorrow",
            "what should i focus on",
            "what should i do tomorrow",
            "what is tomorrow like",
        )
    ):
        return ""
    now_vienna = datetime.now(ZoneInfo("Europe/Vienna"))
    tomorrow_date = now_vienna.date() + timedelta(days=1)
    upcoming = _telegram_upcoming_calendar_events(container, principal_id=principal_id, limit=6)
    tomorrow_events = [
        event
        for event in upcoming
        if event["start_at"].astimezone(ZoneInfo("Europe/Vienna")).date() == tomorrow_date
    ]
    parts: list[str] = []
    if tomorrow_events:
        first = tomorrow_events[0]
        start_text = first["start_at"].astimezone(ZoneInfo("Europe/Vienna")).strftime("%H:%M")
        parts.append(f"Tomorrow, focus first on {first['title']} at {start_text}.")
        if str(first.get("location") or "").strip():
            parts.append(f"Location: {str(first.get('location') or '').strip()}.")
    product_service = build_product_service(container)
    events = list(product_service.list_office_events(principal_id=principal_id, limit=20))
    recent_summaries = [
        str(row.get("summary") or "").strip()
        for row in events
        if str(row.get("channel") or "").strip() in {"gmail", "product", "pocket"}
        and str(row.get("summary") or "").strip()
        and _telegram_is_actionable_focus_summary(row.get("summary"))
    ][:2]
    try:
        queue_items = list(product_service.list_queue(principal_id=principal_id, limit=3))
    except Exception:
        queue_items = []
    if recent_summaries:
        compact_summaries = [_telegram_compact_focus_text(item, limit=90) for item in recent_summaries]
        compact_summaries = [item for item in compact_summaries if item]
        if compact_summaries:
            joined = " | ".join(compact_summaries[:2]).rstrip(". ")
            parts.append("Recent follow-up context: " + joined + ".")
    if queue_items:
        first = queue_items[0]
        first_title = _telegram_compact_focus_text(getattr(first, "title", ""), limit=90)
        first_summary = _telegram_compact_focus_text(getattr(first, "summary", ""), limit=80)
        if first_title:
            sentence = f"Top priority looks like {first_title}."
            if first_summary and first_summary.lower() not in {"operator · pending", "unassigned · normal · pending"}:
                sentence += f" {first_summary}"
            parts.append(sentence)
        if len(queue_items) > 1:
            next_titles = [
                _telegram_compact_focus_text(getattr(item, "title", ""), limit=80)
                for item in queue_items[1:]
                if _telegram_compact_focus_text(getattr(item, "title", ""), limit=80)
            ]
            if next_titles:
                parts.append("After that: " + " | ".join(next_titles[:2]) + ".")
    profile_lines = _telegram_profile_admin_lines(container, principal_id=principal_id, limit=2)
    if profile_lines:
        parts.append("Profile-based focus: " + " | ".join(line.rstrip(". ") for line in profile_lines if line.strip()) + ".")
    if parts:
        return " ".join(parts)
    if profile_lines:
        return "I do not see a concrete appointment for tomorrow yet. " + " ".join(line.rstrip(". ") + "." for line in profile_lines[:2] if line.strip())
    return "I do not see a concrete appointment for tomorrow yet. Focus on clearing the most important inbox and queue follow-ups first."


def _telegram_summary_reply(
    container: AppContainer,
    *,
    principal_id: str,
    lower: str,
) -> str:
    if not any(phrase in lower for phrase in ("summarize", "summary", "recap", "catch me up")):
        return ""
    upcoming = _telegram_upcoming_calendar_events(container, principal_id=principal_id, limit=2)
    product_service = build_product_service(container)
    events = list(product_service.list_office_events(principal_id=principal_id, limit=12))
    recent_signals = [
        row
        for row in events
        if str(row.get("channel") or "").strip() in {"gmail", "calendar", "pocket", "product"}
        and not _telegram_is_low_signal_summary(row.get("summary"))
    ][:4]
    parts: list[str] = []
    if upcoming:
        first = upcoming[0]
        starts = first["start_at"].astimezone(ZoneInfo("Europe/Vienna")).strftime("%A at %H:%M")
        parts.append(f"Next up: {first['title']} on {starts}.")
    if recent_signals:
        summaries = [str(row.get("summary") or "").strip() for row in recent_signals if str(row.get("summary") or "").strip()]
        if summaries:
            parts.append("Recent activity: " + " | ".join(summaries[:3]))
    if parts:
        return " ".join(parts)
    return "I do not have enough recent EA state to summarize anything useful right now."


def _telegram_email_summary_reply(
    container: AppContainer,
    *,
    principal_id: str,
    lower: str,
) -> str:
    if not any(phrase in lower for phrase in ("email", "emails", "inbox", "mail")):
        return ""
    product_service = build_product_service(container)
    events = list(product_service.list_office_events(principal_id=principal_id, limit=20))
    gmail_events = [row for row in events if str(row.get("channel") or "").strip() == "gmail"][:3]
    if gmail_events:
        summaries = [str(row.get("summary") or "").strip() for row in gmail_events if str(row.get("summary") or "").strip()]
        if summaries:
            return "Recent email signals: " + " | ".join(summaries)
    return "I do not see a recent Gmail signal I can summarize right now."


def _telegram_local_assistant_reply_text(
    container: AppContainer,
    *,
    principal_id: str,
    text: str,
) -> str:
    normalized = str(text or "").strip()
    if not normalized:
        return ""
    lower = normalized.lower()
    alpha = "".join(ch for ch in lower if ch.isalpha() or ch.isspace()).strip()
    alpha_words = [part for part in alpha.split() if part]
    return run_local_resolvers(
        _telegram_local_resolvers(
            container=container,
            principal_id=principal_id,
            normalized=normalized,
            lower=lower,
            alpha_words=alpha_words,
        )
    )


def _telegram_local_resolvers(
    *,
    container: AppContainer,
    principal_id: str,
    normalized: str,
    lower: str,
    alpha_words: list[str],
) -> list[TelegramLocalResolver]:
    return [
        TelegramLocalResolver(name="meta", resolve=lambda: _telegram_meta_assistant_reply_text(normalized)),
        TelegramLocalResolver(
            name="google_photos",
            resolve=lambda: _telegram_google_photos_context_reply(
                container,
                principal_id=principal_id,
                normalized=normalized,
                lower=lower,
                alpha_words=alpha_words,
            ),
        ),
        TelegramLocalResolver(
            name="answerly_documents",
            resolve=lambda: _telegram_answerly_document_reply_text(
                container=container,
                principal_id=principal_id,
                text=normalized,
            ),
        ),
        TelegramLocalResolver(
            name="ltd_runtime",
            resolve=lambda: _telegram_ltd_reply_text(
                container,
                principal_id=principal_id,
                text=normalized,
            ),
        ),
        TelegramLocalResolver(
            name="admin_followup",
            resolve=lambda: _telegram_profile_followup_reply_text(
                container,
                principal_id=principal_id,
                text=normalized,
            ),
        ),
        TelegramLocalResolver(
            name="property_alert_policy",
            resolve=lambda: _telegram_property_alert_policy_reply(
                container,
                principal_id=principal_id,
                lower=lower,
            ),
        ),
        TelegramLocalResolver(
            name="tomorrow_focus",
            resolve=lambda: _telegram_tomorrow_focus_reply(
                container,
                principal_id=principal_id,
                lower=lower,
            ),
        ),
        TelegramLocalResolver(
            name="summary",
            resolve=lambda: _telegram_summary_reply(
                container,
                principal_id=principal_id,
                lower=lower,
            ),
        ),
        TelegramLocalResolver(
            name="email_summary",
            resolve=lambda: _telegram_email_summary_reply(
                container,
                principal_id=principal_id,
                lower=lower,
            ),
        ),
    ]


def _parse_isoish_datetime(value: object) -> datetime | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    try:
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"
        parsed = datetime.fromisoformat(normalized)
    except Exception:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=ZoneInfo("UTC"))
    return parsed


def _telegram_upcoming_calendar_events(
    container: AppContainer,
    *,
    principal_id: str,
    limit: int = 4,
) -> list[dict[str, object]]:
    product_service = build_product_service(container)
    rows = list(
        product_service.list_office_events(
            principal_id=principal_id,
            limit=max(limit * 8, 20),
            event_type="office_signal_calendar_note",
        )
    )
    if not rows:
        fallback_rows: list[dict[str, object]] = []
        for observation in container.channel_runtime.list_recent_observations(limit=max(limit * 8, 20), principal_id=principal_id):
            if str(observation.channel or "").strip() != "calendar":
                continue
            if str(observation.event_type or "").strip() != "office_signal_calendar_note":
                continue
            fallback_rows.append(
                {
                    "summary": str(getattr(observation, "event_type", "") or "").strip(),
                    "created_at": str(getattr(observation, "created_at", "") or "").strip(),
                    "payload": dict(getattr(observation, "payload", {}) or {}),
                }
            )
        rows = fallback_rows
    upcoming: list[dict[str, object]] = []
    now = datetime.now(ZoneInfo("UTC"))
    for row in rows:
        payload = dict(row.get("payload") or {})
        start_at = (
            str(payload.get("start_at") or "").strip()
            or str(payload.get("due_at") or "").strip()
            or str(row.get("created_at") or "").strip()
        )
        parsed_start = _parse_isoish_datetime(start_at)
        if parsed_start is None:
            continue
        if parsed_start.astimezone(ZoneInfo("UTC")) < now:
            continue
        title = str(payload.get("title") or row.get("summary") or "").strip() or "Upcoming meeting"
        attendees = [str(item or "").strip() for item in list(payload.get("attendees") or []) if str(item or "").strip()]
        location = str(payload.get("location") or "").strip()
        upcoming.append(
            {
                "title": title,
                "start_at": parsed_start,
                "location": location,
                "attendees": attendees[:4],
                "summary": str(row.get("summary") or "").strip(),
            }
        )
    upcoming.sort(key=lambda item: item["start_at"])
    return upcoming[:limit]


def _telegram_direct_calendar_reply_text(*, container: AppContainer, principal_id: str, text: str) -> str:
    normalized = str(text or "").strip()
    lower = normalized.lower()
    if not normalized:
        return ""
    schedule_markers = (
        "next appointment",
        "next meeting",
        "next calendar",
        "my calendar",
        "my schedule",
        "next event",
        "what's next",
        "whats next",
        "what is next",
        "appointment",
    )
    if not any(marker in lower for marker in schedule_markers):
        return ""
    events = _telegram_upcoming_calendar_events(container, principal_id=principal_id, limit=3)
    if not events:
        return "I do not see an upcoming calendar appointment in EA right now."
    first = events[0]
    starts = first["start_at"].astimezone(ZoneInfo("Europe/Vienna")).strftime("%A at %H:%M")
    prefix = "Yes. " if any(marker in lower for marker in ("can u", "can you")) else ""
    detail_parts = [f"{prefix}Your next appointment is {first['title']} on {starts}."]
    location = str(first.get("location") or "").strip()
    if location:
        detail_parts.append(f"Location: {location}.")
    attendees = [str(item or "").strip() for item in list(first.get("attendees") or []) if str(item or "").strip()]
    if attendees:
        detail_parts.append(f"With {', '.join(attendees[:3])}.")
    return " ".join(detail_parts)


def _telegram_admin_focus_lines_from_profile_refs(refs: list[str], *, limit: int = 4) -> list[str]:
    ref_map = {
        "profile_followup:insurance_admin:rehab_authorization_management": "Insurance admin is a real theme: watch rehab approvals, KfA authorizations, and follow-ups.",
        "profile_followup:insurance_admin:insurance_and_lab_followthrough": "Insurance and lab follow-through matter: keep questionnaires, lab results, and benefit paperwork current.",
        "profile_followup:medical_admin:proactive_case_management": "Medical admin remains active: keep rehab, neurology, and care paperwork moving.",
        "profile_followup:medical_admin:official_followup_management": "Official medical follow-ups matter: stay ahead of Amtsarzt controls and medical forms.",
        "profile_followup:school_admin:school_and_kindergarten_coordination": "School and kindergarten coordination is active: keep Noah enrollment, attendance, and planning paperwork in order.",
        "profile_followup:care_admin:care_leave_management": "Care-leave admin is active: track Pflegefreistellung and child-related schedule disruptions.",
        "profile_followup:utilities_admin:utility_and_provider_account_management": "Utility admin is active: keep Wiener Netze, Wiener Wohnen, and provider-account tasks under control.",
        "profile_followup:housing_admin:rental_and_utilities_admin": "Housing admin matters: watch rent, utilities, mandates, and landlord or provider paperwork.",
        "profile_followup:financial_admin:banking_card_admin": "Banking and card admin matters: keep Easybank, bank99, and Visa tasks tidy.",
        "profile_followup:travel_admin:family_passport_document_management": "Travel-document admin is active: keep passports and family identity documents current.",
    }
    lines: list[str] = []
    seen: set[str] = set()
    for ref in refs:
        line = ref_map.get(str(ref or "").strip())
        if not line or line in seen:
            continue
        seen.add(line)
        lines.append(line)
        if len(lines) >= limit:
            break
    return lines


def _telegram_profile_admin_lines(
    container: AppContainer,
    *,
    principal_id: str,
    limit: int = 4,
) -> list[str]:
    product_service = build_product_service(container)
    try:
        bundle = product_service.get_preference_profile(principal_id=principal_id, person_id="self")
    except Exception:
        return []
    nodes = list(bundle.get("preference_nodes") or [])
    prioritized: list[tuple[str, float]] = []
    for row in nodes:
        if str(row.get("status") or "").strip().lower() != "active":
            continue
        domain = str(row.get("domain") or "").strip().lower()
        category = str(row.get("category") or "").strip().lower()
        key = str(row.get("key") or "").strip().lower()
        confidence = float(row.get("confidence") or 0.0)
        if domain == "willhaben":
            continue
        line = ""
        if category == "medical_admin" and key == "proactive_case_management":
            line = "Medical admin remains active: keep rehab, neurology, and care paperwork moving."
        elif category == "medical_admin" and key == "official_followup_management":
            line = "Official medical follow-ups matter: stay ahead of Amtsarzt controls and medical forms."
        elif category == "insurance_admin" and key == "rehab_authorization_management":
            line = "Insurance admin is a real theme: watch rehab approvals, KfA authorizations, and follow-ups."
        elif category == "insurance_admin" and key == "insurance_and_lab_followthrough":
            line = "Insurance and lab follow-through matter: keep questionnaires, lab results, and benefit paperwork current."
        elif category == "school_admin" and key == "school_and_kindergarten_coordination":
            line = "School and kindergarten coordination is active: keep Noah enrollment, attendance, and planning paperwork in order."
        elif category == "care_admin" and key == "care_leave_management":
            line = "Care-leave admin is active: track Pflegefreistellung and child-related schedule disruptions."
        elif category == "utilities_admin" and key == "utility_and_provider_account_management":
            line = "Utility admin is active: keep Wiener Netze, Wiener Wohnen, and provider-account tasks under control."
        elif category == "housing_admin" and key == "rental_and_utilities_admin":
            line = "Housing admin matters: watch rent, utilities, mandates, and landlord or provider paperwork."
        elif category == "financial_admin" and key == "banking_card_admin":
            line = "Banking and card admin matters: keep Easybank, bank99, and Visa tasks tidy."
        elif category == "workflow" and key == "prefers_proactive_deadline_tracking":
            line = "You tend to need proactive deadline tracking: clear dated admin tasks early."
        elif category == "household" and key in {"shared_family_admin_involvement", "child_related_admin"}:
            line = "Family admin is active: child, travel, and shared household paperwork deserves attention."
        elif category == "travel_admin" and key == "family_passport_document_management":
            line = "Travel-document admin is active: keep passports and family identity documents current."
        if line:
            prioritized.append((line, confidence))
    seen: set[str] = set()
    result: list[str] = []
    for line, _confidence in sorted(prioritized, key=lambda item: item[1], reverse=True):
        if line in seen:
            continue
        seen.add(line)
        result.append(line)
        if len(result) >= limit:
            break
    return result


def _telegram_admin_followup_candidates(
    brief_items: list[object],
    queue_items: list[object],
    *,
    theme_refs: list[str] | None = None,
) -> list[object]:
    theme_refs = [str(item or "").strip() for item in list(theme_refs or []) if str(item or "").strip()]
    direct_admin_markers = (
        "rehab",
        "kfa",
        "bewilligung",
        "amtsarzt",
        "wiederbestellung",
        "school",
        "schule",
        "kindergarten",
        "pflegefreistellung",
        "insurance",
        "utility",
        "paperwork",
        "follow-up",
        "follow up",
        "admin",
    )

    def _matches_theme(item: object) -> bool:
        refs = [
            str(ref or "").strip()
            for ref in list(getattr(item, "profile_followup_refs", ()) or ())
            if str(ref or "").strip()
        ]
        object_ref = str(getattr(item, "object_ref", "") or "").strip()
        if object_ref:
            refs.append(object_ref)
        if theme_refs and any(ref in theme_refs for ref in refs):
            return True
        haystack = " ".join(
            part
            for part in (
                str(getattr(item, "title", "") or "").strip().lower(),
                str(getattr(item, "summary", "") or "").strip().lower(),
                str(getattr(item, "why_now", "") or "").strip().lower(),
                str(getattr(item, "recommended_action", "") or "").strip().lower(),
                object_ref.lower(),
            )
            if part
        )
        return any(marker in haystack for marker in direct_admin_markers)

    candidates: list[object] = []
    seen_keys: set[str] = set()
    ordered_queue = list(queue_items)
    ordered_queue.sort(
        key=lambda row: (
            str(getattr(row, "priority", "") or "").strip().lower() != "high",
            -float(getattr(row, "rank_score", 0.0) or 0.0),
            str(getattr(row, "title", "") or "").strip().lower(),
        )
    )
    ordered_briefs = list(brief_items)
    ordered_briefs.sort(key=lambda row: -float(getattr(row, "score", 0.0) or 0.0))
    for item in ordered_queue + ordered_briefs:
        if not _matches_theme(item):
            continue
        key = str(getattr(item, "id", "") or getattr(item, "object_ref", "") or getattr(item, "title", "") or "").strip()
        if not key or key in seen_keys:
            continue
        seen_keys.add(key)
        candidates.append(item)
    return candidates


def _telegram_profile_followup_reply_text(
    container: AppContainer,
    *,
    principal_id: str,
    text: str,
) -> str:
    normalized = str(text or "").strip()
    if not normalized:
        return ""
    lowered = " ".join(normalized.lower().split())
    persisted_intent_state = _telegram_recent_persisted_intent_state(container, principal_id=principal_id)
    persisted_object_map = _telegram_recent_persisted_object_map(container, principal_id=principal_id)
    theme_refs: list[str] = []
    raw_themes = str(persisted_intent_state.get("active_profile_themes") or "").strip()
    for item in raw_themes.split(","):
        normalized_ref = str(item or "").strip()
        if normalized_ref and normalized_ref not in theme_refs:
            theme_refs.append(normalized_ref)
    for key in ("active_queue_profile_refs",):
        raw = str(persisted_object_map.get(key) or "").strip()
        if not raw:
            continue
        for item in raw.split(","):
            normalized_ref = str(item or "").strip()
            if normalized_ref and normalized_ref not in theme_refs:
                theme_refs.append(normalized_ref)
    intent = str(persisted_intent_state.get("active_intent") or "").strip().lower()
    direct_admin_markers = (
        "rehab",
        "kfa",
        "bewilligung",
        "amtsarzt",
        "wiederbestellung",
        "school",
        "schule",
        "kindergarten",
        "pflegefreistellung",
        "insurance",
        "utility",
        "paperwork",
        "follow-up",
        "follow up",
        "admin",
    )
    wants_secondary = any(
        marker in lowered
        for marker in (
            "after that",
            "and after that",
            "afterwards",
            "what next",
            "what after that",
            "next one",
            "the other one",
            "the other",
        )
    )
    wants_reason = any(
        marker in lowered
        for marker in (
            "why that one",
            "why this one",
            "why that",
            "why this",
            "why first",
            "why that one?",
            "why the other one",
            "why the other",
        )
    )
    is_followup_prompt = (
        intent == "admin_followup"
        and theme_refs
        and (
            _telegram_low_signal_followup_cue(normalized)
            or wants_secondary
            or wants_reason
            or any(marker in lowered for marker in ("paperwork", "follow-up", "follow up", "admin", "rehab", "kfa"))
        )
    )
    if not is_followup_prompt and not any(marker in lowered for marker in direct_admin_markers):
        return ""
    product_service = build_product_service(container)
    try:
        brief_items = list(product_service.list_brief_items(principal_id=principal_id, limit=8))
    except Exception:
        brief_items = []
    try:
        queue_items = list(product_service.list_queue(principal_id=principal_id, limit=8))
    except Exception:
        queue_items = []

    matching_candidates = _telegram_admin_followup_candidates(
        brief_items,
        queue_items,
        theme_refs=theme_refs,
    )
    if matching_candidates:
        persisted_primary = str(persisted_intent_state.get("active_admin_primary") or "").strip()
        persisted_secondary = str(persisted_intent_state.get("active_admin_secondary") or "").strip()
        index = 1 if wants_secondary and len(matching_candidates) > 1 else 0
        if wants_reason and persisted_primary:
            for candidate_index, candidate in enumerate(matching_candidates[:2]):
                candidate_ref = str(getattr(candidate, "object_ref", "") or getattr(candidate, "id", "") or "").strip()
                if candidate_ref == persisted_primary:
                    index = candidate_index
                    break
        if wants_reason and wants_secondary and persisted_secondary:
            for candidate_index, candidate in enumerate(matching_candidates[:2]):
                candidate_ref = str(getattr(candidate, "object_ref", "") or getattr(candidate, "id", "") or "").strip()
                if candidate_ref == persisted_secondary:
                    index = candidate_index
                    break
        top = matching_candidates[index]
        title = str(getattr(top, "title", "") or "").strip()
        summary = " ".join(
            (
                str(getattr(top, "summary", "") or "").strip()
                or str(getattr(top, "why_now", "") or "").strip()
            ).split()
        )
        recommended_action = " ".join(str(getattr(top, "recommended_action", "") or "").strip().split())
        if wants_reason:
            prefix = "That one leads because" if index == 0 else "The other one matters because"
            answer = f"{prefix} {summary or title}."
            if recommended_action:
                answer += f" Next: {recommended_action}."
            return answer.strip()
        prefix = "After that, focus on" if index == 1 else "Top admin follow-up is"
        answer = f"{prefix} {title}."
        if summary:
            answer += f" {summary}"
        if recommended_action:
            answer += f" Next: {recommended_action}."
        return answer.strip()
    admin_lines = _telegram_profile_admin_lines(container, principal_id=principal_id, limit=2)
    if admin_lines:
        return admin_lines[0]
    return ""


def _telegram_recent_conversation_messages(
    container: AppContainer,
    *,
    principal_id: str,
    current_message_id: str = "",
    limit: int = 8,
) -> list[dict[str, object]]:
    rows = list(container.channel_runtime.list_recent_observations(limit=60, principal_id=principal_id))
    rows.sort(key=lambda row: (str(row.created_at or ""), str(row.observation_id or "")))
    messages: list[dict[str, object]] = []
    seen_reply_texts: set[str] = set()
    current_external_id = str(current_message_id or "").strip()
    for row in rows:
        if str(row.channel or "").strip() != "telegram":
            continue
        payload = dict(row.payload or {})
        event_type = str(row.event_type or "").strip().lower()
        if event_type == "telegram.message":
            if current_external_id and str(row.external_id or "").strip() == current_external_id:
                continue
            text = str(payload.get("text") or "").strip()
            if text:
                messages.append({"role": "user", "content": [{"type": "input_text", "text": text}]})
        elif event_type in {"telegram.reply_sent", "telegram.reply_async_sent"}:
            reply_text = str(payload.get("reply_text") or "").strip()
            if reply_text and reply_text not in seen_reply_texts:
                seen_reply_texts.add(reply_text)
                messages.append({"role": "assistant", "content": [{"type": "output_text", "text": reply_text}]})
    return messages[-limit:]


def _telegram_recent_conversation_focus_lines(
    container: AppContainer,
    *,
    principal_id: str,
    limit: int = 4,
) -> list[str]:
    messages = _telegram_recent_conversation_messages(
        container,
        principal_id=principal_id,
        current_message_id="",
        limit=max(limit * 2, 8),
    )
    rows: list[str] = []
    seen: set[str] = set()
    for item in reversed(messages):
        role = str(item.get("role") or "").strip() or "user"
        content_parts = list(item.get("content") or [])
        text_part = ""
        for part in content_parts:
            if not isinstance(part, dict):
                continue
            text_part = str(part.get("text") or "").strip()
            if text_part:
                break
        if not text_part:
            continue
        normalized = " ".join(text_part.split())
        if normalized in seen:
            continue
        seen.add(normalized)
        rows.append(f"- {role}: {normalized}")
        if len(rows) >= limit:
            break
    rows.reverse()
    return rows


def _telegram_recent_subject_hint_lines(
    container: AppContainer,
    *,
    principal_id: str,
    limit: int = 3,
) -> list[str]:
    messages = _telegram_recent_conversation_messages(
        container,
        principal_id=principal_id,
        current_message_id="",
        limit=12,
    )
    followup_markers = {
        "well?",
        "and?",
        "again?",
        "why?",
        "that one?",
        "the other?",
        "well",
        "and",
        "again",
        "why",
    }
    prefix_patterns = [
        r"^top priority is\s+",
        r"^after that:\s*",
        r"^title:\s*",
        r"^summary:\s*",
        r"^recommendation:\s*",
        r"^next:\s*",
        r"^source:\s*",
    ]
    rows: list[str] = []
    seen: set[str] = set()
    for item in reversed(messages):
        role = str(item.get("role") or "").strip().lower() or "user"
        content_parts = list(item.get("content") or [])
        text_part = ""
        for part in content_parts:
            if not isinstance(part, dict):
                continue
            text_part = str(part.get("text") or "").strip()
            if text_part:
                break
        if not text_part:
            continue
        normalized = " ".join(text_part.split())
        if normalized.lower() in followup_markers:
            continue
        subject = normalized
        if role == "assistant":
            for pattern in prefix_patterns:
                subject = re.sub(pattern, "", subject, flags=re.IGNORECASE).strip()
        subject = subject.strip(" .")
        if len(subject) < 12:
            continue
        if len(subject) > 120:
            subject = subject[:117].rstrip() + "..."
        lowered = subject.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        rows.append(f"- {subject}")
        if len(rows) >= limit:
            break
    rows.reverse()
    return rows


def _telegram_compact_reference_tokens(*values: object) -> list[str]:
    tokens: list[str] = []
    seen: set[str] = set()
    for value in values:
        token = str(value or "").strip()
        if not token or token in seen:
            continue
        seen.add(token)
        tokens.append(token)
    return tokens


def _telegram_brief_reference_suffix(item: object) -> str:
    tokens = _telegram_compact_reference_tokens(
        getattr(item, "id", ""),
        getattr(item, "object_ref", ""),
    )
    evidence_refs = list(getattr(item, "evidence_refs", ()) or ())
    for ref in evidence_refs[:2]:
        tokens.extend(
            _telegram_compact_reference_tokens(
                getattr(ref, "ref_id", ""),
                getattr(ref, "href", ""),
            )
        )
    suffix = ""
    if tokens:
        suffix += " | refs: " + ", ".join(tokens[:4])
    profile_refs = [str(ref or "").strip() for ref in list(getattr(item, "profile_followup_refs", ()) or ()) if str(ref or "").strip()]
    if profile_refs:
        suffix += " | profile refs: " + ", ".join(profile_refs[:3])
    return suffix


def _telegram_queue_reference_suffix(item: object) -> str:
    tokens = _telegram_compact_reference_tokens(
        getattr(item, "id", ""),
    )
    evidence_refs = list(getattr(item, "evidence_refs", ()) or ())
    for ref in evidence_refs[:3]:
        tokens.extend(
            _telegram_compact_reference_tokens(
                getattr(ref, "ref_id", ""),
                getattr(ref, "href", ""),
            )
        )
    suffix = ""
    if tokens:
        suffix += " | refs: " + ", ".join(tokens[:5])
    profile_refs = [str(ref or "").strip() for ref in list(getattr(item, "profile_followup_refs", ()) or ()) if str(ref or "").strip()]
    if profile_refs:
        suffix += " | profile refs: " + ", ".join(profile_refs[:3])
    return suffix


def _telegram_profile_followup_refs_text(item: object) -> str:
    refs = [str(ref or "").strip() for ref in list(getattr(item, "profile_followup_refs", ()) or ()) if str(ref or "").strip()]
    if not refs:
        return ""
    return ", ".join(refs[:3])


_TELEGRAM_PROPERTY_OBJECT_KEYS = (
    "active_property_candidate",
    "active_property_refs",
    "active_property_profile_refs",
)
_TELEGRAM_PROPERTY_COMPARISON_KEYS = (
    "comparison_primary",
    "comparison_primary_action",
    "comparison_primary_reason",
    "comparison_primary_score",
    "comparison_secondary",
    "comparison_secondary_action",
    "comparison_secondary_reason",
    "comparison_secondary_score",
    "comparison_pair",
    "comparison_pair_refs",
)
_TELEGRAM_PROPERTY_INTENTS = {"property_compare", "property_review"}


def _telegram_strip_property_object_map(active_object_map: dict[str, str] | None) -> dict[str, str]:
    sanitized = {
        str(key or "").strip(): str(value or "").strip()
        for key, value in dict(active_object_map or {}).items()
        if str(key or "").strip() and str(value or "").strip()
    }
    for key in _TELEGRAM_PROPERTY_OBJECT_KEYS:
        sanitized.pop(key, None)
    return sanitized


def _telegram_strip_property_comparison_state(comparison_state: dict[str, str] | None) -> dict[str, str]:
    sanitized = {
        str(key or "").strip(): str(value or "").strip()
        for key, value in dict(comparison_state or {}).items()
        if str(key or "").strip() and str(value or "").strip()
    }
    for key in _TELEGRAM_PROPERTY_COMPARISON_KEYS:
        sanitized.pop(key, None)
    return sanitized


def _telegram_strip_property_intent_state(intent_state: dict[str, str] | None) -> dict[str, str]:
    sanitized = {
        str(key or "").strip(): str(value or "").strip()
        for key, value in dict(intent_state or {}).items()
        if str(key or "").strip() and str(value or "").strip()
    }
    if str(sanitized.get("active_intent") or "").strip().lower() in _TELEGRAM_PROPERTY_INTENTS:
        sanitized.pop("active_intent", None)
        sanitized.pop("active_profile_themes", None)
    return sanitized


def _telegram_property_comparison_lines(brief_items: list[object], *, limit: int = 2) -> list[str]:
    # Apartment/property comparison belongs to PropertyQuarry, not the EA Telegram assistant.
    return []


def _telegram_property_candidates(brief_items: list[object]) -> list[object]:
    # Apartment/property candidates belong to PropertyQuarry, not the EA Telegram assistant.
    return []


def _telegram_build_intent_state(
    *,
    text: str = "",
    reply_text: str = "",
    active_object_map: dict[str, str] | None = None,
) -> dict[str, str]:
    active_object_map = _telegram_strip_property_object_map(active_object_map)
    lowered = " ".join((str(text or "") + " " + str(reply_text or "")).lower().split())
    existing_theme_refs: list[str] = []
    for key in ("active_queue_profile_refs",):
        raw = str(active_object_map.get(key) or "").strip()
        if not raw:
            continue
        for item in raw.split(","):
            normalized = str(item or "").strip()
            if normalized and normalized not in existing_theme_refs:
                existing_theme_refs.append(normalized)
    intent = ""
    if any(
        marker in lowered
        for marker in (
            "rehab",
            "kfa",
            "bewilligung",
            "amtsarzt",
            "wiederbestellung",
            "school",
            "schule",
            "kindergarten",
            "pflegefreistellung",
            "insurance",
            "utility",
            "paperwork",
            "follow-up",
            "follow up",
        )
    ):
        intent = "admin_followup"
    if not intent and existing_theme_refs and any(
        marker in lowered for marker in ("paperwork", "that", "that one", "the follow-up", "the paperwork", "the admin")
    ):
        intent = "admin_followup"
    if not intent and any(marker in lowered for marker in ("approve", "approval", "reply", "draft", "email thread")):
        if active_object_map.get("active_email_thread") or active_object_map.get("active_queue_item"):
            intent = "email_approval"
    if not intent and any(marker in lowered for marker in ("calendar", "schedule", "appointment", "tomorrow", "focus")):
        intent = "planning"
    if not intent:
        return {}
    result = {"active_intent": intent}
    if existing_theme_refs:
        result["active_profile_themes"] = ", ".join(existing_theme_refs[:4])
    return result


def _telegram_reinforced_profile_themes_from_reply(
    *,
    brief_items: list[object],
    queue_items: list[object],
    reply_text: str,
    active_object_map: dict[str, str] | None = None,
) -> str:
    theme_refs: list[str] = []
    active_object_map = _telegram_strip_property_object_map(active_object_map)
    for key in ("active_queue_profile_refs",):
        raw = str(active_object_map.get(key) or "").strip()
        if not raw:
            continue
        for item in raw.split(","):
            normalized = str(item or "").strip()
            if normalized and normalized not in theme_refs:
                theme_refs.append(normalized)
    lowered_reply = " ".join(str(reply_text or "").lower().split())
    if lowered_reply:
        for item in list(brief_items) + list(queue_items):
            title = str(getattr(item, "title", "") or "").strip()
            summary = str(getattr(item, "summary", "") or "").strip()
            object_ref = str(getattr(item, "object_ref", "") or getattr(item, "id", "") or "").strip()
            matches_reply = False
            if title and title.lower() in lowered_reply:
                matches_reply = True
            elif object_ref and object_ref.lower() in lowered_reply:
                matches_reply = True
            elif summary:
                summary_words = [word for word in re.split(r"\W+", summary.lower()) if len(word) >= 5]
                matches_reply = any(word in lowered_reply for word in summary_words[:6])
            if not matches_reply:
                continue
            for ref in list(getattr(item, "profile_followup_refs", ()) or ()):
                normalized = str(ref or "").strip()
                if normalized and normalized not in theme_refs:
                    theme_refs.append(normalized)
    return ", ".join(theme_refs[:4])


def _telegram_reinforced_intent_state_from_reply(
    intent_state: dict[str, str],
    *,
    brief_items: list[object],
    queue_items: list[object],
    reply_text: str,
    active_object_map: dict[str, str] | None = None,
) -> dict[str, str]:
    reinforced = _telegram_strip_property_intent_state(intent_state)
    lowered_reply = " ".join(str(reply_text or "").lower().split())
    if not lowered_reply:
        return reinforced
    direct_admin_markers = (
        "rehab",
        "kfa",
        "bewilligung",
        "amtsarzt",
        "wiederbestellung",
        "school",
        "schule",
        "kindergarten",
        "pflegefreistellung",
        "insurance",
        "utility",
        "paperwork",
        "follow-up",
        "follow up",
        "care paperwork",
        "authorization",
        "authorisation",
    )
    if any(marker in lowered_reply for marker in direct_admin_markers):
        reinforced["active_intent"] = "admin_followup"
        return reinforced
    theme_refs = [
        str(item or "").strip()
        for item in str(reinforced.get("active_profile_themes") or "").split(",")
        if str(item or "").strip()
    ]
    active_object_map = _telegram_strip_property_object_map(active_object_map)
    for key in ("active_queue_profile_refs",):
        raw = str(active_object_map.get(key) or "").strip()
        if not raw:
            continue
        for item in raw.split(","):
            normalized = str(item or "").strip()
            if normalized and normalized not in theme_refs:
                theme_refs.append(normalized)
    if not theme_refs:
        return reinforced
    for item in list(brief_items) + list(queue_items):
        refs = [str(ref or "").strip() for ref in list(getattr(item, "profile_followup_refs", ()) or ()) if str(ref or "").strip()]
        object_ref = str(getattr(item, "object_ref", "") or "").strip()
        if object_ref:
            refs.append(object_ref)
        if not any(ref in theme_refs for ref in refs):
            continue
        title = str(getattr(item, "title", "") or "").strip().lower()
        summary = str(getattr(item, "summary", "") or "").strip().lower()
        why_now = str(getattr(item, "why_now", "") or "").strip().lower()
        recommended_action = str(getattr(item, "recommended_action", "") or "").strip().lower()
        if any(fragment and fragment in lowered_reply for fragment in (title, summary, why_now, recommended_action)):
            reinforced["active_intent"] = "admin_followup"
            return reinforced
    return reinforced


def _telegram_with_admin_followup_state(
    intent_state: dict[str, str],
    *,
    brief_items: list[object],
    queue_items: list[object],
    active_object_map: dict[str, str] | None = None,
) -> dict[str, str]:
    enriched = _telegram_strip_property_intent_state(intent_state)
    if str(enriched.get("active_intent") or "").strip().lower() != "admin_followup":
        return enriched
    theme_refs: list[str] = []
    for item in str(enriched.get("active_profile_themes") or "").split(","):
        normalized = str(item or "").strip()
        if normalized and normalized not in theme_refs:
            theme_refs.append(normalized)
    active_object_map = _telegram_strip_property_object_map(active_object_map)
    for key in ("active_queue_profile_refs",):
        raw = str(active_object_map.get(key) or "").strip()
        if not raw:
            continue
        for item in raw.split(","):
            normalized = str(item or "").strip()
            if normalized and normalized not in theme_refs:
                theme_refs.append(normalized)
    candidates = _telegram_admin_followup_candidates(
        brief_items,
        queue_items,
        theme_refs=theme_refs,
    )
    if not candidates:
        return enriched
    primary = candidates[0]
    primary_ref = str(getattr(primary, "object_ref", "") or getattr(primary, "id", "") or "").strip()
    primary_title = str(getattr(primary, "title", "") or "").strip()
    if primary_ref:
        enriched["active_admin_primary"] = primary_ref
    if primary_title:
        enriched["active_admin_primary_title"] = primary_title
    if len(candidates) > 1:
        secondary = candidates[1]
        secondary_ref = str(getattr(secondary, "object_ref", "") or getattr(secondary, "id", "") or "").strip()
        secondary_title = str(getattr(secondary, "title", "") or "").strip()
        if secondary_ref:
            enriched["active_admin_secondary"] = secondary_ref
        if secondary_title:
            enriched["active_admin_secondary_title"] = secondary_title
    return enriched


def _telegram_build_active_object_map(
    brief_items: list[object],
    queue_items: list[object],
) -> dict[str, str]:
    result: dict[str, str] = {}

    def _set(label: str, value: str) -> None:
        normalized_label = str(label or "").strip()
        normalized_value = str(value or "").strip()
        if not normalized_label or not normalized_value or normalized_label in result:
            return
        result[normalized_label] = normalized_value

    queue_items_sorted = list(queue_items)
    queue_items_sorted.sort(
        key=lambda row: (
            str(getattr(row, "priority", "") or "").strip().lower() != "high",
            -float(getattr(row, "rank_score", 0.0) or 0.0),
            str(getattr(row, "title", "") or "").strip().lower(),
        )
    )
    if queue_items_sorted:
        top_queue = queue_items_sorted[0]
        _set(
            "active_queue_item",
            f"{str(getattr(top_queue, 'title', '') or '').strip()} | "
            f"{str(getattr(top_queue, 'id', '') or '').strip()}",
        )
        refs = _telegram_queue_reference_suffix(top_queue).replace(" | refs: ", "", 1).strip()
        if refs:
            _set("active_queue_refs", refs)
        profile_refs = _telegram_profile_followup_refs_text(top_queue)
        if profile_refs:
            _set("active_queue_profile_refs", profile_refs)

    email_thread_refs: list[str] = []
    for item in list(queue_items) + list(brief_items):
        evidence_refs = list(getattr(item, "evidence_refs", ()) or ())
        for ref in evidence_refs:
            ref_id = str(getattr(ref, "ref_id", "") or "").strip()
            if ref_id.startswith("gmail-thread:") and ref_id not in email_thread_refs:
                email_thread_refs.append(ref_id)
    if email_thread_refs:
        _set("active_email_thread", email_thread_refs[0])

    return _telegram_strip_property_object_map(result)


def _telegram_build_comparison_state(brief_items: list[object]) -> dict[str, str]:
    candidates = _telegram_property_candidates(brief_items)
    if len(candidates) < 2:
        return {}
    first = candidates[0]
    second = candidates[1]
    first_title = str(getattr(first, "title", "") or "").strip()
    first_ref = str(getattr(first, "object_ref", "") or "").strip()
    first_reason = str(getattr(first, "why_now", "") or "").strip()
    first_action = str(getattr(first, "recommended_action", "") or "").strip()
    first_score = float(getattr(first, "score", 0.0) or 0.0)
    second_title = str(getattr(second, "title", "") or "").strip()
    second_ref = str(getattr(second, "object_ref", "") or "").strip()
    second_reason = str(getattr(second, "why_now", "") or "").strip()
    second_action = str(getattr(second, "recommended_action", "") or "").strip()
    second_score = float(getattr(second, "score", 0.0) or 0.0)
    if not first_title or not second_title:
        return {}
    result = {
        "comparison_primary": f"{first_title} | {first_ref}".strip(),
        "comparison_secondary": f"{second_title} | {second_ref}".strip(),
        "comparison_pair": f"{first_title} | {first_ref} || {second_title} | {second_ref}".strip(),
        "comparison_pair_refs": " ; ".join(
            part for part in (
                _telegram_brief_reference_suffix(first).replace(" | refs: ", "", 1).strip(),
                _telegram_brief_reference_suffix(second).replace(" | refs: ", "", 1).strip(),
            ) if part
        ),
    }
    if first_reason:
        result["comparison_primary_reason"] = first_reason
    if first_action:
        result["comparison_primary_action"] = first_action
    if first_score > 0.0:
        result["comparison_primary_score"] = str(int(round(first_score)))
    if second_reason:
        result["comparison_secondary_reason"] = second_reason
    if second_action:
        result["comparison_secondary_action"] = second_action
    if second_score > 0.0:
        result["comparison_secondary_score"] = str(int(round(second_score)))
    return _telegram_strip_property_comparison_state(result)


def _telegram_reinforce_comparison_state_from_reply(
    comparison_state: dict[str, str],
    *,
    brief_items: list[object],
    reply_text: str,
) -> dict[str, str]:
    reinforced = _telegram_strip_property_comparison_state(comparison_state)
    lowered_reply = " ".join(str(reply_text or "").lower().split())
    if not lowered_reply:
        return reinforced
    candidates = _telegram_property_candidates(brief_items)
    if len(candidates) < 2:
        return reinforced
    matched: list[object] = []
    for item in candidates:
        title = str(getattr(item, "title", "") or "").strip()
        object_ref = str(getattr(item, "object_ref", "") or "").strip()
        if not title:
            continue
        if title.lower() in lowered_reply or (object_ref and object_ref.lower() in lowered_reply):
            matched.append(item)
    if not matched:
        return reinforced
    ordered: list[object] = []
    seen_ids: set[str] = set()
    for item in matched + candidates:
        key = str(getattr(item, "id", "") or getattr(item, "object_ref", "") or "").strip()
        if not key or key in seen_ids:
            continue
        seen_ids.add(key)
        ordered.append(item)
        if len(ordered) >= 2:
            break
    if len(ordered) < 2:
        return reinforced
    first = ordered[0]
    second = ordered[1]
    first_title = str(getattr(first, "title", "") or "").strip()
    first_ref = str(getattr(first, "object_ref", "") or "").strip()
    first_reason = str(getattr(first, "why_now", "") or "").strip()
    first_action = str(getattr(first, "recommended_action", "") or "").strip()
    first_score = float(getattr(first, "score", 0.0) or 0.0)
    second_title = str(getattr(second, "title", "") or "").strip()
    second_ref = str(getattr(second, "object_ref", "") or "").strip()
    second_reason = str(getattr(second, "why_now", "") or "").strip()
    second_action = str(getattr(second, "recommended_action", "") or "").strip()
    second_score = float(getattr(second, "score", 0.0) or 0.0)
    if first_title and second_title:
        reinforced["comparison_primary"] = f"{first_title} | {first_ref}".strip()
        reinforced["comparison_secondary"] = f"{second_title} | {second_ref}".strip()
        reinforced["comparison_pair"] = f"{first_title} | {first_ref} || {second_title} | {second_ref}".strip()
        reinforced["comparison_pair_refs"] = " ; ".join(
            part for part in (
                _telegram_brief_reference_suffix(first).replace(" | refs: ", "", 1).strip(),
                _telegram_brief_reference_suffix(second).replace(" | refs: ", "", 1).strip(),
            ) if part
        )
        if first_reason:
            reinforced["comparison_primary_reason"] = first_reason
        if first_action:
            reinforced["comparison_primary_action"] = first_action
        if first_score > 0.0:
            reinforced["comparison_primary_score"] = str(int(round(first_score)))
        if second_reason:
            reinforced["comparison_secondary_reason"] = second_reason
        if second_action:
            reinforced["comparison_secondary_action"] = second_action
        if second_score > 0.0:
            reinforced["comparison_secondary_score"] = str(int(round(second_score)))
    return _telegram_strip_property_comparison_state(reinforced)


def _telegram_reinforce_active_object_map_from_reply(
    active_object_map: dict[str, str],
    *,
    brief_items: list[object],
    queue_items: list[object],
    reply_text: str,
) -> dict[str, str]:
    reinforced = _telegram_strip_property_object_map(active_object_map)
    lowered_reply = " ".join(str(reply_text or "").lower().split())
    if not lowered_reply:
        return reinforced

    queue_candidates = sorted(
        list(queue_items),
        key=lambda row: (
            str(getattr(row, "priority", "") or "").strip().lower() != "high",
            -float(getattr(row, "rank_score", 0.0) or 0.0),
        ),
    )
    for item in queue_candidates:
        title = str(getattr(item, "title", "") or "").strip()
        if title and title.lower() in lowered_reply:
            reinforced["active_queue_item"] = f"{title} | {str(getattr(item, 'id', '') or '').strip()}".strip(" |")
            refs = _telegram_queue_reference_suffix(item).replace(" | refs: ", "", 1).strip()
            if refs:
                reinforced["active_queue_refs"] = refs
            profile_refs = _telegram_profile_followup_refs_text(item)
            if profile_refs:
                reinforced["active_queue_profile_refs"] = profile_refs
            evidence_refs = list(getattr(item, "evidence_refs", ()) or ())
            for ref in evidence_refs:
                ref_id = str(getattr(ref, "ref_id", "") or "").strip()
                if ref_id.startswith("gmail-thread:"):
                    reinforced["active_email_thread"] = ref_id
                    break
            break

    return _telegram_strip_property_object_map(reinforced)


def _telegram_active_object_map_lines(active_object_map: dict[str, str]) -> list[str]:
    active_object_map = _telegram_strip_property_object_map(active_object_map)
    lines: list[str] = []
    for key in (
        "active_queue_item",
        "active_queue_refs",
        "active_queue_profile_refs",
        "active_email_thread",
    ):
        value = str(active_object_map.get(key) or "").strip()
        if value:
            lines.append(f"- {key}: {value}")
    return lines


def _telegram_recent_persisted_comparison_state(
    container: AppContainer,
    *,
    principal_id: str,
) -> dict[str, str]:
    rows = list(container.channel_runtime.list_recent_observations(limit=40, principal_id=principal_id))
    rows.sort(key=lambda row: (str(row.created_at or ""), str(row.observation_id or "")), reverse=True)
    for row in rows:
        if str(row.channel or "").strip() != "telegram":
            continue
        event_type = str(row.event_type or "").strip().lower()
        if event_type not in {"telegram.reply_sent", "telegram.reply_async_sent"}:
            continue
        payload = dict(row.payload or {})
        comparison_state = payload.get("comparison_state")
        if isinstance(comparison_state, dict) and comparison_state:
            return _telegram_strip_property_comparison_state(comparison_state)
    return {}


def _telegram_recent_persisted_intent_state(
    container: AppContainer,
    *,
    principal_id: str,
) -> dict[str, str]:
    rows = list(container.channel_runtime.list_recent_observations(limit=40, principal_id=principal_id))
    rows.sort(key=lambda row: (str(row.created_at or ""), str(row.observation_id or "")), reverse=True)
    for row in rows:
        if str(row.channel or "").strip() != "telegram":
            continue
        event_type = str(row.event_type or "").strip().lower()
        if event_type not in {"telegram.reply_sent", "telegram.reply_async_sent"}:
            continue
        payload = dict(row.payload or {})
        intent_state = payload.get("intent_state")
        if isinstance(intent_state, dict) and intent_state:
            return _telegram_strip_property_intent_state(intent_state)
    return {}


def _telegram_recent_persisted_object_map(
    container: AppContainer,
    *,
    principal_id: str,
) -> dict[str, str]:
    rows = list(container.channel_runtime.list_recent_observations(limit=40, principal_id=principal_id))
    rows.sort(key=lambda row: (str(row.created_at or ""), str(row.observation_id or "")), reverse=True)
    for row in rows:
        if str(row.channel or "").strip() != "telegram":
            continue
        event_type = str(row.event_type or "").strip().lower()
        if event_type not in {"telegram.reply_sent", "telegram.reply_async_sent"}:
            continue
        payload = dict(row.payload or {})
        active_object_map = payload.get("active_object_map")
        if isinstance(active_object_map, dict) and active_object_map:
            return _telegram_strip_property_object_map(active_object_map)
    return {}


def _telegram_office_grounding_text(container: AppContainer, *, principal_id: str) -> str:
    product_service = build_product_service(container)
    events = list(product_service.list_office_events(principal_id=principal_id, limit=12))
    upcoming_calendar = _telegram_upcoming_calendar_events(container, principal_id=principal_id, limit=4)
    ltd_profiles = _telegram_ltd_runtime_profiles(container)
    brief_items = []
    queue_items = []
    admin_focus_lines = _telegram_profile_admin_lines(container, principal_id=principal_id, limit=4)
    try:
        brief_items = list(product_service.list_brief_items(principal_id=principal_id, limit=5))
    except Exception:
        brief_items = []
    try:
        queue_items = list(product_service.list_queue(principal_id=principal_id, limit=5))
    except Exception:
        queue_items = []
    lines = [
        "Surface: Telegram chat with the principal.",
        "Use this grounding for personal schedule, inbox, links, and assistant-state questions.",
    ]
    recent_focus_lines = _telegram_recent_conversation_focus_lines(container, principal_id=principal_id, limit=4)
    if recent_focus_lines:
        lines.append("Recent conversation focus:")
        lines.extend(recent_focus_lines)
    recent_subject_lines = _telegram_recent_subject_hint_lines(container, principal_id=principal_id, limit=3)
    if recent_subject_lines:
        lines.append("Likely active subjects for short follow-ups:")
        lines.extend(recent_subject_lines)
    active_object_map = _telegram_build_active_object_map(brief_items, queue_items)
    comparison_state = _telegram_build_comparison_state(brief_items)
    persisted_comparison_state = _telegram_recent_persisted_comparison_state(container, principal_id=principal_id)
    persisted_object_map = _telegram_recent_persisted_object_map(container, principal_id=principal_id)
    persisted_intent_state = _telegram_recent_persisted_intent_state(container, principal_id=principal_id)
    derived_admin_refs: list[str] = []
    for item in list(brief_items) + list(queue_items):
        for ref in list(getattr(item, "profile_followup_refs", ()) or ()):
            normalized_ref = str(ref or "").strip()
            if normalized_ref and normalized_ref not in derived_admin_refs:
                derived_admin_refs.append(normalized_ref)
    for raw in (
        str(persisted_intent_state.get("active_profile_themes") or "").strip(),
        str(active_object_map.get("active_queue_profile_refs") or "").strip(),
        str(persisted_object_map.get("active_queue_profile_refs") or "").strip(),
    ):
        if not raw:
            continue
        for ref in raw.split(","):
            normalized_ref = str(ref or "").strip()
            if normalized_ref and normalized_ref not in derived_admin_refs:
                derived_admin_refs.append(normalized_ref)
    for line in _telegram_admin_focus_lines_from_profile_refs(derived_admin_refs, limit=4):
        if line not in admin_focus_lines:
            admin_focus_lines.append(line)
    merged_object_map = dict(active_object_map)
    for key, value in persisted_object_map.items():
        merged_object_map.setdefault(key, value)
    active_object_map_lines = _telegram_active_object_map_lines(merged_object_map)
    if active_object_map_lines:
        lines.append("Last active object map:")
        lines.extend(active_object_map_lines)
    merged_comparison_state = dict(comparison_state)
    for key, value in persisted_comparison_state.items():
        merged_comparison_state.setdefault(key, value)
    comparison_pair = str(merged_comparison_state.get("comparison_pair") or "").strip()
    if comparison_pair:
        lines.append("Last comparison pair:")
        comparison_primary = str(merged_comparison_state.get("comparison_primary") or "").strip()
        if comparison_primary:
            lines.append(f"- comparison_primary: {comparison_primary}")
        comparison_primary_reason = str(merged_comparison_state.get("comparison_primary_reason") or "").strip()
        if comparison_primary_reason:
            lines.append(f"- comparison_primary_reason: {comparison_primary_reason}")
        comparison_primary_action = str(merged_comparison_state.get("comparison_primary_action") or "").strip()
        if comparison_primary_action:
            lines.append(f"- comparison_primary_action: {comparison_primary_action}")
        comparison_primary_score = str(merged_comparison_state.get("comparison_primary_score") or "").strip()
        if comparison_primary_score:
            lines.append(f"- comparison_primary_score: {comparison_primary_score}")
        comparison_secondary = str(merged_comparison_state.get("comparison_secondary") or "").strip()
        if comparison_secondary:
            lines.append(f"- comparison_secondary: {comparison_secondary}")
        comparison_secondary_reason = str(merged_comparison_state.get("comparison_secondary_reason") or "").strip()
        if comparison_secondary_reason:
            lines.append(f"- comparison_secondary_reason: {comparison_secondary_reason}")
        comparison_secondary_action = str(merged_comparison_state.get("comparison_secondary_action") or "").strip()
        if comparison_secondary_action:
            lines.append(f"- comparison_secondary_action: {comparison_secondary_action}")
        comparison_secondary_score = str(merged_comparison_state.get("comparison_secondary_score") or "").strip()
        if comparison_secondary_score:
            lines.append(f"- comparison_secondary_score: {comparison_secondary_score}")
        lines.append(f"- comparison_pair: {comparison_pair}")
        comparison_pair_refs = str(merged_comparison_state.get("comparison_pair_refs") or "").strip()
        if comparison_pair_refs:
            lines.append(f"- comparison_pair_refs: {comparison_pair_refs}")
    active_intent = str(persisted_intent_state.get("active_intent") or "").strip()
    if active_intent:
        lines.append("Last active intent:")
        lines.append(f"- active_intent: {active_intent}")
        active_profile_themes = str(persisted_intent_state.get("active_profile_themes") or "").strip()
        if active_profile_themes:
            lines.append(f"- active_profile_themes: {active_profile_themes}")
        active_admin_primary = str(persisted_intent_state.get("active_admin_primary") or "").strip()
        if active_admin_primary:
            lines.append(f"- active_admin_primary: {active_admin_primary}")
        active_admin_primary_title = str(persisted_intent_state.get("active_admin_primary_title") or "").strip()
        if active_admin_primary_title:
            lines.append(f"- active_admin_primary_title: {active_admin_primary_title}")
        active_admin_secondary = str(persisted_intent_state.get("active_admin_secondary") or "").strip()
        if active_admin_secondary:
            lines.append(f"- active_admin_secondary: {active_admin_secondary}")
        active_admin_secondary_title = str(persisted_intent_state.get("active_admin_secondary_title") or "").strip()
        if active_admin_secondary_title:
            lines.append(f"- active_admin_secondary_title: {active_admin_secondary_title}")
    if admin_focus_lines:
        lines.append("Active admin focus:")
        lines.extend(f"- {line}" for line in admin_focus_lines)
    if ltd_profiles:
        lines.append("Available LTD runtime lanes:")
        for profile in ltd_profiles[:6]:
            service_name = str(getattr(profile, "service_name", "") or "").strip()
            runtime_state = str(getattr(profile, "runtime_state", "") or "").strip()
            tier = str(getattr(profile, "workspace_integration_tier", "") or "").strip()
            actions = [
                str(getattr(action, "action_key", "") or "").strip()
                for action in list(getattr(profile, "actions", ()) or ())
                if str(getattr(action, "action_key", "") or "").strip()
            ]
            detail = f"- {service_name}"
            if runtime_state:
                detail += f" [{runtime_state}]"
            if tier:
                detail += f" {tier}"
            if actions:
                detail += f" | actions: {', '.join(actions[:4])}"
            lines.append(detail)
    answerly_configs = _answerly_document_qa_configs()
    if answerly_configs:
        lines.append("Document Q&A backend:")
        for config in answerly_configs[:3]:
            scope = str(config.get("scope") or "").strip()
            label = str(config.get("label") or "").strip()
            scope_hint = f" [{scope}]" if scope and scope != "generic" else ""
            lines.append(
                f"- Answerly connected for {label}{scope_hint}. Keep this corpus separate and use it only when the user explicitly asks about that document source or when the active context clearly matches it."
            )
    if upcoming_calendar:
        lines.append("Upcoming calendar events:")
        for event in upcoming_calendar:
            start_text = event["start_at"].astimezone(ZoneInfo("Europe/Vienna")).strftime("%Y-%m-%d %H:%M")
            detail = f"- {start_text}: {event['title']}"
            if str(event.get("location") or "").strip():
                detail += f" @ {str(event.get('location') or '').strip()}"
            attendees = [str(item or "").strip() for item in list(event.get("attendees") or []) if str(item or "").strip()]
            if attendees:
                detail += f" with {', '.join(attendees[:3])}"
            lines.append(detail)
    else:
        lines.append("Upcoming calendar events: none visible in stored EA office signals.")
    recent_product_events = [row for row in events if str(row.get("channel") or "").strip() == "product"][:4]
    if recent_product_events:
        lines.append("Recent EA product events:")
        for row in recent_product_events:
            lines.append(f"- {str(row.get('event_type') or '').strip()}: {str(row.get('summary') or '').strip()}")
    if brief_items:
        lines.append("Top brief items:")
        for item in brief_items:
            score = float(getattr(item, "score", 0.0) or 0.0)
            title = str(getattr(item, "title", "") or "").strip()
            why_now = str(getattr(item, "why_now", "") or "").strip()
            recommended_action = str(getattr(item, "recommended_action", "") or "").strip()
            detail = f"- {title}"
            if score > 0.0:
                detail += f" (score {int(round(score)):d})"
            if why_now:
                detail += f": {why_now}"
            if recommended_action:
                detail += f" | next: {recommended_action}"
            detail += _telegram_brief_reference_suffix(item)
            lines.append(detail)
        comparison_lines = _telegram_property_comparison_lines(brief_items)
        if comparison_lines:
            lines.append("Top property comparisons:")
            lines.extend(comparison_lines)
    if queue_items:
        lines.append("Top queue items:")
        for item in queue_items:
            rank_score = float(getattr(item, "rank_score", 0.0) or 0.0)
            priority = str(getattr(item, "priority", "") or "").strip() or "normal"
            title = str(getattr(item, "title", "") or "").strip()
            summary = str(getattr(item, "summary", "") or "").strip()
            detail = f"- [{priority}] {title}"
            if rank_score > 0.0:
                detail += f" (rank {int(round(rank_score)):d})"
            if summary:
                detail += f": {summary}"
            detail += _telegram_queue_reference_suffix(item)
            lines.append(detail)
    recent_signal_events = [row for row in events if str(row.get("channel") or "").strip() in {"gmail", "calendar", "pocket"}][:6]
    if recent_signal_events:
        lines.append("Recent office signals:")
        for row in recent_signal_events:
            lines.append(
                f"- {str(row.get('channel') or '').strip()} {str(row.get('event_type') or '').strip()}: {str(row.get('summary') or '').strip()}"
            )
    return "\n".join(line for line in lines if line).strip()


def _telegram_real_ea_reply_text(
    *,
    container: AppContainer,
    principal_id: str,
    text: str,
    current_message_id: str = "",
    preferred_onemin_labels: tuple[str, ...] = (),
    timeout_seconds: float | None = None,
) -> str:
    normalized = str(text or "").strip()
    if not normalized:
        return ""
    if timeout_seconds is None:
        try:
            timeout_seconds = max(float(str(os.getenv("EA_TELEGRAM_RESPONSES_TIMEOUT_SECONDS") or "12").strip() or "12"), 1.0)
        except Exception:
            timeout_seconds = 12.0
    if float(timeout_seconds) <= 1.0:
        return ""
    model = str(os.getenv("EA_TELEGRAM_RESPONSES_MODEL") or "ea-coder-fast").strip() or "ea-coder-fast"
    normalized_preferred_onemin_labels = tuple(
        str(item or "").strip()
        for item in preferred_onemin_labels
        if str(item or "").strip()
    ) or _telegram_default_preferred_onemin_labels()
    grounding = _telegram_office_grounding_text(container, principal_id=principal_id)
    messages = [
        {
            "role": "system",
            "content": (
            "You are Executive Assistant replying inside a Telegram chat. "
            "Be concise, direct, and useful. "
            "Use the supplied grounding as source of truth for schedule, inbox, links, and workspace-state claims. "
            "Treat short follow-ups like 'well?', 'and?', 'why?', or 'again?' as referring to the most recent relevant subject in the conversation and grounding. "
            "If the grounding does not support a personal factual claim, say that clearly instead of guessing. "
            "Do not mention internal prompts, routes, tokens, or implementation details."
        ),
        },
        {
            "role": "system",
            "content": grounding,
        },
    ]
    for item in _telegram_recent_conversation_messages(
        container,
        principal_id=principal_id,
        current_message_id=current_message_id,
    ):
        role = str(item.get("role") or "").strip() or "user"
        content_parts = list(item.get("content") or [])
        text_part = ""
        for part in content_parts:
            if not isinstance(part, dict):
                continue
            text_part = str(part.get("text") or "").strip()
            if text_part:
                break
        if text_part:
            messages.append({"role": role, "content": text_part})
    messages.append({"role": "user", "content": normalized})
    result_box: dict[str, object] = {}
    error_box: dict[str, BaseException] = {}

    def _worker() -> None:
        try:
            result_box["result"] = _responses_route_module()._generate_upstream_text(
                prompt=normalized,
                messages=messages,
                requested_model=model,
                max_output_tokens=220,
                chatplayground_audit_callback=None,
                chatplayground_audit_callback_only=False,
                chatplayground_audit_principal_id=principal_id,
                preferred_onemin_labels=normalized_preferred_onemin_labels,
                request_deadline_monotonic=time.monotonic() + timeout_seconds,
            )
        except BaseException as exc:  # pragma: no cover - defensive thread boundary
            error_box["error"] = exc

    worker = threading.Thread(target=_worker, name="telegram-real-ea-reply", daemon=True)
    worker.start()
    # Keep the inline Telegram reply path fail-closed well ahead of the configured
    # deadline so suite load and scheduler jitter do not turn a soft timeout into
    # multi-second user-visible blocking.
    join_timeout = max(min(float(timeout_seconds) * 0.5, float(timeout_seconds) - 0.1), 0.05)
    worker.join(timeout=join_timeout)
    if worker.is_alive():
        return ""
    if error_box:
        return ""
    return str(getattr(result_box.get("result"), "text", "") or "").strip()


def _telegram_should_async_assistant_reply(text: str) -> bool:
    normalized = str(text or "").strip()
    if not normalized:
        return False
    if normalized.startswith("/"):
        return False
    if _safe_math_answer(normalized):
        return False
    lower = normalized.lower()
    alpha = "".join(ch for ch in lower if ch.isalpha() or ch.isspace()).strip()
    if lower in {"really", "really?"}:
        return False
    if ("today" in lower and "day" in lower) or alpha in {"day", "today", "what day", "weekday"}:
        return False
    if ("today" in lower and "date" in lower) or alpha in {"date", "today date", "what date"}:
        return False
    if ("time" in lower and "what" in lower) or alpha in {"time", "current time", "what time"}:
        return False
    schedule_markers = (
        "next appointment",
        "next meeting",
        "next calendar",
        "my calendar",
        "my schedule",
        "next event",
        "what's next",
        "whats next",
        "what is next",
        "appointment",
    )
    if any(marker in lower for marker in schedule_markers):
        return False
    if "http://" in normalized or "https://" in normalized:
        return False
    return True


def _telegram_prefers_local_grounded_reply(text: str) -> bool:
    normalized = str(text or "").strip()
    if not normalized:
        return False
    lower = normalized.lower()
    alpha = "".join(ch for ch in lower if ch.isalpha() or ch.isspace()).strip()
    if _telegram_meta_assistant_reply_text(normalized):
        return True
    if any(
        phrase in lower
        for phrase in (
            "do all of that by itself",
            "do that by itself",
            "handle property alerts by itself",
            "notification here",
        )
    ):
        return True
    if ("today" in lower and "day" in lower) or alpha in {"day", "today", "what day", "weekday"}:
        return True
    if ("today" in lower and "date" in lower) or alpha in {"date", "today date", "what date"}:
        return True
    if ("time" in lower and "what" in lower) or alpha in {"time", "current time", "what time"}:
        return True
    if "weather" in lower:
        return True
    schedule_markers = (
        "next appointment",
        "next meeting",
        "next calendar",
        "my calendar",
        "my schedule",
        "next event",
        "what's next",
        "whats next",
        "what is next",
        "appointment",
    )
    if any(marker in lower for marker in schedule_markers):
        return True
    if "google photos" in lower or "picture" in lower or "photo" in lower:
        return True
    return False


def _telegram_prefers_async_codex_chat(text: str) -> bool:
    normalized = str(text or "").strip()
    if not normalized:
        return False
    if normalized.startswith("/"):
        return False
    if _telegram_probe_reply_text(normalized):
        return False
    if _safe_math_answer(normalized):
        return False
    if "http://" in normalized or "https://" in normalized:
        return False
    if _telegram_meta_assistant_reply_text(normalized):
        return False
    if _telegram_prefers_local_grounded_reply(normalized):
        return False
    return True


def _telegram_should_persist_chat_memory(*, text: str, reply_text: str) -> bool:
    normalized = str(text or "").strip()
    if not normalized:
        return False
    if normalized.startswith("/"):
        return False
    if _telegram_probe_reply_text(normalized):
        return False
    if _telegram_meta_assistant_reply_text(normalized):
        return False
    if _safe_math_answer(normalized):
        return False
    if _telegram_prefers_local_grounded_reply(normalized):
        lower = normalized.lower()
        if "weather" in lower or "google photos" in lower or "picture" in lower or "photo" in lower:
            return False
        alpha = "".join(ch for ch in lower if ch.isalpha() or ch.isspace()).strip()
        if ("today" in lower and "day" in lower) or alpha in {"day", "today", "what day", "weekday"}:
            return False
        if ("today" in lower and "date" in lower) or alpha in {"date", "today date", "what date"}:
            return False
        if ("time" in lower and "what" in lower) or alpha in {"time", "current time", "what time"}:
            return False
    return bool(str(reply_text or "").strip())


def _telegram_compute_reply_memory_state(
    *,
    container: AppContainer,
    principal_id: str,
    text: str,
    reply_text: str,
    used_fallback_only: bool = False,
    probe_reply: str = "",
    last_resort_reply: str = "",
) -> TelegramReplyMemoryState:
    persist_memory = _telegram_should_persist_chat_memory(text=text, reply_text=reply_text)
    fallback_only_without_context = used_fallback_only and reply_text in {probe_reply, last_resort_reply}
    if not persist_memory or fallback_only_without_context:
        return TelegramReplyMemoryState(active_object_map={}, intent_state={}, comparison_state={})
    try:
        product_service = build_product_service(container)
        brief_items = list(product_service.list_brief_items(principal_id=principal_id, limit=5))
        queue_items = list(product_service.list_queue(principal_id=principal_id, limit=5))
        active_object_map = _telegram_reinforce_active_object_map_from_reply(
            _telegram_build_active_object_map(brief_items, queue_items),
            brief_items=brief_items,
            queue_items=queue_items,
            reply_text=reply_text,
        )
        comparison_state = _telegram_reinforce_comparison_state_from_reply(
            _telegram_build_comparison_state(brief_items),
            brief_items=brief_items,
            reply_text=reply_text,
        )
        intent_state = _telegram_build_intent_state(
            text=text,
            reply_text=reply_text,
            active_object_map=active_object_map,
        )
        active_profile_themes = _telegram_reinforced_profile_themes_from_reply(
            brief_items=brief_items,
            queue_items=queue_items,
            reply_text=reply_text,
            active_object_map=active_object_map,
        )
        if active_profile_themes:
            intent_state["active_profile_themes"] = active_profile_themes
        intent_state = _telegram_reinforced_intent_state_from_reply(
            intent_state,
            brief_items=brief_items,
            queue_items=queue_items,
            reply_text=reply_text,
            active_object_map=active_object_map,
        )
        intent_state = _telegram_with_admin_followup_state(
            intent_state,
            brief_items=brief_items,
            queue_items=queue_items,
            active_object_map=active_object_map,
        )
        return TelegramReplyMemoryState(
            active_object_map=active_object_map,
            intent_state=intent_state,
            comparison_state=comparison_state,
        )
    except Exception:
        return TelegramReplyMemoryState(active_object_map={}, intent_state={}, comparison_state={})


def _telegram_send_and_record_reply(
    *,
    container: AppContainer,
    principal_id: str,
    bot_config: dict[str, object],
    chat_id: str,
    dedupe_key: str,
    reply_text: str,
    source_text: str,
    async_mode: bool = False,
    current_message_id: str = "",
    used_fallback_only: bool = False,
    probe_reply: str = "",
    last_resort_reply: str = "",
    inline_buttons: list[list[tuple[str, str]]] | None = None,
) -> bool:
    receipt = _telegram_send_and_record_reply_receipt(
        container=container,
        principal_id=principal_id,
        bot_config=bot_config,
        chat_id=chat_id,
        dedupe_key=dedupe_key,
        reply_text=reply_text,
        source_text=source_text,
        async_mode=async_mode,
        current_message_id=current_message_id,
        used_fallback_only=used_fallback_only,
        probe_reply=probe_reply,
        last_resort_reply=last_resort_reply,
        inline_buttons=inline_buttons,
    )
    return str(receipt.get("status") or "").strip() == "sent"


def _telegram_send_and_record_reply_receipt(
    *,
    container: AppContainer,
    principal_id: str,
    bot_config: dict[str, object],
    chat_id: str,
    dedupe_key: str,
    reply_text: str,
    source_text: str,
    async_mode: bool = False,
    current_message_id: str = "",
    used_fallback_only: bool = False,
    probe_reply: str = "",
    last_resort_reply: str = "",
    inline_buttons: list[list[tuple[str, str]]] | None = None,
) -> dict[str, object]:
    if not reply_text or not chat_id:
        return {"status": "skipped", "reason": "reply_text_or_chat_missing"}
    memory_state = _telegram_compute_reply_memory_state(
        container=container,
        principal_id=principal_id,
        text=source_text,
        reply_text=reply_text,
        used_fallback_only=used_fallback_only,
        probe_reply=probe_reply,
        last_resort_reply=last_resort_reply,
    )
    try:
        receipt = _telegram_send_message(
            bot_token=str(bot_config.get("token") or "").strip(),
            chat_id=chat_id,
            text=reply_text,
            inline_buttons=inline_buttons,
        )
    except Exception as exc:
        if async_mode:
            _record_telegram_async_failed(
                container,
                principal_id=principal_id,
                chat_id=chat_id,
                current_message_id=current_message_id,
                prompt_text=source_text,
                stage="send_message",
                error=str(exc),
            )
        return {"status": "failed", "reason": type(exc).__name__}
    reply_sent = bool(receipt.get("ok"))
    if not reply_sent:
        return {"status": "failed", "reason": str(receipt.get("description") or "telegram_send_not_ok").strip()}
    result = dict(receipt.get("result") or {})
    message_id = str(result.get("message_id") or "").strip()
    if async_mode:
        container.channel_runtime.ingest_observation(
            principal_id=principal_id,
            channel="telegram",
            event_type="telegram.reply_async_sent",
            payload={
                "chat_id": chat_id,
                "reply_text": reply_text,
                "active_object_map": memory_state.active_object_map,
                "intent_state": memory_state.intent_state,
                "comparison_state": memory_state.comparison_state,
                "turn_state": "sent",
            },
            source_id=f"telegram:{chat_id}" if chat_id else "telegram",
            external_id=str(current_message_id or "").strip(),
            dedupe_key=f"{str(current_message_id or '').strip()}:assistant_async_sent" if str(current_message_id or '').strip() else "",
        )
        return {"status": "sent", "message_id": message_id}
    _record_telegram_reply_sent(
        container,
        principal_id=principal_id,
        chat_id=chat_id,
        dedupe_key=dedupe_key,
        reply_text=reply_text,
        message_id=message_id,
        active_object_map=memory_state.active_object_map,
        intent_state=memory_state.intent_state,
        comparison_state=memory_state.comparison_state,
    )
    return {"status": "sent", "message_id": message_id}


def _record_audiobook_public_share_reply_delivery(
    *,
    job: dict[str, object],
    send_receipt: dict[str, object],
) -> dict[str, object]:
    if str(job.get("status") or "").strip() != "audiobookshelf_imported":
        return job
    import_result = dict(job.get("audiobookshelf_import") or {})
    public_share = dict(import_result.get("public_share") or {})
    if str(public_share.get("status") or "").strip() != "public_share_ready":
        return job
    job_dir_raw = str(dict(job.get("storage") or {}).get("job_dir") or "").strip()
    if not job_dir_raw:
        return job
    notification = {
        "status": str(send_receipt.get("status") or "").strip() or "unknown",
        "message_id": str(send_receipt.get("message_id") or "").strip(),
        "reason": str(send_receipt.get("reason") or "").strip(),
    }
    try:
        return _record_audiobookshelf_public_share_telegram_delivery(
            job_dir=Path(job_dir_raw),
            job=job,
            notification=notification,
        )
    except Exception:
        return job


def _telegram_audiobook_sender_ref(ctx: TelegramTurnContext) -> str:
    chat_id = str(ctx.chat_id or "").strip()
    return f"telegram:{chat_id}" if chat_id else ""


def _telegram_audiobook_sender_trusted(ctx: TelegramTurnContext, *, sender_ref: str) -> bool:
    if audiobook_access_approval.is_instant_sender(sender_ref=sender_ref, channel="telegram"):
        return True
    if not str(ctx.chat_id or "").strip() or not str(ctx.principal_id or "").strip():
        return False
    with contextlib.suppress(Exception):
        return _telegram_principal_is_registered_user(ctx.container, ctx.principal_id)
    return False


def _telegram_start_approved_audiobook_request(
    *,
    bot_config: dict[str, object],
    record: dict[str, object],
) -> dict[str, object]:
    source = dict(record.get("source") or {})
    telegram = dict(record.get("telegram") or {})
    source_path = audiobook_access_approval.source_path(record)
    if not source_path.is_file():
        raise RuntimeError("approved_audiobook_source_missing")
    requester_chat_id = str(telegram.get("chat_id") or "").strip()
    job = create_job_from_epub(
        epub_path=source_path,
        original_filename=str(source.get("filename") or source_path.name).strip() or source_path.name,
        principal_id=str(record.get("principal_id") or "").strip(),
        chat_id=requester_chat_id,
        message_id=str(telegram.get("message_id") or "").strip(),
        caption="",
        source_url="",
    )
    if requester_chat_id:
        sample_receipts = _telegram_send_audiobook_voice_samples(
            bot_config=bot_config,
            chat_id=requester_chat_id,
            job=job,
        )
        if sample_receipts:
            job = record_audiobook_voice_sample_delivery(job=job, sample_receipts=sample_receipts)
        job, inline_buttons = _telegram_audiobook_playback_acceptance_buttons(
            bot_config=bot_config,
            chat_id=requester_chat_id,
            job=job,
        )
        _telegram_send_message(
            bot_token=str(bot_config.get("token") or "").strip(),
            chat_id=requester_chat_id,
            text=telegram_epub_reply_text(job),
            inline_buttons=inline_buttons or None,
        )
    audiobook_access_approval.update_status(
        str(record.get("approval_id") or "").strip(),
        status="started",
        job_id=str(job.get("job_id") or "").strip(),
    )
    return job


def _telegram_turn_context(
    *,
    container: AppContainer,
    principal_id: str,
    text: str,
    payload: dict[str, object] | None = None,
    bot_handle: str,
    preferred_onemin_labels: tuple[str, ...] = (),
    current_message_id: str = "",
    chat_id: str = "",
) -> TelegramTurnContext:
    return build_turn_context(
        container=container,
        principal_id=principal_id,
        text=text,
        payload=dict(payload or {}),
        bot_handle=bot_handle,
        preferred_onemin_labels=preferred_onemin_labels,
        current_message_id=current_message_id,
        chat_id=chat_id,
        completion_cue_predicate=_telegram_low_signal_followup_cue,
    )


def _telegram_command_turn_decision(ctx: TelegramTurnContext) -> TelegramTurnDecision:
    command = ctx.normalized.split()[0].split("@", 1)[0].lower() if ctx.normalized else ""
    handle = str(ctx.bot_handle or "").strip() or "this bot"
    if command == "/start":
        return TelegramTurnDecision(
            reply_text=(
                f"{handle} is connected to Executive Assistant.\n\n"
                "You can send messages, links, and follow-up requests here. "
                f"EA will capture this chat for {_assistant_owner_label()} and use it as a live assistant inbox."
            )
        )
    if command == "/help":
        return TelegramTurnDecision(
            reply_text=(
                "Available commands:\n"
                "/start - connect this chat to Executive Assistant\n"
                "/help - show this help text\n"
                "/status - check bot and routing status\n\n"
                "You can also send notes, links, or direct assistant requests in plain text."
            )
        )
    if command == "/status":
        return TelegramTurnDecision(
            reply_text=(
                "EA is online.\n"
                "Telegram ingest is active.\n"
                "Google signal sync is active.\n"
                "Pocket sync is active.\n"
                "Teable preference review sync is active."
            )
        )
    return TelegramTurnDecision()


def _telegram_callback_turn_decision(ctx: TelegramTurnContext) -> TelegramTurnDecision:
    if str(ctx.payload.get("kind") or "").strip().lower() != "callback_query":
        return TelegramTurnDecision()
    callback_data = str(ctx.payload.get("callback_data") or "").strip()
    callback_dedupe_key = str(ctx.payload.get("_dedupe_key") or "").strip()
    callback_query_id = str(ctx.payload.get("callback_query_id") or "").strip()
    callback_kind = callback_data.split("|", 1)[0].strip().lower() if "|" in callback_data else ""
    if callback_dedupe_key and _telegram_callback_already_processed(
        ctx.container,
        principal_id=ctx.principal_id,
        dedupe_key=callback_dedupe_key,
    ):
        return TelegramTurnDecision()

    def _processed_callback_decision(**kwargs: object) -> TelegramTurnDecision:
        _record_telegram_callback_processed(
            ctx.container,
            principal_id=ctx.principal_id,
            chat_id=ctx.chat_id,
            dedupe_key=callback_dedupe_key,
            callback_query_id=callback_query_id,
            callback_kind=callback_kind,
            reply_text=str(kwargs.get("reply_text") or "").strip(),
            current_message_id=ctx.current_message_id,
            source_text=str(ctx.payload.get("text") or ctx.payload.get("message_text") or "").strip(),
        )
        return TelegramTurnDecision(**kwargs)

    if callback_data.startswith("aa|"):
        bot_config = dict(ctx.payload.get("_bot_config") or {})
        callback_packet = audiobook_access_approval.decode_telegram_approval_callback(
            callback_data=callback_data,
            approver_chat_id=ctx.chat_id,
            bot_token=str(bot_config.get("token") or "").strip(),
        )
        if not bool(callback_packet.get("ok")):
            reason = str(callback_packet.get("reason") or "").strip().lower()
            if reason == "expired":
                return TelegramTurnDecision(reply_text="That audiobook approval button expired.")
            return TelegramTurnDecision(reply_text="That audiobook approval button is no longer valid.")
        approval_id = str(callback_packet.get("approval_id") or "").strip()
        record = audiobook_access_approval.load_request(approval_id)
        if not record:
            return TelegramTurnDecision(reply_text="That audiobook approval request no longer exists.")
        current_status = str(record.get("status") or "").strip().lower()
        if current_status not in {"pending", "approved"}:
            return TelegramTurnDecision(reply_text=f"That audiobook request is already {current_status}.")
        action = str(callback_packet.get("action") or "").strip()
        if action == "deny":
            audiobook_access_approval.update_status(
                approval_id,
                status="denied",
                decided_by=f"telegram:{ctx.chat_id}",
            )
            telegram = dict(record.get("telegram") or {})
            requester_chat_id = str(telegram.get("chat_id") or "").strip()
            if requester_chat_id:
                _telegram_send_message(
                    bot_token=str(bot_config.get("token") or "").strip(),
                    chat_id=requester_chat_id,
                    text="That audiobook request was not approved.",
                )
            return _processed_callback_decision(reply_text="Denied the audiobook request.")
        approved = audiobook_access_approval.update_status(
            approval_id,
            status="approved",
            decided_by=f"telegram:{ctx.chat_id}",
        )
        if str(approved.get("channel") or "").strip() == "telegram":
            try:
                job = _telegram_start_approved_audiobook_request(
                    bot_config=bot_config,
                    record=approved,
                )
            except Exception as exc:
                audiobook_access_approval.update_status(
                    approval_id,
                    status="failed",
                    reason=str(exc).strip() or type(exc).__name__,
                )
                return TelegramTurnDecision(
                    reply_text=(
                        "Approved, but I could not start that audiobook yet. "
                        f"Current blocker: {compact_text(str(exc), fallback='approved_audiobook_start_failed', limit=140)}."
                    )
                )
            title = str(dict(job.get("metadata") or {}).get("title") or dict(approved.get("source") or {}).get("filename") or "the audiobook").strip()
            return _processed_callback_decision(reply_text=f"Approved and started the audiobook job for {title}.")
        return _processed_callback_decision(
            reply_text="Approved. The WhatsApp audiobook processor will start this request on its next run."
        )
    if callback_data.startswith("ap|"):
        bot_config = dict(ctx.payload.get("_bot_config") or {})
        callback_packet = _telegram_decode_audiobook_playback_callback(
            bot_config=bot_config,
            callback_data=callback_data,
            chat_id=ctx.chat_id,
        )
        if not bool(callback_packet.get("ok")):
            reason = str(callback_packet.get("reason") or "").strip().lower()
            if reason == "expired":
                return TelegramTurnDecision(reply_text="That audiobook playback button expired. Send 'audiobook status' if you want me to check the job again.")
            return TelegramTurnDecision(reply_text="That audiobook playback button is no longer valid.")
        action = str(callback_packet.get("action") or "").strip()
        accepted = action == "accepted"
        try:
            record_audiobook_playback_acceptance_by_callback_token(
                callback_token=str(callback_packet.get("token") or "").strip(),
                accepted=accepted,
                source="telegram_button",
                message_id=ctx.current_message_id,
                feedback="telegram_button_playback_accepted" if accepted else "telegram_button_playback_problem",
            )
        except Exception as exc:
            return TelegramTurnDecision(
                reply_text=(
                    "I could not record that audiobook playback result. "
                    f"Current blocker: {compact_text(str(exc), fallback='audiobook_playback_acceptance_failed', limit=140)}."
                )
            )
        if accepted:
            return _processed_callback_decision(reply_text="Marked the audiobook playback as working.")
        return _processed_callback_decision(reply_text="Noted. I marked this audiobook for playback review.")
    if callback_data.startswith("ab|"):
        bot_config = dict(ctx.payload.get("_bot_config") or {})
        callback_packet = _telegram_decode_audiobook_voice_callback(
            bot_config=bot_config,
            callback_data=callback_data,
            chat_id=ctx.chat_id,
        )
        if not bool(callback_packet.get("ok")):
            reason = str(callback_packet.get("reason") or "").strip().lower()
            if reason == "expired":
                return TelegramTurnDecision(reply_text="That audiobook voice button expired. Ask for fresh audiobook voice samples and I will resend them.")
            return TelegramTurnDecision(reply_text="That audiobook voice button is no longer valid.")
        try:
            job = apply_audiobook_voice_audition_action(
                callback_token=str(callback_packet.get("token") or "").strip(),
                action=str(callback_packet.get("action") or "").strip(),
            )
        except Exception as exc:
            reason = str(exc).strip()
            if reason in {"voice_audition_token_not_found", "voice_audition_token_missing"}:
                return TelegramTurnDecision(
                    reply_text=(
                        "That audiobook voice button is stale, so I ignored it. "
                        "Use the latest voice sample buttons, or reply with the voice name or 'dismiss all'."
                    )
                )
            return TelegramTurnDecision(
                reply_text=(
                    "I could not apply that audiobook voice choice. "
                    f"Current blocker: {compact_text(str(exc), fallback='audiobook_voice_choice_failed', limit=140)}."
                )
            )
        action = str(callback_packet.get("action") or "").strip()
        if action == "dismiss":
            voice_selection = dict(dict(job.get("provider") or {}).get("voice_selection") or {})
            last_action = dict(voice_selection.get("last_action") or {})
            replacement_keys = _extract_audiobook_voice_replacement_keys(
                voice_selection=voice_selection,
                last_action=last_action,
            )
            if not replacement_keys:
                refreshed_job = _telegram_refill_audiobook_voice_audition_if_needed(job=job)
                if refreshed_job is not job:
                    job = refreshed_job
                    voice_selection = dict(dict(job.get("provider") or {}).get("voice_selection") or {})
                    last_action = dict(voice_selection.get("last_action") or {})
                    replacement_keys = _extract_audiobook_voice_replacement_keys(
                        voice_selection=voice_selection,
                        last_action=last_action,
                    )
            if replacement_keys:
                sample_job = _telegram_audiobook_voice_sample_subset(job, replacement_keys)
                if not _telegram_audiobook_voice_samples_pending_delivery(sample_job):
                    return _processed_callback_decision(
                        reply_text=(
                            "Dismissed. The replacement audiobook voice sample is already in Telegram. "
                            "Use the latest buttons, or reply with the voice name."
                        )
                    )
                sample_receipts = _telegram_send_audiobook_voice_samples(bot_config=bot_config, chat_id=ctx.chat_id, job=sample_job)
                if sample_receipts:
                    job = record_audiobook_voice_sample_delivery(job=job, sample_receipts=sample_receipts)
                    sent_count = sum(1 for item in sample_receipts if str(dict(item).get("status") or "").strip() == "sent")
                    if sent_count and sent_count < len(sample_receipts):
                        return _processed_callback_decision(
                            reply_text=f"Dismissed. I sent {sent_count} of {len(sample_receipts)} replacement audiobook voice samples; the rest are still blocked."
                        )
                    if sent_count:
                        sample_word = "sample" if sent_count == 1 else "samples"
                        return _processed_callback_decision(
                            reply_text=f"Dismissed. I sent {sent_count} replacement audiobook voice {sample_word}."
                        )
                    return _processed_callback_decision(
                        reply_text="Dismissed. The replacement audiobook voice is ready, but Telegram could not deliver the sample audio."
                    )
                return _processed_callback_decision(
                    reply_text="Dismissed. The replacement audiobook voice is ready, but I could not send the sample audio."
                )
            if str(voice_selection.get("status") or "").strip().lower() == "exhausted":
                return _processed_callback_decision(
                    reply_text="Dismissed. No more configured audiobook voice samples are available for this book."
                )
            remaining = int(last_action.get("remaining_in_batch") or 0)
            if remaining > 0:
                sample_word = "sample" if remaining == 1 else "samples"
                verb = "remains" if remaining == 1 else "remain"
                return _processed_callback_decision(
                    reply_text=(
                        f"Dismissed. {remaining} audiobook voice {sample_word} {verb} "
                        "in this audition batch, and no replacement candidates were currently available."
                    )
                )
            return _processed_callback_decision(reply_text="Dismissed. No replacement audiobook voice sample is available yet.")
        voice_selection = dict(dict(job.get("provider") or {}).get("voice_selection") or {})
        if str(voice_selection.get("status") or "").strip() == "waiting_user_choice":
            last_action = dict(voice_selection.get("last_action") or {})
            replacement_keys = _extract_audiobook_voice_replacement_keys(
                voice_selection=voice_selection,
                last_action=last_action,
            )
            if replacement_keys:
                sample_job = _telegram_audiobook_voice_sample_subset(job, replacement_keys)
                sample_receipts = _telegram_send_audiobook_voice_samples(bot_config=bot_config, chat_id=ctx.chat_id, job=sample_job)
                if sample_receipts:
                    job = record_audiobook_voice_sample_delivery(job=job, sample_receipts=sample_receipts)
        return _processed_callback_decision(reply_text=telegram_epub_reply_text(job))
    if callback_data.startswith("fb|"):
        callback_packet = decode_telegram_feedback_callback_data(
            bot_token=str(dict(ctx.payload.get("_bot_config") or {}).get("token") or "").strip(),
            callback_data=callback_data,
            chat_id=ctx.chat_id,
        )
        if not bool(callback_packet.get("ok")):
            reason = str(callback_packet.get("reason") or "").strip().lower()
            if reason == "expired":
                return TelegramTurnDecision(reply_text="That feedback button expired. Send a fresh request if you want to tune this again.")
            return TelegramTurnDecision(reply_text="That feedback button is no longer valid.")
        service = build_product_service(ctx.container)
        result = service.record_notification_feedback(
            principal_id=ctx.principal_id,
            notification_key=str(callback_packet.get("notification_key") or "").strip(),
            feedback_key=str(callback_packet.get("feedback_key") or "").strip(),
            actor="telegram_feedback",
            chat_id=ctx.chat_id,
        )
        return _processed_callback_decision(reply_text=str(result.get("reply_text") or "Noted.").strip() or "Noted.")
    if callback_data.startswith("po|"):
        callback_packet = decode_proactive_ooda_telegram_callback(
            callback_data=callback_data,
            chat_id=ctx.chat_id,
            bot_token=str(dict(ctx.payload.get("_bot_config") or {}).get("token") or "").strip(),
        )
        if not bool(callback_packet.get("ok")):
            reason = str(callback_packet.get("reason") or "").strip().lower()
            if reason == "expired":
                return TelegramTurnDecision(reply_text="That proactive OODA approval button expired. Ask EA for a fresh packet if you still want to decide.")
            return TelegramTurnDecision(reply_text="That proactive OODA approval button is no longer valid.")
        try:
            result = apply_proactive_ooda_telegram_approval_callback(
                callback_token=str(callback_packet.get("callback_token") or "").strip(),
                outcome=str(callback_packet.get("action") or "").strip(),
                principal_id=ctx.principal_id,
                actor=f"telegram:{ctx.chat_id}",
                message_id=ctx.current_message_id,
                container=ctx.container,
                state_path=os.getenv("EA_PROACTIVE_OODA_STATE_PATH", "state/proactive_ooda_notified.json"),
                receipt_path=os.getenv("EA_PROACTIVE_OODA_RECEIPT_PATH", ""),
                stage_packet_dir=os.getenv("EA_PROACTIVE_OODA_STAGE_PACKET_DIR", ""),
                safe_work_result_dir=os.getenv("EA_PROACTIVE_OODA_SAFE_WORK_RESULT_DIR", ""),
            )
        except Exception as exc:
            reason = str(exc).strip()
            if reason == "proactive_ooda_approval_callback_token_not_found":
                return TelegramTurnDecision(reply_text="That proactive OODA decision button is stale, so I ignored it.")
            return TelegramTurnDecision(
                reply_text=(
                    "I could not record that proactive OODA decision. "
                    f"Current blocker: {compact_text(str(exc), fallback='proactive_ooda_approval_capture_failed', limit=140)}."
                )
            )
        recorded_outcome = str(result.get("outcome") or "").strip()
        if str(result.get("status") or "").strip() == "already_recorded":
            return _processed_callback_decision(
                reply_text=f"That proactive OODA decision is already recorded as {recorded_outcome}."
            )
        if recorded_outcome == "approved":
            execution = dict(result.get("execution") or {})
            execution_status = str(execution.get("status") or "").strip().lower()
            execution_action = str(execution.get("action") or "").strip().lower()
            if execution_status == "executed" and execution_action == "save_gmail_draft":
                lines = ["Approved. I saved the draft in Gmail."]
                draft_folder_url = str(execution.get("draft_folder_url") or "").strip()
                if draft_folder_url:
                    lines.append(f"Open Drafts: {draft_folder_url}")
                gmail_draft_id = str(execution.get("gmail_draft_id") or "").strip()
                if gmail_draft_id:
                    lines.append(f"Draft ID: {gmail_draft_id}")
                return _processed_callback_decision(reply_text="\n".join(lines))
            if execution_status == "already_executed" and execution_action == "save_gmail_draft":
                return _processed_callback_decision(reply_text="Approved. The Gmail draft was already saved.")
            if execution_status == "blocked":
                lines = ["Approved, but I could not execute the staged next step yet."]
                reason = compact_text(
                    str(execution.get("reason") or "").strip(),
                    fallback="approved_action_blocked",
                    limit=140,
                )
                if reason:
                    lines.append(f"Current blocker: {reason}.")
                next_action = dict(execution.get("next_action_surface") or {})
                href = str(next_action.get("href") or "").strip()
                if href:
                    lines.append(f"Next action: {href}")
                return _processed_callback_decision(reply_text="\n".join(lines))
            return _processed_callback_decision(
                reply_text="Recorded as approved. EA kept the action staged; no purchase, booking, or send was executed."
            )
        if recorded_outcome == "rejected":
            return _processed_callback_decision(
                reply_text="Recorded as rejected. EA will keep this proactive OODA action staged only."
            )
        if recorded_outcome == "deferred":
            return _processed_callback_decision(
                reply_text="Recorded as deferred. EA will leave this proactive OODA action staged for later review."
            )
        return _processed_callback_decision(reply_text=f"Recorded that proactive OODA decision as {recorded_outcome}.")
    callback_packet = _telegram_decode_callback_data(
        bot_config=dict(ctx.payload.get("_bot_config") or {}),
        callback_data=callback_data,
        chat_id=ctx.chat_id,
    )
    if not bool(callback_packet.get("ok")):
        reason = str(callback_packet.get("reason") or "").strip().lower()
        if reason == "expired":
            return TelegramTurnDecision(reply_text="That button expired. Send the request again if you still want EA to work on it.")
        return TelegramTurnDecision(reply_text="That Telegram action is no longer valid. Send the request again if needed.")
    action = str(callback_packet.get("action") or "").strip().lower()
    current_message_id = str(callback_packet.get("current_message_id") or "").strip()
    snapshot = _telegram_async_turn_snapshot(
        ctx.container,
        principal_id=ctx.principal_id,
        current_message_id=current_message_id,
        chat_id=ctx.chat_id,
    )
    if action == "status":
        status = str(snapshot.get("status") or "").strip().lower()
        failure_reason = str(snapshot.get("error") or "").strip()
        if status == "sent":
            return _processed_callback_decision(reply_text="EA already finished that request and sent the reply here.")
        if status == "failed":
            if failure_reason:
                return _processed_callback_decision(
                    reply_text=(
                        "That request failed after processing. "
                        f"Last status: {failure_reason}. "
                        "Tap Retry to run it again."
                    )
                )
            return _processed_callback_decision(reply_text="That request failed after processing. Tap Retry to run it again.")
        return _processed_callback_decision(
            reply_text=(
                "EA is still processing that request.\n"
                "The message is persisted, deduped, and running off the webhook path."
            )
        )
    if action == "help":
        return _processed_callback_decision(
            reply_text=(
                "Use plain language here.\n"
                "For deterministic things EA answers directly.\n"
                "For heavier requests EA acknowledges first and finishes the work asynchronously."
            )
        )
    if action == "retry":
        status = str(snapshot.get("status") or "").strip().lower()
        if status in {"queued", "processing"}:
            return _processed_callback_decision(reply_text="EA is already working on that request.")
        if status == "sent":
            return _processed_callback_decision(
                reply_text="EA already answered that request here. Send a new message if you want a fresh run."
            )
        if not str(snapshot.get("prompt_text") or "").strip():
            return _processed_callback_decision(
                reply_text="EA could not recover the original request text for that button. Send the request again."
            )
        retry_message_id = f"{current_message_id}:retry:{int(time.time())}" if current_message_id else f"retry:{int(time.time())}"
        return _processed_callback_decision(
            schedule_async=True,
            async_text=str(snapshot.get("prompt_text") or "").strip(),
            async_message_id=retry_message_id,
            retry_budget=2,
        )
    return TelegramTurnDecision()


def _telegram_notification_feedback_followup_turn_decision(ctx: TelegramTurnContext) -> TelegramTurnDecision:
    if str(ctx.payload.get("kind") or "").strip().lower() == "callback_query":
        return TelegramTurnDecision()
    normalized = str(ctx.normalized or "").strip()
    if not normalized:
        return TelegramTurnDecision()
    service = build_product_service(ctx.container)
    recorder = getattr(service, "record_notification_feedback_followup_response", None)
    if not callable(recorder):
        return TelegramTurnDecision()
    result = recorder(
        principal_id=ctx.principal_id,
        chat_id=ctx.chat_id,
        text=normalized,
        actor="telegram_feedback_followup",
    )
    if str(result.get("status") or "").strip().lower() in {"recorded", "duplicate", "empty"}:
        return TelegramTurnDecision(reply_text=str(result.get("reply_text") or "").strip() or "Noted.")
    return TelegramTurnDecision()


def _telegram_latest_supported_property_link_in_telegram_chat(
    container: AppContainer,
    *,
    principal_id: str,
    chat_id: str,
) -> str:
    normalized_chat_id = str(chat_id or "").strip()
    for row in container.channel_runtime.list_recent_observations(limit=80, principal_id=principal_id):
        if str(row.channel or "").strip().lower() != "telegram":
            continue
        payload = dict(row.payload or {})
        if normalized_chat_id and str(payload.get("chat_id") or "").strip() != normalized_chat_id:
            continue
        event_type = str(row.event_type or "").strip().lower()
        text = ""
        if event_type == "telegram.message":
            text = str(payload.get("text") or "").strip()
        elif event_type in {"telegram.reply_sent", "telegram.reply_async_sent", "telegram.reply_async_started", "telegram.reply_async_failed"}:
            text = str(payload.get("reply_text") or payload.get("prompt_text") or "").strip()
        if not text:
            continue
        candidate = _telegram_supported_property_link(text)
        if candidate:
            return candidate
    return ""


def _telegram_scout_update_turn_decision(ctx: TelegramTurnContext) -> TelegramTurnDecision:
    normalized = str(ctx.normalized or "").strip()
    if not normalized:
        return TelegramTurnDecision()
    lowered = " ".join(normalized.lower().split())
    if not (
        "/scout_update" in lowered
        or "/scoutupdate" in lowered
        or "/scout-update" in lowered
        or "scout update" in lowered
    ):
        return TelegramTurnDecision()
    return TelegramTurnDecision(reply_text=_telegram_property_boundary_reply_text())


def _telegram_link_turn_decision(ctx: TelegramTurnContext) -> TelegramTurnDecision:
    if "http://" not in ctx.normalized and "https://" not in ctx.normalized:
        return TelegramTurnDecision()
    property_url = _telegram_supported_property_link(ctx.normalized)
    if property_url:
        return TelegramTurnDecision(reply_text=_telegram_property_boundary_reply_text())
    broker_portal_url = _telegram_login_walled_property_link(ctx.normalized)
    if broker_portal_url:
        return TelegramTurnDecision(reply_text=_telegram_property_boundary_reply_text())
    local_assistant_reply = _telegram_local_assistant_reply_text(
        ctx.container,
        principal_id=ctx.principal_id,
        text=ctx.normalized,
    )
    if local_assistant_reply:
        return TelegramTurnDecision(reply_text=local_assistant_reply)
    return TelegramTurnDecision(
        reply_text=(
            "Link received. EA captured it and will route it into "
            f"{_assistant_owner_possessive_label()} assistant workspace for review."
        )
    )


def _telegram_supported_property_link(text: str) -> str:
    normalized = str(text or "").strip()
    if not normalized:
        return ""
    for raw in _URL_RE.findall(normalized):
        candidate = str(raw or "").strip().rstrip(").,!?]}>")
        if candidate and product_service_module._property_scout_is_supported_listing_url(candidate):
            return candidate
    return ""


def _telegram_property_link_bundle_retryable_pending_reason(reason: str) -> bool:
    normalized = str(reason or "").strip().lower()
    if not normalized:
        return False
    return (
        "3d tour missing" in normalized
        or "flythrough video missing" in normalized
        or "dossier not rendered" in normalized
    )


def _telegram_property_link_bundle_retryable_failed_reason(reason: str) -> bool:
    normalized = str(reason or "").strip().lower()
    if not normalized:
        return False
    return (
        "timeout" in normalized
        or "rate limit" in normalized
        or "temporar" in normalized
        or "429" in normalized
        or "502" in normalized
        or "503" in normalized
        or "504" in normalized
        or "connection" in normalized
        or "network" in normalized
        or "upstream" in normalized
        or "service unavailable" in normalized
        or "internal server error" in normalized
    )


def _telegram_property_tour_upgrade_hint(reason: str) -> str:
    normalized = str(reason or "").strip().lower()
    if "property_tour_upgrade_required:plus" in normalized:
        return (
            "You reached your Free tier tour limit (1/day). "
            "Upgrade to Plus for 3 property dossiers per day."
        )
    if "property_tour_upgrade_required:agent" in normalized:
        return (
            "You reached your Plus daily tour limit (3/day). "
            "Upgrade to Agent for unlimited artifact generation."
        )
    return ""


def _telegram_property_link_bundle_error_reply(reason: str, *, prompt_text: str = "") -> str:
    upgrade_hint = _telegram_property_tour_upgrade_hint(str(reason or ""))
    if upgrade_hint:
        return upgrade_hint
    normalized_reason = str(reason or "an internal error").strip()
    if len(normalized_reason) > 180:
        normalized_reason = f"{normalized_reason[:177].rstrip()}..."
    if not normalized_reason:
        normalized_reason = "an internal error"
    if prompt_text:
        return (
            "I couldn’t build the full property package right now. "
            f"Error: {normalized_reason}. Send this once more if you want me to retry."
        )
    return (
        "I couldn’t build the full property package right now. "
        f"Error: {normalized_reason}."
    )


def _compact_telegram_style_hint(value: str, *, max_length: int = 140) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    compact = re.sub(r"\s+", " ", raw).strip(" -_:;,.()[]{}\"'")
    if not compact:
        return ""
    if len(compact) <= max_length:
        return compact
    truncated = compact[:max_length].rstrip(" -_:;,.")
    if " " in truncated:
        truncated = truncated.rsplit(" ", 1)[0]
    return truncated.strip(" -_:;,.")


def _telegram_property_link_diorama_style_hint(text: str) -> str:
    normalized = str(text or "").strip()
    if not normalized:
        return ""
    without_links = re.sub(r"\s+", " ", _URL_RE.sub(" ", normalized)).strip()
    if not without_links:
        return ""

    explicit_patterns = (
        r"(?i)(?:diorama|preview|flythrough|image)\s+(?:style|theme|look|aesthetic|vibe|mood)\s*[:\-]\s*([^.;\n]{4,140})",
        r"(?i)(?:style|theme|aesthetic|look|vibe|mood)\s*[:\-]\s*([^.;\n]{4,140})",
        r"(?i)(?:style|theme|aesthetic|look|vibe|mood)\s+(?:should|must|needs|would|want)\s+be\s+([^.;\n]{4,140})",
        r"(?i)(?:render|design|interior|ambiance|ambience|interiority|diorama)\s+(?:in|as)\s+([^.;\n]{4,140})",
    )
    for pattern in explicit_patterns:
        match = re.search(pattern, without_links)
        if match:
            extracted = _compact_telegram_style_hint(match.group(1), max_length=140)
            if extracted:
                return extracted

    lower_without_links = without_links.lower()
    for token in (
        "scandinavian",
        "scandi",
        "nordic",
        "minimalist",
        "minimal",
        "industrial",
        "boho",
        "bohemian",
        "mid-century",
        "contemporary",
        "modern",
        "vintage",
        "retro",
        "cozy",
        "warm",
        "cool",
        "dark",
        "monochrome",
        "loft",
        "elegant",
        "luxury",
        "earthy",
        "neutral",
    ):
        token_normalized = f" {token} "
        if token_normalized in f" {lower_without_links} ":
            return "scandinavian" if token == "scandi" else token
    return ""


def _telegram_property_link_birthday_party_request(text: str) -> bool:
    normalized = str(text or "").strip()
    if not normalized:
        return False
    without_links = re.sub(r"\s+", " ", _URL_RE.sub(" ", normalized)).strip().lower()
    if not without_links:
        return False
    return any(
        token in without_links
        for token in (
            "birthday party",
            "birthday flythrough",
            "birthday video",
            "geburtstag",
            "geburtstagsfeier",
            "geburtstagsparty",
            "kindergeburtstag",
            "party flythrough",
            "party video",
            "our son",
            "unser sohn",
        )
    )


def _telegram_property_pdf_document_payload(ctx: TelegramTurnContext) -> dict[str, object]:
    payload = dict(ctx.payload or {})
    if str(payload.get("kind") or "").strip().lower() != "document":
        return {}
    metadata = _telegram_document_metadata(ctx)
    filename = str(metadata.get("file_name") or "").strip()
    download_url = str(metadata.get("download_url") or "").strip()
    if not filename.lower().endswith(".pdf") or not download_url:
        return {}
    signal_text = " ".join(
        part
        for part in (
            str(ctx.normalized or "").strip(),
            filename,
            str(metadata.get("caption") or "").strip(),
        )
        if part
    ).lower()
    if not any(
        marker in signal_text
        for marker in (
            "property",
            "propertyquarry",
            "scout",
            "dossier",
            "wohnung",
            "immobil",
            "expose",
            "exposé",
            "grundriss",
            "floorplan",
            "makler",
            "real estate",
        )
    ):
        return {}
    return {
        "kind": "property_pdf_document",
        "source_pdf_url": download_url,
        "source_pdf_filename": filename,
        "caption": str(metadata.get("caption") or ctx.normalized or "").strip(),
        "telegram_file_id": str(metadata.get("file_id") or "").strip(),
    }


def _telegram_document_metadata(ctx: TelegramTurnContext) -> dict[str, object]:
    payload = dict(ctx.payload or {})
    if str(payload.get("kind") or "").strip().lower() != "document":
        return {}
    metadata = dict(payload.get("message_metadata") or {})
    raw = dict(payload.get("raw") or {}) if isinstance(payload.get("raw"), dict) else {}
    raw_message = dict(raw.get("message") or {}) if isinstance(raw.get("message"), dict) else {}
    raw_document = dict(raw_message.get("document") or {}) if isinstance(raw_message.get("document"), dict) else {}
    payload_document = dict(payload.get("document") or {}) if isinstance(payload.get("document"), dict) else {}
    for source in (payload_document, raw_document, payload):
        for key in ("file_id", "file_name", "mime_type", "file_size", "download_url"):
            if metadata.get(key) in {None, ""} and source.get(key) not in {None, ""}:
                metadata[key] = source.get(key)
    if metadata.get("caption") in {None, ""}:
        caption = str(payload.get("caption") or raw_message.get("caption") or ctx.normalized or "").strip()
        if caption:
            metadata["caption"] = caption
    return metadata


def _telegram_audiobook_epub_document_metadata(ctx: TelegramTurnContext) -> dict[str, object]:
    metadata = _telegram_document_metadata(ctx)
    filename = str(metadata.get("file_name") or "").strip()
    mime_type = str(metadata.get("mime_type") or "").strip()
    if not is_epub_document(filename=filename, mime_type=mime_type):
        return {}
    return metadata


def _telegram_audiobook_epub_document_payload(ctx: TelegramTurnContext) -> dict[str, object]:
    if not telegram_epub_skill_enabled():
        return {}
    metadata = _telegram_audiobook_epub_document_metadata(ctx)
    if not metadata:
        return {}
    filename = str(metadata.get("file_name") or "").strip()
    mime_type = str(metadata.get("mime_type") or "").strip()
    download_url = str(metadata.get("download_url") or "").strip()
    file_id = str(metadata.get("file_id") or "").strip()
    if download_url and not is_telegram_epub_download_url_allowed(download_url):
        return {}
    if not download_url and not file_id:
        return {}
    raw_size = metadata.get("file_size")
    file_size = None
    if isinstance(raw_size, int) and raw_size > 0:
        file_size = raw_size
    else:
        with contextlib.suppress(Exception):
            parsed_size = int(str(raw_size or "").strip())
            if parsed_size > 0:
                file_size = parsed_size
    caption = str(metadata.get("caption") or ctx.normalized or "").strip()
    return {
        "kind": "audiobook_epub_document",
        "source_epub_url": download_url,
        "source_epub_filename": filename,
        "source_epub_file_size": file_size,
        "caption": caption,
        "telegram_file_id": str(metadata.get("file_id") or "").strip(),
        "telegram_file_size": metadata.get("file_size"),
        "mime_type": mime_type,
    }


def _telegram_audiobook_epub_turn_decision(ctx: TelegramTurnContext) -> TelegramTurnDecision:
    epub_metadata = _telegram_audiobook_epub_document_metadata(ctx)
    if epub_metadata and not telegram_epub_skill_enabled():
        filename = str(epub_metadata.get("file_name") or "book.epub").strip() or "book.epub"
        return TelegramTurnDecision(
            reply_text=(
                f"I got the ebook `{filename}`, but Telegram audiobook intake is disabled. "
                "Current blocker: telegram_epub_enabled=false."
            )
        )
    epub_payload = _telegram_audiobook_epub_document_payload(ctx)
    if not epub_payload:
        return TelegramTurnDecision()
    filename = str(epub_payload.get("source_epub_filename") or "book.epub").strip() or "book.epub"
    sender_ref = _telegram_audiobook_sender_ref(ctx)
    approval_required = audiobook_access_approval.approval_required(sender_ref=sender_ref, channel="telegram")
    if approval_required and _telegram_audiobook_sender_trusted(ctx, sender_ref=sender_ref):
        approval_required = False
    if approval_required:
        approval_payload = {
            **epub_payload,
            "kind": "audiobook_access_approval_request",
            "source_channel": "telegram",
            "sender_ref": sender_ref,
        }
        return TelegramTurnDecision(
            reply_text=(
                f"Got the ebook `{filename}`. This sender is not on the instant audiobook whitelist, "
                "so I need operator approval before creating the audiobook."
            ),
            schedule_async=True,
            async_text=f"Audiobook approval request: {filename}",
            async_message_id=ctx.current_message_id,
            async_payload=approval_payload,
            suppress_async_ack=True,
            retry_budget=0,
        )
    return TelegramTurnDecision(
        schedule_async=True,
        async_text=f"Audiobook ebook upload: {filename}",
        async_message_id=ctx.current_message_id,
        async_payload=epub_payload,
        suppress_async_ack=True,
        retry_budget=0,
    )


def _telegram_property_pdf_turn_decision(ctx: TelegramTurnContext) -> TelegramTurnDecision:
    pdf_payload = _telegram_property_pdf_document_payload(ctx)
    if not pdf_payload:
        return TelegramTurnDecision()
    return TelegramTurnDecision(reply_text=_telegram_property_boundary_reply_text())


def _telegram_login_walled_property_link(text: str) -> str:
    normalized = str(text or "").strip()
    if not normalized:
        return ""
    for raw in _URL_RE.findall(normalized):
        candidate = str(raw or "").strip().rstrip(").,!?]}>")
        lowered = candidate.lower()
        if any(marker in lowered for marker in ("service.immo/objekt/", "service.immo/login/generate_link")):
            return candidate
    return ""


def _telegram_local_tool_priority(ctx: TelegramTurnContext) -> bool:
    persisted_intent_state = _telegram_recent_persisted_intent_state(
        ctx.container,
        principal_id=ctx.principal_id,
    )
    if _telegram_pocket_candidate_selection(ctx.normalized) > 0:
        return True
    if _telegram_audiobook_text_request_reply_text(ctx.normalized):
        return True
    if _telegram_audio_upload_announcement_reply_text(ctx.normalized):
        return True
    if _telegram_pocket_audio_query_candidate(ctx.normalized):
        return True
    if _telegram_answerly_document_query_candidate(ctx.normalized):
        return True
    if any(marker in ctx.lower for marker in ("google photos", "photo picker", "picture", "photo")):
        return True
    if any(
        phrase in ctx.lower
        for phrase in (
            "next appointment",
            "next meeting",
            "next calendar",
            "my calendar",
            "what is my next appointment",
            "what's my next appointment",
            "focus on tomorrow",
            "what should i focus on tomorrow",
            "what should i focus on",
            "what should i do tomorrow",
            "what is tomorrow like",
        )
    ):
        return True
    if ctx.alpha_words and all(word in {"voice", "message", "done", "finished", "complete", "completed", "ok", "okay"} for word in ctx.alpha_words):
        return True
    return str(persisted_intent_state.get("active_intent") or "").strip().lower() == "admin_followup"


def _telegram_force_async_path(ctx: TelegramTurnContext) -> bool:
    if str(os.getenv("EA_TELEGRAM_STRICT_DECOUPLED_MODE") or "1").strip().lower() in {"0", "false", "no", "off"}:
        return False
    if str(ctx.payload.get("kind") or "").strip().lower() == "callback_query":
        return False
    if not ctx.normalized:
        return False
    if ctx.normalized.startswith("/"):
        return False
    if "http://" in ctx.lower or "https://" in ctx.lower:
        return False
    if _telegram_answerly_document_query_candidate(ctx.normalized):
        return False
    if _safe_math_answer(ctx.normalized):
        return False
    if "audit plan" in ctx.lower:
        return True
    if ctx.lower in {"really", "really?"}:
        return False
    if _telegram_low_signal_followup_cue(ctx.normalized):
        return False
    if _telegram_meta_assistant_reply_text(ctx.normalized):
        return False
    if _telegram_prefers_local_grounded_reply(ctx.normalized):
        return False
    if len(ctx.alpha_words) <= 2 and not any(marker in ctx.lower for marker in ("?", "why", "what", "when", "where", "how", "which")):
        return False
    return True


def _telegram_async_turn_snapshot(
    container: AppContainer,
    *,
    principal_id: str,
    current_message_id: str,
    chat_id: str,
) -> dict[str, str]:
    normalized_message_id = str(current_message_id or "").strip()
    normalized_chat_id = str(chat_id or "").strip()
    if not normalized_message_id:
        return {"status": "unknown", "prompt_text": ""}
    if container.channel_runtime.find_observation_by_dedupe(
        f"{normalized_message_id}:assistant_async_sent",
        principal_id=principal_id,
    ) is not None:
        return {"status": "sent", "prompt_text": ""}
    if container.channel_runtime.find_observation_by_dedupe(
        f"{normalized_message_id}:assistant_async_failed",
        principal_id=principal_id,
    ) is not None:
        for row in container.channel_runtime.list_recent_observations(limit=200, principal_id=principal_id):
            if str(row.channel or "").strip() != "telegram":
                continue
            if str(row.event_type or "").strip() != "telegram.reply_async_failed":
                continue
            if str(getattr(row, "external_id", "") or "").strip() != normalized_message_id:
                continue
            payload = dict(row.payload or {})
            if normalized_chat_id and str(payload.get("chat_id") or "").strip() != normalized_chat_id:
                continue
            return {
                "status": "failed",
                "prompt_text": str(payload.get("prompt_text") or "").strip(),
                "error": str(payload.get("error") or "").strip(),
            }
        return {"status": "failed", "prompt_text": "", "error": ""}
    processing = container.channel_runtime.find_observation_by_dedupe(
        f"{normalized_message_id}:assistant_async_processing",
        principal_id=principal_id,
    )
    if processing is not None:
        payload = dict(processing.payload or {})
        return {"status": "processing", "prompt_text": str(payload.get("prompt_text") or "").strip()}
    for row in container.channel_runtime.list_recent_observations(limit=400, principal_id=principal_id):
        if str(row.channel or "").strip() != "telegram":
            continue
        if str(row.event_type or "").strip() != "telegram.reply_async_started":
            continue
        payload = dict(row.payload or {})
        message_id = str(payload.get("current_message_id") or "").strip()
        if not message_id:
            message_id = str(payload.get("dedupe_key") or "").strip().split(":")[-1].strip()
        if message_id != normalized_message_id:
            continue
        if normalized_chat_id and str(payload.get("chat_id") or "").strip() != normalized_chat_id:
            continue
        return {"status": "queued", "prompt_text": str(payload.get("prompt_text") or "").strip()}
    return {"status": "unknown", "prompt_text": ""}


def _telegram_local_reply_allowed(ctx: TelegramTurnContext, reply_text: str) -> bool:
    if not reply_text:
        return False
    if (
        ctx.is_completion_cue
        and ctx.chat_id
        and _telegram_is_google_photos_picker_block_reply(reply_text)
        and _telegram_recent_messages_include_google_photos_context(
            ctx.container,
            principal_id=ctx.principal_id,
        )
        and _telegram_same_reply_recently_sent(
            ctx.container,
            principal_id=ctx.principal_id,
            chat_id=ctx.chat_id,
            reply_text=reply_text,
        )
    ):
        return False
    if ctx.is_completion_cue and ctx.chat_id and _telegram_same_reply_recently_sent(
        ctx.container,
        principal_id=ctx.principal_id,
        chat_id=ctx.chat_id,
        reply_text=reply_text,
    ):
        return False
    return True


def _telegram_local_turn_decision(ctx: TelegramTurnContext) -> TelegramTurnDecision:
    audiobook_status_reply = _telegram_audiobook_runtime_status_reply_text(
        ctx.normalized,
        chat_id=ctx.chat_id,
        bot_config=dict(ctx.payload.get("_bot_config") or {}),
    )
    if audiobook_status_reply:
        title, inline_buttons = _telegram_latest_audiobook_playback_buttons_for_chat(
            bot_config=dict(ctx.payload.get("_bot_config") or {}),
            chat_id=ctx.chat_id,
        )
        if inline_buttons:
            audiobook_status_reply = (
                f"{audiobook_status_reply}\n\n"
                f"Latest Audiobookshelf delivery awaiting playback confirmation: {title}."
            )
        return TelegramTurnDecision(reply_text=audiobook_status_reply, inline_buttons=inline_buttons or None)
    audiobook_reply = _telegram_audiobook_text_request_reply_text(ctx.normalized)
    if audiobook_reply:
        return TelegramTurnDecision(reply_text=audiobook_reply)
    audio_upload_reply = _telegram_audio_upload_announcement_reply_text(ctx.normalized)
    if audio_upload_reply:
        return TelegramTurnDecision(reply_text=audio_upload_reply)
    pocket_audio_reply = _telegram_pocket_audio_reply_text(
        container=ctx.container,
        principal_id=ctx.principal_id,
        text=ctx.normalized,
    )
    if pocket_audio_reply:
        return TelegramTurnDecision(reply_text=pocket_audio_reply)
    local_assistant_reply = _telegram_local_assistant_reply_text(
        ctx.container,
        principal_id=ctx.principal_id,
        text=ctx.normalized,
    )
    if _telegram_local_reply_allowed(ctx, local_assistant_reply):
        return TelegramTurnDecision(reply_text=local_assistant_reply)
    calendar_reply = _telegram_direct_calendar_reply_text(
        container=ctx.container,
        principal_id=ctx.principal_id,
        text=ctx.normalized,
    )
    if calendar_reply:
        return TelegramTurnDecision(reply_text=calendar_reply)
    return TelegramTurnDecision()


def _telegram_async_assistant_reply_worker(
    *,
    container: AppContainer,
    principal_id: str,
    bot_config: dict[str, object],
    chat_id: str,
    text: str,
    current_message_id: str,
    retry_budget: int = 2,
    async_payload: dict[str, object] | None = None,
) -> None:
    _record_telegram_async_processing(
        container,
        principal_id=principal_id,
        chat_id=chat_id,
        current_message_id=current_message_id,
        prompt_text=text,
    )
    remaining_retries = max(0, int(retry_budget or 0)) + _telegram_property_link_bundle_poll_attempts()
    poll_backoff_seconds = _telegram_property_link_bundle_poll_backoff_seconds()
    payload = dict(async_payload or {})
    if str(payload.get("kind") or "").strip().lower() == "instructional_video":
        payload = _telegram_hydrate_instructional_video_download_url(
            payload,
            bot_token=str(bot_config.get("token") or ""),
        )
        instruction_text = str(payload.get("instruction_text") or text or "")
        video_render_requested = _telegram_instructional_video_prefers_rendered_video(instruction_text)
        prefers_magicfit = _telegram_instructional_video_prefers_magicfit(instruction_text)
        browseract_available = _telegram_browseract_binding_available(container, principal_id=principal_id)
        magicfit_available = _telegram_magicfit_video_fallback_available()
        if not video_render_requested:
            payload = _hydrate_instructional_video_transcript(payload)
        elif str(payload.get("video_download_url") or "").strip():
            payload = _telegram_enrich_payload_with_source_video_references(payload)
        prompt_text = _telegram_instructional_video_prompt(payload)
        reply_text = ""
        used_fallback_only = False
        video_render_result = None
        video_render_error = ""
        if (
            video_render_requested
            and _telegram_local_source_video_fallback_available(payload, instruction_text)
        ):
            try:
                local_delivery = _telegram_render_local_source_video_reply(
                    container=container,
                    principal_id=principal_id,
                    payload=payload,
                    instruction_text=instruction_text,
                )
            except Exception as exc:
                video_render_error = str(exc or "").strip() or "source_video_edit_failed"
                _record_telegram_video_delivery_receipt(
                    container,
                    principal_id=principal_id,
                    chat_id=chat_id,
                    current_message_id=current_message_id,
                    provider="local_source_video_fx",
                    status="failed",
                    payload=payload,
                    error=video_render_error,
                )
            else:
                local_message_ids = _telegram_video_delivery_message_ids(local_delivery)
                if _telegram_video_delivery_sent(local_delivery):
                    reply_text = _telegram_render_success_reply_text()
                    video_render_error = ""
                    _record_telegram_video_delivery_receipt(
                        container,
                        principal_id=principal_id,
                        chat_id=chat_id,
                        current_message_id=current_message_id,
                        provider=str(local_delivery.get("provider") or "local_source_video_fx").strip()
                        or "local_source_video_fx",
                        status="sent",
                        payload=payload,
                        message_ids=local_message_ids,
                    )
                else:
                    video_render_error = _telegram_video_delivery_error(
                        local_delivery,
                        "source_video_edit_delivery_failed",
                    )
                    _record_telegram_video_delivery_receipt(
                        container,
                        principal_id=principal_id,
                        chat_id=chat_id,
                        current_message_id=current_message_id,
                        provider=str(local_delivery.get("provider") or "local_source_video_fx").strip()
                        or "local_source_video_fx",
                        status="failed",
                        payload=payload,
                        message_ids=local_message_ids,
                        error=video_render_error,
                    )
        if not video_render_requested:
            try:
                async_timeout = None
                try:
                    async_timeout = max(
                        float(str(os.getenv("EA_TELEGRAM_ASYNC_REAL_REPLY_TIMEOUT_SECONDS") or "18").strip() or "18"),
                        2.0,
                    )
                except Exception:
                    async_timeout = 18.0
                reply_text = _telegram_real_ea_reply_text(
                    container=container,
                    principal_id=principal_id,
                    text=prompt_text,
                    current_message_id=current_message_id,
                    preferred_onemin_labels=tuple(
                        str(item or "").strip()
                        for item in list(bot_config.get("preferred_onemin_labels") or ())
                        if str(item or "").strip()
                    ),
                    timeout_seconds=async_timeout,
                ).strip()
            except Exception as exc:
                _record_telegram_async_failed(
                    container,
                    principal_id=principal_id,
                    chat_id=chat_id,
                    current_message_id=current_message_id,
                    prompt_text=text,
                    stage="instructional_video_real_reply",
                    error=str(exc),
                )
            if _telegram_is_generic_render_capability_reply(reply_text):
                reply_text = ""
        if (
            video_render_requested
            and prefers_magicfit
            and magicfit_available
        ):
            try:
                magicfit_delivery = _telegram_render_magicfit_video_reply(
                    container=container,
                    principal_id=principal_id,
                    prompt_text=_telegram_instructional_video_render_script(
                        payload=payload,
                        instruction_text=instruction_text,
                        reply_text=reply_text,
                    ),
                    caption=str(payload.get("video_caption") or payload.get("instruction_text") or "Telegram video reply").strip(),
                    instruction_text=instruction_text,
                )
            except Exception as exc:
                video_render_error = str(exc or "").strip() or "magicfit_render_failed"
                _record_telegram_video_delivery_receipt(
                    container,
                    principal_id=principal_id,
                    chat_id=chat_id,
                    current_message_id=current_message_id,
                    provider="magicfit",
                    status="failed",
                    payload=payload,
                    error=video_render_error,
                )
            else:
                magicfit_message_ids = _telegram_video_delivery_message_ids(magicfit_delivery)
                if _telegram_video_delivery_sent(magicfit_delivery):
                    reply_text = _telegram_render_success_reply_text()
                    video_render_error = ""
                    _record_telegram_video_delivery_receipt(
                        container,
                        principal_id=principal_id,
                        chat_id=chat_id,
                        current_message_id=current_message_id,
                        provider=str(magicfit_delivery.get("provider") or "magicfit").strip() or "magicfit",
                        status="sent",
                        payload=payload,
                        message_ids=magicfit_message_ids,
                        sidecar=dict(magicfit_delivery.get("sidecar") or {}),
                    )
                else:
                    video_render_error = _telegram_video_delivery_error(
                        magicfit_delivery,
                        "magicfit_delivery_failed",
                    )
                    _record_telegram_video_delivery_receipt(
                        container,
                        principal_id=principal_id,
                        chat_id=chat_id,
                        current_message_id=current_message_id,
                        provider=str(magicfit_delivery.get("provider") or "magicfit").strip() or "magicfit",
                        status="failed",
                        payload=payload,
                        message_ids=magicfit_message_ids,
                        error=video_render_error,
                        sidecar=dict(magicfit_delivery.get("sidecar") or {}),
                    )
        if (
            video_render_requested
            and not reply_text
            and browseract_available
        ):
            render_script_text = _telegram_instructional_video_render_script(
                payload=payload,
                instruction_text=instruction_text,
                reply_text=reply_text,
            )
            try:
                video_render_result = container.tool_execution.execute_invocation(
                    _telegram_instructional_video_render_request(
                        container=container,
                        principal_id=principal_id,
                        payload=payload,
                        script_text=render_script_text,
                    )
                )
            except Exception as exc:
                video_render_error = str(exc or "").strip() or "instructional_video_render_failed"
                _record_telegram_video_delivery_receipt(
                    container,
                    principal_id=principal_id,
                    chat_id=chat_id,
                    current_message_id=current_message_id,
                    provider="browseract.mootion_movie",
                    status="failed",
                    payload=payload,
                    error=video_render_error,
                )
            else:
                delivery_json = dict(dict(video_render_result.output_json or {}).get("telegram_delivery_json") or {})
                delivery_message_ids = _telegram_video_delivery_message_ids(delivery_json)
                if _telegram_video_delivery_sent(delivery_json):
                    reply_text = _telegram_render_success_reply_text()
                    video_render_error = ""
                    _record_telegram_video_delivery_receipt(
                        container,
                        principal_id=principal_id,
                        chat_id=chat_id,
                        current_message_id=current_message_id,
                        provider=str(delivery_json.get("provider") or "browseract.mootion_movie").strip()
                        or "browseract.mootion_movie",
                        status="sent",
                        payload=payload,
                        message_ids=delivery_message_ids,
                        sidecar=delivery_json,
                    )
                else:
                    video_render_error = _telegram_video_delivery_error(
                        delivery_json,
                        "instructional_video_render_delivery_failed",
                    )
                    _record_telegram_video_delivery_receipt(
                        container,
                        principal_id=principal_id,
                        chat_id=chat_id,
                        current_message_id=current_message_id,
                        provider=str(delivery_json.get("provider") or "browseract.mootion_movie").strip()
                        or "browseract.mootion_movie",
                        status="failed",
                        payload=payload,
                        message_ids=delivery_message_ids,
                        error=video_render_error,
                        sidecar=delivery_json,
                    )
        if (
            video_render_requested
            and video_render_error
            and not reply_text
            and magicfit_available
        ):
            try:
                magicfit_delivery = _telegram_render_magicfit_video_reply(
                    container=container,
                    principal_id=principal_id,
                    prompt_text=_telegram_instructional_video_render_script(
                        payload=payload,
                        instruction_text=instruction_text,
                        reply_text=reply_text,
                    ),
                    caption=str(payload.get("video_caption") or payload.get("instruction_text") or "Telegram video reply").strip(),
                    instruction_text=instruction_text,
                )
            except Exception as exc:
                fallback_error = str(exc or "").strip() or "magicfit_render_failed"
                _record_telegram_video_delivery_receipt(
                    container,
                    principal_id=principal_id,
                    chat_id=chat_id,
                    current_message_id=current_message_id,
                    provider="magicfit",
                    status="failed",
                    payload=payload,
                    error=fallback_error,
                )
                video_render_error = (
                    f"{video_render_error}; magicfit_fallback:"
                    f"{fallback_error}"
                )
            else:
                magicfit_message_ids = _telegram_video_delivery_message_ids(magicfit_delivery)
                if _telegram_video_delivery_sent(magicfit_delivery):
                    reply_text = _telegram_render_success_reply_text()
                    video_render_error = ""
                    _record_telegram_video_delivery_receipt(
                        container,
                        principal_id=principal_id,
                        chat_id=chat_id,
                        current_message_id=current_message_id,
                        provider=str(magicfit_delivery.get("provider") or "magicfit").strip() or "magicfit",
                        status="sent",
                        payload=payload,
                        message_ids=magicfit_message_ids,
                        sidecar=dict(magicfit_delivery.get("sidecar") or {}),
                    )
                else:
                    fallback_error = _telegram_video_delivery_error(
                        magicfit_delivery,
                        "magicfit_delivery_failed",
                    )
                    _record_telegram_video_delivery_receipt(
                        container,
                        principal_id=principal_id,
                        chat_id=chat_id,
                        current_message_id=current_message_id,
                        provider=str(magicfit_delivery.get("provider") or "magicfit").strip() or "magicfit",
                        status="failed",
                        payload=payload,
                        message_ids=magicfit_message_ids,
                        error=fallback_error,
                        sidecar=dict(magicfit_delivery.get("sidecar") or {}),
                    )
                    video_render_error = f"{video_render_error}; magicfit_fallback:{fallback_error}"
        if video_render_requested and not reply_text and not video_render_error:
            if str(payload.get("video_resolve_status") or "").strip().lower() == "failed":
                video_render_error = (
                    "source_video_resolve_failed:"
                    f"{str(payload.get('video_resolve_error_code') or 'unknown').strip() or 'unknown'}"
                )
            elif not str(payload.get("video_download_url") or "").strip():
                video_render_error = "source_video_unavailable"
            else:
                video_render_error = "verified_render_lane_unavailable"
            _record_telegram_video_delivery_receipt(
                container,
                principal_id=principal_id,
                chat_id=chat_id,
                current_message_id=current_message_id,
                provider="telegram_video_delivery_router",
                status="failed",
                payload=payload,
                error=video_render_error,
            )
        if not reply_text:
            if video_render_requested:
                reply_text = _telegram_video_lane_status_reply(
                    payload=payload,
                    instruction_text=instruction_text,
                    video_render_error=video_render_error,
                    prefers_magicfit=prefers_magicfit,
                    browseract_available=browseract_available,
                    magicfit_available=magicfit_available,
                )
                used_fallback_only = True
            else:
                transcript_text = str(payload.get("video_transcript_text") or "").strip()
                if transcript_text:
                    reply_text = (
                        "I captured the video instruction and recovered audio from it, but I do not have a strong final answer yet. "
                        "Send one short follow-up like 'summarize only', 'list action items', or 'what are the risks?'."
                    )
                    used_fallback_only = True
                else:
                    reply_text = (
                        "I captured the video, but I still need a clearer instruction or a spoken transcript from it. "
                        "Send one short follow-up like 'summarize it', 'pull action items', or 'flag risks'."
                    )
                    used_fallback_only = True
        elif video_render_requested and video_render_error:
            reply_text = (
                f"{reply_text}\n\n"
                "I did not manage to send a rendered video reply from this request yet. "
                f"Video lane status: {compact_text(video_render_error, fallback='instructional_video_render_failed', limit=160)}."
            ).strip()
        _telegram_send_and_record_reply(
            container=container,
            principal_id=principal_id,
            bot_config=bot_config,
            chat_id=chat_id,
            dedupe_key="",
            reply_text=reply_text,
            source_text=text,
            async_mode=True,
            current_message_id=current_message_id,
            used_fallback_only=used_fallback_only,
            probe_reply="",
            last_resort_reply="",
        )
        return
    if str(payload.get("kind") or "").strip().lower() == "audiobook_access_approval_request":
        payload = _telegram_hydrate_audiobook_epub_download_url(
            payload,
            bot_token=str(bot_config.get("token") or ""),
        )
        filename = str(payload.get("source_epub_filename") or "book.epub").strip() or "book.epub"
        sender_ref = str(payload.get("sender_ref") or (f"telegram:{chat_id}" if chat_id else "")).strip()
        try:
            record = audiobook_access_approval.find_request_for_source(
                channel="telegram",
                message_id=current_message_id,
                sender_ref=sender_ref,
            )
            if not record:
                root = audiobook_jobs_root()
                staging_dir = root / "_incoming_approval" / datetime.now(ZoneInfo("UTC")).strftime("%Y%m%d")
                staging_dir.mkdir(parents=True, exist_ok=True)
                suffix = Path(filename).suffix or ".epub"
                safe_name = re.sub(r"[^A-Za-z0-9._()\\[\\] -]+", "", Path(filename).name).strip(" .") or "book.epub"
                if suffix and not safe_name.lower().endswith(suffix.lower()):
                    safe_name = f"{safe_name}{suffix}"
                staging_path = staging_dir / f"{uuid.uuid4().hex[:12]}-{safe_name}"
                download_telegram_epub(
                    source_url=str(payload.get("source_epub_url") or "").strip(),
                    target_path=staging_path,
                )
                record = audiobook_access_approval.create_pending_request(
                    channel="telegram",
                    principal_id=principal_id,
                    filename=filename,
                    source_path=staging_path,
                    sender_ref=sender_ref,
                    chat_id=chat_id,
                    message_id=current_message_id,
                    file_size=payload.get("source_epub_file_size") if isinstance(payload.get("source_epub_file_size"), int) else None,
                    mime_type=str(payload.get("mime_type") or "").strip(),
                    caption=str(payload.get("caption") or "").strip(),
                    requester_label=f"Telegram chat {chat_id}" if chat_id else "Telegram requester",
                )
            delivery = audiobook_access_approval.send_telegram_approval_request(
                record=record,
                bot_token=str(bot_config.get("token") or "").strip(),
            )
            reply_text = (
                "I staged the ebook and sent the audiobook approval request to the operator."
                if str(delivery.get("status") or "").strip() == "sent"
                else (
                    "I staged the ebook, but I could not send the operator approval request yet. "
                    f"Current blocker: {compact_text(str(delivery.get('reason') or 'approval_delivery_failed'), fallback='approval_delivery_failed', limit=140)}."
                )
            )
        except Exception as exc:
            reply_text = (
                "I could not stage that ebook for approval yet. "
                f"Current blocker: {compact_text(str(exc), fallback='audiobook_access_approval_failed', limit=160)}."
            )
        if chat_id:
            _telegram_send_and_record_reply(
                container=container,
                principal_id=principal_id,
                bot_config=bot_config,
                chat_id=chat_id,
                dedupe_key="",
                reply_text=reply_text,
                source_text=text,
                async_mode=True,
                current_message_id=current_message_id,
                used_fallback_only=False,
                probe_reply="",
                last_resort_reply="",
            )
        return
    if str(payload.get("kind") or "").strip().lower() == "audiobook_epub_document":
        payload = _telegram_hydrate_audiobook_epub_download_url(
            payload,
            bot_token=str(bot_config.get("token") or ""),
        )
        try:
            job = process_telegram_epub_audiobook_job(
                download_url=str(payload.get("source_epub_url") or "").strip(),
                filename=str(payload.get("source_epub_filename") or "book.epub").strip() or "book.epub",
                file_size=(
                    payload.get("source_epub_file_size")
                    if isinstance(payload.get("source_epub_file_size"), int)
                    else None
                ),
                principal_id=principal_id,
                chat_id=chat_id,
                message_id=current_message_id,
                caption=str(payload.get("caption") or "").strip(),
            )
            sample_receipts = _telegram_send_audiobook_voice_samples(
                bot_config=bot_config,
                chat_id=chat_id,
                job=job,
            ) if chat_id else []
            if sample_receipts:
                job = record_audiobook_voice_sample_delivery(job=job, sample_receipts=sample_receipts)
            reply_text = telegram_epub_reply_text(job)
        except Exception as exc:
            failure_reason = str(exc or "").strip() or "audiobook_epub_job_failed"
            _record_telegram_async_failed(
                container,
                principal_id=principal_id,
                chat_id=chat_id,
                current_message_id=current_message_id,
                prompt_text=text,
                stage="audiobook_epub_job",
                error=failure_reason,
            )
            if chat_id:
                _telegram_send_and_record_reply(
                    container=container,
                    principal_id=principal_id,
                    bot_config=bot_config,
                    chat_id=chat_id,
                    dedupe_key="",
                    reply_text=(
                        "I could not prepare the audiobook source job yet. "
                        f"Current blocker: {compact_text(failure_reason, fallback='audiobook_epub_job_failed', limit=160)}."
                    ),
                    source_text=text,
                    async_mode=True,
                    current_message_id=current_message_id,
                    used_fallback_only=True,
                    probe_reply=_telegram_probe_reply_text(text),
                    last_resort_reply=_telegram_last_resort_reply_text(text),
                )
            return
        _record_telegram_async_sent(
            container,
            principal_id=principal_id,
            chat_id=chat_id,
            current_message_id=current_message_id,
            prompt_text=text,
            reply_text=reply_text,
            used_fallback_only=False,
        )
        if chat_id:
            job, inline_buttons = _telegram_audiobook_playback_acceptance_buttons(
                bot_config=bot_config,
                chat_id=chat_id,
                job=job,
            )
            send_receipt = _telegram_send_and_record_reply_receipt(
                container=container,
                principal_id=principal_id,
                bot_config=bot_config,
                chat_id=chat_id,
                dedupe_key="",
                reply_text=reply_text,
                source_text=text,
                async_mode=True,
                current_message_id=current_message_id,
                used_fallback_only=False,
                probe_reply="",
                last_resort_reply="",
                inline_buttons=inline_buttons,
            )
            _record_audiobook_public_share_reply_delivery(job=job, send_receipt=send_receipt)
        return
    if str(payload.get("kind") or "").strip().lower() == "property_pdf_document":
        try:
            service = build_product_service(container)
            result = service.deliver_telegram_property_pdf_bundle(
                principal_id=principal_id,
                source_pdf_url=str(payload.get("source_pdf_url") or "").strip(),
                source_pdf_filename=str(payload.get("source_pdf_filename") or "").strip(),
                caption=str(payload.get("caption") or "").strip(),
                actor="telegram_property_pdf",
                source_ref=f"telegram:{chat_id}:{current_message_id or hashlib.sha256(str(payload.get('source_pdf_url') or '').encode('utf-8')).hexdigest()[:16]}",
                external_id=str(payload.get("telegram_file_id") or payload.get("source_pdf_url") or "").strip(),
            )
        except Exception as exc:
            failure_reason = str(exc)
            _record_telegram_async_failed(
                container,
                principal_id=principal_id,
                chat_id=chat_id,
                current_message_id=current_message_id,
                prompt_text=text,
                stage="property_pdf_bundle",
                error=failure_reason,
            )
            if chat_id:
                _telegram_send_and_record_reply(
                    container=container,
                    principal_id=principal_id,
                    bot_config=bot_config,
                    chat_id=chat_id,
                    dedupe_key="",
                    reply_text=(
                        "I couldn't build the property PDF packet from that upload right now. "
                        f"Error: {compact_text(failure_reason, fallback='property_pdf_bundle_failed', limit=160)}."
                    ),
                    source_text=text,
                    async_mode=True,
                    current_message_id=current_message_id,
                    used_fallback_only=True,
                    probe_reply=_telegram_probe_reply_text(text),
                    last_resort_reply=_telegram_last_resort_reply_text(text),
                )
            return
        status = str(result.get("status") or "").strip()
        if status == "sent":
            _record_telegram_async_sent(
                container,
                principal_id=principal_id,
                chat_id=chat_id,
                current_message_id=current_message_id,
                prompt_text=text,
                reply_text=f"property_pdf_bundle_sent:{str(result.get('source_pdf_filename') or '').strip()}",
                used_fallback_only=False,
            )
            return
        reason = str(result.get("reason") or result.get("error") or status or "property_pdf_bundle_failed").strip()
        _record_telegram_async_failed(
            container,
            principal_id=principal_id,
            chat_id=chat_id,
            current_message_id=current_message_id,
            prompt_text=text,
            stage="property_pdf_bundle_status",
            error=reason,
        )
        if chat_id:
            _telegram_send_and_record_reply(
                container=container,
                principal_id=principal_id,
                bot_config=bot_config,
                chat_id=chat_id,
                dedupe_key="",
                reply_text=(
                    "I couldn't build the property PDF packet from that upload right now. "
                    f"Current status: {compact_text(reason, fallback='property_pdf_bundle_failed', limit=160)}."
                ),
                source_text=text,
                async_mode=True,
                current_message_id=current_message_id,
                used_fallback_only=True,
                probe_reply=_telegram_probe_reply_text(text),
                last_resort_reply=_telegram_last_resort_reply_text(text),
            )
        return
    property_url = _telegram_supported_property_link(text)
    if property_url:
        style_hint = _telegram_property_link_diorama_style_hint(text)
        birthday_party_request = _telegram_property_link_birthday_party_request(text)
        while True:
            try:
                service = build_product_service(container)
                result = service.deliver_telegram_property_link_bundle(
                    principal_id=principal_id,
                    property_url=property_url,
                    actor="telegram_property_link",
                    source_ref=f"telegram:{chat_id}:{current_message_id or hashlib.sha256(property_url.encode('utf-8')).hexdigest()[:16]}",
                    external_id=property_url,
                    preference_person_id="self",
                    style_hint=style_hint,
                    birthday_party_request=birthday_party_request,
                )
            except Exception as exc:
                failure_reason = str(exc)
                reply_text = _telegram_property_link_bundle_error_reply(failure_reason, prompt_text=text)
                _record_telegram_async_failed(
                    container,
                    principal_id=principal_id,
                    chat_id=chat_id,
                    current_message_id=current_message_id,
                    prompt_text=text,
                    stage="property_link_bundle",
                    error=failure_reason,
                )
                if chat_id:
                    _telegram_send_and_record_reply(
                        container=container,
                        principal_id=principal_id,
                        bot_config=bot_config,
                        chat_id=chat_id,
                        dedupe_key="",
                        reply_text=reply_text,
                        source_text=text,
                        async_mode=True,
                        current_message_id=current_message_id,
                        used_fallback_only=True,
                        probe_reply=_telegram_probe_reply_text(text),
                        last_resort_reply=_telegram_last_resort_reply_text(text),
                    )
                return
            status = str(result.get("status") or "").strip()
            if status == "sent":
                _record_telegram_async_sent(
                    container,
                    principal_id=principal_id,
                    chat_id=chat_id,
                    current_message_id=current_message_id,
                    prompt_text=text,
                    reply_text=f"property_link_bundle_sent:{property_url}",
                    used_fallback_only=False,
                )
                return
            pending_reasons = [str(item or "").strip() for item in list(result.get("pending_reasons") or []) if str(item or "").strip()]
            if status in {"pending", "failed", "blocked"}:
                failure_reason = str(result.get("reason") or result.get("error") or "").strip()
                if status == "failed" and not pending_reasons and failure_reason:
                    pending_reasons = [failure_reason]
                if status == "blocked":
                    blocked_reason = str(result.get("blocked_reason") or failure_reason or "").strip()
                    if blocked_reason:
                        normalized_blocked_reason = blocked_reason.replace("_", " ").strip()
                        if normalized_blocked_reason and not any(
                            str(item or "").strip() == normalized_blocked_reason for item in pending_reasons
                        ):
                            if "media missing" in normalized_blocked_reason:
                                pending_reasons.append(f"3D tour missing ({normalized_blocked_reason})")
                            else:
                                pending_reasons.append(normalized_blocked_reason)
                can_retry = False
                if status in {"pending", "blocked"}:
                    can_retry = all(
                        _telegram_property_link_bundle_retryable_pending_reason(item) for item in pending_reasons
                    ) if pending_reasons else False
                else:
                    can_retry = all(
                        _telegram_property_link_bundle_retryable_failed_reason(item) for item in pending_reasons
                    ) if pending_reasons else False
                upgrade_hint = ""
                for reason in pending_reasons:
                    upgrade_hint = _telegram_property_tour_upgrade_hint(reason)
                    if upgrade_hint:
                        break
                if can_retry and remaining_retries > 0:
                    remaining_retries -= 1
                    if poll_backoff_seconds > 0:
                        time.sleep(poll_backoff_seconds)
                    continue
                if pending_reasons:
                    reason_text = "; ".join(pending_reasons)
                else:
                    reason_text = str(result.get("status") or result.get("reason") or "property_link_bundle_processing")
                if upgrade_hint:
                    reason_text = f"{reason_text}. {upgrade_hint}"
                reply_text = (
                    "I still can’t build the full property package right now. "
                    f"Current status: {reason_text}. "
                    "I’ll try again if you send this once more."
                )
                _record_telegram_async_failed(
                    container,
                    principal_id=principal_id,
                    chat_id=chat_id,
                    current_message_id=current_message_id,
                    prompt_text=text,
                    stage="property_link_bundle_status",
                    error=f"{status}:{reason_text}",
                )
                _telegram_send_and_record_reply(
                    container=container,
                    principal_id=principal_id,
                    bot_config=bot_config,
                    chat_id=chat_id,
                    dedupe_key="",
                    reply_text=reply_text,
                    source_text=text,
                    async_mode=True,
                    current_message_id=current_message_id,
                    used_fallback_only=True,
                    probe_reply=_telegram_probe_reply_text(text),
                    last_resort_reply=_telegram_last_resort_reply_text(text),
                )
                return
            _record_telegram_async_failed(
                container,
                principal_id=principal_id,
                chat_id=chat_id,
                current_message_id=current_message_id,
                prompt_text=text,
                stage="property_link_bundle_status",
                error=str(result.get("reason") or result.get("status") or "property_link_bundle_failed"),
            )
            break
    probe_reply = _telegram_probe_reply_text(text)
    last_resort_reply = _telegram_last_resort_reply_text(text)
    reply_text = _telegram_pocket_audio_reply_text(
        container=container,
        principal_id=principal_id,
        text=text,
    ).strip()
    used_fallback_only = False
    if not reply_text and not probe_reply:
        try:
            async_timeout = None
            try:
                async_timeout = max(
                    float(str(os.getenv("EA_TELEGRAM_ASYNC_REAL_REPLY_TIMEOUT_SECONDS") or "18").strip() or "18"),
                    2.0,
                )
            except Exception:
                async_timeout = 18.0
            reply_text = _telegram_real_ea_reply_text(
                container=container,
                principal_id=principal_id,
                text=text,
                current_message_id=current_message_id,
                preferred_onemin_labels=tuple(
                    str(item or "").strip()
                    for item in list(bot_config.get("preferred_onemin_labels") or ())
                    if str(item or "").strip()
                ),
                timeout_seconds=async_timeout,
            ).strip()
        except Exception as exc:
            _record_telegram_async_failed(
                container,
                principal_id=principal_id,
                chat_id=chat_id,
                current_message_id=current_message_id,
                prompt_text=text,
                stage="real_reply",
                error=str(exc),
            )
            reply_text = ""
    if not reply_text:
        reply_text = (
            probe_reply
            or
            _telegram_local_assistant_reply_text(container, principal_id=principal_id, text=text).strip()
            or _telegram_general_reply_text(container=container, principal_id=principal_id, text=text).strip()
            or last_resort_reply
        )
        used_fallback_only = bool(reply_text)
    if not reply_text:
        _record_telegram_async_failed(
            container,
            principal_id=principal_id,
            chat_id=chat_id,
            current_message_id=current_message_id,
            prompt_text=text,
            stage="empty_reply",
            error="no_reply_text",
        )
        return
    if _telegram_should_suppress_async_fallback_reply(
        reply_text=reply_text,
        used_fallback_only=used_fallback_only,
        probe_reply=probe_reply,
        last_resort_reply=last_resort_reply,
    ):
        _record_telegram_async_failed(
            container,
            principal_id=principal_id,
            chat_id=chat_id,
            current_message_id=current_message_id,
            prompt_text=text,
            stage="fallback_suppressed_no_user_action",
            error="telegram_action_required_only",
        )
        return
    _telegram_send_and_record_reply(
        container=container,
        principal_id=principal_id,
        bot_config=bot_config,
        chat_id=chat_id,
        dedupe_key="",
        reply_text=reply_text,
        source_text=text,
        async_mode=True,
        current_message_id=current_message_id,
        used_fallback_only=used_fallback_only,
        probe_reply=probe_reply,
        last_resort_reply=last_resort_reply,
    )


def _telegram_processing_ack_buttons(
    *,
    bot_config: dict[str, object],
    current_message_id: str,
    chat_id: str,
) -> list[list[tuple[str, str]]]:
    status_packet = _telegram_encode_callback_data(
        bot_config=bot_config,
        action="status",
        current_message_id=current_message_id,
        chat_id=chat_id,
    )
    retry_packet = _telegram_encode_callback_data(
        bot_config=bot_config,
        action="retry",
        current_message_id=current_message_id,
        chat_id=chat_id,
    )
    help_packet = _telegram_encode_callback_data(
        bot_config=bot_config,
        action="help",
        current_message_id=current_message_id,
        chat_id=chat_id,
    )
    buttons: list[list[tuple[str, str]]] = []
    first_row = [(label, value) for label, value in (("Status", status_packet), ("Retry", retry_packet)) if value]
    second_row = [(label, value) for label, value in (("Help", help_packet),) if value]
    if first_row:
        buttons.append(first_row)
    if second_row:
        buttons.append(second_row)
    return buttons


def _telegram_processing_ack_buttons_payload(
    *,
    bot_config: dict[str, object],
    current_message_id: str,
    chat_id: str,
) -> list[list[str]]:
    return [
        [value for _, value in row]
        for row in _telegram_processing_ack_buttons(
            bot_config=bot_config,
            current_message_id=current_message_id,
            chat_id=chat_id,
        )
    ]


def _telegram_processing_ack_text(text: str, *, render_priority: str = "") -> str:
    normalized = str(text or "").strip()
    base = "Saved. EA is processing this asynchronously now."
    if "?" in normalized or any(marker in normalized.lower() for marker in ("what", "why", "how", "where", "when", "which")):
        return "Working on it. EA saved your request and is processing it asynchronously."
    return base


def _telegram_send_processing_ack(
    *,
    container: AppContainer,
    principal_id: str,
    bot_config: dict[str, object],
    chat_id: str,
    dedupe_key: str,
    source_text: str,
    current_message_id: str,
    render_priority: str = "",
) -> bool:
    marker = f"{str(dedupe_key or '').strip()}:processing_ack_sent" if str(dedupe_key or '').strip() else ""
    if marker and container.channel_runtime.find_observation_by_dedupe(marker, principal_id=principal_id) is not None:
        return False
    buttons = _telegram_processing_ack_buttons(
        bot_config=bot_config,
        current_message_id=current_message_id,
        chat_id=chat_id,
    )
    receipt = _telegram_send_message(
        bot_token=str(bot_config.get("token") or "").strip(),
        chat_id=chat_id,
        text=_telegram_processing_ack_text(source_text, render_priority=render_priority),
        inline_buttons=buttons,
    )
    if not bool(receipt.get("ok")):
        return False
    container.channel_runtime.ingest_observation(
        principal_id=principal_id,
        channel="telegram",
        event_type="telegram.processing_ack_sent",
        payload={
            "chat_id": chat_id,
            "reply_text": _telegram_processing_ack_text(source_text, render_priority=render_priority),
            "source_text": source_text,
            "buttons": _telegram_processing_ack_buttons_payload(
                bot_config=bot_config,
                current_message_id=current_message_id,
                chat_id=chat_id,
            ),
            "message_id": str(dict(receipt.get("result") or {}).get("message_id") or "").strip(),
            "current_message_id": str(current_message_id or "").strip(),
        },
        source_id=f"telegram:{chat_id}" if chat_id else "telegram",
        external_id=str(dict(receipt.get("result") or {}).get("message_id") or "").strip(),
        dedupe_key=marker,
    )
    return True


def _telegram_schedule_async_assistant_reply(
    *,
    container: AppContainer,
    principal_id: str,
    bot_config: dict[str, object],
    chat_id: str,
    dedupe_key: str,
    text: str,
    current_message_id: str,
    retry_budget: int = 2,
    async_payload: dict[str, object] | None = None,
) -> None:
    if not chat_id or not dedupe_key:
        return
    if _telegram_async_already_started(container, principal_id=principal_id, dedupe_key=dedupe_key):
        return
    property_url = _telegram_supported_property_link(text)
    render_priority = _telegram_property_render_priority(container=container, principal_id=principal_id) if property_url else "free"
    render_executor = _TELEGRAM_PAID_RENDER_EXECUTOR if render_priority == "paid" else _TELEGRAM_FREE_RENDER_EXECUTOR
    _record_telegram_async_started(
        container,
        principal_id=principal_id,
        chat_id=chat_id,
        dedupe_key=dedupe_key,
        prompt_text=text,
        current_message_id=current_message_id,
        bot_key=str(bot_config.get("bot_key") or "").strip(),
        bot_handle=str(bot_config.get("handle") or "").strip(),
        async_payload=dict(async_payload or {}),
    )
    if _telegram_inline_async_accelerator_enabled():
        if not property_url:
            render_executor = _TELEGRAM_ASYNC_EXECUTOR
        render_executor.submit(
            _telegram_async_assistant_reply_worker,
            container=container,
            principal_id=principal_id,
            bot_config=dict(bot_config),
            chat_id=chat_id,
            text=text,
            current_message_id=current_message_id,
            retry_budget=retry_budget,
            async_payload=dict(async_payload or {}),
        )


def _telegram_inline_proactive_network_fetch_enabled() -> bool:
    raw = str(os.getenv("EA_PROACTIVE_OODA_SAFE_WORK_NETWORK_FETCH_ENABLED") or "1").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _telegram_inline_proactive_network_fetch_limit() -> int:
    raw = str(os.getenv("EA_PROACTIVE_OODA_SAFE_WORK_NETWORK_FETCH_LIMIT") or "4").strip()
    try:
        return max(int(raw or "4"), 1)
    except Exception:
        return 4


def _telegram_inline_proactive_network_fetch_timeout_seconds() -> int:
    raw = str(os.getenv("EA_PROACTIVE_OODA_SAFE_WORK_NETWORK_FETCH_TIMEOUT_SECONDS") or "8").strip()
    try:
        return max(int(raw or "8"), 1)
    except Exception:
        return 8


def _telegram_inline_proactive_stage_packet_dir() -> Path:
    configured = str(os.getenv("EA_PROACTIVE_OODA_STAGE_PACKET_DIR") or "").strip()
    if configured:
        path = Path(configured)
        return path if path.is_absolute() else _EA_ROOT / path
    artifact_dir = default_proactive_ooda_artifact_dir(root=_EA_ROOT, preferred=_EA_ROOT / "state")
    return artifact_dir / "proactive_ooda_stage_packets"


def _telegram_inline_proactive_safe_work_result_dir(stage_packet_dir: Path) -> Path:
    configured = str(os.getenv("EA_PROACTIVE_OODA_SAFE_WORK_RESULT_DIR") or "").strip()
    if configured:
        path = Path(configured)
        return path if path.is_absolute() else _EA_ROOT / path
    return default_safe_work_result_dir(stage_packet_dir)


def _load_json_object(path: str | Path) -> dict[str, object]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _telegram_inline_proactive_recommended_preview(result: dict[str, object]) -> tuple[str, str, str]:
    recommended = dict(result.get("recommended_option_or_draft") or {})
    kind = str(recommended.get("kind") or "").strip()
    value = recommended.get("value")
    if kind == "draft_text":
        preview = compact_text(str(value or "").strip(), fallback="", limit=220)
        return "Draft preview", preview, ""
    if isinstance(value, dict):
        label = compact_text(
            str(value.get("label") or value.get("name") or value.get("title") or "").strip(),
            fallback="Recommended option",
            limit=120,
        )
        detail = compact_text(
            str(value.get("snippet") or value.get("reason") or value.get("summary") or "").strip(),
            fallback="",
            limit=180,
        )
        url = compact_text(str(value.get("url") or value.get("href") or "").strip(), fallback="", limit=220)
        return label, detail, url
    detail = compact_text(str(value or "").strip(), fallback="", limit=180)
    return ("Recommended option" if detail else "", detail, "")


def _telegram_inline_proactive_stage_reply_text(
    *,
    safe_work_result: dict[str, object],
    approval_required: bool,
) -> str:
    lines = ["Saved. I staged this as a reversible next step."]
    summary = compact_text(str(safe_work_result.get("summary") or "").strip(), fallback="", limit=260)
    status = str(safe_work_result.get("status") or "").strip().lower()
    if summary:
        lines.append(summary)
    preview_label, preview_detail, preview_url = _telegram_inline_proactive_recommended_preview(safe_work_result)
    if preview_label and preview_detail:
        lines.append(f"{preview_label}: {preview_detail}")
    elif preview_detail:
        lines.append(preview_detail)
    staged_action_url = compact_text(str(safe_work_result.get("staged_action_url") or preview_url).strip(), fallback="", limit=220)
    if staged_action_url:
        lines.append(f"Candidate: {staged_action_url}")
    lines.append(f"Queue: {ea_public_app_base_url().rstrip('/')}/app/queue")
    if approval_required and status == "staged_for_user_decision":
        approval_prompt = compact_text(
            str(safe_work_result.get("approval_prompt") or "").strip(),
            fallback="No send, booking, purchase, or commitment will happen without explicit approval.",
            limit=220,
        )
        lines.append(approval_prompt)
    return "\n".join(line for line in lines if line).strip()


_TELEGRAM_REFERENTIAL_DRAFT_MARKERS = (
    "if you find one",
    "when you find one",
    "when you found one",
    "wenn du einen gefunden hast",
    "wenn du einen findest",
    "wenn du eine gefunden hast",
    "wenn du eine findest",
)


def _telegram_referential_draft_followup(text: str) -> bool:
    lowered = " ".join(str(text or "").strip().lower().split())
    return any(marker in lowered for marker in _TELEGRAM_REFERENTIAL_DRAFT_MARKERS)


def _telegram_contextual_proactive_request_text(
    *,
    container: AppContainer,
    principal_id: str,
    chat_id: str,
    current_message_id: str,
    message_payload: dict[str, object],
) -> str:
    request_text = str(message_payload.get("analysis_summary") or message_payload.get("text") or "").strip()
    if not _telegram_referential_draft_followup(request_text):
        return request_text
    prior_request = _telegram_recent_discovery_request_text(
        container=container,
        principal_id=principal_id,
        chat_id=chat_id,
        current_message_id=current_message_id,
    )
    if not prior_request:
        return request_text
    separator = "" if prior_request.endswith((".", "!", "?")) else "."
    combined = f"{prior_request}{separator} {request_text}".strip()
    return combined if len(combined) > len(request_text) else request_text


def _telegram_recent_discovery_request_text(
    *,
    container: AppContainer,
    principal_id: str,
    chat_id: str,
    current_message_id: str,
) -> str:
    rows = list(container.channel_runtime.list_recent_observations(limit=40, principal_id=principal_id))
    rows.sort(key=lambda row: (str(row.created_at or ""), str(row.observation_id or "")), reverse=True)
    normalized_chat_id = str(chat_id or "").strip()
    normalized_current_message_id = str(current_message_id or "").strip()
    for row in rows:
        if str(row.channel or "").strip().lower() != "telegram":
            continue
        if str(row.event_type or "").strip().lower() != "telegram.message":
            continue
        if normalized_current_message_id and str(row.external_id or "").strip() == normalized_current_message_id:
            continue
        if normalized_chat_id and str(row.source_id or "").strip() not in {f"telegram:{normalized_chat_id}", "telegram"}:
            continue
        payload = dict(row.payload or {})
        prior_text = str(payload.get("text") or "").strip()
        if not prior_text:
            continue
        prior_signal = observation_row_to_signal(
            observation_id=str(getattr(row, "observation_id", "") or "").strip(),
            principal_id=principal_id,
            channel=str(getattr(row, "channel", "") or "telegram").strip(),
            event_type=str(getattr(row, "event_type", "") or "telegram.message").strip(),
            payload=payload,
            created_at=str(getattr(row, "created_at", "") or "").strip(),
            source_id=str(getattr(row, "source_id", "") or "").strip(),
            external_id=str(getattr(row, "external_id", "") or "").strip(),
            dedupe_key=str(getattr(row, "dedupe_key", "") or "").strip(),
        )
        if prior_signal is None:
            continue
        ooda_loop = dict(dict(prior_signal.payload or {}).get("ooda_loop") or {})
        stage = dict(dict(ooda_loop.get("act") or {}).get("stage") or {})
        work_type = str(stage.get("work_type") or "").strip()
        draft_mode = str(stage.get("draft_mode") or "").strip()
        if work_type in {"research", "compare_options"}:
            return prior_text
        if work_type == "draft" and draft_mode == "research_backed_inquiry":
            return prior_text
    return ""


def _telegram_inline_proactive_execution_reply_text(
    *,
    safe_work_result: dict[str, object],
    execution: dict[str, object],
    principal_id: str,
) -> str:
    action = str(execution.get("action") or "").strip().lower()
    status = str(execution.get("status") or "").strip().lower()
    if status == "executed" and action == "save_gmail_draft":
        lines = ["Saved. I created the Gmail draft."]
        summary = compact_text(str(safe_work_result.get("summary") or "").strip(), fallback="", limit=220)
        if summary:
            lines.append(summary)
        audit = dict(safe_work_result.get("audit") or {})
        if str(audit.get("status") or "").strip().lower() == "review":
            issues = [dict(item) for item in list(audit.get("issues") or []) if isinstance(item, dict)]
            if issues:
                detail = compact_text(str(issues[0].get("detail") or "").strip(), fallback="", limit=180)
                if detail:
                    lines.append(f"Audit: {detail}")
        draft_folder_url = str(execution.get("draft_folder_url") or "").strip()
        if draft_folder_url:
            lines.append(f"Open Drafts: {draft_folder_url}")
        gmail_draft_id = str(execution.get("gmail_draft_id") or "").strip()
        if gmail_draft_id:
            lines.append(f"Draft ID: {gmail_draft_id}")
        return "\n".join(lines)
    if status == "blocked":
        lines = ["I prepared the draft, but I could not save it in Gmail yet."]
        reason = _telegram_inline_proactive_execution_reason(execution=execution)
        if reason:
            lines.append(f"Current blocker: {reason}.")
        connected_google_email = str(execution.get("google_account_email") or "").strip().lower()
        expected_google_email = str(execution.get("expected_google_account_email") or _principal_email_hint(principal_id)).strip().lower()
        if connected_google_email and expected_google_email and connected_google_email != expected_google_email:
            lines.append(f"Connected Google account: {connected_google_email}")
            lines.append(f"Expected inbox account: {expected_google_email}")
        elif connected_google_email:
            lines.append(f"Connected Google account: {connected_google_email}")
        next_action = dict(execution.get("next_action_surface") or {})
        href = str(next_action.get("href") or "").strip()
        if href:
            lines.append(f"Next action: {href}")
        return "\n".join(lines)
    return _telegram_inline_proactive_stage_reply_text(
        safe_work_result=safe_work_result,
        approval_required=False,
    )


def _telegram_inline_proactive_execution_reason(*, execution: dict[str, object]) -> str:
    reason = str(execution.get("reason") or "").strip().lower()
    if reason == "audit_review_required":
        return "the staged draft needs review before EA auto-saves it"
    if reason == "approved_draft_recipient_missing":
        return "I could not resolve a recipient from the request context"
    if reason == "approved_draft_body_missing":
        return "the draft body is still empty"
    if reason == "google_oauth_binding_not_found":
        return "no Google workspace is connected for this tenant"
    if reason in {"google_oauth_invalid_grant", "google_oauth_refresh_failed"}:
        return "the connected Google account needs reauthorization"
    if reason == "google_oauth_account_mismatch":
        return "the connected Google account does not match the tenant inbox"
    if reason == "google_gmail_draft_scope_missing":
        return "the connected Google account does not have Gmail draft scope"
    return compact_text(reason, fallback="", limit=160)


def _telegram_inline_proactive_has_reviewable_material(
    *,
    safe_work_result: dict[str, object],
    execution_result: dict[str, object],
) -> bool:
    execution_status = str(execution_result.get("status") or "").strip().lower()
    execution_action = str(execution_result.get("action") or "").strip().lower()
    if execution_status == "blocked":
        return True
    if execution_status == "executed":
        if execution_action == "save_gmail_draft":
            return bool(
                str(execution_result.get("draft_folder_url") or "").strip()
                or str(execution_result.get("gmail_draft_id") or "").strip()
            )
        return True

    status = str(safe_work_result.get("status") or "").strip().lower()
    if status in {"blocked_human_handoff_required", "blocked_needs_browser_action"}:
        return True

    browser_action_receipt = dict(safe_work_result.get("browser_action_receipt") or {})
    if bool(browser_action_receipt.get("user_action_required")):
        return True

    if str(safe_work_result.get("staged_action_url") or "").strip():
        return True

    shortlist = [item for item in list(safe_work_result.get("shortlist") or []) if isinstance(item, dict)]
    comparison_table = [item for item in list(safe_work_result.get("comparison_table") or []) if isinstance(item, dict)]
    if shortlist or comparison_table:
        return True

    recommended = dict(safe_work_result.get("recommended_option_or_draft") or {})
    kind = str(recommended.get("kind") or "").strip().lower()
    value = recommended.get("value")
    if kind == "research_query":
        return False
    if kind == "draft_text":
        return bool(str(value or "").strip())
    if kind in {"booking_candidate", "reversible_cart_or_link", "shortlist_candidate"}:
        return bool(value)
    return False


def _telegram_inline_proactive_should_absorb_generic_task(
    *,
    safe_work_result: dict[str, object],
    execution_result: dict[str, object],
) -> bool:
    if _telegram_inline_proactive_has_reviewable_material(
        safe_work_result=safe_work_result,
        execution_result=execution_result,
    ):
        return False
    work_type = str(safe_work_result.get("work_type") or "").strip().lower()
    status = str(safe_work_result.get("status") or "").strip().lower()
    if status in {
        "blocked_human_handoff_required",
        "blocked_needs_browser_action",
        "blocked_needs_research_input",
    }:
        return work_type in {"draft", "research", "prepare_booking_candidate", "prepare_cart_or_link"}
    recommended = dict(safe_work_result.get("recommended_option_or_draft") or {})
    kind = str(recommended.get("kind") or "").strip().lower()
    return work_type in {"draft", "research"} and kind in {"", "research_query"}


def _telegram_inline_proactive_user_action_required(
    *,
    safe_work_result: dict[str, object],
    execution_result: dict[str, object],
    approval_request: dict[str, object],
    reply_text: str,
) -> bool:
    if telegram_ooda_text_is_internal_noise(reply_text, safe_work_result.get("summary"), safe_work_result.get("approval_prompt")):
        return False
    execution_status = str(execution_result.get("status") or "").strip().lower()
    execution_action = str(execution_result.get("action") or "").strip().lower()
    if execution_status == "blocked":
        return True
    if execution_status == "executed" and execution_action == "save_gmail_draft":
        return False
    if not _telegram_inline_proactive_has_reviewable_material(
        safe_work_result=safe_work_result,
        execution_result=execution_result,
    ):
        return False
    status = str(safe_work_result.get("status") or "").strip().lower()
    if status == "blocked_needs_research_input":
        lowered = " ".join(str(reply_text or "").strip().lower().split())
        return any(marker in lowered for marker in ("next action:", "current blocker:", "open drafts:"))
    if approval_request_needs_telegram_user_action(approval_request):
        return True
    lowered = " ".join(str(reply_text or "").strip().lower().split())
    return any(marker in lowered for marker in ("next action:", "current blocker:", "open drafts:"))


def _principal_email_hint(principal_id: str) -> str:
    normalized = str(principal_id or "").strip().lower()
    if normalized.startswith("cf-email:"):
        return normalized.split(":", 1)[1].strip().lower()
    return ""


def _telegram_reply_is_generic_task_fallback(reply_text: str) -> bool:
    lowered = " ".join(str(reply_text or "").strip().lower().split())
    if not lowered:
        return True
    return lowered.startswith(
        (
            "i do not see ",
            "i do not have ",
            "let me check that and get back to you here.",
            "working on it.",
            "saved. ea is processing this asynchronously now.",
            "i am still working on that last message.",
        )
    )


def _telegram_async_reply_is_generic_task(async_payload: dict[str, object] | None = None) -> bool:
    payload = dict(async_payload or {})
    kind = " ".join(str(payload.get("kind") or "").strip().lower().split())
    return kind in {"", "generic_task"}


def _telegram_stage_inline_proactive_task(
    *,
    container: AppContainer,
    principal_id: str,
    bot_config: dict[str, object],
    chat_id: str,
    event,
    dedupe_key: str,
    message_payload: dict[str, object],
) -> dict[str, object]:
    if str(getattr(event, "event_type", "") or "").strip().lower() != "telegram.message":
        return {}
    message_payload = dict(message_payload or {})
    kind = str(message_payload.get("kind") or "").strip().lower()
    if kind not in {"", "text", "voice"}:
        return {}
    text = str(message_payload.get("text") or "").strip()
    if not text or _telegram_supported_property_link(text):
        return {}
    contextual_request = _telegram_contextual_proactive_request_text(
        container=container,
        principal_id=principal_id,
        chat_id=chat_id,
        current_message_id=str(message_payload.get("message_id") or getattr(event, "external_id", "") or "").strip(),
        message_payload=message_payload,
    )
    if contextual_request and len(contextual_request) > len(str(message_payload.get("analysis_summary") or "").strip()):
        message_payload["analysis_summary"] = contextual_request
    signal = observation_row_to_signal(
        observation_id=str(getattr(event, "observation_id", "") or "").strip(),
        principal_id=principal_id,
        channel=str(getattr(event, "channel", "") or "telegram").strip(),
        event_type=str(getattr(event, "event_type", "") or "telegram.message").strip(),
        payload=message_payload,
        created_at=str(getattr(event, "created_at", "") or "").strip(),
        source_id=str(getattr(event, "source_id", "") or "").strip(),
        external_id=str(getattr(event, "external_id", "") or "").strip(),
        dedupe_key=dedupe_key,
    )
    if signal is None:
        return {}
    signal_payload = dict(signal.payload or {})
    ooda_loop = dict(signal_payload.get("ooda_loop") or {})
    act_section = dict(ooda_loop.get("act") or {})
    stage_section = dict(act_section.get("stage") or {})
    if not stage_section:
        return {}

    office_signal_result: dict[str, object] = {}
    try:
        office_signal_result = build_product_service(container).ingest_office_signal(
            principal_id=principal_id,
            signal_type="telegram_message",
            channel="telegram",
            title=str(signal.title or "").strip(),
            summary=str(signal.summary or "").strip(),
            text=text,
            source_ref=str(getattr(event, "source_id", "") or "").strip() or f"telegram:{chat_id}:{message_payload.get('message_id') or ''}",
            external_id=str(getattr(event, "external_id", "") or "").strip(),
            counterparty=str(signal.counterparty or "Telegram").strip(),
            payload={
                "chat_id": str(chat_id or "").strip(),
                "message_id": str(message_payload.get("message_id") or "").strip(),
                "dedupe_key": dedupe_key,
                "kind": kind or "text",
            },
            actor="telegram_inline_proactive_stage",
        )
    except Exception:
        office_signal_result = {}

    digest = ProactiveOodaService(max_items=1).build_digest(
        principal_id=principal_id,
        signals=(signal,),
        already_notified_refs=set(),
    )
    digest = ground_digest_for_principal(
        digest,
        principal_id=principal_id,
        memory_runtime=container.memory_runtime,
        preference_profiles=container.preference_profiles,
    )
    if not digest.items:
        return {}

    stage_packet_dir = _telegram_inline_proactive_stage_packet_dir()
    safe_work_result_dir = _telegram_inline_proactive_safe_work_result_dir(stage_packet_dir)
    stage_result = persist_stage_packets(digest=digest, output_dir=stage_packet_dir)
    packet_paths = tuple(stage_result.paths)
    packet_refs = tuple(stage_result.packet_refs)
    if packet_paths:
        packet = _load_json_object(packet_paths[0])
    else:
        built_packets = build_stage_packets(digest)
        packet = dict(built_packets[0]) if built_packets else {}
        packet_ref = str(packet.get("packet_ref") or "").strip()
        if packet_ref and not packet_refs:
            packet_refs = (packet_ref,)
    if not packet:
        return {}

    safe_work_write = persist_safe_work_results_from_paths(
        stage_packet_paths=packet_paths or (),
        result_dir=safe_work_result_dir,
        network_fetch_enabled=_telegram_inline_proactive_network_fetch_enabled(),
        network_fetch_limit=_telegram_inline_proactive_network_fetch_limit(),
        network_fetch_timeout_seconds=_telegram_inline_proactive_network_fetch_timeout_seconds(),
    ) if packet_paths else None
    safe_work_paths = tuple(getattr(safe_work_write, "paths", ()) or ())
    safe_work_refs = tuple(getattr(safe_work_write, "result_refs", ()) or ())
    if safe_work_paths:
        safe_work_result = _load_json_object(safe_work_paths[0])
    else:
        safe_work_result = build_safe_work_result(
            packet,
            network_fetch_enabled=_telegram_inline_proactive_network_fetch_enabled(),
            network_fetch_limit=_telegram_inline_proactive_network_fetch_limit(),
            network_fetch_timeout_seconds=_telegram_inline_proactive_network_fetch_timeout_seconds(),
        )
        result_ref = str(safe_work_result.get("result_ref") or "").strip()
        if result_ref and not safe_work_refs:
            safe_work_refs = (result_ref,)

    approval_required = bool(dict(packet.get("approval") or {}).get("required"))
    stage_payload = dict(dict(packet.get("stage") or {}).get("payload") or {})
    auto_execute_action = str(stage_payload.get("auto_execute_action") or "").strip().lower()
    execution_result: dict[str, object] = {}
    if not approval_required and auto_execute_action == "save_gmail_draft" and packet_refs and safe_work_refs:
        execution_result = execute_proactive_ooda_action(
            container=container,
            principal_id=principal_id,
            packet_ref=packet_refs[0],
            staged_artifact_ref=safe_work_refs[0],
            root=_EA_ROOT,
            state_path=os.getenv("EA_PROACTIVE_OODA_STATE_PATH", "state/proactive_ooda_notified.json"),
            receipt_path=os.getenv("EA_PROACTIVE_OODA_RECEIPT_PATH", ""),
            stage_packet_dir=stage_packet_dir,
            safe_work_result_dir=safe_work_result_dir,
        )
        reply_text = _telegram_inline_proactive_execution_reply_text(
            safe_work_result=safe_work_result,
            execution=execution_result,
            principal_id=principal_id,
        )
    else:
        reply_text = _telegram_inline_proactive_stage_reply_text(
            safe_work_result=safe_work_result,
            approval_required=approval_required,
        )
    approval_request = {
        "packet_ref": packet_refs[0] if packet_refs else "",
        "staged_artifact_ref": safe_work_refs[0] if safe_work_refs else "",
        "approval_prompt": str(safe_work_result.get("approval_prompt") or "").strip(),
        "staged_action_url": str(safe_work_result.get("staged_action_url") or "").strip(),
        "work_type": str(safe_work_result.get("work_type") or "").strip().lower(),
    }
    inline_buttons: list[list[tuple[str, str]]] = []
    approval_surface: dict[str, object] = {}
    approval_record_path = ""
    staged_action_url = str(safe_work_result.get("staged_action_url") or "").strip()
    execution_status = str(execution_result.get("status") or "").strip().lower()
    execution_action = str(execution_result.get("action") or "").strip().lower()
    user_action_required = _telegram_inline_proactive_user_action_required(
        safe_work_result=safe_work_result,
        execution_result=execution_result,
        approval_request=approval_request,
        reply_text=reply_text,
    )
    reviewable_material = _telegram_inline_proactive_has_reviewable_material(
        safe_work_result=safe_work_result,
        execution_result=execution_result,
    )
    absorb_generic_task = _telegram_inline_proactive_should_absorb_generic_task(
        safe_work_result=safe_work_result,
        execution_result=execution_result,
    )
    approval_surface_needed = bool(packet_refs and safe_work_refs) and (
        str(safe_work_result.get("status") or "").strip() == "staged_for_user_decision"
    ) and user_action_required
    if approval_surface_needed:
        approval_prompt = str(safe_work_result.get("approval_prompt") or "").strip()
        approved_execution_mode = ""
        approved_action = ""
        if not approval_required:
            approval_prompt = build_reversible_execution_approval_prompt(action=execution_action)
            approved_execution_mode = "record_outcome_only"
            approved_action = execution_action
        approval_request["approval_prompt"] = approval_prompt
        approval_request["approved_execution_mode"] = approved_execution_mode
        approval_request["approved_action"] = approved_action
        if not approval_request_needs_telegram_user_action(approval_request):
            approval_surface_needed = False
            user_action_required = False
        else:
            prepared = prepare_proactive_ooda_telegram_approval(
                principal_id=principal_id,
                packet_ref=packet_refs[0],
                staged_artifact_ref=safe_work_refs[0],
                approval_prompt=approval_prompt,
                staged_action_url=staged_action_url,
                approved_execution_mode=approved_execution_mode,
                approved_action=approved_action,
                chat_id=str(chat_id or "").strip(),
                bot_token=str(bot_config.get("token") or "").strip(),
                root=_EA_ROOT,
                state_path=os.getenv("EA_PROACTIVE_OODA_STATE_PATH", "state/proactive_ooda_notified.json"),
                receipt_path=os.getenv("EA_PROACTIVE_OODA_RECEIPT_PATH", ""),
            )
            inline_buttons = [
                [(str(label or "").strip(), str(value or "").strip()) for label, value in row if str(label or "").strip() and str(value or "").strip()]
                for row in list(prepared.get("inline_buttons") or [])
                if row
            ]
            approval_surface = {
                "present": True,
                "channel": "telegram",
                "status": str(prepared.get("status") or "pending").strip() or "pending",
                "callback_token_sha256": str(prepared.get("callback_token_sha256") or "").strip(),
                "expires_at": str(prepared.get("expires_at") or "").strip(),
                "packet_ref_sha256": str(prepared.get("packet_ref_sha256") or "").strip(),
                "staged_artifact_sha256": str(prepared.get("staged_artifact_ref_sha256") or "").strip(),
                "approval_prompt_sha256": str(prepared.get("approval_prompt_sha256") or "").strip(),
                "staged_action_url_sha256": str(prepared.get("staged_action_url_sha256") or "").strip(),
                "inline_button_count": sum(len(row) for row in inline_buttons),
                "url_button_count": 0,
                "message_ids": (),
                "message_count": 0,
                "delivery_error_code": "",
            }
            approval_record_path = str(prepared.get("record_path") or "").strip()

    marker = f"{dedupe_key}:inline_proactive_ooda_task_staged" if dedupe_key else ""
    if marker and container.channel_runtime.find_observation_by_dedupe(marker, principal_id=principal_id) is None:
        container.channel_runtime.ingest_observation(
            principal_id=principal_id,
            channel="telegram",
            event_type="telegram.proactive_ooda_task_staged",
            payload={
                "chat_id": str(chat_id or "").strip(),
                "message_id": str(message_payload.get("message_id") or "").strip(),
                "text": text,
                "signal_ref": str(digest.items[0].signal_ref or "").strip(),
                "stage_packet_ref": packet_refs[0] if packet_refs else "",
                "safe_work_result_ref": safe_work_refs[0] if safe_work_refs else "",
                "approval_required": approval_required,
                "work_type": str(safe_work_result.get("work_type") or "").strip(),
                "summary": str(safe_work_result.get("summary") or "").strip(),
                "staged_action_url": staged_action_url,
                "office_signal_observation_id": str(office_signal_result.get("observation_id") or "").strip(),
            },
            source_id=str(getattr(event, "source_id", "") or "").strip() or f"telegram:{chat_id}",
            external_id=str(getattr(event, "external_id", "") or "").strip(),
            dedupe_key=marker,
        )
    return {
        "digest": digest,
        "safe_work_results": (safe_work_result,),
        "reply_text": reply_text,
        "inline_buttons": inline_buttons,
        "approval_surface": approval_surface,
        "approval_record_path": approval_record_path,
        "stage_packet_refs": packet_refs,
        "safe_work_result_refs": safe_work_refs,
        "reviewable_material": reviewable_material,
        "absorb_generic_task": absorb_generic_task,
        "user_action_required": user_action_required or bool(inline_buttons),
    }


def _telegram_finalize_inline_proactive_task(
    *,
    stage_result: dict[str, object],
    send_receipt: dict[str, object],
    principal_id: str,
) -> None:
    if not stage_result:
        return
    message_id = str(send_receipt.get("message_id") or "").strip()
    send_status = str(send_receipt.get("status") or "").strip()
    approval_surface = dict(stage_result.get("approval_surface") or {})
    record_path = str(stage_result.get("approval_record_path") or "").strip()
    if record_path:
        try:
            record_proactive_ooda_telegram_approval_delivery(
                record_path=record_path,
                message_ids=(message_id,) if message_id else (),
                status="pending" if send_status == "sent" and message_id else "delivery_failed",
                delivery_error_code="" if send_status == "sent" and message_id else "telegram_inline_approval_delivery_failed",
            )
        except Exception:
            pass
        if approval_surface:
            approval_surface["status"] = "pending" if send_status == "sent" and message_id else "delivery_failed"
            approval_surface["message_ids"] = (message_id,) if message_id else ()
            approval_surface["message_count"] = 1 if message_id else 0
            approval_surface["delivery_error_code"] = "" if send_status == "sent" and message_id else "telegram_inline_approval_delivery_failed"
    notification_result = {
        "channel": "telegram",
        "message_id": message_id,
        "message_ids": (message_id,) if message_id else (),
        "approval_surface": approval_surface,
    } if send_status == "sent" else None
    error_code = "" if notification_result is not None else "telegram_inline_proactive_reply_failed"
    digest = stage_result.get("digest")
    if digest is None:
        return
    receipt = build_run_receipt(
        digest=digest,
        dry_run=False,
        notification_result=notification_result,
        error_code=error_code,
        stage_packet_refs=tuple(stage_result.get("stage_packet_refs") or ()),
        safe_work_result_refs=tuple(stage_result.get("safe_work_result_refs") or ()),
    )
    persist_proactive_ooda_receipt(principal_id=principal_id, digest=digest, receipt=receipt)
    if teable_sync_enabled():
        try:
            sync_proactive_ooda_to_teable(
                principal_id=principal_id,
                digest=digest,
                receipt=receipt,
                safe_work_results=tuple(stage_result.get("safe_work_results") or ()),
            )
        except Exception:
            pass


def _telegram_command_reply_text(
    *,
    container: AppContainer,
    principal_id: str,
    text: str,
    payload: dict[str, object] | None = None,
    bot_handle: str,
    preferred_onemin_labels: tuple[str, ...] = (),
    current_message_id: str = "",
    chat_id: str = "",
) -> tuple[str, bool, int, bool]:
    fallback_retry_budget = TelegramTurnDecision().retry_budget
    ctx = _telegram_turn_context(
        container=container,
        principal_id=principal_id,
        text=text,
        payload=payload,
        bot_handle=bot_handle,
        preferred_onemin_labels=preferred_onemin_labels,
        current_message_id=current_message_id,
        chat_id=chat_id,
    )
    command_decision = _telegram_command_turn_decision(ctx)
    if command_decision.reply_text or command_decision.schedule_async:
        return (
            command_decision.reply_text,
            command_decision.schedule_async,
            command_decision.retry_budget,
            bool(command_decision.suppress_async_ack),
        )
    scout_update_decision = _telegram_scout_update_turn_decision(ctx)
    if scout_update_decision.reply_text or scout_update_decision.schedule_async:
        return (
            scout_update_decision.reply_text,
            scout_update_decision.schedule_async,
            scout_update_decision.retry_budget,
            bool(scout_update_decision.suppress_async_ack),
        )
    if _telegram_should_suppress_whatsapp_pairing_followup(ctx):
        return "", False, fallback_retry_budget, False
    link_decision = _telegram_link_turn_decision(ctx)
    if link_decision.reply_text or link_decision.schedule_async:
        return (
            link_decision.reply_text,
            link_decision.schedule_async,
            link_decision.retry_budget,
            bool(link_decision.suppress_async_ack),
        )
    photo_reply = _telegram_photo_reply_text(ctx.payload)
    if photo_reply:
        return photo_reply, False, fallback_retry_budget, False
    media_reply = _telegram_media_acknowledgement_reply(ctx.payload, text=ctx.text)
    if media_reply:
        return media_reply, False, fallback_retry_budget, False
    if ctx.normalized:
        probe_reply = _telegram_probe_reply_text(ctx.normalized)
        if probe_reply:
            return probe_reply, False, fallback_retry_budget, False
        if _telegram_local_tool_priority(ctx):
            local_decision = _telegram_local_turn_decision(ctx)
            if local_decision.reply_text or local_decision.schedule_async:
                return local_decision.reply_text, local_decision.schedule_async, local_decision.retry_budget, bool(local_decision.suppress_async_ack)
        math_reply = _safe_math_answer(ctx.normalized)
        if math_reply:
            return math_reply, False, fallback_retry_budget, False
        if _telegram_force_async_path(ctx):
            if _telegram_similar_async_prompt_pending(
                container,
                principal_id=principal_id,
                chat_id=ctx.chat_id,
                text=ctx.normalized,
            ):
                return "", False, fallback_retry_budget, False
            return "", True, fallback_retry_budget, False
        general_reply = _telegram_general_reply_text(container=container, principal_id=principal_id, text=ctx.normalized)
        if (
            ctx.is_completion_cue
            and ctx.chat_id
            and _telegram_is_google_photos_picker_block_reply(general_reply)
            and _telegram_recent_messages_include_google_photos_context(
                container,
                principal_id=principal_id,
            )
            and _telegram_same_reply_recently_sent(
                container,
                principal_id=principal_id,
                chat_id=ctx.chat_id,
                reply_text=general_reply,
                )
            ):
                return "", False, fallback_retry_budget, False
        if general_reply and not general_reply.startswith(_telegram_saved_flow_reply_prefix()):
            return general_reply, False, fallback_retry_budget, False
        if _telegram_prefers_async_codex_chat(ctx.normalized):
            if _telegram_low_signal_followup_cue(ctx.normalized):
                sync_timeout = 0.0
                try:
                    sync_timeout = max(
                        float(str(os.getenv("EA_TELEGRAM_SYNC_REAL_REPLY_TIMEOUT_SECONDS") or "6").strip() or "6"),
                        1.0,
                    )
                except Exception:
                    sync_timeout = 6.0
                real_reply = _telegram_real_ea_reply_text(
                    container=container,
                    principal_id=principal_id,
                    text=ctx.normalized,
                    current_message_id=current_message_id,
                    preferred_onemin_labels=preferred_onemin_labels,
                    timeout_seconds=sync_timeout,
                ).strip()
                if real_reply:
                    return real_reply, False, fallback_retry_budget, False
            if _telegram_similar_async_prompt_pending(
                container,
                principal_id=principal_id,
                chat_id=ctx.chat_id,
                text=ctx.normalized,
            ):
                return "", False, fallback_retry_budget, False
            return "", True, fallback_retry_budget, False
        local_decision = _telegram_local_turn_decision(ctx)
        if local_decision.reply_text or local_decision.schedule_async:
            return (
                local_decision.reply_text,
                local_decision.schedule_async,
                local_decision.retry_budget,
                bool(local_decision.suppress_async_ack),
            )
        sync_timeout = 0.0
        try:
            sync_timeout = max(
                float(str(os.getenv("EA_TELEGRAM_SYNC_REAL_REPLY_TIMEOUT_SECONDS") or "6").strip() or "6"),
                1.0,
            )
        except Exception:
            sync_timeout = 6.0
        real_reply = _telegram_real_ea_reply_text(
            container=container,
            principal_id=principal_id,
            text=ctx.normalized,
            current_message_id=current_message_id,
            preferred_onemin_labels=preferred_onemin_labels,
            timeout_seconds=sync_timeout,
        ).strip()
        if real_reply:
            return real_reply, False, fallback_retry_budget, False
        if _telegram_should_async_assistant_reply(ctx.normalized):
            if _telegram_similar_async_prompt_pending(
                container,
                principal_id=principal_id,
                chat_id=ctx.chat_id,
                text=ctx.normalized,
            ):
                return "", False, fallback_retry_budget, False
            return "", True, fallback_retry_budget, False
        return general_reply, False, fallback_retry_budget, False
    return "", False, fallback_retry_budget, False


def _telegram_session_turn(
    *,
    container: AppContainer,
    principal_id: str,
    text: str,
    payload: dict[str, object] | None = None,
    bot_handle: str,
    preferred_onemin_labels: tuple[str, ...] = (),
    current_message_id: str = "",
    chat_id: str = "",
    dedupe_key: str = "",
) -> TelegramTurnDecision:
    initial_ctx = build_turn_context(
        container=container,
        principal_id=principal_id,
        text=text,
        payload=dict(payload or {}),
        bot_handle=bot_handle,
        preferred_onemin_labels=preferred_onemin_labels,
        current_message_id=current_message_id,
        chat_id=chat_id,
        completion_cue_predicate=_telegram_low_signal_followup_cue,
    )
    if _telegram_should_suppress_whatsapp_pairing_followup(initial_ctx):
        _record_telegram_whatsapp_pairing_followup_suppressed(
            container,
            principal_id=principal_id,
            chat_id=chat_id,
            dedupe_key=dedupe_key,
            current_message_id=current_message_id,
            source_text=text,
            source_kind=str(dict(payload or {}).get("kind") or "").strip(),
        )
        return TelegramTurnDecision()
    audiobook_epub_decision = _telegram_audiobook_epub_turn_decision(initial_ctx)
    if audiobook_epub_decision.reply_text or audiobook_epub_decision.schedule_async:
        return audiobook_epub_decision
    audiobook_status_decision = _telegram_local_turn_decision(initial_ctx)
    if (
        _telegram_audiobook_status_intent(initial_ctx.normalized)
        and (audiobook_status_decision.reply_text or audiobook_status_decision.schedule_async)
    ):
        return audiobook_status_decision
    audiobook_text_reply = _telegram_audiobook_text_request_reply_text(initial_ctx.normalized)
    if audiobook_text_reply:
        return TelegramTurnDecision(reply_text=audiobook_text_reply)
    instructional_video_decision = _telegram_instructional_video_turn_decision(initial_ctx)
    if instructional_video_decision.reply_text or instructional_video_decision.schedule_async:
        return instructional_video_decision
    pdf_decision = _telegram_property_pdf_turn_decision(initial_ctx)
    if pdf_decision.reply_text or pdf_decision.schedule_async:
        return pdf_decision
    reply_text, schedule_async, retry_budget, suppress_async_ack = _telegram_command_reply_text(
        container=container,
        principal_id=principal_id,
        text=text,
        payload=payload,
        bot_handle=bot_handle,
        preferred_onemin_labels=preferred_onemin_labels,
        current_message_id=current_message_id,
        chat_id=chat_id,
    )
    inline_buttons: list[list[tuple[str, str]]] | None = None
    if reply_text and _telegram_audiobook_status_intent(text):
        _title, status_buttons = _telegram_latest_audiobook_playback_buttons_for_chat(
            bot_config=dict(dict(payload or {}).get("_bot_config") or {}),
            chat_id=chat_id,
        )
        inline_buttons = status_buttons or None
    ctx = build_turn_context(
        container=container,
        principal_id=principal_id,
        text=text,
        payload=dict(payload or {}),
        bot_handle=bot_handle,
        preferred_onemin_labels=preferred_onemin_labels,
        current_message_id=current_message_id,
        chat_id=chat_id,
        completion_cue_predicate=_telegram_low_signal_followup_cue,
    )
    callback_decision = _telegram_callback_turn_decision(ctx)
    if callback_decision.reply_text or callback_decision.schedule_async:
        return callback_decision
    feedback_followup_decision = _telegram_notification_feedback_followup_turn_decision(ctx)
    if feedback_followup_decision.reply_text or feedback_followup_decision.schedule_async:
        return feedback_followup_decision
    return TelegramTurnDecision(
        reply_text=reply_text,
        inline_buttons=inline_buttons,
        schedule_async=schedule_async,
        retry_budget=retry_budget,
        suppress_async_ack=suppress_async_ack,
    )


class TelegramIngestOut(BaseModel):
    observation_id: str
    principal_id: str
    channel: str
    event_type: str
    created_at: str
    reply_sent: bool = False
    reply_text: str = ""


class TelegramBusinessIngestOut(BaseModel):
    observation_id: str
    principal_id: str
    channel: str
    event_type: str
    created_at: str
    status: str
    update_type: str
    chat_scope: str
    reply_sent: bool = False
    allowed_updates: list[str] = Field(default_factory=list)


@router.post("/telegram/business/ingest/{bot_key}")
@router.post("/telegram/business/ingest")
def ingest_telegram_business(
    request: Request,
    body: dict[str, object] = Body(default_factory=dict),
    bot_key: str = "",
    container: AppContainer = Depends(get_container),
) -> TelegramBusinessIngestOut:
    payload = dict(body or {})
    update = dict(payload.get("update") or {}) if isinstance(payload.get("update"), dict) else payload
    header_secret = str(request.headers.get("x-telegram-bot-api-secret-token") or "")
    provided_secret = str(update.get("secret_token") or "")
    bot_config = _resolve_telegram_bot_config(bot_key=bot_key, provided_secret=provided_secret, header_secret=header_secret)
    _require_telegram_ingest_secret(
        config=bot_config,
        provided=provided_secret,
        header_value=header_secret,
    )
    result = telegram_business_signal_ingest.normalize_telegram_business_update(
        update,
        allowed_chat_ids=telegram_business_signal_ingest.env_allowed_chat_ids(),
        allowed_chat_hashes=telegram_business_signal_ingest.env_allowed_chat_hashes(),
        allowed_chat_labels=telegram_business_signal_ingest.env_allowed_chat_labels(),
        hash_salt=str(os.getenv("EA_TELEGRAM_BUSINESS_HASH_SALT") or "").strip(),
    )
    principal_id = str(bot_config.get("default_principal_id") or _telegram_default_principal_id() or "").strip()
    principal_id = _canonical_telegram_principal_id(container, principal_id) or principal_id
    if not principal_id:
        raise HTTPException(status_code=404, detail="telegram_business_principal_not_configured")
    if not _telegram_principal_is_registered_user(container=container, principal_id=principal_id):
        raise HTTPException(status_code=403, detail="telegram_principal_not_registered")
    event = container.channel_runtime.ingest_observation(
        principal_id=principal_id,
        channel=telegram_business_signal_ingest.CHANNEL,
        event_type=result.event_type,
        payload=result.candidate,
        source_id=result.source_id,
        external_id=result.external_id,
        dedupe_key=result.dedupe_key,
        auth_context_json={
            "actor_type": "telegram_business_bot",
            "principal_originated": False,
            "bot_key": str(bot_config.get("bot_key") or bot_key or "default").strip() or "default",
            "business_secret_verified": True,
            "read_only_ingest": True,
        },
    )
    return TelegramBusinessIngestOut(
        observation_id=event.observation_id,
        principal_id=event.principal_id,
        channel=event.channel,
        event_type=event.event_type,
        created_at=event.created_at,
        status=result.status,
        update_type=result.update_type,
        chat_scope=result.chat_scope,
        reply_sent=False,
        allowed_updates=telegram_business_signal_ingest.allowed_updates(),
    )


@router.post("/telegram/ingest/{bot_key}")
@router.post("/telegram/ingest")
def ingest_telegram(
    request: Request,
    body: dict[str, object] = Body(default_factory=dict),
    bot_key: str = "",
    container: AppContainer = Depends(get_container),
) -> TelegramIngestOut:
    payload = dict(body or {})
    update = dict(payload.get("update") or {}) if isinstance(payload.get("update"), dict) else payload
    header_secret = str(request.headers.get("x-telegram-bot-api-secret-token") or "")
    provided_secret = str(update.get("secret_token") or "")
    bot_config = _resolve_telegram_bot_config(bot_key=bot_key, provided_secret=provided_secret, header_secret=header_secret)
    _require_telegram_ingest_secret(
        config=bot_config,
        provided=provided_secret,
        header_value=header_secret,
    )
    fields = _telegram.to_observation_fields(update)
    chat_id = str(fields.get("chat_id") or "").strip()
    dedupe_key = str(fields.get("dedupe_key") or "")
    principal_id = _resolve_telegram_principal(
        container,
        chat_id,
        bot_key=str(bot_config.get("bot_key") or "").strip(),
        bot_handle=str(bot_config.get("handle") or "").strip(),
    )
    if not principal_id:
        principal_id = _auto_bind_telegram_chat(container, chat_id, config=bot_config)
    if not principal_id:
        raise HTTPException(status_code=404, detail="telegram_binding_not_found")
    if not _telegram_principal_is_registered_user(container=container, principal_id=principal_id):
        raise HTTPException(status_code=403, detail="telegram_principal_not_registered")
    existing_event = (
        container.channel_runtime.find_observation_by_dedupe(dedupe_key, principal_id=principal_id) if dedupe_key else None
    )
    if existing_event is not None:
        message_payload = dict(getattr(existing_event, "payload", {}) or {})
    else:
        message_payload = resolve_telegram_message_payload(
            payload=dict(fields.get("payload") or {}),
            bot_token=str(bot_config.get("token") or "").strip(),
            allow_video_transcription=False,
        )
        if message_payload:
            fields["payload"] = message_payload
    event = existing_event or container.channel_runtime.ingest_observation(
        principal_id=principal_id,
        channel=_telegram.channel,
        event_type=str(fields.get("event_type") or "telegram.update"),
        payload=message_payload,
        source_id=str(fields.get("source_id") or ""),
        external_id=str(fields.get("external_id") or ""),
        dedupe_key=dedupe_key,
    )
    decision = _telegram_session_turn(
        container=container,
        principal_id=principal_id,
        text=str(message_payload.get("text") or ""),
        payload={**message_payload, "_bot_config": dict(bot_config), "_dedupe_key": dedupe_key},
        bot_handle=str(bot_config.get("handle") or "").strip(),
        preferred_onemin_labels=tuple(
            str(item or "").strip()
            for item in list(bot_config.get("preferred_onemin_labels") or ())
            if str(item or "").strip()
        ),
        current_message_id=str(message_payload.get("message_id") or ""),
        chat_id=chat_id,
        dedupe_key=dedupe_key,
    )
    if str(message_payload.get("kind") or "").strip().lower() == "callback_query":
        try:
            _telegram_answer_callback_query(
                bot_token=str(bot_config.get("token") or "").strip(),
                callback_query_id=str(message_payload.get("callback_query_id") or ""),
                text="Received",
            )
        except Exception:
            pass
    reply_text = decision.reply_text
    schedule_async = decision.schedule_async
    async_text = str(decision.async_text or "").strip() or str(message_payload.get("text") or "")
    async_message_id = str(decision.async_message_id or "").strip() or str(message_payload.get("message_id") or "")
    async_payload = dict(decision.async_payload or {})
    inline_buttons = decision.inline_buttons
    proactive_stage_result: dict[str, object] = {}
    if (
        (not reply_text or _telegram_reply_is_generic_task_fallback(reply_text))
        and (not schedule_async or _telegram_async_reply_is_generic_task(async_payload))
        and not inline_buttons
        and str(message_payload.get("kind") or "").strip().lower() in {"", "text", "voice"}
        and str(message_payload.get("text") or "").strip()
    ):
        proactive_stage_result = _telegram_stage_inline_proactive_task(
            container=container,
            principal_id=principal_id,
            bot_config=bot_config,
            chat_id=chat_id,
            event=event,
            dedupe_key=dedupe_key,
            message_payload=message_payload,
        )
        staged_reply_text = str(proactive_stage_result.get("reply_text") or "").strip()
        staged_inline_buttons = proactive_stage_result.get("inline_buttons")
        reviewable_material = bool(proactive_stage_result.get("reviewable_material"))
        absorb_generic_task = bool(proactive_stage_result.get("absorb_generic_task"))
        if staged_reply_text and reviewable_material:
            reply_text = staged_reply_text
            schedule_async = False
            async_text = ""
            async_message_id = ""
            async_payload = {}
            if isinstance(staged_inline_buttons, list):
                inline_buttons = staged_inline_buttons
        elif absorb_generic_task:
            reply_text = ""
            schedule_async = False
            async_text = ""
            async_message_id = ""
            async_payload = {}
            inline_buttons = []
    if reply_text and _telegram_should_suppress_sync_nonaction_reply(
        reply_text=reply_text,
        has_action_surface=bool(inline_buttons) or bool(proactive_stage_result.get("user_action_required")),
    ):
        _record_telegram_sync_reply_suppressed(
            container,
            principal_id=principal_id,
            chat_id=chat_id,
            dedupe_key=dedupe_key,
            current_message_id=str(message_payload.get("message_id") or ""),
            source_text=str(message_payload.get("text") or ""),
            reply_text=reply_text,
        )
        reply_text = ""
        inline_buttons = None
    reply_sent = False
    send_receipt: dict[str, object] = {}
    if reply_text and chat_id and not _telegram_reply_already_sent(container, principal_id=principal_id, dedupe_key=dedupe_key):
        try:
            if proactive_stage_result or inline_buttons:
                send_receipt = _telegram_send_and_record_reply_receipt(
                    container=container,
                    principal_id=principal_id,
                    bot_config=bot_config,
                    chat_id=chat_id,
                    dedupe_key=dedupe_key,
                    reply_text=reply_text,
                    source_text=str(message_payload.get("text") or ""),
                    inline_buttons=inline_buttons,
                )
                reply_sent = str(send_receipt.get("status") or "").strip() == "sent"
            else:
                reply_sent = _telegram_send_and_record_reply(
                    container=container,
                    principal_id=principal_id,
                    bot_config=bot_config,
                    chat_id=chat_id,
                    dedupe_key=dedupe_key,
                    reply_text=reply_text,
                    source_text=str(message_payload.get("text") or ""),
                )
                send_receipt = {"status": "sent" if reply_sent else "failed"}
        except Exception:
            reply_sent = False
            send_receipt = {"status": "failed", "reason": "send_exception"}
    if proactive_stage_result and send_receipt:
        _telegram_finalize_inline_proactive_task(
            stage_result=proactive_stage_result,
            send_receipt=send_receipt,
            principal_id=principal_id,
        )
    if schedule_async and chat_id:
        async_retry_budget = int(decision.retry_budget)
        async_text_priority = (
            _telegram_property_render_priority(container=container, principal_id=principal_id)
            if _telegram_supported_property_link(str(message_payload.get("text") or "")) else "free"
        )
        if not decision.suppress_async_ack and _telegram_processing_acks_enabled():
            try:
                _telegram_send_processing_ack(
                    container=container,
                    principal_id=principal_id,
                    bot_config=bot_config,
                    chat_id=chat_id,
                    dedupe_key=dedupe_key,
                    source_text=async_text,
                    current_message_id=async_message_id,
                    render_priority=async_text_priority,
                )
            except Exception:
                pass
        _telegram_schedule_async_assistant_reply(
            container=container,
            principal_id=principal_id,
            bot_config=bot_config,
            chat_id=chat_id,
            dedupe_key=dedupe_key,
            text=async_text,
            current_message_id=async_message_id,
            retry_budget=async_retry_budget,
            async_payload=async_payload,
        )
    return TelegramIngestOut(
        observation_id=event.observation_id,
        principal_id=event.principal_id,
        channel=event.channel,
        event_type=event.event_type,
        created_at=event.created_at,
        reply_sent=reply_sent,
        reply_text=reply_text,
    )
