#!/usr/bin/env python3
"""Fail-closed access checks for bind sources used by the memorial API.

The check models the numeric container uid, primary gid, and supplemental gids
against host mode bits.  Release-owned directory mounts are walked with
descriptor-relative, no-follow opens; external data mounts are bounded to their
mount roots so a preflight cannot recursively scan an unbounded media tree.
No file contents are read and evidence contains only hashes of host paths.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import stat
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Mapping, Sequence


SCHEMA = "ea.memorial_bind_source_access.v1"
EXPECTED_USER = "10001:10001"
DEFAULT_MAX_RELEASE_ENTRIES = 50_000
DEFAULT_MAX_RELEASE_BYTES = 2 * 1024**3
DEFAULT_MAX_RELEASE_DEPTH = 64
DEFAULT_TIMEOUT_SECONDS = 20.0


class BindSourceGuardError(RuntimeError):
    """A stable, secret-free bind-source denial reason."""


@dataclass
class _Budget:
    maximum_entries: int
    maximum_bytes: int
    deadline: float
    entries: int = 0
    files: int = 0
    directories: int = 0
    bytes: int = 0

    def charge(self, *, kind: str, size: int = 0) -> None:
        if time.monotonic() > self.deadline:
            raise BindSourceGuardError("bind_source_scan_timeout")
        self.entries += 1
        self.bytes += max(int(size), 0)
        if kind == "file":
            self.files += 1
        elif kind == "directory":
            self.directories += 1
        if self.entries > self.maximum_entries or self.bytes > self.maximum_bytes:
            raise BindSourceGuardError("bind_source_scan_budget_exceeded")


def _metadata_identity(metadata: os.stat_result) -> tuple[int, ...]:
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


def _inode_identity(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_uid,
        metadata.st_gid,
    )


def _external_identity(
    metadata: os.stat_result, *, kind: str
) -> tuple[int, ...]:
    identity = _inode_identity(metadata)
    return identity if kind == "directory" else (*identity, metadata.st_nlink)


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _parse_numeric_identity(value: object) -> tuple[int, int]:
    normalized = str(value or "").strip()
    pieces = normalized.split(":")
    if (
        len(pieces) != 2
        or any(not piece.isdigit() for piece in pieces)
        or any(str(int(piece)) != piece for piece in pieces)
    ):
        raise BindSourceGuardError("memorial_api_numeric_user_required")
    uid, gid = (int(piece) for piece in pieces)
    if not 1 <= uid <= 2**31 - 1 or not 1 <= gid <= 2**31 - 1:
        raise BindSourceGuardError("memorial_api_numeric_user_invalid")
    return uid, gid


def _supplemental_gids(value: object, *, primary_gid: int) -> frozenset[int]:
    if value is None:
        rows: Sequence[object] = ()
    elif isinstance(value, list):
        rows = value
    else:
        raise BindSourceGuardError("memorial_api_group_add_invalid")
    gids = {primary_gid}
    for row in rows:
        normalized = str(row or "").strip()
        if not normalized.isdigit() or str(int(normalized)) != normalized:
            raise BindSourceGuardError("memorial_api_group_add_must_be_numeric")
        gid = int(normalized)
        if not 1 <= gid <= 2**31 - 1:
            raise BindSourceGuardError("memorial_api_group_add_invalid")
        gids.add(gid)
    return frozenset(gids)


def _permission_bits(metadata: os.stat_result, *, uid: int, gids: frozenset[int]) -> int:
    mode = stat.S_IMODE(metadata.st_mode)
    if metadata.st_uid == uid:
        return (mode >> 6) & 0o7
    if metadata.st_gid in gids:
        return (mode >> 3) & 0o7
    return mode & 0o7


def _require_access(
    metadata: os.stat_result,
    *,
    uid: int,
    gids: frozenset[int],
    directory: bool,
    writable: bool = False,
) -> None:
    bits = _permission_bits(metadata, uid=uid, gids=gids)
    required = (
        (0o7 if writable else 0o5)
        if directory
        else (0o6 if writable else 0o4)
    )
    if bits & required != required:
        reason = (
            "bind_source_directory_not_readable_searchable"
            if directory
            else "bind_source_file_not_readable"
        )
        raise BindSourceGuardError(reason)


def _reject_access_acl(descriptor: int) -> None:
    try:
        acl = os.getxattr(descriptor, "system.posix_acl_access")
    except OSError as exc:
        if exc.errno in {errno.ENODATA, errno.ENOTSUP, errno.EOPNOTSUPP}:
            return
        raise BindSourceGuardError("bind_source_acl_status_unavailable") from exc
    if acl:
        raise BindSourceGuardError("bind_source_posix_acl_unsupported")


def _open_parent_no_symlink(path: Path) -> int:
    if not path.is_absolute() or path.name in {"", ".", ".."}:
        raise BindSourceGuardError("bind_source_path_invalid")
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_PATH"):
        raise BindSourceGuardError("bind_source_nofollow_unavailable")
    flags = os.O_PATH | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
    descriptor = os.open("/", flags)
    try:
        for component in path.parent.parts[1:]:
            next_descriptor = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor
    except OSError as exc:
        os.close(descriptor)
        raise BindSourceGuardError("bind_source_parent_unavailable") from exc


def _open_source(path: Path) -> tuple[int, os.stat_result, str]:
    parent_descriptor = _open_parent_no_symlink(path)
    descriptor = -1
    try:
        initial = os.stat(path.name, dir_fd=parent_descriptor, follow_symlinks=False)
        if stat.S_ISLNK(initial.st_mode):
            raise BindSourceGuardError("bind_source_symlink_forbidden")
        if stat.S_ISDIR(initial.st_mode):
            kind = "directory"
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
        elif stat.S_ISREG(initial.st_mode):
            kind = "file"
            flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
        else:
            raise BindSourceGuardError("bind_source_type_invalid")
        descriptor = os.open(path.name, flags, dir_fd=parent_descriptor)
        opened = os.fstat(descriptor)
        if _inode_identity(initial) != _inode_identity(opened):
            raise BindSourceGuardError("bind_source_changed_during_open")
        result = descriptor, opened, kind
        descriptor = -1
        return result
    except FileNotFoundError as exc:
        raise BindSourceGuardError("bind_source_missing") from exc
    except PermissionError as exc:
        raise BindSourceGuardError("bind_source_operator_access_denied") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        os.close(parent_descriptor)


def _walk_release_directory(
    descriptor: int,
    *,
    uid: int,
    gids: frozenset[int],
    budget: _Budget,
    identities: list[dict[str, object]],
    relative: tuple[str, ...] = (),
    maximum_depth: int = DEFAULT_MAX_RELEASE_DEPTH,
) -> None:
    before = os.fstat(descriptor)
    if not stat.S_ISDIR(before.st_mode):
        raise BindSourceGuardError("bind_source_directory_identity_invalid")
    _require_access(before, uid=uid, gids=gids, directory=True)
    _reject_access_acl(descriptor)
    entries: list[tuple[str, os.stat_result]] = []
    with os.scandir(descriptor) as iterator:
        for entry in iterator:
            if time.monotonic() > budget.deadline:
                raise BindSourceGuardError("bind_source_scan_timeout")
            name = entry.name
            if name in {"", ".", ".."} or "/" in name or "\x00" in name:
                raise BindSourceGuardError("bind_source_entry_name_invalid")
            projected = (*relative, name)
            if len(projected) > maximum_depth:
                raise BindSourceGuardError("bind_source_scan_depth_exceeded")
            initial = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            if stat.S_ISLNK(initial.st_mode):
                raise BindSourceGuardError("bind_source_symlink_forbidden")
            if stat.S_ISDIR(initial.st_mode):
                budget.charge(kind="directory")
            elif stat.S_ISREG(initial.st_mode) and initial.st_nlink == 1:
                budget.charge(kind="file", size=initial.st_size)
            else:
                raise BindSourceGuardError("bind_source_release_file_invalid")
            entries.append((name, initial))
    entries.sort(key=lambda item: item[0])
    for name, initial in entries:
        if time.monotonic() > budget.deadline:
            raise BindSourceGuardError("bind_source_scan_timeout")
        projected = (*relative, name)
        path_hash = hashlib.sha256(PurePosixPath(*projected).as_posix().encode("utf-8")).hexdigest()
        if stat.S_ISDIR(initial.st_mode):
            child = os.open(
                name,
                os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
                dir_fd=descriptor,
            )
            try:
                opened = os.fstat(child)
                if _metadata_identity(initial) != _metadata_identity(opened):
                    raise BindSourceGuardError("bind_source_changed_during_walk")
                _require_access(opened, uid=uid, gids=gids, directory=True)
                identities.append(
                    {
                        "path_sha256": path_hash,
                        "kind": "directory",
                        "identity": _metadata_identity(opened),
                    }
                )
                _walk_release_directory(
                    child,
                    uid=uid,
                    gids=gids,
                    budget=budget,
                    identities=identities,
                    relative=projected,
                    maximum_depth=maximum_depth,
                )
                if _metadata_identity(opened) != _metadata_identity(os.fstat(child)):
                    raise BindSourceGuardError("bind_source_changed_during_walk")
            finally:
                os.close(child)
            continue
        child = os.open(
            name,
            os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=descriptor,
        )
        try:
            opened = os.fstat(child)
            if _metadata_identity(initial) != _metadata_identity(opened):
                raise BindSourceGuardError("bind_source_changed_during_walk")
            _require_access(opened, uid=uid, gids=gids, directory=False)
            _reject_access_acl(child)
            identities.append(
                {
                    "path_sha256": path_hash,
                    "kind": "file",
                    "identity": _metadata_identity(opened),
                }
            )
        finally:
            os.close(child)
    if _metadata_identity(before) != _metadata_identity(os.fstat(descriptor)):
        raise BindSourceGuardError("bind_source_changed_during_walk")


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _validate_memorial_bind_sources(
    rendered_compose: Mapping[str, object],
    *,
    service: str,
    release_root: Path,
    expected_user: str = EXPECTED_USER,
    expected_snapshot_sha256: str = "",
    maximum_release_entries: int = DEFAULT_MAX_RELEASE_ENTRIES,
    maximum_release_bytes: int = DEFAULT_MAX_RELEASE_BYTES,
    maximum_release_depth: int = DEFAULT_MAX_RELEASE_DEPTH,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, object]:
    services = rendered_compose.get("services")
    if not isinstance(services, dict) or not isinstance(services.get(service), dict):
        raise BindSourceGuardError("memorial_api_service_missing")
    config = dict(services[service])
    if str(config.get("user") or "").strip() != expected_user:
        raise BindSourceGuardError("memorial_api_explicit_user_mismatch")
    uid, primary_gid = _parse_numeric_identity(config.get("user"))
    gids = _supplemental_gids(config.get("group_add"), primary_gid=primary_gid)
    release_root = Path(os.path.abspath(os.fspath(release_root.expanduser())))
    if not release_root.is_absolute():
        raise BindSourceGuardError("release_root_invalid")
    release_descriptor, _release_metadata, release_kind = _open_source(release_root)
    os.close(release_descriptor)
    if release_kind != "directory":
        raise BindSourceGuardError("release_root_invalid")
    volumes = config.get("volumes") or []
    if not isinstance(volumes, list):
        raise BindSourceGuardError("memorial_api_volumes_invalid")
    if (
        type(maximum_release_entries) is not int
        or maximum_release_entries < 1
        or type(maximum_release_bytes) is not int
        or maximum_release_bytes < 1
        or type(maximum_release_depth) is not int
        or not 1 <= maximum_release_depth <= 256
        or not 0 < float(timeout_seconds) <= 120
    ):
        raise BindSourceGuardError("bind_source_budget_invalid")
    budget = _Budget(
        maximum_entries=maximum_release_entries,
        maximum_bytes=maximum_release_bytes,
        deadline=time.monotonic() + float(timeout_seconds),
    )
    mount_evidence: list[dict[str, object]] = []
    snapshot_rows: list[dict[str, object]] = []
    targets: set[str] = set()
    for raw_mount in volumes:
        if not isinstance(raw_mount, dict):
            raise BindSourceGuardError("memorial_api_mount_invalid")
        if str(raw_mount.get("type") or "") != "bind":
            continue
        source_value = str(raw_mount.get("source") or "")
        target = str(raw_mount.get("target") or "")
        target_path = PurePosixPath(target)
        if (
            not source_value
            or target == "/"
            or target_path.root != "/"
            or target_path.as_posix() != target
            or ".." in target_path.parts
            or "\x00" in source_value
            or "\x00" in target
            or target in targets
        ):
            raise BindSourceGuardError("memorial_api_bind_mount_invalid")
        if type(raw_mount.get("read_only")) is not bool:
            raise BindSourceGuardError("memorial_api_bind_read_only_invalid")
        targets.add(target)
        source = Path(source_value)
        normalized_source = Path(os.path.abspath(os.fspath(source)))
        if not source.is_absolute() or source != normalized_source:
            raise BindSourceGuardError("bind_source_not_absolute")
        source = normalized_source
        descriptor, metadata, kind = _open_source(source)
        identities: list[dict[str, object]] = []
        try:
            under_release = _is_within(source, release_root)
            read_only = raw_mount["read_only"]
            stable_identity = (
                _metadata_identity(metadata)
                if under_release
                else _external_identity(metadata, kind=kind)
            )
            if under_release and not read_only:
                raise BindSourceGuardError("bind_source_release_mount_must_be_read_only")
            _require_access(
                metadata,
                uid=uid,
                gids=gids,
                directory=kind == "directory",
                writable=not read_only,
            )
            _reject_access_acl(descriptor)
            if kind == "directory" and under_release:
                budget.charge(kind="directory")
                identities.append(
                    {
                        "path_sha256": hashlib.sha256(b".").hexdigest(),
                        "kind": "directory",
                        "identity": _metadata_identity(metadata),
                    }
                )
                _walk_release_directory(
                    descriptor,
                    uid=uid,
                    gids=gids,
                    budget=budget,
                    identities=identities,
                    maximum_depth=maximum_release_depth,
                )
            elif kind == "file" and under_release:
                if metadata.st_nlink != 1:
                    raise BindSourceGuardError("bind_source_release_file_invalid")
                budget.charge(kind="file", size=metadata.st_size)
                identities.append(
                    {
                        "path_sha256": hashlib.sha256(b".").hexdigest(),
                        "kind": "file",
                        "identity": _metadata_identity(metadata),
                    }
                )
            final_metadata = os.fstat(descriptor)
            final_identity = (
                _metadata_identity(final_metadata)
                if under_release
                else _external_identity(final_metadata, kind=kind)
            )
            if stable_identity != final_identity:
                raise BindSourceGuardError("bind_source_changed_during_validation")
        finally:
            os.close(descriptor)
        source_sha256 = hashlib.sha256(os.fspath(source).encode("utf-8")).hexdigest()
        identity_digest = _canonical_sha256(identities or [stable_identity])
        row = {
            "target": target,
            "source_sha256": source_sha256,
            "source_kind": kind,
            "under_release_root": under_release,
            "scope": "full_tree" if under_release and kind == "directory" else "root_inode",
            "identity_sha256": identity_digest,
            "read_only": read_only,
        }
        mount_evidence.append(row)
        snapshot_rows.append({**row, "identities": identities})
    if not mount_evidence:
        raise BindSourceGuardError("memorial_api_bind_mounts_missing")
    mount_evidence.sort(key=lambda row: str(row["target"]))
    snapshot_rows.sort(key=lambda row: str(row["target"]))
    snapshot_sha256 = _canonical_sha256(
        {
            "service": service,
            "uid": uid,
            "primary_gid": primary_gid,
            "supplemental_gids": sorted(gids),
            "mounts": snapshot_rows,
        }
    )
    if expected_snapshot_sha256 and snapshot_sha256 != expected_snapshot_sha256:
        raise BindSourceGuardError("bind_source_snapshot_changed")
    return {
        "schema": SCHEMA,
        "status": "pass",
        "service": service,
        "user": expected_user,
        "uid": uid,
        "primary_gid": primary_gid,
        "supplemental_gids": sorted(gids),
        "bind_mount_count": len(mount_evidence),
        "release_tree_mount_count": sum(
            1 for row in mount_evidence if row["scope"] == "full_tree"
        ),
        "root_inode_mount_count": sum(
            1 for row in mount_evidence if row["scope"] == "root_inode"
        ),
        "release_entries_scanned": budget.entries,
        "release_files_scanned": budget.files,
        "release_directories_scanned": budget.directories,
        "release_bytes_accounted": budget.bytes,
        "snapshot_sha256": snapshot_sha256,
        "mounts": mount_evidence,
        "file_contents_read": False,
        "secrets_included": False,
    }


def validate_memorial_bind_sources(
    rendered_compose: Mapping[str, object],
    *,
    service: str,
    release_root: Path,
    expected_user: str = EXPECTED_USER,
    expected_snapshot_sha256: str = "",
    maximum_release_entries: int = DEFAULT_MAX_RELEASE_ENTRIES,
    maximum_release_bytes: int = DEFAULT_MAX_RELEASE_BYTES,
    maximum_release_depth: int = DEFAULT_MAX_RELEASE_DEPTH,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, object]:
    """Validate sources while keeping filesystem-race denials secret-free."""

    try:
        return _validate_memorial_bind_sources(
            rendered_compose,
            service=service,
            release_root=release_root,
            expected_user=expected_user,
            expected_snapshot_sha256=expected_snapshot_sha256,
            maximum_release_entries=maximum_release_entries,
            maximum_release_bytes=maximum_release_bytes,
            maximum_release_depth=maximum_release_depth,
            timeout_seconds=timeout_seconds,
        )
    except BindSourceGuardError:
        raise
    except OSError as exc:
        raise BindSourceGuardError("bind_source_filesystem_race") from exc
