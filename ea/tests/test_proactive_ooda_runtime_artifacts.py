from __future__ import annotations

import json
from pathlib import Path

from app.services import proactive_ooda_runtime_artifacts, proactive_ooda_teable_sync


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


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
