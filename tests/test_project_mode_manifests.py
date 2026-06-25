from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import source_state_head
from scripts.materialize_project_mode_manifests import _fresh_enough, _git_head as _source_state_head, _receipt_passes, _recorded_source_head, _room_receipt_passes
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
    public_voice_path, public_browser_path, room_path = public_gold_gate_paths
    expected_public_gold_status = (
        "public_origin_gold_pass"
        if _receipt_passes(public_voice_path, current_head=current_head)
        and _receipt_passes(public_browser_path, current_head=current_head)
        and _room_receipt_passes(room_path, current_head=current_head)
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


def test_project_modes_reject_old_room_audio_receipts_without_spoken_loop_checks(tmp_path: Path) -> None:
    receipt = {
        "status": "pass",
        "source_git_head": "HEAD",
        "proof_type": "manual_room_attestation",
        "manual_attestation": {
            "attestation_id": "room-review-001",
            "signed_at": "2026-06-18T12:00:00Z",
            "ci_must_not_auto_assert": True,
        },
        "checks": {
            "actual_device_checked": True,
            "actual_speaker_checked": True,
            "first_syllable_not_clipped": True,
            "intelligibility_confirmed": True,
            "answer_text_fallback_visible": True,
            "no_internet_search_confirmed": True,
        },
    }
    path = tmp_path / "room.json"
    path.write_text(json.dumps(receipt), encoding="utf-8")

    assert _room_receipt_passes(path, current_head="HEAD") is False

    receipt["checks"].update(
        {
            "normal_spoken_turn_confirmed": True,
            "interruption_behavior_confirmed": True,
            "retry_path_confirmed": True,
        }
    )
    path.write_text(json.dumps(receipt), encoding="utf-8")

    assert _room_receipt_passes(path, current_head="HEAD") is True


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


def test_source_worktree_metadata_reports_source_dirty_without_generated_noise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = {
        (
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
        ): "\n".join(
            [
                " M .codex-design/product/PROJECT_MODES.generated.json",
                " M .codex-studio/published/memorial_stt_provider_benchmark.generated.json",
                "?? ea/.runtime/voice-preview/sample.wav",
                " M app/api/routes/public_memorials.py",
                "?? scripts/source_state_head.py",
                "R  old_service.py -> app/services/new_service.py",
            ]
        )
        + "\n",
    }

    def _fake_run(args, **kwargs):
        key = tuple(args[3:])
        return SimpleNamespace(stdout=responses.get(key, ""), returncode=0)

    monkeypatch.setattr(source_state_head.subprocess, "run", _fake_run)

    metadata = source_state_head.source_worktree_metadata(ROOT, dirty_path_limit=1)

    assert metadata["source_worktree_dirty"] is True
    assert metadata["source_dirty_count"] == 2
    assert metadata["source_dirty_files"] == ["app/api/routes/public_memorials.py"]
    assert metadata["source_dirty_omitted_count"] == 1
    assert metadata["source_dirty_status_sha256"]
