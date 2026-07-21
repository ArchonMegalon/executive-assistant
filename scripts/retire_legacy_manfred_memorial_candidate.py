#!/usr/bin/env python3
"""Explicit, one-time retirement for the unbound legacy Manfred candidate.

This module is intentionally not part of automatic candidate retention.  It accepts
only the historical ``ea-manfred-candidate`` project, defaults to observation only,
and requires an operator-supplied full image ID before it will even build a plan.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import secrets
import socket
import stat
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.cleanup_manfred_memorial_candidates import (  # noqa: E402
    Inventory,
    _assert_new_receipt_path,
    _atomic_receipt,
    _discover_inventory,
    _existing_image_ids,
    _image_alias_snapshot,
    _inspect_image_alias_snapshot,
    _listed,
    _live_fingerprint,
    _run,
    _safe_error,
)
from scripts.manfred_candidate_fleet_lock import (  # noqa: E402
    hold_candidate_fleet_lock,
)
from scripts.manfred_candidate_registry import (  # noqa: E402
    RUNTIME_SCHEMA,
    default_registry_path,
    operator_state_root,
    registered_candidate_pending,
    registered_candidate_receipts,
)
from scripts.prepare_manfred_memorial_candidate import (  # noqa: E402
    PROJECT_NAME_PREFIX,
    _validate_project_name,
)
from scripts.run_manfred_memorial_candidate import _hold_port_lock  # noqa: E402


RECEIPT_SCHEMA = "ea.manfred_memorial_legacy_candidate_retirement.v1"
LEGACY_PROJECT = "ea-manfred-candidate"
LEGACY_PORT = 18090
EXPECTED_SERVICES = ("api", "gateway", "postgres", "redis")
EXPECTED_NETWORKS = ("backend", "ingress")
LEGACY_EXPECTED_NETWORKS = ("backend", "candidate", "ingress")
EXPECTED_VOLUMES = ("artifacts", "postgres_data", "redis_data")
EXPECTED_SERVICE_IMAGES = {
    "postgres": "postgres:16-alpine@sha256:16bc17c64a573ef34162af9298258d1aec548232985b33ed7b1eac33ba35c229",
    "redis": "redis:7-alpine@sha256:6ab0b6e7381779332f97b8ca76193e45b0756f38d4c0dcda72dbb3c32061ab99",
}
LEGACY_COMPOSE_IMAGE_IDS = {
    "postgres": "sha256:fff3594bf464bea0f502788874403882d8bbbe618b3250f8649e7e42fd118020",
    "redis": "sha256:487efc0616382465781b8fdc3d6d1db449e6fd80ae23bf48432a2da6b6929908",
}
LEGACY_COMPOSE_DEPENDS_ON = {
    "api": "postgres:service_healthy:false,redis:service_healthy:false",
    "gateway": "api:service_healthy:false",
    "postgres": "",
    "redis": "",
}
EXPECTED_VOLUME_USERS = {
    "artifacts": ("api", "/data/artifacts"),
    "postgres_data": ("postgres", "/var/lib/postgresql/data"),
    "redis_data": ("redis", "/data"),
}
LEGACY_COMPOSE_VERSION = "5.1.3"
LEGACY_COMPOSE_FILE = "/docker/EA/deploy/manfred-memorial/docker-compose.candidate.yml"
LEGACY_ENVIRONMENT_FILE = (
    "/home/tibor/.local/share/ea-deploy/manfred-memorial/candidate.env"
)
LEGACY_WORKING_DIRECTORY = "/docker/EA/deploy/manfred-memorial"
LEGACY_CONTAINER_LABEL_KEYS = frozenset(
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
        "com.docker.compose.service",
        "com.docker.compose.version",
    }
)
LEGACY_NETWORK_LABEL_KEYS = frozenset(
    {
        "com.docker.compose.config-hash",
        "com.docker.compose.network",
        "com.docker.compose.project",
        "com.docker.compose.version",
    }
)
LEGACY_VOLUME_LABEL_KEYS = frozenset(
    {
        "com.docker.compose.config-hash",
        "com.docker.compose.project",
        "com.docker.compose.version",
        "com.docker.compose.volume",
    }
)
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
IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}")
HEX_40 = re.compile(r"[0-9a-f]{40}")
HEX_64 = re.compile(r"[0-9a-f]{64}")
IMAGE_LOCATOR = re.compile(r"ea-runtime:manfred-[0-9a-f]{40}")
COMPOSE_CONFIG_HASH = re.compile(r"[0-9a-f]{64}")
MAX_RECEIPT_BYTES = 1024 * 1024
RESUME_CONTRACT_VERSION = 1
PROTECTED_IMAGE_LABELS = frozenset(
    {
        "ea.retention.protected",
        "io.ea.retention.protected",
        "org.opencontainers.image.retention.protected",
    }
)


@dataclass(frozen=True)
class ManagedProof:
    project: str
    observed_at: datetime
    image: str
    image_id: str
    revision: str
    api_container_id: str
    gateway_container_id: str
    port: int
    receipt_sha256: str


@dataclass(frozen=True)
class StackSnapshot:
    project: str
    revision: str
    image: str
    image_id: str
    port: int
    container_ids: tuple[str, ...]
    network_ids: tuple[str, ...]
    volume_names: tuple[str, ...]
    digest_sha256: str


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _parse_timestamp(value: object) -> datetime:
    try:
        return datetime.strptime(str(value or ""), "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise RuntimeError("manfred_legacy_retirement_receipt_timestamp_invalid") from exc


def _read_private_json(path: Path) -> tuple[dict[str, object], str]:
    path = Path(path).expanduser()
    absolute = path if path.is_absolute() else Path.cwd() / path
    try:
        resolved = absolute.resolve(strict=True)
    except OSError as exc:
        raise RuntimeError("manfred_legacy_retirement_receipt_path_invalid") from exc
    if resolved != absolute.absolute() or resolved.is_symlink():
        raise RuntimeError("manfred_legacy_retirement_receipt_path_invalid")
    flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(resolved, flags)
    except OSError as exc:
        raise RuntimeError("manfred_legacy_retirement_receipt_path_invalid") from exc
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
            raise RuntimeError("manfred_legacy_retirement_receipt_file_invalid")
        content = b""
        while len(content) <= MAX_RECEIPT_BYTES:
            chunk = os.read(
                descriptor, min(65536, MAX_RECEIPT_BYTES + 1 - len(content))
            )
            if not chunk:
                break
            content += chunk
        after = os.fstat(descriptor)
        if (
            len(content) != before.st_size
            or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        ):
            raise RuntimeError("manfred_legacy_retirement_receipt_changed")
    finally:
        os.close(descriptor)
    try:
        payload = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("manfred_legacy_retirement_receipt_json_invalid") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("manfred_legacy_retirement_receipt_json_invalid")
    return dict(payload), hashlib.sha256(content).hexdigest()


def _parse_managed_proof(path: Path) -> ManagedProof:
    payload, digest = _read_private_json(path)
    try:
        project = _validate_project_name(payload.get("compose_project"))
        port = int(payload.get("candidate_port"))
    except (TypeError, ValueError) as exc:
        raise RuntimeError("manfred_legacy_retirement_managed_receipt_invalid") from exc
    image = str(payload.get("image") or "")
    image_id = str(payload.get("image_id") or "")
    revision = str(payload.get("image_source_revision") or "")
    candidate_images = dict(payload.get("candidate_container_images") or {})
    api = dict(candidate_images.get("api") or {})
    gateway = dict(candidate_images.get("gateway") or {})
    api_id = str(api.get("container_id") or "")
    gateway_id = str(gateway.get("container_id") or "")
    if (
        payload.get("schema") != RUNTIME_SCHEMA
        or payload.get("status") != "pass"
        or project == LEGACY_PROJECT
        or not project.startswith(PROJECT_NAME_PREFIX)
        or IMAGE_LOCATOR.fullmatch(image) is None
        or IMAGE_ID.fullmatch(image_id) is None
        or HEX_40.fullmatch(revision) is None
        or image != f"ea-runtime:manfred-{revision}"
        or str(payload.get("runtime_source_revision") or "") != revision
        or str(api.get("image_id") or "") != image_id
        or str(gateway.get("image_id") or "") != image_id
        or HEX_64.fullmatch(api_id) is None
        or HEX_64.fullmatch(gateway_id) is None
        or not 1024 <= port <= 65535
        or payload.get("candidate_left_running_for_soak") is not True
        or payload.get("live_ea_api_unchanged") is not True
        or payload.get("promotion_authority") is not False
    ):
        raise RuntimeError("manfred_legacy_retirement_managed_receipt_invalid")
    return ManagedProof(
        project=project,
        observed_at=_parse_timestamp(payload.get("observed_at")),
        image=image,
        image_id=image_id,
        revision=revision,
        api_container_id=api_id,
        gateway_container_id=gateway_id,
        port=port,
        receipt_sha256=digest,
    )


def _registry_state(registry_path: Path) -> dict[str, object]:
    paths = registered_candidate_receipts(registry_path=registry_path)
    proofs = tuple(_parse_managed_proof(path) for path in paths)
    pending = registered_candidate_pending(registry_path=registry_path)
    normalized_pending: list[dict[str, object]] = []
    for row in pending:
        image_id = str(row.get("image_id") or "")
        project = str(row.get("project") or "")
        try:
            port = int(row.get("port"))
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                "manfred_legacy_retirement_pending_registry_invalid"
            ) from exc
        if (
            IMAGE_ID.fullmatch(image_id) is None
            or project == LEGACY_PROJECT
            or not project.startswith(PROJECT_NAME_PREFIX)
            or not 1024 <= port <= 65535
        ):
            raise RuntimeError("manfred_legacy_retirement_pending_registry_invalid")
        normalized_pending.append(
            {"project": project, "port": port, "image_id": image_id}
        )
    identity = {
        "proofs": [
            {
                "project": proof.project,
                "observed_at": proof.observed_at.isoformat(),
                "image_id": proof.image_id,
                "receipt_sha256": proof.receipt_sha256,
            }
            for proof in sorted(proofs, key=lambda row: (row.observed_at, row.project))
        ],
        "pending": sorted(
            normalized_pending, key=lambda row: (str(row["project"]), int(row["port"]))
        ),
    }
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "proofs": proofs,
        "pending": tuple(normalized_pending),
        "digest_sha256": digest,
        "registered_image_ids": frozenset(proof.image_id for proof in proofs),
        "pending_image_ids": frozenset(
            str(row["image_id"]) for row in normalized_pending
        ),
    }


def _compose_label_allowlist(
    labels: dict[str, str], allowed: frozenset[str], required: dict[str, str]
) -> None:
    compose = {key for key in labels if key.startswith("com.docker.compose.")}
    if not compose.issubset(allowed) or any(
        labels.get(key) != value for key, value in required.items()
    ):
        raise RuntimeError("manfred_legacy_retirement_resource_labels_invalid")


def _legacy_container_label_contract(
    labels: dict[str, str], service: str, image_id: str
) -> None:
    keys = frozenset(
        key for key in labels if key.startswith("com.docker.compose.")
    )
    allowed_keys = LEGACY_CONTAINER_LABEL_KEYS
    if service in {"api", "gateway"}:
        allowed_keys = allowed_keys.union({"com.docker.compose.replace"})
    if keys not in {LEGACY_CONTAINER_LABEL_KEYS, allowed_keys}:
        raise RuntimeError("manfred_legacy_retirement_container_label_set_invalid")
    expected_compose_image = (
        image_id if service in {"api", "gateway"} else LEGACY_COMPOSE_IMAGE_IDS[service]
    )
    if (
        COMPOSE_CONFIG_HASH.fullmatch(
            labels.get("com.docker.compose.config-hash", "")
        )
        is None
        or labels.get("com.docker.compose.version") != LEGACY_COMPOSE_VERSION
        or labels.get("com.docker.compose.project.config_files")
        != LEGACY_COMPOSE_FILE
        or labels.get("com.docker.compose.project.environment_file")
        != LEGACY_ENVIRONMENT_FILE
        or labels.get("com.docker.compose.project.working_dir")
        != LEGACY_WORKING_DIRECTORY
        or labels.get("com.docker.compose.image") != expected_compose_image
        or labels.get("com.docker.compose.depends_on")
        != LEGACY_COMPOSE_DEPENDS_ON[service]
        or (
            "com.docker.compose.replace" in labels
            and labels["com.docker.compose.replace"] != f"{service}-1"
        )
    ):
        raise RuntimeError("manfred_legacy_retirement_container_labels_invalid")


def _legacy_resource_label_contract(
    labels: dict[str, str], *, kind: str
) -> None:
    expected_keys = {
        "network": LEGACY_NETWORK_LABEL_KEYS,
        "volume": LEGACY_VOLUME_LABEL_KEYS,
    }.get(kind)
    if expected_keys is None:
        raise RuntimeError("manfred_legacy_retirement_label_kind_invalid")
    keys = frozenset(
        key for key in labels if key.startswith("com.docker.compose.")
    )
    if (
        keys != expected_keys
        or COMPOSE_CONFIG_HASH.fullmatch(
            labels.get("com.docker.compose.config-hash", "")
        )
        is None
        or labels.get("com.docker.compose.version") != LEGACY_COMPOSE_VERSION
    ):
        raise RuntimeError(f"manfred_legacy_retirement_{kind}_labels_invalid")


def _gateway_binding(container: dict[str, object], port: int) -> None:
    bindings = dict(container.get("port_bindings") or {})
    if set(bindings) != {"18090/tcp"}:
        raise RuntimeError("manfred_legacy_retirement_gateway_port_invalid")
    raw = bindings.get("18090/tcp")
    if not isinstance(raw, list) or len(raw) != 1 or not isinstance(raw[0], dict):
        raise RuntimeError("manfred_legacy_retirement_gateway_port_invalid")
    if (
        str(raw[0].get("HostIp") or "") != "127.0.0.1"
        or str(raw[0].get("HostPort") or "") != str(port)
    ):
        raise RuntimeError("manfred_legacy_retirement_gateway_port_invalid")


def _validate_stack(
    inventory: Inventory,
    *,
    project: str,
    image_id: str,
    image: str,
    revision: str,
    port: int,
    api_container_id: str | None = None,
    gateway_container_id: str | None = None,
    expected_networks: tuple[str, ...] = EXPECTED_NETWORKS,
) -> StackSnapshot:
    expected_container_names = {
        f"{project}-{service}-1" for service in EXPECTED_SERVICES
    }
    expected_network_names = {
        f"{project}_{network}" for network in expected_networks
    }
    expected_volume_names = {f"{project}_{volume}" for volume in EXPECTED_VOLUMES}
    containers = tuple(
        row
        for row in inventory.containers
        if row.get("project") == project
        or str(row.get("name") or "") in expected_container_names
    )
    networks = tuple(
        row
        for row in inventory.networks
        if row.get("project") == project
        or str(row.get("name") or "") in expected_network_names
    )
    volumes = tuple(
        row
        for row in inventory.volumes
        if row.get("project") == project
        or str(row.get("name") or "") in expected_volume_names
    )
    if (
        len(containers) != len(EXPECTED_SERVICES)
        or len(networks) != len(expected_networks)
        or len(volumes) != len(EXPECTED_VOLUMES)
    ):
        raise RuntimeError("manfred_legacy_retirement_stack_shape_invalid")

    by_service: dict[str, dict[str, object]] = {}
    for row in containers:
        service = str(row.get("service") or "")
        labels = {str(key): str(value) for key, value in dict(row.get("labels") or {}).items()}
        if service not in EXPECTED_SERVICES or service in by_service:
            raise RuntimeError("manfred_legacy_retirement_services_invalid")
        _compose_label_allowlist(
            labels,
            CONTAINER_COMPOSE_LABELS,
            {
                "com.docker.compose.project": project,
                "com.docker.compose.service": service,
                "com.docker.compose.container-number": "1",
                "com.docker.compose.oneoff": "False",
            },
        )
        if project == LEGACY_PROJECT:
            _legacy_container_label_contract(labels, service, image_id)
        if (
            row.get("name") != f"{project}-{service}-1"
            or HEX_64.fullmatch(str(row.get("id") or "")) is None
            or row.get("running") is not True
            or row.get("status") != "running"
            or row.get("health") != "healthy"
        ):
            raise RuntimeError("manfred_legacy_retirement_container_invalid")
        expected_attached = (
            {f"{project}_backend", f"{project}_ingress"}
            if service == "gateway"
            else {f"{project}_backend"}
        )
        if set(row.get("networks") or ()) != expected_attached:
            raise RuntimeError("manfred_legacy_retirement_container_networks_invalid")
        if service in {"api", "gateway"}:
            if row.get("image_id") != image_id or row.get("image_ref") != image:
                raise RuntimeError("manfred_legacy_retirement_container_image_invalid")
        elif row.get("image_ref") != EXPECTED_SERVICE_IMAGES[service]:
            raise RuntimeError("manfred_legacy_retirement_service_image_invalid")
        if service == "gateway":
            _gateway_binding(row, port)
        elif dict(row.get("port_bindings") or {}):
            raise RuntimeError("manfred_legacy_retirement_unexpected_port_binding")
        by_service[service] = row
    if set(by_service) != set(EXPECTED_SERVICES):
        raise RuntimeError("manfred_legacy_retirement_services_invalid")
    if api_container_id and by_service["api"]["id"] != api_container_id:
        raise RuntimeError("manfred_legacy_retirement_api_receipt_binding_invalid")
    if gateway_container_id and by_service["gateway"]["id"] != gateway_container_id:
        raise RuntimeError("manfred_legacy_retirement_gateway_receipt_binding_invalid")

    by_network: dict[str, dict[str, object]] = {}
    for row in networks:
        network = str(row.get("network") or "")
        labels = {str(key): str(value) for key, value in dict(row.get("labels") or {}).items()}
        if network not in expected_networks or network in by_network:
            raise RuntimeError("manfred_legacy_retirement_networks_invalid")
        _compose_label_allowlist(
            labels,
            NETWORK_COMPOSE_LABELS,
            {
                "com.docker.compose.project": project,
                "com.docker.compose.network": network,
            },
        )
        if project == LEGACY_PROJECT:
            _legacy_resource_label_contract(labels, kind="network")
        expected_services = (
            EXPECTED_SERVICES
            if network == "backend"
            else ("gateway",)
            if network == "ingress"
            else ()
        )
        expected_ids = {
            str(by_service[service]["id"]) for service in expected_services
        }
        if (
            row.get("name") != f"{project}_{network}"
            or HEX_64.fullmatch(str(row.get("id") or "")) is None
            or row.get("driver") != "bridge"
            or bool(row.get("internal")) != (network in {"backend", "candidate"})
            or row.get("attachable") is not False
            or set(row.get("container_ids") or ()) != expected_ids
        ):
            raise RuntimeError("manfred_legacy_retirement_network_invalid")
        by_network[network] = row

    stack_ids = {str(row["id"]) for row in containers}
    by_volume: dict[str, dict[str, object]] = {}
    for row in volumes:
        volume = str(row.get("volume") or "")
        labels = {str(key): str(value) for key, value in dict(row.get("labels") or {}).items()}
        if volume not in EXPECTED_VOLUMES or volume in by_volume:
            raise RuntimeError("manfred_legacy_retirement_volumes_invalid")
        _compose_label_allowlist(
            labels,
            VOLUME_COMPOSE_LABELS,
            {
                "com.docker.compose.project": project,
                "com.docker.compose.volume": volume,
            },
        )
        if project == LEGACY_PROJECT:
            _legacy_resource_label_contract(labels, kind="volume")
        if (
            row.get("name") != f"{project}_{volume}"
            or row.get("driver") != "local"
            or row.get("scope") != "local"
            or (
                project == LEGACY_PROJECT
                and (
                    not str(row.get("created_at") or "")
                    or not str(row.get("mountpoint") or "").startswith("/")
                    or not isinstance(row.get("options"), dict)
                )
            )
        ):
            raise RuntimeError("manfred_legacy_retirement_volume_invalid")
        expected_service, expected_destination = EXPECTED_VOLUME_USERS[volume]
        users = {
            (str(container.get("id") or ""), str(mount.get("destination") or ""))
            for container in inventory.containers
            for mount in tuple(container.get("mounts") or ())
            if mount.get("type") == "volume"
            and mount.get("name") == row.get("name")
        }
        if users != {
            (str(by_service[expected_service]["id"]), expected_destination)
        }:
            raise RuntimeError("manfred_legacy_retirement_volume_users_invalid")
        if not {identifier for identifier, _destination in users}.issubset(stack_ids):
            raise RuntimeError("manfred_legacy_retirement_volume_external_user")
        by_volume[volume] = row
    stack_volume_mounts = {
        str(mount.get("name") or "")
        for container in containers
        for mount in tuple(container.get("mounts") or ())
        if mount.get("type") == "volume"
    }
    if stack_volume_mounts != expected_volume_names:
        raise RuntimeError("manfred_legacy_retirement_container_volumes_invalid")

    image_row = dict(inventory.images.get(image_id) or {})
    alias_snapshot = _image_alias_snapshot(image_row)
    labels = {str(key): str(value) for key, value in dict(image_row.get("labels") or {}).items()}
    revisions = [
        value.split("=", 1)[1]
        for value in tuple(image_row.get("environment") or ())
        if str(value).startswith("EA_SOURCE_REVISION=")
    ]
    expected_image = (
        f"ea-runtime:manfred-{revision[:8]}"
        if project == LEGACY_PROJECT
        else f"ea-runtime:manfred-{revision}"
    )
    if (
        image_row.get("id") != image_id
        or image not in set(alias_snapshot["repo_tags"])
        or labels.get("org.opencontainers.image.revision") != revision
        or revisions != [revision]
        or image != expected_image
    ):
        raise RuntimeError("manfred_legacy_retirement_image_binding_invalid")

    identity = {
        "project": project,
        "image_id": image_id,
        "image": image,
        "revision": revision,
        "port": port,
        "containers": sorted(containers, key=lambda row: str(row["id"])),
        "networks": sorted(networks, key=lambda row: str(row["id"])),
        "volumes": sorted(volumes, key=lambda row: str(row["name"])),
    }
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return StackSnapshot(
        project=project,
        revision=revision,
        image=image,
        image_id=image_id,
        port=port,
        container_ids=tuple(sorted(str(row["id"]) for row in containers)),
        network_ids=tuple(sorted(str(row["id"]) for row in networks)),
        volume_names=tuple(sorted(str(row["name"]) for row in volumes)),
        digest_sha256=digest,
    )


def _legacy_stack(inventory: Inventory, expected_image_id: str) -> StackSnapshot:
    image_row = dict(inventory.images.get(expected_image_id) or {})
    labels = dict(image_row.get("labels") or {})
    revision = str(labels.get("org.opencontainers.image.revision") or "")
    if HEX_40.fullmatch(revision) is None:
        raise RuntimeError("manfred_legacy_retirement_image_revision_invalid")
    return _validate_stack(
        inventory,
        project=LEGACY_PROJECT,
        image_id=expected_image_id,
        image=f"ea-runtime:manfred-{revision[:8]}",
        revision=revision,
        port=LEGACY_PORT,
        expected_networks=LEGACY_EXPECTED_NETWORKS,
    )


def _newest_managed(
    inventory: Inventory, registry_state: dict[str, object]
) -> tuple[ManagedProof, StackSnapshot]:
    active_projects = {
        str(row.get("project") or "")
        for row in inventory.containers
        if str(row.get("project") or "").startswith(PROJECT_NAME_PREFIX)
        and row.get("project") != LEGACY_PROJECT
    }
    proofs = tuple(registry_state.get("proofs") or ())
    by_project = {proof.project: proof for proof in proofs}
    if not active_projects or not active_projects.issubset(by_project):
        raise RuntimeError("manfred_legacy_retirement_managed_candidate_unproven")
    active = tuple(by_project[project] for project in sorted(active_projects))
    observations = [proof.observed_at for proof in active]
    if len(observations) != len(set(observations)):
        raise RuntimeError("manfred_legacy_retirement_newest_candidate_ambiguous")
    proof = max(active, key=lambda row: row.observed_at)
    snapshot = _validate_stack(
        inventory,
        project=proof.project,
        image_id=proof.image_id,
        image=proof.image,
        revision=proof.revision,
        port=proof.port,
        api_container_id=proof.api_container_id,
        gateway_container_id=proof.gateway_container_id,
    )
    return proof, snapshot


def _assert_http_revision(port: int, revision: str) -> None:
    base = f"http://127.0.0.1:{port}"
    try:
        health = urllib.request.Request(f"{base}/healthz", method="GET")
        with urllib.request.urlopen(health, timeout=10) as response:
            content = response.read(65537)
            if int(response.status or 0) != 200 or len(content) > 65536:
                raise RuntimeError("manfred_legacy_retirement_http_unhealthy")
        memorial = urllib.request.Request(
            f"{base}/memorials/manfred.json", method="GET"
        )
        with urllib.request.urlopen(memorial, timeout=10) as response:
            content = response.read(65537)
            if (
                int(response.status or 0) != 200
                or len(content) > 65536
                or str(response.headers.get("X-EA-Source-Revision") or "")
                != revision
            ):
                raise RuntimeError("manfred_legacy_retirement_http_revision_invalid")
    except (OSError, urllib.error.URLError) as exc:
        raise RuntimeError("manfred_legacy_retirement_http_unreachable") from exc


def _stack_summary(snapshot: StackSnapshot) -> dict[str, object]:
    return {
        "project": snapshot.project,
        "revision": snapshot.revision,
        "image_id": snapshot.image_id,
        "port": snapshot.port,
        "container_ids": list(snapshot.container_ids),
        "network_ids": list(snapshot.network_ids),
        "volume_names": list(snapshot.volume_names),
        "resource_digest_sha256": snapshot.digest_sha256,
    }


def _managed_proof_summary(proof: ManagedProof) -> dict[str, object]:
    return {
        "project": proof.project,
        "observed_at": proof.observed_at.isoformat(),
        "image": proof.image,
        "image_id": proof.image_id,
        "revision": proof.revision,
        "api_container_id": proof.api_container_id,
        "gateway_container_id": proof.gateway_container_id,
        "port": proof.port,
        "receipt_sha256": proof.receipt_sha256,
    }


def _image_policy(
    inventory: Inventory,
    *,
    legacy: StackSnapshot,
    newest: StackSnapshot,
    registry_state: dict[str, object],
    protected_image_ids: frozenset[str],
) -> dict[str, object]:
    image_row = dict(inventory.images.get(legacy.image_id) or {})
    alias_snapshot = _image_alias_snapshot(image_row)
    tags = set(alias_snapshot["repo_tags"])
    repo_digests = tuple(alias_snapshot["repo_digests"])
    expected_tags = {legacy.image}
    references = {
        str(row.get("id") or "")
        for row in inventory.containers
        if row.get("image_id") == legacy.image_id
    }
    live_image_ids = {
        str(row.get("image_id") or "")
        for row in inventory.containers
        if row.get("project") == "ea"
    }
    labels = {str(key): str(value).lower() for key, value in dict(image_row.get("labels") or {}).items()}
    reasons: list[str] = []
    if not references.issubset(set(legacy.container_ids)):
        reasons.append("nonlegacy_container_reference")
    if tags != expected_tags:
        reasons.append("not_sole_expected_tag")
    if repo_digests:
        reasons.append("repo_digest_aliases")
    if legacy.image_id in live_image_ids:
        reasons.append("live_ea_image")
    if legacy.image_id == newest.image_id:
        reasons.append("newest_managed_candidate_image")
    if legacy.image_id in set(registry_state.get("registered_image_ids") or ()):
        reasons.append("registered_candidate_image")
    if legacy.image_id in set(registry_state.get("pending_image_ids") or ()):
        reasons.append("pending_candidate_image")
    if legacy.image_id in protected_image_ids or any(
        labels.get(key) in {"1", "true", "yes"} for key in PROTECTED_IMAGE_LABELS
    ):
        reasons.append("protected_image")
    return {
        "eligible": not reasons,
        "expected_tag": legacy.image,
        "observed_tags": sorted(tags),
        "observed_repo_digests": list(repo_digests),
        "reference_container_ids": sorted(references),
        "preserve_reasons": sorted(set(reasons)),
    }


def _assert_target_absent(inventory: Inventory) -> None:
    expected_containers = {
        f"{LEGACY_PROJECT}-{service}-1" for service in EXPECTED_SERVICES
    }
    expected_networks = {
        f"{LEGACY_PROJECT}_{network}" for network in LEGACY_EXPECTED_NETWORKS
    }
    expected_volumes = {
        f"{LEGACY_PROJECT}_{volume}" for volume in EXPECTED_VOLUMES
    }
    if (
        any(
            row.get("project") == LEGACY_PROJECT
            or row.get("name") in expected_containers
            for row in inventory.containers
        )
        or any(
            row.get("project") == LEGACY_PROJECT
            or row.get("name") in expected_networks
            for row in inventory.networks
        )
        or any(
            row.get("project") == LEGACY_PROJECT
            or row.get("name") in expected_volumes
            for row in inventory.volumes
        )
    ):
        raise RuntimeError("manfred_legacy_retirement_target_resources_remain")


def _assert_port_free() -> None:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("127.0.0.1", LEGACY_PORT))
    except OSError as exc:
        raise RuntimeError("manfred_legacy_retirement_port_remains_bound") from exc
    finally:
        probe.close()


def _json_digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _volume_users(inventory: Inventory, name: str) -> list[dict[str, str]]:
    return sorted(
        (
            {
                "container_id": str(container.get("id") or ""),
                "destination": str(mount.get("destination") or ""),
            }
            for container in inventory.containers
            for mount in tuple(container.get("mounts") or ())
            if mount.get("type") == "volume" and mount.get("name") == name
        ),
        key=lambda row: (row["container_id"], row["destination"]),
    )


def _resume_contract(
    inventory: Inventory,
    snapshot: StackSnapshot,
    *,
    image_policy: dict[str, object],
    protected_image_ids: frozenset[str],
) -> dict[str, object]:
    containers: list[dict[str, object]] = []
    for row in sorted(
        (row for row in inventory.containers if row.get("id") in snapshot.container_ids),
        key=lambda value: str(value["id"]),
    ):
        containers.append(
            {
                "id": str(row["id"]),
                "name": str(row["name"]),
                "service": str(row["service"]),
                "binding_sha256": _json_digest(row),
            }
        )
    networks: list[dict[str, object]] = []
    for row in sorted(
        (row for row in inventory.networks if row.get("id") in snapshot.network_ids),
        key=lambda value: str(value["id"]),
    ):
        static = dict(row)
        original_container_ids = list(static.pop("container_ids", ()))
        networks.append(
            {
                "id": str(row["id"]),
                "name": str(row["name"]),
                "network": str(row["network"]),
                "binding_sha256": _json_digest(static),
                "original_container_ids": sorted(
                    str(value) for value in original_container_ids
                ),
            }
        )
    volumes: list[dict[str, object]] = []
    for row in sorted(
        (row for row in inventory.volumes if row.get("name") in snapshot.volume_names),
        key=lambda value: str(value["name"]),
    ):
        volumes.append(
            {
                "name": str(row["name"]),
                "volume": str(row["volume"]),
                "binding_sha256": _json_digest(row),
                "original_users": _volume_users(inventory, str(row["name"])),
            }
        )
    image_row = dict(inventory.images.get(snapshot.image_id) or {})
    aliases = _image_alias_snapshot(image_row)
    image_authorized = image_policy.get("eligible") is True
    actions: list[dict[str, str]] = [
        *({"kind": "container", "id": str(row["id"])} for row in containers),
        *({"kind": "network", "id": str(row["id"])} for row in networks),
        *({"kind": "volume", "name": str(row["name"])} for row in volumes),
    ]
    if image_authorized:
        actions.append({"kind": "image", "id": snapshot.image_id})
    return {
        "version": RESUME_CONTRACT_VERSION,
        "target": {**_stack_summary(snapshot), "image": snapshot.image},
        "protected_image_ids": sorted(protected_image_ids),
        "containers": containers,
        "networks": networks,
        "volumes": volumes,
        "image": {
            "id": snapshot.image_id,
            "binding_sha256": _json_digest(image_row),
            "aliases": aliases,
            "removal_authorized": image_authorized,
        },
        "actions": actions,
    }


def _snapshot_from_resume_contract(
    contract: dict[str, object], expected_image_id: str
) -> StackSnapshot:
    try:
        target = dict(contract.get("target") or {})
        project = str(target.get("project") or "")
        revision = str(target.get("revision") or "")
        image = str(target.get("image") or "")
        image_id = str(target.get("image_id") or "")
        port = int(target.get("port"))
        container_ids = tuple(str(value) for value in target.get("container_ids") or ())
        network_ids = tuple(str(value) for value in target.get("network_ids") or ())
        volume_names = tuple(str(value) for value in target.get("volume_names") or ())
        digest = str(target.get("resource_digest_sha256") or "")
    except (TypeError, ValueError) as exc:
        raise RuntimeError("manfred_legacy_retirement_resume_contract_invalid") from exc
    if (
        contract.get("version") != RESUME_CONTRACT_VERSION
        or project != LEGACY_PROJECT
        or image_id != expected_image_id
        or HEX_40.fullmatch(revision) is None
        or image != f"ea-runtime:manfred-{revision[:8]}"
        or port != LEGACY_PORT
        or len(container_ids) != len(EXPECTED_SERVICES)
        or len(set(container_ids)) != len(container_ids)
        or any(HEX_64.fullmatch(value) is None for value in container_ids)
        or len(network_ids) != len(LEGACY_EXPECTED_NETWORKS)
        or len(set(network_ids)) != len(network_ids)
        or any(HEX_64.fullmatch(value) is None for value in network_ids)
        or set(volume_names)
        != {f"{LEGACY_PROJECT}_{value}" for value in EXPECTED_VOLUMES}
        or HEX_64.fullmatch(digest) is None
    ):
        raise RuntimeError("manfred_legacy_retirement_resume_contract_invalid")
    return StackSnapshot(
        project=project,
        revision=revision,
        image=image,
        image_id=image_id,
        port=port,
        container_ids=container_ids,
        network_ids=network_ids,
        volume_names=volume_names,
        digest_sha256=digest,
    )


def _validate_resume_contract(
    contract: dict[str, object],
    *,
    expected_image_id: str,
    protected_image_ids: frozenset[str],
) -> StackSnapshot:
    snapshot = _snapshot_from_resume_contract(contract, expected_image_id)
    try:
        containers = [dict(row) for row in list(contract.get("containers") or [])]
        networks = [dict(row) for row in list(contract.get("networks") or [])]
        volumes = [dict(row) for row in list(contract.get("volumes") or [])]
        image = dict(contract.get("image") or {})
        actions = [dict(row) for row in list(contract.get("actions") or [])]
    except (TypeError, ValueError) as exc:
        raise RuntimeError("manfred_legacy_retirement_resume_contract_invalid") from exc
    container_ids = [str(row.get("id") or "") for row in containers]
    network_ids = [str(row.get("id") or "") for row in networks]
    volume_names = [str(row.get("name") or "") for row in volumes]
    services = {str(row.get("service") or "") for row in containers}
    network_names = {str(row.get("network") or "") for row in networks}
    volume_keys = {str(row.get("volume") or "") for row in volumes}
    expected_actions: list[dict[str, str]] = [
        *({"kind": "container", "id": value} for value in container_ids),
        *({"kind": "network", "id": value} for value in network_ids),
        *({"kind": "volume", "name": value} for value in volume_names),
    ]
    if image.get("removal_authorized") is True:
        expected_actions.append({"kind": "image", "id": expected_image_id})
    hashes = [
        str(row.get("binding_sha256") or "")
        for row in [*containers, *networks, *volumes, image]
    ]
    if (
        container_ids != list(snapshot.container_ids)
        or network_ids != list(snapshot.network_ids)
        or volume_names != list(snapshot.volume_names)
        or services != set(EXPECTED_SERVICES)
        or network_names != set(LEGACY_EXPECTED_NETWORKS)
        or volume_keys != set(EXPECTED_VOLUMES)
        or any(
            row.get("name") != f"{LEGACY_PROJECT}-{row.get('service')}-1"
            for row in containers
        )
        or any(
            row.get("name") != f"{LEGACY_PROJECT}_{row.get('network')}"
            for row in networks
        )
        or image.get("id") != expected_image_id
        or any(HEX_64.fullmatch(value) is None for value in hashes)
        or actions != expected_actions
        or contract.get("protected_image_ids") != sorted(protected_image_ids)
    ):
        raise RuntimeError("manfred_legacy_retirement_resume_contract_invalid")
    by_service = {
        str(row["service"]): str(row["id"]) for row in containers
    }
    for row in networks:
        network = str(row["network"])
        expected_services = (
            EXPECTED_SERVICES
            if network == "backend"
            else ("gateway",)
            if network == "ingress"
            else ()
        )
        if row.get("original_container_ids") != sorted(
            by_service[service] for service in expected_services
        ):
            raise RuntimeError("manfred_legacy_retirement_resume_contract_invalid")
    for row in volumes:
        service, destination = EXPECTED_VOLUME_USERS[str(row["volume"])]
        if row.get("original_users") != [
            {"container_id": by_service[service], "destination": destination}
        ]:
            raise RuntimeError("manfred_legacy_retirement_resume_contract_invalid")
    aliases = dict(image.get("aliases") or {})
    if (
        aliases.get("image_id") != expected_image_id
        or not isinstance(aliases.get("repo_tags"), list)
        or not isinstance(aliases.get("repo_digests"), list)
    ):
        raise RuntimeError("manfred_legacy_retirement_resume_contract_invalid")
    return snapshot


def _reconcile_resume_contract(
    inventory: Inventory, contract: dict[str, object]
) -> list[dict[str, str]]:
    containers = [dict(row) for row in list(contract["containers"])]
    networks = [dict(row) for row in list(contract["networks"])]
    volumes = [dict(row) for row in list(contract["volumes"])]
    image = dict(contract["image"])
    actions = [dict(row) for row in list(contract["actions"])]

    expected_container_ids = {str(row["id"]) for row in containers}
    expected_container_names = {str(row["name"]) for row in containers}
    target_containers = [
        row
        for row in inventory.containers
        if row.get("project") == LEGACY_PROJECT
        or str(row.get("name") or "") in expected_container_names
    ]
    if any(str(row.get("id") or "") not in expected_container_ids for row in target_containers):
        raise RuntimeError("manfred_legacy_retirement_resume_container_replaced")
    actual_containers = {str(row["id"]): row for row in target_containers}
    surviving_container_ids: set[str] = set()
    for expected in containers:
        identifier = str(expected["id"])
        current = actual_containers.get(identifier)
        if current is not None:
            if _json_digest(current) != expected["binding_sha256"]:
                raise RuntimeError("manfred_legacy_retirement_resume_container_drift")
            surviving_container_ids.add(identifier)

    expected_network_ids = {str(row["id"]) for row in networks}
    expected_network_names = {str(row["name"]) for row in networks}
    target_networks = [
        row
        for row in inventory.networks
        if row.get("project") == LEGACY_PROJECT
        or str(row.get("name") or "") in expected_network_names
    ]
    if any(str(row.get("id") or "") not in expected_network_ids for row in target_networks):
        raise RuntimeError("manfred_legacy_retirement_resume_network_replaced")
    actual_networks = {str(row["id"]): row for row in target_networks}
    for expected in networks:
        current = actual_networks.get(str(expected["id"]))
        if current is None:
            continue
        static = dict(current)
        current_container_ids = sorted(
            str(value) for value in static.pop("container_ids", ())
        )
        expected_container_ids = sorted(
            str(value)
            for value in list(expected["original_container_ids"])
            if str(value) in surviving_container_ids
        )
        if (
            _json_digest(static) != expected["binding_sha256"]
            or current_container_ids != expected_container_ids
        ):
            raise RuntimeError("manfred_legacy_retirement_resume_network_drift")

    expected_volume_names = {str(row["name"]) for row in volumes}
    target_volumes = [
        row
        for row in inventory.volumes
        if row.get("project") == LEGACY_PROJECT
        or str(row.get("name") or "") in expected_volume_names
    ]
    if any(str(row.get("name") or "") not in expected_volume_names for row in target_volumes):
        raise RuntimeError("manfred_legacy_retirement_resume_volume_replaced")
    actual_volumes = {str(row["name"]): row for row in target_volumes}
    for expected in volumes:
        name = str(expected["name"])
        current = actual_volumes.get(name)
        if current is None:
            continue
        expected_users = [
            dict(row)
            for row in list(expected["original_users"])
            if str(dict(row).get("container_id") or "") in surviving_container_ids
        ]
        if (
            _json_digest(current) != expected["binding_sha256"]
            or _volume_users(inventory, name) != expected_users
        ):
            raise RuntimeError("manfred_legacy_retirement_resume_volume_drift")

    current_image = inventory.images.get(str(image["id"]))
    if current_image is not None and _json_digest(current_image) != image["binding_sha256"]:
        raise RuntimeError("manfred_legacy_retirement_resume_image_drift")
    if current_image is None and image.get("removal_authorized") is not True:
        raise RuntimeError("manfred_legacy_retirement_resume_image_unexpectedly_absent")

    presence: list[bool] = []
    for action in actions:
        kind = str(action.get("kind") or "")
        if kind == "container":
            presence.append(str(action.get("id") or "") in actual_containers)
        elif kind == "network":
            presence.append(str(action.get("id") or "") in actual_networks)
        elif kind == "volume":
            presence.append(str(action.get("name") or "") in actual_volumes)
        elif kind == "image":
            presence.append(current_image is not None)
        else:  # pragma: no cover - contract validation rejects this
            raise RuntimeError("manfred_legacy_retirement_resume_contract_invalid")
    seen_present = False
    completed_count = 0
    for is_present in presence:
        if is_present:
            seen_present = True
        elif seen_present:
            raise RuntimeError("manfred_legacy_retirement_resume_nonsequential_drift")
        else:
            completed_count += 1
    return [
        {str(key): str(value) for key, value in action.items()}
        for action in actions[:completed_count]
    ]


def _remove_stack(
    snapshot: StackSnapshot, actions: list[dict[str, str]] | None = None
) -> list[dict[str, str]]:
    actions = actions if actions is not None else []
    for identifier in snapshot.container_ids:
        _run(["docker", "container", "rm", "--force", identifier], timeout=120)
        actions.append({"kind": "container", "id": identifier})
    for identifier in snapshot.network_ids:
        _run(["docker", "network", "rm", identifier], timeout=60)
        actions.append({"kind": "network", "id": identifier})
    for name in snapshot.volume_names:
        _run(["docker", "volume", "rm", name], timeout=60)
        actions.append({"kind": "volume", "name": name})
    return actions


def _remove_image_if_still_eligible(
    expected_image_id: str,
    *,
    planned_policy: dict[str, object],
) -> dict[str, object]:
    if planned_policy.get("eligible") is not True:
        return {
            "removed": False,
            "preserve_reasons": list(planned_policy.get("preserve_reasons") or []),
        }
    references = _listed(
        [
            "docker",
            "container",
            "ls",
            "--all",
            "--quiet",
            "--filter",
            f"ancestor={expected_image_id}",
        ]
    )
    if references:
        return {"removed": False, "preserve_reasons": ["referenced_at_apply"]}
    current_aliases = _inspect_image_alias_snapshot(expected_image_id)
    if current_aliases["repo_digests"]:
        return {
            "removed": False,
            "preserve_reasons": ["repo_digest_aliases_at_apply"],
        }
    if (
        current_aliases["repo_tags"]
        != list(planned_policy.get("observed_tags") or [])
        or current_aliases["repo_digests"]
        != list(planned_policy.get("observed_repo_digests") or [])
    ):
        return {
            "removed": False,
            "preserve_reasons": ["image_alias_changed_at_apply"],
        }
    _run(["docker", "image", "rm", expected_image_id], timeout=120)
    if expected_image_id in _existing_image_ids():
        raise RuntimeError("manfred_legacy_retirement_image_remains")
    return {"removed": True, "preserve_reasons": []}


def _automatic_receipt_path() -> Path:
    directory = operator_state_root() / "manfred-legacy-candidate-retirement-receipts"
    try:
        directory.mkdir(parents=True, mode=0o700, exist_ok=True)
        resolved = directory.resolve(strict=True)
        metadata = resolved.stat()
    except OSError as exc:
        raise RuntimeError("manfred_legacy_retirement_output_path_invalid") from exc
    if (
        resolved != directory.absolute()
        or metadata.st_uid != os.getuid()
        or not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) & 0o022
    ):
        raise RuntimeError("manfred_legacy_retirement_output_path_invalid")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return resolved / f"legacy-retirement-{stamp}-{os.getpid()}-{secrets.token_hex(4)}.json"


def _pre_receipt_path(post_path: Path) -> Path:
    name = post_path.name
    stem = name[:-5] if name.endswith(".json") else name
    return post_path.with_name(f"{stem}.pre.json")


def _inventory_for(
    expected_image_id: str, registry_state: dict[str, object]
) -> Inventory:
    existing = _existing_image_ids()
    desired = {
        expected_image_id,
        *(proof.image_id for proof in tuple(registry_state.get("proofs") or ())),
    }
    return _discover_inventory(desired.intersection(existing))


def _validate_resume_pre_receipt(
    payload: dict[str, object],
    *,
    expected_image_id: str,
    protected_image_ids: frozenset[str],
) -> tuple[dict[str, object], StackSnapshot]:
    try:
        contract = dict(payload.get("resume_contract") or {})
        image_policy = dict(payload.get("image_policy") or {})
        target = dict(payload.get("target") or {})
        newest = dict(payload.get("newest_managed_candidate_before") or {})
        newest_proof = dict(payload.get("newest_managed_proof_before") or {})
        live = dict(payload.get("live_ea_before") or {})
        authorized = dict(payload.get("mutations_authorized") or {})
    except (TypeError, ValueError) as exc:
        raise RuntimeError("manfred_legacy_retirement_resume_receipt_invalid") from exc
    snapshot = _validate_resume_contract(
        contract,
        expected_image_id=expected_image_id,
        protected_image_ids=protected_image_ids,
    )
    contract_image = dict(contract["image"])
    aliases = dict(contract_image.get("aliases") or {})
    expected_authorized = {
        "container_ids": list(snapshot.container_ids),
        "network_ids": list(snapshot.network_ids),
        "volume_names": list(snapshot.volume_names),
        "image_id": (
            expected_image_id
            if contract_image.get("removal_authorized") is True
            else None
        ),
    }
    if (
        payload.get("schema") != RECEIPT_SCHEMA
        or payload.get("status") != "authorized"
        or payload.get("action") != "retirement_intent"
        or payload.get("mode") != "apply"
        or payload.get("apply_requested") is not True
        or payload.get("manual_only") is not True
        or payload.get("dry_run_default") is not True
        or payload.get("automatic_retirement_authorized") is not False
        or payload.get("secrets_included") is not False
        or payload.get("env_files_read") is not False
        or payload.get("live_ea_mutation_requested") is not False
        or payload.get("managed_candidate_mutation_requested") is not False
        or payload.get("project") != LEGACY_PROJECT
        or payload.get("expected_image_id") != expected_image_id
        or target != _stack_summary(snapshot)
        or not newest
        or not newest_proof
        or not live
        or HEX_64.fullmatch(str(payload.get("registry_digest_sha256") or ""))
        is None
        or payload.get("mutations_performed") != 0
        or authorized != expected_authorized
        or image_policy.get("expected_tag") != snapshot.image
        or image_policy.get("observed_tags") != aliases.get("repo_tags")
        or image_policy.get("observed_repo_digests")
        != aliases.get("repo_digests")
        or image_policy.get("eligible")
        is not contract_image.get("removal_authorized")
    ):
        raise RuntimeError("manfred_legacy_retirement_resume_receipt_invalid")
    return contract, snapshot


def _execute_remaining_stack_actions(
    contract: dict[str, object],
    reconciled_actions: list[dict[str, str]],
    performed_actions: list[dict[str, str]],
) -> None:
    actions = [dict(row) for row in list(contract["actions"])]
    stack_count = (
        len(list(contract["containers"]))
        + len(list(contract["networks"]))
        + len(list(contract["volumes"]))
    )
    for raw_action in actions[len(reconciled_actions) : stack_count]:
        action = {str(key): str(value) for key, value in raw_action.items()}
        if action["kind"] == "container":
            _run(
                ["docker", "container", "rm", "--force", action["id"]],
                timeout=120,
            )
        elif action["kind"] == "network":
            _run(["docker", "network", "rm", action["id"]], timeout=60)
        elif action["kind"] == "volume":
            _run(["docker", "volume", "rm", action["name"]], timeout=60)
        else:  # pragma: no cover - validated contract
            raise RuntimeError("manfred_legacy_retirement_resume_contract_invalid")
        performed_actions.append(action)


def _resume_image_policy(
    inventory: Inventory,
    *,
    legacy: StackSnapshot,
    newest: StackSnapshot,
    registry_state: dict[str, object],
    protected_image_ids: frozenset[str],
    planned_policy: dict[str, object],
) -> dict[str, object]:
    if legacy.image_id not in inventory.images:
        return planned_policy
    observed = _image_policy(
        inventory,
        legacy=legacy,
        newest=newest,
        registry_state=registry_state,
        protected_image_ids=protected_image_ids,
    )
    expected = dict(planned_policy)
    expected["reference_container_ids"] = sorted(
        str(row.get("id") or "")
        for row in inventory.containers
        if row.get("image_id") == legacy.image_id
        and str(row.get("id") or "") in set(legacy.container_ids)
    )
    if observed != expected:
        raise RuntimeError("manfred_legacy_retirement_resume_image_policy_changed")
    return observed


def retire_legacy_candidate(
    *,
    project: str,
    expected_image_id: str,
    output_receipt: Path,
    apply: bool,
    registry_path: Path | None = None,
    protected_image_ids: frozenset[str] = frozenset(),
    resume_pre_receipt: Path | None = None,
) -> dict[str, object]:
    if project != LEGACY_PROJECT:
        raise RuntimeError("manfred_legacy_retirement_project_forbidden")
    if IMAGE_ID.fullmatch(expected_image_id) is None or any(
        IMAGE_ID.fullmatch(value) is None for value in protected_image_ids
    ):
        raise RuntimeError("manfred_legacy_retirement_image_id_invalid")
    post_path = _assert_new_receipt_path(output_receipt)
    resume_requested = resume_pre_receipt is not None
    pre_path = (
        Path(resume_pre_receipt).expanduser()
        if resume_requested
        else _assert_new_receipt_path(_pre_receipt_path(post_path))
    )
    registry_path = Path(registry_path or default_registry_path())
    base = {
        "schema": RECEIPT_SCHEMA,
        "observed_at": _utc_now(),
        "project": LEGACY_PROJECT,
        "expected_image_id": expected_image_id,
        "mode": (
            "resume_apply"
            if resume_requested and apply
            else "resume_dry_run"
            if resume_requested
            else "apply"
            if apply
            else "dry_run"
        ),
        "apply_requested": apply,
        "resume_requested": resume_requested,
        "dry_run_default": True,
        "manual_only": True,
        "automatic_retirement_authorized": False,
        "secrets_included": False,
        "env_files_read": False,
        "live_ea_mutation_requested": False,
        "managed_candidate_mutation_requested": False,
    }
    pre_payload: dict[str, object] | None = None
    pre_digest: str | None = None
    pre_written = False
    pre_available = resume_requested
    performed_actions: list[dict[str, str]] = []
    reconciled_actions: list[dict[str, str]] = []
    try:
        with hold_candidate_fleet_lock() as fleet_lock:
            if fleet_lock is None:  # pragma: no cover - raising mode
                raise RuntimeError("manfred_candidate_fleet_lock_held")
            with _hold_port_lock(LEGACY_PORT) as port_lock:
                contract: dict[str, object] | None = None
                if resume_requested:
                    pre_payload, _file_digest = _read_private_json(pre_path)
                    pre_digest = _json_digest(pre_payload)
                    contract, legacy_before = _validate_resume_pre_receipt(
                        pre_payload,
                        expected_image_id=expected_image_id,
                        protected_image_ids=protected_image_ids,
                    )
                    image_policy = dict(pre_payload["image_policy"])
                    live_before = dict(pre_payload["live_ea_before"])
                    newest_before_summary = dict(
                        pre_payload["newest_managed_candidate_before"]
                    )
                    newest_proof_before_summary = dict(
                        pre_payload["newest_managed_proof_before"]
                    )
                    registry_digest_before = str(
                        pre_payload["registry_digest_sha256"]
                    )
                else:
                    registry_planned = _registry_state(registry_path)
                    inventory_planned = _inventory_for(
                        expected_image_id, registry_planned
                    )
                    if expected_image_id not in inventory_planned.images:
                        raise RuntimeError(
                            "manfred_legacy_retirement_expected_image_missing"
                        )
                    live_before = _live_fingerprint(inventory_planned)
                    legacy_before = _legacy_stack(
                        inventory_planned, expected_image_id
                    )
                    newest_proof, newest_before = _newest_managed(
                        inventory_planned, registry_planned
                    )
                    _assert_http_revision(LEGACY_PORT, legacy_before.revision)
                    _assert_http_revision(newest_proof.port, newest_proof.revision)
                    image_policy = _image_policy(
                        inventory_planned,
                        legacy=legacy_before,
                        newest=newest_before,
                        registry_state=registry_planned,
                        protected_image_ids=protected_image_ids,
                    )
                    newest_before_summary = _stack_summary(newest_before)
                    newest_proof_before_summary = _managed_proof_summary(
                        newest_proof
                    )
                    registry_digest_before = str(
                        registry_planned["digest_sha256"]
                    )
                    if apply:
                        contract = _resume_contract(
                            inventory_planned,
                            legacy_before,
                            image_policy=image_policy,
                            protected_image_ids=protected_image_ids,
                        )
                    pre_payload = {
                        **base,
                        "mode": "apply" if apply else "dry_run",
                        "resume_requested": False,
                        "status": "authorized" if apply else "planned",
                        "action": "retirement_intent" if apply else "dry_run_plan",
                        "fleet_lock": fleet_lock,
                        "port_lock": port_lock,
                        "target": _stack_summary(legacy_before),
                        "newest_managed_candidate_before": newest_before_summary,
                        "newest_managed_proof_before": newest_proof_before_summary,
                        "live_ea_before": live_before,
                        "registry_digest_sha256": registry_digest_before,
                        "image_policy": image_policy,
                        "resume_contract": contract,
                        "mutations_authorized": (
                            {
                                "container_ids": list(legacy_before.container_ids),
                                "network_ids": list(legacy_before.network_ids),
                                "volume_names": list(legacy_before.volume_names),
                                "image_id": (
                                    expected_image_id
                                    if image_policy["eligible"] is True
                                    else None
                                ),
                            }
                            if apply
                            else {
                                "container_ids": [],
                                "network_ids": [],
                                "volume_names": [],
                                "image_id": None,
                            }
                        ),
                        "mutations_performed": 0,
                    }
                    _atomic_receipt(pre_path, pre_payload)
                    pre_written = True
                    pre_available = True
                    pre_digest = _json_digest(pre_payload)

                # The inventory used to plan the intent is never itself used to
                # authorize deletion.  Re-read every protected state under both
                # locks immediately before the first possible mutation.
                registry_before = _registry_state(registry_path)
                if registry_before["digest_sha256"] != registry_digest_before:
                    raise RuntimeError("manfred_legacy_retirement_registry_changed")
                inventory_before = _inventory_for(
                    expected_image_id, registry_before
                )
                if _live_fingerprint(inventory_before) != live_before:
                    raise RuntimeError("manfred_legacy_retirement_live_ea_changed")
                newest_proof, newest_before = _newest_managed(
                    inventory_before, registry_before
                )
                if (
                    _managed_proof_summary(newest_proof)
                    != newest_proof_before_summary
                    or _stack_summary(newest_before) != newest_before_summary
                ):
                    raise RuntimeError(
                        "manfred_legacy_retirement_newest_candidate_changed"
                    )
                _assert_http_revision(newest_proof.port, newest_proof.revision)

                if contract is not None:
                    reconciled_actions = _reconcile_resume_contract(
                        inventory_before, contract
                    )
                    stack_action_count = (
                        len(list(contract["containers"]))
                        + len(list(contract["networks"]))
                        + len(list(contract["volumes"]))
                    )
                    if not resume_requested and reconciled_actions:
                        raise RuntimeError(
                            "manfred_legacy_retirement_target_changed_before_apply"
                        )
                    if not reconciled_actions:
                        observed_legacy = _legacy_stack(
                            inventory_before, expected_image_id
                        )
                        if observed_legacy != legacy_before:
                            raise RuntimeError(
                                "manfred_legacy_retirement_target_changed_before_apply"
                            )
                        _assert_http_revision(
                            LEGACY_PORT, observed_legacy.revision
                        )
                    image_policy_at_apply = _resume_image_policy(
                        inventory_before,
                        legacy=legacy_before,
                        newest=newest_before,
                        registry_state=registry_before,
                        protected_image_ids=protected_image_ids,
                        planned_policy=image_policy,
                    )
                    if (
                        not resume_requested
                        and image_policy_at_apply != image_policy
                    ):
                        raise RuntimeError(
                            "manfred_legacy_retirement_image_changed_before_apply"
                        )
                else:
                    stack_action_count = 0
                    observed_legacy = _legacy_stack(
                        inventory_before, expected_image_id
                    )
                    if observed_legacy != legacy_before:
                        raise RuntimeError(
                            "manfred_legacy_retirement_target_changed_during_dry_run"
                        )
                    image_policy_at_apply = _image_policy(
                        inventory_before,
                        legacy=observed_legacy,
                        newest=newest_before,
                        registry_state=registry_before,
                        protected_image_ids=protected_image_ids,
                    )
                    if image_policy_at_apply != image_policy:
                        raise RuntimeError(
                            "manfred_legacy_retirement_image_changed_during_dry_run"
                        )

                image_result: dict[str, object] = {
                    "removed": False,
                    "preserve_reasons": list(image_policy["preserve_reasons"]),
                }
                if apply:
                    if contract is None:  # pragma: no cover - construction invariant
                        raise RuntimeError(
                            "manfred_legacy_retirement_resume_contract_invalid"
                        )
                    _execute_remaining_stack_actions(
                        contract, reconciled_actions, performed_actions
                    )
                    intermediate_registry = _registry_state(registry_path)
                    if (
                        intermediate_registry["digest_sha256"]
                        != registry_before["digest_sha256"]
                    ):
                        raise RuntimeError("manfred_legacy_retirement_registry_changed")
                    intermediate = _inventory_for(
                        expected_image_id, intermediate_registry
                    )
                    _assert_target_absent(intermediate)
                    _assert_port_free()
                    if _live_fingerprint(intermediate) != live_before:
                        raise RuntimeError("manfred_legacy_retirement_live_ea_changed")
                    observed_proof, observed_newest = _newest_managed(
                        intermediate, intermediate_registry
                    )
                    if (
                        observed_proof != newest_proof
                        or observed_newest != newest_before
                    ):
                        raise RuntimeError(
                            "manfred_legacy_retirement_newest_candidate_changed"
                        )
                    _assert_http_revision(observed_proof.port, observed_proof.revision)
                    if expected_image_id not in intermediate.images:
                        if dict(contract["image"]).get("removal_authorized") is not True:
                            raise RuntimeError(
                                "manfred_legacy_retirement_image_changed_before_apply"
                            )
                        image_result = {
                            "removed": True,
                            "preserve_reasons": [],
                            "reconciled_as_already_absent": True,
                        }
                    else:
                        image_policy_at_apply = _image_policy(
                            intermediate,
                            legacy=legacy_before,
                            newest=observed_newest,
                            registry_state=intermediate_registry,
                            protected_image_ids=protected_image_ids,
                        )
                        image_result = _remove_image_if_still_eligible(
                            expected_image_id,
                            planned_policy=(
                                image_policy_at_apply
                                if image_policy["eligible"] is True
                                else image_policy
                            ),
                        )
                        if image_result.get("removed") is True:
                            performed_actions.append(
                                {"kind": "image", "id": expected_image_id}
                            )

                registry_after = _registry_state(registry_path)
                if registry_after["digest_sha256"] != registry_before["digest_sha256"]:
                    raise RuntimeError("manfred_legacy_retirement_registry_changed")
                inventory_after = _inventory_for(expected_image_id, registry_after)
                live_after = _live_fingerprint(inventory_after)
                if live_after != live_before:
                    raise RuntimeError("manfred_legacy_retirement_live_ea_changed")
                observed_proof, newest_after = _newest_managed(
                    inventory_after, registry_after
                )
                if observed_proof != newest_proof or newest_after != newest_before:
                    raise RuntimeError(
                        "manfred_legacy_retirement_newest_candidate_changed"
                    )
                _assert_http_revision(observed_proof.port, observed_proof.revision)
                if apply:
                    _assert_target_absent(inventory_after)
                    _assert_port_free()
                    if contract is not None:
                        final_reconciled = _reconcile_resume_contract(
                            inventory_after, contract
                        )
                        if len(final_reconciled) < stack_action_count:
                            raise RuntimeError(
                                "manfred_legacy_retirement_target_resources_remain"
                            )
                elif not resume_requested:
                    observed_legacy = _legacy_stack(
                        inventory_after, expected_image_id
                    )
                    if observed_legacy != legacy_before:
                        raise RuntimeError(
                            "manfred_legacy_retirement_target_changed_during_dry_run"
                        )
                    observed_policy = _image_policy(
                        inventory_after,
                        legacy=observed_legacy,
                        newest=newest_after,
                        registry_state=registry_after,
                        protected_image_ids=protected_image_ids,
                    )
                    if observed_policy != image_policy:
                        raise RuntimeError(
                            "manfred_legacy_retirement_image_changed_during_dry_run"
                        )
                    image_policy_at_apply = observed_policy
                    _assert_http_revision(LEGACY_PORT, observed_legacy.revision)
                elif contract is not None:
                    final_reconciled = _reconcile_resume_contract(
                        inventory_after, contract
                    )
                    if final_reconciled != reconciled_actions:
                        raise RuntimeError(
                            "manfred_legacy_retirement_target_changed_during_dry_run"
                        )

                post = {
                    **base,
                    "observed_at": _utc_now(),
                    "status": "pass",
                    "action": (
                        "resumed"
                        if resume_requested and apply
                        else "resume_dry_run_complete"
                        if resume_requested
                        else "applied"
                        if apply
                        else "dry_run_complete"
                    ),
                    "pre_receipt": {
                        "filename": pre_path.name,
                        "payload_sha256": pre_digest,
                    },
                    "target_before": _stack_summary(legacy_before),
                    "target_absent_after": apply,
                    "port_18090_free_after": apply,
                    "image_policy": image_policy,
                    "image_policy_at_apply": image_policy_at_apply,
                    "image_result": image_result,
                    "execution": {
                        "actions": performed_actions,
                        "reconciled_actions": reconciled_actions,
                    },
                    "live_ea_after": live_after,
                    "live_ea_unchanged": True,
                    "newest_managed_candidate_after": _stack_summary(newest_after),
                    "newest_managed_candidate_unchanged": True,
                    "registry_unchanged": True,
                    "mutations_performed": len(performed_actions),
                }
                _atomic_receipt(post_path, post)
                return post
    except BaseException as exc:
        failure = {
            **base,
            "observed_at": _utc_now(),
            "status": "fail",
            "error": _safe_error(exc),
            "pre_receipt_created": pre_available or os.path.lexists(pre_path),
            "pre_receipt": (
                {
                    "filename": pre_path.name,
                    "payload_sha256": pre_digest,
                }
                if pre_available and pre_digest
                else None
            ),
            "completed_actions": performed_actions,
            "reconciled_actions": reconciled_actions,
            "mutations_performed": len(performed_actions),
            "additional_mutations_unknown": pre_available and apply,
        }
        with contextlib.suppress(BaseException):
            _atomic_receipt(post_path, failure)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Explicitly plan or retire the exact unbound ea-manfred-candidate legacy stack. "
            "This command is never used by automatic candidate retention."
        )
    )
    parser.add_argument(
        "--project",
        required=True,
        choices=[LEGACY_PROJECT],
        help="Required exact legacy Compose project; no other project is accepted.",
    )
    parser.add_argument(
        "--expected-image-id",
        required=True,
        help="Required full sha256:<64 lowercase hex> image identity.",
    )
    parser.add_argument(
        "--registry",
        default=str(default_registry_path()),
        help="Mode-0600 managed-candidate registry used only for protection checks.",
    )
    parser.add_argument(
        "--protect-image-id",
        action="append",
        default=[],
        help="Additional full image ID that must never be removed (repeatable).",
    )
    parser.add_argument(
        "--receipt",
        help="Immutable mode-0600 post receipt; a sibling .pre.json is also created.",
    )
    parser.add_argument(
        "--resume-pre-receipt",
        help=(
            "Reconcile and, only with --apply, continue an exact immutable "
            "authorized .pre.json intent after an interrupted retirement."
        ),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Perform the exact attested removals. Without this flag, only observe.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        receipt = retire_legacy_candidate(
            project=args.project,
            expected_image_id=args.expected_image_id,
            output_receipt=(
                Path(args.receipt) if args.receipt else _automatic_receipt_path()
            ),
            apply=bool(args.apply),
            registry_path=Path(args.registry),
            protected_image_ids=frozenset(args.protect_image_id),
            resume_pre_receipt=(
                Path(args.resume_pre_receipt)
                if args.resume_pre_receipt
                else None
            ),
        )
    except BaseException as exc:
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
