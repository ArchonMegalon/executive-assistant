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


def _prepare_bundle(output_dir: Path) -> None:
    materializer = _load_script("materialize_ea_promo_review_bundle")
    result = materializer.materialize_ea_promo_review_bundle(
        output_dir=output_dir,
        faction_id="ashline-circle",
        requested_provider="Advertisemind",
        generated_at=GENERATED_AT,
        voice="awb",
    )
    assert result["status"] == "ready"


def test_ea_promo_quality_rubric_passes_for_local_review_bundle(tmp_path: Path) -> None:
    verifier = _load_script("verify_ea_promo_quality_rubric")
    output_dir = tmp_path / "ashline-circle"
    _prepare_bundle(output_dir)

    payload = verifier.write_ea_promo_quality_rubric(artifact_dir=output_dir)

    assert payload["contract_name"] == "ea.promo_quality_rubric.v1"
    assert payload["status"] == "pass"
    assert payload["quality_score"] == 100
    assert payload["issues"] == []
    assert payload["provider_ready"] is False
    assert payload["live_provider_runtime_verified"] is False
    assert payload["route_deployment_verified"] is False
    assert payload["not_provider_proof"] is True
    assert payload["not_public_route_proof"] is True
    assert payload["checks"]["story_arc_has_four_distinct_beats"] is True  # type: ignore[index]
    assert payload["checks"]["continuous_narration_demo_reviewable"] is True  # type: ignore[index]
    assert payload["checks"]["local_mp4_reviewable"] is True  # type: ignore[index]
    assert (output_dir / "promo_quality_rubric.generated.json").is_file()


def test_ea_promo_quality_rubric_rejects_weak_story_and_overclaim(tmp_path: Path) -> None:
    verifier = _load_script("verify_ea_promo_quality_rubric")
    output_dir = tmp_path / "weak"
    _prepare_bundle(output_dir)
    promo_path = output_dir / "promo.json"
    promo = _load(promo_path)
    promo["provider"]["provider_ready"] = True  # type: ignore[index]
    promo["storyboard"]["scenes"][1]["on_screen_text"] = promo["storyboard"]["scenes"][0]["on_screen_text"]  # type: ignore[index]
    promo["storyboard"]["scenes"][2]["visual"] = "Dark frame."  # type: ignore[index]
    promo_path.write_text(json.dumps(promo, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    payload = verifier.verify_ea_promo_quality_rubric(output_dir)

    assert payload["status"] == "fail"
    assert "lower_verifiers_pass_missing" in payload["issues"]
    assert "story_arc_has_four_distinct_beats_missing" in payload["issues"]


def test_ea_promo_quality_rubric_clis_work(tmp_path: Path) -> None:
    script_root = Path(__file__).resolve().parents[1] / "ea" / "scripts"
    output_dir = tmp_path / "cli-artifacts"
    bundle = subprocess.run(
        [
            sys.executable,
            str(script_root / "materialize_ea_promo_review_bundle.py"),
            "--output-dir",
            str(output_dir),
            "--generated-at",
            GENERATED_AT,
            "--requested-provider",
            "Advertisemind",
        ],
        cwd=Path(__file__).resolve().parents[1] / "ea",
        text=True,
        capture_output=True,
        check=False,
    )
    assert bundle.returncode == 0, bundle.stderr + bundle.stdout
    materialized = subprocess.run(
        [
            sys.executable,
            str(script_root / "materialize_ea_promo_quality_rubric.py"),
            "--artifact-dir",
            str(output_dir),
        ],
        cwd=Path(__file__).resolve().parents[1] / "ea",
        text=True,
        capture_output=True,
        check=False,
    )
    assert materialized.returncode == 0, materialized.stderr + materialized.stdout
    result = json.loads(materialized.stdout)
    assert result["status"] == "pass"
    assert result["quality_score"] == 100
    assert result["not_provider_proof"] is True

    verified = subprocess.run(
        [
            sys.executable,
            str(script_root / "verify_ea_promo_quality_rubric.py"),
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
