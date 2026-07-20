from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import secrets

import pytest
from fastapi import HTTPException

from app.api.routes import public_memorials
from app.services.memorial_release_policy import evaluate_memorial_voice_release


SOURCE = "a" * 40
FINGERPRINT = "b" * 64
DEPLOYMENT_ID = "deploy-manfred-20260720-001"
PUBLIC_ORIGIN = "https://myexternalbrain.com"
NOW = datetime(2026, 7, 20, 18, 0, tzinfo=UTC)

EVIDENCE = {
    "stt_candidate": ("memorial_stt_fixture_candidate.generated.json", 72 * 60 * 60),
    "stt_captured_benchmark": (
        "memorial_stt_provider_benchmark_captured_candidate.generated.json",
        72 * 60 * 60,
    ),
    "stt_benchmark": ("memorial_stt_provider_benchmark.generated.json", 72 * 60 * 60),
    "captured_candidate_diagnostic": (
        "memorial_stt_captured_candidate_diagnostic.generated.json",
        72 * 60 * 60,
    ),
    "voice_roundtrip": (
        "memorial_voice_roundtrip_public_origin.generated.json",
        72 * 60 * 60,
    ),
    "realtime_browser": (
        "memorial_realtime_browser_public_origin.generated.json",
        24 * 60 * 60,
    ),
    "room_audio": (
        "memorial_room_audio_public_origin.generated.json",
        30 * 24 * 60 * 60,
    ),
    "room_audio_attestation_packet": (
        "memorial_room_audio_attestation_packet.generated.json",
        7 * 24 * 60 * 60,
    ),
}
EVIDENCE_CONTRACTS = {
    "stt_candidate": (
        "ea.memorial_stt_fixture_candidate",
        "scripts/materialize_memorial_stt_fixture_candidate.py",
        "pass",
    ),
    "stt_captured_benchmark": (
        "ea.memorial_stt_provider_benchmark",
        "scripts/benchmark_memorial_stt_providers.py",
        "pass",
    ),
    "stt_benchmark": (
        "ea.memorial_stt_provider_benchmark",
        "scripts/benchmark_memorial_stt_providers.py",
        "pass",
    ),
    "captured_candidate_diagnostic": (
        "ea.memorial_stt_captured_candidate_diagnostic",
        "scripts/materialize_memorial_stt_captured_candidate_diagnostic.py",
        "pass",
    ),
    "voice_roundtrip": (
        "ea.memorial_voice_roundtrip_exit_gate",
        "scripts/materialize_memorial_voice_roundtrip_exit_gate.py",
        "pass",
    ),
    "realtime_browser": (
        "ea.memorial_realtime_browser_exit_gate",
        "scripts/measure_memorial_live_browser.py",
        "pass",
    ),
    "room_audio": (
        "ea.memorial_room_audio_public_origin",
        "scripts/materialize_memorial_room_audio_receipt.py",
        "pass",
    ),
    "room_audio_attestation_packet": (
        "ea.memorial_room_audio_attestation_packet",
        "scripts/materialize_memorial_room_audio_attestation_packet.py",
        "ready",
    ),
}
ROOM_CHECK_IDS = {
    "actual_device_checked",
    "actual_speaker_checked",
    "answer_text_fallback_visible",
    "first_syllable_not_clipped",
    "intelligibility_confirmed",
    "interruption_behavior_confirmed",
    "no_internet_search_confirmed",
    "normal_spoken_turn_confirmed",
    "retry_path_confirmed",
}


@pytest.fixture(autouse=True)
def _restore_test_directory_permissions(tmp_path: Path):
    yield
    for current, directories, _files in os.walk(tmp_path):
        for directory in directories:
            candidate = Path(current) / directory
            if not candidate.is_symlink():
                candidate.chmod(0o700)
    tmp_path.chmod(0o700)


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write_immutable(path: Path, payload: dict[str, object]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    raw = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    temporary = path.with_name(
        f".{path.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
    )
    descriptor = -1
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            0o600,
        )
        offset = 0
        while offset < len(raw):
            written = os.write(descriptor, raw[offset:])
            if written <= 0:
                raise OSError("immutable_fixture_short_write")
            offset += written
        os.fchmod(descriptor, 0o440)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.replace(temporary, path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        path.parent.chmod(0o550)
    return hashlib.sha256(raw).hexdigest()


def _replace_immutable(path: Path, payload: dict[str, object]) -> str:
    return _write_immutable(path, payload)


def _voice_payload() -> dict[str, object]:
    return {
        "voice_profile_id": "${UNMIXR_VOICE_ID}",
        "tts_plugin_voice_id": "${UNMIXR_VOICE_ID}",
        "voice_label": "Manfred Hoza · Unmixr-Klon",
        "lang": "de-AT",
        "tts_plugin": "unmixr_clone",
        "tts_mode": "unmixr_clone",
        "synthetic_voice_clone_of_memorial_person": True,
        "consent_basis": "owner_consented_voice_clone",
        "voice_consent": {
            "status": "approved",
            "scope": [
                "clone",
                "profile_build",
                "synthesize",
                "conversation_turn",
                "realtime",
            ],
            "authorized_by": "family-owner",
            "authorized_at": "2026-06-05T16:25:00Z",
            "source_assets_reviewed": True,
            "revoked": False,
        },
    }


def _evidence_payload(key: str, *, generated_at: str) -> dict[str, object]:
    contract_name, generated_by, status = EVIDENCE_CONTRACTS[key]
    payload: dict[str, object] = {
        "contract_name": contract_name,
        "generated_at": generated_at,
        "generated_by": generated_by,
        "head_semantics": "source_state",
        "source_git_head": SOURCE,
        "source_state_fingerprint": FINGERPRINT,
        "source_state_fingerprint_semantics": (
            "worktree_source_files_sha256_excluding_generated_only_paths"
        ),
        "status": status,
    }
    if key == "stt_candidate":
        payload.update(
            {
                "candidate_scope": "audio_quality_provenance_and_bound_ground_truth",
                "contract_version": 3,
                "failed_codes": [],
                "privacy_mode": "redacted",
                "raw_text_fields": False,
                "text_mode": "redacted",
            }
        )
    elif key in {"stt_captured_benchmark", "stt_benchmark"}:
        payload.update(
            {
                "fixture_quality_failed_codes": [],
                "fixture_quality_status": "pass",
                "scoring": {
                    "raw_provider_transcript_scored": True,
                    "raw_transcript_fields": False,
                    "redacted_text_fields": True,
                    "semantic_repair_applied": False,
                    "text_mode": "redacted",
                },
            }
        )
    elif key == "captured_candidate_diagnostic":
        payload.update(
            {
                "captured_row_count": 2,
                "contract_version": 2,
                "diagnostic_status": "ready",
                "issues": [],
                "may_update_fixture_manifest": True,
                "promotion_allowed": True,
            }
        )
    elif key == "voice_roundtrip":
        payload.update(
            {
                "base_url": PUBLIC_ORIGIN,
                "dirty_worktree": False,
                "failed_codes": [],
                "gold_claim_allowed": True,
                "require_public_origin": True,
                "slug": "manfred",
            }
        )
    elif key == "realtime_browser":
        payload.update(
            {
                "audio_ready_for_ui": True,
                "base_url": PUBLIC_ORIGIN,
                "dirty_worktree": False,
                "failed_codes": [],
                "gold_claim_allowed": True,
                "require_public_origin": True,
                "slug": "manfred",
                "ui_audio_play_calls": 1,
                "ui_audio_play_ended": 1,
            }
        )
    elif key == "room_audio":
        payload.update(
            {
                "base_url": PUBLIC_ORIGIN,
                "check_requirements": {
                    check_id: f"Reviewed requirement for {check_id}."
                    for check_id in ROOM_CHECK_IDS
                },
                "checks": {check_id: True for check_id in ROOM_CHECK_IDS},
                "device_label": "Family presentation MacBook Pro",
                "dirty_worktree": False,
                "failed_codes": [],
                "gold_claim_allowed": True,
                "manual_attestation": {
                    "attestation_id": "room-attestation-20260720-001",
                    "ci_must_not_auto_assert": True,
                    "signed_at": generated_at,
                    "source": "operator_room_review",
                },
                "notes": "Manfred conversation reviewed in the presentation room.",
                "proof_type": "manual_room_attestation",
                "require_public_origin": True,
                "reviewer": "Tibor Hoza",
                "room_label": "Vienna family presentation room",
                "runtime_source_revision": SOURCE,
                "runtime_source_revision_required": True,
                "slug": "manfred",
                "source_tree_fingerprint": "c" * 64,
                "speaker_label": "Presentation room active speakers",
            }
        )
    elif key == "room_audio_attestation_packet":
        payload.update(
            {
                "ci_must_not_auto_assert": True,
                "manual_only": True,
                "operator_command": "make materialize-memorial-room-audio-gold-clean",
                "proof_target": (
                    ".codex-studio/published/"
                    "memorial_room_audio_public_origin.generated.json"
                ),
                "required_checks": [
                    {"id": check_id} for check_id in sorted(ROOM_CHECK_IDS)
                ],
                "slug": "manfred",
            }
        )
    return payload


def _build_bundle(tmp_path: Path) -> dict[str, object]:
    bundle = tmp_path / "conversation-release"
    authority_root = tmp_path / "release-authority"
    private_root = tmp_path / "private" / "manfred"
    generated = NOW - timedelta(minutes=1)

    evidence_paths: dict[str, Path] = {}
    evidence_hashes: dict[str, str] = {}
    evidence_rows: dict[str, dict[str, object]] = {}
    for key, (filename, max_age) in EVIDENCE.items():
        path = bundle / filename
        payload = _evidence_payload(key, generated_at=_timestamp(generated))
        digest = _write_immutable(path, payload)
        evidence_paths[key] = path
        evidence_hashes[key] = digest
        evidence_rows[key] = {
            "receipt_name": filename,
            "present": True,
            "contract_name": EVIDENCE_CONTRACTS[key][0],
            "contract_valid": True,
            "status": EVIDENCE_CONTRACTS[key][2],
            "fresh": True,
            "receipt_sha256": digest,
            "generated_at": _timestamp(generated),
            "max_age_seconds": max_age,
            "source_git_head_present": True,
            "source_git_head_matches_current": True,
            "source_state_fingerprint_present": True,
            "source_state_matches_current": True,
            "raw_private_context_exposed": False,
            "raw_transcript_fields_exposed": False,
            "raw_credentials_exposed": False,
            "raw_receipt_payload_exposed": False,
        }

    readiness_path = bundle / "manfred_realtime_conversation_readiness.generated.json"
    readiness = {
        "contract_name": "ea.manfred_realtime_conversation_readiness.v1",
        "generated_at": _timestamp(generated),
        "generated_by": (
            "ea/scripts/materialize_manfred_realtime_conversation_readiness.py"
        ),
        "memorial_slug": "manfred",
        "evidence_source": "receipt_aggregation",
        "status": "ready_for_realtime_conversation_review",
        "ready_for_realtime_conversation_review": True,
        "blocked_checks": [],
        "head_semantics": "source_state",
        "source_git_head": SOURCE,
        "source_state_fingerprint": FINGERPRINT,
        "source_state_fingerprint_semantics": (
            "worktree_source_files_sha256_excluding_generated_only_paths"
        ),
        "input_evidence": evidence_rows,
    }
    readiness_hash = _write_immutable(readiness_path, readiness)

    voice_path = private_root / "tts_voice.json"
    voice_hash = _write_immutable(voice_path, _voice_payload())
    manifest_path = authority_root / "release_manifest.generated.json"
    manifest = {
        "contract_name": "ea.release_manifest.v1",
        "commit_sha": SOURCE,
        "deploy_context_commit_sha": SOURCE,
        "deployment_id": DEPLOYMENT_ID,
        "deployment_id_source": "deploy_platform",
        "public_origin": PUBLIC_ORIGIN,
        "project_mode": "MEMORIAL",
        "enabled_project_modes": ["MEMORIAL"],
        "dirty_worktree": False,
        "source_worktree_dirty": False,
        "source_dirty_count": 0,
        "source_dirty_files": [],
    }
    manifest_hash = _write_immutable(manifest_path, manifest)
    status_path = authority_root / "release_authority_status.generated.json"
    authority = {
        "contract_name": "ea.release_authority_status.v1",
        "state": "clear",
        "authority_posture": "authoritative_runtime",
        "issues": [],
        "commit_sha": SOURCE,
        "deployment_id": DEPLOYMENT_ID,
        "gate": {
            "status": "pass",
            "issues": [],
            "commit_sha": SOURCE,
            "deployment_id": DEPLOYMENT_ID,
        },
    }
    status_hash = _write_immutable(status_path, authority)
    modes_path = authority_root / "PROJECT_MODES.generated.json"
    modes_hash = _write_immutable(
        modes_path,
        {
            "contract_name": "ea.project_modes",
            "modes": [{"key": "MEMORIAL"}, {"key": "PROPERTY"}],
        },
    )

    room_path = evidence_paths["room_audio"]
    input_paths = {
        "readiness_receipt": readiness_path,
        "room_audio_receipt": room_path,
        "tts_voice_consent": voice_path,
        "release_manifest": manifest_path,
        "release_authority_status": status_path,
        "project_modes": modes_path,
    }
    effective_expiry = generated + timedelta(hours=24)
    packet = {
        "contract_name": "ea.manfred_realtime_conversation_release.v1",
        "generated_by": "ea/scripts/manfred_realtime_conversation_release.py",
        "generated_at": _timestamp(NOW),
        "effective_expires_at": _timestamp(effective_expiry),
        "status": "pass",
        "memorial_slug": "manfred",
        "source_git_head": SOURCE,
        "head_semantics": "source_state",
        "source_state_fingerprint": FINGERPRINT,
        "source_state_fingerprint_semantics": (
            "worktree_source_files_sha256_excluding_generated_only_paths"
        ),
        "deployment_revision": SOURCE,
        "deployment_id": DEPLOYMENT_ID,
        "deployment_id_source": "deploy_platform",
        "public_origin": PUBLIC_ORIGIN,
        "project_mode": "MEMORIAL",
        "enabled_project_modes": ["MEMORIAL"],
        "conversation_prerequisites_pass": True,
        "release_context_verified": True,
        "room_audio_attestation_verified": True,
        "voice_authority": {
            "authority_source": "private_tts_voice_consent",
            "consent_status": "approved",
            "realtime_scope": True,
            "revoked": False,
            "source_assets_reviewed": True,
            "synthetic_voice_clone_disclosure": True,
            "tts_mode": "unmixr_clone",
            "tts_plugin": "unmixr_clone",
        },
        "raw_input_sha256": {
            "readiness_receipt": readiness_hash,
            "room_audio_receipt": evidence_hashes["room_audio"],
            "tts_voice_consent": voice_hash,
            "release_manifest": manifest_hash,
            "release_authority_status": status_hash,
            "project_modes": modes_hash,
        },
        "readiness_evidence_raw_sha256": evidence_hashes,
    }
    packet_path = bundle / "manfred_realtime_conversation_release.generated.json"
    _write_immutable(packet_path, packet)
    return {
        "packet": packet,
        "packet_path": packet_path,
        "input_paths": input_paths,
        "evidence_paths": evidence_paths,
        "readiness": readiness,
        "voice_path": voice_path,
    }


def _evaluate(bundle: dict[str, object], **overrides: object) -> dict[str, object]:
    runtime_primary_mode = overrides.pop("_runtime_primary_mode", "MEMORIAL")
    runtime_enabled_modes = overrides.pop("_runtime_enabled_modes", "MEMORIAL")
    values: dict[str, object] = {
        "slug": "manfred",
        "receipt_path": bundle["packet_path"],
        "now": NOW.timestamp(),
        "activation_enabled": True,
        "input_paths": bundle["input_paths"],
        "readiness_evidence_paths": bundle["evidence_paths"],
        "expected_source_revision": SOURCE,
        "expected_deployment_id": DEPLOYMENT_ID,
        "expected_public_origin": PUBLIC_ORIGIN,
    }
    values.update(overrides)
    with pytest.MonkeyPatch.context() as environment:
        if runtime_primary_mode is None:
            environment.delenv("EA_DEPLOY_PRIMARY_MODE", raising=False)
        else:
            environment.setenv(
                "EA_DEPLOY_PRIMARY_MODE",
                str(runtime_primary_mode),
            )
        if runtime_enabled_modes is None:
            environment.delenv("EA_DEPLOY_ENABLED_MODES", raising=False)
        else:
            environment.setenv(
                "EA_DEPLOY_ENABLED_MODES",
                str(runtime_enabled_modes),
            )
        return evaluate_memorial_voice_release(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("primary_mode", "enabled_modes"),
    [
        (None, None),
        ("memorial", "MEMORIAL"),
        ("MEMORIAL", "memorial"),
        ("MEMORIAL", "MEMORIAL,PROPERTY"),
        ("MEMORIAL", "MEMORIAL,MEMORIAL"),
        ("EA_CORE", "MEMORIAL"),
    ],
)
def test_release_policy_requires_exact_memorial_only_runtime_topology(
    tmp_path: Path,
    primary_mode: str | None,
    enabled_modes: str | None,
) -> None:
    result = _evaluate(
        _build_bundle(tmp_path),
        _runtime_primary_mode=primary_mode,
        _runtime_enabled_modes=enabled_modes,
    )

    assert result == {
        "allowed": False,
        "status": "blocked",
        "reason": "release_runtime_topology_invalid",
        "receipt_status": "",
    }


def _rebind_evidence_payloads(
    bundle: dict[str, object],
    replacements: dict[str, dict[str, object]],
    *,
    readiness_overrides: dict[str, object] | None = None,
    packet_overrides: dict[str, object] | None = None,
) -> None:
    readiness = copy.deepcopy(bundle["readiness"])
    packet = copy.deepcopy(bundle["packet"])
    evidence_hashes = dict(packet["readiness_evidence_raw_sha256"])
    raw_input_hashes = dict(packet["raw_input_sha256"])
    for key, payload in replacements.items():
        path = bundle["evidence_paths"][key]
        digest = _replace_immutable(path, payload)
        evidence_hashes[key] = digest
        readiness["input_evidence"][key]["receipt_sha256"] = digest
        readiness["input_evidence"][key]["generated_at"] = payload.get(
            "generated_at"
        )
        if key == "room_audio":
            raw_input_hashes["room_audio_receipt"] = digest
    if readiness_overrides:
        readiness.update(readiness_overrides)
    readiness_hash = _replace_immutable(
        bundle["input_paths"]["readiness_receipt"], readiness
    )
    raw_input_hashes["readiness_receipt"] = readiness_hash
    packet["readiness_evidence_raw_sha256"] = evidence_hashes
    packet["raw_input_sha256"] = raw_input_hashes
    if packet_overrides:
        packet.update(packet_overrides)
    _replace_immutable(bundle["packet_path"], packet)


def test_runtime_accepts_only_exact_immutable_activated_bundle(tmp_path: Path) -> None:
    bundle = _build_bundle(tmp_path)
    result = _evaluate(bundle)
    assert result == {
        "allowed": True,
        "status": "prerequisites_active",
        "reason": "",
        "receipt_status": "pass",
    }
    protected_paths = [
        bundle["packet_path"],
        *bundle["input_paths"].values(),
        *bundle["evidence_paths"].values(),
    ]
    assert all(path.stat().st_mode & 0o777 == 0o440 for path in protected_paths)
    assert all(
        path.parent.stat().st_mode & 0o777 == 0o550
        for path in protected_paths
    )


def test_runtime_activation_is_separate_and_defaults_closed(tmp_path: Path) -> None:
    bundle = _build_bundle(tmp_path)
    assert _evaluate(bundle, activation_enabled=False)["reason"] == (
        "release_activation_disabled"
    )
    assert evaluate_memorial_voice_release(
        slug="manfred",
        receipt_path=tmp_path / "missing.json",
        activation_enabled=False,
    )["reason"] == "release_activation_disabled"


def test_runtime_packet_remains_valid_until_bound_evidence_expiry(tmp_path: Path) -> None:
    bundle = _build_bundle(tmp_path)
    result = _evaluate(bundle, now=(NOW + timedelta(hours=2)).timestamp())
    assert result["allowed"] is True


def test_runtime_rejects_schema_less_evidence_even_when_all_hashes_are_rebound(
    tmp_path: Path,
) -> None:
    bundle = _build_bundle(tmp_path)
    generated_at = str(
        bundle["readiness"]["input_evidence"]["stt_candidate"]["generated_at"]
    )
    _rebind_evidence_payloads(
        bundle,
        {"stt_candidate": {"generated_at": generated_at}},
    )

    assert _evaluate(bundle)["reason"] == (
        "release_evidence_contract_invalid:stt_candidate"
    )


def test_runtime_rejects_forged_pass_status_even_when_all_hashes_are_rebound(
    tmp_path: Path,
) -> None:
    bundle = _build_bundle(tmp_path)
    payload = _evidence_payload(
        "voice_roundtrip",
        generated_at=str(
            bundle["readiness"]["input_evidence"]["voice_roundtrip"][
                "generated_at"
            ]
        ),
    )
    payload["gold_claim_allowed"] = False
    _rebind_evidence_payloads(bundle, {"voice_roundtrip": payload})

    assert _evaluate(bundle)["reason"] == (
        "release_evidence_status_invalid:voice_roundtrip"
    )


def test_runtime_rejects_future_readiness_and_evidence_timestamps(
    tmp_path: Path,
) -> None:
    evidence_bundle = _build_bundle(tmp_path / "evidence")
    future = _timestamp(NOW + timedelta(minutes=6))
    payload = _evidence_payload("stt_candidate", generated_at=future)
    _rebind_evidence_payloads(evidence_bundle, {"stt_candidate": payload})
    assert _evaluate(evidence_bundle)["reason"] == (
        "release_evidence_generated_at_future:stt_candidate"
    )

    readiness_bundle = _build_bundle(tmp_path / "readiness")
    _rebind_evidence_payloads(
        readiness_bundle,
        {},
        readiness_overrides={"generated_at": future},
    )
    assert _evaluate(readiness_bundle)["reason"] == (
        "release_readiness_generated_at_future"
    )


def test_runtime_rejects_far_future_evidence_expiry_rebinding(
    tmp_path: Path,
) -> None:
    bundle = _build_bundle(tmp_path)
    future_time = NOW + timedelta(days=3650)
    future = _timestamp(future_time)
    replacements = {
        key: _evidence_payload(key, generated_at=future)
        for key in EVIDENCE
    }
    _rebind_evidence_payloads(
        bundle,
        replacements,
        readiness_overrides={"generated_at": future},
        packet_overrides={
            "effective_expires_at": _timestamp(future_time + timedelta(hours=24))
        },
    )

    assert _evaluate(bundle)["allowed"] is False
    assert _evaluate(bundle)["reason"] in {
        "release_effective_expiry_invalid",
        "release_receipt_timestamp_invalid",
        "release_readiness_generated_at_future",
    }


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("conversation_prerequisites_pass", False, "release_prerequisites_invalid"),
        ("release_context_verified", False, "release_prerequisites_invalid"),
        (
            "enabled_project_modes",
            ["MEMORIAL", "PROPERTY"],
            "release_prerequisites_invalid",
        ),
        ("deployment_revision", "c" * 40, "release_runtime_binding_mismatch"),
        ("public_origin", "https://other.example", "release_runtime_binding_mismatch"),
        (
            "effective_expires_at",
            "2026-07-20T17:59:59Z",
            "release_receipt_timestamp_invalid",
        ),
    ],
)
def test_runtime_rejects_tampered_prerequisite_claims(
    tmp_path: Path, field: str, value: object, reason: str
) -> None:
    bundle = _build_bundle(tmp_path)
    packet = dict(bundle["packet"])
    packet[field] = value
    _replace_immutable(bundle["packet_path"], packet)  # type: ignore[arg-type]
    assert _evaluate(bundle)["reason"] == reason


def test_runtime_rejects_legacy_authority_claim_in_packet(tmp_path: Path) -> None:
    bundle = _build_bundle(tmp_path)
    packet = dict(bundle["packet"])
    packet["runtime_enablement_allowed"] = True
    _replace_immutable(bundle["packet_path"], packet)  # type: ignore[arg-type]
    assert _evaluate(bundle)["reason"] == "release_receipt_schema_invalid"


def test_runtime_rejects_input_hash_tamper_and_voice_revocation(tmp_path: Path) -> None:
    bundle = _build_bundle(tmp_path)
    voice_path = bundle["voice_path"]
    voice = _voice_payload()
    consent = dict(voice["voice_consent"])
    consent["revoked"] = True
    voice["voice_consent"] = consent
    _replace_immutable(voice_path, voice)  # type: ignore[arg-type]
    assert _evaluate(bundle)["reason"] == "release_raw_input_hash_mismatch"

    packet = dict(bundle["packet"])
    hashes = dict(packet["raw_input_sha256"])
    hashes["tts_voice_consent"] = hashlib.sha256(voice_path.read_bytes()).hexdigest()
    packet["raw_input_sha256"] = hashes
    _replace_immutable(bundle["packet_path"], packet)  # type: ignore[arg-type]
    assert _evaluate(bundle)["reason"] == "release_voice_authority_invalid"


def test_runtime_recomputes_earliest_evidence_expiry(tmp_path: Path) -> None:
    bundle = _build_bundle(tmp_path)
    packet = dict(bundle["packet"])
    packet["effective_expires_at"] = _timestamp(NOW + timedelta(days=10))
    _replace_immutable(bundle["packet_path"], packet)  # type: ignore[arg-type]
    assert _evaluate(bundle)["reason"] == "release_receipt_timestamp_invalid"


def test_runtime_rejects_mutable_symlinked_or_hardlinked_packet(tmp_path: Path) -> None:
    bundle = _build_bundle(tmp_path)
    packet_path = bundle["packet_path"]
    packet_path.chmod(0o600)  # type: ignore[union-attr]
    assert _evaluate(bundle)["reason"] == "release_receipt_untrusted"
    packet_path.chmod(0o400)  # type: ignore[union-attr]

    link = tmp_path / "packet-link.json"
    link.symlink_to(packet_path)
    hardlink = tmp_path / "packet-hardlink.json"
    hardlink.hardlink_to(packet_path)
    tmp_path.chmod(0o550)
    try:
        assert _evaluate(bundle, receipt_path=link)["reason"] == (
            "release_receipt_missing_or_unsafe"
        )
        assert _evaluate(bundle)["reason"] == "release_receipt_untrusted"
    finally:
        tmp_path.chmod(0o700)


@pytest.mark.parametrize("mode", [0o640, 0o460, 0o442])
def test_runtime_rejects_any_writable_receipt_mode(
    tmp_path: Path,
    mode: int,
) -> None:
    bundle = _build_bundle(tmp_path)
    bundle["packet_path"].chmod(mode)

    assert _evaluate(bundle)["reason"] == "release_receipt_untrusted"


@pytest.mark.parametrize("mode", [0o750, 0o570, 0o552])
def test_runtime_rejects_any_writable_receipt_parent_mode(
    tmp_path: Path,
    mode: int,
) -> None:
    bundle = _build_bundle(tmp_path)
    bundle["packet_path"].parent.chmod(mode)

    assert _evaluate(bundle)["reason"] == "release_receipt_parent_untrusted"


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"expected_source_revision": "c" * 40}, "release_runtime_binding_mismatch"),
        ({"expected_deployment_id": "local_fallback"}, "release_runtime_deployment_id_invalid"),
        ({"expected_public_origin": "https://localhost"}, "release_public_origin_invalid"),
    ],
)
def test_runtime_rejects_wrong_runtime_identity(
    tmp_path: Path, overrides: dict[str, object], reason: str
) -> None:
    assert _evaluate(_build_bundle(tmp_path), **overrides)["reason"] == reason


@pytest.mark.parametrize(
    ("origin", "reason"),
    [
        ("https://127.0.0.1", "release_public_origin_invalid"),
        ("https://8.8.8.8", "release_public_origin_invalid"),
        ("https://singlelabel", "release_public_origin_invalid"),
        ("https://memorial.local", "release_public_origin_invalid"),
        ("https://memorial.internal", "release_public_origin_invalid"),
        ("https://memorial.home.arpa", "release_public_origin_invalid"),
        ("https://memorial.test", "release_public_origin_invalid"),
        ("https://example.com", "release_public_origin_invalid"),
        ("https://voice.example.com", "release_public_origin_invalid"),
        (
            "https://myexternalbrain.com/",
            "release_public_origin_not_canonical",
        ),
        (
            "https://www.myexternalbrain.com",
            "release_public_origin_not_canonical",
        ),
    ],
)
def test_runtime_rejects_nonpublic_or_noncanonical_origin(
    tmp_path: Path,
    origin: str,
    reason: str,
) -> None:
    assert _evaluate(
        _build_bundle(tmp_path),
        expected_public_origin=origin,
    )["reason"] == reason


def test_memorial_chat_contract_is_transparent_and_never_claims_to_be_manfred() -> None:
    payload = public_memorials._load_memorial("manfred")
    messages = public_memorials._build_memorial_chat_messages(
        payload,
        {},
        "Wer bist du wirklich?",
        slug="manfred",
        memory_runtime=None,
        personal_memory_context={},
    )
    instruction = str(messages[0]["content"])

    assert "Du sprichst hier als Manfred selbst" not in instruction
    assert "Sag niemals, dass du ein LLM" not in instruction
    assert "Du bist nicht Manfred" in instruction
    answer = public_memorials._enforce_memorial_narrator_boundary(
        "Ich bin Manfred. Ich bin wirklich hier.", question="Wer bist du wirklich?"
    )
    assert "nicht Manfred" in answer
    assert "Ich bin Manfred" not in answer


def test_memorial_voice_config_reports_clone_truthfully() -> None:
    payload = public_memorials._load_voice_config("manfred")
    public_payload = public_memorials._public_voice_config_payload("manfred", payload)
    assert payload["synthetic_voice_clone_of_memorial_person"] is True
    assert public_payload["synthetic_voice_clone_of_memorial_person"] is True


def test_production_voice_gate_rejects_before_provider_work(monkeypatch) -> None:
    payload = public_memorials._payload_with_slug(
        "manfred", public_memorials._load_memorial("manfred")
    )
    monkeypatch.setattr(public_memorials, "_memorial_voice_release_enforced", lambda: True)
    monkeypatch.setattr(
        public_memorials,
        "_memorial_voice_release_decision",
        lambda _slug: {
            "allowed": False,
            "status": "blocked",
            "reason": "release_prerequisites_blocked",
            "receipt_status": "blocked_realtime_prerequisites",
        },
    )
    with pytest.raises(HTTPException) as exc_info:
        public_memorials._require_voice_consent(payload, "synthesize")
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "memorial_voice_release_not_verified"


def test_blocked_release_prevents_page_prewarm(monkeypatch) -> None:
    scheduled: list[str] = []
    monkeypatch.setattr(public_memorials, "_memorial_page_prewarm_enabled", lambda: True)
    monkeypatch.setattr(public_memorials, "_memorial_voice_release_enforced", lambda: True)
    monkeypatch.setattr(public_memorials, "_memorial_voice_release_decision", lambda _slug: {"allowed": False})
    monkeypatch.setattr(
        public_memorials,
        "_schedule_memorial_live_warmup",
        lambda slug: scheduled.append(slug),
    )
    public_memorials._prime_memorial_live_warmup_on_page_render("manfred")
    assert scheduled == []
