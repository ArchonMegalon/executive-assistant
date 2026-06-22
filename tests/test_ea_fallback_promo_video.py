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


def _prepare_artifacts(output_dir: Path) -> None:
    promo_materializer = _load_script("materialize_ea_promo_video_fallback")
    segment_materializer = _load_script("materialize_cinematic_narration_segment_chain")
    promo_materializer.materialize_fallback_promo(
        output_dir=output_dir,
        faction_id="ashline-circle",
        requested_provider="Advertisemind",
        generated_at=GENERATED_AT,
    )
    segment_materializer.materialize_cinematic_narration_segment_chain(
        artifact_dir=output_dir,
        generated_at=GENERATED_AT,
        voice="awb",
    )


def _load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_materialize_ea_fallback_promo_video_writes_local_mp4_receipt(tmp_path: Path) -> None:
    video_materializer = _load_script("materialize_ea_fallback_promo_video")
    video_verifier = _load_script("verify_ea_fallback_promo_video")
    output_dir = tmp_path / "ashline-circle"
    _prepare_artifacts(output_dir)

    result = video_materializer.materialize_ea_fallback_promo_video(
        artifact_dir=output_dir,
        generated_at=GENERATED_AT,
    )

    assert result["status"] == "ready"
    assert result["render_mode"] == "local_ffmpeg_static_card_video"
    receipt = _load(output_dir / "promo_fallback_video.generated.json")
    assert receipt["status"] == "ready"
    assert receipt["provider_ready"] is False
    assert receipt["live_provider_runtime_verified"] is False
    assert receipt["verified_provider_claim_allowed"] is False
    assert receipt["provider_output_truth_allowed"] is False
    assert receipt["route_deployment_verified"] is False
    assert receipt["public_route_claim_allowed"] is False
    assert receipt["ea_is_product_truth"] is False
    assert receipt["video"]["has_video"] is True  # type: ignore[index]
    assert receipt["video"]["has_audio"] is True  # type: ignore[index]
    assert receipt["video"]["captions_embedded"] is True  # type: ignore[index]
    assert receipt["review_assets"]["poster"]["luma"]["nonblank"] is True  # type: ignore[index]
    assert receipt["review_assets"]["contact_sheet"]["luma"]["nonblank"] is True  # type: ignore[index]
    assert receipt["review_page"]["provider_claims_present"] is False  # type: ignore[index]
    assert receipt["review_page"]["route_claims_present"] is False  # type: ignore[index]
    video = output_dir / "promo-video" / "promo-fallback.mp4"
    poster = output_dir / "promo-video" / "poster.jpg"
    contact_sheet = output_dir / "promo-video" / "contact-sheet.jpg"
    watch = output_dir / "promo-video" / "watch.html"
    assert video.is_file()
    assert poster.is_file()
    assert contact_sheet.is_file()
    assert watch.is_file()
    assert video.stat().st_size > 0
    assert poster.stat().st_size > 0
    assert contact_sheet.stat().st_size > 0
    watch_html = watch.read_text(encoding="utf-8")
    assert "<video" in watch_html
    assert 'src="promo-fallback.mp4"' in watch_html
    assert 'poster="poster.jpg"' in watch_html
    assert 'src="../promo.vtt"' in watch_html
    assert "Advertisemind" not in watch_html
    verification = video_verifier.verify_ea_fallback_promo_video(output_dir)
    assert verification["status"] == "pass"
    assert verification["issues"] == []


def test_verify_ea_fallback_promo_video_rejects_overclaims(tmp_path: Path) -> None:
    video_materializer = _load_script("materialize_ea_fallback_promo_video")
    video_verifier = _load_script("verify_ea_fallback_promo_video")
    output_dir = tmp_path / "overclaim"
    _prepare_artifacts(output_dir)
    video_materializer.materialize_ea_fallback_promo_video(
        artifact_dir=output_dir,
        generated_at=GENERATED_AT,
    )
    receipt_path = output_dir / "promo_fallback_video.generated.json"
    receipt = _load(receipt_path)
    receipt["provider_ready"] = True
    receipt["verified_provider_claim_allowed"] = True
    receipt["provider_output_truth_allowed"] = True
    receipt["route_deployment_verified"] = True
    receipt["public_route_claim_allowed"] = True
    receipt["review_assets"]["poster"]["luma"]["nonblank"] = False  # type: ignore[index]
    receipt["review_page"]["provider_claims_present"] = True  # type: ignore[index]
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_dir / "promo-video" / "watch.html").write_text(
        "<html><body>VERIFIED_PROVIDER Advertisemind provider_video public route ready</body></html>\n",
        encoding="utf-8",
    )

    verification = video_verifier.verify_ea_fallback_promo_video(output_dir)

    assert verification["status"] == "fail"
    assert "promo_fallback_video_provider_ready_overclaim" in verification["issues"]
    assert "promo_fallback_video_verified_provider_overclaim" in verification["issues"]
    assert "promo_fallback_video_provider_truth_overclaim" in verification["issues"]
    assert "promo_fallback_video_route_deployment_overclaim" in verification["issues"]
    assert "promo_fallback_video_public_route_overclaim" in verification["issues"]
    assert "promo_fallback_video_poster_receipt_blank" in verification["issues"]
    assert "promo_fallback_video_watch_page_sha256_mismatch" in verification["issues"]
    assert "promo_fallback_video_watch_page_provider_name" in verification["issues"]
    assert "promo_fallback_video_watch_page_provider_overclaim" in verification["issues"]
    assert "promo_fallback_video_watch_page_route_overclaim" in verification["issues"]
    assert "promo_fallback_video_watch_page_provider_claim_flag" in verification["issues"]


def test_ea_fallback_promo_video_clis_work(tmp_path: Path) -> None:
    script_root = Path(__file__).resolve().parents[1] / "ea" / "scripts"
    output_dir = tmp_path / "cli-artifacts"
    commands = [
        [
            sys.executable,
            str(script_root / "materialize_ea_promo_video_fallback.py"),
            "--output-dir",
            str(output_dir),
            "--generated-at",
            GENERATED_AT,
        ],
        [
            sys.executable,
            str(script_root / "materialize_cinematic_narration_segment_chain.py"),
            "--artifact-dir",
            str(output_dir),
            "--generated-at",
            GENERATED_AT,
        ],
        [
            sys.executable,
            str(script_root / "materialize_ea_fallback_promo_video.py"),
            "--artifact-dir",
            str(output_dir),
            "--generated-at",
            GENERATED_AT,
        ],
        [
            sys.executable,
            str(script_root / "verify_ea_fallback_promo_video.py"),
            "--artifact-dir",
            str(output_dir),
        ],
    ]
    for command in commands:
        completed = subprocess.run(
            command,
            cwd=Path(__file__).resolve().parents[1] / "ea",
            text=True,
            capture_output=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr + completed.stdout
    verification = json.loads(completed.stdout)
    assert verification["status"] == "pass"
