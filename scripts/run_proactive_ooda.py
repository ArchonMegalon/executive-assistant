#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, time as datetime_time, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
import urllib.request
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

from app.services.proactive_ooda_service import (  # noqa: E402
    JsonOodaStateStore,
    ProactiveOodaDigest,
    ProactiveOodaService,
    build_run_receipt,
    digest_to_dict,
    format_telegram_digest,
    receipt_to_dict,
)
from app.services.proactive_signal_discovery import (  # noqa: E402
    discover_opportunity_rule_signals,
    discover_postgres_observation_signals,
    discover_signals_resilient,
    load_signal_sources_config,
)
from app.services.proactive_ooda_receipts import persist_proactive_ooda_receipt  # noqa: E402
from app.services.proactive_ooda_safe_work import (  # noqa: E402
    build_safe_work_result,
    default_safe_work_result_dir,
    persist_safe_work_results_from_paths,
)
from app.services.proactive_ooda_stage_packets import (  # noqa: E402
    build_stage_packets,
    default_stage_packet_dir,
    persist_stage_packets,
)
from app.services.proactive_ooda_context_grounding import ground_digest_with_context  # noqa: E402
from app.services.proactive_ooda_teable_sync import (  # noqa: E402
    sync_proactive_ooda_to_teable,
    teable_sync_enabled,
)
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
        dest="opportunity_rules_json",
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
        "--paused",
        action=argparse.BooleanOptionalAction,
        default=_env_truthy("EA_PROACTIVE_OODA_PAUSED", default=False),
        help="Build and receipt the OODA packet, but defer delivery and leave refs unnotified.",
    )
    parser.add_argument("--pause-reason", default=os.getenv("EA_PROACTIVE_OODA_PAUSE_REASON", ""))
    parser.add_argument(
        "--interruption-budget-limit",
        type=int,
        default=int(os.getenv("EA_PROACTIVE_OODA_INTERRUPTION_BUDGET_LIMIT", "0") or "0"),
        help="Maximum proactive notifications in the rolling budget window; 0 disables this guard.",
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
    parser.add_argument("--max-items", type=int, default=int(os.getenv("EA_PROACTIVE_OODA_MAX_ITEMS", "5")))
    parser.add_argument("--receipt-path", default=os.getenv("EA_PROACTIVE_OODA_RECEIPT_PATH", ""))
    parser.add_argument("--stage-packet-dir", default=os.getenv("EA_PROACTIVE_OODA_STAGE_PACKET_DIR", ""))
    parser.add_argument(
        "--stage-packets",
        action=argparse.BooleanOptionalAction,
        default=_env_truthy("EA_PROACTIVE_OODA_STAGE_PACKETS_ENABLED", default=True),
    )
    parser.add_argument("--safe-work-result-dir", default=os.getenv("EA_PROACTIVE_OODA_SAFE_WORK_RESULT_DIR", ""))
    parser.add_argument(
        "--safe-work-results",
        action=argparse.BooleanOptionalAction,
        default=_env_truthy("EA_PROACTIVE_OODA_SAFE_WORK_RESULTS_ENABLED", default=True),
    )
    parser.add_argument(
        "--safe-work-network-fetch",
        action=argparse.BooleanOptionalAction,
        default=_env_truthy("EA_PROACTIVE_OODA_SAFE_WORK_NETWORK_FETCH_ENABLED", default=True),
    )
    parser.add_argument(
        "--safe-work-network-fetch-limit",
        type=int,
        default=int(os.getenv("EA_PROACTIVE_OODA_SAFE_WORK_NETWORK_FETCH_LIMIT", "6") or "6"),
    )
    parser.add_argument(
        "--safe-work-network-fetch-timeout-seconds",
        type=int,
        default=int(os.getenv("EA_PROACTIVE_OODA_SAFE_WORK_NETWORK_FETCH_TIMEOUT_SECONDS", "10") or "10"),
    )
    parser.add_argument(
        "--teable-sync",
        action=argparse.BooleanOptionalAction,
        default=teable_sync_enabled(),
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    state_store = JsonOodaStateStore(ROOT / args.state_path)
    signals = _load_signals(
        args,
        state_store=state_store,
        persist_opportunity_state=not args.dry_run,
    )
    service = ProactiveOodaService(
        state_store=state_store,
        max_items=args.max_items,
    )
    error_code = ""
    notification_result: object | None = None
    stored_refs = state_store.load_notified_refs(args.principal_id)
    digest = service.build_digest(
        principal_id=args.principal_id,
        signals=signals,
        already_notified_refs=stored_refs,
    )
    digest = _context_grounded_digest(args.principal_id, digest)
    if not args.dry_run:
        deferred_reason = _operator_pause_defer_reason(args, digest)
        if not deferred_reason:
            deferred_reason = _quiet_hours_defer_reason(args, digest)
        if not deferred_reason:
            deferred_reason = _interruption_budget_defer_reason(
                args,
                state_store=state_store,
                principal_id=args.principal_id,
                digest=digest,
            )
        if deferred_reason:
            digest = _without_notified_refs(digest)
            error_code = deferred_reason
    stage_packet_refs: tuple[str, ...] = ()
    stage_packet_error_count = 0
    safe_work_result_refs: tuple[str, ...] = ()
    safe_work_result_error_count = 0
    stage_packet_paths: tuple[str, ...] = ()
    safe_work_result_paths: tuple[str, ...] = ()
    if digest.items and not args.dry_run and bool(getattr(args, "stage_packets", True)):
        stage_packet_dir = _stage_packet_dir(args)
        stage_result = persist_stage_packets(
            digest=digest,
            output_dir=stage_packet_dir,
        )
        stage_packet_paths = stage_result.paths
        stage_packet_refs = stage_result.packet_refs
        stage_packet_error_count = len(stage_result.errors)
        if stage_result.paths and bool(getattr(args, "safe_work_results", True)):
            safe_work_result = persist_safe_work_results_from_paths(
                stage_packet_paths=stage_result.paths,
                result_dir=_safe_work_result_dir(args, stage_packet_dir=stage_packet_dir),
                network_fetch_enabled=bool(getattr(args, "safe_work_network_fetch", True)),
                network_fetch_limit=max(int(getattr(args, "safe_work_network_fetch_limit", 6) or 1), 1),
                network_fetch_timeout_seconds=max(int(getattr(args, "safe_work_network_fetch_timeout_seconds", 10) or 1), 1),
            )
            safe_work_result_paths = safe_work_result.paths
            safe_work_result_refs = safe_work_result.result_refs
            safe_work_result_error_count = len(safe_work_result.errors)
    safe_work_results = _notification_safe_work_previews(
        args,
        digest=digest,
        stage_packet_paths=stage_packet_paths,
        safe_work_result_paths=safe_work_result_paths,
    )
    notification_text = _format_notification_text(
        digest,
        safe_work_results=safe_work_results,
    )
    if digest.items and not args.dry_run and not error_code:
        try:
            notification_result = _telegram_notify(args.principal_id, notification_text)
            if digest.notified_markers:
                state_store.save_notified_refs(args.principal_id, stored_refs.union(digest.notified_markers))
        except Exception as exc:
            error_code = exc.__class__.__name__
    receipt = build_run_receipt(
        digest=digest,
        dry_run=args.dry_run,
        notification_result=notification_result,
        error_code=error_code,
        stage_packet_refs=stage_packet_refs,
        stage_packet_error_count=stage_packet_error_count,
        safe_work_result_refs=safe_work_result_refs,
        safe_work_result_error_count=safe_work_result_error_count,
    )
    if notification_result is not None and digest.notified_refs and not args.dry_run and not error_code:
        _record_interruption_event(
            args,
            state_store=state_store,
            principal_id=args.principal_id,
            occurred_at=receipt.generated_at,
        )
    if args.receipt_path:
        _write_receipt(Path(args.receipt_path), receipt_to_dict(receipt))
    if _env_truthy("EA_PROACTIVE_OODA_PERSIST_RECEIPTS", default=True):
        persist_proactive_ooda_receipt(principal_id=args.principal_id, digest=digest, receipt=receipt)
    teable_sync: dict[str, Any] = {
        "status": "disabled",
        "sync_attempted": False,
        "blocked_reason": "",
    }
    if bool(getattr(args, "teable_sync", False)):
        teable_sync = sync_proactive_ooda_to_teable(
            principal_id=args.principal_id,
            digest=digest,
            receipt=receipt,
            safe_work_results=safe_work_results,
        )
    if error_code and not _is_deferred_error(error_code):
        raise RuntimeError(f"proactive_ooda_notification_failed:{error_code}")
    if args.pretty:
        print(notification_text or "No actionable OODA ink.")
    else:
        print(
            json.dumps(
                {
                    "digest": digest_to_dict(digest),
                    "receipt": receipt_to_dict(receipt),
                    "teable_sync": teable_sync,
                },
                indent=2,
                sort_keys=True,
            )
        )
    return 0


def _write_receipt(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _context_grounded_digest(principal_id: str, digest: ProactiveOodaDigest) -> ProactiveOodaDigest:
    if not digest.items:
        return digest
    try:
        from app.container import build_container
        from app.services.memory_reasoning_service import MemoryReasoningService
    except Exception:
        return digest
    try:
        container = build_container()
    except Exception:
        return digest
    try:
        context_pack = MemoryReasoningService(container.memory_runtime).build_context_pack(
            principal_id=principal_id,
            task_key="proactive_ooda",
            goal="Ground proactive assistant decisions against current context and commitments.",
            limit=5,
        ).as_dict()
    except Exception:
        context_pack = {}
    try:
        preference_bundle = container.preference_profiles.get_profile_bundle(principal_id=principal_id, person_id="self")
    except Exception:
        preference_bundle = {}

    def _assess_candidate(domain: str, object_type: str, object_id: str, object_payload: dict[str, object]) -> dict[str, object] | None:
        try:
            assessment = container.preference_profiles.assess_candidate(
                principal_id=principal_id,
                person_id="self",
                domain=domain,
                object_type=object_type,
                object_id=object_id,
                object_payload=object_payload,
                persist=False,
                require_existing_profile=False,
            )
        except Exception:
            return None
        return dict(assessment or {}) if isinstance(assessment, dict) else None

    return ground_digest_with_context(
        digest,
        context_pack=context_pack,
        preference_bundle=preference_bundle,
        assess_candidate=_assess_candidate,
    )


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


def _notification_safe_work_previews(
    args: argparse.Namespace,
    *,
    digest: ProactiveOodaDigest,
    stage_packet_paths: Iterable[str | Path] = (),
    safe_work_result_paths: Iterable[str | Path] = (),
) -> tuple[dict[str, Any], ...]:
    if not digest.items or not bool(getattr(args, "safe_work_results", True)):
        return ()
    try:
        ordered_persisted = _ordered_safe_work_results_from_paths(
            stage_packet_paths=stage_packet_paths,
            safe_work_result_paths=safe_work_result_paths,
        )
        if ordered_persisted:
            return ordered_persisted
        packets = build_stage_packets(digest)
        return tuple(
            build_safe_work_result(
                packet,
                network_fetch_enabled=bool(getattr(args, "safe_work_network_fetch", True)),
                network_fetch_limit=max(int(getattr(args, "safe_work_network_fetch_limit", 6) or 1), 1),
                network_fetch_timeout_seconds=max(int(getattr(args, "safe_work_network_fetch_timeout_seconds", 10) or 1), 1),
            )
            for packet in packets
        )
    except Exception:
        return ()


def _ordered_safe_work_results_from_paths(
    *,
    stage_packet_paths: Iterable[str | Path],
    safe_work_result_paths: Iterable[str | Path],
) -> tuple[dict[str, Any], ...]:
    packet_order: list[tuple[int, str]] = []
    for raw_path in stage_packet_paths:
        payload = _read_json_object(raw_path)
        if not payload:
            continue
        packet_ref = str(payload.get("packet_ref") or "").strip()
        item_index = int(payload.get("item_index") or 0)
        if packet_ref and item_index > 0:
            packet_order.append((item_index, _hash_value(packet_ref)))
    if not packet_order:
        return ()
    result_by_packet_hash: dict[str, dict[str, Any]] = {}
    for raw_path in safe_work_result_paths:
        payload = _read_json_object(raw_path)
        packet_hash = str(payload.get("source_packet_ref_hash") or "").strip()
        if packet_hash:
            result_by_packet_hash[packet_hash] = payload
    ordered: list[dict[str, Any]] = []
    for _index, packet_hash in sorted(packet_order):
        payload = result_by_packet_hash.get(packet_hash)
        if payload:
            ordered.append(payload)
    return tuple(ordered)


def _read_json_object(path: str | Path) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _format_notification_text(
    digest: ProactiveOodaDigest,
    *,
    safe_work_results: Iterable[Mapping[str, Any]] = (),
) -> str:
    base = format_telegram_digest(digest)
    if not base:
        return ""
    results = tuple(safe_work_results)
    if not results:
        return base
    lines = base.splitlines()
    enriched: list[str] = []
    result_index = 0
    item_number = 0
    for line in lines:
        enriched.append(line)
        stripped = line.strip()
        if stripped and stripped[0].isdigit() and stripped[1:3] == ". ":
            item_number += 1
            if result_index < len(results):
                preview_lines = _safe_work_preview_lines(results[result_index])
                if preview_lines:
                    enriched.extend(preview_lines)
                result_index += 1
    return "\n".join(enriched).strip()


def _safe_work_preview_lines(result: Mapping[str, Any]) -> list[str]:
    summary = _compact_text(result.get("summary"), 220)
    recommended = _recommended_preview(result.get("recommended_option_or_draft"))
    staged_action_url = _compact_text(result.get("staged_action_url"), 180)
    shortlist = _shortlist_preview(result.get("shortlist"))
    prompt = _compact_text(result.get("approval_prompt"), 220)
    lines: list[str] = []
    if summary:
        lines.append(f"Prepared: {summary}")
    if recommended:
        lines.append(f"Recommended: {recommended}")
    if staged_action_url:
        lines.append(f"Link: {staged_action_url}")
    if shortlist:
        lines.append(f"Shortlist: {shortlist}")
    if prompt:
        lines.append(f"Approve: {prompt}")
    return lines


def _recommended_preview(value: Any) -> str:
    if not isinstance(value, Mapping):
        return _compact_text(value, 180)
    kind = str(value.get("kind") or "result").replace("_", " ").strip()
    raw = value.get("value")
    if isinstance(raw, Mapping):
        label = _compact_text(raw.get("label") or raw.get("title"), 80)
        url = _compact_text(raw.get("url") or raw.get("link") or raw.get("href"), 120)
        title = _compact_text(raw.get("page_title"), 80)
        parts = [part for part in (label, title, url) if part]
        detail = " | ".join(parts)
        return f"{kind}: {detail}" if detail else kind
    detail = _compact_text(raw, 180)
    return f"{kind}: {detail}" if detail else kind


def _shortlist_preview(value: Any, *, limit: int = 2) -> str:
    if not isinstance(value, list):
        return ""
    parts: list[str] = []
    for item in value[: max(int(limit or 1), 1)]:
        if not isinstance(item, Mapping):
            continue
        label = _compact_text(item.get("label") or item.get("title"), 60) or "candidate"
        url = _compact_text(item.get("url") or item.get("link") or item.get("href"), 100)
        reachability = ""
        if item.get("reachable") is True:
            reachability = "reachable"
        elif item.get("reachable") is False:
            reachability = "unreachable"
        page_title = _compact_text(item.get("page_title"), 60)
        detail = ", ".join(part for part in (reachability, page_title) if part)
        candidate = f"{label} - {url}" if url else label
        if detail:
            candidate = f"{candidate} ({detail})"
        parts.append(candidate)
    return " | ".join(parts)


def _compact_text(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").strip().split())
    if not text:
        return ""
    return text if len(text) <= limit else f"{text[: max(limit - 1, 1)].rstrip()}..."


def _hash_value(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def _env_truthy(name: str, *, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _quiet_hours_defer_reason(args: argparse.Namespace, digest: Any, *, now: datetime | None = None) -> str:
    if not getattr(digest, "items", ()):
        return ""
    start = _parse_local_time(getattr(args, "quiet_hours_start", ""))
    end = _parse_local_time(getattr(args, "quiet_hours_end", ""))
    if start is None or end is None:
        return ""
    if bool(getattr(args, "quiet_hours_allow_high_priority", True)) and any(item.priority == "high" for item in digest.items):
        return ""
    local_now = (now or datetime.now(timezone.utc)).astimezone(_quiet_hours_timezone(getattr(args, "quiet_hours_timezone", "")))
    return "deferred_by_quiet_hours" if _is_time_within_quiet_hours(local_now.time(), start=start, end=end) else ""


def _operator_pause_defer_reason(args: argparse.Namespace, digest: Any) -> str:
    if not getattr(digest, "items", ()):
        return ""
    return "deferred_by_operator_pause" if bool(getattr(args, "paused", False)) else ""


def _without_notified_refs(digest: ProactiveOodaDigest) -> ProactiveOodaDigest:
    return ProactiveOodaDigest(
        principal_id=digest.principal_id,
        generated_at=digest.generated_at,
        items=digest.items,
        notified_refs=(),
        notified_markers=(),
    )


def _interruption_budget_defer_reason(
    args: argparse.Namespace,
    *,
    state_store: JsonOodaStateStore,
    principal_id: str,
    digest: Any,
    now: datetime | None = None,
) -> str:
    if not getattr(digest, "items", ()):
        return ""
    limit = max(int(getattr(args, "interruption_budget_limit", 0) or 0), 0)
    if limit <= 0:
        return ""
    if bool(getattr(args, "interruption_budget_allow_high_priority", True)) and any(item.priority == "high" for item in digest.items):
        return ""
    window_hours = max(int(getattr(args, "interruption_budget_window_hours", 24) or 24), 1)
    local_now = now or datetime.now(timezone.utc)
    recent = _recent_interruption_events(
        state_store.load_interruption_events(principal_id),
        now=local_now,
        window_hours=window_hours,
    )
    return "deferred_by_interruption_budget" if len(recent) >= limit else ""


def _record_interruption_event(
    args: argparse.Namespace,
    *,
    state_store: JsonOodaStateStore,
    principal_id: str,
    occurred_at: str,
) -> None:
    window_hours = max(int(getattr(args, "interruption_budget_window_hours", 24) or 24), 1)
    now = _parse_datetime(occurred_at) or datetime.now(timezone.utc)
    recent = list(
        _recent_interruption_events(
            state_store.load_interruption_events(principal_id),
            now=now,
            window_hours=window_hours,
        )
    )
    recent.append(now.isoformat())
    state_store.save_interruption_events(principal_id, recent)


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


def _is_deferred_error(value: str) -> bool:
    return str(value or "").startswith("deferred_by_")


def _load_signals(
    args: argparse.Namespace,
    *,
    state_store: JsonOodaStateStore | None = None,
    persist_opportunity_state: bool = True,
) -> list[dict[str, Any]]:
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
            discovery = discover_signals_resilient(
                sources=sources,
                base_dir=ROOT,
                principal_id=getattr(args, "principal_id", ""),
                opportunity_state_store=state_store,
                persist_opportunity_state=persist_opportunity_state,
            )
            rows.extend(signal.__dict__ for signal in discovery.signals)
            rows.extend(_source_error_signals(discovery.errors, source_label="discovery"))
        except Exception as exc:
            rows.extend(_source_error_signals((f"discovery_json:{exc.__class__.__name__}:config",), source_label="discovery"))
    opportunity_rules_json = str(getattr(args, "opportunity_rules_json", getattr(args, "personal_rules_json", "")) or "")
    if opportunity_rules_json:
        opportunity = discover_opportunity_rule_signals(
            raw_config=opportunity_rules_json,
            base_dir=ROOT,
            principal_id=getattr(args, "principal_id", ""),
            opportunity_state_store=state_store,
            persist_opportunity_state=persist_opportunity_state,
        )
        rows.extend(signal.__dict__ for signal in opportunity.signals)
        rows.extend(_source_error_signals(opportunity.errors, source_label="opportunity_rules"))
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
