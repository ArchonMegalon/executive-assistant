#!/usr/bin/env python3
"""Fail-closed preflight for the EA public-ingress reconciliation.

This lane deliberately performs no mutation. It captures and validates the
inputs the joint coordinator needs, proves the public edge when requested, and
denies standalone reconciliation before any mutating command can run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess  # nosec B404 - the runner admits fixed read-only commands only
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

try:
    from scripts.deploy_ea_memorial import (
        DEFAULT_PUBLIC_HOSTS,
        MEMORIAL_SLUG,
        PROJECT_NAME,
        REQUIRED_CONTROL_TOUR_SLUG,
        SOURCE_REVISION_PATTERN,
        DeployError,
        HttpResponse,
        MemorialDeployLane,
        Runner,
        SubprocessRunner,
        _default_http_no_redirect,
        _environment_identity,
        _first_nonempty,
        _json_object,
        _mount_identities,
        _normalized_command,
        _process_config_identity,
        _utc_now,
        _validate_public_origin,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from deploy_ea_memorial import (  # type: ignore[no-redef]
        DEFAULT_PUBLIC_HOSTS,
        MEMORIAL_SLUG,
        PROJECT_NAME,
        REQUIRED_CONTROL_TOUR_SLUG,
        SOURCE_REVISION_PATTERN,
        DeployError,
        HttpResponse,
        MemorialDeployLane,
        Runner,
        SubprocessRunner,
        _default_http_no_redirect,
        _environment_identity,
        _first_nonempty,
        _json_object,
        _mount_identities,
        _normalized_command,
        _process_config_identity,
        _utc_now,
        _validate_public_origin,
    )


ROOT = Path(__file__).resolve().parents[1]
API_SERVICE = "ea-api"
CLOUDFLARED_SERVICE = "ea-cloudflared"
CLOUDFLARED_CONTAINER = "externalbrain-cloudflared"
TARGET_COMPOSE_FILES = ("docker-compose.yml", "docker-compose.cloudflared.yml")
PUBLIC_INGRESS_NETWORK = "ea_public_ingress"
DEFAULT_NETWORK = f"{PROJECT_NAME}_default"
LEGACY_PROPERTY_NETWORK = "property_default"
PUBLIC_INGRESS_SUBNET = "172.31.254.0/29"
PUBLIC_INGRESS_GATEWAY = "172.31.254.1"
PUBLIC_INGRESS_CLOUDFLARED_IPV4 = "172.31.254.2"
PUBLIC_INGRESS_API_IPV4 = "172.31.254.3"
PUBLIC_INGRESS_TRUSTED_PROXY_CIDR = "172.31.254.2/32"
PINNED_CLOUDFLARED_IMAGE = (
    "cloudflare/cloudflared:latest@sha256:"
    "6d91c121b803126f7a5344005d17a9324788fc09d305b6e2560ec6040a7ae283"
)
GLOBAL_MEMORIAL_LOCK_PATH = Path("/run/lock/ea-memorial-ea-api.lock")
MAX_INPUT_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True)
class PublicProbe:
    label: str
    path: str
    media_types: tuple[str, ...]
    json_revision_field: str = ""


PUBLIC_PROBES = (
    PublicProbe("version", "/version", ("application/json",), "commit_sha"),
    PublicProbe(
        "memorial",
        f"/memorials/{MEMORIAL_SLUG}",
        ("text/html",),
    ),
    PublicProbe(
        "memorial_manifest",
        f"/memorials/{MEMORIAL_SLUG}.json",
        ("application/json",),
    ),
    PublicProbe(
        "spatial_landing",
        f"/tours/{REQUIRED_CONTROL_TOUR_SLUG}",
        ("text/html",),
    ),
    PublicProbe(
        "spatial_manifest",
        f"/tours/{REQUIRED_CONTROL_TOUR_SLUG}.json",
        ("application/json",),
    ),
    PublicProbe(
        "spatial_viewer",
        (
            f"/tours/viewer/{REQUIRED_CONTROL_TOUR_SLUG}/"
            "generated-reconstruction/viewer.html"
        ),
        ("text/html",),
    ),
)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _trusted_file_seal(
    path: Path,
    *,
    private: bool = False,
    expected_uid: int | None = None,
) -> dict[str, object]:
    try:
        seal = MemorialDeployLane._deployment_input_file_seal(path)
    except DeployError as exc:
        try:
            path_metadata = path.lstat()
        except OSError:
            path_metadata = None
        reason = (
            "reconciliation_input_unavailable"
            if str(exc)
            == f"deployment_input_file_unavailable:{path.name}"
            and (
                path_metadata is None
                or not stat.S_ISLNK(path_metadata.st_mode)
            )
            else "reconciliation_input_untrusted"
        )
        raise DeployError(f"{reason}:{path.name}") from exc
    size_bytes = int(seal.get("size_bytes") or 0)
    mode = str(seal.get("mode") or "")
    sealed_uid = seal.get("uid")
    required_uid = os.geteuid() if expected_uid is None else expected_uid
    if (
        not 0 < size_bytes <= MAX_INPUT_BYTES
        or (
            private
            and (
                type(sealed_uid) is not int
                or sealed_uid != required_uid
                or mode != "0600"
            )
        )
    ):
        raise DeployError(f"reconciliation_input_untrusted:{path.name}")
    return dict(seal)


def _trusted_optional_private_file_seal(path: Path) -> dict[str, object]:
    try:
        return {
            "present": True,
            **_trusted_file_seal(
                path,
                private=True,
                expected_uid=os.geteuid(),
            ),
        }
    except DeployError as exc:
        if str(exc) != f"reconciliation_input_unavailable:{path.name}":
            raise
    try:
        return MemorialDeployLane._deployment_input_absence_seal(path)
    except DeployError as exc:
        raise DeployError(f"reconciliation_input_untrusted:{path.name}") from exc


def _environment_mapping(value: object) -> dict[str, str]:
    if isinstance(value, dict):
        mapping = {str(key): str(item) for key, item in value.items()}
    elif isinstance(value, list):
        mapping = {}
        for entry in value:
            if not isinstance(entry, str) or "=" not in entry or "\x00" in entry:
                raise DeployError("cloudflared_environment_invalid")
            key, item = entry.split("=", 1)
            if not key or key in mapping:
                raise DeployError("cloudflared_environment_invalid")
            mapping[key] = item
    else:
        raise DeployError("cloudflared_environment_invalid")
    if any(not key or "\x00" in key or "\x00" in item for key, item in mapping.items()):
        raise DeployError("cloudflared_environment_invalid")
    return mapping


def _environment_digest(mapping: Mapping[str, str]) -> dict[str, object]:
    return _environment_identity(
        [f"{key}={mapping[key]}" for key in sorted(mapping)]
    )


def _security_identity(config: Mapping[str, Any], host: Mapping[str, Any]) -> dict[str, object]:
    del config
    return {
        "cap_drop": sorted(str(item).upper() for item in list(host.get("CapDrop") or [])),
        "memory": int(host.get("Memory") or 0),
        "memory_reservation": int(host.get("MemoryReservation") or 0),
        "pids_limit": int(host.get("PidsLimit") or 0),
        "privileged": bool(host.get("Privileged")),
        "read_only": bool(host.get("ReadonlyRootfs")),
        "restart": str(dict(host.get("RestartPolicy") or {}).get("Name") or ""),
        "security_opt": sorted(
            str(item).removesuffix(":true")
            for item in list(host.get("SecurityOpt") or [])
        ),
    }


def _rendered_security_identity(service: Mapping[str, Any]) -> dict[str, object]:
    return {
        "cap_drop": sorted(str(item).upper() for item in list(service.get("cap_drop") or [])),
        "memory": int(service.get("mem_limit") or 0),
        "memory_reservation": int(service.get("mem_reservation") or 0),
        "pids_limit": int(service.get("pids_limit") or 0),
        "privileged": bool(service.get("privileged")),
        "read_only": bool(service.get("read_only")),
        "restart": str(service.get("restart") or ""),
        "security_opt": sorted(
            str(item).removesuffix(":true")
            for item in list(service.get("security_opt") or [])
        ),
    }


class PublicIngressReconciliationLane(MemorialDeployLane):
    """Read-only ingress preflight serialized with the memorial deploy lane."""

    def __init__(
        self,
        *,
        root: Path = ROOT,
        env: Mapping[str, str] | None = None,
        runner: Runner | None = None,
        http_no_redirect: Callable[[str, float, str, str], HttpResponse] = (
            _default_http_no_redirect
        ),
        receipt_dir: Path | None = None,
        global_lock_path: Path | None = None,
        request_timeout_seconds: float = 10.0,
    ) -> None:
        source_env = dict(os.environ if env is None else env)
        configured_receipt_dir = _first_nonempty(
            source_env.get("EA_PUBLIC_INGRESS_RECEIPT_DIR")
        )
        selected_receipt_dir = receipt_dir or (
            Path(configured_receipt_dir).expanduser()
            if configured_receipt_dir
            else root / ".runtime" / "deployments" / "public-ingress"
        )
        super().__init__(
            root=root,
            env=source_env,
            runner=runner,
            http_no_redirect=http_no_redirect,
            receipt_dir=selected_receipt_dir,
            global_lock_path=global_lock_path or GLOBAL_MEMORIAL_LOCK_PATH,
            request_timeout_seconds=request_timeout_seconds,
        )
        self.source_revision = str(source_env.get("EA_SOURCE_REVISION") or "").strip()
        if SOURCE_REVISION_PATTERN.fullmatch(self.source_revision) is None:
            raise DeployError("public_ingress_source_revision_required")
        configured_hosts = _first_nonempty(
            source_env.get("EA_PUBLIC_INGRESS_PUBLIC_HOST_ALLOWLIST"),
            ",".join(DEFAULT_PUBLIC_HOSTS),
        )
        self.allowed_public_hosts = tuple(
            item.strip().lower().rstrip(".")
            for item in configured_hosts.split(",")
            if item.strip()
        )
        self.public_origin = _validate_public_origin(
            str(source_env.get("EA_PUBLIC_ORIGIN") or ""),
            allowed_hosts=self.allowed_public_hosts,
        )
        self.baseline_path = self.receipt_dir / f"{self.deployment_id}.baseline.json"
        self.command_timeout_provider: Callable[[], float | None] | None = None
        self.target_compose_files = TARGET_COMPOSE_FILES
        self.release_env = dict(source_env)
        self.release_env.update(
            {
                "COMPOSE_PROJECT_NAME": PROJECT_NAME,
                "EA_DEPLOYMENT_ID": self.deployment_id,
                "EA_SOURCE_REVISION": self.source_revision,
            }
        )
        self.receipt = {
            "contract_name": "ea.public_ingress_reconciliation_preflight.v2",
            "deployment_id": self.deployment_id,
            "source_revision": self.source_revision,
            "service_scope": [CLOUDFLARED_SERVICE],
            "mutation_scope": [],
            "global_lock_path": str(self.global_lock_path),
            "started_at": _utc_now(),
            "status": "preflight",
            "checks": [],
            "coordinator": {
                "status": "deny",
                "reason": "standalone_cloudflared_mutation_not_supported",
                "joint_api_ingress_atomicity_proven": False,
            },
        }

    def _run(
        self,
        args: Sequence[str],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        command = tuple(str(item) for item in args)
        read_only = False
        if command in {
            ("docker", "compose", "version"),
            ("docker-compose", "version"),
            ("git", "rev-parse", "HEAD"),
            ("git", "status", "--porcelain=v1", "--untracked-files=no"),
        }:
            read_only = True
        elif command[:2] in {
            ("docker", "inspect"),
            ("docker", "network"),
            ("docker", "image"),
        }:
            read_only = (
                command[:3] in {
                    ("docker", "network", "inspect"),
                    ("docker", "image", "inspect"),
                }
                or command[:2] == ("docker", "inspect")
            )
        elif "config" in command and (
            command[:2] == ("docker", "compose")
            or command[:1] == ("docker-compose",)
        ):
            config_index = command.index("config")
            read_only = command[config_index:] in {
                ("config", "--quiet"),
                ("config", "--format", "json"),
            }
        if not read_only:
            raise DeployError("public_ingress_read_only_command_rejected")
        selected_runner = self.runner
        kwargs = {
            "cwd": (cwd or self.root),
            "env": (self.release_env if env is None else env),
            "check": check,
        }
        if isinstance(selected_runner, SubprocessRunner):
            timeout_seconds = 30.0
            if self.command_timeout_provider is not None:
                remaining = self.command_timeout_provider()
                if remaining is None or remaining <= 0:
                    raise DeployError("public_ingress_command_deadline_exceeded")
                timeout_seconds = min(timeout_seconds, remaining)
            return selected_runner.run(
                list(command),
                **kwargs,
                timeout_seconds=timeout_seconds,
            )
        if self.command_timeout_provider is not None:
            remaining = self.command_timeout_provider()
            if remaining is None or remaining <= 0:
                raise DeployError("public_ingress_command_deadline_exceeded")
        return selected_runner.run(list(command), **kwargs)

    def _git_source_preflight(self) -> None:
        head = self._run(["git", "rev-parse", "HEAD"]).stdout.strip()
        if head != self.source_revision:
            raise DeployError("public_ingress_source_revision_mismatch")
        dirty = self._run(
            ["git", "status", "--porcelain=v1", "--untracked-files=no"]
        ).stdout
        if dirty.strip():
            raise DeployError("public_ingress_source_worktree_dirty")
        self._record_check("source_revision", "pass", source_revision=head)

    @staticmethod
    def _compose_input_paths(*, root: Path, files: Sequence[str]) -> list[Path]:
        selected_root = root.expanduser()
        return [
            selected_root / ".env",
            *(
                candidate
                if (candidate := Path(str(item)).expanduser()).is_absolute()
                else selected_root / candidate
                for item in files
            ),
        ]

    def _capture_compose_input_seals(
        self, *, root: Path, files: Sequence[str]
    ) -> list[dict[str, object]]:
        selected_root = root.expanduser()
        required = [
            _trusted_file_seal(
                path,
                private=(index == 0),
                expected_uid=os.geteuid(),
            )
            for index, path in enumerate(
                self._compose_input_paths(root=root, files=files)
            )
        ]
        return [
            *required,
            _trusted_optional_private_file_seal(selected_root / ".env.local"),
        ]

    def _render_compose(
        self,
        *,
        root: Path,
        files: Sequence[str],
        expected_input_seals: Sequence[Mapping[str, object]] | None = None,
    ) -> tuple[dict[str, Any], list[dict[str, object]]]:
        selected_root = root.expanduser()
        before = self._capture_compose_input_seals(root=selected_root, files=files)
        if expected_input_seals is not None and before != [
            dict(item) for item in expected_input_seals
        ]:
            raise DeployError("public_ingress_compose_input_changed")

        args = self._compose_args(root=selected_root, files=files)
        rendered_stdout = ""
        render_error: BaseException | None = None
        try:
            self._run([*args, "config", "--quiet"], cwd=selected_root)
            rendered_stdout = self._run(
                [*args, "config", "--format", "json"], cwd=selected_root
            ).stdout
        except BaseException as exc:
            render_error = exc
        try:
            after = self._capture_compose_input_seals(
                root=selected_root,
                files=files,
            )
        except DeployError as seal_error:
            if render_error is not None:
                raise DeployError("public_ingress_compose_input_changed") from render_error
            raise seal_error
        if after != before:
            raise DeployError("public_ingress_compose_input_changed") from render_error
        if render_error is not None:
            raise render_error
        return (
            _json_object(
                rendered_stdout,
                reason="public_ingress_compose_render_invalid",
            ),
            before,
        )

    @staticmethod
    def _service(rendered: Mapping[str, Any], name: str) -> dict[str, Any]:
        services = rendered.get("services")
        service = dict(services).get(name) if isinstance(services, dict) else None
        if not isinstance(service, dict):
            raise DeployError(f"public_ingress_service_missing:{name}")
        return dict(service)

    @staticmethod
    def _actual_network_names(
        rendered: Mapping[str, Any], service: Mapping[str, Any]
    ) -> dict[str, str]:
        network_definitions = (
            dict(rendered.get("networks") or {})
            if isinstance(rendered.get("networks"), dict)
            else {}
        )
        service_networks = service.get("networks")
        if isinstance(service_networks, list):
            keys = [str(item) for item in service_networks]
        elif isinstance(service_networks, dict):
            keys = [str(item) for item in service_networks]
        else:
            raise DeployError("public_ingress_networks_invalid")
        result: dict[str, str] = {}
        for key in keys:
            definition = network_definitions.get(key)
            definition = dict(definition) if isinstance(definition, dict) else {}
            result[key] = str(definition.get("name") or key)
        return result

    def _capture_cloudflared_baseline(
        self,
        *,
        allow_legacy_property_detached: bool = False,
    ) -> dict[str, Any]:
        inspection = self._inspect_container(CLOUDFLARED_CONTAINER)
        self._require_compose_identity(
            inspection,
            service=CLOUDFLARED_SERVICE,
            reason_prefix="prior_cloudflared",
        )
        topology = self._compose_topology(
            inspection, reason_prefix="prior_cloudflared"
        )
        prior_root = Path(str(topology["working_dir"])).expanduser()
        prior_files = [str(item) for item in topology["compose_config_files"]]
        rendered, input_seals = self._render_compose(
            root=prior_root,
            files=prior_files,
        )
        service = self._service(rendered, CLOUDFLARED_SERVICE)
        config = dict(inspection.get("Config") or {})
        host = dict(inspection.get("HostConfig") or {})
        state = dict(inspection.get("State") or {})
        if not bool(state.get("Running")) or bool(state.get("Restarting")):
            raise DeployError("prior_cloudflared_not_running")
        image_reference = str(config.get("Image") or "")
        image_id = str(inspection.get("Image") or "")
        if str(service.get("image") or "") != image_reference:
            raise DeployError("prior_cloudflared_compose_image_mismatch")
        image = self._inspect_image_config(image_reference)
        if image["image_id"] != image_id:
            raise DeployError("prior_cloudflared_image_identity_mismatch")
        image_config = dict(image["config"])
        rendered_environment = _environment_mapping(service.get("environment"))
        runtime_environment = _environment_mapping(config.get("Env"))
        token = rendered_environment.get("TUNNEL_TOKEN")
        if not token or runtime_environment.get("TUNNEL_TOKEN") != token:
            raise DeployError("prior_cloudflared_tunnel_identity_mismatch")
        expected_environment = self._rendered_environment_entries(
            service, image_config
        )
        if _environment_identity(expected_environment) != _environment_digest(
            runtime_environment
        ):
            raise DeployError("prior_cloudflared_environment_identity_mismatch")
        rendered_security = _rendered_security_identity(service)
        runtime_security = _security_identity(config, host)
        if rendered_security != runtime_security:
            raise DeployError("prior_cloudflared_security_mismatch")
        expected_process = self._rendered_process_config(service, image_config)
        actual_process = {
            "Cmd": _normalized_command(config.get("Cmd")),
            "Entrypoint": _normalized_command(config.get("Entrypoint")),
            "User": str(config.get("User") or ""),
        }
        if expected_process != actual_process:
            raise DeployError("prior_cloudflared_command_mismatch")
        service_volumes = service.get("volumes")
        if service_volumes is not None and service_volumes != []:
            raise DeployError("prior_cloudflared_mounts_invalid")
        if _mount_identities(inspection):
            raise DeployError("prior_cloudflared_mounts_invalid")
        rendered_network_names = self._actual_network_names(rendered, service)
        rendered_networks = set(rendered_network_names.values())
        runtime_network_payload = dict(
            dict(inspection.get("NetworkSettings") or {}).get("Networks") or {}
        )
        runtime_networks = set(runtime_network_payload)
        if runtime_networks != rendered_networks:
            default_network = str(rendered_network_names.get("default") or "")
            if not (
                allow_legacy_property_detached
                and set(rendered_network_names)
                == {"default", LEGACY_PROPERTY_NETWORK}
                and default_network
                and rendered_network_names.get(LEGACY_PROPERTY_NETWORK)
                == LEGACY_PROPERTY_NETWORK
                and runtime_networks == {default_network}
                and rendered_networks
                == {default_network, LEGACY_PROPERTY_NETWORK}
            ):
                raise DeployError("prior_cloudflared_networks_mismatch")
        container_id = str(inspection.get("Id") or "")
        if not container_id:
            raise DeployError("prior_cloudflared_container_identity_invalid")
        expected_aliases = {
            CLOUDFLARED_SERVICE,
            str(service.get("container_name") or CLOUDFLARED_CONTAINER),
        }
        network_identity: list[dict[str, object]] = []
        for name in sorted(runtime_network_payload):
            endpoint = dict(runtime_network_payload[name] or {})
            network_identity.append(
                self._network_endpoint_identity(
                    name=name,
                    endpoint=endpoint,
                    container_id=container_id,
                    expected_aliases=expected_aliases,
                )
            )
        baseline = {
            "contract_name": "ea.public_ingress_cloudflared_baseline.v1",
            "captured_at": _utc_now(),
            "container": {
                "id": container_id,
                "created_at": str(inspection.get("Created") or ""),
                "image_id": image_id,
                "image_reference": image_reference,
                "compose_working_dir": str(prior_root),
                "compose_config_files": prior_files,
                "compose_input_seals": input_seals,
                "environment_identity": _environment_digest(runtime_environment),
                "command": actual_process["Cmd"],
                "entrypoint": actual_process["Entrypoint"],
                "user": actual_process["User"],
                "process_config_sha256": _process_config_identity(config),
                "security": runtime_security,
                "mounts": [],
                "networks": network_identity,
            },
            "contains_environment_values": False,
            "contains_tunnel_token": False,
            "restoration": {
                "status": "coordinator_required",
                "reason": "standalone_mutation_not_supported",
                "compose_no_deps_required": True,
                "network_removal_allowed": False,
            },
        }
        self._write_private_json(self.baseline_path, baseline)
        self._record_check(
            "cloudflared_baseline",
            "pass",
            baseline_path=str(self.baseline_path),
            baseline_sha256=_sha256(self.baseline_path.read_bytes()),
            environment_count=int(
                dict(baseline["container"]["environment_identity"])[
                    "environment_count"
                ]
            ),
            network_count=len(network_identity),
            contains_environment_values=False,
            contains_tunnel_token=False,
        )
        return baseline

    def _write_private_json(self, path: Path, payload: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.parent.chmod(0o700)
        temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}")
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
            0o600,
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            path.chmod(0o600)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def _validate_target_compose(
        self,
        *,
        expected_input_seals: Sequence[Mapping[str, object]],
    ) -> dict[str, Any]:
        rendered, input_seals = self._render_compose(
            root=self.root,
            files=self.target_compose_files,
            expected_input_seals=expected_input_seals,
        )
        api = self._service(rendered, API_SERVICE)
        cloudflared = self._service(rendered, CLOUDFLARED_SERVICE)
        if str(cloudflared.get("image") or "") != PINNED_CLOUDFLARED_IMAGE:
            raise DeployError("target_cloudflared_image_not_pinned")
        image = self._inspect_image_config(PINNED_CLOUDFLARED_IMAGE)
        image_config = dict(image["config"])
        expected_process = self._rendered_process_config(cloudflared, image_config)
        if expected_process["Cmd"] != ["tunnel", "run"]:
            raise DeployError("target_cloudflared_command_invalid")
        environment = _environment_mapping(cloudflared.get("environment"))
        if set(environment) != {"TUNNEL_TOKEN"} or not environment["TUNNEL_TOKEN"]:
            raise DeployError("target_cloudflared_environment_invalid")
        rendered_environment = self._rendered_environment_entries(
            cloudflared, image_config
        )
        if not rendered_environment or not all(
            isinstance(item, str) and "=" in item for item in rendered_environment
        ):
            raise DeployError("target_cloudflared_environment_invalid")
        target_volumes = cloudflared.get("volumes")
        if target_volumes is not None and target_volumes != []:
            raise DeployError("target_cloudflared_mounts_invalid")
        if str(cloudflared.get("container_name") or "") != CLOUDFLARED_CONTAINER:
            raise DeployError("target_cloudflared_container_name_invalid")
        expected_security = {
            "cap_drop": ["ALL"],
            "memory": 256 * 1024 * 1024,
            "memory_reservation": 64 * 1024 * 1024,
            "pids_limit": 128,
            "privileged": False,
            "read_only": False,
            "restart": "unless-stopped",
            "security_opt": ["no-new-privileges"],
        }
        if _rendered_security_identity(cloudflared) != expected_security:
            raise DeployError("target_cloudflared_security_invalid")
        cloudflared_networks = self._actual_network_names(rendered, cloudflared)
        if set(cloudflared_networks.values()) != {PUBLIC_INGRESS_NETWORK}:
            raise DeployError("target_cloudflared_networks_invalid")
        public_key = next(
            key
            for key, name in cloudflared_networks.items()
            if name == PUBLIC_INGRESS_NETWORK
        )
        raw_service_networks = dict(cloudflared.get("networks") or {})
        public_attachment = dict(raw_service_networks.get(public_key) or {})
        if public_attachment.get("ipv4_address") != PUBLIC_INGRESS_CLOUDFLARED_IPV4:
            raise DeployError("target_cloudflared_ipv4_invalid")
        api_environment = _environment_mapping(api.get("environment"))
        if (
            api_environment.get("EA_TRUST_PROXY_HEADERS") != "1"
            or api_environment.get("EA_TRUSTED_PROXY_CIDRS")
            != PUBLIC_INGRESS_TRUSTED_PROXY_CIDR
        ):
            raise DeployError("target_api_trusted_proxy_invalid")
        api_networks = self._actual_network_names(rendered, api)
        if api_networks != {
            "default": DEFAULT_NETWORK,
            "public_ingress": PUBLIC_INGRESS_NETWORK,
        }:
            raise DeployError("target_api_networks_invalid")
        api_public_key = "public_ingress"
        raw_api_networks = dict(api.get("networks") or {})
        api_public_attachment = raw_api_networks.get(api_public_key)
        if (
            not isinstance(api_public_attachment, Mapping)
            or dict(api_public_attachment).get("ipv4_address")
            != PUBLIC_INGRESS_API_IPV4
        ):
            raise DeployError("target_api_public_ingress_ipv4_invalid")
        networks = dict(rendered.get("networks") or {})
        expected_networks = {
            "default": {"name": DEFAULT_NETWORK, "ipam": {}},
            "public_ingress": {
                "name": PUBLIC_INGRESS_NETWORK,
                "ipam": {
                    "config": [
                        {
                            "subnet": PUBLIC_INGRESS_SUBNET,
                            "gateway": PUBLIC_INGRESS_GATEWAY,
                        }
                    ]
                },
            },
        }
        if networks != expected_networks:
            raise DeployError("target_public_ingress_ipam_invalid")
        self._record_check(
            "target_compose",
            "pass",
            compose_files=list(self.target_compose_files),
            compose_input_seals=input_seals,
            cloudflared_image=PINNED_CLOUDFLARED_IMAGE,
            cloudflared_image_id=image["image_id"],
            cloudflared_process_config_sha256=_process_config_identity(
                expected_process
            ),
            cloudflared_environment_identity=_environment_identity(
                rendered_environment
            ),
            cloudflared_mount_count=0,
            public_ingress_network=PUBLIC_INGRESS_NETWORK,
            cloudflared_ipv4=PUBLIC_INGRESS_CLOUDFLARED_IPV4,
            api_ipv4=PUBLIC_INGRESS_API_IPV4,
            trusted_proxy_cidr=PUBLIC_INGRESS_TRUSTED_PROXY_CIDR,
        )
        return rendered

    def _inspect_network(self, name: str) -> dict[str, Any]:
        completed = self._run(["docker", "network", "inspect", name])
        try:
            payload = json.loads(completed.stdout)
        except ValueError as exc:
            raise DeployError(f"public_ingress_network_inspect_invalid:{name}") from exc
        if (
            not isinstance(payload, list)
            or len(payload) != 1
            or not isinstance(payload[0], dict)
        ):
            raise DeployError(f"public_ingress_network_inspect_invalid:{name}")
        return dict(payload[0])

    def _network_endpoint_identity(
        self,
        *,
        name: str,
        endpoint: Mapping[str, Any],
        container_id: str,
        expected_aliases: set[str],
    ) -> dict[str, object]:
        network = self._inspect_network(name)
        network_id = str(endpoint.get("NetworkID") or "")
        ipv4 = str(endpoint.get("IPAddress") or "")
        aliases_value = endpoint.get("Aliases")
        aliases = (
            sorted({str(item) for item in aliases_value})
            if isinstance(aliases_value, list)
            and all(isinstance(item, str) and item for item in aliases_value)
            else []
        )
        if (
            not network_id
            or not ipv4
            or str(network.get("Id") or "") != network_id
            or str(network.get("Name") or "") != name
            or set(aliases) != expected_aliases
        ):
            raise DeployError("prior_cloudflared_network_identity_invalid")
        driver = str(network.get("Driver") or "")
        ipam = dict(network.get("IPAM") or {})
        ipam_driver = str(ipam.get("Driver") or "")
        ipam_config = list(ipam.get("Config") or [])
        if (
            not driver
            or not ipam_driver
            or not ipam_config
            or not all(isinstance(item, dict) for item in ipam_config)
        ):
            raise DeployError("prior_cloudflared_network_identity_invalid")
        containers = dict(network.get("Containers") or {})
        membership = containers.get(container_id)
        if not isinstance(membership, dict):
            raise DeployError("prior_cloudflared_network_membership_invalid")
        member_ipv4 = str(membership.get("IPv4Address") or "").split("/", 1)[0]
        if (
            str(membership.get("Name") or "") != CLOUDFLARED_CONTAINER
            or member_ipv4 != ipv4
        ):
            raise DeployError("prior_cloudflared_network_membership_invalid")
        return {
            "name": name,
            "network_id": network_id,
            "driver": driver,
            "ipam_driver": ipam_driver,
            "ipam_config": ipam_config,
            "internal": bool(network.get("Internal")),
            "attachable": bool(network.get("Attachable")),
            "ipv4_address": ipv4,
            "aliases": aliases,
        }

    def _validate_api_runtime_posture(
        self, baseline: Mapping[str, Any]
    ) -> None:
        api = self._inspect_container(API_SERVICE)
        self._require_compose_identity(
            api, service=API_SERVICE, reason_prefix="public_ingress_api"
        )
        config = dict(api.get("Config") or {})
        environment = _environment_mapping(config.get("Env"))
        if (
            environment.get("EA_TRUST_PROXY_HEADERS") != "1"
            or environment.get("EA_TRUSTED_PROXY_CIDRS")
            != PUBLIC_INGRESS_TRUSTED_PROXY_CIDR
            or environment.get("EA_SOURCE_REVISION") != self.source_revision
        ):
            raise DeployError("public_ingress_api_runtime_trust_mismatch")
        attachments = dict(
            dict(api.get("NetworkSettings") or {}).get("Networks") or {}
        )
        if set(attachments) != {DEFAULT_NETWORK, PUBLIC_INGRESS_NETWORK}:
            raise DeployError("public_ingress_api_runtime_networks_invalid")
        endpoint = attachments.get(PUBLIC_INGRESS_NETWORK)
        if (
            not isinstance(endpoint, dict)
            or not str(endpoint.get("NetworkID") or "")
            or str(endpoint.get("IPAddress") or "") != PUBLIC_INGRESS_API_IPV4
        ):
            raise DeployError("public_ingress_api_runtime_network_missing")
        network = self._inspect_network(PUBLIC_INGRESS_NETWORK)
        if str(network.get("Name") or "") != PUBLIC_INGRESS_NETWORK:
            raise DeployError("public_ingress_network_name_mismatch")
        ipam = list(dict(network.get("IPAM") or {}).get("Config") or [])
        if len(ipam) != 1 or not isinstance(ipam[0], dict):
            raise DeployError("public_ingress_runtime_ipam_invalid")
        if (
            str(network.get("Driver") or "") != "bridge"
            or str(dict(network.get("IPAM") or {}).get("Driver") or "")
            != "default"
            or ipam
            != [
                {
                    "Subnet": PUBLIC_INGRESS_SUBNET,
                    "Gateway": PUBLIC_INGRESS_GATEWAY,
                }
            ]
            or bool(network.get("Internal"))
            or bool(network.get("Attachable"))
            or str(network.get("Id") or "") != str(endpoint.get("NetworkID") or "")
        ):
            raise DeployError("public_ingress_runtime_ipam_invalid")
        api_container_id = str(api.get("Id") or "")
        api_membership = dict(network.get("Containers") or {}).get(api_container_id)
        if not isinstance(api_membership, dict) or (
            str(api_membership.get("Name") or "") != API_SERVICE
            or str(api_membership.get("IPv4Address") or "").split("/", 1)[0]
            != PUBLIC_INGRESS_API_IPV4
        ):
            raise DeployError("public_ingress_api_runtime_membership_invalid")
        baseline_container_id = str(
            dict(baseline.get("container") or {}).get("id") or ""
        )
        expected_memberships = {
            api_container_id: {
                "Name": API_SERVICE,
                "IPv4Address": f"{PUBLIC_INGRESS_API_IPV4}/29",
                "IPv6Address": "",
            }
        }
        raw_memberships = dict(network.get("Containers") or {})
        if baseline_container_id in raw_memberships:
            expected_memberships[baseline_container_id] = {
                "Name": CLOUDFLARED_CONTAINER,
                "IPv4Address": f"{PUBLIC_INGRESS_CLOUDFLARED_IPV4}/29",
                "IPv6Address": "",
            }
        normalized_memberships = {
            str(container_id): {
                "Name": str(dict(raw).get("Name") or ""),
                "IPv4Address": str(dict(raw).get("IPv4Address") or ""),
                "IPv6Address": str(dict(raw).get("IPv6Address") or ""),
            }
            for container_id, raw in raw_memberships.items()
            if isinstance(raw, Mapping)
        }
        if (
            len(normalized_memberships) != len(raw_memberships)
            or normalized_memberships != expected_memberships
        ):
            raise DeployError("public_ingress_cloudflared_ipv4_not_available")
        self._record_check(
            "api_runtime_public_ingress",
            "pass",
            network_id=str(network.get("Id") or ""),
            api_ipv4=PUBLIC_INGRESS_API_IPV4,
            trusted_proxy_cidr=PUBLIC_INGRESS_TRUSTED_PROXY_CIDR,
            source_revision=self.source_revision,
            cloudflared_ipv4_owner=(
                {
                    "container_id": baseline_container_id,
                    "name": CLOUDFLARED_CONTAINER,
                }
                if baseline_container_id in raw_memberships
                else None
            ),
        )

    def _verify_public_origin(self) -> dict[str, Any]:
        evidence: dict[str, Any] = {}
        for probe in PUBLIC_PROBES:
            url = f"{self.public_origin}{probe.path}"
            parsed = urllib.parse.urlsplit(url)
            if parsed.scheme != "https" or parsed.query or parsed.fragment:
                raise DeployError("public_ingress_probe_url_invalid")
            for method in ("GET", "HEAD"):
                response = self.http_no_redirect(
                    url, self.request_timeout_seconds, method, ""
                )
                if response.status != 200:
                    raise DeployError(
                        f"public_ingress_probe_status_invalid:{probe.label}:{method}"
                    )
                if response.source_revision != self.source_revision:
                    raise DeployError(
                        f"public_ingress_probe_revision_mismatch:{probe.label}:{method}"
                    )
                headers = {
                    str(key).casefold(): str(value)
                    for key, value in dict(response.headers or {}).items()
                }
                if headers.get("location"):
                    raise DeployError(
                        f"public_ingress_probe_redirected:{probe.label}:{method}"
                    )
                media_type = response.content_type.partition(";")[0].strip().lower()
                if media_type not in probe.media_types:
                    raise DeployError(
                        f"public_ingress_probe_media_type_invalid:{probe.label}:{method}"
                    )
                if method == "HEAD" and response.body:
                    raise DeployError(
                        f"public_ingress_probe_head_body_invalid:{probe.label}"
                    )
                if method == "GET" and not response.body:
                    raise DeployError(
                        f"public_ingress_probe_body_missing:{probe.label}"
                    )
                if method == "GET" and probe.json_revision_field:
                    payload = _json_object(
                        response.body.decode("utf-8"),
                        reason="public_ingress_version_json_invalid",
                    )
                    if payload.get(probe.json_revision_field) != self.source_revision:
                        raise DeployError("public_ingress_version_revision_mismatch")
                evidence[f"{probe.label}_{method.lower()}"] = {
                    "method": method,
                    "path": probe.path,
                    "status": response.status,
                    "content_type": response.content_type,
                    "source_revision": response.source_revision,
                    "body_bytes": len(response.body),
                    "body_sha256": _sha256(response.body),
                }
        self._record_check(
            "public_origin_get_head",
            "pass",
            origin=self.public_origin,
            request_count=len(evidence),
            source_revision=self.source_revision,
            probes=evidence,
        )
        return evidence

    def preflight(self) -> dict[str, Any]:
        self._write_receipt()
        if not (self.root / ".env").is_file():
            raise DeployError("env_file_missing")
        self._git_source_preflight()
        self._detect_compose()
        target_input_seals = self._capture_compose_input_seals(
            root=self.root,
            files=self.target_compose_files,
        )
        baseline = self._capture_cloudflared_baseline()
        self._validate_target_compose(
            expected_input_seals=target_input_seals,
        )
        try:
            self._validate_api_runtime_posture(baseline)
        except DeployError as exc:
            self.receipt["coordinator"] = {
                "status": "deny",
                "reason": "joint_api_ingress_atomicity_unproven",
                "api_runtime_posture": str(exc),
            }
            self.receipt["status"] = "coordinator_required"
            self._write_receipt()
            raise DeployError("joint_api_ingress_coordinator_required") from exc
        self.receipt["baseline"] = {
            "path": str(self.baseline_path),
            "sha256": _sha256(self.baseline_path.read_bytes()),
            "contains_environment_values": False,
            "contains_tunnel_token": False,
        }
        self.receipt["status"] = "preflight_pass_coordinator_required"
        self._write_receipt()
        return {"baseline": baseline, "receipt": self.receipt}

    def run(
        self, *, preflight_only: bool = False, verify_public_only: bool = False
    ) -> dict[str, Any]:
        self._acquire_lock()
        try:
            if verify_public_only:
                self._write_receipt()
                self._git_source_preflight()
                evidence = self._verify_public_origin()
                self.receipt["status"] = "public_verification_pass"
                self.receipt["completed_at"] = _utc_now()
                self._write_receipt()
                return {"evidence": evidence, "receipt": self.receipt}
            context = self.preflight()
            if preflight_only:
                self.receipt["completed_at"] = _utc_now()
                self._write_receipt()
                return context
            self.receipt["status"] = "coordinator_required"
            self.receipt["coordinator"] = {
                "status": "deny",
                "reason": "standalone_cloudflared_mutation_not_supported",
                "joint_api_ingress_atomicity_proven": False,
                "mutation_attempted": False,
                "rollback_claimed": False,
            }
            self.receipt["completed_at"] = _utc_now()
            self._write_receipt()
            raise DeployError("public_ingress_reconciliation_coordinator_required")
        except (Exception, KeyboardInterrupt) as exc:
            if self.receipt.get("status") not in {
                "coordinator_required",
                "public_verification_pass",
            }:
                self.receipt["status"] = "preflight_failed"
            self.receipt["failure"] = {
                "at": _utc_now(),
                "reason": str(exc) or type(exc).__name__,
                "type": type(exc).__name__,
                "mutation_attempted": False,
            }
            self.receipt["completed_at"] = _utc_now()
            self._write_receipt()
            if isinstance(exc, (DeployError, KeyboardInterrupt)):
                raise
            raise DeployError(str(exc) or type(exc).__name__) from exc
        finally:
            self._release_lock()


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Preflight EA public ingress and deny standalone mutation until a "
            "joint coordinator executes the atomic transaction."
        )
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--preflight-only", action="store_true")
    mode.add_argument("--verify-public-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        lane = PublicIngressReconciliationLane()
        result = lane.run(
            preflight_only=bool(args.preflight_only),
            verify_public_only=bool(args.verify_public_only),
        )
    except DeployError as exc:
        print(
            json.dumps(
                {"status": "fail", "error": str(exc)},
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        return 2
    print(
        json.dumps(
            {
                "status": str(dict(result.get("receipt") or {}).get("status") or "pass"),
                "mutation_attempted": False,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
