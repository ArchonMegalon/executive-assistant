#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.manfred_candidate_fleet_lock import hold_candidate_fleet_lock
from scripts.manfred_candidate_registry import (
    clear_candidate_pending,
    compact_candidate_registry,
    default_registry_path,
    operator_state_root,
    register_candidate_receipt,
    registered_candidate_pending,
    registered_candidate_receipts,
)
from scripts.prepare_manfred_memorial_candidate import (
    PROJECT_NAME_PREFIX,
    _validate_project_name,
)
from scripts.run_manfred_memorial_candidate import (  # noqa: E402
    _hold_port_lock,
    _hold_project_lock,
)


RECEIPT_SCHEMA = "ea.manfred_memorial_candidate_retention.v1"
STATE_SCHEMA = "ea.manfred_memorial_candidate_retention_state.v1"
RUNTIME_RECEIPT_SCHEMA = "ea.manfred_memorial_candidate_runtime.v3"
RUNTIME_RECEIPT_SCHEMAS = frozenset(
    {
        RUNTIME_RECEIPT_SCHEMA,
        "ea.manfred_memorial_candidate_runtime.v4",
    }
)
LEGACY_COMPOSE_PROJECT = "ea-manfred-candidate"
EXPECTED_SERVICES = ("api", "gateway", "postgres", "redis")
EXPECTED_NETWORKS = ("backend", "ingress")
EXPECTED_VOLUMES = ("artifacts", "postgres_data", "redis_data")
EXPECTED_SERVICE_IMAGES = {
    "postgres": "postgres:16-alpine@sha256:16bc17c64a573ef34162af9298258d1aec548232985b33ed7b1eac33ba35c229",
    "redis": "redis:7-alpine@sha256:6ab0b6e7381779332f97b8ca76193e45b0756f38d4c0dcda72dbb3c32061ab99",
}
CONTAINER_COMPOSE_LABELS = frozenset(
    {
        "com.docker.compose.config-hash",
        "com.docker.compose.container-number",
        "com.docker.compose.depends_on",
        "com.docker.compose.image",
        "com.docker.compose.oneoff",
        "com.docker.compose.project",
        "com.docker.compose.project.config_files",
        "com.docker.compose.project.environment_file",
        "com.docker.compose.project.working_dir",
        "com.docker.compose.replace",
        "com.docker.compose.service",
        "com.docker.compose.version",
    }
)
NETWORK_COMPOSE_LABELS = frozenset(
    {
        "com.docker.compose.config-hash",
        "com.docker.compose.network",
        "com.docker.compose.project",
        "com.docker.compose.version",
    }
)
VOLUME_COMPOSE_LABELS = frozenset(
    {
        "com.docker.compose.config-hash",
        "com.docker.compose.project",
        "com.docker.compose.version",
        "com.docker.compose.volume",
    }
)
MAX_RECEIPTS = 128
MAX_RECEIPT_BYTES = 1024 * 1024
MAX_DOCKER_RESOURCES = 4096
IMAGE_RETENTION_GRACE_SECONDS = 24 * 60 * 60
# Rollback-image grace is unconditional. Keep the receipt field at zero for
# backwards-compatible consumers that display the former disk threshold.
IMAGE_GRACE_MINIMUM_FREE_BYTES = 0
MINIMUM_KEEPER_STABILITY_SECONDS = 15 * 60
MINIMUM_SAMPLE_SPACING_SECONDS = 5 * 60
MAXIMUM_SAMPLE_GAP_SECONDS = 7 * 60 + 30
MAX_STABILITY_SAMPLES = 4
MAX_RETIRE_PROJECTS_PER_RUN = 4
MAX_REMOVE_IMAGES_PER_RUN = 4
RETIREMENT_APPLY_BUDGET_SECONDS = 75 * 60
RETIREMENT_LEDGER_SAFETY_SECONDS = 5 * 60
RETIRED_IMAGE_LEDGER_WINDOW_SECONDS = (
    IMAGE_RETENTION_GRACE_SECONDS
    + RETIREMENT_APPLY_BUDGET_SECONDS
    + RETIREMENT_LEDGER_SAFETY_SECONDS
)
MAX_AUTOMATIC_RECEIPTS = 4096
HEX_40 = re.compile(r"[0-9a-f]{40}")
HEX_64 = re.compile(r"[0-9a-f]{64}")
IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}")
IMAGE_LOCATOR = re.compile(r"ea-runtime:(?:manfred|memorial)-[0-9a-f]{40}")
REPO_DIGEST = re.compile(r"[^@\s]+@sha256:[0-9a-f]{64}")
PENDING_INTENT_TTL_SECONDS = 2 * 60 * 60
AUTOMATIC_RECEIPT_NAME = re.compile(
    r"retention-[0-9]{8}T[0-9]{6}Z-[0-9]+-[0-9a-f]{8}(?:\.intent)?\.json"
)
COMPOSE_ENVIRONMENT_FILE_LABEL = "com.docker.compose.project.environment_file"
AUTOMATIC_RUNTIME_RECEIPT_RELATIVE = Path("receipts/candidate-runtime-v3.json")
LIVE_EA_PROJECT = "ea"
LIVE_EA_API_CONTAINER_NAME = "ea-api"
LIVE_EA_API_SERVICE = "ea-api"
LIVE_EA_EPHEMERAL_PROBE_NAME = "ea-memorial-proxy-probe"
COMPOSE_ONEOFF_LABEL = "com.docker.compose.oneoff"


@dataclass(frozen=True)
class RuntimeProof:
    schema: str
    project: str | None
    observed_at: datetime
    image: str
    image_id: str
    revision: str
    api_container_id: str
    gateway_container_id: str | None
    port: int
    receipt_sha256: str


@dataclass(frozen=True)
class Inventory:
    containers: tuple[dict[str, object], ...]
    networks: tuple[dict[str, object], ...]
    volumes: tuple[dict[str, object], ...]
    images: dict[str, dict[str, object]]


@dataclass(frozen=True)
class Candidate:
    proof: RuntimeProof
    containers: tuple[dict[str, object], ...]
    networks: tuple[dict[str, object], ...]
    volumes: tuple[dict[str, object], ...]
    complete: bool
    healthy: bool

    @property
    def project(self) -> str:
        if self.proof.project is None:  # pragma: no cover - bound before creation
            raise RuntimeError("manfred_candidate_retention_proof_unbound")
        return self.proof.project


class _KeeperStabilizing(RuntimeError):
    def __init__(self, keeper: Candidate, age_seconds: int) -> None:
        super().__init__("manfred_candidate_retention_keeper_stabilizing")
        self.keeper = keeper
        self.age_seconds = age_seconds


@dataclass(frozen=True)
class RetentionPlan:
    keeper: Candidate
    actual_newest: Candidate
    keeper_selection: str
    retirees: tuple[Candidate, ...]
    pending_retirees: tuple[Candidate, ...]
    protected_newer_candidates: tuple[Candidate, ...]
    removable_image_ids: tuple[str, ...]
    preserved_images: tuple[dict[str, str], ...]
    live_before: dict[str, object]
    quarantined_projects: tuple[dict[str, object], ...]
    root_free_bytes: int
    deferred_image_projects: tuple[str, ...]
    grace_candidates: tuple[dict[str, object], ...]
    pending_intent_quarantine: tuple[dict[str, object], ...]
    unknown_project_quarantine: tuple[dict[str, object], ...] = ()
    removable_image_aliases: tuple[dict[str, object], ...] = ()


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
        "SSH_AUTH_SOCK",
        "XDG_RUNTIME_DIR",
    ):
        value = str(os.environ.get(name) or "").strip()
        if value:
            environment[name] = value
    return environment


def _run(argv: list[str], *, timeout: int = 60) -> bytes:
    if not argv or argv[0] != "docker":
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
        raise RuntimeError(
            "manfred_candidate_retention_docker_command_failed"
        ) from exc
    return completed.stdout


def _json_rows(raw: bytes, *, error: str) -> list[dict[str, object]]:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(error) from exc
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise RuntimeError(error)
    return [dict(row) for row in value]


def _listed(argv: list[str]) -> list[str]:
    try:
        values = [
            line.strip()
            for line in _run(argv, timeout=30)
            .decode("utf-8", errors="strict")
            .splitlines()
            if line.strip()
        ]
    except UnicodeDecodeError as exc:
        raise RuntimeError("manfred_candidate_retention_docker_list_invalid") from exc
    if len(values) != len(set(values)) or len(values) > MAX_DOCKER_RESOURCES:
        raise RuntimeError("manfred_candidate_retention_docker_list_invalid")
    return sorted(values)


def _existing_image_ids() -> set[str]:
    try:
        values = {
            line.strip()
            for line in _run(
                ["docker", "image", "ls", "--all", "--quiet", "--no-trunc"],
                timeout=30,
            )
            .decode("ascii", errors="strict")
            .splitlines()
            if line.strip()
        }
    except UnicodeDecodeError as exc:
        raise RuntimeError("manfred_candidate_retention_image_list_invalid") from exc
    if len(values) > MAX_DOCKER_RESOURCES or any(
        IMAGE_ID.fullmatch(value) is None for value in values
    ):
        raise RuntimeError("manfred_candidate_retention_image_list_invalid")
    return values


def _inspect(kind: str, identifiers: list[str]) -> list[dict[str, object]]:
    if kind not in {"container", "image", "network", "volume"}:
        raise RuntimeError("manfred_candidate_retention_inspect_kind_invalid")
    rows: list[dict[str, object]] = []
    for offset in range(0, len(identifiers), 128):
        batch = identifiers[offset : offset + 128]
        rows.extend(
            _json_rows(
                _run(["docker", kind, "inspect", *batch], timeout=60),
                error=f"manfred_candidate_retention_{kind}_inspection_invalid",
            )
        )
    if len(rows) != len(identifiers):
        raise RuntimeError(f"manfred_candidate_retention_{kind}_inspection_invalid")
    return rows


def _normalize_container(row: dict[str, object]) -> dict[str, object]:
    identifier = str(row.get("Id") or "")
    name = str(row.get("Name") or "").lstrip("/")
    config = dict(row.get("Config") or {})
    labels = {str(key): str(value) for key, value in dict(config.get("Labels") or {}).items()}
    state = dict(row.get("State") or {})
    health = dict(state.get("Health") or {})
    network_settings = dict(row.get("NetworkSettings") or {})
    networks = tuple(sorted(str(value) for value in dict(network_settings.get("Networks") or {})))
    mounts: list[dict[str, str]] = []
    for raw_mount in list(row.get("Mounts") or []):
        if not isinstance(raw_mount, dict):
            raise RuntimeError("manfred_candidate_retention_container_mount_invalid")
        mounts.append(
            {
                "type": str(raw_mount.get("Type") or ""),
                "name": str(raw_mount.get("Name") or ""),
                "destination": str(raw_mount.get("Destination") or ""),
            }
        )
    bindings = dict(dict(row.get("HostConfig") or {}).get("PortBindings") or {})
    return {
        "id": identifier,
        "name": name,
        "image_id": str(row.get("Image") or ""),
        "image_ref": str(config.get("Image") or ""),
        "labels": labels,
        "project": labels.get("com.docker.compose.project", ""),
        "service": labels.get("com.docker.compose.service", ""),
        "running": state.get("Running") is True,
        "status": str(state.get("Status") or ""),
        "health": str(health.get("Status") or ""),
        "started_at": str(state.get("StartedAt") or ""),
        "networks": networks,
        "mounts": tuple(sorted(mounts, key=lambda item: (item["name"], item["destination"]))),
        "port_bindings": bindings,
    }


def _normalize_network(row: dict[str, object]) -> dict[str, object]:
    attachable = row.get("Attachable")
    if type(attachable) is not bool:
        raise RuntimeError(
            "manfred_candidate_retention_network_attachable_invalid"
        )
    labels = {str(key): str(value) for key, value in dict(row.get("Labels") or {}).items()}
    return {
        "id": str(row.get("Id") or ""),
        "name": str(row.get("Name") or ""),
        "labels": labels,
        "project": labels.get("com.docker.compose.project", ""),
        "network": labels.get("com.docker.compose.network", ""),
        "driver": str(row.get("Driver") or ""),
        "internal": row.get("Internal") is True,
        "attachable": attachable,
        "container_ids": tuple(sorted(str(value) for value in dict(row.get("Containers") or {}))),
    }


def _normalize_volume(row: dict[str, object]) -> dict[str, object]:
    labels = {str(key): str(value) for key, value in dict(row.get("Labels") or {}).items()}
    options = {
        str(key): str(value)
        for key, value in dict(row.get("Options") or {}).items()
    }
    return {
        "name": str(row.get("Name") or ""),
        "labels": labels,
        "project": labels.get("com.docker.compose.project", ""),
        "volume": labels.get("com.docker.compose.volume", ""),
        "driver": str(row.get("Driver") or ""),
        "scope": str(row.get("Scope") or ""),
        # Docker volumes have no immutable public ID.  Bind the creation and
        # backing-path metadata so a remove/recreate under the same name cannot
        # satisfy a previously written deletion intent.
        "created_at": str(row.get("CreatedAt") or ""),
        "mountpoint": str(row.get("Mountpoint") or ""),
        "options": options,
    }


def _normalize_image(row: dict[str, object]) -> dict[str, object]:
    if "RepoDigests" not in row:
        raise RuntimeError(
            "manfred_candidate_retention_image_repo_digests_invalid"
        )
    raw_digests = row["RepoDigests"]
    if raw_digests is None:
        raw_digests = []
    if not isinstance(raw_digests, list) or len(raw_digests) > MAX_DOCKER_RESOURCES:
        raise RuntimeError(
            "manfred_candidate_retention_image_repo_digests_invalid"
        )
    if (
        any(
            not isinstance(value, str) or REPO_DIGEST.fullmatch(value) is None
            for value in raw_digests
        )
        or len(raw_digests) != len(set(raw_digests))
    ):
        raise RuntimeError(
            "manfred_candidate_retention_image_repo_digests_invalid"
        )
    repo_digests = tuple(sorted(raw_digests))
    config = dict(row.get("Config") or {})
    return {
        "id": str(row.get("Id") or ""),
        "repo_tags": tuple(sorted(str(value) for value in list(row.get("RepoTags") or []))),
        "repo_digests": repo_digests,
        "labels": {str(key): str(value) for key, value in dict(config.get("Labels") or {}).items()},
        "environment": tuple(str(value) for value in list(config.get("Env") or [])),
    }


def _normalized_image_aliases(
    image: dict[str, object],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    repo_tags = image.get("repo_tags")
    repo_digests = image.get("repo_digests")
    if (
        not isinstance(repo_tags, tuple)
        or any(not isinstance(value, str) or not value for value in repo_tags)
        or len(repo_tags) != len(set(repo_tags))
        or not isinstance(repo_digests, tuple)
        or any(
            not isinstance(value, str) or REPO_DIGEST.fullmatch(value) is None
            for value in repo_digests
        )
        or len(repo_digests) != len(set(repo_digests))
    ):
        raise RuntimeError("manfred_candidate_retention_image_aliases_invalid")
    return tuple(sorted(repo_tags)), tuple(sorted(repo_digests))


def _image_alias_snapshot(image: dict[str, object]) -> dict[str, object]:
    repo_tags, repo_digests = _normalized_image_aliases(image)
    image_id = str(image.get("id") or "")
    if IMAGE_ID.fullmatch(image_id) is None:
        raise RuntimeError("manfred_candidate_retention_image_aliases_invalid")
    return {
        "image_id": image_id,
        "repo_tags": list(repo_tags),
        "repo_digests": list(repo_digests),
    }


def _unique(rows: list[dict[str, object]], key: str, error: str) -> tuple[dict[str, object], ...]:
    values = [str(row.get(key) or "") for row in rows]
    if any(not value for value in values) or len(values) != len(set(values)):
        raise RuntimeError(error)
    return tuple(sorted(rows, key=lambda row: str(row[key])))


def _discover_inventory(image_ids: set[str]) -> Inventory:
    container_ids = _listed(["docker", "container", "ls", "--all", "--quiet"])
    network_ids = _listed(["docker", "network", "ls", "--quiet"])
    volume_names = _listed(["docker", "volume", "ls", "--quiet"])
    containers = [_normalize_container(row) for row in _inspect("container", container_ids)]
    networks = [_normalize_network(row) for row in _inspect("network", network_ids)]
    volumes = [_normalize_volume(row) for row in _inspect("volume", volume_names)]
    image_rows = [_normalize_image(row) for row in _inspect("image", sorted(image_ids))]
    images = {str(row["id"]): row for row in image_rows}
    if set(images) != image_ids:
        raise RuntimeError("manfred_candidate_retention_image_inspection_invalid")
    return Inventory(
        containers=_unique(containers, "id", "manfred_candidate_retention_container_inventory_invalid"),
        networks=_unique(networks, "id", "manfred_candidate_retention_network_inventory_invalid"),
        volumes=_unique(volumes, "name", "manfred_candidate_retention_volume_inventory_invalid"),
        images=images,
    )


def _read_receipt(path: Path) -> tuple[dict[str, object], str]:
    path = Path(path).expanduser()
    absolute = path if path.is_absolute() else Path.cwd() / path
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
            chunk = os.read(descriptor, min(65536, MAX_RECEIPT_BYTES + 1 - len(content)))
            if not chunk:
                break
            content += chunk
        after = os.fstat(descriptor)
        if (
            len(content) != before.st_size
            or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        ):
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


def _parse_timestamp(value: object) -> datetime:
    text = str(value or "")
    try:
        parsed = datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise RuntimeError("manfred_candidate_retention_receipt_timestamp_invalid") from exc
    return parsed


def _parse_runtime_proof(payload: dict[str, object], digest: str) -> RuntimeProof:
    schema = str(payload.get("schema") or "")
    if schema not in RUNTIME_RECEIPT_SCHEMAS:
        raise RuntimeError("manfred_candidate_retention_receipt_schema_invalid")
    image = str(payload.get("image") or "")
    image_id = str(payload.get("image_id") or "")
    revision = str(payload.get("image_source_revision") or "")
    api_container_id = str(payload.get("candidate_api_container_id") or "")
    try:
        port = int(payload.get("candidate_port"))
    except (TypeError, ValueError) as exc:
        raise RuntimeError("manfred_candidate_retention_receipt_port_invalid") from exc
    try:
        project = _validate_project_name(payload.get("compose_project"))
    except ValueError as exc:
        raise RuntimeError("manfred_candidate_retention_receipt_project_invalid") from exc
    candidate_images = dict(payload.get("candidate_container_images") or {})
    api_evidence = dict(candidate_images.get("api") or {})
    gateway_evidence = dict(candidate_images.get("gateway") or {})
    gateway_container_id = str(gateway_evidence.get("container_id") or "")
    named = dict(payload.get("candidate_named_resources") or {})
    first_smoke = payload.get("first_smoke_checks")
    second_smoke = payload.get("second_smoke_checks")
    if (
        str(api_evidence.get("container_id") or "") != api_container_id
        or str(api_evidence.get("image_id") or "") != image_id
        or str(gateway_evidence.get("image_id") or "") != image_id
        or named != _expected_named_resources(project)
        or payload.get("projection_tree_revalidated") is not True
        or not isinstance(first_smoke, list)
        or not first_smoke
        or not isinstance(second_smoke, list)
        or not second_smoke
        or payload.get("contribution_survived_restart") is not True
    ):
        raise RuntimeError("manfred_candidate_retention_receipt_binding_invalid")
    if (
        payload.get("status") != "pass"
        or payload.get("candidate_left_running_for_soak") is not True
        or payload.get("live_ea_api_unchanged") is not True
        or payload.get("promotion_authority") is not False
        or IMAGE_LOCATOR.fullmatch(image) is None
        or IMAGE_ID.fullmatch(image_id) is None
        or HEX_40.fullmatch(revision) is None
        or str(payload.get("runtime_source_revision") or "") != revision
        or not (1024 <= port <= 65535)
        or HEX_64.fullmatch(api_container_id) is None
        or HEX_64.fullmatch(gateway_container_id) is None
    ):
        raise RuntimeError("manfred_candidate_retention_receipt_invalid")
    return RuntimeProof(
        schema=schema,
        project=project,
        observed_at=_parse_timestamp(payload.get("observed_at")),
        image=image,
        image_id=image_id,
        revision=revision,
        api_container_id=api_container_id,
        gateway_container_id=gateway_container_id,
        port=port,
        receipt_sha256=digest,
    )


def _load_runtime_proofs(paths: list[Path]) -> tuple[RuntimeProof, ...]:
    if not paths or len(paths) > MAX_RECEIPTS:
        raise RuntimeError("manfred_candidate_retention_receipt_count_invalid")
    proofs: list[RuntimeProof] = []
    digests: set[str] = set()
    for path in paths:
        payload, digest = _read_receipt(path)
        if digest in digests:
            raise RuntimeError("manfred_candidate_retention_receipt_duplicate")
        digests.add(digest)
        proofs.append(_parse_runtime_proof(payload, digest))
    return tuple(proofs)


def _expected_named_resources(project: str) -> dict[str, list[str]]:
    return {
        "containers": sorted(
            [f"{project}-{service}-1" for service in EXPECTED_SERVICES]
            + [f"{project}_{service}_1" for service in EXPECTED_SERVICES]
        ),
        "networks": [f"{project}_{name}" for name in EXPECTED_NETWORKS],
        "volumes": [f"{project}_{name}" for name in EXPECTED_VOLUMES],
    }


def _project_from_name(kind: str, name: str) -> str | None:
    suffixes: list[str] = []
    if kind == "container":
        suffixes = [
            f"{separator}{service}{separator}1"
            for service in EXPECTED_SERVICES
            for separator in ("-", "_")
        ]
    elif kind == "network":
        suffixes = [f"_{value}" for value in EXPECTED_NETWORKS]
    elif kind == "volume":
        suffixes = [f"_{value}" for value in EXPECTED_VOLUMES]
    matches: list[str] = []
    for suffix in suffixes:
        if name.startswith(PROJECT_NAME_PREFIX) and name.endswith(suffix):
            project = name[: -len(suffix)]
            if project == LEGACY_COMPOSE_PROJECT:
                continue
            try:
                matches.append(_validate_project_name(project))
            except ValueError as exc:
                raise RuntimeError("manfred_candidate_retention_resource_name_invalid") from exc
    if len(set(matches)) > 1:
        raise RuntimeError("manfred_candidate_retention_resource_name_ambiguous")
    return matches[0] if matches else None


def _candidate_projects(inventory: Inventory) -> set[str]:
    projects: set[str] = set()
    for kind, rows in (
        ("container", inventory.containers),
        ("network", inventory.networks),
        ("volume", inventory.volumes),
    ):
        for row in rows:
            label_project = str(row.get("project") or "")
            if label_project.startswith(PROJECT_NAME_PREFIX):
                try:
                    projects.add(_validate_project_name(label_project))
                except ValueError as exc:
                    raise RuntimeError("manfred_candidate_retention_resource_project_invalid") from exc
            named_project = _project_from_name(kind, str(row.get("name") or ""))
            if named_project:
                projects.add(named_project)
    return projects


def _legacy_quarantine(inventory: Inventory) -> tuple[dict[str, object], ...]:
    def legacy_name(kind: str, name: str) -> bool:
        if kind == "container":
            return any(
                name
                in {
                    f"{LEGACY_COMPOSE_PROJECT}-{service}-1",
                    f"{LEGACY_COMPOSE_PROJECT}_{service}_1",
                }
                for service in EXPECTED_SERVICES
            )
        if kind == "network":
            return name in {
                f"{LEGACY_COMPOSE_PROJECT}_{value}" for value in EXPECTED_NETWORKS
            }
        return name in {
            f"{LEGACY_COMPOSE_PROJECT}_{value}" for value in EXPECTED_VOLUMES
        }

    containers = [
        row
        for row in inventory.containers
        if row.get("project") == LEGACY_COMPOSE_PROJECT
        or legacy_name("container", str(row.get("name") or ""))
    ]
    networks = [
        row
        for row in inventory.networks
        if row.get("project") == LEGACY_COMPOSE_PROJECT
        or legacy_name("network", str(row.get("name") or ""))
    ]
    volumes = [
        row
        for row in inventory.volumes
        if row.get("project") == LEGACY_COMPOSE_PROJECT
        or legacy_name("volume", str(row.get("name") or ""))
    ]
    if not containers and not networks and not volumes:
        return ()
    evidence = {
        "container_ids": sorted(str(row.get("id") or "") for row in containers),
        "network_ids": sorted(str(row.get("id") or "") for row in networks),
        "volume_names": sorted(str(row.get("name") or "") for row in volumes),
    }
    digest = hashlib.sha256(
        json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return (
        {
            "project": LEGACY_COMPOSE_PROJECT,
            "reason": "legacy_v2_unbound_manual_only",
            "container_count": len(containers),
            "network_count": len(networks),
            "volume_count": len(volumes),
            "resource_digest_sha256": digest,
            "automatic_retirement_authorized": False,
        },
    )


def _pending_project_resources(
    project: str, inventory: Inventory
) -> dict[str, list[str]]:
    containers = sorted(
        str(row.get("id") or "")
        for row in inventory.containers
        if row.get("project") == project
        or _project_from_name("container", str(row.get("name") or "")) == project
    )
    networks = sorted(
        str(row.get("id") or "")
        for row in inventory.networks
        if row.get("project") == project
        or _project_from_name("network", str(row.get("name") or "")) == project
    )
    volumes = sorted(
        str(row.get("name") or "")
        for row in inventory.volumes
        if row.get("project") == project
        or _project_from_name("volume", str(row.get("name") or "")) == project
    )
    return {
        "container_ids": containers,
        "network_ids": networks,
        "volume_names": volumes,
    }


def _unregistered_project_quarantine(
    projects: set[str], inventory: Inventory
) -> tuple[dict[str, object], ...]:
    quarantined: list[dict[str, object]] = []
    for project in sorted(projects):
        resources = _pending_project_resources(project, inventory)
        if not any(resources.values()):
            raise RuntimeError(
                "manfred_candidate_retention_unregistered_project_missing"
            )
        digest = hashlib.sha256(
            json.dumps(
                resources, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()
        quarantined.append(
            {
                "project": project,
                "reason": "unregistered_candidate_project",
                "container_count": len(resources["container_ids"]),
                "network_count": len(resources["network_ids"]),
                "volume_count": len(resources["volume_names"]),
                "resource_digest_sha256": digest,
                "automatic_retirement_authorized": False,
                "operator_action_required": True,
            }
        )
    return tuple(quarantined)


def _pending_intent_status(
    pending: list[dict[str, object]],
    inventory: Inventory,
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    observed_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    projects = _candidate_projects(inventory)
    active_projects: set[str] = set()
    quarantine: list[dict[str, object]] = []
    absent: list[dict[str, object]] = []
    for entry in pending:
        project = str(entry["project"])
        created_at = _parse_timestamp(entry["created_at"])
        age_seconds = int(observed_at.timestamp() - created_at.timestamp())
        if age_seconds < 0:
            raise RuntimeError("manfred_candidate_retention_pending_clock_regressed")
        expired = age_seconds >= PENDING_INTENT_TTL_SECONDS
        if project not in projects:
            absent.append(
                {
                    "project": project,
                    "created_at": str(entry["created_at"]),
                    "age_seconds": age_seconds,
                    "ttl_seconds": PENDING_INTENT_TTL_SECONDS,
                    "ttl_expired": expired,
                    "resources_present": False,
                }
            )
            continue
        active_projects.add(project)
        resources = _pending_project_resources(project, inventory)
        digest = hashlib.sha256(
            json.dumps(
                resources, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()
        quarantine.append(
            {
                "project": project,
                "created_at": str(entry["created_at"]),
                "age_seconds": age_seconds,
                "ttl_seconds": PENDING_INTENT_TTL_SECONDS,
                "ttl_expired": expired,
                "resources_present": True,
                "container_count": len(resources["container_ids"]),
                "network_count": len(resources["network_ids"]),
                "volume_count": len(resources["volume_names"]),
                "resource_digest_sha256": digest,
                "automatic_retirement_authorized": False,
                "operator_action_required": expired,
                "reason": "pending_runtime_proof_intent",
            }
        )
    return {
        "active_projects": active_projects,
        "quarantined": tuple(sorted(quarantine, key=lambda row: str(row["project"]))),
        "absent": tuple(sorted(absent, key=lambda row: str(row["project"]))),
    }


def _clear_expired_absent_pending(
    status: dict[str, object], *, registry_path: Path
) -> tuple[dict[str, object], ...]:
    cleared: list[dict[str, object]] = []
    for row in tuple(status.get("absent") or ()):
        if not isinstance(row, dict) or row.get("ttl_expired") is not True:
            continue
        project = str(row.get("project") or "")
        evidence = clear_candidate_pending(project, registry_path=registry_path)
        if evidence.get("pending_cleared") is not True:
            raise RuntimeError(
                "manfred_candidate_retention_pending_reconciliation_changed"
            )
        cleared.append(
            {
                "project": project,
                "reason": "expired_absent_pending_intent",
                "registry_only": True,
            }
        )
    return tuple(cleared)


def _bind_proofs(
    proofs: tuple[RuntimeProof, ...], inventory: Inventory, projects: set[str]
) -> dict[str, RuntimeProof]:
    by_project: dict[str, list[RuntimeProof]] = {}
    for proof in proofs:
        if proof.project in projects:
            by_project.setdefault(str(proof.project), []).append(proof)
    if set(by_project) != projects or any(len(values) != 1 for values in by_project.values()):
        raise RuntimeError("manfred_candidate_retention_receipt_project_ambiguous")
    return {project: values[0] for project, values in by_project.items()}


def _historical_image_quarantine(
    proofs: tuple[RuntimeProof, ...], inventory: Inventory
) -> tuple[dict[str, object], ...]:
    by_image: dict[str, list[RuntimeProof]] = {}
    for proof in proofs:
        if proof.image_id in inventory.images:
            _validate_image(proof, inventory.images[proof.image_id])
            by_image.setdefault(proof.image_id, []).append(proof)
    quarantined: list[dict[str, object]] = []
    for image_id, image_proofs in sorted(by_image.items()):
        aliases = _image_alias_snapshot(inventory.images[image_id])
        quarantined.append(
            {
                "image_id": image_id,
                "projects": sorted(
                    str(proof.project)
                    for proof in image_proofs
                    if proof.project
                ),
                "receipt_sha256": sorted(
                    proof.receipt_sha256 for proof in image_proofs
                ),
                "repo_tags": list(aliases["repo_tags"]),
                "repo_digests": list(aliases["repo_digests"]),
                "reason": "registered_image_without_active_stack",
                "automatic_image_removal_authorized": False,
            }
        )
    return tuple(quarantined)


def _compose_label_allowlist(
    labels: dict[str, str], allowed: frozenset[str], *, required: dict[str, str]
) -> None:
    compose_keys = {key for key in labels if key.startswith("com.docker.compose.")}
    if not compose_keys.issubset(allowed) or any(labels.get(key) != value for key, value in required.items()):
        raise RuntimeError("manfred_candidate_retention_resource_labels_invalid")


def _validate_image(proof: RuntimeProof, image: dict[str, object]) -> None:
    repo_tags, _repo_digests = _normalized_image_aliases(image)
    labels = dict(image.get("labels") or {})
    revisions = [
        value.split("=", 1)[1]
        for value in tuple(image.get("environment") or ())
        if value.startswith("EA_SOURCE_REVISION=")
    ]
    if (
        str(image.get("id") or "") != proof.image_id
        or proof.image not in set(repo_tags)
        or labels.get("org.opencontainers.image.revision") != proof.revision
        or revisions != [proof.revision]
        or proof.image not in {
            f"ea-runtime:manfred-{proof.revision}",
            f"ea-runtime:memorial-{proof.revision}",
        }
    ):
        raise RuntimeError("manfred_candidate_retention_image_binding_invalid")


def _runtime_container_image_ref(proof: RuntimeProof) -> str:
    if proof.schema == RUNTIME_RECEIPT_SCHEMA:
        return proof.image
    if proof.schema == "ea.manfred_memorial_candidate_runtime.v4":
        return proof.image_id
    raise RuntimeError("manfred_candidate_retention_receipt_schema_invalid")


def _gateway_binding(container: dict[str, object], port: int) -> None:
    raw = dict(container.get("port_bindings") or {}).get("18090/tcp")
    if not isinstance(raw, list) or len(raw) != 1 or not isinstance(raw[0], dict):
        raise RuntimeError("manfred_candidate_retention_gateway_port_invalid")
    if str(raw[0].get("HostIp") or "") != "127.0.0.1" or str(raw[0].get("HostPort") or "") != str(port):
        raise RuntimeError("manfred_candidate_retention_gateway_port_invalid")


def _validate_candidate(
    project: str, proof: RuntimeProof, inventory: Inventory
) -> Candidate:
    named = _expected_named_resources(project)
    containers = tuple(row for row in inventory.containers if row.get("project") == project)
    networks = tuple(row for row in inventory.networks if row.get("project") == project)
    volumes = tuple(row for row in inventory.volumes if row.get("project") == project)
    candidate_named_containers = {
        str(row["name"])
        for row in inventory.containers
        if _project_from_name("container", str(row.get("name") or "")) == project
    }
    candidate_named_networks = {
        str(row["name"])
        for row in inventory.networks
        if _project_from_name("network", str(row.get("name") or "")) == project
    }
    candidate_named_volumes = {
        str(row["name"])
        for row in inventory.volumes
        if _project_from_name("volume", str(row.get("name") or "")) == project
    }
    if (
        candidate_named_containers != {str(row["name"]) for row in containers}
        or candidate_named_networks != {str(row["name"]) for row in networks}
        or candidate_named_volumes != {str(row["name"]) for row in volumes}
    ):
        raise RuntimeError("manfred_candidate_retention_unlabeled_resource_collision")

    by_service: dict[str, dict[str, object]] = {}
    runtime_container_image_ref = _runtime_container_image_ref(proof)
    for row in containers:
        service = str(row.get("service") or "")
        labels = dict(row.get("labels") or {})
        if service not in EXPECTED_SERVICES or service in by_service:
            raise RuntimeError("manfred_candidate_retention_candidate_services_invalid")
        _compose_label_allowlist(
            labels,
            CONTAINER_COMPOSE_LABELS,
            required={
                "com.docker.compose.project": project,
                "com.docker.compose.service": service,
                "com.docker.compose.container-number": "1",
                "com.docker.compose.oneoff": "False",
            },
        )
        if str(row.get("name") or "") not in {
            f"{project}-{service}-1",
            f"{project}_{service}_1",
        }:
            raise RuntimeError("manfred_candidate_retention_container_name_invalid")
        expected_networks = {
            "api": {f"{project}_backend"},
            "gateway": {f"{project}_backend", f"{project}_ingress"},
            "postgres": {f"{project}_backend"},
            "redis": {f"{project}_backend"},
        }[service]
        if set(row.get("networks") or ()) != expected_networks:
            raise RuntimeError("manfred_candidate_retention_container_networks_invalid")
        if service in {"api", "gateway"}:
            if (
                row.get("image_id") != proof.image_id
                or row.get("image_ref") != runtime_container_image_ref
            ):
                raise RuntimeError("manfred_candidate_retention_container_image_invalid")
        elif row.get("image_ref") != EXPECTED_SERVICE_IMAGES[service]:
            raise RuntimeError("manfred_candidate_retention_service_image_invalid")
        if service == "api" and row.get("id") != proof.api_container_id:
            raise RuntimeError("manfred_candidate_retention_api_receipt_binding_invalid")
        if service == "gateway":
            if proof.gateway_container_id and row.get("id") != proof.gateway_container_id:
                raise RuntimeError("manfred_candidate_retention_gateway_receipt_binding_invalid")
            _gateway_binding(row, proof.port)
        by_service[service] = row

    by_network: dict[str, dict[str, object]] = {}
    for row in networks:
        network = str(row.get("network") or "")
        labels = dict(row.get("labels") or {})
        if network not in EXPECTED_NETWORKS or network in by_network:
            raise RuntimeError("manfred_candidate_retention_candidate_networks_invalid")
        _compose_label_allowlist(
            labels,
            NETWORK_COMPOSE_LABELS,
            required={
                "com.docker.compose.project": project,
                "com.docker.compose.network": network,
            },
        )
        if (
            row.get("name") != f"{project}_{network}"
            or row.get("driver") != "bridge"
            or bool(row.get("internal")) != (network == "backend")
            or row.get("attachable") is not False
        ):
            raise RuntimeError("manfred_candidate_retention_network_contract_invalid")
        expected_attached = {
            str(by_service[service]["id"])
            for service in (
                EXPECTED_SERVICES if network == "backend" else ("gateway",)
            )
            if service in by_service
        }
        if set(row.get("container_ids") or ()) != expected_attached:
            raise RuntimeError("manfred_candidate_retention_network_attachment_invalid")
        by_network[network] = row

    by_volume: dict[str, dict[str, object]] = {}
    for row in volumes:
        volume = str(row.get("volume") or "")
        labels = dict(row.get("labels") or {})
        if volume not in EXPECTED_VOLUMES or volume in by_volume:
            raise RuntimeError("manfred_candidate_retention_candidate_volumes_invalid")
        _compose_label_allowlist(
            labels,
            VOLUME_COMPOSE_LABELS,
            required={
                "com.docker.compose.project": project,
                "com.docker.compose.volume": volume,
            },
        )
        if row.get("name") != f"{project}_{volume}" or row.get("driver") != "local":
            raise RuntimeError("manfred_candidate_retention_volume_contract_invalid")
        users = {
            str(container["id"])
            for container in inventory.containers
            if any(
                mount.get("type") == "volume" and mount.get("name") == row.get("name")
                for mount in tuple(container.get("mounts") or ())
            )
        }
        if not users.issubset({str(container["id"]) for container in containers}):
            raise RuntimeError("manfred_candidate_retention_volume_external_user")
        by_volume[volume] = row

    _validate_image(proof, inventory.images.get(proof.image_id, {}))
    complete = (
        set(by_service) == set(EXPECTED_SERVICES)
        and set(by_network) == set(EXPECTED_NETWORKS)
        and set(by_volume) == set(EXPECTED_VOLUMES)
    )
    healthy = complete and all(
        row.get("running") is True and row.get("health") == "healthy"
        for row in containers
    )
    return Candidate(
        proof=proof,
        containers=containers,
        networks=networks,
        volumes=volumes,
        complete=complete,
        healthy=healthy,
    )


def _is_live_ea_ephemeral_probe(row: dict[str, object]) -> bool:
    labels = row.get("labels")
    return (
        row.get("project") == LIVE_EA_PROJECT
        and row.get("name") == LIVE_EA_EPHEMERAL_PROBE_NAME
        and row.get("service") == LIVE_EA_API_SERVICE
        and isinstance(labels, dict)
        and labels.get(COMPOSE_ONEOFF_LABEL) == "True"
    )


def _live_fingerprint(inventory: Inventory) -> dict[str, object]:
    project_containers = [
        row
        for row in inventory.containers
        if row.get("project") == LIVE_EA_PROJECT
    ]
    ephemeral_probes = [
        row for row in project_containers if _is_live_ea_ephemeral_probe(row)
    ]
    if len(ephemeral_probes) > 1:
        raise RuntimeError("manfred_candidate_retention_live_ea_unhealthy")
    containers = [
        row for row in project_containers if not _is_live_ea_ephemeral_probe(row)
    ]
    networks = [
        row for row in inventory.networks if row.get("project") == LIVE_EA_PROJECT
    ]
    volumes = [
        row for row in inventory.volumes if row.get("project") == LIVE_EA_PROJECT
    ]
    api = [
        row
        for row in containers
        if row.get("service") == LIVE_EA_API_SERVICE
        and row.get("name") == LIVE_EA_API_CONTAINER_NAME
    ]
    if len(api) != 1 or api[0].get("running") is not True or api[0].get("health") != "healthy":
        raise RuntimeError("manfred_candidate_retention_live_ea_unhealthy")
    payload = {
        "containers": [
            {
                "id": row["id"],
                "name": row["name"],
                "image_id": row["image_id"],
                "started_at": row["started_at"],
                "running": row["running"],
                "health": row["health"],
                "networks": row["networks"],
            }
            for row in containers
        ],
        "networks": [{"id": row["id"], "name": row["name"]} for row in networks],
        "volumes": [row["name"] for row in volumes],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "digest_sha256": hashlib.sha256(encoded).hexdigest(),
        "container_count": len(containers),
        "network_count": len(networks),
        "volume_count": len(volumes),
        "api_container_id": str(api[0]["id"]),
        "excluded_ephemeral_probe_name": LIVE_EA_EPHEMERAL_PROBE_NAME,
        "healthy": True,
    }


def _assert_keeper_http(proof: RuntimeProof) -> None:
    base = f"http://127.0.0.1:{proof.port}"
    try:
        request = urllib.request.Request(f"{base}/healthz", method="GET")
        with urllib.request.urlopen(request, timeout=10) as response:
            if int(response.status or 0) != 200:
                raise RuntimeError("manfred_candidate_retention_keeper_http_unhealthy")
            response.read(65537)
        request = urllib.request.Request(f"{base}/memorials/manfred.json", method="GET")
        with urllib.request.urlopen(request, timeout=10) as response:
            if (
                int(response.status or 0) != 200
                or str(response.headers.get("X-EA-Source-Revision") or "") != proof.revision
            ):
                raise RuntimeError("manfred_candidate_retention_keeper_revision_invalid")
            response.read(65537)
    except (OSError, urllib.error.URLError) as exc:
        raise RuntimeError("manfred_candidate_retention_keeper_http_unreachable") from exc


def _empty_automatic_enrollment_audit(*, apply: bool) -> dict[str, object]:
    return {
        "apply_only": True,
        "apply_requested": apply,
        "attempted_project_count": 0,
        "registration_attempted_count": 0,
        "registration_confirmed_count": 0,
        "registry_write_possible_count": 0,
        "enrolled_project_count": 0,
        "deferred_project_count": 0,
        "invalid_project_count": 0,
        "enrolled_projects": [],
        "deferred_projects": [],
        "invalid_projects": [],
    }


def _automatic_runtime_receipt_path(
    project: str, inventory: Inventory
) -> Path:
    containers = tuple(
        row
        for row in inventory.containers
        if row.get("project") == project
        or _project_from_name("container", str(row.get("name") or "")) == project
    )
    if not containers:
        raise RuntimeError(
            "manfred_candidate_retention_auto_enrollment_containers_missing"
        )
    environment_files: list[str] = []
    for container in containers:
        labels = container.get("labels")
        if not isinstance(labels, dict):
            raise RuntimeError(
                "manfred_candidate_retention_auto_enrollment_environment_file_invalid"
            )
        value = labels.get(COMPOSE_ENVIRONMENT_FILE_LABEL)
        if not isinstance(value, str) or not value:
            raise RuntimeError(
                "manfred_candidate_retention_auto_enrollment_environment_file_invalid"
            )
        environment_files.append(value)
    if len(set(environment_files)) != 1:
        raise RuntimeError(
            "manfred_candidate_retention_auto_enrollment_environment_file_ambiguous"
        )
    environment_file = Path(environment_files[0])
    try:
        canonical = environment_file.resolve(strict=False)
    except (OSError, RuntimeError, ValueError) as exc:
        raise RuntimeError(
            "manfred_candidate_retention_auto_enrollment_environment_file_invalid"
        ) from exc
    if (
        not environment_file.is_absolute()
        or environment_file.name != "candidate.env"
        or canonical != environment_file
    ):
        raise RuntimeError(
            "manfred_candidate_retention_auto_enrollment_environment_file_invalid"
        )
    return environment_file.parent / AUTOMATIC_RUNTIME_RECEIPT_RELATIVE


def _automatic_enrollment_inventory(
    inventory: Inventory, proof: RuntimeProof
) -> Inventory:
    rows = _inspect("image", [proof.image_id])
    if len(rows) != 1:
        raise RuntimeError(
            "manfred_candidate_retention_auto_enrollment_image_invalid"
        )
    image = _normalize_image(rows[0])
    if image.get("id") != proof.image_id:
        raise RuntimeError(
            "manfred_candidate_retention_auto_enrollment_image_invalid"
        )
    return Inventory(
        containers=inventory.containers,
        networks=inventory.networks,
        volumes=inventory.volumes,
        images={proof.image_id: image},
    )


def _auto_enroll_unregistered_projects(
    projects: set[str],
    inventory: Inventory,
    *,
    registry_path: Path,
    apply: bool,
    now: datetime | None = None,
) -> dict[str, object]:
    observed_at = now or datetime.now(timezone.utc)
    if observed_at.tzinfo is None:
        raise RuntimeError(
            "manfred_candidate_retention_auto_enrollment_clock_invalid"
        )
    observed_at = observed_at.astimezone(timezone.utc)
    enrolled: list[dict[str, object]] = []
    deferred: list[dict[str, object]] = []
    invalid: list[dict[str, object]] = []
    registration_attempted_count = 0
    registration_confirmed_count = 0
    for project in sorted(projects):
        receipt_path: Path | None = None
        try:
            receipt_path = _automatic_runtime_receipt_path(project, inventory)
        except RuntimeError as exc:
            invalid.append({"project": project, "reason": _safe_error(exc)})
            continue
        if not os.path.lexists(receipt_path):
            deferred.append(
                {
                    "project": project,
                    "receipt_path": str(receipt_path),
                    "reason": "runtime_receipt_missing",
                }
            )
            continue
        try:
            payload, digest = _read_receipt(receipt_path)
            proof = _parse_runtime_proof(payload, digest)
            if proof.project != project:
                raise RuntimeError(
                    "manfred_candidate_retention_auto_enrollment_project_mismatch"
                )
            age_seconds = int(
                observed_at.timestamp() - proof.observed_at.timestamp()
            )
            if age_seconds < 0:
                raise RuntimeError(
                    "manfred_candidate_retention_auto_enrollment_clock_regressed"
                )
            evidence: dict[str, object] = {
                "project": project,
                "receipt_path": str(receipt_path),
                "receipt_sha256": digest,
                "proof_observed_at": proof.observed_at.isoformat().replace(
                    "+00:00", "Z"
                ),
                "proof_age_seconds": age_seconds,
            }
            if age_seconds < MINIMUM_KEEPER_STABILITY_SECONDS:
                deferred.append(
                    {
                        **evidence,
                        "reason": "runtime_proof_stabilizing",
                        "minimum_stability_seconds": (
                            MINIMUM_KEEPER_STABILITY_SECONDS
                        ),
                    }
                )
                continue
            candidate = _validate_candidate(
                project,
                proof,
                _automatic_enrollment_inventory(inventory, proof),
            )
            if not candidate.complete:
                raise RuntimeError(
                    "manfred_candidate_retention_auto_enrollment_candidate_incomplete"
                )
            if not candidate.healthy:
                raise RuntimeError(
                    "manfred_candidate_retention_auto_enrollment_candidate_unhealthy"
                )
            _assert_keeper_http(proof)
            if not apply:
                deferred.append(
                    {**evidence, "reason": "apply_required_for_auto_enrollment"}
                )
                continue
            registration_attempted_count += 1
            registration = register_candidate_receipt(
                receipt_path, registry_path=registry_path
            )
            if registration.get("registered") is not True:
                raise RuntimeError(
                    "manfred_candidate_retention_auto_enrollment_registration_failed"
                )
            registration_confirmed_count += 1
            enrolled.append(evidence)
        except RuntimeError as exc:
            invalid.append(
                {
                    "project": project,
                    "receipt_path": str(receipt_path),
                    "reason": _safe_error(exc),
                }
            )
    return {
        "apply_only": True,
        "apply_requested": apply,
        "attempted_project_count": len(projects),
        "registration_attempted_count": registration_attempted_count,
        "registration_confirmed_count": registration_confirmed_count,
        "registry_write_possible_count": registration_attempted_count,
        "enrolled_project_count": len(enrolled),
        "deferred_project_count": len(deferred),
        "invalid_project_count": len(invalid),
        "enrolled_projects": enrolled,
        "deferred_projects": deferred,
        "invalid_projects": invalid,
    }


def _build_plan(
    proofs: tuple[RuntimeProof, ...],
    inventory: Inventory,
    *,
    now: datetime | None = None,
    root_free_bytes: int | None = None,
    retired_images: dict[str, dict[str, object]] | None = None,
    excluded_projects: set[str] | None = None,
    pending_intent_quarantine: tuple[dict[str, object], ...] = (),
    unknown_project_quarantine: tuple[dict[str, object], ...] = (),
    preferred_keeper_project: str | None = None,
    preferred_keeper_qualified: bool = False,
) -> RetentionPlan:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise RuntimeError("manfred_candidate_retention_clock_invalid")
    now = now.astimezone(timezone.utc)
    if root_free_bytes is None:
        try:
            root_free_bytes = shutil.disk_usage("/").free
        except OSError as exc:
            raise RuntimeError("manfred_candidate_retention_disk_state_unavailable") from exc
    if root_free_bytes < 0:
        raise RuntimeError("manfred_candidate_retention_disk_state_invalid")
    retired_images = dict(retired_images or {})
    discovered_projects = _candidate_projects(inventory)
    excluded_projects = set(excluded_projects or set())
    if not excluded_projects.issubset(discovered_projects):
        raise RuntimeError("manfred_candidate_retention_excluded_project_missing")
    pending_projects = {
        str(row.get("project") or "") for row in pending_intent_quarantine
    }
    unknown_projects = {
        str(row.get("project") or "") for row in unknown_project_quarantine
    }
    if (
        pending_projects & unknown_projects
        or pending_projects | unknown_projects != excluded_projects
        or _unregistered_project_quarantine(unknown_projects, inventory)
        != unknown_project_quarantine
    ):
        raise RuntimeError("manfred_candidate_retention_pending_quarantine_mismatch")
    projects = discovered_projects - excluded_projects
    if not projects:
        raise RuntimeError("manfred_candidate_retention_no_active_candidate")
    bound = _bind_proofs(proofs, inventory, projects)
    candidates = tuple(
        _validate_candidate(project, bound[project], inventory)
        for project in sorted(projects)
    )
    timestamps = [candidate.proof.observed_at for candidate in candidates]
    if len(timestamps) != len(set(timestamps)):
        raise RuntimeError("manfred_candidate_retention_proof_order_ambiguous")
    actual_newest = max(candidates, key=lambda item: item.proof.observed_at)
    if not actual_newest.complete or not actual_newest.healthy:
        raise RuntimeError("manfred_candidate_retention_newest_candidate_unhealthy")
    newest_age = now - actual_newest.proof.observed_at
    if newest_age < timedelta(0):
        raise RuntimeError("manfred_candidate_retention_keeper_clock_regressed")

    minimum_age = timedelta(seconds=MINIMUM_KEEPER_STABILITY_SECONDS)

    def mature(candidate: Candidate) -> bool:
        age = now - candidate.proof.observed_at
        return (
            age >= minimum_age
            and candidate.complete
            and candidate.healthy
        )

    mature_candidates = tuple(candidate for candidate in candidates if mature(candidate))
    preferred: Candidate | None = None
    if type(preferred_keeper_qualified) is not bool:
        raise RuntimeError(
            "manfred_candidate_retention_preferred_keeper_invalid"
        )
    if preferred_keeper_qualified and preferred_keeper_project is None:
        raise RuntimeError(
            "manfred_candidate_retention_preferred_keeper_invalid"
        )
    if preferred_keeper_project is not None:
        try:
            preferred_keeper_project = _validate_project_name(
                preferred_keeper_project
            )
        except ValueError as exc:
            raise RuntimeError(
                "manfred_candidate_retention_preferred_keeper_invalid"
            ) from exc
        preferred = next(
            (
                candidate
                for candidate in candidates
                if candidate.project == preferred_keeper_project
            ),
            None,
        )
        if preferred is not None and (
            not preferred.complete
            or not preferred.healthy
            or not mature(preferred)
        ):
            raise RuntimeError(
                "manfred_candidate_retention_preferred_keeper_unhealthy"
            )

    if preferred is not None:
        older_candidates = tuple(
            candidate
            for candidate in candidates
            if candidate.proof.observed_at < preferred.proof.observed_at
        )
        mature_successors = tuple(
            candidate
            for candidate in mature_candidates
            if candidate.proof.observed_at > preferred.proof.observed_at
        )
        if older_candidates:
            keeper = preferred
            keeper_selection = "persisted_mature_anchor"
        elif preferred_keeper_qualified and mature_successors:
            keeper = max(
                mature_successors,
                key=lambda item: item.proof.observed_at,
            )
            keeper_selection = "qualified_drained_anchor_rotation"
        else:
            keeper = preferred
            keeper_selection = "persisted_anchor_waiting_for_mature_successor"
    elif mature_candidates:
        keeper = max(
            mature_candidates,
            key=lambda item: item.proof.observed_at,
        )
        keeper_selection = "newest_mature_bootstrap"
    else:
        raise _KeeperStabilizing(actual_newest, int(newest_age.total_seconds()))

    protected_newer_candidates = tuple(
        sorted(
            (
                candidate
                for candidate in candidates
                if candidate.proof.observed_at > keeper.proof.observed_at
            ),
            key=lambda item: item.proof.observed_at,
        )
    )
    older_candidates = tuple(
        sorted(
            (
                candidate
                for candidate in candidates
                if candidate.proof.observed_at < keeper.proof.observed_at
            ),
            key=lambda item: item.proof.observed_at,
        )
    )
    all_retirees = older_candidates
    if any(
        candidate.proof.observed_at >= keeper.proof.observed_at
        for candidate in all_retirees
    ) or any(
        candidate.proof.observed_at <= keeper.proof.observed_at
        for candidate in protected_newer_candidates
    ):
        raise RuntimeError("manfred_candidate_retention_proof_order_ambiguous")
    retirees = all_retirees[:MAX_RETIRE_PROJECTS_PER_RUN]
    pending_retirees = all_retirees[MAX_RETIRE_PROJECTS_PER_RUN:]

    target_container_ids = {
        str(row["id"]) for candidate in retirees for row in candidate.containers
    }
    retained_image_ids = {
        candidate.proof.image_id
        for candidate in (
            keeper,
            *pending_retirees,
            *protected_newer_candidates,
        )
    }
    removable: list[str] = []
    preserved: list[dict[str, str]] = []
    deferred_projects: set[str] = set()
    grace_candidates: list[dict[str, object]] = []

    def grace_state(
        image_id: str,
        image_proofs: list[RuntimeProof],
        *,
        active_stack: bool,
    ) -> str:
        projects_for_image = sorted(
            str(proof.project) for proof in image_proofs if proof.project
        )
        digests_for_image = sorted(proof.receipt_sha256 for proof in image_proofs)
        entry = retired_images.get(image_id)
        if entry is None:
            grace_candidates.append(
                {
                    "image_id": image_id,
                    "projects": projects_for_image,
                    "receipt_sha256": digests_for_image,
                    "renew": False,
                }
            )
            return "pending"
        if (
            list(entry.get("projects") or []) != projects_for_image
            or list(entry.get("receipt_sha256") or []) != digests_for_image
        ):
            raise RuntimeError(
                "manfred_candidate_retention_retired_image_state_mismatch"
            )
        grace_until = _parse_timestamp(entry.get("grace_until"))
        if now < grace_until:
            return "active"
        if active_stack:
            grace_candidates.append(
                {
                    "image_id": image_id,
                    "projects": projects_for_image,
                    "receipt_sha256": digests_for_image,
                    "renew": True,
                }
            )
            return "pending"
        return "expired"
    retired_by_image: dict[str, list[Candidate]] = {}
    for candidate in retirees:
        retired_by_image.setdefault(candidate.proof.image_id, []).append(candidate)
    for image_id, image_candidates in sorted(retired_by_image.items()):
        references = {
            str(row["id"])
            for row in inventory.containers
            if row.get("image_id") == image_id
        }
        image = inventory.images[image_id]
        image_tags, image_digests = _normalized_image_aliases(image)
        expected_tags = {candidate.proof.image for candidate in image_candidates}
        if image_id in retained_image_ids:
            preserved.append({"image_id": image_id, "reason": "retained_candidate_reference"})
        elif not references.issubset(target_container_ids):
            preserved.append({"image_id": image_id, "reason": "nonretired_container_reference"})
            deferred_projects.update(
                candidate.project for candidate in image_candidates
            )
        elif image_digests:
            preserved.append({"image_id": image_id, "reason": "repo_digest_aliases"})
            deferred_projects.update(
                candidate.project for candidate in image_candidates
            )
        elif set(image_tags) != expected_tags:
            preserved.append({"image_id": image_id, "reason": "additional_image_tags"})
            deferred_projects.update(
                candidate.project for candidate in image_candidates
            )
        else:
            state = grace_state(
                image_id,
                [candidate.proof for candidate in image_candidates],
                active_stack=True,
            )
            if state == "expired":
                removable.append(image_id)
                continue
            preserved.append(
                {
                    "image_id": image_id,
                    "reason": (
                        "post_retirement_grace_pending"
                        if state == "pending"
                        else "24h_post_retirement_grace"
                    ),
                }
            )
            deferred_projects.update(candidate.project for candidate in image_candidates)

    historical_by_image: dict[str, list[RuntimeProof]] = {}
    for proof in proofs:
        if proof.project not in projects and proof.image_id in inventory.images:
            historical_by_image.setdefault(proof.image_id, []).append(proof)
    for image_id, image_proofs in sorted(historical_by_image.items()):
        if image_id in retired_by_image or image_id in retained_image_ids:
            continue
        image = inventory.images[image_id]
        for proof in image_proofs:
            _validate_image(proof, image)
        image_tags, image_digests = _normalized_image_aliases(image)
        references = {
            str(row["id"])
            for row in inventory.containers
            if row.get("image_id") == image_id
        }
        expected_tags = {proof.image for proof in image_proofs}
        if references:
            preserved.append(
                {"image_id": image_id, "reason": "nonretired_container_reference"}
            )
            deferred_projects.update(
                str(proof.project) for proof in image_proofs if proof.project
            )
        elif image_digests:
            preserved.append({"image_id": image_id, "reason": "repo_digest_aliases"})
            deferred_projects.update(
                str(proof.project) for proof in image_proofs if proof.project
            )
        elif set(image_tags) != expected_tags:
            preserved.append({"image_id": image_id, "reason": "additional_image_tags"})
            deferred_projects.update(
                str(proof.project) for proof in image_proofs if proof.project
            )
        else:
            state = grace_state(image_id, image_proofs, active_stack=False)
            if state == "expired":
                removable.append(image_id)
                continue
            preserved.append(
                {
                    "image_id": image_id,
                    "reason": (
                        "post_retirement_grace_pending"
                        if state == "pending"
                        else "24h_post_retirement_grace"
                    ),
                }
            )
            deferred_projects.update(
                str(proof.project) for proof in image_proofs if proof.project
            )
    removable_ids = sorted(set(removable))
    selected_image_ids = tuple(removable_ids[:MAX_REMOVE_IMAGES_PER_RUN])
    selected_image_aliases = tuple(
        _image_alias_snapshot(inventory.images[image_id])
        for image_id in selected_image_ids
    )
    for image_id in removable_ids[MAX_REMOVE_IMAGES_PER_RUN:]:
        preserved.append({"image_id": image_id, "reason": "image_batch_limit"})
        deferred_projects.update(
            str(proof.project)
            for proof in proofs
            if proof.image_id == image_id and proof.project
        )
    return RetentionPlan(
        keeper=keeper,
        actual_newest=actual_newest,
        keeper_selection=keeper_selection,
        retirees=retirees,
        pending_retirees=pending_retirees,
        protected_newer_candidates=protected_newer_candidates,
        removable_image_ids=selected_image_ids,
        preserved_images=tuple(preserved),
        live_before=_live_fingerprint(inventory),
        quarantined_projects=_legacy_quarantine(inventory),
        root_free_bytes=root_free_bytes,
        deferred_image_projects=tuple(sorted(deferred_projects)),
        grace_candidates=tuple(grace_candidates),
        pending_intent_quarantine=pending_intent_quarantine,
        unknown_project_quarantine=unknown_project_quarantine,
        removable_image_aliases=selected_image_aliases,
    )


def _candidate_summary(candidate: Candidate) -> dict[str, object]:
    return {
        "project": candidate.project,
        "observed_at": candidate.proof.observed_at.isoformat().replace("+00:00", "Z"),
        "receipt_sha256": candidate.proof.receipt_sha256,
        "image_id": candidate.proof.image_id,
        "container_count": len(candidate.containers),
        "network_count": len(candidate.networks),
        "volume_count": len(candidate.volumes),
        "complete": candidate.complete,
        "healthy": candidate.healthy,
    }


def _retained_candidates(plan: RetentionPlan) -> tuple[Candidate, ...]:
    return (
        plan.keeper,
        *plan.pending_retirees,
        *plan.protected_newer_candidates,
    )


def _assert_plan_partition(plan: RetentionPlan) -> None:
    retained = _retained_candidates(plan)
    all_candidates = (*retained, *plan.retirees)
    projects = [candidate.project for candidate in all_candidates]
    if len(projects) != len(set(projects)):
        raise RuntimeError("manfred_candidate_retention_plan_partition_invalid")
    if (
        not all_candidates
        or max(
            all_candidates,
            key=lambda candidate: candidate.proof.observed_at,
        )
        != plan.actual_newest
        or not plan.actual_newest.complete
        or not plan.actual_newest.healthy
        or not plan.keeper.complete
        or not plan.keeper.healthy
    ):
        raise RuntimeError("manfred_candidate_retention_plan_partition_invalid")
    if plan.actual_newest.project not in {
        candidate.project for candidate in retained
    }:
        raise RuntimeError(
            "manfred_candidate_retention_actual_newest_target_forbidden"
        )
    if any(
        candidate.proof.observed_at >= plan.keeper.proof.observed_at
        for candidate in (*plan.retirees, *plan.pending_retirees)
    ) or any(
        candidate.proof.observed_at <= plan.keeper.proof.observed_at
        for candidate in plan.protected_newer_candidates
    ):
        raise RuntimeError("manfred_candidate_retention_plan_partition_invalid")


def _plan_receipt(plan: RetentionPlan) -> dict[str, object]:
    _assert_plan_partition(plan)
    return {
        "keeper": _candidate_summary(plan.keeper),
        "keeper_selection": plan.keeper_selection,
        "actual_newest": _candidate_summary(plan.actual_newest),
        "actual_newest_retirement_authorized": False,
        "retirees": [_candidate_summary(candidate) for candidate in plan.retirees],
        "retire_project_count": len(plan.retirees),
        "pending_retirees": [
            _candidate_summary(candidate) for candidate in plan.pending_retirees
        ],
        "pending_retire_project_count": len(plan.pending_retirees),
        "protected_newer_candidates": [
            _candidate_summary(candidate)
            for candidate in plan.protected_newer_candidates
        ],
        "protected_newer_project_count": len(
            plan.protected_newer_candidates
        ),
        "retire_project_batch_limit": MAX_RETIRE_PROJECTS_PER_RUN,
        "removable_image_ids": list(plan.removable_image_ids),
        "preserved_images": list(plan.preserved_images),
        "quarantined_projects": list(plan.quarantined_projects),
        "managed_active_project_count": (
            1
            + len(plan.retirees)
            + len(plan.pending_retirees)
            + len(plan.protected_newer_candidates)
        ),
        "legacy_quarantine_excluded_from_managed_count": True,
        "root_free_bytes": plan.root_free_bytes,
        "image_grace_minimum_free_bytes": IMAGE_GRACE_MINIMUM_FREE_BYTES,
        "deferred_image_projects": list(plan.deferred_image_projects),
        "grace_candidates": list(plan.grace_candidates),
        "image_remove_batch_limit": MAX_REMOVE_IMAGES_PER_RUN,
        "removable_image_aliases": list(plan.removable_image_aliases),
        "pending_intent_quarantine": list(plan.pending_intent_quarantine),
        "unknown_project_quarantine": list(plan.unknown_project_quarantine),
        "unknown_quarantine_excluded_from_managed_count": True,
        "live_ea_before": plan.live_before,
        "live_ea_mutation_requested": False,
        "release_or_runtime_path_removal_requested": False,
    }


def _mutation_targets(plan: RetentionPlan) -> dict[str, list[str]]:
    _assert_plan_partition(plan)
    if any(
        candidate.project == plan.actual_newest.project
        for candidate in plan.retirees
    ):
        raise RuntimeError(
            "manfred_candidate_retention_actual_newest_target_forbidden"
        )
    return {
        "container_ids": sorted(
            str(row["id"])
            for candidate in plan.retirees
            for row in candidate.containers
        ),
        "network_ids": sorted(
            str(row["id"])
            for candidate in plan.retirees
            for row in candidate.networks
        ),
        "volume_names": sorted(
            str(row["name"])
            for candidate in plan.retirees
            for row in candidate.volumes
        ),
        "eligible_image_ids": list(plan.removable_image_ids),
    }


def _intent_receipt_path(output_receipt: Path) -> Path:
    name = output_receipt.name
    stem = name[:-5] if name.endswith(".json") else name
    return output_receipt.with_name(f"{stem}.intent.json")


def _stability_identity(plan: RetentionPlan) -> str:
    stable_pending = [
        {
            "project": row.get("project"),
            "created_at": row.get("created_at"),
            "resource_digest_sha256": row.get("resource_digest_sha256"),
            "ttl_expired": row.get("ttl_expired"),
            "operator_action_required": row.get("operator_action_required"),
            "reason": row.get("reason"),
        }
        for row in plan.pending_intent_quarantine
    ]
    payload = {
        "project": plan.keeper.project,
        "receipt_sha256": plan.keeper.proof.receipt_sha256,
        "image_id": plan.keeper.proof.image_id,
        "keeper_topology": {
            "containers": sorted(
                plan.keeper.containers,
                key=lambda row: str(row.get("id") or ""),
            ),
            "networks": sorted(
                plan.keeper.networks,
                key=lambda row: str(row.get("id") or ""),
            ),
            "volumes": sorted(
                plan.keeper.volumes,
                key=lambda row: str(row.get("name") or ""),
            ),
        },
        # Bind the safety posture, not deployment-specific identities.  A healthy
        # live EA replacement may legitimately change its container, image,
        # start time, or network ID between samples.  Those exact resources are
        # still revalidated around every apply, while a posture change resets
        # the multi-sample qualification window.
        "live_ea_posture": {
            "healthy": plan.live_before["healthy"],
            "container_count": plan.live_before["container_count"],
            "network_count": plan.live_before["network_count"],
            "volume_count": plan.live_before["volume_count"],
            "excluded_ephemeral_probe_name": plan.live_before[
                "excluded_ephemeral_probe_name"
            ],
        },
        "quarantine": {
            "legacy": list(plan.quarantined_projects),
            "pending": stable_pending,
            "unknown": list(plan.unknown_project_quarantine),
        },
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _mutable_private_json(path: Path, payload: dict[str, object]) -> None:
    path = Path(path).expanduser()
    absolute = path if path.is_absolute() else Path.cwd() / path
    parent = absolute.parent
    try:
        parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        resolved_parent = parent.resolve(strict=True)
        parent_status = resolved_parent.stat()
    except OSError as exc:
        raise RuntimeError("manfred_candidate_retention_state_path_invalid") from exc
    if (
        resolved_parent != parent.absolute()
        or not stat.S_ISDIR(parent_status.st_mode)
        or parent_status.st_uid != os.getuid()
        or stat.S_IMODE(parent_status.st_mode) & 0o022
    ):
        raise RuntimeError("manfred_candidate_retention_state_path_invalid")
    destination = resolved_parent / absolute.name
    if os.path.lexists(destination):
        _read_receipt(destination)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{destination.name}.", dir=resolved_parent
    )
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
        destination.chmod(0o600)
        directory_descriptor = os.open(
            resolved_parent,
            os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC,
        )
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        Path(temporary).unlink(missing_ok=True)


def _validated_retired_images(payload: dict[str, object]) -> dict[str, dict[str, object]]:
    raw = payload.get("retired_images", {})
    if not isinstance(raw, dict) or len(raw) > MAX_RECEIPTS:
        raise RuntimeError("manfred_candidate_retention_retired_image_state_invalid")
    validated: dict[str, dict[str, object]] = {}
    for image_id, value in raw.items():
        if IMAGE_ID.fullmatch(str(image_id)) is None or not isinstance(value, dict):
            raise RuntimeError("manfred_candidate_retention_retired_image_state_invalid")
        projects = value.get("projects")
        digests = value.get("receipt_sha256")
        if (
            set(value)
            != {"projects", "receipt_sha256", "retired_at", "grace_until"}
            or not isinstance(projects, list)
            or not projects
            or len(projects) != len(set(str(item) for item in projects))
            or not isinstance(digests, list)
            or not digests
            or len(digests) != len(set(str(item) for item in digests))
            or any(
                len(str(digest)) != 64
                or any(character not in "0123456789abcdef" for character in str(digest))
                for digest in digests
            )
        ):
            raise RuntimeError("manfred_candidate_retention_retired_image_state_invalid")
        try:
            normalized_projects = sorted(
                _validate_project_name(project) for project in projects
            )
        except ValueError as exc:
            raise RuntimeError(
                "manfred_candidate_retention_retired_image_state_invalid"
            ) from exc
        retired_at = _parse_timestamp(value.get("retired_at"))
        grace_until = _parse_timestamp(value.get("grace_until"))
        if (
            grace_until.timestamp() - retired_at.timestamp()
            != RETIRED_IMAGE_LEDGER_WINDOW_SECONDS
        ):
            raise RuntimeError("manfred_candidate_retention_retired_image_state_invalid")
        validated[str(image_id)] = {
            "projects": normalized_projects,
            "receipt_sha256": sorted(str(digest) for digest in digests),
            "retired_at": retired_at.isoformat().replace("+00:00", "Z"),
            "grace_until": grace_until.isoformat().replace("+00:00", "Z"),
        }
    return validated


def _validated_state_anchor(
    payload: dict[str, object],
    *,
    now: datetime,
) -> tuple[str | None, bool]:
    if now.tzinfo is None:
        raise RuntimeError("manfred_candidate_retention_clock_invalid")
    now = now.astimezone(timezone.utc)
    required = {
        "schema",
        "updated_at",
        "identity_sha256",
        "keeper_project",
        "samples",
        "qualified",
        "retired_images",
    }
    if set(payload) != required:
        raise RuntimeError("manfred_candidate_retention_state_shape_invalid")
    updated_at = _parse_timestamp(payload.get("updated_at"))
    if updated_at > now:
        raise RuntimeError("manfred_candidate_retention_state_clock_regressed")
    keeper_project = payload.get("keeper_project")
    identity = payload.get("identity_sha256")
    raw_samples = payload.get("samples")
    qualified = payload.get("qualified")
    if (
        not isinstance(keeper_project, str)
        or not isinstance(identity, str)
        or not isinstance(raw_samples, list)
        or len(raw_samples) > MAX_STABILITY_SAMPLES
        or type(qualified) is not bool
    ):
        raise RuntimeError("manfred_candidate_retention_state_samples_invalid")
    if not keeper_project:
        if identity or raw_samples or qualified:
            raise RuntimeError("manfred_candidate_retention_state_samples_invalid")
        return None, False
    try:
        keeper_project = _validate_project_name(keeper_project)
    except ValueError as exc:
        raise RuntimeError(
            "manfred_candidate_retention_state_keeper_invalid"
        ) from exc
    if HEX_64.fullmatch(identity) is None or not raw_samples:
        raise RuntimeError("manfred_candidate_retention_state_samples_invalid")
    timestamps: list[datetime] = []
    for raw in raw_samples:
        if (
            not isinstance(raw, dict)
            or set(raw) != {"observed_at", "identity_sha256"}
            or raw.get("identity_sha256") != identity
        ):
            raise RuntimeError("manfred_candidate_retention_state_samples_invalid")
        observed_at = _parse_timestamp(raw.get("observed_at"))
        if observed_at > now:
            raise RuntimeError("manfred_candidate_retention_state_clock_regressed")
        timestamps.append(observed_at)
    if timestamps != sorted(timestamps) or len(timestamps) != len(set(timestamps)):
        raise RuntimeError("manfred_candidate_retention_state_samples_invalid")
    if timestamps[-1] > updated_at:
        raise RuntimeError("manfred_candidate_retention_state_samples_invalid")
    for previous, current in zip(timestamps, timestamps[1:]):
        gap = int(current.timestamp() - previous.timestamp())
        if (
            gap < MINIMUM_SAMPLE_SPACING_SECONDS
            or gap > MAXIMUM_SAMPLE_GAP_SECONDS
        ):
            raise RuntimeError("manfred_candidate_retention_state_samples_invalid")
    span_seconds = int(timestamps[-1].timestamp() - timestamps[0].timestamp())
    recomputed_qualified = (
        len(timestamps) >= 3
        and span_seconds >= MINIMUM_KEEPER_STABILITY_SECONDS
    )
    if qualified is not recomputed_qualified:
        raise RuntimeError("manfred_candidate_retention_state_samples_invalid")
    return keeper_project, recomputed_qualified


def _load_retention_state(
    path: Path,
    *,
    now: datetime,
) -> tuple[dict[str, dict[str, object]], str | None, bool, str | None]:
    if not os.path.lexists(Path(path).expanduser()):
        return {}, None, False, None
    payload, digest = _read_receipt(path)
    if payload.get("schema") != STATE_SCHEMA:
        raise RuntimeError("manfred_candidate_retention_state_schema_invalid")
    keeper_project, qualified = _validated_state_anchor(payload, now=now)
    return _validated_retired_images(payload), keeper_project, qualified, digest


def _load_retired_image_ledger(path: Path) -> dict[str, dict[str, object]]:
    ledger, _keeper_project, _qualified, _digest = _load_retention_state(
        path,
        now=datetime.now(timezone.utc),
    )
    return ledger


def _assert_state_clock_not_regressed(path: Path, *, now: datetime) -> None:
    if now.tzinfo is None:
        raise RuntimeError("manfred_candidate_retention_clock_invalid")
    if not os.path.lexists(Path(path).expanduser()):
        return
    _load_retention_state(path, now=now)


def _update_retired_image_ledger(
    path: Path,
    updates: tuple[dict[str, object], ...],
    *,
    now: datetime,
    retain_image_ids: set[str] | None = None,
) -> dict[str, dict[str, object]]:
    if now.tzinfo is None:
        raise RuntimeError("manfred_candidate_retention_clock_invalid")
    now = now.astimezone(timezone.utc).replace(microsecond=0)
    payload: dict[str, object]
    if os.path.lexists(Path(path).expanduser()):
        payload, _digest = _read_receipt(path)
        if payload.get("schema") != STATE_SCHEMA:
            raise RuntimeError("manfred_candidate_retention_state_schema_invalid")
        _validated_state_anchor(payload, now=now)
    else:
        payload = {
            "schema": STATE_SCHEMA,
            "updated_at": now.isoformat().replace("+00:00", "Z"),
            "identity_sha256": "",
            "keeper_project": "",
            "samples": [],
            "qualified": False,
        }
    ledger = _validated_retired_images(payload)
    for update in updates:
        image_id = str(update.get("image_id") or "")
        projects = sorted(str(value) for value in list(update.get("projects") or []))
        digests = sorted(
            str(value) for value in list(update.get("receipt_sha256") or [])
        )
        renew = update.get("renew") is True
        if (
            set(update)
            != {"image_id", "projects", "receipt_sha256", "renew"}
            or not isinstance(update.get("renew"), bool)
            or IMAGE_ID.fullmatch(image_id) is None
            or not projects
            or len(projects) != len(set(projects))
            or not digests
            or len(digests) != len(set(digests))
            or any(HEX_64.fullmatch(digest) is None for digest in digests)
        ):
            raise RuntimeError(
                "manfred_candidate_retention_retired_image_update_invalid"
            )
        try:
            projects = sorted(_validate_project_name(project) for project in projects)
        except ValueError as exc:
            raise RuntimeError(
                "manfred_candidate_retention_retired_image_update_invalid"
            ) from exc
        if image_id in ledger:
            existing = ledger[image_id]
            if existing["projects"] != projects or existing["receipt_sha256"] != digests:
                raise RuntimeError(
                    "manfred_candidate_retention_retired_image_state_mismatch"
                )
            if not renew:
                continue
        retired_at = now
        grace_until = retired_at + timedelta(
            seconds=RETIRED_IMAGE_LEDGER_WINDOW_SECONDS
        )
        ledger[image_id] = {
            "projects": projects,
            "receipt_sha256": digests,
            "retired_at": retired_at.isoformat().replace("+00:00", "Z"),
            "grace_until": grace_until.isoformat().replace("+00:00", "Z"),
        }
    if retain_image_ids is not None:
        ledger = {
            image_id: value
            for image_id, value in ledger.items()
            if image_id in retain_image_ids
        }
    payload["updated_at"] = now.replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )
    payload["retired_images"] = ledger
    _mutable_private_json(path, payload)
    return ledger


def _record_stability_sample(
    path: Path,
    plan: RetentionPlan,
    *,
    now: datetime | None = None,
    expected_state_sha256: str | None = None,
    state_prevalidated: bool = False,
) -> dict[str, object]:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(
        microsecond=0
    )
    identity = _stability_identity(plan)
    existing: dict[str, object] | None = None
    retired_images: dict[str, dict[str, object]] = {}
    state_exists = os.path.lexists(Path(path).expanduser())
    if state_exists:
        existing, observed_digest = _read_receipt(path)
        if state_prevalidated and observed_digest != expected_state_sha256:
            raise RuntimeError("manfred_candidate_retention_state_changed")
        if existing.get("schema") != STATE_SCHEMA:
            raise RuntimeError("manfred_candidate_retention_state_schema_invalid")
        _validated_state_anchor(existing, now=now)
        retired_images = _validated_retired_images(existing)
    elif state_prevalidated and expected_state_sha256 is not None:
        raise RuntimeError("manfred_candidate_retention_state_changed")
    samples: list[dict[str, str]] = []
    if existing and existing.get("identity_sha256") == identity:
        raw_samples = existing.get("samples")
        if not isinstance(raw_samples, list) or len(raw_samples) > MAX_STABILITY_SAMPLES:
            raise RuntimeError("manfred_candidate_retention_state_samples_invalid")
        for raw in raw_samples:
            if not isinstance(raw, dict) or raw.get("identity_sha256") != identity:
                raise RuntimeError("manfred_candidate_retention_state_samples_invalid")
            observed_at = str(raw.get("observed_at") or "")
            _parse_timestamp(observed_at)
            samples.append(
                {"observed_at": observed_at, "identity_sha256": identity}
            )
    append = True
    if samples:
        last = _parse_timestamp(samples[-1]["observed_at"])
        delta = now.timestamp() - last.timestamp()
        if delta < 0:
            raise RuntimeError("manfred_candidate_retention_state_clock_regressed")
        if delta > MAXIMUM_SAMPLE_GAP_SECONDS:
            samples = []
        append = delta >= MINIMUM_SAMPLE_SPACING_SECONDS
        if not samples:
            append = True
    if append:
        samples.append(
            {
                "observed_at": now.isoformat().replace("+00:00", "Z"),
                "identity_sha256": identity,
            }
        )
        samples = samples[-MAX_STABILITY_SAMPLES:]
    first = _parse_timestamp(samples[0]["observed_at"])
    last = _parse_timestamp(samples[-1]["observed_at"])
    span_seconds = int(last.timestamp() - first.timestamp())
    qualified = len(samples) >= 3 and span_seconds >= MINIMUM_KEEPER_STABILITY_SECONDS
    state = {
        "schema": STATE_SCHEMA,
        "updated_at": now.isoformat().replace("+00:00", "Z"),
        "identity_sha256": identity,
        "keeper_project": plan.keeper.project,
        "samples": samples,
        "qualified": qualified,
        "retired_images": retired_images,
    }
    if append or existing is None or existing.get("qualified") != qualified:
        _mutable_private_json(path, state)
    return {
        "identity_sha256": identity,
        "sample_recorded": append,
        "sample_count": len(samples),
        "sample_span_seconds": span_seconds,
        "minimum_sample_spacing_seconds": MINIMUM_SAMPLE_SPACING_SECONDS,
        "maximum_sample_gap_seconds": MAXIMUM_SAMPLE_GAP_SECONDS,
        "minimum_stability_seconds": MINIMUM_KEEPER_STABILITY_SECONDS,
        "qualified": qualified,
    }


@contextlib.contextmanager
def _hold_retention_resource_locks(proofs: dict[str, RuntimeProof]):
    evidence: list[dict[str, object]] = []
    with contextlib.ExitStack() as stack:
        for project in sorted(proofs):
            project_evidence = stack.enter_context(_hold_project_lock(project))
            port_evidence = stack.enter_context(_hold_port_lock(proofs[project].port))
            evidence.append(
                {
                    "project": project_evidence,
                    "port": port_evidence,
                }
            )
        yield evidence


def _inspect_image_alias_snapshot(image_id: str) -> dict[str, object]:
    if IMAGE_ID.fullmatch(image_id) is None:
        raise RuntimeError("manfred_candidate_retention_image_aliases_invalid")
    rows = _inspect("image", [image_id])
    if len(rows) != 1:
        raise RuntimeError("manfred_candidate_retention_image_inspection_invalid")
    snapshot = _image_alias_snapshot(_normalize_image(rows[0]))
    if snapshot["image_id"] != image_id:
        raise RuntimeError("manfred_candidate_retention_image_inspection_invalid")
    return snapshot


def _remaining_apply_timeout(
    deadline_monotonic: float, maximum_seconds: int
) -> int:
    remaining = float(deadline_monotonic) - time.monotonic()
    if remaining < 1:
        raise RuntimeError("manfred_candidate_retention_apply_deadline_exceeded")
    return max(1, min(int(maximum_seconds), int(remaining)))


def _apply_plan(
    plan: RetentionPlan, *, deadline_monotonic: float
) -> dict[str, object]:
    _assert_plan_partition(plan)
    actions: list[dict[str, str]] = []
    for candidate in plan.retirees:
        if candidate.project == "ea" or not candidate.project.startswith(PROJECT_NAME_PREFIX):
            raise RuntimeError("manfred_candidate_retention_live_project_forbidden")
        for row in candidate.containers:
            identifier = str(row["id"])
            _run(
                ["docker", "container", "rm", "--force", identifier],
                timeout=_remaining_apply_timeout(deadline_monotonic, 120),
            )
            actions.append({"kind": "container", "id": identifier, "project": candidate.project})
    for candidate in plan.retirees:
        for row in candidate.networks:
            identifier = str(row["id"])
            _run(
                ["docker", "network", "rm", identifier],
                timeout=_remaining_apply_timeout(deadline_monotonic, 60),
            )
            actions.append({"kind": "network", "id": identifier, "project": candidate.project})
    for candidate in plan.retirees:
        for row in candidate.volumes:
            name = str(row["name"])
            _run(
                ["docker", "volume", "rm", name],
                timeout=_remaining_apply_timeout(deadline_monotonic, 60),
            )
            actions.append({"kind": "volume", "name": name, "project": candidate.project})

    removed_images: list[str] = []
    preserved_at_apply: list[dict[str, str]] = []
    expected_aliases = {
        str(row.get("image_id") or ""): dict(row)
        for row in plan.removable_image_aliases
    }
    if (
        len(expected_aliases) != len(plan.removable_image_aliases)
        or set(expected_aliases) != set(plan.removable_image_ids)
    ):
        raise RuntimeError("manfred_candidate_retention_image_alias_plan_invalid")
    for image_id in plan.removable_image_ids:
        references = _listed(
            [
                "docker",
                "container",
                "ls",
                "--all",
                "--quiet",
                "--filter",
                f"ancestor={image_id}",
            ]
        )
        if references:
            preserved_at_apply.append({"image_id": image_id, "reason": "referenced_at_apply"})
            continue
        _remaining_apply_timeout(deadline_monotonic, 60)
        if _inspect_image_alias_snapshot(image_id) != expected_aliases[image_id]:
            preserved_at_apply.append(
                {"image_id": image_id, "reason": "image_alias_changed_at_apply"}
            )
            continue
        _run(
            ["docker", "image", "rm", image_id],
            timeout=_remaining_apply_timeout(deadline_monotonic, 120),
        )
        removed_images.append(image_id)
        actions.append({"kind": "image", "id": image_id})
    return {
        "actions": actions,
        "removed_image_ids": removed_images,
        "preserved_images_at_apply": preserved_at_apply,
    }


def _verify_after_apply(plan: RetentionPlan) -> dict[str, object]:
    _assert_plan_partition(plan)
    retained_candidates = _retained_candidates(plan)
    post = _discover_inventory(
        {candidate.proof.image_id for candidate in retained_candidates}
    )
    projects = _candidate_projects(post)
    pending_intent_projects = {
        str(row["project"]) for row in plan.pending_intent_quarantine
    }
    expected_projects = {
        *(candidate.project for candidate in retained_candidates),
        *pending_intent_projects,
        *(
            str(row["project"])
            for row in plan.unknown_project_quarantine
        ),
    }
    if projects != expected_projects:
        raise RuntimeError("manfred_candidate_retention_retired_resources_remain")
    keeper = _validate_candidate(plan.keeper.project, plan.keeper.proof, post)
    if not keeper.complete or not keeper.healthy:
        raise RuntimeError("manfred_candidate_retention_keeper_changed")
    for expected in retained_candidates[1:]:
        observed = _validate_candidate(expected.project, expected.proof, post)
        if observed != expected:
            raise RuntimeError(
                "manfred_candidate_retention_retained_candidate_changed"
            )
    for expected in plan.pending_intent_quarantine:
        resources = _pending_project_resources(str(expected["project"]), post)
        digest = hashlib.sha256(
            json.dumps(
                resources, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()
        if digest != expected.get("resource_digest_sha256"):
            raise RuntimeError(
                "manfred_candidate_retention_pending_quarantine_changed"
            )
    for expected in plan.unknown_project_quarantine:
        resources = _pending_project_resources(str(expected["project"]), post)
        digest = hashlib.sha256(
            json.dumps(
                resources, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()
        if digest != expected.get("resource_digest_sha256"):
            raise RuntimeError(
                "manfred_candidate_retention_unknown_quarantine_changed"
            )
    live_after = _live_fingerprint(post)
    if live_after != plan.live_before:
        raise RuntimeError("manfred_candidate_retention_live_ea_changed")
    legacy_after = _legacy_quarantine(post)
    if legacy_after != plan.quarantined_projects:
        raise RuntimeError("manfred_candidate_retention_legacy_quarantine_changed")
    _assert_keeper_http(plan.keeper.proof)
    return {
        "live_ea_after": live_after,
        "live_ea_unchanged": True,
        "keeper_revalidated": True,
        "active_candidate_projects": sorted(expected_projects),
        "pending_retirees_revalidated": len(plan.pending_retirees),
        "protected_newer_candidates_revalidated": len(
            plan.protected_newer_candidates
        ),
        "pending_intent_quarantine_unchanged": True,
        "unknown_project_quarantine_after": list(
            plan.unknown_project_quarantine
        ),
        "unknown_project_quarantine_unchanged": True,
        "legacy_quarantine_after": list(legacy_after),
        "legacy_quarantine_unchanged": True,
    }


def _safe_error(exc: BaseException) -> str:
    text = str(exc)
    if re.fullmatch(r"[a-z0-9_.:-]{1,160}", text):
        return text
    return "manfred_candidate_retention_failed"


def _atomic_receipt(path: Path, payload: dict[str, object]) -> None:
    path = Path(path).expanduser()
    absolute = path if path.is_absolute() else Path.cwd() / path
    parent = absolute.parent
    try:
        resolved_parent = parent.resolve(strict=True)
        parent_status = resolved_parent.stat()
    except OSError as exc:
        raise RuntimeError("manfred_candidate_retention_output_path_invalid") from exc
    if (
        resolved_parent != parent.absolute()
        or not stat.S_ISDIR(parent_status.st_mode)
        or parent_status.st_uid != os.getuid()
        or stat.S_IMODE(parent_status.st_mode) & 0o022
    ):
        raise RuntimeError("manfred_candidate_retention_output_path_invalid")
    destination = resolved_parent / absolute.name
    if os.path.lexists(destination):
        raise RuntimeError("manfred_candidate_retention_output_exists")
    descriptor, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", dir=resolved_parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, destination, follow_symlinks=False)
        except FileExistsError as exc:
            raise RuntimeError("manfred_candidate_retention_output_exists") from exc
        Path(temporary).unlink()
        directory_descriptor = os.open(
            resolved_parent,
            os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC,
        )
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        Path(temporary).unlink(missing_ok=True)


def _assert_new_receipt_path(path: Path) -> Path:
    path = Path(path).expanduser()
    absolute = path if path.is_absolute() else Path.cwd() / path
    try:
        resolved_parent = absolute.parent.resolve(strict=True)
        metadata = resolved_parent.stat()
    except OSError as exc:
        raise RuntimeError("manfred_candidate_retention_output_path_invalid") from exc
    if (
        resolved_parent != absolute.parent.absolute()
        or metadata.st_uid != os.getuid()
        or not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) & 0o022
    ):
        raise RuntimeError("manfred_candidate_retention_output_path_invalid")
    if os.path.lexists(resolved_parent / absolute.name):
        raise RuntimeError("manfred_candidate_retention_output_exists")
    return resolved_parent / absolute.name


def _automatic_receipt_path() -> Path:
    directory = operator_state_root() / "manfred-candidate-retention-receipts"
    try:
        directory.mkdir(parents=True, mode=0o700, exist_ok=True)
        resolved = directory.resolve(strict=True)
        metadata = resolved.stat()
    except OSError as exc:
        raise RuntimeError("manfred_candidate_retention_output_path_invalid") from exc
    if (
        resolved != directory.absolute()
        or metadata.st_uid != os.getuid()
        or not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) & 0o022
    ):
        raise RuntimeError("manfred_candidate_retention_output_path_invalid")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return resolved / f"retention-{timestamp}-{os.getpid()}-{secrets.token_hex(4)}.json"


def _rotate_automatic_receipts(
    directory: Path,
    *,
    preserve_names: set[str] | None = None,
    maximum_receipts: int = MAX_AUTOMATIC_RECEIPTS,
) -> dict[str, object]:
    if maximum_receipts < 1:
        raise RuntimeError("manfred_candidate_retention_receipt_limit_invalid")
    directory = Path(directory)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(directory, flags)
    except OSError as exc:
        raise RuntimeError(
            "manfred_candidate_retention_receipt_directory_invalid"
        ) from exc
    removed: list[str] = []
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) & 0o022
        ):
            raise RuntimeError(
                "manfred_candidate_retention_receipt_directory_invalid"
            )
        managed: list[str] = []
        for name in os.listdir(descriptor):
            if AUTOMATIC_RECEIPT_NAME.fullmatch(name) is None:
                continue
            try:
                entry = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            except OSError as exc:
                raise RuntimeError(
                    "manfred_candidate_retention_receipt_rotation_invalid"
                ) from exc
            if (
                not stat.S_ISREG(entry.st_mode)
                or entry.st_uid != os.getuid()
                or entry.st_nlink != 1
                or stat.S_IMODE(entry.st_mode) != 0o600
            ):
                raise RuntimeError(
                    "manfred_candidate_retention_receipt_rotation_invalid"
                )
            managed.append(name)
        managed.sort()
        preserved = set(preserve_names or set())
        bundles: dict[str, list[str]] = {}
        for name in managed:
            bundle = (
                f"{name.removesuffix('.intent.json')}.json"
                if name.endswith(".intent.json")
                else name
            )
            bundles.setdefault(bundle, []).append(name)
        excess = max(0, len(managed) - maximum_receipts)
        selected: list[str] = []
        for bundle in sorted(bundles):
            names = sorted(
                bundles[bundle],
                key=lambda name: (name.endswith(".intent.json"), name),
            )
            if not excess or preserved.intersection(names):
                continue
            selected.extend(names)
            excess = max(0, excess - len(names))
        if excess:
            raise RuntimeError(
                "manfred_candidate_retention_receipt_rotation_invalid"
            )
        for name in selected:
            os.unlink(name, dir_fd=descriptor)
            removed.append(name)
            os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return {
        "maximum_receipts": maximum_receipts,
        "managed_before": len(managed),
        "removed_count": len(removed),
        "managed_after": len(managed) - len(removed),
    }


def _rotate_for_automatic_output(output_receipt: Path) -> dict[str, object]:
    preserve_names = {output_receipt.name}
    intent_path = _intent_receipt_path(output_receipt)
    if os.path.lexists(intent_path):
        preserve_names.add(intent_path.name)
    return _rotate_automatic_receipts(
        output_receipt.parent,
        preserve_names=preserve_names,
    )


def _registry_activity_audit(
    *,
    explicit_attempted: int,
    explicit_confirmed: int,
    automatic_enrollment: dict[str, object],
) -> dict[str, object]:
    automatic_attempted = int(
        automatic_enrollment["registration_attempted_count"]
    )
    automatic_possible = int(
        automatic_enrollment["registry_write_possible_count"]
    )
    automatic_confirmed = int(
        automatic_enrollment["registration_confirmed_count"]
    )
    automatic_growth = int(automatic_enrollment["enrolled_project_count"])
    return {
        "explicit": {
            "registration_attempted_count": explicit_attempted,
            "registry_write_possible_count": explicit_attempted,
            "registration_confirmed_count": explicit_confirmed,
            "registry_growth_confirmed_count": 0,
            "registry_growth_confirmation_available": False,
        },
        "automatic": {
            "registration_attempted_count": automatic_attempted,
            "registry_write_possible_count": automatic_possible,
            "registration_confirmed_count": automatic_confirmed,
            "registry_growth_confirmed_count": automatic_growth,
            "registry_growth_confirmation_available": True,
        },
        "combined": {
            "registration_attempted_count": (
                explicit_attempted + automatic_attempted
            ),
            "registry_write_possible_count": (
                explicit_attempted + automatic_possible
            ),
            "registration_confirmed_count": (
                explicit_confirmed + automatic_confirmed
            ),
            "registry_growth_confirmed_count": automatic_growth,
            "exact_registry_write_count_reported": False,
        },
    }


def retain_candidates(
    *,
    runtime_receipts: list[Path] | None,
    output_receipt: Path,
    apply: bool,
    state_path: Path | None = None,
    registry_path: Path | None = None,
    automatic_receipt_retention_before: dict[str, object] | None = None,
) -> dict[str, object]:
    explicit_registration_attempted_count = 0
    explicit_registration_confirmed_count = 0
    base: dict[str, object] = {
        "schema": RECEIPT_SCHEMA,
        "observed_at": _utc_now(),
        "mode": "apply" if apply else "dry_run",
        "apply_requested": apply,
        "dry_run_default": True,
        "secrets_included": False,
        "live_ea_mutation_requested": False,
        "automatic_candidate_enrollment": _empty_automatic_enrollment_audit(
            apply=apply
        ),
    }
    if automatic_receipt_retention_before is not None:
        base["automatic_receipt_retention_before"] = dict(
            automatic_receipt_retention_before
        )
    try:
        output_receipt = _assert_new_receipt_path(output_receipt)
        base["receipt_path"] = str(output_receipt)
        with hold_candidate_fleet_lock(skip_if_busy=True) as lock:
            if lock is None:
                receipt = {
                    **base,
                    "status": "skipped",
                    "reason": "candidate_proof_active",
                    "mutations_performed": 0,
                }
                _atomic_receipt(output_receipt, receipt)
                return receipt
            registry = Path(registry_path or default_registry_path())
            for explicit_receipt in runtime_receipts or []:
                explicit_registration_attempted_count += 1
                registration = register_candidate_receipt(
                    explicit_receipt,
                    registry_path=registry,
                )
                if (
                    isinstance(registration, dict)
                    and registration.get("registered") is True
                ):
                    explicit_registration_confirmed_count += 1
            receipt_paths = registered_candidate_receipts(registry_path=registry)
            pending = registered_candidate_pending(registry_path=registry)
            proofs = (
                _load_runtime_proofs(receipt_paths) if receipt_paths else ()
            )
            prelock_inventory = _discover_inventory(set())
            projects = _candidate_projects(prelock_inventory)
            pending_status = _pending_intent_status(pending, prelock_inventory)
            active_pending_projects = set(pending_status["active_projects"])
            candidate_projects = projects - active_pending_projects
            registered_active_projects = {
                str(proof.project)
                for proof in proofs
                if proof.project in candidate_projects
            }
            unknown_projects = candidate_projects - registered_active_projects
            enrollment_audit = _auto_enroll_unregistered_projects(
                unknown_projects,
                prelock_inventory,
                registry_path=registry,
                apply=apply,
            )
            base["automatic_candidate_enrollment"] = enrollment_audit
            receipt_paths = registered_candidate_receipts(registry_path=registry)
            pending = registered_candidate_pending(registry_path=registry)
            proofs = (
                _load_runtime_proofs(receipt_paths) if receipt_paths else ()
            )
            pending_status = _pending_intent_status(pending, prelock_inventory)
            active_pending_projects = set(pending_status["active_projects"])
            candidate_projects = projects - active_pending_projects
            registered_active_projects = {
                str(proof.project)
                for proof in proofs
                if proof.project in candidate_projects
            }
            unknown_projects = candidate_projects - registered_active_projects
            unknown_quarantine = _unregistered_project_quarantine(
                unknown_projects, prelock_inventory
            )
            managed_projects = candidate_projects - unknown_projects
            if not managed_projects:
                existing_image_ids = _existing_image_ids()
                historical_proofs = tuple(
                    proof
                    for proof in proofs
                    if proof.image_id in existing_image_ids
                )
                historical_image_ids = {
                    proof.image_id for proof in historical_proofs
                }
                revalidated = _discover_inventory(historical_image_ids)
                if _candidate_projects(revalidated) != projects:
                    raise RuntimeError(
                        "manfred_candidate_retention_inventory_changed_after_lock"
                    )
                if registered_candidate_pending(registry_path=registry) != pending:
                    raise RuntimeError(
                        "manfred_candidate_retention_pending_reconciliation_changed"
                    )
                final_pending_status = _pending_intent_status(
                    pending, revalidated
                )
                if (
                    final_pending_status["active_projects"]
                    != pending_status["active_projects"]
                ):
                    raise RuntimeError(
                        "manfred_candidate_retention_pending_reconciliation_changed"
                    )
                final_unknown_projects = (
                    _candidate_projects(revalidated)
                    - set(final_pending_status["active_projects"])
                    - registered_active_projects
                )
                final_unknown_quarantine = _unregistered_project_quarantine(
                    final_unknown_projects, revalidated
                )
                if (
                    final_unknown_projects != unknown_projects
                    or final_unknown_quarantine != unknown_quarantine
                ):
                    raise RuntimeError(
                        "manfred_candidate_retention_unknown_quarantine_changed"
                    )
                historical_quarantine = _historical_image_quarantine(
                    historical_proofs, revalidated
                )
                preserved_projects = {
                    str(proof.project)
                    for proof in historical_proofs
                    if proof.project
                }
                pending_reconciliation = (
                    _clear_expired_absent_pending(
                        final_pending_status, registry_path=registry
                    )
                    if apply
                    else ()
                )
                if apply:
                    state = Path(
                        state_path
                        or operator_state_root()
                        / "manfred-candidate-retention-state.json"
                    )
                    ledger_updates = tuple(
                        {
                            "image_id": row["image_id"],
                            "projects": row["projects"],
                            "receipt_sha256": row["receipt_sha256"],
                            "renew": False,
                        }
                        for row in historical_quarantine
                    )
                    retained_ledger = _update_retired_image_ledger(
                        state,
                        ledger_updates,
                        now=datetime.now(timezone.utc),
                        retain_image_ids=existing_image_ids,
                    )
                    registry_compaction = compact_candidate_registry(
                        preserved_projects, registry_path=registry
                    )
                else:
                    retained_ledger = {}
                    registry_compaction = {
                        "status": "not_run_dry_run",
                        "preserved_projects": sorted(preserved_projects),
                    }
                receipt = {
                    **base,
                    "fleet_lock": lock,
                    "status": "pass",
                    "action": (
                        "pending_candidate_quarantined"
                        if active_pending_projects
                        else "unregistered_candidate_quarantined"
                        if unknown_projects
                        else "historical_images_quarantined"
                        if historical_quarantine
                        else "no_active_managed_candidate"
                    ),
                    "post_lock_inventory_revalidated": True,
                    "live_ea": _live_fingerprint(revalidated),
                    "quarantined_projects": list(
                        _legacy_quarantine(revalidated)
                    ),
                    "legacy_quarantine_excluded_from_managed_count": True,
                    "pending_intent_quarantine": list(
                        final_pending_status["quarantined"]
                    ),
                    "unknown_project_quarantine": list(
                        final_unknown_quarantine
                    ),
                    "unknown_quarantine_excluded_from_managed_count": True,
                    "historical_image_quarantine": list(
                        historical_quarantine
                    ),
                    "historical_image_removal_authorized": False,
                    "absent_pending_intents": list(
                        final_pending_status["absent"]
                    ),
                    "pending_registry_reconciliation": list(
                        pending_reconciliation
                    ),
                    "registry_compaction": registry_compaction,
                    "retired_image_ledger": {
                        "entry_count": len(retained_ledger),
                        "image_ids": sorted(retained_ledger),
                        "minimum_post_retirement_grace_seconds": (
                            IMAGE_RETENTION_GRACE_SECONDS
                        ),
                        "ledger_window_seconds": (
                            RETIRED_IMAGE_LEDGER_WINDOW_SECONDS
                        ),
                        "updated": apply,
                    },
                    "mutations_performed": 0,
                }
                _atomic_receipt(output_receipt, receipt)
                return receipt
            bound = _bind_proofs(proofs, prelock_inventory, managed_projects)
            active_proofs = tuple(bound[project] for project in sorted(bound))
            existing_image_ids = _existing_image_ids()
            inspected_image_ids = {
                proof.image_id for proof in active_proofs
            }.union(
                proof.image_id
                for proof in proofs
                if proof.project not in managed_projects
                and proof.image_id in existing_image_ids
            )
            try:
                with _hold_retention_resource_locks(bound) as resource_locks:
                    inventory = _discover_inventory(inspected_image_ids)
                    if registered_candidate_pending(registry_path=registry) != pending:
                        raise RuntimeError(
                            "manfred_candidate_retention_pending_reconciliation_changed"
                        )
                    final_pending_status = _pending_intent_status(
                        pending, inventory
                    )
                    if (
                        final_pending_status["active_projects"]
                        != pending_status["active_projects"]
                    ):
                        raise RuntimeError(
                            "manfred_candidate_retention_pending_reconciliation_changed"
                        )
                    effective_state_path = Path(
                        state_path
                        or operator_state_root()
                        / "manfred-candidate-retention-state.json"
                    )
                    planning_now = datetime.now(timezone.utc).replace(
                        microsecond=0
                    )
                    (
                        retired_images,
                        preferred_keeper_project,
                        preferred_keeper_qualified,
                        state_sha256,
                    ) = _load_retention_state(
                        effective_state_path,
                        now=planning_now,
                    )
                    try:
                        plan = _build_plan(
                            proofs,
                            inventory,
                            now=planning_now,
                            retired_images=retired_images,
                            excluded_projects=set(
                                final_pending_status["active_projects"]
                            ).union(unknown_projects),
                            pending_intent_quarantine=tuple(
                                final_pending_status["quarantined"]
                            ),
                            unknown_project_quarantine=unknown_quarantine,
                            preferred_keeper_project=(
                                preferred_keeper_project
                            ),
                            preferred_keeper_qualified=(
                                preferred_keeper_qualified
                            ),
                        )
                    except _KeeperStabilizing as stabilizing:
                        _assert_state_clock_not_regressed(
                            effective_state_path,
                            now=planning_now,
                        )
                        _assert_keeper_http(stabilizing.keeper.proof)
                        live_ea = _live_fingerprint(inventory)
                        automatic_registration_attempted_count = int(
                            enrollment_audit["registration_attempted_count"]
                        )
                        automatic_registration_confirmed_count = int(
                            enrollment_audit["registration_confirmed_count"]
                        )
                        automatic_enrollment_confirmed_count = int(
                            enrollment_audit["enrolled_project_count"]
                        )
                        receipt = {
                            **base,
                            "fleet_lock": lock,
                            "resource_locks": resource_locks,
                            "post_lock_inventory_revalidated": True,
                            "status": "pass",
                            "action": "keeper_stabilizing",
                            "keeper": _candidate_summary(
                                stabilizing.keeper
                            ),
                            "planning_observed_at": planning_now.isoformat()
                            .replace("+00:00", "Z"),
                            "live_ea": live_ea,
                            "pending_intent_quarantine": list(
                                final_pending_status["quarantined"]
                            ),
                            "unknown_project_quarantine": list(
                                unknown_quarantine
                            ),
                            "absent_pending_intents": list(
                                final_pending_status["absent"]
                            ),
                            "pending_registry_reconciliation": [],
                            "stability": {
                                "keeper_age_seconds": (
                                    stabilizing.age_seconds
                                ),
                                "minimum_stability_seconds": (
                                    MINIMUM_KEEPER_STABILITY_SECONDS
                                ),
                                "qualified": False,
                                "sample_recorded": False,
                            },
                            "apply_deferred": bool(apply),
                            "mutations_performed": 0,
                            "mutations_performed_scope": "docker_resources",
                            "docker_resource_mutations_performed": 0,
                            "registry_activity": {
                                "explicit": {
                                    "registration_attempted_count": (
                                        explicit_registration_attempted_count
                                    ),
                                    "registry_write_possible_count": (
                                        explicit_registration_attempted_count
                                    ),
                                    "registration_confirmed_count": (
                                        explicit_registration_confirmed_count
                                    ),
                                    "registry_growth_confirmed_count": 0,
                                    "registry_growth_confirmation_available": False,
                                },
                                "automatic": {
                                    "registration_attempted_count": (
                                        automatic_registration_attempted_count
                                    ),
                                    "registry_write_possible_count": int(
                                        enrollment_audit[
                                            "registry_write_possible_count"
                                        ]
                                    ),
                                    "registration_confirmed_count": (
                                        automatic_registration_confirmed_count
                                    ),
                                    "registry_growth_confirmed_count": (
                                        automatic_enrollment_confirmed_count
                                    ),
                                    "registry_growth_confirmation_available": True,
                                },
                                "combined": {
                                    "registration_attempted_count": (
                                        explicit_registration_attempted_count
                                        + automatic_registration_attempted_count
                                    ),
                                    "registry_write_possible_count": (
                                        explicit_registration_attempted_count
                                        + int(
                                            enrollment_audit[
                                                "registry_write_possible_count"
                                            ]
                                        )
                                    ),
                                    "registration_confirmed_count": (
                                        explicit_registration_confirmed_count
                                        + automatic_registration_confirmed_count
                                    ),
                                    "registry_growth_confirmed_count": (
                                        automatic_enrollment_confirmed_count
                                    ),
                                    "exact_registry_write_count_reported": False,
                                },
                            },
                        }
                        _atomic_receipt(output_receipt, receipt)
                        return receipt
                    _assert_keeper_http(plan.keeper.proof)
                    pending_reconciliation = (
                        _clear_expired_absent_pending(
                            final_pending_status, registry_path=registry
                        )
                        if apply
                        else ()
                    )
                    stability = _record_stability_sample(
                        effective_state_path,
                        plan,
                        now=planning_now,
                        expected_state_sha256=state_sha256,
                        state_prevalidated=True,
                    )
                    destructive_targets = bool(
                        plan.retirees or plan.removable_image_ids
                    )
                    plan_receipt = _plan_receipt(plan)
                    apply_deferred = bool(
                        apply
                        and destructive_targets
                        and not stability["qualified"]
                    )
                    receipt = {
                        **base,
                        "fleet_lock": lock,
                        "resource_locks": resource_locks,
                        "post_lock_inventory_revalidated": True,
                        "status": "pass",
                        "action": (
                            "planned"
                            if not apply
                            else "stabilizing"
                            if apply_deferred
                            else "applied"
                            if destructive_targets
                            else "housekeeping"
                            if plan.grace_candidates
                            else "observed"
                        ),
                        "plan": plan_receipt,
                        "absent_pending_intents": list(
                            final_pending_status["absent"]
                        ),
                        "pending_registry_reconciliation": list(
                            pending_reconciliation
                        ),
                        "stability": stability,
                        "registry_activity": _registry_activity_audit(
                            explicit_attempted=(
                                explicit_registration_attempted_count
                            ),
                            explicit_confirmed=(
                                explicit_registration_confirmed_count
                            ),
                            automatic_enrollment=enrollment_audit,
                        ),
                        "apply_deferred": apply_deferred,
                        "mutations_performed": 0,
                    }
                    if apply and not destructive_targets:
                        existing_images = _existing_image_ids()
                        retained_ledger = _update_retired_image_ledger(
                            effective_state_path,
                            plan.grace_candidates,
                            now=datetime.now(timezone.utc),
                            retain_image_ids=existing_images,
                        )
                        registry_projects = {
                            *(
                                candidate.project
                                for candidate in _retained_candidates(plan)
                            ),
                            *plan.deferred_image_projects,
                        }
                        registry_compaction = compact_candidate_registry(
                            registry_projects,
                            registry_path=registry,
                        )
                        receipt["registry_compaction"] = registry_compaction
                        receipt["retired_image_ledger"] = {
                            "entry_count": len(retained_ledger),
                            "image_ids": sorted(retained_ledger),
                            "minimum_post_retirement_grace_seconds": (
                                IMAGE_RETENTION_GRACE_SECONDS
                            ),
                            "ledger_window_seconds": (
                                RETIRED_IMAGE_LEDGER_WINDOW_SECONDS
                            ),
                        }
                    if apply and destructive_targets and not apply_deferred:
                        apply_deadline_monotonic = (
                            time.monotonic()
                            + RETIREMENT_APPLY_BUDGET_SECONDS
                        )
                        staged_ledger = _update_retired_image_ledger(
                            effective_state_path,
                            plan.grace_candidates,
                            now=datetime.now(timezone.utc),
                        )
                        plan_digest = hashlib.sha256(
                            json.dumps(
                                plan_receipt,
                                sort_keys=True,
                                separators=(",", ":"),
                            ).encode("utf-8")
                        ).hexdigest()
                        intent = {
                            "schema": RECEIPT_SCHEMA,
                            "observed_at": _utc_now(),
                            "status": "authorized",
                            "action": "apply_intent",
                            "fleet_lock": lock,
                            "resource_locks": resource_locks,
                            "keeper_project": plan.keeper.project,
                            "targets": _mutation_targets(plan),
                            "plan": plan_receipt,
                            "plan_sha256": plan_digest,
                            "apply_budget_seconds": (
                                RETIREMENT_APPLY_BUDGET_SECONDS
                            ),
                            "retired_image_ledger": {
                                "staged_image_ids": sorted(
                                    str(row["image_id"])
                                    for row in plan.grace_candidates
                                ),
                                "entry_count": len(staged_ledger),
                                "minimum_post_retirement_grace_seconds": (
                                    IMAGE_RETENTION_GRACE_SECONDS
                                ),
                                "ledger_window_seconds": (
                                    RETIRED_IMAGE_LEDGER_WINDOW_SECONDS
                                ),
                            },
                            "live_ea_mutation_requested": False,
                            "legacy_quarantine_mutation_requested": False,
                            "secrets_included": False,
                        }
                        intent_path = _intent_receipt_path(output_receipt)
                        _atomic_receipt(intent_path, intent)
                        intent_digest = hashlib.sha256(
                            json.dumps(
                                intent,
                                sort_keys=True,
                                separators=(",", ":"),
                            ).encode("utf-8")
                        ).hexdigest()
                        execution = _apply_plan(
                            plan,
                            deadline_monotonic=apply_deadline_monotonic,
                        )
                        verification = _verify_after_apply(plan)
                        existing_after_apply = _existing_image_ids()
                        completion_updates = tuple(
                            {**row, "renew": True}
                            for row in plan.grace_candidates
                        )
                        retained_ledger = _update_retired_image_ledger(
                            effective_state_path,
                            completion_updates,
                            now=datetime.now(timezone.utc),
                            retain_image_ids=existing_after_apply,
                        )
                        referenced_at_apply = {
                            str(row["image_id"])
                            for row in execution["preserved_images_at_apply"]
                        }
                        registry_projects = {
                            *(
                                candidate.project
                                for candidate in _retained_candidates(plan)
                            ),
                            *plan.deferred_image_projects,
                            *(
                                str(proof.project)
                                for proof in proofs
                                if proof.project
                                and proof.image_id in referenced_at_apply
                            ),
                        }
                        registry_compaction = compact_candidate_registry(
                            registry_projects,
                            registry_path=registry,
                        )
                        receipt.update(
                            {
                                "execution": execution,
                                "verification": verification,
                                "registry_compaction": registry_compaction,
                                "retired_image_ledger": {
                                    "entry_count": len(retained_ledger),
                                    "image_ids": sorted(retained_ledger),
                                    "minimum_post_retirement_grace_seconds": (
                                        IMAGE_RETENTION_GRACE_SECONDS
                                    ),
                                    "ledger_window_seconds": (
                                        RETIRED_IMAGE_LEDGER_WINDOW_SECONDS
                                    ),
                                },
                                "intent_receipt": {
                                    "filename": intent_path.name,
                                    "payload_sha256": intent_digest,
                                },
                                "mutations_performed": len(execution["actions"]),
                            }
                        )
                    _atomic_receipt(output_receipt, receipt)
                    return receipt
            except RuntimeError as exc:
                if str(exc) not in {
                    "manfred_candidate_project_lock_held",
                    "manfred_candidate_port_lock_held",
                }:
                    raise
                receipt = {
                    **base,
                    "status": "skipped",
                    "reason": "candidate_proof_active",
                    "lock_conflict": str(exc),
                    "mutations_performed": 0,
                }
                _atomic_receipt(output_receipt, receipt)
                return receipt
    except BaseException as exc:
        failure = {
            **base,
            "status": "fail",
            "error": _safe_error(exc),
            "live_ea_mutation_requested": False,
        }
        try:
            _atomic_receipt(output_receipt, failure)
        except BaseException:
            pass
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Plan or explicitly apply bounded retention for proven Manfred candidate projects."
        )
    )
    parser.add_argument(
        "--runtime-receipt",
        action="append",
        default=[],
        help="Bootstrap-enroll a mode-0600 runtime v3 proof; future proofs self-register.",
    )
    parser.add_argument(
        "--registry",
        default=str(default_registry_path()),
        help="Bounded mode-0600 registry populated by successful candidate proofs.",
    )
    parser.add_argument(
        "--receipt",
        help="Immutable mode-0600 receipt output; omitted creates a unique state receipt.",
    )
    parser.add_argument(
        "--state",
        default=str(operator_state_root() / "manfred-candidate-retention-state.json"),
        help="Mutable mode-0600 health-sample state (receipts remain immutable).",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Perform the exact validated removals. Without this flag, only plan.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    automatic_receipt = not bool(args.receipt)
    output_receipt: Path | None = None
    try:
        output_receipt = (
            Path(args.receipt) if args.receipt else _automatic_receipt_path()
        )
        retention_before: dict[str, object] | None = None
        if automatic_receipt:
            retention_before = _rotate_automatic_receipts(
                output_receipt.parent,
                maximum_receipts=MAX_AUTOMATIC_RECEIPTS - 2,
            )
            retention_before["reserved_current_run_slots"] = 2
        receipt = retain_candidates(
            runtime_receipts=[Path(value) for value in args.runtime_receipt],
            output_receipt=output_receipt,
            apply=bool(args.apply),
            state_path=Path(args.state),
            registry_path=Path(args.registry),
            automatic_receipt_retention_before=retention_before,
        )
        if automatic_receipt:
            receipt = {
                **receipt,
                "automatic_receipt_retention": (
                    _rotate_for_automatic_output(output_receipt)
                ),
            }
    except BaseException as exc:
        if automatic_receipt and output_receipt is not None:
            with contextlib.suppress(BaseException):
                _rotate_for_automatic_output(output_receipt)
        print(
            json.dumps(
                {
                    "schema": RECEIPT_SCHEMA,
                    "status": "fail",
                    "error": _safe_error(exc),
                    "live_ea_mutation_requested": False,
                    "secrets_included": False,
                },
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
