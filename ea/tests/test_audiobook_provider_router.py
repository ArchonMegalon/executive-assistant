from __future__ import annotations

from dataclasses import replace
import hashlib

import pytest

from app.services.audiobook_tts import (
    AudiobookProviderError,
    AudiobookProviderRouter,
    ProviderFailure,
    ProviderVoiceRef,
    SpeechSynthesisRequest,
)
from app.services.audiobook_tts.providers import UnmixrProvider


def _request(
    *,
    provider: str = "unmixr",
    voice_id: str = "voice-1",
    model: str = "short-tts",
    performance_direction: str = "",
    provider_selection: str = "explicit",
) -> SpeechSynthesisRequest:
    text = "Synthetic route test."
    return SpeechSynthesisRequest(
        job_id="job-1",
        chapter_id="chapter-1",
        segment_id="segment-1",
        source_text=text,
        source_text_sha256=hashlib.sha256(text.encode()).hexdigest(),
        language="en-US",
        speaker_id="speaker-1",
        speaker_role="narrator",
        voice=ProviderVoiceRef(
            provider=provider,  # type: ignore[arg-type]
            provider_voice_id=voice_id,
            voice_id_sha256=hashlib.sha256(voice_id.encode()).hexdigest(),
            safe_label="Approved voice",
            language="en-US",
            supported_languages=("en-US",),
            rights_class="professional",
            rights_receipt_id="rights-1",
        ),
        model=model,
        speed=1.0,
        temperature=1.0,
        output_format="wav",
        sample_rate=44100,
        performance_direction=performance_direction,
        external_processing_authorization_id="authorization-1",
        idempotency_key="idempotency-1",
        provider_selection=provider_selection,  # type: ignore[arg-type]
        cast_snapshot_sha256="c" * 64,
    )


def test_unmixr_remains_explicit_default_and_route_receipt_is_redacted() -> None:
    provider = UnmixrProvider(synthesize_request=lambda **_: (b"audio", "audio/wav"))
    decision = AudiobookProviderRouter((provider,)).decide(_request())
    assert decision.provider == "unmixr"
    assert decision.reason == "explicit_voice_binding"
    assert decision.fallback_allowed is False
    projection = decision.public_projection()
    assert projection["contract_name"] == "ea.audiobook_tts_route_decision.v1"
    assert len(str(projection["budget_reservation_sha256"])) == 64
    assert projection["budget_reservation_sha256"] == hashlib.sha256(
        decision.budget_reservation_id.encode("utf-8")
    ).hexdigest()
    assert decision.budget_reservation_id not in str(projection)
    assert "voice-1" not in str(projection)


def test_router_never_falls_back_to_registered_provider() -> None:
    unmixr = UnmixrProvider(synthesize_request=lambda **_: (b"audio", "audio/wav"))
    with pytest.raises(AudiobookProviderError) as caught:
        AudiobookProviderRouter((unmixr,)).decide(_request(provider="vocallab", model="v-pro"))
    assert caught.value.failure.code == "provider_not_registered"
    assert caught.value.failure.charge_state == "not_charged"


def test_router_blocks_mid_speaker_voice_provider_model_and_cast_drift() -> None:
    first = _request()
    router = AudiobookProviderRouter(
        (UnmixrProvider(synthesize_request=lambda **_: (b"audio", "audio/wav")),)
    )
    router.decide(first)
    variants = (
        replace(
            first,
            voice=replace(
                first.voice,
                provider_voice_id="voice-2",
                voice_id_sha256=hashlib.sha256(b"voice-2").hexdigest(),
            ),
        ),
        replace(first, model="changed-model"),
        replace(first, cast_snapshot_sha256="d" * 64),
    )
    for changed in variants:
        with pytest.raises(AudiobookProviderError) as caught:
            router.decide(changed)
        assert caught.value.failure.code == "process_local_speaker_voice_drift_blocked"


def test_router_rejects_duplicate_provider_registration() -> None:
    provider = UnmixrProvider(synthesize_request=lambda **_: (b"audio", "audio/wav"))
    with pytest.raises(AudiobookProviderError) as caught:
        AudiobookProviderRouter((provider, provider))
    assert caught.value.failure.code == "duplicate_provider_registration"


class _VocalLabStub:
    name = "vocallab"

    def validate_route(self, request: SpeechSynthesisRequest) -> None:
        if request.provider_selection != "explicit":
            raise AudiobookProviderError(
                ProviderFailure(
                    provider="vocallab",
                    code="cross_provider_fallback_disabled",
                    retryable=False,
                    charge_state="not_charged",
                )
            )

    def verify_capability(self) -> dict[str, object]:
        return {}

    def list_voices(self) -> tuple[dict[str, object], ...]:
        return ()

    def estimate_points(self, request: SpeechSynthesisRequest) -> int:
        return 1

    def synthesize(self, request: SpeechSynthesisRequest):  # type: ignore[no-untyped-def]
        raise AssertionError("not called")


def test_explicit_vocallab_expressive_decision_is_receipt_bearing() -> None:
    decision = AudiobookProviderRouter((_VocalLabStub(),)).decide(
        _request(
            provider="vocallab",
            model="v-studio",
            performance_direction="warm",
        )
    )
    assert decision.provider == "vocallab"
    assert decision.model == "v-studio"
    assert decision.reason == "explicit_expressive_voice_binding"
    assert decision.fallback_allowed is False


def test_fallback_selection_remains_denied_even_when_provider_is_registered() -> None:
    with pytest.raises(AudiobookProviderError) as caught:
        AudiobookProviderRouter((_VocalLabStub(),)).decide(
            _request(
                provider="vocallab",
                model="v-pro",
                provider_selection="fallback",
            )
        )
    assert caught.value.failure.code == "cross_provider_fallback_disabled"
