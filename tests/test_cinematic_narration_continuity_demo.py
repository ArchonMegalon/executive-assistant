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
    packet = _load(output_dir / "narration_master.generated.json")
    assert packet["status"] == "ready"
    assert packet["render_mode"] == "continuous_humanized_master"
    assert packet["master_count"] == 1
    assert packet["segment_count"] == 0
    assert packet["humanizer"]["provider"] == "Undetectable Humanizer LTD"  # type: ignore[index]
    assert packet["audio_path_exposed"] is False
    assert packet["provider_output_truth_allowed"] is False
    assert packet["scene_signal_is_canon"] is False
    assert (output_dir / "narration-audio" / packet["audio_file"]).is_file()

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
    proof_path = output_dir / "narration_master.generated.json"
    packet = _load(proof_path)
    packet["segment_count"] = 2
    proof_path.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    verification = verifier.verify_cinematic_narration_continuity_demo(output_dir)

    assert verification["status"] == "fail"
    assert "narration_segment_count_not_zero" in verification["issues"]


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
    assert result["master_count"] == 1
    assert result["segment_count"] == 0

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
