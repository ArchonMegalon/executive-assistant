#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SESSION_REF = "default-wa-web"
DEFAULT_STATE_FILE = "/data/whatsapp-teable-sync/state.json"


def _load_env_file(path: Path = ROOT / ".env") -> None:
    if not path.is_file():
        return
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = _parse_env_value(raw_value)


def _parse_env_value(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        if value[0] == '"':
            try:
                loaded = json.loads(value)
                if isinstance(loaded, str):
                    return loaded
            except Exception:
                return value[1:-1]
        return value[1:-1]
    return value


def _env(name: str, default: str = "") -> str:
    return str(os.environ.get(name) or default).strip()


def _bool_env(name: str, default: bool = False) -> bool:
    raw = _env(name)
    if not raw:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def _int_value(value: object, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


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


def _freshness_seconds(*, interval_seconds: int, run_timeout_seconds: int, explicit_stale_seconds: int) -> int:
    if explicit_stale_seconds > 0:
        return explicit_stale_seconds
    return max(600, interval_seconds * 6 + run_timeout_seconds)


def check_readiness(
    *,
    enabled: bool,
    state_file: Path,
    session_ref: str,
    stale_seconds: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    checked_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if not enabled:
        return {
            "checked_at": checked_at.isoformat().replace("+00:00", "Z"),
            "enabled": False,
            "ok": True,
            "ready": True,
            "reason": "disabled",
        }
    if not state_file.is_file():
        return {
            "checked_at": checked_at.isoformat().replace("+00:00", "Z"),
            "enabled": True,
            "ok": False,
            "ready": False,
            "reason": "state_file_missing",
            "state_file": str(state_file),
        }
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "checked_at": checked_at.isoformat().replace("+00:00", "Z"),
            "enabled": True,
            "ok": False,
            "ready": False,
            "reason": "state_file_unreadable",
            "state_file": str(state_file),
        }
    if not isinstance(state, dict):
        return {
            "checked_at": checked_at.isoformat().replace("+00:00", "Z"),
            "enabled": True,
            "ok": False,
            "ready": False,
            "reason": "state_not_object",
            "state_file": str(state_file),
        }
    state_session_ref = str(state.get("session_ref") or "").strip()
    if session_ref and state_session_ref != session_ref:
        return {
            "checked_at": checked_at.isoformat().replace("+00:00", "Z"),
            "enabled": True,
            "ok": False,
            "ready": False,
            "reason": "session_ref_mismatch",
            "session_ref": session_ref,
            "state_session_ref": state_session_ref,
        }
    updated_at = _parse_iso(state.get("updated_at"))
    if updated_at is None:
        return {
            "checked_at": checked_at.isoformat().replace("+00:00", "Z"),
            "enabled": True,
            "ok": False,
            "ready": False,
            "reason": "updated_at_missing_or_invalid",
        }
    age_seconds = max(0, int((checked_at - updated_at).total_seconds()))
    if age_seconds > stale_seconds:
        return {
            "age_seconds": age_seconds,
            "checked_at": checked_at.isoformat().replace("+00:00", "Z"),
            "enabled": True,
            "ok": False,
            "ready": False,
            "reason": "state_stale",
            "stale_seconds": stale_seconds,
            "updated_at": updated_at.isoformat().replace("+00:00", "Z"),
        }
    conversation_count = _int_value(state.get("conversation_count"), -1)
    conversation_total = _int_value(state.get("conversation_total"), -1)
    next_skip = _int_value(state.get("next_conversation_skip"), -1)
    if conversation_count < 0 or conversation_total < 0 or next_skip < 0 or conversation_count > conversation_total:
        return {
            "checked_at": checked_at.isoformat().replace("+00:00", "Z"),
            "enabled": True,
            "ok": False,
            "ready": False,
            "reason": "cursor_values_invalid",
        }
    message_upsert = state.get("message_upsert") if isinstance(state.get("message_upsert"), dict) else {}
    return {
        "age_seconds": age_seconds,
        "checked_at": checked_at.isoformat().replace("+00:00", "Z"),
        "conversation_count": conversation_count,
        "conversation_page_complete": bool(state.get("conversation_page_complete")),
        "conversation_scan_completed": bool(state.get("conversation_scan_completed")),
        "conversation_scan_completed_at": str(state.get("conversation_scan_completed_at") or "").strip(),
        "conversation_scan_completed_count": _int_value(state.get("conversation_scan_completed_count"), 0),
        "conversation_scan_completed_total": _int_value(state.get("conversation_scan_completed_total"), 0),
        "conversation_skip": _int_value(state.get("conversation_skip"), 0),
        "conversation_total": conversation_total,
        "enabled": True,
        "message_upsert_cycle_total": _int_value(state.get("message_upsert_cycle_total"), 0),
        "message_upsert_total": _int_value(message_upsert.get("total"), 0),
        "next_conversation_skip": next_skip,
        "ok": True,
        "ready": True,
        "reason": "ready",
        "session_ref": state_session_ref,
        "stale_seconds": stale_seconds,
        "updated_at": updated_at.isoformat().replace("+00:00", "Z"),
    }


def parse_args() -> argparse.Namespace:
    _load_env_file()
    interval_seconds = _int_value(_env("EA_WHATSAPP_WEB_TEABLE_SYNC_INTERVAL_SECONDS", "30"), 30)
    run_timeout_seconds = _int_value(_env("EA_WHATSAPP_WEB_TEABLE_SYNC_RUN_TIMEOUT_SECONDS", "180"), 180)
    explicit_stale_seconds = _int_value(_env("EA_WHATSAPP_WEB_TEABLE_SYNC_STALE_SECONDS", ""), 0)
    parser = argparse.ArgumentParser(description="Check WhatsApp Web Teable sync cursor freshness.")
    parser.add_argument("--enabled", default=_env("EA_WHATSAPP_WEB_TEABLE_SYNC_ENABLED", "0"))
    parser.add_argument("--session-ref", default=_env("EA_WHATSAPP_WEB_DEFAULT_SESSION_REF", DEFAULT_SESSION_REF))
    parser.add_argument("--state-file", default=_env("EA_WHATSAPP_WEB_TEABLE_SYNC_STATE_FILE", DEFAULT_STATE_FILE))
    parser.add_argument(
        "--stale-seconds",
        type=int,
        default=_freshness_seconds(
            interval_seconds=interval_seconds,
            run_timeout_seconds=run_timeout_seconds,
            explicit_stale_seconds=explicit_stale_seconds,
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    enabled = str(args.enabled or "").strip().lower() in {"1", "true", "yes", "on"}
    report = check_readiness(
        enabled=enabled,
        state_file=Path(str(args.state_file)),
        session_ref=str(args.session_ref or "").strip(),
        stale_seconds=max(1, int(args.stale_seconds)),
    )
    print(json.dumps(report, sort_keys=True))
    return 0 if bool(report.get("ready")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
