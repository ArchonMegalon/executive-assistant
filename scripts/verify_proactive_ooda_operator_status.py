#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from scripts.source_state_head import resolve_source_state_head
    from scripts.source_state_head import resolve_source_worktree_fingerprint
except ModuleNotFoundError:  # pragma: no cover - script execution path
    from source_state_head import resolve_source_state_head
    from source_state_head import resolve_source_worktree_fingerprint


ROOT = Path(__file__).resolve().parents[1]
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
KNOWN_STATUSES = {
    "blocked_delivery_route",
    "blocked_local_runtime",
    "deferred",
    "ready_local_runtime",
    "ready_with_live_receipt",
    "ready_with_recovery_action",
}


def _is_google_workspace_recovery(receipt: dict[str, Any]) -> bool:
    reason = str(receipt.get("reason") or "").strip()
    if reason.startswith("google_workspace_signal_source_unhealthy:"):
        return True
    return False


def _verify_next_action_surface(receipt: dict[str, Any], issues: list[str]) -> None:
    next_action = str(receipt.get("next_action") or "").strip()
    if next_action == "maintain_proactive_ooda_runtime":
        href = str(receipt.get("next_action_href") or "").strip()
        label = str(receipt.get("next_action_label") or "").strip()
        method = str(receipt.get("next_action_method") or "").strip().lower()
        if not href:
            issues.append("maintain_proactive_ooda_runtime requires next_action_href")
        elif "/app/today" not in href:
            issues.append("maintain_proactive_ooda_runtime next_action_href must target Today")
        if not label:
            issues.append("maintain_proactive_ooda_runtime requires next_action_label")
        if method != "get":
            issues.append("maintain_proactive_ooda_runtime requires next_action_method=get")
        return
    if next_action != "reauthorize_google_workspace_binding":
        return
    href = str(receipt.get("next_action_href") or "").strip()
    label = str(receipt.get("next_action_label") or "").strip()
    method = str(receipt.get("next_action_method") or "").strip().lower()
    if not href:
        issues.append("reauthorize_google_workspace_binding requires next_action_href")
    elif "/app/actions/google/connect?" not in href:
        issues.append("reauthorize_google_workspace_binding next_action_href must target the Google connect action")
    if not label:
        issues.append("reauthorize_google_workspace_binding requires next_action_label")
    if method != "get":
        issues.append("reauthorize_google_workspace_binding requires next_action_method=get")


def _verify_source_coverage(receipt: dict[str, Any], issues: list[str]) -> None:
    source_coverage = dict(receipt.get("source_coverage") or {})
    if not source_coverage:
        issues.append("source_coverage missing")
        return
    if "checked" not in source_coverage:
        issues.append("source_coverage.checked missing")
    if not str(source_coverage.get("status") or "").strip():
        issues.append("source_coverage.status missing")
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
    if "pocket_recording_archive_indexed" not in required_event_types:
        issues.append("pocket_ai_audio_transcripts lane must require pocket_recording_archive_indexed evidence")
    evidence_event_types = {
        str(item).strip()
        for item in list(pocket_lane.get("evidence_event_types") or [])
        if str(item).strip()
    }
    missing_required_event_types = {
        str(item).strip()
        for item in list(pocket_lane.get("missing_required_event_types") or [])
        if str(item).strip()
    }
    if bool(pocket_lane.get("observed")):
        if pocket_lane.get("required_event_type_observed") is not True:
            issues.append("observed pocket_ai_audio_transcripts lane must set required_event_type_observed=true")
        if "pocket_recording_archive_indexed" not in evidence_event_types:
            issues.append("observed pocket_ai_audio_transcripts lane must include pocket_recording_archive_indexed evidence")
    else:
        if "pocket_recording_archive_indexed" not in missing_required_event_types:
            issues.append("unobserved pocket_ai_audio_transcripts lane must surface missing pocket_recording_archive_indexed")
        if str(pocket_lane.get("next_action") or "").strip() != "sync_pocket_ai_audio_transcripts":
            issues.append("unobserved pocket_ai_audio_transcripts lane must request sync_pocket_ai_audio_transcripts")


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
    if int(approval_capture.get("current_packet_live_pending_count") or 0) <= 0:
        issues.append("ready approval_capture_surface requires approval_capture.current_packet_live_pending_count>0")
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
    if status == "ready_with_recovery_action" and not str(receipt.get("delivery_route_error") or "").strip() and not _is_google_workspace_recovery(
        receipt
    ):
        issues.append("ready_with_recovery_action requires delivery_route_error")
    if status == "blocked_delivery_route" and bool(receipt.get("delivery_route_ready")):
        issues.append("blocked_delivery_route must not claim delivery_route_ready=true")
    if status == "deferred" and str(delivery_guard.get("delivery_state") or "").strip() != "deferred":
        issues.append("deferred status requires delivery_guard.delivery_state=deferred")

    approval_capture_surface = dict(receipt.get("approval_capture_surface") or {})
    approval_capture = dict(receipt.get("approval_capture") or {})
    if approval_capture_surface:
        approval_capture_required = bool(approval_capture_surface.get("ready"))
        approval_capture_ready = bool(approval_capture.get("ready"))
        if bool(approval_capture_surface.get("ready")):
            if str(approval_capture_surface.get("selected_channel") or "").strip() != "telegram":
                issues.append("ready approval_capture_surface requires selected_channel=telegram")
            if not bool(approval_capture_surface.get("callback_dir_writable")):
                issues.append("ready approval_capture_surface requires callback_dir_writable=true")
            if not str(approval_capture_surface.get("approval_outcome_path") or "").strip():
                issues.append("ready approval_capture_surface requires approval_outcome_path")
            if not str(approval_capture_surface.get("callback_dir") or "").strip():
                issues.append("ready approval_capture_surface requires callback_dir")
            if int(approval_capture_surface.get("current_packet_live_pending_count") or 0) <= 0:
                issues.append("ready approval_capture_surface requires current_packet_live_pending_count>0")
            if status == "ready_with_live_receipt" and approval_capture_ready:
                if str(receipt.get("next_action") or "").strip() != "tap_proactive_telegram_approval_button_or_record_proactive_ooda_approval_outcome":
                    issues.append("ready approval_capture_surface with ready_with_live_receipt requires approval-capture next_action")
                if str(receipt.get("operator_action_state") or "").strip() != "approval_capture_pending":
                    issues.append("ready approval_capture_surface with ready_with_live_receipt requires operator_action_state=approval_capture_pending")
                if str(delivery_guard.get("delivery_state") or "").strip() != "approval_capture_pending":
                    issues.append("ready approval_capture_surface with ready_with_live_receipt requires delivery_guard.delivery_state=approval_capture_pending")
                if delivery_guard.get("user_action_required") is not True:
                    issues.append("ready approval_capture_surface with ready_with_live_receipt requires delivery_guard.user_action_required=true")
                if int(receipt.get("actionable_count") or 0) < int(approval_capture_surface.get("current_packet_live_pending_count") or 0):
                    issues.append("ready approval_capture_surface with ready_with_live_receipt requires actionable_count to include pending approval surfaces")
            if status == "ready_with_live_receipt" and approval_capture and not approval_capture_ready:
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
