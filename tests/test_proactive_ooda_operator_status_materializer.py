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
        "flat_search_enabled": False,
        "excluded_event_types": ["property_scout_sync_completed"],
        "excluded_event_type_counts": {"property_scout_sync_completed": 3},
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
    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_source_coverage", _fake_source_coverage_probe)

    receipt = module.build_proactive_ooda_operator_status(
        output_path=tmp_path / "ea_proactive_ooda_operator_status.generated.json",
        generated_at="2026-07-01T12:01:00Z",
        report_args=Namespace(principal_id="exec-1"),
    )

    assert artifact_calls == []
    assert receipt["approval_capture_surface"]["source"] == "docker_compose_exec"
    assert receipt["approval_capture_surface"]["current_packet_callback_record_count"] == 1


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
    monkeypatch.setattr(module.ea_live_ops, "probe_proactive_source_coverage", _fake_source_coverage_probe)
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
    assert receipt["verifier_commands"] == [
        "make verify-proactive-ooda",
        "make verify-proactive-ooda-live-receipt",
        "make verify-proactive-ooda-operator-status",
    ]

    persisted = json.loads(output.read_text(encoding="utf-8"))
    assert persisted["status"] == "ready_with_recovery_action"
    assert persisted["next_action"] == "scan_whatsapp_web_qr"


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
    assert receipt["stage_packets"] == {"ready": False, "errors": []}
    assert receipt["safe_work_results"] == {"ready": False, "errors": []}
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
    assert receipt["source_coverage"]["status"] == "ready_with_gaps"
    assert receipt["source_coverage"]["flat_search_enabled"] is False
    assert receipt["source_coverage"]["excluded_event_types"] == ["property_scout_sync_completed"]
    assert receipt["source_coverage"]["excluded_event_type_counts"] == {"property_scout_sync_completed": 3}
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
    assert receipt["source_coverage"]["observed_lane_count"] == 3


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
