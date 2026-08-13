#!/usr/bin/env python3
"""Materialize EA-only Docker env files without product-external operator credentials."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import stat
import sys
from pathlib import Path
from typing import Any


MAX_SOURCE_BYTES = 16 * 1024 * 1024
RUNTIME_DIRECTORY = ".ea-runtime-secrets"
BLOCKED_PREFIX = b"PROPERTYQUARRY_"
OPERATOR_ONLY_PROVIDER_PREFIXES = (b"PANO2VR_",)
REGISTRATION_MAIL_KEYS = frozenset(
    {
        b"EMAILIT_API_KEY",
        b"EA_EMAIL_DEFAULT_FROM",
        b"EA_EMAIL_DEFAULT_NAME",
        b"EA_REGISTRATION_EMAIL_FORCE_FALLBACK",
        b"EA_REGISTRATION_EMAIL_FROM",
        b"EA_REGISTRATION_EMAIL_FROM_FALLBACK",
        b"EA_REGISTRATION_EMAIL_NAME",
        b"EA_REGISTRATION_EMAIL_NAME_FALLBACK",
        b"PROPERTYQUARRY_REGISTRATION_EMAIL_ENABLED",
        b"PROPERTYQUARRY_REGISTRATION_EMAIL_SENDER",
        b"PROPERTYQUARRY_REGISTRATION_EMAIL_SMTP_HOST",
        b"PROPERTYQUARRY_REGISTRATION_EMAIL_SMTP_PORT",
        b"PROPERTYQUARRY_REGISTRATION_EMAIL_SMTP_USERNAME",
        b"PROPERTYQUARRY_REGISTRATION_EMAIL_SMTP_PASSWORD",
        b"PROPERTYQUARRY_REGISTRATION_EMAIL_SMTP_USE_SSL",
        b"PROPERTYQUARRY_REGISTRATION_EMAIL_SMTP_STARTTLS",
    }
)
GOOGLE_IDENTITY_KEYS = frozenset(
    {
        b"PROPERTYQUARRY_GOOGLE_CLIENT_ID",
        b"PROPERTYQUARRY_GOOGLE_CLIENT_SECRET",
        b"PROPERTYQUARRY_GOOGLE_REDIRECT_URI",
        b"PROPERTYQUARRY_GOOGLE_AUTH_URI",
        b"PROPERTYQUARRY_GOOGLE_TOKEN_URI",
    }
)
BLOCKED_EXACT_KEYS = REGISTRATION_MAIL_KEYS | GOOGLE_IDENTITY_KEYS
ENV_ASSIGNMENT = re.compile(
    rb"^[ \t]*(?:export[ \t]+)?([A-Za-z_][A-Za-z0-9_]*)[ \t]*(?==|$|#)"
)


class SanitizerError(RuntimeError):
    """Raised when the runtime projection cannot be prepared safely."""


def _metadata_identity(metadata: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_nlink,
        metadata.st_uid,
        metadata.st_size,
        metadata.st_mtime_ns,
    )


def _require_safe_regular(
    metadata: os.stat_result,
    *,
    label: str,
    allowed_owners: frozenset[int],
    exact_mode: int | None = None,
    owner_only: bool = False,
) -> None:
    if not stat.S_ISREG(metadata.st_mode):
        raise SanitizerError(f"{label} must be a regular file")
    if metadata.st_nlink != 1:
        raise SanitizerError(f"{label} must have exactly one hard link")
    if metadata.st_uid not in allowed_owners:
        raise SanitizerError(f"{label} has an untrusted owner")
    mode = stat.S_IMODE(metadata.st_mode)
    if mode & 0o022:
        raise SanitizerError(f"{label} must not be group- or world-writable")
    if owner_only and mode & 0o077:
        raise SanitizerError(f"{label} must not grant group or world access")
    if exact_mode is not None and mode != exact_mode:
        raise SanitizerError(f"{label} must have mode {exact_mode:04o}")


def _read_source(
    root_fd: int,
    name: str,
    *,
    required: bool,
    allowed_owners: frozenset[int],
) -> bytes | None:
    try:
        entry_before = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
    except FileNotFoundError:
        if required:
            raise SanitizerError(f"required source {name} is missing") from None
        return None
    except OSError as exc:
        raise SanitizerError(f"could not inspect source {name}: errno {exc.errno}") from None

    _require_safe_regular(
        entry_before,
        label=f"source {name}",
        allowed_owners=allowed_owners,
        owner_only=True,
    )
    if entry_before.st_size < 0 or entry_before.st_size > MAX_SOURCE_BYTES:
        raise SanitizerError(f"source {name} exceeds the size limit")

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0)
    if not hasattr(os, "O_NOFOLLOW"):
        raise SanitizerError("this platform cannot safely open env sources")
    flags |= os.O_NOFOLLOW

    try:
        descriptor = os.open(name, flags, dir_fd=root_fd)
    except OSError as exc:
        raise SanitizerError(f"could not safely open source {name}: errno {exc.errno}") from None

    try:
        opened_before = os.fstat(descriptor)
        _require_safe_regular(
            opened_before,
            label=f"source {name}",
            allowed_owners=allowed_owners,
            owner_only=True,
        )
        if _metadata_identity(entry_before) != _metadata_identity(opened_before):
            raise SanitizerError(f"source {name} changed while it was opened")

        chunks: list[bytes] = []
        remaining = MAX_SOURCE_BYTES + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
        if len(content) > MAX_SOURCE_BYTES:
            raise SanitizerError(f"source {name} exceeds the size limit")

        opened_after = os.fstat(descriptor)
        if _metadata_identity(opened_before) != _metadata_identity(opened_after):
            raise SanitizerError(f"source {name} changed while it was read")
        try:
            entry_after = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
        except OSError:
            raise SanitizerError(f"source {name} changed while it was read") from None
        if _metadata_identity(opened_after) != _metadata_identity(entry_after):
            raise SanitizerError(f"source {name} changed while it was read")
        if b"\x00" in content:
            raise SanitizerError(f"source {name} contains a NUL byte")
        return content
    finally:
        os.close(descriptor)


def _assignment_key(line: bytes) -> bytes | None:
    logical_line = line.rstrip(b"\r\n")
    match = ENV_ASSIGNMENT.match(logical_line)
    if match is None:
        return None
    return match.group(1)


def sanitize_env_bytes(content: bytes) -> tuple[bytes, int]:
    """Remove product-external assignments while preserving every other byte."""

    retained: list[bytes] = []
    removed_count = 0
    for line in content.splitlines(keepends=True):
        key = _assignment_key(line)
        if key is not None and (
            key.startswith(BLOCKED_PREFIX)
            or key.startswith(OPERATOR_ONLY_PROVIDER_PREFIXES)
            or key in BLOCKED_EXACT_KEYS
        ):
            removed_count += 1
            continue
        retained.append(line)
    return b"".join(retained), removed_count


def _open_runtime_directory(root_fd: int, *, allowed_owners: frozenset[int]) -> int:
    try:
        metadata = os.stat(RUNTIME_DIRECTORY, dir_fd=root_fd, follow_symlinks=False)
    except FileNotFoundError:
        try:
            os.mkdir(RUNTIME_DIRECTORY, 0o700, dir_fd=root_fd)
        except FileExistsError:
            pass
        except OSError as exc:
            raise SanitizerError(f"could not create runtime directory: errno {exc.errno}") from None
        try:
            metadata = os.stat(RUNTIME_DIRECTORY, dir_fd=root_fd, follow_symlinks=False)
        except OSError as exc:
            raise SanitizerError(f"could not inspect runtime directory: errno {exc.errno}") from None
    except OSError as exc:
        raise SanitizerError(f"could not inspect runtime directory: errno {exc.errno}") from None

    if not stat.S_ISDIR(metadata.st_mode):
        raise SanitizerError("runtime directory must be a real directory, not a symlink or file")
    if metadata.st_uid not in allowed_owners:
        raise SanitizerError("runtime directory has an untrusted owner")
    if not hasattr(os, "O_NOFOLLOW"):
        raise SanitizerError("this platform cannot safely open the runtime directory")

    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(RUNTIME_DIRECTORY, flags, dir_fd=root_fd)
    except OSError as exc:
        raise SanitizerError(f"could not safely open runtime directory: errno {exc.errno}") from None
    opened = os.fstat(descriptor)
    if (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino):
        os.close(descriptor)
        raise SanitizerError("runtime directory changed while it was opened")
    if opened.st_uid not in allowed_owners:
        os.close(descriptor)
        raise SanitizerError("runtime directory has an untrusted owner")
    try:
        os.fchmod(descriptor, 0o700)
    except OSError as exc:
        os.close(descriptor)
        raise SanitizerError(f"could not secure runtime directory: errno {exc.errno}") from None
    if stat.S_IMODE(os.fstat(descriptor).st_mode) != 0o700:
        os.close(descriptor)
        raise SanitizerError("runtime directory mode could not be secured")
    return descriptor


def _destination_metadata(runtime_fd: int, name: str) -> os.stat_result | None:
    try:
        return os.stat(name, dir_fd=runtime_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise SanitizerError(f"could not inspect destination {name}: errno {exc.errno}") from None


def _validate_existing_destination(
    runtime_fd: int,
    name: str,
    *,
    allowed_owners: frozenset[int],
) -> bool:
    metadata = _destination_metadata(runtime_fd, name)
    if metadata is None:
        return False
    _require_safe_regular(
        metadata,
        label=f"destination {name}",
        allowed_owners=allowed_owners,
        exact_mode=0o600,
    )
    return True


def _atomic_write(
    runtime_fd: int,
    name: str,
    content: bytes,
    *,
    allowed_owners: frozenset[int],
) -> None:
    _validate_existing_destination(runtime_fd, name, allowed_owners=allowed_owners)
    temporary_name = f".{name}.tmp-{os.getpid()}-{secrets.token_hex(12)}"
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = -1
    try:
        descriptor = os.open(temporary_name, flags, 0o600, dir_fd=runtime_fd)
        os.fchmod(descriptor, 0o600)
        view = memoryview(content)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise SanitizerError(f"could not write destination {name}")
            view = view[written:]
        os.fsync(descriptor)
        temporary_metadata = os.fstat(descriptor)
        _require_safe_regular(
            temporary_metadata,
            label=f"temporary destination for {name}",
            allowed_owners=frozenset({os.geteuid()}),
            exact_mode=0o600,
        )
        if temporary_metadata.st_size != len(content):
            raise SanitizerError(f"destination {name} was not written completely")
        os.close(descriptor)
        descriptor = -1
        os.replace(
            temporary_name,
            name,
            src_dir_fd=runtime_fd,
            dst_dir_fd=runtime_fd,
        )
        os.fsync(runtime_fd)
        final_metadata = _destination_metadata(runtime_fd, name)
        if final_metadata is None:
            raise SanitizerError(f"destination {name} disappeared after replacement")
        _require_safe_regular(
            final_metadata,
            label=f"destination {name}",
            allowed_owners=allowed_owners,
            exact_mode=0o600,
        )
        if final_metadata.st_size != len(content):
            raise SanitizerError(f"destination {name} has an unexpected size")
    except SanitizerError:
        raise
    except OSError as exc:
        raise SanitizerError(f"could not atomically replace destination {name}: errno {exc.errno}") from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            os.unlink(temporary_name, dir_fd=runtime_fd)
        except FileNotFoundError:
            pass
        except OSError:
            pass


def _remove_optional_destination(
    runtime_fd: int,
    name: str,
    *,
    allowed_owners: frozenset[int],
) -> bool:
    if not _validate_existing_destination(runtime_fd, name, allowed_owners=allowed_owners):
        return False
    try:
        os.unlink(name, dir_fd=runtime_fd)
        os.fsync(runtime_fd)
    except OSError as exc:
        raise SanitizerError(f"could not remove stale destination {name}: errno {exc.errno}") from None
    return True


def _verify_runtime_binding(root_fd: int, runtime_fd: int) -> None:
    try:
        current = os.stat(RUNTIME_DIRECTORY, dir_fd=root_fd, follow_symlinks=False)
    except OSError:
        raise SanitizerError("runtime directory changed during materialization") from None
    opened = os.fstat(runtime_fd)
    if (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
        raise SanitizerError("runtime directory changed during materialization")
    if stat.S_IMODE(opened.st_mode) != 0o700:
        raise SanitizerError("runtime directory mode changed during materialization")


def prepare_runtime_env(root: Path) -> dict[str, Any]:
    root_path = Path(root)
    try:
        root_metadata = os.lstat(root_path)
    except OSError as exc:
        raise SanitizerError(f"could not inspect repository root: errno {exc.errno}") from None
    if not stat.S_ISDIR(root_metadata.st_mode) or stat.S_ISLNK(root_metadata.st_mode):
        raise SanitizerError("repository root must be a real directory")
    if root_metadata.st_mode & 0o002:
        raise SanitizerError("repository root must not be world-writable")
    if not hasattr(os, "O_NOFOLLOW"):
        raise SanitizerError("this platform cannot safely open the repository root")

    root_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    try:
        root_fd = os.open(root_path, root_flags)
    except OSError as exc:
        raise SanitizerError(f"could not safely open repository root: errno {exc.errno}") from None

    try:
        opened_root = os.fstat(root_fd)
        if (opened_root.st_dev, opened_root.st_ino) != (root_metadata.st_dev, root_metadata.st_ino):
            raise SanitizerError("repository root changed while it was opened")
        allowed_owners = frozenset({0, os.geteuid(), opened_root.st_uid})
        primary_source = _read_source(root_fd, ".env", required=True, allowed_owners=allowed_owners)
        local_source = _read_source(root_fd, ".env.local", required=False, allowed_owners=allowed_owners)
        assert primary_source is not None

        runtime_fd = _open_runtime_directory(root_fd, allowed_owners=allowed_owners)
        try:
            outputs: list[dict[str, Any]] = []
            primary_sanitized, primary_removed = sanitize_env_bytes(primary_source)
            _atomic_write(
                runtime_fd,
                "ea_runtime.env",
                primary_sanitized,
                allowed_owners=allowed_owners,
            )
            outputs.append(
                {
                    "source": ".env",
                    "destination": f"{RUNTIME_DIRECTORY}/ea_runtime.env",
                    "byte_count": len(primary_sanitized),
                    "removed_key_count": primary_removed,
                    "sha256": hashlib.sha256(primary_sanitized).hexdigest(),
                }
            )

            stale_local_removed = False
            if local_source is None:
                stale_local_removed = _remove_optional_destination(
                    runtime_fd,
                    "ea_runtime.local.env",
                    allowed_owners=allowed_owners,
                )
            else:
                local_sanitized, local_removed = sanitize_env_bytes(local_source)
                _atomic_write(
                    runtime_fd,
                    "ea_runtime.local.env",
                    local_sanitized,
                    allowed_owners=allowed_owners,
                )
                outputs.append(
                    {
                        "source": ".env.local",
                        "destination": f"{RUNTIME_DIRECTORY}/ea_runtime.local.env",
                        "byte_count": len(local_sanitized),
                        "removed_key_count": local_removed,
                        "sha256": hashlib.sha256(local_sanitized).hexdigest(),
                    }
                )

            _verify_runtime_binding(root_fd, runtime_fd)
            return {
                "status": "prepared",
                "output_count": len(outputs),
                "removed_key_count": sum(int(item["removed_key_count"]) for item in outputs),
                "optional_local_source": "present" if local_source is not None else "absent",
                "stale_local_output_removed": stale_local_removed,
                "outputs": outputs,
            }
        finally:
            os.close(runtime_fd)
    finally:
        os.close(root_fd)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare owner-only EA runtime env files without product-external keys."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="EA repository root (default: the parent of scripts/).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        receipt = prepare_runtime_env(args.root)
    except SanitizerError as exc:
        print(
            json.dumps({"status": "error", "error": str(exc)}, sort_keys=True, separators=(",", ":")),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
