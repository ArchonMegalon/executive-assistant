from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import source_state_head
from scripts.materialize_project_mode_manifests import _fresh_enough, _git_head as _source_state_head, _memorial_flagship_experience_gold_status, _memorial_public_voice_gold_status, _receipt_passes, _recorded_source_head, _room_receipt_passes, _source_fingerprint, _spatial_receipt_passes
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
        ".codex-studio/published/memorial_spatial_tour_public_origin.generated.json",
    ]
    assert modes["MEMORIAL"]["local_release_gate"] == ".codex-studio/published/memorial_voice_roundtrip_exit_gate.generated.json"
    assert ".codex-studio/published/memorial_voice_roundtrip_public_origin.generated.json" in modes["MEMORIAL"]["public_gold_gates"]
    assert ".codex-studio/published/memorial_realtime_browser_public_origin.generated.json" in modes["MEMORIAL"]["public_gold_gates"]
    assert ".codex-studio/published/memorial_room_audio_public_origin.generated.json" in modes["MEMORIAL"]["public_gold_gates"]
    assert ".codex-studio/published/memorial_spatial_tour_public_origin.generated.json" in modes["MEMORIAL"]["public_gold_gates"]
    assert modes["MEMORIAL"]["public_voice_gold_gates"] == [
        ".codex-studio/published/memorial_voice_roundtrip_public_origin.generated.json",
        ".codex-studio/published/memorial_realtime_browser_public_origin.generated.json",
        ".codex-studio/published/memorial_room_audio_public_origin.generated.json",
    ]
    assert modes["MEMORIAL"]["flagship_experience_gold_gates"] == modes["MEMORIAL"]["public_gold_gates"]
    assert modes["MEMORIAL"]["claim_labels"]["public_voice"] == "Memorial public-origin voice gold"
    assert modes["MEMORIAL"]["claim_labels"]["flagship"] == "Memorial flagship experience gold"
    assert (
        modes["MEMORIAL"]["public_gold_status_semantics"]
        == "legacy_alias_of_flagship_experience_gold_status"
    )
    public_gold_gate_paths = [ROOT / path for path in modes["MEMORIAL"]["public_gold_gates"]]
    public_voice_path, public_browser_path, room_path, spatial_path = public_gold_gate_paths
    expected_public_voice_gold_status = (
        "public_origin_voice_gold_pass"
        if _receipt_passes(public_voice_path, current_head=current_head)
        and _receipt_passes(public_browser_path, current_head=current_head)
        and _room_receipt_passes(room_path, current_head=current_head)
        else "public_origin_voice_gold_blocked"
    )
    expected_flagship_experience_gold_status = (
        "flagship_experience_gold_pass"
        if expected_public_voice_gold_status == "public_origin_voice_gold_pass"
        and _spatial_receipt_passes(
            spatial_path,
            current_head=current_head,
            current_fingerprint=_source_fingerprint(),
        )
        else "flagship_experience_gold_blocked"
    )
    expected_public_gold_status = (
        "public_origin_gold_pass"
        if expected_flagship_experience_gold_status
        == "flagship_experience_gold_pass"
        else "public_origin_gold_blocked"
    )
    assert modes["MEMORIAL"]["public_voice_gold_status"] == expected_public_voice_gold_status
    assert modes["MEMORIAL"]["flagship_experience_gold_status"] == expected_flagship_experience_gold_status
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
    assert any(
        "Memorial public-origin voice gold" in note
        for note in payload["operator_notes"]
    )
    assert any(
        "Memorial flagship experience gold" in note
        for note in payload["operator_notes"]
    )


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


def test_project_modes_keep_spatial_out_of_public_voice_gold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import scripts.materialize_project_mode_manifests as module

    voice = tmp_path / "voice.json"
    browser = tmp_path / "browser.json"
    room = tmp_path / "room.json"
    spatial = tmp_path / "spatial.json"
    for path in (voice, browser):
        path.write_text(
            json.dumps({"status": "pass", "source_git_head": "HEAD"}),
            encoding="utf-8",
        )
    room.write_text(
        json.dumps(
            {
                "status": "pass",
                "source_git_head": "HEAD",
                "proof_type": "manual_room_attestation",
                "manual_attestation": {
                    "attestation_id": "room-review-001",
                    "signed_at": "2026-07-28T12:00:00Z",
                    "ci_must_not_auto_assert": True,
                },
                "checks": {
                    "actual_device_checked": True,
                    "actual_speaker_checked": True,
                    "first_syllable_not_clipped": True,
                    "intelligibility_confirmed": True,
                    "answer_text_fallback_visible": True,
                    "no_internet_search_confirmed": True,
                    "normal_spoken_turn_confirmed": True,
                    "interruption_behavior_confirmed": True,
                    "retry_path_confirmed": True,
                },
            }
        ),
        encoding="utf-8",
    )
    spatial.write_text(
        json.dumps({"status": "blocked", "failed_codes": ["spatial_missing"]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "MEMORIAL_PUBLIC_VOICE_GATE", voice)
    monkeypatch.setattr(module, "MEMORIAL_PUBLIC_BROWSER_GATE", browser)
    monkeypatch.setattr(module, "MEMORIAL_PUBLIC_ROOM_GATE", room)
    monkeypatch.setattr(module, "MEMORIAL_SPATIAL_PUBLIC_ORIGIN_GATE", spatial)

    assert (
        _memorial_public_voice_gold_status(current_head="HEAD")
        == "public_origin_voice_gold_pass"
    )
    assert (
        _memorial_flagship_experience_gold_status(
            current_head="HEAD",
            current_fingerprint="source-fingerprint",
        )
        == "flagship_experience_gold_blocked"
    )


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


def test_source_state_head_reads_git_head_without_git_binary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    git_dir = tmp_path / ".git"
    ref_path = git_dir / "refs" / "heads" / "main"
    ref_path.parent.mkdir(parents=True)
    git_dir.mkdir(exist_ok=True)
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    ref_path.write_text("a" * 40 + "\n", encoding="utf-8")
    monkeypatch.setattr(source_state_head, "_git_stdout", lambda *_args, **_kwargs: "")

    assert source_state_head.resolve_source_state_head(tmp_path) == "a" * 40


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
                " M .vexp/manifest.json",
                "?? ea/.runtime/voice-preview/sample.wav",
                " M state/proactive_ooda_latest_run.generated.json",
                "?? ea/state/proactive_ooda_safe_work_results/result.json",
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


def test_source_worktree_fingerprint_hashes_effective_source_files_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "app/api/routes").mkdir(parents=True)
    (tmp_path / "scripts").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / ".vexp").mkdir()
    (tmp_path / ".codex-studio/published").mkdir(parents=True)
    source_file = tmp_path / "app/api/routes/public_memorials.py"
    materializer = tmp_path / "scripts/materialize_project_mode_manifests.py"
    vexp_manifest = tmp_path / ".vexp/manifest.json"
    generated = tmp_path / ".codex-studio/published/receipt.generated.json"
    state_generated = tmp_path / "state/proactive_ooda_latest_run.generated.json"
    dot_state_generated = tmp_path / ".state/runtime-artifact.json"
    ea_state_generated = tmp_path / "ea/state/proactive_ooda_safe_work_results/result.generated.json"
    test_file = tmp_path / "tests/test_generated_noise.py"
    tmp_probe = tmp_path / "tmp_runtime_probe.py"
    source_file.write_text("source = 1\n", encoding="utf-8")
    materializer.write_text("materializer = 1\n", encoding="utf-8")
    vexp_manifest.write_text("{\"indexed\":1}\n", encoding="utf-8")
    generated.write_text("generated = 1\n", encoding="utf-8")
    state_generated.parent.mkdir(parents=True)
    state_generated.write_text("runtime = 1\n", encoding="utf-8")
    dot_state_generated.parent.mkdir(parents=True)
    dot_state_generated.write_text("dot runtime = 1\n", encoding="utf-8")
    ea_state_generated.parent.mkdir(parents=True)
    ea_state_generated.write_text("ea runtime = 1\n", encoding="utf-8")
    test_file.write_text("test = 1\n", encoding="utf-8")
    tmp_probe.write_text("probe = 1\n", encoding="utf-8")

    def _fake_git_stdout(_root: Path, *args: str) -> str:
        if args == ("ls-files", "--cached", "--others", "--exclude-standard"):
            return "\n".join(
                [
                    "app/api/routes/public_memorials.py",
                    "scripts/materialize_project_mode_manifests.py",
                    ".vexp/manifest.json",
                    ".codex-studio/published/receipt.generated.json",
                    "state/proactive_ooda_latest_run.generated.json",
                    ".state/runtime-artifact.json",
                    "ea/state/proactive_ooda_safe_work_results/result.generated.json",
                    "tests/test_generated_noise.py",
                    "tmp_runtime_probe.py",
                    "deleted_source.py",
                ]
            )
        return ""

    monkeypatch.setattr(source_state_head, "_git_stdout", _fake_git_stdout)

    first = source_state_head.resolve_source_worktree_fingerprint(tmp_path)
    vexp_manifest.write_text("{\"indexed\":2}\n", encoding="utf-8")
    generated.write_text("generated = 2\n", encoding="utf-8")
    state_generated.write_text("runtime = 2\n", encoding="utf-8")
    dot_state_generated.write_text("dot runtime = 2\n", encoding="utf-8")
    ea_state_generated.write_text("ea runtime = 2\n", encoding="utf-8")
    test_file.write_text("test = 2\n", encoding="utf-8")
    tmp_probe.write_text("probe = 2\n", encoding="utf-8")
    assert source_state_head.resolve_source_worktree_fingerprint(tmp_path) == first

    source_file.write_text("source = 2\n", encoding="utf-8")
    assert source_state_head.resolve_source_worktree_fingerprint(tmp_path) != first


def test_source_worktree_fingerprint_falls_back_without_git_binary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / ".vexp").mkdir()
    (tmp_path / ".codex-studio/published").mkdir(parents=True)
    source_file = tmp_path / "app/service.py"
    test_file = tmp_path / "tests/test_service.py"
    vexp_manifest = tmp_path / ".vexp/manifest.json"
    generated = tmp_path / ".codex-studio/published/receipt.generated.json"
    state_generated = tmp_path / "state/proactive_ooda_latest_run.generated.json"
    dot_state_generated = tmp_path / ".state/runtime-artifact.json"
    ea_state_generated = tmp_path / "ea/state/proactive_ooda_safe_work_results/result.generated.json"
    env_file = tmp_path / ".env"
    env_example = tmp_path / ".env.example"
    tmp_probe = tmp_path / "tmp_runtime_probe.py"
    source_file.write_text("source = 1\n", encoding="utf-8")
    test_file.write_text("test = 1\n", encoding="utf-8")
    vexp_manifest.write_text("{\"indexed\":1}\n", encoding="utf-8")
    generated.write_text("generated = 1\n", encoding="utf-8")
    state_generated.parent.mkdir(parents=True)
    state_generated.write_text("runtime = 1\n", encoding="utf-8")
    dot_state_generated.parent.mkdir(parents=True)
    dot_state_generated.write_text("dot runtime = 1\n", encoding="utf-8")
    ea_state_generated.parent.mkdir(parents=True)
    ea_state_generated.write_text("ea runtime = 1\n", encoding="utf-8")
    env_file.write_text("SECRET=real\n", encoding="utf-8")
    env_example.write_text("SECRET=\n", encoding="utf-8")
    tmp_probe.write_text("probe = 1\n", encoding="utf-8")
    monkeypatch.setattr(source_state_head, "_git_stdout", lambda *_args, **_kwargs: "")

    first = source_state_head.resolve_source_worktree_fingerprint(tmp_path)
    assert first

    test_file.write_text("test = 2\n", encoding="utf-8")
    vexp_manifest.write_text("{\"indexed\":2}\n", encoding="utf-8")
    generated.write_text("generated = 2\n", encoding="utf-8")
    state_generated.write_text("runtime = 2\n", encoding="utf-8")
    dot_state_generated.write_text("dot runtime = 2\n", encoding="utf-8")
    ea_state_generated.write_text("ea runtime = 2\n", encoding="utf-8")
    env_file.write_text("SECRET=changed\n", encoding="utf-8")
    tmp_probe.write_text("probe = 2\n", encoding="utf-8")
    assert source_state_head.resolve_source_worktree_fingerprint(tmp_path) == first

    source_file.write_text("source = 2\n", encoding="utf-8")
    assert source_state_head.resolve_source_worktree_fingerprint(tmp_path) != first
