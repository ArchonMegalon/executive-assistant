#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Callable


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts"
for path in (ROOT / "ea", ROOT, SCRIPT_DIR):
    if path.exists() and str(path) not in sys.path:
        sys.path.insert(0, str(path))

import activate_whatsapp_web_session as activation  # noqa: E402
import bootstrap_whatsapp_web_session_account as bootstrap  # noqa: E402


SENSITIVE_KEYS = {
    "authorization",
    "auth_header",
    "qr",
    "raw_qr",
    "session_api_token",
    "token",
}


def _env(name: str, default: str = "") -> str:
    return str(os.environ.get(name) or default).strip()


def _env_bool(name: str, default: str = "0") -> bool:
    return _env(name, default).lower() in {"1", "true", "yes", "on"}


def _default_principal_id() -> str:
    return activation._default_principal_id()


def _redact(value: object) -> object:
    if isinstance(value, dict):
        redacted: dict[str, object] = {}
        for key, item in value.items():
            normalized = str(key or "").strip().lower()
            if normalized in SENSITIVE_KEYS or (
                normalized.endswith("_token") and not normalized.endswith("_token_present")
            ):
                redacted[str(key)] = "[redacted]" if item else ""
            else:
                redacted[str(key)] = _redact(item)
        return redacted
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _activation_args(args: argparse.Namespace) -> SimpleNamespace:
    return SimpleNamespace(
        auth_header_name=str(args.auth_header_name or "").strip(),
        auth_header_prefix=str(args.auth_header_prefix or "").strip(),
        binding_id=str(args.binding_id or "").strip(),
        browser_profile_ref=str(args.browser_profile_ref or "").strip(),
        database_url=str(args.database_url or "").strip(),
        display_name=str(args.display_name or "").strip(),
        dry_run=bool(args.dry_run),
        email=str(args.email or "").strip(),
        phone_number=str(args.phone_number or "").strip(),
        poll_interval_seconds=0,
        principal_id=str(args.principal_id or "").strip(),
        probe_session=bool(args.probe_session),
        recipient=str(args.recipient or "").strip(),
        send_test=bool(args.send_test),
        session_api_base_url=str(args.session_api_base_url or "").strip(),
        session_api_token=str(args.session_api_token or "").strip(),
        session_label=str(args.session_label or "").strip(),
        session_ref=str(args.session_ref or "").strip(),
        session_send_url_template=str(args.session_send_url_template or "").strip(),
        session_status_url_template=str(args.session_status_url_template or "").strip(),
        session_store_ref=str(args.session_store_ref or "").strip(),
        tenant_id=str(args.tenant_id or "").strip(),
        tenant_name=str(args.tenant_name or "").strip(),
        tenant_slug=str(args.tenant_slug or "").strip(),
        text=str(args.text or "").strip(),
        timeout_seconds=max(float(args.timeout_seconds or 5.0), 0.1),
        wait_seconds=0,
    )


def _event_from_report(report: dict[str, object], *, attempt: int) -> dict[str, object]:
    return {
        **dict(_redact(report)),
        "attempt": attempt,
        "event": "whatsapp_web_session_activation_attempt",
    }


def _run_activation(args: argparse.Namespace) -> dict[str, object]:
    try:
        return activation.build_report(_activation_args(args))
    except Exception as exc:
        return {
            "activated": False,
            "binding_id": str(args.binding_id or "").strip(),
            "delivery_transport": "whatsapp_web_session",
            "error_type": type(exc).__name__,
            "principal_id": str(args.principal_id or "").strip(),
            "reason": "activation_exception",
            "session_ref": str(args.session_ref or "").strip(),
        }


def _report_with_watch_status(args: argparse.Namespace, report: dict[str, object]) -> dict[str, object]:
    if not bool(args.send_test) or not bool(report.get("activated")):
        return report
    live_send = report.get("live_send")
    live_send_report = live_send if isinstance(live_send, dict) else {}
    if bool(live_send_report.get("sent")):
        return report
    adjusted = dict(report)
    adjusted["activated"] = False
    adjusted["activation_reason"] = str(report.get("reason") or "")
    adjusted["binding_activated"] = True
    adjusted["live_send_reason"] = str(live_send_report.get("reason") or "live_send_missing")
    adjusted["reason"] = "live_send_pending"
    return adjusted


def _timeout_reached(*, start: float, now: float, max_seconds: float, once: bool) -> bool:
    if once:
        return True
    if max_seconds <= 0:
        return False
    return now - start >= max_seconds


def build_report(
    args: argparse.Namespace,
    *,
    emit: Callable[[dict[str, object]], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, object]:
    interval = max(float(args.interval_seconds or 5.0), 0.1)
    max_seconds = max(float(args.max_seconds or 0.0), 0.0)
    started = clock()
    attempts = 0
    last_event: dict[str, object] = {}

    while True:
        attempts += 1
        raw_report = _report_with_watch_status(args, _run_activation(args))
        event = _event_from_report(raw_report, attempt=attempts)
        last_event = event
        if emit is not None:
            emit(event)

        if bool(raw_report.get("activated")):
            return {
                "activated": True,
                "attempts": attempts,
                "binding_id": str(raw_report.get("binding_id") or args.binding_id or ""),
                "delivery_transport": "whatsapp_web_session",
                "last_activation": last_event,
                "principal_id": str(raw_report.get("principal_id") or args.principal_id or ""),
                "reason": "activated",
                "session_ref": str(raw_report.get("session_ref") or args.session_ref or ""),
                "watch_max_seconds": max_seconds,
            }

        now = clock()
        if _timeout_reached(start=started, now=now, max_seconds=max_seconds, once=bool(args.once)):
            reason = "watch_timeout" if max_seconds > 0 and not bool(args.once) else str(raw_report.get("reason") or "not_activated")
            return {
                "activated": False,
                "attempts": attempts,
                "binding_id": str(raw_report.get("binding_id") or args.binding_id or ""),
                "delivery_transport": "whatsapp_web_session",
                "last_activation": last_event,
                "principal_id": str(raw_report.get("principal_id") or args.principal_id or ""),
                "reason": reason,
                "session_ref": str(raw_report.get("session_ref") or args.session_ref or ""),
                "watch_max_seconds": max_seconds,
            }

        sleep_seconds = interval
        if max_seconds > 0:
            remaining = max(max_seconds - (now - started), 0.0)
            sleep_seconds = min(interval, remaining)
        if sleep_seconds > 0:
            sleep(sleep_seconds)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Poll the WhatsApp Web sidecar and enable the EA binding once the browser session is ready."
    )
    parser.add_argument("--database-url", default=_env("DATABASE_URL"))
    parser.add_argument("--tenant-id", default=_env("EA_WHATSAPP_WEB_DEFAULT_TENANT_ID") or _env("EA_WHATSAPP_DEFAULT_TENANT_ID", bootstrap.DEFAULT_TENANT_ID))
    parser.add_argument("--tenant-name", default=_env("EA_WHATSAPP_WEB_DEFAULT_TENANT_NAME") or _env("EA_WHATSAPP_DEFAULT_TENANT_NAME", bootstrap.DEFAULT_TENANT_NAME))
    parser.add_argument("--tenant-slug", default=_env("EA_WHATSAPP_WEB_DEFAULT_TENANT_SLUG") or _env("EA_WHATSAPP_DEFAULT_TENANT_SLUG", bootstrap.DEFAULT_TENANT_SLUG))
    parser.add_argument("--principal-id", default=_default_principal_id())
    parser.add_argument("--display-name", default=_env("EA_WHATSAPP_WEB_DEFAULT_DISPLAY_NAME") or _env("EA_WHATSAPP_DEFAULT_DISPLAY_NAME", bootstrap.DEFAULT_DISPLAY_NAME))
    parser.add_argument("--email", default=_env("EA_WHATSAPP_WEB_DEFAULT_EMAIL") or _env("EA_WHATSAPP_DEFAULT_EMAIL", bootstrap.DEFAULT_EMAIL))
    parser.add_argument("--phone-number", default=_env("EA_WHATSAPP_WEB_DEFAULT_PHONE_NUMBER") or _env("EA_WHATSAPP_DEFAULT_BUSINESS_PHONE_NUMBER", bootstrap.DEFAULT_PHONE_NUMBER))
    parser.add_argument("--session-label", default=_env("EA_WHATSAPP_WEB_DEFAULT_SESSION_LABEL", bootstrap.DEFAULT_SESSION_LABEL))
    parser.add_argument("--binding-id", default=_env("EA_WHATSAPP_WEB_DEFAULT_BINDING_ID", bootstrap.DEFAULT_BINDING_ID))
    parser.add_argument("--session-ref", default=_env("EA_WHATSAPP_WEB_DEFAULT_SESSION_REF"))
    parser.add_argument("--session-store-ref", default=_env("EA_WHATSAPP_WEB_DEFAULT_SESSION_STORE_REF"))
    parser.add_argument("--browser-profile-ref", default=_env("EA_WHATSAPP_WEB_DEFAULT_BROWSER_PROFILE_REF"))
    parser.add_argument("--session-api-base-url", default=_env("EA_WHATSAPP_WEB_SESSION_API_BASE_URL"))
    parser.add_argument("--session-send-url-template", default=_env("EA_WHATSAPP_WEB_SESSION_SEND_URL_TEMPLATE"))
    parser.add_argument("--session-status-url-template", default=_env("EA_WHATSAPP_WEB_SESSION_STATUS_URL_TEMPLATE"))
    parser.add_argument("--session-api-token", default=_env("EA_WHATSAPP_WEB_SESSION_API_TOKEN"))
    parser.add_argument("--auth-header-name", default=_env("EA_WHATSAPP_WEB_SESSION_AUTH_HEADER_NAME", "Authorization"))
    parser.add_argument("--auth-header-prefix", default=_env("EA_WHATSAPP_WEB_SESSION_AUTH_HEADER_PREFIX", "Bearer "))
    parser.add_argument("--timeout-seconds", type=float, default=float(_env("EA_WHATSAPP_WEB_SESSION_REQUEST_TIMEOUT_SECONDS", "15") or "15"))
    parser.add_argument("--interval-seconds", type=float, default=float(_env("EA_WHATSAPP_WEB_ACTIVATION_WATCH_INTERVAL_SECONDS", "5") or "5"))
    parser.add_argument("--max-seconds", type=float, default=float(_env("EA_WHATSAPP_WEB_ACTIVATION_WATCH_MAX_SECONDS", "0") or "0"))
    parser.add_argument("--probe-session", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--send-test", action="store_true", default=_env_bool("EA_WHATSAPP_WEB_ACTIVATION_SEND_TEST", "0"))
    parser.add_argument("--recipient", default=_env("EA_WHATSAPP_WEB_LIVE_TEST_RECIPIENT"))
    parser.add_argument("--text", default=_env("EA_WHATSAPP_WEB_LIVE_TEST_TEXT", "EA WhatsApp Web live delivery test"))
    parser.add_argument("--once", action="store_true", help="Run one activation attempt and exit.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    def _emit(event: dict[str, object]) -> None:
        print(json.dumps(event, sort_keys=True), flush=True)

    report = build_report(args, emit=_emit)
    print(json.dumps({"event": "whatsapp_web_session_activation_watch_complete", **report}, sort_keys=True))
    return 0 if bool(report.get("activated")) else 2


if __name__ == "__main__":
    raise SystemExit(main())
