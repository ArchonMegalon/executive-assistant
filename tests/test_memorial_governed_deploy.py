from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Mapping, Sequence

import pytest

from scripts import deploy_ea_memorial as deploy


SAFE_HTML = (
    "<!doctype html><html><body>Manfred – der Begleiter ist nicht Manfred "
    "und spricht nicht für ihn.</body></html>"
).encode("utf-8")
SAFE_MANIFEST = json.dumps(
    {
        "slug": "manfred",
        "intro": (
            "Der synthetische Gedenkbegleiter ist nicht Manfred und spricht nicht für ihn."
        ),
        "disclosure": "Neue Texte sind quellengebundene Einordnungen.",
    },
    ensure_ascii=False,
    separators=(",", ":"),
).encode("utf-8")
SAFE_TOUR = json.dumps(
    {"slug": "control-tour", "title": "Control tour"},
    separators=(",", ":"),
).encode("utf-8")


def _completed(
    args: Sequence[str],
    *,
    stdout: str = "",
    stderr: str = "",
    returncode: int = 0,
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(list(args), returncode, stdout, stderr)


class FakeRunner:
    def __init__(
        self,
        root: Path,
        *,
        authority_status: str = "pass",
        readiness_status: str = "pass",
        baseline_files: tuple[str, ...] = ("docker-compose.yml",),
        include_working_dir_label: bool = True,
        baseline_root: Path | None = None,
        redis_present: bool = True,
        redis_running: bool = True,
        redis_health: str = "healthy",
        redis_project: str = "ea",
        redis_service: str = "ea-redis",
        prior_image_reference: str = "ea-runtime:latest",
        branch: str = "release/manfred",
        upstream: str = "origin/main",
        candidate_status: str = "pass",
        candidate_websockets: int = 0,
        candidate_http_errors: int = 0,
    ) -> None:
        self.root = root
        self.baseline_root = baseline_root or root
        self.authority_status = authority_status
        self.readiness_status = readiness_status
        self.baseline_files = baseline_files
        self.include_working_dir_label = include_working_dir_label
        self.redis_present = redis_present
        self.redis_running = redis_running
        self.redis_health = redis_health
        self.redis_project = redis_project
        self.redis_service = redis_service
        self.calls: list[list[str]] = []
        self.call_envs: list[dict[str, str]] = []
        self.old_image = "sha256:" + "a" * 64
        self.candidate_image = "sha256:" + "c" * 64
        self.candidate_reference = f"ea-runtime:memorial-{'b' * 40}"
        self.prior_image_reference = prior_image_reference
        self.branch = branch
        self.upstream = upstream
        self.candidate_status = candidate_status
        self.candidate_websockets = candidate_websockets
        self.candidate_http_errors = candidate_http_errors
        self.image_refs = {
            self.prior_image_reference: self.old_image,
            self.candidate_reference: self.candidate_image,
        }
        self.api_mode = "prior"
        self.forward_files: list[str] = []
        self.forward_working_root = self.root
        self.forward_image_id = self.candidate_image
        self.forward_project = "ea"
        self.forward_service = "ea-api"
        self.forward_source_mounts = True
        self.rollback_mount_mismatch = False
        self.rollback_env_mismatch = False
        self.rollback_mode = False
        self.prior_openapi_paths = ["/health", "/memorials/{slug}", "/tours/{slug}"]
        self.forward_openapi_paths = list(self.prior_openapi_paths)
        self.prior_tour_json = SAFE_TOUR
        self.forward_tour_json = SAFE_TOUR
        self.rendered_candidate_reference = self.candidate_reference
        self.rendered_pull_policy = "never"
        self.rollback_render_environment: dict[str, str] = {}

    @staticmethod
    def _api_mounts(root: Path, *, memorial: bool) -> list[dict[str, object]]:
        mounts: list[dict[str, object]] = [
            {
                "Type": "bind",
                "Source": str(root / "ea" / "app"),
                "Destination": "/app/app",
                "RW": False,
            },
            {
                "Type": "bind",
                "Source": str(root / "scripts"),
                "Destination": "/app/scripts",
                "RW": False,
            },
        ]
        if memorial:
            mounts.append(
                {
                    "Type": "bind",
                    "Source": str(root / "memorial_data"),
                    "Destination": "/data/memorial_data",
                    "RW": False,
                }
            )
        return mounts

    def run(
        self,
        args: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        argv = [str(item) for item in args]
        self.calls.append(argv)
        self.call_envs.append(dict(env))
        stdout = ""
        stderr = ""
        returncode = 0
        if argv[:3] == ["docker", "compose", "version"]:
            stdout = "Docker Compose version v2"
        elif argv[:2] == ["docker-compose", "version"]:
            returncode = 1
        elif argv[:4] == ["git", "symbolic-ref", "--quiet", "--short"]:
            if self.branch:
                stdout = self.branch + "\n"
            else:
                returncode = 1
        elif argv[:3] == ["git", "rev-parse", "--abbrev-ref"]:
            if self.upstream:
                stdout = self.upstream + "\n"
            else:
                returncode = 1
        elif argv[:3] == ["git", "rev-parse", "HEAD"]:
            stdout = "b" * 40 + "\n"
        elif argv[:3] == ["docker", "image", "inspect"]:
            reference = argv[-1]
            image_id = self.image_refs.get(reference, self.candidate_image)
            stdout = json.dumps(
                [
                    {
                        "Id": image_id,
                        "Config": {
                            "Env": [],
                            "Cmd": ["uvicorn", "app.main:app"],
                            "Entrypoint": ["/usr/bin/tini", "--"],
                            "User": "10001:10001",
                        },
                    }
                ]
            )
        elif argv[:3] == ["docker", "image", "tag"]:
            source, destination = argv[-2:]
            self.image_refs[destination] = self.image_refs.get(source, source)
        elif argv[:2] == ["docker", "inspect"]:
            name = argv[-1]
            if name == "ea-redis" and not self.redis_present:
                returncode = 1
                stderr = "Error: No such object: ea-redis"
                result = _completed(
                    argv, stdout=stdout, stderr=stderr, returncode=returncode
                )
                return result
            forward = name == "ea-api" and self.api_mode == "forward"
            working_root = self.forward_working_root if forward else self.baseline_root
            config_files = (
                self.forward_files
                if forward
                else [str(self.baseline_root / item) for item in self.baseline_files]
            )
            project = (
                self.forward_project
                if forward
                else self.redis_project
                if name == "ea-redis"
                else "ea"
            )
            service = (
                self.forward_service
                if forward
                else self.redis_service
                if name == "ea-redis"
                else name
            )
            labels = {
                "com.docker.compose.project": project,
                "com.docker.compose.service": service,
                "com.docker.compose.project.config_files": ",".join(config_files),
            }
            if self.include_working_dir_label:
                labels["com.docker.compose.project.working_dir"] = str(working_root)
            running = self.redis_running if name == "ea-redis" else True
            health = self.redis_health if name == "ea-redis" else "healthy"
            image_id = self.forward_image_id if forward else self.old_image
            image_reference = (
                self.candidate_reference if forward else self.prior_image_reference
            )
            mounts = (
                self._api_mounts(working_root, memorial=forward)
                if name == "ea-api"
                else []
            )
            if forward and not self.forward_source_mounts:
                mounts = []
            if name == "ea-api" and self.rollback_mode and self.rollback_mount_mismatch:
                mounts.append(
                    {
                        "Type": "bind",
                        "Source": str(working_root / "unexpected"),
                        "Destination": "/unexpected",
                        "RW": False,
                    }
                )
            payload = {
                "Id": "container-" + name,
                "Created": "2026-07-13T00:00:00Z",
                "Image": image_id,
                "Config": {
                    "Image": image_reference,
                    "Labels": labels,
                    "Env": (
                        [f"EA_SOURCE_REVISION={'b' * 40}"]
                        if forward
                        else ["ROLLBACK_DRIFT=1"]
                        if self.rollback_mode and self.rollback_env_mismatch
                        else []
                    ),
                    "Cmd": ["uvicorn", "app.main:app"],
                    "Entrypoint": ["/usr/bin/tini", "--"],
                    "User": "10001:10001",
                },
                "State": {
                    "Running": running,
                    "Restarting": False,
                    "StartedAt": "2026-07-13T00:00:01Z",
                    "Health": {"Status": health},
                },
                "Mounts": mounts,
            }
            stdout = json.dumps([payload])
        elif argv[-2:] == ["config", "--services"]:
            stdout = "ea-db\nea-redis\nea-api\nea-worker\n"
        elif argv[-2:] == ["config", "--quiet"]:
            stdout = ""
        elif argv[-3:] == ["config", "--format", "json"]:
            memorial = (
                any(item.endswith("docker-compose.memorial.yml") for item in argv)
                and "EA_MEMORIAL_IMAGE" in env
            )
            if memorial:
                stdout = json.dumps(
                    {
                        "name": "ea",
                        "services": {
                            "ea-api": {
                                "image": self.rendered_candidate_reference,
                                "pull_policy": self.rendered_pull_policy,
                                "user": "10001:10001",
                                "group_add": [str(os.getgid())],
                                "volumes": [
                                    {
                                        "type": "bind",
                                        "source": str(self.root / "ea" / "app"),
                                        "target": "/app/app",
                                        "read_only": True,
                                    }
                                ],
                            }
                        },
                    }
                )
            else:
                stdout = json.dumps(
                    {
                        "name": "ea",
                        "services": {
                            "ea-api": {
                                "image": self.prior_image_reference,
                                "environment": self.rollback_render_environment,
                                "volumes": [
                                    {
                                        "type": "bind",
                                        "source": str(
                                            self.baseline_root / "ea" / "app"
                                        ),
                                        "target": "/app/app",
                                        "read_only": True,
                                    },
                                    {
                                        "type": "bind",
                                        "source": str(self.baseline_root / "scripts"),
                                        "target": "/app/scripts",
                                        "read_only": True,
                                    },
                                ],
                            }
                        },
                    }
                )
        elif argv[:3] == ["docker", "start", "ea-redis"]:
            self.redis_present = True
            self.redis_running = True
            self.redis_health = "healthy"
        elif "up" in argv and argv[-1] == "ea-redis":
            self.redis_present = True
            self.redis_running = True
            self.redis_health = "healthy"
        elif "up" in argv and argv[-1] == "ea-api":
            memorial = any(
                item.endswith("docker-compose.memorial.yml") for item in argv
            )
            self.api_mode = "forward" if memorial else "prior"
            self.rollback_mode = not memorial
            if memorial:
                self.forward_files = [
                    argv[index + 1]
                    for index, item in enumerate(argv[:-1])
                    if item == "-f"
                ]
        elif any(item.endswith("verify_release_authority.py") for item in argv):
            stdout = json.dumps(
                {
                    "contract_name": "ea.release_authority_gate.v1",
                    "status": self.authority_status,
                    "source_worktree_dirty": False,
                    "deployment_id": "memorial-release-001",
                    "project_mode": "MEMORIAL",
                    "public_origin": "https://memorial.example.org",
                }
            )
        elif any(item.endswith("verify_memorial_deploy_readiness.py") for item in argv):
            stdout = json.dumps(
                {
                    "contract_name": "ea.memorial_deploy_readiness.v1",
                    "status": self.readiness_status,
                }
            )
        elif any(
            item.endswith("materialize_memorial_operator_status.py") for item in argv
        ):
            stdout = json.dumps({"status": "blocked"})
        elif any(
            item.endswith("verify_manfred_memorial_candidate.py") for item in argv
        ):
            stdout = json.dumps(
                {
                    "schema": "ea.manfred_memorial_candidate_smoke.v1",
                    "status": self.candidate_status,
                    "checks": [
                        "source_grounded_narrator_boundary",
                        "voice_provider_boundary_blocked",
                        "browser_provider_websocket_boundary",
                    ],
                    "provider_calls_performed": False,
                    "page_get_performed": True,
                    "browser_audit": {
                        "status": "pass",
                        "automatic_provider_requests": 0,
                        "automatic_websockets": self.candidate_websockets,
                        "external_requests": 0,
                        "failed_requests": 0,
                        "page_errors": 0,
                        "http_errors": self.candidate_http_errors,
                    },
                }
            )
        elif any("materialize_" in Path(item).name for item in argv):
            stdout = json.dumps({"status": "pass"})
        result = _completed(argv, stdout=stdout, stderr=stderr, returncode=returncode)
        if check and returncode:
            raise deploy.DeployError(f"command_failed:{returncode}:{' '.join(argv)}")
        return result


@pytest.fixture()
def release_root(tmp_path: Path) -> Path:
    root = tmp_path / "release"
    root.mkdir()
    (root / ".env").write_text("EA_HOST_PORT=8090\n", encoding="utf-8")
    app = root / "ea" / "app"
    app.mkdir(parents=True)
    runner = app / "runner.py"
    runner.write_text("from __future__ import annotations\n", encoding="utf-8")
    runner.chmod(0o440)
    app.chmod(0o550)
    for filename in (
        "docker-compose.yml",
        "docker-compose.prod.yml",
        deploy.MEMORIAL_COMPOSE_FILE,
    ):
        (root / filename).write_text("services: {}\n", encoding="utf-8")
    return root


def _lane(
    root: Path,
    runner: FakeRunner,
    *,
    http_get=None,  # type: ignore[no-untyped-def]
    deployment_id: str = "memorial-release-001",
    receipt_dir: Path | None = None,
    global_lock_path: Path | None = None,
    control_tour_slug: str = "",
) -> deploy.MemorialDeployLane:
    def safe_http(url: str, timeout: float) -> deploy.HttpResponse:
        if url.endswith("/openapi.json"):
            paths = (
                runner.forward_openapi_paths
                if runner.api_mode == "forward"
                else runner.prior_openapi_paths
            )
            body = json.dumps(
                {"openapi": "3.1.0", "paths": {path: {} for path in paths}},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            return deploy.HttpResponse(200, "application/json", body, "b" * 40)
        if "/tours/" in url and url.endswith(".json"):
            body = (
                runner.forward_tour_json
                if runner.api_mode == "forward"
                else runner.prior_tour_json
            )
            return deploy.HttpResponse(200, "application/json", body, "b" * 40)
        if "/tours/" in url:
            return deploy.HttpResponse(
                200,
                "text/html; charset=utf-8",
                b"<!doctype html><html><body>Tour</body></html>",
                "b" * 40,
            )
        if url.endswith(".json"):
            return deploy.HttpResponse(200, "application/json", SAFE_MANIFEST, "b" * 40)
        if url.endswith("/health"):
            return deploy.HttpResponse(200, "application/json", b'{"status":"ok"}')
        return deploy.HttpResponse(200, "text/html; charset=utf-8", SAFE_HTML, "b" * 40)

    candidate_receipt = root / ".runtime" / "candidate-runtime-receipt.json"
    candidate_receipt.parent.mkdir(parents=True, exist_ok=True)
    candidate_receipt.write_text(
        json.dumps(
            {
                "schema": "ea.manfred_memorial_candidate_runtime.v3",
                "status": "pass",
                "image": runner.candidate_reference,
                "image_id": runner.candidate_image,
                "image_source_revision": "b" * 40,
                "image_locator_evidence": {
                    "locator": runner.candidate_reference,
                    "resolved_image_id": runner.candidate_image,
                    "revision_label": "b" * 40,
                    "locator_only": True,
                },
                "image_locator_only": True,
                "runtime_source_revision": "b" * 40,
                "runtime_revision_matches_image": True,
                "projection_commit": "b" * 40,
                "prepared_image_locator": runner.candidate_reference,
                "prepared_image_id": runner.candidate_image,
                "projection_tree_revalidated": True,
                "release_id": (root / "memorial_data").name,
                "release_root": str((root / "memorial_data").resolve()),
                "projection_sha256": "e" * 64,
                "compose_project": "ea-manfred-candidate-test0001",
                "compose_project_isolated": True,
                "compose_environment_bound_to_candidate_env": True,
                "candidate_named_resources": {
                    "containers": sorted(
                        [
                            f"ea-manfred-candidate-test0001-{service}-1"
                            for service in ("api", "gateway", "postgres", "redis")
                        ]
                        + [
                            f"ea-manfred-candidate-test0001_{service}_1"
                            for service in ("api", "gateway", "postgres", "redis")
                        ]
                    ),
                    "networks": [
                        "ea-manfred-candidate-test0001_backend",
                        "ea-manfred-candidate-test0001_ingress",
                    ],
                    "volumes": [
                        "ea-manfred-candidate-test0001_artifacts",
                        "ea-manfred-candidate-test0001_postgres_data",
                        "ea-manfred-candidate-test0001_redis_data",
                    ],
                },
                "candidate_preflight": {
                    "project": "ea-manfred-candidate-test0001",
                    "containers": 0,
                    "networks": 0,
                    "volumes": 0,
                    "named_container_collisions": [],
                    "named_network_collisions": [],
                    "named_volume_collisions": [],
                    "loopback_host": "127.0.0.1",
                    "loopback_port": 18090,
                    "loopback_port_free_before_start": True,
                },
                "locks": {
                    "project": {
                        "scope": "compose_project",
                        "project": "ea-manfred-candidate-test0001",
                        "held_through_candidate_proof": True,
                    },
                    "port": {
                        "scope": "host_loopback_port",
                        "port": 18090,
                        "held_through_candidate_proof": True,
                    },
                },
                "project_lock": {
                    "scope": "compose_project",
                    "project": "ea-manfred-candidate-test0001",
                    "held_through_candidate_proof": True,
                },
                "port_lock": {
                    "scope": "host_loopback_port",
                    "port": 18090,
                    "held_through_candidate_proof": True,
                },
                "candidate_container_images": {
                    "api": {
                        "container_id": "candidate-api-container",
                        "image_id": runner.candidate_image,
                    },
                    "gateway": {
                        "container_id": "candidate-gateway-container",
                        "image_id": runner.candidate_image,
                    },
                    "prepared_image_id": runner.candidate_image,
                    "revision_label": "b" * 40,
                    "all_match_prepared_image": True,
                },
                "candidate_api_container_id": "candidate-api-container",
                "candidate_port": 18090,
                "api_network_internal": True,
                "gateway_has_runtime_secrets": False,
                "provider_credentials_present": False,
                "provider_calls_performed": False,
                "openapi_contract": {
                    "live_before": {
                        "path_count": 3,
                        "operation_count": 5,
                        "schema_count": 2,
                        "security_scheme_count": 1,
                        "path_digest_sha256": "1" * 64,
                        "contract_digest_sha256": "3" * 64,
                    },
                    "candidate": {
                        "path_count": 4,
                        "operation_count": 6,
                        "schema_count": 3,
                        "security_scheme_count": 1,
                        "path_digest_sha256": "2" * 64,
                        "contract_digest_sha256": "4" * 64,
                    },
                    "live_after": {
                        "path_count": 3,
                        "operation_count": 5,
                        "schema_count": 2,
                        "security_scheme_count": 1,
                        "path_digest_sha256": "1" * 64,
                        "contract_digest_sha256": "3" * 64,
                    },
                    "candidate_preserves_live_contract": True,
                    "missing_or_changed_operation_count": 0,
                    "missing_or_changed_schema_count": 0,
                    "missing_or_changed_security_scheme_count": 0,
                },
                "live_ea_api_unchanged": True,
                "live_ea_api": {
                    "name": "ea-api",
                    "service": "ea-api",
                    "running": True,
                    "health": "healthy",
                },
                "live_ea_project_before": {
                    "project": "ea",
                    "containers": [
                        {
                            "name": "ea-api",
                            "service": "ea-api",
                            "running": True,
                            "health": "healthy",
                        }
                    ],
                    "networks": [],
                    "volumes": [],
                },
                "live_ea_project_after": {
                    "project": "ea",
                    "containers": [
                        {
                            "name": "ea-api",
                            "service": "ea-api",
                            "running": True,
                            "health": "healthy",
                        }
                    ],
                    "networks": [],
                    "volumes": [],
                },
                "live_ea_project_unchanged": True,
                "candidate_left_running_for_soak": True,
                "promotion_authority": False,
                "first_smoke_checks": [
                    "source_grounded_narrator_boundary",
                    "voice_provider_boundary_blocked",
                ],
                "second_smoke_checks": [
                    "source_grounded_narrator_boundary",
                    "voice_provider_boundary_blocked",
                ],
                "browser_surface": {
                    "status": "pass",
                    "automatic_provider_requests": 0,
                    "automatic_websockets": 0,
                    "external_requests": 0,
                    "failed_requests": 0,
                    "page_errors": 0,
                    "http_errors": 0,
                },
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    candidate_receipt.chmod(0o600)

    env = {
        "EA_DEPLOYMENT_ID": deployment_id,
        "EA_MEMORIAL_IMAGE": runner.candidate_reference,
        "EA_MEMORIAL_CANDIDATE_RECEIPT": str(candidate_receipt),
        "EA_MEMORIAL_DATA_HOST_PATH": str((root / "memorial_data").resolve()),
        "EA_MEMORIAL_PUBLIC_HOST_ALLOWLIST": "memorial.example.org",
    }
    if control_tour_slug:
        env["EA_MEMORIAL_CONTROL_TOUR_SLUG"] = control_tour_slug

    def selected_http(url: str, timeout: float) -> deploy.HttpResponse:
        if url.endswith("/openapi.json") or "/tours/" in url:
            return safe_http(url, timeout)
        return (http_get or safe_http)(url, timeout)

    return deploy.MemorialDeployLane(
        root=root,
        env=env,
        runner=runner,
        http_get=selected_http,
        sleep=lambda _: None,
        wait_seconds=0,
        receipt_dir=receipt_dir or root / ".runtime" / "test-receipts",
        global_lock_path=global_lock_path or root / ".runtime" / "test-global.lock",
        durable_root_check=lambda _root: None,
    )


@pytest.mark.parametrize(
    "value",
    ["", "local-20260713", "../escape", "has space", "bad;command", "ab"],
)
def test_explicit_deployment_id_fails_closed(value: str, tmp_path: Path) -> None:
    with pytest.raises(deploy.DeployError):
        deploy.MemorialDeployLane(
            root=tmp_path,
            env={"EA_DEPLOYMENT_ID": value},
            receipt_dir=tmp_path / "receipts",
        )


def test_global_lock_serializes_distinct_ids_and_receipt_roots(
    release_root: Path,
) -> None:
    global_lock = release_root / ".runtime" / "host-global.lock"
    first = _lane(
        release_root,
        FakeRunner(release_root),
        deployment_id="memorial-release-001",
        receipt_dir=release_root / ".runtime" / "receipts-a",
        global_lock_path=global_lock,
    )
    second = _lane(
        release_root,
        FakeRunner(release_root),
        deployment_id="memorial-release-002",
        receipt_dir=release_root / ".runtime" / "receipts-b",
        global_lock_path=global_lock,
    )

    first._acquire_lock()
    try:
        with pytest.raises(
            deploy.DeployError, match="memorial_api_deployment_already_running"
        ):
            second._acquire_lock()
    finally:
        first._release_lock()


def test_default_global_lock_is_host_stable_across_receipt_roots(
    release_root: Path,
) -> None:
    lane = deploy.MemorialDeployLane(
        root=release_root,
        env={
            "EA_DEPLOYMENT_ID": "memorial-release-001",
            "EA_MEMORIAL_IMAGE": f"ea-runtime:memorial-{'b' * 40}",
        },
        receipt_dir=release_root / "custom-receipts",
        durable_root_check=lambda _root: None,
    )

    assert lane.global_lock_path == Path("/run/lock/ea-memorial-ea-api.lock")
    assert release_root not in lane.global_lock_path.parents


def test_release_root_policy_rejects_temporary_paths_and_accepts_workspace(
    release_root: Path,
) -> None:
    with pytest.raises(deploy.DeployError, match="release_root_not_durable"):
        deploy._require_durable_release_root(release_root)
    deploy._require_durable_release_root(deploy.ROOT)


@pytest.mark.parametrize(
    ("branch", "upstream", "reason"),
    [
        ("", "origin/main", "release_branch_detached"),
        ("release/manfred", "", "release_branch_upstream_missing"),
    ],
)
def test_release_source_requires_attached_branch_and_upstream(
    release_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    branch: str,
    upstream: str,
    reason: str,
) -> None:
    runner = FakeRunner(release_root, branch=branch, upstream=upstream)
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )

    with pytest.raises(deploy.DeployError, match=reason):
        _lane(release_root, runner).deploy(preflight_only=True)

    assert not any("up" in call for call in runner.calls)


@pytest.mark.parametrize(
    ("origin", "hosts", "reason"),
    [
        (
            "http://myexternalbrain.com",
            ["myexternalbrain.com"],
            "public_origin_invalid",
        ),
        (
            "https://unapproved.example.org",
            ["myexternalbrain.com"],
            "public_origin_host_not_approved",
        ),
        (
            "https://myexternalbrain.com:not-a-port",
            ["myexternalbrain.com"],
            "public_origin_invalid",
        ),
    ],
)
def test_public_origin_requires_https_and_approved_exact_host(
    origin: str, hosts: list[str], reason: str
) -> None:
    with pytest.raises(deploy.DeployError, match=reason):
        deploy._validate_public_origin(origin, allowed_hosts=hosts)

    assert (
        deploy._validate_public_origin(
            "https://www.myexternalbrain.com",
            allowed_hosts=deploy.DEFAULT_PUBLIC_HOSTS,
        )
        == "https://www.myexternalbrain.com"
    )


@pytest.mark.parametrize(
    ("image_reference", "reason"),
    [
        ("", "explicit_memorial_image_required"),
        ("ea-runtime:latest", "memorial_image_not_revision_bound"),
        ("https://registry.invalid/image:tag", "memorial_image_reference_invalid"),
    ],
)
def test_candidate_image_must_be_explicit_safe_and_revision_bound(
    release_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    image_reference: str,
    reason: str,
) -> None:
    runner = FakeRunner(release_root)
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    lane = _lane(release_root, runner)
    lane.memorial_image_reference = image_reference

    with pytest.raises(deploy.DeployError, match=reason):
        lane.deploy(preflight_only=True)

    assert not any("up" in call for call in runner.calls)


@pytest.mark.parametrize(
    ("attribute", "value", "reason"),
    [
        (
            "rendered_candidate_reference",
            "ea-runtime:wrong-candidate",
            "memorial_compose_candidate_image_mismatch",
        ),
        (
            "rendered_pull_policy",
            "missing",
            "memorial_compose_pull_policy_invalid",
        ),
    ],
)
def test_rendered_compose_requires_exact_candidate_and_never_pull(
    release_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    attribute: str,
    value: str,
    reason: str,
) -> None:
    runner = FakeRunner(release_root)
    setattr(runner, attribute, value)
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )

    with pytest.raises(deploy.DeployError, match=reason):
        _lane(release_root, runner).deploy(preflight_only=True)

    assert not any("up" in call for call in runner.calls)


def test_rollback_render_environment_drift_fails_before_mutation(
    release_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner(release_root)
    runner.rollback_render_environment = {"DRIFTED_VALUE": "changed"}
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )

    with pytest.raises(
        deploy.DeployError,
        match="rollback_render_environment_identity_mismatch",
    ):
        _lane(release_root, runner).deploy(preflight_only=True)

    assert not any("up" in call for call in runner.calls)


def test_release_authority_failure_stops_before_compose_mutation(
    release_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner(release_root, authority_status="fail")
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    lane = _lane(release_root, runner)

    with pytest.raises(deploy.DeployError, match="release_authority_not_pass"):
        lane.deploy(preflight_only=True)

    mutating = [
        call for call in runner.calls if "up" in call or "force-recreate" in call
    ]
    assert mutating == []


def test_memorial_readiness_failure_stops_before_compose_mutation(
    release_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner(release_root, readiness_status="fail")
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    lane = _lane(release_root, runner)

    with pytest.raises(deploy.DeployError, match="memorial_deploy_readiness_not_pass"):
        lane.deploy(preflight_only=True)

    assert not any("up" in call for call in runner.calls)


def test_dirty_source_fails_before_evidence_or_docker_mutation(
    release_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner(release_root)
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {
            "source_worktree_dirty": True,
            "source_dirty_files": ["ea/app/example.py"],
        },
    )
    lane = _lane(release_root, runner)

    with pytest.raises(deploy.DeployError, match="source_worktree_dirty"):
        lane.deploy(preflight_only=True)

    assert not any("materialize_" in " ".join(call) for call in runner.calls)
    assert not any("up" in call for call in runner.calls)


def test_happy_path_mutates_only_redis_and_api(
    release_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner(release_root)
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    lane = _lane(release_root, runner)

    receipt = lane.deploy()

    assert receipt["status"] == "pass"
    up_calls = [call for call in runner.calls if "up" in call]
    assert len(up_calls) == 1
    assert up_calls[0][-1] == "ea-api"
    assert "--no-deps" in up_calls[0]
    assert "--force-recreate" in up_calls[0]
    assert "docker-compose.memorial.yml" in " ".join(up_calls[0])
    assert "docker-compose.prod.yml" not in " ".join(up_calls[0])
    assert receipt["target_compose_files"] == [
        "docker-compose.yml",
        "docker-compose.memorial.yml",
    ]
    assert receipt["source_revision"] == "b" * 40
    assert receipt["candidate_image"] == {
        "reference": runner.candidate_reference,
        "image_id": runner.candidate_image,
    }
    memorial_probes = [
        probe for probe in receipt["probes"] if "/memorials/manfred" in probe["url"]
    ]
    assert len(memorial_probes) == 4
    assert {probe["source_revision"] for probe in memorial_probes} == {"b" * 40}
    config_index = next(
        index
        for index, call in enumerate(runner.calls)
        if call[-2:] == ["config", "--quiet"]
    )
    assert runner.call_envs[config_index]["EA_SOURCE_REVISION"] == "b" * 40
    assert (
        runner.call_envs[config_index]["EA_MEMORIAL_IMAGE"]
        == runner.candidate_reference
    )
    rendered_config_calls = [
        call
        for call in runner.calls
        if call[-3:] == ["config", "--format", "json"]
        and "docker-compose.memorial.yml" in " ".join(call)
    ]
    assert len(rendered_config_calls) == 3
    revalidation_checks = [
        check
        for check in receipt["checks"]
        if check["name"] == "bind_source_access_revalidation"
    ]
    assert [check["boundary"] for check in revalidation_checks] == [
        "before_ensure_redis",
        "before_recreate_api",
    ]
    assert any(
        call[:2] == ["docker", "inspect"] and call[-1] == "ea-redis"
        for call in runner.calls
    )
    assert not any("build" in call for call in runner.calls)
    forbidden = {
        "ea-worker",
        "ea-scheduler",
        "ea-teable-relay",
        "ea-db",
        "ea-cloudflared",
    }
    assert not any(forbidden.intersection(call[-1:]) for call in up_calls)
    candidate_calls = [
        call
        for call in runner.calls
        if any(item.endswith("verify_manfred_memorial_candidate.py") for item in call)
    ]
    assert len(candidate_calls) == 2
    assert all("--browser-audit" in call for call in candidate_calls)
    assert "http://127.0.0.1:8090" in candidate_calls[0]
    assert "https://memorial.example.org" in candidate_calls[1]
    assert {item["origin"] for item in receipt["candidate_verifier"]} == {
        "local",
        "public",
    }
    assert all("base_url" not in item for item in receipt["candidate_verifier"])
    previous = receipt["previous_api"]
    assert "mount_identities" not in previous
    assert "mounts" not in previous
    assert len(previous["mount_identity_sha256"]) == 64
    rollback_render = receipt["rollback_render_preflight"]
    assert rollback_render["status"] == "pass"
    assert rollback_render["environment_sha256"] == previous["environment_sha256"]
    assert rollback_render["process_config_sha256"] == previous["process_config_sha256"]
    prior_render_index = next(
        index
        for index, call in enumerate(runner.calls)
        if call[-3:] == ["config", "--format", "json"]
        and "docker-compose.memorial.yml" not in " ".join(call)
    )
    assert not deploy.FORWARD_ONLY_ENV_KEYS.intersection(
        runner.call_envs[prior_render_index]
    )
    promotion = receipt["candidate_promotion_evidence"]
    assert promotion["path"] == lane.candidate_receipt_value
    assert len(promotion["sha256"]) == 64
    assert promotion["schema"] == "ea.manfred_memorial_candidate_runtime.v3"
    assert len(promotion["projection"]["projection_sha256"]) == 64
    assert len(promotion["live_ea"]["snapshot_sha256"]) == 64
    assert promotion["openapi"]["candidate_preserves_live_contract"] is True
    assert promotion["browser"]["http_errors"] == 0
    assert "first_smoke_checks" not in promotion
    assert "second_smoke_checks" not in promotion
    assert "browser_surface" not in promotion
    assert "candidate_api_container_id" not in promotion
    assert "live_ea_project_before" not in promotion
    assert "live_ea_project_after" not in promotion
    predeploy_openapi = receipt["predeploy_non_memorial_controls"]["openapi"]
    postdeploy_openapi = receipt["postdeploy_non_memorial_controls"]["openapi"]
    assert predeploy_openapi["paths"] == sorted(runner.prior_openapi_paths)
    assert postdeploy_openapi["path_count"] == predeploy_openapi["path_count"]
    assert postdeploy_openapi["added_path_count"] == 0


def test_candidate_promotion_receipt_is_explicit_private_and_non_symlink(
    release_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner(release_root)
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )

    missing = _lane(
        release_root,
        runner,
        deployment_id="memorial-release-missing-candidate",
    )
    missing.candidate_receipt_value = ""
    with pytest.raises(
        deploy.DeployError, match="explicit_memorial_candidate_receipt_required"
    ):
        missing.deploy(preflight_only=True)

    insecure = _lane(
        release_root,
        runner,
        deployment_id="memorial-release-insecure-candidate",
    )
    Path(insecure.candidate_receipt_value).chmod(0o644)
    with pytest.raises(
        deploy.DeployError,
        match="memorial_candidate_receipt_permissions_invalid",
    ):
        insecure.deploy(preflight_only=True)

    symlinked = _lane(
        release_root,
        runner,
        deployment_id="memorial-release-symlink-candidate",
    )
    target = Path(symlinked.candidate_receipt_value)
    link = target.with_name("candidate-runtime-link.json")
    link.symlink_to(target)
    symlinked.candidate_receipt_value = str(link)
    with pytest.raises(
        deploy.DeployError, match="memorial_candidate_receipt_path_invalid"
    ):
        symlinked.deploy(preflight_only=True)

    hardlinked = _lane(
        release_root,
        runner,
        deployment_id="memorial-release-hardlink-candidate",
    )
    original = Path(hardlinked.candidate_receipt_value)
    hardlink = original.with_name("candidate-runtime-hardlink.json")
    hardlink.hardlink_to(original)
    hardlinked.candidate_receipt_value = str(hardlink)
    with pytest.raises(
        deploy.DeployError,
        match="memorial_candidate_receipt_permissions_invalid",
    ):
        hardlinked.deploy(preflight_only=True)

    assert not any("up" in call for call in runner.calls)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("image_id", "sha256:" + "d" * 64),
        ("schema", "ea.manfred_memorial_candidate_runtime.v2"),
        ("runtime_source_revision", "a" * 40),
        ("image_locator_only", False),
        ("image_locator_evidence", {}),
        ("projection_commit", "a" * 40),
        ("prepared_image_id", "sha256:" + "d" * 64),
        ("projection_sha256", "not-a-digest"),
        ("compose_project_isolated", False),
        ("candidate_preflight.containers", 1),
        ("projection_tree_revalidated", False),
        ("locks", {}),
        ("project_lock", {}),
        ("port_lock", {}),
        ("candidate_container_images", {}),
        ("candidate_api_container_id", "different-container"),
        ("openapi_contract.candidate_preserves_live_contract", False),
        ("live_ea_project_after", {}),
        ("live_ea_api_unchanged", False),
        ("provider_calls_performed", True),
        ("release_root", "/different/memorial-data"),
        ("browser_surface.http_errors", 1),
        ("browser_surface.failed_requests", None),
    ],
)
def test_candidate_promotion_receipt_contract_mismatch_fails_before_mutation(
    release_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
) -> None:
    runner = FakeRunner(release_root)
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    lane = _lane(release_root, runner)
    path = Path(lane.candidate_receipt_value)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if "." in field:
        parent, child = field.split(".", 1)
        if value is None:
            payload[parent].pop(child)
        else:
            payload[parent][child] = value
    else:
        payload[field] = value
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    path.chmod(0o600)

    with pytest.raises(
        deploy.DeployError, match="memorial_candidate_receipt_contract_invalid"
    ):
        lane.deploy(preflight_only=True)

    assert not any("up" in call for call in runner.calls)


def test_candidate_openapi_evidence_rejects_extra_unbounded_fields(
    release_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner(release_root)
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    lane = _lane(release_root, runner)
    path = Path(lane.candidate_receipt_value)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["openapi_contract"]["live_before"]["raw_contract"] = {
        "unexpected": "content"
    }
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    path.chmod(0o600)

    with pytest.raises(
        deploy.DeployError, match="memorial_candidate_receipt_contract_invalid"
    ):
        lane.deploy(preflight_only=True)

    assert not any("up" in call for call in runner.calls)


def test_openapi_path_regression_rolls_back(
    release_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner(release_root)
    runner.forward_openapi_paths = ["/health", "/memorials/{slug}"]
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    lane = _lane(release_root, runner)

    with pytest.raises(deploy.DeployError, match="deployment_failed_rolled_back"):
        lane.deploy()

    receipt = json.loads(lane.receipt_path.read_text(encoding="utf-8"))
    assert "postdeploy_openapi_path_regression" in receipt["failure"]["reason"]
    assert receipt["rollback"]["status"] == "pass"


def test_optional_tour_control_survives_unchanged(
    release_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner(release_root)
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )

    receipt = _lane(
        release_root,
        runner,
        control_tour_slug="control-tour",
    ).deploy()

    before = receipt["predeploy_non_memorial_controls"]["tour"]
    after = receipt["postdeploy_non_memorial_controls"]["tour"]
    assert before["slug"] == "control-tour"
    assert before["json"]["body_sha256"] == after["json"]["body_sha256"]
    assert before["html"]["status_code"] == after["html"]["status_code"] == 200


def test_optional_tour_json_drift_rolls_back(
    release_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner(release_root)
    runner.forward_tour_json = b'{"slug":"control-tour","title":"changed"}'
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    lane = _lane(
        release_root,
        runner,
        control_tour_slug="control-tour",
    )

    with pytest.raises(deploy.DeployError, match="deployment_failed_rolled_back"):
        lane.deploy()

    receipt = json.loads(lane.receipt_path.read_text(encoding="utf-8"))
    assert "postdeploy_control_tour_json_changed" in receipt["failure"]["reason"]
    assert receipt["rollback"]["status"] == "pass"


@pytest.mark.parametrize(
    ("attribute", "value", "reason"),
    [
        ("forward_image_id", "sha256:" + "d" * 64, "deployed_api_image_mismatch"),
        ("forward_project", "other", "deployed_api_project_mismatch"),
        ("forward_service", "other-api", "deployed_api_service_mismatch"),
        ("forward_source_mounts", False, "deployed_api_source_mounts_mismatch"),
    ],
)
def test_forward_api_identity_mismatch_rolls_back(
    release_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    attribute: str,
    value: object,
    reason: str,
) -> None:
    runner = FakeRunner(release_root)
    setattr(runner, attribute, value)
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    lane = _lane(release_root, runner)

    with pytest.raises(deploy.DeployError, match="deployment_failed_rolled_back"):
        lane.deploy()

    receipt = json.loads(lane.receipt_path.read_text(encoding="utf-8"))
    assert reason in receipt["failure"]["reason"]
    assert receipt["rollback"]["status"] == "pass"


def test_missing_redis_is_created_without_touching_other_dependencies(
    release_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner(release_root, redis_present=False)
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )

    receipt = _lane(release_root, runner).deploy()

    up_calls = [call for call in runner.calls if "up" in call]
    assert [call[-1] for call in up_calls] == ["ea-redis", "ea-api"]
    assert receipt["status"] == "pass"


def test_stopped_redis_is_started_without_compose_reconfiguration(
    release_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner(release_root, redis_running=False, redis_health="unhealthy")
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )

    _lane(release_root, runner).deploy()

    assert ["docker", "start", "ea-redis"] in runner.calls
    assert not any("up" in call and call[-1] == "ea-redis" for call in runner.calls)


def test_running_unhealthy_redis_is_never_reconfigured(
    release_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner(release_root, redis_health="unhealthy")
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )

    with pytest.raises(deploy.DeployError, match="container_not_ready:ea-redis"):
        _lane(release_root, runner).deploy()

    assert not any("up" in call for call in runner.calls)
    assert ["docker", "start", "ea-redis"] not in runner.calls


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"redis_project": "other"}, "redis_project_mismatch"),
        ({"redis_service": "other-redis"}, "redis_service_mismatch"),
    ],
)
def test_existing_redis_requires_exact_compose_identity_before_trust_or_start(
    release_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    kwargs: dict[str, str],
    reason: str,
) -> None:
    runner = FakeRunner(release_root, **kwargs)
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )

    with pytest.raises(deploy.DeployError, match=reason):
        _lane(release_root, runner).deploy()

    assert not any("up" in call for call in runner.calls)
    assert ["docker", "start", "ea-redis"] not in runner.calls


def test_unrestorable_baseline_fails_before_redis_or_api_mutation(
    release_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner(release_root, baseline_files=())
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    lane = _lane(release_root, runner)

    with pytest.raises(
        deploy.DeployError, match="prior_api_compose_config_files_missing"
    ):
        lane.deploy(preflight_only=True)

    assert not any("up" in call for call in runner.calls)


def test_missing_baseline_working_dir_fails_before_mutation(
    release_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner(release_root, include_working_dir_label=False)
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    lane = _lane(release_root, runner)

    with pytest.raises(
        deploy.DeployError, match="prior_api_compose_working_dir_missing"
    ):
        lane.deploy(preflight_only=True)

    assert not any("up" in call for call in runner.calls)


def test_forward_topology_rebases_ordered_baseline_layers_into_release_root(
    release_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prior_root = tmp_path / "prior-live"
    prior_root.mkdir()
    (prior_root / ".env").write_text("EA_HOST_PORT=8090\n", encoding="utf-8")
    for filename in ("docker-compose.yml", "docker-compose.prod.yml"):
        (prior_root / filename).write_text("services: {}\n", encoding="utf-8")
    runner = FakeRunner(
        release_root,
        baseline_root=prior_root,
        baseline_files=("docker-compose.yml", "docker-compose.prod.yml"),
    )
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )

    receipt = _lane(release_root, runner).deploy(preflight_only=True)

    assert receipt["target_compose_files"] == [
        "docker-compose.yml",
        "docker-compose.prod.yml",
        "docker-compose.memorial.yml",
    ]
    config_call = [call for call in runner.calls if call[-2:] == ["config", "--quiet"]][
        0
    ]
    assert str(release_root / "docker-compose.yml") in config_call
    assert str(release_root / "docker-compose.prod.yml") in config_call
    assert str(prior_root / "docker-compose.yml") not in config_call
    assert receipt["rollback_compose_files"] == [
        str(prior_root / "docker-compose.yml"),
        str(prior_root / "docker-compose.prod.yml"),
    ]


def test_existing_memorial_baseline_is_rejected_before_mutation(
    release_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner(
        release_root,
        baseline_files=("docker-compose.yml", "docker-compose.memorial.yml"),
    )
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )

    with pytest.raises(
        deploy.DeployError, match="forward_baseline_already_contains_memorial"
    ):
        _lane(release_root, runner).deploy(preflight_only=True)

    assert not any("up" in call for call in runner.calls)


def test_baseline_layer_outside_prior_working_dir_is_rejected(
    release_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prior_root = tmp_path / "prior-live"
    prior_root.mkdir()
    (prior_root / ".env").write_text("EA_HOST_PORT=8090\n", encoding="utf-8")
    external_file = tmp_path / "external-compose.yml"
    external_file.write_text("services: {}\n", encoding="utf-8")
    runner = FakeRunner(
        release_root,
        baseline_root=prior_root,
        baseline_files=(str(external_file),),
    )
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )

    with pytest.raises(
        deploy.DeployError, match="forward_baseline_compose_file_unmappable"
    ):
        _lane(release_root, runner).deploy(preflight_only=True)

    assert not any("up" in call for call in runner.calls)


@pytest.mark.parametrize(
    "reference",
    ["sha256:" + "a" * 64, "registry.example.org/ea@sha256:" + "a" * 64],
)
def test_unrestorable_prior_image_reference_fails_before_mutation(
    release_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    reference: str,
) -> None:
    runner = FakeRunner(release_root, prior_image_reference=reference)
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )

    with pytest.raises(
        deploy.DeployError, match="prior_api_image_reference_unrestorable"
    ):
        _lane(release_root, runner).deploy(preflight_only=True)

    assert not any("up" in call for call in runner.calls)


def test_public_failure_rolls_back_once_with_base_and_prod_only(
    release_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner(
        release_root,
        baseline_files=("docker-compose.yml", "docker-compose.prod.yml"),
    )
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )

    def failing_public_http(url: str, timeout: float) -> deploy.HttpResponse:
        if url.startswith("https://") and not url.endswith(".json"):
            raise deploy.DeployError("http_status_invalid:404")
        if url.endswith(".json"):
            return deploy.HttpResponse(200, "application/json", SAFE_MANIFEST, "b" * 40)
        if url.endswith("/health"):
            return deploy.HttpResponse(200, "application/json", b'{"status":"ok"}')
        return deploy.HttpResponse(200, "text/html", SAFE_HTML, "b" * 40)

    lane = _lane(release_root, runner, http_get=failing_public_http)

    with pytest.raises(deploy.DeployError, match="deployment_failed_rolled_back"):
        lane.deploy()

    api_up_calls = [
        call for call in runner.calls if "up" in call and call[-1] == "ea-api"
    ]
    assert len(api_up_calls) == 2
    forward, rollback = api_up_calls
    assert "docker-compose.memorial.yml" in " ".join(forward)
    assert "docker-compose.memorial.yml" not in " ".join(rollback)
    assert "docker-compose.yml" in " ".join(rollback)
    assert "docker-compose.prod.yml" in " ".join(rollback)
    payload = json.loads(lane.receipt_path.read_text(encoding="utf-8"))
    assert payload["status"] == "failed_rolled_back"
    assert payload["rollback"]["status"] == "pass"
    rollback_index = runner.calls.index(rollback)
    assert not deploy.FORWARD_ONLY_ENV_KEYS.intersection(
        runner.call_envs[rollback_index]
    )
    assert [
        "docker",
        "image",
        "tag",
        runner.old_image,
        runner.prior_image_reference,
    ] in runner.calls
    assert payload["failure"]["reason"].startswith("http_probe_exhausted:")


def test_rollback_mount_mismatch_preserves_primary_and_rollback_failures(
    release_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner(release_root)
    runner.rollback_mount_mismatch = True
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )

    def failing_public_http(url: str, timeout: float) -> deploy.HttpResponse:
        if url.startswith("https://") and not url.endswith(".json"):
            raise deploy.DeployError("http_status_invalid:404")
        if url.endswith(".json"):
            return deploy.HttpResponse(200, "application/json", SAFE_MANIFEST, "b" * 40)
        if url.endswith("/health"):
            return deploy.HttpResponse(200, "application/json", b'{"status":"ok"}')
        return deploy.HttpResponse(200, "text/html", SAFE_HTML, "b" * 40)

    lane = _lane(release_root, runner, http_get=failing_public_http)

    with pytest.raises(deploy.DeployError, match="deployment_and_rollback_failed"):
        lane.deploy()

    receipt = json.loads(lane.receipt_path.read_text(encoding="utf-8"))
    assert receipt["status"] == "rollback_failed"
    assert receipt["failure"]["reason"].startswith("http_probe_exhausted:")
    assert receipt["rollback"]["reason"] == "rollback_mount_identity_mismatch"


def test_rollback_environment_drift_preserves_primary_and_rollback_failures(
    release_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner(release_root)
    runner.rollback_env_mismatch = True
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )

    def failing_public_http(url: str, timeout: float) -> deploy.HttpResponse:
        if url.startswith("https://") and not url.endswith(".json"):
            raise deploy.DeployError("http_status_invalid:404")
        if url.endswith("/openapi.json"):
            return deploy.HttpResponse(
                200,
                "application/json",
                b'{"paths":{"/health":{}}}',
            )
        if url.endswith(".json"):
            return deploy.HttpResponse(200, "application/json", SAFE_MANIFEST, "b" * 40)
        if url.endswith("/health"):
            return deploy.HttpResponse(200, "application/json", b'{"status":"ok"}')
        return deploy.HttpResponse(200, "text/html", SAFE_HTML, "b" * 40)

    lane = _lane(release_root, runner, http_get=failing_public_http)

    with pytest.raises(deploy.DeployError, match="deployment_and_rollback_failed"):
        lane.deploy()

    receipt = json.loads(lane.receipt_path.read_text(encoding="utf-8"))
    assert receipt["failure"]["reason"].startswith("http_probe_exhausted:")
    assert receipt["rollback"]["reason"] == "rollback_environment_identity_mismatch"


def test_rollback_replays_exact_captured_baseline_compose_files(
    release_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner(release_root, baseline_files=("docker-compose.yml",))
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )

    def failing_public_http(url: str, timeout: float) -> deploy.HttpResponse:
        if url.startswith("https://") and not url.endswith(".json"):
            raise deploy.DeployError("http_status_invalid:404")
        if url.endswith(".json"):
            return deploy.HttpResponse(200, "application/json", SAFE_MANIFEST, "b" * 40)
        if url.endswith("/health"):
            return deploy.HttpResponse(200, "application/json", b'{"status":"ok"}')
        return deploy.HttpResponse(200, "text/html", SAFE_HTML, "b" * 40)

    lane = _lane(release_root, runner, http_get=failing_public_http)
    with pytest.raises(deploy.DeployError, match="deployment_failed_rolled_back"):
        lane.deploy()

    rollback = [
        call
        for call in runner.calls
        if "up" in call
        and call[-1] == "ea-api"
        and "docker-compose.memorial.yml" not in " ".join(call)
    ][0]
    assert str(release_root / "docker-compose.yml") in rollback
    assert str(release_root / "docker-compose.prod.yml") not in rollback
    receipt = json.loads(lane.receipt_path.read_text(encoding="utf-8"))
    assert receipt["rollback"]["compose_config_files"] == [
        str(release_root / "docker-compose.yml")
    ]


def test_memorial_surface_requires_transparent_narrator_markers(
    release_root: Path,
) -> None:
    runner = FakeRunner(release_root)

    def unsafe_http(url: str, timeout: float) -> deploy.HttpResponse:
        return deploy.HttpResponse(200, "text/html", b"<html>Ich bin Manfred</html>")

    lane = _lane(release_root, runner, http_get=unsafe_http)

    with pytest.raises(deploy.DeployError, match="http_probe_exhausted"):
        lane._wait_http("https://memorial.example.org/memorials/manfred", kind="html")


def test_public_manifest_must_match_local_manifest(release_root: Path) -> None:
    runner = FakeRunner(release_root)

    def divergent_http(url: str, timeout: float) -> deploy.HttpResponse:
        if url.endswith("/health"):
            return deploy.HttpResponse(200, "application/json", b'{"status":"ok"}')
        if url.endswith(".json"):
            body = SAFE_MANIFEST
            if url.startswith("https://"):
                body = SAFE_MANIFEST + b" "
            return deploy.HttpResponse(200, "application/json", body, "b" * 40)
        return deploy.HttpResponse(200, "text/html", SAFE_HTML, "b" * 40)

    lane = _lane(release_root, runner, http_get=divergent_http)

    with pytest.raises(
        deploy.DeployError, match="public_memorial_manifest_differs_from_local"
    ):
        lane._verify_deployed_surface(
            "https://memorial.example.org", source_revision="b" * 40
        )


def test_memorial_probe_rejects_stale_runtime_source_revision(
    release_root: Path,
) -> None:
    runner = FakeRunner(release_root)

    def stale_http(url: str, timeout: float) -> deploy.HttpResponse:
        if url.endswith("/health"):
            return deploy.HttpResponse(200, "application/json", b'{"status":"ok"}')
        if url.endswith(".json"):
            return deploy.HttpResponse(200, "application/json", SAFE_MANIFEST, "a" * 40)
        return deploy.HttpResponse(200, "text/html", SAFE_HTML, "a" * 40)

    lane = _lane(release_root, runner, http_get=stale_http)

    with pytest.raises(deploy.DeployError, match="source_revision_mismatch"):
        lane._verify_deployed_surface(
            "https://memorial.example.org", source_revision="b" * 40
        )


@pytest.mark.parametrize(
    "runner_kwargs",
    [
        {"candidate_websockets": 1},
        {"candidate_http_errors": 1},
    ],
)
def test_candidate_browser_or_provider_boundary_failure_rolls_back(
    release_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    runner_kwargs: dict[str, int],
) -> None:
    runner = FakeRunner(release_root, **runner_kwargs)
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    lane = _lane(release_root, runner)

    with pytest.raises(deploy.DeployError, match="deployment_failed_rolled_back"):
        lane.deploy()

    candidate_calls = [
        call
        for call in runner.calls
        if any(item.endswith("verify_manfred_memorial_candidate.py") for item in call)
    ]
    assert candidate_calls
    assert all("--browser-audit" in call for call in candidate_calls)
    assert all("--submit-contribution-receipt" not in call for call in candidate_calls)
    assert all(
        "--withdraw-contribution-receipt" not in call for call in candidate_calls
    )
    receipt = json.loads(lane.receipt_path.read_text(encoding="utf-8"))
    assert "candidate_verifier_contract_failed" in receipt["failure"]["reason"]
    assert receipt["rollback"]["status"] == "pass"


def test_candidate_verifier_browser_flag_is_explicit() -> None:
    from scripts import verify_manfred_memorial_candidate as candidate

    args = candidate.build_parser().parse_args(
        [
            "--base-url",
            "https://myexternalbrain.com",
            "--public-origin",
            "https://myexternalbrain.com",
            "--browser-audit",
        ]
    )

    assert args.browser_audit is True


def test_subprocess_failure_never_exposes_output_or_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "super-secret-token"

    def failed_run(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        return _completed(
            ["docker", "compose", "config"],
            stdout=f"stdout:{secret}",
            stderr=f"stderr:{secret}",
            returncode=9,
        )

    monkeypatch.setattr(subprocess, "run", failed_run)

    with pytest.raises(deploy.DeployError) as raised:
        deploy.SubprocessRunner().run(
            ["docker", "compose", "config"],
            cwd=tmp_path,
            env={"TOKEN": secret},
        )

    message = str(raised.value)
    assert message == "command_failed:9:docker"
    assert secret not in message
    assert "stdout" not in message
    assert "stderr" not in message


def test_receipt_is_private_and_deployment_id_cannot_be_reused(
    release_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner(release_root)
    monkeypatch.setattr(
        deploy,
        "source_worktree_metadata",
        lambda *_args, **_kwargs: {"source_worktree_dirty": False},
    )
    lane = _lane(release_root, runner)
    lane.deploy(preflight_only=True)

    assert lane.receipt_path.stat().st_mode & 0o777 == 0o600
    duplicate = _lane(release_root, FakeRunner(release_root))
    with pytest.raises(deploy.DeployError, match="deployment_receipt_already_exists"):
        duplicate.deploy(preflight_only=True)


def test_make_target_uses_scoped_lane_not_generic_deployer() -> None:
    makefile = (deploy.ROOT / "Makefile").read_text(encoding="utf-8")
    target = makefile.split("deploy-ea-memorial:", 1)[1].split("\n\n", 1)[0]
    scoped = makefile.split("deploy-ea-memorial-scoped:\n", 1)[1].split("\n\n", 1)[0]

    assert "deploy-ea-memorial-scoped" in target
    assert "scripts/deploy_ea_memorial.py" in scoped
    assert "EA_MEMORIAL_IMAGE" in scoped
    assert "EA_MEMORIAL_CANDIDATE_RECEIPT" in scoped
    assert "scripts/deploy.sh" not in target + scoped


def test_memorial_compose_override_is_api_only() -> None:
    raw = (deploy.ROOT / "docker-compose.memorial.yml").read_text(encoding="utf-8")
    assert raw.startswith("services:\n  ea-api:\n")
    assert "image: ${EA_MEMORIAL_IMAGE:?" in raw
    assert "pull_policy: never" in raw
    assert "EA_SOURCE_REVISION=${EA_SOURCE_REVISION:?" in raw
    assert "\n  ea-worker:" not in raw
    assert "\n  ea-scheduler:" not in raw
