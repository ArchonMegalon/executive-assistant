from __future__ import annotations

from pathlib import Path
import re
import subprocess

import yaml


ROOT = Path(__file__).resolve().parents[1]
PACK_PATH = ROOT / "docs" / "chummer5a_parity_lab" / "CHUMMER5A_PARITY_LAB_PACK.yaml"
ORACLE_BASELINES_PATH = ROOT / "docs" / "chummer5a_parity_lab" / "oracle_baselines.yaml"
WORKFLOW_PACK_PATH = ROOT / "docs" / "chummer5a_parity_lab" / "veteran_workflow_pack.yaml"
COMPARE_PACKS_PATH = ROOT / "docs" / "chummer5a_parity_lab" / "compare_packs.yaml"
FIXTURE_INVENTORY_PATH = ROOT / "docs" / "chummer5a_parity_lab" / "import_export_fixture_inventory.yaml"
HANDOFF_CLOSEOUT_PATH = ROOT / "docs" / "chummer5a_parity_lab" / "SUCCESSOR_HANDOFF_CLOSEOUT.yaml"
PUBLISHED_PACK_PATH = ROOT / ".codex-studio" / "published" / "CHUMMER5A_PARITY_ORACLE_PACK.generated.json"
PARITY_ORACLE_PATH = Path("/docker/chummer5a/docs/PARITY_ORACLE.json")
ACTIVE_RUN_HANDOFF_PATH = Path("/var/lib/codex-fleet/chummer_design_supervisor/shard-3/ACTIVE_RUN_HANDOFF.generated.md")
VETERAN_GATE_PATH = Path("/docker/chummercomplete/chummer-design/products/chummer/VETERAN_FIRST_MINUTE_GATE.yaml")
FLAGSHIP_PARITY_REGISTRY_PATH = Path("/docker/chummercomplete/chummer-design/products/chummer/FLAGSHIP_PARITY_REGISTRY.yaml")
SUCCESSOR_REGISTRY_PATH = Path("/docker/chummercomplete/chummer-design/products/chummer/NEXT_90_DAY_PRODUCT_ADVANCE_REGISTRY.yaml")
DESIGN_SUCCESSOR_QUEUE_PATH = Path("/docker/chummercomplete/chummer-design/products/chummer/NEXT_90_DAY_QUEUE_STAGING.generated.yaml")
SUCCESSOR_QUEUE_PATH = Path("/docker/fleet/.codex-studio/published/NEXT_90_DAY_QUEUE_STAGING.generated.yaml")
FLAGSHIP_READINESS_PATH = Path("/docker/fleet/.codex-studio/published/FLAGSHIP_PRODUCT_READINESS.generated.json")
FEEDBACK_CLOSEOUT_PATH = ROOT / "feedback" / "2026-04-14-chummer5a-parity-lab-package-closeout.md"


def _yaml(path: Path) -> dict:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return payload if isinstance(payload, dict) else {}


def _active_handoff_generated_at() -> str:
    text = ACTIVE_RUN_HANDOFF_PATH.read_text(encoding="utf-8")
    match = re.search(r"^Generated at:\s*(\S+)", text, re.MULTILINE)
    assert match, "active handoff missing generated-at timestamp"
    return match.group(1)


def _active_handoff_prompt_text() -> str:
    text = ACTIVE_RUN_HANDOFF_PATH.read_text(encoding="utf-8")
    match = re.search(r"^- Prompt path:\s*(\S+)", text, re.MULTILINE)
    assert match, "active handoff missing prompt path"
    prompt_path = Path(match.group(1))
    assert prompt_path.exists(), str(prompt_path)
    return prompt_path.read_text(encoding="utf-8")


def test_pack_contract_tracks_milestone_and_owned_surfaces() -> None:
    pack = _yaml(PACK_PATH)

    assert pack.get("contract_name") == "ea.chummer5a_parity_lab_pack"
    assert pack.get("package_id") == "next90-m103-ea-parity-lab"
    assert int(pack.get("milestone_id") or 0) == 103
    assert pack.get("status") == "task_proven"
    assert list(pack.get("owned_surfaces") or []) == ["parity_lab:capture", "veteran_compare_packs"]


def test_pack_contract_matches_canonical_successor_registry_and_queue() -> None:
    pack = _yaml(PACK_PATH)
    registry = _yaml(SUCCESSOR_REGISTRY_PATH)
    design_queue = _yaml(DESIGN_SUCCESSOR_QUEUE_PATH)
    queue = _yaml(SUCCESSOR_QUEUE_PATH)

    milestones = {int(dict(item).get("id") or 0): dict(item) for item in (registry.get("milestones") or [])}
    milestone = milestones[103]
    assert milestone.get("title") == "Chummer5a parity lab and veteran migration certification"
    assert milestone.get("wave") == "W7"
    assert "executive-assistant" in set(milestone.get("owners") or [])
    assert 101 in set(milestone.get("dependencies") or [])
    assert 102 in set(milestone.get("dependencies") or [])
    task_103_1 = next(dict(task) for task in (milestone.get("work_tasks") or []) if dict(task).get("id") == 103.1)
    assert task_103_1.get("owner") == "executive-assistant"
    assert task_103_1.get("status") == "complete"
    task_evidence = "\n".join(str(item) for item in (task_103_1.get("evidence") or []))
    assert "CHUMMER5A_PARITY_LAB_PACK.yaml reports status=task_proven" in task_evidence
    assert "SUCCESSOR_HANDOFF_CLOSEOUT.yaml reports status=ea_scope_complete" in task_evidence
    assert "python tests/test_chummer5a_parity_lab_pack.py exits with ran=15 failed=0" in task_evidence

    queue_items = {str(dict(item).get("package_id") or ""): dict(item) for item in (queue.get("items") or [])}
    queue_item = queue_items["next90-m103-ea-parity-lab"]
    assert queue.get("source_design_queue_path") == DESIGN_SUCCESSOR_QUEUE_PATH.as_posix()
    assert queue_item.get("repo") == "executive-assistant"
    assert queue_item.get("status") == "complete"
    assert int(queue_item.get("frontier_id") or 0) == 4287684466
    assert int(queue_item.get("milestone_id") or 0) == int(pack.get("milestone_id") or 0)
    assert queue_item.get("wave") == milestone.get("wave")
    assert list(queue_item.get("allowed_paths") or []) == ["skills", "tests", "feedback", "docs"]
    assert list(queue_item.get("owned_surfaces") or []) == list(pack.get("owned_surfaces") or [])
    assert queue_item.get("title") == "Extract Chummer5a oracle baselines and veteran workflow packs"
    proof = set(str(item) for item in (queue_item.get("proof") or []))
    assert {
        "/docker/EA/docs/chummer5a_parity_lab/CHUMMER5A_PARITY_LAB_PACK.yaml",
        "/docker/EA/docs/chummer5a_parity_lab/SUCCESSOR_HANDOFF_CLOSEOUT.yaml",
        "/docker/EA/.codex-studio/published/CHUMMER5A_PARITY_ORACLE_PACK.generated.json",
        "python tests/test_chummer5a_parity_lab_pack.py",
    } <= proof
    for proof_anchor in proof:
        if proof_anchor.startswith("/docker/EA/"):
            assert Path(proof_anchor).exists(), proof_anchor

    design_queue_items = {str(dict(item).get("package_id") or ""): dict(item) for item in (design_queue.get("items") or [])}
    design_queue_item = design_queue_items["next90-m103-ea-parity-lab"]
    assert design_queue_item.get("repo") == queue_item.get("repo") == "executive-assistant"
    assert design_queue_item.get("status") == queue_item.get("status") == "complete"
    assert int(design_queue_item.get("frontier_id") or 0) == int(queue_item.get("frontier_id") or 0) == 4287684466
    assert int(design_queue_item.get("milestone_id") or 0) == int(queue_item.get("milestone_id") or 0) == 103
    assert design_queue_item.get("wave") == queue_item.get("wave") == "W7"
    assert list(design_queue_item.get("allowed_paths") or []) == list(queue_item.get("allowed_paths") or [])
    assert list(design_queue_item.get("owned_surfaces") or []) == list(queue_item.get("owned_surfaces") or [])
    design_proof = set(str(item) for item in (design_queue_item.get("proof") or []))
    assert {
        "/docker/EA/docs/chummer5a_parity_lab/CHUMMER5A_PARITY_LAB_PACK.yaml",
        "/docker/EA/docs/chummer5a_parity_lab/SUCCESSOR_HANDOFF_CLOSEOUT.yaml",
        "/docker/EA/.codex-studio/published/CHUMMER5A_PARITY_ORACLE_PACK.generated.json",
        "python tests/test_chummer5a_parity_lab_pack.py",
    } <= design_proof


def test_pack_required_outputs_exist_on_disk() -> None:
    pack = _yaml(PACK_PATH)
    outputs = dict(pack.get("required_outputs") or {})

    expected = {
        "screenshot_corpora": ORACLE_BASELINES_PATH,
        "workflow_maps": WORKFLOW_PACK_PATH,
        "compare_packs": COMPARE_PACKS_PATH,
        "import_export_fixture_inventory": FIXTURE_INVENTORY_PATH,
    }
    for key, path in expected.items():
        row = dict(outputs.get(key) or {})
        assert row.get("present") is True
        assert row.get("path") == path.relative_to(ROOT).as_posix()
        assert path.exists(), str(path)
        assert row.get("proof_level")


def test_published_parity_oracle_receipt_matches_task_proven_pack() -> None:
    pack = _yaml(PACK_PATH)
    receipt = _yaml(PUBLISHED_PACK_PATH)

    assert receipt.get("contract_name") == "ea.chummer5a_parity_oracle_pack"
    assert receipt.get("package_id") == pack.get("package_id") == "next90-m103-ea-parity-lab"
    assert int(receipt.get("milestone_id") or 0) == int(pack.get("milestone_id") or 0) == 103
    assert receipt.get("status") == pack.get("status") == "task_proven"
    assert list(receipt.get("owned_surfaces") or []) == list(pack.get("owned_surfaces") or [])

    outputs = dict(receipt.get("outputs") or {})
    assert outputs == {
        "screenshot_corpora": True,
        "workflow_maps": True,
        "compare_packs": True,
        "import_export_fixture_inventory": True,
    }
    output_paths = dict(receipt.get("output_paths") or {})
    assert output_paths == {
        "screenshot_corpora": ORACLE_BASELINES_PATH.relative_to(ROOT).as_posix(),
        "workflow_maps": WORKFLOW_PACK_PATH.relative_to(ROOT).as_posix(),
        "compare_packs": COMPARE_PACKS_PATH.relative_to(ROOT).as_posix(),
        "import_export_fixture_inventory": FIXTURE_INVENTORY_PATH.relative_to(ROOT).as_posix(),
        "handoff_closeout": HANDOFF_CLOSEOUT_PATH.relative_to(ROOT).as_posix(),
    }
    for output_path in output_paths.values():
        assert (ROOT / str(output_path)).exists(), output_path
    assert receipt.get("blocking_reasons") == []
    assert receipt.get("current_limitations") == []
    assert "promoted-head certification remains delegated" in str(receipt.get("operator_summary") or "")
    proof = dict(receipt.get("proof") or {})
    assert proof.get("command") == "python tests/test_chummer5a_parity_lab_pack.py"
    assert proof.get("result") == "ran=16 failed=0"

    successor_closure = dict(receipt.get("successor_closure") or {})
    assert int(successor_closure.get("successor_frontier_id") or 0) == 4287684466
    assert successor_closure.get("registry") == SUCCESSOR_REGISTRY_PATH.as_posix()
    assert successor_closure.get("design_queue") == DESIGN_SUCCESSOR_QUEUE_PATH.as_posix()
    assert successor_closure.get("fleet_queue") == SUCCESSOR_QUEUE_PATH.as_posix()
    assert successor_closure.get("active_handoff_min_generated_at") >= "2026-04-15T14:32:18Z"
    receipt_proof_commits = [str(commit) for commit in (successor_closure.get("local_proof_commits") or [])]
    assert {
        "f3a3649",
        "528c278",
        "98313c9",
        "5d56f66",
        "4e6b1d8",
        "357ee65",
        "d3f164c",
        "9cd70ea",
        "b880b75",
        "4dda75d",
        "466d7e4",
        "6ed29ce",
        "76a3acc",
        "c83eca2",
        "a57fc43",
        "f244a62",
        "7b7da3e",
        "945ed7b",
        "ac84501",
        "1dfb104",
        "dfdfa45",
        "e1289e7",
        "e8ec699",
        "48ae7bc",
        "c28df5a",
        "e706014",
        "87ad539",
        "4d186b6",
        "d274b66",
        "1783ee6",
    } <= set(receipt_proof_commits)
    for commit in receipt_proof_commits:
        subprocess.run(
            ["git", "-C", str(ROOT), "cat-file", "-e", f"{commit}^{{commit}}"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    proof_hygiene = dict(successor_closure.get("proof_hygiene") or {})
    assert proof_hygiene.get("operator_owned_run_helpers_invoked") is False
    assert proof_hygiene.get("operator_owned_helper_output_cited") is False

    terminal_policy = dict(successor_closure.get("terminal_verification_policy") or {})
    assert terminal_policy.get("status") == "terminal_for_ea_scope"
    assert terminal_policy.get("latest_required_handoff_floor") == "2026-04-15T16:20:33Z"
    assert terminal_policy.get("no_timestamp_chasing_required") is True
    assert terminal_policy.get("no_operator_helper_evidence_allowed") is True
    assert terminal_policy.get("closed_scope_guard_test") == "test_terminal_verification_policy_stops_timestamp_chasing"
    assert set(str(item) for item in (terminal_policy.get("allowed_next_work") or [])) == {
        "next90-m103-ui-veteran-certification",
        "next90-m103-design-parity-ladder",
        "next90-m103-fleet-readiness-consumption",
    }
    current_or_newer_rule = str(terminal_policy.get("current_or_newer_handoff_rule") or "")
    assert "assignment context only" in current_or_newer_rule
    assert "not a reason to edit this EA package" in current_or_newer_rule
    assert "direct proof command" in current_or_newer_rule


def test_successor_handoff_closeout_prevents_repeating_ea_scope() -> None:
    pack = _yaml(PACK_PATH)
    closeout = _yaml(HANDOFF_CLOSEOUT_PATH)
    registry = _yaml(SUCCESSOR_REGISTRY_PATH)
    design_queue = _yaml(DESIGN_SUCCESSOR_QUEUE_PATH)
    queue = _yaml(SUCCESSOR_QUEUE_PATH)

    assert closeout.get("contract_name") == "ea.chummer5a_parity_lab_successor_handoff_closeout"
    assert closeout.get("package_id") == pack.get("package_id") == "next90-m103-ea-parity-lab"
    assert int(closeout.get("milestone_id") or 0) == int(pack.get("milestone_id") or 0) == 103
    assert closeout.get("status") == "ea_scope_complete"
    assert set(closeout.get("closed_surfaces") or []) == set(pack.get("owned_surfaces") or [])

    local_proof_commits = [dict(item) for item in (closeout.get("local_proof_commits") or [])]
    assert local_proof_commits
    for proof_commit in local_proof_commits:
        commit = str(proof_commit.get("commit") or "")
        assert re.fullmatch(r"[0-9a-f]{7,40}", commit), commit
        assert str(proof_commit.get("subject") or "").strip()
        assert str(proof_commit.get("purpose") or "").strip()
        subprocess.run(
            ["git", "-C", str(ROOT), "cat-file", "-e", f"{commit}^{{commit}}"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    closure_scope = dict(closeout.get("closure_scope") or {})
    assert closure_scope.get("allowed_paths") == ["skills", "tests", "feedback", "docs"]
    assert closure_scope.get("package_only") is True
    assert closure_scope.get("closed_package_only") == "next90-m103-ea-parity-lab"
    assert set(closure_scope.get("forbidden_reopen_targets") or []) == {
        "flagship_closeout_wave",
        "promoted_head_veteran_certification",
    }

    completed_outputs = {ROOT / str(path) for path in (closeout.get("completed_outputs") or [])}
    assert {
        PACK_PATH,
        ORACLE_BASELINES_PATH,
        WORKFLOW_PACK_PATH,
        COMPARE_PACKS_PATH,
        FIXTURE_INVENTORY_PATH,
        HANDOFF_CLOSEOUT_PATH,
        PUBLISHED_PACK_PATH,
    } <= completed_outputs
    for path in completed_outputs:
        assert path.exists(), str(path)

    proof = dict(closeout.get("proof") or {})
    assert proof.get("command") == "python tests/test_chummer5a_parity_lab_pack.py"
    assert proof.get("result") == "ran=16 failed=0"

    repeat_verifications = [dict(item) for item in (closeout.get("repeat_verifications") or [])]
    assert repeat_verifications
    latest_repeat = repeat_verifications[-1]
    assert latest_repeat.get("verified_at") >= proof.get("verified_at")
    assert _active_handoff_generated_at() >= str(latest_repeat.get("active_handoff_generated_at") or "")
    assert int(latest_repeat.get("frontier_id") or 0) == 4287684466
    assert latest_repeat.get("package_id") == pack.get("package_id")
    assert latest_repeat.get("result") == "registry=complete design_queue=assigned fleet_queue=complete proof=ran=16 failed=0 local_proof_commit=d274b66"
    assert "do not recapture parity-lab artifacts" in str(latest_repeat.get("worker_rule") or "")
    assert "at-least-this-new active handoff" in str(latest_repeat.get("worker_rule") or "")
    assert "design-owned queue assignment" in str(latest_repeat.get("worker_rule") or "")
    assert "Fleet completed queue mirror" in str(latest_repeat.get("worker_rule") or "")
    assert "direct proof command" in str(latest_repeat.get("worker_rule") or "")
    assert "resolving local handoff proof commit d274b66" in str(latest_repeat.get("worker_rule") or "")
    assert "invoke operator-owned run helpers" in str(latest_repeat.get("worker_rule") or "")
    assert "cite operator-owned helper output" in str(latest_repeat.get("worker_rule") or "")

    closure_markers = dict(closeout.get("canonical_closure_markers") or {})
    assert closure_markers.get("successor_registry_work_task") == "103.1 status=complete"
    assert closure_markers.get("design_queue_completed_package") == "next90-m103-ea-parity-lab status=complete frontier=4287684466"
    assert closure_markers.get("queue_package") == "next90-m103-ea-parity-lab status=complete"
    assert closure_markers.get("queue_proof_command") == "python tests/test_chummer5a_parity_lab_pack.py"
    assert closure_markers.get("active_handoff_frontier") == "4287684466 focused_package=next90-m103-ea-parity-lab"

    canonical_sources = dict(closeout.get("canonical_successor_sources") or {})
    assert canonical_sources.get("design_queue") == DESIGN_SUCCESSOR_QUEUE_PATH.as_posix()
    assert canonical_sources.get("active_run_handoff") == ACTIVE_RUN_HANDOFF_PATH.as_posix()
    active_handoff_text = ACTIVE_RUN_HANDOFF_PATH.read_text(encoding="utf-8")
    active_prompt_text = _active_handoff_prompt_text()
    assert "Mode: successor_wave" in active_handoff_text
    assert "Frontier ids: 4287684466" in active_handoff_text
    assert "next90-m103-ea-parity-lab" in active_handoff_text
    assert "Extract Chummer5a oracle baselines and veteran workflow packs" in active_handoff_text
    assert '"package_id": "next90-m103-ea-parity-lab"' in active_prompt_text
    assert '"parity_lab:capture"' in active_prompt_text
    assert '"veteran_compare_packs"' in active_prompt_text
    assert "do not reopen the closed flagship wave" in active_prompt_text

    repeat_prevention = dict(closeout.get("repeat_prevention") or {})
    assert int(repeat_prevention.get("successor_frontier_id") or 0) == 4287684466
    assert repeat_prevention.get("active_handoff_verified_at") == latest_repeat.get("verified_at")
    assert repeat_prevention.get("active_handoff_min_generated_at") == latest_repeat.get("active_handoff_generated_at")
    assert _active_handoff_generated_at() >= str(repeat_prevention.get("active_handoff_min_generated_at") or "")
    assert repeat_prevention.get("active_handoff_focus_required") == "next90-m103-ea-parity-lab"
    assert repeat_prevention.get("active_handoff_owned_surfaces_required") == [
        "parity_lab:capture",
        "veteran_compare_packs",
    ]
    assert repeat_prevention.get("registry_task_status_required") == "complete"
    assert repeat_prevention.get("design_queue_completed_package_required") == "next90-m103-ea-parity-lab status=complete frontier=4287684466"
    assert repeat_prevention.get("queue_package_status_required") == "complete"
    assert repeat_prevention.get("repeat_guard_test") == "test_successor_handoff_closeout_prevents_repeating_ea_scope"
    assert repeat_prevention.get("blocked_helper_guard_test") == "test_successor_closeout_does_not_use_active_run_helper_commands"
    assert repeat_prevention.get("local_proof_commit_guard_test") == "test_successor_handoff_closeout_prevents_repeating_ea_scope"
    assert "delegated non-EA follow-up packages" in str(repeat_prevention.get("worker_rule") or "")

    milestones = {int(dict(item).get("id") or 0): dict(item) for item in (registry.get("milestones") or [])}
    task_103_1 = next(dict(task) for task in (milestones[103].get("work_tasks") or []) if dict(task).get("id") == 103.1)
    assert task_103_1.get("status") == repeat_prevention.get("registry_task_status_required") == "complete"

    queue_items = {str(dict(item).get("package_id") or ""): dict(item) for item in (queue.get("items") or [])}
    queue_item = queue_items["next90-m103-ea-parity-lab"]
    assert int(queue_item.get("frontier_id") or 0) == int(repeat_prevention.get("successor_frontier_id") or 0)
    assert queue_item.get("status") == repeat_prevention.get("queue_package_status_required") == "complete"

    design_queue_items = {str(dict(item).get("package_id") or ""): dict(item) for item in (design_queue.get("items") or [])}
    design_queue_item = design_queue_items["next90-m103-ea-parity-lab"]
    assert int(design_queue_item.get("frontier_id") or 0) == int(repeat_prevention.get("successor_frontier_id") or 0)
    assert design_queue_item.get("status") == queue_item.get("status") == "complete"
    assert list(design_queue_item.get("allowed_paths") or []) == ["skills", "tests", "feedback", "docs"]
    assert list(design_queue_item.get("owned_surfaces") or []) == [
        "parity_lab:capture",
        "veteran_compare_packs",
    ]

    remaining = {str(dict(item).get("owner") or "") for item in (closeout.get("remaining_non_ea_work") or [])}
    assert "executive-assistant" not in remaining
    assert {"chummer6-ui", "chummer6-design", "fleet"} <= remaining

    anti_reopen_rules = "\n".join(str(item) for item in (closeout.get("anti_reopen_rules") or []))
    assert "Do not reopen the closed flagship closeout wave" in anti_reopen_rules
    assert "promoted-head screenshot certification" in anti_reopen_rules


def test_successor_handoff_closeout_outputs_stay_inside_assigned_scope() -> None:
    closeout = _yaml(HANDOFF_CLOSEOUT_PATH)
    closure_scope = dict(closeout.get("closure_scope") or {})
    allowed_roots = tuple(f"{root}/" for root in (closure_scope.get("allowed_paths") or []))

    assert allowed_roots == ("skills/", "tests/", "feedback/", "docs/")
    for output in closeout.get("completed_outputs") or []:
        output_path = str(output)
        assert (
            output_path.startswith(allowed_roots)
            or output_path == PUBLISHED_PACK_PATH.relative_to(ROOT).as_posix()
        ), output_path


def test_terminal_verification_policy_stops_timestamp_chasing() -> None:
    closeout = _yaml(HANDOFF_CLOSEOUT_PATH)
    repeat_prevention = dict(closeout.get("repeat_prevention") or {})
    terminal_policy = dict(closeout.get("terminal_verification_policy") or {})

    assert terminal_policy.get("status") == "terminal_for_ea_scope"
    assert terminal_policy.get("latest_required_handoff_floor") == repeat_prevention.get(
        "active_handoff_min_generated_at"
    )
    assert _active_handoff_generated_at() >= str(terminal_policy.get("latest_required_handoff_floor") or "")
    assert terminal_policy.get("no_timestamp_chasing_required") is True
    assert terminal_policy.get("no_operator_helper_evidence_allowed") is True
    assert terminal_policy.get("closed_scope_guard_test") == "test_terminal_verification_policy_stops_timestamp_chasing"

    current_or_newer_rule = str(terminal_policy.get("current_or_newer_handoff_rule") or "")
    assert "assignment context only" in current_or_newer_rule
    assert "not a reason to edit this EA package" in current_or_newer_rule
    assert "canonical registry" in current_or_newer_rule
    assert "direct proof command" in current_or_newer_rule
    assert "green" in current_or_newer_rule

    allowed_next_work = set(str(item) for item in (terminal_policy.get("allowed_next_work") or []))
    assert allowed_next_work == {
        "next90-m103-ui-veteran-certification",
        "next90-m103-design-parity-ladder",
        "next90-m103-fleet-readiness-consumption",
    }


def test_successor_closeout_does_not_use_active_run_helper_commands() -> None:
    closeout = _yaml(HANDOFF_CLOSEOUT_PATH)
    receipt = _yaml(PUBLISHED_PACK_PATH)
    pack = _yaml(PACK_PATH)
    registry = _yaml(SUCCESSOR_REGISTRY_PATH)
    design_queue = _yaml(DESIGN_SUCCESSOR_QUEUE_PATH)
    queue = _yaml(SUCCESSOR_QUEUE_PATH)

    combined = "\n".join(
        [
            HANDOFF_CLOSEOUT_PATH.read_text(encoding="utf-8"),
            PUBLISHED_PACK_PATH.read_text(encoding="utf-8"),
            PACK_PATH.read_text(encoding="utf-8"),
        ]
    )
    blocked_markers = [
        "TASK_LOCAL_TELEMETRY",
        "operator telemetry",
        "active-run helper",
        "active run helper",
        "ooda",
        "telemetry helper",
    ]
    for marker in blocked_markers:
        assert marker.lower() not in combined.lower(), marker

    proof_command = str(dict(closeout.get("proof") or {}).get("command") or "")
    receipt_command = str(dict(receipt.get("proof") or {}).get("command") or "")
    assert proof_command == receipt_command == "python tests/test_chummer5a_parity_lab_pack.py"
    assert dict(pack.get("readiness_evidence") or {}).get("flagship_readiness_status") == "pass"

    milestones = {int(dict(item).get("id") or 0): dict(item) for item in (registry.get("milestones") or [])}
    task_103_1 = next(dict(task) for task in (milestones[103].get("work_tasks") or []) if dict(task).get("id") == 103.1)
    design_queue_items = {str(dict(item).get("package_id") or ""): dict(item) for item in (design_queue.get("items") or [])}
    queue_items = {str(dict(item).get("package_id") or ""): dict(item) for item in (queue.get("items") or [])}

    canonical_package_proof = "\n".join(
        str(item)
        for item in (
            list(task_103_1.get("evidence") or [])
            + list(design_queue_items["next90-m103-ea-parity-lab"].get("proof") or [])
            + list(queue_items["next90-m103-ea-parity-lab"].get("proof") or [])
        )
    )
    blocked_proof_markers = [
        "TASK_LOCAL_TELEMETRY",
        "ACTIVE_RUN_HANDOFF.generated.md",
        "/runs/",
        "active-run telemetry",
        "operator telemetry",
        "telemetry helper output",
        "operator-owned helper output",
    ]
    for marker in blocked_proof_markers:
        assert marker.lower() not in canonical_package_proof.lower(), marker


def test_pack_source_pointers_resolve_to_repo_local_evidence() -> None:
    pack = _yaml(PACK_PATH)
    source_repos = dict(pack.get("source_repos") or {})
    assert Path(str(source_repos.get("chummer5a") or "")).is_dir()
    assert Path(str(source_repos.get("chummer6_ui") or "")).is_dir()

    oracle_sources = dict(pack.get("oracle_sources") or {})
    for key in ("parity_oracle_json", "parity_checklist_md", "parity_audit_md"):
        path = Path(str(oracle_sources.get(key) or ""))
        assert path.exists(), f"{key}: {path}"

    baselines = _yaml(ORACLE_BASELINES_PATH)
    baseline_sources = dict(baselines.get("source") or {})
    assert Path(str(baseline_sources.get("parity_oracle_json") or "")).exists()
    assert Path(str(baseline_sources.get("parity_checklist_md") or "")).exists()
    assert Path(str(baseline_sources.get("parity_audit_md") or "")).exists()

    workflow = _yaml(WORKFLOW_PACK_PATH)
    workflow_sources = dict(workflow.get("source_of_truth") or {})
    assert Path(str(workflow_sources.get("veteran_gate") or "")).exists()
    assert Path(str(workflow_sources.get("flagship_parity_registry") or "")).exists()
    for path_text in workflow_sources.get("chummer5a_oracle") or []:
        path = Path(str(path_text))
        assert path.exists(), str(path)

    compare = _yaml(COMPARE_PACKS_PATH)
    compare_sources = dict(compare.get("source_of_truth") or {})
    assert Path(str(compare_sources.get("flagship_parity_registry") or "")).exists()
    assert Path(str(compare_sources.get("chummer5a_oracle") or "")).exists()

    fixture_inventory = _yaml(FIXTURE_INVENTORY_PATH)
    inventory_sources = dict(fixture_inventory.get("source_of_truth") or {})
    assert Path(str(inventory_sources.get("parity_oracle_json") or "")).exists()
    assert Path(str(inventory_sources.get("parity_checklist") or "")).exists()
    assert Path(str(inventory_sources.get("parity_audit") or "")).exists()


def test_pack_readiness_evidence_tracks_green_flagship_packet_without_reopening_closeout() -> None:
    pack = _yaml(PACK_PATH)
    readiness = _yaml(FLAGSHIP_READINESS_PATH)
    evidence = dict(pack.get("readiness_evidence") or {})
    completion_audit = dict(readiness.get("completion_audit") or {})
    external_host_proof = dict(readiness.get("external_host_proof") or {})

    assert evidence.get("flagship_readiness") == FLAGSHIP_READINESS_PATH.as_posix()
    assert evidence.get("flagship_readiness_status") == readiness.get("status") == "pass"
    assert evidence.get("flagship_readiness_generated_at") == readiness.get("generated_at")
    assert completion_audit.get("status") == "pass"
    assert int(completion_audit.get("unresolved_external_proof_request_count") or 0) == 0
    assert evidence.get("external_host_proof_status") == external_host_proof.get("status") == "pass"
    assert int(evidence.get("unresolved_external_host_proof_requests", -1)) == int(
        external_host_proof.get("unresolved_request_count", -1)
    ) == 0


def test_feedback_closeout_no_longer_carries_stale_host_proof_blocker() -> None:
    text = FEEDBACK_CLOSEOUT_PATH.read_text(encoding="utf-8")

    assert "still required before full `desktop_client` readiness can turn green" not in text
    assert "must not reopen the closed flagship wave" in text
    assert "zero unresolved external host-proof requests" in text


def test_screenshot_corpus_only_claims_files_that_exist() -> None:
    baselines = _yaml(ORACLE_BASELINES_PATH)
    corpus = dict(baselines.get("screenshot_corpora") or {})
    screenshot_root = Path(str(corpus.get("promoted_ui_screenshot_root") or ""))
    supplemental_root = Path(str(corpus.get("supplemental_finished_wave_screenshot_root") or ""))

    assert screenshot_root.exists(), str(screenshot_root)
    assert supplemental_root.exists(), str(supplemental_root)
    captured = [str(item) for item in (corpus.get("captured_screenshots") or [])]
    supplemental = [str(item) for item in (corpus.get("supplemental_finished_wave_screenshots") or [])]
    assert captured
    assert supplemental == ["16-master-index-dialog-light.png", "17-character-roster-dialog-light.png"]

    for filename in captured:
        assert (screenshot_root / filename).exists(), filename
    for filename in supplemental:
        assert (supplemental_root / filename).exists(), filename
    assert not set(captured).intersection(supplemental)


def test_desktop_non_negotiable_anchors_are_source_backed() -> None:
    baselines = _yaml(ORACLE_BASELINES_PATH)
    anchors = dict(baselines.get("desktop_non_negotiable_anchors") or {})
    assert anchors

    for anchor_id, anchor in anchors.items():
        row = dict(anchor or {})
        source_path = Path(str(row.get("source_path") or ""))
        assert source_path.exists(), f"{anchor_id}: {source_path}"
        source_text = source_path.read_text(encoding="utf-8")

        locators = list(row.get("locators") or [])
        if row.get("locator"):
            locators.append(str(row.get("locator")))
        assert locators, anchor_id
        for locator in locators:
            assert str(locator) in source_text, f"{anchor_id}: {locator}"


def test_veteran_workflow_pack_matches_required_landmarks_and_tasks() -> None:
    workflow = _yaml(WORKFLOW_PACK_PATH)
    gate = _yaml(VETERAN_GATE_PATH)

    required_landmarks = {str(item).strip() for item in (gate.get("required_landmarks") or []) if str(item).strip()}
    packed_landmarks = {str(item).strip() for item in (workflow.get("required_landmarks") or []) if str(item).strip()}
    assert required_landmarks <= packed_landmarks

    required_tasks = {str(dict(item).get("id") or "").strip() for item in (gate.get("tasks") or [])}
    packed_tasks = {str(dict(item).get("id") or "").strip() for item in (workflow.get("required_first_minute_tasks") or [])}
    assert required_tasks <= packed_tasks


def test_compare_packs_cover_all_flagship_parity_families() -> None:
    compare = _yaml(COMPARE_PACKS_PATH)
    registry = _yaml(FLAGSHIP_PARITY_REGISTRY_PATH)

    compare_families = {str(dict(item).get("id") or "").strip() for item in (compare.get("families") or [])}
    required_families = {str(dict(item).get("id") or "").strip() for item in (registry.get("families") or [])}
    assert required_families <= compare_families


def test_import_export_inventory_counts_match_parity_oracle() -> None:
    fixture_inventory = _yaml(FIXTURE_INVENTORY_PATH)
    parity_oracle = _yaml(PARITY_ORACLE_PATH)
    inventory = dict(fixture_inventory.get("inventory") or {})
    counts = dict(fixture_inventory.get("counts") or {})

    assert int(counts.get("tabs") or 0) == len(list(inventory.get("tab_fixture_ids") or [])) == len(list(parity_oracle.get("tabs") or []))
    assert int(counts.get("workspace_actions") or 0) == len(list(inventory.get("workspace_action_fixture_ids") or [])) == len(
        list(parity_oracle.get("workspaceActions") or [])
    )
    assert int(counts.get("desktop_controls") or 0) == len(list(inventory.get("desktop_control_fixture_ids") or [])) == len(
        list(parity_oracle.get("desktopControls") or [])
    )


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
