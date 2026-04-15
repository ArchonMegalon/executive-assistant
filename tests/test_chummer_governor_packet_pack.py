from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
PACK_PATH = ROOT / "docs" / "chummer_governor_packets" / "CHUMMER_GOVERNOR_PACKET_PACK.yaml"
CANONICAL_REGISTRY_PATH = Path("/docker/chummercomplete/chummer-design/products/chummer/NEXT_90_DAY_PRODUCT_ADVANCE_REGISTRY.yaml")
QUEUE_STAGING_PATH = Path("/docker/fleet/.codex-studio/published/NEXT_90_DAY_QUEUE_STAGING.generated.yaml")
PROGRESS_EMAIL_WORKFLOW_PATH = ROOT / ".codex-design" / "product" / "FEEDBACK_PROGRESS_EMAIL_WORKFLOW.yaml"
FEEDBACK_RELEASE_GATE_PATH = ROOT / ".codex-design" / "product" / "FEEDBACK_LOOP_RELEASE_GATE.yaml"


def _yaml(path: Path) -> dict:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return payload if isinstance(payload, dict) else {}


def _source_path(row: dict) -> Path:
    raw_path = Path(str(row.get("path") or ""))
    return raw_path if raw_path.is_absolute() else ROOT / raw_path


def _find_package(queue: dict) -> dict:
    for item in queue.get("items") or []:
        if dict(item).get("package_id") == "next90-m106-ea-governor-packets":
            return dict(item)
    raise AssertionError("missing next90-m106-ea-governor-packets in successor queue")


def _find_milestone(registry: dict, milestone_id: int) -> dict:
    for item in registry.get("milestones") or []:
        row = dict(item)
        if int(row.get("id") or 0) == milestone_id:
            return row
    raise AssertionError(f"missing milestone {milestone_id}")


def test_pack_contract_tracks_successor_package_and_owned_surfaces() -> None:
    pack = _yaml(PACK_PATH)
    queue_item = _find_package(_yaml(QUEUE_STAGING_PATH))

    assert pack.get("contract_name") == "ea.chummer_governor_packet_pack"
    assert pack.get("package_id") == "next90-m106-ea-governor-packets"
    assert int(pack.get("milestone_id") or 0) == 106
    assert pack.get("wave") == "W8"
    assert list(pack.get("owned_surfaces") or []) == [
        "operator_packets:weekly_governor",
        "reporter_followthrough:release_truth",
    ]
    assert queue_item.get("repo") == "executive-assistant"
    assert list(queue_item.get("allowed_paths") or []) == ["skills", "tests", "feedback", "docs"]
    assert list(queue_item.get("owned_surfaces") or []) == list(pack.get("owned_surfaces") or [])


def test_canonical_registry_still_assigns_milestone_106_ea_synthesis_work() -> None:
    registry = _yaml(CANONICAL_REGISTRY_PATH)
    milestone = _find_milestone(registry, 106)

    assert milestone.get("status") == "in_progress"
    assert "executive-assistant" in set(milestone.get("owners") or [])
    assert {int(item) for item in milestone.get("dependencies") or []} == {101, 102, 103, 104, 105}
    assert any(
        dict(task).get("owner") == "executive-assistant"
        and dict(task).get("id") == 106.2
        and "Synthesize support, parity, and release signals" in str(dict(task).get("title") or "")
        for task in milestone.get("work_tasks") or []
    )


def test_pack_source_truth_files_exist_and_share_evidence_anchors() -> None:
    pack = _yaml(PACK_PATH)
    source_truth = {str(key): dict(value) for key, value in dict(pack.get("source_truth") or {}).items()}
    shared_anchors = set(pack.get("shared_evidence_anchor_ids") or [])

    assert shared_anchors == {"weekly_pulse", "parity_lab_pack", "feedback_release_gate", "progress_email_workflow"}
    for key, row in source_truth.items():
        if row.get("required") is True:
            assert _source_path(row).exists(), key

    assert set(pack["operator_packet"]["evidence_anchor_ids"]) == shared_anchors
    assert set(pack["reporter_followthrough"]["evidence_anchor_ids"]) == shared_anchors


def test_operator_packet_can_explain_all_governor_postures_without_claiming_authority() -> None:
    pack = _yaml(PACK_PATH)
    operator_packet = dict(pack.get("operator_packet") or {})
    boundary = dict(pack.get("boundary_fit") or {})

    assert set(operator_packet.get("decision_postures") or []) == {
        "launch",
        "freeze",
        "canary",
        "rollback",
        "focus_shift",
    }
    assert {"recommended_decision", "exit_condition", "downstream_action"} <= set(operator_packet.get("minimum_fields") or [])
    assert boundary.get("ea_is_release_authority") is False
    assert boundary.get("ea_is_support_case_database") is False
    assert boundary.get("ea_is_canonical_product_truth") is False
    assert "Fleet and design remain the decision and canon authorities" in str(operator_packet.get("output_rule") or "")


def test_operator_posture_gates_fail_closed_before_launch_or_rollout_claims() -> None:
    pack = _yaml(PACK_PATH)
    operator_packet = dict(pack.get("operator_packet") or {})
    posture_gates = {str(key): dict(value) for key, value in dict(operator_packet.get("posture_gates") or {}).items()}

    assert set(posture_gates) == set(operator_packet.get("decision_postures") or [])
    launch_gate = posture_gates["launch"]
    assert launch_gate["required_states"]["release_health_state"] == ["ready"]
    assert launch_gate["required_states"]["flagship_readiness_state"] == ["ready"]
    assert launch_gate["required_states"]["journey_gate_state"] == ["ready"]
    assert launch_gate["required_states"]["support_closure_state"] == ["clear"]
    assert any("reporter followthrough gate" in item for item in launch_gate["required_receipts"])

    canary_gate = posture_gates["canary"]
    assert "bounded rollout cohort" in canary_gate["required_receipts"]
    assert "cited rollback trigger" in canary_gate["required_receipts"]
    assert "successor milestone or risk cluster" in posture_gates["focus_shift"]["required_receipts"]
    for gate in posture_gates.values():
        assert str(gate.get("fail_closed_reason") or "").strip()


def test_reporter_followthrough_matches_progress_mail_and_release_gate_contracts() -> None:
    pack = _yaml(PACK_PATH)
    reporter = dict(pack.get("reporter_followthrough") or {})
    workflow = _yaml(PROGRESS_EMAIL_WORKFLOW_PATH)
    release_gate = _yaml(FEEDBACK_RELEASE_GATE_PATH)

    assert list(reporter.get("required_stage_sequence") or []) == list(
        dict(workflow.get("e2e_gate") or {}).get("required_stage_sequence") or []
    )
    assert reporter["sender_identity"]["from_email"] == workflow["delivery_plane"]["sender_identity"]["from_email"]
    assert reporter["sender_identity"]["reply_to"] == workflow["delivery_plane"]["sender_identity"]["reply_to"]
    assert reporter["sender_identity"]["dispatch_tool"] == workflow["delivery_plane"]["dispatch_contract"]["tool_name"]
    assert reporter["sender_identity"]["provider"] == workflow["delivery_plane"]["dispatch_contract"]["preferred_provider"]
    assert set(reporter.get("required_receipt_fields") or []) == set(
        workflow["delivery_plane"]["dispatch_contract"]["required_receipt_fields"]
    )
    assert reporter["release_truth_guard"]["fix_available_requires_status"] == "released_to_reporter_channel"
    assert reporter["release_truth_guard"]["fix_available_requires_registry_truth"] is True
    assert "no_closure_without_release_truth" in {
        str(dict(item).get("id") or "") for item in release_gate.get("requirements") or []
    }


def test_reporter_stage_gates_match_workflow_exactly_once_rules_and_truth_planes() -> None:
    pack = _yaml(PACK_PATH)
    reporter = dict(pack.get("reporter_followthrough") or {})
    workflow = _yaml(PROGRESS_EMAIL_WORKFLOW_PATH)
    stages = {str(dict(stage).get("id")): dict(stage) for stage in workflow.get("stages") or []}
    stage_gates = {str(key): dict(value) for key, value in dict(reporter.get("stage_gates") or {}).items()}

    assert set(stage_gates) == set(reporter.get("required_stage_sequence") or [])
    assert stage_gates["request_received"]["exactly_once_rule"] == "exactly_once_per_case"
    assert stages["request_received"]["exactly_once_per_case"] is True
    assert stage_gates["audited_decision"]["exactly_once_rule"] == "exactly_once_per_decision_change"
    assert stages["audited_decision"]["exactly_once_per_decision_change"] is True
    assert stage_gates["fix_available"]["exactly_once_rule"] == "exactly_once_per_reporter_channel_release"
    assert stages["fix_available"]["exactly_once_per_reporter_channel_release"] is True

    assert "Registry release-channel truth" in stage_gates["fix_available"]["required_truth_planes"]
    assert "Hub reporter-channel linkage" in stage_gates["fix_available"]["required_truth_planes"]
    assert "download or updater route is known" in stage_gates["fix_available"]["fail_closed_reason"]
    for gate in stage_gates.values():
        assert str(gate.get("fail_closed_reason") or "").strip()


def test_runtime_safety_records_no_worker_side_telemetry_or_active_run_helpers() -> None:
    pack = _yaml(PACK_PATH)
    runtime_safety = dict(pack.get("runtime_safety") or {})

    assert runtime_safety.get("do_not_invoke_operator_telemetry_or_active_run_helpers") is True
    assert runtime_safety.get("active_run_helper_commands_invoked") == []
    assert runtime_safety.get("operator_telemetry_commands_invoked") == []
