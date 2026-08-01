from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path

import pytest

from app.services.audiobook_tts import ProviderVoiceRef
from app.services.audiobook_tts.voice_catalog import (
    VocalLabVoiceCatalog,
    VoiceCatalogError,
)


NOW = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)


def _row(
    voice_id: str = "voice-private-1",
    *,
    provider_type: str = "preset",
    rights_class: str = "professional",
    consent: str = "",
    reviewed_at: datetime = NOW,
    languages: list[str] | None = None,
) -> dict[str, object]:
    return {
        "provider_voice_id": voice_id,
        "voice_id_sha256": hashlib.sha256(voice_id.encode()).hexdigest(),
        "safe_label": "Approved voice",
        "provider_type": provider_type,
        "rights_class": rights_class,
        "languages": languages or ["en-US"],
        "tags": ["narration"],
        "allowed_uses": ["audiobook_narration", "dialogue", "voice_audition"],
        "blocked_uses": ["unapproved_clone"],
        "rights_receipt_id": "rights-1",
        "consent_receipt_id": consent,
        "reviewed_at": reviewed_at.isoformat().replace("+00:00", "Z"),
        "active": True,
    }


def _catalog(rows: list[dict[str, object]]) -> VocalLabVoiceCatalog:
    return VocalLabVoiceCatalog.from_payload(
        {
            "contract_name": "ea.audiobook_vocallab_voice_catalog.v1",
            "catalog_version": 1,
            "voices": rows,
        },
        now=NOW,
    )


def _voice(row: dict[str, object], *, consent: str = "") -> ProviderVoiceRef:
    return ProviderVoiceRef(
        provider="vocallab",
        provider_voice_id=str(row["provider_voice_id"]),
        voice_id_sha256=str(row["voice_id_sha256"]),
        safe_label="Approved voice",
        language="en-US",
        supported_languages=("en-US",),
        rights_class=str(row["rights_class"]),
        rights_receipt_id="rights-1",
        consent_receipt_id=consent,
    )


def test_professional_voice_is_authorized_and_public_projection_has_no_raw_id() -> None:
    row = _row()
    catalog = _catalog([row])
    entry = catalog.authorize(
        _voice(row),
        language="en-US",
        use="audiobook_narration",
        now=NOW,
    )
    assert entry.safe_label == "Approved voice"
    projection = catalog.public_projection()
    rendered = json.dumps(projection)
    assert projection["approved_count"] == 1
    assert projection["raw_voice_ids_exposed"] is False
    assert str(row["provider_voice_id"]) not in rendered


def test_consented_clone_is_unconditionally_rejected() -> None:
    row = _row(rights_class="consented_clone", provider_type="clone", consent="consent-1")
    with pytest.raises(VoiceCatalogError) as blocked:
        _catalog([row])
    assert blocked.value.code == "voice_catalog_rights_inconsistent"


@pytest.mark.parametrize("provider_type", ["community", "cartoon"])
def test_community_and_cartoon_voices_are_blocked_by_default(provider_type: str) -> None:
    row = _row(provider_type=provider_type)
    with pytest.raises(VoiceCatalogError) as caught:
        _catalog([row])
    assert caught.value.code == "voice_catalog_rights_inconsistent"


def test_unknown_duplicate_hash_mismatch_language_and_stale_catalog_fail_closed() -> None:
    row = _row()
    with pytest.raises(VoiceCatalogError) as duplicate:
        _catalog([row, dict(row)])
    assert duplicate.value.code == "voice_catalog_duplicate_voice"

    bad_hash = dict(row)
    bad_hash["voice_id_sha256"] = "0" * 64
    with pytest.raises(VoiceCatalogError) as hash_error:
        _catalog([bad_hash])
    assert hash_error.value.code == "voice_catalog_voice_hash_invalid"

    catalog = _catalog([row])
    with pytest.raises(VoiceCatalogError) as language:
        catalog.authorize(
            _voice(row),
            language="de-DE",
            use="audiobook_narration",
            now=NOW,
        )
    assert language.value.code == "voice_language_not_allowed"

    stale_row = _row(reviewed_at=NOW - timedelta(days=31))
    with pytest.raises(VoiceCatalogError) as stale:
        _catalog([stale_row]).authorize(
            _voice(stale_row),
            language="en-US",
            use="audiobook_narration",
            now=NOW,
        )
    assert stale.value.code == "voice_catalog_stale"


def test_unapproved_clone_use_is_blocked_by_catalog_even_for_professional_voice() -> None:
    row = _row()
    with pytest.raises(VoiceCatalogError) as caught:
        _catalog([row]).authorize(
            _voice(row),
            language="en-US",
            use="unapproved_clone",
            now=NOW,
        )
    assert caught.value.code == "voice_use_not_allowed"


def test_catalog_file_must_be_owner_only_regular_and_not_symlink(tmp_path: Path) -> None:
    payload = {
        "contract_name": "ea.audiobook_vocallab_voice_catalog.v1",
        "catalog_version": 1,
        "voices": [_row()],
    }
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(payload))
    path.chmod(0o600)
    assert VocalLabVoiceCatalog.from_file(path, now=NOW).entries

    path.chmod(0o644)
    with pytest.raises(VoiceCatalogError) as mode:
        VocalLabVoiceCatalog.from_file(path, now=NOW)
    assert mode.value.code == "voice_catalog_file_unsafe"

    path.chmod(0o600)
    link = tmp_path / "catalog-link.json"
    link.symlink_to(path)
    with pytest.raises(VoiceCatalogError) as symlink:
        VocalLabVoiceCatalog.from_file(link, now=NOW)
    assert symlink.value.code == "voice_catalog_file_unsafe"


def test_invalid_schema_and_clone_without_consent_are_rejected() -> None:
    with pytest.raises(VoiceCatalogError) as schema:
        VocalLabVoiceCatalog.from_payload(
            {"contract_name": "wrong", "catalog_version": 1, "voices": []}
        )
    assert schema.value.code == "voice_catalog_invalid"

    with pytest.raises(VoiceCatalogError) as consent:
        _catalog([_row(rights_class="consented_clone", provider_type="clone")])
    assert consent.value.code == "voice_catalog_rights_inconsistent"


def test_raw_id_cannot_leak_through_any_cross_entry_label_or_voice_projection() -> None:
    first = _row("Private-ID-One")
    second = _row("private-id-two")
    second["safe_label"] = "Narrator PRIVATE-ID-ONE"
    with pytest.raises(VoiceCatalogError) as cross_entry:
        _catalog([first, second])
    assert cross_entry.value.code == "voice_catalog_invalid"

    projection = _voice(first).public_projection()
    rendered = json.dumps(projection)
    assert "safe_label" not in projection
    assert "Private-ID-One" not in rendered


def test_catalog_requires_exact_nonempty_runtime_schema() -> None:
    row = _row()
    extra_row = dict(row)
    extra_row["provider_secret"] = "not-allowed"
    with pytest.raises(VoiceCatalogError) as entry:
        _catalog([extra_row])
    assert entry.value.code == "voice_catalog_invalid"

    with pytest.raises(VoiceCatalogError) as root:
        VocalLabVoiceCatalog.from_payload(
            {
                "contract_name": "ea.audiobook_vocallab_voice_catalog.v1",
                "catalog_version": 1,
                "voices": [row],
                "unexpected": False,
            }
        )
    assert root.value.code == "voice_catalog_invalid"

    inactive = dict(row)
    inactive["active"] = False
    with pytest.raises(VoiceCatalogError) as empty:
        _catalog([inactive])
    assert empty.value.code == "voice_catalog_empty"
