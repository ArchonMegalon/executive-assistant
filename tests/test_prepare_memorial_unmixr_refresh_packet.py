from __future__ import annotations

import wave
from pathlib import Path

import pytest

from scripts import prepare_memorial_unmixr_refresh_packet as packet


def _write_wav(path: Path, *, seconds: float = 30.0) -> None:
    sample_rate = 16_000
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b"\0\0" * int(sample_rate * seconds))


def test_default_packet_uses_single_reviewed_xlr_sample() -> None:
    assert packet.DEFAULT_SEGMENT_RELATIVE_PATHS == (
        Path("voice_profile/curated/manfred-unmixr-xlr-1325-1355-v1.wav"),
    )


def test_packet_hash_binds_audio_shape_and_duration(tmp_path: Path) -> None:
    source = tmp_path / "manfred-reviewed.wav"
    _write_wav(source)

    payload = packet.build_packet(
        slug="manfred",
        voice_label="Manfred reviewed",
        segment_paths=[source],
        output_dir=tmp_path / "receipt",
    )

    assert len(payload["segments"]) == 1
    segment = payload["segments"][0]
    assert segment["filename"] == source.name
    assert segment["duration_seconds"] == 30.0
    assert segment["sample_rate_hz"] == 16_000
    assert segment["channels"] == 1
    assert segment["codec_name"] == "pcm_s16le"
    assert len(segment["sha256"]) == 64


def test_packet_rejects_multiple_too_short_or_overlong_sources(tmp_path: Path) -> None:
    first = tmp_path / "first.wav"
    second = tmp_path / "second.wav"
    too_short = tmp_path / "too-short.wav"
    overlong = tmp_path / "overlong.wav"
    _write_wav(first)
    _write_wav(second)
    _write_wav(too_short, seconds=29.8)
    _write_wav(overlong, seconds=75.2)

    with pytest.raises(ValueError, match="single_prepared_segment_required"):
        packet.build_packet(
            slug="manfred",
            voice_label="Manfred reviewed",
            segment_paths=[first, second],
            output_dir=tmp_path / "multiple",
        )

    with pytest.raises(ValueError, match="segment_audio_too_short"):
        packet.build_packet(
            slug="manfred",
            voice_label="Manfred reviewed",
            segment_paths=[too_short],
            output_dir=tmp_path / "too-short",
        )

    with pytest.raises(ValueError, match="segment_audio_too_long"):
        packet.build_packet(
            slug="manfred",
            voice_label="Manfred reviewed",
            segment_paths=[overlong],
            output_dir=tmp_path / "overlong",
        )
