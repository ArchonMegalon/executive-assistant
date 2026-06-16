from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import source_state_head
from scripts.materialize_project_mode_manifests import _fresh_enough, _git_head as _source_state_head, _recorded_source_head
from scripts.materialize_project_mode_manifests import main as materialize_project_modes
from scripts.materialize_project_mode_manifests import project_modes, show_surface_manifest
from scripts.verify_project_mode_manifests import main as verify_project_modes


ROOT = Path(__file__).resolve().parents[1]

def test_project_modes_name_each_repo_plane_and_first_value_gate() -> None:
    payload = project_modes()
    modes = {item["key"]: item for item in payload["modes"]}
    memorial_receipt = json.loads(
        (ROOT / ".codex-studio/published/memorial_voice_roundtrip_exit_gate.generated.json").read_text(encoding="utf-8")
    )
    current_head = _source_state_head()
    expected_memorial_status = (
        "shipping_memorial"
        if memorial_receipt.get("status") == "pass"
        and _fresh_enough(_recorded_source_head(memorial_receipt), current_head=current_head)
        else "separate_risk_zone"
    )

    assert set(modes) == {"EA_CORE", "MEMORIAL", "PROVIDER_LAB", "CHUMMER_RELEASE_CONTROL", "PROPERTY"}
    assert modes["EA_CORE"]["status"] == "shipping_core"
    assert modes["EA_CORE"]["hard_gate"] == "tests/e2e/test_ea_first_value_journey.py"
    assert modes["MEMORIAL"]["status"] == expected_memorial_status
    assert modes["MEMORIAL"]["hard_gate"] == "make memorial-gold-gates"
    assert modes["MEMORIAL"]["hard_gates"] == [
        ".codex-studio/published/memorial_voice_roundtrip_exit_gate.generated.json",
        ".codex-studio/published/memorial_voice_roundtrip_public_origin.generated.json",
        ".codex-studio/published/memorial_realtime_browser_public_origin.generated.json",
    ]
    assert modes["MEMORIAL"]["local_release_gate"] == ".codex-studio/published/memorial_voice_roundtrip_exit_gate.generated.json"
    assert ".codex-studio/published/memorial_voice_roundtrip_public_origin.generated.json" in modes["MEMORIAL"]["public_gold_gates"]
    assert ".codex-studio/published/memorial_realtime_browser_public_origin.generated.json" in modes["MEMORIAL"]["public_gold_gates"]
    assert ".codex-studio/published/memorial_room_audio_public_origin.generated.json" in modes["MEMORIAL"]["public_gold_gates"]
    public_gold_gate_paths = [ROOT / path for path in modes["MEMORIAL"]["public_gold_gates"]]
    expected_public_gold_status = (
        "public_origin_gold_pass"
        if all(
            json.loads(path.read_text(encoding="utf-8")).get("status") == "pass"
            and _fresh_enough(
                _recorded_source_head(json.loads(path.read_text(encoding="utf-8"))),
                current_head=current_head,
            )
            for path in public_gold_gate_paths
            if path.is_file()
        )
        and all(path.is_file() for path in public_gold_gate_paths)
        else "public_origin_gold_blocked"
    )
    assert modes["MEMORIAL"]["public_gold_status"] == expected_public_gold_status
    assert "No internet search for Manfred" in modes["MEMORIAL"]["purpose"]
    assert "/memorials/" in modes["MEMORIAL"]["route_prefixes"]


def test_show_surface_manifest_keeps_ea_core_demo_from_lab_and_memorial_surfaces() -> None:
    payload = show_surface_manifest()

    assert payload["demo_mode"] == "ea_core"
    assert "/app/today" in payload["allowed_surfaces"]
    assert "/memorials/*" in payload["forbidden_surfaces"]
    assert "/memorials/files/*" in payload["forbidden_surfaces"]
    assert "JoggAI" in payload["forbidden_provider_names"]
    assert "Unmixr" in payload["forbidden_provider_names"]
    assert any("Memorial public-origin gold" in note for note in payload["operator_notes"])


def test_materialized_project_mode_manifests_verify() -> None:
    assert materialize_project_modes() == 0
    assert verify_project_modes() == 0


def test_project_modes_source_head_skips_generated_only_head_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    import scripts.materialize_project_mode_manifests as module

    monkeypatch.setattr(module, "resolve_source_state_head", lambda root: "SOURCE_HEAD")

    payload = module.project_modes()

    assert payload["source_git_head"] == "SOURCE_HEAD"


def test_source_state_head_skips_verifier_and_generated_only_commits(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = {
        ("rev-parse", "HEAD"): "VERIFY_HEAD\n",
        ("rev-list", "--max-count=128", "HEAD"): "VERIFY_HEAD\nSOURCE_HEAD\n",
        ("rev-list", "--parents", "-n", "1", "VERIFY_HEAD"): "VERIFY_HEAD SOURCE_HEAD\n",
        (
            "diff",
            "--name-only",
            "SOURCE_HEAD..VERIFY_HEAD",
        ): "scripts/verify_project_mode_manifests.py\n.codex-design/product/PROJECT_MODES.generated.json\n",
        ("rev-list", "--parents", "-n", "1", "SOURCE_HEAD"): "SOURCE_HEAD BASE_HEAD\n",
        ("diff", "--name-only", "BASE_HEAD..SOURCE_HEAD"): "scripts/materialize_project_mode_manifests.py\n",
    }

    def _fake_run(args, **kwargs):
        key = tuple(args[3:])
        return SimpleNamespace(stdout=responses.get(key, ""), returncode=0)

    monkeypatch.setattr(source_state_head.subprocess, "run", _fake_run)

    assert source_state_head.resolve_source_state_head(ROOT) == "SOURCE_HEAD"
