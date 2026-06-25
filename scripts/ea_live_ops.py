#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from functools import lru_cache
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts"
for path in (ROOT / "ea", ROOT, SCRIPT_DIR):
    if path.exists() and str(path) not in sys.path:
        sys.path.insert(0, str(path))

import check_whatsapp_web_session_readiness as readiness_script  # noqa: E402
from app.container import build_container  # noqa: E402
from app.services import whatsapp_web_session_delivery  # noqa: E402
from app.services.audiobook_epub_pipeline import audiobook_runtime_preflight  # noqa: E402
from app.services.responses_upstream import _provider_health_report  # noqa: E402


DEFAULT_SESSION_API_BASE_URL = "http://127.0.0.1:8098"
DEFAULT_READINESS_RECEIPT_PATH = ROOT / ".codex-studio" / "published" / "whatsapp_web_action_processor_readiness.generated.json"
DEFAULT_RUNTIME_CONTAINER = "ea-api"


def _env(name: str, default: str = "") -> str:
    return str(os.environ.get(name) or default).strip()


def _digits(value: object) -> str:
    return re.sub(r"\D+", "", str(value or ""))


def _normalize_phone_hint(value: object) -> str:
    raw = str(value or "").strip()
    return raw if raw in {"*", "default"} else _digits(raw)


def _json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True)


def _read_json_file(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _request_json(
    *,
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
    body: dict[str, object] | None = None,
    timeout: float = 15.0,
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers=headers or {},
        data=None if body is None else json.dumps(body).encode("utf-8"),
        method=method,
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return dict(payload) if isinstance(payload, dict) else {}


def _http_error_payload(exc: urllib.error.HTTPError) -> dict[str, Any]:
    try:
        payload = json.loads(exc.read().decode("utf-8"))
    except Exception:
        payload = {}
    result = dict(payload) if isinstance(payload, dict) else {}
    result.setdefault("status_code", int(getattr(exc, "code", 0) or 0))
    result.setdefault("reason", str(result.get("reason") or getattr(exc, "reason", "") or type(exc).__name__))
    return result


def _runtime_container_name() -> str:
    return _env("EA_RUNTIME_CONTAINER", DEFAULT_RUNTIME_CONTAINER)


def _runtime_container_preflight() -> dict[str, object]:
    container = _runtime_container_name()
    if not container:
        return {}
    code = (
        "import json\n"
        "from app.services.audiobook_epub_pipeline import audiobook_runtime_preflight\n"
        "print(json.dumps(audiobook_runtime_preflight(), sort_keys=True))\n"
    )
    try:
        proc = subprocess.run(
            ["docker", "exec", container, "python3", "-c", code],
            text=True,
            capture_output=True,
            check=False,
            timeout=20,
        )
    except Exception:
        return {}
    if proc.returncode != 0:
        return {}
    try:
        payload = json.loads(str(proc.stdout or "").strip())
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


@lru_cache(maxsize=1)
def _container():
    return build_container()


def _provider_display_name(provider_key: str) -> str:
    state = _container().provider_registry.binding_state(provider_key)
    if state is not None and str(state.display_name or "").strip():
        return str(state.display_name)
    return provider_key.replace("_", " ")


def _normalize_provider_key(value: object) -> str:
    registry = _container().provider_registry
    normalizer = getattr(registry, "_normalize_provider_key", None)
    if callable(normalizer):
        return str(normalizer(value) or "").strip()
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _operator_text_for_provider(report: dict[str, object]) -> str:
    pieces = [
        f"provider={report.get('provider_key')}",
        f"state={report.get('status')}",
    ]
    if report.get("account_label"):
        pieces.append(f"account={report['account_label']}")
    if report.get("remaining") not in (None, "") and report.get("unit"):
        pieces.append(f"remaining={report['remaining']} {report['unit']}")
    if report.get("refresh_at"):
        pieces.append(f"refresh_at={report['refresh_at']}")
    if report.get("observed_at"):
        pieces.append(f"observed_at={report['observed_at']}")
    if report.get("source"):
        pieces.append(f"source={report['source']}")
    return "; ".join(str(item) for item in pieces if str(item).strip())


def _unmixr_runtime_operational_status(preflight: dict[str, object]) -> str:
    provider_payload = dict(preflight.get("provider") or {})
    checks = {
        str(row.get("key") or "").strip(): str(row.get("status") or "").strip()
        for row in preflight.get("checks") or []
        if isinstance(row, dict) and str(row.get("key") or "").strip()
    }
    blocking_checks = (
        "telegram_audiobook_enabled",
        "jobs_root_durable",
        "jobs_root_writable",
        "external_tts_enabled",
        "unmixr_auto_render_enabled",
        "voice_catalog_configured",
    )
    if any(checks.get(key) == "fail" for key in blocking_checks):
        return "fail"
    if int(provider_payload.get("voice_catalog_count") or 0) < int(provider_payload.get("voice_audition_min_candidates") or 3):
        return "fail"
    if int(provider_payload.get("api_key_slot_count") or 0) <= 0:
        return "fail"
    return "pass"


def probe_provider(provider: str, *, output_format: str = "json") -> dict[str, object]:
    provider_key = _normalize_provider_key(provider)
    if provider_key == "onemin":
        provider_health = _provider_health_report()
        aggregate = _container().onemin_manager.aggregate_snapshot(
            provider_health=provider_health,
            binding_rows=[],
            principal_id="",
        )
        accounts = [dict(row) for row in aggregate.get("accounts") or [] if isinstance(row, dict)]
        latest_snapshot = max(
            (str(row.get("last_billing_snapshot_at") or "").strip() for row in accounts if str(row.get("last_billing_snapshot_at") or "").strip()),
            default="",
        )
        next_topup = min(
            (str(row.get("next_topup_at") or "").strip() for row in accounts if str(row.get("next_topup_at") or "").strip()),
            default="",
        )
        report = {
            "provider_key": "onemin",
            "display_name": _provider_display_name("onemin"),
            "status": str(aggregate.get("state") or "unknown").strip() or "unknown",
            "remaining": aggregate.get("live_remaining_credits_total", aggregate.get("sum_free_credits")),
            "unit": "credits",
            "refresh_at": next_topup or latest_snapshot,
            "observed_at": latest_snapshot or "",
            "account_label": "",
            "source": "app.services.responses_upstream._provider_health_report + onemin_manager.aggregate_snapshot",
            "raw": {
                "account_count": aggregate.get("account_count"),
                "live_positive_balance_account_count": aggregate.get("live_positive_balance_account_count"),
                "estimated_hours_remaining_at_current_pace": aggregate.get("estimated_hours_remaining_at_current_pace"),
                "scope": aggregate.get("scope"),
            },
        }
    elif provider_key == "unmixr":
        preflight = _runtime_container_preflight() or audiobook_runtime_preflight()
        provider_payload = dict(preflight.get("provider") or {})
        report = {
            "provider_key": "unmixr",
            "display_name": _provider_display_name("unmixr"),
            "status": _unmixr_runtime_operational_status(preflight),
            "remaining": provider_payload.get("api_key_slot_count"),
            "unit": "configured_api_key_slots",
            "refresh_at": "",
            "observed_at": str(preflight.get("observed_at") or "").strip(),
            "account_label": "",
            "source": str(preflight.get("contract_name") or "ea.telegram_epub_audiobook_runtime_preflight.v1"),
            "raw": {
                "voice_catalog_count": provider_payload.get("voice_catalog_count"),
                "voice_discovery_enabled": provider_payload.get("voice_discovery_enabled"),
                "unmixr_auto_render_enabled": provider_payload.get("unmixr_auto_render_enabled"),
                "voice_audition_min_candidates": provider_payload.get("voice_audition_min_candidates"),
                "runtime_container": _runtime_container_name(),
                "preflight_status": str(preflight.get("status") or "").strip(),
                "preflight_failed_checks": list(preflight.get("failed_checks") or []),
                "preflight_warned_checks": list(preflight.get("warned_checks") or []),
            },
        }
    else:
        state = _container().provider_registry.binding_state(provider_key)
        report = {
            "provider_key": provider_key,
            "display_name": _provider_display_name(provider_key),
            "status": str(getattr(state, "state", "") or getattr(state, "status", "") or "unknown").strip() or "unknown",
            "remaining": None,
            "unit": "",
            "refresh_at": "",
            "observed_at": str(getattr(state, "updated_at", "") or "").strip(),
            "account_label": "",
            "source": "provider_registry.binding_state",
            "raw": {
                "enabled": bool(getattr(state, "enabled", False)),
                "executable": bool(getattr(state, "executable", False)),
                "health_state": str(getattr(state, "health_state", "") or "").strip(),
                "capabilities": list(getattr(state, "capabilities", ()) or ()),
            },
        }
    if output_format == "operator":
        report["operator_text"] = _operator_text_for_provider(report)
    return report


def _load_whatsapp_binding(args: argparse.Namespace):
    binding_path = str(getattr(args, "binding_json", "") or "").strip()
    database_url = str(args.database_url or _env("DATABASE_URL")).strip()
    binding_id = str(args.binding_id or "").strip()
    principal_id = str(args.principal_id or "").strip()
    if binding_path:
        payload = readiness_script._load_json_file(binding_path)
        binding = readiness_script._binding_from_json(payload, binding_id=binding_id)
        if binding is None and readiness_script._should_fallback_to_latest_binding(binding_id=binding_id, principal_id=principal_id):
            binding = readiness_script._latest_enabled_binding_from_json(payload)
        if binding is not None:
            return binding
    if not database_url:
        return None
    binding = readiness_script._binding_from_postgres(
        database_url,
        binding_id=binding_id,
        principal_id=principal_id,
    )
    if binding is None and readiness_script._should_fallback_to_latest_binding(binding_id=binding_id, principal_id=principal_id):
        binding = readiness_script._binding_from_postgres(database_url, binding_id="", principal_id="")
    return binding


def _session_headers_from_binding(binding: Any | None) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if binding is not None:
        config = _whatsapp_delivery_config(binding)
        token = str(config.get("token") or "").strip()
        header_name = str(config.get("auth_header_name") or "Authorization").strip() or "Authorization"
        header_prefix = str(config.get("auth_header_prefix") or "").strip()
    else:
        token = _env("EA_WHATSAPP_WEB_SESSION_API_TOKEN")
        header_name = _env("EA_WHATSAPP_WEB_SESSION_AUTH_HEADER_NAME", "Authorization") or "Authorization"
        header_prefix = _env("EA_WHATSAPP_WEB_SESSION_AUTH_HEADER_PREFIX", "Bearer ")
    if token:
        headers[header_name] = f"{header_prefix}{token}".strip()
    return headers


def _session_api_base_url(binding: Any | None, explicit_base_url: str = "") -> str:
    if str(explicit_base_url or "").strip():
        return str(explicit_base_url).rstrip("/")
    if binding is not None:
        config = _whatsapp_delivery_config(binding)
        template = str(config.get("endpoint_template") or "").strip()
        if "/sessions/" in template:
            return template.split("/sessions/", 1)[0].rstrip("/")
    return _env("EA_WHATSAPP_WEB_SESSION_API_BASE_URL", DEFAULT_SESSION_API_BASE_URL).rstrip("/")


def _whatsapp_delivery_config(binding: Any | None) -> dict[str, Any]:
    if binding is None:
        return {}
    try:
        return dict(whatsapp_web_session_delivery.resolve_whatsapp_web_session_delivery_config(binding))
    except Exception:
        return {}


def _session_ref(binding: Any | None, explicit_session_ref: str = "") -> str:
    if str(explicit_session_ref or "").strip():
        return str(explicit_session_ref).strip()
    if binding is not None:
        config = _whatsapp_delivery_config(binding)
        configured = str(config.get("session_ref") or "").strip()
        if configured:
            return configured
    env_value = _env("EA_WHATSAPP_WEB_DEFAULT_SESSION_REF")
    if env_value:
        return env_value
    receipt = _read_json_file(DEFAULT_READINESS_RECEIPT_PATH)
    return str(receipt.get("effective_session_ref") or receipt.get("session_ref") or "").strip()


def _sidecar_get(*, binding: Any | None, suffix: str, session_api_base_url: str = "", session_ref: str = "", timeout_seconds: float = 15.0) -> dict[str, Any]:
    base_url = _session_api_base_url(binding, session_api_base_url)
    effective_session_ref = urllib.parse.quote(_session_ref(binding, session_ref), safe="")
    return _request_json(
        method="GET",
        url=f"{base_url}/sessions/{effective_session_ref}/{suffix.lstrip('/')}",
        headers=_session_headers_from_binding(binding),
        timeout=timeout_seconds,
    )


def _sidecar_post(*, binding: Any | None, suffix: str, body: dict[str, object], session_api_base_url: str = "", session_ref: str = "", timeout_seconds: float = 15.0) -> dict[str, Any]:
    base_url = _session_api_base_url(binding, session_api_base_url)
    effective_session_ref = urllib.parse.quote(_session_ref(binding, session_ref), safe="")
    return _request_json(
        method="POST",
        url=f"{base_url}/sessions/{effective_session_ref}/{suffix.lstrip('/')}",
        headers=_session_headers_from_binding(binding),
        body=body,
        timeout=timeout_seconds,
    )


def _match_route(route: dict[str, object], phone_hint: str) -> bool:
    normalized_hint = _normalize_phone_hint(phone_hint)
    if normalized_hint in {"", "*", "default"}:
        return str(route.get("route_key") or "").strip() in {"default", "*"}
    candidates = {
        _digits(route.get("inbound_number_digits")),
        _digits(route.get("route_key")),
    }
    return any(candidate.endswith(normalized_hint) for candidate in candidates if candidate)


def _recent_chat_ref_for_hint(conversations_payload: dict[str, object], phone_hint: str) -> str:
    return _recent_conversation_match(conversations_payload, phone_hint).get("chat_ref", "")


def _recent_sender_digits_for_hint(conversations_payload: dict[str, object], phone_hint: str) -> str:
    return _recent_conversation_match(conversations_payload, phone_hint, include_outbound_sender_digits=True).get("sender_digits", "")


def _recent_conversation_match(
    conversations_payload: dict[str, object],
    phone_hint: str,
    *,
    include_outbound_sender_digits: bool = False,
) -> dict[str, str]:
    normalized_hint = _normalize_phone_hint(phone_hint)
    if not normalized_hint or normalized_hint in {"*", "default"}:
        return {}
    matches: list[tuple[str, str, str]] = []
    for conversation in conversations_payload.get("conversations") or []:
        if not isinstance(conversation, dict):
            continue
        chat_ref = str(conversation.get("chat_ref") or "").strip()
        if not chat_ref:
            continue
        sender_candidates = {
            _digits(conversation.get("recipient")),
        }
        latest_message_timestamp = ""
        for message in conversation.get("messages") or []:
            if isinstance(message, dict):
                message_timestamp = str(message.get("message_timestamp") or "").strip()
                if message_timestamp > latest_message_timestamp:
                    latest_message_timestamp = message_timestamp
                direction = str(message.get("direction") or "").strip().lower()
                from_me = bool(message.get("from_me"))
                if include_outbound_sender_digits or (not from_me and direction != "outbound"):
                    sender_candidates.add(_digits(message.get("sender_digits")))
        matched_sender = next(
            (candidate for candidate in sorted(sender_candidates) if candidate and candidate.endswith(normalized_hint)),
            "",
        )
        if matched_sender:
            sort_timestamp = str(
                conversation.get("updated_at")
                or conversation.get("last_message_at")
                or conversation.get("timestamp")
                or latest_message_timestamp
                or ""
            ).strip()
            matches.append(
                (
                    sort_timestamp,
                    chat_ref,
                    matched_sender,
                )
            )
    matches.sort()
    if not matches:
        return {}
    _, chat_ref, sender_digits = matches[-1]
    return {"chat_ref": chat_ref, "sender_digits": sender_digits}


def resolve_whatsapp(phone_hint: str, *, args: argparse.Namespace) -> dict[str, object]:
    binding = _load_whatsapp_binding(args)
    normalized_hint = _normalize_phone_hint(phone_hint)
    routes_payload = _sidecar_get(
        binding=binding,
        suffix="heyy-ai-routes",
        session_api_base_url=str(getattr(args, "session_api_base_url", "") or "").strip(),
        session_ref=str(getattr(args, "session_ref", "") or "").strip(),
        timeout_seconds=float(getattr(args, "timeout_seconds", 15.0) or 15.0),
    )
    try:
        conversations_payload = _sidecar_get(
            binding=binding,
            suffix="conversations?take=50&messages=1&fetch_timeout_ms=5000",
            session_api_base_url=str(getattr(args, "session_api_base_url", "") or "").strip(),
            session_ref=str(getattr(args, "session_ref", "") or "").strip(),
            timeout_seconds=float(getattr(args, "timeout_seconds", 15.0) or 15.0),
        )
    except urllib.error.HTTPError as exc:
        conversations_payload = _http_error_payload(exc)
    routes = [dict(row) for row in routes_payload.get("routes") or [] if isinstance(row, dict)]
    matched_routes = [row for row in routes if _match_route(row, phone_hint)]
    recent_sender_digits = _recent_sender_digits_for_hint(conversations_payload, phone_hint)
    if recent_sender_digits:
        narrowed_routes = [
            row
            for row in matched_routes
            if _digits(row.get("inbound_number_digits") or row.get("route_key")).endswith(recent_sender_digits)
        ]
        if len(narrowed_routes) == 1:
            matched_routes = narrowed_routes
    route = matched_routes[0] if len(matched_routes) == 1 else {}
    recipient_digits = _digits(route.get("inbound_number_digits") or route.get("route_key") or recent_sender_digits)
    if not route and normalized_hint and recipient_digits == normalized_hint:
        recipient_digits = ""
    recipient_payload: dict[str, Any] = {}
    if recipient_digits:
        try:
            recipient_payload = _sidecar_get(
                binding=binding,
                suffix=f"recipients/{urllib.parse.quote(recipient_digits, safe='')}",
                session_api_base_url=str(getattr(args, "session_api_base_url", "") or "").strip(),
                session_ref=str(getattr(args, "session_ref", "") or "").strip(),
                timeout_seconds=float(getattr(args, "timeout_seconds", 15.0) or 15.0),
            )
        except Exception as exc:
            recipient_payload = {"registered": False, "reason": type(exc).__name__}
    chat_ref = str(recipient_payload.get("chat_ref") or "").strip() or _recent_chat_ref_for_hint(conversations_payload, phone_hint)
    conversations_ready = bool(conversations_payload.get("ok", True))
    sidecar_reason = str(conversations_payload.get("reason") or "").strip()
    status = (
        "resolved"
        if route
        else "ambiguous"
        if len(matched_routes) > 1
        else "unresolved"
    )
    if not conversations_ready and status != "resolved":
        status = "blocked"
    return {
        "status": status,
        "reason": sidecar_reason if not conversations_ready else "",
        "phone_hint": str(phone_hint or ""),
        "recipient_digits": recipient_digits,
        "binding_id": str(getattr(binding, "binding_id", "") or ""),
        "principal_id": str(getattr(binding, "principal_id", "") or ""),
        "session_ref": _session_ref(binding, str(getattr(args, "session_ref", "") or "").strip()),
        "route_key": str(route.get("route_key") or "").strip(),
        "ai_key": str(route.get("ai_key") or "").strip(),
        "ai_name": str(route.get("ai_name") or "").strip(),
        "auto_reply_enabled": bool(route.get("auto_reply_enabled")) if route else False,
        "chat_ref": chat_ref,
        "registered": bool(recipient_payload.get("registered")),
        "resolution_method": str(recipient_payload.get("resolution_method") or "").strip(),
        "chat_id_kind": str(recipient_payload.get("chat_id_kind") or "").strip(),
        "conversation_lookup_ready": conversations_ready,
        "conversation_lookup_status": str(conversations_payload.get("status") or "").strip(),
        "conversation_lookup_status_code": int(conversations_payload.get("status_code") or 0),
        "candidate_count": len(matched_routes),
        "candidates": [
            {
                "route_key": str(item.get("route_key") or "").strip(),
                "inbound_number_digits": str(item.get("inbound_number_digits") or "").strip(),
                "ai_key": str(item.get("ai_key") or "").strip(),
                "ai_name": str(item.get("ai_name") or "").strip(),
            }
            for item in matched_routes[:5]
        ],
    }


def _operator_whatsapp_sidecar_body(*, resolution: dict[str, object], text: str) -> dict[str, object]:
    body: dict[str, object] = {
        "text": str(text or ""),
        "pre_reply_delay_min_seconds": 0,
        "pre_reply_delay_max_seconds": 0,
        "typing_delay_ms": 0,
        "typing_delay_ms_per_character": 0,
        "typing_status_enabled": False,
    }
    chat_ref = str(resolution.get("chat_ref") or "").strip()
    recipient_digits = str(resolution.get("recipient_digits") or "").strip()
    if chat_ref:
        body["chat_ref"] = chat_ref
    elif recipient_digits:
        body["to"] = recipient_digits
    return body


def send_whatsapp(*, phone_hint: str, text: str, args: argparse.Namespace) -> dict[str, object]:
    resolution = resolve_whatsapp(phone_hint, args=args)
    binding = _load_whatsapp_binding(args)
    recipient_digits = str(resolution.get("recipient_digits") or "").strip()
    chat_ref = str(resolution.get("chat_ref") or "").strip()
    if not recipient_digits:
        return {
            "sent": False,
            "reason": "recipient_unresolved",
            "resolution": resolution,
        }
    if bool(getattr(args, "dry_run", False)):
        return {
            "sent": False,
            "reason": "dry_run",
            "resolution": resolution,
            "binding_id": str(getattr(binding, "binding_id", "") or ""),
            "principal_id": str(getattr(binding, "principal_id", "") or ""),
            "recipient_digits": recipient_digits,
        }
    payload = _sidecar_post(
        binding=binding,
        suffix="messages",
        body=_operator_whatsapp_sidecar_body(resolution=resolution, text=text),
        session_api_base_url=str(getattr(args, "session_api_base_url", "") or "").strip(),
        session_ref=str(getattr(args, "session_ref", "") or "").strip(),
        timeout_seconds=float(getattr(args, "timeout_seconds", 15.0) or 15.0),
    )
    if not bool(payload.get("ok", True)) and chat_ref and recipient_digits and str(payload.get("reason") or "").strip() == "chat_ref_not_found":
        payload = _sidecar_post(
            binding=binding,
            suffix="messages",
            body={
                "to": recipient_digits,
                "text": str(text or ""),
                "pre_reply_delay_min_seconds": 0,
                "pre_reply_delay_max_seconds": 0,
                "typing_delay_ms": 0,
                "typing_delay_ms_per_character": 0,
                "typing_status_enabled": False,
            },
            session_api_base_url=str(getattr(args, "session_api_base_url", "") or "").strip(),
            session_ref=str(getattr(args, "session_ref", "") or "").strip(),
            timeout_seconds=float(getattr(args, "timeout_seconds", 15.0) or 15.0),
        )
    message_ids = [str(value or "").strip() for value in payload.get("message_ids") or [] if str(value or "").strip()]
    return {
        "sent": bool(payload.get("ok", True)),
        "reason": "sent" if bool(payload.get("ok", True)) else str(payload.get("reason") or "send_failed").strip(),
        "binding_id": str(getattr(binding, "binding_id", "") or ""),
        "principal_id": str(getattr(binding, "principal_id", "") or ""),
        "recipient_digits": recipient_digits,
        "delivery_transport": "whatsapp_web_session_sidecar",
        "message_ids": message_ids,
        "request_url_present": True,
        "chat_ref_used": bool(chat_ref),
        "resolution": resolution,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generic EA live-ops provider probing and WhatsApp operator delivery.")
    parser.add_argument("--database-url", default=_env("DATABASE_URL"))
    parser.add_argument("--binding-json", default=_env("EA_WHATSAPP_WEB_READINESS_BINDING_JSON"))
    parser.add_argument("--binding-id", default=_env("EA_WHATSAPP_WEB_DEFAULT_BINDING_ID", "ea-whatsapp-web-session"))
    parser.add_argument(
        "--principal-id",
        default=_env("EA_WHATSAPP_WEB_DEFAULT_PRINCIPAL_ID") or _env("EA_WHATSAPP_DEFAULT_PRINCIPAL_ID", "principal-default"),
    )
    parser.add_argument("--session-api-base-url", default=_env("EA_WHATSAPP_WEB_SESSION_API_BASE_URL", DEFAULT_SESSION_API_BASE_URL))
    parser.add_argument("--session-ref", default=_env("EA_WHATSAPP_WEB_DEFAULT_SESSION_REF"))
    parser.add_argument("--timeout-seconds", type=float, default=15.0)
    subparsers = parser.add_subparsers(dest="command", required=True)

    probe = subparsers.add_parser("probe-provider", help="Probe a live provider state.")
    probe.add_argument("--provider", required=True)
    probe.add_argument("--format", choices=("json", "operator"), default="json")

    resolve = subparsers.add_parser("resolve-whatsapp", help="Resolve a WhatsApp recipient from a partial phone hint.")
    resolve.add_argument("--phone-hint", required=True)

    send = subparsers.add_parser("send-whatsapp", help="Send a factual operator update over WhatsApp Web.")
    send.add_argument("--phone-hint", required=True)
    send.add_argument("--text", required=True)
    send.add_argument("--dry-run", action="store_true")

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "probe-provider":
        report = probe_provider(args.provider, output_format=args.format)
        if args.format == "operator":
            print(str(report.get("operator_text") or ""))
        else:
            print(_json_dumps(report))
        return 0
    if args.command == "resolve-whatsapp":
        report = resolve_whatsapp(args.phone_hint, args=args)
        print(_json_dumps(report))
        return 0 if str(report.get("status") or "") == "resolved" else 2
    if args.command == "send-whatsapp":
        report = send_whatsapp(phone_hint=args.phone_hint, text=args.text, args=args)
        print(_json_dumps(report))
        return 0 if bool(report.get("sent")) or str(report.get("reason") or "") == "dry_run" else 2
    raise RuntimeError(f"unsupported_command:{args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
