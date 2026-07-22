"""Provider-neutral audiobook text-to-speech boundary.

Provider implementations synthesize authorized narration segments.  Source,
speaker, casting, quality, publication, and delivery authority remain with the
existing audiobook pipeline.
"""

from app.services.audiobook_tts.contracts import (
    AudioFormat,
    AudiobookTtsProvider,
    ProviderName,
    ProviderRouteDecision,
    ProviderVoiceRef,
    SpeechSynthesisRequest,
    SpeechSynthesisResult,
    synthesis_fingerprint,
)
from app.services.audiobook_tts.errors import (
    AudiobookProviderError,
    ProviderFailure,
)
from app.services.audiobook_tts.provider_router import AudiobookProviderRouter

__all__ = (
    "AudioFormat",
    "AudiobookProviderError",
    "AudiobookProviderRouter",
    "AudiobookTtsProvider",
    "ProviderFailure",
    "ProviderName",
    "ProviderRouteDecision",
    "ProviderVoiceRef",
    "SpeechSynthesisRequest",
    "SpeechSynthesisResult",
    "synthesis_fingerprint",
)
