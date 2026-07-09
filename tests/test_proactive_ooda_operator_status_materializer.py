from __future__ import annotations

import importlib.util
import json
import os
import sys
from argparse import Namespace
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "materialize_proactive_ooda_operator_status.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("materialize_proactive_ooda_operator_status", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _fake_source_coverage_probe(**_kwargs: object) -> dict[str, object]:
    return {
        "probe_ok": True,
        "checked": True,
        "status": "ready",
        "source": "docker_compose_exec",
        "runtime_service": "ea-proactive-ooda",
        "observed_at": "2026-06-29T08:00:00Z",
        "observation_repository": "PostgresObservationEventRepository",
        "observation_limit": 400,
        "observation_row_count": 8,
        "lane_count": 8,
        "observed_lane_count": 8,
        "missing_lane_keys": [],
        "next_action": "",
        "next_action_href": "",
        "next_action_label": "",
        "next_action_method": "",
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
                "latest_observed_at": "2026-06-29T07:58:00Z",
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
                "latest_observed_at": "2026-06-29T07:57:00Z",
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
                    "latest_observed_at": "2026-06-29T07:56:00Z",
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


def _fake_provider_cost_pressure_probe(**_kwargs: object) -> dict[str, object]:
    return {
        "probe_ok": True,
        "status": "active_cost_control",
        "observed_at": "2026-07-02T09:25:00Z",
        "source": "runtime_container_exec:ea-api:provider_ledger_cache",
        "window": "24h",
        "primary_background_provider": "onemin",
        "provider_order": ["onemin", "magixai", "gemini_vortex"],
        "fast_provider_order": ["onemin", "magixai", "gemini_vortex"],
        "cheap_provider_order": ["onemin", "magixai", "gemini_vortex"],
        "groundwork_provider_order": ["onemin", "magixai", "gemini_vortex"],
        "hard_provider_order": ["onemin", "magixai", "gemini_vortex"],
        "cost_sensitive_lanes": ["audit", "fast", "groundwork", "overflow", "review", "review_light"],
        "onemin_preferred_when_speed_is_not_critical": True,
        "onemin_preferred_whenever_usable": True,
        "onemin_usable": True,
        "onemin_ready_slots": 18,
        "onemin_configured_slots": 70,
        "onemin_remaining_credits": 133270343.0,
        "gemini_provider_key": "gemini_vortex",
        "gemini_token_tracking": {
            "billing_truth_boundary": "token_ledger_is_cost_pressure_telemetry_not_google_cloud_billing_truth",
            "selected_window": {
                "window_seconds": 86400.0,
                "request_count": 0,
                "tokens_in": 0,
                "tokens_out": 0,
                "total_tokens": 0,
                "soft_cap_tokens": 200000,
                "state": "within_soft_cap",
            },
            "24h": {
                "window_seconds": 86400.0,
                "request_count": 0,
                "tokens_in": 0,
                "tokens_out": 0,
                "total_tokens": 0,
                "soft_cap_tokens": 200000,
                "state": "within_soft_cap",
            },
            "soft_cap_percent_24h": 0.0,
            "background_cost_gate": "open",
            "explicit_gemini_requests_allowed": True,
        },
        "routing_decision": "prefer_onemin_background_when_usable",
        "privacy": {
            "raw_prompt_or_response_text_exposed": False,
            "raw_provider_secret_exposed": False,
            "raw_google_cloud_billing_account_exposed": False,
            "raw_provider_slots_exposed": False,
        },
    }


def _fake_provider_cost_pressure_misconfigured_probe(**_kwargs: object) -> dict[str, object]:
    payload = dict(_fake_provider_cost_pressure_probe(**_kwargs))
    payload.update(
        {
            "status": "misconfigured",
            "primary_background_provider": "gemini_vortex",
            "provider_order": ["gemini_vortex", "onemin"],
            "fast_provider_order": ["gemini_vortex", "onemin"],
            "groundwork_provider_order": ["gemini_vortex", "onemin"],
            "onemin_preferred_when_speed_is_not_critical": False,
            "onemin_preferred_whenever_usable": False,
            "routing_decision": "repair_provider_cost_routing",
        }
    )
    return payload


def _fake_provider_cost_pressure_probe_pending_probe(**_kwargs: object) -> dict[str, object]:
    payload = dict(_fake_provider_cost_pressure_probe(**_kwargs))
    payload.update(
        {
            "status": "active_cost_control_onemin_probe_pending",
            "onemin_usable": True,
            "onemin_probe_pending": True,
            "onemin_ready_slots": 0,
            "onemin_unknown_slots": 70,
            "routing_decision": "prefer_onemin_background_pending_probe_with_gemini_fallback_only",
        }
    )
    return payload


def _fake_source_coverage_gap_probe(**_kwargs: object) -> dict[str, object]:
    return {
        "probe_ok": True,
        "checked": True,
        "status": "ready_with_gaps",
        "source": "docker_compose_exec",
        "runtime_service": "ea-proactive-ooda",
        "observed_at": "2026-06-29T08:00:00Z",
        "observation_repository": "PostgresObservationEventRepository",
        "observation_limit": 400,
        "observation_row_count": 7,
        "lane_count": 8,
        "observed_lane_count": 7,
        "missing_lane_keys": ["pocket_ai_audio_transcripts"],
        "next_action": "sync_pocket_ai_audio_transcripts",
        "next_action_href": "https://myexternalbrain.com/app/api/signals/pocket/sync?limit=10",
        "next_action_label": "Sync Pocket transcripts",
        "next_action_method": "post",
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
                "latest_observed_at": "2026-06-29T07:58:00Z",
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
                    "latest_observed_at": "2026-06-29T07:56:00Z",
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


def _fake_source_coverage_probe_failure(**_kwargs: object) -> dict[str, object]:
    return {
        "probe_ok": False,
        "checked": False,
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
        "missing_lane_keys": list(
            (
                "postgres_observations",
                "google_workspace",
                "pocket_ai_audio_transcripts",
                "calendar_and_renewal_signals",
                "relationship_and_occasion_signals",
                "shopping_and_vendor_signals",
                "commitment_and_deadline_signals",
                "durable_profile_and_location_context",
            )
        ),
        "lanes": [],
        "privacy": {
            "raw_rows_exposed": False,
            "raw_payload_exposed": False,
            "raw_transcript_text_exposed": False,
            "raw_credential_exposed": False,
            "source_ids_hashed": True,
        },
    }


def _fake_approval_capture_probe(**_kwargs: object) -> dict[str, object]:
    return {
        "probe_ok": True,
        "ready": True,
        "status": "ready",
        "source": "docker_compose_exec:proactive_approval_capture",
        "runtime_service": "ea-proactive-ooda",
        "observed_at": "2026-06-29T06:55:20Z",
        "blocking_reason": "",
        "next_action": "tap_proactive_telegram_approval_button_or_record_proactive_ooda_approval_outcome",
        "callback_dir_exists": True,
        "callback_record_count": 1,
        "current_packet_ref_sha256": "a" * 64,
        "current_staged_artifact_ref_sha256": "b" * 64,
        "current_packet_refs_present": True,
        "current_packet_callback_record_count": 1,
        "current_packet_live_pending_count": 1,
        "current_packet_callback_latest_status": "pending",
        "current_packet_callback_latest_expired": False,
        "current_packet_callback_latest_age_seconds": 91,
        "current_packet_callback_latest_seconds_until_expiry": 1200,
        "callback_principal_hash_present": True,
        "candidate_principal_hash_count": 3,
        "principal_match_ready": True,
        "telegram_binding_ready": True,
        "telegram_blocking_reason": "",
        "telegram_chat_ref_present": True,
        "telegram_chat_ref_sha256": "c" * 64,
        "telegram_bot_key_present": True,
        "telegram_bot_token_present": True,
        "privacy": {
            "raw_callback_token_exposed": False,
            "raw_principal_id_exposed": False,
            "raw_chat_ref_exposed": False,
            "raw_packet_ref_exposed": False,
            "raw_staged_artifact_ref_exposed": False,
        },
    }


def test_source_coverage_summary_fallback_keeps_pocket_required_event_contract() -> None:
    module = _load_script()

    summary = module._source_coverage_summary({})  # noqa: SLF001

    pocket_lane = next(row for row in summary["lanes"] if row["key"] == "pocket_ai_audio_transcripts")
    assert pocket_lane["observed"] is False
    assert pocket_lane["required_event_types"] == ["pocket_recording_archive_indexed"]
    assert pocket_lane["missing_required_event_types"] == ["pocket_recording_archive_indexed"]
    assert pocket_lane["required_event_type_observed"] is False
    assert pocket_lane["next_action"] == "sync_pocket_ai_audio_transcripts"


def test_source_coverage_summary_probe_failure_keeps_required_lane_contract() -> None:
    module = _load_script()

    summary = module._source_coverage_summary(  # noqa: SLF001
        {
            "probe_ok": False,
            "checked": False,
            "status": "probe_failed",
            "source": "docker_compose_exec",
            "missing_lane_keys": list(module.ea_live_ops.PROACTIVE_SOURCE_COVERAGE_LANE_KEYS),
            "lanes": [],
            "lane_count": 0,
            "observed_lane_count": 0,
        }
    )

    assert summary["checked"] is False
    assert summary["status"] == "probe_failed"
    assert summary["lane_count"] == len(module.ea_live_ops.PROACTIVE_SOURCE_COVERAGE_LANE_KEYS)
    assert [row["key"] for row in summary["lanes"]] == list(module.ea_live_ops.PROACTIVE_SOURCE_COVERAGE_LANE_KEYS)
    pocket_lane = next(row for row in summary["lanes"] if row["key"] == "pocket_ai_audio_transcripts")
    assert pocket_lane["missing_required_event_types"] == ["pocket_recording_archive_indexed"]
    assert pocket_lane["raw_transcript_text_exposed"] is False


def test_materialize_proactive_ooda_operator_status_recovers_on_degraded_source_coverage(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")
    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_route", lambda **_kwargs: {
        "probe_ok": True,
        "source": "docker_compose_exec",
        "runtime_service": "ea-proactive-ooda",
        "observed_at": "2026-07-01T09:00:00Z",
        "live_receipt_checked": True,
        "live_receipt": {
            "ok": True,
            "receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json",
            "errors": [],
        },
        "route_report": {
            "ok": True,
            "delivery_route": {
                "ready": True,
                "route_error": "",
                "recovery_hint": "",
                "next_action": "",
                "selected_channel": "telegram",
                "selected_by": "tool_runtime_binding",
            },
            "delivery_guard": {"delivery_state": "no_actionable_items"},
            "stage_packets": {"ready": True, "errors": []},
            "safe_work_results": {"ready": True, "errors": []},
            "receipt_observation_count": 1,
            "actionable_count": 0,
        },
    })
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_gmail_draft",
        lambda **_kwargs: {"probe_ok": True, "status": "no_pending_draft", "source": "docker_compose_exec"},
    )
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_artifacts",
        lambda **_kwargs: {
            "probe_ok": True,
            "source": "docker_compose_exec",
            "run_receipt": {
                "generated_at": "2026-07-01T09:00:30Z",
                "notification_status": "skipped_no_items",
                "error_code": "",
                "item_count": 0,
                "teable_sync": {
                    "status": "synced",
                    "projection_summary": {
                        "record_count": 1,
                        "suppressed_item_count": 0,
                        "suppressed_safe_work_review_count": 0,
                        "suppressed_projection_reasons": [],
                        "suppressed_safe_work_issue_codes": [],
                        "tables": {
                            "proactive_ooda_runs": {"record_count": 1},
                            "proactive_ooda_items": {"record_count": 0},
                            "proactive_ooda_safe_work": {"record_count": 0},
                        },
                    },
                },
            },
            "action_required_only_quiet_receipt": {},
        },
    )
    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_source_coverage", _fake_source_coverage_gap_probe)
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_approval_capture",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("degraded source coverage should short-circuit approval followthrough")),
    )

    receipt = module.build_proactive_ooda_operator_status(
        output_path=tmp_path / "ea_proactive_ooda_operator_status.generated.json",
        generated_at="2026-07-01T09:01:00Z",
        report_args=Namespace(principal_id="exec-1"),
    )

    assert receipt["status"] == "ready_with_recovery_action"
    assert receipt["reason"] == "source_coverage_ready_with_gaps:pocket_ai_audio_transcripts"
    assert receipt["next_action"] == "sync_pocket_ai_audio_transcripts"
    assert receipt["next_action_href"] == "https://myexternalbrain.com/app/api/signals/pocket/sync?limit=10"
    assert receipt["next_action_label"] == "Sync Pocket transcripts"
    assert receipt["next_action_method"] == "post"
    assert receipt["operator_action_state"] == "recovery_required"
    assert "missing lane" in receipt["summary"]
    assert receipt["source_coverage"]["status"] == "ready_with_gaps"
    assert receipt["source_coverage"]["missing_lane_keys"] == ["pocket_ai_audio_transcripts"]
    assert receipt["source_coverage"]["next_action"] == "sync_pocket_ai_audio_transcripts"


def test_materialize_proactive_ooda_operator_status_recovers_on_runtime_source_health_issue(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")
    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_route", lambda **_kwargs: {
        "probe_ok": True,
        "source": "docker_compose_exec",
        "runtime_service": "ea-proactive-ooda",
        "observed_at": "2026-07-01T09:00:00Z",
        "live_receipt_checked": True,
        "live_receipt": {
            "ok": True,
            "receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json",
            "errors": [],
        },
        "route_report": {
            "ok": True,
            "delivery_route": {
                "ready": True,
                "route_error": "",
                "recovery_hint": "",
                "next_action": "",
                "selected_channel": "telegram",
                "selected_by": "tool_runtime_binding",
            },
            "delivery_guard": {"delivery_state": "no_actionable_items"},
            "stage_packets": {"ready": True, "errors": []},
            "safe_work_results": {"ready": True, "errors": []},
            "receipt_observation_count": 1,
            "actionable_count": 0,
        },
    })
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_gmail_draft",
        lambda **_kwargs: {"probe_ok": True, "status": "no_pending_draft", "source": "docker_compose_exec"},
    )
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_artifacts",
        lambda **_kwargs: {
            "probe_ok": True,
            "source": "docker_compose_exec",
            "run_receipt": {
                "generated_at": "2026-07-01T09:00:30Z",
                "notification_status": "skipped_no_items",
                "error_code": "",
                "item_count": 0,
                "source_health": {
                    "present": True,
                    "status": "recovery_required",
                    "issue_count": 1,
                    "operator_action_required": True,
                    "user_action_required": False,
                    "issues": [
                        {
                            "source_key": "discovery",
                            "source_type": "json",
                            "status": "failed",
                            "error_code": "FileNotFoundError",
                            "error_ref_hash": "abc123",
                            "operator_action_required": True,
                            "user_action_required": False,
                            "next_action": "repair_proactive_signal_source",
                            "raw_source_ref_exposed": False,
                            "raw_payload_exposed": False,
                            "raw_credential_exposed": False,
                        }
                    ],
                    "privacy": {
                        "raw_source_ref_exposed": False,
                        "raw_payload_exposed": False,
                        "raw_credential_exposed": False,
                        "source_refs_hashed": True,
                    },
                },
                "teable_sync": {
                    "status": "synced",
                    "projection_summary": {
                        "record_count": 1,
                        "suppressed_item_count": 0,
                        "suppressed_safe_work_review_count": 0,
                        "suppressed_projection_reasons": [],
                        "suppressed_safe_work_issue_codes": [],
                        "tables": {
                            "proactive_ooda_runs": {"record_count": 1},
                            "proactive_ooda_items": {"record_count": 0},
                            "proactive_ooda_safe_work": {"record_count": 0},
                        },
                    },
                },
            },
            "action_required_only_quiet_receipt": {},
        },
    )
    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_source_coverage", _fake_source_coverage_probe)
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_approval_capture",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("source health recovery should short-circuit approval followthrough")),
    )

    receipt = module.build_proactive_ooda_operator_status(
        output_path=tmp_path / "ea_proactive_ooda_operator_status.generated.json",
        generated_at="2026-07-01T09:01:00Z",
        report_args=Namespace(principal_id="exec-1"),
    )

    assert receipt["status"] == "ready_with_recovery_action"
    assert receipt["reason"] == "source_health_discovery:FileNotFoundError"
    assert receipt["next_action"] == "repair_proactive_signal_source"
    assert receipt["next_action_label"] == "Open goals"
    assert receipt["operator_action_state"] == "recovery_required"
    assert "signal source health issue" in receipt["summary"]
    assert receipt["source_health"]["present"] is True
    assert receipt["source_health"]["user_action_required"] is False
    assert receipt["source_health"]["privacy"]["raw_payload_exposed"] is False
    assert receipt["source_coverage"]["status"] == "ready"


def test_materialize_proactive_ooda_operator_status_prefers_source_health_over_followthrough_repair(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")
    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_route", lambda **_kwargs: {
        "probe_ok": True,
        "source": "docker_compose_exec",
        "runtime_service": "ea-proactive-ooda",
        "observed_at": "2026-07-06T18:00:00Z",
        "live_receipt_checked": True,
        "live_receipt": {
            "ok": False,
            "errors": ["followthrough_artifacts_missing"],
            "receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json",
            "notification_status": "sent",
            "delivery_next_action": "repair_proactive_operator_runtime_posture",
            "delivery_route_error": "",
            "delivery_message_count": 1,
            "telegram_message_count": 1,
        },
        "route_report": {
            "ok": True,
            "delivery_route": {
                "ready": True,
                "route_error": "",
                "recovery_hint": "",
                "next_action": "",
                "selected_channel": "telegram",
                "selected_by": "tool_runtime_binding",
            },
            "delivery_guard": {"delivery_state": "eligible"},
            "stage_packets": {"ready": True, "errors": []},
            "safe_work_results": {"ready": True, "errors": []},
            "receipt_observation_count": 1,
            "actionable_count": 0,
        },
    })
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_gmail_draft",
        lambda **_kwargs: {"probe_ok": True, "status": "no_pending_draft", "source": "docker_compose_exec"},
    )
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_artifacts",
        lambda **_kwargs: {
            "probe_ok": True,
            "source": "docker_compose_exec",
            "run_receipt": {
                "generated_at": "2026-07-06T18:00:30Z",
                "notification_status": "sent",
                "error_code": "",
                "item_count": 1,
                "source_health": {
                    "present": True,
                    "status": "recovery_required",
                    "issue_count": 1,
                    "operator_action_required": True,
                    "user_action_required": False,
                    "issues": [
                        {
                            "source_key": "google_workspace",
                            "source_type": "google_workspace",
                            "status": "unhealthy",
                            "error_code": "google_oauth_invalid_grant",
                            "recovery_mode": "scheduler_cooldown",
                            "blocked_until": "2026-07-06T20:00:00Z",
                            "cooldown_active": True,
                            "cooldown_seconds_remaining": 7200,
                            "last_observed_at": "2026-07-06T18:00:30Z",
                            "error_ref_hash": "abc123",
                            "operator_action_required": True,
                            "user_action_required": False,
                            "next_action": "reauthorize_google_workspace_binding",
                            "raw_source_ref_exposed": False,
                            "raw_payload_exposed": False,
                            "raw_credential_exposed": False,
                        }
                    ],
                    "privacy": {
                        "raw_source_ref_exposed": False,
                        "raw_payload_exposed": False,
                        "raw_credential_exposed": False,
                        "source_refs_hashed": True,
                    },
                },
            },
            "action_required_only_quiet_receipt": {},
        },
    )
    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_source_coverage", _fake_source_coverage_probe)
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_approval_capture",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("source health recovery should avoid approval followthrough")
        ),
    )

    receipt = module.build_proactive_ooda_operator_status(
        output_path=tmp_path / "ea_proactive_ooda_operator_status.generated.json",
        generated_at="2026-07-06T18:01:00Z",
        report_args=Namespace(principal_id="exec-1"),
    )

    assert receipt["status"] == "ready_with_recovery_action"
    assert receipt["reason"] == "source_health_google_workspace:google_oauth_invalid_grant"
    assert receipt["next_action"] == "reauthorize_google_workspace_binding"
    assert receipt["next_action_label"] == "Reconnect Google workspace"
    assert receipt["source_health"]["user_action_required"] is True
    assert receipt["source_health"]["issues"][0]["user_action_required"] is True
    assert receipt["source_health"]["issues"][0]["next_action"] == "reauthorize_google_workspace_binding"
    assert receipt["source_health"]["issues"][0]["recovery_mode"] == "scheduler_cooldown"
    assert receipt["source_health"]["issues"][0]["blocked_until"] == "2026-07-06T20:00:00Z"
    assert receipt["source_health"]["issues"][0]["cooldown_active"] is True
    assert receipt["source_health"]["issues"][0]["cooldown_seconds_remaining"] == 7200
    assert receipt["summary"] == (
        "Proactive OODA route and packet runtime are available, but "
        "Google workspace recovery cooldown is active until 2026-07-06T20:00:00Z."
    )


def test_materialize_proactive_ooda_operator_status_recovers_on_runtime_artifact_drift(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")
    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_route", lambda **_kwargs: {
        "probe_ok": True,
        "source": "docker_compose_exec",
        "runtime_service": "ea-proactive-ooda",
        "observed_at": "2026-07-08T09:00:00Z",
        "live_receipt_checked": True,
        "live_receipt": {
            "ok": True,
            "receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json",
            "errors": [],
            "notification_status": "sent",
            "delivery_message_count": 1,
            "telegram_message_count": 1,
        },
        "route_report": {
            "ok": True,
            "delivery_route": {
                "ready": True,
                "route_error": "",
                "recovery_hint": "",
                "next_action": "",
                "selected_channel": "telegram",
                "selected_by": "tool_runtime_binding",
            },
            "delivery_guard": {"delivery_state": "eligible"},
            "stage_packets": {"ready": True, "errors": []},
            "safe_work_results": {"ready": True, "errors": []},
            "receipt_observation_count": 1,
            "actionable_count": 1,
        },
    })
    monkeypatch.setattr(
        module,
        "_local_artifact_probe",
        lambda **_kwargs: {
            "source": "docker_compose_exec",
            "artifact_resolution_source": "live_runtime",
            "artifact_resolution_host_fallback_used": False,
            "artifact_resolution_fallback_reason": "",
            "runtime_artifact_drift": {
                "checked": True,
                "present": True,
                "status": "drift_detected",
                "requires_recovery": True,
                "blocking_reason": "runtime_artifact_drift:stage_packet_ref_sha256",
                "next_action": "repair_proactive_runtime_artifact_drift",
                "mismatch_count": 2,
                "material_mismatch_count": 2,
                "mismatch_fields": ["stage_packet_ref_sha256", "safe_work_result_ref_sha256"],
                "material_mismatch_fields": ["stage_packet_ref_sha256", "safe_work_result_ref_sha256"],
                "host_artifacts_present": True,
            },
            "artifact_filter_reason": "",
            "run_receipt": {"notification_status": "sent"},
            "stage_packet": {
                "packet_ref": "stage_packet:live-packet",
                "approval": {"required": True},
            },
            "safe_work_result": {
                "result_ref": "safe_work_result:live-artifact",
                "status": "staged_for_user_decision",
                "approval": {"required": True},
                "approval_prompt": "Approve the staged shortlist.",
                "staged_action_url": "https://example.test/approve",
                "audit": {"status": "pass", "issues": []},
            },
            "approval_outcome": {},
            "approval_callback_dir_exists": True,
            "approval_callback_dir_writable": True,
            "approval_callback_record_count": 1,
            "approval_callback_pending_count": 1,
            "approval_callback_raw_pending_count": 1,
            "approval_callback_live_pending_count": 1,
            "approval_callback_unexpired_pending_count": 1,
            "approval_callback_noncurrent_pending_count": 0,
            "approval_callback_stale_pending_count": 0,
            "approval_callback_expired_pending_count": 0,
            "approval_callback_recorded_count": 0,
            "approval_callback_expired_count": 0,
            "approval_callback_superseded_count": 0,
            "approval_callback_terminal_count": 0,
            "current_packet_callback_record_count": 1,
            "current_packet_callback_pending_count": 1,
            "current_packet_callback_raw_pending_count": 1,
            "current_packet_callback_stale_pending_count": 0,
            "current_packet_callback_expired_pending_count": 0,
            "current_packet_callback_recorded_count": 0,
            "current_packet_callback_expired_count": 0,
            "current_packet_callback_superseded_count": 0,
            "current_packet_live_callback_record_count": 1,
            "current_packet_live_pending_count": 1,
            "current_packet_callback_latest_status": "pending",
            "current_packet_callback_latest_expired": False,
            "current_packet_callback_latest_created_at": "2026-07-08T08:59:00Z",
            "current_packet_callback_latest_expires_at": "2026-07-08T09:19:00Z",
            "current_packet_callback_latest_age_seconds": 60,
            "current_packet_callback_latest_seconds_until_expiry": 1200,
        },
    )
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_gmail_draft",
        lambda **_kwargs: {"probe_ok": True, "status": "no_pending_draft", "source": "docker_compose_exec"},
    )
    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_source_coverage", _fake_source_coverage_probe)
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_approval_capture",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("runtime artifact drift recovery should short-circuit approval followthrough")
        ),
    )

    receipt = module.build_proactive_ooda_operator_status(
        output_path=tmp_path / "ea_proactive_ooda_operator_status.generated.json",
        generated_at="2026-07-08T09:01:00Z",
        report_args=Namespace(principal_id="exec-1"),
    )

    assert receipt["status"] == "ready_with_recovery_action"
    assert receipt["reason"] == "runtime_artifact_drift:stage_packet_ref_sha256"
    assert receipt["next_action"] == "repair_proactive_runtime_artifact_drift"
    assert receipt["operator_action_state"] == "recovery_required"
    assert receipt["runtime_artifact_drift"]["requires_recovery"] is True
    assert receipt["runtime_artifact_drift"]["host_artifacts_present"] is True
    assert receipt["runtime_artifact_drift"]["material_mismatch_fields"] == [
        "stage_packet_ref_sha256",
        "safe_work_result_ref_sha256",
    ]
    assert "runtime artifact drift" in receipt["summary"]


def test_materialize_proactive_ooda_operator_status_projects_provider_cost_pressure(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")
    monkeypatch.setattr(
        module,
        "_local_artifact_probe",
        lambda **_kwargs: {
            "source": "local_filesystem",
            "run_receipt": {},
            "stage_packet": {},
            "safe_work_result": {},
            "approval_outcome": {},
            "approval_callback_dir_exists": False,
            "approval_callback_dir_writable": False,
            "approval_callback_record_count": 0,
            "approval_callback_pending_count": 0,
            "current_packet_callback_record_count": 0,
            "current_packet_live_pending_count": 0,
        },
    )
    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_route", lambda **_kwargs: {
        "probe_ok": True,
        "source": "docker_compose_exec",
        "runtime_service": "ea-proactive-ooda",
        "observed_at": "2026-07-02T09:25:00Z",
        "live_receipt_checked": True,
        "live_receipt": {
            "ok": True,
            "receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json",
            "errors": [],
        },
        "route_report": {
            "ok": True,
            "delivery_route": {
                "ready": True,
                "route_error": "",
                "recovery_hint": "",
                "next_action": "",
                "selected_channel": "telegram",
                "selected_by": "tool_runtime_binding",
            },
            "delivery_guard": {"delivery_state": "no_actionable_items"},
            "stage_packets": {"ready": True, "errors": []},
            "safe_work_results": {"ready": True, "errors": []},
            "receipt_observation_count": 1,
            "actionable_count": 0,
        },
    })
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_gmail_draft",
        lambda **_kwargs: {"probe_ok": True, "status": "no_pending_draft", "source": "docker_compose_exec"},
    )
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_artifacts",
        lambda **_kwargs: {"probe_ok": True, "source": "docker_compose_exec", "run_receipt": {}},
    )
    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_source_coverage", _fake_source_coverage_probe)
    monkeypatch.setattr(module.ea_live_ops, "probe_provider_cost_pressure", _fake_provider_cost_pressure_probe)

    receipt = module.build_proactive_ooda_operator_status(
        output_path=tmp_path / "ea_proactive_ooda_operator_status.generated.json",
        generated_at="2026-07-02T09:26:00Z",
        report_args=Namespace(principal_id="exec-1"),
        skip_provider_cost_pressure_probe=False,
    )

    assert receipt["status"] == "ready_with_live_receipt"
    assert receipt["provider_cost_pressure"]["checked"] is True
    assert receipt["provider_cost_pressure"]["status"] == "active_cost_control"
    assert receipt["provider_cost_pressure"]["requires_recovery"] is False
    assert receipt["provider_cost_pressure"]["primary_background_provider"] == "onemin"
    assert receipt["provider_cost_pressure"]["fast_provider_order"] == ["onemin", "magixai", "gemini_vortex"]
    assert receipt["provider_cost_pressure"]["cheap_provider_order"] == ["onemin", "magixai", "gemini_vortex"]
    assert receipt["provider_cost_pressure"]["onemin_preferred_when_speed_is_not_critical"] is True
    assert receipt["provider_cost_pressure"]["onemin_preferred_whenever_usable"] is True
    assert receipt["provider_cost_pressure"]["hard_provider_order"] == ["onemin", "magixai", "gemini_vortex"]
    assert receipt["provider_cost_pressure"]["gemini_token_tracking"]["24h"]["total_tokens"] == 0
    assert receipt["provider_cost_pressure"]["privacy"]["raw_provider_secret_exposed"] is False


def test_materialize_proactive_ooda_operator_status_backfills_provider_cost_pressure_with_explicit_live_receipt_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_route",
        lambda **_kwargs: {
            "probe_ok": True,
            "source": "docker_compose_exec",
            "runtime_service": "ea-proactive-ooda",
            "observed_at": "2026-07-02T09:25:00Z",
            "live_receipt_checked": True,
            "live_receipt": {
                "ok": True,
                "receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json",
                "errors": [],
            },
            "route_report": {
                "ok": True,
                "delivery_route": {
                    "ready": True,
                    "route_error": "",
                    "recovery_hint": "",
                    "next_action": "",
                    "selected_channel": "telegram",
                    "selected_by": "tool_runtime_binding",
                },
                "delivery_guard": {"delivery_state": "no_actionable_items"},
                "stage_packets": {"ready": True, "errors": []},
                "safe_work_results": {"ready": True, "errors": []},
                "receipt_observation_count": 1,
                "actionable_count": 0,
            },
        },
    )
    monkeypatch.setattr(
        module,
        "_local_artifact_probe",
        lambda **_kwargs: {
            "source": "local_filesystem",
            "run_receipt": {},
            "stage_packet": {},
            "safe_work_result": {},
            "approval_outcome": {},
            "approval_callback_dir_exists": False,
            "approval_callback_dir_writable": False,
            "approval_callback_record_count": 0,
            "approval_callback_pending_count": 0,
            "current_packet_callback_record_count": 0,
            "current_packet_live_pending_count": 0,
        },
    )
    monkeypatch.setattr(module.ea_live_ops, "probe_provider_cost_pressure", _fake_provider_cost_pressure_probe)

    receipt = module.build_proactive_ooda_operator_status(
        output_path=tmp_path / "ea_proactive_ooda_operator_status.generated.json",
        generated_at="2026-07-02T09:26:00Z",
        report_args=Namespace(principal_id="exec-1"),
        live_receipt_path=tmp_path / "live-receipt.json",
        skip_provider_cost_pressure_probe=False,
    )

    assert receipt["provider_cost_pressure"]["checked"] is True
    assert receipt["provider_cost_pressure"]["status"] == "active_cost_control"
    assert receipt["provider_cost_pressure"]["requires_recovery"] is False
    assert receipt["provider_cost_pressure"]["primary_background_provider"] == "onemin"
    assert receipt["provider_cost_pressure"]["provider_order"] == ["onemin", "magixai", "gemini_vortex"]
    assert receipt["provider_cost_pressure"]["gemini_token_tracking"]["background_cost_gate"] == "open"


def test_materialize_proactive_ooda_operator_status_recovers_on_provider_cost_misconfiguration(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")
    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_route", lambda **_kwargs: {
        "probe_ok": True,
        "source": "docker_compose_exec",
        "runtime_service": "ea-proactive-ooda",
        "observed_at": "2026-07-02T09:25:00Z",
        "live_receipt_checked": True,
        "live_receipt": {
            "ok": True,
            "receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json",
            "errors": [],
        },
        "route_report": {
            "ok": True,
            "delivery_route": {
                "ready": True,
                "route_error": "",
                "recovery_hint": "",
                "next_action": "",
                "selected_channel": "telegram",
                "selected_by": "tool_runtime_binding",
            },
            "delivery_guard": {"delivery_state": "no_actionable_items"},
            "stage_packets": {"ready": True, "errors": []},
            "safe_work_results": {"ready": True, "errors": []},
            "receipt_observation_count": 1,
            "actionable_count": 0,
        },
    })
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_gmail_draft",
        lambda **_kwargs: {"probe_ok": True, "status": "no_pending_draft", "source": "docker_compose_exec"},
    )
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_artifacts",
        lambda **_kwargs: {"probe_ok": True, "source": "docker_compose_exec", "run_receipt": {}},
    )
    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_source_coverage", _fake_source_coverage_probe)
    monkeypatch.setattr(module.ea_live_ops, "probe_provider_cost_pressure", _fake_provider_cost_pressure_misconfigured_probe)
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_approval_capture",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("provider cost recovery should short-circuit approval followthrough")),
    )

    receipt = module.build_proactive_ooda_operator_status(
        output_path=tmp_path / "ea_proactive_ooda_operator_status.generated.json",
        generated_at="2026-07-02T09:26:00Z",
        report_args=Namespace(principal_id="exec-1"),
        skip_provider_cost_pressure_probe=False,
    )

    assert receipt["status"] == "ready_with_recovery_action"
    assert receipt["reason"] == "provider_cost_pressure_misconfigured"
    assert receipt["next_action"] == "repair_provider_cost_routing"
    assert receipt["next_action_label"] == "Open goals"
    assert receipt["operator_action_state"] == "recovery_required"
    assert receipt["provider_cost_pressure"]["requires_recovery"] is True
    assert receipt["provider_cost_pressure"]["primary_background_provider"] == "gemini_vortex"
    assert "provider cost routing needs recovery" in receipt["summary"]


def test_materialize_proactive_ooda_operator_status_keeps_running_when_onemin_probe_is_pending(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")
    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_route", lambda **_kwargs: {
        "probe_ok": True,
        "source": "docker_compose_exec",
        "runtime_service": "ea-proactive-ooda",
        "observed_at": "2026-07-02T09:25:00Z",
        "live_receipt_checked": True,
        "live_receipt": {
            "ok": True,
            "receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json",
            "errors": [],
        },
        "route_report": {
            "ok": True,
            "delivery_route": {
                "ready": True,
                "route_error": "",
                "recovery_hint": "",
                "next_action": "",
                "selected_channel": "telegram",
                "selected_by": "tool_runtime_binding",
            },
            "delivery_guard": {"delivery_state": "no_actionable_items"},
            "stage_packets": {"ready": True, "errors": []},
            "safe_work_results": {"ready": True, "errors": []},
            "receipt_observation_count": 1,
            "actionable_count": 0,
        },
    })
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_gmail_draft",
        lambda **_kwargs: {"probe_ok": True, "status": "no_pending_draft", "source": "docker_compose_exec"},
    )
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_artifacts",
        lambda **_kwargs: {"probe_ok": True, "source": "docker_compose_exec", "run_receipt": {}},
    )
    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_source_coverage", _fake_source_coverage_probe)
    monkeypatch.setattr(module.ea_live_ops, "probe_provider_cost_pressure", _fake_provider_cost_pressure_probe_pending_probe)

    receipt = module.build_proactive_ooda_operator_status(
        output_path=tmp_path / "ea_proactive_ooda_operator_status.generated.json",
        generated_at="2026-07-02T09:26:00Z",
        report_args=Namespace(principal_id="exec-1"),
        skip_provider_cost_pressure_probe=False,
    )

    assert receipt["status"] == "ready_with_live_receipt"
    assert receipt["provider_cost_pressure"]["requires_recovery"] is False
    assert receipt["provider_cost_pressure"]["status"] == "active_cost_control_onemin_probe_pending"
    assert receipt["provider_cost_pressure"]["onemin_usable"] is True
    assert receipt["provider_cost_pressure"]["onemin_probe_pending"] is True
    assert receipt["provider_cost_pressure"]["onemin_unknown_slots"] == 70


def test_materialize_proactive_ooda_operator_status_recovers_on_source_coverage_probe_failure(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")
    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_route", lambda **_kwargs: {
        "probe_ok": True,
        "source": "docker_compose_exec",
        "runtime_service": "ea-proactive-ooda",
        "observed_at": "2026-07-01T21:24:00Z",
        "live_receipt_checked": True,
        "live_receipt": {
            "ok": True,
            "receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json",
            "errors": [],
        },
        "route_report": {
            "ok": True,
            "delivery_route": {
                "ready": True,
                "route_error": "",
                "recovery_hint": "",
                "next_action": "",
                "selected_channel": "telegram",
                "selected_by": "tool_runtime_binding",
            },
            "delivery_guard": {"delivery_state": "no_actionable_items"},
            "stage_packets": {"ready": True, "errors": []},
            "safe_work_results": {"ready": True, "errors": []},
            "receipt_observation_count": 1,
            "actionable_count": 0,
        },
    })
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_gmail_draft",
        lambda **_kwargs: {"probe_ok": True, "status": "no_pending_draft", "source": "docker_compose_exec"},
    )
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_artifacts",
        lambda **_kwargs: {
            "probe_ok": True,
            "source": "docker_compose_exec",
            "run_receipt": {
                "generated_at": "2026-07-01T21:24:10Z",
                "notification_status": "skipped_no_items",
                "error_code": "",
                "item_count": 0,
                "teable_sync": {
                    "status": "synced",
                    "projection_summary": {
                        "record_count": 1,
                        "suppressed_item_count": 0,
                        "suppressed_safe_work_review_count": 0,
                        "suppressed_projection_reasons": [],
                        "suppressed_safe_work_issue_codes": [],
                        "tables": {
                            "proactive_ooda_runs": {"record_count": 1},
                            "proactive_ooda_items": {"record_count": 0},
                            "proactive_ooda_safe_work": {"record_count": 0},
                        },
                    },
                },
            },
            "action_required_only_quiet_receipt": {},
        },
    )
    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_source_coverage", _fake_source_coverage_probe_failure)
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_approval_capture",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("failed source coverage should short-circuit approval followthrough")),
    )

    receipt = module.build_proactive_ooda_operator_status(
        output_path=tmp_path / "ea_proactive_ooda_operator_status.generated.json",
        generated_at="2026-07-01T21:24:30Z",
        report_args=Namespace(principal_id="exec-1"),
    )

    assert receipt["status"] == "ready_with_recovery_action"
    assert receipt["reason"] == "source_coverage_TimeoutExpired:30s"
    assert receipt["next_action"] == "inspect_proactive_runtime_container"
    assert receipt["operator_action_state"] == "recovery_required"
    assert "source coverage probing needs recovery" in receipt["summary"]
    assert receipt["source_coverage"]["checked"] is False
    assert receipt["source_coverage"]["status"] == "probe_failed"
    assert receipt["source_coverage"]["blocking_reason"] == "TimeoutExpired:30s"


def test_build_operator_status_uses_configured_live_probe_timeout(tmp_path: Path, monkeypatch) -> None:
    module = _load_script()
    monkeypatch.setenv("EA_PROACTIVE_OODA_LIVE_PROBE_TIMEOUT_SECONDS", "180")
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")
    captured: dict[str, float] = {}

    def _capture_timeout(name: str, **kwargs: object) -> None:
        captured[name] = float(kwargs.get("timeout_seconds") or 0)

    def _fake_route(**kwargs: object) -> dict[str, object]:
        _capture_timeout("route", **kwargs)
        return {
            "probe_ok": True,
            "source": "docker_compose_exec",
            "runtime_service": "ea-proactive-ooda",
            "observed_at": "2026-06-29T08:00:00Z",
            "live_receipt_checked": True,
            "live_receipt": {"ok": True, "receipt_path": "/app/state/proactive_ooda/live-receipt.json", "errors": []},
            "route_report": {
                "ok": True,
                "delivery_route": {"ready": True, "selected_channel": "telegram", "selected_by": "tool_runtime_binding"},
                "delivery_guard": {"delivery_state": "no_actionable_items"},
                "stage_packets": {"ready": True, "errors": []},
                "safe_work_results": {"ready": True, "errors": []},
                "receipt_observation_count": 1,
                "actionable_count": 0,
            },
        }

    def _fake_artifacts(**kwargs: object) -> dict[str, object]:
        _capture_timeout("artifacts", **kwargs)
        return {"probe_ok": True, "approval_callback_dir_exists": True, "approval_callback_dir_writable": True}

    def _fake_approval_capture(**kwargs: object) -> dict[str, object]:
        _capture_timeout("approval_capture", **kwargs)
        return _fake_approval_capture_probe(**kwargs)

    def _fake_gmail_draft(**kwargs: object) -> dict[str, object]:
        _capture_timeout("gmail_draft", **kwargs)
        return {"probe_ok": True, "status": "no_pending_draft", "source": "docker_compose_exec"}

    def _fake_source_coverage(**kwargs: object) -> dict[str, object]:
        _capture_timeout("source_coverage", **kwargs)
        return _fake_source_coverage_probe(**kwargs)

    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_route", _fake_route)
    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_artifacts", _fake_artifacts)
    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_approval_capture", _fake_approval_capture)
    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_gmail_draft", _fake_gmail_draft)
    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_source_coverage", _fake_source_coverage)

    receipt = module.build_proactive_ooda_operator_status(
        output_path=tmp_path / "ea_proactive_ooda_operator_status.generated.json",
        generated_at="2026-06-29T08:01:00Z",
        report_args=Namespace(principal_id="exec-1"),
    )

    assert receipt["route_probe_runtime_service"] == "ea-proactive-ooda"
    assert captured == {
        "route": 180.0,
        "artifacts": 180.0,
        "gmail_draft": 180.0,
        "source_coverage": 180.0,
    }
    assert receipt["approval_capture"]["checked"] is False


def test_build_operator_status_reuses_route_artifact_probe(tmp_path: Path, monkeypatch) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")
    artifact_calls: list[object] = []
    route_artifact = {
        "probe_ok": True,
        "source": "docker_compose_exec",
        "approval_callback_dir_exists": True,
        "approval_callback_dir_writable": True,
        "approval_callback_record_count": 1,
        "approval_callback_pending_count": 1,
        "current_packet_callback_record_count": 1,
        "current_packet_callback_pending_count": 1,
        "current_packet_live_callback_record_count": 1,
        "current_packet_live_pending_count": 1,
        "stage_packet": {"packet_ref": "stage_packet:pkt-route"},
        "safe_work_result": {"result_ref": "safe_work_result:res-route"},
    }

    def _fake_route(**_kwargs: object) -> dict[str, object]:
        return {
            "probe_ok": True,
            "source": "docker_compose_exec",
            "runtime_service": "ea-proactive-ooda",
            "observed_at": "2026-07-01T12:00:00Z",
            "live_receipt_checked": True,
            "live_receipt": {"ok": True, "receipt_path": "/app/state/proactive_ooda/live-receipt.json", "errors": []},
            "artifact_probe": route_artifact,
            "route_report": {
                "ok": True,
                "delivery_route": {"ready": True, "selected_channel": "telegram", "selected_by": "tool_runtime_binding"},
                "delivery_guard": {"delivery_state": "eligible"},
                "stage_packets": {"ready": True, "errors": []},
                "safe_work_results": {"ready": True, "errors": []},
                "receipt_observation_count": 1,
                "actionable_count": 1,
            },
        }

    def _unexpected_artifacts(**kwargs: object) -> dict[str, object]:
        artifact_calls.append(kwargs)
        raise AssertionError("route artifact probe should be reused")

    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_route", _fake_route)
    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_artifacts", _unexpected_artifacts)
    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_approval_capture", _fake_approval_capture_probe)
    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_gmail_draft", lambda **_kwargs: {"probe_ok": True, "status": "ready"})
    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_source_coverage", _fake_source_coverage_gap_probe)

    receipt = module.build_proactive_ooda_operator_status(
        output_path=tmp_path / "ea_proactive_ooda_operator_status.generated.json",
        generated_at="2026-07-01T12:01:00Z",
        report_args=Namespace(principal_id="exec-1"),
    )

    assert artifact_calls == []
    assert receipt["approval_capture_surface"]["source"] == "docker_compose_exec"
    assert receipt["approval_capture_surface"]["current_packet_callback_record_count"] == 1


def test_build_operator_status_uses_local_artifact_probe_when_route_skips_artifacts(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")
    monkeypatch.setattr(module.ea_live_ops, "probe_provider_cost_pressure", _fake_provider_cost_pressure_probe)

    local_artifact = {
        "source": "local_filesystem",
        "artifact_resolution_source": "host_runtime_fallback",
        "stage_packet": {
            "schema": "proactive_ooda.stage_packet.v1",
            "packet_ref": "stage_packet:packet-1",
            "stage": {"kind": "approval_packet"},
            "approval": {"required": True},
        },
        "safe_work_result": {
            "schema": "proactive_ooda.safe_work_result.v1",
            "result_ref": "safe_work_result:result-1",
            "status": "staged_for_user_decision",
            "approval": {"required": True},
            "approval_prompt": "Approve this staged candidate.",
            "staged_action_url": "https://example.test/candidate",
            "audit": {"status": "pass", "issues": []},
        },
        "run_receipt": {
            "notification_status": "sent",
            "item_count": 1,
            "delivery_message_ids": ["msg-1"],
        },
        "approval_outcome": {},
        "approval_callback_dir_exists": True,
        "approval_callback_dir_writable": True,
        "approval_callback_record_count": 1,
        "approval_callback_pending_count": 1,
        "approval_callback_raw_pending_count": 1,
        "approval_callback_live_pending_count": 1,
        "approval_callback_unexpired_pending_count": 1,
        "approval_callback_noncurrent_pending_count": 0,
        "approval_callback_stale_pending_count": 0,
        "approval_callback_expired_pending_count": 0,
        "approval_callback_recorded_count": 0,
        "approval_callback_expired_count": 0,
        "approval_callback_superseded_count": 0,
        "approval_callback_terminal_count": 0,
        "current_packet_callback_record_count": 1,
        "current_packet_callback_pending_count": 1,
        "current_packet_callback_raw_pending_count": 1,
        "current_packet_callback_stale_pending_count": 0,
        "current_packet_callback_expired_pending_count": 0,
        "current_packet_callback_recorded_count": 0,
        "current_packet_callback_expired_count": 0,
        "current_packet_callback_superseded_count": 0,
        "current_packet_live_callback_record_count": 1,
        "current_packet_live_pending_count": 1,
        "current_packet_callback_latest_status": "pending",
        "current_packet_callback_latest_expired": False,
        "current_packet_callback_latest_created_at": "2026-06-28T14:00:00Z",
        "current_packet_callback_latest_expires_at": "2099-01-01T00:00:00Z",
        "current_packet_callback_latest_age_seconds": 60,
        "current_packet_callback_latest_seconds_until_expiry": 3600,
    }

    local_probe_calls: list[dict[str, object]] = []

    def _fake_local_artifact_probe(**kwargs: object) -> dict[str, object]:
        local_probe_calls.append(dict(kwargs))
        return dict(local_artifact)

    def _fake_route(**kwargs: object) -> dict[str, object]:
        assert kwargs.get("include_artifact_probe") is False
        return {
            "probe_ok": True,
            "source": "docker_compose_exec",
            "runtime_service": "ea-proactive-ooda",
            "observed_at": "2026-07-01T12:00:00Z",
            "live_receipt_checked": True,
            "live_receipt": {
                "ok": True,
                "receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json",
                "errors": [],
            },
            "artifact_probe": {},
            "route_report": {
                "ok": True,
                "delivery_route": {"ready": True, "selected_channel": "telegram", "selected_by": "tool_runtime_binding"},
                "delivery_guard": {"delivery_state": "eligible"},
                "stage_packets": {"ready": True, "errors": []},
                "safe_work_results": {"ready": True, "errors": []},
                "receipt_observation_count": 1,
                "actionable_count": 1,
            },
        }

    monkeypatch.setattr(module, "_local_artifact_probe", _fake_local_artifact_probe)
    monkeypatch.setattr(
        module,
        "_route_live_receipt_host_path",
        lambda _route_probe: Path("/host/provider-ledger/proactive_ooda_latest_run.generated.json"),
    )
    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_route", _fake_route)
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_artifacts",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("live artifact probe should not run")),
    )
    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_approval_capture", _fake_approval_capture_probe)
    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_gmail_draft", lambda **_kwargs: {"probe_ok": True, "status": "ready"})
    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_source_coverage", _fake_source_coverage_probe)

    receipt = module.build_proactive_ooda_operator_status(
        output_path=tmp_path / "ea_proactive_ooda_operator_status.generated.json",
        generated_at="2026-07-01T12:01:00Z",
        report_args=Namespace(principal_id="exec-1"),
        skip_provider_cost_pressure_probe=False,
    )

    assert local_probe_calls
    assert local_probe_calls[0]["allow_live_runtime_probe"] is True
    assert str(local_probe_calls[0]["live_receipt_path"]) == "/host/provider-ledger/proactive_ooda_latest_run.generated.json"
    assert receipt["provider_cost_pressure"]["checked"] is True
    assert receipt["provider_cost_pressure"]["primary_background_provider"] == "onemin"
    assert receipt["approval_capture_surface"]["source"] == "local_filesystem"
    assert receipt["approval_capture_surface"]["current_packet_live_pending_count"] == 1


def test_host_path_for_runtime_container_path_translates_provider_ledger_mount(monkeypatch) -> None:
    module = _load_script()
    monkeypatch.setattr(
        module,
        "_runtime_container_mounts",
        lambda _container_name: [
            {
                "Source": "/var/lib/docker/volumes/ea_ea_provider_ledger/_data",
                "Destination": "/data/provider-ledger",
            }
        ],
    )

    resolved = module._host_path_for_runtime_container_path(  # noqa: SLF001
        "/data/provider-ledger/proactive_ooda_latest_run.generated.json"
    )

    assert resolved == Path("/var/lib/docker/volumes/ea_ea_provider_ledger/_data/proactive_ooda_latest_run.generated.json")


def test_materialize_proactive_ooda_operator_status_keeps_explicit_artifact_dirs_on_local_probe(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_script()
    local_probe_calls: list[dict[str, object]] = []

    def _fake_local_artifact_probe(**kwargs: object) -> dict[str, object]:
        local_probe_calls.append(dict(kwargs))
        return {
            "source": "local_filesystem",
            "artifact_resolution_source": "host_runtime_fallback",
            "stage_packet": {},
            "safe_work_result": {},
            "run_receipt": {},
            "approval_outcome": {},
        }

    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_route",
        lambda **_kwargs: {
            "probe_ok": True,
            "source": "docker_compose_exec",
            "runtime_service": "ea-proactive-ooda",
            "observed_at": "2026-07-01T12:00:00Z",
            "live_receipt_checked": True,
            "live_receipt": {"ok": True, "receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json", "errors": []},
            "artifact_probe": {},
            "route_report": {
                "ok": True,
                "delivery_route": {"ready": True, "selected_channel": "telegram", "selected_by": "tool_runtime_binding"},
                "delivery_guard": {"delivery_state": "no_actionable_items"},
                "stage_packets": {"ready": True, "errors": []},
                "safe_work_results": {"ready": True, "errors": []},
                "receipt_observation_count": 1,
                "actionable_count": 0,
            },
        },
    )
    monkeypatch.setattr(module, "_local_artifact_probe", _fake_local_artifact_probe)
    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_gmail_draft", lambda **_kwargs: {"probe_ok": True, "status": "ready"})
    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_source_coverage", _fake_source_coverage_probe)

    module.build_proactive_ooda_operator_status(
        output_path=tmp_path / "ea_proactive_ooda_operator_status.generated.json",
        generated_at="2026-07-01T12:01:00Z",
        report_args=Namespace(
            principal_id="exec-1",
            stage_packet_dir=str(tmp_path / "custom-stage-packets"),
        ),
    )

    assert local_probe_calls
    assert local_probe_calls[0]["allow_live_runtime_probe"] is False


def test_materialize_proactive_ooda_operator_status_blocks_current_safe_work_audit_review(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")

    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_route",
        lambda **_kwargs: {
            "probe_ok": True,
            "source": "docker_compose_exec",
            "runtime_service": "ea-proactive-ooda",
            "observed_at": "2026-06-29T08:00:00Z",
            "live_receipt_checked": True,
            "live_receipt": {
                "ok": True,
                "receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json",
                "errors": [],
            },
            "route_report": {
                "ok": True,
                "delivery_route": {"ready": True, "selected_channel": "telegram", "selected_by": "tool_runtime_binding"},
                "delivery_guard": {"delivery_state": "eligible"},
                "stage_packets": {"ready": True, "errors": []},
                "safe_work_results": {"ready": True, "errors": []},
                "receipt_observation_count": 1,
                "actionable_count": 1,
            },
        },
    )
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_artifacts",
        lambda **_kwargs: {
            "probe_ok": True,
            "source": "docker_compose_exec",
            "safe_work_result": {
                "schema": "proactive_ooda.safe_work_result.v1",
                "status": "blocked_needs_research_input",
                "audit": {
                    "status": "review",
                    "issues": [
                        {
                            "code": "top_candidate_not_provider_like",
                            "severity": "warn",
                            "detail": "Candidate details stay out of operator status.",
                        }
                    ],
                },
            },
        },
    )
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_gmail_draft",
        lambda **_kwargs: {"probe_ok": True, "status": "no_pending_draft", "source": "docker_compose_exec"},
    )
    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_source_coverage", _fake_source_coverage_gap_probe)
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_approval_capture",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("audit-blocked packets should not probe approval capture")),
    )

    receipt = module.build_proactive_ooda_operator_status(
        output_path=tmp_path / "ea_proactive_ooda_operator_status.generated.json",
        generated_at="2026-06-29T08:01:00Z",
        report_args=Namespace(principal_id="exec-1"),
    )

    assert receipt["status"] == "blocked_local_runtime"
    assert receipt["reason"] == "safe_work_audit_review"
    assert receipt["next_action"] == "repair_proactive_safe_work_audit"
    assert receipt["next_action_href"] == "https://myexternalbrain.com/app/queue"
    assert receipt["operator_action_state"] == "recovery_required"
    assert receipt["safe_work_audit"]["present"] is True
    assert receipt["safe_work_audit"]["audit_status"] == "review"
    assert receipt["safe_work_audit"]["delivery_allowed"] is False
    assert receipt["safe_work_audit"]["blocks_operator_followthrough"] is True
    assert receipt["safe_work_audit"]["issue_codes"] == ["top_candidate_not_provider_like"]
    assert receipt["safe_work_audit"]["privacy"]["raw_issue_details_exposed"] is False


def test_materialize_proactive_ooda_operator_status_surfaces_redacted_browser_handoff_recovery(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")

    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_route",
        lambda **_kwargs: {
            "probe_ok": True,
            "source": "docker_compose_exec",
            "runtime_service": "ea-proactive-ooda",
            "observed_at": "2026-07-04T11:20:00Z",
            "live_receipt_checked": True,
            "live_receipt": {
                "ok": True,
                "receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json",
                "errors": [],
            },
            "route_report": {
                "ok": True,
                "delivery_route": {
                    "ready": True,
                    "selected_channel": "telegram",
                    "selected_by": "tool_runtime_binding",
                },
                "delivery_guard": {"delivery_state": "eligible"},
                "stage_packets": {"ready": True, "errors": []},
                "safe_work_results": {"ready": True, "errors": []},
                "receipt_observation_count": 1,
                "actionable_count": 0,
            },
        },
    )
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_artifacts",
        lambda **_kwargs: {
            "probe_ok": True,
            "source": "docker_compose_exec",
            "stage_packet": {
                "schema": "proactive_ooda.stage_packet.v1",
                "stage": {"payload": {"site": "www.amazon.de"}},
            },
            "safe_work_result": {
                "schema": "proactive_ooda.safe_work_result.v1",
                "status": "blocked_human_handoff_required",
                "approval_prompt": "Provide the verification code sent to the phone ending 419.",
                "audit": {
                    "status": "review",
                    "issues": [{"code": "browser_handoff_required", "severity": "info"}],
                },
                "browser_action_receipt": {
                    "schema": "proactive_ooda.browser_action_receipt.v1",
                    "site": "www.amazon.de",
                    "status": "blocked_human_handoff_required",
                    "user_action_required": True,
                    "staged_artifact_present": False,
                    "handoff": {
                        "required": True,
                        "blocker_code": "mfa_code_required",
                        "reason": "Multi-factor verification requires user action.",
                        "next_action": "complete_browser_handoff_then_resume_ooda_task",
                        "resume_instruction": "After the code is provided, resume the browser task from the authenticated session.",
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
                    },
                    "privacy": {
                        "raw_credentials_stored": False,
                        "raw_cookie_or_session_stored": False,
                    },
                },
            },
        },
    )
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_gmail_draft",
        lambda **_kwargs: {"probe_ok": True, "status": "no_pending_draft", "source": "docker_compose_exec"},
    )
    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_source_coverage", _fake_source_coverage_probe)
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_approval_capture",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("browser handoff packets should not probe approval capture")),
    )

    receipt = module.build_proactive_ooda_operator_status(
        output_path=tmp_path / "ea_proactive_ooda_operator_status.generated.json",
        generated_at="2026-07-04T11:21:00Z",
        report_args=Namespace(principal_id="exec-1"),
    )

    assert receipt["status"] == "ready_with_recovery_action"
    assert receipt["reason"] == "browser_handoff_required"
    assert receipt["summary"].startswith("Proactive OODA is waiting on a live browser handoff for www.amazon.de")
    assert "phone ending 419" in receipt["summary"]
    assert receipt["next_action"] == "complete_browser_handoff_then_resume_ooda_task"
    assert receipt["next_action_href"] == "https://myexternalbrain.com/app/queue"
    assert receipt["next_action_label"] == "Resume browser handoff"
    assert receipt["next_action_method"] == "get"
    assert receipt["operator_action_state"] == "recovery_required"
    assert receipt["delivery_guard"]["delivery_state"] == "browser_handoff_pending"
    assert receipt["delivery_guard"]["user_action_required"] is True
    assert receipt["actionable_count"] == 1
    assert receipt["safe_work_audit"]["present"] is True
    assert receipt["safe_work_audit"]["audit_status"] == "review"
    assert receipt["safe_work_audit"]["delivery_allowed"] is True
    assert receipt["safe_work_audit"]["browser_handoff_user_action_required"] is True
    assert receipt["safe_work_audit"]["blocks_operator_followthrough"] is False
    assert receipt["browser_handoff"]["present"] is True
    assert receipt["browser_handoff"]["required"] is True
    assert receipt["browser_handoff"]["site_host"] == "www.amazon.de"
    assert receipt["browser_handoff"]["blocker_code"] == "mfa_code_required"
    assert receipt["browser_handoff"]["next_action"] == "complete_browser_handoff_then_resume_ooda_task"
    assert receipt["browser_handoff"]["challenge"]["available_channels"] == ["whatsapp", "phone"]
    assert receipt["browser_handoff"]["challenge"]["destination_hint"] == "phone ending 419"
    assert receipt["browser_handoff"]["challenge"]["raw_destination_stored"] is False
    assert receipt["browser_handoff"]["privacy"]["raw_credentials_stored"] is False
    assert receipt["browser_handoff"]["privacy"]["raw_cookie_or_session_stored"] is False


def test_materialize_proactive_ooda_operator_status_suppresses_single_official_info_link(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")

    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_route",
        lambda **_kwargs: {
            "probe_ok": True,
            "source": "docker_compose_exec",
            "runtime_service": "ea-proactive-ooda",
            "observed_at": "2026-07-01T08:00:00Z",
            "live_receipt_checked": True,
            "live_receipt": {
                "ok": True,
                "receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json",
                "errors": [],
            },
            "route_report": {
                "ok": True,
                "delivery_route": {"ready": True, "selected_channel": "telegram", "selected_by": "tool_runtime_binding"},
                "delivery_guard": {"delivery_state": "eligible"},
                "stage_packets": {"ready": True, "errors": []},
                "safe_work_results": {"ready": True, "errors": []},
                "receipt_observation_count": 1,
                "actionable_count": 1,
            },
        },
    )
    candidate = {
        "label": "Official City of Vienna information portal",
        "url": "https://www.wien.gv.at/english/",
        "source": "official_site",
    }
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_artifacts",
        lambda **_kwargs: {
            "probe_ok": True,
            "source": "docker_compose_exec",
            "stage_packet": {
                "schema": "proactive_ooda.stage_packet.v1",
                "stage": {
                    "payload": {
                        "work_type": "compare_options",
                        "candidate_items": [candidate],
                        "selection_criteria": ["official source", "reversible link only"],
                    }
                },
                "safe_work_order": {
                    "work_type": "compare_options",
                    "input_contract": {
                        "candidate_items": [candidate],
                        "selection_criteria": ["official source", "reversible link only"],
                    },
                },
            },
            "safe_work_result": {
                "schema": "proactive_ooda.safe_work_result.v1",
                "status": "staged_for_user_decision",
                "work_type": "compare_options",
                "recommended_option_or_draft": {"kind": "shortlist_candidate", "value": candidate},
                "shortlist": [candidate],
                "audit": {"status": "pass", "issues": []},
            },
        },
    )
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_gmail_draft",
        lambda **_kwargs: {"probe_ok": True, "status": "no_pending_draft", "source": "docker_compose_exec"},
    )
    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_source_coverage", _fake_source_coverage_probe)
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_approval_capture",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("filtered non-material packets should not probe approval capture")),
    )

    receipt = module.build_proactive_ooda_operator_status(
        output_path=tmp_path / "ea_proactive_ooda_operator_status.generated.json",
        generated_at="2026-07-01T08:01:00Z",
        report_args=Namespace(principal_id="exec-1"),
    )

    assert receipt["status"] == "ready_with_live_receipt"
    assert receipt["reason"] == "ready"
    assert receipt["next_action"] == "maintain_proactive_ooda_runtime"
    assert receipt["safe_work_audit"]["audit_status"] == "filtered"
    assert receipt["safe_work_audit"]["audit_passed"] is False
    assert receipt["safe_work_audit"]["filtered_non_material"] is True
    assert receipt["safe_work_audit"]["delivery_allowed"] is False
    assert receipt["safe_work_audit"]["blocks_operator_followthrough"] is False
    assert receipt["safe_work_audit"]["blocking_reason"] == ""
    assert receipt["safe_work_audit"]["issue_codes"] == ["single_official_info_link_not_decision_ready"]
    assert receipt["safe_work_audit"]["privacy"]["raw_candidate_exposed"] is False


def test_materialize_proactive_ooda_operator_status_records_filtered_current_artifact_without_recovery(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")

    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_route",
        lambda **_kwargs: {
            "probe_ok": True,
            "source": "docker_compose_exec",
            "runtime_service": "ea-proactive-ooda",
            "observed_at": "2026-07-01T08:20:00Z",
            "live_receipt_checked": True,
            "live_receipt": {
                "ok": True,
                "receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json",
                "errors": [],
            },
            "route_report": {
                "ok": True,
                "delivery_route": {"ready": True, "selected_channel": "telegram", "selected_by": "tool_runtime_binding"},
                "delivery_guard": {"delivery_state": "eligible"},
                "stage_packets": {"ready": True, "errors": []},
                "safe_work_results": {"ready": True, "errors": []},
                "receipt_observation_count": 1,
                "actionable_count": 1,
            },
        },
    )
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_artifacts",
        lambda **_kwargs: {
            "probe_ok": True,
            "source": "docker_compose_exec",
            "stage_packet": {},
            "safe_work_result": {},
            "artifact_filter_reason": "single_official_info_link_not_decision_ready",
        },
    )
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_gmail_draft",
        lambda **_kwargs: {"probe_ok": True, "status": "no_pending_draft", "source": "docker_compose_exec"},
    )
    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_source_coverage", _fake_source_coverage_probe)
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_approval_capture",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("filtered non-material packets should not probe approval capture")),
    )

    receipt = module.build_proactive_ooda_operator_status(
        output_path=tmp_path / "ea_proactive_ooda_operator_status.generated.json",
        generated_at="2026-07-01T08:21:00Z",
        report_args=Namespace(principal_id="exec-1"),
    )

    assert receipt["status"] == "ready_with_live_receipt"
    assert receipt["reason"] == "ready"
    assert receipt["next_action"] == "maintain_proactive_ooda_runtime"
    assert receipt["operator_action_state"] == "clear"
    assert receipt["safe_work_audit"]["present"] is False
    assert receipt["current_artifact_filter"]["present"] is True
    assert receipt["current_artifact_filter"]["filter_status"] == "suppressed_non_material"
    assert receipt["current_artifact_filter"]["requires_recovery"] is False
    assert receipt["current_artifact_filter"]["blocking_reason"] == ""
    assert receipt["current_artifact_filter"]["next_action"] == ""
    assert receipt["current_artifact_filter"]["issue_codes"] == ["single_official_info_link_not_decision_ready"]
    assert receipt["current_artifact_filter"]["privacy"]["raw_candidate_exposed"] is False


def test_materialize_proactive_ooda_operator_status_recovers_on_internal_action_packet(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_route",
        lambda **_kwargs: {
            "probe_ok": True,
            "source": "docker_compose_exec",
            "runtime_service": "ea-proactive-ooda",
            "observed_at": "2026-07-04T14:00:00Z",
            "live_receipt_checked": True,
            "live_receipt": {
                "ok": True,
                "receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json",
                "errors": [],
            },
            "route_report": {
                "ok": True,
                "delivery_route": {"ready": True, "selected_channel": "telegram", "selected_by": "tool_runtime_binding"},
                "delivery_guard": {"delivery_state": "eligible"},
                "stage_packets": {"ready": True, "errors": []},
                "safe_work_results": {"ready": True, "errors": []},
                "receipt_observation_count": 1,
                "actionable_count": 1,
            },
        },
    )
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_artifacts",
        lambda **_kwargs: {
            "probe_ok": True,
            "source": "docker_compose_exec",
            "approval_outcome_path": "/app/state/proactive_ooda/approval-outcomes.jsonl",
            "approval_callback_dir": "/app/state/proactive_ooda/approval-callbacks",
            "approval_callback_dir_writable": True,
            "current_packet_callback_record_count": 1,
            "current_packet_callback_pending_count": 1,
            "current_packet_callback_raw_pending_count": 1,
            "current_packet_live_callback_record_count": 1,
            "current_packet_live_pending_count": 1,
            "stage_packet": {
                "packet_ref": "packet-internal-1",
                "stage": {
                    "kind": "internal_action",
                    "payload": {
                        "work_type": "record_internal_action",
                        "approval_prompt": "Record this internal action?",
                        "approval_url": "https://myexternalbrain.com/app/queue",
                    },
                },
                "safe_work_order": {"work_type": "record_internal_action"},
                "approval": {"required": True},
            },
            "safe_work_result": {
                "result_ref": "result-internal-1",
                "status": "staged_for_user_decision",
                "work_type": "record_internal_action",
                "approval": {"required": True},
                "approval_prompt": "Record this internal action?",
                "staged_action_url": "https://myexternalbrain.com/app/queue",
                "audit": {"status": "pass", "issues": []},
            },
        },
    )
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_gmail_draft",
        lambda **_kwargs: {"probe_ok": True, "status": "no_pending_draft", "source": "docker_compose_exec"},
    )
    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_source_coverage", _fake_source_coverage_probe)
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_approval_capture",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("internal-action packets must not probe approval followthrough")
        ),
    )

    receipt = module.build_proactive_ooda_operator_status(
        output_path=tmp_path / "ea_proactive_ooda_operator_status.generated.json",
        generated_at="2026-07-04T14:01:00Z",
        report_args=Namespace(principal_id="exec-1"),
    )

    assert receipt["status"] == "ready_with_recovery_action"
    assert receipt["reason"] == "internal_action_not_assistant_grade"
    assert receipt["summary"] == (
        "The proactive OODA mechanics have evidence, but the selected packet is not assistant-grade enough "
        "to prove production readiness."
    )
    assert receipt["next_action"] == "stage_fresh_assistant_grade_proactive_packet"
    assert receipt["next_action_href"] == "https://myexternalbrain.com/app/queue"
    assert receipt["next_action_label"] == "Open queue"
    assert receipt["next_action_method"] == "get"
    assert receipt["operator_action_state"] == "recovery_required"
    assert receipt["assistant_grade_packet"]["present"] is True
    assert receipt["assistant_grade_packet"]["stage_kind"] == "internal_action"
    assert receipt["assistant_grade_packet"]["work_type"] == "record_internal_action"
    assert receipt["assistant_grade_packet"]["requires_recovery"] is True
    assert receipt["assistant_grade_packet"]["blocking_reason"] == "internal_action_not_assistant_grade"
    assert receipt["assistant_grade_packet"]["next_action"] == "stage_fresh_assistant_grade_proactive_packet"
    assert receipt["approval_capture_surface"] == {}
    assert receipt["approval_capture"] == {}


def test_materialize_proactive_ooda_operator_status_uses_historical_browse_backed_packet_for_assistant_grade(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_route",
        lambda **_kwargs: {
            "probe_ok": True,
            "source": "docker_compose_exec",
            "runtime_service": "ea-proactive-ooda",
            "observed_at": "2026-07-04T14:00:00Z",
            "live_receipt_checked": True,
            "live_receipt": {
                "ok": True,
                "receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json",
                "errors": [],
                "generated_at": "2026-07-04T13:59:00Z",
                "notification_status": "sent",
            },
            "route_report": {
                "ok": True,
                "delivery_route": {"ready": True, "selected_channel": "telegram", "selected_by": "tool_runtime_binding"},
                "delivery_guard": {"delivery_state": "eligible"},
                "stage_packets": {"ready": True, "errors": []},
                "safe_work_results": {"ready": True, "errors": []},
                "receipt_observation_count": 1,
                "actionable_count": 1,
            },
        },
    )

    def _artifact_probe(**kwargs):
        if kwargs.get("prefer_browse_backed_delivery"):
            return {
                "probe_ok": True,
                "source": "docker_compose_exec",
                "assistant_grade_bundle_source": "historical_browse_backed_proof_bundle",
                "stage_packet_path": "/data/provider-ledger/proactive_ooda_stage_packets/pkt-live.json",
                "safe_work_result_path": "/data/provider-ledger/proactive_ooda_safe_work_results/res-live.json",
                "stage_packet": {
                    "schema": "proactive_ooda.stage_packet.v1",
                    "packet_ref": "packet-live-1",
                    "stage": {"kind": "research_packet", "payload": {"work_type": "compare_options"}},
                    "safe_work_order": {"work_type": "compare_options"},
                    "approval": {"required": True},
                },
                "safe_work_result": {
                    "schema": "proactive_ooda.safe_work_result.v1",
                    "result_ref": "result-live-1",
                    "status": "staged_for_user_decision",
                    "work_type": "compare_options",
                    "approval": {"required": True},
                    "approval_prompt": "Approve the shortlist?",
                    "staged_action_url": "https://myexternalbrain.com/app/queue",
                    "recommended_option_or_draft": {
                        "kind": "shortlist_candidate",
                        "value": {"label": "Live Source", "url": "https://example.test/live"},
                    },
                    "shortlist": [{"label": "Live Source"}],
                    "audit": {"status": "pass", "issues": []},
                    "execution_receipt": {
                        "network_fetch_count": 1,
                        "network_fetch_success_count": 1,
                        "page_checks": [{"url": "https://example.test/live", "reachable": True}],
                        "irreversible_actions_attempted": [],
                    },
                },
                "run_receipt": {"notification_status": "sent", "item_count": 1, "delivery_channel": "telegram"},
            }
        return {
            "probe_ok": True,
            "source": "docker_compose_exec",
            "approval_outcome_path": "/data/provider-ledger/proactive_ooda_latest_approval_outcome.generated.json",
            "approval_callback_dir": "/data/provider-ledger/proactive_ooda_approval_callbacks",
            "approval_callback_dir_exists": True,
            "approval_callback_dir_writable": True,
            "approval_callback_record_count": 1,
            "approval_callback_pending_count": 1,
            "approval_callback_raw_pending_count": 1,
            "approval_callback_live_pending_count": 1,
            "approval_callback_unexpired_pending_count": 1,
            "approval_callback_noncurrent_pending_count": 0,
            "approval_callback_stale_pending_count": 0,
            "approval_callback_recorded_count": 0,
            "current_packet_callback_record_count": 1,
            "current_packet_callback_pending_count": 1,
            "current_packet_callback_raw_pending_count": 1,
            "current_packet_live_callback_record_count": 1,
            "current_packet_live_pending_count": 1,
            "stage_packet": {
                "schema": "proactive_ooda.stage_packet.v1",
                "packet_ref": "packet-internal-1",
                "stage": {"kind": "internal_action", "payload": {"work_type": "record_internal_action"}},
                "safe_work_order": {"work_type": "record_internal_action"},
                "approval": {"required": True},
            },
            "safe_work_result": {
                "schema": "proactive_ooda.safe_work_result.v1",
                "result_ref": "result-internal-1",
                "status": "staged_for_user_decision",
                "work_type": "record_internal_action",
                "approval": {"required": True},
                "approval_prompt": "Record this internal action?",
                "staged_action_url": "https://myexternalbrain.com/app/queue",
                "audit": {"status": "pass", "issues": []},
            },
            "run_receipt": {"notification_status": "sent", "item_count": 1, "delivery_channel": "telegram"},
        }

    monkeypatch.setattr(module, "_local_artifact_probe", _artifact_probe)
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_gmail_draft",
        lambda **_kwargs: {"probe_ok": True, "status": "no_pending_draft", "source": "docker_compose_exec"},
    )
    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_source_coverage", _fake_source_coverage_probe)
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_approval_capture",
        lambda **_kwargs: {
            "checked": True,
            "probe_ok": True,
            "ready": True,
            "status": "ready",
            "source": "docker_compose_exec",
            "privacy": {
                "raw_callback_token_exposed": False,
                "raw_principal_id_exposed": False,
                "raw_chat_ref_exposed": False,
                "raw_packet_ref_exposed": False,
                "raw_staged_artifact_ref_exposed": False,
            },
        },
    )

    receipt = module.build_proactive_ooda_operator_status(
        output_path=tmp_path / "ea_proactive_ooda_operator_status.generated.json",
        generated_at="2026-07-04T14:01:00Z",
        report_args=Namespace(principal_id="exec-1"),
    )

    assert receipt["status"] == "ready_with_live_receipt"
    assert receipt["reason"] == "ready"
    assert receipt["next_action"] != "stage_fresh_assistant_grade_proactive_packet"
    assert receipt["assistant_grade_packet"]["bundle_source"] == "historical_browse_backed_proof_bundle"
    assert receipt["assistant_grade_packet"]["stage_kind"] == "research_packet"
    assert receipt["assistant_grade_packet"]["work_type"] == "compare_options"
    assert receipt["assistant_grade_packet"]["requires_recovery"] is False
    assert receipt["stage_packets"]["selected_packet_present"] is True
    assert receipt["stage_packets"]["selected_bundle_source"] == "historical_browse_backed_proof_bundle"
    assert receipt["stage_packets"]["selected_packet_path"] == "/data/provider-ledger/proactive_ooda_stage_packets/pkt-live.json"
    assert receipt["stage_packets"]["packet_count"] == 1
    assert receipt["stage_packets"]["expected_packet_count"] == 1
    assert receipt["stage_packets"]["safe_work_order_count"] == 1
    assert receipt["safe_work_results"]["selected_result_present"] is True
    assert receipt["safe_work_results"]["selected_bundle_source"] == "historical_browse_backed_proof_bundle"
    assert receipt["safe_work_results"]["selected_result_path"] == "/data/provider-ledger/proactive_ooda_safe_work_results/res-live.json"
    assert receipt["safe_work_results"]["result_count"] == 1
    assert receipt["safe_work_results"]["expected_result_count"] == 1
    assert receipt["safe_work_results"]["schema_valid_count"] == 1
    assert receipt["approval_capture_surface"] != {}


def test_materialize_proactive_ooda_operator_status_rejects_historical_browse_backed_packet_without_decision_ready_material(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_route",
        lambda **_kwargs: {
            "probe_ok": True,
            "source": "docker_compose_exec",
            "runtime_service": "ea-proactive-ooda",
            "observed_at": "2026-07-09T04:11:06Z",
            "live_receipt_checked": True,
            "live_receipt": {
                "ok": True,
                "receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json",
                "errors": [],
                "generated_at": "2026-07-09T04:11:31Z",
                "notification_status": "sent",
            },
            "route_report": {
                "ok": True,
                "delivery_route": {"ready": True, "selected_channel": "telegram", "selected_by": "tool_runtime_binding"},
                "delivery_guard": {"delivery_state": "eligible"},
                "stage_packets": {"ready": True, "errors": []},
                "safe_work_results": {"ready": True, "errors": []},
                "receipt_observation_count": 1,
                "actionable_count": 1,
            },
        },
    )

    def _artifact_probe(**kwargs):
        if kwargs.get("prefer_browse_backed_delivery"):
            return {
                "probe_ok": True,
                "source": "local_filesystem",
                "assistant_grade_bundle_source": "historical_browse_backed_proof_bundle",
                "stage_packet_path": "/data/provider-ledger/proactive_ooda_stage_packets/pkt-review.json",
                "safe_work_result_path": "/data/provider-ledger/proactive_ooda_safe_work_results/res-review.json",
                "stage_packet": {
                    "schema": "proactive_ooda.stage_packet.v1",
                    "packet_ref": "packet-review-1",
                    "stage": {"kind": "decision_packet", "payload": {"work_type": "research"}},
                    "safe_work_order": {"work_type": "research"},
                    "approval": {"required": True},
                },
                "safe_work_result": {
                    "schema": "proactive_ooda.safe_work_result.v1",
                    "result_ref": "result-review-1",
                    "status": "staged_for_user_decision",
                    "work_type": "research",
                    "approval": {"required": True},
                    "audit": {
                        "status": "review",
                        "issues": [{"code": "no_decision_ready_material", "severity": "warn"}],
                    },
                    "execution_receipt": {
                        "network_fetch_count": 0,
                        "network_fetch_success_count": 0,
                        "page_checks": [],
                        "irreversible_actions_attempted": [],
                    },
                },
                "run_receipt": {"notification_status": "sent", "item_count": 1, "delivery_channel": "telegram"},
            }
        return {
            "probe_ok": True,
            "source": "docker_compose_exec",
            "approval_outcome_path": "/data/provider-ledger/proactive_ooda_latest_approval_outcome.generated.json",
            "approval_callback_dir": "/data/provider-ledger/proactive_ooda_approval_callbacks",
            "approval_callback_dir_exists": True,
            "approval_callback_dir_writable": True,
            "approval_callback_record_count": 1,
            "approval_callback_pending_count": 0,
            "approval_callback_raw_pending_count": 0,
            "approval_callback_live_pending_count": 0,
            "approval_callback_unexpired_pending_count": 0,
            "approval_callback_noncurrent_pending_count": 0,
            "approval_callback_stale_pending_count": 0,
            "approval_callback_recorded_count": 1,
            "current_packet_callback_record_count": 0,
            "current_packet_callback_pending_count": 0,
            "current_packet_callback_raw_pending_count": 0,
            "current_packet_live_callback_record_count": 0,
            "current_packet_live_pending_count": 0,
            "stage_packet_path": "/data/provider-ledger/proactive_ooda_stage_packets/pkt-current.json",
            "safe_work_result_path": "/data/provider-ledger/proactive_ooda_safe_work_results/res-current.json",
            "stage_packet": {
                "schema": "proactive_ooda.stage_packet.v1",
                "packet_ref": "packet-internal-1",
                "stage": {"kind": "internal_action", "payload": {"work_type": "record_internal_action"}},
                "safe_work_order": {"work_type": "record_internal_action"},
                "approval": {"required": True},
            },
            "safe_work_result": {
                "schema": "proactive_ooda.safe_work_result.v1",
                "result_ref": "result-internal-1",
                "status": "staged_for_user_decision",
                "work_type": "record_internal_action",
                "approval": {"required": True},
                "approval_prompt": "Record this internal action?",
                "staged_action_url": "https://myexternalbrain.com/app/queue",
                "audit": {"status": "pass", "issues": []},
            },
            "run_receipt": {"notification_status": "sent", "item_count": 1, "delivery_channel": "telegram"},
        }

    monkeypatch.setattr(module, "_local_artifact_probe", _artifact_probe)
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_gmail_draft",
        lambda **_kwargs: {"probe_ok": True, "status": "no_pending_draft", "source": "docker_compose_exec"},
    )
    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_source_coverage", _fake_source_coverage_probe)
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_approval_capture",
        lambda **_kwargs: {
            "checked": True,
            "probe_ok": True,
            "ready": True,
            "status": "ready",
            "source": "docker_compose_exec",
            "privacy": {
                "raw_callback_token_exposed": False,
                "raw_principal_id_exposed": False,
                "raw_chat_ref_exposed": False,
                "raw_packet_ref_exposed": False,
                "raw_staged_artifact_ref_exposed": False,
            },
        },
    )

    receipt = module.build_proactive_ooda_operator_status(
        output_path=tmp_path / "ea_proactive_ooda_operator_status.generated.json",
        generated_at="2026-07-09T04:11:31Z",
        report_args=Namespace(principal_id="exec-1"),
    )

    assert receipt["status"] == "ready_with_recovery_action"
    assert receipt["reason"] == "internal_action_not_assistant_grade"
    assert receipt["assistant_grade_packet"]["bundle_source"] == "current_runtime_bundle"
    assert receipt["assistant_grade_packet"]["stage_kind"] == "internal_action"
    assert receipt["assistant_grade_packet"]["work_type"] == "record_internal_action"
    assert receipt["assistant_grade_packet"]["requires_recovery"] is True
    assert receipt["assistant_grade_packet"]["blocking_reason"] == "internal_action_not_assistant_grade"
    assert receipt["stage_packets"]["selected_bundle_source"] == "current_runtime_bundle"
    assert receipt["stage_packets"]["selected_packet_path"] == "/data/provider-ledger/proactive_ooda_stage_packets/pkt-current.json"
    assert receipt["safe_work_results"]["selected_bundle_source"] == "current_runtime_bundle"
    assert receipt["safe_work_results"]["selected_result_path"] == "/data/provider-ledger/proactive_ooda_safe_work_results/res-current.json"


def test_normalized_assistant_grade_packet_requires_transcript_action_intent() -> None:
    module = _load_script()

    packet = module._normalized_assistant_grade_packet(  # noqa: SLF001
        {
            "source": "docker_compose_exec",
            "assistant_grade_bundle_source": "current_runtime_bundle",
            "stage_packet": {
                "packet_ref": "packet-transcript-1",
                "stage": {
                    "kind": "research_packet",
                    "payload": {
                        "adapter_hint": "transcript_signal",
                        "work_type": "compare_options",
                        "draft_request_text": "background chatter and a passing remark",
                    },
                },
                "safe_work_order": {"work_type": "compare_options"},
                "approval": {"required": True},
            },
            "safe_work_result": {
                "result_ref": "result-transcript-1",
                "status": "staged_for_user_decision",
                "work_type": "compare_options",
                "approval": {"required": True},
                "approval_prompt": "Approve this shortlist?",
                "staged_action_url": "https://example.test/candidate",
                "audit": {"status": "pass", "issues": []},
                "recommended_option_or_draft": {
                    "kind": "shortlist_candidate",
                    "value": {"label": "Candidate", "url": "https://example.test/candidate"},
                },
                "shortlist": [{"label": "Candidate", "url": "https://example.test/candidate"}],
                "execution_receipt": {
                    "network_fetch_count": 1,
                    "network_fetch_success_count": 1,
                    "page_checks": [{"url": "https://example.test/candidate", "reachable": True}],
                    "irreversible_actions_attempted": [],
                },
            },
            "run_receipt": {
                "notification_status": "sent",
                "item_count": 1,
                "delivery_channel": "telegram",
            },
        }
    )

    assert packet["present"] is True
    assert packet["requires_recovery"] is True
    assert packet["blocking_reason"] == "transcript_signal_lacks_action_intent"
    assert packet["next_action"] == "stage_fresh_assistant_grade_proactive_packet"


def test_materialize_proactive_ooda_operator_status_explicit_live_receipt_still_uses_historical_browse_backed_packet(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_route",
        lambda **_kwargs: {
            "probe_ok": True,
            "source": "docker_compose_exec",
            "runtime_service": "ea-proactive-ooda",
            "observed_at": "2026-07-06T05:54:32Z",
            "live_receipt_checked": True,
            "live_receipt": {
                "ok": True,
                "receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json",
                "errors": [],
                "generated_at": "2026-07-06T04:54:04.435281+00:00",
                "notification_status": "sent",
            },
            "route_report": {
                "ok": True,
                "delivery_route": {"ready": True, "selected_channel": "telegram", "selected_by": "tool_runtime_binding"},
                "delivery_guard": {"delivery_state": "eligible"},
                "stage_packets": {"ready": True, "errors": []},
                "safe_work_results": {"ready": True, "errors": []},
                "receipt_observation_count": 1,
                "actionable_count": 1,
            },
        },
    )

    def _artifact_probe(**kwargs):
        if kwargs.get("prefer_browse_backed_delivery"):
            return {
                "probe_ok": True,
                "source": "docker_compose_exec",
                "assistant_grade_bundle_source": "historical_browse_backed_proof_bundle",
                "stage_packet_path": "/data/provider-ledger/proactive_ooda_stage_packets/pkt-live.json",
                "safe_work_result_path": "/data/provider-ledger/proactive_ooda_safe_work_results/res-live.json",
                "stage_packet": {
                    "schema": "proactive_ooda.stage_packet.v1",
                    "packet_ref": "packet-live-1",
                    "stage": {"kind": "research_packet", "payload": {"work_type": "compare_options"}},
                    "safe_work_order": {"work_type": "compare_options"},
                    "approval": {"required": True},
                },
                "safe_work_result": {
                    "schema": "proactive_ooda.safe_work_result.v1",
                    "result_ref": "result-live-1",
                    "status": "staged_for_user_decision",
                    "work_type": "compare_options",
                    "approval": {"required": True},
                    "approval_prompt": "Approve the shortlist?",
                    "staged_action_url": "https://example.test/review",
                    "recommended_option_or_draft": {
                        "kind": "shortlist_candidate",
                        "value": {"label": "Live Source", "url": "https://example.test/live"},
                    },
                    "shortlist": [{"label": "Live Source"}],
                    "audit": {"status": "pass", "issues": []},
                    "execution_receipt": {
                        "network_fetch_count": 1,
                        "network_fetch_success_count": 1,
                        "page_checks": [{"url": "https://example.test/live", "reachable": True}],
                        "irreversible_actions_attempted": [],
                    },
                },
                "run_receipt": {"notification_status": "sent", "item_count": 1, "delivery_channel": "telegram"},
            }
        return {
            "probe_ok": True,
            "source": "docker_compose_exec",
            "stage_packet": {
                "schema": "proactive_ooda.stage_packet.v1",
                "packet_ref": "packet-internal-1",
                "stage": {"kind": "internal_action", "payload": {"work_type": "record_internal_action"}},
                "safe_work_order": {"work_type": "record_internal_action"},
                "approval": {"required": True},
            },
            "safe_work_result": {
                "schema": "proactive_ooda.safe_work_result.v1",
                "result_ref": "result-internal-1",
                "status": "staged_for_user_decision",
                "work_type": "record_internal_action",
                "approval": {"required": True},
                "approval_prompt": "Record this internal action?",
                "staged_action_url": "https://myexternalbrain.com/app/queue",
                "audit": {"status": "pass", "issues": []},
            },
            "run_receipt": {"notification_status": "sent", "item_count": 1, "delivery_channel": "telegram"},
        }

    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_artifacts", _artifact_probe)
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_gmail_draft",
        lambda **_kwargs: {"probe_ok": True, "status": "no_pending_draft", "source": "docker_compose_exec"},
    )
    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_source_coverage", _fake_source_coverage_probe)
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_approval_capture",
        lambda **_kwargs: {
            "checked": True,
            "probe_ok": True,
            "ready": True,
            "status": "ready",
            "source": "docker_compose_exec",
            "privacy": {
                "raw_callback_token_exposed": False,
                "raw_principal_id_exposed": False,
                "raw_chat_ref_exposed": False,
                "raw_packet_ref_exposed": False,
                "raw_staged_artifact_ref_exposed": False,
            },
        },
    )

    receipt = module.build_proactive_ooda_operator_status(
        output_path=tmp_path / "ea_proactive_ooda_operator_status.generated.json",
        generated_at="2026-07-06T05:55:00Z",
        report_args=Namespace(principal_id="exec-1"),
        live_receipt_path=Path("/data/provider-ledger/proactive_ooda_latest_run.generated.json"),
    )

    assert receipt["status"] == "ready_with_live_receipt"
    assert receipt["reason"] == "ready"
    assert receipt["assistant_grade_packet"]["requires_recovery"] is False
    assert receipt["next_action"] in {
        "maintain_proactive_ooda_runtime",
        "record_proactive_ooda_approval_outcome",
    }


def test_materialize_proactive_ooda_operator_status_records_non_material_suppressed_projection_without_recovery(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_route",
        lambda **_kwargs: {
            "probe_ok": True,
            "source": "docker_compose_exec",
            "runtime_service": "ea-proactive-ooda",
            "observed_at": "2026-06-30T08:10:00Z",
            "live_receipt_checked": True,
            "live_receipt": {
                "ok": True,
                "receipt_path": "/app/state/proactive_ooda/live-receipt.json",
                "delivery_next_action": "",
                "delivery_route_error": "",
                "delivery_recovery_hint": "",
                "errors": [],
                "generated_at": "2026-06-30T08:09:00Z",
                "notification_status": "sent",
            },
            "route_report": {
                "ok": True,
                "delivery_route": {
                    "ready": True,
                    "route_error": "",
                    "recovery_hint": "",
                    "next_action": "",
                    "selected_channel": "telegram",
                    "selected_transport": "telegram",
                    "selected_by": "tool_runtime_binding",
                    "available_channels": ["telegram"],
                },
                "delivery_guard": {"delivery_state": "no_actionable_items", "armed_send": True},
                "stage_packets": {"ready": True, "errors": []},
                "safe_work_results": {"ready": True, "errors": []},
                "receipt_observation_count": 1,
                "actionable_count": 0,
                "source_mode": "postgres_observations",
            },
        },
    )
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_artifacts",
        lambda **_kwargs: {
            "probe_ok": True,
            "source": "docker_compose_exec",
            "action_required_only_quiet_receipt": {
                "generated_at": "2026-06-30T08:09:30Z",
                "notification_status": "deferred",
                "error_code": "no_user_action_required",
                "item_count": 2,
                "teable_sync": {
                    "status": "synced",
                    "projection_summary": {
                        "record_count": 1,
                        "suppressed_item_count": 2,
                        "suppressed_safe_work_review_count": 2,
                        "suppressed_projection_reasons": ["safe_work_audit_review"],
                        "suppressed_safe_work_issue_codes": ["no_decision_ready_material"],
                        "tables": {
                            "proactive_ooda_runs": {"record_count": 1},
                            "proactive_ooda_items": {"record_count": 0},
                            "proactive_ooda_safe_work": {"record_count": 0},
                        },
                    },
                },
            },
        },
    )
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_gmail_draft",
        lambda **_kwargs: {"probe_ok": True, "status": "no_pending_draft", "source": "docker_compose_exec"},
    )
    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_source_coverage", _fake_source_coverage_probe)
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_approval_capture",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("suppressed projection should not probe approval capture")),
    )

    receipt = module.build_proactive_ooda_operator_status(
        output_path=tmp_path / "ea_proactive_ooda_operator_status.generated.json",
        generated_at="2026-06-30T08:11:00Z",
        report_args=Namespace(principal_id="exec-1"),
    )

    assert receipt["status"] == "ready_with_live_receipt"
    assert receipt["reason"] == "ready"
    assert receipt["next_action"] == "maintain_proactive_ooda_runtime"
    assert receipt["next_action_href"] == "https://myexternalbrain.com/app/today"
    assert receipt["operator_action_state"] == "clear"
    assert receipt["safe_work_audit"]["present"] is False
    assert receipt["suppressed_projection"]["requires_recovery"] is False
    assert receipt["suppressed_projection"]["status"] == "suppressed_non_material"
    assert receipt["suppressed_projection"]["suppressed_non_material"] is True
    assert receipt["suppressed_projection"]["suppressed_non_material_reason"] == "quiet_no_decision_ready_material"
    assert receipt["suppressed_projection"]["blocking_reason"] == ""
    assert receipt["suppressed_projection"]["next_action"] == ""
    assert receipt["suppressed_projection"]["suppressed_item_count"] == 2
    assert receipt["suppressed_projection"]["suppressed_safe_work_review_count"] == 2
    assert receipt["suppressed_projection"]["suppressed_projection_reasons"] == ["safe_work_audit_review"]
    assert receipt["suppressed_projection"]["suppressed_safe_work_issue_codes"] == ["no_decision_ready_material"]
    assert receipt["suppressed_projection"]["packet_projection_record_count"] == 0
    assert receipt["suppressed_projection"]["privacy"]["raw_candidate_exposed"] is False
    assert "ready for operator follow-through" in receipt["summary"]


def test_suppressed_projection_prefers_current_run_over_stale_quiet_receipt() -> None:
    module = _load_script()

    summary = module._normalized_suppressed_projection(  # noqa: SLF001
        {
            "source": "docker_compose_exec",
            "run_receipt": {
                "generated_at": "2026-06-30T08:15:00Z",
                "notification_status": "skipped_no_items",
                "error_code": "",
                "item_count": 0,
                "teable_sync": {
                    "status": "synced",
                    "projection_summary": {
                        "record_count": 1,
                        "suppressed_item_count": 0,
                        "suppressed_safe_work_review_count": 0,
                        "tables": {
                            "proactive_ooda_runs": {"record_count": 1},
                            "proactive_ooda_items": {"record_count": 0},
                            "proactive_ooda_safe_work": {"record_count": 0},
                        },
                    },
                },
            },
            "action_required_only_quiet_receipt": {
                "generated_at": "2026-06-30T08:09:30Z",
                "notification_status": "deferred",
                "error_code": "no_user_action_required",
                "item_count": 2,
                "teable_sync": {
                    "status": "synced",
                    "projection_summary": {
                        "record_count": 1,
                        "suppressed_item_count": 2,
                        "suppressed_safe_work_review_count": 2,
                        "suppressed_projection_reasons": ["safe_work_audit_review"],
                        "suppressed_safe_work_issue_codes": ["no_decision_ready_material"],
                        "tables": {
                            "proactive_ooda_runs": {"record_count": 1},
                            "proactive_ooda_items": {"record_count": 0},
                            "proactive_ooda_safe_work": {"record_count": 0},
                        },
                    },
                },
            },
        }
    )

    assert summary["status"] == "clear"
    assert summary["requires_recovery"] is False
    assert summary["run_receipt_generated_at"] == "2026-06-30T08:15:00Z"
    assert summary["suppressed_item_count"] == 0
    assert summary["suppressed_safe_work_issue_codes"] == []


def test_suppressed_projection_with_recovery_issue_still_requires_repair() -> None:
    module = _load_script()

    summary = module._normalized_suppressed_projection(  # noqa: SLF001
        {
            "source": "docker_compose_exec",
            "action_required_only_quiet_receipt": {
                "generated_at": "2026-06-30T08:09:30Z",
                "notification_status": "deferred",
                "error_code": "no_user_action_required",
                "item_count": 1,
                "teable_sync": {
                    "status": "synced",
                    "projection_summary": {
                        "record_count": 1,
                        "suppressed_item_count": 1,
                        "suppressed_safe_work_review_count": 1,
                        "suppressed_projection_reasons": ["safe_work_audit_review"],
                        "suppressed_safe_work_issue_codes": ["no_provider_safe_candidate"],
                        "tables": {
                            "proactive_ooda_runs": {"record_count": 1},
                            "proactive_ooda_items": {"record_count": 0},
                            "proactive_ooda_safe_work": {"record_count": 0},
                        },
                    },
                },
            },
        }
    )

    assert summary["status"] == "suppressed"
    assert summary["requires_recovery"] is True
    assert summary["blocking_reason"] == "suppressed_safe_work_projection"
    assert summary["next_action"] == "repair_proactive_safe_work_audit"
    assert summary["suppressed_non_material"] is False
    assert summary["suppressed_safe_work_issue_codes"] == ["no_provider_safe_candidate"]


def test_suppressed_projection_treats_flat_search_disabled_as_non_material_without_explicit_issue_codes() -> None:
    module = _load_script()

    summary = module._normalized_suppressed_projection(  # noqa: SLF001
        {
            "source": "docker_compose_exec",
            "run_receipt": {
                "generated_at": "2026-07-01T20:55:53Z",
                "notification_status": "deferred",
                "error_code": "no_user_action_required",
                "item_count": 1,
                "teable_sync": {
                    "status": "synced",
                    "projection_summary": {
                        "record_count": 1,
                        "suppressed_item_count": 1,
                        "suppressed_safe_work_review_count": 0,
                        "suppressed_projection_reasons": ["flat_search_disabled"],
                        "suppressed_safe_work_issue_codes": [],
                        "tables": {
                            "proactive_ooda_runs": {"record_count": 1},
                            "proactive_ooda_items": {"record_count": 0},
                            "proactive_ooda_safe_work": {"record_count": 0},
                        },
                    },
                },
            },
        }
    )

    assert summary["status"] == "suppressed_non_material"
    assert summary["requires_recovery"] is False
    assert summary["suppressed_non_material"] is True
    assert summary["suppressed_non_material_reason"] == "configured_source_exclusion"
    assert summary["blocking_reason"] == ""
    assert summary["next_action"] == ""
    assert summary["suppressed_projection_reasons"] == ["flat_search_disabled"]
    assert summary["suppressed_safe_work_issue_codes"] == ["flat_search_disabled"]


def test_suppressed_projection_treats_mixed_delivery_non_material_review_as_non_blocking() -> None:
    module = _load_script()

    summary = module._normalized_suppressed_projection(  # noqa: SLF001
        {
            "source": "docker_compose_exec",
            "run_receipt": {
                "generated_at": "2026-07-09T05:39:02Z",
                "notification_status": "sent",
                "error_code": "",
                "item_count": 5,
                "teable_sync": {
                    "status": "synced",
                    "projection_summary": {
                        "record_count": 4,
                        "suppressed_item_count": 4,
                        "suppressed_safe_work_review_count": 4,
                        "suppressed_projection_reasons": ["safe_work_quality_gate_review"],
                        "suppressed_safe_work_issue_codes": ["no_decision_ready_material"],
                        "tables": {
                            "proactive_ooda_runs": {"record_count": 1},
                            "proactive_ooda_items": {"record_count": 1},
                            "proactive_ooda_safe_work": {"record_count": 1},
                        },
                    },
                },
            },
        }
    )

    assert summary["status"] == "suppressed_non_material"
    assert summary["requires_recovery"] is False
    assert summary["suppressed_non_material"] is True
    assert summary["suppressed_non_material_reason"] == "mixed_delivery_non_material"
    assert summary["blocking_reason"] == ""
    assert summary["next_action"] == ""
    assert summary["packet_projection_record_count"] == 2
    assert summary["suppressed_item_count"] == 4
    assert summary["suppressed_safe_work_issue_codes"] == ["no_decision_ready_material"]


def test_materialize_proactive_ooda_operator_status_writes_recovery_receipt(tmp_path: Path, monkeypatch) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")
    monkeypatch.setattr(
        module.proactive_verifier,
        "_build_report",
        lambda _args: {
            "ok": True,
            "delivery_route": {
                "ready": True,
                "route_error": "whatsapp_web_session_not_ready:qr_required",
                "recovery_hint": "Scan the WhatsApp Web QR code and re-activate the session before preferring WhatsApp again.",
                "next_action": "scan_whatsapp_web_qr",
            },
            "delivery_guard": {"delivery_state": "eligible"},
            "stage_packets": {"ready": True, "errors": []},
            "safe_work_results": {"ready": True, "errors": []},
            "receipt_observation_count": 2,
            "actionable_count": 3,
            "source_mode": "discovery_json+postgres_observations",
        },
    )
    monkeypatch.setattr(
        module.live_receipt_verifier,
        "verify_receipt",
        lambda _path: {
            "ok": False,
            "errors": ["receipt_missing"],
            "receipt_path": str(tmp_path / "live-receipt.json"),
            "notification_status": "",
            "delivery_channel": "",
            "delivery_message_count": 0,
            "telegram_message_count": 0,
            "delivery_route_error": "",
            "delivery_recovery_hint": "",
            "delivery_next_action": "",
            "generated_at": "",
        },
    )

    output = tmp_path / ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json"
    receipt = module.build_proactive_ooda_operator_status(
        output_path=output,
        generated_at="2026-06-26T17:30:00Z",
        report_args=Namespace(),
        live_receipt_path=tmp_path / "live-receipt.json",
        allow_live_route_probe=False,
    )

    assert receipt["contract_name"] == "ea.proactive_ooda_operator_status.v1"
    assert receipt["generated_by"] == "scripts/materialize_proactive_ooda_operator_status.py"
    assert receipt["source_git_head"] == "source-head-123"
    assert receipt["head_semantics"] == "source_state"
    assert receipt["status"] == "ready_with_recovery_action"
    assert receipt["reason"] == "whatsapp_web_session_not_ready:qr_required"
    assert receipt["next_action"] == "scan_whatsapp_web_qr"
    assert receipt["next_action_href"] == "https://myexternalbrain.com/integrations/whatsapp"
    assert receipt["next_action_label"] == "Open WhatsApp pairing"
    assert receipt["next_action_method"] == "get"
    assert receipt["operator_action_state"] == "recovery_required"
    assert receipt["delivery_route_ready"] is True
    assert receipt["delivery_route_error"] == "whatsapp_web_session_not_ready:qr_required"
    assert receipt["delivery_recovery_hint"].startswith("Scan the WhatsApp Web QR code")
    assert receipt["live_receipt_checked"] is True
    assert receipt["route_probe_source"] == "host_verifier"
    assert receipt["route_probe_runtime_service"] == ""
    assert receipt["route_probe_observed_at"] == ""
    assert receipt["goal_completion_claim_allowed"] is False
    assert receipt["live_delivery_claim_allowed"] is False
    assert receipt["remaining_external_proofs"] == [
        "real proactive OODA packet accepted with routed delivery, approved-source or transcript signal, live browse evidence, auditor-passed chosen candidate, staged reversible artifact, mirrored Teable delivery, current-packet, stale-approval, and decision facts, and explicit approval outcome"
    ]


def test_materialize_proactive_ooda_operator_status_still_probes_source_coverage_when_live_route_probe_disabled(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")
    monkeypatch.setattr(module, "_source_fingerprint", lambda path=module.ROOT: "source-fingerprint-123")
    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_source_coverage", _fake_source_coverage_probe)
    monkeypatch.setattr(
        module.proactive_verifier,
        "_build_report",
        lambda _args: {
            "ok": True,
            "delivery_route": {
                "ready": False,
                "route_error": "",
                "recovery_hint": "",
                "next_action": "",
            },
            "delivery_guard": {"delivery_state": "eligible"},
            "stage_packets": {"ready": True, "errors": []},
            "safe_work_results": {"ready": True, "errors": []},
            "receipt_observation_count": 0,
            "actionable_count": 0,
            "source_mode": "none",
        },
    )
    monkeypatch.setattr(
        module.live_receipt_verifier,
        "verify_receipt",
        lambda _path: {
            "ok": False,
            "errors": ["receipt_missing"],
            "receipt_path": str(tmp_path / "live-receipt.json"),
            "notification_status": "",
            "delivery_channel": "",
            "delivery_message_count": 0,
            "telegram_message_count": 0,
            "delivery_route_error": "",
            "delivery_recovery_hint": "",
            "delivery_next_action": "",
            "generated_at": "",
        },
    )

    output = tmp_path / ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json"
    receipt = module.build_proactive_ooda_operator_status(
        output_path=output,
        generated_at="2026-07-07T03:45:00Z",
        report_args=Namespace(principal_id="exec-1"),
        live_receipt_path=tmp_path / "live-receipt.json",
        allow_live_route_probe=False,
    )

    assert receipt["source_coverage"]["checked"] is True
    assert receipt["source_coverage"]["probe_ok"] is True
    assert receipt["source_coverage"]["status"] == "ready"
    assert receipt["source_coverage"]["source"] == "docker_compose_exec"
    assert receipt["source_coverage"]["missing_lane_keys"] == []
    assert receipt["verifier_commands"] == [
        "make verify-proactive-ooda",
        "make verify-proactive-ooda-live-receipt",
        "make verify-proactive-ooda-operator-status",
    ]

    persisted = json.loads(output.read_text(encoding="utf-8"))
    assert persisted["source_coverage"]["checked"] is True
    assert persisted["source_coverage"]["status"] == "ready"
    assert persisted["source_coverage"]["missing_lane_keys"] == []


def test_materialize_proactive_ooda_operator_status_normalizes_missing_delivery_shapes(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")
    monkeypatch.setattr(module, "_source_fingerprint", lambda path=module.ROOT: "source-fingerprint-123")
    monkeypatch.setattr(
        module.proactive_verifier,
        "_build_report",
        lambda _args: {
            "ok": False,
            "errors": ["delivery_route_unavailable"],
            "receipt_observation_count": 0,
            "actionable_count": 0,
            "source_mode": "signals_json",
        },
    )
    monkeypatch.setattr(
        module.live_receipt_verifier,
        "verify_receipt",
        lambda _path: {
            "ok": False,
            "errors": ["receipt_missing"],
            "receipt_path": str(tmp_path / "live-receipt.json"),
            "notification_status": "",
            "delivery_channel": "",
            "delivery_message_count": 0,
            "telegram_message_count": 0,
            "delivery_route_error": "",
            "delivery_recovery_hint": "",
            "delivery_next_action": "",
            "generated_at": "",
        },
    )

    output = tmp_path / ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json"
    receipt = module.build_proactive_ooda_operator_status(
        output_path=output,
        generated_at="2026-06-29T22:05:00Z",
        report_args=Namespace(),
        live_receipt_path=tmp_path / "live-receipt.json",
        allow_live_route_probe=False,
    )

    assert receipt["status"] == "blocked_delivery_route"
    assert receipt["reason"] == "delivery_route_unavailable"
    assert receipt["next_action"] == "repair_proactive_stage_packet_runtime"
    assert receipt["delivery_route"] == {
        "ready": False,
        "route_error": "",
        "recovery_hint": "",
        "next_action": "",
    }
    assert receipt["delivery_guard"]["delivery_state"] == ""
    assert receipt["stage_packets"]["ready"] is False
    assert receipt["stage_packets"]["errors"] == []
    assert receipt["safe_work_results"]["ready"] is False
    assert receipt["safe_work_results"]["errors"] == []
    assert receipt["delivery_route_ready"] is False
    assert receipt["delivery_route_error"] == ""
    assert receipt["delivery_next_action"] == ""

    persisted = json.loads(output.read_text(encoding="utf-8"))
    assert persisted["delivery_route"]["ready"] is False
    assert persisted["delivery_guard"]["delivery_state"] == ""
    assert persisted["stage_packets"]["ready"] is False
    assert persisted["safe_work_results"]["ready"] is False


def test_materialize_proactive_ooda_operator_status_prefers_live_route_probe_when_available(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_route",
        lambda **_kwargs: {
            "probe_ok": True,
            "source": "docker_compose_exec",
            "runtime_service": "ea-proactive-ooda",
            "observed_at": "2026-06-26T18:00:00Z",
            "live_receipt_checked": True,
            "live_receipt": {
                "ok": True,
                "receipt_path": "/app/state/proactive_ooda/live-receipt.json",
                "delivery_next_action": "",
                "delivery_route_error": "",
                "delivery_recovery_hint": "",
                "errors": [],
                "generated_at": "2026-06-26T17:59:00Z",
                "notification_status": "sent",
            },
            "route_report": {
                "ok": True,
                "delivery_route": {
                    "ready": True,
                    "route_error": "whatsapp_web_session_not_ready:qr_required",
                    "recovery_hint": "Scan the WhatsApp Web QR code and re-activate the session before preferring WhatsApp again.",
                    "next_action": "scan_whatsapp_web_qr",
                    "selected_channel": "telegram",
                    "selected_transport": "telegram",
                    "selected_by": "tool_runtime_binding",
                    "available_channels": ["telegram"],
                },
                "delivery_guard": {"delivery_state": "eligible"},
                "stage_packets": {"ready": True, "errors": []},
                "safe_work_results": {"ready": True, "errors": []},
                "context_grounding": {
                    "grounded": True,
                    "item_count": 2,
                    "grounded_item_count": 2,
                    "ungrounded_item_count": 0,
                    "applied_context_count": 4,
                    "preference_count": 1,
                    "requirement_count": 1,
                    "candidate_assessment_count": 1,
                    "recipient_location_count": 1,
                },
                "receipt_observation_count": 1,
                "actionable_count": 2,
                "source_mode": "postgres_observations",
            },
        },
    )
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_artifacts",
        lambda **_kwargs: {
            "probe_ok": True,
            "source": "docker_compose_exec",
            "approval_outcome_path": "/data/provider-ledger/proactive_ooda_latest_approval_outcome.generated.json",
            "approval_callback_dir": "/data/provider-ledger/proactive_ooda_approval_callbacks",
            "approval_callback_dir_exists": True,
            "approval_callback_dir_writable": True,
            "approval_callback_record_count": 1,
            "approval_callback_pending_count": 1,
            "approval_callback_recorded_count": 0,
            "current_packet_callback_record_count": 1,
            "current_packet_callback_pending_count": 1,
            "current_packet_callback_recorded_count": 0,
            "current_packet_live_callback_record_count": 1,
            "current_packet_live_pending_count": 1,
            "current_packet_callback_latest_status": "pending",
            "current_packet_callback_latest_expired": False,
        },
    )
    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_approval_capture", _fake_approval_capture_probe)
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_gmail_draft",
        lambda **_kwargs: {
            "probe_ok": True,
            "status": "already_executed",
            "source": "docker_compose_exec",
            "observed_at": "2026-06-26T18:00:30Z",
            "action": "save_gmail_draft",
            "work_type": "draft",
            "execution_observation_present": True,
            "execution_status": "executed",
            "execution_saved_at": "2026-06-26T17:58:00Z",
            "recipient_email_hash_present": True,
            "gmail_draft_id_hash_present": True,
            "gmail_message_id_hash_present": True,
            "draft_folder_url_hash_present": True,
            "raw_execution_payload_exposed": False,
        },
    )
    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_source_coverage", _fake_source_coverage_probe)
    monkeypatch.setattr(
        module.proactive_verifier,
        "_build_report",
        lambda _args: (_ for _ in ()).throw(AssertionError("host verifier fallback should not run")),
    )
    monkeypatch.setattr(
        module.live_receipt_verifier,
        "verify_receipt",
        lambda _path: (_ for _ in ()).throw(AssertionError("host live receipt verifier should not run")),
    )

    output = tmp_path / ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json"
    receipt = module.build_proactive_ooda_operator_status(
        output_path=output,
        generated_at="2026-06-26T18:01:00Z",
        report_args=Namespace(principal_id="exec-1"),
    )

    assert receipt["status"] == "ready_with_recovery_action"
    assert receipt["reason"] == "whatsapp_web_session_not_ready:qr_required"
    assert receipt["route_probe_source"] == "docker_compose_exec"
    assert receipt["route_probe_runtime_service"] == "ea-proactive-ooda"
    assert receipt["route_probe_observed_at"] == "2026-06-26T18:00:00Z"
    assert receipt["delivery_route_ready"] is True
    assert receipt["delivery_next_action"] == "scan_whatsapp_web_qr"
    assert receipt["delivery_route"]["selected_channel"] == "telegram"
    assert receipt["delivery_route"]["selected_by"] == "tool_runtime_binding"
    assert receipt["context_grounding"]["grounded"] is True
    assert receipt["context_grounding"]["item_count"] == 2
    assert receipt["context_grounding"]["grounded_item_count"] == 2
    assert receipt["context_grounding"]["ungrounded_item_count"] == 0
    assert receipt["context_grounding"]["recipient_location_count"] == 1
    assert receipt["live_receipt_checked"] is True
    assert receipt["live_receipt"]["ok"] is True
    assert receipt["next_action"] == "scan_whatsapp_web_qr"
    assert receipt["operator_action_state"] == "recovery_required"
    assert receipt["approval_capture_surface"]["ready"] is True
    assert receipt["approval_capture_surface"]["callback_dir_writable"] is True
    assert receipt["approval_capture_surface"]["current_packet_callback_record_count"] == 1
    assert receipt["approval_capture_surface"]["current_packet_live_pending_count"] == 1
    assert receipt["approval_capture"]["checked"] is True
    assert receipt["approval_capture"]["ready"] is True
    assert receipt["approval_capture"]["principal_match_ready"] is True
    assert receipt["approval_capture"]["telegram_bot_token_present"] is True
    assert receipt["approval_capture"]["privacy"]["raw_callback_token_exposed"] is False
    assert receipt["gmail_draft_followthrough"]["status"] == "already_executed"
    assert receipt["gmail_draft_followthrough"]["action"] == "save_gmail_draft"
    assert receipt["gmail_draft_followthrough"]["execution_observation_present"] is True
    assert receipt["gmail_draft_followthrough"]["gmail_draft_id_hash_present"] is True
    assert receipt["gmail_draft_followthrough"]["raw_execution_payload_exposed"] is False
    assert receipt["source_coverage"]["status"] == "ready"
    assert "flat_search_enabled" not in receipt["source_coverage"]
    assert "excluded_event_types" not in receipt["source_coverage"]
    assert "excluded_event_type_counts" not in receipt["source_coverage"]
    assert receipt["source_coverage"]["privacy"]["raw_transcript_text_exposed"] is False


def test_materialize_proactive_ooda_operator_status_treats_current_packet_ref_errors_as_recovery(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_route",
        lambda **_kwargs: {
            "probe_ok": True,
            "source": "docker_compose_exec",
            "runtime_service": "ea-proactive-ooda",
            "observed_at": "2026-07-09T07:10:00Z",
            "live_receipt_checked": True,
            "live_receipt": {
                "ok": True,
                "receipt_path": "/data/provider-ledger/proactive_ooda_latest_run.generated.json",
                "errors": [],
            },
            "route_report": {
                "ok": True,
                "delivery_route": {
                    "ready": True,
                    "selected_channel": "telegram",
                    "selected_by": "tool_runtime_binding",
                    "next_action": "regenerate_proactive_ooda_stage_packet",
                },
                "delivery_guard": {"delivery_state": "no_actionable_items"},
                "stage_packets": {"ready": True, "errors": ["current_packet_refs_missing"]},
                "safe_work_results": {"ready": True, "errors": []},
                "receipt_observation_count": 1,
                "actionable_count": 0,
            },
        },
    )
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_artifacts",
        lambda **_kwargs: {
            "probe_ok": True,
            "source": "docker_compose_exec",
            "approval_outcome_path": "/data/provider-ledger/proactive_ooda_latest_approval_outcome.generated.json",
            "approval_callback_dir": "/data/provider-ledger/proactive_ooda_approval_callbacks",
            "approval_callback_dir_exists": True,
            "approval_callback_dir_writable": True,
            "approval_callback_record_count": 1,
            "approval_callback_pending_count": 1,
            "approval_callback_recorded_count": 0,
            "current_packet_callback_record_count": 1,
            "current_packet_callback_pending_count": 1,
            "current_packet_callback_recorded_count": 0,
            "current_packet_live_callback_record_count": 1,
            "current_packet_live_pending_count": 1,
            "current_packet_callback_latest_status": "pending",
            "current_packet_callback_latest_expired": False,
        },
    )
    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_approval_capture", _fake_approval_capture_probe)
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_gmail_draft",
        lambda **_kwargs: {"probe_ok": True, "status": "no_pending_draft", "source": "docker_compose_exec"},
    )
    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_source_coverage", _fake_source_coverage_probe)

    receipt = module.build_proactive_ooda_operator_status(
        output_path=tmp_path / "ea_proactive_ooda_operator_status.generated.json",
        generated_at="2026-07-09T07:11:00Z",
        report_args=Namespace(principal_id="exec-1"),
    )

    assert receipt["status"] == "ready_with_recovery_action"
    assert receipt["reason"] == "current_packet_refs_missing"
    assert receipt["next_action"] == "regenerate_proactive_ooda_stage_packet"
    assert receipt["operator_action_state"] == "recovery_required"
    assert receipt["approval_capture_surface"]["ready"] is True
    assert receipt["delivery_guard"]["delivery_state"] == "no_actionable_items"
    assert receipt["delivery_guard"].get("user_action_required") is not True
    assert receipt["actionable_count"] == 0


def test_materialize_proactive_ooda_operator_status_counts_pending_approval_as_user_action(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_route",
        lambda **_kwargs: {
            "probe_ok": True,
            "source": "docker_compose_exec",
            "runtime_service": "ea-proactive-ooda",
            "observed_at": "2026-06-29T06:55:00Z",
            "live_receipt_checked": True,
            "live_receipt": {
                "ok": True,
                "receipt_path": "/data/provider-ledger/proactive_ooda_run_receipts/live.json",
                "delivery_next_action": "",
                "delivery_route_error": "",
                "delivery_recovery_hint": "",
                "errors": [],
                "generated_at": "2026-06-29T06:54:00Z",
                "notification_status": "sent",
            },
            "route_report": {
                "ok": True,
                "delivery_route": {
                    "ready": True,
                    "route_error": "",
                    "recovery_hint": "",
                    "next_action": "",
                    "selected_channel": "telegram",
                    "selected_transport": "telegram",
                    "selected_by": "tool_runtime_binding",
                    "available_channels": ["telegram"],
                },
                "delivery_guard": {"delivery_state": "no_actionable_items", "armed_send": True},
                "stage_packets": {"ready": True, "errors": []},
                "safe_work_results": {"ready": True, "errors": []},
                "receipt_observation_count": 1,
                "actionable_count": 0,
                "source_mode": "postgres_observations",
            },
        },
    )
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_artifacts",
        lambda **_kwargs: {
            "probe_ok": True,
            "source": "docker_compose_exec",
            "approval_outcome_path": "/data/provider-ledger/proactive_ooda_latest_approval_outcome.generated.json",
            "approval_callback_dir": "/data/provider-ledger/proactive_ooda_approval_callbacks",
            "approval_callback_dir_exists": True,
            "approval_callback_dir_writable": True,
            "approval_callback_record_count": 15,
            "approval_callback_pending_count": 1,
            "approval_callback_recorded_count": 2,
            "current_packet_callback_record_count": 2,
            "current_packet_callback_pending_count": 1,
            "current_packet_callback_recorded_count": 0,
            "current_packet_live_callback_record_count": 2,
            "current_packet_live_pending_count": 1,
            "current_packet_callback_latest_status": "pending",
            "current_packet_callback_latest_expired": False,
        },
    )
    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_approval_capture", _fake_approval_capture_probe)
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_gmail_draft",
        lambda **_kwargs: {
            "probe_ok": True,
            "status": "no_pending_draft",
            "source": "docker_compose_exec",
            "observed_at": "2026-06-29T06:55:30Z",
        },
    )
    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_source_coverage", _fake_source_coverage_probe)
    monkeypatch.setattr(
        module.proactive_verifier,
        "_build_report",
        lambda _args: (_ for _ in ()).throw(AssertionError("host verifier fallback should not run")),
    )
    monkeypatch.setattr(
        module.live_receipt_verifier,
        "verify_receipt",
        lambda _path: (_ for _ in ()).throw(AssertionError("host live receipt verifier should not run")),
    )

    output = tmp_path / ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json"
    receipt = module.build_proactive_ooda_operator_status(
        output_path=output,
        generated_at="2026-06-29T06:56:00Z",
        report_args=Namespace(principal_id="exec-1"),
    )

    assert receipt["status"] == "ready_with_live_receipt"
    assert receipt["next_action"] == "tap_proactive_telegram_approval_button_or_record_proactive_ooda_approval_outcome"
    assert receipt["operator_action_state"] == "approval_capture_pending"
    assert receipt["runtime_actionable_count"] == 0
    assert receipt["actionable_count"] == 1
    assert receipt["delivery_guard"]["runtime_delivery_state"] == "no_actionable_items"
    assert receipt["delivery_guard"]["delivery_state"] == "approval_capture_pending"
    assert receipt["delivery_guard"]["user_action_required"] is True
    assert receipt["delivery_guard"]["pending_approval_surface"] is True
    assert receipt["delivery_guard"]["current_packet_live_pending_count"] == 1
    assert receipt["approval_capture"]["checked"] is True
    assert receipt["approval_capture"]["ready"] is True
    assert receipt["approval_capture"]["current_packet_live_pending_count"] == 1
    assert receipt["approval_capture"]["privacy"]["raw_principal_id_exposed"] is False
    assert receipt["source_coverage"]["observed_lane_count"] == 8


def test_materialize_proactive_ooda_operator_status_blocks_on_approval_callback_hygiene(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_route",
        lambda **_kwargs: {
            "probe_ok": True,
            "source": "docker_compose_exec",
            "runtime_service": "ea-proactive-ooda",
            "observed_at": "2026-07-02T17:00:00Z",
            "live_receipt_checked": True,
            "live_receipt": {
                "ok": True,
                "receipt_path": "/data/provider-ledger/proactive_ooda_run_receipts/live.json",
                "delivery_next_action": "",
                "delivery_route_error": "",
                "delivery_recovery_hint": "",
                "errors": [],
                "generated_at": "2026-07-02T16:59:00Z",
                "notification_status": "sent",
            },
            "route_report": {
                "ok": True,
                "delivery_route": {
                    "ready": True,
                    "route_error": "",
                    "recovery_hint": "",
                    "next_action": "",
                    "selected_channel": "telegram",
                    "selected_transport": "telegram",
                    "selected_by": "tool_runtime_binding",
                    "available_channels": ["telegram"],
                },
                "delivery_guard": {"delivery_state": "no_actionable_items", "armed_send": True},
                "stage_packets": {"ready": True, "errors": []},
                "safe_work_results": {"ready": True, "errors": []},
                "receipt_observation_count": 1,
                "actionable_count": 0,
                "source_mode": "postgres_observations",
            },
        },
    )
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_artifacts",
        lambda **_kwargs: {
            "probe_ok": True,
            "source": "docker_compose_exec",
            "approval_outcome_path": "/data/provider-ledger/proactive_ooda_latest_approval_outcome.generated.json",
            "approval_callback_dir": "/data/provider-ledger/proactive_ooda_approval_callbacks",
            "approval_callback_dir_exists": True,
            "approval_callback_dir_writable": True,
            "approval_callback_record_count": 40,
            "approval_callback_pending_count": 3,
            "approval_callback_raw_pending_count": 3,
            "approval_callback_live_pending_count": 1,
            "approval_callback_unexpired_pending_count": 3,
            "approval_callback_noncurrent_pending_count": 2,
            "approval_callback_stale_pending_count": 2,
            "approval_callback_recorded_count": 2,
            "approval_callback_expired_count": 0,
            "approval_callback_superseded_count": 28,
            "approval_callback_terminal_count": 30,
            "current_packet_callback_record_count": 1,
            "current_packet_callback_pending_count": 1,
            "current_packet_callback_raw_pending_count": 1,
            "current_packet_callback_stale_pending_count": 0,
            "current_packet_callback_expired_pending_count": 0,
            "current_packet_callback_recorded_count": 0,
            "current_packet_live_callback_record_count": 1,
            "current_packet_live_pending_count": 1,
            "current_packet_callback_latest_status": "pending",
            "current_packet_callback_latest_expired": False,
        },
    )
    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_approval_capture", _fake_approval_capture_probe)
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_gmail_draft",
        lambda **_kwargs: {
            "probe_ok": True,
            "status": "no_pending_draft",
            "source": "docker_compose_exec",
            "observed_at": "2026-07-02T17:00:30Z",
        },
    )
    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_source_coverage", _fake_source_coverage_probe)

    output = tmp_path / ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json"
    receipt = module.build_proactive_ooda_operator_status(
        output_path=output,
        generated_at="2026-07-02T17:01:00Z",
        report_args=Namespace(principal_id="exec-1"),
    )

    assert receipt["status"] == "blocked_local_runtime"
    assert receipt["reason"] == "approval_callback_noncurrent_pending"
    assert receipt["next_action"] == "cleanup_proactive_approval_callbacks"
    assert receipt["operator_action_state"] == "recovery_required"
    assert receipt["approval_capture_surface"]["ready"] is False
    assert receipt["approval_capture_surface"]["callback_hygiene_ready"] is False
    assert receipt["approval_capture_surface"]["callback_hygiene_blocking_reason"] == "approval_callback_noncurrent_pending"
    assert receipt["approval_capture_surface"]["callback_hygiene_next_action"] == "cleanup_proactive_approval_callbacks"
    assert receipt["approval_capture_surface"]["callback_noncurrent_pending_count"] == 2
    assert receipt["approval_capture_surface"]["callback_stale_pending_count"] == 2


def test_materialize_proactive_ooda_operator_status_surfaces_manual_approval_capture_for_mirrored_packet(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_route",
        lambda **_kwargs: {
            "probe_ok": True,
            "source": "docker_compose_exec",
            "runtime_service": "ea-proactive-ooda",
            "observed_at": "2026-07-01T00:55:00Z",
            "live_receipt_checked": True,
            "live_receipt": {
                "ok": True,
                "receipt_path": "/data/provider-ledger/proactive_ooda_run_receipts/mirror.json",
                "delivery_mode": "operator_safe_mirror",
                "delivery_next_action": "",
                "delivery_route_error": "",
                "delivery_recovery_hint": "",
                "errors": [],
                "generated_at": "2026-07-01T00:54:00Z",
                "notification_status": "deferred",
                "telegram_message_count": 0,
                "delivery_message_count": 0,
            },
            "route_report": {
                "ok": True,
                "delivery_route": {
                    "ready": True,
                    "route_error": "",
                    "recovery_hint": "",
                    "next_action": "",
                    "selected_channel": "telegram",
                    "selected_transport": "telegram",
                    "selected_by": "tool_runtime_binding",
                    "available_channels": ["telegram"],
                },
                "delivery_guard": {"delivery_state": "no_actionable_items", "armed_send": True},
                "stage_packets": {"ready": True, "errors": []},
                "safe_work_results": {"ready": True, "errors": []},
                "receipt_observation_count": 1,
                "actionable_count": 0,
                "source_mode": "postgres_observations",
            },
        },
    )
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_artifacts",
        lambda **_kwargs: {
            "probe_ok": True,
            "source": "docker_compose_exec",
            "approval_outcome_path": "/data/provider-ledger/proactive_ooda_latest_approval_outcome.generated.json",
            "approval_callback_dir": "/data/provider-ledger/proactive_ooda_approval_callbacks",
            "approval_callback_dir_exists": True,
            "approval_callback_dir_writable": True,
            "approval_callback_record_count": 27,
            "approval_callback_pending_count": 0,
            "approval_callback_recorded_count": 6,
            "current_packet_callback_record_count": 0,
            "current_packet_callback_pending_count": 0,
            "current_packet_callback_recorded_count": 0,
            "current_packet_live_callback_record_count": 0,
            "current_packet_live_pending_count": 0,
            "current_packet_callback_latest_status": "",
            "current_packet_callback_latest_expired": False,
            "current_packet": {
                "present": True,
                "status": "staged",
                "approval_outcome_matches_current_packet": False,
            },
            "stage_packet": {
                "schema": "proactive_ooda.stage_packet.v1",
                "packet_ref": "stage_packet:mirror-proof",
                "approval": {"required": True},
                "stage": {
                    "kind": "approval_packet",
                    "payload": {
                        "approval_prompt": "Approve this staged candidate.",
                        "approval_url": "https://example.test/candidate",
                    },
                },
            },
            "safe_work_result": {
                "schema": "proactive_ooda.safe_work_result.v1",
                "result_ref": "safe_work_result:mirror-proof",
                "status": "staged_for_user_decision",
                "approval": {"required": True},
                "approval_prompt": "Approve this staged candidate.",
                "staged_action_url": "https://example.test/candidate",
                "audit": {"status": "pass", "issues": []},
            },
            "approval_outcome": {},
        },
    )

    def _unexpected_approval_capture(**_kwargs: object) -> dict[str, object]:
        raise AssertionError("manual outcome capture must not require a Telegram callback probe")

    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_approval_capture", _unexpected_approval_capture)
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_gmail_draft",
        lambda **_kwargs: {
            "probe_ok": True,
            "status": "no_pending_draft",
            "source": "docker_compose_exec",
            "observed_at": "2026-07-01T00:55:30Z",
        },
    )
    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_source_coverage", _fake_source_coverage_probe)

    output = tmp_path / ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json"
    receipt = module.build_proactive_ooda_operator_status(
        output_path=output,
        generated_at="2026-07-01T00:56:00Z",
        report_args=Namespace(principal_id="exec-1"),
    )

    assert receipt["status"] == "ready_with_live_receipt"
    assert receipt["next_action"] == "record_proactive_ooda_approval_outcome"
    assert receipt["operator_action_state"] == "approval_capture_pending"
    assert receipt["actionable_count"] == 1
    assert receipt["delivery_guard"]["runtime_delivery_state"] == "no_actionable_items"
    assert receipt["delivery_guard"]["delivery_state"] == "approval_capture_pending"
    assert receipt["delivery_guard"]["user_action_required"] is True
    assert receipt["delivery_guard"]["manual_outcome_capture_ready"] is True
    assert receipt["delivery_guard"]["current_packet_live_pending_count"] == 0
    assert receipt["approval_capture"]["checked"] is False
    assert receipt["approval_capture_surface"]["ready"] is True
    assert receipt["approval_capture_surface"]["mode"] == "manual_outcome_capture_ready"
    assert receipt["approval_capture_surface"]["current_packet_live_pending_count"] == 0
    assert receipt["approval_capture_surface"]["manual_outcome_capture_ready"] is True
    assert receipt["approval_capture_surface"]["current_packet_approval_request_recordable"] is True
    assert receipt["approval_capture_surface"]["approval_outcome_matches_current_packet"] is False


def test_materialize_proactive_ooda_operator_status_prefers_live_surface_when_probe_reports_missing_current_callback(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_route",
        lambda **_kwargs: {
            "probe_ok": True,
            "source": "docker_compose_exec",
            "runtime_service": "ea-proactive-ooda",
            "observed_at": "2026-07-05T08:00:00Z",
            "live_receipt_checked": True,
            "live_receipt": {
                "ok": True,
                "receipt_path": "/data/provider-ledger/proactive_ooda_run_receipts/live.json",
                "delivery_next_action": "",
                "delivery_route_error": "",
                "delivery_recovery_hint": "",
                "errors": [],
                "generated_at": "2026-07-05T07:59:00Z",
                "notification_status": "sent",
            },
            "route_report": {
                "ok": True,
                "delivery_route": {
                    "ready": True,
                    "route_error": "",
                    "recovery_hint": "",
                    "next_action": "",
                    "selected_channel": "telegram",
                    "selected_transport": "telegram",
                    "selected_by": "tool_runtime_binding",
                    "available_channels": ["telegram"],
                },
                "delivery_guard": {"delivery_state": "no_actionable_items", "armed_send": True},
                "stage_packets": {"ready": True, "errors": []},
                "safe_work_results": {"ready": True, "errors": []},
                "receipt_observation_count": 1,
                "actionable_count": 0,
                "source_mode": "postgres_observations",
            },
        },
    )
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_artifacts",
        lambda **_kwargs: {
            "probe_ok": True,
            "source": "docker_compose_exec",
            "approval_outcome_path": "/data/provider-ledger/proactive_ooda_latest_approval_outcome.generated.json",
            "approval_callback_dir": "/data/provider-ledger/proactive_ooda_approval_callbacks",
            "approval_callback_dir_exists": True,
            "approval_callback_dir_writable": True,
            "approval_callback_record_count": 18,
            "approval_callback_pending_count": 1,
            "approval_callback_raw_pending_count": 1,
            "approval_callback_live_pending_count": 1,
            "approval_callback_unexpired_pending_count": 1,
            "approval_callback_noncurrent_pending_count": 0,
            "approval_callback_stale_pending_count": 0,
            "approval_callback_recorded_count": 3,
            "approval_callback_expired_count": 0,
            "approval_callback_superseded_count": 12,
            "approval_callback_terminal_count": 15,
            "current_packet_callback_record_count": 1,
            "current_packet_callback_pending_count": 1,
            "current_packet_callback_raw_pending_count": 1,
            "current_packet_callback_stale_pending_count": 0,
            "current_packet_callback_expired_pending_count": 0,
            "current_packet_callback_recorded_count": 0,
            "current_packet_live_callback_record_count": 1,
            "current_packet_live_pending_count": 1,
            "current_packet_callback_latest_status": "pending",
            "current_packet_callback_latest_expired": False,
            "current_packet_callback_latest_created_at": "2026-07-04T21:19:05.732743Z",
            "current_packet_callback_latest_expires_at": "2026-07-11T21:19:05Z",
            "current_packet_callback_latest_age_seconds": 60,
            "current_packet_callback_latest_seconds_until_expiry": 600000,
            "current_packet": {
                "present": True,
                "status": "pending_approval",
                "approval_outcome_matches_current_packet": False,
            },
            "stage_packet": {
                "schema": "proactive_ooda.stage_packet.v1",
                "packet_ref": "stage_packet:pkt-live",
                "approval": {"required": True},
                "stage": {
                    "kind": "approval_packet",
                    "payload": {
                        "approval_prompt": "Approve this staged candidate.",
                        "approval_url": "https://example.test/candidate",
                    },
                },
            },
            "safe_work_result": {
                "schema": "proactive_ooda.safe_work_result.v1",
                "result_ref": "safe_work_result:res-live",
                "status": "staged_for_user_decision",
                "approval": {"required": True},
                "approval_prompt": "Approve this staged candidate.",
                "staged_action_url": "https://example.test/candidate",
                "audit": {"status": "pass", "issues": []},
            },
            "approval_outcome": {},
        },
    )
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_approval_capture",
        lambda **_kwargs: {
            "probe_ok": True,
            "ready": False,
            "status": "blocked",
            "source": "docker_compose_exec:proactive_approval_capture",
            "runtime_service": "ea-proactive-ooda",
            "observed_at": "2026-07-05T08:00:10Z",
            "blocking_reason": "current_packet_approval_callback_missing",
            "next_action": "reissue_proactive_approval",
            "callback_dir_exists": True,
            "callback_record_count": 19,
            "current_packet_ref_sha256": "a" * 64,
            "current_staged_artifact_ref_sha256": "b" * 64,
            "current_packet_refs_present": True,
            "current_packet_callback_record_count": 1,
            "current_packet_live_pending_count": 0,
            "current_packet_callback_latest_status": "superseded",
            "current_packet_callback_latest_expired": False,
            "current_packet_callback_latest_age_seconds": 120,
            "current_packet_callback_latest_seconds_until_expiry": 599000,
            "callback_principal_hash_present": True,
            "candidate_principal_hash_count": 3,
            "principal_match_ready": True,
            "telegram_binding_ready": True,
            "telegram_blocking_reason": "",
            "telegram_chat_ref_present": True,
            "telegram_chat_ref_sha256": "c" * 64,
            "telegram_bot_key_present": True,
            "telegram_bot_token_present": True,
            "privacy": {
                "raw_callback_token_exposed": False,
                "raw_principal_id_exposed": False,
                "raw_chat_ref_exposed": False,
                "raw_packet_ref_exposed": False,
                "raw_staged_artifact_ref_exposed": False,
            },
        },
    )
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_gmail_draft",
        lambda **_kwargs: {
            "probe_ok": True,
            "status": "no_pending_draft",
            "source": "docker_compose_exec",
            "observed_at": "2026-07-05T08:00:20Z",
        },
    )
    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_source_coverage", _fake_source_coverage_probe)

    output = tmp_path / ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json"
    receipt = module.build_proactive_ooda_operator_status(
        output_path=output,
        generated_at="2026-07-05T08:01:00Z",
        report_args=Namespace(principal_id="exec-1"),
    )

    assert receipt["status"] == "ready_with_live_receipt"
    assert receipt["next_action"] == "tap_proactive_telegram_approval_button_or_record_proactive_ooda_approval_outcome"
    assert receipt["operator_action_state"] == "approval_capture_pending"
    assert receipt["actionable_count"] == 1
    assert receipt["delivery_guard"]["delivery_state"] == "approval_capture_pending"
    assert receipt["approval_capture"]["ready"] is True
    assert receipt["approval_capture"]["status"] == "ready"
    assert receipt["approval_capture"]["blocking_reason"] == ""
    assert receipt["approval_capture"]["current_packet_live_pending_count"] == 1
    assert receipt["approval_capture"]["current_packet_callback_latest_status"] == "pending"
    assert receipt["approval_capture"]["surface_authoritative_fallback_used"] is True


def test_approval_capture_surface_keeps_manual_capture_ready_with_live_pending_callback() -> None:
    module = _load_script()

    surface = module._approval_capture_surface(  # noqa: SLF001
        report={
            "delivery_route": {"ready": True, "selected_channel": "telegram"},
            "stage_packets": {"ready": True},
            "safe_work_results": {"ready": True},
        },
        artifact_probe={
            "approval_outcome_path": "/data/provider-ledger/proactive_ooda_latest_approval_outcome.generated.json",
            "approval_callback_dir": "/data/provider-ledger/proactive_ooda_approval_callbacks",
            "approval_callback_dir_exists": True,
            "approval_callback_dir_writable": True,
            "approval_callback_record_count": 1,
            "approval_callback_pending_count": 1,
            "current_packet_callback_record_count": 1,
            "current_packet_callback_pending_count": 1,
            "current_packet_live_callback_record_count": 1,
            "current_packet_live_pending_count": 1,
            "current_packet_callback_latest_status": "pending",
            "stage_packet": {
                "packet_ref": "stage_packet:pkt-live",
                "approval": {"required": True},
                "stage": {"payload": {"approval_url": "https://example.test/candidate"}},
            },
            "safe_work_result": {
                "result_ref": "safe_work_result:res-live",
                "status": "staged_for_user_decision",
                "approval": {"required": True},
                "approval_prompt": "Approve this staged candidate.",
                "staged_action_url": "https://example.test/candidate",
            },
            "approval_outcome": {},
        },
    )

    assert surface["ready"] is True
    assert surface["mode"] == "telegram_callback_pending"
    assert surface["telegram_approval_surface_ready"] is True
    assert surface["manual_outcome_capture_ready"] is True
    assert surface["current_packet_approval_request_recordable"] is True
    assert surface["current_packet_live_pending_count"] == 1


def test_approval_capture_surface_treats_live_pending_callback_as_user_action_when_policy_says_no(
    monkeypatch,
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "approval_request_needs_telegram_user_action", lambda _request: False)

    surface = module._approval_capture_surface(  # noqa: SLF001
        report={
            "delivery_route": {"ready": True, "selected_channel": "telegram"},
            "stage_packets": {"ready": True},
            "safe_work_results": {"ready": True},
        },
        artifact_probe={
            "approval_outcome_path": "/data/provider-ledger/proactive_ooda_latest_approval_outcome.generated.json",
            "approval_callback_dir": "/data/provider-ledger/proactive_ooda_approval_callbacks",
            "approval_callback_dir_exists": True,
            "approval_callback_dir_writable": True,
            "approval_callback_record_count": 1,
            "approval_callback_pending_count": 1,
            "current_packet_callback_record_count": 1,
            "current_packet_callback_pending_count": 1,
            "current_packet_live_callback_record_count": 1,
            "current_packet_live_pending_count": 1,
            "current_packet_callback_latest_status": "pending",
            "stage_packet": {
                "packet_ref": "stage_packet:pkt-live",
                "approval": {"required": True},
                "stage": {"payload": {"approval_url": "https://example.test/candidate"}},
            },
            "safe_work_result": {
                "result_ref": "safe_work_result:res-live",
                "status": "staged_for_user_decision",
                "work_type": "compare_options",
                "approval": {"required": True},
                "approval_prompt": "Approve this staged candidate.",
                "staged_action_url": "https://example.test/candidate",
            },
            "approval_outcome": {},
        },
    )

    assert surface["ready"] is True
    assert surface["current_packet_user_action_required"] is True
    assert surface["telegram_approval_surface_ready"] is True
    assert surface["manual_outcome_capture_ready"] is True


def test_normalize_approval_capture_surface_downgrades_unverified_live_callback_to_manual_capture() -> None:
    module = _load_script()

    surface = module._normalize_approval_capture_surface(  # noqa: SLF001
        {
            "ready": True,
            "mode": "telegram_callback_pending",
            "telegram_approval_surface_ready": True,
            "manual_outcome_capture_ready": True,
            "current_packet_approval_request_recordable": True,
            "current_packet_live_pending_count": 1,
        },
        {"checked": False},
    )

    assert surface["ready"] is True
    assert surface["mode"] == "manual_outcome_capture_ready"
    assert surface["telegram_approval_surface_ready"] is False
    assert surface["manual_outcome_capture_ready"] is True
    assert surface["current_packet_live_pending_count"] == 1


def test_materialize_proactive_ooda_operator_status_prioritizes_approval_followthrough_over_workspace_reauth(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_route",
        lambda **_kwargs: {
            "probe_ok": True,
            "source": "docker_compose_exec",
            "runtime_service": "ea-proactive-ooda",
            "observed_at": "2026-06-28T13:50:00Z",
            "live_receipt_checked": True,
            "live_receipt": {
                "ok": True,
                "receipt_path": "/app/state/proactive_ooda/live-receipt.json",
                "delivery_next_action": "",
                "delivery_route_error": "",
                "delivery_recovery_hint": "",
                "errors": [],
                "generated_at": "2026-06-28T13:49:00Z",
                "notification_status": "sent",
            },
            "route_report": {
                "ok": False,
                "errors": ["google_workspace_signal_source_unhealthy:google_oauth_invalid_grant"],
                "delivery_route": {
                    "ready": True,
                    "route_error": "",
                    "recovery_hint": "",
                    "next_action": "",
                    "selected_channel": "telegram",
                    "selected_transport": "telegram",
                    "selected_by": "tool_runtime_binding",
                    "available_channels": ["telegram"],
                },
                "delivery_guard": {"delivery_state": "eligible"},
                "stage_packets": {"ready": True, "errors": []},
                "safe_work_results": {"ready": True, "errors": []},
                "receipt_observation_count": 1,
                "actionable_count": 0,
                "source_mode": "google_workspace_error",
            },
        },
    )
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_artifacts",
        lambda **_kwargs: {
            "probe_ok": True,
            "source": "docker_compose_exec",
            "approval_outcome_path": "/data/provider-ledger/proactive_ooda_latest_approval_outcome.generated.json",
            "approval_callback_dir": "/data/provider-ledger/proactive_ooda_approval_callbacks",
            "approval_callback_dir_exists": True,
            "approval_callback_dir_writable": True,
            "approval_callback_record_count": 1,
            "approval_callback_pending_count": 1,
            "approval_callback_recorded_count": 0,
            "current_packet_callback_record_count": 1,
            "current_packet_callback_pending_count": 1,
            "current_packet_callback_recorded_count": 0,
            "current_packet_live_callback_record_count": 1,
            "current_packet_live_pending_count": 1,
            "current_packet_callback_latest_status": "pending",
            "current_packet_callback_latest_expired": False,
        },
    )
    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_approval_capture", _fake_approval_capture_probe)
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_gmail_draft",
        lambda **_kwargs: {
            "probe_ok": True,
            "status": "blocked",
            "source": "docker_compose_exec",
            "observed_at": "2026-06-28T13:50:30Z",
            "blocking_reason": "google_oauth_invalid_grant",
            "next_action": "reauthorize_google_workspace_binding",
            "next_action_href": "https://myexternalbrain.com/app/actions/google/connect?scope_bundle=full_workspace",
            "next_action_label": "Reconnect Google workspace",
            "next_action_method": "get",
            "raw_execution_payload_exposed": False,
        },
    )
    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_source_coverage", _fake_source_coverage_probe)

    output = tmp_path / ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json"
    receipt = module.build_proactive_ooda_operator_status(
        output_path=output,
        generated_at="2026-06-28T13:51:00Z",
        report_args=Namespace(principal_id="exec-1"),
    )

    assert receipt["status"] == "ready_with_live_receipt"
    assert receipt["reason"] == "google_workspace_signal_source_unhealthy:google_oauth_invalid_grant"
    assert receipt["operator_action_state"] == "approval_capture_pending"
    assert receipt["delivery_route_ready"] is True
    assert receipt["next_action"] == "tap_proactive_telegram_approval_button_or_record_proactive_ooda_approval_outcome"
    assert receipt["next_action_href"] == (
        "https://myexternalbrain.com/admin/proactive-ooda/approval"
    )
    assert receipt["next_action_label"] == "Record packet verdict"
    assert receipt["next_action_method"] == "get"
    assert receipt["approval_capture_surface"]["ready"] is True
    assert receipt["delivery_guard"]["delivery_state"] == "approval_capture_pending"
    assert receipt["delivery_guard"]["user_action_required"] is True
    assert "ready for operator follow-through" in receipt["summary"]


def test_materialize_proactive_ooda_operator_status_retries_host_runtime_probe_when_default_bundle_is_incomplete(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")
    monkeypatch.setattr(module, "_source_fingerprint", lambda path=module.ROOT: "source-fingerprint-123")
    monkeypatch.delenv("EA_LIVE_OPS_PREFER_HOST_RUNTIME_PROACTIVE_PROBE", raising=False)
    monkeypatch.delenv("EA_LIVE_OPS_FORCE_DOCKER_COMPOSE_EXEC", raising=False)

    route_probe_preferences: list[str | None] = []
    source_probe_preferences: list[str | None] = []

    def _fake_route_probe(**_kwargs: object) -> dict[str, object]:
        preference = os.getenv("EA_LIVE_OPS_PREFER_HOST_RUNTIME_PROACTIVE_PROBE")
        route_probe_preferences.append(preference)
        if preference != "1":
            return {}
        return {
            "probe_ok": True,
            "source": "host_python_exec",
            "runtime_service": "ea-proactive-ooda",
            "observed_at": "2026-07-06T11:20:00Z",
            "live_receipt_checked": True,
            "live_receipt": {
                "ok": True,
                "receipt_path": "/data/provider-ledger/proactive_ooda_run_receipts/live.json",
                "delivery_next_action": "",
                "delivery_route_error": "",
                "delivery_recovery_hint": "",
                "errors": [],
                "generated_at": "2026-07-06T11:19:00Z",
                "notification_status": "deferred",
            },
            "route_report": {
                "ok": True,
                "delivery_route": {
                    "ready": True,
                    "route_error": "",
                    "recovery_hint": "",
                    "next_action": "",
                    "selected_channel": "telegram",
                    "selected_transport": "telegram",
                    "selected_by": "tool_runtime_binding",
                    "available_channels": ["telegram"],
                },
                "delivery_guard": {"delivery_state": "no_actionable_items", "armed_send": True},
                "stage_packets": {"ready": True, "errors": []},
                "safe_work_results": {"ready": True, "errors": []},
                "receipt_observation_count": 1,
                "actionable_count": 0,
                "source_mode": "postgres_observations",
            },
        }

    def _fake_local_artifact_probe(**_kwargs: object) -> dict[str, object]:
        if os.getenv("EA_LIVE_OPS_PREFER_HOST_RUNTIME_PROACTIVE_PROBE") != "1":
            return {}
        return {
            "probe_ok": True,
            "source": "in_process_runtime",
            "approval_outcome_path": "/data/provider-ledger/proactive_ooda_latest_approval_outcome.generated.json",
            "approval_callback_dir": "/data/provider-ledger/proactive_ooda_approval_callbacks",
            "approval_callback_dir_exists": True,
            "approval_callback_dir_writable": True,
            "approval_callback_record_count": 27,
            "approval_callback_pending_count": 0,
            "approval_callback_recorded_count": 6,
            "current_packet_callback_record_count": 0,
            "current_packet_callback_pending_count": 0,
            "current_packet_callback_recorded_count": 0,
            "current_packet_live_callback_record_count": 0,
            "current_packet_live_pending_count": 0,
            "current_packet_callback_latest_status": "",
            "current_packet_callback_latest_expired": False,
            "current_packet": {
                "present": True,
                "status": "staged",
                "approval_outcome_matches_current_packet": False,
            },
            "stage_packet": {
                "schema": "proactive_ooda.stage_packet.v1",
                "packet_ref": "stage_packet:mirror-proof",
                "approval": {"required": True},
                "stage": {
                    "kind": "approval_packet",
                    "payload": {
                        "approval_prompt": "Approve this staged candidate.",
                        "approval_url": "https://example.test/candidate",
                    },
                },
            },
            "safe_work_result": {
                "schema": "proactive_ooda.safe_work_result.v1",
                "result_ref": "safe_work_result:mirror-proof",
                "status": "staged_for_user_decision",
                "approval": {"required": True},
                "approval_prompt": "Approve this staged candidate.",
                "staged_action_url": "https://example.test/candidate",
                "audit": {"status": "pass", "issues": []},
            },
            "approval_outcome": {},
        }

    def _fake_source_coverage(**_kwargs: object) -> dict[str, object]:
        preference = os.getenv("EA_LIVE_OPS_PREFER_HOST_RUNTIME_PROACTIVE_PROBE")
        source_probe_preferences.append(preference)
        if preference != "1":
            return {}
        return _fake_source_coverage_probe(**_kwargs)

    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_route", _fake_route_probe)
    monkeypatch.setattr(module, "_local_artifact_probe", _fake_local_artifact_probe)
    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_source_coverage", _fake_source_coverage)
    monkeypatch.setattr(
        module.ea_live_ops,
        "probe_proactive_gmail_draft",
        lambda **_kwargs: (
            {
                "probe_ok": True,
                "status": "no_pending_draft",
                "source": "host_python_exec",
                "observed_at": "2026-07-06T11:19:30Z",
            }
            if os.getenv("EA_LIVE_OPS_PREFER_HOST_RUNTIME_PROACTIVE_PROBE") == "1"
            else {}
        ),
    )

    output = tmp_path / ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json"
    receipt = module.build_proactive_ooda_operator_status(
        output_path=output,
        generated_at="2026-07-06T11:21:00Z",
        report_args=Namespace(principal_id="exec-1"),
    )

    assert route_probe_preferences == [None, "1"]
    assert source_probe_preferences == [None, "1"]
    assert receipt["status"] == "ready_with_live_receipt"
    assert receipt["route_probe_source"] == "host_python_exec"
    assert receipt["source_coverage"]["status"] == "ready"
    assert receipt["approval_capture_surface"]["manual_outcome_capture_ready"] is True


def test_materialize_proactive_ooda_operator_status_uses_live_route_probe_with_explicit_receipt_path(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")
    monkeypatch.setattr(module, "_source_fingerprint", lambda path=module.ROOT: "source-fingerprint-123")
    receipt_path = tmp_path / "state" / "proactive_ooda_latest_run.generated.json"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text("{}\n", encoding="utf-8")
    calls: dict[str, object] = {}

    def _fake_route_probe(**kwargs: object) -> dict[str, object]:
        calls["route"] = dict(kwargs)
        return {
            "probe_ok": True,
            "source": "docker_compose_exec",
            "runtime_service": "ea-proactive-ooda",
            "observed_at": "2026-07-01T04:20:00Z",
            "live_receipt_checked": True,
            "live_receipt": {
                "ok": True,
                "receipt_path": str(receipt_path),
                "delivery_mode": "operator_safe_mirror",
                "operator_safe_mirror_present": True,
                "errors": [],
                "notification_status": "deferred",
            },
            "route_report": {
                "ok": True,
                "errors": [],
                "delivery_route": {
                    "ready": True,
                    "route_error": "",
                    "recovery_hint": "",
                    "next_action": "",
                    "selected_channel": "telegram",
                    "selected_transport": "telegram",
                    "selected_by": "tool_runtime_binding",
                    "available_channels": ["telegram"],
                },
                "delivery_guard": {"delivery_state": "no_actionable_items", "armed_send": True},
                "stage_packets": {"ready": True, "errors": []},
                "safe_work_results": {"ready": True, "errors": []},
                "receipt_observation_count": 3,
                "actionable_count": 0,
                "source_mode": "none",
            },
        }

    def _unexpected_host_report(_args: object) -> dict[str, object]:
        raise AssertionError("live route probe should provide the route report")

    def _unexpected_artifact_probe(**_kwargs: object) -> dict[str, object]:
        raise AssertionError("explicit receipt paths should use local artifact probing")

    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_route", _fake_route_probe)
    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_artifacts", _unexpected_artifact_probe)
    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_source_coverage", _fake_source_coverage_probe)
    monkeypatch.setattr(module.proactive_verifier, "_build_report", _unexpected_host_report)

    output = tmp_path / ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json"
    receipt = module.build_proactive_ooda_operator_status(
        output_path=output,
        generated_at="2026-07-01T04:21:00Z",
        report_args=Namespace(principal_id="exec-1"),
        live_receipt_path=receipt_path,
    )

    assert calls["route"]["receipt_path"] == str(receipt_path)
    assert receipt["status"] == "ready_with_live_receipt"
    assert receipt["route_probe_source"] == "docker_compose_exec"
    assert receipt["delivery_route_ready"] is True
    assert receipt["live_receipt"]["operator_safe_mirror_present"] is True
    assert receipt["source_coverage"]["source"] == "docker_compose_exec"


def test_default_report_args_uses_configured_runtime_receipt_path(tmp_path: Path, monkeypatch) -> None:
    receipt_path = tmp_path / "state" / "custom-proactive-ooda.json"
    monkeypatch.setenv("EA_PROACTIVE_OODA_RECEIPT_PATH", str(receipt_path))

    module = _load_script()
    report_args = module._default_report_args()

    assert report_args.receipt_path == str(receipt_path)


def test_materialize_proactive_ooda_operator_status_uses_effective_default_receipt_path_for_route_probe(
    tmp_path: Path, monkeypatch
) -> None:
    receipt_path = tmp_path / "state" / "proactive_ooda_latest_run.generated.json"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text("{}\n", encoding="utf-8")
    monkeypatch.setenv("EA_PROACTIVE_OODA_RECEIPT_PATH", str(receipt_path))

    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")
    monkeypatch.setattr(module, "_source_fingerprint", lambda path=module.ROOT: "source-fingerprint-123")
    calls: dict[str, object] = {}

    def _fake_route_probe(**kwargs: object) -> dict[str, object]:
        calls["route"] = dict(kwargs)
        return {
            "probe_ok": True,
            "source": "docker_compose_exec",
            "runtime_service": "ea-proactive-ooda",
            "observed_at": "2026-07-02T15:00:00Z",
            "live_receipt_checked": True,
            "live_receipt": {
                "ok": True,
                "errors": [],
                "notification_status": "deferred",
            },
            "route_report": {
                "ok": True,
                "errors": [],
                "delivery_route": {
                    "ready": True,
                    "route_error": "",
                    "recovery_hint": "",
                    "next_action": "",
                    "selected_channel": "telegram",
                    "selected_transport": "telegram",
                    "selected_by": "tool_runtime_binding",
                    "available_channels": ["telegram"],
                },
                "delivery_guard": {"delivery_state": "no_actionable_items", "armed_send": True},
                "stage_packets": {"ready": True, "errors": []},
                "safe_work_results": {"ready": True, "errors": []},
                "receipt_observation_count": 3,
                "actionable_count": 0,
                "source_mode": "none",
            },
        }

    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_route", _fake_route_probe)
    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_source_coverage", _fake_source_coverage_probe)

    output = tmp_path / ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json"
    receipt = module.build_proactive_ooda_operator_status(
        output_path=output,
        generated_at="2026-07-02T15:01:00Z",
        report_args=Namespace(principal_id="exec-1"),
    )

    assert calls["route"]["receipt_path"] == str(receipt_path)
    assert receipt["live_receipt"]["receipt_path"] == str(receipt_path)


def test_materialize_proactive_ooda_operator_status_does_not_force_host_fallback_receipt_path_into_live_route_probe(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")
    monkeypatch.setattr(module, "_source_fingerprint", lambda path=module.ROOT: "source-fingerprint-123")
    calls: dict[str, object] = {}

    def _fake_route_probe(**kwargs: object) -> dict[str, object]:
        calls["route"] = dict(kwargs)
        return {
            "probe_ok": True,
            "source": "docker_compose_exec",
            "runtime_service": "ea-proactive-ooda",
            "observed_at": "2026-07-02T16:00:00Z",
            "live_receipt_checked": True,
            "live_receipt": {
                "ok": True,
                "errors": [],
                "receipt_path": "/data/provider-ledger/proactive_ooda_run_receipts/runtime-sent.json",
                "notification_status": "sent",
                "delivery_channel": "telegram",
                "delivery_message_count": 1,
                "telegram_message_count": 1,
            },
            "route_report": {
                "ok": True,
                "errors": [],
                "delivery_route": {
                    "ready": True,
                    "route_error": "",
                    "recovery_hint": "",
                    "next_action": "",
                    "selected_channel": "telegram",
                    "selected_transport": "telegram",
                    "selected_by": "tool_runtime_binding",
                    "available_channels": ["telegram"],
                },
                "delivery_guard": {"delivery_state": "no_actionable_items", "armed_send": True},
                "stage_packets": {"ready": True, "errors": []},
                "safe_work_results": {"ready": True, "errors": []},
                "receipt_observation_count": 3,
                "actionable_count": 0,
                "source_mode": "none",
            },
        }

    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_route", _fake_route_probe)
    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_source_coverage", _fake_source_coverage_probe)

    output = tmp_path / ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json"
    receipt = module.build_proactive_ooda_operator_status(
        output_path=output,
        generated_at="2026-07-02T16:01:00Z",
        report_args=Namespace(principal_id="exec-1"),
    )

    assert calls["route"]["receipt_path"] == ""
    assert receipt["live_receipt"]["receipt_path"] == "/data/provider-ledger/proactive_ooda_run_receipts/runtime-sent.json"


def test_materialize_proactive_ooda_operator_status_fills_missing_live_receipt_path_from_route_probe(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")
    monkeypatch.setattr(module, "_source_fingerprint", lambda path=module.ROOT: "source-fingerprint-123")
    receipt_path = tmp_path / "state" / "proactive_ooda_latest_run.generated.json"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text("{}\n", encoding="utf-8")

    def _fake_route_probe(**_kwargs: object) -> dict[str, object]:
        return {
            "probe_ok": True,
            "source": "docker_compose_exec",
            "runtime_service": "ea-proactive-ooda",
            "observed_at": "2026-07-01T04:20:00Z",
            "live_receipt_checked": True,
            "live_receipt": {
                "ok": False,
                "reason": "TimeoutExpired:5s",
                "errors": [],
            },
            "route_report": {
                "ok": True,
                "errors": [],
                "delivery_route": {
                    "ready": True,
                    "route_error": "",
                    "recovery_hint": "",
                    "next_action": "",
                    "selected_channel": "telegram",
                    "selected_transport": "telegram",
                    "selected_by": "tool_runtime_binding",
                    "available_channels": ["telegram"],
                },
                "delivery_guard": {"delivery_state": "no_actionable_items", "armed_send": True},
                "stage_packets": {"ready": True, "errors": []},
                "safe_work_results": {"ready": True, "errors": []},
                "receipt_observation_count": 3,
                "actionable_count": 0,
                "source_mode": "none",
            },
        }

    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_route", _fake_route_probe)
    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_source_coverage", _fake_source_coverage_probe)

    output = tmp_path / ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json"
    receipt = module.build_proactive_ooda_operator_status(
        output_path=output,
        generated_at="2026-07-01T04:21:00Z",
        report_args=Namespace(principal_id="exec-1"),
        live_receipt_path=receipt_path,
    )

    assert receipt["live_receipt_checked"] is True
    assert receipt["live_receipt"]["receipt_path"] == str(receipt_path)


def test_materialize_proactive_ooda_operator_status_recovers_from_explicit_missing_receipt_via_unpinned_route_probe(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")
    monkeypatch.setattr(module, "_source_fingerprint", lambda path=module.ROOT: "source-fingerprint-123")
    receipt_path = tmp_path / "state" / "proactive_ooda_latest_run.generated.json"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text("{}\n", encoding="utf-8")
    route_calls: list[dict[str, object]] = []

    def _fake_route_probe(**kwargs: object) -> dict[str, object]:
        route_calls.append(dict(kwargs))
        pinned = str(kwargs.get("receipt_path") or "").strip()
        if pinned:
            return {
                "probe_ok": True,
                "source": "docker_compose_exec",
                "runtime_service": "ea-proactive-ooda",
                "observed_at": "2026-07-06T12:22:15Z",
                "live_receipt_checked": True,
                "live_receipt": {
                    "ok": False,
                    "receipt_path": pinned,
                    "errors": ["receipt_missing"],
                    "notification_status": "",
                },
                "route_report": {
                    "ok": True,
                    "errors": [],
                    "delivery_route": {
                        "ready": True,
                        "route_error": "",
                        "recovery_hint": "",
                        "next_action": "",
                        "selected_channel": "telegram",
                        "selected_transport": "telegram",
                        "selected_by": "tool_runtime_binding",
                        "available_channels": ["telegram"],
                    },
                    "delivery_guard": {"delivery_state": "no_actionable_items", "armed_send": True},
                    "stage_packets": {"ready": True, "errors": []},
                    "safe_work_results": {"ready": True, "errors": []},
                    "receipt_observation_count": 3,
                    "actionable_count": 0,
                    "source_mode": "none",
                },
            }
        return {
            "probe_ok": True,
            "source": "docker_compose_exec",
            "runtime_service": "ea-proactive-ooda",
            "observed_at": "2026-07-06T12:22:19Z",
            "live_receipt_checked": True,
            "live_receipt": {
                "ok": True,
                "receipt_path": "/data/provider-ledger/proactive_ooda_run_receipts/runtime-sent.json",
                "errors": [],
                "archived_sent_receipt_used": True,
                "notification_status": "sent",
                "followthrough_status": "ok",
                "followthrough_operator_status": "ready_with_recovery_action",
                "delivery_channel": "telegram",
                "delivery_message_count": 1,
                "telegram_message_count": 1,
                "delivery_mode": "telegram_sent",
            },
            "route_report": {
                "ok": True,
                "errors": [],
                "delivery_route": {
                    "ready": True,
                    "route_error": "",
                    "recovery_hint": "",
                    "next_action": "",
                    "selected_channel": "telegram",
                    "selected_transport": "telegram",
                    "selected_by": "tool_runtime_binding",
                    "available_channels": ["telegram"],
                },
                "delivery_guard": {"delivery_state": "no_actionable_items", "armed_send": True},
                "stage_packets": {"ready": True, "errors": []},
                "safe_work_results": {"ready": True, "errors": []},
                "receipt_observation_count": 4,
                "actionable_count": 0,
                "source_mode": "none",
            },
        }

    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_route", _fake_route_probe)
    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_source_coverage", _fake_source_coverage_probe)

    output = tmp_path / ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json"
    receipt = module.build_proactive_ooda_operator_status(
        output_path=output,
        generated_at="2026-07-06T12:23:00Z",
        report_args=Namespace(principal_id="exec-1"),
        live_receipt_path=receipt_path,
    )

    assert [str(call.get("receipt_path") or "") for call in route_calls] == [str(receipt_path), ""]
    assert receipt["status"] == "ready_with_live_receipt"
    assert receipt["route_probe_source"] == "docker_compose_exec"
    assert receipt["live_receipt"]["ok"] is True
    assert receipt["live_receipt"]["archived_sent_receipt_used"] is True
    assert receipt["live_receipt"]["receipt_path"] == "/data/provider-ledger/proactive_ooda_run_receipts/runtime-sent.json"


def test_materialize_proactive_ooda_operator_status_propagates_effective_default_receipt_path_to_host_verifier(
    tmp_path: Path, monkeypatch
) -> None:
    receipt_path = tmp_path / "state" / "proactive_ooda_latest_run.generated.json"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text("{}\n", encoding="utf-8")
    monkeypatch.setenv("EA_PROACTIVE_OODA_RECEIPT_PATH", str(receipt_path))

    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")
    monkeypatch.setattr(module, "_source_fingerprint", lambda path=module.ROOT: "source-fingerprint-123")
    calls: dict[str, object] = {}

    def _fake_build_report(args: Namespace) -> dict[str, object]:
        calls["build_report_receipt_path"] = getattr(args, "receipt_path", "")
        return {
            "ok": True,
            "errors": [],
            "delivery_route": {
                "ready": True,
                "route_error": "",
                "recovery_hint": "",
                "next_action": "",
                "selected_channel": "telegram",
                "selected_transport": "telegram",
                "selected_by": "tool_runtime_binding",
                "available_channels": ["telegram"],
            },
            "delivery_guard": {
                "delivery_state": "no_actionable_items",
                "armed_send": False,
            },
            "stage_packets": {"ready": True, "errors": []},
            "safe_work_results": {"ready": True, "errors": []},
            "receipt_observation_count": 0,
            "actionable_count": 0,
            "source_mode": "none",
        }

    def _fake_verify_receipt(path: Path) -> dict[str, object]:
        calls["verify_receipt_path"] = str(path)
        return {
            "ok": True,
            "errors": [],
            "receipt_path": str(path),
            "notification_status": "deferred",
            "delivery_channel": "telegram",
            "delivery_message_count": 1,
            "telegram_message_count": 1,
            "delivery_route_error": "",
            "delivery_recovery_hint": "",
            "delivery_next_action": "",
            "generated_at": "2026-07-02T15:02:00Z",
        }

    monkeypatch.setattr(module.proactive_verifier, "_build_report", _fake_build_report)
    monkeypatch.setattr(module.live_receipt_verifier, "verify_receipt", _fake_verify_receipt)

    output = tmp_path / ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json"
    receipt = module.build_proactive_ooda_operator_status(
        output_path=output,
        generated_at="2026-07-02T15:03:00Z",
        report_args=Namespace(principal_id="exec-1"),
        allow_live_route_probe=False,
    )

    assert calls["build_report_receipt_path"] == str(receipt_path)
    assert calls["verify_receipt_path"] == str(receipt_path)
    assert receipt["live_receipt"]["receipt_path"] == str(receipt_path)


def test_materialize_proactive_ooda_operator_status_reports_unarmed_stage_only_posture(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")
    monkeypatch.setattr(
        module.proactive_verifier,
        "_build_report",
        lambda _args: {
            "ok": True,
            "delivery_route": {
                "ready": True,
                "route_error": "",
                "recovery_hint": "",
                "next_action": "",
                "selected_channel": "telegram",
                "selected_transport": "telegram",
                "selected_by": "tool_runtime_binding",
                "available_channels": ["telegram"],
            },
            "delivery_guard": {
                "delivery_state": "deferred",
                "deferred_reason": "deferred_by_unarmed_send",
                "armed_send": False,
            },
            "stage_packets": {"ready": True, "errors": []},
            "safe_work_results": {"ready": True, "errors": []},
            "receipt_observation_count": 0,
            "actionable_count": 1,
            "source_mode": "signals_json",
        },
    )
    monkeypatch.setattr(
        module.live_receipt_verifier,
        "verify_receipt",
        lambda _path: {
            "ok": False,
            "errors": ["receipt_missing"],
            "receipt_path": str(tmp_path / "live-receipt.json"),
            "notification_status": "",
            "delivery_channel": "",
            "delivery_message_count": 0,
            "telegram_message_count": 0,
            "delivery_route_error": "",
            "delivery_recovery_hint": "",
            "delivery_next_action": "",
            "generated_at": "",
        },
    )

    output = tmp_path / ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json"
    receipt = module.build_proactive_ooda_operator_status(
        output_path=output,
        generated_at="2026-06-28T14:30:00Z",
        report_args=Namespace(armed_send=False),
        live_receipt_path=tmp_path / "live-receipt.json",
        allow_live_route_probe=False,
    )

    assert receipt["status"] == "deferred"
    assert receipt["reason"] == "deferred_by_unarmed_send"
    assert receipt["next_action"] == "arm_proactive_send_for_live_delivery"
    assert receipt["operator_action_state"] == "arming_required"
    assert receipt["summary"] == "Proactive OODA delivery is intentionally stage-only because send arming is disabled for this runtime."
    assert receipt["delivery_guard"]["armed_send"] is False


def test_materialize_proactive_ooda_operator_status_surfaces_followthrough_recovery_action(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")
    monkeypatch.setattr(
        module.proactive_verifier,
        "_build_report",
        lambda _args: {
            "ok": True,
            "delivery_route": {
                "ready": True,
                "route_error": "",
                "recovery_hint": "",
                "next_action": "",
                "selected_channel": "telegram",
                "selected_transport": "telegram",
                "selected_by": "tool_runtime_binding",
                "available_channels": ["telegram"],
            },
            "delivery_guard": {"delivery_state": "eligible", "armed_send": True},
            "stage_packets": {"ready": True, "errors": []},
            "safe_work_results": {"ready": True, "errors": []},
            "receipt_observation_count": 1,
            "actionable_count": 1,
            "source_mode": "signals_json",
        },
    )
    monkeypatch.setattr(
        module.live_receipt_verifier,
        "verify_receipt",
        lambda _path: {
            "ok": False,
            "errors": ["followthrough_status_not_ok"],
            "receipt_path": str(tmp_path / "live-receipt.json"),
            "notification_status": "sent",
            "delivery_channel": "telegram",
            "delivery_message_count": 1,
            "telegram_message_count": 1,
            "delivery_route_error": "",
            "delivery_recovery_hint": "",
            "delivery_next_action": "repair_proactive_operator_runtime_posture",
            "generated_at": "2026-07-06T10:12:00Z",
            "followthrough_status": "failed",
            "followthrough_reason": "AttributeError",
        },
    )

    output = tmp_path / ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json"
    receipt = module.build_proactive_ooda_operator_status(
        output_path=output,
        generated_at="2026-07-06T10:15:00Z",
        report_args=Namespace(armed_send=True),
        live_receipt_path=tmp_path / "live-receipt.json",
        allow_live_route_probe=False,
    )

    assert receipt["status"] == "ready_with_recovery_action"
    assert receipt["reason"] == "followthrough_status_not_ok"
    assert receipt["next_action"] == "repair_proactive_operator_runtime_posture"
    assert receipt["next_action_label"] == "Open goals"


def test_materialize_proactive_ooda_operator_status_humanizes_quiet_hours_deferral(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")
    monkeypatch.setattr(
        module.proactive_verifier,
        "_build_report",
        lambda _args: {
            "ok": True,
            "delivery_route": {
                "ready": True,
                "route_error": "",
                "recovery_hint": "",
                "next_action": "",
                "selected_channel": "telegram",
                "selected_transport": "telegram",
                "selected_by": "tool_runtime_binding",
                "available_channels": ["telegram"],
            },
            "delivery_guard": {
                "delivery_state": "deferred",
                "deferred_reason": "deferred_by_quiet_hours",
                "armed_send": True,
                "quiet_hours_active": True,
                "interruption_budget_exhausted": False,
            },
            "stage_packets": {"ready": True, "errors": []},
            "safe_work_results": {"ready": True, "errors": []},
            "receipt_observation_count": 0,
            "actionable_count": 1,
            "source_mode": "signals_json",
        },
    )
    monkeypatch.setattr(
        module.live_receipt_verifier,
        "verify_receipt",
        lambda _path: {
            "ok": False,
            "errors": ["receipt_missing"],
            "receipt_path": str(tmp_path / "live-receipt.json"),
            "notification_status": "",
            "delivery_channel": "",
            "delivery_message_count": 0,
            "telegram_message_count": 0,
            "delivery_route_error": "",
            "delivery_recovery_hint": "",
            "delivery_next_action": "",
            "generated_at": "",
        },
    )

    receipt = module.build_proactive_ooda_operator_status(
        output_path=tmp_path / ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json",
        generated_at="2026-07-02T22:30:00Z",
        report_args=Namespace(armed_send=True),
        live_receipt_path=tmp_path / "live-receipt.json",
        allow_live_route_probe=False,
    )

    assert receipt["status"] == "deferred"
    assert receipt["reason"] == "deferred_by_quiet_hours"
    assert receipt["next_action"] == "resume_after_quiet_hours"
    assert receipt["operator_action_state"] == "deferred"
    assert receipt["summary"] == "Proactive OODA delivery is currently deferred by quiet hours."
    assert receipt["delivery_guard"]["quiet_hours_active"] is True


def test_materialize_proactive_ooda_operator_status_humanizes_interruption_budget_deferral(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")
    monkeypatch.setattr(
        module.proactive_verifier,
        "_build_report",
        lambda _args: {
            "ok": True,
            "delivery_route": {
                "ready": True,
                "route_error": "",
                "recovery_hint": "",
                "next_action": "",
                "selected_channel": "telegram",
                "selected_transport": "telegram",
                "selected_by": "tool_runtime_binding",
                "available_channels": ["telegram"],
            },
            "delivery_guard": {
                "delivery_state": "deferred",
                "deferred_reason": "deferred_by_interruption_budget",
                "armed_send": True,
                "quiet_hours_active": False,
                "interruption_budget_exhausted": True,
            },
            "stage_packets": {"ready": True, "errors": []},
            "safe_work_results": {"ready": True, "errors": []},
            "receipt_observation_count": 0,
            "actionable_count": 1,
            "source_mode": "signals_json",
        },
    )
    monkeypatch.setattr(
        module.live_receipt_verifier,
        "verify_receipt",
        lambda _path: {
            "ok": False,
            "errors": ["receipt_missing"],
            "receipt_path": str(tmp_path / "live-receipt.json"),
            "notification_status": "",
            "delivery_channel": "",
            "delivery_message_count": 0,
            "telegram_message_count": 0,
            "delivery_route_error": "",
            "delivery_recovery_hint": "",
            "delivery_next_action": "",
            "generated_at": "",
        },
    )

    receipt = module.build_proactive_ooda_operator_status(
        output_path=tmp_path / ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json",
        generated_at="2026-07-02T22:45:00Z",
        report_args=Namespace(armed_send=True),
        live_receipt_path=tmp_path / "live-receipt.json",
        allow_live_route_probe=False,
    )

    assert receipt["status"] == "deferred"
    assert receipt["reason"] == "deferred_by_interruption_budget"
    assert receipt["next_action"] == "wait_for_interruption_budget_window"
    assert receipt["operator_action_state"] == "deferred"
    assert receipt["summary"] == "Proactive OODA delivery is currently deferred because the interruption budget is exhausted."
    assert receipt["delivery_guard"]["interruption_budget_exhausted"] is True


def test_materialize_proactive_ooda_operator_status_humanizes_notification_cooldown_deferral(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")
    monkeypatch.setattr(
        module.proactive_verifier,
        "_build_report",
        lambda _args: {
            "ok": True,
            "delivery_route": {
                "ready": True,
                "route_error": "",
                "recovery_hint": "",
                "next_action": "",
                "selected_channel": "telegram",
                "selected_transport": "telegram",
                "selected_by": "tool_runtime_binding",
                "available_channels": ["telegram"],
            },
            "delivery_guard": {
                "delivery_state": "deferred",
                "deferred_reason": "deferred_by_notification_cooldown",
                "armed_send": True,
                "quiet_hours_active": False,
                "interruption_budget_exhausted": False,
                "notification_cooldown_active": True,
                "notification_cooldown_seconds_remaining": 1200,
            },
            "stage_packets": {"ready": True, "errors": []},
            "safe_work_results": {"ready": True, "errors": []},
            "receipt_observation_count": 0,
            "actionable_count": 1,
            "source_mode": "signals_json",
        },
    )
    monkeypatch.setattr(
        module.live_receipt_verifier,
        "verify_receipt",
        lambda _path: {
            "ok": False,
            "errors": ["receipt_missing"],
            "receipt_path": str(tmp_path / "live-receipt.json"),
            "notification_status": "",
            "delivery_channel": "",
            "delivery_message_count": 0,
            "telegram_message_count": 0,
            "delivery_route_error": "",
            "delivery_recovery_hint": "",
            "delivery_next_action": "",
            "generated_at": "",
        },
    )

    receipt = module.build_proactive_ooda_operator_status(
        output_path=tmp_path / ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json",
        generated_at="2026-07-02T22:50:00Z",
        report_args=Namespace(armed_send=True),
        live_receipt_path=tmp_path / "live-receipt.json",
        allow_live_route_probe=False,
    )

    assert receipt["status"] == "deferred"
    assert receipt["reason"] == "deferred_by_notification_cooldown"
    assert receipt["next_action"] == "wait_for_notification_cooldown"
    assert receipt["next_action_label"] == "Open Today"
    assert receipt["operator_action_state"] == "deferred"
    assert receipt["summary"] == "Proactive OODA delivery is currently deferred by the notification cooldown (1200s remaining)."
    assert receipt["delivery_guard"]["notification_cooldown_active"] is True
    assert receipt["delivery_guard"]["notification_cooldown_seconds_remaining"] == 1200


def test_materialize_proactive_ooda_operator_status_default_report_args_include_notification_cooldown_env(
    monkeypatch
) -> None:
    module = _load_script()
    monkeypatch.setenv("EA_PROACTIVE_OODA_NOTIFICATION_COOLDOWN_SECONDS", "900")
    monkeypatch.setenv("EA_PROACTIVE_OODA_NOTIFICATION_COOLDOWN_ALLOW_HIGH_PRIORITY", "0")

    args = module._default_report_args()

    assert args.notification_cooldown_seconds == 900
    assert args.notification_cooldown_allow_high_priority is False


def test_materialize_proactive_ooda_operator_status_uses_local_callback_surface_when_live_probe_is_skipped(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_script()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "_git_head", lambda path=module.ROOT: "source-head-123")
    monkeypatch.setattr(
        module.proactive_verifier,
        "_build_report",
        lambda _args: {
            "ok": True,
            "delivery_route": {
                "ready": True,
                "route_error": "",
                "recovery_hint": "",
                "next_action": "",
                "selected_channel": "telegram",
                "selected_transport": "telegram",
                "selected_by": "tool_runtime_binding",
                "available_channels": ["telegram"],
            },
            "delivery_guard": {"delivery_state": "eligible", "armed_send": False},
            "stage_packets": {"ready": True, "errors": []},
            "safe_work_results": {"ready": True, "errors": []},
            "receipt_observation_count": 0,
            "actionable_count": 1,
            "source_mode": "signals_json",
        },
    )
    monkeypatch.setattr(
        module.live_receipt_verifier,
        "verify_receipt",
        lambda _path: {
            "ok": False,
            "errors": ["receipt_missing"],
            "receipt_path": str(tmp_path / "state" / "proactive_ooda_latest_run.generated.json"),
            "notification_status": "deferred",
            "delivery_channel": "",
            "delivery_message_count": 0,
            "telegram_message_count": 0,
            "delivery_route_error": "",
            "delivery_recovery_hint": "",
            "delivery_next_action": "",
            "generated_at": "",
        },
    )

    stage_dir = tmp_path / "state" / "proactive_ooda_stage_packets"
    safe_dir = tmp_path / "state" / "proactive_ooda_safe_work_results"
    callback_dir = tmp_path / "state" / "proactive_ooda_approval_callbacks"
    stage_dir.mkdir(parents=True, exist_ok=True)
    safe_dir.mkdir(parents=True, exist_ok=True)
    callback_dir.mkdir(parents=True, exist_ok=True)
    (tmp_path / "state" / "proactive_ooda_notified.json").parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "state" / "proactive_ooda_notified.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "state" / "proactive_ooda_latest_run.generated.json").write_text(
        json.dumps(
            {
                "notification_status": "deferred",
                "item_count": 1,
                "stage_packet_output_dir": str(stage_dir),
                "safe_work_result_output_dir": str(safe_dir),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (stage_dir / "pkt-1.json").write_text(
        json.dumps(
            {
                "schema": "proactive_ooda.stage_packet.v1",
                "packet_ref": "stage_packet:packet-1",
                "stage": {"kind": "approval_packet"},
                "approval": {"required": True},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (safe_dir / "res-1.json").write_text(
        json.dumps(
            {
                "schema": "proactive_ooda.safe_work_result.v1",
                "result_ref": "safe_work_result:result-1",
                "source_packet_ref_hash": __import__("hashlib").sha256("stage_packet:packet-1".encode("utf-8")).hexdigest(),
                "status": "staged_for_user_decision",
                "approval": {"required": True},
                "approval_prompt": "Approve this staged candidate.",
                "staged_action_url": "https://example.test/candidate",
                "audit": {"status": "pass", "issues": []},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (callback_dir / "callback.json").write_text(
        json.dumps(
            {
                "schema": "ea.proactive_ooda_telegram_approval_callback.v1",
                "callback_token": "cb-1",
                "status": "pending",
                "created_at": "2026-06-28T14:00:00Z",
                "expires_at": "2099-01-01T00:00:00Z",
                "packet_ref": "stage_packet:packet-1",
                "staged_artifact_ref": "safe_work_result:result-1",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    output = tmp_path / ".codex-studio/published/ea_proactive_ooda_operator_status.generated.json"
    receipt = module.build_proactive_ooda_operator_status(
        output_path=output,
        generated_at="2026-06-28T14:40:00Z",
        report_args=Namespace(
            principal_id="exec",
            state_path="state/proactive_ooda_notified.json",
            stage_packet_dir="state/proactive_ooda_stage_packets",
            safe_work_result_dir="state/proactive_ooda_safe_work_results",
            armed_send=False,
        ),
        live_receipt_path=tmp_path / "state" / "proactive_ooda_latest_run.generated.json",
        allow_live_route_probe=False,
    )

    assert receipt["approval_capture_surface"]["source"] == "local_filesystem"
    assert receipt["approval_capture_surface"]["ready"] is True
    assert receipt["approval_capture_surface"]["mode"] == "manual_outcome_capture_ready"
    assert receipt["approval_capture_surface"]["telegram_approval_surface_ready"] is False
    assert receipt["approval_capture_surface"]["manual_outcome_capture_ready"] is True
    assert receipt["approval_capture_surface"]["callback_dir_exists"] is True
    assert receipt["approval_capture_surface"]["current_packet_callback_record_count"] == 1
    assert receipt["approval_capture_surface"]["current_packet_live_pending_count"] == 1
    assert receipt["approval_capture_surface"]["current_packet_callback_latest_created_at"] == "2026-06-28T14:00:00Z"
    assert receipt["approval_capture_surface"]["current_packet_callback_latest_expires_at"] == "2099-01-01T00:00:00Z"
    assert isinstance(receipt["approval_capture_surface"]["current_packet_callback_latest_age_seconds"], int)
    assert receipt["approval_capture_surface"]["current_packet_callback_latest_seconds_until_expiry"] > 0
    assert receipt["safe_work_audit"]["present"] is True
    assert receipt["safe_work_audit"]["audit_status"] == "pass"
    assert receipt["safe_work_audit"]["delivery_allowed"] is True
    assert receipt["safe_work_audit"]["privacy"]["raw_issue_details_exposed"] is False
