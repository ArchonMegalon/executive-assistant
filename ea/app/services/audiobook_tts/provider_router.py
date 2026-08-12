"""Explicit, fail-closed routing for audiobook synthesis providers."""

from __future__ import annotations

from collections.abc import Iterable
import hashlib
import threading

from app.services.audiobook_tts.contracts import (
    AudiobookTtsProvider,
    ProviderName,
    ProviderRouteDecision,
    SpeechSynthesisRequest,
    SpeechSynthesisResult,
    validate_synthesis_authority,
)
from app.services.audiobook_tts.errors import (
    AudiobookProviderError,
    ProviderFailure,
)


class AudiobookProviderRouter:
    """Resolve only the provider already authorized by the voice binding.

    Phase 1 deliberately has no automatic fallback.  A missing, duplicated, or
    mismatched provider fails closed instead of silently changing a voice. The
    speaker-drift guard is explicitly process-local; durable cast authority is
    enforced by the signed cast snapshot validated by each provider.
    """

    def __init__(self, providers: Iterable[AudiobookTtsProvider]) -> None:
        registered: dict[ProviderName, AudiobookTtsProvider] = {}
        for provider in providers:
            if provider.name in registered:
                raise AudiobookProviderError(
                    ProviderFailure(
                        provider=str(provider.name),
                        code="duplicate_provider_registration",
                        retryable=False,
                        charge_state="not_charged",
                        public_reason="provider_configuration_invalid",
                    )
                )
            registered[provider.name] = provider
        self._providers = registered
        self._speaker_bindings: dict[
            tuple[str, str], tuple[ProviderName, str, str, str]
        ] = {}
        self._binding_lock = threading.Lock()

    def decide(self, request: SpeechSynthesisRequest) -> ProviderRouteDecision:
        provider_name = request.voice.provider
        if provider_name not in self._providers:
            raise AudiobookProviderError(
                ProviderFailure(
                    provider=str(provider_name),
                    code="provider_not_registered",
                    retryable=False,
                    charge_state="not_charged",
                    public_reason="authorized_provider_unavailable",
                )
            )
        provider = self._providers[provider_name]
        try:
            validate_synthesis_authority(request)
        except ValueError as exc:
            raise AudiobookProviderError(
                ProviderFailure(
                    provider=str(provider_name),
                    code=str(exc),
                    retryable=False,
                    charge_state="not_charged",
                    public_reason="synthesis_authority_invalid",
                )
            ) from None
        validate_route = getattr(provider, "validate_route", None)
        if callable(validate_route):
            validate_route(request)
        binding_key = (request.job_id, request.speaker_id)
        binding = (
            provider_name,
            request.voice.voice_id_sha256,
            request.model,
            request.cast_snapshot_sha256,
        )
        with self._binding_lock:
            existing = self._speaker_bindings.get(binding_key)
            if existing is not None and existing != binding:
                raise AudiobookProviderError(
                    ProviderFailure(
                        provider=str(provider_name),
                        code="process_local_speaker_voice_drift_blocked",
                        retryable=False,
                        charge_state="not_charged",
                        public_reason="process_local_cast_binding_changed",
                    )
                )
            self._speaker_bindings[binding_key] = binding
        reservation_id = hashlib.sha256(
            (
                "ea.audiobook.provider-budget-reservation.v1\x00"
                f"{provider_name}\x00{request.job_id}\x00{request.idempotency_key}"
            ).encode("utf-8")
        ).hexdigest()
        return ProviderRouteDecision(
            provider=provider_name,
            model=request.model,
            reason=(
                "explicit_expressive_voice_binding"
                if provider_name == "vocallab" and request.performance_direction
                else "explicit_voice_binding"
            ),
            fallback_allowed=False,
            voice_binding_sha256=request.voice.voice_id_sha256,
            budget_reservation_id=reservation_id,
        )

    def synthesize(self, request: SpeechSynthesisRequest) -> SpeechSynthesisResult:
        decision = self.decide(request)
        result = self._providers[decision.provider].synthesize(request)
        if result.provider != decision.provider:
            raise AudiobookProviderError(
                ProviderFailure(
                    provider=str(decision.provider),
                    code="provider_result_mismatch",
                    retryable=False,
                    charge_state="unknown",
                    public_reason="provider_contract_violation",
                )
            )
        return result
