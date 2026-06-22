#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts"
for path in (ROOT / "ea", ROOT, SCRIPT_DIR):
    if path.exists() and str(path) not in sys.path:
        sys.path.insert(0, str(path))

import check_whatsapp_web_session_readiness as readiness_script  # noqa: E402
from app.services import whatsapp_web_session_delivery  # noqa: E402
from app.services.whatsapp_web_session_readiness import check_whatsapp_web_session_readiness  # noqa: E402


def _env(name: str, default: str = "") -> str:
    return str(os.environ.get(name) or default).strip()


def _load_binding(args: argparse.Namespace):
    binding_path = str(args.binding_json or "").strip()
    database_url = str(args.database_url or "").strip()
    binding_id = str(args.binding_id or "").strip()
    principal_id = str(args.principal_id or "").strip()
    if binding_path:
        path = Path(binding_path)
        if not path.exists():
            return None, "binding_json_not_found"
        try:
            payload = readiness_script._load_json_file(str(path))
        except Exception:
            return None, "binding_json_invalid"
        binding = readiness_script._binding_from_json(payload, binding_id=binding_id)
        if binding is None and readiness_script._should_fallback_to_latest_binding(
            binding_id=binding_id,
            principal_id=principal_id,
        ):
            binding = readiness_script._latest_enabled_binding_from_json(payload)
        return binding, ""
    if database_url:
        try:
            return readiness_script._binding_from_postgres(
                database_url,
                binding_id=binding_id,
                principal_id=principal_id,
            ), ""
        except Exception:
            return None, "database_lookup_failed"
    return None, "binding_json_or_database_url_required"


def _request_host(request_url: str) -> str:
    parsed = urlparse(str(request_url or ""))
    return str(parsed.netloc or "").strip()


def _base_report(args: argparse.Namespace) -> dict[str, object]:
    return {
        "binding_id": str(args.binding_id or "").strip(),
        "principal_id": str(args.principal_id or "").strip(),
        "delivery_transport": "whatsapp_web_session",
    }


def _safe_error_reason(exc: Exception) -> str:
    text = str(exc or "").strip()
    if not text:
        return type(exc).__name__
    return text.split(":", 1)[0]


def build_report(args: argparse.Namespace) -> dict[str, object]:
    binding, load_error = _load_binding(args)
    base = _base_report(args)
    if load_error:
        return {**base, "ready": False, "sent": False, "reason": load_error}
    if binding is None:
        return {**base, "ready": False, "sent": False, "reason": "binding_not_found"}

    effective_binding_id = str(getattr(binding, "binding_id", "") or args.binding_id).strip()
    effective_principal_id = str(getattr(binding, "principal_id", "") or args.principal_id).strip()
    readiness = check_whatsapp_web_session_readiness(
        tool_runtime=None,
        principal_id=effective_principal_id,
        binding_id=effective_binding_id,
        binding=binding,
        probe_session=bool(args.probe_session),
    )
    readiness_report = readiness.as_dict()
    if not readiness.ready:
        return {
            **base,
            **readiness_report,
            "sent": False,
        }

    recipient = str(args.recipient or "").strip()
    if not recipient:
        return {
            **base,
            **readiness_report,
            "sent": False,
            "reason": "recipient_required",
        }

    if bool(args.dry_run):
        return {
            **base,
            **readiness_report,
            "sent": False,
            "reason": "dry_run",
            "recipient_present": True,
        }

    try:
        receipt = whatsapp_web_session_delivery.send_whatsapp_web_session_text(
            tool_runtime=None,
            principal_id=effective_principal_id,
            recipient=recipient,
            text=str(args.text or ""),
            binding_id=effective_binding_id,
            binding=binding,
            heyy_ai_key=str(getattr(args, "heyy_ai_key", "") or "").strip(),
            heyy_ai_name=str(getattr(args, "heyy_ai_name", "") or "").strip(),
        )
    except Exception as exc:
        return {
            **base,
            **readiness_report,
            "sent": False,
            "reason": "send_failed",
            "error_type": type(exc).__name__,
            "error_reason": _safe_error_reason(exc),
        }

    message_ids = [str(value or "").strip() for value in receipt.message_ids if str(value or "").strip()]
    return {
        **base,
        **readiness_report,
        "sent": True,
        "reason": "sent",
        "binding_id": receipt.binding_id,
        "principal_id": receipt.principal_id,
        "connector_name": receipt.connector_name,
        "binding_status": receipt.binding_status,
        "external_account_ref_present": bool(str(receipt.external_account_ref or "").strip()),
        "recipient": receipt.recipient,
        "heyy_ai_key": str(getattr(args, "heyy_ai_key", "") or "").strip(),
        "heyy_ai_name": str(getattr(args, "heyy_ai_name", "") or "").strip(),
        "message_ids": message_ids,
        "message_id_count": len(message_ids),
        "request_url_present": bool(str(receipt.request_url or "").strip()),
        "request_host": _request_host(receipt.request_url),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send a live EA WhatsApp Web session test message after readiness passes.")
    parser.add_argument("--binding-json", default=_env("EA_WHATSAPP_WEB_READINESS_BINDING_JSON"))
    parser.add_argument("--database-url", default=_env("DATABASE_URL"))
    parser.add_argument("--binding-id", default=_env("EA_WHATSAPP_WEB_DEFAULT_BINDING_ID", "ea-whatsapp-web-session"))
    parser.add_argument(
        "--principal-id",
        default=_env("EA_WHATSAPP_WEB_DEFAULT_PRINCIPAL_ID") or _env("EA_WHATSAPP_DEFAULT_PRINCIPAL_ID", "principal-default"),
    )
    parser.add_argument("--recipient", default=_env("EA_WHATSAPP_WEB_LIVE_TEST_RECIPIENT"))
    parser.add_argument(
        "--text",
        default=_env("EA_WHATSAPP_WEB_LIVE_TEST_TEXT", "EA WhatsApp Web live delivery test"),
    )
    parser.add_argument("--heyy-ai-key", default=_env("EA_WHATSAPP_WEB_LIVE_TEST_HEYY_AI_KEY"))
    parser.add_argument("--heyy-ai-name", default=_env("EA_WHATSAPP_WEB_LIVE_TEST_HEYY_AI_NAME"))
    parser.add_argument("--probe-session", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_report(args)
    print(json.dumps(report, sort_keys=True))
    return 0 if bool(report.get("sent")) or str(report.get("reason") or "") == "dry_run" else 2


if __name__ == "__main__":
    raise SystemExit(main())
