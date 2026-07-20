#!/usr/bin/env python3
"""Host-side aggregation of Manfred conversation prerequisites.

This module creates no human or release authority. It only joins established,
canonically verified readiness, room-attestation, private voice-consent, and
release-context planes. A ``status: pass`` result does not prove a root permit,
authorize deployment or public release, enable a runtime, or make a Gold claim.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any
from urllib.parse import urlsplit


SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[2]
for import_root in (REPO_ROOT, SCRIPT_PATH.parent):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

import materialize_manfred_realtime_conversation_readiness as readiness_materializer
import verify_manfred_realtime_conversation_readiness as readiness_verifier
from scripts.materialize_memorial_room_audio_receipt import ROOM_AUDIO_CHECK_REQUIREMENTS
from scripts.verify_release_authority import validate_release_authority


CONTRACT_NAME = "ea.manfred_realtime_conversation_release.v1"
VERIFY_CONTRACT_NAME = "ea.manfred_realtime_conversation_release.verify.v1"
GENERATED_BY = "ea/scripts/manfred_realtime_conversation_release.py"
MEMORIAL_SLUG = "manfred"
SOURCE_HEAD_SEMANTICS = "source_state"
SOURCE_FINGERPRINT_SEMANTICS = (
    "worktree_source_files_sha256_excluding_generated_only_paths"
)
READINESS_CONTRACT = "ea.manfred_realtime_conversation_readiness.v1"
ROOM_CONTRACT = "ea.memorial_room_audio_public_origin"
RELEASE_MANIFEST_CONTRACT = "ea.release_manifest.v1"
RELEASE_STATUS_CONTRACT = "ea.release_authority_status.v1"
RELEASE_GATE_CONTRACT = "ea.release_authority_gate.v1"
DEPLOY_CONTEXT_GATE_CONTRACT = "ea.deploy_context_gate.v1"
UNMIXR_CLONE_CONTRACT = {
    "tts_plugin": "unmixr_clone",
    "tts_mode": "unmixr_clone",
    "tts_plugin_voice_id": "${UNMIXR_VOICE_ID}",
    "consent_basis": "owner_consented_voice_clone",
}
MANFRED_VOICE_ID = "${UNMIXR_VOICE_ID}"
MANFRED_VOICE_LABEL = "Manfred Hoza · Unmixr-Klon"
MANFRED_VOICE_LANGUAGE = "de-AT"
VOICE_SCOPE = [
    "clone",
    "profile_build",
    "synthesize",
    "conversation_turn",
    "realtime",
]
REVIEWED_PROJECT_MODE = "MEMORIAL"
REVIEWED_ENABLED_PROJECT_MODES = ["MEMORIAL"]
MAX_JSON_BYTES = 4 * 1024 * 1024
READ_CHUNK_BYTES = 64 * 1024
MAX_FUTURE_SKEW = timedelta(minutes=5)
READINESS_MAX_AGE = timedelta(
    seconds=readiness_materializer.READINESS_MAX_AGE_SECONDS
)

PUBLISHED_ROOT = REPO_ROOT / ".codex-studio" / "published"
DEFAULT_READINESS_RECEIPT = (
    PUBLISHED_ROOT / "manfred_realtime_conversation_readiness.generated.json"
)
DEFAULT_READINESS_EVIDENCE_ROOT = PUBLISHED_ROOT
DEFAULT_ROOM_RECEIPT = (
    PUBLISHED_ROOT / "memorial_room_audio_public_origin.generated.json"
)
DEFAULT_TTS_VOICE = (
    REPO_ROOT / "memorial_data" / "private_memorial_profiles"
    / MEMORIAL_SLUG / "tts_voice.json"
)
DEFAULT_RELEASE_MANIFEST = PUBLISHED_ROOT / "release_manifest.generated.json"
DEFAULT_RELEASE_AUTHORITY_STATUS = (
    PUBLISHED_ROOT / "release_authority_status.generated.json"
)
DEFAULT_PROJECT_MODES = (
    REPO_ROOT / ".codex-design" / "product" / "PROJECT_MODES.generated.json"
)
DEFAULT_OUTPUT = (
    PUBLISHED_ROOT / "manfred_realtime_conversation_release.generated.json"
)

ROOM_RECEIPT_KEYS = {
    "base_url", "check_requirements", "checks", "contract_name", "device_label",
    "dirty_worktree", "failed_codes", "generated_at", "generated_by",
    "gold_claim_allowed", "head_semantics", "manual_attestation", "notes",
    "proof_type", "require_public_origin", "reviewer", "room_label",
    "runtime_source_revision", "runtime_source_revision_required", "slug",
    "source_git_head", "source_state_fingerprint",
    "source_state_fingerprint_semantics", "source_tree_fingerprint",
    "speaker_label", "status",
}
GENERIC_ROOM_LABELS = {
    "reviewer": {
        "qa-room-reviewer", "qa room reviewer", "reviewer", "test reviewer",
    },
    "device_label": {
        "laptop speaker test", "presentation laptop", "laptop", "test device",
    },
    "speaker_label": {
        "room speaker", "speaker", "laptop speaker", "test speaker",
    },
    "room_label": {"office", "room", "test room"},
}
RELEASE_BINDING_FIELDS = (
    "repository", "branch", "tracking_branch", "commit_sha",
    "source_remote_ref", "source_remote_ref_commit_sha",
    "source_remote_ref_evidence", "source_commit_reachable_from_remote_ref",
    "deployment_id", "deployment_id_source", "public_origin",
    "public_origin_source", "deploy_context_generated_at",
    "deploy_context_branch", "deploy_context_tracking_branch",
    "deploy_context_commit_sha", "project_mode", "enabled_project_modes",
    "compose_files", "compose_overrides", "dirty_worktree",
    "source_worktree_dirty", "source_dirty_count", "source_dirty_files",
    "source_dirty_omitted_count", "source_dirty_status_sha256",
)
OUTPUT_KEYS = {
    "contract_name", "conversation_prerequisites_pass", "deployment_id",
    "deployment_id_source", "deployment_revision", "effective_expires_at",
    "enabled_project_modes", "generated_at", "generated_by", "head_semantics",
    "memorial_slug", "project_mode", "public_origin", "raw_input_sha256",
    "readiness_evidence_raw_sha256", "release_context_verified",
    "room_audio_attestation_verified",
    "source_git_head", "source_state_fingerprint",
    "source_state_fingerprint_semantics", "status", "voice_authority",
}


class ReleaseContractError(ValueError):
    """Fail-closed validation error with a stable code."""

    def __init__(self, code: str):
        self.code = str(code or "release_contract_invalid")
        super().__init__(self.code)


@dataclass(frozen=True)
class InputSnapshot:
    label: str
    path: Path
    raw: bytes
    payload: dict[str, Any]
    sha256: str
    identity: tuple[int, ...]
    private: bool


def _fail(code: str) -> None:
    raise ReleaseContractError(code)


def _identity(observed: os.stat_result) -> tuple[int, ...]:
    return (
        observed.st_dev, observed.st_ino, observed.st_uid, observed.st_gid,
        observed.st_mode, observed.st_nlink, observed.st_size,
        observed.st_mtime_ns, observed.st_ctime_ns,
    )


def _directory_identity(observed: os.stat_result) -> tuple[int, ...]:
    return (
        observed.st_dev,
        observed.st_ino,
        observed.st_uid,
        observed.st_gid,
        observed.st_mode,
    )


def _trusted_directory(observed: os.stat_result, *, label: str) -> None:
    if not stat.S_ISDIR(observed.st_mode):
        _fail(f"{label}_parent_not_directory")
    if observed.st_uid != os.geteuid():
        _fail(f"{label}_parent_owner_untrusted")
    if stat.S_IMODE(observed.st_mode) & 0o022:
        _fail(f"{label}_parent_permissions_unsafe")


def _trusted_file(
    observed: os.stat_result, *, label: str, private: bool
) -> None:
    if not stat.S_ISREG(observed.st_mode):
        _fail(f"{label}_not_regular")
    if observed.st_uid != os.geteuid():
        _fail(f"{label}_owner_untrusted")
    if observed.st_nlink != 1:
        _fail(f"{label}_link_count_unsafe")
    mode = stat.S_IMODE(observed.st_mode)
    if mode & 0o022:
        _fail(f"{label}_permissions_unsafe")
    if private and mode & 0o077:
        _fail(f"{label}_permissions_not_private")
    if observed.st_size < 2 or observed.st_size > MAX_JSON_BYTES:
        _fail(f"{label}_size_invalid")


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail("json_duplicate_key")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> None:
    _fail(f"json_nonfinite:{value}")


def _parse_json_document(raw: bytes, *, label: str) -> dict[str, Any]:
    try:
        parsed = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_nonfinite,
        )
    except ReleaseContractError as exc:
        _fail(f"{label}_{exc.code}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        _fail(f"{label}_json_invalid")
    if not isinstance(parsed, dict):
        _fail(f"{label}_shape_invalid")
    return dict(parsed)


def _snapshot_json(
    path: str | Path, *, label: str, private: bool = False
) -> InputSnapshot:
    target = Path(path)
    parent_fd = -1
    file_fd = -1
    try:
        try:
            parent_fd, target_name = readiness_materializer._open_parent_dirfd(
                target, create=False
            )
        except (
            FileNotFoundError, OSError, readiness_materializer.UnsafeLocalFileError
        ):
            _fail(f"{label}_path_unsafe_or_missing")
        _trusted_directory(os.fstat(parent_fd), label=label)
        try:
            path_before = os.stat(
                target_name, dir_fd=parent_fd, follow_symlinks=False
            )
            file_fd = os.open(
                target_name,
                os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
                dir_fd=parent_fd,
            )
        except (FileNotFoundError, OSError):
            _fail(f"{label}_path_unsafe_or_missing")
        opened_before = os.fstat(file_fd)
        _trusted_file(opened_before, label=label, private=private)
        if _identity(path_before) != _identity(opened_before):
            _fail(f"{label}_changed_during_open")

        remaining = opened_before.st_size
        chunks: list[bytes] = []
        while remaining:
            chunk = os.read(file_fd, min(remaining, READ_CHUNK_BYTES))
            if not chunk:
                _fail(f"{label}_short_read")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(file_fd, 1):
            _fail(f"{label}_grew_during_read")
        opened_after = os.fstat(file_fd)
        try:
            path_after = os.stat(
                target_name, dir_fd=parent_fd, follow_symlinks=False
            )
        except OSError:
            _fail(f"{label}_changed_during_read")
        if (
            _identity(opened_before) != _identity(opened_after)
            or _identity(opened_after) != _identity(path_after)
        ):
            _fail(f"{label}_changed_during_read")
        raw = b"".join(chunks)
        return InputSnapshot(
            label=label,
            path=target,
            raw=raw,
            payload=_parse_json_document(raw, label=label),
            sha256=hashlib.sha256(raw).hexdigest(),
            identity=_identity(opened_after),
            private=private,
        )
    finally:
        if file_fd >= 0:
            os.close(file_fd)
        if parent_fd >= 0:
            os.close(parent_fd)


def _assert_inputs_unchanged(snapshots: list[InputSnapshot]) -> None:
    for snapshot in snapshots:
        current = _snapshot_json(
            snapshot.path, label=snapshot.label, private=snapshot.private
        )
        if (
            current.identity != snapshot.identity
            or current.sha256 != snapshot.sha256
            or current.raw != snapshot.raw
        ):
            _fail(f"{snapshot.label}_changed_before_commit")


def _output_location(path: Path) -> tuple[int, ...]:
    parent_fd = -1
    try:
        parent_fd, target_name = readiness_materializer._open_parent_dirfd(
            path, create=False
        )
        observed = os.fstat(parent_fd)
        _trusted_directory(observed, label="output")
        try:
            target = os.stat(
                target_name, dir_fd=parent_fd, follow_symlinks=False
            )
        except FileNotFoundError:
            target = None
        except OSError:
            _fail("output_target_stat_failed")
        if target is not None:
            _trusted_file(target, label="output_target", private=True)
        return _directory_identity(observed)
    except (
        FileNotFoundError, OSError, readiness_materializer.UnsafeLocalFileError
    ):
        _fail("output_parent_unsafe_or_missing")
    finally:
        if parent_fd >= 0:
            os.close(parent_fd)


def _atomic_write(path: str | Path, payload: dict[str, Any]) -> None:
    target = Path(path)
    try:
        parent_identity = _output_location(target)
        readiness_materializer._write(target, payload)
        if _output_location(target) != parent_identity:
            _fail("output_parent_changed_during_commit")
        committed = _snapshot_json(
            target, label="release_receipt", private=True
        )
        if committed.payload != payload:
            _fail("output_atomic_content_mismatch")
    except ReleaseContractError:
        raise
    except (OSError, readiness_materializer.UnsafeLocalFileError) as exc:
        raise ReleaseContractError("output_atomic_write_failed") from exc


def _as_utc(value: datetime | None) -> datetime:
    observed = value or datetime.now(UTC)
    if observed.tzinfo is None:
        _fail("now_timezone_missing")
    return observed.astimezone(UTC)


def _parse_timestamp(value: object, *, label: str) -> datetime:
    text = str(value or "").strip()
    if not text or not text.endswith("Z"):
        _fail(f"{label}_invalid")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except (TypeError, ValueError, OverflowError):
        _fail(f"{label}_invalid")
    if parsed.tzinfo is None:
        _fail(f"{label}_invalid")
    return parsed.astimezone(UTC)


def _format_timestamp(value: datetime) -> str:
    return (
        value.astimezone(UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _valid_sha(value: object, length: int) -> bool:
    text = str(value or "")
    return bool(
        len(text) == length
        and text == text.lower()
        and all(character in "0123456789abcdef" for character in text)
    )


def _source_binding(
    *,
    expected_source_git_head: str,
    expected_source_state_fingerprint: str,
) -> tuple[str, str]:
    if (
        not isinstance(expected_source_git_head, str)
        or not isinstance(expected_source_state_fingerprint, str)
        or not expected_source_git_head
        or not expected_source_state_fingerprint
    ):
        _fail("explicit_source_binding_required")
    head = expected_source_git_head
    fingerprint = expected_source_state_fingerprint
    if head != head.strip() or fingerprint != fingerprint.strip():
        _fail("explicit_source_binding_not_exact")
    if not _valid_sha(head, 40):
        _fail("source_git_head_invalid")
    if not _valid_sha(fingerprint, 64):
        _fail("source_state_fingerprint_invalid")
    return head, fingerprint


def _canonical_readiness_pass(
    *,
    receipt_path: Path,
    evidence_root: Path,
    expected_head: str,
    expected_fingerprint: str,
) -> None:
    result = readiness_verifier.verify_manfred_realtime_conversation_readiness(
        receipt_path,
        evidence_root=evidence_root,
        expected_source_git_head=expected_head,
        expected_source_state_fingerprint=expected_fingerprint,
    )
    expected = {
        "contract_name": (
            "ea.manfred_realtime_conversation_readiness.verify.v1"
        ),
        "status": "pass",
        "issues": [],
    }
    if result != expected:
        _fail("canonical_readiness_verifier_not_pass")


def _public_origin(value: object) -> str:
    text = str(value or "").strip().rstrip("/")
    try:
        parsed = urlsplit(text)
        port = parsed.port
    except ValueError:
        _fail("public_origin_invalid")
    hostname = str(parsed.hostname or "").lower()
    if (
        parsed.scheme.lower() != "https"
        or not hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
        or hostname == "localhost"
        or hostname.endswith(".local")
        or "." not in hostname
    ):
        _fail("public_origin_invalid")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        _fail("public_origin_invalid")
    authority = hostname if port in {None, 443} else f"{hostname}:{port}"
    normalized = f"https://{authority}"
    if text.lower() != normalized:
        _fail("public_origin_not_canonical")
    return normalized


def _validate_readiness(
    snapshot: InputSnapshot,
    *,
    evidence: dict[str, InputSnapshot],
    expected_head: str,
    expected_fingerprint: str,
    now: datetime,
) -> datetime:
    payload = snapshot.payload
    if (
        payload.get("contract_name") != READINESS_CONTRACT
        or payload.get("memorial_slug") != MEMORIAL_SLUG
        or payload.get("status")
        != "ready_for_realtime_conversation_review"
        or payload.get("ready_for_realtime_conversation_review") is not True
        or payload.get("blocked_checks") != []
        or payload.get("evidence_source") != "receipt_aggregation"
    ):
        _fail("readiness_not_exact_pass")
    if any(
        payload.get(field) is not False
        for field in (
            "realtime_conversation_claim_allowed",
            "premium_spoken_claim_allowed",
            "goal_completion_claim_allowed",
        )
    ):
        _fail("readiness_claim_boundary_invalid")
    if (
        payload.get("source_git_head") != expected_head
        or payload.get("head_semantics") != SOURCE_HEAD_SEMANTICS
        or payload.get("source_state_fingerprint") != expected_fingerprint
        or payload.get("source_state_fingerprint_semantics")
        != SOURCE_FINGERPRINT_SEMANTICS
    ):
        _fail("readiness_source_binding_mismatch")
    generated_at = _parse_timestamp(
        payload.get("generated_at"), label="readiness_generated_at"
    )
    if generated_at - now > MAX_FUTURE_SKEW:
        _fail("readiness_generated_at_future")
    effective_expires_at = generated_at + READINESS_MAX_AGE
    if now >= effective_expires_at:
        _fail("readiness_expired")

    input_evidence = payload.get("input_evidence")
    if not isinstance(input_evidence, dict):
        _fail("readiness_input_evidence_invalid")
    if set(input_evidence) != set(readiness_materializer.EVIDENCE_RECEIPTS):
        _fail("readiness_input_evidence_incomplete")
    for key, snapshot_row in evidence.items():
        row = input_evidence.get(key)
        expected_max_age = readiness_materializer.EVIDENCE_MAX_AGE_SECONDS.get(
            key
        )
        if (
            not isinstance(row, dict)
            or row.get("present") is not True
            or row.get("contract_valid") is not True
            or row.get("fresh") is not True
            or row.get("receipt_sha256") != snapshot_row.sha256
            or row.get("source_git_head_matches_current") is not True
            or row.get("source_state_matches_current") is not True
        ):
            _fail(f"readiness_evidence_binding_invalid:{key}")
        if (
            type(expected_max_age) is not int
            or expected_max_age <= 0
            or type(row.get("max_age_seconds")) is not int
            or row.get("max_age_seconds") != expected_max_age
        ):
            _fail(f"readiness_evidence_max_age_invalid:{key}")
        direct_generated_at = snapshot_row.payload.get("generated_at")
        if row.get("generated_at") != direct_generated_at:
            _fail(f"readiness_evidence_generated_at_mismatch:{key}")
        evidence_generated_at = _parse_timestamp(
            direct_generated_at,
            label=f"readiness_evidence_generated_at:{key}",
        )
        if evidence_generated_at - now > MAX_FUTURE_SKEW:
            _fail(f"readiness_evidence_generated_at_future:{key}")
        evidence_expires_at = evidence_generated_at + timedelta(
            seconds=expected_max_age
        )
        if now >= evidence_expires_at:
            _fail(f"readiness_evidence_expired:{key}")
        effective_expires_at = min(
            effective_expires_at, evidence_expires_at
        )
    return effective_expires_at


def _normal_label(value: object) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _validate_room(
    snapshot: InputSnapshot,
    *,
    expected_head: str,
    expected_fingerprint: str,
    public_origin: str,
    now: datetime,
) -> None:
    room = snapshot.payload
    if set(room) != ROOM_RECEIPT_KEYS:
        _fail("room_receipt_schema_invalid")
    if (
        room.get("contract_name") != ROOM_CONTRACT
        or room.get("generated_by")
        != "scripts/materialize_memorial_room_audio_receipt.py"
        or room.get("proof_type") != "manual_room_attestation"
        or room.get("status") != "pass"
        or room.get("gold_claim_allowed") is not True
        or room.get("failed_codes") != []
        or room.get("dirty_worktree") is not False
        or room.get("slug") != MEMORIAL_SLUG
        or room.get("require_public_origin") is not True
        or room.get("runtime_source_revision_required") is not True
    ):
        _fail("room_receipt_not_exact_pass")
    if (
        room.get("source_git_head") != expected_head
        or room.get("head_semantics") != SOURCE_HEAD_SEMANTICS
        or room.get("source_state_fingerprint") != expected_fingerprint
        or room.get("source_state_fingerprint_semantics")
        != SOURCE_FINGERPRINT_SEMANTICS
        or room.get("runtime_source_revision") != expected_head
        or not _valid_sha(room.get("source_tree_fingerprint"), 64)
    ):
        _fail("room_source_or_runtime_binding_mismatch")
    if _public_origin(room.get("base_url")) != public_origin:
        _fail("room_public_origin_mismatch")
    generated_at = _parse_timestamp(
        room.get("generated_at"), label="room_generated_at"
    )
    if generated_at - now > MAX_FUTURE_SKEW:
        _fail("room_generated_at_future")
    checks = room.get("checks")
    if (
        not isinstance(checks, dict)
        or set(checks) != set(ROOM_AUDIO_CHECK_REQUIREMENTS)
        or any(value is not True for value in checks.values())
        or room.get("check_requirements") != ROOM_AUDIO_CHECK_REQUIREMENTS
    ):
        _fail("room_checks_invalid")
    for field, generic_values in GENERIC_ROOM_LABELS.items():
        normalized = _normal_label(room.get(field))
        if not normalized or normalized in generic_values:
            _fail(f"room_{field}_invalid")
    if not str(room.get("notes") or "").strip():
        _fail("room_notes_missing")
    attestation = room.get("manual_attestation")
    if (
        not isinstance(attestation, dict)
        or set(attestation)
        != {"attestation_id", "signed_at", "source", "ci_must_not_auto_assert"}
        or not str(attestation.get("attestation_id") or "").strip()
        or attestation.get("source") != "operator_room_review"
        or attestation.get("ci_must_not_auto_assert") is not True
    ):
        _fail("room_manual_attestation_invalid")
    signed_at = _parse_timestamp(
        attestation.get("signed_at"), label="room_attestation_signed_at"
    )
    if (
        abs(signed_at - generated_at) > MAX_FUTURE_SKEW
        or signed_at - now > MAX_FUTURE_SKEW
    ):
        _fail("room_attestation_time_invalid")


def _validate_voice(snapshot: InputSnapshot, *, now: datetime) -> None:
    voice = snapshot.payload
    if (
        voice.get("voice_profile_id") != MANFRED_VOICE_ID
        or voice.get("tts_plugin_voice_id") != MANFRED_VOICE_ID
        or voice.get("voice_label") != MANFRED_VOICE_LABEL
        or voice.get("lang") != MANFRED_VOICE_LANGUAGE
    ):
        _fail("voice_manfred_identity_mismatch")
    if any(
        voice.get(key) != value
        for key, value in UNMIXR_CLONE_CONTRACT.items()
    ):
        _fail("voice_unmixr_clone_contract_mismatch")
    if voice.get("synthetic_voice_clone_of_memorial_person") is not True:
        _fail("voice_synthetic_clone_disclosure_missing")
    consent = voice.get("voice_consent")
    if not isinstance(consent, dict):
        _fail("voice_consent_missing")
    if (
        consent.get("status") != "approved"
        or consent.get("scope") != VOICE_SCOPE
        or not str(consent.get("authorized_by") or "").strip()
        or consent.get("source_assets_reviewed") is not True
        or consent.get("revoked") is not False
    ):
        _fail("voice_consent_not_current")
    authorized_at = _parse_timestamp(
        consent.get("authorized_at"), label="voice_authorized_at"
    )
    if authorized_at - now > MAX_FUTURE_SKEW:
        _fail("voice_authorized_at_future")


def _validate_release_authority(
    manifest_snapshot: InputSnapshot,
    status_snapshot: InputSnapshot,
    project_modes_snapshot: InputSnapshot,
    *,
    expected_head: str,
    now: datetime,
) -> tuple[str, str]:
    manifest = manifest_snapshot.payload
    project_modes = project_modes_snapshot.payload
    issues = validate_release_authority(
        release_manifest=manifest,
        project_modes=project_modes,
        require_public_origin=True,
        require_explicit_deployment=True,
        require_clean_worktree=True,
        require_tracking_branch=True,
        require_source_remote_ref=True,
        require_compose_files=True,
    )
    if issues:
        _fail("canonical_release_authority_not_pass:" + ",".join(issues))
    if (
        manifest.get("contract_name") != RELEASE_MANIFEST_CONTRACT
        or manifest.get("commit_sha") != expected_head
        or manifest.get("deploy_context_commit_sha") != expected_head
        or manifest.get("project_mode") != REVIEWED_PROJECT_MODE
        or manifest.get("enabled_project_modes")
        != REVIEWED_ENABLED_PROJECT_MODES
        or manifest.get("dirty_worktree") is not False
        or manifest.get("source_worktree_dirty") is not False
        or manifest.get("source_dirty_count") != 0
        or manifest.get("source_dirty_files") != []
        or manifest.get("source_dirty_omitted_count") != 0
    ):
        _fail("release_manifest_binding_invalid")
    deployment_id = str(manifest.get("deployment_id") or "").strip()
    deployment_id_source = str(
        manifest.get("deployment_id_source") or ""
    ).strip()
    if (
        not deployment_id
        or deployment_id.startswith("local-")
        or not deployment_id_source
        or deployment_id_source == "local_fallback"
    ):
        _fail("release_deployment_id_not_authoritative")
    public_origin = _public_origin(manifest.get("public_origin"))
    manifest_generated_at = _parse_timestamp(
        manifest.get("generated_at"), label="release_manifest_generated_at"
    )
    if manifest_generated_at - now > MAX_FUTURE_SKEW:
        _fail("release_manifest_generated_at_future")

    declared_modes = {
        str(row.get("key") or "").strip().upper().replace("-", "_")
        for row in list(project_modes.get("modes") or [])
        if isinstance(row, dict)
    }
    if not set(REVIEWED_ENABLED_PROJECT_MODES).issubset(declared_modes):
        _fail("reviewed_project_modes_not_declared")

    status_payload = status_snapshot.payload
    gate = status_payload.get("gate")
    deploy_gate = status_payload.get("deploy_context_gate")
    if (
        status_payload.get("contract_name") != RELEASE_STATUS_CONTRACT
        or status_payload.get("state") != "clear"
        or status_payload.get("authority_posture")
        != "authoritative_runtime"
        or status_payload.get("issues") != []
        or not isinstance(gate, dict)
        or gate.get("contract_name") != RELEASE_GATE_CONTRACT
        or gate.get("status") != "pass"
        or gate.get("authority_posture") != "authoritative_runtime"
        or gate.get("issues") != []
        or not isinstance(deploy_gate, dict)
        or deploy_gate.get("contract_name") != DEPLOY_CONTEXT_GATE_CONTRACT
        or deploy_gate.get("status") != "pass"
        or deploy_gate.get("issues") != []
    ):
        _fail("release_authority_status_not_exact_pass")
    status_generated_at = _parse_timestamp(
        status_payload.get("generated_at"),
        label="release_authority_generated_at",
    )
    if status_generated_at - now > MAX_FUTURE_SKEW:
        _fail("release_authority_generated_at_future")
    for field in RELEASE_BINDING_FIELDS:
        expected = manifest.get(field)
        if status_payload.get(field) != expected or gate.get(field) != expected:
            _fail(f"release_authority_binding_mismatch:{field}")
    for field in (
        "deployment_id", "deployment_id_source", "public_origin",
        "public_origin_source", "repository", "branch", "tracking_branch",
        "commit_sha", "release_label", "project_mode",
        "enabled_project_modes", "compose_files", "compose_overrides",
    ):
        if deploy_gate.get(field) != manifest.get(field):
            _fail(f"deploy_context_gate_binding_mismatch:{field}")
    expected_declared_modes = [
        str(row.get("key") or "").strip()
        for row in list(project_modes.get("modes") or [])
        if isinstance(row, dict) and str(row.get("key") or "").strip()
    ]
    if status_payload.get("declared_project_modes") != expected_declared_modes:
        _fail("release_authority_declared_modes_mismatch")
    artifact_set = list(manifest.get("artifact_set") or [])
    if (
        status_payload.get("artifact_count") != len(artifact_set)
        or status_payload.get("artifact_set_preview") != artifact_set[:8]
    ):
        _fail("release_authority_artifact_set_mismatch")
    return public_origin, deployment_id


def _evidence_snapshots(evidence_root: Path) -> dict[str, InputSnapshot]:
    snapshots: dict[str, InputSnapshot] = {}
    for key, (receipt_name, _contract) in (
        readiness_materializer.EVIDENCE_RECEIPTS.items()
    ):
        snapshots[key] = _snapshot_json(
            evidence_root / receipt_name,
            label=f"readiness_evidence_{key}",
        )
    return snapshots


def _validated_release_payload(
    *,
    readiness_receipt_path: Path,
    readiness_evidence_root: Path,
    room_receipt_path: Path,
    tts_voice_path: Path,
    release_manifest_path: Path,
    release_authority_status_path: Path,
    project_modes_path: Path,
    expected_source_git_head: str,
    expected_source_state_fingerprint: str,
    generated_at: str,
    now: datetime | None,
) -> tuple[dict[str, Any], list[InputSnapshot]]:
    observed_now = _as_utc(now)
    expected_head, expected_fingerprint = _source_binding(
        expected_source_git_head=expected_source_git_head,
        expected_source_state_fingerprint=expected_source_state_fingerprint,
    )
    readiness = _snapshot_json(
        readiness_receipt_path, label="readiness_receipt"
    )
    evidence = _evidence_snapshots(readiness_evidence_root)
    room = _snapshot_json(room_receipt_path, label="room_audio_receipt")
    voice = _snapshot_json(
        tts_voice_path, label="tts_voice_consent", private=True
    )
    manifest = _snapshot_json(
        release_manifest_path, label="release_manifest"
    )
    authority = _snapshot_json(
        release_authority_status_path, label="release_authority_status"
    )
    project_modes = _snapshot_json(
        project_modes_path, label="project_modes"
    )
    snapshots = [
        readiness, *evidence.values(), room, voice, manifest, authority,
        project_modes,
    ]
    if (
        room.sha256 != evidence["room_audio"].sha256
        or room.raw != evidence["room_audio"].raw
    ):
        _fail("room_receipt_not_readiness_bound")

    _canonical_readiness_pass(
        receipt_path=readiness_receipt_path,
        evidence_root=readiness_evidence_root,
        expected_head=expected_head,
        expected_fingerprint=expected_fingerprint,
    )
    effective_expiry = _validate_readiness(
        readiness,
        evidence=evidence,
        expected_head=expected_head,
        expected_fingerprint=expected_fingerprint,
        now=observed_now,
    )
    public_origin, deployment_id = _validate_release_authority(
        manifest,
        authority,
        project_modes,
        expected_head=expected_head,
        now=observed_now,
    )
    _validate_room(
        room,
        expected_head=expected_head,
        expected_fingerprint=expected_fingerprint,
        public_origin=public_origin,
        now=observed_now,
    )
    _validate_voice(voice, now=observed_now)

    generated_time = (
        _parse_timestamp(generated_at, label="release_generated_at")
        if str(generated_at or "").strip()
        else observed_now
    )
    if abs(generated_time - observed_now) > MAX_FUTURE_SKEW:
        _fail("release_generated_at_not_current")
    if generated_time >= effective_expiry:
        _fail("release_generated_after_readiness_expiry")
    _assert_inputs_unchanged(snapshots)

    payload = {
        "contract_name": CONTRACT_NAME,
        "generated_by": GENERATED_BY,
        "generated_at": _format_timestamp(generated_time),
        "effective_expires_at": _format_timestamp(effective_expiry),
        "status": "pass",
        "memorial_slug": MEMORIAL_SLUG,
        "source_git_head": expected_head,
        "head_semantics": SOURCE_HEAD_SEMANTICS,
        "source_state_fingerprint": expected_fingerprint,
        "source_state_fingerprint_semantics": SOURCE_FINGERPRINT_SEMANTICS,
        "deployment_revision": expected_head,
        "deployment_id": deployment_id,
        "deployment_id_source": manifest.payload["deployment_id_source"],
        "public_origin": public_origin,
        "project_mode": REVIEWED_PROJECT_MODE,
        "enabled_project_modes": REVIEWED_ENABLED_PROJECT_MODES,
        # These are prerequisite/context statements only. They deliberately do
        # not assert root permit, deploy authority, runtime enablement, public
        # release, whole-project completion, or Gold status.
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
            "readiness_receipt": readiness.sha256,
            "room_audio_receipt": room.sha256,
            "tts_voice_consent": voice.sha256,
            "release_manifest": manifest.sha256,
            "release_authority_status": authority.sha256,
            "project_modes": project_modes.sha256,
        },
        "readiness_evidence_raw_sha256": {
            key: row.sha256 for key, row in evidence.items()
        },
    }
    if set(payload) != OUTPUT_KEYS:
        _fail("internal_output_schema_invalid")
    return payload, snapshots


def materialize_manfred_realtime_conversation_release(
    *,
    output_path: str | Path = DEFAULT_OUTPUT,
    readiness_receipt_path: str | Path = DEFAULT_READINESS_RECEIPT,
    readiness_evidence_root: str | Path = DEFAULT_READINESS_EVIDENCE_ROOT,
    room_receipt_path: str | Path = DEFAULT_ROOM_RECEIPT,
    tts_voice_path: str | Path = DEFAULT_TTS_VOICE,
    release_manifest_path: str | Path = DEFAULT_RELEASE_MANIFEST,
    release_authority_status_path: str | Path = DEFAULT_RELEASE_AUTHORITY_STATUS,
    project_modes_path: str | Path = DEFAULT_PROJECT_MODES,
    expected_source_git_head: str,
    expected_source_state_fingerprint: str,
    generated_at: str = "",
    now: datetime | None = None,
) -> dict[str, Any]:
    payload, snapshots = _validated_release_payload(
        readiness_receipt_path=Path(readiness_receipt_path),
        readiness_evidence_root=Path(readiness_evidence_root),
        room_receipt_path=Path(room_receipt_path),
        tts_voice_path=Path(tts_voice_path),
        release_manifest_path=Path(release_manifest_path),
        release_authority_status_path=Path(release_authority_status_path),
        project_modes_path=Path(project_modes_path),
        expected_source_git_head=expected_source_git_head,
        expected_source_state_fingerprint=expected_source_state_fingerprint,
        generated_at=generated_at,
        now=now,
    )
    _assert_inputs_unchanged(snapshots)
    _atomic_write(output_path, payload)
    return payload


def verify_manfred_realtime_conversation_release(
    *,
    receipt_path: str | Path = DEFAULT_OUTPUT,
    readiness_receipt_path: str | Path = DEFAULT_READINESS_RECEIPT,
    readiness_evidence_root: str | Path = DEFAULT_READINESS_EVIDENCE_ROOT,
    room_receipt_path: str | Path = DEFAULT_ROOM_RECEIPT,
    tts_voice_path: str | Path = DEFAULT_TTS_VOICE,
    release_manifest_path: str | Path = DEFAULT_RELEASE_MANIFEST,
    release_authority_status_path: str | Path = DEFAULT_RELEASE_AUTHORITY_STATUS,
    project_modes_path: str | Path = DEFAULT_PROJECT_MODES,
    expected_source_git_head: str,
    expected_source_state_fingerprint: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    try:
        receipt = _snapshot_json(
            receipt_path, label="release_receipt", private=True
        )
        generated_at = str(receipt.payload.get("generated_at") or "")
        expected, inputs = _validated_release_payload(
            readiness_receipt_path=Path(readiness_receipt_path),
            readiness_evidence_root=Path(readiness_evidence_root),
            room_receipt_path=Path(room_receipt_path),
            tts_voice_path=Path(tts_voice_path),
            release_manifest_path=Path(release_manifest_path),
            release_authority_status_path=Path(
                release_authority_status_path
            ),
            project_modes_path=Path(project_modes_path),
            expected_source_git_head=expected_source_git_head,
            expected_source_state_fingerprint=(
                expected_source_state_fingerprint
            ),
            generated_at=generated_at,
            now=now,
        )
        _assert_inputs_unchanged([receipt, *inputs])
        if receipt.payload != expected or set(receipt.payload) != OUTPUT_KEYS:
            _fail("release_receipt_content_mismatch")
    except ReleaseContractError as exc:
        return {
            "contract_name": VERIFY_CONTRACT_NAME,
            "status": "fail",
            "issues": [exc.code],
        }
    return {
        "contract_name": VERIFY_CONTRACT_NAME,
        "status": "pass",
        "issues": [],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Materialize or verify the host-side Manfred realtime "
            "conversation release receipt."
        )
    )
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument(
        "--readiness-receipt", default=str(DEFAULT_READINESS_RECEIPT)
    )
    parser.add_argument(
        "--readiness-evidence-root",
        default=str(DEFAULT_READINESS_EVIDENCE_ROOT),
    )
    parser.add_argument("--room-receipt", default=str(DEFAULT_ROOM_RECEIPT))
    parser.add_argument("--tts-voice", default=str(DEFAULT_TTS_VOICE))
    parser.add_argument(
        "--release-manifest", default=str(DEFAULT_RELEASE_MANIFEST)
    )
    parser.add_argument(
        "--release-authority-status",
        default=str(DEFAULT_RELEASE_AUTHORITY_STATUS),
    )
    parser.add_argument("--project-modes", default=str(DEFAULT_PROJECT_MODES))
    parser.add_argument("--expected-source-git-head", required=True)
    parser.add_argument(
        "--expected-source-state-fingerprint", required=True
    )
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    common = {
        "readiness_receipt_path": args.readiness_receipt,
        "readiness_evidence_root": args.readiness_evidence_root,
        "room_receipt_path": args.room_receipt,
        "tts_voice_path": args.tts_voice,
        "release_manifest_path": args.release_manifest,
        "release_authority_status_path": args.release_authority_status,
        "project_modes_path": args.project_modes,
        "expected_source_git_head": args.expected_source_git_head,
        "expected_source_state_fingerprint": (
            args.expected_source_state_fingerprint
        ),
    }
    try:
        if args.verify:
            result = verify_manfred_realtime_conversation_release(
                receipt_path=args.output, **common
            )
            exit_code = 0 if result["status"] == "pass" else 1
        else:
            result = materialize_manfred_realtime_conversation_release(
                output_path=args.output,
                generated_at=args.generated_at,
                **common,
            )
            exit_code = 0
    except ReleaseContractError as exc:
        result = {
            "contract_name": CONTRACT_NAME,
            "status": "fail",
            "issues": [exc.code],
        }
        exit_code = 1
    print(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2 if args.pretty else None,
            sort_keys=True,
        )
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
