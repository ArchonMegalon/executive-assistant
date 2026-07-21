from __future__ import annotations

import base64
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import stat
from typing import Callable

import pytest
from pydantic import ValidationError

from app.services.governed_spatial_contract import (
    BUILD_AUTHORIZATION_SCHEMA,
    REQUEST_CONTRACT_NAME,
    SAFE_INTEGER_MAX,
    SAFE_INTEGER_MIN,
    SOURCE_PACKET_CONTRACT_NAME,
    CanonicalizationError,
    GovernedSpatialBuildAuthorization,
    GovernedSpatialRenderRequestV1,
    GovernedSpatialSourcePacketV1,
    RawJsonContractError,
    bounded_jcs,
    bounded_sha256,
    forbidden_rule_field_paths,
    normalized_request_material,
    parse_normalized_request_material,
    parse_raw_json,
    sensitive_material_paths,
    signed_payload_bytes,
)
from app.services.governed_spatial_crypto import (
    Ed25519EnvelopeSigner,
    Ed25519KeyRecord,
    Ed25519KeyRegistry,
    KeyRegistryError,
    SignatureVerificationError,
    sign_envelope,
    verify_signed_envelope,
)


NOW = datetime(2026, 7, 11, 10, 0, tzinfo=UTC)
ISSUER = "fixture-signing-authority"
ENVIRONMENT = "test"


def _signer(
    seed: bytes = bytes(range(32)),
    *,
    issuer: str = ISSUER,
    environment: str = ENVIRONMENT,
    key_ref: str = "fixture-key-v1",
    key_epoch: int = 1,
    not_before: str = "2026-07-01T00:00:00Z",
    not_after: str = "2026-08-01T00:00:00Z",
) -> Ed25519EnvelopeSigner:
    return Ed25519EnvelopeSigner.from_seed(
        seed,
        issuer=issuer,
        environment=environment,
        key_ref=key_ref,
        key_epoch=key_epoch,
        not_before=not_before,
        not_after=not_after,
    )


def _receipt(**updates: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "governed_spatial_receipt_v1",
        "contract_name": REQUEST_CONTRACT_NAME,
        "receipt_id": "receipt-fixture-0001",
        "issuer": ISSUER,
        "environment": ENVIRONMENT,
        "issued_at": "2026-07-11T10:00:00Z",
        "expires_at": "2026-07-11T10:04:00Z",
        "state": "audit_only",
        "quota": {
            "consume_quota": False,
            "attempt_number": 0,
            "reservation_ref_digest": None,
            "consumption_receipt_digest": None,
        },
        "evidence_refs": ["evidence:compose-validator:v1"],
    }
    payload.update(updates)
    return payload


def _signed_receipt(
    signer: Ed25519EnvelopeSigner | None = None,
    **updates: object,
) -> dict[str, object]:
    return sign_envelope(_receipt(**updates), signer or _signer())


def _registry(signer: Ed25519EnvelopeSigner | None = None) -> Ed25519KeyRegistry:
    return Ed25519KeyRegistry([(signer or _signer()).key_record])


def _resign_existing(receipt: dict[str, object], signer: Ed25519EnvelopeSigner) -> dict[str, object]:
    payload = signed_payload_bytes(receipt)
    signature = receipt["signature"]
    assert isinstance(signature, dict)
    signature["signed_payload_digest"] = "sha256:" + __import__("hashlib").sha256(payload).hexdigest()
    signature["signature_value"] = base64.urlsafe_b64encode(signer.private_key.sign(payload)).decode().rstrip("=")
    return receipt


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (b'{"a":1,"b":true,"c":null}', {"a": 1, "b": True, "c": None}),
        (
            ('{"lo":%d,"hi":%d}' % (SAFE_INTEGER_MIN, SAFE_INTEGER_MAX)).encode(),
            {"lo": SAFE_INTEGER_MIN, "hi": SAFE_INTEGER_MAX},
        ),
        ('{"euro":"€","emoji":"😀"}'.encode(), {"euro": "€", "emoji": "😀"}),
    ],
)
def test_raw_json_positive_domain(raw: bytes, expected: dict[str, object]) -> None:
    assert parse_raw_json(raw) == expected


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        (b'{"a":1,"a":2}', "duplicate_member"),
        (b'{"a":{"b":1,"b":2}}', "duplicate_member"),
        (b'\xef\xbb\xbf{"a":1}', "bom_forbidden"),
        (b'{"a":"\xff"}', "invalid_utf8"),
        (b'{"a":"\\ud800"}', "invalid_unicode"),
        (b'{"a":"\\udc00"}', "invalid_unicode"),
        (b'{"a":NaN}', "non_finite_forbidden"),
        (b'{"a":Infinity}', "non_finite_forbidden"),
        (b'{"a":1.0}', "float_forbidden"),
        (b'{"a":1e0}', "float_forbidden"),
        (b'{"a":-0}', "negative_zero_forbidden"),
        ((f'{{"a":{SAFE_INTEGER_MAX + 1}}}').encode(), "unsafe_integer"),
        ((f'{{"a":{SAFE_INTEGER_MIN - 1}}}').encode(), "unsafe_integer"),
        (b'{"a":1}{}', "malformed_json"),
        (b'[]', "root_object_required"),
    ],
)
def test_raw_json_rejects_adversarial_domain(raw: bytes, reason: str) -> None:
    with pytest.raises(RawJsonContractError, match=reason):
        parse_raw_json(raw)


def test_raw_json_size_and_input_type_are_bounded() -> None:
    with pytest.raises(RawJsonContractError, match="raw_json_too_large"):
        parse_raw_json(b'{"a":1}', max_bytes=4)
    with pytest.raises(RawJsonContractError, match="raw_json_bytes_required"):
        parse_raw_json(7)  # type: ignore[arg-type]


def test_bounded_jcs_uses_utf16_key_order_and_unicode_preservation() -> None:
    value = {
        "€": "Euro",
        "\r": "CR",
        "דּ": "Hebrew",
        "1": "One",
        "😀": "Emoji",
        "\u0080": "Control",
        "ö": "O-diaeresis",
    }
    expected = '{"\\r":"CR","1":"One","\u0080":"Control","ö":"O-diaeresis","€":"Euro","😀":"Emoji","דּ":"Hebrew"}'
    assert bounded_jcs(value) == expected.encode()


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ('"', b'"\\\""'),
        ("\\", b'"\\\\"'),
        ("\x0f", b'"\\u000f"'),
        ("\n", b'"\\n"'),
        ("€", '"€"'.encode()),
    ],
)
def test_bounded_jcs_scalar_escaping(value: str, expected: bytes) -> None:
    assert bounded_jcs(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        1.0,
        -0.0,
        float("nan"),
        float("inf"),
        SAFE_INTEGER_MAX + 1,
        "\ud800",
        (1, 2),
    ],
)
def test_bounded_jcs_rejects_out_of_domain_values(value: object) -> None:
    with pytest.raises(CanonicalizationError):
        bounded_jcs(value)


def test_signed_payload_deletes_exactly_the_two_nested_members() -> None:
    signed = _signed_receipt(
        signature_value="top-level-signed-field",
        signed_payload_digest="top-level-digest-field",
    )
    original = signed_payload_bytes(signed)
    changed_excluded = deepcopy(signed)
    nested_signature = changed_excluded["signature"]
    assert isinstance(nested_signature, dict)
    nested_signature["signature_value"] = "B" * 86
    nested_signature["signed_payload_digest"] = "sha256:" + ("f" * 64)
    assert signed_payload_bytes(changed_excluded) == original

    changed_included = deepcopy(signed)
    changed_included["signature_value"] = "changed-top-level-value"
    assert signed_payload_bytes(changed_included) != original


def test_real_ed25519_signature_is_deterministic_and_verifies() -> None:
    signer = _signer()
    first = _signed_receipt(signer)
    second = _signed_receipt(signer)
    assert first == second
    signature = first["signature"]
    assert isinstance(signature, dict)
    assert len(str(signature["signature_value"])) == 86
    verification = verify_signed_envelope(first, _registry(signer), observed_at=NOW)
    assert verification.payload_digest == signature["signed_payload_digest"]
    assert verification.key_fingerprint == signer.key_record.fingerprint


def test_ed25519_signature_supports_non_ascii_payload() -> None:
    signed = _signed_receipt(receipt_id="receipt-€-😀", evidence_refs=["evidence:世界:v1"])
    verify_signed_envelope(signed, _registry(), observed_at=NOW)


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("algorithm", "none", "signature_profile:algorithm"),
        ("encoding", "base64", "signature_profile:encoding"),
        ("canonicalization", "json", "signature_profile:canonicalization"),
        ("signed_payload_scope", "entire_receipt", "signature_profile:signed_payload_scope"),
        ("key_ref", "", "signature_key_ref_invalid"),
        ("key_epoch", -1, "signature_key_epoch_invalid"),
        ("key_epoch", True, "signature_key_epoch_invalid"),
        ("key_fingerprint", "sha256:" + ("A" * 64), "signature_key_fingerprint_invalid"),
        ("signature_value", "A" * 85, "signature_value_shape"),
        ("signature_value", ("A" * 85) + "B", "signature_value_shape"),
        ("signed_payload_digest", "sha256:" + ("g" * 64), "signed_payload_digest_invalid"),
    ],
)
def test_signature_profile_rejects_structural_mutations(field: str, value: object, reason: str) -> None:
    candidate = _signed_receipt()
    signature = candidate["signature"]
    assert isinstance(signature, dict)
    signature[field] = value
    with pytest.raises(SignatureVerificationError, match=reason):
        verify_signed_envelope(candidate, _registry(), observed_at=NOW)


def test_signature_profile_rejects_missing_and_extra_members() -> None:
    missing = _signed_receipt()
    missing_signature = missing["signature"]
    assert isinstance(missing_signature, dict)
    missing_signature.pop("signature_value")
    with pytest.raises(SignatureVerificationError, match="signature_members_invalid"):
        verify_signed_envelope(missing, _registry(), observed_at=NOW)

    extra = _signed_receipt()
    extra_signature = extra["signature"]
    assert isinstance(extra_signature, dict)
    extra_signature["unexpected"] = "forbidden"
    with pytest.raises(SignatureVerificationError, match="signature_members_invalid"):
        verify_signed_envelope(extra, _registry(), observed_at=NOW)


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (lambda receipt: receipt.update({"receipt_id": "tampered"}), "signed_payload_digest_mismatch"),
        (lambda receipt: receipt.update({"issuer": "other-authority"}), "signed_payload_digest_mismatch"),
        (lambda receipt: receipt.update({"environment": "other"}), "signed_payload_digest_mismatch"),
        (lambda receipt: receipt.update({"expires_at": "2026-07-11T10:03:00Z"}), "signed_payload_digest_mismatch"),
    ],
)
def test_signed_envelope_mutations_fail_closed(
    mutate: Callable[[dict[str, object]], None],
    reason: str,
) -> None:
    candidate = _signed_receipt()
    mutate(candidate)
    with pytest.raises(SignatureVerificationError, match=reason):
        verify_signed_envelope(candidate, _registry(), observed_at=NOW)


def test_wrong_digest_and_signature_fail_closed() -> None:
    wrong_digest = _signed_receipt()
    digest_signature = wrong_digest["signature"]
    assert isinstance(digest_signature, dict)
    digest_signature["signed_payload_digest"] = "sha256:" + ("0" * 64)
    with pytest.raises(SignatureVerificationError, match="signed_payload_digest_mismatch"):
        verify_signed_envelope(wrong_digest, _registry(), observed_at=NOW)

    wrong_signature = _signed_receipt()
    crypto_signature = wrong_signature["signature"]
    assert isinstance(crypto_signature, dict)
    value = str(crypto_signature["signature_value"])
    crypto_signature["signature_value"] = ("B" if value[0] != "B" else "C") + value[1:]
    with pytest.raises(SignatureVerificationError, match="ed25519_signature_invalid"):
        verify_signed_envelope(wrong_signature, _registry(), observed_at=NOW)


def test_registry_binds_key_to_issuer_environment_ref_and_epoch() -> None:
    signed = _signed_receipt()
    for signer in (
        _signer(issuer="other-authority"),
        _signer(environment="other"),
        _signer(key_ref="other-key"),
        _signer(key_epoch=2),
    ):
        with pytest.raises(SignatureVerificationError, match="key_identity_non_unique_or_missing"):
            verify_signed_envelope(signed, _registry(signer), observed_at=NOW)


def test_registry_rejects_global_fingerprint_aliases_and_identity_reuse() -> None:
    primary = _signer()
    alias = _signer(key_ref="alias-key", key_epoch=2)
    with pytest.raises(KeyRegistryError, match="global_key_fingerprint_duplicate"):
        Ed25519KeyRegistry([primary.key_record, alias.key_record])
    with pytest.raises(KeyRegistryError, match="key_identity_duplicate"):
        Ed25519KeyRegistry([primary.key_record, primary.key_record])


def test_registry_rejects_epoch_regression() -> None:
    newer = _signer(bytes(reversed(range(32))), key_epoch=2)
    older = _signer(bytes(range(32)), key_epoch=1)
    registry = Ed25519KeyRegistry([newer.key_record])
    with pytest.raises(KeyRegistryError, match="key_epoch_regression"):
        registry.register(older.key_record)


def test_key_and_receipt_chronology_are_enforced() -> None:
    signed = _signed_receipt()
    too_late = _signer(not_after="2026-07-11T10:03:59Z")
    with pytest.raises(SignatureVerificationError, match="key_or_receipt_chronology_invalid"):
        verify_signed_envelope(signed, _registry(too_late), observed_at=NOW)

    future = _signed_receipt(issued_at="2026-07-11T10:10:01Z", expires_at="2026-07-11T10:11:00Z")
    with pytest.raises(SignatureVerificationError, match="receipt_not_yet_current"):
        verify_signed_envelope(future, _registry(), observed_at=NOW)

    stale = _signed_receipt(issued_at="2026-07-11T09:00:00Z", expires_at="2026-07-11T09:04:00Z")
    with pytest.raises(SignatureVerificationError, match="receipt_expired"):
        verify_signed_envelope(stale, _registry(), observed_at=NOW)


def test_maximum_receipt_freshness_window_is_enforced() -> None:
    signed = _signed_receipt(expires_at="2026-07-12T10:00:01Z")
    with pytest.raises(SignatureVerificationError, match="receipt_freshness_window_exceeded"):
        verify_signed_envelope(
            signed,
            _registry(),
            observed_at=NOW,
            maximum_receipt_age=timedelta(hours=24),
        )


def test_revocation_is_idempotent_and_invalidates_later_verification(tmp_path) -> None:
    signer = _signer()
    path = tmp_path / "private" / "key-registry.json"
    registry = Ed25519KeyRegistry([signer.key_record], path=path)
    reason = "sha256:" + ("a" * 64)
    first = registry.revoke(signer.key_record.identity, revoked_at=NOW, reason_digest=reason)
    second = registry.revoke(signer.key_record.identity, revoked_at=NOW, reason_digest=reason)
    assert first == second
    with pytest.raises(SignatureVerificationError, match="key_revoked_or_inactive"):
        verify_signed_envelope(_signed_receipt(signer), registry, observed_at=NOW)

    restarted = Ed25519KeyRegistry(path=path)
    assert restarted.records[0].state == "revoked"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    persisted = path.read_text(encoding="utf-8")
    assert "private_key" not in persisted
    assert bytes(range(32)).hex() not in persisted


def test_persisted_registry_integrity_and_permissions_fail_closed(tmp_path) -> None:
    path = tmp_path / "registry.json"
    Ed25519KeyRegistry([_signer().key_record], path=path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["records"][0]["state"] = "revoked"
    path.write_text(json.dumps(payload), encoding="utf-8")
    path.chmod(0o600)
    with pytest.raises(KeyRegistryError, match="registry_integrity_failed"):
        Ed25519KeyRegistry(path=path)

    Ed25519KeyRegistry([_signer().key_record], path=tmp_path / "other.json")
    other = tmp_path / "other.json"
    other.chmod(0o644)
    with pytest.raises(KeyRegistryError, match="registry_permissions_not_private"):
        Ed25519KeyRegistry(path=other)


def test_registry_rejects_final_component_symlinks_without_following_them(tmp_path) -> None:
    target = tmp_path / "real-registry.json"
    Ed25519KeyRegistry([_signer().key_record], path=target)
    link = tmp_path / "registry-link.json"
    link.symlink_to(target)

    with pytest.raises(KeyRegistryError, match="registry_file_invalid"):
        Ed25519KeyRegistry(path=link)

    dangling = tmp_path / "dangling-registry.json"
    dangling.symlink_to(tmp_path / "missing-registry.json")
    with pytest.raises(KeyRegistryError, match="registry_file_invalid"):
        Ed25519KeyRegistry(path=dangling)


def test_register_persistence_failure_leaves_memory_disk_and_temp_files_unchanged(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "registry.json"
    registry = Ed25519KeyRegistry([_signer().key_record], path=path)
    before_records = registry.records
    before_events = registry.revocation_events
    before_disk = path.read_bytes()
    before_names = {entry.name for entry in tmp_path.iterdir()}
    candidate = _signer(bytes(reversed(range(32))), key_ref="fixture-key-v2", key_epoch=2).key_record

    def fail_replace(source: object, destination: object) -> None:
        raise OSError("forced_replace_failure")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError, match="forced_replace_failure"):
        registry.register(candidate)

    assert registry.records == before_records
    assert registry.revocation_events == before_events
    assert path.read_bytes() == before_disk
    assert {entry.name for entry in tmp_path.iterdir()} == before_names


def test_revoke_persistence_failure_leaves_records_and_events_unchanged(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    signer = _signer()
    path = tmp_path / "registry.json"
    registry = Ed25519KeyRegistry([signer.key_record], path=path)
    before_records = registry.records
    before_events = registry.revocation_events
    before_disk = path.read_bytes()

    def fail_replace(source: object, destination: object) -> None:
        raise OSError("forced_revoke_persistence_failure")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError, match="forced_revoke_persistence_failure"):
        registry.revoke(
            signer.key_record.identity,
            revoked_at=NOW,
            reason_digest="sha256:" + ("c" * 64),
        )

    assert registry.records == before_records
    assert registry.revocation_events == before_events
    assert path.read_bytes() == before_disk
    assert not any(entry.name.endswith(".tmp") for entry in tmp_path.iterdir())


def test_registry_atomic_writes_use_unique_same_directory_temp_names(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_sources: list[Path] = []
    real_replace = os.replace

    def capture_replace(source: object, destination: object) -> None:
        captured_sources.append(Path(source))
        real_replace(source, destination)

    monkeypatch.setattr(os, "replace", capture_replace)
    path = tmp_path / "registry.json"
    registry = Ed25519KeyRegistry([_signer().key_record], path=path)
    registry.register(
        _signer(bytes(reversed(range(32))), key_ref="fixture-key-v2", key_epoch=2).key_record
    )

    assert len(captured_sources) == 2
    assert len({source.name for source in captured_sources}) == 2
    assert all(source.parent == path.parent for source in captured_sources)
    assert all(source.name.startswith(f".{path.name}.") for source in captured_sources)
    assert all(source.name.endswith(".tmp") for source in captured_sources)
    assert not any(entry.name.endswith(".tmp") for entry in tmp_path.iterdir())


def test_verification_requires_current_offset_aware_observation() -> None:
    signed = _signed_receipt()
    with pytest.raises(TypeError, match="observed_at"):
        verify_signed_envelope(signed, _registry())  # type: ignore[call-arg]
    with pytest.raises(SignatureVerificationError, match="observed_at_offset_required"):
        verify_signed_envelope(
            signed,
            _registry(),
            observed_at=datetime(2026, 7, 11, 10, 0),
        )


@pytest.mark.parametrize(
    ("arguments", "reason"),
    [
        ({"allowed_clock_skew": timedelta(seconds=-1)}, "allowed_clock_skew_negative"),
        ({"allowed_clock_skew": timedelta(seconds=301)}, "allowed_clock_skew_exceeds_maximum"),
        ({"allowed_clock_skew": 300}, "allowed_clock_skew_invalid"),
        ({"maximum_receipt_age": timedelta(seconds=-1)}, "maximum_receipt_age_negative"),
        ({"maximum_receipt_age": timedelta(hours=24, seconds=1)}, "maximum_receipt_age_exceeds_maximum"),
        ({"maximum_receipt_age": None}, "maximum_receipt_age_invalid"),
    ],
)
def test_freshness_parameters_cannot_bypass_current_verification(
    arguments: dict[str, object],
    reason: str,
) -> None:
    with pytest.raises(SignatureVerificationError, match=reason):
        verify_signed_envelope(
            _signed_receipt(),
            _registry(),
            observed_at=NOW,
            **arguments,  # type: ignore[arg-type]
        )


def test_zero_length_receipt_and_key_windows_are_rejected() -> None:
    zero_receipt = _signed_receipt(
        issued_at="2026-07-11T10:00:00Z",
        expires_at="2026-07-11T10:00:00Z",
    )
    with pytest.raises(SignatureVerificationError, match="receipt_chronology_invalid"):
        verify_signed_envelope(zero_receipt, _registry(), observed_at=NOW)

    with pytest.raises(KeyRegistryError, match="key_window_invalid"):
        _signer(
            not_before="2026-07-11T10:00:00Z",
            not_after="2026-07-11T10:00:00Z",
        )


@pytest.mark.parametrize(
    "revoked_at",
    ["2026-06-30T23:59:59Z", "2026-08-01T00:00:01Z"],
)
def test_revoked_at_must_remain_within_key_validity_window(revoked_at: str) -> None:
    active = _signer().key_record
    with pytest.raises(KeyRegistryError, match="revoked_at_outside_key_window"):
        Ed25519KeyRecord(
            issuer=active.issuer,
            environment=active.environment,
            key_ref=active.key_ref,
            key_epoch=active.key_epoch,
            public_key_bytes=active.public_key_bytes,
            not_before=active.not_before,
            not_after=active.not_after,
            state="revoked",
            revoked_at=revoked_at,
            revocation_reason_digest="sha256:" + ("d" * 64),
        )


def test_failed_out_of_window_revocation_does_not_mutate_registry() -> None:
    signer = _signer()
    registry = Ed25519KeyRegistry([signer.key_record])
    with pytest.raises(KeyRegistryError, match="revoked_at_outside_key_window"):
        registry.revoke(
            signer.key_record.identity,
            revoked_at=datetime(2026, 8, 1, 0, 0, 1, tzinfo=UTC),
            reason_digest="sha256:" + ("e" * 64),
        )
    assert registry.records == (signer.key_record,)
    assert registry.revocation_events == ()


def _request_payload() -> dict[str, object]:
    return {
        "contract_name": REQUEST_CONTRACT_NAME,
        "request_id": "74bc092f-c6d8-44ec-990a-5738cc0987ac",
        "idempotency_key": "consumer-tour-demo-v1",
        "consumer": {
            "product": "consumer_alpha",
            "tenant_ref": "tenant:demo",
            "subject_ref": "subject:demo-flat",
        },
        "artifact": {"kind": "continuous_walkthrough", "purpose": "walkthrough", "locale": "en-AT"},
        "source_packet_ref": "source-packet:demo-flat-v1",
        "truth_refs": ["truth:demo-flat"],
        "evidence_refs": ["evidence:room-graph-v1"],
        "spatial_plan": {
            "room_graph_ref": "room-graph:demo-flat-v1",
            "walkable_mesh_ref": "walkable-mesh:demo-flat-v1",
            "portal_graph_ref": "portal-graph:demo-flat-v1",
            "required_room_ids": ["living", "bathroom"],
            "route_room_ids": ["living", "bathroom"],
            "portal_edges": [{"from_room_id": "living", "to_room_id": "bathroom"}],
            "route_policy": "continuous_all_walkable_rooms",
            "allow_revisit": False,
        },
        "style": {"style_pack_id": "style-pack-v1", "room_overrides": {}},
        "scene_overlays": [],
        "camera": {
            "height_m": 1.6,
            "target_delivery_fps": 60,
            "minimum_effective_motion_fps": 30,
            "motion_profile": "slow_inspection",
            "cuts_allowed": False,
            "teleports_allowed": False,
            "collision_avoidance": True,
            "rotation_smoothing": True,
        },
        "output": {
            "desktop": True,
            "mobile": True,
            "video_codec": "h264",
            "interactive_package": False,
            "poster_frame": True,
            "contact_sheet": True,
        },
        "content_policy": {
            "rating": "general",
            "graphic_injury": False,
            "real_person_likeness": False,
            "minor_combatants": False,
        },
        "quota": {"consume_quota": False, "maximum_provider_attempts": 0},
        "callback": {"product_event_ref": "event:render-complete"},
    }


def test_request_contract_is_consumer_generic_and_normalized_deterministically() -> None:
    first = GovernedSpatialRenderRequestV1.model_validate(_request_payload())
    changed_id = _request_payload()
    changed_id["request_id"] = "4b5f63bf-d590-456d-b693-226aec5d403f"
    second = GovernedSpatialRenderRequestV1.model_validate(changed_id)
    first_material = normalized_request_material(first)
    second_material = normalized_request_material(second)
    assert first_material == second_material
    assert first_material["camera"]["height_m"] == "1.6"  # type: ignore[index]
    assert bounded_sha256(first_material) == bounded_sha256(second_material)


def _revisit_request_payload() -> dict[str, object]:
    payload = _request_payload()
    payload["spatial_plan"] = {
        "room_graph_ref": "room-graph:demo-flat-v1",
        "walkable_mesh_ref": "walkable-mesh:demo-flat-v1",
        "portal_graph_ref": "portal-graph:demo-flat-v1",
        "required_room_ids": ["hall", "bedroom", "bathroom"],
        "route_room_ids": ["bedroom", "hall", "bathroom", "hall", "bedroom"],
        "portal_edges": [
            {"from_room_id": "hall", "to_room_id": "bedroom"},
            {"from_room_id": "bathroom", "to_room_id": "hall"},
        ],
        "route_policy": "continuous_all_walkable_rooms",
        "allow_revisit": True,
    }
    return payload


def test_request_route_accepts_exact_2n_minus_1_and_binds_exact_order() -> None:
    at_ceiling = GovernedSpatialRenderRequestV1.model_validate(_revisit_request_payload())
    assert at_ceiling.spatial_plan.route_room_ids == ["bedroom", "hall", "bathroom", "hall", "bedroom"]
    assert at_ceiling.spatial_plan.allow_revisit is True

    alternate = _revisit_request_payload()
    alternate["spatial_plan"]["route_room_ids"] = [  # type: ignore[index]
        "bathroom",
        "hall",
        "bedroom",
        "hall",
        "bathroom",
    ]
    alternate_model = GovernedSpatialRenderRequestV1.model_validate(alternate)
    assert normalized_request_material(at_ceiling) != normalized_request_material(alternate_model)
    assert bounded_sha256(normalized_request_material(at_ceiling)) != bounded_sha256(
        normalized_request_material(alternate_model)
    )


def test_request_route_rejects_2n_and_exact_revisit_equivalence_failures() -> None:
    too_long = _revisit_request_payload()
    too_long["spatial_plan"]["route_room_ids"] = [  # type: ignore[index]
        "bedroom",
        "hall",
        "bathroom",
        "hall",
        "bedroom",
        "hall",
    ]
    with pytest.raises(ValidationError, match="route_visit_count_exceeds_2n_minus_1"):
        GovernedSpatialRenderRequestV1.model_validate(too_long)

    duplicate_with_false = _revisit_request_payload()
    duplicate_with_false["spatial_plan"]["allow_revisit"] = False  # type: ignore[index]
    with pytest.raises(ValidationError, match="allow_revisit_must_equal_actual_route_revisit"):
        GovernedSpatialRenderRequestV1.model_validate(duplicate_with_false)

    unique_with_true = _request_payload()
    unique_with_true["spatial_plan"]["allow_revisit"] = True  # type: ignore[index]
    with pytest.raises(ValidationError, match="allow_revisit_must_equal_actual_route_revisit"):
        GovernedSpatialRenderRequestV1.model_validate(unique_with_true)

    consecutive = _revisit_request_payload()
    consecutive["spatial_plan"]["route_room_ids"] = [  # type: ignore[index]
        "bedroom",
        "hall",
        "hall",
        "bathroom",
    ]
    with pytest.raises(ValidationError, match="consecutive_route_room_ids_forbidden"):
        GovernedSpatialRenderRequestV1.model_validate(consecutive)


def test_request_portals_are_undirected_unique_and_non_self() -> None:
    reverse = _request_payload()
    reverse["spatial_plan"]["portal_edges"] = [  # type: ignore[index]
        {"from_room_id": "bathroom", "to_room_id": "living"}
    ]
    assert GovernedSpatialRenderRequestV1.model_validate(reverse).spatial_plan.route_room_ids == [
        "living",
        "bathroom",
    ]

    duplicate = _request_payload()
    duplicate["spatial_plan"]["portal_edges"] = [  # type: ignore[index]
        {"from_room_id": "living", "to_room_id": "bathroom"},
        {"from_room_id": "bathroom", "to_room_id": "living"},
    ]
    with pytest.raises(ValidationError, match="duplicate_undirected_portal_edge"):
        GovernedSpatialRenderRequestV1.model_validate(duplicate)

    self_edge = _request_payload()
    self_edge["spatial_plan"]["portal_edges"] = [  # type: ignore[index]
        {"from_room_id": "living", "to_room_id": "living"},
        {"from_room_id": "living", "to_room_id": "bathroom"},
    ]
    with pytest.raises(ValidationError, match="self_portal_edge_forbidden"):
        GovernedSpatialRenderRequestV1.model_validate(self_edge)

    unused_extraneous = _request_payload()
    unused_extraneous["spatial_plan"]["portal_edges"] = [  # type: ignore[index]
        {"from_room_id": "living", "to_room_id": "bathroom"},
        {"from_room_id": "living", "to_room_id": "attic"},
    ]
    with pytest.raises(ValidationError, match="portal_edge_room_not_required"):
        GovernedSpatialRenderRequestV1.model_validate(unused_extraneous)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload.update({"truth_refs": ["https://external.invalid/raw"]}),
        lambda payload: payload["consumer"].update({"tenant_ref": "provider_account_id:raw"}),  # type: ignore[union-attr]
        lambda payload: payload["style"].update({"provider_url": "hidden"}),  # type: ignore[union-attr]
        lambda payload: payload["quota"].update({"consume_quota": True}),  # type: ignore[union-attr]
        lambda payload: payload["quota"].update({"maximum_provider_attempts": 1}),  # type: ignore[union-attr]
    ],
)
def test_request_contract_rejects_sensitive_or_quota_mutations(
    mutation: Callable[[dict[str, object]], None],
) -> None:
    payload = _request_payload()
    mutation(payload)
    with pytest.raises(ValidationError):
        GovernedSpatialRenderRequestV1.model_validate(payload)


def test_recursive_rules_result_scan_reports_nested_paths() -> None:
    overlay = {"beats": [{"action": "move", "nested": {"damage": 4}}]}
    assert forbidden_rule_field_paths(overlay, path="scene_overlays[0]") == [
        "scene_overlays[0].beats[0].nested.damage"
    ]
    assert sensitive_material_paths({"safe": {"provider_task_id": "raw"}}) == [
        "sensitive_field:safe.provider_task_id"
    ]


def test_build_authorization_requires_explicit_consume_quota_and_exact_attempts() -> None:
    valid = {
        "schema_name": BUILD_AUTHORIZATION_SCHEMA,
        "accepted_composition_digest": "a" * 64,
        "idempotency_key": "build-demo-v1",
        "requested_by_ref": "operator:approved",
        "authorization_ref": "authorization:build-1",
        "audit_event_ref": "audit-event:build-1",
        "consume_quota": True,
        "maximum_provider_attempts": 2,
    }
    assert GovernedSpatialBuildAuthorization.model_validate(valid).maximum_provider_attempts == 2
    for mutation in (
        {"consume_quota": False},
        {"maximum_provider_attempts": 0},
        {"maximum_provider_attempts": 3},
        {"maximum_provider_attempts": True},
        {"maximum_provider_attempts": 1.5},
    ):
        with pytest.raises(ValidationError):
            GovernedSpatialBuildAuthorization.model_validate({**valid, **mutation})


def _source_payload() -> dict[str, object]:
    return {
        "contract_name": SOURCE_PACKET_CONTRACT_NAME,
        "source_packet_ref": "source-packet:fixture:v1",
        "source_digest": "b" * 64,
        "source_retrieved_at": "2026-07-11T09:00:00Z",
        "normalized_floorplan_ref": "floorplan:fixture:v1",
        "room_graph_ref": "room-graph:fixture:v1",
        "walkable_mesh_ref": "mesh:fixture:v1",
        "portal_graph_ref": "portals:fixture:v1",
        "scale_m_per_unit": 1,
        "orientation_degrees": 90,
        "license_provenance_refs": ["license:first-party:v1"],
        "source_media_assignments": [],
        "inaccessible_rooms": [],
        "route_exclusions": [],
        "rooms": [
            {
                "room_id": "living",
                "room_type": "living",
                "walkable": True,
                "boundary_ref": "boundary:living",
                "ceiling_height_m": 3,
                "geometry_anchor_ref": "anchor:living",
                "texture_anchor_refs": ["texture:living"],
            }
        ],
        "portals": [],
        "route_room_ids": ["living"],
        "existing_artifacts": {},
    }


def test_source_packet_contract_rejects_unknown_route_rooms_and_sensitive_material() -> None:
    assert GovernedSpatialSourcePacketV1.model_validate(_source_payload()).source_digest == "b" * 64
    unknown = _source_payload()
    unknown["route_room_ids"] = ["unknown"]
    with pytest.raises(ValidationError, match="route_room_not_in_source_inventory"):
        GovernedSpatialSourcePacketV1.model_validate(unknown)

    sensitive = _source_payload()
    sensitive["source_media_assignments"] = [{"provider_task_id": "raw"}]
    with pytest.raises(ValidationError):
        GovernedSpatialSourcePacketV1.model_validate(sensitive)


def test_source_packet_created_at_is_optional_for_legacy_and_strict_when_present() -> None:
    legacy = GovernedSpatialSourcePacketV1.model_validate(_source_payload())
    assert legacy.source_packet_created_at is None

    current = _source_payload()
    current["source_packet_created_at"] = "2026-07-11T09:30:00+00:00"
    assert GovernedSpatialSourcePacketV1.model_validate(current).source_packet_created_at == current[
        "source_packet_created_at"
    ]

    for value, reason in (
        ("2026-07-11T09:30:00", "source_timestamp_offset_required"),
        ("2026-07-11T08:59:59Z", "source_packet_created_before_source_retrieved"),
    ):
        invalid = _source_payload()
        invalid["source_packet_created_at"] = value
        with pytest.raises(ValidationError, match=reason):
            GovernedSpatialSourcePacketV1.model_validate(invalid)


def test_normalized_request_material_parser_accepts_only_exact_typed_dump() -> None:
    request = GovernedSpatialRenderRequestV1.model_validate(_request_payload())
    normalized = normalized_request_material(request)
    assert parse_normalized_request_material(normalized) == normalized

    with_request_id = deepcopy(normalized)
    with_request_id["request_id"] = str(request.request_id)
    with pytest.raises(ValueError, match="normalized_request_request_id_forbidden"):
        parse_normalized_request_material(with_request_id)

    legacy_float = deepcopy(normalized)
    legacy_float["camera"]["height_m"] = 1.6
    with pytest.raises(ValueError, match="normalized_request_canonical_form_required"):
        parse_normalized_request_material(legacy_float)

    omitted = deepcopy(normalized)
    omitted["style"].pop("asset_reuse_proof_refs")
    with pytest.raises(ValueError, match="normalized_request_canonical_form_required"):
        parse_normalized_request_material(omitted)


def test_normalized_request_material_revalidates_mutated_typed_instances() -> None:
    request = GovernedSpatialRenderRequestV1.model_validate(_request_payload())
    request.style.asset_reuse_proof_refs.append("https://attacker.invalid/credential")
    with pytest.raises(ValidationError):
        normalized_request_material(request)


def _revisit_source_payload() -> dict[str, object]:
    payload = _source_payload()
    payload["rooms"] = [
        {
            "room_id": room_id,
            "room_type": "room",
            "walkable": True,
            "boundary_ref": f"boundary:{room_id}",
            "ceiling_height_m": 3,
            "geometry_anchor_ref": f"anchor:{room_id}",
            "texture_anchor_refs": [f"texture:{room_id}"],
        }
        for room_id in ("hall", "bedroom", "bathroom")
    ]
    payload["portals"] = [
        {
            "portal_id": "portal:bedroom-hall",
            "from_room_id": "bedroom",
            "to_room_id": "hall",
            "walkable": True,
        },
        {
            "portal_id": "portal:bathroom-hall",
            "from_room_id": "bathroom",
            "to_room_id": "hall",
            "walkable": True,
        },
    ]
    payload["route_room_ids"] = ["bedroom", "hall", "bathroom", "hall", "bedroom"]
    return payload


def test_source_route_accepts_revisits_and_reverse_portal_traversal_at_ceiling() -> None:
    parsed = GovernedSpatialSourcePacketV1.model_validate(_revisit_source_payload())
    assert parsed.route_room_ids == ["bedroom", "hall", "bathroom", "hall", "bedroom"]


def test_source_route_accepts_distinct_parallel_portal_ids_for_one_undirected_edge() -> None:
    payload = _revisit_source_payload()
    payload["portals"].append(  # type: ignore[union-attr]
        {
            "portal_id": "portal:hall-bedroom:second",
            "from_room_id": "hall",
            "to_room_id": "bedroom",
            "walkable": True,
        }
    )
    parsed = GovernedSpatialSourcePacketV1.model_validate(payload)
    assert [portal.portal_id for portal in parsed.portals] == [
        "portal:bedroom-hall",
        "portal:bathroom-hall",
        "portal:hall-bedroom:second",
    ]


def test_source_preserves_known_nonwalkable_portal_truth_without_routing_it() -> None:
    payload = _source_payload()
    payload["rooms"].append(  # type: ignore[union-attr]
        {
            "room_id": "service",
            "room_type": "service",
            "walkable": False,
            "boundary_ref": "boundary:service",
            "ceiling_height_m": 3,
            "geometry_anchor_ref": "anchor:service",
            "texture_anchor_refs": ["texture:service"],
        }
    )
    payload["portals"] = [
        {
            "portal_id": "portal:living-service",
            "from_room_id": "living",
            "to_room_id": "service",
            "walkable": True,
        }
    ]
    parsed = GovernedSpatialSourcePacketV1.model_validate(payload)
    assert parsed.route_room_ids == ["living"]
    assert parsed.portals[0].to_room_id == "service"

    routed_nonwalkable = deepcopy(payload)
    routed_nonwalkable["route_room_ids"] = ["service"]
    with pytest.raises(ValidationError, match="route_room_not_walkable"):
        GovernedSpatialSourcePacketV1.model_validate(routed_nonwalkable)

    unknown_portal = deepcopy(payload)
    unknown_portal["portals"][0]["to_room_id"] = "unknown"  # type: ignore[index]
    with pytest.raises(ValidationError, match="source_portal_room_not_in_inventory"):
        GovernedSpatialSourcePacketV1.model_validate(unknown_portal)


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (
            lambda payload: payload.__setitem__(
                "route_room_ids", ["bedroom", "hall", "bathroom", "hall", "bedroom", "hall"]
            ),
            "source_route_visit_count_exceeds_2n_minus_1",
        ),
        (
            lambda payload: payload.__setitem__("route_room_ids", ["bedroom", "hall", "hall", "bathroom"]),
            "source_consecutive_route_room_ids_forbidden",
        ),
        (
            lambda payload: payload["portals"].append(  # type: ignore[union-attr]
                {
                    "portal_id": "portal:bedroom-hall",
                    "from_room_id": "hall",
                    "to_room_id": "bedroom",
                    "walkable": True,
                }
            ),
            "source_portal_ids_must_be_unique",
        ),
        (
            lambda payload: payload["portals"].append(  # type: ignore[union-attr]
                {
                    "portal_id": "portal:self",
                    "from_room_id": "hall",
                    "to_room_id": "hall",
                    "walkable": True,
                }
            ),
            "source_self_portal_forbidden",
        ),
        (
            lambda payload: payload.__setitem__("portals", []),
            "source_route_transition_has_no_portal",
        ),
    ],
)
def test_source_route_rejects_malicious_bounded_shapes(mutation: Callable[[dict[str, object]], None], reason: str) -> None:
    payload = _revisit_source_payload()
    mutation(payload)
    with pytest.raises(ValidationError, match=reason):
        GovernedSpatialSourcePacketV1.model_validate(payload)


def test_key_record_rejects_malformed_revocation_and_public_key() -> None:
    with pytest.raises(KeyRegistryError, match="ed25519_public_key_size"):
        Ed25519KeyRecord(
            issuer=ISSUER,
            environment=ENVIRONMENT,
            key_ref="bad-key",
            key_epoch=1,
            public_key_bytes=b"short",
            not_before="2026-07-01T00:00:00Z",
            not_after="2026-08-01T00:00:00Z",
        )
    with pytest.raises(KeyRegistryError, match="revoked_key_evidence_required"):
        Ed25519KeyRecord(
            issuer=ISSUER,
            environment=ENVIRONMENT,
            key_ref="revoked-key",
            key_epoch=1,
            public_key_bytes=_signer().key_record.public_key_bytes,
            not_before="2026-07-01T00:00:00Z",
            not_after="2026-08-01T00:00:00Z",
            state="revoked",
        )
