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
    discover_personal_rule_signals,
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
        "--opportunity-rules-json",
        "--personal-rules-json",
        dest="personal_rules_json",
        default=os.getenv("EA_PROACTIVE_OODA_OPPORTUNITY_RULES_JSON", os.getenv("EA_PROACTIVE_OODA_PERSONAL_RULES_JSON", "")),
        help="JSON list/object configuring local OODA opportunity rules.",
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
    parser.add_argument("--skip-workspace-source", action="store_true")
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
        try:
            payload = json.loads(Path(args.signals_json).read_text(encoding="utf-8"))
            if not isinstance(payload, list):
                raise ValueError("signals_json_must_be_a_list")
            rows.extend(dict(item) for item in payload if isinstance(item, dict))
        except Exception as exc:
            rows.extend(_source_error_signals((f"signals_json:{exc.__class__.__name__}:{_short_hash(args.signals_json)}",), source_label="signals_json"))
    if args.discovery_json:
        try:
            sources = load_signal_sources_config(args.discovery_json)
            discovery = discover_signals_resilient(sources=sources, base_dir=ROOT)
            rows.extend(signal.__dict__ for signal in discovery.signals)
            rows.extend(_source_error_signals(discovery.errors, source_label="discovery"))
        except Exception as exc:
            rows.extend(_source_error_signals((f"discovery_json:{exc.__class__.__name__}:config",), source_label="discovery"))
    personal_rules_json = str(getattr(args, "personal_rules_json", getattr(args, "opportunity_rules_json", "")) or "")
    if personal_rules_json:
        personal = discover_personal_rule_signals(raw_config=personal_rules_json, base_dir=ROOT)
        rows.extend(signal.__dict__ for signal in personal.signals)
        rows.extend(_source_error_signals(personal.errors, source_label="personal_rules"))
    if not args.skip_observation_source:
        observation_signals = discover_postgres_observation_signals(
            principal_id=args.principal_id,
            limit=args.observation_limit,
            lookback_hours=args.observation_lookback_hours,
        )
        if observation_signals:
            rows.extend(signal.__dict__ for signal in observation_signals)
    if bool(getattr(args, "skip_workspace_source", False)):
        return rows
    try:
        from app.container import build_container
        from app.services.google_oauth import list_recent_workspace_signals
    except Exception as exc:  # pragma: no cover - depends on full runtime being present
        return rows + [_workspace_source_error_signal(exc)]
    try:
        container = build_container()
        packet = list_recent_workspace_signals(
            container=container,
            principal_id=args.principal_id,
            email_limit=args.email_limit,
            calendar_limit=args.calendar_limit,
            gmail_query=args.gmail_query,
        )
    except Exception as exc:
        return rows + [_workspace_source_error_signal(exc)]
    for signal in packet.signals:
        if hasattr(signal, "__dict__"):
            rows.append(dict(signal.__dict__))
    return rows


def _source_error_signals(errors: tuple[str, ...], *, source_label: str) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []
    for error in errors:
        error_label = str(error or "").strip()
        if not error_label:
            continue
        signals.append(
            {
                "source_ref": f"proactive_source_error:{source_label}:{_short_hash(error_label)}",
                "signal_type": "proactive_source_health",
                "channel": "proactive_runtime",
                "title": "EA proactive source needs attention",
                "summary": "A configured proactive source failed. EA kept running, but this source may be missing from the brief.",
                "counterparty": "EA runtime",
                "payload": {
                    "ooda_loop": _source_health_ooda(
                        "A configured proactive source failed.",
                        "Check the configured source and repair credentials, URL, or table mapping.",
                    )
                },
            }
        )
    return signals


def _workspace_source_error_signal(exc: Exception) -> dict[str, Any]:
    error_name = exc.__class__.__name__
    error_text = str(exc or error_name)
    summary = "Google workspace scanning is failing, so EA cannot reliably inspect Gmail or Calendar for proactive nudges."
    action = "Reauthorize Google for the EA principal, then rerun the proactive OODA verifier."
    return {
        "source_ref": f"proactive_source_error:google_workspace:{_short_hash(error_text or error_name)}",
        "signal_type": "proactive_source_health",
        "channel": "proactive_runtime",
        "title": "EA cannot scan Google workspace",
        "summary": summary,
        "counterparty": "Google workspace",
        "payload": {"ooda_loop": _source_health_ooda(summary, action)},
    }


def _source_health_ooda(summary: str, action: str) -> dict[str, Any]:
    return {
        "reviewed": True,
        "observe": {"summary": summary, "channel": "proactive_runtime", "signal_type": "source_health"},
        "orient": {
            "summary": "A paid-assistant loop should degrade visibly instead of going silent when one source breaks.",
            "tags": ["proactive", "reliability"],
        },
        "decide": {
            "summary": "Repair the source or accept that EA will miss reminders from it.",
            "recommended_actions": [action],
            "approval_required": False,
            "ignored_consequence": "EA may stay quiet even when a human assistant would have found the signal.",
        },
        "act": {"summary": action},
    }


def _short_hash(value: str) -> str:
    import hashlib

    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()[:12]


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
