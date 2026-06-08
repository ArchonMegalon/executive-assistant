from __future__ import annotations

import json
import subprocess
from pathlib import Path
from urllib.parse import urlparse


class _FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


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
    assert len(payload["candidate_segments"]) == 7
    assert isinstance(payload["selection_keywords"], list)
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


def test_prepare_memorial_vidboard_avatar_packet_selects_best_transcript(monkeypatch, tmp_path: Path) -> None:
    import scripts.prepare_memorial_vidboard_avatar_packet as packet

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
                "pwa_icon": {"src_512": "icons/manfred-pwa-icon-512.png"},
                "audio_clips": [{"title": "Archivsegment", "description": "Originalaufnahme", "asset_relpath": "audio/demo.wav"}],
                "memory_cards": [{"title": "Schach und Familie", "body": "Das Schach bleibt in der Familie."}],
            }
        ),
        encoding="utf-8",
    )

    transcripts = {
        0.0: "belangloser einstieg",
        120.0: "Das Schach bleibt in der Familie.",
        300.0: "anderer text",
        600.0: "",
        900.0: "",
        1200.0: "",
        1800.0: "",
    }

    def _fake_urlopen(request, timeout=120):
        parsed = urlparse(request.full_url)
        assert parsed.path.endswith("/speech-transcribe")
        payload = request.data or b""
        # infer candidate from output filenames written in order by current selector
        index = len(calls)
        calls.append(index)
        start = [0.0, 120.0, 300.0, 600.0, 900.0, 1200.0, 1800.0][index]
        return _FakeResponse({"transcription_status": "transcribed", "transcript_text": transcripts[start], "transcriber": "test"})

    calls: list[int] = []
    monkeypatch.setattr(packet.urllib.request, "urlopen", _fake_urlopen)
    output_root = tmp_path / "packets"
    bundle_dir2, memorial = packet._bundle_paths("manfred", bundle_root)
    audio_source = packet._audio_source(bundle_dir2, packet._first_audio_clip(memorial))
    packet_dir = output_root / "manfred_vidboard_avatar_packet"
    packet_dir.mkdir(parents=True, exist_ok=True)
    selected_path, transcript, transcript_text, candidates, selected_candidate = packet._curate_segment(
        audio_source=audio_source,
        packet_dir=packet_dir,
        slug="manfred",
        base_url="http://example.test",
        duration_seconds=1.5,
        start_seconds=0.0,
        memorial=memorial,
    )
    assert selected_path.name == "manfred-public-audio-segment.wav"
    assert transcript_text == "Das Schach bleibt in der Familie."
    assert transcript["transcriber"] == "test"
    assert selected_candidate["start_seconds"] == 120.0
    assert max(item["score"] for item in candidates) == next(item["score"] for item in candidates if item["transcript_text"] == transcript_text)
