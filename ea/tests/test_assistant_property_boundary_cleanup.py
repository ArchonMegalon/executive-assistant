from __future__ import annotations

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
