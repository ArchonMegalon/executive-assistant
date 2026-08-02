from __future__ import annotations

import json

from scripts import materialize_project_mode_manifests as materialize
from scripts import verify_project_mode_manifests as verify


def test_project_modes_are_owned_ea_planes_only() -> None:
    payload = materialize.project_modes()
    modes = {item["key"]: item for item in payload["modes"]}

    assert set(modes) == {
        "EA_CORE",
        "PROVIDER_LAB",
        "CHUMMER_RELEASE_CONTROL",
        "PROPERTY",
    }
    assert modes["EA_CORE"]["status"] == "shipping_core"
    assert modes["EA_CORE"]["hard_gate"] == "tests/e2e/test_ea_first_value_journey.py"


def test_show_surface_manifest_keeps_core_demo_bounded() -> None:
    payload = materialize.show_surface_manifest()

    assert payload["demo_mode"] == "ea_core"
    assert "/app/today" in payload["allowed_surfaces"]
    assert "/properties*" in payload["forbidden_surfaces"]
    assert "Unmixr" in payload["forbidden_provider_names"]
    assert any("one repository" in note for note in payload["operator_notes"])


def test_materialized_project_mode_manifests_verify(
    tmp_path, monkeypatch
) -> None:
    modes_path = tmp_path / "PROJECT_MODES.generated.json"
    show_path = tmp_path / "SHOW_SURFACE_MANIFEST.generated.json"
    monkeypatch.setattr(materialize, "PROJECT_MODES_OUTPUT", modes_path)
    monkeypatch.setattr(materialize, "SHOW_SURFACE_OUTPUT", show_path)
    monkeypatch.setattr(verify, "PROJECT_MODES", modes_path)
    monkeypatch.setattr(verify, "SHOW_SURFACE", show_path)
    monkeypatch.setattr(materialize, "_git_head", lambda: "HEAD")
    monkeypatch.setattr(verify, "resolve_source_state_head", lambda _root: "HEAD")

    assert materialize.main() == 0
    assert verify.main() == 0
    assert json.loads(modes_path.read_text(encoding="utf-8"))["source_git_head"] == "HEAD"
