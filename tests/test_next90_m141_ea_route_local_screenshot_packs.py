from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "ea") not in sys.path:
    sys.path.insert(0, str(ROOT / "ea"))

from app.yaml_inputs import load_yaml_dict

PACK_PATH = ROOT / "docs" / "chummer5a_parity_lab" / "NEXT90_M141_ROUTE_LOCAL_SCREENSHOT_PACKS.generated.yaml"
MARKDOWN_PATH = ROOT / "docs" / "chummer5a_parity_lab" / "NEXT90_M141_ROUTE_LOCAL_SCREENSHOT_PACKS.generated.md"
FEEDBACK_PATH = ROOT / "feedback" / "2026-05-06-next90-m141-ea-route-local-screenshot-packs.md"
MATERIALIZER_PATH = ROOT / "scripts" / "materialize_next90_m141_ea_route_local_screenshot_packs.py"
VERIFY_PATH = ROOT / "scripts" / "verify_next90_m141_ea_route_local_screenshot_packs.py"
PARITY_LAB_PACK_PATH = ROOT / "docs" / "chummer5a_parity_lab" / "CHUMMER5A_PARITY_LAB_PACK.yaml"
QUEUE_STAGING_PATH = Path("/docker/fleet/.codex-studio/published/NEXT_90_DAY_QUEUE_STAGING.generated.yaml")
DESIGN_QUEUE_STAGING_PATH = Path("/docker/chummercomplete/chummer-design/products/chummer/NEXT_90_DAY_QUEUE_STAGING.generated.yaml")
SUCCESSOR_REGISTRY_PATH = Path("/docker/chummercomplete/chummer-design/products/chummer/NEXT_90_DAY_PRODUCT_ADVANCE_REGISTRY.yaml")


def _yaml(path: Path) -> dict:
    return load_yaml_dict(path)


def _materializer_module():
    spec = importlib.util.spec_from_file_location("ea_next90_m141_materializer", MATERIALIZER_PATH)
    assert spec is not None and spec.loader is not None, MATERIALIZER_PATH
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_materializer_rebuilds_current_generated_packet() -> None:
    module = _materializer_module()
    payload = _yaml(PACK_PATH)
    assert module.without_generated_at(payload) == module.without_generated_at(module.build_payload())


def test_direct_verifier_passes_against_current_packet() -> None:
    result = subprocess.run(
        [sys.executable, str(VERIFY_PATH)],
        check=False,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_packet_identity_and_scope() -> None:
    payload = _yaml(PACK_PATH)
    assert payload.get("contract_name") == "ea.next90_m141_route_local_screenshot_packs"
    assert payload.get("package_id") == "next90-m141-ea-compile-route-local-screenshot-packs-and-compare-packets-for-translator-x"
    assert int(payload.get("milestone_id") or 0) == 141
    assert payload.get("work_task_id") == "141.4"
    assert list(payload.get("owned_surfaces") or []) == ["compile_route_local_screenshot_packs_and_compare_packets:ea"]
    assert list(payload.get("allowed_paths") or []) == ["scripts", "feedback", "docs"]


def test_parity_lab_pack_manifest_lists_the_live_m141_receipt() -> None:
    pack = _yaml(PARITY_LAB_PACK_PATH)

    successor_receipts = [dict(item) for item in (pack.get("successor_wave_receipts") or [])]
    m141_receipts = [
        item
        for item in successor_receipts
        if str(item.get("package_id") or "")
        == "next90-m141-ea-compile-route-local-screenshot-packs-and-compare-packets-for-translator-x"
    ]
    assert len(m141_receipts) == 1, successor_receipts

    receipt = m141_receipts[0]
    assert int(receipt.get("milestone_id") or 0) == 141
    assert str(receipt.get("work_task_id") or "") == "141.4"
    assert str(receipt.get("status") or "") == "generated_packet_only"
    assert list(receipt.get("owned_surfaces") or []) == [
        "compile_route_local_screenshot_packs_and_compare_packets:ea"
    ]

    packet_artifacts = dict(receipt.get("packet_artifacts") or {})
    assert packet_artifacts == {
        "yaml": "docs/chummer5a_parity_lab/NEXT90_M141_ROUTE_LOCAL_SCREENSHOT_PACKS.generated.yaml",
        "markdown": "docs/chummer5a_parity_lab/NEXT90_M141_ROUTE_LOCAL_SCREENSHOT_PACKS.generated.md",
        "feedback": "feedback/2026-05-06-next90-m141-ea-route-local-screenshot-packs.md",
    }
    for relative_path in packet_artifacts.values():
        assert (ROOT / str(relative_path)).exists(), relative_path

    proof_commands = dict(receipt.get("proof_commands") or {})
    assert proof_commands == {
        "materialize": "python3 scripts/materialize_next90_m141_ea_route_local_screenshot_packs.py",
        "verify": "python3 scripts/verify_next90_m141_ea_route_local_screenshot_packs.py",
        "focused_test": "python3 -m unittest tests.test_next90_m141_ea_route_local_screenshot_packs",
    }

    notes = [str(item) for item in (receipt.get("notes") or [])]
    assert len(notes) == 2
    assert "route-local" in notes[0]
    assert "does not claim queue closeout" in notes[1]


def test_route_rows_and_family_rows_stay_direct_and_complete() -> None:
    payload = _yaml(PACK_PATH)
    module = _materializer_module()
    route_rows = [dict(row) for row in (payload.get("route_local_screenshot_packs") or [])]
    family_rows = [dict(row) for row in (payload.get("family_compare_packets") or [])]
    route_specs = {str(key): dict(value) for key, value in dict(module.ROUTE_SPECS).items()}
    family_specs = {str(key): dict(value) for key, value in dict(module.FAMILY_SPECS).items()}
    assert {row["route_id"] for row in route_rows} == {
        "menu:translator",
        "menu:xml_editor",
        "menu:hero_lab_importer",
        "workflow:import_oracle",
    }
    assert {row["family_id"] for row in family_rows} == {
        "custom_data_xml_and_translator_bridge",
        "legacy_and_adjacent_import_oracles",
    }
    for row in route_rows:
        spec = route_specs[row["route_id"]]
        assert row["status"] == "pass"
        assert row["required_compare_artifacts"] == spec["required_compare_artifacts"]
        assert row["required_screenshots"] == spec["required_screenshots"]
        assert row["missing_compare_artifacts"] == []
        assert row["missing_workflow_artifacts"] == []
        assert row["missing_screenshots"] == []
        assert row["deterministic_receipts"] == spec["deterministic_receipts"]
        assert row["ui_direct_receipt_group"] == spec["ui_direct_group"]
        assert set(row["compare_artifacts"]) >= set(spec["required_compare_artifacts"])
        assert set(row["screenshots"]) >= set(spec["required_screenshots"])
        assert row["route_receipts"]
        if row.get("parity_row_id"):
            parity_row = dict(row.get("parity_row") or {})
            assert parity_row.get("visual_parity") == "yes"
            assert parity_row.get("behavioral_parity") == "yes"
            assert parity_row.get("present_in_chummer5a") == "yes"
            assert parity_row.get("present_in_chummer6") == "yes"
    for row in family_rows:
        spec = family_specs[row["family_id"]]
        assert row["status"] == "pass"
        assert row["required_compare_artifacts"] == spec["required_compare_artifacts"]
        assert row["required_screenshots"] == spec["required_screenshots"]
        assert row["missing_compare_artifacts"] == []
        assert row["missing_workflow_artifacts"] == []
        assert row["missing_screenshots"] == []
        assert row["deterministic_receipts"] == spec["deterministic_receipts"]
        assert row["ui_direct_receipt_group"] == spec["ui_direct_group"]
        assert set(row["compare_artifacts"]) >= set(spec["required_compare_artifacts"])
        assert set(row["screenshots"]) >= set(spec["required_screenshots"])
        parity_row = dict(row.get("parity_row") or {})
        assert parity_row.get("visual_parity") == "yes"
        assert parity_row.get("behavioral_parity") == "yes"
        assert parity_row.get("present_in_chummer5a") == "yes"
        assert parity_row.get("present_in_chummer6") == "yes"


def test_markdown_and_feedback_keep_boundary_explicit() -> None:
    payload = _yaml(PACK_PATH)
    markdown = MARKDOWN_PATH.read_text(encoding="utf-8")
    feedback = FEEDBACK_PATH.read_text(encoding="utf-8")
    assert "menu:translator" in markdown
    assert "workflow:import_oracle" in markdown
    assert f"canonical frontier: `{payload.get('frontier_id')}`" in markdown
    assert "stale handoff or assignment frontier snippets are not proof" in markdown
    assert "canonical queue/registry rows are still open" in markdown
    assert "approved local mirror" in markdown
    assert "registry_task=unspecified" in markdown
    assert "duplicate queue or registry rows fail closed" in markdown
    assert "next90-m141-ea-compile-route-local-screenshot-packs-and-compare-packets-for-translator-x" in feedback
    assert f"current canonical frontier is `{payload.get('frontier_id')}`" in feedback
    assert "stale handoff or assignment frontier snippets are not authority" in feedback
    assert "does not mark the canonical queue rows complete" in feedback
    assert "Fleet M141 closeout gate" in feedback
    assert "approved local mirror" in feedback
    lowered = f"{payload!r}\n{markdown}\n{feedback}".lower()
    for forbidden in (
        "task_local_telemetry",
        "active_run_handoff",
        "/var/lib/codex-fleet",
        "supervisor status",
        "supervisor eta",
        "operator telemetry",
    ):
        assert forbidden not in lowered


def test_queue_and_registry_rows_match_the_active_m141_package() -> None:
    queue = _yaml(QUEUE_STAGING_PATH)
    design_queue = _yaml(DESIGN_QUEUE_STAGING_PATH)
    registry = _yaml(SUCCESSOR_REGISTRY_PATH)

    queue_rows = [dict(item) for item in (queue.get("items") or []) if dict(item).get("package_id") == "next90-m141-ea-compile-route-local-screenshot-packs-and-compare-packets-for-translator-x"]
    design_queue_rows = [dict(item) for item in (design_queue.get("items") or []) if dict(item).get("package_id") == "next90-m141-ea-compile-route-local-screenshot-packs-and-compare-packets-for-translator-x"]
    milestone = next(item for item in registry.get("milestones") or [] if int(dict(item).get("id") or 0) == 141)
    work_tasks = [dict(item) for item in (milestone.get("work_tasks") or []) if str(dict(item).get("id")) == "141.4"]

    assert len(queue_rows) == 1
    assert len(design_queue_rows) == 1
    assert len(work_tasks) == 1

    queue_row = queue_rows[0]
    design_queue_row = design_queue_rows[0]
    work_task = work_tasks[0]
    expected_frontier_id = int(queue_row["frontier_id"])

    assert queue_row["status"] == design_queue_row["status"] == "not_started"
    assert queue_row["title"] == design_queue_row["title"] == "Compile route-local screenshot packs and compare packets for translator, XML amendment, Hero Lab, and import-oracle proof without inventing parity."
    assert queue_row["task"] == design_queue_row["task"] == "Compile route-local screenshot packs and compare packets for translator, XML amendment, Hero Lab, and import-oracle proof without inventing parity."
    assert queue_row["repo"] == design_queue_row["repo"] == "executive-assistant"
    assert queue_row["wave"] == design_queue_row["wave"] == "W22P"
    assert str(queue_row["work_task_id"]) == str(design_queue_row["work_task_id"]) == "141.4"
    assert expected_frontier_id == int(design_queue_row["frontier_id"])
    assert work_task["owner"] == "executive-assistant"
    assert work_task["title"] == "Compile route-local screenshot packs and compare packets for translator, XML amendment, Hero Lab, and import-oracle proof without inventing parity."
    assert "status" not in work_task


def test_canonical_monitors_distinguish_unspecified_registry_status_from_missing_row() -> None:
    payload = _yaml(PACK_PATH)
    assert int(payload.get("frontier_id") or 0) > 0
    source_inputs = dict(payload.get("source_inputs") or {})
    design_queue = dict(source_inputs.get("design_queue") or {})
    fleet_queue = dict(source_inputs.get("fleet_queue") or {})
    local_mirror_queue = dict(source_inputs.get("local_mirror_queue") or {})
    registry_input = dict(source_inputs.get("registry") or {})
    local_mirror_registry = dict(source_inputs.get("local_mirror_registry") or {})
    readiness_input = dict(source_inputs.get("flagship_readiness") or {})
    guide_markers = dict(dict(payload.get("canonical_monitors") or {}).get("guide_markers") or {})
    queue_alignment = dict(dict(payload.get("canonical_monitors") or {}).get("queue_alignment") or {})
    mirror_alignment = dict(dict(payload.get("canonical_monitors") or {}).get("mirror_alignment") or {})
    queue_closeout = dict(dict(payload.get("canonical_monitors") or {}).get("queue_closeout") or {})
    fleet_gate_monitor = dict(dict(payload.get("canonical_monitors") or {}).get("fleet_m141_gate") or {})
    assert design_queue.get("status") == "not_started"
    assert design_queue.get("path") == "/docker/chummercomplete/chummer-design/products/chummer/NEXT_90_DAY_QUEUE_STAGING.generated.yaml"
    assert int(design_queue.get("match_count") or 0) == 1
    assert design_queue.get("unique_match") is True
    assert design_queue.get("work_task_id") == "141.4"
    assert int(design_queue.get("milestone_id") or 0) == 141
    assert int(design_queue.get("frontier_id") or 0) == int(payload.get("frontier_id") or 0)
    assert design_queue.get("wave") == "W22P"
    assert design_queue.get("repo") == "executive-assistant"
    assert design_queue.get("row_fingerprint")
    assert fleet_queue.get("status") == "not_started"
    assert fleet_queue.get("path") == "/docker/fleet/.codex-studio/published/NEXT_90_DAY_QUEUE_STAGING.generated.yaml"
    assert int(fleet_queue.get("match_count") or 0) == 1
    assert fleet_queue.get("unique_match") is True
    assert fleet_queue.get("work_task_id") == "141.4"
    assert int(fleet_queue.get("milestone_id") or 0) == 141
    assert int(fleet_queue.get("frontier_id") or 0) == int(payload.get("frontier_id") or 0)
    assert fleet_queue.get("wave") == "W22P"
    assert fleet_queue.get("repo") == "executive-assistant"
    assert fleet_queue.get("row_fingerprint")
    assert design_queue.get("row_fingerprint") == fleet_queue.get("row_fingerprint")
    assert int(local_mirror_queue.get("match_count") or 0) == 1
    assert local_mirror_queue.get("path") == "/docker/EA/.codex-design/product/NEXT_90_DAY_QUEUE_STAGING.generated.yaml"
    assert local_mirror_queue.get("unique_match") is True
    assert local_mirror_queue.get("status") == "not_started"
    assert local_mirror_queue.get("work_task_id") == "141.4"
    assert int(local_mirror_queue.get("milestone_id") or 0) == 141
    assert int(local_mirror_queue.get("frontier_id") or 0) == int(payload.get("frontier_id") or 0)
    assert local_mirror_queue.get("wave") == "W22P"
    assert local_mirror_queue.get("repo") == "executive-assistant"
    assert local_mirror_queue.get("row_fingerprint")
    assert registry_input.get("work_task_id") == "141.4"
    assert registry_input.get("path") == "/docker/chummercomplete/chummer-design/products/chummer/NEXT_90_DAY_PRODUCT_ADVANCE_REGISTRY.yaml"
    assert int(registry_input.get("milestone_id") or 0) == 141
    assert registry_input.get("owner") == "executive-assistant"
    assert registry_input.get("title") == payload.get("title")
    assert int(registry_input.get("match_count") or 0) == 1
    assert registry_input.get("unique_match") is True
    assert registry_input.get("row_fingerprint")
    assert int(local_mirror_registry.get("match_count") or 0) == 1
    assert local_mirror_registry.get("path") == "/docker/EA/.codex-design/product/NEXT_90_DAY_PRODUCT_ADVANCE_REGISTRY.yaml"
    assert local_mirror_registry.get("unique_match") is True
    assert local_mirror_registry.get("work_task_id") == "141.4"
    assert int(local_mirror_registry.get("milestone_id") or 0) == 141
    assert local_mirror_registry.get("status") == ""
    assert local_mirror_registry.get("owner") == "executive-assistant"
    assert local_mirror_registry.get("title") == payload.get("title")
    assert local_mirror_registry.get("row_fingerprint")
    assert readiness_input.get("path") == "/docker/fleet/.codex-studio/published/FLAGSHIP_PRODUCT_READINESS.generated.json"
    assert readiness_input.get("coverage_key") == "desktop_client"
    assert readiness_input.get("status") == dict(payload.get("desktop_client_readiness") or {}).get("status")
    assert readiness_input.get("summary") == dict(payload.get("desktop_client_readiness") or {}).get("summary")
    assert int(readiness_input.get("reason_count") or 0) == len(list(dict(payload.get("desktop_client_readiness") or {}).get("reasons") or []))
    module = _materializer_module()
    expected_readiness_fingerprint = module._stable_fingerprint(
        module._desktop_readiness_fingerprint_payload(
            dict(payload.get("desktop_client_readiness") or {}),
            desktop_status=str(dict(payload.get("desktop_client_readiness") or {}).get("status") or ""),
            desktop_summary=str(dict(payload.get("desktop_client_readiness") or {}).get("summary") or ""),
            desktop_reasons=[str(item) for item in (dict(payload.get("desktop_client_readiness") or {}).get("reasons") or [])],
        )
    )
    assert readiness_input.get("row_fingerprint") == expected_readiness_fingerprint
    assert guide_markers == {"wave": True, "milestone": True, "exit": True}
    assert queue_alignment.get("design_queue_unique") is True
    assert queue_alignment.get("fleet_queue_unique") is True
    assert queue_alignment.get("registry_task_unique") is True
    assert queue_alignment.get("design_fleet_queue_fingerprint_matches") is True
    assert queue_alignment.get("work_task_id_matches") is True
    assert queue_alignment.get("milestone_id_matches") is True
    assert queue_alignment.get("wave_matches") is True
    assert queue_alignment.get("repo_matches") is True
    assert queue_alignment.get("frontier_id_matches") is True
    assert queue_alignment.get("registry_task_present") is True
    assert queue_alignment.get("registry_task_owner_matches") is True
    assert queue_alignment.get("registry_task_title_matches") is True
    assert mirror_alignment.get("local_mirror_queue_present") is True
    assert mirror_alignment.get("local_mirror_registry_present") is True
    assert mirror_alignment.get("local_mirror_queue_unique") is True
    assert mirror_alignment.get("local_mirror_registry_unique") is True
    assert mirror_alignment.get("local_mirror_queue_matches_design_queue") is True
    assert mirror_alignment.get("local_mirror_queue_matches_fleet_queue") is True
    assert mirror_alignment.get("local_mirror_registry_matches_canonical_registry") is True
    assert mirror_alignment.get("local_mirror_registry_owner_matches") is True
    assert mirror_alignment.get("local_mirror_registry_title_matches") is True
    assert fleet_gate_monitor.get("status") == "pass"
    assert fleet_gate_monitor.get("ready") is True
    assert int(fleet_gate_monitor.get("runtime_blocker_count") or 0) == 0
    assert queue_closeout.get("registry_task_status") == "unspecified"
    assert queue_closeout.get("ready_to_mark_complete") is False
    blockers = [str(item) for item in (dict(payload.get("closeout") or {}).get("blockers") or [])]
    assert not any("approved local mirror" in blocker for blocker in blockers)
    assert any("canonical queue/registry rows are still open" in blocker for blocker in blockers)


def test_runtime_fingerprint_ignores_generated_timestamp_only_churn() -> None:
    module = _materializer_module()
    readiness = {
        "status": "ready",
        "summary": "Desktop install, release-channel, and flagship workbench proof are current.",
        "reasons": [],
        "generatedAt": "2026-05-06T03:21:00Z",
        "nested": {
            "generated_at": "2026-05-06T03:21:01Z",
            "value": "stable",
        },
        "evidence": {
            "ui_executable_gate_generated_at": "2026-05-06T03:21:02Z",
            "ui_executable_gate_age_seconds": 90,
            "ui_executable_gate_freshness_proof_age_seconds": {
                "desktop workflow execution gate proof_age_seconds": 45,
            },
        },
    }
    changed_only_timestamps = {
        "status": "ready",
        "summary": "Desktop install, release-channel, and flagship workbench proof are current.",
        "reasons": [],
        "generatedAt": "2026-05-06T04:00:00Z",
        "nested": {
            "generated_at": "2026-05-06T04:00:01Z",
            "value": "stable",
        },
        "evidence": {
            "ui_executable_gate_generated_at": "2026-05-06T04:00:02Z",
            "ui_executable_gate_age_seconds": 450,
            "ui_executable_gate_freshness_proof_age_seconds": {
                "desktop workflow execution gate proof_age_seconds": 405,
            },
        },
    }

    fingerprint = module._stable_fingerprint(
        module._desktop_readiness_fingerprint_payload(
            readiness,
            desktop_status="ready",
            desktop_summary=readiness["summary"],
            desktop_reasons=[],
        )
    )
    changed_fingerprint = module._stable_fingerprint(
        module._desktop_readiness_fingerprint_payload(
            changed_only_timestamps,
            desktop_status="ready",
            desktop_summary=changed_only_timestamps["summary"],
            desktop_reasons=[],
        )
    )

    assert fingerprint == changed_fingerprint


def test_queue_alignment_reports_metadata_drift_when_canonical_rows_disagree() -> None:
    module = _materializer_module()
    design_queue_row = {
        "package_id": "next90-m141-ea-compile-route-local-screenshot-packs-and-compare-packets-for-translator-x",
        "allowed_paths": ["scripts", "feedback", "docs"],
        "owned_surfaces": ["compile_route_local_screenshot_packs_and_compare_packets:ea"],
        "work_task_id": "141.4",
        "milestone_id": 141,
        "wave": "W22P",
        "repo": "executive-assistant",
        "frontier_id": 2732551969,
    }
    fleet_queue_row = dict(design_queue_row)
    fleet_queue_row["frontier_id"] = 1490492808
    registry_task = {
        "id": "141.4",
        "owner": "executive-assistant",
        "title": "Compile route-local screenshot packs and compare packets for translator, XML amendment, Hero Lab, and import-oracle proof without inventing parity.",
    }

    alignment = module._queue_alignment(
        design_queue_row,
        fleet_queue_row,
        registry_task,
        design_queue_match_count=1,
        fleet_queue_match_count=1,
        registry_task_match_count=1,
    )

    assert alignment["frontier_id_matches"] is False
    assert alignment["design_queue_unique"] is True
    assert alignment["fleet_queue_unique"] is True
    assert alignment["registry_task_unique"] is True


def test_mirror_alignment_reports_missing_local_registry_row_fail_closed() -> None:
    module = _materializer_module()
    canonical_queue_row = {
        "package_id": "next90-m141-ea-compile-route-local-screenshot-packs-and-compare-packets-for-translator-x",
        "allowed_paths": ["scripts", "feedback", "docs"],
        "owned_surfaces": ["compile_route_local_screenshot_packs_and_compare_packets:ea"],
        "work_task_id": "141.4",
        "milestone_id": 141,
        "wave": "W22P",
        "repo": "executive-assistant",
        "frontier_id": 2732551969,
        "status": "not_started",
    }
    registry_task = {
        "id": "141.4",
        "owner": "executive-assistant",
        "title": "Compile route-local screenshot packs and compare packets for translator, XML amendment, Hero Lab, and import-oracle proof without inventing parity.",
    }

    alignment = module._mirror_alignment(
        canonical_queue_row,
        canonical_queue_row,
        registry_task,
        canonical_queue_row,
        {},
        local_mirror_queue_match_count=1,
        local_mirror_registry_match_count=0,
    )

    assert alignment["local_mirror_queue_present"] is True
    assert alignment["local_mirror_registry_present"] is False
    assert alignment["local_mirror_queue_unique"] is True
    assert alignment["local_mirror_registry_unique"] is False
    assert alignment["local_mirror_queue_matches_design_queue"] is True
    assert alignment["local_mirror_queue_matches_fleet_queue"] is True
    assert alignment["local_mirror_registry_matches_canonical_registry"] is False
    assert alignment["local_mirror_registry_owner_matches"] is False
    assert alignment["local_mirror_registry_title_matches"] is False


def test_mirror_alignment_reports_aligned_local_registry_row() -> None:
    module = _materializer_module()
    canonical_queue_row = {
        "package_id": "next90-m141-ea-compile-route-local-screenshot-packs-and-compare-packets-for-translator-x",
        "allowed_paths": ["scripts", "feedback", "docs"],
        "owned_surfaces": ["compile_route_local_screenshot_packs_and_compare_packets:ea"],
        "work_task_id": "141.4",
        "milestone_id": 141,
        "wave": "W22P",
        "repo": "executive-assistant",
        "frontier_id": 2732551969,
        "status": "not_started",
    }
    registry_task = {
        "id": "141.4",
        "owner": "executive-assistant",
        "title": "Compile route-local screenshot packs and compare packets for translator, XML amendment, Hero Lab, and import-oracle proof without inventing parity.",
    }

    alignment = module._mirror_alignment(
        canonical_queue_row,
        canonical_queue_row,
        registry_task,
        canonical_queue_row,
        registry_task,
        local_mirror_queue_match_count=1,
        local_mirror_registry_match_count=1,
    )

    assert alignment["local_mirror_queue_present"] is True
    assert alignment["local_mirror_registry_present"] is True
    assert alignment["local_mirror_queue_unique"] is True
    assert alignment["local_mirror_registry_unique"] is True
    assert alignment["local_mirror_queue_matches_design_queue"] is True
    assert alignment["local_mirror_queue_matches_fleet_queue"] is True
    assert alignment["local_mirror_registry_matches_canonical_registry"] is True
    assert alignment["local_mirror_registry_owner_matches"] is True
    assert alignment["local_mirror_registry_title_matches"] is True


def load_tests(loader: unittest.TestLoader, tests: unittest.TestSuite, pattern: str | None) -> unittest.TestSuite:
    suite = unittest.TestSuite()
    for name, func in sorted(globals().items()):
        if name.startswith("test_") and callable(func):
            suite.addTest(unittest.FunctionTestCase(func))
    return suite


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
