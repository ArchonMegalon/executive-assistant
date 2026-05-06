#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
import sys
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "ea") not in sys.path:
    sys.path.insert(0, str(ROOT / "ea"))

from app.yaml_inputs import load_yaml_dict

DOCS_ROOT = ROOT / "docs" / "chummer5a_parity_lab"

OUTPUT_PATH = DOCS_ROOT / "NEXT90_M143_ROUTE_SPECIFIC_COMPARE_PACKS.generated.yaml"
MARKDOWN_PATH = DOCS_ROOT / "NEXT90_M143_ROUTE_SPECIFIC_COMPARE_PACKS.generated.md"
COMPARE_PACKS_PATH = DOCS_ROOT / "compare_packs.yaml"
VETERAN_WORKFLOW_PACK_PATH = Path("/docker/fleet/docs/chummer5a-oracle/veteran_workflow_packs.yaml")
SUCCESSOR_REGISTRY_PATH = Path("/docker/chummercomplete/chummer-design/products/chummer/NEXT_90_DAY_PRODUCT_ADVANCE_REGISTRY.yaml")
DESIGN_QUEUE_PATH = Path("/docker/chummercomplete/chummer-design/products/chummer/NEXT_90_DAY_QUEUE_STAGING.generated.yaml")
FLEET_QUEUE_PATH = Path("/docker/fleet/.codex-studio/published/NEXT_90_DAY_QUEUE_STAGING.generated.yaml")
NEXT90_GUIDE_PATH = Path("/docker/chummercomplete/chummer-design/products/chummer/NEXT_90_DAY_PRODUCT_ADVANCE_GUIDE.md")
SCREENSHOT_GATE_PATH = Path("/docker/chummercomplete/chummer-presentation/.codex-studio/published/CHUMMER5A_SCREENSHOT_REVIEW_GATE.generated.json")
SECTION_HOST_PARITY_PATH = Path("/docker/chummercomplete/chummer-presentation/.codex-studio/published/SECTION_HOST_RULESET_PARITY.generated.json")
GENERATED_DIALOG_PARITY_PATH = Path("/docker/chummercomplete/chummer-presentation/.codex-studio/published/GENERATED_DIALOG_ELEMENT_PARITY.generated.json")
M114_RULE_STUDIO_PATH = Path("/docker/chummercomplete/chummer-presentation/.codex-studio/published/NEXT90_M114_UI_RULE_STUDIO.generated.json")
CORE_RECEIPTS_DOC_PATH = Path("/docker/chummercomplete/chummer-core-engine/docs/NEXT90_M143_EXPORT_PRINT_SUPPLEMENT_RULE_ENVIRONMENT_RECEIPTS.md")
FLEET_M143_GATE_PATH = Path("/docker/fleet/.codex-studio/published/NEXT90_M143_FLEET_ROUTE_LOCAL_OUTPUT_CLOSEOUT_GATES.generated.json")
FLAGSHIP_READINESS_PATH = Path("/docker/fleet/.codex-studio/published/FLAGSHIP_PRODUCT_READINESS.generated.json")

PACKAGE_ID = "next90-m143-ea-compile-route-specific-compare-packs-and-artifact-proofs-for-print-export"
TITLE = "Compile route-specific compare packs and artifact proofs for print, export, exchange, SR6 supplement, and house-rule workflows."
WORK_TASK_ID = "143.5"
MILESTONE_ID = 143
FRONTIER_ID = 5326878760
WAVE = "W22P"
OWNED_SURFACES = ["compile_route_specific_compare_packs_and_artifact_proofs:ea"]
ALLOWED_PATHS = ["scripts", "feedback", "docs"]

GUIDE_MARKERS = {
    "wave": "## Wave 22P - close human-tested parity proof and desktop executable trust before successor breadth",
    "milestone": "### 143. Direct parity proof for print/export/exchange and SR6 supplements or house-rule workflows",
    "exit": "Exit: print/export/exchange plus SR6 supplement/house-rule families all flip to direct `yes/yes` parity with current screenshot/runtime proof and receipt-backed outputs.",
}

TARGET_FAMILIES: dict[str, dict[str, Any]] = {
    "sheet_export_print_viewer_and_exchange": {
        "label": "Sheet export, print viewer, and exchange",
        "required_compare_artifacts": ["menu:open_for_printing", "menu:open_for_export", "menu:file_print_multiple"],
        "required_route_receipts": [
            {
                "route_id": "menu:open_for_printing",
                "source_key": "section_host_ruleset_parity",
                "required_tokens": ["open_for_printing"],
            },
            {
                "route_id": "menu:open_for_export",
                "source_key": "section_host_ruleset_parity",
                "required_tokens": ["open_for_export"],
            },
            {
                "route_id": "menu:file_print_multiple",
                "source_key": "generated_dialog_parity",
                "required_tokens": ["print_multiple"],
            },
            {
                "route_id": "receipt:workspace_exchange",
                "source_key": "core_receipts_doc",
                "required_tokens": [
                    "WorkspaceExchangeDeterministicReceipt",
                    "family:sheet_export_print_viewer_and_exchange",
                ],
            },
            {
                "route_id": "screenshot:print_export_exchange",
                "source_key": "screenshot_gate",
                "required_tokens": [
                    "print_export_exchange",
                    "open_for_printing_menu_route",
                    "open_for_export_menu_route",
                    "print_multiple_menu_route",
                ],
            },
        ],
        "evidence_paths": [
            str(VETERAN_WORKFLOW_PACK_PATH),
            str(SECTION_HOST_PARITY_PATH),
            str(GENERATED_DIALOG_PARITY_PATH),
            str(SCREENSHOT_GATE_PATH),
            str(CORE_RECEIPTS_DOC_PATH),
        ],
    },
    "sr6_supplements_designers_and_house_rules": {
        "label": "SR6 supplements, designers, and house rules",
        "required_compare_artifacts": ["workflow:sr6_supplements", "workflow:house_rules"],
        "required_route_receipts": [
            {
                "route_id": "workflow:sr6_supplements",
                "source_key": "core_receipts_doc",
                "required_tokens": [
                    "Sr6SuccessorLaneDeterministicReceipt",
                    "family:sr6_supplements_designers_and_house_rules",
                    "supplement",
                ],
            },
            {
                "route_id": "workflow:house_rules",
                "source_key": "core_receipts_doc",
                "required_tokens": [
                    "Sr6SuccessorLaneDeterministicReceipt",
                    "family:sr6_supplements_designers_and_house_rules",
                    "house-rule",
                ],
            },
            {
                "route_id": "surface:rule_environment_studio",
                "source_key": "m114_rule_studio",
                "required_tokens": ["rule_environment_studio"],
            },
            {
                "route_id": "screenshot:sr6_supplements_and_house_rules",
                "source_key": "screenshot_gate",
                "required_tokens": ["sr6_rule_environment", "sr6_supplements", "house_rules"],
            },
        ],
        "evidence_paths": [
            str(VETERAN_WORKFLOW_PACK_PATH),
            str(SCREENSHOT_GATE_PATH),
            str(M114_RULE_STUDIO_PATH),
            str(CORE_RECEIPTS_DOC_PATH),
        ],
    },
}

DESKTOP_REASON_MARKERS: dict[str, tuple[str, ...]] = {
    "sheet_export_print_viewer_and_exchange": (
        "desktop workflow execution gate",
        "chummer5a desktop workflow parity proof",
        "release channel publishes linux installer media",
        "release channel publishes windows installer media",
    ),
    "sr6_supplements_designers_and_house_rules": (
        "sr6 desktop workflow parity proof",
        "desktop workflow execution gate",
    ),
}


def _yaml(path: Path) -> dict[str, Any]:
    return load_yaml_dict(path)


def _json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8")) or {}
    return dict(payload) if isinstance(payload, dict) else {}


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _queue_row(path: Path) -> dict[str, Any]:
    text = _text(path)
    marker = f"package_id: {PACKAGE_ID}"
    start = text.find(marker)
    if start == -1:
        return {}
    block_start = text.rfind("- title:", 0, start)
    next_start = text.find("\n- title:", start)
    block = text[block_start:] if next_start == -1 else text[block_start:next_start]
    payload = yaml.safe_load(block) or []
    if isinstance(payload, list) and payload and isinstance(payload[0], dict):
        return dict(payload[0])
    return {}


def _registry_task(path: Path) -> dict[str, Any]:
    payload = _yaml(path)
    for milestone in payload.get("milestones") or []:
        if isinstance(milestone, dict) and int(milestone.get("id") or 0) == MILESTONE_ID:
            for task in milestone.get("work_tasks") or []:
                if isinstance(task, dict) and str(task.get("id") or "").strip() == WORK_TASK_ID:
                    return dict(task)
    return {}


def _family_row(compare_packs: dict[str, Any], family_id: str) -> dict[str, Any]:
    for row in compare_packs.get("families") or []:
        if isinstance(row, dict) and str(row.get("id") or "").strip() == family_id:
            return dict(row)
    return {}


def _workflow_family_row(workflow_pack: dict[str, Any], family_id: str) -> dict[str, Any]:
    for row in workflow_pack.get("families") or []:
        if isinstance(row, dict) and str(row.get("id") or "").strip() == family_id:
            return dict(row)
    return {}


def _generated_at(path: Path, payload: dict[str, Any] | None = None) -> str:
    payload = payload or {}
    direct = str(payload.get("generated_at") or payload.get("generatedAt") or "").strip()
    if direct:
        return direct
    return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_payload() -> dict[str, Any]:
    compare_packs = _yaml(COMPARE_PACKS_PATH)
    workflow_pack = _yaml(VETERAN_WORKFLOW_PACK_PATH)
    design_queue_row = _queue_row(DESIGN_QUEUE_PATH)
    fleet_queue_row = _queue_row(FLEET_QUEUE_PATH)
    registry_task = _registry_task(SUCCESSOR_REGISTRY_PATH)
    guide_text = _text(NEXT90_GUIDE_PATH)
    screenshot_gate = _json(SCREENSHOT_GATE_PATH)
    section_host_parity = _json(SECTION_HOST_PARITY_PATH)
    generated_dialog_parity = _json(GENERATED_DIALOG_PARITY_PATH)
    m114_rule_studio = _json(M114_RULE_STUDIO_PATH)
    fleet_gate = _json(FLEET_M143_GATE_PATH)
    readiness = _json(FLAGSHIP_READINESS_PATH)
    coverage = dict(readiness.get("coverage") or {})
    coverage_details = dict(readiness.get("coverage_details") or {})
    desktop_coverage = dict(coverage_details.get("desktop_client") or {})
    desktop_status = str(coverage.get("desktop_client") or desktop_coverage.get("status") or "")
    desktop_summary = str(desktop_coverage.get("summary") or "")
    desktop_reasons = [str(item) for item in (desktop_coverage.get("reasons") or [])]
    proof_texts = {
        "screenshot_gate": json.dumps(screenshot_gate, sort_keys=True),
        "section_host_ruleset_parity": json.dumps(section_host_parity, sort_keys=True),
        "generated_dialog_parity": json.dumps(generated_dialog_parity, sort_keys=True),
        "m114_rule_studio": json.dumps(m114_rule_studio, sort_keys=True),
        "core_receipts_doc": _text(CORE_RECEIPTS_DOC_PATH),
    }

    compare_rows: list[dict[str, Any]] = []
    unresolved: list[str] = []
    for family_id, spec in TARGET_FAMILIES.items():
        compare_row = _family_row(compare_packs, family_id)
        workflow_row = _workflow_family_row(workflow_pack, family_id)
        compare_artifacts = [str(item) for item in (compare_row.get("compare_artifacts") or [])]
        missing_compare_artifacts = [item for item in spec["required_compare_artifacts"] if item not in compare_artifacts]
        route_receipts: list[dict[str, Any]] = []
        missing_route_receipts: list[str] = []
        for receipt in spec["required_route_receipts"]:
            text = proof_texts[receipt["source_key"]]
            satisfied = all(token in text for token in receipt["required_tokens"])
            route_receipts.append(
                {
                    "route_id": receipt["route_id"],
                    "source_key": receipt["source_key"],
                    "required_tokens": list(receipt["required_tokens"]),
                    "satisfied": satisfied,
                }
            )
            if not satisfied:
                missing_route_receipts.append(receipt["route_id"])
        issues: list[str] = []
        if not compare_row:
            issues.append("EA compare_packs family row is missing.")
        if not workflow_row:
            issues.append("Fleet veteran workflow family row is missing.")
        if missing_compare_artifacts:
            issues.append("missing compare_artifacts: " + ", ".join(missing_compare_artifacts))
        if missing_route_receipts:
            issues.append("missing route-local receipts: " + ", ".join(missing_route_receipts))
        if issues:
            unresolved.append(f"{family_id}: {'; '.join(issues)}")
        relevant_desktop_reasons = [
            reason
            for reason in desktop_reasons
            if any(marker in reason.lower() for marker in DESKTOP_REASON_MARKERS.get(family_id, ()))
        ]
        compare_rows.append(
            {
                "family_id": family_id,
                "label": spec["label"],
                "compare_artifacts": compare_artifacts,
                "required_compare_artifacts": list(spec["required_compare_artifacts"]),
                "workflow_readiness_target": str(workflow_row.get("readiness_target") or ""),
                "expected_readiness_floor": str(compare_row.get("expected_readiness_floor") or ""),
                "evidence_paths": list(spec["evidence_paths"]),
                "desktop_client_dependency": {
                    "coverage_key": "desktop_client",
                    "coverage_status": desktop_status,
                    "coverage_summary": desktop_summary,
                    "relevant_reasons": relevant_desktop_reasons,
                },
                "route_receipts": route_receipts,
                "issues": issues,
            }
        )

    guide_checks = {name: marker in guide_text for name, marker in GUIDE_MARKERS.items()}
    guide_issues = [name for name, present in guide_checks.items() if not present]
    queue_checks = {
        "design_queue_present": bool(design_queue_row),
        "fleet_queue_present": bool(fleet_queue_row),
        "registry_task_present": bool(registry_task),
        "package_id_matches": str(design_queue_row.get("package_id") or "") == PACKAGE_ID
        and str(fleet_queue_row.get("package_id") or "") == PACKAGE_ID,
        "title_matches": str(design_queue_row.get("title") or "") == TITLE
        and str(fleet_queue_row.get("title") or "") == TITLE
        and str(registry_task.get("title") or "") == TITLE,
        "task_matches": str(design_queue_row.get("task") or "") == TITLE and str(fleet_queue_row.get("task") or "") == TITLE,
        "work_task_matches": str(design_queue_row.get("work_task_id") or "") == WORK_TASK_ID
        and str(fleet_queue_row.get("work_task_id") or "") == WORK_TASK_ID
        and str(registry_task.get("id") or "") == WORK_TASK_ID,
        "frontier_matches": int(design_queue_row.get("frontier_id") or 0) == FRONTIER_ID
        and int(fleet_queue_row.get("frontier_id") or 0) == FRONTIER_ID,
        "milestone_matches": int(design_queue_row.get("milestone_id") or 0) == MILESTONE_ID
        and int(fleet_queue_row.get("milestone_id") or 0) == MILESTONE_ID,
        "wave_matches": str(design_queue_row.get("wave") or "") == WAVE and str(fleet_queue_row.get("wave") or "") == WAVE,
        "repo_matches": str(design_queue_row.get("repo") or "") == "executive-assistant"
        and str(fleet_queue_row.get("repo") or "") == "executive-assistant"
        and str(registry_task.get("owner") or "") == "executive-assistant",
        "allowed_paths_match": list(design_queue_row.get("allowed_paths") or []) == ALLOWED_PATHS
        and list(fleet_queue_row.get("allowed_paths") or []) == ALLOWED_PATHS,
        "owned_surfaces_match": list(design_queue_row.get("owned_surfaces") or []) == OWNED_SURFACES
        and list(fleet_queue_row.get("owned_surfaces") or []) == OWNED_SURFACES,
    }
    fleet_gate_status = str(fleet_gate.get("status") or "")
    fleet_closeout_status = str(dict(fleet_gate.get("monitor_summary") or {}).get("route_local_output_closeout_status") or "")
    fleet_gate_checks = {
        "gate_status_pass": fleet_gate_status == "pass",
        "route_local_output_closeout_status_pass": fleet_closeout_status == "pass",
    }
    queue_closeout = {
        "design_queue_status": str(design_queue_row.get("status") or ""),
        "fleet_queue_status": str(fleet_queue_row.get("status") or ""),
        "registry_task_status": str(registry_task.get("status") or ""),
        "ready_to_mark_complete": str(design_queue_row.get("status") or "") == "complete"
        and str(fleet_queue_row.get("status") or "") == "complete"
        and str(registry_task.get("status") or "") == "complete",
    }
    closeout_blockers: list[str] = []
    if guide_issues:
        closeout_blockers.append("guide markers missing: " + ", ".join(guide_issues))
    if not all(queue_checks.values()):
        closeout_blockers.append("canonical package metadata drifted")
    if not all(fleet_gate_checks.values()):
        closeout_blockers.append("fleet route-local output closeout gate is not passing")
    if unresolved:
        closeout_blockers.extend(unresolved)
    if desktop_status != "ready":
        blocker = f"published readiness still reports desktop_client as {desktop_status or 'unknown'}"
        if desktop_summary:
            blocker += f": {desktop_summary}"
        closeout_blockers.append(blocker)
    if not queue_closeout["ready_to_mark_complete"]:
        closeout_blockers.append("canonical design/queue rows are not marked complete yet")

    packet_status = (
        "pass"
        if not unresolved and not guide_issues and all(queue_checks.values()) and all(fleet_gate_checks.values())
        else "fail"
    )

    return {
        "contract_name": "ea.next90_m143_route_specific_compare_packs",
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "package_id": PACKAGE_ID,
        "title": TITLE,
        "milestone_id": MILESTONE_ID,
        "work_task_id": WORK_TASK_ID,
        "frontier_id": FRONTIER_ID,
        "wave": WAVE,
        "owned_surfaces": list(OWNED_SURFACES),
        "allowed_paths": list(ALLOWED_PATHS),
        "status": packet_status,
        "summary": {
            "route_family_count": len(compare_rows),
            "route_family_pass_count": sum(1 for row in compare_rows if not row["issues"]),
            "fleet_m143_gate_status": fleet_gate_status,
            "fleet_m143_closeout_status": fleet_closeout_status,
            "desktop_client_status": desktop_status,
            "desktop_client_reason_count": len(desktop_reasons),
        },
        "source_inputs": {
            "ea_compare_packs": {"path": str(COMPARE_PACKS_PATH), "generated_at": _generated_at(COMPARE_PACKS_PATH)},
            "fleet_veteran_workflow_pack": {"path": str(VETERAN_WORKFLOW_PACK_PATH), "generated_at": _generated_at(VETERAN_WORKFLOW_PACK_PATH)},
            "next90_guide": {"path": str(NEXT90_GUIDE_PATH), "generated_at": _generated_at(NEXT90_GUIDE_PATH)},
            "design_queue": {"path": str(DESIGN_QUEUE_PATH), "generated_at": _generated_at(DESIGN_QUEUE_PATH)},
            "fleet_queue": {"path": str(FLEET_QUEUE_PATH), "generated_at": _generated_at(FLEET_QUEUE_PATH)},
            "registry": {"path": str(SUCCESSOR_REGISTRY_PATH), "generated_at": _generated_at(SUCCESSOR_REGISTRY_PATH)},
            "screenshot_gate": {"path": str(SCREENSHOT_GATE_PATH), "generated_at": _generated_at(SCREENSHOT_GATE_PATH, screenshot_gate)},
            "section_host_ruleset_parity": {"path": str(SECTION_HOST_PARITY_PATH), "generated_at": _generated_at(SECTION_HOST_PARITY_PATH, section_host_parity)},
            "generated_dialog_parity": {"path": str(GENERATED_DIALOG_PARITY_PATH), "generated_at": _generated_at(GENERATED_DIALOG_PARITY_PATH, generated_dialog_parity)},
            "m114_rule_studio": {"path": str(M114_RULE_STUDIO_PATH), "generated_at": _generated_at(M114_RULE_STUDIO_PATH, m114_rule_studio)},
            "core_receipts_doc": {"path": str(CORE_RECEIPTS_DOC_PATH), "generated_at": _generated_at(CORE_RECEIPTS_DOC_PATH)},
            "fleet_m143_gate": {"path": str(FLEET_M143_GATE_PATH), "generated_at": _generated_at(FLEET_M143_GATE_PATH, fleet_gate)},
            "flagship_readiness": {"path": str(FLAGSHIP_READINESS_PATH), "generated_at": _generated_at(FLAGSHIP_READINESS_PATH, readiness)},
        },
        "canonical_monitors": {
            "guide_markers": guide_checks,
            "queue_alignment": queue_checks,
            "fleet_gate": fleet_gate_checks,
            "queue_closeout": queue_closeout,
        },
        "desktop_client_readiness": {
            "coverage_key": "desktop_client",
            "status": desktop_status,
            "summary": desktop_summary,
            "reason_count": len(desktop_reasons),
            "reasons": desktop_reasons,
        },
        "family_route_compare_packs": compare_rows,
        "closeout": {
            "ready": not closeout_blockers,
            "blockers": closeout_blockers,
            "notes": [
                "This EA packet compiles route-local compare proof for milestone 143 using current Fleet and owner-repo receipts.",
                "It does not overwrite owner-repo executable proof or pretend the canonical queue closeout already happened.",
            ],
        },
    }


def _markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Next90 M143 EA Route-Specific Compare Packs",
        "",
        f"- status: `{payload.get('status', '')}`",
        f"- ready: `{dict(payload.get('closeout') or {}).get('ready', False)}`",
        "",
        "## Desktop readiness",
        f"- `desktop_client`: `{dict(payload.get('desktop_client_readiness') or {}).get('status', '')}`",
        f"- summary: {dict(payload.get('desktop_client_readiness') or {}).get('summary', '')}",
        "",
        "## Family summary",
    ]
    for row in payload.get("family_route_compare_packs") or []:
        current = dict(row)
        lines.append(f"- `{current.get('family_id', '')}`: {'pass' if not current.get('issues') else 'fail'}")
        dependency = dict(current.get("desktop_client_dependency") or {})
        if dependency.get("relevant_reasons"):
            lines.append(
                f"  - desktop dependency: `{dependency.get('coverage_status', '')}` ({len(list(dependency.get('relevant_reasons') or []))} route-relevant blocker(s))"
            )
        for receipt in current.get("route_receipts") or []:
            route = dict(receipt)
            lines.append(f"  - `{route.get('route_id', '')}` -> `{'ok' if route.get('satisfied') else 'missing'}`")
    lines.extend(["", "## Closeout blockers"])
    blockers = list(dict(payload.get("closeout") or {}).get("blockers") or [])
    if blockers:
        for blocker in blockers:
            lines.append(f"- {blocker}")
    else:
        lines.append("- none")
    return "\n".join(lines) + "\n"


def main() -> int:
    payload = build_payload()
    OUTPUT_PATH.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    MARKDOWN_PATH.write_text(_markdown(payload), encoding="utf-8")
    print(str(OUTPUT_PATH))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
