from __future__ import annotations

import importlib.util
import io
import json
import math
import struct
import wave
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "materialize_memorial_stt_capture_discovery.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("materialize_memorial_stt_capture_discovery", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _wav_bytes(*, duration_seconds: float = 3.0) -> bytes:
    sample_rate = 16_000
    total_frames = max(1, int(sample_rate * duration_seconds))
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        frames = bytearray()
        for index in range(total_frames):
            sample = int(9000 * math.sin(2.0 * math.pi * 260 * index / sample_rate))
            frames.extend(struct.pack("<h", sample))
        wav.writeframes(bytes(frames))
    return buffer.getvalue()


def _bundle(tmp_path: Path, *, text: str, duration_seconds: float) -> Path:
    bundle = tmp_path / "manfred" / "2026" / "06" / "16" / "captured"
    bundle.mkdir(parents=True)
    (bundle / "input.wav").write_bytes(_wav_bytes(duration_seconds=duration_seconds))
    (bundle / "error.json").write_text(
        json.dumps(
            {
                "route": "conversation_turn",
                "reason": "conversation_turn_llm_timeout",
                "content_type": "audio/wav",
                "stored_wav": True,
                "answer": {"question": text},
                "transcription": {
                    "transcript_effective_text": text,
                    "transcript_text": text,
                },
            }
        ),
        encoding="utf-8",
    )
    return bundle


def test_memorial_stt_capture_discovery_finds_promotable_redacted_candidate(tmp_path: Path) -> None:
    module = _load_module()
    bundle = _bundle(
        tmp_path,
        text="Hallo Manfred, kannst du jetzt mit mir sprechen?",
        duration_seconds=3.0,
    )

    payload = module.build_discovery(
        bundle_dirs=[bundle],
        samples={"contact_opening"},
        bundle_root=tmp_path,
    )

    assert payload["status"] == "pass"
    assert payload["promotable_count"] == 1
    assert payload["raw_text_fields"] is False
    row = payload["rows"][0]
    assert row["status"] == "pass"
    assert row["sample"] == "contact_opening"
    assert row["expected_text_chars"] == 48
    assert row["expected_text_sha256"]
    assert row["required_token_count"] == 3
    assert "Hallo Manfred" not in str(payload)


def test_memorial_stt_capture_discovery_blocks_truncated_candidate(tmp_path: Path) -> None:
    module = _load_module()
    bundle = _bundle(
        tmp_path,
        text="Hallo Manfred, kannst du jetzt mit mir sprechen?",
        duration_seconds=0.35,
    )

    payload = module.build_discovery(
        bundle_dirs=[bundle],
        samples={"contact_opening"},
        bundle_root=tmp_path,
    )

    assert payload["status"] == "blocked"
    assert payload["promotable_count"] == 0
    assert payload["rows"][0]["failed_codes"] == ["audio_too_short_for_expected_text"]
    assert payload["failed_codes"] == ["audio_too_short_for_expected_text"]


def test_memorial_stt_capture_discovery_ignores_nonmatching_bundle(tmp_path: Path) -> None:
    module = _load_module()
    bundle = _bundle(
        tmp_path,
        text="Ganz anderer Text.",
        duration_seconds=3.0,
    )

    payload = module.build_discovery(
        bundle_dirs=[bundle],
        samples={"contact_opening"},
        bundle_root=tmp_path,
    )

    assert payload["status"] == "blocked"
    assert payload["matched_count"] == 0
    assert payload["rows"] == []


def test_memorial_stt_capture_discovery_auto_discovers_nested_private_bundles(tmp_path: Path) -> None:
    module = _load_module()
    bundle = _bundle(
        tmp_path,
        text="Hallo Manfred, kannst du jetzt mit mir sprechen?",
        duration_seconds=3.0,
    )
    ignored = tmp_path / "manfred" / "2026" / "06" / "16" / "metadata-only"
    ignored.mkdir(parents=True)
    (ignored / "error.json").write_text("{}", encoding="utf-8")

    discovered = module.discover_bundle_dirs(tmp_path)

    assert discovered == [bundle]

    payload = module.build_discovery(
        bundle_dirs=discovered,
        samples={"contact_opening"},
        bundle_root=tmp_path,
        bundle_discovery_mode="auto_bundle_root_scan",
    )

    assert payload["status"] == "pass"
    assert payload["bundle_count"] == 1
    assert payload["bundle_discovery_mode"] == "auto_bundle_root_scan"
    assert payload["promotable_count"] == 1
