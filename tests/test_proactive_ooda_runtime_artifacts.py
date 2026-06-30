from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.services.proactive_ooda_runtime_artifacts import (
    load_runtime_artifact_bundle,
    select_current_approval_outcome_for_bundle,
)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def test_load_runtime_artifact_bundle_prefers_matching_archived_sent_receipt(tmp_path: Path) -> None:
    state_path = "state/proactive_ooda_notified.json"
    primary_receipt_path = tmp_path / "state" / "proactive_ooda_latest_run.generated.json"
    archive_receipt_path = tmp_path / "state" / "proactive_ooda_run_receipts" / "20260628T105700Z-sent-proof.json"
    stage_dir = tmp_path / "state" / "proactive_ooda_stage_packets"
    safe_dir = tmp_path / "state" / "proactive_ooda_safe_work_results"

    stage_packet = {
        "schema": "proactive_ooda.stage_packet.v1",
        "packet_ref": "stage_packet:pkt-live",
        "stage": {"kind": "approval_packet"},
        "approval": {"required": True},
    }
    safe_work_result = {
        "schema": "proactive_ooda.safe_work_result.v1",
        "result_ref": "safe_work_result:res-live",
        "source_packet_ref_hash": _sha256(stage_packet["packet_ref"]),
        "status": "staged_for_user_decision",
        "recommended_option_or_draft": {
            "kind": "shortlist_candidate",
            "value": {"label": "Vendor A", "url": "https://example.test/vendor-a"},
        },
        "approval": {"required": True},
        "execution_receipt": {
            "network_fetch_count": 1,
            "network_fetch_success_count": 1,
            "page_checks": [{"url": "https://example.test/vendor-a", "reachable": True}],
            "irreversible_actions_attempted": [],
        },
    }
    _write_json(stage_dir / "pkt-live.json", stage_packet)
    _write_json(safe_dir / "res-live.json", safe_work_result)
    _write_json(
        primary_receipt_path,
        {
            "notification_status": "skipped_no_items",
            "item_count": 0,
            "stage_packet_output_dir": str(stage_dir),
            "safe_work_result_output_dir": str(safe_dir),
            "stage_packet_ref_hashes": [],
            "safe_work_result_ref_hashes": [],
            "telegram_message_ids": [],
        },
    )
    _write_json(
        archive_receipt_path,
        {
            "notification_status": "sent",
            "item_count": 1,
            "stage_packet_ref_hashes": [_sha256(stage_packet["packet_ref"])],
            "safe_work_result_ref_hashes": [_sha256(safe_work_result["result_ref"])],
            "telegram_message_ids": ["3130"],
            "teable_sync": {
                "status": "synced",
                "sync_attempted": True,
                "projection_summary": {
                    "record_count": 3,
                    "tables": {
                        "proactive_ooda_runs": {"record_count": 1},
                        "proactive_ooda_items": {"record_count": 1},
                        "proactive_ooda_safe_work": {"record_count": 1},
                    },
                },
            },
        },
    )

    bundle = load_runtime_artifact_bundle(root=tmp_path, state_path=state_path)

    assert bundle["run_receipt_path"] == archive_receipt_path
    assert bundle["run_receipt"]["notification_status"] == "sent"
    assert bundle["stage_packet"]["packet_ref"] == "stage_packet:pkt-live"
    assert bundle["safe_work_result"]["result_ref"] == "safe_work_result:res-live"


def test_load_runtime_artifact_bundle_keeps_sent_packet_when_primary_is_newer_noop(tmp_path: Path) -> None:
    state_path = "state/proactive_ooda_notified.json"
    primary_receipt_path = tmp_path / "state" / "proactive_ooda_latest_run.generated.json"
    archive_receipt_path = tmp_path / "state" / "proactive_ooda_run_receipts" / "20260629T110000Z-sent-proof.json"
    delivered_deferred_receipt_path = (
        tmp_path / "state" / "proactive_ooda_run_receipts" / "20260629T110500Z-delivered-deferred.json"
    )
    stage_dir = tmp_path / "state" / "proactive_ooda_stage_packets"
    safe_dir = tmp_path / "state" / "proactive_ooda_safe_work_results"

    actionable_stage = {
        "schema": "proactive_ooda.stage_packet.v1",
        "packet_ref": "stage_packet:pkt-actionable",
        "stage": {"kind": "approval_packet"},
        "approval": {"required": True},
    }
    actionable_safe = {
        "schema": "proactive_ooda.safe_work_result.v1",
        "result_ref": "safe_work_result:res-actionable",
        "source_packet_ref_hash": _sha256(actionable_stage["packet_ref"]),
        "status": "staged_for_user_decision",
        "recommended_option_or_draft": {
            "kind": "shortlist_candidate",
            "value": {"label": "Vendor A", "url": "https://example.test/vendor-a"},
        },
        "approval": {"required": True},
        "execution_receipt": {
            "network_fetch_count": 1,
            "network_fetch_success_count": 1,
            "page_checks": [{"url": "https://example.test/vendor-a", "reachable": True}],
            "irreversible_actions_attempted": [],
        },
    }
    noop_stage = {
        "schema": "proactive_ooda.stage_packet.v1",
        "packet_ref": "stage_packet:pkt-noop",
        "stage": {"kind": "approval_packet"},
        "approval": {"required": False},
    }
    noop_safe = {
        "schema": "proactive_ooda.safe_work_result.v1",
        "result_ref": "safe_work_result:res-noop",
        "source_packet_ref_hash": _sha256(noop_stage["packet_ref"]),
        "status": "blocked_needs_research_input",
        "recommended_option_or_draft": {"kind": "", "value": ""},
        "approval": {"required": False},
        "execution_receipt": {
            "network_fetch_count": 0,
            "network_fetch_success_count": 0,
            "page_checks": [],
            "irreversible_actions_attempted": [],
        },
    }
    _write_json(stage_dir / "pkt-actionable.json", actionable_stage)
    _write_json(safe_dir / "res-actionable.json", actionable_safe)
    _write_json(stage_dir / "pkt-noop.json", noop_stage)
    _write_json(safe_dir / "res-noop.json", noop_safe)
    _write_json(
        archive_receipt_path,
        {
            "notification_status": "sent",
            "item_count": 1,
            "stage_packet_ref_hashes": [_sha256(actionable_stage["packet_ref"])],
            "safe_work_result_ref_hashes": [_sha256(actionable_safe["result_ref"])],
            "telegram_message_ids": ["3130"],
            "teable_sync": {"status": "synced", "sync_attempted": True},
        },
    )
    _write_json(
        primary_receipt_path,
        {
            "notification_status": "deferred",
            "error_code": "no_user_action_required",
            "item_count": 4,
            "stage_packet_output_dir": str(stage_dir),
            "safe_work_result_output_dir": str(safe_dir),
            "stage_packet_ref_hashes": [_sha256(noop_stage["packet_ref"])],
            "safe_work_result_ref_hashes": [_sha256(noop_safe["result_ref"])],
            "telegram_message_ids": [],
        },
    )
    _write_json(
        delivered_deferred_receipt_path,
        {
            "notification_status": "deferred",
            "error_code": "no_user_action_required",
            "item_count": 9,
            "stage_packet_output_dir": str(stage_dir),
            "safe_work_result_output_dir": str(safe_dir),
            "stage_packet_ref_hashes": [_sha256(noop_stage["packet_ref"])],
            "safe_work_result_ref_hashes": [_sha256(noop_safe["result_ref"])],
            "telegram_message_ids": [],
            "delivery_message_ids": ["delivered-message-1"],
        },
    )

    bundle = load_runtime_artifact_bundle(root=tmp_path, state_path=state_path)

    assert bundle["run_receipt_path"] == archive_receipt_path
    assert bundle["run_receipt"]["notification_status"] == "sent"
    assert bundle["action_required_only_quiet_receipt_path"] == primary_receipt_path
    assert bundle["action_required_only_quiet_receipt"]["error_code"] == "no_user_action_required"
    assert bundle["stage_packet"]["packet_ref"] == "stage_packet:pkt-actionable"
    assert bundle["safe_work_result"]["result_ref"] == "safe_work_result:res-actionable"


def test_load_runtime_artifact_bundle_hides_property_scout_packet_when_flat_search_disabled(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("EA_PROACTIVE_OODA_DISABLE_FLAT_SEARCH", "1")
    state_path = "state/proactive_ooda_notified.json"
    primary_receipt_path = tmp_path / "state" / "proactive_ooda_latest_run.generated.json"
    archive_receipt_path = tmp_path / "state" / "proactive_ooda_run_receipts" / "20260630T000522Z-sent-property.json"
    stage_dir = tmp_path / "state" / "proactive_ooda_stage_packets"
    safe_dir = tmp_path / "state" / "proactive_ooda_safe_work_results"

    property_stage = {
        "schema": "proactive_ooda.stage_packet.v1",
        "packet_ref": "stage_packet:pkt-property",
        "observe": "Property scout found no viable matches.",
        "decide": "Approve whether EA should stage one filter-review packet.",
        "stage": {
            "kind": "research_packet",
            "payload": {
                "research_query": "Review why the current property scout filters produced zero viable matches.",
            },
        },
        "approval": {"required": True},
    }
    property_safe = {
        "schema": "proactive_ooda.safe_work_result.v1",
        "result_ref": "safe_work_result:res-property",
        "source_packet_ref_hash": _sha256(property_stage["packet_ref"]),
        "status": "staged_for_user_decision",
        "summary": "One property scout filter-review packet.",
        "recommended_option_or_draft": {
            "kind": "shortlist_candidate",
            "value": {"label": "IMMMO Wien rentals", "url": "https://www.immmo.at/immo/Wohnung-mieten/Wien"},
        },
        "approval": {"required": True},
        "execution_receipt": {
            "network_fetch_count": 1,
            "network_fetch_success_count": 1,
            "page_checks": [{"url": "https://www.immmo.at/immo/Wohnung-mieten/Wien", "reachable": True}],
            "irreversible_actions_attempted": [],
        },
    }
    _write_json(stage_dir / "pkt-property.json", property_stage)
    _write_json(safe_dir / "res-property.json", property_safe)
    _write_json(
        primary_receipt_path,
        {
            "notification_status": "skipped_no_items",
            "item_count": 0,
            "stage_packet_output_dir": str(stage_dir),
            "safe_work_result_output_dir": str(safe_dir),
            "stage_packet_ref_hashes": [],
            "safe_work_result_ref_hashes": [],
            "telegram_message_ids": [],
        },
    )
    _write_json(
        archive_receipt_path,
        {
            "notification_status": "sent",
            "item_count": 1,
            "stage_packet_ref_hashes": [_sha256(property_stage["packet_ref"])],
            "safe_work_result_ref_hashes": [_sha256(property_safe["result_ref"])],
            "telegram_message_ids": ["3379"],
            "teable_sync": {"status": "synced", "sync_attempted": True},
        },
    )

    bundle = load_runtime_artifact_bundle(root=tmp_path, state_path=state_path)

    assert bundle["run_receipt_path"] == primary_receipt_path
    assert bundle["stage_packet_path"] is None
    assert bundle["stage_packet"] == {}
    assert bundle["safe_work_result_path"] is None
    assert bundle["safe_work_result"] == {}
    assert bundle["artifact_filter_reason"] == "flat_search_disabled_property_scout"
    assert bundle["flat_search_enabled"] is False
    assert bundle["current_packet_callback_record_count"] == 0


def test_load_runtime_artifact_bundle_prefers_primary_run_linked_artifacts_over_newer_unrelated_pair(tmp_path: Path) -> None:
    state_path = "state/proactive_ooda_notified.json"
    primary_receipt_path = tmp_path / "state" / "proactive_ooda_latest_run.generated.json"
    stage_dir = tmp_path / "state" / "proactive_ooda_stage_packets"
    safe_dir = tmp_path / "state" / "proactive_ooda_safe_work_results"

    matching_stage = {
        "schema": "proactive_ooda.stage_packet.v1",
        "packet_ref": "stage_packet:pkt-matching",
        "stage": {"kind": "approval_packet"},
        "approval": {"required": True},
    }
    matching_safe = {
        "schema": "proactive_ooda.safe_work_result.v1",
        "result_ref": "safe_work_result:res-matching",
        "source_packet_ref_hash": _sha256(matching_stage["packet_ref"]),
        "status": "staged_for_user_decision",
        "recommended_option_or_draft": {
            "kind": "shortlist_candidate",
            "value": {"label": "Vendor A", "url": "https://example.test/vendor-a"},
        },
        "approval": {"required": True},
        "execution_receipt": {
            "network_fetch_count": 1,
            "network_fetch_success_count": 1,
            "page_checks": [{"url": "https://example.test/vendor-a", "reachable": True}],
            "irreversible_actions_attempted": [],
        },
    }
    unrelated_stage = {
        "schema": "proactive_ooda.stage_packet.v1",
        "packet_ref": "stage_packet:pkt-unrelated",
        "stage": {"kind": "approval_packet"},
        "approval": {"required": True},
    }
    unrelated_safe = {
        "schema": "proactive_ooda.safe_work_result.v1",
        "result_ref": "safe_work_result:res-unrelated",
        "source_packet_ref_hash": _sha256(unrelated_stage["packet_ref"]),
        "status": "staged_for_user_decision",
        "recommended_option_or_draft": {
            "kind": "shortlist_candidate",
            "value": {"label": "Vendor B", "url": "https://example.test/vendor-b"},
        },
        "approval": {"required": True},
        "execution_receipt": {
            "network_fetch_count": 1,
            "network_fetch_success_count": 1,
            "page_checks": [{"url": "https://example.test/vendor-b", "reachable": True}],
            "irreversible_actions_attempted": [],
        },
    }
    _write_json(stage_dir / "pkt-matching.json", matching_stage)
    _write_json(safe_dir / "res-matching.json", matching_safe)
    _write_json(stage_dir / "pkt-unrelated.json", unrelated_stage)
    _write_json(safe_dir / "res-unrelated.json", unrelated_safe)
    _write_json(
        primary_receipt_path,
        {
            "notification_status": "sent",
            "item_count": 1,
            "stage_packet_output_dir": str(stage_dir),
            "safe_work_result_output_dir": str(safe_dir),
            "stage_packet_ref_hashes": [_sha256(matching_stage["packet_ref"])],
            "safe_work_result_ref_hashes": [_sha256(matching_safe["result_ref"])],
            "telegram_message_ids": ["3131"],
        },
    )

    bundle = load_runtime_artifact_bundle(root=tmp_path, state_path=state_path)

    assert bundle["run_receipt_path"] == primary_receipt_path
    assert bundle["stage_packet"]["packet_ref"] == "stage_packet:pkt-matching"
    assert bundle["safe_work_result"]["result_ref"] == "safe_work_result:res-matching"


def test_load_runtime_artifact_bundle_includes_current_packet_approval_callback_stats(tmp_path: Path) -> None:
    state_path = "state/proactive_ooda_notified.json"
    receipt_path = tmp_path / "state" / "proactive_ooda_latest_run.generated.json"
    stage_dir = tmp_path / "state" / "proactive_ooda_stage_packets"
    safe_dir = tmp_path / "state" / "proactive_ooda_safe_work_results"
    callback_dir = tmp_path / "state" / "proactive_ooda_approval_callbacks"

    stage_packet = {
        "schema": "proactive_ooda.stage_packet.v1",
        "packet_ref": "stage_packet:pkt-live",
        "stage": {"kind": "approval_packet"},
        "approval": {"required": True},
    }
    safe_work_result = {
        "schema": "proactive_ooda.safe_work_result.v1",
        "result_ref": "safe_work_result:res-live",
        "source_packet_ref_hash": _sha256(stage_packet["packet_ref"]),
        "status": "staged_for_user_decision",
        "recommended_option_or_draft": {
            "kind": "shortlist_candidate",
            "value": {"label": "Vendor A", "url": "https://example.test/vendor-a"},
        },
        "approval": {"required": True},
        "execution_receipt": {
            "network_fetch_count": 1,
            "network_fetch_success_count": 1,
            "page_checks": [{"url": "https://example.test/vendor-a", "reachable": True}],
            "irreversible_actions_attempted": [],
        },
    }
    _write_json(stage_dir / "pkt-live.json", stage_packet)
    _write_json(safe_dir / "res-live.json", safe_work_result)
    _write_json(
        receipt_path,
        {
            "notification_status": "deferred",
            "item_count": 1,
            "stage_packet_ref_hashes": [_sha256(stage_packet["packet_ref"])],
            "safe_work_result_ref_hashes": [_sha256(safe_work_result["result_ref"])],
            "stage_packet_output_dir": str(stage_dir),
            "safe_work_result_output_dir": str(safe_dir),
        },
    )
    _write_json(
        callback_dir / "pending.json",
        {
            "schema": "ea.proactive_ooda_telegram_approval_callback.v1",
            "callback_token": "cb-1",
            "status": "pending",
            "created_at": "2026-06-28T14:00:00Z",
            "expires_at": "2099-01-01T00:00:00Z",
            "packet_ref": "stage_packet:pkt-live",
            "staged_artifact_ref": "safe_work_result:res-live",
        },
    )
    _write_json(
        callback_dir / "expired-current.json",
        {
            "schema": "ea.proactive_ooda_telegram_approval_callback.v1",
            "callback_token": "cb-expired-current",
            "status": "pending",
            "created_at": "2026-06-28T13:30:00Z",
            "expires_at": "2000-01-01T00:00:00Z",
            "packet_ref": "stage_packet:pkt-live",
            "staged_artifact_ref": "safe_work_result:res-live",
        },
    )
    _write_json(
        callback_dir / "other.json",
        {
            "schema": "ea.proactive_ooda_telegram_approval_callback.v1",
            "callback_token": "cb-2",
            "status": "approved",
            "created_at": "2026-06-28T13:00:00Z",
            "expires_at": "2099-01-01T00:00:00Z",
            "packet_ref": "stage_packet:other",
            "staged_artifact_ref": "safe_work_result:other",
        },
    )
    _write_json(
        callback_dir / "other-pending.json",
        {
            "schema": "ea.proactive_ooda_telegram_approval_callback.v1",
            "callback_token": "cb-3",
            "status": "pending",
            "created_at": "2026-06-28T12:30:00Z",
            "expires_at": "2099-01-01T00:00:00Z",
            "packet_ref": "stage_packet:other-pending",
            "staged_artifact_ref": "safe_work_result:other-pending",
        },
    )

    bundle = load_runtime_artifact_bundle(root=tmp_path, state_path=state_path)

    assert bundle["approval_callback_dir"] == callback_dir
    assert bundle["approval_callback_dir_exists"] is True
    assert bundle["approval_callback_dir_writable"] is True
    assert bundle["approval_callback_record_count"] == 4
    assert bundle["approval_callback_pending_count"] == 1
    assert bundle["approval_callback_raw_pending_count"] == 3
    assert bundle["approval_callback_live_pending_count"] == 1
    assert bundle["approval_callback_unexpired_pending_count"] == 2
    assert bundle["approval_callback_noncurrent_pending_count"] == 1
    assert bundle["approval_callback_expired_pending_count"] == 1
    assert bundle["approval_callback_stale_pending_count"] == 2
    assert bundle["current_packet_callback_record_count"] == 2
    assert bundle["current_packet_callback_pending_count"] == 2
    assert bundle["current_packet_callback_raw_pending_count"] == 2
    assert bundle["current_packet_callback_expired_pending_count"] == 1
    assert bundle["current_packet_callback_stale_pending_count"] == 1
    assert bundle["current_packet_live_pending_count"] == 1
    assert bundle["current_packet_callback_latest_status"] == "pending"
    assert bundle["current_packet_callback_latest_expired"] is False
    assert bundle["current_packet_callback_latest_created_at"] == "2026-06-28T14:00:00Z"
    assert bundle["current_packet_callback_latest_expires_at"] == "2099-01-01T00:00:00Z"
    assert isinstance(bundle["current_packet_callback_latest_age_seconds"], int)
    assert bundle["current_packet_callback_latest_seconds_until_expiry"] > 0


def test_select_current_approval_outcome_ignores_stale_saved_artifact() -> None:
    stage_packet = {"packet_ref": "stage_packet:current"}
    safe_work_result = {"result_ref": "safe_work_result:current"}

    selected = select_current_approval_outcome_for_bundle(
        {
            "stage_packet": stage_packet,
            "safe_work_result": safe_work_result,
            "approval_outcome": {
                "approval_outcome_recorded": True,
                "status": "accepted_redacted",
                "outcome": "approved",
                "packet_ref_sha256": _sha256("stage_packet:old"),
                "staged_artifact_sha256": _sha256("safe_work_result:old"),
            },
        }
    )

    assert selected["approval_outcome"] == {}
    assert selected["source"] == ""
    assert selected["stale_saved_approval_outcome_present"] is True


def test_select_current_approval_outcome_prefers_current_callback_over_saved_artifact() -> None:
    stage_packet = {"packet_ref": "stage_packet:current"}
    safe_work_result = {"result_ref": "safe_work_result:current"}

    selected = select_current_approval_outcome_for_bundle(
        {
            "stage_packet": stage_packet,
            "safe_work_result": safe_work_result,
            "current_packet_callback_outcome": {
                "approval_outcome_recorded": True,
                "status": "recorded_not_accepted",
                "outcome": "deferred",
                "packet_ref_sha256": _sha256("stage_packet:current"),
                "staged_artifact_sha256": _sha256("safe_work_result:current"),
            },
            "approval_outcome": {
                "approval_outcome_recorded": True,
                "status": "accepted_redacted",
                "outcome": "approved",
                "packet_ref_sha256": _sha256("stage_packet:current"),
                "staged_artifact_sha256": _sha256("safe_work_result:current"),
            },
        }
    )

    assert selected["source"] == "current_packet_callback"
    assert selected["approval_outcome"]["outcome"] == "deferred"
    assert selected["stale_saved_approval_outcome_present"] is False
