"""Sanitized errors shared by audiobook TTS providers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


ChargeState = Literal["not_charged", "charged", "unknown"]


@dataclass(frozen=True, slots=True)
class ProviderFailure:
    provider: str
    code: str
    retryable: bool
    charge_state: ChargeState
    retry_after_seconds: int = 0
    public_reason: str = ""


class AudiobookProviderError(RuntimeError):
    """Provider-neutral failure whose string form contains only a safe code."""

    def __init__(self, failure: ProviderFailure) -> None:
        super().__init__(failure.code)
        self.failure = failure

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(provider={self.failure.provider!r}, "
            f"code={self.failure.code!r}, retryable={self.failure.retryable!r}, "
            f"charge_state={self.failure.charge_state!r})"
        )
