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
    matches = [
        dict(item)
        for item in queue.get("items") or []
        if dict(item).get("package_id") == "next90-m106-ea-governor-packets"
    ]
    assert len(matches) == 1, "successor queue must contain exactly one next90-m106-ea-governor-packets row"
    return matches[0]


def _find_milestone(registry: dict, milestone_id: int) -> dict:
    for item in registry.get("milestones") or []:
        row = dict(item)
        if int(row.get("id") or 0) == milestone_id:
            return row
    raise AssertionError(f"missing milestone {milestone_id}")


def _find_registry_task(milestone: dict, task_id: float) -> dict:
    matches = [
        dict(task)
        for task in milestone.get("work_tasks") or []
        if dict(task).get("id") == task_id
    ]
    assert len(matches) == 1, f"milestone {milestone.get('id')} must contain exactly one work task {task_id}"
    return matches[0]


def _expected_direct_runner_result() -> str:
    ran = sum(1 for name, func in globals().items() if name.startswith("test_") and callable(func))
    return f"ran={ran} failed=0"


def _allowed_historical_runner_results() -> set[str]:
    return {"ran=17 failed=0", _expected_direct_runner_result()}


def _timestamp_suffix_from_repeat_note(note_path: str) -> str:
    stem = Path(note_path).stem
    suffix = stem.rsplit("-", 1)[-1].removesuffix("z")
    return suffix if suffix.isdigit() else ""


def _strings(value: object) -> list[str]:
    if isinstance(value, dict):
        return [item for child in value.values() for item in _strings(child)]
    if isinstance(value, list):
        return [item for child in value for item in _strings(child)]
    if isinstance(value, str):
        return [value]
    return []


def _without_keys(value: object, keys_to_drop: set[str]) -> object:
    if isinstance(value, dict):
        return {
            key: _without_keys(child, keys_to_drop)
            for key, child in value.items()
            if str(key) not in keys_to_drop
        }
    if isinstance(value, list):
        return [_without_keys(child, keys_to_drop) for child in value]
    return value


def test_pack_contract_tracks_successor_package_and_owned_surfaces() -> None:
    pack = _yaml(PACK_PATH)
    queue_item = _find_package(_yaml(QUEUE_STAGING_PATH))
    design_queue_item = _find_package(_yaml(DESIGN_QUEUE_STAGING_PATH))
    expected_result = _expected_direct_runner_result()

    assert pack.get("contract_name") == "ea.chummer_governor_packet_pack"
    assert pack.get("package_id") == "next90-m106-ea-governor-packets"
    assert int(pack.get("milestone_id") or 0) == 106
    assert pack.get("wave") == "W8"
    assert pack.get("status") == "task_proven"
    assert list(pack.get("owned_surfaces") or []) == [
        "operator_packets:weekly_governor",
        "reporter_followthrough:release_truth",
    ]
    assert queue_item.get("repo") == "executive-assistant"
    assert queue_item.get("status") == "complete"
    assert int(queue_item.get("frontier_id") or 0) == 1758984842
    assert list(queue_item.get("allowed_paths") or []) == ["skills", "tests", "feedback", "docs"]
    assert list(queue_item.get("owned_surfaces") or []) == list(pack.get("owned_surfaces") or [])
    assert queue_item.get("title") == "Synthesize parity, support, and release signals into operator-ready and reporter-ready packets"
    assert queue_item.get("task") == (
        "Produce operator packets and reporter followthrough from the same readiness and parity truth used by the governor loop."
    )
    assert _yaml(SPECIMENS_PATH).get("status") == pack.get("status")
    assert _yaml(HANDOFF_CLOSEOUT_PATH).get("status") == "ea_scope_complete"
    assert design_queue_item.get("status") == queue_item.get("status") == "complete"
    assert int(design_queue_item.get("frontier_id") or 0) == int(queue_item.get("frontier_id") or 0) == 1758984842
    assert design_queue_item.get("repo") == queue_item.get("repo") == "executive-assistant"
    assert list(design_queue_item.get("allowed_paths") or []) == list(queue_item.get("allowed_paths") or [])
    assert list(design_queue_item.get("owned_surfaces") or []) == list(queue_item.get("owned_surfaces") or [])
    assert set(str(item) for item in design_queue_item.get("proof") or []) == {
        str(item) for item in queue_item.get("proof") or []
    }
    expected_queue_proof = {
        "/docker/EA/docs/chummer_governor_packets/CHUMMER_GOVERNOR_PACKET_PACK.yaml",
        "/docker/EA/docs/chummer_governor_packets/OPERATOR_AND_REPORTER_PACKET_SPECIMENS.yaml",
        "/docker/EA/docs/chummer_governor_packets/README.md",
        "/docker/EA/docs/chummer_governor_packets/SUCCESSOR_HANDOFF_CLOSEOUT.yaml",
        "/docker/EA/tests/test_chummer_governor_packet_pack.py",
        "/docker/EA/feedback/2026-04-15-ea-governor-packets-package-closeout.md",
        "/docker/EA/feedback/2026-04-15-chummer-governor-packets-successor-guard.md",
        "/docker/EA/feedback/2026-04-15-ea-governor-packets-terminal-repeat-prevention.md",
        f"python tests/test_chummer_governor_packet_pack.py exits 0 with {expected_result}",
    }
    assert {str(item) for item in queue_item.get("proof") or []} == expected_queue_proof
    assert {str(item) for item in design_queue_item.get("proof") or []} == expected_queue_proof
    assert not any(
        "ea-governor-packets-successor-wave-pass-" in str(item)
        for item in queue_item.get("proof") or []
    )


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
    design_queue_item = _find_package(_yaml(DESIGN_QUEUE_STAGING_PATH))
    milestone = _find_milestone(_yaml(CANONICAL_REGISTRY_PATH), 106)
    guardrails = dict(pack.get("proof_guardrails") or {})
    verification = dict(guardrails.get("canonical_package_verification") or {})
    registry_task = _find_registry_task(milestone, verification.get("registry_work_task_id"))
    expected_result = _expected_direct_runner_result()

    assert verification.get("queue_package_id") == pack.get("package_id") == queue_item.get("package_id")
    assert int(verification.get("queue_frontier_id") or 0) == int(queue_item.get("frontier_id") or 0) == 1758984842
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
            "/docker/EA/feedback/2026-04-15-ea-governor-packets-terminal-repeat-prevention.md",
            f"python tests/test_chummer_governor_packet_pack.py exits 0 with {expected_result}.",
        }
    )
    registry_evidence_items = [str(item) for item in registry_task.get("evidence") or []]
    assert not any(
        "ea-governor-packets-successor-wave-pass-" in item
        for item in registry_evidence_items
    )
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
        item == f"python tests/test_chummer_governor_packet_pack.py exits 0 with {expected_result}."
        for item in registry_evidence_items
    )
    all_canonical_evidence_items = [
        *[str(item) for item in queue_item.get("proof") or []],
        *[str(item) for item in design_queue_item.get("proof") or []],
        *registry_evidence_items,
    ]
    forbidden_worker_proof_markers = {
        "task_local_telemetry.generated.json",
        "operator telemetry stdout",
        "operator telemetry stderr",
        "active-run helper stdout",
        "active-run helper stderr",
        "active-run helper command output",
        "run-helper output",
        "helper command receipt",
        "telemetry command receipt",
    }
    forbidden_mutable_proof_paths = {
        "/var/lib/codex-fleet/chummer_design_supervisor/",
        "/var/lib/codex-fleet/",
        "/docker/fleet/state/chummer_design_supervisor/",
    }
    assert not any(
        marker in evidence.lower()
        for evidence in all_canonical_evidence_items
        for marker in forbidden_worker_proof_markers
    )
    assert not any(
        path in evidence
        for evidence in all_canonical_evidence_items
        for path in forbidden_mutable_proof_paths
    )

    drift_policy = [str(item) for item in guardrails.get("drift_policy") or []]
    assert any("successor queue" in item and "owned surfaces" in item for item in drift_policy)
    assert any("progress email workflow" in item and "exactly-once" in item for item in drift_policy)
    assert any("docs, tests, feedback, or skills" in item for item in drift_policy)
    assert any(
        "Implementation-only retry assignments" in item
        and "assignment context only" in item
        and "must not become packet proof" in item
        for item in drift_policy
    )


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
        "feedback/2026-04-15-ea-governor-packets-dual-queue-proof-guard.md",
        "feedback/2026-04-15-ea-governor-packets-successor-wave-pass-111728z.md",
        "feedback/2026-04-15-ea-governor-packets-successor-wave-pass-112001z.md",
        "feedback/2026-04-15-ea-governor-packets-successor-wave-pass-1124z.md",
        "feedback/2026-04-15-ea-governor-packets-successor-wave-pass-113230z.md",
    }:
        assert expected in completed_outputs
        assert (ROOT / expected).exists()

    proof = dict(handoff.get("proof_command") or {})
    assert proof.get("command") == "python tests/test_chummer_governor_packet_pack.py"
    assert proof.get("worker_runtime_fallback_command") == "python3 tests/test_chummer_governor_packet_pack.py"
    fallback_use_rule = str(proof.get("fallback_use_rule") or "")
    assert "worker image has no python executable" in fallback_use_rule
    assert "same direct-run proof module" in fallback_use_rule
    assert proof.get("expected_result") == _expected_direct_runner_result()

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
    assert authority.get("queue_frontier") == "1758984842"
    assert authority.get("registry_work_task") == "106.2 status=complete owner=executive-assistant"
    assert set(authority.get("queue_proof_required_entries") or []) == {
        str(item) for item in queue_item.get("proof") or []
    }
    assert set(authority.get("queue_proof_required_entries") or []) == {
        str(item) for item in _find_package(_yaml(DESIGN_QUEUE_STAGING_PATH)).get("proof") or []
    }
    assert (
        "/docker/EA/feedback/2026-04-15-ea-governor-packets-terminal-repeat-prevention.md"
        in set(authority.get("queue_proof_required_entries") or [])
    )

    repeat_prevention = dict(handoff.get("repeat_prevention") or {})
    assert "Treat this EA-owned package as closed" in str(repeat_prevention.get("worker_rule") or "")
    assert any("Fleet weekly governor packet runtime" in item for item in repeat_prevention.get("do_not_reopen_for") or [])
    assert any("Design successor registry meaning" in item for item in repeat_prevention.get("do_not_reopen_for") or [])

    terminal_policy = dict(handoff.get("terminal_verification_policy") or {})
    policy_inputs = dict(terminal_policy.get("applies_after") or {})
    assert terminal_policy.get("policy_id") == "ea-governor-packets-terminal-repeat-prevention"
    assert policy_inputs.get("queue_package") == "next90-m106-ea-governor-packets status=complete"
    assert policy_inputs.get("registry_work_task") == "106.2 status=complete owner=executive-assistant"
    assert policy_inputs.get("proof_command_result") == _expected_direct_runner_result()
    assert terminal_policy.get("active_run_handoff_refresh_required") is False
    assert terminal_policy.get("timestamp_only_handoff_refreshes_are_proof") is False
    assert terminal_policy.get("successor_wave_verification_history_closed") is True
    assert terminal_policy.get("latest_allowed_timestamp_only_verification_at") == "2026-04-15T15:13:15Z"
    assert terminal_policy.get("post_terminal_proof_command_result_required") == _expected_direct_runner_result()
    assert "Do not append a new successor-wave verification note solely because" in str(
        terminal_policy.get("current_worker_rule") or ""
    )
    assert "ACTIVE_RUN_HANDOFF.generated.md has a newer timestamp" in str(
        terminal_policy.get("current_worker_rule") or ""
    )
    implementation_only_retry_rule = str(terminal_policy.get("implementation_only_retry_rule") or "")
    assert "Implementation-only retries" in implementation_only_retry_rule
    assert "task-local telemetry proof" in implementation_only_retry_rule
    assert "allowed reopen trigger" in implementation_only_retry_rule
    latest_allowed_timestamp_only = str(terminal_policy.get("latest_allowed_timestamp_only_verification_at") or "")
    assert (
        terminal_policy.get("repeated_assignment_handling")
        == (
            "Treat later active-run handoffs for the same package id and frontier id as ignored by this "
            "terminal policy without appending per-handoff manifest rows, unless an allowed reopen trigger "
            "below fires."
        )
    )
    ignored_assignment_rule = dict(terminal_policy.get("ignored_assignment_rule") or {})
    assert ignored_assignment_rule.get("package_id") == "next90-m106-ea-governor-packets"
    assert int(ignored_assignment_rule.get("frontier_id") or 0) == 1758984842
    assert ignored_assignment_rule.get("active_run_handoff_path") == (
        "/docker/fleet/state/chummer_design_supervisor/shard-12/ACTIVE_RUN_HANDOFF.generated.md"
    )
    assert ignored_assignment_rule.get("generated_after") == latest_allowed_timestamp_only
    assert ignored_assignment_rule.get("prompt_path_pattern") == (
        "/docker/fleet/state/chummer_design_supervisor/shard-12/runs/*/prompt.txt"
    )
    assert ignored_assignment_rule.get("action") == "ignore_without_manifest_append"
    assert ignored_assignment_rule.get("worker_safety_instruction_required") is True
    assert {
        "completed_outputs",
        "proof_artifacts",
        "latest_successor_wave_verification",
        "additional_successor_wave_verifications",
        "canonical registry evidence",
        "design queue proof",
        "fleet queue proof",
        "ignored_assignment_signals_after_terminal",
    } == {str(item) for item in ignored_assignment_rule.get("do_not_add_to") or []}
    assert ignored_assignment_rule.get("active_run_helper_commands_invoked") == []
    assert ignored_assignment_rule.get("operator_telemetry_commands_invoked") == []
    forbidden_retry_proof_sources = {str(item) for item in terminal_policy.get("forbidden_retry_proof_sources") or []}
    assert {
        "task-local telemetry generated file",
        "ACTIVE_RUN_HANDOFF.generated.md timestamp refresh",
        "supervisor status helper output",
        "supervisor eta helper output",
        "supervisor polling helper output",
        "active-run polling output",
        "operator telemetry output",
        "feedback/2026-04-16-ea-governor-packets-*",
        "feedback/2026-04-17-ea-governor-packets-*",
    } <= forbidden_retry_proof_sources
    retry_helper_loop_guard = dict(terminal_policy.get("retry_helper_loop_guard") or {})
    assert retry_helper_loop_guard.get("guard_id") == "implementation_only_retry_helper_loop_guard"
    assert retry_helper_loop_guard.get("applies_to_package_id") == "next90-m106-ea-governor-packets"
    assert int(retry_helper_loop_guard.get("applies_to_frontier_id") or 0) == 1758984842
    assert "supervisor helper loops" in str(retry_helper_loop_guard.get("previous_failure_mode") or "")
    assert "no EA-owned packet evidence" in str(retry_helper_loop_guard.get("previous_failure_mode") or "")
    retry_worker_rule = str(retry_helper_loop_guard.get("worker_rule") or "")
    assert "Implementation-only retries" in retry_worker_rule
    assert "worker-safe handoff as assignment context" in retry_worker_rule
    assert "not valid orientation, proof, or reopen evidence" in retry_worker_rule
    denied_command_fragments = {str(item) for item in retry_helper_loop_guard.get("denied_command_fragments") or []}
    assert {
        "supervisor status",
        "supervisor eta",
        "supervisor polling",
        "status helper",
        "eta helper",
        "polling helper",
        "active-run polling",
        "operator telemetry",
        "codexea status",
        "codexea eta",
    } <= denied_command_fragments
    allowed_worker_context = {str(item) for item in retry_helper_loop_guard.get("allowed_worker_context") or []}
    assert "task-local telemetry file may be read only because the assignment requires it" in allowed_worker_context
    assert "ACTIVE_RUN_HANDOFF.generated.md may be read only as worker-safe resume context" in allowed_worker_context
    assert "repo-local docs and tests remain the proof boundary" in allowed_worker_context
    required_startup_context = {str(item) for item in retry_helper_loop_guard.get("required_startup_context") or []}
    assert {
        "task-local telemetry path supplied by the active assignment prompt",
        "at least one listed canonical repo file before package inspection",
        "worker-safe active-run handoff when the prompt requires it",
        "target package files under docs, tests, feedback, or skills before any edit",
    } == required_startup_context
    startup_command_policy = str(retry_helper_loop_guard.get("startup_command_policy") or "")
    assert "current worker prompt's required direct reads" in startup_command_policy
    assert "assignment intake, not package proof" in startup_command_policy
    assert "invented orientation helpers" in startup_command_policy
    assert "supervisor status" in startup_command_policy
    assignment_context_pattern = dict(retry_helper_loop_guard.get("assignment_context_pattern") or {})
    assert assignment_context_pattern.get("telemetry_path_pattern") == (
        "/docker/fleet/state/chummer_design_supervisor/shard-12/runs/*/TASK_LOCAL_TELEMETRY.generated.json"
    )
    assert assignment_context_pattern.get("active_run_handoff_path") == (
        "/docker/fleet/state/chummer_design_supervisor/shard-12/ACTIVE_RUN_HANDOFF.generated.md"
    )
    assert assignment_context_pattern.get("generated_after") == latest_allowed_timestamp_only
    assert "assignment context only" in str(assignment_context_pattern.get("use_rule") or "")
    assert "do not add run ids" in str(assignment_context_pattern.get("use_rule") or "")
    assert assignment_context_pattern.get("first_commands_are_assignment_intake_not_proof") is True
    assert assignment_context_pattern.get("active_run_helper_commands_invoked") == []
    assert assignment_context_pattern.get("operator_telemetry_commands_invoked") == []
    edit_policy = str(retry_helper_loop_guard.get("implementation_only_edit_policy") or "")
    assert "After the prompt-required startup reads" in edit_policy
    assert "direct target inspection" in edit_policy
    assert "edit repo-local docs, tests, feedback, or skills" in edit_policy
    assert "real drift" in edit_policy
    historical_operator_status_policy = str(
        retry_helper_loop_guard.get("historical_operator_status_policy") or ""
    )
    assert "historical operator status snippets" in historical_operator_status_policy
    assert "stale notes" in historical_operator_status_policy
    assert "not commands to repeat" in historical_operator_status_policy
    stop_report_contract = dict(retry_helper_loop_guard.get("stop_report_contract") or {})
    assert stop_report_contract.get("required_fields") == [
        "What shipped",
        "What remains",
        "Exact blocker",
    ]
    assert retry_helper_loop_guard.get("invented_orientation_denied") is True
    assert set(retry_helper_loop_guard.get("required_direct_read_context_roles") or []) == {
        "task-local telemetry assignment file",
        "Fleet-published successor queue mirror",
        "design-owned successor registry",
        "program milestone spine",
        "closed biggest-wins registry",
        "product roadmap",
        "worker-safe active-run handoff",
    }
    assert set(retry_helper_loop_guard.get("proof_boundary") or []) == {
        "docs/chummer_governor_packets/CHUMMER_GOVERNOR_PACKET_PACK.yaml",
        "docs/chummer_governor_packets/OPERATOR_AND_REPORTER_PACKET_SPECIMENS.yaml",
        "docs/chummer_governor_packets/SUCCESSOR_HANDOFF_CLOSEOUT.yaml",
        "tests/test_chummer_governor_packet_pack.py",
    }
    allowed_reopen_triggers = {str(item) for item in terminal_policy.get("allowed_reopen_triggers") or []}
    assert {
        "canonical successor registry reopens or changes work task 106.2",
        "design or Fleet successor queue row changes package id, frontier id, repo, allowed paths, owned surfaces, status, or required proof entries",
        "docs/chummer_governor_packets packet artifacts or tests fail the proof command",
        "mirrored progress email workflow, feedback release gate, parity pack, or weekly pulse anchors disappear or drift from the guarded contract",
    } <= allowed_reopen_triggers
    assert not any("active-run" in item.lower() and "timestamp" in item.lower() for item in allowed_reopen_triggers)
    assert terminal_policy.get("proof_note") == (
        "feedback/2026-04-15-ea-governor-packets-terminal-repeat-prevention.md"
    )
    assert str(terminal_policy.get("proof_note") or "") in completed_outputs
    assert str(terminal_policy.get("proof_note") or "") in proof_artifacts
    assert terminal_policy.get("ignored_assignment_signals_after_terminal") == []

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
    expected_result = _expected_direct_runner_result()
    historical_results = _allowed_historical_runner_results()
    latest_note_path = ROOT / str(latest_verification.get("note_path") or "")
    completed_outputs = {str(item) for item in handoff.get("completed_outputs") or []}
    proof_artifacts = {str(item) for item in handoff.get("proof_artifacts") or []}

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
    assert latest_verification.get("proof_command_result") in historical_results
    assert latest_verification.get("active_run_handoff_generated_at") == "2026-04-15T15:13:15Z"
    assert str(latest_verification.get("active_run_handoff_prompt_path") or "").endswith(
        "/runs/20260415T151205Z-shard-12/prompt.txt"
    )
    assert set(latest_verification.get("checked_authorities") or []) == {
        "canonical successor registry milestone 106 work task 106.2",
        "design successor queue staging row",
        "fleet successor queue staging mirror row",
        "active-run handoff successor frontier assignment",
    }
    assert latest_verification.get("active_run_helper_commands_invoked") == []
    assert latest_verification.get("operator_telemetry_commands_invoked") == []
    assert latest_note_path.exists()
    assert str(latest_verification.get("note_path") or "") in completed_outputs
    assert str(latest_verification.get("note_path") or "") in proof_artifacts
    latest_note = latest_note_path.read_text(encoding="utf-8")
    assert "No operator telemetry or active-run helper commands were invoked" in latest_note
    assert "No EA-owned work remains" in latest_note

    verification_history = [latest_verification] + [
        dict(item) for item in handoff.get("additional_successor_wave_verifications") or []
    ]
    terminal_policy = dict(handoff.get("terminal_verification_policy") or {})
    latest_allowed_timestamp_only = str(terminal_policy.get("latest_allowed_timestamp_only_verification_at") or "")
    post_terminal_result = str(terminal_policy.get("post_terminal_proof_command_result_required") or "")
    successor_wave_pass_notes = sorted(
        (ROOT / "feedback").glob("2026-04-15-ea-governor-packets-successor-wave-pass-*.md")
    )
    assert verification_history, "closeout manifest should retain successor-wave verification history"
    assert post_terminal_result == expected_result
    assert len({str(item.get("note_path") or "") for item in verification_history}) == len(verification_history)
    assert verification_history == sorted(
        verification_history,
        key=lambda item: str(item.get("verified_at") or ""),
        reverse=True,
    )
    assert terminal_policy.get("successor_wave_verification_history_closed") is True
    assert all(str(item.get("verified_at") or "") <= latest_allowed_timestamp_only for item in verification_history)
    assert all(
        str(path.relative_to(ROOT)) in completed_outputs
        for path in successor_wave_pass_notes
    )
    terminal_note_time = latest_allowed_timestamp_only.split("T", 1)[1].removesuffix("Z").replace(":", "")
    timestamped_successor_notes = {
        path.stem.rsplit("-", 1)[-1].removesuffix("z")
        for path in successor_wave_pass_notes
        if path.stem.rsplit("-", 1)[-1].endswith("z")
    }
    assert all(note_time <= terminal_note_time for note_time in timestamped_successor_notes)
    assert not any(
        "timestamp-only" in str(item.get("hardening_added") or "").lower()
        for item in verification_history
    )
    terminal_note_path = ROOT / str(terminal_policy.get("proof_note") or "")
    terminal_note = terminal_note_path.read_text(encoding="utf-8")
    assert "a newer `ACTIVE_RUN_HANDOFF.generated.md` timestamp alone is not a reason" in terminal_note
    assert "Future reopen triggers are limited to real authority or proof drift" in terminal_note
    assert "Proof:" in terminal_note
    forbidden_proof_output_markers = {
        "task_local_telemetry.generated.json",
        "operator telemetry stdout",
        "operator telemetry stderr",
        "active-run helper stdout",
        "active-run helper stderr",
        "active-run helper command output",
        "run-helper output",
        "helper command receipt",
        "telemetry command receipt",
    }
    for verification in verification_history:
        note_path = ROOT / str(verification.get("note_path") or "")
        assert verification.get("verified_package_id") == "next90-m106-ea-governor-packets"
        assert int(verification.get("verified_frontier_id") or 0) == 1758984842
        assert verification.get("result") == "no_ea_owned_work_remaining"
        assert verification.get("proof_command_result") in historical_results
        if str(verification.get("verified_at") or "") > latest_allowed_timestamp_only:
            assert verification.get("proof_command_result") == post_terminal_result
        assert verification.get("active_run_helper_commands_invoked") == []
        assert verification.get("operator_telemetry_commands_invoked") == []
        assert note_path.exists()
        assert str(verification.get("note_path") or "") in completed_outputs
        assert str(verification.get("note_path") or "") in proof_artifacts
        note_text = note_path.read_text(encoding="utf-8").lower()
        assert not any(marker in note_text for marker in forbidden_proof_output_markers), note_path


def test_terminal_policy_blocks_mutable_handoff_timestamp_from_becoming_evidence() -> None:
    handoff = _yaml(HANDOFF_CLOSEOUT_PATH)
    terminal_policy = dict(handoff.get("terminal_verification_policy") or {})
    latest_verification = dict(handoff.get("latest_successor_wave_verification") or {})
    additional_verifications = [
        dict(item) for item in handoff.get("additional_successor_wave_verifications") or []
    ]
    completed_outputs = {str(item) for item in handoff.get("completed_outputs") or []}
    proof_artifacts = {str(item) for item in handoff.get("proof_artifacts") or []}
    latest_allowed_timestamp_only = str(terminal_policy.get("latest_allowed_timestamp_only_verification_at") or "")
    history = [latest_verification, *additional_verifications]

    assert terminal_policy.get("active_run_handoff_refresh_required") is False
    assert terminal_policy.get("timestamp_only_handoff_refreshes_are_proof") is False
    assert terminal_policy.get("successor_wave_verification_history_closed") is True
    assert "assignment signal, not EA-owned implementation evidence" in (
        ROOT / "docs" / "chummer_governor_packets" / "README.md"
    ).read_text(encoding="utf-8")
    readme_text = (ROOT / "docs" / "chummer_governor_packets" / "README.md").read_text(encoding="utf-8")
    assert "Implementation-only retries for the same package id and frontier id" in readme_text
    assert "must not create new timestamp-only feedback notes" in readme_text
    assert "`retry_helper_loop_guard`" in readme_text
    assert "direct-read context set" in readme_text
    assert "invented orientation as denied" in readme_text
    assert "not orientation, proof, or reopen evidence" in readme_text
    assert "newer `ACTIVE_RUN_HANDOFF.generated.md` timestamp alone is not a reason" in (
        ROOT / str(terminal_policy.get("proof_note") or "")
    ).read_text(encoding="utf-8")
    assert "without appending per-handoff manifest rows" in str(
        terminal_policy.get("repeated_assignment_handling") or ""
    )
    ignored_assignment_rule = dict(terminal_policy.get("ignored_assignment_rule") or {})
    assert ignored_assignment_rule.get("action") == "ignore_without_manifest_append"
    assert ignored_assignment_rule.get("generated_after") == latest_allowed_timestamp_only
    assert "completed_outputs" in set(ignored_assignment_rule.get("do_not_add_to") or [])
    assert "additional_successor_wave_verifications" in set(ignored_assignment_rule.get("do_not_add_to") or [])
    assert "ignored_assignment_signals_after_terminal" in set(
        ignored_assignment_rule.get("do_not_add_to") or []
    )

    for verification in history:
        assert str(verification.get("verified_at") or "") <= latest_allowed_timestamp_only
        assert str(verification.get("active_run_handoff_generated_at") or "") <= latest_allowed_timestamp_only

    successor_wave_pass_notes = {
        str(path.relative_to(ROOT))
        for path in (ROOT / "feedback").glob("2026-04-15-ea-governor-packets-successor-wave-pass-*.md")
    }
    assert successor_wave_pass_notes <= completed_outputs
    assert successor_wave_pass_notes <= proof_artifacts
    assert not any(
        note.rsplit("-", 1)[-1].removesuffix(".md").removesuffix("z") > "151315"
        for note in successor_wave_pass_notes
        if note.rsplit("-", 1)[-1].removesuffix(".md").endswith("z")
    )
    terminal_note_time = latest_allowed_timestamp_only.split("T", 1)[1].removesuffix("Z").replace(":", "")
    repeat_note_prefixes = (
        "feedback/2026-04-15-ea-governor-packets-successor-wave-pass-",
        "feedback/2026-04-15-ea-governor-packets-active-run-handoff-",
        "feedback/2026-04-15-ea-governor-packets-repeat-verification-",
        "feedback/2026-04-15-ea-governor-packets-current-handoff-",
    )
    manifest_repeat_notes = {
        note
        for note in completed_outputs | proof_artifacts
        if note.startswith(repeat_note_prefixes)
    }
    assert not any(
        note_time and note_time > terminal_note_time
        for note_time in (_timestamp_suffix_from_repeat_note(note) for note in manifest_repeat_notes)
    )

    verification_history = [
        dict(handoff.get("latest_successor_wave_verification") or {}),
        *[dict(item) for item in handoff.get("additional_successor_wave_verifications") or []],
    ]
    completed_outputs = {str(item) for item in handoff.get("completed_outputs") or []}
    proof_artifacts = {str(item) for item in handoff.get("proof_artifacts") or []}
    queue_item = _find_package(_yaml(QUEUE_STAGING_PATH))
    design_queue_item = _find_package(_yaml(DESIGN_QUEUE_STAGING_PATH))
    registry_task = _find_registry_task(_find_milestone(_yaml(CANONICAL_REGISTRY_PATH), 106), 106.2)
    canonical_evidence = [
        *[str(item) for item in queue_item.get("proof") or []],
        *[str(item) for item in design_queue_item.get("proof") or []],
        *[str(item) for item in registry_task.get("evidence") or []],
    ]

    ignored_signals = terminal_policy.get("ignored_assignment_signals_after_terminal")
    assert ignored_signals == []
    synthetic_ignored_assignment = {
        "active_run_handoff_generated_at": "2026-04-15T19:44:20Z",
        "active_run_handoff_prompt_path": (
            "/docker/fleet/state/chummer_design_supervisor/shard-12/runs/"
            "20260415T194253Z-shard-12/prompt.txt"
        ),
    }
    ignored_prompt_paths = {synthetic_ignored_assignment["active_run_handoff_prompt_path"]}
    ignored_times = {synthetic_ignored_assignment["active_run_handoff_generated_at"]}
    history_prompt_paths = {str(item.get("active_run_handoff_prompt_path") or "") for item in verification_history}
    history_times = {str(item.get("active_run_handoff_generated_at") or "") for item in verification_history}

    assert ignored_prompt_paths.isdisjoint(history_prompt_paths)
    assert ignored_times.isdisjoint(history_times)
    for ignored_prompt_path in ignored_prompt_paths:
        run_id = Path(ignored_prompt_path).parts[-2]
        assert not any(run_id in item for item in completed_outputs)
        assert not any(run_id in item for item in proof_artifacts)
        assert not any(run_id in item for item in canonical_evidence)
    assert not any(
        item.startswith("/var/lib/codex-fleet/chummer_design_supervisor/")
        or item.startswith("/docker/fleet/state/chummer_design_supervisor/")
        for item in canonical_evidence
    )
    forbidden_retry_feedback_notes = sorted(
        [
            *ROOT.glob("feedback/2026-04-16-ea-governor-packets-*.md"),
            *ROOT.glob("feedback/2026-04-17-ea-governor-packets-*.md"),
        ]
    )
    assert forbidden_retry_feedback_notes == []


def test_terminal_policy_ignores_later_same_package_assignments_without_enumerating_them() -> None:
    handoff = _yaml(HANDOFF_CLOSEOUT_PATH)
    terminal_policy = dict(handoff.get("terminal_verification_policy") or {})
    ignored_assignment_rule = dict(terminal_policy.get("ignored_assignment_rule") or {})
    latest_allowed_timestamp_only = str(terminal_policy.get("latest_allowed_timestamp_only_verification_at") or "")
    later_same_package_assignment = {
        "package_id": "next90-m106-ea-governor-packets",
        "frontier_id": 1758984842,
        "generated_at": "2026-04-15T18:55:26Z",
        "prompt_path": (
            "/docker/fleet/state/chummer_design_supervisor/shard-12/runs/"
            "20260415T185515Z-shard-12/prompt.txt"
        ),
    }

    assert later_same_package_assignment["generated_at"] > latest_allowed_timestamp_only
    assert later_same_package_assignment["package_id"] == ignored_assignment_rule.get("package_id")
    assert later_same_package_assignment["frontier_id"] == int(ignored_assignment_rule.get("frontier_id") or 0)
    assert ignored_assignment_rule.get("action") == "ignore_without_manifest_append"
    assert "without appending per-handoff manifest rows" in str(
        terminal_policy.get("repeated_assignment_handling") or ""
    )
    assert (
        "unless an allowed reopen trigger below fires"
        in str(terminal_policy.get("repeated_assignment_handling") or "")
    )

    completed_outputs = {str(item) for item in handoff.get("completed_outputs") or []}
    proof_artifacts = {str(item) for item in handoff.get("proof_artifacts") or []}
    run_id = Path(later_same_package_assignment["prompt_path"]).parts[-2]
    assert not any(run_id in item for item in completed_outputs)
    assert not any(run_id in item for item in proof_artifacts)


def test_any_post_terminal_same_package_assignment_is_covered_without_new_note() -> None:
    handoff = _yaml(HANDOFF_CLOSEOUT_PATH)
    terminal_policy = dict(handoff.get("terminal_verification_policy") or {})
    ignored_assignment_rule = dict(terminal_policy.get("ignored_assignment_rule") or {})
    latest_allowed_timestamp_only = str(terminal_policy.get("latest_allowed_timestamp_only_verification_at") or "")
    same_package_assignment_after_terminal_closeout = {
        "package_id": "next90-m106-ea-governor-packets",
        "frontier_id": 1758984842,
        "generated_at": "2026-04-16T00:00:00Z",
        "prompt_path": (
            "/docker/fleet/state/chummer_design_supervisor/shard-12/runs/"
            "20260415T235900Z-shard-12/prompt.txt"
        ),
    }

    assert same_package_assignment_after_terminal_closeout["generated_at"] > latest_allowed_timestamp_only
    assert same_package_assignment_after_terminal_closeout["package_id"] == ignored_assignment_rule.get("package_id")
    assert same_package_assignment_after_terminal_closeout["frontier_id"] == int(
        ignored_assignment_rule.get("frontier_id") or 0
    )
    assert ignored_assignment_rule.get("action") == "ignore_without_manifest_append"
    assert ignored_assignment_rule.get("worker_safety_instruction_required") is True

    completed_outputs = {str(item) for item in handoff.get("completed_outputs") or []}
    proof_artifacts = {str(item) for item in handoff.get("proof_artifacts") or []}
    queue_item = _find_package(_yaml(QUEUE_STAGING_PATH))
    design_queue_item = _find_package(_yaml(DESIGN_QUEUE_STAGING_PATH))
    registry_task = _find_registry_task(_find_milestone(_yaml(CANONICAL_REGISTRY_PATH), 106), 106.2)
    canonical_evidence = [
        *[str(item) for item in queue_item.get("proof") or []],
        *[str(item) for item in design_queue_item.get("proof") or []],
        *[str(item) for item in registry_task.get("evidence") or []],
    ]
    run_id = Path(same_package_assignment_after_terminal_closeout["prompt_path"]).parts[-2]
    retry_helper_loop_guard = dict(terminal_policy.get("retry_helper_loop_guard") or {})
    assignment_context_pattern = dict(retry_helper_loop_guard.get("assignment_context_pattern") or {})
    example_current_retry_run_id = "20260417T201912Z-shard-12"

    assert not any(run_id in item for item in completed_outputs)
    assert not any(run_id in item for item in proof_artifacts)
    assert not any(run_id in item for item in canonical_evidence)
    assert retry_helper_loop_guard.get("required_startup_commands") is None
    assert retry_helper_loop_guard.get("current_retry_context") is None
    assert assignment_context_pattern.get("telemetry_path_pattern") == (
        "/docker/fleet/state/chummer_design_supervisor/shard-12/runs/*/TASK_LOCAL_TELEMETRY.generated.json"
    )
    assert assignment_context_pattern.get("first_commands_are_assignment_intake_not_proof") is True
    assert ignored_assignment_rule.get("action") == "ignore_without_manifest_append"
    assert terminal_policy.get("ignored_assignment_signals_after_terminal") == []
    assert not any(example_current_retry_run_id in item for item in completed_outputs)
    assert not any(example_current_retry_run_id in item for item in proof_artifacts)
    assert not any(example_current_retry_run_id in item for item in canonical_evidence)
    assert sorted(ROOT.glob("feedback/2026-04-17-ea-governor-packets-*.md")) == []


def test_canonical_registry_still_assigns_milestone_106_ea_synthesis_work() -> None:
    registry = _yaml(CANONICAL_REGISTRY_PATH)
    milestone = _find_milestone(registry, 106)

    assert milestone.get("status") == "in_progress"
    assert "executive-assistant" in set(milestone.get("owners") or [])
    assert {int(item) for item in milestone.get("dependencies") or []} == {101, 102, 103, 104, 105}
    registry_task = _find_registry_task(milestone, 106.2)
    assert registry_task.get("owner") == "executive-assistant"
    assert "Synthesize support, parity, and release signals" in str(registry_task.get("title") or "")


def test_pack_source_truth_files_exist_and_share_evidence_anchors() -> None:
    pack = _yaml(PACK_PATH)
    source_truth = {str(key): dict(value) for key, value in dict(pack.get("source_truth") or {}).items()}
    shared_anchors = set(pack.get("shared_evidence_anchor_ids") or [])
    truth_bundle = dict(pack.get("normalized_truth_bundle") or {})

    assert shared_anchors == {"weekly_pulse", "parity_lab_pack", "feedback_release_gate", "progress_email_workflow"}
    assert truth_bundle.get("bundle_id") == "ea-m106-governor-readiness-parity-support-release-v1"
    assert set(truth_bundle.get("consumer_surfaces") or []) == set(pack.get("owned_surfaces") or [])
    assert set(truth_bundle.get("input_anchor_ids") or []) == shared_anchors
    assert {
        "release_health",
        "flagship_readiness",
        "journey_gate_health",
        "support_closure",
        "parity_evidence",
        "reporter_followthrough",
        "release_channel_truth",
    } <= set(truth_bundle.get("required_signal_families") or [])
    assert "same bundle id" in str(truth_bundle.get("single_bundle_rule") or "")
    assert _source_path(source_truth["canonical_successor_queue"]).resolve() == QUEUE_STAGING_PATH.resolve()
    assert _source_path(source_truth["design_successor_queue"]).resolve() == DESIGN_QUEUE_STAGING_PATH.resolve()
    assert "Fleet-published queue mirror" in str(source_truth["canonical_successor_queue"].get("use_rule") or "")
    assert "design-owned successor queue source" in str(source_truth["design_successor_queue"].get("use_rule") or "")
    for key, row in source_truth.items():
        if row.get("required") is True:
            assert _source_path(row).exists(), key

    assert set(pack["operator_packet"]["evidence_anchor_ids"]) == shared_anchors
    assert set(pack["reporter_followthrough"]["evidence_anchor_ids"]) == shared_anchors
    assert pack["operator_packet"]["truth_bundle_id"] == truth_bundle["bundle_id"]
    assert pack["reporter_followthrough"]["truth_bundle_id"] == truth_bundle["bundle_id"]


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
    specimens = _yaml(SPECIMENS_PATH)
    handoff = _yaml(HANDOFF_CLOSEOUT_PATH)
    queue_item = _find_package(_yaml(QUEUE_STAGING_PATH))
    design_queue_item = _find_package(_yaml(DESIGN_QUEUE_STAGING_PATH))
    registry_task = _find_registry_task(_find_milestone(_yaml(CANONICAL_REGISTRY_PATH), 106), 106.2)
    runtime_safety = dict(pack.get("runtime_safety") or {})
    forbidden_proof_output_markers = {
        "task_local_telemetry.generated.json",
        "operator telemetry stdout",
        "operator telemetry stderr",
        "active-run helper stdout",
        "active-run helper stderr",
        "active-run helper command output",
        "run-helper output",
        "helper command receipt",
        "telemetry command receipt",
    }

    assert runtime_safety.get("do_not_invoke_operator_telemetry_or_active_run_helpers") is True
    assert runtime_safety.get("active_run_helper_commands_invoked") == []
    assert runtime_safety.get("operator_telemetry_commands_invoked") == []
    assert dict(specimens.get("runtime_safety") or {}).get("active_run_helper_commands_invoked") == []
    assert dict(specimens.get("runtime_safety") or {}).get("operator_telemetry_commands_invoked") == []
    assert dict(handoff.get("runtime_safety") or {}).get("active_run_helper_commands_invoked") == []
    assert dict(handoff.get("runtime_safety") or {}).get("operator_telemetry_commands_invoked") == []

    handoff_proof_strings = _strings(
        _without_keys(
            handoff,
            {"required_startup_commands", "current_retry_context", "assignment_context_pattern"},
        )
    )
    canonical_and_local_proof_strings = [
        *_strings(pack),
        *_strings(specimens),
        *handoff_proof_strings,
        *[str(item) for item in queue_item.get("proof") or []],
        *[str(item) for item in design_queue_item.get("proof") or []],
        *[str(item) for item in registry_task.get("evidence") or []],
    ]
    assert not any(
        marker in item.lower()
        for item in canonical_and_local_proof_strings
        for marker in forbidden_proof_output_markers
    )


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
    pack_truth_bundle = dict(pack.get("normalized_truth_bundle") or {})
    specimen_truth_bundle = dict(specimens.get("normalized_truth_bundle") or {})
    assert specimens.get("package_id") == pack.get("package_id")
    assert int(specimens.get("milestone_id") or 0) == int(pack.get("milestone_id") or 0)
    assert set(specimens.get("shared_evidence_anchor_ids") or []) == shared_anchors
    assert set(dict(specimens.get("shared_evidence_bindings") or {})) == shared_anchors
    assert specimen_truth_bundle.get("bundle_id") == pack_truth_bundle.get("bundle_id")
    assert set(specimen_truth_bundle.get("input_anchor_ids") or []) == shared_anchors
    assert set(specimen_truth_bundle.get("projected_signal_families") or []) == set(
        pack_truth_bundle.get("required_signal_families") or []
    )
    assert "same truth_bundle_id" in str(specimen_truth_bundle.get("use_rule") or "")
    assert specimens["operator_packet_specimen"]["packet_kind"] == "operator_packets:weekly_governor"
    assert specimens["reporter_followthrough_specimen"]["packet_kind"] == "reporter_followthrough:release_truth"
    assert specimens["operator_packet_specimen"]["truth_bundle_id"] == pack_truth_bundle["bundle_id"]
    assert specimens["reporter_followthrough_specimen"]["truth_bundle_id"] == pack_truth_bundle["bundle_id"]
    assert (
        specimens["operator_packet_specimen"]["specimen_payload"]["truth_bundle_id"]
        == specimens["reporter_followthrough_specimen"]["truth_bundle_id"]
    )
    assert set(specimens["operator_packet_specimen"]["specimen_payload"]["cited_signal_ids"]) == shared_anchors
    assert set(specimens["reporter_followthrough_specimen"]["source_signal_ids"]) == shared_anchors
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
