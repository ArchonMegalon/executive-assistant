#!/usr/bin/env python3
"""Fail-closed interlocks for EA memorial recovery transactions.

The baseline normalizer owns a recovery journal distinct from the joint
API/ingress deployment journal.  Ordinary deployment lanes only need one
operation on that state: prove the journal is absent without following links
or trusting a mutable pathname.  Any present or indeterminate entry blocks.
"""

from __future__ import annotations

import os
import pwd
import stat
from pathlib import Path


NORMALIZATION_RECOVERY_STATE_DIRECTORY = ".ea-memorial-deploy-state"
NORMALIZATION_RECOVERY_JOURNAL_FILENAME = (
    "api-baseline-normalization-active-recovery.json"
)


class MemorialRecoveryInterlockError(RuntimeError):
    """Recovery state is active or cannot be proven safely absent."""


def default_normalization_recovery_journal_path(
    *, operator_anchor: Path
) -> Path:
    """Return the fixed journal path for the owner of a trusted release root.

    The process environment (notably ``HOME``) is not an authority for the
    recovery location.  A production lane binds the path to the account that
    owns its already-resolved release root and refuses cross-account execution.
    """
    if not _path_is_absolute_normal(operator_anchor):
        _raise_active_or_indeterminate()
    try:
        anchor_metadata = operator_anchor.lstat()
        account_home = Path(pwd.getpwuid(anchor_metadata.st_uid).pw_dir)
        account_home_metadata = account_home.lstat()
    except (KeyError, OSError):
        _raise_active_or_indeterminate()
    if (
        not stat.S_ISDIR(anchor_metadata.st_mode)
        or stat.S_ISLNK(anchor_metadata.st_mode)
        or anchor_metadata.st_uid != os.geteuid()
        or not _path_is_absolute_normal(account_home)
        or not stat.S_ISDIR(account_home_metadata.st_mode)
        or stat.S_ISLNK(account_home_metadata.st_mode)
        or account_home_metadata.st_uid != anchor_metadata.st_uid
        or stat.S_IMODE(account_home_metadata.st_mode) & 0o022
    ):
        _raise_active_or_indeterminate()
    return (
        account_home
        / NORMALIZATION_RECOVERY_STATE_DIRECTORY
        / NORMALIZATION_RECOVERY_JOURNAL_FILENAME
    )


def _path_is_absolute_normal(path: Path) -> bool:
    raw = str(path)
    return bool(
        raw
        and "\x00" not in raw
        and not raw.startswith("~")
        and path.is_absolute()
        and os.path.normpath(raw) == raw
        and ".." not in path.parts
        and path != Path("/")
    )


def _same_directory_identity(left: os.stat_result, right: os.stat_result) -> bool:
    return (
        stat.S_ISDIR(left.st_mode)
        and stat.S_ISDIR(right.st_mode)
        and not stat.S_ISLNK(left.st_mode)
        and not stat.S_ISLNK(right.st_mode)
        and (left.st_dev, left.st_ino, left.st_uid, left.st_gid, left.st_mode)
        == (right.st_dev, right.st_ino, right.st_uid, right.st_gid, right.st_mode)
    )


def _raise_active_or_indeterminate() -> None:
    raise MemorialRecoveryInterlockError(
        "api_baseline_normalization_recovery_active_or_indeterminate"
    )


def _revalidate_absence_from_root(
    *,
    selected: Path,
    opened_components: list[tuple[str, os.stat_result]],
    missing_component_index: int | None,
    expected_root: os.stat_result,
) -> None:
    """Re-walk the canonical pathname before accepting an absence proof."""
    directory_flags = os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptors: list[int] = []
    try:
        try:
            current = os.open("/", directory_flags)
        except OSError:
            _raise_active_or_indeterminate()
        descriptors.append(current)
        if not _same_directory_identity(expected_root, os.fstat(current)):
            _raise_active_or_indeterminate()
        parent_parts = selected.parent.parts[1:]
        for index, component in enumerate(parent_parts):
            if index == missing_component_index:
                try:
                    os.stat(component, dir_fd=current, follow_symlinks=False)
                except FileNotFoundError:
                    return
                except OSError:
                    _raise_active_or_indeterminate()
                _raise_active_or_indeterminate()
            try:
                path_metadata = os.stat(
                    component,
                    dir_fd=current,
                    follow_symlinks=False,
                )
                child = os.open(component, directory_flags, dir_fd=current)
            except OSError:
                _raise_active_or_indeterminate()
            descriptors.append(child)
            opened_metadata = os.fstat(child)
            if (
                index >= len(opened_components)
                or opened_components[index][0] != component
                or not _same_directory_identity(path_metadata, opened_metadata)
                or not _same_directory_identity(
                    opened_components[index][1], opened_metadata
                )
            ):
                _raise_active_or_indeterminate()
            current = child
        if missing_component_index is not None:
            _raise_active_or_indeterminate()
        try:
            os.stat(selected.name, dir_fd=current, follow_symlinks=False)
        except FileNotFoundError:
            return
        except OSError:
            _raise_active_or_indeterminate()
        _raise_active_or_indeterminate()
    finally:
        for descriptor in reversed(descriptors):
            try:
                os.close(descriptor)
            except OSError:
                pass


def require_normalization_recovery_absent(path: Path | None = None) -> None:
    """Prove the private normalization journal is absent, or fail closed.

    The walk starts from an already-open root directory and opens every
    descendant with ``O_NOFOLLOW``.  The final state directory must be private
    and owned by this process.  The journal itself is deliberately not read or
    parsed: any filesystem entry with its canonical name is active recovery
    state and must remain byte-for-byte untouched for the normalizer.
    """
    selected = path
    if (
        not isinstance(selected, Path)
        or not _path_is_absolute_normal(selected)
        or selected.name != NORMALIZATION_RECOVERY_JOURNAL_FILENAME
        or selected.parent.name != NORMALIZATION_RECOVERY_STATE_DIRECTORY
    ):
        _raise_active_or_indeterminate()
    required_flags = ("O_CLOEXEC", "O_DIRECTORY", "O_NOFOLLOW")
    if any(not hasattr(os, name) for name in required_flags):
        _raise_active_or_indeterminate()
    if os.open not in os.supports_dir_fd or os.stat not in os.supports_dir_fd:
        _raise_active_or_indeterminate()

    directory_flags = os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptors: list[int] = []
    opened_components: list[tuple[str, os.stat_result]] = []
    try:
        try:
            current = os.open("/", directory_flags)
        except OSError:
            _raise_active_or_indeterminate()
        descriptors.append(current)
        current_metadata = os.fstat(current)
        if not stat.S_ISDIR(current_metadata.st_mode):
            _raise_active_or_indeterminate()
        root_metadata = current_metadata

        parent_parts = selected.parent.parts[1:]
        for index, component in enumerate(parent_parts):
            try:
                path_metadata = os.stat(
                    component,
                    dir_fd=current,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                _revalidate_absence_from_root(
                    selected=selected,
                    opened_components=opened_components,
                    missing_component_index=index,
                    expected_root=root_metadata,
                )
                return
            except OSError:
                _raise_active_or_indeterminate()
            try:
                child = os.open(component, directory_flags, dir_fd=current)
            except OSError:
                _raise_active_or_indeterminate()
            descriptors.append(child)
            opened_metadata = os.fstat(child)
            if not _same_directory_identity(path_metadata, opened_metadata):
                _raise_active_or_indeterminate()
            opened_components.append((component, opened_metadata))
            if index == len(parent_parts) - 2 and (
                opened_metadata.st_uid != os.geteuid()
                or stat.S_IMODE(opened_metadata.st_mode) & 0o022
            ):
                _raise_active_or_indeterminate()
            if index == len(parent_parts) - 1 and (
                opened_metadata.st_uid != os.geteuid()
                or stat.S_IMODE(opened_metadata.st_mode) != 0o700
            ):
                _raise_active_or_indeterminate()
            current = child

        try:
            os.stat(
                selected.name,
                dir_fd=current,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            final_directory_metadata = os.fstat(current)
            final_path_metadata = os.stat(
                selected.parent.name,
                dir_fd=descriptors[-2],
                follow_symlinks=False,
            )
            if not _same_directory_identity(
                final_directory_metadata, final_path_metadata
            ):
                _raise_active_or_indeterminate()
            _revalidate_absence_from_root(
                selected=selected,
                opened_components=opened_components,
                missing_component_index=None,
                expected_root=root_metadata,
            )
            return
        except OSError:
            _raise_active_or_indeterminate()
        _raise_active_or_indeterminate()
    finally:
        for descriptor in reversed(descriptors):
            try:
                os.close(descriptor)
            except OSError:
                pass
