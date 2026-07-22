from __future__ import annotations

import base64
import io
from typing import Any
import wave

import pytest

from app.services.audiobook_tts.output_validation import (
    AudioOutputValidationError,
    decode_inline_audio,
    download_provider_audio,
    validate_audio_bytes,
    validate_provider_audio_url,
)


def _wav(*, frames: int = 4410, sample_rate: int = 44100) -> bytes:
    target = io.BytesIO()
    with wave.open(target, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        writer.writeframes(b"\x00\x00" * frames)
    return target.getvalue()


def _validate(audio: bytes, **changes: object):  # type: ignore[no-untyped-def]
    values: dict[str, object] = {
        "expected_format": "wav",
        "expected_sample_rate": 44100,
        "content_type": "audio/wav",
        "max_audio_bytes": 1024 * 1024,
    }
    values.update(changes)
    return validate_audio_bytes(audio, **values)  # type: ignore[arg-type]


def test_valid_wav_requires_complete_real_frames_and_redacts_bytes_from_repr() -> None:
    audio = _wav()
    result = _validate(audio)
    assert result.audio_bytes == audio
    assert result.sample_rate == 44100
    assert "audio_bytes" not in repr(result)
    assert repr(audio) not in repr(result)


@pytest.mark.parametrize(
    "audio",
    [
        b"RIFF" + b"\x00" * 40,
        _wav(frames=0),
        _wav(frames=100),
        _wav(frames=2205),
    ],
)
def test_empty_header_only_and_implausibly_short_wav_are_rejected(audio: bytes) -> None:
    with pytest.raises(AudioOutputValidationError) as caught:
        _validate(audio)
    assert caught.value.code == "audio_structure_invalid"


def test_riff_length_and_full_declared_frame_payload_are_enforced() -> None:
    wrong_riff = bytearray(_wav())
    wrong_riff[4:8] = (1).to_bytes(4, "little")
    with pytest.raises(AudioOutputValidationError) as riff:
        _validate(bytes(wrong_riff))
    assert riff.value.code == "audio_structure_invalid"

    truncated = bytearray(_wav()[:-2])
    truncated[4:8] = (len(truncated) - 8).to_bytes(4, "little")
    with pytest.raises(AudioOutputValidationError) as frames:
        _validate(bytes(truncated))
    assert frames.value.code == "audio_structure_invalid"


def test_sample_rate_mime_and_size_are_strict() -> None:
    with pytest.raises(AudioOutputValidationError) as rate:
        _validate(_wav(sample_rate=48000))
    assert rate.value.code == "audio_sample_rate_mismatch"

    with pytest.raises(AudioOutputValidationError) as mime:
        _validate(_wav(), content_type="text/html")
    assert mime.value.code == "audio_content_type_invalid"

    with pytest.raises(AudioOutputValidationError) as size:
        _validate(_wav(), max_audio_bytes=100)
    assert size.value.code == "audio_too_large"


@pytest.mark.parametrize("audio_format", ["mp3", "flac", "ogg"])
def test_uninspected_non_wav_formats_are_rejected(audio_format: str) -> None:
    with pytest.raises(AudioOutputValidationError) as caught:
        _validate(
            b"synthetic-container",
            expected_format=audio_format,
            content_type={
                "mp3": "audio/mpeg",
                "flac": "audio/flac",
                "ogg": "audio/ogg",
            }[audio_format],
        )
    assert caught.value.code == "audio_format_not_inspected"


def test_inline_base64_is_bounded_and_data_url_mime_must_match() -> None:
    encoded = base64.b64encode(_wav()).decode()
    result = decode_inline_audio(
        f"data:audio/wav;base64,{encoded}",
        expected_format="wav",
        expected_sample_rate=44100,
        max_audio_bytes=1024 * 1024,
    )
    assert result.audio_bytes == _wav()

    for value, code in (
        ("data:audio/wav,not-base64", "audio_data_url_invalid"),
        (f"data:text/html;base64,{encoded}", "audio_content_type_invalid"),
        ("not base64", "audio_base64_invalid"),
    ):
        with pytest.raises(AudioOutputValidationError) as caught:
            decode_inline_audio(
                value,
                expected_format="wav",
                expected_sample_rate=44100,
                max_audio_bytes=1024 * 1024,
            )
        assert caught.value.code == code

    with pytest.raises(AudioOutputValidationError) as oversized:
        decode_inline_audio(
            encoded,
            expected_format="wav",
            expected_sample_rate=44100,
            max_audio_bytes=100,
        )
    assert oversized.value.code == "audio_too_large"


class NoNetworkSession:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def get(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append((args, kwargs))
        raise AssertionError("network must not be called")


def test_url_validation_and_download_are_unconditionally_disabled() -> None:
    with pytest.raises(AudioOutputValidationError) as validated:
        validate_provider_audio_url(
            "https://api.vocallab.ai/private.wav",
            allowed_hosts=("api.vocallab.ai",),
        )
    assert validated.value.code == "audio_url_fallback_disabled"

    session = NoNetworkSession()
    with pytest.raises(AudioOutputValidationError) as downloaded:
        download_provider_audio(
            session,
            "https://api.vocallab.ai/private.wav",
            allowed_hosts=("api.vocallab.ai",),
            expected_format="wav",
            expected_sample_rate=44100,
            max_audio_bytes=1024 * 1024,
            timeout_seconds=10,
        )
    assert downloaded.value.code == "audio_url_fallback_disabled"
    assert session.calls == []
