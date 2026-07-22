"""Private, operator-approved VocalLab voice catalogue.

Provider discovery is inventory, never authorization.  This module binds a
private provider voice identifier to reviewed rights and consent evidence and
offers a deliberately redacted public projection.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import json
from pathlib import Path
import re
from typing import Any, Mapping

from app.services.audiobook_tts.authorities import AuthorityError, read_private_json
from app.services.audiobook_tts.contracts import ProviderVoiceRef


CATALOG_CONTRACT_NAME = "ea.audiobook_vocallab_voice_catalog.v1"
_MAX_CATALOG_BYTES = 1024 * 1024
_SHA256_HEX_LENGTH = 64
_PRIVATE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")


class VoiceCatalogError(RuntimeError):
    """Code-only catalogue failure safe for public error mapping."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _strict_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def _reject_json_constant(_value: str) -> None:
    raise ValueError("nonfinite_json_number")


def _require_string(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise VoiceCatalogError("voice_catalog_invalid")
    return value.strip()


def _parse_timestamp(value: str) -> datetime:
    if not value.endswith("Z"):
        raise VoiceCatalogError("voice_catalog_invalid")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        raise VoiceCatalogError("voice_catalog_invalid") from None
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise VoiceCatalogError("voice_catalog_invalid")
    return parsed.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class VoiceCatalogEntry:
    provider_voice_id: str = field(repr=False)
    voice_id_sha256: str
    safe_label: str
    provider_type: str
    rights_class: str
    languages: tuple[str, ...]
    tags: tuple[str, ...]
    allowed_uses: tuple[str, ...]
    blocked_uses: tuple[str, ...]
    rights_receipt_id: str = field(repr=False)
    consent_receipt_id: str = field(repr=False)
    reviewed_at: datetime
    active: bool

    def public_projection(self) -> dict[str, object]:
        return {
            "voice_id_sha256": self.voice_id_sha256,
            "safe_label": self.safe_label,
            "provider_type": self.provider_type,
            "rights_class": self.rights_class,
            "languages": list(self.languages),
            "tags": list(self.tags),
            "allowed_uses": list(self.allowed_uses),
            "blocked_uses": list(self.blocked_uses),
            "rights_receipt_sha256": hashlib.sha256(
                self.rights_receipt_id.encode("utf-8")
            ).hexdigest(),
            "consent_receipt_present": bool(self.consent_receipt_id),
            "active": self.active,
            "raw_voice_id_exposed": False,
        }


class VocalLabVoiceCatalog:
    def __init__(
        self,
        entries: tuple[VoiceCatalogEntry, ...],
        *,
        catalog_version: int,
        source_sha256: str,
        max_age_days: int = 30,
        now: datetime | None = None,
    ) -> None:
        if not isinstance(catalog_version, int) or isinstance(catalog_version, bool):
            raise VoiceCatalogError("voice_catalog_invalid")
        if (
            catalog_version < 1
            or not isinstance(max_age_days, int)
            or isinstance(max_age_days, bool)
            or max_age_days < 1
        ):
            raise VoiceCatalogError("voice_catalog_invalid")
        if not entries or not any(entry.active for entry in entries):
            raise VoiceCatalogError("voice_catalog_empty")
        ids: set[str] = set()
        hashes: set[str] = set()
        for entry in entries:
            if entry.provider_voice_id in ids or entry.voice_id_sha256 in hashes:
                raise VoiceCatalogError("voice_catalog_duplicate_voice")
            ids.add(entry.provider_voice_id)
            hashes.add(entry.voice_id_sha256)
        folded_ids = tuple(value.casefold() for value in ids)
        if any(
            provider_id in entry.safe_label.casefold()
            for entry in entries
            for provider_id in folded_ids
        ):
            raise VoiceCatalogError("voice_catalog_invalid")
        self._entries = entries
        self.catalog_version = catalog_version
        self.source_sha256 = source_sha256
        self.max_age_days = max_age_days
        self._now = now

    @classmethod
    def from_file(
        cls,
        path: str | Path,
        *,
        max_age_days: int = 30,
        now: datetime | None = None,
    ) -> "VocalLabVoiceCatalog":
        try:
            payload, raw, source_sha256 = read_private_json(Path(path))
        except AuthorityError:
            raise VoiceCatalogError("voice_catalog_file_unsafe") from None
        if len(raw) > _MAX_CATALOG_BYTES:
            raise VoiceCatalogError("voice_catalog_invalid")
        return cls.from_payload(
            payload,
            source_sha256=source_sha256,
            max_age_days=max_age_days,
            now=now,
        )

    @classmethod
    def from_bytes(
        cls,
        raw: bytes,
        *,
        max_age_days: int = 30,
        now: datetime | None = None,
    ) -> "VocalLabVoiceCatalog":
        if not raw or len(raw) > _MAX_CATALOG_BYTES:
            raise VoiceCatalogError("voice_catalog_invalid")
        try:
            payload = json.loads(
                raw.decode("utf-8"),
                object_pairs_hook=_strict_json_object,
                parse_constant=_reject_json_constant,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            raise VoiceCatalogError("voice_catalog_invalid") from None
        if not isinstance(payload, dict):
            raise VoiceCatalogError("voice_catalog_invalid")
        return cls.from_payload(
            payload,
            source_sha256=hashlib.sha256(raw).hexdigest(),
            max_age_days=max_age_days,
            now=now,
        )

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Any],
        *,
        source_sha256: str = "fixture",
        max_age_days: int = 30,
        now: datetime | None = None,
    ) -> "VocalLabVoiceCatalog":
        if set(payload) != {"contract_name", "catalog_version", "voices"}:
            raise VoiceCatalogError("voice_catalog_invalid")
        if payload.get("contract_name") != CATALOG_CONTRACT_NAME:
            raise VoiceCatalogError("voice_catalog_invalid")
        version = payload.get("catalog_version")
        rows = payload.get("voices")
        if (
            not isinstance(version, int)
            or isinstance(version, bool)
            or not isinstance(rows, list)
        ):
            raise VoiceCatalogError("voice_catalog_invalid")
        entries = tuple(cls._parse_entry(row) for row in rows)
        return cls(
            entries,
            catalog_version=version,
            source_sha256=source_sha256,
            max_age_days=max_age_days,
            now=now,
        )

    @staticmethod
    def _parse_entry(value: Any) -> VoiceCatalogEntry:
        if not isinstance(value, dict):
            raise VoiceCatalogError("voice_catalog_invalid")
        if set(value) != {
            "provider_voice_id",
            "voice_id_sha256",
            "safe_label",
            "provider_type",
            "rights_class",
            "languages",
            "tags",
            "allowed_uses",
            "blocked_uses",
            "rights_receipt_id",
            "consent_receipt_id",
            "reviewed_at",
            "active",
        }:
            raise VoiceCatalogError("voice_catalog_invalid")
        provider_voice_id = _require_string(value, "provider_voice_id")
        if not _PRIVATE_ID_RE.fullmatch(provider_voice_id):
            raise VoiceCatalogError("voice_catalog_invalid")
        voice_id_sha256 = _require_string(value, "voice_id_sha256").lower()
        if (
            len(voice_id_sha256) != _SHA256_HEX_LENGTH
            or any(character not in "0123456789abcdef" for character in voice_id_sha256)
            or not hmac.compare_digest(
                voice_id_sha256,
                hashlib.sha256(provider_voice_id.encode("utf-8")).hexdigest(),
            )
        ):
            raise VoiceCatalogError("voice_catalog_voice_hash_invalid")
        safe_label = _require_string(value, "safe_label")
        if provider_voice_id.casefold() in safe_label.casefold():
            raise VoiceCatalogError("voice_catalog_invalid")
        provider_type = _require_string(value, "provider_type").lower()
        rights_class = _require_string(value, "rights_class").lower()
        rights_receipt_id = _require_string(value, "rights_receipt_id")
        consent = value.get("consent_receipt_id", "")
        if not isinstance(consent, str):
            raise VoiceCatalogError("voice_catalog_invalid")

        def string_tuple(key: str, *, required: bool = False) -> tuple[str, ...]:
            raw_values = value.get(key)
            if not isinstance(raw_values, list) or any(
                not isinstance(item, str) or not item.strip() for item in raw_values
            ):
                raise VoiceCatalogError("voice_catalog_invalid")
            result = tuple(dict.fromkeys(item.strip() for item in raw_values))
            if len(result) != len(raw_values):
                raise VoiceCatalogError("voice_catalog_invalid")
            if required and not result:
                raise VoiceCatalogError("voice_catalog_invalid")
            return result

        languages = string_tuple("languages", required=True)
        tags = string_tuple("tags")
        allowed_uses = string_tuple("allowed_uses", required=True)
        blocked_uses = string_tuple("blocked_uses")
        active = value.get("active")
        if not isinstance(active, bool):
            raise VoiceCatalogError("voice_catalog_invalid")
        reviewed_at = _parse_timestamp(_require_string(value, "reviewed_at"))
        if rights_class != "professional":
            raise VoiceCatalogError("voice_catalog_rights_inconsistent")
        if provider_type != "preset":
            raise VoiceCatalogError("voice_catalog_rights_inconsistent")
        if consent.strip():
            raise VoiceCatalogError("voice_catalog_rights_inconsistent")
        return VoiceCatalogEntry(
            provider_voice_id=provider_voice_id,
            voice_id_sha256=voice_id_sha256,
            safe_label=safe_label,
            provider_type=provider_type,
            rights_class=rights_class,
            languages=languages,
            tags=tags,
            allowed_uses=allowed_uses,
            blocked_uses=blocked_uses,
            rights_receipt_id=rights_receipt_id,
            consent_receipt_id=consent.strip(),
            reviewed_at=reviewed_at,
            active=active,
        )

    @property
    def entries(self) -> tuple[VoiceCatalogEntry, ...]:
        return self._entries

    def authorize(
        self,
        voice: ProviderVoiceRef,
        *,
        language: str,
        use: str,
        allow_clones: bool = False,
        allow_community: bool = False,
        allowed_rights_classes: tuple[str, ...] = ("professional",),
        now: datetime | None = None,
    ) -> VoiceCatalogEntry:
        if allow_clones:
            raise VoiceCatalogError("voice_cloning_disabled")
        matches = [
            entry
            for entry in self._entries
            if hmac.compare_digest(entry.provider_voice_id, voice.provider_voice_id)
        ]
        if len(matches) != 1:
            raise VoiceCatalogError("voice_not_approved")
        entry = matches[0]
        current_value = now or self._now or datetime.now(UTC)
        if current_value.tzinfo is None or current_value.utcoffset() is None:
            raise VoiceCatalogError("voice_catalog_invalid")
        current = current_value.astimezone(UTC)
        if current - entry.reviewed_at > timedelta(days=self.max_age_days):
            raise VoiceCatalogError("voice_catalog_stale")
        if entry.reviewed_at > current + timedelta(minutes=5):
            raise VoiceCatalogError("voice_catalog_invalid")
        if not entry.active:
            raise VoiceCatalogError("voice_not_active")
        if not hmac.compare_digest(entry.voice_id_sha256, voice.voice_id_sha256):
            raise VoiceCatalogError("voice_binding_mismatch")
        if entry.rights_class != voice.rights_class:
            raise VoiceCatalogError("voice_rights_class_mismatch")
        if entry.rights_class not in allowed_rights_classes:
            raise VoiceCatalogError("voice_rights_not_allowed")
        if entry.provider_type in {"community", "cartoon"} and not allow_community:
            raise VoiceCatalogError("community_voice_not_allowed")
        if entry.rights_class != "professional" or voice.consent_receipt_id:
            raise VoiceCatalogError("voice_cloning_disabled")
        if not hmac.compare_digest(entry.rights_receipt_id, voice.rights_receipt_id):
            raise VoiceCatalogError("voice_rights_receipt_mismatch")
        if language not in entry.languages:
            raise VoiceCatalogError("voice_language_not_allowed")
        if use not in entry.allowed_uses or use in entry.blocked_uses:
            raise VoiceCatalogError("voice_use_not_allowed")
        return entry

    def public_projection(self) -> dict[str, object]:
        rights = Counter(entry.rights_class for entry in self._entries if entry.active)
        languages = Counter(
            language
            for entry in self._entries
            if entry.active
            for language in entry.languages
        )
        return {
            "contract_name": CATALOG_CONTRACT_NAME,
            "catalog_version": self.catalog_version,
            "catalog_sha256": self.source_sha256,
            "approved_count": sum(1 for entry in self._entries if entry.active),
            "rights_class_counts": dict(sorted(rights.items())),
            "language_counts": dict(sorted(languages.items())),
            "raw_voice_ids_exposed": False,
        }
