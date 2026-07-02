from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.verify_proactive_ooda_operator_status as verifier


def _write_receipt(path: Path, **payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _approval_capture_ready() -> dict[str, object]:
    return {
        "checked": True,
        "probe_ok": True,
        "ready": True,
        "status": "ready",
        "source": "docker_compose_exec:proactive_approval_capture",
        "observed_at": "2026-06-29T06:55:20Z",
        "blocking_reason": "",
        "next_action": "tap_proactive_telegram_approval_button_or_record_proactive_ooda_approval_outcome",
        "current_packet_refs_present": True,
        "current_packet_callback_record_count": 1,
        "current_packet_live_pending_count": 1,
        "current_packet_callback_latest_status": "pending",
        "callback_principal_hash_present": True,
        "candidate_principal_hash_count": 3,
        "principal_match_ready": True,
        "telegram_binding_ready": True,
        "telegram_chat_ref_present": True,
        "telegram_bot_token_present": True,
        "privacy": {
            "raw_callback_token_exposed": False,
            "raw_principal_id_exposed": False,
            "raw_chat_ref_exposed": False,
            "raw_packet_ref_exposed": False,
            "raw_staged_artifact_ref_exposed": False,
        },
    }


def _degraded_source_coverage() -> dict[str, object]:
    return {
        "checked": True,
        "probe_ok": True,
        "status": "ready_with_gaps",
        "source": "docker_compose_exec",
        "runtime_service": "ea-proactive-ooda",
        "observed_at": "2026-06-29T08:00:00Z",
        "blocking_reason": "",
        "next_action": "sync_pocket_ai_audio_transcripts",
        "next_action_href": "https://myexternalbrain.com/app/api/signals/pocket/sync?limit=10",
        "next_action_label": "Sync Pocket transcripts",
        "next_action_method": "post",
        "observation_repository": "PostgresObservationEventRepository",
        "observation_limit": 400,
        "observation_row_count": 7,
        "lane_count": 8,
        "observed_lane_count": 7,
        "missing_lane_keys": ["pocket_ai_audio_transcripts"],
        "lanes": [
            {
                "key": "postgres_observations",
                "label": "Postgres observations",
                "status": "observed",
                "observed": True,
                "record_count": 7,
                "latest_observed_at": "2026-06-29T07:59:00Z",
                "evidence_event_types": ["telegram.message"],
                "next_action": "",
                "raw_payload_exposed": False,
                "raw_transcript_text_exposed": False,
                "raw_credential_exposed": False,
            },
            {
                "key": "google_workspace",
                "label": "Google workspace",
                "status": "observed",
                "observed": True,
                "record_count": 4,
                "latest_observed_at": "2026-06-29T07:59:00Z",
                "evidence_event_types": ["gmail.message"],
                "next_action": "",
                "raw_payload_exposed": False,
                "raw_transcript_text_exposed": False,
                "raw_credential_exposed": False,
            },
            {
                "key": "pocket_ai_audio_transcripts",
                "label": "Pocket.ai audio transcripts",
                "status": "not_observed",
                "observed": False,
                "record_count": 0,
                "latest_observed_at": "",
                "evidence_event_types": [],
                "required_event_types": ["pocket_recording_archive_indexed"],
                "required_event_type_observed": False,
                "missing_required_event_types": ["pocket_recording_archive_indexed"],
                "next_action": "sync_pocket_ai_audio_transcripts",
                "raw_payload_exposed": False,
                "raw_transcript_text_exposed": False,
                "raw_credential_exposed": False,
            },
            *[
                {
                    "key": key,
                    "label": key.replace("_", " "),
                    "status": "observed",
                    "observed": True,
                    "record_count": 1,
                    "latest_observed_at": "2026-06-29T07:57:00Z",
                    "evidence_event_types": ["office_signal_ooda_evaluated"],
                    "next_action": "",
                    "raw_payload_exposed": False,
                    "raw_transcript_text_exposed": False,
                    "raw_credential_exposed": False,
                }
                for key in (
                    "calendar_and_renewal_signals",
                    "relationship_and_occasion_signals",
                    "shopping_and_vendor_signals",
                    "commitment_and_deadline_signals",
                    "durable_profile_and_location_context",
                )
            ],
        ],
        "privacy": {
            "raw_rows_exposed": False,
            "raw_payload_exposed": False,
            "raw_transcript_text_exposed": False,
            "raw_credential_exposed": False,
            "source_ids_hashed": True,
        },
    }


def _failed_source_coverage() -> dict[str, object]:
    return {
        "checked": False,
        "probe_ok": False,
        "status": "probe_failed",
        "source": "docker_compose_exec",
        "runtime_service": "ea-proactive-ooda",
        "observed_at": "2026-07-01T21:23:57Z",
        "blocking_reason": "TimeoutExpired:30s",
        "next_action": "inspect_proactive_runtime_container",
        "next_action_href": "",
        "next_action_label": "",
        "next_action_method": "",
        "observation_repository": "",
        "observation_limit": 0,
        "observation_row_count": 0,
        "lane_count": 8,
        "observed_lane_count": 0,
        "missing_lane_keys": [
            "postgres_observations",
            "google_workspace",
            "pocket_ai_audio_transcripts",
            "calendar_and_renewal_signals",
            "relationship_and_occasion_signals",
            "shopping_and_vendor_signals",
            "commitment_and_deadline_signals",
            "durable_profile_and_location_context",
        ],
        "lanes": [
            {
                "key": "pocket_ai_audio_transcripts",
                "label": "Pocket.ai audio transcripts",
                "status": "probe_failed",
                "observed": False,
                "record_count": 0,
                "latest_observed_at": "",
                "evidence_event_types": [],
                "required_event_types": ["pocket_recording_archive_indexed"],
                "required_event_type_observed": False,
                "missing_required_event_types": ["pocket_recording_archive_indexed"],
                "next_action": "sync_pocket_ai_audio_transcripts",
                "raw_payload_exposed": False,
                "raw_transcript_text_exposed": False,
                "raw_credential_exposed": False,
            }
        ],
        "privacy": {
            "raw_rows_exposed": False,
            "raw_payload_exposed": False,
            "raw_transcript_text_exposed": False,
            "raw_credential_exposed": False,
            "source_ids_hashed": True,
        },
    }


def _provider_cost_pressure_recovery() -> dict[str, object]:
    return {
        "checked": True,
        "probe_ok": True,
        "status": "misconfigured",
        "source": "runtime_container_exec:ea-api:provider_ledger_cache",
        "observed_at": "2026-07-02T09:25:00Z",
        "window": "24h",
        "blocking_reason": "",
        "next_action": "repair_provider_cost_routing",
        "primary_background_provider": "gemini_vortex",
        "provider_order": ["gemini_vortex", "onemin"],
        "groundwork_provider_order": ["gemini_vortex", "onemin"],
        "cost_sensitive_lanes": ["groundwork"],
        "onemin_preferred_when_speed_is_not_critical": False,
        "onemin_usable": True,
        "onemin_ready_slots": 18,
        "onemin_configured_slots": 70,
        "gemini_provider_key": "gemini_vortex",
        "gemini_token_tracking": {
            "billing_truth_boundary": "token_ledger_is_cost_pressure_telemetry_not_google_cloud_billing_truth",
            "selected_window": {
                "window_seconds": 86400.0,
                "request_count": 1,
                "tokens_in": 10,
                "tokens_out": 5,
                "total_tokens": 15,
                "soft_cap_tokens": 200000,
                "state": "within_soft_cap",
            },
            "24h": {
                "window_seconds": 86400.0,
                "request_count": 1,
                "tokens_in": 10,
                "tokens_out": 5,
                "total_tokens": 15,
                "soft_cap_tokens": 200000,
                "state": "within_soft_cap",
            },
            "soft_cap_percent_24h": 0.01,
            "background_cost_gate": "open",
            "explicit_gemini_requests_allowed": True,
        },
        "routing_decision": "repair_provider_cost_routing",
        "requires_recovery": True,
        "privacy": {
            "raw_prompt_or_response_text_exposed": False,
            "raw_provider_secret_exposed": False,
            "raw_google_cloud_billing_account_exposed": False,
            "raw_provider_slots_exposed": False,
        },
    }


def _base_payload() -> dict[str, object]:
    return {
        "contract_name": "ea.proactive_ooda_operator_status.v1",
        "generated_by": "scripts/materialize_proactive_ooda_operator_status.py",
        "head_semantics": "source_state",
        "source_state_fingerprint": "source-fingerprint-123",
        "source_state_fingerprint_semantics": "worktree_source_files_sha256_excluding_generated_only_paths",
        "status": "ready_local_runtime",
        "summary": "Proactive OODA route and packet runtime are locally ready; mirror a host-visible live receipt when the next real packet is sent.",
        "next_action": "run_or_mirror_live_proactive_ooda_receipt",
        "goal_completion_claim_allowed": False,
        "live_delivery_claim_allowed": False,
        "route_probe_source": "host_verifier",
        "route_probe_runtime_service": "",
        "route_probe_observed_at": "",
        "delivery_route_ready": True,
        "delivery_route_error": "",
        "delivery_recovery_hint": "",
        "delivery_next_action": "",
        "delivery_route": {"ready": True, "route_error": "", "next_action": ""},
        "delivery_guard": {"delivery_state": "eligible"},
        "stage_packets": {"ready": True},
        "safe_work_results": {"ready": True},
        "safe_work_audit": {
            "present": False,
            "source": "",
            "result_status": "",
            "audit_present": False,
            "audit_status": "",
            "audit_passed": False,
            "issue_count": 0,
            "issue_codes": [],
            "issue_severity_counts": {},
            "browser_handoff_user_action_required": False,
            "delivery_allowed": False,
            "blocks_operator_followthrough": False,
            "blocking_reason": "",
            "next_action": "",
            "privacy": {
                "raw_issue_details_exposed": False,
                "raw_candidate_exposed": False,
                "raw_draft_text_exposed": False,
                "raw_private_link_exposed": False,
            },
        },
        "suppressed_projection": {
            "present": False,
            "source": "",
            "status": "not_observed",
            "requires_recovery": False,
            "blocking_reason": "",
            "next_action": "",
            "run_receipt_generated_at": "",
            "notification_status": "",
            "error_code": "",
            "item_count": 0,
            "teable_status": "",
            "projection_record_count": 0,
            "packet_projection_record_count": 0,
            "suppressed_item_count": 0,
            "suppressed_safe_work_review_count": 0,
            "suppressed_projection_reasons": [],
            "suppressed_safe_work_issue_codes": [],
            "inferred_from_packet_projection_gap": False,
            "privacy": {
                "raw_packet_text_exposed": False,
                "raw_candidate_exposed": False,
                "raw_draft_text_exposed": False,
                "raw_private_link_exposed": False,
            },
        },
        "live_receipt_checked": False,
        "live_receipt": {"ok": False, "receipt_path": ""},
        "gmail_draft_followthrough": {
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
        },
        "source_coverage": {
            "checked": True,
            "probe_ok": True,
            "status": "ready",
            "source": "docker_compose_exec",
            "runtime_service": "ea-proactive-ooda",
            "observed_at": "2026-06-29T08:00:00Z",
            "blocking_reason": "",
            "next_action": "",
            "next_action_href": "",
            "next_action_label": "",
            "next_action_method": "",
            "observation_repository": "PostgresObservationEventRepository",
            "observation_limit": 400,
            "observation_row_count": 8,
            "lane_count": 8,
            "observed_lane_count": 8,
            "missing_lane_keys": [],
            "lanes": [
                {
                    "key": "postgres_observations",
                    "label": "Postgres observations",
                    "status": "observed",
                    "observed": True,
                    "record_count": 8,
                    "latest_observed_at": "2026-06-29T07:59:00Z",
                    "evidence_event_types": ["telegram.message"],
                    "next_action": "",
                    "raw_payload_exposed": False,
                    "raw_transcript_text_exposed": False,
                    "raw_credential_exposed": False,
                },
                {
                    "key": "google_workspace",
                    "label": "Google workspace",
                    "status": "observed",
                    "observed": True,
                    "record_count": 4,
                    "latest_observed_at": "2026-06-29T07:59:00Z",
                    "evidence_event_types": ["gmail.message"],
                    "next_action": "",
                    "raw_payload_exposed": False,
                    "raw_transcript_text_exposed": False,
                    "raw_credential_exposed": False,
                },
                {
                    "key": "pocket_ai_audio_transcripts",
                    "label": "Pocket.ai audio transcripts",
                    "status": "observed",
                    "observed": True,
                    "record_count": 1,
                    "latest_observed_at": "2026-06-29T07:58:00Z",
                    "evidence_event_types": ["pocket_recording_archive_indexed"],
                    "next_action": "",
                    "raw_payload_exposed": False,
                    "raw_transcript_text_exposed": False,
                    "raw_credential_exposed": False,
                },
                *[
                    {
                        "key": key,
                        "label": key.replace("_", " "),
                        "status": "observed",
                        "observed": True,
                        "record_count": 1,
                        "latest_observed_at": "2026-06-29T07:57:00Z",
                        "evidence_event_types": ["office_signal_ooda_evaluated"],
                        "next_action": "",
                        "raw_payload_exposed": False,
                        "raw_transcript_text_exposed": False,
                        "raw_credential_exposed": False,
                    }
                    for key in (
                        "calendar_and_renewal_signals",
                        "relationship_and_occasion_signals",
                        "shopping_and_vendor_signals",
                        "commitment_and_deadline_signals",
                        "durable_profile_and_location_context",
                    )
                ],
            ],
            "privacy": {
                "raw_rows_exposed": False,
                "raw_payload_exposed": False,
                "raw_transcript_text_exposed": False,
                "raw_credential_exposed": False,
                "source_ids_hashed": True,
            },
        },
        "verifier_commands": [
            "make verify-proactive-ooda",
            "make verify-proactive-ooda-live-receipt",
            "make verify-proactive-ooda-operator-status",
        ],
        "remaining_external_proofs": [
            "real proactive OODA packet accepted with routed delivery, approved-source or transcript signal, live browse evidence, auditor-passed chosen candidate, staged reversible artifact, mirrored Teable delivery, current-packet, stale-approval, and decision facts, and explicit approval outcome"
        ],
        "rules": [
            "This receipt proves proactive OODA route, guard, and packet-runtime posture only; it does not prove a human accepted the packet.",
            "Delivery recovery hints may be mirrored here and in Teable, but they remain operator aids rather than canonical queue truth.",
            "A live sent receipt can prove one routed delivery happened, but it does not by itself prove ordinary-use usefulness or approval correctness.",
            "Gold-production claims still require accepted proactive packets, routed delivery proof, approved-source or transcript signal evidence, live browse evidence, an auditor-passed chosen candidate, staged reversible artifacts, mirrored Teable current/stale delivery and decision facts, explicit approval outcome evidence, and consent-gated irreversible actions.",
        ],
    }


@pytest.fixture(autouse=True)
def _stable_source_fingerprint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(verifier, "_source_fingerprint", lambda path=verifier.ROOT: "source-fingerprint-123")


def test_proactive_ooda_operator_status_verifier_accepts_valid_receipt(tmp_path: Path, monkeypatch) -> None:
    receipt = tmp_path / ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json"
    payload = _base_payload()
    payload["source_git_head"] = "source-head-123"
    _write_receipt(receipt, **payload)
    monkeypatch.setattr(verifier, "_git_head", lambda path=verifier.ROOT: "source-head-123")

    assert verifier.verify(receipt, root=tmp_path) == []


def test_proactive_ooda_operator_status_verifier_accepts_source_coverage_recovery(
    tmp_path: Path, monkeypatch
) -> None:
    receipt = tmp_path / ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json"
    payload = _base_payload()
    payload.update(
        {
            "source_git_head": "source-head-123",
            "status": "ready_with_recovery_action",
            "reason": "source_coverage_ready_with_gaps:pocket_ai_audio_transcripts",
            "summary": "Proactive OODA route and packet runtime are available, but approved source coverage still has 1 missing lane: pocket_ai_audio_transcripts. Recover that signal ingest before treating the loop as gold-ready.",
            "next_action": "sync_pocket_ai_audio_transcripts",
            "next_action_href": "https://myexternalbrain.com/app/api/signals/pocket/sync?limit=10",
            "next_action_label": "Sync Pocket transcripts",
            "next_action_method": "post",
            "operator_action_state": "recovery_required",
            "live_receipt_checked": True,
            "live_receipt": {"ok": True, "receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json"},
            "source_coverage": _degraded_source_coverage(),
        }
    )
    _write_receipt(receipt, **payload)
    monkeypatch.setattr(verifier, "_git_head", lambda path=verifier.ROOT: "source-head-123")

    assert verifier.verify(receipt, root=tmp_path) == []


def test_proactive_ooda_operator_status_verifier_accepts_provider_cost_recovery(
    tmp_path: Path, monkeypatch
) -> None:
    receipt = tmp_path / ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json"
    monkeypatch.setattr(verifier, "_git_head", lambda root=tmp_path: "source-head-123")
    monkeypatch.setattr(verifier, "_source_fingerprint", lambda root=tmp_path: "source-fingerprint-123")
    payload = _base_payload()
    payload.update(
        {
            "source_git_head": "source-head-123",
            "status": "ready_with_recovery_action",
            "reason": "provider_cost_pressure_misconfigured",
            "summary": "Proactive OODA route and packet runtime are available, but provider cost routing needs recovery.",
            "next_action": "repair_provider_cost_routing",
            "next_action_href": "https://myexternalbrain.com/admin/goals",
            "next_action_label": "Open goals",
            "next_action_method": "get",
            "operator_action_state": "recovery_required",
            "provider_cost_pressure": _provider_cost_pressure_recovery(),
        }
    )
    _write_receipt(receipt, **payload)

    assert verifier.verify(receipt, root=tmp_path) == []


def test_proactive_ooda_operator_status_verifier_rejects_provider_cost_privacy_leak(
    tmp_path: Path, monkeypatch
) -> None:
    receipt = tmp_path / ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json"
    monkeypatch.setattr(verifier, "_git_head", lambda root=tmp_path: "source-head-123")
    monkeypatch.setattr(verifier, "_source_fingerprint", lambda root=tmp_path: "source-fingerprint-123")
    provider_cost = _provider_cost_pressure_recovery()
    privacy = dict(provider_cost["privacy"])
    privacy["raw_provider_secret_exposed"] = True
    provider_cost["privacy"] = privacy
    payload = _base_payload()
    payload.update(
        {
            "source_git_head": "source-head-123",
            "status": "ready_with_recovery_action",
            "reason": "provider_cost_pressure_misconfigured",
            "summary": "Proactive OODA route and packet runtime are available, but provider cost routing needs recovery.",
            "next_action": "repair_provider_cost_routing",
            "next_action_href": "https://myexternalbrain.com/admin/goals",
            "next_action_label": "Open goals",
            "next_action_method": "get",
            "operator_action_state": "recovery_required",
            "provider_cost_pressure": provider_cost,
        }
    )
    _write_receipt(receipt, **payload)

    assert "provider_cost_pressure.privacy.raw_provider_secret_exposed must remain false" in verifier.verify(
        receipt,
        root=tmp_path,
    )


def test_proactive_ooda_operator_status_verifier_rejects_live_receipt_overclaim_with_degraded_source_coverage(
    tmp_path: Path, monkeypatch
) -> None:
    receipt = tmp_path / ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json"
    payload = _base_payload()
    payload.update(
        {
            "source_git_head": "source-head-123",
            "status": "ready_with_live_receipt",
            "reason": "ready",
            "summary": "Proactive OODA route, packet runtime, and latest host-visible live receipt are ready for operator follow-through.",
            "next_action": "maintain_proactive_ooda_runtime",
            "next_action_href": "https://myexternalbrain.com/app/today",
            "next_action_label": "Open Today",
            "next_action_method": "get",
            "operator_action_state": "clear",
            "live_receipt_checked": True,
            "live_receipt": {"ok": True, "receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json"},
            "source_coverage": _degraded_source_coverage(),
        }
    )
    _write_receipt(receipt, **payload)
    monkeypatch.setattr(verifier, "_git_head", lambda path=verifier.ROOT: "source-head-123")

    issues = verifier.verify(receipt, root=tmp_path)

    assert "degraded source_coverage without a higher-priority blocker requires status=ready_with_recovery_action" in issues
    assert "degraded source_coverage without a higher-priority blocker requires operator_action_state=recovery_required" in issues
    assert "degraded source_coverage without a higher-priority blocker requires source_coverage reason" in issues
    assert "degraded source_coverage without a higher-priority blocker requires receipt.next_action to match source_coverage.next_action" in issues


def test_proactive_ooda_operator_status_verifier_rejects_live_receipt_overclaim_with_failed_source_probe(
    tmp_path: Path, monkeypatch
) -> None:
    receipt = tmp_path / ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json"
    payload = _base_payload()
    payload.update(
        {
            "source_git_head": "source-head-123",
            "status": "ready_with_live_receipt",
            "reason": "ready",
            "summary": "Proactive OODA route, packet runtime, and latest host-visible live receipt are ready for operator follow-through.",
            "next_action": "maintain_proactive_ooda_runtime",
            "next_action_href": "https://myexternalbrain.com/app/today",
            "next_action_label": "Open Today",
            "next_action_method": "get",
            "operator_action_state": "clear",
            "live_receipt_checked": True,
            "live_receipt": {"ok": True, "receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json"},
            "source_coverage": _failed_source_coverage(),
        }
    )
    _write_receipt(receipt, **payload)
    monkeypatch.setattr(verifier, "_git_head", lambda path=verifier.ROOT: "source-head-123")

    issues = verifier.verify(receipt, root=tmp_path)

    assert "degraded source_coverage without a higher-priority blocker requires status=ready_with_recovery_action" in issues
    assert "degraded source_coverage without a higher-priority blocker requires operator_action_state=recovery_required" in issues
    assert "degraded source_coverage without a higher-priority blocker requires source_coverage reason" in issues


def test_proactive_ooda_operator_status_verifier_rejects_clear_status_with_blocked_safe_work_audit(
    tmp_path: Path, monkeypatch
) -> None:
    receipt = tmp_path / ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json"
    payload = _base_payload()
    payload["source_git_head"] = "source-head-123"
    payload["status"] = "ready_with_live_receipt"
    payload["next_action"] = "maintain_proactive_ooda_runtime"
    payload["next_action_href"] = "https://myexternalbrain.com/app/today"
    payload["next_action_label"] = "Open Today"
    payload["next_action_method"] = "get"
    payload["operator_action_state"] = "clear"
    payload["live_receipt_checked"] = True
    payload["live_receipt"] = {"ok": True, "receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json"}
    payload["safe_work_audit"] = {
        "present": True,
        "source": "docker_compose_exec",
        "result_status": "blocked_needs_research_input",
        "audit_present": True,
        "audit_status": "review",
        "audit_passed": False,
        "issue_count": 1,
        "issue_codes": ["top_candidate_not_provider_like"],
        "issue_severity_counts": {"warn": 1},
        "browser_handoff_user_action_required": False,
        "delivery_allowed": False,
        "blocks_operator_followthrough": True,
        "blocking_reason": "safe_work_audit_review",
        "next_action": "repair_proactive_safe_work_audit",
        "privacy": {
            "raw_issue_details_exposed": False,
            "raw_candidate_exposed": False,
            "raw_draft_text_exposed": False,
            "raw_private_link_exposed": False,
        },
    }
    _write_receipt(receipt, **payload)
    monkeypatch.setattr(verifier, "_git_head", lambda path=verifier.ROOT: "source-head-123")

    issues = verifier.verify(receipt, root=tmp_path)

    assert "non-deliverable safe_work_audit requires status=blocked_local_runtime" in issues
    assert "non-deliverable safe_work_audit requires next_action=repair_proactive_safe_work_audit" in issues
    assert "non-deliverable safe_work_audit requires operator_action_state=recovery_required" in issues


def test_proactive_ooda_operator_status_verifier_allows_suppressed_projection_recovery_without_route_error(
    tmp_path: Path, monkeypatch
) -> None:
    receipt = tmp_path / ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json"
    payload = _base_payload()
    payload.update(
        {
            "source_git_head": "source-head-123",
            "status": "ready_with_recovery_action",
            "reason": "suppressed_safe_work_projection",
            "summary": "Proactive OODA runtime is healthy, but the latest quiet run suppressed 2 non-deliverable safe-work item(s) from user and Teable packet projection.",
            "next_action": "repair_proactive_safe_work_audit",
            "next_action_href": "https://myexternalbrain.com/app/queue",
            "next_action_label": "Review safe work",
            "next_action_method": "get",
            "operator_action_state": "recovery_required",
            "delivery_route_error": "",
            "delivery_route": {"ready": True, "route_error": "", "next_action": ""},
            "suppressed_projection": {
                "present": True,
                "source": "docker_compose_exec",
                "status": "suppressed",
                "requires_recovery": True,
                "blocking_reason": "suppressed_safe_work_projection",
                "next_action": "repair_proactive_safe_work_audit",
                "run_receipt_generated_at": "2026-06-30T08:00:00Z",
                "notification_status": "deferred",
                "error_code": "no_user_action_required",
                "item_count": 2,
                "teable_status": "synced",
                "projection_record_count": 1,
                "packet_projection_record_count": 0,
                "suppressed_item_count": 2,
                "suppressed_safe_work_review_count": 2,
                "suppressed_projection_reasons": ["safe_work_audit_review"],
                "suppressed_safe_work_issue_codes": ["no_decision_ready_material"],
                "inferred_from_packet_projection_gap": False,
                "privacy": {
                    "raw_packet_text_exposed": False,
                    "raw_candidate_exposed": False,
                    "raw_draft_text_exposed": False,
                    "raw_private_link_exposed": False,
                },
            },
        }
    )
    _write_receipt(receipt, **payload)
    monkeypatch.setattr(verifier, "_git_head", lambda path=verifier.ROOT: "source-head-123")

    assert verifier.verify(receipt, root=tmp_path) == []


def test_proactive_ooda_operator_status_verifier_allows_non_material_suppressed_projection(
    tmp_path: Path, monkeypatch
) -> None:
    receipt = tmp_path / ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json"
    payload = _base_payload()
    payload.update(
        {
            "source_git_head": "source-head-123",
            "status": "ready_with_live_receipt",
            "reason": "ready",
            "summary": "Proactive OODA route, packet runtime, and latest host-visible live receipt are ready for operator follow-through.",
            "next_action": "maintain_proactive_ooda_runtime",
            "next_action_href": "https://myexternalbrain.com/app/today",
            "next_action_label": "Open Today",
            "next_action_method": "get",
            "operator_action_state": "clear",
            "delivery_route_error": "",
            "delivery_route": {"ready": True, "route_error": "", "next_action": ""},
            "live_receipt_checked": True,
            "live_receipt": {"ok": True, "receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json"},
            "suppressed_projection": {
                "present": True,
                "source": "docker_compose_exec",
                "status": "suppressed_non_material",
                "requires_recovery": False,
                "blocking_reason": "",
                "next_action": "",
                "suppressed_non_material": True,
                "suppressed_non_material_reason": "quiet_no_decision_ready_material",
                "run_receipt_generated_at": "2026-06-30T08:00:00Z",
                "notification_status": "deferred",
                "error_code": "no_user_action_required",
                "item_count": 2,
                "teable_status": "synced",
                "projection_record_count": 1,
                "packet_projection_record_count": 0,
                "suppressed_item_count": 2,
                "suppressed_safe_work_review_count": 2,
                "suppressed_projection_reasons": ["safe_work_audit_review"],
                "suppressed_safe_work_issue_codes": ["no_decision_ready_material"],
                "inferred_from_packet_projection_gap": False,
                "privacy": {
                    "raw_packet_text_exposed": False,
                    "raw_candidate_exposed": False,
                    "raw_draft_text_exposed": False,
                    "raw_private_link_exposed": False,
                },
            },
        }
    )
    _write_receipt(receipt, **payload)
    monkeypatch.setattr(verifier, "_git_head", lambda path=verifier.ROOT: "source-head-123")

    assert verifier.verify(receipt, root=tmp_path) == []


def test_proactive_ooda_operator_status_verifier_allows_configured_source_exclusion_suppressed_projection(
    tmp_path: Path, monkeypatch
) -> None:
    receipt = tmp_path / ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json"
    payload = _base_payload()
    payload.update(
        {
            "source_git_head": "source-head-123",
            "status": "ready_with_live_receipt",
            "reason": "ready",
            "summary": "Proactive OODA route, packet runtime, and latest host-visible live receipt are ready for operator follow-through.",
            "next_action": "maintain_proactive_ooda_runtime",
            "next_action_href": "https://myexternalbrain.com/app/today",
            "next_action_label": "Open Today",
            "next_action_method": "get",
            "operator_action_state": "clear",
            "delivery_route_error": "",
            "delivery_route": {"ready": True, "route_error": "", "next_action": ""},
            "live_receipt_checked": True,
            "live_receipt": {"ok": True, "receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json"},
            "suppressed_projection": {
                "present": True,
                "source": "docker_compose_exec",
                "status": "suppressed_non_material",
                "requires_recovery": False,
                "blocking_reason": "",
                "next_action": "",
                "suppressed_non_material": True,
                "suppressed_non_material_reason": "configured_source_exclusion",
                "run_receipt_generated_at": "2026-07-01T20:55:53Z",
                "notification_status": "sent",
                "error_code": "",
                "item_count": 1,
                "teable_status": "synced",
                "projection_record_count": 1,
                "packet_projection_record_count": 0,
                "suppressed_item_count": 1,
                "suppressed_safe_work_review_count": 0,
                "suppressed_projection_reasons": ["flat_search_disabled"],
                "suppressed_safe_work_issue_codes": ["flat_search_disabled"],
                "inferred_from_packet_projection_gap": False,
                "privacy": {
                    "raw_packet_text_exposed": False,
                    "raw_candidate_exposed": False,
                    "raw_draft_text_exposed": False,
                    "raw_private_link_exposed": False,
                },
            },
        }
    )
    _write_receipt(receipt, **payload)
    monkeypatch.setattr(verifier, "_git_head", lambda path=verifier.ROOT: "source-head-123")

    assert verifier.verify(receipt, root=tmp_path) == []


def test_proactive_ooda_operator_status_verifier_allows_non_material_current_artifact_filter(
    tmp_path: Path, monkeypatch
) -> None:
    receipt = tmp_path / ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json"
    payload = _base_payload()
    payload.update(
        {
            "source_git_head": "source-head-123",
            "status": "ready_with_live_receipt",
            "reason": "ready",
            "summary": "Proactive OODA route, packet runtime, and latest host-visible live receipt are ready for operator follow-through.",
            "next_action": "maintain_proactive_ooda_runtime",
            "next_action_href": "https://myexternalbrain.com/app/today",
            "next_action_label": "Open Today",
            "next_action_method": "get",
            "operator_action_state": "clear",
            "live_receipt_checked": True,
            "live_receipt": {"ok": True, "receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json"},
            "current_artifact_filter": {
                "present": True,
                "source": "docker_compose_exec",
                "reason": "single_official_info_link_not_decision_ready",
                "filter_status": "suppressed_non_material",
                "requires_recovery": False,
                "blocking_reason": "",
                "next_action": "",
                "issue_codes": ["single_official_info_link_not_decision_ready"],
                "privacy": {
                    "raw_packet_text_exposed": False,
                    "raw_candidate_exposed": False,
                    "raw_draft_text_exposed": False,
                    "raw_private_link_exposed": False,
                },
            },
        }
    )
    _write_receipt(receipt, **payload)
    monkeypatch.setattr(verifier, "_git_head", lambda path=verifier.ROOT: "source-head-123")

    assert verifier.verify(receipt, root=tmp_path) == []


def test_proactive_ooda_operator_status_verifier_rejects_clear_status_with_suppressed_projection_recovery(
    tmp_path: Path, monkeypatch
) -> None:
    receipt = tmp_path / ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json"
    payload = _base_payload()
    payload.update(
        {
            "source_git_head": "source-head-123",
            "status": "ready_with_live_receipt",
            "next_action": "maintain_proactive_ooda_runtime",
            "next_action_href": "https://myexternalbrain.com/app/today",
            "next_action_label": "Open Today",
            "next_action_method": "get",
            "operator_action_state": "clear",
            "live_receipt_checked": True,
            "live_receipt": {"ok": True, "receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json"},
            "suppressed_projection": {
                "present": True,
                "source": "docker_compose_exec",
                "status": "suppressed",
                "requires_recovery": True,
                "blocking_reason": "suppressed_safe_work_projection",
                "next_action": "repair_proactive_safe_work_audit",
                "run_receipt_generated_at": "2026-06-30T08:00:00Z",
                "notification_status": "deferred",
                "error_code": "no_user_action_required",
                "item_count": 1,
                "teable_status": "synced",
                "projection_record_count": 1,
                "packet_projection_record_count": 0,
                "suppressed_item_count": 1,
                "suppressed_safe_work_review_count": 1,
                "suppressed_projection_reasons": ["safe_work_audit_review"],
                "suppressed_safe_work_issue_codes": ["no_decision_ready_material"],
                "inferred_from_packet_projection_gap": False,
                "privacy": {
                    "raw_packet_text_exposed": False,
                    "raw_candidate_exposed": False,
                    "raw_draft_text_exposed": False,
                    "raw_private_link_exposed": False,
                },
            },
        }
    )
    _write_receipt(receipt, **payload)
    monkeypatch.setattr(verifier, "_git_head", lambda path=verifier.ROOT: "source-head-123")

    issues = verifier.verify(receipt, root=tmp_path)

    assert "suppressed_projection recovery requires status=ready_with_recovery_action" in issues
    assert "suppressed_projection recovery requires receipt.next_action=repair_proactive_safe_work_audit" in issues
    assert "suppressed_projection recovery requires operator_action_state=recovery_required" in issues


def test_proactive_ooda_operator_status_verifier_accepts_post_commit_head_change_when_source_fingerprint_matches(
    tmp_path: Path, monkeypatch
) -> None:
    receipt = tmp_path / ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json"
    payload = _base_payload()
    payload["source_git_head"] = "pre-commit-source-head"
    _write_receipt(receipt, **payload)
    monkeypatch.setattr(verifier, "_git_head", lambda path=verifier.ROOT: "post-commit-source-head")

    assert verifier.verify(receipt, root=tmp_path) == []


def test_proactive_ooda_operator_status_verifier_rejects_source_fingerprint_drift(
    tmp_path: Path, monkeypatch
) -> None:
    receipt = tmp_path / ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json"
    payload = _base_payload()
    payload["source_git_head"] = "pre-commit-source-head"
    payload["source_state_fingerprint"] = "old-source-fingerprint"
    _write_receipt(receipt, **payload)
    monkeypatch.setattr(verifier, "_git_head", lambda path=verifier.ROOT: "post-commit-source-head")

    issues = verifier.verify(receipt, root=tmp_path)

    assert "receipt is stale relative to current source HEAD" in issues
    assert "receipt is stale relative to current source fingerprint" in issues


def test_proactive_ooda_operator_status_verifier_rejects_live_receipt_overclaim(tmp_path: Path, monkeypatch) -> None:
    receipt = tmp_path / ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json"
    payload = _base_payload()
    payload.update(
        {
            "source_git_head": "source-head-123",
            "status": "ready_with_live_receipt",
            "live_receipt_checked": True,
            "live_receipt": {"ok": False, "receipt_path": str(tmp_path / "receipt.json")},
        }
    )
    _write_receipt(receipt, **payload)
    monkeypatch.setattr(verifier, "_git_head", lambda path=verifier.ROOT: "source-head-123")

    issues = verifier.verify(receipt, root=tmp_path)

    assert "ready_with_live_receipt status requires live_receipt.ok=true" in issues


def test_proactive_ooda_operator_status_verifier_rejects_gmail_draft_execution_overclaim(
    tmp_path: Path, monkeypatch
) -> None:
    receipt = tmp_path / ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json"
    payload = _base_payload()
    payload["source_git_head"] = "source-head-123"
    payload["gmail_draft_followthrough"] = {
        **dict(payload["gmail_draft_followthrough"]),
        "status": "already_executed",
        "action": "save_gmail_draft",
        "execution_status": "",
        "execution_observation_present": False,
        "gmail_draft_id_hash_present": False,
        "raw_execution_payload_exposed": True,
    }
    _write_receipt(receipt, **payload)
    monkeypatch.setattr(verifier, "_git_head", lambda path=verifier.ROOT: "source-head-123")

    issues = verifier.verify(receipt, root=tmp_path)

    assert "gmail_draft_followthrough.raw_execution_payload_exposed must remain false" in issues
    assert "already_executed gmail_draft_followthrough requires execution_status=executed" in issues
    assert "already_executed gmail_draft_followthrough requires execution_observation_present=true" in issues
    assert "already_executed gmail_draft_followthrough requires gmail_draft_id_hash_present=true" in issues


def test_proactive_ooda_operator_status_verifier_rejects_raw_source_coverage_exposure(
    tmp_path: Path, monkeypatch
) -> None:
    receipt = tmp_path / ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json"
    payload = _base_payload()
    payload["source_git_head"] = "source-head-123"
    source_coverage = dict(payload["source_coverage"])
    privacy = dict(source_coverage["privacy"])
    privacy["raw_transcript_text_exposed"] = True
    source_coverage["privacy"] = privacy
    payload["source_coverage"] = source_coverage
    _write_receipt(receipt, **payload)
    monkeypatch.setattr(verifier, "_git_head", lambda path=verifier.ROOT: "source-head-123")

    issues = verifier.verify(receipt, root=tmp_path)

    assert "source_coverage.privacy.raw_transcript_text_exposed must remain false" in issues


def test_proactive_ooda_operator_status_verifier_rejects_incomplete_docker_probe_metadata(
    tmp_path: Path, monkeypatch
) -> None:
    receipt = tmp_path / ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json"
    payload = _base_payload()
    payload.update(
        {
            "source_git_head": "source-head-123",
            "route_probe_source": "docker_compose_exec",
            "route_probe_runtime_service": "",
            "route_probe_observed_at": "",
        }
    )
    _write_receipt(receipt, **payload)
    monkeypatch.setattr(verifier, "_git_head", lambda path=verifier.ROOT: "source-head-123")

    issues = verifier.verify(receipt, root=tmp_path)

    assert "docker_compose_exec route probes require route_probe_runtime_service" in issues
    assert "docker_compose_exec route probes require route_probe_observed_at" in issues


def test_proactive_ooda_operator_status_verifier_rejects_ready_approval_surface_without_live_pending_callback(
    tmp_path: Path, monkeypatch
) -> None:
    receipt = tmp_path / ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json"
    payload = _base_payload()
    payload.update(
        {
            "source_git_head": "source-head-123",
            "approval_capture_surface": {
                "ready": True,
                "selected_channel": "telegram",
                "callback_dir_writable": True,
                "approval_outcome_path": "state/proactive_ooda_latest_approval_outcome.generated.json",
                "callback_dir": "/data/provider-ledger/proactive_ooda_approval_callbacks",
                "current_packet_live_pending_count": 0,
            },
        }
    )
    _write_receipt(receipt, **payload)
    monkeypatch.setattr(verifier, "_git_head", lambda path=verifier.ROOT: "source-head-123")

    issues = verifier.verify(receipt, root=tmp_path)

    assert "ready approval_capture_surface requires live callback or manual_outcome_capture_ready" in issues


def test_proactive_ooda_operator_status_verifier_rejects_clear_status_when_approval_capture_is_pending(
    tmp_path: Path, monkeypatch
) -> None:
    receipt = tmp_path / ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json"
    payload = _base_payload()
    payload.update(
        {
            "source_git_head": "source-head-123",
            "status": "ready_with_live_receipt",
            "live_receipt_checked": True,
            "live_receipt": {"ok": True, "receipt_path": str(tmp_path / "receipt.json")},
            "next_action": "maintain_proactive_ooda_runtime",
            "operator_action_state": "clear",
            "approval_capture_surface": {
                "ready": True,
                "selected_channel": "telegram",
                "callback_dir_writable": True,
                "approval_outcome_path": "state/proactive_ooda_latest_approval_outcome.generated.json",
                "callback_dir": "/data/provider-ledger/proactive_ooda_approval_callbacks",
                "current_packet_live_pending_count": 1,
            },
            "approval_capture": _approval_capture_ready(),
        }
    )
    _write_receipt(receipt, **payload)
    monkeypatch.setattr(verifier, "_git_head", lambda path=verifier.ROOT: "source-head-123")

    issues = verifier.verify(receipt, root=tmp_path)

    assert "ready approval_capture_surface with ready_with_live_receipt requires approval-capture next_action" in issues
    assert "ready approval_capture_surface with ready_with_live_receipt requires operator_action_state=approval_capture_pending" in issues
    assert "ready approval_capture_surface with ready_with_live_receipt requires delivery_guard.delivery_state=approval_capture_pending" in issues
    assert "ready approval_capture_surface with ready_with_live_receipt requires delivery_guard.user_action_required=true" in issues
    assert "ready approval_capture_surface with ready_with_live_receipt requires actionable_count to include pending approval surfaces" in issues


def test_proactive_ooda_operator_status_verifier_requires_reauth_surface_for_google_reauth(
    tmp_path: Path, monkeypatch
) -> None:
    receipt = tmp_path / ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json"
    payload = _base_payload()
    payload.update(
        {
            "source_git_head": "source-head-123",
            "status": "blocked_local_runtime",
            "summary": "Proactive OODA routing is available, but Google workspace needs reauthorization before EA can rely on that source (google_oauth_invalid_grant).",
            "next_action": "reauthorize_google_workspace_binding",
            "next_action_href": "",
            "next_action_label": "",
            "next_action_method": "",
        }
    )
    _write_receipt(receipt, **payload)
    monkeypatch.setattr(verifier, "_git_head", lambda path=verifier.ROOT: "source-head-123")

    issues = verifier.verify(receipt, root=tmp_path)

    assert "reauthorize_google_workspace_binding requires next_action_href" in issues
    assert "reauthorize_google_workspace_binding requires next_action_label" in issues
    assert "reauthorize_google_workspace_binding requires next_action_method=get" in issues


def test_proactive_ooda_operator_status_verifier_allows_google_workspace_recovery_without_route_error(
    tmp_path: Path, monkeypatch
) -> None:
    receipt = tmp_path / ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json"
    payload = _base_payload()
    payload.update(
        {
            "source_git_head": "source-head-123",
            "status": "ready_with_recovery_action",
            "summary": "Proactive OODA routing is available, but Google workspace needs reauthorization before EA can rely on that source (google_oauth_invalid_grant).",
            "reason": "google_workspace_signal_source_unhealthy:google_oauth_invalid_grant",
            "next_action": "maintain_proactive_ooda_runtime",
            "delivery_route_error": "",
            "delivery_route": {"ready": True, "route_error": "", "next_action": ""},
        }
    )
    _write_receipt(receipt, **payload)
    monkeypatch.setattr(verifier, "_git_head", lambda path=verifier.ROOT: "source-head-123")

    assert verifier.verify(receipt, root=tmp_path) == []
