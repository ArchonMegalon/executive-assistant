from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MEMORIAL_PORTABLE_DEFAULT_FILES = (
    "docs/MEMORIAL_FLAGSHIP_RUNBOOK.md",
    "docs/MEMORIAL_FLAGSHIP_LAUNCH.md",
    "docs/MEMORIAL_GO_NO_GO_CHECKLIST.md",
    "docs/MEMORIAL_ROOM_READY_PROCEDURE.md",
    "docs/MEMORIAL_SHOWTIME_CUE_CARD.md",
    "docs/MEMORIAL_V6_CURRENT_LANDING_NOTES.md",
    "docs/MEMORIAL_V3_OPERATOR_NOTES.md",
    "scripts/materialize_memorial_room_audio_attestation_packet.py",
)


def test_memorial_stt_benchmark_uses_repo_local_and_env_paths() -> None:
    source = (ROOT / "scripts" / "benchmark_memorial_stt_providers.py").read_text(encoding="utf-8")

    assert "EA_MEMORIAL_STT_FIXTURE_ROOT" in source
    assert "EA_MEMORIAL_STT_ERROR_LOG_ROOT" in source
    assert ".codex-studio" in source
    assert "/docker/" + "EA/tests/fixtures/memorial" not in source
    assert "/mnt/" + "pcloud/EA/memorial_stt_errors" not in source


def test_voicewave_memorial_voice_uses_repo_local_storage_first() -> None:
    source = "\n".join(
        (
            (ROOT / "scripts" / "voicewave_memorial_voice.py").read_text(encoding="utf-8"),
            (ROOT / "docs" / "MEMORIAL_VOICEWAVE_RUNTIME_RUNBOOK.md").read_text(encoding="utf-8"),
        )
    )

    assert "VOICEWAVE_MEMORIAL_OUTPUT_ROOT" in source
    assert "EA_UI_SERVICE_SHARED_TEMP_ROOT" in source
    assert "/data/artifacts/voicewave_provider" in source
    assert ".codex-studio" in source
    assert "/docker/" + "fleet/state/chummer6/voicewave_provider" not in source
    assert "/mnt/" + "pcloud/EA/voicewave_provider" not in source
    assert "/mnt/" + "pcloud/EA/browseract_ui_worker_shared" not in source
    assert "/mnt/" + "pcloud/EA/voicewave_runtime_tmp" not in source


def test_memorial_flagship_exit_gate_resolves_repo_from_script_location() -> None:
    source = (ROOT / "scripts" / "memorial_flagship_exit_gates.sh").read_text(encoding="utf-8")

    assert 'dirname "${BASH_SOURCE[0]}"' in source
    assert 'ROOT="/docker/' + 'EA"' not in source


def test_memorial_stt_fixture_candidate_uses_repo_local_storage_by_default() -> None:
    source = (ROOT / "scripts" / "materialize_memorial_stt_fixture_candidate.py").read_text(encoding="utf-8")

    assert "EA_MEMORIAL_STT_ERROR_LOG_DIR" in source
    assert ".codex-studio" in source
    assert "memorial_stt_errors" in source
    assert "/mnt/" + "pcloud/EA/memorial_stt_errors" not in source


def test_memorial_operator_defaults_do_not_embed_live_origin_or_host_paths() -> None:
    source = "\n".join(
        (ROOT / relative_path).read_text(encoding="utf-8")
        for relative_path in MEMORIAL_PORTABLE_DEFAULT_FILES
    )

    assert "MEMORIAL_PUBLIC_ORIGIN" in source
    assert "https://memorial.example.test" in source
    assert "https://myexternalbrain" + ".com" not in source
    assert "/docker/" + "EA/examples" not in source
    assert "/docker/" + "EA/ea" not in source
    assert "/docker/" + "EA/scripts" not in source
    assert "/docker/" + "EA/docs" not in source
    assert "../" + "examples/" not in source
    assert "../" + "tests/" not in source
