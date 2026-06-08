from __future__ import annotations

import json
import subprocess
from pathlib import Path


def _make_wav(path: Path) -> None:
    completed = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_prepare_memorial_vidboard_avatar_packet_writes_expected_artifacts(tmp_path: Path) -> None:
    bundle_root = tmp_path / "bundles"
    bundle_dir = bundle_root / "manfred"
    (bundle_dir / "icons").mkdir(parents=True)
    (bundle_dir / "audio").mkdir(parents=True)
    (bundle_dir / "icons" / "manfred-pwa-icon-512.png").write_bytes(b"png")
    _make_wav(bundle_dir / "audio" / "demo.wav")
    (bundle_dir / "memorial.json").write_text(
        json.dumps(
            {
                "slug": "manfred",
                "person_name": "Manfred Hoza",
                "branding": {"icons": {"src_512": "icons/manfred-pwa-icon-512.png"}},
                "audio_clips": [
                    {
                        "title": "Archivsegment",
                        "description": "Originalaufnahme",
                        "asset_relpath": "audio/demo.wav",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    output_root = tmp_path / "packets"
    script = Path(__file__).resolve().parents[1] / "scripts" / "prepare_memorial_vidboard_avatar_packet.py"
    completed = subprocess.run(
        [
            "python3",
            str(script),
            "--slug",
            "manfred",
            "--bundle-root",
            str(bundle_root),
            "--output-root",
            str(output_root),
            "--duration-seconds",
            "1.5",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    packet_path = Path(completed.stdout.strip())
    payload = json.loads(packet_path.read_text(encoding="utf-8"))
    assert payload["slug"] == "manfred"
    assert payload["provider_key"] == "vidboard"
    assert payload["portrait"]["path"].endswith(".png")
    assert payload["audio_segment"]["path"].endswith(".wav")
    assert payload["audio_segment"]["duration_seconds"] == 1.5
    assert payload["transcript_text"] == ""
    assert "talking-photo clip" in payload["provider_instruction"]
    assert (packet_path.parent / "README.md").is_file()


def test_prepare_memorial_vidboard_avatar_packet_rejects_missing_bundle(tmp_path: Path) -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "prepare_memorial_vidboard_avatar_packet.py"
    completed = subprocess.run(
        [
            "python3",
            str(script),
            "--slug",
            "missing",
            "--bundle-root",
            str(tmp_path / "bundles"),
            "--output-root",
            str(tmp_path / "packets"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode != 0
    assert "memorial_bundle_missing" in completed.stderr
