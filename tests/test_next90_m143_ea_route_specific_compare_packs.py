from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "ea") not in sys.path:
    sys.path.insert(0, str(ROOT / "ea"))

from app.yaml_inputs import load_yaml_dict

PACK_PATH = ROOT / "docs" / "chummer5a_parity_lab" / "NEXT90_M143_ROUTE_SPECIFIC_COMPARE_PACKS.generated.yaml"
MARKDOWN_PATH = ROOT / "docs" / "chummer5a_parity_lab" / "NEXT90_M143_ROUTE_SPECIFIC_COMPARE_PACKS.generated.md"
FEEDBACK_PATH = ROOT / "feedback" / "2026-05-05-next90-m143-ea-route-specific-compare-packs.md"
MATERIALIZER_PATH = ROOT / "scripts" / "materialize_next90_m143_ea_route_specific_compare_packs.py"
VERIFY_PATH = ROOT / "scripts" / "verify_next90_m143_ea_route_specific_compare_packs.py"
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
            "workflow_readiness_target": row.get("workflow_readiness_target"),
            "expected_readiness_floor": row.get("expected_readiness_floor"),
            "receipt_routes": [
                {
                    "route_id": receipt.get("route_id"),
                    "source_key": receipt.get("source_key"),
                    "required_tokens": list(receipt.get("required_tokens") or []),
                }
                for receipt in [dict(item) for item in (row.get("route_receipts") or [])]
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
        "family_rows": [_row_projection(dict(row)) for row in (payload.get("family_route_compare_packs") or [])],
        "closeout_notes": list(dict(payload.get("closeout") or {}).get("notes") or []),
    }


def test_materializer_rebuilds_current_generated_packet() -> None:
    payload = _yaml(PACK_PATH)
    materializer = _module(MATERIALIZER_PATH, "ea_next90_m143_materializer")
    assert _stable_contract_projection(payload) == _stable_contract_projection(materializer.build_payload())


def test_packet_identity_and_scope() -> None:
    payload = _yaml(PACK_PATH)
    assert payload.get("contract_name") == "ea.next90_m143_route_specific_compare_packs"
    assert payload.get("package_id") == "next90-m143-ea-compile-route-specific-compare-packs-and-artifact-proofs-for-print-export"
    assert payload.get("title") == "Compile route-specific compare packs and artifact proofs for print, export, exchange, SR6 supplement, and house-rule workflows."
    assert int(payload.get("milestone_id") or 0) == 143
    assert payload.get("work_task_id") == "143.5"
    assert int(payload.get("frontier_id") or 0) == 5326878760
    assert payload.get("wave") == "W22P"
    assert list(payload.get("owned_surfaces") or []) == ["compile_route_specific_compare_packs_and_artifact_proofs:ea"]
    assert list(payload.get("allowed_paths") or []) == ["scripts", "feedback", "docs"]


def test_family_rows_keep_direct_route_receipts_and_desktop_dependency() -> None:
    payload = _yaml(PACK_PATH)
    desktop_readiness = dict(payload.get("desktop_client_readiness") or {})
    rows = [dict(row) for row in (payload.get("family_route_compare_packs") or [])]
    blockers = [str(item) for item in dict(payload.get("closeout") or {}).get("blockers") or []]
    assert {row["family_id"] for row in rows} == {
        "sheet_export_print_viewer_and_exchange",
        "sr6_supplements_designers_and_house_rules",
    }
    for row in rows:
        assert row.get("evidence_paths")
        dependency = dict(row.get("desktop_client_dependency") or {})
        assert dependency.get("coverage_key") == "desktop_client"
        assert dependency.get("coverage_status") == desktop_readiness.get("status")
        if desktop_readiness.get("status") == "ready":
            assert dependency.get("relevant_reasons") == []
        else:
            assert dependency.get("relevant_reasons")
        if row.get("issues"):
            assert any(str(row.get("family_id")) in blocker for blocker in blockers)
        route_receipts = [dict(receipt) for receipt in (row.get("route_receipts") or [])]
        assert route_receipts
        assert all(receipt.get("satisfied") for receipt in route_receipts)
        assert all(receipt.get("required_tokens") for receipt in route_receipts)


def test_markdown_feedback_and_closeout_blockers_stay_honest() -> None:
    payload = _yaml(PACK_PATH)
    markdown = MARKDOWN_PATH.read_text(encoding="utf-8")
    feedback = FEEDBACK_PATH.read_text(encoding="utf-8")
    closeout = dict(payload.get("closeout") or {})
    blockers = [str(item) for item in (closeout.get("blockers") or [])]

    assert payload.get("status") in {"pass", "fail"}
    assert closeout.get("ready") is False
    assert "canonical design/queue rows are not marked complete yet" in blockers
    if dict(payload.get("desktop_client_readiness") or {}).get("status") != "ready":
        assert any("desktop_client" in blocker for blocker in blockers)
    assert "sheet_export_print_viewer_and_exchange" in markdown
    assert "sr6_supplements_designers_and_house_rules" in markdown
    assert "`desktop_client`" in markdown
    assert "desktop_client" in feedback

    lowered = f"{markdown}\n{feedback}".lower()
    for forbidden in (
        "task_local_telemetry",
        "active_run_handoff",
        "/var/lib/codex-fleet",
        "supervisor status",
        "supervisor eta",
        "operator telemetry",
    ):
        assert forbidden not in lowered


def test_canonical_monitors_pin_queue_alignment_and_fleet_gate_status() -> None:
    payload = _yaml(PACK_PATH)
    canonical_monitors = dict(payload.get("canonical_monitors") or {})
    queue_alignment = dict(canonical_monitors.get("queue_alignment") or {})
    fleet_gate = dict(canonical_monitors.get("fleet_gate") or {})
    summary = dict(payload.get("summary") or {})

    assert queue_alignment
    assert all(bool(value) for value in queue_alignment.values())
    assert fleet_gate == {
        "gate_status_pass": True,
        "route_local_output_closeout_status_pass": True,
    }
    assert summary.get("fleet_m143_gate_status") == "pass"
    assert summary.get("fleet_m143_closeout_status") == "pass"


def test_queue_and_registry_rows_match_the_active_m143_package() -> None:
    queue = _yaml(QUEUE_STAGING_PATH)
    design_queue = _yaml(DESIGN_QUEUE_STAGING_PATH)
    registry = _yaml(SUCCESSOR_REGISTRY_PATH)

    queue_row = next(item for item in queue.get("items") or [] if dict(item).get("package_id") == "next90-m143-ea-compile-route-specific-compare-packs-and-artifact-proofs-for-print-export")
    design_queue_row = next(item for item in design_queue.get("items") or [] if dict(item).get("package_id") == "next90-m143-ea-compile-route-specific-compare-packs-and-artifact-proofs-for-print-export")
    milestone = next(item for item in registry.get("milestones") or [] if int(dict(item).get("id") or 0) == 143)
    work_task = next(item for item in milestone.get("work_tasks") or [] if str(dict(item).get("id")) == "143.5")

    assert queue_row["status"] == design_queue_row["status"] == "not_started"
    assert queue_row["repo"] == design_queue_row["repo"] == "executive-assistant"
    assert queue_row["wave"] == design_queue_row["wave"] == "W22P"
    assert str(queue_row["work_task_id"]) == str(design_queue_row["work_task_id"]) == "143.5"
    assert list(queue_row["allowed_paths"] or []) == ["scripts", "feedback", "docs"]
    assert list(design_queue_row["allowed_paths"] or []) == ["scripts", "feedback", "docs"]
    assert list(queue_row["owned_surfaces"] or []) == ["compile_route_specific_compare_packs_and_artifact_proofs:ea"]
    assert list(design_queue_row["owned_surfaces"] or []) == ["compile_route_specific_compare_packs_and_artifact_proofs:ea"]
    assert work_task["owner"] == "executive-assistant"
    assert work_task["title"] == "Compile route-specific compare packs and artifact proofs for print, export, exchange, SR6 supplement, and house-rule workflows."


def test_verifier_script_accepts_the_current_packet() -> None:
    verifier = _module(VERIFY_PATH, "ea_next90_m143_verifier")
    assert verifier.main() == 0


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
