from __future__ import annotations

import contextlib
import copy
import errno
import inspect
import io
import json
import os
import signal
import socket
import stat
from email.message import Message
from pathlib import Path

import pytest

from scripts import build_manfred_memorial_image as image_builder
from scripts import prepare_manfred_memorial_candidate as prepare
from scripts import run_manfred_memorial_candidate as runner


PROJECT = "ea-manfred-candidate-20260713-a1b2c3d4"
COMMIT = "a" * 40
IMAGE_ID = "sha256:" + "b" * 64
EXPECTED_OPENAPI_RETIREMENT_OPERATIONS = [
    "POST /v1/internal/governed-spatial-render/build",
    "POST /v1/internal/governed-spatial-render/compose",
]


class _FakeCandidateVexpLease:
    def __init__(self, boundary: str) -> None:
        self.authority_evidence = {
            "status": "pass",
            "phase": "pre_mutation",
            "boundary": boundary,
        }

    def command_timeout(self, requested_seconds: float) -> float:
        return requested_seconds


class _FakeCandidateVexpAuthority:
    def __init__(self) -> None:
        self.mutation_boundaries: list[str] = []

    def require_current(self) -> dict[str, object]:
        return {
            "status": "pass",
            "phase": "entry",
            "boundary": "candidate_entry",
        }

    @contextlib.contextmanager
    def mutation(self, boundary: str, *, minimum_validity_seconds: float):
        assert minimum_validity_seconds > 0
        self.mutation_boundaries.append(boundary)
        yield _FakeCandidateVexpLease(boundary)

    @contextlib.contextmanager
    def finalization(self):
        yield {
            "status": "pass",
            "phase": "finalization",
            "boundary": "candidate_receipt_publication",
        }


def _candidate_env(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    env_file = (tmp_path / "candidate.env").resolve()
    release_root = (tmp_path / "releases" / "release-a").resolve()
    runtime_root = (tmp_path / "runtime").resolve()
    release_root.mkdir(parents=True)
    authority_root = release_root / prepare.CANDIDATE_RELEASE_AUTHORITY_DIRNAME
    authority_root.mkdir()
    runtime_root.mkdir(parents=True)
    values = {
        "EA_MANFRED_COMPOSE_PROJECT": PROJECT,
        "EA_MANFRED_COMMIT": COMMIT,
        "EA_MANFRED_DEPLOYMENT_ID": f"{PROJECT}-{COMMIT[:12]}",
        "EA_MANFRED_IMAGE": f"ea-runtime:manfred-{COMMIT}",
        "EA_MANFRED_ENV_FILE": str(env_file),
        "EA_MANFRED_RELEASE_ROOT": str(release_root),
        "EA_MANFRED_RELEASE_AUTHORITY_ROOT": str(authority_root),
        "EA_MANFRED_RUNTIME_ROOT": str(runtime_root),
        "EA_MANFRED_MEMORIAL_SURFACE": prepare.MEMORIAL_SURFACE,
        "EA_MANFRED_SPATIAL_SCOPE": prepare.SPATIAL_SCOPE,
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
            "source": env["EA_MANFRED_RELEASE_AUTHORITY_ROOT"],
            "target": "/data/release-authority",
            "read_only": True,
        },
        {"type": "volume", "source": "artifacts", "target": "/data/artifacts"},
    ]
    declared = runner._expected_candidate_api_environment(env)
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
    monkeypatch.setattr(
        runner,
        "candidate_vexp_authority",
        lambda **_kwargs: _FakeCandidateVexpAuthority(),
    )
    monkeypatch.setattr(
        runner,
        "_assert_env_allowlist",
        lambda _path, *, environment_bytes=None: dict(env),
    )

    compose_bytes = b"name: governed-candidate\nservices: {}\n"

    def compose_attestation(
        compose_file: Path, *, expected_commit: str
    ) -> dict[str, object]:
        canonical_path = str(compose_file.expanduser().resolve())
        return {
            "canonical_relative_path": (
                runner.CANDIDATE_COMPOSE_RELATIVE_PATH.as_posix()
            ),
            "canonical_source_path": canonical_path,
            "candidate_commit": expected_commit,
            "git_blob_oid": "c" * 40,
            "sha256": prepare._sha256(compose_bytes),
            "size_bytes": len(compose_bytes),
            "canonical_path_enforced": True,
            "tracked_blob_bytes_enforced": True,
        }

    monkeypatch.setattr(runner, "_candidate_compose_attestation", compose_attestation)
    monkeypatch.setattr(
        runner,
        "_candidate_compose_source_snapshot",
        lambda compose_file, *, expected_commit: (
            compose_attestation(compose_file, expected_commit=expected_commit),
            compose_bytes,
        ),
    )
    monkeypatch.setattr(
        runner,
        "_projection_evidence",
        lambda _env: {
            "release_id": "release-a",
            "release_root": env["EA_MANFRED_RELEASE_ROOT"],
            "projection_sha256": "d" * 64,
            "projection_files": [],
            "projection_file_count": 0,
            "projection_bytes": 0,
            "projection_commit": COMMIT,
            "prepared_image_locator": env["EA_MANFRED_IMAGE"],
            "prepared_image_id": IMAGE_ID,
            "projection_tree_revalidated": True,
            "memorial_surface": prepare.MEMORIAL_SURFACE,
            "spatial_scope": prepare.SPATIAL_SCOPE,
            "public_property_tours_packaged": False,
            "memorial_spatial_receipt_generated": False,
        },
    )
    monkeypatch.setattr(
        runner,
        "_candidate_runtime_projection_evidence",
        lambda **_kwargs: {
            "schema": runner.RUNTIME_PROJECTION_SCHEMA,
            "projection_sha256": "d" * 64,
            "file_count": 0,
            "projection_bytes": 0,
            "mount_roots": [
                "/data/memorial/public",
                "/data/memorial/private",
                "/data/memorial/archive",
                "/data/release-authority",
            ],
            "memorial_surface": prepare.MEMORIAL_SURFACE,
            "spatial_scope": prepare.SPATIAL_SCOPE,
            "public_property_tours_packaged": False,
            "runtime_bytes_match_prepared_projection": True,
        },
    )
    monkeypatch.setattr(runner, "_rendered_compose", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        runner, "_assert_compose_isolation", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(runner, "_hold_candidate_locks", _fake_candidate_locks)
    monkeypatch.setattr(
        runner,
        "candidate_registry_recovery_state",
        lambda **_kwargs: {"state": "absent"},
    )
    monkeypatch.setattr(
        runner,
        "clear_candidate_pending_exact",
        lambda **_kwargs: {"pending_cleared": True},
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
    monkeypatch.setattr(
        runner,
        "register_candidate_receipt",
        lambda _path, **_kwargs: {"registered": True},
    )
    monkeypatch.setattr(
        runner,
        "_assert_prepared_image_locator",
        lambda _projection: {
            "locator": env["EA_MANFRED_IMAGE"],
            "resolved_image_id": IMAGE_ID,
            "revision_label": COMMIT,
            "used_for_attestation_only": True,
            "consumed_by_compose": False,
        },
    )
    monkeypatch.setattr(runner, "_live_snapshot", _baseline_snapshot)
    monkeypatch.setattr(runner, "_assert_live_healthy", lambda _snapshot: None)
    monkeypatch.setattr(runner, "_assert_live_http", lambda: None)
    monkeypatch.setattr(
        runner,
        "_candidate_openapi_contract_snapshot",
        lambda _compose, _environment, **_kwargs: copy.deepcopy(_openapi_snapshot()),
    )
    monkeypatch.setattr(
        runner,
        "_assert_candidate_openapi_retired",
        lambda _base: {"status": 404, "public_endpoint_retired": True},
    )
    monkeypatch.setattr(
        runner,
        "_spatial_handoff_runtime_proof",
        lambda *_args, **_kwargs: {
            "included": True,
            "routes_required": True,
            "ea_public_activation_authority": False,
            "upstream_public_activation_authority": True,
        },
    )


def test_candidate_authority_entry_denial_stops_before_docker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    env_file, env = _candidate_env(tmp_path)
    _patch_prestart(monkeypatch, env)

    class DeniedAuthority:
        def require_current(self) -> dict[str, object]:
            raise RuntimeError("candidate-authority-denied")

    monkeypatch.setattr(
        runner,
        "_run",
        lambda *_args, **_kwargs: pytest.fail(
            "Docker must not run after candidate authority denial"
        ),
    )

    with pytest.raises(RuntimeError, match="candidate-authority-denied"):
        runner.prove_candidate(
            env_file=env_file,
            compose_file=tmp_path / "compose.yml",
            receipt_path=tmp_path / "runtime.json",
            wait_seconds=60,
            vexp_authority=DeniedAuthority(),
        )


def test_candidate_up_boundary_denial_never_runs_compose_up(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    env_file, env = _candidate_env(tmp_path)
    _patch_prestart(monkeypatch, env)
    commands: list[list[str]] = []
    pending_cleared: list[str] = []

    class DeniedUpAuthority(_FakeCandidateVexpAuthority):
        @contextlib.contextmanager
        def mutation(self, boundary: str, *, minimum_validity_seconds: float):
            assert boundary == "before_candidate_up"
            assert minimum_validity_seconds > 0
            raise RuntimeError("candidate-up-authority-denied")
            yield  # pragma: no cover

    monkeypatch.setattr(
        runner,
        "_candidate_preflight",
        lambda project, port: {"project": project, "port": port},
    )
    monkeypatch.setattr(
        runner,
        "_run",
        lambda argv, **_kwargs: commands.append(list(argv)) or b"",
    )
    monkeypatch.setattr(
        runner,
        "clear_candidate_pending",
        lambda project: pending_cleared.append(project) or {"pending_cleared": True},
    )

    with pytest.raises(RuntimeError, match="candidate-up-authority-denied"):
        runner.prove_candidate(
            env_file=env_file,
            compose_file=tmp_path / "compose.yml",
            receipt_path=tmp_path / "runtime.json",
            wait_seconds=60,
            vexp_authority=DeniedUpAuthority(),
        )

    assert commands == []
    assert pending_cleared == [PROJECT]


def test_candidate_up_postcheck_race_denies_unauthorized_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    env_file, env = _candidate_env(tmp_path)
    _patch_prestart(monkeypatch, env)
    commands: list[list[str]] = []

    class ChangedAfterUpAuthority(_FakeCandidateVexpAuthority):
        @contextlib.contextmanager
        def mutation(self, boundary: str, *, minimum_validity_seconds: float):
            assert minimum_validity_seconds > 0
            if boundary == "before_candidate_up":
                yield _FakeCandidateVexpLease(boundary)
                raise RuntimeError("candidate-authority-changed-after-up")
            if boundary == "before_candidate_cleanup":
                raise runner.CandidateAuthorityError(
                    "candidate-cleanup-authority-unavailable"
                )
            raise AssertionError(f"unexpected boundary: {boundary}")

    monkeypatch.setattr(
        runner,
        "_candidate_preflight",
        lambda project, port: {"project": project, "port": port},
    )
    monkeypatch.setattr(
        runner,
        "_run",
        lambda argv, **_kwargs: commands.append(list(argv)) or b"",
    )
    monkeypatch.setattr(
        runner,
        "_assert_candidate_project_absent",
        lambda _project: {},
    )
    monkeypatch.setattr(
        runner,
        "_wait_for_loopback_port_not_listening",
        lambda _port: None,
    )

    with pytest.raises(
        RuntimeError,
        match="candidate-authority-changed-after-up",
    ):
        runner.prove_candidate(
            env_file=env_file,
            compose_file=tmp_path / "compose.yml",
            receipt_path=tmp_path / "runtime.json",
            wait_seconds=60,
            vexp_authority=ChangedAfterUpAuthority(),
        )

    assert len(commands) == 1
    assert "up" in commands[0]
    assert "restart" not in commands[0]
    assert not any("down" in command for command in commands)
    assert not (tmp_path / "runtime.json").exists()


def test_first_mutating_interaction_denial_stops_before_callback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    env_file, env = _candidate_env(tmp_path)
    _patch_prestart(monkeypatch, env)
    commands: list[list[str]] = []
    interaction_callbacks: list[str] = []

    class DeniedInteractionAuthority(_FakeCandidateVexpAuthority):
        @contextlib.contextmanager
        def mutation(self, boundary: str, *, minimum_validity_seconds: float):
            if boundary == "before_candidate_interaction":
                self.mutation_boundaries.append(boundary)
                raise runner.CandidateAuthorityError(
                    "candidate-interaction-authority-denied"
                )
                yield  # pragma: no cover
            with super().mutation(
                boundary,
                minimum_validity_seconds=minimum_validity_seconds,
            ) as lease:
                yield lease

    authority = DeniedInteractionAuthority()
    monkeypatch.setattr(
        runner,
        "_candidate_preflight",
        lambda project, port: {"project": project, "loopback_port": port},
    )
    monkeypatch.setattr(
        runner,
        "_run",
        lambda argv, **_kwargs: commands.append(list(argv)) or b"",
    )
    monkeypatch.setattr(runner, "_assert_redis", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        runner,
        "verify_candidate",
        lambda **_kwargs: interaction_callbacks.append("smoke") or {},
    )
    monkeypatch.setattr(runner, "_assert_candidate_project_absent", lambda _p: {})
    monkeypatch.setattr(
        runner,
        "_wait_for_loopback_port_not_listening",
        lambda _port: None,
    )

    with pytest.raises(
        runner.CandidateAuthorityError,
        match="candidate-interaction-authority-denied",
    ):
        runner.prove_candidate(
            env_file=env_file,
            compose_file=tmp_path / "compose.yml",
            receipt_path=tmp_path / "runtime.json",
            wait_seconds=60,
            vexp_authority=authority,
        )

    assert interaction_callbacks == []
    assert authority.mutation_boundaries == [
        "before_candidate_up",
        "before_candidate_interaction",
        "before_candidate_cleanup",
    ]
    assert any("up" in command for command in commands)
    assert any("down" in command for command in commands)
    assert not any("restart" in command for command in commands)
    assert not (tmp_path / "runtime.json").exists()


def test_revoked_interaction_authority_blocks_second_smoke_before_callback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    env_file, env = _candidate_env(tmp_path)
    _patch_prestart(monkeypatch, env)
    commands: list[list[str]] = []
    interaction_callbacks: list[str] = []
    api_container_id = "1" * 64

    class RevokedInteractionAuthority(_FakeCandidateVexpAuthority):
        def __init__(self) -> None:
            super().__init__()
            self.interaction_count = 0

        @contextlib.contextmanager
        def mutation(self, boundary: str, *, minimum_validity_seconds: float):
            if boundary == "before_candidate_interaction":
                self.interaction_count += 1
                if self.interaction_count == 2:
                    self.mutation_boundaries.append(boundary)
                    raise runner.CandidateAuthorityError(
                        "candidate-interaction-authority-revoked"
                    )
                    yield  # pragma: no cover
            with super().mutation(
                boundary,
                minimum_validity_seconds=minimum_validity_seconds,
            ) as lease:
                yield lease

    authority = RevokedInteractionAuthority()

    def run(argv: list[str], **_kwargs: object) -> bytes:
        commands.append(list(argv))
        if "ps" in argv and "api" in argv:
            return api_container_id.encode("ascii")
        return b""

    def verify_candidate(**_kwargs: object) -> dict[str, object]:
        interaction_callbacks.append("smoke")
        return {"checks": [], "contribution": {}}

    monkeypatch.setattr(
        runner,
        "_candidate_preflight",
        lambda project, port: {"project": project, "loopback_port": port},
    )
    monkeypatch.setattr(runner, "_run", run)
    monkeypatch.setattr(runner, "_assert_redis", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(runner, "verify_candidate", verify_candidate)
    monkeypatch.setattr(
        runner,
        "_wait_for_candidate_api_healthy",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(runner, "_assert_candidate_project_absent", lambda _p: {})
    monkeypatch.setattr(
        runner,
        "_wait_for_loopback_port_not_listening",
        lambda _port: None,
    )

    with pytest.raises(
        runner.CandidateAuthorityError,
        match="candidate-interaction-authority-revoked",
    ):
        runner.prove_candidate(
            env_file=env_file,
            compose_file=tmp_path / "compose.yml",
            receipt_path=tmp_path / "runtime.json",
            wait_seconds=60,
            vexp_authority=authority,
        )

    assert interaction_callbacks == ["smoke"]
    assert authority.mutation_boundaries == [
        "before_candidate_up",
        "before_candidate_interaction",
        "before_candidate_restart",
        "before_candidate_interaction",
        "before_candidate_cleanup",
    ]
    assert any("restart" in command for command in commands)
    assert any("down" in command for command in commands)
    assert not (tmp_path / "runtime.json").exists()


def test_success_receipt_seals_exact_candidate_mutation_and_finalization_envelope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    env_file, env = _candidate_env(tmp_path)
    _patch_prestart(monkeypatch, env)
    authority = _FakeCandidateVexpAuthority()
    commands: list[list[str]] = []
    smoke_calls = 0
    api_container_id = "1" * 64
    container_images = {
        "api": {"container_id": api_container_id, "image_id": IMAGE_ID},
        "gateway": {"container_id": "2" * 64, "image_id": IMAGE_ID},
        "prepared_image_id": IMAGE_ID,
        "revision_label": COMMIT,
        "all_match_prepared_image": True,
    }
    runtime_projection = {
        "schema": runner.RUNTIME_PROJECTION_SCHEMA,
        "projection_sha256": "d" * 64,
        "file_count": 0,
        "projection_bytes": 0,
        "mount_roots": [
            "/data/memorial/public",
            "/data/memorial/private",
            "/data/memorial/archive",
            "/data/public_property_tours",
            "/data/release-authority",
        ],
        "runtime_bytes_match_prepared_projection": True,
    }

    def record_exec(
        vexp_authority: _FakeCandidateVexpAuthority,
        vexp_mutation_evidence: list[dict[str, object]],
    ) -> None:
        with vexp_authority.mutation(
            "before_candidate_exec",
            minimum_validity_seconds=120,
        ) as lease:
            operation = runner._begin_candidate_operation(
                vexp_mutation_evidence,
                operation="redis_ping",
                argv=["fixture-candidate-exec", "redis-ping"],
                target="fixture:redis",
                authority=dict(lease.authority_evidence),
            )
            operation["runner_acknowledged"] = True

    def run(argv: list[str], **_kwargs: object) -> bytes:
        commands.append(list(argv))
        if "ps" in argv and "api" in argv:
            return api_container_id.encode("ascii")
        return b""

    def assert_redis(
        _compose: list[str],
        _environment: dict[str, str],
        *,
        vexp_authority: _FakeCandidateVexpAuthority,
        vexp_mutation_evidence: list[dict[str, object]],
    ) -> None:
        record_exec(vexp_authority, vexp_mutation_evidence)

    def projection_evidence(
        *,
        vexp_authority: _FakeCandidateVexpAuthority,
        vexp_mutation_evidence: list[dict[str, object]],
        **_kwargs: object,
    ) -> dict[str, object]:
        record_exec(vexp_authority, vexp_mutation_evidence)
        return dict(runtime_projection)

    def loopback_request(
        *_args: object,
        vexp_authority: _FakeCandidateVexpAuthority,
        vexp_mutation_evidence: list[dict[str, object]],
        **_kwargs: object,
    ) -> tuple[int, bytes, dict[str, str]]:
        record_exec(vexp_authority, vexp_mutation_evidence)
        return 200, b"{}", {}

    def verify_candidate(**kwargs: object) -> dict[str, object]:
        nonlocal smoke_calls
        smoke_calls += 1
        transport = kwargs["transport_request"]
        assert callable(transport)
        for index in range(5):
            transport(  # type: ignore[operator]
                kwargs["base_url"],
                f"/candidate-check-{index}",
                expected={200},
            )
        return {
            "checks": [f"smoke-{smoke_calls}", "conversation_only_public_surface"],
            "contribution": {"survived_candidate_restart": False},
        }

    def conversation_state_mode(
        _compose: list[str],
        _environment: dict[str, str],
        *,
        vexp_authority: _FakeCandidateVexpAuthority,
        vexp_mutation_evidence: list[dict[str, object]],
    ) -> dict[str, str]:
        record_exec(vexp_authority, vexp_mutation_evidence)
        return {"conversation_state_root": "700"}

    def openapi_snapshot(
        _compose: list[str],
        _environment: dict[str, str],
        *,
        vexp_authority: _FakeCandidateVexpAuthority,
        vexp_mutation_evidence: list[dict[str, object]],
    ) -> tuple[dict[str, object], dict[str, object]]:
        record_exec(vexp_authority, vexp_mutation_evidence)
        return copy.deepcopy(_openapi_snapshot())

    monkeypatch.setattr(
        runner,
        "_candidate_preflight",
        lambda project, port: {"project": project, "loopback_port": port},
    )
    monkeypatch.setattr(runner, "_run", run)
    monkeypatch.setattr(runner, "_assert_redis", assert_redis)
    monkeypatch.setattr(
        runner,
        "_candidate_runtime_projection_evidence",
        projection_evidence,
    )
    monkeypatch.setattr(runner, "_candidate_api_loopback_request", loopback_request)
    monkeypatch.setattr(runner, "verify_candidate", verify_candidate)
    monkeypatch.setattr(
        runner,
        "_wait_for_candidate_api_healthy",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        runner,
        "_assert_conversation_state_mode",
        conversation_state_mode,
    )
    monkeypatch.setattr(
        runner,
        "_candidate_api_runtime_posture",
        lambda **_kwargs: {
            "api_container_id": api_container_id,
            "running_and_healthy": True,
        },
    )
    monkeypatch.setattr(
        runner,
        "_candidate_container_image_evidence",
        lambda **_kwargs: copy.deepcopy(container_images),
    )
    monkeypatch.setattr(
        runner,
        "_candidate_runtime_version_identity",
        lambda *_args, **_kwargs: {
            "source_revision_header": COMMIT,
            "body_commit_sha": COMMIT,
            "revision_agreement_verified": True,
        },
    )
    monkeypatch.setattr(
        runner,
        "audit_browser_surface",
        lambda _base_url, **_kwargs: {
            "status": "pass",
            "memorial_surface": prepare.MEMORIAL_SURFACE,
            "spatial_scope": prepare.SPATIAL_SCOPE,
        },
    )
    monkeypatch.setattr(runner, "_assert_logs_clean", lambda *_args: None)
    monkeypatch.setattr(
        runner,
        "_candidate_openapi_contract_snapshot",
        openapi_snapshot,
    )

    receipt = runner.prove_candidate(
        env_file=env_file,
        compose_file=tmp_path / "compose.yml",
        receipt_path=tmp_path / "runtime.json",
        wait_seconds=60,
        vexp_authority=authority,
    )

    expected_boundaries = (
        ["before_candidate_up"]
        + ["before_candidate_exec"] * 2
        + ["before_candidate_interaction"]
        + ["before_candidate_exec"] * 5
        + ["before_candidate_restart"]
        + ["before_candidate_interaction"]
        + ["before_candidate_exec"] * 7
        + ["before_candidate_interaction"] * 2
        + ["before_candidate_exec"] * 2
    )
    assert len(expected_boundaries) == 22
    assert authority.mutation_boundaries == expected_boundaries
    assert smoke_calls == 2
    assert [
        "up" if "up" in command else "restart" if "restart" in command else "ps"
        for command in commands
    ] == ["up", "ps", "restart", "ps"]
    assert receipt["openapi_contract"] == {
        "candidate": _openapi_snapshot()[1],
        "candidate_public_endpoint": {
            "status": 404,
            "public_endpoint_retired": True,
        },
        "live_comparison_status": "deferred_to_governed_promotion",
        "candidate_preserves_live_contract": False,
        "candidate_live_contract_claim_allowed": False,
    }
    envelope = receipt["vexp_candidate_mutation_authority"]
    assert envelope["entry"] == {
        "status": "pass",
        "phase": "entry",
        "boundary": "candidate_entry",
    }
    assert envelope["finalization"] == {
        "status": "pass",
        "phase": "finalization",
        "boundary": "candidate_receipt_publication",
    }
    assert envelope["cleanup_requires_positive_authority"] is True
    assert envelope["retention_timer_only_authority_free_cleanup"] is True
    mutations = envelope["mutations"]
    assert isinstance(mutations, list)
    assert len(mutations) == len(expected_boundaries)
    allowed_by_boundary = {
        "before_candidate_up": {"compose_up"},
        "before_candidate_exec": {"redis_ping"},
        "before_candidate_interaction": {
            "candidate_smoke",
            "candidate_smoke_after_restart",
            "runtime_identity_probe",
            "browser_surface_audit",
        },
        "before_candidate_restart": {"compose_restart_api"},
    }
    for sequence, (operation, boundary) in enumerate(
        zip(mutations, expected_boundaries, strict=True),
        start=1,
    ):
        assert set(operation) == {
            "sequence",
            "operation",
            "resource",
            "runner_acknowledged",
            "authority",
        }
        assert operation["sequence"] == sequence
        assert operation["operation"] in allowed_by_boundary[boundary]
        assert operation["runner_acknowledged"] is True
        assert set(operation["resource"]) == {"argv", "target"}
        assert operation["resource"]["argv"]
        assert operation["resource"]["target"]
        assert operation["authority"] == {
            "status": "pass",
            "phase": "pre_mutation",
            "boundary": boundary,
        }


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


def test_conversation_candidate_does_not_require_spatial_handoff_before_source_access(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        prepare,
        "_commit",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("source-resolution-reached")
        ),
    )

    with pytest.raises(RuntimeError, match="source-resolution-reached"):
        prepare.prepare_candidate(
            source_root=tmp_path,
            ref="HEAD",
            image=f"ea-runtime:manfred-{COMMIT}",
            deploy_root=tmp_path / "deploy",
            public_base_url="https://myexternalbrain.com",
            host_port=18091,
            project_name=PROJECT,
        )


def test_image_build_receipt_is_no_replace_with_exact_byte_reuse(
    tmp_path: Path,
) -> None:
    receipt = tmp_path / "receipts" / "image-build.json"
    payload = {
        "schema": image_builder.RECEIPT_SCHEMA,
        "status": "pass",
        "commit": COMMIT,
        "image_id": IMAGE_ID,
    }

    image_builder._atomic_json(receipt, payload)
    original = receipt.read_bytes()
    original_inode = receipt.stat().st_ino
    image_builder._atomic_json(receipt, dict(payload))

    assert receipt.read_bytes() == original
    assert receipt.stat().st_ino == original_inode
    with pytest.raises(RuntimeError, match=image_builder.RECEIPT_CONFLICT_ERROR):
        image_builder._atomic_json(receipt, {**payload, "status": "fail"})
    assert receipt.read_bytes() == original
    assert receipt.stat().st_ino == original_inode


@pytest.mark.parametrize(
    "temporary_name",
    [
        (f".{image_builder.RECEIPT_TEMP_BASENAME}.1234.abcdef012345abcdef012345.tmp"),
        ".image-build.json.abc123__",
    ],
)
def test_image_build_receipt_completes_exact_interrupted_link_window(
    tmp_path: Path,
    temporary_name: str,
) -> None:
    receipt = tmp_path / "image-build.json"
    temporary = tmp_path / temporary_name
    payload = {
        "schema": image_builder.RECEIPT_SCHEMA,
        "status": "pass",
        "commit": COMMIT,
        "image_id": IMAGE_ID,
    }
    expected = image_builder._build_receipt_bytes(payload)
    temporary.write_bytes(expected)
    temporary.chmod(0o600)
    original_inode = temporary.stat().st_ino
    os.link(temporary, receipt)
    assert receipt.stat().st_nlink == 2

    image_builder._atomic_json(receipt, payload)

    assert not temporary.exists()
    assert receipt.read_bytes() == expected
    assert receipt.stat().st_ino == original_inode
    assert receipt.stat().st_nlink == 1


@pytest.mark.parametrize("fault_stage", ["directory_fsync", "single_link_read"])
@pytest.mark.parametrize("receipt_state", ["exact", "conflict"])
def test_image_build_receipt_recovery_fault_preserves_no_replace_semantics(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fault_stage: str,
    receipt_state: str,
) -> None:
    receipt = tmp_path / "image-build.json"
    temporary = tmp_path / (
        f".{image_builder.RECEIPT_TEMP_BASENAME}.1234.abcdef012345abcdef012345.tmp"
    )
    payload = {
        "schema": image_builder.RECEIPT_SCHEMA,
        "status": "pass",
        "commit": COMMIT,
        "image_id": IMAGE_ID,
    }
    expected = image_builder._build_receipt_bytes(payload)
    staged = (
        expected
        if receipt_state == "exact"
        else image_builder._build_receipt_bytes(
            {**payload, "image_id": "sha256:" + "c" * 64}
        )
    )
    temporary.write_bytes(staged)
    temporary.chmod(0o600)
    os.link(temporary, receipt)
    fault_injected = False
    fault_message = f"simulated recovery {fault_stage} fault"

    if fault_stage == "directory_fsync":
        real_fsync = image_builder.os.fsync

        def fail_recovery_fsync(descriptor: int) -> None:
            nonlocal fault_injected
            if stat.S_ISDIR(os.fstat(descriptor).st_mode) and not fault_injected:
                fault_injected = True
                raise OSError(fault_message)
            real_fsync(descriptor)

        monkeypatch.setattr(image_builder.os, "fsync", fail_recovery_fsync)
    else:
        real_read = image_builder._read_build_receipt_entry

        def fail_recovery_read(
            directory_descriptor: int,
            name: str,
            *,
            required_nlink: int,
        ) -> tuple[bytes, os.stat_result]:
            nonlocal fault_injected
            if required_nlink == 1 and not fault_injected:
                fault_injected = True
                raise OSError(fault_message)
            return real_read(
                directory_descriptor,
                name,
                required_nlink=required_nlink,
            )

        monkeypatch.setattr(
            image_builder,
            "_read_build_receipt_entry",
            fail_recovery_read,
        )

    with pytest.raises(OSError, match=fault_message):
        image_builder._atomic_json(receipt, payload)

    assert fault_injected is True
    assert not temporary.exists()
    if receipt_state == "conflict":
        assert receipt.read_bytes() == staged
        assert receipt.stat().st_nlink == 1
        with pytest.raises(RuntimeError, match=image_builder.RECEIPT_CONFLICT_ERROR):
            image_builder._atomic_json(receipt, payload)
        assert receipt.read_bytes() == staged
        assert receipt.stat().st_nlink == 1
        assert list(tmp_path.iterdir()) == [receipt]
    else:
        assert not receipt.exists()
        assert list(tmp_path.iterdir()) == []
        image_builder._atomic_json(receipt, payload)
        assert receipt.read_bytes() == expected
        assert receipt.stat().st_nlink == 1
        assert list(tmp_path.iterdir()) == [receipt]


def test_image_build_receipt_conflicting_interrupted_link_fails_closed(
    tmp_path: Path,
) -> None:
    receipt = tmp_path / "image-build.json"
    temporary = tmp_path / (
        f".{image_builder.RECEIPT_TEMP_BASENAME}.1234.abcdef012345abcdef012345.tmp"
    )
    desired = {
        "schema": image_builder.RECEIPT_SCHEMA,
        "status": "pass",
        "commit": COMMIT,
        "image_id": IMAGE_ID,
    }
    conflicting = image_builder._build_receipt_bytes(
        {**desired, "image_id": "sha256:" + "c" * 64}
    )
    temporary.write_bytes(conflicting)
    temporary.chmod(0o600)
    os.link(temporary, receipt)
    assert receipt.stat().st_nlink == 2

    with pytest.raises(RuntimeError, match=image_builder.RECEIPT_CONFLICT_ERROR):
        image_builder._atomic_json(receipt, desired)

    assert not temporary.exists()
    assert receipt.read_bytes() == conflicting
    assert receipt.stat().st_nlink == 1


def test_image_build_receipt_durable_conflict_is_not_masked_by_cleanup_fsync(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    receipt = tmp_path / "image-build.json"
    temporary = tmp_path / (
        f".{image_builder.RECEIPT_TEMP_BASENAME}.1234.abcdef012345abcdef012345.tmp"
    )
    desired = {
        "schema": image_builder.RECEIPT_SCHEMA,
        "status": "pass",
        "commit": COMMIT,
        "image_id": IMAGE_ID,
    }
    conflicting = image_builder._build_receipt_bytes(
        {**desired, "image_id": "sha256:" + "c" * 64}
    )
    temporary.write_bytes(conflicting)
    temporary.chmod(0o600)
    os.link(temporary, receipt)
    real_fsync = image_builder.os.fsync
    directory_fsync_count = 0

    def fail_redundant_directory_fsync(descriptor: int) -> None:
        nonlocal directory_fsync_count
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            directory_fsync_count += 1
            if directory_fsync_count > 1:
                raise OSError("redundant conflict cleanup fsync")
        real_fsync(descriptor)

    monkeypatch.setattr(
        image_builder.os,
        "fsync",
        fail_redundant_directory_fsync,
    )

    with pytest.raises(RuntimeError, match=image_builder.RECEIPT_CONFLICT_ERROR):
        image_builder._atomic_json(receipt, desired)

    assert directory_fsync_count == 1
    assert not temporary.exists()
    assert receipt.read_bytes() == conflicting
    assert receipt.stat().st_nlink == 1


def test_image_build_receipt_destination_is_never_its_own_recovery_stage(
    tmp_path: Path,
) -> None:
    receipt = tmp_path / (
        f".{image_builder.RECEIPT_TEMP_BASENAME}.1234.abcdef012345abcdef012345.tmp"
    )
    unrelated = tmp_path / "operator-backup.json"
    payload = {
        "schema": image_builder.RECEIPT_SCHEMA,
        "status": "pass",
        "commit": COMMIT,
        "image_id": IMAGE_ID,
    }
    expected = image_builder._build_receipt_bytes(payload)
    receipt.write_bytes(expected)
    receipt.chmod(0o600)
    os.link(receipt, unrelated)

    with pytest.raises(RuntimeError, match=image_builder.RECEIPT_PATH_ERROR):
        image_builder._atomic_json(receipt, payload)

    assert receipt.read_bytes() == expected
    assert unrelated.read_bytes() == expected
    assert receipt.stat().st_nlink == 2


def test_image_build_receipt_post_link_failure_rolls_back_published_name(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    receipt = tmp_path / "image-build.json"
    payload = {
        "schema": image_builder.RECEIPT_SCHEMA,
        "status": "pass",
        "commit": COMMIT,
        "image_id": IMAGE_ID,
    }
    real_fsync = image_builder.os.fsync
    directory_failure_injected = False

    def fail_first_directory_fsync(descriptor: int) -> None:
        nonlocal directory_failure_injected
        if (
            stat.S_ISDIR(os.fstat(descriptor).st_mode)
            and not directory_failure_injected
        ):
            directory_failure_injected = True
            raise OSError("simulated post-link directory fsync failure")
        real_fsync(descriptor)

    monkeypatch.setattr(image_builder.os, "fsync", fail_first_directory_fsync)

    with pytest.raises(OSError, match="simulated post-link directory fsync failure"):
        image_builder._atomic_json(receipt, payload)

    assert directory_failure_injected is True
    assert not receipt.exists()
    assert list(tmp_path.iterdir()) == []


def test_image_build_receipt_link_commit_then_exception_rolls_back_published_name(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    receipt = tmp_path / "image-build.json"
    payload = {
        "schema": image_builder.RECEIPT_SCHEMA,
        "status": "pass",
        "commit": COMMIT,
        "image_id": IMAGE_ID,
    }
    real_link = image_builder.os.link

    def commit_link_then_fail(*args: object, **kwargs: object) -> None:
        real_link(*args, **kwargs)  # type: ignore[arg-type]
        raise OSError("simulated exception after hard-link commit")

    monkeypatch.setattr(image_builder.os, "link", commit_link_then_fail)

    with pytest.raises(OSError, match="simulated exception after hard-link commit"):
        image_builder._atomic_json(receipt, payload)

    assert not receipt.exists()
    assert list(tmp_path.iterdir()) == []


def test_runtime_version_identity_delegates_all_four_revision_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = {
        "path": "/version",
        "status": 200,
        "commit_sha": COMMIT,
        "body_commit_sha": COMMIT,
        "source_revision_header": COMMIT,
        "expected_commit_sha": COMMIT,
        "oci_image_revision": COMMIT,
        "repository": "EA",
        "role": "api",
        "release_authority_state": "clear",
        "release_authority_posture": "authoritative_runtime",
        "release_authority_source": "published_status_artifact",
        "commit_observed_over_http": True,
        "revision_agreement_verified": True,
    }
    observed: list[tuple[str, int]] = []

    class Response:
        status = 200

        def __init__(self, header_commit: str) -> None:
            self.headers = {
                "X-EA-Source-Revision": header_commit,
                "Content-Type": "application/json; charset=utf-8",
            }

        def read(self, _maximum: int) -> bytes:
            return json.dumps(
                {
                    "commit_sha": COMMIT,
                    "repository": "EA",
                    "role": "api",
                    "release_authority_state": "clear",
                    "release_authority_posture": "authoritative_runtime",
                    "release_authority_source": "published_status_artifact",
                }
            ).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    def open_version(request: object, *, timeout: int):
        observed.append((str(getattr(request, "full_url", "")), timeout))
        return Response(COMMIT)

    monkeypatch.setattr(runner.urllib.request, "urlopen", open_version)
    assert runner._candidate_runtime_version_identity(
        "http://127.0.0.1:18091",
        expected_commit=COMMIT,
        oci_image_revision=COMMIT,
    ) == expected
    assert observed == [("http://127.0.0.1:18091/version", 10)]

    monkeypatch.setattr(
        runner.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: Response("c" * 40),
    )
    with pytest.raises(
        RuntimeError,
        match="manfred_candidate_runtime_version_identity_invalid",
    ):
        runner._candidate_runtime_version_identity(
            "http://127.0.0.1:18091",
            expected_commit=COMMIT,
            oci_image_revision=COMMIT,
        )


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


def test_candidate_compose_attestation_binds_canonical_tracked_blob(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    compose_path = tmp_path / runner.CANDIDATE_COMPOSE_RELATIVE_PATH
    compose_path.parent.mkdir(parents=True)
    compose_bytes = b"name: governed-candidate\nservices: {}\n"
    compose_path.write_bytes(compose_bytes)
    blob_oid = "c" * 40
    commands: list[list[str]] = []

    def run(argv: list[str], **_kwargs) -> bytes:
        commands.append(list(argv))
        return f"{blob_oid}\n".encode("ascii")

    def run_bounded(argv: list[str], **_kwargs) -> bytes:
        commands.append(list(argv))
        return compose_bytes

    monkeypatch.setattr(runner, "_run", run)
    monkeypatch.setattr(runner, "_run_bounded_output", run_bounded)

    evidence = runner._candidate_compose_attestation(
        compose_path,
        expected_commit=COMMIT,
    )

    assert evidence == {
        "canonical_relative_path": (runner.CANDIDATE_COMPOSE_RELATIVE_PATH.as_posix()),
        "canonical_source_path": str(compose_path),
        "candidate_commit": COMMIT,
        "git_blob_oid": blob_oid,
        "sha256": prepare._sha256(compose_bytes),
        "size_bytes": len(compose_bytes),
        "canonical_path_enforced": True,
        "tracked_blob_bytes_enforced": True,
    }
    assert commands == [
        [
            "git",
            "-C",
            str(tmp_path),
            "rev-parse",
            "--verify",
            f"{COMMIT}:{runner.CANDIDATE_COMPOSE_RELATIVE_PATH.as_posix()}",
        ],
        ["git", "-C", str(tmp_path), "cat-file", "blob", blob_oid],
    ]


def test_candidate_compose_attestation_rejects_alternate_or_stale_source(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    canonical = tmp_path / runner.CANDIDATE_COMPOSE_RELATIVE_PATH
    canonical.parent.mkdir(parents=True)
    canonical.write_text("services: {}\n", encoding="utf-8")
    alternate = tmp_path / "alternate-compose.yml"
    alternate.write_bytes(canonical.read_bytes())

    with pytest.raises(RuntimeError, match="compose_source_not_canonical"):
        runner._candidate_compose_attestation(
            alternate,
            expected_commit=COMMIT,
        )

    monkeypatch.setattr(runner, "_run", lambda *_args, **_kwargs: b"c" * 40 + b"\n")
    monkeypatch.setattr(
        runner,
        "_run_bounded_output",
        lambda *_args, **_kwargs: b"services:\n  api: {}\n",
    )
    with pytest.raises(RuntimeError, match="compose_source_not_tracked"):
        runner._candidate_compose_attestation(
            canonical,
            expected_commit=COMMIT,
        )


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("OPENAI_API_KEY", "must-never-reach-candidate"),
        ("EA_ENABLE_PUBLIC_MEMORIAL_OPERATOR_SURFACES", "1"),
        ("EA_PUBLIC_MEMORIAL_ARCHIVE_PUBLISHED_SLUGS", "manfred"),
    ],
)
def test_candidate_compose_api_environment_is_exactly_allowlisted(
    tmp_path: Path,
    name: str,
    value: str,
) -> None:
    env_file, env = _candidate_env(tmp_path)
    payload, source = _compose_payloads(env_file, env)
    source["services"]["api"]["environment"][name] = value
    payload["services"]["api"]["environment"][name] = value

    with pytest.raises(RuntimeError, match="compose_api_environment_not_allowlisted"):
        runner._assert_compose_isolation(
            payload,
            source,
            env=env,
            env_file=env_file,
        )


@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_internal_transport_probe_is_api_loopback_only_and_parses_security_headers(
    monkeypatch: pytest.MonkeyPatch,
    method: str,
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

    authority = _FakeCandidateVexpAuthority()
    evidence: list[dict[str, object]] = []
    status, body, headers = runner._candidate_api_loopback_request(
        ["docker", "compose", "--project-name", PROJECT],
        {"PATH": "/usr/bin:/bin"},
        "http://127.0.0.1:18091",
        "/memorials/manfred",
        method=method,
        headers={
            "Host": "myexternalbrain.com",
            "X-Forwarded-Host": "myexternalbrain.com",
            "X-Forwarded-Proto": "https",
        },
        expected={200},
        follow_redirects=False,
        vexp_authority=authority,
        vexp_mutation_evidence=evidence,
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
    assert "X-Forwarded-Host: myexternalbrain.com" in command
    assert "X-Forwarded-Proto: https" in command
    if method == "HEAD":
        assert "--head" in command
        assert "--request" not in command
    else:
        assert "--head" not in command
        assert command[command.index("--request") + 1] == method
    assert authority.mutation_boundaries == ["before_candidate_exec"]
    assert len(evidence) == 1


@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_internal_transport_probe_allows_exact_singular_alias_first_hop(
    monkeypatch: pytest.MonkeyPatch,
    method: str,
) -> None:
    commands: list[list[str]] = []
    raw = (
        b"HTTP/1.1 308 Permanent Redirect\r\n"
        b"Location: /memorials/manfred?from=ea-launch-verifier\r\n"
        b"Cache-Control: no-store\r\n\r\n"
        + f"\n{runner.INTERNAL_TRANSPORT_STATUS_MARKER}308\n".encode("ascii")
    )
    monkeypatch.setattr(
        runner,
        "_run",
        lambda argv, **_kwargs: commands.append(list(argv)) or raw,
    )

    authority = _FakeCandidateVexpAuthority()
    evidence: list[dict[str, object]] = []
    status, body, headers = runner._candidate_api_loopback_request(
        ["docker", "compose", "--project-name", PROJECT],
        {"PATH": "/usr/bin:/bin"},
        "http://127.0.0.1:18091",
        "/memorial/manfred?from=ea-launch-verifier",
        method=method,
        headers={
            "Host": "myexternalbrain.com",
            "X-Forwarded-Host": "myexternalbrain.com",
            "X-Forwarded-Proto": "https",
        },
        expected={308},
        follow_redirects=False,
        vexp_authority=authority,
        vexp_mutation_evidence=evidence,
    )

    assert status == 308
    assert body == b""
    assert headers["location"] == "/memorials/manfred?from=ea-launch-verifier"
    command = commands[0]
    assert command[-1] == (
        "http://127.0.0.1:8090/memorial/manfred?from=ea-launch-verifier"
    )
    assert "--location" not in command
    assert "Host: myexternalbrain.com" in command
    assert "X-Forwarded-Host: myexternalbrain.com" in command
    assert "X-Forwarded-Proto: https" in command
    if method == "HEAD":
        assert "--head" in command
        assert "--request" not in command
    else:
        assert "--head" not in command
        assert command[command.index("--request") + 1] == method
    assert authority.mutation_boundaries == ["before_candidate_exec"]
    assert len(evidence) == 1


def test_internal_transport_probe_rejects_unexpected_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = (
        b"HTTP/1.1 308 Permanent Redirect\r\n"
        b"Location: https://myexternalbrain.com/memorials/manfred\r\n\r\n"
        + f"\n{runner.INTERNAL_TRANSPORT_STATUS_MARKER}308\n".encode("ascii")
    )
    monkeypatch.setattr(runner, "_run", lambda *_args, **_kwargs: raw)
    authority = _FakeCandidateVexpAuthority()
    evidence: list[dict[str, object]] = []
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
            vexp_authority=authority,
            vexp_mutation_evidence=evidence,
        )
    assert authority.mutation_boundaries == ["before_candidate_exec"]
    assert len(evidence) == 1


def test_restart_health_wait_pins_container_identity_until_healthy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container_id = "a" * 64
    inspections = iter(
        [
            [
                {
                    "Id": container_id,
                    "State": {"Running": True, "Health": {"Status": "starting"}},
                }
            ],
            [
                {
                    "Id": container_id,
                    "State": {"Running": True, "Health": {"Status": "healthy"}},
                }
            ],
        ]
    )
    monotonic = iter([0.0, 0.0, 1.0])

    monkeypatch.setattr(
        runner,
        "_compose_service_container_id",
        lambda *_args, **_kwargs: container_id,
    )
    monkeypatch.setattr(
        runner,
        "_run",
        lambda *_args, **_kwargs: json.dumps(next(inspections)).encode("utf-8"),
    )
    monkeypatch.setattr(runner.time, "monotonic", lambda: next(monotonic))
    monkeypatch.setattr(runner.time, "sleep", lambda _seconds: None)

    runner._wait_for_candidate_api_healthy(
        compose=["docker", "compose"],
        environment={},
        expected_container_id=container_id,
        wait_seconds=30,
    )


def test_restart_health_wait_rejects_container_recreation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runner,
        "_compose_service_container_id",
        lambda *_args, **_kwargs: "b" * 64,
    )
    monkeypatch.setattr(runner.time, "monotonic", lambda: 0.0)

    with pytest.raises(
        RuntimeError,
        match="manfred_candidate_restart_recreated_container",
    ):
        runner._wait_for_candidate_api_healthy(
            compose=["docker", "compose"],
            environment={},
            expected_container_id="a" * 64,
            wait_seconds=30,
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
        "/memorial/manfred",
        "/memorial/manfred?from=ea-launch-verifier&extra=1",
        "/memorial/manfred?from=EA-launch-verifier",
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
    authority = _FakeCandidateVexpAuthority()
    evidence: list[dict[str, object]] = []
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
            vexp_authority=authority,
            vexp_mutation_evidence=evidence,
        )
    assert authority.mutation_boundaries == []
    assert evidence == []


def test_internal_transport_probe_rejects_case_insensitive_outgoing_duplicates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runner,
        "_run",
        lambda *_args, **_kwargs: pytest.fail(
            "duplicate headers must fail before curl"
        ),
    )
    authority = _FakeCandidateVexpAuthority()
    evidence: list[dict[str, object]] = []
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
            vexp_authority=authority,
            vexp_mutation_evidence=evidence,
        )
    assert authority.mutation_boundaries == []
    assert evidence == []


def test_conversation_candidate_forbids_spatial_bind_and_environment(
    tmp_path: Path,
) -> None:
    env_file, env = _candidate_env(tmp_path)
    payload, source = _compose_payloads(env_file, env)

    forbidden_bind = copy.deepcopy(payload)
    forbidden_bind["services"]["api"]["volumes"].append(
        {
            "type": "bind",
            "source": str(tmp_path / "public_property_tours"),
            "target": "/data/public_property_tours",
            "read_only": True,
        }
    )
    with pytest.raises(RuntimeError, match="compose_mount_root_mismatch"):
        runner._assert_compose_isolation(
            forbidden_bind, source, env=env, env_file=env_file
        )

    wrong_environment = copy.deepcopy(source)
    wrong_environment["services"]["api"]["environment"]["EA_PUBLIC_TOUR_DIR"] = (
        "/tmp/public-tours"
    )
    with pytest.raises(RuntimeError, match="compose_api_environment_not_allowlisted"):
        runner._assert_compose_isolation(
            payload, wrong_environment, env=env, env_file=env_file
        )

    gateway_bind = copy.deepcopy(payload)
    gateway_bind["services"]["gateway"]["volumes"] = [
        {
            "type": "bind",
            "source": str(tmp_path / "public_property_tours"),
            "target": "/data/public_property_tours",
            "read_only": True,
        }
    ]
    with pytest.raises(RuntimeError, match="spatial_compose_scope_invalid"):
        runner._assert_compose_isolation(
            gateway_bind, source, env=env, env_file=env_file
        )

    invalid_env = dict(env)
    invalid_env["EA_MANFRED_SPATIAL_SHA256"] = prepare._sha256(b"[]")
    env_file.write_text(
        "".join(f"{name}={value}\n" for name, value in sorted(invalid_env.items())),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="env_allowlist_invalid"):
        runner._assert_env_allowlist(env_file)


def test_projection_receipt_binds_safe_release_root_digest_image_and_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
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
    build_receipt_path = (tmp_path / "image-build.v3.json").resolve()
    build_receipt_bytes = b'{"schema":"test-image-build"}\n'
    build_receipt_path.write_bytes(build_receipt_bytes)
    build_receipt_path.chmod(0o600)
    image_build_authority_binding = {
        "receipt_schema": image_builder.RECEIPT_SCHEMA,
        "receipt_path": str(build_receipt_path),
        "receipt_sha256": prepare._sha256(build_receipt_bytes),
        "image_tag": env["EA_MANFRED_IMAGE"],
        "image_id": IMAGE_ID,
        "runtime_source_revision": COMMIT,
        "producer_sha256": "c" * 64,
        "image_reused": False,
        "authority": {},
    }
    monkeypatch.setattr(
        runner,
        "validate_build_authority_binding",
        lambda value, **_kwargs: dict(value),
    )
    monkeypatch.setattr(
        runner,
        "validated_build_receipt_binding",
        lambda _encoded, **_kwargs: dict(image_build_authority_binding),
    )
    receipt_path.write_bytes(
        prepare._receipt_bytes(
            {
                "schema": prepare.RECEIPT_SCHEMA,
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
                "memorial_surface": prepare.MEMORIAL_SURFACE,
                "spatial_scope": prepare.SPATIAL_SCOPE,
                "public_property_tours_packaged": False,
                "memorial_spatial_receipt_generated": False,
                "image_build_authority_binding": image_build_authority_binding,
            }
        ),
    )
    receipt_path.chmod(0o600)

    release_authority_evidence = {
        "schema": prepare.CANDIDATE_RELEASE_AUTHORITY_SCHEMA,
        "status": "pass",
        "commit_sha": COMMIT,
        "image_id": IMAGE_ID,
        "runtime_authority_state": "clear",
        "runtime_authority_posture": "authoritative_runtime",
        "promotion_authority": False,
    }
    monkeypatch.setattr(
        runner,
        "_validate_candidate_release_authority_bundle",
        lambda *_args, **_kwargs: release_authority_evidence,
    )

    evidence = runner._projection_evidence(env)
    assert evidence == {
        "release_id": release_root.name,
        "release_root": str(release_root),
        "projection_sha256": projection_sha256,
        "projection_files": projected_files,
        "projection_file_count": len(projected_files),
        "projection_bytes": sum(int(row["size_bytes"]) for row in projected_files),
        "projection_commit": COMMIT,
        "prepared_image_locator": env["EA_MANFRED_IMAGE"],
        "prepared_image_id": IMAGE_ID,
        "image_build_authority_binding": image_build_authority_binding,
        "projection_tree_revalidated": True,
        "memorial_surface": prepare.MEMORIAL_SURFACE,
        "spatial_scope": prepare.SPATIAL_SCOPE,
        "public_property_tours_packaged": False,
        "memorial_spatial_receipt_generated": False,
        "release_authority": release_authority_evidence,
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

    monkeypatch.setattr(runner, "_assert_loopback_port_not_listening", assert_port_free)
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

    monkeypatch.setattr(runner, "_assert_loopback_port_not_listening", assert_port_free)
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
            runner._assert_loopback_port_not_listening(int(listener.getsockname()[1]))
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


def test_nested_candidate_lifecycle_conflicts_on_fleet_lock() -> None:
    project = "ea-manfred-candidate-project-lock-a1b2c3d4"
    with runner._hold_candidate_locks(project, 18991):
        with pytest.raises(RuntimeError, match="fleet_lock_held"):
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
    authority = _FakeCandidateVexpAuthority()
    mutation_evidence: list[dict[str, object]] = []
    contract, evidence = runner._candidate_openapi_contract_snapshot(
        ["docker", "compose", "--project-name", PROJECT],
        {"PATH": "/usr/bin:/bin"},
        vexp_authority=authority,
        vexp_mutation_evidence=mutation_evidence,
    )

    assert contract == runner._canonical_openapi_contract(document)
    assert evidence["snapshot_source"] == runner.CANDIDATE_OPENAPI_SNAPSHOT_SOURCE
    assert evidence["public_docs_config_retired"] is True
    assert evidence["operation_count"] == 2
    assert environments == [{"PATH": "/usr/bin:/bin"}]
    assert commands[0][-6:-3] == ["exec", "-T", "api"]
    assert commands[0][-3:-1] == ["python", "-c"]
    assert commands[0][-1] == runner.CANDIDATE_OPENAPI_SNAPSHOT_SCRIPT
    assert authority.mutation_boundaries == ["before_candidate_exec"]
    assert len(mutation_evidence) == 1

    exposed = copy.deepcopy(envelope)
    exposed["openapi_url"] = "/openapi.json"
    monkeypatch.setattr(
        runner,
        "_run_bounded_output",
        lambda *_args, **_kwargs: json.dumps(exposed).encode("utf-8"),
    )
    with pytest.raises(RuntimeError, match="internal_openapi_docs_exposed"):
        runner._candidate_openapi_contract_snapshot(
            ["docker", "compose"],
            {},
            vexp_authority=authority,
            vexp_mutation_evidence=mutation_evidence,
        )
    assert authority.mutation_boundaries == ["before_candidate_exec"] * 2
    assert len(mutation_evidence) == 2


def test_candidate_proof_never_execs_live_openapi_and_defers_comparison() -> None:
    source = inspect.getsource(runner._prove_candidate_with_execution_inputs)

    assert "_live_openapi_contract_snapshot" not in source
    assert '"live_comparison_status": "deferred_to_governed_promotion"' in source
    assert '"candidate_preserves_live_contract": False' in source
    assert '"candidate_live_contract_claim_allowed": False' in source
    assert not hasattr(runner, "_live_openapi_contract_snapshot")


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
    evidence = runner._assert_candidate_openapi_retired("http://127.0.0.1:18091")
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
        with pytest.raises(RuntimeError, match="openapi_retirement_contract_invalid"):
            runner._assert_candidate_openapi_retired("http://127.0.0.1:18091")
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
    candidate_document["paths"]["/version"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]["additionalProperties"] = {
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
    candidate_schema = candidate_document["paths"]["/version"]["get"]["responses"][
        "200"
    ]["content"]["application/json"]["schema"]
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
        candidate_schema["additionalProperties"]["anyOf"].append({"type": "null"})
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


@pytest.mark.parametrize("case", ["partially_retired", "reintroduced"])
def test_openapi_retirement_rejects_partial_or_reintroduced_policy(case: str) -> None:
    live_document = _meaningful_openapi_document()
    candidate_document = copy.deepcopy(live_document)
    if case == "partially_retired":
        candidate_document["paths"].pop("/v1/internal/governed-spatial-render/compose")
    else:
        _retire_governed_spatial_operations(live_document)
        candidate_document = copy.deepcopy(live_document)
        candidate_document["paths"]["/v1/internal/governed-spatial-render/build"] = {
            "post": {"responses": {"202": {}}}
        }

    live = runner._canonical_openapi_contract(live_document)
    candidate = runner._canonical_openapi_contract(candidate_document)
    with pytest.raises(RuntimeError, match="openapi_contract_regression"):
        runner._assert_openapi_contract_preserved(live, candidate)


def test_openapi_retirement_is_idempotent_after_live_policy_applied() -> None:
    live_document = _meaningful_openapi_document()
    _retire_governed_spatial_operations(live_document)
    contract = runner._canonical_openapi_contract(live_document)

    result = runner._assert_openapi_contract_preserved(contract, contract)

    assert result["retirement_policy_exact_match"] is True
    assert result["retirement_allowed_operations"] == list(
        EXPECTED_OPENAPI_RETIREMENT_OPERATIONS
    )
    assert result["retired_operations"] == list(EXPECTED_OPENAPI_RETIREMENT_OPERATIONS)
    assert result["retired_operation_count"] == len(
        EXPECTED_OPENAPI_RETIREMENT_OPERATIONS
    )
    assert result["candidate_preserves_live_contract"] is True


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
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("candidate-smoke-failed")
        ),
    )
    monkeypatch.setattr(runner, "_assert_candidate_project_absent", lambda _project: {})
    monkeypatch.setattr(
        runner, "_assert_loopback_port_not_listening", lambda _port: None
    )
    runtime_receipt = tmp_path / "runtime.json"

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


def test_existing_runtime_receipt_is_preserved_and_blocks_start(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    env_file, env = _candidate_env(tmp_path)
    _patch_prestart(monkeypatch, env)
    commands: list[list[str]] = []
    monkeypatch.setattr(
        runner,
        "_run",
        lambda argv, **_kwargs: commands.append(list(argv)) or b"",
    )
    runtime_receipt = tmp_path / "runtime.json"
    original = b'{"status":"operator-owned"}\n'
    runtime_receipt.write_bytes(original)
    runtime_receipt.chmod(0o600)

    with pytest.raises(RuntimeError, match="receipt_output_exists"):
        runner.prove_candidate(
            env_file=env_file,
            compose_file=tmp_path / "compose.yml",
            receipt_path=runtime_receipt,
            wait_seconds=60,
        )

    assert runtime_receipt.read_bytes() == original
    assert commands == []


def test_spatial_browser_receipt_argument_is_forbidden_and_existing_file_preserved(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    env_file, env = _candidate_env(tmp_path)
    _patch_prestart(monkeypatch, env)
    commands: list[list[str]] = []
    monkeypatch.setattr(
        runner,
        "_run",
        lambda argv, **_kwargs: commands.append(list(argv)) or b"",
    )
    runtime_receipt = tmp_path / "runtime.json"
    spatial_receipt = tmp_path / "candidate-browser.v5.json"
    original = b'{"status":"operator-owned"}\n'
    spatial_receipt.write_bytes(original)
    spatial_receipt.chmod(0o600)

    with pytest.raises(
        RuntimeError,
        match="spatial_browser_receipt_forbidden_in_conversation_only",
    ):
        runner.prove_candidate(
            env_file=env_file,
            compose_file=tmp_path / "compose.yml",
            receipt_path=runtime_receipt,
            spatial_browser_receipt_path=spatial_receipt,
            wait_seconds=60,
        )

    assert spatial_receipt.read_bytes() == original
    assert not runtime_receipt.exists()
    assert commands == []


@pytest.mark.parametrize(
    "spatial_name",
    ["runtime.json", "candidate-contribution.private.json"],
)
def test_spatial_browser_receipt_argument_is_forbidden_before_alias_checks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    spatial_name: str,
) -> None:
    env_file, env = _candidate_env(tmp_path)
    _patch_prestart(monkeypatch, env)
    commands: list[list[str]] = []
    monkeypatch.setattr(
        runner,
        "_run",
        lambda argv, **_kwargs: commands.append(list(argv)) or b"",
    )
    runtime_receipt = tmp_path / "runtime.json"

    with pytest.raises(
        RuntimeError,
        match="spatial_browser_receipt_forbidden_in_conversation_only",
    ):
        runner.prove_candidate(
            env_file=env_file,
            compose_file=tmp_path / "compose.yml",
            receipt_path=runtime_receipt,
            spatial_browser_receipt_path=tmp_path / spatial_name,
            wait_seconds=60,
        )

    assert not runtime_receipt.exists()
    assert commands == []


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
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
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
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("candidate-smoke-failed")
        ),
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

    assert absence_checks == [PROJECT, PROJECT]


def test_candidate_cleanup_retries_bounded_compose_down_after_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[tuple[list[str], int, dict[str, str]]] = []
    attempts = 0

    def run(
        argv: list[str],
        *,
        timeout: int,
        environment: dict[str, str],
    ) -> bytes:
        nonlocal attempts
        commands.append((list(argv), timeout, dict(environment)))
        attempts += 1
        if attempts == 1:
            raise runner.subprocess.TimeoutExpired(argv, timeout)
        return b""

    absence_checks: list[str] = []
    monkeypatch.setattr(runner, "_run", run)
    monkeypatch.setattr(
        runner,
        "_assert_candidate_project_absent",
        lambda project: absence_checks.append(project) or {},
    )

    authority = _FakeCandidateVexpAuthority()
    evidence: list[dict[str, object]] = []
    runner._cleanup_candidate_project(
        compose=["docker", "compose", "--project-name", PROJECT],
        environment={"PATH": "/usr/bin:/bin"},
        project=PROJECT,
        vexp_authority=authority,
        vexp_mutation_evidence=evidence,
    )

    assert [timeout for _argv, timeout, _environment in commands] == [120, 180]
    assert all("down" in argv and "--volumes" in argv for argv, _t, _e in commands)
    assert all(
        argv[argv.index("--project-name") + 1] == PROJECT
        for argv, _timeout, _environment in commands
    )
    assert all(
        environment == {"PATH": "/usr/bin:/bin"}
        for _argv, _timeout, environment in commands
    )
    assert absence_checks == [PROJECT]
    assert authority.mutation_boundaries == [
        "before_candidate_cleanup",
        "before_candidate_cleanup",
    ]
    assert len(evidence) == 2


def test_persistent_compose_timeout_uses_exact_candidate_label_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = {
        "project": PROJECT,
        "containers": [
            {
                "container_id": "candidate-api-id",
                "name": f"{PROJECT}-api-1",
                "service": "api",
            }
        ],
        "networks": [
            {
                "network_id": "candidate-backend-id",
                "name": f"{PROJECT}_backend",
                "compose_network": "backend",
            }
        ],
        "volumes": [
            {
                "name": f"{PROJECT}_artifacts",
                "compose_volume": "artifacts",
            }
        ],
    }
    commands: list[tuple[list[str], int]] = []

    def run(argv: list[str], *, timeout: int, **_kwargs: object) -> bytes:
        commands.append((list(argv), timeout))
        if "down" in argv:
            raise runner.subprocess.TimeoutExpired(argv, timeout)
        return b""

    monkeypatch.setattr(runner, "_run", run)
    monkeypatch.setattr(runner, "_project_snapshot", lambda project: snapshot)
    monkeypatch.setattr(runner, "_assert_candidate_project_absent", lambda _project: {})

    authority = _FakeCandidateVexpAuthority()
    evidence: list[dict[str, object]] = []
    runner._cleanup_candidate_project(
        compose=["docker", "compose", "--project-name", PROJECT],
        environment={"PATH": "/usr/bin:/bin"},
        project=PROJECT,
        vexp_authority=authority,
        vexp_mutation_evidence=evidence,
    )

    assert [timeout for argv, timeout in commands if "down" in argv] == [120, 180]
    destructive = [argv for argv, _timeout in commands if "down" not in argv]
    assert destructive == [
        ["docker", "container", "rm", "--force", "candidate-api-id"],
        ["docker", "network", "rm", "candidate-backend-id"],
        ["docker", "volume", "rm", f"{PROJECT}_artifacts"],
    ]
    assert not any("ea-api" in value for argv in destructive for value in argv)
    assert authority.mutation_boundaries == ["before_candidate_cleanup"] * 5
    assert len(evidence) == 5


def test_forced_cleanup_rejects_scope_mismatch_before_any_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hostile = {
        "project": PROJECT,
        "containers": [
            {
                "container_id": "live-api-id",
                "name": "ea-api",
                "service": "api",
            }
        ],
        "networks": [],
        "volumes": [],
    }
    commands: list[list[str]] = []
    monkeypatch.setattr(runner, "_project_snapshot", lambda _project: hostile)
    monkeypatch.setattr(
        runner,
        "_run",
        lambda argv, **_kwargs: commands.append(list(argv)) or b"",
    )

    authority = _FakeCandidateVexpAuthority()
    evidence: list[dict[str, object]] = []
    with pytest.raises(RuntimeError, match="forced_cleanup_scope_invalid"):
        runner._force_remove_candidate_project(
            PROJECT,
            vexp_authority=authority,
            vexp_mutation_evidence=evidence,
        )
    assert commands == []
    assert authority.mutation_boundaries == []
    assert evidence == []


@pytest.mark.parametrize(
    ("compose", "environment"),
    [
        (["docker", "compose", "--project-name", "ea"], {}),
        (
            ["docker", "compose", "--project-name", PROJECT, "-p", "ea"],
            {},
        ),
        (
            ["docker", "compose", "--project-name", PROJECT, "-p=ea"],
            {},
        ),
        (
            ["docker", "compose", "--project-name", PROJECT, "-pea"],
            {},
        ),
        (
            ["docker", "compose", "--project-name", PROJECT],
            {"COMPOSE_PROJECT_NAME": "ea"},
        ),
    ],
)
def test_candidate_cleanup_rejects_hostile_compose_scope_before_mutation(
    monkeypatch: pytest.MonkeyPatch,
    compose: list[str],
    environment: dict[str, str],
) -> None:
    commands: list[list[str]] = []
    monkeypatch.setattr(
        runner,
        "_run",
        lambda argv, **_kwargs: commands.append(list(argv)) or b"",
    )
    with pytest.raises(
        (RuntimeError, ValueError),
        match="candidate_(cleanup_scope|project_name)_invalid",
    ):
        runner._cleanup_candidate_project(
            compose=compose,
            environment=environment,
            project=PROJECT,
            vexp_authority=_FakeCandidateVexpAuthority(),
            vexp_mutation_evidence=[],
        )
    assert commands == []


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
        lambda *_args, **_kwargs: (_ for _ in ()).throw(KeyboardInterrupt()),
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
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
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
    forced_cleanup_attempts: list[str] = []

    def run(argv: list[str], **_kwargs: object) -> bytes:
        if "down" in argv:
            raise KeyboardInterrupt()
        return b""

    monkeypatch.setattr(runner, "_run", run)
    monkeypatch.setattr(
        runner,
        "_assert_redis",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            runner.GovernedSignalInterrupt(signal.SIGTERM)
        ),
    )
    monkeypatch.setattr(
        runner,
        "_assert_candidate_project_absent",
        lambda project: absence_checked.append(project) or {},
    )

    def interrupt_forced_cleanup(project: str, **_kwargs: object) -> None:
        forced_cleanup_attempts.append(project)
        raise KeyboardInterrupt()

    monkeypatch.setattr(
        runner, "_force_remove_candidate_project", interrupt_forced_cleanup
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
    assert forced_cleanup_attempts == [PROJECT]
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
                "--vexp-state-path",
                str(tmp_path / "state.json"),
                "--vexp-state-owner-uid",
                str(os.geteuid()),
            ]
        )
        == expected_status
    )


@pytest.mark.parametrize("include_spatial_output", [False, True])
def test_main_spatial_browser_receipt_option_is_removed_from_memorial_lane(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    include_spatial_output: bool,
) -> None:
    captured: dict[str, object] = {}

    def prove(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"schema": runner.RECEIPT_SCHEMA, "status": "pass"}

    monkeypatch.setattr(runner, "prove_candidate", prove)
    spatial_output = tmp_path / "candidate-browser.v5.json"
    argv = [
        "--env-file",
        str(tmp_path / "candidate.env"),
        "--receipt",
        str(tmp_path / "runtime.json"),
        "--vexp-state-path",
        str(tmp_path / "state.json"),
        "--vexp-state-owner-uid",
        str(os.geteuid()),
    ]
    if include_spatial_output:
        argv.extend(["--spatial-browser-receipt", str(spatial_output)])

    if include_spatial_output:
        with pytest.raises(SystemExit) as exc_info:
            runner.main(argv)
        assert exc_info.value.code == 2
        assert captured == {}
    else:
        assert runner.main(argv) == 0
        assert "spatial_browser_receipt_path" not in captured


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


def test_runtime_receipt_is_no_replace_private_and_inode_bound(
    tmp_path: Path,
) -> None:
    receipt = tmp_path / "runtime-v4.json"
    payload = {"schema": runner.RECEIPT_SCHEMA, "status": "pass"}

    artifact = runner._atomic_receipt(receipt, payload)
    assert artifact.path == receipt
    assert stat.S_IMODE(receipt.stat().st_mode) == 0o600
    assert json.loads(receipt.read_text(encoding="utf-8")) == payload
    with pytest.raises(RuntimeError, match="receipt_output_exists"):
        runner._atomic_receipt(receipt, payload)

    receipt.unlink()
    replacement = b'{"status":"operator-replacement"}\n'
    receipt.write_bytes(replacement)
    receipt.chmod(0o600)
    assert runner._unlink_created_receipt_artifact(artifact) is False
    assert receipt.read_bytes() == replacement


def test_spatial_browser_receipt_is_exact_private_no_replace_artifact(
    tmp_path: Path,
) -> None:
    browser_receipt = {
        "schema": runner.SPATIAL_BROWSER_RECEIPT_SCHEMA,
        "status": "pass",
        "secret_material_recorded": False,
        "surfaces": {"desktop": {"status": 200}},
    }
    runtime_receipt = {
        "schema": runner.RECEIPT_SCHEMA,
        "status": "pass",
        "spatial_handoff_runtime": {
            "candidate_browser_gate": browser_receipt,
        },
    }
    output = tmp_path / "candidate-browser.v5.json"
    artifacts: dict[Path, runner._CreatedReceiptArtifact] = {}

    artifact = runner._persist_spatial_browser_receipt(
        output,
        runtime_receipt,
        created_artifacts=artifacts,
    )

    metadata = output.stat()
    assert artifact.path == output
    assert artifacts == {output: artifact}
    assert metadata.st_uid == os.geteuid()
    assert metadata.st_nlink == 1
    assert stat.S_IMODE(metadata.st_mode) == 0o600
    assert json.loads(output.read_text(encoding="utf-8")) == browser_receipt
    original = output.read_bytes()
    with pytest.raises(RuntimeError, match=runner.RECEIPT_OUTPUT_EXISTS):
        runner._persist_spatial_browser_receipt(output, runtime_receipt)
    assert output.read_bytes() == original


def test_spatial_browser_receipt_rejects_symlink_and_unsafe_parent(
    tmp_path: Path,
) -> None:
    browser_receipt = {
        "schema": runner.SPATIAL_BROWSER_RECEIPT_SCHEMA,
        "status": "pass",
        "secret_material_recorded": False,
    }
    runtime_receipt = {
        "spatial_handoff_runtime": {
            "candidate_browser_gate": browser_receipt,
        }
    }
    target = tmp_path / "operator-owned.json"
    original = b'{"operator":"preserve"}\n'
    target.write_bytes(original)
    target.chmod(0o600)
    symlink_output = tmp_path / "candidate-browser.v5.json"
    symlink_output.symlink_to(target)

    with pytest.raises(RuntimeError, match=runner.RECEIPT_PATH_INVALID):
        runner._persist_spatial_browser_receipt(symlink_output, runtime_receipt)
    assert target.read_bytes() == original

    unsafe_parent = tmp_path / "unsafe"
    unsafe_parent.mkdir()
    unsafe_parent.chmod(0o777)
    with pytest.raises(RuntimeError, match=runner.RECEIPT_PARENT_INVALID):
        runner._persist_spatial_browser_receipt(
            unsafe_parent / "candidate-browser.v5.json",
            runtime_receipt,
        )


def test_spatial_browser_receipt_rejects_invalid_embedded_gate(
    tmp_path: Path,
) -> None:
    output = tmp_path / "candidate-browser.v5.json"
    runtime_receipt = {
        "spatial_handoff_runtime": {
            "candidate_browser_gate": {
                "schema": runner.SPATIAL_BROWSER_RECEIPT_SCHEMA,
                "status": "pass",
                "secret_material_recorded": True,
            }
        }
    }

    with pytest.raises(RuntimeError, match=runner.SPATIAL_BROWSER_RECEIPT_INVALID):
        runner._persist_spatial_browser_receipt(output, runtime_receipt)
    assert not output.exists()


def test_contribution_withdrawal_helper_preserves_token_on_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    receipt = tmp_path / "candidate-contribution.private.json"
    content = b'{"manage_token":"private"}\n'
    receipt.write_bytes(content)
    receipt.chmod(0o600)
    monkeypatch.setattr(
        runner,
        "_withdraw_contribution",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("withdraw-unavailable")
        ),
    )

    with pytest.raises(RuntimeError, match="withdraw-unavailable"):
        runner._withdraw_candidate_contribution_if_present(
            "http://127.0.0.1:18091",
            receipt,
        )
    assert receipt.read_bytes() == content

    monkeypatch.setattr(
        runner,
        "_withdraw_contribution",
        lambda _base_url, path: path.unlink(),
    )
    assert (
        runner._withdraw_candidate_contribution_if_present(
            "http://127.0.0.1:18091",
            receipt,
        )
        is True
    )
    assert not receipt.exists()


def test_interrupted_no_replace_link_window_is_completed_exactly(
    tmp_path: Path,
) -> None:
    temporary = tmp_path / ".ea-manfred-receipt.1234.abcdef012345abcdef012345.tmp"
    receipt = tmp_path / "runtime-v4.json"
    payload = b'{"schema":"ea.manfred_memorial_candidate_runtime.v4"}\n'
    temporary.write_bytes(payload)
    temporary.chmod(0o600)
    os.link(temporary, receipt)
    assert receipt.stat().st_nlink == 2

    assert runner._complete_interrupted_receipt_publication(receipt) is True
    assert not temporary.exists()
    assert receipt.read_bytes() == payload
    assert receipt.stat().st_nlink == 1
    assert runner._complete_interrupted_receipt_publication(receipt) is False


def test_unrelated_hardlink_is_not_treated_as_interrupted_publication(
    tmp_path: Path,
) -> None:
    receipt = tmp_path / "runtime-v4.json"
    unrelated = tmp_path / "operator-backup.json"
    receipt.write_text("{}\n", encoding="utf-8")
    receipt.chmod(0o600)
    os.link(receipt, unrelated)

    assert runner._complete_interrupted_receipt_publication(receipt) is False
    assert receipt.exists()
    assert unrelated.exists()
    assert receipt.stat().st_nlink == 2


def test_runtime_receipt_is_fsynced_before_registry_registration(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    receipt = tmp_path / "runtime-v4.json"
    payload = {"schema": runner.RECEIPT_SCHEMA, "status": "pass"}
    observed: list[Path] = []

    def register(path: Path, *, require_pending: bool = False) -> dict[str, object]:
        observed.append(path)
        assert require_pending is True
        assert path == receipt
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert json.loads(path.read_text(encoding="utf-8")) == payload
        return {"registered": True}

    monkeypatch.setattr(runner, "register_candidate_receipt", register)
    artifacts: dict[Path, runner._CreatedReceiptArtifact] = {}
    result = runner._persist_runtime_receipt(
        receipt,
        payload,
        created_artifacts=artifacts,
    )

    assert result == {"registered": True}
    assert observed == [receipt]
    assert artifacts[receipt].inode == receipt.stat().st_ino


def test_pending_registration_precedes_compose_up_and_clears_after_recovery(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    env_file, env = _candidate_env(tmp_path)
    _patch_prestart(monkeypatch, env)
    events: list[str] = []
    monkeypatch.setattr(
        runner,
        "_candidate_preflight",
        lambda project, port: {"project": project, "loopback_port": port},
    )

    monkeypatch.setattr(
        runner,
        "register_candidate_pending",
        lambda **_kwargs: events.append("pending") or {"pending_registered": True},
    )
    monkeypatch.setattr(
        runner,
        "clear_candidate_pending",
        lambda _project: events.append("cleared") or {"pending_cleared": True},
    )

    def run(argv: list[str], **_kwargs: object) -> bytes:
        if "up" in argv:
            events.append("compose-up")
        if "down" in argv:
            events.append("compose-down")
        return b""

    monkeypatch.setattr(runner, "_run", run)
    monkeypatch.setattr(
        runner,
        "_assert_redis",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("smoke-failed")),
    )
    monkeypatch.setattr(runner, "_assert_candidate_project_absent", lambda _p: {})
    monkeypatch.setattr(
        runner,
        "_wait_for_loopback_port_not_listening",
        lambda _port: None,
    )

    with pytest.raises(RuntimeError, match="smoke-failed"):
        runner.prove_candidate(
            env_file=env_file,
            compose_file=tmp_path / "compose.yml",
            receipt_path=tmp_path / "runtime-v4.json",
            wait_seconds=60,
        )

    assert events[0:2] == ["pending", "compose-up"]
    assert events[-2:] == ["compose-down", "cleared"]


def test_first_smoke_restart_failure_cleans_conversation_candidate_without_contribution(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    env_file, env = _candidate_env(tmp_path)
    _patch_prestart(monkeypatch, env)
    runtime_receipt = tmp_path / "runtime-v4.json"
    events: list[str] = []
    monkeypatch.setattr(
        runner,
        "_candidate_preflight",
        lambda project, port: {"project": project, "loopback_port": port},
    )
    monkeypatch.setattr(runner, "_assert_redis", lambda *_args, **_kwargs: None)

    def verify_candidate(**kwargs: object) -> dict[str, object]:
        assert kwargs.get("submit_receipt") is None
        assert kwargs.get("withdraw_receipt") is None
        assert kwargs.get("conversation_only") is True
        events.append("first-smoke")
        return {
            "checks": ["conversation_only_public_surface"],
            "contribution": {"submitted": False, "withdrawn": False},
        }

    monkeypatch.setattr(runner, "verify_candidate", verify_candidate)

    def run(argv: list[str], **_kwargs: object) -> bytes:
        if "up" in argv:
            events.append("compose-up")
            return b""
        if "ps" in argv and "api" in argv:
            return ("1" * 64).encode("ascii")
        if "restart" in argv:
            events.append("restart-failed")
            raise RuntimeError("restart-failed")
        return b""

    monkeypatch.setattr(runner, "_run", run)

    monkeypatch.setattr(
        runner,
        "_cleanup_candidate_project",
        lambda **_kwargs: events.append("candidate-cleaned"),
    )
    monkeypatch.setattr(
        runner,
        "_assert_candidate_project_absent",
        lambda _project: events.append("candidate-absent") or {},
    )
    monkeypatch.setattr(
        runner,
        "_wait_for_loopback_port_not_listening",
        lambda _port: events.append("port-closed"),
    )
    monkeypatch.setattr(
        runner,
        "clear_candidate_pending",
        lambda _project: events.append("pending-cleared") or {"pending_cleared": True},
    )

    with pytest.raises(RuntimeError, match="restart-failed"):
        runner.prove_candidate(
            env_file=env_file,
            compose_file=tmp_path / "compose.yml",
            receipt_path=runtime_receipt,
            wait_seconds=60,
        )

    assert events == [
        "compose-up",
        "first-smoke",
        "restart-failed",
        "candidate-cleaned",
        "candidate-absent",
        "port-closed",
        "pending-cleared",
    ]


def test_failed_recovery_preserves_pending_registry_intent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    env_file, env = _candidate_env(tmp_path)
    _patch_prestart(monkeypatch, env)
    cleared: list[str] = []
    monkeypatch.setattr(
        runner,
        "_candidate_preflight",
        lambda project, port: {"project": project, "loopback_port": port},
    )
    monkeypatch.setattr(
        runner,
        "register_candidate_pending",
        lambda **_kwargs: {"pending_registered": True},
    )
    monkeypatch.setattr(
        runner,
        "clear_candidate_pending",
        lambda project: cleared.append(project) or {"pending_cleared": True},
    )
    monkeypatch.setattr(runner, "_run", lambda _argv, **_kwargs: b"")
    monkeypatch.setattr(
        runner,
        "_assert_redis",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("smoke-failed")),
    )
    monkeypatch.setattr(runner, "_assert_candidate_project_absent", lambda _p: {})
    monkeypatch.setattr(
        runner,
        "_wait_for_loopback_port_not_listening",
        lambda _port: (_ for _ in ()).throw(RuntimeError("port-still-bound")),
    )

    with pytest.raises(RuntimeError, match="candidate_port_remains_bound"):
        runner.prove_candidate(
            env_file=env_file,
            compose_file=tmp_path / "compose.yml",
            receipt_path=tmp_path / "runtime-v4.json",
            wait_seconds=60,
        )

    assert cleared == []


def test_pending_only_crash_withdraws_contribution_before_cleanup_and_clear(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    env_file, env = _candidate_env(tmp_path)
    _patch_prestart(monkeypatch, env)
    contribution_receipt = tmp_path / "candidate-contribution.private.json"
    contribution_receipt.write_text(
        '{"manage_token":"private"}\n',
        encoding="utf-8",
    )
    contribution_receipt.chmod(0o600)
    events: list[str] = []
    preflight_calls: list[tuple[str, int]] = []
    monkeypatch.setattr(
        runner,
        "candidate_registry_recovery_state",
        lambda **_kwargs: {"state": "pending_only"},
    )
    monkeypatch.setattr(
        runner,
        "_withdraw_candidate_contribution_if_present",
        lambda _base_url, _receipt_path, *, expected_artifact=None: (
            pytest.fail("missing exact contribution artifact")
            if expected_artifact is None
            else (events.append("contribution-withdrawn") or True)
        ),
    )
    monkeypatch.setattr(
        runner,
        "_cleanup_candidate_project",
        lambda **_kwargs: events.append("cleanup"),
    )
    monkeypatch.setattr(
        runner,
        "_assert_candidate_project_absent",
        lambda _project: events.append("absent") or {},
    )
    monkeypatch.setattr(
        runner,
        "_wait_for_loopback_port_not_listening",
        lambda _port: events.append("port-closed"),
    )
    monkeypatch.setattr(
        runner,
        "_assert_live_recovery_unchanged",
        lambda **_kwargs: events.append("live-unchanged"),
    )
    monkeypatch.setattr(
        runner,
        "clear_candidate_pending_exact",
        lambda **kwargs: (
            events.append(
                "pending-cleared" if kwargs.get("resources_absent") is True else "bad"
            )
            or {"pending_cleared": True}
        ),
    )
    monkeypatch.setattr(
        runner,
        "_candidate_preflight",
        lambda project, port: (
            preflight_calls.append((project, port))
            or pytest.fail("fresh candidate launch must require a new invocation")
        ),
    )

    with pytest.raises(
        RuntimeError,
        match="manfred_candidate_pending_recovery_completed:fresh_invocation_required",
    ):
        runner.prove_candidate(
            env_file=env_file,
            compose_file=tmp_path / "compose.yml",
            receipt_path=tmp_path / "runtime-v4.json",
            wait_seconds=60,
        )

    assert events == [
        "contribution-withdrawn",
        "cleanup",
        "absent",
        "port-closed",
        "live-unchanged",
        "pending-cleared",
    ]
    assert preflight_calls == []


def test_pending_only_crash_without_contribution_skips_interaction_authority(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    env_file, env = _candidate_env(tmp_path)
    _patch_prestart(monkeypatch, env)
    events: list[str] = []
    monkeypatch.setattr(
        runner,
        "candidate_registry_recovery_state",
        lambda **_kwargs: {"state": "pending_only"},
    )
    monkeypatch.setattr(
        runner,
        "_withdraw_candidate_contribution_if_present",
        lambda *_args, **_kwargs: pytest.fail(
            "withdraw must not run without a contribution receipt"
        ),
    )
    monkeypatch.setattr(
        runner,
        "_cleanup_candidate_project",
        lambda **_kwargs: events.append("cleanup"),
    )
    monkeypatch.setattr(runner, "_assert_candidate_project_absent", lambda _p: {})
    monkeypatch.setattr(
        runner,
        "_wait_for_loopback_port_not_listening",
        lambda _port: None,
    )
    monkeypatch.setattr(runner, "_assert_live_recovery_unchanged", lambda **_k: None)
    monkeypatch.setattr(
        runner,
        "clear_candidate_pending_exact",
        lambda **_kwargs: {"pending_cleared": True},
    )

    with pytest.raises(
        RuntimeError,
        match="manfred_candidate_pending_recovery_completed:fresh_invocation_required",
    ):
        runner.prove_candidate(
            env_file=env_file,
            compose_file=tmp_path / "compose.yml",
            receipt_path=tmp_path / "runtime-v4.json",
            wait_seconds=60,
        )

    assert events == ["cleanup"]


def test_pending_contribution_withdrawal_failure_preserves_runtime_and_token(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    env_file, env = _candidate_env(tmp_path)
    _patch_prestart(monkeypatch, env)
    contribution_receipt = tmp_path / "candidate-contribution.private.json"
    contribution_receipt.write_text(
        '{"manage_token":"private"}\n',
        encoding="utf-8",
    )
    contribution_receipt.chmod(0o600)
    cleanup_events: list[str] = []
    monkeypatch.setattr(
        runner,
        "candidate_registry_recovery_state",
        lambda **_kwargs: {"state": "pending_only"},
    )
    monkeypatch.setattr(
        runner,
        "_withdraw_candidate_contribution_if_present",
        lambda _base_url, path: (
            pytest.fail("unexpected contribution receipt path")
            if path != contribution_receipt
            else (_ for _ in ()).throw(RuntimeError("withdraw-unavailable"))
        ),
    )
    monkeypatch.setattr(
        runner,
        "_cleanup_candidate_project",
        lambda **_kwargs: cleanup_events.append("cleanup"),
    )

    with pytest.raises(
        RuntimeError,
        match="manfred_candidate_pending_contribution_recovery_failed",
    ):
        runner.prove_candidate(
            env_file=env_file,
            compose_file=tmp_path / "compose.yml",
            receipt_path=tmp_path / "runtime-v4.json",
            wait_seconds=60,
        )

    assert cleanup_events == []
    assert contribution_receipt.is_file()


def test_pending_receipt_crash_resumes_exact_running_candidate_without_up(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    env_file, env = _candidate_env(tmp_path)
    _patch_prestart(monkeypatch, env)
    receipt_payload = {
        "schema": runner.RECEIPT_SCHEMA,
        "status": "pass",
        "memorial_surface": prepare.MEMORIAL_SURFACE,
        "spatial_scope": prepare.SPATIAL_SCOPE,
        "public_property_tours_tested": False,
        "memorial_spatial_receipt_generated": False,
    }
    runtime_receipt = tmp_path / "runtime-v6.json"
    events: list[str] = []
    monkeypatch.setattr(
        runner,
        "candidate_registry_recovery_state",
        lambda **_kwargs: {
            "state": "pending_receipt",
            "receipt_sha256": "f" * 64,
            "runtime_receipt": receipt_payload,
        },
    )
    monkeypatch.setattr(
        runner,
        "_assert_recovered_candidate_runtime",
        lambda **_kwargs: events.append("runtime-verified"),
    )
    monkeypatch.setattr(
        runner,
        "_assert_live_recovery_unchanged",
        lambda **_kwargs: events.append("live-unchanged"),
    )

    def register(path: Path, *, require_pending: bool = False):  # type: ignore[no-untyped-def]
        assert path == runtime_receipt
        assert require_pending is True
        events.append("registered")
        return {"registered": True}

    monkeypatch.setattr(runner, "register_candidate_receipt", register)
    monkeypatch.setattr(
        runner,
        "_run",
        lambda argv, **_kwargs: pytest.fail(f"unexpected mutation: {argv}"),
    )

    recovered = runner.prove_candidate(
        env_file=env_file,
        compose_file=tmp_path / "compose.yml",
        receipt_path=runtime_receipt,
        wait_seconds=60,
    )

    assert recovered == receipt_payload
    assert events == ["runtime-verified", "live-unchanged", "registered"]


def test_invalid_pending_receipt_is_preserved_after_exact_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    env_file, env = _candidate_env(tmp_path)
    _patch_prestart(monkeypatch, env)
    receipt = tmp_path / "runtime-v4.json"
    original = b'{"operator":"preserve"}\n'
    receipt.write_bytes(original)
    receipt.chmod(0o600)
    cleared: list[str] = []
    monkeypatch.setattr(
        runner,
        "candidate_registry_recovery_state",
        lambda **_kwargs: {
            "state": "pending_receipt",
            "receipt_sha256": "e" * 64,
            "runtime_receipt": {"schema": runner.RECEIPT_SCHEMA},
        },
    )
    monkeypatch.setattr(
        runner,
        "_assert_recovered_candidate_runtime",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("identity-drift")),
    )
    monkeypatch.setattr(runner, "_cleanup_candidate_project", lambda **_kwargs: None)
    monkeypatch.setattr(runner, "_assert_candidate_project_absent", lambda _p: {})
    monkeypatch.setattr(
        runner, "_wait_for_loopback_port_not_listening", lambda _p: None
    )
    monkeypatch.setattr(
        runner, "_assert_live_recovery_unchanged", lambda **_kwargs: None
    )
    monkeypatch.setattr(
        runner,
        "clear_candidate_pending_exact",
        lambda **kwargs: (
            cleared.append(str(kwargs["expected_receipt_sha256"]))
            or {"pending_cleared": True}
        ),
    )

    with pytest.raises(RuntimeError, match="recovered_receipt_runtime_invalid"):
        runner.prove_candidate(
            env_file=env_file,
            compose_file=tmp_path / "compose.yml",
            receipt_path=receipt,
            wait_seconds=60,
        )

    assert cleared == ["e" * 64]
    assert receipt.read_bytes() == original


def test_sealed_execution_inputs_are_immutable_and_detached_from_sources(
    tmp_path: Path,
) -> None:
    compose_source = tmp_path / "compose.yml"
    environment_source = tmp_path / "candidate.env"
    compose_bytes = b"name: governed-candidate\nservices: {}\n"
    environment_bytes = b"EA_MANFRED_COMPOSE_PROJECT=sealed-candidate\n"
    environment = {"EA_MANFRED_COMPOSE_PROJECT": "sealed-candidate"}
    compose_source.write_bytes(compose_bytes)
    environment_source.write_bytes(environment_bytes)
    attestation = {
        "git_blob_oid": "c" * 40,
        "sha256": prepare._sha256(compose_bytes),
        "size_bytes": len(compose_bytes),
    }

    with runner._sealed_candidate_execution_inputs(
        compose_bytes=compose_bytes,
        environment_bytes=environment_bytes,
        environment=environment,
        compose_attestation=attestation,
        compose_image_id=IMAGE_ID,
    ) as inputs:
        assert inputs.compose_path != compose_source
        assert inputs.environment_path != environment_source
        assert inputs.compose_path.read_bytes() == compose_bytes
        assert inputs.environment_path.read_bytes() == environment_bytes

        compose_source.write_bytes(b"services:\n  hostile: {}\n")
        environment_source.write_bytes(b"OPENAI_API_KEY=hostile\n")

        runner._assert_sealed_execution_inputs_current(inputs)
        assert inputs.compose_path.read_bytes() == compose_bytes
        assert inputs.environment_path.read_bytes() == environment_bytes
        assert inputs.evidence["transport"] == "sealed_memfd"
        assert inputs.evidence["all_compose_commands_use_sealed_inputs"] is True
        assert inputs.evidence["mutable_source_paths_consumed_by_compose"] is False
        assert inputs.evidence["compose_image_id"] == IMAGE_ID
        assert inputs.evidence["mutable_image_locator_consumed_by_compose"] is False


def test_source_replacement_after_validation_cannot_reach_compose_render(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    env_file, env = _candidate_env(tmp_path)
    compose_file = tmp_path / "compose.yml"
    compose_bytes = b"name: governed-candidate\nservices: {}\n"
    compose_file.write_bytes(compose_bytes)
    original_environment_bytes = env_file.read_bytes()
    _patch_prestart(monkeypatch, env)

    def replace_sources(
        _compose_file: Path,
        *,
        expected_commit: str,
    ) -> tuple[dict[str, object], bytes]:
        env_file.write_bytes(b"OPENAI_API_KEY=hostile\n")
        compose_file.write_bytes(b"services:\n  hostile: {}\n")
        return (
            {
                "canonical_relative_path": (
                    runner.CANDIDATE_COMPOSE_RELATIVE_PATH.as_posix()
                ),
                "canonical_source_path": str(compose_file.resolve()),
                "candidate_commit": expected_commit,
                "git_blob_oid": "c" * 40,
                "sha256": prepare._sha256(compose_bytes),
                "size_bytes": len(compose_bytes),
                "canonical_path_enforced": True,
                "tracked_blob_bytes_enforced": True,
            },
            compose_bytes,
        )

    observed: list[tuple[bytes, bytes, Path, Path]] = []

    def render(
        sealed_env_file: Path,
        sealed_compose_file: Path,
        **_kwargs: object,
    ) -> dict[str, object]:
        observed.append(
            (
                sealed_env_file.read_bytes(),
                sealed_compose_file.read_bytes(),
                sealed_env_file,
                sealed_compose_file,
            )
        )
        raise RuntimeError("stop-after-sealed-render")

    monkeypatch.setattr(runner, "_candidate_compose_source_snapshot", replace_sources)
    monkeypatch.setattr(runner, "_rendered_compose", render)

    with pytest.raises(RuntimeError, match="stop-after-sealed-render"):
        runner.prove_candidate(
            env_file=env_file,
            compose_file=compose_file,
            receipt_path=tmp_path / "runtime-v4.json",
            wait_seconds=60,
        )

    assert len(observed) == 1
    sealed_environment, sealed_compose, sealed_env_path, sealed_compose_path = observed[
        0
    ]
    assert sealed_environment == original_environment_bytes
    assert sealed_compose == compose_bytes
    assert sealed_env_path != env_file
    assert sealed_compose_path != compose_file
    assert env_file.read_bytes() == b"OPENAI_API_KEY=hostile\n"
    assert compose_file.read_bytes() == b"services:\n  hostile: {}\n"


def test_recovered_runtime_rebinds_projection_compose_and_execution_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projection = {
        "release_id": "release-a",
        "projection_sha256": "d" * 64,
        "projection_files": [],
        "projection_file_count": 0,
        "projection_bytes": 0,
        "projection_commit": COMMIT,
    }
    compose_attestation = {"sha256": "c" * 64}
    execution_inputs = {"environment_sha256": "e" * 64}
    images = {
        "api": {"container_id": "1" * 64, "image_id": IMAGE_ID},
        "gateway": {"container_id": "2" * 64, "image_id": IMAGE_ID},
        "prepared_image_id": IMAGE_ID,
        "revision_label": COMMIT,
        "all_match_prepared_image": True,
    }
    runtime_identity = {"revision_agreement_verified": True}
    runtime_projection = {"runtime_bytes_match_prepared_projection": True}
    runtime_posture = {"running_and_healthy": True}
    observed_hashes: list[str] = []

    monkeypatch.setattr(
        runner,
        "_candidate_container_image_evidence",
        lambda **_kwargs: images,
    )
    monkeypatch.setattr(
        runner,
        "_candidate_runtime_version_identity",
        lambda *_args, **_kwargs: runtime_identity,
    )
    monkeypatch.setattr(
        runner,
        "_candidate_runtime_projection_evidence",
        lambda **_kwargs: runtime_projection,
    )

    def posture(**kwargs: object) -> dict[str, object]:
        observed_hashes.append(str(kwargs["execution_environment_sha256"]))
        return runtime_posture

    monkeypatch.setattr(runner, "_candidate_api_runtime_posture", posture)
    monkeypatch.setattr(runner, "_assert_redis", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(runner, "_assert_logs_clean", lambda *_args: None)
    receipt = {
        **projection,
        "compose_attestation": compose_attestation,
        "execution_inputs": execution_inputs,
        "candidate_container_images": images,
        "candidate_container_images_initial": images,
        "candidate_container_images_final": images,
        "candidate_container_image_identity_stable": True,
        "runtime_version_identity": runtime_identity,
        "runtime_projection_initial": runtime_projection,
        "runtime_projection_final": runtime_projection,
        "runtime_projection_identity_stable": True,
        "runtime_api_posture": runtime_posture,
    }
    authority = _FakeCandidateVexpAuthority()
    evidence: list[dict[str, object]] = []

    runner._assert_recovered_candidate_runtime(
        receipt=receipt,
        compose=["docker", "compose"],
        environment={},
        project=PROJECT,
        base_url="http://127.0.0.1:18091",
        projection=projection,
        candidate_env={},
        compose_attestation=compose_attestation,
        execution_inputs_evidence=execution_inputs,
        execution_environment_sha256="e" * 64,
        vexp_authority=authority,
        vexp_mutation_evidence=evidence,
    )
    assert observed_hashes == ["e" * 64]

    receipt["projection_sha256"] = "f" * 64
    with pytest.raises(RuntimeError, match="recovered_projection_identity_invalid"):
        runner._assert_recovered_candidate_runtime(
            receipt=receipt,
            compose=["docker", "compose"],
            environment={},
            project=PROJECT,
            base_url="http://127.0.0.1:18091",
            projection=projection,
            candidate_env={},
            compose_attestation=compose_attestation,
            execution_inputs_evidence=execution_inputs,
            execution_environment_sha256="e" * 64,
            vexp_authority=authority,
            vexp_mutation_evidence=evidence,
        )


def test_runtime_projection_snapshot_must_equal_prepared_file_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        {
            "path": "public_memorials/manfred/memorial.json",
            "sha256": "a" * 64,
            "size_bytes": 3,
            "mode": "444",
        }
    ]
    digest = prepare._sha256(
        json.dumps(rows, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    projection = {
        "projection_sha256": digest,
        "projection_files": rows,
        "projection_file_count": 1,
        "projection_bytes": 3,
    }
    payload = {
        "schema": runner.RUNTIME_PROJECTION_SCHEMA,
        "projection_sha256": digest,
        "rows": rows,
    }
    monkeypatch.setattr(
        runner,
        "_run_bounded_output",
        lambda *_args, **_kwargs: json.dumps(payload).encode("utf-8"),
    )

    authority = _FakeCandidateVexpAuthority()
    mutation_evidence: list[dict[str, object]] = []
    evidence = runner._candidate_runtime_projection_evidence(
        compose=["docker", "compose"],
        environment={},
        projection=projection,
        vexp_authority=authority,
        vexp_mutation_evidence=mutation_evidence,
    )
    assert evidence["projection_sha256"] == digest
    assert evidence["runtime_bytes_match_prepared_projection"] is True

    payload["rows"] = [{**rows[0], "sha256": "b" * 64}]
    with pytest.raises(RuntimeError, match="runtime_projection_mismatch"):
        runner._candidate_runtime_projection_evidence(
            compose=["docker", "compose"],
            environment={},
            projection=projection,
            vexp_authority=authority,
            vexp_mutation_evidence=mutation_evidence,
        )
    assert authority.mutation_boundaries == ["before_candidate_exec"] * 2
    assert len(mutation_evidence) == 2


@pytest.mark.parametrize("receipt_case", ["hardlink", "noncanonical"])
def test_projection_receipt_rejects_replaceable_or_noncanonical_evidence(
    tmp_path: Path,
    receipt_case: str,
) -> None:
    release_root = tmp_path / "releases" / "release-a"
    release_root.mkdir(parents=True)
    receipt_path = tmp_path / "receipts" / "release-a.json"
    receipt_path.parent.mkdir()
    if receipt_case == "hardlink":
        receipt_path.write_bytes(prepare._receipt_bytes({"status": "pass"}))
        os.link(receipt_path, receipt_path.with_name("operator-backup.json"))
    else:
        receipt_path.write_bytes(b'{"status":"pass"}\n')
    receipt_path.chmod(0o600)

    with pytest.raises(RuntimeError, match="projection_receipt_(invalid|mismatch)"):
        runner._projection_evidence({"EA_MANFRED_RELEASE_ROOT": str(release_root)})


def test_spatial_projection_revalidation_threads_retained_review_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    release_root = tmp_path / "releases" / "release-a"
    spatial_root = release_root / "public_property_tours"
    spatial_root.mkdir(parents=True)
    slug = prepare.PROPERTY_AUTHORIZED_SLUG
    asset_paths = [
        "generated-reconstruction/reconstruction.json",
        "generated-reconstruction/source-floorplan.png",
        "generated-reconstruction/vendor/examples/jsm/controls/OrbitControls.js",
        "generated-reconstruction/vendor/three.module.js",
        "generated-reconstruction/viewer.html",
    ]
    observed_files = [
        {
            "path": f"{slug}/tour.json",
            "sha256": "1" * 64,
            "size_bytes": 1,
            "mode": "444",
        },
        *[
            {
                "path": f"{slug}/{path}",
                "sha256": format(index, "064x"),
                "size_bytes": 1,
                "mode": "444",
            }
            for index, path in enumerate(asset_paths, start=2)
        ],
    ]
    spatial_digest = "a" * 64
    final_path = (tmp_path / "review" / "final.json").resolve()
    browser_path = (tmp_path / "review" / "browser.json").resolve()
    review_evidence = {
        "flagship_final": {
            "schema": "propertyquarry.flagship_3d_review_receipt.v1",
            "status": "polished_review_candidate_pass_guarded_not_published",
            "sha256": "b" * 64,
            "source_path": str(final_path),
        },
        "exact_viewer_browser": {
            "schema": "propertyquarry.exact_viewer_browser_audit.v3",
            "status": "pass",
            "sha256": "c" * 64,
            "source_path": str(browser_path),
        },
    }
    authority = {
        "schema": prepare.PROPERTY_PUBLICATION_AUTHORITY_SCHEMA,
        "status": "authorized",
        "public_activation_authority": True,
    }
    authority_sha256 = prepare._sha256(prepare._canonical_json_bytes(authority))
    monkeypatch.setattr(runner, "PROPERTY_AUTHORITY_SHA256", authority_sha256)
    receipt = {
        "schema": prepare.SPATIAL_PROJECTION_SCHEMA,
        "status": "pass",
        "release_id": "release-a",
        "public_activation_authority": False,
        "spatial_release_root": str(spatial_root),
        "spatial_handoff_included": True,
        "candidate_handoff_authorized": True,
        "slug": slug,
        "spatial_projection_sha256": spatial_digest,
        "files": observed_files,
        "file_count": 6,
        "projection_bytes": 6,
        "asset_paths": asset_paths,
        "viewer_relpath": "generated-reconstruction/viewer.html",
        "proof_relpath": "generated-reconstruction/reconstruction.json",
        "route_labels": ["entry", "living"],
        "upstream_publication_authority": authority,
        "upstream_publication_authority_sha256": authority_sha256,
        "upstream_public_activation_authority": True,
        "upstream_package_sha256": "d" * 64,
        "upstream_tour_manifest_sha256": "e" * 64,
        "pre_authority_manifest_canonical_sha256": "f" * 64,
        "review_evidence": review_evidence,
    }
    receipt_path = tmp_path / "receipts" / "release-a.spatial.json"
    receipt_path.parent.mkdir()
    receipt_bytes = prepare._receipt_bytes(receipt)
    receipt_path.write_bytes(receipt_bytes)
    receipt_path.chmod(0o600)
    projection_receipt = {
        "spatial_receipt_path": str(receipt_path),
        "spatial_receipt_sha256": prepare._sha256(receipt_bytes),
        "spatial_release_root": str(spatial_root),
        "spatial_handoff_included": True,
        "spatial_slug": slug,
        "spatial_projection_sha256": spatial_digest,
        "spatial_file_count": 6,
        "spatial_projection_bytes": 6,
        "spatial_upstream_public_activation_authority": True,
        "spatial_ea_public_activation_authority": False,
    }
    snapshot = {"tour.json": b"{}\n", **{path: b"x" for path in asset_paths}}
    validated = {
        "slug": slug,
        "asset_paths": asset_paths,
        "viewer_relpath": "generated-reconstruction/viewer.html",
        "proof_relpath": "generated-reconstruction/reconstruction.json",
        "route_labels": ["entry", "living"],
        "upstream_publication_authority": authority,
        "upstream_publication_authority_sha256": authority_sha256,
        "upstream_public_activation_authority": True,
        "upstream_package_sha256": "d" * 64,
        "upstream_tour_manifest_sha256": "e" * 64,
        "pre_authority_manifest_canonical_sha256": "f" * 64,
        "review_evidence": review_evidence,
    }
    captured: list[tuple[Path, Path]] = []

    def validate(**kwargs: object) -> dict[str, object]:
        captured.append(
            (
                Path(str(kwargs["final_review_receipt_path"])),
                Path(str(kwargs["browser_review_receipt_path"])),
            )
        )
        return validated

    monkeypatch.setattr(
        runner,
        "_tree_digest",
        lambda _root: (spatial_digest, observed_files),
    )
    monkeypatch.setattr(
        runner,
        "_spatial_tree_snapshot",
        lambda *_args, **_kwargs: snapshot,
    )
    monkeypatch.setattr(runner, "_validated_property_publication", validate)
    monkeypatch.setattr(
        runner,
        "verify_spatial_bundle",
        lambda *_args, **_kwargs: {"pass": True, "checks": {"binding_count": 5}},
    )

    evidence = runner._spatial_projection_evidence(
        {
            "EA_MANFRED_SPATIAL_RELEASE_ROOT": str(spatial_root),
            "EA_MANFRED_SPATIAL_HANDOFF_INCLUDED": "1",
            "EA_MANFRED_SPATIAL_SLUG": slug,
            "EA_MANFRED_SPATIAL_SHA256": spatial_digest,
            "EA_PUBLIC_APP_BASE_URL": "https://myexternalbrain.com",
        },
        projection_receipt=projection_receipt,
        release_root=release_root,
        release_id="release-a",
    )

    assert captured == [(final_path, browser_path)]
    assert evidence["included"] is True
    assert evidence["upstream_public_activation_authority"] is True
