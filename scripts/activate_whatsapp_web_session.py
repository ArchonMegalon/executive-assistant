#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts"
for path in (ROOT / "ea", ROOT, SCRIPT_DIR):
    if path.exists() and str(path) not in sys.path:
        sys.path.insert(0, str(path))

import bootstrap_whatsapp_web_session_account as bootstrap  # noqa: E402
import check_whatsapp_web_session_readiness as readiness_script  # noqa: E402
import send_whatsapp_web_session_live_test as live_send_script  # noqa: E402


def _env(name: str, default: str = "") -> str:
    return str(os.environ.get(name) or default).strip()


def _default_principal_id() -> str:
    return readiness_script._default_principal_id()


def _format_template(template: str, *, session_ref: str, binding_id: str, principal_id: str) -> str:
    return str(template or "").format(
        session_ref=session_ref,
        binding_id=binding_id,
        principal_id=principal_id,
    )


def _status_url(args: argparse.Namespace) -> str:
    session_ref = str(args.session_ref or "").strip()
    template = str(args.session_status_url_template or "").strip()
    if template:
        return _format_template(
            template,
            session_ref=session_ref,
            binding_id=str(args.binding_id or "").strip(),
            principal_id=str(args.principal_id or "").strip(),
        )
    base_url = str(args.session_api_base_url or "").strip().rstrip("/")
    if not base_url:
        return ""
    return f"{base_url}/sessions/{session_ref}/status"


def _auth_header(args: argparse.Namespace) -> dict[str, str]:
    token = str(args.session_api_token or "").strip()
    if not token:
        return {}
    name = str(args.auth_header_name or "Authorization").strip() or "Authorization"
    prefix = str(args.auth_header_prefix if args.auth_header_prefix is not None else "Bearer ")
    return {name: f"{prefix}{token}".strip()}


def _sidecar_status(args: argparse.Namespace) -> dict[str, object]:
    request_url = _status_url(args)
    if not request_url:
        return {"ok": False, "reason": "status_url_missing"}
    request = urllib.request.Request(request_url, method="GET", headers=_auth_header(args))
    try:
        with urllib.request.urlopen(request, timeout=max(float(args.timeout_seconds or 5.0), 0.1)) as response:
            status_code = int(getattr(response, "status", 200) or 200)
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return {"ok": False, "reason": f"http_{int(getattr(exc, 'code', 500) or 500)}"}
    except Exception as exc:
        return {"ok": False, "reason": type(exc).__name__}
    if status_code >= 400:
        return {"ok": False, "reason": f"http_{status_code}"}
    try:
        parsed = json.loads(body or "{}")
    except Exception:
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}
    state = str(parsed.get("status") or parsed.get("state") or "").strip()
    return {
        "ok": True,
        "ready": bool(parsed.get("ready")),
        "authenticated": bool(parsed.get("authenticated")),
        "qr_required": bool(parsed.get("qr_required")) or state == "qr_required",
        "session_ref": str(parsed.get("session_ref") or "").strip(),
        "status": state,
    }


def _wait_for_sidecar(args: argparse.Namespace) -> dict[str, object]:
    deadline = time.monotonic() + max(float(args.wait_seconds or 0.0), 0.0)
    interval = max(float(args.poll_interval_seconds or 2.0), 0.1)
    while True:
        status = _sidecar_status(args)
        if bool(status.get("ok")) and bool(status.get("ready")):
            return status
        if time.monotonic() >= deadline:
            return status
        time.sleep(interval)


def _bootstrap_args(args: argparse.Namespace, *, connector_status: str) -> SimpleNamespace:
    return SimpleNamespace(
        auth_header_name=str(args.auth_header_name or "").strip(),
        auth_header_prefix=str(args.auth_header_prefix or "").strip(),
        binding_id=str(args.binding_id or "").strip(),
        browser_profile_ref=str(args.browser_profile_ref or "").strip(),
        connector_status=connector_status,
        display_name=str(args.display_name or "").strip(),
        email=str(args.email or "").strip(),
        phone_number=str(args.phone_number or "").strip(),
        principal_id=str(args.principal_id or "").strip(),
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
    )


def _readiness_report(args: argparse.Namespace) -> dict[str, object]:
    return readiness_script.build_report(
        SimpleNamespace(
            binding_json="",
            database_url=str(args.database_url or "").strip(),
            binding_id=str(args.binding_id or "").strip(),
            principal_id=str(args.principal_id or "").strip(),
            probe_session=bool(args.probe_session),
        )
    )


def _live_send_report(args: argparse.Namespace) -> dict[str, object]:
    return live_send_script.build_report(
        SimpleNamespace(
            binding_json="",
            database_url=str(args.database_url or "").strip(),
            binding_id=str(args.binding_id or "").strip(),
            principal_id=str(args.principal_id or "").strip(),
            recipient=str(args.recipient or "").strip(),
            text=str(args.text or "").strip(),
            probe_session=bool(args.probe_session),
            dry_run=False,
        )
    )


def build_report(args: argparse.Namespace) -> dict[str, object]:
    binding_id = str(args.binding_id or "").strip()
    principal_id = str(args.principal_id or "").strip()
    session_ref = str(args.session_ref or "").strip()
    base = {
        "binding_id": binding_id,
        "delivery_transport": "whatsapp_web_session",
        "principal_id": principal_id,
        "session_ref": session_ref,
    }
    if not session_ref:
        return {**base, "activated": False, "reason": "session_ref_required"}
    if not str(args.database_url or "").strip() and not bool(args.dry_run):
        return {**base, "activated": False, "reason": "database_url_required"}

    sidecar = _wait_for_sidecar(args)
    sidecar_report = {
        "sidecar_authenticated": bool(sidecar.get("authenticated")),
        "sidecar_qr_required": bool(sidecar.get("qr_required")),
        "sidecar_ready": bool(sidecar.get("ready")),
        "sidecar_session_ref": str(sidecar.get("session_ref") or ""),
        "sidecar_status": str(sidecar.get("status") or ""),
    }
    if not bool(sidecar.get("ok")):
        return {
            **base,
            **sidecar_report,
            "activated": False,
            "reason": str(sidecar.get("reason") or "sidecar_status_failed"),
        }
    if not bool(sidecar.get("ready")):
        return {
            **base,
            **sidecar_report,
            "activated": False,
            "reason": "sidecar_not_ready",
        }

    try:
        seed = bootstrap.build_seed(_bootstrap_args(args, connector_status="enabled"))
    except Exception as exc:
        return {
            **base,
            **sidecar_report,
            "activated": False,
            "reason": str(exc or type(exc).__name__).split(":", 1)[0],
        }

    seed_summary = seed.sanitized_summary()
    if bool(args.dry_run):
        return {
            **base,
            **sidecar_report,
            "activated": False,
            "reason": "dry_run",
            "would_seed": True,
            "seed": seed_summary,
        }

    bootstrap.seed_postgres(str(args.database_url or "").strip(), seed)
    readiness = _readiness_report(args)
    report: dict[str, object] = {
        **base,
        **sidecar_report,
        "activated": bool(readiness.get("ready")),
        "reason": "activated" if bool(readiness.get("ready")) else "readiness_failed_after_seed",
        "readiness": readiness,
        "seed": seed_summary,
    }
    if bool(args.send_test):
        report["live_send"] = _live_send_report(args)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Enable the EA WhatsApp Web binding only after the sidecar session is ready.")
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
    parser.add_argument("--wait-seconds", type=float, default=float(_env("EA_WHATSAPP_WEB_ACTIVATE_WAIT_SECONDS", "0") or "0"))
    parser.add_argument("--poll-interval-seconds", type=float, default=float(_env("EA_WHATSAPP_WEB_ACTIVATE_POLL_INTERVAL_SECONDS", "2") or "2"))
    parser.add_argument("--probe-session", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--send-test", action="store_true")
    parser.add_argument("--recipient", default=_env("EA_WHATSAPP_WEB_LIVE_TEST_RECIPIENT"))
    parser.add_argument("--text", default=_env("EA_WHATSAPP_WEB_LIVE_TEST_TEXT", "EA WhatsApp Web live delivery test"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_report(args)
    print(json.dumps(report, sort_keys=True))
    return 0 if bool(report.get("activated")) or str(report.get("reason") or "") == "dry_run" else 2


if __name__ == "__main__":
    raise SystemExit(main())
