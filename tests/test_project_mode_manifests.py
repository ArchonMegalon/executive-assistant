from __future__ import annotations

import json
from pathlib import Path

from scripts.materialize_project_mode_manifests import project_modes, show_surface_manifest
from scripts.verify_project_mode_manifests import main as verify_project_modes


ROOT = Path(__file__).resolve().parents[1]


def test_project_modes_name_each_repo_plane_and_first_value_gate() -> None:
    payload = project_modes()
    modes = {item["key"]: item for item in payload["modes"]}
    memorial_receipt = json.loads(
        (ROOT / ".codex-studio/published/memorial_voice_roundtrip_exit_gate.generated.json").read_text(encoding="utf-8")
    )
    expected_memorial_status = "shipping_memorial" if memorial_receipt.get("status") == "pass" else "separate_risk_zone"

    assert set(modes) == {"EA_CORE", "MEMORIAL", "PROVIDER_LAB", "CHUMMER_RELEASE_CONTROL", "PROPERTY"}
    assert modes["EA_CORE"]["status"] == "shipping_core"
    assert modes["EA_CORE"]["hard_gate"] == "tests/e2e/test_ea_first_value_journey.py"
    assert modes["MEMORIAL"]["status"] == expected_memorial_status
    assert "/memorials/" in modes["MEMORIAL"]["route_prefixes"]


def test_show_surface_manifest_keeps_ea_core_demo_from_lab_and_memorial_surfaces() -> None:
    payload = show_surface_manifest()

    assert payload["demo_mode"] == "ea_core"
    assert "/app/today" in payload["allowed_surfaces"]
    assert "/memorials/*" in payload["forbidden_surfaces"]
    assert "/memorials/files/*" in payload["forbidden_surfaces"]
    assert "JoggAI" in payload["forbidden_provider_names"]
    assert "Unmixr" in payload["forbidden_provider_names"]


def test_materialized_project_mode_manifests_verify() -> None:
    assert verify_project_modes() == 0
