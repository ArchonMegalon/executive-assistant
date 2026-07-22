#!/usr/bin/python3.12
"""Attest or apply one hash-bound finite Manfred capacity request as root.

This file is deliberately self-contained and imports only the Python standard
library.  A hash-bound inline installer copies it and all receipts into a
root-owned private directory before this staged copy is executed.  Target
traversal then uses no-follow file descriptors throughout.
"""

from __future__ import annotations

import argparse
import contextlib
import errno
import fcntl
import hashlib
import json
import os
import pwd
import re
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


ROOT_ATTEST_REQUEST_SCHEMA = (
    "ea.manfred_memorial_build_capacity.root_attest_request.v3"
)
ROOT_ATTESTATION_SCHEMA = "ea.manfred_memorial_build_capacity.root_attestation.v3"
HANDOFF_SCHEMA = "ea.manfred_memorial_build_capacity.root_handoff.v3"
USER_RECEIPT_SCHEMA = "ea.manfred_memorial_build_capacity.user_receipt.v3"
ROOT_RECEIPT_SCHEMA = "ea.manfred_memorial_build_capacity.root_receipt.v3"
DELETION_JOURNAL_SCHEMA = "ea.manfred_memorial_build_capacity.deletion_journal.v3"
DELETION_COMPLETE_SCHEMA = "ea.manfred_memorial_build_capacity.deletion_complete.v3"
PROJECTION_SCHEMA = "ea.manfred_memorial_candidate_projection.v3"
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_SOURCE_BYTES = 4 * 1024 * 1024
MAX_COMMAND_OUTPUT_BYTES = 4 * 1024 * 1024
MAX_TREE_FILES = 200_000
MAX_TREE_ENTRIES = MAX_TREE_FILES + 1
MAX_TREE_BYTES = 4 * 1024**3
MAX_PROJECTIONS = 64
EXPECTED_PROJECTION_COUNT = 26
MAX_PROCESS_REFERENCES = 64
MAX_PROCESS_FDS = 4096
MAX_PROCESS_COUNT = 32_768
MAX_PROCESS_CMDLINE_BYTES = 4 * 1024 * 1024
MAX_PROCESS_ENVIRON_BYTES = 4 * 1024 * 1024
MAX_PROCESS_MAPS_BYTES = 32 * 1024 * 1024
MAX_PROCESS_MOUNTINFO_BYTES = 4 * 1024 * 1024
MAX_ROOT_CANDIDATES = 64
MAX_CONTAINERS = 1024
MAX_MOUNTS_PER_CONTAINER = 256
CONTAINER_INSPECT_CHUNK = 32
CAPACITY_LOCK_NAME = "ea-manfred-build-capacity.lock"
FLEET_LOCK_PATH = Path("/run/lock/ea-manfred-candidate-fleet.lock")
DOCKER_BINARY = Path("/usr/bin/docker")
DOCKER_HOST = "unix:///var/run/docker.sock"
TARGET_ROOT_FREE_BYTES = 15 * 1024**3 + 256 * 1024**2
DEPLOY_ROOT_RELATIVE = Path(".local/share/ea-deploy/manfred-memorial")
ROOT_RECEIPT_DIRECTORY = Path("/var/lib/ea/manfred-root-receipts")
QUARANTINE_ROOT = Path("/var/lib/ea/manfred-capacity-quarantine")
ROOT_STAGE_PARENT = Path("/root")
PYTHON_EXECUTABLE = "/usr/bin/python3.12"
ROOT_INSTALLER_DELIVERY = "sudo_inline_stdlib_stager_v2"
ROOT_STAGE_NAME = re.compile(r"ea-manfred-capacity\.[A-Za-z0-9_-]{4,80}")
ROOT_RECEIPT_NAME = re.compile(
    r"manfred-capacity-[0-9a-z][0-9a-z-]{0,80}\.v3\.json"
)
MAX_MOUNTINFO_BYTES = 2 * 1024 * 1024
MAX_MOUNTINFO_ROWS = 4096
HEX_40 = re.compile(r"[0-9a-f]{40}")
HEX_64 = re.compile(r"[0-9a-f]{64}")
PROJECT = re.compile(r"ea-manfred-candidate-[a-z0-9][a-z0-9_-]{1,100}")
CANDIDATE_ROOT = re.compile(r"candidate-[a-z0-9][a-z0-9-]{7,119}")
VSCODE_SERVER_NAME = re.compile(r"Stable-([0-9a-f]{40})")
ROOT_TEMP_CANDIDATE_PATHS = {
    "temp:chummer6-ui-desktop-build:nuget-packages": Path(
        "/tmp/chummer6-ui-desktop-build/nuget-packages"
    ),
    "temp:chummer6-ui-desktop-build:dotnet-nuget": Path(
        "/tmp/chummer6-ui-desktop-build/dotnet-home/.local/share/NuGet"
    ),
    "temp:chummer-ai:nuget-http-cache": Path(
        "/tmp/chummer-ai/.local/share/NuGet/http-cache"
    ),
    "temp:chummer-hub-dotnet-10.0.103": Path(
        "/tmp/chummer-hub-dotnet-10.0.103"
    ),
    "temp:chummer-powershell-7.4.6": Path(
        "/tmp/chummer-powershell-7.4.6"
    ),
    "temp:chummer-stage-candidate-debug": Path(
        "/tmp/chummer-stage-candidate-debug"
    ),
    "temp:chummer-hub-eta-audit-pytest": Path(
        "/tmp/chummer-hub-eta-audit-pytest"
    ),
    "temp:chummer-core-engine:vexp": Path("/tmp/chummer-core-engine/.vexp"),
    "temp:chummer-core-engine:aider-tags-v4": Path(
        "/tmp/chummer-core-engine/.aider.tags.cache.v4"
    ),
    "temp:chummer-hub-registry:vexp": Path("/tmp/chummer-hub-registry/.vexp"),
}
DELETION_STATUSES = {"removed", "recovered_removed", "already_removed_verified"}
PRESERVED_STATUSES = {
    "preserved_capacity_ready",
    "preserved_not_authorized",
    "preserved_referenced",
}


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _json_bytes(payload: object) -> bytes:
    encoded = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode(
            "utf-8"
        )
        + b"\n"
    )
    if not 1 <= len(encoded) <= MAX_JSON_BYTES:
        raise RuntimeError("manfred_capacity_root_json_size_invalid")
    return encoded


def _canonical_absolute(path: Path, *, must_exist: bool) -> Path:
    if not path.is_absolute() or "\x00" in str(path):
        raise RuntimeError("manfred_capacity_root_path_invalid")
    try:
        resolved = path.resolve(strict=must_exist)
    except OSError as exc:
        raise RuntimeError("manfred_capacity_root_path_invalid") from exc
    if resolved != path:
        raise RuntimeError("manfred_capacity_root_path_invalid")
    return path


def _read_fd_all(descriptor: int, *, maximum: int) -> bytes:
    before = os.fstat(descriptor)
    content = b""
    while len(content) <= maximum:
        chunk = os.read(descriptor, min(65536, maximum + 1 - len(content)))
        if not chunk:
            break
        content += chunk
    after = os.fstat(descriptor)
    if (
        len(content) != before.st_size
        or len(content) > maximum
        or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    ):
        raise RuntimeError("manfred_capacity_root_file_changed")
    return content


def _read_regular(
    path: Path,
    *,
    expected_uid: int,
    expected_mode: int,
    maximum: int,
    expected_gid: int | None = None,
) -> tuple[bytes, str]:
    absolute = _canonical_absolute(path, must_exist=True)
    flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(absolute, flags)
    except OSError as exc:
        raise RuntimeError("manfred_capacity_root_file_invalid") from exc
    try:
        status = os.fstat(descriptor)
        if (
            not stat.S_ISREG(status.st_mode)
            or status.st_uid != expected_uid
            or (expected_gid is not None and status.st_gid != expected_gid)
            or status.st_nlink != 1
            or stat.S_IMODE(status.st_mode) != expected_mode
            or not 1 <= status.st_size <= maximum
        ):
            raise RuntimeError("manfred_capacity_root_file_invalid")
        content = _read_fd_all(descriptor, maximum=maximum)
    finally:
        os.close(descriptor)
    return content, _sha256(content)


def _read_json(
    path: Path, *, expected_uid: int, expected_mode: int = 0o600
) -> tuple[dict[str, object], str]:
    content, digest = _read_regular(
        path,
        expected_uid=expected_uid,
        expected_mode=expected_mode,
        maximum=MAX_JSON_BYTES,
    )
    try:
        payload = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("manfred_capacity_root_json_invalid") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("manfred_capacity_root_json_invalid")
    return dict(payload), digest


def _source_digest(path: Path, *, expected_uid: int) -> str:
    absolute = _canonical_absolute(path, must_exist=True)
    flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(absolute, flags)
    try:
        status = os.fstat(descriptor)
        if (
            not stat.S_ISREG(status.st_mode)
            or status.st_uid != expected_uid
            or status.st_nlink != 1
            or stat.S_IMODE(status.st_mode) & 0o022
            or not 1 <= status.st_size <= MAX_SOURCE_BYTES
        ):
            raise RuntimeError("manfred_capacity_root_source_invalid")
        return _sha256(_read_fd_all(descriptor, maximum=MAX_SOURCE_BYTES))
    finally:
        os.close(descriptor)


def _directory_fd(path: Path, *, expected_uid: int, writable_mask: int = 0o022) -> int:
    absolute = _canonical_absolute(path, must_exist=True)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(absolute, flags)
    status = os.fstat(descriptor)
    if (
        not stat.S_ISDIR(status.st_mode)
        or status.st_uid != expected_uid
        or stat.S_IMODE(status.st_mode) & writable_mask
    ):
        os.close(descriptor)
        raise RuntimeError("manfred_capacity_root_directory_invalid")
    return descriptor


def _open_dir_at(parent: int, name: str, *, expected_uid: int, exact_mode: int | None = None) -> int:
    if not name or name in {".", ".."} or "/" in name or "\x00" in name:
        raise RuntimeError("manfred_capacity_root_directory_invalid")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(name, flags, dir_fd=parent)
    status = os.fstat(descriptor)
    if (
        not stat.S_ISDIR(status.st_mode)
        or status.st_uid != expected_uid
        or (exact_mode is not None and stat.S_IMODE(status.st_mode) != exact_mode)
    ):
        os.close(descriptor)
        raise RuntimeError("manfred_capacity_root_directory_invalid")
    return descriptor


def _bounded_names(
    descriptor: int,
    *,
    maximum: int,
    error: str,
) -> list[str]:
    """Enumerate a directory without first materializing an unbounded list."""

    if type(maximum) is not int or maximum < 0:
        raise RuntimeError(error)
    names: list[str] = []
    iterator: object | None = None
    try:
        iterator = os.scandir(descriptor)
        for entry in iterator:
            if len(names) >= maximum:
                raise RuntimeError(error)
            names.append(entry.name)
    except RuntimeError:
        raise
    except OSError as exc:
        raise RuntimeError(error) from exc
    finally:
        close = getattr(iterator, "close", None)
        if callable(close):
            close()
    names.sort()
    return names


def _bounded_path_entries(
    path: Path,
    *,
    maximum: int,
    error: str,
) -> list[os.DirEntry[str]]:
    if type(maximum) is not int or maximum < 0:
        raise RuntimeError(error)
    entries: list[os.DirEntry[str]] = []
    iterator: object | None = None
    try:
        iterator = os.scandir(path)
        for entry in iterator:
            if len(entries) >= maximum:
                raise RuntimeError(error)
            entries.append(entry)
    except RuntimeError:
        raise
    except OSError as exc:
        raise RuntimeError(error) from exc
    finally:
        close = getattr(iterator, "close", None)
        if callable(close):
            close()
    entries.sort(key=lambda entry: entry.name)
    return entries


def _read_json_at(
    parent: int, name: str, *, expected_uid: int
) -> tuple[dict[str, object], str]:
    if not name or name in {".", ".."} or "/" in name or "\x00" in name:
        raise RuntimeError("manfred_capacity_root_file_invalid")
    flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(name, flags, dir_fd=parent)
    try:
        status = os.fstat(descriptor)
        if (
            not stat.S_ISREG(status.st_mode)
            or status.st_uid != expected_uid
            or status.st_nlink != 1
            or stat.S_IMODE(status.st_mode) != 0o600
            or not 1 <= status.st_size <= MAX_JSON_BYTES
        ):
            raise RuntimeError("manfred_capacity_root_file_invalid")
        content = _read_fd_all(descriptor, maximum=MAX_JSON_BYTES)
    finally:
        os.close(descriptor)
    try:
        payload = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("manfred_capacity_root_json_invalid") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("manfred_capacity_root_json_invalid")
    return dict(payload), _sha256(content)


@contextlib.contextmanager
def _exclusive_existing_lock(path: Path, *, uid: int) -> Iterator[dict[str, object]]:
    absolute = _canonical_absolute(path, must_exist=True)
    flags = os.O_RDWR | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(absolute, flags)
    locked = False
    try:
        status = os.fstat(descriptor)
        if (
            not stat.S_ISREG(status.st_mode)
            or status.st_uid != uid
            or status.st_nlink != 1
            or stat.S_IMODE(status.st_mode) != 0o600
        ):
            raise RuntimeError("manfred_capacity_root_lock_invalid")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EAGAIN}:
                raise RuntimeError("manfred_capacity_root_lock_held") from exc
            raise RuntimeError("manfred_capacity_root_lock_invalid") from exc
        yield {
            "path": str(absolute),
            "owner_uid": uid,
            "exclusive": True,
            "nonblocking": True,
        }
    finally:
        if locked:
            with contextlib.suppress(OSError):
                fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _root_free_bytes() -> int:
    status = os.statvfs("/")
    value = status.f_bavail * status.f_frsize
    if value < 0:
        raise RuntimeError("manfred_capacity_root_stat_invalid")
    return value


def _validate_docker_binary() -> None:
    try:
        status = os.stat(DOCKER_BINARY, follow_symlinks=False)
    except OSError as exc:
        raise RuntimeError("manfred_capacity_root_docker_invalid") from exc
    if (
        not stat.S_ISREG(status.st_mode)
        or status.st_uid != 0
        or status.st_nlink != 1
        or stat.S_IMODE(status.st_mode) & 0o022
    ):
        raise RuntimeError("manfred_capacity_root_docker_invalid")


def _docker_output(argv: list[str]) -> bytes:
    _validate_docker_binary()
    command = [str(DOCKER_BINARY), "--host", DOCKER_HOST, *argv]
    try:
        completed = subprocess.run(
            command,
            check=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60,
            env={
                "HOME": "/root",
                "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8",
                "PATH": "/usr/bin:/bin",
            },
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError("manfred_capacity_root_docker_query_failed") from exc
    if (
        len(completed.stdout) > MAX_COMMAND_OUTPUT_BYTES
        or len(completed.stderr) > MAX_COMMAND_OUTPUT_BYTES
    ):
        raise RuntimeError("manfred_capacity_root_docker_output_invalid")
    return completed.stdout


def _docker_lines(argv: list[str]) -> list[str]:
    try:
        return [
            line.strip()
            for line in _docker_output(argv).decode("utf-8", errors="strict").splitlines()
            if line.strip()
        ]
    except UnicodeDecodeError as exc:
        raise RuntimeError("manfred_capacity_root_docker_output_invalid") from exc


def _docker_json(argv: list[str]) -> object:
    try:
        return json.loads(_docker_output(argv))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("manfred_capacity_root_docker_output_invalid") from exc


def _require_no_container_mount_references(
    paths: tuple[str, ...], *, projection_inodes: set[tuple[int, int]]
) -> dict[str, object]:
    normalized_paths: tuple[Path, ...] = tuple(Path(value) for value in paths)
    if not normalized_paths or any(
        not value.is_absolute() or Path(os.path.normpath(value)) != value
        for value in normalized_paths
    ):
        raise RuntimeError("manfred_capacity_root_mount_path_invalid")
    identifiers = _docker_lines(
        ["container", "ls", "--all", "--quiet", "--no-trunc"]
    )
    if (
        len(identifiers) > MAX_CONTAINERS
        or len(set(identifiers)) != len(identifiers)
        or any(HEX_64.fullmatch(value) is None for value in identifiers)
    ):
        raise RuntimeError("manfred_capacity_root_container_inventory_invalid")
    mount_count = 0
    inspected: set[str] = set()
    for offset in range(0, len(identifiers), CONTAINER_INSPECT_CHUNK):
        chunk = sorted(identifiers[offset : offset + CONTAINER_INSPECT_CHUNK])
        rows = _docker_json(["container", "inspect", *chunk])
        if not isinstance(rows, list) or len(rows) != len(chunk):
            raise RuntimeError("manfred_capacity_root_container_inventory_invalid")
        for row in rows:
            if not isinstance(row, dict):
                raise RuntimeError("manfred_capacity_root_container_inventory_invalid")
            identifier = str(row.get("Id") or "")
            mounts = row.get("Mounts")
            if (
                identifier not in chunk
                or identifier in inspected
                or not isinstance(mounts, list)
                or len(mounts) > MAX_MOUNTS_PER_CONTAINER
            ):
                raise RuntimeError("manfred_capacity_root_container_inventory_invalid")
            inspected.add(identifier)
            for mount in mounts:
                if not isinstance(mount, dict):
                    raise RuntimeError("manfred_capacity_root_container_inventory_invalid")
                mount_type = str(mount.get("Type") or "")
                if mount_type not in {"bind", "volume", "tmpfs"}:
                    raise RuntimeError("manfred_capacity_root_container_inventory_invalid")
                if mount_type == "tmpfs":
                    continue
                source = Path(str(mount.get("Source") or ""))
                try:
                    resolved_source = source.resolve(strict=True)
                    source_status = resolved_source.stat()
                except OSError as exc:
                    raise RuntimeError(
                        "manfred_capacity_root_container_mount_alias_invalid"
                    ) from exc
                if (
                    not source.is_absolute()
                    or Path(os.path.normpath(source)) != source
                    or resolved_source != source
                ):
                    raise RuntimeError("manfred_capacity_root_container_inventory_invalid")
                mount_count += 1
                if any(
                    source == target
                    or source.is_relative_to(target)
                    or target.is_relative_to(source)
                    for target in normalized_paths
                ) or (source_status.st_dev, source_status.st_ino) in projection_inodes:
                    raise RuntimeError(
                        "manfred_capacity_root_projection_container_mounted"
                    )
    if inspected != set(identifiers):
        raise RuntimeError("manfred_capacity_root_container_inventory_invalid")
    return {
        "container_count": len(identifiers),
        "container_set_sha256": _sha256(_json_bytes(sorted(identifiers))),
        "bind_or_volume_mount_count": mount_count,
        "all_containers_inspected": True,
        "identities_redacted": True,
    }


def _decode_mountinfo_path(value: bytes) -> Path:
    decoded = value
    for escaped, raw in ((b"\\040", b" "), (b"\\011", b"\t"), (b"\\012", b"\n"), (b"\\134", b"\\")):
        decoded = decoded.replace(escaped, raw)
    try:
        text = decoded.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise RuntimeError("manfred_capacity_root_mountinfo_invalid") from exc
    path = Path(text)
    if not path.is_absolute() or Path(os.path.normpath(path)) != path:
        raise RuntimeError("manfred_capacity_root_mountinfo_invalid")
    return path


def _require_no_nested_host_mounts(paths: tuple[str, ...]) -> dict[str, object]:
    targets = tuple(Path(value) for value in paths)
    try:
        with open("/proc/self/mountinfo", "rb", buffering=0) as handle:
            content = handle.read(MAX_MOUNTINFO_BYTES + 1)
    except OSError as exc:
        raise RuntimeError("manfred_capacity_root_mountinfo_invalid") from exc
    if len(content) > MAX_MOUNTINFO_BYTES:
        raise RuntimeError("manfred_capacity_root_mountinfo_unbounded")
    rows = content.splitlines()
    if len(rows) > MAX_MOUNTINFO_ROWS:
        raise RuntimeError("manfred_capacity_root_mountinfo_unbounded")
    mountpoints: list[Path] = []
    for row in rows:
        fields = row.split(b" ")
        if len(fields) < 10 or b"-" not in fields[6:]:
            raise RuntimeError("manfred_capacity_root_mountinfo_invalid")
        mountpoint = _decode_mountinfo_path(fields[4])
        mountpoints.append(mountpoint)
        if any(
            mountpoint != Path("/")
            and (
                mountpoint == target
                or mountpoint.is_relative_to(target)
                or target.is_relative_to(mountpoint)
            )
            for target in targets
        ):
            raise RuntimeError("manfred_capacity_root_projection_nested_mount")
    return {
        "mount_count": len(mountpoints),
        "mountpoint_set_sha256": _sha256(
            _json_bytes(sorted(str(value) for value in mountpoints))
        ),
        "nested_mounts_absent": True,
        "identities_redacted": True,
    }


def _require_project_absent(project: str) -> None:
    if PROJECT.fullmatch(project) is None:
        raise RuntimeError("manfred_capacity_root_project_invalid")
    label = f"label=com.docker.compose.project={project}"
    queries = (
        ["container", "ls", "--all", "--quiet", "--no-trunc", "--filter", label],
        ["network", "ls", "--quiet", "--no-trunc", "--filter", label],
        ["volume", "ls", "--quiet", "--filter", label],
    )
    if any(_docker_lines(query) for query in queries):
        raise RuntimeError("manfred_capacity_root_project_resources_present")


def _tree_from_fd(
    root_descriptor: int, *, path: str, runtime_uid: int
) -> tuple[
    dict[str, object],
    set[tuple[int, int]],
    str,
    int,
    int,
    list[dict[str, object]],
]:
    root = os.fstat(root_descriptor)
    if (
        not stat.S_ISDIR(root.st_mode)
        or root.st_uid != runtime_uid
        or stat.S_IMODE(root.st_mode) != 0o550
    ):
        raise RuntimeError("manfred_capacity_root_projection_identity_invalid")
    manifest_rows: list[bytes] = []
    projection_rows: list[dict[str, object]] = []
    journal_entries: list[dict[str, object]] = []
    inodes: set[tuple[int, int]] = set()
    file_count = 0
    entry_count = 1
    apparent = 0
    allocated = 0

    def walk(descriptor: int, relative: tuple[str, ...]) -> None:
        nonlocal file_count, entry_count, apparent, allocated
        before = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(before.st_mode)
            or before.st_dev != root.st_dev
            or before.st_uid != runtime_uid
            or stat.S_IMODE(before.st_mode) != 0o550
        ):
            raise RuntimeError("manfred_capacity_root_projection_identity_invalid")
        inodes.add((before.st_dev, before.st_ino))
        allocated += before.st_blocks * 512
        relative_text = "." if not relative else "/".join(relative)
        manifest_rows.append(
            (
                f"d\0{relative_text}\0{stat.S_IMODE(before.st_mode):o}"
                f"\0{before.st_uid}\0{before.st_gid}\0{before.st_nlink}\n"
            ).encode("utf-8")
        )
        journal_entries.append(
            {
                "path": relative_text,
                "kind": "directory",
                "device": before.st_dev,
                "inode": before.st_ino,
                "mode": stat.S_IMODE(before.st_mode),
                "uid": before.st_uid,
                "gid": before.st_gid,
            }
        )
        names = _bounded_names(
            descriptor,
            maximum=MAX_TREE_ENTRIES - entry_count,
            error="manfred_capacity_root_projection_too_large",
        )
        for name in names:
            if not name or name in {".", ".."} or "/" in name or "\x00" in name:
                raise RuntimeError("manfred_capacity_root_projection_identity_invalid")
            initial = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            entry_count += 1
            if entry_count > MAX_TREE_ENTRIES:
                raise RuntimeError("manfred_capacity_root_projection_too_large")
            projected = (*relative, name)
            if stat.S_ISDIR(initial.st_mode) and not stat.S_ISLNK(initial.st_mode):
                child = _open_dir_at(descriptor, name, expected_uid=runtime_uid, exact_mode=0o550)
                try:
                    opened = os.fstat(child)
                    if (initial.st_dev, initial.st_ino, initial.st_mtime_ns) != (
                        opened.st_dev,
                        opened.st_ino,
                        opened.st_mtime_ns,
                    ) or opened.st_dev != root.st_dev:
                        raise RuntimeError("manfred_capacity_root_projection_changed")
                    walk(child, projected)
                    after = os.fstat(child)
                    if (opened.st_dev, opened.st_ino, opened.st_mtime_ns) != (
                        after.st_dev,
                        after.st_ino,
                        after.st_mtime_ns,
                    ):
                        raise RuntimeError("manfred_capacity_root_projection_changed")
                finally:
                    os.close(child)
                continue
            mode = stat.S_IMODE(initial.st_mode)
            if (
                not stat.S_ISREG(initial.st_mode)
                or initial.st_dev != root.st_dev
                or stat.S_ISLNK(initial.st_mode)
                or initial.st_uid != runtime_uid
                or initial.st_nlink != 1
                or mode not in {0o440, 0o444}
            ):
                raise RuntimeError("manfred_capacity_root_projection_identity_invalid")
            if (
                initial.st_size < 0
                or initial.st_size > MAX_TREE_BYTES - apparent
            ):
                raise RuntimeError("manfred_capacity_root_projection_too_large")
            flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
            file_descriptor = os.open(name, flags, dir_fd=descriptor)
            try:
                opened = os.fstat(file_descriptor)
                identity = (
                    opened.st_dev,
                    opened.st_ino,
                    opened.st_mode,
                    opened.st_nlink,
                    opened.st_size,
                    opened.st_mtime_ns,
                    opened.st_ctime_ns,
                )
                if identity != (
                    initial.st_dev,
                    initial.st_ino,
                    initial.st_mode,
                    initial.st_nlink,
                    initial.st_size,
                    initial.st_mtime_ns,
                    initial.st_ctime_ns,
                ):
                    raise RuntimeError("manfred_capacity_root_projection_changed")
                digest = hashlib.sha256()
                size = 0
                while True:
                    chunk = os.read(file_descriptor, 1024 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
                    size += len(chunk)
                    if size > initial.st_size:
                        raise RuntimeError("manfred_capacity_root_projection_changed")
                final = os.fstat(file_descriptor)
                if identity != (
                    final.st_dev,
                    final.st_ino,
                    final.st_mode,
                    final.st_nlink,
                    final.st_size,
                    final.st_mtime_ns,
                    final.st_ctime_ns,
                ) or size != opened.st_size:
                    raise RuntimeError("manfred_capacity_root_projection_changed")
            finally:
                os.close(file_descriptor)
            inodes.add((initial.st_dev, initial.st_ino))
            file_count += 1
            apparent += initial.st_size
            allocated += initial.st_blocks * 512
            if file_count > MAX_TREE_FILES:
                raise RuntimeError("manfred_capacity_root_projection_too_large")
            relative_text = "/".join(projected)
            file_sha = digest.hexdigest()
            manifest_rows.append(
                (
                    f"f\0{relative_text}\0{mode:o}\0{initial.st_uid}\0{initial.st_gid}"
                    f"\0{initial.st_nlink}\0{initial.st_size}\0{file_sha}\n"
                ).encode("utf-8")
            )
            projection_rows.append(
                {
                    "path": relative_text,
                    "sha256": file_sha,
                    "size_bytes": size,
                    "mode": format(mode, "03o"),
                }
            )
            journal_entries.append(
                {
                    "path": relative_text,
                    "kind": "file",
                    "device": initial.st_dev,
                    "inode": initial.st_ino,
                    "mode": mode,
                    "uid": initial.st_uid,
                    "gid": initial.st_gid,
                    "size_bytes": size,
                    "sha256": file_sha,
                }
            )
        after = os.fstat(descriptor)
        if (before.st_dev, before.st_ino, before.st_mtime_ns) != (
            after.st_dev,
            after.st_ino,
            after.st_mtime_ns,
        ):
            raise RuntimeError("manfred_capacity_root_projection_changed")

    walk(root_descriptor, ())
    manifest = hashlib.sha256()
    for row in sorted(manifest_rows):
        manifest.update(row)
    projection_bytes = json.dumps(
        projection_rows, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    evidence = {
        "path": path,
        "exists": True,
        "device": root.st_dev,
        "inode": root.st_ino,
        "mode": stat.S_IMODE(root.st_mode),
        "uid": root.st_uid,
        "gid": root.st_gid,
        "file_count": file_count,
        "apparent_bytes": apparent,
        "allocated_bytes": allocated,
        "manifest_sha256": manifest.hexdigest(),
        "nlink": root.st_nlink,
        "entry_count": entry_count,
        "root_kind": "directory",
    }
    journal_entries.sort(key=lambda row: str(row["path"]))
    return (
        evidence,
        inodes,
        _sha256(projection_bytes),
        file_count,
        apparent,
        journal_entries,
    )


def _open_dir_component(parent: int, name: str) -> int:
    if not name or name in {".", ".."} or "/" in name or "\x00" in name:
        raise RuntimeError("manfred_capacity_root_candidate_path_invalid")
    flags = (
        os.O_RDONLY
        | os.O_DIRECTORY
        | os.O_CLOEXEC
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(name, flags, dir_fd=parent)
    except OSError as exc:
        raise RuntimeError("manfred_capacity_root_candidate_path_invalid") from exc
    status = os.fstat(descriptor)
    if not stat.S_ISDIR(status.st_mode):
        os.close(descriptor)
        raise RuntimeError("manfred_capacity_root_candidate_path_invalid")
    return descriptor


def _open_candidate_parent(path: Path) -> tuple[int, str]:
    path = _canonical_absolute(path, must_exist=True)
    if path == Path("/") or not path.name:
        raise RuntimeError("manfred_capacity_root_candidate_path_invalid")
    flags = (
        os.O_RDONLY
        | os.O_DIRECTORY
        | os.O_CLOEXEC
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open("/", flags)
    try:
        for component in path.parent.parts[1:]:
            child = _open_dir_component(descriptor, component)
            os.close(descriptor)
            descriptor = child
        return descriptor, path.name
    except BaseException:
        os.close(descriptor)
        raise


def _general_tree_from_fd(
    root_descriptor: int, *, path: str
) -> tuple[dict[str, object], set[tuple[int, int]], list[dict[str, object]], str]:
    root = os.fstat(root_descriptor)
    root_device = os.stat("/", follow_symlinks=False).st_dev
    if not stat.S_ISDIR(root.st_mode) or root.st_dev != root_device:
        raise RuntimeError("manfred_capacity_root_candidate_identity_invalid")
    manifest_rows: list[bytes] = []
    journal_entries: list[dict[str, object]] = []
    inodes: set[tuple[int, int]] = set()
    file_count = 0
    entry_count = 1
    apparent = 0
    allocated = 0

    def walk(descriptor: int, relative: tuple[str, ...]) -> None:
        nonlocal file_count, entry_count, apparent, allocated
        before = os.fstat(descriptor)
        if not stat.S_ISDIR(before.st_mode) or before.st_dev != root.st_dev:
            raise RuntimeError("manfred_capacity_root_candidate_identity_invalid")
        identity_before = (
            before.st_dev,
            before.st_ino,
            before.st_mode,
            before.st_uid,
            before.st_gid,
            before.st_nlink,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        relative_text = "." if not relative else "/".join(relative)
        allocated += before.st_blocks * 512
        inodes.add((before.st_dev, before.st_ino))
        manifest_rows.append(
            (
                f"d\0{relative_text}\0{stat.S_IMODE(before.st_mode):o}"
                f"\0{before.st_uid}\0{before.st_gid}\0{before.st_nlink}\n"
            ).encode("utf-8")
        )
        journal_entries.append(
            {
                "path": relative_text,
                "kind": "directory",
                "device": before.st_dev,
                "inode": before.st_ino,
                "mode": stat.S_IMODE(before.st_mode),
                "uid": before.st_uid,
                "gid": before.st_gid,
                "nlink": before.st_nlink,
            }
        )
        names = _bounded_names(
            descriptor,
            maximum=MAX_TREE_ENTRIES - entry_count,
            error="manfred_capacity_root_candidate_too_large",
        )
        for name in names:
            if not name or name in {".", ".."} or "/" in name or "\x00" in name:
                raise RuntimeError("manfred_capacity_root_candidate_identity_invalid")
            initial = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            entry_count += 1
            if entry_count > MAX_TREE_ENTRIES:
                raise RuntimeError("manfred_capacity_root_candidate_too_large")
            projected = (*relative, name)
            if stat.S_ISDIR(initial.st_mode) and not stat.S_ISLNK(initial.st_mode):
                child = _open_dir_component(descriptor, name)
                try:
                    opened = os.fstat(child)
                    if (
                        (opened.st_dev, opened.st_ino, opened.st_mode)
                        != (initial.st_dev, initial.st_ino, initial.st_mode)
                        or opened.st_dev != root.st_dev
                    ):
                        raise RuntimeError("manfred_capacity_root_candidate_changed")
                    walk(child, projected)
                finally:
                    os.close(child)
                continue
            if (
                not stat.S_ISREG(initial.st_mode)
                or stat.S_ISLNK(initial.st_mode)
                or initial.st_dev != root.st_dev
                or initial.st_nlink != 1
            ):
                raise RuntimeError("manfred_capacity_root_candidate_identity_invalid")
            if (
                initial.st_size < 0
                or initial.st_size > MAX_TREE_BYTES - apparent
            ):
                raise RuntimeError("manfred_capacity_root_candidate_too_large")
            flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
            file_descriptor = os.open(name, flags, dir_fd=descriptor)
            try:
                opened = os.fstat(file_descriptor)
                identity = (
                    opened.st_dev,
                    opened.st_ino,
                    opened.st_mode,
                    opened.st_uid,
                    opened.st_gid,
                    opened.st_nlink,
                    opened.st_size,
                    opened.st_mtime_ns,
                    opened.st_ctime_ns,
                )
                if identity != (
                    initial.st_dev,
                    initial.st_ino,
                    initial.st_mode,
                    initial.st_uid,
                    initial.st_gid,
                    initial.st_nlink,
                    initial.st_size,
                    initial.st_mtime_ns,
                    initial.st_ctime_ns,
                ):
                    raise RuntimeError("manfred_capacity_root_candidate_changed")
                digest = hashlib.sha256()
                size = 0
                while True:
                    chunk = os.read(file_descriptor, 1024 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
                    size += len(chunk)
                    if size > initial.st_size:
                        raise RuntimeError(
                            "manfred_capacity_root_candidate_changed"
                        )
                final = os.fstat(file_descriptor)
                if identity != (
                    final.st_dev,
                    final.st_ino,
                    final.st_mode,
                    final.st_uid,
                    final.st_gid,
                    final.st_nlink,
                    final.st_size,
                    final.st_mtime_ns,
                    final.st_ctime_ns,
                ) or size != opened.st_size:
                    raise RuntimeError("manfred_capacity_root_candidate_changed")
            finally:
                os.close(file_descriptor)
            file_count += 1
            apparent += initial.st_size
            allocated += initial.st_blocks * 512
            if file_count > MAX_TREE_FILES:
                raise RuntimeError("manfred_capacity_root_candidate_too_large")
            inodes.add((initial.st_dev, initial.st_ino))
            relative_text = "/".join(projected)
            file_sha = digest.hexdigest()
            manifest_rows.append(
                (
                    f"f\0{relative_text}\0{stat.S_IMODE(initial.st_mode):o}"
                    f"\0{initial.st_uid}\0{initial.st_gid}\0{initial.st_nlink}"
                    f"\0{initial.st_size}\0{file_sha}\n"
                ).encode("utf-8")
            )
            journal_entries.append(
                {
                    "path": relative_text,
                    "kind": "file",
                    "device": initial.st_dev,
                    "inode": initial.st_ino,
                    "mode": stat.S_IMODE(initial.st_mode),
                    "uid": initial.st_uid,
                    "gid": initial.st_gid,
                    "nlink": initial.st_nlink,
                    "size_bytes": size,
                    "sha256": file_sha,
                }
            )
        after = os.fstat(descriptor)
        if identity_before != (
            after.st_dev,
            after.st_ino,
            after.st_mode,
            after.st_uid,
            after.st_gid,
            after.st_nlink,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            raise RuntimeError("manfred_capacity_root_candidate_changed")

    walk(root_descriptor, ())
    manifest = hashlib.sha256()
    for row in sorted(manifest_rows):
        manifest.update(row)
    journal_entries.sort(key=lambda row: str(row["path"]))
    identity_bytes = json.dumps(
        journal_entries, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    if len(identity_bytes) > MAX_JSON_BYTES:
        raise RuntimeError("manfred_capacity_root_candidate_journal_unbounded")
    evidence = {
        "path": path,
        "exists": True,
        "device": root.st_dev,
        "inode": root.st_ino,
        "mode": stat.S_IMODE(root.st_mode),
        "uid": root.st_uid,
        "gid": root.st_gid,
        "file_count": file_count,
        "apparent_bytes": apparent,
        "allocated_bytes": allocated,
        "manifest_sha256": manifest.hexdigest(),
        "nlink": root.st_nlink,
        "entry_count": entry_count,
        "root_kind": "directory",
    }
    return evidence, inodes, journal_entries, _sha256(identity_bytes)


def _candidate_quarantine_name(raw: dict[str, object]) -> str:
    if raw.get("kind") == "candidate_release_projection":
        projection = dict(raw.get("projection") or {})
        candidate_root = Path(str(projection.get("candidate_root") or ""))
        release_id = str(projection.get("release_id") or "")
        return f"{_sha256(str(candidate_root).encode('utf-8'))[:16]}-{release_id}"
    return _sha256(
        (
            f"{raw.get('action_id')}\0{raw.get('path')}\0"
            f"{dict(raw.get('tree') or {}).get('manifest_sha256')}"
        ).encode("utf-8")
    )[:32]


def _root_candidate_snapshot(
    raw: dict[str, object], *, recovery_root: Path | None = None
) -> dict[str, object]:
    logical_path = Path(str(raw.get("path") or ""))
    expected = raw.get("tree")
    if not isinstance(expected, dict) or expected.get("exists") is not True:
        raise RuntimeError("manfred_capacity_root_candidate_identity_invalid")
    physical_path = logical_path
    recovered = False
    recovery_journal: tuple[dict[str, object], str] | None = None
    projection_recovery_journal: tuple[dict[str, object], str] | None = None
    if not os.path.lexists(logical_path):
        if recovery_root is None:
            raise RuntimeError("manfred_capacity_root_candidate_changed")
        physical_path = recovery_root / _candidate_quarantine_name(raw)
        recovered = True
        if raw.get("kind") != "candidate_release_projection":
            journal_path = recovery_root / (
                f"{_candidate_quarantine_name(raw)}.journal.v3.json"
            )
            recovery_journal = _read_optional_root_json(journal_path)
            if recovery_journal is None:
                raise RuntimeError(
                    "manfred_capacity_root_candidate_journal_missing"
                )
            journal, journal_sha = recovery_journal
            if not _generic_deletion_journal_valid(
                journal,
                raw=raw,
                handoff_sha256=recovery_root.name,
                quarantine_path=physical_path,
            ):
                raise RuntimeError(
                    "manfred_capacity_root_candidate_journal_invalid"
                )
            complete_path = recovery_root / (
                f"{_candidate_quarantine_name(raw)}.complete.v3.json"
            )
            complete_loaded = _read_optional_root_json(complete_path)
            if complete_loaded is not None:
                complete, _complete_sha = complete_loaded
                if os.path.lexists(physical_path) or not _generic_deletion_complete_valid(
                    complete,
                    journal_sha256=journal_sha,
                    raw=raw,
                    handoff_sha256=recovery_root.name,
                ):
                    raise RuntimeError(
                        "manfred_capacity_root_candidate_journal_invalid"
                    )
            if not os.path.lexists(physical_path):
                entries = [dict(row) for row in list(journal["entries"])]
                return {
                    "action_id": str(raw.get("action_id") or ""),
                    "path": str(logical_path),
                    "physical_path": str(physical_path),
                    "recovered_quarantine": True,
                    "recovered_absent": True,
                    "reference_paths": sorted(
                        {str(logical_path), str(physical_path)}
                    ),
                    "tree": dict(expected),
                    "inodes": set(),
                    "entries": entries,
                    "identity_manifest_sha256": journal[
                        "identity_manifest_sha256"
                    ],
                }
        else:
            journal_path = recovery_root / (
                f"{_candidate_quarantine_name(raw)}.journal.v3.json"
            )
            projection_recovery_journal = _read_optional_root_json(journal_path)
            if projection_recovery_journal is None:
                raise RuntimeError(
                    "manfred_capacity_root_projection_journal_missing"
                )
            journal, journal_sha = projection_recovery_journal
            if not _projection_recovery_journal_valid(
                journal,
                raw=raw,
                handoff_sha256=recovery_root.name,
                quarantine_path=physical_path,
            ):
                raise RuntimeError(
                    "manfred_capacity_root_projection_journal_invalid"
                )
            complete_path = recovery_root / (
                f"{_candidate_quarantine_name(raw)}.complete.v3.json"
            )
            complete_loaded = _read_optional_root_json(complete_path)
            if complete_loaded is not None:
                complete, _complete_sha = complete_loaded
                if os.path.lexists(
                    physical_path
                ) or not _projection_deletion_complete_valid(
                    complete,
                    journal_sha256=journal_sha,
                    raw=raw,
                    handoff_sha256=recovery_root.name,
                ):
                    raise RuntimeError(
                        "manfred_capacity_root_projection_journal_invalid"
                    )
            if not os.path.lexists(physical_path):
                entries = [dict(row) for row in list(journal["entries"])]
                return {
                    "action_id": str(raw.get("action_id") or ""),
                    "path": str(logical_path),
                    "physical_path": str(physical_path),
                    "recovered_quarantine": True,
                    "recovered_absent": True,
                    "reference_paths": sorted(
                        {str(logical_path), str(physical_path)}
                    ),
                    "tree": dict(expected),
                    "inodes": set(),
                    "entries": entries,
                    "identity_manifest_sha256": journal[
                        "root_candidate_identity_manifest_sha256"
                    ],
                }
    parent_descriptor, name = _open_candidate_parent(physical_path)
    descriptor = -1
    try:
        descriptor = _open_dir_component(parent_descriptor, name)
        if recovered and projection_recovery_journal is not None:
            journal, _journal_sha = projection_recovery_journal
            projection = dict(raw.get("projection") or {})
            (
                _remaining_evidence,
                inodes,
                _projection_sha,
                _file_count,
                _apparent_bytes,
                remaining_entries,
            ) = _tree_from_fd(
                descriptor,
                path=str(logical_path),
                runtime_uid=int(projection["runtime_uid"]),
            )
            entries = [dict(row) for row in list(journal["entries"])]
            if not _remaining_entries_valid(entries, remaining_entries):
                raise RuntimeError(
                    "manfred_capacity_root_projection_remaining_set_invalid"
                )
            evidence = dict(expected)
            identity_sha = str(
                journal["root_candidate_identity_manifest_sha256"]
            )
        else:
            evidence, inodes, entries, identity_sha = _general_tree_from_fd(
                descriptor, path=str(logical_path)
            )
        if recovered and recovery_journal is not None:
            journal, _journal_sha = recovery_journal
            expected_entries = [
                dict(row) for row in list(journal.get("entries") or [])
            ]
            if not _generic_remaining_entries_valid(expected_entries, entries):
                raise RuntimeError(
                    "manfred_capacity_root_candidate_remaining_set_invalid"
                )
            evidence = dict(expected)
            entries = expected_entries
            identity_sha = str(journal["identity_manifest_sha256"])
        elif evidence != expected:
            raise RuntimeError("manfred_capacity_root_candidate_changed")
        return {
            "action_id": str(raw.get("action_id") or ""),
            "path": str(logical_path),
            "physical_path": str(physical_path),
            "recovered_quarantine": recovered,
            "reference_paths": sorted({str(logical_path), str(physical_path)}),
            "tree": evidence,
            "inodes": inodes,
            "entries": entries,
            "identity_manifest_sha256": identity_sha,
        }
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        os.close(parent_descriptor)


def _projection_candidate_row(projection: dict[str, object]) -> dict[str, object]:
    tree = dict(projection.get("tree") or {})
    return {
        "action_id": f"projection:{projection.get('release_id')}",
        "kind": "candidate_release_projection",
        "classification": "receipt_valid_rebuildable_projection",
        "path": str(projection.get("path") or ""),
        "tree": tree,
        "projection": dict(projection),
        "user_eligible": False,
        "root_candidate": True,
        "root_reclaim_floor_bytes": int(tree.get("allocated_bytes") or 0),
        "reported_observation_bytes": None,
        "capacity_source": "live_tree_evidence",
        "parent_preserved": True,
        "protected_overlap": False,
        "selection_group": None,
        "selection_limit": None,
    }


def _validate_root_candidate_scope(
    raw_rows: object,
    *,
    operator_uid: int,
    operator_home: Path,
    deploy_root: Path,
    projections: object,
) -> list[dict[str, object]]:
    if (
        type(operator_uid) is not int
        or operator_uid < 1
        or not isinstance(raw_rows, list)
        or not 1 <= len(raw_rows) <= MAX_ROOT_CANDIDATES
        or any(not isinstance(row, dict) for row in raw_rows)
    ):
        raise RuntimeError("manfred_capacity_root_candidate_scope_invalid")
    rows = [dict(row) for row in raw_rows]
    if (
        not isinstance(projections, list)
        or len(projections) != EXPECTED_PROJECTION_COUNT
        or any(not isinstance(row, dict) for row in projections)
    ):
        raise RuntimeError("manfred_capacity_root_candidate_scope_invalid")
    discovered_projections = [dict(row) for row in projections]
    expected_projection_rows = [
        _projection_candidate_row(row) for row in discovered_projections
    ]
    action_ids = [str(row.get("action_id") or "") for row in rows]
    paths = [Path(str(row.get("path") or "")) for row in rows]
    if (
        any(not value for value in action_ids)
        or len(set(action_ids)) != len(action_ids)
        or len(set(paths)) != len(paths)
        or any(not path.is_absolute() or ".." in path.parts for path in paths)
        or any(
            left == right
            or left in right.parents
            or right in left.parents
            for index, left in enumerate(paths)
            for right in paths[index + 1 :]
        )
    ):
        raise RuntimeError("manfred_capacity_root_candidate_scope_invalid")
    cache_paths = {
        "cache:nuget_http": operator_home / ".local/share/NuGet/http-cache",
        "cache:nuget_global_packages": operator_home / ".nuget/packages",
        "cache:npm_content_cache": operator_home / ".npm/_cacache",
        "cache:pip_cache": operator_home / ".cache/pip",
    }
    projection_count = 0
    cache_count = 0
    vscode_count = 0
    temp_count = 0
    for row, path in zip(rows, paths, strict=True):
        tree = row.get("tree")
        action_id = str(row.get("action_id") or "")
        kind = row.get("kind")
        if (
            not isinstance(tree, dict)
            or tree.get("path") != str(path)
            or tree.get("exists") is not True
            or tree.get("root_kind") != "directory"
            or row.get("root_candidate") is not True
            or row.get("user_eligible") is not False
            or row.get("capacity_source") != "live_tree_evidence"
            or row.get("parent_preserved") is not True
            or row.get("protected_overlap") is not False
            or row.get("root_reclaim_floor_bytes") != tree.get("allocated_bytes")
            or any(
                type(tree.get(key)) is not int or int(tree[key]) < 0
                for key in (
                    "device",
                    "inode",
                    "mode",
                    "uid",
                    "gid",
                    "nlink",
                    "file_count",
                    "entry_count",
                    "apparent_bytes",
                    "allocated_bytes",
                )
            )
            or int(tree["nlink"]) < 2
            or int(tree["entry_count"]) < 1
            or HEX_64.fullmatch(str(tree.get("manifest_sha256") or "")) is None
        ):
            raise RuntimeError("manfred_capacity_root_candidate_scope_invalid")
        if kind == "candidate_release_projection":
            projection = row.get("projection")
            if not isinstance(projection, dict):
                raise RuntimeError("manfred_capacity_root_candidate_scope_invalid")
            candidate_root = Path(str(projection.get("candidate_root") or ""))
            release_id = str(projection.get("release_id") or "")
            if (
                action_id != f"projection:{release_id}"
                or CANDIDATE_ROOT.fullmatch(candidate_root.name) is None
                or candidate_root != deploy_root / candidate_root.name
                or HEX_40.fullmatch(release_id) is None
                or path != candidate_root / "releases" / release_id
                or projection.get("path") != str(path)
                or projection.get("tree") != tree
                or type(projection.get("runtime_uid")) is not int
                or int(projection["runtime_uid"]) < 1
                or int(projection["runtime_uid"]) == operator_uid
                or tree.get("uid") != projection.get("runtime_uid")
                or projection.get("release_authority_promotion_authority")
                is not False
                or projection.get("release_authority_runtime_clear") is not True
                or projection.get("candidate_root_preserved") is not True
                or projection.get("runtime_preserved") is not True
                or projection.get("receipts_preserved") is not True
            ):
                raise RuntimeError("manfred_capacity_root_candidate_scope_invalid")
            projection_count += 1
        elif kind == "operator_cache_tree":
            if (
                tree.get("uid") not in {0, operator_uid}
                or cache_paths.get(action_id) != path
                or row.get("classification") != "rebuildable_operator_cache"
                or row.get("selection_group") is not None
                or row.get("selection_limit") is not None
            ):
                raise RuntimeError("manfred_capacity_root_candidate_scope_invalid")
            cache_count += 1
        elif kind == "vscode_server_tree":
            if (
                tree.get("uid") not in {0, operator_uid}
                or path.parent != operator_home / ".vscode-server/cli/servers"
                or VSCODE_SERVER_NAME.fullmatch(path.name) is None
                or action_id != f"vscode:{path.name}"
                or row.get("selection_group") != "vscode_inactive_one"
                or row.get("selection_limit") != 1
                or row.get("extensions_preserved") is not True
                or row.get("tokens_preserved") is not True
            ):
                raise RuntimeError("manfred_capacity_root_candidate_scope_invalid")
            vscode_count += 1
        elif kind == "rebuildable_temp_tree":
            if (
                tree.get("uid") not in {0, operator_uid}
                or ROOT_TEMP_CANDIDATE_PATHS.get(action_id) != path
                or row.get("classification")
                != "exact_rebuildable_temporary_output"
                or row.get("selection_group") is not None
                or row.get("selection_limit") is not None
            ):
                raise RuntimeError("manfred_capacity_root_candidate_scope_invalid")
            temp_count += 1
        else:
            raise RuntimeError("manfred_capacity_root_candidate_scope_invalid")
    if (
        projection_count != EXPECTED_PROJECTION_COUNT
        or cache_count > len(cache_paths)
        or vscode_count not in {0, 2}
        or temp_count > len(ROOT_TEMP_CANDIDATE_PATHS)
    ):
        raise RuntimeError("manfred_capacity_root_candidate_scope_invalid")
    if [
        row for row in rows if row.get("kind") == "candidate_release_projection"
    ] != expected_projection_rows:
        raise RuntimeError("manfred_capacity_root_candidate_scope_invalid")
    vscode_rows = [
        row for row in rows if row.get("kind") == "vscode_server_tree"
    ]
    if vscode_rows:
        expected_vscode = sorted(
            vscode_rows,
            key=lambda row: (
                -int(dict(row["tree"])["allocated_bytes"]),
                str(row["path"]),
            ),
        )
        if vscode_rows != expected_vscode or [
            row.get("selection_order") for row in vscode_rows
        ] != list(range(len(vscode_rows))):
            raise RuntimeError("manfred_capacity_root_candidate_scope_invalid")
    return rows


def _process_error_is_vanished(exc: OSError) -> bool:
    return exc.errno in {errno.ENOENT, errno.ESRCH}


def _process_references(
    *, paths: tuple[str, ...], inodes: set[tuple[int, int]]
) -> list[dict[str, object]]:
    references: list[dict[str, object]] = []
    needles = tuple(value.encode("utf-8") for value in paths)
    process_entries = _bounded_path_entries(
        Path("/proc"),
        maximum=MAX_PROCESS_COUNT,
        error="manfred_capacity_root_process_inventory_unbounded",
    )
    for entry in process_entries:
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        root = Path(entry.path)
        kinds: set[str] = set()
        for name in ("exe", "cwd", "root"):
            candidate = root / name
            try:
                metadata = candidate.stat()
                target = os.readlink(candidate)
            except OSError as exc:
                if _process_error_is_vanished(exc):
                    continue
                raise RuntimeError(
                    "manfred_capacity_root_process_inventory_invalid"
                ) from exc
            if (metadata.st_dev, metadata.st_ino) in inodes or any(
                target == value or target.startswith(f"{value}/") for value in paths
            ):
                kinds.add(name)
        for name in ("cmdline", "maps"):
            try:
                with open(root / name, "rb", buffering=0) as handle:
                    content = handle.read(4 * 1024 * 1024 + 1)
            except OSError as exc:
                if _process_error_is_vanished(exc):
                    continue
                raise RuntimeError(
                    "manfred_capacity_root_process_inventory_invalid"
                ) from exc
            if len(content) > 4 * 1024 * 1024:
                raise RuntimeError("manfred_capacity_root_process_inventory_unbounded")
            if any(needle in content for needle in needles):
                kinds.add(name)
        try:
            descriptors = _bounded_path_entries(
                root / "fd",
                maximum=MAX_PROCESS_FDS,
                error="manfred_capacity_root_process_fd_inventory_unbounded",
            )
        except OSError as exc:
            if _process_error_is_vanished(exc):
                descriptors = []
            else:
                raise RuntimeError(
                    "manfred_capacity_root_process_inventory_invalid"
                ) from exc
        for descriptor in descriptors:
            try:
                metadata = os.stat(descriptor.path)
                target = os.readlink(descriptor.path)
            except OSError as exc:
                if _process_error_is_vanished(exc):
                    continue
                raise RuntimeError(
                    "manfred_capacity_root_process_inventory_invalid"
                ) from exc
            if (metadata.st_dev, metadata.st_ino) in inodes or any(
                target == value or target.startswith(f"{value}/") for value in paths
            ):
                kinds.add("fd")
                break
        if kinds:
            references.append({"pid": int(entry.name), "kinds": sorted(kinds)})
            if len(references) > MAX_PROCESS_REFERENCES:
                raise RuntimeError("manfred_capacity_root_process_references_unbounded")
    return sorted(references, key=lambda row: int(row["pid"]))


def _bounded_proc_read(path: Path, *, maximum: int) -> bytes:
    flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        content = b""
        while len(content) <= maximum:
            chunk = os.read(
                descriptor, min(65536, maximum + 1 - len(content))
            )
            if not chunk:
                break
            content += chunk
        if len(content) > maximum:
            raise RuntimeError("manfred_capacity_root_process_inventory_unbounded")
        return content
    finally:
        os.close(descriptor)


def _reference_target_matches(target: str, path: str) -> bool:
    return (
        target == path
        or target.startswith(f"{path}/")
        or target.startswith(f"{path} (deleted)")
    )


def _strict_process_inventory(
    snapshots: list[dict[str, object]],
) -> dict[str, object]:
    action_order = [str(row["action_id"]) for row in snapshots]
    candidate_paths = {
        str(row["action_id"]): list(row.get("reference_paths") or [row["path"]])
        for row in snapshots
    }
    candidate_inodes = {
        str(row["action_id"]): set(row["inodes"]) for row in snapshots
    }
    all_process_entries = _bounded_path_entries(
        Path("/proc"),
        maximum=MAX_PROCESS_COUNT,
        error="manfred_capacity_root_process_inventory_unbounded",
    )
    process_entries = sorted(
        (entry for entry in all_process_entries if entry.name.isdigit()),
        key=lambda entry: int(entry.name),
    )
    referenced: set[str] = set()
    inventory_rows: list[dict[str, object]] = []
    completed_processes = 0
    for entry in process_entries:
        process_root = Path(entry.path)
        try:
            process_status = process_root.stat()
        except OSError as exc:
            if _process_error_is_vanished(exc):
                continue
            raise RuntimeError(
                "manfred_capacity_root_process_inventory_invalid"
            ) from exc
        matched: set[str] = set()
        link_rows: list[tuple[str, str, int, int]] = []
        vanished = False
        for name in ("cwd", "root", "exe"):
            candidate = process_root / name
            try:
                metadata = candidate.stat()
                target = os.readlink(candidate)
            except OSError as exc:
                if _process_error_is_vanished(exc) and not process_root.exists():
                    vanished = True
                    break
                raise RuntimeError(
                    "manfred_capacity_root_process_inventory_invalid"
                ) from exc
            link_rows.append((name, target, metadata.st_dev, metadata.st_ino))
            for action_id in action_order:
                if (
                    (metadata.st_dev, metadata.st_ino)
                    in candidate_inodes[action_id]
                    or any(
                        _reference_target_matches(target, value)
                        for value in candidate_paths[action_id]
                    )
                ):
                    matched.add(action_id)
        if vanished:
            continue
        content_rows: list[tuple[str, str, int]] = []
        for name, maximum in (
            ("cmdline", MAX_PROCESS_CMDLINE_BYTES),
            ("maps", MAX_PROCESS_MAPS_BYTES),
            ("environ", MAX_PROCESS_ENVIRON_BYTES),
            ("mountinfo", MAX_PROCESS_MOUNTINFO_BYTES),
        ):
            try:
                content = _bounded_proc_read(process_root / name, maximum=maximum)
            except OSError as exc:
                if _process_error_is_vanished(exc) and not process_root.exists():
                    vanished = True
                    break
                raise RuntimeError(
                    "manfred_capacity_root_process_inventory_invalid"
                ) from exc
            content_rows.append((name, _sha256(content), len(content)))
            for action_id in action_order:
                if any(
                    value.encode("utf-8") in content
                    for value in candidate_paths[action_id]
                ):
                    matched.add(action_id)
        if vanished:
            continue
        try:
            descriptors = _bounded_path_entries(
                process_root / "fd",
                maximum=MAX_PROCESS_FDS,
                error="manfred_capacity_root_process_fd_inventory_unbounded",
            )
        except OSError as exc:
            if _process_error_is_vanished(exc) and not process_root.exists():
                continue
            raise RuntimeError(
                "manfred_capacity_root_process_inventory_invalid"
            ) from exc
        fd_rows: list[tuple[str, str, int, int]] = []
        for descriptor in sorted(descriptors, key=lambda value: value.name):
            try:
                metadata = os.stat(descriptor.path)
                target = os.readlink(descriptor.path)
            except OSError as exc:
                if _process_error_is_vanished(exc):
                    continue
                raise RuntimeError(
                    "manfred_capacity_root_process_inventory_invalid"
                ) from exc
            fd_rows.append(
                (descriptor.name, target, metadata.st_dev, metadata.st_ino)
            )
            for action_id in action_order:
                if (
                    (metadata.st_dev, metadata.st_ino)
                    in candidate_inodes[action_id]
                    or any(
                        _reference_target_matches(target, value)
                        for value in candidate_paths[action_id]
                    )
                ):
                    matched.add(action_id)
        referenced.update(matched)
        completed_processes += 1
        inventory_rows.append(
            {
                "pid": int(entry.name),
                "process_device": process_status.st_dev,
                "process_inode": process_status.st_ino,
                "process_uid": process_status.st_uid,
                "links_sha256": _sha256(
                    json.dumps(link_rows, separators=(",", ":")).encode("utf-8")
                ),
                "content_sha256": _sha256(
                    json.dumps(content_rows, separators=(",", ":")).encode(
                        "utf-8"
                    )
                ),
                "fds_sha256": _sha256(
                    json.dumps(fd_rows, separators=(",", ":")).encode("utf-8")
                ),
                "referenced_action_ids": [
                    action_id for action_id in action_order if action_id in matched
                ],
            }
        )
    encoded_inventory = json.dumps(
        inventory_rows, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return {
        "process_count": completed_processes,
        "process_inventory_sha256": _sha256(encoded_inventory),
        "referenced_action_ids": [
            action_id for action_id in action_order if action_id in referenced
        ],
        "all_process_fields_readable": True,
        "fields": [
            "cwd",
            "root",
            "exe",
            "fd",
            "maps",
            "cmdline",
            "environ",
            "mountinfo",
        ],
        "identities_redacted": True,
    }


def _root_union_sample(
    rows: list[dict[str, object]], *, recovery_root: Path | None = None
) -> dict[str, object]:
    snapshots = [
        _root_candidate_snapshot(row, recovery_root=recovery_root) for row in rows
    ]
    paths = tuple(
        value
        for row in snapshots
        for value in list(row.get("reference_paths") or [row["path"]])
    )
    inodes: set[tuple[int, int]] = set()
    for row in snapshots:
        inodes.update(set(row["inodes"]))
    host_mounts = _require_no_nested_host_mounts(paths)
    docker_mounts = _require_no_container_mount_references(
        paths, projection_inodes=inodes
    )
    processes = _strict_process_inventory(snapshots)
    public_candidates = [
        {
            "action_id": row["action_id"],
            "path": row["path"],
            "tree": row["tree"],
            "identity_manifest_sha256": row["identity_manifest_sha256"],
            "entry_count": len(list(row["entries"])),
        }
        for row in snapshots
    ]
    return {
        "snapshots": snapshots,
        "candidates": public_candidates,
        "processes": processes,
        "host_mounts": host_mounts,
        "docker_mounts": docker_mounts,
    }


def _two_sample_root_preflight(
    rows: list[dict[str, object]],
    *,
    recovery_root: Path | None = None,
) -> dict[str, object]:
    first = _root_union_sample(rows, recovery_root=recovery_root)
    second = _root_union_sample(rows, recovery_root=recovery_root)
    if (
        first["candidates"] != second["candidates"]
        or dict(first["processes"]).get("referenced_action_ids")
        != dict(second["processes"]).get("referenced_action_ids")
        or dict(first["host_mounts"]).get("mountpoint_set_sha256")
        != dict(second["host_mounts"]).get("mountpoint_set_sha256")
        or dict(first["docker_mounts"]).get("container_set_sha256")
        != dict(second["docker_mounts"]).get("container_set_sha256")
        or dict(first["docker_mounts"]).get("bind_or_volume_mount_count")
        != dict(second["docker_mounts"]).get("bind_or_volume_mount_count")
    ):
        raise RuntimeError("manfred_capacity_root_preflight_drift")
    return {
        **second,
        "first_process_inventory_sha256": dict(first["processes"])[
            "process_inventory_sha256"
        ],
        "second_process_inventory_sha256": dict(second["processes"])[
            "process_inventory_sha256"
        ],
        "two_sample_stable": True,
        "global_preflight_complete": True,
    }


def _eligible_root_prefix(
    rows: list[dict[str, object]],
    *,
    referenced_action_ids: list[str],
    root_free_bytes: int,
    user_reclaim_floor_bytes: int,
    target: int,
) -> tuple[list[str], list[str], int, int]:
    if (
        type(root_free_bytes) is not int
        or root_free_bytes < 0
        or type(user_reclaim_floor_bytes) is not int
        or user_reclaim_floor_bytes < 0
        or target != TARGET_ROOT_FREE_BYTES
    ):
        raise RuntimeError("manfred_capacity_root_target_invalid")
    referenced = set(referenced_action_ids)
    groups_used: set[str] = set()
    eligible: list[dict[str, object]] = []
    for row in rows:
        action_id = str(row["action_id"])
        if action_id in referenced:
            continue
        group = row.get("selection_group")
        if group is not None:
            if group != "vscode_inactive_one" or row.get("selection_limit") != 1:
                raise RuntimeError("manfred_capacity_root_candidate_scope_invalid")
            if group in groups_used:
                continue
            groups_used.add(group)
        eligible.append(row)
    eligible_ids = [str(row["action_id"]) for row in eligible]
    eligible_floor = sum(int(row["root_reclaim_floor_bytes"]) for row in eligible)
    authorized: list[str] = []
    authorized_floor = 0
    if root_free_bytes < target:
        # User-scoped reclaim figures are observations, not guaranteed free
        # blocks.  Bind the complete finite eligible set so a partial user
        # reclaim cannot strand the later root handoff behind an optimistic
        # prefix.  Apply still stops as soon as the target is reached.
        authorized = list(eligible_ids)
        authorized_floor = eligible_floor
    if root_free_bytes + user_reclaim_floor_bytes + authorized_floor < target:
        raise RuntimeError("manfred_capacity_root_candidates_insufficient")
    return eligible_ids, authorized, eligible_floor, authorized_floor


def _unlink_contents(
    descriptor: int,
    *,
    runtime_uid: int,
    expected_device: int | None = None,
    remaining_entries: list[int] | None = None,
) -> None:
    device = os.fstat(descriptor).st_dev if expected_device is None else expected_device
    if remaining_entries is None:
        remaining_entries = [MAX_TREE_ENTRIES - 1]
    names = _bounded_names(
        descriptor,
        maximum=remaining_entries[0],
        error="manfred_capacity_root_projection_too_large",
    )
    for name in names:
        remaining_entries[0] -= 1
        if remaining_entries[0] < 0:
            raise RuntimeError("manfred_capacity_root_projection_too_large")
        metadata = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
        if metadata.st_dev != device:
            raise RuntimeError("manfred_capacity_root_projection_device_changed")
        if stat.S_ISDIR(metadata.st_mode) and not stat.S_ISLNK(metadata.st_mode):
            child = _open_dir_at(descriptor, name, expected_uid=runtime_uid, exact_mode=0o550)
            try:
                _unlink_contents(
                    child,
                    runtime_uid=runtime_uid,
                    expected_device=device,
                    remaining_entries=remaining_entries,
                )
            finally:
                os.close(child)
            current = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            if (current.st_dev, current.st_ino) != (metadata.st_dev, metadata.st_ino):
                raise RuntimeError("manfred_capacity_root_projection_changed")
            os.rmdir(name, dir_fd=descriptor)
        elif (
            stat.S_ISREG(metadata.st_mode)
            and metadata.st_uid == runtime_uid
            and metadata.st_nlink == 1
            and stat.S_IMODE(metadata.st_mode) in {0o440, 0o444}
        ):
            os.unlink(name, dir_fd=descriptor)
        else:
            raise RuntimeError("manfred_capacity_root_projection_identity_invalid")


@contextlib.contextmanager
def _root_quarantine(
    *, handoff_sha256: str, deploy_device: int
) -> Iterator[tuple[int, Path]]:
    if HEX_64.fullmatch(handoff_sha256) is None:
        raise RuntimeError("manfred_capacity_root_quarantine_invalid")
    ea_root = _directory_fd(Path("/var/lib/ea"), expected_uid=0)
    quarantine_descriptor = handoff_descriptor = -1
    try:
        try:
            os.mkdir(QUARANTINE_ROOT.name, 0o700, dir_fd=ea_root)
        except FileExistsError:
            pass
        quarantine_descriptor = _open_dir_at(
            ea_root, QUARANTINE_ROOT.name, expected_uid=0, exact_mode=0o700
        )
        try:
            os.mkdir(handoff_sha256, 0o700, dir_fd=quarantine_descriptor)
        except FileExistsError:
            pass
        handoff_descriptor = _open_dir_at(
            quarantine_descriptor,
            handoff_sha256,
            expected_uid=0,
            exact_mode=0o700,
        )
        if os.fstat(handoff_descriptor).st_dev != deploy_device:
            raise RuntimeError("manfred_capacity_root_quarantine_cross_device")
        yield handoff_descriptor, QUARANTINE_ROOT / handoff_sha256
    finally:
        for descriptor in (handoff_descriptor, quarantine_descriptor, ea_root):
            if descriptor >= 0:
                os.close(descriptor)


def _entry_identity_matches(
    status: os.stat_result, expected: dict[str, object], *, directory: bool
) -> bool:
    return bool(
        status.st_dev == expected.get("device")
        and status.st_ino == expected.get("inode")
        and stat.S_IMODE(status.st_mode) == expected.get("mode")
        and status.st_uid == expected.get("uid")
        and status.st_gid == expected.get("gid")
        and (
            directory
            or (
                status.st_nlink == expected.get("nlink") == 1
                and status.st_size == expected.get("size_bytes")
            )
        )
    )


def _unlink_general_contents(
    descriptor: int,
    *,
    relative: tuple[str, ...],
    expected_by_path: dict[str, dict[str, object]],
    expected_device: int,
    pre_mutation: object,
    remaining_entries: list[int] | None = None,
) -> None:
    if not callable(pre_mutation):
        raise RuntimeError("manfred_capacity_root_candidate_guard_invalid")
    if remaining_entries is None:
        remaining_entries = [len(expected_by_path)]
    names = _bounded_names(
        descriptor,
        maximum=remaining_entries[0],
        error="manfred_capacity_root_candidate_remaining_set_invalid",
    )
    for name in names:
        remaining_entries[0] -= 1
        if remaining_entries[0] < 0:
            raise RuntimeError(
                "manfred_capacity_root_candidate_remaining_set_invalid"
            )
        projected = (*relative, name)
        relative_text = "/".join(projected)
        expected = expected_by_path.get(relative_text)
        if expected is None:
            raise RuntimeError("manfred_capacity_root_candidate_remaining_set_invalid")
        metadata = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
        if metadata.st_dev != expected_device:
            raise RuntimeError("manfred_capacity_root_candidate_device_changed")
        if stat.S_ISDIR(metadata.st_mode) and not stat.S_ISLNK(metadata.st_mode):
            if expected.get("kind") != "directory" or not _entry_identity_matches(
                metadata, expected, directory=True
            ):
                raise RuntimeError("manfred_capacity_root_candidate_changed")
            child = _open_dir_component(descriptor, name)
            try:
                _unlink_general_contents(
                    child,
                    relative=projected,
                    expected_by_path=expected_by_path,
                    expected_device=expected_device,
                    pre_mutation=pre_mutation,
                    remaining_entries=remaining_entries,
                )
            finally:
                os.close(child)
            current = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            if (current.st_dev, current.st_ino) != (
                metadata.st_dev,
                metadata.st_ino,
            ):
                raise RuntimeError("manfred_capacity_root_candidate_changed")
            pre_mutation()
            os.rmdir(name, dir_fd=descriptor)
        elif (
            expected.get("kind") == "file"
            and stat.S_ISREG(metadata.st_mode)
            and not stat.S_ISLNK(metadata.st_mode)
            and _entry_identity_matches(metadata, expected, directory=False)
        ):
            pre_mutation()
            current = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            if not _entry_identity_matches(current, expected, directory=False):
                raise RuntimeError("manfred_capacity_root_candidate_changed")
            os.unlink(name, dir_fd=descriptor)
        else:
            raise RuntimeError("manfred_capacity_root_candidate_identity_invalid")


def _generic_journal_entries_valid(
    rows: object, *, expected_tree: dict[str, object]
) -> bool:
    if (
        not isinstance(rows, list)
        or not 1 <= len(rows) <= MAX_TREE_ENTRIES
        or any(not isinstance(row, dict) for row in rows)
        or len({str(row.get("path") or "") for row in rows}) != len(rows)
        or len(rows) != expected_tree.get("entry_count")
    ):
        return False
    file_count = 0
    apparent_bytes = 0
    root_seen = False
    for raw in rows:
        row = dict(raw)
        relative = Path(str(row.get("path") or ""))
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or not str(row.get("path") or "")
            or row.get("kind") not in {"directory", "file"}
            or any(
                type(row.get(key)) is not int or int(row[key]) < 0
                for key in ("device", "inode", "mode", "uid", "gid")
            )
        ):
            return False
        if row["kind"] == "directory":
            if type(row.get("nlink")) is not int or int(row["nlink"]) < 2:
                return False
            root_seen = root_seen or row["path"] == "."
        else:
            if (
                type(row.get("nlink")) is not int
                or row.get("nlink") != 1
                or type(row.get("size_bytes")) is not int
                or int(row["size_bytes"]) < 0
                or int(row["size_bytes"]) > MAX_TREE_BYTES - apparent_bytes
                or HEX_64.fullmatch(str(row.get("sha256") or "")) is None
            ):
                return False
            file_count += 1
            apparent_bytes += int(row["size_bytes"])
    return bool(
        root_seen
        and file_count == expected_tree.get("file_count")
        and apparent_bytes == expected_tree.get("apparent_bytes")
    )


def _generic_deletion_journal_valid(
    journal: dict[str, object],
    *,
    raw: dict[str, object],
    handoff_sha256: str,
    quarantine_path: Path,
) -> bool:
    tree = raw.get("tree")
    rows = journal.get("entries")
    if not isinstance(tree, dict) or not _generic_journal_entries_valid(
        rows, expected_tree=tree
    ):
        return False
    assert isinstance(rows, list)
    identity_bytes = json.dumps(
        rows, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    if len(identity_bytes) > MAX_JSON_BYTES:
        return False
    try:
        _json_bytes(journal)
    except RuntimeError:
        return False
    return bool(
        journal.get("schema") == DELETION_JOURNAL_SCHEMA
        and journal.get("handoff_sha256") == handoff_sha256
        and journal.get("action_id") == raw.get("action_id")
        and journal.get("kind") == raw.get("kind")
        and journal.get("target_path") == raw.get("path")
        and journal.get("quarantine_path") == str(quarantine_path)
        and journal.get("tree") == tree
        and journal.get("identity_manifest_sha256")
        == _sha256(identity_bytes)
        and journal.get("entry_count") == len(rows)
        and journal.get("target_broadened") is False
    )


def _generic_remaining_entries_valid(
    expected: list[dict[str, object]], observed: list[dict[str, object]]
) -> bool:
    if (
        not expected
        or not observed
        or len(observed) > len(expected)
        or len({str(row.get("path") or "") for row in expected}) != len(expected)
        or len({str(row.get("path") or "") for row in observed}) != len(observed)
    ):
        return False
    expected_by_path = {str(row["path"]): row for row in expected}
    observed_paths = {str(row.get("path") or "") for row in observed}
    if "." not in observed_paths:
        return False
    for observed_row in observed:
        path = str(observed_row.get("path") or "")
        expected_row = expected_by_path.get(path)
        if expected_row is None or observed_row.get("kind") != expected_row.get("kind"):
            return False
        if observed_row.get("kind") == "file":
            if observed_row != expected_row:
                return False
        else:
            stable_keys = ("path", "kind", "device", "inode", "mode", "uid", "gid")
            if any(observed_row.get(key) != expected_row.get(key) for key in stable_keys):
                return False
            if (
                type(observed_row.get("nlink")) is not int
                or not 2 <= int(observed_row["nlink"]) <= int(expected_row["nlink"])
            ):
                return False
        relative = Path(path)
        if path != ".":
            parent = relative.parent.as_posix()
            if parent not in observed_paths:
                return False
    return True


def _generic_deletion_complete_valid(
    complete: dict[str, object],
    *,
    journal_sha256: str,
    raw: dict[str, object],
    handoff_sha256: str,
) -> bool:
    return bool(
        complete.get("schema") == DELETION_COMPLETE_SCHEMA
        and complete.get("handoff_sha256") == handoff_sha256
        and complete.get("journal_sha256") == journal_sha256
        and complete.get("action_id") == raw.get("action_id")
        and complete.get("target_path") == raw.get("path")
        and complete.get("status") == "tree_removed"
    )


def _projection_recovery_journal_valid(
    journal: dict[str, object],
    *,
    raw: dict[str, object],
    handoff_sha256: str,
    quarantine_path: Path,
) -> bool:
    projection = raw.get("projection")
    tree = raw.get("tree")
    rows = journal.get("entries")
    if (
        not isinstance(projection, dict)
        or not isinstance(tree, dict)
        or not isinstance(rows, list)
        or not 1 <= len(rows) <= MAX_TREE_ENTRIES
        or any(not isinstance(row, dict) for row in rows)
        or len({str(row.get("path") or "") for row in rows}) != len(rows)
        or journal.get("entry_count") != len(rows)
        or len(rows) != tree.get("entry_count")
    ):
        return False
    try:
        _json_bytes(journal)
    except RuntimeError:
        return False
    return bool(
        journal.get("schema") == DELETION_JOURNAL_SCHEMA
        and journal.get("handoff_sha256") == handoff_sha256
        and journal.get("target_path") == raw.get("path")
        and journal.get("quarantine_path") == str(quarantine_path)
        and journal.get("release_id") == projection.get("release_id")
        and journal.get("runtime_uid") == projection.get("runtime_uid")
        and journal.get("tree") == tree
        and journal.get("projection_sha256")
        == projection.get("projection_sha256")
        and HEX_64.fullmatch(
            str(journal.get("root_candidate_identity_manifest_sha256") or "")
        )
        is not None
        and journal.get("root_candidate_entry_count") == len(rows)
        and journal.get("target_broadened") is False
    )


def _projection_deletion_complete_valid(
    complete: dict[str, object],
    *,
    journal_sha256: str,
    raw: dict[str, object],
    handoff_sha256: str,
) -> bool:
    projection = dict(raw.get("projection") or {})
    return bool(
        complete.get("schema") == DELETION_COMPLETE_SCHEMA
        and complete.get("handoff_sha256") == handoff_sha256
        and complete.get("journal_sha256") == journal_sha256
        and complete.get("target_path") == raw.get("path")
        and complete.get("release_id") == projection.get("release_id")
        and complete.get("status") == "tree_removed"
    )


def _remove_generic_candidate(
    raw: dict[str, object],
    *,
    handoff_sha256: str,
    quarantine_descriptor: int,
    quarantine_root: Path,
    pre_mutation: object,
) -> dict[str, object]:
    target = Path(str(raw.get("path") or ""))
    quarantine_name = _candidate_quarantine_name(raw)
    quarantine_path = quarantine_root / quarantine_name
    journal_path = quarantine_root / f"{quarantine_name}.journal.v3.json"
    complete_path = quarantine_root / f"{quarantine_name}.complete.v3.json"
    journal_loaded = _read_optional_root_json(journal_path)
    complete_loaded = _read_optional_root_json(complete_path)
    source_exists = os.path.lexists(target)
    quarantine_exists = os.path.lexists(quarantine_path)
    if source_exists and quarantine_exists:
        raise RuntimeError("manfred_capacity_root_candidate_recovery_ambiguous")
    if complete_loaded is not None and (source_exists or quarantine_exists):
        raise RuntimeError("manfred_capacity_root_candidate_recovery_ambiguous")
    if not source_exists and not quarantine_exists:
        if journal_loaded is None:
            raise RuntimeError("manfred_capacity_root_candidate_changed")
        journal, journal_sha = journal_loaded
        if not _generic_deletion_journal_valid(
            journal,
            raw=raw,
            handoff_sha256=handoff_sha256,
            quarantine_path=quarantine_path,
        ):
            raise RuntimeError("manfred_capacity_root_candidate_journal_invalid")
        recovered = complete_loaded is None
        if complete_loaded is None:
            complete = {
                "schema": DELETION_COMPLETE_SCHEMA,
                "created_at": _utc_now(),
                "handoff_sha256": handoff_sha256,
                "journal_sha256": journal_sha,
                "action_id": raw["action_id"],
                "target_path": str(target),
                "status": "tree_removed",
            }
            complete_sha = _atomic_private_root_json(complete_path, complete)
        else:
            complete, complete_sha = complete_loaded
            if not _generic_deletion_complete_valid(
                complete,
                journal_sha256=journal_sha,
                raw=raw,
                handoff_sha256=handoff_sha256,
            ):
                raise RuntimeError("manfred_capacity_root_candidate_journal_invalid")
        return {
            "action_id": raw["action_id"],
            "path": str(target),
            "status": (
                "recovered_removed" if recovered else "already_removed_verified"
            ),
            "allocated_bytes": int(raw["root_reclaim_floor_bytes"]),
            "deletion_journal_path": str(journal_path),
            "deletion_journal_sha256": journal_sha,
            "deletion_complete_path": str(complete_path),
            "deletion_complete_sha256": complete_sha,
        }
    started_from_source = source_exists
    physical = target if source_exists else quarantine_path
    if source_exists:
        snapshot = _root_candidate_snapshot(raw)
        entries = [dict(row) for row in list(snapshot["entries"])]
        journal = {
            "schema": DELETION_JOURNAL_SCHEMA,
            "created_at": _utc_now(),
            "handoff_sha256": handoff_sha256,
            "action_id": raw["action_id"],
            "kind": raw["kind"],
            "target_path": str(target),
            "quarantine_path": str(quarantine_path),
            "tree": raw["tree"],
            "identity_manifest_sha256": snapshot["identity_manifest_sha256"],
            "entries": entries,
            "entry_count": len(entries),
            "target_broadened": False,
        }
        if not _generic_deletion_journal_valid(
            journal,
            raw=raw,
            handoff_sha256=handoff_sha256,
            quarantine_path=quarantine_path,
        ):
            raise RuntimeError("manfred_capacity_root_candidate_journal_invalid")
        if journal_loaded is None:
            journal_sha = _atomic_private_root_json(journal_path, journal)
        else:
            loaded, journal_sha = journal_loaded
            comparison = dict(journal)
            comparison["created_at"] = loaded.get("created_at")
            if loaded != comparison:
                raise RuntimeError("manfred_capacity_root_candidate_journal_invalid")
    else:
        if journal_loaded is None:
            raise RuntimeError("manfred_capacity_root_candidate_journal_missing")
        journal, journal_sha = journal_loaded
        if not _generic_deletion_journal_valid(
            journal,
            raw=raw,
            handoff_sha256=handoff_sha256,
            quarantine_path=quarantine_path,
        ):
            raise RuntimeError("manfred_capacity_root_candidate_journal_invalid")
        entries = [dict(row) for row in list(journal["entries"])]
    if source_exists:
        parent_descriptor, source_name = _open_candidate_parent(target)
        try:
            pre_mutation()
            current = os.stat(
                source_name, dir_fd=parent_descriptor, follow_symlinks=False
            )
            tree = dict(raw["tree"])
            if (current.st_dev, current.st_ino) != (
                tree["device"],
                tree["inode"],
            ):
                raise RuntimeError("manfred_capacity_root_candidate_changed")
            os.rename(
                source_name,
                quarantine_name,
                src_dir_fd=parent_descriptor,
                dst_dir_fd=quarantine_descriptor,
            )
            os.fsync(parent_descriptor)
            os.fsync(quarantine_descriptor)
        finally:
            os.close(parent_descriptor)
        physical = quarantine_path
    parent_descriptor, physical_name = _open_candidate_parent(physical)
    tree_descriptor = -1
    try:
        tree_descriptor = _open_dir_component(parent_descriptor, physical_name)
        repeated, remaining_inodes, remaining, repeated_identity = _general_tree_from_fd(
            tree_descriptor, path=str(target)
        )
        if started_from_source:
            if (
                repeated != raw.get("tree")
                or remaining != entries
                or repeated_identity != journal["identity_manifest_sha256"]
            ):
                raise RuntimeError("manfred_capacity_root_candidate_changed")
        elif not _generic_remaining_entries_valid(entries, remaining):
            raise RuntimeError(
                "manfred_capacity_root_candidate_remaining_set_invalid"
            )
        guard_snapshot = {
            "action_id": raw["action_id"],
            "path": str(target),
            "inodes": remaining_inodes,
        }
        guard_snapshot["reference_paths"] = [str(target), str(quarantine_path)]

        def immediate_guard() -> None:
            _require_no_nested_host_mounts((str(target), str(quarantine_path)))
            _require_no_container_mount_references(
                (str(target), str(quarantine_path)),
                projection_inodes=set(guard_snapshot["inodes"]),
            )
            if _strict_process_inventory([guard_snapshot])[
                "referenced_action_ids"
            ]:
                raise RuntimeError("manfred_capacity_root_candidate_referenced")
            pre_mutation()

        expected_by_path = {
            str(row["path"]): dict(row)
            for row in entries
            if str(row["path"]) != "."
        }
        _unlink_general_contents(
            tree_descriptor,
            relative=(),
            expected_by_path=expected_by_path,
            expected_device=int(dict(raw["tree"])["device"]),
            pre_mutation=immediate_guard,
        )
        opened = os.fstat(tree_descriptor)
    finally:
        if tree_descriptor >= 0:
            os.close(tree_descriptor)
        os.close(parent_descriptor)
    current = os.stat(
        quarantine_name,
        dir_fd=quarantine_descriptor,
        follow_symlinks=False,
    )
    if (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
        raise RuntimeError("manfred_capacity_root_candidate_changed")
    pre_mutation()
    os.rmdir(quarantine_name, dir_fd=quarantine_descriptor)
    os.fsync(quarantine_descriptor)
    complete = {
        "schema": DELETION_COMPLETE_SCHEMA,
        "created_at": _utc_now(),
        "handoff_sha256": handoff_sha256,
        "journal_sha256": journal_sha,
        "action_id": raw["action_id"],
        "target_path": str(target),
        "status": "tree_removed",
    }
    complete_sha = _atomic_private_root_json(complete_path, complete)
    return {
        "action_id": raw["action_id"],
        "path": str(target),
        "status": "removed" if started_from_source else "recovered_removed",
        "allocated_bytes": int(raw["root_reclaim_floor_bytes"]),
        "deletion_journal_path": str(journal_path),
        "deletion_journal_sha256": journal_sha,
        "deletion_complete_path": str(complete_path),
        "deletion_complete_sha256": complete_sha,
    }


def _atomic_private_root_json(path: Path, payload: dict[str, object]) -> str:
    encoded = _json_bytes(payload)
    parent = _canonical_absolute(path.parent, must_exist=True)
    status = parent.stat()
    if (
        not stat.S_ISDIR(status.st_mode)
        or status.st_uid != 0
        or stat.S_IMODE(status.st_mode) != 0o700
        or os.path.lexists(path)
    ):
        raise RuntimeError("manfred_capacity_root_journal_path_invalid")
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            descriptor = -1
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path, follow_symlinks=False)
        Path(temporary).unlink()
        temporary = ""
        parent_descriptor = os.open(
            parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
        )
        try:
            os.fsync(parent_descriptor)
        finally:
            os.close(parent_descriptor)
    except FileExistsError as exc:
        raise RuntimeError("manfred_capacity_root_journal_exists") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary:
            with contextlib.suppress(OSError):
                Path(temporary).unlink()
    return _sha256(encoded)


def _read_optional_root_json(path: Path) -> tuple[dict[str, object], str] | None:
    if not os.path.lexists(path):
        return None
    return _read_json(path, expected_uid=0)


def _remaining_entries_valid(
    expected: list[dict[str, object]], observed: list[dict[str, object]]
) -> bool:
    if (
        not expected
        or len({str(row.get("path") or "") for row in expected}) != len(expected)
        or len({str(row.get("path") or "") for row in observed}) != len(observed)
    ):
        return False
    expected_by_path = {str(row["path"]): row for row in expected}
    return all(expected_by_path.get(str(row.get("path") or "")) == row for row in observed)


def _validate_projection(
    raw: dict[str, object],
    *,
    deploy_descriptor: int,
    deploy_root: Path,
    operator_uid: int,
    handoff_sha256: str,
    quarantine_descriptor: int,
    quarantine_root: Path,
) -> dict[str, object]:
    candidate_root = Path(str(raw.get("candidate_root") or ""))
    release_id = str(raw.get("release_id") or "")
    target = Path(str(raw.get("path") or ""))
    if (
        CANDIDATE_ROOT.fullmatch(candidate_root.name) is None
        or candidate_root != deploy_root / candidate_root.name
        or HEX_40.fullmatch(release_id) is None
        or target != candidate_root / "releases" / release_id
        or raw.get("candidate_root_preserved") is not True
        or raw.get("runtime_preserved") is not True
        or raw.get("receipts_preserved") is not True
        or raw.get("root_revalidation_required") is not True
        or raw.get("process_reference_check") != "root_revalidation_required"
        or raw.get("process_references") is not None
    ):
        raise RuntimeError("manfred_capacity_root_projection_path_invalid")

    quarantine_name = (
        f"{_sha256(str(candidate_root).encode('utf-8'))[:16]}-{release_id}"
    )
    journal_path = quarantine_root / f"{quarantine_name}.journal.v3.json"
    complete_path = quarantine_root / f"{quarantine_name}.complete.v3.json"
    journal_loaded = _read_optional_root_json(journal_path)
    complete_loaded = _read_optional_root_json(complete_path)

    candidate_descriptor = _open_dir_at(
        deploy_descriptor,
        candidate_root.name,
        expected_uid=operator_uid,
        exact_mode=0o700,
    )
    releases_descriptor = receipts_descriptor = target_descriptor = -1
    quarantine_tree_descriptor = -1
    try:
        releases_descriptor = _open_dir_at(
            candidate_descriptor, "releases", expected_uid=operator_uid
        )
        if stat.S_IMODE(os.fstat(releases_descriptor).st_mode) & 0o022:
            raise RuntimeError("manfred_capacity_root_directory_invalid")
        receipts_descriptor = _open_dir_at(
            candidate_descriptor, "receipts", expected_uid=operator_uid
        )
        if stat.S_IMODE(os.fstat(receipts_descriptor).st_mode) & 0o022:
            raise RuntimeError("manfred_capacity_root_directory_invalid")
        receipt, receipt_sha = _read_json_at(
            receipts_descriptor, f"{release_id}.json", expected_uid=operator_uid
        )
        _spatial, spatial_sha = _read_json_at(
            receipts_descriptor,
            f"{release_id}.spatial.json",
            expected_uid=operator_uid,
        )
        runtime_uid = receipt.get("runtime_uid")
        if (
            receipt_sha != raw.get("receipt_sha256")
            or spatial_sha != raw.get("spatial_receipt_sha256")
            or receipt.get("schema") != PROJECTION_SCHEMA
            or receipt.get("status") != "pass"
            or receipt.get("release_id") != release_id
            or receipt.get("release_root") != str(target)
            or receipt.get("compose_project") != raw.get("project")
            or receipt.get("projection_sha256") != raw.get("projection_sha256")
            or receipt.get("spatial_receipt_sha256") != spatial_sha
            or receipt.get("release_authority_promotion_authority") is not False
            or receipt.get("release_authority_runtime_clear") is not True
            or runtime_uid != raw.get("runtime_uid")
            or raw.get("release_authority_promotion_authority") is not False
            or raw.get("release_authority_runtime_clear") is not True
        ):
            raise RuntimeError("manfred_capacity_root_projection_receipt_invalid")
        if type(runtime_uid) is not int or runtime_uid < 1 or runtime_uid == operator_uid:
            raise RuntimeError("manfred_capacity_root_projection_receipt_invalid")

        target_exists = quarantine_exists = False
        try:
            target_descriptor = _open_dir_at(
                releases_descriptor,
                release_id,
                expected_uid=runtime_uid,
                exact_mode=0o550,
            )
            target_exists = True
        except FileNotFoundError:
            pass
        try:
            quarantine_tree_descriptor = _open_dir_at(
                quarantine_descriptor,
                quarantine_name,
                expected_uid=runtime_uid,
                exact_mode=0o550,
            )
            quarantine_exists = True
        except FileNotFoundError:
            pass
        if target_exists and quarantine_exists:
            raise RuntimeError("manfred_capacity_root_projection_recovery_ambiguous")
        if target_exists and complete_loaded is not None:
            raise RuntimeError("manfred_capacity_root_projection_recovery_ambiguous")
        if complete_loaded is not None and journal_loaded is None:
            raise RuntimeError("manfred_capacity_root_projection_journal_invalid")

        _require_project_absent(str(raw.get("project") or ""))
        allocated_bytes = int(dict(raw.get("tree") or {})["allocated_bytes"])
        if not target_exists and not quarantine_exists:
            journal_sha = None
            complete_sha = None
            status = "already_absent"
            if journal_loaded is not None:
                journal, journal_sha = journal_loaded
                raw_entries = journal.get("entries")
                if (
                    journal.get("schema") != DELETION_JOURNAL_SCHEMA
                    or journal.get("handoff_sha256") != handoff_sha256
                    or journal.get("target_path") != str(target)
                    or journal.get("quarantine_path")
                    != str(quarantine_root / quarantine_name)
                    or journal.get("release_id") != release_id
                    or journal.get("runtime_uid") != runtime_uid
                    or journal.get("tree") != raw.get("tree")
                    or journal.get("projection_sha256")
                    != raw.get("projection_sha256")
                    or not isinstance(raw_entries, list)
                    or any(not isinstance(row, dict) for row in raw_entries)
                    or journal.get("entry_count") != len(raw_entries)
                    or not 1 <= len(raw_entries) <= MAX_TREE_ENTRIES
                    or HEX_64.fullmatch(
                        str(
                            journal.get(
                                "root_candidate_identity_manifest_sha256"
                            )
                            or ""
                        )
                    )
                    is None
                    or journal.get("root_candidate_entry_count")
                    != len(raw_entries)
                    or journal.get("target_broadened") is not False
                ):
                    raise RuntimeError(
                        "manfred_capacity_root_projection_journal_invalid"
                    )
                if complete_loaded is None:
                    complete = {
                        "schema": DELETION_COMPLETE_SCHEMA,
                        "created_at": _utc_now(),
                        "handoff_sha256": handoff_sha256,
                        "journal_sha256": journal_sha,
                        "target_path": str(target),
                        "release_id": release_id,
                        "status": "tree_removed",
                    }
                    complete_sha = _atomic_private_root_json(
                        complete_path, complete
                    )
                else:
                    complete, complete_sha = complete_loaded
                    if (
                        complete.get("schema") != DELETION_COMPLETE_SCHEMA
                        or complete.get("handoff_sha256") != handoff_sha256
                        or complete.get("journal_sha256") != journal_sha
                        or complete.get("target_path") != str(target)
                        or complete.get("release_id") != release_id
                        or complete.get("status") != "tree_removed"
                    ):
                        raise RuntimeError(
                            "manfred_capacity_root_projection_journal_invalid"
                        )
                status = (
                    "recovered_removed"
                    if complete_loaded is None
                    else "already_removed_verified"
                )
            return {
                "path": str(target),
                "status": status,
                "allocated_bytes": allocated_bytes,
                "deletion_journal_path": (
                    str(journal_path) if journal_loaded is not None else None
                ),
                "deletion_journal_sha256": journal_sha,
                "deletion_complete_sha256": complete_sha,
            }

        reference_paths = (str(target), str(quarantine_root / quarantine_name))
        journal_sha: str
        expected_entries: list[dict[str, object]]

        if target_exists:
            (
                evidence,
                inodes,
                projection_sha,
                file_count,
                projection_bytes,
                expected_entries,
            ) = _tree_from_fd(
                target_descriptor, path=str(target), runtime_uid=runtime_uid
            )
            if (
                evidence != raw.get("tree")
                or projection_sha != raw.get("projection_sha256")
                or file_count != receipt.get("file_count")
                or projection_bytes != receipt.get("projection_bytes")
            ):
                raise RuntimeError("manfred_capacity_root_projection_changed")
            (
                root_candidate_evidence,
                _root_candidate_inodes,
                root_candidate_entries,
                root_candidate_identity,
            ) = _general_tree_from_fd(
                target_descriptor,
                path=str(target),
            )
            if (
                root_candidate_evidence != evidence
                or len(root_candidate_entries) != len(expected_entries)
            ):
                raise RuntimeError("manfred_capacity_root_projection_changed")
            journal = {
                "schema": DELETION_JOURNAL_SCHEMA,
                "created_at": _utc_now(),
                "handoff_sha256": handoff_sha256,
                "target_path": str(target),
                "quarantine_path": str(quarantine_root / quarantine_name),
                "release_id": release_id,
                "runtime_uid": runtime_uid,
                "tree": evidence,
                "projection_sha256": projection_sha,
                "entries": expected_entries,
                "entry_count": len(expected_entries),
                "root_candidate_identity_manifest_sha256": root_candidate_identity,
                "root_candidate_entry_count": len(root_candidate_entries),
                "target_broadened": False,
            }
            # Prove that the immutable recovery journal fits its bounded durable
            # representation before moving the only live projection pathname.
            _json_bytes(journal)
            mount_check_before = _require_no_container_mount_references(
                reference_paths, projection_inodes=inodes
            )
            host_mount_check_before = _require_no_nested_host_mounts(reference_paths)
            if _process_references(paths=reference_paths, inodes=inodes):
                raise RuntimeError("manfred_capacity_root_projection_referenced")
            if journal_loaded is None:
                journal_sha = _atomic_private_root_json(journal_path, journal)
            else:
                loaded, journal_sha = journal_loaded
                comparison = dict(journal)
                comparison["created_at"] = loaded.get("created_at")
                if loaded != comparison:
                    raise RuntimeError(
                        "manfred_capacity_root_projection_journal_invalid"
                    )
            os.rename(
                release_id,
                quarantine_name,
                src_dir_fd=releases_descriptor,
                dst_dir_fd=quarantine_descriptor,
            )
            os.fsync(releases_descriptor)
            os.fsync(quarantine_descriptor)
            quarantine_tree_descriptor = target_descriptor
            target_descriptor = -1
            (
                repeated,
                repeated_inodes,
                repeated_sha,
                _repeated_count,
                _repeated_bytes,
                repeated_entries,
            ) = _tree_from_fd(
                quarantine_tree_descriptor,
                path=str(target),
                runtime_uid=runtime_uid,
            )
            if (
                repeated != evidence
                or repeated_sha != projection_sha
                or repeated_entries != expected_entries
            ):
                raise RuntimeError("manfred_capacity_root_projection_changed")
        else:
            if journal_loaded is None:
                raise RuntimeError(
                    "manfred_capacity_root_projection_journal_missing"
                )
            else:
                journal, journal_sha = journal_loaded
                raw_entries = journal.get("entries")
                if (
                    journal.get("schema") != DELETION_JOURNAL_SCHEMA
                    or journal.get("handoff_sha256") != handoff_sha256
                    or journal.get("target_path") != str(target)
                    or journal.get("quarantine_path")
                    != str(quarantine_root / quarantine_name)
                    or journal.get("release_id") != release_id
                    or journal.get("runtime_uid") != runtime_uid
                    or journal.get("tree") != raw.get("tree")
                    or journal.get("projection_sha256")
                    != raw.get("projection_sha256")
                    or not isinstance(raw_entries, list)
                    or any(not isinstance(row, dict) for row in raw_entries)
                    or journal.get("entry_count") != len(raw_entries)
                    or not 1 <= len(raw_entries) <= MAX_TREE_FILES + 1
                    or HEX_64.fullmatch(
                        str(
                            journal.get(
                                "root_candidate_identity_manifest_sha256"
                            )
                            or ""
                        )
                    )
                    is None
                    or journal.get("root_candidate_entry_count")
                    != len(raw_entries)
                ):
                    raise RuntimeError(
                        "manfred_capacity_root_projection_journal_invalid"
                    )
                expected_entries = [dict(row) for row in raw_entries]
            (
                _remaining_evidence,
                repeated_inodes,
                _remaining_sha,
                _remaining_count,
                _remaining_bytes,
                remaining_entries,
            ) = _tree_from_fd(
                quarantine_tree_descriptor,
                path=str(target),
                runtime_uid=runtime_uid,
            )
            if not _remaining_entries_valid(expected_entries, remaining_entries):
                raise RuntimeError(
                    "manfred_capacity_root_projection_remaining_set_invalid"
                )
            mount_check_before = _require_no_container_mount_references(
                reference_paths, projection_inodes=repeated_inodes
            )
            host_mount_check_before = _require_no_nested_host_mounts(reference_paths)
            if _process_references(paths=reference_paths, inodes=repeated_inodes):
                raise RuntimeError("manfred_capacity_root_projection_referenced")

        (
            _final_evidence,
            final_inodes,
            _final_sha,
            _final_count,
            _final_bytes,
            final_entries,
        ) = _tree_from_fd(
            quarantine_tree_descriptor,
            path=str(target),
            runtime_uid=runtime_uid,
        )
        if not _remaining_entries_valid(expected_entries, final_entries):
            raise RuntimeError(
                "manfred_capacity_root_projection_remaining_set_invalid"
            )
        mount_check_after = _require_no_container_mount_references(
            reference_paths, projection_inodes=final_inodes
        )
        host_mount_check_after = _require_no_nested_host_mounts(reference_paths)
        if _process_references(paths=reference_paths, inodes=final_inodes):
            raise RuntimeError("manfred_capacity_root_projection_referenced")

        opened = os.fstat(quarantine_tree_descriptor)
        _unlink_contents(
            quarantine_tree_descriptor,
            runtime_uid=runtime_uid,
            expected_device=opened.st_dev,
        )
        current = os.stat(
            quarantine_name,
            dir_fd=quarantine_descriptor,
            follow_symlinks=False,
        )
        if (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
            raise RuntimeError("manfred_capacity_root_projection_changed")
        os.rmdir(quarantine_name, dir_fd=quarantine_descriptor)
        os.fsync(quarantine_descriptor)
        complete = {
            "schema": DELETION_COMPLETE_SCHEMA,
            "created_at": _utc_now(),
            "handoff_sha256": handoff_sha256,
            "journal_sha256": journal_sha,
            "target_path": str(target),
            "release_id": release_id,
            "status": "tree_removed",
        }
        complete_sha = _atomic_private_root_json(complete_path, complete)
        return {
            "path": str(target),
            "status": "removed" if target_exists else "recovered_removed",
            "allocated_bytes": allocated_bytes,
            "deletion_journal_path": str(journal_path),
            "deletion_journal_sha256": journal_sha,
            "deletion_complete_path": str(complete_path),
            "deletion_complete_sha256": complete_sha,
            "global_container_mount_checks": [
                mount_check_before,
                mount_check_after,
            ],
            "host_mount_checks": [
                host_mount_check_before,
                host_mount_check_after,
            ],
        }
    finally:
        for descriptor in (
            quarantine_tree_descriptor,
            target_descriptor,
            receipts_descriptor,
            releases_descriptor,
            candidate_descriptor,
        ):
            if descriptor >= 0:
                os.close(descriptor)


def _validate_root_receipt_destination(path: Path, *, operator_gid: int) -> Path:
    if not path.is_absolute() or os.path.lexists(path):
        raise RuntimeError("manfred_capacity_root_receipt_path_invalid")
    parent = _canonical_absolute(path.parent, must_exist=True)
    parent_status = parent.stat()
    if (
        not stat.S_ISDIR(parent_status.st_mode)
        or parent != ROOT_RECEIPT_DIRECTORY
        or ROOT_RECEIPT_NAME.fullmatch(path.name) is None
        or parent_status.st_uid != 0
        or parent_status.st_gid != operator_gid
        or stat.S_IMODE(parent_status.st_mode) & 0o022
        or stat.S_IMODE(parent_status.st_mode) & 0o050 != 0o050
    ):
        raise RuntimeError("manfred_capacity_root_receipt_parent_invalid")
    return path


def _atomic_root_receipt(
    path: Path, payload: dict[str, object], *, operator_gid: int
) -> str:
    encoded = _json_bytes(payload)
    path = _validate_root_receipt_destination(path, operator_gid=operator_gid)
    parent = path.parent
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=parent)
    try:
        os.fchown(descriptor, 0, operator_gid)
        os.fchmod(descriptor, 0o640)
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            descriptor = -1
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path, follow_symlinks=False)
        Path(temporary).unlink()
        temporary = ""
        parent_descriptor = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            os.fsync(parent_descriptor)
        finally:
            os.close(parent_descriptor)
    except FileExistsError as exc:
        raise RuntimeError("manfred_capacity_root_receipt_exists") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary:
            with contextlib.suppress(OSError):
                Path(temporary).unlink()
    return _sha256(encoded)


def _root_stage_contract() -> dict[str, object]:
    return {
        "parent": "/root",
        "mode": 0o700,
        "applier_name": "applier.py",
        "applier_mode": 0o500,
        "controller_name": "controller.py",
        "controller_mode": 0o400,
        "handoff_name": "handoff.json",
        "handoff_mode": 0o400,
        "user_receipt_name": "user-receipt.json",
        "user_receipt_mode": 0o400,
    }


def _validate_root_stage(
    *,
    stage_path: Path,
    applier_path: Path,
    controller_path: Path,
    handoff_path: Path,
    user_receipt_path: Path,
) -> Path:
    stage = _canonical_absolute(stage_path, must_exist=True)
    status = stage.stat()
    expected_paths = {
        "applier.py": applier_path,
        "controller.py": controller_path,
        "handoff.json": handoff_path,
        "user-receipt.json": user_receipt_path,
    }
    if (
        stage.parent != ROOT_STAGE_PARENT
        or ROOT_STAGE_NAME.fullmatch(stage.name) is None
        or not stat.S_ISDIR(status.st_mode)
        or status.st_uid != 0
        or status.st_gid != 0
        or status.st_nlink != 2
        or stat.S_IMODE(status.st_mode) != 0o700
    ):
        raise RuntimeError("manfred_capacity_root_stage_invalid")
    observed: set[str] = set()
    for entry in _bounded_path_entries(
        stage,
        maximum=len(expected_paths),
        error="manfred_capacity_root_stage_invalid",
    ):
        observed.add(entry.name)
        if entry.name not in expected_paths or not entry.is_file(follow_symlinks=False):
            raise RuntimeError("manfred_capacity_root_stage_invalid")
    if observed != set(expected_paths):
        raise RuntimeError("manfred_capacity_root_stage_invalid")
    for name, path in expected_paths.items():
        expected = stage / name
        if _canonical_absolute(path, must_exist=True) != expected:
            raise RuntimeError("manfred_capacity_root_stage_invalid")
    if Path(__file__).resolve(strict=True) != expected_paths["applier.py"]:
        raise RuntimeError("manfred_capacity_root_stage_invalid")
    return stage


def _staged_evidence(
    path: Path,
    *,
    mode: int,
    expected_sha256: str | None,
) -> tuple[bytes, dict[str, object]]:
    content, digest = _read_regular(
        path,
        expected_uid=0,
        expected_gid=0,
        expected_mode=mode,
        maximum=MAX_SOURCE_BYTES,
    )
    if expected_sha256 is not None and digest != expected_sha256:
        raise RuntimeError("manfred_capacity_root_staged_digest_invalid")
    return content, {
        "path": str(path),
        "sha256": digest,
        "size_bytes": len(content),
        "owner_uid": 0,
        "owner_gid": 0,
        "mode": mode,
    }


def _source_binding_valid(
    raw: object,
    *,
    expected_path: object,
    expected_sha256: object,
    operator_uid: int,
) -> bool:
    if not isinstance(raw, dict):
        return False
    path = Path(str(raw.get("path") or ""))
    mode = raw.get("mode")
    size = raw.get("size_bytes")
    return (
        path.is_absolute()
        and ".." not in path.parts
        and str(path) == str(expected_path)
        and raw.get("sha256") == expected_sha256
        and raw.get("owner_uid") == operator_uid
        and type(mode) is int
        and not int(mode) & 0o022
        and type(size) is int
        and 1 <= int(size) <= MAX_SOURCE_BYTES
    )


def _installer_binding_valid(raw: object, *, installer_sha256: str) -> bool:
    if not isinstance(raw, dict):
        return False
    size = raw.get("code_size_bytes")
    return (
        raw.get("delivery") == ROOT_INSTALLER_DELIVERY
        and raw.get("sudo_path") == "/usr/bin/sudo"
        and raw.get("interpreter_path") == PYTHON_EXECUTABLE
        and raw.get("code_sha256") == installer_sha256
        and type(size) is int
        and 1 <= int(size) <= MAX_SOURCE_BYTES
        and raw.get("stdlib_only") is True
        and raw.get("root_stage_parent") == "/root"
        and raw.get("root_stage_mode") == 0o700
        and raw.get("sudo_uid_required") is True
        and raw.get("literal_argv_only") is True
        and raw.get("operator_authorized_inline_bootstrap") is True
        and raw.get("unreviewed_command_string_authenticated") is False
        and raw.get("user_writable_root_interpreted_file") is False
    )


def _bounded_projection_actions(
    projections: list[dict[str, object]],
    *,
    target: int,
    free_bytes: object,
    remove_projection: object,
) -> list[dict[str, object]]:
    if target != TARGET_ROOT_FREE_BYTES or not callable(free_bytes) or not callable(
        remove_projection
    ):
        raise RuntimeError("manfred_capacity_root_target_invalid")
    actions: list[dict[str, object]] = []
    capacity_reached = False
    for row in projections:
        if capacity_reached or free_bytes() >= target:
            capacity_reached = True
            actions.append(
                {
                    "path": str(row.get("path") or ""),
                    "status": "preserved_capacity_ready",
                    "allocated_bytes": int(
                        dict(row.get("tree") or {})["allocated_bytes"]
                    ),
                }
            )
            continue
        result = remove_projection(row)
        if not isinstance(result, dict):
            raise RuntimeError("manfred_capacity_root_projection_result_invalid")
        actions.append(result)
    return actions


def attest(
    *,
    operator_uid: int,
    request_path: Path,
    request_source_path: Path,
    request_sha256: str,
    request_copy_path: Path,
    request_copy_source_path: Path,
    request_copy_sha256: str,
    root_attestation_path: Path,
    applier_sha256: str,
    controller_copy_path: Path,
    installer_sha256: str,
    stage_path: Path,
) -> dict[str, object]:
    if os.geteuid() != 0:
        raise RuntimeError("manfred_capacity_root_requires_root")
    if (
        type(operator_uid) is not int
        or operator_uid < 1
        or request_sha256 != request_copy_sha256
        or any(
            HEX_64.fullmatch(value) is None
            for value in (request_sha256, applier_sha256, installer_sha256)
        )
    ):
        raise RuntimeError("manfred_capacity_root_digest_invalid")
    try:
        operator = pwd.getpwuid(operator_uid)
    except KeyError as exc:
        raise RuntimeError("manfred_capacity_root_operator_invalid") from exc
    root_attestation_path = _validate_root_receipt_destination(
        root_attestation_path, operator_gid=operator.pw_gid
    )
    applier_copy = Path(__file__).resolve(strict=True)
    request_probe = _canonical_absolute(request_path, must_exist=True)
    request_copy = _canonical_absolute(request_copy_path, must_exist=True)
    controller_copy = _canonical_absolute(controller_copy_path, must_exist=True)
    stage = _validate_root_stage(
        stage_path=stage_path,
        applier_path=applier_copy,
        controller_path=controller_copy,
        handoff_path=request_probe,
        user_receipt_path=request_copy,
    )
    if (
        request_source_path != request_copy_source_path
        or not request_source_path.is_absolute()
        or ".." in request_source_path.parts
        or request_source_path in {request_probe, request_copy}
        or ROOT_STAGE_PARENT in request_source_path.parents
    ):
        raise RuntimeError("manfred_capacity_root_source_binding_invalid")
    applier_content, staged_applier = _staged_evidence(
        applier_copy, mode=0o500, expected_sha256=applier_sha256
    )
    controller_content, staged_controller = _staged_evidence(
        controller_copy, mode=0o400, expected_sha256=None
    )
    request_content, staged_request = _staged_evidence(
        request_probe, mode=0o400, expected_sha256=request_sha256
    )
    request_copy_content, staged_request_copy = _staged_evidence(
        request_copy, mode=0o400, expected_sha256=request_copy_sha256
    )
    if request_content != request_copy_content:
        raise RuntimeError("manfred_capacity_root_attest_request_changed")
    try:
        raw = json.loads(request_content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("manfred_capacity_root_json_invalid") from exc
    if not isinstance(raw, dict):
        raise RuntimeError("manfred_capacity_root_json_invalid")
    request = dict(raw)
    producer_sha256 = str(request.get("producer_sha256") or "")
    if (
        HEX_64.fullmatch(producer_sha256) is None
        or _sha256(controller_content) != producer_sha256
    ):
        raise RuntimeError("manfred_capacity_root_controller_changed")
    staged_controller["sha256"] = producer_sha256
    applier_source = request.get("root_applier_source")
    producer_source = request.get("producer_source")
    if (
        request.get("schema") != ROOT_ATTEST_REQUEST_SCHEMA
        or request.get("operator_uid") != operator_uid
        or request.get("root_applier_sha256") != applier_sha256
        or not _source_binding_valid(
            applier_source,
            expected_path=request.get("root_applier_path"),
            expected_sha256=applier_sha256,
            operator_uid=operator_uid,
        )
        or dict(applier_source).get("size_bytes") != len(applier_content)
        or not _source_binding_valid(
            producer_source,
            expected_path=request.get("producer_path"),
            expected_sha256=producer_sha256,
            operator_uid=operator_uid,
        )
        or dict(producer_source).get("size_bytes") != len(controller_content)
        or request.get("root_installer_sha256") != installer_sha256
        or not _installer_binding_valid(
            request.get("root_installer"), installer_sha256=installer_sha256
        )
        or request.get("root_stage_contract") != _root_stage_contract()
        or request.get("request_source_path") != str(request_source_path)
        or request.get("root_attestation_path") != str(root_attestation_path)
        or request.get("preflight_scope")
        != "complete_finite_root_candidate_union"
        or request.get("two_sample_required") is not True
        or request.get("target_broadening_allowed") is not False
        or request.get("mutation_authorized") is not False
    ):
        raise RuntimeError("manfred_capacity_root_attest_request_invalid")
    operator_home = _canonical_absolute(Path(operator.pw_dir), must_exist=True)
    deploy_root = _canonical_absolute(
        operator_home / DEPLOY_ROOT_RELATIVE, must_exist=True
    )
    if (
        request.get("operator_home") != str(operator_home)
        or request.get("deploy_root") != str(deploy_root)
    ):
        raise RuntimeError("manfred_capacity_root_deploy_root_invalid")
    projections = request.get("projections")
    if (
        not isinstance(projections, list)
        or len(projections) != EXPECTED_PROJECTION_COUNT
        or request.get("projection_count") != len(projections)
        or any(not isinstance(row, dict) for row in projections)
    ):
        raise RuntimeError("manfred_capacity_root_candidate_scope_invalid")
    rows = _validate_root_candidate_scope(
        request.get("root_candidates"),
        operator_uid=operator_uid,
        operator_home=operator_home,
        deploy_root=deploy_root,
        projections=projections,
    )
    if (
        request.get("root_candidate_count") != len(rows)
        or request.get("root_candidate_set_sha256")
        != _sha256(_json_bytes(rows))
    ):
        raise RuntimeError("manfred_capacity_root_candidate_scope_invalid")
    target = request.get("target_root_free_bytes")
    user_floor = request.get("user_eligible_reclaim_floor_bytes")
    if (
        target != TARGET_ROOT_FREE_BYTES
        or type(user_floor) is not int
        or user_floor < 0
        or request.get("guaranteed_user_reclaim_floor_bytes") != 0
    ):
        raise RuntimeError("manfred_capacity_root_target_invalid")
    capacity_lock = Path("/run/user") / str(operator_uid) / CAPACITY_LOCK_NAME
    with _exclusive_existing_lock(capacity_lock, uid=operator_uid) as capacity:
        with _exclusive_existing_lock(FLEET_LOCK_PATH, uid=operator_uid) as fleet:
            root_free = _root_free_bytes()
            preflight = _two_sample_root_preflight(rows)
            processes = dict(preflight["processes"])
            eligible_ids, authorized_ids, eligible_floor, authorized_floor = (
                _eligible_root_prefix(
                    rows,
                    referenced_action_ids=list(
                        processes["referenced_action_ids"]
                    ),
                    root_free_bytes=root_free,
                    user_reclaim_floor_bytes=user_floor,
                    target=target,
                )
            )
    receipt = {
        "schema": ROOT_ATTESTATION_SCHEMA,
        "status": "root_candidates_sufficient",
        "created_at": _utc_now(),
        "producer_sha256": producer_sha256,
        "root_applier_sha256": applier_sha256,
        "root_installer": dict(request["root_installer"]),
        "root_installer_sha256": installer_sha256,
        "operator_uid": operator_uid,
        "request_path": str(request_source_path),
        "request_sha256": request_sha256,
        "staged_request": staged_request,
        "staged_request_copy": staged_request_copy,
        "staged_root_applier": staged_applier,
        "staged_controller": staged_controller,
        "root_stage_path": str(stage),
        "plan_sha256": request["plan_sha256"],
        "root_candidate_set_sha256": request["root_candidate_set_sha256"],
        "root_candidate_count": len(rows),
        "root_free_bytes_at_attestation": root_free,
        "user_eligible_reclaim_floor_bytes": user_floor,
        "target_root_free_bytes": target,
        "eligible_root_action_ids": eligible_ids,
        "authorized_root_action_ids": authorized_ids,
        "referenced_root_action_ids": list(
            processes["referenced_action_ids"]
        ),
        "eligible_root_reclaim_floor_bytes": eligible_floor,
        "authorized_root_reclaim_floor_bytes": authorized_floor,
        "guaranteed_user_reclaim_floor_bytes": 0,
        "root_authorization_basis": "all_finite_eligible_candidates",
        "candidate_samples": preflight["candidates"],
        "first_process_inventory_sha256": preflight[
            "first_process_inventory_sha256"
        ],
        "second_process_inventory_sha256": preflight[
            "second_process_inventory_sha256"
        ],
        "all_process_fields_readable": processes[
            "all_process_fields_readable"
        ],
        "all_host_mounts_inventoried": True,
        "all_docker_mounts_inventoried": True,
        "host_mount_inventory": preflight["host_mounts"],
        "docker_mount_inventory": preflight["docker_mounts"],
        "global_preflight_complete": preflight["global_preflight_complete"],
        "two_sample_stable": preflight["two_sample_stable"],
        "capacity_lock": capacity,
        "fleet_lock": fleet,
        "mutation_performed": False,
        "target_broadened": False,
        "secrets_included": False,
    }
    receipt_sha = _atomic_root_receipt(
        root_attestation_path, receipt, operator_gid=operator.pw_gid
    )
    return {
        **receipt,
        "receipt_path": str(root_attestation_path),
        "receipt_sha256": receipt_sha,
    }


def apply(
    *,
    operator_uid: int,
    handoff_path: Path,
    handoff_source_path: Path,
    handoff_sha256: str,
    user_receipt_path: Path,
    user_receipt_source_path: Path,
    user_receipt_sha256: str,
    root_receipt_path: Path,
    applier_sha256: str,
    controller_copy_path: Path,
    installer_sha256: str,
    stage_path: Path,
) -> dict[str, object]:
    if os.geteuid() != 0:
        raise RuntimeError("manfred_capacity_root_requires_root")
    if (
        type(operator_uid) is not int
        or operator_uid < 1
        or any(
            HEX_64.fullmatch(value) is None
            for value in (
                handoff_sha256,
                user_receipt_sha256,
                applier_sha256,
                installer_sha256,
            )
        )
    ):
        raise RuntimeError("manfred_capacity_root_digest_invalid")
    try:
        operator = pwd.getpwuid(operator_uid)
    except KeyError as exc:
        raise RuntimeError("manfred_capacity_root_operator_invalid") from exc
    root_receipt_path = _validate_root_receipt_destination(
        root_receipt_path, operator_gid=operator.pw_gid
    )
    applier_copy = Path(__file__).resolve(strict=True)
    handoff_probe = _canonical_absolute(handoff_path, must_exist=True)
    user_receipt_copy = _canonical_absolute(user_receipt_path, must_exist=True)
    controller_copy = _canonical_absolute(controller_copy_path, must_exist=True)
    stage = _validate_root_stage(
        stage_path=stage_path,
        applier_path=applier_copy,
        controller_path=controller_copy,
        handoff_path=handoff_probe,
        user_receipt_path=user_receipt_copy,
    )
    for source in (handoff_source_path, user_receipt_source_path):
        if (
            not source.is_absolute()
            or ".." in source.parts
            or source == handoff_probe
            or source == user_receipt_copy
            or ROOT_STAGE_PARENT in source.parents
        ):
            raise RuntimeError("manfred_capacity_root_source_binding_invalid")
    applier_content, staged_applier = _staged_evidence(
        applier_copy, mode=0o500, expected_sha256=applier_sha256
    )
    controller_content, staged_controller = _staged_evidence(
        controller_copy, mode=0o400, expected_sha256=None
    )
    handoff_content, staged_handoff = _staged_evidence(
        handoff_probe, mode=0o400, expected_sha256=handoff_sha256
    )
    user_content, staged_user_receipt = _staged_evidence(
        user_receipt_copy,
        mode=0o400,
        expected_sha256=user_receipt_sha256,
    )
    try:
        handoff_raw = json.loads(handoff_content)
        user_raw = json.loads(user_content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("manfred_capacity_root_json_invalid") from exc
    if not isinstance(handoff_raw, dict) or not isinstance(user_raw, dict):
        raise RuntimeError("manfred_capacity_root_json_invalid")
    handoff = dict(handoff_raw)
    user = dict(user_raw)
    applier_source = handoff.get("root_applier_source")
    producer_source = handoff.get("producer_source")
    applier_source_path = handoff.get("root_applier_path")
    producer_source_path = handoff.get("producer_path")
    # The controller digest is learned from the already hash-bound handoff, then
    # checked against the staged controller bytes before any target is opened.
    producer_sha256 = str(handoff.get("producer_sha256") or "")
    if HEX_64.fullmatch(producer_sha256) is None:
        raise RuntimeError("manfred_capacity_root_handoff_invalid")
    if _sha256(controller_content) != producer_sha256:
        raise RuntimeError("manfred_capacity_root_controller_changed")
    staged_controller["sha256"] = producer_sha256
    if (
        handoff.get("schema") != HANDOFF_SCHEMA
        or handoff.get("operator_uid") != operator_uid
        or handoff.get("root_applier_sha256") != applier_sha256
        or not _source_binding_valid(
            applier_source,
            expected_path=applier_source_path,
            expected_sha256=applier_sha256,
            operator_uid=operator_uid,
        )
        or dict(applier_source).get("size_bytes") != len(applier_content)
        or not _source_binding_valid(
            producer_source,
            expected_path=producer_source_path,
            expected_sha256=producer_sha256,
            operator_uid=operator_uid,
        )
        or dict(producer_source).get("size_bytes") != len(controller_content)
        or handoff.get("root_installer_sha256") != installer_sha256
        or not _installer_binding_valid(
            handoff.get("root_installer"), installer_sha256=installer_sha256
        )
        or handoff.get("root_stage_contract") != _root_stage_contract()
        or handoff.get("target_broadening_allowed") is not False
        or handoff.get("delete_scope")
        != "attested_finite_root_candidate_prefix_only"
        or handoff.get("candidate_roots_removed") is not False
        or handoff.get("runtime_removed") is not False
        or handoff.get("receipts_removed") is not False
        or handoff.get("environment_files_removed") is not False
        or handoff.get("handoff_source_path") != str(handoff_source_path)
        or handoff.get("user_receipt_path") != str(user_receipt_source_path)
        or handoff.get("root_receipt_path") != str(root_receipt_path)
    ):
        raise RuntimeError("manfred_capacity_root_handoff_invalid")
    if (
        user.get("schema") != USER_RECEIPT_SCHEMA
        or user.get("status") != "root_handoff_required"
        or user.get("root_handoff_path") != handoff.get("handoff_source_path")
        or user.get("root_handoff_sha256") != handoff_sha256
        or user.get("root_receipt_path") != handoff.get("root_receipt_path")
        or user.get("intent_sha256") != handoff.get("intent_sha256")
        or user.get("plan_sha256") != handoff.get("plan_sha256")
        or user.get("root_installer") != handoff.get("root_installer")
        or user.get("root_installer_sha256") != installer_sha256
        or user.get("root_apply_argv") is not None
        or user.get("root_apply_argv_persisted") is not False
        or user.get("root_actions_performed") is not False
        or user.get("root_handoff_required") is not True
        or user.get("projection_deletion_authorized") is not True
        or user.get("root_candidate_deletion_authorized") is not True
        or user.get("projection_deletion_performed") is not False
        or user.get("root_attestation_path")
        != handoff.get("root_attestation_path")
        or user.get("root_attestation_sha256")
        != handoff.get("root_attestation_sha256")
    ):
        raise RuntimeError("manfred_capacity_root_user_receipt_invalid")
    attestation_path = Path(str(handoff.get("root_attestation_path") or ""))
    attestation_content, attestation_sha = _read_regular(
        attestation_path,
        expected_uid=0,
        expected_gid=operator.pw_gid,
        expected_mode=0o640,
        maximum=MAX_JSON_BYTES,
    )
    try:
        attestation_raw = json.loads(attestation_content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("manfred_capacity_root_attestation_invalid") from exc
    if not isinstance(attestation_raw, dict):
        raise RuntimeError("manfred_capacity_root_attestation_invalid")
    attestation = dict(attestation_raw)
    if (
        attestation_sha != handoff.get("root_attestation_sha256")
        or attestation != handoff.get("root_attestation")
        or attestation.get("schema") != ROOT_ATTESTATION_SCHEMA
        or attestation.get("status") != "root_candidates_sufficient"
        or attestation.get("operator_uid") != operator_uid
        or attestation.get("plan_sha256") != handoff.get("plan_sha256")
        or attestation.get("producer_sha256") != producer_sha256
        or attestation.get("root_applier_sha256") != applier_sha256
        or attestation.get("root_installer") != handoff.get("root_installer")
        or attestation.get("root_installer_sha256") != installer_sha256
        or attestation.get("root_candidate_set_sha256")
        != handoff.get("root_candidate_set_sha256")
        or attestation.get("authorized_root_action_ids")
        != handoff.get("authorized_root_action_ids")
        or attestation.get("global_preflight_complete") is not True
        or attestation.get("two_sample_stable") is not True
        or attestation.get("all_process_fields_readable") is not True
        or attestation.get("all_host_mounts_inventoried") is not True
        or attestation.get("all_docker_mounts_inventoried") is not True
        or attestation.get("guaranteed_user_reclaim_floor_bytes") != 0
        or attestation.get("root_authorization_basis")
        != "all_finite_eligible_candidates"
        or attestation.get("mutation_performed") is not False
        or attestation.get("target_broadened") is not False
    ):
        raise RuntimeError("manfred_capacity_root_attestation_invalid")
    projections = handoff.get("projections")
    projection_identities = (
        [
            (
                str(row.get("path") or ""),
                str(row.get("candidate_root") or ""),
                str(row.get("release_id") or ""),
            )
            for row in projections
        ]
        if isinstance(projections, list)
        and all(isinstance(row, dict) for row in projections)
        else []
    )
    if (
        not isinstance(projections, list)
        or any(not isinstance(row, dict) for row in projections)
        or any(not all(identity) for identity in projection_identities)
        or len(set(projection_identities)) != len(projection_identities)
        or len({row[0] for row in projection_identities}) != len(projection_identities)
        or len({row[1] for row in projection_identities}) != len(projection_identities)
        or len({row[2] for row in projection_identities}) != len(projection_identities)
        or len(projections) != handoff.get("projection_count")
        or len(projections) != EXPECTED_PROJECTION_COUNT
        or len(projections) > MAX_PROJECTIONS
        or any(
            row.get("root_revalidation_required") is not True
            or row.get("process_reference_check")
            != "root_revalidation_required"
            or row.get("process_references") is not None
            or type(row.get("runtime_uid")) is not int
            or int(row["runtime_uid"]) < 1
            or int(row["runtime_uid"]) == operator_uid
            or row.get("release_authority_promotion_authority") is not False
            or row.get("release_authority_runtime_clear") is not True
            for row in projections
        )
    ):
        raise RuntimeError("manfred_capacity_root_handoff_invalid")
    operator_home = _canonical_absolute(Path(operator.pw_dir), must_exist=True)
    expected_deploy_root = _canonical_absolute(
        operator_home / DEPLOY_ROOT_RELATIVE, must_exist=True
    )
    deploy_root = _canonical_absolute(
        Path(str(handoff.get("deploy_root") or "")), must_exist=True
    )
    if (
        deploy_root != expected_deploy_root
        or handoff.get("operator_home") != str(operator_home)
    ):
        raise RuntimeError("manfred_capacity_root_deploy_root_invalid")
    root_candidates = _validate_root_candidate_scope(
        handoff.get("root_candidates"),
        operator_uid=operator_uid,
        operator_home=operator_home,
        deploy_root=deploy_root,
        projections=projections,
    )
    if (
        handoff.get("root_candidate_count") != len(root_candidates)
        or handoff.get("root_candidate_set_sha256")
        != _sha256(_json_bytes(root_candidates))
        or attestation.get("root_candidate_count") != len(root_candidates)
    ):
        raise RuntimeError("manfred_capacity_root_candidate_scope_invalid")
    authorized_ids = handoff.get("authorized_root_action_ids")
    candidate_ids = [str(row["action_id"]) for row in root_candidates]
    if (
        not isinstance(authorized_ids, list)
        or any(type(value) is not str for value in authorized_ids)
        or len(set(authorized_ids)) != len(authorized_ids)
        or any(value not in candidate_ids for value in authorized_ids)
        or authorized_ids
        != list(attestation.get("eligible_root_action_ids") or [
        ])[: len(authorized_ids)]
    ):
        raise RuntimeError("manfred_capacity_root_attestation_invalid")
    target = handoff.get("target_root_free_bytes")
    if type(target) is not int or target != TARGET_ROOT_FREE_BYTES:
        raise RuntimeError("manfred_capacity_root_handoff_invalid")
    capacity_lock = Path("/run/user") / str(operator_uid) / CAPACITY_LOCK_NAME
    before_free = _root_free_bytes()
    actions: list[dict[str, object]] = []
    deploy_descriptor = -1
    quarantine_descriptor = -1
    quarantine_path: Path | None = None
    recovery_root = QUARANTINE_ROOT / handoff_sha256
    if os.path.lexists(recovery_root):
        recovery_root = _canonical_absolute(recovery_root, must_exist=True)
        recovery_status = recovery_root.stat()
        if (
            not stat.S_ISDIR(recovery_status.st_mode)
            or recovery_status.st_uid != 0
            or stat.S_IMODE(recovery_status.st_mode) != 0o700
            or recovery_status.st_dev != os.stat("/").st_dev
        ):
            raise RuntimeError("manfred_capacity_root_quarantine_invalid")
    else:
        recovery_root = None
    attested_samples = {
        str(row.get("action_id") or ""): dict(row)
        for row in list(attestation.get("candidate_samples") or [])
        if isinstance(row, dict)
    }
    if set(attested_samples) != set(candidate_ids):
        raise RuntimeError("manfred_capacity_root_attestation_invalid")

    def checked_preflight(rows: list[dict[str, object]]) -> dict[str, object]:
        if not rows:
            return {
                "candidates": [],
                "processes": {
                    "referenced_action_ids": [],
                    "all_process_fields_readable": True,
                },
                "global_preflight_complete": True,
                "two_sample_stable": True,
            }
        observed = _two_sample_root_preflight(
            rows,
            recovery_root=recovery_root,
        )
        for sample in list(observed["candidates"]):
            if attested_samples.get(str(sample["action_id"])) != sample:
                raise RuntimeError("manfred_capacity_root_attestation_drift")
        return observed

    with _exclusive_existing_lock(capacity_lock, uid=operator_uid) as capacity:
        with _exclusive_existing_lock(FLEET_LOCK_PATH, uid=operator_uid) as fleet:
            with contextlib.ExitStack() as resources:
                initial_preflight = checked_preflight(root_candidates)
                initially_referenced = set(
                    dict(initial_preflight["processes"])[
                        "referenced_action_ids"
                    ]
                )
                authorized_rows = [
                    row
                    for action_id in authorized_ids
                    for row in root_candidates
                    if row["action_id"] == action_id
                ]
                available_floor = sum(
                    int(row["root_reclaim_floor_bytes"])
                    for row in authorized_rows
                    if row["action_id"] not in initially_referenced
                )
                if before_free < target and before_free + available_floor < target:
                    raise RuntimeError("manfred_capacity_root_candidates_insufficient")

                def ensure_quarantine() -> None:
                    nonlocal deploy_descriptor, quarantine_descriptor, quarantine_path
                    if quarantine_descriptor < 0:
                        deploy_descriptor = _directory_fd(
                            deploy_root, expected_uid=operator_uid
                        )
                        resources.callback(os.close, deploy_descriptor)
                        quarantine_descriptor, quarantine_path = resources.enter_context(
                            _root_quarantine(
                                handoff_sha256=handoff_sha256,
                                deploy_device=os.fstat(deploy_descriptor).st_dev,
                            )
                        )
                    if quarantine_path is None:
                        raise RuntimeError("manfred_capacity_root_quarantine_invalid")

                completed_ids: set[str] = set()
                capacity_latched = before_free >= target
                for row in root_candidates:
                    action_id = str(row["action_id"])
                    base = {
                        "action_id": action_id,
                        "kind": row["kind"],
                        "path": row["path"],
                        "allocated_bytes": int(row["root_reclaim_floor_bytes"]),
                    }
                    if capacity_latched:
                        actions.append({**base, "status": "preserved_capacity_ready"})
                        continue
                    if action_id not in authorized_ids:
                        actions.append({**base, "status": "preserved_not_authorized"})
                        continue
                    remaining_rows = [
                        candidate
                        for candidate in root_candidates
                        if candidate["action_id"] not in completed_ids
                    ]
                    action_preflight = checked_preflight(remaining_rows)
                    referenced_now = set(
                        dict(action_preflight["processes"])[
                            "referenced_action_ids"
                        ]
                    )
                    if action_id in referenced_now:
                        actions.append({**base, "status": "preserved_referenced"})
                        continue
                    ensure_quarantine()
                    if quarantine_path is None:
                        raise RuntimeError("manfred_capacity_root_quarantine_invalid")
                    if row["kind"] == "candidate_release_projection":
                        result = _validate_projection(
                            dict(row["projection"]),
                            deploy_descriptor=deploy_descriptor,
                            deploy_root=deploy_root,
                            operator_uid=operator_uid,
                            handoff_sha256=handoff_sha256,
                            quarantine_descriptor=quarantine_descriptor,
                            quarantine_root=quarantine_path,
                        )
                    else:
                        first_guard = True

                        def pre_mutation() -> None:
                            nonlocal first_guard
                            if first_guard:
                                first_guard = False
                                checked_preflight(remaining_rows)

                        result = _remove_generic_candidate(
                            row,
                            handoff_sha256=handoff_sha256,
                            quarantine_descriptor=quarantine_descriptor,
                            quarantine_root=quarantine_path,
                            pre_mutation=pre_mutation,
                        )
                    result = {**base, **result}
                    actions.append(result)
                    if result.get("status") in {
                        *DELETION_STATUSES,
                        "already_absent",
                    }:
                        completed_ids.add(action_id)
                    current_free = _root_free_bytes()
                    if current_free >= target:
                        capacity_latched = True
    after_free = _root_free_bytes()
    removed_count = sum(row.get("status") in DELETION_STATUSES for row in actions)
    removed_projection_count = sum(
        row.get("status") in DELETION_STATUSES
        and row.get("kind") == "candidate_release_projection"
        for row in actions
    )
    preserved_count = sum(
        row.get("kind") == "candidate_release_projection"
        and row.get("status") in PRESERVED_STATUSES
        for row in actions
    )
    receipt = {
        "schema": ROOT_RECEIPT_SCHEMA,
        "status": "capacity_ready" if after_free >= target else "capacity_insufficient",
        "created_at": _utc_now(),
        "producer_path": str(producer_source_path),
        "producer_sha256": handoff["producer_sha256"],
        "producer_source": dict(producer_source),
        "staged_controller": staged_controller,
        "root_applier_path": str(applier_source_path),
        "root_applier_sha256": applier_sha256,
        "root_applier_source": dict(applier_source),
        "staged_root_applier": staged_applier,
        "root_installer": dict(handoff["root_installer"]),
        "root_installer_sha256": installer_sha256,
        "root_stage_path": str(stage),
        "root_stage_mode": 0o700,
        "root_stage_nlink": 2,
        "operator_uid": operator_uid,
        "handoff_path": str(handoff_source_path),
        "handoff_sha256": handoff_sha256,
        "staged_handoff": staged_handoff,
        "user_receipt_path": str(user_receipt_source_path),
        "user_receipt_sha256": user_receipt_sha256,
        "staged_user_receipt": staged_user_receipt,
        "intent_sha256": handoff["intent_sha256"],
        "plan_sha256": handoff["plan_sha256"],
        "target_root_free_bytes": target,
        "root_free_bytes_before": before_free,
        "root_free_bytes_after": after_free,
        "actions": actions,
        "projection_count": EXPECTED_PROJECTION_COUNT,
        "root_candidate_count": len(actions),
        "authorized_root_action_ids": list(authorized_ids),
        "root_attestation_path": str(attestation_path),
        "root_attestation_sha256": attestation_sha,
        "root_candidate_set_sha256": handoff["root_candidate_set_sha256"],
        "global_preflight_complete_before_mutation": True,
        "projection_deletion_performed": bool(removed_projection_count),
        "root_candidate_deletion_performed": bool(removed_count),
        "projections_preserved_count": preserved_count,
        "capacity_lock": capacity,
        "fleet_lock": fleet,
        "candidate_roots_removed": False,
        "runtime_removed": False,
        "receipts_removed": False,
        "docker_mutations_performed": False,
        "target_broadened": False,
        "inline_installer_execution_trust_boundary": True,
        "user_writable_root_interpreted_file": False,
        "secrets_included": False,
    }
    receipt_sha = _atomic_root_receipt(
        root_receipt_path, receipt, operator_gid=operator.pw_gid
    )
    return {
        **receipt,
        "receipt_path": str(root_receipt_path),
        "receipt_sha256": receipt_sha,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operator-uid", type=int, required=True)
    parser.add_argument("--handoff", type=Path, required=True)
    parser.add_argument("--handoff-source", type=Path, required=True)
    parser.add_argument("--handoff-sha256", required=True)
    parser.add_argument("--user-receipt", type=Path, required=True)
    parser.add_argument("--user-receipt-source", type=Path, required=True)
    parser.add_argument("--user-receipt-sha256", required=True)
    parser.add_argument("--root-receipt", type=Path, required=True)
    parser.add_argument("--root-applier-sha256", required=True)
    parser.add_argument("--controller-copy", type=Path, required=True)
    parser.add_argument("--installer-sha256", required=True)
    parser.add_argument("--stage-path", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        arguments = _parser().parse_args(argv)
        staged_payload, _staged_sha = _read_json(
            arguments.handoff, expected_uid=0, expected_mode=0o400
        )
        if staged_payload.get("schema") == ROOT_ATTEST_REQUEST_SCHEMA:
            result = attest(
                operator_uid=arguments.operator_uid,
                request_path=arguments.handoff,
                request_source_path=arguments.handoff_source,
                request_sha256=arguments.handoff_sha256,
                request_copy_path=arguments.user_receipt,
                request_copy_source_path=arguments.user_receipt_source,
                request_copy_sha256=arguments.user_receipt_sha256,
                root_attestation_path=arguments.root_receipt,
                applier_sha256=arguments.root_applier_sha256,
                controller_copy_path=arguments.controller_copy,
                installer_sha256=arguments.installer_sha256,
                stage_path=arguments.stage_path,
            )
        elif staged_payload.get("schema") == HANDOFF_SCHEMA:
            result = apply(
                operator_uid=arguments.operator_uid,
                handoff_path=arguments.handoff,
                handoff_source_path=arguments.handoff_source,
                handoff_sha256=arguments.handoff_sha256,
                user_receipt_path=arguments.user_receipt,
                user_receipt_source_path=arguments.user_receipt_source,
                user_receipt_sha256=arguments.user_receipt_sha256,
                root_receipt_path=arguments.root_receipt,
                applier_sha256=arguments.root_applier_sha256,
                controller_copy_path=arguments.controller_copy,
                installer_sha256=arguments.installer_sha256,
                stage_path=arguments.stage_path,
            )
        else:
            raise RuntimeError("manfred_capacity_root_schema_invalid")
        print(json.dumps(result, sort_keys=True))
        return 0
    except (RuntimeError, OSError, KeyError, TypeError, ValueError) as exc:
        reason = str(exc)
        if re.fullmatch(r"[a-z0-9_]{1,160}", reason) is None:
            reason = "manfred_capacity_root_failed"
        print(json.dumps({"status": "fail", "reason": reason}, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
