#!/usr/bin/env python3
"""Build and verify a non-authoritative vexp root-maintenance handoff request.

This module reads only Git objects and a local operator-authorization artifact.
It cannot install root plumbing, operate systemd, call Docker, void an epoch,
issue a certificate or permit, or mutate live EA.  Those actions remain owned by
an external root actor and require the receipts described by the request.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
from typing import Any, Final, Mapping, Sequence


ROOT: Final = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST_PATH: Final = (
    "config/vexp_root_maintenance_recovery_request.v1.json"
)
MANIFEST_CONTRACT: Final = "ea.vexp_root_maintenance_recovery_manifest.v1"
REQUEST_CONTRACT: Final = "ea.vexp_root_maintenance_recovery_request.v1"
OPERATOR_AUTHORIZATION_CONTRACT: Final = (
    "ea.vexp_root_maintenance_operator_authorization.v1"
)
REQUEST_VERSION: Final = 1
MINIMUM_QUALIFICATION_DURATION_MS: Final = 604_800_000
MAX_JSON_BYTES: Final = 1024 * 1024
MAX_OPERATOR_AUTHORIZATION_BYTES: Final = 64 * 1024
MAX_SENTINEL_STATE_BYTES: Final = 1024 * 1024
MAX_REVIEWED_BLOB_BYTES: Final = 2 * 1024 * 1024
SHA256_RE: Final = re.compile(r"^[0-9a-f]{64}$")
SHA256_IDENTITY_RE: Final = re.compile(r"^sha256:[0-9a-f]{64}$")
COMMIT_RE: Final = re.compile(r"^[0-9a-f]{40}$")
REFERENCE_RE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}$")
UTC_MS_TIMESTAMP_RE: Final = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"
)
UTC: Final = timezone.utc

MANIFEST_KEYS: Final = frozenset(
    {
        "authority",
        "contract_name",
        "external_owner_handoff",
        "guarded_plumbing",
        "guarded_plumbing_failure_policy",
        "post_recovery_qualification",
        "pre_change_epoch_void",
        "prohibited_effects",
        "reviewed_blob_paths",
        "scope",
        "version",
    }
)
REQUEST_KEYS: Final = frozenset(
    {
        "authority",
        "contract_name",
        "execution_observations",
        "external_owner_handoff",
        "guarded_plumbing",
        "guarded_plumbing_failure_policy",
        "operator_authorization",
        "operator_state_snapshot",
        "post_recovery_qualification",
        "pre_change_epoch_void",
        "prohibited_effects",
        "request_identity",
        "reviewed_blobs",
        "reviewed_commit",
        "source_manifest",
        "status",
        "version",
    }
)
OPERATOR_AUTHORIZATION_KEYS: Final = frozenset(
    {
        "authorization_id",
        "contract_name",
        "external_root_receipt_required",
        "manifest_path",
        "reviewed_commit",
        "root_execution_authority",
        "scope",
        "source_request_only",
        "version",
    }
)
ALLOWED_COMPONENT_ACTIONS: Final[dict[str, tuple[str, ...]]] = {
    "sentinel": (
        "install_exact_reviewed_artifact",
        "replace_exact_reviewed_artifact",
        "restore_manifest_bound_pre_change_artifact_after_failure",
        "start_named_unit",
        "restart_named_unit",
        "verify_identity",
    ),
    "qualification_finalizer": (
        "install_exact_reviewed_artifact",
        "replace_exact_reviewed_artifact",
        "restore_manifest_bound_pre_change_artifact_after_failure",
        "start_named_unit",
        "restart_named_unit",
        "verify_identity",
    ),
    "certificate_writer_plumbing": (
        "install_exact_reviewed_artifact",
        "replace_exact_reviewed_artifact",
        "restore_manifest_bound_pre_change_artifact_after_failure",
        "start_named_unit",
        "restart_named_unit",
        "verify_identity",
    ),
    "apparmor": (
        "install_exact_reviewed_artifact",
        "replace_exact_reviewed_artifact",
        "restore_manifest_bound_pre_change_artifact_after_failure",
        "reload_named_policy",
        "verify_identity",
    ),
    "event_guard": (
        "install_exact_reviewed_artifact",
        "replace_exact_reviewed_artifact",
        "restore_manifest_bound_pre_change_artifact_after_failure",
        "start_named_unit",
        "restart_named_unit",
        "verify_identity",
    ),
    "mutation_gate": (
        "install_exact_reviewed_artifact",
        "replace_exact_reviewed_artifact",
        "restore_manifest_bound_pre_change_artifact_after_failure",
        "start_named_unit",
        "restart_named_unit",
        "verify_identity",
    ),
    "current_predicate_attestor": (
        "install_exact_reviewed_artifact",
        "replace_exact_reviewed_artifact",
        "restore_manifest_bound_pre_change_artifact_after_failure",
        "start_named_unit",
        "restart_named_unit",
        "verify_identity",
    ),
    "candidate_boundary_attestor": (
        "install_exact_reviewed_artifact",
        "replace_exact_reviewed_artifact",
        "restore_manifest_bound_pre_change_artifact_after_failure",
        "start_named_unit",
        "restart_named_unit",
        "verify_identity",
    ),
}
OPERATOR_STATE_SNAPSHOT_KEYS: Final = frozenset(
    {
        "certification_blocker_count",
        "certification_deferment_count",
        "current_resources_healthy",
        "epoch_started_at",
        "epoch_started_ms",
        "epoch_identity_sha256",
        "live_state_truth_established",
        "predicate_contract",
        "predicate_contract_sha256",
        "qualification_earliest_completion_at",
        "qualification_floor_valid",
        "qualification_phase",
        "qualified_at",
        "schema_observation_codes",
        "snapshot_content_included",
        "snapshot_sha256",
        "snapshot_size_bytes",
        "state_version",
        "trust_model",
        "updated_at",
    }
)
ALLOWED_CURRENT_QUALIFICATION_PHASES: Final = frozenset(
    {"enforced_soak", "qualified"}
)
PROHIBITED_EFFECTS: Final[tuple[str, ...]] = (
    "authority_restoring_rollback",
    "candidate_creation",
    "certificate_issuance",
    "docker_or_compose_mutation",
    "live_ea_mutation",
    "merge",
    "permit_issuance",
    "promotion",
)
AUTHORITY_DENIAL: Final[dict[str, bool]] = {
    "authority_restoring_rollback": False,
    "candidate": False,
    "certificate_issuance": False,
    "docker_or_compose": False,
    "live_ea_mutation": False,
    "merge": False,
    "permit_issuance": False,
    "promotion": False,
    "root_maintenance_execution": False,
}
EXECUTION_OBSERVATIONS: Final[dict[str, bool]] = {
    "certificate_or_permit_issued": False,
    "docker_or_compose_calls_performed": False,
    "external_root_receipt_present": False,
    "live_or_candidate_mutation_performed": False,
    "pre_change_epoch_void_receipt_present": False,
    "root_owned_state_truth_established": False,
    "systemd_calls_performed": False,
}
REVIEWED_BLOB_PATHS: Final[tuple[str, ...]] = (
    ".codex-design/repo/IMPLEMENTATION_SCOPE.md",
    "AGENTS.md",
    DEFAULT_MANIFEST_PATH,
    "docs/MANFRED_MEMORIAL_JOINT_DEPLOY_RUNBOOK.md",
    "docs/MANFRED_MEMORIAL_SCOPED_DEPLOY_RUNBOOK.md",
    "scripts/deploy_ea_memorial.py",
    "scripts/manage_manfred_vexp_mutation_permit.py",
    "scripts/manfred_candidate_vexp_authority.py",
    "scripts/materialize_vexp_root_maintenance_recovery_request.py",
    "scripts/materialize_vexp_sentinel_v6_floor_fix.py",
    "scripts/run_manfred_memorial_candidate.py",
    "scripts/verify_vexp_root_maintenance_recovery_request.py",
    "scripts/vexp_root_maintenance_recovery_request.py",
)


class RecoveryRequestError(RuntimeError):
    """Stable, content-free source-request denial."""


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _decode_json(raw: bytes, *, reason: str) -> dict[str, Any]:
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
        raise RecoveryRequestError(reason) from exc
    if not isinstance(payload, dict):
        raise RecoveryRequestError(reason)
    return payload


def _repo_path(value: object) -> str:
    if not isinstance(value, str) or not value or value.startswith("/"):
        raise RecoveryRequestError("recovery_manifest_repo_path_invalid")
    path = Path(value)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise RecoveryRequestError("recovery_manifest_repo_path_invalid")
    if path.as_posix() != value:
        raise RecoveryRequestError("recovery_manifest_repo_path_invalid")
    return value


def _git(repo_root: Path, args: Sequence[str], *, reason: str) -> bytes:
    command = [
        "git",
        "-c",
        f"safe.directory={repo_root}",
        "-C",
        str(repo_root),
        *args,
    ]
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
        )
    except OSError as exc:
        raise RecoveryRequestError(reason) from exc
    if result.returncode != 0:
        raise RecoveryRequestError(reason)
    return bytes(result.stdout)


def _resolve_reviewed_commit(repo_root: Path, reviewed_commit: str) -> str:
    if not COMMIT_RE.fullmatch(reviewed_commit):
        raise RecoveryRequestError("recovery_reviewed_commit_invalid")
    resolved = _git(
        repo_root,
        ["rev-parse", "--verify", f"{reviewed_commit}^{{commit}}"],
        reason="recovery_reviewed_commit_unavailable",
    ).decode("ascii", errors="strict").strip()
    if resolved != reviewed_commit:
        raise RecoveryRequestError("recovery_reviewed_commit_not_exact")
    return resolved


def _git_blob(repo_root: Path, reviewed_commit: str, path: str) -> bytes:
    selected_path = _repo_path(path)
    return _git(
        repo_root,
        ["cat-file", "blob", f"{reviewed_commit}:{selected_path}"],
        reason="recovery_reviewed_blob_unavailable",
    )


def _expected_guarded_plumbing() -> list[dict[str, object]]:
    return [
        {
            "allowed_actions": list(actions),
            "component": component,
        }
        for component, actions in ALLOWED_COMPONENT_ACTIONS.items()
    ]


def _expected_pre_change_void() -> dict[str, object]:
    return {
        "active_epoch_and_derived_authority_irrevocably_void": True,
        "actual_state_owner_must_match_trusted_sentinel_owner": True,
        "atomic_root_actor_pre_change_state_capture_required": True,
        "durable_root_owned_receipt_required": True,
        "hand_edits_forbidden": True,
        "must_bind_atomic_pre_change_state_sha256": True,
        "must_match_operator_snapshot_epoch_identity_sha256": True,
        "must_precede_first_guarded_change": True,
        "receipt_contract_name": (
            "fleet.vexp_qualification_epoch_void_receipt.v1"
        ),
        "receipt_must_be_signed": True,
        "stable_no_follow_actual_state_read_required": True,
    }


def _expected_guarded_plumbing_failure_policy() -> dict[str, object]:
    return {
        "authority_restoration_forbidden": True,
        "epoch_void_remains_permanent": True,
        "plumbing_rollback_allowed_after_durable_void": True,
        "pre_change_artifact_manifest_required": True,
        "rollback_must_be_recorded_in_root_receipt": True,
        "rollback_must_use_pre_change_artifact_manifest": True,
        "rollback_scope": "guarded_plumbing_only",
    }


def _expected_post_recovery() -> dict[str, object]:
    return {
        "certificate_schema": "ea.vexp_qualification_certificate.v2",
        "certification_blockers": [],
        "certification_deferments": [],
        "current_resources_healthy": True,
        "independent_root_finalizer_required": True,
        "minimum_monotonic_duration_ms": MINIMUM_QUALIFICATION_DURATION_MS,
        "minimum_wall_duration_ms": MINIMUM_QUALIFICATION_DURATION_MS,
        "permit_contract_version": 2,
        "permit_may_be_issued_only_after_certificate_validation": True,
        "separate_root_permit_manager_required": True,
        "state_version": 6,
        "strictly_newer_epoch_required": True,
    }


def _expected_external_handoff() -> dict[str, object]:
    return {
        "finalizer_implementation_location": "external_owner_required",
        "external_pre_change_authorization_required": True,
        "owner_plane": "fleet",
        "reason": (
            "ea_must_not_own_release_authority_or_hidden_contract_packages"
        ),
        "required": True,
        "request_grants_root_execution_authority": False,
        "root_receipt_is_post_execution_evidence": True,
        "required_root_receipt": {
            "contract_name": (
                "fleet.vexp_root_maintenance_recovery_receipt.v1"
            ),
            "must_be_root_owned": True,
            "must_be_signed": True,
            "must_bind_atomic_pre_change_state_sha256": True,
            "must_bind_exact_artifact_manifest_sha256": True,
            "must_bind_new_epoch_identity": True,
            "must_bind_pre_change_void_receipt_sha256": True,
            "must_bind_pre_change_artifact_manifest_sha256": True,
            "must_bind_request_identity": True,
            "must_bind_operator_snapshot_epoch_identity_sha256": True,
            "must_record_actual_state_owner_uid": True,
            "must_record_first_change_after_void": True,
            "must_record_plumbing_rollback_disposition": True,
            "signature_algorithm": "ed25519",
        },
    }


def validate_source_manifest(payload: Mapping[str, Any]) -> None:
    if set(payload) != MANIFEST_KEYS:
        raise RecoveryRequestError("recovery_manifest_schema_invalid")
    if payload.get("contract_name") != MANIFEST_CONTRACT:
        raise RecoveryRequestError("recovery_manifest_contract_invalid")
    if type(payload.get("version")) is not int or payload["version"] != 1:
        raise RecoveryRequestError("recovery_manifest_version_invalid")
    if payload.get("scope") != "source_only_external_root_handoff":
        raise RecoveryRequestError("recovery_manifest_scope_invalid")
    if payload.get("authority") is not False:
        raise RecoveryRequestError("recovery_manifest_authority_invalid")
    if payload.get("guarded_plumbing") != _expected_guarded_plumbing():
        raise RecoveryRequestError("recovery_manifest_guarded_plumbing_invalid")
    if payload.get(
        "guarded_plumbing_failure_policy"
    ) != _expected_guarded_plumbing_failure_policy():
        raise RecoveryRequestError(
            "recovery_manifest_guarded_plumbing_failure_policy_invalid"
        )
    if payload.get("pre_change_epoch_void") != _expected_pre_change_void():
        raise RecoveryRequestError("recovery_manifest_epoch_void_invalid")
    if payload.get("post_recovery_qualification") != _expected_post_recovery():
        raise RecoveryRequestError("recovery_manifest_qualification_invalid")
    if payload.get("prohibited_effects") != list(PROHIBITED_EFFECTS):
        raise RecoveryRequestError("recovery_manifest_prohibited_effects_invalid")
    if payload.get("external_owner_handoff") != _expected_external_handoff():
        raise RecoveryRequestError("recovery_manifest_external_handoff_invalid")
    paths = payload.get("reviewed_blob_paths")
    if not isinstance(paths, list) or not paths:
        raise RecoveryRequestError("recovery_manifest_reviewed_blobs_invalid")
    normalized = [_repo_path(path) for path in paths]
    if normalized != sorted(set(normalized)):
        raise RecoveryRequestError("recovery_manifest_reviewed_blobs_invalid")
    if normalized != list(REVIEWED_BLOB_PATHS):
        raise RecoveryRequestError("recovery_manifest_reviewed_blobs_invalid")


def _reviewed_source(
    repo_root: Path,
    reviewed_commit: str,
    manifest_path: str,
) -> tuple[dict[str, Any], bytes, list[dict[str, object]]]:
    resolved_commit = _resolve_reviewed_commit(repo_root, reviewed_commit)
    normalized_manifest_path = _repo_path(manifest_path)
    if normalized_manifest_path != DEFAULT_MANIFEST_PATH:
        raise RecoveryRequestError("recovery_manifest_path_invalid")
    manifest_raw = _git_blob(repo_root, resolved_commit, normalized_manifest_path)
    if not 0 < len(manifest_raw) <= MAX_JSON_BYTES:
        raise RecoveryRequestError("recovery_manifest_size_invalid")
    manifest = _decode_json(
        manifest_raw, reason="recovery_manifest_json_invalid"
    )
    validate_source_manifest(manifest)
    if normalized_manifest_path not in manifest["reviewed_blob_paths"]:
        raise RecoveryRequestError("recovery_manifest_self_binding_missing")
    reviewed_blobs: list[dict[str, object]] = []
    for path in manifest["reviewed_blob_paths"]:
        raw = _git_blob(repo_root, resolved_commit, str(path))
        if not 0 < len(raw) <= MAX_REVIEWED_BLOB_BYTES:
            raise RecoveryRequestError("recovery_reviewed_blob_size_invalid")
        reviewed_blobs.append(
            {
                "path": path,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "size_bytes": len(raw),
            }
        )
    return manifest, manifest_raw, reviewed_blobs


def _stable_regular_read(
    path: Path,
    *,
    max_bytes: int,
    reason: str,
    expected_mode: int | None = None,
    expected_uid: int | None = None,
) -> bytes:
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_NONBLOCK"):
        raise RecoveryRequestError(f"{reason}_safe_open_unavailable")
    descriptor = -1
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK,
        )
        before = os.fstat(descriptor)
    except OSError as exc:
        raise RecoveryRequestError(f"{reason}_unavailable") from exc
    try:
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or not 0 < before.st_size <= max_bytes
            or (
                expected_mode is not None
                and stat.S_IMODE(before.st_mode) != expected_mode
            )
            or (expected_uid is not None and before.st_uid != expected_uid)
        ):
            raise RecoveryRequestError(f"{reason}_untrusted")
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = -1
            raw = handle.read(max_bytes + 1)
            after = os.fstat(handle.fileno())
    except OSError as exc:
        raise RecoveryRequestError(f"{reason}_unavailable") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    try:
        path_after = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise RecoveryRequestError(f"{reason}_changed_during_read") from exc

    def identity(row: os.stat_result) -> tuple[int, ...]:
        return (
            row.st_dev,
            row.st_ino,
            row.st_mode,
            row.st_uid,
            row.st_gid,
            row.st_nlink,
            row.st_size,
            row.st_mtime_ns,
            row.st_ctime_ns,
        )

    if (
        len(raw) != before.st_size
        or len(raw) > max_bytes
        or identity(before) != identity(after)
        or identity(before) != identity(path_after)
    ):
        raise RecoveryRequestError(f"{reason}_changed_during_read")
    return raw


def _validate_operator_authorization(
    raw: bytes,
    *,
    reference: str,
    reviewed_commit: str,
) -> None:
    payload = _decode_json(
        raw, reason="recovery_operator_authorization_json_invalid"
    )
    if set(payload) != OPERATOR_AUTHORIZATION_KEYS:
        raise RecoveryRequestError("recovery_operator_authorization_schema_invalid")
    if payload.get("contract_name") != OPERATOR_AUTHORIZATION_CONTRACT:
        raise RecoveryRequestError("recovery_operator_authorization_contract_invalid")
    if type(payload.get("version")) is not int or payload["version"] != 1:
        raise RecoveryRequestError("recovery_operator_authorization_version_invalid")
    if (
        payload.get("authorization_id") != reference
        or payload.get("scope")
        != "schema_v6_qualification_plumbing_recovery"
        or payload.get("reviewed_commit") != reviewed_commit
        or payload.get("manifest_path") != DEFAULT_MANIFEST_PATH
        or payload.get("source_request_only") is not True
        or payload.get("root_execution_authority") is not False
        or payload.get("external_root_receipt_required") is not True
    ):
        raise RecoveryRequestError("recovery_operator_authorization_binding_invalid")


def _parse_utc_ms(value: object, *, reason: str) -> datetime:
    if not isinstance(value, str) or not UTC_MS_TIMESTAMP_RE.fullmatch(value):
        raise RecoveryRequestError(reason)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RecoveryRequestError(reason) from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise RecoveryRequestError(reason)
    return parsed.astimezone(UTC)


def _epoch_ms(value: datetime) -> int:
    delta = value - datetime(1970, 1, 1, tzinfo=UTC)
    return (
        delta.days * 86_400_000
        + delta.seconds * 1_000
        + delta.microseconds // 1_000
    )


def _operator_snapshot_epoch_identity(
    value: Mapping[str, object],
) -> dict[str, object]:
    return {
        "epoch_started_at": value.get("epoch_started_at"),
        "epoch_started_ms": value.get("epoch_started_ms"),
        "state_version": value.get("state_version", value.get("version")),
    }


def _operator_state_snapshot(raw: bytes) -> dict[str, object]:
    state = _decode_json(raw, reason="recovery_sentinel_state_json_invalid")
    if type(state.get("version")) is not int or state["version"] != 6:
        raise RecoveryRequestError("recovery_sentinel_state_version_invalid")
    epoch_started_at = _parse_utc_ms(
        state.get("epoch_started_at"),
        reason="recovery_sentinel_state_epoch_invalid",
    )
    epoch_started_ms = state.get("epoch_started_ms")
    if (
        type(epoch_started_ms) is not int
        or epoch_started_ms <= 0
        or _epoch_ms(epoch_started_at) != epoch_started_ms
    ):
        raise RecoveryRequestError("recovery_sentinel_state_epoch_invalid")
    earliest = _parse_utc_ms(
        state.get("qualification_earliest_completion_at"),
        reason="recovery_sentinel_state_earliest_completion_invalid",
    )
    floor_valid = (
        _epoch_ms(earliest)
        >= epoch_started_ms + MINIMUM_QUALIFICATION_DURATION_MS
    )
    observation_codes: list[str] = []
    if not floor_valid:
        observation_codes.append("qualification_floor_below_seven_days")
    phase = state.get("qualification_phase")
    if (
        not isinstance(phase, str)
        or phase not in ALLOWED_CURRENT_QUALIFICATION_PHASES
    ):
        raise RecoveryRequestError("recovery_sentinel_state_phase_invalid")
    qualified_at_value = state.get("qualified_at")
    qualified_at: datetime | None = None
    if qualified_at_value is not None:
        qualified_at = _parse_utc_ms(
            qualified_at_value,
            reason="recovery_sentinel_state_qualified_at_invalid",
        )
    if (
        (phase == "enforced_soak" and qualified_at is not None)
        or (phase == "qualified" and qualified_at is None)
    ):
        raise RecoveryRequestError("recovery_sentinel_state_phase_invalid")
    if qualified_at is not None and qualified_at < earliest:
        observation_codes.append("qualified_at_before_observed_floor")
    updated_at = _parse_utc_ms(
        state.get("updated_at"),
        reason="recovery_sentinel_state_updated_at_invalid",
    )
    if updated_at < epoch_started_at or (
        qualified_at is not None and updated_at < qualified_at
    ):
        raise RecoveryRequestError("recovery_sentinel_state_updated_at_invalid")
    if type(state.get("current_resources_healthy")) is not bool:
        raise RecoveryRequestError("recovery_sentinel_state_health_invalid")
    blockers = state.get("certification_blockers")
    deferments = state.get("certification_deferments")
    if not isinstance(blockers, list):
        raise RecoveryRequestError("recovery_sentinel_state_findings_invalid")
    deferment_count: int | None
    if isinstance(deferments, list):
        deferment_count = len(deferments)
    else:
        deferment_count = None
        observation_codes.append("certification_deferments_missing_or_invalid")
    predicate_contract = state.get("predicate_contract")
    if (
        not isinstance(predicate_contract, str)
        or not REFERENCE_RE.fullmatch(predicate_contract)
    ):
        predicate_contract = None
        observation_codes.append("predicate_contract_missing_or_invalid")
    predicate_contract_sha256 = state.get("predicate_contract_sha256")
    if (
        not isinstance(predicate_contract_sha256, str)
        or not SHA256_RE.fullmatch(predicate_contract_sha256)
    ):
        predicate_contract_sha256 = None
        observation_codes.append(
            "predicate_contract_sha256_missing_or_invalid"
        )
    snapshot: dict[str, object] = {
        "certification_blocker_count": len(blockers),
        "certification_deferment_count": deferment_count,
        "current_resources_healthy": state["current_resources_healthy"],
        "epoch_started_at": state["epoch_started_at"],
        "epoch_started_ms": epoch_started_ms,
        "live_state_truth_established": False,
        "predicate_contract": predicate_contract,
        "predicate_contract_sha256": predicate_contract_sha256,
        "qualification_earliest_completion_at": state[
            "qualification_earliest_completion_at"
        ],
        "qualification_floor_valid": floor_valid,
        "qualification_phase": phase,
        "qualified_at": qualified_at_value,
        "schema_observation_codes": observation_codes,
        "snapshot_content_included": False,
        "snapshot_sha256": hashlib.sha256(raw).hexdigest(),
        "snapshot_size_bytes": len(raw),
        "state_version": state["version"],
        "trust_model": "untrusted_operator_supplied_snapshot",
        "updated_at": state["updated_at"],
    }
    snapshot["epoch_identity_sha256"] = canonical_sha256(
        _operator_snapshot_epoch_identity(snapshot)
    )
    return snapshot


def _read_operator_state_snapshot(path: Path) -> dict[str, object]:
    raw = _stable_regular_read(
        Path(os.path.abspath(path)),
        max_bytes=MAX_SENTINEL_STATE_BYTES,
        reason="recovery_operator_state_snapshot",
        expected_mode=0o600,
        expected_uid=os.geteuid(),
    )
    return _operator_state_snapshot(raw)


def _validate_operator_state_snapshot(snapshot: object) -> dict[str, object]:
    if (
        not isinstance(snapshot, dict)
        or set(snapshot) != OPERATOR_STATE_SNAPSHOT_KEYS
        or snapshot.get("trust_model")
        != "untrusted_operator_supplied_snapshot"
        or snapshot.get("live_state_truth_established") is not False
        or snapshot.get("snapshot_content_included") is not False
        or type(snapshot.get("state_version")) is not int
        or snapshot["state_version"] != 6
        or type(snapshot.get("snapshot_size_bytes")) is not int
        or not 0 < snapshot["snapshot_size_bytes"] <= MAX_SENTINEL_STATE_BYTES
        or not isinstance(snapshot.get("snapshot_sha256"), str)
        or not SHA256_RE.fullmatch(snapshot["snapshot_sha256"])
        or type(snapshot.get("certification_blocker_count")) is not int
        or snapshot["certification_blocker_count"] < 0
        or (
            snapshot.get("certification_deferment_count") is not None
            and (
                type(snapshot["certification_deferment_count"]) is not int
                or snapshot["certification_deferment_count"] < 0
            )
        )
        or type(snapshot.get("current_resources_healthy")) is not bool
        or type(snapshot.get("qualification_floor_valid")) is not bool
        or not isinstance(snapshot.get("schema_observation_codes"), list)
    ):
        raise RecoveryRequestError(
            "recovery_request_operator_state_snapshot_invalid"
        )
    epoch_started_at = _parse_utc_ms(
        snapshot.get("epoch_started_at"),
        reason="recovery_request_operator_state_snapshot_invalid",
    )
    epoch_started_ms = snapshot.get("epoch_started_ms")
    if (
        type(epoch_started_ms) is not int
        or epoch_started_ms <= 0
        or _epoch_ms(epoch_started_at) != epoch_started_ms
    ):
        raise RecoveryRequestError(
            "recovery_request_operator_state_snapshot_invalid"
        )
    earliest = _parse_utc_ms(
        snapshot.get("qualification_earliest_completion_at"),
        reason="recovery_request_operator_state_snapshot_invalid",
    )
    floor_valid = (
        _epoch_ms(earliest)
        >= epoch_started_ms + MINIMUM_QUALIFICATION_DURATION_MS
    )
    expected_observations: list[str] = []
    if not floor_valid:
        expected_observations.append("qualification_floor_below_seven_days")
    phase = snapshot.get("qualification_phase")
    if (
        not isinstance(phase, str)
        or phase not in ALLOWED_CURRENT_QUALIFICATION_PHASES
    ):
        raise RecoveryRequestError(
            "recovery_request_operator_state_snapshot_invalid"
        )
    qualified_at_value = snapshot.get("qualified_at")
    qualified_at: datetime | None = None
    if qualified_at_value is not None:
        qualified_at = _parse_utc_ms(
            qualified_at_value,
            reason="recovery_request_operator_state_snapshot_invalid",
        )
    if (
        (phase == "enforced_soak" and qualified_at is not None)
        or (phase == "qualified" and qualified_at is None)
    ):
        raise RecoveryRequestError(
            "recovery_request_operator_state_snapshot_invalid"
        )
    if qualified_at is not None and qualified_at < earliest:
        expected_observations.append("qualified_at_before_observed_floor")
    updated_at = _parse_utc_ms(
        snapshot.get("updated_at"),
        reason="recovery_request_operator_state_snapshot_invalid",
    )
    if updated_at < epoch_started_at or (
        qualified_at is not None and updated_at < qualified_at
    ):
        raise RecoveryRequestError(
            "recovery_request_operator_state_snapshot_invalid"
        )
    predicate_contract = snapshot.get("predicate_contract")
    predicate_contract_sha256 = snapshot.get("predicate_contract_sha256")
    if snapshot.get("certification_deferment_count") is None:
        expected_observations.append(
            "certification_deferments_missing_or_invalid"
        )
    if predicate_contract is None:
        expected_observations.append("predicate_contract_missing_or_invalid")
    elif (
        not isinstance(predicate_contract, str)
        or not REFERENCE_RE.fullmatch(predicate_contract)
    ):
        raise RecoveryRequestError(
            "recovery_request_operator_state_snapshot_invalid"
        )
    if predicate_contract_sha256 is None:
        expected_observations.append(
            "predicate_contract_sha256_missing_or_invalid"
        )
    elif (
        not isinstance(predicate_contract_sha256, str)
        or not SHA256_RE.fullmatch(predicate_contract_sha256)
    ):
        raise RecoveryRequestError(
            "recovery_request_operator_state_snapshot_invalid"
        )
    if (
        snapshot.get("qualification_floor_valid") is not floor_valid
        or snapshot.get("schema_observation_codes") != expected_observations
        or snapshot.get("epoch_identity_sha256")
        != canonical_sha256(_operator_snapshot_epoch_identity(snapshot))
    ):
        raise RecoveryRequestError(
            "recovery_request_operator_state_snapshot_invalid"
        )
    return snapshot


def build_request(
    *,
    repo_root: Path,
    reviewed_commit: str,
    operator_authorization_path: Path,
    operator_authorization_reference: str,
    operator_state_snapshot_path: Path,
    manifest_path: str = DEFAULT_MANIFEST_PATH,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    if not COMMIT_RE.fullmatch(reviewed_commit):
        raise RecoveryRequestError("recovery_reviewed_commit_invalid")
    if not REFERENCE_RE.fullmatch(operator_authorization_reference):
        raise RecoveryRequestError("recovery_operator_authorization_reference_invalid")
    authorization_raw = _stable_regular_read(
        Path(os.path.abspath(operator_authorization_path)),
        max_bytes=MAX_OPERATOR_AUTHORIZATION_BYTES,
        reason="recovery_operator_authorization",
        expected_mode=0o600,
        expected_uid=os.geteuid(),
    )
    _validate_operator_authorization(
        authorization_raw,
        reference=operator_authorization_reference,
        reviewed_commit=reviewed_commit,
    )
    manifest, manifest_raw, reviewed_blobs = _reviewed_source(
        repo_root, reviewed_commit, manifest_path
    )
    operator_state_snapshot = _read_operator_state_snapshot(
        operator_state_snapshot_path
    )
    request: dict[str, Any] = {
        "authority": dict(AUTHORITY_DENIAL),
        "contract_name": REQUEST_CONTRACT,
        "execution_observations": dict(EXECUTION_OBSERVATIONS),
        "external_owner_handoff": manifest["external_owner_handoff"],
        "guarded_plumbing": manifest["guarded_plumbing"],
        "guarded_plumbing_failure_policy": manifest[
            "guarded_plumbing_failure_policy"
        ],
        "operator_authorization": {
            "content_included": False,
            "explicit_recovery_scope_required": True,
            "reference": operator_authorization_reference,
            "sha256": hashlib.sha256(authorization_raw).hexdigest(),
        },
        "operator_state_snapshot": operator_state_snapshot,
        "post_recovery_qualification": manifest[
            "post_recovery_qualification"
        ],
        "pre_change_epoch_void": manifest["pre_change_epoch_void"],
        "prohibited_effects": manifest["prohibited_effects"],
        "reviewed_blobs": reviewed_blobs,
        "reviewed_commit": reviewed_commit,
        "source_manifest": {
            "path": manifest_path,
            "sha256": hashlib.sha256(manifest_raw).hexdigest(),
            "size_bytes": len(manifest_raw),
        },
        "status": "blocked_external_root_receipt_required",
        "version": REQUEST_VERSION,
    }
    request["request_identity"] = f"sha256:{canonical_sha256(request)}"
    return request


def validate_request(
    payload: Mapping[str, Any],
    *,
    repo_root: Path,
) -> dict[str, object]:
    if set(payload) != REQUEST_KEYS:
        raise RecoveryRequestError("recovery_request_schema_invalid")
    if payload.get("contract_name") != REQUEST_CONTRACT:
        raise RecoveryRequestError("recovery_request_contract_invalid")
    if type(payload.get("version")) is not int or payload["version"] != 1:
        raise RecoveryRequestError("recovery_request_version_invalid")
    if payload.get("status") != "blocked_external_root_receipt_required":
        raise RecoveryRequestError("recovery_request_status_invalid")
    if payload.get("authority") != AUTHORITY_DENIAL:
        raise RecoveryRequestError("recovery_request_authority_invalid")
    if payload.get("execution_observations") != EXECUTION_OBSERVATIONS:
        raise RecoveryRequestError("recovery_request_observations_invalid")
    operator_state_snapshot = _validate_operator_state_snapshot(
        payload.get("operator_state_snapshot")
    )
    reviewed_commit = payload.get("reviewed_commit")
    if not isinstance(reviewed_commit, str):
        raise RecoveryRequestError("recovery_reviewed_commit_invalid")
    source_manifest = payload.get("source_manifest")
    if not isinstance(source_manifest, dict) or set(source_manifest) != {
        "path",
        "sha256",
        "size_bytes",
    }:
        raise RecoveryRequestError("recovery_request_source_manifest_invalid")
    manifest_path = _repo_path(source_manifest.get("path"))
    manifest, manifest_raw, reviewed_blobs = _reviewed_source(
        repo_root.resolve(), reviewed_commit, manifest_path
    )
    if source_manifest != {
        "path": manifest_path,
        "sha256": hashlib.sha256(manifest_raw).hexdigest(),
        "size_bytes": len(manifest_raw),
    }:
        raise RecoveryRequestError("recovery_request_source_manifest_invalid")
    if payload.get("reviewed_blobs") != reviewed_blobs:
        raise RecoveryRequestError("recovery_request_reviewed_blobs_invalid")
    for key in (
        "external_owner_handoff",
        "guarded_plumbing",
        "guarded_plumbing_failure_policy",
        "post_recovery_qualification",
        "pre_change_epoch_void",
        "prohibited_effects",
    ):
        if payload.get(key) != manifest[key]:
            raise RecoveryRequestError(f"recovery_request_{key}_invalid")
    authorization = payload.get("operator_authorization")
    if not isinstance(authorization, dict) or set(authorization) != {
        "content_included",
        "explicit_recovery_scope_required",
        "reference",
        "sha256",
    }:
        raise RecoveryRequestError("recovery_operator_authorization_invalid")
    if (
        authorization.get("content_included") is not False
        or authorization.get("explicit_recovery_scope_required") is not True
        or not isinstance(authorization.get("reference"), str)
        or not REFERENCE_RE.fullmatch(authorization["reference"])
        or not isinstance(authorization.get("sha256"), str)
        or not SHA256_RE.fullmatch(authorization["sha256"])
    ):
        raise RecoveryRequestError("recovery_operator_authorization_invalid")
    identity = payload.get("request_identity")
    if not isinstance(identity, str) or not SHA256_IDENTITY_RE.fullmatch(identity):
        raise RecoveryRequestError("recovery_request_identity_invalid")
    identity_payload = dict(payload)
    identity_payload.pop("request_identity", None)
    if identity != f"sha256:{canonical_sha256(identity_payload)}":
        raise RecoveryRequestError("recovery_request_identity_invalid")
    return {
        "authority": False,
        "external_owner_handoff_required": True,
        "external_root_receipt_present": False,
        "live_state_truth_established": False,
        "operator_snapshot_epoch_identity_sha256": operator_state_snapshot[
            "epoch_identity_sha256"
        ],
        "request_identity": identity,
        "status": "valid_non_authoritative_request",
    }


def write_new_private_json(path: Path, payload: Mapping[str, Any]) -> None:
    output = Path(os.path.abspath(path))
    try:
        parent = os.stat(output.parent, follow_symlinks=False)
    except OSError as exc:
        raise RecoveryRequestError("recovery_request_output_parent_unavailable") from exc
    if (
        not stat.S_ISDIR(parent.st_mode)
        or parent.st_uid != os.geteuid()
        or stat.S_IMODE(parent.st_mode) != 0o700
    ):
        raise RecoveryRequestError("recovery_request_output_parent_untrusted")
    raw = canonical_json_bytes(payload) + b"\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = -1
    try:
        descriptor = os.open(output, flags, 0o600)
        os.fchmod(descriptor, 0o600)
        written = 0
        while written < len(raw):
            count = os.write(descriptor, raw[written:])
            if count <= 0:
                raise OSError("short_write")
            written += count
        os.fsync(descriptor)
    except OSError as exc:
        raise RecoveryRequestError("recovery_request_output_write_failed") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    directory_fd = -1
    try:
        directory_fd = os.open(
            output.parent,
            os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_DIRECTORY", 0),
        )
        os.fsync(directory_fd)
    except OSError as exc:
        raise RecoveryRequestError("recovery_request_output_sync_failed") from exc
    finally:
        if directory_fd >= 0:
            os.close(directory_fd)


def load_and_validate_request(
    path: Path,
    *,
    repo_root: Path,
) -> tuple[dict[str, Any], dict[str, object]]:
    raw = _stable_regular_read(
        Path(os.path.abspath(path)),
        max_bytes=MAX_JSON_BYTES,
        reason="recovery_request",
        expected_mode=0o600,
        expected_uid=os.geteuid(),
    )
    payload = _decode_json(raw, reason="recovery_request_json_invalid")
    return payload, validate_request(payload, repo_root=repo_root)
