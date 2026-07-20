#!/usr/bin/env python3
"""Secret-safe Gemini OAuth credential snapshot and candidate provisioning.

This module deliberately performs no Docker, network, provider, or live-runtime
operation.  The governed deploy lane is responsible for importing
``snapshot_source_credentials`` and streaming the snapshot to this file's
``install`` CLI over stdin.

The deploy lane must invoke the CLI from the immutable candidate image ID with
network disabled, a read-only root filesystem, all capabilities dropped,
``no-new-privileges``, a bounded PID limit, and exactly one read/write mount for
the Memorial runtime state.  That invocation is a live mutation and therefore
must remain inside the release lease with authority revalidated immediately
before it.  This helper grants no release or mutation authority.

Credential bytes are accepted only from stdin by the install CLI.  They are
never accepted from argv, environment variables, or a source-file option.

The helper holds ``.oauth_creds.lock`` across validation, replace, verification,
and rollback.  The runtime refresh implementation must honor the same advisory
lock, and the deploy lane must stop old runtime versions that do not honor it.
"""

from __future__ import annotations

import errno
import fcntl
import hashlib
import json
import math
import os
import secrets
import stat
import sys
from dataclasses import dataclass
from typing import BinaryIO, TextIO


CONTRACT = "ea.memorial_gemini_oauth_provision.v1"
TARGET_UID = 10001
MAX_CREDENTIAL_BYTES = 128 * 1024
MAX_JSON_DEPTH = 32
MAX_JSON_NODES = 4096
TARGET_RELATIVE_PARTS = ("state", "gemini-oauth", "oauth_creds.json")
LOCK_FILE_NAME = ".oauth_creds.lock"
CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
MIN_EXPIRY_EPOCH_MS = 946_684_800_000  # 2000-01-01T00:00:00Z
MAX_EXPIRY_EPOCH_MS = 4_102_444_800_000  # 2100-01-01T00:00:00Z

_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_NONBLOCK = getattr(os, "O_NONBLOCK", 0)
_PATH = getattr(os, "O_PATH", 0)
_DIR_OPEN_FLAGS = os.O_RDONLY | _CLOEXEC | _NOFOLLOW | _DIRECTORY
_FILE_READ_FLAGS = os.O_RDONLY | _CLOEXEC | _NOFOLLOW | _NONBLOCK
_PATH_OPEN_FLAGS = _PATH | _CLOEXEC | _NOFOLLOW
_REQUIRED_TEXT_FIELDS = ("refresh_token", "token_type", "scope")
_REQUIRED_LINUX_FLAGS = ("O_NOFOLLOW", "O_DIRECTORY", "O_NONBLOCK", "O_PATH")


class ProvisioningError(RuntimeError):
    """A fixed, secret-free provisioning failure."""

    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class CredentialMetadata:
    """The only non-secret information exposed by a source snapshot."""

    schema: str
    status: str
    sha256: str
    size_bytes: int
    uid: int
    gid: int
    mode: str
    device: int
    inode: int

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "status": self.status,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "uid": self.uid,
            "gid": self.gid,
            "mode": self.mode,
            "device": self.device,
            "inode": self.inode,
        }


@dataclass(frozen=True, slots=True)
class _ExistingTargetSnapshot:
    device: int
    inode: int
    sha256: str
    size_bytes: int
    uid: int
    gid: int
    mode: int

    @property
    def inode_binding(self) -> tuple[int, int]:
        return (self.device, self.inode)


class CredentialSnapshot:
    """A bounded in-memory secret with a redacted representation.

    Callers can stream the canonical bytes directly into a subprocess stdin,
    but there is intentionally no bytes-valued property and the representation
    contains metadata only.  ``close`` best-effort overwrites this object's
    mutable backing buffer only; Python parser strings and immutable temporary
    byte objects cannot be comprehensively zeroized.
    """

    __slots__ = ("_secret", "metadata", "_closed")

    def __init__(self, canonical_bytes: bytes, metadata: CredentialMetadata) -> None:
        self._secret = bytearray(canonical_bytes)
        self.metadata = metadata
        self._closed = False

    def __enter__(self) -> CredentialSnapshot:
        if self._closed:
            raise ProvisioningError("oauth_snapshot_closed")
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"CredentialSnapshot(metadata={self.metadata!r}, closed={self._closed})"

    def write_secret_to(self, stream: BinaryIO) -> None:
        if self._closed:
            raise ProvisioningError("oauth_snapshot_closed")
        view = memoryview(self._secret)
        offset = 0
        try:
            while offset < len(view):
                written = stream.write(view[offset:])
                if (
                    type(written) is not int
                    or written <= 0
                    or written > len(view) - offset
                ):
                    raise OSError
                offset += written
        except Exception as exc:  # pragma: no cover - stream-specific behavior
            raise ProvisioningError("oauth_snapshot_stream_failed") from exc

    def close(self) -> None:
        if self._closed:
            return
        for index in range(len(self._secret)):
            self._secret[index] = 0
        try:
            self._secret.clear()
        except BufferError:
            # A trusted BinaryIO implementation may retain an exported view.
            # The backing bytes are already overwritten even when resizing is
            # temporarily prohibited by that view.
            pass
        self._closed = True


class _DuplicateKey(ValueError):
    pass


class _NonFiniteNumber(ValueError):
    pass


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey
        result[key] = value
    return result


def _reject_nonfinite_constant(_value: str) -> object:
    raise _NonFiniteNumber


def _parse_finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise _NonFiniteNumber
    return parsed


def _json_structure_is_bounded(value: object) -> bool:
    stack: list[tuple[object, int]] = [(value, 1)]
    nodes = 0
    while stack:
        current, depth = stack.pop()
        nodes += 1
        if depth > MAX_JSON_DEPTH or nodes > MAX_JSON_NODES:
            return False
        if isinstance(current, dict):
            stack.extend((child, depth + 1) for child in current.values())
        elif isinstance(current, list):
            stack.extend((child, depth + 1) for child in current)
    return True


def _try_canonicalize_credentials(raw: bytes) -> tuple[bytes | None, str | None]:
    """Return canonical credentials or a fixed code without propagating parsers.

    In particular, JSON/Unicode exception objects retain the original document.
    They are consumed inside this frame and are never attached to the public
    ``ProvisioningError`` raised by the wrapper.
    """

    if not raw or len(raw) > MAX_CREDENTIAL_BYTES:
        return None, "oauth_credentials_size_invalid"
    text: str | None = None
    payload: object | None = None
    parse_error: str | None = None
    try:
        text = raw.decode("utf-8")
        payload = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite_constant,
            parse_float=_parse_finite_float,
        )
    except _DuplicateKey:
        parse_error = "oauth_credentials_duplicate_key"
    except _NonFiniteNumber:
        parse_error = "oauth_credentials_nonfinite"
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError):
        parse_error = "oauth_credentials_json_invalid"
    if parse_error is not None:
        return None, parse_error

    if not isinstance(payload, dict):
        return None, "oauth_credentials_object_required"
    if not _json_structure_is_bounded(payload):
        return None, "oauth_credentials_json_invalid"
    for field in _REQUIRED_TEXT_FIELDS:
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            return None, f"oauth_credentials_{field}_invalid"
    if payload["token_type"] != "Bearer":
        return None, "oauth_credentials_token_type_invalid"
    if CLOUD_PLATFORM_SCOPE not in payload["scope"].split():
        return None, "oauth_credentials_scope_invalid"
    if "access_token" in payload:
        access_token = payload["access_token"]
        if not isinstance(access_token, str) or not access_token.strip():
            return None, "oauth_credentials_access_token_invalid"
    if "expiry_date" in payload:
        expiry = payload["expiry_date"]
        if (
            isinstance(expiry, bool)
            or not isinstance(expiry, int)
            or expiry < MIN_EXPIRY_EPOCH_MS
            or expiry > MAX_EXPIRY_EPOCH_MS
        ):
            return None, "oauth_credentials_expiry_invalid"

    canonical: bytes | None = None
    canonical_error = False
    try:
        canonical = (
            json.dumps(
                payload,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            + b"\n"
        )
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError, OverflowError):
        canonical_error = True
    if canonical_error or canonical is None:
        return None, "oauth_credentials_json_invalid"
    if len(canonical) > MAX_CREDENTIAL_BYTES:
        return None, "oauth_credentials_size_invalid"
    return canonical, None


def _canonicalize_credentials(raw: bytes) -> bytes:
    canonical, error = _try_canonicalize_credentials(raw)
    del raw
    if error is not None or canonical is None:
        raise ProvisioningError(error or "oauth_credentials_json_invalid")
    return canonical


def _require_linux_file_primitives() -> None:
    for name in _REQUIRED_LINUX_FLAGS:
        value = getattr(os, name, None)
        if not isinstance(value, int) or value <= 0:
            raise ProvisioningError("oauth_platform_unsupported")


def _absolute_path_parts(path: str | os.PathLike[str], *, code: str) -> tuple[str, ...]:
    try:
        raw = os.fspath(path)
    except TypeError as exc:
        raise ProvisioningError(code) from exc
    if (
        not isinstance(raw, str)
        or not raw.startswith("/")
        or raw.startswith("//")
        or "\x00" in raw
    ):
        raise ProvisioningError(code)
    if raw != os.path.normpath(raw):
        raise ProvisioningError(code)
    parts = tuple(part for part in raw.split("/") if part)
    if any(part in {".", ".."} for part in parts):
        raise ProvisioningError(code)
    return parts


def _stat_binding(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_uid,
        value.st_gid,
        stat.S_IMODE(value.st_mode),
        value.st_nlink,
    )


def _stable_file_binding(value: os.stat_result) -> tuple[int, ...]:
    return (
        *_stat_binding(value),
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _validate_trusted_directory(
    value: os.stat_result,
    *,
    expected_uid: int,
    exact_mode: int | None = None,
    code: str,
) -> None:
    mode = stat.S_IMODE(value.st_mode)
    if not stat.S_ISDIR(value.st_mode):
        raise ProvisioningError(code)
    if value.st_uid not in {0, expected_uid}:
        raise ProvisioningError(code)
    if mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise ProvisioningError(code)
    if exact_mode is not None and mode != exact_mode:
        raise ProvisioningError(code)


def _open_directory_chain(
    parts: tuple[str, ...],
    *,
    expected_uid: int,
    trusted_depth: int,
    code: str,
) -> int:
    try:
        current = os.open("/", _DIR_OPEN_FLAGS)
    except OSError as exc:  # pragma: no cover - a viable Unix host has /
        raise ProvisioningError(code) from exc
    try:
        if trusted_depth == 0:
            _validate_trusted_directory(os.fstat(current), expected_uid=expected_uid, code=code)
        for depth, part in enumerate(parts, start=1):
            try:
                next_fd = os.open(part, _DIR_OPEN_FLAGS, dir_fd=current)
            except OSError as exc:
                raise ProvisioningError(code) from exc
            try:
                value = os.fstat(next_fd)
                if depth >= trusted_depth:
                    _validate_trusted_directory(value, expected_uid=expected_uid, code=code)
            except Exception:
                os.close(next_fd)
                raise
            os.close(current)
            current = next_fd
        return current
    except Exception:
        os.close(current)
        raise


def _open_path_nofollow(parent_fd: int, name: str, *, code: str) -> tuple[int, os.stat_result]:
    try:
        fd = os.open(name, _PATH_OPEN_FLAGS, dir_fd=parent_fd)
        value = os.fstat(fd)
    except OSError as exc:
        if "fd" in locals():
            os.close(fd)
        raise ProvisioningError(code) from exc
    return fd, value


def _open_bound_regular_reader(
    path_fd: int,
    expected: os.stat_result,
    *,
    code: str,
) -> int:
    """Open the already-vetted O_PATH inode without reopening its pathname."""

    if not stat.S_ISREG(expected.st_mode):
        raise ProvisioningError(code)
    try:
        fd = os.open(f"/proc/self/fd/{path_fd}", os.O_RDONLY | _CLOEXEC | _NONBLOCK)
        actual = os.fstat(fd)
    except OSError as exc:
        if "fd" in locals():
            os.close(fd)
        raise ProvisioningError(code) from exc
    if _stable_file_binding(actual) != _stable_file_binding(expected):
        os.close(fd)
        raise ProvisioningError(code)
    return fd


def _open_bound_regular_writer(
    path_fd: int,
    expected: os.stat_result,
    *,
    code: str,
) -> int:
    if not stat.S_ISREG(expected.st_mode):
        raise ProvisioningError(code)
    try:
        fd = os.open(f"/proc/self/fd/{path_fd}", os.O_RDWR | _CLOEXEC | _NONBLOCK)
        actual = os.fstat(fd)
    except OSError as exc:
        if "fd" in locals():
            os.close(fd)
        raise ProvisioningError(code) from exc
    if _stable_file_binding(actual) != _stable_file_binding(expected):
        os.close(fd)
        raise ProvisioningError(code)
    return fd


def _validate_lock_file(
    value: os.stat_result,
    *,
    expected_uid: int,
    expected_gid: int,
) -> None:
    if (
        not stat.S_ISREG(value.st_mode)
        or value.st_nlink != 1
        or value.st_uid != expected_uid
        or value.st_gid != expected_gid
        or stat.S_IMODE(value.st_mode) != 0o600
        or value.st_size != 0
    ):
        raise ProvisioningError("oauth_target_lock_unsafe")


def _acquire_runtime_lock(
    parent_fd: int,
    *,
    expected_uid: int,
    expected_gid: int,
) -> int:
    lock_fd = -1
    path_fd = -1
    rebound_fd = -1
    created = False
    binding: tuple[int, int] | None = None
    acquired = False
    try:
        for _attempt in range(16):
            try:
                lock_fd = os.open(
                    LOCK_FILE_NAME,
                    os.O_RDWR
                    | os.O_CREAT
                    | os.O_EXCL
                    | _CLOEXEC
                    | _NOFOLLOW
                    | _NONBLOCK,
                    0o600,
                    dir_fd=parent_fd,
                )
                created = True
                os.fchmod(lock_fd, 0o600)
                before = os.fstat(lock_fd)
                break
            except FileExistsError:
                try:
                    path_fd = os.open(LOCK_FILE_NAME, _PATH_OPEN_FLAGS, dir_fd=parent_fd)
                except FileNotFoundError:
                    continue
                except OSError as exc:
                    raise ProvisioningError("oauth_target_lock_unsafe") from exc
                before = os.fstat(path_fd)
                _validate_lock_file(
                    before,
                    expected_uid=expected_uid,
                    expected_gid=expected_gid,
                )
                lock_fd = _open_bound_regular_writer(
                    path_fd,
                    before,
                    code="oauth_target_lock_unsafe",
                )
                break
            except OSError as exc:
                raise ProvisioningError("oauth_target_lock_unsafe") from exc
        if lock_fd < 0:
            raise ProvisioningError("oauth_target_lock_unsafe")

        value = os.fstat(lock_fd)
        _validate_lock_file(
            value,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
        )
        binding = (value.st_dev, value.st_ino)
        if created:
            os.fsync(lock_fd)
            os.fsync(parent_fd)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EAGAIN}:
                raise ProvisioningError("oauth_target_lock_busy") from None
            raise ProvisioningError("oauth_target_lock_unsafe") from exc

        rebound_fd, rebound = _open_path_nofollow(
            parent_fd,
            LOCK_FILE_NAME,
            code="oauth_target_lock_unsafe",
        )
        _validate_lock_file(
            rebound,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
        )
        if (rebound.st_dev, rebound.st_ino) != binding:
            raise ProvisioningError("oauth_target_lock_unsafe")
        acquired = True
        return lock_fd
    except Exception:
        if lock_fd >= 0:
            os.close(lock_fd)
            lock_fd = -1
        raise
    finally:
        if rebound_fd >= 0:
            os.close(rebound_fd)
        if path_fd >= 0:
            os.close(path_fd)
        if not acquired and lock_fd >= 0:
            os.close(lock_fd)


def _read_fd_once(fd: int, *, code: str) -> bytes:
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        chunks: list[bytes] = []
        remaining = MAX_CREDENTIAL_BYTES + 1
        while remaining:
            chunk = os.read(fd, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
    except OSError as exc:
        raise ProvisioningError(code) from exc
    if not data or len(data) > MAX_CREDENTIAL_BYTES:
        raise ProvisioningError("oauth_credentials_size_invalid")
    return data


def _read_stable_fd(fd: int, *, code: str) -> tuple[bytes, os.stat_result]:
    try:
        before = os.fstat(fd)
    except OSError as exc:
        raise ProvisioningError(code) from exc
    first = _read_fd_once(fd, code=code)
    try:
        middle = os.fstat(fd)
    except OSError as exc:
        raise ProvisioningError(code) from exc
    second = _read_fd_once(fd, code=code)
    try:
        after = os.fstat(fd)
    except OSError as exc:
        raise ProvisioningError(code) from exc
    if (
        first != second
        or _stable_file_binding(before) != _stable_file_binding(middle)
        or _stable_file_binding(middle) != _stable_file_binding(after)
    ):
        raise ProvisioningError(code)
    return first, after


def _validate_source_file(value: os.stat_result, *, expected_uid: int) -> None:
    if not stat.S_ISREG(value.st_mode):
        raise ProvisioningError("oauth_source_file_unsafe")
    if value.st_nlink != 1:
        raise ProvisioningError("oauth_source_file_unsafe")
    if value.st_uid != expected_uid:
        raise ProvisioningError("oauth_source_owner_invalid")
    if stat.S_IMODE(value.st_mode) != 0o600:
        raise ProvisioningError("oauth_source_mode_invalid")
    if value.st_size <= 0 or value.st_size > MAX_CREDENTIAL_BYTES:
        raise ProvisioningError("oauth_credentials_size_invalid")


def snapshot_source_credentials(
    source_path: str | os.PathLike[str],
    *,
    trusted_root: str | os.PathLike[str] = "/",
    expected_uid: int | None = None,
) -> CredentialSnapshot:
    """Return a stable private snapshot without logging or printing its values."""

    _require_linux_file_primitives()
    owner_uid = os.geteuid() if expected_uid is None else expected_uid
    if not isinstance(owner_uid, int) or owner_uid < 0:
        raise ProvisioningError("oauth_source_owner_invalid")
    source_parts = _absolute_path_parts(source_path, code="oauth_source_path_invalid")
    root_parts = _absolute_path_parts(trusted_root, code="oauth_source_trust_root_invalid")
    if len(source_parts) <= len(root_parts) or source_parts[: len(root_parts)] != root_parts:
        raise ProvisioningError("oauth_source_trust_root_invalid")

    parent_parts = source_parts[:-1]
    parent_fd = _open_directory_chain(
        parent_parts,
        expected_uid=owner_uid,
        trusted_depth=len(root_parts),
        code="oauth_source_parent_untrusted",
    )
    path_fd = -1
    file_fd = -1
    try:
        parent_before = os.fstat(parent_fd)
        path_fd, file_before = _open_path_nofollow(
            parent_fd,
            source_parts[-1],
            code="oauth_source_file_unsafe",
        )
        _validate_source_file(file_before, expected_uid=owner_uid)
        file_fd = _open_bound_regular_reader(
            path_fd,
            file_before,
            code="oauth_source_file_unsafe",
        )
        raw, file_after = _read_stable_fd(file_fd, code="oauth_source_unstable")
        _validate_source_file(file_after, expected_uid=owner_uid)
        if _stat_binding(parent_before) != _stat_binding(os.fstat(parent_fd)):
            raise ProvisioningError("oauth_source_unstable")

        rebound_parent = _open_directory_chain(
            parent_parts,
            expected_uid=owner_uid,
            trusted_depth=len(root_parts),
            code="oauth_source_parent_untrusted",
        )
        rebound_path = -1
        rebound_file = -1
        try:
            if _stat_binding(os.fstat(rebound_parent)) != _stat_binding(parent_before):
                raise ProvisioningError("oauth_source_unstable")
            rebound_path, rebound_before = _open_path_nofollow(
                rebound_parent,
                source_parts[-1],
                code="oauth_source_unstable",
            )
            _validate_source_file(rebound_before, expected_uid=owner_uid)
            rebound_file = _open_bound_regular_reader(
                rebound_path,
                rebound_before,
                code="oauth_source_unstable",
            )
            rebound_raw, rebound_stat = _read_stable_fd(rebound_file, code="oauth_source_unstable")
            if (
                _stable_file_binding(rebound_stat) != _stable_file_binding(file_after)
                or rebound_raw != raw
            ):
                raise ProvisioningError("oauth_source_unstable")
        finally:
            if rebound_file >= 0:
                os.close(rebound_file)
            if rebound_path >= 0:
                os.close(rebound_path)
            os.close(rebound_parent)
    except OSError as exc:
        raise ProvisioningError("oauth_source_unstable") from exc
    finally:
        if file_fd >= 0:
            os.close(file_fd)
        if path_fd >= 0:
            os.close(path_fd)
        os.close(parent_fd)

    canonical, canonical_error = _try_canonicalize_credentials(raw)
    del raw
    del rebound_raw
    if canonical_error is not None or canonical is None:
        raise ProvisioningError(canonical_error or "oauth_credentials_json_invalid")
    digest = hashlib.sha256(canonical).hexdigest()
    metadata = CredentialMetadata(
        schema=CONTRACT,
        status="snapshotted",
        sha256=digest,
        size_bytes=len(canonical),
        uid=file_after.st_uid,
        gid=file_after.st_gid,
        mode=f"{stat.S_IMODE(file_after.st_mode):04o}",
        device=file_after.st_dev,
        inode=file_after.st_ino,
    )
    return CredentialSnapshot(canonical, metadata)


def _validate_runtime_directory(
    fd: int,
    *,
    expected_uid: int,
    expected_gid: int,
    exact_mode: int | None,
    code: str,
) -> os.stat_result:
    try:
        value = os.fstat(fd)
    except OSError as exc:
        raise ProvisioningError(code) from exc
    if value.st_uid != expected_uid:
        raise ProvisioningError(code)
    if value.st_gid != expected_gid:
        raise ProvisioningError(code)
    _validate_trusted_directory(
        value,
        expected_uid=expected_uid,
        exact_mode=exact_mode,
        code=code,
    )
    return value


def _open_or_create_private_directory(
    parent_fd: int,
    name: str,
    *,
    expected_uid: int,
    expected_gid: int,
    exact_mode: int | None,
    code: str,
) -> tuple[int, os.stat_result]:
    created = False
    try:
        fd = os.open(name, _DIR_OPEN_FLAGS, dir_fd=parent_fd)
    except FileNotFoundError:
        try:
            os.mkdir(name, 0o700, dir_fd=parent_fd)
            created = True
            fd = os.open(name, _DIR_OPEN_FLAGS, dir_fd=parent_fd)
        except OSError as exc:
            raise ProvisioningError(code) from exc
    except OSError as exc:
        raise ProvisioningError(code) from exc
    try:
        value = _validate_runtime_directory(
            fd,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
            exact_mode=exact_mode,
            code=code,
        )
        if created:
            os.fsync(fd)
            os.fsync(parent_fd)
        return fd, value
    except Exception:
        os.close(fd)
        raise


def _snapshot_existing_target(
    parent_fd: int,
    *,
    expected_uid: int,
    expected_gid: int,
) -> _ExistingTargetSnapshot | None:
    path_fd = -1
    read_fd = -1
    try:
        path_fd = os.open(TARGET_RELATIVE_PARTS[-1], _PATH_OPEN_FLAGS, dir_fd=parent_fd)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ProvisioningError("oauth_target_file_unsafe") from exc
    try:
        before = os.fstat(path_fd)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_uid != expected_uid
            or before.st_gid != expected_gid
            or stat.S_IMODE(before.st_mode) != 0o600
        ):
            raise ProvisioningError("oauth_target_file_unsafe")
        read_fd = _open_bound_regular_reader(
            path_fd,
            before,
            code="oauth_target_file_unsafe",
        )
        raw, after = _read_stable_fd(read_fd, code="oauth_target_file_unsafe")
        stable = _stable_file_binding(before) == _stable_file_binding(after)
        canonical, canonical_error = _try_canonicalize_credentials(raw)
        digest = hashlib.sha256(raw).hexdigest()
        size_bytes = len(raw)
        del raw
        del canonical
        if not stable or canonical_error is not None:
            raise ProvisioningError("oauth_target_file_unsafe")
        return _ExistingTargetSnapshot(
            device=after.st_dev,
            inode=after.st_ino,
            sha256=digest,
            size_bytes=size_bytes,
            uid=after.st_uid,
            gid=after.st_gid,
            mode=stat.S_IMODE(after.st_mode),
        )
    finally:
        if read_fd >= 0:
            os.close(read_fd)
        if path_fd >= 0:
            os.close(path_fd)


def _write_all(fd: int, payload: bytes) -> None:
    view = memoryview(payload)
    offset = 0
    try:
        while offset < len(view):
            written = os.write(fd, view[offset:])
            if written <= 0:
                raise OSError
            offset += written
    except OSError as exc:
        raise ProvisioningError("oauth_target_write_failed") from exc


def _unlink_if_same_inode(parent_fd: int, name: str, binding: tuple[int, int]) -> bool:
    path_fd = -1
    try:
        path_fd = os.open(name, _PATH_OPEN_FLAGS, dir_fd=parent_fd)
        value = os.fstat(path_fd)
        if (value.st_dev, value.st_ino) != binding:
            return False
        os.unlink(name, dir_fd=parent_fd)
        os.fsync(parent_fd)
        return True
    except FileNotFoundError:
        return True
    except OSError:
        return False
    finally:
        if path_fd >= 0:
            os.close(path_fd)


def _current_target_binding(parent_fd: int, *, code: str) -> tuple[int, int] | None:
    path_fd = -1
    try:
        path_fd = os.open(TARGET_RELATIVE_PARTS[-1], _PATH_OPEN_FLAGS, dir_fd=parent_fd)
        value = os.fstat(path_fd)
        return (value.st_dev, value.st_ino)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ProvisioningError(code) from exc
    finally:
        if path_fd >= 0:
            os.close(path_fd)


def _create_existing_target_backup(
    parent_fd: int,
    snapshot: _ExistingTargetSnapshot,
) -> str:
    backup_name = ""
    for _attempt in range(16):
        candidate = f".oauth-creds.rollback-{secrets.token_hex(16)}"
        try:
            os.link(
                TARGET_RELATIVE_PARTS[-1],
                candidate,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
                follow_symlinks=False,
            )
            backup_name = candidate
            break
        except FileExistsError:
            continue
        except OSError as exc:
            raise ProvisioningError("oauth_target_backup_failed") from exc
    if not backup_name:
        raise ProvisioningError("oauth_target_backup_failed")

    path_fd = -1
    read_fd = -1
    try:
        path_fd, before = _open_path_nofollow(
            parent_fd,
            backup_name,
            code="oauth_target_backup_failed",
        )
        if (
            (before.st_dev, before.st_ino) != snapshot.inode_binding
            or not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 2
            or before.st_uid != snapshot.uid
            or before.st_gid != snapshot.gid
            or stat.S_IMODE(before.st_mode) != snapshot.mode
            or _current_target_binding(parent_fd, code="oauth_target_backup_failed")
            != snapshot.inode_binding
        ):
            raise ProvisioningError("oauth_target_backup_failed")
        read_fd = _open_bound_regular_reader(
            path_fd,
            before,
            code="oauth_target_backup_failed",
        )
        raw, after = _read_stable_fd(read_fd, code="oauth_target_backup_failed")
        matches = (
            (after.st_dev, after.st_ino) == snapshot.inode_binding
            and after.st_nlink == 2
            and len(raw) == snapshot.size_bytes
            and hashlib.sha256(raw).hexdigest() == snapshot.sha256
        )
        del raw
        if not matches:
            raise ProvisioningError("oauth_target_backup_failed")
        os.fsync(parent_fd)
        return backup_name
    except Exception:
        if not _unlink_if_same_inode(parent_fd, backup_name, snapshot.inode_binding):
            raise ProvisioningError("oauth_target_backup_cleanup_failed") from None
        raise
    finally:
        if read_fd >= 0:
            os.close(read_fd)
        if path_fd >= 0:
            os.close(path_fd)


def _verify_restored_target(
    parent_fd: int,
    snapshot: _ExistingTargetSnapshot,
) -> bool:
    try:
        restored = _snapshot_existing_target(
            parent_fd,
            expected_uid=snapshot.uid,
            expected_gid=snapshot.gid,
        )
    except ProvisioningError:
        return False
    return bool(
        restored is not None
        and restored.inode_binding == snapshot.inode_binding
        and restored.sha256 == snapshot.sha256
        and restored.size_bytes == snapshot.size_bytes
        and restored.mode == snapshot.mode
    )


def _rollback_replacement(
    parent_fd: int,
    *,
    installed_binding: tuple[int, int],
    previous: _ExistingTargetSnapshot | None,
    backup_name: str,
) -> tuple[str, str | None]:
    try:
        current = _current_target_binding(parent_fd, code="oauth_target_rollback_failed")
        previous_binding = previous.inode_binding if previous is not None else None
        if current not in {None, installed_binding, previous_binding}:
            if previous is not None and backup_name:
                if not _unlink_if_same_inode(
                    parent_fd,
                    backup_name,
                    previous.inode_binding,
                ):
                    return backup_name, "oauth_target_rollback_failed"
            return "", "oauth_target_rollback_conflict"

        if previous is None:
            if current == installed_binding:
                if not _unlink_if_same_inode(
                    parent_fd,
                    TARGET_RELATIVE_PARTS[-1],
                    installed_binding,
                ):
                    return backup_name, "oauth_target_rollback_failed"
            return backup_name, None

        if current == previous.inode_binding:
            if backup_name and not _unlink_if_same_inode(
                parent_fd,
                backup_name,
                previous.inode_binding,
            ):
                return backup_name, "oauth_target_rollback_failed"
            backup_name = ""
        else:
            if not backup_name:
                return backup_name, "oauth_target_rollback_failed"
            os.replace(
                backup_name,
                TARGET_RELATIVE_PARTS[-1],
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
            )
            backup_name = ""
            os.fsync(parent_fd)
        if not _verify_restored_target(parent_fd, previous):
            return backup_name, "oauth_target_rollback_failed"
        return backup_name, None
    except (OSError, ProvisioningError):
        return backup_name, "oauth_target_rollback_failed"


def _verify_installed_file(
    parent_fd: int,
    *,
    expected_uid: int,
    expected_gid: int,
    expected_inode: tuple[int, int],
    canonical: bytes,
) -> os.stat_result:
    path_fd = -1
    fd = -1
    try:
        path_fd, before = _open_path_nofollow(
            parent_fd,
            TARGET_RELATIVE_PARTS[-1],
            code="oauth_target_verification_failed",
        )
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_uid != expected_uid
            or before.st_gid != expected_gid
            or stat.S_IMODE(before.st_mode) != 0o600
            or (before.st_dev, before.st_ino) != expected_inode
        ):
            raise ProvisioningError("oauth_target_verification_failed")
        fd = _open_bound_regular_reader(
            path_fd,
            before,
            code="oauth_target_verification_failed",
        )
        raw, value = _read_stable_fd(fd, code="oauth_target_verification_failed")
        if (
            not stat.S_ISREG(value.st_mode)
            or value.st_nlink != 1
            or value.st_uid != expected_uid
            or value.st_gid != expected_gid
            or stat.S_IMODE(value.st_mode) != 0o600
            or (value.st_dev, value.st_ino) != expected_inode
            or raw != canonical
            or hashlib.sha256(raw).digest() != hashlib.sha256(canonical).digest()
        ):
            raise ProvisioningError("oauth_target_verification_failed")
        return value
    finally:
        if fd >= 0:
            os.close(fd)
        if path_fd >= 0:
            os.close(path_fd)


def _read_bounded_stdin(stream: BinaryIO) -> bytes:
    try:
        chunks: list[bytes] = []
        total = 0
        while total <= MAX_CREDENTIAL_BYTES:
            requested = min(64 * 1024, MAX_CREDENTIAL_BYTES + 1 - total)
            chunk = stream.read(requested)
            if not isinstance(chunk, bytes):
                raise ProvisioningError("oauth_credentials_stdin_failed")
            if len(chunk) > requested:
                raise ProvisioningError("oauth_credentials_size_invalid")
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        raw = b"".join(chunks)
    except ProvisioningError:
        raise
    except Exception as exc:
        raise ProvisioningError("oauth_credentials_stdin_failed") from exc
    if not raw or len(raw) > MAX_CREDENTIAL_BYTES:
        raise ProvisioningError("oauth_credentials_size_invalid")
    return raw


def install_from_stdin(
    runtime_root: str | os.PathLike[str],
    stream: BinaryIO,
    *,
    expected_uid: int = TARGET_UID,
    expected_gid: int | None = None,
) -> dict[str, object]:
    """Install stdin credentials atomically below a private runtime root."""

    _require_linux_file_primitives()
    owner_gid = expected_uid if expected_gid is None else expected_gid
    if (
        type(expected_uid) is not int
        or type(owner_gid) is not int
        or expected_uid < 0
        or owner_gid < 0
        or os.geteuid() != expected_uid
        or os.getegid() != owner_gid
    ):
        raise ProvisioningError("oauth_provision_uid_invalid")
    stdin_raw = _read_bounded_stdin(stream)
    canonical, canonical_error = _try_canonicalize_credentials(stdin_raw)
    del stdin_raw
    if canonical_error is not None or canonical is None:
        raise ProvisioningError(canonical_error or "oauth_credentials_json_invalid")
    root_parts = _absolute_path_parts(runtime_root, code="oauth_target_path_invalid")
    if not root_parts:
        raise ProvisioningError("oauth_target_path_invalid")

    root_fd = _open_directory_chain(
        root_parts,
        expected_uid=expected_uid,
        trusted_depth=len(root_parts),
        code="oauth_target_root_unsafe",
    )
    state_fd = -1
    parent_fd = -1
    lock_fd = -1
    temp_fd = -1
    temp_name = ""
    temp_binding: tuple[int, int] | None = None
    previous: _ExistingTargetSnapshot | None = None
    backup_name = ""
    replace_attempted = False
    try:
        _validate_runtime_directory(
            root_fd,
            expected_uid=expected_uid,
            expected_gid=owner_gid,
            exact_mode=None,
            code="oauth_target_root_unsafe",
        )
        state_fd, _ = _open_or_create_private_directory(
            root_fd,
            TARGET_RELATIVE_PARTS[0],
            expected_uid=expected_uid,
            expected_gid=owner_gid,
            exact_mode=None,
            code="oauth_target_state_unsafe",
        )
        parent_fd, parent_stat = _open_or_create_private_directory(
            state_fd,
            TARGET_RELATIVE_PARTS[1],
            expected_uid=expected_uid,
            expected_gid=owner_gid,
            exact_mode=0o700,
            code="oauth_target_parent_unsafe",
        )
        lock_fd = _acquire_runtime_lock(
            parent_fd,
            expected_uid=expected_uid,
            expected_gid=owner_gid,
        )
        # Directory link counts legitimately change while the two private
        # descendants are created.  Bind the race check only after the target
        # chain is complete.
        root_stat = os.fstat(root_fd)
        state_stat = os.fstat(state_fd)
        parent_stat = os.fstat(parent_fd)
        previous = _snapshot_existing_target(
            parent_fd,
            expected_uid=expected_uid,
            expected_gid=owner_gid,
        )

        for _attempt in range(16):
            candidate = f".oauth-creds.tmp-{secrets.token_hex(16)}"
            try:
                temp_fd = os.open(
                    candidate,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | _CLOEXEC | _NOFOLLOW,
                    0o600,
                    dir_fd=parent_fd,
                )
                temp_name = candidate
                break
            except FileExistsError:
                continue
            except OSError as exc:
                raise ProvisioningError("oauth_target_temp_create_failed") from exc
        if temp_fd < 0:
            raise ProvisioningError("oauth_target_temp_create_failed")

        os.fchmod(temp_fd, 0o600)
        temp_stat = os.fstat(temp_fd)
        temp_binding = (temp_stat.st_dev, temp_stat.st_ino)
        if (
            not stat.S_ISREG(temp_stat.st_mode)
            or temp_stat.st_nlink != 1
            or temp_stat.st_uid != expected_uid
            or temp_stat.st_gid != owner_gid
            or stat.S_IMODE(temp_stat.st_mode) != 0o600
        ):
            raise ProvisioningError("oauth_target_temp_unsafe")
        _write_all(temp_fd, canonical)
        os.fsync(temp_fd)
        sealed_temp = os.fstat(temp_fd)
        if (
            (sealed_temp.st_dev, sealed_temp.st_ino) != temp_binding
            or sealed_temp.st_size != len(canonical)
            or sealed_temp.st_nlink != 1
            or sealed_temp.st_uid != expected_uid
            or sealed_temp.st_gid != owner_gid
            or stat.S_IMODE(sealed_temp.st_mode) != 0o600
        ):
            raise ProvisioningError("oauth_target_temp_unsafe")
        os.close(temp_fd)
        temp_fd = -1

        if previous is not None:
            backup_name = _create_existing_target_backup(parent_fd, previous)

        replace_attempted = True
        try:
            os.replace(
                temp_name,
                TARGET_RELATIVE_PARTS[-1],
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
            )
            temp_name = ""
            os.fsync(parent_fd)
        except OSError as exc:
            raise ProvisioningError("oauth_target_replace_failed") from exc

        installed = _verify_installed_file(
            parent_fd,
            expected_uid=expected_uid,
            expected_gid=owner_gid,
            expected_inode=temp_binding,
            canonical=canonical,
        )

        rebound_root = _open_directory_chain(
            root_parts,
            expected_uid=expected_uid,
            trusted_depth=len(root_parts),
            code="oauth_target_race_detected",
        )
        rebound_state = -1
        rebound_parent = -1
        try:
            if _stat_binding(os.fstat(rebound_root)) != _stat_binding(root_stat):
                raise ProvisioningError("oauth_target_race_detected")
            rebound_state = os.open(TARGET_RELATIVE_PARTS[0], _DIR_OPEN_FLAGS, dir_fd=rebound_root)
            if _stat_binding(os.fstat(rebound_state)) != _stat_binding(state_stat):
                raise ProvisioningError("oauth_target_race_detected")
            rebound_parent = os.open(TARGET_RELATIVE_PARTS[1], _DIR_OPEN_FLAGS, dir_fd=rebound_state)
            if _stat_binding(os.fstat(rebound_parent)) != _stat_binding(parent_stat):
                raise ProvisioningError("oauth_target_race_detected")
            rebound_installed = _verify_installed_file(
                rebound_parent,
                expected_uid=expected_uid,
                expected_gid=owner_gid,
                expected_inode=temp_binding,
                canonical=canonical,
            )
            if _stable_file_binding(rebound_installed) != _stable_file_binding(installed):
                raise ProvisioningError("oauth_target_race_detected")
        except OSError as exc:
            raise ProvisioningError("oauth_target_race_detected") from exc
        finally:
            if rebound_parent >= 0:
                os.close(rebound_parent)
            if rebound_state >= 0:
                os.close(rebound_state)
            os.close(rebound_root)

        if _current_target_binding(parent_fd, code="oauth_target_race_detected") != temp_binding:
            raise ProvisioningError("oauth_target_race_detected")
        if previous is not None:
            if not backup_name or not _unlink_if_same_inode(
                parent_fd,
                backup_name,
                previous.inode_binding,
            ):
                raise ProvisioningError("oauth_target_backup_cleanup_failed")
            backup_name = ""

        return {
            "schema": CONTRACT,
            "status": "provisioned",
            "sha256": hashlib.sha256(canonical).hexdigest(),
            "size_bytes": len(canonical),
            "uid": installed.st_uid,
            "gid": installed.st_gid,
            "mode": f"{stat.S_IMODE(installed.st_mode):04o}",
        }
    except BaseException as exc:
        if replace_attempted and temp_binding is not None and parent_fd >= 0:
            backup_name, rollback_error = _rollback_replacement(
                parent_fd,
                installed_binding=temp_binding,
                previous=previous,
                backup_name=backup_name,
            )
            if rollback_error is not None:
                raise ProvisioningError(rollback_error) from None
        if isinstance(exc, OSError):
            raise ProvisioningError("oauth_target_io_failed") from None
        raise
    finally:
        if temp_fd >= 0:
            os.close(temp_fd)
        if temp_name and temp_binding is not None and parent_fd >= 0:
            _unlink_if_same_inode(parent_fd, temp_name, temp_binding)
        if backup_name and previous is not None and parent_fd >= 0:
            _unlink_if_same_inode(parent_fd, backup_name, previous.inode_binding)
        if lock_fd >= 0:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            except OSError:
                # Closing the descriptor also releases flock; do not turn a
                # completed, verified transaction into an ambiguous failure.
                pass
            finally:
                os.close(lock_fd)
        if parent_fd >= 0:
            os.close(parent_fd)
        if state_fd >= 0:
            os.close(state_fd)
        os.close(root_fd)


def _safe_cli_arguments(argv: list[str]) -> str:
    if argv == ["--help"] or argv == ["-h"]:
        return ""
    if len(argv) != 3 or argv[0] != "install" or argv[1] != "--runtime-root":
        raise ProvisioningError("oauth_provision_arguments_invalid")
    return argv[2]


def _run_cli(
    argv: list[str],
    *,
    stdin: BinaryIO,
    stdout: TextIO,
    stderr: TextIO,
    expected_uid: int,
    expected_gid: int | None = None,
) -> int:
    try:
        runtime_root = _safe_cli_arguments(argv)
        if not runtime_root:
            stdout.write("usage: provision_memorial_gemini_oauth.py install --runtime-root ABSOLUTE_PATH\n")
            return 0
        receipt = install_from_stdin(
            runtime_root,
            stdin,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
        )
        stdout.write(json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n")
        return 0
    except ProvisioningError as exc:
        stderr.write(exc.code + "\n")
        return 2
    except BaseException:
        stderr.write("oauth_provision_internal_error\n")
        return 2


def main(argv: list[str] | None = None) -> int:
    return _run_cli(
        list(sys.argv[1:] if argv is None else argv),
        stdin=sys.stdin.buffer,
        stdout=sys.stdout,
        stderr=sys.stderr,
        expected_uid=TARGET_UID,
        expected_gid=TARGET_UID,
    )


if __name__ == "__main__":
    raise SystemExit(main())
