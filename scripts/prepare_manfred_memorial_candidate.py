#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import ctypes
import errno
import functools
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

try:
    from scripts.build_manfred_memorial_image import (
        IMAGE_BUILD_AUTHORITY_BINDING_KEYS,
        IMAGE_BUILD_RECEIPT_MAX_BYTES,
        RECEIPT_SCHEMA as IMAGE_BUILD_RECEIPT_SCHEMA,
        validated_build_receipt_binding,
    )
    from scripts.manfred_candidate_fleet_lock import hold_candidate_fleet_lock
    from scripts.materialize_release_authority_status import build_status
    from scripts.source_state_head import resolve_source_worktree_fingerprint
    from scripts.verify_deploy_context import verify as verify_deploy_context
    from scripts.verify_release_authority import validate_release_authority
    from scripts.verify_release_manifest_runtime_mode import (
        validate_release_contract as validate_release_runtime_mode,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from build_manfred_memorial_image import (  # type: ignore[no-redef]
        IMAGE_BUILD_AUTHORITY_BINDING_KEYS,
        IMAGE_BUILD_RECEIPT_MAX_BYTES,
        RECEIPT_SCHEMA as IMAGE_BUILD_RECEIPT_SCHEMA,
        validated_build_receipt_binding,
    )
    from manfred_candidate_fleet_lock import hold_candidate_fleet_lock
    from materialize_release_authority_status import build_status
    from source_state_head import resolve_source_worktree_fingerprint
    from verify_deploy_context import verify as verify_deploy_context
    from verify_release_authority import validate_release_authority
    from verify_release_manifest_runtime_mode import (
        validate_release_contract as validate_release_runtime_mode,
    )


LEGACY_RECEIPT_SCHEMA_V3 = "ea.manfred_memorial_candidate_projection.v3"
RECEIPT_SCHEMA = "ea.manfred_memorial_candidate_projection.v4"
MEMORIAL_SURFACE = "conversation_only"
SPATIAL_SCOPE = "separate_propertyquarry_lane"
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
PROPERTY_AUTHORIZED_SLUG = "360-tour-balkon-wohnung-in-neustift-layout-first-0146e6f9c6"
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
# Compatibility defaults for the low-level spatial intake helpers. Candidate
# preparation still requires both receipt paths explicitly, and the helpers
# continue to verify the exact pinned bytes, schemas, statuses, and digests.
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
CANDIDATE_RELEASE_AUTHORITY_SCHEMA = "ea.manfred_candidate_release_authority.v1"
CANDIDATE_RELEASE_AUTHORITY_DIRNAME = "release-authority"
CANDIDATE_RELEASE_AUTHORITY_CONTAINER_ROOT = Path("/data/release-authority")
CANDIDATE_RELEASE_AUTHORITY_FILENAMES = {
    "deploy_context": "deploy_context.generated.json",
    "project_modes": "PROJECT_MODES.generated.json",
    "release_manifest": "release_manifest.generated.json",
    "release_status": "release_authority_status.generated.json",
    "receipt": "candidate_release_authority.json",
}
OFFICIAL_EA_REMOTE_ORIGIN = "https://github.com/ArchonMegalon/executive-assistant.git"
OFFICIAL_EA_REMOTE_ORIGINS = frozenset({OFFICIAL_EA_REMOTE_ORIGIN})
LIVE_REMOTE_REF_EVIDENCE = "isolated_git_ls_remote_exact_https_ref"
PRIVATE_OUTPUT_MAX_BYTES = 8 * 1024 * 1024
CONVERSATION_RELEASE_DIRNAME = "conversation-release"
CONVERSATION_PREREQUISITES_FILENAME = (
    "manfred_realtime_conversation_release.generated.json"
)
CONVERSATION_READINESS_FILENAME = (
    "manfred_realtime_conversation_readiness.generated.json"
)
CONVERSATION_ROOM_FILENAME = (
    "memorial_room_audio_public_origin.generated.json"
)
CONVERSATION_PREREQUISITES_CONTAINER_PATH = (
    "/data/memorial_data/conversation-release/"
    + CONVERSATION_PREREQUISITES_FILENAME
)
CONVERSATION_EVIDENCE_FILENAMES = {
    "captured_candidate_diagnostic": (
        "memorial_stt_captured_candidate_diagnostic.generated.json"
    ),
    "realtime_browser": (
        "memorial_realtime_browser_public_origin.generated.json"
    ),
    "room_audio": CONVERSATION_ROOM_FILENAME,
    "room_audio_attestation_packet": (
        "memorial_room_audio_attestation_packet.generated.json"
    ),
    "stt_benchmark": "memorial_stt_provider_benchmark.generated.json",
    "stt_candidate": "memorial_stt_fixture_candidate.generated.json",
    "stt_captured_benchmark": (
        "memorial_stt_provider_benchmark_captured_candidate.generated.json"
    ),
    "voice_roundtrip": (
        "memorial_voice_roundtrip_public_origin.generated.json"
    ),
}
CONVERSATION_VERIFY_CONTRACT = (
    "ea.manfred_realtime_conversation_release.verify.v1"
)
MEMORIAL_ENABLED_PROJECT_MODES = ("MEMORIAL",)
CREDENTIAL_EXPOSURE_REMEDIATION_BLOCKER = (
    "credential_exposure_remediation_unverified"
)


def _require_credential_exposure_remediation() -> None:
    """Deny candidate work until canonical closure verification exists."""
    raise ValueError(CREDENTIAL_EXPOSURE_REMEDIATION_BLOCKER)


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
    timeout: int | None = None,
    environment: dict[str, str] | None = None,
) -> bytes:
    completed = subprocess.run(
        argv,
        cwd=str(cwd) if cwd else None,
        check=True,
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        env=environment,
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


def _commit_generated_at(source_root: Path, commit: str) -> str:
    try:
        raw = (
            _run(
                ["git", "show", "-s", "--format=%cI", commit],
                cwd=source_root,
            )
            .decode("ascii", errors="strict")
            .strip()
        )
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (OSError, UnicodeError, ValueError, subprocess.CalledProcessError) as exc:
        raise ValueError("manfred_candidate_commit_time_invalid") from exc
    if parsed.tzinfo is None:
        raise ValueError("manfred_candidate_commit_time_invalid")
    return (
        parsed.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


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
        return any(
            _spatial_payload_has_private_host_path(child) for child in value.values()
        )
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
            set(raw_binding) != {"path", "sha256", "size_bytes", "mime_type", "role"}
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

        def identity(metadata: os.stat_result) -> tuple[int, ...]:
            return (
                metadata.st_dev,
                metadata.st_ino,
                metadata.st_mode,
                metadata.st_nlink,
                metadata.st_size,
                metadata.st_mtime_ns,
                metadata.st_ctime_ns,
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
                    raise ValueError("manfred_candidate_spatial_root_invalid") from exc
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
    root: Path,
    *,
    require_sanitized_modes: bool,
    expected_root_identity: tuple[int, int] | None = None,
    expected_file_identities: dict[str, tuple[int, int]] | None = None,
) -> dict[str, bytes]:
    root = Path(os.path.abspath(os.fspath(root.expanduser())))
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise ValueError("manfred_candidate_spatial_nofollow_unavailable")
    directory_flags = os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | nofollow
    file_flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NONBLOCK", 0) | nofollow

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
            safe_mode = _safe_spatial_source_mode(metadata.st_mode, directory=True)
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
                raise ValueError("manfred_candidate_spatial_source_changed") from exc
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
                        raise ValueError("manfred_candidate_spatial_source_changed")
                    walk(child_descriptor, projected)
                    if directory_identity(opened) != directory_identity(
                        os.fstat(child_descriptor)
                    ):
                        raise ValueError("manfred_candidate_spatial_source_changed")
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
                    and not _safe_spatial_source_mode(initial.st_mode, directory=False)
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
                    or (
                        expected_file_identities is not None
                        and (opened.st_dev, opened.st_ino)
                        != expected_file_identities.get(relpath)
                    )
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
        if (
            expected_root_identity is not None
            and (
                root_metadata.st_dev,
                root_metadata.st_ino,
            )
            != expected_root_identity
        ):
            raise ValueError("manfred_candidate_spatial_root_identity_changed")
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
            directory_identity(root_metadata) != directory_identity(final_root_metadata)
            or directory_identity(final_root_metadata)
            != directory_identity(final_root_path_metadata)
            or (
                expected_root_identity is not None
                and (
                    final_root_metadata.st_dev,
                    final_root_metadata.st_ino,
                )
                != expected_root_identity
            )
        ):
            raise ValueError("manfred_candidate_spatial_source_changed")
    finally:
        os.close(root_descriptor)
    if not files:
        raise ValueError("manfred_candidate_spatial_bundle_empty")
    if expected_file_identities is not None and set(files) != set(
        expected_file_identities
    ):
        raise ValueError("manfred_candidate_spatial_source_changed")
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


def _property_review_evidence(
    snapshot: dict[str, bytes],
    *,
    final_review_receipt_path: Path,
    browser_review_receipt_path: Path,
) -> dict[str, object]:
    final_path = Path(
        os.path.abspath(os.fspath(final_review_receipt_path.expanduser()))
    )
    browser_path = Path(
        os.path.abspath(os.fspath(browser_review_receipt_path.expanduser()))
    )
    if final_path == browser_path:
        raise ValueError("manfred_candidate_spatial_review_evidence_invalid")
    final_bytes = _read_spatial_file_snapshot(final_path, require_sanitized_modes=False)
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
        or final.get("status") != "polished_review_candidate_pass_guarded_not_published"
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
            verification.get("independent_camera_geometry_accessibility_review") or {}
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
            "source_path": str(final_path),
        },
        "exact_viewer_browser": {
            "schema": str(browser["schema"]),
            "status": str(browser["status"]),
            "sha256": PROPERTY_BROWSER_REVIEW_SHA256,
            "source_path": str(browser_path),
        },
    }


def _validated_property_publication(
    *,
    snapshot: dict[str, bytes],
    authority_bytes: bytes,
    target_origin: str,
    final_review_receipt_path: Path,
    browser_review_receipt_path: Path,
) -> dict[str, object]:
    target_origin = _validate_public_base_url(target_origin)
    if len(authority_bytes) > MAX_SPATIAL_AUTHORITY_RECEIPT_BYTES:
        raise ValueError("manfred_candidate_spatial_authority_receipt_invalid")
    try:
        tour_bytes = snapshot["tour.json"]
        proof_bytes = snapshot["generated-reconstruction/reconstruction.json"]
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
    if tour_bytes != _canonical_json_bytes(
        tour
    ) or authority_bytes != _canonical_json_bytes(authority):
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
        or release.get("publication_authority_receipt_sha256") != authority_sha256
        or release.get("browser_receipt_sha256") != PROPERTY_BROWSER_REVIEW_SHA256
        or release.get("source_provenance_receipt_sha256")
        != PROPERTY_FINAL_REVIEW_SHA256
        or release.get("security_review_receipt_sha256") != PROPERTY_FINAL_REVIEW_SHA256
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
            not isinstance(label, str) or not label.strip() or label != label.strip()
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
        or authority.get("user_instruction_sha256") != PROPERTY_USER_INSTRUCTION_SHA256
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
    pre_authority_sha256 = _sha256(_canonical_json_bytes_without_lf(pre_authority))
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
    review_evidence = _property_review_evidence(
        snapshot,
        final_review_receipt_path=final_review_receipt_path,
        browser_review_receipt_path=browser_review_receipt_path,
    )
    review_contract = {
        name: {
            key: value for key, value in dict(row or {}).items() if key != "source_path"
        }
        for name, row in review_evidence.items()
    }
    if review_contract != authority_reviews:
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
    retain_as: str | None = None,
    retained_files: dict[str, tuple[int, tuple[int, int]]] | None = None,
) -> tuple[int, int]:
    if name in {"", ".", ".."} or "/" in name:
        raise ValueError("manfred_candidate_spatial_output_name_invalid")
    if (retain_as is None) != (retained_files is None):
        raise ValueError("manfred_candidate_spatial_retention_invalid")
    if retain_as is not None and retain_as in retained_files:
        raise ValueError("manfred_candidate_spatial_retention_invalid")
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
        identity = (metadata.st_dev, metadata.st_ino)
        if retain_as is not None and retained_files is not None:
            retained_files[retain_as] = (os.dup(descriptor), identity)
        return identity
    except BaseException as exc:
        cleanup_failed = False
        identity: tuple[int, int] | None = None
        try:
            metadata = os.fstat(descriptor)
            identity = (metadata.st_dev, metadata.st_ino)
            if not _quarantine_entry_nondestructive(
                parent_descriptor,
                name,
            ):
                cleanup_failed = True
        except (OSError, ValueError):
            cleanup_failed = True
        try:
            metadata = os.fstat(descriptor)
            if (
                identity is not None
                and (
                    metadata.st_dev,
                    metadata.st_ino,
                )
                != identity
            ):
                cleanup_failed = True
            os.ftruncate(descriptor, 0)
            os.fchmod(descriptor, 0o000)
            os.fsync(descriptor)
        except OSError:
            cleanup_failed = True
        if cleanup_failed:
            raise RuntimeError(
                "manfred_candidate_spatial_partial_output_rollback_incomplete"
            ) from exc
        raise
    finally:
        os.close(descriptor)


def _write_spatial_bundle_at(
    root_descriptor: int,
    files: dict[str, bytes],
    *,
    retained_files: dict[str, tuple[int, tuple[int, int]]] | None = None,
) -> None:
    directory_flags = (
        os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
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
                retain_as=relpath if retained_files is not None else None,
                retained_files=retained_files,
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


def _entry_identity(
    parent_descriptor: int,
    name: str,
    *,
    directory: bool,
) -> tuple[int, int] | None:
    try:
        metadata = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
    except OSError:
        return None
    expected_type = stat.S_ISDIR if directory else stat.S_ISREG
    if not expected_type(metadata.st_mode):
        return None
    return metadata.st_dev, metadata.st_ino


def _entry_exists_at(parent_descriptor: int, name: str) -> bool:
    try:
        os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
    except FileNotFoundError:
        return False
    return True


def _quarantine_entry_nondestructive(
    parent_descriptor: int,
    name: str,
    *,
    maximum_attempts: int = 16,
) -> bool:
    if name in {"", ".", ".."} or "/" in name:
        raise ValueError("manfred_candidate_spatial_output_name_invalid")
    for _attempt in range(maximum_attempts):
        if not _entry_exists_at(parent_descriptor, name):
            os.fsync(parent_descriptor)
            return not _entry_exists_at(parent_descriptor, name)
        quarantine_name = f".{name}.{uuid.uuid4().hex}.rollback"
        try:
            _rename_noreplace(
                parent_descriptor,
                name,
                parent_descriptor,
                quarantine_name,
            )
        except ValueError:
            if not _entry_exists_at(parent_descriptor, name):
                os.fsync(parent_descriptor)
                return True
            continue
        if not _entry_exists_at(parent_descriptor, quarantine_name):
            return False
        os.fsync(parent_descriptor)
    return not _entry_exists_at(parent_descriptor, name)


def _restore_quarantined_entry(
    parent_descriptor: int,
    quarantine_name: str,
    original_name: str,
) -> None:
    if (
        _entry_identity(
            parent_descriptor,
            original_name,
            directory=False,
        )
        is not None
        or _entry_identity(
            parent_descriptor,
            original_name,
            directory=True,
        )
        is not None
    ):
        return
    try:
        _rename_noreplace(
            parent_descriptor,
            quarantine_name,
            parent_descriptor,
            original_name,
        )
    except ValueError:
        return


def _remove_bundle_if_identity(
    parent_descriptor: int, name: str, identity: tuple[int, int]
) -> bool:
    if (
        _entry_identity(
            parent_descriptor,
            name,
            directory=True,
        )
        != identity
    ):
        return False
    quarantine_name = f".{name}.{uuid.uuid4().hex}.rollback"
    _rename_noreplace(
        parent_descriptor,
        name,
        parent_descriptor,
        quarantine_name,
    )
    if (
        _entry_identity(
            parent_descriptor,
            quarantine_name,
            directory=True,
        )
        != identity
    ):
        _restore_quarantined_entry(
            parent_descriptor,
            quarantine_name,
            name,
        )
        return False
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(
        quarantine_name,
        flags,
        dir_fd=parent_descriptor,
    )
    try:
        metadata = os.fstat(descriptor)
        if (metadata.st_dev, metadata.st_ino) != identity:
            _restore_quarantined_entry(
                parent_descriptor,
                quarantine_name,
                name,
            )
            return False
        current = os.stat(
            quarantine_name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        if (
            current.st_dev,
            current.st_ino,
        ) != identity or not stat.S_ISDIR(current.st_mode):
            raise ValueError("manfred_candidate_spatial_rollback_identity_drift")
        os.fchmod(descriptor, 0o000)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.fsync(parent_descriptor)
    return True


def _scrub_retained_spatial_files(
    retained_files: dict[str, tuple[int, tuple[int, int]]],
) -> bool:
    scrubbed = True
    for descriptor, identity in retained_files.values():
        try:
            metadata = os.fstat(descriptor)
            if (metadata.st_dev, metadata.st_ino) != identity or not stat.S_ISREG(
                metadata.st_mode
            ):
                scrubbed = False
                continue
            os.ftruncate(descriptor, 0)
            os.fchmod(descriptor, 0o000)
            os.fsync(descriptor)
            final = os.fstat(descriptor)
            if (
                (final.st_dev, final.st_ino) != identity
                or final.st_size != 0
                or stat.S_IMODE(final.st_mode) != 0o000
            ):
                scrubbed = False
        except OSError:
            scrubbed = False
    return scrubbed


def _unlink_file_if_identity(
    parent_descriptor: int, name: str, identity: tuple[int, int]
) -> bool:
    if (
        _entry_identity(
            parent_descriptor,
            name,
            directory=False,
        )
        != identity
    ):
        return False
    quarantine_name = f".{name}.{uuid.uuid4().hex}.rollback"
    _rename_noreplace(
        parent_descriptor,
        name,
        parent_descriptor,
        quarantine_name,
    )
    if (
        _entry_identity(
            parent_descriptor,
            quarantine_name,
            directory=False,
        )
        != identity
    ):
        _restore_quarantined_entry(
            parent_descriptor,
            quarantine_name,
            name,
        )
        return False
    flags = (
        os.O_WRONLY
        | os.O_CLOEXEC
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(
        quarantine_name,
        flags,
        dir_fd=parent_descriptor,
    )
    try:
        metadata = os.fstat(descriptor)
        if (metadata.st_dev, metadata.st_ino) != identity:
            _restore_quarantined_entry(
                parent_descriptor,
                quarantine_name,
                name,
            )
            return False
        os.ftruncate(descriptor, 0)
        os.fchmod(descriptor, 0o000)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    if (
        _entry_identity(
            parent_descriptor,
            quarantine_name,
            directory=False,
        )
        != identity
    ):
        return False
    os.fsync(parent_descriptor)
    return True


def _read_file_at_identity(
    parent_descriptor: int,
    name: str,
    identity: tuple[int, int],
    *,
    maximum: int,
) -> bytes:
    flags = (
        os.O_RDONLY
        | os.O_CLOEXEC
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(name, flags, dir_fd=parent_descriptor)
    try:
        metadata = os.fstat(descriptor)
        if (
            (metadata.st_dev, metadata.st_ino) != identity
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_size <= 0
            or metadata.st_size > maximum
        ):
            raise ValueError("manfred_candidate_spatial_output_identity_drift")
        chunks: list[bytes] = []
        remaining = int(metadata.st_size)
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                raise ValueError("manfred_candidate_spatial_output_identity_drift")
            chunks.append(chunk)
            remaining -= len(chunk)
        final = os.fstat(descriptor)
        if (
            final.st_dev,
            final.st_ino,
            final.st_size,
            final.st_mtime_ns,
            final.st_ctime_ns,
        ) != (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_size,
            metadata.st_mtime_ns,
            metadata.st_ctime_ns,
        ):
            raise ValueError("manfred_candidate_spatial_output_identity_drift")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def materialize_spatial_handoff(
    *,
    source_bundle_dir: Path,
    upstream_authority_receipt_path: Path,
    final_review_receipt_path: Path | None = None,
    browser_review_receipt_path: Path | None = None,
    handoff_bundle_dir: Path,
    handoff_receipt_path: Path,
    target_origin: str,
) -> dict[str, object]:
    source_bundle_dir = Path(os.path.abspath(os.fspath(source_bundle_dir.expanduser())))
    upstream_authority_receipt_path = Path(
        os.path.abspath(os.fspath(upstream_authority_receipt_path.expanduser()))
    )
    final_review_receipt_path = Path(
        os.path.abspath(
            os.fspath(
                (
                    final_review_receipt_path
                    if final_review_receipt_path is not None
                    else PROPERTY_FINAL_REVIEW_RECEIPT
                ).expanduser()
            )
        )
    )
    browser_review_receipt_path = Path(
        os.path.abspath(
            os.fspath(
                (
                    browser_review_receipt_path
                    if browser_review_receipt_path is not None
                    else PROPERTY_BROWSER_REVIEW_RECEIPT
                ).expanduser()
            )
        )
    )
    handoff_bundle_dir = Path(
        os.path.abspath(os.fspath(handoff_bundle_dir.expanduser()))
    )
    handoff_receipt_path = Path(
        os.path.abspath(os.fspath(handoff_receipt_path.expanduser()))
    )
    target_origin = _validate_public_base_url(target_origin)
    output_paths = (handoff_bundle_dir, handoff_receipt_path)
    property_inputs = (
        source_bundle_dir,
        upstream_authority_receipt_path,
        final_review_receipt_path,
        browser_review_receipt_path,
    )
    if handoff_bundle_dir.name != PROPERTY_AUTHORIZED_SLUG or any(
        output == property_input or property_input in output.parents
        for output in output_paths
        for property_input in property_inputs
    ):
        raise ValueError("manfred_candidate_spatial_materialization_target_invalid")
    # Intake may be operator-private (0700/0600) or group-readable/writable.
    # The stable descriptor snapshot rejects unsafe/world-writable inputs and
    # materialization below emits a detached, sanitized 0755/0644 projection.
    snapshot = _spatial_tree_snapshot(source_bundle_dir, require_sanitized_modes=False)
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
        final_review_receipt_path=final_review_receipt_path,
        browser_review_receipt_path=browser_review_receipt_path,
    )
    _verify_spatial_bundle_before_copy(source_bundle_dir, slug=str(validated["slug"]))
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
        "upstream_tour_manifest_sha256": validated["upstream_tour_manifest_sha256"],
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
    installed_identity: tuple[int, int] | None = None
    retained_files: dict[str, tuple[int, tuple[int, int]]] = {}
    retained_receipt: dict[str, tuple[int, tuple[int, int]]] = {}
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
            raise ValueError("manfred_candidate_spatial_output_staging_failed") from exc
        staging_metadata = os.fstat(staging_descriptor)
        staging_identity = (staging_metadata.st_dev, staging_metadata.st_ino)
        _write_spatial_bundle_at(
            staging_descriptor,
            snapshot,
            retained_files=retained_files,
        )
        if set(retained_files) != set(snapshot):
            raise ValueError("manfred_candidate_spatial_retention_invalid")
        retained_identities = {
            relpath: identity
            for relpath, (_descriptor, identity) in retained_files.items()
        }
        staging_path = handoff_bundle_dir.parent / temporary_name
        path_metadata = os.lstat(staging_path)
        if (path_metadata.st_dev, path_metadata.st_ino) != staging_identity:
            raise ValueError("manfred_candidate_spatial_output_parent_changed")
        _verify_spatial_bundle_before_copy(staging_path, slug=str(validated["slug"]))
        staged_snapshot = _spatial_tree_snapshot(
            staging_path,
            require_sanitized_modes=True,
            expected_root_identity=staging_identity,
            expected_file_identities=retained_identities,
        )
        if staged_snapshot != snapshot:
            raise ValueError("manfred_candidate_spatial_output_digest_drift")
        _rename_noreplace(
            bundle_parent_descriptor,
            temporary_name,
            bundle_parent_descriptor,
            handoff_bundle_dir.name,
        )
        bundle_installed = True
        installed_identity = _entry_identity(
            bundle_parent_descriptor,
            handoff_bundle_dir.name,
            directory=True,
        )
        if installed_identity is None:
            raise ValueError("manfred_candidate_spatial_output_install_drift")
        try:
            installed_snapshot = _spatial_tree_snapshot(
                handoff_bundle_dir,
                require_sanitized_modes=True,
                expected_root_identity=staging_identity,
                expected_file_identities=retained_identities,
            )
        except (OSError, ValueError) as exc:
            raise ValueError("manfred_candidate_spatial_output_install_drift") from exc
        if installed_identity != staging_identity or installed_snapshot != snapshot:
            raise ValueError("manfred_candidate_spatial_output_install_drift")
        os.fsync(bundle_parent_descriptor)
        receipt_identity = _exclusive_write_at(
            receipt_parent_descriptor,
            handoff_receipt_path.name,
            receipt_bytes,
            mode=0o600,
            retain_as=handoff_receipt_path.name,
            retained_files=retained_receipt,
        )
        if (
            set(retained_receipt) != {handoff_receipt_path.name}
            or retained_receipt[handoff_receipt_path.name][1] != receipt_identity
        ):
            raise ValueError("manfred_candidate_spatial_retention_invalid")
        if (
            _read_file_at_identity(
                receipt_parent_descriptor,
                handoff_receipt_path.name,
                receipt_identity,
                maximum=MAX_SPATIAL_AUTHORITY_RECEIPT_BYTES,
            )
            != receipt_bytes
        ):
            raise ValueError("manfred_candidate_spatial_output_receipt_drift")
        try:
            final_installed_snapshot = _spatial_tree_snapshot(
                handoff_bundle_dir,
                require_sanitized_modes=True,
                expected_root_identity=staging_identity,
                expected_file_identities=retained_identities,
            )
        except (OSError, ValueError) as exc:
            raise ValueError("manfred_candidate_spatial_output_install_drift") from exc
        if final_installed_snapshot != snapshot:
            raise ValueError("manfred_candidate_spatial_output_install_drift")
        os.fsync(receipt_parent_descriptor)
    except BaseException:
        rollback_failures: list[str] = []
        if receipt_identity is not None:
            receipt_cleanup_failed = False
            try:
                if not _quarantine_entry_nondestructive(
                    receipt_parent_descriptor,
                    handoff_receipt_path.name,
                ):
                    receipt_cleanup_failed = True
            except (OSError, ValueError):
                receipt_cleanup_failed = True
            if retained_receipt and not _scrub_retained_spatial_files(retained_receipt):
                receipt_cleanup_failed = True
            if receipt_cleanup_failed:
                rollback_failures.append("receipt")
        if retained_files and not _scrub_retained_spatial_files(retained_files):
            rollback_failures.append("staging_files")
        if staging_identity is not None:
            cleanup_name = (
                handoff_bundle_dir.name if bundle_installed else temporary_name
            )
            try:
                _remove_bundle_if_identity(
                    bundle_parent_descriptor,
                    cleanup_name,
                    staging_identity,
                )
                if not _quarantine_entry_nondestructive(
                    bundle_parent_descriptor,
                    cleanup_name,
                ):
                    rollback_failures.append("bundle")
            except (OSError, ValueError):
                rollback_failures.append("bundle")
        if staging_descriptor >= 0:
            try:
                os.fchmod(staging_descriptor, 0o000)
                os.fsync(staging_descriptor)
            except (OSError, ValueError):
                rollback_failures.append("staging")
        if rollback_failures:
            raise RuntimeError(
                "manfred_candidate_spatial_rollback_incomplete:"
                + ",".join(sorted(set(rollback_failures)))
            )
        raise
    finally:
        for descriptor, _identity in retained_receipt.values():
            os.close(descriptor)
        for descriptor, _identity in retained_files.values():
            os.close(descriptor)
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
    final_review_receipt_path: Path | None = None,
    browser_review_receipt_path: Path | None = None,
    target_origin: str,
) -> dict[str, object]:
    final_review_receipt_path = (
        final_review_receipt_path
        if final_review_receipt_path is not None
        else PROPERTY_FINAL_REVIEW_RECEIPT
    )
    browser_review_receipt_path = (
        browser_review_receipt_path
        if browser_review_receipt_path is not None
        else PROPERTY_BROWSER_REVIEW_RECEIPT
    )
    snapshot = _spatial_tree_snapshot(bundle_dir, require_sanitized_modes=True)
    authority_bytes = _read_spatial_file_snapshot(
        authority_receipt_path, require_sanitized_modes=False
    )
    if stat.S_IMODE(os.lstat(authority_receipt_path).st_mode) != 0o600:
        raise ValueError("manfred_candidate_spatial_authority_receipt_invalid")
    validated = _validated_property_publication(
        snapshot=snapshot,
        authority_bytes=authority_bytes,
        target_origin=target_origin,
        final_review_receipt_path=final_review_receipt_path,
        browser_review_receipt_path=browser_review_receipt_path,
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


def _read_regular_source(
    source: Path,
    *,
    maximum: int,
    missing_ok: bool = False,
) -> bytes | None:
    source = Path(os.path.abspath(os.fspath(source.expanduser())))
    parent_descriptor = _open_directory_path_nofollow(source.parent)

    def identity(metadata: os.stat_result) -> tuple[int, ...]:
        return (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_mode,
            metadata.st_nlink,
            metadata.st_uid,
            metadata.st_size,
            metadata.st_mtime_ns,
            metadata.st_ctime_ns,
        )

    try:
        try:
            initial = os.stat(
                source.name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            if missing_ok:
                return None
            raise ValueError("manfred_candidate_source_asset_missing") from None
        if (
            not stat.S_ISREG(initial.st_mode)
            or stat.S_ISLNK(initial.st_mode)
            or initial.st_uid != os.getuid()
            or initial.st_nlink != 1
            or stat.S_IMODE(initial.st_mode) & 0o002
            or initial.st_size <= 0
            or initial.st_size > maximum
        ):
            raise ValueError("manfred_candidate_source_asset_invalid")
        flags = (
            os.O_RDONLY
            | os.O_CLOEXEC
            | getattr(os, "O_NONBLOCK", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        try:
            descriptor = os.open(source.name, flags, dir_fd=parent_descriptor)
        except OSError as exc:
            raise ValueError("manfred_candidate_source_asset_invalid") from exc
        try:
            opened = os.fstat(descriptor)
            if identity(initial) != identity(opened):
                raise ValueError("manfred_candidate_source_asset_changed")
            chunks: list[bytes] = []
            remaining = int(opened.st_size)
            while remaining:
                chunk = os.read(descriptor, min(1024 * 1024, remaining))
                if not chunk:
                    raise ValueError("manfred_candidate_source_asset_changed")
                chunks.append(chunk)
                remaining -= len(chunk)
            if identity(opened) != identity(os.fstat(descriptor)):
                raise ValueError("manfred_candidate_source_asset_changed")
        finally:
            os.close(descriptor)
        try:
            final_path = os.stat(
                source.name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        except OSError as exc:
            raise ValueError("manfred_candidate_source_asset_changed") from exc
        if identity(initial) != identity(final_path):
            raise ValueError("manfred_candidate_source_asset_changed")
        return b"".join(chunks)
    finally:
        os.close(parent_descriptor)


def _image_build_authority_binding(
    receipt_path: Path,
    *,
    commit: str,
    image: str,
    image_id: str,
) -> dict[str, object]:
    normalized = Path(os.path.abspath(os.fspath(receipt_path.expanduser())))
    if not receipt_path.expanduser().is_absolute() or normalized.is_symlink():
        raise ValueError("manfred_candidate_image_build_receipt_path_invalid")
    try:
        metadata = os.lstat(normalized)
    except OSError as exc:
        raise ValueError("manfred_candidate_image_build_receipt_missing") from exc
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or metadata.st_nlink != 1
        or stat.S_IMODE(metadata.st_mode) != 0o600
    ):
        raise ValueError("manfred_candidate_image_build_receipt_private_invalid")
    try:
        encoded = _read_regular_source(
            normalized,
            maximum=IMAGE_BUILD_RECEIPT_MAX_BYTES,
        )
        if encoded is None:  # pragma: no cover - missing_ok is false
            raise ValueError("manfred_candidate_image_build_receipt_missing")
        binding = validated_build_receipt_binding(
            encoded,
            receipt_path=normalized,
            commit=commit,
            image_tag=image,
            image_id=image_id,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError("manfred_candidate_image_build_receipt_invalid") from exc
    if (
        set(binding) != IMAGE_BUILD_AUTHORITY_BINDING_KEYS
        or binding.get("receipt_schema") != IMAGE_BUILD_RECEIPT_SCHEMA
        or binding.get("receipt_path") != str(normalized)
        or binding.get("image_tag") != image
        or binding.get("image_id") != image_id
        or binding.get("runtime_source_revision") != commit
    ):
        raise ValueError("manfred_candidate_image_build_receipt_binding_invalid")
    return binding


def _copy_regular(
    source: Path, destination: Path, *, maximum: int, mode: int
) -> dict[str, object]:
    content = _read_regular_source(source, maximum=maximum)
    if content is None:  # pragma: no cover - missing_ok is false
        raise ValueError("manfred_candidate_source_asset_missing")
    _write_bytes(destination, content, mode=mode)
    return {"sha256": _sha256(content), "size_bytes": len(content)}


def _write_bytes(destination: Path, content: bytes, *, mode: int) -> dict[str, object]:
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination.write_bytes(content)
    destination.chmod(mode)
    return {"sha256": _sha256(content), "size_bytes": len(content)}


def _candidate_release_authority_paths(root: Path) -> dict[str, Path]:
    return {
        name: root / filename
        for name, filename in CANDIDATE_RELEASE_AUTHORITY_FILENAMES.items()
    }


def _candidate_release_authority_container_paths() -> dict[str, str]:
    return {
        name: str(CANDIDATE_RELEASE_AUTHORITY_CONTAINER_ROOT / filename)
        for name, filename in CANDIDATE_RELEASE_AUTHORITY_FILENAMES.items()
    }


def _candidate_remote_main_evidence(
    source_root: Path,
    *,
    commit: str,
) -> dict[str, object]:
    if _run(["git", "status", "--short"], cwd=source_root).strip():
        raise ValueError("manfred_candidate_release_source_dirty")
    head_commit = _commit(source_root, "HEAD")
    if head_commit != commit:
        raise ValueError("manfred_candidate_release_head_mismatch")
    remote_ref = "refs/remotes/origin/main"
    remote_commit = _commit(source_root, remote_ref)
    if remote_commit != commit:
        raise ValueError("manfred_candidate_release_remote_main_mismatch")
    try:
        configured_origin = (
            _run(["git", "remote", "get-url", "origin"], cwd=source_root)
            .decode("utf-8", errors="strict")
            .strip()
        )
    except (OSError, subprocess.CalledProcessError, UnicodeError) as exc:
        raise ValueError("manfred_candidate_release_remote_main_unverifiable") from exc
    if configured_origin not in OFFICIAL_EA_REMOTE_ORIGINS:
        raise ValueError("manfred_candidate_release_remote_origin_invalid")

    live_git_environment = {
        "GIT_ALLOW_PROTOCOL": "https",
        "GIT_ASKPASS": "/bin/false",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_PROTOCOL_FROM_USER": "0",
        "GIT_TERMINAL_PROMPT": "0",
        "HOME": os.sep,
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": os.environ.get("PATH") or os.defpath,
        "SSH_ASKPASS": "/bin/false",
    }
    try:
        _run(
            ["git", "merge-base", "--is-ancestor", commit, remote_ref],
            cwd=source_root,
        )
        live_output = (
            _run(
                [
                    "git",
                    "-c",
                    "protocol.allow=never",
                    "-c",
                    "protocol.https.allow=always",
                    "-c",
                    "credential.helper=",
                    "-c",
                    "core.askPass=",
                    "ls-remote",
                    "--exit-code",
                    OFFICIAL_EA_REMOTE_ORIGIN,
                    "refs/heads/main",
                ],
                cwd=Path(os.sep),
                timeout=30,
                environment=live_git_environment,
            )
            .decode("ascii", errors="strict")
            .strip()
        )
    except (
        OSError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        UnicodeError,
    ) as exc:
        raise ValueError("manfred_candidate_release_remote_main_unverifiable") from exc
    live_rows = live_output.splitlines()
    if len(live_rows) != 1:
        raise ValueError("manfred_candidate_release_remote_main_unverifiable")
    live_commit, separator, live_ref = live_rows[0].partition("\t")
    live_commit = live_commit.strip().lower()
    if (
        separator != "\t"
        or live_ref != "refs/heads/main"
        or not COMMIT_RE.fullmatch(live_commit)
        or live_commit != commit
    ):
        raise ValueError("manfred_candidate_release_live_main_mismatch")
    return {
        "source_head_commit_sha": head_commit,
        "source_head_matches_candidate_commit": True,
        "source_remote_ref": remote_ref,
        "source_remote_ref_commit_sha": remote_commit,
        "source_remote_ref_evidence": "local_remote_tracking_ref",
        "source_commit_reachable_from_remote_ref": True,
        "git_remote_origin": OFFICIAL_EA_REMOTE_ORIGIN,
        "live_remote_ref": live_ref,
        "live_remote_ref_commit_sha": live_commit,
        "live_remote_ref_evidence": LIVE_REMOTE_REF_EVIDENCE,
    }


def _materialize_candidate_release_authority(
    *,
    root: Path,
    source_root: Path,
    commit: str,
    image_id: str,
    image_revision: str,
    project_name: str,
    public_origin: str,
    generated_at: str,
    public_artifacts: list[str],
) -> dict[str, object]:
    if commit != image_revision or not COMMIT_RE.fullmatch(commit):
        raise ValueError("manfred_candidate_release_identity_mismatch")
    remote = _candidate_remote_main_evidence(source_root, commit=commit)
    deployment_id = f"{project_name}-{commit[:12]}"
    enabled_modes = list(MEMORIAL_ENABLED_PROJECT_MODES)
    compose_files = ["deploy/manfred-memorial/docker-compose.candidate.yml"]
    paths = _candidate_release_authority_paths(root)
    container_paths = _candidate_release_authority_container_paths()
    root.mkdir(parents=True, mode=0o700)

    tracked_modes = _strict_json_object(
        _git_blob(
            source_root,
            commit,
            ".codex-design/product/PROJECT_MODES.generated.json",
        ),
        error="manfred_candidate_release_project_modes_invalid",
    )
    declared_modes = {
        str(row.get("key") or "").strip()
        for row in list(tracked_modes.get("modes") or [])
        if isinstance(row, dict)
    }
    if tracked_modes.get("contract_name") != "ea.project_modes" or not set(
        enabled_modes
    ).issubset(declared_modes):
        raise ValueError("manfred_candidate_release_project_modes_invalid")
    project_modes = {
        **tracked_modes,
        "generated_at": generated_at,
        "generated_by": "scripts/prepare_manfred_memorial_candidate.py",
        "source_git_head": commit,
        "head_semantics": "candidate_release",
    }
    project_modes_bytes = _receipt_bytes(project_modes)
    _write_bytes(paths["project_modes"], project_modes_bytes, mode=0o444)

    deploy_context = {
        "contract_name": "ea.deploy_context.v1",
        "generated_by": "scripts/prepare_manfred_memorial_candidate.py",
        "generated_at": generated_at,
        "repository": "EA",
        "deployment_id": deployment_id,
        "deployment_id_source": "explicit",
        "public_origin": public_origin,
        "public_origin_source": "EA_PUBLIC_APP_BASE_URL",
        "branch": "main",
        "tracking_branch": "origin/main",
        "commit_sha": commit,
        "release_label": deployment_id,
        "project_mode": "MEMORIAL",
        "enabled_project_modes": enabled_modes,
        "compose_files": compose_files,
        "compose_overrides": [],
    }
    deploy_context_gate = verify_deploy_context(deploy_context=deploy_context)
    if deploy_context_gate.get("status") != "pass":
        raise ValueError("manfred_candidate_release_deploy_context_invalid")
    deploy_context_bytes = _receipt_bytes(deploy_context)
    _write_bytes(paths["deploy_context"], deploy_context_bytes, mode=0o444)

    artifacts = sorted(
        {str(value).strip() for value in public_artifacts if str(value).strip()}
    )
    if not artifacts:
        raise ValueError("manfred_candidate_release_artifacts_missing")
    release_manifest = {
        "contract_name": "ea.release_manifest.v1",
        "generated_at": generated_at,
        "generated_by": "scripts/prepare_manfred_memorial_candidate.py",
        "repository": "EA",
        "branch": "main",
        "tracking_branch": "origin/main",
        "commit_sha": commit,
        **remote,
        "dirty_worktree": False,
        "source_worktree_dirty": False,
        "source_dirty_count": 0,
        "source_dirty_files": [],
        "source_dirty_omitted_count": 0,
        "source_dirty_status_sha256": "",
        "deploy_context_generated_at": generated_at,
        "deploy_context_branch": "main",
        "deploy_context_tracking_branch": "origin/main",
        "deploy_context_commit_sha": commit,
        "deployment_id": deployment_id,
        "deployment_id_source": "explicit",
        "public_origin": public_origin,
        "public_origin_source": "EA_PUBLIC_APP_BASE_URL",
        "project_mode": "MEMORIAL",
        "enabled_project_modes": enabled_modes,
        "compose_files": compose_files,
        "compose_overrides": [],
        "artifact_set": artifacts,
        "release_label": deployment_id,
    }
    if validate_release_authority(
        release_manifest=release_manifest,
        project_modes=project_modes,
    ) or validate_release_runtime_mode(
        release_manifest=release_manifest,
        project_modes=project_modes,
        requested_mode="MEMORIAL",
        enabled_modes=enabled_modes,
        compose_overrides=[],
        manfred_composite_candidate_observed=True,
    ):
        raise ValueError("manfred_candidate_release_manifest_invalid")
    release_manifest_bytes = _receipt_bytes(release_manifest)
    _write_bytes(
        paths["release_manifest"],
        release_manifest_bytes,
        mode=0o444,
    )

    release_status = build_status(
        release_manifest_path=paths["release_manifest"],
        deploy_context_path=paths["deploy_context"],
        project_modes_path=paths["project_modes"],
        generated_at=generated_at,
    )
    release_status["manifest_path"] = container_paths["release_manifest"]
    release_status["deploy_context_path"] = container_paths["deploy_context"]
    release_status["project_modes_path"] = container_paths["project_modes"]
    gate = dict(release_status.get("gate") or {})
    gate["manifest_path"] = container_paths["release_manifest"]
    gate["deploy_context_path"] = container_paths["deploy_context"]
    gate["project_modes_path"] = container_paths["project_modes"]
    release_status["gate"] = gate
    release_status["candidate_runtime"] = True
    release_status["promotion_authority"] = False
    if (
        release_status.get("state") != "clear"
        or release_status.get("authority_posture") != "authoritative_runtime"
        or gate.get("status") != "pass"
        or release_status.get("commit_sha") != commit
        or release_status.get("deployment_id") != deployment_id
    ):
        raise ValueError("manfred_candidate_release_status_invalid")
    release_status_bytes = _receipt_bytes(release_status)
    _write_bytes(paths["release_status"], release_status_bytes, mode=0o444)

    document_bytes = {
        "deploy_context": deploy_context_bytes,
        "project_modes": project_modes_bytes,
        "release_manifest": release_manifest_bytes,
        "release_status": release_status_bytes,
    }
    receipt = {
        "schema": CANDIDATE_RELEASE_AUTHORITY_SCHEMA,
        "status": "pass",
        "generated_at": generated_at,
        "commit_sha": commit,
        "image_id": image_id,
        "image_revision": image_revision,
        "deployment_id": deployment_id,
        "project_mode": "MEMORIAL",
        "enabled_project_modes": enabled_modes,
        "container_paths": container_paths,
        "documents": {
            name: {
                "sha256": _sha256(content),
                "size_bytes": len(content),
            }
            for name, content in sorted(document_bytes.items())
        },
        "source_remote_ref": remote["source_remote_ref"],
        "source_remote_ref_commit_sha": remote["source_remote_ref_commit_sha"],
        "source_commit_reachable_from_remote_ref": True,
        "git_remote_origin": remote["git_remote_origin"],
        "live_remote_ref": remote["live_remote_ref"],
        "live_remote_ref_commit_sha": remote["live_remote_ref_commit_sha"],
        "live_remote_ref_evidence": remote["live_remote_ref_evidence"],
        "runtime_authority_state": "clear",
        "runtime_authority_posture": "authoritative_runtime",
        "promotion_authority": False,
        "secret_material_recorded": False,
    }
    receipt_bytes = _receipt_bytes(receipt)
    _write_bytes(paths["receipt"], receipt_bytes, mode=0o444)
    return _validate_candidate_release_authority_bundle(
        root,
        expected_commit=commit,
        expected_image_id=image_id,
        expected_project_name=project_name,
        expected_public_origin=public_origin,
    )


def _validate_candidate_release_authority_bundle(
    root: Path,
    *,
    expected_commit: str,
    expected_image_id: str,
    expected_project_name: str,
    expected_public_origin: str,
) -> dict[str, object]:
    normalized_root = root.resolve()
    if root.is_symlink() or not normalized_root.is_dir():
        raise ValueError("manfred_candidate_release_authority_root_invalid")
    paths = _candidate_release_authority_paths(normalized_root)
    if {path.name for path in normalized_root.iterdir()} != {
        path.name for path in paths.values()
    }:
        raise ValueError("manfred_candidate_release_authority_files_invalid")
    payloads: dict[str, dict[str, object]] = {}
    contents: dict[str, bytes] = {}
    for name, path in paths.items():
        metadata = path.lstat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_ISLNK(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_size <= 0
            or metadata.st_size > 8 * 1024 * 1024
        ):
            raise ValueError("manfred_candidate_release_authority_files_invalid")
        contents[name] = path.read_bytes()
        payloads[name] = _strict_json_object(
            contents[name],
            error="manfred_candidate_release_authority_json_invalid",
        )
    manifest = payloads["release_manifest"]
    project_modes = payloads["project_modes"]
    deploy_context = payloads["deploy_context"]
    status = payloads["release_status"]
    receipt = payloads["receipt"]
    expected_deployment_id = (
        f"{_validate_project_name(expected_project_name)}-{expected_commit[:12]}"
    )
    container_paths = _candidate_release_authority_container_paths()
    document_evidence = {
        name: {
            "sha256": _sha256(contents[name]),
            "size_bytes": len(contents[name]),
        }
        for name in (
            "deploy_context",
            "project_modes",
            "release_manifest",
            "release_status",
        )
    }
    if (
        not COMMIT_RE.fullmatch(expected_commit)
        or validate_release_authority(
            release_manifest=manifest,
            project_modes=project_modes,
        )
        or validate_release_runtime_mode(
            release_manifest=manifest,
            project_modes=project_modes,
            requested_mode="MEMORIAL",
            enabled_modes=list(MEMORIAL_ENABLED_PROJECT_MODES),
            compose_overrides=[],
            manfred_composite_candidate_observed=True,
        )
        or verify_deploy_context(deploy_context=deploy_context).get("status") != "pass"
        or manifest.get("commit_sha") != expected_commit
        or manifest.get("source_remote_ref_commit_sha") != expected_commit
        or manifest.get("source_commit_reachable_from_remote_ref") is not True
        or manifest.get("git_remote_origin") != OFFICIAL_EA_REMOTE_ORIGIN
        or manifest.get("live_remote_ref") != "refs/heads/main"
        or manifest.get("live_remote_ref_commit_sha") != expected_commit
        or manifest.get("live_remote_ref_evidence") != LIVE_REMOTE_REF_EVIDENCE
        or manifest.get("deployment_id") != expected_deployment_id
        or manifest.get("public_origin") != expected_public_origin
        or manifest.get("project_mode") != "MEMORIAL"
        or manifest.get("enabled_project_modes")
        != list(MEMORIAL_ENABLED_PROJECT_MODES)
        or manifest.get("compose_files")
        != ["deploy/manfred-memorial/docker-compose.candidate.yml"]
        or manifest.get("compose_overrides") != []
        or deploy_context.get("commit_sha") != expected_commit
        or deploy_context.get("deployment_id") != expected_deployment_id
        or deploy_context.get("public_origin") != expected_public_origin
        or deploy_context.get("compose_files")
        != ["deploy/manfred-memorial/docker-compose.candidate.yml"]
        or deploy_context.get("compose_overrides") != []
        or project_modes.get("source_git_head") != expected_commit
        or status.get("contract_name") != "ea.release_authority_status.v1"
        or status.get("state") != "clear"
        or status.get("authority_posture") != "authoritative_runtime"
        or status.get("commit_sha") != expected_commit
        or status.get("deployment_id") != expected_deployment_id
        or status.get("manifest_path") != container_paths["release_manifest"]
        or status.get("deploy_context_path") != container_paths["deploy_context"]
        or status.get("project_modes_path") != container_paths["project_modes"]
        or status.get("candidate_runtime") is not True
        or status.get("promotion_authority") is not False
        or dict(status.get("gate") or {}).get("status") != "pass"
        or receipt.get("schema") != CANDIDATE_RELEASE_AUTHORITY_SCHEMA
        or receipt.get("status") != "pass"
        or receipt.get("commit_sha") != expected_commit
        or receipt.get("image_id") != expected_image_id
        or receipt.get("image_revision") != expected_commit
        or receipt.get("deployment_id") != expected_deployment_id
        or receipt.get("git_remote_origin") != OFFICIAL_EA_REMOTE_ORIGIN
        or receipt.get("live_remote_ref") != "refs/heads/main"
        or receipt.get("live_remote_ref_commit_sha") != expected_commit
        or receipt.get("live_remote_ref_evidence") != LIVE_REMOTE_REF_EVIDENCE
        or receipt.get("container_paths") != container_paths
        or receipt.get("documents") != document_evidence
        or receipt.get("runtime_authority_state") != "clear"
        or receipt.get("runtime_authority_posture") != "authoritative_runtime"
        or receipt.get("promotion_authority") is not False
        or receipt.get("secret_material_recorded") is not False
    ):
        raise ValueError("manfred_candidate_release_authority_binding_invalid")
    return {
        "schema": CANDIDATE_RELEASE_AUTHORITY_SCHEMA,
        "status": "pass",
        "root": str(normalized_root),
        "commit_sha": expected_commit,
        "image_id": expected_image_id,
        "deployment_id": expected_deployment_id,
        "git_remote_origin": OFFICIAL_EA_REMOTE_ORIGIN,
        "live_remote_ref": "refs/heads/main",
        "live_remote_ref_commit_sha": expected_commit,
        "live_remote_ref_evidence": LIVE_REMOTE_REF_EVIDENCE,
        "project_mode": "MEMORIAL",
        "enabled_project_modes": list(MEMORIAL_ENABLED_PROJECT_MODES),
        "container_paths": container_paths,
        "documents": document_evidence,
        "runtime_authority_state": "clear",
        "runtime_authority_posture": "authoritative_runtime",
        "promotion_authority": False,
        "secret_material_recorded": False,
    }


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


def _read_private_output(
    path: Path,
    *,
    maximum: int = PRIVATE_OUTPUT_MAX_BYTES,
    missing_ok: bool = False,
) -> bytes | None:
    absolute = Path(os.path.abspath(os.fspath(path.expanduser())))
    if missing_ok and not os.path.lexists(absolute):
        return None
    flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(absolute, flags)
    except OSError as exc:
        raise ValueError("manfred_candidate_private_output_invalid") from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.getuid()
            or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_size <= 0
            or before.st_size > maximum
        ):
            raise ValueError("manfred_candidate_private_output_invalid")
        chunks: list[bytes] = []
        remaining = int(before.st_size)
        while remaining:
            chunk = os.read(descriptor, min(65536, remaining))
            if not chunk:
                raise ValueError("manfred_candidate_private_output_changed")
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    try:
        path_status = os.stat(absolute, follow_symlinks=False)
    except OSError as exc:
        raise ValueError("manfred_candidate_private_output_changed") from exc
    identity = (
        before.st_dev,
        before.st_ino,
        before.st_mode,
        before.st_nlink,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    )
    if identity != (
        after.st_dev,
        after.st_ino,
        after.st_mode,
        after.st_nlink,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    ) or (path_status.st_dev, path_status.st_ino) != (before.st_dev, before.st_ino):
        raise ValueError("manfred_candidate_private_output_changed")
    return b"".join(chunks)


def _install_private_output_noreplace(
    path: Path,
    content: bytes,
    *,
    conflict_error: str,
) -> bool:
    """Install private evidence once; return True only for exact-byte reuse."""

    if not content or len(content) > PRIVATE_OUTPUT_MAX_BYTES:
        raise ValueError("manfred_candidate_private_output_invalid")
    path = Path(os.path.abspath(os.fspath(path.expanduser())))
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    try:
        parent = path.parent.resolve(strict=True)
        parent_status = parent.stat()
    except OSError as exc:
        raise ValueError("manfred_candidate_private_output_parent_invalid") from exc
    if (
        parent != path.parent
        or not stat.S_ISDIR(parent_status.st_mode)
        or parent_status.st_uid != os.getuid()
        or stat.S_IMODE(parent_status.st_mode) & 0o022
    ):
        raise ValueError("manfred_candidate_private_output_parent_invalid")

    existing = _read_private_output(path, missing_ok=True)
    if existing is not None:
        if existing == content:
            return True
        raise ValueError(conflict_error)

    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=parent)
    temporary_path = Path(temporary)
    directory_descriptor = -1
    installed = False
    try:
        os.fchmod(descriptor, 0o600)
        view = memoryview(content)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise ValueError("manfred_candidate_private_output_write_failed")
            view = view[written:]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        directory_descriptor = os.open(
            parent,
            os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            _rename_noreplace(
                directory_descriptor,
                temporary_path.name,
                directory_descriptor,
                path.name,
            )
            installed = True
            temporary = ""
        except ValueError as exc:
            if str(exc) != "manfred_candidate_spatial_output_exists":
                raise ValueError(
                    "manfred_candidate_private_output_install_failed"
                ) from exc
            existing = _read_private_output(path)
            if existing != content:
                raise ValueError(conflict_error) from exc
        os.fsync(directory_descriptor)
        observed = _read_private_output(path)
        if observed != content:
            raise ValueError("manfred_candidate_private_output_changed")
        return not installed
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if directory_descriptor >= 0:
            os.close(directory_descriptor)
        if temporary:
            temporary_path.unlink(missing_ok=True)


def _parse_env_bytes(content: bytes) -> dict[str, str]:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("manfred_candidate_env_invalid") from exc
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError("manfred_candidate_env_invalid")
        key, value = line.split("=", 1)
        if (
            not key
            or any(
                character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"
                for character in key
            )
            or key in values
        ):
            raise ValueError("manfred_candidate_env_invalid")
        if "\x00" in value or "\n" in value or "\r" in value:
            raise ValueError("manfred_candidate_env_invalid")
        values[key] = value
    return values


def _parse_env(path: Path) -> dict[str, str]:
    content = _read_private_output(path, missing_ok=True)
    if content is None:
        return {}
    return _parse_env_bytes(content)


def _canonical_conversation_prerequisites_verification(
    *,
    receipt_path: Path,
    readiness_receipt_path: Path,
    readiness_evidence_root: Path,
    room_receipt_path: Path,
    tts_voice_path: Path,
    release_manifest_path: Path,
    release_authority_status_path: Path,
    project_modes_path: Path,
    expected_source_git_head: str,
    expected_source_state_fingerprint: str,
) -> dict[str, object]:
    try:
        module_root = Path(__file__).resolve().parents[1]
        if str(module_root) not in sys.path:
            sys.path.insert(0, str(module_root))
        from ea.scripts.manfred_realtime_conversation_release import (  # noqa: PLC0415
            verify_manfred_realtime_conversation_release,
        )

        result = verify_manfred_realtime_conversation_release(
            receipt_path=receipt_path,
            readiness_receipt_path=readiness_receipt_path,
            readiness_evidence_root=readiness_evidence_root,
            room_receipt_path=room_receipt_path,
            tts_voice_path=tts_voice_path,
            release_manifest_path=release_manifest_path,
            release_authority_status_path=release_authority_status_path,
            project_modes_path=project_modes_path,
            expected_source_git_head=expected_source_git_head,
            expected_source_state_fingerprint=(
                expected_source_state_fingerprint
            ),
        )
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        raise ValueError(
            "manfred_candidate_conversation_prerequisites_unverifiable"
        ) from exc
    expected = {
        "contract_name": CONVERSATION_VERIFY_CONTRACT,
        "status": "pass",
        "issues": [],
    }
    if result != expected:
        raise ValueError("manfred_candidate_conversation_prerequisites_not_pass")
    return dict(result)


def _stage_conversation_prerequisites(
    *,
    receipt_path: Path,
    evidence_root: Path,
    destination_root: Path,
    source_tts_voice_path: Path,
    staged_tts_voice_path: Path,
    authority_root: Path,
    expected_source_git_head: str,
    expected_source_state_fingerprint: str,
) -> dict[str, object]:
    if (
        not COMMIT_RE.fullmatch(expected_source_git_head)
        or not SHA256_RE.fullmatch(expected_source_state_fingerprint)
    ):
        raise ValueError("manfred_candidate_conversation_source_binding_invalid")
    normalized_receipt = Path(
        os.path.abspath(os.fspath(receipt_path.expanduser()))
    )
    normalized_evidence_root = Path(
        os.path.abspath(os.fspath(evidence_root.expanduser()))
    )
    readiness_path = normalized_evidence_root / CONVERSATION_READINESS_FILENAME
    room_path = normalized_evidence_root / CONVERSATION_ROOM_FILENAME
    authority_paths = _candidate_release_authority_paths(authority_root)
    verification_arguments = {
        "readiness_receipt_path": readiness_path,
        "readiness_evidence_root": normalized_evidence_root,
        "room_receipt_path": room_path,
        "release_manifest_path": authority_paths["release_manifest"],
        "release_authority_status_path": authority_paths["release_status"],
        "project_modes_path": authority_paths["project_modes"],
        "expected_source_git_head": expected_source_git_head,
        "expected_source_state_fingerprint": (
            expected_source_state_fingerprint
        ),
    }
    _canonical_conversation_prerequisites_verification(
        receipt_path=normalized_receipt,
        tts_voice_path=source_tts_voice_path,
        **verification_arguments,
    )

    source_files = {
        CONVERSATION_PREREQUISITES_FILENAME: normalized_receipt,
        CONVERSATION_READINESS_FILENAME: readiness_path,
        **{
            filename: normalized_evidence_root / filename
            for filename in CONVERSATION_EVIDENCE_FILENAMES.values()
        },
    }
    copied: dict[str, dict[str, object]] = {}
    for filename, source_path in sorted(source_files.items()):
        content = _read_regular_source(
            source_path,
            maximum=PRIVATE_OUTPUT_MAX_BYTES,
        )
        if content is None:  # pragma: no cover - missing_ok is false
            raise ValueError("manfred_candidate_source_asset_missing")
        copied[filename] = _write_bytes(
            destination_root / filename,
            content,
            mode=0o400,
        )

    staged_arguments = {
        **verification_arguments,
        "readiness_receipt_path": (
            destination_root / CONVERSATION_READINESS_FILENAME
        ),
        "readiness_evidence_root": destination_root,
        "room_receipt_path": destination_root / CONVERSATION_ROOM_FILENAME,
    }
    _canonical_conversation_prerequisites_verification(
        receipt_path=(
            destination_root / CONVERSATION_PREREQUISITES_FILENAME
        ),
        tts_voice_path=staged_tts_voice_path,
        **staged_arguments,
    )
    packet_bytes = _read_regular_source(
        destination_root / CONVERSATION_PREREQUISITES_FILENAME,
        maximum=PRIVATE_OUTPUT_MAX_BYTES,
    )
    if packet_bytes is None:  # pragma: no cover - missing_ok is false
        raise ValueError("manfred_candidate_source_asset_missing")
    packet = _strict_json_object(
        packet_bytes,
        error="manfred_candidate_conversation_prerequisites_invalid",
    )
    effective_expires_at = str(packet.get("effective_expires_at") or "").strip()
    if (
        packet.get("status") != "pass"
        or packet.get("conversation_prerequisites_pass") is not True
        or packet.get("source_git_head") != expected_source_git_head
        or packet.get("source_state_fingerprint")
        != expected_source_state_fingerprint
        or not effective_expires_at
    ):
        raise ValueError("manfred_candidate_conversation_prerequisites_invalid")
    return {
        "effective_expires_at": effective_expires_at,
        "packet_sha256": copied[CONVERSATION_PREREQUISITES_FILENAME][
            "sha256"
        ],
        "readiness_receipt_sha256": copied[CONVERSATION_READINESS_FILENAME][
            "sha256"
        ],
        "room_audio_receipt_sha256": copied[CONVERSATION_ROOM_FILENAME][
            "sha256"
        ],
        "evidence_sha256": {
            key: copied[filename]["sha256"]
            for key, filename in sorted(
                CONVERSATION_EVIDENCE_FILENAMES.items()
            )
        },
        "source_state_fingerprint": expected_source_state_fingerprint,
        "files": [
            {
                "path": f"{CONVERSATION_RELEASE_DIRNAME}/{filename}",
                **copied[filename],
            }
            for filename in sorted(copied)
        ],
    }


def _write_env(
    *,
    path: Path,
    image: str,
    release_root: Path,
    runtime_root: Path,
    public_base_url: str,
    host_port: int,
    project_name: str,
    commit: str,
    conversation_prerequisites_included: bool = False,
    rotate_secrets: bool = False,
) -> None:
    if not COMMIT_RE.fullmatch(commit):
        raise ValueError("manfred_candidate_commit_invalid")
    normalized_project_name = _validate_project_name(project_name)
    deployment_id = f"{normalized_project_name}-{commit[:12]}"
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
    values = {
        "EA_MANFRED_COMMIT": commit,
        "EA_MANFRED_COMPOSE_PROJECT": normalized_project_name,
        "EA_MANFRED_DEPLOYMENT_ID": deployment_id,
        "EA_MANFRED_IMAGE": image,
        "EA_MANFRED_ENV_FILE": str(path.resolve()),
        "EA_MANFRED_RELEASE_ROOT": str(release_root.resolve()),
        "EA_MANFRED_RELEASE_AUTHORITY_ROOT": str(
            (release_root / CANDIDATE_RELEASE_AUTHORITY_DIRNAME).resolve()
        ),
        "EA_MANFRED_RUNTIME_ROOT": str(runtime_root.resolve()),
        "EA_MANFRED_MEMORIAL_SURFACE": MEMORIAL_SURFACE,
        "EA_MANFRED_SPATIAL_SCOPE": SPATIAL_SCOPE,
        "EA_MEMORIAL_DEPLOYMENT_ID": deployment_id,
        "EA_MEMORIAL_CONVERSATION_PREREQUISITES_PATH": (
            CONVERSATION_PREREQUISITES_CONTAINER_PATH
        ),
        "EA_MEMORIAL_PUBLIC_VOICE_ACTIVATION": (
            "1" if conversation_prerequisites_included else "0"
        ),
        "EA_MEMORIAL_VOICE_PREVIEW_ENABLED": (
            "0" if conversation_prerequisites_included else "1"
        ),
        "EA_ENABLE_PUBLIC_MEMORIAL_OPERATOR_SURFACES": (
            "0" if conversation_prerequisites_included else "1"
        ),
        "EA_MANFRED_HOST_PORT": str(host_port),
        "EA_MANFRED_POSTGRES_PASSWORD": postgres_password,
        "DATABASE_URL": f"postgresql://ea:{postgres_password}@postgres:5432/ea",
        "EA_API_TOKEN": api_token,
        "EA_SIGNING_SECRET": signing_secret,
        "EA_PUBLIC_APP_BASE_URL": public_base_url,
    }
    encoded = "".join(f"{key}={values[key]}\n" for key in sorted(values)).encode(
        "utf-8"
    )
    _install_private_output_noreplace(
        path,
        encoded,
        conflict_error="manfred_candidate_env_existing_conflict",
    )


def _atomic_receipt(path: Path, payload: dict[str, object]) -> None:
    _install_private_output_noreplace(
        path,
        _receipt_bytes(payload),
        conflict_error="manfred_candidate_receipt_existing_conflict",
    )


def _hold_candidate_preparation_fleet_lock(function):  # type: ignore[no-untyped-def]
    @functools.wraps(function)
    def locked(*args, **kwargs):  # type: ignore[no-untyped-def]
        _require_credential_exposure_remediation()
        with hold_candidate_fleet_lock() as evidence:
            if evidence is None:  # pragma: no cover - raising mode
                raise RuntimeError("manfred_candidate_fleet_lock_held")
            return function(*args, **kwargs)

    return locked


@_hold_candidate_preparation_fleet_lock
def prepare_candidate(
    *,
    source_root: Path,
    ref: str,
    image: str,
    deploy_root: Path,
    public_base_url: str,
    host_port: int,
    project_name: str,
    image_build_receipt: Path | None = None,
    spatial_tour_bundle_dir: Path | None = None,
    spatial_authority_receipt: Path | None = None,
    spatial_final_review_receipt: Path | None = None,
    spatial_browser_review_receipt: Path | None = None,
    conversation_prerequisites_receipt: Path | None = None,
    conversation_evidence_root: Path | None = None,
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
    if (conversation_prerequisites_receipt is None) != (
        conversation_evidence_root is None
    ):
        raise ValueError(
            "manfred_candidate_conversation_prerequisites_inputs_incomplete"
        )
    if any(
        value is not None
        for value in (
            spatial_tour_bundle_dir,
            spatial_authority_receipt,
            spatial_final_review_receipt,
            spatial_browser_review_receipt,
        )
    ):
        raise ValueError(
            "manfred_candidate_spatial_inputs_forbidden_in_conversation_only"
        )
    commit = _commit(source_root, ref)
    image_id, image_commit = _image_revision(image)
    if image_commit != commit:
        raise ValueError("manfred_candidate_image_revision_mismatch")
    if image_build_receipt is None:
        raise ValueError("manfred_candidate_image_build_receipt_required")
    image_build_authority_binding = _image_build_authority_binding(
        image_build_receipt,
        commit=commit,
        image=image,
        image_id=image_id,
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
        voice_manifest_bytes = _read_regular_source(
            voice_manifest_path,
            maximum=8 * 1024 * 1024,
            missing_ok=True,
        )
        if voice_manifest_bytes is not None:
            try:
                voice_manifest = json.loads(voice_manifest_bytes)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError("manfred_candidate_voice_manifest_invalid") from exc
            if not isinstance(voice_manifest, dict):
                raise ValueError("manfred_candidate_voice_manifest_invalid")
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
        authority_generated_at = _commit_generated_at(source_root, commit)
        created_at = authority_generated_at
        public_release_artifacts = [
            str(row.get("path") or "")
            for row in file_receipts
            if str(row.get("path") or "").startswith(
                ("public_memorials/", "memorial_archive/")
            )
        ]
        authority_root = staging / CANDIDATE_RELEASE_AUTHORITY_DIRNAME
        _materialize_candidate_release_authority(
            root=authority_root,
            source_root=source_root,
            commit=commit,
            image_id=image_id,
            image_revision=image_commit,
            project_name=project_name,
            public_origin=public_base_url,
            generated_at=authority_generated_at,
            public_artifacts=public_release_artifacts,
        )
        conversation_prerequisites_included = (
            conversation_prerequisites_receipt is not None
        )
        conversation_prerequisites: dict[str, object] = {
            "effective_expires_at": "",
            "evidence_sha256": {},
            "files": [],
            "packet_sha256": "",
            "readiness_receipt_sha256": "",
            "room_audio_receipt_sha256": "",
            "source_state_fingerprint": "",
        }
        conversation_release_root = staging / CONVERSATION_RELEASE_DIRNAME
        conversation_release_root.mkdir(mode=0o700)
        if conversation_prerequisites_included:
            source_state_fingerprint = resolve_source_worktree_fingerprint(
                source_root
            )
            if not SHA256_RE.fullmatch(source_state_fingerprint):
                raise ValueError(
                    "manfred_candidate_conversation_source_fingerprint_invalid"
                )
            conversation_prerequisites = _stage_conversation_prerequisites(
                receipt_path=conversation_prerequisites_receipt,
                evidence_root=conversation_evidence_root,
                destination_root=conversation_release_root,
                source_tts_voice_path=private_source / "tts_voice.json",
                staged_tts_voice_path=private_root / "tts_voice.json",
                authority_root=authority_root,
                expected_source_git_head=commit,
                expected_source_state_fingerprint=source_state_fingerprint,
            )
        _set_modes(staging)
        _authority_digest, authority_files = _tree_digest(authority_root)
        file_receipts.extend(
            {
                "path": (f"{CANDIDATE_RELEASE_AUTHORITY_DIRNAME}/{row['path']}"),
                "sha256": row["sha256"],
                "size_bytes": row["size_bytes"],
            }
            for row in authority_files
        )
        projection_sha256, projected_files = _tree_digest(staging)
        conversation_projection_files = [
            dict(row)
            for row in projected_files
            if str(row.get("path") or "").startswith(
                f"{CONVERSATION_RELEASE_DIRNAME}/"
            )
        ]
        expected_conversation_files = list(
            conversation_prerequisites.get("files") or []
        )
        if conversation_prerequisites_included:
            expected_by_path = {
                str(row.get("path") or ""): {
                    "sha256": row.get("sha256"),
                    "size_bytes": row.get("size_bytes"),
                }
                for row in expected_conversation_files
                if isinstance(row, dict)
            }
            observed_by_path = {
                str(row.get("path") or ""): {
                    "sha256": row.get("sha256"),
                    "size_bytes": row.get("size_bytes"),
                }
                for row in conversation_projection_files
            }
            if (
                expected_by_path != observed_by_path
                or any(
                    row.get("mode") != "440"
                    for row in conversation_projection_files
                )
            ):
                raise ValueError(
                    "manfred_candidate_conversation_projection_mismatch"
                )
        elif conversation_projection_files:
            raise ValueError(
                "manfred_candidate_conversation_projection_unexpected"
            )
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
            commit=commit,
            conversation_prerequisites_included=(
                conversation_prerequisites_included
            ),
            rotate_secrets=rotate_secrets,
        )
        release_authority = _validate_candidate_release_authority_bundle(
            release_root / CANDIDATE_RELEASE_AUTHORITY_DIRNAME,
            expected_commit=commit,
            expected_image_id=image_id,
            expected_project_name=project_name,
            expected_public_origin=public_base_url,
        )
        receipt = {
            "schema": RECEIPT_SCHEMA,
            "status": "pass",
            "created_at": created_at,
            "commit": commit,
            "image": image,
            "image_id": image_id,
            "image_build_authority_binding": image_build_authority_binding,
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
            "memorial_surface": MEMORIAL_SURFACE,
            "spatial_scope": SPATIAL_SCOPE,
            "public_property_tours_packaged": False,
            "memorial_spatial_receipt_generated": False,
            "conversation_prerequisites_included": (
                conversation_prerequisites_included
            ),
            "public_voice_activation_intended": (
                conversation_prerequisites_included
            ),
            "conversation_prerequisites_effective_expires_at": (
                conversation_prerequisites["effective_expires_at"]
            ),
            "conversation_prerequisites_sha256": (
                conversation_prerequisites["packet_sha256"]
            ),
            "conversation_readiness_receipt_sha256": (
                conversation_prerequisites["readiness_receipt_sha256"]
            ),
            "conversation_room_audio_receipt_sha256": (
                conversation_prerequisites["room_audio_receipt_sha256"]
            ),
            "conversation_evidence_sha256": (
                conversation_prerequisites["evidence_sha256"]
            ),
            "conversation_source_state_fingerprint": (
                conversation_prerequisites["source_state_fingerprint"]
            ),
            "conversation_release_files": conversation_projection_files,
            "release_authority": release_authority,
            "release_authority_runtime_clear": True,
            "release_authority_promotion_authority": False,
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
        "--image-build-receipt",
        required=True,
        help="Required private canonical v3 image-build authority receipt.",
    )
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
        help="Rejected for the conversation-only Memorial contract; use the separate PropertyQuarry lane.",
    )
    parser.add_argument(
        "--spatial-authority-receipt",
        help="Rejected for the conversation-only Memorial contract.",
    )
    parser.add_argument(
        "--spatial-final-review-receipt",
        help="Rejected for the conversation-only Memorial contract.",
    )
    parser.add_argument(
        "--spatial-browser-review-receipt",
        help="Rejected for the conversation-only Memorial contract.",
    )
    parser.add_argument(
        "--conversation-prerequisites-receipt",
        help=(
            "Optional private canonical Manfred conversation-prerequisites "
            "packet; requires --conversation-evidence-root."
        ),
    )
    parser.add_argument(
        "--conversation-evidence-root",
        help=(
            "Trusted directory containing the exact readiness, room, and "
            "eight evidence receipts bound by the prerequisites packet."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        receipt = prepare_candidate(
            source_root=Path(args.source_root),
            ref=args.ref,
            image=args.image,
            image_build_receipt=Path(args.image_build_receipt),
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
            spatial_final_review_receipt=(
                Path(args.spatial_final_review_receipt)
                if args.spatial_final_review_receipt
                else None
            ),
            spatial_browser_review_receipt=(
                Path(args.spatial_browser_review_receipt)
                if args.spatial_browser_review_receipt
                else None
            ),
            conversation_prerequisites_receipt=(
                Path(args.conversation_prerequisites_receipt)
                if args.conversation_prerequisites_receipt
                else None
            ),
            conversation_evidence_root=(
                Path(args.conversation_evidence_root)
                if args.conversation_evidence_root
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
