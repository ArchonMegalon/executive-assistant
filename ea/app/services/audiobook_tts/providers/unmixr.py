"""Compatibility adapter over the established Unmixr short-TTS path."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import hashlib
import re
from typing import Any

from app.services.audiobook_tts.contracts import (
    ProviderName,
    SpeechSynthesisRequest,
    SpeechSynthesisResult,
)
from app.services.audiobook_tts.errors import (
    AudiobookProviderError,
    ProviderFailure,
)
from app.services.audiobook_tts.providers.base import BaseAudiobookTtsProvider


UNMIXR_PROVIDER_CONTRACT_VERSION = "ea.audiobook_tts.unmixr.v1"
_RETRY_AFTER_RE = re.compile(
    r"(?:retry_after_|available[^0-9]{0,40})(\d{1,7})",
    re.IGNORECASE,
)

UnmixrSynthesizeCallable = Callable[..., tuple[bytes, str]]


def _default_unmixr_synthesize_request(**kwargs: Any) -> tuple[bytes, str]:
    # Keep the established implementation as the compatibility owner.  The
    # import is lazy so tests and callers may inject a seam without importing
    # memorial runtime configuration while constructing the adapter.
    from app.services.memorial_openvoice import unmixr_synthesize_request

    return unmixr_synthesize_request(**kwargs)


def _exception_detail(exc: BaseException) -> str:
    try:
        detail = getattr(exc, "detail", "")
    except Exception:
        return ""
    candidate = detail if detail not in (None, "") else exc
    try:
        return str(candidate)[:4096].strip().lower()
    except Exception:
        return ""


def _exception_status_code(exc: BaseException) -> int:
    try:
        value = getattr(exc, "status_code", 0)
    except Exception:
        return 0
    if type(value) is int and 100 <= value <= 599:
        return value
    return 0


def _bounded_retry_after(detail: str) -> int:
    match = _RETRY_AFTER_RE.search(detail)
    if not match:
        return 0
    return min(max(int(match.group(1)), 0), 604800)


def _provider_failure_from_exception(exc: BaseException) -> ProviderFailure:
    """Classify an upstream error without retaining its raw message."""

    try:
        detail = _exception_detail(exc)
        status_code = _exception_status_code(exc)
        retry_after = _bounded_retry_after(detail)

        code = "provider_failed"
        retryable = False
        charge_state = "unknown"
        if status_code == 401 or any(
            marker in detail
            for marker in ("api_key_missing", "authentication_failed", "unauthorized")
        ):
            code = "authentication_failed"
            charge_state = "not_charged"
        elif status_code == 403 or any(
            marker in detail for marker in ("access_denied", "forbidden")
        ):
            code = "plan_or_api_access_denied"
            charge_state = "not_charged"
        elif any(
            marker in detail
            for marker in (
                "balance_exhausted",
                "insufficient balance",
                "insufficient api balance",
            )
        ):
            code = "balance_exhausted"
            charge_state = "not_charged"
        elif status_code in {400, 413, 422} or any(
            marker in detail
            for marker in (
                "input_too_long",
                "input too long",
                "limit your input",
                "invalid_request",
            )
        ):
            code = "invalid_request"
            charge_state = "not_charged"
        elif status_code == 429 or any(
            marker in detail
            for marker in ("rate_limited", "rate limit", "too many requests")
        ):
            code = "rate_limited"
            retryable = True
            charge_state = "not_charged"
        elif status_code in {500, 502, 503, 504} or any(
            marker in detail
            for marker in (
                "upstream_unavailable",
                "upstream_unreachable",
                "audio_fetch_failed",
                "no_audio_url",
                "temporar",
                "timeout",
            )
        ):
            code = "upstream_unavailable"
            retryable = True

        return ProviderFailure(
            provider="unmixr",
            code=code,
            retryable=retryable,
            charge_state=charge_state,
            retry_after_seconds=retry_after,
            public_reason=code,
        )
    except Exception:
        return ProviderFailure(
            provider="unmixr",
            code="provider_failed",
            retryable=False,
            charge_state="unknown",
            public_reason="provider_failed",
        )


class UnmixrProvider(BaseAudiobookTtsProvider):
    """Adapt the existing Unmixr implementation to the neutral contract.

    ``legacy_error_compatibility`` is used only by the existing EPUB helper so
    its established retry classification, outward exception type, and test
    monkeypatch surface remain byte-for-byte compatible during Phase 1.
    New callers receive sanitized ``AudiobookProviderError`` instances.
    """

    name: ProviderName = "unmixr"

    def __init__(
        self,
        *,
        synthesize_request: UnmixrSynthesizeCallable | None = None,
        speaking_rate: str | None = None,
        speaking_pitch: str | None = None,
        speaking_volume: str | None = None,
        pronunciation_dict: Mapping[str, str] | None = None,
        legacy_error_compatibility: bool = False,
    ) -> None:
        self._synthesize_request = synthesize_request or _default_unmixr_synthesize_request
        self._speaking_rate = speaking_rate
        self._speaking_pitch = speaking_pitch
        self._speaking_volume = speaking_volume
        self._pronunciation_dict = dict(pronunciation_dict or {})
        self._legacy_error_compatibility = legacy_error_compatibility

    def verify_capability(self) -> dict[str, object]:
        # Capability verification stays an explicit live-ops action.  Merely
        # importing or constructing this adapter must never make a network call.
        return {
            "provider": self.name,
            "status": "not_probed",
            "provider_contract_version": UNMIXR_PROVIDER_CONTRACT_VERSION,
        }

    def list_voices(self) -> tuple[dict[str, object], ...]:
        # The current voice catalogue remains owned by the existing audiobook
        # selection path until a later, separately reviewed catalogue migration.
        return ()

    def estimate_points(self, request: SpeechSynthesisRequest) -> int:
        del request
        return 0

    def synthesize(self, request: SpeechSynthesisRequest) -> SpeechSynthesisResult:
        if request.voice.provider != self.name:
            raise AudiobookProviderError(
                ProviderFailure(
                    provider=self.name,
                    code="voice_provider_mismatch",
                    retryable=False,
                    charge_state="not_charged",
                    public_reason="voice_provider_mismatch",
                )
            )

        try:
            audio_bytes, content_type = self._synthesize_request(
                text=request.source_text,
                voice_id=request.voice.provider_voice_id,
                lang=request.language,
                speaking_rate=self._speaking_rate,
                speaking_pitch=self._speaking_pitch,
                speaking_volume=self._speaking_volume,
                pronunciation_dict=dict(self._pronunciation_dict),
            )
        except Exception as exc:
            if self._legacy_error_compatibility:
                raise
            # Do not chain the raw exception: a standard traceback must not
            # disclose an upstream body, source text, URL, or account detail.
            raise AudiobookProviderError(_provider_failure_from_exception(exc)) from None

        return SpeechSynthesisResult(
            provider=self.name,
            model=request.model,
            content_type=content_type,
            audio_bytes=audio_bytes,
            audio_sha256=hashlib.sha256(audio_bytes).hexdigest(),
            provider_generation_id_private="",
            provider_generation_id_sha256="",
            points_estimated=0,
            points_used=0,
            retry_count=0,
            provider_contract_version=UNMIXR_PROVIDER_CONTRACT_VERSION,
        )
