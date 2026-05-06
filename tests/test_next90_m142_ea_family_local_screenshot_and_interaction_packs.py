from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "ea") not in sys.path:
    sys.path.insert(0, str(ROOT / "ea"))

from app.yaml_inputs import load_yaml_dict


PACK_PATH = ROOT / "docs" / "chummer5a_parity_lab" / "NEXT90_M142_FAMILY_LOCAL_SCREENSHOT_AND_INTERACTION_PACKS.generated.yaml"
MARKDOWN_PATH = ROOT / "docs" / "chummer5a_parity_lab" / "NEXT90_M142_FAMILY_LOCAL_SCREENSHOT_AND_INTERACTION_PACKS.generated.md"
FEEDBACK_PATH = ROOT / "feedback" / "2026-05-06-next90-m142-ea-family-local-screenshot-and-interaction-packs.md"
MATERIALIZER_PATH = ROOT / "scripts" / "materialize_next90_m142_ea_family_local_screenshot_and_interaction_packs.py"
VERIFY_PATH = ROOT / "scripts" / "verify_next90_m142_ea_family_local_screenshot_and_interaction_packs.py"
QUEUE_STAGING_PATH = Path("/docker/fleet/.codex-studio/published/NEXT_90_DAY_QUEUE_STAGING.generated.yaml")
DESIGN_QUEUE_STAGING_PATH = Path("/docker/chummercomplete/chummer-design/products/chummer/NEXT_90_DAY_QUEUE_STAGING.generated.yaml")
SUCCESSOR_REGISTRY_PATH = Path("/docker/chummercomplete/chummer-design/products/chummer/NEXT_90_DAY_PRODUCT_ADVANCE_REGISTRY.yaml")


def _yaml(path: Path) -> dict:
    return load_yaml_dict(path)


def _module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _without_generated_at(payload: dict) -> dict:
    clone = dict(payload)
    clone.pop("generated_at", None)
    return clone


def _stable_contract_projection(payload: dict) -> dict:
    def _row_projection(row: dict) -> dict:
        return {
            "family_id": row.get("family_id"),
            "label": row.get("label"),
            "compare_artifacts": list(row.get("compare_artifacts") or []),
            "required_compare_artifacts": list(row.get("required_compare_artifacts") or []),
            "required_screenshots": list(row.get("required_screenshots") or []),
            "workflow_task_ids": list(row.get("workflow_task_ids") or []),
            "receipt_routes": [
                {
                    "route_id": receipt.get("route_id"),
                    "source_key": receipt.get("source_key"),
                    "required_tokens": list(receipt.get("required_tokens") or []),
                }
                for receipt in [dict(item) for item in (row.get("screenshot_receipts") or []) + (row.get("interaction_receipts") or [])]
            ],
            "evidence_paths": list(row.get("evidence_paths") or []),
        }

    source_inputs = dict(payload.get("source_inputs") or {})
    return {
        "contract_name": payload.get("contract_name"),
        "package_id": payload.get("package_id"),
        "milestone_id": payload.get("milestone_id"),
        "work_task_id": payload.get("work_task_id"),
        "frontier_id": payload.get("frontier_id"),
        "wave": payload.get("wave"),
        "owned_surfaces": list(payload.get("owned_surfaces") or []),
        "allowed_paths": list(payload.get("allowed_paths") or []),
        "source_input_paths": {key: dict(value).get("path") for key, value in source_inputs.items()},
        "queue_identity": {
            "design_queue": {
                "match_count": dict(source_inputs.get("design_queue") or {}).get("match_count"),
                "unique_match": dict(source_inputs.get("design_queue") or {}).get("unique_match"),
                "status": dict(source_inputs.get("design_queue") or {}).get("status"),
                "frontier_id": dict(source_inputs.get("design_queue") or {}).get("frontier_id"),
            },
            "fleet_queue": {
                "match_count": dict(source_inputs.get("fleet_queue") or {}).get("match_count"),
                "unique_match": dict(source_inputs.get("fleet_queue") or {}).get("unique_match"),
                "status": dict(source_inputs.get("fleet_queue") or {}).get("status"),
                "frontier_id": dict(source_inputs.get("fleet_queue") or {}).get("frontier_id"),
            },
            "local_mirror_queue": {
                "match_count": dict(source_inputs.get("local_mirror_queue") or {}).get("match_count"),
                "unique_match": dict(source_inputs.get("local_mirror_queue") or {}).get("unique_match"),
                "status": dict(source_inputs.get("local_mirror_queue") or {}).get("status"),
                "frontier_id": dict(source_inputs.get("local_mirror_queue") or {}).get("frontier_id"),
            },
            "registry": {
                "match_count": dict(source_inputs.get("registry") or {}).get("match_count"),
                "unique_match": dict(source_inputs.get("registry") or {}).get("unique_match"),
                "status": dict(source_inputs.get("registry") or {}).get("status"),
                "owner": dict(source_inputs.get("registry") or {}).get("owner"),
            },
            "local_mirror_registry": {
                "match_count": dict(source_inputs.get("local_mirror_registry") or {}).get("match_count"),
                "unique_match": dict(source_inputs.get("local_mirror_registry") or {}).get("unique_match"),
                "status": dict(source_inputs.get("local_mirror_registry") or {}).get("status"),
                "owner": dict(source_inputs.get("local_mirror_registry") or {}).get("owner"),
            },
            "flagship_readiness": {
                "path": dict(source_inputs.get("flagship_readiness") or {}).get("path"),
                "coverage_key": dict(source_inputs.get("flagship_readiness") or {}).get("coverage_key"),
            },
        },
        "family_rows": [_row_projection(dict(row)) for row in (payload.get("family_local_packs") or [])],
        "closeout_notes": list(dict(payload.get("closeout") or {}).get("notes") or []),
    }


def test_materializer_rebuilds_current_generated_packet() -> None:
    payload = _yaml(PACK_PATH)
    materializer = _module(MATERIALIZER_PATH, "ea_next90_m142_materializer")
    assert _stable_contract_projection(payload) == _stable_contract_projection(materializer.build_payload())
    assert materializer.build_payload().get("generated_at") == payload.get("generated_at")


def test_packet_identity_and_scope() -> None:
    payload = _yaml(PACK_PATH)
    assert payload.get("contract_name") == "ea.next90_m142_family_local_screenshot_and_interaction_packs"
    assert payload.get("package_id") == "next90-m142-ea-compile-family-local-screenshot-and-interaction-packs-for-these-workflows"
    assert int(payload.get("milestone_id") or 0) == 142
    assert payload.get("work_task_id") == "142.4"
    assert int(payload.get("frontier_id") or 0) == 5399660048
    assert list(payload.get("owned_surfaces") or []) == ["compile_family_local_screenshot_and_interaction_packs_fo:ea"]
    assert list(payload.get("allowed_paths") or []) == ["scripts", "feedback", "docs"]
    assert MARKDOWN_PATH.is_file()
    assert FEEDBACK_PATH.is_file()


def test_family_rows_keep_direct_receipts_and_desktop_dependency() -> None:
    payload = _yaml(PACK_PATH)
    desktop_readiness = dict(payload.get("desktop_client_readiness") or {})
    rows = [dict(row) for row in (payload.get("family_local_packs") or [])]
    expected_workflow_task_ids = {
        "dense_builder_and_career_workflows": ["reach_real_workbench", "recover_section_rhythm"],
        "dice_initiative_and_table_utilities": ["locate_save_import_settings"],
        "identity_contacts_lifestyles_history": ["recover_section_rhythm"],
    }

    assert {row["family_id"] for row in rows} == {
        "dense_builder_and_career_workflows",
        "dice_initiative_and_table_utilities",
        "identity_contacts_lifestyles_history",
    }
    assert desktop_readiness.get("coverage_key") == "desktop_client"
    assert str(desktop_readiness.get("status") or "").strip()
    blockers = [str(item) for item in dict(payload.get("closeout") or {}).get("blockers") or []]

    for row in rows:
        assert row.get("evidence_paths")
        assert row.get("required_screenshots")
        assert row.get("workflow_task_ids") == expected_workflow_task_ids[row["family_id"]]
        assert row.get("screenshot_receipts")
        assert row.get("interaction_receipts")
        dependency = dict(row.get("desktop_client_dependency") or {})
        assert dependency.get("coverage_key") == "desktop_client"
        assert dependency.get("coverage_status") == desktop_readiness.get("status")
        parity = dict(row.get("parity_audit") or {})
        visual_parity = str(parity.get("visual_parity") or "").strip().lower()
        behavioral_parity = str(parity.get("behavioral_parity") or "").strip().lower()
        assert visual_parity in {"yes", "no"}
        assert behavioral_parity in {"yes", "no"}
        if visual_parity != "yes" or behavioral_parity != "yes":
            assert row.get("issues")
            assert any(str(row.get("family_id")) in blocker for blocker in blockers)
        for receipt in [dict(item) for item in (row.get("screenshot_receipts") or []) + (row.get("interaction_receipts") or [])]:
            assert receipt.get("required_tokens")
            assert receipt.get("satisfied") is True


def test_queue_and_registry_rows_match_the_active_m142_package() -> None:
    queue = _yaml(QUEUE_STAGING_PATH)
    design_queue = _yaml(DESIGN_QUEUE_STAGING_PATH)
    registry = _yaml(SUCCESSOR_REGISTRY_PATH)
    local_mirror_queue = _yaml(ROOT / ".codex-design" / "product" / "NEXT_90_DAY_QUEUE_STAGING.generated.yaml")
    local_mirror_registry = _yaml(ROOT / ".codex-design" / "product" / "NEXT_90_DAY_PRODUCT_ADVANCE_REGISTRY.yaml")

    package_id = "next90-m142-ea-compile-family-local-screenshot-and-interaction-packs-for-these-workflows"
    queue_row = next(item for item in queue.get("items") or [] if dict(item).get("package_id") == package_id)
    design_queue_row = next(item for item in design_queue.get("items") or [] if dict(item).get("package_id") == package_id)
    local_mirror_queue_row = next(item for item in local_mirror_queue.get("items") or [] if dict(item).get("package_id") == package_id)
    milestone = next(item for item in registry.get("milestones") or [] if int(dict(item).get("id") or 0) == 142)
    work_task = next(item for item in milestone.get("work_tasks") or [] if str(dict(item).get("id")) == "142.4")
    local_mirror_milestone = next(item for item in local_mirror_registry.get("milestones") or [] if int(dict(item).get("id") or 0) == 142)
    local_mirror_work_task = next(item for item in local_mirror_milestone.get("work_tasks") or [] if str(dict(item).get("id")) == "142.4")

    assert queue_row["status"] == design_queue_row["status"] == local_mirror_queue_row["status"] == "not_started"
    assert queue_row["repo"] == design_queue_row["repo"] == local_mirror_queue_row["repo"] == "executive-assistant"
    assert queue_row["wave"] == design_queue_row["wave"] == local_mirror_queue_row["wave"] == "W22P"
    assert str(queue_row["work_task_id"]) == str(design_queue_row["work_task_id"]) == str(local_mirror_queue_row["work_task_id"]) == "142.4"
    assert list(queue_row["owned_surfaces"] or []) == ["compile_family_local_screenshot_and_interaction_packs_fo:ea"]
    assert list(design_queue_row["owned_surfaces"] or []) == ["compile_family_local_screenshot_and_interaction_packs_fo:ea"]
    assert list(local_mirror_queue_row["owned_surfaces"] or []) == ["compile_family_local_screenshot_and_interaction_packs_fo:ea"]
    assert work_task["owner"] == local_mirror_work_task["owner"] == "executive-assistant"
    assert work_task["title"] == local_mirror_work_task["title"] == "Compile family-local screenshot and interaction packs for these workflows without collapsing them into broad family prose."


def test_generated_packet_pins_queue_uniqueness_and_current_feedback_boundary() -> None:
    payload = _yaml(PACK_PATH)
    source_inputs = dict(payload.get("source_inputs") or {})
    queue_alignment = dict(dict(payload.get("canonical_monitors") or {}).get("queue_alignment") or {})
    feedback_text = FEEDBACK_PATH.read_text(encoding="utf-8")

    assert dict(source_inputs.get("design_queue") or {}).get("match_count") == 1
    assert dict(source_inputs.get("design_queue") or {}).get("unique_match") is True
    assert dict(source_inputs.get("fleet_queue") or {}).get("match_count") == 1
    assert dict(source_inputs.get("fleet_queue") or {}).get("unique_match") is True
    assert dict(source_inputs.get("local_mirror_queue") or {}).get("path") == "/docker/EA/.codex-design/product/NEXT_90_DAY_QUEUE_STAGING.generated.yaml"
    assert dict(source_inputs.get("local_mirror_queue") or {}).get("match_count") == 1
    assert dict(source_inputs.get("local_mirror_queue") or {}).get("unique_match") is True
    assert dict(source_inputs.get("registry") or {}).get("match_count") == 1
    assert dict(source_inputs.get("registry") or {}).get("unique_match") is True
    assert dict(source_inputs.get("local_mirror_registry") or {}).get("path") == "/docker/EA/.codex-design/product/NEXT_90_DAY_PRODUCT_ADVANCE_REGISTRY.yaml"
    assert dict(source_inputs.get("local_mirror_registry") or {}).get("match_count") == 1
    assert dict(source_inputs.get("local_mirror_registry") or {}).get("unique_match") is True
    assert queue_alignment.get("design_queue_unique") is True
    assert queue_alignment.get("fleet_queue_unique") is True
    assert queue_alignment.get("local_mirror_queue_unique") is True
    assert queue_alignment.get("registry_task_unique") is True
    assert queue_alignment.get("local_mirror_registry_task_unique") is True
    assert queue_alignment.get("design_fleet_queue_fingerprint_matches") is True
    assert queue_alignment.get("design_local_mirror_queue_fingerprint_matches") is True
    assert queue_alignment.get("registry_task_owner_matches") is True
    assert queue_alignment.get("registry_task_title_matches") is True
    assert queue_alignment.get("local_mirror_queue_owner_matches") is True
    assert queue_alignment.get("local_mirror_queue_frontier_matches") is True
    assert queue_alignment.get("local_mirror_queue_allowed_paths_match") is True
    assert queue_alignment.get("local_mirror_queue_owned_surfaces_match") is True
    assert queue_alignment.get("local_mirror_registry_task_owner_matches") is True
    assert queue_alignment.get("local_mirror_registry_task_title_matches") is True
    assert queue_alignment.get("registry_local_mirror_task_fingerprint_matches") is True
    assert "canonical queue frontier `5399660048`" in feedback_text
    assert ".codex-design local mirror" in feedback_text
    assert "duplicate queue or registry rows fail closed" in feedback_text
    assert "desktop_client = ready" in feedback_text
    assert "screenshot receipts" in feedback_text
    assert "interaction receipts" in feedback_text
    assert "dense_builder_and_career_workflows" in feedback_text
    assert "dice_initiative_and_table_utilities" in feedback_text
    assert "identity_contacts_lifestyles_history" in feedback_text
    lowered = f"{payload!r}\n{MARKDOWN_PATH.read_text(encoding='utf-8')}\n{feedback_text}".lower()
    for forbidden in (
        "task_local_telemetry",
        "active_run_handoff",
        "/var/lib/codex-fleet",
        "supervisor status",
        "supervisor eta",
        "operator telemetry",
    ):
        assert forbidden not in lowered


def test_generated_markdown_keeps_family_local_receipt_detail_visible() -> None:
    markdown = MARKDOWN_PATH.read_text(encoding="utf-8")

    assert "canonical queue frontier: `5399660048`" in markdown
    assert "## Family summary" in markdown
    assert "## Queue guardrails" in markdown
    assert "approved `.codex-design` local mirror" in markdown
    assert "duplicate queue or registry rows fail closed" in markdown
    assert "- `dense_builder_and_career_workflows`: pass" in markdown
    assert "compare artifacts: `oracle:tabs, oracle:workspace_actions, workflow:build_explain_publish`" in markdown
    assert "workflow task ids: `reach_real_workbench, recover_section_rhythm`" in markdown
    assert "required screenshots: `05-dense-section-light.png, 06-dense-section-dark.png, 07-loaded-runner-tabs-light.png`" in markdown
    assert "  - screenshot receipts:" in markdown
    assert "screenshot `screenshot:dense_workbench_light` -> `ok`" in markdown
    assert "receipt proof: `screenshot_gate` requires `05-dense-section-light.png, dense_builder, legacy_dense_builder_rhythm`" in markdown
    assert "  - interaction receipts:" in markdown
    assert "receipt proof: `workflow_gate` requires `create-open-import-save-save-as-print-export, dense-workbench-affordances-search-add-edit-remove-preview-drill-in-compare, Loaded_runner_workbench_preserves_legacy_frmcareer_landmarks, Character_creation_preserves_familiar_dense_builder_rhythm, Advancement_and_karma_journal_workflows_preserve_familiar_progression_rhythm`" in markdown
    assert "- `dice_initiative_and_table_utilities`: pass" in markdown
    assert "workflow task ids: `locate_save_import_settings`" in markdown
    assert "screenshot `screenshot:menu_open` -> `ok`" in markdown
    assert "receipt proof: `visual_gate` requires `02-menu-open-light.png, Runtime_backed_menu_bar_preserves_classic_labels_and_clickable_primary_menus`" in markdown
    assert "interaction `workflow:initiative_runtime_marker` -> `ok`" in markdown
    assert "receipt proof: `workflow_gate` requires `initiative_utility, menu:dice_roller_or_workflow:initiative_screenshot, 11 + 2d6`" in markdown
    assert "- `identity_contacts_lifestyles_history`: pass" in markdown
    assert "workflow task ids: `recover_section_rhythm`" in markdown
    assert "screenshot `screenshot:contacts_section` -> `ok`" in markdown
    assert "receipt proof: `visual_gate` requires `10-contacts-section-light.png, legacyContactsWorkflowRhythm`" in markdown
    assert "interaction `workflow:contacts_notes_runtime_marker` -> `ok`" in markdown
    assert "receipt proof: `workflow_gate` requires `Contacts_diary_and_support_routes_execute_with_public_path_visibility, tab-lifestyle.lifestyles, tab-notes.metadata`" in markdown


def test_verifier_script_accepts_the_current_packet() -> None:
    verifier = _module(VERIFY_PATH, "ea_next90_m142_verifier")
    assert verifier.main() == 0
