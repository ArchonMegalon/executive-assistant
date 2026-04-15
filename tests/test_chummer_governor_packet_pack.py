from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
PACK_PATH = ROOT / "docs" / "chummer_governor_packets" / "CHUMMER_GOVERNOR_PACKET_PACK.yaml"
SPECIMENS_PATH = ROOT / "docs" / "chummer_governor_packets" / "OPERATOR_AND_REPORTER_PACKET_SPECIMENS.yaml"
CANONICAL_REGISTRY_PATH = Path("/docker/chummercomplete/chummer-design/products/chummer/NEXT_90_DAY_PRODUCT_ADVANCE_REGISTRY.yaml")
QUEUE_STAGING_PATH = Path("/docker/fleet/.codex-studio/published/NEXT_90_DAY_QUEUE_STAGING.generated.yaml")
DESIGN_QUEUE_STAGING_PATH = Path("/docker/chummercomplete/chummer-design/products/chummer/NEXT_90_DAY_QUEUE_STAGING.generated.yaml")
PROGRESS_EMAIL_WORKFLOW_PATH = ROOT / ".codex-design" / "product" / "FEEDBACK_PROGRESS_EMAIL_WORKFLOW.yaml"
FEEDBACK_RELEASE_GATE_PATH = ROOT / ".codex-design" / "product" / "FEEDBACK_LOOP_RELEASE_GATE.yaml"
FEEDBACK_CLOSEOUT_PATH = ROOT / "feedback" / "2026-04-15-ea-governor-packets-package-closeout.md"
HANDOFF_CLOSEOUT_PATH = ROOT / "docs" / "chummer_governor_packets" / "SUCCESSOR_HANDOFF_CLOSEOUT.yaml"


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
    design_queue_item = _find_package(_yaml(DESIGN_QUEUE_STAGING_PATH))

    assert pack.get("contract_name") == "ea.chummer_governor_packet_pack"
    assert pack.get("package_id") == "next90-m106-ea-governor-packets"
    assert int(pack.get("milestone_id") or 0) == 106
    assert pack.get("wave") == "W8"
    assert list(pack.get("owned_surfaces") or []) == [
        "operator_packets:weekly_governor",
        "reporter_followthrough:release_truth",
    ]
    assert queue_item.get("repo") == "executive-assistant"
    assert queue_item.get("status") == "complete"
    assert list(queue_item.get("allowed_paths") or []) == ["skills", "tests", "feedback", "docs"]
    assert list(queue_item.get("owned_surfaces") or []) == list(pack.get("owned_surfaces") or [])
    assert queue_item.get("title") == "Synthesize parity, support, and release signals into operator-ready and reporter-ready packets"
    assert queue_item.get("task") == (
        "Produce operator packets and reporter followthrough from the same readiness and parity truth used by the governor loop."
    )
    assert design_queue_item.get("status") == queue_item.get("status") == "complete"
    assert design_queue_item.get("repo") == queue_item.get("repo") == "executive-assistant"
    assert list(design_queue_item.get("allowed_paths") or []) == list(queue_item.get("allowed_paths") or [])
    assert list(design_queue_item.get("owned_surfaces") or []) == list(queue_item.get("owned_surfaces") or [])
    assert set(str(item) for item in design_queue_item.get("proof") or []) == {
        str(item) for item in queue_item.get("proof") or []
    }
    assert {
        "/docker/EA/docs/chummer_governor_packets/CHUMMER_GOVERNOR_PACKET_PACK.yaml",
        "/docker/EA/docs/chummer_governor_packets/OPERATOR_AND_REPORTER_PACKET_SPECIMENS.yaml",
        "/docker/EA/docs/chummer_governor_packets/README.md",
        "/docker/EA/docs/chummer_governor_packets/SUCCESSOR_HANDOFF_CLOSEOUT.yaml",
        "/docker/EA/tests/test_chummer_governor_packet_pack.py",
        "/docker/EA/feedback/2026-04-15-ea-governor-packets-package-closeout.md",
        "/docker/EA/feedback/2026-04-15-chummer-governor-packets-successor-guard.md",
        "python tests/test_chummer_governor_packet_pack.py exits 0 with ran=17 failed=0",
    } <= {str(item) for item in queue_item.get("proof") or []}


def test_successor_queue_ea_proof_paths_are_not_stale() -> None:
    queue_item = _find_package(_yaml(QUEUE_STAGING_PATH))
    design_queue_item = _find_package(_yaml(DESIGN_QUEUE_STAGING_PATH))
    assert set(str(item) for item in design_queue_item.get("proof") or []) == {
        str(item) for item in queue_item.get("proof") or []
    }
    proof_items = [str(item) for item in queue_item.get("proof") or []]
    ea_file_proofs = [Path(item) for item in proof_items if item.startswith("/docker/EA/")]

    assert ea_file_proofs, "queue row should cite EA-local proof artifacts"
    assert all(path.exists() for path in ea_file_proofs)
    assert all(
        path.relative_to(ROOT).parts[0] in {"docs", "tests", "feedback", "skills"}
        for path in ea_file_proofs
    )


def test_pack_proof_guardrails_track_queue_and_registry_authority() -> None:
    pack = _yaml(PACK_PATH)
    queue_item = _find_package(_yaml(QUEUE_STAGING_PATH))
    milestone = _find_milestone(_yaml(CANONICAL_REGISTRY_PATH), 106)
    guardrails = dict(pack.get("proof_guardrails") or {})
    verification = dict(guardrails.get("canonical_package_verification") or {})
    registry_task = next(
        dict(task)
        for task in milestone.get("work_tasks") or []
        if dict(task).get("id") == verification.get("registry_work_task_id")
    )

    assert verification.get("queue_package_id") == pack.get("package_id") == queue_item.get("package_id")
    assert verification.get("queue_repo") == queue_item.get("repo") == "executive-assistant"
    assert list(verification.get("queue_allowed_paths") or []) == list(queue_item.get("allowed_paths") or [])
    assert int(verification.get("registry_milestone_id") or 0) == int(milestone.get("id") or 0)
    assert {int(item) for item in verification.get("registry_dependencies") or []} == {
        int(item) for item in milestone.get("dependencies") or []
    }
    assert registry_task.get("owner") == "executive-assistant"
    assert registry_task.get("status") == "complete"
    assert "Synthesize support, parity, and release signals" in str(registry_task.get("title") or "")
    registry_evidence = {str(item) for item in registry_task.get("evidence") or []}
    assert all(
        any(expected in evidence for evidence in registry_evidence)
        for expected in {
            "/docker/EA/docs/chummer_governor_packets/CHUMMER_GOVERNOR_PACKET_PACK.yaml",
            "/docker/EA/docs/chummer_governor_packets/OPERATOR_AND_REPORTER_PACKET_SPECIMENS.yaml",
            "/docker/EA/docs/chummer_governor_packets/SUCCESSOR_HANDOFF_CLOSEOUT.yaml",
            "/docker/EA/tests/test_chummer_governor_packet_pack.py",
            "/docker/EA/feedback/2026-04-15-ea-governor-packets-package-closeout.md",
            "/docker/EA/feedback/2026-04-15-chummer-governor-packets-successor-guard.md",
            "python tests/test_chummer_governor_packet_pack.py exits 0 with ran=17 failed=0.",
        }
    )
    registry_evidence_items = [str(item) for item in registry_task.get("evidence") or []]
    registry_ea_file_proofs = [
        Path(item.split(" ", 1)[0])
        for item in registry_evidence_items
        if item.startswith("/docker/EA/")
    ]
    assert registry_ea_file_proofs, "registry work task should cite EA-local proof artifacts"
    assert all(path.exists() for path in registry_ea_file_proofs)
    assert all(
        path.relative_to(ROOT).parts[0] in {"docs", "tests", "feedback", "skills"}
        for path in registry_ea_file_proofs
    )
    assert any(
        item == "python tests/test_chummer_governor_packet_pack.py exits 0 with ran=17 failed=0."
        for item in registry_evidence_items
    )

    drift_policy = [str(item) for item in guardrails.get("drift_policy") or []]
    assert any("successor queue" in item and "owned surfaces" in item for item in drift_policy)
    assert any("progress email workflow" in item and "exactly-once" in item for item in drift_policy)
    assert any("docs, tests, feedback, or skills" in item for item in drift_policy)


def test_successor_frontier_closeout_prevents_reopening_completed_ea_slice() -> None:
    pack = _yaml(PACK_PATH)
    frontier = dict(dict(pack.get("proof_guardrails") or {}).get("successor_frontier") or {})
    readme = (ROOT / "docs" / "chummer_governor_packets" / "README.md").read_text(encoding="utf-8")

    assert int(frontier.get("frontier_id") or 0) == 1758984842
    assert frontier.get("local_package_state") == "ea_slice_complete"
    assert "Sibling Fleet, Hub, Registry, and design-owned milestone 106 packages remain" in str(
        frontier.get("remaining_work_boundary") or ""
    )
    assert "verify this pack and its tests before reopening" in str(frontier.get("repeat_prevention_rule") or "")
    assert "1758984842" in readme
    assert "complete for the EA-owned surfaces" in readme
    assert "SUCCESSOR_HANDOFF_CLOSEOUT.yaml" in readme


def test_handoff_closeout_manifest_keeps_future_shards_on_sibling_lanes() -> None:
    handoff = _yaml(HANDOFF_CLOSEOUT_PATH)
    queue_item = _find_package(_yaml(QUEUE_STAGING_PATH))
    pack = _yaml(PACK_PATH)

    assert handoff.get("contract_name") == "ea.chummer_governor_packets_successor_handoff_closeout"
    assert handoff.get("package_id") == pack.get("package_id") == queue_item.get("package_id")
    assert int(handoff.get("milestone_id") or 0) == int(pack.get("milestone_id") or 0)
    assert int(handoff.get("frontier_id") or 0) == 1758984842
    assert handoff.get("status") == "ea_scope_complete"
    assert list(handoff.get("closed_surfaces") or []) == list(pack.get("owned_surfaces") or [])

    boundary = dict(handoff.get("scope_boundary") or {})
    assert boundary.get("closed_package_only") == "next90-m106-ea-governor-packets"
    assert list(boundary.get("allowed_paths") or []) == list(queue_item.get("allowed_paths") or [])
    assert set(boundary.get("remaining_milestone_work_belongs_to") or []) == {
        "fleet",
        "chummer6-hub",
        "chummer6-hub-registry",
        "chummer6-design",
    }

    completed_outputs = {str(item) for item in handoff.get("completed_outputs") or []}
    allowed_output_roots = set(queue_item.get("allowed_paths") or [])
    assert completed_outputs, "handoff closeout should name completed package outputs"
    assert all((ROOT / item).exists() for item in completed_outputs)
    assert all(Path(item).parts[0] in allowed_output_roots for item in completed_outputs)
    for expected in {
        "docs/chummer_governor_packets/CHUMMER_GOVERNOR_PACKET_PACK.yaml",
        "docs/chummer_governor_packets/OPERATOR_AND_REPORTER_PACKET_SPECIMENS.yaml",
        "docs/chummer_governor_packets/README.md",
        "feedback/2026-04-15-ea-governor-packets-package-closeout.md",
        "feedback/2026-04-15-chummer-governor-packets-successor-guard.md",
        "feedback/2026-04-15-ea-governor-packets-successor-wave-pass-102117z.md",
        "feedback/2026-04-15-ea-governor-packets-successor-wave-pass-verified.md",
        "feedback/2026-04-15-ea-governor-packets-registry-evidence-guard.md",
        "feedback/2026-04-15-ea-governor-packets-active-run-handoff-guard.md",
    }:
        assert expected in completed_outputs
        assert (ROOT / expected).exists()

    proof = dict(handoff.get("proof_command") or {})
    assert proof.get("command") == "python tests/test_chummer_governor_packet_pack.py"
    assert proof.get("expected_result") == "ran=17 failed=0"

    proof_artifacts = {str(item) for item in handoff.get("proof_artifacts") or []}
    assert proof_artifacts, "handoff closeout should name the proof artifacts future shards must verify"
    assert all((ROOT / item).exists() for item in proof_artifacts)
    assert all(Path(item).parts[0] in allowed_output_roots for item in proof_artifacts)
    assert completed_outputs <= proof_artifacts
    assert "tests/test_chummer_governor_packet_pack.py" in proof_artifacts

    authority = dict(handoff.get("canonical_authority") or {})
    assert authority.get("successor_registry_path") == str(CANONICAL_REGISTRY_PATH)
    assert authority.get("successor_queue_path") == str(QUEUE_STAGING_PATH)
    assert authority.get("design_successor_queue_path") == str(DESIGN_QUEUE_STAGING_PATH)
    assert authority.get("queue_package") == "next90-m106-ea-governor-packets status=complete"
    assert authority.get("registry_work_task") == "106.2 status=complete owner=executive-assistant"
    assert set(authority.get("queue_proof_required_entries") or []) <= {
        str(item) for item in queue_item.get("proof") or []
    }
    assert set(authority.get("queue_proof_required_entries") or []) <= {
        str(item) for item in _find_package(_yaml(DESIGN_QUEUE_STAGING_PATH)).get("proof") or []
    }

    repeat_prevention = dict(handoff.get("repeat_prevention") or {})
    assert "Treat this EA-owned package as closed" in str(repeat_prevention.get("worker_rule") or "")
    assert any("Fleet weekly governor packet runtime" in item for item in repeat_prevention.get("do_not_reopen_for") or [])
    assert any("Design successor registry meaning" in item for item in repeat_prevention.get("do_not_reopen_for") or [])

    runtime_safety = dict(handoff.get("runtime_safety") or {})
    assert runtime_safety.get("do_not_invoke_operator_telemetry_or_active_run_helpers") is True
    assert runtime_safety.get("active_run_helper_commands_invoked") == []
    assert runtime_safety.get("operator_telemetry_commands_invoked") == []

    handoff_review = dict(handoff.get("active_run_handoff_review") or {})
    assert handoff_review.get("reviewed_path") == (
        "/var/lib/codex-fleet/chummer_design_supervisor/shard-12/ACTIVE_RUN_HANDOFF.generated.md"
    )
    assert int(handoff_review.get("reviewed_frontier_id") or 0) == 1758984842
    assert handoff_review.get("reviewed_package_id") == "next90-m106-ea-governor-packets"
    assert handoff_review.get("reviewed_mode") == "successor_wave"
    assert handoff_review.get("worker_safety_instruction_seen") is True
    assert "mutable operator state" in str(handoff_review.get("stability_rule") or "")


def test_active_run_handoff_review_is_recorded_without_live_handoff_dependency() -> None:
    handoff = _yaml(HANDOFF_CLOSEOUT_PATH)
    feedback = (ROOT / "feedback" / "2026-04-15-ea-governor-packets-active-run-handoff-guard.md").read_text(
        encoding="utf-8"
    )
    handoff_review = dict(handoff.get("active_run_handoff_review") or {})
    latest_verification = dict(handoff.get("latest_successor_wave_verification") or {})
    latest_note_path = ROOT / str(latest_verification.get("note_path") or "")

    assert handoff_review.get("reviewed_package_id") == "next90-m106-ea-governor-packets"
    assert handoff_review.get("worker_safety_instruction_seen") is True
    assert "tests must not depend on transient handoff tail text" in str(
        handoff_review.get("stability_rule") or ""
    )
    assert "reviewed the active-run handoff" in feedback
    assert "without making repo tests depend on mutable handoff tail text" in feedback
    assert "operator telemetry and active-run helper commands" in feedback

    assert latest_verification.get("verified_package_id") == "next90-m106-ea-governor-packets"
    assert int(latest_verification.get("verified_frontier_id") or 0) == 1758984842
    assert latest_verification.get("result") == "no_ea_owned_work_remaining"
    assert latest_verification.get("proof_command_result") == "ran=17 failed=0"
    assert set(latest_verification.get("checked_authorities") or []) == {
        "canonical successor registry milestone 106 work task 106.2",
        "design successor queue staging row",
        "fleet successor queue staging mirror row",
        "active-run handoff successor frontier assignment",
    }
    assert latest_verification.get("active_run_helper_commands_invoked") == []
    assert latest_verification.get("operator_telemetry_commands_invoked") == []
    assert latest_note_path.exists()
    latest_note = latest_note_path.read_text(encoding="utf-8")
    assert "No operator telemetry or active-run helper commands were invoked" in latest_note
    assert "No EA-owned work remains" in latest_note


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


def test_feedback_closeout_marks_ea_slice_complete_without_closing_sibling_work() -> None:
    closeout = FEEDBACK_CLOSEOUT_PATH.read_text(encoding="utf-8")

    assert "Package: next90-m106-ea-governor-packets" in closeout
    assert "operator_packets:weekly_governor" in closeout
    assert "reporter_followthrough:release_truth" in closeout
    assert "None inside the EA-owned package surfaces" in closeout
    assert "Sibling milestone 106 work remains" in closeout


def test_specimens_project_operator_and_reporter_packets_from_same_anchors() -> None:
    pack = _yaml(PACK_PATH)
    specimens = _yaml(SPECIMENS_PATH)

    shared_anchors = set(pack.get("shared_evidence_anchor_ids") or [])
    assert specimens.get("package_id") == pack.get("package_id")
    assert int(specimens.get("milestone_id") or 0) == int(pack.get("milestone_id") or 0)
    assert set(specimens.get("shared_evidence_anchor_ids") or []) == shared_anchors
    assert set(dict(specimens.get("shared_evidence_bindings") or {})) == shared_anchors
    assert specimens["operator_packet_specimen"]["packet_kind"] == "operator_packets:weekly_governor"
    assert specimens["reporter_followthrough_specimen"]["packet_kind"] == "reporter_followthrough:release_truth"
    assert set(specimens["operator_packet_specimen"]["specimen_payload"]["cited_signal_ids"]) == shared_anchors
    assert _source_path({"path": specimens.get("source_pack")}).resolve() == PACK_PATH.resolve()

    source_truth = {
        str(dict(row).get("id") or ""): _source_path(dict(row)).resolve()
        for row in dict(pack.get("source_truth") or {}).values()
        if dict(row).get("id") in shared_anchors
    }
    bindings = {key: _source_path(dict(row)).resolve() for key, row in dict(specimens.get("shared_evidence_bindings") or {}).items()}
    assert bindings == source_truth


def test_specimens_track_progress_workflow_stage_payloads_without_local_drift() -> None:
    specimens = _yaml(SPECIMENS_PATH)
    workflow = _yaml(PROGRESS_EMAIL_WORKFLOW_PATH)
    reporter = dict(specimens.get("reporter_followthrough_specimen") or {})
    workflow_stages = {str(dict(stage).get("id") or ""): dict(stage) for stage in workflow.get("stages") or []}
    specimen_stages = {str(key): dict(value) for key, value in dict(reporter.get("specimen_stage_payloads") or {}).items()}

    assert set(specimen_stages) == set(workflow_stages)
    for stage_id, specimen_stage in specimen_stages.items():
        workflow_stage = workflow_stages[stage_id]
        assert specimen_stage.get("allowed_trigger_statuses") == workflow_stage.get("trigger_statuses")
        assert specimen_stage.get("required_fields") == workflow_stage.get("required_fields")

    assert specimen_stages["request_received"]["exactly_once_rule"] == "exactly_once_per_case"
    assert workflow_stages["request_received"]["exactly_once_per_case"] is True
    assert specimen_stages["audited_decision"]["exactly_once_rule"] == "exactly_once_per_decision_change"
    assert workflow_stages["audited_decision"]["exactly_once_per_decision_change"] is True
    assert specimen_stages["fix_available"]["exactly_once_rule"] == "exactly_once_per_reporter_channel_release"
    assert workflow_stages["fix_available"]["exactly_once_per_reporter_channel_release"] is True


def test_specimens_keep_reporter_fix_available_release_truth_fail_closed() -> None:
    specimens = _yaml(SPECIMENS_PATH)
    reporter = dict(specimens.get("reporter_followthrough_specimen") or {})
    stages = {str(key): dict(value) for key, value in dict(reporter.get("specimen_stage_payloads") or {}).items()}
    fix_available = stages["fix_available"]

    assert list(reporter.get("required_stage_sequence") or []) == ["request_received", "audited_decision", "fix_available"]
    assert reporter["sender_identity"]["from_email"] == "wageslave@chummer.run"
    assert reporter["sender_identity"]["reply_to"] == "support@chummer.run"
    assert fix_available["allowed_trigger_statuses"] == ["released_to_reporter_channel"]
    assert fix_available["release_truth_required"] is True
    assert "Registry release-channel truth" in fix_available["required_truth_planes"]
    assert "Hub reporter-channel linkage" in fix_available["required_truth_planes"]
    assert set(fix_available["forbidden_resolution_sources"]) == {
        "reproduced_bug",
        "drafted_patch",
        "merged_pr",
        "preview_build",
    }


def _run_direct() -> int:
    failed = 0
    ran = 0
    for name, func in sorted(globals().items()):
        if not name.startswith("test_") or not callable(func):
            continue
        ran += 1
        try:
            func()
        except Exception as exc:
            failed += 1
            print(f"FAIL {name}: {exc}")
    print(f"ran={ran} failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_direct())
