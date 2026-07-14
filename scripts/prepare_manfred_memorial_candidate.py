#!/usr/bin/env python3
from __future__ import annotations

import argparse
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
SPATIAL_AUTHORITY_SCHEMA = "ea.manfred_spatial_handoff_authority.v1"
SPATIAL_PROJECTION_SCHEMA = "ea.manfred_memorial_spatial_projection.v1"
SPATIAL_AUTHORITY_SCOPE = "candidate_spatial_handoff"
SPATIAL_MANIFEST_NORMALIZATION = (
    "canonical-json-utf8-lf-sort-keys-compact-with-"
    "generated_viewer_release.publication_authority_receipt_sha256-null"
)
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
SPATIAL_MANIFEST_PUBLIC_KEYS = {
    "brand_name",
    "brief",
    "creation_mode",
    "display_title",
    "facts",
    "generated_reconstruction",
    "generated_viewer_release",
    "privacy_mode",
    "scene_count",
    "scene_strategy",
    "scenes",
    "slug",
    "title",
    "tour_privacy_mode",
    "tour_title",
    "variant_key",
    "variant_label",
}
SPATIAL_PRIVATE_KEYS = {
    "actor",
    "api_key",
    "auth_header",
    "authorization",
    "cookie",
    "cookies",
    "debug",
    "external_id",
    "headers",
    "internal_ref",
    "owner_id",
    "person_id",
    "principal_id",
    "private_recipient_email",
    "raw_signal_json",
    "recipient",
    "recipient_email",
    "recipient_name",
    "recipient_phone",
    "refresh_token",
    "runtime_inputs_json",
    "session",
    "source_ref",
    "token",
}
SPATIAL_PRIVATE_KEY_MARKERS = (
    "access_token",
    "api_key",
    "auth_header",
    "cookie",
    "credential",
    "private",
    "recipient",
    "refresh_token",
    "secret",
)
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


def _spatial_redact_value(value: object) -> object:
    if isinstance(value, dict):
        redacted: dict[str, object] = {}
        for raw_key, child in value.items():
            key = str(raw_key or "").strip()
            lowered = key.lower()
            if (
                not key
                or lowered in SPATIAL_PRIVATE_KEYS
                or any(marker in lowered for marker in SPATIAL_PRIVATE_KEY_MARKERS)
            ):
                continue
            redacted[key] = _spatial_redact_value(child)
        return redacted
    if isinstance(value, list):
        return [_spatial_redact_value(child) for child in value]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    raise ValueError("manfred_candidate_spatial_manifest_value_invalid")


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
    for raw_binding in bindings_raw:
        if not isinstance(raw_binding, dict):
            raise ValueError("manfred_candidate_spatial_asset_allowlist_invalid")
        path = _safe_relative(raw_binding.get("path")).as_posix()
        role = str(raw_binding.get("role") or "").strip().lower()
        if (
            not path.startswith("generated-reconstruction/")
            or _spatial_path_has_private_raw_pattern(path)
            or role not in SPATIAL_LAYOUT_ROLE_COUNTS
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


def _sanitized_spatial_manifest(
    payload: dict[str, object], *, authority_receipt_sha256: str | None
) -> dict[str, object]:
    slug, _paths, _viewer, _proof = _spatial_release_contract(payload)
    sanitized: dict[str, object] = {}
    for key in sorted(SPATIAL_MANIFEST_PUBLIC_KEYS):
        if key in payload:
            sanitized[key] = _spatial_redact_value(payload[key])
    sanitized["slug"] = slug
    sanitized["facts"] = {}
    sanitized["scenes"] = []
    sanitized["scene_count"] = 0
    sanitized["tour_privacy_mode"] = "anonymous_public"
    release = sanitized.get("generated_viewer_release")
    if not isinstance(release, dict):
        raise ValueError("manfred_candidate_spatial_release_contract_invalid")
    release["publication_authority_receipt_sha256"] = authority_receipt_sha256
    if release.get("publication_authority_verified") is not True:
        raise ValueError("manfred_candidate_spatial_authority_not_verified")
    if str(sanitized.get("scene_strategy") or "").strip() == (
        "generated_listing_summary"
    ) or str(sanitized.get("creation_mode") or "").strip() == (
        "hosted_listing_fallback"
    ):
        raise ValueError("manfred_candidate_spatial_fallback_forbidden")
    return sanitized


def _spatial_pre_authority_manifest_bytes(payload: dict[str, object]) -> bytes:
    return _canonical_json_bytes(
        _sanitized_spatial_manifest(payload, authority_receipt_sha256=None)
    )


def _safe_spatial_source_mode(mode: int, *, directory: bool) -> bool:
    normalized = stat.S_IMODE(mode)
    if normalized & 0o7000 or normalized & 0o002:
        return False
    if directory:
        return bool(normalized & 0o500 == 0o500)
    return bool(normalized & 0o400)


def _read_spatial_file_snapshot(path: Path, *, require_sanitized_modes: bool) -> bytes:
    try:
        initial = path.lstat()
    except OSError as exc:
        raise ValueError("manfred_candidate_spatial_source_invalid") from exc
    expected_mode = 0o644
    if (
        not stat.S_ISREG(initial.st_mode)
        or stat.S_ISLNK(initial.st_mode)
        or initial.st_nlink != 1
        or initial.st_size <= 0
        or initial.st_size > MAX_SPATIAL_FILE_BYTES
        or (require_sanitized_modes and stat.S_IMODE(initial.st_mode) != expected_mode)
        or (
            not require_sanitized_modes
            and not _safe_spatial_source_mode(initial.st_mode, directory=False)
        )
    ):
        raise ValueError("manfred_candidate_spatial_source_invalid")
    flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NONBLOCK", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ValueError("manfred_candidate_spatial_source_invalid") from exc
    try:
        opened = os.fstat(descriptor)
        identity = (
            initial.st_dev,
            initial.st_ino,
            initial.st_mode,
            initial.st_nlink,
            initial.st_size,
            initial.st_mtime_ns,
            initial.st_ctime_ns,
        )
        opened_identity = (
            opened.st_dev,
            opened.st_ino,
            opened.st_mode,
            opened.st_nlink,
            opened.st_size,
            opened.st_mtime_ns,
            opened.st_ctime_ns,
        )
        if identity != opened_identity:
            raise ValueError("manfred_candidate_spatial_source_changed")
        chunks: list[bytes] = []
        remaining = int(opened.st_size)
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                raise ValueError("manfred_candidate_spatial_source_changed")
            chunks.append(chunk)
            remaining -= len(chunk)
        final = os.fstat(descriptor)
        final_identity = (
            final.st_dev,
            final.st_ino,
            final.st_mode,
            final.st_nlink,
            final.st_size,
            final.st_mtime_ns,
            final.st_ctime_ns,
        )
        if final_identity != opened_identity:
            raise ValueError("manfred_candidate_spatial_source_changed")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _spatial_tree_snapshot(
    root: Path, *, require_sanitized_modes: bool
) -> dict[str, bytes]:
    root = Path(os.path.abspath(os.fspath(root.expanduser())))
    try:
        root_metadata = root.lstat()
    except OSError as exc:
        raise ValueError("manfred_candidate_spatial_root_invalid") from exc
    if (
        not stat.S_ISDIR(root_metadata.st_mode)
        or stat.S_ISLNK(root_metadata.st_mode)
        or (require_sanitized_modes and stat.S_IMODE(root_metadata.st_mode) != 0o755)
        or (
            not require_sanitized_modes
            and not _safe_spatial_source_mode(root_metadata.st_mode, directory=True)
        )
    ):
        raise ValueError("manfred_candidate_spatial_root_invalid")
    files: dict[str, bytes] = {}
    total_bytes = 0

    def walk(directory: Path, relative: tuple[str, ...]) -> None:
        nonlocal total_bytes
        try:
            entries = sorted(os.scandir(directory), key=lambda item: item.name)
        except OSError as exc:
            raise ValueError("manfred_candidate_spatial_source_invalid") from exc
        for entry in entries:
            if entry.name in {"", ".", ".."} or "/" in entry.name:
                raise ValueError("manfred_candidate_spatial_path_invalid")
            path = Path(entry.path)
            metadata = path.lstat()
            projected = (*relative, entry.name)
            relpath = PurePosixPath(*projected).as_posix()
            if stat.S_ISLNK(metadata.st_mode):
                raise ValueError("manfred_candidate_spatial_symlink_forbidden")
            if stat.S_ISDIR(metadata.st_mode):
                if (
                    require_sanitized_modes and stat.S_IMODE(metadata.st_mode) != 0o755
                ) or (
                    not require_sanitized_modes
                    and not _safe_spatial_source_mode(metadata.st_mode, directory=True)
                ):
                    raise ValueError("manfred_candidate_spatial_mode_invalid")
                walk(path, projected)
                continue
            if not stat.S_ISREG(metadata.st_mode):
                raise ValueError("manfred_candidate_spatial_nonregular_forbidden")
            content = _read_spatial_file_snapshot(
                path, require_sanitized_modes=require_sanitized_modes
            )
            files[relpath] = content
            total_bytes += len(content)
            if (
                len(files) > MAX_SPATIAL_SOURCE_FILES
                or total_bytes > MAX_SPATIAL_SOURCE_BYTES
            ):
                raise ValueError("manfred_candidate_spatial_bundle_oversize")

    walk(root, ())
    if not files:
        raise ValueError("manfred_candidate_spatial_bundle_empty")
    return files


def _write_spatial_bundle(root: Path, *, slug: str, files: dict[str, bytes]) -> Path:
    bundle = root / slug
    bundle.mkdir(parents=True, mode=0o755)
    bundle.chmod(0o755)
    for relpath, content in sorted(files.items()):
        target = bundle / _safe_relative(relpath)
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
        cursor = target.parent
        while cursor != root:
            cursor.chmod(0o755)
            cursor = cursor.parent
        target.write_bytes(content)
        target.chmod(0o644)
    root.chmod(0o755)
    return bundle


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


def _validated_authority_receipt(
    path: Path,
    *,
    slug: str,
    target_origin: str,
    transformed_manifest_pre_authority_sha256: str,
    asset_paths: list[str],
) -> tuple[dict[str, object], bytes]:
    content = _read_spatial_file_snapshot(path, require_sanitized_modes=False)
    metadata = path.lstat()
    if (
        stat.S_IMODE(metadata.st_mode) != 0o600
        or len(content) > MAX_SPATIAL_AUTHORITY_RECEIPT_BYTES
    ):
        raise ValueError("manfred_candidate_spatial_authority_receipt_invalid")
    try:
        payload = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("manfred_candidate_spatial_authority_receipt_invalid") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema") != SPATIAL_AUTHORITY_SCHEMA
        or payload.get("status") != "pass"
        or payload.get("scope") != SPATIAL_AUTHORITY_SCOPE
        or payload.get("candidate_handoff_authorized") is not True
        or payload.get("public_activation_authority") is not False
        or payload.get("slug") != slug
        or payload.get("target_origin") != target_origin
        or payload.get("normalization") != SPATIAL_MANIFEST_NORMALIZATION
        or payload.get("transformed_manifest_pre_authority_sha256")
        != transformed_manifest_pre_authority_sha256
        or payload.get("asset_paths") != asset_paths
        or not COMMIT_RE.fullmatch(str(payload.get("source_commit") or ""))
        or not SHA256_RE.fullmatch(str(payload.get("user_instruction_sha256") or ""))
    ):
        raise ValueError("manfred_candidate_spatial_authority_receipt_mismatch")
    return payload, content


def materialize_spatial_handoff_authority(
    *,
    source_bundle_dir: Path,
    sanitized_bundle_dir: Path,
    authority_receipt_path: Path,
    slug: str,
    source_commit: str,
    target_origin: str,
    user_instruction_sha256: str,
) -> dict[str, object]:
    source_bundle_dir = Path(os.path.abspath(os.fspath(source_bundle_dir.expanduser())))
    sanitized_bundle_dir = Path(
        os.path.abspath(os.fspath(sanitized_bundle_dir.expanduser()))
    )
    authority_receipt_path = Path(
        os.path.abspath(os.fspath(authority_receipt_path.expanduser()))
    )
    if not COMMIT_RE.fullmatch(str(source_commit or "").strip().lower()):
        raise ValueError("manfred_candidate_spatial_source_commit_invalid")
    source_commit = str(source_commit).strip().lower()
    if not SHA256_RE.fullmatch(str(user_instruction_sha256 or "").strip().lower()):
        raise ValueError("manfred_candidate_spatial_instruction_digest_invalid")
    user_instruction_sha256 = str(user_instruction_sha256).strip().lower()
    target_origin = _validate_public_base_url(target_origin)
    if (
        sanitized_bundle_dir.name != slug
        or sanitized_bundle_dir == source_bundle_dir
        or source_bundle_dir in sanitized_bundle_dir.parents
        or authority_receipt_path == source_bundle_dir
        or source_bundle_dir in authority_receipt_path.parents
    ):
        raise ValueError("manfred_candidate_spatial_materialization_target_invalid")
    if sanitized_bundle_dir.exists() or authority_receipt_path.exists():
        raise ValueError("manfred_candidate_spatial_materialization_target_exists")
    snapshot = _spatial_tree_snapshot(source_bundle_dir, require_sanitized_modes=False)
    try:
        raw_payload = json.loads(snapshot["tour.json"])
    except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("manfred_candidate_spatial_manifest_invalid") from exc
    if not isinstance(raw_payload, dict):
        raise ValueError("manfred_candidate_spatial_manifest_invalid")
    observed_slug, asset_paths, _viewer, _proof = _spatial_release_contract(
        raw_payload, expected_slug=slug
    )
    allowed_paths = {"tour.json", *asset_paths}
    missing = allowed_paths - set(snapshot)
    if missing or any(
        _spatial_path_has_private_raw_pattern(path) for path in set(snapshot)
    ):
        raise ValueError("manfred_candidate_spatial_asset_allowlist_invalid")
    pre_authority = _spatial_pre_authority_manifest_bytes(raw_payload)
    pre_authority_sha256 = _sha256(pre_authority)
    receipt = {
        "schema": SPATIAL_AUTHORITY_SCHEMA,
        "status": "pass",
        "scope": SPATIAL_AUTHORITY_SCOPE,
        "candidate_handoff_authorized": True,
        "public_activation_authority": False,
        "slug": observed_slug,
        "source_commit": source_commit,
        "target_origin": target_origin,
        "user_instruction_sha256": user_instruction_sha256,
        "normalization": SPATIAL_MANIFEST_NORMALIZATION,
        "transformed_manifest_pre_authority_sha256": pre_authority_sha256,
        "asset_paths": asset_paths,
    }
    authority_bytes = _receipt_bytes(receipt)
    authority_sha256 = _sha256(authority_bytes)
    final_manifest = _canonical_json_bytes(
        _sanitized_spatial_manifest(
            raw_payload,
            authority_receipt_sha256=authority_sha256,
        )
    )
    selected = {path: snapshot[path] for path in asset_paths}
    selected["tour.json"] = final_manifest
    sanitized_bundle_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary_root = Path(
        tempfile.mkdtemp(
            prefix=f".{sanitized_bundle_dir.name}.",
            dir=str(sanitized_bundle_dir.parent),
        )
    )
    receipt_installed = False
    bundle_installed = False
    try:
        staged_bundle = _write_spatial_bundle(
            temporary_root, slug=observed_slug, files=selected
        )
        _verify_spatial_bundle_before_copy(staged_bundle, slug=observed_slug)
        authority_receipt_path.parent.mkdir(parents=True, exist_ok=True)
        _write_bytes(authority_receipt_path, authority_bytes, mode=0o600)
        receipt_installed = True
        os.replace(staged_bundle, sanitized_bundle_dir)
        bundle_installed = True
        shutil.rmtree(temporary_root)
    except BaseException:
        if receipt_installed:
            authority_receipt_path.unlink(missing_ok=True)
        if bundle_installed and sanitized_bundle_dir.is_dir():
            shutil.rmtree(sanitized_bundle_dir)
        raise
    finally:
        if temporary_root.exists():
            shutil.rmtree(temporary_root)
    return {
        **receipt,
        "authority_receipt_path": str(authority_receipt_path.resolve()),
        "authority_receipt_sha256": authority_sha256,
        "sanitized_bundle_dir": str(sanitized_bundle_dir.resolve()),
        "sanitized_file_count": len(selected),
    }


def _validated_spatial_handoff_input(
    *,
    bundle_dir: Path,
    authority_receipt_path: Path,
    target_origin: str,
) -> dict[str, object]:
    snapshot = _spatial_tree_snapshot(bundle_dir, require_sanitized_modes=True)
    try:
        payload = json.loads(snapshot["tour.json"])
    except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("manfred_candidate_spatial_manifest_invalid") from exc
    if not isinstance(payload, dict):
        raise ValueError("manfred_candidate_spatial_manifest_invalid")
    slug, asset_paths, viewer_relpath, proof_relpath = _spatial_release_contract(
        payload
    )
    if bundle_dir.name != slug:
        raise ValueError("manfred_candidate_spatial_slug_invalid")
    if set(snapshot) != {"tour.json", *asset_paths} or len(snapshot) != 6:
        raise ValueError("manfred_candidate_spatial_asset_allowlist_invalid")
    final_manifest = _canonical_json_bytes(
        _sanitized_spatial_manifest(
            payload,
            authority_receipt_sha256=str(
                dict(payload.get("generated_viewer_release") or {}).get(
                    "publication_authority_receipt_sha256"
                )
                or ""
            ),
        )
    )
    if snapshot["tour.json"] != final_manifest:
        raise ValueError("manfred_candidate_spatial_manifest_not_canonical")
    pre_authority_sha256 = _sha256(_spatial_pre_authority_manifest_bytes(payload))
    authority_payload, authority_bytes = _validated_authority_receipt(
        authority_receipt_path,
        slug=slug,
        target_origin=target_origin,
        transformed_manifest_pre_authority_sha256=pre_authority_sha256,
        asset_paths=asset_paths,
    )
    authority_sha256 = _sha256(authority_bytes)
    release = dict(payload.get("generated_viewer_release") or {})
    if release.get("publication_authority_receipt_sha256") != authority_sha256:
        raise ValueError("manfred_candidate_spatial_authority_digest_mismatch")
    verifier_receipt = _verify_spatial_bundle_before_copy(bundle_dir, slug=slug)
    return {
        "included": True,
        "slug": slug,
        "files": snapshot,
        "asset_paths": asset_paths,
        "viewer_relpath": viewer_relpath,
        "proof_relpath": proof_relpath,
        "authority_receipt": authority_payload,
        "authority_receipt_sha256": authority_sha256,
        "transformed_manifest_pre_authority_sha256": pre_authority_sha256,
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
        "authority_receipt": {},
        "authority_receipt_sha256": "",
        "transformed_manifest_pre_authority_sha256": "",
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
            "authority_receipt": dict(spatial_handoff.get("authority_receipt") or {}),
            "authority_receipt_sha256": str(
                spatial_handoff.get("authority_receipt_sha256") or ""
            ),
            "transformed_manifest_pre_authority_sha256": str(
                spatial_handoff.get("transformed_manifest_pre_authority_sha256") or ""
            ),
            "normalization": (
                SPATIAL_MANIFEST_NORMALIZATION
                if spatial_handoff.get("included")
                else ""
            ),
            "source_verifier": dict(spatial_handoff.get("verifier_receipt") or {}),
            "candidate_handoff_only": True,
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
            "spatial_public_activation_authority": False,
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
        help="Optional exact sanitized six-file generated-viewer bundle.",
    )
    parser.add_argument(
        "--spatial-authority-receipt",
        help="Mode-0600 candidate-scoped authority receipt paired with the bundle.",
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
