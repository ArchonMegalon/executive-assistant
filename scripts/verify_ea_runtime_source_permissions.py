#!/usr/bin/env python3
"""Verify that bind-mounted EA source trees are readable by the runtime UID.

The production compose topology overlays ``ea/app`` and ``scripts`` onto the
application image, and operator services mount the release root at ``/app``.
Git records a regular source file as ``100644`` but does not preserve its group
and other read bits separately, nor checkout directory modes, so a host-side
``0600`` file or ``0700`` source ancestor is invisible to the clean-worktree
release check and can break every freshly restarted runtime.

This verifier reuses the descriptor-relative, no-follow bind-source guard.  It
does not read source contents and emits only bounded, secret-free evidence.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat

try:
    from .memorial_bind_source_guard import (
        BindSourceGuardError,
        EXPECTED_USER,
        validate_memorial_bind_sources,
    )
except ImportError:
    from memorial_bind_source_guard import (
        BindSourceGuardError,
        EXPECTED_USER,
        validate_memorial_bind_sources,
    )


ROOT = Path(__file__).resolve().parents[1]
SERVICE = "ea-runtime-source"
CONTRACT_NAME = "ea.runtime_source_permissions.v5"
RUNTIME_MOUNT_DIRECTORIES = (".", "ea")
DEFAULT_SOURCE_BINDINGS = (
    ("ea/app", "/app/app"),
    ("scripts", "/app/scripts"),
    (
        "docker-compose.whatsapp-web-session.yml",
        "/app/docker-compose.whatsapp-web-session.yml",
    ),
    (".codex-design", "/app/.codex-design"),
    (".codex-studio", "/app/.codex-studio"),
)


def repair_runtime_source_tree_permissions(source: Path) -> int:
    """Normalize public source modes without following links or reading files."""

    resolved_source = Path(os.path.abspath(os.fspath(source.expanduser())))
    source_metadata = resolved_source.lstat()
    if stat.S_ISLNK(source_metadata.st_mode):
        raise BindSourceGuardError("bind_source_symlink_forbidden")
    if stat.S_ISREG(source_metadata.st_mode):
        current_mode = stat.S_IMODE(source_metadata.st_mode)
        desired_mode = (current_mode | 0o444) & ~0o022
        if desired_mode == current_mode:
            return 0
        resolved_source.chmod(desired_mode, follow_symlinks=False)
        return 1
    if not stat.S_ISDIR(source_metadata.st_mode):
        raise BindSourceGuardError("bind_source_type_invalid")
    repaired = 0
    for current_root, directory_names, file_names in os.walk(
        resolved_source,
        topdown=True,
        followlinks=False,
    ):
        current = Path(current_root)
        entries = [(current, True)]
        entries.extend((current / name, True) for name in directory_names)
        entries.extend((current / name, False) for name in file_names)
        for entry, directory in entries:
            metadata = entry.lstat()
            if stat.S_ISLNK(metadata.st_mode):
                raise BindSourceGuardError("bind_source_symlink_forbidden")
            if directory and not stat.S_ISDIR(metadata.st_mode):
                raise BindSourceGuardError("bind_source_type_invalid")
            if not directory and not stat.S_ISREG(metadata.st_mode):
                raise BindSourceGuardError("bind_source_type_invalid")
            current_mode = stat.S_IMODE(metadata.st_mode)
            desired_mode = (
                (current_mode | 0o555) & ~0o022
                if directory
                else (current_mode | 0o444) & ~0o022
            )
            if desired_mode == current_mode:
                continue
            entry.chmod(desired_mode, follow_symlinks=False)
            repaired += 1
    return repaired


def _runtime_identity_bits(metadata: os.stat_result) -> int:
    uid_text, gid_text = EXPECTED_USER.split(":", 1)
    uid = int(uid_text)
    gid = int(gid_text)
    mode = stat.S_IMODE(metadata.st_mode)
    if metadata.st_uid == uid:
        return (mode >> 6) & 0o7
    if metadata.st_gid == gid:
        return (mode >> 3) & 0o7
    return mode & 0o7


def verify_runtime_mount_root(root: Path) -> None:
    """Require the whole-worktree /app mount to be readable and searchable."""

    metadata = root.lstat()
    if stat.S_ISLNK(metadata.st_mode):
        raise BindSourceGuardError("bind_source_symlink_forbidden")
    if not stat.S_ISDIR(metadata.st_mode):
        raise BindSourceGuardError("bind_source_type_invalid")
    if _runtime_identity_bits(metadata) & 0o5 != 0o5:
        raise BindSourceGuardError("bind_source_directory_not_readable_searchable")


def repair_runtime_mount_root_permissions(root: Path) -> int:
    """Normalize only the mount root, never private files below it."""

    metadata = root.lstat()
    if stat.S_ISLNK(metadata.st_mode):
        raise BindSourceGuardError("bind_source_symlink_forbidden")
    if not stat.S_ISDIR(metadata.st_mode):
        raise BindSourceGuardError("bind_source_type_invalid")
    current_mode = stat.S_IMODE(metadata.st_mode)
    desired_mode = (current_mode | 0o555) & ~0o022
    if desired_mode == current_mode:
        return 0
    root.chmod(desired_mode, follow_symlinks=False)
    return 1


def _source_bindings(
    root: Path,
    *,
    source: Path | None = None,
) -> list[tuple[str, Path, str]]:
    if source is not None:
        resolved_source = Path(os.path.abspath(os.fspath(source.expanduser())))
        try:
            source_label = resolved_source.relative_to(root).as_posix()
        except ValueError:
            source_label = "explicit_source"
        return [(source_label, resolved_source, "/app/source")]
    return [
        (
            source_label,
            Path(os.path.abspath(os.fspath((root / source_label).expanduser()))),
            target,
        )
        for source_label, target in DEFAULT_SOURCE_BINDINGS
    ]


def repair_runtime_source_permissions(
    root: Path = ROOT,
    *,
    source: Path | None = None,
) -> int:
    resolved_root = Path(os.path.abspath(os.fspath(root.expanduser())))
    repaired = (
        sum(
            repair_runtime_mount_root_permissions(resolved_root / relative_path)
            for relative_path in RUNTIME_MOUNT_DIRECTORIES
        )
        if source is None
        else 0
    )
    return repaired + sum(
        repair_runtime_source_tree_permissions(source_path)
        for _label, source_path, _target in _source_bindings(
            resolved_root,
            source=source,
        )
    )


def verify_runtime_source_tree(
    root: Path = ROOT,
    *,
    source: Path | None = None,
) -> dict[str, object]:
    resolved_root = Path(os.path.abspath(os.fspath(root.expanduser())))
    if source is None:
        for relative_path in RUNTIME_MOUNT_DIRECTORIES:
            verify_runtime_mount_root(resolved_root / relative_path)
    bindings = _source_bindings(resolved_root, source=source)
    rendered = {
        "services": {
            SERVICE: {
                "user": EXPECTED_USER,
                "group_add": [],
                "volumes": [
                    {
                        "type": "bind",
                        "source": str(source_path),
                        "target": target,
                        "read_only": True,
                    }
                    for _label, source_path, target in bindings
                ],
            }
        }
    }
    receipt = validate_memorial_bind_sources(
        rendered,
        service=SERVICE,
        release_root=resolved_root,
    )
    return {
        "contract_name": CONTRACT_NAME,
        "status": "pass",
        "runtime_user": EXPECTED_USER,
        "runtime_mount_directories": (
            list(RUNTIME_MOUNT_DIRECTORIES) if source is None else []
        ),
        "runtime_mount_root_verified": source is None,
        "source_trees": [label for label, _source, _target in bindings],
        "release_entries_scanned": int(receipt["release_entries_scanned"]),
        "release_files_scanned": int(receipt["release_files_scanned"]),
        "release_directories_scanned": int(receipt["release_directories_scanned"]),
        "snapshot_sha256": str(receipt["snapshot_sha256"]),
        "file_contents_read": False,
        "secrets_included": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Fail closed when bind-mounted EA application or script source "
            "is unreadable by UID 10001."
        )
    )
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--source", type=Path)
    parser.add_argument(
        "--repair",
        action="store_true",
        help=(
            "Normalize public runtime mount ancestors, ea/app, scripts, and "
            "required compose source modes before fail-closed verification. "
            "Private files outside those exact paths are never changed."
        ),
    )
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    try:
        resolved_root = Path(os.path.abspath(os.fspath(args.root.expanduser())))
        repaired_entries = (
            repair_runtime_source_permissions(
                resolved_root,
                source=args.source,
            )
            if args.repair
            else 0
        )
        payload = verify_runtime_source_tree(
            resolved_root,
            source=args.source,
        )
        payload["repaired_entries"] = repaired_entries
    except BindSourceGuardError as exc:
        payload = {
            "contract_name": CONTRACT_NAME,
            "status": "fail",
            "reason": str(exc),
            "runtime_user": EXPECTED_USER,
            "source_trees": [
                label
                for label, _source, _target in _source_bindings(
                    resolved_root,
                    source=args.source,
                )
            ],
            "file_contents_read": False,
            "secrets_included": False,
            "repair_requested": bool(args.repair),
        }
        print(json.dumps(payload, indent=2 if args.pretty else None, sort_keys=True))
        return 1

    print(json.dumps(payload, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
