from __future__ import annotations

import contextlib
import copy
import json
import os
import signal
from pathlib import Path

import pytest

from scripts import prepare_manfred_memorial_candidate as prepare
from scripts import manfred_candidate_registry as registry
from scripts import run_manfred_memorial_candidate as runner


PROJECT = "ea-manfred-candidate-20260713-a1b2c3d4"
COMMIT = "a" * 40
IMAGE_ID = "sha256:" + "b" * 64


def _candidate_env(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    env_file = (tmp_path / "candidate.env").resolve()
    release_root = (tmp_path / "releases" / "release-a").resolve()
    runtime_root = (tmp_path / "runtime").resolve()
    release_root.mkdir(parents=True)
    runtime_root.mkdir(parents=True)
    values = {
        "EA_MANFRED_COMPOSE_PROJECT": PROJECT,
        "EA_MANFRED_IMAGE": f"ea-runtime:manfred-{COMMIT}",
        "EA_MANFRED_ENV_FILE": str(env_file),
        "EA_MANFRED_RELEASE_ROOT": str(release_root),
        "EA_MANFRED_RUNTIME_ROOT": str(runtime_root),
        "EA_MANFRED_HOST_PORT": "18091",
        "EA_MANFRED_POSTGRES_PASSWORD": "p" * 64,
        "DATABASE_URL": "postgresql://ea:private@postgres:5432/ea",
        "EA_API_TOKEN": "a" * 64,
        "EA_SIGNING_SECRET": "s" * 64,
        "EA_PUBLIC_APP_BASE_URL": "https://myexternalbrain.com",
    }
    env_file.write_text(
        "".join(f"{name}={value}\n" for name, value in sorted(values.items())),
        encoding="utf-8",
    )
    env_file.chmod(0o600)
    return env_file, values


def _compose_payloads(env_file: Path, env: dict[str, str]) -> tuple[dict, dict]:
    release_root = Path(env["EA_MANFRED_RELEASE_ROOT"])
    runtime_root = Path(env["EA_MANFRED_RUNTIME_ROOT"])
    mounts = [
        {
            "type": "bind",
            "source": str(release_root / "public_memorials"),
            "target": "/data/memorial/public",
            "read_only": True,
        },
        {
            "type": "bind",
            "source": str(release_root / "private_memorial_profiles"),
            "target": "/data/memorial/private",
            "read_only": True,
        },
        {
            "type": "bind",
            "source": str(release_root / "memorial_archive"),
            "target": "/data/memorial/archive",
            "read_only": True,
        },
        {
            "type": "bind",
            "source": str(runtime_root / "public-contributions"),
            "target": "/data/memorial/public-contributions",
        },
        {
            "type": "bind",
            "source": str(runtime_root / "private-contributions"),
            "target": "/data/memorial/private-contributions",
        },
        {
            "type": "bind",
            "source": str(runtime_root / "state"),
            "target": "/data/memorial/state",
        },
        {"type": "volume", "source": "artifacts", "target": "/data/artifacts"},
    ]
    declared = {"EA_ROLE": "api"}
    services = {
        "api": {
            "image": env["EA_MANFRED_IMAGE"],
            "pull_policy": "never",
            "read_only": True,
            "user": "10001:10001",
            "networks": ["backend"],
            "environment": {**env, **declared},
            "volumes": mounts,
        },
        "gateway": {
            "image": env["EA_MANFRED_IMAGE"],
            "networks": ["backend", "ingress"],
            "ports": [
                {
                    "host_ip": "127.0.0.1",
                    "target": 18090,
                    "published": env["EA_MANFRED_HOST_PORT"],
                }
            ],
        },
        "postgres": {"networks": ["backend"]},
        "redis": {"networks": ["backend"]},
    }
    payload = {
        "name": PROJECT,
        "services": services,
        "networks": {
            "backend": {"name": f"{PROJECT}_backend", "internal": True},
            "ingress": {"name": f"{PROJECT}_ingress"},
        },
        "volumes": {
            name: {"name": f"{PROJECT}_{name}"}
            for name in runner.EXPECTED_CANDIDATE_VOLUMES
        },
    }
    source = copy.deepcopy(payload)
    source["services"]["api"]["environment"] = declared
    source["services"]["api"]["env_file"] = [{"path": str(env_file)}]
    return payload, source


def _baseline_snapshot() -> dict[str, object]:
    return {
        "project": "ea",
        "containers": [
            {
                "container_id": "api-id",
                "name": "ea-api",
                "service": "ea-api",
                "image_id": "image-id",
                "started_at": "2026-07-13T00:00:00Z",
                "running": True,
                "status": "running",
                "health": "healthy",
                "networks": [{"name": "ea_default", "network_id": "network-id"}],
            }
        ],
        "networks": [{"name": "ea_default", "network_id": "network-id"}],
        "volumes": [{"name": "ea_redis", "driver": "local"}],
    }


@contextlib.contextmanager
def _fake_candidate_locks(project: str, port: int):
    yield {
        "project": {
            "scope": "compose_project",
            "project": project,
            "held_through_candidate_proof": True,
        },
        "port": {
            "scope": "host_loopback_port",
            "port": port,
            "held_through_candidate_proof": True,
        },
    }


def _openapi_snapshot() -> tuple[dict[str, object], dict[str, object]]:
    contract: dict[str, object] = {
        "operations": {"GET /healthz": {"responses": {"200": {}}}},
        "schemas": {},
        "security_schemes": {},
    }
    return contract, runner._openapi_contract_evidence(contract)


def _patch_prestart(monkeypatch: pytest.MonkeyPatch, env: dict[str, str]) -> None:
    monkeypatch.setattr(runner, "_assert_env_allowlist", lambda _path: dict(env))
    monkeypatch.setattr(
        runner,
        "_projection_evidence",
        lambda _env: {
            "release_id": "release-a",
            "release_root": env["EA_MANFRED_RELEASE_ROOT"],
            "projection_sha256": "d" * 64,
            "projection_commit": COMMIT,
            "prepared_image_locator": env["EA_MANFRED_IMAGE"],
            "prepared_image_id": IMAGE_ID,
            "projection_tree_revalidated": True,
        },
    )
    monkeypatch.setattr(runner, "_rendered_compose", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        runner, "_assert_compose_isolation", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(runner, "_hold_candidate_locks", _fake_candidate_locks)
    monkeypatch.setattr(
        runner,
        "_assert_prepared_image_locator",
        lambda _projection: {
            "locator": env["EA_MANFRED_IMAGE"],
            "resolved_image_id": IMAGE_ID,
            "revision_label": COMMIT,
            "locator_only": True,
        },
    )
    monkeypatch.setattr(runner, "_live_snapshot", _baseline_snapshot)
    monkeypatch.setattr(runner, "_assert_live_healthy", lambda _snapshot: None)
    monkeypatch.setattr(runner, "_assert_live_http", lambda: None)
    monkeypatch.setattr(
        runner,
        "_openapi_contract_snapshot",
        lambda _base: copy.deepcopy(_openapi_snapshot()),
    )
    monkeypatch.setattr(
        runner,
        "register_candidate_pending",
        lambda **_kwargs: {"pending_registered": True},
    )
    monkeypatch.setattr(
        runner,
        "clear_candidate_pending",
        lambda _project: {"pending_cleared": True},
    )


def test_project_name_requires_deployment_specific_candidate_prefix() -> None:
    assert prepare._validate_project_name(PROJECT) == PROJECT
    for value in (
        "ea",
        "ea-manfred-candidate",
        "ea-manfred-candidate-v2",
        "other-20260713",
    ):
        with pytest.raises(ValueError, match="manfred_candidate_project_name_invalid"):
            prepare._validate_project_name(value)


def test_hostile_ambient_compose_values_are_replaced(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    env_file, env = _candidate_env(tmp_path)
    monkeypatch.setenv("EA_MANFRED_COMPOSE_PROJECT", "ea")
    monkeypatch.setenv("EA_MANFRED_ENV_FILE", "/docker/EA/.env")
    monkeypatch.setenv("COMPOSE_PROJECT_NAME", "ea")
    assert runner._assert_env_allowlist(env_file) == env
    sanitized = runner._compose_environment(env)
    assert sanitized["EA_MANFRED_COMPOSE_PROJECT"] == PROJECT
    assert sanitized["EA_MANFRED_ENV_FILE"] == str(env_file)
    assert "COMPOSE_PROJECT_NAME" not in sanitized
    command = runner._compose_argv(
        PROJECT, env_file, tmp_path / "compose.yml", "config"
    )
    assert command[command.index("--project-name") + 1] == PROJECT


def test_compose_contract_binds_project_env_file_and_mount_roots(
    tmp_path: Path,
) -> None:
    env_file, env = _candidate_env(tmp_path)
    payload, source = _compose_payloads(env_file, env)
    runner._assert_compose_isolation(payload, source, env=env, env_file=env_file)

    hostile = copy.deepcopy(source)
    hostile["services"]["api"]["env_file"] = [{"path": "/docker/EA/.env"}]
    with pytest.raises(RuntimeError, match="compose_env_file_mismatch"):
        runner._assert_compose_isolation(payload, hostile, env=env, env_file=env_file)

    hostile_project = copy.deepcopy(payload)
    hostile_project["name"] = "ea"
    with pytest.raises(RuntimeError, match="compose_project_mismatch"):
        runner._assert_compose_isolation(
            hostile_project, source, env=env, env_file=env_file
        )


def test_projection_receipt_binds_safe_release_root_digest_image_and_project(
    tmp_path: Path,
) -> None:
    _env_file, env = _candidate_env(tmp_path)
    release_root = Path(env["EA_MANFRED_RELEASE_ROOT"])
    (release_root / "public_memorials").mkdir()
    (release_root / "public_memorials" / "memorial.json").write_text(
        "{}\n", encoding="utf-8"
    )
    prepare._set_modes(release_root)
    projection_sha256, projected_files = prepare._tree_digest(release_root)
    receipt_path = release_root.parent.parent / "receipts" / f"{release_root.name}.json"
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_text(
        json.dumps(
            {
                "schema": "ea.manfred_memorial_candidate_projection.v2",
                "status": "pass",
                "commit": COMMIT,
                "release_id": release_root.name,
                "release_root": str(release_root),
                "image": env["EA_MANFRED_IMAGE"],
                "image_id": IMAGE_ID,
                "compose_project": PROJECT,
                "projection_sha256": projection_sha256,
                "projection_operator_gid": os.getgid(),
                "file_count": len(projected_files),
                "projection_bytes": sum(
                    int(row["size_bytes"]) for row in projected_files
                ),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    receipt_path.chmod(0o600)

    assert runner._projection_evidence(env) == {
        "release_id": release_root.name,
        "release_root": str(release_root),
        "projection_sha256": projection_sha256,
        "projection_commit": COMMIT,
        "prepared_image_locator": env["EA_MANFRED_IMAGE"],
        "prepared_image_id": IMAGE_ID,
        "projection_tree_revalidated": True,
    }

    prepare._make_tree_removable(release_root)
    (release_root / "public_memorials" / "memorial.json").write_text(
        '{"retargeted":true}\n', encoding="utf-8"
    )
    prepare._set_modes(release_root)
    with pytest.raises(RuntimeError, match="projection_tree_digest_mismatch"):
        runner._projection_evidence(env)


def test_preflight_failure_occurs_before_any_compose_mutation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    env_file, env = _candidate_env(tmp_path)
    _patch_prestart(monkeypatch, env)
    monkeypatch.setattr(
        runner,
        "_candidate_preflight",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("preflight-blocked")),
    )
    commands: list[list[str]] = []
    monkeypatch.setattr(
        runner,
        "_run",
        lambda argv, **_kwargs: commands.append(list(argv)) or b"",
    )
    with pytest.raises(RuntimeError, match="preflight-blocked"):
        runner.prove_candidate(
            env_file=env_file,
            compose_file=tmp_path / "compose.yml",
            receipt_path=tmp_path / "runtime.json",
            wait_seconds=60,
        )
    assert not any("up" in command or "down" in command for command in commands)


def test_preflight_rejects_unlabeled_exact_named_project_resource(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runner,
        "_project_snapshot",
        lambda project: {
            "project": project,
            "containers": [],
            "networks": [],
            "volumes": [],
        },
    )

    def listed(argv: list[str]) -> list[str]:
        if "network" in argv:
            return [f"{PROJECT}_backend"]
        return []

    monkeypatch.setattr(runner, "_listed_values", listed)
    with pytest.raises(RuntimeError, match="project_resources_already_exist"):
        runner._assert_candidate_project_absent(PROJECT)


def test_same_project_different_ports_conflict_on_project_lock() -> None:
    project = "ea-manfred-candidate-project-lock-a1b2c3d4"
    with runner._hold_candidate_locks(project, 18991):
        with pytest.raises(RuntimeError, match="fleet_lock_held"):
            with runner._hold_candidate_locks(project, 18992):
                pytest.fail("same candidate project acquired twice")


def test_retargeted_image_locator_is_rejected_before_candidate_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projection = {
        "prepared_image_locator": f"ea-runtime:manfred-{COMMIT}",
        "prepared_image_id": IMAGE_ID,
        "projection_commit": COMMIT,
    }
    monkeypatch.setattr(
        runner,
        "_inspect_image",
        lambda _identifier: {
            "image_id": "sha256:" + "c" * 64,
            "revision_label": COMMIT,
        },
    )
    with pytest.raises(RuntimeError, match="image_locator_retargeted"):
        runner._assert_prepared_image_locator(projection)


def test_governed_image_locator_prefixes_are_exactly_revision_bound(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    inspected: list[str] = []

    def inspect(identifier: str) -> dict[str, object]:
        inspected.append(identifier)
        return {"image_id": IMAGE_ID, "revision_label": COMMIT}

    monkeypatch.setattr(runner, "_inspect_image", inspect)
    for prefix in ("manfred", "memorial"):
        locator = f"ea-runtime:{prefix}-{COMMIT}"
        evidence = runner._assert_prepared_image_locator(
            {
                "prepared_image_locator": locator,
                "prepared_image_id": IMAGE_ID,
                "projection_commit": COMMIT,
            }
        )
        assert evidence["locator"] == locator
        pending = registry._normalized_pending(
            project=PROJECT,
            port=18091,
            receipt_path=(tmp_path / f"{prefix}.json").resolve(),
            image=locator,
            image_id=IMAGE_ID,
            revision=COMMIT,
            created_at="2026-07-13T17:00:00Z",
        )
        assert pending["image"] == locator
    assert inspected == [
        f"ea-runtime:manfred-{COMMIT}",
        f"ea-runtime:memorial-{COMMIT}",
    ]

    with pytest.raises(RuntimeError, match="pending_invalid"):
        registry._normalized_pending(
            project=PROJECT,
            port=18091,
            receipt_path=(tmp_path / "other.json").resolve(),
            image=f"ea-runtime:other-{COMMIT}",
            image_id=IMAGE_ID,
            revision=COMMIT,
            created_at="2026-07-13T17:00:00Z",
        )


def test_running_api_and_gateway_must_use_prepared_image_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identifiers = {"api": "api-container", "gateway": "gateway-container"}
    monkeypatch.setattr(
        runner,
        "_compose_service_container_id",
        lambda _compose, _environment, service: identifiers[service],
    )
    rows = [
        {
            "Id": identifiers["api"],
            "Image": IMAGE_ID,
            "Config": {
                "Labels": {
                    "com.docker.compose.project": PROJECT,
                    "com.docker.compose.service": "api",
                }
            },
        },
        {
            "Id": identifiers["gateway"],
            "Image": "sha256:" + "c" * 64,
            "Config": {
                "Labels": {
                    "com.docker.compose.project": PROJECT,
                    "com.docker.compose.service": "gateway",
                }
            },
        },
    ]
    monkeypatch.setattr(
        runner,
        "_run",
        lambda _argv, **_kwargs: json.dumps(rows).encode("utf-8"),
    )
    with pytest.raises(RuntimeError, match="runtime_container_image_mismatch"):
        runner._candidate_container_image_evidence(
            compose=["docker", "compose"],
            environment={},
            project=PROJECT,
            projection={
                "prepared_image_id": IMAGE_ID,
                "projection_commit": COMMIT,
            },
        )


def test_short_revision_image_locator_is_rejected_before_inspection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runner,
        "_inspect_image",
        lambda _identifier: pytest.fail("short locator reached Docker inspection"),
    )
    with pytest.raises(RuntimeError, match="image_locator_revision_mismatch"):
        runner._assert_prepared_image_locator(
            {
                "prepared_image_locator": f"ea-runtime:manfred-{COMMIT[:12]}",
                "prepared_image_id": IMAGE_ID,
                "projection_commit": COMMIT,
            }
        )


def _meaningful_openapi_document() -> dict[str, object]:
    return {
        "openapi": "3.1.0",
        "security": [{"BearerAuth": []}],
        "paths": {
            "/healthz": {"get": {"security": [], "responses": {"200": {}}}},
            "/items/{item_id}": {
                "parameters": [
                    {
                        "name": "item_id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    }
                ],
                "get": {
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Item"}
                                }
                            }
                        }
                    }
                },
            },
        },
        "components": {
            "schemas": {
                "Item": {
                    "type": "object",
                    "required": ["description", "name"],
                    "properties": {
                        "description": {"type": "string"},
                        "name": {"type": "string"},
                    },
                }
            },
            "securitySchemes": {"BearerAuth": {"type": "http", "scheme": "bearer"}},
        },
    }


def test_openapi_contract_allows_additions_and_persists_only_bounded_evidence() -> None:
    live_document = _meaningful_openapi_document()
    candidate_document = copy.deepcopy(live_document)
    candidate_document["paths"]["/candidate-only"] = {
        "post": {"security": [], "responses": {"204": {}}}
    }
    live = runner._canonical_openapi_contract(live_document)
    candidate = runner._canonical_openapi_contract(candidate_document)

    assert runner._assert_openapi_contract_preserved(live, candidate) == {
        "missing_or_changed_operation_count": 0,
        "missing_or_changed_schema_count": 0,
        "missing_or_changed_security_scheme_count": 0,
        "candidate_preserves_live_contract": True,
    }
    evidence = runner._openapi_contract_evidence(live)
    assert set(evidence) == {
        "path_count",
        "operation_count",
        "schema_count",
        "security_scheme_count",
        "path_digest_sha256",
        "contract_digest_sha256",
    }
    assert "operations" not in evidence


@pytest.mark.parametrize(
    "drift",
    [
        "method",
        "response_schema",
        "presentation_named_schema_property",
        "security_scheme",
    ],
)
def test_openapi_contract_rejects_meaningful_drift(drift: str) -> None:
    live_document = _meaningful_openapi_document()
    candidate_document = copy.deepcopy(live_document)
    item_path = candidate_document["paths"]["/items/{item_id}"]
    if drift == "method":
        item_path["post"] = item_path.pop("get")
    elif drift == "response_schema":
        candidate_document["components"]["schemas"]["Item"]["properties"]["name"][
            "type"
        ] = "integer"
    elif drift == "presentation_named_schema_property":
        candidate_document["components"]["schemas"]["Item"]["properties"][
            "description"
        ]["type"] = "integer"
    else:
        candidate_document["components"]["securitySchemes"]["BearerAuth"]["scheme"] = (
            "basic"
        )

    live = runner._canonical_openapi_contract(live_document)
    candidate = runner._canonical_openapi_contract(candidate_document)
    with pytest.raises(RuntimeError, match="openapi_contract_regression"):
        runner._assert_openapi_contract_preserved(live, candidate)


def test_runtime_receipt_must_be_a_new_path_and_existing_content_is_preserved(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime_receipt = tmp_path / "runtime.json"
    original = b'{"status":"existing"}\n'
    runtime_receipt.write_bytes(original)
    runtime_receipt.chmod(0o600)
    monkeypatch.setattr(
        runner,
        "_assert_env_allowlist",
        lambda _path: pytest.fail("existing receipt reached candidate preflight"),
    )

    with pytest.raises(RuntimeError, match=runner.RECEIPT_OUTPUT_EXISTS):
        runner.prove_candidate(
            env_file=tmp_path / "candidate.env",
            compose_file=tmp_path / "compose.yml",
            receipt_path=runtime_receipt,
            wait_seconds=60,
        )

    assert runtime_receipt.read_bytes() == original


@pytest.mark.parametrize("symlink_component", ["target", "parent"])
def test_runtime_receipt_rejects_symlink_components_without_touching_target(
    tmp_path: Path, symlink_component: str
) -> None:
    victim = tmp_path / "victim.json"
    victim.write_text('{"status":"victim"}\n', encoding="utf-8")
    victim.chmod(0o600)
    if symlink_component == "target":
        output = tmp_path / "runtime.json"
        output.symlink_to(victim)
    else:
        real_parent = tmp_path / "real-parent"
        real_parent.mkdir(mode=0o700)
        linked_parent = tmp_path / "linked-parent"
        linked_parent.symlink_to(real_parent, target_is_directory=True)
        output = linked_parent / "runtime.json"

    with pytest.raises(
        RuntimeError,
        match=f"{runner.RECEIPT_PATH_INVALID}|{runner.RECEIPT_PARENT_INVALID}",
    ):
        runner._atomic_receipt(output, {"status": "replacement"})

    assert victim.read_text(encoding="utf-8") == '{"status":"victim"}\n'
    assert not (tmp_path / "real-parent" / "runtime.json").exists()


def test_runtime_receipt_rejects_group_writable_parent(tmp_path: Path) -> None:
    unsafe_parent = tmp_path / "unsafe"
    unsafe_parent.mkdir(mode=0o770)
    unsafe_parent.chmod(0o770)
    output = unsafe_parent / "runtime.json"

    with pytest.raises(RuntimeError, match=runner.RECEIPT_PARENT_INVALID):
        runner._atomic_receipt(output, {"status": "pass"})

    assert not output.exists()


@pytest.mark.parametrize("sibling_kind", ["existing", "symlink"])
def test_private_contribution_receipt_must_be_new_and_is_never_unlinked_prestart(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, sibling_kind: str
) -> None:
    contribution = tmp_path / "candidate-contribution.private.json"
    victim = tmp_path / "private-victim.json"
    expected_path = contribution
    if sibling_kind == "existing":
        contribution.write_text('{"status":"existing"}\n', encoding="utf-8")
        contribution.chmod(0o600)
    else:
        victim.write_text('{"status":"victim"}\n', encoding="utf-8")
        victim.chmod(0o600)
        contribution.symlink_to(victim)
        expected_path = victim
    original = expected_path.read_bytes()
    monkeypatch.setattr(
        runner,
        "_assert_env_allowlist",
        lambda _path: pytest.fail("private receipt collision reached candidate preflight"),
    )

    with pytest.raises(
        RuntimeError,
        match=f"{runner.RECEIPT_OUTPUT_EXISTS}|{runner.RECEIPT_PATH_INVALID}",
    ):
        runner.prove_candidate(
            env_file=tmp_path / "candidate.env",
            compose_file=tmp_path / "compose.yml",
            receipt_path=tmp_path / "runtime.json",
            wait_seconds=60,
        )

    assert expected_path.read_bytes() == original
    assert contribution.exists() or contribution.is_symlink()
    assert not (tmp_path / "runtime.json").exists()


def test_runtime_receipt_cleanup_refuses_changed_identity(tmp_path: Path) -> None:
    output = tmp_path / "runtime.json"
    artifact = runner._atomic_receipt(output, {"status": "created"})
    output.unlink()
    replacement = b'{"status":"replacement"}\n'
    output.write_bytes(replacement)
    output.chmod(0o600)

    assert runner._unlink_created_receipt_artifact(artifact) is False
    assert output.read_bytes() == replacement


def test_runtime_receipt_writer_never_replaces_existing_output(tmp_path: Path) -> None:
    output = tmp_path / "runtime.json"
    runner._atomic_receipt(output, {"status": "first"})
    original = output.read_bytes()

    with pytest.raises(RuntimeError, match=runner.RECEIPT_OUTPUT_EXISTS):
        runner._atomic_receipt(output, {"status": "second"})

    assert output.read_bytes() == original


def test_post_start_failure_cleans_only_explicit_candidate_project(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    env_file, env = _candidate_env(tmp_path)
    _patch_prestart(monkeypatch, env)
    monkeypatch.setattr(
        runner,
        "_candidate_preflight",
        lambda project, port: {"project": project, "loopback_port": port},
    )
    commands: list[list[str]] = []
    monkeypatch.setattr(
        runner,
        "_run",
        lambda argv, **_kwargs: commands.append(list(argv)) or b"",
    )
    monkeypatch.setattr(
        runner,
        "_assert_redis",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("candidate-smoke-failed")),
    )
    monkeypatch.setattr(runner, "_assert_candidate_project_absent", lambda _project: {})
    monkeypatch.setattr(runner, "_assert_loopback_port_free", lambda _port: None)
    runtime_receipt = tmp_path / "runtime.json"
    unrelated_receipt = tmp_path / "unrelated.json"
    unrelated_receipt.write_text('{"status":"preserve"}\n', encoding="utf-8")
    unrelated_receipt.chmod(0o600)

    with pytest.raises(RuntimeError, match="candidate-smoke-failed"):
        runner.prove_candidate(
            env_file=env_file,
            compose_file=tmp_path / "compose.yml",
            receipt_path=runtime_receipt,
            wait_seconds=60,
        )
    down = next(command for command in commands if "down" in command)
    assert down[down.index("--project-name") + 1] == PROJECT
    assert "--volumes" in down
    assert not any(value == "ea" for value in down)
    assert not runtime_receipt.exists()
    assert unrelated_receipt.read_text(encoding="utf-8") == '{"status":"preserve"}\n'


def test_failed_first_smoke_removes_only_its_tracked_private_receipt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    env_file, env = _candidate_env(tmp_path)
    _patch_prestart(monkeypatch, env)
    monkeypatch.setattr(
        runner,
        "_candidate_preflight",
        lambda project, port: {"project": project, "loopback_port": port},
    )
    commands: list[list[str]] = []
    monkeypatch.setattr(
        runner,
        "_run",
        lambda argv, **_kwargs: commands.append(list(argv)) or b"",
    )
    monkeypatch.setattr(runner, "_assert_redis", lambda *_args: None)

    def failed_smoke(**kwargs: object) -> dict[str, object]:
        private_receipt = Path(kwargs["submit_receipt"])
        private_receipt.write_text('{"status":"created"}\n', encoding="utf-8")
        private_receipt.chmod(0o600)
        raise RuntimeError("candidate-first-smoke-failed")

    monkeypatch.setattr(runner, "verify_candidate", failed_smoke)
    monkeypatch.setattr(runner, "_assert_candidate_project_absent", lambda _project: {})
    monkeypatch.setattr(runner, "_assert_loopback_port_free", lambda _port: None)
    unrelated = tmp_path / "unrelated.private.json"
    unrelated.write_text('{"status":"preserve"}\n', encoding="utf-8")
    unrelated.chmod(0o600)

    with pytest.raises(RuntimeError, match="candidate-first-smoke-failed"):
        runner.prove_candidate(
            env_file=env_file,
            compose_file=tmp_path / "compose.yml",
            receipt_path=tmp_path / "runtime.json",
            wait_seconds=60,
        )

    assert not (tmp_path / "candidate-contribution.private.json").exists()
    assert unrelated.read_text(encoding="utf-8") == '{"status":"preserve"}\n'
    assert any("down" in command for command in commands)


def test_pending_intent_is_persisted_before_up_and_cleared_after_recovery(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    env_file, env = _candidate_env(tmp_path)
    _patch_prestart(monkeypatch, env)
    monkeypatch.setattr(
        runner,
        "_candidate_preflight",
        lambda project, port: {"project": project, "loopback_port": port},
    )
    events: list[str] = []

    def register(**_kwargs: object) -> dict[str, object]:
        events.append("pending")
        return {"pending_registered": True}

    def clear(_project: str) -> dict[str, object]:
        events.append("clear")
        return {"pending_cleared": True}

    def run(argv: list[str], **_kwargs: object) -> bytes:
        if "up" in argv:
            events.append("up")
        if "down" in argv:
            events.append("down")
        return b""

    monkeypatch.setattr(runner, "register_candidate_pending", register)
    monkeypatch.setattr(runner, "clear_candidate_pending", clear)
    monkeypatch.setattr(runner, "_run", run)
    monkeypatch.setattr(
        runner,
        "_assert_redis",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("candidate-failed")),
    )
    monkeypatch.setattr(runner, "_assert_candidate_project_absent", lambda _project: {})
    monkeypatch.setattr(runner, "_assert_loopback_port_free", lambda _port: None)
    with pytest.raises(RuntimeError, match="candidate-failed"):
        runner.prove_candidate(
            env_file=env_file,
            compose_file=tmp_path / "compose.yml",
            receipt_path=tmp_path / "runtime.json",
            wait_seconds=60,
        )
    assert events == ["pending", "up", "down", "clear"]


def test_cleanup_detects_any_main_project_snapshot_change(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    env_file, env = _candidate_env(tmp_path)
    _patch_prestart(monkeypatch, env)
    monkeypatch.setattr(
        runner, "_candidate_preflight", lambda project, port: {"project": project}
    )
    before = _baseline_snapshot()
    after = copy.deepcopy(before)
    after["volumes"] = [{"name": "ea_redis-replaced", "driver": "local"}]
    snapshots = iter((before, after))
    monkeypatch.setattr(runner, "_live_snapshot", lambda: next(snapshots))
    monkeypatch.setattr(runner, "_run", lambda _argv, **_kwargs: b"")
    monkeypatch.setattr(
        runner,
        "_assert_redis",
        lambda *_args: (_ for _ in ()).throw(
            RuntimeError("original-candidate-failure")
        ),
    )
    monkeypatch.setattr(runner, "_assert_candidate_project_absent", lambda _project: {})
    monkeypatch.setattr(runner, "_assert_loopback_port_free", lambda _port: None)

    with pytest.raises(
        RuntimeError,
        match="original-candidate-failure;manfred_candidate_recovery_failed:live_ea_changed_or_unhealthy",
    ):
        runner.prove_candidate(
            env_file=env_file,
            compose_file=tmp_path / "compose.yml",
            receipt_path=tmp_path / "runtime.json",
            wait_seconds=60,
        )


def test_post_start_keyboard_interrupt_cleans_candidate_and_is_preserved(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    env_file, env = _candidate_env(tmp_path)
    _patch_prestart(monkeypatch, env)
    monkeypatch.setattr(
        runner, "_candidate_preflight", lambda project, port: {"project": project}
    )
    commands: list[list[str]] = []
    monkeypatch.setattr(
        runner,
        "_run",
        lambda argv, **_kwargs: commands.append(list(argv)) or b"",
    )
    monkeypatch.setattr(
        runner,
        "_assert_redis",
        lambda *_args: (_ for _ in ()).throw(KeyboardInterrupt()),
    )
    monkeypatch.setattr(runner, "_assert_candidate_project_absent", lambda _project: {})
    monkeypatch.setattr(runner, "_assert_loopback_port_free", lambda _port: None)

    with pytest.raises(KeyboardInterrupt):
        runner.prove_candidate(
            env_file=env_file,
            compose_file=tmp_path / "compose.yml",
            receipt_path=tmp_path / "runtime.json",
            wait_seconds=60,
        )
    assert any("down" in command and "--volumes" in command for command in commands)


def test_post_start_sigterm_cleans_candidate_and_is_preserved(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    env_file, env = _candidate_env(tmp_path)
    _patch_prestart(monkeypatch, env)
    monkeypatch.setattr(
        runner,
        "_candidate_preflight",
        lambda project, port: {"project": project, "loopback_port": port},
    )
    commands: list[list[str]] = []
    monkeypatch.setattr(
        runner,
        "_run",
        lambda argv, **_kwargs: commands.append(list(argv)) or b"",
    )
    monkeypatch.setattr(
        runner,
        "_assert_redis",
        lambda *_args: (_ for _ in ()).throw(
            runner.GovernedSignalInterrupt(signal.SIGTERM)
        ),
    )
    monkeypatch.setattr(runner, "_assert_candidate_project_absent", lambda _project: {})
    monkeypatch.setattr(runner, "_assert_loopback_port_free", lambda _port: None)

    with pytest.raises(runner.GovernedSignalInterrupt) as caught:
        runner.prove_candidate(
            env_file=env_file,
            compose_file=tmp_path / "compose.yml",
            receipt_path=tmp_path / "runtime.json",
            wait_seconds=60,
        )
    assert caught.value.signum == signal.SIGTERM
    assert any("down" in command and "--volumes" in command for command in commands)


def test_second_interrupt_cannot_abort_bounded_cleanup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    env_file, env = _candidate_env(tmp_path)
    _patch_prestart(monkeypatch, env)
    monkeypatch.setattr(
        runner,
        "_candidate_preflight",
        lambda project, port: {"project": project, "loopback_port": port},
    )
    absence_checked: list[str] = []
    pending_clear_calls: list[str] = []

    def run(argv: list[str], **_kwargs: object) -> bytes:
        if "down" in argv:
            raise KeyboardInterrupt()
        return b""

    monkeypatch.setattr(runner, "_run", run)
    monkeypatch.setattr(
        runner,
        "_assert_redis",
        lambda *_args: (_ for _ in ()).throw(
            runner.GovernedSignalInterrupt(signal.SIGTERM)
        ),
    )
    monkeypatch.setattr(
        runner,
        "_assert_candidate_project_absent",
        lambda project: absence_checked.append(project) or {},
    )
    monkeypatch.setattr(runner, "_assert_loopback_port_free", lambda _port: None)
    monkeypatch.setattr(
        runner,
        "clear_candidate_pending",
        lambda project: pending_clear_calls.append(project)
        or {"pending_cleared": True},
    )

    with pytest.raises(runner.GovernedSignalInterrupt) as caught:
        runner.prove_candidate(
            env_file=env_file,
            compose_file=tmp_path / "compose.yml",
            receipt_path=tmp_path / "runtime.json",
            wait_seconds=60,
        )
    assert absence_checked == [PROJECT]
    assert pending_clear_calls == []
    assert any(
        "candidate_compose_down_failed" in note
        for note in getattr(caught.value, "__notes__", [])
    )


@pytest.mark.parametrize(
    ("signum", "expected_status"),
    [(signal.SIGTERM, 143), (signal.SIGHUP, 129)],
)
def test_main_maps_governed_signals_to_shell_exit_status(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    signum: int,
    expected_status: int,
) -> None:
    monkeypatch.setattr(
        runner,
        "prove_candidate",
        lambda **_kwargs: (_ for _ in ()).throw(runner.GovernedSignalInterrupt(signum)),
    )
    assert (
        runner.main(
            [
                "--env-file",
                str(tmp_path / "candidate.env"),
                "--receipt",
                str(tmp_path / "runtime.json"),
            ]
        )
        == expected_status
    )


def test_existing_release_is_rehashed_and_mode_bound_before_reuse(
    tmp_path: Path,
) -> None:
    existing = tmp_path / "existing"
    staging = tmp_path / "staging"
    for root in (existing, staging):
        (root / "public_memorials").mkdir(parents=True)
        (root / "public_memorials" / "memorial.json").write_text(
            "{}\n", encoding="utf-8"
        )
        prepare._set_modes(root)
    digest, files = prepare._tree_digest(staging)
    prepare._install_or_verify_release(
        staging=staging,
        release_root=existing,
        projection_sha256=digest,
        projected_files=files,
    )
    assert not staging.exists()

    prepare._make_tree_removable(existing)
    (existing / "public_memorials" / "memorial.json").write_text(
        "changed\n", encoding="utf-8"
    )
    prepare._set_modes(existing)
    replacement = tmp_path / "replacement"
    (replacement / "public_memorials").mkdir(parents=True)
    (replacement / "public_memorials" / "memorial.json").write_text(
        "{}\n", encoding="utf-8"
    )
    prepare._set_modes(replacement)
    with pytest.raises(ValueError, match="existing_release_digest_mismatch"):
        prepare._install_or_verify_release(
            staging=replacement,
            release_root=existing,
            projection_sha256=digest,
            projected_files=files,
        )
