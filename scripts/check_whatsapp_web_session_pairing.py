#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT / "ea", ROOT):
    if path.exists() and str(path) not in sys.path:
        sys.path.insert(0, str(path))


def _env(name: str, default: str = "") -> str:
    return str(os.environ.get(name) or default).strip()


def _auth_header(args: argparse.Namespace) -> dict[str, str]:
    token = str(args.session_api_token or "").strip()
    if not token:
        return {}
    name = str(args.auth_header_name or "Authorization").strip() or "Authorization"
    prefix = str(args.auth_header_prefix if args.auth_header_prefix is not None else "Bearer ")
    return {name: f"{prefix}{token}".strip()}


def _request_json(url: str, args: argparse.Namespace) -> tuple[int, dict[str, object]]:
    request = urllib.request.Request(url, method="GET", headers=_auth_header(args))
    try:
        with urllib.request.urlopen(request, timeout=max(float(args.timeout_seconds or 5.0), 0.1)) as response:
            status_code = int(getattr(response, "status", 200) or 200)
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8") or "{}")
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}
        return int(getattr(exc, "code", 500) or 500), body
    except Exception as exc:
        return 0, {"ok": False, "reason": type(exc).__name__}
    try:
        parsed = json.loads(raw or "{}")
    except Exception:
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}
    return status_code, parsed


def _base_url(args: argparse.Namespace) -> str:
    return str(args.session_api_base_url or "").strip().rstrip("/")


def _session_url(args: argparse.Namespace, suffix: str) -> str:
    base = _base_url(args)
    session_ref = urllib.parse.quote(str(args.session_ref or "").strip(), safe="")
    if not base or not session_ref:
        return ""
    return f"{base}/sessions/{session_ref}/{suffix.lstrip('/')}"


def build_report(args: argparse.Namespace) -> dict[str, object]:
    session_ref = str(args.session_ref or "").strip()
    base = {
        "include_qr": bool(args.include_qr),
        "session_ref": session_ref,
    }
    if not session_ref:
        return {**base, "ok": False, "reason": "session_ref_required"}
    if not _base_url(args):
        return {**base, "ok": False, "reason": "session_api_base_url_required"}

    status_code, status_payload = _request_json(_session_url(args, "status"), args)
    qr_url = _session_url(args, "qr")
    if bool(args.include_qr):
        qr_url = f"{qr_url}?include=1"
    qr_status, qr_payload = _request_json(qr_url, args)

    report: dict[str, object] = {
        **base,
        "ok": status_code == 200 and qr_status == 200,
        "qr_last_seen_at": str(qr_payload.get("last_qr_at") or status_payload.get("last_qr_at") or ""),
        "qr_present": bool(qr_payload.get("qr_present")),
        "qr_required": bool(qr_payload.get("qr_required")) or bool(status_payload.get("qr_required")),
        "ready": bool(status_payload.get("ready")),
        "sidecar_status": str(status_payload.get("status") or qr_payload.get("status") or ""),
        "status_code": status_code,
        "qr_status_code": qr_status,
    }
    if not report["ok"]:
        report["reason"] = str(status_payload.get("reason") or qr_payload.get("reason") or "sidecar_request_failed")
    elif bool(args.include_qr):
        report["qr"] = str(qr_payload.get("qr") or "")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check the local WhatsApp Web sidecar pairing state.")
    parser.add_argument("--session-api-base-url", default=_env("EA_WHATSAPP_WEB_SESSION_API_BASE_URL", "http://127.0.0.1:8098"))
    parser.add_argument("--session-ref", default=_env("EA_WHATSAPP_WEB_DEFAULT_SESSION_REF", "default-wa-web"))
    parser.add_argument("--session-api-token", default=_env("EA_WHATSAPP_WEB_SESSION_API_TOKEN"))
    parser.add_argument("--auth-header-name", default=_env("EA_WHATSAPP_WEB_SESSION_AUTH_HEADER_NAME", "Authorization"))
    parser.add_argument("--auth-header-prefix", default=_env("EA_WHATSAPP_WEB_SESSION_AUTH_HEADER_PREFIX", "Bearer "))
    parser.add_argument("--timeout-seconds", type=float, default=float(_env("EA_WHATSAPP_WEB_SESSION_REQUEST_TIMEOUT_SECONDS", "15") or "15"))
    parser.add_argument("--include-qr", action="store_true", help="Include the raw QR payload. Treat output as sensitive.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_report(args)
    print(json.dumps(report, sort_keys=True))
    return 0 if bool(report.get("ok")) else 2


if __name__ == "__main__":
    raise SystemExit(main())
