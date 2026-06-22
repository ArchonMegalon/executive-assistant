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


def test_materialize_cinematic_narration_continuity_demo_writes_ongoing_scene_conditioned_chain(
    tmp_path: Path,
) -> None:
    materializer = _load_script("materialize_cinematic_narration_continuity_demo")
    verifier = _load_script("verify_cinematic_narration_continuity_demo")
    output_dir = tmp_path / "continuity-demo"

    result = materializer.materialize_cinematic_narration_continuity_demo(
        artifact_dir=output_dir,
        generated_at=GENERATED_AT,
        voice="awb",
    )

    assert result["status"] == "ready"
    packet = _load(output_dir / "cinematic_narration_continuity_demo.generated.json")
    assert packet["status"] == "ready"
    assert packet["design"]["mode"] == "ongoing_cinematic_narration"  # type: ignore[index]
    assert packet["design"]["scene_conditioned"] is True  # type: ignore[index]
    assert packet["design"]["scene_bound"] is False  # type: ignore[index]
    assert packet["raw_audio_path_exposed"] is False
    assert packet["provider_output_truth_allowed"] is False
    assert packet["scene_signal_is_canon"] is False
    segments = packet["segments"]
    assert len(segments) == 3
    assert segments[0]["previous_segment_digest"] == ""
    assert segments[1]["previous_segment_digest"] == segments[0]["segment_digest"]
    assert segments[2]["previous_segment_digest"] == segments[1]["segment_digest"]
    for segment in segments:
        assert segment["status"] == "ready"
        assert segment["scene_bound"] is False
        assert segment["current_scene_conditioned"] is True
        assert segment["rolling_state_preserved"] is True
        assert segment["scene_fit"]["focus_terms_present"] is True
        assert segment["scene_fit"]["pressure_terms_present"] is True
        assert segment["scene_fit"]["continuity_callback_present"] is True
        assert (output_dir / "narration-audio" / segment["audio_file"]).is_file()

    verification = verifier.verify_cinematic_narration_continuity_demo(output_dir)
    assert verification["status"] == "pass"
    assert verification["issues"] == []


def test_verify_cinematic_narration_continuity_demo_rejects_scene_bound_and_overclaims(
    tmp_path: Path,
) -> None:
    materializer = _load_script("materialize_cinematic_narration_continuity_demo")
    verifier = _load_script("verify_cinematic_narration_continuity_demo")
    output_dir = tmp_path / "tampered"
    materializer.materialize_cinematic_narration_continuity_demo(
        artifact_dir=output_dir,
        generated_at=GENERATED_AT,
        voice="awb",
    )
    proof_path = output_dir / "cinematic_narration_continuity_demo.generated.json"
    packet = _load(proof_path)
    packet["design"]["scene_bound"] = True  # type: ignore[index]
    packet["provider_output_truth_allowed"] = True
    packet["segments"][1]["previous_segment_digest"] = "bad"  # type: ignore[index]
    proof_path.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    verification = verifier.verify_cinematic_narration_continuity_demo(output_dir)

    assert verification["status"] == "fail"
    assert "continuity_demo_scene_bound_overclaim" in verification["issues"]
    assert "continuity_demo_provider_truth_overclaim" in verification["issues"]
    assert "continuity_demo_previous_segment_digest_mismatch" in verification["issues"]


def test_cinematic_narration_continuity_demo_clis_work(tmp_path: Path) -> None:
    script_root = Path(__file__).resolve().parents[1] / "ea" / "scripts"
    output_dir = tmp_path / "cli-demo"
    materialized = subprocess.run(
        [
            sys.executable,
            str(script_root / "materialize_cinematic_narration_continuity_demo.py"),
            "--artifact-dir",
            str(output_dir),
            "--generated-at",
            GENERATED_AT,
        ],
        cwd=Path(__file__).resolve().parents[1] / "ea",
        text=True,
        capture_output=True,
        check=False,
    )
    assert materialized.returncode == 0, materialized.stderr + materialized.stdout
    result = json.loads(materialized.stdout)
    assert result["status"] == "ready"
    assert result["segment_count"] == 3

    verified = subprocess.run(
        [
            sys.executable,
            str(script_root / "verify_cinematic_narration_continuity_demo.py"),
            "--artifact-dir",
            str(output_dir),
        ],
        cwd=Path(__file__).resolve().parents[1] / "ea",
        text=True,
        capture_output=True,
        check=False,
    )
    assert verified.returncode == 0, verified.stderr + verified.stdout
    verification = json.loads(verified.stdout)
    assert verification["status"] == "pass"
