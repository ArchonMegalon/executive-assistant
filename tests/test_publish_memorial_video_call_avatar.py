from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType


def _load_script() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "scripts" / "publish_memorial_video_call_avatar.py"
    spec = importlib.util.spec_from_file_location("publish_memorial_video_call_avatar", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_memorial_bundle(root: Path, slug: str) -> Path:
    bundle_dir = root / slug
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "memorial.json").write_text(
        json.dumps({"slug": slug, "person_name": "Manfred Hoza", "audio_clips": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    return bundle_dir


def _write_proof(path: Path, *, verdict: str = "VERIFIED_PROVIDER", provider_ready: bool = True) -> None:
    path.write_text(
        json.dumps(
            {
                "generated_at": "2026-06-08T12:00:00Z",
                "provider": "VidBoard",
                "provider_key": "vidboard",
                "verdict": verdict,
                "provider_ready": provider_ready,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _write_test_video(path: Path) -> None:
    completed = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=320x240:d=2",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=44100:cl=mono",
            "-shortest",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_publish_memorial_video_call_avatar_updates_bundle_and_receipt(tmp_path: Path) -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "publish_memorial_video_call_avatar.py"
    bundle_root = tmp_path / "public_memorials"
    _write_memorial_bundle(bundle_root, "manfred")
    proof_path = tmp_path / "vidboard_AVATAR_PRESENTER_PROVIDER_PROOF.generated.json"
    _write_proof(proof_path)
    asset_path = tmp_path / "avatar.mp4"
    poster_path = tmp_path / "poster.png"
    _write_test_video(asset_path)
    poster_path.write_bytes(b"\x89PNG\r\n\x1a\nposter")
    receipt_path = tmp_path / "publish_receipt.generated.json"

    completed = subprocess.run(
        [
            "python3",
            str(script),
            "--slug",
            "manfred",
            "--provider",
            "vidboard",
            "--asset",
            str(asset_path),
            "--poster",
            str(poster_path),
            "--bundle-root",
            str(bundle_root),
            "--proof",
            str(proof_path),
            "--publish-receipt",
            str(receipt_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads((bundle_root / "manfred" / "memorial.json").read_text(encoding="utf-8"))
    avatar = dict(payload["video_call_avatar"])
    assert avatar["provider_key"] == "vidboard"
    assert avatar["provider_proof_verdict"] == "VERIFIED_PROVIDER"
    assert avatar["public_ready"] is True
    assert avatar["asset_relpath"].startswith("video/manfred-vidboard-avatar.")
    assert avatar["poster_relpath"].startswith("video/manfred-vidboard-avatar-poster.")
    assert avatar["asset_metadata"]["duration_seconds"] >= 1.0
    assert avatar["asset_metadata"]["width"] == 320
    assert avatar["asset_metadata"]["height"] == 240
    assert (bundle_root / "manfred" / avatar["asset_relpath"]).is_file()
    assert (bundle_root / "manfred" / avatar["poster_relpath"]).is_file()

    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["slug"] == "manfred"
    assert receipt["provider_key"] == "vidboard"
    assert receipt["provider_proof_verdict"] == "VERIFIED_PROVIDER"
    assert receipt["asset_metadata"]["codec_name"] == "h264"


def test_publish_memorial_video_call_avatar_generates_poster_when_missing(tmp_path: Path) -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "publish_memorial_video_call_avatar.py"
    bundle_root = tmp_path / "public_memorials"
    _write_memorial_bundle(bundle_root, "manfred")
    proof_path = tmp_path / "vidboard_AVATAR_PRESENTER_PROVIDER_PROOF.generated.json"
    _write_proof(proof_path)
    asset_path = tmp_path / "avatar.mp4"
    _write_test_video(asset_path)
    auto_poster_path = tmp_path / "generated-poster.png"

    completed = subprocess.run(
        [
            "python3",
            str(script),
            "--slug",
            "manfred",
            "--provider",
            "vidboard",
            "--asset",
            str(asset_path),
            "--poster",
            str(auto_poster_path),
            "--bundle-root",
            str(bundle_root),
            "--proof",
            str(proof_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert auto_poster_path.is_file()
    payload = json.loads((bundle_root / "manfred" / "memorial.json").read_text(encoding="utf-8"))
    avatar = dict(payload["video_call_avatar"])
    assert avatar["poster_relpath"].startswith("video/manfred-vidboard-avatar-poster.")


def test_publish_memorial_video_call_avatar_rejects_unverified_proof(tmp_path: Path) -> None:
    module = _load_script()
    bundle_root = tmp_path / "public_memorials"
    _write_memorial_bundle(bundle_root, "manfred")
    proof_path = tmp_path / "vidboard_AVATAR_PRESENTER_PROVIDER_PROOF.generated.json"
    _write_proof(proof_path, verdict="READY_VIA_FALLBACK", provider_ready=False)
    asset_path = tmp_path / "avatar.mp4"
    poster_path = tmp_path / "poster.png"
    _write_test_video(asset_path)
    poster_path.write_bytes(b"\x89PNG\r\n\x1a\nposter")

    try:
        module._validated_proof(proof_path, "vidboard")
    except SystemExit as exc:
        assert str(exc) == "provider_proof_not_verified"
    else:
        raise AssertionError("expected provider proof rejection")


def test_publish_memorial_video_call_avatar_rejects_too_short_video(tmp_path: Path) -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "publish_memorial_video_call_avatar.py"
    bundle_root = tmp_path / "public_memorials"
    _write_memorial_bundle(bundle_root, "manfred")
    proof_path = tmp_path / "vidboard_AVATAR_PRESENTER_PROVIDER_PROOF.generated.json"
    _write_proof(proof_path)
    asset_path = tmp_path / "avatar.mp4"
    poster_path = tmp_path / "poster.png"
    completed = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=320x240:d=0.3",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(asset_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    poster_path.write_bytes(b"\x89PNG\r\n\x1a\nposter")

    completed = subprocess.run(
        [
            "python3",
            str(script),
            "--slug",
            "manfred",
            "--provider",
            "vidboard",
            "--asset",
            str(asset_path),
            "--poster",
            str(poster_path),
            "--bundle-root",
            str(bundle_root),
            "--proof",
            str(proof_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "avatar_asset_too_short" in (completed.stderr or completed.stdout)
