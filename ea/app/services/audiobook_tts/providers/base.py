"""Abstract base for concrete audiobook TTS providers."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.services.audiobook_tts.contracts import (
    ProviderName,
    SpeechSynthesisRequest,
    SpeechSynthesisResult,
)


class BaseAudiobookTtsProvider(ABC):
    name: ProviderName

    @abstractmethod
    def verify_capability(self) -> dict[str, object]:
        """Return bounded capability posture without performing hidden work."""

    @abstractmethod
    def list_voices(self) -> tuple[dict[str, object], ...]:
        """Return provider discovery rows; authorization is a separate gate."""

    @abstractmethod
    def estimate_points(self, request: SpeechSynthesisRequest) -> int:
        """Return provider-native estimated spend, or zero when unsupported."""

    @abstractmethod
    def synthesize(self, request: SpeechSynthesisRequest) -> SpeechSynthesisResult:
        """Synthesize exactly one already-authorized narration segment."""
