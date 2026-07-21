from __future__ import annotations

import contextlib
import copy
import hashlib
import json
import os
import stat
import subprocess
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import cleanup_manfred_memorial_candidates as retention
from scripts import manfred_candidate_fleet_lock as fleet_lock
from scripts import manfred_candidate_registry as registry
from scripts import run_manfred_memorial_candidate as runner


NOW = datetime(2026, 7, 13, 14, 45, tzinfo=timezone.utc)
OLD_PROJECT = "ea-manfred-candidate-b8b9401f-114500"
NEW_PROJECT = "ea-manfred-candidate-dac3f8d7-122220"
OLD_REVISION = "1" * 40
NEW_REVISION = "2" * 40
OLD_IMAGE = "sha256:" + "a" * 64
NEW_IMAGE = "sha256:" + "b" * 64


def _resource_id(project: str, kind: str) -> str:
    return hashlib.sha256(f"{project}:{kind}".encode("utf-8")).hexdigest()


def _proof(
    project: str,
    revision: str,
    image_id: str,
    observed_at: datetime,
    port: int,
) -> retention.RuntimeProof:
    return retention.RuntimeProof(
        schema=retention.RUNTIME_RECEIPT_SCHEMA,
        project=project,
        observed_at=observed_at,
        image=f"ea-runtime:manfred-{revision}",
        image_id=image_id,
        revision=revision,
        api_container_id=_resource_id(project, "api"),
        gateway_container_id=_resource_id(project, "gateway"),
        port=port,
        receipt_sha256=_resource_id(project, "receipt"),
    )


def _container_labels(project: str, service: str) -> dict[str, str]:
    return {
        "com.docker.compose.project": project,
        "com.docker.compose.service": service,
        "com.docker.compose.container-number": "1",
        "com.docker.compose.oneoff": "False",
        "com.docker.compose.version": "2.29.0",
    }


def _candidate_rows(proof: retention.RuntimeProof) -> tuple[list[dict], list[dict], list[dict]]:
    assert proof.project is not None
    project = proof.project
    ids = {
        "api": proof.api_container_id,
        "gateway": proof.gateway_container_id,
        "postgres": _resource_id(project, "postgres"),
        "redis": _resource_id(project, "redis"),
    }
    containers: list[dict] = []
    for service in retention.EXPECTED_SERVICES:
        networks = (
            (f"{project}_backend", f"{project}_ingress")
            if service == "gateway"
            else (f"{project}_backend",)
        )
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
        image_id = (
            proof.image_id
            if service in {"api", "gateway"}
            else "sha256:" + _resource_id(project, f"{service}-image")
        )
        image_ref = (
            proof.image
            if service in {"api", "gateway"}
            else retention.EXPECTED_SERVICE_IMAGES[service]
        )
        containers.append(
            {
                "id": ids[service],
                "name": f"{project}-{service}-1",
                "image_id": image_id,
                "image_ref": image_ref,
                "labels": _container_labels(project, service),
                "project": project,
                "service": service,
                "running": True,
                "status": "running",
                "health": "healthy",
                "started_at": "2026-07-13T12:22:20Z",
                "networks": networks,
                "mounts": mounts,
                "port_bindings": (
                    {
                        "18090/tcp": [
                            {"HostIp": "127.0.0.1", "HostPort": str(proof.port)}
                        ]
                    }
                    if service == "gateway"
                    else {}
                ),
            }
        )
    networks = [
        {
            "id": _resource_id(project, f"network-{index}"),
            "name": f"{project}_{name}",
            "labels": {
                "com.docker.compose.project": project,
                "com.docker.compose.network": name,
                "com.docker.compose.version": "2.29.0",
            },
            "project": project,
            "network": name,
            "driver": "bridge",
            "internal": name == "backend",
            "attachable": False,
            "container_ids": tuple(
                sorted(
                    ids[service]
                    for service in (
                        retention.EXPECTED_SERVICES
                        if name == "backend"
                        else ("gateway",)
                    )
                )
            ),
        }
        for index, name in enumerate(retention.EXPECTED_NETWORKS)
    ]
    volumes = [
        {
            "name": f"{project}_{name}",
            "labels": {
                "com.docker.compose.project": project,
                "com.docker.compose.volume": name,
                "com.docker.compose.version": "2.29.0",
            },
            "project": project,
            "volume": name,
            "driver": "local",
            "scope": "local",
        }
        for name in retention.EXPECTED_VOLUMES
    ]
    return containers, networks, volumes


def _live_rows() -> tuple[list[dict], list[dict], list[dict]]:
    return (
        [
            {
                "id": "9" * 64,
                "name": "ea-api",
                "image_id": "sha256:" + "9" * 64,
                "image_ref": "ea-api:rollback-safe",
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
                "id": "0" * 64,
                "name": "ea_default",
                "labels": {
                    "com.docker.compose.project": "ea",
                    "com.docker.compose.network": "default",
                },
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
                "labels": {
                    "com.docker.compose.project": "ea",
                    "com.docker.compose.volume": "postgres",
                },
                "project": "ea",
                "volume": "postgres",
                "driver": "local",
                "scope": "local",
            }
        ],
    )


def test_live_fingerprint_excludes_only_the_exact_oneoff_memorial_probe() -> None:
    containers, networks, volumes = _live_rows()
    baseline = retention._live_fingerprint(
        retention.Inventory(tuple(containers), tuple(networks), tuple(volumes), {})
    )
    probe = {
        **copy.deepcopy(containers[0]),
        "id": "8" * 64,
        "name": retention.LIVE_EA_EPHEMERAL_PROBE_NAME,
        "labels": {
            **copy.deepcopy(containers[0]["labels"]),
            retention.COMPOSE_ONEOFF_LABEL: "True",
        },
    }
    with_probe = retention._live_fingerprint(
        retention.Inventory(
            tuple([*containers, probe]), tuple(networks), tuple(volumes), {}
        )
    )

    assert with_probe == baseline
    assert baseline["api_container_id"] == "9" * 64
    assert baseline["excluded_ephemeral_probe_name"] == (
        retention.LIVE_EA_EPHEMERAL_PROBE_NAME
    )

    non_oneoff = copy.deepcopy(probe)
    non_oneoff["labels"][retention.COMPOSE_ONEOFF_LABEL] = "False"
    with_non_oneoff = retention._live_fingerprint(
        retention.Inventory(
            tuple([*containers, non_oneoff]), tuple(networks), tuple(volumes), {}
        )
    )
    assert with_non_oneoff["container_count"] == baseline["container_count"] + 1
    assert with_non_oneoff["digest_sha256"] != baseline["digest_sha256"]


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("name", "ea-memorial-proxy-probe-copy"),
        ("service", "api"),
    ),
)
def test_live_fingerprint_keeps_probe_lookalikes_in_the_fingerprint(
    field: str, replacement: str
) -> None:
    containers, networks, volumes = _live_rows()
    baseline = retention._live_fingerprint(
        retention.Inventory(tuple(containers), tuple(networks), tuple(volumes), {})
    )
    lookalike = {
        **copy.deepcopy(containers[0]),
        "id": "8" * 64,
        "name": retention.LIVE_EA_EPHEMERAL_PROBE_NAME,
        "labels": {
            **copy.deepcopy(containers[0]["labels"]),
            retention.COMPOSE_ONEOFF_LABEL: "True",
        },
    }
    lookalike[field] = replacement

    observed = retention._live_fingerprint(
        retention.Inventory(
            tuple([*containers, lookalike]), tuple(networks), tuple(volumes), {}
        )
    )
    assert observed["container_count"] == baseline["container_count"] + 1
    assert observed["digest_sha256"] != baseline["digest_sha256"]


def test_live_fingerprint_rejects_duplicate_exact_oneoff_probes() -> None:
    containers, networks, volumes = _live_rows()
    probe = {
        **copy.deepcopy(containers[0]),
        "id": "8" * 64,
        "name": retention.LIVE_EA_EPHEMERAL_PROBE_NAME,
        "labels": {
            **copy.deepcopy(containers[0]["labels"]),
            retention.COMPOSE_ONEOFF_LABEL: "True",
        },
    }
    duplicate = {**copy.deepcopy(probe), "id": "7" * 64}

    with pytest.raises(
        RuntimeError, match="manfred_candidate_retention_live_ea_unhealthy"
    ):
        retention._live_fingerprint(
            retention.Inventory(
                tuple([*containers, probe, duplicate]),
                tuple(networks),
                tuple(volumes),
                {},
            )
        )


def test_live_fingerprint_requires_exact_canonical_api_name_and_service() -> None:
    containers, networks, volumes = _live_rows()
    for field, replacement in (("name", "ea-api-copy"), ("service", "api")):
        malformed = copy.deepcopy(containers)
        malformed[0][field] = replacement
        with pytest.raises(
            RuntimeError, match="manfred_candidate_retention_live_ea_unhealthy"
        ):
            retention._live_fingerprint(
                retention.Inventory(
                    tuple(malformed), tuple(networks), tuple(volumes), {}
                )
            )


def _image(proof: retention.RuntimeProof) -> dict[str, object]:
    return {
        "id": proof.image_id,
        "repo_tags": (proof.image,),
        "repo_digests": (),
        "labels": {"org.opencontainers.image.revision": proof.revision},
        "environment": (f"EA_SOURCE_REVISION={proof.revision}",),
    }


def _inventory(
    old: retention.RuntimeProof,
    new: retention.RuntimeProof,
    *,
    legacy: bool = False,
) -> retention.Inventory:
    inventory = _inventory_for_proofs((old, new))
    containers = list(inventory.containers)
    networks = list(inventory.networks)
    volumes = list(inventory.volumes)
    images = dict(inventory.images)
    if legacy:
        containers.append(
            {
                "id": "7" * 64,
                "name": "ea-manfred-candidate-api-1",
                "image_id": "sha256:" + "7" * 64,
                "image_ref": "ea-runtime:legacy",
                "labels": {
                    "com.docker.compose.project": retention.LEGACY_COMPOSE_PROJECT,
                    "com.docker.compose.service": "api",
                },
                "project": retention.LEGACY_COMPOSE_PROJECT,
                "service": "api",
                "running": True,
                "status": "running",
                "health": "healthy",
                "started_at": "2026-07-12T00:00:00Z",
                "networks": ("ea-manfred-candidate_default",),
                "mounts": (),
                "port_bindings": {},
            }
        )
    return retention.Inventory(
        containers=tuple(containers),
        networks=tuple(networks),
        volumes=tuple(volumes),
        images=images,
    )


def _inventory_for_proofs(
    proofs: tuple[retention.RuntimeProof, ...],
    *,
    active_projects: set[str] | None = None,
) -> retention.Inventory:
    containers, networks, volumes = _live_rows()
    active_projects = (
        {str(proof.project) for proof in proofs}
        if active_projects is None
        else set(active_projects)
    )
    for proof in proofs:
        if proof.project not in active_projects:
            continue
        candidate_containers, candidate_networks, candidate_volumes = _candidate_rows(proof)
        containers.extend(candidate_containers)
        networks.extend(candidate_networks)
        volumes.extend(candidate_volumes)
    return retention.Inventory(
        containers=tuple(containers),
        networks=tuple(networks),
        volumes=tuple(volumes),
        images={proof.image_id: _image(proof) for proof in proofs},
    )


def _pair() -> tuple[retention.RuntimeProof, retention.RuntimeProof]:
    return (
        _proof(OLD_PROJECT, OLD_REVISION, OLD_IMAGE, NOW - timedelta(hours=2), 18091),
        _proof(NEW_PROJECT, NEW_REVISION, NEW_IMAGE, NOW - timedelta(hours=1), 18092),
    )


def _batch_proofs(count: int = 7) -> tuple[retention.RuntimeProof, ...]:
    return tuple(
        _proof(
            f"ea-manfred-candidate-batch-{index:02d}-abcdef",
            f"{index + 1:040x}",
            "sha256:" + f"{index + 1:064x}",
            NOW - timedelta(hours=count - index),
            18100 + index,
        )
        for index in range(count)
    )


def _retired_ledger(
    proof: retention.RuntimeProof, *, retired_at: datetime = NOW
) -> dict[str, dict[str, object]]:
    assert proof.project is not None
    grace_until = retired_at + timedelta(
        seconds=retention.RETIRED_IMAGE_LEDGER_WINDOW_SECONDS
    )
    return {
        proof.image_id: {
            "projects": [proof.project],
            "receipt_sha256": [proof.receipt_sha256],
            "retired_at": retired_at.isoformat().replace("+00:00", "Z"),
            "grace_until": grace_until.isoformat().replace("+00:00", "Z"),
        }
    }


def _runtime_payload(proof: retention.RuntimeProof) -> dict[str, object]:
    assert proof.project is not None
    return {
        "schema": retention.RUNTIME_RECEIPT_SCHEMA,
        "status": "pass",
        "observed_at": proof.observed_at.isoformat().replace("+00:00", "Z"),
        "image": proof.image,
        "image_id": proof.image_id,
        "image_source_revision": proof.revision,
        "runtime_source_revision": proof.revision,
        "candidate_api_container_id": proof.api_container_id,
        "candidate_port": proof.port,
        "compose_project": proof.project,
        "candidate_container_images": {
            "api": {
                "container_id": proof.api_container_id,
                "image_id": proof.image_id,
            },
            "gateway": {
                "container_id": proof.gateway_container_id,
                "image_id": proof.image_id,
            },
        },
        "candidate_named_resources": retention._expected_named_resources(
            proof.project
        ),
        "projection_tree_revalidated": True,
        "first_smoke_checks": ["healthz"],
        "second_smoke_checks": ["healthz"],
        "contribution_survived_restart": True,
        "candidate_left_running_for_soak": True,
        "live_ea_api_unchanged": True,
        "promotion_authority": False,
    }


def _with_environment_file(
    inventory: retention.Inventory,
    project: str,
    environment_file: Path,
) -> retention.Inventory:
    containers = [copy.deepcopy(row) for row in inventory.containers]
    for container in containers:
        if container.get("project") == project:
            container["labels"][retention.COMPOSE_ENVIRONMENT_FILE_LABEL] = str(
                environment_file
            )
    return retention.Inventory(
        containers=tuple(containers),
        networks=inventory.networks,
        volumes=inventory.volumes,
        images=inventory.images,
    )


def _write_automatic_runtime_receipt(
    tmp_path: Path, proof: retention.RuntimeProof
) -> tuple[Path, Path]:
    deployment = (tmp_path / str(proof.project)).resolve()
    receipts = deployment / "receipts"
    receipts.mkdir(parents=True, mode=0o700)
    environment_file = deployment / "candidate.env"
    receipt = receipts / "candidate-runtime-v3.json"
    receipt.write_text(json.dumps(_runtime_payload(proof)) + "\n", encoding="utf-8")
    receipt.chmod(0o600)
    return environment_file, receipt


def _raw_image(proof: retention.RuntimeProof) -> dict[str, object]:
    return {
        "Id": proof.image_id,
        "RepoTags": [proof.image],
        "RepoDigests": [],
        "Config": {
            "Labels": {"org.opencontainers.image.revision": proof.revision},
            "Env": [f"EA_SOURCE_REVISION={proof.revision}"],
        },
    }


def test_network_normalizer_preserves_bool_and_rejects_missing_or_non_bool() -> None:
    raw = {
        "Id": "1" * 64,
        "Name": "candidate_backend",
        "Labels": {},
        "Driver": "bridge",
        "Internal": True,
        "Attachable": True,
        "Containers": {},
    }
    assert retention._normalize_network(raw)["attachable"] is True

    missing = dict(raw)
    missing.pop("Attachable")
    with pytest.raises(RuntimeError, match="network_attachable_invalid"):
        retention._normalize_network(missing)
    for malformed in (None, 0, 1, "false", {}, []):
        with pytest.raises(RuntimeError, match="network_attachable_invalid"):
            retention._normalize_network({**raw, "Attachable": malformed})


def test_image_normalizer_strictly_preserves_repo_digests() -> None:
    digest = "registry.example/ea-runtime@sha256:" + "a" * 64
    raw = {
        "Id": OLD_IMAGE,
        "RepoTags": [f"ea-runtime:manfred-{OLD_REVISION}"],
        "RepoDigests": [digest],
        "Config": {"Labels": {}, "Env": []},
    }
    assert retention._normalize_image(raw)["repo_digests"] == (digest,)
    assert retention._normalize_image({**raw, "RepoDigests": None})[
        "repo_digests"
    ] == ()

    missing = dict(raw)
    missing.pop("RepoDigests")
    malformed_values = (
        "not-a-list",
        [digest, digest],
        ["missing-at-digest"],
        [123],
    )
    with pytest.raises(RuntimeError, match="image_repo_digests_invalid"):
        retention._normalize_image(missing)
    for malformed in malformed_values:
        with pytest.raises(RuntimeError, match="image_repo_digests_invalid"):
            retention._normalize_image({**raw, "RepoDigests": malformed})


def test_managed_candidate_requires_non_attachable_networks() -> None:
    old, new = _pair()
    inventory = _inventory(old, new)
    for replacement in (True, None):
        networks = [copy.deepcopy(row) for row in inventory.networks]
        target = next(
            row
            for row in networks
            if row.get("project") == OLD_PROJECT
            and row.get("network") == "backend"
        )
        if replacement is None:
            target.pop("attachable")
        else:
            target["attachable"] = replacement
        with pytest.raises(RuntimeError, match="network_contract_invalid"):
            retention._build_plan(
                (old, new),
                retention.Inventory(
                    inventory.containers,
                    tuple(networks),
                    inventory.volumes,
                    inventory.images,
                ),
                now=NOW,
                root_free_bytes=34 * 1024**3,
            )


def test_plan_keeps_newest_v3_quarantines_legacy_and_preserves_recent_image() -> None:
    old, new = _pair()
    plan = retention._build_plan(
        (old, new),
        _inventory(old, new, legacy=True),
        now=NOW,
        root_free_bytes=34 * 1024**3,
    )
    assert plan.keeper.project == NEW_PROJECT
    assert [candidate.project for candidate in plan.retirees] == [OLD_PROJECT]
    assert plan.removable_image_ids == ()
    assert plan.preserved_images == (
        {"image_id": OLD_IMAGE, "reason": "post_retirement_grace_pending"},
    )
    assert plan.grace_candidates == (
        {
            "image_id": OLD_IMAGE,
            "projects": [OLD_PROJECT],
            "receipt_sha256": [old.receipt_sha256],
            "renew": False,
        },
    )
    assert plan.quarantined_projects[0]["project"] == retention.LEGACY_COMPOSE_PROJECT
    assert plan.quarantined_projects[0]["automatic_retirement_authorized"] is False


def test_plan_allows_only_strictly_older_receipts() -> None:
    old, new = _pair()
    tied = retention.RuntimeProof(**{**old.__dict__, "observed_at": new.observed_at})
    with pytest.raises(RuntimeError, match="proof_order_ambiguous"):
        retention._build_plan(
            (tied, new),
            _inventory(tied, new),
            now=NOW,
            root_free_bytes=34 * 1024**3,
        )


def test_unregistered_candidate_project_is_quarantined_without_blocking_keeper() -> None:
    old, new = _pair()
    unknown = _proof(
        "ea-manfred-candidate-orphan-abcdef",
        "c" * 40,
        "sha256:" + "c" * 64,
        NOW - timedelta(hours=3),
        18093,
    )
    inventory = _inventory_for_proofs((old, new, unknown))
    assert unknown.project is not None
    quarantine = retention._unregistered_project_quarantine(
        {unknown.project}, inventory
    )
    plan = retention._build_plan(
        (old, new),
        inventory,
        now=NOW,
        root_free_bytes=34 * 1024**3,
        excluded_projects={unknown.project},
        unknown_project_quarantine=quarantine,
    )

    assert plan.keeper.project == NEW_PROJECT
    assert plan.unknown_project_quarantine == quarantine
    assert quarantine[0]["automatic_retirement_authorized"] is False
    assert quarantine[0]["operator_action_required"] is True
    assert unknown.project not in json.dumps(retention._mutation_targets(plan))


def test_apply_auto_enrolls_old_memorial_receipt_and_stability_blocks_docker_retirement(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    managed = _proof(
        NEW_PROJECT,
        NEW_REVISION,
        NEW_IMAGE,
        NOW - timedelta(hours=2),
        18092,
    )
    project = "ea-manfred-candidate-autoenroll-abcdef"
    automatic = replace(
        _proof(
            project,
            "c" * 40,
            "sha256:" + "c" * 64,
            NOW - timedelta(hours=1),
            18093,
        ),
        image="ea-runtime:memorial-" + "c" * 40,
    )
    _managed_env, managed_receipt = _write_automatic_runtime_receipt(
        tmp_path, managed
    )
    automatic_env, automatic_receipt = _write_automatic_runtime_receipt(
        tmp_path, automatic
    )
    registry_path = tmp_path / "registry.json"
    registry.register_candidate_receipt(
        managed_receipt, registry_path=registry_path
    )
    inventory = _with_environment_file(
        _inventory_for_proofs((managed, automatic)),
        project,
        automatic_env,
    )
    real_auto_enroll = retention._auto_enroll_unregistered_projects
    real_build_plan = retention._build_plan
    monkeypatch.setattr(
        retention,
        "_auto_enroll_unregistered_projects",
        lambda projects, observed, **kwargs: real_auto_enroll(
            projects, observed, now=NOW, **kwargs
        ),
    )
    monkeypatch.setattr(
        retention,
        "_build_plan",
        lambda proofs, observed, **kwargs: real_build_plan(
            proofs,
            observed,
            now=NOW,
            root_free_bytes=34 * 1024**3,
            **{key: value for key, value in kwargs.items() if key != "now"},
        ),
    )
    monkeypatch.setattr(
        retention,
        "hold_candidate_fleet_lock",
        lambda **_kwargs: _lock({"scope": "fleet"}),
    )
    monkeypatch.setattr(
        retention,
        "_hold_retention_resource_locks",
        lambda proofs: _lock([{"projects": sorted(proofs)}]),
    )
    monkeypatch.setattr(retention, "_discover_inventory", lambda _ids: inventory)
    monkeypatch.setattr(retention, "_inspect", lambda kind, ids: [_raw_image(automatic)])
    monkeypatch.setattr(
        retention,
        "_existing_image_ids",
        lambda: {managed.image_id, automatic.image_id},
    )
    monkeypatch.setattr(retention, "_assert_keeper_http", lambda _proof: None)
    monkeypatch.setattr(
        retention,
        "_record_stability_sample",
        lambda *_args, **_kwargs: {
            "sample_count": 1,
            "sample_span_seconds": 0,
            "qualified": False,
        },
    )
    monkeypatch.setattr(retention, "_atomic_receipt", lambda *_args: None)
    monkeypatch.setattr(
        retention,
        "_apply_plan",
        lambda *_args, **_kwargs: pytest.fail(
            "automatic enrollment bypassed persistent stability"
        ),
    )

    receipt = retention.retain_candidates(
        runtime_receipts=[],
        output_receipt=tmp_path / "retention.json",
        apply=True,
        state_path=tmp_path / "state.json",
        registry_path=registry_path,
    )

    audit = receipt["automatic_candidate_enrollment"]
    assert audit["enrolled_project_count"] == 1
    assert audit["enrolled_projects"][0]["project"] == project
    assert receipt["plan"]["keeper"]["project"] == project
    assert receipt["plan"]["unknown_project_quarantine"] == []
    assert receipt["action"] == "stabilizing"
    assert receipt["mutations_performed"] == 0
    assert set(registry.registered_candidate_receipts(registry_path=registry_path)) == {
        managed_receipt,
        automatic_receipt,
    }


def test_auto_enrollment_defers_young_proof_without_docker_or_registry_mutation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    project = "ea-manfred-candidate-youngproof-abcdef"
    proof = replace(
        _proof(
            project,
            "d" * 40,
            "sha256:" + "d" * 64,
            NOW - timedelta(minutes=10),
            18093,
        ),
        image="ea-runtime:memorial-" + "d" * 40,
    )
    environment_file, _receipt = _write_automatic_runtime_receipt(tmp_path, proof)
    inventory = _with_environment_file(
        _inventory_for_proofs((proof,)), project, environment_file
    )
    monkeypatch.setattr(
        retention,
        "_inspect",
        lambda *_args: pytest.fail("young proof reached Docker validation"),
    )
    monkeypatch.setattr(
        retention,
        "register_candidate_receipt",
        lambda *_args, **_kwargs: pytest.fail("young proof mutated registry"),
    )

    audit = retention._auto_enroll_unregistered_projects(
        {project},
        inventory,
        registry_path=tmp_path / "registry.json",
        apply=True,
        now=NOW,
    )

    assert audit["enrolled_projects"] == []
    assert audit["invalid_projects"] == []
    assert audit["deferred_projects"][0]["reason"] == "runtime_proof_stabilizing"
    assert audit["deferred_projects"][0]["proof_age_seconds"] == 600


def test_auto_enrollment_rejects_naive_clock_before_side_effects(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        RuntimeError,
        match="manfred_candidate_retention_auto_enrollment_clock_invalid",
    ):
        retention._auto_enroll_unregistered_projects(
            set(),
            retention.Inventory((), (), (), {}),
            registry_path=tmp_path / "registry.json",
            apply=True,
            now=datetime(2026, 7, 13, 14, 45),
        )
    assert not (tmp_path / "registry.json").exists()


def test_auto_enrollment_dry_run_validates_but_never_registers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    project = "ea-manfred-candidate-dryrun-abcdef12"
    proof = replace(
        _proof(
            project,
            "e" * 40,
            "sha256:" + "e" * 64,
            NOW - timedelta(hours=1),
            18093,
        ),
        image="ea-runtime:memorial-" + "e" * 40,
    )
    environment_file, _receipt = _write_automatic_runtime_receipt(tmp_path, proof)
    inventory = _with_environment_file(
        _inventory_for_proofs((proof,)), project, environment_file
    )
    monkeypatch.setattr(retention, "_inspect", lambda _kind, _ids: [_raw_image(proof)])
    monkeypatch.setattr(retention, "_assert_keeper_http", lambda _proof: None)
    monkeypatch.setattr(
        retention,
        "register_candidate_receipt",
        lambda *_args, **_kwargs: pytest.fail("dry-run mutated registry"),
    )

    audit = retention._auto_enroll_unregistered_projects(
        {project},
        inventory,
        registry_path=tmp_path / "registry.json",
        apply=False,
        now=NOW,
    )

    assert audit["enrolled_projects"] == []
    assert audit["invalid_projects"] == []
    assert audit["deferred_projects"][0]["reason"] == (
        "apply_required_for_auto_enrollment"
    )
    assert not (tmp_path / "registry.json").exists()


def test_auto_enrollment_missing_invalid_and_mismatched_proofs_stay_quarantined(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    project = "ea-manfred-candidate-invalidproof-abcdef"
    proof = _proof(
        project,
        "f" * 40,
        "sha256:" + "f" * 64,
        NOW - timedelta(hours=1),
        18093,
    )
    base_inventory = _inventory_for_proofs((proof,))

    missing_env = (tmp_path / "missing" / "candidate.env").resolve()
    missing = retention._auto_enroll_unregistered_projects(
        {project},
        _with_environment_file(base_inventory, project, missing_env),
        registry_path=tmp_path / "missing-registry.json",
        apply=True,
        now=NOW,
    )
    assert missing["deferred_projects"][0]["reason"] == "runtime_receipt_missing"

    malformed_env, malformed_receipt = _write_automatic_runtime_receipt(
        tmp_path / "malformed", proof
    )
    malformed_receipt.write_text("not-json\n", encoding="utf-8")
    malformed_receipt.chmod(0o600)
    malformed = retention._auto_enroll_unregistered_projects(
        {project},
        _with_environment_file(base_inventory, project, malformed_env),
        registry_path=tmp_path / "malformed-registry.json",
        apply=True,
        now=NOW,
    )
    assert "receipt_json_invalid" in malformed["invalid_projects"][0]["reason"]

    mismatch_env, mismatch_receipt = _write_automatic_runtime_receipt(
        tmp_path / "mismatch", proof
    )
    other = replace(proof, project="ea-manfred-candidate-otherproof-abcdef")
    mismatch_receipt.write_text(
        json.dumps(_runtime_payload(other)) + "\n", encoding="utf-8"
    )
    mismatch_receipt.chmod(0o600)
    mismatch = retention._auto_enroll_unregistered_projects(
        {project},
        _with_environment_file(base_inventory, project, mismatch_env),
        registry_path=tmp_path / "mismatch-registry.json",
        apply=True,
        now=NOW,
    )
    assert "project_mismatch" in mismatch["invalid_projects"][0]["reason"]

    ambiguous = _with_environment_file(base_inventory, project, mismatch_env)
    containers = [copy.deepcopy(row) for row in ambiguous.containers]
    next(row for row in containers if row.get("project") == project)["labels"][
        retention.COMPOSE_ENVIRONMENT_FILE_LABEL
    ] = str((tmp_path / "other" / "candidate.env").resolve())
    ambiguous_inventory = retention.Inventory(
        tuple(containers), ambiguous.networks, ambiguous.volumes, ambiguous.images
    )
    ambiguous_audit = retention._auto_enroll_unregistered_projects(
        {project},
        ambiguous_inventory,
        registry_path=tmp_path / "ambiguous-registry.json",
        apply=True,
        now=NOW,
    )
    assert "environment_file_ambiguous" in (
        ambiguous_audit["invalid_projects"][0]["reason"]
    )
    assert all(
        audit["enrolled_projects"] == []
        for audit in (missing, malformed, mismatch, ambiguous_audit)
    )


def test_retirement_and_image_removal_are_bounded_batches() -> None:
    proofs = _batch_proofs()
    plan = retention._build_plan(
        proofs,
        _inventory_for_proofs(proofs),
        now=NOW,
        root_free_bytes=34 * 1024**3,
    )
    assert len(plan.retirees) == retention.MAX_RETIRE_PROJECTS_PER_RUN
    assert [candidate.project for candidate in plan.retirees] == [
        str(proof.project) for proof in proofs[:4]
    ]
    assert [candidate.project for candidate in plan.pending_retirees] == [
        str(proof.project) for proof in proofs[4:6]
    ]
    mutation_targets = json.dumps(retention._mutation_targets(plan))
    assert all(str(proof.project) not in mutation_targets for proof in proofs[4:])

    keeper = proofs[-1]
    expired_ledger: dict[str, dict[str, object]] = {}
    for proof in proofs[:-1]:
        expired_ledger.update(
            _retired_ledger(
                proof,
                retired_at=NOW
                - timedelta(
                    seconds=retention.RETIRED_IMAGE_LEDGER_WINDOW_SECONDS + 1
                ),
            )
        )
    historical = retention._build_plan(
        proofs,
        _inventory_for_proofs(
            proofs, active_projects={str(keeper.project)}
        ),
        now=NOW,
        root_free_bytes=0,
        retired_images=expired_ledger,
    )
    assert len(historical.removable_image_ids) == retention.MAX_REMOVE_IMAGES_PER_RUN
    assert len(
        [row for row in historical.preserved_images if row["reason"] == "image_batch_limit"]
    ) == 2
    assert set(historical.deferred_image_projects) == {
        str(proof.project) for proof in proofs[4:6]
    }


def test_plan_requires_newest_complete_healthy_and_bootstraps_mature_anchor() -> None:
    old, new = _pair()
    inventory = _inventory(old, new)
    containers = [dict(row) for row in inventory.containers]
    next(row for row in containers if row.get("project") == NEW_PROJECT and row.get("service") == "gateway")[
        "health"
    ] = "unhealthy"
    unhealthy = retention.Inventory(tuple(containers), inventory.networks, inventory.volumes, inventory.images)
    with pytest.raises(RuntimeError, match="newest_candidate_unhealthy"):
        retention._build_plan(
            (old, new), unhealthy, now=NOW, root_free_bytes=34 * 1024**3
        )

    stabilizing = retention.RuntimeProof(
        **{**new.__dict__, "observed_at": NOW - timedelta(minutes=10)}
    )
    protected = retention._build_plan(
        (old, stabilizing),
        _inventory(old, stabilizing),
        now=NOW,
        root_free_bytes=34 * 1024**3,
    )
    assert protected.keeper.project == old.project
    assert protected.actual_newest.project == stabilizing.project
    assert protected.keeper_selection == "newest_mature_bootstrap"
    assert protected.retirees == ()
    assert protected.protected_newer_candidates == (
        retention._validate_candidate(
            str(stabilizing.project),
            stabilizing,
            _inventory(old, stabilizing),
        ),
    )
    assert stabilizing.project not in json.dumps(
        retention._mutation_targets(protected)
    )

    with pytest.raises(RuntimeError, match="keeper_stabilizing"):
        retention._build_plan(
            (stabilizing,),
            _inventory_for_proofs((stabilizing,)),
            now=NOW,
            root_free_bytes=34 * 1024**3,
        )

    future = replace(
        new,
        observed_at=NOW + timedelta(seconds=1),
    )
    with pytest.raises(RuntimeError, match="keeper_clock_regressed"):
        retention._build_plan(
            (old, future),
            _inventory(old, future),
            now=NOW,
            root_free_bytes=34 * 1024**3,
        )


def test_strictly_older_degraded_candidate_remains_bounded_retirement_target() -> None:
    old, new = _pair()
    inventory = _inventory(old, new)
    containers = [dict(row) for row in inventory.containers]
    next(
        row
        for row in containers
        if row.get("project") == OLD_PROJECT
        and row.get("service") == "gateway"
    )["health"] = "unhealthy"
    degraded = retention.Inventory(
        tuple(containers),
        inventory.networks,
        inventory.volumes,
        inventory.images,
    )
    plan = retention._build_plan(
        (old, new),
        degraded,
        now=NOW,
        root_free_bytes=34 * 1024**3,
    )
    assert plan.keeper.project == NEW_PROJECT
    assert [candidate.project for candidate in plan.retirees] == [OLD_PROJECT]
    assert plan.retirees[0].healthy is False
    targets = retention._mutation_targets(plan)
    assert set(targets["container_ids"]) == {
        str(row["id"]) for row in plan.retirees[0].containers
    }


def test_plan_fails_closed_on_unexpected_compose_label_or_external_volume_user() -> None:
    old, new = _pair()
    inventory = _inventory(old, new)
    containers = [copy.deepcopy(row) for row in inventory.containers]
    target = next(row for row in containers if row.get("project") == OLD_PROJECT)
    target["labels"]["com.docker.compose.unexpected"] = "unsafe"
    hostile = retention.Inventory(tuple(containers), inventory.networks, inventory.volumes, inventory.images)
    with pytest.raises(RuntimeError, match="resource_labels_invalid"):
        retention._build_plan(
            (old, new), hostile, now=NOW, root_free_bytes=34 * 1024**3
        )

    containers = [copy.deepcopy(row) for row in inventory.containers]
    containers.append(
        {
            "id": "f" * 64,
            "name": "unrelated",
            "image_id": "sha256:" + "f" * 64,
            "project": "",
            "service": "",
            "mounts": (
                {
                    "type": "volume",
                    "name": f"{OLD_PROJECT}_artifacts",
                    "destination": "/data",
                },
            ),
        }
    )
    hostile = retention.Inventory(tuple(containers), inventory.networks, inventory.volumes, inventory.images)
    with pytest.raises(RuntimeError, match="volume_external_user"):
        retention._build_plan(
            (old, new), hostile, now=NOW, root_free_bytes=34 * 1024**3
        )


def test_image_is_removed_only_after_grace_and_without_other_references() -> None:
    old, new = _pair()
    inventory = _inventory(old, new)
    expired_while_active = retention._build_plan(
        (old, new),
        inventory,
        now=NOW
        + timedelta(seconds=retention.RETIRED_IMAGE_LEDGER_WINDOW_SECONDS + 1),
        root_free_bytes=34 * 1024**3,
        retired_images=_retired_ledger(old),
    )
    assert expired_while_active.removable_image_ids == ()
    assert expired_while_active.grace_candidates[0]["renew"] is True

    low_disk_without_ledger = retention._build_plan(
        (old, new),
        inventory,
        now=NOW,
        root_free_bytes=0,
    )
    assert low_disk_without_ledger.removable_image_ids == ()
    assert low_disk_without_ledger.grace_candidates[0]["renew"] is False
    assert low_disk_without_ledger.preserved_images == (
        {"image_id": OLD_IMAGE, "reason": "post_retirement_grace_pending"},
    )

    without_old_stack = retention.Inventory(
        tuple(row for row in inventory.containers if row.get("project") != OLD_PROJECT),
        tuple(row for row in inventory.networks if row.get("project") != OLD_PROJECT),
        tuple(row for row in inventory.volumes if row.get("project") != OLD_PROJECT),
        inventory.images,
    )
    plan = retention._build_plan(
        (old, new),
        without_old_stack,
        now=NOW
        + timedelta(seconds=retention.RETIRED_IMAGE_LEDGER_WINDOW_SECONDS + 1),
        root_free_bytes=34 * 1024**3,
        retired_images=_retired_ledger(old),
    )
    assert plan.removable_image_ids == (OLD_IMAGE,)

    containers = list(inventory.containers)
    containers = [row for row in containers if row.get("project") != OLD_PROJECT]
    containers.append(
        {
            "id": "f" * 64,
            "name": "noncandidate-image-user",
            "image_id": OLD_IMAGE,
            "project": "",
            "service": "",
            "mounts": (),
        }
    )
    referenced = retention.Inventory(
        tuple(containers),
        without_old_stack.networks,
        without_old_stack.volumes,
        inventory.images,
    )
    plan = retention._build_plan(
        (old, new),
        referenced,
        now=NOW
        + timedelta(seconds=retention.RETIRED_IMAGE_LEDGER_WINDOW_SECONDS + 1),
        root_free_bytes=34 * 1024**3,
        retired_images=_retired_ledger(old),
    )
    assert plan.removable_image_ids == ()
    assert plan.preserved_images == (
        {"image_id": OLD_IMAGE, "reason": "nonretired_container_reference"},
    )


def test_repo_digest_alias_always_preserves_managed_image() -> None:
    old, new = _pair()
    inventory = _inventory(old, new)
    images = copy.deepcopy(inventory.images)
    images[OLD_IMAGE]["repo_digests"] = (
        "registry.example/ea-runtime@sha256:" + "c" * 64,
    )
    without_old_stack = retention.Inventory(
        tuple(row for row in inventory.containers if row.get("project") != OLD_PROJECT),
        tuple(row for row in inventory.networks if row.get("project") != OLD_PROJECT),
        tuple(row for row in inventory.volumes if row.get("project") != OLD_PROJECT),
        images,
    )
    plan = retention._build_plan(
        (old, new),
        without_old_stack,
        now=NOW
        + timedelta(seconds=retention.RETIRED_IMAGE_LEDGER_WINDOW_SECONDS + 1),
        root_free_bytes=0,
        retired_images=_retired_ledger(old),
    )
    assert plan.removable_image_ids == ()
    assert plan.preserved_images == (
        {"image_id": OLD_IMAGE, "reason": "repo_digest_aliases"},
    )
    assert plan.deferred_image_projects == (OLD_PROJECT,)


def test_absent_historical_stack_image_remains_managed_through_grace() -> None:
    old, new = _pair()
    inventory = _inventory(old, new)
    without_old_stack = retention.Inventory(
        tuple(row for row in inventory.containers if row.get("project") != OLD_PROJECT),
        tuple(row for row in inventory.networks if row.get("project") != OLD_PROJECT),
        tuple(row for row in inventory.volumes if row.get("project") != OLD_PROJECT),
        inventory.images,
    )
    grace = retention._build_plan(
        (old, new),
        without_old_stack,
        now=NOW,
        root_free_bytes=34 * 1024**3,
    )
    assert grace.retirees == ()
    assert grace.removable_image_ids == ()
    assert grace.deferred_image_projects == (OLD_PROJECT,)
    assert grace.preserved_images == (
        {"image_id": OLD_IMAGE, "reason": "post_retirement_grace_pending"},
    )

    active_grace = retention._build_plan(
        (old, new),
        without_old_stack,
        now=NOW + timedelta(hours=1),
        root_free_bytes=34 * 1024**3,
        retired_images=_retired_ledger(old),
    )
    assert active_grace.preserved_images == (
        {"image_id": OLD_IMAGE, "reason": "24h_post_retirement_grace"},
    )

    expired = retention._build_plan(
        (old, new),
        without_old_stack,
        now=NOW
        + timedelta(seconds=retention.RETIRED_IMAGE_LEDGER_WINDOW_SECONDS + 1),
        root_free_bytes=34 * 1024**3,
        retired_images=_retired_ledger(old),
    )
    assert expired.retirees == ()
    assert expired.removable_image_ids == (OLD_IMAGE,)
    assert expired.deferred_image_projects == ()


def test_retired_image_ledger_survives_crash_and_renews_if_stack_remains(
    tmp_path: Path,
) -> None:
    old, new = _pair()
    inventory = _inventory(old, new)
    state = tmp_path / "retention-state.json"
    initial = retention._build_plan(
        (old, new),
        inventory,
        now=NOW,
        root_free_bytes=34 * 1024**3,
    )
    assert initial.grace_candidates[0]["renew"] is False
    staged = retention._update_retired_image_ledger(
        state,
        initial.grace_candidates,
        now=NOW,
    )
    assert retention._load_retired_image_ledger(state) == staged
    assert (
        retention._parse_timestamp(staged[OLD_IMAGE]["grace_until"]).timestamp()
        - retention._parse_timestamp(staged[OLD_IMAGE]["retired_at"]).timestamp()
        == retention.RETIRED_IMAGE_LEDGER_WINDOW_SECONDS
    )
    assert stat_mode(state) == 0o600

    crash_recovery_at = NOW + timedelta(
        seconds=retention.RETIRED_IMAGE_LEDGER_WINDOW_SECONDS + 1
    )
    still_active = retention._build_plan(
        (old, new),
        inventory,
        now=crash_recovery_at,
        root_free_bytes=34 * 1024**3,
        retired_images=staged,
    )
    assert still_active.removable_image_ids == ()
    assert still_active.grace_candidates[0]["renew"] is True
    renewed = retention._update_retired_image_ledger(
        state,
        still_active.grace_candidates,
        now=crash_recovery_at,
    )
    assert renewed[OLD_IMAGE]["retired_at"] == crash_recovery_at.isoformat().replace(
        "+00:00", "Z"
    )

    without_old_stack = _inventory_for_proofs(
        (old, new), active_projects={NEW_PROJECT}
    )
    before_grace = retention._build_plan(
        (old, new),
        without_old_stack,
        now=crash_recovery_at
        + timedelta(seconds=retention.RETIRED_IMAGE_LEDGER_WINDOW_SECONDS - 1),
        root_free_bytes=34 * 1024**3,
        retired_images=renewed,
    )
    assert before_grace.removable_image_ids == ()
    after_grace = retention._build_plan(
        (old, new),
        without_old_stack,
        now=crash_recovery_at
        + timedelta(seconds=retention.RETIRED_IMAGE_LEDGER_WINDOW_SECONDS + 1),
        root_free_bytes=34 * 1024**3,
        retired_images=renewed,
    )
    assert after_grace.removable_image_ids == (OLD_IMAGE,)


@contextlib.contextmanager
def _lock(value: object):
    yield value


def test_young_newest_bootstraps_anchor_without_docker_resource_mutation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    old, newest = _pair()
    young = replace(
        newest,
        observed_at=NOW - timedelta(minutes=10),
    )
    proofs = (old, young)
    inventory = _inventory(old, young)
    receipt_path = tmp_path / "retention.json"
    state_path = tmp_path / "state.json"
    http_probes: list[retention.RuntimeProof] = []
    discoveries: list[set[str]] = []
    compact_calls: list[set[str]] = []

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz: timezone | None = None) -> datetime:
            if tz is None:
                return NOW.replace(tzinfo=None)
            return NOW.astimezone(tz)

    def forbidden(name: str):
        def fail(*_args: object, **_kwargs: object) -> None:
            pytest.fail(f"young keeper reached {name}")

        return fail

    monkeypatch.setattr(retention, "datetime", FrozenDateTime)
    monkeypatch.setattr(retention, "_load_runtime_proofs", lambda _paths: proofs)
    monkeypatch.setattr(
        retention,
        "registered_candidate_receipts",
        lambda **_kwargs: [tmp_path / "old.json", tmp_path / "young.json"],
    )
    monkeypatch.setattr(
        retention,
        "registered_candidate_pending",
        lambda **_kwargs: [],
    )
    monkeypatch.setattr(
        retention,
        "register_candidate_receipt",
        forbidden("registry enrollment"),
    )
    monkeypatch.setattr(
        retention,
        "hold_candidate_fleet_lock",
        lambda **_kwargs: _lock({"scope": "fleet"}),
    )
    monkeypatch.setattr(
        retention,
        "_hold_retention_resource_locks",
        lambda _proofs: _lock([{"scope": "project-port"}]),
    )
    monkeypatch.setattr(
        retention,
        "_discover_inventory",
        lambda image_ids: discoveries.append(set(image_ids)) or inventory,
    )
    monkeypatch.setattr(
        retention,
        "_existing_image_ids",
        lambda: {OLD_IMAGE, NEW_IMAGE},
    )
    monkeypatch.setattr(
        retention,
        "_assert_keeper_http",
        lambda proof: http_probes.append(proof),
    )
    monkeypatch.setattr(
        retention,
        "_clear_expired_absent_pending",
        lambda *_args, **_kwargs: (),
    )
    monkeypatch.setattr(
        retention,
        "compact_candidate_registry",
        lambda projects, **_kwargs: compact_calls.append(set(projects))
        or {"after_count": len(projects)},
    )
    for name in ("_apply_plan", "_verify_after_apply"):
        monkeypatch.setattr(retention, name, forbidden(name))

    assert (
        retention.main(
            [
                "--receipt",
                str(receipt_path),
                "--state",
                str(state_path),
                "--registry",
                str(tmp_path / "registry.json"),
                "--apply",
            ]
        )
        == 0
    )
    stdout = json.loads(capsys.readouterr().out)
    persisted = json.loads(receipt_path.read_text(encoding="utf-8"))

    assert stdout == persisted
    assert persisted["status"] == "pass"
    assert persisted["action"] == "observed"
    assert persisted["apply_deferred"] is False
    assert persisted["mutations_performed"] == 0
    assert persisted["registry_activity"] == {
        "explicit": {
            "registration_attempted_count": 0,
            "registry_write_possible_count": 0,
            "registration_confirmed_count": 0,
            "registry_growth_confirmed_count": 0,
            "registry_growth_confirmation_available": False,
        },
        "automatic": {
            "registration_attempted_count": 0,
            "registry_write_possible_count": 0,
            "registration_confirmed_count": 0,
            "registry_growth_confirmed_count": 0,
            "registry_growth_confirmation_available": True,
        },
        "combined": {
            "registration_attempted_count": 0,
            "registry_write_possible_count": 0,
            "registration_confirmed_count": 0,
            "registry_growth_confirmed_count": 0,
            "exact_registry_write_count_reported": False,
        },
    }
    assert persisted["stability"]["sample_count"] == 1
    assert persisted["stability"]["qualified"] is False
    assert persisted["stability"]["sample_recorded"] is True
    assert persisted["plan"]["keeper"]["project"] == OLD_PROJECT
    assert persisted["plan"]["actual_newest"]["project"] == NEW_PROJECT
    assert persisted["plan"]["actual_newest_retirement_authorized"] is False
    assert [
        row["project"]
        for row in persisted["plan"]["protected_newer_candidates"]
    ] == [NEW_PROJECT]
    assert persisted["post_lock_inventory_revalidated"] is True
    assert persisted["plan"]["live_ea_before"]["healthy"] is True
    assert persisted["pending_registry_reconciliation"] == []
    assert http_probes == [old]
    assert discoveries == [set(), {OLD_IMAGE, NEW_IMAGE}]
    assert compact_calls == [{OLD_PROJECT, NEW_PROJECT}]
    assert stat.S_IMODE(receipt_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(state_path.stat().st_mode) == 0o600
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "retention.json",
        "state.json",
    ]
    with pytest.raises(RuntimeError, match="output_exists"):
        retention._atomic_receipt(receipt_path, {"status": "replacement"})


def test_young_keeper_discloses_preplanning_registry_growth_without_cleanup_mutations(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    old_unregistered = replace(
        _proof(
            "ea-manfred-candidate-old-unregistered-abcdef",
            "c" * 40,
            "sha256:" + "c" * 64,
            NOW - timedelta(hours=2),
            18093,
        ),
        image="ea-runtime:memorial-" + "c" * 40,
    )
    young_registered = replace(
        _proof(
            "ea-manfred-candidate-young-registered-abcdef",
            "d" * 40,
            "sha256:" + "d" * 64,
            NOW - timedelta(minutes=10),
            18094,
        ),
        image="ea-runtime:memorial-" + "d" * 40,
    )
    old_environment, old_receipt = _write_automatic_runtime_receipt(
        tmp_path, old_unregistered
    )
    _young_environment, young_receipt = _write_automatic_runtime_receipt(
        tmp_path, young_registered
    )
    registry_path = tmp_path / "registry.json"
    registry.register_candidate_receipt(
        young_receipt, registry_path=registry_path
    )
    registry_before = registry.registered_candidate_receipts(
        registry_path=registry_path
    )
    inventory = _with_environment_file(
        _inventory_for_proofs((old_unregistered, young_registered)),
        str(old_unregistered.project),
        old_environment,
    )
    inventory_before = copy.deepcopy(inventory)
    state_path = tmp_path / "state.json"
    http_probes: list[retention.RuntimeProof] = []

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz: timezone | None = None) -> datetime:
            if tz is None:
                return NOW.replace(tzinfo=None)
            return NOW.astimezone(tz)

    def forbidden(name: str):
        def fail(*_args: object, **_kwargs: object) -> None:
            pytest.fail(f"young keeper reached cleanup mutation lane {name}")

        return fail

    real_build_plan = retention._build_plan
    monkeypatch.setattr(retention, "datetime", FrozenDateTime)
    monkeypatch.setattr(
        retention,
        "hold_candidate_fleet_lock",
        lambda **_kwargs: _lock({"scope": "fleet"}),
    )
    monkeypatch.setattr(
        retention,
        "_hold_retention_resource_locks",
        lambda _proofs: _lock([{"scope": "project-port"}]),
    )
    monkeypatch.setattr(retention, "_discover_inventory", lambda _ids: inventory)
    monkeypatch.setattr(
        retention,
        "_inspect",
        lambda _kind, _ids: [_raw_image(old_unregistered)],
    )
    monkeypatch.setattr(
        retention,
        "_existing_image_ids",
        lambda: {old_unregistered.image_id, young_registered.image_id},
    )
    monkeypatch.setattr(
        retention,
        "_assert_keeper_http",
        lambda proof: http_probes.append(proof),
    )
    monkeypatch.setattr(
        retention,
        "_build_plan",
        lambda proofs, observed_inventory, **kwargs: real_build_plan(
            proofs,
            observed_inventory,
            root_free_bytes=34 * 1024**3,
            **kwargs,
        ),
    )
    monkeypatch.setattr(
        retention,
        "_clear_expired_absent_pending",
        lambda *_args, **_kwargs: (),
    )
    for name in ("_apply_plan", "_verify_after_apply"):
        monkeypatch.setattr(retention, name, forbidden(name))

    receipt = retention.retain_candidates(
        # Re-register the already enrolled keeper to exercise the explicit
        # idempotence-unknown accounting alongside confirmed automatic growth.
        runtime_receipts=[young_receipt],
        output_receipt=tmp_path / "retention.json",
        apply=True,
        state_path=state_path,
        registry_path=registry_path,
    )

    registry_after = registry.registered_candidate_receipts(
        registry_path=registry_path
    )
    assert registry_before == [young_receipt]
    assert set(registry_after) == {old_receipt, young_receipt}
    assert receipt["action"] == "observed"
    assert receipt["plan"]["keeper"]["project"] == old_unregistered.project
    assert receipt["plan"]["actual_newest"]["project"] == young_registered.project
    assert [
        row["project"]
        for row in receipt["plan"]["protected_newer_candidates"]
    ] == [young_registered.project]
    assert receipt["mutations_performed"] == 0
    assert receipt["automatic_candidate_enrollment"]["enrolled_project_count"] == 1
    assert receipt["registry_activity"] == {
        "explicit": {
            "registration_attempted_count": 1,
            "registry_write_possible_count": 1,
            "registration_confirmed_count": 1,
            "registry_growth_confirmed_count": 0,
            "registry_growth_confirmation_available": False,
        },
        "automatic": {
            "registration_attempted_count": 1,
            "registry_write_possible_count": 1,
            "registration_confirmed_count": 1,
            "registry_growth_confirmed_count": 1,
            "registry_growth_confirmation_available": True,
        },
        "combined": {
            "registration_attempted_count": 2,
            "registry_write_possible_count": 2,
            "registration_confirmed_count": 2,
            "registry_growth_confirmed_count": 1,
            "exact_registry_write_count_reported": False,
        },
    }
    assert receipt["pending_registry_reconciliation"] == []
    assert receipt["stability"]["sample_recorded"] is True
    assert receipt["stability"]["sample_count"] == 1
    assert state_path.exists()
    assert inventory == inventory_before
    assert [proof.project for proof in http_probes] == [
        old_unregistered.project,
        old_unregistered.project,
    ]


def test_young_keeper_state_clock_guard_rejects_future_persisted_state(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "state.json"
    future = NOW + timedelta(seconds=1)
    retention._mutable_private_json(
        state_path,
        {
            "schema": retention.STATE_SCHEMA,
            "updated_at": future.isoformat().replace("+00:00", "Z"),
            "identity_sha256": "a" * 64,
            "keeper_project": NEW_PROJECT,
            "samples": [
                {
                    "observed_at": future.isoformat().replace("+00:00", "Z"),
                    "identity_sha256": "a" * 64,
                }
            ],
            "qualified": False,
            "retired_images": {},
        },
    )

    with pytest.raises(RuntimeError, match="state_clock_regressed"):
        retention._assert_state_clock_not_regressed(state_path, now=NOW)


def test_dry_run_revalidates_after_all_locks_and_never_mutates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    old, new = _pair()
    historical = _proof(
        "ea-manfred-candidate-history1-000001",
        "8" * 40,
        "sha256:" + "8" * 64,
        NOW - timedelta(days=2),
        18093,
    )
    inventory = _inventory(old, new)
    discoveries: list[set[str]] = []
    written: list[dict[str, object]] = []
    monkeypatch.setattr(
        retention,
        "_load_runtime_proofs",
        lambda _paths: (historical, old, new),
    )
    monkeypatch.setattr(retention, "register_candidate_receipt", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        retention,
        "registered_candidate_receipts",
        lambda **_kwargs: [
            tmp_path / "historical.json",
            tmp_path / "old.json",
            tmp_path / "new.json",
        ],
    )
    monkeypatch.setattr(
        retention, "registered_candidate_pending", lambda **_kwargs: []
    )
    monkeypatch.setattr(
        retention,
        "hold_candidate_fleet_lock",
        lambda **_kwargs: _lock({"scope": "fleet"}),
    )
    monkeypatch.setattr(
        retention,
        "_hold_retention_resource_locks",
        lambda _proofs: _lock([{"scope": "project-port"}]),
    )
    monkeypatch.setattr(
        retention,
        "_discover_inventory",
        lambda ids: discoveries.append(set(ids)) or inventory,
    )
    monkeypatch.setattr(retention, "_existing_image_ids", lambda: {OLD_IMAGE, NEW_IMAGE})
    monkeypatch.setattr(retention, "_assert_keeper_http", lambda _proof: None)
    monkeypatch.setattr(
        retention,
        "_record_stability_sample",
        lambda *_args, **_kwargs: {
            "sample_count": 1,
            "sample_span_seconds": 0,
            "qualified": False,
        },
    )
    build_plan = retention._build_plan
    monkeypatch.setattr(
        retention,
        "_build_plan",
        lambda proofs, observed_inventory, **kwargs: build_plan(
            proofs,
            observed_inventory,
            now=NOW,
            root_free_bytes=34 * 1024**3,
            retired_images=kwargs.get("retired_images"),
            excluded_projects=kwargs.get("excluded_projects"),
            pending_intent_quarantine=kwargs.get(
                "pending_intent_quarantine", ()
            ),
        ),
    )
    monkeypatch.setattr(retention, "_atomic_receipt", lambda _path, payload: written.append(payload))
    monkeypatch.setattr(
        retention,
        "_apply_plan",
        lambda _plan: pytest.fail("dry-run reached mutation lane"),
    )
    receipt = retention.retain_candidates(
        runtime_receipts=[tmp_path / "old.json", tmp_path / "new.json"],
        output_receipt=tmp_path / "retention.json",
        apply=False,
    )
    assert len(discoveries) == 2
    assert discoveries[0] == set()
    assert discoveries[1] == {OLD_IMAGE, NEW_IMAGE}
    assert receipt["action"] == "planned"
    assert receipt["mutations_performed"] == 0
    assert receipt["post_lock_inventory_revalidated"] is True
    assert receipt["receipt_path"] == str((tmp_path / "retention.json").resolve())
    assert written == [receipt]


def test_busy_fleet_skips_before_any_docker_action(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    old, new = _pair()
    written: list[dict[str, object]] = []
    monkeypatch.setattr(retention, "_load_runtime_proofs", lambda _paths: (old, new))
    monkeypatch.setattr(
        retention,
        "hold_candidate_fleet_lock",
        lambda **_kwargs: _lock(None),
    )
    monkeypatch.setattr(
        retention,
        "_discover_inventory",
        lambda _ids: pytest.fail("busy fleet performed Docker discovery"),
    )
    monkeypatch.setattr(retention, "_atomic_receipt", lambda _path, payload: written.append(payload))
    receipt = retention.retain_candidates(
        runtime_receipts=[tmp_path / "old.json", tmp_path / "new.json"],
        output_receipt=tmp_path / "retention.json",
        apply=True,
    )
    assert receipt["status"] == "skipped"
    assert receipt["reason"] == "candidate_proof_active"
    assert receipt["mutations_performed"] == 0
    assert written == [receipt]


def test_absent_managed_projects_compact_historical_registry_without_docker_mutation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    live_containers, live_networks, live_volumes = _live_rows()
    inventory = retention.Inventory(
        tuple(live_containers), tuple(live_networks), tuple(live_volumes), {}
    )
    compact_calls: list[set[str]] = []
    monkeypatch.setattr(retention, "register_candidate_receipt", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(retention, "registered_candidate_receipts", lambda **_kwargs: [])
    monkeypatch.setattr(
        retention, "registered_candidate_pending", lambda **_kwargs: []
    )
    monkeypatch.setattr(
        retention,
        "_load_runtime_proofs",
        lambda _paths: pytest.fail("empty registry was parsed as a proof set"),
    )
    monkeypatch.setattr(
        retention,
        "hold_candidate_fleet_lock",
        lambda **_kwargs: _lock({"scope": "fleet"}),
    )
    monkeypatch.setattr(retention, "_discover_inventory", lambda _ids: inventory)
    monkeypatch.setattr(retention, "_existing_image_ids", lambda: {OLD_IMAGE, NEW_IMAGE})
    monkeypatch.setattr(
        retention,
        "compact_candidate_registry",
        lambda projects, **_kwargs: compact_calls.append(set(projects))
        or {"before_count": 12, "after_count": 0},
    )
    monkeypatch.setattr(retention, "_atomic_receipt", lambda *_args: None)
    monkeypatch.setattr(
        retention,
        "_apply_plan",
        lambda _plan: pytest.fail("no-active path reached Docker mutation"),
    )
    receipt = retention.retain_candidates(
        runtime_receipts=[],
        output_receipt=tmp_path / "retention.json",
        apply=True,
        state_path=tmp_path / "state.json",
        registry_path=tmp_path / "registry.json",
    )
    assert receipt["action"] == "no_active_managed_candidate"
    assert receipt["mutations_performed"] == 0
    assert compact_calls == [set()]


def test_absent_stack_preserves_proof_and_stages_historical_image_grace(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    old, _new = _pair()
    live_containers, live_networks, live_volumes = _live_rows()
    inventory = retention.Inventory(
        tuple(live_containers),
        tuple(live_networks),
        tuple(live_volumes),
        {OLD_IMAGE: _image(old)},
    )
    compact_calls: list[set[str]] = []
    monkeypatch.setattr(
        retention,
        "registered_candidate_receipts",
        lambda **_kwargs: [tmp_path / "old.json"],
    )
    monkeypatch.setattr(
        retention, "registered_candidate_pending", lambda **_kwargs: []
    )
    monkeypatch.setattr(retention, "_load_runtime_proofs", lambda _paths: (old,))
    monkeypatch.setattr(
        retention,
        "hold_candidate_fleet_lock",
        lambda **_kwargs: _lock({"scope": "fleet"}),
    )
    monkeypatch.setattr(retention, "_discover_inventory", lambda _ids: inventory)
    monkeypatch.setattr(retention, "_existing_image_ids", lambda: {OLD_IMAGE})
    monkeypatch.setattr(
        retention,
        "compact_candidate_registry",
        lambda projects, **_kwargs: compact_calls.append(set(projects))
        or {"after_count": 1},
    )
    monkeypatch.setattr(retention, "_atomic_receipt", lambda *_args: None)

    state = tmp_path / "state.json"
    receipt = retention.retain_candidates(
        runtime_receipts=[],
        output_receipt=tmp_path / "retention.json",
        apply=True,
        state_path=state,
        registry_path=tmp_path / "registry.json",
    )

    assert receipt["action"] == "historical_images_quarantined"
    assert receipt["historical_image_removal_authorized"] is False
    assert receipt["historical_image_quarantine"][0]["image_id"] == OLD_IMAGE
    assert compact_calls == [{OLD_PROJECT}]
    assert retention._load_retired_image_ledger(state)[OLD_IMAGE][
        "projects"
    ] == [OLD_PROJECT]


@pytest.mark.parametrize(
    ("qualified", "expected_action", "expected_apply_calls"),
    [(False, "stabilizing", 0), (True, "applied", 1)],
)
def test_apply_waits_for_real_samples_then_compacts_registry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    qualified: bool,
    expected_action: str,
    expected_apply_calls: int,
) -> None:
    old, new = _pair()
    inventory = _inventory(old, new)
    plan = retention._build_plan(
        (old, new),
        inventory,
        now=NOW,
        root_free_bytes=34 * 1024**3,
    )
    apply_calls: list[str] = []
    compact_calls: list[set[str]] = []
    monkeypatch.setattr(retention, "register_candidate_receipt", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        retention,
        "registered_candidate_receipts",
        lambda **_kwargs: [tmp_path / "old.json", tmp_path / "new.json"],
    )
    monkeypatch.setattr(
        retention, "registered_candidate_pending", lambda **_kwargs: []
    )
    monkeypatch.setattr(retention, "_load_runtime_proofs", lambda _paths: (old, new))
    monkeypatch.setattr(
        retention,
        "hold_candidate_fleet_lock",
        lambda **_kwargs: _lock({"scope": "fleet"}),
    )
    monkeypatch.setattr(
        retention,
        "_hold_retention_resource_locks",
        lambda _proofs: _lock([]),
    )
    monkeypatch.setattr(retention, "_discover_inventory", lambda _ids: inventory)
    monkeypatch.setattr(retention, "_existing_image_ids", lambda: {OLD_IMAGE, NEW_IMAGE})
    monkeypatch.setattr(
        retention, "_build_plan", lambda *_args, **_kwargs: plan
    )
    monkeypatch.setattr(retention, "_assert_keeper_http", lambda _proof: None)
    monkeypatch.setattr(
        retention,
        "_record_stability_sample",
        lambda *_args, **_kwargs: {
            "sample_count": 4 if qualified else 1,
            "sample_span_seconds": 900 if qualified else 0,
            "qualified": qualified,
        },
    )
    monkeypatch.setattr(
        retention,
        "_apply_plan",
        lambda _plan, **_kwargs: apply_calls.append("apply")
        or {"actions": [], "removed_image_ids": [], "preserved_images_at_apply": []},
    )
    monkeypatch.setattr(
        retention,
        "_verify_after_apply",
        lambda _plan: {"live_ea_unchanged": True},
    )
    monkeypatch.setattr(
        retention,
        "compact_candidate_registry",
        lambda projects, **_kwargs: compact_calls.append(set(projects))
        or {"after_count": 1},
    )
    monkeypatch.setattr(retention, "_atomic_receipt", lambda *_args: None)
    receipt = retention.retain_candidates(
        runtime_receipts=[],
        output_receipt=tmp_path / "retention.json",
        apply=True,
        state_path=tmp_path / "state.json",
        registry_path=tmp_path / "registry.json",
    )
    assert receipt["action"] == expected_action
    assert len(apply_calls) == expected_apply_calls
    assert compact_calls == ([{NEW_PROJECT, OLD_PROJECT}] if qualified else [])


def test_empty_target_apply_reconciles_crash_state_without_intent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _old, keeper = _pair()
    inventory = _inventory_for_proofs((keeper,))
    plan = retention._build_plan(
        (keeper,),
        inventory,
        now=NOW,
        root_free_bytes=34 * 1024**3,
    )
    assert plan.retirees == ()
    assert plan.removable_image_ids == ()
    compact_calls: list[set[str]] = []
    ledger_calls: list[dict[str, object]] = []
    receipt_paths: list[Path] = []

    monkeypatch.setattr(
        retention, "registered_candidate_receipts", lambda **_kwargs: [tmp_path / "keeper.json"]
    )
    monkeypatch.setattr(
        retention, "registered_candidate_pending", lambda **_kwargs: []
    )
    monkeypatch.setattr(retention, "_load_runtime_proofs", lambda _paths: (keeper,))
    monkeypatch.setattr(
        retention,
        "hold_candidate_fleet_lock",
        lambda **_kwargs: _lock({"scope": "fleet"}),
    )
    monkeypatch.setattr(
        retention, "_hold_retention_resource_locks", lambda _proofs: _lock([])
    )
    monkeypatch.setattr(retention, "_discover_inventory", lambda _ids: inventory)
    monkeypatch.setattr(retention, "_existing_image_ids", lambda: {NEW_IMAGE})
    monkeypatch.setattr(retention, "_build_plan", lambda *_args, **_kwargs: plan)
    monkeypatch.setattr(retention, "_assert_keeper_http", lambda _proof: None)
    monkeypatch.setattr(
        retention,
        "_record_stability_sample",
        lambda *_args, **_kwargs: {"qualified": True},
    )
    monkeypatch.setattr(
        retention,
        "_update_retired_image_ledger",
        lambda _path, updates, **kwargs: ledger_calls.append(
            {"updates": updates, **kwargs}
        )
        or {},
    )
    monkeypatch.setattr(
        retention,
        "compact_candidate_registry",
        lambda projects, **_kwargs: compact_calls.append(set(projects))
        or {"after_count": 1},
    )
    monkeypatch.setattr(
        retention,
        "_apply_plan",
        lambda *_args, **_kwargs: pytest.fail("empty target created mutation intent"),
    )
    monkeypatch.setattr(
        retention,
        "_atomic_receipt",
        lambda path, _payload: receipt_paths.append(Path(path)),
    )

    output = tmp_path / "retention.json"
    receipt = retention.retain_candidates(
        runtime_receipts=[],
        output_receipt=output,
        apply=True,
        state_path=tmp_path / "state.json",
        registry_path=tmp_path / "registry.json",
    )

    assert receipt["action"] == "observed"
    assert receipt["mutations_performed"] == 0
    assert compact_calls == [{NEW_PROJECT}]
    assert ledger_calls[0]["retain_image_ids"] == {NEW_IMAGE}
    assert receipt_paths == [output]


def test_apply_targets_only_retiree_exact_ids_and_preserves_grace_image(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old, new = _pair()
    plan = retention._build_plan(
        (old, new),
        _inventory(old, new),
        now=NOW,
        root_free_bytes=19 * 1024**3,
    )
    commands: list[list[str]] = []
    monkeypatch.setattr(
        retention,
        "_run",
        lambda argv, **_kwargs: commands.append(list(argv)) or b"",
    )
    monkeypatch.setattr(retention, "_listed", lambda _argv: [])
    execution = retention._apply_plan(plan, deadline_monotonic=10**18)
    assert execution["removed_image_ids"] == []
    assert ["docker", "image", "rm", OLD_IMAGE] not in commands
    flattened = json.dumps(commands)
    assert NEW_PROJECT not in flattened
    assert "ea-api" not in flattened
    assert "--force" in flattened
    assert "--volumes" not in flattened


def test_apply_deadline_expires_before_any_destructive_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old, new = _pair()
    plan = retention._build_plan(
        (old, new),
        _inventory(old, new),
        now=NOW,
        root_free_bytes=34 * 1024**3,
    )
    commands: list[list[str]] = []
    monkeypatch.setattr(retention.time, "monotonic", lambda: 100.0)
    monkeypatch.setattr(
        retention,
        "_run",
        lambda argv, **_kwargs: commands.append(list(argv)) or b"",
    )

    with pytest.raises(RuntimeError, match="apply_deadline_exceeded"):
        retention._apply_plan(plan, deadline_monotonic=100.5)

    assert commands == []


def test_apply_preserves_image_if_a_reference_appears_after_planning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old, new = _pair()
    inventory = _inventory(old, new)
    without_old_stack = retention.Inventory(
        tuple(row for row in inventory.containers if row.get("project") != OLD_PROJECT),
        tuple(row for row in inventory.networks if row.get("project") != OLD_PROJECT),
        tuple(row for row in inventory.volumes if row.get("project") != OLD_PROJECT),
        inventory.images,
    )
    plan = retention._build_plan(
        (old, new),
        without_old_stack,
        now=NOW
        + timedelta(seconds=retention.RETIRED_IMAGE_LEDGER_WINDOW_SECONDS + 1),
        root_free_bytes=0,
        retired_images=_retired_ledger(old),
    )
    commands: list[list[str]] = []
    monkeypatch.setattr(
        retention,
        "_run",
        lambda argv, **_kwargs: commands.append(list(argv)) or b"",
    )
    monkeypatch.setattr(retention, "_listed", lambda _argv: ["new-reference"])
    execution = retention._apply_plan(plan, deadline_monotonic=10**18)
    assert execution["removed_image_ids"] == []
    assert execution["preserved_images_at_apply"] == [
        {"image_id": OLD_IMAGE, "reason": "referenced_at_apply"}
    ]
    assert ["docker", "image", "rm", OLD_IMAGE] not in commands


@pytest.mark.parametrize("alias_kind", ["tag", "digest"])
def test_apply_rechecks_exact_image_aliases_before_removal(
    monkeypatch: pytest.MonkeyPatch,
    alias_kind: str,
) -> None:
    old, new = _pair()
    inventory = _inventory(old, new)
    without_old_stack = retention.Inventory(
        tuple(row for row in inventory.containers if row.get("project") != OLD_PROJECT),
        tuple(row for row in inventory.networks if row.get("project") != OLD_PROJECT),
        tuple(row for row in inventory.volumes if row.get("project") != OLD_PROJECT),
        inventory.images,
    )
    plan = retention._build_plan(
        (old, new),
        without_old_stack,
        now=NOW
        + timedelta(seconds=retention.RETIRED_IMAGE_LEDGER_WINDOW_SECONDS + 1),
        root_free_bytes=0,
        retired_images=_retired_ledger(old),
    )
    assert plan.removable_image_ids == (OLD_IMAGE,)
    observed = copy.deepcopy(plan.removable_image_aliases[0])
    if alias_kind == "tag":
        observed["repo_tags"].append("ea-runtime:unexpected-alias")
    else:
        observed["repo_digests"].append(
            "registry.example/ea-runtime@sha256:" + "d" * 64
        )
    commands: list[list[str]] = []
    monkeypatch.setattr(retention, "_listed", lambda _argv: [])
    monkeypatch.setattr(
        retention, "_inspect_image_alias_snapshot", lambda _image_id: observed
    )
    monkeypatch.setattr(
        retention,
        "_run",
        lambda argv, **_kwargs: commands.append(list(argv)) or b"",
    )
    execution = retention._apply_plan(plan, deadline_monotonic=10**18)
    assert execution["removed_image_ids"] == []
    assert execution["preserved_images_at_apply"] == [
        {"image_id": OLD_IMAGE, "reason": "image_alias_changed_at_apply"}
    ]
    assert ["docker", "image", "rm", OLD_IMAGE] not in commands


def test_receipt_loader_rejects_legacy_schema_symlinks_and_bad_modes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps({"schema": "ea.manfred_memorial_candidate_runtime.v2"}), encoding="utf-8")
    path.chmod(0o600)
    payload, digest = retention._read_receipt(path)
    with pytest.raises(RuntimeError, match="receipt_schema_invalid"):
        retention._parse_runtime_proof(payload, digest)

    link = tmp_path / "receipt-link.json"
    link.symlink_to(path)
    with pytest.raises(RuntimeError, match="receipt_path_invalid"):
        retention._read_receipt(link)

    path.chmod(0o644)
    with pytest.raises(RuntimeError, match="receipt_file_invalid"):
        retention._read_receipt(path)


@pytest.mark.parametrize(
    "schema",
    sorted(retention.RUNTIME_RECEIPT_SCHEMAS),
)
def test_retention_accepts_only_explicit_runtime_receipt_schemas(schema: str) -> None:
    old, _new = _pair()
    payload = _runtime_payload(old)
    payload["schema"] = schema

    parsed = retention._parse_runtime_proof(payload, old.receipt_sha256)

    assert parsed.schema == schema

    payload["schema"] = "ea.manfred_memorial_candidate_runtime.v5"
    with pytest.raises(RuntimeError, match="receipt_schema_invalid"):
        retention._parse_runtime_proof(payload, old.receipt_sha256)


@pytest.mark.parametrize("schema", sorted(registry.RUNTIME_SCHEMAS))
def test_registry_accepts_only_explicit_runtime_receipt_schemas(
    tmp_path: Path,
    schema: str,
) -> None:
    receipt = tmp_path / f"runtime-{schema.rsplit('.', 1)[-1]}.json"
    payload = {
        "schema": schema,
        "status": "pass",
        "compose_project": NEW_PROJECT,
        "observed_at": "2026-07-13T12:27:56Z",
        "image_id": NEW_IMAGE,
    }
    receipt.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    receipt.chmod(0o600)

    _payload, entry = registry._receipt_entry(receipt)

    assert entry["project"] == NEW_PROJECT

    payload["schema"] = "ea.manfred_memorial_candidate_runtime.v5"
    receipt.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    receipt.chmod(0o600)
    with pytest.raises(RuntimeError, match="registry_receipt_invalid"):
        registry._receipt_entry(receipt)


def test_runtime_v3_receipt_requires_full_revision_image_locator() -> None:
    old, _new = _pair()
    payload = _runtime_payload(old)
    parsed = retention._parse_runtime_proof(payload, old.receipt_sha256)
    assert parsed.image == f"ea-runtime:manfred-{OLD_REVISION}"
    retention._validate_image(parsed, _image(parsed))

    memorial = replace(old, image=f"ea-runtime:memorial-{OLD_REVISION}")
    payload = _runtime_payload(memorial)
    parsed = retention._parse_runtime_proof(payload, memorial.receipt_sha256)
    assert parsed.image == f"ea-runtime:memorial-{OLD_REVISION}"
    retention._validate_image(parsed, _image(parsed))

    payload["image"] = f"ea-runtime:manfred-{OLD_REVISION[:12]}"
    with pytest.raises(RuntimeError, match="receipt_invalid"):
        retention._parse_runtime_proof(payload, old.receipt_sha256)

    payload["image"] = f"ea-runtime:other-{OLD_REVISION}"
    with pytest.raises(RuntimeError, match="receipt_invalid"):
        retention._parse_runtime_proof(payload, old.receipt_sha256)


def test_runtime_v4_candidate_requires_immutable_container_image_id() -> None:
    old, _new = _pair()
    proof = replace(
        old,
        schema="ea.manfred_memorial_candidate_runtime.v4",
    )
    inventory = _inventory_for_proofs((proof,))
    containers = tuple(
        {
            **row,
            "image_ref": proof.image_id,
        }
        if row.get("project") == proof.project
        and row.get("service") in {"api", "gateway"}
        else row
        for row in inventory.containers
    )
    immutable_inventory = retention.Inventory(
        containers=containers,
        networks=inventory.networks,
        volumes=inventory.volumes,
        images=inventory.images,
    )

    candidate = retention._validate_candidate(
        str(proof.project),
        proof,
        immutable_inventory,
    )

    assert candidate.complete is True
    with pytest.raises(RuntimeError, match="container_image_invalid"):
        retention._validate_candidate(str(proof.project), proof, inventory)


def test_retention_receipt_is_mode_0600_and_immutable(tmp_path: Path) -> None:
    output = tmp_path / "retention.json"
    retention._atomic_receipt(output, {"schema": retention.RECEIPT_SCHEMA, "status": "pass"})
    assert stat_mode(output) == 0o600
    with pytest.raises(RuntimeError, match="output_exists"):
        retention._atomic_receipt(output, {"status": "replacement"})
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "pass"


def test_automatic_receipt_rotation_is_bounded_and_rejects_symlinks(
    tmp_path: Path,
) -> None:
    names = [
        f"retention-20260713T0000{index:02d}Z-1-deadbeef.json"
        for index in range(5)
    ]
    for name in names:
        path = tmp_path / name
        path.write_text("{}\n", encoding="utf-8")
        path.chmod(0o600)

    evidence = retention._rotate_automatic_receipts(
        tmp_path,
        preserve_names={names[-1]},
        maximum_receipts=3,
    )
    assert evidence == {
        "maximum_receipts": 3,
        "managed_before": 5,
        "removed_count": 2,
        "managed_after": 3,
    }
    assert sorted(path.name for path in tmp_path.iterdir()) == names[-3:]

    target = tmp_path / "unrelated.json"
    target.write_text("preserve\n", encoding="utf-8")
    target.chmod(0o600)
    link = tmp_path / "retention-20260713T000099Z-1-feedface.json"
    link.symlink_to(target)
    with pytest.raises(RuntimeError, match="receipt_rotation_invalid"):
        retention._rotate_automatic_receipts(
            tmp_path,
            maximum_receipts=3,
        )
    assert target.read_text(encoding="utf-8") == "preserve\n"

    bundle_directory = tmp_path / "bundles"
    bundle_directory.mkdir(mode=0o700)
    first = "retention-20260713T010000Z-1-11111111"
    second = "retention-20260713T020000Z-1-22222222"
    for name in (f"{first}.json", f"{first}.intent.json", f"{second}.json"):
        path = bundle_directory / name
        path.write_text("{}\n", encoding="utf-8")
        path.chmod(0o600)
    bundle_evidence = retention._rotate_automatic_receipts(
        bundle_directory,
        maximum_receipts=2,
    )
    assert bundle_evidence["removed_count"] == 2
    assert sorted(path.name for path in bundle_directory.iterdir()) == [
        f"{second}.json"
    ]


def test_stability_requires_real_spaced_persistent_samples(tmp_path: Path) -> None:
    old, new = _pair()
    plan = retention._build_plan(
        (old, new),
        _inventory(old, new),
        now=NOW,
        root_free_bytes=34 * 1024**3,
    )
    state = tmp_path / "stability.json"
    observations = [
        retention._record_stability_sample(
            state, plan, now=NOW + timedelta(minutes=offset)
        )
        for offset in (0, 5, 10, 15)
    ]
    assert [row["sample_count"] for row in observations] == [1, 2, 3, 4]
    assert [row["qualified"] for row in observations] == [False, False, False, True]
    assert observations[-1]["sample_span_seconds"] == 900
    assert stat_mode(state) == 0o600

    replaced_live = replace(
        plan,
        live_before={
            **plan.live_before,
            "digest_sha256": "0" * 64,
            "api_container_id": "f" * 64,
        },
    )
    preserved = retention._record_stability_sample(
        state, replaced_live, now=NOW + timedelta(minutes=20)
    )
    assert preserved["sample_count"] == 4
    assert preserved["qualified"] is True
    assert preserved["identity_sha256"] == observations[-1]["identity_sha256"]

    changed_network = dict(plan.keeper.networks[0])
    changed_network["id"] = "f" * 64
    changed_keeper = replace(
        plan.keeper,
        networks=(changed_network, *plan.keeper.networks[1:]),
    )
    changed_topology = replace(
        plan,
        keeper=changed_keeper,
        actual_newest=changed_keeper,
    )
    topology_state = tmp_path / "topology-stability.json"
    first_topology = retention._record_stability_sample(
        topology_state, plan, now=NOW
    )
    reset_topology = retention._record_stability_sample(
        topology_state,
        changed_topology,
        now=NOW + timedelta(minutes=5),
    )
    assert first_topology["sample_count"] == 1
    assert reset_topology["sample_count"] == 1
    assert (
        reset_topology["identity_sha256"]
        != first_topology["identity_sha256"]
    )


def test_five_minute_arrivals_do_not_reset_persisted_mature_anchor(
    tmp_path: Path,
) -> None:
    retiree = _proof(
        "ea-manfred-candidate-cadence-retiree-abcdef",
        "a" * 40,
        "sha256:" + "a" * 64,
        NOW - timedelta(hours=3),
        18200,
    )
    anchor = _proof(
        "ea-manfred-candidate-cadence-anchor-abcdef",
        "b" * 40,
        "sha256:" + "b" * 64,
        NOW - timedelta(hours=2),
        18201,
    )
    arrivals: list[retention.RuntimeProof] = []
    state = tmp_path / "cadence-state.json"
    observations: list[dict[str, object]] = []
    identities: list[str] = []

    for index, offset in enumerate((0, 5, 10, 15)):
        observed_now = NOW + timedelta(minutes=offset)
        arrival = _proof(
            f"ea-manfred-candidate-cadence-new-{index:02d}-abcdef",
            f"{index + 10:040x}",
            "sha256:" + f"{index + 10:064x}",
            observed_now,
            18210 + index,
        )
        arrivals.append(arrival)
        proofs = (retiree, anchor, *arrivals)
        inventory = _inventory_for_proofs(proofs)
        (
            retired_images,
            preferred_keeper,
            preferred_qualified,
            state_sha256,
        ) = retention._load_retention_state(state, now=observed_now)
        plan = retention._build_plan(
            proofs,
            inventory,
            now=observed_now,
            root_free_bytes=34 * 1024**3,
            retired_images=retired_images,
            preferred_keeper_project=preferred_keeper,
            preferred_keeper_qualified=preferred_qualified,
        )
        assert plan.keeper.project == anchor.project
        assert plan.actual_newest.project == arrival.project
        assert [candidate.project for candidate in plan.retirees] == [
            retiree.project
        ]
        assert [
            candidate.project for candidate in plan.protected_newer_candidates
        ] == [candidate.project for candidate in arrivals]
        targets = retention._mutation_targets(plan)
        protected_container_ids = {
            str(row["id"])
            for candidate in plan.protected_newer_candidates
            for row in candidate.containers
        }
        protected_network_ids = {
            str(row["id"])
            for candidate in plan.protected_newer_candidates
            for row in candidate.networks
        }
        protected_volume_names = {
            str(row["name"])
            for candidate in plan.protected_newer_candidates
            for row in candidate.volumes
        }
        assert protected_container_ids.isdisjoint(targets["container_ids"])
        assert protected_network_ids.isdisjoint(targets["network_ids"])
        assert protected_volume_names.isdisjoint(targets["volume_names"])
        assert all(
            candidate.image_id not in targets["eligible_image_ids"]
            for candidate in arrivals
        )
        identities.append(retention._stability_identity(plan))
        observations.append(
            retention._record_stability_sample(
                state,
                plan,
                now=observed_now,
                expected_state_sha256=state_sha256,
                state_prevalidated=True,
            )
        )

    assert len(set(identities)) == 1
    assert [row["sample_count"] for row in observations] == [1, 2, 3, 4]
    assert observations[-1]["qualified"] is True


def test_retiree_batch_turnover_does_not_reset_qualified_anchor() -> None:
    proofs = _batch_proofs(9)
    first = retention._build_plan(
        proofs,
        _inventory_for_proofs(proofs),
        now=NOW,
        root_free_bytes=34 * 1024**3,
    )
    assert [candidate.project for candidate in first.retirees] == [
        proof.project for proof in proofs[:4]
    ]
    remaining = tuple(
        proof
        for proof in proofs
        if proof.project
        not in {candidate.project for candidate in first.retirees}
    )
    second = retention._build_plan(
        remaining,
        _inventory_for_proofs(remaining),
        now=NOW + timedelta(minutes=5),
        root_free_bytes=34 * 1024**3,
        preferred_keeper_project=first.keeper.project,
        preferred_keeper_qualified=True,
    )
    assert [candidate.project for candidate in second.retirees] == [
        proof.project for proof in proofs[4:8]
    ]
    assert second.keeper == first.keeper
    assert retention._stability_identity(second) == retention._stability_identity(
        first
    )


def test_daylong_five_minute_cadence_recovers_after_skipped_ticks() -> None:
    active = list(_batch_proofs(9))
    preferred_keeper: str | None = None
    preferred_qualified = False
    identity: str | None = None
    consecutive_samples = 0
    last_sample_tick: int | None = None
    maximum_active = len(active)
    retired_total = 0
    arrival_count = 24 * 12

    for tick in range(arrival_count):
        observed_now = NOW + timedelta(minutes=5 * tick)
        arrival = _proof(
            f"ea-manfred-candidate-week-{tick:04d}-abcdef",
            f"{tick + 1000:040x}",
            "sha256:" + f"{tick + 1000:064x}",
            observed_now,
            20000 + tick,
        )
        active.append(arrival)
        maximum_active = max(maximum_active, len(active))

        # Model a recurring missed timer/lock-conflict tick.  The resulting
        # ten-minute observation gap is deliberately wider than the accepted
        # 7.5-minute sample gap and therefore resets qualification.
        if tick % 29 == 7:
            continue

        plan = retention._build_plan(
            tuple(active),
            _inventory_for_proofs(tuple(active)),
            now=observed_now,
            root_free_bytes=34 * 1024**3,
            preferred_keeper_project=preferred_keeper,
            preferred_keeper_qualified=preferred_qualified,
        )
        observed_identity = retention._stability_identity(plan)
        if (
            identity != observed_identity
            or last_sample_tick is None
            or tick - last_sample_tick > 1
        ):
            consecutive_samples = 0
        consecutive_samples += 1
        preferred_qualified = consecutive_samples >= 4
        preferred_keeper = plan.keeper.project
        identity = observed_identity
        last_sample_tick = tick

        if preferred_qualified and plan.retirees:
            retired_projects = {
                candidate.project for candidate in plan.retirees
            }
            active = [
                candidate
                for candidate in active
                if candidate.project not in retired_projects
            ]
            retired_total += len(retired_projects)

    assert retired_total >= arrival_count - 12
    assert maximum_active <= 20
    assert len(active) <= 16
    assert max(
        active,
        key=lambda candidate: candidate.observed_at,
    ).project.startswith("ea-manfred-candidate-week-")


def test_qualified_drained_anchor_rotates_without_inheriting_qualification(
    tmp_path: Path,
) -> None:
    retiree = _proof(
        "ea-manfred-candidate-rotate-retiree-abcdef",
        "c" * 40,
        "sha256:" + "c" * 64,
        NOW - timedelta(hours=3),
        18220,
    )
    anchor = _proof(
        "ea-manfred-candidate-rotate-anchor-abcdef",
        "d" * 40,
        "sha256:" + "d" * 64,
        NOW - timedelta(hours=2),
        18221,
    )
    state = tmp_path / "rotation-state.json"
    initial = retention._build_plan(
        (retiree, anchor),
        _inventory_for_proofs((retiree, anchor)),
        now=NOW,
        root_free_bytes=34 * 1024**3,
    )
    for offset in (0, 5, 10, 15):
        retention._record_stability_sample(
            state,
            initial,
            now=NOW + timedelta(minutes=offset),
        )
    successor = _proof(
        "ea-manfred-candidate-rotate-successor-abcdef",
        "e" * 40,
        "sha256:" + "e" * 64,
        NOW - timedelta(minutes=30),
        18222,
    )
    rotation_now = NOW + timedelta(minutes=20)
    (
        retired_images,
        preferred_keeper,
        preferred_qualified,
        state_sha256,
    ) = retention._load_retention_state(state, now=rotation_now)
    assert preferred_keeper == anchor.project
    assert preferred_qualified is True
    rotated = retention._build_plan(
        (anchor, successor),
        _inventory_for_proofs((anchor, successor)),
        now=rotation_now,
        root_free_bytes=34 * 1024**3,
        retired_images=retired_images,
        preferred_keeper_project=preferred_keeper,
        preferred_keeper_qualified=preferred_qualified,
    )
    assert rotated.keeper.project == successor.project
    assert rotated.keeper_selection == "qualified_drained_anchor_rotation"
    assert [candidate.project for candidate in rotated.retirees] == [
        anchor.project
    ]
    rotated_sample = retention._record_stability_sample(
        state,
        rotated,
        now=rotation_now,
        expected_state_sha256=state_sha256,
        state_prevalidated=True,
    )
    assert rotated_sample["sample_count"] == 1
    assert rotated_sample["qualified"] is False
    assert (
        rotated_sample["identity_sha256"]
        != retention._stability_identity(initial)
    )


def test_state_loader_rejects_forged_qualification_and_stale_digest(
    tmp_path: Path,
) -> None:
    state = tmp_path / "forged-state.json"
    timestamp = NOW.isoformat().replace("+00:00", "Z")
    retention._mutable_private_json(
        state,
        {
            "schema": retention.STATE_SCHEMA,
            "updated_at": timestamp,
            "identity_sha256": "a" * 64,
            "keeper_project": NEW_PROJECT,
            "samples": [
                {
                    "observed_at": timestamp,
                    "identity_sha256": "a" * 64,
                }
            ],
            "qualified": True,
            "retired_images": {},
        },
    )
    with pytest.raises(RuntimeError, match="state_samples_invalid"):
        retention._load_retention_state(state, now=NOW)

    state.unlink()
    old, new = _pair()
    plan = retention._build_plan(
        (old, new),
        _inventory(old, new),
        now=NOW,
        root_free_bytes=34 * 1024**3,
    )
    retention._record_stability_sample(state, plan, now=NOW)
    _ledger, _keeper, _qualified, stale_digest = (
        retention._load_retention_state(
            state,
            now=NOW + timedelta(minutes=5),
        )
    )
    retention._record_stability_sample(
        state,
        plan,
        now=NOW + timedelta(minutes=5),
    )
    with pytest.raises(RuntimeError, match="state_changed"):
        retention._record_stability_sample(
            state,
            plan,
            now=NOW + timedelta(minutes=10),
            expected_state_sha256=stale_digest,
            state_prevalidated=True,
        )


def test_apply_verification_fails_on_protected_newer_candidate_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old, newest = _pair()
    young = replace(newest, observed_at=NOW - timedelta(minutes=10))
    inventory = _inventory(old, young)
    plan = retention._build_plan(
        (old, young),
        inventory,
        now=NOW,
        root_free_bytes=34 * 1024**3,
    )
    containers = [dict(row) for row in inventory.containers]
    next(
        row
        for row in containers
        if row.get("project") == young.project
        and row.get("service") == "gateway"
    )["health"] = "unhealthy"
    drifted = retention.Inventory(
        tuple(containers),
        inventory.networks,
        inventory.volumes,
        inventory.images,
    )
    monkeypatch.setattr(retention, "_discover_inventory", lambda _ids: drifted)
    with pytest.raises(RuntimeError, match="retained_candidate_changed"):
        retention._verify_after_apply(plan)


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("healthy", False),
        ("container_count", 2),
        ("network_count", 2),
        ("volume_count", 2),
        ("excluded_ephemeral_probe_name", "unexpected-probe"),
    ),
)
def test_stability_identity_resets_on_live_ea_posture_drift(
    field: str, replacement: object
) -> None:
    old, new = _pair()
    plan = retention._build_plan(
        (old, new),
        _inventory(old, new),
        now=NOW,
        root_free_bytes=34 * 1024**3,
    )
    changed = replace(
        plan,
        live_before={**plan.live_before, field: replacement},
    )

    assert retention._stability_identity(changed) != retention._stability_identity(plan)


def test_pending_quarantine_age_does_not_reset_stability_samples(
    tmp_path: Path,
) -> None:
    old, new = _pair()
    plan = retention._build_plan(
        (old, new),
        _inventory(old, new),
        now=NOW,
        root_free_bytes=34 * 1024**3,
    )
    state = tmp_path / "stability-with-pending.json"
    identities: list[str] = []
    observations: list[dict[str, object]] = []
    for offset in (0, 5, 10, 15):
        pending = (
            {
                "project": "ea-manfred-candidate-pending-abcdef",
                "created_at": "2026-07-13T13:00:00Z",
                "age_seconds": 60 + offset * 60,
                "ttl_expired": False,
                "operator_action_required": False,
                "resource_digest_sha256": "d" * 64,
                "reason": "pending_runtime_proof_intent",
            },
        )
        observed_plan = replace(plan, pending_intent_quarantine=pending)
        identities.append(retention._stability_identity(observed_plan))
        observations.append(
            retention._record_stability_sample(
                state, observed_plan, now=NOW + timedelta(minutes=offset)
            )
        )

    assert len(set(identities)) == 1
    assert [row["sample_count"] for row in observations] == [1, 2, 3, 4]
    assert observations[-1]["qualified"] is True


def test_registry_securely_enrolls_and_detects_receipt_change(tmp_path: Path) -> None:
    project = NEW_PROJECT
    receipt = tmp_path / "runtime-v3.json"
    receipt.write_text(
        json.dumps(
            {
                "schema": registry.RUNTIME_SCHEMA,
                "status": "pass",
                "compose_project": project,
                "observed_at": "2026-07-13T12:27:56Z",
                "image_id": NEW_IMAGE,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    receipt.chmod(0o600)
    registry_path = tmp_path / "registry.json"
    evidence = registry.register_candidate_receipt(
        receipt, registry_path=registry_path
    )
    assert evidence["registered"] is True
    assert registry.registered_candidate_receipts(
        registry_path=registry_path
    ) == [receipt]
    assert stat_mode(registry_path) == 0o600

    receipt.write_text(
        receipt.read_text(encoding="utf-8").replace("12:27:56", "12:28:56"),
        encoding="utf-8",
    )
    receipt.chmod(0o600)
    with pytest.raises(RuntimeError, match="receipt_changed"):
        registry.registered_candidate_receipts(registry_path=registry_path)


def test_registry_pending_intent_is_durable_and_receipt_finalizes_it(
    tmp_path: Path,
) -> None:
    receipt = (tmp_path / "runtime-v3.json").resolve()
    registry_path = tmp_path / "registry.json"
    evidence = registry.register_candidate_pending(
        project=NEW_PROJECT,
        port=18092,
        receipt_path=receipt,
        image=f"ea-runtime:manfred-{NEW_REVISION}",
        image_id=NEW_IMAGE,
        revision=NEW_REVISION,
        registry_path=registry_path,
    )
    assert evidence["pending_registered"] is True
    pending = registry.registered_candidate_pending(registry_path=registry_path)
    assert [row["project"] for row in pending] == [NEW_PROJECT]
    registry.compact_candidate_registry(set(), registry_path=registry_path)
    assert registry.registered_candidate_pending(
        registry_path=registry_path
    ) == pending

    receipt.write_text(
        json.dumps(
            {
                "schema": registry.RUNTIME_SCHEMA,
                "status": "pass",
                "compose_project": NEW_PROJECT,
                "observed_at": "2026-07-13T12:27:56Z",
                "image": f"ea-runtime:manfred-{NEW_REVISION}",
                "image_id": NEW_IMAGE,
                "image_source_revision": NEW_REVISION,
                "candidate_port": 18093,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    receipt.chmod(0o600)
    with pytest.raises(RuntimeError, match="pending_mismatch"):
        registry.register_candidate_receipt(receipt, registry_path=registry_path)
    assert len(
        registry.registered_candidate_pending(registry_path=registry_path)
    ) == 1
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    payload["candidate_port"] = 18092
    receipt.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    receipt.chmod(0o600)
    assert registry.register_candidate_receipt(
        receipt, registry_path=registry_path
    )["registered"] is True
    assert registry.registered_candidate_pending(registry_path=registry_path) == []


def test_pending_runtime_intent_is_quarantined_and_expired_absent_is_cleared(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    old, new = _pair()
    pending = {
        "project": OLD_PROJECT,
        "port": old.port,
        "receipt_path": str((tmp_path / "old-runtime.json").resolve()),
        "image": old.image,
        "image_id": old.image_id,
        "revision": old.revision,
        "created_at": (NOW - timedelta(minutes=1))
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
    }
    inventory = _inventory(old, new)
    status = retention._pending_intent_status([pending], inventory, now=NOW)
    assert status["active_projects"] == {OLD_PROJECT}
    assert status["quarantined"][0]["automatic_retirement_authorized"] is False
    plan = retention._build_plan(
        (old, new),
        inventory,
        now=NOW,
        root_free_bytes=34 * 1024**3,
        excluded_projects={OLD_PROJECT},
        pending_intent_quarantine=status["quarantined"],
    )
    assert plan.keeper.project == NEW_PROJECT
    assert plan.retirees == ()
    assert retention._mutation_targets(plan) == {
        "container_ids": [],
        "network_ids": [],
        "volume_names": [],
        "eligible_image_ids": [],
    }

    orphan_project = "ea-manfred-candidate-orphan-abcdef12"
    orphan_revision = "7" * 40
    registry_path = tmp_path / "orphan-registry.json"
    monkeypatch.setattr(
        registry,
        "_utc_now",
        lambda: (NOW - timedelta(hours=3)).isoformat().replace("+00:00", "Z"),
    )
    registry.register_candidate_pending(
        project=orphan_project,
        port=18199,
        receipt_path=tmp_path / "orphan-runtime.json",
        image=f"ea-runtime:manfred-{orphan_revision}",
        image_id="sha256:" + "7" * 64,
        revision=orphan_revision,
        registry_path=registry_path,
    )
    orphan_pending = registry.registered_candidate_pending(
        registry_path=registry_path
    )
    orphan_status = retention._pending_intent_status(
        orphan_pending,
        _inventory_for_proofs((new,)),
        now=NOW,
    )
    assert orphan_status["absent"][0]["ttl_expired"] is True
    cleared = retention._clear_expired_absent_pending(
        orphan_status, registry_path=registry_path
    )
    assert cleared[0]["project"] == orphan_project
    assert registry.registered_candidate_pending(registry_path=registry_path) == []


def test_collector_excludes_active_pending_intent_without_blocking_valid_keeper(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    old, new = _pair()
    inventory = _inventory(old, new)
    pending = {
        "project": OLD_PROJECT,
        "port": old.port,
        "receipt_path": str((tmp_path / "old-runtime.json").resolve()),
        "image": old.image,
        "image_id": old.image_id,
        "revision": old.revision,
        "created_at": (datetime.now(timezone.utc) - timedelta(minutes=1))
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
    }
    monkeypatch.setattr(
        retention,
        "registered_candidate_receipts",
        lambda **_kwargs: [tmp_path / "old.json", tmp_path / "new.json"],
    )
    monkeypatch.setattr(
        retention, "registered_candidate_pending", lambda **_kwargs: [pending]
    )
    monkeypatch.setattr(retention, "_load_runtime_proofs", lambda _paths: (old, new))
    monkeypatch.setattr(
        retention,
        "hold_candidate_fleet_lock",
        lambda **_kwargs: _lock({"scope": "fleet"}),
    )
    monkeypatch.setattr(
        retention,
        "_hold_retention_resource_locks",
        lambda proofs: _lock([{"projects": sorted(proofs)}]),
    )
    monkeypatch.setattr(retention, "_discover_inventory", lambda _ids: inventory)
    monkeypatch.setattr(
        retention, "_existing_image_ids", lambda: {OLD_IMAGE, NEW_IMAGE}
    )
    monkeypatch.setattr(retention, "_assert_keeper_http", lambda _proof: None)
    monkeypatch.setattr(
        retention,
        "_record_stability_sample",
        lambda *_args, **_kwargs: {
            "sample_count": 1,
            "sample_span_seconds": 0,
            "qualified": False,
        },
    )
    build_plan = retention._build_plan
    monkeypatch.setattr(
        retention,
        "_build_plan",
        lambda proofs, observed, **kwargs: build_plan(
            proofs,
            observed,
            now=NOW,
            root_free_bytes=34 * 1024**3,
            **{key: value for key, value in kwargs.items() if key != "now"},
        ),
    )
    monkeypatch.setattr(retention, "_atomic_receipt", lambda *_args: None)
    receipt = retention.retain_candidates(
        runtime_receipts=[],
        output_receipt=tmp_path / "retention.json",
        apply=False,
        state_path=tmp_path / "state.json",
        registry_path=tmp_path / "registry.json",
    )
    assert receipt["action"] == "planned"
    assert receipt["plan"]["keeper"]["project"] == NEW_PROJECT
    assert receipt["plan"]["retirees"] == []
    assert receipt["plan"]["pending_intent_quarantine"][0]["project"] == OLD_PROJECT
    assert receipt["mutations_performed"] == 0


def test_registry_compaction_prevents_historical_capacity_from_blocking_new_proof(
    tmp_path: Path,
) -> None:
    registry_path = tmp_path / "registry.json"
    entries = [
        {
            "project": f"ea-manfred-candidate-history-{index:04d}",
            "receipt_path": str(tmp_path / f"historical-{index:04d}.json"),
            "receipt_sha256": f"{index:064x}",
            "observed_at": "2026-07-12T00:00:00Z",
            "image_id": "sha256:" + f"{index:064x}",
        }
        for index in range(registry.MAX_REGISTRY_ENTRIES)
    ]
    registry._atomic_registry(
        registry_path,
        {
            "schema": registry.REGISTRY_SCHEMA,
            "entry_count": len(entries),
            "entries": entries,
        },
    )
    compacted = registry.compact_candidate_registry(
        set(), registry_path=registry_path
    )
    assert compacted["before_count"] == registry.MAX_REGISTRY_ENTRIES
    assert compacted["after_count"] == 0
    assert compacted["historical_receipts_deleted"] is False

    receipt = tmp_path / "new-runtime-v3.json"
    receipt.write_text(
        json.dumps(
            {
                "schema": registry.RUNTIME_SCHEMA,
                "status": "pass",
                "compose_project": NEW_PROJECT,
                "observed_at": "2026-07-13T12:27:56Z",
                "image_id": NEW_IMAGE,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    receipt.chmod(0o600)
    assert registry.register_candidate_receipt(
        receipt, registry_path=registry_path
    )["registered"] is True


def stat_mode(path: Path) -> int:
    return path.stat().st_mode & 0o777


def test_shared_fleet_lock_is_nonblocking(tmp_path: Path) -> None:
    path = tmp_path / fleet_lock.FLEET_LOCK_PATH.name
    with fleet_lock.hold_candidate_fleet_lock(lock_path=path) as first:
        assert first is not None
        with fleet_lock.hold_candidate_fleet_lock(
            lock_path=path, skip_if_busy=True
        ) as second:
            assert second is None


def test_shared_fleet_lock_accepts_only_exact_idmapped_root_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(fleet_lock.os, "getuid", lambda: 1000)
    idmapped_root = SimpleNamespace(
        st_uid=fleet_lock.NAMESPACE_ROOT_OVERFLOW_UID,
        st_mode=stat.S_IFDIR | 0o1777,
    )
    assert fleet_lock._trusted_lock_directory_owner(
        fleet_lock.FLEET_LOCK_PATH, idmapped_root
    )
    assert not fleet_lock._trusted_lock_directory_owner(
        tmp_path / fleet_lock.FLEET_LOCK_PATH.name, idmapped_root
    )
    wrong_mode = SimpleNamespace(
        st_uid=fleet_lock.NAMESPACE_ROOT_OVERFLOW_UID,
        st_mode=stat.S_IFDIR | 0o0777,
    )
    assert not fleet_lock._trusted_lock_directory_owner(
        fleet_lock.FLEET_LOCK_PATH, wrong_mode
    )


def test_registry_state_root_ignores_ambient_home_overrides(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    expected = (
        Path(registry.pwd.getpwuid(os.getuid()).pw_dir)
        / ".local/state/ea/manfred-candidate-registry.json"
    )
    monkeypatch.setenv("HOME", str(tmp_path / "hostile-home"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "hostile-state"))
    assert registry.default_registry_path() == expected


def test_cli_default_creates_unique_receipt_path_under_operator_state_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(retention, "operator_state_root", lambda: tmp_path / "ea")
    captured: dict[str, object] = {}

    def retain(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"schema": retention.RECEIPT_SCHEMA, "status": "pass"}

    monkeypatch.setattr(retention, "retain_candidates", retain)
    assert retention.main([]) == 0
    output = Path(captured["output_receipt"])
    assert output.parent == tmp_path / "ea/manfred-candidate-retention-receipts"
    assert output.name.startswith("retention-")
    assert captured["apply"] is False
    assert json.loads(capsys.readouterr().out)["status"] == "pass"


def test_script_cli_bootstraps_repo_import_path_from_arbitrary_cwd(
    tmp_path: Path,
) -> None:
    completed = subprocess.run(
        [
            os.environ.get("PYTHON", "python3"),
            str(retention.ROOT / "scripts/cleanup_manfred_memorial_candidates.py"),
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
    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")
    assert b"--apply" in completed.stdout


def test_runner_checks_fleet_before_project_or_port_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resource_lock_entered = False

    @contextlib.contextmanager
    def busy_fleet(**_kwargs: object):
        raise RuntimeError(fleet_lock.FLEET_LOCK_BUSY)
        yield  # pragma: no cover

    @contextlib.contextmanager
    def resource_lock(*_args: object, **_kwargs: object):
        nonlocal resource_lock_entered
        resource_lock_entered = True
        yield {}

    monkeypatch.setattr(runner, "hold_candidate_fleet_lock", busy_fleet)
    monkeypatch.setattr(runner, "_hold_project_lock", resource_lock)
    monkeypatch.setattr(runner, "_hold_port_lock", resource_lock)
    with pytest.raises(RuntimeError, match="fleet_lock_held"):
        with runner._hold_candidate_locks(OLD_PROJECT, 18091):
            pytest.fail("busy fleet admitted a candidate proof")
    assert resource_lock_entered is False


def test_runner_persists_receipt_before_self_registration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    order: list[str] = []
    path = tmp_path / "runtime.json"
    monkeypatch.setattr(
        runner,
        "_atomic_receipt",
        lambda observed_path, _payload: order.append(f"write:{observed_path.name}"),
    )
    monkeypatch.setattr(
        runner,
        "register_candidate_receipt",
        lambda observed_path: order.append(f"register:{observed_path.name}")
        or {"registered": True},
    )
    assert runner._persist_runtime_receipt(path, {"status": "pass"}) == {
        "registered": True
    }
    assert order == ["write:runtime.json", "register:runtime.json"]


def test_runner_receipt_fsyncs_file_and_parent_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    observed: list[str] = []
    real_fsync = os.fsync

    def record_fsync(descriptor: int) -> None:
        mode = os.fstat(descriptor).st_mode
        observed.append("directory" if stat.S_ISDIR(mode) else "file")
        real_fsync(descriptor)

    monkeypatch.setattr(runner.os, "fsync", record_fsync)
    output = tmp_path / "runtime.json"
    artifact = runner._atomic_receipt(
        output,
        {"schema": runner.RECEIPT_SCHEMA, "status": "pass"},
    )

    assert artifact.path == output
    assert observed == ["file", "directory"]
    assert output.stat().st_mode & 0o777 == 0o600
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "pass"
    assert [path.name for path in tmp_path.iterdir()] == ["runtime.json"]
