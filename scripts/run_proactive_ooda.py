#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import logging
import os
import sys
import tempfile
from contextlib import contextmanager
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
    RUN_RECEIPT_DIRNAME,
    default_run_receipt_dir,
    default_run_receipt_path,
)
from app.services.proactive_ooda_safe_work import (  # noqa: E402
    build_safe_work_result,
    default_safe_work_result_dir,
    persist_safe_work_results_from_paths,
    safe_work_decision_materiality_issue,
)
from app.services.proactive_ooda_stage_packets import (  # noqa: E402
    build_stage_packets,
    default_stage_packet_dir,
    persist_stage_packets,
)
from app.services.proactive_ooda_telegram_approval import (
    build_reversible_execution_approval_prompt,
    execute_proactive_ooda_action,
    expire_stale_proactive_ooda_telegram_approval_callbacks,
)
from app.services.proactive_ooda_context_grounding import ground_digest_for_principal, ground_digest_with_context  # noqa: E402
from app.services.proactive_ooda_delivery import (  # noqa: E402
    resolve_proactive_ooda_delivery_status,
    send_proactive_ooda_notification,
)
from app.services.proactive_ooda_goal_actions import (  # noqa: E402
    DEFAULT_GOAL_ACTION_QUEUE_LIMIT,
    load_goal_action_queue_signals,
)
from app.services.proactive_ooda_telegram_policy import approval_request_needs_telegram_user_action  # noqa: E402
from app.services.proactive_ooda_teable_sync import (  # noqa: E402
    sync_proactive_ooda_to_teable,
    teable_sync_enabled,
)
from app.services.proactive_source_health_policy import source_health_issue_requires_user_action  # noqa: E402
from app.services.assistant_property_boundary_cleanup import (  # noqa: E402
    cleanup_hidden_property_runtime_state,
)
from app.services.assistant_property_lane import (  # noqa: E402
    assistant_property_lane_enabled,
    assistant_property_signal_present,
)


def _default_principal_id() -> str:
    return os.getenv("EA_PROACTIVE_OODA_PRINCIPAL_ID") or os.getenv("EA_DEFAULT_PRINCIPAL_ID") or "principal-default"


@contextmanager
def _suppress_container_postgres_fallback_warning():
    logger = logging.getLogger("ea.container")

    class _PostgresFallbackFilter(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            try:
                message = record.getMessage()
            except Exception:
                message = str(getattr(record, "msg", "") or "")
            return "postgres runtime profile unavailable, switching whole container to memory" not in message

    noise_filter = _PostgresFallbackFilter()
    logger.addFilter(noise_filter)
    try:
        yield
    finally:
        logger.removeFilter(noise_filter)


def _build_postgres_container_for_script() -> object | None:
    try:
        from app.container import build_container
    except Exception:
        return None
    try:
        with _suppress_container_postgres_fallback_warning():
            container = build_container()
    except Exception:
        return None
    runtime_profile = getattr(container, "runtime_profile", None)
    storage_backend = str(getattr(runtime_profile, "storage_backend", "") or "").strip().lower()
    if storage_backend and storage_backend != "postgres":
        return None
    return container


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
        "--goal-posture-json",
        default=os.getenv(
            "EA_PROACTIVE_OODA_GOAL_POSTURE_JSON",
            ".codex-studio/published/ea_continuous_improvement_goal_posture.generated.json",
        ),
        help="Continuous-improvement goal posture receipt whose operator action queue can become action-required OODA signals.",
    )
    parser.add_argument(
        "--include-goal-action-queue",
        action=argparse.BooleanOptionalAction,
        default=_env_truthy("EA_PROACTIVE_OODA_INCLUDE_GOAL_ACTION_QUEUE", default=True),
        help="Ingest sanitized user-action-required rows from the goal posture operator action queue.",
    )
    parser.add_argument(
        "--operator-action-required-digest-json",
        default=os.getenv(
            "EA_PROACTIVE_OODA_OPERATOR_ACTION_REQUIRED_DIGEST_JSON",
            ".codex-studio/published/ea_operator_action_required_digest.generated.json",
        ),
        help="Published operator action-required digest refreshed after the live run.",
    )
    parser.add_argument(
        "--operator-action-required-digest-state-path",
        default=os.getenv(
            "EA_PROACTIVE_OODA_OPERATOR_ACTION_REQUIRED_DIGEST_STATE_PATH",
            ".runtime/ea_operator_action_required_digest_state.json",
        ),
        help="State file used to suppress duplicate operator action-required digest sends.",
    )
    parser.add_argument(
        "--goal-action-queue-limit",
        type=int,
        default=int(os.getenv("EA_PROACTIVE_OODA_GOAL_ACTION_QUEUE_LIMIT", str(DEFAULT_GOAL_ACTION_QUEUE_LIMIT)) or "1"),
        help="Maximum goal-posture action queue rows to surface per run. Defaults to one prioritized action.",
    )
    parser.add_argument(
        "--goal-action-operator-streams",
        default=os.getenv("EA_PROACTIVE_OODA_GOAL_ACTION_OPERATOR_STREAMS", ""),
        help=(
            "Optional comma-separated operator streams to ingest from goal posture action rows. "
            "Defaults to the posture's published action-digest streams."
        ),
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
    parser.add_argument(
        "--notification-cooldown-seconds",
        type=int,
        default=int(os.getenv("EA_PROACTIVE_OODA_NOTIFICATION_COOLDOWN_SECONDS", "1800") or "1800"),
        help="Minimum gap between proactive sends for the same principal; 0 disables this guard.",
    )
    parser.add_argument(
        "--notification-cooldown-allow-high-priority",
        action=argparse.BooleanOptionalAction,
        default=_env_truthy("EA_PROACTIVE_OODA_NOTIFICATION_COOLDOWN_ALLOW_HIGH_PRIORITY", default=True),
        help="Allow high-priority digests to bypass the proactive send cooldown.",
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
    parser.add_argument(
        "--mirror-delivery-proof",
        action=argparse.BooleanOptionalAction,
        default=_env_truthy("EA_PROACTIVE_OODA_MIRROR_DELIVERY_PROOF", default=False),
        help="Mirror one action-required packet into receipts/Teable without sending a user notification.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    if not str(args.receipt_path or "").strip():
        args.receipt_path = str(default_run_receipt_path(root=ROOT, state_path=args.state_path))

    property_boundary_cleanup = _cleanup_hidden_property_boundary(args)
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
    signals, digest = _recover_sparse_observation_digest(
        args,
        state_store=state_store,
        stored_refs=stored_refs,
        service=service,
        signals=signals,
        digest=digest,
    )
    source_health = _source_health_summary(signals)
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
            deferred_reason = _notification_cooldown_defer_reason(
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
    approval_callback_cleanup = _cleanup_approval_callbacks(
        args,
        approval_request=approval_request,
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
    delivery_mirror: dict[str, Any] = {}
    if digest.items and not args.dry_run and not error_code and bool(getattr(args, "mirror_delivery_proof", False)):
        delivery_mirror = _delivery_mirror_receipt(
            approval_request=approval_request,
            notification_text=notification_text,
        )
        digest = _without_notified_refs(digest)
        error_code = "mirrored_delivery_proof"
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
    delivery_guard = _delivery_guard_snapshot(
        args,
        state_store=state_store,
        principal_id=args.principal_id,
        digest=digest,
        approval_request=approval_request,
        safe_work_results=safe_work_results,
        error_code=error_code,
    )
    receipt = build_run_receipt(
        digest=digest,
        dry_run=args.dry_run,
        notification_result=notification_result,
        error_code=error_code,
        stage_packet_refs=stage_packet_refs,
        stage_packet_error_count=stage_packet_error_count,
        safe_work_result_refs=safe_work_result_refs,
        safe_work_result_error_count=safe_work_result_error_count,
        delivery_guard=delivery_guard,
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
    followthrough_artifacts: dict[str, Any] = {}
    if args.receipt_path:
        receipt_payload = _receipt_payload(
            receipt=receipt,
            teable_sync=teable_sync,
            stage_packet_dir=stage_packet_dir,
            safe_work_result_dir=safe_work_result_dir,
            auto_execute_results=auto_execution_results,
            delivery_mirror=delivery_mirror,
            source_health=source_health,
            approval_callback_cleanup=approval_callback_cleanup,
            property_boundary_cleanup=property_boundary_cleanup,
        )
        _write_receipt(Path(args.receipt_path), receipt_payload)
        _write_receipt(_archived_receipt_path(args, payload=receipt_payload), receipt_payload)
        followthrough_artifacts = _materialize_followthrough_artifacts(
            args,
            receipt_path=Path(args.receipt_path),
            stage_packet_dir=stage_packet_dir,
            safe_work_result_dir=safe_work_result_dir,
            current_runtime_artifacts_present=bool(stage_packet_refs or safe_work_result_refs),
        )
        receipt_payload = _receipt_payload(
            receipt=receipt,
            teable_sync=teable_sync,
            stage_packet_dir=stage_packet_dir,
            safe_work_result_dir=safe_work_result_dir,
            auto_execute_results=auto_execution_results,
            delivery_mirror=delivery_mirror,
            source_health=source_health,
            approval_callback_cleanup=approval_callback_cleanup,
            property_boundary_cleanup=property_boundary_cleanup,
            followthrough_artifacts=followthrough_artifacts,
        )
        _write_receipt(Path(args.receipt_path), receipt_payload)
        _write_receipt(_archived_receipt_path(args, payload=receipt_payload), receipt_payload)
        if str(dict(followthrough_artifacts.get("operator_status") or {}).get("reason") or "").strip() == "followthrough_artifacts_missing":
            followthrough_artifacts = _materialize_followthrough_artifacts(
                args,
                receipt_path=Path(args.receipt_path),
                stage_packet_dir=stage_packet_dir,
                safe_work_result_dir=safe_work_result_dir,
                current_runtime_artifacts_present=bool(stage_packet_refs or safe_work_result_refs),
            )
            receipt_payload = _receipt_payload(
                receipt=receipt,
                teable_sync=teable_sync,
                stage_packet_dir=stage_packet_dir,
                safe_work_result_dir=safe_work_result_dir,
                auto_execute_results=auto_execution_results,
                delivery_mirror=delivery_mirror,
                source_health=source_health,
                approval_callback_cleanup=approval_callback_cleanup,
                property_boundary_cleanup=property_boundary_cleanup,
                followthrough_artifacts=followthrough_artifacts,
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
                        delivery_mirror=delivery_mirror,
                        source_health=source_health,
                        approval_callback_cleanup=approval_callback_cleanup,
                        property_boundary_cleanup=property_boundary_cleanup,
                        followthrough_artifacts=followthrough_artifacts,
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
    serialized = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
            temp_path = Path(handle.name)
        if temp_path is None:
            raise OSError("receipt_tempfile_missing")
        temp_path.replace(path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink(missing_ok=True)


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


def _receipt_artifact_root(receipt_path: Path) -> Path:
    if receipt_path.parent.name == RUN_RECEIPT_DIRNAME:
        return receipt_path.parent.parent
    return receipt_path.parent


def _followthrough_runtime_context(
    args: argparse.Namespace,
    *,
    receipt_path: Path,
    stage_packet_dir: Path,
    safe_work_result_dir: Path,
    current_runtime_artifacts_present: bool,
) -> dict[str, Path]:
    if current_runtime_artifacts_present:
        state_path_value = Path(
            str(getattr(args, "state_path", "state/proactive_ooda_notified.json") or "state/proactive_ooda_notified.json")
        )
        resolved_state_path = state_path_value if state_path_value.is_absolute() else ROOT / state_path_value
        return {
            "state_path": resolved_state_path,
            "stage_packet_dir": stage_packet_dir,
            "safe_work_result_dir": safe_work_result_dir,
        }
    artifact_root = _receipt_artifact_root(receipt_path)
    return {
        "state_path": artifact_root / "proactive_ooda_notified.json",
        "stage_packet_dir": artifact_root / "proactive_ooda_stage_packets",
        "safe_work_result_dir": artifact_root / "proactive_ooda_safe_work_results",
    }


def _operator_status_google_workspace_reauth_required_reason(operator_status: Mapping[str, Any]) -> str:
    payload = dict(operator_status or {})
    source_health = dict(payload.get("source_health") or {})
    for raw_issue in list(source_health.get("issues") or []):
        issue = dict(raw_issue or {}) if isinstance(raw_issue, Mapping) else {}
        source_key = str(issue.get("source_key") or issue.get("source_type") or "").strip()
        if source_key != "google_workspace":
            continue
        if not source_health_issue_requires_user_action(issue):
            continue
        error_code = str(issue.get("error_code") or issue.get("reason_code") or "").strip()
        if error_code:
            return error_code
    reason = str(payload.get("reason") or "").strip()
    for prefix in (
        "source_health_google_workspace:",
        "google_workspace_signal_source_unhealthy:",
    ):
        if reason.startswith(prefix):
            return reason[len(prefix) :].strip()
    return ""


def _receipt_payload(
    *,
    receipt: Any,
    teable_sync: Mapping[str, Any],
    stage_packet_dir: Path,
    safe_work_result_dir: Path,
    auto_execute_results: Iterable[Mapping[str, Any]] = (),
    delivery_mirror: Mapping[str, Any] | None = None,
    source_health: Mapping[str, Any] | None = None,
    approval_callback_cleanup: Mapping[str, Any] | None = None,
    property_boundary_cleanup: Mapping[str, Any] | None = None,
    followthrough_artifacts: Mapping[str, Any] | None = None,
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
    if delivery_mirror:
        payload["delivery_mirror"] = dict(delivery_mirror)
    payload["source_health"] = dict(source_health or _source_health_summary(()))
    if approval_callback_cleanup:
        payload["approval_callback_cleanup"] = dict(approval_callback_cleanup)
    if property_boundary_cleanup:
        payload["property_boundary_cleanup"] = dict(property_boundary_cleanup)
    if followthrough_artifacts:
        payload["followthrough_artifacts"] = dict(followthrough_artifacts)
    return payload


def _materialize_followthrough_artifacts(
    args: argparse.Namespace,
    *,
    receipt_path: Path,
    stage_packet_dir: Path,
    safe_work_result_dir: Path,
    current_runtime_artifacts_present: bool,
) -> dict[str, Any]:
    if bool(getattr(args, "dry_run", False)):
        return {
            "status": "skipped",
            "reason": "dry_run",
            "run_receipt_path": _display_root_relative_path(receipt_path),
        }

    builders = _load_followthrough_builders()
    operator_status_path = _root_relative_path(
        "",
        default_relative=".codex-studio/published/ea_proactive_ooda_operator_status.generated.json",
    )
    gold_acceptance_path = _root_relative_path(
        "",
        default_relative=".codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json",
    )
    goal_posture_path = _root_relative_path(
        str(getattr(args, "goal_posture_json", "") or ""),
        default_relative=".codex-studio/published/ea_continuous_improvement_goal_posture.generated.json",
    )
    digest_path = _root_relative_path(
        str(getattr(args, "operator_action_required_digest_json", "") or ""),
        default_relative=".codex-studio/published/ea_operator_action_required_digest.generated.json",
    )
    digest_state_path = _root_relative_path(
        str(getattr(args, "operator_action_required_digest_state_path", "") or ""),
        default_relative=".runtime/ea_operator_action_required_digest_state.json",
    )
    dedupe_proof_path = _root_relative_path(
        "",
        default_relative=".codex-studio/published/ea_operator_action_required_dedupe_proof.generated.json",
    )
    google_workspace_oauth_readiness_path = _root_relative_path(
        "",
        default_relative=".codex-studio/published/ea_google_workspace_oauth_readiness.generated.json",
    )
    summary: dict[str, Any] = {
        "status": "ok",
        "reason": "",
        "run_receipt_path": _display_root_relative_path(receipt_path),
        "operator_status": {
            "path": _display_root_relative_path(operator_status_path),
            "status": "pending",
        },
        "gold_acceptance": {
            "path": _display_root_relative_path(gold_acceptance_path),
            "status": "pending",
        },
        "goal_posture": {
            "path": _display_root_relative_path(goal_posture_path),
            "status": "pending",
        },
        "google_workspace_oauth_readiness": {
            "path": _display_root_relative_path(google_workspace_oauth_readiness_path),
            "status": "not_needed",
            "reason": "no_google_workspace_runtime_blocker",
        },
        "operator_action_required_digest": {
            "path": _display_root_relative_path(digest_path),
            "status": "pending",
            "input_path": _display_root_relative_path(goal_posture_path),
            "state_path": _display_root_relative_path(digest_state_path),
            "refresh_source": False,
        },
        "operator_action_required_dedupe_proof": {
            "path": _display_root_relative_path(dedupe_proof_path),
            "status": "not_needed",
            "input_path": _display_root_relative_path(goal_posture_path),
            "state_path": _display_root_relative_path(digest_state_path),
            "sent_receipt_path": _display_root_relative_path(digest_path),
        },
    }
    runtime_context = _followthrough_runtime_context(
        args,
        receipt_path=receipt_path,
        stage_packet_dir=stage_packet_dir,
        safe_work_result_dir=safe_work_result_dir,
        current_runtime_artifacts_present=current_runtime_artifacts_present,
    )
    report_args = builders["operator_status_default_report_args"]()
    for key, value in vars(args).items():
        setattr(report_args, key, value)
    report_args.state_path = str(runtime_context["state_path"])
    report_args.stage_packet_dir = str(runtime_context["stage_packet_dir"])
    report_args.safe_work_result_dir = str(runtime_context["safe_work_result_dir"])
    digest_send_requested = bool(getattr(args, "armed_send", False))
    try:
        operator_status = dict(
            builders["operator_status"](
                output_path=operator_status_path,
                report_args=report_args,
                live_receipt_path=receipt_path,
                allow_live_route_probe=False,
            )
        )
        summary["operator_status"].update(
            {
                "status": str(operator_status.get("status") or "written").strip() or "written",
                "route_status": str(dict(operator_status.get("route") or {}).get("status") or "").strip(),
                "reason": str(operator_status.get("reason") or "").strip(),
            }
        )
        google_workspace_reauth_reason = _operator_status_google_workspace_reauth_required_reason(operator_status)
        if google_workspace_reauth_reason:
            google_workspace_oauth_readiness = dict(
                builders["google_workspace_oauth_readiness"](
                    reauth_required_reason=google_workspace_reauth_reason,
                    include_env_file=ROOT / ".env",
                    probe_gcloud=False,
                )
            )
            _write_receipt(google_workspace_oauth_readiness_path, google_workspace_oauth_readiness)
            summary["google_workspace_oauth_readiness"].update(
                {
                    "status": str(google_workspace_oauth_readiness.get("status") or "written").strip() or "written",
                    "reason": "",
                    "reauth_required_reason": str(
                        google_workspace_oauth_readiness.get("reauth_required_reason") or ""
                    ).strip(),
                    "next_action": str(
                        dict(google_workspace_oauth_readiness.get("operator_action") or {}).get("next_action") or ""
                    ).strip(),
                }
            )

        gold_acceptance = dict(
            builders["gold_acceptance"](
                output_path=gold_acceptance_path,
                operator_status_path=operator_status_path,
                run_receipt_path=receipt_path,
                stage_packet_dir=runtime_context["stage_packet_dir"],
                safe_work_result_dir=runtime_context["safe_work_result_dir"],
                allow_live_runtime_probe=False,
            )
        )
        summary["gold_acceptance"].update(
            {
                "status": str(gold_acceptance.get("status") or "written").strip() or "written",
            }
        )

        goal_posture = dict(
            builders["goal_posture"](
                root=ROOT,
                output_path=goal_posture_path,
            )
        )
        summary["goal_posture"].update(
            {
                "status": str(goal_posture.get("status") or "written").strip() or "written",
                "operator_action_queue_count": len(list(goal_posture.get("operator_action_queue") or [])),
            }
        )

        action_required_digest = dict(
            builders["operator_action_required_digest"](
                root=ROOT,
                input_path=goal_posture_path,
                output_path=digest_path,
                state_path=digest_state_path,
                principal_id=str(getattr(args, "principal_id", "") or "").strip(),
                send=digest_send_requested,
                dry_run=False,
                refresh_source=False,
            )
        )
        summary["operator_action_required_digest"].update(
            {
                "status": str(action_required_digest.get("status") or "written").strip() or "written",
                "notification_status": str(action_required_digest.get("notification_status") or "").strip(),
                "item_count": int(action_required_digest.get("item_count") or 0),
                "send_requested": digest_send_requested,
            }
        )
        digest_notification_status = str(action_required_digest.get("notification_status") or "").strip()
        if digest_notification_status == "suppressed_duplicate":
            dedupe_proof = dict(
                builders["operator_action_required_dedupe_proof"](
                    root=ROOT,
                    input_path=goal_posture_path,
                    state_path=digest_state_path,
                    sent_receipt_path=digest_path,
                    output_path=dedupe_proof_path,
                )
            )
            summary["operator_action_required_dedupe_proof"].update(
                {
                    "status": str(dedupe_proof.get("status") or "written").strip() or "written",
                }
            )
        if digest_notification_status in {"sent", "suppressed_duplicate"}:
            gold_acceptance = dict(
                builders["gold_acceptance"](
                    output_path=gold_acceptance_path,
                    operator_status_path=operator_status_path,
                    run_receipt_path=receipt_path,
                    stage_packet_dir=runtime_context["stage_packet_dir"],
                    safe_work_result_dir=runtime_context["safe_work_result_dir"],
                    allow_live_runtime_probe=False,
                )
            )
            summary["gold_acceptance"].update(
                {
                    "status": str(gold_acceptance.get("status") or "written").strip() or "written",
                    "after_digest_delivery_refresh": True,
                }
            )
    except Exception as exc:
        summary["status"] = "failed"
        summary["reason"] = type(exc).__name__
        summary["error"] = f"{type(exc).__name__}:{str(exc or '').strip()}"
    return summary


def _cleanup_hidden_property_boundary(args: argparse.Namespace) -> dict[str, Any]:
    if bool(getattr(args, "dry_run", False)):
        return {
            "status": "skipped",
            "reason": "dry_run",
            "ran": False,
            "archived_total": 0,
        }
    if assistant_property_lane_enabled():
        return {
            "status": "skipped",
            "reason": "assistant_property_lane_enabled",
            "ran": False,
            "archived_total": 0,
        }
    cleanup = dict(
        cleanup_hidden_property_runtime_state(
            state_path=str(getattr(args, "state_path", "") or "state/proactive_ooda_notified.json"),
        )
        or {}
    )
    cleanup.setdefault("status", "ok")
    cleanup["ran"] = True
    cleanup["reason"] = ""
    cleanup["archived_total"] = int(cleanup.get("archived_total") or 0)
    cleanup["stage_packet_total"] = int(cleanup.get("stage_packet_total") or 0)
    cleanup["safe_work_result_total"] = int(cleanup.get("safe_work_result_total") or 0)
    cleanup["approval_callback_total"] = int(cleanup.get("approval_callback_total") or 0)
    return cleanup


def _delivery_mirror_receipt(
    *,
    approval_request: Mapping[str, Any] | None,
    notification_text: str,
) -> dict[str, Any]:
    request = dict(approval_request or {})
    return {
        "schema": "ea.proactive_ooda.delivery_mirror.v1",
        "enabled": True,
        "mode": "operator_safe_mirror",
        "reason": "mirror_delivery_proof",
        "user_notification_suppressed": True,
        "approval_request_requires_user_action": _notification_requires_user_action(request),
        "packet_ref_hash": _hash_value(str(request.get("packet_ref") or "").strip()),
        "staged_artifact_ref_hash": _hash_value(str(request.get("staged_artifact_ref") or "").strip()),
        "approval_prompt_present": bool(str(request.get("approval_prompt") or "").strip()),
        "staged_action_url_present": bool(str(request.get("staged_action_url") or "").strip()),
        "approved_execution_mode_present": bool(str(request.get("approved_execution_mode") or "").strip()),
        "approved_action_present": bool(str(request.get("approved_action") or "").strip()),
        "notification_text_sha256": _hash_value(notification_text),
        "raw_notification_text_exposed": False,
        "raw_approval_prompt_exposed": False,
        "raw_private_url_exposed": False,
    }


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

    container = _build_postgres_container_for_script()
    if container is None:
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
        if not _safe_work_allows_auto_execution(result):
            continue
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


def _safe_work_allows_auto_execution(result: Mapping[str, Any]) -> bool:
    if not _safe_work_allows_delivery_or_auto_execution(result):
        return False
    if str(result.get("status") or "").strip() != "staged_for_user_decision":
        return False
    audit = result.get("audit")
    if not isinstance(audit, Mapping):
        return False
    return str(audit.get("status") or "").strip().lower() == "pass"


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
    container = _build_postgres_container_for_script()
    if container is None:
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
        if _safe_work_requires_user_action(result):
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
        if not _safe_work_requires_user_action(result):
            continue
        packet_hash = str(result.get("source_packet_ref_hash") or "").strip()
        stage_packet = stage_packets_by_hash.get(packet_hash, {})
        stage_payload = dict(dict(stage_packet.get("stage") or {}).get("payload") or {})
        approval = dict(stage_packet.get("approval") or {})
        packet_ref = str(stage_packet.get("packet_ref") or "").strip()
        staged_artifact_ref = str(result.get("result_ref") or "").strip()
        work_type = str(result.get("work_type") or stage_payload.get("work_type") or "").strip().lower()
        notification_policy = _approval_request_notification_policy(
            result=result,
            stage_payload=stage_payload,
        )
        operator_action_required = _approval_request_operator_action_required(stage_payload=stage_payload)
        if not packet_ref or not staged_artifact_ref:
            continue
        if bool(approval.get("required")):
            return {
                "packet_ref": packet_ref,
                "staged_artifact_ref": staged_artifact_ref,
                "approval_prompt": str(result.get("approval_prompt") or "").strip(),
                "staged_action_url": str(result.get("staged_action_url") or "").strip(),
                "approved_action": _approval_request_approved_action_name(
                    work_type=work_type,
                    stage_payload=stage_payload,
                ),
                "work_type": work_type,
                "notification_policy": notification_policy,
                "operator_action_required": operator_action_required,
            }
        auto_execute_action = str(stage_payload.get("auto_execute_action") or "").strip().lower()
        if auto_execute_action and (packet_ref, staged_artifact_ref, auto_execute_action, "executed") in auto_executed_pairs:
            return {
                "packet_ref": packet_ref,
                "staged_artifact_ref": staged_artifact_ref,
                "approval_prompt": build_reversible_execution_approval_prompt(action=auto_execute_action),
                "staged_action_url": str(result.get("staged_action_url") or "").strip(),
                "approved_execution_mode": "record_outcome_only",
                "approved_action": auto_execute_action,
                "work_type": work_type,
                "notification_policy": notification_policy,
                "operator_action_required": operator_action_required,
            }
        return {
            "packet_ref": packet_ref,
            "staged_artifact_ref": staged_artifact_ref,
            "approval_prompt": str(result.get("approval_prompt") or "").strip(),
            "staged_action_url": str(result.get("staged_action_url") or "").strip(),
            "work_type": work_type,
            "notification_policy": notification_policy,
            "operator_action_required": operator_action_required,
        }
    return None


def _approval_request_approved_action_name(*, work_type: str, stage_payload: Mapping[str, Any]) -> str:
    explicit = str(
        stage_payload.get("post_approval_action")
        or stage_payload.get("approved_action")
        or ""
    ).strip().lower()
    if explicit:
        return explicit
    return "save_gmail_draft" if work_type == "draft" else "keep_staged"


def _approval_request_notification_policy(
    *,
    result: Mapping[str, Any],
    stage_payload: Mapping[str, Any],
) -> str:
    quality_gate = dict(result.get("quality_gate") or {})
    constraints = dict(stage_payload.get("constraints") or {})
    return str(
        quality_gate.get("notification_policy")
        or constraints.get("delivery_policy")
        or ""
    ).strip().lower()


def _approval_request_operator_action_required(*, stage_payload: Mapping[str, Any]) -> bool:
    criteria = stage_payload.get("selection_criteria")
    if not isinstance(criteria, (list, tuple)):
        return False
    normalized = {
        str(item or "").strip().lower()
        for item in criteria
        if str(item or "").strip()
    }
    return "operator action required" in normalized


def _safe_work_requires_user_action(result: Mapping[str, Any]) -> bool:
    if not _safe_work_allows_delivery_or_auto_execution(result):
        return False
    status = str(result.get("status") or "").strip()
    if status == "staged_for_user_decision":
        return True
    if status != "blocked_human_handoff_required":
        return False
    browser_receipt = result.get("browser_action_receipt")
    if not isinstance(browser_receipt, Mapping):
        return False
    return bool(browser_receipt.get("user_action_required"))


def _safe_work_allows_delivery_or_auto_execution(result: Mapping[str, Any]) -> bool:
    if safe_work_decision_materiality_issue(safe_work_result=result):
        return False
    status = str(result.get("status") or "").strip()
    audit = result.get("audit")
    if isinstance(audit, Mapping):
        if str(audit.get("status") or "").strip().lower() == "pass":
            return True
        if status == "blocked_human_handoff_required":
            browser_receipt = result.get("browser_action_receipt")
            return isinstance(browser_receipt, Mapping) and bool(browser_receipt.get("user_action_required"))
        return False
    return status in {"staged_for_user_decision", "blocked_human_handoff_required"}


def _notification_requires_user_action(approval_request: Mapping[str, Any] | None) -> bool:
    return approval_request_needs_telegram_user_action(approval_request)


def _approval_request_is_nonassistant_internal_action(approval_request: Mapping[str, Any] | None) -> bool:
    request = dict(approval_request or {})
    work_type = str(request.get("work_type") or "").strip().lower()
    return work_type in {"record_internal_action", "internal_action", "operator_action"}


def _cleanup_approval_callbacks(
    args: argparse.Namespace,
    *,
    approval_request: Mapping[str, Any] | None,
) -> dict[str, Any]:
    requires_user_action = _notification_requires_user_action(approval_request)
    if bool(getattr(args, "dry_run", False)):
        return {
            "status": "skipped",
            "reason": "dry_run",
            "approval_request_requires_user_action": requires_user_action,
            "supersede_noncurrent_requested": False,
        }
    request = dict(approval_request or {})
    active_packet_ref = str(request.get("packet_ref") or "").strip()
    active_staged_artifact_ref = str(request.get("staged_artifact_ref") or "").strip()
    active_refs_present = bool(active_packet_ref and active_staged_artifact_ref)
    supersede_noncurrent = bool(
        active_refs_present
        and requires_user_action
        and not _approval_request_is_nonassistant_internal_action(request)
    )
    supersede_active_pending = bool(active_refs_present and not requires_user_action)
    cleanup = dict(
        expire_stale_proactive_ooda_telegram_approval_callbacks(
            root=ROOT,
            state_path=str(getattr(args, "state_path", "state/proactive_ooda_notified.json") or "state/proactive_ooda_notified.json"),
            receipt_path=str(getattr(args, "receipt_path", "") or ""),
            supersede_noncurrent=supersede_noncurrent,
            supersede_active_pending=supersede_active_pending,
            active_packet_ref=active_packet_ref,
            active_staged_artifact_ref=active_staged_artifact_ref,
        )
    )
    cleanup["approval_request_requires_user_action"] = requires_user_action
    cleanup["supersede_noncurrent_requested"] = supersede_noncurrent
    cleanup["supersede_active_pending_requested"] = supersede_active_pending
    return cleanup


def _delivery_guard_snapshot(
    args: argparse.Namespace,
    *,
    state_store: JsonOodaStateStore,
    principal_id: str,
    digest: Any,
    approval_request: Mapping[str, Any] | None,
    safe_work_results: Iterable[Mapping[str, Any]],
    error_code: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    current_now = now or datetime.now(timezone.utc)
    items = tuple(getattr(digest, "items", ()) or ())
    has_items = bool(items)
    has_high_priority = any(getattr(item, "priority", "") == "high" for item in items)
    paused = bool(getattr(args, "paused", False))
    quiet_active = _quiet_hours_active(args, now=current_now)
    quiet_allows_high = bool(getattr(args, "quiet_hours_allow_high_priority", True))
    armed_send = bool(getattr(args, "armed_send", False))
    budget_limit = max(int(getattr(args, "interruption_budget_limit", 0) or 0), 0)
    budget_window_hours = max(int(getattr(args, "interruption_budget_window_hours", 24) or 24), 1)
    budget_allows_high = bool(getattr(args, "interruption_budget_allow_high_priority", True))
    notification_cooldown_seconds = _notification_cooldown_seconds(args)
    notification_cooldown_allow_high_priority = _notification_cooldown_allow_high_priority(args)
    recent_budget_events = _recent_interruption_events(
        state_store.load_interruption_events(principal_id),
        now=current_now,
        window_hours=budget_window_hours,
    )
    budget_used = len(recent_budget_events)
    budget_exhausted = budget_limit > 0 and budget_used >= budget_limit
    latest_interruption_event = _latest_interruption_event(state_store.load_interruption_events(principal_id))
    notification_cooldown_seconds_remaining = 0
    if latest_interruption_event is not None and notification_cooldown_seconds > 0:
        notification_cooldown_seconds_remaining = max(
            0,
            int((latest_interruption_event - current_now).total_seconds()) + notification_cooldown_seconds,
        )
    notification_cooldown_active = notification_cooldown_seconds_remaining > 0
    user_action_required = _notification_requires_user_action(approval_request)
    decision_ready_safe_work = _has_decision_ready_safe_work(safe_work_results)
    if not has_items:
        delivery_state = "no_actionable_items"
    elif error_code:
        delivery_state = "deferred" if _is_deferred_error(error_code) else "failed"
    else:
        delivery_state = "eligible"
    return {
        "delivery_state": delivery_state,
        "deferred_reason": str(error_code or "").strip() if _is_deferred_error(error_code) else "",
        "armed_send": armed_send,
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
        "notification_cooldown_seconds": notification_cooldown_seconds,
        "notification_cooldown_active": notification_cooldown_active,
        "notification_cooldown_seconds_remaining": notification_cooldown_seconds_remaining,
        "notification_cooldown_allow_high_priority": notification_cooldown_allow_high_priority,
        "has_high_priority": has_high_priority,
        "action_required_delivery_only": bool(getattr(args, "action_required_delivery_only", True)),
        "notification_requires_user_action": user_action_required,
        "decision_ready_safe_work_present": decision_ready_safe_work,
        "mirror_delivery_proof_enabled": bool(getattr(args, "mirror_delivery_proof", False)),
        "delivery_mirrored_for_proof": str(error_code or "").strip() == "mirrored_delivery_proof",
    }


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


def _notification_cooldown_seconds(args: argparse.Namespace) -> int:
    try:
        return max(int(getattr(args, "notification_cooldown_seconds", 1800) or 0), 0)
    except (TypeError, ValueError):
        return 1800


def _notification_cooldown_allow_high_priority(args: argparse.Namespace) -> bool:
    return bool(getattr(args, "notification_cooldown_allow_high_priority", True))


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


def _notification_cooldown_defer_reason(
    args: argparse.Namespace,
    *,
    state_store: JsonOodaStateStore,
    principal_id: str,
    digest: Any,
    now: datetime | None = None,
) -> str:
    if not getattr(digest, "items", ()):
        return ""
    cooldown_seconds = _notification_cooldown_seconds(args)
    if cooldown_seconds <= 0:
        return ""
    if _notification_cooldown_allow_high_priority(args) and any(item.priority == "high" for item in digest.items):
        return ""
    latest_event = _latest_interruption_event(state_store.load_interruption_events(principal_id))
    if latest_event is None:
        return ""
    current_now = now or datetime.now(timezone.utc)
    elapsed_seconds = (current_now - latest_event).total_seconds()
    return "deferred_by_notification_cooldown" if elapsed_seconds < cooldown_seconds else ""


def _record_interruption_event(
    args: argparse.Namespace,
    *,
    state_store: JsonOodaStateStore,
    principal_id: str,
    occurred_at: str,
) -> None:
    window_hours = _interruption_event_retention_window_hours(args)
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


def _interruption_event_retention_window_hours(args: argparse.Namespace) -> int:
    budget_window_hours = max(int(getattr(args, "interruption_budget_window_hours", 24) or 24), 1)
    cooldown_seconds = _notification_cooldown_seconds(args)
    cooldown_window_hours = max(1, (cooldown_seconds + 3599) // 3600) if cooldown_seconds > 0 else 1
    return max(budget_window_hours, cooldown_window_hours)


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


def _latest_interruption_event(events: tuple[str, ...]) -> datetime | None:
    latest: datetime | None = None
    for raw_event in events:
        parsed = _parse_datetime(raw_event)
        if parsed is None:
            continue
        if latest is None or parsed > latest:
            latest = parsed
    return latest


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


def _quiet_hours_configured(args: argparse.Namespace) -> bool:
    start = _parse_local_time(getattr(args, "quiet_hours_start", ""))
    end = _parse_local_time(getattr(args, "quiet_hours_end", ""))
    return start is not None and end is not None


def _quiet_hours_active(args: argparse.Namespace, *, now: datetime | None = None) -> bool:
    start = _parse_local_time(getattr(args, "quiet_hours_start", ""))
    end = _parse_local_time(getattr(args, "quiet_hours_end", ""))
    if start is None or end is None:
        return False
    local_now = (now or datetime.now(timezone.utc)).astimezone(_quiet_hours_timezone(getattr(args, "quiet_hours_timezone", "")))
    return _is_time_within_quiet_hours(local_now.time(), start=start, end=end)


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
        "mirrored_delivery_proof",
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
    if bool(getattr(args, "include_goal_action_queue", False)):
        goal_posture_path = _goal_posture_json_path(str(getattr(args, "goal_posture_json", "") or ""))
        if goal_posture_path:
            goal_action_signals = load_goal_action_queue_signals(
                goal_posture_path,
                limit=max(int(getattr(args, "goal_action_queue_limit", DEFAULT_GOAL_ACTION_QUEUE_LIMIT) or 0), 0),
                allowed_operator_streams=str(getattr(args, "goal_action_operator_streams", "") or ""),
            )
            rows.extend(signal.__dict__ for signal in goal_action_signals)
    if not args.skip_observation_source:
        observation_signals = discover_postgres_observation_signals(
            principal_id=args.principal_id,
            limit=args.observation_limit,
            lookback_hours=args.observation_lookback_hours,
        )
        if observation_signals:
            rows.extend(signal.__dict__ for signal in observation_signals)
    if bool(getattr(args, "skip_workspace_source", False)):
        return _filter_hidden_property_rows(_apply_recent_topic_suppressions(rows))
    try:
        from app.services.google_oauth import list_recent_workspace_signals
    except Exception as exc:  # pragma: no cover - depends on full runtime being present
        if _workspace_source_not_configured(exc):
            return _filter_hidden_property_rows(_apply_recent_topic_suppressions(rows))
        return _filter_hidden_property_rows(_apply_recent_topic_suppressions(rows + [_workspace_source_error_signal(exc)]))
    cooldown_state: dict[str, Any] = {}
    try:
        container = _build_postgres_container_for_script()
        if container is None:
            return _filter_hidden_property_rows(_apply_recent_topic_suppressions(rows))
        cooldown_state = _google_workspace_runtime_cooldown_state(
            container=container,
            principal_id=args.principal_id,
        )
        if bool(cooldown_state.get("active")):
            cooldown_reason = str(cooldown_state.get("reason") or "google_workspace_recovery_cooldown_active").strip()
            return _filter_hidden_property_rows(
                _apply_recent_topic_suppressions(
                    rows + [_workspace_source_error_signal(RuntimeError(cooldown_reason), cooldown_state=cooldown_state)]
                )
            )
        packet = list_recent_workspace_signals(
            container=container,
            principal_id=args.principal_id,
            email_limit=args.email_limit,
            calendar_limit=args.calendar_limit,
            gmail_query=args.gmail_query,
        )
    except Exception as exc:
        if _workspace_source_not_configured(exc):
            return _filter_hidden_property_rows(_apply_recent_topic_suppressions(rows))
        return _filter_hidden_property_rows(
            _apply_recent_topic_suppressions(rows + [_workspace_source_error_signal(exc, cooldown_state=cooldown_state)])
        )
    for signal in packet.signals:
        if hasattr(signal, "__dict__"):
            rows.append(dict(signal.__dict__))
    return _filter_hidden_property_rows(_apply_recent_topic_suppressions(rows))


def _recover_sparse_observation_digest(
    args: argparse.Namespace,
    *,
    state_store: JsonOodaStateStore | None,
    stored_refs: set[str],
    service: ProactiveOodaService,
    signals: list[dict[str, Any]],
    digest: ProactiveOodaDigest,
) -> tuple[list[dict[str, Any]], ProactiveOodaDigest]:
    if getattr(digest, "items", ()):
        return signals, digest
    if bool(getattr(args, "skip_observation_source", False)):
        return signals, digest
    recovery_lookback_hours = _observation_recovery_lookback_hours(args)
    current_lookback_hours = max(int(getattr(args, "observation_lookback_hours", 0) or 0), 0)
    if recovery_lookback_hours <= current_lookback_hours:
        return signals, digest
    if not _signals_only_internal_recovery_rows(signals):
        return signals, digest

    recovery_args = argparse.Namespace(**dict(vars(args)))
    recovery_args.observation_lookback_hours = recovery_lookback_hours
    recovered_signals = _load_signals(
        recovery_args,
        state_store=state_store,
        persist_opportunity_state=False,
    )
    recovered_digest = service.build_digest(
        principal_id=str(getattr(args, "principal_id", "") or ""),
        signals=recovered_signals,
        already_notified_refs=stored_refs,
    )
    recovered_digest = _context_grounded_digest(str(getattr(args, "principal_id", "") or ""), recovered_digest)
    if len(tuple(getattr(recovered_digest, "items", ()) or ())) <= len(tuple(getattr(digest, "items", ()) or ())):
        return signals, digest
    return recovered_signals, recovered_digest


def _observation_recovery_lookback_hours(args: argparse.Namespace) -> int:
    configured = int(os.getenv("EA_PROACTIVE_OODA_RECOVERY_OBSERVATION_LOOKBACK_HOURS", "72") or "72")
    current = max(int(getattr(args, "observation_lookback_hours", 0) or 0), 0)
    return max(configured, current)


def _signals_only_internal_recovery_rows(rows: Iterable[Mapping[str, Any]]) -> bool:
    observed_any = False
    for row in rows:
        observed_any = True
        signal_type = str(row.get("signal_type") or row.get("type") or "").strip().lower()
        channel = str(row.get("channel") or "").strip().lower()
        source_ref = str(row.get("source_ref") or row.get("ref") or row.get("id") or "").strip().lower()
        payload = row.get("payload") if isinstance(row.get("payload"), Mapping) else {}
        if signal_type == "goal_action_queue":
            continue
        if signal_type in {"proactive_source_health", "source_health"}:
            continue
        if channel == "proactive_runtime" and source_ref.startswith("proactive_source_error:"):
            continue
        if isinstance(payload.get("source_health"), Mapping):
            continue
        return False
    return observed_any


def _goal_posture_json_path(value: str) -> Path | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    path = Path(normalized)
    return path if path.is_absolute() else ROOT / path


def _root_relative_path(value: str, *, default_relative: str) -> Path:
    normalized = str(value or "").strip() or default_relative
    path = Path(normalized)
    return path if path.is_absolute() else ROOT / path


def _display_root_relative_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except Exception:
        return str(path)


def _load_followthrough_builders() -> dict[str, Any]:
    from scripts.materialize_continuous_improvement_goal_posture import build_goal_posture
    from scripts.materialize_google_workspace_oauth_readiness import (
        build_receipt as build_google_workspace_oauth_readiness_receipt,
    )
    from scripts.materialize_operator_action_required_dedupe_proof import (
        build_operator_action_required_dedupe_proof,
    )
    from scripts.materialize_operator_action_required_digest import build_operator_action_required_digest
    from scripts.materialize_proactive_ooda_gold_acceptance import materialize_proactive_ooda_gold_acceptance
    from scripts.materialize_proactive_ooda_operator_status import (
        _default_report_args as operator_status_default_report_args,
    )
    from scripts.materialize_proactive_ooda_operator_status import build_proactive_ooda_operator_status

    return {
        "operator_status": build_proactive_ooda_operator_status,
        "operator_status_default_report_args": operator_status_default_report_args,
        "gold_acceptance": materialize_proactive_ooda_gold_acceptance,
        "goal_posture": build_goal_posture,
        "google_workspace_oauth_readiness": build_google_workspace_oauth_readiness_receipt,
        "operator_action_required_digest": build_operator_action_required_digest,
        "operator_action_required_dedupe_proof": build_operator_action_required_dedupe_proof,
    }


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


def _filter_hidden_property_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if assistant_property_lane_enabled():
        return rows
    filtered: list[dict[str, Any]] = []
    for row in rows:
        if _row_hidden_from_ea_property_boundary(row):
            continue
        filtered.append(row)
    return filtered


def _row_hidden_from_ea_property_boundary(row: Mapping[str, Any]) -> bool:
    return assistant_property_signal_present(
        row.get("source_ref"),
        row.get("signal_type"),
        row.get("channel"),
        row.get("title"),
        row.get("summary"),
        row.get("counterparty"),
        row.get("external_id"),
        row.get("payload"),
        row,
    )


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
        source_health = _source_health_issue_payload(
            source_key=source_label,
            source_type=source_label,
            status="failed",
            error_code=_source_health_error_code(error_label),
            next_action="repair_proactive_signal_source",
        )
        signals.append(
            {
                "source_ref": f"proactive_source_error:{source_label}:{_short_hash(error_label)}",
                "signal_type": "proactive_source_health",
                "channel": "proactive_runtime",
                "title": "EA proactive source needs attention",
                "summary": "A configured proactive source failed. EA kept running, but this source may be missing from the brief.",
                "counterparty": "EA runtime",
                "payload": {
                    "source_health": source_health,
                    "ooda_loop": _source_health_ooda(
                        "A configured proactive source failed.",
                        "Check the configured source and repair credentials, URL, or table mapping.",
                        user_action_required=bool(source_health.get("user_action_required")),
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


def _google_workspace_runtime_cooldown_state(
    *,
    container: object,
    principal_id: str,
) -> dict[str, Any]:
    runtime = getattr(container, "channel_runtime", None)
    list_recent_observations = getattr(runtime, "list_recent_observations", None)
    if not callable(list_recent_observations):
        return {}
    try:
        rows = list(list_recent_observations(limit=200, principal_id=principal_id) or [])
    except Exception:
        return {}
    product_rows = sorted(
        [
            row
            for row in rows
            if str(getattr(row, "channel", "") or "").strip().lower() == "product"
        ],
        key=lambda row: str(getattr(row, "created_at", "") or "").strip(),
    )
    cooldown_event = next(
        (
            row
            for row in reversed(product_rows)
            if str(getattr(row, "event_type", "") or "").strip()
            == "google_workspace_signal_sync_recovery_blocked"
        ),
        None,
    )
    if cooldown_event is None:
        return {}
    payload = dict(getattr(cooldown_event, "payload", {}) or {})
    blocked_until = str(payload.get("blocked_until") or payload.get("cooldown_until") or "").strip()
    blocked_until_at = _parse_timestamp(blocked_until)
    if blocked_until_at is None:
        return {}
    cooldown_event_at = _parse_timestamp(str(getattr(cooldown_event, "created_at", "") or "").strip())
    latest_completed = next(
        (
            row
            for row in reversed(product_rows)
            if str(getattr(row, "event_type", "") or "").strip()
            == "google_workspace_signal_sync_completed"
        ),
        None,
    )
    recovered_at = ""
    latest_completed_at = _parse_timestamp(str(getattr(latest_completed, "created_at", "") or "").strip()) if latest_completed else None
    if cooldown_event_at is not None and latest_completed_at is not None and latest_completed_at >= cooldown_event_at:
        recovered_at = str(getattr(latest_completed, "created_at", "") or "").strip()
    now = datetime.now(timezone.utc)
    try:
        cooldown_seconds = max(int(payload.get("cooldown_seconds") or 0), 0)
    except Exception:
        cooldown_seconds = 0
    active = blocked_until_at > now and not recovered_at
    return {
        "reason": str(payload.get("reason") or "").strip(),
        "blocked_until": blocked_until,
        "last_observed_at": str(getattr(cooldown_event, "created_at", "") or payload.get("blocked_at") or "").strip(),
        "cooldown_seconds": cooldown_seconds,
        "seconds_remaining": max(int((blocked_until_at - now).total_seconds()), 0) if active else 0,
        "recovery_mode": str(payload.get("recovery_mode") or "scheduler_cooldown").strip(),
        "active": active,
        "recovered_at": recovered_at,
    }


def _workspace_source_error_signal(
    exc: Exception,
    *,
    cooldown_state: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    error_name = exc.__class__.__name__
    error_text = _workspace_source_error_detail(exc)
    cooldown = dict(cooldown_state or {})
    if not error_text:
        error_text = str(cooldown.get("reason") or error_name).strip()
    cooldown_active = bool(cooldown.get("active"))
    blocked_until = str(cooldown.get("blocked_until") or "").strip()
    summary = "Google workspace scanning is failing, so EA cannot reliably inspect Gmail or Calendar for proactive nudges."
    action = "Reauthorize Google for the EA principal, then rerun the proactive OODA verifier."
    if cooldown_active:
        until_suffix = f" until {blocked_until}" if blocked_until else ""
        summary = (
            "Google workspace scanning is paused in a bounded recovery cooldown"
            f"{until_suffix}, so EA is waiting for reauthorization before retrying Gmail or Calendar ingest."
        )
        action = "Reconnect Google workspace, then rerun the proactive OODA verifier after the cooldown clears."
    source_health = _source_health_issue_payload(
        source_key="google_workspace",
        source_type="google_workspace",
        status="unhealthy",
        error_code=error_text or error_name,
        next_action="reauthorize_google_workspace_binding",
        recovery_mode=str(cooldown.get("recovery_mode") or "scheduler_cooldown").strip() if cooldown_active else "",
        blocked_until=blocked_until,
        cooldown_seconds_remaining=int(cooldown.get("seconds_remaining") or 0),
        last_observed_at=str(cooldown.get("last_observed_at") or "").strip(),
        cooldown_active=cooldown_active if cooldown else None,
    )
    return {
        "source_ref": f"proactive_source_error:google_workspace:{_short_hash(error_text or error_name)}",
        "signal_type": "proactive_source_health",
        "channel": "proactive_runtime",
        "title": "EA cannot scan Google workspace",
        "summary": summary,
        "counterparty": "Google workspace",
        "payload": {
            "source_health": source_health,
            "reason_code": error_text or error_name,
            "ooda_loop": _source_health_ooda(
                summary,
                action,
                user_action_required=bool(source_health.get("user_action_required")),
            ),
        },
    }


def _source_health_issue_payload(
    *,
    source_key: str,
    source_type: str,
    status: str,
    error_code: str,
    next_action: str,
    recovery_mode: str = "",
    blocked_until: str = "",
    cooldown_seconds_remaining: int | None = None,
    last_observed_at: str = "",
    cooldown_active: bool | None = None,
) -> dict[str, Any]:
    issue = {
        "schema": "ea.proactive_ooda.source_health.v1",
        "source_key": str(source_key or "unknown").strip() or "unknown",
        "source_type": str(source_type or "unknown").strip() or "unknown",
        "status": str(status or "failed").strip() or "failed",
        "error_code": _source_health_error_code(error_code),
        "error_ref_hash": _short_hash(error_code),
        "operator_action_required": True,
        "user_action_required": False,
        "next_action": str(next_action or "repair_proactive_signal_source").strip() or "repair_proactive_signal_source",
        "raw_source_ref_exposed": False,
        "raw_payload_exposed": False,
        "raw_credential_exposed": False,
    }
    if str(recovery_mode or "").strip():
        issue["recovery_mode"] = str(recovery_mode or "").strip()[:80]
    if str(blocked_until or "").strip():
        issue["blocked_until"] = str(blocked_until or "").strip()[:40]
    if cooldown_seconds_remaining is not None and int(cooldown_seconds_remaining or 0) > 0:
        issue["cooldown_seconds_remaining"] = max(int(cooldown_seconds_remaining or 0), 0)
    if str(last_observed_at or "").strip():
        issue["last_observed_at"] = str(last_observed_at or "").strip()[:40]
    if cooldown_active is not None:
        issue["cooldown_active"] = bool(cooldown_active)
    issue["user_action_required"] = source_health_issue_requires_user_action(issue)
    return issue


def _source_health_summary(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        if not _is_source_health_row(row):
            continue
        payload = row.get("payload") if isinstance(row.get("payload"), Mapping) else {}
        issue = dict(payload.get("source_health") or {}) if isinstance(payload.get("source_health"), Mapping) else {}
        if not issue:
            issue = _source_health_issue_from_row(row)
        if issue:
            issues.append(_compact_source_health_issue(issue))
    user_action_required = any(bool(issue.get("user_action_required")) for issue in issues)
    operator_action_required = any(bool(issue.get("operator_action_required")) for issue in issues)
    return {
        "schema": "ea.proactive_ooda.source_health_summary.v1",
        "present": bool(issues),
        "status": "recovery_required" if operator_action_required or user_action_required else "clear",
        "issue_count": len(issues),
        "operator_action_required": operator_action_required,
        "user_action_required": user_action_required,
        "issues": issues[:10],
        "privacy": {
            "raw_source_ref_exposed": False,
            "raw_payload_exposed": False,
            "raw_credential_exposed": False,
            "source_refs_hashed": True,
        },
    }


def _is_source_health_row(row: Mapping[str, Any]) -> bool:
    signal_type = str(row.get("signal_type") or row.get("type") or "").strip().lower()
    channel = str(row.get("channel") or "").strip().lower()
    source_ref = str(row.get("source_ref") or row.get("ref") or row.get("id") or "").strip().lower()
    payload = row.get("payload") if isinstance(row.get("payload"), Mapping) else {}
    return bool(
        signal_type in {"proactive_source_health", "source_health"}
        or (channel == "proactive_runtime" and source_ref.startswith("proactive_source_error:"))
        or isinstance(payload.get("source_health"), Mapping)
    )


def _source_health_issue_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    source_ref = str(row.get("source_ref") or row.get("ref") or row.get("id") or "").strip()
    parts = source_ref.split(":")
    source_key = parts[1] if len(parts) > 2 and parts[0] == "proactive_source_error" else "unknown"
    payload = row.get("payload") if isinstance(row.get("payload"), Mapping) else {}
    return _source_health_issue_payload(
        source_key=source_key,
        source_type=source_key,
        status="failed",
        error_code=str(payload.get("reason_code") or source_ref or "source_health_issue"),
        next_action="repair_proactive_signal_source",
    )


def _compact_source_health_issue(issue: Mapping[str, Any]) -> dict[str, Any]:
    source_key = str(issue.get("source_key") or "unknown").strip() or "unknown"
    source_type = str(issue.get("source_type") or source_key).strip() or source_key
    error_code = _source_health_error_code(str(issue.get("error_code") or issue.get("reason_code") or "source_error"))
    normalized = {
        "source_key": source_key[:80],
        "source_type": source_type[:80],
        "status": str(issue.get("status") or "failed").strip()[:80] or "failed",
        "error_code": error_code,
        "error_ref_hash": str(issue.get("error_ref_hash") or _short_hash(error_code)).strip()[:24],
        "operator_action_required": bool(issue.get("operator_action_required", True)),
        "user_action_required": bool(issue.get("user_action_required")),
        "next_action": str(issue.get("next_action") or "repair_proactive_signal_source").strip()[:120]
        or "repair_proactive_signal_source",
        "raw_source_ref_exposed": False,
        "raw_payload_exposed": False,
        "raw_credential_exposed": False,
    }
    recovery_mode = str(issue.get("recovery_mode") or "").strip()
    blocked_until = str(issue.get("blocked_until") or issue.get("cooldown_until") or "").strip()
    last_observed_at = str(issue.get("last_observed_at") or "").strip()
    if recovery_mode:
        normalized["recovery_mode"] = recovery_mode[:80]
    if blocked_until:
        normalized["blocked_until"] = blocked_until[:40]
    if last_observed_at:
        normalized["last_observed_at"] = last_observed_at[:40]
    if "cooldown_active" in issue or blocked_until:
        normalized["cooldown_active"] = bool(issue.get("cooldown_active"))
    try:
        cooldown_seconds_remaining = max(int(issue.get("cooldown_seconds_remaining") or 0), 0)
    except Exception:
        cooldown_seconds_remaining = 0
    if cooldown_seconds_remaining > 0:
        normalized["cooldown_seconds_remaining"] = cooldown_seconds_remaining
    normalized["user_action_required"] = source_health_issue_requires_user_action(normalized)
    return normalized


def _source_health_error_code(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return "source_error"
    if all(char.isalnum() or char in {"_", ":", ".", "-", "+"} for char in normalized):
        return normalized[:160]
    return "source_error"


def _source_health_ooda(summary: str, action: str, *, user_action_required: bool = False) -> dict[str, Any]:
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
            "approval_required": user_action_required,
            "user_action_required": user_action_required,
            "ignored_consequence": "EA may stay quiet even when a human assistant would have found the signal.",
        },
        "act": {
            "summary": action,
            "user_action_required": user_action_required,
        },
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
    container = _build_postgres_container_for_script()
    if container is None:
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
    container = _build_postgres_container_for_script()
    if container is None:
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
