from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.services.assistant_property_boundary_cleanup import cleanup_hidden_property_runtime_state


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_cleanup_hidden_property_runtime_state_archives_only_property_artifacts(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    stage_dir = root / "state" / "proactive_ooda_stage_packets"
    safe_dir = root / "state" / "proactive_ooda_safe_work_results"
    callback_dir = root / "state" / "proactive_ooda_approval_callbacks"

    property_stage = stage_dir / "property-stage.json"
    property_safe = safe_dir / "property-safe.json"
    property_callback = callback_dir / "property-callback.json"
    normal_stage = stage_dir / "normal-stage.json"
    normal_safe = safe_dir / "normal-safe.json"
    normal_callback = callback_dir / "normal-callback.json"

    _write_json(
        property_stage,
        {
            "packet_ref": "stage_packet:property-stage",
            "stage": {"payload": {"research_query": "Compare the two best property candidates."}},
        },
    )
    _write_json(
        property_safe,
        {
            "result_ref": "safe_work_result:property-safe",
            "recommended_option_or_draft": {"value": "Compare the two best property candidates."},
        },
    )
    _write_json(
        property_callback,
        {
            "packet_ref": "stage_packet:property-stage",
            "staged_artifact_ref": "safe_work_result:property-safe",
            "status": "pending",
        },
    )
    _write_json(
        normal_stage,
        {
            "packet_ref": "stage_packet:normal-stage",
            "stage": {"payload": {"research_query": "Find an electrician in Vienna."}},
        },
    )
    _write_json(
        normal_safe,
        {
            "result_ref": "safe_work_result:normal-safe",
            "recommended_option_or_draft": {"value": "Find an electrician in Vienna."},
        },
    )
    _write_json(
        normal_callback,
        {
            "packet_ref": "stage_packet:normal-stage",
            "staged_artifact_ref": "safe_work_result:normal-safe",
            "status": "pending",
        },
    )

    result = cleanup_hidden_property_runtime_state(
        root_candidates=(root,),
        archive_label="test-archive",
    )

    archive_root = root / "state" / "assistant_property_boundary_archive" / "test-archive"
    assert result["archived_total"] == 3
    assert result["stage_packet_total"] == 1
    assert result["safe_work_result_total"] == 1
    assert result["approval_callback_total"] == 1
    assert (archive_root / "stage_packets" / property_stage.name).exists()
    assert (archive_root / "safe_work_results" / property_safe.name).exists()
    assert (archive_root / "approval_callbacks" / property_callback.name).exists()
    assert not property_stage.exists()
    assert not property_safe.exists()
    assert not property_callback.exists()
    assert normal_stage.exists()
    assert normal_safe.exists()
    assert normal_callback.exists()


def test_cleanup_hidden_property_runtime_state_keeps_google_oauth_action_with_propertyquarry_project(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    stage_dir = root / "state" / "proactive_ooda_stage_packets"
    safe_dir = root / "state" / "proactive_ooda_safe_work_results"
    callback_dir = root / "state" / "proactive_ooda_approval_callbacks"

    stage = stage_dir / "google-oauth-stage.json"
    safe = safe_dir / "google-oauth-safe.json"
    callback = callback_dir / "google-oauth-callback.json"

    _write_json(
        stage,
        {
            "packet_ref": "stage_packet:google-oauth",
            "stage": {
                "payload": {
                    "kind": "internal_action",
                    "work_type": "record_internal_action",
                    "summary": "Action needed: Google Workspace OAuth test-user setup.",
                    "links": [
                        "https://myexternalbrain.com/integrations/google",
                        "https://console.cloud.google.com/auth/audience?project=propertyquarry-498318",
                    ],
                }
            },
            "safe_work_order": {
                "quality_gate": {
                    "fail_closed_if": [
                        "flat_search_blocked",
                        "privacy_or_secret_leak",
                    ],
                },
            },
        },
    )
    _write_json(
        safe,
        {
            "result_ref": "safe_work_result:google-oauth",
            "work_type": "record_internal_action",
            "recommended_option_or_draft": {
                "kind": "internal_action",
                "value": {
                    "label": "Retry Google auth",
                    "url": "https://myexternalbrain.com/integrations/google",
                },
            },
            "execution_receipt": {
                "research_search_plan": {
                    "flat_search_allowed": False,
                    "flat_search_blockers": [],
                    "mode": "internal_action",
                },
            },
            "quality_gate": {
                "accepted_stop_conditions": ["quality_gate_failed"],
                "fail_closed_if": ["flat_search_blocked"],
            },
        },
    )
    _write_json(
        callback,
        {
            "packet_ref": "stage_packet:google-oauth",
            "staged_artifact_ref": "safe_work_result:google-oauth",
            "status": "pending",
        },
    )

    result = cleanup_hidden_property_runtime_state(
        root_candidates=(root,),
        archive_label="test-archive",
    )

    assert result["archived_total"] == 0
    assert stage.exists()
    assert safe.exists()
    assert callback.exists()


def test_cleanup_hidden_property_runtime_state_uses_live_artifact_root_for_absolute_state_path(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    artifact_root = tmp_path / "provider-ledger"
    stage_dir = artifact_root / "proactive_ooda_stage_packets"
    safe_dir = artifact_root / "proactive_ooda_safe_work_results"
    callback_dir = artifact_root / "proactive_ooda_approval_callbacks"
    state_path = artifact_root / "proactive_ooda_notified.json"

    property_stage = stage_dir / "property-stage.json"
    property_safe = safe_dir / "property-safe.json"
    property_callback = callback_dir / "property-callback.json"

    _write_json(
        property_stage,
        {
            "packet_ref": "stage_packet:property-stage",
            "stage": {"payload": {"research_query": "Compare the two best property candidates."}},
        },
    )
    _write_json(
        property_safe,
        {
            "result_ref": "safe_work_result:property-safe",
            "recommended_option_or_draft": {"value": "Compare the two best property candidates."},
        },
    )
    _write_json(
        property_callback,
        {
            "packet_ref": "stage_packet:property-stage",
            "staged_artifact_ref": "safe_work_result:property-safe",
            "status": "pending",
        },
    )

    result = cleanup_hidden_property_runtime_state(
        root_candidates=(repo_root,),
        state_path=state_path,
        archive_label="provider-ledger-archive",
    )

    archive_root = artifact_root / "assistant_property_boundary_archive" / "provider-ledger-archive"
    assert result["archived_total"] == 3
    assert (archive_root / "stage_packets" / property_stage.name).exists()
    assert (archive_root / "safe_work_results" / property_safe.name).exists()
    assert (archive_root / "approval_callbacks" / property_callback.name).exists()
    assert not property_stage.exists()
    assert not property_safe.exists()
    assert not property_callback.exists()


def test_cleanup_hidden_property_runtime_state_archives_callbacks_referencing_existing_property_archive(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    state_dir = root / "state"
    callback_dir = state_dir / "proactive_ooda_approval_callbacks"
    prior_archive = state_dir / "assistant_property_boundary_archive" / "prior"

    archived_stage = prior_archive / "stage_packets" / "opaque-stage.json"
    archived_safe = prior_archive / "safe_work_results" / "opaque-safe.json"
    live_callback = callback_dir / "live-callback.json"
    unrelated_callback = callback_dir / "unrelated-callback.json"

    _write_json(
        archived_stage,
        {
            "packet_ref": "stage_packet:opaque-property-ref",
            "stage": {"payload": {"research_query": "Compare apartment candidates."}},
        },
    )
    _write_json(
        archived_safe,
        {
            "result_ref": "safe_work_result:opaque-property-ref",
            "recommended_option_or_draft": {"value": "Property search shortlist."},
        },
    )
    _write_json(
        live_callback,
        {
            "packet_ref": "stage_packet:opaque-property-ref",
            "staged_artifact_ref": "safe_work_result:opaque-property-ref",
            "status": "pending",
        },
    )
    _write_json(
        unrelated_callback,
        {
            "packet_ref": "stage_packet:normal-ref",
            "staged_artifact_ref": "safe_work_result:normal-ref",
            "status": "pending",
        },
    )

    result = cleanup_hidden_property_runtime_state(
        root_candidates=(root,),
        archive_label="current",
    )

    current_archive = state_dir / "assistant_property_boundary_archive" / "current"
    assert result["archived_total"] == 1
    assert result["approval_callback_total"] == 1
    assert (current_archive / "approval_callbacks" / live_callback.name).exists()
    assert not live_callback.exists()
    assert unrelated_callback.exists()


def test_cleanup_hidden_property_runtime_state_archives_run_receipts_referencing_hidden_property_artifacts(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    state_dir = root / "state"
    stage_dir = state_dir / "proactive_ooda_stage_packets"
    safe_dir = state_dir / "proactive_ooda_safe_work_results"
    run_dir = state_dir / "proactive_ooda_run_receipts"
    current_receipt = state_dir / "proactive_ooda_latest_run.generated.json"
    archived_receipt = run_dir / "20260705T100000Z-property.json"
    unrelated_receipt = run_dir / "20260705T101500Z-normal.json"

    property_stage_ref = "stage_packet:property-stage"
    property_safe_ref = "safe_work_result:property-safe"
    property_stage_hash = hashlib.sha256(property_stage_ref.encode("utf-8")).hexdigest()
    property_safe_hash = hashlib.sha256(property_safe_ref.encode("utf-8")).hexdigest()

    _write_json(
        stage_dir / "property-stage.json",
        {
            "packet_ref": property_stage_ref,
            "stage": {"payload": {"research_query": "Compare apartment candidates."}},
        },
    )
    _write_json(
        safe_dir / "property-safe.json",
        {
            "result_ref": property_safe_ref,
            "recommended_option_or_draft": {"value": "Apartment shortlist."},
        },
    )
    _write_json(
        current_receipt,
        {
            "notification_status": "deferred",
            "error_code": "no_user_action_required",
            "stage_packet_ref_hashes": [property_stage_hash],
            "safe_work_result_ref_hashes": [property_safe_hash],
        },
    )
    _write_json(
        archived_receipt,
        {
            "notification_status": "failed",
            "stage_packet_ref_hashes": [property_stage_hash],
            "safe_work_result_ref_hashes": [property_safe_hash],
        },
    )
    _write_json(
        unrelated_receipt,
        {
            "notification_status": "sent",
            "stage_packet_ref_hashes": [hashlib.sha256(b"stage_packet:normal").hexdigest()],
            "safe_work_result_ref_hashes": [hashlib.sha256(b"safe_work_result:normal").hexdigest()],
        },
    )

    result = cleanup_hidden_property_runtime_state(
        root_candidates=(root,),
        archive_label="receipt-archive",
    )

    archive_root = state_dir / "assistant_property_boundary_archive" / "receipt-archive"
    assert result["run_receipt_total"] == 2
    assert result["archived_total"] == 4
    assert (archive_root / "run_receipts" / current_receipt.name).exists()
    assert (archive_root / "run_receipts" / archived_receipt.name).exists()
    assert not current_receipt.exists()
    assert not archived_receipt.exists()
    assert unrelated_receipt.exists()
