from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType


GENERATED_AT = "2026-06-19T12:00:00Z"


def _load_script(name: str) -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "ea" / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_materialize_cinematic_narration_segment_chain_writes_spoken_audio_receipts(tmp_path: Path) -> None:
    promo_materializer = _load_script("materialize_ea_promo_video_fallback")
    segment_materializer = _load_script("materialize_cinematic_narration_segment_chain")
    segment_verifier = _load_script("verify_cinematic_narration_segment_chain")
    output_dir = tmp_path / "ashline-circle"
    promo_materializer.materialize_fallback_promo(
        output_dir=output_dir,
        faction_id="ashline-circle",
        requested_provider="Advertisemind",
        generated_at=GENERATED_AT,
    )

    result = segment_materializer.materialize_cinematic_narration_segment_chain(
        artifact_dir=output_dir,
        generated_at=GENERATED_AT,
        voice="awb",
    )

    assert result["status"] == "ready"
    assert result["segment_count"] == 4
    packet = _load(output_dir / "narration_segments.generated.json")
    assert packet["status"] == "ready"
    assert packet["render_mode"] == "local_ffmpeg_flite_speech_fixture"
    assert packet["audio_path_exposed"] is False
    assert packet["raw_provider_voice_id_exposed"] is False
    assert packet["provider_output_truth_allowed"] is False
    assert packet["scene_signal_is_canon"] is False
    assert packet["voice"]["provider_ready"] is False  # type: ignore[index]
    assert packet["voice"]["verified_provider_claim_allowed"] is False  # type: ignore[index]
    segments = packet["segments"]
    assert len(segments) == 4
    assert segments[0]["previous_segment_digest"] == ""
    assert segments[1]["previous_segment_digest"] == segments[0]["segment_digest"]
    assert segments[2]["previous_segment_digest"] == segments[1]["segment_digest"]
    assert segments[3]["previous_segment_digest"] == segments[2]["segment_digest"]
    for segment in segments:
        audio_path = output_dir / "narration-audio" / segment["audio_file"]
        assert audio_path.is_file()
        assert audio_path.read_bytes().startswith(b"RIFF")
        assert segment["status"] == "ready"
        assert segment["scene_bound"] is False
        assert segment["current_scene_conditioned"] is True
        assert segment["audio_path_exposed"] is False
        assert segment["raw_provider_voice_id_exposed"] is False
        assert segment["provider_output_truth_allowed"] is False
        assert segment["quality_gate"]["status"] == "pass"
    verification = segment_verifier.verify_cinematic_narration_segment_chain(output_dir)
    assert verification["status"] == "pass"
    assert verification["issues"] == []


def test_verify_cinematic_narration_segment_chain_rejects_overclaims(tmp_path: Path) -> None:
    promo_materializer = _load_script("materialize_ea_promo_video_fallback")
    segment_materializer = _load_script("materialize_cinematic_narration_segment_chain")
    segment_verifier = _load_script("verify_cinematic_narration_segment_chain")
    output_dir = tmp_path / "overclaim"
    promo_materializer.materialize_fallback_promo(output_dir=output_dir, generated_at=GENERATED_AT)
    segment_materializer.materialize_cinematic_narration_segment_chain(
        artifact_dir=output_dir,
        generated_at=GENERATED_AT,
        voice="awb",
    )
    path = output_dir / "narration_segments.generated.json"
    packet = _load(path)
    packet["provider_output_truth_allowed"] = True
    packet["voice"]["provider_ready"] = True  # type: ignore[index]
    packet["segments"][0]["audio_path_exposed"] = True  # type: ignore[index]
    path.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    verification = segment_verifier.verify_cinematic_narration_segment_chain(output_dir)

    assert verification["status"] == "fail"
    assert "segment_chain_provider_output_truth_allowed_not_false" in verification["issues"]
    assert "segment_chain_provider_ready_overclaim" in verification["issues"]
    assert "segment_audio_path_exposed_not_false" in verification["issues"]


def test_cinematic_narration_segment_chain_clis_work(tmp_path: Path) -> None:
    script_root = Path(__file__).resolve().parents[1] / "ea" / "scripts"
    output_dir = tmp_path / "cli-artifacts"
    promo = subprocess.run(
        [
            sys.executable,
            str(script_root / "materialize_ea_promo_video_fallback.py"),
            "--output-dir",
            str(output_dir),
            "--generated-at",
            GENERATED_AT,
        ],
        cwd=Path(__file__).resolve().parents[1] / "ea",
        text=True,
        capture_output=True,
        check=False,
    )
    assert promo.returncode == 0

    materialized = subprocess.run(
        [
            sys.executable,
            str(script_root / "materialize_cinematic_narration_segment_chain.py"),
            "--artifact-dir",
            str(output_dir),
            "--generated-at",
            GENERATED_AT,
            "--voice",
            "awb",
        ],
        cwd=Path(__file__).resolve().parents[1] / "ea",
        text=True,
        capture_output=True,
        check=False,
    )
    assert materialized.returncode == 0
    body = json.loads(materialized.stdout)
    assert body["status"] == "ready"
    assert body["segment_count"] == 4
    verified = subprocess.run(
        [
            sys.executable,
            str(script_root / "verify_cinematic_narration_segment_chain.py"),
            "--artifact-dir",
            str(output_dir),
        ],
        cwd=Path(__file__).resolve().parents[1] / "ea",
        text=True,
        capture_output=True,
        check=False,
    )
    assert verified.returncode == 0
    verification = json.loads(verified.stdout)
    assert verification["status"] == "pass"
