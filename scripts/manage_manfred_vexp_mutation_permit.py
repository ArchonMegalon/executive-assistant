#!/usr/bin/env python3
"""Issue, inspect, revoke, or permanently void Memorial mutation authority.

This installed program is intentionally self-contained.  It must never import
Python from an operator checkout while running as root.
"""

from __future__ import annotations

import argparse
import ctypes
import errno
import fcntl
import hashlib
import json
import os
import pwd
import re
import secrets
import stat
import sys
import time
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence


ROOT_UID = 0
ROOT_GID = 0
TRUSTED_EXECUTABLE_PATH = Path(
    "/usr/local/libexec/ea/manage-manfred-vexp-mutation-permit"
)
TRUSTED_PYTHON_EXECUTABLE = Path("/usr/bin/python3")
TRUSTED_EXECUTABLE_MODE = 0o555
TRUSTED_EXECUTABLE_PARENT_MODE = 0o755
RUNTIME_DIRECTORY_MODE = 0o755
PERMIT_MODE = 0o644
PERMIT_COMMIT_MODE = 0o644
LOCK_MODE = 0o644
STATE_MODE = 0o600
MIN_TTL_SECONDS = 1
MAX_TTL_SECONDS = 3600
MAX_STATE_AGE = timedelta(minutes=5)
MAX_STATE_FUTURE_SKEW = timedelta(seconds=30)
MAX_VEXP_SENTINEL_STATE_BYTES = 1024 * 1024
MAX_VEXP_QUALIFICATION_CERTIFICATE_BYTES = 2 * 1024 * 1024
MAX_VEXP_QUALIFICATION_CERTIFICATE_SIDECAR_BYTES = 72
MAX_VEXP_MUTATION_PERMIT_BYTES = 16 * 1024
MAX_VEXP_MUTATION_PERMIT_COMMIT_BYTES = 16 * 1024
MAX_VEXP_EPOCH_VOID_LEDGER_ENTRY_BYTES = 64 * 1024
MAX_VEXP_RECOVERY_MANIFEST_BYTES = 256 * 1024
MAX_VEXP_CANDIDATE_AUTHORITY_RECORD_BYTES = 256 * 1024
MAX_VEXP_CANDIDATE_RUNTIME_RECEIPT_BYTES = 4 * 1024 * 1024
MAX_VEXP_CANDIDATE_IMAGE_BUILD_RECEIPT_BYTES = 1024 * 1024
MAX_VEXP_CURRENT_PREDICATE_BYTES = 128 * 1024
MAX_VEXP_CANDIDATE_BOUNDARY_EVENT_BYTES = 128 * 1024
MAX_VEXP_CANDIDATE_PUBLICATION_EVIDENCE_BYTES = 128 * 1024
MAX_TRUSTED_ROOT_PRODUCER_BYTES = 16 * 1024 * 1024
PERMIT_PATH = Path("/run/ea/memorial-vexp-mutation-permit.json")
PERMIT_COMMIT_PATH = Path(
    "/run/ea/memorial-vexp-mutation-permit.commit.json"
)
LOCK_PATH = Path("/run/ea/memorial-vexp-mutation-permit.lock")
RUNTIME_AUTHORITY_TRUSTED_PARENT = Path("/run")
EPOCH_VOID_LEDGER_ROOT = Path("/var/lib/vexp-qualification-epoch-voids")
EPOCH_VOID_LEDGER_OWNER_UID = 0
EPOCH_VOID_LEDGER_OWNER_GID = 1000
EPOCH_VOID_LEDGER_DIRECTORY_MODE = 0o750
EPOCH_VOID_LEDGER_ENTRY_MODE = 0o640
CANDIDATE_AUTHORITY_LEDGER_ROOT = Path(
    "/var/lib/vexp-manfred-candidate-authority"
)
CANDIDATE_AUTHORITY_ISSUANCE_DIRECTORY = (
    CANDIDATE_AUTHORITY_LEDGER_ROOT / "issuances"
)
CANDIDATE_AUTHORITY_FINALIZATION_DIRECTORY = (
    CANDIDATE_AUTHORITY_LEDGER_ROOT / "finalizations"
)
CANDIDATE_AUTHORITY_OPERATION_DIRECTORY = (
    CANDIDATE_AUTHORITY_LEDGER_ROOT / "operations"
)
CANDIDATE_AUTHORITY_PUBLICATION_DIRECTORY = (
    CANDIDATE_AUTHORITY_LEDGER_ROOT / "publications"
)
CANDIDATE_AUTHORITY_REVOCATION_DIRECTORY = (
    CANDIDATE_AUTHORITY_LEDGER_ROOT / "revocations"
)
CANDIDATE_AUTHORITY_PRODUCER_MANIFEST_PATH = (
    CANDIDATE_AUTHORITY_LEDGER_ROOT / "producer-manifest.json"
)
CANDIDATE_AUTHORITY_ATTESTOR_PATH = Path(
    "/usr/local/libexec/vexp-candidate-boundary-attestor"
)
CANDIDATE_AUTHORITY_LEDGER_OWNER_UID = 0
CANDIDATE_AUTHORITY_LEDGER_OWNER_GID = 1000
CANDIDATE_AUTHORITY_LEDGER_DIRECTORY_MODE = 0o750
CANDIDATE_AUTHORITY_RECORD_MODE = 0o640
CURRENT_PREDICATE_ROOT = Path(
    "/var/lib/vexp-qualification-current-predicate"
)
CURRENT_PREDICATE_RECORD_DIRECTORY = CURRENT_PREDICATE_ROOT / "records"
CURRENT_PREDICATE_POINTER_PATH = CURRENT_PREDICATE_ROOT / "current.json"
CURRENT_PREDICATE_PRODUCER_MANIFEST_PATH = (
    CURRENT_PREDICATE_ROOT / "producer-manifest.json"
)
CURRENT_PREDICATE_PRODUCER_PATH = Path(
    "/usr/local/libexec/vexp-current-predicate-attestor"
)
TRUSTED_ROOT_PRODUCER_INSTALL_PARENT = Path("/usr/local/libexec")
TRUSTED_ROOT_PRODUCER_DIRECTORY_MODE = 0o755
TRUSTED_ROOT_PRODUCER_MODE = 0o555
CURRENT_PREDICATE_OWNER_UID = 0
CURRENT_PREDICATE_OWNER_GID = 1000
CURRENT_PREDICATE_DIRECTORY_MODE = 0o750
CURRENT_PREDICATE_RECORD_MODE = 0o640
TRUSTED_AUTHORITY_STORAGE_PREFIX = Path("/var/lib")
BOOT_ID_PATH = Path("/proc/sys/kernel/random/boot_id")
AT_FDCWD = -100
RENAME_NOREPLACE = 1
RECOVERY_MANIFEST_ROOT = Path("/var/lib/vexp-qualification-recovery")
RECOVERY_MANIFEST_PATH = RECOVERY_MANIFEST_ROOT / "reviewed-maintenance-manifest.json"
RECOVERY_MANIFEST_OWNER_UID = 0
RECOVERY_MANIFEST_OWNER_GID = 1000
RECOVERY_MANIFEST_DIRECTORY_MODE = 0o750
RECOVERY_MANIFEST_MODE = 0o640
QUALIFICATION_IMPLEMENTATION_MANIFEST_PATH = (
    RECOVERY_MANIFEST_ROOT / "reviewed-implementation-manifest.json"
)
VEXP_QUALIFICATION_IMPLEMENTATION_MANIFEST_CONTRACT_NAME = (
    "ea.vexp_qualification_implementation_manifest.v1"
)
VEXP_QUALIFICATION_IMPLEMENTATION_MANIFEST_VERSION = 1
QUALIFICATION_CERTIFICATE_ROOT = Path("/var/lib/vexp-qualification-certificate")
QUALIFICATION_CERTIFICATE_DIRECTORY = (
    QUALIFICATION_CERTIFICATE_ROOT / "certificates"
)
QUALIFICATION_CERTIFICATE_OWNER_UID = 0
QUALIFICATION_CERTIFICATE_OWNER_GID = 1000
QUALIFICATION_CERTIFICATE_MODE = 0o640
QUALIFICATION_CERTIFICATE_DIRECTORY_MODE = 0o750
VEXP_QUALIFICATION_CERTIFICATE_SCHEMA = "ea.vexp_qualification_certificate.v2"
VEXP_SENTINEL_STATE_VERSION = 6
VEXP_MUTATION_PERMIT_CONTRACT_NAME = "ea.vexp_memorial_mutation_permit.v2"
VEXP_MUTATION_PERMIT_VERSION = 2
VEXP_MUTATION_PERMIT_COMMIT_CONTRACT_NAME = (
    "ea.vexp_mutation_permit_commit.v1"
)
VEXP_MUTATION_PERMIT_COMMIT_VERSION = 1
VEXP_EPOCH_VOID_CONTRACT_NAME = "ea.vexp_qualification_epoch_void.v1"
VEXP_EPOCH_VOID_VERSION = 1
VEXP_CANDIDATE_PERMIT_ISSUANCE_CONTRACT_NAME = (
    "ea.vexp_candidate_permit_issuance.v1"
)
VEXP_CANDIDATE_PERMIT_ISSUANCE_VERSION = 1
VEXP_CANDIDATE_FINALIZATION_CONTRACT_NAME = (
    "ea.vexp_candidate_finalization.v1"
)
VEXP_CANDIDATE_FINALIZATION_VERSION = 1
VEXP_CANDIDATE_FINALIZATION_COMMIT_CONTRACT_NAME = (
    "ea.vexp_candidate_finalization_commit.v1"
)
VEXP_CANDIDATE_FINALIZATION_COMMIT_VERSION = 1
VEXP_CANDIDATE_FINALIZATION_ABORT_CONTRACT_NAME = (
    "ea.vexp_candidate_finalization_abort.v1"
)
VEXP_CANDIDATE_FINALIZATION_ABORT_VERSION = 1
VEXP_CURRENT_PREDICATE_CONTRACT_NAME = "ea.vexp_current_predicate.v1"
VEXP_CURRENT_PREDICATE_VERSION = 1
VEXP_CURRENT_PREDICATE_POINTER_CONTRACT_NAME = (
    "ea.vexp_current_predicate_pointer.v1"
)
VEXP_CURRENT_PREDICATE_POINTER_VERSION = 1
VEXP_CURRENT_PREDICATE_PRODUCER_MANIFEST_CONTRACT_NAME = (
    "ea.vexp_current_predicate_producer_manifest.v1"
)
VEXP_CURRENT_PREDICATE_PRODUCER_MANIFEST_VERSION = 1
VEXP_CANDIDATE_BOUNDARY_EVENT_CONTRACT_NAME = (
    "ea.vexp_candidate_boundary_event.v2"
)
VEXP_CANDIDATE_BOUNDARY_EVENT_VERSION = 2
VEXP_CANDIDATE_PUBLICATION_EVIDENCE_CONTRACT_NAME = (
    "ea.vexp_candidate_publication_evidence.v1"
)
VEXP_CANDIDATE_PUBLICATION_EVIDENCE_VERSION = 1
VEXP_CANDIDATE_EVIDENCE_PRODUCER_MANIFEST_CONTRACT_NAME = (
    "ea.vexp_candidate_evidence_producer_manifest.v1"
)
VEXP_CANDIDATE_EVIDENCE_PRODUCER_MANIFEST_VERSION = 1
CANDIDATE_RUNTIME_RECEIPT_SCHEMA = "ea.manfred_memorial_candidate_runtime.v6"
CANDIDATE_IMAGE_BUILD_RECEIPT_SCHEMA = "ea.manfred_memorial_image_build.v3"
VEXP_RECOVERY_MANIFEST_CONTRACT_NAME = (
    "ea.vexp_schema6_qualification_plumbing_recovery_manifest.v1"
)
VEXP_RECOVERY_MANIFEST_VERSION = 1
VEXP_RECOVERY_SCOPE = "schema_v6_qualification_plumbing_only"
VEXP_RECOVERY_REASON = "schema_v6_qualification_plumbing_recovery"
VEXP_MUTATION_BOUNDARIES = (
    "before_ensure_redis",
    "before_protect_previous_image",
    "before_recreate_api",
    "before_api_exec",
    "before_api_interaction",
    "before_rollback_api",
)
JOINT_VEXP_MUTATION_PERMIT_CONTRACT_NAME = "ea.vexp_memorial_joint_mutation_permit.v2"
JOINT_VEXP_MUTATION_PERMIT_VERSION = 2
JOINT_VEXP_MUTATION_BOUNDARIES = (
    *VEXP_MUTATION_BOUNDARIES,
    "before_recreate_cloudflared",
    "before_rollback_cloudflared",
    "before_rollback_network",
)
CANDIDATE_VEXP_MUTATION_PERMIT_CONTRACT_NAME = (
    "ea.vexp_manfred_candidate_mutation_permit.v2"
)
CANDIDATE_VEXP_MUTATION_PERMIT_VERSION = 2
CANDIDATE_VEXP_MUTATION_BOUNDARIES = (
    "before_candidate_image_build",
    "before_candidate_up",
    "before_candidate_exec",
    "before_candidate_interaction",
    "before_candidate_restart",
    "before_candidate_cleanup",
)
CANDIDATE_VEXP_MUTATION_SEQUENCE = (
    "before_candidate_up",
    *("before_candidate_exec",) * 2,
    "before_candidate_interaction",
    *("before_candidate_exec",) * 5,
    "before_candidate_restart",
    "before_candidate_interaction",
    *("before_candidate_exec",) * 7,
    *("before_candidate_interaction",) * 2,
    *("before_candidate_exec",) * 2,
)
API_PERMIT_MODE = "api"
JOINT_PERMIT_MODE = "joint"
CANDIDATE_PERMIT_MODE = "candidate"
PERMIT_MODES = (API_PERMIT_MODE, JOINT_PERMIT_MODE, CANDIDATE_PERMIT_MODE)
VEXP_MUTATION_PERMIT_KEYS = frozenset(
    {
        "contract_name",
        "version",
        "status",
        "epoch_started_at",
        "epoch_started_ms",
        "qualification_earliest_completion_at",
        "qualified_at",
        "terminal_identity_sha256",
        "qualification_certificate_schema",
        "qualification_certificate_sha256",
        "qualification_certificate_identity",
        "qualification_certificate_event_hash",
        "issued_at",
        "expires_at",
        "mutation_boundaries",
    }
)
CANDIDATE_VEXP_MUTATION_PERMIT_KEYS = VEXP_MUTATION_PERMIT_KEYS | {
    "candidate_boundary_attestor_sha256",
    "candidate_evidence_producer_manifest_sha256",
}
VEXP_MUTATION_PERMIT_COMMIT_KEYS = frozenset(
    {
        "contract_name",
        "version",
        "status",
        "permit_sha256",
        "permit_contract_name",
        "permit_version",
        "epoch_started_at",
        "epoch_started_ms",
        "terminal_identity_sha256",
        "qualification_certificate_sha256",
        "issued_at",
        "expires_at",
    }
)
CANDIDATE_AUTHORITY_EVIDENCE_KEYS = frozenset(
    {
        "status",
        "phase",
        "boundary",
        "contract_name",
        "version",
        "epoch_started_ms",
        "qualified_at",
        "terminal_identity_sha256",
        "qualification_certificate_schema",
        "qualification_certificate_sha256",
        "qualification_certificate_identity",
        "qualification_certificate_event_hash",
        "permit_sha256",
        "permit_commit",
        "epoch_void_ledger",
        "permit_issued_at",
        "permit_expires_at",
        "current_predicate",
    }
)
CANDIDATE_AUTHORITY_TUPLE_KEYS = CANDIDATE_AUTHORITY_EVIDENCE_KEYS - {
    "status",
    "phase",
    "boundary",
    "current_predicate",
}
CURRENT_PREDICATE_EVIDENCE_KEYS = frozenset(
    {
        "contract_name",
        "version",
        "status",
        "epoch_started_ms",
        "generation",
        "record_sha256",
        "boot_id",
        "monotonic_ns",
        "sentinel_producer_sha256",
        "root_predicate_producer_sha256",
    }
)
CANDIDATE_RUNTIME_OPERATION_KEYS = frozenset(
    {
        "sequence",
        "operation",
        "resource",
        "runner_acknowledged",
        "authority",
    }
)
CANDIDATE_OPERATION_RESOURCE_KEYS = frozenset({"argv", "target"})
CANDIDATE_RUNTIME_OPERATIONS_BY_BOUNDARY = {
    "before_candidate_up": frozenset({"compose_up"}),
    "before_candidate_exec": frozenset(
        {
            "redis_ping",
            "runtime_projection_snapshot",
            "candidate_openapi_snapshot",
            "contribution_mode_probe",
            "conversation_state_mode_probe",
            "internal_transport_request",
        }
    ),
    "before_candidate_interaction": frozenset(
        {
            "candidate_smoke",
            "candidate_smoke_after_restart",
            "runtime_identity_probe",
            "browser_surface_audit",
        }
    ),
    "before_candidate_restart": frozenset({"compose_restart_api"}),
}
CANDIDATE_PERMIT_ISSUANCE_KEYS = frozenset(
    {
        "contract_name",
        "version",
        "status",
        "recorded_at",
        "sentinel_state_path",
        "sentinel_state_owner_uid",
        "permit_mode",
        "permit",
        "permit_sha256",
        "permit_commit",
        "permit_commit_sha256",
        "epoch_void_ledger",
        "current_predicate",
    }
)
CANDIDATE_FINALIZATION_KEYS = frozenset(
    {
        "contract_name",
        "version",
        "status",
        "sealed_at",
        "sentinel_state_path",
        "sentinel_state_owner_uid",
        "epoch_started_ms",
        "terminal_identity_sha256",
        "qualification_certificate_schema",
        "qualification_certificate_sha256",
        "qualification_certificate_identity",
        "qualification_certificate_event_hash",
        "candidate_receipt_path",
        "candidate_receipt_owner_uid",
        "candidate_receipt_schema",
        "candidate_receipt_sha256",
        "candidate_observed_at",
        "source_revision",
        "image_tag",
        "image_id",
        "compose_project",
        "candidate_permit_sha256",
        "candidate_permit_commit_sha256",
        "candidate_issuance_record_sha256",
        "image_build_receipt_path",
        "image_build_receipt_owner_uid",
        "image_build_receipt_schema",
        "image_build_receipt_sha256",
        "image_build_producer_sha256",
        "image_reused",
        "image_build_permit_sha256",
        "image_build_permit_commit_sha256",
        "image_build_issuance_record_sha256",
        "candidate_operation_evidence_sha256",
        "candidate_publication_evidence_sha256",
        "candidate_publication_published_at",
        "candidate_publication_deadline_monotonic_ns",
        "image_build_operation_evidence_sha256",
        "image_build_publication_evidence_sha256",
        "image_build_publication_published_at",
        "image_build_publication_deadline_monotonic_ns",
        "finalization_boot_id",
        "finalization_monotonic_ns",
    }
)
CANDIDATE_FINALIZATION_COMMIT_KEYS = frozenset(
    {
        "contract_name",
        "version",
        "status",
        "committed_at",
        "candidate_permit_sha256",
        "finalization_record_sha256",
        "candidate_publication_evidence_sha256",
        "image_build_publication_evidence_sha256",
        "boot_id",
        "monotonic_ns",
    }
)
CANDIDATE_FINALIZATION_ABORT_KEYS = frozenset(
    {
        "contract_name",
        "version",
        "status",
        "aborted_at",
        "candidate_permit_sha256",
        "finalization_record_sha256",
        "finalization_commit_sha256",
        "reason",
    }
)
CURRENT_PREDICATE_POINTER_KEYS = frozenset(
    {
        "contract_name",
        "version",
        "status",
        "epoch_started_ms",
        "generation",
        "record_path",
        "record_sha256",
    }
)
CURRENT_PREDICATE_RECORD_KEYS = frozenset(
    {
        "contract_name",
        "version",
        "status",
        "epoch_started_ms",
        "generation",
        "observed_at",
        "recorded_at",
        "boot_id",
        "monotonic_ns",
        "sentinel_state_path",
        "sentinel_state_owner_uid",
        "sentinel_state_sha256",
        "terminal_identity_sha256",
        "qualification_certificate_sha256",
        "predicate_contract_sha256",
        "current_resources_healthy",
        "certification_blockers",
        "certification_deferments",
        "sentinel_producer_sha256",
        "root_predicate_producer_sha256",
        "previous_record_sha256",
    }
)
CURRENT_PREDICATE_PRODUCER_MANIFEST_KEYS = frozenset(
    {"contract_name", "version", "status", "producer_path", "producer_sha256"}
)
CANDIDATE_BOUNDARY_EVENT_KEYS = frozenset(
    {
        "contract_name",
        "version",
        "status",
        "receipt_kind",
        "sequence",
        "event_nonce",
        "permit_sha256",
        "permit_commit_sha256",
        "epoch_started_ms",
        "qualification_certificate_sha256",
        "current_predicate_generation",
        "current_predicate_record_sha256",
        "boundary",
        "operation",
        "resource_sha256",
        "producer_sha256",
        "root_attestor_sha256",
        "boot_id",
        "opened_at",
        "closed_at",
        "opened_monotonic_ns",
        "closed_monotonic_ns",
        "deadline_monotonic_ns",
        "previous_event_sha256",
    }
)
CANDIDATE_PUBLICATION_EVIDENCE_KEYS = frozenset(
    {
        "contract_name",
        "version",
        "status",
        "receipt_kind",
        "permit_sha256",
        "permit_commit_sha256",
        "epoch_started_ms",
        "qualification_certificate_sha256",
        "current_predicate_record_sha256",
        "receipt_path",
        "receipt_sha256",
        "producer_sha256",
        "root_attestor_sha256",
        "operation_tail_sha256",
        "boot_id",
        "published_at",
        "published_monotonic_ns",
        "deadline_monotonic_ns",
    }
)
CANDIDATE_EVIDENCE_PRODUCER_MANIFEST_KEYS = frozenset(
    {
        "contract_name",
        "version",
        "status",
        "attestor_path",
        "attestor_sha256",
        "allowed_producers",
    }
)
CANDIDATE_EVIDENCE_ALLOWED_PRODUCER_KEYS = frozenset(
    {"receipt_kind", "producer_sha256"}
)
VEXP_RECOVERY_MANIFEST_KEYS = frozenset(
    {
        "contract_name",
        "version",
        "status",
        "qualification_schema_version",
        "recovery_scope",
        "reviewed_revision",
        "artifacts",
    }
)
VEXP_RECOVERY_MANIFEST_ARTIFACT_KEYS = frozenset({"path", "sha256"})
VEXP_EPOCH_VOID_KEYS = frozenset(
    {
        "contract_name",
        "version",
        "status",
        "epoch_started_at",
        "epoch_started_ms",
        "sentinel_state_path",
        "sentinel_state_owner_uid",
        "sentinel_state_sha256",
        "voided_at",
        "reason",
        "maintenance_manifest_path",
        "maintenance_manifest_sha256",
        "reviewed_revision",
    }
)
VEXP_UTC_TIMESTAMP_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$"
)
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
SHA256_IDENTITY_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
BOOT_ID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
GIT_COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
IMAGE_ID_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
IMAGE_TAG_PATTERN = re.compile(
    r"^ea-runtime:(?:manfred|memorial)-[0-9a-f]{40}$"
)
CANDIDATE_PROJECT_PATTERN = re.compile(
    r"^ea-manfred-candidate-[a-z0-9](?:[a-z0-9_-]{0,61}[a-z0-9])?$"
)
MINIMUM_QUALIFICATION_DURATION_MS = 7 * 24 * 60 * 60 * 1000
MINIMUM_VEXP_QUALIFICATION_AT = datetime(2026, 7, 20, 9, 43, 56, 206_000, tzinfo=UTC)
MAX_CANDIDATE_BOUNDARY_DURATION_NS = 10 * 60 * 1_000_000_000

ACTIVE_CHAIN_KEYS = frozenset(
    {
        "anchor",
        "qualification_event",
        "tail_sequence",
        "tail_hash",
        "event_count",
        "index",
        "index_sha256",
    }
)
CHAIN_INDEX_ROW_KEYS = frozenset(
    {"at", "event", "sequence", "previous_hash", "hash"}
)
SOURCE_ATTESTATION_KEYS = frozenset(
    {
        "sentinel_state_sha256",
        "event_generations",
        "event_log_guard_sha256",
        "event_log_guard",
        "apparmor_audit_sha256",
        "apparmor_audit",
        "implementation_manifest_sha256",
        "implementation",
    }
)
IMPLEMENTATION_ATTESTATION_KEYS = frozenset(
    {
        "sentinel_executable",
        "sentinel_systemd_unit",
        "predicate_contract",
        "finalizer_executable",
        "finalizer_checksum_manifest",
        "finalizer_checksum_binding",
        "finalizer_systemd_unit",
        "systemd_runtime",
        "apparmor_policy",
    }
)
IMPLEMENTATION_FILE_ATTESTATION_KEYS = IMPLEMENTATION_ATTESTATION_KEYS - {
    "predicate_contract"
}
IMPLEMENTATION_MANIFEST_KEYS = frozenset(
    {"contract_name", "version", "status", "artifacts"}
)
IMPLEMENTATION_MANIFEST_ARTIFACT_KEYS = frozenset(
    {"path", "sha256", "owner_uid", "owner_gid", "mode"}
)
SEAL_KEYS = frozenset(
    {
        "writer",
        "write_policy",
        "telegram_sent_by_finalizer",
        "docker_socket_used",
    }
)


class PermitError(RuntimeError):
    """A fail-closed permit authority error."""


def _utc_now_datetime() -> datetime:
    return datetime.now(UTC)


def _format_utc_timestamp(value: datetime) -> str:
    return (
        value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    )


def _parse_utc_timestamp(value: object, *, reason: str) -> datetime:
    if not isinstance(value, str) or not VEXP_UTC_TIMESTAMP_PATTERN.fullmatch(value):
        raise PermitError(reason)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PermitError(reason) from exc
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise PermitError(reason)
    return parsed.astimezone(UTC)


def _require_utc_clock(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise PermitError("vexp_permit_clock_invalid")
    return value.astimezone(UTC)


def _datetime_epoch_ms(value: datetime) -> int:
    delta = value - datetime(1970, 1, 1, tzinfo=UTC)
    return delta.days * 86_400_000 + delta.seconds * 1_000 + delta.microseconds // 1_000


def _trusted_file_identity(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_nlink,
        metadata.st_uid,
        metadata.st_gid,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _trusted_directory_identity(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_uid,
        metadata.st_gid,
    )


def _decode_guard_json(raw: bytes, *, reason: str) -> dict[str, Any]:
    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for key, value in pairs:
            if key in payload:
                raise ValueError("duplicate_json_key")
            payload[key] = value
        return payload

    def reject_constant(_value: str) -> None:
        raise ValueError("non_finite_json_constant")

    try:
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=unique_object,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, ValueError) as exc:
        raise PermitError(reason) from exc
    if not isinstance(payload, dict):
        raise PermitError(reason)
    return payload


def _terminal_identity(state: Mapping[str, Any]) -> dict[str, object]:
    return {
        "epoch_started_at": state.get("epoch_started_at"),
        "epoch_started_ms": state.get("epoch_started_ms"),
        "qualification_earliest_completion_at": state.get(
            "qualification_earliest_completion_at"
        ),
        "qualified_at": state.get("qualified_at"),
    }


def _terminal_identity_sha256(state: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        _terminal_identity(state),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _canonical_json_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _canonical_record_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _permit_mode_for_payload(permit: Mapping[str, Any]) -> str:
    for permit_mode in PERMIT_MODES:
        contract_name, version, boundaries = _permit_contract(permit_mode)
        if (
            permit.get("contract_name") == contract_name
            and permit.get("version") == version
            and permit.get("mutation_boundaries") == list(boundaries)
        ):
            return permit_mode
    raise PermitError("vexp_mutation_permit_contract_invalid")


def _qualification_certificate_paths(epoch_started_ms: int) -> tuple[Path, Path]:
    if type(epoch_started_ms) is not int or epoch_started_ms <= 0:
        raise PermitError("vexp_qualification_certificate_epoch_invalid")
    certificate_path = QUALIFICATION_CERTIFICATE_DIRECTORY / f"{epoch_started_ms}.json"
    return certificate_path, certificate_path.with_suffix(".json.sha256")


def _validate_qualification_certificate_directory(path: Path, *, reason: str) -> None:
    try:
        metadata = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise PermitError(reason) from exc
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode)
        != QUALIFICATION_CERTIFICATE_DIRECTORY_MODE
        or metadata.st_uid != QUALIFICATION_CERTIFICATE_OWNER_UID
        or metadata.st_gid != QUALIFICATION_CERTIFICATE_OWNER_GID
    ):
        raise PermitError(reason)


def _require_sha256(value: object, *, reason: str) -> str:
    if not isinstance(value, str) or not SHA256_PATTERN.fullmatch(value):
        raise PermitError(reason)
    return value


def _validate_qualification_certificate(
    certificate: Mapping[str, Any],
    *,
    state: Mapping[str, Any],
) -> dict[str, str]:
    reason = "vexp_qualification_certificate_contract_invalid"
    if certificate.get("schema") != VEXP_QUALIFICATION_CERTIFICATE_SCHEMA:
        raise PermitError(reason)
    if (
        type(certificate.get("sentinel_version")) is not int
        or certificate["sentinel_version"] != VEXP_SENTINEL_STATE_VERSION
    ):
        raise PermitError("vexp_qualification_certificate_sentinel_version_invalid")

    epoch_started_ms = state.get("epoch_started_ms")
    if (
        type(epoch_started_ms) is not int
        or certificate.get("epoch_started_ms") != epoch_started_ms
        or certificate.get("epoch_started_at") != state.get("epoch_started_at")
        or certificate.get("qualified_at") != state.get("qualified_at")
    ):
        raise PermitError("vexp_qualification_certificate_terminal_binding_invalid")
    epoch_started_at = _parse_utc_timestamp(
        certificate.get("epoch_started_at"),
        reason="vexp_qualification_certificate_terminal_binding_invalid",
    )
    qualified_at = _parse_utc_timestamp(
        certificate.get("qualified_at"),
        reason="vexp_qualification_certificate_terminal_binding_invalid",
    )
    if (
        epoch_started_at.microsecond % 1_000 != 0
        or _datetime_epoch_ms(epoch_started_at) != epoch_started_ms
    ):
        raise PermitError("vexp_qualification_certificate_terminal_binding_invalid")
    wall_duration_ms = _datetime_epoch_ms(qualified_at) - epoch_started_ms
    qualification_duration_ms = certificate.get("qualification_duration_ms")
    monotonic_duration_ms = certificate.get("qualification_monotonic_duration_ms")
    qualification_boot_id = certificate.get("qualification_boot_id")
    monotonic_started_ns = certificate.get("qualification_monotonic_started_ns")
    monotonic_qualified_ns = certificate.get("qualification_monotonic_qualified_ns")
    if (
        type(qualification_duration_ms) is not int
        or qualification_duration_ms != wall_duration_ms
        or qualification_duration_ms < MINIMUM_QUALIFICATION_DURATION_MS
        or type(monotonic_duration_ms) is not int
        or monotonic_duration_ms < MINIMUM_QUALIFICATION_DURATION_MS
        or not isinstance(qualification_boot_id, str)
        or BOOT_ID_PATTERN.fullmatch(qualification_boot_id) is None
        or type(monotonic_started_ns) is not int
        or monotonic_started_ns <= 0
        or type(monotonic_qualified_ns) is not int
        or monotonic_qualified_ns <= monotonic_started_ns
        or monotonic_qualified_ns - monotonic_started_ns
        != monotonic_duration_ms * 1_000_000
    ):
        raise PermitError("vexp_qualification_certificate_duration_invalid")

    active_chain = certificate.get("active_chain")
    if not isinstance(active_chain, dict) or set(active_chain) != ACTIVE_CHAIN_KEYS:
        raise PermitError("vexp_qualification_certificate_chain_invalid")
    anchor = active_chain.get("anchor")
    if not isinstance(anchor, dict) or anchor.get("event") != "qualification_reset":
        raise PermitError("vexp_qualification_certificate_chain_invalid")
    try:
        anchor_row = {key: anchor[key] for key in CHAIN_INDEX_ROW_KEYS}
    except KeyError as exc:
        raise PermitError("vexp_qualification_certificate_chain_invalid") from exc
    index = active_chain.get("index")
    event_count = active_chain.get("event_count")
    if (
        not isinstance(index, list)
        or not index
        or type(event_count) is not int
        or event_count != len(index)
    ):
        raise PermitError("vexp_qualification_certificate_chain_invalid")
    normalized_rows: list[dict[str, Any]] = []
    previous_hash: str | None = None
    previous_sequence: int | None = None
    for row_index, row in enumerate(index):
        if not isinstance(row, dict) or set(row) != CHAIN_INDEX_ROW_KEYS:
            raise PermitError("vexp_qualification_certificate_chain_invalid")
        sequence = row.get("sequence")
        row_previous_hash = _require_sha256(
            row.get("previous_hash"),
            reason="vexp_qualification_certificate_chain_invalid",
        )
        if (
            type(sequence) is not int
            or sequence < 0
            or (previous_sequence is not None and sequence != previous_sequence + 1)
            or (row_index > 0 and row_previous_hash != previous_hash)
            or not isinstance(row.get("event"), str)
            or not row["event"]
        ):
            raise PermitError("vexp_qualification_certificate_chain_invalid")
        _parse_utc_timestamp(
            row.get("at"), reason="vexp_qualification_certificate_chain_invalid"
        )
        row_hash = _require_sha256(
            row.get("hash"), reason="vexp_qualification_certificate_chain_invalid"
        )
        normalized_rows.append(dict(row))
        previous_hash = row_hash
        previous_sequence = sequence
    if (
        anchor_row != normalized_rows[0]
        or active_chain.get("tail_sequence") != previous_sequence
        or active_chain.get("tail_hash") != previous_hash
        or _require_sha256(
            active_chain.get("index_sha256"),
            reason="vexp_qualification_certificate_chain_invalid",
        )
        != _canonical_json_sha256(normalized_rows)
    ):
        raise PermitError("vexp_qualification_certificate_chain_invalid")
    qualification_event = active_chain.get("qualification_event")
    if not isinstance(qualification_event, dict):
        raise PermitError("vexp_qualification_certificate_chain_invalid")
    try:
        qualification_row = {
            key: qualification_event[key] for key in CHAIN_INDEX_ROW_KEYS
        }
    except KeyError as exc:
        raise PermitError("vexp_qualification_certificate_chain_invalid") from exc
    if (
        qualification_event.get("event") != "seven_day_qualification_achieved"
        or qualification_event.get("at") != certificate.get("qualified_at")
        or sum(row == qualification_row for row in normalized_rows) != 1
    ):
        raise PermitError("vexp_qualification_certificate_chain_invalid")
    qualification_event_hash = _require_sha256(
        qualification_event.get("hash"),
        reason="vexp_qualification_certificate_chain_invalid",
    )

    terminal_state = certificate.get("terminal_state")
    if not isinstance(terminal_state, dict):
        raise PermitError("vexp_qualification_certificate_terminal_state_invalid")
    if (
        terminal_state.get("version") != VEXP_SENTINEL_STATE_VERSION
        or terminal_state.get("epoch_started_at") != state.get("epoch_started_at")
        or terminal_state.get("epoch_started_ms") != epoch_started_ms
        or terminal_state.get("qualified_at") != state.get("qualified_at")
        or terminal_state.get("qualification_boot_id") != qualification_boot_id
        or terminal_state.get("qualification_monotonic_started_ns")
        != monotonic_started_ns
        or terminal_state.get("qualification_monotonic_qualified_ns")
        != monotonic_qualified_ns
        or terminal_state.get("qualification_phase") != "qualified"
        or terminal_state.get("certification_blockers") != []
        or terminal_state.get("certification_deferments") != []
        or terminal_state.get("last_event_hash") != previous_hash
    ):
        raise PermitError("vexp_qualification_certificate_terminal_state_invalid")

    attestations = certificate.get("source_attestations")
    if not isinstance(attestations, dict) or set(attestations) != SOURCE_ATTESTATION_KEYS:
        raise PermitError("vexp_qualification_certificate_attestations_invalid")
    for key in (
        "sentinel_state_sha256",
        "event_log_guard_sha256",
        "apparmor_audit_sha256",
        "implementation_manifest_sha256",
    ):
        _require_sha256(
            attestations.get(key),
            reason="vexp_qualification_certificate_attestations_invalid",
        )
    if (
        not isinstance(attestations.get("event_generations"), (list, dict))
        or not attestations["event_generations"]
        or not isinstance(attestations.get("event_log_guard"), dict)
        or not attestations["event_log_guard"]
        or not isinstance(attestations.get("apparmor_audit"), dict)
        or not attestations["apparmor_audit"]
    ):
        raise PermitError("vexp_qualification_certificate_attestations_invalid")
    implementation = attestations.get("implementation")
    if (
        not isinstance(implementation, dict)
        or set(implementation) != IMPLEMENTATION_ATTESTATION_KEYS
        or any(value in (None, "", [], {}) for value in implementation.values())
    ):
        raise PermitError("vexp_qualification_certificate_attestations_invalid")
    predicate_contract = implementation.get("predicate_contract")
    if (
        not isinstance(predicate_contract, dict)
        or set(predicate_contract) != {"value", "sha256"}
        or predicate_contract.get("value") in (None, "", [], {})
    ):
        raise PermitError("vexp_qualification_certificate_attestations_invalid")
    _require_sha256(
        predicate_contract.get("sha256"),
        reason="vexp_qualification_certificate_attestations_invalid",
    )
    for implementation_key in IMPLEMENTATION_ATTESTATION_KEYS - {
        "predicate_contract"
    }:
        implementation_identity = implementation.get(implementation_key)
        if (
            not isinstance(implementation_identity, dict)
            or set(implementation_identity) != {"sha256"}
        ):
            raise PermitError(
                "vexp_qualification_certificate_attestations_invalid"
            )
        _require_sha256(
            implementation_identity.get("sha256"),
            reason="vexp_qualification_certificate_attestations_invalid",
        )
    if (
        terminal_state.get("predicate_contract") != predicate_contract["value"]
        or terminal_state.get("predicate_contract_sha256")
        != predicate_contract["sha256"]
        or state.get("predicate_contract") != predicate_contract["value"]
        or state.get("predicate_contract_sha256") != predicate_contract["sha256"]
    ):
        raise PermitError(
            "vexp_qualification_certificate_predicate_contract_binding_invalid"
        )

    seal = certificate.get("seal")
    if (
        not isinstance(seal, dict)
        or set(seal) != SEAL_KEYS
        or seal.get("writer") != "root_owned_systemd_oneshot"
        or seal.get("write_policy") != "create_exclusive_never_overwrite"
        or seal.get("telegram_sent_by_finalizer") is not False
        or seal.get("docker_socket_used") is not False
    ):
        raise PermitError("vexp_qualification_certificate_seal_invalid")

    identity = certificate.get("identity")
    if not isinstance(identity, str) or not SHA256_IDENTITY_PATTERN.fullmatch(identity):
        raise PermitError("vexp_qualification_certificate_identity_invalid")
    identity_payload = dict(certificate)
    identity_payload.pop("identity", None)
    if identity != f"sha256:{_canonical_json_sha256(identity_payload)}":
        raise PermitError("vexp_qualification_certificate_identity_invalid")
    return {
        "schema": VEXP_QUALIFICATION_CERTIFICATE_SCHEMA,
        "identity": identity,
        "event_hash": qualification_event_hash,
    }


def _read_qualification_certificate(
    state: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, str]]:
    epoch_started_ms = state.get("epoch_started_ms")
    if type(epoch_started_ms) is not int or epoch_started_ms <= 0:
        raise PermitError("vexp_qualification_certificate_epoch_invalid")
    _validate_qualification_certificate_directory(
        QUALIFICATION_CERTIFICATE_ROOT,
        reason="vexp_qualification_certificate_root_untrusted",
    )
    _validate_qualification_certificate_directory(
        QUALIFICATION_CERTIFICATE_DIRECTORY,
        reason="vexp_qualification_certificate_directory_untrusted",
    )
    certificate_path, sidecar_path = _qualification_certificate_paths(
        epoch_started_ms
    )
    raw, _metadata = _trusted_read(
        certificate_path,
        expected_mode=QUALIFICATION_CERTIFICATE_MODE,
        expected_uid=QUALIFICATION_CERTIFICATE_OWNER_UID,
        expected_gid=QUALIFICATION_CERTIFICATE_OWNER_GID,
        max_bytes=MAX_VEXP_QUALIFICATION_CERTIFICATE_BYTES,
        reason_prefix="vexp_qualification_certificate",
    )
    sidecar, _sidecar_metadata = _trusted_read(
        sidecar_path,
        expected_mode=QUALIFICATION_CERTIFICATE_MODE,
        expected_uid=QUALIFICATION_CERTIFICATE_OWNER_UID,
        expected_gid=QUALIFICATION_CERTIFICATE_OWNER_GID,
        max_bytes=MAX_VEXP_QUALIFICATION_CERTIFICATE_SIDECAR_BYTES,
        reason_prefix="vexp_qualification_certificate_sidecar",
    )
    raw_sha256 = hashlib.sha256(raw).hexdigest()
    if sidecar != f"sha256:{raw_sha256}\n".encode("ascii"):
        raise PermitError("vexp_qualification_certificate_sidecar_invalid")
    certificate = _decode_guard_json(
        raw, reason="vexp_qualification_certificate_json_invalid"
    )
    evidence = _validate_qualification_certificate(certificate, state=state)
    _require_reviewed_qualification_implementation_manifest(certificate)
    evidence["sha256"] = raw_sha256
    return certificate, evidence


def _current_executable_path() -> Path:
    return Path(os.path.abspath(__file__))


def _current_python_executable() -> Path:
    return Path(os.path.abspath(sys.executable))


def _isolated_mode_enabled() -> bool:
    return sys.flags.isolated == 1


def _verify_trusted_execution_path() -> None:
    """Require the reviewed, immutable root installation before any operation."""

    if not _isolated_mode_enabled():
        raise PermitError("vexp_permit_manager_isolated_mode_required")
    if _current_python_executable() != TRUSTED_PYTHON_EXECUTABLE:
        raise PermitError("vexp_permit_manager_python_untrusted")
    current_path = _current_executable_path()
    if current_path != TRUSTED_EXECUTABLE_PATH:
        raise PermitError("vexp_permit_manager_execution_path_untrusted")
    parent = TRUSTED_EXECUTABLE_PATH.parent
    try:
        parent_metadata = os.stat(parent, follow_symlinks=False)
    except OSError as exc:
        raise PermitError("vexp_permit_manager_parent_unavailable") from exc
    if (
        not stat.S_ISDIR(parent_metadata.st_mode)
        or stat.S_IMODE(parent_metadata.st_mode) != TRUSTED_EXECUTABLE_PARENT_MODE
        or parent_metadata.st_uid != ROOT_UID
        or parent_metadata.st_gid != ROOT_GID
    ):
        raise PermitError("vexp_permit_manager_parent_untrusted")
    _require_safe_open_flags("vexp_permit_manager")
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
    descriptor = -1
    try:
        descriptor = os.open(TRUSTED_EXECUTABLE_PATH, flags)
        metadata = os.fstat(descriptor)
        path_metadata = os.stat(TRUSTED_EXECUTABLE_PATH, follow_symlinks=False)
    except OSError as exc:
        raise PermitError("vexp_permit_manager_executable_unavailable") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or stat.S_IMODE(metadata.st_mode) != TRUSTED_EXECUTABLE_MODE
        or metadata.st_uid != ROOT_UID
        or metadata.st_gid != ROOT_GID
        or _trusted_file_identity(path_metadata) != _trusted_file_identity(metadata)
    ):
        raise PermitError("vexp_permit_manager_executable_untrusted")


def _require_safe_open_flags(reason_prefix: str) -> None:
    if not hasattr(os, "O_NOFOLLOW"):
        raise PermitError(f"{reason_prefix}_nofollow_unavailable")
    if not hasattr(os, "O_NONBLOCK"):
        raise PermitError(f"{reason_prefix}_nonblock_unavailable")


def _trusted_read(
    path: Path,
    *,
    expected_mode: int,
    expected_uid: int,
    expected_gid: int | None,
    max_bytes: int,
    reason_prefix: str,
) -> tuple[bytes, os.stat_result]:
    _require_safe_open_flags(reason_prefix)
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
    descriptor = -1
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise PermitError(f"{reason_prefix}_unavailable") from exc
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or stat.S_IMODE(metadata.st_mode) != expected_mode
            or metadata.st_uid != expected_uid
            or (expected_gid is not None and metadata.st_gid != expected_gid)
        ):
            raise PermitError(f"{reason_prefix}_untrusted")
        if not 0 < metadata.st_size <= max_bytes:
            raise PermitError(f"{reason_prefix}_size_invalid")
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = -1
            raw = handle.read(max_bytes + 1)
            final_metadata = os.fstat(handle.fileno())
    except OSError as exc:
        raise PermitError(f"{reason_prefix}_unreadable") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    try:
        final_path_metadata = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise PermitError(f"{reason_prefix}_changed_during_read") from exc
    if (
        len(raw) != metadata.st_size
        or len(raw) > max_bytes
        or _trusted_file_identity(final_metadata) != _trusted_file_identity(metadata)
        or _trusted_file_identity(final_path_metadata)
        != _trusted_file_identity(metadata)
    ):
        raise PermitError(f"{reason_prefix}_changed_during_read")
    return raw, final_metadata


def _measure_trusted_root_producer(
    path: Path,
    *,
    expected_sha256: str,
    reason_prefix: str,
) -> tuple[str, tuple[int, ...]]:
    expected_digest = _require_sha256(
        expected_sha256,
        reason=f"{reason_prefix}_sha256_invalid",
    )
    parent = TRUSTED_ROOT_PRODUCER_INSTALL_PARENT
    if (
        not path.is_absolute()
        or not parent.is_absolute()
        or path.parent != parent
        or ".." in path.parts
    ):
        raise PermitError(f"{reason_prefix}_path_invalid")
    chain = (parent,)
    if parent == Path("/usr/local/libexec"):
        chain = (Path("/"), Path("/usr"), Path("/usr/local"), parent)
    for directory in chain:
        try:
            directory_metadata = os.stat(directory, follow_symlinks=False)
        except OSError as exc:
            raise PermitError(f"{reason_prefix}_parent_unavailable") from exc
        if (
            not stat.S_ISDIR(directory_metadata.st_mode)
            or stat.S_IMODE(directory_metadata.st_mode)
            != TRUSTED_ROOT_PRODUCER_DIRECTORY_MODE
            or directory_metadata.st_uid != ROOT_UID
            or directory_metadata.st_gid != ROOT_GID
        ):
            raise PermitError(f"{reason_prefix}_parent_untrusted")
    raw, metadata = _trusted_read(
        path,
        expected_mode=TRUSTED_ROOT_PRODUCER_MODE,
        expected_uid=ROOT_UID,
        expected_gid=ROOT_GID,
        max_bytes=MAX_TRUSTED_ROOT_PRODUCER_BYTES,
        reason_prefix=reason_prefix,
    )
    observed_digest = hashlib.sha256(raw).hexdigest()
    if observed_digest != expected_digest:
        raise PermitError(f"{reason_prefix}_sha256_mismatch")
    return observed_digest, _trusted_file_identity(metadata)


def _validate_trusted_directory(
    path: Path,
    *,
    expected_mode: int,
    expected_uid: int,
    expected_gid: int,
    reason: str,
) -> os.stat_result:
    try:
        metadata = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise PermitError(reason) from exc
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != expected_mode
        or metadata.st_uid != expected_uid
        or metadata.st_gid != expected_gid
    ):
        raise PermitError(reason)
    return metadata


def _validate_trusted_storage_chain(path: Path, *, reason: str) -> None:
    """Validate every mutable directory component beneath the fixed root anchor.

    Production callers are compiled with ``/var/lib`` as the immutable anchor.
    Tests may replace that constant together with the root uid; installed code
    cannot.  No component beneath the anchor may be a symlink, non-directory,
    non-root-owned, or writable by group/other.
    """

    anchor = TRUSTED_AUTHORITY_STORAGE_PREFIX
    if not path.is_absolute() or not anchor.is_absolute():
        raise PermitError(reason)
    try:
        relative = path.relative_to(anchor)
    except ValueError as exc:
        raise PermitError(reason) from exc
    chain = [anchor]
    current = anchor
    for component in relative.parts:
        current = current / component
        chain.append(current)
    if anchor == Path("/var/lib"):
        chain = [Path("/"), Path("/var"), *chain]
    for component in chain:
        try:
            metadata = os.stat(component, follow_symlinks=False)
        except OSError as exc:
            raise PermitError(reason) from exc
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or stat.S_ISLNK(metadata.st_mode)
            or metadata.st_uid != ROOT_UID
            or stat.S_IMODE(metadata.st_mode) & 0o022
        ):
            raise PermitError(reason)


def _validate_root_owned_artifact_parent_chain(path: Path, *, reason: str) -> None:
    if not path.is_absolute() or path.name in {"", ".", ".."} or ".." in path.parts:
        raise PermitError(reason)
    chain = [Path("/")]
    current = Path("/")
    for component in path.parent.parts[1:]:
        current = current / component
        chain.append(current)
    for directory in chain:
        try:
            metadata = os.stat(directory, follow_symlinks=False)
        except OSError as exc:
            raise PermitError(reason) from exc
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != ROOT_UID
            or stat.S_IMODE(metadata.st_mode) & 0o022
        ):
            raise PermitError(reason)


def _require_reviewed_qualification_implementation_manifest(
    certificate: Mapping[str, Any],
) -> None:
    """Bind certificate implementation claims to reviewed, measured root files."""

    missing_reason = "vexp_qualification_implementation_manifest_missing"
    reason = "vexp_qualification_implementation_manifest_invalid"
    try:
        os.stat(QUALIFICATION_IMPLEMENTATION_MANIFEST_PATH, follow_symlinks=False)
    except FileNotFoundError as exc:
        raise PermitError(missing_reason) from exc
    except OSError as exc:
        raise PermitError(reason) from exc
    _validate_trusted_storage_chain(
        RECOVERY_MANIFEST_ROOT,
        reason="vexp_qualification_implementation_manifest_root_untrusted",
    )
    _validate_trusted_directory(
        RECOVERY_MANIFEST_ROOT,
        expected_mode=RECOVERY_MANIFEST_DIRECTORY_MODE,
        expected_uid=RECOVERY_MANIFEST_OWNER_UID,
        expected_gid=RECOVERY_MANIFEST_OWNER_GID,
        reason="vexp_qualification_implementation_manifest_root_untrusted",
    )
    raw, _metadata = _trusted_read(
        QUALIFICATION_IMPLEMENTATION_MANIFEST_PATH,
        expected_mode=RECOVERY_MANIFEST_MODE,
        expected_uid=RECOVERY_MANIFEST_OWNER_UID,
        expected_gid=RECOVERY_MANIFEST_OWNER_GID,
        max_bytes=MAX_VEXP_RECOVERY_MANIFEST_BYTES,
        reason_prefix="vexp_qualification_implementation_manifest",
    )
    manifest = _decode_guard_json(raw, reason=reason)
    manifest_sha256 = hashlib.sha256(raw).hexdigest()
    source_attestations = certificate.get("source_attestations")
    implementation = (
        source_attestations.get("implementation")
        if isinstance(source_attestations, dict)
        else None
    )
    if (
        raw != _canonical_record_bytes(manifest)
        or set(manifest) != IMPLEMENTATION_MANIFEST_KEYS
        or manifest.get("contract_name")
        != VEXP_QUALIFICATION_IMPLEMENTATION_MANIFEST_CONTRACT_NAME
        or manifest.get("version")
        != VEXP_QUALIFICATION_IMPLEMENTATION_MANIFEST_VERSION
        or manifest.get("status") != "reviewed"
        or not isinstance(implementation, dict)
        or not isinstance(source_attestations, dict)
        or source_attestations.get("implementation_manifest_sha256")
        != manifest_sha256
    ):
        raise PermitError(reason)
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != (
        IMPLEMENTATION_FILE_ATTESTATION_KEYS
    ):
        raise PermitError(reason)
    initial_artifact_raw: dict[str, bytes] = {}
    for artifact_name in sorted(IMPLEMENTATION_FILE_ATTESTATION_KEYS):
        artifact = artifacts.get(artifact_name)
        certificate_identity = implementation.get(artifact_name)
        if (
            not isinstance(artifact, dict)
            or set(artifact) != IMPLEMENTATION_MANIFEST_ARTIFACT_KEYS
            or not isinstance(certificate_identity, dict)
            or artifact.get("sha256") != certificate_identity.get("sha256")
            or type(artifact.get("owner_uid")) is not int
            or artifact["owner_uid"] != ROOT_UID
            or type(artifact.get("owner_gid")) is not int
            or artifact["owner_gid"] < 0
            or type(artifact.get("mode")) is not int
            or not 0 < artifact["mode"] <= 0o7777
            or artifact["mode"] & 0o022
        ):
            raise PermitError(reason)
        artifact_path_value = artifact.get("path")
        if not isinstance(artifact_path_value, str):
            raise PermitError(reason)
        artifact_path = Path(artifact_path_value)
        _validate_root_owned_artifact_parent_chain(artifact_path, reason=reason)
        expected_sha256 = _require_sha256(artifact.get("sha256"), reason=reason)
        artifact_raw, _artifact_metadata = _trusted_read(
            artifact_path,
            expected_mode=artifact["mode"],
            expected_uid=artifact["owner_uid"],
            expected_gid=artifact["owner_gid"],
            max_bytes=MAX_TRUSTED_ROOT_PRODUCER_BYTES,
            reason_prefix="vexp_qualification_implementation_artifact",
        )
        if hashlib.sha256(artifact_raw).hexdigest() != expected_sha256:
            raise PermitError(reason)
        initial_artifact_raw[artifact_name] = artifact_raw
    final_raw, _final_metadata = _trusted_read(
        QUALIFICATION_IMPLEMENTATION_MANIFEST_PATH,
        expected_mode=RECOVERY_MANIFEST_MODE,
        expected_uid=RECOVERY_MANIFEST_OWNER_UID,
        expected_gid=RECOVERY_MANIFEST_OWNER_GID,
        max_bytes=MAX_VEXP_RECOVERY_MANIFEST_BYTES,
        reason_prefix="vexp_qualification_implementation_manifest",
    )
    if final_raw != raw:
        raise PermitError("vexp_qualification_implementation_manifest_changed")
    for artifact_name in sorted(IMPLEMENTATION_FILE_ATTESTATION_KEYS):
        artifact = dict(artifacts[artifact_name])
        final_artifact_raw, _final_artifact_metadata = _trusted_read(
            Path(str(artifact["path"])),
            expected_mode=int(artifact["mode"]),
            expected_uid=int(artifact["owner_uid"]),
            expected_gid=int(artifact["owner_gid"]),
            max_bytes=MAX_TRUSTED_ROOT_PRODUCER_BYTES,
            reason_prefix="vexp_qualification_implementation_artifact",
        )
        if final_artifact_raw != initial_artifact_raw[artifact_name]:
            raise PermitError("vexp_qualification_implementation_artifact_changed")


def _current_boot_id() -> str:
    _require_safe_open_flags("vexp_boot_id")
    descriptor = -1
    try:
        descriptor = os.open(
            BOOT_ID_PATH,
            os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK,
        )
        metadata = os.fstat(descriptor)
        raw = os.read(descriptor, 128)
        final_metadata = os.fstat(descriptor)
    except OSError as exc:
        raise PermitError("vexp_boot_id_unavailable") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != ROOT_UID
        or _trusted_file_identity(metadata) != _trusted_file_identity(final_metadata)
    ):
        raise PermitError("vexp_boot_id_untrusted")
    value = raw.decode("ascii", errors="strict").strip().lower()
    if BOOT_ID_PATTERN.fullmatch(value) is None:
        raise PermitError("vexp_boot_id_invalid")
    return value


def _monotonic_ns() -> int:
    try:
        value = time.monotonic_ns()
    except Exception as exc:
        raise PermitError("vexp_monotonic_clock_invalid") from exc
    if type(value) is not int or value <= 0:
        raise PermitError("vexp_monotonic_clock_invalid")
    return value


def _current_predicate_generation_paths(
    *, epoch_started_ms: int, generation: int
) -> tuple[Path, ...]:
    """Return the exact, gap-free current-epoch predicate history."""

    reason = "vexp_current_predicate_generation_chain_invalid"
    if (
        type(epoch_started_ms) is not int
        or epoch_started_ms <= 0
        or type(generation) is not int
        or generation <= 0
    ):
        raise PermitError(reason)
    prefix = f"{epoch_started_ms}-"
    generations: dict[int, Path] = {}
    try:
        with os.scandir(CURRENT_PREDICATE_RECORD_DIRECTORY) as entries:
            for entry in entries:
                name = entry.name
                if not name.startswith(prefix):
                    continue
                match = re.fullmatch(rf"{re.escape(prefix)}([1-9][0-9]*)\.json", name)
                if match is None:
                    raise PermitError(reason)
                record_generation = int(match.group(1))
                if record_generation in generations:
                    raise PermitError(reason)
                generations[record_generation] = (
                    CURRENT_PREDICATE_RECORD_DIRECTORY / name
                )
    except PermitError:
        raise
    except OSError as exc:
        raise PermitError(reason) from exc
    ordered_generations = sorted(generations)
    if (
        len(ordered_generations) != generation
        or any(
            observed != expected
            for expected, observed in enumerate(ordered_generations, start=1)
        )
    ):
        raise PermitError(reason)
    return tuple(generations[index] for index in ordered_generations)


def _read_current_predicate_evidence(
    *,
    state: Mapping[str, Any],
    state_sha256: str,
    state_path: Path,
    state_owner_uid: int,
    certificate: Mapping[str, Any],
    qualification_certificate: Mapping[str, str],
    now: datetime,
) -> dict[str, object]:
    """Read the independent root-authenticated current-health projection.

    The operator-owned sentinel JSON remains useful detail, but cannot grant
    authority.  This root-owned pointer and append-only generation record bind
    the exact state bytes, epoch, terminal certificate, reviewed sentinel
    producer, boot, wall clock, and monotonic clock.  Missing plumbing is a
    denial by construction.
    """

    reason = "vexp_current_predicate_invalid"
    now = _require_utc_clock(now)
    _validate_trusted_storage_chain(
        CURRENT_PREDICATE_RECORD_DIRECTORY,
        reason="vexp_current_predicate_directory_chain_untrusted",
    )
    root_metadata = _validate_trusted_directory(
        CURRENT_PREDICATE_ROOT,
        expected_mode=CURRENT_PREDICATE_DIRECTORY_MODE,
        expected_uid=CURRENT_PREDICATE_OWNER_UID,
        expected_gid=CURRENT_PREDICATE_OWNER_GID,
        reason="vexp_current_predicate_root_untrusted",
    )
    records_metadata = _validate_trusted_directory(
        CURRENT_PREDICATE_RECORD_DIRECTORY,
        expected_mode=CURRENT_PREDICATE_DIRECTORY_MODE,
        expected_uid=CURRENT_PREDICATE_OWNER_UID,
        expected_gid=CURRENT_PREDICATE_OWNER_GID,
        reason="vexp_current_predicate_directory_untrusted",
    )
    pointer_raw, _pointer_metadata = _trusted_read(
        CURRENT_PREDICATE_POINTER_PATH,
        expected_mode=CURRENT_PREDICATE_RECORD_MODE,
        expected_uid=CURRENT_PREDICATE_OWNER_UID,
        expected_gid=CURRENT_PREDICATE_OWNER_GID,
        max_bytes=MAX_VEXP_CURRENT_PREDICATE_BYTES,
        reason_prefix="vexp_current_predicate_pointer",
    )
    pointer = _decode_guard_json(pointer_raw, reason=reason)
    epoch_started_ms = state.get("epoch_started_ms")
    generation = pointer.get("generation")
    if (
        set(pointer) != CURRENT_PREDICATE_POINTER_KEYS
        or pointer.get("contract_name")
        != VEXP_CURRENT_PREDICATE_POINTER_CONTRACT_NAME
        or pointer.get("version") != VEXP_CURRENT_PREDICATE_POINTER_VERSION
        or pointer.get("status") != "published"
        or type(epoch_started_ms) is not int
        or pointer.get("epoch_started_ms") != epoch_started_ms
        or type(generation) is not int
        or generation <= 0
        or pointer_raw != _canonical_record_bytes(pointer)
    ):
        raise PermitError(reason)
    generation_paths = _current_predicate_generation_paths(
        epoch_started_ms=epoch_started_ms,
        generation=generation,
    )
    record_path = generation_paths[-1]
    record_sha256 = _require_sha256(pointer.get("record_sha256"), reason=reason)
    if pointer.get("record_path") != str(record_path):
        raise PermitError(reason)
    chain_raw: list[bytes] = []
    chain: list[dict[str, Any]] = []
    chain_sha256: list[str] = []
    for record_index, history_path in enumerate(generation_paths, start=1):
        history_raw, _history_metadata = _trusted_read(
            history_path,
            expected_mode=CURRENT_PREDICATE_RECORD_MODE,
            expected_uid=CURRENT_PREDICATE_OWNER_UID,
            expected_gid=CURRENT_PREDICATE_OWNER_GID,
            max_bytes=MAX_VEXP_CURRENT_PREDICATE_BYTES,
            reason_prefix=(
                "vexp_current_predicate_record"
                if record_index == generation
                else "vexp_current_predicate_history_record"
            ),
        )
        history = _decode_guard_json(history_raw, reason=reason)
        if history_raw != _canonical_record_bytes(history):
            raise PermitError("vexp_current_predicate_record_noncanonical")
        chain_raw.append(history_raw)
        chain.append(history)
        chain_sha256.append(hashlib.sha256(history_raw).hexdigest())
    record_raw = chain_raw[-1]
    record = chain[-1]
    if chain_sha256[-1] != record_sha256:
        raise PermitError("vexp_current_predicate_record_sha256_mismatch")
    producer_manifest_raw, _producer_manifest_metadata = _trusted_read(
        CURRENT_PREDICATE_PRODUCER_MANIFEST_PATH,
        expected_mode=CURRENT_PREDICATE_RECORD_MODE,
        expected_uid=CURRENT_PREDICATE_OWNER_UID,
        expected_gid=CURRENT_PREDICATE_OWNER_GID,
        max_bytes=MAX_VEXP_CURRENT_PREDICATE_BYTES,
        reason_prefix="vexp_current_predicate_producer_manifest",
    )
    producer_manifest = _decode_guard_json(
        producer_manifest_raw,
        reason="vexp_current_predicate_producer_manifest_invalid",
    )
    if (
        set(producer_manifest) != CURRENT_PREDICATE_PRODUCER_MANIFEST_KEYS
        or producer_manifest.get("contract_name")
        != VEXP_CURRENT_PREDICATE_PRODUCER_MANIFEST_CONTRACT_NAME
        or producer_manifest.get("version")
        != VEXP_CURRENT_PREDICATE_PRODUCER_MANIFEST_VERSION
        or producer_manifest.get("status") != "reviewed"
        or producer_manifest.get("producer_path")
        != str(CURRENT_PREDICATE_PRODUCER_PATH)
        or producer_manifest_raw != _canonical_record_bytes(producer_manifest)
    ):
        raise PermitError("vexp_current_predicate_producer_manifest_invalid")
    root_predicate_producer_sha256 = _require_sha256(
        producer_manifest.get("producer_sha256"),
        reason="vexp_current_predicate_producer_manifest_invalid",
    )
    (
        measured_root_predicate_producer_sha256,
        root_predicate_producer_identity,
    ) = _measure_trusted_root_producer(
        CURRENT_PREDICATE_PRODUCER_PATH,
        expected_sha256=root_predicate_producer_sha256,
        reason_prefix="vexp_current_predicate_producer",
    )
    if measured_root_predicate_producer_sha256 != root_predicate_producer_sha256:
        raise PermitError("vexp_current_predicate_producer_sha256_mismatch")
    implementation = dict(
        dict(certificate.get("source_attestations") or {}).get("implementation")
        or {}
    )
    sentinel_executable = implementation.get("sentinel_executable")
    sentinel_producer_sha256 = (
        sentinel_executable.get("sha256")
        if isinstance(sentinel_executable, dict)
        else None
    )
    sentinel_producer_sha256 = _require_sha256(
        sentinel_producer_sha256,
        reason="vexp_current_predicate_producer_invalid",
    )
    state_updated_at = _parse_utc_timestamp(state.get("updated_at"), reason=reason)
    boot_id = _current_boot_id()
    current_monotonic_ns = _monotonic_ns()
    predicate_contract_sha256 = _require_sha256(
        state.get("predicate_contract_sha256"), reason=reason
    )
    qualification_certificate_sha256 = _require_sha256(
        qualification_certificate.get("sha256"), reason=reason
    )
    terminal_identity_sha256 = _terminal_identity_sha256(state)
    previous_observed_at: datetime | None = None
    previous_recorded_at: datetime | None = None
    previous_monotonic_ns: int | None = None
    for record_index, (history, history_sha256) in enumerate(
        zip(chain, chain_sha256, strict=True), start=1
    ):
        history_observed_at = _parse_utc_timestamp(
            history.get("observed_at"), reason=reason
        )
        history_recorded_at = _parse_utc_timestamp(
            history.get("recorded_at"), reason=reason
        )
        history_monotonic_ns = history.get("monotonic_ns")
        expected_previous_sha256 = (
            "0" * 64 if record_index == 1 else chain_sha256[record_index - 2]
        )
        _require_sha256(history.get("sentinel_state_sha256"), reason=reason)
        if (
            set(history) != CURRENT_PREDICATE_RECORD_KEYS
            or history.get("contract_name")
            != VEXP_CURRENT_PREDICATE_CONTRACT_NAME
            or history.get("version") != VEXP_CURRENT_PREDICATE_VERSION
            or history.get("status") != "positive"
            or history.get("epoch_started_ms") != epoch_started_ms
            or history.get("generation") != record_index
            or history.get("previous_record_sha256")
            != expected_previous_sha256
            or history.get("sentinel_state_path") != str(state_path)
            or history.get("sentinel_state_owner_uid") != state_owner_uid
            or history.get("terminal_identity_sha256")
            != terminal_identity_sha256
            or history.get("qualification_certificate_sha256")
            != qualification_certificate_sha256
            or history.get("predicate_contract_sha256")
            != predicate_contract_sha256
            or history.get("current_resources_healthy") is not True
            or history.get("certification_blockers") != []
            or history.get("certification_deferments") != []
            or history.get("sentinel_producer_sha256")
            != sentinel_producer_sha256
            or history.get("root_predicate_producer_sha256")
            != root_predicate_producer_sha256
            or history.get("boot_id") != boot_id
            or certificate.get("qualification_boot_id") != boot_id
            or type(history_monotonic_ns) is not int
            or history_monotonic_ns <= 0
            or history_monotonic_ns > current_monotonic_ns
            or history_observed_at > history_recorded_at
            or history_observed_at > now + MAX_STATE_FUTURE_SKEW
            or history_recorded_at > now + MAX_STATE_FUTURE_SKEW
            or (
                previous_observed_at is not None
                and history_observed_at < previous_observed_at
            )
            or (
                previous_recorded_at is not None
                and history_recorded_at < previous_recorded_at
            )
            or (
                previous_monotonic_ns is not None
                and history_monotonic_ns <= previous_monotonic_ns
            )
        ):
            raise PermitError("vexp_current_predicate_generation_chain_invalid")
        previous_observed_at = history_observed_at
        previous_recorded_at = history_recorded_at
        previous_monotonic_ns = history_monotonic_ns
    observed_at = previous_observed_at
    recorded_at = previous_recorded_at
    record_monotonic_ns = previous_monotonic_ns
    if (
        observed_at != state_updated_at
        or recorded_at is None
        or now - recorded_at > MAX_STATE_AGE
        or record_monotonic_ns is None
        or current_monotonic_ns - record_monotonic_ns
        > int(MAX_STATE_AGE.total_seconds() * 1_000_000_000)
        or record.get("sentinel_state_sha256") != state_sha256
        or state.get("current_resources_healthy") is not True
        or state.get("certification_blockers") != []
        or state.get("certification_deferments") != []
    ):
        raise PermitError(reason)
    final_pointer_raw, _final_pointer_metadata = _trusted_read(
        CURRENT_PREDICATE_POINTER_PATH,
        expected_mode=CURRENT_PREDICATE_RECORD_MODE,
        expected_uid=CURRENT_PREDICATE_OWNER_UID,
        expected_gid=CURRENT_PREDICATE_OWNER_GID,
        max_bytes=MAX_VEXP_CURRENT_PREDICATE_BYTES,
        reason_prefix="vexp_current_predicate_pointer",
    )
    final_generation_paths = _current_predicate_generation_paths(
        epoch_started_ms=epoch_started_ms,
        generation=generation,
    )
    final_chain_raw: list[bytes] = []
    for history_path in final_generation_paths:
        history_raw, _history_metadata = _trusted_read(
            history_path,
            expected_mode=CURRENT_PREDICATE_RECORD_MODE,
            expected_uid=CURRENT_PREDICATE_OWNER_UID,
            expected_gid=CURRENT_PREDICATE_OWNER_GID,
            max_bytes=MAX_VEXP_CURRENT_PREDICATE_BYTES,
            reason_prefix="vexp_current_predicate_history_record",
        )
        final_chain_raw.append(history_raw)
    final_root_metadata = _validate_trusted_directory(
        CURRENT_PREDICATE_ROOT,
        expected_mode=CURRENT_PREDICATE_DIRECTORY_MODE,
        expected_uid=CURRENT_PREDICATE_OWNER_UID,
        expected_gid=CURRENT_PREDICATE_OWNER_GID,
        reason="vexp_current_predicate_root_untrusted",
    )
    final_records_metadata = _validate_trusted_directory(
        CURRENT_PREDICATE_RECORD_DIRECTORY,
        expected_mode=CURRENT_PREDICATE_DIRECTORY_MODE,
        expected_uid=CURRENT_PREDICATE_OWNER_UID,
        expected_gid=CURRENT_PREDICATE_OWNER_GID,
        reason="vexp_current_predicate_directory_untrusted",
    )
    final_producer_manifest_raw, _final_producer_manifest_metadata = _trusted_read(
        CURRENT_PREDICATE_PRODUCER_MANIFEST_PATH,
        expected_mode=CURRENT_PREDICATE_RECORD_MODE,
        expected_uid=CURRENT_PREDICATE_OWNER_UID,
        expected_gid=CURRENT_PREDICATE_OWNER_GID,
        max_bytes=MAX_VEXP_CURRENT_PREDICATE_BYTES,
        reason_prefix="vexp_current_predicate_producer_manifest",
    )
    (
        final_root_predicate_producer_sha256,
        final_root_predicate_producer_identity,
    ) = _measure_trusted_root_producer(
        CURRENT_PREDICATE_PRODUCER_PATH,
        expected_sha256=root_predicate_producer_sha256,
        reason_prefix="vexp_current_predicate_producer",
    )
    if (
        final_pointer_raw != pointer_raw
        or final_generation_paths != generation_paths
        or final_chain_raw != chain_raw
        or final_producer_manifest_raw != producer_manifest_raw
        or final_root_predicate_producer_sha256
        != measured_root_predicate_producer_sha256
        or final_root_predicate_producer_identity
        != root_predicate_producer_identity
        or _trusted_file_identity(final_root_metadata)
        != _trusted_file_identity(root_metadata)
        or _trusted_file_identity(final_records_metadata)
        != _trusted_file_identity(records_metadata)
    ):
        raise PermitError("vexp_current_predicate_changed_during_read")
    return {
        "contract_name": VEXP_CURRENT_PREDICATE_CONTRACT_NAME,
        "version": VEXP_CURRENT_PREDICATE_VERSION,
        "status": "positive",
        "epoch_started_ms": epoch_started_ms,
        "generation": generation,
        "record_sha256": record_sha256,
        "boot_id": boot_id,
        "monotonic_ns": record_monotonic_ns,
        "sentinel_producer_sha256": sentinel_producer_sha256,
        "root_predicate_producer_sha256": root_predicate_producer_sha256,
    }


def _read_recovery_manifest(
    *, reviewed_revision: str
) -> tuple[dict[str, Any], str]:
    reason = "vexp_recovery_manifest_invalid"
    if (
        not RECOVERY_MANIFEST_ROOT.is_absolute()
        or not RECOVERY_MANIFEST_PATH.is_absolute()
        or RECOVERY_MANIFEST_PATH.parent != RECOVERY_MANIFEST_ROOT
        or not GIT_COMMIT_PATTERN.fullmatch(reviewed_revision)
    ):
        raise PermitError(reason)
    root_metadata = _validate_trusted_directory(
        RECOVERY_MANIFEST_ROOT,
        expected_mode=RECOVERY_MANIFEST_DIRECTORY_MODE,
        expected_uid=RECOVERY_MANIFEST_OWNER_UID,
        expected_gid=RECOVERY_MANIFEST_OWNER_GID,
        reason="vexp_recovery_manifest_root_untrusted",
    )
    raw, _metadata = _trusted_read(
        RECOVERY_MANIFEST_PATH,
        expected_mode=RECOVERY_MANIFEST_MODE,
        expected_uid=RECOVERY_MANIFEST_OWNER_UID,
        expected_gid=RECOVERY_MANIFEST_OWNER_GID,
        max_bytes=MAX_VEXP_RECOVERY_MANIFEST_BYTES,
        reason_prefix="vexp_recovery_manifest",
    )
    final_root_metadata = _validate_trusted_directory(
        RECOVERY_MANIFEST_ROOT,
        expected_mode=RECOVERY_MANIFEST_DIRECTORY_MODE,
        expected_uid=RECOVERY_MANIFEST_OWNER_UID,
        expected_gid=RECOVERY_MANIFEST_OWNER_GID,
        reason="vexp_recovery_manifest_root_untrusted",
    )
    if _trusted_file_identity(final_root_metadata) != _trusted_file_identity(
        root_metadata
    ):
        raise PermitError("vexp_recovery_manifest_root_changed_during_read")
    manifest = _decode_guard_json(raw, reason=reason)
    if (
        set(manifest) != VEXP_RECOVERY_MANIFEST_KEYS
        or manifest.get("contract_name")
        != VEXP_RECOVERY_MANIFEST_CONTRACT_NAME
        or type(manifest.get("version")) is not int
        or manifest["version"] != VEXP_RECOVERY_MANIFEST_VERSION
        or manifest.get("status") != "reviewed"
        or type(manifest.get("qualification_schema_version")) is not int
        or manifest["qualification_schema_version"]
        != VEXP_SENTINEL_STATE_VERSION
        or manifest.get("recovery_scope") != VEXP_RECOVERY_SCOPE
        or manifest.get("reviewed_revision") != reviewed_revision
    ):
        raise PermitError(reason)
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not 0 < len(artifacts) <= 128:
        raise PermitError(reason)
    observed_paths: set[str] = set()
    for artifact in artifacts:
        if not isinstance(artifact, dict) or set(artifact) != (
            VEXP_RECOVERY_MANIFEST_ARTIFACT_KEYS
        ):
            raise PermitError(reason)
        path_value = artifact.get("path")
        if (
            not isinstance(path_value, str)
            or not path_value
            or not Path(path_value).is_absolute()
            or ".." in Path(path_value).parts
            or str(Path(path_value)) != path_value
            or path_value in observed_paths
            or not isinstance(artifact.get("sha256"), str)
            or not SHA256_PATTERN.fullmatch(artifact["sha256"])
        ):
            raise PermitError(reason)
        observed_paths.add(path_value)
    return manifest, hashlib.sha256(raw).hexdigest()


def _require_epoch_not_voided(state: Mapping[str, Any]) -> dict[str, object]:
    if not EPOCH_VOID_LEDGER_ROOT.is_absolute():
        raise PermitError("vexp_epoch_void_ledger_root_untrusted")
    try:
        root_metadata = os.stat(
            EPOCH_VOID_LEDGER_ROOT, follow_symlinks=False
        )
    except OSError as exc:
        raise PermitError("vexp_epoch_void_ledger_root_unavailable") from exc
    if (
        not stat.S_ISDIR(root_metadata.st_mode)
        or stat.S_IMODE(root_metadata.st_mode)
        != EPOCH_VOID_LEDGER_DIRECTORY_MODE
        or root_metadata.st_uid != EPOCH_VOID_LEDGER_OWNER_UID
        or root_metadata.st_gid != EPOCH_VOID_LEDGER_OWNER_GID
    ):
        raise PermitError("vexp_epoch_void_ledger_root_untrusted")
    epoch_started_ms = state.get("epoch_started_ms")
    if type(epoch_started_ms) is not int or epoch_started_ms <= 0:
        raise PermitError("vexp_sentinel_state_epoch_invalid")
    entry = EPOCH_VOID_LEDGER_ROOT / f"{epoch_started_ms}.json"
    try:
        os.stat(entry, follow_symlinks=False)
    except FileNotFoundError:
        try:
            final_root_metadata = os.stat(
                EPOCH_VOID_LEDGER_ROOT, follow_symlinks=False
            )
        except OSError as exc:
            raise PermitError(
                "vexp_epoch_void_ledger_root_changed_during_check"
            ) from exc
        if _trusted_file_identity(
            final_root_metadata
        ) != _trusted_file_identity(root_metadata):
            raise PermitError(
                "vexp_epoch_void_ledger_root_changed_during_check"
            )
        return {
            "root": str(EPOCH_VOID_LEDGER_ROOT),
            "entry": str(entry),
            "entry_present": False,
            "root_trusted": True,
        }
    except OSError as exc:
        raise PermitError("vexp_epoch_void_ledger_entry_untrusted") from exc
    _trusted_read(
        entry,
        expected_mode=EPOCH_VOID_LEDGER_ENTRY_MODE,
        expected_uid=EPOCH_VOID_LEDGER_OWNER_UID,
        expected_gid=EPOCH_VOID_LEDGER_OWNER_GID,
        max_bytes=MAX_VEXP_EPOCH_VOID_LEDGER_ENTRY_BYTES,
        reason_prefix="vexp_epoch_void_ledger_entry",
    )
    raise PermitError("vexp_qualification_epoch_voided")


def _read_state_with_sha256(
    path: Path, *, owner_uid: int
) -> tuple[dict[str, Any], str]:
    raw, _metadata = _trusted_read(
        path,
        expected_mode=STATE_MODE,
        expected_uid=owner_uid,
        expected_gid=None,
        max_bytes=MAX_VEXP_SENTINEL_STATE_BYTES,
        reason_prefix="vexp_sentinel_state",
    )
    payload = _decode_guard_json(raw, reason="vexp_sentinel_state_json_invalid")
    if (
        type(payload.get("version")) is not int
        or payload["version"] != VEXP_SENTINEL_STATE_VERSION
    ):
        raise PermitError("vexp_sentinel_state_version_invalid")
    if (
        type(payload.get("epoch_started_ms")) is not int
        or payload["epoch_started_ms"] <= 0
    ):
        raise PermitError("vexp_sentinel_state_epoch_invalid")
    epoch_started_at = _parse_utc_timestamp(
        payload.get("epoch_started_at"), reason="vexp_sentinel_state_epoch_invalid"
    )
    if (
        epoch_started_at.microsecond % 1_000 != 0
        or _datetime_epoch_ms(epoch_started_at) != payload["epoch_started_ms"]
    ):
        raise PermitError("vexp_sentinel_state_epoch_invalid")
    return payload, hashlib.sha256(raw).hexdigest()


def _read_state(path: Path, *, owner_uid: int) -> dict[str, Any]:
    payload, _sha256 = _read_state_with_sha256(path, owner_uid=owner_uid)
    return payload


def _validate_terminal_state(state: Mapping[str, Any], *, now: datetime) -> datetime:
    now = _require_utc_clock(now)
    updated_at = _parse_utc_timestamp(
        state.get("updated_at"), reason="vexp_sentinel_updated_at_invalid"
    )
    if updated_at > now + MAX_STATE_FUTURE_SKEW:
        raise PermitError("vexp_sentinel_updated_at_future")
    if now - updated_at > MAX_STATE_AGE:
        raise PermitError("vexp_sentinel_updated_at_stale")
    if state.get("qualification_phase") != "qualified":
        raise PermitError("vexp_sentinel_state_not_terminal")
    qualified_at = _parse_utc_timestamp(
        state.get("qualified_at"), reason="vexp_sentinel_qualified_at_invalid"
    )
    epoch_started_at = _parse_utc_timestamp(
        state.get("epoch_started_at"), reason="vexp_sentinel_state_epoch_invalid"
    )
    earliest_completion_at = _parse_utc_timestamp(
        state.get("qualification_earliest_completion_at"),
        reason="vexp_sentinel_earliest_completion_invalid",
    )
    try:
        qualification_floor = epoch_started_at + timedelta(days=7)
    except OverflowError as exc:
        raise PermitError("vexp_sentinel_qualification_time_invalid") from exc
    if earliest_completion_at < qualification_floor:
        raise PermitError("vexp_sentinel_earliest_completion_invalid")
    required_completion_at = max(
        MINIMUM_VEXP_QUALIFICATION_AT,
        qualification_floor,
        earliest_completion_at,
    )
    if qualified_at < required_completion_at:
        raise PermitError("vexp_sentinel_qualification_before_minimum")
    if qualified_at > now or now < required_completion_at:
        raise PermitError("vexp_sentinel_qualification_not_elapsed")
    if state.get("current_resources_healthy") is not True:
        raise PermitError("vexp_sentinel_resources_not_healthy")
    if "certification_blockers" not in state:
        raise PermitError("vexp_sentinel_certification_blockers_missing")
    if (
        type(state["certification_blockers"]) is not list
        or state["certification_blockers"] != []
    ):
        raise PermitError("vexp_sentinel_certification_blockers_present")
    if state.get("certification_deferments") != []:
        raise PermitError("vexp_sentinel_certification_deferments_present")
    return qualified_at


def _permit_contract(permit_mode: str) -> tuple[str, int, tuple[str, ...]]:
    if permit_mode == API_PERMIT_MODE:
        return (
            VEXP_MUTATION_PERMIT_CONTRACT_NAME,
            VEXP_MUTATION_PERMIT_VERSION,
            VEXP_MUTATION_BOUNDARIES,
        )
    if permit_mode == JOINT_PERMIT_MODE:
        return (
            JOINT_VEXP_MUTATION_PERMIT_CONTRACT_NAME,
            JOINT_VEXP_MUTATION_PERMIT_VERSION,
            JOINT_VEXP_MUTATION_BOUNDARIES,
        )
    if permit_mode == CANDIDATE_PERMIT_MODE:
        return (
            CANDIDATE_VEXP_MUTATION_PERMIT_CONTRACT_NAME,
            CANDIDATE_VEXP_MUTATION_PERMIT_VERSION,
            CANDIDATE_VEXP_MUTATION_BOUNDARIES,
        )
    raise PermitError("vexp_mutation_permit_mode_invalid")


def _permit_payload(
    state: Mapping[str, Any],
    *,
    qualification_certificate: Mapping[str, str],
    now: datetime,
    ttl_seconds: int,
    permit_mode: str = API_PERMIT_MODE,
    candidate_evidence_manifest: Mapping[str, object] | None = None,
) -> dict[str, object]:
    contract_name, version, boundaries = _permit_contract(permit_mode)
    payload: dict[str, object] = {
        "contract_name": contract_name,
        "version": version,
        "status": "allow",
        **_terminal_identity(state),
        "terminal_identity_sha256": _terminal_identity_sha256(state),
        "qualification_certificate_schema": qualification_certificate["schema"],
        "qualification_certificate_sha256": qualification_certificate["sha256"],
        "qualification_certificate_identity": qualification_certificate["identity"],
        "qualification_certificate_event_hash": qualification_certificate[
            "event_hash"
        ],
        "issued_at": _format_utc_timestamp(now),
        "expires_at": _format_utc_timestamp(now + timedelta(seconds=ttl_seconds)),
        "mutation_boundaries": list(boundaries),
    }
    if permit_mode == CANDIDATE_PERMIT_MODE:
        if candidate_evidence_manifest is None:
            raise PermitError("vexp_candidate_evidence_readiness_missing")
        payload.update(
            {
                "candidate_boundary_attestor_sha256": _require_sha256(
                    candidate_evidence_manifest.get("attestor_sha256"),
                    reason="vexp_candidate_evidence_readiness_invalid",
                ),
                "candidate_evidence_producer_manifest_sha256": _require_sha256(
                    candidate_evidence_manifest.get("_manifest_sha256"),
                    reason="vexp_candidate_evidence_readiness_invalid",
                ),
            }
        )
    return payload


def _validate_permit(
    permit: Mapping[str, Any],
    *,
    now: datetime,
    require_current: bool,
    permit_mode: str = API_PERMIT_MODE,
) -> None:
    now = _require_utc_clock(now)
    contract_name, version, boundaries = _permit_contract(permit_mode)
    expected_keys = (
        CANDIDATE_VEXP_MUTATION_PERMIT_KEYS
        if permit_mode == CANDIDATE_PERMIT_MODE
        else VEXP_MUTATION_PERMIT_KEYS
    )
    permit_keys = set(permit)
    if permit_keys != expected_keys:
        if permit_keys in (
            set(VEXP_MUTATION_PERMIT_KEYS),
            set(CANDIDATE_VEXP_MUTATION_PERMIT_KEYS),
        ) and permit.get("contract_name") != contract_name:
            raise PermitError("vexp_mutation_permit_contract_invalid")
        raise PermitError("vexp_mutation_permit_schema_invalid")
    if permit.get("contract_name") != contract_name:
        raise PermitError("vexp_mutation_permit_contract_invalid")
    if type(permit.get("version")) is not int or permit["version"] != version:
        raise PermitError("vexp_mutation_permit_version_invalid")
    if permit.get("status") != "allow":
        raise PermitError("vexp_mutation_permit_not_positive")
    if permit.get("mutation_boundaries") != list(boundaries):
        raise PermitError("vexp_mutation_permit_boundaries_invalid")
    if permit_mode == CANDIDATE_PERMIT_MODE:
        _require_sha256(
            permit.get("candidate_boundary_attestor_sha256"),
            reason="vexp_candidate_evidence_readiness_invalid",
        )
        _require_sha256(
            permit.get("candidate_evidence_producer_manifest_sha256"),
            reason="vexp_candidate_evidence_readiness_invalid",
        )
    if (
        permit.get("qualification_certificate_schema")
        != VEXP_QUALIFICATION_CERTIFICATE_SCHEMA
        or not isinstance(permit.get("qualification_certificate_sha256"), str)
        or not SHA256_PATTERN.fullmatch(permit["qualification_certificate_sha256"])
        or not isinstance(permit.get("qualification_certificate_identity"), str)
        or not SHA256_IDENTITY_PATTERN.fullmatch(
            permit["qualification_certificate_identity"]
        )
        or not isinstance(
            permit.get("qualification_certificate_event_hash"), str
        )
        or not SHA256_PATTERN.fullmatch(
            permit["qualification_certificate_event_hash"]
        )
    ):
        raise PermitError("vexp_mutation_permit_certificate_binding_invalid")
    if (
        type(permit.get("epoch_started_ms")) is not int
        or permit["epoch_started_ms"] <= 0
    ):
        raise PermitError("vexp_mutation_permit_terminal_binding_invalid")
    epoch_started_at = _parse_utc_timestamp(
        permit.get("epoch_started_at"),
        reason="vexp_mutation_permit_terminal_binding_invalid",
    )
    if (
        epoch_started_at.microsecond % 1_000 != 0
        or _datetime_epoch_ms(epoch_started_at) != permit["epoch_started_ms"]
    ):
        raise PermitError("vexp_mutation_permit_terminal_binding_invalid")
    earliest_completion_at = _parse_utc_timestamp(
        permit.get("qualification_earliest_completion_at"),
        reason="vexp_mutation_permit_terminal_binding_invalid",
    )
    qualified_at = _parse_utc_timestamp(
        permit.get("qualified_at"),
        reason="vexp_mutation_permit_terminal_binding_invalid",
    )
    try:
        qualification_floor = epoch_started_at + timedelta(days=7)
    except OverflowError as exc:
        raise PermitError("vexp_mutation_permit_terminal_binding_invalid") from exc
    required_completion_at = max(
        MINIMUM_VEXP_QUALIFICATION_AT,
        qualification_floor,
        earliest_completion_at,
    )
    if (
        earliest_completion_at < qualification_floor
        or qualified_at < required_completion_at
    ):
        raise PermitError("vexp_mutation_permit_terminal_binding_invalid")
    identity = {
        "epoch_started_at": permit.get("epoch_started_at"),
        "epoch_started_ms": permit.get("epoch_started_ms"),
        "qualification_earliest_completion_at": permit.get(
            "qualification_earliest_completion_at"
        ),
        "qualified_at": permit.get("qualified_at"),
    }
    digest = permit.get("terminal_identity_sha256")
    if (
        not isinstance(digest, str)
        or not SHA256_PATTERN.fullmatch(digest)
        or digest != _terminal_identity_sha256(identity)
    ):
        raise PermitError("vexp_mutation_permit_identity_digest_invalid")
    issued_at = _parse_utc_timestamp(
        permit.get("issued_at"), reason="vexp_mutation_permit_issued_at_invalid"
    )
    expires_at = _parse_utc_timestamp(
        permit.get("expires_at"), reason="vexp_mutation_permit_expires_at_invalid"
    )
    if (
        issued_at < qualified_at
        or expires_at <= issued_at
        or expires_at - issued_at > timedelta(seconds=MAX_TTL_SECONDS)
    ):
        raise PermitError("vexp_mutation_permit_validity_invalid")
    if require_current and (now < issued_at or now >= expires_at):
        raise PermitError("vexp_mutation_permit_not_current")


def _validate_permit_certificate_binding(
    permit: Mapping[str, Any],
    qualification_certificate: Mapping[str, str],
) -> None:
    expected = {
        "qualification_certificate_schema": qualification_certificate["schema"],
        "qualification_certificate_sha256": qualification_certificate["sha256"],
        "qualification_certificate_identity": qualification_certificate["identity"],
        "qualification_certificate_event_hash": qualification_certificate[
            "event_hash"
        ],
    }
    if any(permit.get(key) != value for key, value in expected.items()):
        raise PermitError("vexp_mutation_permit_certificate_binding_mismatch")


def _read_permit_body(
    *,
    now: datetime,
    require_current: bool,
    permit_mode: str = API_PERMIT_MODE,
) -> tuple[dict[str, Any], str]:
    raw, _metadata = _trusted_read(
        PERMIT_PATH,
        expected_mode=PERMIT_MODE,
        expected_uid=ROOT_UID,
        expected_gid=ROOT_GID,
        max_bytes=MAX_VEXP_MUTATION_PERMIT_BYTES,
        reason_prefix="vexp_mutation_permit",
    )
    permit = _decode_guard_json(raw, reason="vexp_mutation_permit_json_invalid")
    _validate_permit(
        permit,
        now=now,
        require_current=require_current,
        permit_mode=permit_mode,
    )
    return permit, hashlib.sha256(raw).hexdigest()


def _permit_commit_payload(
    permit: Mapping[str, Any], *, permit_sha256: str
) -> dict[str, object]:
    return {
        "contract_name": VEXP_MUTATION_PERMIT_COMMIT_CONTRACT_NAME,
        "version": VEXP_MUTATION_PERMIT_COMMIT_VERSION,
        "status": "committed",
        "permit_sha256": permit_sha256,
        "permit_contract_name": permit.get("contract_name"),
        "permit_version": permit.get("version"),
        "epoch_started_at": permit.get("epoch_started_at"),
        "epoch_started_ms": permit.get("epoch_started_ms"),
        "terminal_identity_sha256": permit.get("terminal_identity_sha256"),
        "qualification_certificate_sha256": permit.get(
            "qualification_certificate_sha256"
        ),
        "issued_at": permit.get("issued_at"),
        "expires_at": permit.get("expires_at"),
    }


def _validate_permit_commit(
    commit: Mapping[str, Any],
    *,
    permit: Mapping[str, Any],
    permit_sha256: str,
) -> None:
    if set(commit) != VEXP_MUTATION_PERMIT_COMMIT_KEYS:
        raise PermitError("vexp_mutation_permit_commit_schema_invalid")
    if (
        commit.get("contract_name")
        != VEXP_MUTATION_PERMIT_COMMIT_CONTRACT_NAME
        or type(commit.get("version")) is not int
        or commit["version"] != VEXP_MUTATION_PERMIT_COMMIT_VERSION
        or commit.get("status") != "committed"
    ):
        raise PermitError("vexp_mutation_permit_commit_contract_invalid")
    expected = _permit_commit_payload(
        permit, permit_sha256=permit_sha256
    )
    if any(commit.get(key) != value for key, value in expected.items()):
        raise PermitError("vexp_mutation_permit_commit_binding_invalid")


def _read_committed_permit(
    *,
    now: datetime,
    require_current: bool,
    permit_mode: str = API_PERMIT_MODE,
) -> tuple[dict[str, Any], str, dict[str, Any], str]:
    initial_directory_chain = _runtime_authority_directory_chain_identity()
    commit_raw, _metadata = _trusted_read(
        PERMIT_COMMIT_PATH,
        expected_mode=PERMIT_COMMIT_MODE,
        expected_uid=ROOT_UID,
        expected_gid=ROOT_GID,
        max_bytes=MAX_VEXP_MUTATION_PERMIT_COMMIT_BYTES,
        reason_prefix="vexp_mutation_permit_commit",
    )
    permit, permit_sha256 = _read_permit_body(
        now=now,
        require_current=require_current,
        permit_mode=permit_mode,
    )
    final_commit_raw, _final_metadata = _trusted_read(
        PERMIT_COMMIT_PATH,
        expected_mode=PERMIT_COMMIT_MODE,
        expected_uid=ROOT_UID,
        expected_gid=ROOT_GID,
        max_bytes=MAX_VEXP_MUTATION_PERMIT_COMMIT_BYTES,
        reason_prefix="vexp_mutation_permit_commit",
    )
    if (
        final_commit_raw != commit_raw
        or _runtime_authority_directory_chain_identity()
        != initial_directory_chain
    ):
        raise PermitError("vexp_mutation_permit_commit_changed_during_read")
    commit = _decode_guard_json(
        commit_raw, reason="vexp_mutation_permit_commit_json_invalid"
    )
    _validate_permit_commit(
        commit, permit=permit, permit_sha256=permit_sha256
    )
    return (
        permit,
        permit_sha256,
        commit,
        hashlib.sha256(commit_raw).hexdigest(),
    )


def _read_permit(
    *,
    now: datetime,
    require_current: bool,
    permit_mode: str = API_PERMIT_MODE,
) -> tuple[dict[str, Any], str]:
    permit, permit_sha256, _commit, _commit_sha256 = (
        _read_committed_permit(
            now=now,
            require_current=require_current,
            permit_mode=permit_mode,
        )
    )
    return permit, permit_sha256


def _runtime_authority_directory_chain_identity() -> tuple[tuple[int, ...], ...]:
    authority_directory = PERMIT_PATH.parent
    authority_paths = (PERMIT_PATH, PERMIT_COMMIT_PATH, LOCK_PATH)
    trusted_parent = RUNTIME_AUTHORITY_TRUSTED_PARENT
    if (
        not trusted_parent.is_absolute()
        or ".." in trusted_parent.parts
        or any(not path.is_absolute() or ".." in path.parts for path in authority_paths)
        or any(path.parent != authority_directory for path in authority_paths)
    ):
        raise PermitError("vexp_mutation_authority_paths_invalid")
    if trusted_parent == Path("/run"):
        if authority_directory != trusted_parent / "ea":
            raise PermitError("vexp_mutation_authority_paths_invalid")
        chain = (Path("/"), trusted_parent, authority_directory)
    else:
        if authority_directory != trusted_parent / "ea":
            raise PermitError("vexp_mutation_authority_paths_invalid")
        chain = (trusted_parent, authority_directory)
    identities: list[tuple[int, ...]] = []
    for path in chain:
        try:
            metadata = os.stat(path, follow_symlinks=False)
        except OSError as exc:
            raise PermitError(
                "vexp_mutation_runtime_directory_chain_unavailable"
            ) from exc
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != RUNTIME_DIRECTORY_MODE
            or metadata.st_uid != ROOT_UID
            or metadata.st_gid != ROOT_GID
        ):
            raise PermitError("vexp_mutation_runtime_directory_chain_untrusted")
        identities.append(_trusted_directory_identity(metadata))
    return tuple(identities)


def _validate_runtime_directory(path: Path) -> None:
    if path != PERMIT_PATH.parent:
        raise PermitError("vexp_mutation_runtime_directory_untrusted")
    _runtime_authority_directory_chain_identity()


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise PermitError("vexp_mutation_runtime_directory_unreadable") from exc
    try:
        os.fsync(descriptor)
    except OSError as exc:
        raise PermitError("vexp_mutation_runtime_directory_fsync_failed") from exc
    finally:
        os.close(descriptor)


def _ensure_runtime_directory() -> Path:
    parent = PERMIT_PATH.parent
    if (
        not PERMIT_PATH.is_absolute()
        or not PERMIT_COMMIT_PATH.is_absolute()
        or not LOCK_PATH.is_absolute()
        or PERMIT_COMMIT_PATH.parent != parent
        or LOCK_PATH.parent != parent
    ):
        raise PermitError("vexp_mutation_authority_paths_invalid")
    try:
        trusted_parent_metadata = os.stat(
            RUNTIME_AUTHORITY_TRUSTED_PARENT,
            follow_symlinks=False,
        )
    except OSError as exc:
        raise PermitError("vexp_mutation_runtime_parent_unavailable") from exc
    if (
        not stat.S_ISDIR(trusted_parent_metadata.st_mode)
        or stat.S_IMODE(trusted_parent_metadata.st_mode) != RUNTIME_DIRECTORY_MODE
        or trusted_parent_metadata.st_uid != ROOT_UID
        or trusted_parent_metadata.st_gid != ROOT_GID
    ):
        raise PermitError("vexp_mutation_runtime_parent_untrusted")
    created = False
    try:
        os.mkdir(parent, RUNTIME_DIRECTORY_MODE)
        created = True
    except FileExistsError:
        pass
    except OSError as exc:
        raise PermitError("vexp_mutation_runtime_directory_unavailable") from exc
    if created:
        try:
            os.chown(parent, ROOT_UID, ROOT_GID)
            os.chmod(parent, RUNTIME_DIRECTORY_MODE)
            _fsync_directory(parent.parent)
        except OSError as exc:
            raise PermitError("vexp_mutation_runtime_directory_setup_failed") from exc
    _validate_runtime_directory(parent)
    return parent


@contextmanager
def _authority_lock(
    *, exclusive: bool, create: bool, wait: bool = False
) -> Iterator[None]:
    _require_safe_open_flags("vexp_mutation_permit_lock")
    initial_directory_chain = _runtime_authority_directory_chain_identity()
    access = os.O_RDWR if exclusive else os.O_RDONLY
    flags = access | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
    descriptor = -1
    try:
        if create:
            try:
                descriptor = os.open(
                    LOCK_PATH,
                    flags | os.O_CREAT | os.O_EXCL,
                    LOCK_MODE,
                )
                os.fchmod(descriptor, LOCK_MODE)
                os.fchown(descriptor, ROOT_UID, ROOT_GID)
                os.fsync(descriptor)
                _fsync_directory(LOCK_PATH.parent)
            except FileExistsError:
                descriptor = os.open(LOCK_PATH, flags)
        else:
            descriptor = os.open(LOCK_PATH, flags)
    except OSError as exc:
        if descriptor >= 0:
            os.close(descriptor)
        raise PermitError("vexp_mutation_permit_lock_unavailable") from exc
    locked = False
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or stat.S_IMODE(metadata.st_mode) != LOCK_MODE
            or metadata.st_uid != ROOT_UID
            or metadata.st_gid != ROOT_GID
        ):
            raise PermitError("vexp_mutation_permit_lock_untrusted")
        try:
            mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
            fcntl.flock(descriptor, mode if wait else mode | fcntl.LOCK_NB)
            locked = True
        except BlockingIOError as exc:
            raise PermitError("vexp_mutation_permit_lock_busy") from exc
        except OSError as exc:
            raise PermitError("vexp_mutation_permit_lock_unavailable") from exc
        final_metadata = os.fstat(descriptor)
        try:
            final_path_metadata = os.stat(LOCK_PATH, follow_symlinks=False)
        except OSError as exc:
            raise PermitError(
                "vexp_mutation_permit_lock_changed_during_acquire"
            ) from exc
        if _trusted_file_identity(final_metadata) != _trusted_file_identity(
            metadata
        ) or _trusted_file_identity(final_path_metadata) != _trusted_file_identity(
            metadata
        ) or _runtime_authority_directory_chain_identity() != initial_directory_chain:
            raise PermitError("vexp_mutation_permit_lock_changed_during_acquire")
        try:
            yield
        except BaseException as action_error:
            try:
                final_descriptor_metadata = os.fstat(descriptor)
                final_path_metadata = os.stat(LOCK_PATH, follow_symlinks=False)
                final_directory_chain = _runtime_authority_directory_chain_identity()
            except OSError as exc:
                raise PermitError("vexp_mutation_permit_lock_changed") from exc
            if (
                _trusted_file_identity(final_descriptor_metadata)
                != _trusted_file_identity(metadata)
                or _trusted_file_identity(final_path_metadata)
                != _trusted_file_identity(metadata)
                or final_directory_chain != initial_directory_chain
            ):
                raise PermitError("vexp_mutation_permit_lock_changed") from action_error
            raise
        else:
            final_descriptor_metadata = os.fstat(descriptor)
            final_path_metadata = os.stat(LOCK_PATH, follow_symlinks=False)
            if (
                _trusted_file_identity(final_descriptor_metadata)
                != _trusted_file_identity(metadata)
                or _trusted_file_identity(final_path_metadata)
                != _trusted_file_identity(metadata)
                or _runtime_authority_directory_chain_identity()
                != initial_directory_chain
            ):
                raise PermitError("vexp_mutation_permit_lock_changed")
    finally:
        unlock_error: OSError | None = None
        if locked:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            except OSError as exc:
                unlock_error = exc
                if exclusive:
                    _invalidate_permit_commit(required=False)
        try:
            os.close(descriptor)
        except OSError as exc:
            if unlock_error is None:
                unlock_error = exc
        if unlock_error is not None:
            raise PermitError("vexp_mutation_permit_lock_release_failed") from unlock_error


def _validate_candidate_authority_ledger() -> None:
    if (
        not CANDIDATE_AUTHORITY_LEDGER_ROOT.is_absolute()
        or CANDIDATE_AUTHORITY_ISSUANCE_DIRECTORY.parent
        != CANDIDATE_AUTHORITY_LEDGER_ROOT
        or CANDIDATE_AUTHORITY_FINALIZATION_DIRECTORY.parent
        != CANDIDATE_AUTHORITY_LEDGER_ROOT
        or CANDIDATE_AUTHORITY_OPERATION_DIRECTORY.parent
        != CANDIDATE_AUTHORITY_LEDGER_ROOT
        or CANDIDATE_AUTHORITY_PUBLICATION_DIRECTORY.parent
        != CANDIDATE_AUTHORITY_LEDGER_ROOT
        or CANDIDATE_AUTHORITY_REVOCATION_DIRECTORY.parent
        != CANDIDATE_AUTHORITY_LEDGER_ROOT
        or CANDIDATE_AUTHORITY_ISSUANCE_DIRECTORY
        == CANDIDATE_AUTHORITY_FINALIZATION_DIRECTORY
        or len(
            {
                CANDIDATE_AUTHORITY_ISSUANCE_DIRECTORY,
                CANDIDATE_AUTHORITY_FINALIZATION_DIRECTORY,
                CANDIDATE_AUTHORITY_OPERATION_DIRECTORY,
                CANDIDATE_AUTHORITY_PUBLICATION_DIRECTORY,
                CANDIDATE_AUTHORITY_REVOCATION_DIRECTORY,
            }
        )
        != 5
    ):
        raise PermitError("vexp_candidate_authority_ledger_paths_invalid")
    _validate_trusted_storage_chain(
        CANDIDATE_AUTHORITY_LEDGER_ROOT,
        reason="vexp_candidate_authority_ledger_chain_untrusted",
    )
    for path in (
        CANDIDATE_AUTHORITY_LEDGER_ROOT,
        CANDIDATE_AUTHORITY_ISSUANCE_DIRECTORY,
        CANDIDATE_AUTHORITY_FINALIZATION_DIRECTORY,
        CANDIDATE_AUTHORITY_OPERATION_DIRECTORY,
        CANDIDATE_AUTHORITY_PUBLICATION_DIRECTORY,
        CANDIDATE_AUTHORITY_REVOCATION_DIRECTORY,
    ):
        _validate_trusted_directory(
            path,
            expected_mode=CANDIDATE_AUTHORITY_LEDGER_DIRECTORY_MODE,
            expected_uid=CANDIDATE_AUTHORITY_LEDGER_OWNER_UID,
            expected_gid=CANDIDATE_AUTHORITY_LEDGER_OWNER_GID,
            reason="vexp_candidate_authority_ledger_untrusted",
        )


def _candidate_authority_record_path(directory: Path, identity: str) -> Path:
    digest = _require_sha256(
        identity,
        reason="vexp_candidate_authority_record_identity_invalid",
    )
    if directory not in {
        CANDIDATE_AUTHORITY_ISSUANCE_DIRECTORY,
        CANDIDATE_AUTHORITY_FINALIZATION_DIRECTORY,
    }:
        raise PermitError("vexp_candidate_authority_record_directory_invalid")
    return directory / f"{digest}.json"


def _write_candidate_authority_staging(path: Path, encoded: bytes) -> None:
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | os.O_CLOEXEC
        | os.O_NOFOLLOW
        | os.O_NONBLOCK
    )
    descriptor = -1
    completed = False
    try:
        descriptor = os.open(path, flags, 0o600)
        os.fchmod(descriptor, CANDIDATE_AUTHORITY_RECORD_MODE)
        os.fchown(
            descriptor,
            CANDIDATE_AUTHORITY_LEDGER_OWNER_UID,
            CANDIDATE_AUTHORITY_LEDGER_OWNER_GID,
        )
        written = 0
        while written < len(encoded):
            count = os.write(descriptor, encoded[written:])
            if count <= 0:
                raise PermitError("vexp_candidate_authority_record_write_failed")
            written += count
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        observed, _metadata = _trusted_read(
            path,
            expected_mode=CANDIDATE_AUTHORITY_RECORD_MODE,
            expected_uid=CANDIDATE_AUTHORITY_LEDGER_OWNER_UID,
            expected_gid=CANDIDATE_AUTHORITY_LEDGER_OWNER_GID,
            max_bytes=MAX_VEXP_CANDIDATE_AUTHORITY_RECORD_BYTES,
            reason_prefix="vexp_candidate_authority_record_staging",
        )
        if observed != encoded:
            raise PermitError("vexp_candidate_authority_record_staging_mismatch")
        completed = True
    except PermitError:
        raise
    except OSError as exc:
        raise PermitError("vexp_candidate_authority_record_write_failed") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if not completed:
            try:
                os.unlink(path)
            except OSError:
                pass


def _atomic_publish_candidate_authority_record(
    path: Path,
    payload: Mapping[str, Any],
) -> tuple[str, bool]:
    _validate_candidate_authority_ledger()
    if path.parent not in {
        CANDIDATE_AUTHORITY_ISSUANCE_DIRECTORY,
        CANDIDATE_AUTHORITY_FINALIZATION_DIRECTORY,
    }:
        raise PermitError("vexp_candidate_authority_record_path_invalid")
    encoded = _canonical_record_bytes(payload)
    if not 0 < len(encoded) <= MAX_VEXP_CANDIDATE_AUTHORITY_RECORD_BYTES:
        raise PermitError("vexp_candidate_authority_record_size_invalid")
    temporary = path.with_name(
        f".{path.name}.tmp.{os.getpid()}.{secrets.token_hex(8)}"
    )
    published = False
    try:
        _write_candidate_authority_staging(temporary, encoded)
        try:
            _rename_noreplace(temporary, path)
            published = True
        except FileExistsError:
            existing, _metadata = _trusted_read(
                path,
                expected_mode=CANDIDATE_AUTHORITY_RECORD_MODE,
                expected_uid=CANDIDATE_AUTHORITY_LEDGER_OWNER_UID,
                expected_gid=CANDIDATE_AUTHORITY_LEDGER_OWNER_GID,
                max_bytes=MAX_VEXP_CANDIDATE_AUTHORITY_RECORD_BYTES,
                reason_prefix="vexp_candidate_authority_record",
            )
            if existing != encoded:
                raise PermitError("vexp_candidate_authority_record_conflict")
            os.unlink(temporary)
        except PermitError as exc:
            raise PermitError(
                "vexp_candidate_authority_record_noreplace_unavailable"
            ) from exc
        _fsync_directory(path.parent)
        final_raw, _metadata = _trusted_read(
            path,
            expected_mode=CANDIDATE_AUTHORITY_RECORD_MODE,
            expected_uid=CANDIDATE_AUTHORITY_LEDGER_OWNER_UID,
            expected_gid=CANDIDATE_AUTHORITY_LEDGER_OWNER_GID,
            max_bytes=MAX_VEXP_CANDIDATE_AUTHORITY_RECORD_BYTES,
            reason_prefix="vexp_candidate_authority_record",
        )
        if final_raw != encoded:
            raise PermitError("vexp_candidate_authority_record_postwrite_mismatch")
        return hashlib.sha256(final_raw).hexdigest(), published
    except OSError as exc:
        raise PermitError("vexp_candidate_authority_record_publish_failed") from exc
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        except OSError:
            pass


def _validate_candidate_epoch_void_evidence(
    value: object,
    *,
    epoch_started_ms: int,
) -> dict[str, object]:
    expected_entry = EPOCH_VOID_LEDGER_ROOT / f"{epoch_started_ms}.json"
    if (
        not isinstance(value, dict)
        or set(value) != {"root", "entry", "entry_present", "root_trusted"}
        or value.get("root") != str(EPOCH_VOID_LEDGER_ROOT)
        or value.get("entry") != str(expected_entry)
        or value.get("entry_present") is not False
        or value.get("root_trusted") is not True
    ):
        raise PermitError("vexp_candidate_issuance_void_evidence_invalid")
    return dict(value)


def _candidate_issuance_payload(
    *,
    permit: Mapping[str, Any],
    permit_sha256: str,
    permit_commit: Mapping[str, Any],
    permit_commit_sha256: str,
    state_path: Path,
    state_owner_uid: int,
    epoch_void_ledger: Mapping[str, Any],
    current_predicate: Mapping[str, Any],
    recorded_at: datetime,
) -> dict[str, object]:
    return {
        "contract_name": VEXP_CANDIDATE_PERMIT_ISSUANCE_CONTRACT_NAME,
        "version": VEXP_CANDIDATE_PERMIT_ISSUANCE_VERSION,
        "status": "issued",
        "recorded_at": _format_utc_timestamp(recorded_at),
        "sentinel_state_path": str(state_path),
        "sentinel_state_owner_uid": state_owner_uid,
        "permit_mode": CANDIDATE_PERMIT_MODE,
        "permit": dict(permit),
        "permit_sha256": permit_sha256,
        "permit_commit": dict(permit_commit),
        "permit_commit_sha256": permit_commit_sha256,
        "epoch_void_ledger": dict(epoch_void_ledger),
        "current_predicate": dict(current_predicate),
    }


def _validate_candidate_issuance_record(
    value: object,
    *,
    expected_permit_sha256: str | None = None,
) -> dict[str, Any]:
    reason = "vexp_candidate_issuance_record_invalid"
    if not isinstance(value, dict) or set(value) != CANDIDATE_PERMIT_ISSUANCE_KEYS:
        raise PermitError(reason)
    permit = value.get("permit")
    permit_commit = value.get("permit_commit")
    permit_sha256 = _require_sha256(value.get("permit_sha256"), reason=reason)
    permit_commit_sha256 = _require_sha256(
        value.get("permit_commit_sha256"), reason=reason
    )
    state_path = Path(str(value.get("sentinel_state_path") or ""))
    state_owner_uid = value.get("sentinel_state_owner_uid")
    if (
        value.get("contract_name")
        != VEXP_CANDIDATE_PERMIT_ISSUANCE_CONTRACT_NAME
        or value.get("version") != VEXP_CANDIDATE_PERMIT_ISSUANCE_VERSION
        or value.get("status") != "issued"
        or value.get("permit_mode") != CANDIDATE_PERMIT_MODE
        or not isinstance(permit, dict)
        or not isinstance(permit_commit, dict)
        or type(state_owner_uid) is not int
        or state_owner_uid < 0
        or not state_path.is_absolute()
        or state_path != _canonical_sentinel_state_path(state_owner_uid)
        or (expected_permit_sha256 is not None and permit_sha256 != expected_permit_sha256)
    ):
        raise PermitError(reason)
    issued_at = _parse_utc_timestamp(
        permit.get("issued_at"), reason=reason
    )
    recorded_at = _parse_utc_timestamp(value.get("recorded_at"), reason=reason)
    expires_at = _parse_utc_timestamp(permit.get("expires_at"), reason=reason)
    if not issued_at <= recorded_at < expires_at:
        raise PermitError(reason)
    _validate_permit(
        permit,
        now=issued_at,
        require_current=False,
        permit_mode=CANDIDATE_PERMIT_MODE,
    )
    if (
        hashlib.sha256(_canonical_record_bytes(permit)).hexdigest()
        != permit_sha256
    ):
        raise PermitError(reason)
    _validate_permit_commit(
        permit_commit,
        permit=permit,
        permit_sha256=permit_sha256,
    )
    if (
        hashlib.sha256(_canonical_record_bytes(permit_commit)).hexdigest()
        != permit_commit_sha256
    ):
        raise PermitError(reason)
    _validate_candidate_epoch_void_evidence(
        value.get("epoch_void_ledger"),
        epoch_started_ms=int(permit["epoch_started_ms"]),
    )
    predicate = value.get("current_predicate")
    if (
        not isinstance(predicate, dict)
        or set(predicate)
        != {
            "contract_name",
            "version",
            "status",
            "epoch_started_ms",
            "generation",
            "record_sha256",
            "boot_id",
            "monotonic_ns",
            "sentinel_producer_sha256",
            "root_predicate_producer_sha256",
        }
        or predicate.get("contract_name") != VEXP_CURRENT_PREDICATE_CONTRACT_NAME
        or predicate.get("version") != VEXP_CURRENT_PREDICATE_VERSION
        or predicate.get("status") != "positive"
        or predicate.get("epoch_started_ms") != permit.get("epoch_started_ms")
        or type(predicate.get("generation")) is not int
        or predicate["generation"] <= 0
        or type(predicate.get("monotonic_ns")) is not int
        or predicate["monotonic_ns"] <= 0
        or BOOT_ID_PATTERN.fullmatch(str(predicate.get("boot_id") or "")) is None
    ):
        raise PermitError(reason)
    for name in (
        "record_sha256",
        "sentinel_producer_sha256",
        "root_predicate_producer_sha256",
    ):
        _require_sha256(predicate.get(name), reason=reason)
    return dict(value)


def _publish_candidate_issuance_record(
    *,
    permit: Mapping[str, Any],
    permit_sha256: str,
    permit_commit: Mapping[str, Any],
    permit_commit_sha256: str,
    state_path: Path,
    state_owner_uid: int,
    epoch_void_ledger: Mapping[str, Any],
    current_predicate: Mapping[str, Any],
    recorded_at: datetime,
) -> tuple[dict[str, Any], str, bool]:
    payload = _candidate_issuance_payload(
        permit=permit,
        permit_sha256=permit_sha256,
        permit_commit=permit_commit,
        permit_commit_sha256=permit_commit_sha256,
        state_path=state_path,
        state_owner_uid=state_owner_uid,
        epoch_void_ledger=epoch_void_ledger,
        current_predicate=current_predicate,
        recorded_at=recorded_at,
    )
    validated = _validate_candidate_issuance_record(
        payload,
        expected_permit_sha256=permit_sha256,
    )
    path = _candidate_authority_record_path(
        CANDIDATE_AUTHORITY_ISSUANCE_DIRECTORY,
        permit_sha256,
    )
    record_sha256, created = _atomic_publish_candidate_authority_record(
        path,
        validated,
    )
    return validated, record_sha256, created


def _read_candidate_issuance_record(
    permit_sha256: str,
) -> tuple[dict[str, Any], str]:
    _validate_candidate_authority_ledger()
    path = _candidate_authority_record_path(
        CANDIDATE_AUTHORITY_ISSUANCE_DIRECTORY,
        permit_sha256,
    )
    raw, _metadata = _trusted_read(
        path,
        expected_mode=CANDIDATE_AUTHORITY_RECORD_MODE,
        expected_uid=CANDIDATE_AUTHORITY_LEDGER_OWNER_UID,
        expected_gid=CANDIDATE_AUTHORITY_LEDGER_OWNER_GID,
        max_bytes=MAX_VEXP_CANDIDATE_AUTHORITY_RECORD_BYTES,
        reason_prefix="vexp_candidate_issuance_record",
    )
    payload = _decode_guard_json(
        raw,
        reason="vexp_candidate_issuance_record_invalid",
    )
    validated = _validate_candidate_issuance_record(
        payload,
        expected_permit_sha256=permit_sha256,
    )
    if raw != _canonical_record_bytes(validated):
        raise PermitError("vexp_candidate_issuance_record_noncanonical")
    return validated, hashlib.sha256(raw).hexdigest()


def _read_candidate_operator_receipt(
    path: Path,
    *,
    owner_uid: int,
    maximum_bytes: int,
    expected_sha256: str | None,
    reason_prefix: str,
) -> tuple[Path, dict[str, Any], bytes, str]:
    candidate = Path(path).expanduser()
    absolute = Path(os.path.abspath(os.fspath(candidate)))
    if not candidate.is_absolute() or absolute != candidate:
        raise PermitError(f"{reason_prefix}_path_invalid")
    try:
        resolved = absolute.resolve(strict=True)
    except OSError as exc:
        raise PermitError(f"{reason_prefix}_unavailable") from exc
    if resolved != absolute or absolute.is_symlink():
        raise PermitError(f"{reason_prefix}_path_invalid")
    raw, _metadata = _trusted_read(
        absolute,
        expected_mode=0o600,
        expected_uid=owner_uid,
        expected_gid=None,
        max_bytes=maximum_bytes,
        reason_prefix=reason_prefix,
    )
    digest = hashlib.sha256(raw).hexdigest()
    if expected_sha256 is not None:
        expected = _require_sha256(
            expected_sha256,
            reason=f"{reason_prefix}_sha256_invalid",
        )
        if digest != expected:
            raise PermitError(f"{reason_prefix}_sha256_mismatch")
    payload = _decode_guard_json(raw, reason=f"{reason_prefix}_json_invalid")
    return absolute, payload, raw, digest


def _candidate_authority_tuple_from_issuance(
    issuance: Mapping[str, Any],
) -> dict[str, object]:
    permit = issuance.get("permit")
    permit_commit = issuance.get("permit_commit")
    if not isinstance(permit, dict) or not isinstance(permit_commit, dict):
        raise PermitError("vexp_candidate_issuance_record_invalid")
    return {
        "contract_name": permit["contract_name"],
        "version": permit["version"],
        "epoch_started_ms": permit["epoch_started_ms"],
        "qualified_at": permit["qualified_at"],
        "terminal_identity_sha256": permit["terminal_identity_sha256"],
        "qualification_certificate_schema": permit[
            "qualification_certificate_schema"
        ],
        "qualification_certificate_sha256": permit[
            "qualification_certificate_sha256"
        ],
        "qualification_certificate_identity": permit[
            "qualification_certificate_identity"
        ],
        "qualification_certificate_event_hash": permit[
            "qualification_certificate_event_hash"
        ],
        "permit_sha256": issuance["permit_sha256"],
        "permit_commit": {
            "contract_name": permit_commit["contract_name"],
            "version": permit_commit["version"],
            "status": permit_commit["status"],
            "sha256": issuance["permit_commit_sha256"],
        },
        "epoch_void_ledger": dict(issuance["epoch_void_ledger"]),
        "permit_issued_at": permit["issued_at"],
        "permit_expires_at": permit["expires_at"],
    }


def _validated_candidate_operation_resource(value: object) -> dict[str, object]:
    reason = "vexp_candidate_operation_resource_invalid"
    if not isinstance(value, dict) or set(value) != CANDIDATE_OPERATION_RESOURCE_KEYS:
        raise PermitError(reason)
    argv = value.get("argv")
    target = value.get("target")
    if (
        not isinstance(argv, list)
        or not 0 < len(argv) <= 256
        or any(
            not isinstance(argument, str)
            or not argument
            or len(argument) > 16 * 1024
            or "\x00" in argument
            for argument in argv
        )
        or not isinstance(target, str)
        or not target
        or len(target) > 16 * 1024
        or "\x00" in target
    ):
        raise PermitError(reason)
    normalized = {"argv": list(argv), "target": target}
    # Force JSON representability and the exact canonical byte contract before
    # the descriptor is ever used as root-attested evidence.
    encoded = _canonical_record_bytes(normalized)
    if not 0 < len(encoded) <= MAX_VEXP_CANDIDATE_BOUNDARY_EVENT_BYTES:
        raise PermitError(reason)
    return normalized


def _validated_candidate_row_predicate(
    value: object,
    *,
    issuance: Mapping[str, Any],
    minimum_generation: int,
    minimum_monotonic_ns: int,
) -> dict[str, object]:
    reason = "vexp_candidate_runtime_predicate_binding_invalid"
    permit = issuance.get("permit")
    if (
        not isinstance(permit, dict)
        or not isinstance(value, dict)
        or set(value) != CURRENT_PREDICATE_EVIDENCE_KEYS
    ):
        raise PermitError(reason)
    generation = value.get("generation")
    monotonic_ns = value.get("monotonic_ns")
    if (
        value.get("contract_name") != VEXP_CURRENT_PREDICATE_CONTRACT_NAME
        or value.get("version") != VEXP_CURRENT_PREDICATE_VERSION
        or value.get("status") != "positive"
        or value.get("epoch_started_ms") != permit.get("epoch_started_ms")
        or type(generation) is not int
        or generation < minimum_generation
        or type(monotonic_ns) is not int
        or monotonic_ns < minimum_monotonic_ns
        or not isinstance(value.get("boot_id"), str)
        or len(str(value["boot_id"])) != 36
        or any(
            not isinstance(value.get(name), str)
            or len(str(value[name])) != 64
            or any(
                character not in "0123456789abcdef"
                for character in str(value[name])
            )
            for name in (
                "record_sha256",
                "sentinel_producer_sha256",
                "root_predicate_producer_sha256",
            )
        )
    ):
        raise PermitError(reason)
    return dict(value)


def _validate_candidate_runtime_authority_envelope(
    value: object,
    *,
    issuance: Mapping[str, Any],
) -> dict[str, Any]:
    reason = "vexp_candidate_runtime_authority_invalid"
    if not isinstance(value, dict) or set(value) != {
        "entry",
        "mutations",
        "finalization",
        "cleanup_requires_positive_authority",
        "retention_timer_only_authority_free_cleanup",
    }:
        raise PermitError(reason)
    entry = value.get("entry")
    mutations = value.get("mutations")
    finalization = value.get("finalization")
    if (
        not isinstance(entry, dict)
        or not isinstance(mutations, list)
        or any(not isinstance(row, dict) for row in mutations)
        or not isinstance(finalization, dict)
        or value.get("cleanup_requires_positive_authority") is not True
        or value.get("retention_timer_only_authority_free_cleanup") is not True
    ):
        raise PermitError(reason)
    operation_rows: list[dict[str, Any]] = []
    authority_rows: list[dict[str, Any]] = [dict(entry)]
    for sequence, raw_operation in enumerate(mutations, start=1):
        operation = dict(raw_operation)
        authority = operation.get("authority")
        if (
            set(operation) != CANDIDATE_RUNTIME_OPERATION_KEYS
            or operation.get("sequence") != sequence
            or operation.get("runner_acknowledged") is not True
            or not isinstance(operation.get("operation"), str)
            or not isinstance(authority, dict)
        ):
            raise PermitError(reason)
        resource = _validated_candidate_operation_resource(operation.get("resource"))
        operation["resource"] = resource
        operation["authority"] = dict(authority)
        operation_rows.append(operation)
        authority_rows.append(dict(authority))
    authority_rows.append(dict(finalization))
    expected_phases_and_boundaries = (
        [("entry", "candidate_entry")]
        + [
            ("pre_mutation", boundary)
            for boundary in CANDIDATE_VEXP_MUTATION_SEQUENCE
        ]
        + [("finalization", "candidate_receipt_publication")]
    )
    expected_tuple = _candidate_authority_tuple_from_issuance(issuance)
    if len(authority_rows) != len(expected_phases_and_boundaries):
        raise PermitError(reason)
    previous_generation = 0
    previous_monotonic_ns = 0
    for row, (phase, boundary) in zip(
        authority_rows,
        expected_phases_and_boundaries,
        strict=True,
    ):
        if (
            set(row) != CANDIDATE_AUTHORITY_EVIDENCE_KEYS
            or row.get("status") != "pass"
            or row.get("phase") != phase
            or row.get("boundary") != boundary
            or {
                key: row.get(key)
                for key in CANDIDATE_AUTHORITY_TUPLE_KEYS
            }
            != expected_tuple
        ):
            raise PermitError(reason)
        predicate = _validated_candidate_row_predicate(
            row.get("current_predicate"),
            issuance=issuance,
            minimum_generation=previous_generation,
            minimum_monotonic_ns=previous_monotonic_ns,
        )
        previous_generation = int(predicate["generation"])
        previous_monotonic_ns = int(predicate["monotonic_ns"])
    for operation, (_phase, boundary) in zip(
        operation_rows,
        expected_phases_and_boundaries[1:-1],
        strict=True,
    ):
        operation_name = str(operation["operation"])
        if operation_name not in CANDIDATE_RUNTIME_OPERATIONS_BY_BOUNDARY.get(
            boundary, frozenset()
        ):
            raise PermitError(reason)
    return {
        **dict(value),
        "entry": dict(entry),
        "mutations": operation_rows,
        "finalization": dict(finalization),
    }


def _validate_image_build_authority_envelope(
    value: object,
    *,
    image_reused: bool,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    reason = "vexp_candidate_image_build_authority_invalid"
    expected_keys = {
        "entry",
        "operations",
        "finalization",
        "operation_count",
        "operations_exact",
        "authority_basis",
        "receipt_publication",
        "receipt_publication_held_under_authority",
    }
    if not isinstance(value, dict) or set(value) != expected_keys:
        raise PermitError(reason)
    entry = value.get("entry")
    operations = value.get("operations")
    finalization = value.get("finalization")
    if (
        not isinstance(entry, dict)
        or not isinstance(operations, list)
        or any(not isinstance(row, dict) for row in operations)
        or not isinstance(finalization, dict)
        or value.get("operation_count") != len(operations)
        or value.get("operations_exact") is not True
        or value.get("receipt_publication")
        != "exclusive_hardlink_noreplace_v1"
        or value.get("receipt_publication_held_under_authority") is not True
    ):
        raise PermitError(reason)
    permit_sha256 = _require_sha256(entry.get("permit_sha256"), reason=reason)
    issuance, issuance_sha256 = _read_candidate_issuance_record(permit_sha256)
    expected_tuple = _candidate_authority_tuple_from_issuance(issuance)
    rows = [dict(entry)]
    operation_names: list[str] = []
    allowed_operations = {
        "builder_create",
        "image_build",
        "builder_prune",
        "verification_stale_cleanup",
        "verification_create",
        "verification_probe",
        "verification_cleanup",
        "image_cleanup",
    }
    for index, operation in enumerate(operations, start=1):
        if (
            set(operation) != CANDIDATE_RUNTIME_OPERATION_KEYS
            or operation.get("sequence") != index
            or operation.get("operation") not in allowed_operations
            or operation.get("runner_acknowledged") is not True
            or not isinstance(operation.get("authority"), dict)
        ):
            raise PermitError(reason)
        _validated_candidate_operation_resource(operation.get("resource"))
        operation_names.append(str(operation["operation"]))
        rows.append(dict(operation["authority"]))
    rows.append(dict(finalization))
    expected_phases_and_boundaries = (
        [("entry", "candidate_entry")]
        + [
            ("pre_mutation", "before_candidate_image_build")
            for _operation in operations
        ]
        + [("finalization", "candidate_receipt_publication")]
    )
    previous_generation = 0
    previous_monotonic_ns = 0
    for row, (phase, boundary) in zip(
        rows,
        expected_phases_and_boundaries,
        strict=True,
    ):
        if (
            set(row) != CANDIDATE_AUTHORITY_EVIDENCE_KEYS
            or row.get("status") != "pass"
            or row.get("phase") != phase
            or row.get("boundary") != boundary
            or {
                key: row.get(key)
                for key in CANDIDATE_AUTHORITY_TUPLE_KEYS
            }
            != expected_tuple
        ):
            raise PermitError(reason)
        predicate = _validated_candidate_row_predicate(
            row.get("current_predicate"),
            issuance=issuance,
            minimum_generation=previous_generation,
            minimum_monotonic_ns=previous_monotonic_ns,
        )
        previous_generation = int(predicate["generation"])
        previous_monotonic_ns = int(predicate["monotonic_ns"])
    verification_tails = (
        ["verification_create", "verification_probe", "verification_cleanup"],
        [
            "verification_stale_cleanup",
            "verification_create",
            "verification_probe",
            "verification_cleanup",
        ],
    )
    if image_reused:
        allowed_sequences = verification_tails
        expected_basis = "preexisting_image_current_authority_probe"
    else:
        allowed_sequences = tuple(
            [*prefix, *tail]
            for prefix in (
                ["image_build", "builder_prune"],
                ["builder_create", "image_build", "builder_prune"],
            )
            for tail in verification_tails
        )
        expected_basis = "new_image_build"
    if (
        operation_names not in allowed_sequences
        or value.get("authority_basis") != expected_basis
    ):
        raise PermitError(reason)
    return dict(value), issuance, issuance_sha256


def _validated_candidate_seal_inputs(
    *,
    candidate_receipt_path: Path,
    candidate_receipt_sha256: str,
    state_owner_uid: int,
    current_issuance: Mapping[str, Any],
) -> dict[str, object]:
    (
        normalized_candidate_path,
        candidate,
        _candidate_raw,
        observed_candidate_sha256,
    ) = _read_candidate_operator_receipt(
        candidate_receipt_path,
        owner_uid=state_owner_uid,
        maximum_bytes=MAX_VEXP_CANDIDATE_RUNTIME_RECEIPT_BYTES,
        expected_sha256=candidate_receipt_sha256,
        reason_prefix="vexp_candidate_runtime_receipt",
    )
    source_revision = str(candidate.get("image_source_revision") or "")
    image_tag = str(candidate.get("image") or "")
    image_id = str(candidate.get("image_id") or "")
    compose_project = str(candidate.get("compose_project") or "")
    observed_at = str(candidate.get("observed_at") or "")
    candidate_producer_sha256 = _require_sha256(
        candidate.get("producer_sha256"),
        reason="vexp_candidate_runtime_producer_invalid",
    )
    if (
        candidate.get("schema") != CANDIDATE_RUNTIME_RECEIPT_SCHEMA
        or candidate.get("status") != "pass"
        or GIT_COMMIT_PATTERN.fullmatch(source_revision) is None
        or IMAGE_TAG_PATTERN.fullmatch(image_tag) is None
        or image_tag
        not in {
            f"ea-runtime:manfred-{source_revision}",
            f"ea-runtime:memorial-{source_revision}",
        }
        or IMAGE_ID_PATTERN.fullmatch(image_id) is None
        or CANDIDATE_PROJECT_PATTERN.fullmatch(compose_project) is None
        or candidate.get("runtime_source_revision") != source_revision
        or candidate.get("runtime_authority_commit") != source_revision
    ):
        raise PermitError("vexp_candidate_runtime_receipt_invalid")
    candidate_authority = _validate_candidate_runtime_authority_envelope(
        candidate.get("vexp_candidate_mutation_authority"),
        issuance=current_issuance,
    )
    current_permit = dict(current_issuance["permit"])
    candidate_observed = _parse_utc_timestamp(
        observed_at,
        reason="vexp_candidate_runtime_receipt_observed_at_invalid",
    )
    if not (
        _parse_utc_timestamp(
            current_permit["issued_at"],
            reason="vexp_candidate_runtime_receipt_observed_at_invalid",
        )
        <= candidate_observed
        < _parse_utc_timestamp(
            current_permit["expires_at"],
            reason="vexp_candidate_runtime_receipt_observed_at_invalid",
        )
    ):
        raise PermitError("vexp_candidate_runtime_receipt_observed_at_invalid")

    binding = candidate.get("image_build_authority_binding")
    binding_keys = {
        "receipt_schema",
        "receipt_path",
        "receipt_sha256",
        "image_tag",
        "image_id",
        "runtime_source_revision",
        "producer_sha256",
        "image_reused",
        "authority",
    }
    if not isinstance(binding, dict) or set(binding) != binding_keys:
        raise PermitError("vexp_candidate_image_build_binding_invalid")
    image_receipt_path = Path(str(binding.get("receipt_path") or ""))
    image_receipt_sha256 = _require_sha256(
        binding.get("receipt_sha256"),
        reason="vexp_candidate_image_build_binding_invalid",
    )
    producer_sha256 = _require_sha256(
        binding.get("producer_sha256"),
        reason="vexp_candidate_image_build_binding_invalid",
    )
    image_reused = binding.get("image_reused")
    if (
        binding.get("receipt_schema") != CANDIDATE_IMAGE_BUILD_RECEIPT_SCHEMA
        or binding.get("image_tag") != image_tag
        or binding.get("image_id") != image_id
        or binding.get("runtime_source_revision") != source_revision
        or not isinstance(image_reused, bool)
    ):
        raise PermitError("vexp_candidate_image_build_binding_invalid")
    (
        normalized_image_path,
        image_receipt,
        _image_raw,
        observed_image_sha256,
    ) = _read_candidate_operator_receipt(
        image_receipt_path,
        owner_uid=state_owner_uid,
        maximum_bytes=MAX_VEXP_CANDIDATE_IMAGE_BUILD_RECEIPT_BYTES,
        expected_sha256=image_receipt_sha256,
        reason_prefix="vexp_candidate_image_build_receipt",
    )
    image_authority, image_issuance, image_issuance_sha256 = (
        _validate_image_build_authority_envelope(
            binding.get("authority"),
            image_reused=image_reused,
        )
    )
    if (
        image_receipt.get("schema") != CANDIDATE_IMAGE_BUILD_RECEIPT_SCHEMA
        or image_receipt.get("status") != "pass"
        or image_receipt.get("commit") != source_revision
        or image_receipt.get("runtime_source_revision") != source_revision
        or image_receipt.get("image_tag") != image_tag
        or image_receipt.get("image_id") != image_id
        or image_receipt.get("producer_sha256") != producer_sha256
        or image_receipt.get("image_reused") is not image_reused
        or image_receipt.get("image_build_authority") != image_authority
        or observed_image_sha256 != image_receipt_sha256
    ):
        raise PermitError("vexp_candidate_image_build_receipt_invalid")
    image_permit = dict(image_issuance["permit"])
    if (
        image_issuance.get("sentinel_state_path")
        != current_issuance.get("sentinel_state_path")
        or image_issuance.get("sentinel_state_owner_uid")
        != current_issuance.get("sentinel_state_owner_uid")
        or any(
            image_permit.get(name) != current_permit.get(name)
            for name in (
                "epoch_started_at",
                "epoch_started_ms",
                "qualification_earliest_completion_at",
                "qualified_at",
                "terminal_identity_sha256",
                "qualification_certificate_schema",
                "qualification_certificate_sha256",
                "qualification_certificate_identity",
                "qualification_certificate_event_hash",
            )
        )
    ):
        raise PermitError("vexp_candidate_image_build_epoch_binding_mismatch")
    image_created_at = _parse_utc_timestamp(
        image_receipt.get("created_at"),
        reason="vexp_candidate_image_build_receipt_created_at_invalid",
    )
    if not (
        _parse_utc_timestamp(
            image_permit["issued_at"],
            reason="vexp_candidate_image_build_receipt_created_at_invalid",
        )
        <= image_created_at
        < _parse_utc_timestamp(
            image_permit["expires_at"],
            reason="vexp_candidate_image_build_receipt_created_at_invalid",
        )
    ):
        raise PermitError("vexp_candidate_image_build_receipt_created_at_invalid")
    return {
        "candidate_receipt_path": str(normalized_candidate_path),
        "candidate_receipt_sha256": observed_candidate_sha256,
        "candidate_observed_at": observed_at,
        "source_revision": source_revision,
        "image_tag": image_tag,
        "image_id": image_id,
        "compose_project": compose_project,
        "candidate_producer_sha256": candidate_producer_sha256,
        "image_build_receipt_path": str(normalized_image_path),
        "image_build_receipt_sha256": image_receipt_sha256,
        "image_build_created_at": image_receipt.get("created_at"),
        "image_build_producer_sha256": producer_sha256,
        "image_reused": image_reused,
        "image_build_permit_sha256": image_issuance["permit_sha256"],
        "image_build_permit_commit_sha256": image_issuance[
            "permit_commit_sha256"
        ],
        "image_build_issuance_record_sha256": image_issuance_sha256,
        "candidate_operations": [
            {
                "boundary": str(operation["authority"]["boundary"]),
                "operation": str(operation["operation"]),
                "resource": dict(operation["resource"]),
                "resource_sha256": _canonical_json_sha256(operation["resource"]),
                "current_predicate_generation": int(
                    operation["authority"]["current_predicate"]["generation"]
                ),
                "current_predicate_record_sha256": str(
                    operation["authority"]["current_predicate"]["record_sha256"]
                ),
            }
            for operation in candidate_authority["mutations"]
        ],
        "image_build_operations": [
            {
                "boundary": "before_candidate_image_build",
                "operation": str(operation["operation"]),
                "resource": dict(operation["resource"]),
                "resource_sha256": _canonical_json_sha256(operation["resource"]),
                "current_predicate_generation": int(
                    operation["authority"]["current_predicate"]["generation"]
                ),
                "current_predicate_record_sha256": str(
                    operation["authority"]["current_predicate"]["record_sha256"]
                ),
            }
            for operation in image_authority["operations"]
        ],
        "candidate_producer_sha256": candidate_producer_sha256,
    }


def _read_candidate_evidence_producer_manifest() -> dict[str, object]:
    _validate_candidate_authority_ledger()
    raw, _metadata = _trusted_read(
        CANDIDATE_AUTHORITY_PRODUCER_MANIFEST_PATH,
        expected_mode=CANDIDATE_AUTHORITY_RECORD_MODE,
        expected_uid=CANDIDATE_AUTHORITY_LEDGER_OWNER_UID,
        expected_gid=CANDIDATE_AUTHORITY_LEDGER_OWNER_GID,
        max_bytes=MAX_VEXP_CANDIDATE_AUTHORITY_RECORD_BYTES,
        reason_prefix="vexp_candidate_evidence_producer_manifest",
    )
    payload = _decode_guard_json(
        raw, reason="vexp_candidate_evidence_producer_manifest_invalid"
    )
    allowed = payload.get("allowed_producers")
    if (
        set(payload) != CANDIDATE_EVIDENCE_PRODUCER_MANIFEST_KEYS
        or payload.get("contract_name")
        != VEXP_CANDIDATE_EVIDENCE_PRODUCER_MANIFEST_CONTRACT_NAME
        or payload.get("version")
        != VEXP_CANDIDATE_EVIDENCE_PRODUCER_MANIFEST_VERSION
        or payload.get("status") != "reviewed"
        or payload.get("attestor_path") != str(CANDIDATE_AUTHORITY_ATTESTOR_PATH)
        or not isinstance(allowed, list)
        or len(allowed) != 2
        or any(
            not isinstance(row, dict)
            or set(row) != CANDIDATE_EVIDENCE_ALLOWED_PRODUCER_KEYS
            for row in allowed
        )
        or {row.get("receipt_kind") for row in allowed}
        != {"candidate_runtime", "image_build"}
        or raw != _canonical_record_bytes(payload)
    ):
        raise PermitError("vexp_candidate_evidence_producer_manifest_invalid")
    _require_sha256(
        payload.get("attestor_sha256"),
        reason="vexp_candidate_evidence_producer_manifest_invalid",
    )
    attestor_sha256, attestor_identity = _measure_trusted_root_producer(
        CANDIDATE_AUTHORITY_ATTESTOR_PATH,
        expected_sha256=str(payload["attestor_sha256"]),
        reason_prefix="vexp_candidate_boundary_attestor",
    )
    for row in allowed:
        _require_sha256(
            row.get("producer_sha256"),
            reason="vexp_candidate_evidence_producer_manifest_invalid",
        )
    final_raw, _final_metadata = _trusted_read(
        CANDIDATE_AUTHORITY_PRODUCER_MANIFEST_PATH,
        expected_mode=CANDIDATE_AUTHORITY_RECORD_MODE,
        expected_uid=CANDIDATE_AUTHORITY_LEDGER_OWNER_UID,
        expected_gid=CANDIDATE_AUTHORITY_LEDGER_OWNER_GID,
        max_bytes=MAX_VEXP_CANDIDATE_AUTHORITY_RECORD_BYTES,
        reason_prefix="vexp_candidate_evidence_producer_manifest",
    )
    final_attestor_sha256, final_attestor_identity = _measure_trusted_root_producer(
        CANDIDATE_AUTHORITY_ATTESTOR_PATH,
        expected_sha256=attestor_sha256,
        reason_prefix="vexp_candidate_boundary_attestor",
    )
    if (
        final_raw != raw
        or final_attestor_sha256 != attestor_sha256
        or final_attestor_identity != attestor_identity
    ):
        raise PermitError("vexp_candidate_evidence_producer_changed_during_read")
    return {
        **payload,
        "_manifest_sha256": hashlib.sha256(raw).hexdigest(),
        "_attestor_identity": list(attestor_identity),
    }


def _candidate_boundary_event_path(
    *, permit_sha256: str, receipt_kind: str, sequence: int
) -> Path:
    _require_sha256(permit_sha256, reason="vexp_candidate_boundary_event_invalid")
    if receipt_kind not in {"candidate_runtime", "image_build"}:
        raise PermitError("vexp_candidate_boundary_event_invalid")
    if type(sequence) is not int or sequence <= 0:
        raise PermitError("vexp_candidate_boundary_event_invalid")
    return CANDIDATE_AUTHORITY_OPERATION_DIRECTORY / (
        f"{permit_sha256}.{receipt_kind}.{sequence:03d}.json"
    )


def _read_candidate_operation_evidence(
    *,
    issuance: Mapping[str, Any],
    receipt_kind: str,
    operations: Sequence[Mapping[str, object]],
    producer_sha256: str,
    now: datetime,
) -> dict[str, object]:
    reason = "vexp_candidate_boundary_evidence_invalid"
    now = _require_utc_clock(now)
    producer_digest = _require_sha256(producer_sha256, reason=reason)
    manifest = _read_candidate_evidence_producer_manifest()
    allowed = {
        str(row["receipt_kind"]): str(row["producer_sha256"])
        for row in manifest["allowed_producers"]
    }
    if allowed.get(receipt_kind) != producer_digest:
        raise PermitError("vexp_candidate_boundary_producer_not_reviewed")
    attestor_sha256 = _require_sha256(manifest.get("attestor_sha256"), reason=reason)
    permit = issuance.get("permit")
    if not isinstance(permit, dict):
        raise PermitError(reason)
    permit_sha256 = _require_sha256(issuance.get("permit_sha256"), reason=reason)
    permit_commit_sha256 = _require_sha256(
        issuance.get("permit_commit_sha256"), reason=reason
    )
    issuance_predicate = issuance.get("current_predicate")
    if not isinstance(issuance_predicate, dict):
        raise PermitError(reason)
    certificate_sha256 = _require_sha256(
        permit.get("qualification_certificate_sha256"), reason=reason
    )
    issued_at = _parse_utc_timestamp(permit.get("issued_at"), reason=reason)
    expires_at = _parse_utc_timestamp(permit.get("expires_at"), reason=reason)
    boot_id = _current_boot_id()
    current_monotonic_ns = _monotonic_ns()
    event_sha256s: list[str] = []
    event_nonces: set[str] = set()
    expected_names: set[str] = set()
    previous_sha256 = "0" * 64
    last_closed_monotonic_ns = 0
    last_closed_at: datetime | None = None
    previous_predicate_generation = 0
    tail_predicate_record_sha256 = ""
    for sequence, operation in enumerate(operations, start=1):
        if set(operation) != {
            "boundary",
            "operation",
            "resource",
            "resource_sha256",
            "current_predicate_generation",
            "current_predicate_record_sha256",
        }:
            raise PermitError(reason)
        resource = _validated_candidate_operation_resource(operation.get("resource"))
        expected_resource_sha256 = _canonical_json_sha256(resource)
        operation_predicate_generation = operation.get(
            "current_predicate_generation"
        )
        operation_predicate_record_sha256 = _require_sha256(
            operation.get("current_predicate_record_sha256"), reason=reason
        )
        if (
            type(operation_predicate_generation) is not int
            or operation_predicate_generation < previous_predicate_generation
            or operation.get("resource_sha256") != expected_resource_sha256
        ):
            raise PermitError(reason)
        path = _candidate_boundary_event_path(
            permit_sha256=permit_sha256,
            receipt_kind=receipt_kind,
            sequence=sequence,
        )
        expected_names.add(path.name)
        raw, _metadata = _trusted_read(
            path,
            expected_mode=CANDIDATE_AUTHORITY_RECORD_MODE,
            expected_uid=CANDIDATE_AUTHORITY_LEDGER_OWNER_UID,
            expected_gid=CANDIDATE_AUTHORITY_LEDGER_OWNER_GID,
            max_bytes=MAX_VEXP_CANDIDATE_BOUNDARY_EVENT_BYTES,
            reason_prefix="vexp_candidate_boundary_event",
        )
        payload = _decode_guard_json(raw, reason=reason)
        digest = hashlib.sha256(raw).hexdigest()
        opened_at = _parse_utc_timestamp(payload.get("opened_at"), reason=reason)
        closed_at = _parse_utc_timestamp(payload.get("closed_at"), reason=reason)
        opened_monotonic_ns = payload.get("opened_monotonic_ns")
        closed_monotonic_ns = payload.get("closed_monotonic_ns")
        deadline_monotonic_ns = payload.get("deadline_monotonic_ns")
        event_nonce = _require_sha256(payload.get("event_nonce"), reason=reason)
        if (
            set(payload) != CANDIDATE_BOUNDARY_EVENT_KEYS
            or payload.get("contract_name")
            != VEXP_CANDIDATE_BOUNDARY_EVENT_CONTRACT_NAME
            or payload.get("version") != VEXP_CANDIDATE_BOUNDARY_EVENT_VERSION
            or payload.get("status") != "succeeded"
            or payload.get("receipt_kind") != receipt_kind
            or payload.get("sequence") != sequence
            or event_nonce == "0" * 64
            or event_nonce in event_nonces
            or payload.get("permit_sha256") != permit_sha256
            or payload.get("permit_commit_sha256") != permit_commit_sha256
            or payload.get("epoch_started_ms") != permit.get("epoch_started_ms")
            or payload.get("qualification_certificate_sha256")
            != certificate_sha256
            or payload.get("current_predicate_generation")
            != operation_predicate_generation
            or payload.get("current_predicate_record_sha256")
            != operation_predicate_record_sha256
            or payload.get("boundary") != operation.get("boundary")
            or payload.get("operation") != operation.get("operation")
            or payload.get("resource_sha256") != operation.get("resource_sha256")
            or payload.get("producer_sha256") != producer_digest
            or payload.get("root_attestor_sha256") != attestor_sha256
            or payload.get("boot_id") != boot_id
            or payload.get("previous_event_sha256") != previous_sha256
            or type(opened_monotonic_ns) is not int
            or type(closed_monotonic_ns) is not int
            or type(deadline_monotonic_ns) is not int
            or not 0 < opened_monotonic_ns < closed_monotonic_ns
            <= deadline_monotonic_ns
            or deadline_monotonic_ns - opened_monotonic_ns
            > MAX_CANDIDATE_BOUNDARY_DURATION_NS
            or closed_monotonic_ns > current_monotonic_ns
            or (
                last_closed_monotonic_ns > 0
                and opened_monotonic_ns < last_closed_monotonic_ns
            )
            or not issued_at <= opened_at <= closed_at < expires_at
            or (last_closed_at is not None and opened_at < last_closed_at)
            or closed_at > now
            or raw != _canonical_record_bytes(payload)
        ):
            raise PermitError(reason)
        event_sha256s.append(digest)
        event_nonces.add(event_nonce)
        previous_sha256 = digest
        last_closed_monotonic_ns = closed_monotonic_ns
        last_closed_at = closed_at
        previous_predicate_generation = operation_predicate_generation
        tail_predicate_record_sha256 = operation_predicate_record_sha256
    prefix = f"{permit_sha256}.{receipt_kind}."
    try:
        observed_names = {
            entry.name
            for entry in os.scandir(CANDIDATE_AUTHORITY_OPERATION_DIRECTORY)
            if entry.name.startswith(prefix) and entry.name.endswith(".json")
        }
    except OSError as exc:
        raise PermitError(reason) from exc
    if observed_names != expected_names or not event_sha256s:
        raise PermitError("vexp_candidate_boundary_event_set_invalid")
    return {
        "aggregate_sha256": _canonical_json_sha256(event_sha256s),
        "tail_sha256": event_sha256s[-1],
        "last_closed_monotonic_ns": last_closed_monotonic_ns,
        "last_closed_at": _format_utc_timestamp(last_closed_at),
        "boot_id": boot_id,
        "current_predicate_generation": previous_predicate_generation,
        "current_predicate_record_sha256": tail_predicate_record_sha256,
    }


def _candidate_publication_evidence_path(
    *, permit_sha256: str, receipt_kind: str, receipt_sha256: str
) -> Path:
    _require_sha256(permit_sha256, reason="vexp_candidate_publication_invalid")
    _require_sha256(receipt_sha256, reason="vexp_candidate_publication_invalid")
    if receipt_kind not in {"candidate_runtime", "image_build"}:
        raise PermitError("vexp_candidate_publication_invalid")
    return CANDIDATE_AUTHORITY_PUBLICATION_DIRECTORY / (
        f"{permit_sha256}.{receipt_kind}.{receipt_sha256}.json"
    )


def _read_candidate_publication_evidence(
    *,
    issuance: Mapping[str, Any],
    receipt_kind: str,
    receipt_path: str,
    receipt_sha256: str,
    producer_sha256: str,
    operation_evidence: Mapping[str, object],
    receipt_timestamp: str,
    now: datetime,
) -> tuple[dict[str, Any], str]:
    reason = "vexp_candidate_publication_evidence_invalid"
    now = _require_utc_clock(now)
    permit = issuance.get("permit")
    predicate = issuance.get("current_predicate")
    if not isinstance(permit, dict) or not isinstance(predicate, dict):
        raise PermitError(reason)
    permit_sha256 = _require_sha256(issuance.get("permit_sha256"), reason=reason)
    path = _candidate_publication_evidence_path(
        permit_sha256=permit_sha256,
        receipt_kind=receipt_kind,
        receipt_sha256=receipt_sha256,
    )
    raw, _metadata = _trusted_read(
        path,
        expected_mode=CANDIDATE_AUTHORITY_RECORD_MODE,
        expected_uid=CANDIDATE_AUTHORITY_LEDGER_OWNER_UID,
        expected_gid=CANDIDATE_AUTHORITY_LEDGER_OWNER_GID,
        max_bytes=MAX_VEXP_CANDIDATE_PUBLICATION_EVIDENCE_BYTES,
        reason_prefix="vexp_candidate_publication_evidence",
    )
    payload = _decode_guard_json(raw, reason=reason)
    manifest = _read_candidate_evidence_producer_manifest()
    allowed = {
        str(row["receipt_kind"]): str(row["producer_sha256"])
        for row in manifest["allowed_producers"]
    }
    producer_digest = _require_sha256(producer_sha256, reason=reason)
    receipt_digest = _require_sha256(receipt_sha256, reason=reason)
    receipt_time = _parse_utc_timestamp(receipt_timestamp, reason=reason)
    published_at = _parse_utc_timestamp(payload.get("published_at"), reason=reason)
    last_closed_at = _parse_utc_timestamp(
        operation_evidence.get("last_closed_at"), reason=reason
    )
    issued_at = _parse_utc_timestamp(permit.get("issued_at"), reason=reason)
    expires_at = _parse_utc_timestamp(permit.get("expires_at"), reason=reason)
    published_monotonic_ns = payload.get("published_monotonic_ns")
    deadline_monotonic_ns = payload.get("deadline_monotonic_ns")
    current_monotonic_ns = _monotonic_ns()
    if (
        set(payload) != CANDIDATE_PUBLICATION_EVIDENCE_KEYS
        or payload.get("contract_name")
        != VEXP_CANDIDATE_PUBLICATION_EVIDENCE_CONTRACT_NAME
        or payload.get("version")
        != VEXP_CANDIDATE_PUBLICATION_EVIDENCE_VERSION
        or payload.get("status") != "published"
        or payload.get("receipt_kind") != receipt_kind
        or payload.get("permit_sha256") != permit_sha256
        or payload.get("permit_commit_sha256")
        != issuance.get("permit_commit_sha256")
        or payload.get("epoch_started_ms") != permit.get("epoch_started_ms")
        or payload.get("qualification_certificate_sha256")
        != permit.get("qualification_certificate_sha256")
        or payload.get("current_predicate_record_sha256")
        != predicate.get("record_sha256")
        or payload.get("receipt_path") != receipt_path
        or payload.get("receipt_sha256") != receipt_digest
        or payload.get("producer_sha256") != producer_digest
        or allowed.get(receipt_kind) != producer_digest
        or payload.get("root_attestor_sha256") != manifest.get("attestor_sha256")
        or payload.get("operation_tail_sha256")
        != operation_evidence.get("tail_sha256")
        or payload.get("boot_id") != operation_evidence.get("boot_id")
        or payload.get("boot_id") != _current_boot_id()
        or type(published_monotonic_ns) is not int
        or type(deadline_monotonic_ns) is not int
        or published_monotonic_ns < int(
            operation_evidence.get("last_closed_monotonic_ns") or 0
        )
        or published_monotonic_ns > deadline_monotonic_ns
        or published_monotonic_ns > current_monotonic_ns
        or deadline_monotonic_ns - published_monotonic_ns
        > MAX_CANDIDATE_BOUNDARY_DURATION_NS
        or current_monotonic_ns > deadline_monotonic_ns
        or not issued_at <= receipt_time <= published_at < expires_at
        or published_at < last_closed_at
        or published_at > now
        or raw != _canonical_record_bytes(payload)
    ):
        raise PermitError(reason)
    publication_sha256 = hashlib.sha256(raw).hexdigest()
    _require_candidate_publication_not_revoked(publication_sha256)
    return dict(payload), publication_sha256


def _require_candidate_publication_not_revoked(publication_sha256: str) -> None:
    publication_digest = _require_sha256(
        publication_sha256,
        reason="vexp_candidate_publication_revocation_invalid",
    )
    revocation_path = (
        CANDIDATE_AUTHORITY_REVOCATION_DIRECTORY
        / f"{publication_digest}.json"
    )
    revocation_directory_metadata = _validate_trusted_directory(
        CANDIDATE_AUTHORITY_REVOCATION_DIRECTORY,
        expected_mode=CANDIDATE_AUTHORITY_LEDGER_DIRECTORY_MODE,
        expected_uid=CANDIDATE_AUTHORITY_LEDGER_OWNER_UID,
        expected_gid=CANDIDATE_AUTHORITY_LEDGER_OWNER_GID,
        reason="vexp_candidate_publication_revocation_directory_untrusted",
    )
    try:
        os.stat(revocation_path, follow_symlinks=False)
    except FileNotFoundError:
        final_revocation_directory_metadata = _validate_trusted_directory(
            CANDIDATE_AUTHORITY_REVOCATION_DIRECTORY,
            expected_mode=CANDIDATE_AUTHORITY_LEDGER_DIRECTORY_MODE,
            expected_uid=CANDIDATE_AUTHORITY_LEDGER_OWNER_UID,
            expected_gid=CANDIDATE_AUTHORITY_LEDGER_OWNER_GID,
            reason="vexp_candidate_publication_revocation_directory_untrusted",
        )
        if _trusted_file_identity(
            revocation_directory_metadata
        ) != _trusted_file_identity(final_revocation_directory_metadata):
            raise PermitError(
                "vexp_candidate_publication_revocation_directory_changed"
            )
    except OSError as exc:
        raise PermitError("vexp_candidate_publication_revocation_untrusted") from exc
    else:
        _trusted_read(
            revocation_path,
            expected_mode=CANDIDATE_AUTHORITY_RECORD_MODE,
            expected_uid=CANDIDATE_AUTHORITY_LEDGER_OWNER_UID,
            expected_gid=CANDIDATE_AUTHORITY_LEDGER_OWNER_GID,
            max_bytes=MAX_VEXP_CANDIDATE_PUBLICATION_EVIDENCE_BYTES,
            reason_prefix="vexp_candidate_publication_revocation",
        )
        raise PermitError("vexp_candidate_publication_revoked")


def _require_candidate_publication_record_current(
    *,
    permit_sha256: str,
    receipt_kind: str,
    receipt_sha256: str,
    expected_publication_sha256: str,
) -> None:
    expected_digest = _require_sha256(
        expected_publication_sha256,
        reason="vexp_candidate_publication_binding_invalid",
    )
    path = _candidate_publication_evidence_path(
        permit_sha256=permit_sha256,
        receipt_kind=receipt_kind,
        receipt_sha256=receipt_sha256,
    )
    raw, _metadata = _trusted_read(
        path,
        expected_mode=CANDIDATE_AUTHORITY_RECORD_MODE,
        expected_uid=CANDIDATE_AUTHORITY_LEDGER_OWNER_UID,
        expected_gid=CANDIDATE_AUTHORITY_LEDGER_OWNER_GID,
        max_bytes=MAX_VEXP_CANDIDATE_PUBLICATION_EVIDENCE_BYTES,
        reason_prefix="vexp_candidate_publication_evidence",
    )
    payload = _decode_guard_json(
        raw,
        reason="vexp_candidate_publication_binding_invalid",
    )
    if (
        hashlib.sha256(raw).hexdigest() != expected_digest
        or raw != _canonical_record_bytes(payload)
        or set(payload) != CANDIDATE_PUBLICATION_EVIDENCE_KEYS
        or payload.get("contract_name")
        != VEXP_CANDIDATE_PUBLICATION_EVIDENCE_CONTRACT_NAME
        or payload.get("version") != VEXP_CANDIDATE_PUBLICATION_EVIDENCE_VERSION
        or payload.get("status") != "published"
        or payload.get("receipt_kind") != receipt_kind
        or payload.get("permit_sha256") != permit_sha256
        or payload.get("receipt_sha256") != receipt_sha256
    ):
        raise PermitError("vexp_candidate_publication_binding_invalid")
    _require_candidate_publication_not_revoked(expected_digest)


def _candidate_finalization_payload(
    *,
    sealed_at: datetime,
    state_path: Path,
    state_owner_uid: int,
    current_issuance: Mapping[str, Any],
    current_issuance_sha256: str,
    inputs: Mapping[str, object],
) -> dict[str, object]:
    permit = dict(current_issuance["permit"])
    return {
        "contract_name": VEXP_CANDIDATE_FINALIZATION_CONTRACT_NAME,
        "version": VEXP_CANDIDATE_FINALIZATION_VERSION,
        "status": "sealed",
        "sealed_at": _format_utc_timestamp(sealed_at),
        "sentinel_state_path": str(state_path),
        "sentinel_state_owner_uid": state_owner_uid,
        "epoch_started_ms": permit["epoch_started_ms"],
        "terminal_identity_sha256": permit["terminal_identity_sha256"],
        "qualification_certificate_schema": permit[
            "qualification_certificate_schema"
        ],
        "qualification_certificate_sha256": permit[
            "qualification_certificate_sha256"
        ],
        "qualification_certificate_identity": permit[
            "qualification_certificate_identity"
        ],
        "qualification_certificate_event_hash": permit[
            "qualification_certificate_event_hash"
        ],
        "candidate_receipt_path": inputs["candidate_receipt_path"],
        "candidate_receipt_owner_uid": state_owner_uid,
        "candidate_receipt_schema": CANDIDATE_RUNTIME_RECEIPT_SCHEMA,
        "candidate_receipt_sha256": inputs["candidate_receipt_sha256"],
        "candidate_observed_at": inputs["candidate_observed_at"],
        "source_revision": inputs["source_revision"],
        "image_tag": inputs["image_tag"],
        "image_id": inputs["image_id"],
        "compose_project": inputs["compose_project"],
        "candidate_permit_sha256": current_issuance["permit_sha256"],
        "candidate_permit_commit_sha256": current_issuance[
            "permit_commit_sha256"
        ],
        "candidate_issuance_record_sha256": current_issuance_sha256,
        "image_build_receipt_path": inputs["image_build_receipt_path"],
        "image_build_receipt_owner_uid": state_owner_uid,
        "image_build_receipt_schema": CANDIDATE_IMAGE_BUILD_RECEIPT_SCHEMA,
        "image_build_receipt_sha256": inputs["image_build_receipt_sha256"],
        "image_build_producer_sha256": inputs["image_build_producer_sha256"],
        "image_reused": inputs["image_reused"],
        "image_build_permit_sha256": inputs["image_build_permit_sha256"],
        "image_build_permit_commit_sha256": inputs[
            "image_build_permit_commit_sha256"
        ],
        "image_build_issuance_record_sha256": inputs[
            "image_build_issuance_record_sha256"
        ],
        "candidate_operation_evidence_sha256": inputs[
            "candidate_operation_evidence_sha256"
        ],
        "candidate_publication_evidence_sha256": inputs[
            "candidate_publication_evidence_sha256"
        ],
        "candidate_publication_published_at": inputs[
            "candidate_publication_published_at"
        ],
        "candidate_publication_deadline_monotonic_ns": inputs[
            "candidate_publication_deadline_monotonic_ns"
        ],
        "image_build_operation_evidence_sha256": inputs[
            "image_build_operation_evidence_sha256"
        ],
        "image_build_publication_evidence_sha256": inputs[
            "image_build_publication_evidence_sha256"
        ],
        "image_build_publication_published_at": inputs[
            "image_build_publication_published_at"
        ],
        "image_build_publication_deadline_monotonic_ns": inputs[
            "image_build_publication_deadline_monotonic_ns"
        ],
        "finalization_boot_id": inputs["finalization_boot_id"],
        "finalization_monotonic_ns": inputs["finalization_monotonic_ns"],
    }


def _validate_candidate_finalization_record(
    value: object,
    *,
    expected_candidate_permit_sha256: str | None = None,
) -> dict[str, Any]:
    reason = "vexp_candidate_finalization_record_invalid"
    if not isinstance(value, dict) or set(value) != CANDIDATE_FINALIZATION_KEYS:
        raise PermitError(reason)
    candidate_permit_sha256 = _require_sha256(
        value.get("candidate_permit_sha256"), reason=reason
    )
    image_permit_sha256 = _require_sha256(
        value.get("image_build_permit_sha256"), reason=reason
    )
    candidate_issuance, candidate_issuance_sha256 = (
        _read_candidate_issuance_record(candidate_permit_sha256)
    )
    image_issuance, image_issuance_sha256 = _read_candidate_issuance_record(
        image_permit_sha256
    )
    candidate_permit = dict(candidate_issuance["permit"])
    image_permit = dict(image_issuance["permit"])
    if (
        value.get("contract_name") != VEXP_CANDIDATE_FINALIZATION_CONTRACT_NAME
        or value.get("version") != VEXP_CANDIDATE_FINALIZATION_VERSION
        or value.get("status") != "sealed"
        or (
            expected_candidate_permit_sha256 is not None
            and candidate_permit_sha256 != expected_candidate_permit_sha256
        )
        or value.get("sentinel_state_path")
        != candidate_issuance.get("sentinel_state_path")
        or value.get("sentinel_state_owner_uid")
        != candidate_issuance.get("sentinel_state_owner_uid")
        or value.get("candidate_receipt_owner_uid")
        != candidate_issuance.get("sentinel_state_owner_uid")
        or value.get("image_build_receipt_owner_uid")
        != candidate_issuance.get("sentinel_state_owner_uid")
        or image_issuance.get("sentinel_state_path")
        != candidate_issuance.get("sentinel_state_path")
        or image_issuance.get("sentinel_state_owner_uid")
        != candidate_issuance.get("sentinel_state_owner_uid")
        or any(
            image_permit.get(name) != candidate_permit.get(name)
            for name in (
                "epoch_started_at",
                "epoch_started_ms",
                "qualification_earliest_completion_at",
                "qualified_at",
                "terminal_identity_sha256",
                "qualification_certificate_schema",
                "qualification_certificate_sha256",
                "qualification_certificate_identity",
                "qualification_certificate_event_hash",
            )
        )
        or value.get("candidate_receipt_schema")
        != CANDIDATE_RUNTIME_RECEIPT_SCHEMA
        or value.get("image_build_receipt_schema")
        != CANDIDATE_IMAGE_BUILD_RECEIPT_SCHEMA
        or value.get("candidate_issuance_record_sha256")
        != candidate_issuance_sha256
        or value.get("image_build_issuance_record_sha256")
        != image_issuance_sha256
        or value.get("candidate_permit_commit_sha256")
        != candidate_issuance.get("permit_commit_sha256")
        or value.get("image_build_permit_commit_sha256")
        != image_issuance.get("permit_commit_sha256")
        or value.get("epoch_started_ms") != candidate_permit["epoch_started_ms"]
        or value.get("terminal_identity_sha256")
        != candidate_permit["terminal_identity_sha256"]
        or value.get("qualification_certificate_schema")
        != candidate_permit["qualification_certificate_schema"]
        or value.get("qualification_certificate_sha256")
        != candidate_permit["qualification_certificate_sha256"]
        or value.get("qualification_certificate_identity")
        != candidate_permit["qualification_certificate_identity"]
        or value.get("qualification_certificate_event_hash")
        != candidate_permit["qualification_certificate_event_hash"]
        or not isinstance(value.get("image_reused"), bool)
    ):
        raise PermitError(reason)
    for name in (
        "candidate_receipt_sha256",
        "image_build_receipt_sha256",
        "image_build_producer_sha256",
        "candidate_operation_evidence_sha256",
        "candidate_publication_evidence_sha256",
        "image_build_operation_evidence_sha256",
        "image_build_publication_evidence_sha256",
    ):
        _require_sha256(value.get(name), reason=reason)
    if (
        BOOT_ID_PATTERN.fullmatch(str(value.get("finalization_boot_id") or ""))
        is None
        or type(value.get("finalization_monotonic_ns")) is not int
        or value["finalization_monotonic_ns"] <= 0
    ):
        raise PermitError(reason)
    for name in ("candidate_receipt_path", "image_build_receipt_path"):
        path = Path(str(value.get(name) or ""))
        if not path.is_absolute() or path != Path(os.path.abspath(os.fspath(path))):
            raise PermitError(reason)
    source_revision = str(value.get("source_revision") or "")
    if (
        GIT_COMMIT_PATTERN.fullmatch(source_revision) is None
        or value.get("image_tag")
        not in {
            f"ea-runtime:manfred-{source_revision}",
            f"ea-runtime:memorial-{source_revision}",
        }
        or IMAGE_ID_PATTERN.fullmatch(str(value.get("image_id") or "")) is None
        or CANDIDATE_PROJECT_PATTERN.fullmatch(
            str(value.get("compose_project") or "")
        )
        is None
    ):
        raise PermitError(reason)
    issued_at = _parse_utc_timestamp(candidate_permit["issued_at"], reason=reason)
    expires_at = _parse_utc_timestamp(candidate_permit["expires_at"], reason=reason)
    image_expires_at = _parse_utc_timestamp(image_permit["expires_at"], reason=reason)
    observed_at = _parse_utc_timestamp(value.get("candidate_observed_at"), reason=reason)
    sealed_at = _parse_utc_timestamp(value.get("sealed_at"), reason=reason)
    candidate_published_at = _parse_utc_timestamp(
        value.get("candidate_publication_published_at"), reason=reason
    )
    image_published_at = _parse_utc_timestamp(
        value.get("image_build_publication_published_at"), reason=reason
    )
    candidate_deadline = value.get("candidate_publication_deadline_monotonic_ns")
    image_deadline = value.get("image_build_publication_deadline_monotonic_ns")
    if (
        type(candidate_deadline) is not int
        or type(image_deadline) is not int
        or not 0 < int(value["finalization_monotonic_ns"]) <= min(
            candidate_deadline, image_deadline
        )
        or not issued_at <= observed_at
        or max(candidate_published_at, image_published_at) > sealed_at
        or sealed_at >= min(expires_at, image_expires_at)
    ):
        raise PermitError(reason)
    return dict(value)


def _read_candidate_finalization_record(
    candidate_permit_sha256: str,
) -> tuple[dict[str, Any], str]:
    _validate_candidate_authority_ledger()
    path = _candidate_authority_record_path(
        CANDIDATE_AUTHORITY_FINALIZATION_DIRECTORY,
        candidate_permit_sha256,
    )
    raw, _metadata = _trusted_read(
        path,
        expected_mode=CANDIDATE_AUTHORITY_RECORD_MODE,
        expected_uid=CANDIDATE_AUTHORITY_LEDGER_OWNER_UID,
        expected_gid=CANDIDATE_AUTHORITY_LEDGER_OWNER_GID,
        max_bytes=MAX_VEXP_CANDIDATE_AUTHORITY_RECORD_BYTES,
        reason_prefix="vexp_candidate_finalization_record",
    )
    payload = _decode_guard_json(
        raw,
        reason="vexp_candidate_finalization_record_invalid",
    )
    validated = _validate_candidate_finalization_record(
        payload,
        expected_candidate_permit_sha256=candidate_permit_sha256,
    )
    if raw != _canonical_record_bytes(validated):
        raise PermitError("vexp_candidate_finalization_record_noncanonical")
    return validated, hashlib.sha256(raw).hexdigest()


def _candidate_finalization_commit_path(candidate_permit_sha256: str) -> Path:
    digest = _require_sha256(
        candidate_permit_sha256,
        reason="vexp_candidate_finalization_commit_invalid",
    )
    return CANDIDATE_AUTHORITY_FINALIZATION_DIRECTORY / f"{digest}.commit.json"


def _candidate_finalization_commit_payload(
    *,
    committed_at: datetime,
    candidate_permit_sha256: str,
    finalization_record_sha256: str,
    finalization: Mapping[str, Any],
    boot_id: str,
    monotonic_ns: int,
) -> dict[str, object]:
    return {
        "contract_name": VEXP_CANDIDATE_FINALIZATION_COMMIT_CONTRACT_NAME,
        "version": VEXP_CANDIDATE_FINALIZATION_COMMIT_VERSION,
        "status": "committed",
        "committed_at": _format_utc_timestamp(committed_at),
        "candidate_permit_sha256": candidate_permit_sha256,
        "finalization_record_sha256": finalization_record_sha256,
        "candidate_publication_evidence_sha256": finalization[
            "candidate_publication_evidence_sha256"
        ],
        "image_build_publication_evidence_sha256": finalization[
            "image_build_publication_evidence_sha256"
        ],
        "boot_id": boot_id,
        "monotonic_ns": monotonic_ns,
    }


def _validate_candidate_finalization_commit(
    value: object,
    *,
    candidate_permit_sha256: str,
    finalization_record_sha256: str,
    finalization: Mapping[str, Any],
) -> dict[str, Any]:
    reason = "vexp_candidate_finalization_commit_invalid"
    if not isinstance(value, dict) or set(value) != CANDIDATE_FINALIZATION_COMMIT_KEYS:
        raise PermitError(reason)
    committed_at = _parse_utc_timestamp(value.get("committed_at"), reason=reason)
    sealed_at = _parse_utc_timestamp(finalization.get("sealed_at"), reason=reason)
    candidate_issuance, _candidate_issuance_sha256 = (
        _read_candidate_issuance_record(candidate_permit_sha256)
    )
    image_issuance, _image_issuance_sha256 = _read_candidate_issuance_record(
        str(finalization.get("image_build_permit_sha256") or "")
    )
    candidate_expires_at = _parse_utc_timestamp(
        candidate_issuance["permit"]["expires_at"], reason=reason
    )
    image_expires_at = _parse_utc_timestamp(
        image_issuance["permit"]["expires_at"], reason=reason
    )
    candidate_deadline = finalization.get(
        "candidate_publication_deadline_monotonic_ns"
    )
    image_deadline = finalization.get(
        "image_build_publication_deadline_monotonic_ns"
    )
    if (
        value.get("contract_name")
        != VEXP_CANDIDATE_FINALIZATION_COMMIT_CONTRACT_NAME
        or value.get("version") != VEXP_CANDIDATE_FINALIZATION_COMMIT_VERSION
        or value.get("status") != "committed"
        or value.get("candidate_permit_sha256") != candidate_permit_sha256
        or value.get("finalization_record_sha256")
        != finalization_record_sha256
        or value.get("candidate_publication_evidence_sha256")
        != finalization.get("candidate_publication_evidence_sha256")
        or value.get("image_build_publication_evidence_sha256")
        != finalization.get("image_build_publication_evidence_sha256")
        or BOOT_ID_PATTERN.fullmatch(str(value.get("boot_id") or "")) is None
        or value.get("boot_id") != finalization.get("finalization_boot_id")
        or type(value.get("monotonic_ns")) is not int
        or value["monotonic_ns"] < int(finalization.get("finalization_monotonic_ns") or 0)
        or committed_at < sealed_at
        or committed_at >= min(candidate_expires_at, image_expires_at)
        or type(candidate_deadline) is not int
        or type(image_deadline) is not int
        or value["monotonic_ns"] > min(candidate_deadline, image_deadline)
    ):
        raise PermitError(reason)
    for name in (
        "candidate_permit_sha256",
        "finalization_record_sha256",
        "candidate_publication_evidence_sha256",
        "image_build_publication_evidence_sha256",
    ):
        _require_sha256(value.get(name), reason=reason)
    return dict(value)


def _read_candidate_finalization_commit(
    *,
    candidate_permit_sha256: str,
    finalization_record_sha256: str,
    finalization: Mapping[str, Any],
) -> tuple[dict[str, Any], str]:
    path = _candidate_finalization_commit_path(candidate_permit_sha256)
    raw, _metadata = _trusted_read(
        path,
        expected_mode=CANDIDATE_AUTHORITY_RECORD_MODE,
        expected_uid=CANDIDATE_AUTHORITY_LEDGER_OWNER_UID,
        expected_gid=CANDIDATE_AUTHORITY_LEDGER_OWNER_GID,
        max_bytes=MAX_VEXP_CANDIDATE_AUTHORITY_RECORD_BYTES,
        reason_prefix="vexp_candidate_finalization_commit",
    )
    payload = _decode_guard_json(
        raw,
        reason="vexp_candidate_finalization_commit_invalid",
    )
    validated = _validate_candidate_finalization_commit(
        payload,
        candidate_permit_sha256=candidate_permit_sha256,
        finalization_record_sha256=finalization_record_sha256,
        finalization=finalization,
    )
    if raw != _canonical_record_bytes(validated):
        raise PermitError("vexp_candidate_finalization_commit_noncanonical")
    return validated, hashlib.sha256(raw).hexdigest()


def _candidate_finalization_abort_path(candidate_permit_sha256: str) -> Path:
    digest = _require_sha256(
        candidate_permit_sha256,
        reason="vexp_candidate_finalization_abort_invalid",
    )
    return CANDIDATE_AUTHORITY_FINALIZATION_DIRECTORY / f"{digest}.abort.json"


def _publish_candidate_finalization_abort(
    *,
    candidate_permit_sha256: str,
    finalization_record_sha256: str,
    finalization_commit_sha256: str,
    reason: str,
) -> None:
    if not isinstance(reason, str) or not reason.startswith("vexp_candidate_"):
        reason = "vexp_candidate_postcommit_revalidation_failed"
    payload = {
        "contract_name": VEXP_CANDIDATE_FINALIZATION_ABORT_CONTRACT_NAME,
        "version": VEXP_CANDIDATE_FINALIZATION_ABORT_VERSION,
        "status": "aborted",
        "aborted_at": _format_utc_timestamp(_utc_now_datetime()),
        "candidate_permit_sha256": candidate_permit_sha256,
        "finalization_record_sha256": finalization_record_sha256,
        "finalization_commit_sha256": finalization_commit_sha256,
        "reason": reason,
    }
    if set(payload) != CANDIDATE_FINALIZATION_ABORT_KEYS:
        raise PermitError("vexp_candidate_finalization_abort_invalid")
    for name in (
        "candidate_permit_sha256",
        "finalization_record_sha256",
        "finalization_commit_sha256",
    ):
        _require_sha256(payload[name], reason="vexp_candidate_finalization_abort_invalid")
    _parse_utc_timestamp(
        payload["aborted_at"], reason="vexp_candidate_finalization_abort_invalid"
    )
    _atomic_publish_candidate_authority_record(
        _candidate_finalization_abort_path(candidate_permit_sha256),
        payload,
    )


def _require_candidate_finalization_not_aborted(
    *,
    candidate_permit_sha256: str,
    finalization_record_sha256: str,
    finalization_commit_sha256: str,
) -> None:
    path = _candidate_finalization_abort_path(candidate_permit_sha256)
    directory_before = _validate_trusted_directory(
        CANDIDATE_AUTHORITY_FINALIZATION_DIRECTORY,
        expected_mode=CANDIDATE_AUTHORITY_LEDGER_DIRECTORY_MODE,
        expected_uid=CANDIDATE_AUTHORITY_LEDGER_OWNER_UID,
        expected_gid=CANDIDATE_AUTHORITY_LEDGER_OWNER_GID,
        reason="vexp_candidate_finalization_directory_untrusted",
    )
    try:
        raw, _metadata = _trusted_read(
            path,
            expected_mode=CANDIDATE_AUTHORITY_RECORD_MODE,
            expected_uid=CANDIDATE_AUTHORITY_LEDGER_OWNER_UID,
            expected_gid=CANDIDATE_AUTHORITY_LEDGER_OWNER_GID,
            max_bytes=MAX_VEXP_CANDIDATE_AUTHORITY_RECORD_BYTES,
            reason_prefix="vexp_candidate_finalization_abort",
        )
    except PermitError as exc:
        if str(exc) != "vexp_candidate_finalization_abort_unavailable":
            raise
        directory_after = _validate_trusted_directory(
            CANDIDATE_AUTHORITY_FINALIZATION_DIRECTORY,
            expected_mode=CANDIDATE_AUTHORITY_LEDGER_DIRECTORY_MODE,
            expected_uid=CANDIDATE_AUTHORITY_LEDGER_OWNER_UID,
            expected_gid=CANDIDATE_AUTHORITY_LEDGER_OWNER_GID,
            reason="vexp_candidate_finalization_directory_untrusted",
        )
        if _trusted_file_identity(directory_before) != _trusted_file_identity(
            directory_after
        ):
            raise PermitError("vexp_candidate_finalization_abort_race")
        return
    payload = _decode_guard_json(raw, reason="vexp_candidate_finalization_abort_invalid")
    if (
        raw != _canonical_record_bytes(payload)
        or set(payload) != CANDIDATE_FINALIZATION_ABORT_KEYS
        or payload.get("contract_name")
        != VEXP_CANDIDATE_FINALIZATION_ABORT_CONTRACT_NAME
        or payload.get("version") != VEXP_CANDIDATE_FINALIZATION_ABORT_VERSION
        or payload.get("status") != "aborted"
        or payload.get("candidate_permit_sha256") != candidate_permit_sha256
        or payload.get("finalization_record_sha256")
        != finalization_record_sha256
        or payload.get("finalization_commit_sha256")
        != finalization_commit_sha256
    ):
        raise PermitError("vexp_candidate_finalization_abort_invalid")
    raise PermitError("vexp_candidate_finalization_aborted")


def seal_candidate(
    *,
    state_path: Path,
    state_owner_uid: int,
    candidate_receipt_path: Path,
    candidate_receipt_sha256: str,
) -> dict[str, object]:
    _verify_trusted_execution_path()
    _require_root()
    _validate_state_arguments(state_path=state_path, state_owner_uid=state_owner_uid)
    _require_canonical_sentinel_state_path(
        state_path=state_path,
        state_owner_uid=state_owner_uid,
    )
    _validate_candidate_authority_ledger()
    _validate_runtime_directory(PERMIT_PATH.parent)
    expected_candidate_receipt_sha256 = _require_sha256(
        candidate_receipt_sha256,
        reason="vexp_candidate_runtime_receipt_sha256_invalid",
    )
    with _authority_lock(exclusive=True, create=False):
        now = _utc_now_datetime()
        state, state_sha256 = _read_state_with_sha256(
            state_path, owner_uid=state_owner_uid
        )
        _validate_terminal_state(state, now=now)
        void_ledger = _require_epoch_not_voided(state)
        permit, permit_sha256, commit, commit_sha256 = _read_committed_permit(
            now=now,
            require_current=True,
            permit_mode=CANDIDATE_PERMIT_MODE,
        )
        if _terminal_identity(permit) != _terminal_identity(state):
            raise PermitError("vexp_mutation_permit_state_binding_mismatch")
        certificate, qualification_certificate = _read_qualification_certificate(state)
        current_predicate = _read_current_predicate_evidence(
            state=state,
            state_sha256=state_sha256,
            state_path=state_path,
            state_owner_uid=state_owner_uid,
            certificate=certificate,
            qualification_certificate=qualification_certificate,
            now=now,
        )
        _validate_permit_certificate_binding(permit, qualification_certificate)
        current_issuance, current_issuance_sha256 = (
            _read_candidate_issuance_record(permit_sha256)
        )
        if (
            current_issuance.get("permit") != permit
            or current_issuance.get("permit_commit") != commit
            or current_issuance.get("permit_commit_sha256") != commit_sha256
            or current_issuance.get("epoch_void_ledger") != void_ledger
        ):
            raise PermitError("vexp_candidate_issuance_binding_mismatch")
        inputs = _validated_candidate_seal_inputs(
            candidate_receipt_path=candidate_receipt_path,
            candidate_receipt_sha256=expected_candidate_receipt_sha256,
            state_owner_uid=state_owner_uid,
            current_issuance=current_issuance,
        )
        image_issuance, _image_issuance_sha256 = _read_candidate_issuance_record(
            str(inputs["image_build_permit_sha256"])
        )
        candidate_operation_evidence = _read_candidate_operation_evidence(
            issuance=current_issuance,
            receipt_kind="candidate_runtime",
            operations=list(inputs["candidate_operations"]),
            producer_sha256=str(inputs["candidate_producer_sha256"]),
            now=now,
        )
        image_operation_evidence = _read_candidate_operation_evidence(
            issuance=image_issuance,
            receipt_kind="image_build",
            operations=list(inputs["image_build_operations"]),
            producer_sha256=str(inputs["image_build_producer_sha256"]),
            now=now,
        )
        _candidate_publication, candidate_publication_sha256 = (
            _read_candidate_publication_evidence(
                issuance=current_issuance,
                receipt_kind="candidate_runtime",
                receipt_path=str(inputs["candidate_receipt_path"]),
                receipt_sha256=str(inputs["candidate_receipt_sha256"]),
                producer_sha256=str(inputs["candidate_producer_sha256"]),
                operation_evidence=candidate_operation_evidence,
                receipt_timestamp=str(inputs["candidate_observed_at"]),
                now=now,
            )
        )
        _image_publication, image_publication_sha256 = (
            _read_candidate_publication_evidence(
                issuance=image_issuance,
                receipt_kind="image_build",
                receipt_path=str(inputs["image_build_receipt_path"]),
                receipt_sha256=str(inputs["image_build_receipt_sha256"]),
                producer_sha256=str(inputs["image_build_producer_sha256"]),
                operation_evidence=image_operation_evidence,
                receipt_timestamp=str(inputs["image_build_created_at"]),
                now=now,
            )
        )
        finalization_monotonic_ns = _monotonic_ns()
        if not (
            max(
                int(_candidate_publication["published_monotonic_ns"]),
                int(_image_publication["published_monotonic_ns"]),
            )
            <= finalization_monotonic_ns
            <= min(
                int(_candidate_publication["deadline_monotonic_ns"]),
                int(_image_publication["deadline_monotonic_ns"]),
            )
        ):
            raise PermitError("vexp_candidate_finalization_deadline_expired")
        inputs.update(
            {
                "candidate_operation_evidence_sha256": candidate_operation_evidence[
                    "aggregate_sha256"
                ],
                "candidate_publication_evidence_sha256": candidate_publication_sha256,
                "candidate_publication_published_at": _candidate_publication[
                    "published_at"
                ],
                "candidate_publication_deadline_monotonic_ns": (
                    _candidate_publication["deadline_monotonic_ns"]
                ),
                "image_build_operation_evidence_sha256": image_operation_evidence[
                    "aggregate_sha256"
                ],
                "image_build_publication_evidence_sha256": image_publication_sha256,
                "image_build_publication_published_at": _image_publication[
                    "published_at"
                ],
                "image_build_publication_deadline_monotonic_ns": (
                    _image_publication["deadline_monotonic_ns"]
                ),
                "finalization_boot_id": _current_boot_id(),
                "finalization_monotonic_ns": finalization_monotonic_ns,
            }
        )
        final_now = _utc_now_datetime()
        if (
            final_now
            < max(
                _parse_utc_timestamp(
                    _candidate_publication["published_at"],
                    reason="vexp_candidate_finalization_publication_time_invalid",
                ),
                _parse_utc_timestamp(
                    _image_publication["published_at"],
                    reason="vexp_candidate_finalization_publication_time_invalid",
                ),
            )
            or final_now
            >= min(
                _parse_utc_timestamp(
                    permit["expires_at"],
                    reason="vexp_candidate_finalization_deadline_expired",
                ),
                _parse_utc_timestamp(
                    image_issuance["permit"]["expires_at"],
                    reason="vexp_candidate_finalization_deadline_expired",
                ),
            )
        ):
            raise PermitError("vexp_candidate_finalization_deadline_expired")
        final_state, final_state_sha256 = _read_state_with_sha256(
            state_path, owner_uid=state_owner_uid
        )
        _validate_terminal_state(final_state, now=final_now)
        final_void_ledger = _require_epoch_not_voided(final_state)
        final_certificate, final_qualification_certificate = (
            _read_qualification_certificate(final_state)
        )
        final_current_predicate = _read_current_predicate_evidence(
            state=final_state,
            state_sha256=final_state_sha256,
            state_path=state_path,
            state_owner_uid=state_owner_uid,
            certificate=final_certificate,
            qualification_certificate=final_qualification_certificate,
            now=final_now,
        )
        (
            final_permit,
            final_permit_sha256,
            final_commit,
            final_commit_sha256,
        ) = _read_committed_permit(
            now=final_now,
            require_current=True,
            permit_mode=CANDIDATE_PERMIT_MODE,
        )
        if (
            _terminal_identity(final_state) != _terminal_identity(state)
            or final_void_ledger != void_ledger
            or final_permit != permit
            or final_permit_sha256 != permit_sha256
            or final_commit != commit
            or final_commit_sha256 != commit_sha256
            or final_qualification_certificate != qualification_certificate
            or final_current_predicate != current_predicate
        ):
            raise PermitError("vexp_candidate_authority_changed_before_seal")
        path = _candidate_authority_record_path(
            CANDIDATE_AUTHORITY_FINALIZATION_DIRECTORY,
            permit_sha256,
        )
        try:
            existing, record_sha256 = _read_candidate_finalization_record(
                permit_sha256
            )
        except PermitError as exc:
            if str(exc) != "vexp_candidate_finalization_record_unavailable":
                raise
            payload = _candidate_finalization_payload(
                sealed_at=final_now,
                state_path=state_path,
                state_owner_uid=state_owner_uid,
                current_issuance=current_issuance,
                current_issuance_sha256=current_issuance_sha256,
                inputs=inputs,
            )
            validated = _validate_candidate_finalization_record(
                payload,
                expected_candidate_permit_sha256=permit_sha256,
            )
            record_sha256, created = _atomic_publish_candidate_authority_record(
                path,
                validated,
            )
        else:
            existing_sealed_at = _parse_utc_timestamp(
                existing.get("sealed_at"),
                reason="vexp_candidate_finalization_record_invalid",
            )
            inputs["finalization_boot_id"] = existing["finalization_boot_id"]
            inputs["finalization_monotonic_ns"] = existing[
                "finalization_monotonic_ns"
            ]
            expected_existing = _candidate_finalization_payload(
                sealed_at=existing_sealed_at,
                state_path=state_path,
                state_owner_uid=state_owner_uid,
                current_issuance=current_issuance,
                current_issuance_sha256=current_issuance_sha256,
                inputs=inputs,
            )
            if existing != expected_existing:
                raise PermitError("vexp_candidate_authority_record_conflict")
            validated = existing
            created = False
        published_finalization, published_finalization_sha256 = (
            _read_candidate_finalization_record(permit_sha256)
        )
        if (
            published_finalization != validated
            or published_finalization_sha256 != record_sha256
        ):
            raise PermitError("vexp_candidate_finalization_changed_after_publish")

        postpublish_now = _utc_now_datetime()
        postpublish_state, postpublish_state_sha256 = _read_state_with_sha256(
            state_path, owner_uid=state_owner_uid
        )
        _validate_terminal_state(postpublish_state, now=postpublish_now)
        postpublish_void_ledger = _require_epoch_not_voided(postpublish_state)
        postpublish_certificate, postpublish_qualification_certificate = (
            _read_qualification_certificate(postpublish_state)
        )
        postpublish_predicate = _read_current_predicate_evidence(
            state=postpublish_state,
            state_sha256=postpublish_state_sha256,
            state_path=state_path,
            state_owner_uid=state_owner_uid,
            certificate=postpublish_certificate,
            qualification_certificate=postpublish_qualification_certificate,
            now=postpublish_now,
        )
        (
            postpublish_permit,
            postpublish_permit_sha256,
            postpublish_commit,
            postpublish_commit_sha256,
        ) = _read_committed_permit(
            now=postpublish_now,
            require_current=True,
            permit_mode=CANDIDATE_PERMIT_MODE,
        )
        postpublish_current_issuance = _read_candidate_issuance_record(permit_sha256)
        postpublish_image_issuance = _read_candidate_issuance_record(
            str(inputs["image_build_permit_sha256"])
        )
        if (
            _terminal_identity(postpublish_state) != _terminal_identity(state)
            or postpublish_void_ledger != void_ledger
            or postpublish_permit != permit
            or postpublish_permit_sha256 != permit_sha256
            or postpublish_commit != commit
            or postpublish_commit_sha256 != commit_sha256
            or postpublish_qualification_certificate != qualification_certificate
            or postpublish_predicate != current_predicate
            or postpublish_current_issuance
            != (current_issuance, current_issuance_sha256)
            or postpublish_image_issuance
            != (image_issuance, _image_issuance_sha256)
        ):
            raise PermitError("vexp_candidate_authority_changed_after_finalization")

        post_candidate_operation_evidence = _read_candidate_operation_evidence(
            issuance=current_issuance,
            receipt_kind="candidate_runtime",
            operations=list(inputs["candidate_operations"]),
            producer_sha256=str(inputs["candidate_producer_sha256"]),
            now=postpublish_now,
        )
        post_image_operation_evidence = _read_candidate_operation_evidence(
            issuance=image_issuance,
            receipt_kind="image_build",
            operations=list(inputs["image_build_operations"]),
            producer_sha256=str(inputs["image_build_producer_sha256"]),
            now=postpublish_now,
        )
        post_candidate_publication, post_candidate_publication_sha256 = (
            _read_candidate_publication_evidence(
                issuance=current_issuance,
                receipt_kind="candidate_runtime",
                receipt_path=str(inputs["candidate_receipt_path"]),
                receipt_sha256=str(inputs["candidate_receipt_sha256"]),
                producer_sha256=str(inputs["candidate_producer_sha256"]),
                operation_evidence=post_candidate_operation_evidence,
                receipt_timestamp=str(inputs["candidate_observed_at"]),
                now=postpublish_now,
            )
        )
        post_image_publication, post_image_publication_sha256 = (
            _read_candidate_publication_evidence(
                issuance=image_issuance,
                receipt_kind="image_build",
                receipt_path=str(inputs["image_build_receipt_path"]),
                receipt_sha256=str(inputs["image_build_receipt_sha256"]),
                producer_sha256=str(inputs["image_build_producer_sha256"]),
                operation_evidence=post_image_operation_evidence,
                receipt_timestamp=str(inputs["image_build_created_at"]),
                now=postpublish_now,
            )
        )
        commit_monotonic_ns = _monotonic_ns()
        if (
            post_candidate_operation_evidence != candidate_operation_evidence
            or post_image_operation_evidence != image_operation_evidence
            or post_candidate_publication != _candidate_publication
            or post_image_publication != _image_publication
            or post_candidate_publication_sha256 != candidate_publication_sha256
            or post_image_publication_sha256 != image_publication_sha256
            or not (
                int(validated["finalization_monotonic_ns"])
                <= commit_monotonic_ns
                <= min(
                    int(post_candidate_publication["deadline_monotonic_ns"]),
                    int(post_image_publication["deadline_monotonic_ns"]),
                )
            )
        ):
            raise PermitError("vexp_candidate_evidence_changed_after_finalization")

        try:
            finalization_commit, finalization_commit_sha256 = (
                _read_candidate_finalization_commit(
                    candidate_permit_sha256=permit_sha256,
                    finalization_record_sha256=record_sha256,
                    finalization=validated,
                )
            )
            commit_created = False
        except PermitError as exc:
            if str(exc) != "vexp_candidate_finalization_commit_unavailable":
                raise
            finalization_commit = _candidate_finalization_commit_payload(
                committed_at=postpublish_now,
                candidate_permit_sha256=permit_sha256,
                finalization_record_sha256=record_sha256,
                finalization=validated,
                boot_id=str(validated["finalization_boot_id"]),
                monotonic_ns=commit_monotonic_ns,
            )
            finalization_commit = _validate_candidate_finalization_commit(
                finalization_commit,
                candidate_permit_sha256=permit_sha256,
                finalization_record_sha256=record_sha256,
                finalization=validated,
            )
            finalization_commit_sha256, commit_created = (
                _atomic_publish_candidate_authority_record(
                    _candidate_finalization_commit_path(permit_sha256),
                    finalization_commit,
                )
            )
        observed_finalization_commit = _read_candidate_finalization_commit(
            candidate_permit_sha256=permit_sha256,
            finalization_record_sha256=record_sha256,
            finalization=validated,
        )
        if observed_finalization_commit != (
            finalization_commit,
            finalization_commit_sha256,
        ):
            raise PermitError("vexp_candidate_finalization_commit_changed")
        try:
            postcommit_now = _utc_now_datetime()
            postcommit_monotonic_ns = _monotonic_ns()
            if (
                postcommit_now
                >= min(
                    _parse_utc_timestamp(
                        permit["expires_at"],
                        reason="vexp_candidate_postcommit_authority_expired",
                    ),
                    _parse_utc_timestamp(
                        image_issuance["permit"]["expires_at"],
                        reason="vexp_candidate_postcommit_authority_expired",
                    ),
                )
                or postcommit_monotonic_ns
                > min(
                    int(_candidate_publication["deadline_monotonic_ns"]),
                    int(_image_publication["deadline_monotonic_ns"]),
                )
            ):
                raise PermitError("vexp_candidate_postcommit_authority_expired")
            postcommit_state, postcommit_state_sha256 = _read_state_with_sha256(
                state_path, owner_uid=state_owner_uid
            )
            _validate_terminal_state(postcommit_state, now=postcommit_now)
            postcommit_void_ledger = _require_epoch_not_voided(postcommit_state)
            postcommit_certificate, postcommit_qualification_certificate = (
                _read_qualification_certificate(postcommit_state)
            )
            postcommit_predicate = _read_current_predicate_evidence(
                state=postcommit_state,
                state_sha256=postcommit_state_sha256,
                state_path=state_path,
                state_owner_uid=state_owner_uid,
                certificate=postcommit_certificate,
                qualification_certificate=postcommit_qualification_certificate,
                now=postcommit_now,
            )
            (
                postcommit_permit,
                postcommit_permit_sha256,
                postcommit_permit_commit,
                postcommit_permit_commit_sha256,
            ) = _read_committed_permit(
                now=postcommit_now,
                require_current=True,
                permit_mode=CANDIDATE_PERMIT_MODE,
            )
            postcommit_current_issuance = _read_candidate_issuance_record(
                permit_sha256
            )
            postcommit_image_issuance = _read_candidate_issuance_record(
                str(inputs["image_build_permit_sha256"])
            )
            postcommit_candidate_operations = _read_candidate_operation_evidence(
                issuance=current_issuance,
                receipt_kind="candidate_runtime",
                operations=list(inputs["candidate_operations"]),
                producer_sha256=str(inputs["candidate_producer_sha256"]),
                now=postcommit_now,
            )
            postcommit_image_operations = _read_candidate_operation_evidence(
                issuance=image_issuance,
                receipt_kind="image_build",
                operations=list(inputs["image_build_operations"]),
                producer_sha256=str(inputs["image_build_producer_sha256"]),
                now=postcommit_now,
            )
            postcommit_candidate_publication = _read_candidate_publication_evidence(
                issuance=current_issuance,
                receipt_kind="candidate_runtime",
                receipt_path=str(inputs["candidate_receipt_path"]),
                receipt_sha256=str(inputs["candidate_receipt_sha256"]),
                producer_sha256=str(inputs["candidate_producer_sha256"]),
                operation_evidence=postcommit_candidate_operations,
                receipt_timestamp=str(inputs["candidate_observed_at"]),
                now=postcommit_now,
            )
            postcommit_image_publication = _read_candidate_publication_evidence(
                issuance=image_issuance,
                receipt_kind="image_build",
                receipt_path=str(inputs["image_build_receipt_path"]),
                receipt_sha256=str(inputs["image_build_receipt_sha256"]),
                producer_sha256=str(inputs["image_build_producer_sha256"]),
                operation_evidence=postcommit_image_operations,
                receipt_timestamp=str(inputs["image_build_created_at"]),
                now=postcommit_now,
            )
            if (
                _terminal_identity(postcommit_state) != _terminal_identity(state)
                or postcommit_void_ledger != void_ledger
                or postcommit_qualification_certificate != qualification_certificate
                or postcommit_predicate != current_predicate
                or postcommit_permit != permit
                or postcommit_permit_sha256 != permit_sha256
                or postcommit_permit_commit != commit
                or postcommit_permit_commit_sha256 != commit_sha256
                or postcommit_current_issuance
                != (current_issuance, current_issuance_sha256)
                or postcommit_image_issuance
                != (image_issuance, _image_issuance_sha256)
                or postcommit_candidate_operations != candidate_operation_evidence
                or postcommit_image_operations != image_operation_evidence
                or postcommit_candidate_publication
                != (_candidate_publication, candidate_publication_sha256)
                or postcommit_image_publication
                != (_image_publication, image_publication_sha256)
            ):
                raise PermitError("vexp_candidate_authority_changed_after_commit")
            _require_candidate_finalization_not_aborted(
                candidate_permit_sha256=permit_sha256,
                finalization_record_sha256=record_sha256,
                finalization_commit_sha256=finalization_commit_sha256,
            )
        except PermitError as postcommit_error:
            try:
                _publish_candidate_finalization_abort(
                    candidate_permit_sha256=permit_sha256,
                    finalization_record_sha256=record_sha256,
                    finalization_commit_sha256=finalization_commit_sha256,
                    reason=str(postcommit_error),
                )
            except PermitError as abort_error:
                raise abort_error from postcommit_error
            raise
    return {
        "status": "sealed",
        "contract_name": VEXP_CANDIDATE_FINALIZATION_CONTRACT_NAME,
        "version": VEXP_CANDIDATE_FINALIZATION_VERSION,
        "path": str(path),
        "sha256": record_sha256,
        "created": created,
        "commit": {
            "contract_name": finalization_commit["contract_name"],
            "version": finalization_commit["version"],
            "status": finalization_commit["status"],
            "sha256": finalization_commit_sha256,
            "created": commit_created,
        },
        "candidate_permit_sha256": permit_sha256,
        "candidate_receipt_sha256": validated["candidate_receipt_sha256"],
        "image_build_receipt_sha256": validated[
            "image_build_receipt_sha256"
        ],
        "image_build_permit_sha256": validated["image_build_permit_sha256"],
    }


def candidate_seal_status(
    *,
    candidate_permit_sha256: str,
    candidate_receipt_path: Path,
    candidate_receipt_sha256: str,
    image_build_receipt_sha256: str,
) -> dict[str, object]:
    _verify_trusted_execution_path()
    _validate_candidate_authority_ledger()
    _validate_runtime_directory(PERMIT_PATH.parent)
    permit_digest = _require_sha256(
        candidate_permit_sha256,
        reason="vexp_candidate_seal_status_permit_sha256_invalid",
    )
    receipt_digest = _require_sha256(
        candidate_receipt_sha256,
        reason="vexp_candidate_seal_status_receipt_sha256_invalid",
    )
    image_digest = _require_sha256(
        image_build_receipt_sha256,
        reason="vexp_candidate_seal_status_image_sha256_invalid",
    )
    normalized_path = Path(os.path.abspath(os.fspath(candidate_receipt_path)))
    if not candidate_receipt_path.is_absolute() or normalized_path != candidate_receipt_path:
        raise PermitError("vexp_candidate_seal_status_receipt_path_invalid")
    with _authority_lock(exclusive=False, create=False):
        record, record_sha256 = _read_candidate_finalization_record(permit_digest)
        if (
            record.get("candidate_receipt_path") != str(normalized_path)
            or record.get("candidate_receipt_sha256") != receipt_digest
            or record.get("image_build_receipt_sha256") != image_digest
        ):
            raise PermitError("vexp_candidate_seal_status_binding_mismatch")
        finalization_commit, finalization_commit_sha256 = (
            _read_candidate_finalization_commit(
                candidate_permit_sha256=permit_digest,
                finalization_record_sha256=record_sha256,
                finalization=record,
            )
        )
        _require_candidate_finalization_not_aborted(
            candidate_permit_sha256=permit_digest,
            finalization_record_sha256=record_sha256,
            finalization_commit_sha256=finalization_commit_sha256,
        )
        _require_candidate_publication_record_current(
            permit_sha256=permit_digest,
            receipt_kind="candidate_runtime",
            receipt_sha256=receipt_digest,
            expected_publication_sha256=str(
                record["candidate_publication_evidence_sha256"]
            ),
        )
        _require_candidate_publication_record_current(
            permit_sha256=str(record["image_build_permit_sha256"]),
            receipt_kind="image_build",
            receipt_sha256=image_digest,
            expected_publication_sha256=str(
                record["image_build_publication_evidence_sha256"]
            ),
        )
        final_record = _read_candidate_finalization_record(permit_digest)
        final_commit = _read_candidate_finalization_commit(
            candidate_permit_sha256=permit_digest,
            finalization_record_sha256=record_sha256,
            finalization=record,
        )
        if final_record != (record, record_sha256) or final_commit != (
            finalization_commit,
            finalization_commit_sha256,
        ):
            raise PermitError("vexp_candidate_seal_status_changed_during_read")
    return {
        "status": "valid",
        "contract_name": VEXP_CANDIDATE_FINALIZATION_CONTRACT_NAME,
        "version": VEXP_CANDIDATE_FINALIZATION_VERSION,
        "path": str(
            _candidate_authority_record_path(
                CANDIDATE_AUTHORITY_FINALIZATION_DIRECTORY,
                permit_digest,
            )
        ),
        "sha256": record_sha256,
        "commit": {
            "contract_name": finalization_commit["contract_name"],
            "version": finalization_commit["version"],
            "status": finalization_commit["status"],
            "sha256": finalization_commit_sha256,
        },
        "candidate_permit_sha256": permit_digest,
        "candidate_receipt_path": str(normalized_path),
        "candidate_receipt_sha256": receipt_digest,
        "image_build_receipt_sha256": image_digest,
        "image_build_permit_sha256": record["image_build_permit_sha256"],
        "epoch_started_ms": record["epoch_started_ms"],
        "qualification_certificate_sha256": record[
            "qualification_certificate_sha256"
        ],
    }


def _existing_permit_is_absent_or_trusted(
    now: datetime, *, permit_mode: str = API_PERMIT_MODE
) -> None:
    try:
        _read_permit_body(
            now=now,
            require_current=False,
            permit_mode=permit_mode,
        )
    except PermitError as exc:
        if str(exc) == "vexp_mutation_permit_unavailable":
            try:
                os.stat(PERMIT_PATH, follow_symlinks=False)
            except FileNotFoundError:
                return
            except OSError as stat_exc:
                raise PermitError("vexp_mutation_permit_target_untrusted") from stat_exc
        raise


def _invalidate_permit_commit(*, required: bool) -> str | None:
    try:
        raw, _metadata = _trusted_read(
            PERMIT_COMMIT_PATH,
            expected_mode=PERMIT_COMMIT_MODE,
            expected_uid=ROOT_UID,
            expected_gid=ROOT_GID,
            max_bytes=MAX_VEXP_MUTATION_PERMIT_COMMIT_BYTES,
            reason_prefix="vexp_mutation_permit_commit",
        )
    except PermitError as exc:
        if str(exc) != "vexp_mutation_permit_commit_unavailable":
            raise
        try:
            os.stat(PERMIT_COMMIT_PATH, follow_symlinks=False)
        except FileNotFoundError:
            if required:
                raise
            return None
        except OSError as stat_exc:
            raise PermitError(
                "vexp_mutation_permit_commit_target_untrusted"
            ) from stat_exc
        raise
    digest = hashlib.sha256(raw).hexdigest()
    try:
        os.unlink(PERMIT_COMMIT_PATH)
    except OSError as exc:
        raise PermitError(
            "vexp_mutation_permit_commit_invalidation_failed"
        ) from exc
    _fsync_directory(PERMIT_COMMIT_PATH.parent)
    return digest


def _invalidate_permit_body(*, required: bool) -> str | None:
    try:
        raw, _metadata = _trusted_read(
            PERMIT_PATH,
            expected_mode=PERMIT_MODE,
            expected_uid=ROOT_UID,
            expected_gid=ROOT_GID,
            max_bytes=MAX_VEXP_MUTATION_PERMIT_BYTES,
            reason_prefix="vexp_mutation_permit",
        )
    except PermitError as exc:
        if str(exc) != "vexp_mutation_permit_unavailable":
            raise
        try:
            os.stat(PERMIT_PATH, follow_symlinks=False)
        except FileNotFoundError:
            if required:
                raise
            return None
        except OSError as stat_exc:
            raise PermitError(
                "vexp_mutation_permit_target_untrusted"
            ) from stat_exc
        raise
    digest = hashlib.sha256(raw).hexdigest()
    try:
        os.unlink(PERMIT_PATH)
    except OSError as exc:
        raise PermitError("vexp_mutation_permit_invalidation_failed") from exc
    _fsync_directory(PERMIT_PATH.parent)
    return digest


def _epoch_void_payload(
    state: Mapping[str, Any],
    *,
    state_path: Path,
    state_owner_uid: int,
    state_sha256: str,
    voided_at: datetime,
    maintenance_manifest_sha256: str,
    reviewed_revision: str,
) -> dict[str, object]:
    return {
        "contract_name": VEXP_EPOCH_VOID_CONTRACT_NAME,
        "version": VEXP_EPOCH_VOID_VERSION,
        "status": "void",
        "epoch_started_at": state.get("epoch_started_at"),
        "epoch_started_ms": state.get("epoch_started_ms"),
        "sentinel_state_path": str(state_path),
        "sentinel_state_owner_uid": state_owner_uid,
        "sentinel_state_sha256": state_sha256,
        "voided_at": _format_utc_timestamp(voided_at),
        "reason": VEXP_RECOVERY_REASON,
        "maintenance_manifest_path": str(RECOVERY_MANIFEST_PATH),
        "maintenance_manifest_sha256": maintenance_manifest_sha256,
        "reviewed_revision": reviewed_revision,
    }


def _validate_epoch_void(
    payload: Mapping[str, Any],
    *,
    state: Mapping[str, Any],
    state_path: Path,
    state_owner_uid: int,
    expected_state_sha256: str | None,
    maintenance_manifest_sha256: str,
    reviewed_revision: str,
) -> None:
    reason = "vexp_epoch_void_record_invalid"
    if (
        set(payload) != VEXP_EPOCH_VOID_KEYS
        or payload.get("contract_name") != VEXP_EPOCH_VOID_CONTRACT_NAME
        or type(payload.get("version")) is not int
        or payload["version"] != VEXP_EPOCH_VOID_VERSION
        or payload.get("status") != "void"
        or payload.get("epoch_started_at") != state.get("epoch_started_at")
        or payload.get("epoch_started_ms") != state.get("epoch_started_ms")
        or payload.get("sentinel_state_path") != str(state_path)
        or type(payload.get("sentinel_state_owner_uid")) is not int
        or payload["sentinel_state_owner_uid"] != state_owner_uid
        or not isinstance(payload.get("sentinel_state_sha256"), str)
        or not SHA256_PATTERN.fullmatch(payload["sentinel_state_sha256"])
        or (
            expected_state_sha256 is not None
            and payload["sentinel_state_sha256"] != expected_state_sha256
        )
        or payload.get("reason") != VEXP_RECOVERY_REASON
        or payload.get("maintenance_manifest_path")
        != str(RECOVERY_MANIFEST_PATH)
        or payload.get("maintenance_manifest_sha256")
        != maintenance_manifest_sha256
        or payload.get("reviewed_revision") != reviewed_revision
    ):
        raise PermitError(reason)
    _parse_utc_timestamp(payload.get("voided_at"), reason=reason)


def _read_epoch_void(
    entry: Path,
    *,
    state: Mapping[str, Any],
    state_path: Path,
    state_owner_uid: int,
    maintenance_manifest_sha256: str,
    reviewed_revision: str,
) -> tuple[dict[str, Any], str]:
    raw, _metadata = _trusted_read(
        entry,
        expected_mode=EPOCH_VOID_LEDGER_ENTRY_MODE,
        expected_uid=EPOCH_VOID_LEDGER_OWNER_UID,
        expected_gid=EPOCH_VOID_LEDGER_OWNER_GID,
        max_bytes=MAX_VEXP_EPOCH_VOID_LEDGER_ENTRY_BYTES,
        reason_prefix="vexp_epoch_void_record",
    )
    payload = _decode_guard_json(raw, reason="vexp_epoch_void_record_invalid")
    _validate_epoch_void(
        payload,
        state=state,
        state_path=state_path,
        state_owner_uid=state_owner_uid,
        expected_state_sha256=None,
        maintenance_manifest_sha256=maintenance_manifest_sha256,
        reviewed_revision=reviewed_revision,
    )
    return payload, hashlib.sha256(raw).hexdigest()


def _rename_noreplace(source: Path, destination: Path) -> None:
    """Atomically publish one same-directory path without replacement.

    Epoch voids are permanent records.  A check-then-rename sequence is not
    sufficient because plain rename may replace an entry created between the
    check and publication.  Linux renameat2 with RENAME_NOREPLACE provides the
    required single-operation create-or-EEXIST contract for both files and the
    recovery-only ledger-directory bootstrap.
    """

    if (
        not source.is_absolute()
        or not destination.is_absolute()
        or source.parent != destination.parent
        or source == destination
        or ".." in source.parts
        or ".." in destination.parts
    ):
        raise PermitError("vexp_epoch_void_record_publish_paths_invalid")
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        renameat2 = libc.renameat2
    except (AttributeError, OSError) as exc:
        raise PermitError(
            "vexp_epoch_void_record_rename_noreplace_unavailable"
        ) from exc
    renameat2.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    renameat2.restype = ctypes.c_int
    ctypes.set_errno(0)
    result = renameat2(
        AT_FDCWD,
        os.fsencode(source),
        AT_FDCWD,
        os.fsencode(destination),
        RENAME_NOREPLACE,
    )
    if result == 0:
        return
    observed_errno = ctypes.get_errno()
    if observed_errno == errno.EEXIST:
        raise FileExistsError(
            observed_errno,
            os.strerror(observed_errno),
            str(destination),
        )
    if observed_errno in (errno.ENOSYS, errno.EINVAL):
        raise PermitError(
            "vexp_epoch_void_record_rename_noreplace_unavailable"
        )
    raise OSError(
        observed_errno,
        os.strerror(observed_errno),
        str(destination),
    )


def _write_epoch_void_file(path: Path, encoded: bytes) -> None:
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | os.O_CLOEXEC
        | os.O_NOFOLLOW
        | os.O_NONBLOCK
    )
    descriptor = -1
    completed = False
    try:
        descriptor = os.open(path, flags, 0o600)
        os.fchmod(descriptor, EPOCH_VOID_LEDGER_ENTRY_MODE)
        os.fchown(
            descriptor,
            EPOCH_VOID_LEDGER_OWNER_UID,
            EPOCH_VOID_LEDGER_OWNER_GID,
        )
        written = 0
        while written < len(encoded):
            count = os.write(descriptor, encoded[written:])
            if count <= 0:
                raise PermitError("vexp_epoch_void_record_write_failed")
            written += count
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        observed, _metadata = _trusted_read(
            path,
            expected_mode=EPOCH_VOID_LEDGER_ENTRY_MODE,
            expected_uid=EPOCH_VOID_LEDGER_OWNER_UID,
            expected_gid=EPOCH_VOID_LEDGER_OWNER_GID,
            max_bytes=MAX_VEXP_EPOCH_VOID_LEDGER_ENTRY_BYTES,
            reason_prefix="vexp_epoch_void_record_prepublication",
        )
        if observed != encoded:
            raise PermitError("vexp_epoch_void_record_prepublication_mismatch")
        completed = True
    except PermitError:
        raise
    except OSError as exc:
        raise PermitError("vexp_epoch_void_record_write_failed") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if not completed:
            try:
                os.unlink(path)
            except OSError:
                pass


def _epoch_void_encoded_payload(
    state: Mapping[str, Any],
    *,
    state_path: Path,
    state_owner_uid: int,
    state_sha256: str,
    maintenance_manifest_sha256: str,
    reviewed_revision: str,
    now: datetime,
) -> tuple[dict[str, object], bytes]:
    payload = _epoch_void_payload(
        state,
        state_path=state_path,
        state_owner_uid=state_owner_uid,
        state_sha256=state_sha256,
        voided_at=now,
        maintenance_manifest_sha256=maintenance_manifest_sha256,
        reviewed_revision=reviewed_revision,
    )
    _validate_epoch_void(
        payload,
        state=state,
        state_path=state_path,
        state_owner_uid=state_owner_uid,
        expected_state_sha256=state_sha256,
        maintenance_manifest_sha256=maintenance_manifest_sha256,
        reviewed_revision=reviewed_revision,
    )
    encoded = (
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    if not 0 < len(encoded) <= MAX_VEXP_EPOCH_VOID_LEDGER_ENTRY_BYTES:
        raise PermitError("vexp_epoch_void_record_size_invalid")
    return payload, encoded


def _atomic_publish_epoch_void(
    state: Mapping[str, Any],
    *,
    state_path: Path,
    state_owner_uid: int,
    state_sha256: str,
    maintenance_manifest_sha256: str,
    reviewed_revision: str,
    now: datetime,
) -> tuple[dict[str, Any], str, bool]:
    if (
        not EPOCH_VOID_LEDGER_ROOT.is_absolute()
        or EPOCH_VOID_LEDGER_ROOT.parent == EPOCH_VOID_LEDGER_ROOT
        or ".." in EPOCH_VOID_LEDGER_ROOT.parts
    ):
        raise PermitError("vexp_epoch_void_ledger_root_untrusted")
    entry = EPOCH_VOID_LEDGER_ROOT / f"{state['epoch_started_ms']}.json"
    if entry.parent != EPOCH_VOID_LEDGER_ROOT:
        raise PermitError("vexp_epoch_void_record_path_invalid")

    payload, encoded = _epoch_void_encoded_payload(
        state,
        state_path=state_path,
        state_owner_uid=state_owner_uid,
        state_sha256=state_sha256,
        maintenance_manifest_sha256=maintenance_manifest_sha256,
        reviewed_revision=reviewed_revision,
        now=now,
    )

    try:
        root_metadata = _validate_trusted_directory(
            EPOCH_VOID_LEDGER_ROOT,
            expected_mode=EPOCH_VOID_LEDGER_DIRECTORY_MODE,
            expected_uid=EPOCH_VOID_LEDGER_OWNER_UID,
            expected_gid=EPOCH_VOID_LEDGER_OWNER_GID,
            reason="vexp_epoch_void_ledger_root_untrusted",
        )
    except PermitError as exc:
        try:
            os.stat(EPOCH_VOID_LEDGER_ROOT, follow_symlinks=False)
        except FileNotFoundError:
            return _atomic_bootstrap_epoch_void_ledger(
                state,
                state_path=state_path,
                state_owner_uid=state_owner_uid,
                state_sha256=state_sha256,
                maintenance_manifest_sha256=maintenance_manifest_sha256,
                reviewed_revision=reviewed_revision,
                payload=payload,
                encoded=encoded,
            )
        except OSError as stat_exc:
            raise PermitError("vexp_epoch_void_ledger_root_untrusted") from stat_exc
        raise exc

    try:
        os.stat(entry, follow_symlinks=False)
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise PermitError("vexp_epoch_void_record_untrusted") from exc
    else:
        payload, digest = _read_epoch_void(
            entry,
            state=state,
            state_path=state_path,
            state_owner_uid=state_owner_uid,
            maintenance_manifest_sha256=maintenance_manifest_sha256,
            reviewed_revision=reviewed_revision,
        )
        final_root_metadata = _validate_trusted_directory(
            EPOCH_VOID_LEDGER_ROOT,
            expected_mode=EPOCH_VOID_LEDGER_DIRECTORY_MODE,
            expected_uid=EPOCH_VOID_LEDGER_OWNER_UID,
            expected_gid=EPOCH_VOID_LEDGER_OWNER_GID,
            reason="vexp_epoch_void_ledger_root_untrusted",
        )
        if (
            final_root_metadata.st_dev != root_metadata.st_dev
            or final_root_metadata.st_ino != root_metadata.st_ino
        ):
            raise PermitError("vexp_epoch_void_ledger_root_changed")
        return payload, digest, False

    temporary = entry.with_name(
        f".{entry.name}.tmp.{os.getpid()}.{secrets.token_hex(8)}"
    )
    published = False
    try:
        _write_epoch_void_file(temporary, encoded)
        _fsync_directory(EPOCH_VOID_LEDGER_ROOT)
        try:
            _rename_noreplace(temporary, entry)
        except FileExistsError:
            existing_payload, existing_digest = _read_epoch_void(
                entry,
                state=state,
                state_path=state_path,
                state_owner_uid=state_owner_uid,
                maintenance_manifest_sha256=maintenance_manifest_sha256,
                reviewed_revision=reviewed_revision,
            )
            final_root_metadata = _validate_trusted_directory(
                EPOCH_VOID_LEDGER_ROOT,
                expected_mode=EPOCH_VOID_LEDGER_DIRECTORY_MODE,
                expected_uid=EPOCH_VOID_LEDGER_OWNER_UID,
                expected_gid=EPOCH_VOID_LEDGER_OWNER_GID,
                reason="vexp_epoch_void_ledger_root_untrusted",
            )
            if (
                final_root_metadata.st_dev != root_metadata.st_dev
                or final_root_metadata.st_ino != root_metadata.st_ino
            ):
                raise PermitError("vexp_epoch_void_ledger_root_changed")
            return existing_payload, existing_digest, False
        except OSError as exc:
            raise PermitError("vexp_epoch_void_record_publish_failed") from exc
        published = True
        _fsync_directory(EPOCH_VOID_LEDGER_ROOT)
        final_raw, _final_metadata = _trusted_read(
            entry,
            expected_mode=EPOCH_VOID_LEDGER_ENTRY_MODE,
            expected_uid=EPOCH_VOID_LEDGER_OWNER_UID,
            expected_gid=EPOCH_VOID_LEDGER_OWNER_GID,
            max_bytes=MAX_VEXP_EPOCH_VOID_LEDGER_ENTRY_BYTES,
            reason_prefix="vexp_epoch_void_record",
        )
        if final_raw != encoded:
            raise PermitError("vexp_epoch_void_record_postpublication_mismatch")
        final_root_metadata = _validate_trusted_directory(
            EPOCH_VOID_LEDGER_ROOT,
            expected_mode=EPOCH_VOID_LEDGER_DIRECTORY_MODE,
            expected_uid=EPOCH_VOID_LEDGER_OWNER_UID,
            expected_gid=EPOCH_VOID_LEDGER_OWNER_GID,
            reason="vexp_epoch_void_ledger_root_untrusted",
        )
        if final_root_metadata.st_dev != root_metadata.st_dev or (
            final_root_metadata.st_ino != root_metadata.st_ino
        ):
            raise PermitError("vexp_epoch_void_ledger_root_changed")
    except PermitError:
        raise
    except OSError as exc:
        raise PermitError("vexp_epoch_void_record_write_failed") from exc
    finally:
        if not published:
            try:
                os.unlink(temporary)
            except OSError:
                pass
    return payload, hashlib.sha256(encoded).hexdigest(), True


def _atomic_bootstrap_epoch_void_ledger(
    state: Mapping[str, Any],
    *,
    state_path: Path,
    state_owner_uid: int,
    state_sha256: str,
    maintenance_manifest_sha256: str,
    reviewed_revision: str,
    payload: dict[str, object],
    encoded: bytes,
) -> tuple[dict[str, Any], str, bool]:
    """Install an absent ledger with its first durable void already inside.

    The recovery transaction must not expose an empty canonical ledger even
    briefly.  Build a private sibling directory, fsync the exact record and
    directory, set final metadata, then atomically rename the whole directory
    into the canonical path with no-replace semantics.
    """

    parent = EPOCH_VOID_LEDGER_ROOT.parent
    try:
        parent_metadata = os.stat(parent, follow_symlinks=False)
    except OSError as exc:
        raise PermitError("vexp_epoch_void_ledger_parent_untrusted") from exc
    if (
        not stat.S_ISDIR(parent_metadata.st_mode)
        or parent_metadata.st_uid != ROOT_UID
        or parent_metadata.st_gid != ROOT_GID
        or stat.S_IMODE(parent_metadata.st_mode) & 0o022
    ):
        raise PermitError("vexp_epoch_void_ledger_parent_untrusted")

    entry_name = f"{state['epoch_started_ms']}.json"
    temporary_root = parent / (
        f".{EPOCH_VOID_LEDGER_ROOT.name}.bootstrap."
        f"{os.getpid()}.{secrets.token_hex(8)}"
    )
    temporary_entry = temporary_root / entry_name
    published = False
    created_root = False
    staged_root_metadata: os.stat_result | None = None
    try:
        os.mkdir(temporary_root, 0o700)
        created_root = True
        os.chown(
            temporary_root,
            EPOCH_VOID_LEDGER_OWNER_UID,
            EPOCH_VOID_LEDGER_OWNER_GID,
        )
        _write_epoch_void_file(temporary_entry, encoded)
        os.chmod(temporary_root, EPOCH_VOID_LEDGER_DIRECTORY_MODE)
        _fsync_directory(temporary_root)
        staged_root_metadata = os.stat(temporary_root, follow_symlinks=False)
        _fsync_directory(parent)
        try:
            _rename_noreplace(temporary_root, EPOCH_VOID_LEDGER_ROOT)
        except FileExistsError:
            existing_root_metadata = _validate_trusted_directory(
                EPOCH_VOID_LEDGER_ROOT,
                expected_mode=EPOCH_VOID_LEDGER_DIRECTORY_MODE,
                expected_uid=EPOCH_VOID_LEDGER_OWNER_UID,
                expected_gid=EPOCH_VOID_LEDGER_OWNER_GID,
                reason="vexp_epoch_void_ledger_root_untrusted",
            )
            entry = EPOCH_VOID_LEDGER_ROOT / entry_name
            existing_payload, existing_digest = _read_epoch_void(
                entry,
                state=state,
                state_path=state_path,
                state_owner_uid=state_owner_uid,
                maintenance_manifest_sha256=maintenance_manifest_sha256,
                reviewed_revision=reviewed_revision,
            )
            final_existing_root_metadata = _validate_trusted_directory(
                EPOCH_VOID_LEDGER_ROOT,
                expected_mode=EPOCH_VOID_LEDGER_DIRECTORY_MODE,
                expected_uid=EPOCH_VOID_LEDGER_OWNER_UID,
                expected_gid=EPOCH_VOID_LEDGER_OWNER_GID,
                reason="vexp_epoch_void_ledger_root_untrusted",
            )
            if (
                final_existing_root_metadata.st_dev
                != existing_root_metadata.st_dev
                or final_existing_root_metadata.st_ino
                != existing_root_metadata.st_ino
            ):
                raise PermitError("vexp_epoch_void_ledger_root_changed")
            return existing_payload, existing_digest, False
        except OSError as exc:
            raise PermitError("vexp_epoch_void_ledger_bootstrap_failed") from exc
        published = True
        _fsync_directory(parent)
        final_root_metadata = _validate_trusted_directory(
            EPOCH_VOID_LEDGER_ROOT,
            expected_mode=EPOCH_VOID_LEDGER_DIRECTORY_MODE,
            expected_uid=EPOCH_VOID_LEDGER_OWNER_UID,
            expected_gid=EPOCH_VOID_LEDGER_OWNER_GID,
            reason="vexp_epoch_void_ledger_root_untrusted",
        )
        if (
            staged_root_metadata is None
            or final_root_metadata.st_dev != staged_root_metadata.st_dev
            or final_root_metadata.st_ino != staged_root_metadata.st_ino
        ):
            raise PermitError("vexp_epoch_void_ledger_bootstrap_changed")
        final_entry = EPOCH_VOID_LEDGER_ROOT / entry_name
        final_raw, _metadata = _trusted_read(
            final_entry,
            expected_mode=EPOCH_VOID_LEDGER_ENTRY_MODE,
            expected_uid=EPOCH_VOID_LEDGER_OWNER_UID,
            expected_gid=EPOCH_VOID_LEDGER_OWNER_GID,
            max_bytes=MAX_VEXP_EPOCH_VOID_LEDGER_ENTRY_BYTES,
            reason_prefix="vexp_epoch_void_record",
        )
        if final_raw != encoded:
            raise PermitError("vexp_epoch_void_record_postpublication_mismatch")
        stable_root_metadata = _validate_trusted_directory(
            EPOCH_VOID_LEDGER_ROOT,
            expected_mode=EPOCH_VOID_LEDGER_DIRECTORY_MODE,
            expected_uid=EPOCH_VOID_LEDGER_OWNER_UID,
            expected_gid=EPOCH_VOID_LEDGER_OWNER_GID,
            reason="vexp_epoch_void_ledger_root_untrusted",
        )
        try:
            final_parent_metadata = os.stat(parent, follow_symlinks=False)
        except OSError as exc:
            raise PermitError("vexp_epoch_void_ledger_parent_changed") from exc
        if (
            stable_root_metadata.st_dev != final_root_metadata.st_dev
            or stable_root_metadata.st_ino != final_root_metadata.st_ino
            or final_parent_metadata.st_dev != parent_metadata.st_dev
            or final_parent_metadata.st_ino != parent_metadata.st_ino
            or final_parent_metadata.st_uid != parent_metadata.st_uid
            or final_parent_metadata.st_gid != parent_metadata.st_gid
            or stat.S_IMODE(final_parent_metadata.st_mode)
            != stat.S_IMODE(parent_metadata.st_mode)
        ):
            raise PermitError("vexp_epoch_void_ledger_parent_changed")
        return payload, hashlib.sha256(final_raw).hexdigest(), True
    except PermitError:
        raise
    except OSError as exc:
        raise PermitError("vexp_epoch_void_ledger_bootstrap_failed") from exc
    finally:
        if created_root and not published:
            try:
                os.unlink(temporary_entry)
            except OSError:
                pass
            try:
                os.rmdir(temporary_root)
            except OSError:
                pass


def _atomic_publish_permit_commit(
    permit: Mapping[str, Any], *, permit_sha256: str
) -> tuple[dict[str, object], str]:
    payload = _permit_commit_payload(
        permit, permit_sha256=permit_sha256
    )
    _validate_permit_commit(
        payload, permit=permit, permit_sha256=permit_sha256
    )
    encoded = (
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    if not 0 < len(encoded) <= MAX_VEXP_MUTATION_PERMIT_COMMIT_BYTES:
        raise PermitError("vexp_mutation_permit_commit_size_invalid")
    temporary = PERMIT_COMMIT_PATH.with_name(
        f".{PERMIT_COMMIT_PATH.name}.tmp.{os.getpid()}.{secrets.token_hex(8)}"
    )
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | os.O_CLOEXEC
        | os.O_NOFOLLOW
        | os.O_NONBLOCK
    )
    descriptor = -1
    published = False
    committed = False
    try:
        descriptor = os.open(temporary, flags, 0o600)
        os.fchmod(descriptor, PERMIT_COMMIT_MODE)
        os.fchown(descriptor, ROOT_UID, ROOT_GID)
        written = 0
        while written < len(encoded):
            count = os.write(descriptor, encoded[written:])
            if count <= 0:
                raise PermitError("vexp_mutation_permit_commit_write_failed")
            written += count
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        observed, _metadata = _trusted_read(
            temporary,
            expected_mode=PERMIT_COMMIT_MODE,
            expected_uid=ROOT_UID,
            expected_gid=ROOT_GID,
            max_bytes=MAX_VEXP_MUTATION_PERMIT_COMMIT_BYTES,
            reason_prefix="vexp_mutation_permit_commit_prepublication",
        )
        if observed != encoded:
            raise PermitError(
                "vexp_mutation_permit_commit_prepublication_mismatch"
            )
        _fsync_directory(PERMIT_COMMIT_PATH.parent)
        try:
            os.replace(temporary, PERMIT_COMMIT_PATH)
            published = True
        except OSError as exc:
            try:
                final_raw, _final_metadata = _trusted_read(
                    PERMIT_COMMIT_PATH,
                    expected_mode=PERMIT_COMMIT_MODE,
                    expected_uid=ROOT_UID,
                    expected_gid=ROOT_GID,
                    max_bytes=MAX_VEXP_MUTATION_PERMIT_COMMIT_BYTES,
                    reason_prefix="vexp_mutation_permit_commit",
                )
            except PermitError:
                _invalidate_permit_commit(required=False)
                raise PermitError(
                    "vexp_mutation_permit_commit_publish_failed"
                ) from exc
            if final_raw != encoded:
                _invalidate_permit_commit(required=True)
                raise PermitError(
                    "vexp_mutation_permit_commit_publish_failed"
                ) from exc
            published = True
        _fsync_directory(PERMIT_COMMIT_PATH.parent)
        final_raw, _final_metadata = _trusted_read(
            PERMIT_COMMIT_PATH,
            expected_mode=PERMIT_COMMIT_MODE,
            expected_uid=ROOT_UID,
            expected_gid=ROOT_GID,
            max_bytes=MAX_VEXP_MUTATION_PERMIT_COMMIT_BYTES,
            reason_prefix="vexp_mutation_permit_commit",
        )
        if final_raw != encoded:
            raise PermitError(
                "vexp_mutation_permit_commit_postpublication_mismatch"
            )
        committed = True
    except (PermitError, OSError) as exc:
        try:
            _invalidate_permit_commit(required=published)
        except PermitError as rollback_exc:
            raise PermitError(
                "vexp_mutation_permit_commit_rollback_failed"
            ) from rollback_exc
        if isinstance(exc, PermitError):
            raise
        raise PermitError("vexp_mutation_permit_commit_write_failed") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if not committed:
            try:
                os.unlink(temporary)
            except OSError:
                pass
    if not committed:
        raise PermitError("vexp_mutation_permit_commit_not_committed")
    return payload, hashlib.sha256(encoded).hexdigest()


def _atomic_write_permit(
    payload: Mapping[str, object],
    *,
    now: datetime,
    permit_mode: str = API_PERMIT_MODE,
) -> str:
    _existing_permit_is_absent_or_trusted(now, permit_mode=permit_mode)
    encoded = (
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")
    if not 0 < len(encoded) <= MAX_VEXP_MUTATION_PERMIT_BYTES:
        raise PermitError("vexp_mutation_permit_size_invalid")
    temporary = PERMIT_PATH.with_name(
        f".{PERMIT_PATH.name}.tmp.{os.getpid()}.{secrets.token_hex(8)}"
    )
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | os.O_CLOEXEC
        | os.O_NOFOLLOW
        | os.O_NONBLOCK
    )
    descriptor = -1
    replaced = False
    try:
        descriptor = os.open(temporary, flags, 0o600)
        os.fchmod(descriptor, PERMIT_MODE)
        os.fchown(descriptor, ROOT_UID, ROOT_GID)
        written = 0
        while written < len(encoded):
            count = os.write(descriptor, encoded[written:])
            if count <= 0:
                raise PermitError("vexp_mutation_permit_write_failed")
            written += count
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.replace(temporary, PERMIT_PATH)
        replaced = True
        _fsync_directory(PERMIT_PATH.parent)
    except PermitError:
        raise
    except OSError as exc:
        raise PermitError("vexp_mutation_permit_write_failed") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if not replaced:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            except OSError:
                pass
    raw, _metadata = _trusted_read(
        PERMIT_PATH,
        expected_mode=PERMIT_MODE,
        expected_uid=ROOT_UID,
        expected_gid=ROOT_GID,
        max_bytes=MAX_VEXP_MUTATION_PERMIT_BYTES,
        reason_prefix="vexp_mutation_permit",
    )
    if raw != encoded:
        raise PermitError("vexp_mutation_permit_postwrite_mismatch")
    return hashlib.sha256(raw).hexdigest()


def _remove_just_written_permit(
    *,
    expected_sha256: str,
    now: datetime,
    permit_mode: str = API_PERMIT_MODE,
) -> None:
    _permit, observed_sha256 = _read_permit_body(
        now=now,
        require_current=False,
        permit_mode=permit_mode,
    )
    if observed_sha256 != expected_sha256:
        raise PermitError("vexp_mutation_permit_postwrite_cleanup_target_changed")
    try:
        os.unlink(PERMIT_PATH)
    except OSError as exc:
        raise PermitError("vexp_mutation_permit_postwrite_cleanup_failed") from exc
    _fsync_directory(PERMIT_PATH.parent)


def _validate_state_arguments(*, state_path: Path, state_owner_uid: int) -> None:
    if not state_path.is_absolute():
        raise PermitError("vexp_sentinel_state_path_not_absolute")
    if state_owner_uid < 0:
        raise PermitError("vexp_sentinel_state_owner_uid_invalid")


def _canonical_sentinel_state_path(owner_uid: int) -> Path:
    try:
        account_home = Path(pwd.getpwuid(owner_uid).pw_dir)
    except KeyError as exc:
        raise PermitError("vexp_sentinel_state_owner_unknown") from exc
    if not account_home.is_absolute() or ".." in account_home.parts:
        raise PermitError("vexp_sentinel_state_account_home_invalid")
    return account_home / ".local/state/vexp-sentinel/state.json"


def _require_canonical_sentinel_state_path(
    *, state_path: Path, state_owner_uid: int
) -> None:
    if state_path != _canonical_sentinel_state_path(state_owner_uid):
        raise PermitError("vexp_mutation_permit_canonical_sentinel_state_required")


def _require_root() -> None:
    if os.geteuid() != ROOT_UID:
        raise PermitError("vexp_mutation_permit_root_required")


def void_epoch(
    *,
    state_path: Path,
    state_owner_uid: int,
    reviewed_revision: str,
) -> dict[str, object]:
    """Irrevocably void the active epoch before reviewed plumbing recovery.

    This command grants no recovery or mutation authority.  It only waits for
    every shared mutation lease to drain, records a permanent exact-epoch void
    under the exclusive coordination lock, and invalidates any derived permit.
    """

    _verify_trusted_execution_path()
    _require_root()
    _validate_state_arguments(state_path=state_path, state_owner_uid=state_owner_uid)
    if state_path != _canonical_sentinel_state_path(state_owner_uid):
        raise PermitError("vexp_recovery_canonical_sentinel_state_required")
    if not GIT_COMMIT_PATTERN.fullmatch(reviewed_revision):
        raise PermitError("vexp_recovery_reviewed_revision_invalid")
    # Validate every operator-selected input and the root-owned recovery manifest
    # before the recovery command can create or alter any guarded plumbing.
    _initial_state, _initial_state_sha256 = _read_state_with_sha256(
        state_path, owner_uid=state_owner_uid
    )
    _initial_manifest, initial_manifest_sha256 = _read_recovery_manifest(
        reviewed_revision=reviewed_revision
    )

    def publish_void() -> tuple[
        dict[str, Any], str, bool, dict[str, Any], str
    ]:
        state, state_sha256 = _read_state_with_sha256(
            state_path, owner_uid=state_owner_uid
        )
        _manifest, manifest_sha256 = _read_recovery_manifest(
            reviewed_revision=reviewed_revision
        )
        if manifest_sha256 != initial_manifest_sha256:
            raise PermitError("vexp_recovery_manifest_changed_before_void")
        now = _require_utc_clock(_utc_now_datetime())
        record, record_sha256, created = _atomic_publish_epoch_void(
            state,
            state_path=state_path,
            state_owner_uid=state_owner_uid,
            state_sha256=state_sha256,
            maintenance_manifest_sha256=manifest_sha256,
            reviewed_revision=reviewed_revision,
            now=now,
        )
        final_state = _read_state(state_path, owner_uid=state_owner_uid)
        if final_state.get("epoch_started_ms") != state.get("epoch_started_ms"):
            raise PermitError("vexp_sentinel_epoch_changed_during_void")
        return record, record_sha256, created, state, manifest_sha256

    try:
        os.stat(LOCK_PATH, follow_symlinks=False)
    except FileNotFoundError:
        # A missing coordination lock means no conforming consumer can hold a
        # mutation lease.  Recovery may therefore publish the durable void as
        # its first mutation, but only when no permit body/commit can exist.
        try:
            os.stat(PERMIT_PATH.parent, follow_symlinks=False)
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise PermitError("vexp_mutation_runtime_directory_untrusted") from exc
        else:
            _validate_runtime_directory(PERMIT_PATH.parent)
        for authority_path in (PERMIT_PATH, PERMIT_COMMIT_PATH):
            try:
                os.stat(authority_path, follow_symlinks=False)
            except FileNotFoundError:
                continue
            except OSError as exc:
                raise PermitError(
                    "vexp_recovery_lockless_authority_untrusted"
                ) from exc
            raise PermitError("vexp_recovery_lockless_authority_present")
        record, record_sha256, created, state, manifest_sha256 = publish_void()
        for authority_path in (LOCK_PATH, PERMIT_PATH, PERMIT_COMMIT_PATH):
            try:
                os.stat(authority_path, follow_symlinks=False)
            except FileNotFoundError:
                continue
            except OSError as exc:
                raise PermitError(
                    "vexp_recovery_authority_appeared_during_lockless_void"
                ) from exc
            raise PermitError(
                "vexp_recovery_authority_appeared_during_lockless_void"
            )
        commit_sha256 = None
        permit_sha256 = None
    except OSError as exc:
        raise PermitError("vexp_mutation_permit_lock_untrusted") from exc
    else:
        _validate_runtime_directory(PERMIT_PATH.parent)
        with _authority_lock(exclusive=True, create=False, wait=True):
            record, record_sha256, created, state, manifest_sha256 = publish_void()
            commit_sha256 = _invalidate_permit_commit(required=False)
            permit_sha256 = _invalidate_permit_body(required=False)
    return {
        "status": "voided",
        "authority_granted": False,
        "epoch_started_at": record["epoch_started_at"],
        "epoch_started_ms": record["epoch_started_ms"],
        "epoch_void_record": {
            "path": str(
                EPOCH_VOID_LEDGER_ROOT / f"{record['epoch_started_ms']}.json"
            ),
            "sha256": record_sha256,
            "created": created,
        },
        "maintenance_manifest": {
            "path": str(RECOVERY_MANIFEST_PATH),
            "sha256": manifest_sha256,
            "reviewed_revision": reviewed_revision,
        },
        "permit_commit_invalidated_sha256": commit_sha256,
        "permit_invalidated_sha256": permit_sha256,
    }


def issue(
    *,
    state_path: Path,
    state_owner_uid: int,
    ttl_seconds: int,
    permit_mode: str = API_PERMIT_MODE,
) -> dict[str, object]:
    _verify_trusted_execution_path()
    _require_root()
    _validate_state_arguments(state_path=state_path, state_owner_uid=state_owner_uid)
    _require_canonical_sentinel_state_path(
        state_path=state_path,
        state_owner_uid=state_owner_uid,
    )
    if not MIN_TTL_SECONDS <= ttl_seconds <= MAX_TTL_SECONDS:
        raise PermitError("vexp_mutation_permit_ttl_invalid")
    initial_now = _utc_now_datetime()
    initial_state, _initial_state_sha256 = _read_state_with_sha256(
        state_path, owner_uid=state_owner_uid
    )
    _validate_terminal_state(initial_state, now=initial_now)
    _require_epoch_not_voided(initial_state)
    initial_candidate_evidence_manifest: dict[str, object] | None = None
    if permit_mode == CANDIDATE_PERMIT_MODE:
        _validate_candidate_authority_ledger()
        initial_candidate_evidence_manifest = (
            _read_candidate_evidence_producer_manifest()
        )
    _ensure_runtime_directory()
    candidate_issuance: dict[str, object] | None = None
    with _authority_lock(exclusive=True, create=True):
        _invalidate_permit_commit(required=False)
        now = _utc_now_datetime()
        state, state_sha256 = _read_state_with_sha256(
            state_path, owner_uid=state_owner_uid
        )
        qualified_at = _validate_terminal_state(state, now=now)
        void_ledger = _require_epoch_not_voided(state)
        certificate, qualification_certificate = (
            _read_qualification_certificate(state)
        )
        prewrite_state, prewrite_state_sha256 = _read_state_with_sha256(
            state_path, owner_uid=state_owner_uid
        )
        _validate_terminal_state(prewrite_state, now=now)
        _require_epoch_not_voided(prewrite_state)
        if _terminal_identity(prewrite_state) != _terminal_identity(state):
            raise PermitError("vexp_sentinel_terminal_identity_changed")
        prewrite_certificate, prewrite_qualification_certificate = (
            _read_qualification_certificate(prewrite_state)
        )
        if prewrite_qualification_certificate != qualification_certificate:
            raise PermitError("vexp_qualification_certificate_changed")
        current_predicate = _read_current_predicate_evidence(
            state=prewrite_state,
            state_sha256=prewrite_state_sha256,
            state_path=state_path,
            state_owner_uid=state_owner_uid,
            certificate=prewrite_certificate,
            qualification_certificate=prewrite_qualification_certificate,
            now=now,
        )
        candidate_evidence_manifest: dict[str, object] | None = None
        if permit_mode == CANDIDATE_PERMIT_MODE:
            candidate_evidence_manifest = (
                _read_candidate_evidence_producer_manifest()
            )
            if candidate_evidence_manifest != initial_candidate_evidence_manifest:
                raise PermitError(
                    "vexp_candidate_evidence_readiness_changed_before_issue"
                )
        payload = _permit_payload(
            prewrite_state,
            qualification_certificate=qualification_certificate,
            now=now,
            ttl_seconds=ttl_seconds,
            permit_mode=permit_mode,
            candidate_evidence_manifest=candidate_evidence_manifest,
        )
        _validate_permit(
            payload,
            now=now,
            require_current=True,
            permit_mode=permit_mode,
        )
        _validate_permit_certificate_binding(payload, qualification_certificate)
        permit_sha256 = _atomic_write_permit(
            payload,
            now=now,
            permit_mode=permit_mode,
        )
        postwrite_now = _utc_now_datetime()
        try:
            postwrite_state, postwrite_state_sha256 = _read_state_with_sha256(
                state_path, owner_uid=state_owner_uid
            )
            _validate_terminal_state(postwrite_state, now=postwrite_now)
            _require_epoch_not_voided(postwrite_state)
            if _terminal_identity(postwrite_state) != _terminal_identity(
                prewrite_state
            ):
                raise PermitError("vexp_sentinel_terminal_identity_changed")
            postwrite_certificate_body, postwrite_certificate = (
                _read_qualification_certificate(postwrite_state)
            )
            if postwrite_certificate != qualification_certificate:
                raise PermitError("vexp_qualification_certificate_changed")
            _validate_permit_certificate_binding(payload, postwrite_certificate)
            postwrite_predicate = _read_current_predicate_evidence(
                state=postwrite_state,
                state_sha256=postwrite_state_sha256,
                state_path=state_path,
                state_owner_uid=state_owner_uid,
                certificate=postwrite_certificate_body,
                qualification_certificate=postwrite_certificate,
                now=postwrite_now,
            )
            if postwrite_predicate != current_predicate:
                raise PermitError("vexp_current_predicate_changed_during_issue")
            if permit_mode == CANDIDATE_PERMIT_MODE and (
                _read_candidate_evidence_producer_manifest()
                != candidate_evidence_manifest
            ):
                raise PermitError(
                    "vexp_candidate_evidence_readiness_changed_during_issue"
                )
        except PermitError:
            _remove_just_written_permit(
                expected_sha256=permit_sha256,
                now=postwrite_now,
                permit_mode=permit_mode,
            )
            raise
        try:
            commit, commit_sha256 = _atomic_publish_permit_commit(
                payload, permit_sha256=permit_sha256
            )
        except PermitError:
            _remove_just_written_permit(
                expected_sha256=permit_sha256,
                now=_utc_now_datetime(),
                permit_mode=permit_mode,
            )
            raise
        if permit_mode == CANDIDATE_PERMIT_MODE:
            try:
                (
                    _issuance_record,
                    issuance_record_sha256,
                    issuance_created,
                ) = _publish_candidate_issuance_record(
                    permit=payload,
                    permit_sha256=permit_sha256,
                    permit_commit=commit,
                    permit_commit_sha256=commit_sha256,
                    state_path=state_path,
                    state_owner_uid=state_owner_uid,
                    epoch_void_ledger=void_ledger,
                    current_predicate=current_predicate,
                    recorded_at=_utc_now_datetime(),
                )
                if (
                    _read_candidate_evidence_producer_manifest()
                    != candidate_evidence_manifest
                ):
                    raise PermitError(
                        "vexp_candidate_evidence_readiness_changed_after_issue"
                    )
            except PermitError:
                invalidated_commit_sha256 = _invalidate_permit_commit(required=True)
                if invalidated_commit_sha256 != commit_sha256:
                    raise PermitError(
                        "vexp_candidate_issuance_rollback_commit_changed"
                    )
                _remove_just_written_permit(
                    expected_sha256=permit_sha256,
                    now=_utc_now_datetime(),
                    permit_mode=permit_mode,
                )
                raise
            candidate_issuance = {
                "contract_name": VEXP_CANDIDATE_PERMIT_ISSUANCE_CONTRACT_NAME,
                "version": VEXP_CANDIDATE_PERMIT_ISSUANCE_VERSION,
                "path": str(
                    _candidate_authority_record_path(
                        CANDIDATE_AUTHORITY_ISSUANCE_DIRECTORY,
                        permit_sha256,
                    )
                ),
                "sha256": issuance_record_sha256,
                "created": issuance_created,
            }
    result: dict[str, object] = {
        "status": "issued",
        "contract_name": payload["contract_name"],
        "epoch_started_ms": prewrite_state["epoch_started_ms"],
        "qualified_at": _format_utc_timestamp(qualified_at),
        "expires_at": payload["expires_at"],
        "terminal_identity_sha256": payload["terminal_identity_sha256"],
        "qualification_certificate_schema": qualification_certificate["schema"],
        "qualification_certificate_sha256": qualification_certificate["sha256"],
        "qualification_certificate_identity": qualification_certificate["identity"],
        "qualification_certificate_event_hash": qualification_certificate[
            "event_hash"
        ],
        "permit_sha256": permit_sha256,
        "permit_commit": {
            "contract_name": commit["contract_name"],
            "version": commit["version"],
            "status": commit["status"],
            "sha256": commit_sha256,
        },
        "epoch_void_ledger": void_ledger,
        "current_predicate": current_predicate,
    }
    if candidate_issuance is not None:
        result["candidate_issuance"] = candidate_issuance
    if candidate_evidence_manifest is not None:
        result["candidate_evidence"] = {
            "attestor_sha256": candidate_evidence_manifest["attestor_sha256"],
            "producer_manifest_sha256": candidate_evidence_manifest[
                "_manifest_sha256"
            ],
        }
    return result


def status(
    *,
    state_path: Path,
    state_owner_uid: int,
    permit_mode: str = API_PERMIT_MODE,
) -> dict[str, object]:
    _verify_trusted_execution_path()
    _validate_state_arguments(state_path=state_path, state_owner_uid=state_owner_uid)
    _require_canonical_sentinel_state_path(
        state_path=state_path,
        state_owner_uid=state_owner_uid,
    )
    _validate_runtime_directory(PERMIT_PATH.parent)
    with _authority_lock(exclusive=False, create=False):
        now = _utc_now_datetime()
        state, state_sha256 = _read_state_with_sha256(
            state_path, owner_uid=state_owner_uid
        )
        _validate_terminal_state(state, now=now)
        void_ledger = _require_epoch_not_voided(state)
        permit, permit_sha256, commit, commit_sha256 = _read_committed_permit(
            now=now,
            require_current=True,
            permit_mode=permit_mode,
        )
        candidate_issuance: tuple[dict[str, Any], str] | None = None
        candidate_evidence_manifest: dict[str, object] | None = None
        if permit_mode == CANDIDATE_PERMIT_MODE:
            candidate_evidence_manifest = (
                _read_candidate_evidence_producer_manifest()
            )
            if (
                permit.get("candidate_boundary_attestor_sha256")
                != candidate_evidence_manifest.get("attestor_sha256")
                or permit.get("candidate_evidence_producer_manifest_sha256")
                != candidate_evidence_manifest.get("_manifest_sha256")
            ):
                raise PermitError(
                    "vexp_candidate_evidence_readiness_binding_mismatch"
                )
            candidate_issuance = _read_candidate_issuance_record(permit_sha256)
            issuance_record, _issuance_sha256 = candidate_issuance
            if (
                issuance_record.get("permit") != permit
                or issuance_record.get("permit_commit") != commit
                or issuance_record.get("permit_commit_sha256") != commit_sha256
                or issuance_record.get("epoch_void_ledger") != void_ledger
            ):
                raise PermitError("vexp_candidate_issuance_binding_mismatch")
        if _terminal_identity(permit) != _terminal_identity(state):
            raise PermitError("vexp_mutation_permit_state_binding_mismatch")
        certificate, qualification_certificate = (
            _read_qualification_certificate(state)
        )
        current_predicate = _read_current_predicate_evidence(
            state=state,
            state_sha256=state_sha256,
            state_path=state_path,
            state_owner_uid=state_owner_uid,
            certificate=certificate,
            qualification_certificate=qualification_certificate,
            now=now,
        )
        _validate_permit_certificate_binding(permit, qualification_certificate)
        final_now = _utc_now_datetime()
        final_state, final_state_sha256 = _read_state_with_sha256(
            state_path, owner_uid=state_owner_uid
        )
        _validate_terminal_state(final_state, now=final_now)
        final_void_ledger = _require_epoch_not_voided(final_state)
        if _terminal_identity(final_state) != _terminal_identity(state):
            raise PermitError("vexp_sentinel_terminal_identity_changed")
        final_certificate, final_qualification_certificate = (
            _read_qualification_certificate(final_state)
        )
        final_current_predicate = _read_current_predicate_evidence(
            state=final_state,
            state_sha256=final_state_sha256,
            state_path=state_path,
            state_owner_uid=state_owner_uid,
            certificate=final_certificate,
            qualification_certificate=final_qualification_certificate,
            now=final_now,
        )
        (
            final_permit,
            final_permit_sha256,
            final_commit,
            final_commit_sha256,
        ) = _read_committed_permit(
            now=final_now,
            require_current=True,
            permit_mode=permit_mode,
        )
        if (
            final_permit != permit
            or final_permit_sha256 != permit_sha256
            or final_commit != commit
            or final_commit_sha256 != commit_sha256
            or final_void_ledger != void_ledger
            or final_current_predicate != current_predicate
        ):
            raise PermitError("vexp_mutation_authority_changed_during_status")
        if candidate_issuance is not None:
            final_candidate_issuance = _read_candidate_issuance_record(
                permit_sha256
            )
            if final_candidate_issuance != candidate_issuance:
                raise PermitError(
                    "vexp_candidate_issuance_changed_during_status"
                )
            if (
                _read_candidate_evidence_producer_manifest()
                != candidate_evidence_manifest
            ):
                raise PermitError(
                    "vexp_candidate_evidence_readiness_changed_during_status"
                )
        if _terminal_identity(permit) != _terminal_identity(final_state):
            raise PermitError("vexp_mutation_permit_state_binding_mismatch")
        if final_qualification_certificate != qualification_certificate:
            raise PermitError("vexp_qualification_certificate_changed")
        _validate_permit_certificate_binding(
            permit, final_qualification_certificate
        )
    result: dict[str, object] = {
        "status": "valid",
        "contract_name": permit["contract_name"],
        "epoch_started_ms": permit["epoch_started_ms"],
        "qualified_at": permit["qualified_at"],
        "issued_at": permit["issued_at"],
        "expires_at": permit["expires_at"],
        "terminal_identity_sha256": permit["terminal_identity_sha256"],
        "qualification_certificate_schema": permit[
            "qualification_certificate_schema"
        ],
        "qualification_certificate_sha256": permit[
            "qualification_certificate_sha256"
        ],
        "qualification_certificate_identity": permit[
            "qualification_certificate_identity"
        ],
        "qualification_certificate_event_hash": permit[
            "qualification_certificate_event_hash"
        ],
        "permit_sha256": permit_sha256,
        "permit_commit": {
            "contract_name": commit["contract_name"],
            "version": commit["version"],
            "status": commit["status"],
            "sha256": commit_sha256,
        },
        "epoch_void_ledger": void_ledger,
        "current_predicate": current_predicate,
        "mutation_boundaries": permit["mutation_boundaries"],
    }
    if candidate_evidence_manifest is not None:
        result["candidate_evidence"] = {
            "attestor_sha256": candidate_evidence_manifest["attestor_sha256"],
            "producer_manifest_sha256": candidate_evidence_manifest[
                "_manifest_sha256"
            ],
        }
    return result


def revoke(*, permit_mode: str = API_PERMIT_MODE) -> dict[str, object]:
    _verify_trusted_execution_path()
    _require_root()
    now = _utc_now_datetime()
    _validate_runtime_directory(PERMIT_PATH.parent)
    with _authority_lock(exclusive=True, create=False):
        _permit, permit_sha256, _commit, commit_sha256 = _read_committed_permit(
            now=now,
            require_current=False,
            permit_mode=permit_mode,
        )
        invalidated_commit_sha256 = _invalidate_permit_commit(required=True)
        if invalidated_commit_sha256 != commit_sha256:
            raise PermitError(
                "vexp_mutation_permit_commit_changed_before_revoke"
            )
        try:
            os.unlink(PERMIT_PATH)
        except OSError as exc:
            raise PermitError("vexp_mutation_permit_revoke_failed") from exc
        _fsync_directory(PERMIT_PATH.parent)
    return {
        "status": "revoked",
        "permit_sha256": permit_sha256,
        "permit_commit_sha256": commit_sha256,
        "permit_commit_invalidated": True,
    }


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Manage the root-owned exact-epoch Manfred mutation permit."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    issue_parser = subparsers.add_parser("issue")
    issue_parser.add_argument("--state-path", required=True, type=Path)
    issue_parser.add_argument("--state-owner-uid", required=True, type=int)
    issue_parser.add_argument("--ttl-seconds", type=int, default=900)
    issue_parser.add_argument(
        "--permit-mode",
        choices=PERMIT_MODES,
        default=API_PERMIT_MODE,
    )
    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--state-path", required=True, type=Path)
    status_parser.add_argument("--state-owner-uid", required=True, type=int)
    status_parser.add_argument(
        "--permit-mode",
        choices=PERMIT_MODES,
        default=API_PERMIT_MODE,
    )
    seal_parser = subparsers.add_parser("seal-candidate")
    seal_parser.add_argument("--state-path", required=True, type=Path)
    seal_parser.add_argument("--state-owner-uid", required=True, type=int)
    seal_parser.add_argument("--candidate-receipt", required=True, type=Path)
    seal_parser.add_argument("--candidate-receipt-sha256", required=True)
    seal_status_parser = subparsers.add_parser("candidate-seal-status")
    seal_status_parser.add_argument("--candidate-permit-sha256", required=True)
    seal_status_parser.add_argument("--candidate-receipt", required=True, type=Path)
    seal_status_parser.add_argument("--candidate-receipt-sha256", required=True)
    seal_status_parser.add_argument("--image-build-receipt-sha256", required=True)
    revoke_parser = subparsers.add_parser("revoke")
    revoke_parser.add_argument(
        "--permit-mode",
        choices=PERMIT_MODES,
        default=API_PERMIT_MODE,
    )
    void_parser = subparsers.add_parser("void-epoch")
    void_parser.add_argument("--state-path", required=True, type=Path)
    void_parser.add_argument("--state-owner-uid", required=True, type=int)
    void_parser.add_argument("--reviewed-revision", required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        if args.command == "issue":
            result = issue(
                state_path=args.state_path,
                state_owner_uid=args.state_owner_uid,
                ttl_seconds=args.ttl_seconds,
                permit_mode=args.permit_mode,
            )
        elif args.command == "status":
            result = status(
                state_path=args.state_path,
                state_owner_uid=args.state_owner_uid,
                permit_mode=args.permit_mode,
            )
        elif args.command == "seal-candidate":
            result = seal_candidate(
                state_path=args.state_path,
                state_owner_uid=args.state_owner_uid,
                candidate_receipt_path=args.candidate_receipt,
                candidate_receipt_sha256=args.candidate_receipt_sha256,
            )
        elif args.command == "candidate-seal-status":
            result = candidate_seal_status(
                candidate_permit_sha256=args.candidate_permit_sha256,
                candidate_receipt_path=args.candidate_receipt,
                candidate_receipt_sha256=args.candidate_receipt_sha256,
                image_build_receipt_sha256=args.image_build_receipt_sha256,
            )
        elif args.command == "revoke":
            result = revoke(permit_mode=args.permit_mode)
        else:
            result = void_epoch(
                state_path=args.state_path,
                state_owner_uid=args.state_owner_uid,
                reviewed_revision=args.reviewed_revision,
            )
    except PermitError as exc:
        print(f"permit_error:{exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
