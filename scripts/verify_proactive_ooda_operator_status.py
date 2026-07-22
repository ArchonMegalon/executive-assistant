#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

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

from app.services.proactive_ooda_operator_actions import proactive_next_action_surface
DEFAULT_RECEIPT = ROOT / ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json"
EXPECTED_RULES = {
    "This receipt proves proactive OODA route, guard, and packet-runtime posture only; it does not prove a human accepted the packet.",
    "Delivery recovery hints may be mirrored here and in Teable, but they remain operator aids rather than canonical queue truth.",
    "A live sent receipt can prove one routed delivery happened, but it does not by itself prove ordinary-use usefulness or approval correctness.",
    "Gold-production claims still require accepted proactive packets, routed delivery proof, approved-source or transcript signal evidence, live browse evidence, an auditor-passed chosen candidate, staged reversible artifacts, mirrored Teable current/stale delivery and decision facts, explicit approval outcome evidence, and consent-gated irreversible actions.",
}
EXPECTED_REMAINING_PROOF = (
    "real proactive OODA packet accepted with routed delivery, approved-source or transcript signal, live browse evidence, auditor-passed chosen candidate, staged reversible artifact, mirrored Teable delivery, current-packet, stale-approval, and decision facts, and explicit approval outcome"
)
EXPECTED_SOURCE_COVERAGE_LANES = {
    "postgres_observations",
    "google_workspace",
    "pocket_ai_audio_transcripts",
    "calendar_and_renewal_signals",
    "relationship_and_occasion_signals",
    "shopping_and_vendor_signals",
    "commitment_and_deadline_signals",
    "durable_profile_and_location_context",
}
POCKET_REQUIRED_EVENT_TYPE = "pocket_recording_archive_indexed"
KNOWN_STATUSES = {
    "blocked_delivery_route",
    "blocked_local_runtime",
    "deferred",
    "ready_local_runtime",
    "ready_with_live_receipt",
    "ready_with_recovery_action",
}
NON_MATERIAL_SUPPRESSED_PROJECTION_ISSUE_CODES = {
    "no_decision_ready_material",
    "single_official_info_link_not_decision_ready",
    "flat_search_disabled_property_scout",
    "flat_search_disabled",
}
QUIET_NON_MATERIAL_SUPPRESSED_PROJECTION_ERROR_CODES = {
    "no_user_action_required",
    "no_decision_ready_safe_work",
}
NON_MATERIAL_SUPPRESSED_PROJECTION_REASONS = {
    "packet_projection_suppressed",
    "safe_work_audit_review",
    "safe_work_quality_gate_review",
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


def _is_google_workspace_recovery(receipt: dict[str, Any]) -> bool:
    reason = str(receipt.get("reason") or "").strip()
    return reason.startswith(
        (
            "google_workspace_signal_source_unhealthy:",
            "source_health_google_workspace:",
        )
    )


def _is_suppressed_projection_recovery(receipt: dict[str, Any]) -> bool:
    suppressed = dict(receipt.get("suppressed_projection") or {})
    return bool(suppressed.get("requires_recovery"))


def _source_coverage_missing_lane_keys(source_coverage: dict[str, Any]) -> list[str]:
    return [
        str(item).strip()
        for item in list(source_coverage.get("missing_lane_keys") or [])
        if str(item).strip()
    ]


def _source_coverage_requires_recovery(receipt: dict[str, Any]) -> bool:
    source_coverage = dict(receipt.get("source_coverage") or {})
    if str(source_coverage.get("blocking_reason") or "").strip():
        return True
    if _source_coverage_missing_lane_keys(source_coverage):
        return True
    status = str(source_coverage.get("status") or "").strip()
    if not bool(source_coverage.get("checked")):
        return status not in {"", "not_checked"}
    return status not in {"", "not_checked", "ready", "pass", "fully_ready"}


def _is_source_coverage_recovery(receipt: dict[str, Any]) -> bool:
    return str(receipt.get("reason") or "").strip().startswith("source_coverage_")


def _is_followthrough_recovery(receipt: dict[str, Any]) -> bool:
    reason = str(receipt.get("reason") or "").strip()
    if reason.startswith("followthrough_"):
        return True
    live_receipt = dict(receipt.get("live_receipt") or {})
    return any(
        str(item or "").strip().startswith("followthrough_")
        for item in list(live_receipt.get("errors") or [])
    )


def _provider_cost_pressure_requires_recovery(receipt: dict[str, Any]) -> bool:
    provider_cost = dict(receipt.get("provider_cost_pressure") or {})
    if not provider_cost:
        return False
    if str(provider_cost.get("blocking_reason") or "").strip():
        return True
    return bool(provider_cost.get("requires_recovery"))


def _browser_handoff_requires_recovery(receipt: dict[str, Any]) -> bool:
    browser_handoff = dict(receipt.get("browser_handoff") or {})
    return bool(browser_handoff.get("required"))


def _is_browser_handoff_recovery(receipt: dict[str, Any]) -> bool:
    if _browser_handoff_requires_recovery(receipt):
        return True
    return str(receipt.get("reason") or "").strip() == "browser_handoff_required"


def _assistant_grade_packet_requires_recovery(receipt: dict[str, Any]) -> bool:
    assistant_grade_packet = dict(receipt.get("assistant_grade_packet") or {})
    if assistant_grade_packet:
        return bool(assistant_grade_packet.get("requires_recovery"))
    return str(receipt.get("reason") or "").strip() == "internal_action_not_assistant_grade"


def _is_assistant_grade_packet_recovery(receipt: dict[str, Any]) -> bool:
    return str(receipt.get("reason") or "").strip() == "internal_action_not_assistant_grade"


def _higher_priority_recovery_present(receipt: dict[str, Any]) -> bool:
    delivery_route = dict(receipt.get("delivery_route") or {})
    delivery_guard = dict(receipt.get("delivery_guard") or {})
    stage_packets = dict(receipt.get("stage_packets") or {})
    safe_work_results = dict(receipt.get("safe_work_results") or {})
    safe_work_audit = dict(receipt.get("safe_work_audit") or {})
    current_artifact_filter = dict(receipt.get("current_artifact_filter") or {})
    return bool(
        str(receipt.get("delivery_route_error") or "").strip()
        or str(delivery_route.get("route_error") or "").strip()
        or str(delivery_guard.get("delivery_state") or "").strip() == "deferred"
        or not bool(delivery_route.get("ready", receipt.get("delivery_route_ready")))
        or not bool(stage_packets.get("ready"))
        or not bool(safe_work_results.get("ready"))
        or bool(safe_work_audit.get("blocks_operator_followthrough"))
        or _browser_handoff_requires_recovery(receipt)
        or _assistant_grade_packet_requires_recovery(receipt)
        or bool(current_artifact_filter.get("requires_recovery"))
        or _is_suppressed_projection_recovery(receipt)
        or _is_google_workspace_recovery(receipt)
        or _provider_cost_pressure_requires_recovery(receipt)
    )


def _verify_next_action_surface(receipt: dict[str, Any], issues: list[str]) -> None:
    next_action = str(receipt.get("next_action") or "").strip()
    if next_action in {
        "maintain_proactive_ooda_runtime",
        "repair_proactive_safe_work_audit",
        "stage_fresh_assistant_grade_proactive_packet",
        "complete_browser_handoff_then_resume_ooda_task",
        "sync_pocket_ai_audio_transcripts",
    }:
        if _is_google_workspace_recovery(receipt):
            return
        href = str(receipt.get("next_action_href") or "").strip()
        label = str(receipt.get("next_action_label") or "").strip()
        method = str(receipt.get("next_action_method") or "").strip().lower()
        if not href:
            issues.append(f"{next_action} requires next_action_href")
        elif next_action == "maintain_proactive_ooda_runtime" and "/app/today" not in href:
            issues.append("maintain_proactive_ooda_runtime next_action_href must target Today")
        elif next_action in {
            "repair_proactive_safe_work_audit",
            "stage_fresh_assistant_grade_proactive_packet",
            "complete_browser_handoff_then_resume_ooda_task",
        } and "/app/queue" not in href:
            issues.append(f"{next_action} next_action_href must target Queue")
        elif next_action == "sync_pocket_ai_audio_transcripts" and "/app/api/signals/pocket/sync" not in href:
            issues.append("sync_pocket_ai_audio_transcripts next_action_href must target the Pocket transcript sync action")
        if not label:
            issues.append(f"{next_action} requires next_action_label")
        expected_method = "post" if next_action == "sync_pocket_ai_audio_transcripts" else "get"
        if method != expected_method:
            issues.append(f"{next_action} requires next_action_method={expected_method}")
        return
    if next_action == "repair_provider_cost_routing":
        href = str(receipt.get("next_action_href") or "").strip()
        label = str(receipt.get("next_action_label") or "").strip()
        method = str(receipt.get("next_action_method") or "").strip().lower()
        if not href:
            issues.append("repair_provider_cost_routing requires next_action_href")
        elif "/admin/goals" not in href:
            issues.append("repair_provider_cost_routing next_action_href must target goal evidence")
        if not label:
            issues.append("repair_provider_cost_routing requires next_action_label")
        if method != "get":
            issues.append("repair_provider_cost_routing requires next_action_method=get")
        return
    if next_action != "reauthorize_google_workspace_binding":
        return
    expected_surface = proactive_next_action_surface(next_action)
    href = str(receipt.get("next_action_href") or "").strip()
    label = str(receipt.get("next_action_label") or "").strip()
    method = str(receipt.get("next_action_method") or "").strip().lower()
    if not href:
        issues.append("reauthorize_google_workspace_binding requires next_action_href")
    elif href != str(expected_surface.get("href") or "").strip():
        issues.append("reauthorize_google_workspace_binding next_action_href must target the Google auth recovery surface")
    if not label:
        issues.append("reauthorize_google_workspace_binding requires next_action_label")
    elif label != str(expected_surface.get("label") or "").strip():
        issues.append("reauthorize_google_workspace_binding next_action_label drifted")
    if method != str(expected_surface.get("method") or "").strip().lower():
        issues.append("reauthorize_google_workspace_binding requires next_action_method=get")


def _verify_source_coverage(receipt: dict[str, Any], issues: list[str]) -> None:
    source_coverage = dict(receipt.get("source_coverage") or {})
    if not source_coverage:
        issues.append("source_coverage missing")
        return
    if "checked" not in source_coverage:
        issues.append("source_coverage.checked missing")
    if "probe_ok" not in source_coverage:
        issues.append("source_coverage.probe_ok missing")
    if not str(source_coverage.get("status") or "").strip():
        issues.append("source_coverage.status missing")
    if bool(source_coverage.get("checked")):
        if not str(source_coverage.get("source") or "").strip():
            issues.append("checked source_coverage requires source")
        if not str(source_coverage.get("observed_at") or "").strip():
            issues.append("checked source_coverage requires observed_at")
    lanes = [dict(row or {}) for row in list(source_coverage.get("lanes") or []) if isinstance(row, dict)]
    lane_keys = {str(row.get("key") or "").strip() for row in lanes if str(row.get("key") or "").strip()}
    missing = sorted(EXPECTED_SOURCE_COVERAGE_LANES - lane_keys)
    if missing:
        issues.append(f"source_coverage missing required lanes: {', '.join(missing)}")
    if int(source_coverage.get("lane_count") or 0) < len(EXPECTED_SOURCE_COVERAGE_LANES):
        issues.append("source_coverage.lane_count must include all required lanes")
    privacy = dict(source_coverage.get("privacy") or {})
    for key in ("raw_rows_exposed", "raw_payload_exposed", "raw_transcript_text_exposed", "raw_credential_exposed"):
        if privacy.get(key) is not False:
            issues.append(f"source_coverage.privacy.{key} must remain false")
    if privacy.get("source_ids_hashed") is not True:
        issues.append("source_coverage.privacy.source_ids_hashed must remain true")
    for lane in lanes:
        lane_key = str(lane.get("key") or "").strip() or "unknown"
        if not str(lane.get("status") or "").strip():
            issues.append(f"source_coverage lane {lane_key} status missing")
        if "observed" not in lane:
            issues.append(f"source_coverage lane {lane_key} observed missing")
        for privacy_key in ("raw_payload_exposed", "raw_transcript_text_exposed", "raw_credential_exposed"):
            if lane.get(privacy_key) is not False:
                issues.append(f"source_coverage lane {lane_key} {privacy_key} must remain false")
    pocket_lane = next((row for row in lanes if str(row.get("key") or "").strip() == "pocket_ai_audio_transcripts"), {})
    if not pocket_lane:
        issues.append("source_coverage must include pocket_ai_audio_transcripts lane")
        return
    if pocket_lane.get("raw_transcript_text_exposed") is not False:
        issues.append("pocket_ai_audio_transcripts lane must not expose raw transcript text")
    required_event_types = {
        str(item).strip()
        for item in list(pocket_lane.get("required_event_types") or [])
        if str(item).strip()
    }
    evidence_event_types = {
        str(item).strip()
        for item in list(pocket_lane.get("evidence_event_types") or [])
        if str(item).strip()
    }
    pocket_event_observed = POCKET_REQUIRED_EVENT_TYPE in evidence_event_types
    if POCKET_REQUIRED_EVENT_TYPE not in required_event_types and not pocket_event_observed:
        issues.append("pocket_ai_audio_transcripts lane must require pocket_recording_archive_indexed evidence")
    missing_required_event_types = {
        str(item).strip()
        for item in list(pocket_lane.get("missing_required_event_types") or [])
        if str(item).strip()
    }
    if bool(pocket_lane.get("observed")):
        if pocket_lane.get("required_event_type_observed") is not True and not pocket_event_observed:
            issues.append("observed pocket_ai_audio_transcripts lane must set required_event_type_observed=true")
        if POCKET_REQUIRED_EVENT_TYPE not in evidence_event_types:
            issues.append("observed pocket_ai_audio_transcripts lane must include pocket_recording_archive_indexed evidence")
    else:
        if POCKET_REQUIRED_EVENT_TYPE not in missing_required_event_types:
            issues.append("unobserved pocket_ai_audio_transcripts lane must surface missing pocket_recording_archive_indexed")
        if str(pocket_lane.get("next_action") or "").strip() != "sync_pocket_ai_audio_transcripts":
            issues.append("unobserved pocket_ai_audio_transcripts lane must request sync_pocket_ai_audio_transcripts")
    if _source_coverage_requires_recovery(receipt) and not _higher_priority_recovery_present(receipt):
        if str(receipt.get("status") or "").strip() != "ready_with_recovery_action":
            issues.append("degraded source_coverage without a higher-priority blocker requires status=ready_with_recovery_action")
        if str(receipt.get("operator_action_state") or "").strip() != "recovery_required":
            issues.append("degraded source_coverage without a higher-priority blocker requires operator_action_state=recovery_required")
        if not _is_source_coverage_recovery(receipt):
            issues.append("degraded source_coverage without a higher-priority blocker requires source_coverage reason")
        expected_next_action = str(source_coverage.get("next_action") or "").strip()
        if expected_next_action and str(receipt.get("next_action") or "").strip() != expected_next_action:
            issues.append("degraded source_coverage without a higher-priority blocker requires receipt.next_action to match source_coverage.next_action")


def _verify_assistant_grade_packet(receipt: dict[str, Any], issues: list[str]) -> None:
    assistant_grade_packet = dict(receipt.get("assistant_grade_packet") or {})
    if not assistant_grade_packet:
        issues.append("assistant_grade_packet missing")
        return
    if "present" not in assistant_grade_packet:
        issues.append("assistant_grade_packet.present missing")
    privacy = dict(assistant_grade_packet.get("privacy") or {})
    for key in (
        "raw_packet_text_exposed",
        "raw_candidate_exposed",
        "raw_draft_text_exposed",
        "raw_private_link_exposed",
    ):
        if privacy.get(key) is not False:
            issues.append(f"assistant_grade_packet.privacy.{key} must remain false")
    requires_recovery = bool(assistant_grade_packet.get("requires_recovery"))
    if requires_recovery:
        if str(assistant_grade_packet.get("blocking_reason") or "").strip() != "internal_action_not_assistant_grade":
            issues.append("assistant_grade_packet recovery requires blocking_reason=internal_action_not_assistant_grade")
        if str(assistant_grade_packet.get("next_action") or "").strip() != "stage_fresh_assistant_grade_proactive_packet":
            issues.append("assistant_grade_packet recovery requires next_action=stage_fresh_assistant_grade_proactive_packet")
        stage_kind = str(assistant_grade_packet.get("stage_kind") or "").strip().lower()
        work_type = str(assistant_grade_packet.get("work_type") or "").strip().lower()
        if stage_kind not in ASSISTANT_GRADE_BLOCKING_WORK_TYPES and work_type not in ASSISTANT_GRADE_BLOCKING_WORK_TYPES:
            issues.append("assistant_grade_packet recovery requires an internal-action stage_kind or work_type")
        if str(receipt.get("status") or "").strip() != "ready_with_recovery_action":
            issues.append("assistant_grade_packet recovery requires status=ready_with_recovery_action")
        if str(receipt.get("reason") or "").strip() != "internal_action_not_assistant_grade":
            issues.append("assistant_grade_packet recovery requires reason=internal_action_not_assistant_grade")
        if str(receipt.get("next_action") or "").strip() != "stage_fresh_assistant_grade_proactive_packet":
            issues.append("assistant_grade_packet recovery requires receipt.next_action=stage_fresh_assistant_grade_proactive_packet")
        if str(receipt.get("operator_action_state") or "").strip() != "recovery_required":
            issues.append("assistant_grade_packet recovery requires operator_action_state=recovery_required")
        if bool(dict(receipt.get("approval_capture_surface") or {}).get("ready")):
            issues.append("assistant_grade_packet recovery must not keep approval_capture_surface.ready=true")
        return
    if bool(assistant_grade_packet.get("present")):
        bundle_source = str(assistant_grade_packet.get("bundle_source") or "").strip()
        if bundle_source == "historical_browse_backed_proof_bundle":
            stage_packets = dict(receipt.get("stage_packets") or {})
            safe_work_results = dict(receipt.get("safe_work_results") or {})
            if bool(stage_packets.get("selected_packet_present")) is not True:
                issues.append(
                    "historical assistant_grade_packet requires stage_packets.selected_packet_present=true"
                )
            if str(stage_packets.get("selected_bundle_source") or "").strip() != bundle_source:
                issues.append(
                    "historical assistant_grade_packet requires stage_packets.selected_bundle_source=historical_browse_backed_proof_bundle"
                )
            if int(stage_packets.get("packet_count") or 0) <= 0:
                issues.append("historical assistant_grade_packet requires stage_packets.packet_count>0")
            if bool(safe_work_results.get("selected_result_present")) is not True:
                issues.append(
                    "historical assistant_grade_packet requires safe_work_results.selected_result_present=true"
                )
            if str(safe_work_results.get("selected_bundle_source") or "").strip() != bundle_source:
                issues.append(
                    "historical assistant_grade_packet requires safe_work_results.selected_bundle_source=historical_browse_backed_proof_bundle"
                )
            if int(safe_work_results.get("result_count") or 0) <= 0:
                issues.append("historical assistant_grade_packet requires safe_work_results.result_count>0")
    if str(assistant_grade_packet.get("next_action") or "").strip():
        issues.append("assistant_grade_packet without recovery must not request next_action")
    if str(assistant_grade_packet.get("blocking_reason") or "").strip():
        issues.append("assistant_grade_packet without recovery must not set blocking_reason")


def _verify_provider_cost_pressure(receipt: dict[str, Any], issues: list[str]) -> None:
    provider_cost = dict(receipt.get("provider_cost_pressure") or {})
    if not provider_cost:
        return
    if "checked" not in provider_cost:
        issues.append("provider_cost_pressure.checked missing")
    if "probe_ok" not in provider_cost:
        issues.append("provider_cost_pressure.probe_ok missing")
    status = str(provider_cost.get("status") or "").strip()
    if not status:
        issues.append("provider_cost_pressure.status missing")
    if bool(provider_cost.get("checked")) and status != "not_checked":
        if not str(provider_cost.get("source") or "").strip():
            issues.append("checked provider_cost_pressure requires source")
        if not str(provider_cost.get("observed_at") or "").strip():
            issues.append("checked provider_cost_pressure requires observed_at")
    privacy = dict(provider_cost.get("privacy") or {})
    for key in (
        "raw_prompt_or_response_text_exposed",
        "raw_provider_secret_exposed",
        "raw_google_cloud_billing_account_exposed",
        "raw_provider_slots_exposed",
    ):
        if privacy.get(key) is not False:
            issues.append(f"provider_cost_pressure.privacy.{key} must remain false")
    gemini = dict(provider_cost.get("gemini_token_tracking") or {})
    if provider_cost.get("gemini_provider_key") not in {"", "gemini_vortex"}:
        issues.append("provider_cost_pressure gemini_provider_key must remain gemini_vortex")
    if bool(provider_cost.get("checked")) and status in {"active_cost_control", "ready"}:
        cheap_expected_order = ["onemin", "magixai", "gemini_vortex"]
        hard_expected_order = ["onemin", "magixai", "gemini_vortex"]
        for key in ("provider_order", "fast_provider_order", "cheap_provider_order", "groundwork_provider_order"):
            if list(provider_cost.get(key) or [])[:3] != cheap_expected_order:
                issues.append(f"provider_cost_pressure {key} drifted")
        if list(provider_cost.get("hard_provider_order") or [])[:3] != hard_expected_order:
            issues.append("provider_cost_pressure hard_provider_order drifted")
        if provider_cost.get("onemin_preferred_whenever_usable") is not True:
            issues.append("provider_cost_pressure onemin_preferred_whenever_usable must remain true")
    if gemini:
        boundary = str(gemini.get("billing_truth_boundary") or "").strip()
        if bool(provider_cost.get("checked")) and boundary != "token_ledger_is_cost_pressure_telemetry_not_google_cloud_billing_truth":
            issues.append("provider_cost_pressure Gemini token tracking boundary missing")
        window_24h = dict(gemini.get("24h") or {})
        for key in ("tokens_in", "tokens_out", "total_tokens", "request_count"):
            if int(window_24h.get(key) or 0) < 0:
                issues.append(f"provider_cost_pressure Gemini 24h {key} must be non-negative")
    if _provider_cost_pressure_requires_recovery(receipt):
        if str(receipt.get("status") or "").strip() != "ready_with_recovery_action":
            issues.append("provider_cost_pressure recovery requires status=ready_with_recovery_action")
        if str(receipt.get("operator_action_state") or "").strip() != "recovery_required":
            issues.append("provider_cost_pressure recovery requires operator_action_state=recovery_required")
        if not str(receipt.get("reason") or "").strip().startswith("provider_cost_pressure_"):
            issues.append("provider_cost_pressure recovery requires provider_cost_pressure reason")
        if str(receipt.get("next_action") or "").strip() != "repair_provider_cost_routing":
            issues.append("provider_cost_pressure recovery requires next_action=repair_provider_cost_routing")


def _verify_onemin_direct_refresh_posture(receipt: dict[str, Any], issues: list[str]) -> None:
    posture = dict(receipt.get("onemin_direct_refresh_posture") or {})
    if not posture:
        issues.append("onemin_direct_refresh_posture missing")
        return
    if "checked" not in posture:
        issues.append("onemin_direct_refresh_posture.checked missing")
    if "probe_ok" not in posture:
        issues.append("onemin_direct_refresh_posture.probe_ok missing")
    status = str(posture.get("status") or "").strip()
    if not status:
        issues.append("onemin_direct_refresh_posture.status missing")
    if bool(posture.get("checked")):
        if not str(posture.get("source") or "").strip():
            issues.append("checked onemin_direct_refresh_posture requires source")
        if not str(posture.get("observed_at") or "").strip():
            issues.append("checked onemin_direct_refresh_posture requires observed_at")
        if not str(posture.get("receipt_name") or "").strip():
            issues.append("checked onemin_direct_refresh_posture requires receipt_name")
    if str(posture.get("next_action") or "").strip():
        if not str(posture.get("next_action_href") or "").strip():
            issues.append("onemin_direct_refresh_posture next_action requires next_action_href")
        if not str(posture.get("next_action_label") or "").strip():
            issues.append("onemin_direct_refresh_posture next_action requires next_action_label")
        if str(posture.get("next_action_method") or "").strip().lower() != "get":
            issues.append("onemin_direct_refresh_posture next_action requires next_action_method=get")
    controls = dict(posture.get("controls") or {})
    if int(controls.get("batch_size") or 0) < 1:
        issues.append("onemin_direct_refresh_posture controls.batch_size must be >=1")
    for key in ("batch_backoff_seconds", "max_rate_limit_sleep_seconds"):
        if float(controls.get(key) or 0.0) < 0.0:
            issues.append(f"onemin_direct_refresh_posture controls.{key} must be non-negative")
    if controls and str(controls.get("refresh_transport") or "").strip() != "direct_provider_api":
        issues.append("onemin_direct_refresh_posture controls.refresh_transport must remain direct_provider_api")
    if controls and str(controls.get("proxy_mode") or "").strip() != "direct_no_ui_proxy":
        issues.append("onemin_direct_refresh_posture controls.proxy_mode must remain direct_no_ui_proxy")
    telegram_delivery = dict(posture.get("telegram_delivery") or {})
    if "checked" not in telegram_delivery:
        issues.append("onemin_direct_refresh_posture.telegram_delivery.checked missing")
    if int(telegram_delivery.get("message_count") or 0) < 0:
        issues.append("onemin_direct_refresh_posture.telegram_delivery.message_count must be non-negative")
    if bool(telegram_delivery.get("sent")) and int(telegram_delivery.get("message_count") or 0) <= 0:
        issues.append("sent onemin_direct_refresh_posture.telegram_delivery requires message_count>0")
    privacy = dict(posture.get("privacy") or {})
    for key in (
        "raw_owner_email_exposed",
        "raw_login_secret_exposed",
        "raw_telegram_chat_ref_exposed",
    ):
        if privacy.get(key) is not False:
            issues.append(f"onemin_direct_refresh_posture.privacy.{key} must remain false")


def _verify_approval_capture(approval_capture: dict[str, Any], issues: list[str], *, required: bool) -> None:
    if not approval_capture:
        if required:
            issues.append("ready approval_capture_surface requires redacted approval_capture readiness proof")
        return
    privacy = dict(approval_capture.get("privacy") or {})
    for flag in (
        "raw_callback_token_exposed",
        "raw_principal_id_exposed",
        "raw_chat_ref_exposed",
        "raw_packet_ref_exposed",
        "raw_staged_artifact_ref_exposed",
    ):
        if bool(privacy.get(flag)):
            issues.append(f"approval_capture.privacy.{flag} must remain false")
    if not required:
        return
    if bool(approval_capture.get("checked")) is not True:
        issues.append("ready approval_capture_surface requires approval_capture.checked=true")
    if not str(approval_capture.get("source") or "").strip():
        issues.append("ready approval_capture_surface requires approval_capture.source")
    if not str(approval_capture.get("observed_at") or "").strip():
        issues.append("ready approval_capture_surface requires approval_capture.observed_at")
    if bool(approval_capture.get("ready")) is not True:
        if not str(approval_capture.get("blocking_reason") or "").strip():
            issues.append("blocked approval_capture requires blocking_reason")
        if not str(approval_capture.get("next_action") or "").strip():
            issues.append("blocked approval_capture requires next_action")
        return
    if bool(approval_capture.get("probe_ok")) is not True:
        issues.append("ready approval_capture_surface requires approval_capture.probe_ok=true")
    if str(approval_capture.get("status") or "").strip() != "ready":
        issues.append("ready approval_capture_surface requires approval_capture.status=ready")
    if bool(approval_capture.get("current_packet_refs_present")) is not True:
        issues.append("ready approval_capture_surface requires approval_capture.current_packet_refs_present=true")
    if int(approval_capture.get("current_packet_callback_record_count") or 0) <= 0:
        issues.append("ready approval_capture_surface requires approval_capture.current_packet_callback_record_count>0")
    if int(approval_capture.get("current_packet_live_pending_count") or 0) != 1:
        issues.append("ready approval_capture_surface requires approval_capture.current_packet_live_pending_count=1")
    if str(approval_capture.get("current_packet_callback_latest_status") or "").strip() != "pending":
        issues.append("ready approval_capture_surface requires approval_capture.current_packet_callback_latest_status=pending")
    if bool(approval_capture.get("callback_principal_hash_present")) is not True:
        issues.append("ready approval_capture_surface requires approval_capture.callback_principal_hash_present=true")
    if int(approval_capture.get("candidate_principal_hash_count") or 0) <= 0:
        issues.append("ready approval_capture_surface requires approval_capture.candidate_principal_hash_count>0")
    if bool(approval_capture.get("principal_match_ready")) is not True:
        issues.append("ready approval_capture_surface requires approval_capture.principal_match_ready=true")
    if bool(approval_capture.get("telegram_binding_ready")) is not True:
        issues.append("ready approval_capture_surface requires approval_capture.telegram_binding_ready=true")
    if bool(approval_capture.get("telegram_chat_ref_present")) is not True:
        issues.append("ready approval_capture_surface requires approval_capture.telegram_chat_ref_present=true")
    if bool(approval_capture.get("telegram_bot_token_present")) is not True:
        issues.append("ready approval_capture_surface requires approval_capture.telegram_bot_token_present=true")


def _json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _git_head(path: Path = ROOT) -> str:
    return resolve_source_state_head(path)


def _source_fingerprint(path: Path = ROOT) -> str:
    return resolve_source_worktree_fingerprint(path)


def _verify_safe_work_audit(receipt: dict[str, Any], issues: list[str]) -> None:
    safe_work_audit = dict(receipt.get("safe_work_audit") or {})
    if not safe_work_audit:
        issues.append("safe_work_audit missing")
        return
    if "present" not in safe_work_audit:
        issues.append("safe_work_audit.present missing")
    privacy = dict(safe_work_audit.get("privacy") or {})
    for key in (
        "raw_issue_details_exposed",
        "raw_candidate_exposed",
        "raw_draft_text_exposed",
        "raw_private_link_exposed",
    ):
        if privacy.get(key) is not False:
            issues.append(f"safe_work_audit.privacy.{key} must remain false")
    if not bool(safe_work_audit.get("present")):
        return
    if not str(safe_work_audit.get("result_status") or "").strip():
        issues.append("present safe_work_audit requires result_status")
    if "audit_present" not in safe_work_audit:
        issues.append("present safe_work_audit requires audit_present")
    if not str(safe_work_audit.get("audit_status") or "").strip():
        issues.append("present safe_work_audit requires audit_status")
    delivery_allowed = bool(safe_work_audit.get("delivery_allowed"))
    audit_passed = bool(safe_work_audit.get("audit_passed"))
    browser_handoff = bool(safe_work_audit.get("browser_handoff_user_action_required"))
    if delivery_allowed and not (audit_passed or browser_handoff):
        issues.append("safe_work_audit.delivery_allowed requires audit_passed or browser handoff")
    if delivery_allowed:
        return
    if (
        str(safe_work_audit.get("audit_status") or "").strip() == "filtered"
        and bool(safe_work_audit.get("filtered_non_material"))
        and safe_work_audit.get("issue_codes")
    ):
        if bool(safe_work_audit.get("blocks_operator_followthrough")):
            issues.append("filtered non-material safe_work_audit must not block operator followthrough")
        if str(safe_work_audit.get("next_action") or "").strip():
            issues.append("filtered non-material safe_work_audit must not request recovery next_action")
        if str(safe_work_audit.get("blocking_reason") or "").strip():
            issues.append("filtered non-material safe_work_audit must not set blocking_reason")
        return
    if bool(safe_work_audit.get("blocks_operator_followthrough")) is not True:
        issues.append("non-deliverable safe_work_audit requires blocks_operator_followthrough=true")
    if str(receipt.get("status") or "").strip() != "blocked_local_runtime":
        issues.append("non-deliverable safe_work_audit requires status=blocked_local_runtime")
    if str(receipt.get("next_action") or "").strip() != "repair_proactive_safe_work_audit":
        issues.append("non-deliverable safe_work_audit requires next_action=repair_proactive_safe_work_audit")
    if str(receipt.get("operator_action_state") or "").strip() != "recovery_required":
        issues.append("non-deliverable safe_work_audit requires operator_action_state=recovery_required")
    if not str(safe_work_audit.get("blocking_reason") or "").strip():
        issues.append("non-deliverable safe_work_audit requires blocking_reason")


def _verify_browser_handoff(receipt: dict[str, Any], issues: list[str]) -> None:
    browser_handoff = dict(receipt.get("browser_handoff") or {})
    if not browser_handoff:
        issues.append("browser_handoff missing")
        return
    if "present" not in browser_handoff:
        issues.append("browser_handoff.present missing")
    privacy = dict(browser_handoff.get("privacy") or {})
    for key in ("raw_credentials_stored", "raw_cookie_or_session_stored", "raw_browser_artifact_stored"):
        if privacy.get(key) is not False:
            issues.append(f"browser_handoff.privacy.{key} must remain false")
    if not bool(browser_handoff.get("present")):
        if bool(browser_handoff.get("required")):
            issues.append("browser_handoff.required must be false when browser_handoff.present=false")
        return
    if not str(browser_handoff.get("blocker_code") or "").strip():
        issues.append("present browser_handoff requires blocker_code")
    challenge = dict(browser_handoff.get("challenge") or {})
    if not challenge:
        issues.append("present browser_handoff requires challenge")
        challenge = {}
    if challenge.get("raw_destination_stored") is not False:
        issues.append("browser_handoff.challenge.raw_destination_stored must remain false")
    safe_work_audit = dict(receipt.get("safe_work_audit") or {})
    if bool(safe_work_audit.get("browser_handoff_user_action_required")) and not bool(browser_handoff.get("required")):
        issues.append("safe_work_audit browser_handoff_user_action_required requires browser_handoff.required=true")
    if not bool(browser_handoff.get("required")):
        return
    if str(receipt.get("status") or "").strip() != "ready_with_recovery_action":
        issues.append("required browser_handoff requires status=ready_with_recovery_action")
    if str(receipt.get("reason") or "").strip() != "browser_handoff_required":
        issues.append("required browser_handoff requires reason=browser_handoff_required")
    expected_next_action = str(browser_handoff.get("next_action") or "").strip()
    if expected_next_action != "complete_browser_handoff_then_resume_ooda_task":
        issues.append("required browser_handoff requires next_action=complete_browser_handoff_then_resume_ooda_task")
    if str(receipt.get("next_action") or "").strip() != expected_next_action:
        issues.append("required browser_handoff requires receipt.next_action to match browser_handoff.next_action")
    if str(receipt.get("operator_action_state") or "").strip() != "recovery_required":
        issues.append("required browser_handoff requires operator_action_state=recovery_required")
    delivery_guard = dict(receipt.get("delivery_guard") or {})
    if str(delivery_guard.get("delivery_state") or "").strip() != "browser_handoff_pending":
        issues.append("required browser_handoff requires delivery_guard.delivery_state=browser_handoff_pending")
    if delivery_guard.get("user_action_required") is not True:
        issues.append("required browser_handoff requires delivery_guard.user_action_required=true")
    if not str(browser_handoff.get("resume_instruction") or "").strip():
        issues.append("required browser_handoff requires resume_instruction")
    blocker_code = str(browser_handoff.get("blocker_code") or "").strip()
    available_channels = [
        str(item).strip()
        for item in list(challenge.get("available_channels") or [])
        if str(item).strip()
    ]
    if blocker_code in {"mfa_code_required", "otp_required"}:
        if not available_channels:
            issues.append("OTP browser_handoff requires challenge.available_channels")
        if not str(challenge.get("operator_instruction") or "").strip():
            issues.append("OTP browser_handoff requires challenge.operator_instruction")


def _verify_suppressed_projection(receipt: dict[str, Any], issues: list[str]) -> None:
    suppressed = dict(receipt.get("suppressed_projection") or {})
    if not suppressed:
        issues.append("suppressed_projection missing")
        return
    privacy = dict(suppressed.get("privacy") or {})
    for key in (
        "raw_packet_text_exposed",
        "raw_candidate_exposed",
        "raw_draft_text_exposed",
        "raw_private_link_exposed",
    ):
        if privacy.get(key) is not False:
            issues.append(f"suppressed_projection.privacy.{key} must remain false")
    present = bool(suppressed.get("present"))
    requires_recovery = bool(suppressed.get("requires_recovery"))
    if not present:
        if requires_recovery:
            issues.append("unobserved suppressed_projection must not require recovery")
        return
    status = str(suppressed.get("status") or "").strip()
    if requires_recovery:
        if status != "suppressed":
            issues.append("suppressed_projection recovery requires status=suppressed")
        if int(suppressed.get("suppressed_item_count") or 0) <= 0:
            issues.append("suppressed_projection recovery requires suppressed_item_count>0")
        if not str(suppressed.get("blocking_reason") or "").strip():
            issues.append("suppressed_projection recovery requires blocking_reason")
        if str(suppressed.get("next_action") or "").strip() != "repair_proactive_safe_work_audit":
            issues.append("suppressed_projection recovery requires next_action=repair_proactive_safe_work_audit")
        if str(receipt.get("status") or "").strip() != "ready_with_recovery_action":
            issues.append("suppressed_projection recovery requires status=ready_with_recovery_action")
        if str(receipt.get("next_action") or "").strip() != "repair_proactive_safe_work_audit":
            issues.append("suppressed_projection recovery requires receipt.next_action=repair_proactive_safe_work_audit")
        if str(receipt.get("operator_action_state") or "").strip() != "recovery_required":
            issues.append("suppressed_projection recovery requires operator_action_state=recovery_required")
        return
    suppressed_count = int(suppressed.get("suppressed_item_count") or 0)
    if suppressed_count > 0:
        issue_codes = [
            str(item or "").strip()
            for item in list(suppressed.get("suppressed_safe_work_issue_codes") or [])
            if str(item or "").strip()
        ]
        reasons = [
            str(item or "").strip()
            for item in list(suppressed.get("suppressed_projection_reasons") or [])
            if str(item or "").strip()
        ]
        if status != "suppressed_non_material":
            issues.append("non-material suppressed_projection requires status=suppressed_non_material")
        if suppressed.get("suppressed_non_material") is not True:
            issues.append("non-material suppressed_projection requires suppressed_non_material=true")
        non_material_reason = str(suppressed.get("suppressed_non_material_reason") or "").strip()
        if non_material_reason not in {
            "quiet_no_decision_ready_material",
            "configured_source_exclusion",
            "mixed_delivery_non_material",
        }:
            issues.append("non-material suppressed_projection requires a recognized non-material reason")
        if non_material_reason == "quiet_no_decision_ready_material":
            if str(suppressed.get("notification_status") or "").strip() != "deferred":
                issues.append("quiet non-material suppressed_projection requires deferred notification_status")
            if str(suppressed.get("error_code") or "").strip() not in QUIET_NON_MATERIAL_SUPPRESSED_PROJECTION_ERROR_CODES:
                issues.append(
                    "quiet non-material suppressed_projection requires no_user_action_required or no_decision_ready_safe_work error_code"
                )
        if non_material_reason == "mixed_delivery_non_material":
            if str(suppressed.get("notification_status") or "").strip() != "sent":
                issues.append("mixed-delivery non-material suppressed_projection requires sent notification_status")
            if int(suppressed.get("packet_projection_record_count") or 0) <= 0:
                issues.append("mixed-delivery non-material suppressed_projection requires projected packet records")
            if int(suppressed.get("item_count") or 0) <= int(suppressed.get("packet_projection_record_count") or 0):
                issues.append("mixed-delivery non-material suppressed_projection requires suppressed siblings beyond projected records")
        if non_material_reason == "configured_source_exclusion":
            if any(code not in CONFIGURED_SOURCE_EXCLUSION_REASONS for code in issue_codes):
                issues.append("configured-source-exclusion suppressed_projection contains non-exclusion issue code")
            if any(reason not in CONFIGURED_SOURCE_EXCLUSION_REASONS for reason in reasons):
                issues.append("configured-source-exclusion suppressed_projection contains non-exclusion reason")
        if not issue_codes:
            issues.append("non-material suppressed_projection requires issue codes")
        elif any(code not in NON_MATERIAL_SUPPRESSED_PROJECTION_ISSUE_CODES for code in issue_codes):
            issues.append("non-material suppressed_projection contains recovery issue code")
        if any(reason not in NON_MATERIAL_SUPPRESSED_PROJECTION_REASONS for reason in reasons):
            issues.append("non-material suppressed_projection contains recovery reason")
        if str(suppressed.get("blocking_reason") or "").strip():
            issues.append("non-material suppressed_projection must not set blocking_reason")
        if str(suppressed.get("next_action") or "").strip():
            issues.append("non-material suppressed_projection must not request next_action")
        return
    if status == "suppressed":
        issues.append("suppressed_projection status=suppressed requires requires_recovery=true")


def _verify_current_artifact_filter(receipt: dict[str, Any], issues: list[str]) -> None:
    filtered = dict(receipt.get("current_artifact_filter") or {})
    if not filtered:
        return
    privacy = dict(filtered.get("privacy") or {})
    for key in (
        "raw_packet_text_exposed",
        "raw_candidate_exposed",
        "raw_draft_text_exposed",
        "raw_private_link_exposed",
    ):
        if privacy.get(key) is not False:
            issues.append(f"current_artifact_filter.privacy.{key} must remain false")
    if not bool(filtered.get("present")):
        if bool(filtered.get("requires_recovery")):
            issues.append("absent current_artifact_filter must not require recovery")
        return
    if not str(filtered.get("reason") or "").strip():
        issues.append("present current_artifact_filter requires reason")
    if bool(filtered.get("requires_recovery")):
        if not str(filtered.get("blocking_reason") or "").strip():
            issues.append("current_artifact_filter recovery requires blocking_reason")
        if str(filtered.get("next_action") or "").strip() != "repair_proactive_safe_work_audit":
            issues.append("current_artifact_filter recovery requires next_action=repair_proactive_safe_work_audit")
        if str(receipt.get("status") or "").strip() != "blocked_local_runtime":
            issues.append("current_artifact_filter recovery requires status=blocked_local_runtime")
        if str(receipt.get("next_action") or "").strip() != "repair_proactive_safe_work_audit":
            issues.append("current_artifact_filter recovery requires receipt.next_action=repair_proactive_safe_work_audit")
        if str(receipt.get("operator_action_state") or "").strip() != "recovery_required":
            issues.append("current_artifact_filter recovery requires operator_action_state=recovery_required")
    elif str(filtered.get("next_action") or "").strip():
        issues.append("current_artifact_filter without recovery must not request next_action")


def verify(path: Path = DEFAULT_RECEIPT, *, root: Path = ROOT) -> list[str]:
    issues: list[str] = []
    receipt = _json(path)
    if not receipt:
        return [f"proactive OODA operator status missing or invalid: {path}"]

    if receipt.get("contract_name") != "ea.proactive_ooda_operator_status.v1":
        issues.append("contract_name must be ea.proactive_ooda_operator_status.v1")
    if receipt.get("generated_by") != "scripts/materialize_proactive_ooda_operator_status.py":
        issues.append("generated_by must point at the proactive OODA operator-status materializer")
    if receipt.get("head_semantics") != "source_state":
        issues.append("head_semantics must remain source_state")
    if receipt.get("source_state_fingerprint_semantics") != "worktree_source_files_sha256_excluding_generated_only_paths":
        issues.append("source_state_fingerprint_semantics must describe the source worktree fingerprint")

    current_head = _git_head(root)
    recorded_head = str(receipt.get("source_git_head") or "").strip()
    current_fingerprint = _source_fingerprint(root)
    recorded_fingerprint = str(receipt.get("source_state_fingerprint") or "").strip()
    fingerprint_matches = bool(current_fingerprint and recorded_fingerprint and current_fingerprint == recorded_fingerprint)
    if not recorded_head:
        issues.append("source_git_head missing")
    elif current_head and recorded_head != current_head and not fingerprint_matches:
        issues.append("receipt is stale relative to current source HEAD")
    if not recorded_fingerprint:
        issues.append("source_state_fingerprint missing")
    elif current_fingerprint and recorded_fingerprint != current_fingerprint:
        issues.append("receipt is stale relative to current source fingerprint")

    status = str(receipt.get("status") or "").strip()
    if status not in KNOWN_STATUSES:
        issues.append(f"status must stay within known proactive OODA operator states: {status or 'missing'}")
    if not str(receipt.get("next_action") or "").strip():
        issues.append("next_action must be present")
    _verify_next_action_surface(receipt, issues)
    if not str(receipt.get("summary") or "").strip():
        issues.append("summary must be present")
    if receipt.get("goal_completion_claim_allowed") is not False:
        issues.append("goal_completion_claim_allowed must remain false")
    if receipt.get("live_delivery_claim_allowed") is not False:
        issues.append("live_delivery_claim_allowed must remain false")
    route_probe_source = str(receipt.get("route_probe_source") or "").strip()
    if not route_probe_source:
        issues.append("route_probe_source must be present")
    if route_probe_source == "docker_compose_exec":
        if not str(receipt.get("route_probe_runtime_service") or "").strip():
            issues.append("docker_compose_exec route probes require route_probe_runtime_service")
        if not str(receipt.get("route_probe_observed_at") or "").strip():
            issues.append("docker_compose_exec route probes require route_probe_observed_at")

    rules = set(str(item).strip() for item in list(receipt.get("rules") or []) if str(item).strip())
    if rules != EXPECTED_RULES:
        issues.append("rules drifted")

    delivery_route = dict(receipt.get("delivery_route") or {})
    if "ready" not in delivery_route:
        issues.append("delivery_route.ready missing")
    if "route_error" not in delivery_route:
        issues.append("delivery_route.route_error missing")
    if "next_action" not in delivery_route:
        issues.append("delivery_route.next_action missing")

    delivery_guard = dict(receipt.get("delivery_guard") or {})
    if "delivery_state" not in delivery_guard:
        issues.append("delivery_guard.delivery_state missing")

    stage_packets = dict(receipt.get("stage_packets") or {})
    safe_work_results = dict(receipt.get("safe_work_results") or {})
    if "ready" not in stage_packets:
        issues.append("stage_packets.ready missing")
    if "ready" not in safe_work_results:
        issues.append("safe_work_results.ready missing")
    _verify_safe_work_audit(receipt, issues)
    _verify_browser_handoff(receipt, issues)
    _verify_current_artifact_filter(receipt, issues)
    _verify_assistant_grade_packet(receipt, issues)
    _verify_suppressed_projection(receipt, issues)
    _verify_provider_cost_pressure(receipt, issues)
    _verify_onemin_direct_refresh_posture(receipt, issues)

    gmail_draft_followthrough = dict(receipt.get("gmail_draft_followthrough") or {})
    if "checked" not in gmail_draft_followthrough:
        issues.append("gmail_draft_followthrough.checked missing")
    if not str(gmail_draft_followthrough.get("status") or "").strip():
        issues.append("gmail_draft_followthrough.status missing")
    if gmail_draft_followthrough.get("raw_execution_payload_exposed") is not False:
        issues.append("gmail_draft_followthrough.raw_execution_payload_exposed must remain false")
    gmail_status = str(gmail_draft_followthrough.get("status") or "").strip()
    if gmail_status == "already_executed":
        if str(gmail_draft_followthrough.get("action") or "").strip() != "save_gmail_draft":
            issues.append("already_executed gmail_draft_followthrough requires action=save_gmail_draft")
        if str(gmail_draft_followthrough.get("execution_status") or "").strip() != "executed":
            issues.append("already_executed gmail_draft_followthrough requires execution_status=executed")
        if gmail_draft_followthrough.get("execution_observation_present") is not True:
            issues.append("already_executed gmail_draft_followthrough requires execution_observation_present=true")
        if gmail_draft_followthrough.get("gmail_draft_id_hash_present") is not True:
            issues.append("already_executed gmail_draft_followthrough requires gmail_draft_id_hash_present=true")
    if gmail_status in {"no_pending_draft", "pending_google_reauth", "pending_execution", "blocked", "probe_failed"}:
        if not str(gmail_draft_followthrough.get("next_action") or "").strip():
            issues.append(f"{gmail_status} gmail_draft_followthrough requires next_action")
    _verify_next_action_surface(gmail_draft_followthrough, issues)
    _verify_source_coverage(receipt, issues)

    live_receipt_checked = bool(receipt.get("live_receipt_checked"))
    live_receipt = dict(receipt.get("live_receipt") or {})
    if live_receipt_checked:
        if "ok" not in live_receipt:
            issues.append("live_receipt.ok missing when live receipt is checked")
        if not str(live_receipt.get("receipt_path") or "").strip():
            issues.append("live_receipt.receipt_path missing when live receipt is checked")
    if status == "ready_with_live_receipt" and not bool(live_receipt.get("ok")):
        issues.append("ready_with_live_receipt status requires live_receipt.ok=true")
    if (
        status == "ready_with_recovery_action"
        and not str(receipt.get("delivery_route_error") or "").strip()
        and not _is_google_workspace_recovery(receipt)
        and not _is_browser_handoff_recovery(receipt)
        and not _is_assistant_grade_packet_recovery(receipt)
        and not _is_source_coverage_recovery(receipt)
        and not _is_followthrough_recovery(receipt)
        and not _is_suppressed_projection_recovery(receipt)
        and not _provider_cost_pressure_requires_recovery(receipt)
    ):
        issues.append("ready_with_recovery_action requires delivery_route_error")
    if status == "blocked_delivery_route" and bool(receipt.get("delivery_route_ready")):
        issues.append("blocked_delivery_route must not claim delivery_route_ready=true")
    if status == "deferred" and str(delivery_guard.get("delivery_state") or "").strip() != "deferred":
        issues.append("deferred status requires delivery_guard.delivery_state=deferred")

    approval_capture_surface = dict(receipt.get("approval_capture_surface") or {})
    approval_capture = dict(receipt.get("approval_capture") or {})
    if approval_capture_surface:
        callback_hygiene_ready = bool(approval_capture_surface.get("callback_hygiene_ready", True))
        callback_hygiene_blocking_reason = str(
            approval_capture_surface.get("callback_hygiene_blocking_reason") or ""
        ).strip()
        callback_hygiene_next_action = str(
            approval_capture_surface.get("callback_hygiene_next_action") or ""
        ).strip()
        if callback_hygiene_ready:
            if int(approval_capture_surface.get("callback_noncurrent_pending_count") or 0) != 0:
                issues.append("ready approval_capture_surface requires callback_noncurrent_pending_count=0")
            if int(approval_capture_surface.get("callback_stale_pending_count") or 0) != 0:
                issues.append("ready approval_capture_surface requires callback_stale_pending_count=0")
            if int(approval_capture_surface.get("current_packet_callback_stale_pending_count") or 0) != 0:
                issues.append("ready approval_capture_surface requires current_packet_callback_stale_pending_count=0")
            if int(approval_capture_surface.get("current_packet_duplicate_live_pending_count") or 0) != 0:
                issues.append("ready approval_capture_surface requires current_packet_duplicate_live_pending_count=0")
        else:
            if not callback_hygiene_blocking_reason:
                issues.append("approval_capture_surface callback_hygiene_ready=false requires callback_hygiene_blocking_reason")
            if not callback_hygiene_next_action:
                issues.append("approval_capture_surface callback_hygiene_ready=false requires callback_hygiene_next_action")
            if status != "blocked_local_runtime":
                issues.append("approval_capture_surface callback_hygiene_ready=false requires status=blocked_local_runtime")
        approval_capture_ready = bool(approval_capture.get("ready"))
        live_pending_count = int(approval_capture_surface.get("current_packet_live_pending_count") or 0)
        telegram_capture_ready = bool(approval_capture_surface.get("telegram_approval_surface_ready"))
        manual_capture_ready = bool(approval_capture_surface.get("manual_outcome_capture_ready"))
        approval_capture_required = bool(approval_capture_surface.get("ready")) and not (
            manual_capture_ready and not telegram_capture_ready
        )
        if bool(approval_capture_surface.get("ready")):
            if str(approval_capture_surface.get("selected_channel") or "").strip() != "telegram":
                issues.append("ready approval_capture_surface requires selected_channel=telegram")
            if not bool(approval_capture_surface.get("callback_dir_writable")):
                issues.append("ready approval_capture_surface requires callback_dir_writable=true")
            if not str(approval_capture_surface.get("approval_outcome_path") or "").strip():
                issues.append("ready approval_capture_surface requires approval_outcome_path")
            if not str(approval_capture_surface.get("callback_dir") or "").strip():
                issues.append("ready approval_capture_surface requires callback_dir")
            if not telegram_capture_ready and not manual_capture_ready:
                issues.append("ready approval_capture_surface requires live callback or manual_outcome_capture_ready")
            if telegram_capture_ready and live_pending_count != 1:
                issues.append("ready approval_capture_surface requires current_packet_live_pending_count=1")
            if manual_capture_ready:
                if not bool(approval_capture_surface.get("current_packet_approval_request_recordable")):
                    issues.append("manual approval_capture_surface requires current_packet_approval_request_recordable=true")
                if bool(approval_capture_surface.get("approval_outcome_matches_current_packet")):
                    issues.append("manual approval_capture_surface requires missing current approval outcome")
            if status == "ready_with_live_receipt" and (approval_capture_ready or manual_capture_ready):
                expected_next_action = (
                    "record_proactive_ooda_approval_outcome"
                    if manual_capture_ready and not telegram_capture_ready
                    else "tap_proactive_telegram_approval_button_or_record_proactive_ooda_approval_outcome"
                )
                if str(receipt.get("next_action") or "").strip() != expected_next_action:
                    issues.append(
                        "ready approval_capture_surface with ready_with_live_receipt requires approval-capture next_action"
                    )
                if str(receipt.get("operator_action_state") or "").strip() != "approval_capture_pending":
                    issues.append("ready approval_capture_surface with ready_with_live_receipt requires operator_action_state=approval_capture_pending")
                if str(delivery_guard.get("delivery_state") or "").strip() != "approval_capture_pending":
                    issues.append("ready approval_capture_surface with ready_with_live_receipt requires delivery_guard.delivery_state=approval_capture_pending")
                if delivery_guard.get("user_action_required") is not True:
                    issues.append("ready approval_capture_surface with ready_with_live_receipt requires delivery_guard.user_action_required=true")
                required_actionable_count = live_pending_count if telegram_capture_ready else 1 if manual_capture_ready else 0
                if int(receipt.get("actionable_count") or 0) < required_actionable_count:
                    issues.append("ready approval_capture_surface with ready_with_live_receipt requires actionable_count to include pending approval surfaces")
            if status == "ready_with_live_receipt" and approval_capture_required and approval_capture and not approval_capture_ready:
                expected_next_action = str(approval_capture.get("next_action") or "").strip()
                if expected_next_action and str(receipt.get("next_action") or "").strip() != expected_next_action:
                    issues.append("blocked approval_capture requires receipt.next_action to match approval_capture.next_action")
                if str(receipt.get("operator_action_state") or "").strip() != "recovery_required":
                    issues.append("blocked approval_capture with ready_with_live_receipt requires operator_action_state=recovery_required")
        _verify_approval_capture(approval_capture, issues, required=approval_capture_required)
    elif approval_capture:
        _verify_approval_capture(approval_capture, issues, required=False)

    commands = [str(item).strip() for item in list(receipt.get("verifier_commands") or []) if str(item).strip()]
    for expected in (
        "make verify-proactive-ooda",
        "make verify-proactive-ooda-live-receipt",
        "make verify-proactive-ooda-operator-status",
    ):
        if expected not in commands:
            issues.append(f"verifier_commands missing: {expected}")

    remaining = [str(item).strip() for item in list(receipt.get("remaining_external_proofs") or []) if str(item).strip()]
    if EXPECTED_REMAINING_PROOF not in remaining:
        issues.append("remaining_external_proofs must keep the proactive OODA routed-delivery proof")
    return issues


def main() -> int:
    if any(flag in __import__("sys").argv[1:] for flag in ("--help", "-h")):
        print(
            "Usage:\n"
            "  python scripts/verify_proactive_ooda_operator_status.py [options]\n\n"
            "Verify the proactive OODA operator-status receipt."
        )
        return 0
    parser = argparse.ArgumentParser(description="Verify the proactive OODA operator-status receipt.")
    parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    issues = verify(args.receipt)
    payload = {"status": "pass" if not issues else "blocked", "issues": issues}
    if args.pretty:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(json.dumps(payload))
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
