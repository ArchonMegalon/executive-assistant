#!/usr/bin/env python3
"""Governed, one-shot public Blip STT proof executor.

This module intentionally has no "materialize an observation supplied by the
caller" API.  A passing proof can only be produced while this process holds a
protected one-time challenge, directly performs the HTTPS POST, validates the
live response, signs the sanitized result with a release-authorized Ed25519
key, and records terminal nonce consumption.

No audio bytes, audio digest, audio path, transcript, or transcript digest are
written to the challenge store, ticket, proof, or command output.
"""

from __future__ import annotations

import argparse
import base64
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from copy import deepcopy
import ctypes
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import fcntl
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import resource
import secrets
import ssl
import stat
import sys
from typing import Any
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
EA_ROOT = ROOT / "ea"
if str(EA_ROOT) not in sys.path:
    sys.path.insert(0, str(EA_ROOT))

from app.services.governed_spatial_contract import (  # noqa: E402
    bounded_sha256,
    parse_raw_json,
)
from app.services.governed_spatial_crypto import (  # noqa: E402
    Ed25519EnvelopeSigner,
    Ed25519KeyRecord,
    Ed25519KeyRegistry,
    KeyRegistryError,
    SignatureVerificationError,
    SpatialCryptoError,
    parse_timestamp,
    sign_envelope,
    verify_signed_envelope,
)


PUBLIC_ORIGIN = "https://myexternalbrain.com"
PUBLIC_ENDPOINT = f"{PUBLIC_ORIGIN}/memorials/manfred/speech-transcribe"
PUBLIC_HOST = "myexternalbrain.com"
PUBLIC_PATH = "/memorials/manfred/speech-transcribe"
MEMORIAL_SLUG = "manfred"
EXACT_TRANSCRIBER = "blipai/stt"
UPLOAD_AUTHORITY_PHRASE = "Aufnahme bestätigt. Upload erlaubt."
PROOF_SCOPE = "uncached_public_real_speech_blip_primary_stt"
EXPECTED_STT_POLICY = {
    "primary": "blipai",
    "fallbacks": ["cartesia", "1min.ai"],
}
EXPECTED_STT_POLICY_BINDING_SCHEMA = "ea.manfred_candidate_stt_policy_binding.v1"

CONTRACT_NAME = "ea.memorial_public_blip_stt_proof"
CONTRACT_VERSION = "2.0.0"
VERIFIER_CONTRACT_NAME = "ea.memorial_public_blip_stt_proof_verifier"
INTEGRITY_BINDING_CONTRACT_NAME = (
    "ea.memorial_public_blip_stt_sole_operator_integrity_binding"
)
INTEGRITY_BINDING_CONTRACT_VERSION = "1.0.0"
CHALLENGE_CONTRACT_NAME = "ea.memorial_public_blip_stt_challenge"
CHALLENGE_CONTRACT_VERSION = "1.0.0"
JOURNAL_SCHEMA = "ea_memorial_public_blip_stt_challenge_journal_v1"
GENERATED_BY = "scripts/materialize_memorial_public_blip_stt_proof.py"

DEFAULT_OUTPUT = ROOT / ".codex-studio/private/memorial_public_blip_stt_proof.generated.json"
DEFAULT_CHALLENGE_OUTPUT = (
    ROOT / ".codex-studio/private/memorial_public_blip_stt_challenge.generated.json"
)

MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_PROOF_BYTES = 256 * 1024
MAX_INTEGRITY_BINDING_BYTES = 128 * 1024
MAX_CHALLENGE_BYTES = 128 * 1024
MAX_REGISTRY_BYTES = 2 * 1024 * 1024
MAX_RESPONSE_BYTES = 256 * 1024
MAX_AUDIO_BYTES = 25 * 1024 * 1024
MAX_JOURNAL_BYTES = 16 * 1024 * 1024
MAX_JOURNAL_RECORD_BYTES = 8192
CHALLENGE_LIFETIME = timedelta(minutes=10)
PROOF_LIFETIME = timedelta(minutes=10)
MAX_INTEGRITY_BINDING_AGE = timedelta(hours=24)
MAX_DEPLOYMENT_AGE = timedelta(days=2)
HTTP_TIMEOUT_SECONDS = 60.0

_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_IMAGE_ID_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{15,199}$")
_CHALLENGE_RE = re.compile(r"^[0-9a-f]{64}$")
_KEY_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_ALLOWED_AUDIO_CONTENT_TYPES = frozenset(
    {"audio/mp4", "audio/mpeg", "audio/ogg", "audio/wav", "audio/webm"}
)
_JOURNAL_STATES = frozenset(
    {"issued", "execution_intent", "consumed_pass", "consumed_abort"}
)
_JOURNAL_KEYS = {
    "schema",
    "sequence",
    "prior_record_digest",
    "record_digest",
    "challenge_id",
    "state",
    "ticket_digest",
    "deployment_receipt_digest",
    "operator_integrity_payload_digest",
    "issued_at",
    "expires_at",
    "observed_at",
    "proof_digest",
    "failure_code",
}
_INTEGRITY_BINDING_KEYS = {
    "contract_name",
    "contract_version",
    "issuer",
    "environment",
    "issued_at",
    "expires_at",
    "scope",
    "deployment_binding",
    "operator_integrity_key",
    "signature",
}
_INTEGRITY_SCOPE_KEYS = {
    "proof_scope",
    "public_origin",
    "public_endpoint",
    "method",
    "memorial_slug",
    "real_audio_required",
    "operator_upload_confirmation_required",
}
_DEPLOYMENT_BINDING_KEYS = {
    "deployment_id",
    "source_revision",
    "image_id",
    "deployment_receipt_digest",
    "stt_policy",
    "stt_policy_binding",
}
_INTEGRITY_KEY_KEYS = {
    "issuer",
    "environment",
    "key_ref",
    "key_epoch",
    "key_fingerprint",
}
_CHALLENGE_KEYS = {
    "contract_name",
    "contract_version",
    "issuer",
    "environment",
    "issued_at",
    "expires_at",
    "challenge_id",
    "proof_scope",
    "public_endpoint",
    "memorial_slug",
    "deployment_binding",
    "operator_integrity_payload_digest",
    "operator_authorization_required",
    "real_audio_required",
    "transport_policy",
    "signature",
}
_TRANSPORT_POLICY = {
    "scheme": "https",
    "tls_certificate_verification": "required",
    "hostname_verification": "required",
    "proxy": "disabled",
    "redirects": "forbidden",
    "method": "POST",
}
_PROOF_KEYS = {
    "contract_name",
    "contract_version",
    "issuer",
    "environment",
    "issued_at",
    "expires_at",
    "generated_by",
    "proof_scope",
    "status",
    "proof_eligible",
    "challenge",
    "operator_authority",
    "public_request",
    "real_audio",
    "immutable_deployment",
    "integrity_evidence",
    "privacy",
    "claims",
    "signature",
}
_REQUIRED_DEPLOYMENT_CHECKS = frozenset(
    {
        "rollback_capsule_render_preflight",
        "candidate_promotion_evidence",
        "operator_integrity_binding_predeploy",
        "memorial_deploy_readiness_predeploy",
        "operator_integrity_binding_postdeploy",
        "memorial_deploy_readiness_postdeploy",
    }
)


class PublicBlipProofError(RuntimeError):
    """Static, redacted failure from the governed proof lane."""


@dataclass(frozen=True, slots=True)
class PrivateArtifact:
    payload: dict[str, Any]
    raw: bytes
    digest: str


@dataclass(frozen=True, slots=True)
class DeploymentBinding:
    deployment_id: str
    source_revision: str
    image_id: str
    deployment_receipt_digest: str
    stt_policy: dict[str, object]
    stt_policy_binding: dict[str, object]
    completed_at: datetime

    def as_dict(self) -> dict[str, object]:
        return {
            "deployment_id": self.deployment_id,
            "source_revision": self.source_revision,
            "image_id": self.image_id,
            "deployment_receipt_digest": self.deployment_receipt_digest,
            "stt_policy": deepcopy(self.stt_policy),
            "stt_policy_binding": deepcopy(self.stt_policy_binding),
        }


@dataclass(frozen=True, slots=True)
class OperatorIntegrityBinding:
    payload_digest: str
    executor_key: Ed25519KeyRecord
    envelope: dict[str, Any]


@dataclass(frozen=True, slots=True)
class HttpObservation:
    status_code: int
    headers: tuple[tuple[str, str], ...]
    body: bytes
    tls_certificate_verified: bool
    hostname_verified: bool
    proxy_used: bool
    redirect_count: int


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _iso(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise PublicBlipProofError("offset_aware_timestamp_required")
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _observed(value: datetime | None) -> datetime:
    result = value or _utc_now()
    if result.tzinfo is None or result.utcoffset() is None:
        raise PublicBlipProofError("observed_at_offset_required")
    return result.astimezone(UTC).replace(microsecond=0)


def _harden_sensitive_process() -> None:
    """Fail closed unless this process cannot emit a sensitive memory dump."""

    try:
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        if resource.getrlimit(resource.RLIMIT_CORE) != (0, 0):
            raise OSError("core_limit_not_zero")
    except (OSError, ValueError) as exc:
        raise PublicBlipProofError("process_core_dump_hardening_failed") from exc

    if not sys.platform.startswith("linux"):
        return
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        prctl = libc.prctl
        prctl.argtypes = [
            ctypes.c_int,
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.c_ulong,
        ]
        prctl.restype = ctypes.c_int
        if prctl(4, 0, 0, 0, 0) != 0:  # PR_SET_DUMPABLE
            raise OSError(ctypes.get_errno(), "prctl_set_dumpable_failed")
        if prctl(3, 0, 0, 0, 0) != 0:  # PR_GET_DUMPABLE
            raise OSError(ctypes.get_errno(), "process_remains_dumpable")
    except (AttributeError, OSError, ValueError) as exc:
        raise PublicBlipProofError("process_dumpable_hardening_failed") from exc


def _exact_keys(
    value: object,
    expected: set[str],
    reason: str,
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise PublicBlipProofError(reason)
    return dict(value)


def _path_has_symlink_component(path: Path) -> bool:
    absolute = Path(os.path.abspath(os.fspath(path)))
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        try:
            details = os.lstat(current)
        except FileNotFoundError:
            return False
        except OSError:
            return True
        if stat.S_ISLNK(details.st_mode):
            return True
    return False


def _verify_private_stat(
    details: os.stat_result,
    *,
    label: str,
    expected_uid: int,
    expected_gid: int,
    require_regular: bool = True,
) -> None:
    if require_regular and not stat.S_ISREG(details.st_mode):
        raise PublicBlipProofError(f"{label}_not_regular")
    if stat.S_IMODE(details.st_mode) != 0o600:
        raise PublicBlipProofError(f"{label}_mode_not_0600")
    if details.st_uid != expected_uid:
        raise PublicBlipProofError(f"{label}_uid_mismatch")
    if details.st_gid != expected_gid:
        raise PublicBlipProofError(f"{label}_gid_mismatch")
    if details.st_nlink != 1:
        raise PublicBlipProofError(f"{label}_link_count_invalid")


def _read_private_bytes(
    path: Path,
    *,
    label: str,
    expected_uid: int,
    expected_gid: int,
    maximum_bytes: int,
    minimum_bytes: int = 1,
) -> bytes:
    if _path_has_symlink_component(path):
        raise PublicBlipProofError(f"{label}_symlink_forbidden")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise PublicBlipProofError(f"{label}_unavailable") from exc
    try:
        before = os.fstat(descriptor)
        _verify_private_stat(
            before,
            label=label,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
        )
        if not minimum_bytes <= before.st_size <= maximum_bytes:
            raise PublicBlipProofError(f"{label}_size_invalid")
        chunks: list[bytes] = []
        remaining = int(before.st_size)
        while remaining:
            chunk = os.read(descriptor, min(remaining, 65_536))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(descriptor)
        if (
            len(raw) != before.st_size
            or (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino)
            or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or before.st_ctime_ns != after.st_ctime_ns
            or before.st_mode != after.st_mode
            or before.st_uid != after.st_uid
            or before.st_gid != after.st_gid
            or before.st_nlink != after.st_nlink
        ):
            raise PublicBlipProofError(f"{label}_changed_during_read")
        linked = os.stat(path, follow_symlinks=False)
        if (linked.st_dev, linked.st_ino) != (before.st_dev, before.st_ino):
            raise PublicBlipProofError(f"{label}_retargeted_during_read")
        return raw
    finally:
        os.close(descriptor)


def _load_private_json(
    path: Path,
    *,
    label: str,
    expected_uid: int,
    expected_gid: int,
    maximum_bytes: int,
) -> PrivateArtifact:
    raw = _read_private_bytes(
        path,
        label=label,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
        maximum_bytes=maximum_bytes,
    )
    try:
        payload = parse_raw_json(raw)
    except (TypeError, ValueError) as exc:
        raise PublicBlipProofError(f"{label}_json_invalid") from exc
    if not isinstance(payload, dict):
        raise PublicBlipProofError(f"{label}_json_object_required")
    return PrivateArtifact(
        payload=dict(payload),
        raw=raw,
        digest="sha256:" + hashlib.sha256(raw).hexdigest(),
    )


def _prepare_private_directory(
    path: Path,
    *,
    label: str,
    expected_uid: int,
    expected_gid: int,
) -> None:
    if _path_has_symlink_component(path.parent):
        raise PublicBlipProofError(f"{label}_parent_symlink_forbidden")
    try:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    except OSError as exc:
        raise PublicBlipProofError(f"{label}_unavailable") from exc
    if _path_has_symlink_component(path):
        raise PublicBlipProofError(f"{label}_symlink_forbidden")
    details = os.stat(path, follow_symlinks=False)
    if not stat.S_ISDIR(details.st_mode):
        raise PublicBlipProofError(f"{label}_not_directory")
    if stat.S_IMODE(details.st_mode) != 0o700:
        raise PublicBlipProofError(f"{label}_mode_not_0700")
    if details.st_uid != expected_uid or details.st_gid != expected_gid:
        raise PublicBlipProofError(f"{label}_owner_mismatch")


def _preflight_output(
    path: Path,
    *,
    label: str,
    expected_uid: int,
    expected_gid: int,
) -> None:
    parent = path.parent
    _prepare_private_directory(
        parent,
        label="proof_output_directory",
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    try:
        details = os.lstat(path)
    except FileNotFoundError:
        return
    if stat.S_ISLNK(details.st_mode) or not stat.S_ISREG(details.st_mode):
        raise PublicBlipProofError("proof_output_target_invalid")
    _verify_private_stat(
        details,
        label=label,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    raise PublicBlipProofError(f"{label}_already_exists")


def _atomic_write_private_bytes(
    path: Path,
    raw: bytes,
    *,
    label: str,
    expected_uid: int,
    expected_gid: int,
) -> None:
    _preflight_output(
        path,
        label=label,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    parent_flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    directory_fd = os.open(path.parent, parent_flags)
    temporary_name = f".{path.name}.{secrets.token_hex(16)}.tmp"
    descriptor: int | None = None
    temporary_exists = False
    try:
        descriptor = os.open(
            temporary_name,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=directory_fd,
        )
        temporary_exists = True
        os.fchmod(descriptor, 0o600)
        details = os.fstat(descriptor)
        _verify_private_stat(
            details,
            label=f"{label}_temporary",
            expected_uid=expected_uid,
            expected_gid=expected_gid,
        )
        offset = 0
        while offset < len(raw):
            written = os.write(descriptor, raw[offset:])
            if written <= 0:
                raise OSError("private_output_short_write")
            offset += written
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        try:
            os.link(
                temporary_name,
                path.name,
                src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd,
                follow_symlinks=False,
            )
        except FileExistsError as exc:
            raise PublicBlipProofError(f"{label}_already_exists") from exc
        os.unlink(temporary_name, dir_fd=directory_fd)
        temporary_exists = False
        os.fsync(directory_fd)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary_exists:
            try:
                os.unlink(temporary_name, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
        os.close(directory_fd)
    reopened = _read_private_bytes(
        path,
        label=label,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
        maximum_bytes=max(len(raw), 1),
        minimum_bytes=len(raw),
    )
    if reopened != raw:
        raise PublicBlipProofError(f"{label}_reopen_mismatch")


def _json_bytes(payload: Mapping[str, object]) -> bytes:
    try:
        return (
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PublicBlipProofError("json_serialization_failed") from exc


def _reject_response_constant(value: str) -> None:
    raise ValueError(f"invalid_json_constant:{value}")


def _reject_response_duplicate_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def _parse_public_response_json(raw: bytes) -> dict[str, object]:
    """Duplicate-safe JSON that permits normal finite timing floats."""

    try:
        value = json.loads(
            raw.decode("utf-8"),
            parse_constant=_reject_response_constant,
            object_pairs_hook=_reject_response_duplicate_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise PublicBlipProofError("public_response_json_invalid") from exc
    if not isinstance(value, dict):
        raise PublicBlipProofError("public_response_json_object_required")
    return dict(value)


def _load_registry(
    path: Path,
    *,
    expected_uid: int,
    expected_gid: int,
) -> Ed25519KeyRegistry:
    artifact = _load_private_json(
        path,
        label="trusted_key_registry",
        expected_uid=expected_uid,
        expected_gid=expected_gid,
        maximum_bytes=MAX_REGISTRY_BYTES,
    )
    payload = artifact.payload
    if set(payload) != {
        "schema_name",
        "records",
        "revocation_events",
        "registry_digest",
    }:
        raise PublicBlipProofError("trusted_key_registry_schema_invalid")
    material = {
        "schema_name": payload.get("schema_name"),
        "records": payload.get("records"),
        "revocation_events": payload.get("revocation_events"),
    }
    if material["schema_name"] != "governed_spatial_ed25519_key_registry_v1":
        raise PublicBlipProofError("trusted_key_registry_schema_invalid")
    if payload.get("registry_digest") != bounded_sha256(material, prefixed=True):
        raise PublicBlipProofError("trusted_key_registry_integrity_failed")
    rows = material["records"]
    events = material["revocation_events"]
    if not isinstance(rows, list) or not isinstance(events, list):
        raise PublicBlipProofError("trusted_key_registry_collections_invalid")
    try:
        records = [
            Ed25519KeyRecord.from_dict(row)
            for row in rows
            if isinstance(row, dict)
        ]
        if len(records) != len(rows) or any(not isinstance(row, dict) for row in events):
            raise ValueError
        return Ed25519KeyRegistry(records)
    except (KeyRegistryError, SignatureVerificationError, ValueError) as exc:
        raise PublicBlipProofError("trusted_key_registry_invalid") from exc


def _validate_stt_policy(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or value != EXPECTED_STT_POLICY:
        raise PublicBlipProofError("deployment_stt_policy_invalid")
    return deepcopy(EXPECTED_STT_POLICY)


def _validate_deployment(
    artifact: PrivateArtifact,
    *,
    observed_at: datetime,
) -> DeploymentBinding:
    receipt = artifact.payload
    if (
        receipt.get("contract_name") != "ea.memorial_joint_api_ingress_deploy.v2"
        or receipt.get("status") != "pass"
    ):
        raise PublicBlipProofError("deployment_receipt_not_passing")
    deployment_id = receipt.get("deployment_id")
    source_revision = receipt.get("source_revision")
    image_id = (
        dict(receipt.get("candidate_image"))
        if isinstance(receipt.get("candidate_image"), dict)
        else {}
    ).get("image_id")
    if not isinstance(deployment_id, str) or not _SAFE_ID_RE.fullmatch(deployment_id):
        raise PublicBlipProofError("deployment_id_invalid")
    if not isinstance(source_revision, str) or not _GIT_SHA_RE.fullmatch(source_revision):
        raise PublicBlipProofError("deployment_source_revision_invalid")
    if not isinstance(image_id, str) or not _IMAGE_ID_RE.fullmatch(image_id):
        raise PublicBlipProofError("deployment_image_id_invalid")
    try:
        completed_at = parse_timestamp(receipt.get("completed_at"))
    except SignatureVerificationError as exc:
        raise PublicBlipProofError("deployment_completed_at_invalid") from exc
    if completed_at > observed_at or observed_at - completed_at > MAX_DEPLOYMENT_AGE:
        raise PublicBlipProofError("deployment_not_current")

    release_source = (
        dict(receipt.get("release_source"))
        if isinstance(receipt.get("release_source"), dict)
        else {}
    )
    candidate = (
        dict(receipt.get("candidate_promotion_evidence"))
        if isinstance(receipt.get("candidate_promotion_evidence"), dict)
        else {}
    )
    runtime_identity = (
        dict(candidate.get("runtime_identity"))
        if isinstance(candidate.get("runtime_identity"), dict)
        else {}
    )
    if (
        release_source.get("source_revision") != source_revision
        or candidate.get("status") != "pass"
        or candidate.get("source_revision") != source_revision
        or candidate.get("image_id") != image_id
        or candidate.get("runtime_revision_matches_image") is not True
        or runtime_identity.get("source_revision") != source_revision
        or runtime_identity.get("authority_commit") != source_revision
        or runtime_identity.get("oci_image_revision") != source_revision
        or runtime_identity.get("revision_agreement_verified") is not True
    ):
        raise PublicBlipProofError("deployment_immutable_identity_invalid")

    policy = _validate_stt_policy(receipt.get("stt_policy"))
    if candidate.get("stt_policy") != policy:
        raise PublicBlipProofError("deployment_candidate_stt_policy_mismatch")
    policy_binding = (
        dict(receipt.get("stt_policy_binding"))
        if isinstance(receipt.get("stt_policy_binding"), dict)
        else {}
    )
    candidate_policy_binding = (
        dict(candidate.get("stt_policy_binding"))
        if isinstance(candidate.get("stt_policy_binding"), dict)
        else {}
    )
    if (
        policy_binding != candidate_policy_binding
        or policy_binding.get("schema") != EXPECTED_STT_POLICY_BINDING_SCHEMA
        or policy_binding.get("probe_source")
        != "candidate_api_container_runtime_contract"
        or policy_binding.get("source_revision") != source_revision
        or policy_binding.get("image_id") != image_id
        or not isinstance(policy_binding.get("api_container_id"), str)
        or re.fullmatch(r"[0-9a-f]{64}", str(policy_binding.get("api_container_id")))
        is None
    ):
        raise PublicBlipProofError("deployment_stt_policy_binding_invalid")

    check_names = [
        str(row.get("name") or "")
        for row in receipt.get("checks", [])
        if isinstance(row, dict) and row.get("status") == "pass"
    ]
    if any(check_names.count(name) != 1 for name in _REQUIRED_DEPLOYMENT_CHECKS):
        raise PublicBlipProofError("deployment_required_checks_invalid")
    joint = (
        dict(receipt.get("joint_atomicity"))
        if isinstance(receipt.get("joint_atomicity"), dict)
        else {}
    )
    if (
        joint.get("transaction_status") != "committed"
        or joint.get("api_rollback_baseline_verified") is not True
        or joint.get("ingress_rollback_baseline_verified") is not True
        or joint.get("network_rollback_baseline_captured") is not True
        or joint.get("public_edge_rollback_baseline_captured") is not True
    ):
        raise PublicBlipProofError("deployment_transaction_not_committed")
    rollback = (
        dict(receipt.get("rollback"))
        if isinstance(receipt.get("rollback"), dict)
        else {}
    )
    capsule = (
        dict(receipt.get("rollback_capsule"))
        if isinstance(receipt.get("rollback_capsule"), dict)
        else {}
    )
    preflight = (
        dict(receipt.get("rollback_render_preflight"))
        if isinstance(receipt.get("rollback_render_preflight"), dict)
        else {}
    )
    cleanup = (
        dict(receipt.get("recovery_journal_cleanup"))
        if isinstance(receipt.get("recovery_journal_cleanup"), dict)
        else {}
    )
    if (
        rollback.get("status") != "available"
        or capsule.get("status") != "sealed"
        or capsule.get("mode") != "0600"
        or preflight.get("status") != "pass"
        or preflight.get("capsule_sha256") != capsule.get("sha256")
        or cleanup.get("status") != "removed"
    ):
        raise PublicBlipProofError("deployment_rollback_posture_invalid")
    return DeploymentBinding(
        deployment_id=deployment_id,
        source_revision=source_revision,
        image_id=image_id,
        deployment_receipt_digest=artifact.digest,
        stt_policy=policy,
        stt_policy_binding=policy_binding,
        completed_at=completed_at,
    )


def _key_identity(record: Ed25519KeyRecord) -> dict[str, object]:
    return {
        "issuer": record.issuer,
        "environment": record.environment,
        "key_ref": record.key_ref,
        "key_epoch": record.key_epoch,
        "key_fingerprint": record.fingerprint,
    }


def _validate_operator_integrity_binding(
    artifact: PrivateArtifact,
    *,
    registry: Ed25519KeyRegistry,
    deployment: DeploymentBinding,
    observed_at: datetime,
) -> OperatorIntegrityBinding:
    envelope = artifact.payload
    _exact_keys(
        envelope,
        _INTEGRITY_BINDING_KEYS,
        "operator_integrity_binding_schema_invalid",
    )
    if (
        envelope.get("contract_name") != INTEGRITY_BINDING_CONTRACT_NAME
        or envelope.get("contract_version") != INTEGRITY_BINDING_CONTRACT_VERSION
    ):
        raise PublicBlipProofError("operator_integrity_binding_contract_invalid")
    try:
        verification = verify_signed_envelope(
            envelope,
            registry,
            observed_at=observed_at,
            maximum_receipt_age=MAX_INTEGRITY_BINDING_AGE,
        )
    except SpatialCryptoError as exc:
        raise PublicBlipProofError("operator_integrity_signature_invalid") from exc
    scope = _exact_keys(
        envelope.get("scope"),
        _INTEGRITY_SCOPE_KEYS,
        "operator_integrity_scope_schema_invalid",
    )
    expected_scope = {
        "proof_scope": PROOF_SCOPE,
        "public_origin": PUBLIC_ORIGIN,
        "public_endpoint": PUBLIC_ENDPOINT,
        "method": "POST",
        "memorial_slug": MEMORIAL_SLUG,
        "real_audio_required": True,
        "operator_upload_confirmation_required": True,
    }
    if scope != expected_scope:
        raise PublicBlipProofError("operator_integrity_scope_invalid")
    deployment_binding = _exact_keys(
        envelope.get("deployment_binding"),
        _DEPLOYMENT_BINDING_KEYS,
        "operator_integrity_deployment_binding_schema_invalid",
    )
    if deployment_binding != deployment.as_dict():
        raise PublicBlipProofError("operator_integrity_deployment_binding_invalid")
    key_value = _exact_keys(
        envelope.get("operator_integrity_key"),
        _INTEGRITY_KEY_KEYS,
        "operator_integrity_key_schema_invalid",
    )
    key_ref = key_value.get("key_ref")
    key_epoch = key_value.get("key_epoch")
    if (
        not isinstance(key_ref, str)
        or not _KEY_REF_RE.fullmatch(key_ref)
        or isinstance(key_epoch, bool)
        or not isinstance(key_epoch, int)
    ):
        raise PublicBlipProofError("operator_integrity_key_invalid")
    try:
        executor_key = registry.resolve(
            str(key_value.get("issuer") or ""),
            str(key_value.get("environment") or ""),
            key_ref,
            key_epoch,
        )
    except SpatialCryptoError as exc:
        raise PublicBlipProofError("operator_integrity_key_untrusted") from exc
    if executor_key.state != "active" or key_value != _key_identity(executor_key):
        raise PublicBlipProofError("operator_integrity_key_untrusted")
    # Sole-operator trust model: this signature is tamper evidence only, not a
    # second-person approval. The exact upload phrase is the sole authorization.
    if verification.key_identity != executor_key.identity:
        raise PublicBlipProofError("operator_integrity_signer_mismatch")
    if envelope.get("environment") != executor_key.environment:
        raise PublicBlipProofError("operator_integrity_environment_mismatch")
    if executor_key.environment != "production":
        raise PublicBlipProofError("operator_integrity_environment_not_production")
    try:
        authority_expiry = parse_timestamp(envelope.get("expires_at"))
        executor_not_after = parse_timestamp(executor_key.not_after)
    except SignatureVerificationError as exc:
        raise PublicBlipProofError("operator_integrity_timestamp_invalid") from exc
    if authority_expiry > executor_not_after:
        raise PublicBlipProofError("operator_integrity_exceeds_key_window")
    return OperatorIntegrityBinding(
        payload_digest=verification.payload_digest,
        executor_key=executor_key,
        envelope=deepcopy(envelope),
    )


def _load_signer(
    path: Path,
    *,
    expected_uid: int,
    expected_gid: int,
    key_record: Ed25519KeyRecord,
) -> Ed25519EnvelopeSigner:
    seed = bytearray(
        _read_private_bytes(
            path,
            label="operator_integrity_signing_key",
            expected_uid=expected_uid,
            expected_gid=expected_gid,
            maximum_bytes=32,
            minimum_bytes=32,
        )
    )
    try:
        if len(seed) != 32:
            raise PublicBlipProofError("operator_integrity_signing_key_size_invalid")
        signer = Ed25519EnvelopeSigner.from_seed(
            bytes(seed),
            issuer=key_record.issuer,
            environment=key_record.environment,
            key_ref=key_record.key_ref,
            key_epoch=key_record.key_epoch,
            not_before=key_record.not_before,
            not_after=key_record.not_after,
        )
    except (KeyRegistryError, ValueError) as exc:
        raise PublicBlipProofError("operator_integrity_signing_key_invalid") from exc
    finally:
        for index in range(len(seed)):
            seed[index] = 0
    if signer.key_record.fingerprint != key_record.fingerprint:
        raise PublicBlipProofError(
            "operator_integrity_signing_key_not_registered"
        )
    return signer


class ChallengeJournal:
    """Protected hash-chained one-time challenge state."""

    def __init__(
        self,
        root: Path,
        *,
        expected_uid: int,
        expected_gid: int,
    ) -> None:
        self.root = Path(os.path.abspath(os.fspath(root)))
        self.expected_uid = expected_uid
        self.expected_gid = expected_gid
        _prepare_private_directory(
            self.root,
            label="challenge_state",
            expected_uid=expected_uid,
            expected_gid=expected_gid,
        )
        self.lock_path = self.root / ".challenge.lock"
        self.journal_path = self.root / "challenge.journal.jsonl"
        self.pending_path = self.root / "challenge.journal.pending.json"

    def _open_owned_file(self, path: Path, *, create: bool, append: bool = False) -> int:
        flags = (
            os.O_RDWR
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        if create:
            flags |= os.O_CREAT
        if append:
            flags |= os.O_APPEND
        descriptor = os.open(path, flags, 0o600)
        os.fchmod(descriptor, 0o600)
        try:
            _verify_private_stat(
                os.fstat(descriptor),
                label="challenge_state_file",
                expected_uid=self.expected_uid,
                expected_gid=self.expected_gid,
            )
        except Exception:
            os.close(descriptor)
            raise
        return descriptor

    @contextmanager
    def locked(self, *, recover_pending: bool) -> Iterator[list[dict[str, Any]]]:
        lock_fd = self._open_owned_file(self.lock_path, create=True)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            journal_fd = self._open_owned_file(
                self.journal_path,
                create=True,
                append=True,
            )
            try:
                records = self._read_records(journal_fd)
                if os.path.lexists(self.pending_path):
                    if not recover_pending:
                        raise PublicBlipProofError("challenge_journal_pending_recovery")
                    self._recover_pending(journal_fd, records)
                    records = self._read_records(journal_fd)
                if recover_pending:
                    self._recover_interrupted_executions(journal_fd, records)
                yield records
            finally:
                os.close(journal_fd)
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)

    def _read_records(self, journal_fd: int) -> list[dict[str, Any]]:
        os.lseek(journal_fd, 0, os.SEEK_SET)
        details = os.fstat(journal_fd)
        if details.st_size > MAX_JOURNAL_BYTES:
            raise PublicBlipProofError("challenge_journal_too_large")
        raw = b""
        remaining = int(details.st_size)
        while remaining:
            chunk = os.read(journal_fd, min(remaining, 65_536))
            if not chunk:
                break
            raw += chunk
            remaining -= len(chunk)
        if len(raw) != details.st_size or (raw and not raw.endswith(b"\n")):
            raise PublicBlipProofError("challenge_journal_truncated")
        records: list[dict[str, Any]] = []
        for line in raw.splitlines():
            if not line or len(line) > MAX_JOURNAL_RECORD_BYTES:
                raise PublicBlipProofError("challenge_journal_record_size_invalid")
            try:
                parsed = parse_raw_json(line)
            except (TypeError, ValueError) as exc:
                raise PublicBlipProofError("challenge_journal_json_invalid") from exc
            if not isinstance(parsed, dict):
                raise PublicBlipProofError("challenge_journal_record_invalid")
            records.append(dict(parsed))
        self._validate_records(records)
        return records

    def _recover_interrupted_executions(
        self,
        journal_fd: int,
        records: list[dict[str, Any]],
    ) -> None:
        latest: dict[str, dict[str, Any]] = {}
        for record in records:
            latest[str(record["challenge_id"])] = record
        for challenge_id, record in tuple(latest.items()):
            if record.get("state") != "execution_intent":
                continue
            self.append(
                journal_fd,
                records,
                challenge_id=challenge_id,
                state_value="consumed_abort",
                ticket_digest=str(record["ticket_digest"]),
                deployment_receipt_digest=str(
                    record["deployment_receipt_digest"]
                ),
                operator_integrity_payload_digest=str(
                    record["operator_integrity_payload_digest"]
                ),
                issued_at=str(record["issued_at"]),
                expires_at=str(record["expires_at"]),
                observed_at=_iso(_utc_now()),
                failure_code="interrupted_execution_consumed",
            )

    @staticmethod
    def _record_material(record: Mapping[str, object]) -> dict[str, object]:
        material = dict(record)
        material.pop("record_digest", None)
        return material

    def _validate_records(self, records: list[dict[str, Any]]) -> None:
        prior = "sha256:" + ("0" * 64)
        states: dict[str, str] = {}
        ticket_by_challenge: dict[str, str] = {}
        for sequence, record in enumerate(records, start=1):
            if set(record) != _JOURNAL_KEYS or record.get("schema") != JOURNAL_SCHEMA:
                raise PublicBlipProofError("challenge_journal_record_schema_invalid")
            if record.get("sequence") != sequence or record.get("prior_record_digest") != prior:
                raise PublicBlipProofError("challenge_journal_chain_invalid")
            expected_digest = bounded_sha256(self._record_material(record), prefixed=True)
            if record.get("record_digest") != expected_digest:
                raise PublicBlipProofError("challenge_journal_record_digest_invalid")
            challenge_id = record.get("challenge_id")
            state_value = record.get("state")
            if (
                not isinstance(challenge_id, str)
                or not _CHALLENGE_RE.fullmatch(challenge_id)
                or state_value not in _JOURNAL_STATES
                or not _SHA256_RE.fullmatch(str(record.get("ticket_digest") or ""))
                or not _SHA256_RE.fullmatch(
                    str(record.get("deployment_receipt_digest") or "")
                )
                or not _SHA256_RE.fullmatch(
                    str(record.get("operator_integrity_payload_digest") or "")
                )
            ):
                raise PublicBlipProofError("challenge_journal_record_invalid")
            previous_state = states.get(challenge_id)
            if state_value == "issued":
                if previous_state is not None:
                    raise PublicBlipProofError("challenge_journal_replay")
                if record.get("proof_digest") is not None or record.get("failure_code") is not None:
                    raise PublicBlipProofError("challenge_journal_issued_shape_invalid")
                ticket_by_challenge[challenge_id] = str(record["ticket_digest"])
            elif state_value == "execution_intent":
                if previous_state != "issued":
                    raise PublicBlipProofError("challenge_journal_transition_invalid")
                if record.get("proof_digest") is not None or record.get("failure_code") is not None:
                    raise PublicBlipProofError("challenge_journal_intent_shape_invalid")
            elif state_value == "consumed_pass":
                if previous_state != "execution_intent":
                    raise PublicBlipProofError("challenge_journal_transition_invalid")
                if (
                    not _SHA256_RE.fullmatch(str(record.get("proof_digest") or ""))
                    or record.get("failure_code") is not None
                ):
                    raise PublicBlipProofError("challenge_journal_pass_shape_invalid")
            else:
                if (
                    previous_state != "execution_intent"
                    or record.get("proof_digest") is not None
                    or not isinstance(record.get("failure_code"), str)
                    or not _SAFE_ID_RE.fullmatch(str(record.get("failure_code") or ""))
                ):
                    raise PublicBlipProofError("challenge_journal_abort_shape_invalid")
            if (
                challenge_id in ticket_by_challenge
                and record.get("ticket_digest") != ticket_by_challenge[challenge_id]
            ):
                raise PublicBlipProofError("challenge_journal_ticket_substitution")
            states[challenge_id] = str(state_value)
            prior = expected_digest

    def _pending_payload(self, record: Mapping[str, object]) -> dict[str, object]:
        encoded = _json_bytes(record)
        return {
            "schema": "ea_memorial_public_blip_stt_challenge_pending_v1",
            "record_digest": record["record_digest"],
            "record_encoding": "base64url_no_padding",
            "record_bytes": base64.urlsafe_b64encode(encoded).decode("ascii").rstrip("="),
        }

    def _recover_pending(
        self,
        journal_fd: int,
        records: list[dict[str, Any]],
    ) -> None:
        pending = _load_private_json(
            self.pending_path,
            label="challenge_journal_pending",
            expected_uid=self.expected_uid,
            expected_gid=self.expected_gid,
            maximum_bytes=MAX_JOURNAL_RECORD_BYTES * 2,
        ).payload
        if set(pending) != {
            "schema",
            "record_digest",
            "record_encoding",
            "record_bytes",
        } or pending.get("schema") != "ea_memorial_public_blip_stt_challenge_pending_v1":
            raise PublicBlipProofError("challenge_journal_pending_invalid")
        encoded = pending.get("record_bytes")
        if not isinstance(encoded, str) or pending.get("record_encoding") != "base64url_no_padding":
            raise PublicBlipProofError("challenge_journal_pending_invalid")
        try:
            padding = "=" * (-len(encoded) % 4)
            raw = base64.b64decode(
                (encoded + padding).encode("ascii"),
                altchars=b"-_",
                validate=True,
            )
            if base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=") != encoded:
                raise ValueError
            parsed = parse_raw_json(raw)
        except (UnicodeEncodeError, ValueError, TypeError) as exc:
            raise PublicBlipProofError("challenge_journal_pending_invalid") from exc
        if (
            not isinstance(parsed, dict)
            or parsed.get("record_digest") != pending.get("record_digest")
        ):
            raise PublicBlipProofError("challenge_journal_pending_invalid")
        record = dict(parsed)
        if records and records[-1].get("record_digest") == record.get("record_digest"):
            self.pending_path.unlink()
            self._fsync_root()
            return
        candidate = [*records, record]
        self._validate_records(candidate)
        self._append_raw(journal_fd, raw)
        self.pending_path.unlink()
        self._fsync_root()

    def _fsync_root(self) -> None:
        descriptor = os.open(
            self.root,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0),
        )
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _append_raw(self, journal_fd: int, raw: bytes) -> None:
        if len(raw) > MAX_JOURNAL_RECORD_BYTES or not raw.endswith(b"\n"):
            raise PublicBlipProofError("challenge_journal_record_size_invalid")
        os.lseek(journal_fd, 0, os.SEEK_END)
        offset = 0
        while offset < len(raw):
            written = os.write(journal_fd, raw[offset:])
            if written <= 0:
                raise OSError("challenge_journal_short_write")
            offset += written
        os.fsync(journal_fd)

    def append(
        self,
        journal_fd: int,
        records: list[dict[str, Any]],
        *,
        challenge_id: str,
        state_value: str,
        ticket_digest: str,
        deployment_receipt_digest: str,
        operator_integrity_payload_digest: str,
        issued_at: str,
        expires_at: str,
        observed_at: str,
        proof_digest: str | None = None,
        failure_code: str | None = None,
    ) -> dict[str, Any]:
        record: dict[str, Any] = {
            "schema": JOURNAL_SCHEMA,
            "sequence": len(records) + 1,
            "prior_record_digest": (
                str(records[-1]["record_digest"])
                if records
                else "sha256:" + ("0" * 64)
            ),
            "record_digest": "",
            "challenge_id": challenge_id,
            "state": state_value,
            "ticket_digest": ticket_digest,
            "deployment_receipt_digest": deployment_receipt_digest,
            "operator_integrity_payload_digest": operator_integrity_payload_digest,
            "issued_at": issued_at,
            "expires_at": expires_at,
            "observed_at": observed_at,
            "proof_digest": proof_digest,
            "failure_code": failure_code,
        }
        record["record_digest"] = bounded_sha256(
            self._record_material(record),
            prefixed=True,
        )
        self._validate_records([*records, record])
        if os.path.lexists(self.pending_path):
            raise PublicBlipProofError("challenge_journal_pending_recovery")
        pending_raw = _json_bytes(self._pending_payload(record))
        descriptor = os.open(
            self.pending_path,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            os.fchmod(descriptor, 0o600)
            _verify_private_stat(
                os.fstat(descriptor),
                label="challenge_journal_pending",
                expected_uid=self.expected_uid,
                expected_gid=self.expected_gid,
            )
            offset = 0
            while offset < len(pending_raw):
                written = os.write(descriptor, pending_raw[offset:])
                if written <= 0:
                    raise OSError("challenge_pending_short_write")
                offset += written
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        self._fsync_root()
        record_raw = _json_bytes(record)
        self._append_raw(journal_fd, record_raw)
        self.pending_path.unlink()
        self._fsync_root()
        records.append(record)
        return record

    @staticmethod
    def records_for(
        records: list[dict[str, Any]],
        challenge_id: str,
    ) -> list[dict[str, Any]]:
        return [
            deepcopy(record)
            for record in records
            if record.get("challenge_id") == challenge_id
        ]


def _challenge_unsigned(
    *,
    challenge_id: str,
    issued_at: datetime,
    expires_at: datetime,
    signer: Ed25519EnvelopeSigner,
    deployment: DeploymentBinding,
    authority: OperatorIntegrityBinding,
) -> dict[str, object]:
    return {
        "contract_name": CHALLENGE_CONTRACT_NAME,
        "contract_version": CHALLENGE_CONTRACT_VERSION,
        "issuer": signer.key_record.issuer,
        "environment": signer.key_record.environment,
        "issued_at": _iso(issued_at),
        "expires_at": _iso(expires_at),
        "challenge_id": challenge_id,
        "proof_scope": PROOF_SCOPE,
        "public_endpoint": PUBLIC_ENDPOINT,
        "memorial_slug": MEMORIAL_SLUG,
        "deployment_binding": deployment.as_dict(),
        "operator_integrity_payload_digest": authority.payload_digest,
        "operator_authorization_required": True,
        "real_audio_required": True,
        "transport_policy": deepcopy(_TRANSPORT_POLICY),
    }


def _validate_challenge(
    artifact: PrivateArtifact,
    *,
    registry: Ed25519KeyRegistry,
    deployment: DeploymentBinding,
    authority: OperatorIntegrityBinding,
    observed_at: datetime,
) -> tuple[dict[str, Any], str]:
    ticket = artifact.payload
    _exact_keys(ticket, _CHALLENGE_KEYS, "challenge_ticket_schema_invalid")
    if (
        ticket.get("contract_name") != CHALLENGE_CONTRACT_NAME
        or ticket.get("contract_version") != CHALLENGE_CONTRACT_VERSION
    ):
        raise PublicBlipProofError("challenge_ticket_contract_invalid")
    try:
        verification = verify_signed_envelope(
            ticket,
            registry,
            observed_at=observed_at,
            maximum_receipt_age=CHALLENGE_LIFETIME,
        )
    except SpatialCryptoError as exc:
        raise PublicBlipProofError("challenge_ticket_signature_invalid") from exc
    if verification.key_identity != authority.executor_key.identity:
        raise PublicBlipProofError("challenge_ticket_signer_not_authorized")
    challenge_id = ticket.get("challenge_id")
    if not isinstance(challenge_id, str) or not _CHALLENGE_RE.fullmatch(challenge_id):
        raise PublicBlipProofError("challenge_id_invalid")
    expected = {
        "proof_scope": PROOF_SCOPE,
        "public_endpoint": PUBLIC_ENDPOINT,
        "memorial_slug": MEMORIAL_SLUG,
        "deployment_binding": deployment.as_dict(),
        "operator_integrity_payload_digest": authority.payload_digest,
        "operator_authorization_required": True,
        "real_audio_required": True,
        "transport_policy": _TRANSPORT_POLICY,
    }
    if any(ticket.get(key) != value for key, value in expected.items()):
        raise PublicBlipProofError("challenge_ticket_binding_invalid")
    return ticket, bounded_sha256(ticket, prefixed=True)


def issue_challenge(
    *,
    deployment_receipt_path: Path,
    operator_integrity_binding_path: Path,
    trusted_key_registry_path: Path,
    operator_integrity_signing_key_path: Path,
    state_root: Path,
    challenge_output_path: Path = DEFAULT_CHALLENGE_OUTPUT,
    expected_uid: int | None = None,
    expected_gid: int | None = None,
    observed_at: datetime | None = None,
) -> dict[str, object]:
    uid = os.geteuid() if expected_uid is None else expected_uid
    gid = os.getegid() if expected_gid is None else expected_gid
    _harden_sensitive_process()
    _preflight_output(
        challenge_output_path,
        label="challenge_ticket",
        expected_uid=uid,
        expected_gid=gid,
    )
    now = _observed(observed_at)
    deployment_artifact = _load_private_json(
        deployment_receipt_path,
        label="deployment_receipt",
        expected_uid=uid,
        expected_gid=gid,
        maximum_bytes=MAX_JSON_BYTES,
    )
    deployment = _validate_deployment(deployment_artifact, observed_at=now)
    registry = _load_registry(
        trusted_key_registry_path,
        expected_uid=uid,
        expected_gid=gid,
    )
    authority_artifact = _load_private_json(
        operator_integrity_binding_path,
        label="operator_integrity_binding",
        expected_uid=uid,
        expected_gid=gid,
        maximum_bytes=MAX_INTEGRITY_BINDING_BYTES,
    )
    authority = _validate_operator_integrity_binding(
        authority_artifact,
        registry=registry,
        deployment=deployment,
        observed_at=now,
    )
    signer = _load_signer(
        operator_integrity_signing_key_path,
        expected_uid=uid,
        expected_gid=gid,
        key_record=authority.executor_key,
    )
    challenge_id = secrets.token_hex(32)
    ticket = sign_envelope(
        _challenge_unsigned(
            challenge_id=challenge_id,
            issued_at=now,
            expires_at=now + CHALLENGE_LIFETIME,
            signer=signer,
            deployment=deployment,
            authority=authority,
        ),
        signer,
    )
    ticket_digest = bounded_sha256(ticket, prefixed=True)
    journal = ChallengeJournal(
        state_root,
        expected_uid=uid,
        expected_gid=gid,
    )
    with journal.locked(recover_pending=True) as records:
        journal_fd = journal._open_owned_file(  # noqa: SLF001
            journal.journal_path,
            create=True,
            append=True,
        )
        try:
            journal.append(
                journal_fd,
                records,
                challenge_id=challenge_id,
                state_value="issued",
                ticket_digest=ticket_digest,
                deployment_receipt_digest=deployment.deployment_receipt_digest,
                operator_integrity_payload_digest=authority.payload_digest,
                issued_at=str(ticket["issued_at"]),
                expires_at=str(ticket["expires_at"]),
                observed_at=_iso(now),
            )
        finally:
            os.close(journal_fd)
    _atomic_write_private_bytes(
        challenge_output_path,
        _json_bytes(ticket),
        label="challenge_ticket",
        expected_uid=uid,
        expected_gid=gid,
    )
    return deepcopy(ticket)


def _read_audio(
    descriptor: int,
    *,
    expected_uid: int,
    expected_gid: int,
) -> bytearray:
    try:
        details = os.fstat(descriptor)
    except OSError as exc:
        raise PublicBlipProofError("audio_descriptor_invalid") from exc
    if stat.S_ISREG(details.st_mode):
        _verify_private_stat(
            details,
            label="audio_source",
            expected_uid=expected_uid,
            expected_gid=expected_gid,
        )
        if not 1 <= details.st_size <= MAX_AUDIO_BYTES:
            raise PublicBlipProofError("audio_size_invalid")
    elif not (stat.S_ISFIFO(details.st_mode) or stat.S_ISSOCK(details.st_mode)):
        raise PublicBlipProofError("audio_source_type_invalid")
    result = bytearray()
    while True:
        chunk = os.read(descriptor, min(65_536, MAX_AUDIO_BYTES + 1 - len(result)))
        if not chunk:
            break
        result.extend(chunk)
        if len(result) > MAX_AUDIO_BYTES:
            raise PublicBlipProofError("audio_too_large")
    if not result:
        raise PublicBlipProofError("audio_missing")
    if stat.S_ISREG(details.st_mode):
        after = os.fstat(descriptor)
        if (
            (details.st_dev, details.st_ino) != (after.st_dev, after.st_ino)
            or details.st_size != after.st_size
            or details.st_mtime_ns != after.st_mtime_ns
            or details.st_ctime_ns != after.st_ctime_ns
            or details.st_mode != after.st_mode
            or details.st_nlink != after.st_nlink
        ):
            raise PublicBlipProofError("audio_changed_during_read")
    return result


def _read_operator_authorization_phrase(
    descriptor: int,
    *,
    expected_uid: int,
    expected_gid: int,
) -> str:
    try:
        details = os.fstat(descriptor)
    except OSError as exc:
        raise PublicBlipProofError("operator_authorization_descriptor_invalid") from exc
    if stat.S_ISREG(details.st_mode):
        _verify_private_stat(
            details,
            label="operator_authorization_source",
            expected_uid=expected_uid,
            expected_gid=expected_gid,
        )
    elif not (
        stat.S_ISFIFO(details.st_mode)
        or stat.S_ISSOCK(details.st_mode)
        or stat.S_ISCHR(details.st_mode)
    ):
        raise PublicBlipProofError("operator_authorization_source_type_invalid")
    maximum = len(UPLOAD_AUTHORITY_PHRASE.encode("utf-8")) + 2
    raw = os.read(descriptor, maximum + 1)
    if len(raw) > maximum:
        raise PublicBlipProofError("operator_upload_authorization_missing")
    try:
        phrase = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PublicBlipProofError("operator_upload_authorization_missing") from exc
    if phrase.endswith("\n"):
        phrase = phrase[:-1]
    if phrase.endswith("\r"):
        phrase = phrase[:-1]
    return phrase


class DirectHttpsTransport:
    """Exact-origin HTTPS transport; stdlib HTTPSConnection ignores proxy env."""

    __slots__ = ("_capability",)
    _CAPABILITY = object()

    def __init__(self) -> None:
        self._capability = self._CAPABILITY

    def post_audio(
        self,
        *,
        audio: bytearray,
        content_type: str,
        timeout: float,
    ) -> HttpObservation:
        split = urlsplit(PUBLIC_ENDPOINT)
        if (
            split.scheme != "https"
            or split.hostname != PUBLIC_HOST
            or split.port is not None
            or split.path != PUBLIC_PATH
            or split.query
            or split.fragment
        ):
            raise PublicBlipProofError("public_endpoint_constant_invalid")
        context = ssl.create_default_context()
        context.check_hostname = True
        context.verify_mode = ssl.CERT_REQUIRED
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        connection = http.client.HTTPSConnection(
            PUBLIC_HOST,
            443,
            timeout=timeout,
            context=context,
        )
        try:
            connection.request(
                "POST",
                PUBLIC_PATH,
                body=audio,
                headers={
                    "Accept": "application/json",
                    "Content-Type": content_type,
                    "Content-Length": str(len(audio)),
                    "Cache-Control": "no-store",
                    "User-Agent": "ea-governed-public-blip-proof/2",
                },
                encode_chunked=False,
            )
            response = connection.getresponse()
            body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                raise PublicBlipProofError("public_response_too_large")
            headers = tuple((str(key).lower(), str(value)) for key, value in response.getheaders())
            return HttpObservation(
                status_code=response.status,
                headers=headers,
                body=body,
                tls_certificate_verified=True,
                hostname_verified=True,
                proxy_used=False,
                redirect_count=0,
            )
        except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
            raise PublicBlipProofError("public_https_request_failed") from exc
        finally:
            connection.close()


def _header_exact(
    headers: tuple[tuple[str, str], ...],
    name: str,
) -> str:
    values = [value.strip() for key, value in headers if key.lower() == name]
    if len(values) != 1:
        raise PublicBlipProofError(f"public_response_{name.replace('-', '_')}_invalid")
    return values[0]


def _validate_http_observation(
    observation: HttpObservation,
    *,
    source_revision: str,
) -> None:
    if type(observation.status_code) is not int or observation.status_code != 200:
        raise PublicBlipProofError("public_response_status_not_200")
    if (
        observation.tls_certificate_verified is not True
        or observation.hostname_verified is not True
    ):
        raise PublicBlipProofError("public_response_tls_not_verified")
    if observation.proxy_used is not False:
        raise PublicBlipProofError("public_response_proxy_used")
    if type(observation.redirect_count) is not int or observation.redirect_count != 0:
        raise PublicBlipProofError("public_response_redirect_observed")
    cache_control = _header_exact(observation.headers, "cache-control")
    source_header = _header_exact(observation.headers, "x-ea-source-revision")
    content_type = _header_exact(observation.headers, "content-type")
    if cache_control.lower() != "no-store":
        raise PublicBlipProofError("public_response_cache_control_invalid")
    if source_header != source_revision:
        raise PublicBlipProofError("public_response_source_revision_mismatch")
    if content_type.split(";", 1)[0].strip().lower() != "application/json":
        raise PublicBlipProofError("public_response_content_type_invalid")
    payload = _parse_public_response_json(observation.body)
    transcript = payload.get("transcript_original_text") or payload.get("transcript_text")
    if (
        payload.get("transcription_status") != "transcribed"
        or payload.get("transcriber") != EXACT_TRANSCRIBER
        or not isinstance(transcript, str)
        or not transcript.strip()
    ):
        raise PublicBlipProofError("public_response_blip_transcript_not_proven")


def _proof_unsigned(
    *,
    issued_at: datetime,
    signer: Ed25519EnvelopeSigner,
    challenge: Mapping[str, object],
    ticket_digest: str,
    deployment: DeploymentBinding,
    authority: OperatorIntegrityBinding,
    audio_content_type: str,
    audio_bytes: int,
    request_started_at: datetime,
    response_observed_at: datetime,
) -> dict[str, object]:
    return {
        "contract_name": CONTRACT_NAME,
        "contract_version": CONTRACT_VERSION,
        "issuer": signer.key_record.issuer,
        "environment": signer.key_record.environment,
        "issued_at": _iso(issued_at),
        "expires_at": _iso(issued_at + PROOF_LIFETIME),
        "generated_by": GENERATED_BY,
        "proof_scope": PROOF_SCOPE,
        "status": "pass",
        "proof_eligible": True,
        "challenge": {
            "challenge_id": challenge["challenge_id"],
            "ticket_digest": ticket_digest,
            "issued_at": challenge["issued_at"],
            "expires_at": challenge["expires_at"],
            "terminal_state": "consumed_pass",
        },
        "operator_authority": {
            "operator_confirmed_real_speech": True,
            "operator_confirmed_upload_authority": True,
            "authorization_phrase_recorded": False,
        },
        "public_request": {
            "origin": PUBLIC_ORIGIN,
            "endpoint": PUBLIC_ENDPOINT,
            "method": "POST",
            "request_started_at": _iso(request_started_at),
            "response_observed_at": _iso(response_observed_at),
            "http_status": 200,
            "cache_control": "no-store",
            "x_ea_source_revision": deployment.source_revision,
            "redirect_count": 0,
            "proxy_used": False,
            "tls_certificate_verified": True,
            "hostname_verified": True,
            "transcriber": EXACT_TRANSCRIBER,
            "transcript_nonempty": True,
            "transcript_content_recorded": False,
            "transcript_digest_recorded": False,
            "response_body_recorded": False,
        },
        "real_audio": {
            "content_type": audio_content_type,
            "bytes": audio_bytes,
            "operator_confirmed_real_speech": True,
            "content_recorded": False,
            "content_digest_recorded": False,
            "path_recorded": False,
        },
        "immutable_deployment": {
            **deployment.as_dict(),
            "passing_receipt_bound": True,
            "observed_source_header_matches": True,
        },
        "integrity_evidence": {
            "trust_model": (
                "sole_operator_protected_key_integrity_not_independent_approval"
            ),
            "operator_integrity_payload_digest": authority.payload_digest,
            "operator_integrity_key": _key_identity(authority.executor_key),
        },
        "privacy": {
            "file_mode": "0600",
            "raw_audio_recorded": False,
            "audio_digest_recorded": False,
            "audio_path_recorded": False,
            "transcript_content_recorded": False,
            "transcript_digest_recorded": False,
            "private_paths_recorded": False,
            "secret_material_recorded": False,
        },
        "claims": {
            "public_blip_primary_stt_proven": True,
            "exact_flagship_stt_policy_bound": True,
            "one_button_conversation_proven": False,
            "tts_health_proven": False,
            "human_listening_acceptance_proven": False,
            "voice_flagship_or_gold_claim_allowed": False,
        },
    }


def _validate_proof_shape(
    receipt: Mapping[str, object],
    *,
    registry: Ed25519KeyRegistry,
    challenge: Mapping[str, object],
    ticket_digest: str,
    deployment: DeploymentBinding,
    authority: OperatorIntegrityBinding,
    observed_at: datetime,
) -> str:
    proof = _exact_keys(receipt, _PROOF_KEYS, "proof_schema_invalid")
    if (
        proof.get("contract_name") != CONTRACT_NAME
        or proof.get("contract_version") != CONTRACT_VERSION
        or proof.get("generated_by") != GENERATED_BY
        or proof.get("proof_scope") != PROOF_SCOPE
        or proof.get("status") != "pass"
        or proof.get("proof_eligible") is not True
    ):
        raise PublicBlipProofError("proof_contract_invalid")
    try:
        verification = verify_signed_envelope(
            proof,
            registry,
            observed_at=observed_at,
            maximum_receipt_age=PROOF_LIFETIME,
        )
    except SpatialCryptoError as exc:
        raise PublicBlipProofError("proof_signature_invalid") from exc
    if verification.key_identity != authority.executor_key.identity:
        raise PublicBlipProofError("proof_signer_not_authorized")
    expected_challenge = {
        "challenge_id": challenge["challenge_id"],
        "ticket_digest": ticket_digest,
        "issued_at": challenge["issued_at"],
        "expires_at": challenge["expires_at"],
        "terminal_state": "consumed_pass",
    }
    if proof.get("challenge") != expected_challenge:
        raise PublicBlipProofError("proof_challenge_binding_invalid")
    immutable = proof.get("immutable_deployment")
    expected_immutable = {
        **deployment.as_dict(),
        "passing_receipt_bound": True,
        "observed_source_header_matches": True,
    }
    if immutable != expected_immutable:
        raise PublicBlipProofError("proof_deployment_binding_invalid")
    if proof.get("integrity_evidence") != {
        "trust_model": (
            "sole_operator_protected_key_integrity_not_independent_approval"
        ),
        "operator_integrity_payload_digest": authority.payload_digest,
        "operator_integrity_key": _key_identity(authority.executor_key),
    }:
        raise PublicBlipProofError("proof_authority_binding_invalid")
    public_request = proof.get("public_request")
    if not isinstance(public_request, dict) or public_request != {
        "origin": PUBLIC_ORIGIN,
        "endpoint": PUBLIC_ENDPOINT,
        "method": "POST",
        "request_started_at": public_request.get("request_started_at"),
        "response_observed_at": public_request.get("response_observed_at"),
        "http_status": 200,
        "cache_control": "no-store",
        "x_ea_source_revision": deployment.source_revision,
        "redirect_count": 0,
        "proxy_used": False,
        "tls_certificate_verified": True,
        "hostname_verified": True,
        "transcriber": EXACT_TRANSCRIBER,
        "transcript_nonempty": True,
        "transcript_content_recorded": False,
        "transcript_digest_recorded": False,
        "response_body_recorded": False,
    }:
        raise PublicBlipProofError("proof_public_request_invalid")
    try:
        started = parse_timestamp(public_request.get("request_started_at"))
        responded = parse_timestamp(public_request.get("response_observed_at"))
    except SignatureVerificationError as exc:
        raise PublicBlipProofError("proof_public_request_timestamp_invalid") from exc
    if not deployment.completed_at < started <= responded <= observed_at + timedelta(seconds=1):
        raise PublicBlipProofError("proof_public_request_chronology_invalid")
    audio = proof.get("real_audio")
    if (
        not isinstance(audio, dict)
        or audio.get("content_type") not in _ALLOWED_AUDIO_CONTENT_TYPES
        or isinstance(audio.get("bytes"), bool)
        or not isinstance(audio.get("bytes"), int)
        or not 1 <= int(audio["bytes"]) <= MAX_AUDIO_BYTES
        or audio.get("operator_confirmed_real_speech") is not True
        or audio.get("content_recorded") is not False
        or audio.get("content_digest_recorded") is not False
        or audio.get("path_recorded") is not False
    ):
        raise PublicBlipProofError("proof_real_audio_invalid")
    if proof.get("operator_authority") != {
        "operator_confirmed_real_speech": True,
        "operator_confirmed_upload_authority": True,
        "authorization_phrase_recorded": False,
    }:
        raise PublicBlipProofError("proof_operator_authority_invalid")
    privacy = proof.get("privacy")
    if not isinstance(privacy, dict) or any(
        privacy.get(key) is not False
        for key in (
            "raw_audio_recorded",
            "audio_digest_recorded",
            "audio_path_recorded",
            "transcript_content_recorded",
            "transcript_digest_recorded",
            "private_paths_recorded",
            "secret_material_recorded",
        )
    ):
        raise PublicBlipProofError("proof_privacy_invalid")
    claims = proof.get("claims")
    if not isinstance(claims, dict) or claims != {
        "public_blip_primary_stt_proven": True,
        "exact_flagship_stt_policy_bound": True,
        "one_button_conversation_proven": False,
        "tts_health_proven": False,
        "human_listening_acceptance_proven": False,
        "voice_flagship_or_gold_claim_allowed": False,
    }:
        raise PublicBlipProofError("proof_claims_invalid")
    return bounded_sha256(proof, prefixed=True)


def execute_proof(
    *,
    challenge_ticket_path: Path,
    deployment_receipt_path: Path,
    operator_integrity_binding_path: Path,
    trusted_key_registry_path: Path,
    operator_integrity_signing_key_path: Path,
    state_root: Path,
    output_path: Path = DEFAULT_OUTPUT,
    audio_descriptor: int = 0,
    audio_content_type: str,
    operator_authorization_phrase: str,
    expected_uid: int | None = None,
    expected_gid: int | None = None,
    observed_at: datetime | None = None,
    transport: DirectHttpsTransport | None = None,
) -> dict[str, object]:
    uid = os.geteuid() if expected_uid is None else expected_uid
    gid = os.getegid() if expected_gid is None else expected_gid
    _harden_sensitive_process()
    now = _observed(observed_at)
    if operator_authorization_phrase != UPLOAD_AUTHORITY_PHRASE:
        raise PublicBlipProofError("operator_upload_authorization_missing")
    normalized_content_type = str(audio_content_type or "").split(";", 1)[0].strip().lower()
    if normalized_content_type not in _ALLOWED_AUDIO_CONTENT_TYPES:
        raise PublicBlipProofError("audio_content_type_invalid")
    _preflight_output(
        output_path,
        label="proof_output",
        expected_uid=uid,
        expected_gid=gid,
    )
    deployment_artifact = _load_private_json(
        deployment_receipt_path,
        label="deployment_receipt",
        expected_uid=uid,
        expected_gid=gid,
        maximum_bytes=MAX_JSON_BYTES,
    )
    deployment = _validate_deployment(deployment_artifact, observed_at=now)
    registry = _load_registry(
        trusted_key_registry_path,
        expected_uid=uid,
        expected_gid=gid,
    )
    authority_artifact = _load_private_json(
        operator_integrity_binding_path,
        label="operator_integrity_binding",
        expected_uid=uid,
        expected_gid=gid,
        maximum_bytes=MAX_INTEGRITY_BINDING_BYTES,
    )
    authority = _validate_operator_integrity_binding(
        authority_artifact,
        registry=registry,
        deployment=deployment,
        observed_at=now,
    )
    signer = _load_signer(
        operator_integrity_signing_key_path,
        expected_uid=uid,
        expected_gid=gid,
        key_record=authority.executor_key,
    )
    challenge_artifact = _load_private_json(
        challenge_ticket_path,
        label="challenge_ticket",
        expected_uid=uid,
        expected_gid=gid,
        maximum_bytes=MAX_CHALLENGE_BYTES,
    )
    challenge, ticket_digest = _validate_challenge(
        challenge_artifact,
        registry=registry,
        deployment=deployment,
        authority=authority,
        observed_at=now,
    )
    audio = _read_audio(
        audio_descriptor,
        expected_uid=uid,
        expected_gid=gid,
    )
    selected_transport = transport or DirectHttpsTransport()
    if (
        type(selected_transport) is not DirectHttpsTransport
        or selected_transport._capability is not DirectHttpsTransport._CAPABILITY  # noqa: SLF001
    ):
        for index in range(len(audio)):
            audio[index] = 0
        raise PublicBlipProofError("governed_https_transport_required")

    journal = ChallengeJournal(
        state_root,
        expected_uid=uid,
        expected_gid=gid,
    )
    challenge_id = str(challenge["challenge_id"])
    proof: dict[str, object] | None = None
    terminal_written = False
    try:
        with journal.locked(recover_pending=True) as records:
            challenge_records = journal.records_for(records, challenge_id)
            if (
                len(challenge_records) != 1
                or challenge_records[0].get("state") != "issued"
                or challenge_records[0].get("ticket_digest") != ticket_digest
                or challenge_records[0].get("deployment_receipt_digest")
                != deployment.deployment_receipt_digest
                or challenge_records[0].get("operator_integrity_payload_digest")
                != authority.payload_digest
            ):
                raise PublicBlipProofError("challenge_not_issued_or_already_consumed")
            try:
                expires_at = parse_timestamp(challenge.get("expires_at"))
            except SignatureVerificationError as exc:
                raise PublicBlipProofError("challenge_expiry_invalid") from exc
            if now > expires_at:
                raise PublicBlipProofError("challenge_expired")
            journal_fd = journal._open_owned_file(  # noqa: SLF001
                journal.journal_path,
                create=True,
                append=True,
            )
            try:
                journal.append(
                    journal_fd,
                    records,
                    challenge_id=challenge_id,
                    state_value="execution_intent",
                    ticket_digest=ticket_digest,
                    deployment_receipt_digest=deployment.deployment_receipt_digest,
                    operator_integrity_payload_digest=authority.payload_digest,
                    issued_at=str(challenge["issued_at"]),
                    expires_at=str(challenge["expires_at"]),
                    observed_at=_iso(now),
                )
                request_started = _observed(observed_at)
                try:
                    response = selected_transport.post_audio(
                        audio=audio,
                        content_type=normalized_content_type,
                        timeout=HTTP_TIMEOUT_SECONDS,
                    )
                    response_observed = _observed(observed_at)
                    _validate_http_observation(
                        response,
                        source_revision=deployment.source_revision,
                    )
                    proof = sign_envelope(
                        _proof_unsigned(
                            issued_at=response_observed,
                            signer=signer,
                            challenge=challenge,
                            ticket_digest=ticket_digest,
                            deployment=deployment,
                            authority=authority,
                            audio_content_type=normalized_content_type,
                            audio_bytes=len(audio),
                            request_started_at=request_started,
                            response_observed_at=response_observed,
                        ),
                        signer,
                    )
                    proof_digest = _validate_proof_shape(
                        proof,
                        registry=registry,
                        challenge=challenge,
                        ticket_digest=ticket_digest,
                        deployment=deployment,
                        authority=authority,
                        observed_at=response_observed,
                    )
                except Exception as exc:
                    failure_code = (
                        str(exc)
                        if isinstance(exc, PublicBlipProofError)
                        and _SAFE_ID_RE.fullmatch(str(exc))
                        else "governed_execution_failed"
                    )
                    journal.append(
                        journal_fd,
                        records,
                        challenge_id=challenge_id,
                        state_value="consumed_abort",
                        ticket_digest=ticket_digest,
                        deployment_receipt_digest=deployment.deployment_receipt_digest,
                        operator_integrity_payload_digest=authority.payload_digest,
                        issued_at=str(challenge["issued_at"]),
                        expires_at=str(challenge["expires_at"]),
                        observed_at=_iso(_observed(observed_at)),
                        failure_code=failure_code,
                    )
                    terminal_written = True
                    raise
                journal.append(
                    journal_fd,
                    records,
                    challenge_id=challenge_id,
                    state_value="consumed_pass",
                    ticket_digest=ticket_digest,
                    deployment_receipt_digest=deployment.deployment_receipt_digest,
                    operator_integrity_payload_digest=authority.payload_digest,
                    issued_at=str(challenge["issued_at"]),
                    expires_at=str(challenge["expires_at"]),
                    observed_at=_iso(response_observed),
                    proof_digest=proof_digest,
                )
                terminal_written = True
            finally:
                os.close(journal_fd)
            if proof is None:
                raise PublicBlipProofError("proof_not_materialized")
            _atomic_write_private_bytes(
                output_path,
                _json_bytes(proof),
                label="proof_receipt",
                expected_uid=uid,
                expected_gid=gid,
            )
    finally:
        for index in range(len(audio)):
            audio[index] = 0
        del audio
    if proof is None or not terminal_written:
        raise PublicBlipProofError("proof_not_materialized")
    return deepcopy(proof)


def verify_proof(
    receipt_path: Path,
    *,
    challenge_ticket_path: Path,
    deployment_receipt_path: Path,
    operator_integrity_binding_path: Path,
    trusted_key_registry_path: Path,
    state_root: Path,
    expected_uid: int | None = None,
    expected_gid: int | None = None,
    observed_at: datetime | None = None,
) -> dict[str, object]:
    uid = os.geteuid() if expected_uid is None else expected_uid
    gid = os.getegid() if expected_gid is None else expected_gid
    try:
        _harden_sensitive_process()
        now = _observed(observed_at)
        deployment_artifact = _load_private_json(
            deployment_receipt_path,
            label="deployment_receipt",
            expected_uid=uid,
            expected_gid=gid,
            maximum_bytes=MAX_JSON_BYTES,
        )
        deployment = _validate_deployment(deployment_artifact, observed_at=now)
        registry = _load_registry(
            trusted_key_registry_path,
            expected_uid=uid,
            expected_gid=gid,
        )
        authority_artifact = _load_private_json(
            operator_integrity_binding_path,
            label="operator_integrity_binding",
            expected_uid=uid,
            expected_gid=gid,
            maximum_bytes=MAX_INTEGRITY_BINDING_BYTES,
        )
        authority = _validate_operator_integrity_binding(
            authority_artifact,
            registry=registry,
            deployment=deployment,
            observed_at=now,
        )
        challenge_artifact = _load_private_json(
            challenge_ticket_path,
            label="challenge_ticket",
            expected_uid=uid,
            expected_gid=gid,
            maximum_bytes=MAX_CHALLENGE_BYTES,
        )
        challenge, ticket_digest = _validate_challenge(
            challenge_artifact,
            registry=registry,
            deployment=deployment,
            authority=authority,
            observed_at=now,
        )
        receipt_artifact = _load_private_json(
            receipt_path,
            label="proof_receipt",
            expected_uid=uid,
            expected_gid=gid,
            maximum_bytes=MAX_PROOF_BYTES,
        )
        proof_digest = _validate_proof_shape(
            receipt_artifact.payload,
            registry=registry,
            challenge=challenge,
            ticket_digest=ticket_digest,
            deployment=deployment,
            authority=authority,
            observed_at=now,
        )
        journal = ChallengeJournal(
            state_root,
            expected_uid=uid,
            expected_gid=gid,
        )
        with journal.locked(recover_pending=False) as records:
            challenge_records = journal.records_for(
                records,
                str(challenge["challenge_id"]),
            )
        if (
            [record.get("state") for record in challenge_records]
            != ["issued", "execution_intent", "consumed_pass"]
            or challenge_records[-1].get("proof_digest") != proof_digest
            or any(
                record.get("ticket_digest") != ticket_digest
                or record.get("deployment_receipt_digest")
                != deployment.deployment_receipt_digest
                or record.get("operator_integrity_payload_digest") != authority.payload_digest
                for record in challenge_records
            )
        ):
            raise PublicBlipProofError("challenge_consumption_not_proven")
    except Exception as exc:
        code = (
            str(exc)
            if isinstance(exc, PublicBlipProofError) and _SAFE_ID_RE.fullmatch(str(exc))
            else "proof_verification_failed"
        )
        return {
            "contract_name": VERIFIER_CONTRACT_NAME,
            "status": "fail",
            "issues": [code],
            "receipt": "[private_0600_proof]",
            "challenge_state": "[private_replay_safe_state]",
        }
    return {
        "contract_name": VERIFIER_CONTRACT_NAME,
        "status": "pass",
        "issues": [],
        "receipt": "[private_0600_proof]",
        "challenge_state": "[private_replay_safe_state]",
        "transcriber": EXACT_TRANSCRIBER,
        "source_revision": deployment.source_revision,
        "stt_policy": deepcopy(EXPECTED_STT_POLICY),
        "voice_flagship_or_gold_claim_allowed": False,
    }


def _common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--deployment-receipt", type=Path, required=True)
    parser.add_argument("--operator-integrity-binding", type=Path, required=True)
    parser.add_argument("--trusted-key-registry", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--expected-uid", type=int, default=os.geteuid())
    parser.add_argument("--expected-gid", type=int, default=os.getegid())


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Issue or consume one governed public-Blip STT proof challenge."
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    issue = subcommands.add_parser("issue-challenge")
    _common_arguments(issue)
    issue.add_argument("--operator-integrity-signing-key", type=Path, required=True)
    issue.add_argument("--challenge-output", type=Path, default=DEFAULT_CHALLENGE_OUTPUT)

    execute = subcommands.add_parser("execute")
    _common_arguments(execute)
    execute.add_argument("--operator-integrity-signing-key", type=Path, required=True)
    execute.add_argument("--challenge-ticket", type=Path, required=True)
    execute.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    execute.add_argument("--audio-fd", type=int, required=True)
    execute.add_argument("--audio-content-type", required=True)
    execute.add_argument("--operator-authorization-fd", type=int, default=0)
    args = parser.parse_args()
    try:
        _harden_sensitive_process()
        if args.command == "issue-challenge":
            payload = issue_challenge(
                deployment_receipt_path=args.deployment_receipt,
                operator_integrity_binding_path=args.operator_integrity_binding,
                trusted_key_registry_path=args.trusted_key_registry,
                operator_integrity_signing_key_path=args.operator_integrity_signing_key,
                state_root=args.state_root,
                challenge_output_path=args.challenge_output,
                expected_uid=args.expected_uid,
                expected_gid=args.expected_gid,
            )
            summary = {
                "contract_name": CHALLENGE_CONTRACT_NAME,
                "status": "issued",
                "challenge_id": payload["challenge_id"],
                "challenge_ticket": "[private_0600_ticket]",
            }
        else:
            if args.audio_fd == args.operator_authorization_fd:
                raise PublicBlipProofError(
                    "audio_and_operator_authorization_fd_must_differ"
                )
            operator_phrase = _read_operator_authorization_phrase(
                args.operator_authorization_fd,
                expected_uid=args.expected_uid,
                expected_gid=args.expected_gid,
            )
            payload = execute_proof(
                challenge_ticket_path=args.challenge_ticket,
                deployment_receipt_path=args.deployment_receipt,
                operator_integrity_binding_path=args.operator_integrity_binding,
                trusted_key_registry_path=args.trusted_key_registry,
                operator_integrity_signing_key_path=args.operator_integrity_signing_key,
                state_root=args.state_root,
                output_path=args.output,
                audio_descriptor=args.audio_fd,
                audio_content_type=args.audio_content_type,
                operator_authorization_phrase=operator_phrase,
                expected_uid=args.expected_uid,
                expected_gid=args.expected_gid,
            )
            summary = {
                "contract_name": CONTRACT_NAME,
                "status": payload["status"],
                "proof_eligible": payload["proof_eligible"],
                "receipt": "[private_0600_proof]",
            }
    except Exception as exc:
        code = (
            str(exc)
            if isinstance(exc, PublicBlipProofError) and _SAFE_ID_RE.fullmatch(str(exc))
            else "governed_public_blip_proof_failed"
        )
        print(
            json.dumps(
                {"status": "blocked", "issues": [code]},
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
