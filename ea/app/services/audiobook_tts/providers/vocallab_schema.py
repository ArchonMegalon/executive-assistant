"""Pure, exact parsers for the verified VocalLab HTTP JSON contract."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import math
import re
import unicodedata
from typing import Any, Mapping


VOCALLAB_BILLING_UNIT = (
    "points (billed by text length: ceil(chars/15) on the API; "
    "1 pt ≈ 1 second of audio)"
)
VOCALLAB_MODEL_KEYS = ("v-studio", "v-pro", "v-lite")
VOCALLAB_VERIFICATION_SYNTHETIC_TEXT = (
    "EA VocalLab provider verification. This is synthetic test content."
)
VOCALLAB_VERIFICATION_SYNTHETIC_TEXT_SHA256 = hashlib.sha256(
    VOCALLAB_VERIFICATION_SYNTHETIC_TEXT.encode("utf-8")
).hexdigest()
VOCALLAB_VERIFICATION_SYNTHETIC_POINTS = (
    len(VOCALLAB_VERIFICATION_SYNTHETIC_TEXT) + 14
) // 15
VOCALLAB_GENERATION_PENDING = frozenset({"queued", "pending", "processing"})
VOCALLAB_GENERATION_SUCCESS = frozenset(
    {"completed", "ready", "success", "succeeded"}
)
VOCALLAB_GENERATION_FAILED = frozenset({"failed", "error", "cancelled"})
_GENERATION_STATUSES = (
    VOCALLAB_GENERATION_PENDING
    | VOCALLAB_GENERATION_SUCCESS
    | VOCALLAB_GENERATION_FAILED
)
_PRIVATE_ID_RE = re.compile(r"^[^\s\x00-\x1f\x7f]{1,256}$")
_CATALOG_VOICE_KEYS = frozenset(
    {
        "accent",
        "category",
        "id",
        "language_code",
        "languages",
        "name",
        "slug",
        "type",
    }
)
_CLONE_VOICE_KEYS = frozenset(
    {"created_at", "id", "languages", "name", "type"}
)
_MODEL_SEMANTICS = (
    ("v-studio", True, True, 1.0),
    ("v-pro", False, False, 1.0),
    ("v-lite", False, False, 0.5),
)


class VocalLabSchemaError(RuntimeError):
    """Code-only parser failure that never retains an upstream value."""

    def __init__(self) -> None:
        super().__init__("invalid_provider_response")
        self.code = "invalid_provider_response"


def _valid_private_id(value: object) -> bool:
    return bool(
        isinstance(value, str)
        and _PRIVATE_ID_RE.fullmatch(value)
        and all(not unicodedata.category(character).startswith("C") for character in value)
    )


@dataclass(frozen=True, slots=True)
class PingObservation:
    message: str = field(repr=False)
    points: int = field(repr=False)


@dataclass(frozen=True, slots=True)
class AccountObservation:
    points: int = field(repr=False)


@dataclass(frozen=True, slots=True)
class ModelObservation:
    key: str
    label: str
    gated: bool
    steerable: bool
    cost_multiplier: float


@dataclass(frozen=True, slots=True)
class VoiceObservation:
    provider_voice_id: str = field(repr=False)
    name: str
    provider_type: str
    languages: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GenerationObservation:
    generation_id: str = field(repr=False)
    status: str
    model: str
    audio_format: str
    points_used: int | None
    audio_base64: str = field(default="", repr=False)
    audio_url: str = field(default="", repr=False)


def _mapping(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise VocalLabSchemaError()
    return value


def parse_ping(payload: object) -> PingObservation:
    try:
        value = _mapping(payload)
        if set(value) != {"message", "ok", "points", "unit"}:
            raise VocalLabSchemaError()
        message = value.get("message")
        points = value.get("points")
        if (
            message != "Authenticated — your VocalLab API key is working."
            or value.get("ok") is not True
            or type(points) is not int
            or points < 0
            or value.get("unit") != VOCALLAB_BILLING_UNIT
        ):
            raise VocalLabSchemaError()
        return PingObservation(message=message, points=points)
    except VocalLabSchemaError:
        raise
    except Exception:
        raise VocalLabSchemaError() from None


def parse_account(payload: object) -> AccountObservation:
    try:
        value = _mapping(payload)
        if set(value) != {"is_pro", "is_studio", "points", "unit"}:
            raise VocalLabSchemaError()
        points = value.get("points")
        if (
            value.get("is_pro") is not True
            or value.get("is_studio") is not True
            or type(points) is not int
            or points < 0
            or value.get("unit") != VOCALLAB_BILLING_UNIT
        ):
            raise VocalLabSchemaError()
        return AccountObservation(points=points)
    except VocalLabSchemaError:
        raise
    except Exception:
        raise VocalLabSchemaError() from None


def parse_models(payload: object) -> tuple[ModelObservation, ...]:
    try:
        value = _mapping(payload)
        if set(value) != {"default", "models"} or value.get("default") != "v-pro":
            raise VocalLabSchemaError()
        rows = value.get("models")
        if not isinstance(rows, list) or len(rows) != len(_MODEL_SEMANTICS):
            raise VocalLabSchemaError()
        observations: list[ModelObservation] = []
        for row, expected in zip(rows, _MODEL_SEMANTICS, strict=True):
            item = _mapping(row)
            if set(item) != {
                "costMultiplier",
                "gated",
                "key",
                "label",
                "steerable",
            }:
                raise VocalLabSchemaError()
            key, gated, steerable, multiplier = expected
            actual_multiplier = item.get("costMultiplier")
            label = item.get("label")
            if (
                item.get("key") != key
                or type(item.get("gated")) is not bool
                or item.get("gated") is not gated
                or type(item.get("steerable")) is not bool
                or item.get("steerable") is not steerable
                or type(actual_multiplier) not in {int, float}
                or not math.isfinite(float(actual_multiplier))
                or float(actual_multiplier) != multiplier
                or not isinstance(label, str)
                or not label.strip()
                or label != label.strip()
            ):
                raise VocalLabSchemaError()
            observations.append(
                ModelObservation(
                    key=key,
                    label=label,
                    gated=gated,
                    steerable=steerable,
                    cost_multiplier=multiplier,
                )
            )
        return tuple(observations)
    except VocalLabSchemaError:
        raise
    except Exception:
        raise VocalLabSchemaError() from None


def parse_voices(payload: object) -> tuple[VoiceObservation, ...]:
    try:
        value = _mapping(payload)
        if set(value) != {"count", "has_more", "offset", "total", "voices"}:
            raise VocalLabSchemaError()
        rows = value.get("voices")
        count = value.get("count")
        offset = value.get("offset")
        total = value.get("total")
        has_more = value.get("has_more")
        if (
            not isinstance(rows, list)
            or type(count) is not int
            or type(offset) is not int
            or type(total) is not int
            or type(has_more) is not bool
            or not 0 <= count <= 500
            or offset < 0
            or total < 0
            or count != len(rows)
            or offset + count > total
            or has_more is not (offset + count < total)
        ):
            raise VocalLabSchemaError()
        observations: list[VoiceObservation] = []
        seen: set[str] = set()
        for row in rows:
            item = _mapping(row)
            voice_id = item.get("id")
            name = item.get("name")
            provider_type = item.get("type")
            languages = item.get("languages")
            if provider_type == "clone":
                if set(item) != _CLONE_VOICE_KEYS:
                    raise VocalLabSchemaError()
                metadata = (item.get("created_at"),)
            else:
                if set(item) != _CATALOG_VOICE_KEYS:
                    raise VocalLabSchemaError()
                metadata = tuple(
                    item.get(key)
                    for key in ("accent", "category", "language_code", "slug")
                )
            if (
                not _valid_private_id(voice_id)
                or voice_id in seen
                or not isinstance(name, str)
                or not name.strip()
                or name != name.strip()
                or len(name) > 120
                or provider_type not in {"preset", "clone", "designed"}
                or not isinstance(languages, list)
                or not languages
                or any(
                    not isinstance(language, str)
                    or not language.strip()
                    or language != language.strip()
                    for language in languages
                )
                or len(set(languages)) != len(languages)
                or any(
                    not isinstance(field, str)
                    or not field.strip()
                    or field != field.strip()
                    or len(field) > 200
                    for field in metadata
                )
            ):
                raise VocalLabSchemaError()
            seen.add(voice_id)
            observations.append(
                VoiceObservation(
                    provider_voice_id=voice_id,
                    name=name,
                    provider_type=provider_type,
                    languages=tuple(languages),
                )
            )
        # Provider labels are operator-visible. Preserve legitimate labels, but
        # never echo any private provider identifier that appears in any label
        # (including a cross-entry label) back to an operator surface.
        identifiers = tuple(item.provider_voice_id.casefold() for item in observations)
        return tuple(
            VoiceObservation(
                provider_voice_id=item.provider_voice_id,
                name=(
                    f"Catalog voice {index}"
                    if any(identifier in item.name.casefold() for identifier in identifiers)
                    else item.name
                ),
                provider_type=item.provider_type,
                languages=item.languages,
            )
            for index, item in enumerate(observations, start=1)
        )
    except VocalLabSchemaError:
        raise
    except Exception:
        raise VocalLabSchemaError() from None


def parse_generation(
    payload: object,
    *,
    expected_model: str,
    expected_generation_id: str = "",
) -> GenerationObservation:
    try:
        value = _mapping(payload)
        allowed = {
            "audio_base64",
            "audio_url",
            "format",
            "id",
            "model",
            "points_used",
            "status",
        }
        if not {"format", "id", "model", "status"}.issubset(value) or not set(
            value
        ).issubset(allowed):
            raise VocalLabSchemaError()
        generation_id = value.get("id")
        status = value.get("status")
        if (
            not isinstance(generation_id, str)
            or not _PRIVATE_ID_RE.fullmatch(generation_id)
            or (expected_generation_id and generation_id != expected_generation_id)
            or status not in _GENERATION_STATUSES
            or value.get("model") != expected_model
            or value.get("format") != "WAV"
        ):
            raise VocalLabSchemaError()
        points = value.get("points_used")
        if status in VOCALLAB_GENERATION_SUCCESS:
            if type(points) is not int or points <= 0:
                raise VocalLabSchemaError()
        elif points is not None and (type(points) is not int or points < 0):
            raise VocalLabSchemaError()
        inline = value.get("audio_base64", "")
        raw_audio_url = value.get("audio_url", "")
        if raw_audio_url is None:
            audio_url = ""
        elif isinstance(raw_audio_url, str):
            audio_url = raw_audio_url
        else:
            raise VocalLabSchemaError()
        if not isinstance(inline, str):
            raise VocalLabSchemaError()
        if inline and (type(points) is not int or points <= 0):
            raise VocalLabSchemaError()
        return GenerationObservation(
            generation_id=generation_id,
            status=status,
            model=expected_model,
            audio_format="WAV",
            points_used=points,
            audio_base64=inline,
            audio_url=audio_url,
        )
    except VocalLabSchemaError:
        raise
    except Exception:
        raise VocalLabSchemaError() from None


__all__ = (
    "AccountObservation",
    "GenerationObservation",
    "ModelObservation",
    "PingObservation",
    "VOCALLAB_BILLING_UNIT",
    "VOCALLAB_GENERATION_FAILED",
    "VOCALLAB_GENERATION_PENDING",
    "VOCALLAB_GENERATION_SUCCESS",
    "VOCALLAB_MODEL_KEYS",
    "VOCALLAB_VERIFICATION_SYNTHETIC_POINTS",
    "VOCALLAB_VERIFICATION_SYNTHETIC_TEXT",
    "VOCALLAB_VERIFICATION_SYNTHETIC_TEXT_SHA256",
    "VocalLabSchemaError",
    "VoiceObservation",
    "parse_account",
    "parse_generation",
    "parse_models",
    "parse_ping",
    "parse_voices",
)
