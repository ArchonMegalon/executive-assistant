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
        "fast_provider_order": ["gemini_vortex", "onemin"],
        "groundwork_provider_order": ["gemini_vortex", "onemin"],
        "cost_sensitive_lanes": ["groundwork"],
        "onemin_preferred_when_speed_is_not_critical": False,
        "onemin_preferred_whenever_usable": False,
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


def _assistant_grade_packet_recovery() -> dict[str, object]:
    return {
        "present": True,
        "source": "docker_compose_exec",
        "stage_kind": "internal_action",
        "work_type": "record_internal_action",
        "requires_recovery": True,
        "blocking_reason": "internal_action_not_assistant_grade",
        "next_action": "stage_fresh_assistant_grade_proactive_packet",
        "privacy": {
            "raw_packet_text_exposed": False,
            "raw_candidate_exposed": False,
            "raw_draft_text_exposed": False,
            "raw_private_link_exposed": False,
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
        "browser_handoff": {
            "present": False,
            "required": False,
            "source": "",
            "site_host": "",
            "blocker_code": "",
            "reason": "",
            "next_action": "",
            "resume_instruction": "",
            "staged_artifact_present": False,
            "challenge": {
                "primary_channel": "",
                "available_channels": [],
                "destination_hint": "",
                "operator_instruction": "",
                "raw_destination_stored": False,
            },
            "privacy": {
                "raw_credentials_stored": False,
                "raw_cookie_or_session_stored": False,
                "raw_browser_artifact_stored": False,
            },
        },
        "assistant_grade_packet": {
            "present": False,
            "source": "",
            "stage_kind": "",
            "work_type": "",
            "requires_recovery": False,
            "blocking_reason": "",
            "next_action": "",
            "privacy": {
                "raw_packet_text_exposed": False,
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
        "onemin_direct_refresh_posture": {
            "checked": False,
            "probe_ok": False,
            "status": "not_checked",
            "source": "",
            "observed_at": "",
            "reason": "",
            "next_action": "",
            "ready": False,
            "receipt_name": "",
            "selected_account_count": 0,
            "pending_account_count": 0,
            "owner_row_count": 0,
            "attempted_count": 0,
            "current_run_refreshed_count": 0,
            "refreshed_count": 0,
            "error_count": 0,
            "error_code_counts": {},
            "rate_limited": False,
            "remaining_credits_total": None,
            "remaining_credits_min": None,
            "remaining_credits_max": None,
            "next_topup_at_earliest": "",
            "next_topup_at_latest": "",
            "controls": {
                "batch_size": 1,
                "batch_backoff_seconds": 1.0,
                "max_rate_limit_sleep_seconds": 120.0,
                "continue_on_rate_limit": True,
                "refresh_transport": "direct_provider_api",
                "proxy_mode": "direct_no_ui_proxy",
                "controls_inferred_from_defaults": True,
                "single_account_batch_mode": True,
            },
            "telegram_delivery": {
                "checked": False,
                "sent": False,
                "reason": "",
                "ready": False,
                "message_count": 0,
                "observed_at": "",
                "source": "",
                "dry_run": False,
            },
            "privacy": {
                "raw_owner_email_exposed": False,
                "raw_login_secret_exposed": False,
                "raw_telegram_chat_ref_exposed": False,
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


def test_proactive_ooda_operator_status_verifier_accepts_mixed_delivery_non_material_suppression(
    tmp_path: Path, monkeypatch
) -> None:
    receipt = tmp_path / ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json"
    payload = _base_payload()
    payload.update(
        {
            "source_git_head": "source-head-123",
            "status": "ready_with_live_receipt",
            "summary": "Proactive OODA route, packet runtime, and latest host-visible live receipt are ready for operator follow-through.",
            "next_action": "maintain_proactive_ooda_runtime",
            "next_action_href": "https://myexternalbrain.com/app/today",
            "next_action_label": "Open Today",
            "next_action_method": "get",
            "operator_action_state": "clear",
            "route_probe_source": "docker_compose_exec",
            "route_probe_runtime_service": "ea-proactive-ooda",
            "route_probe_observed_at": "2026-07-09T05:40:00Z",
            "live_receipt_checked": True,
            "live_receipt": {
                "ok": True,
                "receipt_path": "/data/provider-ledger/proactive_ooda_live_sent_receipt.json",
                "delivery_mode": "telegram_sent",
                "sent_message_ids": ["3610"],
            },
            "delivery_route": {
                "ready": True,
                "route_error": "",
                "next_action": "",
                "selected_channel": "telegram",
                "selected_transport": "telegram",
                "selected_by": "tool_runtime_binding",
                "available_channels": ["telegram"],
            },
            "suppressed_projection": {
                "present": True,
                "source": "docker_compose_exec",
                "status": "suppressed_non_material",
                "requires_recovery": False,
                "blocking_reason": "",
                "next_action": "",
                "run_receipt_generated_at": "2026-07-09T05:39:02Z",
                "notification_status": "sent",
                "error_code": "",
                "item_count": 5,
                "teable_status": "synced",
                "projection_record_count": 4,
                "packet_projection_record_count": 2,
                "suppressed_item_count": 4,
                "suppressed_safe_work_review_count": 4,
                "suppressed_projection_reasons": ["safe_work_quality_gate_review"],
                "suppressed_safe_work_issue_codes": ["no_decision_ready_material"],
                "suppressed_non_material": True,
                "suppressed_non_material_reason": "mixed_delivery_non_material",
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


def test_proactive_ooda_operator_status_verifier_accepts_browser_handoff_recovery(
    tmp_path: Path, monkeypatch
) -> None:
    receipt = tmp_path / ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json"
    payload = _base_payload()
    payload.update(
        {
            "source_git_head": "source-head-123",
            "status": "ready_with_recovery_action",
            "reason": "browser_handoff_required",
            "summary": (
                "Proactive OODA is waiting on a live browser handoff for www.amazon.de before the current packet can "
                "resume. Provide the verification code sent to the phone ending 419. The page also offers WhatsApp "
                "code delivery. After the code is provided, resume the browser task from the authenticated session."
            ),
            "next_action": "complete_browser_handoff_then_resume_ooda_task",
            "next_action_href": "https://myexternalbrain.com/app/queue",
            "next_action_label": "Resume browser handoff",
            "next_action_method": "get",
            "operator_action_state": "recovery_required",
            "delivery_route_error": "",
            "delivery_route": {"ready": True, "route_error": "", "next_action": ""},
            "delivery_guard": {
                "delivery_state": "browser_handoff_pending",
                "user_action_required": True,
                "browser_handoff_pending": True,
                "blocker_code": "mfa_code_required",
            },
            "safe_work_audit": {
                "present": True,
                "source": "docker_compose_exec",
                "result_status": "blocked_human_handoff_required",
                "audit_present": True,
                "audit_status": "review",
                "audit_passed": False,
                "issue_count": 1,
                "issue_codes": ["browser_handoff_required"],
                "issue_severity_counts": {"info": 1},
                "filtered_non_material": False,
                "browser_handoff_user_action_required": True,
                "delivery_allowed": True,
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
            "browser_handoff": {
                "present": True,
                "required": True,
                "source": "docker_compose_exec",
                "site_host": "www.amazon.de",
                "blocker_code": "mfa_code_required",
                "reason": "Multi-factor verification requires user action.",
                "next_action": "complete_browser_handoff_then_resume_ooda_task",
                "resume_instruction": "After the code is provided, resume the browser task from the authenticated session.",
                "staged_artifact_present": False,
                "challenge": {
                    "primary_channel": "phone",
                    "available_channels": ["whatsapp", "phone"],
                    "destination_hint": "phone ending 419",
                    "operator_instruction": (
                        "Provide the verification code sent to the phone ending 419. "
                        "The page also offers WhatsApp code delivery."
                    ),
                    "raw_destination_stored": False,
                },
                "privacy": {
                    "raw_credentials_stored": False,
                    "raw_cookie_or_session_stored": False,
                    "raw_browser_artifact_stored": False,
                },
            },
        }
    )
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


def test_proactive_ooda_operator_status_verifier_accepts_assistant_grade_recovery(
    tmp_path: Path, monkeypatch
) -> None:
    receipt = tmp_path / ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json"
    payload = _base_payload()
    payload.update(
        {
            "source_git_head": "source-head-123",
            "status": "ready_with_recovery_action",
            "reason": "internal_action_not_assistant_grade",
            "summary": (
                "The proactive OODA mechanics have evidence, but the selected packet is not assistant-grade enough "
                "to prove production readiness."
            ),
            "next_action": "stage_fresh_assistant_grade_proactive_packet",
            "next_action_href": "https://myexternalbrain.com/app/queue",
            "next_action_label": "Open queue",
            "next_action_method": "get",
            "operator_action_state": "recovery_required",
            "live_receipt_checked": True,
            "live_receipt": {"ok": True, "receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json"},
            "assistant_grade_packet": _assistant_grade_packet_recovery(),
            "approval_capture_surface": {},
            "approval_capture": {},
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


def test_proactive_ooda_operator_status_verifier_rejects_onemin_direct_refresh_privacy_leak(
    tmp_path: Path, monkeypatch
) -> None:
    receipt = tmp_path / ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json"
    monkeypatch.setattr(verifier, "_git_head", lambda root=tmp_path: "source-head-123")
    monkeypatch.setattr(verifier, "_source_fingerprint", lambda root=tmp_path: "source-fingerprint-123")
    payload = _base_payload()
    posture = dict(payload["onemin_direct_refresh_posture"])
    posture.update(
        {
            "checked": True,
            "probe_ok": True,
            "status": "rate_limited",
            "source": "private_receipt:onemin_direct_refresh_live.json",
            "observed_at": "2026-07-10T02:10:57Z",
            "receipt_name": "onemin_direct_refresh_live.json",
        }
    )
    privacy = dict(posture["privacy"])
    privacy["raw_login_secret_exposed"] = True
    posture["privacy"] = privacy
    payload.update({"source_git_head": "source-head-123", "onemin_direct_refresh_posture": posture})
    _write_receipt(receipt, **payload)

    assert "onemin_direct_refresh_posture.privacy.raw_login_secret_exposed must remain false" in verifier.verify(
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


def test_proactive_ooda_operator_status_verifier_rejects_ready_live_receipt_with_pending_approval_surface_but_clear_operator_state(
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
                "telegram_approval_surface_ready": True,
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


def test_proactive_ooda_operator_status_verifier_allows_source_health_google_workspace_recovery_without_route_error(
    tmp_path: Path, monkeypatch
) -> None:
    receipt = tmp_path / ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json"
    payload = _base_payload()
    payload.update(
        {
            "source_git_head": "source-head-123",
            "status": "ready_with_recovery_action",
            "summary": "Proactive OODA routing is available, but Google workspace needs reauthorization before EA can rely on that source (google_oauth_invalid_grant).",
            "reason": "source_health_google_workspace:google_oauth_invalid_grant",
            "next_action": "maintain_proactive_ooda_runtime",
            "delivery_route_error": "",
            "delivery_route": {"ready": True, "route_error": "", "next_action": ""},
        }
    )
    _write_receipt(receipt, **payload)
    monkeypatch.setattr(verifier, "_git_head", lambda path=verifier.ROOT: "source-head-123")

    assert verifier.verify(receipt, root=tmp_path) == []


def test_proactive_ooda_operator_status_verifier_allows_followthrough_recovery_without_route_error(
    tmp_path: Path, monkeypatch
) -> None:
    receipt = tmp_path / ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json"
    payload = _base_payload()
    payload.update(
        {
            "source_git_head": "source-head-123",
            "status": "ready_with_recovery_action",
            "summary": "Proactive OODA can still route, but followthrough artifacts need recovery.",
            "reason": "followthrough_artifacts_missing",
            "next_action": "repair_proactive_operator_runtime_posture",
            "delivery_route_error": "",
            "delivery_route": {"ready": True, "route_error": "", "next_action": ""},
            "live_receipt_checked": True,
            "live_receipt": {
                "ok": False,
                "receipt_path": "/data/provider-ledger/proactive_ooda_run_receipts/latest.json",
                "errors": ["followthrough_artifacts_missing"],
            },
        }
    )
    _write_receipt(receipt, **payload)
    monkeypatch.setattr(verifier, "_git_head", lambda path=verifier.ROOT: "source-head-123")

    assert verifier.verify(receipt, root=tmp_path) == []


def test_proactive_ooda_operator_status_verifier_rejects_historical_assistant_grade_packet_without_selected_artifact_telemetry(
    tmp_path: Path,
    monkeypatch,
) -> None:
    receipt = tmp_path / ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json"
    payload = _base_payload()
    payload.update(
        {
            "source_git_head": "source-head-123",
            "assistant_grade_packet": {
                "present": True,
                "source": "docker_compose_exec",
                "bundle_source": "historical_browse_backed_proof_bundle",
                "stage_kind": "research_packet",
                "work_type": "compare_options",
                "requires_recovery": False,
                "blocking_reason": "",
                "next_action": "",
                "privacy": {
                    "raw_packet_text_exposed": False,
                    "raw_candidate_exposed": False,
                    "raw_draft_text_exposed": False,
                    "raw_private_link_exposed": False,
                },
            },
            "stage_packets": {"ready": True, "packet_count": 0},
            "safe_work_results": {"ready": True, "result_count": 0},
        }
    )
    _write_receipt(receipt, **payload)
    monkeypatch.setattr(verifier, "_git_head", lambda path=verifier.ROOT: "source-head-123")

    issues = verifier.verify(receipt, root=tmp_path)

    assert "historical assistant_grade_packet requires stage_packets.selected_packet_present=true" in issues
    assert "historical assistant_grade_packet requires safe_work_results.selected_result_present=true" in issues
