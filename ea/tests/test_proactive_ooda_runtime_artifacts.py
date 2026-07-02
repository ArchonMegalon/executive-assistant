from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from app.services import proactive_ooda_runtime_artifacts, proactive_ooda_teable_sync


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _stage_packet(packet_ref: str) -> dict[str, object]:
    return {
        "schema": proactive_ooda_runtime_artifacts.STAGE_PACKET_SCHEMA,
        "packet_ref": packet_ref,
        "generated_at": "2026-07-01T08:00:00+00:00",
        "stage": {"kind": "approval_packet", "summary": "Stage one reversible next step."},
        "approval": {"required": True},
    }


def _safe_work_result(
    result_ref: str,
    *,
    network_fetch_success_count: int,
    recommended_label: str,
) -> dict[str, object]:
    page_checks = (
        [{"url": "https://example.com/vendor", "reachable": True}]
        if network_fetch_success_count > 0
        else []
    )
    return {
        "schema": proactive_ooda_runtime_artifacts.SAFE_WORK_RESULT_SCHEMA,
        "result_ref": result_ref,
        "generated_at": "2026-07-01T08:00:01+00:00",
        "status": "staged_for_user_decision",
        "work_type": "prepare_shortlist",
        "summary": "Stage one reversible next step.",
        "recommended_option_or_draft": {
            "kind": "shortlist_candidate",
            "value": {
                "label": recommended_label,
                "url": "https://example.com/vendor",
            },
        },
        "execution_receipt": {
            "network_fetch_count": network_fetch_success_count,
            "network_fetch_success_count": network_fetch_success_count,
            "page_checks": page_checks,
        },
        "approval": {"required": True},
        "audit": {"status": "pass", "issues": []},
    }


def _sent_run_receipt(
    *,
    stage_packet: dict[str, object],
    safe_work_result: dict[str, object],
    stage_dir: Path,
    safe_dir: Path,
) -> dict[str, object]:
    return {
        "notification_status": "sent",
        "item_count": 1,
        "delivery_message_ids": ["123"],
        "stage_packet_output_dir": stage_dir.as_posix(),
        "safe_work_result_output_dir": safe_dir.as_posix(),
        "stage_packet_ref_hashes": [_sha256(str(stage_packet["packet_ref"]))],
        "safe_work_result_ref_hashes": [_sha256(str(safe_work_result["result_ref"]))],
        "teable_sync": {"status": "synced"},
    }


def _property_candidate_stage_packet() -> dict[str, object]:
    return {
        "schema": proactive_ooda_runtime_artifacts.STAGE_PACKET_SCHEMA,
        "packet_ref": "stage_packet:property-candidates",
        "generated_at": "2026-07-01T08:00:00+00:00",
        "stage": {
            "kind": "research_packet",
            "summary": "Research a shortlist and stage one reversible option for review.",
            "payload": {
                "research_query": "Compare the two best property candidates.",
            },
        },
    }


def _property_candidate_safe_work_result() -> dict[str, object]:
    return {
        "schema": proactive_ooda_runtime_artifacts.SAFE_WORK_RESULT_SCHEMA,
        "result_ref": "safe_work_result:property-candidates",
        "generated_at": "2026-07-01T08:00:01+00:00",
        "status": "staged_for_user_decision",
        "work_type": "compare_options",
        "summary": "Research a shortlist and stage one reversible option for review.",
        "recommended_option_or_draft": {
            "kind": "research_query",
            "value": "Compare the two best property candidates.",
        },
        "audit": {"status": "pass", "issues": []},
    }


def test_disabled_flat_search_filters_current_runtime_property_candidate_artifact(
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EA_PROACTIVE_OODA_DISABLE_FLAT_SEARCH", "1")
    monkeypatch.setenv("EA_PROACTIVE_OODA_FLAT_SEARCH_ENABLED", "1")
    stage_dir = tmp_path / "stage"
    safe_dir = tmp_path / "safe"
    _write_json(stage_dir / "stage.json", _property_candidate_stage_packet())
    _write_json(safe_dir / "safe.json", _property_candidate_safe_work_result())

    bundle = proactive_ooda_runtime_artifacts.load_runtime_artifact_bundle(
        root=tmp_path,
        state_path="state/proactive_ooda_notified.json",
        stage_packet_dir=stage_dir,
        safe_work_result_dir=safe_dir,
    )

    assert bundle["flat_search_enabled"] is False
    assert bundle["artifact_filter_reason"] == "flat_search_disabled_property_scout"
    assert bundle["stage_packet"] == {}
    assert bundle["safe_work_result"] == {}


def test_disabled_flat_search_safe_work_is_not_teable_projectable(monkeypatch: object) -> None:
    monkeypatch.setenv("EA_PROACTIVE_OODA_DISABLE_FLAT_SEARCH", "1")
    monkeypatch.setenv("EA_PROACTIVE_OODA_FLAT_SEARCH_ENABLED", "1")
    safe_work = _property_candidate_safe_work_result()

    assert proactive_ooda_teable_sync._safe_work_result_is_projectable(safe_work) is False
    assert proactive_ooda_teable_sync._safe_work_projection_suppression_reason(safe_work) == "flat_search_disabled"


def test_runtime_artifacts_prefer_delivered_browse_backed_receipt_over_newer_internal_action(
    tmp_path: Path,
) -> None:
    stage_dir = tmp_path / "stage"
    safe_dir = tmp_path / "safe"
    run_dir = tmp_path / "state" / proactive_ooda_runtime_artifacts.RUN_RECEIPT_DIRNAME

    browse_stage = _stage_packet("stage_packet:browse")
    browse_safe = _safe_work_result(
        "safe_work_result:browse",
        network_fetch_success_count=1,
        recommended_label="Verified vendor",
    )
    internal_stage = _stage_packet("stage_packet:internal")
    internal_safe = _safe_work_result(
        "safe_work_result:internal",
        network_fetch_success_count=0,
        recommended_label="Record internal action",
    )
    browse_safe["source_packet_ref_hash"] = _sha256(str(browse_stage["packet_ref"]))
    internal_safe["source_packet_ref_hash"] = _sha256(str(internal_stage["packet_ref"]))
    _write_json(stage_dir / "browse.json", browse_stage)
    _write_json(safe_dir / "browse.json", browse_safe)
    _write_json(stage_dir / "internal.json", internal_stage)
    _write_json(safe_dir / "internal.json", internal_safe)

    browse_receipt = run_dir / "20260702T094856_000000_0000-sent-browse.json"
    internal_receipt = run_dir / "20260702T105239_000000_0000-sent-internal.json"
    _write_json(
        browse_receipt,
        _sent_run_receipt(
            stage_packet=browse_stage,
            safe_work_result=browse_safe,
            stage_dir=stage_dir,
            safe_dir=safe_dir,
        ),
    )
    _write_json(
        internal_receipt,
        _sent_run_receipt(
            stage_packet=internal_stage,
            safe_work_result=internal_safe,
            stage_dir=stage_dir,
            safe_dir=safe_dir,
        ),
    )
    os.utime(browse_receipt, (1000, 1000))
    os.utime(internal_receipt, (2000, 2000))

    current_bundle = proactive_ooda_runtime_artifacts.load_runtime_artifact_bundle(
        root=tmp_path,
        state_path="state/proactive_ooda_notified.json",
        stage_packet_dir=stage_dir,
        safe_work_result_dir=safe_dir,
    )
    proof_bundle = proactive_ooda_runtime_artifacts.load_runtime_artifact_bundle(
        root=tmp_path,
        state_path="state/proactive_ooda_notified.json",
        stage_packet_dir=stage_dir,
        safe_work_result_dir=safe_dir,
        prefer_browse_backed_delivery=True,
    )

    assert current_bundle["run_receipt_path"] == internal_receipt
    assert current_bundle["stage_packet"]["packet_ref"] == "stage_packet:internal"
    assert current_bundle["safe_work_result"]["result_ref"] == "safe_work_result:internal"
    assert proof_bundle["run_receipt_path"] == browse_receipt
    assert proof_bundle["stage_packet"]["packet_ref"] == "stage_packet:browse"
    assert proof_bundle["safe_work_result"]["result_ref"] == "safe_work_result:browse"
    execution = proof_bundle["safe_work_result"]["execution_receipt"]
    assert execution["network_fetch_success_count"] == 1
