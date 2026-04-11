from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GATE_PATH = ROOT / ".codex-design" / "repo" / "EA_FLAGSHIP_RELEASE_GATE.json"
TRUTH_PLANE_PATH = ROOT / ".codex-design" / "repo" / "EA_FLAGSHIP_TRUTH_PLANE.md"
GENERATED_GATE_PATH = ROOT / ".codex-design" / "product" / "EA_FLAGSHIP_RELEASE_GATE.generated.json"
RELEASE_CHECKLIST_PATH = ROOT / "RELEASE_CHECKLIST.md"
PRODUCT_RELEASE_CHECKLIST_PATH = ROOT / "PRODUCT_RELEASE_CHECKLIST.md"
README_PATH = ROOT / "README.md"
RUNBOOK_PATH = ROOT / "RUNBOOK.md"


def test_flagship_truth_plane_seed_points_at_browser_workflow_proof() -> None:
    gate = json.loads(GATE_PATH.read_text(encoding="utf-8"))

    assert gate["product"] == "executive-assistant"
    assert gate["surface"] == "flagship_release_control"
    assert gate["truth_plane"]["source"] == ".codex-design/repo/EA_FLAGSHIP_TRUTH_PLANE.md"
    assert gate["truth_plane"]["legacy_history"] == "MILESTONE.json"

    browser_proof = gate["browser_workflow_proof"]["evidence_sources"]
    evidence_index = {entry["file"]: set(entry["cases"]) for entry in browser_proof}

    assert "tests/test_product_browser_journeys.py" in evidence_index
    assert "tests/e2e/test_product_workflows.py" in evidence_index
    assert "test_workspace_pages_render_seeded_product_objects" in evidence_index["tests/test_product_browser_journeys.py"]
    assert "test_browser_action_routes_match_rendered_forms" in evidence_index["tests/test_product_browser_journeys.py"]
    assert "test_activation_and_memo_flow_in_real_browser" in evidence_index["tests/e2e/test_product_workflows.py"]
    assert "test_draft_and_commitment_workflows_in_real_browser" in evidence_index["tests/e2e/test_product_workflows.py"]

    conditions = gate["release_claim"]["required_conditions"]
    assert any("browser workflow proof" in condition for condition in conditions)
    assert any("release asset verification" in condition for condition in conditions)
    assert any("MILESTONE green" in condition or "MILESTONE" in condition for condition in conditions)

    expected_signals = gate["browser_workflow_proof"]["expected_browser_signals"]
    assert any("Google-first activation" in signal for signal in expected_signals)
    assert any("Morning Memo" in signal for signal in expected_signals)
    assert any("placeholder cards" in signal for signal in expected_signals)


def test_flagship_release_docs_cite_the_truth_plane_instead_of_milestone_as_oracle() -> None:
    truth_plane = TRUTH_PLANE_PATH.read_text(encoding="utf-8")
    release_checklist = RELEASE_CHECKLIST_PATH.read_text(encoding="utf-8")
    product_release_checklist = PRODUCT_RELEASE_CHECKLIST_PATH.read_text(encoding="utf-8")
    readme = README_PATH.read_text(encoding="utf-8")
    runbook = RUNBOOK_PATH.read_text(encoding="utf-8")

    assert "EA_FLAGSHIP_TRUTH_PLANE.md" in truth_plane
    assert "MILESTONE.json" in truth_plane
    assert "EA_FLAGSHIP_RELEASE_GATE.json" in release_checklist
    assert "EA_FLAGSHIP_RELEASE_GATE.generated.json" in release_checklist
    assert "EA_FLAGSHIP_TRUTH_PLANE.md" in release_checklist
    assert "EA_FLAGSHIP_RELEASE_GATE.json" in product_release_checklist
    assert "EA_FLAGSHIP_RELEASE_GATE.generated.json" in product_release_checklist
    assert "EA_FLAGSHIP_TRUTH_PLANE.md" in product_release_checklist
    assert "EA_FLAGSHIP_TRUTH_PLANE.md" in readme
    assert "EA_FLAGSHIP_RELEASE_GATE.json" in readme
    assert "EA_FLAGSHIP_RELEASE_GATE.generated.json" in readme
    assert "scripts/materialize_ea_flagship_release_gate.py" in readme
    assert "EA_FLAGSHIP_TRUTH_PLANE.md" in runbook
    assert "EA_FLAGSHIP_RELEASE_GATE.generated.json" in runbook
    assert "scripts/materialize_ea_flagship_release_gate.py" in runbook


def test_flagship_release_receipt_is_materialized_or_expected_to_materialize() -> None:
    assert GENERATED_GATE_PATH.exists()
