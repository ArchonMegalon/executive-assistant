#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any


DEFAULT_SESSION_API_BASE_URL = "http://127.0.0.1:8098"
DEFAULT_SESSION_REF = "default-wa-web"
DEFAULT_HERTA_AI_KEY = "empathetic_slow_typing_old_lady"
DEFAULT_HERTA_AI_NAME = "Herta (Heyy Lady)"
DEFAULT_ROUTE_KEYS = "436647916419"
DEFAULT_PROMPT = (
    'Mei, ich prüf noch einmal den Herta-Weg. Schreib mir bitte "paßt live", '
    "dann antworte ich langsam als Herta. - Herta"
)
DEFAULT_HERTA_PRE_REPLY_DELAY_MIN_SECONDS = 180
DEFAULT_HERTA_PRE_REPLY_DELAY_MAX_SECONDS = 1800
DEFAULT_HERTA_QUIET_HOURS_START_HOUR = 21
DEFAULT_HERTA_QUIET_HOURS_END_HOUR = 6
DEFAULT_HERTA_TYPING_DELAY_MS = 6500
DEFAULT_HERTA_TYPING_DELAY_MS_PER_CHARACTER = 8000


def _env(name: str, default: str = "") -> str:
    return str(os.environ.get(name) or default).strip()


def _digits(value: object) -> str:
    return re.sub(r"\D+", "", str(value or ""))


def _parse_iso(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = f"{raw[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _route_keys(raw: str) -> list[str]:
    return [value.strip() for value in str(raw or "").split(",") if value.strip()]


def _message_time(message: dict[str, object]) -> datetime | None:
    return _parse_iso(
        message.get("received_at")
        or message.get("sent_at")
        or message.get("message_timestamp")
        or message.get("timestamp")
    )


def _after_cutoff(message: dict[str, object], cutoff: datetime | None) -> bool:
    if cutoff is None:
        return True
    message_time = _message_time(message)
    return message_time is not None and message_time >= cutoff


def _sidecar_url(base_url: str, session_ref: str, suffix: str) -> str:
    base = str(base_url or DEFAULT_SESSION_API_BASE_URL).rstrip("/")
    session = urllib.parse.quote(str(session_ref or DEFAULT_SESSION_REF).strip(), safe="")
    return f"{base}/sessions/{session}/{suffix.lstrip('/')}"


def _healthz_url(base_url: str) -> str:
    return f"{str(base_url or DEFAULT_SESSION_API_BASE_URL).rstrip('/')}/healthz"


def _get_json(*, base_url: str, session_ref: str, suffix: str, timeout_seconds: float) -> dict[str, Any]:
    with urllib.request.urlopen(_sidecar_url(base_url, session_ref, suffix), timeout=timeout_seconds) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return dict(payload) if isinstance(payload, dict) else {}


def _get_healthz_json(*, base_url: str, timeout_seconds: float) -> dict[str, Any]:
    with urllib.request.urlopen(_healthz_url(base_url), timeout=timeout_seconds) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return dict(payload) if isinstance(payload, dict) else {}


def _error_payload(exc: Exception) -> dict[str, object]:
    if isinstance(exc, urllib.error.HTTPError):
        try:
            payload = json.loads(exc.read().decode("utf-8") or "{}")
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        payload.setdefault("ok", False)
        payload.setdefault("reason", f"http_{exc.code}")
        payload["http_status"] = exc.code
        return payload
    return {"ok": False, "reason": type(exc).__name__, "error": str(exc)}


def sidecar_health_payload(*, base_url: str, timeout_seconds: float) -> dict[str, object]:
    try:
        return _get_healthz_json(base_url=base_url, timeout_seconds=timeout_seconds)
    except Exception as exc:
        return _error_payload(exc)


def sidecar_blocked_report(
    *,
    error_payload: dict[str, object],
    sent: dict[str, Any],
    session: dict[str, object],
    wait_seconds: float,
) -> dict[str, object]:
    reason = str(error_payload.get("reason") or "sidecar_request_failed").strip()
    return {
        **session,
        "failure_count": 1,
        "failures": [
            {
                "http_status": error_payload.get("http_status"),
                "reason": reason,
                "status": error_payload.get("status"),
            }
        ],
        "http_status": error_payload.get("http_status"),
        "ok": False,
        "reason": reason,
        "sent": sent,
        "sidecar_error": error_payload,
        "status": error_payload.get("status"),
        "wait_seconds": wait_seconds,
    }


def resolve_session_ref(
    *,
    base_url: str,
    configured_session_ref: str,
    timeout_seconds: float,
) -> dict[str, object]:
    configured = str(configured_session_ref or DEFAULT_SESSION_REF).strip() or DEFAULT_SESSION_REF
    health = sidecar_health_payload(base_url=base_url, timeout_seconds=timeout_seconds)
    health_ref = str(health.get("session_ref") or "").strip()
    if health_ref:
        return {
            "configured_session_ref": configured,
            "session_ref": health_ref,
            "session_ref_source": "sidecar_healthz",
            "sidecar_health_ok": bool(health.get("ok", True)),
            "sidecar_health_status": str(health.get("status") or "").strip(),
        }
    return {
        "configured_session_ref": configured,
        "session_ref": configured,
        "session_ref_source": "configured",
        "sidecar_health_ok": bool(health.get("ok")),
        "sidecar_health_reason": str(health.get("reason") or "").strip(),
        "sidecar_health_status": str(health.get("status") or "").strip(),
    }


def _post_json(
    *,
    base_url: str,
    session_ref: str,
    suffix: str,
    body: dict[str, object],
    timeout_seconds: float,
) -> dict[str, Any]:
    request = urllib.request.Request(
        _sidecar_url(base_url, session_ref, suffix),
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return dict(payload) if isinstance(payload, dict) else {}


def route_failures(
    routes_payload: dict[str, object],
    *,
    expected_ai_key: str,
    required_route_keys: list[str],
    expected_pre_reply_min_seconds: int,
    expected_pre_reply_max_seconds: int,
    expected_quiet_start_hour: int,
    expected_quiet_end_hour: int,
    expected_typing_delay_ms_per_character: int,
) -> list[dict[str, object]]:
    routes = routes_payload.get("routes") if isinstance(routes_payload.get("routes"), list) else []
    by_key = {str(route.get("route_key") or "").strip(): dict(route) for route in routes if isinstance(route, dict)}
    failures: list[dict[str, object]] = []
    expected_values = {
        "ai_key": expected_ai_key,
        "pre_reply_delay_min_seconds": expected_pre_reply_min_seconds,
        "pre_reply_delay_max_seconds": expected_pre_reply_max_seconds,
        "quiet_hours_start_hour": expected_quiet_start_hour,
        "quiet_hours_end_hour": expected_quiet_end_hour,
        "typing_delay_ms_per_character": expected_typing_delay_ms_per_character,
    }
    for route_key in required_route_keys:
        route = by_key.get(route_key)
        if not route:
            failures.append({"reason": "required_route_missing", "route_key": route_key})
            continue
        mismatches = {
            key: {"actual": route.get(key), "expected": expected_value}
            for key, expected_value in expected_values.items()
            if route.get(key) != expected_value
        }
        if mismatches:
            failures.append({"mismatches": mismatches, "reason": "required_route_mismatch", "route_key": route_key})
    return failures


def messages_from_payloads(
    inbox_payload: dict[str, object],
    conversations_payload: dict[str, object],
) -> list[dict[str, object]]:
    messages: list[dict[str, object]] = []
    for message in inbox_payload.get("messages") or []:
        if isinstance(message, dict):
            messages.append(dict(message))
    for conversation in conversations_payload.get("conversations") or []:
        if not isinstance(conversation, dict):
            continue
        for message in conversation.get("messages") or []:
            if isinstance(message, dict):
                messages.append(dict(message))
    return messages


def find_matching_inbound(
    messages: list[dict[str, object]],
    *,
    cutoff: datetime | None,
    expected_sender_digits: str,
    expected_ai_key: str,
    body_contains: str,
) -> dict[str, object]:
    expected_sender = _digits(expected_sender_digits)
    needle = str(body_contains or "").strip().lower()
    candidates: list[dict[str, object]] = []
    for message in messages:
        if str(message.get("direction") or "").strip() != "inbound":
            continue
        if bool(message.get("from_me")):
            continue
        if not _after_cutoff(message, cutoff):
            continue
        if expected_sender and _digits(message.get("sender_digits")) != expected_sender:
            continue
        if str(message.get("heyy_ai_key") or "").strip() != expected_ai_key:
            continue
        if message.get("heyy_ai_route_matched") is False:
            continue
        if needle and needle not in str(message.get("body_text") or "").lower():
            continue
        candidates.append(message)
    candidates.sort(key=lambda item: _message_time(item) or datetime.min.replace(tzinfo=timezone.utc))
    return candidates[-1] if candidates else {}


def find_matching_auto_reply(
    outbox_payload: dict[str, object],
    *,
    cutoff: datetime | None,
    expected_ai_key: str,
) -> dict[str, object]:
    candidates: list[dict[str, object]] = []
    for message in outbox_payload.get("messages") or []:
        if not isinstance(message, dict):
            continue
        if str(message.get("origin") or "").strip() != "auto_reply":
            continue
        if not _after_cutoff(message, cutoff):
            continue
        if str(message.get("heyy_ai_key") or "").strip() != expected_ai_key:
            continue
        if not bool(message.get("body_present")):
            continue
        candidates.append(dict(message))
    candidates.sort(key=lambda item: _message_time(item) or datetime.min.replace(tzinfo=timezone.utc))
    return candidates[-1] if candidates else {}


def verify_snapshot(
    *,
    status_payload: dict[str, object],
    routes_payload: dict[str, object],
    inbox_payload: dict[str, object],
    outbox_payload: dict[str, object],
    conversations_payload: dict[str, object],
    cutoff: datetime | None,
    expected_ai_key: str,
    required_route_keys: list[str],
    expected_sender_digits: str,
    body_contains: str,
    require_auto_reply: bool,
) -> dict[str, object]:
    failures: list[dict[str, object]] = []
    if not bool(status_payload.get("ready")) or str(status_payload.get("status") or "") != "ready":
        failures.append({"reason": "session_not_ready", "status": status_payload.get("status")})
    if not bool(status_payload.get("auto_reply_enabled")):
        failures.append({"reason": "auto_reply_disabled"})
    failures.extend(
        route_failures(
            routes_payload,
            expected_ai_key=expected_ai_key,
            required_route_keys=required_route_keys,
            expected_pre_reply_min_seconds=DEFAULT_HERTA_PRE_REPLY_DELAY_MIN_SECONDS,
            expected_pre_reply_max_seconds=DEFAULT_HERTA_PRE_REPLY_DELAY_MAX_SECONDS,
            expected_quiet_start_hour=DEFAULT_HERTA_QUIET_HOURS_START_HOUR,
            expected_quiet_end_hour=DEFAULT_HERTA_QUIET_HOURS_END_HOUR,
            expected_typing_delay_ms_per_character=DEFAULT_HERTA_TYPING_DELAY_MS_PER_CHARACTER,
        )
    )
    messages = messages_from_payloads(inbox_payload, conversations_payload)
    inbound = find_matching_inbound(
        messages,
        cutoff=cutoff,
        expected_sender_digits=expected_sender_digits,
        expected_ai_key=expected_ai_key,
        body_contains=body_contains,
    )
    if not inbound:
        failures.append({"reason": "matching_inbound_not_seen"})
    inbound_time = _message_time(inbound) if inbound else cutoff
    auto_reply = find_matching_auto_reply(
        outbox_payload,
        cutoff=inbound_time or cutoff,
        expected_ai_key=expected_ai_key,
    )
    if require_auto_reply and not auto_reply:
        failures.append({"reason": "matching_auto_reply_not_seen"})
    return {
        "auto_reply": auto_reply,
        "cutoff": cutoff.isoformat().replace("+00:00", "Z") if cutoff else "",
        "failure_count": len(failures),
        "failures": failures,
        "inbound": inbound,
        "ok": not failures,
        "route_count": routes_payload.get("route_count"),
        "session_ready": bool(status_payload.get("ready")),
    }


def fetch_snapshot(args: argparse.Namespace, *, session_ref: str = "") -> dict[str, dict[str, Any]]:
    base_url = str(args.session_api_base_url or DEFAULT_SESSION_API_BASE_URL).strip()
    effective_session_ref = str(session_ref or args.session_ref or DEFAULT_SESSION_REF).strip()
    timeout_seconds = float(args.request_timeout_seconds)
    conversation_suffix = (
        f"conversations?take={max(1, int(args.conversation_take))}"
        f"&messages={max(1, int(args.conversation_message_limit))}"
        f"&fetch_timeout_ms={max(1000, int(args.conversation_fetch_timeout_ms))}"
    )
    return {
        "status": _get_json(base_url=base_url, session_ref=effective_session_ref, suffix="status", timeout_seconds=timeout_seconds),
        "routes": _get_json(base_url=base_url, session_ref=effective_session_ref, suffix="heyy-ai-routes", timeout_seconds=timeout_seconds),
        "inbox": _get_json(base_url=base_url, session_ref=effective_session_ref, suffix="messages?take=100", timeout_seconds=timeout_seconds),
        "outbox": _get_json(base_url=base_url, session_ref=effective_session_ref, suffix="outbox?take=100", timeout_seconds=timeout_seconds),
        "conversations": _get_json(base_url=base_url, session_ref=effective_session_ref, suffix=conversation_suffix, timeout_seconds=timeout_seconds),
    }


def send_prompt(args: argparse.Namespace, *, session_ref: str = "") -> dict[str, Any]:
    body = {
        "heyy_ai_key": str(args.expected_ai_key or DEFAULT_HERTA_AI_KEY),
        "heyy_ai_name": DEFAULT_HERTA_AI_NAME,
        "pre_reply_delay_max_seconds": DEFAULT_HERTA_PRE_REPLY_DELAY_MAX_SECONDS,
        "pre_reply_delay_min_seconds": DEFAULT_HERTA_PRE_REPLY_DELAY_MIN_SECONDS,
        "quiet_hours_end_hour": DEFAULT_HERTA_QUIET_HOURS_END_HOUR,
        "quiet_hours_start_hour": DEFAULT_HERTA_QUIET_HOURS_START_HOUR,
        "text": str(args.send_text or DEFAULT_PROMPT),
        "to": str(args.recipient or "").strip(),
        "typing_delay_ms": DEFAULT_HERTA_TYPING_DELAY_MS,
        "typing_delay_ms_per_character": DEFAULT_HERTA_TYPING_DELAY_MS_PER_CHARACTER,
        "typing_status_enabled": True,
    }
    return _post_json(
        base_url=str(args.session_api_base_url or DEFAULT_SESSION_API_BASE_URL).strip(),
        session_ref=str(session_ref or args.session_ref or DEFAULT_SESSION_REF).strip(),
        suffix="messages",
        body=body,
        timeout_seconds=float(args.send_timeout_seconds),
    )


def run(args: argparse.Namespace) -> dict[str, object]:
    base_url = str(args.session_api_base_url or DEFAULT_SESSION_API_BASE_URL).strip()
    session = resolve_session_ref(
        base_url=base_url,
        configured_session_ref=str(args.session_ref or DEFAULT_SESSION_REF).strip(),
        timeout_seconds=float(args.request_timeout_seconds),
    )
    session_ref = str(session.get("session_ref") or DEFAULT_SESSION_REF).strip()
    cutoff = _parse_iso(args.since)
    sent: dict[str, Any] = {}
    wait_seconds = max(0.0, float(args.wait_seconds))
    if args.send:
        if not str(args.recipient or "").strip():
            return {"ok": False, "reason": "recipient_required"}
        cutoff = _parse_iso(_iso_now())
        try:
            sent = send_prompt(args, session_ref=session_ref)
        except Exception as exc:
            return sidecar_blocked_report(
                error_payload=_error_payload(exc),
                sent=sent,
                session=session,
                wait_seconds=wait_seconds,
            )
    elif cutoff is None:
        cutoff = _parse_iso(_iso_now())

    deadline = time.monotonic() + wait_seconds
    report: dict[str, object] = {}
    while True:
        try:
            snapshot = fetch_snapshot(args, session_ref=session_ref)
        except Exception as exc:
            return sidecar_blocked_report(
                error_payload=_error_payload(exc),
                sent=sent,
                session=session,
                wait_seconds=wait_seconds,
            )
        report = verify_snapshot(
            status_payload=snapshot["status"],
            routes_payload=snapshot["routes"],
            inbox_payload=snapshot["inbox"],
            outbox_payload=snapshot["outbox"],
            conversations_payload=snapshot["conversations"],
            cutoff=cutoff,
            expected_ai_key=str(args.expected_ai_key or DEFAULT_HERTA_AI_KEY),
            required_route_keys=_route_keys(args.required_route_keys),
            expected_sender_digits=str(args.expected_sender_digits or ""),
            body_contains=str(args.body_contains or ""),
            require_auto_reply=not bool(args.no_require_auto_reply),
        )
        report.update(session)
        report["sent"] = sent
        report["wait_seconds"] = wait_seconds
        if bool(report.get("ok")) or time.monotonic() >= deadline:
            return report
        time.sleep(max(1.0, float(args.poll_interval_seconds)))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify the live Herta WhatsApp Web route end to end.")
    parser.add_argument("--session-api-base-url", default=_env("EA_WHATSAPP_WEB_SESSION_API_BASE_URL", DEFAULT_SESSION_API_BASE_URL))
    parser.add_argument("--session-ref", default=_env("EA_WHATSAPP_WEB_DEFAULT_SESSION_REF", DEFAULT_SESSION_REF))
    parser.add_argument("--recipient", default=_env("EA_WHATSAPP_WEB_LIVE_TEST_RECIPIENT"))
    parser.add_argument("--send", action="store_true")
    parser.add_argument("--send-text", default=_env("EA_WHATSAPP_WEB_HERTA_LIVE_TEST_TEXT", DEFAULT_PROMPT))
    parser.add_argument("--since", default="")
    parser.add_argument("--wait-seconds", type=float, default=float(_env("EA_WHATSAPP_WEB_HERTA_E2E_WAIT_SECONDS", "1200") or "1200"))
    parser.add_argument("--poll-interval-seconds", type=float, default=5.0)
    parser.add_argument("--request-timeout-seconds", type=float, default=30.0)
    parser.add_argument("--send-timeout-seconds", type=float, default=960.0)
    parser.add_argument("--conversation-take", type=int, default=5)
    parser.add_argument("--conversation-message-limit", type=int, default=40)
    parser.add_argument("--conversation-fetch-timeout-ms", type=int, default=15000)
    parser.add_argument("--expected-ai-key", default=DEFAULT_HERTA_AI_KEY)
    parser.add_argument("--expected-sender-digits", default=_env("EA_WHATSAPP_WEB_HERTA_EXPECTED_SENDER_DIGITS", "436647916419"))
    parser.add_argument("--required-route-keys", default=_env("EA_WHATSAPP_WEB_HERTA_REQUIRED_ROUTE_KEYS", DEFAULT_ROUTE_KEYS))
    parser.add_argument("--body-contains", default=_env("EA_WHATSAPP_WEB_HERTA_E2E_BODY_CONTAINS", "passt live"))
    parser.add_argument("--no-require-auto-reply", action="store_true")
    return parser.parse_args()


def main() -> int:
    report = run(parse_args())
    print(json.dumps(report, sort_keys=True, ensure_ascii=False))
    return 0 if bool(report.get("ok")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
