#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import ctypes
import errno
import hashlib
import io
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse


RECEIPT_SCHEMA = "ea.manfred_memorial_candidate_projection.v2"
PROPERTY_PUBLICATION_AUTHORITY_SCHEMA = (
    "propertyquarry.generated-viewer-publication-authority.v1"
)
PROPERTY_PUBLIC_TOUR_PACKAGE_SCHEMA = (
    "propertyquarry.public-tour-generated-viewer-package.v1"
)
PROPERTY_RECONSTRUCTION_SCHEMA = (
    "propertyquarry.generated-reconstruction-publication.v1"
)
PROPERTY_AUTHORITY_OWNER = "PropertyQuarry"
PROPERTY_REPOSITORY = "ArchonMegalon/property"
PROPERTY_AUTHORIZED_SLUG = (
    "360-tour-balkon-wohnung-in-neustift-layout-first-0146e6f9c6"
)
PROPERTY_ARTIFACT_COMMIT = "dd81d16421339d1ac4ca9f01d65f5ebcf607258f"
PROPERTY_PACKAGER_COMMIT = "b5eb627267dadb8dd5115dde7643cd8bdbad3317"
PROPERTY_USER_INSTRUCTION_SHA256 = (
    "4763872ed9080c1aae6fa6c16b923ed79ad8e776068a40fa960520d8e646e265"
)
PROPERTY_FINAL_REVIEW_SHA256 = (
    "08b79e6b69cdb6559339919bd9c9f414aa11cf747848e6a98565e3b59cef0c8d"
)
PROPERTY_BROWSER_REVIEW_SHA256 = (
    "866bc0c59952d1000a34d0685d31b539cde96beea3ab6598604f371e47c894c3"
)
PROPERTY_AUTHORITY_SHA256 = (
    "d4c45dcf5e9d09eb092934e3b2b586a8dda14ab5e320e0ae19b62c1ed2e4d9f1"
)
PROPERTY_TOUR_SHA256 = (
    "c5aa916d54bd7c549042c4e856c411a4a0f9f573e0354f6c27e555145489642c"
)
PROPERTY_PRE_AUTHORITY_SHA256 = (
    "0e35c90d5f7c66324e386a1e92643d5c3c07c668bcd35f984d297e4825568da0"
)
PROPERTY_ALLOWED_PUBLIC_ORIGINS = frozenset(
    {"https://myexternalbrain.com", "https://propertyquarry.com"}
)
PROPERTY_PRE_AUTHORITY_CANONICALIZATION = (
    "utf8_sorted_keys_compact_ensure_ascii_false_no_trailing_lf_"
    "with_publication_authority_receipt_sha256_null"
)
PROPERTY_FINAL_REVIEW_RECEIPT = Path(
    "/home/tibor/.local/share/ea-spatial-review/"
    "20260714-neustift-viewer-accessibility-v1/flagship-3d-final-receipt.json"
)
PROPERTY_BROWSER_REVIEW_RECEIPT = Path(
    "/home/tibor/.local/share/ea-spatial-review/"
    "20260714-neustift-viewer-accessibility-v1/browser-audit/"
    "exact-viewer-browser-audit-v3.json"
)
SPATIAL_HANDOFF_SCHEMA = "ea.manfred_spatial_candidate_handoff.v1"
SPATIAL_PROJECTION_SCHEMA = "ea.manfred_memorial_spatial_projection.v2"
SPATIAL_HANDOFF_SCOPE = "candidate_spatial_handoff"
PROJECT_NAME_PREFIX = "ea-manfred-candidate-"
PRIVATE_CONTEXT_FILENAME = "memorial_private_context.json"
HELPER_IMAGE = "postgres:16-alpine@sha256:16bc17c64a573ef34162af9298258d1aec548232985b33ed7b1eac33ba35c229"
PUBLIC_GIT_FILES = (
    "memorial.json",
    "archive_registry.json",
    "archive_registry.generated.json",
)
PRIVATE_METADATA_FILES = (
    PRIVATE_CONTEXT_FILENAME,
    "audio_identification_safe_profile.json",
    "llm_profile_notes.json",
    "mail_cluster_report.json",
    "ratings.json",
    "transcript_persona_workflow.md",
    "transcript_signal_report.json",
    "tts_voice.json",
    "voice_ab.json",
    "voice_ab_challengers.json",
    "voice_profile_manifest.json",
)
PUBLIC_ASSET_SUFFIXES = {
    ".jpeg",
    ".jpg",
    ".m4a",
    ".mp3",
    ".mp4",
    ".ogg",
    ".pdf",
    ".png",
    ".svg",
    ".wav",
    ".webp",
}
MAX_ASSET_BYTES = 128 * 1024 * 1024
MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
MAX_SPATIAL_SOURCE_FILES = 64
MAX_SPATIAL_SOURCE_BYTES = 256 * 1024 * 1024
MAX_SPATIAL_FILE_BYTES = 32 * 1024 * 1024
MAX_SPATIAL_AUTHORITY_RECEIPT_BYTES = 1024 * 1024
SPATIAL_LAYOUT_ROLE_COUNTS = {
    "floorplan_texture": 1,
    "reconstruction_manifest": 1,
    "viewer_document": 1,
    "viewer_module": 2,
}
SPATIAL_VIEWER_MODULE_PATHS = {
    "generated-reconstruction/vendor/three.module.js",
    "generated-reconstruction/vendor/examples/jsm/controls/OrbitControls.js",
}
SPATIAL_PRIVATE_PATH_TOKENS = {
    ".env",
    "backup",
    "cookie",
    "cookies",
    "credential",
    "credentials",
    "debug",
    "private",
    "probe",
    "raw",
    "raw-bundle",
    "raw-export",
    "secret",
    "secrets",
    "session",
    "test",
    "tmp",
    "token",
    "tokens",
}
SPATIAL_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


def _validate_project_name(value: object) -> str:
    project = str(value or "").strip()
    suffix = project.removeprefix(PROJECT_NAME_PREFIX)
    if (
        project != project.lower()
        or project == "ea"
        or not project.startswith(PROJECT_NAME_PREFIX)
        or len(project) > 63
        or len(suffix) < 8
        or re.fullmatch(r"[a-z0-9][a-z0-9-]*", suffix) is None
    ):
        raise ValueError("manfred_candidate_project_name_invalid")
    return project


def _run(
    argv: list[str],
    *,
    cwd: Path | None = None,
    input_bytes: bytes | None = None,
) -> bytes:
    completed = subprocess.run(
        argv,
        cwd=str(cwd) if cwd else None,
        check=True,
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return completed.stdout


def _commit(source_root: Path, ref: str) -> str:
    value = (
        _run(
            [
                "git",
                "rev-parse",
                "--verify",
                f"{str(ref or 'HEAD').strip()}^{{commit}}",
            ],
            cwd=source_root,
        )
        .decode("ascii")
        .strip()
        .lower()
    )
    if len(value) != 40 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ValueError("manfred_candidate_commit_invalid")
    return value


def _git_blob(source_root: Path, commit: str, path: str) -> bytes:
    return _run(["git", "show", f"{commit}:{path}"], cwd=source_root)


def _safe_relative(value: object, *, suffix_required: bool = False) -> Path:
    text = str(value or "").strip().replace("\\", "/")
    pure = PurePosixPath(text)
    if (
        not text
        or pure.is_absolute()
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise ValueError("manfred_candidate_asset_path_invalid")
    path = Path(*pure.parts)
    if suffix_required and path.suffix.lower() not in PUBLIC_ASSET_SUFFIXES:
        raise ValueError("manfred_candidate_asset_type_forbidden")
    return path


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical_json_bytes(payload: object) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        + b"\n"
    )


def _receipt_bytes(payload: dict[str, object]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode(
            "utf-8"
        )
        + b"\n"
    )


def _spatial_path_has_private_raw_pattern(path: str) -> bool:
    lowered = str(path or "").strip().replace("\\", "/").lower()
    tokens = {
        token
        for part in PurePosixPath(lowered).parts
        for token in re.split(r"[^a-z0-9.]+", part)
        if token
    }
    return bool(tokens.intersection(SPATIAL_PRIVATE_PATH_TOKENS))


def _canonical_json_bytes_without_lf(payload: object) -> bytes:
    try:
        return json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("manfred_candidate_spatial_json_invalid") from exc


def _strict_json_object(content: bytes, *, error: str) -> dict[str, object]:
    def reject_duplicate(pairs: list[tuple[str, object]]) -> dict[str, object]:
        payload: dict[str, object] = {}
        for key, value in pairs:
            if key in payload:
                raise ValueError(error)
            payload[key] = value
        return payload

    def reject_constant(_value: str) -> None:
        raise ValueError(error)

    try:
        payload = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=reject_duplicate,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(error) from exc
    if not isinstance(payload, dict):
        raise ValueError(error)
    return payload


def _spatial_payload_has_private_host_path(value: object) -> bool:
    if isinstance(value, dict):
        return any(_spatial_payload_has_private_host_path(child) for child in value.values())
    if isinstance(value, list):
        return any(_spatial_payload_has_private_host_path(child) for child in value)
    if not isinstance(value, str):
        return False
    normalized = value.strip().replace("\\", "/").lower()
    return (
        normalized.startswith(("/home/", "/tmp/", "/var/tmp/", "file://", "pcloud://"))
        or "/home/" in normalized
        or "/tmp/" in normalized
        or "/var/tmp/" in normalized
    )


def _spatial_release_contract(
    payload: dict[str, object], *, expected_slug: str = ""
) -> tuple[str, list[str], str, str]:
    slug = str(payload.get("slug") or "").strip()
    if (
        not SPATIAL_SLUG_RE.fullmatch(slug)
        or slug in {".", ".."}
        or (expected_slug and slug != expected_slug)
    ):
        raise ValueError("manfred_candidate_spatial_slug_invalid")
    release_raw = payload.get("generated_viewer_release")
    generated_raw = payload.get("generated_reconstruction")
    if not isinstance(release_raw, dict) or not isinstance(generated_raw, dict):
        raise ValueError("manfred_candidate_spatial_release_contract_invalid")
    bindings_raw = release_raw.get("asset_bindings")
    if not isinstance(bindings_raw, list) or len(bindings_raw) != 5:
        raise ValueError("manfred_candidate_spatial_asset_allowlist_invalid")
    role_counts: dict[str, int] = {}
    paths: list[str] = []
    proof_relpath = ""
    viewer_relpath = ""
    floorplan_relpath = ""
    module_paths: set[str] = set()
    expected_mimes = {
        "viewer_document": {"text/html"},
        "reconstruction_manifest": {"application/json"},
        "floorplan_texture": {"image/png"},
        "viewer_module": {"text/javascript"},
    }
    for raw_binding in bindings_raw:
        if not isinstance(raw_binding, dict):
            raise ValueError("manfred_candidate_spatial_asset_allowlist_invalid")
        path = _safe_relative(raw_binding.get("path")).as_posix()
        role = str(raw_binding.get("role") or "").strip().lower()
        digest = str(raw_binding.get("sha256") or "").strip().lower()
        mime_type = str(raw_binding.get("mime_type") or "").strip().lower()
        size_bytes = raw_binding.get("size_bytes")
        if (
            set(raw_binding)
            != {"path", "sha256", "size_bytes", "mime_type", "role"}
            or not path.startswith("generated-reconstruction/")
            or _spatial_path_has_private_raw_pattern(path)
            or role not in SPATIAL_LAYOUT_ROLE_COUNTS
            or mime_type not in expected_mimes.get(role, set())
            or not SHA256_RE.fullmatch(digest)
            or type(size_bytes) is not int
            or int(size_bytes) <= 0
            or int(size_bytes) > MAX_SPATIAL_FILE_BYTES
        ):
            raise ValueError("manfred_candidate_spatial_asset_allowlist_invalid")
        paths.append(path)
        role_counts[role] = role_counts.get(role, 0) + 1
        if role == "reconstruction_manifest":
            proof_relpath = path
        elif role == "viewer_document":
            viewer_relpath = path
        elif role == "floorplan_texture":
            floorplan_relpath = path
        elif role == "viewer_module":
            module_paths.add(path)
    if (
        role_counts != SPATIAL_LAYOUT_ROLE_COUNTS
        or len(set(paths)) != 5
        or str(release_raw.get("viewer_relpath") or "").strip() != viewer_relpath
        or str(generated_raw.get("manifest_relpath") or "").strip() != proof_relpath
        or viewer_relpath != "generated-reconstruction/viewer.html"
        or proof_relpath != "generated-reconstruction/reconstruction.json"
        or floorplan_relpath
        != str(generated_raw.get("floorplan_relpath") or "").strip()
        or not floorplan_relpath.startswith("generated-reconstruction/")
        or Path(floorplan_relpath).suffix.lower() != ".png"
        or module_paths != SPATIAL_VIEWER_MODULE_PATHS
    ):
        raise ValueError("manfred_candidate_spatial_asset_allowlist_invalid")
    return slug, sorted(paths), viewer_relpath, proof_relpath


def _spatial_package_sha256(snapshot: dict[str, bytes]) -> str:
    rows = [
        {
            "path": path,
            "sha256": _sha256(content),
            "size_bytes": len(content),
        }
        for path, content in sorted(snapshot.items())
    ]
    return _sha256(_canonical_json_bytes_without_lf(rows))


def _safe_spatial_source_mode(mode: int, *, directory: bool) -> bool:
    normalized = stat.S_IMODE(mode)
    if normalized & 0o7000 or normalized & 0o002:
        return False
    if directory:
        return bool(normalized & 0o500 == 0o500)
    return bool(normalized & 0o400)


def _read_spatial_file_snapshot(path: Path, *, require_sanitized_modes: bool) -> bytes:
    path = Path(os.path.abspath(os.fspath(path.expanduser())))
    if path.name in {"", ".", ".."}:
        raise ValueError("manfred_candidate_spatial_source_invalid")
    parent_descriptor = _open_directory_path_nofollow(path.parent)
    try:
        identity = (
            lambda metadata: (
                metadata.st_dev,
                metadata.st_ino,
                metadata.st_mode,
                metadata.st_nlink,
                metadata.st_size,
                metadata.st_mtime_ns,
                metadata.st_ctime_ns,
            )
        )
        try:
            initial = os.stat(
                path.name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        except OSError as exc:
            raise ValueError("manfred_candidate_spatial_source_invalid") from exc
        expected_mode = 0o644
        if (
            not stat.S_ISREG(initial.st_mode)
            or stat.S_ISLNK(initial.st_mode)
            or initial.st_nlink != 1
            or initial.st_size <= 0
            or initial.st_size > MAX_SPATIAL_FILE_BYTES
            or (
                require_sanitized_modes
                and stat.S_IMODE(initial.st_mode) != expected_mode
            )
            or (
                not require_sanitized_modes
                and not _safe_spatial_source_mode(initial.st_mode, directory=False)
            )
        ):
            raise ValueError("manfred_candidate_spatial_source_invalid")
        flags = (
            os.O_RDONLY
            | os.O_CLOEXEC
            | getattr(os, "O_NONBLOCK", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        try:
            descriptor = os.open(path.name, flags, dir_fd=parent_descriptor)
        except OSError as exc:
            raise ValueError("manfred_candidate_spatial_source_invalid") from exc
        try:
            opened = os.fstat(descriptor)
            if identity(initial) != identity(opened):
                raise ValueError("manfred_candidate_spatial_source_changed")
            chunks: list[bytes] = []
            remaining = int(opened.st_size)
            while remaining:
                chunk = os.read(descriptor, min(1024 * 1024, remaining))
                if not chunk:
                    raise ValueError("manfred_candidate_spatial_source_changed")
                chunks.append(chunk)
                remaining -= len(chunk)
            if identity(opened) != identity(os.fstat(descriptor)):
                raise ValueError("manfred_candidate_spatial_source_changed")
        finally:
            os.close(descriptor)
        try:
            final_path_metadata = os.stat(
                path.name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        except OSError as exc:
            raise ValueError("manfred_candidate_spatial_source_changed") from exc
        if identity(initial) != identity(final_path_metadata):
            raise ValueError("manfred_candidate_spatial_source_changed")
        return b"".join(chunks)
    finally:
        os.close(parent_descriptor)


def _open_directory_path_nofollow(
    path: Path,
    *,
    create_missing: bool = False,
    create_mode: int = 0o700,
) -> int:
    normalized = Path(os.path.abspath(os.fspath(path.expanduser())))
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory_flag = getattr(os, "O_DIRECTORY", None)
    if nofollow is None or directory_flag is None:
        raise ValueError("manfred_candidate_spatial_nofollow_unavailable")
    flags = os.O_RDONLY | os.O_CLOEXEC | directory_flag | nofollow
    try:
        descriptor = os.open("/", flags)
    except OSError as exc:
        raise ValueError("manfred_candidate_spatial_root_invalid") from exc
    try:
        for part in normalized.parts[1:]:
            if part in {"", ".", ".."} or "/" in part:
                raise ValueError("manfred_candidate_spatial_path_invalid")
            try:
                child = os.open(part, flags, dir_fd=descriptor)
            except FileNotFoundError as exc:
                if not create_missing:
                    raise ValueError(
                        "manfred_candidate_spatial_root_invalid"
                    ) from exc
                try:
                    os.mkdir(part, create_mode, dir_fd=descriptor)
                    child = os.open(part, flags, dir_fd=descriptor)
                except OSError as exc:
                    raise ValueError(
                        "manfred_candidate_spatial_output_parent_invalid"
                    ) from exc
            except OSError as exc:
                raise ValueError("manfred_candidate_spatial_root_invalid") from exc
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _spatial_tree_snapshot(
    root: Path, *, require_sanitized_modes: bool
) -> dict[str, bytes]:
    root = Path(os.path.abspath(os.fspath(root.expanduser())))
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise ValueError("manfred_candidate_spatial_nofollow_unavailable")
    directory_flags = os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | nofollow
    file_flags = (
        os.O_RDONLY
        | os.O_CLOEXEC
        | getattr(os, "O_NONBLOCK", 0)
        | nofollow
    )

    def directory_identity(metadata: os.stat_result) -> tuple[int, ...]:
        return (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_mode,
            metadata.st_nlink,
            metadata.st_size,
            metadata.st_mtime_ns,
            metadata.st_ctime_ns,
        )

    def file_identity(metadata: os.stat_result) -> tuple[int, ...]:
        return (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_mode,
            metadata.st_nlink,
            metadata.st_size,
            metadata.st_mtime_ns,
            metadata.st_ctime_ns,
        )

    def validate_directory(metadata: os.stat_result, *, root_entry: bool) -> None:
        if not stat.S_ISDIR(metadata.st_mode):
            raise ValueError(
                "manfred_candidate_spatial_root_invalid"
                if root_entry
                else "manfred_candidate_spatial_source_invalid"
            )
        if require_sanitized_modes:
            safe_mode = stat.S_IMODE(metadata.st_mode) == 0o755
        else:
            safe_mode = _safe_spatial_source_mode(
                metadata.st_mode, directory=True
            )
        if not safe_mode:
            raise ValueError(
                "manfred_candidate_spatial_root_invalid"
                if root_entry
                else "manfred_candidate_spatial_mode_invalid"
            )

    root_descriptor = _open_directory_path_nofollow(root)
    files: dict[str, bytes] = {}
    total_bytes = 0

    def walk(directory_descriptor: int, relative: tuple[str, ...]) -> None:
        nonlocal total_bytes
        before = os.fstat(directory_descriptor)
        validate_directory(before, root_entry=False)
        try:
            with os.scandir(directory_descriptor) as iterator:
                names = sorted(entry.name for entry in iterator)
        except OSError as exc:
            raise ValueError("manfred_candidate_spatial_source_invalid") from exc
        for name in names:
            if name in {"", ".", ".."} or "/" in name:
                raise ValueError("manfred_candidate_spatial_path_invalid")
            try:
                initial = os.stat(
                    name,
                    dir_fd=directory_descriptor,
                    follow_symlinks=False,
                )
            except OSError as exc:
                raise ValueError(
                    "manfred_candidate_spatial_source_changed"
                ) from exc
            projected = (*relative, name)
            relpath = PurePosixPath(*projected).as_posix()
            if stat.S_ISLNK(initial.st_mode):
                raise ValueError("manfred_candidate_spatial_symlink_forbidden")
            if stat.S_ISDIR(initial.st_mode):
                validate_directory(initial, root_entry=False)
                try:
                    child_descriptor = os.open(
                        name,
                        directory_flags,
                        dir_fd=directory_descriptor,
                    )
                except OSError as exc:
                    raise ValueError(
                        "manfred_candidate_spatial_source_changed"
                    ) from exc
                try:
                    opened = os.fstat(child_descriptor)
                    if directory_identity(initial) != directory_identity(opened):
                        raise ValueError(
                            "manfred_candidate_spatial_source_changed"
                        )
                    walk(child_descriptor, projected)
                    if directory_identity(opened) != directory_identity(
                        os.fstat(child_descriptor)
                    ):
                        raise ValueError(
                            "manfred_candidate_spatial_source_changed"
                        )
                finally:
                    os.close(child_descriptor)
                try:
                    final_path_metadata = os.stat(
                        name,
                        dir_fd=directory_descriptor,
                        follow_symlinks=False,
                    )
                except OSError as exc:
                    raise ValueError(
                        "manfred_candidate_spatial_source_changed"
                    ) from exc
                if directory_identity(initial) != directory_identity(
                    final_path_metadata
                ):
                    raise ValueError("manfred_candidate_spatial_source_changed")
                continue
            if not stat.S_ISREG(initial.st_mode):
                raise ValueError("manfred_candidate_spatial_nonregular_forbidden")
            expected_mode = 0o644
            if (
                initial.st_nlink != 1
                or initial.st_size <= 0
                or initial.st_size > MAX_SPATIAL_FILE_BYTES
                or (
                    require_sanitized_modes
                    and stat.S_IMODE(initial.st_mode) != expected_mode
                )
                or (
                    not require_sanitized_modes
                    and not _safe_spatial_source_mode(
                        initial.st_mode, directory=False
                    )
                )
            ):
                raise ValueError("manfred_candidate_spatial_source_invalid")
            try:
                file_descriptor = os.open(
                    name,
                    file_flags,
                    dir_fd=directory_descriptor,
                )
            except OSError as exc:
                raise ValueError("manfred_candidate_spatial_source_changed") from exc
            try:
                opened = os.fstat(file_descriptor)
                if (
                    file_identity(initial) != file_identity(opened)
                    or not stat.S_ISREG(opened.st_mode)
                    or opened.st_nlink != 1
                ):
                    raise ValueError("manfred_candidate_spatial_source_changed")
                chunks: list[bytes] = []
                remaining = int(opened.st_size)
                while remaining:
                    chunk = os.read(file_descriptor, min(1024 * 1024, remaining))
                    if not chunk:
                        raise ValueError("manfred_candidate_spatial_source_changed")
                    chunks.append(chunk)
                    remaining -= len(chunk)
                final = os.fstat(file_descriptor)
                if file_identity(opened) != file_identity(final):
                    raise ValueError("manfred_candidate_spatial_source_changed")
                content = b"".join(chunks)
            finally:
                os.close(file_descriptor)
            try:
                final_path_metadata = os.stat(
                    name,
                    dir_fd=directory_descriptor,
                    follow_symlinks=False,
                )
            except OSError as exc:
                raise ValueError("manfred_candidate_spatial_source_changed") from exc
            if file_identity(initial) != file_identity(final_path_metadata):
                raise ValueError("manfred_candidate_spatial_source_changed")
            files[relpath] = content
            total_bytes += len(content)
            if (
                len(files) > MAX_SPATIAL_SOURCE_FILES
                or total_bytes > MAX_SPATIAL_SOURCE_BYTES
            ):
                raise ValueError("manfred_candidate_spatial_bundle_oversize")
        if directory_identity(before) != directory_identity(
            os.fstat(directory_descriptor)
        ):
            raise ValueError("manfred_candidate_spatial_source_changed")

    try:
        root_metadata = os.fstat(root_descriptor)
        validate_directory(root_metadata, root_entry=True)
        try:
            root_path_metadata = os.stat(root, follow_symlinks=False)
        except OSError as exc:
            raise ValueError("manfred_candidate_spatial_root_invalid") from exc
        if directory_identity(root_metadata) != directory_identity(root_path_metadata):
            raise ValueError("manfred_candidate_spatial_root_invalid")
        walk(root_descriptor, ())
        final_root_metadata = os.fstat(root_descriptor)
        try:
            final_root_path_metadata = os.stat(root, follow_symlinks=False)
        except OSError as exc:
            raise ValueError("manfred_candidate_spatial_source_changed") from exc
        if (
            directory_identity(root_metadata)
            != directory_identity(final_root_metadata)
            or directory_identity(final_root_metadata)
            != directory_identity(final_root_path_metadata)
        ):
            raise ValueError("manfred_candidate_spatial_source_changed")
    finally:
        os.close(root_descriptor)
    if not files:
        raise ValueError("manfred_candidate_spatial_bundle_empty")
    return files


def _verify_spatial_bundle_before_copy(bundle: Path, *, slug: str) -> dict[str, object]:
    verifier = Path(__file__).with_name(
        "verify_public_tour_generated_viewer_release.py"
    )
    try:
        raw = _run(
            [
                sys.executable,
                str(verifier),
                "--bundle-dir",
                str(bundle),
                "--slug",
                slug,
            ]
        )
        receipt = json.loads(raw)
    except (
        subprocess.CalledProcessError,
        json.JSONDecodeError,
        UnicodeDecodeError,
    ) as exc:
        raise ValueError("manfred_candidate_spatial_verifier_blocked") from exc
    if (
        not isinstance(receipt, dict)
        or receipt.get("pass") is not True
        or receipt.get("status") != "pass"
        or receipt.get("slug") != slug
        or dict(receipt.get("checks") or {}).get("binding_count") != 5
    ):
        raise ValueError("manfred_candidate_spatial_verifier_blocked")
    return receipt


def _property_review_evidence(snapshot: dict[str, bytes]) -> dict[str, object]:
    final_path = Path(PROPERTY_FINAL_REVIEW_RECEIPT)
    browser_path = Path(PROPERTY_BROWSER_REVIEW_RECEIPT)
    final_bytes = _read_spatial_file_snapshot(
        final_path, require_sanitized_modes=False
    )
    browser_bytes = _read_spatial_file_snapshot(
        browser_path, require_sanitized_modes=False
    )
    for path, content, expected in (
        (final_path, final_bytes, PROPERTY_FINAL_REVIEW_SHA256),
        (browser_path, browser_bytes, PROPERTY_BROWSER_REVIEW_SHA256),
    ):
        metadata = os.lstat(path)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or _sha256(content) != expected
        ):
            raise ValueError("manfred_candidate_spatial_review_evidence_invalid")
    final = _strict_json_object(
        final_bytes, error="manfred_candidate_spatial_final_review_invalid"
    )
    browser = _strict_json_object(
        browser_bytes, error="manfred_candidate_spatial_browser_review_invalid"
    )
    final_source = dict(final.get("source") or {})
    review_bundle = dict(final.get("review_bundle") or {})
    visual = dict(final.get("visual_verification") or {})
    verification = dict(final.get("verification") or {})
    live_guard = dict(final.get("live_guard") or {})
    if (
        final.get("schema") != "propertyquarry.flagship_3d_review_receipt.v1"
        or final.get("status")
        != "polished_review_candidate_pass_guarded_not_published"
        or final.get("slug") != PROPERTY_AUTHORIZED_SLUG
        or final_source.get("commit") != PROPERTY_ARTIFACT_COMMIT
        or final_source.get("worktree_clean") is not True
        or review_bundle.get("viewer_sha256")
        != _sha256(snapshot["generated-reconstruction/viewer.html"])
        or review_bundle.get("floorplan_sha256")
        != _sha256(snapshot["generated-reconstruction/source-floorplan.png"])
        or review_bundle.get("runtime_publish_required") is not False
        or review_bundle.get("runtime_publish_ok") is not True
        or review_bundle.get("verified_provider_capture") is not False
        or review_bundle.get("satisfies_verified_tour_gate") is not False
        or visual.get("browser_receipt_sha256") != PROPERTY_BROWSER_REVIEW_SHA256
        or visual.get("browser_status") != "pass"
        or visual.get("browser_failures") != []
        or visual.get("route_status") != "pass"
        or visual.get("route_failures") != []
        or visual.get("route_stop_count") != 9
        or set(visual.get("surfaces") or [])
        != {"desktop", "mobile", "reduced-motion", "webgl-fallback"}
        or dict(verification.get("property_generated_reconstruction") or {}).get(
            "result"
        )
        != "pass"
        or dict(verification.get("property_tour_control_and_importers") or {}).get(
            "result"
        )
        != "pass"
        or dict(
            verification.get("independent_camera_geometry_accessibility_review")
            or {}
        ).get("result")
        != "approved"
        or dict(
            verification.get("independent_runtime_publish_safety_review") or {}
        ).get("result")
        != "approved"
        or live_guard.get("runtime_mutation_detected") is not False
        or live_guard.get("all_observed_product_routes_guarded_404") is not True
    ):
        raise ValueError("manfred_candidate_spatial_final_review_invalid")
    browser_surfaces = dict(browser.get("surfaces") or {})
    if (
        browser.get("schema") != "propertyquarry.exact_viewer_browser_audit.v3"
        or browser.get("status") != "pass"
        or browser.get("slug") != PROPERTY_AUTHORIZED_SLUG
        or browser.get("failures") != []
        or browser.get("viewer_sha256")
        != _sha256(snapshot["generated-reconstruction/viewer.html"])
        or browser.get("reconstruction_sha256")
        != review_bundle.get("reconstruction_sha256")
        or set(browser_surfaces)
        != {"desktop", "mobile", "reduced-motion", "webgl-fallback"}
    ):
        raise ValueError("manfred_candidate_spatial_browser_review_invalid")
    for name, raw_surface in browser_surfaces.items():
        surface = dict(raw_surface or {})
        expected_status = "not-ready" if name == "webgl-fallback" else "ready"
        if (
            surface.get("http_status") != 200
            or surface.get("viewerStatus") != expected_status
            or surface.get("page_errors") != []
            or surface.get("console_errors") != []
            or surface.get("horizontalOverflowPx") != 0
            or surface.get("undersizedTargets") != []
            or (
                name == "webgl-fallback"
                and (
                    surface.get("alertRole") != "alert"
                    or surface.get("alertVisible") is not True
                    or surface.get("enabledInteractiveControlCount") != 0
                )
            )
        ):
            raise ValueError("manfred_candidate_spatial_browser_review_invalid")
    return {
        "flagship_final": {
            "schema": str(final["schema"]),
            "status": str(final["status"]),
            "sha256": PROPERTY_FINAL_REVIEW_SHA256,
        },
        "exact_viewer_browser": {
            "schema": str(browser["schema"]),
            "status": str(browser["status"]),
            "sha256": PROPERTY_BROWSER_REVIEW_SHA256,
        },
    }


def _validated_property_publication(
    *,
    snapshot: dict[str, bytes],
    authority_bytes: bytes,
    target_origin: str,
) -> dict[str, object]:
    target_origin = _validate_public_base_url(target_origin)
    if len(authority_bytes) > MAX_SPATIAL_AUTHORITY_RECEIPT_BYTES:
        raise ValueError("manfred_candidate_spatial_authority_receipt_invalid")
    try:
        tour_bytes = snapshot["tour.json"]
        proof_bytes = snapshot[
            "generated-reconstruction/reconstruction.json"
        ]
    except KeyError as exc:
        raise ValueError("manfred_candidate_spatial_asset_allowlist_invalid") from exc
    tour = _strict_json_object(
        tour_bytes, error="manfred_candidate_spatial_manifest_invalid"
    )
    authority = _strict_json_object(
        authority_bytes,
        error="manfred_candidate_spatial_authority_receipt_invalid",
    )
    proof = _strict_json_object(
        proof_bytes, error="manfred_candidate_spatial_proof_manifest_invalid"
    )
    if (
        tour_bytes != _canonical_json_bytes(tour)
        or authority_bytes != _canonical_json_bytes(authority)
    ):
        raise ValueError("manfred_candidate_spatial_manifest_not_canonical")
    slug, asset_paths, viewer_relpath, proof_relpath = _spatial_release_contract(
        tour, expected_slug=PROPERTY_AUTHORIZED_SLUG
    )
    expected_paths = {"tour.json", *asset_paths}
    if set(snapshot) != expected_paths or len(snapshot) != 6:
        raise ValueError("manfred_candidate_spatial_asset_allowlist_invalid")
    release = dict(tour.get("generated_viewer_release") or {})
    generated = dict(tour.get("generated_reconstruction") or {})
    bindings = list(release.get("asset_bindings") or [])
    route_labels = list(generated.get("route_labels") or [])
    for raw_binding in bindings:
        binding = dict(raw_binding or {})
        path = str(binding.get("path") or "")
        content = snapshot.get(path)
        if (
            content is None
            or binding.get("sha256") != _sha256(content)
            or binding.get("size_bytes") != len(content)
        ):
            raise ValueError("manfred_candidate_spatial_asset_digest_mismatch")
    authority_sha256 = _sha256(authority_bytes)
    if (
        tour.get("schema") != PROPERTY_PUBLIC_TOUR_PACKAGE_SCHEMA
        or tour.get("source_commit") != PROPERTY_ARTIFACT_COMMIT
        or tour.get("synthetic") is not True
        or generated.get("synthetic") is not True
        or generated.get("capture_mode") is not False
        or generated.get("verified_provider_capture") is not False
        or generated.get("satisfies_verified_tour_gate") is not False
        or release.get("contract") != "ea.public-tour-generated-viewer-release.v1"
        or release.get("status") != "ready"
        or release.get("public_activation_authority") is not True
        or release.get("publication_authority_verified") is not True
        or release.get("publication_authority_receipt_sha256")
        != authority_sha256
        or release.get("browser_receipt_sha256")
        != PROPERTY_BROWSER_REVIEW_SHA256
        or release.get("source_provenance_receipt_sha256")
        != PROPERTY_FINAL_REVIEW_SHA256
        or release.get("security_review_receipt_sha256")
        != PROPERTY_FINAL_REVIEW_SHA256
        or release.get("accessibility_review_receipt_sha256")
        != PROPERTY_FINAL_REVIEW_SHA256
        or release.get("browser_interaction_verified") is not True
        or release.get("visual_quality_review_passed") is not True
        or release.get("security_review_passed") is not True
        or release.get("accessibility_review_passed") is not True
        or release.get("source_provenance_verified") is not True
        or release.get("revoked") is not False
        or release.get("disqualified") is not False
        or len(route_labels) != 9
        or route_labels != list(tour.get("route_labels") or [])
        or len(set(str(label) for label in route_labels)) != 9
        or any(
            not isinstance(label, str)
            or not label.strip()
            or label != label.strip()
            for label in route_labels
        )
        or _spatial_payload_has_private_host_path(tour)
    ):
        raise ValueError("manfred_candidate_spatial_release_contract_invalid")
    authority_source = dict(authority.get("source") or {})
    classification = dict(authority.get("classification") or {})
    authority_package = dict(authority.get("package") or {})
    authority_reviews = dict(authority.get("review_receipts") or {})
    if (
        set(authority)
        != {
            "allowed_public_origins",
            "classification",
            "owner",
            "package",
            "public_activation_authority",
            "publication_authority_verified",
            "repository",
            "review_receipts",
            "schema",
            "slug",
            "source",
            "status",
            "user_instruction_sha256",
        }
        or authority.get("schema") != PROPERTY_PUBLICATION_AUTHORITY_SCHEMA
        or authority.get("status") != "authorized"
        or authority.get("owner") != PROPERTY_AUTHORITY_OWNER
        or authority.get("repository") != PROPERTY_REPOSITORY
        or authority.get("slug") != slug
        or authority.get("public_activation_authority") is not True
        or authority.get("publication_authority_verified") is not True
        or authority.get("user_instruction_sha256")
        != PROPERTY_USER_INSTRUCTION_SHA256
        or set(authority.get("allowed_public_origins") or [])
        != PROPERTY_ALLOWED_PUBLIC_ORIGINS
        or target_origin not in PROPERTY_ALLOWED_PUBLIC_ORIGINS
        or target_origin not in list(authority.get("allowed_public_origins") or [])
        or authority_source
        != {
            "artifact_commit": PROPERTY_ARTIFACT_COMMIT,
            "packager_commit": PROPERTY_PACKAGER_COMMIT,
            "worktree_clean": True,
        }
        or classification.get("synthetic") is not True
        or classification.get("capture_mode") is not False
        or classification.get("verified_provider_capture") is not False
        or classification.get("satisfies_verified_tour_gate") is not False
        or not str(classification.get("disclosure") or "").strip()
        or authority_reviews
        != {
            "flagship_final": {
                "schema": "propertyquarry.flagship_3d_review_receipt.v1",
                "status": "polished_review_candidate_pass_guarded_not_published",
                "sha256": PROPERTY_FINAL_REVIEW_SHA256,
            },
            "exact_viewer_browser": {
                "schema": "propertyquarry.exact_viewer_browser_audit.v3",
                "status": "pass",
                "sha256": PROPERTY_BROWSER_REVIEW_SHA256,
            },
        }
        or authority_package.get("public_bundle_relpath")
        != f"public_property_tours/{slug}"
        or authority_package.get("public_file_relpaths") != sorted(expected_paths)
        or authority_package.get("public_file_count") != 6
        or authority_package.get("pre_authority_manifest_canonicalization")
        != PROPERTY_PRE_AUTHORITY_CANONICALIZATION
        or authority_package.get("asset_bindings") != bindings
        or authority_sha256 != PROPERTY_AUTHORITY_SHA256
        or _sha256(tour_bytes) != PROPERTY_TOUR_SHA256
    ):
        raise ValueError("manfred_candidate_spatial_authority_receipt_mismatch")
    pre_authority = copy.deepcopy(tour)
    pre_release = dict(pre_authority.get("generated_viewer_release") or {})
    pre_release["publication_authority_receipt_sha256"] = None
    pre_authority["generated_viewer_release"] = pre_release
    pre_authority_sha256 = _sha256(
        _canonical_json_bytes_without_lf(pre_authority)
    )
    if (
        pre_authority_sha256 != PROPERTY_PRE_AUTHORITY_SHA256
        or authority_package.get("pre_authority_manifest_canonical_sha256")
        != pre_authority_sha256
    ):
        raise ValueError("manfred_candidate_spatial_pre_authority_digest_mismatch")
    floorplan = dict(proof.get("floorplan") or {})
    viewer = dict(proof.get("viewer") or {})
    if (
        proof_bytes != _canonical_json_bytes(proof)
        or proof.get("schema") != PROPERTY_RECONSTRUCTION_SCHEMA
        or proof.get("slug") != slug
        or proof.get("source_commit") != PROPERTY_ARTIFACT_COMMIT
        or proof.get("synthetic") is not True
        or proof.get("capture_mode") is not False
        or proof.get("verified_provider_capture") is not False
        or proof.get("satisfies_verified_tour_gate") is not False
        or proof.get("route_labels") != route_labels
        or floorplan.get("source_path")
        != (
            f"property://{PROPERTY_REPOSITORY}/{PROPERTY_ARTIFACT_COMMIT}/"
            "floorplan-apartment-crop.png"
        )
        or floorplan.get("sha256")
        != _sha256(snapshot["generated-reconstruction/source-floorplan.png"])
        or viewer.get("sha256")
        != _sha256(snapshot["generated-reconstruction/viewer.html"])
        or _spatial_payload_has_private_host_path(proof)
    ):
        raise ValueError("manfred_candidate_spatial_proof_manifest_invalid")
    review_evidence = _property_review_evidence(snapshot)
    if review_evidence != authority_reviews:
        raise ValueError("manfred_candidate_spatial_review_evidence_mismatch")
    return {
        "slug": slug,
        "asset_paths": asset_paths,
        "viewer_relpath": viewer_relpath,
        "proof_relpath": proof_relpath,
        "route_labels": route_labels,
        "upstream_publication_authority": authority,
        "upstream_publication_authority_sha256": authority_sha256,
        "upstream_public_activation_authority": True,
        "upstream_package_sha256": _spatial_package_sha256(snapshot),
        "upstream_tour_manifest_sha256": _sha256(tour_bytes),
        "pre_authority_manifest_canonical_sha256": pre_authority_sha256,
        "review_evidence": review_evidence,
    }


def _exclusive_write_at(
    parent_descriptor: int,
    name: str,
    content: bytes,
    *,
    mode: int,
) -> tuple[int, int]:
    if name in {"", ".", ".."} or "/" in name:
        raise ValueError("manfred_candidate_spatial_output_name_invalid")
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | os.O_CLOEXEC
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(name, flags, mode, dir_fd=parent_descriptor)
    except OSError as exc:
        raise ValueError("manfred_candidate_spatial_output_exists") from exc
    try:
        offset = 0
        while offset < len(content):
            written = os.write(descriptor, content[offset:])
            if written <= 0:
                raise ValueError("manfred_candidate_spatial_output_write_failed")
            offset += written
        os.fchmod(descriptor, mode)
        os.fsync(descriptor)
        metadata = os.fstat(descriptor)
        return metadata.st_dev, metadata.st_ino
    finally:
        os.close(descriptor)


def _write_spatial_bundle_at(
    root_descriptor: int, files: dict[str, bytes]
) -> None:
    directory_flags = (
        os.O_RDONLY
        | os.O_CLOEXEC
        | os.O_DIRECTORY
        | getattr(os, "O_NOFOLLOW", 0)
    )
    for relpath, content in sorted(files.items()):
        parts = _safe_relative(relpath).parts
        descriptor = os.dup(root_descriptor)
        try:
            for part in parts[:-1]:
                try:
                    os.mkdir(part, 0o755, dir_fd=descriptor)
                except FileExistsError:
                    pass
                child = os.open(part, directory_flags, dir_fd=descriptor)
                os.fchmod(child, 0o755)
                os.close(descriptor)
                descriptor = child
            _exclusive_write_at(
                descriptor,
                parts[-1],
                content,
                mode=0o644,
            )
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    os.fchmod(root_descriptor, 0o755)
    os.fsync(root_descriptor)


def _rename_noreplace(
    source_parent_descriptor: int,
    source_name: str,
    destination_parent_descriptor: int,
    destination_name: str,
) -> None:
    renameat2 = getattr(ctypes.CDLL(None, use_errno=True), "renameat2", None)
    if renameat2 is None:
        raise ValueError("manfred_candidate_spatial_rename_noreplace_unavailable")
    renameat2.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    renameat2.restype = ctypes.c_int
    if (
        renameat2(
            source_parent_descriptor,
            os.fsencode(source_name),
            destination_parent_descriptor,
            os.fsencode(destination_name),
            1,
        )
        == 0
    ):
        return
    error_number = ctypes.get_errno()
    if error_number in {errno.EEXIST, errno.ENOTEMPTY}:
        raise ValueError("manfred_candidate_spatial_output_exists")
    raise ValueError("manfred_candidate_spatial_output_install_failed")


def _remove_bundle_if_identity(
    parent_descriptor: int, name: str, identity: tuple[int, int]
) -> None:
    try:
        metadata = os.stat(
            name, dir_fd=parent_descriptor, follow_symlinks=False
        )
    except OSError:
        return
    if (metadata.st_dev, metadata.st_ino) != identity or not stat.S_ISDIR(
        metadata.st_mode
    ):
        return
    shutil.rmtree(Path(f"/proc/{os.getpid()}/fd/{parent_descriptor}") / name)


def _unlink_file_if_identity(
    parent_descriptor: int, name: str, identity: tuple[int, int]
) -> None:
    try:
        metadata = os.stat(
            name, dir_fd=parent_descriptor, follow_symlinks=False
        )
    except OSError:
        return
    if (metadata.st_dev, metadata.st_ino) == identity and stat.S_ISREG(
        metadata.st_mode
    ):
        os.unlink(name, dir_fd=parent_descriptor)


def materialize_spatial_handoff(
    *,
    source_bundle_dir: Path,
    upstream_authority_receipt_path: Path,
    handoff_bundle_dir: Path,
    handoff_receipt_path: Path,
    target_origin: str,
) -> dict[str, object]:
    source_bundle_dir = Path(
        os.path.abspath(os.fspath(source_bundle_dir.expanduser()))
    )
    upstream_authority_receipt_path = Path(
        os.path.abspath(os.fspath(upstream_authority_receipt_path.expanduser()))
    )
    handoff_bundle_dir = Path(
        os.path.abspath(os.fspath(handoff_bundle_dir.expanduser()))
    )
    handoff_receipt_path = Path(
        os.path.abspath(os.fspath(handoff_receipt_path.expanduser()))
    )
    target_origin = _validate_public_base_url(target_origin)
    if (
        handoff_bundle_dir.name != PROPERTY_AUTHORIZED_SLUG
        or handoff_bundle_dir == source_bundle_dir
        or source_bundle_dir in handoff_bundle_dir.parents
        or upstream_authority_receipt_path == handoff_receipt_path
    ):
        raise ValueError("manfred_candidate_spatial_materialization_target_invalid")
    snapshot = _spatial_tree_snapshot(
        source_bundle_dir, require_sanitized_modes=True
    )
    authority_bytes = _read_spatial_file_snapshot(
        upstream_authority_receipt_path,
        require_sanitized_modes=False,
    )
    if stat.S_IMODE(os.lstat(upstream_authority_receipt_path).st_mode) != 0o600:
        raise ValueError("manfred_candidate_spatial_authority_receipt_invalid")
    validated = _validated_property_publication(
        snapshot=snapshot,
        authority_bytes=authority_bytes,
        target_origin=target_origin,
    )
    _verify_spatial_bundle_before_copy(
        source_bundle_dir, slug=str(validated["slug"])
    )
    receipt = {
        "schema": SPATIAL_HANDOFF_SCHEMA,
        "status": "pass",
        "scope": SPATIAL_HANDOFF_SCOPE,
        "candidate_handoff_authorized": True,
        "public_activation_authority": False,
        "target_origin": target_origin,
        "slug": validated["slug"],
        "asset_paths": validated["asset_paths"],
        "upstream_owner": PROPERTY_AUTHORITY_OWNER,
        "upstream_repository": PROPERTY_REPOSITORY,
        "upstream_publication_authority_schema": (
            PROPERTY_PUBLICATION_AUTHORITY_SCHEMA
        ),
        "upstream_publication_authority_sha256": validated[
            "upstream_publication_authority_sha256"
        ],
        "upstream_public_activation_authority": True,
        "upstream_package_sha256": validated["upstream_package_sha256"],
        "upstream_tour_manifest_sha256": validated[
            "upstream_tour_manifest_sha256"
        ],
        "source_artifact_commit": PROPERTY_ARTIFACT_COMMIT,
        "source_packager_commit": PROPERTY_PACKAGER_COMMIT,
        "review_evidence": validated["review_evidence"],
    }
    receipt_bytes = _receipt_bytes(receipt)
    bundle_parent_descriptor = _open_directory_path_nofollow(
        handoff_bundle_dir.parent, create_missing=True
    )
    receipt_parent_descriptor = _open_directory_path_nofollow(
        handoff_receipt_path.parent, create_missing=True
    )
    temporary_name = f".{handoff_bundle_dir.name}.{uuid.uuid4().hex}.tmp"
    staging_descriptor = -1
    bundle_installed = False
    receipt_identity: tuple[int, int] | None = None
    staging_identity: tuple[int, int] | None = None
    try:
        try:
            os.mkdir(temporary_name, 0o700, dir_fd=bundle_parent_descriptor)
            staging_descriptor = os.open(
                temporary_name,
                os.O_RDONLY
                | os.O_CLOEXEC
                | os.O_DIRECTORY
                | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=bundle_parent_descriptor,
            )
        except OSError as exc:
            raise ValueError(
                "manfred_candidate_spatial_output_staging_failed"
            ) from exc
        staging_metadata = os.fstat(staging_descriptor)
        staging_identity = (staging_metadata.st_dev, staging_metadata.st_ino)
        _write_spatial_bundle_at(staging_descriptor, snapshot)
        staging_path = handoff_bundle_dir.parent / temporary_name
        path_metadata = os.lstat(staging_path)
        if (path_metadata.st_dev, path_metadata.st_ino) != staging_identity:
            raise ValueError("manfred_candidate_spatial_output_parent_changed")
        _verify_spatial_bundle_before_copy(
            staging_path, slug=str(validated["slug"])
        )
        staged_snapshot = _spatial_tree_snapshot(
            staging_path, require_sanitized_modes=True
        )
        final_path_metadata = os.lstat(staging_path)
        if (
            (final_path_metadata.st_dev, final_path_metadata.st_ino)
            != staging_identity
            or staged_snapshot != snapshot
        ):
            raise ValueError("manfred_candidate_spatial_output_digest_drift")
        _rename_noreplace(
            bundle_parent_descriptor,
            temporary_name,
            bundle_parent_descriptor,
            handoff_bundle_dir.name,
        )
        bundle_installed = True
        receipt_identity = _exclusive_write_at(
            receipt_parent_descriptor,
            handoff_receipt_path.name,
            receipt_bytes,
            mode=0o600,
        )
    except BaseException:
        if receipt_identity is not None:
            _unlink_file_if_identity(
                receipt_parent_descriptor,
                handoff_receipt_path.name,
                receipt_identity,
            )
        if staging_identity is not None:
            _remove_bundle_if_identity(
                bundle_parent_descriptor,
                handoff_bundle_dir.name if bundle_installed else temporary_name,
                staging_identity,
            )
        raise
    finally:
        if staging_descriptor >= 0:
            os.close(staging_descriptor)
        os.close(bundle_parent_descriptor)
        os.close(receipt_parent_descriptor)
    return {
        **receipt,
        "handoff_bundle_dir": str(handoff_bundle_dir),
        "handoff_receipt_path": str(handoff_receipt_path),
        "handoff_receipt_sha256": _sha256(receipt_bytes),
        "public_file_count": len(snapshot),
    }


def _validated_spatial_handoff_input(
    *,
    bundle_dir: Path,
    authority_receipt_path: Path,
    target_origin: str,
) -> dict[str, object]:
    snapshot = _spatial_tree_snapshot(
        bundle_dir, require_sanitized_modes=True
    )
    authority_bytes = _read_spatial_file_snapshot(
        authority_receipt_path, require_sanitized_modes=False
    )
    if stat.S_IMODE(os.lstat(authority_receipt_path).st_mode) != 0o600:
        raise ValueError("manfred_candidate_spatial_authority_receipt_invalid")
    validated = _validated_property_publication(
        snapshot=snapshot,
        authority_bytes=authority_bytes,
        target_origin=target_origin,
    )
    if bundle_dir.name != validated["slug"]:
        raise ValueError("manfred_candidate_spatial_slug_invalid")
    verifier_receipt = _verify_spatial_bundle_before_copy(
        bundle_dir, slug=str(validated["slug"])
    )
    return {
        "included": True,
        "files": snapshot,
        **validated,
        "verifier_receipt": verifier_receipt,
    }


def _copy_regular(
    source: Path, destination: Path, *, maximum: int, mode: int
) -> dict[str, object]:
    try:
        metadata = source.lstat()
    except OSError as exc:
        raise ValueError("manfred_candidate_source_asset_missing") from exc
    if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise ValueError("manfred_candidate_source_asset_invalid")
    if metadata.st_size <= 0 or metadata.st_size > maximum:
        raise ValueError("manfred_candidate_source_asset_size_invalid")
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    content = source.read_bytes()
    if len(content) != metadata.st_size:
        raise ValueError("manfred_candidate_source_asset_changed")
    destination.write_bytes(content)
    destination.chmod(mode)
    return {"sha256": _sha256(content), "size_bytes": len(content)}


def _write_bytes(destination: Path, content: bytes, *, mode: int) -> dict[str, object]:
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination.write_bytes(content)
    destination.chmod(mode)
    return {"sha256": _sha256(content), "size_bytes": len(content)}


def _load_private_context(
    source_root: Path, slug: str
) -> tuple[dict[str, object], bytes]:
    app_root = source_root / "ea"
    if str(app_root) not in sys.path:
        sys.path.insert(0, str(app_root))
    from app.services.memorial_private_context import (  # noqa: PLC0415
        read_private_memorial_context_document,
    )

    return read_private_memorial_context_document(
        private_root=source_root / "memorial_data" / "private_memorial_profiles",
        slug=slug,
    )


def _declared_assets(
    public_payload: dict[str, object], private_overrides: dict[str, object]
) -> dict[Path, int]:
    merged = dict(public_payload)
    merged.update(private_overrides)
    assets: dict[Path, int] = {}

    def add(value: object, *, private: bool) -> None:
        if not str(value or "").strip():
            return
        assets[_safe_relative(value, suffix_required=True)] = (
            0o400 if private else 0o444
        )

    for field in ("audio_clips", "public_documents", "candidate_recordings"):
        rows = merged.get(field)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            visibility = str(row.get("visibility") or "").strip().lower()
            add(row.get("asset_relpath"), private=visibility != "public")
    for field in ("pwa_icon", "video_call_avatar"):
        row = merged.get(field)
        if not isinstance(row, dict):
            continue
        for key, value in row.items():
            if "relpath" in str(key) or str(key).startswith("src_"):
                add(value, private=False)
    return assets


def _copy_archive(
    *, source_root: Path, commit: str, destination: Path
) -> list[dict[str, object]]:
    archive = _run(
        ["git", "archive", "--format=tar", commit, "memorial_archive/manfred/public"],
        cwd=source_root,
    )
    receipts: list[dict[str, object]] = []
    total = 0
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as bundle:
        for member in bundle.getmembers():
            if member.isdir():
                continue
            if not member.isfile() or member.issym() or member.islnk():
                raise ValueError("manfred_candidate_archive_entry_invalid")
            relative = _safe_relative(member.name)
            prefix = Path("memorial_archive")
            try:
                projected = relative.relative_to(prefix)
            except ValueError as exc:
                raise ValueError("manfred_candidate_archive_path_invalid") from exc
            extracted = bundle.extractfile(member)
            if extracted is None:
                raise ValueError("manfred_candidate_archive_entry_invalid")
            content = extracted.read(MAX_ARCHIVE_BYTES + 1)
            total += len(content)
            if len(content) != member.size or total > MAX_ARCHIVE_BYTES:
                raise ValueError("manfred_candidate_archive_size_invalid")
            target = destination / projected
            info = _write_bytes(target, content, mode=0o444)
            receipts.append({"path": projected.as_posix(), **info})
    return sorted(receipts, key=lambda item: str(item["path"]))


def _tree_digest(root: Path) -> tuple[str, list[dict[str, object]]]:
    def directory_identity(metadata: os.stat_result) -> tuple[int, ...]:
        return (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_mode,
            metadata.st_mtime_ns,
            metadata.st_ctime_ns,
        )

    def file_identity(metadata: os.stat_result) -> tuple[int, ...]:
        return (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_mode,
            metadata.st_nlink,
            metadata.st_size,
            metadata.st_mtime_ns,
            metadata.st_ctime_ns,
        )

    directory_flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_DIRECTORY", 0)
    file_flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NONBLOCK", 0)
    if hasattr(os, "O_NOFOLLOW"):
        directory_flags |= os.O_NOFOLLOW
        file_flags |= os.O_NOFOLLOW
    try:
        root_descriptor = os.open(root, directory_flags)
    except OSError as exc:
        raise ValueError("manfred_candidate_projection_root_invalid") from exc
    rows: list[dict[str, object]] = []
    try:
        root_metadata = os.fstat(root_descriptor)
        try:
            root_path_metadata = os.stat(root, follow_symlinks=False)
        except OSError as exc:
            raise ValueError("manfred_candidate_projection_root_invalid") from exc
        if (
            not stat.S_ISDIR(root_metadata.st_mode)
            or stat.S_ISLNK(root_path_metadata.st_mode)
            or stat.S_IMODE(root_metadata.st_mode) != 0o550
            or (root_metadata.st_dev, root_metadata.st_ino)
            != (root_path_metadata.st_dev, root_path_metadata.st_ino)
        ):
            raise ValueError("manfred_candidate_projection_root_invalid")

        def walk(directory_descriptor: int, relative: tuple[str, ...]) -> None:
            before = os.fstat(directory_descriptor)
            if (
                not stat.S_ISDIR(before.st_mode)
                or stat.S_IMODE(before.st_mode) != 0o550
            ):
                raise ValueError("manfred_candidate_projection_directory_mode_invalid")
            try:
                with os.scandir(directory_descriptor) as iterator:
                    entries = sorted(iterator, key=lambda row: row.name)
            except OSError as exc:
                raise ValueError("manfred_candidate_projection_entry_invalid") from exc
            for entry in entries:
                name = entry.name
                try:
                    initial = os.stat(
                        name,
                        dir_fd=directory_descriptor,
                        follow_symlinks=False,
                    )
                except OSError as exc:
                    raise ValueError(
                        "manfred_candidate_projection_changed_during_digest"
                    ) from exc
                projected = (*relative, name)
                if stat.S_ISDIR(initial.st_mode) and not stat.S_ISLNK(initial.st_mode):
                    try:
                        child_descriptor = os.open(
                            name,
                            directory_flags,
                            dir_fd=directory_descriptor,
                        )
                    except OSError as exc:
                        raise ValueError(
                            "manfred_candidate_projection_changed_during_digest"
                        ) from exc
                    try:
                        opened = os.fstat(child_descriptor)
                        if (
                            directory_identity(initial) != directory_identity(opened)
                            or stat.S_IMODE(opened.st_mode) != 0o550
                        ):
                            raise ValueError(
                                "manfred_candidate_projection_changed_during_digest"
                            )
                        walk(child_descriptor, projected)
                        if directory_identity(opened) != directory_identity(
                            os.fstat(child_descriptor)
                        ):
                            raise ValueError(
                                "manfred_candidate_projection_changed_during_digest"
                            )
                    finally:
                        os.close(child_descriptor)
                    continue
                if not stat.S_ISREG(initial.st_mode) or stat.S_ISLNK(initial.st_mode):
                    raise ValueError("manfred_candidate_projection_entry_invalid")
                if initial.st_nlink != 1:
                    raise ValueError("manfred_candidate_projection_file_links_invalid")
                mode = stat.S_IMODE(initial.st_mode)
                if mode not in {0o440, 0o444}:
                    raise ValueError("manfred_candidate_projection_file_mode_invalid")
                try:
                    file_descriptor = os.open(
                        name,
                        file_flags,
                        dir_fd=directory_descriptor,
                    )
                except OSError as exc:
                    raise ValueError(
                        "manfred_candidate_projection_changed_during_digest"
                    ) from exc
                try:
                    opened = os.fstat(file_descriptor)
                    if (
                        file_identity(initial) != file_identity(opened)
                        or not stat.S_ISREG(opened.st_mode)
                        or opened.st_nlink != 1
                    ):
                        raise ValueError(
                            "manfred_candidate_projection_changed_during_digest"
                        )
                    digest = hashlib.sha256()
                    size = 0
                    while True:
                        chunk = os.read(file_descriptor, 1024 * 1024)
                        if not chunk:
                            break
                        digest.update(chunk)
                        size += len(chunk)
                    final = os.fstat(file_descriptor)
                    if file_identity(opened) != file_identity(final) or size != int(
                        opened.st_size
                    ):
                        raise ValueError(
                            "manfred_candidate_projection_changed_during_digest"
                        )
                finally:
                    os.close(file_descriptor)
                rows.append(
                    {
                        "path": PurePosixPath(*projected).as_posix(),
                        "sha256": digest.hexdigest(),
                        "size_bytes": size,
                        "mode": format(mode, "03o"),
                    }
                )
            if directory_identity(before) != directory_identity(
                os.fstat(directory_descriptor)
            ):
                raise ValueError("manfred_candidate_projection_changed_during_digest")

        walk(root_descriptor, ())
        final_root_metadata = os.fstat(root_descriptor)
        try:
            final_root_path_metadata = os.stat(root, follow_symlinks=False)
        except OSError as exc:
            raise ValueError(
                "manfred_candidate_projection_changed_during_digest"
            ) from exc
        if directory_identity(root_metadata) != directory_identity(
            final_root_metadata
        ) or (final_root_metadata.st_dev, final_root_metadata.st_ino) != (
            final_root_path_metadata.st_dev,
            final_root_path_metadata.st_ino,
        ):
            raise ValueError("manfred_candidate_projection_changed_during_digest")
    finally:
        os.close(root_descriptor)
    encoded = json.dumps(rows, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return _sha256(encoded), rows


def _set_modes(root: Path) -> None:
    for path in sorted(root.rglob("*"), reverse=True):
        if path.is_dir():
            path.chmod(0o550)
        elif path.is_file():
            current = stat.S_IMODE(path.stat().st_mode)
            path.chmod(0o440 if current & 0o044 == 0 else 0o444)
    root.chmod(0o550)


def _make_tree_removable(root: Path) -> None:
    if not root.exists():
        return
    root.chmod(0o700)
    for path in root.rglob("*"):
        if path.is_dir():
            path.chmod(0o700)
        elif path.is_file():
            path.chmod(0o600)


def _install_or_verify_release(
    *,
    staging: Path,
    release_root: Path,
    projection_sha256: str,
    projected_files: list[dict[str, object]],
) -> None:
    if release_root.exists():
        if release_root.is_symlink() or not release_root.is_dir():
            raise ValueError("manfred_candidate_existing_release_invalid")
        try:
            existing_sha256, existing_files = _tree_digest(release_root)
        except (OSError, ValueError) as exc:
            raise ValueError("manfred_candidate_existing_release_unverifiable") from exc
        if existing_sha256 != projection_sha256 or existing_files != projected_files:
            raise ValueError("manfred_candidate_existing_release_digest_mismatch")
        _make_tree_removable(staging)
        shutil.rmtree(staging)
        return
    os.replace(staging, release_root)


def _chown_for_runtime(paths: list[Path], *, uid: int, gid: int) -> None:
    if os.geteuid() == 0:
        for root in paths:
            os.chown(root, uid, gid)
            for path in root.rglob("*"):
                os.chown(path, uid, gid, follow_symlinks=False)
        return
    command = (
        "chown -R "
        + f"{uid}:{gid} "
        + " ".join(f"/target/{index}" for index in range(len(paths)))
    )
    argv = [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--user",
        "0:0",
        "--read-only",
        "--pull",
        "never",
        "--entrypoint",
        "/bin/sh",
    ]
    for index, path in enumerate(paths):
        argv.extend(["--volume", f"{path.resolve()}:/target/{index}:rw"])
    argv.extend([HELPER_IMAGE, "-ec", command])
    _run(argv)


def _validate_public_base_url(value: str) -> str:
    normalized = str(value or "").strip().rstrip("/")
    try:
        parsed = urlparse(normalized)
    except ValueError as exc:
        raise ValueError("manfred_candidate_public_base_url_invalid") from exc
    host = str(parsed.hostname or "").strip().lower().strip(".")
    if (
        parsed.scheme != "https"
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or bool(parsed.query)
        or bool(parsed.fragment)
        or parsed.path not in {"", "/"}
        or host in {"localhost", "127.0.0.1", "example.test", "example.invalid"}
        or host.endswith(".invalid")
        or host.endswith(".localhost")
        or host.endswith(".local")
        or host.endswith(".test")
    ):
        raise ValueError("manfred_candidate_public_base_url_invalid")
    return normalized


def _image_revision(image: str) -> tuple[str, str]:
    if not image or image.lower() == "latest" or image.lower().endswith(":latest"):
        raise ValueError("manfred_candidate_image_tag_invalid")
    payload = json.loads(_run(["docker", "image", "inspect", image]))
    if not isinstance(payload, list) or len(payload) != 1:
        raise ValueError("manfred_candidate_image_missing")
    row = payload[0]
    labels = dict((row.get("Config") or {}).get("Labels") or {})
    return str(row.get("Id") or ""), str(
        labels.get("org.opencontainers.image.revision") or ""
    )


def _parse_env(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    if stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise ValueError("manfred_candidate_env_permissions_invalid")
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError("manfred_candidate_env_invalid")
        key, value = line.split("=", 1)
        if not key or any(
            character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"
            for character in key
        ):
            raise ValueError("manfred_candidate_env_invalid")
        if "\x00" in value or "\n" in value or "\r" in value:
            raise ValueError("manfred_candidate_env_invalid")
        values[key] = value
    return values


def _write_env(
    *,
    path: Path,
    image: str,
    release_root: Path,
    runtime_root: Path,
    public_base_url: str,
    host_port: int,
    project_name: str,
    spatial_release_root: Path | None = None,
    spatial_handoff_included: bool = False,
    spatial_slug: str = "",
    spatial_sha256: str = "",
    rotate_secrets: bool = False,
) -> None:
    current = _parse_env(path)
    postgres_password = (
        "" if rotate_secrets else current.get("EA_MANFRED_POSTGRES_PASSWORD", "")
    ) or secrets.token_hex(32)
    api_token = (
        "" if rotate_secrets else current.get("EA_API_TOKEN", "")
    ) or secrets.token_urlsafe(48)
    signing_secret = (
        "" if rotate_secrets else current.get("EA_SIGNING_SECRET", "")
    ) or secrets.token_urlsafe(64)
    resolved_spatial_root = (
        spatial_release_root or (release_root / "public_property_tours")
    ).resolve()
    normalized_spatial_sha256 = spatial_sha256 or _sha256(b"[]")
    if not SHA256_RE.fullmatch(normalized_spatial_sha256):
        raise ValueError("manfred_candidate_spatial_digest_invalid")
    if spatial_handoff_included != bool(spatial_slug):
        raise ValueError("manfred_candidate_spatial_slug_invalid")
    values = {
        "EA_MANFRED_COMPOSE_PROJECT": _validate_project_name(project_name),
        "EA_MANFRED_IMAGE": image,
        "EA_MANFRED_ENV_FILE": str(path.resolve()),
        "EA_MANFRED_RELEASE_ROOT": str(release_root.resolve()),
        "EA_MANFRED_RUNTIME_ROOT": str(runtime_root.resolve()),
        "EA_MANFRED_SPATIAL_HANDOFF_INCLUDED": (
            "1" if spatial_handoff_included else "0"
        ),
        "EA_MANFRED_SPATIAL_RELEASE_ROOT": str(resolved_spatial_root),
        "EA_MANFRED_SPATIAL_SHA256": normalized_spatial_sha256,
        "EA_MANFRED_SPATIAL_SLUG": spatial_slug,
        "EA_MANFRED_HOST_PORT": str(host_port),
        "EA_MANFRED_POSTGRES_PASSWORD": postgres_password,
        "DATABASE_URL": f"postgresql://ea:{postgres_password}@postgres:5432/ea",
        "EA_API_TOKEN": api_token,
        "EA_SIGNING_SECRET": signing_secret,
        "EA_PUBLIC_APP_BASE_URL": public_base_url,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=str(path.parent)
    )
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            for key in sorted(values):
                handle.write(f"{key}={values[key]}\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        Path(temporary).unlink(missing_ok=True)


def _atomic_receipt(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=str(path.parent)
    )
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        Path(temporary).unlink(missing_ok=True)


def prepare_candidate(
    *,
    source_root: Path,
    ref: str,
    image: str,
    deploy_root: Path,
    public_base_url: str,
    host_port: int,
    project_name: str,
    spatial_tour_bundle_dir: Path | None = None,
    spatial_authority_receipt: Path | None = None,
    runtime_uid: int = 10001,
    runtime_gid: int = 10001,
    rotate_secrets: bool = False,
) -> dict[str, object]:
    source_root = source_root.expanduser().resolve()
    deploy_root = deploy_root.expanduser().resolve()
    if not 1024 <= host_port <= 65535:
        raise ValueError("manfred_candidate_host_port_invalid")
    project_name = _validate_project_name(project_name)
    public_base_url = _validate_public_base_url(public_base_url)
    commit = _commit(source_root, ref)
    image_id, image_commit = _image_revision(image)
    if image_commit != commit:
        raise ValueError("manfred_candidate_image_revision_mismatch")
    if bool(spatial_tour_bundle_dir) != bool(spatial_authority_receipt):
        raise ValueError("manfred_candidate_spatial_input_pair_required")
    spatial_handoff: dict[str, object] = {
        "included": False,
        "slug": "",
        "files": {},
        "asset_paths": [],
        "viewer_relpath": "",
        "proof_relpath": "",
        "route_labels": [],
        "upstream_publication_authority": {},
        "upstream_publication_authority_sha256": "",
        "upstream_public_activation_authority": False,
        "upstream_package_sha256": "",
        "upstream_tour_manifest_sha256": "",
        "pre_authority_manifest_canonical_sha256": "",
        "review_evidence": {},
        "verifier_receipt": {},
    }
    if spatial_tour_bundle_dir and spatial_authority_receipt:
        spatial_handoff = _validated_spatial_handoff_input(
            bundle_dir=Path(
                os.path.abspath(os.fspath(spatial_tour_bundle_dir.expanduser()))
            ),
            authority_receipt_path=Path(
                os.path.abspath(os.fspath(spatial_authority_receipt.expanduser()))
            ),
            target_origin=public_base_url,
        )

    slug = "manfred"
    public_documents: dict[str, bytes] = {}
    for name in PUBLIC_GIT_FILES:
        public_documents[name] = _git_blob(
            source_root,
            commit,
            f"memorial_data/public_memorials/{slug}/{name}",
        )
    try:
        public_payload = json.loads(public_documents["memorial.json"])
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("manfred_candidate_public_manifest_invalid") from exc
    if not isinstance(public_payload, dict) or public_payload.get("slug") != slug:
        raise ValueError("manfred_candidate_public_manifest_invalid")
    private_overrides, private_document = _load_private_context(source_root, slug)

    releases_root = deploy_root / "releases"
    receipts_root = deploy_root / "receipts"
    runtime_root = deploy_root / "runtime"
    releases_root.mkdir(parents=True, exist_ok=True)
    receipts_root.mkdir(parents=True, exist_ok=True)
    staging = releases_root / f".{commit[:12]}.{uuid.uuid4().hex}.tmp"
    staging.mkdir(mode=0o700)
    try:
        public_root = staging / "public_memorials" / slug
        private_root = staging / "private_memorial_profiles" / slug
        archive_root = staging / "memorial_archive"
        spatial_root = staging / "public_property_tours"
        spatial_root.mkdir(mode=0o700)
        file_receipts: list[dict[str, object]] = []
        for name, content in public_documents.items():
            info = _write_bytes(public_root / name, content, mode=0o444)
            file_receipts.append({"path": f"public_memorials/{slug}/{name}", **info})
        public_source = source_root / "memorial_data" / "public_memorials" / slug
        for relative, mode in sorted(
            _declared_assets(public_payload, private_overrides).items(),
            key=lambda item: item[0].as_posix(),
        ):
            info = _copy_regular(
                public_source / relative,
                public_root / relative,
                maximum=MAX_ASSET_BYTES,
                mode=mode,
            )
            file_receipts.append(
                {"path": f"public_memorials/{slug}/{relative.as_posix()}", **info}
            )

        private_source = (
            source_root / "memorial_data" / "private_memorial_profiles" / slug
        )
        for name in PRIVATE_METADATA_FILES:
            source = private_source / name
            if name == PRIVATE_CONTEXT_FILENAME:
                info = _write_bytes(private_root / name, private_document, mode=0o400)
            elif source.exists():
                info = _copy_regular(
                    source, private_root / name, maximum=8 * 1024 * 1024, mode=0o400
                )
            else:
                continue
            file_receipts.append(
                {"path": f"private_memorial_profiles/{slug}/{name}", **info}
            )

        voice_manifest_path = private_source / "voice_profile_manifest.json"
        if voice_manifest_path.is_file():
            voice_manifest = json.loads(voice_manifest_path.read_text(encoding="utf-8"))
            for item in list(voice_manifest.get("audio_assets") or []):
                if not isinstance(item, dict):
                    continue
                relative_value = str(item.get("asset_relpath") or "").strip()
                if not relative_value.startswith("voice_profile/"):
                    continue
                relative = _safe_relative(relative_value, suffix_required=True)
                info = _copy_regular(
                    private_source / relative,
                    private_root / relative,
                    maximum=MAX_ASSET_BYTES,
                    mode=0o400,
                )
                file_receipts.append(
                    {
                        "path": f"private_memorial_profiles/{slug}/{relative.as_posix()}",
                        **info,
                    }
                )
        curated = Path("voice_profile/curated/unmixr-challenger-youtube-v5.wav")
        if (private_source / curated).is_file():
            info = _copy_regular(
                private_source / curated,
                private_root / curated,
                maximum=MAX_ASSET_BYTES,
                mode=0o400,
            )
            file_receipts.append(
                {
                    "path": f"private_memorial_profiles/{slug}/{curated.as_posix()}",
                    **info,
                }
            )

        archive_receipts = _copy_archive(
            source_root=source_root,
            commit=commit,
            destination=archive_root,
        )
        file_receipts.extend(
            {
                "path": f"memorial_archive/{row['path']}",
                "sha256": row["sha256"],
                "size_bytes": row["size_bytes"],
            }
            for row in archive_receipts
        )
        spatial_slug = str(spatial_handoff.get("slug") or "")
        if spatial_handoff.get("included") is True:
            spatial_files = dict(spatial_handoff.get("files") or {})
            for relpath, content in sorted(spatial_files.items()):
                if not isinstance(content, bytes):
                    raise ValueError("manfred_candidate_spatial_source_invalid")
                info = _write_bytes(
                    spatial_root / spatial_slug / _safe_relative(relpath),
                    content,
                    mode=0o444,
                )
                file_receipts.append(
                    {
                        "path": (f"public_property_tours/{spatial_slug}/{relpath}"),
                        **info,
                    }
                )
        _set_modes(staging)
        spatial_projection_sha256, spatial_projected_files = _tree_digest(spatial_root)
        projection_sha256, projected_files = _tree_digest(staging)
        release_id = f"{commit[:12]}-{projection_sha256[:12]}"
        release_root = releases_root / release_id
        _install_or_verify_release(
            staging=staging,
            release_root=release_root,
            projection_sha256=projection_sha256,
            projected_files=projected_files,
        )

        public_contributions = runtime_root / "public-contributions"
        private_contributions = runtime_root / "private-contributions"
        state_root = runtime_root / "state"
        for path, mode in (
            (public_contributions, 0o700),
            (private_contributions, 0o700),
            (state_root, 0o700),
        ):
            if not path.exists():
                path.mkdir(parents=True, exist_ok=True)
                path.chmod(mode)
        operator_gid = os.getgid()
        _chown_for_runtime([release_root], uid=runtime_uid, gid=operator_gid)
        _chown_for_runtime(
            [public_contributions, private_contributions, state_root],
            uid=runtime_uid,
            gid=runtime_gid,
        )

        env_path = deploy_root / "candidate.env"
        _write_env(
            path=env_path,
            image=image,
            release_root=release_root,
            runtime_root=runtime_root,
            public_base_url=public_base_url,
            host_port=host_port,
            project_name=project_name,
            spatial_release_root=release_root / "public_property_tours",
            spatial_handoff_included=bool(spatial_handoff.get("included")),
            spatial_slug=spatial_slug,
            spatial_sha256=spatial_projection_sha256,
            rotate_secrets=rotate_secrets,
        )
        created_at = (
            datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )
        spatial_receipt_path = receipts_root / f"{release_id}.spatial.json"
        spatial_receipt = {
            "schema": SPATIAL_PROJECTION_SCHEMA,
            "status": "pass",
            "created_at": created_at,
            "release_id": release_id,
            "spatial_handoff_included": bool(spatial_handoff.get("included")),
            "slug": spatial_slug,
            "spatial_release_root": str(
                (release_root / "public_property_tours").resolve()
            ),
            "spatial_projection_sha256": spatial_projection_sha256,
            "file_count": len(spatial_projected_files),
            "projection_bytes": sum(
                int(row["size_bytes"]) for row in spatial_projected_files
            ),
            "files": spatial_projected_files,
            "asset_paths": list(spatial_handoff.get("asset_paths") or []),
            "viewer_relpath": str(spatial_handoff.get("viewer_relpath") or ""),
            "proof_relpath": str(spatial_handoff.get("proof_relpath") or ""),
            "route_labels": list(spatial_handoff.get("route_labels") or []),
            "upstream_publication_authority": dict(
                spatial_handoff.get("upstream_publication_authority") or {}
            ),
            "upstream_publication_authority_sha256": str(
                spatial_handoff.get("upstream_publication_authority_sha256") or ""
            ),
            "upstream_public_activation_authority": bool(
                spatial_handoff.get("upstream_public_activation_authority")
            ),
            "upstream_package_sha256": str(
                spatial_handoff.get("upstream_package_sha256") or ""
            ),
            "upstream_tour_manifest_sha256": str(
                spatial_handoff.get("upstream_tour_manifest_sha256") or ""
            ),
            "pre_authority_manifest_canonical_sha256": str(
                spatial_handoff.get("pre_authority_manifest_canonical_sha256")
                or ""
            ),
            "review_evidence": dict(
                spatial_handoff.get("review_evidence") or {}
            ),
            "source_verifier": dict(spatial_handoff.get("verifier_receipt") or {}),
            "candidate_handoff_authorized": bool(spatial_handoff.get("included")),
            "public_activation_authority": False,
        }
        spatial_receipt_bytes = _receipt_bytes(spatial_receipt)
        _atomic_receipt(spatial_receipt_path, spatial_receipt)
        receipt = {
            "schema": RECEIPT_SCHEMA,
            "status": "pass",
            "created_at": created_at,
            "commit": commit,
            "image": image,
            "image_id": image_id,
            "release_id": release_id,
            "release_root": str(release_root),
            "runtime_root": str(runtime_root),
            "env_file": str(env_path),
            "host_port": host_port,
            "compose_project": project_name,
            "projection_sha256": projection_sha256,
            "private_context_sha256": _sha256(private_document),
            "file_count": len(projected_files),
            "projection_bytes": sum(int(row["size_bytes"]) for row in projected_files),
            "tracked_public_manifest": True,
            "tracked_public_archive_only": True,
            "private_context_in_image": False,
            "provider_credentials_in_candidate_env": False,
            "candidate_secrets_rotated": rotate_secrets,
            "runtime_uid": runtime_uid,
            "runtime_gid": runtime_gid,
            "projection_operator_gid": operator_gid,
            "spatial_handoff_included": bool(spatial_handoff.get("included")),
            "spatial_slug": spatial_slug,
            "spatial_release_root": str(
                (release_root / "public_property_tours").resolve()
            ),
            "spatial_projection_sha256": spatial_projection_sha256,
            "spatial_file_count": len(spatial_projected_files),
            "spatial_projection_bytes": sum(
                int(row["size_bytes"]) for row in spatial_projected_files
            ),
            "spatial_receipt_path": str(spatial_receipt_path.resolve()),
            "spatial_receipt_sha256": _sha256(spatial_receipt_bytes),
            "spatial_upstream_public_activation_authority": bool(
                spatial_handoff.get("upstream_public_activation_authority")
            ),
            "spatial_ea_public_activation_authority": False,
        }
        _atomic_receipt(receipts_root / f"{release_id}.json", receipt)
        return receipt
    finally:
        if staging.exists():
            _make_tree_removable(staging)
            shutil.rmtree(staging)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare a private, hash-receipted Manfred Memorial candidate projection."
    )
    parser.add_argument(
        "--source-root", default=str(Path(__file__).resolve().parents[1])
    )
    parser.add_argument("--ref", default="HEAD")
    parser.add_argument("--image", required=True)
    parser.add_argument(
        "--deploy-root",
        default=str(Path("~/.local/share/ea-deploy/manfred-memorial")),
    )
    parser.add_argument("--public-base-url", required=True)
    parser.add_argument("--host-port", type=int, default=18090)
    parser.add_argument(
        "--project-name",
        required=True,
        help="Unique ea-manfred-candidate-<deployment> Compose project name.",
    )
    parser.add_argument("--rotate-secrets", action="store_true")
    parser.add_argument(
        "--spatial-tour-bundle-dir",
        help="Optional exact Property-owned six-file generated-viewer bundle.",
    )
    parser.add_argument(
        "--spatial-authority-receipt",
        help="Mode-0600 detached Property publication authority paired with the bundle.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        receipt = prepare_candidate(
            source_root=Path(args.source_root),
            ref=args.ref,
            image=args.image,
            deploy_root=Path(args.deploy_root),
            public_base_url=args.public_base_url,
            host_port=args.host_port,
            project_name=args.project_name,
            spatial_tour_bundle_dir=(
                Path(args.spatial_tour_bundle_dir)
                if args.spatial_tour_bundle_dir
                else None
            ),
            spatial_authority_receipt=(
                Path(args.spatial_authority_receipt)
                if args.spatial_authority_receipt
                else None
            ),
            rotate_secrets=args.rotate_secrets,
        )
    except (
        OSError,
        ValueError,
        RuntimeError,
        subprocess.CalledProcessError,
        json.JSONDecodeError,
    ) as exc:
        print(
            json.dumps(
                {
                    "schema": RECEIPT_SCHEMA,
                    "status": "fail",
                    "error": str(exc)[:200],
                    "private_material_included": False,
                    "provider_credentials_included": False,
                },
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
