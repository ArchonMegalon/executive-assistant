from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _script() -> Path:
    return Path(__file__).resolve().parents[1] / "scripts" / "verify_memorial_joggai_asset.py"


def _write_video(path: Path) -> None:
    completed = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=640x360:d=1",
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
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def _write_script_packet(path: Path, **overrides: object) -> None:
    packet: dict[str, object] = {
        "script_id": "how-this-memorial-works-v1",
        "audience": "public",
        "provider": "joggai",
        "speaker_type": "neutral_presenter",
        "uses_manfred_likeness": False,
        "uses_manfred_voice": False,
        "approved_by": "operator",
        "approved_at": "2026-06-11T00:00:00Z",
        "source_material": ["memorial_disclosure.md"],
        "script": "This memorial is a sourced memory interface and does not claim literal presence.",
    }
    packet.update(overrides)
    path.write_text(json.dumps(packet, ensure_ascii=False), encoding="utf-8")


def _write_provider_receipt(path: Path, *, verdict: str = "VERIFIED_PROVIDER", provider_ready: bool = True) -> None:
    path.write_text(
        json.dumps(
            {
                "contract_name": "executive_assistant.joggai_provider_verification.v1",
                "provider": "joggai",
                "provider_key": "joggai",
                "verdict": verdict,
                "provider_ready": provider_ready,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _run_verifier(tmp_path: Path, *, packet_overrides: dict[str, object] | None = None, extra_args: list[str] | None = None) -> subprocess.CompletedProcess[str]:
    asset = tmp_path / "how-this-memorial-works.mp4"
    poster = tmp_path / "how-this-memorial-works-poster.webp"
    packet = tmp_path / "script.json"
    output = tmp_path / "receipt.json"
    _write_video(asset)
    poster.write_bytes(b"poster")
    _write_script_packet(packet, **(packet_overrides or {}))
    command = [
        sys.executable,
        str(_script()),
        "--slug",
        "manfred",
        "--asset",
        str(asset),
        "--poster",
        str(poster),
        "--script-packet",
        str(packet),
        "--output",
        str(output),
        "--asset-relpath",
        "video/joggai/how-this-memorial-works.mp4",
        "--poster-relpath",
        "video/joggai/how-this-memorial-works-poster.webp",
    ]
    command.extend(extra_args or [])
    return subprocess.run(command, cwd="/docker/EA", text=True, capture_output=True, check=False)


def test_joggai_asset_verifier_writes_public_ready_receipt(tmp_path: Path) -> None:
    provider_receipt = tmp_path / "JOGGAI_PROVIDER_VERIFICATION.generated.json"
    _write_provider_receipt(provider_receipt)
    result = _run_verifier(
        tmp_path,
        extra_args=[
            "--review-status",
            "approved",
            "--public-ready",
            "--provider-verification-receipt",
            str(provider_receipt),
        ],
    )

    assert result.returncode == 0, result.stderr
    receipt = json.loads((tmp_path / "receipt.json").read_text(encoding="utf-8"))
    assert receipt["contract_name"] == "executive_assistant.memorial_joggai_render.v1"
    assert receipt["provider_key"] == "joggai"
    assert receipt["slug"] == "manfred"
    assert receipt["script_id"] == "how-this-memorial-works-v1"
    assert receipt["asset_relpath"] == "video/joggai/how-this-memorial-works.mp4"
    assert receipt["asset_metadata"]["codec_name"] == "h264"
    assert receipt["asset_metadata"]["width"] == 640
    assert receipt["asset_metadata"]["height"] == 360
    assert receipt["aspect_ratio"] == "16:9"
    assert receipt["review_status"] == "approved"
    assert receipt["public_ready"] is True
    assert receipt["provider_verdict_required"] == "VERIFIED_PROVIDER"
    assert receipt["provider_verification_receipt"] == str(provider_receipt)
    assert receipt["provider_verification_sha256"]
    assert receipt["api_used"] is False


def test_joggai_asset_verifier_rejects_public_ready_without_verified_provider_receipt(tmp_path: Path) -> None:
    result = _run_verifier(tmp_path, extra_args=["--review-status", "approved", "--public-ready"])

    assert result.returncode != 0
    assert "public_ready_requires_provider_verification_receipt" in (result.stderr + result.stdout)


def test_joggai_asset_verifier_defaults_to_public_bundle_relpaths(tmp_path: Path) -> None:
    asset = tmp_path / "intro.mp4"
    poster = tmp_path / "intro-poster.webp"
    packet = tmp_path / "script.json"
    output = tmp_path / "receipt.json"
    _write_video(asset)
    poster.write_bytes(b"poster")
    _write_script_packet(packet)

    result = subprocess.run(
        [
            sys.executable,
            str(_script()),
            "--slug",
            "manfred",
            "--asset",
            str(asset),
            "--poster",
            str(poster),
            "--script-packet",
            str(packet),
            "--output",
            str(output),
        ],
        cwd="/docker/EA",
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    receipt = json.loads(output.read_text(encoding="utf-8"))
    assert receipt["asset_relpath"] == "video/joggai/intro.mp4"
    assert receipt["poster_relpath"] == "video/joggai/intro-poster.webp"


def test_joggai_asset_verifier_rejects_forbidden_presence_claim(tmp_path: Path) -> None:
    result = _run_verifier(
        tmp_path,
        packet_overrides={"script": "I am Manfred and I am here again."},
        extra_args=["--review-status", "approved", "--public-ready"],
    )

    assert result.returncode != 0
    assert "script_forbidden_memorial_claim" in (result.stderr or result.stdout)


def test_joggai_asset_verifier_requires_avatar_consent_for_manfred_likeness(tmp_path: Path) -> None:
    result = _run_verifier(
        tmp_path,
        packet_overrides={"uses_manfred_likeness": True},
        extra_args=["--review-status", "approved", "--public-ready"],
    )

    assert result.returncode != 0
    assert "avatar_consent_required" in (result.stderr or result.stdout)


def test_joggai_asset_verifier_allows_candidate_likeness_with_consent(tmp_path: Path) -> None:
    result = _run_verifier(
        tmp_path,
        packet_overrides={
            "uses_manfred_likeness": True,
            "avatar_consent": {
                "status": "approved",
                "scope": ["joggai_candidate_render", "family_review"],
                "authorized_by": "family-owner",
                "authorized_at": "2026-06-11T00:00:00Z",
                "source_assets_reviewed": True,
                "revoked": False,
            },
        },
    )

    assert result.returncode == 0, result.stderr
    receipt = json.loads((tmp_path / "receipt.json").read_text(encoding="utf-8"))
    assert receipt["uses_manfred_likeness"] is True
    assert receipt["public_ready"] is False
    assert receipt["review_status"] == "candidate"


def test_joggai_asset_verifier_requires_public_playback_for_public_likeness(tmp_path: Path) -> None:
    result = _run_verifier(
        tmp_path,
        packet_overrides={
            "uses_manfred_likeness": True,
            "avatar_consent": {
                "status": "approved",
                "scope": ["joggai_candidate_render", "family_review"],
                "authorized_by": "family-owner",
                "authorized_at": "2026-06-11T00:00:00Z",
                "source_assets_reviewed": True,
                "revoked": False,
            },
        },
        extra_args=["--review-status", "approved", "--public-ready"],
    )

    assert result.returncode != 0
    assert "avatar_consent_scope_missing:public_playback" in (result.stderr or result.stdout)


def test_joggai_asset_verifier_requires_voice_consent_for_manfred_voice(tmp_path: Path) -> None:
    result = _run_verifier(
        tmp_path,
        packet_overrides={"uses_manfred_voice": True},
    )

    assert result.returncode != 0
    assert "voice_consent_required" in (result.stderr or result.stdout)


def test_joggai_asset_verifier_allows_manfred_voice_with_specific_consent(tmp_path: Path) -> None:
    provider_receipt = tmp_path / "JOGGAI_PROVIDER_VERIFICATION.generated.json"
    _write_provider_receipt(provider_receipt)
    result = _run_verifier(
        tmp_path,
        packet_overrides={
            "uses_manfred_voice": True,
            "voice_consent": {
                "status": "approved",
                "scope": ["joggai_candidate_render", "clone", "public_playback"],
                "authorized_by": "family-owner",
                "authorized_at": "2026-06-11T00:00:00Z",
                "revoked": False,
            },
        },
        extra_args=[
            "--review-status",
            "approved",
            "--public-ready",
            "--provider-verification-receipt",
            str(provider_receipt),
        ],
    )

    assert result.returncode == 0, result.stderr
    receipt = json.loads((tmp_path / "receipt.json").read_text(encoding="utf-8"))
    assert receipt["uses_manfred_voice"] is True
    assert receipt["public_ready"] is True


def test_joggai_asset_verifier_requires_private_memory_review(tmp_path: Path) -> None:
    result = _run_verifier(
        tmp_path,
        packet_overrides={"uses_private_memory": True},
    )

    assert result.returncode != 0
    assert "private_memory_review_required" in (result.stderr or result.stdout)


def test_joggai_asset_verifier_blocks_public_ready_candidate(tmp_path: Path) -> None:
    result = _run_verifier(tmp_path, extra_args=["--public-ready"])

    assert result.returncode != 0
    assert "public_ready_requires_approved_review" in (result.stderr or result.stdout)


def test_joggai_asset_verifier_rejects_unsafe_manifest_relpath(tmp_path: Path) -> None:
    result = _run_verifier(
        tmp_path,
        extra_args=[
            "--review-status",
            "approved",
            "--public-ready",
            "--asset-relpath",
            "../private.mp4",
        ],
    )

    assert result.returncode != 0
    assert "asset_relpath_unsafe" in (result.stderr or result.stdout)


def test_joggai_asset_verifier_rejects_absolute_manifest_relpath(tmp_path: Path) -> None:
    result = _run_verifier(
        tmp_path,
        extra_args=[
            "--review-status",
            "approved",
            "--public-ready",
            "--asset-relpath",
            "/tmp/private.mp4",
        ],
    )

    assert result.returncode != 0
    assert "asset_relpath_unsafe" in (result.stderr or result.stdout)
