"""Bounded validation for provider-produced audiobook audio.

The provider boundary never trusts an upstream MIME type, data URL, redirect,
or hostname merely because it came from a successful JSON response.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
import base64
import binascii
import io
import ipaddress
import socket
import time
from typing import Any
from urllib.parse import urlsplit
import wave


_FORMAT_MIME_TYPES: dict[str, frozenset[str]] = {
    "wav": frozenset({"audio/wav", "audio/x-wav", "audio/wave"}),
    "mp3": frozenset({"audio/mpeg", "audio/mp3"}),
    "flac": frozenset({"audio/flac", "audio/x-flac"}),
    "ogg": frozenset({"audio/ogg", "application/ogg"}),
}
_MIN_WAV_DURATION_NUMERATOR = 2
_MIN_WAV_DURATION_DENOMINATOR = 25  # 80 ms of complete PCM frames.


class AudioOutputValidationError(RuntimeError):
    """Code-only validation error safe for logs and public failures."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class ValidatedAudio:
    audio_bytes: bytes = field(repr=False)
    content_type: str
    audio_format: str
    sample_rate: int


def _normalized_content_type(value: str) -> str:
    return str(value or "").split(";", 1)[0].strip().lower()


def _validate_wav(audio: bytes, expected_sample_rate: int) -> int:
    if len(audio) < 44 or audio[:4] != b"RIFF" or audio[8:12] != b"WAVE":
        raise AudioOutputValidationError("audio_structure_invalid")
    if int.from_bytes(audio[4:8], "little") + 8 != len(audio):
        raise AudioOutputValidationError("audio_structure_invalid")
    try:
        with wave.open(io.BytesIO(audio), "rb") as reader:
            sample_rate = int(reader.getframerate())
            frame_count = int(reader.getnframes())
            channels = int(reader.getnchannels())
            sample_width = int(reader.getsampwidth())
            if (
                frame_count <= 0
                or frame_count * _MIN_WAV_DURATION_DENOMINATOR
                < sample_rate * _MIN_WAV_DURATION_NUMERATOR
                or channels not in {1, 2}
                or sample_width not in {1, 2, 3, 4}
                or reader.getcomptype() != "NONE"
            ):
                raise AudioOutputValidationError("audio_structure_invalid")
            frames = reader.readframes(frame_count)
            if len(frames) != frame_count * channels * sample_width:
                raise AudioOutputValidationError("audio_structure_invalid")
            if reader.readframes(1):
                raise AudioOutputValidationError("audio_structure_invalid")
    except AudioOutputValidationError:
        raise
    except (EOFError, wave.Error):
        raise AudioOutputValidationError("audio_structure_invalid") from None
    if sample_rate != expected_sample_rate:
        raise AudioOutputValidationError("audio_sample_rate_mismatch")
    return sample_rate


def validate_audio_bytes(
    audio: bytes,
    *,
    expected_format: str,
    expected_sample_rate: int,
    content_type: str,
    max_audio_bytes: int,
) -> ValidatedAudio:
    """Validate bounded bytes against both declared and structural format."""

    normalized_format = str(expected_format or "").strip().lower()
    normalized_type = _normalized_content_type(content_type)
    if normalized_format != "wav":
        raise AudioOutputValidationError("audio_format_not_inspected")
    if normalized_format not in _FORMAT_MIME_TYPES:
        raise AudioOutputValidationError("audio_format_invalid")
    if normalized_type not in _FORMAT_MIME_TYPES[normalized_format]:
        raise AudioOutputValidationError("audio_content_type_invalid")
    if not isinstance(audio, bytes) or not audio:
        raise AudioOutputValidationError("audio_empty")
    if max_audio_bytes <= 0 or len(audio) > max_audio_bytes:
        raise AudioOutputValidationError("audio_too_large")

    sample_rate = expected_sample_rate
    if normalized_format == "wav":
        sample_rate = _validate_wav(audio, expected_sample_rate)

    return ValidatedAudio(
        audio_bytes=audio,
        content_type=normalized_type,
        audio_format=normalized_format,
        sample_rate=sample_rate,
    )


def decode_inline_audio(
    value: str,
    *,
    expected_format: str,
    expected_sample_rate: int,
    max_audio_bytes: int,
) -> ValidatedAudio:
    """Decode strict base64 (optionally a matching audio data URL)."""

    if not isinstance(value, str) or not value:
        raise AudioOutputValidationError("audio_base64_missing")
    expected = str(expected_format).strip().lower()
    content_type = next(iter(sorted(_FORMAT_MIME_TYPES.get(expected, ()))), "")
    encoded = value
    if value.startswith("data:"):
        prefix, separator, encoded = value.partition(",")
        if not separator or not prefix.endswith(";base64"):
            raise AudioOutputValidationError("audio_data_url_invalid")
        content_type = _normalized_content_type(prefix[5:-7])
        if content_type not in _FORMAT_MIME_TYPES.get(expected, frozenset()):
            raise AudioOutputValidationError("audio_content_type_invalid")
    elif "://" in value or "," in value:
        raise AudioOutputValidationError("audio_base64_invalid")

    # Reject before allocating the decoded payload.  Four encoded bytes carry
    # at most three decoded bytes; eight bytes cover legal padding.
    encoded_limit = ((max_audio_bytes + 2) // 3) * 4 + 8
    if len(encoded) > encoded_limit:
        raise AudioOutputValidationError("audio_too_large")
    try:
        audio = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise AudioOutputValidationError("audio_base64_invalid") from None
    return validate_audio_bytes(
        audio,
        expected_format=expected,
        expected_sample_rate=expected_sample_rate,
        content_type=content_type,
        max_audio_bytes=max_audio_bytes,
    )


Resolver = Callable[..., list[tuple[Any, ...]]]


def validate_provider_audio_url(
    value: str,
    *,
    allowed_hosts: Iterable[str],
    resolver: Resolver = socket.getaddrinfo,
) -> str:
    """URL output is deliberately unavailable in the offline adapter phase."""

    del value, allowed_hosts, resolver
    raise AudioOutputValidationError("audio_url_fallback_disabled")


def download_provider_audio(
    session: Any,
    value: str,
    *,
    allowed_hosts: Iterable[str],
    expected_format: str,
    expected_sample_rate: int,
    max_audio_bytes: int,
    timeout_seconds: int,
    resolver: Resolver = socket.getaddrinfo,
    monotonic: Callable[[], float] = time.monotonic,
) -> ValidatedAudio:
    del (
        session,
        value,
        allowed_hosts,
        expected_format,
        expected_sample_rate,
        max_audio_bytes,
        timeout_seconds,
        resolver,
        monotonic,
    )
    raise AudioOutputValidationError("audio_url_fallback_disabled")
