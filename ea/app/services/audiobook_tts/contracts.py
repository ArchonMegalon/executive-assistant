"""Immutable provider-neutral contracts for audiobook speech synthesis."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Literal, Protocol


AudioFormat = Literal["wav", "mp3", "flac", "ogg"]
ProviderName = Literal["unmixr", "vocallab", "piper_local"]


@dataclass(frozen=True, slots=True)
class ProviderVoiceRef:
    provider: ProviderName

    # Private provider identifier.  Public receipts use only the digest below.
    provider_voice_id: str = field(repr=False)

    voice_id_sha256: str
    safe_label: str
    language: str
    supported_languages: tuple[str, ...]
    rights_class: str
    rights_receipt_id: str
    consent_receipt_id: str = ""

    def public_projection(self) -> dict[str, object]:
        """Return the receipt-safe voice representation."""

        return {
            "provider": self.provider,
            "voice_id_sha256": self.voice_id_sha256,
            "language": self.language,
            "supported_languages": list(self.supported_languages),
            "rights_class": self.rights_class,
            "rights_receipt_sha256": _sha256_text(self.rights_receipt_id),
            "consent_receipt_present": bool(self.consent_receipt_id),
            "raw_voice_id_exposed": False,
        }


@dataclass(frozen=True, slots=True)
class SpeechSynthesisRequest:
    job_id: str
    chapter_id: str
    segment_id: str

    source_text: str = field(repr=False)
    source_text_sha256: str

    language: str
    speaker_id: str
    speaker_role: str
    voice: ProviderVoiceRef

    model: str
    speed: float
    temperature: float
    output_format: AudioFormat
    sample_rate: int

    # Controlled EA direction, never provider-inferred manuscript meaning.
    performance_direction: str

    external_processing_authorization_id: str = field(repr=False)
    idempotency_key: str = field(repr=False)

    # These defaults preserve the Phase-1 call surface while allowing provider
    # policy to distinguish an explicit audiobook request from automatic,
    # preview, or sensitive persona work.  They are authority inputs, not provider
    # inferences.
    workload: Literal["audiobook", "voice_audition", "sensitive_persona"] = "audiobook"
    provider_selection: Literal["explicit", "automatic", "fallback"] = "explicit"
    publication_intent: bool = True
    cast_snapshot_sha256: str = ""
    external_processing_authorization_sha256: str = ""
    audition_authorization_id: str = field(default="", repr=False)
    audition_authorization_sha256: str = ""
    provider_contract_version: str = ""


@dataclass(frozen=True, slots=True)
class SpeechSynthesisResult:
    provider: ProviderName
    model: str
    content_type: str
    audio_bytes: bytes = field(repr=False)
    audio_sha256: str

    # The raw generation identifier is private; receipts use its digest only.
    provider_generation_id_private: str = field(repr=False)
    provider_generation_id_sha256: str

    points_estimated: int
    points_used: int
    retry_count: int
    provider_contract_version: str

    def public_projection(self) -> dict[str, object]:
        """Return bounded metadata without audio or private provider IDs."""

        return {
            "provider": self.provider,
            "model": self.model,
            "content_type": self.content_type,
            "audio_sha256": self.audio_sha256,
            "provider_generation_id_sha256": self.provider_generation_id_sha256,
            "points_estimated": self.points_estimated,
            "points_used": self.points_used,
            "retry_count": self.retry_count,
            "provider_contract_version": self.provider_contract_version,
            "audio_bytes_exposed": False,
            "provider_generation_id_exposed": False,
        }

    def segment_receipt(
        self,
        request: SpeechSynthesisRequest,
    ) -> dict[str, object]:
        """Build the provider-neutral, public-safe segment receipt."""

        return {
            "contract_name": "ea.audiobook_tts_segment.v2",
            "job_id_sha256": _sha256_text(request.job_id),
            "chapter_id_sha256": _sha256_text(request.chapter_id),
            "segment_id_sha256": _sha256_text(request.segment_id),
            "provider": self.provider,
            "model": self.model,
            "voice_id_sha256": request.voice.voice_id_sha256,
            "source_text_sha256": request.source_text_sha256,
            "provider_input_sha256": synthesis_fingerprint(request),
            "performance_direction_sha256": _sha256_text(
                request.performance_direction
            ),
            "output_sha256": self.audio_sha256,
            "content_type": self.content_type,
            "sample_rate": request.sample_rate,
            "points_estimated": self.points_estimated,
            "points_used": self.points_used,
            "retry_count": self.retry_count,
            "rights_receipt_sha256": _sha256_text(
                request.voice.rights_receipt_id
            ),
            "consent_receipt_sha256": (
                _sha256_text(request.voice.consent_receipt_id)
                if request.voice.consent_receipt_id
                else ""
            ),
            "raw_text_exposed": False,
            "raw_voice_id_exposed": False,
            "provider_secret_exposed": False,
            "provider_generation_id_exposed": False,
            "provider_url_exposed": False,
        }


@dataclass(frozen=True, slots=True)
class ProviderRouteDecision:
    provider: ProviderName
    model: str
    reason: str
    fallback_allowed: bool
    voice_binding_sha256: str
    budget_reservation_id: str

    def public_projection(self) -> dict[str, object]:
        return {
            "contract_name": "ea.audiobook_tts_route_decision.v1",
            "provider": self.provider,
            "model": self.model,
            "reason": self.reason,
            "fallback_allowed": self.fallback_allowed,
            "voice_binding_sha256": self.voice_binding_sha256,
            "budget_reservation_sha256": _sha256_text(
                self.budget_reservation_id
            ),
            "raw_voice_id_exposed": False,
        }


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _valid_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def synthesis_fingerprint(request: SpeechSynthesisRequest) -> str:
    """Return a canonical cache identity without serializing private values."""

    if request.voice.provider == "vocallab":
        route_authority = (
            request.audition_authorization_sha256
            if request.workload == "voice_audition"
            else request.cast_snapshot_sha256
        )
        if (
            not _valid_sha256(request.source_text_sha256)
            or not _valid_sha256(request.voice.voice_id_sha256)
            or not _valid_sha256(
                request.external_processing_authorization_sha256
            )
            or not _valid_sha256(route_authority)
            or not request.external_processing_authorization_id
            or not request.provider_contract_version
        ):
            raise ValueError("synthesis_authority_binding_invalid")

    payload = {
        "contract_name": "ea.audiobook_tts_segment_identity.v2",
        "provider": request.voice.provider,
        "model": request.model,
        "voice_id_sha256": request.voice.voice_id_sha256,
        "source_text_sha256": request.source_text_sha256,
        "language": request.language,
        "performance_direction_sha256": _sha256_text(
            request.performance_direction
        ),
        "speed": request.speed,
        "temperature": request.temperature,
        "format": request.output_format,
        "sample_rate": request.sample_rate,
        "rights_receipt_sha256": _sha256_text(request.voice.rights_receipt_id),
        "consent_receipt_sha256": (
            _sha256_text(request.voice.consent_receipt_id)
            if request.voice.consent_receipt_id
            else ""
        ),
        "cast_snapshot_sha256": request.cast_snapshot_sha256,
        "external_processing_authorization_sha256": _sha256_text(
            request.external_processing_authorization_id
        ),
        "external_processing_authority_artifact_sha256": (
            request.external_processing_authorization_sha256
        ),
        "provider_contract_version": request.provider_contract_version,
        "audition_authorization_sha256": request.audition_authorization_sha256,
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class AudiobookTtsProvider(Protocol):
    """Structural interface implemented by every audiobook TTS provider."""

    name: ProviderName

    def verify_capability(self) -> dict[str, object]: ...

    def list_voices(self) -> tuple[dict[str, object], ...]: ...

    def estimate_points(self, request: SpeechSynthesisRequest) -> int: ...

    def synthesize(self, request: SpeechSynthesisRequest) -> SpeechSynthesisResult: ...
