#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

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

from app.services.proactive_ooda_service import JsonOodaStateStore, ProactiveOodaService, digest_to_dict  # noqa: E402
from app.services.proactive_signal_discovery import (  # noqa: E402
    discover_opportunity_rule_signals,
    discover_postgres_observation_signals,
    discover_signals_resilient,
    load_signal_sources_config,
)
from app.services.proactive_telegram_binding import proactive_telegram_ready  # noqa: E402


def _default_principal_id() -> str:
    return os.getenv("EA_PROACTIVE_OODA_PRINCIPAL_ID") or os.getenv("EA_DEFAULT_PRINCIPAL_ID") or "principal-default"


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify proactive OODA signal ingestion and notification readiness.")
    parser.add_argument("--principal-id", default=_default_principal_id())
    parser.add_argument("--signals-json", default=os.getenv("EA_PROACTIVE_OODA_SIGNALS_JSON", ""))
    parser.add_argument("--discovery-json", default=os.getenv("EA_PROACTIVE_OODA_DISCOVERY_JSON", ""))
    parser.add_argument(
        "--opportunity-rules-json",
        default=os.getenv("EA_PROACTIVE_OODA_OPPORTUNITY_RULES_JSON", os.getenv("EA_PROACTIVE_OODA_PERSONAL_RULES_JSON", "")),
    )
    parser.add_argument("--state-path", default=os.getenv("EA_PROACTIVE_OODA_STATE_PATH", "state/proactive_ooda_notified.json"))
    parser.add_argument("--max-items", type=int, default=int(os.getenv("EA_PROACTIVE_OODA_MAX_ITEMS", "5")))
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
    parser.add_argument("--require-source", action="store_true", default=_env_truthy("EA_PROACTIVE_OODA_ENABLED"))
    parser.add_argument("--require-telegram", action="store_true", default=_env_truthy("EA_PROACTIVE_OODA_ENABLED"))
    parser.add_argument("--require-receipt-observation", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    report = _build_report(args)
    if args.pretty:
        print(_format_report(report))
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


def _build_report(args: argparse.Namespace) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    source_modes: list[str] = []
    signals: list[dict[str, Any]] = []
    if args.signals_json:
        try:
            loaded = _load_signal_file(args.signals_json)
            if loaded:
                source_modes.append("signals_json")
                signals.extend(loaded)
        except Exception as exc:
            errors.append(f"signals_json_invalid:{exc.__class__.__name__}")
    if args.discovery_json:
        try:
            sources = load_signal_sources_config(args.discovery_json)
            discovery = discover_signals_resilient(sources=sources, base_dir=ROOT)
            loaded = [signal.__dict__ for signal in discovery.signals]
            if loaded:
                source_modes.append("discovery_json")
                signals.extend(loaded)
            warnings.extend(f"discovery_source_failed:{item}" for item in discovery.errors)
        except Exception as exc:
            errors.append(f"discovery_json_invalid:{exc.__class__.__name__}")
    opportunity_rules_json = str(getattr(args, "opportunity_rules_json", "") or "")
    if opportunity_rules_json:
        discovery = discover_opportunity_rule_signals(raw_config=opportunity_rules_json, base_dir=ROOT)
        loaded = [signal.__dict__ for signal in discovery.signals]
        if loaded:
            source_modes.append("opportunity_rules")
            signals.extend(loaded)
        warnings.extend(f"opportunity_rule_failed:{item}" for item in discovery.errors)
    if not args.skip_observation_source:
        observation_signals = discover_postgres_observation_signals(
            principal_id=args.principal_id,
            limit=args.observation_limit,
            lookback_hours=args.observation_lookback_hours,
        )
        if observation_signals:
            source_modes.append("postgres_observations")
            signals.extend(signal.__dict__ for signal in observation_signals)
    workspace_source_checked = False
    workspace_source_healthy = False
    if not bool(getattr(args, "skip_workspace_source", True)):
        workspace_source_checked = True
        try:
            from app.container import build_container
            from app.services.google_oauth import list_recent_workspace_signals

            packet = list_recent_workspace_signals(
                container=build_container(),
                principal_id=args.principal_id,
                email_limit=1,
                calendar_limit=1,
                gmail_query=os.getenv("EA_PROACTIVE_OODA_GMAIL_QUERY", ""),
            )
            loaded = [dict(signal.__dict__) for signal in tuple(getattr(packet, "signals", ()) or ()) if hasattr(signal, "__dict__")]
            source_modes.append("google_workspace")
            signals.extend(loaded)
            workspace_source_healthy = True
        except Exception as exc:
            source_modes.append("google_workspace_error")
            errors.append(f"google_workspace_signal_source_unhealthy:{exc.__class__.__name__}")
    source_mode = "+".join(source_modes) if source_modes else "none"
    if args.require_source and source_mode == "none":
        errors.append("no_signal_source_configured")

    telegram_ready = _telegram_ready(args.principal_id)
    if args.require_telegram and not telegram_ready:
        errors.append("telegram_notification_not_configured")
    receipt_observation_count = _receipt_observation_count(args.principal_id)
    if args.require_receipt_observation and receipt_observation_count < 1:
        errors.append("receipt_observation_missing")

    digest_items = 0
    notified_refs: list[str] = []
    if signals:
        digest = ProactiveOodaService(
            state_store=JsonOodaStateStore(ROOT / args.state_path),
            max_items=args.max_items,
        ).build_digest(principal_id=args.principal_id, signals=signals)
        digest_items = len(digest.items)
        notified_refs = list(digest.notified_refs)
        digest_payload = digest_to_dict(digest)
    else:
        digest_payload = {}

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "principal_id": args.principal_id,
        "source_mode": source_mode,
        "signal_count": len(signals),
        "actionable_count": digest_items,
        "notified_refs": notified_refs,
        "telegram_ready": telegram_ready,
        "receipt_observation_count": receipt_observation_count,
        "workspace_source_checked": workspace_source_checked,
        "workspace_source_healthy": workspace_source_healthy,
        "state_path": args.state_path,
        "digest": digest_payload,
    }


def _load_signal_file(path_value: str) -> list[dict[str, Any]]:
    payload = json.loads(Path(path_value).read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("signals_json_must_be_a_list")
    return [dict(item) for item in payload if isinstance(item, dict)]


def _telegram_ready(principal_id: str) -> bool:
    return proactive_telegram_ready(principal_id=principal_id)


def _receipt_observation_count(principal_id: str) -> int:
    database_url = str(os.getenv("DATABASE_URL") or "").strip()
    if not database_url:
        return 0
    try:
        import psycopg
    except Exception:
        return 0
    try:
        with psycopg.connect(database_url, connect_timeout=5) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select count(*)
                    from observation_events
                    where principal_id = %s
                      and event_type = 'proactive_ooda.run_receipt'
                      and not (payload_json ? 'chat_id')
                      and not (payload_json ? 'message_text')
                      and not (payload_json ? 'source_ref')
                    """,
                    (principal_id,),
                )
                row = cursor.fetchone()
    except Exception:
        return 0
    return int(row[0] or 0) if row else 0


def _env_truthy(name: str) -> bool:
    return str(os.getenv(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def _format_report(report: dict[str, Any]) -> str:
    status = "ok" if report["ok"] else "not ready"
    lines = [
        f"proactive OODA: {status}",
        f"source: {report['source_mode']} ({report['signal_count']} signals, {report['actionable_count']} actionable)",
        f"telegram: {'ready' if report['telegram_ready'] else 'not configured'}",
        f"workspace: {_workspace_status(report)}",
        f"receipt observations: {report['receipt_observation_count']}",
        f"state: {report['state_path']}",
    ]
    if report["errors"]:
        lines.append(f"errors: {', '.join(report['errors'])}")
    if report.get("warnings"):
        lines.append(f"warnings: {', '.join(report['warnings'])}")
    return "\n".join(lines)


def _workspace_status(report: dict[str, Any]) -> str:
    if not report.get("workspace_source_checked"):
        return "not checked"
    return "ready" if report.get("workspace_source_healthy") else "unhealthy"


if __name__ == "__main__":
    raise SystemExit(main())
