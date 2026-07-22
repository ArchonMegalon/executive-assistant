from __future__ import annotations

from dataclasses import FrozenInstanceError
import hashlib

import pytest

from app.services import audiobook_epub_pipeline
from app.services.audiobook_tts import (
    AudiobookProviderError,
    AudiobookProviderRouter,
    ProviderVoiceRef,
    SpeechSynthesisRequest,
)
from app.services.audiobook_tts.providers import UnmixrProvider


def _request(
    *,
    provider: str = "unmixr",
    source_text: str = "Synthetic audiobook provider boundary test.",
    voice_id: str = "private-unmixr-voice-id",
) -> SpeechSynthesisRequest:
    source_sha256 = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
    voice_sha256 = hashlib.sha256(voice_id.encode("utf-8")).hexdigest()
    return SpeechSynthesisRequest(
        job_id="job-1",
        chapter_id="chapter-1",
        segment_id="segment-1",
        source_text=source_text,
        source_text_sha256=source_sha256,
        language="de-DE",
        speaker_id="speaker-1",
        speaker_role="narrator",
        voice=ProviderVoiceRef(
            provider=provider,  # type: ignore[arg-type]
            provider_voice_id=voice_id,
            voice_id_sha256=voice_sha256,
            safe_label="Approved narrator",
            language="de-DE",
            supported_languages=("de-DE",),
            rights_class="professional",
            rights_receipt_id="rights-1",
        ),
        model="short-tts",
        speed=1.0,
        temperature=0.0,
        output_format="mp3",
        sample_rate=44100,
        performance_direction="",
        external_processing_authorization_id="authorization-1",
        idempotency_key="idempotency-1",
    )


def test_provider_contracts_are_immutable_and_public_projections_are_redacted() -> None:
    request = _request()

    with pytest.raises(FrozenInstanceError):
        request.voice.provider_voice_id = "replacement"  # type: ignore[misc]

    public_voice = request.voice.public_projection()
    assert "provider_voice_id" not in public_voice
    assert "safe_label" not in public_voice
    assert public_voice["raw_voice_id_exposed"] is False


def test_unmixr_provider_forwards_existing_short_tts_arguments_without_network() -> None:
    calls: list[dict[str, object]] = []

    def synthesize_request(**kwargs: object) -> tuple[bytes, str]:
        calls.append(dict(kwargs))
        return b"stable-audio", "audio/wav"

    provider = UnmixrProvider(
        synthesize_request=synthesize_request,
        speaking_rate="medium",
        speaking_pitch="low",
        speaking_volume="high",
        pronunciation_dict={"Chummer": "Tschammer"},
    )
    result = AudiobookProviderRouter((provider,)).synthesize(_request())

    assert calls == [
        {
            "text": "Synthetic audiobook provider boundary test.",
            "voice_id": "private-unmixr-voice-id",
            "lang": "de-DE",
            "speaking_rate": "medium",
            "speaking_pitch": "low",
            "speaking_volume": "high",
            "pronunciation_dict": {"Chummer": "Tschammer"},
        }
    ]
    assert result.audio_bytes == b"stable-audio"
    assert result.content_type == "audio/wav"
    assert result.audio_sha256 == hashlib.sha256(b"stable-audio").hexdigest()
    assert result.provider == "unmixr"
    public_result = result.public_projection()
    assert "audio_bytes" not in public_result
    assert "provider_generation_id_private" not in public_result
    assert public_result["audio_bytes_exposed"] is False


def test_unmixr_provider_maps_raw_failure_to_sanitized_neutral_error() -> None:
    source_text = "PRIVATE MANUSCRIPT SENTENCE"
    upstream_body = f"provider response contained {source_text} and Bearer private-token"

    def synthesize_request(**_: object) -> tuple[bytes, str]:
        raise RuntimeError(upstream_body)

    provider = UnmixrProvider(synthesize_request=synthesize_request)

    with pytest.raises(AudiobookProviderError) as caught:
        provider.synthesize(_request(source_text=source_text))

    rendered_error = f"{caught.value!s} {caught.value!r}"
    assert caught.value.failure.provider == "unmixr"
    assert caught.value.failure.code == "provider_failed"
    assert source_text not in rendered_error
    assert "private-token" not in rendered_error
    assert caught.value.__cause__ is None


@pytest.mark.parametrize("status", [True, "401", 99, 600, object()])
def test_unmixr_status_classifier_never_coerces_untrusted_values(status: object) -> None:
    upstream_failure = RuntimeError("PRIVATE BODY")
    upstream_failure.status_code = status  # type: ignore[attr-defined]
    upstream_failure.detail = "PRIVATE BODY"  # type: ignore[attr-defined]

    provider = UnmixrProvider(
        synthesize_request=lambda **_: (_ for _ in ()).throw(upstream_failure)
    )
    with pytest.raises(AudiobookProviderError) as caught:
        provider.synthesize(_request())
    assert caught.value.failure.code == "provider_failed"
    assert caught.value.failure.charge_state == "unknown"
    assert "PRIVATE" not in f"{caught.value!s} {caught.value!r}"
    assert caught.value.__cause__ is None


def test_unmixr_classifier_survives_hostile_attributes_and_stringification() -> None:
    class Unprintable:
        def __str__(self) -> str:
            raise RuntimeError("PRIVATE STRING BODY")

    class HostileFailure(RuntimeError):
        @property
        def status_code(self) -> object:
            raise RuntimeError("PRIVATE STATUS BODY")

        @property
        def detail(self) -> object:
            return Unprintable()

    provider = UnmixrProvider(
        synthesize_request=lambda **_: (_ for _ in ()).throw(HostileFailure())
    )
    with pytest.raises(AudiobookProviderError) as caught:
        provider.synthesize(_request())
    assert caught.value.failure.code == "provider_failed"
    assert caught.value.failure.public_reason == "provider_failed"
    assert "PRIVATE" not in f"{caught.value!s} {caught.value!r}"
    assert caught.value.__cause__ is None


def test_router_fails_closed_without_cross_provider_fallback() -> None:
    provider = UnmixrProvider(synthesize_request=lambda **_: (b"audio", "audio/wav"))

    with pytest.raises(AudiobookProviderError) as caught:
        AudiobookProviderRouter((provider,)).synthesize(_request(provider="vocallab"))

    assert caught.value.failure.code == "provider_not_registered"
    assert caught.value.failure.retryable is False
    assert caught.value.failure.charge_state == "not_charged"


def test_epub_compatibility_seam_routes_through_adapter_with_output_parity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def synthesize_request(**kwargs: object) -> tuple[bytes, str]:
        calls.append(dict(kwargs))
        return b"existing-epub-audio", "audio/mpeg"

    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_RETRY_COUNT", "1")
    monkeypatch.setenv("EA_AUDIOBOOK_UNMIXR_RETRY_BACKOFF_SECONDS", "0")
    monkeypatch.setattr(
        audiobook_epub_pipeline,
        "unmixr_synthesize_request",
        synthesize_request,
    )
    monkeypatch.setattr(
        audiobook_epub_pipeline,
        "unmixr_pronunciation_dict",
        lambda: {"Chummer": "Tschammer"},
    )

    result = audiobook_epub_pipeline._synthesize_unmixr_with_retries(
        text="Existing audiobook segment.",
        voice_id="existing-voice",
        lang="en-US",
        speaking_rate="medium",
        speaking_pitch="low",
        speaking_volume="high",
    )

    assert result == (b"existing-epub-audio", "audio/mpeg", [])
    assert calls == [
        {
            "text": "Existing audiobook segment.",
            "voice_id": "existing-voice",
            "lang": "en-US",
            "speaking_rate": "medium",
            "speaking_pitch": "low",
            "speaking_volume": "high",
            "pronunciation_dict": {"Chummer": "Tschammer"},
        }
    ]
