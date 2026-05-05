#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from materialize_next90_m135_ea_closure_coverage import OUTPUT_PATH, build_payload, without_generated_at

REPO_ROOT = Path(__file__).resolve().parents[1]
PACK_PATH = REPO_ROOT / "docs/chummer_closure_coverage/CHUMMER_CLOSURE_COVERAGE_PACK.yaml"
HANDOFF_PATH = REPO_ROOT / "docs/chummer_closure_coverage/SUCCESSOR_HANDOFF_CLOSEOUT.yaml"
README_PATH = REPO_ROOT / "docs/chummer_closure_coverage/README.md"
FEEDBACK_PATH = REPO_ROOT / "feedback/2026-05-05-next90-m135-ea-closure-coverage-progress.md"
DESIGN_REGISTRY_PATH = Path("/docker/chummercomplete/chummer-design/products/chummer/NEXT_90_DAY_PRODUCT_ADVANCE_REGISTRY.yaml")
DESIGN_QUEUE_PATH = Path("/docker/chummercomplete/chummer-design/products/chummer/NEXT_90_DAY_QUEUE_STAGING.generated.yaml")
FLEET_QUEUE_PATH = Path("/docker/fleet/.codex-studio/published/NEXT_90_DAY_QUEUE_STAGING.generated.yaml")
EXPECTED_ANCHORS = [
    "governor_operator_packet_contract",
    "operator_safe_followthrough_receipt",
    "organizer_followthrough_receipt",
    "launch_followthrough_contract",
    "participation_followthrough_receipt",
    "explain_companion_contract",
    "provider_digest_script",
    "public_copy_guard_script",
]
EXPECTED_PROOF_PATHS = [
    "/docker/EA/docs/chummer_closure_coverage/CHUMMER_CLOSURE_COVERAGE_PACK.yaml",
    "/docker/EA/docs/chummer_closure_coverage/README.md",
    "/docker/EA/docs/chummer_closure_coverage/SUCCESSOR_HANDOFF_CLOSEOUT.yaml",
    "/docker/EA/scripts/materialize_next90_m135_ea_closure_coverage.py",
    "/docker/EA/scripts/verify_next90_m135_ea_closure_coverage.py",
    "/docker/EA/.codex-studio/published/NEXT90_M135_EA_CLOSURE_COVERAGE.generated.json",
    "/docker/EA/feedback/2026-05-05-next90-m135-ea-closure-coverage-progress.md",
]
FORBIDDEN_MARKERS = [
    "TODO",
    "TBD",
    "placeholder",
]
EXPECTED_EVIDENCE_SUBSTRINGS = [
    "/docker/EA/docs/chummer_closure_coverage/CHUMMER_CLOSURE_COVERAGE_PACK.yaml",
    "/docker/EA/.codex-studio/published/NEXT90_M135_EA_CLOSURE_COVERAGE.generated.json now summarizes the live M106, M113, M118, M120, M129, and M145 source contracts",
    "/docker/EA/scripts/chummer6_provider_readiness.py and /docker/EA/scripts/chummer6_guide_worker.py remain explicit bounded source surfaces",
    "python3 scripts/materialize_next90_m135_ea_closure_coverage.py",
]


def _load_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text())


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _find_registry_row(rows: list[dict[str, Any]]) -> dict[str, Any]:
    for milestone in rows:
        for row in milestone.get("work_tasks", []):
            if str(row.get("id")) == "135.10":
                return row
    raise AssertionError("Registry row 135.10 not found")


def _verify_queue_row(path: Path) -> None:
    text = path.read_text()
    marker = "work_task_id: '135.10'"
    start = text.find(marker)
    _assert(start != -1, f"{path} missing 135.10 block")
    block_start = text.rfind("- title:", 0, start)
    _assert(block_start != -1, f"{path} missing block start")
    next_start = text.find("\n- title:", start)
    block = text[block_start:] if next_start == -1 else text[block_start:next_start]
    required_snippets = [
        "package_id: next90-m135-ea-close-ea-compile-signal-companion-public-copy-operator-p",
        "frontier_id: 4019469848",
        "milestone_id: 135",
        "status: complete",
        "wave: W22",
        "repo: executive-assistant",
        "completion_action: verify_closed_package_only",
        "landed_commit: unlanded",
        "closure bundle",
        "queue/registry",
        "allowed_paths:\n  - scripts\n  - feedback\n  - docs",
        "owned_surfaces:\n  - close_ea_compile_signal_companion:executive_assistant",
    ]
    for snippet in required_snippets:
        _assert(snippet in block, f"{path} missing snippet: {snippet}")
    for proof_path in EXPECTED_PROOF_PATHS:
        _assert(proof_path in block, f"{path} missing proof path: {proof_path}")


def main() -> int:
    for path in [PACK_PATH, HANDOFF_PATH, README_PATH, FEEDBACK_PATH, OUTPUT_PATH]:
        _assert(path.exists(), f"Missing required file: {path}")
    expected = without_generated_at(build_payload())
    actual = without_generated_at(json.loads(OUTPUT_PATH.read_text()))
    _assert(actual == expected, "Generated proof drift")
    _assert(actual.get("status") == "passed", "Proof status must pass")
    _assert(actual.get("truth_bundle", {}).get("source_anchor_ids") == EXPECTED_ANCHORS, "Anchor ids drifted")
    for item in actual.get("source_truth_status", []):
        _assert(item.get("present"), f"Missing anchor source: {item.get('anchor_id')}")
        if item.get("kind") == "bounded_script":
            _assert(item.get("markers_ok"), f"Marker drift: {item.get('anchor_id')}")
    for family in actual.get("coverage_families", []):
        _assert(family.get("coverage_state") == "covered", f"Coverage family blocked: {family.get('family_id')}")
    for path in [PACK_PATH, HANDOFF_PATH, FEEDBACK_PATH, OUTPUT_PATH]:
        text = path.read_text()
        for marker in FORBIDDEN_MARKERS:
            _assert(marker not in text, f"Forbidden marker {marker} in {path}")
    registry = _load_yaml(DESIGN_REGISTRY_PATH)
    row = _find_registry_row(registry["milestones"])
    _assert(row.get("owner") == "executive-assistant", "Registry owner drift")
    _assert(row.get("status") == "complete", "Registry status")
    _assert(row.get("title") == "Close EA compile, signal, companion, public copy, operator packet, provider digest, and followthrough coverage without canon authority.", "Registry title")
    evidence = row.get("evidence")
    _assert(isinstance(evidence, list) and len(evidence) == 4, "Registry evidence shape")
    normalized_evidence = [item.replace("`", "") for item in evidence]
    for snippet in EXPECTED_EVIDENCE_SUBSTRINGS:
        _assert(any(snippet in item for item in normalized_evidence), f"Registry evidence missing snippet: {snippet}")
    _verify_queue_row(DESIGN_QUEUE_PATH)
    _verify_queue_row(FLEET_QUEUE_PATH)
    handoff = _load_yaml(HANDOFF_PATH)
    _assert(handoff.get("status") == "ea_scope_complete", "Handoff status")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
