#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
EA_ROOT = ROOT / "ea"
for candidate in (str(ROOT), str(EA_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

try:
    from scripts.source_state_head import resolve_source_state_head
    from scripts.source_state_head import resolve_source_worktree_fingerprint
except ModuleNotFoundError:  # pragma: no cover - script execution path
    from source_state_head import resolve_source_state_head
    from source_state_head import resolve_source_worktree_fingerprint

import scripts.verify_proactive_ooda as proactive_verifier
import scripts.verify_proactive_ooda_live_receipt as live_receipt_verifier
import scripts.ea_live_ops as ea_live_ops
from app.services.proactive_ooda_operator_actions import proactive_next_action_surface
from app.services.proactive_ooda_safe_work import safe_work_decision_materiality_issue
from app.services.proactive_ooda_runtime_artifacts import load_runtime_artifact_bundle


DEFAULT_OUTPUT = ROOT / ".codex-studio" / "published" / "ea_proactive_ooda_operator_status.generated.json"
CONTRACT_NAME = "ea.proactive_ooda_operator_status.v1"

RULES = [
    "This receipt proves proactive OODA route, guard, and packet-runtime posture only; it does not prove a human accepted the packet.",
    "Delivery recovery hints may be mirrored here and in Teable, but they remain operator aids rather than canonical queue truth.",
    "A live sent receipt can prove one routed delivery happened, but it does not by itself prove ordinary-use usefulness or approval correctness.",
    "Gold-production claims still require accepted proactive packets, routed delivery proof, approved-source or transcript signal evidence, live browse evidence, an auditor-passed chosen candidate, staged reversible artifacts, mirrored Teable current/stale delivery and decision facts, explicit approval outcome evidence, and consent-gated irreversible actions.",
]
REMAINING_EXTERNAL_PROOF = (
    "real proactive OODA packet accepted with routed delivery, approved-source or transcript signal, live browse evidence, auditor-passed chosen candidate, staged reversible artifact, mirrored Teable delivery, current-packet, stale-approval, and decision facts, and explicit approval outcome"
)
SOURCE_COVERAGE_LANE_CONTRACTS = {
    str(row["key"]): {
        "next_action": str(row.get("next_action") or "").strip(),
        "required_event_types": tuple(str(item).strip() for item in tuple(row.get("required_event_types") or ()) if str(item).strip()),
    }
    for row in ea_live_ops.PROACTIVE_SOURCE_COVERAGE_LANES
}
NON_MATERIAL_ARTIFACT_FILTER_REASONS = {
    "single_official_info_link_not_decision_ready",
    "flat_search_disabled_property_scout",
    "flat_search_disabled",
}
NON_MATERIAL_SUPPRESSED_PROJECTION_ISSUE_CODES = {
    "no_decision_ready_material",
    "single_official_info_link_not_decision_ready",
}
NON_MATERIAL_SUPPRESSED_PROJECTION_REASONS = {
    "packet_projection_suppressed",
    "safe_work_audit_review",
}


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _git_head(path: Path = ROOT) -> str:
    return resolve_source_state_head(path)


def _source_fingerprint(path: Path = ROOT) -> str:
    return resolve_source_worktree_fingerprint(path)


def _env_truthy(name: str, *, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _safe_int(value: str, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: str, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _live_probe_timeout_seconds() -> float:
    return max(
        _safe_float(str(os.getenv("EA_PROACTIVE_OODA_LIVE_PROBE_TIMEOUT_SECONDS") or "30"), default=30.0),
        1.0,
    )


def _default_report_args() -> argparse.Namespace:
    return argparse.Namespace(
        principal_id=proactive_verifier._default_principal_id(),
        signals_json=str(os.getenv("EA_PROACTIVE_OODA_SIGNALS_JSON") or "").strip(),
        discovery_json=str(os.getenv("EA_PROACTIVE_OODA_DISCOVERY_JSON") or "").strip(),
        opportunity_rules_json=str(
            os.getenv("EA_PROACTIVE_OODA_OPPORTUNITY_RULES_JSON")
            or os.getenv("EA_PROACTIVE_OODA_PERSONAL_RULES_JSON")
            or ""
        ).strip(),
        state_path=str(os.getenv("EA_PROACTIVE_OODA_STATE_PATH") or "state/proactive_ooda_notified.json").strip(),
        max_items=_safe_int(str(os.getenv("EA_PROACTIVE_OODA_MAX_ITEMS") or "5"), default=5),
        observation_lookback_hours=_safe_int(str(os.getenv("EA_PROACTIVE_OODA_OBSERVATION_LOOKBACK_HOURS") or "24"), default=24),
        observation_limit=_safe_int(str(os.getenv("EA_PROACTIVE_OODA_OBSERVATION_LIMIT") or "50"), default=50),
        skip_observation_source=_env_truthy("EA_PROACTIVE_OODA_OPERATOR_SKIP_OBSERVATION_SOURCE", default=True),
        skip_workspace_source=_env_truthy("EA_PROACTIVE_OODA_OPERATOR_SKIP_WORKSPACE_SOURCE", default=False),
        armed_send=_env_truthy("EA_PROACTIVE_OODA_ARMED_SEND", default=False),
        paused=_env_truthy("EA_PROACTIVE_OODA_PAUSED"),
        pause_reason=str(os.getenv("EA_PROACTIVE_OODA_PAUSE_REASON") or "").strip(),
        quiet_hours_start=str(os.getenv("EA_PROACTIVE_OODA_QUIET_HOURS_START") or "").strip(),
        quiet_hours_end=str(os.getenv("EA_PROACTIVE_OODA_QUIET_HOURS_END") or "").strip(),
        quiet_hours_timezone=str(os.getenv("EA_PROACTIVE_OODA_QUIET_HOURS_TIMEZONE") or os.getenv("TZ") or "UTC").strip(),
        quiet_hours_allow_high_priority=_env_truthy("EA_PROACTIVE_OODA_QUIET_HOURS_ALLOW_HIGH_PRIORITY", default=True),
        interruption_budget_limit=_safe_int(str(os.getenv("EA_PROACTIVE_OODA_INTERRUPTION_BUDGET_LIMIT") or "0"), default=0),
        interruption_budget_window_hours=_safe_int(str(os.getenv("EA_PROACTIVE_OODA_INTERRUPTION_BUDGET_WINDOW_HOURS") or "24"), default=24),
        interruption_budget_allow_high_priority=_env_truthy("EA_PROACTIVE_OODA_INTERRUPTION_BUDGET_ALLOW_HIGH_PRIORITY", default=True),
        stage_packet_dir=str(os.getenv("EA_PROACTIVE_OODA_STAGE_PACKET_DIR") or "").strip(),
        safe_work_result_dir=str(os.getenv("EA_PROACTIVE_OODA_SAFE_WORK_RESULT_DIR") or "").strip(),
        stage_packets=_env_truthy("EA_PROACTIVE_OODA_STAGE_PACKETS_ENABLED", default=True),
        safe_work_results=_env_truthy("EA_PROACTIVE_OODA_SAFE_WORK_RESULTS_ENABLED", default=True),
        require_stage_packets=False,
        require_safe_work_results=False,
        require_source=False,
        require_telegram=False,
        require_receipt_observation=False,
        pretty=False,
    )


def _deferred_reason(report: dict[str, Any]) -> str:
    return str(dict(report.get("delivery_guard") or {}).get("deferred_reason") or "").strip()


def _google_workspace_health_error_items(report: Mapping[str, Any]) -> list[str]:
    return [item for item in _report_errors(report) if item.startswith("google_workspace_signal_source_unhealthy:")]


def _has_only_workspace_health_errors(report: Mapping[str, Any]) -> bool:
    errors = _report_errors(report)
    if not errors:
        return False
    return len(_google_workspace_health_error_items(report)) == len(errors)


def _gmail_draft_followthrough_probe(principal_id: str, *, timeout_seconds: float | None = None) -> dict[str, Any]:
    try:
        return ea_live_ops.probe_proactive_gmail_draft(
            principal_id=principal_id,
            timeout_seconds=float(timeout_seconds or _live_probe_timeout_seconds()),
            output_format="json",
        )
    except Exception:
        return {}


def _source_coverage_probe(principal_id: str, *, timeout_seconds: float | None = None) -> dict[str, Any]:
    try:
        return ea_live_ops.probe_proactive_source_coverage(
            principal_id=principal_id,
            timeout_seconds=float(timeout_seconds or _live_probe_timeout_seconds()),
            output_format="json",
        )
    except Exception:
        return {}


def _approval_capture_probe(principal_id: str, *, timeout_seconds: float | None = None) -> dict[str, Any]:
    try:
        return ea_live_ops.probe_proactive_approval_capture(
            principal_id=principal_id,
            timeout_seconds=float(timeout_seconds or _live_probe_timeout_seconds()),
            output_format="json",
        )
    except Exception as exc:
        reason = type(exc).__name__
        return {
            "probe_ok": False,
            "ready": False,
            "status": "probe_failed",
            "source": "docker_compose_exec:proactive_approval_capture",
            "observed_at": _utc_now(),
            "blocking_reason": reason,
            "next_action": "inspect_proactive_approval_capture_runtime_probe",
            "privacy": {
                "raw_callback_token_exposed": False,
                "raw_principal_id_exposed": False,
                "raw_chat_ref_exposed": False,
                "raw_packet_ref_exposed": False,
                "raw_staged_artifact_ref_exposed": False,
            },
        }


def _approval_capture_summary(probe: Mapping[str, Any]) -> dict[str, Any]:
    if not probe:
        return {
            "checked": False,
            "probe_ok": False,
            "ready": False,
            "status": "not_checked",
            "source": "",
            "runtime_service": "",
            "observed_at": "",
            "blocking_reason": "",
            "next_action": "",
            "next_action_href": "",
            "next_action_label": "",
            "next_action_method": "",
            "callback_dir_exists": False,
            "callback_record_count": 0,
            "current_packet_ref_sha256": "",
            "current_staged_artifact_ref_sha256": "",
            "current_packet_refs_present": False,
            "current_packet_callback_record_count": 0,
            "current_packet_live_pending_count": 0,
            "current_packet_callback_latest_status": "",
            "current_packet_callback_latest_expired": False,
            "current_packet_callback_latest_age_seconds": 0,
            "current_packet_callback_latest_seconds_until_expiry": 0,
            "callback_principal_hash_present": False,
            "candidate_principal_hash_count": 0,
            "principal_match_ready": False,
            "telegram_binding_ready": False,
            "telegram_blocking_reason": "",
            "telegram_chat_ref_present": False,
            "telegram_chat_ref_sha256": "",
            "telegram_bot_key_present": False,
            "telegram_bot_token_present": False,
            "privacy": {
                "raw_callback_token_exposed": False,
                "raw_principal_id_exposed": False,
                "raw_chat_ref_exposed": False,
                "raw_packet_ref_exposed": False,
                "raw_staged_artifact_ref_exposed": False,
            },
        }
    privacy = dict(probe.get("privacy") or {})
    return {
        "checked": True,
        "probe_ok": bool(probe.get("probe_ok")),
        "ready": bool(probe.get("ready")),
        "status": str(probe.get("status") or "").strip() or "unknown",
        "source": str(probe.get("source") or "").strip(),
        "runtime_service": str(probe.get("runtime_service") or "").strip(),
        "observed_at": str(probe.get("observed_at") or "").strip(),
        "blocking_reason": str(probe.get("blocking_reason") or "").strip(),
        "next_action": str(probe.get("next_action") or "").strip(),
        "next_action_href": str(probe.get("next_action_href") or "").strip(),
        "next_action_label": str(probe.get("next_action_label") or "").strip(),
        "next_action_method": str(probe.get("next_action_method") or "").strip(),
        "callback_dir_exists": bool(probe.get("callback_dir_exists")),
        "callback_record_count": int(probe.get("callback_record_count") or 0),
        "current_packet_ref_sha256": str(probe.get("current_packet_ref_sha256") or "").strip(),
        "current_staged_artifact_ref_sha256": str(probe.get("current_staged_artifact_ref_sha256") or "").strip(),
        "current_packet_refs_present": bool(probe.get("current_packet_refs_present")),
        "current_packet_callback_record_count": int(probe.get("current_packet_callback_record_count") or 0),
        "current_packet_live_pending_count": int(probe.get("current_packet_live_pending_count") or 0),
        "current_packet_callback_latest_status": str(probe.get("current_packet_callback_latest_status") or "").strip(),
        "current_packet_callback_latest_expired": bool(probe.get("current_packet_callback_latest_expired")),
        "current_packet_callback_latest_age_seconds": int(probe.get("current_packet_callback_latest_age_seconds") or 0),
        "current_packet_callback_latest_seconds_until_expiry": int(
            probe.get("current_packet_callback_latest_seconds_until_expiry") or 0
        ),
        "callback_principal_hash_present": bool(probe.get("callback_principal_hash_present")),
        "candidate_principal_hash_count": int(probe.get("candidate_principal_hash_count") or 0),
        "principal_match_ready": bool(probe.get("principal_match_ready")),
        "telegram_binding_ready": bool(probe.get("telegram_binding_ready")),
        "telegram_blocking_reason": str(probe.get("telegram_blocking_reason") or "").strip(),
        "telegram_chat_ref_present": bool(probe.get("telegram_chat_ref_present")),
        "telegram_chat_ref_sha256": str(probe.get("telegram_chat_ref_sha256") or "").strip(),
        "telegram_bot_key_present": bool(probe.get("telegram_bot_key_present")),
        "telegram_bot_token_present": bool(probe.get("telegram_bot_token_present")),
        "privacy": {
            "raw_callback_token_exposed": bool(privacy.get("raw_callback_token_exposed")),
            "raw_principal_id_exposed": bool(privacy.get("raw_principal_id_exposed")),
            "raw_chat_ref_exposed": bool(privacy.get("raw_chat_ref_exposed")),
            "raw_packet_ref_exposed": bool(privacy.get("raw_packet_ref_exposed")),
            "raw_staged_artifact_ref_exposed": bool(privacy.get("raw_staged_artifact_ref_exposed")),
        },
    }


def _gmail_draft_followthrough_summary(probe: Mapping[str, Any]) -> dict[str, Any]:
    if not probe:
        return {
            "checked": False,
            "status": "not_checked",
            "source": "",
            "observed_at": "",
            "blocking_reason": "",
            "next_action": "",
            "next_action_href": "",
            "next_action_label": "",
            "next_action_method": "",
            "action": "",
            "work_type": "",
            "execution_observation_present": False,
            "execution_status": "",
            "execution_saved_at": "",
            "recipient_email_hash_present": False,
            "gmail_draft_id_hash_present": False,
            "gmail_message_id_hash_present": False,
            "draft_folder_url_hash_present": False,
            "raw_execution_payload_exposed": False,
        }
    return {
        "checked": bool(probe.get("probe_ok")),
        "status": str(probe.get("status") or "").strip() or "unknown",
        "source": str(probe.get("source") or "").strip(),
        "observed_at": str(probe.get("observed_at") or "").strip(),
        "blocking_reason": str(probe.get("blocking_reason") or "").strip(),
        "next_action": str(probe.get("next_action") or "").strip(),
        "next_action_href": str(probe.get("next_action_href") or "").strip(),
        "next_action_label": str(probe.get("next_action_label") or "").strip(),
        "next_action_method": str(probe.get("next_action_method") or "").strip(),
        "action": str(probe.get("action") or "").strip(),
        "work_type": str(probe.get("work_type") or "").strip(),
        "execution_observation_present": bool(probe.get("execution_observation_present")),
        "execution_status": str(probe.get("execution_status") or "").strip(),
        "execution_saved_at": str(probe.get("execution_saved_at") or "").strip(),
        "recipient_email_hash_present": bool(probe.get("recipient_email_hash_present")),
        "gmail_draft_id_hash_present": bool(probe.get("gmail_draft_id_hash_present")),
        "gmail_message_id_hash_present": bool(probe.get("gmail_message_id_hash_present")),
        "draft_folder_url_hash_present": bool(probe.get("draft_folder_url_hash_present")),
        "raw_execution_payload_exposed": bool(probe.get("raw_execution_payload_exposed")),
    }


def _source_coverage_summary(probe: Mapping[str, Any]) -> dict[str, Any]:
    if not probe:
        lanes = _source_coverage_fallback_lanes(status="not_checked")
        return {
            "checked": False,
            "status": "not_checked",
            "source": "",
            "observed_at": "",
            "observation_repository": "",
            "observation_limit": 0,
            "observation_row_count": 0,
            "lane_count": len(ea_live_ops.PROACTIVE_SOURCE_COVERAGE_LANE_KEYS),
            "observed_lane_count": 0,
            "missing_lane_keys": list(ea_live_ops.PROACTIVE_SOURCE_COVERAGE_LANE_KEYS),
            "lanes": lanes,
            "privacy": {
                "raw_rows_exposed": False,
                "raw_payload_exposed": False,
                "raw_transcript_text_exposed": False,
                "raw_credential_exposed": False,
                "source_ids_hashed": True,
            },
        }
    lanes = []
    for row in list(probe.get("lanes") or []):
        lane = dict(row or {}) if isinstance(row, Mapping) else {}
        lane_key = str(lane.get("key") or "").strip()
        lane_contract = SOURCE_COVERAGE_LANE_CONTRACTS.get(lane_key, {})
        required_event_types = [
            str(item).strip()
            for item in list(lane.get("required_event_types") or lane_contract.get("required_event_types") or [])
            if str(item).strip()
        ][:8]
        evidence_event_types = [
            str(item).strip()
            for item in list(lane.get("evidence_event_types") or [])
            if str(item).strip()
        ][:8]
        missing_required_event_types = [
            str(item).strip()
            for item in list(lane.get("missing_required_event_types") or [])
            if str(item).strip()
        ][:8]
        if required_event_types and not missing_required_event_types:
            observed_events = {item.lower() for item in evidence_event_types}
            missing_required_event_types = [
                item for item in required_event_types if item.lower() not in observed_events
            ][:8]
        required_event_type_observed = (
            bool(lane.get("required_event_type_observed", True))
            and not missing_required_event_types
        )
        lanes.append(
            {
                "key": lane_key,
                "label": str(lane.get("label") or "").strip(),
                "status": str(lane.get("status") or "").strip() or "unknown",
                "observed": bool(lane.get("observed")),
                "record_count": int(lane.get("record_count") or 0),
                "latest_observed_at": str(lane.get("latest_observed_at") or "").strip(),
                "evidence_event_types": evidence_event_types,
                "required_event_types": required_event_types,
                "required_event_type_observed": required_event_type_observed,
                "missing_required_event_types": missing_required_event_types,
                "next_action": str(lane.get("next_action") or "").strip()
                or (str(lane_contract.get("next_action") or "").strip() if not bool(lane.get("observed")) else ""),
                "raw_payload_exposed": bool(lane.get("raw_payload_exposed")),
                "raw_transcript_text_exposed": bool(lane.get("raw_transcript_text_exposed")),
                "raw_credential_exposed": bool(lane.get("raw_credential_exposed")),
            }
        )
    if not lanes:
        lanes = _source_coverage_fallback_lanes(status=str(probe.get("status") or "probe_failed").strip() or "probe_failed")
    privacy = dict(probe.get("privacy") or {})
    missing_lane_keys = [
        str(item).strip()
        for item in list(probe.get("missing_lane_keys") or [])
        if str(item).strip()
    ]
    if not missing_lane_keys:
        missing_lane_keys = [str(row["key"]) for row in lanes if not bool(row.get("observed"))]
    summary: dict[str, Any] = {
        "checked": bool(probe.get("checked", probe.get("probe_ok"))),
        "status": str(probe.get("status") or "").strip() or "unknown",
        "source": str(probe.get("source") or "").strip(),
        "observed_at": str(probe.get("observed_at") or "").strip(),
        "observation_repository": str(probe.get("observation_repository") or "").strip(),
        "observation_limit": int(probe.get("observation_limit") or 0),
        "observation_row_count": int(probe.get("observation_row_count") or 0),
        "lane_count": max(
            int(probe.get("lane_count") or 0),
            len(lanes),
            len(ea_live_ops.PROACTIVE_SOURCE_COVERAGE_LANE_KEYS),
        ),
        "observed_lane_count": int(probe.get("observed_lane_count") or 0),
        "missing_lane_keys": missing_lane_keys,
        "lanes": lanes,
        "privacy": {
            "raw_rows_exposed": bool(privacy.get("raw_rows_exposed")),
            "raw_payload_exposed": bool(privacy.get("raw_payload_exposed")),
            "raw_transcript_text_exposed": bool(privacy.get("raw_transcript_text_exposed")),
            "raw_credential_exposed": bool(privacy.get("raw_credential_exposed")),
            "source_ids_hashed": bool(privacy.get("source_ids_hashed", True)),
        },
    }
    if "flat_search_enabled" in probe:
        summary["flat_search_enabled"] = bool(probe.get("flat_search_enabled"))
        summary["excluded_event_types"] = [
            str(item).strip()
            for item in list(probe.get("excluded_event_types") or [])
            if str(item).strip()
        ][:8]
        summary["excluded_event_type_counts"] = {
            str(key or "").strip(): int(value or 0)
            for key, value in dict(probe.get("excluded_event_type_counts") or {}).items()
            if str(key or "").strip()
        }
    return summary


def _source_coverage_fallback_lanes(*, status: str) -> list[dict[str, Any]]:
    lanes: list[dict[str, Any]] = []
    normalized_status = str(status or "not_checked").strip() or "not_checked"
    for key in ea_live_ops.PROACTIVE_SOURCE_COVERAGE_LANE_KEYS:
        lane_contract = SOURCE_COVERAGE_LANE_CONTRACTS.get(str(key), {})
        required_event_types = [
            str(item).strip()
            for item in list(lane_contract.get("required_event_types") or [])
            if str(item).strip()
        ][:8]
        lanes.append(
            {
                "key": key,
                "status": normalized_status,
                "observed": False,
                "record_count": 0,
                "latest_observed_at": "",
                "evidence_event_types": [],
                "required_event_types": required_event_types,
                "required_event_type_observed": not required_event_types,
                "missing_required_event_types": required_event_types,
                "next_action": str(lane_contract.get("next_action") or "").strip(),
                "raw_payload_exposed": False,
                "raw_transcript_text_exposed": False,
                "raw_credential_exposed": False,
            }
        )
    return lanes


def _report_errors(report: Mapping[str, Any]) -> list[str]:
    return [str(item).strip() for item in list(report.get("errors") or []) if str(item).strip()]


def _runtime_error_next_action(report: Mapping[str, Any]) -> str:
    errors = _report_errors(report)
    first = errors[0] if errors else ""
    if first.startswith("google_workspace_signal_source_unhealthy:"):
        return "reauthorize_google_workspace_binding"
    if first:
        return "repair_proactive_runtime_inputs"
    return "maintain_proactive_ooda_runtime"


def _next_action_surface_fields(action: str) -> dict[str, str]:
    surface = proactive_next_action_surface(action)
    return {
        "next_action_href": str(surface.get("href") or "").strip(),
        "next_action_label": str(surface.get("label") or "").strip(),
        "next_action_method": str(surface.get("method") or "").strip(),
    }


def _approval_capture_surface_ready(surface: Mapping[str, Any] | None) -> bool:
    return bool(dict(surface or {}).get("ready"))


def _approval_capture_checked(probe: Mapping[str, Any] | None) -> bool:
    return bool(dict(probe or {}).get("checked"))


def _approval_capture_probe_ready(probe: Mapping[str, Any] | None) -> bool:
    normalized = dict(probe or {})
    if not bool(normalized.get("checked")):
        return True
    return bool(normalized.get("ready"))


def _approval_capture_probe_blocks_followthrough(
    *,
    status: str,
    live_receipt: Mapping[str, Any],
    live_receipt_checked: bool,
    approval_capture_surface: Mapping[str, Any] | None,
    approval_capture: Mapping[str, Any] | None,
) -> bool:
    if status in {"blocked_local_runtime", "blocked_delivery_route", "deferred", "ready_with_recovery_action"}:
        return False
    return (
        _approval_capture_surface_ready(approval_capture_surface)
        and live_receipt_checked
        and bool(live_receipt.get("ok"))
        and _approval_capture_checked(approval_capture)
        and not _approval_capture_probe_ready(approval_capture)
    )


def _approval_followthrough_ready(
    status: str,
    *,
    live_receipt: Mapping[str, Any],
    live_receipt_checked: bool,
    approval_capture_surface: Mapping[str, Any] | None,
    approval_capture: Mapping[str, Any] | None,
) -> bool:
    if status in {"blocked_local_runtime", "blocked_delivery_route", "deferred", "ready_with_recovery_action"}:
        return False
    return (
        _approval_capture_surface_ready(approval_capture_surface)
        and live_receipt_checked
        and bool(live_receipt.get("ok"))
        and _approval_capture_probe_ready(approval_capture)
    )


def _default_live_receipt_path() -> Path | None:
    explicit = str(
        os.getenv("EA_PROACTIVE_OODA_OPERATOR_RECEIPT_PATH")
        or os.getenv("EA_PROACTIVE_OODA_LIVE_RECEIPT_PATH")
        or os.getenv("EA_PROACTIVE_OODA_RECEIPT_PATH")
        or ""
    ).strip()
    if explicit:
        return Path(explicit)
    return live_receipt_verifier.default_receipt_path()


def _normalized_delivery_route(report: Mapping[str, Any]) -> dict[str, Any]:
    route = dict(report.get("delivery_route") or {})
    route.setdefault("ready", False)
    route.setdefault("route_error", "")
    route.setdefault("recovery_hint", "")
    route.setdefault("next_action", "")
    return route


def _normalized_delivery_guard(report: Mapping[str, Any]) -> dict[str, Any]:
    guard = dict(report.get("delivery_guard") or {})
    guard.setdefault("delivery_state", "")
    return guard


def _normalized_stage_packets(report: Mapping[str, Any]) -> dict[str, Any]:
    stage_packets = dict(report.get("stage_packets") or {})
    stage_packets.setdefault("ready", False)
    stage_packets.setdefault("errors", [])
    return stage_packets


def _normalized_safe_work_results(report: Mapping[str, Any]) -> dict[str, Any]:
    safe_work = dict(report.get("safe_work_results") or {})
    safe_work.setdefault("ready", False)
    safe_work.setdefault("errors", [])
    return safe_work


def _normalized_safe_work_audit(artifact_probe: Mapping[str, Any]) -> dict[str, Any]:
    stage_packet = dict(artifact_probe.get("stage_packet") or {})
    safe_work_result = dict(artifact_probe.get("safe_work_result") or {})
    audit = dict(safe_work_result.get("audit") or {})
    browser_receipt = dict(safe_work_result.get("browser_action_receipt") or {})
    result_status = str(safe_work_result.get("status") or "").strip()
    audit_status = str(audit.get("status") or "").strip().lower()
    issues = [dict(item or {}) for item in list(audit.get("issues") or []) if isinstance(item, Mapping)]
    materiality_issue = _safe_work_materiality_issue(
        stage_packet=stage_packet,
        safe_work_result=safe_work_result,
    )
    if materiality_issue:
        issues.append({"code": materiality_issue, "severity": "warn"})
    issue_codes = [str(item.get("code") or "").strip() for item in issues if str(item.get("code") or "").strip()]
    severity_counts: dict[str, int] = {}
    for issue in issues:
        severity = str(issue.get("severity") or "unknown").strip().lower() or "unknown"
        severity_counts[severity] = severity_counts.get(severity, 0) + 1
    browser_handoff_user_action_required = bool(
        result_status == "blocked_human_handoff_required" and browser_receipt.get("user_action_required")
    )
    effective_audit_status = "filtered" if materiality_issue else audit_status
    audit_passed = bool(effective_audit_status == "pass")
    delivery_allowed = bool(safe_work_result) and bool(audit_passed or browser_handoff_user_action_required)
    blocking_reason = ""
    filtered_non_material = bool(materiality_issue)
    if safe_work_result and not delivery_allowed and not filtered_non_material:
        blocking_reason = "safe_work_audit_not_pass"
        if not audit:
            blocking_reason = "safe_work_audit_missing"
        elif effective_audit_status:
            blocking_reason = f"safe_work_audit_{effective_audit_status}"
    return {
        "present": bool(safe_work_result),
        "source": str(artifact_probe.get("source") or "").strip(),
        "result_status": result_status,
        "audit_present": bool(audit),
        "audit_status": effective_audit_status or ("missing" if safe_work_result else ""),
        "audit_passed": audit_passed,
        "issue_count": len(issues),
        "issue_codes": issue_codes[:8],
        "issue_severity_counts": severity_counts,
        "filtered_non_material": filtered_non_material,
        "browser_handoff_user_action_required": browser_handoff_user_action_required,
        "delivery_allowed": delivery_allowed,
        "blocks_operator_followthrough": bool(safe_work_result and not delivery_allowed and not filtered_non_material),
        "blocking_reason": blocking_reason,
        "next_action": "repair_proactive_safe_work_audit" if blocking_reason else "",
        "privacy": {
            "raw_issue_details_exposed": False,
            "raw_candidate_exposed": False,
            "raw_draft_text_exposed": False,
            "raw_private_link_exposed": False,
        },
    }


def _safe_work_materiality_issue(
    *,
    stage_packet: Mapping[str, Any],
    safe_work_result: Mapping[str, Any],
) -> str:
    return safe_work_decision_materiality_issue(
        stage_packet=stage_packet,
        safe_work_result=safe_work_result,
    )


def _projection_table_record_count(projection_summary: Mapping[str, Any], table_name: str) -> int:
    tables = dict(dict(projection_summary or {}).get("tables") or {})
    return int(dict(tables.get(table_name) or {}).get("record_count") or 0)


def _normalized_suppressed_projection(artifact_probe: Mapping[str, Any]) -> dict[str, Any]:
    probe = dict(artifact_probe or {})
    quiet_receipt = dict(probe.get("action_required_only_quiet_receipt") or {})
    run_receipt = dict(probe.get("run_receipt") or {})
    candidate_receipts = [run_receipt] if run_receipt else [quiet_receipt] if quiet_receipt else []
    selected_receipt: dict[str, Any] = {}
    selected_summary: dict[str, Any] = {}
    for candidate in candidate_receipts:
        summary = dict(dict(candidate.get("teable_sync") or {}).get("projection_summary") or {})
        if int(summary.get("suppressed_item_count") or 0) > 0:
            selected_receipt = candidate
            selected_summary = summary
            break
    if not selected_receipt and candidate_receipts:
        selected_receipt = candidate_receipts[0]
        selected_summary = dict(dict(selected_receipt.get("teable_sync") or {}).get("projection_summary") or {})
    teable_sync = dict(selected_receipt.get("teable_sync") or {})
    item_table_count = _projection_table_record_count(selected_summary, "proactive_ooda_items")
    safe_work_table_count = _projection_table_record_count(selected_summary, "proactive_ooda_safe_work")
    packet_projection_record_count = item_table_count + safe_work_table_count
    suppressed_item_count = int(selected_summary.get("suppressed_item_count") or 0)
    suppressed_review_count = int(selected_summary.get("suppressed_safe_work_review_count") or 0)
    inferred_suppressed = False
    if (
        not suppressed_item_count
        and selected_receipt
        and str(teable_sync.get("status") or "").strip() in {"synced", "partial"}
        and str(selected_receipt.get("notification_status") or "").strip() == "deferred"
        and str(selected_receipt.get("error_code") or "").strip() == "no_user_action_required"
        and int(selected_receipt.get("item_count") or 0) > 0
        and packet_projection_record_count == 0
    ):
        suppressed_item_count = int(selected_receipt.get("item_count") or 0)
        inferred_suppressed = True
    reasons = [
        str(item or "").strip()
        for item in list(selected_summary.get("suppressed_projection_reasons") or [])
        if str(item or "").strip()
    ][:8]
    if inferred_suppressed and not reasons:
        reasons = ["packet_projection_suppressed"]
    issue_codes = [
        str(item or "").strip()
        for item in list(selected_summary.get("suppressed_safe_work_issue_codes") or [])
        if str(item or "").strip()
    ][:12]
    quiet_no_action = (
        str(selected_receipt.get("notification_status") or "").strip() == "deferred"
        and str(selected_receipt.get("error_code") or "").strip() == "no_user_action_required"
    )
    non_material_suppression = bool(
        suppressed_item_count > 0
        and quiet_no_action
        and issue_codes
        and all(code in NON_MATERIAL_SUPPRESSED_PROJECTION_ISSUE_CODES for code in issue_codes)
        and all(reason in NON_MATERIAL_SUPPRESSED_PROJECTION_REASONS for reason in reasons)
    )
    requires_recovery = suppressed_item_count > 0 and not non_material_suppression
    return {
        "present": bool(selected_receipt),
        "source": str(probe.get("source") or "").strip(),
        "status": (
            "suppressed"
            if requires_recovery
            else "suppressed_non_material"
            if non_material_suppression
            else "clear"
            if selected_receipt
            else "not_observed"
        ),
        "requires_recovery": requires_recovery,
        "blocking_reason": "suppressed_safe_work_projection" if requires_recovery else "",
        "next_action": "repair_proactive_safe_work_audit" if requires_recovery else "",
        "suppressed_non_material": non_material_suppression,
        "suppressed_non_material_reason": "quiet_no_decision_ready_material" if non_material_suppression else "",
        "run_receipt_generated_at": str(selected_receipt.get("generated_at") or "").strip(),
        "notification_status": str(selected_receipt.get("notification_status") or "").strip(),
        "error_code": str(selected_receipt.get("error_code") or "").strip(),
        "item_count": int(selected_receipt.get("item_count") or 0),
        "teable_status": str(teable_sync.get("status") or "").strip(),
        "projection_record_count": int(selected_summary.get("record_count") or 0),
        "packet_projection_record_count": packet_projection_record_count,
        "suppressed_item_count": suppressed_item_count,
        "suppressed_safe_work_review_count": suppressed_review_count,
        "suppressed_projection_reasons": reasons,
        "suppressed_safe_work_issue_codes": issue_codes,
        "inferred_from_packet_projection_gap": inferred_suppressed,
        "privacy": {
            "raw_packet_text_exposed": False,
            "raw_candidate_exposed": False,
            "raw_draft_text_exposed": False,
            "raw_private_link_exposed": False,
        },
    }


def _normalized_current_artifact_filter(artifact_probe: Mapping[str, Any]) -> dict[str, Any]:
    probe = dict(artifact_probe or {})
    reason = str(probe.get("artifact_filter_reason") or "").strip()
    issue_codes: list[str] = []
    if reason in {
        "single_official_info_link_not_decision_ready",
        "flat_search_disabled_property_scout",
        "flat_search_disabled",
    }:
        issue_codes.append(reason)
    requires_recovery = bool(reason) and reason not in NON_MATERIAL_ARTIFACT_FILTER_REASONS
    return {
        "present": bool(reason),
        "source": str(probe.get("source") or "").strip(),
        "reason": reason,
        "filter_status": "requires_recovery" if requires_recovery else "suppressed_non_material" if reason else "none",
        "requires_recovery": requires_recovery,
        "blocking_reason": f"filtered_current_artifact_{reason}" if requires_recovery else "",
        "next_action": "repair_proactive_safe_work_audit" if requires_recovery else "",
        "issue_codes": issue_codes,
        "privacy": {
            "raw_packet_text_exposed": False,
            "raw_candidate_exposed": False,
            "raw_draft_text_exposed": False,
            "raw_private_link_exposed": False,
        },
    }


def _safe_work_audit_blocks_operator(safe_work_audit: Mapping[str, Any]) -> bool:
    return bool(dict(safe_work_audit or {}).get("blocks_operator_followthrough"))


def _safe_work_audit_blocking_reason(safe_work_audit: Mapping[str, Any]) -> str:
    return (
        str(dict(safe_work_audit or {}).get("blocking_reason") or "").strip()
        or "safe_work_audit_not_pass"
    )


def _has_explicit_artifact_dirs(report_args: argparse.Namespace) -> bool:
    return bool(
        str(getattr(report_args, "stage_packet_dir", "") or "").strip()
        or str(getattr(report_args, "safe_work_result_dir", "") or "").strip()
    )


def _normalized_context_grounding(report: Mapping[str, Any]) -> dict[str, Any]:
    context = dict(report.get("context_grounding") or {})
    item_count = int(context.get("item_count") or report.get("actionable_count") or 0)
    grounded_item_count = int(context.get("grounded_item_count") or 0)
    applied_context_count = int(context.get("applied_context_count") or 0)
    ungrounded_item_count = int(context.get("ungrounded_item_count") or max(item_count - grounded_item_count, 0))
    return {
        "grounded": bool(context.get("grounded")) and applied_context_count > 0 and ungrounded_item_count == 0,
        "item_count": item_count,
        "grounded_item_count": grounded_item_count,
        "ungrounded_item_count": ungrounded_item_count,
        "applied_context_count": applied_context_count,
        "notes_count": int(context.get("notes_count") or 0),
        "preference_count": int(context.get("preference_count") or 0),
        "requirement_count": int(context.get("requirement_count") or 0),
        "exclusion_count": int(context.get("exclusion_count") or 0),
        "deadline_count": int(context.get("deadline_count") or 0),
        "candidate_assessment_count": int(context.get("candidate_assessment_count") or 0),
        "recipient_context_count": int(context.get("recipient_context_count") or 0),
        "recipient_location_count": int(context.get("recipient_location_count") or 0),
    }


def _status(report: dict[str, Any], *, live_receipt: dict[str, Any], live_receipt_checked: bool) -> str:
    route = _normalized_delivery_route(report)
    guard = _normalized_delivery_guard(report)
    stage_packets = _normalized_stage_packets(report)
    safe_work = _normalized_safe_work_results(report)
    route_ready = bool(route.get("ready"))
    route_error = str(route.get("route_error") or "").strip()
    delivery_state = str(guard.get("delivery_state") or "").strip()
    if delivery_state == "deferred":
        return "deferred"
    if route_error:
        return "ready_with_recovery_action" if route_ready else "blocked_delivery_route"
    if not route_ready:
        return "blocked_delivery_route"
    if not bool(stage_packets.get("ready")) or not bool(safe_work.get("ready")):
        return "blocked_local_runtime"
    if not bool(report.get("ok")) and not _has_only_workspace_health_errors(report):
        return "blocked_local_runtime"
    if not bool(report.get("ok")) and _has_only_workspace_health_errors(report):
        return "ready_with_recovery_action"
    if live_receipt_checked and bool(live_receipt.get("ok")):
        return "ready_with_live_receipt"
    return "ready_local_runtime"


def _reason(report: dict[str, Any], *, live_receipt: dict[str, Any], live_receipt_checked: bool) -> str:
    route = _normalized_delivery_route(report)
    guard = _normalized_delivery_guard(report)
    stage_packets = _normalized_stage_packets(report)
    safe_work = _normalized_safe_work_results(report)
    route_error = str(route.get("route_error") or "").strip()
    if route_error:
        return route_error
    deferred_reason = _deferred_reason(report)
    if deferred_reason:
        return deferred_reason
    stage_errors = [str(item).strip() for item in list(stage_packets.get("errors") or []) if str(item).strip()]
    if stage_errors:
        return stage_errors[0]
    safe_errors = [str(item).strip() for item in list(safe_work.get("errors") or []) if str(item).strip()]
    if safe_errors:
        return safe_errors[0]
    errors = [str(item).strip() for item in list(report.get("errors") or []) if str(item).strip()]
    if errors:
        return errors[0]
    if live_receipt_checked and not bool(live_receipt.get("ok")):
        live_errors = [str(item).strip() for item in list(live_receipt.get("errors") or []) if str(item).strip()]
        if live_errors:
            return live_errors[0]
    return "ready"


def _next_action(report: dict[str, Any], *, live_receipt: dict[str, Any], live_receipt_checked: bool) -> str:
    route = _normalized_delivery_route(report)
    guard = _normalized_delivery_guard(report)
    stage_packets = _normalized_stage_packets(report)
    safe_work = _normalized_safe_work_results(report)
    next_action = str(route.get("next_action") or "").strip()
    if next_action:
        return next_action
    deferred_reason = _deferred_reason(report)
    if deferred_reason == "deferred_by_operator_pause":
        return "clear_proactive_operator_pause"
    if deferred_reason == "deferred_by_quiet_hours":
        return "resume_after_quiet_hours"
    if deferred_reason == "deferred_by_interruption_budget":
        return "wait_for_interruption_budget_window"
    if deferred_reason == "deferred_by_unarmed_send":
        return "arm_proactive_send_for_live_delivery"
    if not bool(stage_packets.get("ready")):
        return "repair_proactive_stage_packet_runtime"
    if not bool(safe_work.get("ready")):
        return "repair_proactive_safe_work_runtime"
    if _report_errors(report):
        return _runtime_error_next_action(report)
    if live_receipt_checked and not bool(live_receipt.get("ok")):
        return str(live_receipt.get("delivery_next_action") or "refresh_proactive_live_receipt").strip() or "refresh_proactive_live_receipt"
    if live_receipt_checked and bool(live_receipt.get("ok")):
        return "maintain_proactive_ooda_runtime"
    return "run_or_mirror_live_proactive_ooda_receipt"


def _operator_followthrough_next_action(
    status: str,
    report: dict[str, Any],
    *,
    live_receipt: dict[str, Any],
    live_receipt_checked: bool,
    approval_capture_surface: Mapping[str, Any] | None,
    approval_capture: Mapping[str, Any] | None,
) -> str:
    if _approval_followthrough_ready(
        status,
        live_receipt=live_receipt,
        live_receipt_checked=live_receipt_checked,
        approval_capture_surface=approval_capture_surface,
        approval_capture=approval_capture,
    ):
        if bool(dict(approval_capture_surface or {}).get("manual_outcome_capture_ready")):
            return "record_proactive_ooda_approval_outcome"
        return "tap_proactive_telegram_approval_button_or_record_proactive_ooda_approval_outcome"
    if _approval_capture_probe_blocks_followthrough(
        status=status,
        live_receipt=live_receipt,
        live_receipt_checked=live_receipt_checked,
        approval_capture_surface=approval_capture_surface,
        approval_capture=approval_capture,
    ):
        return str(dict(approval_capture or {}).get("next_action") or "repair_proactive_approval_capture").strip()
    return _next_action(report, live_receipt=live_receipt, live_receipt_checked=live_receipt_checked)


def _summary(
    status: str,
    report: dict[str, Any],
    *,
    live_receipt: dict[str, Any],
    live_receipt_checked: bool,
    approval_capture_surface: dict[str, Any] | None = None,
    approval_capture: dict[str, Any] | None = None,
) -> str:
    route = dict(report.get("delivery_route") or {})
    route_error = str(route.get("route_error") or "").strip()
    recovery_hint = str(route.get("recovery_hint") or "").strip()
    delivery_state = str(dict(report.get("delivery_guard") or {}).get("delivery_state") or "").strip()
    deferred_reason = _deferred_reason(report)
    if status == "deferred":
        if deferred_reason == "deferred_by_unarmed_send":
            return "Proactive OODA delivery is intentionally stage-only because send arming is disabled for this runtime."
        return f"Proactive OODA delivery is currently deferred by {delivery_state or 'operator policy'}."
    if status == "ready_with_recovery_action":
        first_error = _report_errors(report)[0] if _report_errors(report) else ""
        if first_error.startswith("google_workspace_signal_source_unhealthy:"):
            reason = first_error.split(":", 1)[1].strip() if ":" in first_error else "google_workspace_unhealthy"
            return (
                "Proactive OODA routing is available, but Google workspace needs reauthorization "
                f"before EA can rely on that source ({reason})."
            )
        base = f"Proactive OODA can still route, but a preferred delivery path needs recovery: {route_error or 'route recovery required'}."
        return f"{base} {recovery_hint}".strip()
    if status == "blocked_delivery_route":
        base = f"No proactive delivery route is currently ready: {route_error or 'delivery_route_unavailable'}."
        return f"{base} {recovery_hint}".strip()
    if status == "blocked_local_runtime":
        errors = _report_errors(report)
        first = errors[0] if errors else ""
        if first.startswith("google_workspace_signal_source_unhealthy:"):
            reason = first.split(":", 1)[1].strip() if ":" in first else "google_workspace_unhealthy"
            return (
                "Proactive OODA routing is available, but Google workspace needs reauthorization "
                f"before EA can rely on that source ({reason})."
            )
        return "Proactive OODA routing is available, but stage-packet or safe-work runtime posture is still blocked."
    if status == "ready_with_live_receipt":
        if _approval_capture_probe_blocks_followthrough(
            status=status,
            live_receipt=live_receipt,
            live_receipt_checked=live_receipt_checked,
            approval_capture_surface=approval_capture_surface,
            approval_capture=approval_capture,
        ):
            reason = str(dict(approval_capture or {}).get("blocking_reason") or "approval_capture_not_ready").strip()
            return f"Proactive OODA route, packet runtime, and latest host-visible live receipt are ready, but approval capture needs recovery: {reason}."
        if bool(dict(approval_capture_surface or {}).get("ready")):
            if bool(dict(approval_capture_surface or {}).get("manual_outcome_capture_ready")):
                return "Proactive OODA route, packet runtime, latest host-visible live receipt, and manual approval outcome capture are ready for operator follow-through."
            return "Proactive OODA route, packet runtime, latest host-visible live receipt, and Telegram approval capture surface are ready for operator follow-through."
        return "Proactive OODA route, packet runtime, and latest host-visible live receipt are ready for operator follow-through."
    if live_receipt_checked:
        return "Proactive OODA route and packet runtime are locally ready; refresh accepted live receipt evidence next."
    return "Proactive OODA route and packet runtime are locally ready; mirror a host-visible live receipt when the next real packet is sent."


def _operator_action_state(status: str, *, report: dict[str, Any]) -> str:
    if _deferred_reason(report) == "deferred_by_unarmed_send":
        return "arming_required"
    if status == "deferred":
        return "deferred"
    if status in {"ready_with_recovery_action", "blocked_delivery_route", "blocked_local_runtime"}:
        return "recovery_required"
    if status == "ready_with_live_receipt":
        return "clear"
    return "live_proof_pending"


def _operator_followthrough_action_state(
    status: str,
    *,
    report: dict[str, Any],
    live_receipt: dict[str, Any],
    live_receipt_checked: bool,
    approval_capture_surface: Mapping[str, Any] | None,
    approval_capture: Mapping[str, Any] | None,
) -> str:
    if _approval_followthrough_ready(
        status,
        live_receipt=live_receipt,
        live_receipt_checked=live_receipt_checked,
        approval_capture_surface=approval_capture_surface,
        approval_capture=approval_capture,
    ):
        return "approval_capture_pending"
    if _approval_capture_probe_blocks_followthrough(
        status=status,
        live_receipt=live_receipt,
        live_receipt_checked=live_receipt_checked,
        approval_capture_surface=approval_capture_surface,
        approval_capture=approval_capture,
    ):
        return "recovery_required"
    return _operator_action_state(status, report=report)


def _operator_delivery_guard(
    status: str,
    report: Mapping[str, Any],
    *,
    live_receipt: Mapping[str, Any],
    live_receipt_checked: bool,
    approval_capture_surface: Mapping[str, Any] | None,
    approval_capture: Mapping[str, Any] | None,
) -> dict[str, Any]:
    guard = _normalized_delivery_guard(report)
    if not _approval_followthrough_ready(
        status,
        live_receipt=live_receipt,
        live_receipt_checked=live_receipt_checked,
        approval_capture_surface=approval_capture_surface,
        approval_capture=approval_capture,
    ):
        return guard
    runtime_delivery_state = str(guard.get("delivery_state") or "").strip()
    if runtime_delivery_state and runtime_delivery_state != "approval_capture_pending":
        guard["runtime_delivery_state"] = runtime_delivery_state
    guard["delivery_state"] = "approval_capture_pending"
    guard["user_action_required"] = True
    guard["pending_approval_surface"] = True
    guard["manual_outcome_capture_ready"] = bool(
        dict(approval_capture_surface or {}).get("manual_outcome_capture_ready")
    )
    guard["current_packet_live_pending_count"] = int(
        dict(approval_capture_surface or {}).get("current_packet_live_pending_count") or 0
    )
    return guard


def _operator_actionable_count(
    report: Mapping[str, Any],
    *,
    status: str,
    live_receipt: Mapping[str, Any],
    live_receipt_checked: bool,
    approval_capture_surface: Mapping[str, Any] | None,
    approval_capture: Mapping[str, Any] | None,
) -> int:
    runtime_count = int(report.get("actionable_count") or 0)
    if not _approval_followthrough_ready(
        status,
        live_receipt=live_receipt,
        live_receipt_checked=live_receipt_checked,
        approval_capture_surface=approval_capture_surface,
        approval_capture=approval_capture,
    ):
        return runtime_count
    pending_count = int(dict(approval_capture_surface or {}).get("current_packet_live_pending_count") or 0)
    if pending_count <= 0 and bool(dict(approval_capture_surface or {}).get("manual_outcome_capture_ready")):
        pending_count = 1
    return max(runtime_count, pending_count, 1)


def _hash_value(value: str) -> str:
    normalized = str(value or "").strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest() if normalized else ""


def _stage_packet_ref(stage_packet: Mapping[str, Any]) -> str:
    return str(stage_packet.get("packet_ref") or stage_packet.get("packet_id") or "").strip()


def _safe_work_result_ref(safe_work_result: Mapping[str, Any]) -> str:
    result_ref = str(safe_work_result.get("result_ref") or "").strip()
    if result_ref:
        return result_ref
    result_id = str(safe_work_result.get("result_id") or "").strip()
    return f"safe_work_result:{result_id}" if result_id else ""


def _approval_outcome_matches_current_packet(artifact_probe: Mapping[str, Any]) -> bool:
    current_packet = dict(artifact_probe.get("current_packet") or {})
    if "approval_outcome_matches_current_packet" in current_packet:
        return bool(current_packet.get("approval_outcome_matches_current_packet"))
    if "approval_outcome_matches_current_packet" in artifact_probe:
        return bool(artifact_probe.get("approval_outcome_matches_current_packet"))
    approval_outcome = dict(artifact_probe.get("approval_outcome") or {})
    if not bool(approval_outcome.get("approval_outcome_recorded")):
        return False
    stage_packet = dict(artifact_probe.get("stage_packet") or {})
    safe_work_result = dict(artifact_probe.get("safe_work_result") or {})
    packet_ref = _stage_packet_ref(stage_packet)
    staged_artifact_ref = _safe_work_result_ref(safe_work_result)
    return bool(
        packet_ref
        and staged_artifact_ref
        and str(approval_outcome.get("packet_ref_sha256") or "").strip() == _hash_value(packet_ref)
        and str(approval_outcome.get("staged_artifact_sha256") or "").strip() == _hash_value(staged_artifact_ref)
    )


def _current_packet_approval_request_recordable(artifact_probe: Mapping[str, Any]) -> bool:
    stage_packet = dict(artifact_probe.get("stage_packet") or {})
    safe_work_result = dict(artifact_probe.get("safe_work_result") or {})
    packet_ref = _stage_packet_ref(stage_packet)
    staged_artifact_ref = _safe_work_result_ref(safe_work_result)
    stage_approval = dict(stage_packet.get("approval") or {})
    safe_work_approval = dict(safe_work_result.get("approval") or {})
    stage_payload = dict(dict(stage_packet.get("stage") or {}).get("payload") or {})
    approval_required = bool(stage_approval.get("required")) or bool(safe_work_approval.get("required"))
    approval_surface_present = bool(
        str(safe_work_result.get("approval_prompt") or stage_payload.get("approval_prompt") or "").strip()
        or str(safe_work_result.get("staged_action_url") or stage_payload.get("approval_url") or "").strip()
    )
    return bool(
        packet_ref
        and staged_artifact_ref
        and str(safe_work_result.get("status") or "").strip() == "staged_for_user_decision"
        and approval_required
        and approval_surface_present
    )


def _approval_capture_surface(
    *,
    report: dict[str, Any],
    artifact_probe: dict[str, Any],
) -> dict[str, Any]:
    delivery_route = _normalized_delivery_route(report)
    selected_channel = str(delivery_route.get("selected_channel") or "").strip()
    callback_dir = str(artifact_probe.get("approval_callback_dir") or "").strip()
    approval_outcome_path = str(artifact_probe.get("approval_outcome_path") or "").strip()
    callback_dir_writable = bool(artifact_probe.get("approval_callback_dir_writable"))
    current_packet_callback_record_count = int(artifact_probe.get("current_packet_callback_record_count") or 0)
    current_packet_callback_pending_count = int(artifact_probe.get("current_packet_callback_pending_count") or 0)
    current_packet_callback_raw_pending_count = int(
        artifact_probe.get("current_packet_callback_raw_pending_count") or current_packet_callback_pending_count
    )
    current_packet_callback_stale_pending_count = int(artifact_probe.get("current_packet_callback_stale_pending_count") or 0)
    current_packet_callback_expired_pending_count = int(artifact_probe.get("current_packet_callback_expired_pending_count") or 0)
    current_packet_callback_recorded_count = int(artifact_probe.get("current_packet_callback_recorded_count") or 0)
    current_packet_callback_expired_count = int(artifact_probe.get("current_packet_callback_expired_count") or 0)
    current_packet_callback_superseded_count = int(artifact_probe.get("current_packet_callback_superseded_count") or 0)
    current_packet_live_callback_record_count = int(artifact_probe.get("current_packet_live_callback_record_count") or 0)
    current_packet_live_pending_count = int(artifact_probe.get("current_packet_live_pending_count") or 0)
    current_packet_callback_latest_status = str(artifact_probe.get("current_packet_callback_latest_status") or "").strip()
    current_packet_callback_latest_expired = bool(artifact_probe.get("current_packet_callback_latest_expired"))
    current_packet_callback_latest_created_at = str(
        artifact_probe.get("current_packet_callback_latest_created_at") or ""
    ).strip()
    current_packet_callback_latest_expires_at = str(
        artifact_probe.get("current_packet_callback_latest_expires_at") or ""
    ).strip()
    current_packet_callback_latest_age_seconds = int(
        artifact_probe.get("current_packet_callback_latest_age_seconds") or 0
    )
    current_packet_callback_latest_seconds_until_expiry = int(
        artifact_probe.get("current_packet_callback_latest_seconds_until_expiry") or 0
    )
    current_packet = dict(artifact_probe.get("current_packet") or {})
    approval_outcome_matches_current_packet = _approval_outcome_matches_current_packet(artifact_probe)
    manual_outcome_capture_ready = bool(
        _current_packet_approval_request_recordable(artifact_probe)
        and not approval_outcome_matches_current_packet
        and current_packet_live_pending_count <= 0
    )
    ready = (
        bool(delivery_route.get("ready"))
        and bool(dict(report.get("stage_packets") or {}).get("ready"))
        and bool(dict(report.get("safe_work_results") or {}).get("ready"))
        and selected_channel == "telegram"
        and bool(approval_outcome_path)
        and bool(callback_dir)
        and callback_dir_writable
        and (current_packet_live_pending_count > 0 or manual_outcome_capture_ready)
    )
    return {
        "present": bool(approval_outcome_path or callback_dir),
        "ready": ready,
        "mode": (
            "telegram_callback_pending"
            if current_packet_live_pending_count > 0
            else "manual_outcome_capture_ready"
            if manual_outcome_capture_ready
            else ""
        ),
        "selected_channel": selected_channel,
        "approval_outcome_path": approval_outcome_path,
        "callback_dir": callback_dir,
        "callback_dir_exists": bool(artifact_probe.get("approval_callback_dir_exists")),
        "callback_dir_writable": callback_dir_writable,
        "callback_record_count": int(artifact_probe.get("approval_callback_record_count") or 0),
        "callback_pending_count": int(artifact_probe.get("approval_callback_pending_count") or 0),
        "callback_raw_pending_count": int(artifact_probe.get("approval_callback_raw_pending_count") or artifact_probe.get("approval_callback_pending_count") or 0),
        "callback_live_pending_count": int(artifact_probe.get("approval_callback_live_pending_count") or artifact_probe.get("approval_callback_pending_count") or 0),
        "callback_unexpired_pending_count": int(artifact_probe.get("approval_callback_unexpired_pending_count") or 0),
        "callback_noncurrent_pending_count": int(artifact_probe.get("approval_callback_noncurrent_pending_count") or 0),
        "callback_stale_pending_count": int(artifact_probe.get("approval_callback_stale_pending_count") or 0),
        "callback_expired_pending_count": int(artifact_probe.get("approval_callback_expired_pending_count") or 0),
        "callback_recorded_count": int(artifact_probe.get("approval_callback_recorded_count") or 0),
        "callback_expired_count": int(artifact_probe.get("approval_callback_expired_count") or 0),
        "callback_superseded_count": int(artifact_probe.get("approval_callback_superseded_count") or 0),
        "callback_terminal_count": int(artifact_probe.get("approval_callback_terminal_count") or 0),
        "current_packet_callback_record_count": current_packet_callback_record_count,
        "current_packet_callback_pending_count": current_packet_callback_pending_count,
        "current_packet_callback_raw_pending_count": current_packet_callback_raw_pending_count,
        "current_packet_callback_stale_pending_count": current_packet_callback_stale_pending_count,
        "current_packet_callback_expired_pending_count": current_packet_callback_expired_pending_count,
        "current_packet_callback_recorded_count": current_packet_callback_recorded_count,
        "current_packet_callback_expired_count": current_packet_callback_expired_count,
        "current_packet_callback_superseded_count": current_packet_callback_superseded_count,
        "current_packet_live_callback_record_count": current_packet_live_callback_record_count,
        "current_packet_live_pending_count": current_packet_live_pending_count,
        "current_packet_callback_latest_status": current_packet_callback_latest_status,
        "current_packet_callback_latest_expired": current_packet_callback_latest_expired,
        "current_packet_callback_latest_created_at": current_packet_callback_latest_created_at,
        "current_packet_callback_latest_expires_at": current_packet_callback_latest_expires_at,
        "current_packet_callback_latest_age_seconds": current_packet_callback_latest_age_seconds,
        "current_packet_callback_latest_seconds_until_expiry": current_packet_callback_latest_seconds_until_expiry,
        "current_packet_status": str(current_packet.get("status") or "").strip(),
        "current_packet_present": bool(current_packet.get("present")) or bool(
            artifact_probe.get("stage_packet") or artifact_probe.get("safe_work_result")
        ),
        "current_packet_approval_request_recordable": _current_packet_approval_request_recordable(artifact_probe),
        "approval_outcome_matches_current_packet": approval_outcome_matches_current_packet,
        "manual_outcome_capture_ready": manual_outcome_capture_ready,
        "source": str(artifact_probe.get("source") or "").strip() or "",
    }


def _local_artifact_probe(
    *,
    report_args: argparse.Namespace,
    live_receipt_path: Path | None,
) -> dict[str, Any]:
    bundle = load_runtime_artifact_bundle(
        root=ROOT,
        state_path=str(getattr(report_args, "state_path", "state/proactive_ooda_notified.json") or "state/proactive_ooda_notified.json"),
        receipt_path=str(live_receipt_path or ""),
        stage_packet_dir=str(getattr(report_args, "stage_packet_dir", "") or ""),
        safe_work_result_dir=str(getattr(report_args, "safe_work_result_dir", "") or ""),
    )
    return {
        "source": "local_filesystem",
        "approval_outcome_path": bundle.get("approval_outcome_path"),
        "approval_callback_dir": bundle.get("approval_callback_dir"),
        "approval_callback_dir_exists": bool(bundle.get("approval_callback_dir_exists")),
        "approval_callback_dir_writable": bool(bundle.get("approval_callback_dir_writable")),
        "approval_callback_record_count": int(bundle.get("approval_callback_record_count") or 0),
        "approval_callback_pending_count": int(bundle.get("approval_callback_pending_count") or 0),
        "approval_callback_raw_pending_count": int(bundle.get("approval_callback_raw_pending_count") or bundle.get("approval_callback_pending_count") or 0),
        "approval_callback_live_pending_count": int(bundle.get("approval_callback_live_pending_count") or bundle.get("approval_callback_pending_count") or 0),
        "approval_callback_unexpired_pending_count": int(bundle.get("approval_callback_unexpired_pending_count") or 0),
        "approval_callback_noncurrent_pending_count": int(bundle.get("approval_callback_noncurrent_pending_count") or 0),
        "approval_callback_stale_pending_count": int(bundle.get("approval_callback_stale_pending_count") or 0),
        "approval_callback_expired_pending_count": int(bundle.get("approval_callback_expired_pending_count") or 0),
        "approval_callback_recorded_count": int(bundle.get("approval_callback_recorded_count") or 0),
        "approval_callback_expired_count": int(bundle.get("approval_callback_expired_count") or 0),
        "approval_callback_superseded_count": int(bundle.get("approval_callback_superseded_count") or 0),
        "approval_callback_terminal_count": int(bundle.get("approval_callback_terminal_count") or 0),
        "current_packet_callback_record_count": int(bundle.get("current_packet_callback_record_count") or 0),
        "current_packet_callback_pending_count": int(bundle.get("current_packet_callback_pending_count") or 0),
        "current_packet_callback_raw_pending_count": int(
            bundle.get("current_packet_callback_raw_pending_count") or bundle.get("current_packet_callback_pending_count") or 0
        ),
        "current_packet_callback_stale_pending_count": int(bundle.get("current_packet_callback_stale_pending_count") or 0),
        "current_packet_callback_expired_pending_count": int(bundle.get("current_packet_callback_expired_pending_count") or 0),
        "current_packet_callback_recorded_count": int(bundle.get("current_packet_callback_recorded_count") or 0),
        "current_packet_callback_expired_count": int(bundle.get("current_packet_callback_expired_count") or 0),
        "current_packet_callback_superseded_count": int(bundle.get("current_packet_callback_superseded_count") or 0),
        "current_packet_live_callback_record_count": int(bundle.get("current_packet_live_callback_record_count") or 0),
        "current_packet_live_pending_count": int(bundle.get("current_packet_live_pending_count") or 0),
        "current_packet_callback_latest_status": str(bundle.get("current_packet_callback_latest_status") or "").strip(),
        "current_packet_callback_latest_expired": bool(bundle.get("current_packet_callback_latest_expired")),
        "current_packet_callback_latest_created_at": str(bundle.get("current_packet_callback_latest_created_at") or "").strip(),
        "current_packet_callback_latest_expires_at": str(bundle.get("current_packet_callback_latest_expires_at") or "").strip(),
        "current_packet_callback_latest_age_seconds": int(bundle.get("current_packet_callback_latest_age_seconds") or 0),
        "current_packet_callback_latest_seconds_until_expiry": int(
            bundle.get("current_packet_callback_latest_seconds_until_expiry") or 0
        ),
        "stage_packet": dict(bundle.get("stage_packet") or {}),
        "safe_work_result": dict(bundle.get("safe_work_result") or {}),
        "approval_outcome": dict(bundle.get("approval_outcome") or {}),
        "run_receipt": dict(bundle.get("run_receipt") or {}),
        "action_required_only_quiet_receipt": dict(bundle.get("action_required_only_quiet_receipt") or {}),
    }


def build_proactive_ooda_operator_status(
    *,
    output_path: Path = DEFAULT_OUTPUT,
    generated_at: str | None = None,
    report_args: argparse.Namespace | None = None,
    live_receipt_path: Path | None = None,
    allow_live_route_probe: bool = True,
    skip_gmail_draft_followthrough_probe: bool = False,
    skip_source_coverage_probe: bool = False,
) -> dict[str, Any]:
    effective_report_args = report_args or _default_report_args()
    route_probe: dict[str, Any] = {}
    artifact_probe: dict[str, Any] = {}
    approval_capture_probe: dict[str, Any] = {}
    gmail_draft_probe: dict[str, Any] = {}
    source_coverage_probe: dict[str, Any] = {}
    principal_id = str(getattr(effective_report_args, "principal_id", "") or proactive_verifier._default_principal_id()).strip()
    live_probe_timeout_seconds = _live_probe_timeout_seconds()
    effective_live_receipt_path = live_receipt_path if live_receipt_path is not None else _default_live_receipt_path()
    if allow_live_route_probe:
        try:
            route_probe = ea_live_ops.probe_proactive_route(
                principal_id=principal_id,
                receipt_path=str(live_receipt_path or ""),
                timeout_seconds=live_probe_timeout_seconds,
            )
        except Exception:
            route_probe = {}
        if isinstance(route_probe.get("artifact_probe"), dict):
            artifact_probe = dict(route_probe.get("artifact_probe") or {})
        if live_receipt_path is None:
            if not artifact_probe:
                try:
                    artifact_probe = ea_live_ops.probe_proactive_artifacts(
                        timeout_seconds=live_probe_timeout_seconds,
                        output_format="json",
                    )
                except Exception:
                    artifact_probe = {}
            if not skip_gmail_draft_followthrough_probe:
                gmail_draft_probe = _gmail_draft_followthrough_probe(principal_id, timeout_seconds=live_probe_timeout_seconds)
        if not skip_source_coverage_probe:
            source_coverage_probe = _source_coverage_probe(principal_id, timeout_seconds=live_probe_timeout_seconds)

    if bool(route_probe.get("probe_ok")) and isinstance(route_probe.get("route_report"), dict):
        report = dict(route_probe.get("route_report") or {})
        live_receipt = dict(route_probe.get("live_receipt") or {})
        live_receipt_checked = bool(route_probe.get("live_receipt_checked"))
        if (
            live_receipt_checked
            and effective_live_receipt_path is not None
            and not str(live_receipt.get("receipt_path") or "").strip()
        ):
            live_receipt["receipt_path"] = str(effective_live_receipt_path)
    else:
        report = proactive_verifier._build_report(effective_report_args)
        live_receipt_checked = effective_live_receipt_path is not None
        live_receipt = (
            live_receipt_verifier.verify_receipt(effective_live_receipt_path)
            if effective_live_receipt_path is not None
            else {
                "ok": False,
                "errors": [],
                "receipt_path": "",
                "notification_status": "not_checked",
                "delivery_channel": "",
                "delivery_message_count": 0,
                "telegram_message_count": 0,
                "delivery_route_error": "",
                "delivery_recovery_hint": "",
                "delivery_next_action": "",
                "generated_at": "",
            }
        )
        artifact_probe = _local_artifact_probe(
            report_args=effective_report_args,
            live_receipt_path=effective_live_receipt_path,
        )
    if not artifact_probe:
        artifact_probe = _local_artifact_probe(
            report_args=effective_report_args,
            live_receipt_path=live_receipt_path,
        )
    safe_work_audit_probe: Mapping[str, Any] = artifact_probe
    if (
        live_receipt_path is not None
        and str(artifact_probe.get("source") or "").strip() == "local_filesystem"
        and not _has_explicit_artifact_dirs(effective_report_args)
    ):
        safe_work_audit_probe = {}
    safe_work_audit = _normalized_safe_work_audit(safe_work_audit_probe)
    safe_work_audit_blocks = _safe_work_audit_blocks_operator(safe_work_audit)
    current_artifact_filter = _normalized_current_artifact_filter(artifact_probe)
    current_artifact_filter_blocks = bool(current_artifact_filter.get("requires_recovery"))
    suppressed_projection = _normalized_suppressed_projection(artifact_probe)
    suppressed_projection_blocks = bool(suppressed_projection.get("requires_recovery"))
    status = _status(report, live_receipt=live_receipt, live_receipt_checked=live_receipt_checked)
    reason = _reason(report, live_receipt=live_receipt, live_receipt_checked=live_receipt_checked)
    if safe_work_audit_blocks:
        status = "blocked_local_runtime"
        reason = _safe_work_audit_blocking_reason(safe_work_audit)
    elif current_artifact_filter_blocks:
        status = "blocked_local_runtime"
        reason = str(current_artifact_filter.get("blocking_reason") or "filtered_current_artifact").strip()
    elif suppressed_projection_blocks and status in {"ready_local_runtime", "ready_with_live_receipt", "ready_with_recovery_action"}:
        status = "ready_with_recovery_action"
        reason = str(suppressed_projection.get("blocking_reason") or "suppressed_safe_work_projection").strip()
    approval_capture_surface = _approval_capture_surface(report=report, artifact_probe=artifact_probe)
    if (
        allow_live_route_probe
        and live_receipt_path is None
        and not safe_work_audit_blocks
        and not current_artifact_filter_blocks
        and _approval_capture_surface_ready(approval_capture_surface)
        and int(approval_capture_surface.get("current_packet_live_pending_count") or 0) > 0
        and live_receipt_checked
        and bool(live_receipt.get("ok"))
    ):
        approval_capture_probe = _approval_capture_probe(principal_id, timeout_seconds=live_probe_timeout_seconds)
    approval_capture = _approval_capture_summary(approval_capture_probe)
    if _approval_capture_probe_blocks_followthrough(
        status=status,
        live_receipt=live_receipt,
        live_receipt_checked=live_receipt_checked,
        approval_capture_surface=approval_capture_surface,
        approval_capture=approval_capture,
    ):
        reason = str(approval_capture.get("blocking_reason") or "approval_capture_not_ready").strip()
    if safe_work_audit_blocks or current_artifact_filter_blocks or suppressed_projection_blocks:
        next_action = "repair_proactive_safe_work_audit"
    else:
        next_action = _operator_followthrough_next_action(
            status,
            report,
            live_receipt=live_receipt,
            live_receipt_checked=live_receipt_checked,
            approval_capture_surface=approval_capture_surface,
            approval_capture=approval_capture,
        )
    next_action_surface = _next_action_surface_fields(next_action)
    if safe_work_audit_blocks:
        summary = (
            "Proactive OODA has a current safe-work artifact, but the packet-quality auditor did not pass it "
            "for operator follow-through."
        )
    elif current_artifact_filter_blocks:
        summary = "Proactive OODA filtered the current packet before follow-through because it is not decision-ready."
    elif suppressed_projection_blocks:
        summary = (
            "Proactive OODA runtime is healthy, but the latest quiet run suppressed "
            f"{int(suppressed_projection.get('suppressed_item_count') or 0)} non-deliverable safe-work "
            "item(s) from user and Teable packet projection."
        )
    else:
        summary = _summary(
            status,
            report,
            live_receipt=live_receipt,
            live_receipt_checked=live_receipt_checked,
            approval_capture_surface=approval_capture_surface,
            approval_capture=approval_capture,
        )
    operator_delivery_guard = _operator_delivery_guard(
        status,
        report,
        live_receipt=live_receipt,
        live_receipt_checked=live_receipt_checked,
        approval_capture_surface=approval_capture_surface,
        approval_capture=approval_capture,
    )
    runtime_actionable_count = int(report.get("actionable_count") or 0)
    receipt = {
        "contract_name": CONTRACT_NAME,
        "generated_at": generated_at or _utc_now(),
        "generated_by": "scripts/materialize_proactive_ooda_operator_status.py",
        "source_git_head": _git_head(ROOT),
        "head_semantics": "source_state",
        "source_state_fingerprint": _source_fingerprint(ROOT),
        "source_state_fingerprint_semantics": "worktree_source_files_sha256_excluding_generated_only_paths",
        "output_path": output_path.relative_to(ROOT).as_posix() if output_path.is_absolute() and output_path.is_relative_to(ROOT) else output_path.as_posix(),
        "status": status,
        "reason": reason,
        "summary": summary,
        "next_action": next_action,
        **next_action_surface,
        "operator_action_state": (
            "recovery_required"
            if safe_work_audit_blocks or current_artifact_filter_blocks or suppressed_projection_blocks
            else _operator_followthrough_action_state(
                status,
                report=report,
                live_receipt=live_receipt,
                live_receipt_checked=live_receipt_checked,
                approval_capture_surface=approval_capture_surface,
                approval_capture=approval_capture,
            )
        ),
        "route_probe_source": str(route_probe.get("source") or "host_verifier").strip() or "host_verifier",
        "route_probe_runtime_service": str(route_probe.get("runtime_service") or "").strip(),
        "route_probe_observed_at": str(route_probe.get("observed_at") or "").strip(),
        "claim_limit": "operator_runtime_posture_not_real_daily_acceptance",
        "goal_completion_claim_allowed": False,
        "live_delivery_claim_allowed": False,
        "route_ready_claim_allowed": bool(_normalized_delivery_route(report).get("ready")),
        "delivery_route_ready": bool(_normalized_delivery_route(report).get("ready")),
        "delivery_route_error": str(_normalized_delivery_route(report).get("route_error") or "").strip(),
        "delivery_recovery_hint": str(_normalized_delivery_route(report).get("recovery_hint") or "").strip(),
        "delivery_next_action": str(_normalized_delivery_route(report).get("next_action") or "").strip(),
        "delivery_route": _normalized_delivery_route(report),
        "delivery_guard": operator_delivery_guard,
        "context_grounding": _normalized_context_grounding(report),
        "stage_packets": _normalized_stage_packets(report),
        "safe_work_results": _normalized_safe_work_results(report),
        "safe_work_audit": safe_work_audit,
        "current_artifact_filter": current_artifact_filter,
        "suppressed_projection": suppressed_projection,
        "receipt_observation_count": int(report.get("receipt_observation_count") or 0),
        "runtime_actionable_count": runtime_actionable_count,
        "actionable_count": _operator_actionable_count(
            report,
            status=status,
            live_receipt=live_receipt,
            live_receipt_checked=live_receipt_checked,
            approval_capture_surface=approval_capture_surface,
            approval_capture=approval_capture,
        ),
        "source_mode": str(report.get("source_mode") or "").strip(),
        "live_receipt_checked": live_receipt_checked,
        "live_receipt": dict(live_receipt or {}),
        "approval_capture_surface": approval_capture_surface,
        "approval_capture": approval_capture,
        "gmail_draft_followthrough": _gmail_draft_followthrough_summary(gmail_draft_probe),
        "source_coverage": _source_coverage_summary(source_coverage_probe),
        "remaining_external_proofs": [
            REMAINING_EXTERNAL_PROOF,
        ],
        "verifier_commands": [
            "make verify-proactive-ooda",
            "make verify-proactive-ooda-live-receipt",
            "make verify-proactive-ooda-operator-status",
        ],
        "rules": list(RULES),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def parse_args() -> argparse.Namespace:
    if any(flag in os.sys.argv[1:] for flag in ("--help", "-h")):
        print(
            "Usage:\n"
            "  python scripts/materialize_proactive_ooda_operator_status.py [options]\n\n"
            "Materialize the proactive OODA operator-status receipt."
        )
        raise SystemExit(0)
    parser = argparse.ArgumentParser(description="Materialize the proactive OODA operator-status receipt.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--receipt-path", default="")
    parser.add_argument("--principal-id", default=proactive_verifier._default_principal_id())
    parser.add_argument(
        "--armed-send",
        dest="armed_send",
        action=argparse.BooleanOptionalAction,
        default=_env_truthy("EA_PROACTIVE_OODA_ARMED_SEND", default=False),
    )
    parser.add_argument("--skip-observation-source", dest="skip_observation_source", action="store_true", default=_env_truthy("EA_PROACTIVE_OODA_OPERATOR_SKIP_OBSERVATION_SOURCE", default=True))
    parser.add_argument("--no-skip-observation-source", dest="skip_observation_source", action="store_false")
    parser.add_argument("--skip-workspace-source", dest="skip_workspace_source", action="store_true", default=_env_truthy("EA_PROACTIVE_OODA_OPERATOR_SKIP_WORKSPACE_SOURCE", default=False))
    parser.add_argument("--no-skip-workspace-source", dest="skip_workspace_source", action="store_false")
    parser.add_argument(
        "--skip-gmail-draft-followthrough-probe",
        action="store_true",
        default=_env_truthy("EA_PROACTIVE_OODA_OPERATOR_SKIP_GMAIL_DRAFT_PROBE", default=False),
    )
    parser.add_argument(
        "--skip-source-coverage-probe",
        action="store_true",
        default=_env_truthy("EA_PROACTIVE_OODA_OPERATOR_SKIP_SOURCE_COVERAGE_PROBE", default=False),
    )
    parser.add_argument("--pretty", action="store_true")
    parser.add_argument("--require-ready", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report_args = _default_report_args()
    report_args.principal_id = args.principal_id
    report_args.armed_send = bool(args.armed_send)
    report_args.skip_observation_source = bool(args.skip_observation_source)
    report_args.skip_workspace_source = bool(args.skip_workspace_source)
    live_receipt_path = Path(args.receipt_path) if str(args.receipt_path or "").strip() else None
    output_path = args.output if args.output.is_absolute() else ROOT / args.output
    receipt = build_proactive_ooda_operator_status(
        output_path=output_path,
        generated_at=args.generated_at or None,
        report_args=report_args,
        live_receipt_path=live_receipt_path,
        skip_gmail_draft_followthrough_probe=bool(args.skip_gmail_draft_followthrough_probe),
        skip_source_coverage_probe=bool(args.skip_source_coverage_probe),
    )
    if args.pretty:
        print(json.dumps(receipt, indent=2, sort_keys=True))
    else:
        print(output_path)
    if args.require_ready and not str(receipt.get("status") or "").startswith("ready"):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
