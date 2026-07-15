#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import secrets
import stat
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
RECEIPT_CONTRACT_NAME = "ea.memorial_voicewave_backup_refresh_receipt"
RECEIPT_CONTRACT_VERSION = 3
BLOCKED_REASON = "provider_evidence_lane_unavailable"
MAX_RECEIPT_BYTES = 256 * 1024
ALLOWED_EXISTING_PRIVATE_DIRECTORY_MODES = frozenset({0o700, 0o750})

_SLUG_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
_DIRECTORY_OPEN_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
)
_FILE_OPEN_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)


class _PrivateWriteError(RuntimeError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _safe_slug(value: Any) -> str:
    slug = _safe_text(value).lower()
    if _SLUG_RE.fullmatch(slug) is None:
        raise ValueError("slug_invalid")
    return slug


def _normalized_absolute_path(path: Path | str) -> Path:
    expanded = os.path.expanduser(os.fspath(path))
    return Path(os.path.abspath(os.path.normpath(expanded)))


def _private_profiles_root() -> Path:
    explicit = _safe_text(os.getenv("EA_PRIVATE_MEMORIAL_PROFILE_DIR"))
    if explicit:
        return _normalized_absolute_path(explicit)
    memorial_data_root = _safe_text(os.getenv("EA_MEMORIAL_DATA_ROOT"))
    if memorial_data_root:
        return _normalized_absolute_path(Path(memorial_data_root) / "private_memorial_profiles")
    return _normalized_absolute_path(REPO_ROOT / "memorial_data" / "private_memorial_profiles")


def _voice_config_path(slug: str) -> Path:
    return _private_profiles_root() / _safe_slug(slug) / "tts_voice.json"


def _file_identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_uid,
        value.st_gid,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _open_private_directory(path: Path, *, create: bool) -> int:
    absolute = _normalized_absolute_path(path)
    if absolute == Path(absolute.anchor):
        raise _PrivateWriteError("private_directory_root_forbidden")
    try:
        descriptor = os.open(absolute.anchor, _DIRECTORY_OPEN_FLAGS)
    except OSError:
        raise _PrivateWriteError("directory_chain_untrusted") from None
    try:
        for index, part in enumerate(absolute.parts[1:]):
            created = False
            try:
                next_descriptor = os.open(part, _DIRECTORY_OPEN_FLAGS, dir_fd=descriptor)
            except FileNotFoundError:
                if not create:
                    raise _PrivateWriteError("private_directory_missing") from None
                parent_stat = os.fstat(descriptor)
                if (
                    parent_stat.st_uid != os.geteuid()
                    or stat.S_IMODE(parent_stat.st_mode) & 0o022
                ):
                    raise _PrivateWriteError("private_directory_parent_untrusted") from None
                try:
                    os.mkdir(part, mode=0o700, dir_fd=descriptor)
                    created = True
                except FileExistsError:
                    pass
                except OSError:
                    raise _PrivateWriteError("private_directory_create_failed") from None
                try:
                    next_descriptor = os.open(part, _DIRECTORY_OPEN_FLAGS, dir_fd=descriptor)
                except OSError:
                    raise _PrivateWriteError("directory_chain_untrusted") from None
            except OSError:
                raise _PrivateWriteError("directory_chain_untrusted") from None

            next_stat = os.fstat(next_descriptor)
            if not stat.S_ISDIR(next_stat.st_mode):
                os.close(next_descriptor)
                raise _PrivateWriteError("directory_chain_untrusted")
            if created:
                os.fchmod(next_descriptor, 0o700)
                next_stat = os.fstat(next_descriptor)
                if stat.S_IMODE(next_stat.st_mode) != 0o700:
                    os.close(next_descriptor)
                    raise _PrivateWriteError("created_private_directory_mode_invalid")

            is_final = index == len(absolute.parts[1:]) - 1
            if is_final and not created:
                if next_stat.st_uid != os.geteuid():
                    os.close(next_descriptor)
                    raise _PrivateWriteError("private_directory_owner_invalid")
                if stat.S_IMODE(next_stat.st_mode) not in ALLOWED_EXISTING_PRIVATE_DIRECTORY_MODES:
                    os.close(next_descriptor)
                    raise _PrivateWriteError("private_directory_mode_invalid")

            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _target_stat(directory_fd: int, name: str) -> os.stat_result | None:
    try:
        value = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    except OSError:
        raise _PrivateWriteError("private_target_inspection_failed") from None
    if not stat.S_ISREG(value.st_mode):
        raise _PrivateWriteError("private_target_not_regular")
    if value.st_nlink != 1:
        raise _PrivateWriteError("private_target_link_count_invalid")
    if value.st_uid != os.geteuid():
        raise _PrivateWriteError("private_target_owner_invalid")
    if stat.S_IMODE(value.st_mode) != 0o600:
        raise _PrivateWriteError("private_target_mode_invalid")
    return value


def _assert_target_unchanged(directory_fd: int, name: str, expected: tuple[int, ...] | None) -> None:
    current = _target_stat(directory_fd, name)
    current_identity = _file_identity(current) if current is not None else None
    if current_identity != expected:
        raise _PrivateWriteError("private_target_concurrent_change")


def _open_private_lock(directory_fd: int, target_name: str) -> int:
    lock_name = f".{target_name}.lock"
    flags = os.O_RDWR | os.O_CREAT | _FILE_OPEN_NOFOLLOW
    try:
        descriptor = os.open(lock_name, flags, 0o600, dir_fd=directory_fd)
    except OSError:
        raise _PrivateWriteError("private_lock_open_failed") from None
    try:
        value = os.fstat(descriptor)
        if (
            not stat.S_ISREG(value.st_mode)
            or value.st_nlink != 1
            or value.st_uid != os.geteuid()
            or stat.S_IMODE(value.st_mode) != 0o600
        ):
            raise _PrivateWriteError("private_lock_untrusted")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        current = os.stat(lock_name, dir_fd=directory_fd, follow_symlinks=False)
        if _file_identity(current) != _file_identity(os.fstat(descriptor)):
            raise _PrivateWriteError("private_lock_identity_changed")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _create_unique_temp(directory_fd: int, target_name: str) -> tuple[int, str]:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | _FILE_OPEN_NOFOLLOW
    for _ in range(32):
        name = f".{target_name}.{os.getpid()}.{secrets.token_hex(12)}.tmp"
        try:
            descriptor = os.open(name, flags, 0o600, dir_fd=directory_fd)
        except FileExistsError:
            continue
        except OSError:
            raise _PrivateWriteError("private_temp_create_failed") from None
        os.fchmod(descriptor, 0o600)
        return descriptor, name
    raise _PrivateWriteError("private_temp_name_exhausted")


def _write_all(descriptor: int, content: bytes) -> None:
    remaining = memoryview(content)
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0:
            raise _PrivateWriteError("private_temp_write_failed")
        remaining = remaining[written:]


def _write_private_json(path: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    target = _normalized_absolute_path(path)
    if not target.name or len(target.name.encode("utf-8")) > 180:
        raise _PrivateWriteError("private_target_name_invalid")
    try:
        content = (json.dumps(dict(payload), indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    except (TypeError, ValueError):
        raise _PrivateWriteError("private_receipt_payload_invalid") from None
    if len(content) > MAX_RECEIPT_BYTES:
        raise _PrivateWriteError("private_receipt_too_large")

    directory_fd = _open_private_directory(target.parent, create=True)
    lock_fd = -1
    temp_name = ""
    try:
        lock_fd = _open_private_lock(directory_fd, target.name)
        before = _target_stat(directory_fd, target.name)
        expected_identity = _file_identity(before) if before is not None else None
        temp_fd, temp_name = _create_unique_temp(directory_fd, target.name)
        try:
            _write_all(temp_fd, content)
            os.fsync(temp_fd)
            if stat.S_IMODE(os.fstat(temp_fd).st_mode) != 0o600:
                raise _PrivateWriteError("private_temp_mode_invalid")
        finally:
            os.close(temp_fd)
        _assert_target_unchanged(directory_fd, target.name, expected_identity)
        os.replace(temp_name, target.name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
        temp_name = ""
        os.fsync(directory_fd)
        final = _target_stat(directory_fd, target.name)
        if final is None:
            raise _PrivateWriteError("private_target_missing_after_replace")
        return dict(payload)
    except OSError:
        raise _PrivateWriteError("private_atomic_replace_failed") from None
    finally:
        if temp_name:
            try:
                os.unlink(temp_name, dir_fd=directory_fd)
            except OSError:
                pass
        if lock_fd >= 0:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(lock_fd)
        os.close(directory_fd)


def _blocked_receipt(slug: str, *, receipt_persisted: bool) -> dict[str, Any]:
    return {
        "contract_name": RECEIPT_CONTRACT_NAME,
        "contract_version": RECEIPT_CONTRACT_VERSION,
        "generated_at": _utc_now(),
        "slug": slug,
        "status": "blocked",
        "reason": BLOCKED_REASON,
        "applied_metadata": False,
        "receipt_persisted": receipt_persisted,
        "provider_evidence_lane": {
            "status": "unavailable",
            "independent_verification_required": True,
        },
    }


def run_refresh(
    *,
    slug: str,
    base_url: str,
    prompts: list[str],
    compare_output_dir: Path,
    compare_output_path: Path,
    apply_metadata: bool,
    comparator_path: Path | None = None,
    comparator_sha256: str = "",
) -> dict[str, Any]:
    # The current release has no independently verified provider-evidence lane.
    # All provider, prompt, URL, and metadata inputs are deliberately inert.
    receipt = _blocked_receipt(_safe_slug(slug), receipt_persisted=True)
    try:
        _write_private_json(compare_output_path, receipt)
    except _PrivateWriteError:
        receipt["receipt_persisted"] = False
        receipt["receipt_error"] = "receipt_write_failed"
    return receipt


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Emit the blocked memorial Voicewave provider-evidence receipt for this release."
    )
    parser.add_argument("--slug", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8090")
    parser.add_argument("--prompt", action="append", default=[])
    parser.add_argument(
        "--compare-output-dir",
        type=Path,
        default=REPO_ROOT / ".codex-studio" / "published" / "memorial_voicewave_backup",
    )
    parser.add_argument(
        "--compare-output-path",
        type=Path,
        default=REPO_ROOT
        / ".codex-studio"
        / "published"
        / "memorial_voicewave_backup"
        / "refresh-receipt.generated.json",
    )
    parser.add_argument("--apply-metadata", action="store_true")
    parser.add_argument("--comparator-path", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--comparator-sha256", default="", help=argparse.SUPPRESS)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    result = run_refresh(
        slug=args.slug,
        base_url=args.base_url,
        prompts=list(args.prompt),
        compare_output_dir=args.compare_output_dir,
        compare_output_path=args.compare_output_path,
        apply_metadata=bool(args.apply_metadata),
        comparator_path=args.comparator_path,
        comparator_sha256=args.comparator_sha256,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
