from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
PACK_PATH = ROOT / "docs" / "chummer5a_parity_lab" / "CHUMMER5A_PARITY_LAB_PACK.yaml"
ORACLE_BASELINES_PATH = ROOT / "docs" / "chummer5a_parity_lab" / "oracle_baselines.yaml"
WORKFLOW_PACK_PATH = ROOT / "docs" / "chummer5a_parity_lab" / "veteran_workflow_pack.yaml"
COMPARE_PACKS_PATH = ROOT / "docs" / "chummer5a_parity_lab" / "compare_packs.yaml"
FIXTURE_INVENTORY_PATH = ROOT / "docs" / "chummer5a_parity_lab" / "import_export_fixture_inventory.yaml"
PARITY_ORACLE_PATH = Path("/docker/chummer5a/docs/PARITY_ORACLE.json")
VETERAN_GATE_PATH = Path("/docker/chummercomplete/chummer-design/products/chummer/VETERAN_FIRST_MINUTE_GATE.yaml")
FLAGSHIP_PARITY_REGISTRY_PATH = Path("/docker/chummercomplete/chummer-design/products/chummer/FLAGSHIP_PARITY_REGISTRY.yaml")
SUCCESSOR_REGISTRY_PATH = Path("/docker/chummercomplete/chummer-design/products/chummer/NEXT_90_DAY_PRODUCT_ADVANCE_REGISTRY.yaml")
SUCCESSOR_QUEUE_PATH = Path("/docker/fleet/.codex-studio/published/NEXT_90_DAY_QUEUE_STAGING.generated.yaml")


def _yaml(path: Path) -> dict:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return payload if isinstance(payload, dict) else {}


def test_pack_contract_tracks_milestone_and_owned_surfaces() -> None:
    pack = _yaml(PACK_PATH)

    assert pack.get("contract_name") == "ea.chummer5a_parity_lab_pack"
    assert pack.get("package_id") == "next90-m103-ea-parity-lab"
    assert int(pack.get("milestone_id") or 0) == 103
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
    assert any(dict(task).get("id") == 103.1 for task in (milestone.get("work_tasks") or []))

    queue_items = {str(dict(item).get("package_id") or ""): dict(item) for item in (queue.get("items") or [])}
    queue_item = queue_items["next90-m103-ea-parity-lab"]
    assert queue_item.get("repo") == "executive-assistant"
    assert int(queue_item.get("milestone_id") or 0) == int(pack.get("milestone_id") or 0)
    assert queue_item.get("wave") == milestone.get("wave")
    assert list(queue_item.get("allowed_paths") or []) == ["skills", "tests", "feedback", "docs"]
    assert list(queue_item.get("owned_surfaces") or []) == list(pack.get("owned_surfaces") or [])
    assert queue_item.get("title") == "Extract Chummer5a oracle baselines and veteran workflow packs"


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
