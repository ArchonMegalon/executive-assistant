from __future__ import annotations

import json
import stat
import subprocess
import urllib.parse
from pathlib import Path
from typing import Callable, Mapping, Sequence

import pytest

from scripts import reconcile_ea_public_ingress as ingress


SOURCE_REVISION = "a" * 40
IMAGE_ID = "sha256:" + "b" * 64
NETWORK_ID = "c" * 64
PROPERTY_NETWORK_ID = "d" * 64
TUNNEL_TOKEN = "test-token-never-written-to-receipts"


def _completed(
    args: Sequence[str],
    *,
    stdout: str = "",
    stderr: str = "",
    returncode: int = 0,
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(list(args), returncode, stdout, stderr)


def _security() -> dict[str, object]:
    return {
        "cap_drop": ["ALL"],
        "mem_limit": 256 * 1024 * 1024,
        "mem_reservation": 64 * 1024 * 1024,
        "pids_limit": 128,
        "restart": "unless-stopped",
        "security_opt": ["no-new-privileges:true"],
    }


def _target_rendered() -> dict[str, object]:
    return {
        "services": {
            ingress.API_SERVICE: {
                "environment": {
                    "EA_TRUST_PROXY_HEADERS": "1",
                    "EA_TRUSTED_PROXY_CIDRS": (
                        ingress.PUBLIC_INGRESS_TRUSTED_PROXY_CIDR
                    ),
                },
                "networks": {
                    "default": None,
                    "public_ingress": {
                        "ipv4_address": ingress.PUBLIC_INGRESS_API_IPV4
                    },
                },
            },
            ingress.CLOUDFLARED_SERVICE: {
                "image": ingress.PINNED_CLOUDFLARED_IMAGE,
                "container_name": ingress.CLOUDFLARED_CONTAINER,
                "command": ["tunnel", "run"],
                "environment": {"TUNNEL_TOKEN": TUNNEL_TOKEN},
                "networks": {
                    "public_ingress": {
                        "ipv4_address": ingress.PUBLIC_INGRESS_CLOUDFLARED_IPV4
                    },
                },
                **_security(),
            },
        },
        "networks": {
            "default": {"name": "ea_default", "ipam": {}},
            "public_ingress": {
                "name": ingress.PUBLIC_INGRESS_NETWORK,
                "ipam": {
                    "config": [
                        {
                            "subnet": ingress.PUBLIC_INGRESS_SUBNET,
                            "gateway": ingress.PUBLIC_INGRESS_GATEWAY,
                        }
                    ]
                },
            },
        },
    }


def _prior_rendered() -> dict[str, object]:
    return {
        "services": {
            ingress.CLOUDFLARED_SERVICE: {
                "image": ingress.PINNED_CLOUDFLARED_IMAGE,
                "container_name": ingress.CLOUDFLARED_CONTAINER,
                "command": ["tunnel", "run"],
                "environment": {"TUNNEL_TOKEN": TUNNEL_TOKEN},
                "networks": {"default": None, "property_default": None},
                **_security(),
            }
        },
        "networks": {
            "default": {"name": "ea_default"},
            "property_default": {"name": ingress.LEGACY_PROPERTY_NETWORK},
        },
    }


def _cloudflared_inspection(
    root: Path,
    *,
    mounts: list[dict[str, object]] | None = None,
    property_attached: bool = True,
) -> dict[str, object]:
    networks = {
        "ea_default": {
            "NetworkID": "e" * 64,
            "IPAddress": "172.22.0.4",
            "Aliases": [
                ingress.CLOUDFLARED_CONTAINER,
                ingress.CLOUDFLARED_SERVICE,
            ],
        }
    }
    if property_attached:
        networks[ingress.LEGACY_PROPERTY_NETWORK] = {
            "NetworkID": PROPERTY_NETWORK_ID,
            "IPAddress": "172.25.0.9",
            "Aliases": [
                ingress.CLOUDFLARED_CONTAINER,
                ingress.CLOUDFLARED_SERVICE,
            ],
        }
    return {
        "Id": "cloudflared-container-id",
        "Created": "2026-07-17T00:00:00Z",
        "Image": IMAGE_ID,
        "Config": {
            "Image": ingress.PINNED_CLOUDFLARED_IMAGE,
            "Cmd": ["tunnel", "run"],
            "Entrypoint": ["cloudflared", "--no-autoupdate"],
            "User": "65532",
            "Env": ["PATH=/usr/local/bin", f"TUNNEL_TOKEN={TUNNEL_TOKEN}"],
            "Labels": {
                "com.docker.compose.project": ingress.PROJECT_NAME,
                "com.docker.compose.service": ingress.CLOUDFLARED_SERVICE,
                "com.docker.compose.project.working_dir": str(root),
                "com.docker.compose.project.config_files": str(
                    root / "docker-compose.previous.yml"
                ),
            },
        },
        "HostConfig": {
            "CapDrop": ["ALL"],
            "Memory": 256 * 1024 * 1024,
            "MemoryReservation": 64 * 1024 * 1024,
            "PidsLimit": 128,
            "Privileged": False,
            "ReadonlyRootfs": False,
            "RestartPolicy": {"Name": "unless-stopped"},
            "SecurityOpt": ["no-new-privileges"],
        },
        "State": {"Running": True, "Restarting": False},
        "NetworkSettings": {"Networks": networks},
        "Mounts": list(mounts or []),
    }


def _api_inspection(
    *,
    stable: bool,
    public_ipv4: str = ingress.PUBLIC_INGRESS_API_IPV4,
    extra_network: bool = False,
) -> dict[str, object]:
    environment = [
        "EA_TRUST_PROXY_HEADERS=1",
        (
            "EA_TRUSTED_PROXY_CIDRS="
            + (
                ingress.PUBLIC_INGRESS_TRUSTED_PROXY_CIDR
                if stable
                else "172.22.0.12/32"
            )
        ),
        f"EA_SOURCE_REVISION={SOURCE_REVISION}",
    ]
    networks = (
        {
            ingress.DEFAULT_NETWORK: {
                "NetworkID": "e" * 64,
                "IPAddress": "172.22.0.12",
            },
            ingress.PUBLIC_INGRESS_NETWORK: {
                "NetworkID": NETWORK_ID,
                "IPAddress": public_ipv4,
            }
        }
        if stable
        else {"ea_default": {"NetworkID": "e" * 64, "IPAddress": "172.22.0.12"}}
    )
    if stable and extra_network:
        networks[ingress.LEGACY_PROPERTY_NETWORK] = {
            "NetworkID": PROPERTY_NETWORK_ID,
            "IPAddress": "172.25.0.12",
        }
    return {
        "Id": "api-container-id",
        "Config": {
            "Env": environment,
            "Labels": {
                "com.docker.compose.project": ingress.PROJECT_NAME,
                "com.docker.compose.service": ingress.API_SERVICE,
            },
        },
        "NetworkSettings": {"Networks": networks},
    }


class FakeRunner:
    def __init__(
        self,
        root: Path,
        *,
        api_stable: bool = True,
        target_rendered: Mapping[str, object] | None = None,
        baseline_mounts: list[dict[str, object]] | None = None,
        baseline_property_attached: bool = True,
        foreign_public_ipv4_owner: bool = False,
        api_runtime_ipv4: str = ingress.PUBLIC_INGRESS_API_IPV4,
        api_runtime_extra_network: bool = False,
        after_render: Callable[[], None] | None = None,
    ) -> None:
        self.root = root
        self.api_stable = api_stable
        self.target_rendered = dict(target_rendered or _target_rendered())
        self.baseline_mounts = list(baseline_mounts or [])
        self.baseline_property_attached = baseline_property_attached
        self.foreign_public_ipv4_owner = foreign_public_ipv4_owner
        self.api_runtime_ipv4 = api_runtime_ipv4
        self.api_runtime_extra_network = api_runtime_extra_network
        self.after_render = after_render
        self.commands: list[tuple[str, ...]] = []

    def run(
        self,
        args: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        del cwd, env
        command = tuple(args)
        self.commands.append(command)
        if command == ("git", "rev-parse", "HEAD"):
            return _completed(args, stdout=f"{SOURCE_REVISION}\n")
        if command == ("git", "status", "--porcelain=v1", "--untracked-files=no"):
            return _completed(args)
        if command == ("docker", "compose", "version"):
            return _completed(args, stdout="Docker Compose version v2.29.0\n")
        if command[:2] == ("docker", "inspect"):
            name = command[2]
            payload = (
                _cloudflared_inspection(
                    self.root,
                    mounts=self.baseline_mounts,
                    property_attached=self.baseline_property_attached,
                )
                if name == ingress.CLOUDFLARED_CONTAINER
                else _api_inspection(
                    stable=self.api_stable,
                    public_ipv4=self.api_runtime_ipv4,
                    extra_network=self.api_runtime_extra_network,
                )
            )
            return _completed(args, stdout=json.dumps([payload]))
        if command[:3] == ("docker", "image", "inspect"):
            return _completed(
                args,
                stdout=json.dumps(
                    [
                        {
                            "Id": IMAGE_ID,
                            "Config": {
                                "Env": ["PATH=/usr/local/bin"],
                                "Cmd": ["version"],
                                "Entrypoint": [
                                    "cloudflared",
                                    "--no-autoupdate",
                                ],
                                "User": "65532",
                            },
                        }
                    ]
                ),
            )
        if command[:3] == ("docker", "network", "inspect"):
            name = command[3]
            if name == ingress.PUBLIC_INGRESS_NETWORK:
                containers = {
                    "api-container-id": {
                        "Name": ingress.API_SERVICE,
                        "IPv4Address": f"{self.api_runtime_ipv4}/29",
                    }
                }
                if self.foreign_public_ipv4_owner:
                    containers["foreign-container-id"] = {
                        "Name": "foreign-proxy",
                        "IPv4Address": "172.31.254.2/29",
                    }
                payload = {
                    "Id": NETWORK_ID,
                    "Name": ingress.PUBLIC_INGRESS_NETWORK,
                    "Driver": "bridge",
                    "IPAM": {
                        "Driver": "default",
                        "Config": [
                            {
                                "Subnet": ingress.PUBLIC_INGRESS_SUBNET,
                                "Gateway": ingress.PUBLIC_INGRESS_GATEWAY,
                            }
                        ]
                    },
                    "Containers": containers,
                }
            elif name == "ea_default":
                payload = {
                    "Id": "e" * 64,
                    "Name": "ea_default",
                    "Driver": "bridge",
                    "IPAM": {
                        "Driver": "default",
                        "Config": [{"Subnet": "172.22.0.0/16"}],
                    },
                    "Containers": {
                        "cloudflared-container-id": {
                            "Name": ingress.CLOUDFLARED_CONTAINER,
                            "IPv4Address": "172.22.0.4/16",
                        }
                    },
                }
            else:
                payload = {
                    "Id": PROPERTY_NETWORK_ID,
                    "Name": ingress.LEGACY_PROPERTY_NETWORK,
                    "Driver": "bridge",
                    "IPAM": {
                        "Driver": "default",
                        "Config": [{"Subnet": "172.25.0.0/16"}],
                    },
                    "Containers": {
                        "cloudflared-container-id": {
                            "Name": ingress.CLOUDFLARED_CONTAINER,
                            "IPv4Address": "172.25.0.9/16",
                        }
                    },
                }
            return _completed(args, stdout=json.dumps([payload]))
        if "config" in command:
            config_index = command.index("config")
            if command[config_index:] == ("config", "--quiet"):
                return _completed(args)
            files = [
                command[index + 1]
                for index, item in enumerate(command)
                if item == "-f"
            ]
            rendered = (
                _prior_rendered()
                if any(item.endswith("docker-compose.previous.yml") for item in files)
                else self.target_rendered
            )
            if command[config_index:] == ("config", "--format", "json"):
                callback = self.after_render
                self.after_render = None
                if callback is not None:
                    callback()
            return _completed(args, stdout=json.dumps(rendered))
        completed = _completed(args, returncode=1, stderr="unexpected command")
        if check:
            raise AssertionError(f"unexpected command: {command}")
        return completed


def _root(tmp_path: Path) -> Path:
    for name in (
        ".env",
        "docker-compose.yml",
        "docker-compose.cloudflared.yml",
        "docker-compose.previous.yml",
    ):
        (tmp_path / name).write_text(f"# {name}\n", encoding="utf-8")
    (tmp_path / ".env").chmod(0o600)
    return tmp_path


def _lane(
    tmp_path: Path,
    *,
    runner: FakeRunner | None = None,
    http_no_redirect=None,
) -> ingress.PublicIngressReconciliationLane:
    root = _root(tmp_path)
    selected_runner = runner or FakeRunner(root)
    kwargs = {}
    if http_no_redirect is not None:
        kwargs["http_no_redirect"] = http_no_redirect
    return ingress.PublicIngressReconciliationLane(
        root=root,
        env={
            "EA_DEPLOYMENT_ID": "ingress-test-001",
            "EA_SOURCE_REVISION": SOURCE_REVISION,
            "EA_PUBLIC_ORIGIN": "https://myexternalbrain.com",
        },
        runner=selected_runner,
        receipt_dir=tmp_path / "receipts",
        global_lock_path=tmp_path / "ea-memorial-ea-api.lock",
        **kwargs,
    )


def _assert_no_mutation(commands: Sequence[Sequence[str]]) -> None:
    flattened = [tuple(command) for command in commands]
    assert not any("up" in command for command in flattened)
    assert not any("down" in command for command in flattened)
    assert not any(command[:3] == ("docker", "network", "rm") for command in flattened)
    assert not any(command[:2] == ("docker", "start") for command in flattened)


def _compose_config_commands(
    commands: Sequence[Sequence[str]],
) -> list[tuple[str, ...]]:
    return [tuple(command) for command in commands if "config" in command]


def test_preflight_captures_private_redacted_baseline_and_stable_api(tmp_path: Path) -> None:
    runner = FakeRunner(_root(tmp_path))
    lane = _lane(tmp_path, runner=runner)

    result = lane.run(preflight_only=True)

    assert result["receipt"]["status"] == "preflight_pass_coordinator_required"
    assert lane.baseline_path.stat().st_mode & 0o777 == 0o600
    raw = lane.baseline_path.read_text(encoding="utf-8")
    baseline = json.loads(raw)
    assert TUNNEL_TOKEN not in raw
    assert baseline["contains_environment_values"] is False
    assert baseline["contains_tunnel_token"] is False
    assert baseline["container"]["environment_identity"]["environment_count"] == 2
    assert baseline["container"]["user"] == "65532"
    assert baseline["container"]["mounts"] == []
    assert all(
        network["driver"] == "bridge"
        and network["ipam_driver"] == "default"
        and network["aliases"]
        for network in baseline["container"]["networks"]
    )
    assert lane.receipt_path.stat().st_mode & 0o777 == 0o600
    _assert_no_mutation(runner.commands)


def test_current_proxy_mismatch_denies_joint_reconciliation_without_mutation(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    runner = FakeRunner(root, api_stable=False)
    lane = _lane(tmp_path, runner=runner)

    with pytest.raises(
        ingress.DeployError, match="joint_api_ingress_coordinator_required"
    ):
        lane.run(preflight_only=True)

    assert lane.receipt["status"] == "coordinator_required"
    assert lane.receipt["coordinator"]["reason"] == "joint_api_ingress_atomicity_unproven"
    assert lane.receipt["failure"]["mutation_attempted"] is False
    _assert_no_mutation(runner.commands)


def test_default_reconciliation_is_denied_even_after_passing_preflight(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    runner = FakeRunner(root)
    lane = _lane(tmp_path, runner=runner)

    with pytest.raises(
        ingress.DeployError,
        match="public_ingress_reconciliation_coordinator_required",
    ):
        lane.run()

    assert lane.receipt["coordinator"] == {
        "status": "deny",
        "reason": "standalone_cloudflared_mutation_not_supported",
        "joint_api_ingress_atomicity_proven": False,
        "mutation_attempted": False,
        "rollback_claimed": False,
    }
    _assert_no_mutation(runner.commands)


def test_read_only_runner_rejects_compose_up(tmp_path: Path) -> None:
    lane = _lane(tmp_path)

    with pytest.raises(
        ingress.DeployError, match="public_ingress_read_only_command_rejected"
    ):
        lane._run(["docker", "compose", "up", "-d", ingress.CLOUDFLARED_SERVICE])


def test_target_compose_rejects_unpinned_cloudflared_image(tmp_path: Path) -> None:
    root = _root(tmp_path)
    rendered = _target_rendered()
    rendered["services"][ingress.CLOUDFLARED_SERVICE]["image"] = (
        "cloudflare/cloudflared:latest"
    )
    runner = FakeRunner(root, target_rendered=rendered)
    lane = _lane(tmp_path, runner=runner)

    with pytest.raises(
        ingress.DeployError, match="target_cloudflared_image_not_pinned"
    ):
        lane.run(preflight_only=True)

    _assert_no_mutation(runner.commands)


def test_target_compose_rejects_insecure_cloudflared_service(tmp_path: Path) -> None:
    root = _root(tmp_path)
    rendered = _target_rendered()
    rendered["services"][ingress.CLOUDFLARED_SERVICE]["cap_drop"] = []
    runner = FakeRunner(root, target_rendered=rendered)
    lane = _lane(tmp_path, runner=runner)

    with pytest.raises(
        ingress.DeployError, match="target_cloudflared_security_invalid"
    ):
        lane.run(preflight_only=True)


@pytest.mark.parametrize(
    "public_attachment",
    [None, {"ipv4_address": "172.31.254.4"}],
)
def test_target_compose_requires_exact_api_static_ipv4(
    tmp_path: Path,
    public_attachment: object,
) -> None:
    root = _root(tmp_path)
    rendered = _target_rendered()
    rendered["services"][ingress.API_SERVICE]["networks"][
        "public_ingress"
    ] = public_attachment
    lane = _lane(
        tmp_path,
        runner=FakeRunner(root, target_rendered=rendered),
    )

    with pytest.raises(
        ingress.DeployError, match="target_api_public_ingress_ipv4_invalid"
    ):
        lane.run(preflight_only=True)


def test_target_compose_rejects_extra_api_network(tmp_path: Path) -> None:
    root = _root(tmp_path)
    rendered = _target_rendered()
    rendered["services"][ingress.API_SERVICE]["networks"][
        "property_default"
    ] = None
    rendered["networks"]["property_default"] = {
        "name": ingress.LEGACY_PROPERTY_NETWORK
    }
    lane = _lane(
        tmp_path,
        runner=FakeRunner(root, target_rendered=rendered),
    )

    with pytest.raises(ingress.DeployError, match="target_api_networks_invalid"):
        lane.run(preflight_only=True)


@pytest.mark.parametrize(
    ("runner_kwargs", "reason"),
    [
        (
            {"api_runtime_ipv4": "172.31.254.4"},
            "public_ingress_api_runtime_network_missing",
        ),
        (
            {"api_runtime_extra_network": True},
            "public_ingress_api_runtime_networks_invalid",
        ),
    ],
)
def test_runtime_requires_exact_api_network_membership(
    tmp_path: Path,
    runner_kwargs: dict[str, object],
    reason: str,
) -> None:
    root = _root(tmp_path)
    lane = _lane(
        tmp_path,
        runner=FakeRunner(root, **runner_kwargs),
    )

    with pytest.raises(
        ingress.DeployError, match="joint_api_ingress_coordinator_required"
    ):
        lane.run(preflight_only=True)
    assert lane.receipt["coordinator"]["api_runtime_posture"] == reason


def test_baseline_rejects_cloudflared_mounts(tmp_path: Path) -> None:
    root = _root(tmp_path)
    runner = FakeRunner(
        root,
        baseline_mounts=[
            {
                "Type": "bind",
                "Source": "/tmp/unexpected",
                "Destination": "/unexpected",
                "RW": False,
            }
        ],
    )
    lane = _lane(tmp_path, runner=runner)

    with pytest.raises(
        ingress.DeployError, match="prior_cloudflared_mounts_invalid"
    ):
        lane.run(preflight_only=True)

    _assert_no_mutation(runner.commands)


def test_standalone_baseline_rejects_legacy_detached_property_render(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    runner = FakeRunner(root, baseline_property_attached=False)
    lane = _lane(tmp_path, runner=runner)

    with pytest.raises(
        ingress.DeployError, match="prior_cloudflared_networks_mismatch"
    ):
        lane.run(preflight_only=True)

    _assert_no_mutation(runner.commands)


def test_target_ipv4_must_be_free_or_owned_by_baseline_cloudflared(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    runner = FakeRunner(root, foreign_public_ipv4_owner=True)
    lane = _lane(tmp_path, runner=runner)

    with pytest.raises(
        ingress.DeployError, match="joint_api_ingress_coordinator_required"
    ):
        lane.run(preflight_only=True)

    assert (
        lane.receipt["coordinator"]["api_runtime_posture"]
        == "public_ingress_cloudflared_ipv4_not_available"
    )
    _assert_no_mutation(runner.commands)


def _public_response(
    url: str,
    _timeout: float,
    method: str,
    _authority: str,
    *,
    source_revision: str = SOURCE_REVISION,
) -> ingress.HttpResponse:
    path = urllib.parse.urlsplit(url).path
    content_type = "application/json" if path.endswith(".json") or path == "/version" else "text/html; charset=utf-8"
    body = (
        json.dumps({"commit_sha": source_revision}).encode("utf-8")
        if path == "/version"
        else json.dumps({"slug": "manfred"}).encode("utf-8")
        if content_type == "application/json"
        else b"<!doctype html><title>Manfred</title>"
    )
    return ingress.HttpResponse(
        200,
        content_type,
        b"" if method == "HEAD" else body,
        source_revision,
        headers={},
    )


def test_public_verification_proves_get_and_head_on_all_surfaces(tmp_path: Path) -> None:
    lane = _lane(tmp_path, http_no_redirect=_public_response)

    result = lane.run(verify_public_only=True)

    assert result["receipt"]["status"] == "public_verification_pass"
    assert len(result["evidence"]) == len(ingress.PUBLIC_PROBES) * 2
    assert {row["method"] for row in result["evidence"].values()} == {"GET", "HEAD"}


def test_public_verification_rejects_wrong_revision(tmp_path: Path) -> None:
    def wrong_revision(
        url: str, timeout: float, method: str, authority: str
    ) -> ingress.HttpResponse:
        return _public_response(
            url,
            timeout,
            method,
            authority,
            source_revision="f" * 40,
        )

    lane = _lane(tmp_path, http_no_redirect=wrong_revision)

    with pytest.raises(ingress.DeployError, match="probe_revision_mismatch"):
        lane.run(verify_public_only=True)


def test_global_memorial_lock_is_private_and_reused(tmp_path: Path) -> None:
    lane = _lane(tmp_path)

    lane._acquire_lock()
    try:
        assert lane.global_lock_path.name == "ea-memorial-ea-api.lock"
        assert lane.global_lock_path.stat().st_mode & 0o777 == 0o600
    finally:
        lane._release_lock()


def test_baseline_and_receipt_paths_do_not_follow_symlinks(tmp_path: Path) -> None:
    lane = _lane(tmp_path)
    lane.receipt_dir.mkdir(parents=True, exist_ok=True)
    target = tmp_path / "outside.json"
    target.write_text("keep", encoding="utf-8")
    lane.baseline_path.symlink_to(target)

    lane._write_private_json(lane.baseline_path, {"safe": True})

    assert target.read_text(encoding="utf-8") == "keep"
    assert not lane.baseline_path.is_symlink()
    assert json.loads(lane.baseline_path.read_text(encoding="utf-8")) == {
        "safe": True
    }


def test_baseline_file_mode_is_exactly_private(tmp_path: Path) -> None:
    lane = _lane(tmp_path)
    lane._write_private_json(lane.baseline_path, {"safe": True})

    mode = stat.S_IMODE(lane.baseline_path.stat().st_mode)
    assert mode == 0o600


def test_preflight_rejects_world_readable_env_file(tmp_path: Path) -> None:
    lane = _lane(tmp_path)
    (tmp_path / ".env").chmod(0o644)

    with pytest.raises(
        ingress.DeployError, match="reconciliation_input_untrusted:.env"
    ):
        lane.run(preflight_only=True)

    assert _compose_config_commands(lane.runner.commands) == []


def test_preflight_rejects_world_readable_optional_env_before_any_render(
    tmp_path: Path,
) -> None:
    lane = _lane(tmp_path)
    optional_env = tmp_path / ".env.local"
    optional_env.write_text("EA_API_TOKEN=private\n", encoding="utf-8")
    optional_env.chmod(0o644)

    with pytest.raises(
        ingress.DeployError,
        match=r"reconciliation_input_untrusted:\.env\.local",
    ):
        lane.run(preflight_only=True)

    assert _compose_config_commands(lane.runner.commands) == []


def test_preflight_rejects_symlinked_env_file(tmp_path: Path) -> None:
    lane = _lane(tmp_path)
    target = tmp_path / "outside.env"
    target.write_text("TUNNEL_TOKEN=outside\n", encoding="utf-8")
    target.chmod(0o600)
    env_path = tmp_path / ".env"
    env_path.unlink()
    env_path.symlink_to(target)

    with pytest.raises(
        ingress.DeployError, match="reconciliation_input_untrusted:.env"
    ):
        lane.run(preflight_only=True)

    assert _compose_config_commands(lane.runner.commands) == []


def test_preflight_rejects_symlinked_target_compose_before_any_render(
    tmp_path: Path,
) -> None:
    lane = _lane(tmp_path)
    target = tmp_path / "outside-compose.yml"
    target.write_text("services: {}\n", encoding="utf-8")
    compose_path = tmp_path / "docker-compose.cloudflared.yml"
    compose_path.unlink()
    compose_path.symlink_to(target)

    with pytest.raises(
        ingress.DeployError,
        match="reconciliation_input_untrusted:docker-compose.cloudflared.yml",
    ):
        lane.run(preflight_only=True)

    assert _compose_config_commands(lane.runner.commands) == []


def test_preflight_rejects_symlinked_prior_compose_before_any_render(
    tmp_path: Path,
) -> None:
    lane = _lane(tmp_path)
    target = tmp_path / "outside-prior-compose.yml"
    target.write_text("services: {}\n", encoding="utf-8")
    compose_path = tmp_path / "docker-compose.previous.yml"
    compose_path.unlink()
    compose_path.symlink_to(target)

    with pytest.raises(
        ingress.DeployError,
        match="prior_cloudflared_rollback_input_invalid",
    ):
        lane.run(preflight_only=True)

    assert _compose_config_commands(lane.runner.commands) == []


def test_preflight_rejects_input_changed_after_compose_render(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)

    def mutate_env() -> None:
        (root / ".env").write_text("# changed after render\n", encoding="utf-8")

    runner = FakeRunner(root, after_render=mutate_env)
    lane = _lane(tmp_path, runner=runner)

    with pytest.raises(
        ingress.DeployError,
        match="public_ingress_compose_input_changed",
    ):
        lane.run(preflight_only=True)

    assert len(_compose_config_commands(runner.commands)) == 2
    _assert_no_mutation(runner.commands)
