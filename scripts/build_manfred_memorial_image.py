#!/usr/bin/env python3
from __future__ import annotations

import argparse
import errno
import fcntl
import hashlib
import json
import os
import shutil
import stat
import subprocess
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


RECEIPT_SCHEMA = "ea.manfred_memorial_image_build.v2"
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
FORBIDDEN_CONTEXT_PATHS = (
    ".env",
    ".env.local",
    "memorial_data",
    "memorial_archive",
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


def _run(
    argv: list[str],
    *,
    cwd: Path | None = None,
    stdout: object | None = subprocess.PIPE,
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        argv,
        cwd=str(cwd) if cwd else None,
        check=True,
        stdin=subprocess.DEVNULL,
        stdout=stdout,
        stderr=subprocess.PIPE,
    )


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
    lowered = tag.lower()
    if (
        not tag
        or tag != tag.strip()
        or any(character.isspace() for character in tag)
    ):
        raise ValueError("manfred_image_tag_invalid")
    if lowered == "latest" or lowered.endswith(":latest"):
        raise ValueError("manfred_image_mutable_tag_forbidden")
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


def _ensure_dedicated_builder() -> bool:
    if _dedicated_builder_driver() is not None:
        _validate_dedicated_builder()
        return False
    created = _run(
        [
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
    ).stdout
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


def _prune_dedicated_builder_cache() -> None:
    _run(
        [
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
    )


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


def _cleanup_new_image(tag: str, *, expected_image_id: str | None) -> str:
    try:
        current_image_id = _listed_image_id(tag)
    except (OSError, RuntimeError, subprocess.CalledProcessError):
        return "not_removed_identity_unavailable"
    if current_image_id is None:
        return "already_absent"
    if expected_image_id is None or current_image_id != expected_image_id:
        return "not_removed_identity_changed"
    try:
        _run(["docker", "image", "rm", tag])
        remaining_image_id = _listed_image_id(tag)
    except (OSError, RuntimeError, subprocess.CalledProcessError):
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
) -> dict[str, object]:
    return {
        "schema": RECEIPT_SCHEMA,
        "status": "pass",
        "commit": commit,
        "image_tag": image_tag,
        "image_id": image_id,
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
    }


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
    forbidden_names = {
        "EA_API_TOKEN",
        "EA_SIGNING_SECRET",
        "DATABASE_URL",
        "UNMIXR_API_KEY",
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
    }
    for item in configured_environment:
        name = str(item).split("=", 1)[0]
        if name in forbidden_names:
            raise RuntimeError("manfred_image_runtime_secret_baked_in")
    return image_id, inspection


def _verify_image_filesystem(tag: str) -> None:
    checks = " && ".join(f"test ! -e {path}" for path in FORBIDDEN_IMAGE_PATHS)
    _run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--entrypoint",
            "/bin/sh",
            tag,
            "-ec",
            checks,
        ]
    )


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        Path(temporary).unlink(missing_ok=True)


def build_image(
    *,
    source_root: Path,
    ref: str,
    tag: str,
    receipt_path: Path,
) -> dict[str, object]:
    # Enforce same-owner, single-link, non-writable producer identity before
    # even creating/acquiring a per-UID lock. This makes sudo/root invocation of
    # a tibor-owned producer fail closed before Docker or lock-file mutation.
    _producer_sha256()
    with _exclusive_build_lock():
        return _build_image_locked(
            source_root=source_root,
            ref=ref,
            tag=tag,
            receipt_path=receipt_path,
        )


def _build_image_locked(
    *,
    source_root: Path,
    ref: str,
    tag: str,
    receipt_path: Path,
) -> dict[str, object]:
    source_root = source_root.expanduser().resolve()
    if not (source_root / ".git").exists():
        raise ValueError("manfred_image_source_repo_invalid")
    commit = _commit_for_ref(source_root, ref)
    safe_tag = _safe_tag(tag, commit=commit)
    created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    producer_digest = _producer_sha256()
    root_free_observations: dict[str, int] = {}
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
            _verify_image_filesystem(safe_tag)
            if _listed_image_id(safe_tag) != preexisting_image_id:
                raise RuntimeError(EXISTING_IMAGE_MISMATCH_ERROR)
        except (
            OSError,
            ValueError,
            RuntimeError,
            subprocess.CalledProcessError,
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
        receipt = _success_receipt(
            commit=commit,
            image_tag=safe_tag,
            image_id=image_id,
            inspection=inspection,
            created_at=created_at,
            builder_created=False,
            builder_validated=False,
            image_reused=True,
            cache_prune_status="not_run_existing_image_reused",
            admission=admission,
        )
        _atomic_json(receipt_path, receipt)
        return receipt

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
        builder_created = _ensure_dedicated_builder()
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
        try:
            _run(build_command, stdout=None)
        except (
            OSError,
            ValueError,
            RuntimeError,
            subprocess.CalledProcessError,
            UnicodeError,
        ) as exc:
            admission = _admission_evidence(
                producer_sha256=producer_digest,
                root_free_observations=root_free_observations,
                builder_created=builder_created,
                docker_build_started=isinstance(
                    exc, subprocess.CalledProcessError
                ),
            )
            cache_prune_status = "fail"
            try:
                _prune_dedicated_builder_cache()
                cache_prune_status = "pass"
            except (OSError, RuntimeError, subprocess.CalledProcessError):
                pass
            try:
                partial_image_id = _listed_image_id(safe_tag)
            except (OSError, RuntimeError, subprocess.CalledProcessError):
                cleanup_status = "not_removed_identity_unavailable"
            else:
                cleanup_status = _cleanup_new_image(
                    safe_tag,
                    expected_image_id=partial_image_id,
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
        _prune_dedicated_builder_cache()
        cache_prune_status = "pass"
        image_id, inspection = _image_inspection(safe_tag, expected_commit=commit)
        if image_id != post_build_image_id:
            raise RuntimeError(POST_BUILD_VERIFY_ERROR)
        _verify_image_filesystem(safe_tag)
        if _listed_image_id(safe_tag) != post_build_image_id:
            raise RuntimeError(POST_BUILD_VERIFY_ERROR)
    except (
        OSError,
        ValueError,
        RuntimeError,
        subprocess.CalledProcessError,
        json.JSONDecodeError,
        UnicodeError,
    ) as exc:
        cleanup_status = _cleanup_new_image(
            safe_tag,
            expected_image_id=post_build_image_id,
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

    receipt = _success_receipt(
        commit=commit,
        image_tag=safe_tag,
        image_id=image_id,
        inspection=inspection,
        created_at=created_at,
        builder_created=builder_created,
        builder_validated=True,
        image_reused=False,
        cache_prune_status=cache_prune_status,
        admission=admission,
    )
    _atomic_json(receipt_path, receipt)
    return receipt


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
            receipt = build_image(
                source_root=Path(args.source_root),
                ref=args.ref,
                tag=args.tag,
                receipt_path=Path(args.receipt),
            )
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
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
