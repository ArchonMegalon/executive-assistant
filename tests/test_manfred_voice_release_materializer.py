from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
from types import ModuleType

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import pytest

from app.services.manfred_voice_signing import (
    MANFRED_TTS_MODEL,
    MANFRED_TTS_PROVIDER,
    reference_aggregate_sha256,
    verify_signed_receipt,
)
from app.services.memorial_release_policy import evaluate_memorial_voice_release


ROOT = Path(__file__).resolve().parents[1]
RELEASE_SCRIPT = ROOT / "scripts" / "materialize_manfred_voice_release.py"
AUTHORITY_SCRIPT = ROOT / "scripts" / "materialize_manfred_voice_authority.py"
SOURCE_REVISION = "a" * 40
SOURCE_FINGERPRINT = "b" * 64
PUBLIC_ORIGIN = "https://myexternalbrain.com"
IMAGE_ID = f"sha256:{'c' * 64}"
VOICE_CONFIG_SHA256 = "d" * 64
VOICE_MANIFEST_SHA256 = "e" * 64
VOICE_REFERENCE_AGGREGATE_SHA256 = "f" * 64
PROVIDER_VOICE_ID_SHA256 = "1" * 64
NOW = datetime(2026, 7, 23, 8, 0, tzinfo=UTC)


def test_hosted_clone_empty_reference_aggregate_is_canonical() -> None:
    assert reference_aggregate_sha256([]) == hashlib.sha256(b"[]").hexdigest()


def test_release_requires_all_room_spoken_turn_and_voice_quality_checks(
    modules: tuple[ModuleType, ModuleType],
) -> None:
    release, _authority = modules

    assert release.ROOM_AND_SPOKEN_TURN_CHECK_IDS == (
        "actual_device_checked",
        "actual_speaker_checked",
        "first_syllable_not_clipped",
        "intelligibility_confirmed",
        "answer_text_fallback_visible",
        "no_internet_search_confirmed",
        "normal_spoken_turn_confirmed",
        "interruption_behavior_confirmed",
        "retry_path_confirmed",
        "likeness_accepted",
        "warmth_accepted",
        "pronunciation_accepted",
    )


def _module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def modules() -> tuple[ModuleType, ModuleType]:
    release = _module(RELEASE_SCRIPT, "materialize_manfred_voice_release")
    authority = _module(AUTHORITY_SCRIPT, "materialize_manfred_voice_authority")
    return release, authority


@pytest.fixture
def signing_paths(
    tmp_path: Path,
) -> tuple[Ed25519PrivateKey, Path, Path]:
    private_key = Ed25519PrivateKey.generate()
    private_path = tmp_path / "voice-signing-private.pem"
    private_path.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    private_path.chmod(0o600)
    public_path = tmp_path / "voice-signing-public.pem"
    public_path.write_bytes(
        private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    public_path.chmod(0o600)
    return private_key, private_path, public_path


def _timestamp(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write_private(path: Path, payload: dict[str, object]) -> bytes:
    rendered = (
        json.dumps(
            payload,
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    path.write_bytes(rendered)
    path.chmod(0o600)
    return rendered


def _readiness(
    module: ModuleType,
    *,
    generated_at: datetime = NOW - timedelta(minutes=10),
) -> dict[str, object]:
    evidence = {
        key: {
            "contract_valid": True,
            "fresh": True,
            "present": True,
            "raw_credentials_exposed": False,
            "raw_private_context_exposed": False,
            "raw_receipt_payload_exposed": False,
            "raw_transcript_fields_exposed": False,
            "receipt_sha256": hashlib.sha256(key.encode("utf-8")).hexdigest(),
            "source_state_matches_current": True,
        }
        for key in module.READINESS_EVIDENCE_KEYS
    }
    return {
        "blocked_checks": [],
        "contract_name": module.READINESS_CONTRACT,
        "evidence_source": "receipt_aggregation",
        "generated_at": _timestamp(generated_at),
        "generated_by": module.READINESS_GENERATOR,
        "goal_completion_claim_allowed": False,
        "head_semantics": "source_state",
        "input_evidence": evidence,
        "premium_spoken_claim_allowed": False,
        "privacy": {
            "candidate_raw_text_fields": False,
            "raw_private_context_exposed": False,
            "raw_transcript_fields": False,
            "redacted_text_fields": True,
        },
        "ready_for_realtime_conversation_review": True,
        "realtime_conversation_claim_allowed": False,
        "source_git_head": SOURCE_REVISION,
        "source_state_fingerprint": SOURCE_FINGERPRINT,
        "source_state_fingerprint_semantics": (
            module.SOURCE_FINGERPRINT_SEMANTICS
        ),
        "status": "ready_for_realtime_conversation_review",
    }


def _voice_kwargs() -> dict[str, str]:
    return {
        "provider_voice_id_sha256": PROVIDER_VOICE_ID_SHA256,
        "tts_model": MANFRED_TTS_MODEL,
        "tts_provider": MANFRED_TTS_PROVIDER,
        "voice_config_sha256": VOICE_CONFIG_SHA256,
        "voice_manifest_sha256": VOICE_MANIFEST_SHA256,
        "voice_reference_aggregate_sha256": (
            VOICE_REFERENCE_AGGREGATE_SHA256
        ),
    }


def _operator(
    module: ModuleType,
    *,
    generated_at: datetime = NOW - timedelta(minutes=5),
) -> dict[str, object]:
    voice_binding = module._expected_voice_binding(**_voice_kwargs())
    return {
        "accepted": True,
        "checks": {
            check_id: True for check_id in module.ROOM_AND_SPOKEN_TURN_CHECK_IDS
        },
        "contract_name": module.OPERATOR_ACCEPTANCE_CONTRACT,
        "deployed_source_revision": SOURCE_REVISION,
        "generated_at": _timestamp(generated_at),
        "image_id": IMAGE_ID,
        "image_id_semantics": module.IMAGE_ID_SEMANTICS,
        "memorial_slug": "manfred",
        "native_realtime_claim_accepted": False,
        "public_origin": PUBLIC_ORIGIN,
        "review_surface": module.MANFRED_PHASE_1_LIVE_REVIEW_SURFACE,
        "reviewer_ref_sha256": "3" * 64,
        "reviewer_ref_sha256_semantics": (
            module.REVIEWER_REF_SHA256_SEMANTICS
        ),
        "spoken_turn_claim_accepted": True,
        **voice_binding,
    }


def _inputs(
    tmp_path: Path,
    release: ModuleType,
    authority: ModuleType,
    *,
    private_path: Path,
    public_path: Path,
    now: datetime = NOW,
) -> tuple[dict[str, Path], dict[str, dict[str, object]], dict[str, bytes]]:
    paths = {
        "readiness": tmp_path / "readiness.json",
        "operator": tmp_path / "operator.json",
        "authority": tmp_path / "authority.json",
        "output": tmp_path / "release.json",
    }
    payloads = {
        "readiness": _readiness(
            release,
            generated_at=now - timedelta(minutes=10),
        ),
        "operator": _operator(
            release,
            generated_at=now - timedelta(minutes=5),
        ),
    }
    raw = {
        name: _write_private(paths[name], payload)
        for name, payload in payloads.items()
    }
    payloads["authority"] = authority.materialize_manfred_voice_authority(
        signing_private_key_path=private_path,
        trusted_public_key_path=public_path,
        output_path=paths["authority"],
        attestor_ref_sha256="2" * 64,
        confirmation=authority.AUTHORITY_CONFIRMATION,
        now=now - timedelta(days=30),
        **_voice_kwargs(),
    )
    raw["authority"] = paths["authority"].read_bytes()
    return paths, payloads, raw


def _materialize(
    module: ModuleType,
    paths: dict[str, Path],
    *,
    private_path: Path,
    public_path: Path,
    now: datetime = NOW,
    **overrides: object,
) -> dict[str, object]:
    kwargs: dict[str, object] = {
        "readiness_receipt_path": paths["readiness"],
        "operator_acceptance_receipt_path": paths["operator"],
        "voice_authority_receipt_path": paths["authority"],
        "signing_private_key_path": private_path,
        "trusted_public_key_path": public_path,
        "output_path": paths["output"],
        "source_revision": SOURCE_REVISION,
        "public_origin": PUBLIC_ORIGIN,
        "image_id": IMAGE_ID,
        "now": now,
        **_voice_kwargs(),
    }
    kwargs.update(overrides)
    return module.materialize_manfred_voice_release(**kwargs)


def _policy_kwargs(public_path: Path) -> dict[str, object]:
    return {
        "expected_source_revision": SOURCE_REVISION,
        "expected_public_origin": PUBLIC_ORIGIN,
        "expected_image_id": IMAGE_ID,
        "expected_voice_config_sha256": VOICE_CONFIG_SHA256,
        "expected_voice_manifest_sha256": VOICE_MANIFEST_SHA256,
        "expected_voice_reference_aggregate_sha256": (
            VOICE_REFERENCE_AGGREGATE_SHA256
        ),
        "expected_provider_voice_id_sha256": PROVIDER_VOICE_ID_SHA256,
        "expected_tts_provider": MANFRED_TTS_PROVIDER,
        "expected_tts_model": MANFRED_TTS_MODEL,
        "trusted_public_key_path": public_path,
        "now": NOW.timestamp(),
    }


def test_materializes_signed_image_and_voice_bound_spoken_turn_release(
    tmp_path: Path,
    modules: tuple[ModuleType, ModuleType],
    signing_paths: tuple[Ed25519PrivateKey, Path, Path],
) -> None:
    release_module, authority_module = modules
    _private_key, private_path, public_path = signing_paths
    paths, _payloads, raw = _inputs(
        tmp_path,
        release_module,
        authority_module,
        private_path=private_path,
        public_path=public_path,
    )

    release = _materialize(
        release_module,
        paths,
        private_path=private_path,
        public_path=public_path,
    )

    assert release["contract_name"] == "ea.manfred_voice_release.v2"
    assert release["status"] == "released"
    assert release["image_id"] == IMAGE_ID
    assert release["spoken_turn_claim_allowed"] is True
    assert release["native_realtime_claim_allowed"] is False
    assert release["operator_acceptance_review_surface"] == (
        release_module.MANFRED_PHASE_1_LIVE_REVIEW_SURFACE
    )
    assert release["tts_provider"] == "unmixr_clone"
    assert release["tts_model"] == "unmixr"
    assert release["blocked_checks"] == []
    operator_payload = json.loads(
        paths["operator"].read_text(encoding="utf-8")
    )
    assert operator_payload["reviewer_ref_sha256"] == "3" * 64
    assert operator_payload["reviewer_ref_sha256_semantics"] == (
        "sha256_utf8_pseudonymous_operator_reference_v1"
    )
    authority_payload = json.loads(paths["authority"].read_text(encoding="utf-8"))
    assert authority_payload["attestor_ref_sha256_semantics"] == (
        "sha256_utf8_pseudonymous_authority_reference_v1"
    )
    assert (
        release["readiness_receipt_sha256"]
        == hashlib.sha256(raw["readiness"]).hexdigest()
    )
    assert (
        release["operator_acceptance_receipt_sha256"]
        == hashlib.sha256(raw["operator"]).hexdigest()
    )
    assert (
        release["voice_authority_receipt_sha256"]
        == hashlib.sha256(raw["authority"]).hexdigest()
    )
    verify_signed_receipt(release, trusted_public_key_path=public_path)
    assert stat.S_IMODE(paths["output"].stat().st_mode) == 0o600
    assert evaluate_memorial_voice_release(
        slug="manfred",
        receipt_path=paths["output"],
        **_policy_kwargs(public_path),
    )["allowed"] is True


def test_authority_requires_explicit_confirmation_and_trusted_signer(
    tmp_path: Path,
    modules: tuple[ModuleType, ModuleType],
    signing_paths: tuple[Ed25519PrivateKey, Path, Path],
) -> None:
    release_module, authority_module = modules
    _private_key, private_path, public_path = signing_paths

    with pytest.raises(
        release_module.VoiceReleaseError,
        match="voice_authority_confirmation_missing",
    ):
        authority_module.materialize_manfred_voice_authority(
            signing_private_key_path=private_path,
            trusted_public_key_path=public_path,
            output_path=tmp_path / "authority.json",
            attestor_ref_sha256="2" * 64,
            confirmation="yes",
            now=NOW,
            **_voice_kwargs(),
        )

    other_private = Ed25519PrivateKey.generate()
    other_path = tmp_path / "other-private.pem"
    other_path.write_bytes(
        other_private.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    other_path.chmod(0o600)
    with pytest.raises(
        release_module.VoiceReleaseError,
        match="signing_private_key_untrusted",
    ):
        authority_module.materialize_manfred_voice_authority(
            signing_private_key_path=other_path,
            trusted_public_key_path=public_path,
            output_path=tmp_path / "authority.json",
            attestor_ref_sha256="2" * 64,
            confirmation=authority_module.AUTHORITY_CONFIRMATION,
            now=NOW,
            **_voice_kwargs(),
        )


def test_release_rejects_tampered_signed_authority(
    tmp_path: Path,
    modules: tuple[ModuleType, ModuleType],
    signing_paths: tuple[Ed25519PrivateKey, Path, Path],
) -> None:
    release_module, authority_module = modules
    _private_key, private_path, public_path = signing_paths
    paths, payloads, _raw = _inputs(
        tmp_path,
        release_module,
        authority_module,
        private_path=private_path,
        public_path=public_path,
    )
    authority = deepcopy(payloads["authority"])
    authority["public_synthetic_voice_authorized"] = False
    _write_private(paths["authority"], authority)

    with pytest.raises(
        release_module.VoiceReleaseError,
        match="voice_authority_signature_invalid",
    ):
        _materialize(
            release_module,
            paths,
            private_path=private_path,
            public_path=public_path,
        )
    assert not paths["output"].exists()


@pytest.mark.parametrize(
    ("case", "reason"),
    [
        ("operator_image", "operator_acceptance_image_id_mismatch"),
        ("operator_manifest", "operator_acceptance_voice_mismatch"),
        ("operator_native_true", "operator_acceptance_native_realtime_invalid"),
        ("operator_accepted_int", "operator_acceptance_missing"),
        ("operator_checks_int", "operator_acceptance_check_failed"),
        (
            "operator_review_surface",
            "operator_acceptance_review_surface_invalid",
        ),
        ("operator_reviewer_ref", "operator_acceptance_reviewer_ref_invalid"),
        (
            "operator_reviewer_semantics",
            "operator_acceptance_reviewer_ref_semantics_invalid",
        ),
        ("authority_voice_mismatch", "voice_authority_signature_invalid"),
        ("readiness_stale", "readiness_generated_at_stale"),
    ],
)
def test_release_fails_closed_on_unbound_or_wrongly_typed_inputs(
    tmp_path: Path,
    modules: tuple[ModuleType, ModuleType],
    signing_paths: tuple[Ed25519PrivateKey, Path, Path],
    case: str,
    reason: str,
) -> None:
    release_module, authority_module = modules
    _private_key, private_path, public_path = signing_paths
    paths, payloads, _raw = _inputs(
        tmp_path,
        release_module,
        authority_module,
        private_path=private_path,
        public_path=public_path,
    )
    readiness = deepcopy(payloads["readiness"])
    operator = deepcopy(payloads["operator"])
    authority = deepcopy(payloads["authority"])
    if case == "operator_image":
        operator["image_id"] = f"sha256:{'9' * 64}"
    elif case == "operator_manifest":
        operator["voice_manifest_sha256"] = "9" * 64
    elif case == "operator_native_true":
        operator["native_realtime_claim_accepted"] = True
    elif case == "operator_accepted_int":
        operator["accepted"] = 1
    elif case == "operator_checks_int":
        checks = operator["checks"]
        assert isinstance(checks, dict)
        checks["retry_path_confirmed"] = 1
    elif case == "operator_review_surface":
        operator["review_surface"] = "candidate"
    elif case == "operator_reviewer_ref":
        operator["reviewer_ref_sha256"] = "not-a-sha256"
    elif case == "operator_reviewer_semantics":
        operator["reviewer_ref_sha256_semantics"] = "sha256_unspecified"
    elif case == "authority_voice_mismatch":
        authority["voice_manifest_sha256"] = "9" * 64
    elif case == "readiness_stale":
        readiness["generated_at"] = _timestamp(NOW - timedelta(days=2))
    else:  # pragma: no cover
        raise AssertionError(case)
    _write_private(paths["readiness"], readiness)
    _write_private(paths["operator"], operator)
    _write_private(paths["authority"], authority)

    with pytest.raises(release_module.VoiceReleaseError, match=reason):
        _materialize(
            release_module,
            paths,
            private_path=private_path,
            public_path=public_path,
        )
    assert not paths["output"].exists()


def test_private_inputs_reject_links_permissions_and_output_alias(
    tmp_path: Path,
    modules: tuple[ModuleType, ModuleType],
    signing_paths: tuple[Ed25519PrivateKey, Path, Path],
) -> None:
    release_module, authority_module = modules
    _private_key, private_path, public_path = signing_paths
    paths, _payloads, _raw = _inputs(
        tmp_path,
        release_module,
        authority_module,
        private_path=private_path,
        public_path=public_path,
    )

    paths["readiness"].chmod(0o640)
    with pytest.raises(
        release_module.VoiceReleaseError,
        match="readiness_receipt_permissions_invalid",
    ):
        _materialize(
            release_module,
            paths,
            private_path=private_path,
            public_path=public_path,
        )
    paths["readiness"].chmod(0o600)

    alias = tmp_path / "readiness-alias.json"
    os.link(paths["readiness"], alias)
    with pytest.raises(
        release_module.VoiceReleaseError,
        match="readiness_receipt_multiply_linked",
    ):
        _materialize(
            release_module,
            paths,
            private_path=private_path,
            public_path=public_path,
        )
    alias.unlink()

    with pytest.raises(
        release_module.VoiceReleaseError,
        match="release_paths_not_distinct",
    ):
        _materialize(
            release_module,
            paths,
            private_path=private_path,
            public_path=public_path,
            output_path=paths["operator"],
        )


def test_trusted_public_key_exact_output_path_is_rejected(
    tmp_path: Path,
    modules: tuple[ModuleType, ModuleType],
    signing_paths: tuple[Ed25519PrivateKey, Path, Path],
) -> None:
    release_module, authority_module = modules
    _private_key, private_path, public_path = signing_paths
    public_bytes = public_path.read_bytes()

    with pytest.raises(
        release_module.VoiceReleaseError,
        match="voice_authority_paths_not_distinct",
    ):
        authority_module.materialize_manfred_voice_authority(
            signing_private_key_path=private_path,
            trusted_public_key_path=public_path,
            output_path=public_path,
            attestor_ref_sha256="2" * 64,
            confirmation=authority_module.AUTHORITY_CONFIRMATION,
            now=NOW,
            **_voice_kwargs(),
        )
    assert public_path.read_bytes() == public_bytes

    paths, _payloads, _raw = _inputs(
        tmp_path,
        release_module,
        authority_module,
        private_path=private_path,
        public_path=public_path,
    )
    with pytest.raises(
        release_module.VoiceReleaseError,
        match="release_paths_not_distinct",
    ):
        _materialize(
            release_module,
            paths,
            private_path=private_path,
            public_path=public_path,
            output_path=public_path,
        )
    assert public_path.read_bytes() == public_bytes


def test_read_only_trusted_public_key_mode_remains_supported(
    tmp_path: Path,
    modules: tuple[ModuleType, ModuleType],
    signing_paths: tuple[Ed25519PrivateKey, Path, Path],
) -> None:
    release_module, authority_module = modules
    _private_key, private_path, public_path = signing_paths
    public_path.chmod(0o644)
    paths, _payloads, _raw = _inputs(
        tmp_path,
        release_module,
        authority_module,
        private_path=private_path,
        public_path=public_path,
    )

    release = _materialize(
        release_module,
        paths,
        private_path=private_path,
        public_path=public_path,
    )

    assert release["status"] == "released"
    assert stat.S_IMODE(public_path.stat().st_mode) == 0o644


def test_authority_rejects_trusted_public_key_hardlink_identity_at_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    modules: tuple[ModuleType, ModuleType],
    signing_paths: tuple[Ed25519PrivateKey, Path, Path],
) -> None:
    release_module, authority_module = modules
    _private_key, private_path, public_path = signing_paths
    output_path = tmp_path / "authority.json"
    public_bytes = public_path.read_bytes()
    real_sign_receipt = authority_module.sign_receipt

    def move_trusted_key_to_output(
        payload: dict[str, object],
        *,
        private_key: Ed25519PrivateKey,
    ) -> dict[str, object]:
        receipt = real_sign_receipt(payload, private_key=private_key)
        os.link(public_path, output_path)
        public_path.unlink()
        return receipt

    monkeypatch.setattr(
        authority_module,
        "sign_receipt",
        move_trusted_key_to_output,
    )
    with pytest.raises(
        release_module.VoiceReleaseError,
        match="release_output_matches_input",
    ):
        authority_module.materialize_manfred_voice_authority(
            signing_private_key_path=private_path,
            trusted_public_key_path=public_path,
            output_path=output_path,
            attestor_ref_sha256="2" * 64,
            confirmation=authority_module.AUTHORITY_CONFIRMATION,
            now=NOW,
            **_voice_kwargs(),
        )
    assert output_path.read_bytes() == public_bytes


def test_release_rejects_trusted_public_key_hardlink_identity_at_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    modules: tuple[ModuleType, ModuleType],
    signing_paths: tuple[Ed25519PrivateKey, Path, Path],
) -> None:
    release_module, authority_module = modules
    _private_key, private_path, public_path = signing_paths
    public_bytes = public_path.read_bytes()
    paths, _payloads, _raw = _inputs(
        tmp_path,
        release_module,
        authority_module,
        private_path=private_path,
        public_path=public_path,
    )
    real_sign_receipt = release_module.sign_receipt

    def move_trusted_key_to_output(
        payload: dict[str, object],
        *,
        private_key: Ed25519PrivateKey,
    ) -> dict[str, object]:
        receipt = real_sign_receipt(payload, private_key=private_key)
        os.link(public_path, paths["output"])
        public_path.unlink()
        return receipt

    monkeypatch.setattr(
        release_module,
        "sign_receipt",
        move_trusted_key_to_output,
    )
    with pytest.raises(
        release_module.VoiceReleaseError,
        match="release_output_matches_input",
    ):
        _materialize(
            release_module,
            paths,
            private_path=private_path,
            public_path=public_path,
        )
    assert paths["output"].read_bytes() == public_bytes


def test_output_parent_must_be_owner_controlled(
    tmp_path: Path,
    modules: tuple[ModuleType, ModuleType],
    signing_paths: tuple[Ed25519PrivateKey, Path, Path],
) -> None:
    release_module, authority_module = modules
    _private_key, private_path, public_path = signing_paths
    inputs_dir = tmp_path / "inputs"
    inputs_dir.mkdir(mode=0o700)
    paths, _payloads, _raw = _inputs(
        inputs_dir,
        release_module,
        authority_module,
        private_path=private_path,
        public_path=public_path,
    )
    unsafe_dir = tmp_path / "unsafe"
    unsafe_dir.mkdir(mode=0o777)
    unsafe_dir.chmod(0o777)
    paths["output"] = unsafe_dir / "release.json"

    with pytest.raises(
        release_module.VoiceReleaseError,
        match="release_output_path_unsafe",
    ):
        _materialize(
            release_module,
            paths,
            private_path=private_path,
            public_path=public_path,
        )
    assert not paths["output"].exists()


def test_atomic_install_keeps_temp_descriptor_open_through_rename_and_verify(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    modules: tuple[ModuleType, ModuleType],
    signing_paths: tuple[Ed25519PrivateKey, Path, Path],
) -> None:
    release_module, authority_module = modules
    _private_key, private_path, public_path = signing_paths
    paths, _payloads, _raw = _inputs(
        tmp_path,
        release_module,
        authority_module,
        private_path=private_path,
        public_path=public_path,
    )
    real_replace = release_module.os.replace
    observed_open_descriptor = False

    def checked_replace(
        source: str,
        destination: str,
        *,
        src_dir_fd: int,
        dst_dir_fd: int,
    ) -> None:
        nonlocal observed_open_descriptor
        real_replace(
            source,
            destination,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
        )
        destination_stat = os.stat(destination, dir_fd=dst_dir_fd)
        for descriptor_name in os.listdir("/proc/self/fd"):
            try:
                descriptor = int(descriptor_name)
                metadata = os.fstat(descriptor)
            except (OSError, ValueError):
                continue
            if (
                metadata.st_dev == destination_stat.st_dev
                and metadata.st_ino == destination_stat.st_ino
            ):
                observed_open_descriptor = True
                break

    monkeypatch.setattr(release_module.os, "replace", checked_replace)
    _materialize(
        release_module,
        paths,
        private_path=private_path,
        public_path=public_path,
    )
    assert observed_open_descriptor is True


def test_signing_private_key_is_never_written_to_receipts(
    tmp_path: Path,
    modules: tuple[ModuleType, ModuleType],
    signing_paths: tuple[Ed25519PrivateKey, Path, Path],
) -> None:
    release_module, authority_module = modules
    _private_key, private_path, public_path = signing_paths
    private_bytes = private_path.read_bytes()
    paths, _payloads, _raw = _inputs(
        tmp_path,
        release_module,
        authority_module,
        private_path=private_path,
        public_path=public_path,
    )
    _materialize(
        release_module,
        paths,
        private_path=private_path,
        public_path=public_path,
    )
    assert private_bytes not in paths["authority"].read_bytes()
    assert private_bytes not in paths["output"].read_bytes()
    assert stat.S_IMODE(private_path.stat().st_mode) == 0o600
