#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
EA_ROOT = ROOT / "ea"
for candidate in (str(ROOT), str(EA_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


def _load_dotenv_if_present(path: Path) -> None:
    if not path.exists():
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        normalized = value.strip()
        if len(normalized) >= 2 and normalized[0] == normalized[-1] and normalized[0] in {"'", '"'}:
            normalized = normalized[1:-1]
        os.environ[key] = normalized


_load_dotenv_if_present(ROOT / ".env")

from app.services.proactive_ooda_service import (  # noqa: E402
    JsonOodaStateStore,
    ProactiveOodaService,
    build_run_receipt,
    digest_to_dict,
    format_telegram_digest,
    receipt_to_dict,
)
from app.services.proactive_signal_discovery import (  # noqa: E402
    discover_postgres_observation_signals,
    discover_signals_resilient,
    load_signal_sources_config,
)
from app.services.proactive_ooda_receipts import persist_proactive_ooda_receipt  # noqa: E402
from app.services.proactive_telegram_binding import resolve_proactive_telegram_chat_id  # noqa: E402


def _default_principal_id() -> str:
    return os.getenv("EA_PROACTIVE_OODA_PRINCIPAL_ID") or os.getenv("EA_DEFAULT_PRINCIPAL_ID") or "principal-default"


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest workspace signals, build OODA ink, and notify the user.")
    parser.add_argument("--principal-id", default=_default_principal_id())
    parser.add_argument(
        "--signals-json",
        default=os.getenv("EA_PROACTIVE_OODA_SIGNALS_JSON", ""),
        help="Optional file containing a list of signal objects.",
    )
    parser.add_argument("--state-path", default=os.getenv("EA_PROACTIVE_OODA_STATE_PATH", "state/proactive_ooda_notified.json"))
    parser.add_argument("--email-limit", type=int, default=int(os.getenv("EA_PROACTIVE_OODA_EMAIL_LIMIT", "8")))
    parser.add_argument("--calendar-limit", type=int, default=int(os.getenv("EA_PROACTIVE_OODA_CALENDAR_LIMIT", "8")))
    parser.add_argument("--gmail-query", default=os.getenv("EA_PROACTIVE_OODA_GMAIL_QUERY", ""))
    parser.add_argument(
        "--discovery-json",
        default=os.getenv("EA_PROACTIVE_OODA_DISCOVERY_JSON", ""),
        help="JSON list/object configuring generic JSON, JSONL, or RSS signal sources.",
    )
    parser.add_argument(
        "--observation-lookback-hours",
        type=int,
        default=int(os.getenv("EA_PROACTIVE_OODA_OBSERVATION_LOOKBACK_HOURS", "24")),
    )
    parser.add_argument(
        "--observation-limit",
        type=int,
        default=int(os.getenv("EA_PROACTIVE_OODA_OBSERVATION_LIMIT", "50")),
    )
    parser.add_argument("--skip-observation-source", action="store_true")
    parser.add_argument("--max-items", type=int, default=int(os.getenv("EA_PROACTIVE_OODA_MAX_ITEMS", "5")))
    parser.add_argument("--receipt-path", default=os.getenv("EA_PROACTIVE_OODA_RECEIPT_PATH", ""))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    signals = _load_signals(args)
    service = ProactiveOodaService(
        notify=_telegram_notify,
        state_store=JsonOodaStateStore(ROOT / args.state_path),
        max_items=args.max_items,
    )
    error_code = ""
    notification_result: object | None = None
    try:
        digest, notification_result = service.run(principal_id=args.principal_id, signals=signals, dry_run=args.dry_run)
    except Exception as exc:
        digest = service.build_digest(principal_id=args.principal_id, signals=signals)
        error_code = exc.__class__.__name__
    receipt = build_run_receipt(
        digest=digest,
        dry_run=args.dry_run,
        notification_result=notification_result,
        error_code=error_code,
    )
    if args.receipt_path:
        _write_receipt(Path(args.receipt_path), receipt_to_dict(receipt))
    if _env_truthy("EA_PROACTIVE_OODA_PERSIST_RECEIPTS", default=True):
        persist_proactive_ooda_receipt(principal_id=args.principal_id, digest=digest, receipt=receipt)
    if error_code:
        raise RuntimeError(f"proactive_ooda_notification_failed:{error_code}")
    if args.pretty:
        text = format_telegram_digest(digest) or "No actionable OODA ink."
        print(text)
    else:
        print(json.dumps({"digest": digest_to_dict(digest), "receipt": receipt_to_dict(receipt)}, indent=2, sort_keys=True))
    return 0


def _write_receipt(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _env_truthy(name: str, *, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _load_signals(args: argparse.Namespace) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if args.signals_json:
        payload = json.loads(Path(args.signals_json).read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise SystemExit("signals_json_must_be_a_list")
        rows.extend(dict(item) for item in payload if isinstance(item, dict))
    if args.discovery_json:
        sources = load_signal_sources_config(args.discovery_json)
        discovery = discover_signals_resilient(sources=sources, base_dir=ROOT)
        rows.extend(signal.__dict__ for signal in discovery.signals)
    if not args.skip_observation_source:
        observation_signals = discover_postgres_observation_signals(
            principal_id=args.principal_id,
            limit=args.observation_limit,
            lookback_hours=args.observation_lookback_hours,
        )
        if observation_signals:
            rows.extend(signal.__dict__ for signal in observation_signals)
    if rows:
        return rows
    try:
        from app.container import build_container
        from app.services.google_oauth import list_recent_workspace_signals
    except Exception as exc:  # pragma: no cover - depends on full runtime being present
        raise SystemExit(f"workspace_signal_runtime_unavailable:{exc.__class__.__name__}") from exc
    container = build_container()
    packet = list_recent_workspace_signals(
        container=container,
        principal_id=args.principal_id,
        email_limit=args.email_limit,
        calendar_limit=args.calendar_limit,
        gmail_query=args.gmail_query,
    )
    rows: list[dict[str, Any]] = []
    for signal in packet.signals:
        if hasattr(signal, "__dict__"):
            rows.append(dict(signal.__dict__))
    return rows


def _telegram_notify(principal_id: str, text: str) -> object:
    try:
        from app.container import build_container
        from app.services.telegram_delivery import send_telegram_message_for_principal
    except Exception as exc:  # pragma: no cover - depends on full runtime being present
        return _telegram_notify_from_env(principal_id=principal_id, text=text, fallback_error=exc)
    container = build_container()
    return send_telegram_message_for_principal(container.tool_runtime, principal_id=principal_id, text=text)


def _telegram_notify_from_env(*, principal_id: str, text: str, fallback_error: Exception) -> object:
    token = str(os.getenv("EA_TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = resolve_proactive_telegram_chat_id(principal_id=principal_id)
    if not token or not chat_id:
        raise RuntimeError(f"telegram_runtime_unavailable:{fallback_error.__class__.__name__}") from fallback_error
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=json.dumps({"chat_id": chat_id, "text": text}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not bool(payload.get("ok")):
        raise RuntimeError("telegram_sendmessage_failed")
    return payload.get("result") or {}


if __name__ == "__main__":
    raise SystemExit(main())
