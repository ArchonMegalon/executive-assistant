from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class MemorialSpeechTranscription:
    transcript_text: str
    transcript_effective_text: str
    transcript_original_text: str
    transcription_status: str
    transcriber: str
    extra: dict[str, Any] = field(default_factory=dict)

    def as_public_payload(self) -> dict[str, Any]:
        payload = dict(self.extra)
        payload["transcript_text"] = self.transcript_text
        payload["transcript_effective_text"] = self.transcript_effective_text
        payload["transcript_original_text"] = self.transcript_original_text
        payload["transcription_status"] = self.transcription_status
        payload["transcriber"] = self.transcriber
        return payload


@dataclass(frozen=True)
class MemorialTurnRequest:
    slug: str
    audio_payload: bytes
    content_type: str
    prefer_fast_tts: bool = False
    personal_memory_context: dict[str, object] = field(default_factory=dict)
    voice_ab_variant: str = ""
    difficult_memory_mode: bool = False


@dataclass(frozen=True)
class MemorialAnswerPlan:
    answer_payload: dict[str, Any]
    selected_model: str
    llm_ms: float
    direct_contact_opening: bool


@dataclass(frozen=True)
class MemorialRenderedAudio:
    payload: bytes
    content_type: str
    answer_audio_text: str
    tts_plugin: str
    tts_fast_path: bool
    tts_ms: float
    pad_ms: float


@dataclass(frozen=True)
class MemorialTurnResult:
    response_payload: dict[str, Any]

    def as_public_payload(self) -> dict[str, Any]:
        return dict(self.response_payload)
