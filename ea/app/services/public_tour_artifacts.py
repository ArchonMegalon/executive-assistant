from __future__ import annotations

import json
import os
import shutil
import stat
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO

from app.services.public_artifact_paths import public_tour_dir


PUBLIC_TOUR_DIRECTORY_MODE = 0o755
PUBLIC_TOUR_FILE_MODE = 0o644


def _public_tour_root(root: Path | None = None) -> Path:
    candidate = Path(os.path.abspath(Path(root if root is not None else public_tour_dir()).expanduser()))
    if os.path.lexists(candidate):
        root_stat = os.lstat(candidate)
        if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
            raise RuntimeError("public_tour_root_invalid")
    else:
        candidate.mkdir(parents=True, mode=PUBLIC_TOUR_DIRECTORY_MODE, exist_ok=True)
    os.chmod(candidate, PUBLIC_TOUR_DIRECTORY_MODE, follow_symlinks=False)
    return candidate


def _path_beneath_public_tour_root(path: Path, *, root: Path | None = None) -> tuple[Path, Path]:
    root_path = _public_tour_root(root)
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = root_path / candidate
    candidate = Path(os.path.abspath(candidate))
    try:
        candidate.relative_to(root_path)
    except ValueError as exc:
        raise RuntimeError("public_tour_path_outside_root") from exc
    return root_path, candidate


def _ensure_directory_chain(path: Path, *, root: Path | None = None) -> Path:
    root_path, candidate = _path_beneath_public_tour_root(path, root=root)
    relative = candidate.relative_to(root_path)
    cursor = root_path
    for part in relative.parts:
        cursor = cursor / part
        if os.path.lexists(cursor):
            cursor_stat = os.lstat(cursor)
            if stat.S_ISLNK(cursor_stat.st_mode) or not stat.S_ISDIR(cursor_stat.st_mode):
                raise RuntimeError("public_tour_directory_invalid")
        else:
            cursor.mkdir(mode=PUBLIC_TOUR_DIRECTORY_MODE)
        os.chmod(cursor, PUBLIC_TOUR_DIRECTORY_MODE, follow_symlinks=False)
    return candidate


def ensure_public_tour_directory(path: Path, *, root: Path | None = None) -> Path:
    return _ensure_directory_chain(path, root=root)


def _validate_public_file_target(path: Path, *, root: Path | None = None) -> Path:
    root_path, candidate = _path_beneath_public_tour_root(path, root=root)
    _ensure_directory_chain(candidate.parent, root=root_path)
    if os.path.lexists(candidate):
        target_stat = os.lstat(candidate)
        if stat.S_ISLNK(target_stat.st_mode) or not stat.S_ISREG(target_stat.st_mode):
            raise RuntimeError("public_tour_file_invalid")
    return candidate


def _atomic_write_public_tour_file(
    path: Path,
    writer: Callable[[BinaryIO], None],
    *,
    root: Path | None = None,
) -> Path:
    target = _validate_public_file_target(path, root=root)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, PUBLIC_TOUR_FILE_MODE)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            writer(handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, target)
        os.chmod(target, PUBLIC_TOUR_FILE_MODE, follow_symlinks=False)
        directory_descriptor = os.open(target.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary_path.unlink(missing_ok=True)
    return target


def write_public_tour_file(
    path: Path,
    writer: Callable[[BinaryIO], None],
    *,
    root: Path | None = None,
) -> Path:
    return _atomic_write_public_tour_file(path, writer, root=root)


def write_public_tour_bytes(path: Path, data: bytes, *, root: Path | None = None) -> Path:
    payload = bytes(data)
    return write_public_tour_file(path, lambda handle: handle.write(payload), root=root)


def write_public_tour_json(path: Path, payload: object, *, root: Path | None = None) -> Path:
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    return write_public_tour_bytes(path, encoded, root=root)


def copy_public_tour_file(source: Path, target: Path, *, root: Path | None = None) -> Path:
    source_path = Path(source)
    source_stat = os.lstat(source_path)
    if stat.S_ISLNK(source_stat.st_mode) or not stat.S_ISREG(source_stat.st_mode):
        raise RuntimeError("public_tour_copy_source_invalid")

    def _copy(handle: BinaryIO) -> None:
        with source_path.open("rb") as source_handle:
            shutil.copyfileobj(source_handle, handle, length=1024 * 1024)

    return _atomic_write_public_tour_file(target, _copy, root=root)


def normalize_public_tour_bundle_modes(bundle_dir: Path, *, root: Path | None = None) -> Path:
    directory = _ensure_directory_chain(bundle_dir, root=root)

    def _normalize(current: Path) -> None:
        current_stat = os.lstat(current)
        if stat.S_ISLNK(current_stat.st_mode) or not stat.S_ISDIR(current_stat.st_mode):
            raise RuntimeError("public_tour_directory_invalid")
        os.chmod(current, PUBLIC_TOUR_DIRECTORY_MODE, follow_symlinks=False)
        with os.scandir(current) as entries:
            for entry in entries:
                entry_path = Path(entry.path)
                entry_stat = entry.stat(follow_symlinks=False)
                if stat.S_ISLNK(entry_stat.st_mode):
                    raise RuntimeError("public_tour_bundle_symlink_forbidden")
                if stat.S_ISDIR(entry_stat.st_mode):
                    _normalize(entry_path)
                    continue
                if not stat.S_ISREG(entry_stat.st_mode):
                    raise RuntimeError("public_tour_bundle_entry_invalid")
                os.chmod(entry_path, PUBLIC_TOUR_FILE_MODE, follow_symlinks=False)

    _normalize(directory)
    return directory
