#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, time as datetime_time, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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

import scripts.run_proactive_ooda as runner  # noqa: E402

from app.services.proactive_ooda_service import JsonOodaStateStore, ProactiveOodaService, digest_to_dict  # noqa: E402
from app.services.proactive_ooda_safe_work import (  # noqa: E402
    SAFE_WORK_RESULT_SCHEMA,
    build_safe_work_results,
    default_safe_work_result_dir,
)
from app.services.proactive_ooda_stage_packets import (  # noqa: E402
    SAFE_WORK_ORDER_SCHEMA,
    build_stage_packets,
    default_stage_packet_dir,
)
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
    parser.add_argument(
        "--paused",
        action=argparse.BooleanOptionalAction,
        default=_env_truthy("EA_PROACTIVE_OODA_PAUSED"),
    )
    parser.add_argument("--pause-reason", default=os.getenv("EA_PROACTIVE_OODA_PAUSE_REASON", ""))
    parser.add_argument("--quiet-hours-start", default=os.getenv("EA_PROACTIVE_OODA_QUIET_HOURS_START", ""))
    parser.add_argument("--quiet-hours-end", default=os.getenv("EA_PROACTIVE_OODA_QUIET_HOURS_END", ""))
    parser.add_argument(
        "--quiet-hours-timezone",
        default=os.getenv("EA_PROACTIVE_OODA_QUIET_HOURS_TIMEZONE", os.getenv("TZ", "UTC")),
    )
    parser.add_argument(
        "--quiet-hours-allow-high-priority",
        action=argparse.BooleanOptionalAction,
        default=_env_truthy("EA_PROACTIVE_OODA_QUIET_HOURS_ALLOW_HIGH_PRIORITY", default=True),
    )
    parser.add_argument(
        "--interruption-budget-limit",
        type=int,
        default=int(os.getenv("EA_PROACTIVE_OODA_INTERRUPTION_BUDGET_LIMIT", "0") or "0"),
    )
    parser.add_argument(
        "--interruption-budget-window-hours",
        type=int,
        default=int(os.getenv("EA_PROACTIVE_OODA_INTERRUPTION_BUDGET_WINDOW_HOURS", "24") or "24"),
    )
    parser.add_argument(
        "--interruption-budget-allow-high-priority",
        action=argparse.BooleanOptionalAction,
        default=_env_truthy("EA_PROACTIVE_OODA_INTERRUPTION_BUDGET_ALLOW_HIGH_PRIORITY", default=True),
    )
    parser.add_argument("--stage-packet-dir", default=os.getenv("EA_PROACTIVE_OODA_STAGE_PACKET_DIR", ""))
    parser.add_argument("--safe-work-result-dir", default=os.getenv("EA_PROACTIVE_OODA_SAFE_WORK_RESULT_DIR", ""))
    parser.add_argument(
        "--stage-packets",
        action=argparse.BooleanOptionalAction,
        default=_env_truthy("EA_PROACTIVE_OODA_STAGE_PACKETS_ENABLED", default=True),
    )
    parser.add_argument(
        "--safe-work-results",
        action=argparse.BooleanOptionalAction,
        default=_env_truthy("EA_PROACTIVE_OODA_SAFE_WORK_RESULTS_ENABLED", default=True),
    )
    parser.add_argument(
        "--require-stage-packets",
        action=argparse.BooleanOptionalAction,
        default=_env_truthy("EA_PROACTIVE_OODA_ENABLED")
        and _env_truthy("EA_PROACTIVE_OODA_STAGE_PACKETS_ENABLED", default=True),
    )
    parser.add_argument(
        "--require-safe-work-results",
        action=argparse.BooleanOptionalAction,
        default=_env_truthy("EA_PROACTIVE_OODA_ENABLED")
        and _env_truthy("EA_PROACTIVE_OODA_STAGE_PACKETS_ENABLED", default=True)
        and _env_truthy("EA_PROACTIVE_OODA_SAFE_WORK_RESULTS_ENABLED", default=True),
    )
    parser.add_argument(
        "--require-source",
        action=argparse.BooleanOptionalAction,
        default=_env_truthy("EA_PROACTIVE_OODA_ENABLED"),
    )
    parser.add_argument(
        "--require-telegram",
        action=argparse.BooleanOptionalAction,
        default=_env_truthy("EA_PROACTIVE_OODA_ENABLED"),
    )
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
    guard_status: dict[str, Any]
    context_grounding_status: dict[str, Any]
    delivery_route_status: dict[str, Any]
    state_store = JsonOodaStateStore(ROOT / args.state_path)
    if signals:
        digest = ProactiveOodaService(state_store=state_store, max_items=args.max_items).build_digest(
            principal_id=args.principal_id,
            signals=signals,
            already_notified_refs=state_store.load_notified_refs(args.principal_id),
        )
        grounded_digest = runner._context_grounded_digest(args.principal_id, digest)
        digest_items = len(grounded_digest.items)
        notified_refs = list(grounded_digest.notified_refs)
        digest_payload = digest_to_dict(grounded_digest)
        guard_status = _delivery_guard_status(args, state_store=state_store, digest=grounded_digest)
        context_grounding_status = _context_grounding_status(grounded_digest)
        delivery_route_status = _delivery_route_status(args.principal_id, grounded_digest)
    else:
        grounded_digest = None
        digest_payload = {}
        guard_status = _delivery_guard_status(args, state_store=state_store, digest=None)
        context_grounding_status = _context_grounding_status(None)
        delivery_route_status = _delivery_route_status(args.principal_id, None)
    stage_packet_status = _stage_packet_status(args, digest=grounded_digest)
    if stage_packet_status["required"] and not stage_packet_status["ready"]:
        errors.extend(stage_packet_status["errors"])
    safe_work_result_status = _safe_work_result_status(args, digest=grounded_digest, stage_packet_dir=Path(stage_packet_status["output_dir"]))
    if safe_work_result_status["required"] and not safe_work_result_status["ready"]:
        errors.extend(safe_work_result_status["errors"])

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
        "delivery_route": delivery_route_status,
        "delivery_guard": guard_status,
        "context_grounding": context_grounding_status,
        "stage_packets": stage_packet_status,
        "safe_work_results": safe_work_result_status,
        "digest": digest_payload,
    }


def _load_signal_file(path_value: str) -> list[dict[str, Any]]:
    payload = json.loads(Path(path_value).read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("signals_json_must_be_a_list")
    return [dict(item) for item in payload if isinstance(item, dict)]


def _telegram_ready(principal_id: str) -> bool:
    return proactive_telegram_ready(principal_id=principal_id)


def _delivery_route_status(principal_id: str, digest: Any | None) -> dict[str, Any]:
    status = runner._delivery_status(principal_id, digest=digest)
    return {
        "ready": bool(getattr(status, "ready", False)),
        "selected_channel": str(getattr(status, "selected_channel", "") or ""),
        "selected_transport": str(getattr(status, "selected_transport", "") or ""),
        "selected_by": str(getattr(status, "selected_by", "") or ""),
        "selected_reason": str(getattr(status, "selected_reason", "") or ""),
        "binding_id_present": bool(str(getattr(status, "binding_id", "") or "").strip()),
        "recipient_ref_hash_present": bool(str(getattr(status, "recipient_ref_hash", "") or "").strip()),
        "available_channels": [str(item or "") for item in getattr(status, "available_channels", ()) if str(item or "").strip()],
        "errors": [str(item or "") for item in getattr(status, "errors", ()) if str(item or "").strip()],
        "route_error": str(getattr(status, "route_error", "") or ""),
        "recovery_hint": str(getattr(status, "recovery_hint", "") or ""),
        "next_action": str(getattr(status, "next_action", "") or ""),
        "preference_count": int(getattr(status, "preference_count", 0) or 0),
        "policy_count": int(getattr(status, "policy_count", 0) or 0),
        "follow_up_hint_count": int(getattr(status, "follow_up_hint_count", 0) or 0),
    }


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


def _env_truthy(name: str, *, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _delivery_guard_status(
    args: argparse.Namespace,
    *,
    state_store: JsonOodaStateStore,
    digest: Any | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    items = tuple(getattr(digest, "items", ()) or ()) if digest is not None else ()
    has_items = bool(items)
    has_high_priority = any(getattr(item, "priority", "") == "high" for item in items)
    paused = bool(getattr(args, "paused", False))
    quiet_active = _quiet_hours_active(args, now=now)
    quiet_allows_high = bool(getattr(args, "quiet_hours_allow_high_priority", True))
    budget_limit = max(_safe_int(getattr(args, "interruption_budget_limit", 0), default=0), 0)
    budget_window_hours = max(_safe_int(getattr(args, "interruption_budget_window_hours", 24), default=24), 1)
    budget_used = len(
        _recent_interruption_events(
            state_store.load_interruption_events(str(getattr(args, "principal_id", "") or "")),
            now=now or datetime.now(timezone.utc),
            window_hours=budget_window_hours,
        )
    )
    budget_allows_high = bool(getattr(args, "interruption_budget_allow_high_priority", True))
    budget_exhausted = budget_limit > 0 and budget_used >= budget_limit

    delivery_state = "no_actionable_items" if not has_items else "eligible"
    deferred_reason = ""
    if has_items and paused:
        delivery_state = "deferred"
        deferred_reason = "deferred_by_operator_pause"
    elif has_items and quiet_active and not (quiet_allows_high and has_high_priority):
        delivery_state = "deferred"
        deferred_reason = "deferred_by_quiet_hours"
    elif has_items and budget_exhausted and not (budget_allows_high and has_high_priority):
        delivery_state = "deferred"
        deferred_reason = "deferred_by_interruption_budget"

    return {
        "delivery_state": delivery_state,
        "deferred_reason": deferred_reason,
        "operator_paused": paused,
        "pause_reason_present": bool(str(getattr(args, "pause_reason", "") or "").strip()),
        "quiet_hours_configured": _quiet_hours_configured(args),
        "quiet_hours_active": quiet_active,
        "quiet_hours_allow_high_priority": quiet_allows_high,
        "interruption_budget_limit": budget_limit,
        "interruption_budget_window_hours": budget_window_hours,
        "interruption_budget_used": budget_used,
        "interruption_budget_exhausted": budget_exhausted,
        "interruption_budget_allow_high_priority": budget_allows_high,
        "has_high_priority": has_high_priority,
    }


def _context_grounding_status(digest: Any | None) -> dict[str, Any]:
    items = tuple(getattr(digest, "items", ()) or ()) if digest is not None else ()
    notes_count = 0
    preference_count = 0
    requirement_count = 0
    exclusion_count = 0
    assessment_count = 0
    deadline_count = 0
    for item in items:
        payload = dict(getattr(item, "stage_payload", None) or {})
        notes_count += len(_list_value(payload.get("notes")))
        preference_count += len(_list_value(payload.get("preferences")))
        requirement_count += len(_list_value(payload.get("requirements")))
        exclusion_count += len(_list_value(payload.get("exclusions")))
        if str(payload.get("deadline") or "").strip():
            deadline_count += 1
        for key in ("candidate_items", "candidates", "booking_options"):
            for candidate in _object_list(payload.get(key)):
                if isinstance(candidate.get("preference_assessment"), dict):
                    assessment_count += 1
    return {
        "grounded": bool(items),
        "notes_count": notes_count,
        "preference_count": preference_count,
        "requirement_count": requirement_count,
        "exclusion_count": exclusion_count,
        "deadline_count": deadline_count,
        "candidate_assessment_count": assessment_count,
    }


def _stage_packet_status(args: argparse.Namespace, *, digest: Any | None) -> dict[str, Any]:
    enabled = bool(getattr(args, "stage_packets", True))
    required = bool(getattr(args, "require_stage_packets", False))
    output_dir = _stage_packet_dir(args)
    expected_packet_count = len(tuple(getattr(digest, "items", ()) or ())) if digest is not None else 0
    packet_count = 0
    safe_work_order_count = 0
    errors: list[str] = []
    writable = False
    if not enabled:
        if required:
            errors.append("stage_packets_disabled")
        return {
            "enabled": False,
            "required": required,
            "ready": not errors,
            "output_dir": str(output_dir),
            "output_dir_writable": False,
            "expected_packet_count": expected_packet_count,
            "packet_count": 0,
            "safe_work_order_count": 0,
            "errors": errors,
        }
    writable, write_error = _directory_writable(output_dir)
    if not writable:
        errors.append(f"stage_packet_dir_unwritable:{write_error}")
    if digest is not None:
        try:
            packets = build_stage_packets(digest)
            packet_count = len(packets)
            safe_work_order_count = sum(
                1
                for packet in packets
                if isinstance(packet.get("safe_work_order"), dict)
                and packet["safe_work_order"].get("schema") == SAFE_WORK_ORDER_SCHEMA
            )
        except Exception as exc:
            errors.append(f"stage_packet_build_failed:{exc.__class__.__name__}")
    if expected_packet_count and packet_count != expected_packet_count:
        errors.append("stage_packet_count_mismatch")
    if expected_packet_count and safe_work_order_count != expected_packet_count:
        errors.append("safe_work_order_count_mismatch")
    return {
        "enabled": True,
        "required": required,
        "ready": not errors,
        "output_dir": str(output_dir),
        "output_dir_writable": writable,
        "expected_packet_count": expected_packet_count,
        "packet_count": packet_count,
        "safe_work_order_count": safe_work_order_count,
        "errors": errors,
    }


def _safe_work_result_status(args: argparse.Namespace, *, digest: Any | None, stage_packet_dir: Path) -> dict[str, Any]:
    enabled = bool(getattr(args, "safe_work_results", True))
    required = bool(getattr(args, "require_safe_work_results", False))
    output_dir = _safe_work_result_dir(args, stage_packet_dir=stage_packet_dir)
    expected_result_count = len(tuple(getattr(digest, "items", ()) or ())) if digest is not None else 0
    result_count = 0
    schema_valid_count = 0
    errors: list[str] = []
    writable = False
    if not enabled:
        if required:
            errors.append("safe_work_results_disabled")
        return {
            "enabled": False,
            "required": required,
            "ready": not errors,
            "output_dir": str(output_dir),
            "output_dir_writable": False,
            "expected_result_count": expected_result_count,
            "result_count": 0,
            "schema_valid_count": 0,
            "errors": errors,
        }
    writable, write_error = _directory_writable(output_dir)
    if not writable:
        errors.append(f"safe_work_result_dir_unwritable:{write_error}")
    if digest is not None:
        try:
            results = build_safe_work_results(build_stage_packets(digest))
            result_count = len(results)
            schema_valid_count = sum(1 for result in results if result.get("schema") == SAFE_WORK_RESULT_SCHEMA)
        except Exception as exc:
            errors.append(f"safe_work_result_build_failed:{exc.__class__.__name__}")
    if expected_result_count and result_count != expected_result_count:
        errors.append("safe_work_result_count_mismatch")
    if expected_result_count and schema_valid_count != expected_result_count:
        errors.append("safe_work_result_schema_count_mismatch")
    return {
        "enabled": True,
        "required": required,
        "ready": not errors,
        "output_dir": str(output_dir),
        "output_dir_writable": writable,
        "expected_result_count": expected_result_count,
        "result_count": result_count,
        "schema_valid_count": schema_valid_count,
        "errors": errors,
    }


def _stage_packet_dir(args: argparse.Namespace) -> Path:
    configured = str(getattr(args, "stage_packet_dir", "") or "").strip()
    if configured:
        path = Path(configured)
        return path if path.is_absolute() else ROOT / path
    return default_stage_packet_dir(root=ROOT, state_path=getattr(args, "state_path", "state/proactive_ooda_notified.json"))


def _safe_work_result_dir(args: argparse.Namespace, *, stage_packet_dir: Path) -> Path:
    configured = str(getattr(args, "safe_work_result_dir", "") or "").strip()
    if configured:
        path = Path(configured)
        return path if path.is_absolute() else ROOT / path
    return default_safe_work_result_dir(stage_packet_dir)


def _directory_writable(path: Path) -> tuple[bool, str]:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / f".proactive_ooda_write_probe.{os.getpid()}"
        probe.write_text("ok\n", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True, ""
    except Exception as exc:
        return False, exc.__class__.__name__


def _object_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [dict(value)]
    if not isinstance(value, (list, tuple)):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _list_value(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item or "").strip() for item in value if str(item or "").strip()]


def _quiet_hours_configured(args: argparse.Namespace) -> bool:
    return _parse_local_time(getattr(args, "quiet_hours_start", "")) is not None and _parse_local_time(
        getattr(args, "quiet_hours_end", "")
    ) is not None


def _quiet_hours_active(args: argparse.Namespace, *, now: datetime | None = None) -> bool:
    start = _parse_local_time(getattr(args, "quiet_hours_start", ""))
    end = _parse_local_time(getattr(args, "quiet_hours_end", ""))
    if start is None or end is None:
        return False
    local_now = (now or datetime.now(timezone.utc)).astimezone(_quiet_hours_timezone(getattr(args, "quiet_hours_timezone", "")))
    return _is_time_within_quiet_hours(local_now.time(), start=start, end=end)


def _parse_local_time(value: str) -> datetime_time | None:
    parts = str(value or "").strip().split(":")
    if len(parts) < 2:
        return None
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError:
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return datetime_time(hour=hour, minute=minute)


def _quiet_hours_timezone(value: str):
    name = str(value or "UTC").strip() or "UTC"
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return timezone.utc


def _is_time_within_quiet_hours(current: datetime_time, *, start: datetime_time, end: datetime_time) -> bool:
    current_minutes = current.hour * 60 + current.minute
    start_minutes = start.hour * 60 + start.minute
    end_minutes = end.hour * 60 + end.minute
    if start_minutes == end_minutes:
        return False
    if start_minutes < end_minutes:
        return start_minutes <= current_minutes < end_minutes
    return current_minutes >= start_minutes or current_minutes < end_minutes


def _recent_interruption_events(events: tuple[str, ...], *, now: datetime, window_hours: int) -> tuple[str, ...]:
    normalized_now = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    cutoff_epoch = normalized_now.timestamp() - (max(int(window_hours or 1), 1) * 3600)
    recent: list[str] = []
    for raw_event in events:
        parsed = _parse_datetime(raw_event)
        if parsed is None:
            continue
        if parsed.timestamp() >= cutoff_epoch:
            recent.append(parsed.isoformat())
    return tuple(recent)


def _parse_datetime(value: str) -> datetime | None:
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


def _safe_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _format_report(report: dict[str, Any]) -> str:
    status = "ok" if report["ok"] else "not ready"
    lines = [
        f"proactive OODA: {status}",
        f"source: {report['source_mode']} ({report['signal_count']} signals, {report['actionable_count']} actionable)",
        f"telegram: {'ready' if report['telegram_ready'] else 'not configured'}",
        f"delivery route: {_delivery_route_summary(report)}",
        f"workspace: {_workspace_status(report)}",
        f"delivery guard: {_delivery_guard_summary(report)}",
        f"context grounding: {_context_grounding_summary(report)}",
        f"stage packets: {_stage_packet_summary(report)}",
        f"safe-work results: {_safe_work_result_summary(report)}",
        f"receipt observations: {report['receipt_observation_count']}",
        f"state: {report['state_path']}",
    ]
    recovery = _delivery_recovery_summary(report)
    if recovery:
        lines.append(f"delivery recovery: {recovery}")
    if report["errors"]:
        lines.append(f"errors: {', '.join(report['errors'])}")
    if report.get("warnings"):
        lines.append(f"warnings: {', '.join(report['warnings'])}")
    return "\n".join(lines)


def _workspace_status(report: dict[str, Any]) -> str:
    if not report.get("workspace_source_checked"):
        return "not checked"
    return "ready" if report.get("workspace_source_healthy") else "unhealthy"


def _delivery_route_summary(report: dict[str, Any]) -> str:
    status = dict(report.get("delivery_route") or {})
    if not status:
        return "unknown"
    ready = "ready" if status.get("ready") else "not ready"
    channel = str(status.get("selected_channel") or "").strip()
    transport = str(status.get("selected_transport") or "").strip()
    selected_by = str(status.get("selected_by") or "").strip()
    available = list(status.get("available_channels") or [])
    errors = list(status.get("errors") or [])
    route_error = str(status.get("route_error") or "").strip()
    next_action = str(status.get("next_action") or "").strip()
    detail = channel
    if transport and transport != channel:
        detail = f"{detail} via {transport}" if detail else transport
    if selected_by:
        detail = f"{detail} ({selected_by})" if detail else selected_by
    available_text = f", available {', '.join(available)}" if available else ""
    blocker = route_error or (errors[0] if errors else "")
    error_text = f", blocked by {blocker}" if blocker else ""
    next_action_text = f", next action {next_action}" if next_action else ""
    return f"{ready}{f' [{detail}]' if detail else ''}{available_text}{error_text}{next_action_text}"


def _delivery_recovery_summary(report: dict[str, Any]) -> str:
    status = dict(report.get("delivery_route") or {})
    route_error = str(status.get("route_error") or "").strip()
    recovery_hint = str(status.get("recovery_hint") or "").strip()
    next_action = str(status.get("next_action") or "").strip()
    if not route_error and not recovery_hint and not next_action:
        return ""
    head = next_action or "inspect_proactive_delivery_route"
    if route_error:
        head = f"{head} ({route_error})"
    if recovery_hint:
        head = f"{head} - {recovery_hint}"
    return head


def _delivery_guard_summary(report: dict[str, Any]) -> str:
    guard = dict(report.get("delivery_guard") or {})
    state = str(guard.get("delivery_state") or "unknown")
    reason = str(guard.get("deferred_reason") or "").strip()
    budget_limit = int(guard.get("interruption_budget_limit") or 0)
    budget_used = int(guard.get("interruption_budget_used") or 0)
    budget = f", budget {budget_used}/{budget_limit}" if budget_limit > 0 else ""
    paused = ", paused" if guard.get("operator_paused") else ""
    quiet = ", quiet-active" if guard.get("quiet_hours_active") else ""
    return f"{state}{f' ({reason})' if reason else ''}{paused}{quiet}{budget}"


def _context_grounding_summary(report: dict[str, Any]) -> str:
    status = dict(report.get("context_grounding") or {})
    if not status.get("grounded"):
        return "no actionable stage context"
    return (
        f"{status.get('candidate_assessment_count', 0)} candidate assessments, "
        f"{status.get('preference_count', 0)} preferences, "
        f"{status.get('requirement_count', 0)} requirements, "
        f"{status.get('deadline_count', 0)} deadlines"
    )


def _stage_packet_summary(report: dict[str, Any]) -> str:
    status = dict(report.get("stage_packets") or {})
    if not status.get("enabled"):
        return "disabled"
    ready = "ready" if status.get("ready") else "not ready"
    writable = "writable" if status.get("output_dir_writable") else "unwritable"
    return (
        f"{ready}, {status.get('packet_count', 0)}/{status.get('expected_packet_count', 0)} packets, "
        f"{status.get('safe_work_order_count', 0)} work orders, {writable}"
    )


def _safe_work_result_summary(report: dict[str, Any]) -> str:
    status = dict(report.get("safe_work_results") or {})
    if not status.get("enabled"):
        return "disabled"
    ready = "ready" if status.get("ready") else "not ready"
    writable = "writable" if status.get("output_dir_writable") else "unwritable"
    return (
        f"{ready}, {status.get('result_count', 0)}/{status.get('expected_result_count', 0)} results, "
        f"{status.get('schema_valid_count', 0)} schema-valid, {writable}"
    )


if __name__ == "__main__":
    raise SystemExit(main())
