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


def test_materialize_ea_promo_review_bundle_writes_complete_local_review_set(tmp_path: Path) -> None:
    materializer = _load_script("materialize_ea_promo_review_bundle")
    verifier = _load_script("verify_ea_promo_review_bundle")
    output_dir = tmp_path / "ashline-circle"

    result = materializer.materialize_ea_promo_review_bundle(
        output_dir=output_dir,
        faction_id="ashline-circle",
        requested_provider="Advertisemind",
        generated_at=GENERATED_AT,
        voice="awb",
    )

    assert result["status"] == "ready"
    bundle = _load(output_dir / "promo_review_bundle.generated.json")
    assert bundle["status"] == "ready"
    assert bundle["provider_ready"] is False
    assert bundle["verified_provider_claim_allowed"] is False
    assert bundle["provider_output_truth_allowed"] is False
    assert bundle["route_deployment_verified"] is False
    assert bundle["public_route_claim_allowed"] is False
    assert bundle["render_modes"]["storyboard"] == "fallback_static_storyboard"  # type: ignore[index]
    assert bundle["render_modes"]["narration"] == "local_ffmpeg_flite_speech_fixture"  # type: ignore[index]
    assert bundle["render_modes"]["continuity_demo"] == "local_ffmpeg_flite_speech_fixture"  # type: ignore[index]
    assert bundle["render_modes"]["video"] == "local_ffmpeg_static_card_video"  # type: ignore[index]
    for key in (
        "promo_json",
        "promo_vtt",
        "preview_html",
        "narration_windows",
        "narration_segments",
        "continuity_demo",
        "fallback_video_receipt",
        "fallback_video",
        "poster",
        "contact_sheet",
        "watch_page",
    ):
        assert bundle["files"][key]["exists"] is True  # type: ignore[index]
        assert bundle["files"][key]["sha256"]  # type: ignore[index]
    assert (output_dir / "promo-video" / "watch.html").is_file()
    assert (output_dir / "promo-video" / "promo-fallback.mp4").is_file()
    verification = verifier.verify_ea_promo_review_bundle(output_dir)
    assert verification["status"] == "pass"
    assert verification["issues"] == []


def test_verify_ea_promo_review_bundle_rejects_overclaim_and_hash_tamper(tmp_path: Path) -> None:
    materializer = _load_script("materialize_ea_promo_review_bundle")
    verifier = _load_script("verify_ea_promo_review_bundle")
    output_dir = tmp_path / "tamper"
    materializer.materialize_ea_promo_review_bundle(
        output_dir=output_dir,
        generated_at=GENERATED_AT,
    )
    bundle_path = output_dir / "promo_review_bundle.generated.json"
    bundle = _load(bundle_path)
    bundle["provider_ready"] = True
    bundle["route_deployment_verified"] = True
    bundle["files"]["continuity_demo"]["sha256"] = "bad"  # type: ignore[index]
    bundle["files"]["watch_page"]["sha256"] = "bad"  # type: ignore[index]
    bundle_path.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    verification = verifier.verify_ea_promo_review_bundle(output_dir)

    assert verification["status"] == "fail"
    assert "promo_review_bundle_provider_ready_overclaim" in verification["issues"]
    assert "promo_review_bundle_route_deployment_verified_overclaim" in verification["issues"]
    assert "promo_review_bundle_continuity_demo_sha256_mismatch" in verification["issues"]
    assert "promo_review_bundle_watch_page_sha256_mismatch" in verification["issues"]


def test_ea_promo_review_bundle_clis_work(tmp_path: Path) -> None:
    script_root = Path(__file__).resolve().parents[1] / "ea" / "scripts"
    output_dir = tmp_path / "cli-artifacts"
    materialized = subprocess.run(
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
    assert materialized.returncode == 0, materialized.stderr + materialized.stdout
    result = json.loads(materialized.stdout)
    assert result["status"] == "ready"
    verified = subprocess.run(
        [
            sys.executable,
            str(script_root / "verify_ea_promo_review_bundle.py"),
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
