from __future__ import annotations

import contextlib
import copy
import errno
import io
import json
import os
import signal
import socket
from email.message import Message
from pathlib import Path

import pytest

from scripts import prepare_manfred_memorial_candidate as prepare
from scripts import run_manfred_memorial_candidate as runner


PROJECT = "ea-manfred-candidate-20260713-a1b2c3d4"
COMMIT = "a" * 40
IMAGE_ID = "sha256:" + "b" * 64
EXPECTED_OPENAPI_RETIREMENT_OPERATIONS = [
    "POST /v1/internal/governed-spatial-render/build",
    "POST /v1/internal/governed-spatial-render/compose",
]


def _candidate_env(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    env_file = (tmp_path / "candidate.env").resolve()
    release_root = (tmp_path / "releases" / "release-a").resolve()
    runtime_root = (tmp_path / "runtime").resolve()
    release_root.mkdir(parents=True)
    spatial_root = release_root / "public_property_tours"
    spatial_root.mkdir()
    runtime_root.mkdir(parents=True)
    values = {
        "EA_MANFRED_COMPOSE_PROJECT": PROJECT,
        "EA_MANFRED_IMAGE": "ea-runtime:manfred-a1b2c3d4",
        "EA_MANFRED_ENV_FILE": str(env_file),
        "EA_MANFRED_RELEASE_ROOT": str(release_root),
        "EA_MANFRED_RUNTIME_ROOT": str(runtime_root),
        "EA_MANFRED_SPATIAL_HANDOFF_INCLUDED": "0",
        "EA_MANFRED_SPATIAL_RELEASE_ROOT": str(spatial_root),
        "EA_MANFRED_SPATIAL_SHA256": prepare._sha256(b"[]"),
        "EA_MANFRED_SPATIAL_SLUG": "",
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
        {
            "type": "bind",
            "source": env["EA_MANFRED_SPATIAL_RELEASE_ROOT"],
            "target": "/data/public_property_tours",
            "read_only": True,
        },
        {"type": "volume", "source": "artifacts", "target": "/data/artifacts"},
    ]
    declared = {
        "EA_ROLE": "api",
        "EA_PUBLIC_TOUR_DIR": "/data/public_property_tours",
        "EA_TRUST_PROXY_HEADERS": "1",
    }
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
        "_candidate_openapi_contract_snapshot",
        lambda _compose, _environment: copy.deepcopy(_openapi_snapshot()),
    )
    monkeypatch.setattr(
        runner,
        "_assert_candidate_openapi_retired",
        lambda _base: {"status": 404, "public_endpoint_retired": True},
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


def test_internal_transport_probe_is_api_loopback_only_and_parses_security_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[list[str]] = []
    raw = (
        b"HTTP/1.1 200 OK\r\n"
        b"Strict-Transport-Security: max-age=31536000\r\n"
        b"Set-Cookie: ea_memorial_guest=redacted; Secure; HttpOnly\r\n\r\n"
        + f"\n{runner.INTERNAL_TRANSPORT_STATUS_MARKER}200\n".encode("ascii")
    )
    monkeypatch.setattr(
        runner,
        "_run",
        lambda argv, **_kwargs: commands.append(list(argv)) or raw,
    )

    status, body, headers = runner._candidate_api_loopback_request(
        ["docker", "compose", "--project-name", PROJECT],
        {"PATH": "/usr/bin:/bin"},
        "http://127.0.0.1:18091",
        "/memorials/manfred",
        headers={
            "Host": "myexternalbrain.com",
            "X-Forwarded-Proto": "https",
        },
        expected={200},
        follow_redirects=False,
    )

    assert status == 200
    assert body == b""
    assert headers["strict-transport-security"] == "max-age=31536000"
    assert "Secure" in headers["set-cookie"]
    command = commands[0]
    assert command[command.index("exec") + 1 : command.index("curl") + 1] == [
        "-T",
        "api",
        "curl",
    ]
    assert command[command.index("curl") + 1 : command.index("curl") + 6] == [
        "--disable",
        "--noproxy",
        "*",
        "--globoff",
        "--path-as-is",
    ]
    assert command[-1] == "http://127.0.0.1:8090/memorials/manfred"
    assert "--location" not in command
    assert "Host: myexternalbrain.com" in command
    assert "X-Forwarded-Proto: https" in command


def test_internal_transport_probe_rejects_unexpected_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = (
        b"HTTP/1.1 308 Permanent Redirect\r\n"
        b"Location: https://myexternalbrain.com/memorials/manfred\r\n\r\n"
        + f"\n{runner.INTERNAL_TRANSPORT_STATUS_MARKER}308\n".encode("ascii")
    )
    monkeypatch.setattr(runner, "_run", lambda *_args, **_kwargs: raw)
    with pytest.raises(
        RuntimeError,
        match="candidate_http_status_unexpected:/memorials/manfred:308",
    ):
        runner._candidate_api_loopback_request(
            ["docker", "compose"],
            {},
            "http://127.0.0.1:18091",
            "/memorials/manfred",
            expected={200},
            follow_redirects=False,
        )


@pytest.mark.parametrize(
    "raw",
    [
        (
            b"HTTP/1.1 200 OK\r\n"
            b"Strict-Transport-Security: max-age=0\r\n"
            b"Strict-Transport-Security: max-age=31536000\r\n\r\n"
            + f"\n{runner.INTERNAL_TRANSPORT_STATUS_MARKER}200\n".encode("ascii")
        ),
        (
            b"HTTP/1.1 308 Permanent Redirect\r\n"
            b"Location: https://myexternalbrain.com/memorials/manfred\r\n\r\n"
            + f"\n{runner.INTERNAL_TRANSPORT_STATUS_MARKER}200\n".encode("ascii")
        ),
        (
            b"HTTP/1.1 200 OK\r\n"
            b"X-Pad: harmless\r\n"
            b" Strict-Transport-Security: max-age=31536000\r\n\r\n"
            + f"\n{runner.INTERNAL_TRANSPORT_STATUS_MARKER}200\n".encode("ascii")
        ),
        (
            b"HTTP/1.1 200 OK\r\n"
            b"Strict Transport Security: max-age=31536000\r\n\r\n"
            + f"\n{runner.INTERNAL_TRANSPORT_STATUS_MARKER}200\n".encode("ascii")
        ),
        (
            b"HTTP/1.1 200 OK\x00\r\n"
            b"Strict-Transport-Security: max-age=31536000\r\n\r\n"
            + f"\n{runner.INTERNAL_TRANSPORT_STATUS_MARKER}200\n".encode("ascii")
        ),
        (
            b"HTTP/1..1 200 OK\r\n"
            b"Strict-Transport-Security: max-age=31536000\r\n\r\n"
            + f"\n{runner.INTERNAL_TRANSPORT_STATUS_MARKER}200\n".encode("ascii")
        ),
        (
            b"HTTP/1.1 200\r\n"
            b"Strict-Transport-Security: max-age=31536000\r\n\r\n"
            + f"\n{runner.INTERNAL_TRANSPORT_STATUS_MARKER}200\n".encode("ascii")
        ),
        (
            b"HTTP/1.1 200 OK\n"
            b"Strict-Transport-Security: max-age=31536000\n\n"
            + f"\n{runner.INTERNAL_TRANSPORT_STATUS_MARKER}200\n".encode("ascii")
        ),
        (
            b"HTTP/1.1 200 OK\r\n"
            b"Strict-Transport-Security: max-age=31536000\n\n"
            + f"\n{runner.INTERNAL_TRANSPORT_STATUS_MARKER}200\n".encode("ascii")
        ),
    ],
)
def test_internal_transport_probe_rejects_duplicate_or_status_spoofing(
    raw: bytes,
) -> None:
    with pytest.raises(
        RuntimeError,
        match="manfred_candidate_internal_transport_probe_invalid",
    ):
        runner._parse_internal_transport_headers(raw)


@pytest.mark.parametrize(
    "status_line",
    [
        "HTTP/. 200 OK",
        "HTTP/1 200 OK",
        "HTTP/1. 200 OK",
        "HTTP/1..1 200 OK",
        "HTTP/1.1 200",
    ],
)
def test_internal_transport_probe_rejects_malformed_http_versions(
    status_line: str,
) -> None:
    raw = (
        f"{status_line}\r\nStrict-Transport-Security: max-age=31536000\r\n\r\n"
        f"\n{runner.INTERNAL_TRANSPORT_STATUS_MARKER}200\n"
    ).encode("ascii")
    with pytest.raises(
        RuntimeError,
        match="manfred_candidate_internal_transport_probe_invalid",
    ):
        runner._parse_internal_transport_headers(raw)


@pytest.mark.parametrize(
    "path",
    [
        "/memorials/manfred#not-sent-by-http",
        "/memorials/manfred#",
        "/memorials/../manfred",
        "/memorials/manfred\t?from=ea-transport-verifier",
        "/mémorials/manfred",
    ],
)
def test_internal_transport_probe_rejects_paths_curl_cannot_send_exactly(
    monkeypatch: pytest.MonkeyPatch,
    path: str,
) -> None:
    monkeypatch.setattr(
        runner,
        "_run",
        lambda *_args, **_kwargs: pytest.fail("invalid path must fail before curl"),
    )
    with pytest.raises(
        RuntimeError,
        match="manfred_candidate_internal_transport_request_invalid",
    ):
        runner._candidate_api_loopback_request(
            ["docker", "compose"],
            {},
            "http://127.0.0.1:18091",
            path,
            expected={200},
            follow_redirects=False,
        )


def test_internal_transport_probe_rejects_case_insensitive_outgoing_duplicates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runner,
        "_run",
        lambda *_args, **_kwargs: pytest.fail("duplicate headers must fail before curl"),
    )
    with pytest.raises(
        RuntimeError,
        match="manfred_candidate_internal_transport_request_invalid",
    ):
        runner._candidate_api_loopback_request(
            ["docker", "compose"],
            {},
            "http://127.0.0.1:18091",
            "/memorials/manfred",
            headers={"Host": "myexternalbrain.com", "host": "spoof.invalid"},
            expected={200},
            follow_redirects=False,
        )


def test_spatial_bind_environment_and_api_only_scope_fail_closed(
    tmp_path: Path,
) -> None:
    env_file, env = _candidate_env(tmp_path)
    payload, source = _compose_payloads(env_file, env)

    missing_bind = copy.deepcopy(payload)
    missing_bind["services"]["api"]["volumes"] = [
        mount
        for mount in missing_bind["services"]["api"]["volumes"]
        if mount.get("target") != "/data/public_property_tours"
    ]
    with pytest.raises(RuntimeError, match="compose_mount_root_mismatch"):
        runner._assert_compose_isolation(
            missing_bind, source, env=env, env_file=env_file
        )

    wrong_environment = copy.deepcopy(source)
    wrong_environment["services"]["api"]["environment"]["EA_PUBLIC_TOUR_DIR"] = (
        "/tmp/public-tours"
    )
    with pytest.raises(RuntimeError, match="spatial_compose_environment_invalid"):
        runner._assert_compose_isolation(
            payload, wrong_environment, env=env, env_file=env_file
        )

    gateway_bind = copy.deepcopy(payload)
    gateway_bind["services"]["gateway"]["volumes"] = [
        {
            "type": "bind",
            "source": env["EA_MANFRED_SPATIAL_RELEASE_ROOT"],
            "target": "/data/public_property_tours",
            "read_only": True,
        }
    ]
    with pytest.raises(RuntimeError, match="spatial_compose_scope_invalid"):
        runner._assert_compose_isolation(
            gateway_bind, source, env=env, env_file=env_file
        )

    invalid_env = dict(env)
    invalid_env.pop("EA_MANFRED_SPATIAL_SHA256")
    env_file.write_text(
        "".join(f"{name}={value}\n" for name, value in sorted(invalid_env.items())),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="env_allowlist_invalid"):
        runner._assert_env_allowlist(env_file)


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
    spatial_root = release_root / "public_property_tours"
    spatial_sha256, spatial_files = prepare._tree_digest(spatial_root)
    receipt_path = release_root.parent.parent / "receipts" / f"{release_root.name}.json"
    receipt_path.parent.mkdir(parents=True)
    spatial_receipt_path = receipt_path.with_name(f"{release_root.name}.spatial.json")
    spatial_receipt = {
        "schema": prepare.SPATIAL_PROJECTION_SCHEMA,
        "status": "pass",
        "created_at": "2026-07-14T00:00:00Z",
        "release_id": release_root.name,
        "spatial_handoff_included": False,
        "slug": "",
        "spatial_release_root": str(spatial_root),
        "spatial_projection_sha256": spatial_sha256,
        "file_count": 0,
        "projection_bytes": 0,
        "files": spatial_files,
        "asset_paths": [],
        "viewer_relpath": "",
        "proof_relpath": "",
        "route_labels": [],
        "upstream_publication_authority": {},
        "upstream_publication_authority_sha256": "",
        "upstream_public_activation_authority": False,
        "upstream_package_sha256": "",
        "upstream_tour_manifest_sha256": "",
        "pre_authority_manifest_canonical_sha256": "",
        "review_evidence": {},
        "source_verifier": {},
        "candidate_handoff_authorized": False,
        "public_activation_authority": False,
    }
    spatial_receipt_path.write_bytes(prepare._receipt_bytes(spatial_receipt))
    spatial_receipt_path.chmod(0o600)
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
                "spatial_handoff_included": False,
                "spatial_slug": "",
                "spatial_release_root": str(spatial_root),
                "spatial_projection_sha256": spatial_sha256,
                "spatial_file_count": 0,
                "spatial_projection_bytes": 0,
                "spatial_receipt_path": str(spatial_receipt_path),
                "spatial_receipt_sha256": prepare._sha256(
                    prepare._receipt_bytes(spatial_receipt)
                ),
                "spatial_upstream_public_activation_authority": False,
                "spatial_ea_public_activation_authority": False,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    receipt_path.chmod(0o600)

    evidence = runner._projection_evidence(env)
    assert evidence == {
        "release_id": release_root.name,
        "release_root": str(release_root),
        "projection_sha256": projection_sha256,
        "projection_commit": COMMIT,
        "prepared_image_locator": env["EA_MANFRED_IMAGE"],
        "prepared_image_id": IMAGE_ID,
        "projection_tree_revalidated": True,
        "spatial_handoff": {
            "included": False,
            "slug": "",
            "release_root": str(spatial_root),
            "projection_sha256": spatial_sha256,
            "file_count": 0,
            "projection_bytes": 0,
            "receipt_path": str(spatial_receipt_path),
            "receipt_sha256": prepare._sha256(prepare._receipt_bytes(spatial_receipt)),
            "projection_tree_revalidated": True,
            "ea_public_activation_authority": False,
        },
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


def test_cleanup_port_wait_retries_transient_release_race(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts: list[int] = []
    sleeps: list[float] = []

    def assert_port_free(port: int) -> None:
        attempts.append(port)
        if len(attempts) < 3:
            raise RuntimeError("manfred_candidate_loopback_port_unavailable")

    monkeypatch.setattr(
        runner, "_assert_loopback_port_not_listening", assert_port_free
    )
    monkeypatch.setattr(runner.time, "sleep", sleeps.append)

    runner._wait_for_loopback_port_not_listening(
        18091,
        timeout_seconds=1.0,
        poll_seconds=0.1,
    )

    assert attempts == [18091, 18091, 18091]
    assert sleeps == [0.1, 0.1]


def test_cleanup_port_wait_fails_closed_after_bounded_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [100.0]
    attempts: list[int] = []
    sleeps: list[float] = []

    def assert_port_free(port: int) -> None:
        attempts.append(port)
        raise RuntimeError("manfred_candidate_loopback_port_unavailable")

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    monkeypatch.setattr(
        runner, "_assert_loopback_port_not_listening", assert_port_free
    )
    monkeypatch.setattr(runner.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(runner.time, "sleep", sleep)

    with pytest.raises(RuntimeError, match="loopback_port_unavailable"):
        runner._wait_for_loopback_port_not_listening(
            18091,
            timeout_seconds=0.25,
            poll_seconds=0.1,
        )

    assert attempts == [18091, 18091, 18091, 18091]
    assert sum(sleeps) == pytest.approx(0.25)
    assert max(sleeps) <= 0.1


def test_cleanup_distinguishes_a_listener_from_a_nonlistening_bound_socket() -> None:
    bound = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        bound.bind(("127.0.0.1", 0))
        bound_port = int(bound.getsockname()[1])
        with pytest.raises(RuntimeError, match="loopback_port_unavailable"):
            runner._assert_loopback_port_free(bound_port)
        runner._assert_loopback_port_not_listening(bound_port)

        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        with pytest.raises(RuntimeError, match="loopback_port_still_listening"):
            runner._assert_loopback_port_not_listening(
                int(listener.getsockname()[1])
            )
    finally:
        bound.close()
        listener.close()


def test_cleanup_fails_closed_on_ambiguous_connect_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Probe:
        def settimeout(self, _seconds: float) -> None:
            return None

        def connect_ex(self, _address: tuple[str, int]) -> int:
            return errno.EAGAIN

        def close(self) -> None:
            return None

    monkeypatch.setattr(runner, "_host_tcp_listener_present", lambda _port: False)
    monkeypatch.setattr(runner.socket, "socket", lambda *_args: Probe())
    with pytest.raises(RuntimeError, match="loopback_port_still_listening"):
        runner._assert_loopback_port_not_listening(18091)


def test_preflight_port_check_remains_immediate_and_does_not_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts: list[int] = []
    monkeypatch.setattr(
        runner,
        "_assert_candidate_project_absent",
        lambda project: {"project": project},
    )

    def assert_port_free(port: int) -> None:
        attempts.append(port)
        raise RuntimeError("manfred_candidate_loopback_port_unavailable")

    monkeypatch.setattr(runner, "_assert_loopback_port_free", assert_port_free)
    monkeypatch.setattr(
        runner,
        "_wait_for_loopback_port_not_listening",
        lambda _port: pytest.fail("preflight must not use the cleanup retry"),
    )

    with pytest.raises(RuntimeError, match="loopback_port_unavailable"):
        runner._candidate_preflight(PROJECT, 18091)

    assert attempts == [18091]


def test_same_project_different_ports_conflict_on_project_lock() -> None:
    project = "ea-manfred-candidate-project-lock-a1b2c3d4"
    with runner._hold_candidate_locks(project, 18991):
        with pytest.raises(RuntimeError, match="project_lock_held"):
            with runner._hold_candidate_locks(project, 18992):
                pytest.fail("same candidate project acquired twice")


def test_retargeted_image_locator_is_rejected_before_candidate_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projection = {
        "prepared_image_locator": "ea-runtime:manfred-a1b2c3d4",
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
            "/v1/internal/governed-spatial-render/build": {
                "post": {"responses": {"202": {}}}
            },
            "/v1/internal/governed-spatial-render/compose": {
                "post": {"responses": {"200": {}}}
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


def _retire_governed_spatial_operations(document: dict[str, object]) -> None:
    for operation in EXPECTED_OPENAPI_RETIREMENT_OPERATIONS:
        _method, path = operation.split(" ", 1)
        document["paths"].pop(path)


def test_candidate_openapi_snapshot_is_internal_bounded_and_docs_retired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = _meaningful_openapi_document()
    _retire_governed_spatial_operations(document)
    envelope = {
        "docs_url": None,
        "document": document,
        "openapi_url": None,
        "redoc_url": None,
    }
    commands: list[list[str]] = []
    environments: list[dict[str, str]] = []

    def run(
        argv: list[str],
        *,
        timeout: int,
        environment: dict[str, str],
        stdout_limit: int,
        stderr_limit: int,
        output_limit_error: str,
    ) -> bytes:
        commands.append(list(argv))
        environments.append(environment)
        assert timeout == 120
        assert stdout_limit == runner.MAX_OPENAPI_DOCUMENT_BYTES
        assert stderr_limit == runner.MAX_OPENAPI_SNAPSHOT_STDERR_BYTES
        assert output_limit_error.endswith("snapshot_output_too_large")
        return json.dumps(envelope, separators=(",", ":"), sort_keys=True).encode(
            "utf-8"
        )

    monkeypatch.setattr(runner, "_run_bounded_output", run)
    contract, evidence = runner._candidate_openapi_contract_snapshot(
        ["docker", "compose", "--project-name", PROJECT],
        {"PATH": "/usr/bin:/bin"},
    )

    assert contract == runner._canonical_openapi_contract(document)
    assert evidence["snapshot_source"] == runner.CANDIDATE_OPENAPI_SNAPSHOT_SOURCE
    assert evidence["public_docs_config_retired"] is True
    assert evidence["operation_count"] == 2
    assert environments == [{"PATH": "/usr/bin:/bin"}]
    assert commands[0][-6:-3] == ["exec", "-T", "api"]
    assert commands[0][-3:-1] == ["python", "-c"]
    assert commands[0][-1] == runner.CANDIDATE_OPENAPI_SNAPSHOT_SCRIPT

    exposed = copy.deepcopy(envelope)
    exposed["openapi_url"] = "/openapi.json"
    monkeypatch.setattr(
        runner,
        "_run_bounded_output",
        lambda *_args, **_kwargs: json.dumps(exposed).encode("utf-8"),
    )
    with pytest.raises(RuntimeError, match="internal_openapi_docs_exposed"):
        runner._candidate_openapi_contract_snapshot(["docker", "compose"], {})


def test_candidate_openapi_public_endpoint_must_be_structured_secure_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    correlation_id = "6c43cd88-b5a4-4ec1-914d-b723a9668197"
    body = json.dumps(
        {
            "error": {
                "code": "not_found",
                "message": "not_found",
                "details": "not_found",
                "correlation_id": correlation_id,
            }
        },
        separators=(",", ":"),
    ).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Content-Security-Policy": "frame-ancestors 'none'; base-uri 'self'",
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "X-Correlation-ID": correlation_id,
    }

    class Opener:
        def open(self, request: object, *, timeout: int) -> object:
            assert timeout == 20
            raise runner.urllib.error.HTTPError(
                getattr(request, "full_url"),
                404,
                "Not Found",
                headers,
                io.BytesIO(body),
            )

    monkeypatch.setattr(
        runner.urllib.request,
        "build_opener",
        lambda *_handlers: Opener(),
    )
    evidence = runner._assert_candidate_openapi_retired(
        "http://127.0.0.1:18091"
    )
    assert evidence["status"] == 404
    assert evidence["public_endpoint_retired"] is True
    assert evidence["correlation_header_matches_body"] is True

    headers["X-Frame-Options"] = "SAMEORIGIN"
    with pytest.raises(RuntimeError, match="openapi_retirement_contract_invalid"):
        runner._assert_candidate_openapi_retired("http://127.0.0.1:18091")
    headers["X-Frame-Options"] = "DENY"

    for name, hostile_value in (
        ("Content-Type", "application/jsonp"),
        (
            "Content-Security-Policy",
            "default-src frame-ancestors 'none'",
        ),
        (
            "Content-Security-Policy",
            "frame-ancestors 'self'; frame-ancestors 'none'",
        ),
    ):
        expected_value = headers[name]
        headers[name] = hostile_value
        with pytest.raises(
            RuntimeError, match="openapi_retirement_contract_invalid"
        ):
            runner._assert_candidate_openapi_retired(
                "http://127.0.0.1:18091"
            )
        headers[name] = expected_value


@pytest.mark.parametrize("oversized_stream", ["stdout", "stderr"])
def test_candidate_openapi_snapshot_host_capture_is_memory_bounded(
    monkeypatch: pytest.MonkeyPatch,
    oversized_stream: str,
) -> None:
    class Completed:
        returncode = 0

    def run(
        _argv: list[str],
        *,
        stdout: object,
        stderr: object,
        **_kwargs: object,
    ) -> Completed:
        if oversized_stream == "stdout":
            stdout.write(b"12345")
        else:
            stderr.write(b"12345")
        return Completed()

    monkeypatch.setattr(runner.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="bounded-output-rejected"):
        runner._run_bounded_output(
            ["safe-command"],
            timeout=1,
            environment={"PATH": "/usr/bin:/bin"},
            stdout_limit=4,
            stderr_limit=4,
            output_limit_error="bounded-output-rejected",
        )


@pytest.mark.parametrize(
    ("duplicate_name", "hostile_value"),
    [
        ("Content-Type", "text/plain"),
        ("Content-Security-Policy", "default-src *"),
        ("X-Content-Type-Options", "sniff"),
        ("X-Correlation-ID", "hostile-correlation"),
        ("X-Frame-Options", "SAMEORIGIN"),
    ],
)
def test_candidate_openapi_retirement_rejects_duplicate_critical_headers(
    monkeypatch: pytest.MonkeyPatch,
    duplicate_name: str,
    hostile_value: str,
) -> None:
    correlation_id = "6c43cd88-b5a4-4ec1-914d-b723a9668197"
    body = json.dumps(
        {
            "error": {
                "code": "not_found",
                "message": "not_found",
                "details": "not_found",
                "correlation_id": correlation_id,
            }
        },
        separators=(",", ":"),
    ).encode("utf-8")
    expected_headers = {
        "Content-Type": "application/json",
        "Content-Security-Policy": "frame-ancestors 'none'; base-uri 'self'",
        "X-Content-Type-Options": "nosniff",
        "X-Correlation-ID": correlation_id,
        "X-Frame-Options": "DENY",
    }
    headers = Message()
    for name, value in expected_headers.items():
        if name.lower() == duplicate_name.lower():
            headers[name] = hostile_value
        headers[name] = value

    class Opener:
        def open(self, request: object, *, timeout: int) -> object:
            assert timeout == 20
            raise runner.urllib.error.HTTPError(
                getattr(request, "full_url"),
                404,
                "Not Found",
                headers,
                io.BytesIO(body),
            )

    monkeypatch.setattr(
        runner.urllib.request,
        "build_opener",
        lambda *_handlers: Opener(),
    )
    with pytest.raises(RuntimeError, match="openapi_retirement_headers_ambiguous"):
        runner._assert_candidate_openapi_retired("http://127.0.0.1:18091")


def test_openapi_contract_allows_additions_and_persists_only_bounded_evidence() -> None:
    live_document = _meaningful_openapi_document()
    candidate_document = copy.deepcopy(live_document)
    _retire_governed_spatial_operations(candidate_document)
    candidate_document["paths"]["/candidate-only"] = {
        "post": {"security": [], "responses": {"204": {}}}
    }
    live = runner._canonical_openapi_contract(live_document)
    candidate = runner._canonical_openapi_contract(candidate_document)

    assert runner._assert_openapi_contract_preserved(live, candidate) == {
        "missing_or_changed_operation_count": 0,
        "missing_or_changed_schema_count": 0,
        "missing_or_changed_security_scheme_count": 0,
        "retirement_policy_id": (
            "ea.openapi.safety-retirement.governed-spatial-routes.v1"
        ),
        "retirement_allowed_operations": EXPECTED_OPENAPI_RETIREMENT_OPERATIONS,
        "retired_operations": EXPECTED_OPENAPI_RETIREMENT_OPERATIONS,
        "retired_operation_count": 2,
        "retirement_policy_exact_match": True,
        "compatible_evolution_policy_id": (
            "ea.openapi.compatible-evolution.version-remote-reachability.v1"
        ),
        "compatible_evolution_allowed_operations": ["GET /version"],
        "compatible_evolved_operations": [],
        "compatible_evolved_operation_count": 0,
        "compatible_evolution_policy_exact_match": True,
        "candidate_preserves_live_contract": True,
    }
    assert list(runner.OPENAPI_RETIREMENT_ALLOWED_OPERATIONS) == (
        EXPECTED_OPENAPI_RETIREMENT_OPERATIONS
    )
    assert not any(
        "*" in operation for operation in runner.OPENAPI_RETIREMENT_ALLOWED_OPERATIONS
    )
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


def _add_version_openapi_operation(
    document: dict[str, object],
    *,
    additional_properties: object,
) -> None:
    document["paths"]["/version"] = {
        "get": {
            "security": [],
            "responses": {
                "200": {
                    "description": "Successful Response",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "title": "Response Version Version Get",
                                "additionalProperties": additional_properties,
                            }
                        }
                    },
                }
            },
        }
    }


def test_openapi_contract_allows_only_precise_version_boolean_evolution() -> None:
    live_document = _meaningful_openapi_document()
    _add_version_openapi_operation(
        live_document,
        additional_properties={"type": "string"},
    )
    candidate_document = copy.deepcopy(live_document)
    _retire_governed_spatial_operations(candidate_document)
    candidate_document["paths"]["/version"]["get"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]["additionalProperties"] = {
        "anyOf": [{"type": "string"}, {"type": "boolean"}]
    }

    result = runner._assert_openapi_contract_preserved(
        runner._canonical_openapi_contract(live_document),
        runner._canonical_openapi_contract(candidate_document),
    )

    assert result["compatible_evolution_policy_id"] == (
        "ea.openapi.compatible-evolution.version-remote-reachability.v1"
    )
    assert result["compatible_evolution_allowed_operations"] == ["GET /version"]
    assert result["compatible_evolved_operations"] == ["GET /version"]
    assert result["compatible_evolved_operation_count"] == 1
    assert result["missing_or_changed_operation_count"] == 0


@pytest.mark.parametrize(
    "case",
    [
        "unconstrained",
        "integer_instead_of_boolean",
        "extra_variant",
        "extra_schema_keyword",
        "other_operation_drift",
    ],
)
def test_openapi_version_evolution_policy_rejects_broader_drift(case: str) -> None:
    live_document = _meaningful_openapi_document()
    _add_version_openapi_operation(
        live_document,
        additional_properties={"type": "string"},
    )
    candidate_document = copy.deepcopy(live_document)
    _retire_governed_spatial_operations(candidate_document)
    candidate_schema = candidate_document["paths"]["/version"]["get"][
        "responses"
    ]["200"]["content"]["application/json"]["schema"]
    candidate_schema["additionalProperties"] = {
        "anyOf": [{"type": "string"}, {"type": "boolean"}]
    }
    if case == "unconstrained":
        candidate_schema["additionalProperties"] = True
    elif case == "integer_instead_of_boolean":
        candidate_schema["additionalProperties"] = {
            "anyOf": [{"type": "string"}, {"type": "integer"}]
        }
    elif case == "extra_variant":
        candidate_schema["additionalProperties"]["anyOf"].append(
            {"type": "null"}
        )
    elif case == "extra_schema_keyword":
        candidate_schema["additionalProperties"]["not"] = {"type": "null"}
    else:
        candidate_document["paths"]["/version"]["get"]["responses"]["200"][
            "description"
        ] = "Changed response"

    with pytest.raises(RuntimeError, match="openapi_contract_regression"):
        runner._assert_openapi_contract_preserved(
            runner._canonical_openapi_contract(live_document),
            runner._canonical_openapi_contract(candidate_document),
        )


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
    _retire_governed_spatial_operations(candidate_document)
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


@pytest.mark.parametrize("case", ["retained_equivalent", "live_policy_stale"])
def test_openapi_retirement_rejects_partial_or_stale_policy(case: str) -> None:
    live_document = _meaningful_openapi_document()
    candidate_document = copy.deepcopy(live_document)
    if case == "retained_equivalent":
        candidate_document["paths"].pop("/v1/internal/governed-spatial-render/compose")
    else:
        live_document["paths"].pop("/v1/internal/governed-spatial-render/build")
        _retire_governed_spatial_operations(candidate_document)

    live = runner._canonical_openapi_contract(live_document)
    candidate = runner._canonical_openapi_contract(candidate_document)
    with pytest.raises(RuntimeError, match="openapi_contract_regression"):
        runner._assert_openapi_contract_preserved(live, candidate)


def test_openapi_retirement_does_not_waive_changed_retained_route() -> None:
    live_document = _meaningful_openapi_document()
    candidate_document = copy.deepcopy(live_document)
    candidate_document["paths"].pop("/v1/internal/governed-spatial-render/compose")
    candidate_document["paths"]["/v1/internal/governed-spatial-render/build"]["post"][
        "responses"
    ] = {"500": {}}

    live = runner._canonical_openapi_contract(live_document)
    candidate = runner._canonical_openapi_contract(candidate_document)
    with pytest.raises(RuntimeError, match="openapi_contract_regression"):
        runner._assert_openapi_contract_preserved(live, candidate)


def test_openapi_retirement_rejects_any_other_operation_omission() -> None:
    live_document = _meaningful_openapi_document()
    candidate_document = copy.deepcopy(live_document)
    _retire_governed_spatial_operations(candidate_document)
    candidate_document["paths"].pop("/healthz")

    live = runner._canonical_openapi_contract(live_document)
    candidate = runner._canonical_openapi_contract(candidate_document)
    with pytest.raises(RuntimeError, match="openapi_contract_regression"):
        runner._assert_openapi_contract_preserved(live, candidate)


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
    monkeypatch.setattr(
        runner, "_assert_loopback_port_not_listening", lambda _port: None
    )
    runtime_receipt = tmp_path / "runtime.json"
    runtime_receipt.write_text('{"status":"stale-pass"}\n', encoding="utf-8")

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
    monkeypatch.setattr(
        runner, "_assert_loopback_port_not_listening", lambda _port: None
    )

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


def test_cleanup_reports_persistent_bound_port_without_weakening_absence_proof(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    env_file, env = _candidate_env(tmp_path)
    _patch_prestart(monkeypatch, env)
    monkeypatch.setattr(
        runner, "_candidate_preflight", lambda project, port: {"project": project}
    )
    absence_checks: list[str] = []
    monkeypatch.setattr(runner, "_run", lambda _argv, **_kwargs: b"")
    monkeypatch.setattr(
        runner,
        "_assert_redis",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("candidate-smoke-failed")),
    )
    monkeypatch.setattr(
        runner,
        "_assert_candidate_project_absent",
        lambda project: absence_checks.append(project) or {},
    )
    monkeypatch.setattr(
        runner,
        "_wait_for_loopback_port_not_listening",
        lambda _port: (_ for _ in ()).throw(
            RuntimeError("manfred_candidate_loopback_port_unavailable")
        ),
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "candidate-smoke-failed;manfred_candidate_recovery_failed:"
            "candidate_port_remains_bound"
        ),
    ):
        runner.prove_candidate(
            env_file=env_file,
            compose_file=tmp_path / "compose.yml",
            receipt_path=tmp_path / "runtime.json",
            wait_seconds=60,
        )

    assert absence_checks == [PROJECT]


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
    monkeypatch.setattr(
        runner, "_assert_loopback_port_not_listening", lambda _port: None
    )

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
    monkeypatch.setattr(
        runner, "_assert_loopback_port_not_listening", lambda _port: None
    )

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

    with pytest.raises(runner.GovernedSignalInterrupt) as caught:
        runner.prove_candidate(
            env_file=env_file,
            compose_file=tmp_path / "compose.yml",
            receipt_path=tmp_path / "runtime.json",
            wait_seconds=60,
        )
    assert absence_checked == [PROJECT]
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
