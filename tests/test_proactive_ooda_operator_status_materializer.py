from __future__ import annotations

import importlib.util
import json
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
        "status": "ready_with_gaps",
        "source": "docker_compose_exec",
        "observed_at": "2026-06-29T08:00:00Z",
        "observation_repository": "PostgresObservationEventRepository",
        "observation_limit": 400,
        "observation_row_count": 3,
        "lane_count": 8,
        "observed_lane_count": 3,
        "missing_lane_keys": [
            "calendar_and_renewal_signals",
            "relationship_and_occasion_signals",
            "shopping_and_vendor_signals",
            "commitment_and_deadline_signals",
            "durable_profile_and_location_context",
        ],
        "lanes": [
            {
                "key": "postgres_observations",
                "label": "Postgres observations",
                "status": "observed",
                "observed": True,
                "record_count": 3,
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
                "record_count": 1,
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
                    "status": "not_observed",
                    "observed": False,
                    "record_count": 0,
                    "latest_observed_at": "",
                    "evidence_event_types": [],
                    "next_action": "sync_source",
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
    assert receipt["verifier_commands"] == [
        "make verify-proactive-ooda",
        "make verify-proactive-ooda-live-receipt",
        "make verify-proactive-ooda-operator-status",
    ]

    persisted = json.loads(output.read_text(encoding="utf-8"))
    assert persisted["status"] == "ready_with_recovery_action"
    assert persisted["next_action"] == "scan_whatsapp_web_qr"


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
    assert receipt["live_receipt_checked"] is True
    assert receipt["live_receipt"]["ok"] is True
    assert receipt["next_action"] == "scan_whatsapp_web_qr"
    assert receipt["operator_action_state"] == "recovery_required"
    assert receipt["approval_capture_surface"]["ready"] is True
    assert receipt["approval_capture_surface"]["callback_dir_writable"] is True
    assert receipt["approval_capture_surface"]["current_packet_callback_record_count"] == 1
    assert receipt["approval_capture_surface"]["current_packet_live_pending_count"] == 1
    assert receipt["gmail_draft_followthrough"]["status"] == "already_executed"
    assert receipt["gmail_draft_followthrough"]["action"] == "save_gmail_draft"
    assert receipt["gmail_draft_followthrough"]["execution_observation_present"] is True
    assert receipt["gmail_draft_followthrough"]["gmail_draft_id_hash_present"] is True
    assert receipt["gmail_draft_followthrough"]["raw_execution_payload_exposed"] is False
    assert receipt["source_coverage"]["status"] == "ready_with_gaps"
    assert receipt["source_coverage"]["privacy"]["raw_transcript_text_exposed"] is False


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
    assert receipt["source_coverage"]["observed_lane_count"] == 3


def test_materialize_proactive_ooda_operator_status_blocks_when_live_route_probe_reports_workspace_failure(
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

    assert receipt["status"] == "ready_with_recovery_action"
    assert receipt["reason"] == "google_workspace_signal_source_unhealthy:google_oauth_invalid_grant"
    assert receipt["operator_action_state"] == "recovery_required"
    assert receipt["delivery_route_ready"] is True
    assert receipt["next_action"] == "reauthorize_google_workspace_binding"
    assert receipt["next_action_href"] == (
        "https://myexternalbrain.com/app/actions/google/connect?"
        "return_to=%2Fapp%2Fsettings%2Fgoogle&scope_bundle=full_workspace"
    )
    assert receipt["next_action_label"] == "Reconnect Google workspace"
    assert receipt["next_action_method"] == "get"
    assert receipt["approval_capture_surface"]["ready"] is True
    assert "Google workspace needs reauthorization" in receipt["summary"]


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
    )

    assert receipt["status"] == "deferred"
    assert receipt["reason"] == "deferred_by_unarmed_send"
    assert receipt["next_action"] == "arm_proactive_send_for_live_delivery"
    assert receipt["operator_action_state"] == "arming_required"
    assert receipt["summary"] == "Proactive OODA delivery is intentionally stage-only because send arming is disabled for this runtime."
    assert receipt["delivery_guard"]["armed_send"] is False


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
    )

    assert receipt["approval_capture_surface"]["source"] == "local_filesystem"
    assert receipt["approval_capture_surface"]["ready"] is True
    assert receipt["approval_capture_surface"]["callback_dir_exists"] is True
    assert receipt["approval_capture_surface"]["current_packet_callback_record_count"] == 1
    assert receipt["approval_capture_surface"]["current_packet_live_pending_count"] == 1
    assert receipt["approval_capture_surface"]["current_packet_callback_latest_created_at"] == "2026-06-28T14:00:00Z"
    assert receipt["approval_capture_surface"]["current_packet_callback_latest_expires_at"] == "2099-01-01T00:00:00Z"
    assert isinstance(receipt["approval_capture_surface"]["current_packet_callback_latest_age_seconds"], int)
    assert receipt["approval_capture_surface"]["current_packet_callback_latest_seconds_until_expiry"] > 0
