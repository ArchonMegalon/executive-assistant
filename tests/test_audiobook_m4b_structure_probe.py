from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest


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


pytestmark = pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
    reason="ffmpeg and ffprobe are required for the M4B structure probe",
)


def test_audiobook_m4b_structure_probe_materializes_chaptered_m4b_with_cover(tmp_path: Path) -> None:
    materializer = _load_script("materialize_audiobook_m4b_structure_probe")
    verifier = _load_script("verify_audiobook_m4b_structure_probe")
    output_dir = tmp_path / "m4b-probe"

    result = materializer.materialize_audiobook_m4b_structure_probe(
        artifact_dir=output_dir,
        generated_at=GENERATED_AT,
    )

    assert result["status"] == "ready"
    receipt = _load(output_dir / "audiobook_m4b_structure_probe.generated.json")
    assert receipt["status"] == "ready"
    assert receipt["expected"]["chapter_count"] == 2  # type: ignore[index]
    assert receipt["merge_result"]["cover_embedded"] is True  # type: ignore[index]
    assert (output_dir / receipt["m4b"]["path"]).is_file()  # type: ignore[index]

    verification = verifier.verify_audiobook_m4b_structure_probe(output_dir)

    assert verification["status"] == "pass"
    assert verification["issues"] == []
    assert verification["chapter_count"] == 2
    assert verification["cover_attached_pic"] is True


def test_audiobook_m4b_structure_probe_verifier_rejects_hash_tamper(tmp_path: Path) -> None:
    materializer = _load_script("materialize_audiobook_m4b_structure_probe")
    verifier = _load_script("verify_audiobook_m4b_structure_probe")
    output_dir = tmp_path / "tamper"
    materializer.materialize_audiobook_m4b_structure_probe(
        artifact_dir=output_dir,
        generated_at=GENERATED_AT,
    )
    receipt_path = output_dir / "audiobook_m4b_structure_probe.generated.json"
    receipt = _load(receipt_path)
    receipt["m4b"]["sha256"] = "bad"  # type: ignore[index]
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    verification = verifier.verify_audiobook_m4b_structure_probe(output_dir)

    assert verification["status"] == "fail"
    assert "m4b_structure_probe_m4b_sha256_mismatch" in verification["issues"]


def test_audiobook_m4b_structure_probe_clis_work(tmp_path: Path) -> None:
    script_root = Path(__file__).resolve().parents[1] / "ea" / "scripts"
    output_dir = tmp_path / "cli"
    materialized = subprocess.run(
        [
            sys.executable,
            str(script_root / "materialize_audiobook_m4b_structure_probe.py"),
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

    verified = subprocess.run(
        [
            sys.executable,
            str(script_root / "verify_audiobook_m4b_structure_probe.py"),
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
