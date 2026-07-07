#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from contextlib import contextmanager
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
from app.services.proactive_ooda_live_ops_bridge import resolve_proactive_ooda_capture_bundle
from app.services.proactive_ooda_operator_actions import proactive_next_action_surface
from app.services.proactive_ooda_telegram_policy import approval_request_needs_telegram_user_action
from app.services.proactive_ooda_safe_work import safe_work_decision_materiality_issue
from app.services.proactive_ooda_runtime_artifacts import load_runtime_artifact_bundle


DEFAULT_OUTPUT = ROOT / ".codex-studio" / "published" / "ea_proactive_ooda_operator_status.generated.json"
CONTRACT_NAME = "ea.proactive_ooda_operator_status.v1"
GOOGLE_WORKSPACE_REAUTH_USER_ACTION_ERROR_CODES = {
    "disconnected_by_operator",
    "google_oauth_access_denied",
    "google_oauth_access_token_missing",
    "google_oauth_account_mismatch",
    "google_oauth_binding_not_found",
    "google_oauth_invalid_grant",
    "google_oauth_refresh_failed",
    "google_oauth_unauthorized_client",
}
GOOGLE_WORKSPACE_REAUTH_USER_ACTIONS = {
    "reauthorize_google_workspace_binding",
}

RULES = [
    "This receipt proves proactive OODA route, guard, and packet-runtime posture only; it does not prove a human accepted the packet.",
    "Delivery recovery hints may be mirrored here and in Teable, but they remain operator aids rather than canonical queue truth.",
    "A live sent receipt can prove one routed delivery happened, but it does not by itself prove ordinary-use usefulness or approval correctness.",
    "Gold-production claims still require accepted proactive packets, routed delivery proof, approved-source or transcript signal evidence, live browse evidence, an auditor-passed chosen candidate, staged reversible artifacts, mirrored Teable current/stale delivery and decision facts, explicit approval outcome evidence, and consent-gated irreversible actions.",
]
REMAINING_EXTERNAL_PROOF = (
    "real proactive OODA packet accepted with routed delivery, approved-source or transcript signal, live browse evidence, auditor-passed chosen candidate, staged reversible artifact, mirrored Teable delivery, current-packet, stale-approval, and decision facts, and explicit approval outcome"
)
DEFAULT_PROACTIVE_OODA_RUNTIME_CONTAINER = str(
    os.getenv("EA_PROACTIVE_OODA_RUNTIME_CONTAINER")
    or ea_live_ops.DEFAULT_PROACTIVE_OODA_RUNTIME_SERVICE
    or "ea-proactive-ooda"
).strip() or "ea-proactive-ooda"
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
    "flat_search_disabled_property_scout",
    "flat_search_disabled",
}
NON_MATERIAL_SUPPRESSED_PROJECTION_REASONS = {
    "packet_projection_suppressed",
    "safe_work_audit_review",
    "flat_search_disabled_property_scout",
    "flat_search_disabled",
}
CONFIGURED_SOURCE_EXCLUSION_REASONS = {
    "flat_search_disabled_property_scout",
    "flat_search_disabled",
}
ASSISTANT_GRADE_BLOCKING_WORK_TYPES = {
    "record_internal_action",
    "internal_action",
    "operator_action",
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
        receipt_path=str(os.getenv("EA_PROACTIVE_OODA_RECEIPT_PATH") or "").strip(),
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
            "probe_ok": False,
            "status": "not_checked",
            "source": "",
            "runtime_service": "",
            "observed_at": "",
            "blocking_reason": "",
            "next_action": "",
            "next_action_href": "",
            "next_action_label": "",
            "next_action_method": "",
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
        "probe_ok": bool(probe.get("probe_ok")),
        "status": str(probe.get("status") or "").strip() or "unknown",
        "source": str(probe.get("source") or "").strip(),
        "runtime_service": str(probe.get("runtime_service") or "").strip(),
        "observed_at": str(probe.get("observed_at") or "").strip(),
        "blocking_reason": str(probe.get("blocking_reason") or "").strip(),
        "next_action": str(probe.get("next_action") or "").strip(),
        "next_action_href": str(probe.get("next_action_href") or "").strip(),
        "next_action_label": str(probe.get("next_action_label") or "").strip(),
        "next_action_method": str(probe.get("next_action_method") or "").strip(),
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


def _source_coverage_missing_lane_keys(source_coverage: Mapping[str, Any] | None) -> list[str]:
    return [
        str(item).strip()
        for item in list(dict(source_coverage or {}).get("missing_lane_keys") or [])
        if str(item).strip()
    ]


def _source_coverage_is_ready(source_coverage: Mapping[str, Any] | None) -> bool:
    normalized = dict(source_coverage or {})
    status = str(normalized.get("status") or "").strip()
    if not bool(normalized.get("checked")):
        return False
    if status not in {"ready", "pass", "fully_ready"}:
        return False
    if _source_coverage_missing_lane_keys(normalized):
        return False
    if str(normalized.get("blocking_reason") or "").strip():
        return False
    return True


def _source_coverage_requires_recovery(source_coverage: Mapping[str, Any] | None) -> bool:
    normalized = dict(source_coverage or {})
    if _source_coverage_missing_lane_keys(normalized):
        return True
    if str(normalized.get("blocking_reason") or "").strip():
        return True
    status = str(normalized.get("status") or "").strip()
    checked = bool(normalized.get("checked"))
    if not checked:
        return status not in {"", "not_checked"}
    if _source_coverage_is_ready(normalized):
        return False
    return status not in {"", "not_checked"}


def _source_coverage_probe_pending(source_coverage: Mapping[str, Any] | None) -> bool:
    normalized = dict(source_coverage or {})
    if bool(normalized.get("checked")):
        return False
    status = str(normalized.get("status") or "").strip()
    if status not in {"", "not_checked"}:
        return False
    return bool(
        _source_coverage_missing_lane_keys(normalized)
        or list(normalized.get("lanes") or [])
        or int(normalized.get("lane_count") or 0) > 0
    )


def _source_coverage_recovery_reason(source_coverage: Mapping[str, Any] | None) -> str:
    normalized = dict(source_coverage or {})
    blocking_reason = str(normalized.get("blocking_reason") or "").strip()
    if blocking_reason:
        return f"source_coverage_{blocking_reason}"
    status = str(normalized.get("status") or "").strip() or "recovery_required"
    missing_lane_keys = _source_coverage_missing_lane_keys(normalized)
    if missing_lane_keys:
        return f"source_coverage_{status}:{missing_lane_keys[0]}"
    return f"source_coverage_{status}"


def _source_coverage_recovery_next_action(source_coverage: Mapping[str, Any] | None) -> str:
    normalized = dict(source_coverage or {})
    next_action = str(normalized.get("next_action") or "").strip()
    if next_action:
        return next_action
    for lane in list(normalized.get("lanes") or []):
        lane_payload = dict(lane or {}) if isinstance(lane, Mapping) else {}
        lane_next_action = str(lane_payload.get("next_action") or "").strip()
        if lane_next_action and not bool(lane_payload.get("observed")):
            return lane_next_action
    return "probe_proactive_source_coverage"


def _source_coverage_recovery_surface_fields(source_coverage: Mapping[str, Any] | None, next_action: str) -> dict[str, str]:
    normalized = dict(source_coverage or {})
    source_next_action = str(normalized.get("next_action") or "").strip()
    if source_next_action == str(next_action or "").strip():
        href = str(normalized.get("next_action_href") or "").strip()
        label = str(normalized.get("next_action_label") or "").strip()
        method = str(normalized.get("next_action_method") or "").strip().lower()
        if href and label and method:
            return {
                "next_action_href": href,
                "next_action_label": label,
                "next_action_method": method,
            }
    return _next_action_surface_fields(next_action)


def _source_coverage_recovery_summary(source_coverage: Mapping[str, Any] | None) -> str:
    normalized = dict(source_coverage or {})
    blocking_reason = str(normalized.get("blocking_reason") or "").strip()
    if blocking_reason:
        return (
            "Proactive OODA route and packet runtime are available, but source coverage probing needs recovery "
            f"before gold-ready posture is trustworthy ({blocking_reason})."
        )
    missing_lane_keys = _source_coverage_missing_lane_keys(normalized)
    if missing_lane_keys:
        lane_preview = ", ".join(missing_lane_keys[:3])
        extra_count = max(len(missing_lane_keys) - 3, 0)
        suffix = f" (+{extra_count} more)" if extra_count else ""
        return (
            "Proactive OODA route and packet runtime are available, but approved source coverage still has "
            f"{len(missing_lane_keys)} missing lane(s): {lane_preview}{suffix}. Recover that signal ingest before "
            "treating the loop as gold-ready."
        )
    status = str(normalized.get("status") or "").strip() or "unknown"
    return (
        "Proactive OODA route and packet runtime are available, but source coverage posture still needs recovery "
        f"before gold-ready claims are trustworthy ({status})."
    )


def _provider_cost_pressure_probe(principal_id: str, *, timeout_seconds: float | None = None) -> dict[str, Any]:
    try:
        return ea_live_ops.probe_provider_cost_pressure(
            window="24h",
            principal_id=principal_id,
            timeout_seconds=float(timeout_seconds or _live_probe_timeout_seconds()),
            output_format="json",
        )
    except Exception as exc:
        return {
            "probe_ok": False,
            "status": "probe_failed",
            "observed_at": _utc_now(),
            "source": "runtime_container_exec:provider_ledger_cache",
            "window": "24h",
            "blocking_reason": type(exc).__name__,
            "privacy": {
                "raw_prompt_or_response_text_exposed": False,
                "raw_provider_secret_exposed": False,
                "raw_google_cloud_billing_account_exposed": False,
                "raw_provider_slots_exposed": False,
            },
        }


def _provider_cost_pressure_summary(probe: Mapping[str, Any]) -> dict[str, Any]:
    if not probe:
        return {
            "checked": False,
            "probe_ok": False,
            "status": "not_checked",
            "source": "",
            "observed_at": "",
            "window": "",
            "blocking_reason": "",
            "next_action": "",
            "primary_background_provider": "",
            "provider_order": [],
            "fast_provider_order": [],
            "cheap_provider_order": [],
            "groundwork_provider_order": [],
            "hard_provider_order": [],
            "cost_sensitive_lanes": [],
            "onemin_preferred_when_speed_is_not_critical": False,
            "onemin_preferred_whenever_usable": False,
            "onemin_usable": False,
            "onemin_probe_pending": False,
            "onemin_ready_slots": 0,
            "onemin_configured_slots": 0,
            "onemin_unknown_slots": 0,
            "gemini_provider_key": "gemini_vortex",
            "gemini_token_tracking": _empty_gemini_token_tracking(),
            "routing_decision": "",
            "requires_recovery": False,
            "privacy": _provider_cost_privacy({}),
        }
    privacy = dict(probe.get("privacy") or {})
    gemini = dict(probe.get("gemini_token_tracking") or {})
    status = str(probe.get("status") or "").strip() or "unknown"
    blocking_reason = str(probe.get("blocking_reason") or "").strip()
    requires_recovery = _provider_cost_pressure_requires_recovery_status(status=status, blocking_reason=blocking_reason)
    return {
        "checked": True,
        "probe_ok": bool(probe.get("probe_ok")),
        "status": status,
        "source": str(probe.get("source") or "").strip(),
        "observed_at": str(probe.get("observed_at") or "").strip(),
        "window": str(probe.get("window") or "").strip(),
        "blocking_reason": blocking_reason,
        "next_action": "repair_provider_cost_routing" if requires_recovery else "",
        "primary_background_provider": str(probe.get("primary_background_provider") or "").strip(),
        "provider_order": _string_list(probe.get("provider_order"), limit=8),
        "fast_provider_order": _string_list(probe.get("fast_provider_order"), limit=8),
        "cheap_provider_order": _string_list(probe.get("cheap_provider_order"), limit=8),
        "groundwork_provider_order": _string_list(probe.get("groundwork_provider_order"), limit=8),
        "hard_provider_order": _string_list(probe.get("hard_provider_order"), limit=8),
        "cost_sensitive_lanes": _string_list(probe.get("cost_sensitive_lanes"), limit=12),
        "onemin_preferred_when_speed_is_not_critical": bool(probe.get("onemin_preferred_when_speed_is_not_critical")),
        "onemin_preferred_whenever_usable": bool(probe.get("onemin_preferred_whenever_usable")),
        "onemin_usable": bool(probe.get("onemin_usable")),
        "onemin_probe_pending": bool(probe.get("onemin_probe_pending")),
        "onemin_ready_slots": int(probe.get("onemin_ready_slots") or 0),
        "onemin_configured_slots": int(probe.get("onemin_configured_slots") or 0),
        "onemin_unknown_slots": int(probe.get("onemin_unknown_slots") or 0),
        "onemin_remaining_credits": _safe_float_or_none(probe.get("onemin_remaining_credits")),
        "onemin_remaining_percent_total": _safe_float_or_none(probe.get("onemin_remaining_percent_total")),
        "onemin_next_topup_at": str(probe.get("onemin_next_topup_at") or "").strip(),
        "onemin_burn_basis": str(probe.get("onemin_burn_basis") or "").strip(),
        "gemini_provider_key": str(probe.get("gemini_provider_key") or "gemini_vortex").strip(),
        "gemini_token_tracking": _provider_cost_gemini_tracking(gemini),
        "routing_decision": str(probe.get("routing_decision") or "").strip(),
        "requires_recovery": requires_recovery,
        "privacy": _provider_cost_privacy(privacy),
    }


def _empty_gemini_token_tracking() -> dict[str, Any]:
    return {
        "billing_truth_boundary": "",
        "selected_window": {},
        "24h": {},
        "soft_cap_percent_24h": None,
        "background_cost_gate": "",
        "explicit_gemini_requests_allowed": False,
    }


def _provider_cost_gemini_tracking(gemini: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "billing_truth_boundary": str(gemini.get("billing_truth_boundary") or "").strip(),
        "selected_window": _token_window_summary(gemini.get("selected_window")),
        "24h": _token_window_summary(gemini.get("24h")),
        "soft_cap_percent_24h": _safe_float_or_none(gemini.get("soft_cap_percent_24h")),
        "background_cost_gate": str(gemini.get("background_cost_gate") or "").strip(),
        "explicit_gemini_requests_allowed": bool(gemini.get("explicit_gemini_requests_allowed")),
    }


def _token_window_summary(value: Any) -> dict[str, Any]:
    window = dict(value or {}) if isinstance(value, Mapping) else {}
    return {
        "window_seconds": _safe_float_or_none(window.get("window_seconds")),
        "request_count": int(window.get("request_count") or 0),
        "tokens_in": int(window.get("tokens_in") or 0),
        "tokens_out": int(window.get("tokens_out") or 0),
        "total_tokens": int(window.get("total_tokens") or 0),
        "soft_cap_tokens": int(window.get("soft_cap_tokens") or 0),
        "state": str(window.get("state") or "").strip(),
    }


def _provider_cost_privacy(value: Mapping[str, Any]) -> dict[str, bool]:
    return {
        "raw_prompt_or_response_text_exposed": bool(value.get("raw_prompt_or_response_text_exposed")),
        "raw_provider_secret_exposed": bool(value.get("raw_provider_secret_exposed")),
        "raw_google_cloud_billing_account_exposed": bool(value.get("raw_google_cloud_billing_account_exposed")),
        "raw_provider_slots_exposed": bool(value.get("raw_provider_slots_exposed")),
    }


def _provider_cost_pressure_requires_recovery_status(*, status: str, blocking_reason: str = "") -> bool:
    normalized = str(status or "").strip()
    if str(blocking_reason or "").strip():
        return True
    return normalized in {"probe_failed", "misconfigured", "active_cost_control_onemin_not_live_ready"}


def _provider_cost_pressure_recovery_reason(provider_cost_pressure: Mapping[str, Any] | None) -> str:
    normalized = dict(provider_cost_pressure or {})
    status = str(normalized.get("status") or "recovery_required").strip() or "recovery_required"
    blocking_reason = str(normalized.get("blocking_reason") or "").strip()
    if blocking_reason:
        return f"provider_cost_pressure_{blocking_reason}"
    return f"provider_cost_pressure_{status}"


def _provider_cost_pressure_recovery_summary(provider_cost_pressure: Mapping[str, Any] | None) -> str:
    normalized = dict(provider_cost_pressure or {})
    status = str(normalized.get("status") or "unknown").strip() or "unknown"
    primary = str(normalized.get("primary_background_provider") or "unknown").strip() or "unknown"
    return (
        "Proactive OODA route and packet runtime are available, but provider cost routing needs recovery "
        f"before background work can safely stay off Gemini/Vertex ({status}, primary={primary})."
    )


def _safe_float_or_none(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _string_list(value: Any, *, limit: int) -> list[str]:
    return [
        str(item).strip()
        for item in list(value or [])
        if str(item).strip()
    ][: max(int(limit or 1), 1)]


def _runtime_source_health_issue_requires_user_action(issue: Mapping[str, Any]) -> bool:
    if bool(issue.get("user_action_required")):
        return True
    source_key = str(issue.get("source_key") or "").strip()
    source_type = str(issue.get("source_type") or "").strip()
    error_code = str(issue.get("error_code") or "").strip()
    next_action = str(issue.get("next_action") or "").strip()
    if next_action in GOOGLE_WORKSPACE_REAUTH_USER_ACTIONS:
        return True
    if "google_workspace" in {source_key, source_type} and error_code in GOOGLE_WORKSPACE_REAUTH_USER_ACTION_ERROR_CODES:
        return True
    return False


def _runtime_source_health_summary(artifact_probe: Mapping[str, Any] | None) -> dict[str, Any]:
    run_receipt = dict(dict(artifact_probe or {}).get("run_receipt") or {})
    source_health = dict(run_receipt.get("source_health") or {})
    issues: list[dict[str, Any]] = []
    for issue in list(source_health.get("issues") or []):
        if not isinstance(issue, Mapping):
            continue
        issue_user_action_required = _runtime_source_health_issue_requires_user_action(issue)
        normalized = {
            "source_key": str(issue.get("source_key") or "unknown").strip()[:80] or "unknown",
            "source_type": str(issue.get("source_type") or issue.get("source_key") or "unknown").strip()[:80]
            or "unknown",
            "status": str(issue.get("status") or "failed").strip()[:80] or "failed",
            "error_code": str(issue.get("error_code") or "source_error").strip()[:160] or "source_error",
            "error_ref_hash": str(issue.get("error_ref_hash") or "").strip()[:24],
            "operator_action_required": bool(issue.get("operator_action_required", True)),
            "user_action_required": issue_user_action_required,
            "next_action": str(issue.get("next_action") or "repair_proactive_signal_source").strip()[:120]
            or "repair_proactive_signal_source",
            "raw_source_ref_exposed": False,
            "raw_payload_exposed": False,
            "raw_credential_exposed": False,
        }
        issues.append(normalized)
    operator_action_required = any(bool(issue.get("operator_action_required")) for issue in issues)
    user_action_required = any(bool(issue.get("user_action_required")) for issue in issues)
    return {
        "present": bool(issues),
        "status": str(source_health.get("status") or ("recovery_required" if issues else "clear")).strip()
        or ("recovery_required" if issues else "clear"),
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


def _runtime_source_health_requires_recovery(source_health: Mapping[str, Any] | None) -> bool:
    normalized = dict(source_health or {})
    if not bool(normalized.get("present")):
        return False
    if bool(normalized.get("operator_action_required")) or bool(normalized.get("user_action_required")):
        return True
    return str(normalized.get("status") or "").strip() not in {"", "clear", "healthy", "ready"}


def _runtime_source_health_recovery_reason(source_health: Mapping[str, Any] | None) -> str:
    normalized = dict(source_health or {})
    for issue in list(normalized.get("issues") or []):
        issue_payload = dict(issue or {}) if isinstance(issue, Mapping) else {}
        source_key = str(issue_payload.get("source_key") or "unknown").strip() or "unknown"
        error_code = str(issue_payload.get("error_code") or "source_error").strip() or "source_error"
        return f"source_health_{source_key}:{error_code}"
    return "source_health_recovery_required"


def _runtime_source_health_recovery_next_action(source_health: Mapping[str, Any] | None) -> str:
    normalized = dict(source_health or {})
    for issue in list(normalized.get("issues") or []):
        issue_payload = dict(issue or {}) if isinstance(issue, Mapping) else {}
        next_action = str(issue_payload.get("next_action") or "").strip()
        if next_action:
            return next_action
    return "repair_proactive_signal_source"


def _source_health_recovery_candidate_status(status: str, reason: str) -> bool:
    normalized_status = str(status or "").strip()
    if normalized_status in {"ready_local_runtime", "ready_with_live_receipt"}:
        return True
    return bool(
        normalized_status == "ready_with_recovery_action"
        and str(reason or "").strip().startswith("followthrough_")
    )


def _runtime_source_health_recovery_summary(source_health: Mapping[str, Any] | None) -> str:
    normalized = dict(source_health or {})
    issues = [dict(issue or {}) for issue in list(normalized.get("issues") or []) if isinstance(issue, Mapping)]
    if not issues:
        return "Proactive OODA route and packet runtime are available, but source-health posture needs review."
    preview = ", ".join(str(issue.get("source_key") or "unknown").strip() or "unknown" for issue in issues[:3])
    extra_count = max(len(issues) - 3, 0)
    suffix = f" (+{extra_count} more)" if extra_count else ""
    return (
        "Proactive OODA route and packet runtime are available, but "
        f"{len(issues)} signal source health issue(s) need operator recovery: {preview}{suffix}."
    )


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


def _live_receipt_requires_runtime_recovery(live_receipt: Mapping[str, Any]) -> bool:
    if bool(live_receipt.get("ok")):
        return False
    errors = [str(item).strip() for item in list(live_receipt.get("errors") or []) if str(item).strip()]
    return any(item.startswith("followthrough_") for item in errors)


def _next_action_surface_fields(action: str) -> dict[str, str]:
    surface = proactive_next_action_surface(action)
    return {
        "next_action_href": str(surface.get("href") or "").strip(),
        "next_action_label": str(surface.get("label") or "").strip(),
        "next_action_method": str(surface.get("method") or "").strip(),
    }


def _approval_callback_hygiene(
    *,
    callback_noncurrent_pending_count: int,
    callback_stale_pending_count: int,
    current_packet_callback_stale_pending_count: int,
    current_packet_duplicate_live_pending_count: int,
) -> tuple[bool, str, str]:
    if int(current_packet_duplicate_live_pending_count or 0) > 0:
        return False, "approval_callback_duplicate_live_pending", "cleanup_proactive_approval_callbacks"
    if int(current_packet_callback_stale_pending_count or 0) > 0:
        return False, "approval_callback_current_packet_stale_pending", "cleanup_proactive_approval_callbacks"
    if int(callback_noncurrent_pending_count or 0) > 0:
        return False, "approval_callback_noncurrent_pending", "cleanup_proactive_approval_callbacks"
    if int(callback_stale_pending_count or 0) > 0:
        return False, "approval_callback_stale_pending", "cleanup_proactive_approval_callbacks"
    return True, "", ""


def _approval_capture_surface_ready(surface: Mapping[str, Any] | None) -> bool:
    return bool(dict(surface or {}).get("ready"))


def _approval_capture_checked(probe: Mapping[str, Any] | None) -> bool:
    return bool(dict(probe or {}).get("checked"))


def _approval_capture_probe_ready(probe: Mapping[str, Any] | None) -> bool:
    normalized = dict(probe or {})
    if not bool(normalized.get("checked")):
        return True
    return bool(normalized.get("ready"))


def _approval_capture_surface_authoritative_fallback(
    surface: Mapping[str, Any] | None,
    approval_capture: Mapping[str, Any] | None,
) -> bool:
    normalized_surface = dict(surface or {})
    normalized_probe = dict(approval_capture or {})
    if not bool(normalized_surface.get("ready")):
        return False
    if not bool(normalized_surface.get("telegram_approval_surface_ready")):
        return False
    if not bool(normalized_surface.get("callback_hygiene_ready", True)):
        return False
    if int(normalized_surface.get("current_packet_live_pending_count") or 0) != 1:
        return False
    if str(normalized_surface.get("current_packet_callback_latest_status") or "").strip() != "pending":
        return False
    if int(normalized_surface.get("current_packet_callback_record_count") or 0) <= 0:
        return False
    if not bool(normalized_probe.get("checked")) or bool(normalized_probe.get("ready")):
        return False
    if str(normalized_probe.get("blocking_reason") or "").strip() != "current_packet_approval_callback_missing":
        return False
    if bool(normalized_probe.get("current_packet_refs_present")) is not True:
        return False
    if int(normalized_probe.get("current_packet_callback_record_count") or 0) <= 0:
        return False
    if bool(normalized_probe.get("callback_principal_hash_present")) is not True:
        return False
    if bool(normalized_probe.get("principal_match_ready")) is not True:
        return False
    if bool(normalized_probe.get("telegram_binding_ready")) is not True:
        return False
    if bool(normalized_probe.get("telegram_chat_ref_present")) is not True:
        return False
    if bool(normalized_probe.get("telegram_bot_token_present")) is not True:
        return False
    return True


def _reconcile_approval_capture_surface_authority(
    approval_capture: Mapping[str, Any] | None,
    approval_capture_surface: Mapping[str, Any] | None,
) -> dict[str, Any]:
    normalized_probe = dict(approval_capture or {})
    normalized_surface = dict(approval_capture_surface or {})
    if not _approval_capture_surface_authoritative_fallback(normalized_surface, normalized_probe):
        return normalized_probe
    reconciled = dict(normalized_probe)
    reconciled.update(
        {
            "ready": True,
            "status": "ready",
            "blocking_reason": "",
            "next_action": "tap_proactive_telegram_approval_button_or_record_proactive_ooda_approval_outcome",
            "current_packet_callback_record_count": max(
                int(reconciled.get("current_packet_callback_record_count") or 0),
                int(normalized_surface.get("current_packet_callback_record_count") or 0),
            ),
            "current_packet_live_pending_count": int(normalized_surface.get("current_packet_live_pending_count") or 0),
            "current_packet_callback_latest_status": str(
                normalized_surface.get("current_packet_callback_latest_status") or reconciled.get("current_packet_callback_latest_status") or ""
            ).strip(),
            "current_packet_callback_latest_expired": bool(normalized_surface.get("current_packet_callback_latest_expired")),
            "current_packet_callback_latest_age_seconds": int(
                normalized_surface.get("current_packet_callback_latest_age_seconds")
                or reconciled.get("current_packet_callback_latest_age_seconds")
                or 0
            ),
            "current_packet_callback_latest_seconds_until_expiry": int(
                normalized_surface.get("current_packet_callback_latest_seconds_until_expiry")
                or reconciled.get("current_packet_callback_latest_seconds_until_expiry")
                or 0
            ),
            "surface_authoritative_fallback_used": True,
            "surface_authoritative_fallback_reason": "current_packet_live_pending_surface_preferred",
        }
    )
    return reconciled


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


def _soft_followthrough_recovery_override(
    *,
    status: str,
    report: Mapping[str, Any],
    source_coverage: Mapping[str, Any] | None,
    live_receipt: Mapping[str, Any],
    live_receipt_checked: bool,
    approval_capture_surface: Mapping[str, Any] | None,
    approval_capture: Mapping[str, Any] | None,
    safe_work_audit_blocks: bool,
    current_artifact_filter_blocks: bool,
    assistant_grade_recovery_active: bool,
    suppressed_projection_blocks: bool,
    browser_handoff_recovery_active: bool,
    source_health_recovery_active: bool,
    provider_cost_pressure_recovery_active: bool,
    approval_callback_hygiene_blocks: bool,
) -> bool:
    if status != "ready_with_recovery_action":
        return False
    if (
        safe_work_audit_blocks
        or current_artifact_filter_blocks
        or assistant_grade_recovery_active
        or suppressed_projection_blocks
        or browser_handoff_recovery_active
        or provider_cost_pressure_recovery_active
        or approval_callback_hygiene_blocks
    ):
        return False
    if not live_receipt_checked or not bool(live_receipt.get("ok")):
        return False
    if not _approval_capture_surface_ready(approval_capture_surface):
        return False
    if not _approval_capture_probe_ready(approval_capture):
        return False
    return _has_only_workspace_health_errors(report) or _source_coverage_probe_pending(source_coverage)


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


def _configured_live_receipt_path() -> Path | None:
    explicit = str(
        os.getenv("EA_PROACTIVE_OODA_OPERATOR_RECEIPT_PATH")
        or os.getenv("EA_PROACTIVE_OODA_LIVE_RECEIPT_PATH")
        or os.getenv("EA_PROACTIVE_OODA_RECEIPT_PATH")
        or ""
    ).strip()
    return Path(explicit) if explicit else None


def _runtime_container_mounts(container_name: str) -> list[dict[str, Any]]:
    normalized = str(container_name or "").strip()
    if not normalized:
        return []
    try:
        completed = subprocess.run(
            ["docker", "inspect", normalized, "--format", "{{json .Mounts}}"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=15.0,
        )
    except Exception:
        return []
    if int(completed.returncode or 0) != 0:
        return []
    try:
        payload = json.loads(str(completed.stdout or "[]"))
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    return [dict(row) for row in payload if isinstance(row, Mapping)]


def _host_path_for_runtime_container_path(
    container_path: str | Path,
    *,
    container_name: str = DEFAULT_PROACTIVE_OODA_RUNTIME_CONTAINER,
) -> Path | None:
    raw_path = str(container_path or "").strip()
    if not raw_path:
        return None
    candidate = Path(raw_path)
    if candidate.exists():
        return candidate
    best_match: tuple[str, str] | None = None
    for row in _runtime_container_mounts(container_name):
        destination = str(row.get("Destination") or "").strip().rstrip("/")
        source = str(row.get("Source") or "").strip().rstrip("/")
        if not destination or not source:
            continue
        if raw_path == destination or raw_path.startswith(f"{destination}/"):
            if best_match is None or len(destination) > len(best_match[0]):
                best_match = (destination, source)
    if best_match is None:
        return None
    destination, source = best_match
    suffix = raw_path[len(destination):].lstrip("/")
    return Path(source) / suffix if suffix else Path(source)


def _route_live_receipt_host_path(route_probe: Mapping[str, Any] | None) -> Path | None:
    live_receipt = dict(dict(route_probe or {}).get("live_receipt") or {})
    raw_path = str(live_receipt.get("receipt_path") or "").strip()
    if not raw_path:
        return None
    return _host_path_for_runtime_container_path(raw_path)


@contextmanager
def _host_runtime_proactive_probe_override(enabled: bool):
    if not enabled or _env_truthy("EA_LIVE_OPS_FORCE_DOCKER_COMPOSE_EXEC", default=False):
        yield
        return
    key = "EA_LIVE_OPS_PREFER_HOST_RUNTIME_PROACTIVE_PROBE"
    previous = os.getenv(key)
    os.environ[key] = "1"
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = previous


def _live_probe_bundle_score(
    *,
    route_probe: Mapping[str, Any],
    artifact_probe: Mapping[str, Any],
    gmail_draft_probe: Mapping[str, Any],
    source_coverage_probe: Mapping[str, Any],
    provider_cost_pressure_probe: Mapping[str, Any],
) -> int:
    score = 0
    if bool(route_probe.get("probe_ok")):
        score += 3
        if str(route_probe.get("source") or "").strip() == "host_python_exec":
            score += 1
    score += _artifact_probe_evidence_score(artifact_probe)
    if str(gmail_draft_probe.get("status") or "").strip():
        score += 1
    if bool(source_coverage_probe.get("probe_ok")) or str(source_coverage_probe.get("status") or "").strip():
        score += 2
    if bool(provider_cost_pressure_probe.get("probe_ok")) or str(provider_cost_pressure_probe.get("status") or "").strip():
        score += 1
    return score


def _artifact_probe_evidence_score(artifact_probe: Mapping[str, Any] | None) -> int:
    probe = dict(artifact_probe or {})
    if not probe:
        return 0
    score = 1
    if (
        dict(probe.get("stage_packet") or {})
        or dict(probe.get("safe_work_result") or {})
        or _path_text(probe.get("stage_packet_path"))
        or _path_text(probe.get("safe_work_result_path"))
    ):
        score += 3
    if str(probe.get("artifact_filter_reason") or "").strip():
        score += 3
    if (
        str(probe.get("approval_outcome_path") or "").strip()
        or str(probe.get("approval_callback_dir") or "").strip()
        or int(probe.get("current_packet_callback_record_count") or 0) > 0
        or int(probe.get("current_packet_callback_pending_count") or 0) > 0
        or int(probe.get("current_packet_live_pending_count") or 0) > 0
    ):
        score += 3
    if dict(probe.get("run_receipt") or {}) or _path_text(probe.get("run_receipt_path")):
        score += 1
    return score


def _route_probe_live_receipt_missing(
    *,
    route_probe: Mapping[str, Any],
) -> bool:
    if not bool(route_probe.get("probe_ok")):
        return False
    live_receipt = dict(route_probe.get("live_receipt") or {})
    if bool(live_receipt.get("ok")):
        return False
    errors = [str(item).strip() for item in list(live_receipt.get("errors") or []) if str(item).strip()]
    return "receipt_missing" in errors


def _route_probe_live_receipt_score(
    *,
    route_probe: Mapping[str, Any],
) -> int:
    if not bool(route_probe.get("probe_ok")):
        return 0
    live_receipt = dict(route_probe.get("live_receipt") or {})
    score = 1
    if bool(live_receipt.get("ok")):
        score += 4
    if bool(live_receipt.get("archived_sent_receipt_used")):
        score += 2
    if str(live_receipt.get("notification_status") or "").strip() == "sent":
        score += 1
    if str(live_receipt.get("followthrough_status") or "").strip():
        score += 1
    return score


def _should_retry_host_runtime_live_probe(
    *,
    allow_live_route_probe: bool,
    live_receipt_path: Path | None,
    report_args: argparse.Namespace,
    route_probe: Mapping[str, Any],
    artifact_probe: Mapping[str, Any],
    source_coverage_probe: Mapping[str, Any],
    provider_cost_pressure_probe: Mapping[str, Any],
    skip_source_coverage_probe: bool,
    skip_provider_cost_pressure_probe: bool,
) -> bool:
    if not allow_live_route_probe or live_receipt_path is not None:
        return False
    if _has_explicit_artifact_dirs(report_args):
        return False
    if _env_truthy("EA_LIVE_OPS_FORCE_DOCKER_COMPOSE_EXEC", default=False):
        return False
    if _env_truthy("EA_LIVE_OPS_PREFER_HOST_RUNTIME_PROACTIVE_PROBE", default=False):
        return False
    if not bool(route_probe.get("probe_ok")):
        return True
    if not artifact_probe:
        return True
    if not skip_source_coverage_probe and not source_coverage_probe:
        return True
    if not skip_provider_cost_pressure_probe and not provider_cost_pressure_probe:
        return True
    return False


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


def _path_text(value: Any) -> str:
    if isinstance(value, Path):
        return value.as_posix()
    return str(value or "").strip()


def _selected_artifact_probe(
    *,
    artifact_probe: Mapping[str, Any] | None,
    assistant_grade_probe: Mapping[str, Any] | None,
) -> dict[str, Any]:
    for candidate in (assistant_grade_probe, artifact_probe):
        probe = _mapping_value(candidate)
        if (
            _mapping_value(probe.get("stage_packet"))
            or _mapping_value(probe.get("safe_work_result"))
            or _path_text(probe.get("stage_packet_path"))
            or _path_text(probe.get("safe_work_result_path"))
        ):
            return probe
    return {}


def _reconciled_stage_packets(
    report: Mapping[str, Any],
    *,
    artifact_probe: Mapping[str, Any] | None = None,
    assistant_grade_probe: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    stage_packets = _normalized_stage_packets(report)
    selected_probe = _selected_artifact_probe(
        artifact_probe=artifact_probe,
        assistant_grade_probe=assistant_grade_probe,
    )
    selected_stage_packet = _mapping_value(selected_probe.get("stage_packet"))
    selected_stage_packet_path = _path_text(selected_probe.get("stage_packet_path"))
    if not selected_stage_packet and not selected_stage_packet_path:
        return stage_packets

    selected_bundle_source = str(
        selected_probe.get("assistant_grade_bundle_source") or "current_runtime_bundle"
    ).strip()
    selected_safe_work_order = _mapping_value(selected_stage_packet.get("safe_work_order"))
    stage_packets["selected_packet_present"] = True
    stage_packets["selected_packet_path"] = selected_stage_packet_path
    stage_packets["selected_bundle_source"] = selected_bundle_source
    stage_packets["packet_count"] = max(int(stage_packets.get("packet_count") or 0), 1)
    stage_packets["expected_packet_count"] = max(int(stage_packets.get("expected_packet_count") or 0), 1)
    if selected_safe_work_order or "safe_work_order_count" in stage_packets:
        stage_packets["safe_work_order_count"] = max(
            int(stage_packets.get("safe_work_order_count") or 0),
            1 if selected_safe_work_order else 0,
        )
    return stage_packets


def _reconciled_safe_work_results(
    report: Mapping[str, Any],
    *,
    artifact_probe: Mapping[str, Any] | None = None,
    assistant_grade_probe: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    safe_work_results = _normalized_safe_work_results(report)
    selected_probe = _selected_artifact_probe(
        artifact_probe=artifact_probe,
        assistant_grade_probe=assistant_grade_probe,
    )
    selected_safe_work_result = _mapping_value(selected_probe.get("safe_work_result"))
    selected_safe_work_result_path = _path_text(selected_probe.get("safe_work_result_path"))
    if not selected_safe_work_result and not selected_safe_work_result_path:
        return safe_work_results

    selected_bundle_source = str(
        selected_probe.get("assistant_grade_bundle_source") or "current_runtime_bundle"
    ).strip()
    schema_valid = str(selected_safe_work_result.get("schema") or "").strip() == "proactive_ooda.safe_work_result.v1"
    safe_work_results["selected_result_present"] = True
    safe_work_results["selected_result_path"] = selected_safe_work_result_path
    safe_work_results["selected_bundle_source"] = selected_bundle_source
    safe_work_results["result_count"] = max(int(safe_work_results.get("result_count") or 0), 1)
    safe_work_results["expected_result_count"] = max(int(safe_work_results.get("expected_result_count") or 0), 1)
    if schema_valid or "schema_valid_count" in safe_work_results:
        safe_work_results["schema_valid_count"] = max(
            int(safe_work_results.get("schema_valid_count") or 0),
            1 if schema_valid else 0,
        )
    return safe_work_results


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


def _normalized_browser_handoff(artifact_probe: Mapping[str, Any]) -> dict[str, Any]:
    stage_packet = dict(artifact_probe.get("stage_packet") or {})
    stage_payload = dict(dict(stage_packet.get("stage") or {}).get("payload") or {})
    safe_work_result = dict(artifact_probe.get("safe_work_result") or {})
    browser_receipt = dict(safe_work_result.get("browser_action_receipt") or {})
    handoff = dict(browser_receipt.get("handoff") or {})
    challenge = dict(handoff.get("challenge") or {})
    browser_privacy = dict(browser_receipt.get("privacy") or {})
    result_status = str(safe_work_result.get("status") or "").strip()
    required = bool(
        browser_receipt
        and browser_receipt.get("user_action_required")
        and (handoff.get("required") or result_status == "blocked_human_handoff_required")
    )
    available_channels = [
        str(item).strip()
        for item in list(challenge.get("available_channels") or [])
        if str(item).strip()
    ]
    return {
        "present": bool(browser_receipt),
        "required": required,
        "source": str(artifact_probe.get("source") or "").strip(),
        "site_host": str(browser_receipt.get("site") or stage_payload.get("site") or "").strip(),
        "blocker_code": str(handoff.get("blocker_code") or "").strip(),
        "reason": str(handoff.get("reason") or "").strip(),
        "next_action": str(handoff.get("next_action") or "").strip(),
        "resume_instruction": str(handoff.get("resume_instruction") or "").strip(),
        "staged_artifact_present": bool(browser_receipt.get("staged_artifact_present")),
        "challenge": {
            "primary_channel": str(challenge.get("primary_channel") or "").strip(),
            "available_channels": available_channels,
            "destination_hint": str(challenge.get("destination_hint") or "").strip(),
            "operator_instruction": str(challenge.get("operator_instruction") or "").strip(),
            "raw_destination_stored": bool(challenge.get("raw_destination_stored")),
        },
        "privacy": {
            "raw_credentials_stored": bool(browser_privacy.get("raw_credentials_stored")),
            "raw_cookie_or_session_stored": bool(browser_privacy.get("raw_cookie_or_session_stored")),
            "raw_browser_artifact_stored": False,
        },
    }


def _browser_handoff_requires_recovery(browser_handoff: Mapping[str, Any] | None) -> bool:
    return bool(dict(browser_handoff or {}).get("required"))


def _browser_handoff_recovery_reason(browser_handoff: Mapping[str, Any] | None) -> str:
    if not _browser_handoff_requires_recovery(browser_handoff):
        return ""
    return "browser_handoff_required"


def _browser_handoff_recovery_next_action(browser_handoff: Mapping[str, Any] | None) -> str:
    if not _browser_handoff_requires_recovery(browser_handoff):
        return ""
    return (
        str(dict(browser_handoff or {}).get("next_action") or "complete_browser_handoff_then_resume_ooda_task").strip()
        or "complete_browser_handoff_then_resume_ooda_task"
    )


def _browser_handoff_recovery_summary(browser_handoff: Mapping[str, Any] | None) -> str:
    normalized = dict(browser_handoff or {})
    site_host = str(normalized.get("site_host") or "").strip()
    base = "Proactive OODA is waiting on a live browser handoff before the current packet can resume."
    if site_host:
        base = f"Proactive OODA is waiting on a live browser handoff for {site_host} before the current packet can resume."
    challenge = dict(normalized.get("challenge") or {})
    operator_instruction = str(challenge.get("operator_instruction") or "").strip()
    resume_instruction = str(normalized.get("resume_instruction") or "").strip()
    if operator_instruction and resume_instruction and resume_instruction not in operator_instruction:
        return f"{base} {operator_instruction} {resume_instruction}".strip()
    if operator_instruction:
        return f"{base} {operator_instruction}".strip()
    if resume_instruction:
        return f"{base} {resume_instruction}".strip()
    return base


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
    if not issue_codes:
        issue_codes = [
            reason
            for reason in reasons
            if reason in NON_MATERIAL_SUPPRESSED_PROJECTION_ISSUE_CODES
        ][:12]
    quiet_no_action = (
        str(selected_receipt.get("notification_status") or "").strip() == "deferred"
        and str(selected_receipt.get("error_code") or "").strip() == "no_user_action_required"
    )
    configured_source_exclusion = bool(
        reasons
        and all(reason in CONFIGURED_SOURCE_EXCLUSION_REASONS for reason in reasons)
        and issue_codes
        and all(code in CONFIGURED_SOURCE_EXCLUSION_REASONS for code in issue_codes)
    )
    non_material_suppression = bool(
        suppressed_item_count > 0
        and issue_codes
        and all(code in NON_MATERIAL_SUPPRESSED_PROJECTION_ISSUE_CODES for code in issue_codes)
        and all(reason in NON_MATERIAL_SUPPRESSED_PROJECTION_REASONS for reason in reasons)
        and (quiet_no_action or configured_source_exclusion)
    )
    requires_recovery = suppressed_item_count > 0 and not non_material_suppression
    non_material_reason = ""
    if non_material_suppression:
        non_material_reason = (
            "configured_source_exclusion"
            if configured_source_exclusion
            else "quiet_no_decision_ready_material"
        )
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
        "suppressed_non_material_reason": non_material_reason,
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


def _assistant_grade_stage_kind_and_work_type(artifact_probe: Mapping[str, Any]) -> tuple[str, str]:
    probe = _mapping_value(artifact_probe)
    stage_packet = _mapping_value(probe.get("stage_packet"))
    stage = _mapping_value(stage_packet.get("stage"))
    stage_payload = _mapping_value(stage.get("payload"))
    safe_work_order = _mapping_value(stage_packet.get("safe_work_order"))
    safe_work_result = _mapping_value(probe.get("safe_work_result"))
    stage_kind = str(stage.get("kind") or "").strip().lower()
    work_type = str(
        stage_payload.get("work_type")
        or safe_work_order.get("work_type")
        or safe_work_result.get("work_type")
        or ""
    ).strip().lower()
    return stage_kind, work_type


def _normalized_assistant_grade_packet(artifact_probe: Mapping[str, Any]) -> dict[str, Any]:
    probe = _mapping_value(artifact_probe)
    stage_packet = _mapping_value(probe.get("stage_packet"))
    safe_work_result = _mapping_value(probe.get("safe_work_result"))
    present = bool(stage_packet or safe_work_result)
    stage_kind, work_type = _assistant_grade_stage_kind_and_work_type(probe)
    requires_recovery = bool(
        present
        and (
            stage_kind in ASSISTANT_GRADE_BLOCKING_WORK_TYPES
            or work_type in ASSISTANT_GRADE_BLOCKING_WORK_TYPES
        )
    )
    return {
        "present": present,
        "source": str(probe.get("source") or "").strip(),
        "bundle_source": str(probe.get("assistant_grade_bundle_source") or "current_runtime_bundle").strip(),
        "stage_kind": stage_kind,
        "work_type": work_type,
        "requires_recovery": requires_recovery,
        "blocking_reason": "internal_action_not_assistant_grade" if requires_recovery else "",
        "next_action": "stage_fresh_assistant_grade_proactive_packet" if requires_recovery else "",
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


def _mapping_value(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text_list(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _object_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, (list, tuple)):
        return [dict(item) for item in value if isinstance(item, Mapping)]
    return []


def _stage_or_input(stage_payload: Mapping[str, Any], input_contract: Mapping[str, Any], key: str) -> Any:
    stage_value = stage_payload.get(key)
    if stage_value not in (None, "", [], (), {}):
        return stage_value
    return input_contract.get(key)


def _recipient_location_count(recipient_context: Mapping[str, Any]) -> int:
    location = _mapping_value(recipient_context.get("location"))
    return 1 if any(_text_list(location.get(key)) for key in ("phrases", "city_terms", "postal_codes", "country_codes", "country_names")) else 0


def _candidate_assessment_count_for_current_packet(
    *,
    stage_payload: Mapping[str, Any],
    input_contract: Mapping[str, Any],
    safe_work_result: Mapping[str, Any],
) -> int:
    for key in ("candidate_items", "candidates", "booking_options"):
        candidates = _object_list(_stage_or_input(stage_payload, input_contract, key))
        if candidates:
            return sum(1 for candidate in candidates if isinstance(candidate.get("preference_assessment"), Mapping))
    shortlist = _object_list(safe_work_result.get("shortlist"))
    if shortlist:
        return sum(1 for candidate in shortlist if isinstance(candidate.get("preference_assessment"), Mapping))
    recommended = _mapping_value(safe_work_result.get("recommended_option_or_draft"))
    recommended_value = _mapping_value(recommended.get("value"))
    return 1 if isinstance(recommended_value.get("preference_assessment"), Mapping) else 0


def _normalized_current_packet_context_grounding(artifact_probe: Mapping[str, Any]) -> dict[str, Any]:
    stage_packet = _mapping_value(dict(artifact_probe or {}).get("stage_packet"))
    safe_work_result = _mapping_value(dict(artifact_probe or {}).get("safe_work_result"))
    stage_payload = _mapping_value(_mapping_value(stage_packet.get("stage")).get("payload"))
    input_contract = _mapping_value(_mapping_value(stage_packet.get("safe_work_order")).get("input_contract"))
    packet_present = bool(stage_packet or safe_work_result)
    notes_count = len(_text_list(_stage_or_input(stage_payload, input_contract, "notes")))
    preference_count = len(_text_list(_stage_or_input(stage_payload, input_contract, "preferences")))
    requirement_count = len(_text_list(_stage_or_input(stage_payload, input_contract, "requirements")))
    exclusion_count = len(_text_list(_stage_or_input(stage_payload, input_contract, "exclusions")))
    deadline_count = 1 if str(_stage_or_input(stage_payload, input_contract, "deadline") or "").strip() else 0
    recipient_context = _mapping_value(_stage_or_input(stage_payload, input_contract, "recipient_context"))
    recipient_context_count = 1 if recipient_context else 0
    recipient_location_count = _recipient_location_count(recipient_context)
    candidate_assessment_count = _candidate_assessment_count_for_current_packet(
        stage_payload=stage_payload,
        input_contract=input_contract,
        safe_work_result=safe_work_result,
    )
    applied_context_count = (
        notes_count
        + preference_count
        + requirement_count
        + exclusion_count
        + deadline_count
        + recipient_context_count
        + recipient_location_count
        + candidate_assessment_count
    )
    grounded = packet_present and applied_context_count > 0
    item_count = 1 if packet_present else 0
    grounded_item_count = 1 if grounded else 0
    return {
        "grounded": grounded,
        "item_count": item_count,
        "grounded_item_count": grounded_item_count,
        "ungrounded_item_count": max(item_count - grounded_item_count, 0),
        "applied_context_count": applied_context_count,
        "notes_count": notes_count,
        "preference_count": preference_count,
        "requirement_count": requirement_count,
        "exclusion_count": exclusion_count,
        "deadline_count": deadline_count,
        "candidate_assessment_count": candidate_assessment_count,
        "recipient_context_count": recipient_context_count,
        "recipient_location_count": recipient_location_count,
        "source": "current_packet_runtime_artifact",
    }


def _normalized_context_grounding(report: Mapping[str, Any], *, artifact_probe: Mapping[str, Any] | None = None) -> dict[str, Any]:
    context = dict(report.get("context_grounding") or {})
    item_count = int(context.get("item_count") or report.get("actionable_count") or 0)
    grounded_item_count = int(context.get("grounded_item_count") or 0)
    applied_context_count = int(context.get("applied_context_count") or 0)
    ungrounded_item_count = int(context.get("ungrounded_item_count") or max(item_count - grounded_item_count, 0))
    current_packet_context = _normalized_current_packet_context_grounding(artifact_probe or {})
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
        "current_packet_context_grounding": current_packet_context,
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
    if live_receipt_checked and _live_receipt_requires_runtime_recovery(live_receipt):
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
    if live_receipt_checked and _live_receipt_requires_runtime_recovery(live_receipt):
        return (
            str(live_receipt.get("delivery_next_action") or "repair_proactive_operator_runtime_posture").strip()
            or "repair_proactive_operator_runtime_posture"
        )
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
        surface = dict(approval_capture_surface or {})
        live_pending_count = int(surface.get("current_packet_live_pending_count") or 0)
        if bool(surface.get("manual_outcome_capture_ready")) and live_pending_count <= 0:
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
        if deferred_reason == "deferred_by_quiet_hours":
            return "Proactive OODA delivery is currently deferred by quiet hours."
        if deferred_reason == "deferred_by_interruption_budget":
            return "Proactive OODA delivery is currently deferred because the interruption budget is exhausted."
        if deferred_reason == "deferred_by_operator_pause":
            return "Proactive OODA delivery is currently deferred by operator pause."
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
            surface = dict(approval_capture_surface or {})
            live_pending_count = int(surface.get("current_packet_live_pending_count") or 0)
            if bool(surface.get("manual_outcome_capture_ready")) and live_pending_count > 0:
                return (
                    "Proactive OODA route, packet runtime, latest host-visible live receipt, "
                    "Telegram approval, and manual approval outcome capture are ready for operator follow-through."
                )
            if bool(surface.get("manual_outcome_capture_ready")):
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
    browser_handoff: Mapping[str, Any] | None,
    approval_capture_surface: Mapping[str, Any] | None,
    approval_capture: Mapping[str, Any] | None,
) -> dict[str, Any]:
    guard = _normalized_delivery_guard(report)
    if _browser_handoff_requires_recovery(browser_handoff):
        runtime_delivery_state = str(guard.get("delivery_state") or "").strip()
        if runtime_delivery_state and runtime_delivery_state != "browser_handoff_pending":
            guard["runtime_delivery_state"] = runtime_delivery_state
        guard["delivery_state"] = "browser_handoff_pending"
        guard["user_action_required"] = True
        guard["browser_handoff_pending"] = True
        guard["blocker_code"] = str(dict(browser_handoff or {}).get("blocker_code") or "").strip()
        return guard
    if not _approval_followthrough_ready(
        status,
        live_receipt=live_receipt,
        live_receipt_checked=live_receipt_checked,
        approval_capture_surface=approval_capture_surface,
        approval_capture=approval_capture,
    ):
        return _clear_stale_approval_followthrough_guard(
            report,
            guard,
            approval_capture_surface=approval_capture_surface,
        )
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
    browser_handoff: Mapping[str, Any] | None,
    approval_capture_surface: Mapping[str, Any] | None,
    approval_capture: Mapping[str, Any] | None,
) -> int:
    runtime_count = int(report.get("actionable_count") or 0)
    if _browser_handoff_requires_recovery(browser_handoff):
        return max(runtime_count, 1)
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
    if _current_packet_internal_action(artifact_probe):
        return False
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


def _current_packet_internal_action(artifact_probe: Mapping[str, Any]) -> bool:
    stage_packet = dict(artifact_probe.get("stage_packet") or {})
    stage = dict(stage_packet.get("stage") or {})
    stage_payload = dict(stage.get("payload") or {})
    safe_work_order = dict(stage_packet.get("safe_work_order") or {})
    safe_work_result = dict(artifact_probe.get("safe_work_result") or {})
    stage_kind = str(stage.get("kind") or "").strip().lower()
    work_type = str(
        stage_payload.get("work_type")
        or safe_work_order.get("work_type")
        or safe_work_result.get("work_type")
        or ""
    ).strip().lower()
    return bool(
        stage_kind in ASSISTANT_GRADE_BLOCKING_WORK_TYPES
        or work_type in ASSISTANT_GRADE_BLOCKING_WORK_TYPES
    )


def _current_packet_user_action_required(artifact_probe: Mapping[str, Any]) -> bool:
    if _current_packet_internal_action(artifact_probe):
        return False
    if not _current_packet_approval_request_recordable(artifact_probe):
        return bool(
            int(artifact_probe.get("current_packet_live_pending_count") or 0) > 0
            or int(artifact_probe.get("current_packet_callback_pending_count") or 0) > 0
            or int(artifact_probe.get("current_packet_callback_record_count") or 0) > 0
        )
    stage_packet = dict(artifact_probe.get("stage_packet") or {})
    safe_work_result = dict(artifact_probe.get("safe_work_result") or {})
    stage_payload = dict(dict(stage_packet.get("stage") or {}).get("payload") or {})
    safe_work_order = dict(stage_packet.get("safe_work_order") or {})
    approval_request = {
        "packet_ref": _stage_packet_ref(stage_packet),
        "staged_artifact_ref": _safe_work_result_ref(safe_work_result),
        "approval_prompt": str(
            safe_work_result.get("approval_prompt")
            or stage_payload.get("approval_prompt")
            or ""
        ).strip(),
        "staged_action_url": str(
            safe_work_result.get("staged_action_url")
            or stage_payload.get("approval_url")
            or ""
        ).strip(),
        "approved_execution_mode": str(stage_payload.get("approved_execution_mode") or "").strip(),
        "approved_action": str(stage_payload.get("approved_action") or "").strip(),
        "work_type": str(
            stage_payload.get("work_type")
            or safe_work_order.get("work_type")
            or safe_work_result.get("work_type")
            or ""
        ).strip().lower(),
    }
    return approval_request_needs_telegram_user_action(approval_request)


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
    current_packet_duplicate_live_pending_count = max(current_packet_live_pending_count - 1, 0)
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
    current_packet_user_action_required = _current_packet_user_action_required(artifact_probe)
    manual_outcome_capture_ready = bool(
        _current_packet_approval_request_recordable(artifact_probe)
        and current_packet_user_action_required
        and not approval_outcome_matches_current_packet
    )
    callback_noncurrent_pending_count = int(artifact_probe.get("approval_callback_noncurrent_pending_count") or 0)
    callback_stale_pending_count = int(artifact_probe.get("approval_callback_stale_pending_count") or 0)
    callback_hygiene_ready, callback_hygiene_blocking_reason, callback_hygiene_next_action = _approval_callback_hygiene(
        callback_noncurrent_pending_count=callback_noncurrent_pending_count,
        callback_stale_pending_count=callback_stale_pending_count,
        current_packet_callback_stale_pending_count=current_packet_callback_stale_pending_count,
        current_packet_duplicate_live_pending_count=current_packet_duplicate_live_pending_count,
    )
    ready = (
        bool(delivery_route.get("ready"))
        and bool(dict(report.get("stage_packets") or {}).get("ready"))
        and bool(dict(report.get("safe_work_results") or {}).get("ready"))
        and selected_channel == "telegram"
        and bool(approval_outcome_path)
        and bool(callback_dir)
        and callback_dir_writable
        and callback_hygiene_ready
        and ((current_packet_live_pending_count == 1 and current_packet_user_action_required) or manual_outcome_capture_ready)
    )
    return {
        "present": bool(approval_outcome_path or callback_dir),
        "ready": ready,
        "mode": (
            "telegram_callback_pending"
            if current_packet_live_pending_count == 1
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
        "callback_noncurrent_pending_count": callback_noncurrent_pending_count,
        "callback_stale_pending_count": callback_stale_pending_count,
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
        "current_packet_duplicate_live_pending_count": current_packet_duplicate_live_pending_count,
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
        "current_packet_user_action_required": current_packet_user_action_required,
        "current_packet_ref_sha256": _hash_value(_stage_packet_ref(dict(artifact_probe.get("stage_packet") or {}))),
        "current_staged_artifact_ref_sha256": _hash_value(
            _safe_work_result_ref(dict(artifact_probe.get("safe_work_result") or {}))
        ),
        "approval_outcome_matches_current_packet": approval_outcome_matches_current_packet,
        "telegram_approval_surface_ready": current_packet_live_pending_count == 1 and current_packet_user_action_required,
        "duplicate_live_pending_callbacks_present": current_packet_duplicate_live_pending_count > 0,
        "manual_outcome_capture_ready": manual_outcome_capture_ready,
        "callback_hygiene_ready": callback_hygiene_ready,
        "callback_hygiene_blocking_reason": callback_hygiene_blocking_reason,
        "callback_hygiene_next_action": callback_hygiene_next_action,
        **_next_action_surface_fields(callback_hygiene_next_action),
        "source": str(artifact_probe.get("source") or "").strip() or "",
    }


def _normalize_approval_capture_surface(
    surface: Mapping[str, Any] | None,
    approval_capture: Mapping[str, Any] | None,
) -> dict[str, Any]:
    normalized = dict(surface or {})
    if not normalized:
        return {}
    current_packet_user_action_required = bool(
        normalized.get("current_packet_user_action_required")
        if "current_packet_user_action_required" in normalized
        else (
            normalized.get("manual_outcome_capture_ready")
            or normalized.get("telegram_approval_surface_ready")
            or int(normalized.get("current_packet_live_pending_count") or 0) > 0
        )
    )
    callback_hygiene_ready = bool(normalized.get("callback_hygiene_ready", True))
    manual_outcome_capture_ready = bool(
        normalized.get("manual_outcome_capture_ready")
        and normalized.get("current_packet_approval_request_recordable")
        and current_packet_user_action_required
        and callback_hygiene_ready
    )
    telegram_approval_surface_ready = bool(
        normalized.get("telegram_approval_surface_ready")
        and current_packet_user_action_required
        and bool(dict(approval_capture or {}).get("checked"))
        and callback_hygiene_ready
    )
    normalized["current_packet_user_action_required"] = current_packet_user_action_required
    normalized["manual_outcome_capture_ready"] = manual_outcome_capture_ready
    normalized["telegram_approval_surface_ready"] = telegram_approval_surface_ready
    normalized["ready"] = callback_hygiene_ready and bool(normalized.get("ready")) and bool(
        telegram_approval_surface_ready or manual_outcome_capture_ready
    )
    normalized["mode"] = (
        "telegram_callback_pending"
        if telegram_approval_surface_ready
        else "manual_outcome_capture_ready"
        if manual_outcome_capture_ready
        else str(normalized.get("mode") or "").strip()
    )
    return normalized


def _clear_stale_approval_followthrough_guard(
    report: Mapping[str, Any],
    guard: Mapping[str, Any] | None,
    *,
    approval_capture_surface: Mapping[str, Any] | None,
) -> dict[str, Any]:
    normalized = dict(guard or {})
    if str(normalized.get("delivery_state") or "").strip() != "approval_capture_pending":
        return normalized
    if bool(dict(approval_capture_surface or {}).get("ready")):
        return normalized
    runtime_count = int(report.get("actionable_count") or 0)
    fallback_state = str(normalized.get("runtime_delivery_state") or "").strip()
    if not fallback_state and runtime_count <= 0:
        fallback_state = "no_actionable_items"
    normalized["delivery_state"] = fallback_state
    normalized["user_action_required"] = False
    normalized["pending_approval_surface"] = False
    normalized["manual_outcome_capture_ready"] = False
    normalized["current_packet_live_pending_count"] = 0
    return normalized


def _local_artifact_probe(
    *,
    report_args: argparse.Namespace,
    live_receipt_path: Path | None,
    allow_live_runtime_probe: bool = False,
    live_probe_timeout_seconds: float | None = None,
    prefer_browse_backed_delivery: bool = False,
) -> dict[str, Any]:
    effective_timeout = float(live_probe_timeout_seconds or _live_probe_timeout_seconds())
    state_path = str(
        getattr(report_args, "state_path", "state/proactive_ooda_notified.json") or "state/proactive_ooda_notified.json"
    )
    receipt_path = str(live_receipt_path or "")
    stage_packet_dir = str(getattr(report_args, "stage_packet_dir", "") or "")
    safe_work_result_dir = str(getattr(report_args, "safe_work_result_dir", "") or "")

    def _live_probe(*, timeout_seconds: float | None = None) -> Mapping[str, Any]:
        if not allow_live_runtime_probe:
            return {
                "probe_ok": False,
                "status": "probe_disabled",
                "blocking_reason": "live_runtime_probe_disabled",
            }
        try:
            return dict(
                ea_live_ops.probe_proactive_artifacts(
                    timeout_seconds=float(timeout_seconds or effective_timeout),
                    output_format="json",
                    prefer_browse_backed_delivery=prefer_browse_backed_delivery,
                )
                or {}
            )
        except Exception as exc:
            return {
                "probe_ok": False,
                "status": "probe_failed",
                "blocking_reason": type(exc).__name__,
                "reason": type(exc).__name__,
            }

    def _bundle_loader(
        *,
        root: Path,
        state_path: str | Path,
        receipt_path: str | Path = "",
        stage_packet_dir: str | Path = "",
        safe_work_result_dir: str | Path = "",
    ) -> Mapping[str, Any]:
        return load_runtime_artifact_bundle(
            root=root,
            state_path=state_path,
            receipt_path=receipt_path,
            stage_packet_dir=stage_packet_dir,
            safe_work_result_dir=safe_work_result_dir,
            prefer_browse_backed_delivery=prefer_browse_backed_delivery,
        )

    resolution = resolve_proactive_ooda_capture_bundle(
        root=ROOT,
        state_path=state_path,
        receipt_path=receipt_path,
        stage_packet_dir=stage_packet_dir,
        safe_work_result_dir=safe_work_result_dir,
        timeout_seconds=effective_timeout,
        live_probe=_live_probe,
        bundle_loader=_bundle_loader,
    )
    bundle = dict(resolution.get("bundle") or {})
    resolution_source = str(resolution.get("bundle_source") or "").strip()
    live_report = dict(resolution.get("live_report") or {})
    probe_source = (
        str(live_report.get("source") or "").strip() or "docker_compose_exec"
        if resolution_source == "live_runtime"
        else "local_filesystem"
    )
    return {
        "source": probe_source,
        "artifact_resolution_source": resolution_source or "host_runtime_fallback",
        "artifact_resolution_host_fallback_used": bool(resolution.get("host_fallback_used")),
        "artifact_resolution_fallback_reason": str(resolution.get("fallback_reason") or "").strip(),
        "artifact_filter_reason": str(bundle.get("artifact_filter_reason") or "").strip(),
        "assistant_grade_bundle_source": (
            "historical_browse_backed_proof_bundle" if prefer_browse_backed_delivery else "current_runtime_bundle"
        ),
        "state_path": bundle.get("state_path"),
        "run_receipt_path": bundle.get("run_receipt_path"),
        "stage_packet_path": bundle.get("stage_packet_path"),
        "safe_work_result_path": bundle.get("safe_work_result_path"),
        "action_required_only_quiet_receipt_path": bundle.get("action_required_only_quiet_receipt_path"),
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


def _assistant_grade_artifact_probe(
    *,
    artifact_probe: Mapping[str, Any],
    report_args: argparse.Namespace,
    live_receipt_path: Path | None,
    allow_live_route_probe: bool,
    live_probe_timeout_seconds: float,
) -> dict[str, Any]:
    current_probe = dict(artifact_probe or {})
    if not bool(_normalized_assistant_grade_packet(current_probe).get("requires_recovery")):
        return current_probe
    if not _assistant_grade_historical_fallback_allowed(current_probe):
        return current_probe

    candidate_probe = _local_artifact_probe(
        report_args=report_args,
        live_receipt_path=live_receipt_path,
        allow_live_runtime_probe=False,
        live_probe_timeout_seconds=live_probe_timeout_seconds,
        prefer_browse_backed_delivery=True,
    )

    if bool(_normalized_assistant_grade_packet(candidate_probe).get("requires_recovery")):
        return current_probe
    if not (dict(candidate_probe.get("stage_packet") or {}) or dict(candidate_probe.get("safe_work_result") or {})):
        return current_probe
    return candidate_probe


def _assistant_grade_historical_fallback_allowed(artifact_probe: Mapping[str, Any] | None) -> bool:
    probe = dict(artifact_probe or {})
    if bool(probe.get("assistant_grade_allow_historical_fallback")):
        return True
    return bool(
        dict(probe.get("run_receipt") or {})
        or _path_text(probe.get("run_receipt_path"))
    )


def build_proactive_ooda_operator_status(
    *,
    output_path: Path = DEFAULT_OUTPUT,
    generated_at: str | None = None,
    report_args: argparse.Namespace | None = None,
    live_receipt_path: Path | None = None,
    allow_live_route_probe: bool = True,
    skip_gmail_draft_followthrough_probe: bool = False,
    skip_source_coverage_probe: bool = False,
    skip_provider_cost_pressure_probe: bool = True,
) -> dict[str, Any]:
    effective_report_args = argparse.Namespace(**vars(report_args)) if report_args is not None else _default_report_args()
    route_probe: dict[str, Any] = {}
    artifact_probe: dict[str, Any] = {}
    approval_capture_probe: dict[str, Any] = {}
    gmail_draft_probe: dict[str, Any] = {}
    source_coverage_probe: dict[str, Any] = {}
    provider_cost_pressure_probe: dict[str, Any] = {}
    principal_id = str(getattr(effective_report_args, "principal_id", "") or proactive_verifier._default_principal_id()).strip()
    live_probe_timeout_seconds = _live_probe_timeout_seconds()
    configured_live_receipt_path = live_receipt_path if live_receipt_path is not None else _configured_live_receipt_path()
    effective_live_receipt_path = live_receipt_path if live_receipt_path is not None else _default_live_receipt_path()
    allow_live_artifact_probe = bool(
        allow_live_route_probe
        and live_receipt_path is None
        and not _has_explicit_artifact_dirs(effective_report_args)
    )
    if effective_live_receipt_path is not None:
        effective_report_args.receipt_path = str(effective_live_receipt_path)
    elif not hasattr(effective_report_args, "receipt_path"):
        effective_report_args.receipt_path = ""

    def _run_live_probe_bundle(*, prefer_host_runtime: bool) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
        bundle_route_probe: dict[str, Any] = {}
        bundle_artifact_probe: dict[str, Any] = {}
        bundle_gmail_draft_probe: dict[str, Any] = {}
        bundle_source_coverage_probe: dict[str, Any] = {}
        bundle_provider_cost_pressure_probe: dict[str, Any] = {}
        with _host_runtime_proactive_probe_override(prefer_host_runtime):
            if allow_live_route_probe:
                try:
                    bundle_route_probe = ea_live_ops.probe_proactive_route(
                        principal_id=principal_id,
                        receipt_path=str(configured_live_receipt_path or ""),
                        timeout_seconds=live_probe_timeout_seconds,
                        include_artifact_probe=False,
                    )
                except Exception:
                    bundle_route_probe = {}
                if isinstance(bundle_route_probe.get("artifact_probe"), dict):
                    bundle_artifact_probe = dict(bundle_route_probe.get("artifact_probe") or {})
                if live_receipt_path is None:
                    route_live_receipt_path = _route_live_receipt_host_path(bundle_route_probe)
                    if not bundle_artifact_probe:
                        bundle_artifact_probe = _local_artifact_probe(
                            report_args=effective_report_args,
                            live_receipt_path=route_live_receipt_path or effective_live_receipt_path,
                            allow_live_runtime_probe=allow_live_artifact_probe,
                            live_probe_timeout_seconds=live_probe_timeout_seconds,
                        )
                    if not skip_gmail_draft_followthrough_probe:
                        bundle_gmail_draft_probe = _gmail_draft_followthrough_probe(
                            principal_id,
                            timeout_seconds=live_probe_timeout_seconds,
                        )
            if not skip_source_coverage_probe:
                bundle_source_coverage_probe = _source_coverage_probe(
                    principal_id,
                    timeout_seconds=live_probe_timeout_seconds,
                )
            if not skip_provider_cost_pressure_probe:
                bundle_provider_cost_pressure_probe = _provider_cost_pressure_probe(
                    principal_id,
                    timeout_seconds=live_probe_timeout_seconds,
                )
        return (
            bundle_route_probe,
            bundle_artifact_probe,
            bundle_gmail_draft_probe,
            bundle_source_coverage_probe,
            bundle_provider_cost_pressure_probe,
        )

    route_probe, artifact_probe, gmail_draft_probe, source_coverage_probe, provider_cost_pressure_probe = _run_live_probe_bundle(
        prefer_host_runtime=False
    )
    if _should_retry_host_runtime_live_probe(
        allow_live_route_probe=allow_live_route_probe,
        live_receipt_path=live_receipt_path,
        report_args=effective_report_args,
        route_probe=route_probe,
        artifact_probe=artifact_probe,
        source_coverage_probe=source_coverage_probe,
        provider_cost_pressure_probe=provider_cost_pressure_probe,
        skip_source_coverage_probe=skip_source_coverage_probe,
        skip_provider_cost_pressure_probe=skip_provider_cost_pressure_probe,
    ):
        retry_route_probe, retry_artifact_probe, retry_gmail_draft_probe, retry_source_coverage_probe, retry_provider_cost_pressure_probe = _run_live_probe_bundle(
            prefer_host_runtime=True
        )
        retry_score = _live_probe_bundle_score(
            route_probe=retry_route_probe,
            artifact_probe=retry_artifact_probe,
            gmail_draft_probe=retry_gmail_draft_probe,
            source_coverage_probe=retry_source_coverage_probe,
            provider_cost_pressure_probe=retry_provider_cost_pressure_probe,
        )
        current_score = _live_probe_bundle_score(
            route_probe=route_probe,
            artifact_probe=artifact_probe,
            gmail_draft_probe=gmail_draft_probe,
            source_coverage_probe=source_coverage_probe,
            provider_cost_pressure_probe=provider_cost_pressure_probe,
        )
        if retry_score > current_score:
            route_probe = retry_route_probe
            artifact_probe = retry_artifact_probe
            gmail_draft_probe = retry_gmail_draft_probe
            source_coverage_probe = retry_source_coverage_probe
            provider_cost_pressure_probe = retry_provider_cost_pressure_probe

    if (
        allow_live_route_probe
        and configured_live_receipt_path is not None
        and _route_probe_live_receipt_missing(route_probe=route_probe)
    ):
        unpinned_route_probe: dict[str, Any] = {}
        with _host_runtime_proactive_probe_override(str(route_probe.get("source") or "").strip() == "host_python_exec"):
            try:
                unpinned_route_probe = ea_live_ops.probe_proactive_route(
                    principal_id=principal_id,
                    receipt_path="",
                    timeout_seconds=live_probe_timeout_seconds,
                    include_artifact_probe=False,
                )
            except Exception:
                unpinned_route_probe = {}
        if _route_probe_live_receipt_score(route_probe=unpinned_route_probe) > _route_probe_live_receipt_score(
            route_probe=route_probe
        ):
            route_probe = unpinned_route_probe

    # Provider-cost posture remains relevant even when the caller pins an explicit
    # live receipt path. Backfill it directly if the bundled probe path left it empty.
    if allow_live_route_probe and not skip_provider_cost_pressure_probe and not provider_cost_pressure_probe:
        provider_cost_pressure_probe = _provider_cost_pressure_probe(
            principal_id,
            timeout_seconds=live_probe_timeout_seconds,
        )

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
            allow_live_runtime_probe=allow_live_artifact_probe,
            live_probe_timeout_seconds=live_probe_timeout_seconds,
        )
    if not artifact_probe:
        artifact_probe = _local_artifact_probe(
            report_args=effective_report_args,
            live_receipt_path=effective_live_receipt_path,
            allow_live_runtime_probe=False,
            live_probe_timeout_seconds=live_probe_timeout_seconds,
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
    browser_handoff = _normalized_browser_handoff(safe_work_audit_probe)
    current_artifact_filter = _normalized_current_artifact_filter(artifact_probe)
    current_artifact_filter_blocks = bool(current_artifact_filter.get("requires_recovery"))
    assistant_grade_probe = _assistant_grade_artifact_probe(
        artifact_probe=safe_work_audit_probe,
        report_args=effective_report_args,
        live_receipt_path=live_receipt_path,
        allow_live_route_probe=allow_live_route_probe,
        live_probe_timeout_seconds=live_probe_timeout_seconds,
    )
    assistant_grade_packet = _normalized_assistant_grade_packet(assistant_grade_probe)
    assistant_grade_recovery_active = bool(assistant_grade_packet.get("requires_recovery"))
    suppressed_projection = _normalized_suppressed_projection(artifact_probe)
    suppressed_projection_blocks = bool(suppressed_projection.get("requires_recovery"))
    runtime_source_health = _runtime_source_health_summary(artifact_probe)
    source_coverage = _source_coverage_summary(source_coverage_probe)
    provider_cost_pressure = _provider_cost_pressure_summary(provider_cost_pressure_probe)
    status = _status(report, live_receipt=live_receipt, live_receipt_checked=live_receipt_checked)
    reason = _reason(report, live_receipt=live_receipt, live_receipt_checked=live_receipt_checked)
    if safe_work_audit_blocks:
        status = "blocked_local_runtime"
        reason = _safe_work_audit_blocking_reason(safe_work_audit)
    elif current_artifact_filter_blocks:
        status = "blocked_local_runtime"
        reason = str(current_artifact_filter.get("blocking_reason") or "filtered_current_artifact").strip()
    elif assistant_grade_recovery_active:
        status = "ready_with_recovery_action"
        reason = str(assistant_grade_packet.get("blocking_reason") or "internal_action_not_assistant_grade").strip()
    elif suppressed_projection_blocks and status in {"ready_local_runtime", "ready_with_live_receipt", "ready_with_recovery_action"}:
        status = "ready_with_recovery_action"
        reason = str(suppressed_projection.get("blocking_reason") or "suppressed_safe_work_projection").strip()
    browser_handoff_recovery_active = bool(
        not safe_work_audit_blocks
        and not current_artifact_filter_blocks
        and not assistant_grade_recovery_active
        and not suppressed_projection_blocks
        and status in {"ready_local_runtime", "ready_with_live_receipt"}
        and _browser_handoff_requires_recovery(browser_handoff)
    )
    if browser_handoff_recovery_active:
        status = "ready_with_recovery_action"
        reason = _browser_handoff_recovery_reason(browser_handoff)
    source_health_recovery_active = bool(
        not safe_work_audit_blocks
        and not current_artifact_filter_blocks
        and not assistant_grade_recovery_active
        and not suppressed_projection_blocks
        and not browser_handoff_recovery_active
        and _source_health_recovery_candidate_status(status, reason)
        and _runtime_source_health_requires_recovery(runtime_source_health)
    )
    if source_health_recovery_active:
        status = "ready_with_recovery_action"
        reason = _runtime_source_health_recovery_reason(runtime_source_health)
    provider_cost_pressure_recovery_active = bool(
        not safe_work_audit_blocks
        and not current_artifact_filter_blocks
        and not assistant_grade_recovery_active
        and not suppressed_projection_blocks
        and not browser_handoff_recovery_active
        and not source_health_recovery_active
        and status in {"ready_local_runtime", "ready_with_live_receipt"}
        and bool(provider_cost_pressure.get("requires_recovery"))
    )
    if provider_cost_pressure_recovery_active:
        status = "ready_with_recovery_action"
        reason = _provider_cost_pressure_recovery_reason(provider_cost_pressure)
    source_coverage_recovery_active = bool(
        not safe_work_audit_blocks
        and not current_artifact_filter_blocks
        and not assistant_grade_recovery_active
        and not suppressed_projection_blocks
        and not browser_handoff_recovery_active
        and not source_health_recovery_active
        and not provider_cost_pressure_recovery_active
        and status in {"ready_local_runtime", "ready_with_live_receipt"}
        and _source_coverage_requires_recovery(source_coverage)
    )
    if source_coverage_recovery_active:
        status = "ready_with_recovery_action"
        reason = _source_coverage_recovery_reason(source_coverage)
    approval_capture_surface = _approval_capture_surface(report=report, artifact_probe=artifact_probe)
    if (
        allow_live_route_probe
        and live_receipt_path is None
        and not safe_work_audit_blocks
        and not current_artifact_filter_blocks
        and not assistant_grade_recovery_active
        and _approval_capture_surface_ready(approval_capture_surface)
        and int(approval_capture_surface.get("current_packet_live_pending_count") or 0) > 0
        and live_receipt_checked
        and bool(live_receipt.get("ok"))
    ):
        approval_capture_probe = _approval_capture_probe(principal_id, timeout_seconds=live_probe_timeout_seconds)
    approval_capture = _approval_capture_summary(approval_capture_probe)
    approval_capture_surface = _normalize_approval_capture_surface(approval_capture_surface, approval_capture)
    approval_capture = _reconcile_approval_capture_surface_authority(approval_capture, approval_capture_surface)
    if assistant_grade_recovery_active:
        approval_capture_surface = {}
        approval_capture = {}
    approval_callback_hygiene_blocks = not bool(approval_capture_surface.get("callback_hygiene_ready", True))
    if approval_callback_hygiene_blocks:
        status = "blocked_local_runtime"
        reason = str(
            approval_capture_surface.get("callback_hygiene_blocking_reason")
            or "approval_callback_hygiene_requires_cleanup"
        ).strip()
    if _approval_capture_probe_blocks_followthrough(
        status=status,
        live_receipt=live_receipt,
        live_receipt_checked=live_receipt_checked,
        approval_capture_surface=approval_capture_surface,
        approval_capture=approval_capture,
    ):
        reason = str(approval_capture.get("blocking_reason") or "approval_capture_not_ready").strip()
    approval_followthrough_override_active = _soft_followthrough_recovery_override(
        status=status,
        report=report,
        source_coverage=source_coverage,
        live_receipt=live_receipt,
        live_receipt_checked=live_receipt_checked,
        approval_capture_surface=approval_capture_surface,
        approval_capture=approval_capture,
        safe_work_audit_blocks=safe_work_audit_blocks,
        current_artifact_filter_blocks=current_artifact_filter_blocks,
        assistant_grade_recovery_active=assistant_grade_recovery_active,
        suppressed_projection_blocks=suppressed_projection_blocks,
        browser_handoff_recovery_active=browser_handoff_recovery_active,
        source_health_recovery_active=source_health_recovery_active,
        provider_cost_pressure_recovery_active=provider_cost_pressure_recovery_active,
        approval_callback_hygiene_blocks=approval_callback_hygiene_blocks,
    )
    if approval_followthrough_override_active:
        status = "ready_with_live_receipt"
        source_health_recovery_active = False
        source_coverage_recovery_active = False
    if safe_work_audit_blocks or current_artifact_filter_blocks or suppressed_projection_blocks:
        next_action = "repair_proactive_safe_work_audit"
    elif assistant_grade_recovery_active:
        next_action = "stage_fresh_assistant_grade_proactive_packet"
    elif browser_handoff_recovery_active:
        next_action = _browser_handoff_recovery_next_action(browser_handoff)
    elif approval_callback_hygiene_blocks:
        next_action = str(
            approval_capture_surface.get("callback_hygiene_next_action")
            or "cleanup_proactive_approval_callbacks"
        ).strip()
    elif source_health_recovery_active:
        next_action = _runtime_source_health_recovery_next_action(runtime_source_health)
    elif provider_cost_pressure_recovery_active:
        next_action = "repair_provider_cost_routing"
    elif source_coverage_recovery_active:
        next_action = _source_coverage_recovery_next_action(source_coverage)
    else:
        next_action = _operator_followthrough_next_action(
            status,
            report,
            live_receipt=live_receipt,
            live_receipt_checked=live_receipt_checked,
            approval_capture_surface=approval_capture_surface,
            approval_capture=approval_capture,
        )
    if source_coverage_recovery_active:
        next_action_surface = _source_coverage_recovery_surface_fields(source_coverage, next_action)
    else:
        next_action_surface = _next_action_surface_fields(next_action)
    if safe_work_audit_blocks:
        summary = (
            "Proactive OODA has a current safe-work artifact, but the packet-quality auditor did not pass it "
            "for operator follow-through."
        )
    elif current_artifact_filter_blocks:
        summary = "Proactive OODA filtered the current packet before follow-through because it is not decision-ready."
    elif assistant_grade_recovery_active:
        summary = (
            "The proactive OODA mechanics have evidence, but the selected packet is not assistant-grade enough "
            "to prove production readiness."
        )
    elif suppressed_projection_blocks:
        summary = (
            "Proactive OODA runtime is healthy, but the latest quiet run suppressed "
            f"{int(suppressed_projection.get('suppressed_item_count') or 0)} non-deliverable safe-work "
            "item(s) from user and Teable packet projection."
        )
    elif browser_handoff_recovery_active:
        summary = _browser_handoff_recovery_summary(browser_handoff)
    elif approval_callback_hygiene_blocks:
        summary = (
            "Proactive OODA approval-callback hygiene needs cleanup before operator follow-through can resume."
        )
    elif source_health_recovery_active:
        summary = _runtime_source_health_recovery_summary(runtime_source_health)
    elif provider_cost_pressure_recovery_active:
        summary = _provider_cost_pressure_recovery_summary(provider_cost_pressure)
    elif source_coverage_recovery_active:
        summary = _source_coverage_recovery_summary(source_coverage)
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
        browser_handoff=browser_handoff,
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
            if safe_work_audit_blocks
            or current_artifact_filter_blocks
            or assistant_grade_recovery_active
            or suppressed_projection_blocks
            or browser_handoff_recovery_active
            or source_health_recovery_active
            or provider_cost_pressure_recovery_active
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
        "context_grounding": _normalized_context_grounding(report, artifact_probe=artifact_probe),
        "stage_packets": _reconciled_stage_packets(
            report,
            artifact_probe=artifact_probe,
            assistant_grade_probe=assistant_grade_probe,
        ),
        "safe_work_results": _reconciled_safe_work_results(
            report,
            artifact_probe=artifact_probe,
            assistant_grade_probe=assistant_grade_probe,
        ),
        "safe_work_audit": safe_work_audit,
        "browser_handoff": browser_handoff,
        "current_artifact_filter": current_artifact_filter,
        "assistant_grade_packet": assistant_grade_packet,
        "suppressed_projection": suppressed_projection,
        "source_health": runtime_source_health,
        "provider_cost_pressure": provider_cost_pressure,
        "receipt_observation_count": int(report.get("receipt_observation_count") or 0),
        "runtime_actionable_count": runtime_actionable_count,
        "actionable_count": _operator_actionable_count(
            report,
            status=status,
            live_receipt=live_receipt,
            live_receipt_checked=live_receipt_checked,
            browser_handoff=browser_handoff,
            approval_capture_surface=approval_capture_surface,
            approval_capture=approval_capture,
        ),
        "source_mode": str(report.get("source_mode") or "").strip(),
        "live_receipt_checked": live_receipt_checked,
        "live_receipt": dict(live_receipt or {}),
        "approval_capture_surface": approval_capture_surface,
        "approval_capture": approval_capture,
        "gmail_draft_followthrough": _gmail_draft_followthrough_summary(gmail_draft_probe),
        "source_coverage": source_coverage,
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
    parser.add_argument(
        "--skip-provider-cost-pressure-probe",
        action="store_true",
        default=_env_truthy("EA_PROACTIVE_OODA_OPERATOR_SKIP_PROVIDER_COST_PRESSURE_PROBE", default=False),
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
        skip_provider_cost_pressure_probe=bool(args.skip_provider_cost_pressure_probe),
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
