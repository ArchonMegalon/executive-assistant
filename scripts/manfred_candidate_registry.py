#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import pwd
import re
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from scripts.prepare_manfred_memorial_candidate import _validate_project_name


REGISTRY_SCHEMA = "ea.manfred_memorial_candidate_registry.v1"
RUNTIME_SCHEMA_V3 = "ea.manfred_memorial_candidate_runtime.v3"
RUNTIME_SCHEMA_V4 = "ea.manfred_memorial_candidate_runtime.v4"
RUNTIME_SCHEMA = RUNTIME_SCHEMA_V4
SUPPORTED_RUNTIME_SCHEMAS = frozenset({RUNTIME_SCHEMA_V3, RUNTIME_SCHEMA_V4})
RUNTIME_SCHEMAS = SUPPORTED_RUNTIME_SCHEMAS
MAX_REGISTRY_ENTRIES = 128
MAX_PENDING_ENTRIES = 16
MAX_JSON_BYTES = 1024 * 1024
HEX_40 = re.compile(r"[0-9a-f]{40}")
HEX_64 = re.compile(r"[0-9a-f]{64}")
IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}")
CONTAINER_ID = re.compile(r"[0-9a-f]{64}")
IMAGE_LOCATOR = re.compile(r"ea-runtime:(?:manfred|memorial)-[0-9a-f]{40}")
GIT_OBJECT_ID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
CANDIDATE_COMPOSE_RELATIVE_PATH = "deploy/manfred-memorial/docker-compose.candidate.yml"
CANDIDATE_COMPOSE_MAX_BYTES = 1024 * 1024
CANDIDATE_ENV_MAX_BYTES = 1024 * 1024
EXECUTION_INPUT_SCHEMA = "ea.manfred_candidate_execution_inputs.v1"
RUNTIME_POSTURE_SCHEMA = "ea.manfred_candidate_api_runtime_posture.v1"
RUNTIME_PROJECTION_SCHEMA = "ea.manfred_candidate_runtime_projection.v1"
CANDIDATE_ENV_KEYS = frozenset(
    {
        "DATABASE_URL",
        "EA_API_TOKEN",
        "EA_MANFRED_COMPOSE_PROJECT",
        "EA_MANFRED_COMMIT",
        "EA_MANFRED_DEPLOYMENT_ID",
        "EA_MANFRED_ENV_FILE",
        "EA_MANFRED_HOST_PORT",
        "EA_MANFRED_IMAGE",
        "EA_MANFRED_POSTGRES_PASSWORD",
        "EA_MANFRED_RELEASE_ROOT",
        "EA_MANFRED_RELEASE_AUTHORITY_ROOT",
        "EA_MANFRED_RUNTIME_ROOT",
        "EA_MANFRED_SPATIAL_HANDOFF_INCLUDED",
        "EA_MANFRED_SPATIAL_RELEASE_ROOT",
        "EA_MANFRED_SPATIAL_SHA256",
        "EA_MANFRED_SPATIAL_SLUG",
        "EA_PUBLIC_APP_BASE_URL",
        "EA_SIGNING_SECRET",
    }
)


def operator_state_root() -> Path:
    try:
        home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    except (KeyError, OSError) as exc:
        raise RuntimeError("manfred_candidate_registry_operator_home_invalid") from exc
    if not home.is_absolute():
        raise RuntimeError("manfred_candidate_registry_operator_home_invalid")
    return home / ".local/state/ea"


def default_registry_path() -> Path:
    return operator_state_root() / "manfred-candidate-registry.json"


def _absolute_path(path: Path) -> Path:
    expanded = Path(path).expanduser()
    return expanded if expanded.is_absolute() else Path.cwd() / expanded


def _read_private_json(
    path: Path,
    *,
    missing_ok: bool = False,
) -> tuple[dict[str, object], str] | None:
    absolute = _absolute_path(path)
    if missing_ok and not os.path.lexists(absolute):
        return None
    try:
        resolved = absolute.resolve(strict=True)
    except OSError as exc:
        raise RuntimeError("manfred_candidate_registry_path_invalid") from exc
    if resolved != absolute.absolute() or resolved.is_symlink():
        raise RuntimeError("manfred_candidate_registry_path_invalid")
    flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(resolved, flags)
    except OSError as exc:
        raise RuntimeError("manfred_candidate_registry_path_invalid") from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.getuid()
            or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_size <= 0
            or before.st_size > MAX_JSON_BYTES
        ):
            raise RuntimeError("manfred_candidate_registry_file_invalid")
        content = b""
        while len(content) <= MAX_JSON_BYTES:
            chunk = os.read(
                descriptor,
                min(65536, MAX_JSON_BYTES + 1 - len(content)),
            )
            if not chunk:
                break
            content += chunk
        after = os.fstat(descriptor)
        if len(content) != before.st_size or (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
            raise RuntimeError("manfred_candidate_registry_file_changed")
    finally:
        os.close(descriptor)
    try:
        payload = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("manfred_candidate_registry_json_invalid") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("manfred_candidate_registry_json_invalid")
    return dict(payload), hashlib.sha256(content).hexdigest()


def _ensure_private_parent(path: Path) -> Path:
    absolute = _absolute_path(path)
    parent = absolute.parent
    try:
        parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        resolved = parent.resolve(strict=True)
        metadata = resolved.stat()
    except OSError as exc:
        raise RuntimeError("manfred_candidate_registry_parent_invalid") from exc
    if (
        resolved != parent.absolute()
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) & 0o022
    ):
        raise RuntimeError("manfred_candidate_registry_parent_invalid")
    return resolved / absolute.name


def _atomic_registry(path: Path, payload: dict[str, object]) -> None:
    destination = _ensure_private_parent(path)
    if os.path.lexists(destination):
        _read_private_json(destination)
    encoded = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode(
            "utf-8"
        )
        + b"\n"
    )
    if not encoded or len(encoded) > MAX_JSON_BYTES:
        raise RuntimeError("manfred_candidate_registry_file_invalid")
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        dir=destination.parent,
    )
    try:
        os.fchmod(descriptor, 0o600)
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or metadata.st_nlink != 1
            or stat.S_IMODE(metadata.st_mode) != 0o600
        ):
            raise RuntimeError("manfred_candidate_registry_file_invalid")
        view = memoryview(encoded)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise RuntimeError("manfred_candidate_registry_write_failed")
            view = view[written:]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.replace(temporary, destination)
        temporary = ""
        directory_descriptor = os.open(
            destination.parent,
            os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC,
        )
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
        loaded = _read_private_json(destination)
        if loaded is None or loaded[0] != payload:
            raise RuntimeError("manfred_candidate_registry_write_failed")
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary:
            Path(temporary).unlink(missing_ok=True)


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _validated_timestamp(value: object) -> str:
    text = str(value or "")
    try:
        datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise RuntimeError("manfred_candidate_registry_timestamp_invalid") from exc
    return text


def _validated_compose_attestation(
    payload: dict[str, object],
    *,
    revision: str,
) -> dict[str, object]:
    attestation = payload.get("compose_attestation")
    expected_keys = {
        "canonical_relative_path",
        "canonical_source_path",
        "candidate_commit",
        "git_blob_oid",
        "sha256",
        "size_bytes",
        "canonical_path_enforced",
        "tracked_blob_bytes_enforced",
    }
    if not isinstance(attestation, dict) or set(attestation) != expected_keys:
        raise RuntimeError("manfred_candidate_registry_compose_attestation_invalid")
    source_path = Path(str(attestation.get("canonical_source_path") or ""))
    raw_size = attestation.get("size_bytes")
    if (
        attestation.get("canonical_relative_path") != CANDIDATE_COMPOSE_RELATIVE_PATH
        or attestation.get("candidate_commit") != revision
        or GIT_OBJECT_ID.fullmatch(str(attestation.get("git_blob_oid") or "")) is None
        or HEX_64.fullmatch(str(attestation.get("sha256") or "")) is None
        or type(raw_size) is not int
        or not 1 <= raw_size <= CANDIDATE_COMPOSE_MAX_BYTES
        or attestation.get("canonical_path_enforced") is not True
        or attestation.get("tracked_blob_bytes_enforced") is not True
        or not source_path.is_absolute()
        or source_path.parts[-3:] != tuple(Path(CANDIDATE_COMPOSE_RELATIVE_PATH).parts)
        or str(source_path) != os.path.normpath(str(source_path))
    ):
        raise RuntimeError("manfred_candidate_registry_compose_attestation_invalid")
    return dict(attestation)


def _validated_execution_inputs(
    payload: dict[str, object],
    *,
    revision: str,
) -> dict[str, object]:
    inputs = payload.get("execution_inputs")
    expected_keys = {
        "schema",
        "compose_sha256",
        "compose_size_bytes",
        "compose_git_blob_oid",
        "environment_sha256",
        "environment_size_bytes",
        "environment_keys",
        "compose_image_id",
        "compose_image_reference_source",
        "transport",
        "required_seals",
        "all_compose_commands_use_sealed_inputs",
        "mutable_source_paths_consumed_by_compose",
        "mutable_image_locator_consumed_by_compose",
    }
    if not isinstance(inputs, dict) or set(inputs) != expected_keys:
        raise RuntimeError("manfred_candidate_registry_execution_inputs_invalid")
    compose = _validated_compose_attestation(payload, revision=revision)
    environment_keys = inputs.get("environment_keys")
    compose_size = inputs.get("compose_size_bytes")
    environment_size = inputs.get("environment_size_bytes")
    if (
        inputs.get("schema") != EXECUTION_INPUT_SCHEMA
        or inputs.get("compose_sha256") != compose["sha256"]
        or inputs.get("compose_git_blob_oid") != compose["git_blob_oid"]
        or compose_size != compose["size_bytes"]
        or type(compose_size) is not int
        or HEX_64.fullmatch(str(inputs.get("environment_sha256") or "")) is None
        or type(environment_size) is not int
        or not 1 <= environment_size <= CANDIDATE_ENV_MAX_BYTES
        or environment_keys != sorted(CANDIDATE_ENV_KEYS)
        or inputs.get("compose_image_id") != payload.get("image_id")
        or inputs.get("compose_image_reference_source") != "prepared_image_id"
        or inputs.get("transport") != "sealed_memfd"
        or inputs.get("required_seals") != ["grow", "seal", "shrink", "write"]
        or inputs.get("all_compose_commands_use_sealed_inputs") is not True
        or inputs.get("mutable_source_paths_consumed_by_compose") is not False
        or inputs.get("mutable_image_locator_consumed_by_compose") is not False
    ):
        raise RuntimeError("manfred_candidate_registry_execution_inputs_invalid")
    return dict(inputs)


def _validated_runtime_posture(
    payload: dict[str, object],
    *,
    project: str,
    image_id: str,
    execution_inputs: dict[str, object],
) -> dict[str, object]:
    posture = payload.get("runtime_api_posture")
    expected_keys = {
        "schema",
        "api_container_id",
        "image_id",
        "environment_sha256",
        "execution_environment_sha256",
        "environment_keys",
        "environment_exact",
        "provider_credentials_present",
        "mounts",
        "mounts_exact",
        "tmpfs_exact",
        "networks",
        "network_exact",
        "ingress_attached",
        "read_only_rootfs",
        "all_capabilities_dropped",
        "no_new_privileges",
        "runtime_user",
        "running_and_healthy",
    }
    if not isinstance(posture, dict) or set(posture) != expected_keys:
        raise RuntimeError("manfred_candidate_registry_runtime_posture_invalid")
    environment_keys = posture.get("environment_keys")
    if not isinstance(environment_keys, list) or any(
        not isinstance(name, str) for name in environment_keys
    ):
        raise RuntimeError("manfred_candidate_registry_runtime_posture_invalid")
    if (
        posture.get("schema") != RUNTIME_POSTURE_SCHEMA
        or posture.get("api_container_id")
        != payload.get("candidate_api_container_id")
        or CONTAINER_ID.fullmatch(str(posture.get("api_container_id") or "")) is None
        or posture.get("image_id") != image_id
        or HEX_64.fullmatch(str(posture.get("environment_sha256") or "")) is None
        or posture.get("execution_environment_sha256")
        != execution_inputs["environment_sha256"]
        or environment_keys != sorted(set(environment_keys))
        or not CANDIDATE_ENV_KEYS.issubset(set(environment_keys))
        or any(
            name.endswith(
                (
                    "_API_KEY",
                    "_ACCESS_KEY_ID",
                    "_SECRET_ACCESS_KEY",
                    "_SERVICE_ACCOUNT_JSON",
                )
            )
            for name in environment_keys
        )
        or posture.get("environment_exact") is not True
        or posture.get("provider_credentials_present") is not False
        or posture.get("mounts_exact") is not True
        or posture.get("tmpfs_exact") is not True
        or posture.get("networks") != [f"{project}_backend"]
        or posture.get("network_exact") is not True
        or posture.get("ingress_attached") is not False
        or posture.get("read_only_rootfs") is not True
        or posture.get("all_capabilities_dropped") is not True
        or posture.get("no_new_privileges") is not True
        or posture.get("runtime_user") != "10001:10001"
        or posture.get("running_and_healthy") is not True
    ):
        raise RuntimeError("manfred_candidate_registry_runtime_posture_invalid")

    release_root = Path(str(payload.get("release_root") or ""))
    if not release_root.is_absolute() or str(release_root) != os.path.normpath(
        str(release_root)
    ):
        raise RuntimeError("manfred_candidate_registry_runtime_posture_invalid")
    expected_release_mounts = {
        "/data/memorial/public": release_root / "public_memorials",
        "/data/memorial/private": release_root / "private_memorial_profiles",
        "/data/memorial/archive": release_root / "memorial_archive",
        "/data/public_property_tours": release_root / "public_property_tours",
        "/data/release-authority": release_root / "release-authority",
    }
    mounts = posture.get("mounts")
    if not isinstance(mounts, list) or len(mounts) != 9:
        raise RuntimeError("manfred_candidate_registry_runtime_posture_invalid")
    by_destination: dict[str, dict[str, object]] = {}
    for raw in mounts:
        if not isinstance(raw, dict) or set(raw) != {
            "destination",
            "identity",
            "read_only",
            "type",
        }:
            raise RuntimeError("manfred_candidate_registry_runtime_posture_invalid")
        destination = str(raw.get("destination") or "")
        if destination in by_destination:
            raise RuntimeError("manfred_candidate_registry_runtime_posture_invalid")
        by_destination[destination] = raw
    if set(by_destination) != {
        *expected_release_mounts,
        "/data/memorial/public-contributions",
        "/data/memorial/private-contributions",
        "/data/memorial/state",
        "/data/artifacts",
    }:
        raise RuntimeError("manfred_candidate_registry_runtime_posture_invalid")
    for destination, source in expected_release_mounts.items():
        row = by_destination[destination]
        if row != {
            "destination": destination,
            "identity": str(source),
            "read_only": True,
            "type": "bind",
        }:
            raise RuntimeError("manfred_candidate_registry_runtime_posture_invalid")
    runtime_parent: Path | None = None
    for destination, leaf in (
        ("/data/memorial/public-contributions", "public-contributions"),
        ("/data/memorial/private-contributions", "private-contributions"),
        ("/data/memorial/state", "state"),
    ):
        row = by_destination[destination]
        source = Path(str(row.get("identity") or ""))
        if (
            row.get("type") != "bind"
            or row.get("read_only") is not False
            or not source.is_absolute()
            or source.name != leaf
            or str(source) != os.path.normpath(str(source))
            or (runtime_parent is not None and source.parent != runtime_parent)
        ):
            raise RuntimeError("manfred_candidate_registry_runtime_posture_invalid")
        runtime_parent = source.parent
    if by_destination["/data/artifacts"] != {
        "destination": "/data/artifacts",
        "identity": f"{project}_artifacts",
        "read_only": False,
        "type": "volume",
    }:
        raise RuntimeError("manfred_candidate_registry_runtime_posture_invalid")
    return dict(posture)


def _validated_runtime_projection(payload: dict[str, object]) -> dict[str, object]:
    files = payload.get("projection_files")
    if not isinstance(files, list) or not files:
        raise RuntimeError("manfred_candidate_registry_runtime_projection_invalid")
    paths: list[str] = []
    projection_bytes = 0
    for raw in files:
        if not isinstance(raw, dict) or set(raw) != {
            "mode",
            "path",
            "sha256",
            "size_bytes",
        }:
            raise RuntimeError("manfred_candidate_registry_runtime_projection_invalid")
        path = str(raw.get("path") or "")
        size = raw.get("size_bytes")
        if (
            not path
            or path.startswith("/")
            or ".." in Path(path).parts
            or path in paths
            or HEX_64.fullmatch(str(raw.get("sha256") or "")) is None
            or type(size) is not int
            or size <= 0
            or raw.get("mode") not in {"440", "444"}
        ):
            raise RuntimeError("manfred_candidate_registry_runtime_projection_invalid")
        paths.append(path)
        projection_bytes += size
    if paths != sorted(paths):
        raise RuntimeError("manfred_candidate_registry_runtime_projection_invalid")
    digest = hashlib.sha256(
        json.dumps(files, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()
    expected = {
        "schema": RUNTIME_PROJECTION_SCHEMA,
        "projection_sha256": digest,
        "file_count": len(files),
        "projection_bytes": projection_bytes,
        "mount_roots": [
            "/data/memorial/public",
            "/data/memorial/private",
            "/data/memorial/archive",
            "/data/public_property_tours",
            "/data/release-authority",
        ],
        "runtime_bytes_match_prepared_projection": True,
    }
    if (
        payload.get("projection_sha256") != digest
        or payload.get("projection_file_count") != len(files)
        or payload.get("projection_bytes") != projection_bytes
        or payload.get("runtime_projection_initial") != expected
        or payload.get("runtime_projection_final") != expected
        or payload.get("runtime_projection_identity_stable") is not True
    ):
        raise RuntimeError("manfred_candidate_registry_runtime_projection_invalid")
    return expected


def _runtime_identity(payload: dict[str, object]) -> dict[str, object]:
    schema = str(payload.get("schema") or "")
    if schema not in SUPPORTED_RUNTIME_SCHEMAS or payload.get("status") != "pass":
        raise RuntimeError("manfred_candidate_registry_receipt_invalid")
    try:
        project = _validate_project_name(payload.get("compose_project"))
    except ValueError as exc:
        raise RuntimeError("manfred_candidate_registry_receipt_invalid") from exc
    observed_at = _validated_timestamp(payload.get("observed_at"))
    image = str(payload.get("image") or "")
    image_id = str(payload.get("image_id") or "")
    revision = str(payload.get("image_source_revision") or "")
    raw_port = payload.get("candidate_port")
    if type(raw_port) is not int:
        raise RuntimeError("manfred_candidate_registry_receipt_invalid")
    port = raw_port
    if (
        IMAGE_ID.fullmatch(image_id) is None
        or HEX_40.fullmatch(revision) is None
        or IMAGE_LOCATOR.fullmatch(image) is None
        or image
        not in {
            f"ea-runtime:manfred-{revision}",
            f"ea-runtime:memorial-{revision}",
        }
        or not 1024 <= port <= 65535
        or str(payload.get("runtime_source_revision") or "") != revision
        or payload.get("candidate_left_running_for_soak") is not True
        or payload.get("live_ea_api_unchanged") is not True
        or payload.get("promotion_authority") is not False
        or payload.get("provider_credentials_present") is not False
        or payload.get("provider_calls_performed") is not False
        or payload.get("gateway_has_runtime_secrets") is not False
    ):
        raise RuntimeError("manfred_candidate_registry_receipt_invalid")

    if schema == RUNTIME_SCHEMA_V4:
        execution_inputs = _validated_execution_inputs(payload, revision=revision)
        image_locator_evidence = payload.get("image_locator_evidence")
        if image_locator_evidence != {
            "locator": image,
            "resolved_image_id": image_id,
            "revision_label": revision,
            "used_for_attestation_only": True,
            "consumed_by_compose": False,
        } or payload.get("compose_uses_immutable_image_id") is not True:
            raise RuntimeError(
                "manfred_candidate_registry_image_reference_semantics_invalid"
            )
        _validated_runtime_projection(payload)
        runtime_identity = payload.get("runtime_version_identity")
        if not isinstance(runtime_identity, dict):
            raise RuntimeError("manfred_candidate_registry_receipt_identity_invalid")
        expected_identity = {
            "path": "/version",
            "status": 200,
            "commit_sha": revision,
            "body_commit_sha": revision,
            "source_revision_header": revision,
            "expected_commit_sha": revision,
            "oci_image_revision": revision,
            "repository": "EA",
            "role": "api",
            "release_authority_state": "clear",
            "release_authority_posture": "authoritative_runtime",
            "release_authority_source": "published_status_artifact",
            "commit_observed_over_http": True,
            "revision_agreement_verified": True,
        }
        if (
            runtime_identity != expected_identity
            or type(runtime_identity.get("status")) is not int
            or runtime_identity.get("commit_observed_over_http") is not True
            or runtime_identity.get("revision_agreement_verified") is not True
            or str(payload.get("runtime_authority_commit") or "") != revision
        ):
            raise RuntimeError("manfred_candidate_registry_receipt_identity_invalid")
        container_images = payload.get("candidate_container_images")
        initial_container_images = payload.get("candidate_container_images_initial")
        final_container_images = payload.get("candidate_container_images_final")
        if (
            not isinstance(container_images, dict)
            or initial_container_images != container_images
            or final_container_images != container_images
            or payload.get("candidate_container_image_identity_stable") is not True
            or set(container_images)
            != {
                "api",
                "gateway",
                "prepared_image_id",
                "revision_label",
                "all_match_prepared_image",
            }
            or container_images.get("prepared_image_id") != image_id
            or container_images.get("revision_label") != revision
            or container_images.get("all_match_prepared_image") is not True
        ):
            raise RuntimeError(
                "manfred_candidate_registry_receipt_container_identity_invalid"
            )
        for service in ("api", "gateway"):
            service_identity = container_images.get(service)
            if (
                not isinstance(service_identity, dict)
                or set(service_identity) != {"container_id", "image_id"}
                or CONTAINER_ID.fullmatch(
                    str(service_identity.get("container_id") or "")
                )
                is None
                or service_identity.get("image_id") != image_id
            ):
                raise RuntimeError(
                    "manfred_candidate_registry_receipt_container_identity_invalid"
                )
        if payload.get("candidate_api_container_id") != dict(
            container_images["api"]
        ).get("container_id"):
            raise RuntimeError(
                "manfred_candidate_registry_receipt_container_identity_invalid"
            )
        _validated_runtime_posture(
            payload,
            project=project,
            image_id=image_id,
            execution_inputs=execution_inputs,
        )

    return {
        "schema": schema,
        "project": project,
        "observed_at": observed_at,
        "image": image,
        "image_id": image_id,
        "revision": revision,
        "port": port,
        "legacy": schema == RUNTIME_SCHEMA_V3,
    }


def _receipt_entry(
    path: Path,
) -> tuple[dict[str, object], dict[str, str], dict[str, object]]:
    loaded = _read_private_json(path)
    if loaded is None:  # pragma: no cover - missing_ok is false
        raise RuntimeError("manfred_candidate_registry_receipt_missing")
    payload, digest = loaded
    identity = _runtime_identity(payload)
    resolved = Path(path).expanduser().resolve(strict=True)
    return (
        payload,
        {
            "project": str(identity["project"]),
            "receipt_path": str(resolved),
            "receipt_sha256": digest,
            "observed_at": str(identity["observed_at"]),
            "image_id": str(identity["image_id"]),
        },
        identity,
    )


def _normalized_pending(
    *,
    project: object,
    port: object,
    receipt_path: object,
    image: object,
    image_id: object,
    revision: object,
    created_at: object,
) -> dict[str, object]:
    try:
        normalized_project = _validate_project_name(project)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("manfred_candidate_registry_pending_invalid") from exc
    if type(port) is not int:
        raise RuntimeError("manfred_candidate_registry_pending_invalid")
    normalized_port = port
    path = Path(str(receipt_path or "")).expanduser()
    if not path.is_absolute() or path.resolve(strict=False) != path:
        raise RuntimeError("manfred_candidate_registry_pending_invalid")
    normalized_image = str(image or "")
    normalized_image_id = str(image_id or "")
    normalized_revision = str(revision or "")
    if (
        not 1024 <= normalized_port <= 65535
        or IMAGE_LOCATOR.fullmatch(normalized_image) is None
        or IMAGE_ID.fullmatch(normalized_image_id) is None
        or HEX_40.fullmatch(normalized_revision) is None
        or normalized_image
        not in {
            f"ea-runtime:manfred-{normalized_revision}",
            f"ea-runtime:memorial-{normalized_revision}",
        }
    ):
        raise RuntimeError("manfred_candidate_registry_pending_invalid")
    return {
        "project": normalized_project,
        "port": normalized_port,
        "receipt_path": str(path),
        "image": normalized_image,
        "image_id": normalized_image_id,
        "revision": normalized_revision,
        "created_at": _validated_timestamp(created_at),
    }


def _validated_entries(payload: dict[str, object]) -> list[dict[str, str]]:
    if payload.get("schema") != REGISTRY_SCHEMA:
        raise RuntimeError("manfred_candidate_registry_schema_invalid")
    raw_entries = payload.get("entries")
    if (
        not isinstance(raw_entries, list)
        or len(raw_entries) > MAX_REGISTRY_ENTRIES
        or payload.get("entry_count") != len(raw_entries)
    ):
        raise RuntimeError("manfred_candidate_registry_entries_invalid")
    entries: list[dict[str, str]] = []
    projects: set[str] = set()
    paths: set[str] = set()
    for raw in raw_entries:
        if not isinstance(raw, dict) or set(raw) != {
            "project",
            "receipt_path",
            "receipt_sha256",
            "observed_at",
            "image_id",
        }:
            raise RuntimeError("manfred_candidate_registry_entries_invalid")
        try:
            project = _validate_project_name(raw.get("project"))
        except ValueError as exc:
            raise RuntimeError("manfred_candidate_registry_entries_invalid") from exc
        entry = {
            "project": project,
            "receipt_path": str(raw.get("receipt_path") or ""),
            "receipt_sha256": str(raw.get("receipt_sha256") or ""),
            "observed_at": str(raw.get("observed_at") or ""),
            "image_id": str(raw.get("image_id") or ""),
        }
        receipt_path = Path(entry["receipt_path"])
        if (
            project in projects
            or entry["receipt_path"] in paths
            or HEX_64.fullmatch(entry["receipt_sha256"]) is None
            or IMAGE_ID.fullmatch(entry["image_id"]) is None
            or not receipt_path.is_absolute()
            or receipt_path.resolve(strict=False) != receipt_path
        ):
            raise RuntimeError("manfred_candidate_registry_entries_invalid")
        _validated_timestamp(entry["observed_at"])
        projects.add(project)
        paths.add(entry["receipt_path"])
        entries.append(entry)
    return entries


def _validated_pending(payload: dict[str, object]) -> list[dict[str, object]]:
    if payload.get("schema") != REGISTRY_SCHEMA:
        raise RuntimeError("manfred_candidate_registry_schema_invalid")
    raw_pending = payload.get("pending", [])
    pending_count = payload.get(
        "pending_count",
        len(raw_pending) if isinstance(raw_pending, list) else -1,
    )
    if (
        not isinstance(raw_pending, list)
        or len(raw_pending) > MAX_PENDING_ENTRIES
        or pending_count != len(raw_pending)
    ):
        raise RuntimeError("manfred_candidate_registry_pending_invalid")
    pending: list[dict[str, object]] = []
    projects: set[str] = set()
    ports: set[int] = set()
    paths: set[str] = set()
    expected_keys = {
        "project",
        "port",
        "receipt_path",
        "image",
        "image_id",
        "revision",
        "created_at",
    }
    for raw in raw_pending:
        if not isinstance(raw, dict) or set(raw) != expected_keys:
            raise RuntimeError("manfred_candidate_registry_pending_invalid")
        entry = _normalized_pending(**raw)
        project = str(entry["project"])
        port = entry["port"]
        receipt_path = str(entry["receipt_path"])
        if project in projects or port in ports or receipt_path in paths:
            raise RuntimeError("manfred_candidate_registry_pending_invalid")
        projects.add(project)
        ports.add(port)
        paths.add(receipt_path)
        pending.append(entry)
    return sorted(
        pending,
        key=lambda row: (str(row["created_at"]), str(row["project"])),
    )


def _registry_payload(
    entries: list[dict[str, str]],
    pending: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "schema": REGISTRY_SCHEMA,
        "entry_count": len(entries),
        "entries": entries,
        "pending_count": len(pending),
        "pending": pending,
    }


def _validated_registry(
    payload: dict[str, object],
) -> tuple[list[dict[str, str]], list[dict[str, object]]]:
    entries = _validated_entries(payload)
    pending = _validated_pending(payload)
    registered_projects = {entry["project"] for entry in entries}
    registered_receipt_paths = {entry["receipt_path"] for entry in entries}
    if registered_projects.intersection(
        str(entry["project"]) for entry in pending
    ) or registered_receipt_paths.intersection(
        str(entry["receipt_path"]) for entry in pending
    ):
        raise RuntimeError("manfred_candidate_registry_pending_invalid")
    return entries, pending


def register_candidate_pending(
    *,
    project: str,
    port: int,
    receipt_path: Path,
    image: str,
    image_id: str,
    revision: str,
    registry_path: Path | None = None,
) -> dict[str, object]:
    path = Path(registry_path or default_registry_path())
    loaded = _read_private_json(path, missing_ok=True)
    entries, pending = _validated_registry(loaded[0]) if loaded else ([], [])
    entry = _normalized_pending(
        project=project,
        port=port,
        receipt_path=str(Path(receipt_path).expanduser().resolve()),
        image=image,
        image_id=image_id,
        revision=revision,
        created_at=_utc_now(),
    )
    if any(row["project"] == entry["project"] for row in entries):
        raise RuntimeError("manfred_candidate_registry_project_already_registered")
    if any(row["receipt_path"] == entry["receipt_path"] for row in entries):
        raise RuntimeError("manfred_candidate_registry_receipt_path_conflict")
    if any(
        row["project"] == entry["project"]
        or row["port"] == entry["port"]
        or row["receipt_path"] == entry["receipt_path"]
        for row in pending
    ):
        raise RuntimeError("manfred_candidate_registry_pending_exists")
    if len(pending) >= MAX_PENDING_ENTRIES:
        raise RuntimeError("manfred_candidate_registry_pending_full")
    pending.append(entry)
    pending.sort(key=lambda row: (str(row["created_at"]), str(row["project"])))
    _atomic_registry(path, _registry_payload(entries, pending))
    return {
        "schema": REGISTRY_SCHEMA,
        "project": entry["project"],
        "created_at": entry["created_at"],
        "pending_registered": True,
    }


def clear_candidate_pending(
    project: str,
    *,
    registry_path: Path | None = None,
) -> dict[str, object]:
    try:
        normalized = _validate_project_name(project)
    except ValueError as exc:
        raise RuntimeError("manfred_candidate_registry_pending_invalid") from exc
    path = Path(registry_path or default_registry_path())
    loaded = _read_private_json(path, missing_ok=True)
    if loaded is None:
        return {
            "schema": REGISTRY_SCHEMA,
            "project": normalized,
            "pending_cleared": False,
        }
    entries, pending = _validated_registry(loaded[0])
    retained = [row for row in pending if row["project"] != normalized]
    cleared = len(retained) != len(pending)
    if cleared:
        _atomic_registry(path, _registry_payload(entries, retained))
    return {
        "schema": REGISTRY_SCHEMA,
        "project": normalized,
        "pending_cleared": cleared,
    }


def registered_candidate_pending(
    *,
    registry_path: Path | None = None,
) -> list[dict[str, object]]:
    path = Path(registry_path or default_registry_path())
    loaded = _read_private_json(path, missing_ok=True)
    if loaded is None:
        return []
    _entries, pending = _validated_registry(loaded[0])
    return pending


def candidate_registry_recovery_state(
    *,
    project: str,
    port: int,
    receipt_path: Path,
    image: str,
    image_id: str,
    revision: str,
    registry_path: Path | None = None,
) -> dict[str, object]:
    """Return an exact, fail-closed restart state for one launch identity.

    Callers must hold the global candidate fleet lock while acting on this
    evidence.  This function never mutates the registry or a receipt.
    """

    expected = _normalized_pending(
        project=project,
        port=port,
        receipt_path=str(_absolute_path(Path(receipt_path))),
        image=image,
        image_id=image_id,
        revision=revision,
        created_at="1970-01-01T00:00:00Z",
    )
    expected_identity = {
        key: expected[key]
        for key in (
            "project",
            "port",
            "receipt_path",
            "image",
            "image_id",
            "revision",
        )
    }
    path = Path(registry_path or default_registry_path())
    loaded = _read_private_json(path, missing_ok=True)
    entries, pending = _validated_registry(loaded[0]) if loaded else ([], [])
    pending_conflicts = [
        row
        for row in pending
        if row["project"] == expected["project"]
        or row["port"] == expected["port"]
        or row["receipt_path"] == expected["receipt_path"]
    ]
    entry_conflicts = [
        row
        for row in entries
        if row["project"] == expected["project"]
        or row["receipt_path"] == expected["receipt_path"]
    ]
    if len(pending_conflicts) + len(entry_conflicts) > 1:
        raise RuntimeError("manfred_candidate_registry_recovery_conflict")
    if entry_conflicts:
        entry = entry_conflicts[0]
        payload, observed, identity = _receipt_entry(Path(str(entry["receipt_path"])))
        observed_identity = {
            "project": identity["project"],
            "port": identity["port"],
            "receipt_path": str(Path(str(entry["receipt_path"]))),
            "image": identity["image"],
            "image_id": identity["image_id"],
            "revision": identity["revision"],
        }
        if observed != entry or observed_identity != expected_identity:
            raise RuntimeError("manfred_candidate_registry_recovery_conflict")
        return {
            "schema": REGISTRY_SCHEMA,
            "state": "registered_receipt",
            "project": expected["project"],
            "created_at": "",
            "receipt_sha256": entry["receipt_sha256"],
            "runtime_receipt": payload,
        }
    if not pending_conflicts:
        return {
            "schema": REGISTRY_SCHEMA,
            "state": "absent",
            "project": expected["project"],
            "created_at": "",
            "receipt_sha256": "",
        }

    pending_entry = pending_conflicts[0]
    observed_identity = {
        key: pending_entry[key]
        for key in (
            "project",
            "port",
            "receipt_path",
            "image",
            "image_id",
            "revision",
        )
    }
    if observed_identity != expected_identity:
        raise RuntimeError("manfred_candidate_registry_recovery_conflict")
    recovery: dict[str, object] = {
        "schema": REGISTRY_SCHEMA,
        "state": "pending_only",
        "project": expected["project"],
        "created_at": pending_entry["created_at"],
        "receipt_sha256": "",
    }
    receipt = Path(str(expected["receipt_path"]))
    if os.path.lexists(receipt):
        try:
            payload, observed, identity = _receipt_entry(receipt)
        except RuntimeError as exc:
            if str(exc) != "manfred_candidate_registry_file_invalid":
                raise
            recovery["state"] = "pending_receipt_unreadable"
            return recovery
        if (
            observed["project"] != expected["project"]
            or observed["receipt_path"] != expected["receipt_path"]
            or identity["port"] != expected["port"]
            or identity["image"] != expected["image"]
            or identity["image_id"] != expected["image_id"]
            or identity["revision"] != expected["revision"]
        ):
            raise RuntimeError("manfred_candidate_registry_recovery_conflict")
        recovery.update(
            {
                "state": "pending_receipt",
                "receipt_sha256": observed["receipt_sha256"],
                "runtime_receipt": payload,
            }
        )
    return recovery


def clear_candidate_pending_exact(
    *,
    project: str,
    port: int,
    receipt_path: Path,
    image: str,
    image_id: str,
    revision: str,
    resources_absent: bool,
    expected_receipt_sha256: str = "",
    registry_path: Path | None = None,
) -> dict[str, object]:
    """Clear only a fully matched crash intent after external absence proof."""

    if resources_absent is not True:
        raise RuntimeError("manfred_candidate_registry_recovery_not_proven")
    recovery = candidate_registry_recovery_state(
        project=project,
        port=port,
        receipt_path=receipt_path,
        image=image,
        image_id=image_id,
        revision=revision,
        registry_path=registry_path,
    )
    expected_state = "pending_receipt" if expected_receipt_sha256 else "pending_only"
    if (
        recovery.get("state") != expected_state
        or str(recovery.get("receipt_sha256") or "") != expected_receipt_sha256
        or (
            expected_receipt_sha256
            and HEX_64.fullmatch(expected_receipt_sha256) is None
        )
    ):
        raise RuntimeError("manfred_candidate_registry_recovery_changed")
    path = Path(registry_path or default_registry_path())
    loaded = _read_private_json(path)
    if loaded is None:  # pragma: no cover - missing_ok is false
        raise RuntimeError("manfred_candidate_registry_recovery_changed")
    entries, pending = _validated_registry(loaded[0])
    retained = [row for row in pending if row["project"] != recovery["project"]]
    if len(retained) != len(pending) - 1:
        raise RuntimeError("manfred_candidate_registry_recovery_changed")
    _atomic_registry(path, _registry_payload(entries, retained))
    return {
        "schema": REGISTRY_SCHEMA,
        "project": recovery["project"],
        "pending_cleared": True,
        "resources_absent": True,
        "receipt_preserved": bool(expected_receipt_sha256),
    }


def register_candidate_receipt(
    receipt_path: Path,
    *,
    registry_path: Path | None = None,
    require_pending: bool = False,
) -> dict[str, object]:
    payload, entry, identity = _receipt_entry(receipt_path)
    if identity["schema"] != RUNTIME_SCHEMA_V4:
        raise RuntimeError("manfred_candidate_registry_legacy_receipt_forbidden")
    path = Path(registry_path or default_registry_path())
    loaded = _read_private_json(path, missing_ok=True)
    entries, pending = _validated_registry(loaded[0]) if loaded else ([], [])
    if any(
        row["receipt_path"] == entry["receipt_path"]
        and row["project"] != entry["project"]
        for row in entries
    ):
        raise RuntimeError("manfred_candidate_registry_receipt_path_conflict")
    matching_entries = [row for row in entries if row["project"] == entry["project"]]
    if matching_entries:
        if matching_entries != [entry]:
            raise RuntimeError("manfred_candidate_registry_project_already_registered")
        return {
            "schema": REGISTRY_SCHEMA,
            "project": entry["project"],
            "receipt_sha256": entry["receipt_sha256"],
            "registered": True,
            "idempotent": True,
        }
    matching_pending = [row for row in pending if row["project"] == entry["project"]]
    if any(
        row["receipt_path"] == entry["receipt_path"]
        and row["project"] != entry["project"]
        for row in pending
    ):
        raise RuntimeError("manfred_candidate_registry_receipt_path_conflict")
    if require_pending and not matching_pending:
        raise RuntimeError("manfred_candidate_registry_pending_missing")
    if matching_pending:
        intent = matching_pending[0]
        if (
            str(intent["receipt_path"]) != str(entry["receipt_path"])
            or str(intent["image"]) != str(identity["image"])
            or str(intent["image_id"]) != str(identity["image_id"])
            or str(intent["revision"]) != str(identity["revision"])
            or intent["port"] != identity["port"]
        ):
            raise RuntimeError("manfred_candidate_registry_pending_mismatch")
    if len(entries) >= MAX_REGISTRY_ENTRIES:
        raise RuntimeError("manfred_candidate_registry_full")
    entries.append(entry)
    entries.sort(key=lambda row: (row["observed_at"], row["project"]))
    pending = [row for row in pending if row["project"] != entry["project"]]
    _atomic_registry(path, _registry_payload(entries, pending))
    return {
        "schema": REGISTRY_SCHEMA,
        "project": entry["project"],
        "receipt_sha256": entry["receipt_sha256"],
        "registered": True,
        "idempotent": False,
    }


def registered_candidate_receipts(
    *,
    registry_path: Path | None = None,
) -> list[Path]:
    path = Path(registry_path or default_registry_path())
    loaded = _read_private_json(path, missing_ok=True)
    if loaded is None:
        return []
    entries, _pending = _validated_registry(loaded[0])
    paths: list[Path] = []
    for entry in entries:
        receipt_path = Path(entry["receipt_path"])
        _payload, observed, _identity = _receipt_entry(receipt_path)
        if observed != entry:
            raise RuntimeError("manfred_candidate_registry_receipt_changed")
        paths.append(receipt_path)
    return paths


def registered_candidate_receipt_postures(
    *,
    registry_path: Path | None = None,
) -> list[dict[str, object]]:
    path = Path(registry_path or default_registry_path())
    loaded = _read_private_json(path, missing_ok=True)
    if loaded is None:
        return []
    entries, _pending = _validated_registry(loaded[0])
    postures: list[dict[str, object]] = []
    for entry in entries:
        _payload, observed, identity = _receipt_entry(Path(entry["receipt_path"]))
        if observed != entry:
            raise RuntimeError("manfred_candidate_registry_receipt_changed")
        legacy = identity["legacy"] is True
        postures.append(
            {
                **entry,
                "runtime_schema": identity["schema"],
                "legacy": legacy,
                "retention_eligible": not legacy,
                "quarantined": legacy,
                "quarantine_reason": ("legacy_runtime_receipt_v3" if legacy else ""),
                "automatic_retirement_authorized": False,
            }
        )
    return postures


def compact_candidate_registry(
    active_projects: set[str],
    *,
    registry_path: Path | None = None,
) -> dict[str, object]:
    normalized: set[str] = set()
    for project in active_projects:
        try:
            normalized.add(_validate_project_name(project))
        except ValueError as exc:
            raise RuntimeError(
                "manfred_candidate_registry_active_project_invalid"
            ) from exc
    path = Path(registry_path or default_registry_path())
    loaded = _read_private_json(path, missing_ok=True)
    entries, pending = _validated_registry(loaded[0]) if loaded else ([], [])
    retained: list[dict[str, str]] = []
    retained_active_projects: set[str] = set()
    for entry in entries:
        _payload, observed, identity = _receipt_entry(Path(entry["receipt_path"]))
        if observed != entry:
            raise RuntimeError("manfred_candidate_registry_receipt_changed")
        if identity["legacy"] is True or entry["project"] in normalized:
            retained.append(entry)
        if entry["project"] in normalized:
            retained_active_projects.add(entry["project"])
    if retained_active_projects != normalized:
        raise RuntimeError("manfred_candidate_registry_active_receipt_missing")
    _atomic_registry(path, _registry_payload(retained, pending))
    return {
        "schema": REGISTRY_SCHEMA,
        "before_count": len(entries),
        "after_count": len(retained),
        "active_projects": sorted(normalized),
        "historical_receipts_deleted": False,
    }
