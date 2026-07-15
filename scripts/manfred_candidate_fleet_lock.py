#!/usr/bin/env python3
from __future__ import annotations

import contextlib
import errno
import fcntl
import os
import stat
from collections.abc import Iterator
from pathlib import Path


FLEET_LOCK_PATH = Path("/run/lock/ea-manfred-candidate-fleet.lock")
NAMESPACE_ROOT_OVERFLOW_UID = 65534
FLEET_LOCK_BUSY = "manfred_candidate_fleet_lock_held"
FLEET_LOCK_INVALID = "manfred_candidate_fleet_lock_invalid"
FLEET_LOCK_UNAVAILABLE = "manfred_candidate_fleet_lock_unavailable"


def _trusted_lock_directory_owner(path: Path, status: os.stat_result) -> bool:
    if status.st_uid in {0, os.getuid()}:
        return True
    return (
        path == FLEET_LOCK_PATH
        and status.st_uid == NAMESPACE_ROOT_OVERFLOW_UID
        and stat.S_IMODE(status.st_mode) == 0o1777
    )


def _normalized_lock_path(path: Path) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute() or candidate.name != FLEET_LOCK_PATH.name:
        raise RuntimeError(FLEET_LOCK_INVALID)
    try:
        parent = candidate.parent.resolve(strict=True)
    except OSError as exc:
        raise RuntimeError(FLEET_LOCK_UNAVAILABLE) from exc
    normalized = parent / candidate.name
    if normalized != candidate:
        raise RuntimeError(FLEET_LOCK_INVALID)
    return normalized


def _open_validated_lock(path: Path) -> tuple[int, int]:
    path = _normalized_lock_path(path)
    directory_descriptor = -1
    lock_descriptor = -1
    try:
        directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            directory_flags |= os.O_NOFOLLOW
        directory_descriptor = os.open(path.parent, directory_flags)
        directory_status = os.fstat(directory_descriptor)
        if (
            not stat.S_ISDIR(directory_status.st_mode)
            or not _trusted_lock_directory_owner(path, directory_status)
            or (
                directory_status.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
                and not directory_status.st_mode & stat.S_ISVTX
            )
        ):
            raise RuntimeError(FLEET_LOCK_INVALID)

        lock_flags = os.O_CREAT | os.O_RDWR | os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            lock_flags |= os.O_NOFOLLOW
        lock_descriptor = os.open(
            path.name,
            lock_flags,
            0o600,
            dir_fd=directory_descriptor,
        )
        lock_status = os.fstat(lock_descriptor)
        if (
            not stat.S_ISREG(lock_status.st_mode)
            or lock_status.st_uid != os.getuid()
            or lock_status.st_nlink != 1
            or stat.S_IMODE(lock_status.st_mode) != 0o600
        ):
            raise RuntimeError(FLEET_LOCK_INVALID)
        return directory_descriptor, lock_descriptor
    except RuntimeError:
        if lock_descriptor >= 0:
            os.close(lock_descriptor)
        if directory_descriptor >= 0:
            os.close(directory_descriptor)
        raise
    except OSError as exc:
        if lock_descriptor >= 0:
            os.close(lock_descriptor)
        if directory_descriptor >= 0:
            os.close(directory_descriptor)
        raise RuntimeError(FLEET_LOCK_UNAVAILABLE) from exc


@contextlib.contextmanager
def hold_candidate_fleet_lock(
    *,
    skip_if_busy: bool = False,
    lock_path: Path | None = None,
) -> Iterator[dict[str, object] | None]:
    """Hold the cross-project candidate lock without ever waiting."""

    path = Path(lock_path or FLEET_LOCK_PATH)
    directory_descriptor, lock_descriptor = _open_validated_lock(path)
    locked = False
    try:
        try:
            fcntl.flock(lock_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except OSError as exc:
            if exc.errno not in {errno.EACCES, errno.EAGAIN}:
                raise RuntimeError(FLEET_LOCK_UNAVAILABLE) from exc
            if skip_if_busy:
                yield None
                return
            raise RuntimeError(FLEET_LOCK_BUSY) from exc
        yield {
            "scope": "manfred_candidate_fleet",
            "lock_file": path.name,
            "exclusive": True,
            "nonblocking": True,
        }
    finally:
        if locked:
            with contextlib.suppress(OSError):
                fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
        os.close(lock_descriptor)
        os.close(directory_descriptor)
