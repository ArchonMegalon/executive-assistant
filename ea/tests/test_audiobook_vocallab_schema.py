from __future__ import annotations

import base64
from pathlib import Path
import subprocess
import sys

import pytest

from app.services.audiobook_tts.providers.vocallab_schema import (
    VOCALLAB_BILLING_UNIT,
    VocalLabSchemaError,
    parse_account,
    parse_generation,
    parse_models,
    parse_ping,
    parse_voices,
)


def _models() -> dict[str, object]:
    return {
        "default": "v-pro",
        "models": [
            {
                "costMultiplier": 1,
                "gated": True,
                "key": "v-studio",
                "label": "Studio",
                "steerable": True,
            },
            {
                "costMultiplier": 1,
                "gated": False,
                "key": "v-pro",
                "label": "Pro",
                "steerable": False,
            },
            {
                "costMultiplier": 0.5,
                "gated": False,
                "key": "v-lite",
                "label": "Lite",
                "steerable": False,
            },
        ],
    }


def test_exact_authenticated_get_contract_parses_without_exposing_points() -> None:
    ping = parse_ping(
        {
            "message": "Authenticated — your VocalLab API key is working.",
            "ok": True,
            "points": 24000,
            "unit": VOCALLAB_BILLING_UNIT,
        }
    )
    account = parse_account(
        {
            "is_pro": True,
            "is_studio": True,
            "points": 24000,
            "unit": VOCALLAB_BILLING_UNIT,
        }
    )
    models = parse_models(_models())
    assert tuple(model.key for model in models) == ("v-studio", "v-pro", "v-lite")
    assert parse_voices({"voices": []}) == ()
    assert "24000" not in repr(ping)
    assert "24000" not in repr(account)


@pytest.mark.parametrize(
    "payload",
    [
        {
            "message": "VocalLab API is ready",
            "ok": True,
            "points": 1,
            "unit": VOCALLAB_BILLING_UNIT,
        },
        {
            "message": "Authenticated — your VocalLab API key is working.",
            "ok": 1,
            "points": 1,
            "unit": VOCALLAB_BILLING_UNIT,
        },
        {
            "message": "Authenticated — your VocalLab API key is working.",
            "ok": True,
            "points": True,
            "unit": VOCALLAB_BILLING_UNIT,
        },
        {
            "message": "Authenticated — your VocalLab API key is working.",
            "ok": True,
            "points": 1,
            "unit": "points",
        },
    ],
)
def test_ping_rejects_semantic_drift_and_type_confusion(
    payload: dict[str, object],
) -> None:
    with pytest.raises(VocalLabSchemaError, match="invalid_provider_response"):
        parse_ping(payload)


def test_models_require_exact_order_gating_and_cost_semantics() -> None:
    for mutate in ("order", "gated", "extra"):
        payload = _models()
        rows = payload["models"]
        assert isinstance(rows, list)
        if mutate == "order":
            rows[0], rows[1] = rows[1], rows[0]
        elif mutate == "gated":
            rows[0]["gated"] = False
        else:
            rows[0]["provider_secret"] = "private"
        with pytest.raises(VocalLabSchemaError):
            parse_models(payload)


def test_voice_discovery_rejects_cross_entry_casefolded_raw_id_labels() -> None:
    payload = {
        "voices": [
            {
                "id": "Private-Voice-One",
                "name": "Approved One",
                "type": "professional",
                "languages": ["en"],
            },
            {
                "id": "private-voice-two",
                "name": "Reads like PRIVATE-VOICE-ONE",
                "type": "professional",
                "languages": ["en"],
            },
        ]
    }
    with pytest.raises(VocalLabSchemaError):
        parse_voices(payload)


def test_pending_inline_generation_accepts_null_url_without_poll_contract() -> None:
    encoded = base64.b64encode(b"synthetic-audio").decode()
    observation = parse_generation(
        {
            "id": "generation-1",
            "status": "pending",
            "model": "v-pro",
            "format": "WAV",
            "points_used": 3,
            "audio_base64": encoded,
            "audio_url": None,
        },
        expected_model="v-pro",
    )
    assert observation.status == "pending"
    assert observation.points_used == 3
    assert observation.audio_base64 == encoded
    assert observation.audio_url == ""
    assert "generation-1" not in repr(observation)
    assert encoded not in repr(observation)


@pytest.mark.parametrize(
    "payload",
    [
        {"id": "generation-1", "status": "ready", "model": "v-pro", "format": "WAV"},
        {
            "id": "generation-1",
            "status": "ready",
            "model": "v-pro",
            "format": "WAV",
            "points_used": True,
        },
        {
            "id": "generation-1",
            "status": "ready",
            "model": "v-pro",
            "format": "MP3",
            "points_used": 3,
        },
    ],
)
def test_generation_rejects_missing_points_type_confusion_and_format_drift(
    payload: dict[str, object],
) -> None:
    with pytest.raises(VocalLabSchemaError):
        parse_generation(payload, expected_model="v-pro")


def test_schema_only_import_does_not_eagerly_load_requests_runtime() -> None:
    source = (
        "import sys; "
        "import app.services.audiobook_tts.providers.vocallab_schema; "
        "assert 'requests' not in sys.modules"
    )
    subprocess.run(
        [sys.executable, "-c", source],
        check=True,
        cwd=Path(__file__).resolve().parents[1],
    )
