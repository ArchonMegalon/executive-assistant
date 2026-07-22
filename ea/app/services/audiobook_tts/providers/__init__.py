"""Audiobook TTS provider implementations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from app.services.audiobook_tts.providers.unmixr import UnmixrProvider
    from app.services.audiobook_tts.providers.vocallab import (
        VocalLabConfig,
        VocalLabProvider,
        VocalLabProviderVerification,
    )


def __getattr__(name: str) -> Any:
    """Load concrete providers only when callers request them.

    This keeps the pure VocalLab schema module usable by offline operator
    scripts without importing ``requests`` or provider runtime state.
    """

    if name == "UnmixrProvider":
        from app.services.audiobook_tts.providers.unmixr import UnmixrProvider

        return UnmixrProvider
    if name in {
        "VocalLabConfig",
        "VocalLabProvider",
        "VocalLabProviderVerification",
    }:
        from app.services.audiobook_tts.providers import vocallab

        return getattr(vocallab, name)
    raise AttributeError(name)

__all__ = (
    "UnmixrProvider",
    "VocalLabConfig",
    "VocalLabProvider",
    "VocalLabProviderVerification",
)
