from __future__ import annotations

from collections.abc import Callable

import pytest

from app.services.audiobook_tts.providers.vocallab_schema import (
    VocalLabSchemaError,
    parse_voices,
)


def _clone_voice() -> dict[str, object]:
    return {
        "created_at": "2026-08-14T10:00:00Z",
        "id": "private-clone-id",
        "languages": ["English", "German"],
        "name": "Private narration voice",
        "type": "clone",
    }


def _payload(voice: dict[str, object]) -> dict[str, object]:
    return {
        "count": 1,
        "has_more": False,
        "offset": 0,
        "total": 1,
        "voices": [voice],
    }


def test_parse_voices_accepts_current_exact_clone_shape() -> None:
    observations = parse_voices(_payload(_clone_voice()))

    assert len(observations) == 1
    assert observations[0].provider_voice_id == "private-clone-id"
    assert observations[0].provider_type == "clone"
    assert observations[0].languages == ("English", "German")


@pytest.mark.parametrize(
    "mutation",
    [
        lambda voice: voice.pop("created_at"),
        lambda voice: voice.update(created_at=""),
        lambda voice: voice.update(slug="unexpected"),
        lambda voice: voice.update(type="preset"),
    ],
)
def test_parse_voices_rejects_inexact_clone_shapes(
    mutation: Callable[[dict[str, object]], object],
) -> None:
    voice = _clone_voice()
    mutation(voice)

    with pytest.raises(VocalLabSchemaError, match="invalid_provider_response"):
        parse_voices(_payload(voice))
