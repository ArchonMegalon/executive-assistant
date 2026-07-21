from __future__ import annotations

import contextlib
import copy
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts import retire_legacy_manfred_memorial_candidate as legacy


LEGACY_REVISION = "0" * 40
MANAGED_REVISION = "1" * 40
LEGACY_IMAGE_ID = "sha256:" + "a" * 64
MANAGED_IMAGE_ID = "sha256:" + "b" * 64
MANAGED_PROJECT = "ea-manfred-candidate-dac3f8d7-122220"


def _labels(project: str, service: str) -> dict[str, str]:
    labels = {
        "com.docker.compose.project": project,
        "com.docker.compose.service": service,
        "com.docker.compose.container-number": "1",
        "com.docker.compose.oneoff": "False",
        "com.docker.compose.version": "2.29.0",
    }
    if project == legacy.LEGACY_PROJECT:
        labels.update(
            {
                "com.docker.compose.config-hash": "0" * 64,
                "com.docker.compose.depends_on": legacy.LEGACY_COMPOSE_DEPENDS_ON[
                    service
                ],
                "com.docker.compose.image": (
                    LEGACY_IMAGE_ID
                    if service in {"api", "gateway"}
                    else legacy.LEGACY_COMPOSE_IMAGE_IDS[service]
                ),
                "com.docker.compose.project.config_files": legacy.LEGACY_COMPOSE_FILE,
                "com.docker.compose.project.environment_file": legacy.LEGACY_ENVIRONMENT_FILE,
                "com.docker.compose.project.working_dir": legacy.LEGACY_WORKING_DIRECTORY,
                "com.docker.compose.version": legacy.LEGACY_COMPOSE_VERSION,
            }
        )
        if service in {"api", "gateway"}:
            labels["com.docker.compose.replace"] = f"{service}-1"
    return labels


def _stack_rows(
    *,
    project: str,
    revision: str,
    image_id: str,
    port: int,
    alphabet: str,
    expected_networks: tuple[str, ...] = legacy.EXPECTED_NETWORKS,
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    characters = list(alphabet)
    ids = {
        service: characters[index] * 64
        for index, service in enumerate(legacy.EXPECTED_SERVICES)
    }
    containers: list[dict[str, object]] = []
    for service in legacy.EXPECTED_SERVICES:
        mounts: tuple[dict[str, str], ...] = ()
        if service == "api":
            mounts = (
                {
                    "type": "volume",
                    "name": f"{project}_artifacts",
                    "destination": "/data/artifacts",
                },
            )
        elif service == "postgres":
            mounts = (
                {
                    "type": "volume",
                    "name": f"{project}_postgres_data",
                    "destination": "/var/lib/postgresql/data",
                },
            )
        elif service == "redis":
            mounts = (
                {
                    "type": "volume",
                    "name": f"{project}_redis_data",
                    "destination": "/data",
                },
            )
        containers.append(
            {
                "id": ids[service],
                "name": f"{project}-{service}-1",
                "image_id": (
                    image_id
                    if service in {"api", "gateway"}
                    else "sha256:" + service[0] * 64
                ),
                "image_ref": (
                    f"ea-runtime:manfred-{
                        revision[:8]
                        if project == legacy.LEGACY_PROJECT
                        else revision
                    }"
                    if service in {"api", "gateway"}
                    else legacy.EXPECTED_SERVICE_IMAGES[service]
                ),
                "labels": _labels(project, service),
                "project": project,
                "service": service,
                "running": True,
                "status": "running",
                "health": "healthy",
                "started_at": "2026-07-13T12:22:20Z",
                "networks": (
                    (f"{project}_backend", f"{project}_ingress")
                    if service == "gateway"
                    else (f"{project}_backend",)
                ),
                "mounts": mounts,
                "port_bindings": (
                    {
                        "18090/tcp": [
                            {"HostIp": "127.0.0.1", "HostPort": str(port)}
                        ]
                    }
                    if service == "gateway"
                    else {}
                ),
            }
        )
    networks = [
        {
            "id": characters[4 + index] * 64,
            "name": f"{project}_{network}",
            "labels": {
                "com.docker.compose.project": project,
                "com.docker.compose.network": network,
                "com.docker.compose.version": (
                    legacy.LEGACY_COMPOSE_VERSION
                    if project == legacy.LEGACY_PROJECT
                    else "2.29.0"
                ),
                **(
                    {"com.docker.compose.config-hash": "1" * 64}
                    if project == legacy.LEGACY_PROJECT
                    else {}
                ),
            },
            "project": project,
            "network": network,
            "driver": "bridge",
            "internal": network in {"backend", "candidate"},
            "attachable": False,
            "container_ids": tuple(
                sorted(
                    ids[service]
                    for service in (
                        legacy.EXPECTED_SERVICES
                        if network == "backend"
                        else ("gateway",)
                        if network == "ingress"
                        else ()
                    )
                )
            ),
        }
        for index, network in enumerate(expected_networks)
    ]
    volumes = [
        {
            "name": f"{project}_{volume}",
            "labels": {
                "com.docker.compose.project": project,
                "com.docker.compose.volume": volume,
                "com.docker.compose.version": (
                    legacy.LEGACY_COMPOSE_VERSION
                    if project == legacy.LEGACY_PROJECT
                    else "2.29.0"
                ),
                **(
                    {"com.docker.compose.config-hash": "2" * 64}
                    if project == legacy.LEGACY_PROJECT
                    else {}
                ),
            },
            "project": project,
            "volume": volume,
            "driver": "local",
            "scope": "local",
            "created_at": "2026-07-13T10:00:00Z",
            "mountpoint": f"/var/lib/docker/volumes/{project}_{volume}/_data",
            "options": {},
        }
        for volume in legacy.EXPECTED_VOLUMES
    ]
    return containers, networks, volumes


def _image(
    image_id: str, revision: str, *, legacy_short_tag: bool = False
) -> dict[str, object]:
    return {
        "id": image_id,
        "repo_tags": (
            f"ea-runtime:manfred-{
                revision[:8] if legacy_short_tag else revision
            }",
        ),
        "repo_digests": (),
        "labels": {"org.opencontainers.image.revision": revision},
        "environment": (f"EA_SOURCE_REVISION={revision}",),
    }


def _live_rows() -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    return (
        [
            {
                "id": "9" * 64,
                "name": "ea-api",
                "image_id": "sha256:" + "9" * 64,
                "image_ref": "ea-api:live",
                "labels": {
                    "com.docker.compose.project": "ea",
                    "com.docker.compose.service": "ea-api",
                },
                "project": "ea",
                "service": "ea-api",
                "running": True,
                "status": "running",
                "health": "healthy",
                "started_at": "2026-07-13T06:00:00Z",
                "networks": ("ea_default",),
                "mounts": (),
                "port_bindings": {},
            }
        ],
        [
            {
                "id": "8" * 64,
                "name": "ea_default",
                "labels": {"com.docker.compose.project": "ea"},
                "project": "ea",
                "network": "default",
                "driver": "bridge",
                "internal": False,
                "container_ids": ("9" * 64,),
            }
        ],
        [
            {
                "name": "ea_postgres",
                "labels": {"com.docker.compose.project": "ea"},
                "project": "ea",
                "volume": "postgres",
                "driver": "local",
                "scope": "local",
            }
        ],
    )


def _inventory(*, include_legacy: bool = True, include_legacy_image: bool = True) -> legacy.Inventory:
    containers, networks, volumes = _live_rows()
    managed = _stack_rows(
        project=MANAGED_PROJECT,
        revision=MANAGED_REVISION,
        image_id=MANAGED_IMAGE_ID,
        port=18092,
        alphabet="123456",
    )
    containers.extend(managed[0])
    networks.extend(managed[1])
    volumes.extend(managed[2])
    if include_legacy:
        target = _stack_rows(
            project=legacy.LEGACY_PROJECT,
            revision=LEGACY_REVISION,
            image_id=LEGACY_IMAGE_ID,
            port=legacy.LEGACY_PORT,
            alphabet="abcdef7",
            expected_networks=legacy.LEGACY_EXPECTED_NETWORKS,
        )
        containers.extend(target[0])
        networks.extend(target[1])
        volumes.extend(target[2])
    images = {MANAGED_IMAGE_ID: _image(MANAGED_IMAGE_ID, MANAGED_REVISION)}
    if include_legacy_image:
        images[LEGACY_IMAGE_ID] = _image(
            LEGACY_IMAGE_ID,
            LEGACY_REVISION,
            legacy_short_tag=True,
        )
    return legacy.Inventory(tuple(containers), tuple(networks), tuple(volumes), images)


def _proof() -> legacy.ManagedProof:
    return legacy.ManagedProof(
        project=MANAGED_PROJECT,
        observed_at=datetime(2026, 7, 13, 12, 27, 56, tzinfo=timezone.utc),
        image=f"ea-runtime:manfred-{MANAGED_REVISION}",
        image_id=MANAGED_IMAGE_ID,
        revision=MANAGED_REVISION,
        api_container_id="1" * 64,
        gateway_container_id="2" * 64,
        port=18092,
        receipt_sha256="f" * 64,
    )


def _registry(*, registered_legacy_image: bool = False) -> dict[str, object]:
    proof = _proof()
    registered = {proof.image_id}
    if registered_legacy_image:
        registered.add(LEGACY_IMAGE_ID)
    return {
        "proofs": (proof,),
        "pending": (),
        "digest_sha256": "d" * 64,
        "registered_image_ids": frozenset(registered),
        "pending_image_ids": frozenset(),
    }


def _retirement_pre_payload(
    inventory: legacy.Inventory,
    *,
    protected_image_ids: frozenset[str] = frozenset({LEGACY_IMAGE_ID}),
) -> tuple[dict[str, object], dict[str, object]]:
    registry = _registry()
    target = legacy._legacy_stack(inventory, LEGACY_IMAGE_ID)
    _proof_row, newest = legacy._newest_managed(inventory, registry)
    policy = legacy._image_policy(
        inventory,
        legacy=target,
        newest=newest,
        registry_state=registry,
        protected_image_ids=protected_image_ids,
    )
    contract = legacy._resume_contract(
        inventory,
        target,
        image_policy=policy,
        protected_image_ids=protected_image_ids,
    )
    return (
        {
            "schema": legacy.RECEIPT_SCHEMA,
            "observed_at": "2026-07-13T13:00:00Z",
            "project": legacy.LEGACY_PROJECT,
            "expected_image_id": LEGACY_IMAGE_ID,
            "mode": "apply",
            "apply_requested": True,
            "resume_requested": False,
            "dry_run_default": True,
            "manual_only": True,
            "automatic_retirement_authorized": False,
            "secrets_included": False,
            "env_files_read": False,
            "live_ea_mutation_requested": False,
            "managed_candidate_mutation_requested": False,
            "status": "authorized",
            "action": "retirement_intent",
            "target": legacy._stack_summary(target),
            "newest_managed_candidate_before": legacy._stack_summary(newest),
            "newest_managed_proof_before": legacy._managed_proof_summary(
                _proof_row
            ),
            "live_ea_before": legacy._live_fingerprint(inventory),
            "registry_digest_sha256": registry["digest_sha256"],
            "image_policy": policy,
            "resume_contract": contract,
            "mutations_authorized": {
                "container_ids": list(target.container_ids),
                "network_ids": list(target.network_ids),
                "volume_names": list(target.volume_names),
                "image_id": None,
            },
            "mutations_performed": 0,
        },
        contract,
    )


def _inventory_after_prefix(
    original: legacy.Inventory,
    contract: dict[str, object],
    completed_count: int,
) -> legacy.Inventory:
    actions = [dict(row) for row in list(contract["actions"])]
    removed_container_ids = {
        str(row["id"])
        for row in actions[:completed_count]
        if row.get("kind") == "container"
    }
    removed_network_ids = {
        str(row["id"])
        for row in actions[:completed_count]
        if row.get("kind") == "network"
    }
    removed_volume_names = {
        str(row["name"])
        for row in actions[:completed_count]
        if row.get("kind") == "volume"
    }
    image_removed = any(
        row.get("kind") == "image" for row in actions[:completed_count]
    )
    containers = tuple(
        copy.deepcopy(row)
        for row in original.containers
        if str(row.get("id") or "") not in removed_container_ids
    )
    networks: list[dict[str, object]] = []
    for source in original.networks:
        if str(source.get("id") or "") in removed_network_ids:
            continue
        row = copy.deepcopy(source)
        row["container_ids"] = tuple(
            value
            for value in tuple(row.get("container_ids") or ())
            if value not in removed_container_ids
        )
        networks.append(row)
    volumes = tuple(
        copy.deepcopy(row)
        for row in original.volumes
        if str(row.get("name") or "") not in removed_volume_names
    )
    images = copy.deepcopy(original.images)
    if image_removed:
        images.pop(LEGACY_IMAGE_ID, None)
    return legacy.Inventory(containers, tuple(networks), volumes, images)


def _resume_runtime(
    monkeypatch: pytest.MonkeyPatch,
    state: dict[str, legacy.Inventory],
) -> None:
    monkeypatch.setattr(
        legacy,
        "hold_candidate_fleet_lock",
        lambda **_kwargs: _lock({"scope": "fleet"}),
    )
    monkeypatch.setattr(
        legacy,
        "_hold_port_lock",
        lambda _port: _lock({"scope": "port"}),
    )
    monkeypatch.setattr(legacy, "_registry_state", lambda _path: _registry())
    monkeypatch.setattr(legacy, "_inventory_for", lambda *_args: state["inventory"])
    monkeypatch.setattr(legacy, "_assert_http_revision", lambda *_args: None)
    monkeypatch.setattr(legacy, "_assert_port_free", lambda: None)


@contextlib.contextmanager
def _lock(evidence: dict[str, object]):
    yield evidence


def test_legacy_validator_binds_exact_resources_and_rejects_external_volume_user() -> None:
    inventory = _inventory()
    observed = legacy._legacy_stack(inventory, LEGACY_IMAGE_ID)
    assert observed.project == legacy.LEGACY_PROJECT
    assert observed.image_id == LEGACY_IMAGE_ID
    assert len(observed.container_ids) == 4
    assert len(observed.network_ids) == 3

    containers = [copy.deepcopy(row) for row in inventory.containers]
    containers.append(
        {
            "id": "7" * 64,
            "name": "external-volume-user",
            "image_id": "sha256:" + "7" * 64,
            "project": "",
            "service": "",
            "mounts": (
                {
                    "type": "volume",
                    "name": f"{legacy.LEGACY_PROJECT}_artifacts",
                    "destination": "/outside",
                },
            ),
        }
    )
    hostile = legacy.Inventory(
        tuple(containers), inventory.networks, inventory.volumes, inventory.images
    )
    with pytest.raises(RuntimeError, match="volume_(users_invalid|external_user)"):
        legacy._legacy_stack(hostile, LEGACY_IMAGE_ID)


def test_legacy_validator_rejects_unexpected_compose_label_and_wrong_name() -> None:
    inventory = _inventory()
    containers = [copy.deepcopy(row) for row in inventory.containers]
    target = next(
        row for row in containers if row.get("project") == legacy.LEGACY_PROJECT
    )
    target["labels"]["com.docker.compose.unexpected"] = "unsafe"
    with pytest.raises(RuntimeError, match="resource_labels_invalid"):
        legacy._legacy_stack(
            legacy.Inventory(
                tuple(containers), inventory.networks, inventory.volumes, inventory.images
            ),
            LEGACY_IMAGE_ID,
        )

    containers = [copy.deepcopy(row) for row in inventory.containers]
    target = next(
        row for row in containers if row.get("project") == legacy.LEGACY_PROJECT
    )
    target["name"] = "ea-manfred-candidate-api-surprise"
    with pytest.raises(RuntimeError, match="container_invalid"):
        legacy._legacy_stack(
            legacy.Inventory(
                tuple(containers), inventory.networks, inventory.volumes, inventory.images
            ),
            LEGACY_IMAGE_ID,
        )


def test_legacy_candidate_network_must_be_internal_and_empty() -> None:
    inventory = _inventory()
    networks = [copy.deepcopy(row) for row in inventory.networks]
    candidate = next(
        row
        for row in networks
        if row.get("name") == f"{legacy.LEGACY_PROJECT}_candidate"
    )
    assert candidate["internal"] is True
    assert candidate["attachable"] is False
    assert candidate["container_ids"] == ()
    candidate["attachable"] = True
    with pytest.raises(RuntimeError, match="network_invalid"):
        legacy._legacy_stack(
            legacy.Inventory(
                inventory.containers, tuple(networks), inventory.volumes, inventory.images
            ),
            LEGACY_IMAGE_ID,
        )
    candidate["attachable"] = False
    candidate["container_ids"] = ("a" * 64,)
    with pytest.raises(RuntimeError, match="network_invalid"):
        legacy._legacy_stack(
            legacy.Inventory(
                inventory.containers, tuple(networks), inventory.volumes, inventory.images
            ),
            LEGACY_IMAGE_ID,
        )


def test_legacy_compose_label_contract_requires_v513_and_full_config_hash() -> None:
    inventory = _inventory()
    containers = [copy.deepcopy(row) for row in inventory.containers]
    gateway = next(
        row
        for row in containers
        if row.get("project") == legacy.LEGACY_PROJECT
        and row.get("service") == "gateway"
    )
    gateway["labels"]["com.docker.compose.config-hash"] = "short"
    with pytest.raises(RuntimeError, match="container_labels_invalid"):
        legacy._legacy_stack(
            legacy.Inventory(
                tuple(containers), inventory.networks, inventory.volumes, inventory.images
            ),
            LEGACY_IMAGE_ID,
        )

    networks = [copy.deepcopy(row) for row in inventory.networks]
    backend = next(
        row
        for row in networks
        if row.get("name") == f"{legacy.LEGACY_PROJECT}_backend"
    )
    backend["labels"]["com.docker.compose.version"] = "5.1.2"
    with pytest.raises(RuntimeError, match="network_labels_invalid"):
        legacy._legacy_stack(
            legacy.Inventory(
                inventory.containers, tuple(networks), inventory.volumes, inventory.images
            ),
            LEGACY_IMAGE_ID,
        )


@pytest.mark.parametrize("label", ["com.docker.compose.image", "com.docker.compose.depends_on"])
def test_legacy_compose_label_contract_binds_image_and_dependencies(
    label: str,
) -> None:
    inventory = _inventory()
    containers = [copy.deepcopy(row) for row in inventory.containers]
    api = next(
        row
        for row in containers
        if row.get("project") == legacy.LEGACY_PROJECT
        and row.get("service") == "api"
    )
    api["labels"][label] = "unexpected"
    with pytest.raises(RuntimeError, match="container_labels_invalid"):
        legacy._legacy_stack(
            legacy.Inventory(
                tuple(containers), inventory.networks, inventory.volumes, inventory.images
            ),
            LEGACY_IMAGE_ID,
        )


def test_legacy_gateway_rejects_any_additional_port_binding() -> None:
    inventory = _inventory()
    containers = [copy.deepcopy(row) for row in inventory.containers]
    gateway = next(
        row
        for row in containers
        if row.get("project") == legacy.LEGACY_PROJECT
        and row.get("service") == "gateway"
    )
    gateway["port_bindings"]["9999/tcp"] = [
        {"HostIp": "127.0.0.1", "HostPort": "19999"}
    ]
    with pytest.raises(RuntimeError, match="gateway_port_invalid"):
        legacy._legacy_stack(
            legacy.Inventory(
                tuple(containers), inventory.networks, inventory.volumes, inventory.images
            ),
            LEGACY_IMAGE_ID,
        )


def test_image_policy_requires_sole_tag_and_no_protection_or_registration() -> None:
    inventory = _inventory()
    target = legacy._legacy_stack(inventory, LEGACY_IMAGE_ID)
    _managed_proof, newest = legacy._newest_managed(inventory, _registry())
    eligible = legacy._image_policy(
        inventory,
        legacy=target,
        newest=newest,
        registry_state=_registry(),
        protected_image_ids=frozenset(),
    )
    assert eligible["eligible"] is True

    images = copy.deepcopy(inventory.images)
    images[LEGACY_IMAGE_ID]["repo_tags"] = (
        f"ea-runtime:manfred-{LEGACY_REVISION}",
        "ea-runtime:unexpected-alias",
    )
    images[LEGACY_IMAGE_ID]["repo_digests"] = (
        "registry.example/ea-runtime@sha256:" + "c" * 64,
    )
    tagged = legacy.Inventory(
        inventory.containers, inventory.networks, inventory.volumes, images
    )
    policy = legacy._image_policy(
        tagged,
        legacy=target,
        newest=newest,
        registry_state=_registry(registered_legacy_image=True),
        protected_image_ids=frozenset({LEGACY_IMAGE_ID}),
    )
    assert policy["eligible"] is False
    assert policy["preserve_reasons"] == [
        "not_sole_expected_tag",
        "protected_image",
        "registered_candidate_image",
        "repo_digest_aliases",
    ]


def test_dry_run_holds_fleet_then_port_writes_pre_and_post_and_never_mutates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    inventory = _inventory()
    events: list[str] = []
    receipts: list[tuple[Path, dict[str, object]]] = []

    @contextlib.contextmanager
    def fleet(**_kwargs: object):
        events.append("fleet")
        yield {"scope": "fleet"}

    @contextlib.contextmanager
    def port(value: int):
        assert value == legacy.LEGACY_PORT
        events.append("port")
        yield {"scope": "port", "port": value}

    monkeypatch.setattr(legacy, "hold_candidate_fleet_lock", fleet)
    monkeypatch.setattr(legacy, "_hold_port_lock", port)
    monkeypatch.setattr(
        legacy,
        "_registry_state",
        lambda _path: events.append("registry") or _registry(),
    )
    monkeypatch.setattr(
        legacy,
        "_inventory_for",
        lambda *_args: events.append("inventory") or inventory,
    )
    monkeypatch.setattr(legacy, "_assert_http_revision", lambda *_args: None)
    monkeypatch.setattr(
        legacy,
        "_atomic_receipt",
        lambda path, payload: receipts.append((Path(path), payload)),
    )
    monkeypatch.setattr(
        legacy,
        "_run",
        lambda *_args, **_kwargs: pytest.fail("dry-run reached a mutation command"),
    )
    result = legacy.retire_legacy_candidate(
        project=legacy.LEGACY_PROJECT,
        expected_image_id=LEGACY_IMAGE_ID,
        output_receipt=tmp_path / "post.json",
        apply=False,
        registry_path=tmp_path / "registry.json",
    )
    assert events[:3] == ["fleet", "port", "registry"]
    assert result["action"] == "dry_run_complete"
    assert result["mutations_performed"] == 0
    assert [path.name for path, _payload in receipts] == ["post.pre.json", "post.json"]
    assert receipts[0][1]["mutations_authorized"]["container_ids"] == []


def test_apply_uses_only_exact_ids_verifies_absence_and_removes_eligible_image(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    before = _inventory()
    intermediate = _inventory(include_legacy=False, include_legacy_image=True)
    after = _inventory(include_legacy=False, include_legacy_image=False)
    inventories = iter((before, before, intermediate, after))
    commands: list[list[str]] = []
    receipts: list[dict[str, object]] = []
    monkeypatch.setattr(
        legacy,
        "hold_candidate_fleet_lock",
        lambda **_kwargs: _lock({"scope": "fleet"}),
    )
    monkeypatch.setattr(
        legacy,
        "_hold_port_lock",
        lambda _port: _lock({"scope": "port"}),
    )
    monkeypatch.setattr(legacy, "_registry_state", lambda _path: _registry())
    monkeypatch.setattr(legacy, "_inventory_for", lambda *_args: next(inventories))
    monkeypatch.setattr(legacy, "_assert_http_revision", lambda *_args: None)
    monkeypatch.setattr(legacy, "_assert_port_free", lambda: None)
    monkeypatch.setattr(
        legacy,
        "_run",
        lambda argv, **_kwargs: commands.append(list(argv)) or b"",
    )
    monkeypatch.setattr(legacy, "_listed", lambda _argv: [])
    monkeypatch.setattr(
        legacy,
        "_inspect_image_alias_snapshot",
            lambda _image_id: {
                "image_id": LEGACY_IMAGE_ID,
                "repo_tags": [
                    f"ea-runtime:manfred-{LEGACY_REVISION[:8]}"
                ],
            "repo_digests": [],
        },
    )
    monkeypatch.setattr(legacy, "_existing_image_ids", lambda: {MANAGED_IMAGE_ID})
    monkeypatch.setattr(
        legacy, "_atomic_receipt", lambda _path, payload: receipts.append(payload)
    )
    result = legacy.retire_legacy_candidate(
        project=legacy.LEGACY_PROJECT,
        expected_image_id=LEGACY_IMAGE_ID,
        output_receipt=tmp_path / "post.json",
        apply=True,
        registry_path=tmp_path / "registry.json",
    )
    assert result["action"] == "applied"
    assert result["target_absent_after"] is True
    assert result["image_result"]["removed"] is True
    assert ["docker", "image", "rm", LEGACY_IMAGE_ID] in commands
    assert not any(command[:3] == ["docker", "compose", "down"] for command in commands)
    container_removals = [
        command for command in commands if command[:3] == ["docker", "container", "rm"]
    ]
    network_removals = [
        command for command in commands if command[:3] == ["docker", "network", "rm"]
    ]
    assert len(container_removals) == 4
    assert len(network_removals) == 3
    assert all(legacy.HEX_64.fullmatch(command[-1]) for command in container_removals)
    assert all(legacy.HEX_64.fullmatch(command[-1]) for command in network_removals)
    assert result["mutations_performed"] == 11
    assert len(receipts) == 2


@pytest.mark.parametrize(
    ("drift_kind", "expected_error"),
    [
        ("volume_reuse", "resume_volume_drift"),
        ("late_volume_attachment", "resume_volume_drift"),
        ("late_network_attachment", "resume_network_drift"),
    ],
)
def test_apply_reinventory_blocks_volume_drift_before_first_mutation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    drift_kind: str,
    expected_error: str,
) -> None:
    before = _inventory()
    containers = [copy.deepcopy(row) for row in before.containers]
    networks = tuple(copy.deepcopy(row) for row in before.networks)
    volumes = [copy.deepcopy(row) for row in before.volumes]
    if drift_kind == "volume_reuse":
        target = next(
            row
            for row in volumes
            if row.get("name") == f"{legacy.LEGACY_PROJECT}_artifacts"
        )
        target["created_at"] = "2026-07-13T13:01:00Z"
    elif drift_kind == "late_volume_attachment":
        containers.append(
            {
                "id": "7" * 64,
                "name": "late-external-volume-user",
                "image_id": "sha256:" + "7" * 64,
                "project": "",
                "service": "",
                "mounts": (
                    {
                        "type": "volume",
                        "name": f"{legacy.LEGACY_PROJECT}_artifacts",
                        "destination": "/outside",
                    },
                ),
            }
        )
    else:
        backend = next(
            row
            for row in networks
            if row.get("name") == f"{legacy.LEGACY_PROJECT}_backend"
        )
        backend["container_ids"] = tuple(backend["container_ids"]) + ("7" * 64,)
    drifted = legacy.Inventory(
        tuple(containers), networks, tuple(volumes), before.images
    )
    inventories = iter((before, drifted))
    commands: list[list[str]] = []
    _resume_runtime(monkeypatch, {"inventory": before})
    monkeypatch.setattr(legacy, "_inventory_for", lambda *_args: next(inventories))
    monkeypatch.setattr(
        legacy,
        "_atomic_receipt",
        lambda _path, _payload: None,
    )
    monkeypatch.setattr(
        legacy,
        "_run",
        lambda argv, **_kwargs: commands.append(list(argv)) or b"",
    )
    with pytest.raises(RuntimeError, match=expected_error):
        legacy.retire_legacy_candidate(
            project=legacy.LEGACY_PROJECT,
            expected_image_id=LEGACY_IMAGE_ID,
            output_receipt=tmp_path / "drift.json",
            apply=True,
            registry_path=tmp_path / "registry.json",
        )
    assert commands == []


def test_resume_continues_exact_prefix_after_mid_command_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    original = _inventory()
    pre_payload, contract = _retirement_pre_payload(original)
    pre_path = tmp_path / "intent.pre.json"
    legacy._atomic_receipt(pre_path, pre_payload)
    state = {"inventory": original}
    _resume_runtime(monkeypatch, state)
    prefix = {"count": 0}

    def fail_second(_argv: list[str], **_kwargs: object) -> bytes:
        if prefix["count"] == 1:
            raise RuntimeError("simulated_mid_command_failure")
        prefix["count"] += 1
        state["inventory"] = _inventory_after_prefix(
            original, contract, prefix["count"]
        )
        return b""

    monkeypatch.setattr(legacy, "_run", fail_second)
    with pytest.raises(RuntimeError, match="simulated_mid_command_failure"):
        legacy.retire_legacy_candidate(
            project=legacy.LEGACY_PROJECT,
            expected_image_id=LEGACY_IMAGE_ID,
            output_receipt=tmp_path / "failed.json",
            apply=True,
            registry_path=tmp_path / "registry.json",
            protected_image_ids=frozenset({LEGACY_IMAGE_ID}),
            resume_pre_receipt=pre_path,
        )
    assert prefix["count"] == 1

    def finish(_argv: list[str], **_kwargs: object) -> bytes:
        prefix["count"] += 1
        state["inventory"] = _inventory_after_prefix(
            original, contract, prefix["count"]
        )
        return b""

    monkeypatch.setattr(legacy, "_run", finish)
    result = legacy.retire_legacy_candidate(
        project=legacy.LEGACY_PROJECT,
        expected_image_id=LEGACY_IMAGE_ID,
        output_receipt=tmp_path / "resumed.json",
        apply=True,
        registry_path=tmp_path / "registry.json",
        protected_image_ids=frozenset({LEGACY_IMAGE_ID}),
        resume_pre_receipt=pre_path,
    )
    assert result["action"] == "resumed"
    assert result["execution"]["reconciled_actions"] == list(contract["actions"][:1])
    assert result["mutations_performed"] == len(contract["actions"]) - 1
    assert prefix["count"] == len(contract["actions"])


def test_resume_recovers_timeout_after_successful_delete(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    original = _inventory()
    pre_payload, contract = _retirement_pre_payload(original)
    pre_path = tmp_path / "timeout.pre.json"
    legacy._atomic_receipt(pre_path, pre_payload)
    state = {"inventory": original}
    _resume_runtime(monkeypatch, state)
    prefix = {"count": 0}

    def timeout_after_success(_argv: list[str], **_kwargs: object) -> bytes:
        prefix["count"] = 1
        state["inventory"] = _inventory_after_prefix(original, contract, 1)
        raise RuntimeError("simulated_timeout_after_success")

    monkeypatch.setattr(legacy, "_run", timeout_after_success)
    with pytest.raises(RuntimeError, match="simulated_timeout_after_success"):
        legacy.retire_legacy_candidate(
            project=legacy.LEGACY_PROJECT,
            expected_image_id=LEGACY_IMAGE_ID,
            output_receipt=tmp_path / "timeout-failed.json",
            apply=True,
            registry_path=tmp_path / "registry.json",
            protected_image_ids=frozenset({LEGACY_IMAGE_ID}),
            resume_pre_receipt=pre_path,
        )

    def finish(_argv: list[str], **_kwargs: object) -> bytes:
        prefix["count"] += 1
        state["inventory"] = _inventory_after_prefix(
            original, contract, prefix["count"]
        )
        return b""

    monkeypatch.setattr(legacy, "_run", finish)
    result = legacy.retire_legacy_candidate(
        project=legacy.LEGACY_PROJECT,
        expected_image_id=LEGACY_IMAGE_ID,
        output_receipt=tmp_path / "timeout-resumed.json",
        apply=True,
        registry_path=tmp_path / "registry.json",
        protected_image_ids=frozenset({LEGACY_IMAGE_ID}),
        resume_pre_receipt=pre_path,
    )
    assert len(result["execution"]["reconciled_actions"]) == 1
    assert prefix["count"] == len(contract["actions"])


def test_resume_after_post_receipt_failure_performs_no_second_mutation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    original = _inventory()
    pre_payload, contract = _retirement_pre_payload(original)
    pre_path = tmp_path / "post-failure.pre.json"
    write_receipt = legacy._atomic_receipt
    write_receipt(pre_path, pre_payload)
    state = {"inventory": original}
    _resume_runtime(monkeypatch, state)
    prefix = {"count": 0}

    def remove(_argv: list[str], **_kwargs: object) -> bytes:
        prefix["count"] += 1
        state["inventory"] = _inventory_after_prefix(
            original, contract, prefix["count"]
        )
        return b""

    monkeypatch.setattr(legacy, "_run", remove)
    monkeypatch.setattr(
        legacy,
        "_atomic_receipt",
        lambda _path, _payload: (_ for _ in ()).throw(
            RuntimeError("simulated_post_receipt_failure")
        ),
    )
    with pytest.raises(RuntimeError, match="simulated_post_receipt_failure"):
        legacy.retire_legacy_candidate(
            project=legacy.LEGACY_PROJECT,
            expected_image_id=LEGACY_IMAGE_ID,
            output_receipt=tmp_path / "missing-post.json",
            apply=True,
            registry_path=tmp_path / "registry.json",
            protected_image_ids=frozenset({LEGACY_IMAGE_ID}),
            resume_pre_receipt=pre_path,
        )
    assert prefix["count"] == len(contract["actions"])

    monkeypatch.setattr(legacy, "_atomic_receipt", write_receipt)
    monkeypatch.setattr(
        legacy,
        "_run",
        lambda *_args, **_kwargs: pytest.fail("completed resume mutated again"),
    )
    result = legacy.retire_legacy_candidate(
        project=legacy.LEGACY_PROJECT,
        expected_image_id=LEGACY_IMAGE_ID,
        output_receipt=tmp_path / "reconciled-post.json",
        apply=True,
        registry_path=tmp_path / "registry.json",
        protected_image_ids=frozenset({LEGACY_IMAGE_ID}),
        resume_pre_receipt=pre_path,
    )
    assert result["mutations_performed"] == 0
    assert len(result["execution"]["reconciled_actions"]) == len(
        contract["actions"]
    )


def test_image_apply_recheck_preserves_when_a_reference_appears(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[list[str]] = []
    monkeypatch.setattr(legacy, "_listed", lambda _argv: ["new-container-reference"])
    monkeypatch.setattr(
        legacy,
        "_run",
        lambda argv, **_kwargs: commands.append(list(argv)) or b"",
    )
    result = legacy._remove_image_if_still_eligible(
        LEGACY_IMAGE_ID,
        planned_policy={"eligible": True, "preserve_reasons": []},
    )
    assert result == {
        "removed": False,
        "preserve_reasons": ["referenced_at_apply"],
    }
    assert ["docker", "image", "rm", LEGACY_IMAGE_ID] not in commands


@pytest.mark.parametrize(
    ("alias_kind", "expected_reason"),
    [
        ("tag", "image_alias_changed_at_apply"),
        ("digest", "repo_digest_aliases_at_apply"),
    ],
)
def test_image_apply_rechecks_tag_and_digest_aliases(
    monkeypatch: pytest.MonkeyPatch,
    alias_kind: str,
    expected_reason: str,
) -> None:
    observed = {
        "image_id": LEGACY_IMAGE_ID,
        "repo_tags": [f"ea-runtime:manfred-{LEGACY_REVISION}"],
        "repo_digests": [],
    }
    if alias_kind == "tag":
        observed["repo_tags"].append("ea-runtime:unexpected-alias")
    else:
        observed["repo_digests"].append(
            "registry.example/ea-runtime@sha256:" + "e" * 64
        )
    commands: list[list[str]] = []
    monkeypatch.setattr(legacy, "_listed", lambda _argv: [])
    monkeypatch.setattr(
        legacy, "_inspect_image_alias_snapshot", lambda _image_id: observed
    )
    monkeypatch.setattr(
        legacy,
        "_run",
        lambda argv, **_kwargs: commands.append(list(argv)) or b"",
    )
    result = legacy._remove_image_if_still_eligible(
        LEGACY_IMAGE_ID,
        planned_policy={
            "eligible": True,
            "observed_tags": [f"ea-runtime:manfred-{LEGACY_REVISION}"],
            "observed_repo_digests": [],
            "preserve_reasons": [],
        },
    )
    assert result == {"removed": False, "preserve_reasons": [expected_reason]}
    assert ["docker", "image", "rm", LEGACY_IMAGE_ID] not in commands


def test_busy_fleet_fails_before_registry_or_docker_observation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    @contextlib.contextmanager
    def busy(**_kwargs: object):
        raise RuntimeError("manfred_candidate_fleet_lock_held")
        yield  # pragma: no cover

    written: list[dict[str, object]] = []
    monkeypatch.setattr(legacy, "hold_candidate_fleet_lock", busy)
    monkeypatch.setattr(
        legacy,
        "_registry_state",
        lambda _path: pytest.fail("busy fleet read the runtime registry"),
    )
    monkeypatch.setattr(
        legacy,
        "_inventory_for",
        lambda *_args: pytest.fail("busy fleet observed Docker"),
    )
    monkeypatch.setattr(
        legacy, "_atomic_receipt", lambda _path, payload: written.append(payload)
    )
    with pytest.raises(RuntimeError, match="fleet_lock_held"):
        legacy.retire_legacy_candidate(
            project=legacy.LEGACY_PROJECT,
            expected_image_id=LEGACY_IMAGE_ID,
            output_receipt=tmp_path / "post.json",
            apply=True,
        )
    assert len(written) == 1
    assert written[0]["status"] == "fail"


def test_receipts_are_mode_0600_and_cannot_be_replaced(tmp_path: Path) -> None:
    path = tmp_path / "receipt.json"
    legacy._atomic_receipt(path, {"schema": legacy.RECEIPT_SCHEMA, "status": "pass"})
    assert path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(RuntimeError, match="output_exists"):
        legacy._atomic_receipt(path, {"status": "replacement"})
    assert json.loads(path.read_text(encoding="utf-8"))["status"] == "pass"


def test_cli_requires_exact_project_and_full_image_and_defaults_to_dry_run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured: dict[str, object] = {}

    def retire(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"schema": legacy.RECEIPT_SCHEMA, "status": "pass"}

    monkeypatch.setattr(legacy, "retire_legacy_candidate", retire)
    assert (
        legacy.main(
            [
                "--project",
                legacy.LEGACY_PROJECT,
                "--expected-image-id",
                LEGACY_IMAGE_ID,
                "--receipt",
                str(tmp_path / "post.json"),
            ]
        )
        == 0
    )
    assert captured["apply"] is False
    assert captured["project"] == legacy.LEGACY_PROJECT
    assert json.loads(capsys.readouterr().out)["status"] == "pass"

    with pytest.raises(SystemExit):
        legacy.build_parser().parse_args(
            ["--project", "ea", "--expected-image-id", LEGACY_IMAGE_ID]
        )
    with pytest.raises(SystemExit):
        legacy.build_parser().parse_args(["--project", legacy.LEGACY_PROJECT])


def test_cli_help_works_from_arbitrary_cwd_without_docker(tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            os.environ.get("PYTHON", "python3"),
            str(legacy.ROOT / "scripts/retire_legacy_manfred_memorial_candidate.py"),
            "--help",
        ],
        cwd=tmp_path,
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
        env={"HOME": str(tmp_path), "PATH": os.environ.get("PATH", "")},
    )
    assert completed.returncode == 0, completed.stderr.decode(errors="replace")
    assert b"--apply" in completed.stdout
    assert b"--expected-image-id" in completed.stdout
