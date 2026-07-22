#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import stat
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / ".codex-design" / "repo" / "DESIGN_MIRROR_MANIFEST.yaml"
MAX_MIRROR_FILE_BYTES = 16 * 1024 * 1024


class ManifestValidationError(ValueError):
    pass


class _UniqueKeySafeLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(
    loader: _UniqueKeySafeLoader,
    node: yaml.nodes.MappingNode,
    deep: bool = False,
) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found an unhashable mapping key",
                key_node.start_mark,
            ) from exc
        if duplicate:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeySafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _load_manifest(path: Path) -> Any:
    return yaml.load(
        path.read_text(encoding="utf-8"),
        Loader=_UniqueKeySafeLoader,
    )


def _file_identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_uid,
        value.st_gid,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _safe_path_stat(
    path: Path,
    *,
    label: str,
    final_kind: str,
    allow_missing: bool,
    allow_final_symlink: bool = False,
) -> os.stat_result | None:
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    parts = absolute.parts[1:]
    if not parts:
        raise ManifestValidationError(f"{label} has no file path")
    for index, part in enumerate(parts):
        current /= part
        final = index == len(parts) - 1
        try:
            current_stat = os.lstat(current)
        except FileNotFoundError:
            if allow_missing:
                return None
            raise ManifestValidationError(f"{label} is missing: {current}") from None
        except OSError as exc:
            raise ManifestValidationError(f"{label} is unreadable: {current}") from exc
        if stat.S_ISLNK(current_stat.st_mode):
            if final and allow_final_symlink:
                return current_stat
            raise ManifestValidationError(
                f"{label} contains a symlink component: {current}"
            )
        if not final and not stat.S_ISDIR(current_stat.st_mode):
            raise ManifestValidationError(
                f"{label} parent is not a directory: {current}"
            )
        if final:
            expected = (
                stat.S_ISREG(current_stat.st_mode)
                if final_kind == "file"
                else stat.S_ISDIR(current_stat.st_mode)
            )
            if not expected:
                raise ManifestValidationError(
                    f"{label} is not a regular {final_kind}: {current}"
                )
            return current_stat
    raise ManifestValidationError(f"{label} could not be inspected: {path}")


def _stable_sha256(path: Path) -> str:
    label = f"mirror file {path}"
    path_stat = _safe_path_stat(
        path,
        label=label,
        final_kind="file",
        allow_missing=False,
    )
    if path_stat is None:
        raise ManifestValidationError(f"{label} is missing")
    if path_stat.st_size > MAX_MIRROR_FILE_BYTES:
        raise ManifestValidationError(
            f"{label} exceeds the {MAX_MIRROR_FILE_BYTES}-byte hash bound"
        )

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ManifestValidationError(f"{label} could not be opened safely") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or _file_identity(before) != _file_identity(
            path_stat
        ):
            raise ManifestValidationError(f"{label} identity changed before hashing")
        if before.st_size > MAX_MIRROR_FILE_BYTES:
            raise ManifestValidationError(
                f"{label} exceeds the {MAX_MIRROR_FILE_BYTES}-byte hash bound"
            )
        digest = hashlib.sha256()
        total = 0
        while True:
            chunk = os.read(
                descriptor,
                min(65536, MAX_MIRROR_FILE_BYTES + 1 - total),
            )
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_MIRROR_FILE_BYTES:
                raise ManifestValidationError(
                    f"{label} exceeds the {MAX_MIRROR_FILE_BYTES}-byte hash bound"
                )
            digest.update(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if _file_identity(before) != _file_identity(after):
        raise ManifestValidationError(f"{label} changed during hashing")
    final_stat = _safe_path_stat(
        path,
        label=label,
        final_kind="file",
        allow_missing=False,
    )
    if final_stat is None or _file_identity(final_stat) != _file_identity(path_stat):
        raise ManifestValidationError(f"{label} path changed during hashing")
    return digest.hexdigest()


def _normalized_local_path(
    root: Path,
    binding: dict[str, Any],
    *,
    binding_key: str | None,
    expected_absolute_local_path: Path | None,
) -> Path:
    key = binding["key"]
    raw = binding.get("local_path")
    if type(raw) is not str or not raw or raw != raw.strip():
        raise ManifestValidationError(f"binding {key} local_path must be nonempty text")
    candidate = Path(raw)
    if candidate.is_absolute():
        expected = (
            expected_absolute_local_path.as_posix()
            if expected_absolute_local_path is not None
            else ""
        )
        if binding_key != key or not expected or raw != expected:
            raise ManifestValidationError(
                f"binding {key} local_path must be normalized relative text"
            )
        if raw != os.path.abspath(os.path.normpath(raw)) or candidate.as_posix() != raw:
            raise ManifestValidationError(
                f"binding {key} absolute injected local_path is not normalized"
            )
        return candidate
    if (
        raw == "."
        or candidate.as_posix() != raw
        or os.path.normpath(raw) != raw
        or any(part in {"", ".", ".."} for part in candidate.parts)
    ):
        raise ManifestValidationError(
            f"binding {key} local_path must be normalized relative text"
        )
    safe_root = Path(os.path.abspath(root))
    local_path = safe_root / candidate
    if os.path.commonpath((safe_root, local_path)) != os.fspath(safe_root):
        raise ManifestValidationError(f"binding {key} local_path escapes root")
    return local_path


def _normalized_source_path(binding: dict[str, Any]) -> Path:
    key = binding["key"]
    raw = binding.get("source_path")
    if type(raw) is not str or not raw or raw != raw.strip():
        raise ManifestValidationError(
            f"binding {key} source_path must be nonempty text"
        )
    candidate = Path(raw)
    if (
        not candidate.is_absolute()
        or raw.startswith("//")
        or candidate.as_posix() != raw
        or os.path.abspath(os.path.normpath(raw)) != raw
    ):
        raise ManifestValidationError(
            f"binding {key} source_path must be normalized absolute text"
        )
    return candidate


def _validate_manifest(
    root: Path,
    manifest: Any,
    *,
    binding_key: str | None = None,
    expected_absolute_local_path: Path | None = None,
    allow_destination_symlink: bool = False,
) -> list[dict[str, Any]]:
    if not isinstance(manifest, dict):
        raise ManifestValidationError("manifest root must be a mapping")
    version = manifest.get("version")
    if type(version) is not int or version != 1:
        raise ManifestValidationError("manifest version must be the integer 1")
    bindings = manifest.get("bindings")
    if not isinstance(bindings, list) or not bindings:
        raise ManifestValidationError("manifest bindings must be a nonempty list")

    _safe_path_stat(
        Path(os.path.abspath(root)),
        label="mirror root",
        final_kind="directory",
        allow_missing=False,
    )
    seen_keys: set[str] = set()
    validated: list[dict[str, Any]] = []
    for index, raw_binding in enumerate(bindings):
        if not isinstance(raw_binding, dict):
            raise ManifestValidationError(f"binding {index} must be a mapping")
        key = raw_binding.get("key")
        if type(key) is not str or not key or key != key.strip():
            raise ManifestValidationError(f"binding {index} key must be nonempty text")
        if key in seen_keys:
            raise ManifestValidationError(f"binding key is duplicated: {key}")
        seen_keys.add(key)
        if (
            raw_binding.get("kind") != "file"
            or type(raw_binding.get("kind")) is not str
        ):
            raise ManifestValidationError(f"binding {key} kind must be exactly file")
        if type(raw_binding.get("required")) is not bool:
            raise ManifestValidationError(f"binding {key} required must be a boolean")

        binding = dict(raw_binding)
        local_path = _normalized_local_path(
            root,
            binding,
            binding_key=binding_key,
            expected_absolute_local_path=expected_absolute_local_path,
        )
        source_path = _normalized_source_path(binding)
        local_stat = _safe_path_stat(
            local_path,
            label=f"binding {key} local_path",
            final_kind="file",
            allow_missing=True,
            allow_final_symlink=allow_destination_symlink,
        )
        source_stat = _safe_path_stat(
            source_path,
            label=f"binding {key} source_path",
            final_kind="file",
            allow_missing=True,
        )
        for label, file_stat in (
            ("local_path", local_stat),
            ("source_path", source_stat),
        ):
            if (
                file_stat is not None
                and stat.S_ISREG(file_stat.st_mode)
                and file_stat.st_size > MAX_MIRROR_FILE_BYTES
            ):
                raise ManifestValidationError(
                    f"binding {key} {label} exceeds the "
                    f"{MAX_MIRROR_FILE_BYTES}-byte hash bound"
                )
        validated.append(binding)
    return validated


def _binding_row(root: Path, binding: dict[str, Any]) -> dict[str, Any]:
    local_path = root / str(binding.get("local_path") or "").strip()
    source_path = Path(str(binding.get("source_path") or "").strip())
    return {
        "key": str(binding.get("key") or "").strip(),
        "kind": str(binding.get("kind") or "").strip(),
        "local_path": local_path.as_posix(),
        "source_path": source_path.as_posix(),
        "required": binding["required"],
        "status": "ok",
    }


def _inspect_binding(
    root: Path,
    binding: dict[str, Any],
    *,
    hash_file: Callable[[Path], str] = _stable_sha256,
) -> dict[str, Any]:
    local_path = root / str(binding.get("local_path") or "").strip()
    source_path = Path(str(binding.get("source_path") or "").strip())
    row = _binding_row(root, binding)
    source_stat = _safe_path_stat(
        source_path,
        label=f"binding {binding['key']} source_path",
        final_kind="file",
        allow_missing=True,
    )
    local_stat = _safe_path_stat(
        local_path,
        label=f"binding {binding['key']} local_path",
        final_kind="file",
        allow_missing=True,
    )
    if source_stat is None:
        if (
            local_stat is not None
            and os.environ.get("EA_DESIGN_MIRROR_REQUIRE_SOURCE") != "1"
        ):
            row["source_unavailable"] = True
            row["local_sha256"] = hash_file(local_path)
        else:
            row["status"] = "missing_source"
        return row
    if local_stat is None:
        row["status"] = "missing_local"
        return row
    row["local_sha256"] = hash_file(local_path)
    row["source_sha256"] = hash_file(source_path)
    if row["local_sha256"] != row["source_sha256"]:
        row["status"] = "drift"
    return row


def inspect_manifest(
    root: Path,
    manifest_path: Path,
    *,
    hash_file: Callable[[Path], str] = _stable_sha256,
    binding_key: str | None = None,
    expected_absolute_local_path: Path | None = None,
) -> list[dict[str, Any]]:
    manifest = _load_manifest(manifest_path)
    bindings = _validate_manifest(
        root,
        manifest,
        binding_key=binding_key,
        expected_absolute_local_path=expected_absolute_local_path,
    )
    rows: list[dict[str, Any]] = []
    for binding in bindings:
        if binding_key is None or binding["key"] == binding_key:
            rows.append(_inspect_binding(root, binding, hash_file=hash_file))
    if binding_key is not None and not rows:
        raise ManifestValidationError(f"requested binding is missing: {binding_key}")
    return rows


def _safe_repair_local_path(root: Path, binding: dict[str, Any]) -> tuple[Path, Path]:
    key = str(binding.get("key") or "").strip() or "<missing>"
    raw = str(binding.get("local_path") or "").strip()
    relative = Path(raw)
    if (
        not raw
        or raw == "."
        or relative.is_absolute()
        or relative.as_posix() != raw
        or os.path.normpath(raw) != raw
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise ValueError(f"unsafe local_path for {key}: {raw or '<missing>'}")

    safe_root = Path(os.path.abspath(root))
    try:
        root_stat = os.lstat(safe_root)
    except OSError as exc:
        raise ValueError(f"repair root is missing or unreadable: {safe_root}") from exc
    if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
        raise ValueError(f"repair root is not a real directory: {safe_root}")

    destination = safe_root / relative
    if os.path.commonpath((safe_root, destination)) != os.fspath(safe_root):
        raise ValueError(f"local_path escapes repair root for {key}: {raw}")

    current = safe_root
    parent_missing = False
    for part in relative.parts[:-1]:
        current /= part
        if parent_missing:
            continue
        try:
            current_stat = os.lstat(current)
        except FileNotFoundError:
            parent_missing = True
            continue
        except OSError as exc:
            raise ValueError(
                f"local parent is unreadable for {key}: {current}"
            ) from exc
        if stat.S_ISLNK(current_stat.st_mode) or not stat.S_ISDIR(current_stat.st_mode):
            raise ValueError(
                f"local parent is not a real directory for {key}: {current}"
            )

    if not parent_missing:
        try:
            destination_stat = os.lstat(destination)
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise ValueError(f"local destination is unreadable for {key}") from exc
        else:
            if not (
                stat.S_ISREG(destination_stat.st_mode)
                or stat.S_ISLNK(destination_stat.st_mode)
            ):
                raise ValueError(
                    f"local destination is neither a regular file nor symlink for {key}"
                )
    return safe_root, relative


def _safe_repair_source(binding: dict[str, Any]) -> tuple[Path, os.stat_result | None]:
    key = str(binding.get("key") or "").strip() or "<missing>"
    raw = str(binding.get("source_path") or "").strip()
    source = Path(os.path.abspath(raw))
    current = Path(source.anchor)
    parts = source.parts[1:]
    for index, part in enumerate(parts):
        current /= part
        try:
            current_stat = os.lstat(current)
        except FileNotFoundError:
            return source, None
        except OSError as exc:
            raise ValueError(f"source path is unreadable for {key}: {current}") from exc
        if stat.S_ISLNK(current_stat.st_mode):
            raise ValueError(f"source path contains a symlink for {key}: {current}")
        if index < len(parts) - 1 and not stat.S_ISDIR(current_stat.st_mode):
            raise ValueError(f"source parent is not a directory for {key}: {current}")
        if index == len(parts) - 1 and not stat.S_ISREG(current_stat.st_mode):
            raise ValueError(f"source is not a regular file for {key}: {current}")
    return source, os.lstat(source)


def _open_destination_directory(
    root: Path,
    relative_parent: Path,
    *,
    create: bool,
) -> int | None:
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(root, flags)
    except OSError as exc:
        raise ValueError(f"repair root could not be opened safely: {root}") from exc
    try:
        for part in relative_parent.parts:
            try:
                next_descriptor = os.open(part, flags, dir_fd=descriptor)
            except FileNotFoundError:
                if not create:
                    os.close(descriptor)
                    return None
                try:
                    os.mkdir(part, mode=0o755, dir_fd=descriptor)
                except FileExistsError:
                    pass
                next_descriptor = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor
    except OSError as exc:
        os.close(descriptor)
        raise ValueError(
            f"local parent could not be traversed without following links: {relative_parent}"
        ) from exc


def _hash_descriptor(
    descriptor: int,
    *,
    expected_identity: tuple[int, ...] | None = None,
) -> str:
    before = os.fstat(descriptor)
    if not stat.S_ISREG(before.st_mode):
        raise ValueError("opened repair file is not regular")
    if expected_identity is not None and _file_identity(before) != expected_identity:
        raise ValueError("repair file identity changed before read")
    os.lseek(descriptor, 0, os.SEEK_SET)
    digest = hashlib.sha256()
    while chunk := os.read(descriptor, 65536):
        digest.update(chunk)
    after = os.fstat(descriptor)
    if _file_identity(before) != _file_identity(after):
        raise ValueError("repair file changed during read")
    os.lseek(descriptor, 0, os.SEEK_SET)
    return digest.hexdigest()


def _destination_state(directory_descriptor: int, name: str) -> tuple[str, str]:
    try:
        path_stat = os.stat(
            name,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        return "missing", ""
    if stat.S_ISLNK(path_stat.st_mode):
        return "symlink", ""
    if not stat.S_ISREG(path_stat.st_mode):
        raise ValueError(f"repair destination is not a regular file: {name}")

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(name, flags, dir_fd=directory_descriptor)
    except OSError as exc:
        raise ValueError(
            f"repair destination could not be opened safely: {name}"
        ) from exc
    try:
        digest = _hash_descriptor(
            descriptor,
            expected_identity=_file_identity(path_stat),
        )
    finally:
        os.close(descriptor)
    return "regular", digest


def _copy_descriptor_atomic(
    *,
    source_descriptor: int,
    source_identity: tuple[int, ...],
    source_digest: str,
    destination_directory_descriptor: int,
    destination_name: str,
) -> None:
    temporary_name = ""
    temporary_descriptor = -1
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        for _ in range(32):
            candidate = f".{destination_name}.tmp-{secrets.token_hex(8)}"
            try:
                temporary_descriptor = os.open(
                    candidate,
                    flags,
                    0o600,
                    dir_fd=destination_directory_descriptor,
                )
            except FileExistsError:
                continue
            temporary_name = candidate
            break
        if temporary_descriptor < 0:
            raise ValueError("could not allocate an exclusive repair temp file")

        before = os.fstat(source_descriptor)
        if _file_identity(before) != source_identity:
            raise ValueError("repair source identity changed before copy")
        os.lseek(source_descriptor, 0, os.SEEK_SET)
        copied_digest = hashlib.sha256()
        while chunk := os.read(source_descriptor, 65536):
            copied_digest.update(chunk)
            view = memoryview(chunk)
            while view:
                written = os.write(temporary_descriptor, view)
                if written <= 0:
                    raise OSError("short write to repair temp file")
                view = view[written:]
        after = os.fstat(source_descriptor)
        if _file_identity(before) != _file_identity(after):
            raise ValueError("repair source changed during copy")
        if copied_digest.hexdigest() != source_digest:
            raise ValueError("repair source bytes changed after validation")

        os.fchmod(temporary_descriptor, stat.S_IMODE(before.st_mode) & 0o777)
        os.fsync(temporary_descriptor)
        if not stat.S_ISREG(os.fstat(temporary_descriptor).st_mode):
            raise ValueError("repair temp destination is not regular")
        os.close(temporary_descriptor)
        temporary_descriptor = -1
        os.replace(
            temporary_name,
            destination_name,
            src_dir_fd=destination_directory_descriptor,
            dst_dir_fd=destination_directory_descriptor,
        )
        os.fsync(destination_directory_descriptor)
        temporary_name = ""
    finally:
        if temporary_descriptor >= 0:
            os.close(temporary_descriptor)
        if temporary_name:
            try:
                os.unlink(temporary_name, dir_fd=destination_directory_descriptor)
            except FileNotFoundError:
                pass


def repair_manifest(root: Path, manifest_path: Path) -> list[dict[str, Any]]:
    manifest = _load_manifest(manifest_path)
    bindings = _validate_manifest(
        root,
        manifest,
        allow_destination_symlink=True,
    )
    prepared: list[tuple[dict[str, Any], Path, Path, Path, os.stat_result | None]] = []
    for binding in bindings:
        safe_root, relative = _safe_repair_local_path(root, binding)
        source, source_stat = _safe_repair_source(binding)
        prepared.append((binding, safe_root, relative, source, source_stat))

    rows: list[dict[str, Any]] = []
    for binding, safe_root, relative, source, source_stat in prepared:
        row = _binding_row(safe_root, binding)
        if source_stat is None:
            directory_descriptor = _open_destination_directory(
                safe_root,
                relative.parent,
                create=False,
            )
            destination_state = "missing"
            local_digest = ""
            if directory_descriptor is not None:
                try:
                    destination_state, local_digest = _destination_state(
                        directory_descriptor,
                        relative.name,
                    )
                finally:
                    os.close(directory_descriptor)
            if (
                destination_state == "regular"
                and os.environ.get("EA_DESIGN_MIRROR_REQUIRE_SOURCE") != "1"
            ):
                row["source_unavailable"] = True
                row["local_sha256"] = local_digest
                row["action"] = "unchanged"
            else:
                row["status"] = "missing_source"
                row["action"] = "blocked_missing_source"
            rows.append(row)
            continue

        source_flags = (
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        )
        try:
            source_descriptor = os.open(source, source_flags)
        except OSError as exc:
            raise ValueError(
                f"repair source could not be opened safely: {source}"
            ) from exc
        directory_descriptor = -1
        try:
            source_identity = _file_identity(source_stat)
            source_digest = _hash_descriptor(
                source_descriptor,
                expected_identity=source_identity,
            )
            opened_directory = _open_destination_directory(
                safe_root,
                relative.parent,
                create=True,
            )
            if opened_directory is None:
                raise ValueError("repair destination directory was not created")
            directory_descriptor = opened_directory
            destination_state, local_digest = _destination_state(
                directory_descriptor,
                relative.name,
            )
            if destination_state == "regular" and local_digest == source_digest:
                row["local_sha256"] = local_digest
                row["source_sha256"] = source_digest
                row["action"] = "unchanged"
            else:
                _copy_descriptor_atomic(
                    source_descriptor=source_descriptor,
                    source_identity=source_identity,
                    source_digest=source_digest,
                    destination_directory_descriptor=directory_descriptor,
                    destination_name=relative.name,
                )
                row["local_sha256"] = source_digest
                row["source_sha256"] = source_digest
                row["action"] = "copied"
            rows.append(row)
        finally:
            if directory_descriptor >= 0:
                os.close(directory_descriptor)
            os.close(source_descriptor)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify or repair full design mirror parity from an explicit manifest."
    )
    parser.add_argument("--root", type=Path, default=ROOT, help="EA repository root.")
    parser.add_argument(
        "--manifest", type=Path, default=MANIFEST_PATH, help="Mirror manifest path."
    )
    parser.add_argument(
        "--repair",
        action="store_true",
        help="Repair drifted mirror files from their canonical sources.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print JSON output instead of a human summary.",
    )
    args = parser.parse_args()

    try:
        root = args.root.resolve()
        manifest_path = args.manifest.resolve()
        rows = (
            repair_manifest(root, manifest_path)
            if args.repair
            else inspect_manifest(root, manifest_path)
        )
    except Exception as exc:
        issue = f"{type(exc).__name__}: {exc}"
        if args.json:
            print(
                json.dumps(
                    {"status": "failed", "items": [], "issues": [issue]},
                    indent=2,
                )
            )
        else:
            print(f"failed: {issue}")
        return 1
    bad = [row for row in rows if str(row.get("status") or "") != "ok"]
    if args.json:
        print(
            json.dumps(
                {"status": "ok" if not bad else "failed", "items": rows}, indent=2
            )
        )
    else:
        for row in rows:
            print(f"{row['status']}: {row['key']} -> {row['local_path']}")
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
