#!/usr/bin/env python3
"""Fail-closed retention audit for Manfred Memorial candidate runtimes.

This bounded controller deliberately has no Docker mutation primitive.  It proves
which registered v4 candidate is currently identity-stable and quarantines every
other posture.  A later destructive controller can consume the same evidence only
after adding persistent, long-running keeper qualification and exact resource
revalidation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.manfred_candidate_fleet_lock import (  # noqa: E402
    FLEET_LOCK_PATH,
    hold_candidate_fleet_lock,
)
from scripts.manfred_candidate_registry import (  # noqa: E402
    RUNTIME_SCHEMA_V3,
    RUNTIME_SCHEMA_V4,
    _validated_compose_attestation,
    _validated_execution_inputs,
    _validated_runtime_posture,
    default_registry_path,
    registered_candidate_receipt_postures,
)
from scripts.prepare_manfred_memorial_candidate import (  # noqa: E402
    PROJECT_NAME_PREFIX,
    _validate_project_name,
)
from scripts.verify_manfred_spatial_candidate_browser import (  # noqa: E402
    _candidate_version,
)


REPORT_SCHEMA = "ea.manfred_memorial_candidate_retention.v2"
LIVE_COMPOSE_PROJECT = "ea"
LEGACY_CANDIDATE_PROJECT = "ea-manfred-candidate"
EXPECTED_SERVICES = frozenset({"api", "gateway", "postgres", "redis"})
MAX_DOCKER_RESOURCES = 4096
MAX_DOCKER_OUTPUT_BYTES = 16 * 1024 * 1024
MAX_RECEIPT_BYTES = 1024 * 1024
HEX_40 = re.compile(r"[0-9a-f]{40}")
HEX_64 = re.compile(r"[0-9a-f]{64}")
IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}")
IMAGE_LOCATOR = re.compile(r"ea-runtime:(?:manfred|memorial)-[0-9a-f]{40}")
SHA256 = re.compile(r"[0-9a-f]{64}")
OCI_REVISION_LABEL = "org.opencontainers.image.revision"


@dataclass(frozen=True)
class RuntimeProof:
    project: str
    observed_at: str
    receipt_sha256: str
    revision: str
    image_id: str
    port: int
    api_container_id: str
    gateway_container_id: str
    runtime_version_identity: dict[str, object]


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _safe_environment() -> dict[str, str]:
    environment = {
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": os.environ.get("PATH") or os.defpath,
    }
    for name in (
        "DOCKER_CERT_PATH",
        "DOCKER_CONFIG",
        "DOCKER_CONTEXT",
        "DOCKER_HOST",
        "DOCKER_TLS_VERIFY",
        "HOME",
        "XDG_RUNTIME_DIR",
    ):
        value = str(os.environ.get(name) or "").strip()
        if value:
            environment[name] = value
    return environment


def _read_only_docker_command(argv: list[str]) -> bool:
    if argv == [
        "docker",
        "container",
        "ls",
        "--all",
        "--quiet",
        "--no-trunc",
    ]:
        return True
    if len(argv) >= 4 and argv[:3] == ["docker", "container", "inspect"]:
        identifiers = argv[3:]
        return (
            len(identifiers) <= MAX_DOCKER_RESOURCES
            and len(identifiers) == len(set(identifiers))
            and all(HEX_64.fullmatch(value) for value in identifiers)
        )
    if len(argv) == 4 and argv[:3] == ["docker", "image", "inspect"]:
        return IMAGE_ID.fullmatch(argv[3]) is not None
    return False


def _run_docker(argv: list[str], *, timeout: int = 30) -> bytes:
    if not _read_only_docker_command(argv):
        raise RuntimeError("manfred_candidate_retention_command_forbidden")
    try:
        completed = subprocess.run(
            argv,
            check=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            env=_safe_environment(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError("manfred_candidate_retention_docker_command_failed") from exc
    if len(completed.stdout) > MAX_DOCKER_OUTPUT_BYTES:
        raise RuntimeError("manfred_candidate_retention_docker_output_invalid")
    return completed.stdout


def _json_rows(raw: bytes, *, error: str) -> list[dict[str, object]]:
    if len(raw) > MAX_DOCKER_OUTPUT_BYTES:
        raise RuntimeError(error)
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(error) from exc
    if (
        not isinstance(value, list)
        or len(value) > MAX_DOCKER_RESOURCES
        or any(not isinstance(row, dict) for row in value)
    ):
        raise RuntimeError(error)
    return [dict(row) for row in value]


def _mapping(value: object, *, error: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise RuntimeError(error)
    return dict(value)


def _read_private_receipt(path: Path) -> tuple[dict[str, object], str]:
    candidate = Path(path).expanduser()
    absolute = candidate if candidate.is_absolute() else Path.cwd() / candidate
    try:
        resolved = absolute.resolve(strict=True)
    except OSError as exc:
        raise RuntimeError("manfred_candidate_retention_receipt_path_invalid") from exc
    if resolved != absolute.absolute() or resolved.is_symlink():
        raise RuntimeError("manfred_candidate_retention_receipt_path_invalid")
    flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(resolved, flags)
    except OSError as exc:
        raise RuntimeError("manfred_candidate_retention_receipt_path_invalid") from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.getuid()
            or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_size <= 0
            or before.st_size > MAX_RECEIPT_BYTES
        ):
            raise RuntimeError("manfred_candidate_retention_receipt_file_invalid")
        content = b""
        while len(content) <= MAX_RECEIPT_BYTES:
            chunk = os.read(
                descriptor,
                min(65536, MAX_RECEIPT_BYTES + 1 - len(content)),
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
            raise RuntimeError("manfred_candidate_retention_receipt_changed")
    finally:
        os.close(descriptor)
    try:
        payload = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("manfred_candidate_retention_receipt_json_invalid") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("manfred_candidate_retention_receipt_json_invalid")
    return dict(payload), hashlib.sha256(content).hexdigest()


def _expected_runtime_identity(revision: str) -> dict[str, object]:
    return {
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


def _validated_timestamp(value: object) -> str:
    text = str(value or "")
    try:
        datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise RuntimeError(
            "manfred_candidate_retention_receipt_timestamp_invalid"
        ) from exc
    return text


def _parse_v4_proof(posture: dict[str, object]) -> RuntimeProof:
    if (
        posture.get("runtime_schema") != RUNTIME_SCHEMA_V4
        or posture.get("legacy") is not False
        or posture.get("retention_eligible") is not True
        or posture.get("quarantined") is not False
        or posture.get("automatic_retirement_authorized") is not False
    ):
        raise RuntimeError("manfred_candidate_retention_posture_invalid")
    try:
        project = _validate_project_name(posture.get("project"))
    except ValueError as exc:
        raise RuntimeError("manfred_candidate_retention_project_invalid") from exc
    if project == LIVE_COMPOSE_PROJECT:
        raise RuntimeError("manfred_candidate_retention_live_project_forbidden")
    receipt_path = Path(str(posture.get("receipt_path") or ""))
    expected_digest = str(posture.get("receipt_sha256") or "")
    if not receipt_path.is_absolute() or SHA256.fullmatch(expected_digest) is None:
        raise RuntimeError("manfred_candidate_retention_posture_invalid")
    payload, digest = _read_private_receipt(receipt_path)
    if digest != expected_digest:
        raise RuntimeError("manfred_candidate_retention_receipt_changed")

    revision = str(payload.get("image_source_revision") or "")
    image = str(payload.get("image") or "")
    image_id = str(payload.get("image_id") or "")
    observed_at = _validated_timestamp(payload.get("observed_at"))
    raw_port = payload.get("candidate_port")
    if type(raw_port) is not int:
        raise RuntimeError("manfred_candidate_retention_receipt_invalid")
    port = raw_port
    try:
        payload_project = _validate_project_name(payload.get("compose_project"))
    except ValueError as exc:
        raise RuntimeError("manfred_candidate_retention_receipt_invalid") from exc
    expected_identity = _expected_runtime_identity(revision)
    runtime_identity = payload.get("runtime_version_identity")
    try:
        _validated_compose_attestation(payload, revision=revision)
        execution_inputs = _validated_execution_inputs(payload, revision=revision)
        _validated_runtime_posture(
            payload,
            project=project,
            image_id=image_id,
            execution_inputs=execution_inputs,
        )
    except RuntimeError as exc:
        raise RuntimeError("manfred_candidate_retention_receipt_invalid") from exc
    if (
        payload.get("schema") != RUNTIME_SCHEMA_V4
        or payload.get("status") != "pass"
        or payload_project != project
        or str(posture.get("observed_at") or "") != observed_at
        or HEX_40.fullmatch(revision) is None
        or IMAGE_ID.fullmatch(image_id) is None
        or str(posture.get("image_id") or "") != image_id
        or IMAGE_LOCATOR.fullmatch(image) is None
        or image
        not in {
            f"ea-runtime:manfred-{revision}",
            f"ea-runtime:memorial-{revision}",
        }
        or not 1024 <= port <= 65535
        or str(payload.get("runtime_source_revision") or "") != revision
        or str(payload.get("runtime_authority_commit") or "") != revision
        or runtime_identity != expected_identity
        or type(dict(runtime_identity or {}).get("status")) is not int
        or payload.get("candidate_left_running_for_soak") is not True
        or payload.get("live_ea_api_unchanged") is not True
        or payload.get("promotion_authority") is not False
        or payload.get("provider_credentials_present") is not False
        or payload.get("provider_calls_performed") is not False
        or payload.get("gateway_has_runtime_secrets") is not False
    ):
        raise RuntimeError("manfred_candidate_retention_receipt_invalid")

    container_images = payload.get("candidate_container_images")
    initial_images = payload.get("candidate_container_images_initial")
    final_images = payload.get("candidate_container_images_final")
    if (
        not isinstance(container_images, dict)
        or initial_images != container_images
        or final_images != container_images
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
            "manfred_candidate_retention_receipt_container_identity_invalid"
        )
    service_evidence: dict[str, dict[str, str]] = {}
    for service in ("api", "gateway"):
        evidence = container_images.get(service)
        if not isinstance(evidence, dict) or set(evidence) != {
            "container_id",
            "image_id",
        }:
            raise RuntimeError(
                "manfred_candidate_retention_receipt_container_identity_invalid"
            )
        container_id = str(evidence.get("container_id") or "")
        if (
            HEX_64.fullmatch(container_id) is None
            or evidence.get("image_id") != image_id
        ):
            raise RuntimeError(
                "manfred_candidate_retention_receipt_container_identity_invalid"
            )
        service_evidence[service] = {
            "container_id": container_id,
            "image_id": image_id,
        }
    if (
        payload.get("candidate_api_container_id")
        != service_evidence["api"]["container_id"]
    ):
        raise RuntimeError(
            "manfred_candidate_retention_receipt_container_identity_invalid"
        )
    return RuntimeProof(
        project=project,
        observed_at=observed_at,
        receipt_sha256=digest,
        revision=revision,
        image_id=image_id,
        port=port,
        api_container_id=service_evidence["api"]["container_id"],
        gateway_container_id=service_evidence["gateway"]["container_id"],
        runtime_version_identity=dict(runtime_identity),
    )


def _container_inventory() -> tuple[dict[str, object], ...]:
    try:
        identifiers = [
            line.strip()
            for line in _run_docker(
                [
                    "docker",
                    "container",
                    "ls",
                    "--all",
                    "--quiet",
                    "--no-trunc",
                ]
            )
            .decode("ascii", errors="strict")
            .splitlines()
            if line.strip()
        ]
    except UnicodeDecodeError as exc:
        raise RuntimeError(
            "manfred_candidate_retention_container_list_invalid"
        ) from exc
    if (
        len(identifiers) > MAX_DOCKER_RESOURCES
        or len(identifiers) != len(set(identifiers))
        or any(HEX_64.fullmatch(value) is None for value in identifiers)
    ):
        raise RuntimeError("manfred_candidate_retention_container_list_invalid")
    if not identifiers:
        return ()
    rows = _json_rows(
        _run_docker(["docker", "container", "inspect", *identifiers]),
        error="manfred_candidate_retention_container_inspection_invalid",
    )
    normalized: list[dict[str, object]] = []
    for row in rows:
        identifier = str(row.get("Id") or "")
        image_id = str(row.get("Image") or "")
        config = _mapping(
            row.get("Config"),
            error="manfred_candidate_retention_container_inspection_invalid",
        )
        labels_value = config.get("Labels")
        raw_labels = (
            {}
            if labels_value is None
            else _mapping(
                labels_value,
                error="manfred_candidate_retention_container_inspection_invalid",
            )
        )
        if any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in raw_labels.items()
        ):
            raise RuntimeError(
                "manfred_candidate_retention_container_inspection_invalid"
            )
        labels = dict(raw_labels)
        state = _mapping(
            row.get("State"),
            error="manfred_candidate_retention_container_inspection_invalid",
        )
        raw_health = state.get("Health")
        health = (
            {}
            if raw_health is None
            else _mapping(
                raw_health,
                error="manfred_candidate_retention_container_inspection_invalid",
            )
        )
        if HEX_64.fullmatch(identifier) is None or IMAGE_ID.fullmatch(image_id) is None:
            raise RuntimeError(
                "manfred_candidate_retention_container_inspection_invalid"
            )
        normalized.append(
            {
                "id": identifier,
                "project": labels.get("com.docker.compose.project", ""),
                "service": labels.get("com.docker.compose.service", ""),
                "image_id": image_id,
                "running": state.get("Running") is True,
                "health": str(health.get("Status") or ""),
            }
        )
    if {str(row["id"]) for row in normalized} != set(identifiers) or len(
        normalized
    ) != len(identifiers):
        raise RuntimeError("manfred_candidate_retention_container_inspection_invalid")
    return tuple(sorted(normalized, key=lambda row: str(row["id"])))


def _image_revision(image_id: str) -> str:
    rows = _json_rows(
        _run_docker(["docker", "image", "inspect", image_id]),
        error="manfred_candidate_retention_image_inspection_invalid",
    )
    if len(rows) != 1 or str(rows[0].get("Id") or "") != image_id:
        raise RuntimeError("manfred_candidate_retention_image_inspection_invalid")
    config = _mapping(
        rows[0].get("Config"),
        error="manfred_candidate_retention_image_inspection_invalid",
    )
    labels = _mapping(
        config.get("Labels"),
        error="manfred_candidate_retention_image_inspection_invalid",
    )
    revision = str(labels.get(OCI_REVISION_LABEL) or "")
    if HEX_40.fullmatch(revision) is None:
        raise RuntimeError("manfred_candidate_retention_image_revision_invalid")
    return revision


def _probe_runtime_identity(
    port: int,
    *,
    expected_commit: str,
    oci_image_revision: str,
) -> dict[str, object]:
    try:
        identity = _candidate_version(
            f"http://127.0.0.1:{port}",
            expected_commit=expected_commit,
            oci_image_revision=oci_image_revision,
        )
    except (RuntimeError, ValueError) as exc:
        raise RuntimeError(
            "manfred_candidate_retention_runtime_identity_invalid"
        ) from exc
    if not isinstance(identity, dict):
        raise RuntimeError("manfred_candidate_retention_runtime_identity_invalid")
    return dict(identity)


def _project_rows(
    inventory: tuple[dict[str, object], ...], project: str
) -> tuple[dict[str, object], ...]:
    return tuple(row for row in inventory if row.get("project") == project)


def _candidate_projects(
    inventory: tuple[dict[str, object], ...],
) -> set[str]:
    projects: set[str] = set()
    for row in inventory:
        project = str(row.get("project") or "")
        if project == LIVE_COMPOSE_PROJECT:
            continue
        if project == LEGACY_CANDIDATE_PROJECT or project.startswith(
            PROJECT_NAME_PREFIX
        ):
            projects.add(project)
    return projects


def _sample_runtime(
    proof: RuntimeProof,
    inventory: tuple[dict[str, object], ...],
    image_revisions: dict[str, str],
) -> dict[str, object]:
    if proof.project == LIVE_COMPOSE_PROJECT:
        raise RuntimeError("manfred_candidate_retention_live_project_forbidden")
    rows = _project_rows(inventory, proof.project)
    if not rows:
        raise RuntimeError("manfred_candidate_retention_project_absent")
    services: dict[str, dict[str, object]] = {}
    for row in rows:
        service = str(row.get("service") or "")
        if service in services or service not in EXPECTED_SERVICES:
            raise RuntimeError("manfred_candidate_retention_candidate_topology_invalid")
        if row.get("running") is not True or row.get("health") != "healthy":
            raise RuntimeError("manfred_candidate_retention_candidate_health_invalid")
        services[service] = row
    if set(services) != EXPECTED_SERVICES:
        raise RuntimeError("manfred_candidate_retention_candidate_topology_invalid")
    for service, expected_container_id in (
        ("api", proof.api_container_id),
        ("gateway", proof.gateway_container_id),
    ):
        row = services[service]
        if (
            row.get("id") != expected_container_id
            or row.get("image_id") != proof.image_id
        ):
            raise RuntimeError("manfred_candidate_retention_container_binding_invalid")
    if proof.image_id not in image_revisions:
        image_revisions[proof.image_id] = _image_revision(proof.image_id)
    oci_revision = image_revisions[proof.image_id]
    live_identity = _probe_runtime_identity(
        proof.port,
        expected_commit=proof.revision,
        oci_image_revision=oci_revision,
    )
    if (
        oci_revision != proof.revision
        or live_identity != proof.runtime_version_identity
    ):
        raise RuntimeError("manfred_candidate_retention_four_way_identity_mismatch")
    return {
        "project": proof.project,
        "receipt_sha256": proof.receipt_sha256,
        "revision": proof.revision,
        "image_id": proof.image_id,
        "oci_image_revision": oci_revision,
        "containers": [
            {
                "service": service,
                "container_id": str(services[service]["id"]),
                "image_id": str(services[service]["image_id"]),
            }
            for service in sorted(EXPECTED_SERVICES)
        ],
        "runtime_version_identity": live_identity,
    }


def _identity_digest(identity: dict[str, object]) -> str:
    encoded = json.dumps(
        identity,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _safe_error(exc: RuntimeError) -> str:
    code = str(exc)
    if code.startswith("manfred_candidate_retention_"):
        return code
    return "manfred_candidate_retention_validation_failed"


def _quarantine_row(
    project: str,
    *,
    runtime_schema: str,
    reason: str,
    error: str = "",
) -> dict[str, object]:
    row: dict[str, object] = {
        "project": project,
        "runtime_schema": runtime_schema,
        "qualification": "ineligible",
        "quarantined": True,
        "quarantine_reason": reason,
        "automatic_retirement_authorized": False,
    }
    if error:
        row["error"] = error
    return row


def _base_report(*, apply: bool) -> dict[str, object]:
    return {
        "schema": REPORT_SCHEMA,
        "observed_at": _utc_now(),
        "mode": "apply_requested" if apply else "dry_run",
        "controller_posture": "quarantine_only",
        "destructive_apply_supported": False,
        "automatic_retirement_authorized": False,
        "mutation_performed": False,
        "live_compose_project": LIVE_COMPOSE_PROJECT,
        "live_compose_project_protected": True,
        "docker_access": "read_only",
        "limitations": [
            "persistent_long_running_keeper_stability_not_implemented",
            "exact_resource_revalidation_and_destructive_apply_not_implemented",
        ],
    }


def _evaluate_locked(
    *,
    postures: list[dict[str, object]],
    apply: bool,
    sample_spacing_seconds: float,
    sleep: Callable[[float], None],
    lock_evidence: dict[str, object],
) -> dict[str, object]:
    report = _base_report(apply=apply)
    report["lock"] = dict(lock_evidence)
    if len(postures) > 128 or any(not isinstance(row, dict) for row in postures):
        raise RuntimeError("manfred_candidate_retention_postures_invalid")
    projects = [str(row.get("project") or "") for row in postures]
    if any(not project for project in projects) or len(projects) != len(set(projects)):
        raise RuntimeError("manfred_candidate_retention_postures_invalid")
    registered_projects = set(projects)
    candidates: dict[str, dict[str, object]] = {}
    proofs: dict[str, RuntimeProof] = {}

    for raw_posture in postures:
        posture = dict(raw_posture)
        project = str(posture.get("project") or "")
        schema = str(posture.get("runtime_schema") or "")
        if project == LIVE_COMPOSE_PROJECT:
            candidates[project] = _quarantine_row(
                project,
                runtime_schema=schema or "unknown",
                reason="live_project_reserved",
            )
            continue
        if schema == RUNTIME_SCHEMA_V3 or posture.get("legacy") is True:
            candidates[project] = _quarantine_row(
                project,
                runtime_schema=RUNTIME_SCHEMA_V3,
                reason="legacy_runtime_receipt_v3",
            )
            continue
        if schema != RUNTIME_SCHEMA_V4:
            candidates[project] = _quarantine_row(
                project,
                runtime_schema=schema or "unknown",
                reason="unsupported_runtime_receipt_schema",
            )
            continue
        try:
            proofs[project] = _parse_v4_proof(posture)
        except RuntimeError as exc:
            candidates[project] = _quarantine_row(
                project,
                runtime_schema=RUNTIME_SCHEMA_V4,
                reason="registered_v4_receipt_invalid",
                error=_safe_error(exc),
            )

    initial_inventory = _container_inventory()
    initial_samples: dict[str, dict[str, object]] = {}
    initial_revisions: dict[str, str] = {}
    for project, proof in sorted(proofs.items()):
        try:
            initial_samples[project] = _sample_runtime(
                proof,
                initial_inventory,
                initial_revisions,
            )
        except RuntimeError as exc:
            candidates[project] = _quarantine_row(
                project,
                runtime_schema=RUNTIME_SCHEMA_V4,
                reason="runtime_identity_not_qualified",
                error=_safe_error(exc),
            )

    if initial_samples:
        sleep(sample_spacing_seconds)
    final_inventory = _container_inventory()
    final_revisions: dict[str, str] = {}
    stable_projects: list[str] = []
    for project, initial in sorted(initial_samples.items()):
        proof = proofs[project]
        try:
            final = _sample_runtime(proof, final_inventory, final_revisions)
            if final != initial:
                raise RuntimeError(
                    "manfred_candidate_retention_sample_identity_changed"
                )
        except RuntimeError as exc:
            candidates[project] = _quarantine_row(
                project,
                runtime_schema=RUNTIME_SCHEMA_V4,
                reason="runtime_identity_stability_revoked",
                error=_safe_error(exc),
            )
            continue
        stable_projects.append(project)
        candidates[project] = {
            "project": project,
            "runtime_schema": RUNTIME_SCHEMA_V4,
            "qualification": "observed_identity_stable",
            "quarantined": False,
            "four_way_runtime_identity_verified": True,
            "receipt_container_image_identity_stable": True,
            "live_container_image_identity_stable": True,
            "identity_bound_sample_count": 2,
            "sample_identity_sha256": _identity_digest(final),
            "persistent_keeper_qualification": False,
            "automatic_retirement_authorized": False,
        }

    discovered_projects = _candidate_projects(initial_inventory) | _candidate_projects(
        final_inventory
    )
    for project in sorted(discovered_projects - registered_projects):
        candidates[project] = _quarantine_row(
            project,
            runtime_schema="unknown",
            reason="unregistered_candidate_project",
        )

    stable_projects.sort(
        key=lambda project: (proofs[project].observed_at, project),
        reverse=True,
    )
    observed_keeper: dict[str, object] | None = None
    if stable_projects:
        keeper_project = stable_projects[0]
        keeper = proofs[keeper_project]
        observed_keeper = {
            "project": keeper.project,
            "runtime_schema": RUNTIME_SCHEMA_V4,
            "receipt_sha256": keeper.receipt_sha256,
            "revision": keeper.revision,
            "image_id": keeper.image_id,
            "identity_bound_sample_count": 2,
            "persistent_keeper_qualification": False,
            "automatic_retirement_authorized": False,
        }
        for project in stable_projects[1:]:
            candidates[project].update(
                {
                    "quarantined": True,
                    "quarantine_reason": "stable_candidate_not_observed_keeper",
                }
            )

    rows = [candidates[project] for project in sorted(candidates)]
    report.update(
        {
            "status": "blocked" if apply else "pass",
            "registered_projects": sorted(registered_projects),
            "observed_keeper": observed_keeper,
            "candidates": rows,
            "quarantined_projects": [
                row for row in rows if row.get("quarantined") is True
            ],
            "unknown_projects": sorted(discovered_projects - registered_projects),
            "sample_spacing_seconds": sample_spacing_seconds,
            "sample_count": 2 if initial_samples else 0,
            "live_project_container_count": sum(
                1
                for row in final_inventory
                if row.get("project") == LIVE_COMPOSE_PROJECT
            ),
        }
    )
    if apply:
        report["apply_block_reason"] = (
            "manfred_candidate_retention_destructive_apply_not_implemented"
        )
    return report


def evaluate_retention(
    *,
    registry_path: Path | None = None,
    lock_path: Path | None = None,
    apply: bool = False,
    skip_if_busy: bool = False,
    sample_spacing_seconds: float = 5.0,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, object]:
    if (
        type(sample_spacing_seconds) not in {int, float}
        or not 1 <= float(sample_spacing_seconds) <= 300
    ):
        raise RuntimeError("manfred_candidate_retention_sample_spacing_invalid")
    registry = Path(registry_path or default_registry_path())
    fleet_lock = Path(lock_path or FLEET_LOCK_PATH)
    with hold_candidate_fleet_lock(
        skip_if_busy=skip_if_busy,
        lock_path=fleet_lock,
    ) as lock_evidence:
        if lock_evidence is None:
            report = _base_report(apply=apply)
            report.update(
                {
                    "status": "skipped",
                    "skip_reason": "manfred_candidate_fleet_lock_held",
                    "registered_projects": [],
                    "observed_keeper": None,
                    "candidates": [],
                    "quarantined_projects": [],
                    "unknown_projects": [],
                    "sample_count": 0,
                }
            )
            return report
        postures = registered_candidate_receipt_postures(registry_path=registry)
        return _evaluate_locked(
            postures=postures,
            apply=apply,
            sample_spacing_seconds=float(sample_spacing_seconds),
            sleep=sleep,
            lock_evidence=dict(lock_evidence),
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Audit Manfred Memorial candidates under the fleet lock; "
            "destructive retention is intentionally unavailable."
        )
    )
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--lock-path", type=Path)
    parser.add_argument(
        "--sample-spacing-seconds",
        type=float,
        default=5.0,
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Request apply; this bounded controller fails closed without mutation.",
    )
    parser.add_argument("--skip-if-busy", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = evaluate_retention(
            registry_path=args.registry,
            lock_path=args.lock_path,
            apply=args.apply,
            skip_if_busy=args.skip_if_busy,
            sample_spacing_seconds=args.sample_spacing_seconds,
        )
    except RuntimeError as exc:
        report = _base_report(apply=args.apply)
        report.update(
            {
                "status": "error",
                "error": _safe_error(exc),
                "registered_projects": [],
                "observed_keeper": None,
                "candidates": [],
                "quarantined_projects": [],
                "unknown_projects": [],
            }
        )
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 1
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 2 if report.get("status") == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
