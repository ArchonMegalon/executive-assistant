from __future__ import annotations

"""Fail-closed runtime binding for the Manfred operator voice preview.

The preview session is deliberately bound to the candidate release-authority
packet mounted with the Memorial data.  Environment variables select the
packet files but never supply the release identity returned by this module.
"""

import hashlib
import ipaddress
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

_MAX_DOCUMENT_BYTES = 8 * 1024 * 1024
_OFFICIAL_REMOTE = "https://github.com/ArchonMegalon/executive-assistant.git"
_LIVE_REMOTE_EVIDENCE = "isolated_git_ls_remote_exact_https_ref"
_PACKAGED_CONTAINER_ROOT = "/data/release-authority"
_MEMORIAL_PREVIEW_PUBLIC_ORIGINS = frozenset(
    {"https://myexternalbrain.com"}
)
_DOCUMENTS = {
    "deploy_context": (
        "EA_DEPLOY_CONTEXT_PATH",
        "deploy_context.generated.json",
    ),
    "project_modes": (
        "EA_PROJECT_MODES_MANIFEST_PATH",
        "PROJECT_MODES.generated.json",
    ),
    "release_manifest": (
        "EA_RELEASE_MANIFEST_PATH",
        "release_manifest.generated.json",
    ),
    "release_status": (
        "EA_RELEASE_AUTHORITY_STATUS_PATH",
        "release_authority_status.generated.json",
    ),
}
_RECEIPT_FILENAME = "candidate_release_authority.json"


class MemorialVoicePreviewAuthorityError(ValueError):
    """The packaged runtime release identity could not be proven."""


@dataclass(frozen=True, slots=True)
class MemorialVoicePreviewReleaseContext:
    source_revision: str
    deployment_id: str
    public_origin: str


@dataclass(slots=True)
class _AuthorityRootSnapshot:
    root: Path
    descriptors: list[int]
    links: list[tuple[int, str, int, tuple[int, ...]]]

    @property
    def descriptor(self) -> int:
        return self.descriptors[-1]

    def recheck(self) -> None:
        for parent_index, name, child_index, expected in self.links:
            try:
                path_metadata = os.stat(
                    name,
                    dir_fd=self.descriptors[parent_index],
                    follow_symlinks=False,
                )
                descriptor_metadata = os.fstat(self.descriptors[child_index])
            except OSError as exc:
                raise MemorialVoicePreviewAuthorityError(
                    "preview_release_document_root_changed"
                ) from exc
            if (
                _directory_identity(path_metadata) != expected
                or _directory_identity(descriptor_metadata) != expected
            ):
                raise MemorialVoicePreviewAuthorityError(
                    "preview_release_document_root_changed"
                )

    def close(self) -> None:
        for descriptor in reversed(self.descriptors):
            try:
                os.close(descriptor)
            except OSError:
                pass
        self.descriptors.clear()


def _strict_json_object(raw: bytes) -> dict[str, Any]:
    def pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise MemorialVoicePreviewAuthorityError(
                    "preview_release_document_duplicate_field"
                )
            result[key] = value
        return result

    try:
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs_hook)
    except (UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise MemorialVoicePreviewAuthorityError(
            "preview_release_document_json_invalid"
        ) from exc
    if not isinstance(payload, dict):
        raise MemorialVoicePreviewAuthorityError(
            "preview_release_document_shape_invalid"
        )
    return payload


def _directory_identity(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_uid,
        metadata.st_gid,
    )


def _file_identity(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_uid,
        metadata.st_gid,
        metadata.st_nlink,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _contains_local_authority_blocker(value: object) -> bool:
    """Reject local-only authority markers at any bounded nesting depth."""

    pending: list[tuple[object, int]] = [(value, 0)]
    visited = 0
    while pending:
        current, depth = pending.pop()
        visited += 1
        if visited > 20_000 or depth > 64:
            return True
        if isinstance(current, str):
            normalized = "_".join(
                part
                for part in "".join(
                    character.lower() if character.isalnum() else "_"
                    for character in current
                ).split("_")
                if part
            )
            if any(
                marker in normalized
                for marker in (
                    "deployment_id_local_fallback",
                    "local_fallback",
                    "local_only_authority",
                    "local_only_deploy_id",
                    "local_only_deployment",
                    "authority_local_only",
                )
            ):
                return True
            continue
        if isinstance(current, dict):
            pending.extend((key, depth + 1) for key in current)
            pending.extend((item, depth + 1) for item in current.values())
            continue
        if isinstance(current, (list, tuple)):
            pending.extend((item, depth + 1) for item in current)
    return False


def _trusted_directory(metadata: os.stat_result) -> bool:
    mode = stat.S_IMODE(metadata.st_mode)
    writable_by_others = bool(mode & 0o022)
    root_sticky_directory = bool(
        metadata.st_uid == 0 and mode & stat.S_ISVTX
    )
    return bool(
        stat.S_ISDIR(metadata.st_mode)
        and not stat.S_ISLNK(metadata.st_mode)
        and metadata.st_uid in {0, os.geteuid()}
        and (not writable_by_others or root_sticky_directory)
    )


def _immutable_authority_directory(metadata: os.stat_result) -> bool:
    return bool(
        stat.S_ISDIR(metadata.st_mode)
        and not stat.S_ISLNK(metadata.st_mode)
        and metadata.st_uid in {0, os.geteuid()}
        and not (stat.S_IMODE(metadata.st_mode) & 0o222)
    )


def _configured_document_paths() -> tuple[Path, dict[str, str]]:
    paths: dict[str, Path] = {}
    for name, (environment_name, expected_filename) in _DOCUMENTS.items():
        raw = str(os.getenv(environment_name) or "").strip()
        path = Path(raw)
        if (
            not raw
            or not path.is_absolute()
            or str(path) != raw
            or any(part in {"", ".", ".."} for part in path.parts[1:])
            or path.name != expected_filename
            or "\x00" in raw
        ):
            raise MemorialVoicePreviewAuthorityError(
                "preview_release_document_path_invalid"
            )
        paths[name] = path
    roots = {path.parent for path in paths.values()}
    if len(roots) != 1:
        raise MemorialVoicePreviewAuthorityError(
            "preview_release_document_root_mismatch"
        )
    root = roots.pop()
    filenames = {name: path.name for name, path in paths.items()}
    filenames["receipt"] = _RECEIPT_FILENAME
    return root, filenames


def _open_authority_root(root: Path) -> _AuthorityRootSnapshot:
    if root == Path("/") or not root.is_absolute():
        raise MemorialVoicePreviewAuthorityError(
            "preview_release_document_root_invalid"
        )
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptors: list[int] = []
    links: list[tuple[int, str, int, tuple[int, ...]]] = []
    try:
        descriptors.append(os.open("/", flags))
        if not _trusted_directory(os.fstat(descriptors[0])):
            raise MemorialVoicePreviewAuthorityError(
                "preview_release_document_root_untrusted"
            )
        for name in root.parts[1:]:
            parent_index = len(descriptors) - 1
            descriptor = os.open(name, flags, dir_fd=descriptors[parent_index])
            descriptors.append(descriptor)
            metadata = os.fstat(descriptor)
            if not _trusted_directory(metadata):
                raise MemorialVoicePreviewAuthorityError(
                    "preview_release_document_root_untrusted"
                )
            links.append(
                (
                    parent_index,
                    name,
                    len(descriptors) - 1,
                    _directory_identity(metadata),
                )
            )
        snapshot = _AuthorityRootSnapshot(
            root=root,
            descriptors=descriptors,
            links=links,
        )
        if not _immutable_authority_directory(os.fstat(snapshot.descriptor)):
            raise MemorialVoicePreviewAuthorityError(
                "preview_release_document_root_mutable"
            )
        snapshot.recheck()
        return snapshot
    except (OSError, MemorialVoicePreviewAuthorityError) as exc:
        for descriptor in reversed(descriptors):
            try:
                os.close(descriptor)
            except OSError:
                pass
        if isinstance(exc, MemorialVoicePreviewAuthorityError):
            raise
        raise MemorialVoicePreviewAuthorityError(
            "preview_release_document_root_unavailable"
        ) from exc


def _read_document_at(
    root: _AuthorityRootSnapshot,
    filename: str,
) -> tuple[dict[str, Any], dict[str, object]]:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(filename, flags, dir_fd=root.descriptor)
    except OSError as exc:
        raise MemorialVoicePreviewAuthorityError(
            "preview_release_document_unavailable"
        ) from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_uid not in {0, os.geteuid()}
            or stat.S_IMODE(before.st_mode) & 0o222
            or not 0 < before.st_size <= _MAX_DOCUMENT_BYTES
        ):
            raise MemorialVoicePreviewAuthorityError(
                "preview_release_document_untrusted"
            )
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(remaining, 64 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(descriptor)
        try:
            path_metadata = os.stat(
                filename,
                dir_fd=root.descriptor,
                follow_symlinks=False,
            )
        except OSError as exc:
            raise MemorialVoicePreviewAuthorityError(
                "preview_release_document_changed"
            ) from exc
        if (
            remaining
            or len(raw) != before.st_size
            or _file_identity(before) != _file_identity(after)
            or _file_identity(before) != _file_identity(path_metadata)
        ):
            raise MemorialVoicePreviewAuthorityError(
                "preview_release_document_changed"
            )
    finally:
        os.close(descriptor)
    return _strict_json_object(raw), {
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size_bytes": len(raw),
    }


def _canonical_public_origin(value: object) -> str:
    raw = str(value or "")
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise MemorialVoicePreviewAuthorityError(
            "preview_release_public_origin_invalid"
        ) from exc
    hostname = str(parsed.hostname or "")
    labels = hostname.split(".")
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        hostname_is_ip = False
    else:
        hostname_is_ip = True
    reserved_suffixes = (
        ".example",
        ".example.com",
        ".example.net",
        ".example.org",
        ".internal",
        ".invalid",
        ".lan",
        ".local",
        ".localhost",
        ".test",
        ".home.arpa",
    )
    if (
        raw != raw.strip()
        or parsed.scheme != "https"
        or not hostname
        or hostname != hostname.lower()
        or hostname.endswith(".")
        or hostname_is_ip
        or len(labels) < 2
        or hostname in {
            "example.com",
            "example.net",
            "example.org",
            "localhost",
        }
        or hostname.endswith(reserved_suffixes)
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or any(
            not label
            or label.startswith("-")
            or label.endswith("-")
            or any(
                character not in "abcdefghijklmnopqrstuvwxyz0123456789-"
                for character in label
            )
            for label in labels
        )
    ):
        raise MemorialVoicePreviewAuthorityError(
            "preview_release_public_origin_invalid"
        )
    canonical = f"https://{hostname}"
    if raw != canonical or canonical not in _MEMORIAL_PREVIEW_PUBLIC_ORIGINS:
        raise MemorialVoicePreviewAuthorityError(
            "preview_release_public_origin_not_canonical"
        )
    return canonical


def validated_memorial_voice_preview_release_context() -> (
    MemorialVoicePreviewReleaseContext
):
    """Return the exact packaged release identity or fail without a fallback."""

    authority_root_path, filenames = _configured_document_paths()
    payloads: dict[str, dict[str, Any]] = {}
    evidence: dict[str, dict[str, object]] = {}
    authority_root = _open_authority_root(authority_root_path)
    try:
        for name, filename in filenames.items():
            payloads[name], evidence[name] = _read_document_at(
                authority_root,
                filename,
            )
        authority_root.recheck()
    finally:
        authority_root.close()

    manifest = payloads["release_manifest"]
    project_modes = payloads["project_modes"]
    deploy_context = payloads["deploy_context"]
    status = payloads["release_status"]
    receipt = payloads["receipt"]

    source_revision = str(manifest.get("commit_sha") or "")
    deployment_id = str(manifest.get("deployment_id") or "")
    public_origin = _canonical_public_origin(manifest.get("public_origin"))
    expected_container_paths = {
        name: f"{_PACKAGED_CONTAINER_ROOT}/{filename}"
        for name, (_, filename) in _DOCUMENTS.items()
    }
    expected_container_paths["receipt"] = (
        f"{_PACKAGED_CONTAINER_ROOT}/{_RECEIPT_FILENAME}"
    )
    expected_documents = {
        name: evidence[name]
        for name in (
            "deploy_context",
            "project_modes",
            "release_manifest",
            "release_status",
        )
    }
    gate = status.get("gate")
    gate = gate if isinstance(gate, dict) else {}

    try:
        # The governed runtime image packages these tracked root validators at
        # /app/scripts.  Keep imports lazy so the standalone `ea/` package can
        # still import with preview disabled; an image missing the validators
        # fails closed at the exact point authority is requested.
        from scripts.verify_deploy_context import verify as verify_deploy_context
        from scripts.verify_release_authority import validate_release_authority
        from scripts.verify_release_manifest_runtime_mode import (
            validate_release_contract as validate_release_runtime_mode,
        )

        release_issues = validate_release_authority(
            release_manifest=manifest,
            project_modes=project_modes,
        )
        runtime_issues = validate_release_runtime_mode(
            release_manifest=manifest,
            project_modes=project_modes,
            requested_mode="MEMORIAL",
            enabled_modes=["MEMORIAL"],
            # The sealed candidate compose is the reviewed Memorial runtime,
            # but the canonical mode validator classifies Memorial topology by
            # override basename.  Supply that semantic classification here;
            # the exact candidate compose path and empty recorded override set
            # remain independently enforced below.
            compose_overrides=["docker-compose.memorial.yml"],
            manfred_composite_candidate_observed=False,
        )
        deploy_gate = verify_deploy_context(deploy_context=deploy_context)
    except Exception as exc:
        raise MemorialVoicePreviewAuthorityError(
            "preview_release_canonical_validation_failed"
        ) from exc

    if (
        release_issues
        or runtime_issues
        or deploy_gate.get("status") != "pass"
        or len(source_revision) != 40
        or any(character not in "0123456789abcdef" for character in source_revision)
        or project_modes.get("contract_name") != "ea.project_modes"
        or project_modes.get("source_git_head") != source_revision
        or manifest.get("repository") != "EA"
        or manifest.get("branch") != "main"
        or manifest.get("tracking_branch") != "origin/main"
        or manifest.get("project_mode") != "MEMORIAL"
        or manifest.get("enabled_project_modes") != ["MEMORIAL"]
        or manifest.get("compose_files")
        != ["deploy/manfred-memorial/docker-compose.candidate.yml"]
        or manifest.get("compose_overrides") != []
        or manifest.get("git_remote_origin") != _OFFICIAL_REMOTE
        or manifest.get("live_remote_ref") != "refs/heads/main"
        or manifest.get("live_remote_ref_commit_sha") != source_revision
        or manifest.get("live_remote_ref_evidence") != _LIVE_REMOTE_EVIDENCE
        or deploy_context.get("commit_sha") != source_revision
        or deploy_context.get("deployment_id") != deployment_id
        or deploy_context.get("public_origin") != public_origin
        or status.get("contract_name") != "ea.release_authority_status.v1"
        or status.get("state") != "clear"
        or status.get("authority_posture") != "authoritative_runtime"
        or status.get("issues") != []
        or status.get("commit_sha") != source_revision
        or status.get("deployment_id") != deployment_id
        or status.get("candidate_runtime") is not True
        or status.get("promotion_authority") is not False
        or gate.get("status") != "pass"
        or gate.get("issues") != []
        or _contains_local_authority_blocker(status)
        or _contains_local_authority_blocker(gate)
        or status.get("manifest_path")
        != expected_container_paths["release_manifest"]
        or status.get("deploy_context_path")
        != expected_container_paths["deploy_context"]
        or status.get("project_modes_path")
        != expected_container_paths["project_modes"]
        or receipt.get("schema")
        != "ea.manfred_candidate_release_authority.v1"
        or receipt.get("status") != "pass"
        or receipt.get("commit_sha") != source_revision
        or receipt.get("image_revision") != source_revision
        or receipt.get("deployment_id") != deployment_id
        or receipt.get("project_mode") != "MEMORIAL"
        or receipt.get("enabled_project_modes") != ["MEMORIAL"]
        or receipt.get("container_paths") != expected_container_paths
        or receipt.get("documents") != expected_documents
        or receipt.get("runtime_authority_state") != "clear"
        or receipt.get("runtime_authority_posture") != "authoritative_runtime"
        or receipt.get("promotion_authority") is not False
        or receipt.get("secret_material_recorded") is not False
        or str(os.getenv("EA_SOURCE_REVISION") or "").strip() != source_revision
        or str(os.getenv("EA_MEMORIAL_DEPLOYMENT_ID") or "").strip()
        != deployment_id
        or os.getenv("EA_DEPLOY_PRIMARY_MODE") != "MEMORIAL"
        or os.getenv("EA_DEPLOY_ENABLED_MODES") != "MEMORIAL"
    ):
        raise MemorialVoicePreviewAuthorityError(
            "preview_release_authority_binding_invalid"
        )
    return MemorialVoicePreviewReleaseContext(
        source_revision=source_revision,
        deployment_id=deployment_id,
        public_origin=public_origin,
    )
