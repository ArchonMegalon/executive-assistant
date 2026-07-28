from __future__ import annotations

import hashlib
import json
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


def _write_provenance(path: Path, *, seconds: float = 30.0) -> Path:
    provenance_path = path.with_suffix(".provenance.json")
    provenance_path.write_text(
        json.dumps(
            {
                "schema": "ea.memorial.voice_clone_source_provenance.v1",
                "status": "reviewed",
                "provider": "unmixr",
                "prepared_sample": {
                    "path": f"voice_profile/curated/{path.name}",
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "duration_seconds": seconds,
                },
                "speaker_review": {"single_speaker": True},
                "exclusions": [
                    "other speakers",
                    "cross-recording concatenation",
                ],
            }
        ),
        encoding="utf-8",
    )
    return provenance_path


def test_default_packet_uses_single_reviewed_osq_sample() -> None:
    assert packet.DEFAULT_SEGMENT_RELATIVE_PATHS == (
        Path("voice_profile/curated/manfred-unmixr-osq-1438-1478-v2.wav"),
    )


def test_packet_hash_binds_audio_shape_and_duration(tmp_path: Path) -> None:
    source = tmp_path / "manfred-reviewed.wav"
    _write_wav(source)
    provenance_path = _write_provenance(source)

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
    assert payload["source_provenance"]["path"] == provenance_path.as_posix()
    assert len(payload["source_provenance"]["sha256"]) == 64


def test_packet_rejects_unreviewed_or_mismatched_source_provenance(
    tmp_path: Path,
) -> None:
    source = tmp_path / "manfred-unreviewed.wav"
    _write_wav(source)

    with pytest.raises(ValueError, match="segment_source_provenance_missing"):
        packet.build_packet(
            slug="manfred",
            voice_label="Manfred reviewed",
            segment_paths=[source],
            output_dir=tmp_path / "missing",
        )

    provenance_path = _write_provenance(source)
    payload = json.loads(provenance_path.read_text(encoding="utf-8"))
    payload["speaker_review"]["single_speaker"] = False
    provenance_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="segment_source_provenance_invalid"):
        packet.build_packet(
            slug="manfred",
            voice_label="Manfred reviewed",
            segment_paths=[source],
            output_dir=tmp_path / "unreviewed",
        )


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


def test_clone_attempt_requires_exact_account_when_multiple_slots_exist(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "reviewed.wav"
    _write_wav(source)
    clone_called = False

    monkeypatch.setattr(
        packet,
        "_load_unmixr_slots_from_live_env",
        lambda requested_slot="": (
            "UNMIXR_API_KEY",
            "UNMIXR_API_KEY_FALLBACK_2",
        ),
    )

    def clone(**kwargs):
        nonlocal clone_called
        clone_called = True
        return "unexpected"

    monkeypatch.setattr(packet, "unmixr_clone_request", clone)

    result = packet.attempt_clone(
        slug="manfred",
        voice_label="Manfred reviewed",
        segment_paths=[source],
    )

    assert result["status"] == "blocked"
    assert result["code"] == "unmixr_account_slot_required"
    assert clone_called is False


def test_clone_attempt_pins_the_only_available_account_slot(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "reviewed.wav"
    _write_wav(source)
    calls: list[dict[str, object]] = []

    monkeypatch.setattr(
        packet,
        "_load_unmixr_slots_from_live_env",
        lambda requested_slot="": ("UNMIXR_API_KEY_FALLBACK_2",),
    )
    monkeypatch.setattr(
        packet,
        "unmixr_clone_request",
        lambda **kwargs: calls.append(dict(kwargs)) or "new-voice",
    )

    result = packet.attempt_clone(
        slug="manfred",
        voice_label="Manfred reviewed",
        segment_paths=[source],
    )

    assert result == {
        "status": "created",
        "voice_id": "new-voice",
        "account_slot": "UNMIXR_API_KEY_FALLBACK_2",
    }
    assert calls[0]["account_slot"] == "UNMIXR_API_KEY_FALLBACK_2"
