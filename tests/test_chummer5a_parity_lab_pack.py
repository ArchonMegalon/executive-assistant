from __future__ import annotations

from pathlib import Path

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
VETERAN_GATE_PATH = Path("/docker/chummercomplete/chummer-design/products/chummer/VETERAN_FIRST_MINUTE_GATE.yaml")
FLAGSHIP_PARITY_REGISTRY_PATH = Path("/docker/chummercomplete/chummer-design/products/chummer/FLAGSHIP_PARITY_REGISTRY.yaml")
SUCCESSOR_REGISTRY_PATH = Path("/docker/chummercomplete/chummer-design/products/chummer/NEXT_90_DAY_PRODUCT_ADVANCE_REGISTRY.yaml")
SUCCESSOR_QUEUE_PATH = Path("/docker/fleet/.codex-studio/published/NEXT_90_DAY_QUEUE_STAGING.generated.yaml")
FLAGSHIP_READINESS_PATH = Path("/docker/fleet/.codex-studio/published/FLAGSHIP_PRODUCT_READINESS.generated.json")
FEEDBACK_CLOSEOUT_PATH = ROOT / "feedback" / "2026-04-14-chummer5a-parity-lab-package-closeout.md"


def _yaml(path: Path) -> dict:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return payload if isinstance(payload, dict) else {}


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
    assert "python tests/test_chummer5a_parity_lab_pack.py exits with ran=14 failed=0" in task_evidence

    queue_items = {str(dict(item).get("package_id") or ""): dict(item) for item in (queue.get("items") or [])}
    queue_item = queue_items["next90-m103-ea-parity-lab"]
    assert queue_item.get("repo") == "executive-assistant"
    assert queue_item.get("status") == "complete"
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
    assert receipt.get("blocking_reasons") == []
    assert receipt.get("current_limitations") == []
    assert "promoted-head certification remains delegated" in str(receipt.get("operator_summary") or "")
    proof = dict(receipt.get("proof") or {})
    assert proof.get("command") == "python tests/test_chummer5a_parity_lab_pack.py"
    assert proof.get("result") == "ran=14 failed=0"


def test_successor_handoff_closeout_prevents_repeating_ea_scope() -> None:
    pack = _yaml(PACK_PATH)
    closeout = _yaml(HANDOFF_CLOSEOUT_PATH)
    registry = _yaml(SUCCESSOR_REGISTRY_PATH)
    queue = _yaml(SUCCESSOR_QUEUE_PATH)

    assert closeout.get("contract_name") == "ea.chummer5a_parity_lab_successor_handoff_closeout"
    assert closeout.get("package_id") == pack.get("package_id") == "next90-m103-ea-parity-lab"
    assert int(closeout.get("milestone_id") or 0) == int(pack.get("milestone_id") or 0) == 103
    assert closeout.get("status") == "ea_scope_complete"
    assert set(closeout.get("closed_surfaces") or []) == set(pack.get("owned_surfaces") or [])

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
        PUBLISHED_PACK_PATH,
    } <= completed_outputs
    for path in completed_outputs:
        assert path.exists(), str(path)

    proof = dict(closeout.get("proof") or {})
    assert proof.get("command") == "python tests/test_chummer5a_parity_lab_pack.py"
    assert proof.get("result") == "ran=14 failed=0"

    closure_markers = dict(closeout.get("canonical_closure_markers") or {})
    assert closure_markers.get("successor_registry_work_task") == "103.1 status=complete"
    assert closure_markers.get("queue_package") == "next90-m103-ea-parity-lab status=complete"
    assert closure_markers.get("queue_proof_command") == "python tests/test_chummer5a_parity_lab_pack.py"

    repeat_prevention = dict(closeout.get("repeat_prevention") or {})
    assert int(repeat_prevention.get("successor_frontier_id") or 0) == 4287684466
    assert repeat_prevention.get("registry_task_status_required") == "complete"
    assert repeat_prevention.get("queue_package_status_required") == "complete"
    assert repeat_prevention.get("repeat_guard_test") == "test_successor_handoff_closeout_prevents_repeating_ea_scope"
    assert "delegated non-EA follow-up packages" in str(repeat_prevention.get("worker_rule") or "")

    milestones = {int(dict(item).get("id") or 0): dict(item) for item in (registry.get("milestones") or [])}
    task_103_1 = next(dict(task) for task in (milestones[103].get("work_tasks") or []) if dict(task).get("id") == 103.1)
    assert task_103_1.get("status") == repeat_prevention.get("registry_task_status_required") == "complete"

    queue_items = {str(dict(item).get("package_id") or ""): dict(item) for item in (queue.get("items") or [])}
    assert queue_items["next90-m103-ea-parity-lab"].get("status") == repeat_prevention.get(
        "queue_package_status_required"
    ) == "complete"

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
