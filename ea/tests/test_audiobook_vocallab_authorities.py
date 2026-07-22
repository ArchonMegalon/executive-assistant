from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
import hashlib
import json
from pathlib import Path

import pytest

from app.services.audiobook_tts import (
    AudiobookProviderError,
    AudiobookProviderRouter,
    synthesis_fingerprint,
)
from app.services.audiobook_tts.authorities import (
    AuthorityError,
    load_authenticated_vocallab_verification,
    load_external_processing_authorization,
    verify_cast_snapshot,
)
from app.services.audiobook_tts.providers.vocallab import (
    VocalLabConfig,
    VocalLabProvider,
)
from app.services.audiobook_tts.voice_catalog import VocalLabVoiceCatalog
from tests.vocallab_support import (
    API_KEY,
    CREDENTIAL_BINDING_SHA256,
    HMAC_KEY,
    NOW,
    authorized_case,
    verification_payload,
    write_private,
)


def _config(account_state_root: Path) -> VocalLabConfig:
    return VocalLabConfig(
        enabled=True,
        credential_rotation_required=False,
        credential_production_eligible=True,
        api_key=API_KEY,
        account_state_root=str(account_state_root),
        poll_interval_seconds=0.001,
        poll_timeout_seconds=2,
    )


def test_signed_v2_verification_loads_only_through_hmac_factory(tmp_path: Path) -> None:
    _request, catalog, store, _ledger, _private = authorized_case(tmp_path)
    loaded = load_authenticated_vocallab_verification(
        store.verification_path,
        hmac_key=HMAC_KEY,
        expected_catalog_sha256=catalog.source_sha256,
        expected_credential_binding_sha256=CREDENTIAL_BINDING_SHA256,
        now=NOW,
    )
    assert loaded.catalog_sha256 == catalog.source_sha256
    assert loaded.models == ("v-studio", "v-pro", "v-lite")
    assert len(loaded.receipt_sha256) == 64
    assert repr(HMAC_KEY) not in repr(store)


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (lambda payload: payload.update(status="blocked"), "verification_schema_invalid"),
        (lambda payload: payload.update(version=1), "verification_schema_invalid"),
        (
            lambda payload: payload["smoke"].update(points_used=0),
            "verification_schema_invalid",
        ),
        (
            lambda payload: payload["retention"].update(subprocessors=[]),
            "verification_schema_invalid",
        ),
    ],
)
def test_signed_receipt_tampering_or_legacy_schema_fails_closed(
    tmp_path: Path, mutation, code: str  # type: ignore[no-untyped-def]
) -> None:
    _request, catalog, store, _ledger, _private = authorized_case(tmp_path)
    payload = json.loads(store.verification_path.read_text())
    mutation(payload)
    write_private(store.verification_path, payload)
    with pytest.raises(AuthorityError) as caught:
        load_authenticated_vocallab_verification(
            store.verification_path,
            hmac_key=HMAC_KEY,
            expected_catalog_sha256=catalog.source_sha256,
            expected_credential_binding_sha256=CREDENTIAL_BINDING_SHA256,
            now=NOW,
        )
    assert caught.value.code == "verification_authentication_invalid"
    assert "status" not in repr(caught.value)


def test_signed_proof_for_credential_a_cannot_authorize_credential_b(
    tmp_path: Path,
) -> None:
    _request, catalog, store, _ledger, _private = authorized_case(tmp_path)
    with pytest.raises(AuthorityError) as caught:
        load_authenticated_vocallab_verification(
            store.verification_path,
            hmac_key=HMAC_KEY,
            expected_catalog_sha256=catalog.source_sha256,
            expected_credential_binding_sha256="b" * 64,
            now=NOW,
        )
    assert caught.value.code == "verification_credential_binding_mismatch"


def test_runtime_requires_the_shared_exact_synthetic_point_cost(
    tmp_path: Path,
) -> None:
    _request, catalog, store, _ledger, _private = authorized_case(tmp_path)
    write_private(
        store.verification_path,
        verification_payload(catalog.source_sha256, points_used=6),
    )
    with pytest.raises(AuthorityError) as caught:
        load_authenticated_vocallab_verification(
            store.verification_path,
            hmac_key=HMAC_KEY,
            expected_catalog_sha256=catalog.source_sha256,
            expected_credential_binding_sha256=CREDENTIAL_BINDING_SHA256,
            now=NOW,
        )
    assert caught.value.code == "verification_schema_invalid"


def test_wrong_hmac_catalog_expiry_and_naive_time_fail_closed(tmp_path: Path) -> None:
    _request, catalog, store, _ledger, _private = authorized_case(tmp_path)
    cases = (
        (b"x" * 32, catalog.source_sha256, NOW, "verification_authentication_invalid"),
        (HMAC_KEY, "f" * 64, NOW, "verification_catalog_mismatch"),
        (
            HMAC_KEY,
            catalog.source_sha256,
            NOW + timedelta(days=2),
            "authority_time_window_invalid",
        ),
    )
    for key, digest, current, code in cases:
        with pytest.raises(AuthorityError) as caught:
            load_authenticated_vocallab_verification(
                store.verification_path,
                hmac_key=key,
                expected_catalog_sha256=digest,
                expected_credential_binding_sha256=CREDENTIAL_BINDING_SHA256,
                now=current,
            )
        assert caught.value.code == code
    with pytest.raises(AuthorityError):
        load_authenticated_vocallab_verification(
            store.verification_path,
            hmac_key=HMAC_KEY,
            expected_catalog_sha256=catalog.source_sha256,
            expected_credential_binding_sha256=CREDENTIAL_BINDING_SHA256,
            now=NOW.replace(tzinfo=None),
        )


def test_external_authorization_binds_provider_subprocessor_scope_rights_and_digest(
    tmp_path: Path,
) -> None:
    request, _catalog, store, _ledger, _private = authorized_case(tmp_path)
    loaded = load_external_processing_authorization(
        store.external_authorization_path,
        request=request,
        now=NOW,
    )
    assert loaded.authorization_id == request.external_processing_authorization_id

    payload = json.loads(store.external_authorization_path.read_text())
    payload["allowed_subprocessors"] = []
    digest = write_private(store.external_authorization_path, payload)
    changed = replace(request, external_processing_authorization_sha256=digest)
    with pytest.raises(AuthorityError) as caught:
        load_external_processing_authorization(
            store.external_authorization_path,
            request=changed,
            now=NOW,
        )
    assert caught.value.code == "external_authorization_binding_invalid"


def test_generic_nonempty_external_flag_never_authorizes(tmp_path: Path) -> None:
    request, catalog, store, ledger, _private = authorized_case(tmp_path)
    provider = VocalLabProvider(
        config=_config(ledger.account_state_root),
        voice_catalog=catalog,
        authority_store=store,
        budget_ledger=ledger,
        now=lambda: NOW,
    )
    generic = replace(
        request,
        external_processing_authorization_id="external-enabled",
        external_processing_authorization_sha256="0" * 64,
    )
    with pytest.raises(AudiobookProviderError) as caught:
        provider.validate_route(generic)
    assert caught.value.failure.code == "external_authorization_binding_invalid"


def test_owner_only_regular_authority_files_are_required(tmp_path: Path) -> None:
    _request, catalog, store, _ledger, _private = authorized_case(tmp_path)
    store.verification_path.chmod(0o644)
    with pytest.raises(AuthorityError) as mode:
        load_authenticated_vocallab_verification(
            store.verification_path,
            hmac_key=HMAC_KEY,
            expected_catalog_sha256=catalog.source_sha256,
            expected_credential_binding_sha256=CREDENTIAL_BINDING_SHA256,
            now=NOW,
        )
    assert mode.value.code == "private_authority_file_unsafe"

    store.verification_path.chmod(0o600)
    link = store.verification_path.parent / "link.json"
    link.symlink_to(store.verification_path)
    with pytest.raises(AuthorityError) as symlink:
        load_authenticated_vocallab_verification(
            link,
            hmac_key=HMAC_KEY,
            expected_catalog_sha256=catalog.source_sha256,
            expected_credential_binding_sha256=CREDENTIAL_BINDING_SHA256,
            now=NOW,
        )
    assert symlink.value.code == "private_authority_file_unsafe"

    link.unlink()
    hardlink = store.verification_path.parent / "hardlink.json"
    hardlink.hardlink_to(store.verification_path)
    with pytest.raises(AuthorityError) as linked:
        load_authenticated_vocallab_verification(
            store.verification_path,
            hmac_key=HMAC_KEY,
            expected_catalog_sha256=catalog.source_sha256,
            expected_credential_binding_sha256=CREDENTIAL_BINDING_SHA256,
            now=NOW,
        )
    assert linked.value.code == "private_authority_file_unsafe"
    hardlink.unlink()

    store.verification_path.parent.chmod(0o750)
    with pytest.raises(AuthorityError) as parent:
        load_authenticated_vocallab_verification(
            store.verification_path,
            hmac_key=HMAC_KEY,
            expected_catalog_sha256=catalog.source_sha256,
            expected_credential_binding_sha256=CREDENTIAL_BINDING_SHA256,
            now=NOW,
        )
    assert parent.value.code == "private_authority_parent_unsafe"


def test_durable_cast_rejects_model_drift_across_router_instances(tmp_path: Path) -> None:
    request, catalog, store, ledger, _private = authorized_case(tmp_path)
    first = VocalLabProvider(
        config=_config(ledger.account_state_root),
        voice_catalog=catalog,
        authority_store=store,
        budget_ledger=ledger,
        now=lambda: NOW,
    )
    second = VocalLabProvider(
        config=_config(ledger.account_state_root),
        voice_catalog=catalog,
        authority_store=store,
        budget_ledger=ledger,
        now=lambda: NOW,
    )
    AudiobookProviderRouter((first,)).decide(request)
    drifted = replace(request, model="v-studio")
    with pytest.raises(AudiobookProviderError) as caught:
        AudiobookProviderRouter((second,)).decide(drifted)
    assert caught.value.failure.code == "cast_snapshot_voice_drift"


def test_cast_snapshot_digest_and_exact_binding_are_required(tmp_path: Path) -> None:
    request, _catalog, store, _ledger, _private = authorized_case(tmp_path)
    assert verify_cast_snapshot(store.cast_snapshot_path, request=request, now=NOW)  # type: ignore[arg-type]
    changed = replace(request, cast_snapshot_sha256="f" * 64)
    with pytest.raises(AuthorityError) as caught:
        verify_cast_snapshot(store.cast_snapshot_path, request=changed, now=NOW)  # type: ignore[arg-type]
    assert caught.value.code == "cast_snapshot_binding_invalid"


def test_provider_contract_version_changes_segment_fingerprint(tmp_path: Path) -> None:
    request, _catalog, _store, _ledger, _private = authorized_case(tmp_path)
    changed = replace(request, provider_contract_version="ea.audiobook_tts.vocallab.v2")
    assert synthesis_fingerprint(request) != synthesis_fingerprint(changed)


def test_signed_discovery_inventory_must_exactly_match_active_catalog(
    tmp_path: Path,
) -> None:
    request, _catalog, store, ledger, private = authorized_case(tmp_path)
    payload = json.loads((private / "catalog.json").read_text())
    second = dict(payload["voices"][0])
    second["provider_voice_id"] = "private-provider-voice-02"
    second["voice_id_sha256"] = hashlib.sha256(
        second["provider_voice_id"].encode()
    ).hexdigest()
    second["safe_label"] = "Approved narrator two"
    payload["voices"].append(second)
    catalog_path = private / "catalog-two.json"
    write_private(catalog_path, payload)
    catalog = VocalLabVoiceCatalog.from_file(catalog_path, now=NOW)
    write_private(store.verification_path, verification_payload(catalog.source_sha256))
    provider = VocalLabProvider(
        config=_config(ledger.account_state_root),
        voice_catalog=catalog,
        authority_store=store,
        budget_ledger=ledger,
        now=lambda: NOW,
    )
    with pytest.raises(AudiobookProviderError) as caught:
        provider.validate_route(request)
    assert caught.value.failure.code == "verification_catalog_inventory_mismatch"


@pytest.mark.parametrize(
    "changed",
    [
        {"cast_snapshot_sha256": ""},
        {"external_processing_authorization_sha256": ""},
        {"provider_contract_version": ""},
        {"source_text_sha256": "not-a-digest"},
    ],
)
def test_vocallab_fingerprint_refuses_invalid_authority_bindings(
    tmp_path: Path, changed: dict[str, object]
) -> None:
    request, _catalog, _store, _ledger, _private = authorized_case(tmp_path)
    with pytest.raises(ValueError, match="synthesis_authority_binding_invalid"):
        synthesis_fingerprint(replace(request, **changed))
