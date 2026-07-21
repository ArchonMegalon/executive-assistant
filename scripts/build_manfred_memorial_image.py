#!/usr/bin/env python3
from __future__ import annotations

import argparse
import errno
import fcntl
import hashlib
import json
import os
import secrets
import shutil
import stat
import subprocess
import tempfile
from contextlib import contextmanager, suppress
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

try:
    from scripts.manfred_candidate_vexp_authority import (
        DEFAULT_SENTINEL_STATE_PATH,
        CandidateVexpMutationAuthority,
        candidate_vexp_authority,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from manfred_candidate_vexp_authority import (  # type: ignore[no-redef]
        DEFAULT_SENTINEL_STATE_PATH,
        CandidateVexpMutationAuthority,
        candidate_vexp_authority,
    )


RECEIPT_SCHEMA = "ea.manfred_memorial_image_build.v3"
SELF_TEST_SCHEMA = "ea.manfred_memorial_image_build.self_test.v1"
SOAK_ROOT_FREE_FLOOR_BYTES = 20 * 1024**3
BUILD_ROOT_FREE_HEADROOM_BYTES = 15 * 1024**3
MINIMUM_ROOT_FREE_BYTES = (
    SOAK_ROOT_FREE_FLOOR_BYTES + BUILD_ROOT_FREE_HEADROOM_BYTES
)
ROOT_FREE_OBSERVATION_STAGES = (
    "after_lock",
    "after_context",
    "immediately_before_build",
)
BUILD_LOCK_NAME = "ea-manfred-memorial-image-build.lock"
BUILD_BUSY_ERROR = "manfred_image_build_already_running"
BUILD_LOCK_ERROR = "manfred_image_build_lock_unavailable"
DISK_SPACE_ERROR = "manfred_image_insufficient_root_free_space"
BUILDX_BUILDER_NAME = "ea-manfred-memorial-candidates"
BUILDX_BUILDER_DRIVER = "docker-container"
BUILDX_BUILDER_NODE_NAME = f"{BUILDX_BUILDER_NAME}0"
BUILDX_BUILDER_ENDPOINT = "unix:///var/run/docker.sock"
BUILDX_LIST_FORMAT = "{{.Name}}\t{{.DriverEndpoint}}"
BUILDX_CACHE_MAX_USED_SPACE = "8gb"
BUILDX_CACHE_RESERVED_SPACE = "2gb"
BUILDX_CACHE_MIN_FREE_SPACE = "30gb"
BUILDX_BUILDER_LIST_ERROR = "manfred_image_buildx_builder_list_invalid"
BUILDX_BUILDER_MISMATCH_ERROR = "manfred_image_buildx_builder_mismatch"
BUILDX_BUILDER_CREATE_ERROR = "manfred_image_buildx_builder_create_invalid"
EXISTING_IMAGE_MISMATCH_ERROR = "manfred_image_existing_tag_mismatch"
POST_BUILD_VERIFY_ERROR = "manfred_image_post_build_verification_failed"
BUILDX_BUILD_ERROR = "manfred_image_buildx_build_failed"
RECEIPT_CONFLICT_ERROR = "manfred_image_receipt_existing_conflict"
RECEIPT_PATH_ERROR = "manfred_image_receipt_path_invalid"
RECEIPT_WRITE_ERROR = "manfred_image_receipt_write_failed"
RECEIPT_MAX_BYTES = 1024 * 1024
IMAGE_BUILD_RECEIPT_MAX_BYTES = RECEIPT_MAX_BYTES
RECEIPT_TEMP_BASENAME = "ea-manfred-image-receipt"
RECEIPT_TEMP_CREATE_ATTEMPTS = 32
CREDENTIAL_EXPOSURE_REMEDIATION_BLOCKER = (
    "credential_exposure_remediation_unverified"
)


def _require_credential_exposure_remediation() -> None:
    """Deny candidate image work until canonical closure verification exists."""
    raise RuntimeError(CREDENTIAL_EXPOSURE_REMEDIATION_BLOCKER)


IMAGE_BUILD_AUTHORITY_KEYS = frozenset(
    {
        "entry",
        "operations",
        "finalization",
        "operation_count",
        "operations_exact",
        "authority_basis",
        "receipt_publication",
        "receipt_publication_held_under_authority",
    }
)
IMAGE_BUILD_OPERATION_KEYS = frozenset(
    {
        "sequence",
        "operation",
        "resource",
        "runner_acknowledged",
        "authority",
    }
)
OPERATION_RESOURCE_KEYS = frozenset({"argv", "target"})
CURRENT_PREDICATE_KEYS = frozenset(
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
IMAGE_BUILD_AUTHORITY_BINDING_KEYS = frozenset(
    {
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
)
AUTHORITY_EVIDENCE_KEYS = frozenset(
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
AUTHORITY_TUPLE_KEYS = AUTHORITY_EVIDENCE_KEYS - {
    "status",
    "phase",
    "boundary",
    "current_predicate",
}
IMAGE_BUILD_OPERATIONS = frozenset(
    {
        "builder_create",
        "image_build",
        "builder_prune",
        "verification_stale_cleanup",
        "verification_create",
        "verification_probe",
        "verification_cleanup",
        "image_cleanup",
    }
)
VERIFICATION_CONTAINER_LABEL = "ea.manfred.image-verifier"
VERIFICATION_CONTAINER_NAME_PREFIX = "ea-manfred-image-verify-"
SUCCESS_RECEIPT_FIELDS = frozenset(
    {
        "schema",
        "status",
        "commit",
        "image_tag",
        "image_id",
        "producer_sha256",
        "created_at",
        "revision_label",
        "runtime_source_revision",
        "rootfs_layer_count",
        "build_engine",
        "buildx_builder_name",
        "buildx_builder_driver",
        "buildx_builder_node_name",
        "buildx_builder_endpoint",
        "buildx_builder_created",
        "buildx_builder_validated",
        "buildx_load_completed",
        "image_reused",
        "preexisting_image_preserved",
        "build_cache_scope",
        "build_cache_prune",
        "admission",
        "global_build_cache_pruned",
        "live_or_rollback_images_pruned",
        "tracked_archive_context",
        "dirty_worktree_context_used",
        "runtime_secrets_baked_in",
        "memorial_data_baked_in",
        "memorial_archive_baked_in",
        "image_build_authority",
    }
)
SUCCESS_RECEIPT_CACHE_FIELDS = frozenset(
    {"status", "builder", "max_used_space", "reserved_space", "min_free_space"}
)
SUCCESS_RECEIPT_ADMISSION_FIELDS = frozenset(
    {
        "producer_sha256",
        "soak_root_free_floor_bytes",
        "build_root_free_headroom_bytes",
        "minimum_root_free_bytes",
        "root_free_bytes",
        "builder_created_before_build",
        "docker_mutations_before_build",
        "docker_build_started",
    }
)
FORBIDDEN_CONTEXT_PATHS = (
    ".env",
    ".env.local",
    "memorial_data",
    "memorial_archive",
)
_AUTHORIZED_RUN_TIMEOUT_SECONDS: ContextVar[float | None] = ContextVar(
    "manfred_candidate_authorized_run_timeout_seconds",
    default=None,
)


def _root_disk_admissible(free_bytes: int) -> bool:
    return (
        isinstance(free_bytes, int)
        and not isinstance(free_bytes, bool)
        and free_bytes >= MINIMUM_ROOT_FREE_BYTES
    )


def _root_free_bytes() -> int:
    try:
        free_bytes = shutil.disk_usage("/").free
    except OSError as exc:
        raise RuntimeError(DISK_SPACE_ERROR) from exc
    if (
        not isinstance(free_bytes, int)
        or isinstance(free_bytes, bool)
        or free_bytes < 0
    ):
        raise RuntimeError(DISK_SPACE_ERROR)
    return free_bytes


def _require_root_disk_capacity(*, free_bytes: int | None = None) -> None:
    if free_bytes is None:
        free_bytes = _root_free_bytes()
    if not _root_disk_admissible(free_bytes):
        raise RuntimeError(DISK_SPACE_ERROR)


@contextmanager
def _exclusive_build_lock(*, lock_directory: Path | None = None) -> Iterator[None]:
    uid = os.getuid()
    directory = lock_directory or Path("/run/user") / str(uid)
    directory_descriptor = -1
    lock_descriptor = -1
    locked = False
    try:
        try:
            directory_descriptor = os.open(
                directory,
                os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
            )
            directory_status = os.fstat(directory_descriptor)
        except OSError as exc:
            raise RuntimeError(BUILD_LOCK_ERROR) from exc
        if (
            not stat.S_ISDIR(directory_status.st_mode)
            or directory_status.st_uid != uid
            or stat.S_IMODE(directory_status.st_mode) & 0o022
        ):
            raise RuntimeError(BUILD_LOCK_ERROR)
        try:
            lock_descriptor = os.open(
                BUILD_LOCK_NAME,
                os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW,
                0o600,
                dir_fd=directory_descriptor,
            )
            lock_status = os.fstat(lock_descriptor)
        except OSError as exc:
            raise RuntimeError(BUILD_LOCK_ERROR) from exc
        if (
            not stat.S_ISREG(lock_status.st_mode)
            or lock_status.st_uid != uid
            or stat.S_IMODE(lock_status.st_mode) != 0o600
            or lock_status.st_nlink != 1
        ):
            raise RuntimeError(BUILD_LOCK_ERROR)
        try:
            fcntl.flock(lock_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except OSError as exc:
            if exc.errno in (errno.EACCES, errno.EAGAIN):
                raise RuntimeError(BUILD_BUSY_ERROR) from exc
            raise RuntimeError(BUILD_LOCK_ERROR) from exc
        yield
    finally:
        if locked:
            try:
                fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
            except OSError:
                pass
        if lock_descriptor >= 0:
            os.close(lock_descriptor)
        if directory_descriptor >= 0:
            os.close(directory_descriptor)


FORBIDDEN_IMAGE_PATHS = (
    "/app/memorial_data",
    "/app/memorial_archive",
    "/tmp/src",
    "/app/.env",
    "/app/.env.local",
)
FORBIDDEN_IMAGE_ENV_NAMES = frozenset(
    {
        "EA_API_TOKEN",
        "EA_SIGNING_SECRET",
        "DATABASE_URL",
        "UNMIXR_API_KEY",
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
    }
)


def _run(
    argv: list[str],
    *,
    cwd: Path | None = None,
    stdout: object | None = subprocess.PIPE,
    timeout_seconds: float | None = None,
) -> subprocess.CompletedProcess[bytes]:
    effective_timeout = (
        timeout_seconds
        if timeout_seconds is not None
        else _AUTHORIZED_RUN_TIMEOUT_SECONDS.get()
    )
    return subprocess.run(
        argv,
        cwd=str(cwd) if cwd else None,
        check=True,
        stdin=subprocess.DEVNULL,
        stdout=stdout,
        stderr=subprocess.PIPE,
        timeout=effective_timeout,
    )


@contextmanager
def _authorized_run_timeout(timeout_seconds: float) -> Iterator[None]:
    token = _AUTHORIZED_RUN_TIMEOUT_SECONDS.set(timeout_seconds)
    try:
        yield
    finally:
        _AUTHORIZED_RUN_TIMEOUT_SECONDS.reset(token)


def _record_authorized_operation(
    operations: list[dict[str, object]],
    *,
    operation: str,
    argv: list[str],
    target: str,
    evidence: dict[str, object],
) -> dict[str, object]:
    if (
        operation not in IMAGE_BUILD_OPERATIONS
        or not isinstance(argv, list)
        or not argv
        or any(not isinstance(value, str) or not value or "\x00" in value for value in argv)
        or not isinstance(target, str)
        or not target
        or "\x00" in target
    ):
        raise ValueError("manfred_image_authority_operation_invalid")
    record: dict[str, object] = {
        "sequence": len(operations) + 1,
        "operation": operation,
        "resource": {"argv": list(argv), "target": target},
        "runner_acknowledged": False,
        "authority": dict(evidence),
    }
    operations.append(record)
    return record


@contextmanager
def _authorized_operation(
    authority: CandidateVexpMutationAuthority,
    operations: list[dict[str, object]],
    *,
    operation: str,
    argv: list[str],
    target: str,
    minimum_validity_seconds: float,
) -> Iterator[object]:
    with authority.mutation(
        "before_candidate_image_build",
        minimum_validity_seconds=minimum_validity_seconds,
    ) as lease:
        record = _record_authorized_operation(
            operations,
            operation=operation,
            argv=argv,
            target=target,
            evidence=dict(lease.authority_evidence),
        )
        try:
            yield lease
        except BaseException:
            raise
        else:
            record["runner_acknowledged"] = True


def _text(argv: list[str], *, cwd: Path) -> str:
    return _run(argv, cwd=cwd).stdout.decode("utf-8", errors="strict").strip()


def _commit_for_ref(source_root: Path, ref: str) -> str:
    commit = _text(
        ["git", "rev-parse", "--verify", f"{str(ref or 'HEAD').strip()}^{{commit}}"],
        cwd=source_root,
    ).lower()
    if len(commit) != 40 or any(character not in "0123456789abcdef" for character in commit):
        raise ValueError("manfred_image_commit_invalid")
    return commit


def _safe_tag(raw: str, *, commit: str) -> str:
    if (
        not isinstance(commit, str)
        or len(commit) != 40
        or any(character not in "0123456789abcdef" for character in commit)
    ):
        raise ValueError("manfred_image_commit_invalid")
    default_tag = f"ea-runtime:manfred-{commit}"
    allowed_tags = {
        default_tag,
        f"ea-runtime:memorial-{commit}",
    }
    raw_tag = str(raw or "")
    tag = raw_tag or default_tag
    normalized_lowered = tag.strip().lower()
    if normalized_lowered == "latest" or normalized_lowered.endswith(":latest"):
        raise ValueError("manfred_image_mutable_tag_forbidden")
    if (
        not tag
        or tag != tag.strip()
        or any(character.isspace() for character in tag)
    ):
        raise ValueError("manfred_image_tag_invalid")
    if tag not in allowed_tags:
        raise ValueError("manfred_image_tag_revision_mismatch")
    return tag


def _dedicated_builder_driver() -> str | None:
    raw = _run(
        [
            "docker",
            "buildx",
            "ls",
            "--no-trunc",
            "--format",
            BUILDX_LIST_FORMAT,
        ]
    ).stdout
    try:
        rendered = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise RuntimeError(BUILDX_BUILDER_LIST_ERROR) from exc

    matches: list[str] = []
    for raw_line in rendered.splitlines():
        if not raw_line:
            continue
        name, separator, driver_or_endpoint = raw_line.partition("\t")
        if (
            separator != "\t"
            or not name
            or not driver_or_endpoint
            or "\t" in driver_or_endpoint
        ):
            raise RuntimeError(BUILDX_BUILDER_LIST_ERROR)
        if name == BUILDX_BUILDER_NAME:
            matches.append(driver_or_endpoint)

    if len(matches) > 1:
        raise RuntimeError(BUILDX_BUILDER_MISMATCH_ERROR)
    if not matches:
        return None
    if matches[0] != BUILDX_BUILDER_DRIVER:
        raise RuntimeError(BUILDX_BUILDER_MISMATCH_ERROR)
    return matches[0]


def _validate_dedicated_builder() -> None:
    raw = _run(
        ["docker", "buildx", "inspect", BUILDX_BUILDER_NAME]
    ).stdout
    try:
        rendered = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise RuntimeError(BUILDX_BUILDER_MISMATCH_ERROR) from exc

    builder_fields: dict[str, str] = {}
    nodes: list[dict[str, str]] = []
    current_node: dict[str, str] | None = None
    in_nodes = False
    for raw_line in rendered.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        if stripped == "Nodes:":
            if in_nodes:
                raise RuntimeError(BUILDX_BUILDER_MISMATCH_ERROR)
            in_nodes = True
            continue
        key, separator, value = stripped.partition(":")
        if separator != ":":
            continue
        key = key.strip()
        value = value.strip()
        if not in_nodes:
            if key in {"Name", "Driver"}:
                if key in builder_fields or not value:
                    raise RuntimeError(BUILDX_BUILDER_MISMATCH_ERROR)
                builder_fields[key] = value
            continue
        if key == "Name":
            current_node = {"Name": value}
            nodes.append(current_node)
        elif key == "Endpoint":
            if current_node is None or "Endpoint" in current_node:
                raise RuntimeError(BUILDX_BUILDER_MISMATCH_ERROR)
            current_node["Endpoint"] = value

    if builder_fields != {
        "Name": BUILDX_BUILDER_NAME,
        "Driver": BUILDX_BUILDER_DRIVER,
    }:
        raise RuntimeError(BUILDX_BUILDER_MISMATCH_ERROR)
    if nodes != [
        {
            "Name": BUILDX_BUILDER_NODE_NAME,
            "Endpoint": BUILDX_BUILDER_ENDPOINT,
        }
    ]:
        raise RuntimeError(BUILDX_BUILDER_MISMATCH_ERROR)


def _ensure_dedicated_builder(
    authority: CandidateVexpMutationAuthority,
    operations: list[dict[str, object]],
) -> bool:
    if _dedicated_builder_driver() is not None:
        _validate_dedicated_builder()
        return False
    create_command = [
        "docker",
        "buildx",
        "create",
        "--name",
        BUILDX_BUILDER_NAME,
        "--node",
        BUILDX_BUILDER_NODE_NAME,
        "--driver",
        BUILDX_BUILDER_DRIVER,
        BUILDX_BUILDER_ENDPOINT,
    ]
    with _authorized_operation(
        authority,
        operations,
        operation="builder_create",
        argv=create_command,
        target=BUILDX_BUILDER_NAME,
        minimum_validity_seconds=120,
    ) as lease:
        with _authorized_run_timeout(lease.command_timeout(120)):
            created = _run(create_command).stdout
    try:
        created_name = created.decode("utf-8", errors="strict").strip()
    except UnicodeDecodeError as exc:
        raise RuntimeError(BUILDX_BUILDER_CREATE_ERROR) from exc
    if created_name != BUILDX_BUILDER_NAME:
        raise RuntimeError(BUILDX_BUILDER_CREATE_ERROR)
    if _dedicated_builder_driver() != BUILDX_BUILDER_DRIVER:
        raise RuntimeError(BUILDX_BUILDER_MISMATCH_ERROR)
    _validate_dedicated_builder()
    return True


def _prune_dedicated_builder_cache(
    authority: CandidateVexpMutationAuthority,
    operations: list[dict[str, object]],
) -> None:
    prune_command = [
        "docker",
        "buildx",
        "prune",
        "--builder",
        BUILDX_BUILDER_NAME,
        "-f",
        "--max-used-space",
        BUILDX_CACHE_MAX_USED_SPACE,
        "--reserved-space",
        BUILDX_CACHE_RESERVED_SPACE,
        "--min-free-space",
        BUILDX_CACHE_MIN_FREE_SPACE,
    ]
    with _authorized_operation(
        authority,
        operations,
        operation="builder_prune",
        argv=prune_command,
        target=BUILDX_BUILDER_NAME,
        minimum_validity_seconds=300,
    ) as lease:
        with _authorized_run_timeout(lease.command_timeout(300)):
            _run(prune_command)


def _listed_image_id(tag: str) -> str | None:
    raw = _run(
        ["docker", "image", "ls", "--no-trunc", "--quiet", tag]
    ).stdout
    try:
        rendered = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise RuntimeError(EXISTING_IMAGE_MISMATCH_ERROR) from exc
    identifiers = [line.strip().lower() for line in rendered.splitlines() if line.strip()]
    if not identifiers:
        return None
    if len(identifiers) != 1:
        raise RuntimeError(EXISTING_IMAGE_MISMATCH_ERROR)
    identifier = identifiers[0]
    digest = identifier.removeprefix("sha256:")
    if (
        not identifier.startswith("sha256:")
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise RuntimeError(EXISTING_IMAGE_MISMATCH_ERROR)
    return identifier


def _cleanup_new_image(
    tag: str,
    *,
    expected_image_id: str | None,
    authority: CandidateVexpMutationAuthority,
    operations: list[dict[str, object]],
) -> str:
    try:
        current_image_id = _listed_image_id(tag)
    except (OSError, RuntimeError, subprocess.CalledProcessError):
        return "not_removed_identity_unavailable"
    if current_image_id is None:
        return "already_absent"
    if expected_image_id is None or current_image_id != expected_image_id:
        return "not_removed_identity_changed"
    try:
        cleanup_command = ["docker", "image", "rm", tag]
        with _authorized_operation(
            authority,
            operations,
            operation="image_cleanup",
            argv=cleanup_command,
            target=tag,
            minimum_validity_seconds=120,
        ) as lease:
            with _authorized_run_timeout(lease.command_timeout(120)):
                _run(cleanup_command)
        remaining_image_id = _listed_image_id(tag)
    except (OSError, RuntimeError, subprocess.SubprocessError):
        return "remove_failed"
    if remaining_image_id is None:
        return "removed"
    if remaining_image_id != expected_image_id:
        return "not_removed_identity_changed"
    return "remove_failed"


def _cache_policy_receipt(*, status: str) -> dict[str, object]:
    return {
        "status": status,
        "builder": BUILDX_BUILDER_NAME,
        "max_used_space": BUILDX_CACHE_MAX_USED_SPACE,
        "reserved_space": BUILDX_CACHE_RESERVED_SPACE,
        "min_free_space": BUILDX_CACHE_MIN_FREE_SPACE,
    }


def _producer_sha256(*, producer_path: Path | None = None) -> str:
    # Do not resolve /proc/self/fd/<n>: release delegates bind execution to the
    # already-attested inode so a concurrent pathname replacement cannot change
    # which producer runs or which bytes its receipt identifies.
    path = (producer_path or Path(__file__)).expanduser()
    try:
        status = path.stat()
    except OSError as exc:
        raise RuntimeError("manfred_image_producer_metadata_invalid") from exc
    if (
        not stat.S_ISREG(status.st_mode)
        or status.st_uid != os.getuid()
        or status.st_nlink != 1
        or stat.S_IMODE(status.st_mode) & 0o022
    ):
        raise RuntimeError("manfred_image_producer_metadata_invalid")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if len(digest) != 64 or any(
        character not in "0123456789abcdef" for character in digest
    ):
        raise RuntimeError("manfred_image_producer_digest_invalid")
    return digest


def _admission_evidence(
    *,
    producer_sha256: str,
    root_free_observations: dict[str, int],
    builder_created: bool,
    docker_build_started: bool,
) -> dict[str, object]:
    if (
        not isinstance(producer_sha256, str)
        or len(producer_sha256) != 64
        or any(
            character not in "0123456789abcdef"
            for character in producer_sha256
        )
    ):
        raise ValueError("manfred_image_admission_producer_digest_invalid")
    if not isinstance(builder_created, bool) or not isinstance(
        docker_build_started, bool
    ):
        raise ValueError("manfred_image_admission_boolean_invalid")
    stages = tuple(root_free_observations)
    if (
        not stages
        or len(stages) > len(ROOT_FREE_OBSERVATION_STAGES)
        or stages != ROOT_FREE_OBSERVATION_STAGES[: len(stages)]
    ):
        raise ValueError("manfred_image_admission_observation_order_invalid")
    observations: dict[str, int] = {}
    for stage, free_bytes in root_free_observations.items():
        if (
            not isinstance(free_bytes, int)
            or isinstance(free_bytes, bool)
            or free_bytes < 0
        ):
            raise ValueError("manfred_image_admission_observation_invalid")
        observations[stage] = free_bytes
    if docker_build_started and stages != ROOT_FREE_OBSERVATION_STAGES:
        raise ValueError("manfred_image_admission_prebuild_observation_missing")
    return {
        "producer_sha256": producer_sha256,
        "soak_root_free_floor_bytes": SOAK_ROOT_FREE_FLOOR_BYTES,
        "build_root_free_headroom_bytes": BUILD_ROOT_FREE_HEADROOM_BYTES,
        "minimum_root_free_bytes": MINIMUM_ROOT_FREE_BYTES,
        "root_free_bytes": observations,
        "builder_created_before_build": builder_created,
        "docker_mutations_before_build": int(builder_created),
        "docker_build_started": docker_build_started,
    }


def _disk_denial_receipt(
    *,
    commit: str,
    image_tag: str,
    created_at: str,
    producer_sha256: str,
    root_free_observations: dict[str, int],
    builder_created: bool,
    builder_validated: bool,
) -> dict[str, object]:
    if not isinstance(builder_validated, bool):
        raise ValueError("manfred_image_admission_boolean_invalid")
    if (
        not isinstance(commit, str)
        or len(commit) != 40
        or any(character not in "0123456789abcdef" for character in commit)
        or _safe_tag(image_tag, commit=commit) != image_tag
    ):
        raise ValueError("manfred_image_disk_denial_identity_invalid")
    try:
        parsed_created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("manfred_image_disk_denial_created_at_invalid") from exc
    if (
        not isinstance(created_at, str)
        or not created_at.endswith("Z")
        or parsed_created_at.tzinfo != timezone.utc
    ):
        raise ValueError("manfred_image_disk_denial_created_at_invalid")
    admission = _admission_evidence(
        producer_sha256=producer_sha256,
        root_free_observations=root_free_observations,
        builder_created=builder_created,
        docker_build_started=False,
    )
    denied_stage = tuple(root_free_observations)[-1]
    denied_free_bytes = root_free_observations[denied_stage]
    prior_free_bytes = tuple(root_free_observations.values())[:-1]
    if _root_disk_admissible(denied_free_bytes):
        raise ValueError("manfred_image_disk_denial_admissible_observation")
    if any(not _root_disk_admissible(value) for value in prior_free_bytes):
        raise ValueError("manfred_image_disk_denial_prior_observation_invalid")
    prebuild_reached = denied_stage == "immediately_before_build"
    if (
        (builder_created and not prebuild_reached)
        or (builder_validated != prebuild_reached)
    ):
        raise ValueError("manfred_image_disk_denial_builder_state_invalid")
    mutations_performed = int(builder_created)
    return {
        "schema": RECEIPT_SCHEMA,
        "status": "fail",
        "error": DISK_SPACE_ERROR,
        "commit": commit,
        "source_commit": commit,
        "image_tag": image_tag,
        "created_at": created_at,
        "producer_sha256": producer_sha256,
        "denied_stage": denied_stage,
        "admission": admission,
        "docker_build_started": False,
        "mutations_performed": mutations_performed,
        "mutations_performed_exact": True,
        "mutation_scope": "docker",
        "mutation_unit": "mutating_cli_command",
        "buildx_builder_created": builder_created,
        "buildx_builder_validated": builder_validated,
        "buildx_load_completed": False,
        "runtime_secrets_included": False,
    }


def _record_root_free_or_deny(
    *,
    stage: str,
    root_free_observations: dict[str, int],
    commit: str,
    image_tag: str,
    created_at: str,
    producer_sha256: str,
    builder_created: bool,
    builder_validated: bool,
    receipt_path: Path,
) -> int:
    expected_stage_index = len(root_free_observations)
    if (
        expected_stage_index >= len(ROOT_FREE_OBSERVATION_STAGES)
        or stage != ROOT_FREE_OBSERVATION_STAGES[expected_stage_index]
    ):
        raise ValueError("manfred_image_admission_observation_order_invalid")
    free_bytes = _root_free_bytes()
    root_free_observations[stage] = free_bytes
    if not _root_disk_admissible(free_bytes):
        denial = _disk_denial_receipt(
            commit=commit,
            image_tag=image_tag,
            created_at=created_at,
            producer_sha256=producer_sha256,
            root_free_observations=root_free_observations,
            builder_created=builder_created,
            builder_validated=builder_validated,
        )
        _atomic_json(receipt_path, denial)
        raise RuntimeError(DISK_SPACE_ERROR)
    return free_bytes


def _success_receipt(
    *,
    commit: str,
    image_tag: str,
    image_id: str,
    inspection: dict[str, object],
    created_at: str,
    builder_created: bool,
    builder_validated: bool,
    image_reused: bool,
    cache_prune_status: str,
    admission: dict[str, object],
    producer_sha256: str,
    image_build_authority: dict[str, object],
) -> dict[str, object]:
    return {
        "schema": RECEIPT_SCHEMA,
        "status": "pass",
        "commit": commit,
        "image_tag": image_tag,
        "image_id": image_id,
        "producer_sha256": producer_sha256,
        "created_at": created_at,
        "revision_label": commit,
        "runtime_source_revision": commit,
        "rootfs_layer_count": len((inspection.get("RootFS") or {}).get("Layers") or []),
        "build_engine": "docker-buildx",
        "buildx_builder_name": BUILDX_BUILDER_NAME,
        "buildx_builder_driver": BUILDX_BUILDER_DRIVER,
        "buildx_builder_node_name": BUILDX_BUILDER_NODE_NAME,
        "buildx_builder_endpoint": BUILDX_BUILDER_ENDPOINT,
        "buildx_builder_created": builder_created,
        "buildx_builder_validated": builder_validated,
        "buildx_load_completed": not image_reused,
        "image_reused": image_reused,
        "preexisting_image_preserved": image_reused,
        "build_cache_scope": "dedicated_builder_only",
        "build_cache_prune": _cache_policy_receipt(status=cache_prune_status),
        "admission": admission,
        "global_build_cache_pruned": False,
        "live_or_rollback_images_pruned": False,
        "tracked_archive_context": not image_reused,
        "dirty_worktree_context_used": False,
        "runtime_secrets_baked_in": False,
        "memorial_data_baked_in": False,
        "memorial_archive_baked_in": False,
        "image_build_authority": image_build_authority,
    }


def _validate_operation_resource(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != OPERATION_RESOURCE_KEYS:
        raise RuntimeError(RECEIPT_CONFLICT_ERROR)
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
        raise RuntimeError(RECEIPT_CONFLICT_ERROR)
    return {"argv": list(argv), "target": target}


def _validate_authority_predicate(
    value: object,
    *,
    epoch_started_ms: object,
    minimum_generation: int,
    minimum_monotonic_ns: int,
) -> tuple[int, int]:
    if not isinstance(value, dict) or set(value) != CURRENT_PREDICATE_KEYS:
        raise RuntimeError(RECEIPT_CONFLICT_ERROR)
    generation = value.get("generation")
    monotonic_ns = value.get("monotonic_ns")
    digests = (
        value.get("record_sha256"),
        value.get("sentinel_producer_sha256"),
        value.get("root_predicate_producer_sha256"),
    )
    if (
        value.get("contract_name") != "ea.vexp_current_predicate.v1"
        or value.get("version") != 1
        or value.get("status") != "positive"
        or value.get("epoch_started_ms") != epoch_started_ms
        or type(generation) is not int
        or generation < minimum_generation
        or type(monotonic_ns) is not int
        or monotonic_ns < minimum_monotonic_ns
        or not isinstance(value.get("boot_id"), str)
        or len(str(value["boot_id"])) != 36
        or any(
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            for digest in digests
        )
    ):
        raise RuntimeError(RECEIPT_CONFLICT_ERROR)
    return generation, monotonic_ns


def _validate_image_build_authority(
    value: object,
    *,
    image_reused: bool,
    builder_created: bool,
) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != IMAGE_BUILD_AUTHORITY_KEYS:
        raise RuntimeError(RECEIPT_CONFLICT_ERROR)
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
        or value.get("receipt_publication") != "exclusive_hardlink_noreplace_v1"
        or value.get("receipt_publication_held_under_authority") is not True
    ):
        raise RuntimeError(RECEIPT_CONFLICT_ERROR)
    rows = [dict(entry)] + [dict(row["authority"]) for row in operations] + [dict(finalization)]
    if any(set(row) != AUTHORITY_EVIDENCE_KEYS for row in rows):
        raise RuntimeError(RECEIPT_CONFLICT_ERROR)
    immutable = {key: rows[0].get(key) for key in AUTHORITY_TUPLE_KEYS}
    expected_phase_boundary = [
        ("entry", "candidate_entry"),
        *(("pre_mutation", "before_candidate_image_build") for _ in operations),
        ("finalization", "candidate_receipt_publication"),
    ]
    previous_generation = 0
    previous_monotonic_ns = 0
    for row, (phase, boundary) in zip(rows, expected_phase_boundary, strict=True):
        if (
            row.get("status") != "pass"
            or row.get("phase") != phase
            or row.get("boundary") != boundary
            or {key: row.get(key) for key in AUTHORITY_TUPLE_KEYS} != immutable
        ):
            raise RuntimeError(RECEIPT_CONFLICT_ERROR)
        previous_generation, previous_monotonic_ns = _validate_authority_predicate(
            row.get("current_predicate"),
            epoch_started_ms=immutable.get("epoch_started_ms"),
            minimum_generation=previous_generation,
            minimum_monotonic_ns=previous_monotonic_ns,
        )
    operation_names: list[str] = []
    for index, operation in enumerate(operations, start=1):
        if (
            set(operation) != IMAGE_BUILD_OPERATION_KEYS
            or operation.get("sequence") != index
            or operation.get("operation") not in IMAGE_BUILD_OPERATIONS
            or operation.get("runner_acknowledged") is not True
            or not isinstance(operation.get("authority"), dict)
        ):
            raise RuntimeError(RECEIPT_CONFLICT_ERROR)
        _validate_operation_resource(operation.get("resource"))
        operation_names.append(str(operation["operation"]))
    optional_stale = ["verification_stale_cleanup"]
    verification_tail_options = (
        ["verification_create", "verification_probe", "verification_cleanup"],
        [*optional_stale, "verification_create", "verification_probe", "verification_cleanup"],
    )
    if image_reused:
        expected_basis = "preexisting_image_current_authority_probe"
        allowed_sequences = verification_tail_options
    else:
        expected_basis = "new_image_build"
        prefix = ["image_build", "builder_prune"]
        if builder_created:
            prefix.insert(0, "builder_create")
        allowed_sequences = tuple([*prefix, *tail] for tail in verification_tail_options)
    if (
        value.get("authority_basis") != expected_basis
        or operation_names not in allowed_sequences
    ):
        raise RuntimeError(RECEIPT_CONFLICT_ERROR)
    return dict(value)


def _require_build_authority_current(
    value: object,
    *,
    current_entry: dict[str, object],
) -> None:
    if not isinstance(value, dict) or not isinstance(value.get("entry"), dict):
        raise RuntimeError(RECEIPT_CONFLICT_ERROR)
    receipt_entry = dict(value["entry"])
    if (
        set(current_entry) != AUTHORITY_EVIDENCE_KEYS
        or current_entry.get("status") != "pass"
        or current_entry.get("phase") != "entry"
        or current_entry.get("boundary") != "candidate_entry"
        or {key: receipt_entry.get(key) for key in AUTHORITY_TUPLE_KEYS}
        != {key: current_entry.get(key) for key in AUTHORITY_TUPLE_KEYS}
    ):
        raise RuntimeError(RECEIPT_CONFLICT_ERROR)


def _publish_success_receipt(
    receipt_path: Path,
    *,
    authority: CandidateVexpMutationAuthority,
    entry_evidence: dict[str, object],
    operations: list[dict[str, object]],
    authority_basis: str,
    receipt_fields: dict[str, object],
) -> dict[str, object]:
    with authority.finalization() as finalization_evidence:
        image_build_authority = {
            "entry": dict(entry_evidence),
            "operations": [dict(row) for row in operations],
            "finalization": dict(finalization_evidence),
            "operation_count": len(operations),
            "operations_exact": True,
            "authority_basis": authority_basis,
            "receipt_publication": "exclusive_hardlink_noreplace_v1",
            "receipt_publication_held_under_authority": True,
        }
        receipt = _success_receipt(
            **receipt_fields,
            image_build_authority=image_build_authority,
        )
        _validate_success_receipt_shape(
            receipt,
            commit=str(receipt["commit"]),
            image_tag=str(receipt["image_tag"]),
            producer_sha256=str(receipt["producer_sha256"]),
        )
        _atomic_json(receipt_path, receipt)
    return receipt


def _materialize_tracked_context(*, source_root: Path, commit: str, destination: Path) -> None:
    archive_path = destination.parent / "source.tar"
    with archive_path.open("wb") as handle:
        _run(
            ["git", "archive", "--format=tar", commit],
            cwd=source_root,
            stdout=handle,
        )
    _run(["tar", "-xf", str(archive_path), "-C", str(destination)])
    archive_path.unlink(missing_ok=True)
    for relative in FORBIDDEN_CONTEXT_PATHS:
        path = destination / relative
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)
    for relative in FORBIDDEN_CONTEXT_PATHS:
        if (destination / relative).exists() or (destination / relative).is_symlink():
            raise RuntimeError("manfred_image_forbidden_context_path_present")


def _image_inspection(tag: str, *, expected_commit: str) -> tuple[str, dict[str, object]]:
    raw = _run(["docker", "image", "inspect", tag]).stdout
    payload = json.loads(raw)
    if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
        raise RuntimeError("manfred_image_inspection_invalid")
    inspection = dict(payload[0])
    image_id = str(inspection.get("Id") or "").strip()
    labels = dict((inspection.get("Config") or {}).get("Labels") or {})
    if labels.get("org.opencontainers.image.revision") != expected_commit:
        raise RuntimeError("manfred_image_revision_label_mismatch")
    configured_environment = list((inspection.get("Config") or {}).get("Env") or [])
    configured_revisions = [
        str(item).split("=", 1)[1]
        for item in configured_environment
        if str(item).split("=", 1)[0] == "EA_SOURCE_REVISION" and "=" in str(item)
    ]
    if configured_revisions != [expected_commit]:
        raise RuntimeError("manfred_image_source_revision_environment_mismatch")
    for item in configured_environment:
        name = str(item).split("=", 1)[0]
        if name in FORBIDDEN_IMAGE_ENV_NAMES:
            raise RuntimeError("manfred_image_runtime_secret_baked_in")
    return image_id, inspection


def _verification_container_name(image_id: str) -> str:
    if not _valid_receipt_image_id(image_id):
        raise RuntimeError("manfred_image_verification_image_id_invalid")
    return f"{VERIFICATION_CONTAINER_NAME_PREFIX}{image_id[7:39]}"


def _verification_container_identity(
    name: str,
    *,
    image_id: str,
) -> str | None:
    try:
        raw = _run(["docker", "container", "inspect", name]).stdout
    except subprocess.CalledProcessError as exc:
        stderr = bytes(exc.stderr or b"").decode("utf-8", errors="replace").lower()
        if "no such container" in stderr or "no such object" in stderr:
            return None
        raise RuntimeError("manfred_image_verification_container_unverifiable") from exc
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("manfred_image_verification_container_unverifiable") from exc
    if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
        raise RuntimeError("manfred_image_verification_container_unverifiable")
    row = dict(payload[0])
    config = dict(row.get("Config") or {})
    host_config = dict(row.get("HostConfig") or {})
    labels = dict(config.get("Labels") or {})
    container_id = str(row.get("Id") or "").lower()
    if (
        len(container_id) != 64
        or any(character not in "0123456789abcdef" for character in container_id)
        or row.get("Name") != f"/{name}"
        or row.get("Image") != image_id
        or labels != {VERIFICATION_CONTAINER_LABEL: image_id}
        or host_config.get("NetworkMode") != "none"
    ):
        raise RuntimeError("manfred_image_verification_container_identity_mismatch")
    return container_id


def _cleanup_verification_container(
    name: str,
    *,
    image_id: str,
    authority: CandidateVexpMutationAuthority,
    operations: list[dict[str, object]],
    operation: str,
) -> bool:
    container_id = _verification_container_identity(name, image_id=image_id)
    if container_id is None:
        return False
    cleanup_command = ["docker", "container", "rm", "--force", container_id]
    with _authorized_operation(
        authority,
        operations,
        operation=operation,
        argv=cleanup_command,
        target=f"{name}:{container_id}",
        minimum_validity_seconds=120,
    ) as lease:
        with _authorized_run_timeout(lease.command_timeout(120)):
            _run(cleanup_command)
    if _verification_container_identity(name, image_id=image_id) is not None:
        raise RuntimeError("manfred_image_verification_container_cleanup_failed")
    return True


def _verify_image_filesystem(
    image_id: str,
    *,
    authority: CandidateVexpMutationAuthority,
    operations: list[dict[str, object]],
) -> str:
    name = _verification_container_name(image_id)
    checks = " && ".join(f"test ! -e {path}" for path in FORBIDDEN_IMAGE_PATHS)
    _cleanup_verification_container(
        name,
        image_id=image_id,
        authority=authority,
        operations=operations,
        operation="verification_stale_cleanup",
    )
    probe_error: BaseException | None = None
    try:
        create_command = [
            "docker",
            "container",
            "create",
            "--name",
            name,
            "--label",
            f"{VERIFICATION_CONTAINER_LABEL}={image_id}",
            "--network",
            "none",
            "--entrypoint",
            "/bin/sh",
            image_id,
            "-ec",
            checks,
        ]
        with _authorized_operation(
            authority,
            operations,
            operation="verification_create",
            argv=create_command,
            target=name,
            minimum_validity_seconds=120,
        ) as lease:
            with _authorized_run_timeout(lease.command_timeout(120)):
                created = _run(create_command).stdout.decode(
                    "ascii", errors="strict"
                ).strip().lower()
        container_id = _verification_container_identity(name, image_id=image_id)
        if container_id is None or created != container_id:
            raise RuntimeError("manfred_image_verification_container_create_invalid")
        probe_command = ["docker", "container", "start", "--attach", container_id]
        with _authorized_operation(
            authority,
            operations,
            operation="verification_probe",
            argv=probe_command,
            target=f"{name}:{container_id}",
            minimum_validity_seconds=120,
        ) as lease:
            with _authorized_run_timeout(lease.command_timeout(120)):
                _run(probe_command)
    except BaseException as exc:
        probe_error = exc
    finally:
        try:
            _cleanup_verification_container(
                name,
                image_id=image_id,
                authority=authority,
                operations=operations,
                operation="verification_cleanup",
            )
        except BaseException as cleanup_error:
            if probe_error is not None:
                raise RuntimeError(
                    "manfred_image_verification_probe_and_cleanup_failed"
                ) from cleanup_error
            raise
    if probe_error is not None:
        raise probe_error
    return name


def _verify_image_filesystem_authorized(
    image_id: str,
    *,
    authority: CandidateVexpMutationAuthority,
    operations: list[dict[str, object]],
) -> str:
    return _verify_image_filesystem(
        image_id,
        authority=authority,
        operations=operations,
    )


def _build_receipt_bytes(payload: dict[str, object]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode(
            "utf-8"
        )
        + b"\n"
    )


def _trusted_receipt_parent(path: Path) -> tuple[Path, Path]:
    normalized = Path(os.path.abspath(os.fspath(path.expanduser())))
    if normalized.name in {"", ".", ".."}:
        raise RuntimeError(RECEIPT_PATH_ERROR)
    normalized.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    try:
        parent = normalized.parent.resolve(strict=True)
        metadata = parent.stat()
    except OSError as exc:
        raise RuntimeError(RECEIPT_PATH_ERROR) from exc
    if (
        parent != normalized.parent
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) & 0o022
    ):
        raise RuntimeError(RECEIPT_PATH_ERROR)
    return normalized, parent


def _receipt_metadata_identity(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_uid,
        metadata.st_gid,
        metadata.st_nlink,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _read_build_receipt_entry(
    directory_descriptor: int,
    name: str,
    *,
    required_nlink: int,
) -> tuple[bytes, os.stat_result]:
    descriptor = -1
    try:
        try:
            descriptor = os.open(
                name,
                os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=directory_descriptor,
            )
        except FileNotFoundError:
            raise
        except OSError as exc:
            raise RuntimeError(RECEIPT_PATH_ERROR) from exc
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.getuid()
            or before.st_nlink != required_nlink
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_size <= 0
            or before.st_size > RECEIPT_MAX_BYTES
        ):
            raise RuntimeError(RECEIPT_PATH_ERROR)
        chunks: list[bytes] = []
        remaining = int(before.st_size)
        while remaining:
            chunk = os.read(descriptor, min(65536, remaining))
            if not chunk:
                raise RuntimeError(RECEIPT_PATH_ERROR)
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
        try:
            current = os.stat(
                name,
                dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
        except OSError as exc:
            raise RuntimeError(RECEIPT_PATH_ERROR) from exc
        if (
            _receipt_metadata_identity(before)
            != _receipt_metadata_identity(after)
            or _receipt_metadata_identity(before)
            != _receipt_metadata_identity(current)
        ):
            raise RuntimeError(RECEIPT_PATH_ERROR)
        return b"".join(chunks), before
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _read_build_receipt(path: Path, *, missing_ok: bool = False) -> bytes | None:
    normalized, parent = _trusted_receipt_parent(path)
    directory_descriptor = os.open(
        parent,
        os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        try:
            encoded, _metadata = _read_build_receipt_entry(
                directory_descriptor,
                normalized.name,
                required_nlink=1,
            )
        except FileNotFoundError:
            if missing_ok:
                return None
            raise RuntimeError(RECEIPT_PATH_ERROR)
        return encoded
    finally:
        os.close(directory_descriptor)


def _read_existing_build_receipt(path: Path) -> bytes | None:
    try:
        normalized = Path(os.path.abspath(os.fspath(path.expanduser())))
    except (OSError, RuntimeError, ValueError) as exc:
        raise RuntimeError(RECEIPT_PATH_ERROR) from exc
    if not normalized.is_absolute() or normalized.name in {"", ".", ".."}:
        raise RuntimeError(RECEIPT_PATH_ERROR)
    try:
        metadata = os.lstat(normalized)
    except FileNotFoundError:
        # Do not create the receipt parent on the no-replay path.  Normal
        # publication remains solely responsible for that later mutation.
        return None
    except OSError as exc:
        raise RuntimeError(RECEIPT_PATH_ERROR) from exc
    if metadata.st_nlink == 2:
        completed, observed = _reconcile_interrupted_build_receipt_publication(
            normalized,
            expected=None,
        )
        if not completed or observed is None:
            raise RuntimeError(RECEIPT_PATH_ERROR)
        return observed
    return _read_build_receipt(normalized)


def _canonical_success_receipt(encoded: bytes) -> dict[str, object]:
    try:
        payload = json.loads(encoded)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise RuntimeError(RECEIPT_CONFLICT_ERROR) from exc
    if (
        not isinstance(payload, dict)
        or set(payload) != SUCCESS_RECEIPT_FIELDS
        or _build_receipt_bytes(payload) != encoded
    ):
        raise RuntimeError(RECEIPT_CONFLICT_ERROR)
    return dict(payload)


def _valid_receipt_created_at(value: object) -> bool:
    if not isinstance(value, str) or not value.endswith("Z"):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return (
        parsed.tzinfo == timezone.utc
        and parsed.microsecond == 0
        and parsed.isoformat().replace("+00:00", "Z") == value
    )


def _valid_receipt_image_id(value: object) -> bool:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        return False
    digest = value.removeprefix("sha256:")
    return len(digest) == 64 and all(
        character in "0123456789abcdef" for character in digest
    )


def _validate_success_receipt_shape(
    payload: dict[str, object],
    *,
    commit: str,
    image_tag: str,
    producer_sha256: str,
) -> bool:
    image_reused = payload.get("image_reused")
    builder_created = payload.get("buildx_builder_created")
    rootfs_layer_count = payload.get("rootfs_layer_count")
    if (
        payload.get("schema") != RECEIPT_SCHEMA
        or payload.get("status") != "pass"
        or payload.get("commit") != commit
        or payload.get("image_tag") != image_tag
        or not _valid_receipt_image_id(payload.get("image_id"))
        or payload.get("producer_sha256") != producer_sha256
        or not _valid_receipt_created_at(payload.get("created_at"))
        or payload.get("revision_label") != commit
        or payload.get("runtime_source_revision") != commit
        or not isinstance(rootfs_layer_count, int)
        or isinstance(rootfs_layer_count, bool)
        or rootfs_layer_count < 0
        or payload.get("build_engine") != "docker-buildx"
        or payload.get("buildx_builder_name") != BUILDX_BUILDER_NAME
        or payload.get("buildx_builder_driver") != BUILDX_BUILDER_DRIVER
        or payload.get("buildx_builder_node_name") != BUILDX_BUILDER_NODE_NAME
        or payload.get("buildx_builder_endpoint") != BUILDX_BUILDER_ENDPOINT
        or not isinstance(image_reused, bool)
        or not isinstance(builder_created, bool)
        or payload.get("build_cache_scope") != "dedicated_builder_only"
    ):
        raise RuntimeError(RECEIPT_CONFLICT_ERROR)

    expected_state = (
        {
            "buildx_builder_created": False,
            "buildx_builder_validated": False,
            "buildx_load_completed": False,
            "preexisting_image_preserved": True,
            "tracked_archive_context": False,
        }
        if image_reused
        else {
            "buildx_builder_created": builder_created,
            "buildx_builder_validated": True,
            "buildx_load_completed": True,
            "preexisting_image_preserved": False,
            "tracked_archive_context": True,
        }
    )
    expected_state.update(
        {
            "global_build_cache_pruned": False,
            "live_or_rollback_images_pruned": False,
            "dirty_worktree_context_used": False,
            "runtime_secrets_baked_in": False,
            "memorial_data_baked_in": False,
            "memorial_archive_baked_in": False,
        }
    )
    if any(payload.get(name) is not value for name, value in expected_state.items()):
        raise RuntimeError(RECEIPT_CONFLICT_ERROR)

    cache_policy = payload.get("build_cache_prune")
    expected_cache_status = "not_run_existing_image_reused" if image_reused else "pass"
    if (
        not isinstance(cache_policy, dict)
        or set(cache_policy) != SUCCESS_RECEIPT_CACHE_FIELDS
        or cache_policy.get("status") != expected_cache_status
        or cache_policy.get("builder") != BUILDX_BUILDER_NAME
        or cache_policy.get("max_used_space") != BUILDX_CACHE_MAX_USED_SPACE
        or cache_policy.get("reserved_space") != BUILDX_CACHE_RESERVED_SPACE
        or cache_policy.get("min_free_space") != BUILDX_CACHE_MIN_FREE_SPACE
    ):
        raise RuntimeError(RECEIPT_CONFLICT_ERROR)

    admission = payload.get("admission")
    if (
        not isinstance(admission, dict)
        or set(admission) != SUCCESS_RECEIPT_ADMISSION_FIELDS
        or admission.get("producer_sha256") != producer_sha256
        or admission.get("soak_root_free_floor_bytes")
        != SOAK_ROOT_FREE_FLOOR_BYTES
        or admission.get("build_root_free_headroom_bytes")
        != BUILD_ROOT_FREE_HEADROOM_BYTES
        or admission.get("minimum_root_free_bytes") != MINIMUM_ROOT_FREE_BYTES
        or admission.get("builder_created_before_build") is not builder_created
        or admission.get("docker_build_started") is not (not image_reused)
    ):
        raise RuntimeError(RECEIPT_CONFLICT_ERROR)
    docker_mutations = admission.get("docker_mutations_before_build")
    if (
        not isinstance(docker_mutations, int)
        or isinstance(docker_mutations, bool)
        or docker_mutations != int(builder_created)
    ):
        raise RuntimeError(RECEIPT_CONFLICT_ERROR)
    root_free = admission.get("root_free_bytes")
    expected_stages = ("after_lock",) if image_reused else ROOT_FREE_OBSERVATION_STAGES
    if not isinstance(root_free, dict) or set(root_free) != set(expected_stages):
        raise RuntimeError(RECEIPT_CONFLICT_ERROR)
    for stage in expected_stages:
        if not _root_disk_admissible(root_free.get(stage)):
            raise RuntimeError(RECEIPT_CONFLICT_ERROR)
    _validate_image_build_authority(
        payload.get("image_build_authority"),
        image_reused=image_reused,
        builder_created=builder_created,
    )
    return image_reused


def validated_build_receipt_binding(
    encoded: bytes,
    *,
    receipt_path: Path,
    commit: str,
    image_tag: str,
    image_id: str,
) -> dict[str, object]:
    payload = _canonical_success_receipt(encoded)
    producer_sha256 = payload.get("producer_sha256")
    if (
        not isinstance(producer_sha256, str)
        or len(producer_sha256) != 64
        or any(character not in "0123456789abcdef" for character in producer_sha256)
        or payload.get("image_id") != image_id
    ):
        raise RuntimeError(RECEIPT_CONFLICT_ERROR)
    image_reused = _validate_success_receipt_shape(
        payload,
        commit=commit,
        image_tag=image_tag,
        producer_sha256=producer_sha256,
    )
    binding = {
        "receipt_schema": RECEIPT_SCHEMA,
        "receipt_path": str(receipt_path),
        "receipt_sha256": hashlib.sha256(encoded).hexdigest(),
        "image_tag": image_tag,
        "image_id": image_id,
        "runtime_source_revision": commit,
        "producer_sha256": producer_sha256,
        "image_reused": image_reused,
        "authority": dict(payload["image_build_authority"]),
    }
    if set(binding) != IMAGE_BUILD_AUTHORITY_BINDING_KEYS:
        raise RuntimeError(RECEIPT_CONFLICT_ERROR)
    return binding


def validate_build_authority_binding(
    value: object,
    *,
    commit: str,
    image_tag: str,
    image_id: str,
) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != IMAGE_BUILD_AUTHORITY_BINDING_KEYS:
        raise RuntimeError(RECEIPT_CONFLICT_ERROR)
    producer_sha256 = value.get("producer_sha256")
    image_reused = value.get("image_reused")
    authority = value.get("authority")
    if (
        value.get("receipt_schema") != RECEIPT_SCHEMA
        or not isinstance(value.get("receipt_path"), str)
        or not Path(str(value["receipt_path"])).is_absolute()
        or str(
            Path(os.path.abspath(os.fspath(Path(str(value["receipt_path"])))))
        )
        != str(value["receipt_path"])
        or Path(str(value["receipt_path"])).is_symlink()
        or not isinstance(value.get("receipt_sha256"), str)
        or len(str(value["receipt_sha256"])) != 64
        or any(
            character not in "0123456789abcdef"
            for character in str(value["receipt_sha256"])
        )
        or value.get("image_tag") != image_tag
        or value.get("image_id") != image_id
        or value.get("runtime_source_revision") != commit
        or not isinstance(producer_sha256, str)
        or len(producer_sha256) != 64
        or any(character not in "0123456789abcdef" for character in producer_sha256)
        or not isinstance(image_reused, bool)
        or not isinstance(authority, dict)
    ):
        raise RuntimeError(RECEIPT_CONFLICT_ERROR)
    operations = authority.get("operations")
    if not isinstance(operations, list):
        raise RuntimeError(RECEIPT_CONFLICT_ERROR)
    builder_created = bool(
        operations
        and isinstance(operations[0], dict)
        and operations[0].get("operation") == "builder_create"
    )
    _validate_image_build_authority(
        authority,
        image_reused=image_reused,
        builder_created=builder_created,
    )
    return dict(value)


def _validate_replay_image_inspection(
    inspection: dict[str, object],
    *,
    commit: str,
    created_at: str,
    image_reused: bool,
    rootfs_layer_count: int,
) -> None:
    config = inspection.get("Config")
    rootfs = inspection.get("RootFS")
    if not isinstance(config, dict) or not isinstance(rootfs, dict):
        raise RuntimeError(RECEIPT_CONFLICT_ERROR)
    labels = config.get("Labels")
    configured_environment = config.get("Env")
    layers = rootfs.get("Layers")
    if (
        not isinstance(labels, dict)
        or labels.get("org.opencontainers.image.revision") != commit
        or (
            not image_reused
            and labels.get("org.opencontainers.image.created") != created_at
        )
        or not isinstance(configured_environment, list)
        or not isinstance(layers, list)
        or len(layers) != rootfs_layer_count
    ):
        raise RuntimeError(RECEIPT_CONFLICT_ERROR)
    revisions = [
        item.split("=", 1)[1]
        for item in configured_environment
        if isinstance(item, str)
        and "=" in item
        and item.split("=", 1)[0] == "EA_SOURCE_REVISION"
    ]
    if revisions != [commit]:
        raise RuntimeError(RECEIPT_CONFLICT_ERROR)
    for item in configured_environment:
        if (
            not isinstance(item, str)
            or item.split("=", 1)[0] in FORBIDDEN_IMAGE_ENV_NAMES
        ):
            raise RuntimeError(RECEIPT_CONFLICT_ERROR)


def _replayed_success_receipt(
    receipt_path: Path,
    *,
    commit: str,
    image_tag: str,
    producer_sha256: str,
    current_entry: dict[str, object],
) -> dict[str, object] | None:
    encoded = _read_existing_build_receipt(receipt_path)
    if encoded is None:
        return None
    payload = _canonical_success_receipt(encoded)
    image_reused = _validate_success_receipt_shape(
        payload,
        commit=commit,
        image_tag=image_tag,
        producer_sha256=producer_sha256,
    )
    _require_build_authority_current(
        payload.get("image_build_authority"),
        current_entry=current_entry,
    )
    expected_image_id = str(payload.get("image_id") or "")
    try:
        initial_image_id = _listed_image_id(image_tag)
        if initial_image_id != expected_image_id:
            raise RuntimeError(RECEIPT_CONFLICT_ERROR)
        image_id, inspection = _image_inspection(image_tag, expected_commit=commit)
        if image_id != expected_image_id:
            raise RuntimeError(RECEIPT_CONFLICT_ERROR)
        _validate_replay_image_inspection(
            inspection,
            commit=commit,
            created_at=str(payload.get("created_at") or ""),
            image_reused=image_reused,
            rootfs_layer_count=int(payload.get("rootfs_layer_count") or 0),
        )
        if _listed_image_id(image_tag) != expected_image_id:
            raise RuntimeError(RECEIPT_CONFLICT_ERROR)
    except (
        OSError,
        ValueError,
        RuntimeError,
        subprocess.SubprocessError,
        json.JSONDecodeError,
        UnicodeError,
    ) as exc:
        if isinstance(exc, RuntimeError) and str(exc) == RECEIPT_CONFLICT_ERROR:
            raise
        raise RuntimeError(RECEIPT_CONFLICT_ERROR) from exc
    return payload


def _is_build_receipt_temporary_name(name: str, *, final_name: str) -> bool:
    parts = name.split(".")
    current_name = (
        len(parts) == 5
        and parts[0] == ""
        and parts[1] == RECEIPT_TEMP_BASENAME
        and parts[2].isdigit()
        and len(parts[3]) == 24
        and all(character in "0123456789abcdef" for character in parts[3])
        and parts[4] == "tmp"
    )
    # The immediately preceding writer used tempfile.mkstemp with this
    # destination-bound prefix.  Accept that strict eight-character suffix so
    # an upgrade can also finish an already-stranded hard-link window.
    legacy_prefix = f".{final_name}."
    legacy_suffix = (
        name[len(legacy_prefix) :] if name.startswith(legacy_prefix) else ""
    )
    legacy_name = len(legacy_suffix) == 8 and all(
        character in "abcdefghijklmnopqrstuvwxyz0123456789_"
        for character in legacy_suffix
    )
    return current_name or legacy_name


def _reconcile_interrupted_build_receipt_publication(
    path: Path,
    *,
    expected: bytes | None,
) -> tuple[bool, bytes | None]:
    """Normalize the one recoverable hard-link window used by ``_atomic_json``."""

    normalized, parent = _trusted_receipt_parent(path)
    directory_descriptor = os.open(
        parent,
        os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
    )
    recovery_descriptor = -1
    recovery_identity: os.stat_result | None = None
    recovery_mutation_attempted = False
    known_conflict = False
    conflict_durably_normalized = False
    try:
        try:
            final = os.stat(
                normalized.name,
                dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            return False, None
        if (
            not stat.S_ISREG(final.st_mode)
            or final.st_uid != os.getuid()
            or final.st_nlink != 2
            or stat.S_IMODE(final.st_mode) != 0o600
            or final.st_size <= 0
            or final.st_size > RECEIPT_MAX_BYTES
        ):
            return False, None

        recognized_names: list[str] = []
        matches: list[str] = []
        for name in os.listdir(directory_descriptor):
            if name == normalized.name or not _is_build_receipt_temporary_name(
                name,
                final_name=normalized.name,
            ):
                continue
            recognized_names.append(name)
            try:
                candidate = os.stat(
                    name,
                    dir_fd=directory_descriptor,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                continue
            if (
                stat.S_ISREG(candidate.st_mode)
                and candidate.st_uid == final.st_uid
                and candidate.st_dev == final.st_dev
                and candidate.st_ino == final.st_ino
                and candidate.st_nlink == 2
                and stat.S_IMODE(candidate.st_mode) == 0o600
                and candidate.st_size == final.st_size
            ):
                matches.append(name)
        if len(recognized_names) != 1 or matches != recognized_names:
            return False, None

        observed, opened = _read_build_receipt_entry(
            directory_descriptor,
            normalized.name,
            required_nlink=2,
        )
        try:
            recovery_descriptor = os.open(
                normalized.name,
                os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=directory_descriptor,
            )
            recovery_identity = os.fstat(recovery_descriptor)
        except OSError as exc:
            raise RuntimeError(RECEIPT_PATH_ERROR) from exc
        if (
            recovery_identity is None
            or _receipt_metadata_identity(recovery_identity)
            != _receipt_metadata_identity(opened)
        ):
            raise RuntimeError(RECEIPT_PATH_ERROR)
        temporary = os.stat(
            matches[0],
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
        if (
            temporary.st_dev != opened.st_dev
            or temporary.st_ino != opened.st_ino
            or temporary.st_nlink != 2
        ):
            raise RuntimeError(RECEIPT_PATH_ERROR)
        # Without caller-supplied expected bytes, the securely observed inode is
        # the no-replace authority.  Preserve its final name on later recovery
        # faults; only an exact expected-byte retry may roll its own staged inode
        # back completely and publish again.
        known_conflict = expected is None or observed != expected
        accepted = observed if expected is None else expected

        # Whether the bytes match or conflict, retire the recognized private
        # staging name first so a prior killed writer cannot leave nlink > 1.
        try:
            # The unlink may commit before its caller observes an exception.
            # From this point through exact durable validation, the retained
            # descriptor authorizes rollback of this inode's names only.
            recovery_mutation_attempted = True
            os.unlink(matches[0], dir_fd=directory_descriptor)
            os.fsync(directory_descriptor)
            remaining, published = _read_build_receipt_entry(
                directory_descriptor,
                normalized.name,
                required_nlink=1,
            )
            if (
                published.st_dev != opened.st_dev
                or published.st_ino != opened.st_ino
            ):
                raise RuntimeError(RECEIPT_PATH_ERROR)
            if observed != accepted or remaining != accepted:
                known_conflict = True
                conflict_durably_normalized = True
                raise RuntimeError(RECEIPT_CONFLICT_ERROR)
            return True, observed
        except BaseException as exc:
            if not recovery_mutation_attempted or conflict_durably_normalized:
                raise
            cleanup_failed = False
            retained = recovery_identity
            if recovery_descriptor >= 0:
                try:
                    retained = os.fstat(recovery_descriptor)
                except OSError:
                    cleanup_failed = True
            if retained is not None:
                # A securely read conflict predates this recovery call and is
                # the no-replace authority.  Preserve its final name across
                # later fsync/read faults while retiring only the recognized
                # staging link.  Exact-byte recovery faults instead roll back
                # every name for the retained staged inode so retry can publish.
                cleanup_names = (
                    (matches[0],)
                    if known_conflict
                    else (normalized.name, matches[0])
                )
                for name in cleanup_names:
                    try:
                        current = os.stat(
                            name,
                            dir_fd=directory_descriptor,
                            follow_symlinks=False,
                        )
                        if (
                            current.st_dev == retained.st_dev
                            and current.st_ino == retained.st_ino
                        ):
                            os.unlink(name, dir_fd=directory_descriptor)
                    except FileNotFoundError:
                        pass
                    except OSError:
                        cleanup_failed = True
            try:
                os.fsync(directory_descriptor)
            except OSError:
                cleanup_failed = True
            if cleanup_failed:
                raise RuntimeError(RECEIPT_WRITE_ERROR) from exc
            raise
    finally:
        if recovery_descriptor >= 0:
            with suppress(OSError):
                os.close(recovery_descriptor)
        with suppress(OSError):
            os.close(directory_descriptor)


def _complete_interrupted_build_receipt_publication(
    path: Path,
    expected: bytes,
) -> bool:
    completed, _observed = _reconcile_interrupted_build_receipt_publication(
        path,
        expected=expected,
    )
    return completed


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    encoded = _build_receipt_bytes(payload)
    if not encoded or len(encoded) > RECEIPT_MAX_BYTES:
        raise RuntimeError(RECEIPT_WRITE_ERROR)
    normalized, parent = _trusted_receipt_parent(path)
    if _complete_interrupted_build_receipt_publication(normalized, encoded):
        return
    existing = _read_build_receipt(normalized, missing_ok=True)
    if existing is not None:
        if existing == encoded:
            return
        raise RuntimeError(RECEIPT_CONFLICT_ERROR)

    directory_descriptor = os.open(
        parent,
        os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
    )
    descriptor = -1
    temporary_name = ""
    publication_attempted = False
    staged: os.stat_result | None = None
    try:
        temporary_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC
        temporary_flags |= getattr(os, "O_NOFOLLOW", 0)
        for _attempt in range(RECEIPT_TEMP_CREATE_ATTEMPTS):
            temporary_name = (
                f".{RECEIPT_TEMP_BASENAME}.{os.getpid()}."
                f"{secrets.token_hex(12)}.tmp"
            )
            try:
                descriptor = os.open(
                    temporary_name,
                    temporary_flags,
                    0o600,
                    dir_fd=directory_descriptor,
                )
                break
            except FileExistsError:
                continue
        if descriptor < 0:
            raise RuntimeError(RECEIPT_WRITE_ERROR)
        os.fchmod(descriptor, 0o600)
        staged = os.fstat(descriptor)
        if (
            not stat.S_ISREG(staged.st_mode)
            or staged.st_uid != os.getuid()
            or staged.st_nlink != 1
            or stat.S_IMODE(staged.st_mode) != 0o600
        ):
            raise RuntimeError(RECEIPT_WRITE_ERROR)
        view = memoryview(encoded)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise RuntimeError(RECEIPT_WRITE_ERROR)
            view = view[written:]
        os.fsync(descriptor)
        staged = os.fstat(descriptor)
        if (
            not stat.S_ISREG(staged.st_mode)
            or staged.st_uid != os.getuid()
            or staged.st_nlink != 1
            or stat.S_IMODE(staged.st_mode) != 0o600
            or staged.st_size != len(encoded)
        ):
            raise RuntimeError(RECEIPT_WRITE_ERROR)
        try:
            # Treat the final name as possibly published before entering the
            # syscall.  A wrapper or asynchronous failure can be observed only
            # after the kernel has committed the hard link.
            publication_attempted = True
            os.link(
                temporary_name,
                normalized.name,
                src_dir_fd=directory_descriptor,
                dst_dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
        except FileExistsError as exc:
            if _complete_interrupted_build_receipt_publication(normalized, encoded):
                os.unlink(temporary_name, dir_fd=directory_descriptor)
                temporary_name = ""
                os.fsync(directory_descriptor)
                return
            existing = _read_build_receipt(normalized)
            if existing != encoded:
                raise RuntimeError(RECEIPT_CONFLICT_ERROR) from exc
            os.unlink(temporary_name, dir_fd=directory_descriptor)
            temporary_name = ""
            os.fsync(directory_descriptor)
            return
        linked = os.stat(
            normalized.name,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISREG(linked.st_mode)
            or linked.st_uid != staged.st_uid
            or linked.st_dev != staged.st_dev
            or linked.st_ino != staged.st_ino
            or linked.st_nlink != 2
            or stat.S_IMODE(linked.st_mode) != 0o600
            or linked.st_size != len(encoded)
        ):
            raise RuntimeError(RECEIPT_WRITE_ERROR)
        staged_name = os.stat(
            temporary_name,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
        if (
            staged_name.st_dev != staged.st_dev
            or staged_name.st_ino != staged.st_ino
            or staged_name.st_nlink != 2
        ):
            raise RuntimeError(RECEIPT_WRITE_ERROR)
        os.unlink(temporary_name, dir_fd=directory_descriptor)
        temporary_name = ""
        os.fsync(directory_descriptor)
        if _read_build_receipt(normalized) != encoded:
            raise RuntimeError(RECEIPT_WRITE_ERROR)
        publication_attempted = False
    except BaseException as exc:
        cleanup_failed = False
        current_staged = staged
        if descriptor >= 0:
            try:
                current_staged = os.fstat(descriptor)
            except OSError:
                cleanup_failed = True
        if publication_attempted and current_staged is not None:
            try:
                current = os.stat(
                    normalized.name,
                    dir_fd=directory_descriptor,
                    follow_symlinks=False,
                )
                # The staged descriptor stays open until this finally path, so
                # its inode cannot be recycled.  Device/inode equality is the
                # exact authority to remove our published name even if the
                # triggering failure was a concurrent metadata change.
                if (
                    current.st_dev == current_staged.st_dev
                    and current.st_ino == current_staged.st_ino
                ):
                    os.unlink(normalized.name, dir_fd=directory_descriptor)
            except FileNotFoundError:
                pass
            except OSError:
                cleanup_failed = True
        if temporary_name and current_staged is not None:
            try:
                temporary = os.stat(
                    temporary_name,
                    dir_fd=directory_descriptor,
                    follow_symlinks=False,
                )
                if (
                    temporary.st_dev == current_staged.st_dev
                    and temporary.st_ino == current_staged.st_ino
                ):
                    os.unlink(temporary_name, dir_fd=directory_descriptor)
                    temporary_name = ""
                else:
                    cleanup_failed = True
            except FileNotFoundError:
                temporary_name = ""
            except OSError:
                cleanup_failed = True
        try:
            os.fsync(directory_descriptor)
        except OSError:
            cleanup_failed = True
        if cleanup_failed:
            raise RuntimeError(RECEIPT_WRITE_ERROR) from exc
        raise
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        os.close(directory_descriptor)


def build_image(
    *,
    source_root: Path,
    ref: str,
    tag: str,
    receipt_path: Path,
    vexp_state_path: Path = DEFAULT_SENTINEL_STATE_PATH,
    vexp_state_owner_uid: int | None = None,
    vexp_authority: CandidateVexpMutationAuthority | None = None,
) -> dict[str, object]:
    _require_credential_exposure_remediation()
    # Enforce same-owner, single-link, non-writable producer identity before
    # even creating/acquiring a per-UID lock. This makes sudo/root invocation of
    # a tibor-owned producer fail closed before Docker or lock-file mutation.
    _producer_sha256()
    authority = vexp_authority or candidate_vexp_authority(
        state_path=Path(vexp_state_path),
        state_owner_uid=(
            os.geteuid()
            if vexp_state_owner_uid is None
            else vexp_state_owner_uid
        ),
    )
    authority.require_current()
    with _exclusive_build_lock():
        entry_evidence = authority.require_current()
        return _build_image_locked(
            source_root=source_root,
            ref=ref,
            tag=tag,
            receipt_path=receipt_path,
            authority=authority,
            entry_evidence=entry_evidence,
        )


def _build_image_locked(
    *,
    source_root: Path,
    ref: str,
    tag: str,
    receipt_path: Path,
    authority: CandidateVexpMutationAuthority,
    entry_evidence: dict[str, object],
) -> dict[str, object]:
    source_root = source_root.expanduser().resolve()
    if not (source_root / ".git").exists():
        raise ValueError("manfred_image_source_repo_invalid")
    commit = _commit_for_ref(source_root, ref)
    safe_tag = _safe_tag(tag, commit=commit)
    producer_digest = _producer_sha256()
    replayed_receipt = _replayed_success_receipt(
        receipt_path,
        commit=commit,
        image_tag=safe_tag,
        producer_sha256=producer_digest,
        current_entry=entry_evidence,
    )
    if replayed_receipt is not None:
        return replayed_receipt
    created_at = (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
    root_free_observations: dict[str, int] = {}
    authority_operations: list[dict[str, object]] = []
    _record_root_free_or_deny(
        stage="after_lock",
        root_free_observations=root_free_observations,
        commit=commit,
        image_tag=safe_tag,
        created_at=created_at,
        producer_sha256=producer_digest,
        builder_created=False,
        builder_validated=False,
        receipt_path=receipt_path,
    )
    preexisting_image_id = _listed_image_id(safe_tag)
    if preexisting_image_id is not None:
        try:
            image_id, inspection = _image_inspection(safe_tag, expected_commit=commit)
            if image_id != preexisting_image_id:
                raise RuntimeError(EXISTING_IMAGE_MISMATCH_ERROR)
            _verify_image_filesystem_authorized(
                image_id,
                authority=authority,
                operations=authority_operations,
            )
            if _listed_image_id(safe_tag) != preexisting_image_id:
                raise RuntimeError(EXISTING_IMAGE_MISMATCH_ERROR)
        except (
            OSError,
            ValueError,
            RuntimeError,
            subprocess.SubprocessError,
            json.JSONDecodeError,
            UnicodeError,
        ) as exc:
            raise RuntimeError(EXISTING_IMAGE_MISMATCH_ERROR) from exc
        admission = _admission_evidence(
            producer_sha256=producer_digest,
            root_free_observations=root_free_observations,
            builder_created=False,
            docker_build_started=False,
        )
        return _publish_success_receipt(
            receipt_path,
            authority=authority,
            entry_evidence=entry_evidence,
            operations=authority_operations,
            authority_basis="preexisting_image_current_authority_probe",
            receipt_fields={
                "commit": commit,
                "image_tag": safe_tag,
                "image_id": image_id,
                "inspection": inspection,
                "created_at": created_at,
                "builder_created": False,
                "builder_validated": False,
                "image_reused": True,
                "cache_prune_status": "not_run_existing_image_reused",
                "admission": admission,
                "producer_sha256": producer_digest,
            },
        )

    with tempfile.TemporaryDirectory(prefix="ea-manfred-image-") as temporary:
        context = Path(temporary) / "context"
        context.mkdir(mode=0o700)
        _materialize_tracked_context(
            source_root=source_root,
            commit=commit,
            destination=context,
        )
        dockerfile = context / "ea" / "Dockerfile"
        if not dockerfile.is_file():
            raise RuntimeError("manfred_image_dockerfile_missing")
        _record_root_free_or_deny(
            stage="after_context",
            root_free_observations=root_free_observations,
            commit=commit,
            image_tag=safe_tag,
            created_at=created_at,
            producer_sha256=producer_digest,
            builder_created=False,
            builder_validated=False,
            receipt_path=receipt_path,
        )
        builder_created = _ensure_dedicated_builder(authority, authority_operations)
        build_command = [
            "docker",
            "buildx",
            "build",
            "--builder",
            BUILDX_BUILDER_NAME,
            "--load",
            "--file",
            str(dockerfile),
            "--tag",
            safe_tag,
            "--build-arg",
            f"EA_SOURCE_REVISION={commit}",
            "--label",
            f"org.opencontainers.image.revision={commit}",
            "--label",
            f"org.opencontainers.image.created={created_at}",
            "--label",
            "org.opencontainers.image.title=EA Manfred Memorial candidate",
            "--label",
            "org.opencontainers.image.source=git:EA",
            str(context),
        ]
        _record_root_free_or_deny(
            stage="immediately_before_build",
            root_free_observations=root_free_observations,
            commit=commit,
            image_tag=safe_tag,
            created_at=created_at,
            producer_sha256=producer_digest,
            builder_created=builder_created,
            builder_validated=True,
            receipt_path=receipt_path,
        )
        docker_build_started = False
        try:
            with _authorized_operation(
                authority,
                authority_operations,
                operation="image_build",
                argv=build_command,
                target=safe_tag,
                minimum_validity_seconds=3000,
            ) as lease:
                with _authorized_run_timeout(lease.command_timeout(3000)):
                    docker_build_started = True
                    _run(build_command, stdout=None)
        except (
            OSError,
            ValueError,
            RuntimeError,
            subprocess.SubprocessError,
            UnicodeError,
        ) as exc:
            admission = _admission_evidence(
                producer_sha256=producer_digest,
                root_free_observations=root_free_observations,
                builder_created=builder_created,
                docker_build_started=docker_build_started,
            )
            cache_prune_status = "fail"
            try:
                _prune_dedicated_builder_cache(authority, authority_operations)
                cache_prune_status = "pass"
            except (OSError, RuntimeError, subprocess.SubprocessError):
                pass
            try:
                partial_image_id = _listed_image_id(safe_tag)
            except (OSError, RuntimeError, subprocess.SubprocessError):
                cleanup_status = "not_removed_identity_unavailable"
            else:
                cleanup_status = _cleanup_new_image(
                    safe_tag,
                    expected_image_id=partial_image_id,
                    authority=authority,
                    operations=authority_operations,
                )
            failure_receipt = {
                "schema": RECEIPT_SCHEMA,
                "status": "fail",
                "error": BUILDX_BUILD_ERROR,
                "commit": commit,
                "image_tag": safe_tag,
                "created_at": created_at,
                "buildx_builder_name": BUILDX_BUILDER_NAME,
                "buildx_builder_driver": BUILDX_BUILDER_DRIVER,
                "buildx_builder_node_name": BUILDX_BUILDER_NODE_NAME,
                "buildx_builder_endpoint": BUILDX_BUILDER_ENDPOINT,
                "buildx_builder_created": builder_created,
                "buildx_builder_validated": True,
                "buildx_load_completed": False,
                "preexisting_image": False,
                "new_image_cleanup_status": cleanup_status,
                "build_cache_scope": "dedicated_builder_only",
                "build_cache_prune": _cache_policy_receipt(
                    status=cache_prune_status
                ),
                "admission": admission,
                "global_build_cache_pruned": False,
                "live_or_rollback_images_pruned": False,
                "runtime_secrets_included": False,
            }
            _atomic_json(receipt_path, failure_receipt)
            raise RuntimeError(BUILDX_BUILD_ERROR) from exc
        admission = _admission_evidence(
            producer_sha256=producer_digest,
            root_free_observations=root_free_observations,
            builder_created=builder_created,
            docker_build_started=True,
        )

    post_build_image_id: str | None = None
    cache_prune_status = "not_run"
    try:
        post_build_image_id = _listed_image_id(safe_tag)
        if post_build_image_id is None:
            raise RuntimeError(POST_BUILD_VERIFY_ERROR)
        cache_prune_status = "fail"
        _prune_dedicated_builder_cache(authority, authority_operations)
        cache_prune_status = "pass"
        image_id, inspection = _image_inspection(safe_tag, expected_commit=commit)
        if image_id != post_build_image_id:
            raise RuntimeError(POST_BUILD_VERIFY_ERROR)
        _verify_image_filesystem_authorized(
            image_id,
            authority=authority,
            operations=authority_operations,
        )
        if _listed_image_id(safe_tag) != post_build_image_id:
            raise RuntimeError(POST_BUILD_VERIFY_ERROR)
    except (
        OSError,
        ValueError,
        RuntimeError,
        subprocess.SubprocessError,
        json.JSONDecodeError,
        UnicodeError,
    ) as exc:
        cleanup_status = _cleanup_new_image(
            safe_tag,
            expected_image_id=post_build_image_id,
            authority=authority,
            operations=authority_operations,
        )
        failure_receipt = {
            "schema": RECEIPT_SCHEMA,
            "status": "fail",
            "error": POST_BUILD_VERIFY_ERROR,
            "commit": commit,
            "image_tag": safe_tag,
            "created_at": created_at,
            "buildx_builder_name": BUILDX_BUILDER_NAME,
            "buildx_builder_driver": BUILDX_BUILDER_DRIVER,
            "buildx_builder_node_name": BUILDX_BUILDER_NODE_NAME,
            "buildx_builder_endpoint": BUILDX_BUILDER_ENDPOINT,
            "buildx_builder_created": builder_created,
            "buildx_builder_validated": True,
            "buildx_load_completed": True,
            "preexisting_image": False,
            "new_image_cleanup_status": cleanup_status,
            "build_cache_scope": "dedicated_builder_only",
            "build_cache_prune": _cache_policy_receipt(
                status=cache_prune_status
            ),
            "admission": admission,
            "global_build_cache_pruned": False,
            "live_or_rollback_images_pruned": False,
            "runtime_secrets_included": False,
        }
        _atomic_json(receipt_path, failure_receipt)
        raise RuntimeError(POST_BUILD_VERIFY_ERROR) from exc

    return _publish_success_receipt(
        receipt_path,
        authority=authority,
        entry_evidence=entry_evidence,
        operations=authority_operations,
        authority_basis="new_image_build",
        receipt_fields={
            "commit": commit,
            "image_tag": safe_tag,
            "image_id": image_id,
            "inspection": inspection,
            "created_at": created_at,
            "builder_created": builder_created,
            "builder_validated": True,
            "image_reused": False,
            "cache_prune_status": cache_prune_status,
            "admission": admission,
            "producer_sha256": producer_digest,
        },
    )


def _self_test() -> dict[str, object]:
    if SOAK_ROOT_FREE_FLOOR_BYTES != 20 * 1024**3:
        raise RuntimeError("manfred_image_self_test_soak_floor_failed")
    if BUILD_ROOT_FREE_HEADROOM_BYTES != 15 * 1024**3:
        raise RuntimeError("manfred_image_self_test_build_headroom_failed")
    if MINIMUM_ROOT_FREE_BYTES != 35 * 1024**3:
        raise RuntimeError("manfred_image_self_test_total_threshold_failed")
    if _root_disk_admissible(MINIMUM_ROOT_FREE_BYTES - 1):
        raise RuntimeError("manfred_image_self_test_disk_boundary_failed")
    if not _root_disk_admissible(MINIMUM_ROOT_FREE_BYTES):
        raise RuntimeError("manfred_image_self_test_disk_boundary_failed")
    if not _root_disk_admissible(MINIMUM_ROOT_FREE_BYTES + 1):
        raise RuntimeError("manfred_image_self_test_disk_boundary_failed")
    if _root_disk_admissible(True):
        raise RuntimeError("manfred_image_self_test_disk_type_failed")
    try:
        _require_root_disk_capacity(free_bytes=MINIMUM_ROOT_FREE_BYTES - 1)
    except RuntimeError as exc:
        if str(exc) != DISK_SPACE_ERROR:
            raise RuntimeError("manfred_image_self_test_disk_error_failed") from exc
    else:
        raise RuntimeError("manfred_image_self_test_disk_error_failed")

    commit = "a" * 40
    manfred_tag = f"ea-runtime:manfred-{commit}"
    memorial_tag = f"ea-runtime:memorial-{commit}"
    if _safe_tag("", commit=commit) != manfred_tag:
        raise RuntimeError("manfred_image_self_test_default_tag_failed")
    if _safe_tag(manfred_tag, commit=commit) != manfred_tag:
        raise RuntimeError("manfred_image_self_test_manfred_tag_failed")
    if _safe_tag(memorial_tag, commit=commit) != memorial_tag:
        raise RuntimeError("manfred_image_self_test_memorial_tag_failed")
    rejected_tags = (
        f"ea-runtime:other-{commit}",
        f"ea-runtime:manfred-{commit[:12]}",
        f"ea-runtime:memorial-{'b' * 40}",
        f" {manfred_tag}",
        f"{memorial_tag} ",
        manfred_tag.upper(),
        "latest",
    )
    for rejected_tag in rejected_tags:
        try:
            _safe_tag(rejected_tag, commit=commit)
        except ValueError:
            pass
        else:
            raise RuntimeError("manfred_image_self_test_tag_rejection_failed")
    try:
        _safe_tag("", commit=commit[:39])
    except ValueError as exc:
        if str(exc) != "manfred_image_commit_invalid":
            raise RuntimeError(
                "manfred_image_self_test_commit_rejection_failed"
            ) from exc
    else:
        raise RuntimeError("manfred_image_self_test_commit_rejection_failed")

    nested_rejected = False
    stale_file_reusable = False
    denial_schema_verified = False
    denial_mode_verified = False
    producer_digest_verified = False
    with tempfile.TemporaryDirectory(prefix="ea-manfred-lock-test-") as temporary:
        lock_directory = Path(temporary)
        lock_directory.chmod(0o700)
        with _exclusive_build_lock(lock_directory=lock_directory):
            try:
                with _exclusive_build_lock(lock_directory=lock_directory):
                    raise RuntimeError("manfred_image_self_test_nested_lock_entered")
            except RuntimeError as exc:
                if str(exc) != BUILD_BUSY_ERROR:
                    raise
                nested_rejected = True
        with _exclusive_build_lock(lock_directory=lock_directory):
            stale_file_reusable = True

        producer_path = lock_directory / "producer.py"
        producer_path.write_bytes(b"deterministic producer fixture\n")
        expected_producer_digest = hashlib.sha256(producer_path.read_bytes()).hexdigest()
        producer_digest_verified = (
            _producer_sha256(producer_path=producer_path)
            == expected_producer_digest
        )
        observations = {
            "after_lock": MINIMUM_ROOT_FREE_BYTES,
            "after_context": MINIMUM_ROOT_FREE_BYTES,
            "immediately_before_build": MINIMUM_ROOT_FREE_BYTES - 1,
        }
        denial = _disk_denial_receipt(
            commit=commit,
            image_tag=memorial_tag,
            created_at="2026-07-13T00:00:00Z",
            producer_sha256=expected_producer_digest,
            root_free_observations=observations,
            builder_created=True,
            builder_validated=True,
        )
        admission = denial.get("admission")
        denial_schema_verified = (
            denial.get("schema") == RECEIPT_SCHEMA
            and denial.get("status") == "fail"
            and denial.get("error") == DISK_SPACE_ERROR
            and denial.get("source_commit") == commit
            and denial.get("producer_sha256") == expected_producer_digest
            and denial.get("denied_stage") == "immediately_before_build"
            and denial.get("docker_build_started") is False
            and isinstance(denial.get("mutations_performed"), int)
            and not isinstance(denial.get("mutations_performed"), bool)
            and denial.get("mutations_performed") == 1
            and denial.get("mutations_performed_exact") is True
            and denial.get("mutation_scope") == "docker"
            and denial.get("mutation_unit") == "mutating_cli_command"
            and isinstance(admission, dict)
            and admission.get("soak_root_free_floor_bytes")
            == SOAK_ROOT_FREE_FLOOR_BYTES
            and admission.get("build_root_free_headroom_bytes")
            == BUILD_ROOT_FREE_HEADROOM_BYTES
            and admission.get("minimum_root_free_bytes")
            == MINIMUM_ROOT_FREE_BYTES
            and admission.get("root_free_bytes") == observations
            and admission.get("docker_build_started") is False
            and admission.get("docker_mutations_before_build") == 1
        )
        receipt_path = lock_directory / "disk-denial.json"
        _atomic_json(receipt_path, denial)
        denial_mode_verified = (
            stat.S_IMODE(receipt_path.stat().st_mode) == 0o600
            and json.loads(receipt_path.read_text(encoding="utf-8")) == denial
        )
        early_denial = _disk_denial_receipt(
            commit=commit,
            image_tag=manfred_tag,
            created_at="2026-07-13T00:00:00Z",
            producer_sha256=expected_producer_digest,
            root_free_observations={
                "after_lock": MINIMUM_ROOT_FREE_BYTES - 1,
            },
            builder_created=False,
            builder_validated=False,
        )
        if (
            early_denial.get("denied_stage") != "after_lock"
            or early_denial.get("mutations_performed") != 0
        ):
            raise RuntimeError("manfred_image_self_test_early_denial_failed")
        try:
            _admission_evidence(
                producer_sha256=expected_producer_digest,
                root_free_observations={
                    "after_context": MINIMUM_ROOT_FREE_BYTES,
                },
                builder_created=False,
                docker_build_started=False,
            )
        except ValueError as exc:
            if str(exc) != "manfred_image_admission_observation_order_invalid":
                raise
        else:
            raise RuntimeError("manfred_image_self_test_schema_order_failed")

    if (
        not nested_rejected
        or not stale_file_reusable
        or not denial_schema_verified
        or not denial_mode_verified
        or not producer_digest_verified
    ):
        raise RuntimeError("manfred_image_self_test_lock_failed")
    return {
        "schema": SELF_TEST_SCHEMA,
        "status": "pass",
        "soak_root_free_floor_bytes": SOAK_ROOT_FREE_FLOOR_BYTES,
        "build_root_free_headroom_bytes": BUILD_ROOT_FREE_HEADROOM_BYTES,
        "minimum_root_free_bytes": MINIMUM_ROOT_FREE_BYTES,
        "threshold_boundary_verified": True,
        "manfred_tag_verified": True,
        "memorial_tag_verified": True,
        "invalid_tags_rejected": True,
        "producer_sha256_helper_verified": True,
        "denial_receipt_schema_verified": True,
        "denial_receipt_mode_0600_verified": True,
        "nested_lock_rejected": True,
        "stale_lock_file_reusable": True,
        "docker_invoked": False,
        "git_invoked": False,
        "network_used": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build an immutable Manfred Memorial image from an exact tracked Git tree."
    )
    parser.add_argument("--source-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--ref", default="HEAD")
    parser.add_argument("--tag", default="")
    parser.add_argument(
        "--receipt",
        default=str(Path("~/.local/share/ea-deploy/manfred-memorial/image-build.json")),
    )
    parser.add_argument(
        "--vexp-state-path",
        help="Absolute schema-v6 sentinel state path validated by the root permit manager.",
    )
    parser.add_argument(
        "--vexp-state-owner-uid",
        type=int,
        help="Expected owner UID for the schema-v6 sentinel state.",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run deterministic disk and lock tests without Docker or Git.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    schema = SELF_TEST_SCHEMA if args.self_test else RECEIPT_SCHEMA
    try:
        if args.self_test:
            receipt = _self_test()
        else:
            if args.vexp_state_path is None or args.vexp_state_owner_uid is None:
                raise ValueError("manfred_candidate_vexp_authority_arguments_required")
            receipt = build_image(
                source_root=Path(args.source_root),
                ref=args.ref,
                tag=args.tag,
                receipt_path=Path(args.receipt),
                vexp_state_path=Path(args.vexp_state_path),
                vexp_state_owner_uid=args.vexp_state_owner_uid,
            )
    except (
        OSError,
        ValueError,
        RuntimeError,
        subprocess.SubprocessError,
        json.JSONDecodeError,
    ) as exc:
        print(
            json.dumps(
                {
                    "schema": schema,
                    "status": "fail",
                    "error": str(exc)[:200],
                    "runtime_secrets_included": False,
                },
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
