#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from app.yaml_inputs import load_yaml_dict

REPO_ROOT = Path(__file__).resolve().parents[1]
PACK_PATH = REPO_ROOT / "docs/chummer_closure_coverage/CHUMMER_CLOSURE_COVERAGE_PACK.yaml"
HANDOFF_PATH = REPO_ROOT / "docs/chummer_closure_coverage/SUCCESSOR_HANDOFF_CLOSEOUT.yaml"
OUTPUT_PATH = REPO_ROOT / ".codex-studio/published/NEXT90_M135_EA_CLOSURE_COVERAGE.generated.json"


def _load_yaml(path: Path) -> dict[str, Any]:
    return load_yaml_dict(path)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _read_text(path: Path) -> str:
    return path.read_text()


def _anchor_status(anchor: dict[str, Any]) -> dict[str, Any]:
    path = Path(anchor["path"])
    present = path.exists()
    status: dict[str, Any] = {
        "anchor_id": anchor["anchor_id"],
        "path": str(path),
        "kind": anchor["kind"],
        "present": present,
    }
    if not present:
        status["state"] = "missing"
        return status
    if anchor["kind"] == "yaml_contract":
        data = _load_yaml(path)
        status.update(
            {
                "state": data.get("status", "present"),
                "package_id": data.get("package_id"),
                "owned_surfaces": data.get("owned_surfaces", []),
            }
        )
        return status
    if anchor["kind"] == "json_receipt":
        data = _load_json(path)
        package_proof = data.get("package_proof", {})
        handoff = data.get("handoff_status", {})
        status.update(
            {
                "state": data.get("status", "present"),
                "package_id": package_proof.get("package_id"),
                "package_title": package_proof.get("title"),
                "handoff_status": handoff.get("status", data.get("handoff_status")),
            }
        )
        return status
    if anchor["kind"] == "bounded_script":
        text = _read_text(path)
        missing = [marker for marker in anchor.get("required_markers", []) if marker not in text]
        status.update(
            {
                "state": "present" if not missing else "marker_drift",
                "markers_ok": not missing,
                "required_markers": anchor.get("required_markers", []),
                "missing_markers": missing,
            }
        )
        return status
    status["state"] = "unsupported_kind"
    return status


def _family_status(family: dict[str, Any], anchor_states: dict[str, dict[str, Any]]) -> dict[str, Any]:
    required = family.get("required_anchors", [])
    blockers: list[str] = []
    details: list[dict[str, Any]] = []
    for anchor_id in required:
        state = anchor_states[anchor_id]
        details.append({
            "anchor_id": anchor_id,
            "path": state["path"],
            "state": state["state"],
        })
        if not state.get("present"):
            blockers.append(f"{anchor_id}:missing")
        elif state["kind"] == "bounded_script" and not state.get("markers_ok", False):
            blockers.append(f"{anchor_id}:marker_drift")
        elif state["kind"] in {"yaml_contract", "json_receipt"} and state.get("state") == "missing":
            blockers.append(f"{anchor_id}:missing")
    return {
        "family_id": family["family_id"],
        "required_anchors": required,
        "coverage_state": "covered" if not blockers else "blocked",
        "blockers": blockers,
        "anchor_details": details,
    }


def build_payload() -> dict[str, Any]:
    pack = _load_yaml(PACK_PATH)
    handoff = _load_yaml(HANDOFF_PATH)
    bundle = pack["governed_truth_bundle"]
    anchor_states = {
        anchor["anchor_id"]: _anchor_status(anchor)
        for anchor in bundle["source_anchors"]
    }
    family_states = [
        _family_status(family, anchor_states)
        for family in bundle["closure_families"]
    ]
    overall_status = "passed" if all(item["coverage_state"] == "covered" for item in family_states) else "blocked"
    return {
        "contract_name": "ea.next90_m135_closure_coverage",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": overall_status,
        "proof_kind": "repo_local_closure_bundle",
        "package_proof": {
            "package_id": pack["package_id"],
            "title": pack["title"],
            "milestone_id": pack["milestone_id"],
            "work_task_id": pack["work_task_id"],
            "frontier_id": pack["frontier_id"],
            "wave": pack["wave"],
            "allowed_paths": pack["allowed_paths"],
            "owned_surfaces": pack["owned_surfaces"],
        },
        "truth_bundle": {
            "bundle_id": bundle["bundle_id"],
            "source_anchor_ids": [anchor["anchor_id"] for anchor in bundle["source_anchors"]],
        },
        "guardrails": {
            "claim_guard_rules": bundle["claim_guard_rules"],
            "runtime_safety_markers": bundle["runtime_safety_markers"],
            "active_package_status": pack["status"],
        },
        "source_truth_status": list(anchor_states.values()),
        "coverage_families": family_states,
        "handoff_status": handoff,
    }


def without_generated_at(payload: dict[str, Any]) -> dict[str, Any]:
    clone = json.loads(json.dumps(payload))
    clone.pop("generated_at", None)
    return clone


def main() -> int:
    payload = build_payload()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
