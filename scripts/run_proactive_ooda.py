#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import inspect
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
    extract_proactive_suppression_directive,
    load_signal_sources_config,
    signal_matches_proactive_suppression,
)
from app.services.proactive_ooda_receipts import persist_proactive_ooda_receipt  # noqa: E402
from app.services.proactive_ooda_runtime_artifacts import (  # noqa: E402
    default_run_receipt_dir,
    default_run_receipt_path,
)
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
from app.services.proactive_ooda_telegram_approval import (
    build_reversible_execution_approval_prompt,
    execute_proactive_ooda_action,
)
from app.services.proactive_ooda_context_grounding import ground_digest_for_principal, ground_digest_with_context  # noqa: E402
from app.services.proactive_ooda_delivery import (  # noqa: E402
    resolve_proactive_ooda_delivery_status,
    send_proactive_ooda_notification,
)
from app.services.proactive_ooda_telegram_policy import approval_request_needs_telegram_user_action  # noqa: E402
from app.services.proactive_ooda_teable_sync import (  # noqa: E402
    sync_proactive_ooda_to_teable,
    teable_sync_enabled,
)


def _default_principal_id() -> str:
    return os.getenv("EA_PROACTIVE_OODA_PRINCIPAL_ID") or os.getenv("EA_DEFAULT_PRINCIPAL_ID") or "principal-default"


def main() -> int:
    _load_dotenv_if_present(ROOT / ".env")
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
    parser.add_argument(
        "--armed-send",
        action=argparse.BooleanOptionalAction,
        default=_env_truthy("EA_PROACTIVE_OODA_ARMED_SEND", default=False),
        help="Allow this run to send on the resolved delivery route. Defaults to disabled for host/manual runs.",
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
    parser.add_argument(
        "--action-required-delivery-only",
        action=argparse.BooleanOptionalAction,
        default=_env_truthy("EA_PROACTIVE_OODA_ACTION_REQUIRED_DELIVERY_ONLY", default=True),
        help="Only notify when the packet has a concrete user action surface; otherwise keep it in receipts/Teable.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    if not str(args.receipt_path or "").strip():
        args.receipt_path = str(default_run_receipt_path(root=ROOT, state_path=args.state_path))

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
        if not deferred_reason:
            deferred_reason = _unarmed_send_defer_reason(args, digest)
        if deferred_reason:
            digest = _without_notified_refs(digest)
            error_code = deferred_reason
    stage_packet_refs: tuple[str, ...] = ()
    stage_packet_error_count = 0
    safe_work_result_refs: tuple[str, ...] = ()
    safe_work_result_error_count = 0
    stage_packet_paths: tuple[str, ...] = ()
    safe_work_result_paths: tuple[str, ...] = ()
    auto_execution_results: tuple[dict[str, Any], ...] = ()
    stage_packet_dir = _stage_packet_dir(args)
    safe_work_result_dir = _safe_work_result_dir(args, stage_packet_dir=stage_packet_dir)
    if digest.items and not args.dry_run and bool(getattr(args, "stage_packets", True)):
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
                result_dir=safe_work_result_dir,
                network_fetch_enabled=bool(getattr(args, "safe_work_network_fetch", True)),
                network_fetch_limit=max(int(getattr(args, "safe_work_network_fetch_limit", 6) or 1), 1),
                network_fetch_timeout_seconds=max(int(getattr(args, "safe_work_network_fetch_timeout_seconds", 10) or 1), 1),
            )
            safe_work_result_paths = safe_work_result.paths
            safe_work_result_refs = safe_work_result.result_refs
            safe_work_result_error_count = len(safe_work_result.errors)
    if (
        digest.items
        and not args.dry_run
        and not error_code
        and stage_packet_paths
        and safe_work_result_paths
    ):
        auto_execution_results = _auto_execute_proactive_ooda_actions(
            principal_id=args.principal_id,
            stage_packet_paths=stage_packet_paths,
            safe_work_result_paths=safe_work_result_paths,
            root=ROOT,
            state_path=args.state_path,
            receipt_path=args.receipt_path,
            stage_packet_dir=stage_packet_dir,
            safe_work_result_dir=safe_work_result_dir,
        )
    safe_work_results = _notification_safe_work_previews(
        args,
        digest=digest,
        stage_packet_paths=stage_packet_paths,
        safe_work_result_paths=safe_work_result_paths,
    )
    if (
        digest.items
        and not args.dry_run
        and not error_code
        and bool(getattr(args, "safe_work_results", True))
        and safe_work_results
        and not any(bool(getattr(item, "approval_required", False)) for item in digest.items)
        and not _has_decision_ready_safe_work(safe_work_results)
    ):
        digest = _without_notified_refs(digest)
        error_code = "no_decision_ready_safe_work"
    notification_text = _format_notification_text(
        digest,
        safe_work_results=safe_work_results,
    )
    approval_request = _notification_approval_request(
        stage_packet_paths=stage_packet_paths,
        safe_work_result_paths=safe_work_result_paths,
        auto_execute_results=auto_execution_results,
    )
    if (
        digest.items
        and not args.dry_run
        and not error_code
        and bool(getattr(args, "action_required_delivery_only", True))
        and not _notification_requires_user_action(approval_request)
    ):
        digest = _without_notified_refs(digest)
        error_code = "no_user_action_required"
    if digest.items and not args.dry_run and not error_code:
        try:
            deliver_kwargs: dict[str, Any] = {
                "digest": digest,
            }
            if approval_request is not None and _callable_accepts_keyword(_deliver_notification, "approval_request"):
                deliver_kwargs["approval_request"] = approval_request
            notification_result = _deliver_notification(
                args.principal_id,
                notification_text,
                **deliver_kwargs,
            )
            if digest.notified_markers:
                state_store.save_notified_refs(args.principal_id, stored_refs.union(digest.notified_markers))
        except Exception as exc:
            error_code = _notification_error_code(exc)
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
    if args.receipt_path:
        receipt_payload = _receipt_payload(
            receipt=receipt,
            teable_sync=teable_sync,
            stage_packet_dir=stage_packet_dir,
            safe_work_result_dir=safe_work_result_dir,
            auto_execute_results=auto_execution_results,
        )
        _write_receipt(Path(args.receipt_path), receipt_payload)
        _write_receipt(_archived_receipt_path(args, payload=receipt_payload), receipt_payload)
    if error_code and not _is_deferred_error(error_code):
        raise RuntimeError(f"proactive_ooda_notification_failed:{error_code}")
    if args.pretty:
        print(notification_text or "No actionable OODA ink.")
    else:
        print(
            json.dumps(
                {
                    "digest": digest_to_dict(digest),
                    "receipt": _receipt_payload(
                        receipt=receipt,
                        teable_sync=teable_sync,
                        stage_packet_dir=stage_packet_dir,
                        safe_work_result_dir=safe_work_result_dir,
                    ),
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


def _archived_receipt_path(args: argparse.Namespace, *, payload: Mapping[str, Any]) -> Path:
    archive_dir = default_run_receipt_dir(
        root=ROOT,
        state_path=str(args.state_path or ""),
        receipt_path=str(args.receipt_path or ""),
    )
    generated_at = str(payload.get("generated_at") or "").strip()
    timestamp = (
        generated_at.replace("-", "").replace(":", "").replace("+", "_").replace(".", "_")
        if generated_at
        else datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z").replace("-", "").replace(":", "")
    )
    status = str(payload.get("notification_status") or "unknown").strip().lower().replace(" ", "_") or "unknown"
    material = "|".join(
        (
            generated_at,
            status,
            str(payload.get("principal_id_hash") or "").strip(),
            ",".join(str(item or "").strip() for item in list(payload.get("notified_ref_hashes") or [])),
            ",".join(str(item or "").strip() for item in list(payload.get("stage_packet_ref_hashes") or [])),
            ",".join(str(item or "").strip() for item in list(payload.get("safe_work_result_ref_hashes") or [])),
        )
    )
    receipt_hash = hashlib.sha256(material.encode("utf-8")).hexdigest()[:12]
    return archive_dir / f"{timestamp}-{status}-{receipt_hash}.json"


def _receipt_payload(
    *,
    receipt: Any,
    teable_sync: Mapping[str, Any],
    stage_packet_dir: Path,
    safe_work_result_dir: Path,
    auto_execute_results: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    payload = receipt_to_dict(receipt)
    payload["stage_packet_output_dir"] = str(stage_packet_dir)
    payload["safe_work_result_output_dir"] = str(safe_work_result_dir)
    payload["auto_execute_results"] = tuple(
        _redact_auto_execute_result(result) for result in auto_execute_results
    )
    payload["teable_sync"] = {
        "status": str(teable_sync.get("status") or "").strip(),
        "sync_attempted": bool(teable_sync.get("sync_attempted")),
        "blocked_reason": str(teable_sync.get("blocked_reason") or "").strip(),
        "missing_tables": [
            str(item or "").strip()
            for item in list(teable_sync.get("missing_tables") or [])
            if str(item or "").strip()
        ],
        "projection_summary": dict(teable_sync.get("projection_summary") or {}),
    }
    return payload


def _auto_execute_proactive_ooda_actions(
    *,
    principal_id: str,
    stage_packet_paths: Iterable[str | Path],
    safe_work_result_paths: Iterable[str | Path],
    root: Path,
    state_path: str | Path,
    receipt_path: str | Path,
    stage_packet_dir: Path,
    safe_work_result_dir: Path,
) -> tuple[dict[str, Any], ...]:
    candidates = tuple(
        _proactive_ooda_auto_execute_candidates(
            stage_packet_paths=stage_packet_paths,
            safe_work_result_paths=safe_work_result_paths,
        )
    )
    if not candidates:
        return ()

    try:
        from app.container import build_container

        container = build_container()
    except Exception:
        return ()

    results: list[dict[str, Any]] = []
    for candidate in candidates:
        execution = execute_proactive_ooda_action(
            container=container,
            principal_id=principal_id,
            packet_ref=candidate["packet_ref"],
            staged_artifact_ref=candidate["staged_artifact_ref"],
            root=root,
            state_path=state_path,
            receipt_path=receipt_path,
            stage_packet_dir=stage_packet_dir,
            safe_work_result_dir=safe_work_result_dir,
        )
        results.append(
            {
                "packet_ref": candidate["packet_ref"],
                "staged_artifact_ref": candidate["staged_artifact_ref"],
                "execution": execution,
                "result_id": candidate["result_id"],
            }
        )
    return tuple(results)


def _proactive_ooda_auto_execute_candidates(
    *,
    stage_packet_paths: Iterable[str | Path],
    safe_work_result_paths: Iterable[str | Path],
) -> tuple[Mapping[str, str], ...]:
    stage_packets_by_hash = {}
    for raw_path in stage_packet_paths:
        stage_packet = _read_json_object(raw_path)
        packet_ref = str(stage_packet.get("packet_ref") or "").strip()
        if not packet_ref:
            continue
        stage_packets_by_hash[_hash_value(packet_ref)] = stage_packet

    candidates: list[dict[str, str]] = []
    for result in _ordered_safe_work_results_from_paths(
        stage_packet_paths=stage_packet_paths,
        safe_work_result_paths=safe_work_result_paths,
    ):
        packet_ref = ""
        result_ref = str(result.get("result_ref") or "").strip()
        if not result_ref:
            continue
        result_id = str(result.get("result_id") or "").strip()
        stage_hash = str(result.get("source_packet_ref_hash") or "").strip()
        stage_packet = stage_packets_by_hash.get(stage_hash)
        if not stage_packet:
            continue
        packet_ref = str(stage_packet.get("packet_ref") or "").strip()
        if not packet_ref:
            continue
        approval = dict(stage_packet.get("approval") or {})
        if bool(approval.get("required")):
            continue
        stage_payload = dict(dict(stage_packet.get("stage") or {}).get("payload") or {})
        auto_execute_action = str(stage_payload.get("auto_execute_action") or "").strip().lower()
        if auto_execute_action != "save_gmail_draft":
            continue
        candidates.append(
            {
                "packet_ref": packet_ref,
                "staged_artifact_ref": result_ref,
                "result_id": result_id or result_ref,
            }
        )
    return tuple(candidates)


def _redact_auto_execute_result(result: Mapping[str, Any]) -> Mapping[str, Any]:
    execution = dict(result.get("execution") or {})
    return {
        "packet_ref_hash": _hash_value(str(result.get("packet_ref") or "").strip()),
        "safe_work_result_ref_hash": _hash_value(str(result.get("staged_artifact_ref") or "").strip()),
        "status": str(execution.get("status") or "").strip(),
        "action": str(execution.get("action") or "").strip(),
        "reason": str(execution.get("reason") or "").strip(),
        "result_id": str(result.get("result_id") or "").strip(),
    }


def _context_grounded_digest(principal_id: str, digest: ProactiveOodaDigest) -> ProactiveOodaDigest:
    if not digest.items:
        return digest
    try:
        from app.container import build_container
    except Exception:
        return digest
    try:
        container = build_container()
    except Exception:
        return digest
    return ground_digest_for_principal(
        digest,
        principal_id=principal_id,
        memory_runtime=container.memory_runtime,
        preference_profiles=container.preference_profiles,
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


def _has_decision_ready_safe_work(safe_work_results: Iterable[Mapping[str, Any]]) -> bool:
    for result in safe_work_results:
        if not isinstance(result, Mapping):
            continue
        if str(result.get("status") or "").strip() == "staged_for_user_decision":
            return True
    return False


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


def _notification_approval_request(
    *,
    stage_packet_paths: Iterable[str | Path],
    safe_work_result_paths: Iterable[str | Path],
    auto_execute_results: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any] | None:
    ordered_results = _ordered_safe_work_results_from_paths(
        stage_packet_paths=stage_packet_paths,
        safe_work_result_paths=safe_work_result_paths,
    )
    stage_packets_by_hash: dict[str, dict[str, Any]] = {}
    for raw_path in stage_packet_paths:
        payload = _read_json_object(raw_path)
        packet_ref = str(payload.get("packet_ref") or "").strip()
        if packet_ref:
            stage_packets_by_hash[_hash_value(packet_ref)] = payload
    auto_executed_pairs: set[tuple[str, str, str, str]] = set()
    for row in auto_execute_results:
        if not isinstance(row, Mapping):
            continue
        execution = dict(row.get("execution") or {})
        action = str(execution.get("action") or row.get("action") or "").strip().lower()
        status = str(execution.get("status") or row.get("status") or "").strip().lower()
        packet_ref = str(row.get("packet_ref") or "").strip()
        staged_artifact_ref = str(row.get("staged_artifact_ref") or "").strip()
        if not packet_ref or not staged_artifact_ref or not action or not status:
            continue
        auto_executed_pairs.add((packet_ref, staged_artifact_ref, action, status))
    for result in ordered_results:
        if str(result.get("status") or "").strip() != "staged_for_user_decision":
            continue
        packet_hash = str(result.get("source_packet_ref_hash") or "").strip()
        stage_packet = stage_packets_by_hash.get(packet_hash, {})
        approval = dict(stage_packet.get("approval") or {})
        packet_ref = str(stage_packet.get("packet_ref") or "").strip()
        staged_artifact_ref = str(result.get("result_ref") or "").strip()
        if not packet_ref or not staged_artifact_ref:
            continue
        if bool(approval.get("required")):
            return {
                "packet_ref": packet_ref,
                "staged_artifact_ref": staged_artifact_ref,
                "approval_prompt": str(result.get("approval_prompt") or "").strip(),
                "staged_action_url": str(result.get("staged_action_url") or "").strip(),
            }
        stage_payload = dict(dict(stage_packet.get("stage") or {}).get("payload") or {})
        auto_execute_action = str(stage_payload.get("auto_execute_action") or "").strip().lower()
        if auto_execute_action and (packet_ref, staged_artifact_ref, auto_execute_action, "executed") in auto_executed_pairs:
            return {
                "packet_ref": packet_ref,
                "staged_artifact_ref": staged_artifact_ref,
                "approval_prompt": build_reversible_execution_approval_prompt(action=auto_execute_action),
                "staged_action_url": str(result.get("staged_action_url") or "").strip(),
                "approved_execution_mode": "record_outcome_only",
                "approved_action": auto_execute_action,
            }
        return {
            "packet_ref": packet_ref,
            "staged_artifact_ref": staged_artifact_ref,
            "approval_prompt": str(result.get("approval_prompt") or "").strip(),
            "staged_action_url": str(result.get("staged_action_url") or "").strip(),
        }
    return None


def _notification_requires_user_action(approval_request: Mapping[str, Any] | None) -> bool:
    return approval_request_needs_telegram_user_action(approval_request)


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
    return format_telegram_digest(digest, safe_work_results=safe_work_results)


def _hash_value(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def _env_truthy(name: str, *, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _notification_error_code(exc: Exception) -> str:
    detail = " ".join(str(exc or "").split()).strip()
    if detail and all(char.isalnum() or char in {":", "_", "-"} for char in detail):
        return detail[:200]
    return exc.__class__.__name__


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


def _unarmed_send_defer_reason(args: argparse.Namespace, digest: Any) -> str:
    if not getattr(digest, "items", ()):
        return ""
    return "" if bool(getattr(args, "armed_send", False)) else "deferred_by_unarmed_send"


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
    normalized = str(value or "").strip()
    return normalized.startswith("deferred_by_") or normalized in {
        "no_decision_ready_safe_work",
        "no_user_action_required",
    }


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
        return _apply_recent_topic_suppressions(rows)
    try:
        from app.container import build_container
        from app.services.google_oauth import list_recent_workspace_signals
    except Exception as exc:  # pragma: no cover - depends on full runtime being present
        if _workspace_source_not_configured(exc):
            return _apply_recent_topic_suppressions(rows)
        return _apply_recent_topic_suppressions(rows + [_workspace_source_error_signal(exc)])
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
        if _workspace_source_not_configured(exc):
            return _apply_recent_topic_suppressions(rows)
        return _apply_recent_topic_suppressions(rows + [_workspace_source_error_signal(exc)])
    for signal in packet.signals:
        if hasattr(signal, "__dict__"):
            rows.append(dict(signal.__dict__))
    return _apply_recent_topic_suppressions(rows)


def _apply_recent_topic_suppressions(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    suppressions = [
        directive
        for directive in (extract_proactive_suppression_directive(row) for row in rows)
        if directive is not None
    ]
    if not suppressions:
        return rows
    filtered: list[dict[str, Any]] = []
    for row in rows:
        if extract_proactive_suppression_directive(row) is not None:
            filtered.append(row)
            continue
        row_source_ref = str(row.get("source_ref") or "").strip()
        row_created_at = _signal_created_at(row)
        suppressed = False
        for suppression in suppressions:
            if row_source_ref and row_source_ref == str(suppression.get("source_ref") or "").strip():
                continue
            suppression_created_at = _parse_timestamp(str(suppression.get("observed_at") or "").strip())
            if row_created_at is not None and suppression_created_at is not None and row_created_at > suppression_created_at:
                continue
            if signal_matches_proactive_suppression(row, suppression):
                suppressed = True
                break
        if not suppressed:
            filtered.append(row)
    return filtered


def _signal_created_at(row: Mapping[str, Any]) -> datetime | None:
    payload = row.get("payload") if isinstance(row.get("payload"), Mapping) else {}
    candidates = (
        row.get("created_at"),
        payload.get("created_at") if isinstance(payload, Mapping) else "",
    )
    for candidate in candidates:
        parsed = _parse_timestamp(str(candidate or "").strip())
        if parsed is not None:
            return parsed
    return None


def _parse_timestamp(value: str) -> datetime | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    try:
        return datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        return None


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


_WORKSPACE_SOURCE_NOT_CONFIGURED_ERRORS = {
    "google_oauth_binding_not_found",
    "google_oauth_client_id_missing",
    "google_oauth_client_secret_missing",
    "google_oauth_redirect_uri_missing",
    "google_oauth_state_secret_missing",
    "google_oauth_provider_secret_key_missing",
}


def _workspace_source_error_detail(exc: Exception) -> str:
    raw = str(exc or exc.__class__.__name__).strip()
    if raw and all(char.isalnum() or char in {"_", ":", ".", "-", "+"} for char in raw):
        return raw[:160]
    return exc.__class__.__name__


def _workspace_source_not_configured(exc: Exception) -> bool:
    return _workspace_source_error_detail(exc) in _WORKSPACE_SOURCE_NOT_CONFIGURED_ERRORS


def _workspace_source_error_signal(exc: Exception) -> dict[str, Any]:
    error_name = exc.__class__.__name__
    error_text = _workspace_source_error_detail(exc)
    summary = "Google workspace scanning is failing, so EA cannot reliably inspect Gmail or Calendar for proactive nudges."
    action = "Reauthorize Google for the EA principal, then rerun the proactive OODA verifier."
    return {
        "source_ref": f"proactive_source_error:google_workspace:{_short_hash(error_text or error_name)}",
        "signal_type": "proactive_source_health",
        "channel": "proactive_runtime",
        "title": "EA cannot scan Google workspace",
        "summary": summary,
        "counterparty": "Google workspace",
        "payload": {
            "reason_code": error_text or error_name,
            "ooda_loop": _source_health_ooda(summary, action),
        },
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


def _callable_accepts_keyword(fn: object, name: str) -> bool:
    try:
        signature = inspect.signature(fn)
    except Exception:
        return True
    for parameter in signature.parameters.values():
        if parameter.kind == inspect.Parameter.VAR_KEYWORD:
            return True
    return name in signature.parameters


def _delivery_status(principal_id: str, *, digest: ProactiveOodaDigest | None = None) -> object:
    try:
        from app.container import build_container
    except Exception:
        return resolve_proactive_ooda_delivery_status(principal_id=principal_id, digest=digest)
    try:
        container = build_container()
    except Exception:
        return resolve_proactive_ooda_delivery_status(principal_id=principal_id, digest=digest)
    if not hasattr(container, "tool_runtime") or not hasattr(container, "memory_runtime"):
        return resolve_proactive_ooda_delivery_status(principal_id=principal_id, digest=digest)
    return resolve_proactive_ooda_delivery_status(
        principal_id=principal_id,
        tool_runtime=container.tool_runtime,
        memory_runtime=container.memory_runtime,
        digest=digest,
    )


def _deliver_notification(
    principal_id: str,
    text: str,
    *,
    digest: ProactiveOodaDigest | None = None,
    approval_request: Mapping[str, Any] | None = None,
) -> object:
    try:
        from app.container import build_container
    except Exception:
        kwargs: dict[str, Any] = {
            "principal_id": principal_id,
            "text": text,
            "digest": digest,
        }
        if approval_request is not None:
            kwargs["approval_request"] = approval_request
        return send_proactive_ooda_notification(
            **kwargs,
        )
    try:
        container = build_container()
    except Exception:
        kwargs: dict[str, Any] = {
            "principal_id": principal_id,
            "text": text,
            "digest": digest,
        }
        if approval_request is not None:
            kwargs["approval_request"] = approval_request
        return send_proactive_ooda_notification(**kwargs)
    kwargs = {
        "principal_id": principal_id,
        "text": text,
        "tool_runtime": container.tool_runtime,
        "channel_runtime": container.channel_runtime,
        "memory_runtime": container.memory_runtime,
        "digest": digest,
    }
    if approval_request is not None:
        kwargs["approval_request"] = approval_request
    return send_proactive_ooda_notification(**kwargs)


if __name__ == "__main__":
    raise SystemExit(main())
