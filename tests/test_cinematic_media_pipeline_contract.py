from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType


def _load_script() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "ea" / "scripts" / "verify_cinematic_media_pipeline_contract.py"
    spec = importlib.util.spec_from_file_location("verify_cinematic_media_pipeline_contract", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_cinematic_media_pipeline_contract_passes() -> None:
    module = _load_script()

    payload = module.verify_cinematic_media_pipeline_contract()

    assert payload["status"] == "pass"
    assert payload["issues"] == []
    checks = payload["checks"]
    assert checks["ongoing_not_scene_bound"] is True
    assert checks["voice_audition_contract"] is True
    assert checks["audio_quality_gates"] is True
    assert checks["promo_video_fallback_truth"] is True
    assert checks["audiobook_m4b_structure_probe_present"] is True
    assert checks["continuity_demo_scripts_present"] is True
    assert checks["promo_quality_rubric_requires_continuity_demo"] is True
    assert checks["implementation_contains_audition_and_m4b_hooks"] is True


def test_cinematic_media_pipeline_contract_cli_outputs_pass() -> None:
    script = Path(__file__).resolve().parents[1] / "ea" / "scripts" / "verify_cinematic_media_pipeline_contract.py"

    completed = subprocess.run(
        [sys.executable, str(script)],
        cwd=Path(__file__).resolve().parents[1] / "ea",
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["contract_name"] == "ea.cinematic_narration_and_promo_pipeline.v1"
    assert payload["status"] == "pass"


def test_cinematic_media_pipeline_contract_cli_help_does_not_run_verifier() -> None:
    script = Path(__file__).resolve().parents[1] / "ea" / "scripts" / "verify_cinematic_media_pipeline_contract.py"

    completed = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=Path(__file__).resolve().parents[1] / "ea",
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0
    assert "usage:" in completed.stdout
    assert "ea.cinematic_narration_and_promo_pipeline.v1" not in completed.stdout
