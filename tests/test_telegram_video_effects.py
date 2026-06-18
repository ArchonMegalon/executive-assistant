from __future__ import annotations

import io
import socket

import pytest

from app.services import telegram_video_effects


def test_source_video_edit_supported_for_fire_request() -> None:
    assert telegram_video_effects.source_video_edit_supported(
        "Make the ring look like real flames and one shirt briefly catch fire."
    )


def test_source_video_edit_supported_for_on_fire_request() -> None:
    assert telegram_video_effects.source_video_edit_supported(
        "Can you make the ring on fire and keep it photorealistic?"
    )


def test_parse_source_video_edit_plan_supports_on_fire_request() -> None:
    plan = telegram_video_effects.parse_source_video_edit_plan("Make this ring on fire.")
    assert plan["fire_overlay"] is True


def test_source_video_edit_supported_rejects_plain_summary_request() -> None:
    assert not telegram_video_effects.source_video_edit_supported("Summarize this video for me.")


def test_parse_source_video_edit_plan_supports_combined_speed_and_audio_request() -> None:
    plan = telegram_video_effects.parse_source_video_edit_plan(
        "Make it faster and louder, but keep the same video."
    )
    assert plan["speed_factor"] > 1.0
    assert plan["audio_gain_db"] > 0.0


def test_supported_source_video_edit_summary_mentions_current_capabilities() -> None:
    summary = telegram_video_effects.supported_source_video_edit_summary()
    assert "flame" in summary
    assert "speed" in summary
    assert "audio" in summary


def test_extract_source_video_reference_packet_requires_url() -> None:
    try:
        telegram_video_effects.extract_source_video_reference_packet(video_url="")
    except RuntimeError as exc:
        assert str(exc) == "source_video_url_missing"
    else:
        raise AssertionError("expected source_video_url_missing")


def test_source_video_url_rejects_localhost(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EA_TELEGRAM_VIDEO_DOWNLOAD_ALLOWED_HOSTS", "localhost")
    monkeypatch.setattr(
        telegram_video_effects.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))],
    )

    with pytest.raises(RuntimeError, match="source_video_url_host_not_public"):
        telegram_video_effects._validate_video_source_url("https://localhost/file.mp4")


def test_source_video_url_rejects_untrusted_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EA_TELEGRAM_VIDEO_DOWNLOAD_ALLOWED_HOSTS", raising=False)

    with pytest.raises(RuntimeError, match="source_video_url_host_forbidden"):
        telegram_video_effects._validate_video_source_url("https://example.com/file.mp4")


def test_download_video_streams_with_byte_cap_and_magic_check(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("EA_TELEGRAM_VIDEO_DOWNLOAD_ALLOWED_HOSTS", "api.telegram.org")
    monkeypatch.setenv("EA_TELEGRAM_VIDEO_DOWNLOAD_MAX_BYTES", "1048576")
    monkeypatch.setattr(
        telegram_video_effects.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("149.154.167.220", 443))],
    )

    class _Headers:
        def get(self, name, default=None):  # noqa: ANN001
            return "video/mp4" if name.lower() == "content-type" else default

    class _Response:
        headers = _Headers()

        def __init__(self):
            self._stream = io.BytesIO(b"\x00\x00\x00\x18ftypmp42" + b"0" * 128)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, size=-1):  # noqa: ANN001
            return self._stream.read(size)

    class _Opener:
        def open(self, request, timeout=0):  # noqa: ANN001
            return _Response()

    monkeypatch.setattr(telegram_video_effects.urllib.request, "build_opener", lambda *args, **kwargs: _Opener())

    target = tmp_path / "video.mp4"
    result = telegram_video_effects._download_video("https://api.telegram.org/file/bot/video/file.mp4", target)

    assert result == target
    assert target.read_bytes().startswith(b"\x00\x00\x00\x18ftyp")


def test_download_video_rejects_oversized_payload(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("EA_TELEGRAM_VIDEO_DOWNLOAD_ALLOWED_HOSTS", "api.telegram.org")
    monkeypatch.setenv("EA_TELEGRAM_VIDEO_DOWNLOAD_MAX_BYTES", "1048576")
    monkeypatch.setattr(
        telegram_video_effects.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("149.154.167.220", 443))],
    )

    class _Headers:
        def get(self, name, default=None):  # noqa: ANN001
            return "video/mp4" if name.lower() == "content-type" else default

    class _Response:
        headers = _Headers()

        def __init__(self):
            self._sent = 0

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, size=-1):  # noqa: ANN001
            if self._sent > 2:
                return b""
            self._sent += 1
            return b"x" * 700_000

    class _Opener:
        def open(self, request, timeout=0):  # noqa: ANN001
            return _Response()

    monkeypatch.setattr(telegram_video_effects.urllib.request, "build_opener", lambda *args, **kwargs: _Opener())

    with pytest.raises(RuntimeError, match="source_video_download_too_large"):
        telegram_video_effects._download_video("https://api.telegram.org/file/bot/video/file.mp4", tmp_path / "video.mp4")
