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


def test_materialize_ea_promo_video_fallback_writes_honest_storyboard_artifacts(tmp_path: Path) -> None:
    materializer = _load_script("materialize_ea_promo_video_fallback")
    verifier = _load_script("verify_ea_promo_video_fallback")
    output_dir = tmp_path / "ashline-circle"

    result = materializer.materialize_fallback_promo(
        output_dir=output_dir,
        faction_id="ashline-circle",
        title="Black Ledger faction promo",
        requested_provider="Advertisemind",
        generated_at=GENERATED_AT,
    )

    assert result["status"] == "ok"
    promo = _load(output_dir / "promo.json")
    assert promo["verdict"] == "READY_VIA_FALLBACK"
    assert promo["render_mode"] == "fallback_static_storyboard"
    assert promo["provider"]["requested_provider"] == "Advertisemind"  # type: ignore[index]
    assert promo["provider"]["provider_ready"] is False  # type: ignore[index]
    assert promo["provider"]["live_provider_runtime_verified"] is False  # type: ignore[index]
    assert promo["provider"]["verified_provider_claim_allowed"] is False  # type: ignore[index]
    assert promo["route"]["promo_json"] == "/ledger/factions/ashline-circle/promo.json"  # type: ignore[index]
    assert promo["route"]["promo_vtt"] == "/ledger/factions/ashline-circle/promo.vtt"  # type: ignore[index]
    assert promo["route"]["local_preview"] == "promo.html"  # type: ignore[index]
    assert promo["route"]["route_deployment_verified"] is False  # type: ignore[index]
    assert promo["safety"]["gold_claim_allowed"] is False  # type: ignore[index]
    assert promo["media"]["preview_html"] == "promo.html"  # type: ignore[index]
    assert len(promo["storyboard"]["scenes"]) == 4  # type: ignore[index]
    assert promo["narration"]["window_count"] == 4  # type: ignore[index]
    assert promo["narration"]["scene_bound"] is False  # type: ignore[index]
    assert promo["narration"]["current_scene_conditioned"] is True  # type: ignore[index]
    assert promo["narration"]["rolling_state_preserved"] is True  # type: ignore[index]
    assert promo["narration"]["provider_output_truth_allowed"] is False  # type: ignore[index]
    assert promo["narration"]["scene_signal_is_canon"] is False  # type: ignore[index]
    narration = _load(output_dir / "narration_windows.generated.json")
    assert narration["window_count"] == 4
    windows = narration["windows"]
    assert windows[0]["previous_window_digest"] == ""
    assert windows[1]["previous_window_digest"] == windows[0]["window_digest"]
    assert windows[2]["previous_window_digest"] == windows[1]["window_digest"]
    assert windows[3]["previous_window_digest"] == windows[2]["window_digest"]
    assert all(window["scene_bound"] is False for window in windows)
    assert all(window["current_scene_conditioned"] is True for window in windows)
    assert all(scene["narration_window_id"] for scene in promo["storyboard"]["scenes"])  # type: ignore[index]
    assert (output_dir / "promo.vtt").read_text(encoding="utf-8").startswith("WEBVTT\n")
    preview = (output_dir / "promo.html").read_text(encoding="utf-8")
    assert "fallback_static_storyboard" in preview
    assert "provider proof pending" in preview
    assert "public deployment proof pending" in preview
    assert "Advertisemind" not in preview
    assert preview.count("data-scene-id=") == 4

    verification = verifier.verify_fallback_promo(output_dir)
    assert verification["status"] == "pass"
    assert verification["issues"] == []
    assert verification["preview_html"].endswith("promo.html")
    assert verification["route_deployment_verified"] is False


def test_verify_ea_promo_video_fallback_rejects_live_provider_overclaim(tmp_path: Path) -> None:
    materializer = _load_script("materialize_ea_promo_video_fallback")
    verifier = _load_script("verify_ea_promo_video_fallback")
    output_dir = tmp_path / "overclaim"
    materializer.materialize_fallback_promo(output_dir=output_dir, generated_at=GENERATED_AT)
    promo_path = output_dir / "promo.json"
    promo = _load(promo_path)
    promo["verdict"] = "VERIFIED_PROVIDER"
    promo["render_mode"] = "provider_video"
    promo["provider"]["provider_ready"] = True  # type: ignore[index]
    promo["provider"]["live_provider_runtime_verified"] = True  # type: ignore[index]
    promo["provider"]["verified_provider_claim_allowed"] = True  # type: ignore[index]
    promo_path.write_text(json.dumps(promo, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    verification = verifier.verify_fallback_promo(output_dir)

    assert verification["status"] == "fail"
    assert "promo_render_mode_not_fallback" in verification["issues"]
    assert "promo_verdict_not_ready_via_fallback" in verification["issues"]
    assert "provider_ready_overclaim" in verification["issues"]
    assert "live_provider_runtime_overclaim" in verification["issues"]
    assert "verified_provider_claim_overclaim" in verification["issues"]


def test_verify_ea_promo_video_fallback_rejects_malformed_captions(tmp_path: Path) -> None:
    materializer = _load_script("materialize_ea_promo_video_fallback")
    verifier = _load_script("verify_ea_promo_video_fallback")
    output_dir = tmp_path / "bad-vtt"
    materializer.materialize_fallback_promo(output_dir=output_dir, generated_at=GENERATED_AT)
    (output_dir / "promo.vtt").write_text("not webvtt\n", encoding="utf-8")

    verification = verifier.verify_fallback_promo(output_dir)

    assert verification["status"] == "fail"
    assert "promo_vtt_not_webvtt" in verification["issues"]
    assert "promo_vtt_cue_count_mismatch" in verification["issues"]


def test_verify_ea_promo_video_fallback_rejects_scene_bound_narration_overclaim(tmp_path: Path) -> None:
    materializer = _load_script("materialize_ea_promo_video_fallback")
    verifier = _load_script("verify_ea_promo_video_fallback")
    output_dir = tmp_path / "scene-bound"
    materializer.materialize_fallback_promo(output_dir=output_dir, generated_at=GENERATED_AT)
    promo_path = output_dir / "promo.json"
    promo = _load(promo_path)
    promo["narration"]["scene_bound"] = True  # type: ignore[index]
    promo_path.write_text(json.dumps(promo, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    narration_path = output_dir / "narration_windows.generated.json"
    narration = _load(narration_path)
    narration["scene_bound"] = True
    narration["windows"][0]["scene_bound"] = True  # type: ignore[index]
    narration_path.write_text(json.dumps(narration, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    verification = verifier.verify_fallback_promo(output_dir)

    assert verification["status"] == "fail"
    assert "narration_scene_bound_overclaim" in verification["issues"]
    assert "narration_packet_scene_bound_overclaim" in verification["issues"]
    assert "narration_window_scene_bound_overclaim" in verification["issues"]


def test_verify_ea_promo_video_fallback_rejects_preview_provider_overclaim(tmp_path: Path) -> None:
    materializer = _load_script("materialize_ea_promo_video_fallback")
    verifier = _load_script("verify_ea_promo_video_fallback")
    output_dir = tmp_path / "preview-overclaim"
    materializer.materialize_fallback_promo(
        output_dir=output_dir,
        requested_provider="Advertisemind",
        generated_at=GENERATED_AT,
    )
    (output_dir / "promo.html").write_text(
        "<html><body>VERIFIED_PROVIDER Advertisemind provider_video</body></html>\n",
        encoding="utf-8",
    )

    verification = verifier.verify_fallback_promo(output_dir)

    assert verification["status"] == "fail"
    assert "promo_preview_missing_fallback_posture" in verification["issues"]
    assert "promo_preview_provider_name" in verification["issues"]
    assert "promo_preview_verified_provider_overclaim" in verification["issues"]
    assert "promo_preview_scene_count_mismatch" in verification["issues"]


def test_ea_promo_video_fallback_clis_work(tmp_path: Path) -> None:
    script_root = Path(__file__).resolve().parents[1] / "ea" / "scripts"
    output_dir = tmp_path / "cli-artifacts"

    materialized = subprocess.run(
        [
            sys.executable,
            str(script_root / "materialize_ea_promo_video_fallback.py"),
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

    assert materialized.returncode == 0
    body = json.loads(materialized.stdout)
    assert body["verdict"] == "READY_VIA_FALLBACK"
    verified = subprocess.run(
        [
            sys.executable,
            str(script_root / "verify_ea_promo_video_fallback.py"),
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
