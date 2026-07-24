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
    verify_signed_receipt,
)
from app.services.memorial_release_policy import (
    MANFRED_VOICE_PUBLIC_EVALUATION_FIELDS,
    MANFRED_VOICE_PUBLIC_EVALUATION_MANUAL_CHECK_IDS,
)


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (
    ROOT
    / "scripts"
    / "materialize_manfred_voice_public_evaluation_release.py"
)
AUTHORITY_SCRIPT = (
    ROOT / "scripts" / "materialize_manfred_voice_authority.py"
)
DEPLOYED_SOURCE_REVISION = "a" * 40
READINESS_SOURCE_REVISION = "9" * 40
SOURCE_FINGERPRINT = "b" * 64
CURRENT_SOURCE_FINGERPRINT = "6" * 64
PUBLIC_ORIGIN = "https://myexternalbrain.com"
IMAGE_ID = f"sha256:{'c' * 64}"
VOICE_CONFIG_SHA256 = "d" * 64
VOICE_MANIFEST_SHA256 = "e" * 64
VOICE_REFERENCE_AGGREGATE_SHA256 = "f" * 64
PROVIDER_VOICE_ID_SHA256 = "1" * 64
AUTHORIZATION_REF_SHA256 = "2" * 64
NOW = datetime(2026, 7, 24, 14, 0, tzinfo=UTC)
BLOCKED_CHECKS = [
    "real_captured_stt_fixture_ready",
    "captured_candidate_diagnostic_clean",
    "automated_voice_browser_tts_ready",
    "room_audio_receipt_passed",
    "manual_room_checks_confirmed",
]
CURRENT_EVIDENCE_KEYS = {
    "realtime_browser",
    "room_audio_attestation_packet",
    "voice_roundtrip",
}
UNVERIFIED_EVIDENCE_KEYS = [
    "captured_candidate_diagnostic",
    "room_audio",
    "stt_benchmark",
    "stt_candidate",
    "stt_captured_benchmark",
]


def _load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def modules() -> tuple[ModuleType, ModuleType]:
    evaluation = _load_module(
        SCRIPT,
        "materialize_manfred_voice_public_evaluation_release",
    )
    authority = _load_module(
        AUTHORITY_SCRIPT,
        "materialize_manfred_voice_authority_for_public_evaluation",
    )
    return evaluation, authority


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


def _readiness(module: ModuleType) -> dict[str, object]:
    evidence: dict[str, dict[str, object]] = {}
    for key in module.READINESS_EVIDENCE_KEYS:
        current = key in CURRENT_EVIDENCE_KEYS
        evidence[key] = {
            "contract_valid": current,
            "fresh": current,
            "present": current,
            "raw_credentials_exposed": False,
            "raw_private_context_exposed": False,
            "raw_receipt_payload_exposed": False,
            "raw_transcript_fields_exposed": False,
            "receipt_sha256": (
                hashlib.sha256(key.encode("utf-8")).hexdigest()
                if current
                else ""
            ),
            "source_state_matches_current": current,
            "status": "pass" if current else "missing",
        }
    return {
        "blocked_checks": list(BLOCKED_CHECKS),
        "contract_name": module.READINESS_CONTRACT,
        "evidence_source": "receipt_aggregation",
        "generated_at": _timestamp(NOW - timedelta(minutes=10)),
        "generated_by": module.READINESS_GENERATOR,
        "goal_completion_claim_allowed": False,
        "head_semantics": "source_state",
        "input_evidence": evidence,
        "premium_spoken_claim_allowed": False,
        "privacy": dict(module.EXPECTED_READINESS_PRIVACY),
        "ready_for_realtime_conversation_review": False,
        "realtime_conversation_claim_allowed": False,
        "source_git_head": READINESS_SOURCE_REVISION,
        "source_state_fingerprint": SOURCE_FINGERPRINT,
        "source_state_fingerprint_semantics": (
            module.SOURCE_FINGERPRINT_SEMANTICS
        ),
        "status": "blocked_realtime_prerequisites",
    }


def _inputs(
    tmp_path: Path,
    evaluation: ModuleType,
    authority: ModuleType,
    *,
    private_path: Path,
    public_path: Path,
) -> tuple[dict[str, Path], dict[str, object], bytes]:
    paths = {
        "readiness": tmp_path / "readiness.json",
        "authority": tmp_path / "authority.json",
        "output": tmp_path / "release.json",
    }
    readiness = _readiness(evaluation)
    readiness_raw = _write_private(paths["readiness"], readiness)
    authority.materialize_manfred_voice_authority(
        signing_private_key_path=private_path,
        trusted_public_key_path=public_path,
        output_path=paths["authority"],
        attestor_ref_sha256="3" * 64,
        confirmation=authority.AUTHORITY_CONFIRMATION,
        now=NOW - timedelta(days=30),
        **_voice_kwargs(),
    )
    return paths, readiness, readiness_raw


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
        "voice_authority_receipt_path": paths["authority"],
        "signing_private_key_path": private_path,
        "trusted_public_key_path": public_path,
        "output_path": paths["output"],
        "source_revision": DEPLOYED_SOURCE_REVISION,
        "public_origin": PUBLIC_ORIGIN,
        "image_id": IMAGE_ID,
        "authorization_ref_sha256": AUTHORIZATION_REF_SHA256,
        "confirmation": module.PUBLIC_EVALUATION_CONFIRMATION,
        "now": now,
        **_voice_kwargs(),
    }
    kwargs.update(overrides)
    original = module._current_source_fingerprint
    module._current_source_fingerprint = (
        lambda _source_revision: CURRENT_SOURCE_FINGERPRINT
    )
    try:
        return module.materialize_manfred_voice_public_evaluation_release(
            **kwargs
        )
    finally:
        module._current_source_fingerprint = original


def test_materializes_signed_owner_authorized_public_evaluation_without_false_pass_claims(
    tmp_path: Path,
    modules: tuple[ModuleType, ModuleType],
    signing_paths: tuple[Ed25519PrivateKey, Path, Path],
) -> None:
    evaluation, authority = modules
    _private_key, private_path, public_path = signing_paths
    private_key_bytes = private_path.read_bytes()
    paths, _readiness_payload, readiness_raw = _inputs(
        tmp_path,
        evaluation,
        authority,
        private_path=private_path,
        public_path=public_path,
    )

    release = _materialize(
        evaluation,
        paths,
        private_path=private_path,
        public_path=public_path,
    )

    assert set(release) == MANFRED_VOICE_PUBLIC_EVALUATION_FIELDS
    assert release["contract_name"] == (
        "ea.manfred_voice_public_evaluation_release.v1"
    )
    assert release["status"] == "public_evaluation_authorized"
    assert release["release_mode"] == "owner_authorized_public_evaluation"
    assert release["generated_at"] == "2026-07-24T14:00:00Z"
    assert release["expires_at"] == "2026-07-31T14:00:00Z"
    assert release["revoked"] is False
    assert release["source_revision"] == DEPLOYED_SOURCE_REVISION
    assert release["source_git_head"] == DEPLOYED_SOURCE_REVISION
    assert release["source_state_fingerprint"] == CURRENT_SOURCE_FINGERPRINT
    assert (
        release["baseline_readiness_source_revision"]
        == READINESS_SOURCE_REVISION
    )
    assert release["baseline_readiness_same_source_revision"] is False
    assert (
        release["baseline_readiness_status"]
        == "blocked_realtime_prerequisites"
    )
    assert release["blocked_checks"] == BLOCKED_CHECKS
    assert release["unverified_evidence_keys"] == UNVERIFIED_EVIDENCE_KEYS
    assert release["unverified_manual_check_ids"] == list(
        MANFRED_VOICE_PUBLIC_EVALUATION_MANUAL_CHECK_IDS
    )
    assert release[
        "baseline_readiness_receipt_sha256"
    ] == hashlib.sha256(readiness_raw).hexdigest()

    for field in (
        "goal_completion_claim_allowed",
        "native_realtime_claim_allowed",
        "operator_acceptance_verified",
        "premium_spoken_claim_allowed",
        "readiness_prerequisites_satisfied",
        "realtime_conversation_claim_allowed",
        "room_and_spoken_turn_checks_verified",
        "spoken_turn_claim_allowed",
    ):
        assert release[field] is False
    for field in (
        "conversational_use_authorized",
        "public_evaluation_allowed",
        "public_evaluation_disclosure_required",
        "public_synthetic_voice_authorized",
        "baseline_readiness_receipt_contract_verified",
        "runtime_enablement_allowed",
        "source_material_authorized",
        "voice_authority_verified",
    ):
        assert release[field] is True

    verify_signed_receipt(
        release,
        trusted_public_key_path=public_path,
    )
    assert paths["output"].exists()
    assert stat.S_IMODE(paths["output"].stat().st_mode) == 0o600
    assert paths["output"].stat().st_nlink == 1
    installed = paths["output"].read_bytes()
    assert private_key_bytes not in installed
    assert (
        evaluation.PUBLIC_EVALUATION_CONFIRMATION.encode("utf-8")
        not in installed
    )
    assert "operator_acceptance_receipt_sha256" not in release
    for ambiguous_legacy_field in (
        "readiness_receipt_sha256",
        "readiness_receipt_verified",
        "readiness_source_revision",
        "readiness_status",
    ):
        assert ambiguous_legacy_field not in release


def test_same_source_revision_is_derived_from_exact_baseline_comparison(
    tmp_path: Path,
    modules: tuple[ModuleType, ModuleType],
    signing_paths: tuple[Ed25519PrivateKey, Path, Path],
) -> None:
    evaluation, authority = modules
    _private_key, private_path, public_path = signing_paths
    paths, readiness, _readiness_raw = _inputs(
        tmp_path,
        evaluation,
        authority,
        private_path=private_path,
        public_path=public_path,
    )
    same_revision = deepcopy(readiness)
    same_revision["source_git_head"] = DEPLOYED_SOURCE_REVISION
    _write_private(paths["readiness"], same_revision)

    release = _materialize(
        evaluation,
        paths,
        private_path=private_path,
        public_path=public_path,
    )

    assert (
        release["baseline_readiness_source_revision"]
        == DEPLOYED_SOURCE_REVISION
    )
    assert release["baseline_readiness_same_source_revision"] is True
    assert release["readiness_prerequisites_satisfied"] is False


@pytest.mark.parametrize(
    ("overrides", "reason"),
    (
        (
            {"confirmation": "yes"},
            "public_evaluation_confirmation_missing",
        ),
        (
            {"authorization_ref_sha256": "not-a-digest"},
            "public_evaluation_authorization_ref_invalid",
        ),
        (
            {"tts_provider": "other-provider"},
            "public_evaluation_tts_identity_invalid",
        ),
    ),
)
def test_requires_exact_confirmation_authorization_and_voice_identity(
    tmp_path: Path,
    modules: tuple[ModuleType, ModuleType],
    signing_paths: tuple[Ed25519PrivateKey, Path, Path],
    overrides: dict[str, object],
    reason: str,
) -> None:
    evaluation, authority = modules
    _private_key, private_path, public_path = signing_paths
    paths, _readiness_payload, _readiness_raw = _inputs(
        tmp_path,
        evaluation,
        authority,
        private_path=private_path,
        public_path=public_path,
    )

    with pytest.raises(evaluation.VoiceReleaseError, match=reason):
        _materialize(
            evaluation,
            paths,
            private_path=private_path,
            public_path=public_path,
            **overrides,
        )
    assert not paths["output"].exists()


@pytest.mark.parametrize(
    ("mutation", "reason"),
    (
        (
            lambda payload: payload.update(blocked_checks=[]),
            "readiness_blocked_checks_missing",
        ),
        (
            lambda payload: payload["blocked_checks"].append(
                "unsupported_check"
            ),
            "readiness_blocked_checks_unsupported",
        ),
        (
            lambda payload: payload.update(
                realtime_conversation_claim_allowed=True
            ),
            "readiness_evaluation_claim_invalid",
        ),
    ),
)
def test_rejects_blocker_or_claim_rewriting(
    tmp_path: Path,
    modules: tuple[ModuleType, ModuleType],
    signing_paths: tuple[Ed25519PrivateKey, Path, Path],
    mutation,
    reason: str,
) -> None:
    evaluation, authority = modules
    _private_key, private_path, public_path = signing_paths
    paths, readiness, _readiness_raw = _inputs(
        tmp_path,
        evaluation,
        authority,
        private_path=private_path,
        public_path=public_path,
    )
    mutated = deepcopy(readiness)
    mutation(mutated)
    _write_private(paths["readiness"], mutated)

    with pytest.raises(evaluation.VoiceReleaseError, match=reason):
        _materialize(
            evaluation,
            paths,
            private_path=private_path,
            public_path=public_path,
        )
    assert not paths["output"].exists()


def test_rejects_inconsistent_missing_evidence_instead_of_promoting_it(
    tmp_path: Path,
    modules: tuple[ModuleType, ModuleType],
    signing_paths: tuple[Ed25519PrivateKey, Path, Path],
) -> None:
    evaluation, authority = modules
    _private_key, private_path, public_path = signing_paths
    paths, readiness, _readiness_raw = _inputs(
        tmp_path,
        evaluation,
        authority,
        private_path=private_path,
        public_path=public_path,
    )
    mutated = deepcopy(readiness)
    evidence = mutated["input_evidence"]
    assert isinstance(evidence, dict)
    missing = evidence["stt_candidate"]
    assert isinstance(missing, dict)
    missing["contract_valid"] = True
    _write_private(paths["readiness"], mutated)

    with pytest.raises(
        evaluation.VoiceReleaseError,
        match=(
            "readiness_input_evidence_missing_inconsistent:"
            "stt_candidate"
        ),
    ):
        _materialize(
            evaluation,
            paths,
            private_path=private_path,
            public_path=public_path,
        )
    assert not paths["output"].exists()


def test_rejects_tampered_voice_authority(
    tmp_path: Path,
    modules: tuple[ModuleType, ModuleType],
    signing_paths: tuple[Ed25519PrivateKey, Path, Path],
) -> None:
    evaluation, authority = modules
    _private_key, private_path, public_path = signing_paths
    paths, _readiness, _readiness_raw = _inputs(
        tmp_path,
        evaluation,
        authority,
        private_path=private_path,
        public_path=public_path,
    )
    authority_payload = json.loads(
        paths["authority"].read_text(encoding="utf-8")
    )
    authority_payload["public_synthetic_voice_authorized"] = False
    _write_private(paths["authority"], authority_payload)

    with pytest.raises(
        evaluation.VoiceReleaseError,
        match="voice_authority_signature_invalid",
    ):
        _materialize(
            evaluation,
            paths,
            private_path=private_path,
            public_path=public_path,
        )
    assert not paths["output"].exists()


def test_private_inputs_and_output_must_be_distinct(
    tmp_path: Path,
    modules: tuple[ModuleType, ModuleType],
    signing_paths: tuple[Ed25519PrivateKey, Path, Path],
) -> None:
    evaluation, authority = modules
    _private_key, private_path, public_path = signing_paths
    paths, _readiness, _readiness_raw = _inputs(
        tmp_path,
        evaluation,
        authority,
        private_path=private_path,
        public_path=public_path,
    )

    with pytest.raises(
        evaluation.VoiceReleaseError,
        match="release_paths_not_distinct",
    ):
        _materialize(
            evaluation,
            paths,
            private_path=private_path,
            public_path=public_path,
            output_path=paths["readiness"],
        )
    assert paths["readiness"].exists()
    assert stat.S_IMODE(paths["readiness"].stat().st_mode) == 0o600


def test_cli_requires_the_explicit_public_evaluation_confirmation(
    tmp_path: Path,
    modules: tuple[ModuleType, ModuleType],
    signing_paths: tuple[Ed25519PrivateKey, Path, Path],
) -> None:
    evaluation, authority = modules
    _private_key, private_path, public_path = signing_paths
    paths, _readiness, _readiness_raw = _inputs(
        tmp_path,
        evaluation,
        authority,
        private_path=private_path,
        public_path=public_path,
    )

    result = evaluation.main(
        [
            "--readiness-receipt",
            str(paths["readiness"]),
            "--voice-authority-receipt",
            str(paths["authority"]),
            "--signing-private-key",
            str(private_path),
            "--trusted-public-key",
            str(public_path),
            "--output",
            str(paths["output"]),
            "--source-revision",
            DEPLOYED_SOURCE_REVISION,
            "--public-origin",
            PUBLIC_ORIGIN,
            "--image-id",
            IMAGE_ID,
            "--voice-config-sha256",
            VOICE_CONFIG_SHA256,
            "--voice-manifest-sha256",
            VOICE_MANIFEST_SHA256,
            "--voice-reference-aggregate-sha256",
            VOICE_REFERENCE_AGGREGATE_SHA256,
            "--provider-voice-id-sha256",
            PROVIDER_VOICE_ID_SHA256,
            "--tts-provider",
            MANFRED_TTS_PROVIDER,
            "--tts-model",
            MANFRED_TTS_MODEL,
            "--authorization-ref-sha256",
            AUTHORIZATION_REF_SHA256,
            "--confirmation",
            "implicit approval is forbidden",
        ]
    )

    assert result == 1
    assert not paths["output"].exists()
