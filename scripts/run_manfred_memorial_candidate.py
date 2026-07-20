#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import errno
import fcntl
import hashlib
import json
import os
import secrets
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.prepare_manfred_memorial_candidate import (  # noqa: E402
    CANDIDATE_RELEASE_AUTHORITY_DIRNAME,
    PROPERTY_AUTHORITY_SHA256,
    PROPERTY_PUBLICATION_AUTHORITY_SCHEMA,
    IMAGE_BUILD_RECEIPT_MAX_BYTES,
    MEMORIAL_SURFACE,
    RECEIPT_SCHEMA as PROJECTION_RECEIPT_SCHEMA,
    SPATIAL_SCOPE,
    SPATIAL_PROJECTION_SCHEMA,
    SPATIAL_SLUG_RE,
    _canonical_json_bytes,
    _parse_env,
    _parse_env_bytes,
    _read_private_output,
    _receipt_bytes,
    _sha256,
    _spatial_tree_snapshot,
    _tree_digest,
    _validate_candidate_release_authority_bundle,
    _validated_property_publication,
    _validate_project_name,
)
from scripts.build_manfred_memorial_image import (  # noqa: E402
    IMAGE_BUILD_AUTHORITY_BINDING_KEYS,
    RECEIPT_SCHEMA as IMAGE_BUILD_RECEIPT_SCHEMA,
    validate_build_authority_binding,
    validated_build_receipt_binding,
)
from scripts.manfred_candidate_fleet_lock import (  # noqa: E402
    hold_candidate_fleet_lock,
)
from scripts.manfred_candidate_vexp_authority import (  # noqa: E402
    DEFAULT_SENTINEL_STATE_PATH,
    CandidateAuthorityError,
    CandidateVexpMutationAuthority,
    candidate_vexp_authority,
)
from scripts.manfred_candidate_registry import (  # noqa: E402
    candidate_registry_recovery_state,
    clear_candidate_pending,
    clear_candidate_pending_exact,
    register_candidate_pending,
    register_candidate_receipt,
)
from scripts.verify_public_tour_generated_viewer_release import (  # noqa: E402
    verify_bundle as verify_spatial_bundle,
)
from scripts.verify_manfred_memorial_candidate import (  # noqa: E402
    _withdraw_contribution,
    audit_browser_surface,
    verify_candidate,
)
from scripts.verify_manfred_spatial_candidate_browser import (  # noqa: E402
    RECEIPT_SCHEMA as SPATIAL_BROWSER_RECEIPT_SCHEMA,
    audit_spatial_candidate_browser,
    validate_spatial_candidate_browser_receipt,
)


LEGACY_RECEIPT_SCHEMA_V5 = "ea.manfred_memorial_candidate_runtime.v5"
RECEIPT_SCHEMA = "ea.manfred_memorial_candidate_runtime.v6"
ROUTE_ACTIONABILITY_DIAGNOSTIC_SCHEMA = "ea.manfred_route_actionability_diagnostic.v1"
MAX_FAILURE_DIAGNOSTIC_BYTES = 8 * 1024
SPATIAL_BROWSER_RECEIPT_INVALID = "manfred_candidate_spatial_browser_receipt_invalid"
ALLOWED_ENV_KEYS = {
    "DATABASE_URL",
    "EA_API_TOKEN",
    "EA_MANFRED_COMPOSE_PROJECT",
    "EA_MANFRED_COMMIT",
    "EA_MANFRED_DEPLOYMENT_ID",
    "EA_MANFRED_ENV_FILE",
    "EA_MANFRED_HOST_PORT",
    "EA_MANFRED_IMAGE",
    "EA_MANFRED_MEMORIAL_SURFACE",
    "EA_MANFRED_POSTGRES_PASSWORD",
    "EA_MANFRED_RELEASE_ROOT",
    "EA_MANFRED_RELEASE_AUTHORITY_ROOT",
    "EA_MANFRED_RUNTIME_ROOT",
    "EA_MANFRED_SPATIAL_SCOPE",
    "EA_PUBLIC_APP_BASE_URL",
    "EA_SIGNING_SECRET",
}
FORBIDDEN_LOG_MARKERS = (
    "ImportError:",
    "ModuleNotFoundError:",
    "cannot import name",
)
LIVE_COMPOSE_PROJECT = "ea"
DOCKER_ENV_PASSTHROUGH = (
    "DOCKER_CERT_PATH",
    "DOCKER_CONFIG",
    "DOCKER_CONTEXT",
    "DOCKER_HOST",
    "DOCKER_TLS_VERIFY",
    "HOME",
    "PATH",
    "SSH_AUTH_SOCK",
    "XDG_RUNTIME_DIR",
)
EXPECTED_CANDIDATE_NETWORKS = ("backend", "ingress")
EXPECTED_CANDIDATE_VOLUMES = ("artifacts", "postgres_data", "redis_data")
EXPECTED_CANDIDATE_SERVICES = ("api", "gateway", "postgres", "redis")
CANDIDATE_COMPOSE_RELATIVE_PATH = Path(
    "deploy/manfred-memorial/docker-compose.candidate.yml"
)
CANDIDATE_COMPOSE_MAX_BYTES = 1024 * 1024
CANDIDATE_ENV_MAX_BYTES = 1024 * 1024
PROJECTION_RECEIPT_MAX_BYTES = 1024 * 1024
EXECUTION_INPUT_SCHEMA = "ea.manfred_candidate_execution_inputs.v1"
CANDIDATE_COMPOSE_DOWN_TIMEOUTS = (120, 180)
PORT_RELEASE_WAIT_SECONDS = 10.0
PORT_RELEASE_POLL_SECONDS = 0.1
INTERNAL_TRANSPORT_STATUS_MARKER = "__EA_CANDIDATE_HTTP_STATUS__="
HOST_TCP_LISTENER_TABLES = (Path("/proc/net/tcp"), Path("/proc/net/tcp6"))
HTTP_HEADER_NAME_CHARACTERS = frozenset(
    "!#$%&'*+-.^_`|~0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
)
INTERNAL_TRANSPORT_PATHS = frozenset(
    {
        "/memorial/manfred?from=ea-launch-verifier",
        "/memorials/manfred",
        "/memorials/manfred?from=ea-transport-verifier",
    }
)
RECEIPT_PATH_INVALID = "manfred_candidate_receipt_path_invalid"
RECEIPT_PARENT_INVALID = "manfred_candidate_receipt_parent_invalid"
RECEIPT_OUTPUT_EXISTS = "manfred_candidate_receipt_output_exists"
RECEIPT_ARTIFACT_INVALID = "manfred_candidate_receipt_artifact_invalid"
RECEIPT_WRITE_FAILED = "manfred_candidate_receipt_write_failed"


class GovernedSignalInterrupt(BaseException):
    def __init__(self, signum: int) -> None:
        self.signum = int(signum)
        super().__init__(f"manfred_candidate_governed_signal:{self.signum}")


@dataclass(frozen=True)
class _CreatedReceiptArtifact:
    path: Path
    device: int
    inode: int
    ctime_ns: int
    size: int


@dataclass(frozen=True)
class _SealedExecutionInputs:
    compose_descriptor: int
    environment_descriptor: int
    compose_path: Path
    environment_path: Path
    evidence: dict[str, object]


@contextlib.contextmanager
def _governed_signal_handlers():
    governed = (signal.SIGTERM, signal.SIGHUP)
    previous = {signum: signal.getsignal(signum) for signum in governed}

    def interrupt(signum: int, _frame: object) -> None:
        raise GovernedSignalInterrupt(signum)

    try:
        for signum in governed:
            signal.signal(signum, interrupt)
        yield
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


@contextlib.contextmanager
def _shield_cleanup_interrupts():
    shielded = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
    previous = {signum: signal.getsignal(signum) for signum in shielded}
    try:
        for signum in shielded:
            signal.signal(signum, signal.SIG_IGN)
        yield
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def _safe_subprocess_environment() -> dict[str, str]:
    environment = {
        "COMPOSE_ANSI": "never",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": os.environ.get("PATH") or os.defpath,
    }
    for name in DOCKER_ENV_PASSTHROUGH:
        value = str(os.environ.get(name) or "").strip()
        if value:
            environment[name] = value
    return environment


def _compose_environment(
    candidate_env: dict[str, str],
    *,
    execution_env_file: Path | None = None,
) -> dict[str, str]:
    environment = _safe_subprocess_environment()
    environment.update(candidate_env)
    if execution_env_file is not None:
        environment["EA_MANFRED_ENV_FILE"] = str(execution_env_file)
    environment.pop("COMPOSE_PROJECT_NAME", None)
    environment.pop("COMPOSE_FILE", None)
    return environment


def _run(
    argv: list[str],
    *,
    timeout: float = 300,
    environment: dict[str, str] | None = None,
) -> bytes:
    completed = subprocess.run(
        argv,
        check=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        env=dict(environment or _safe_subprocess_environment()),
    )
    return completed.stdout


def _producer_sha256(*, producer_path: Path | None = None) -> str:
    """Bind the runtime receipt to the exact reviewed candidate producer bytes."""

    path = (producer_path or Path(__file__)).expanduser()
    try:
        before = path.stat()
        raw = path.read_bytes()
        after = path.stat()
    except OSError as exc:
        raise RuntimeError("manfred_candidate_producer_metadata_invalid") from exc
    identity = lambda value: (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_nlink,
        value.st_uid,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )
    if (
        not stat.S_ISREG(before.st_mode)
        or before.st_uid != os.getuid()
        or before.st_nlink != 1
        or stat.S_IMODE(before.st_mode) & 0o022
        or identity(before) != identity(after)
    ):
        raise RuntimeError("manfred_candidate_producer_metadata_invalid")
    digest = hashlib.sha256(raw).hexdigest()
    if len(digest) != 64 or any(
        character not in "0123456789abcdef" for character in digest
    ):
        raise RuntimeError("manfred_candidate_producer_digest_invalid")
    return digest


def _run_bounded_output(
    argv: list[str],
    *,
    timeout: float,
    environment: dict[str, str],
    stdout_limit: int,
    stderr_limit: int,
    output_limit_error: str,
) -> bytes:
    with (
        tempfile.TemporaryFile() as stdout_file,
        tempfile.TemporaryFile() as stderr_file,
    ):
        completed = subprocess.run(
            argv,
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=stdout_file,
            stderr=stderr_file,
            timeout=timeout,
            env=dict(environment),
        )
        stdout_file.flush()
        stderr_file.flush()
        stdout_size = os.fstat(stdout_file.fileno()).st_size
        stderr_size = os.fstat(stderr_file.fileno()).st_size
        stdout_file.seek(0)
        stderr_file.seek(0)
        stdout = stdout_file.read(max(0, int(stdout_limit)) + 1)
        stderr = stderr_file.read(max(0, int(stderr_limit)) + 1)
    if stdout_size > stdout_limit or stderr_size > stderr_limit:
        raise RuntimeError(output_limit_error)
    if completed.returncode:
        raise subprocess.CalledProcessError(
            completed.returncode,
            argv,
            output=stdout,
            stderr=stderr,
        )
    return stdout


@contextlib.contextmanager
def _candidate_exec_timeout(
    *,
    vexp_authority: CandidateVexpMutationAuthority,
    vexp_mutation_evidence: list[dict[str, object]],
    operation: str,
    argv: list[str],
    target: str,
    timeout_seconds: float,
):
    with vexp_authority.mutation(
        "before_candidate_exec",
        minimum_validity_seconds=timeout_seconds,
    ) as lease:
        record = _begin_candidate_operation(
            vexp_mutation_evidence,
            operation=operation,
            argv=argv,
            target=target,
            authority=dict(lease.authority_evidence),
        )
        try:
            yield lease.command_timeout(timeout_seconds)
        except BaseException:
            raise
        else:
            record["runner_acknowledged"] = True


def _begin_candidate_operation(
    operations: list[dict[str, object]],
    *,
    operation: str,
    argv: list[str],
    target: str,
    authority: dict[str, object],
) -> dict[str, object]:
    if (
        not operation
        or not isinstance(argv, list)
        or not argv
        or any(
            not isinstance(argument, str)
            or not argument
            or len(argument) > 16 * 1024
            or "\x00" in argument
            for argument in argv
        )
        or not target
        or len(target) > 16 * 1024
        or "\x00" in target
    ):
        raise RuntimeError("manfred_candidate_operation_descriptor_invalid")
    record: dict[str, object] = {
        "sequence": len(operations) + 1,
        "operation": operation,
        "resource": {"argv": list(argv), "target": target},
        "runner_acknowledged": False,
        "authority": dict(authority),
    }
    operations.append(record)
    return record


def _compose_argv(
    project_name: str,
    env_file: Path,
    compose_file: Path,
    *args: str,
) -> list[str]:
    return [
        "docker",
        "compose",
        "--project-name",
        _validate_project_name(project_name),
        "--env-file",
        str(env_file),
        "--file",
        str(compose_file),
        *args,
    ]


def _json_rows(raw: bytes, *, error: str) -> list[dict[str, object]]:
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(error) from exc
    if not isinstance(payload, list) or any(
        not isinstance(row, dict) for row in payload
    ):
        raise RuntimeError(error)
    return [dict(row) for row in payload]


def _listed_values(argv: list[str]) -> list[str]:
    return sorted(
        {
            line.strip()
            for line in _run(argv, timeout=30)
            .decode("utf-8", errors="strict")
            .splitlines()
            if line.strip()
        }
    )


def _project_container_snapshot(project: str) -> list[dict[str, object]]:
    identifiers = _listed_values(
        [
            "docker",
            "container",
            "ls",
            "--all",
            "--quiet",
            "--filter",
            f"label=com.docker.compose.project={project}",
        ]
    )
    if not identifiers:
        return []
    rows = _json_rows(
        _run(["docker", "container", "inspect", *identifiers], timeout=30),
        error="manfred_candidate_container_snapshot_invalid",
    )
    snapshot: list[dict[str, object]] = []
    for row in rows:
        config = dict(row.get("Config") or {})
        labels = dict(config.get("Labels") or {})
        if str(labels.get("com.docker.compose.project") or "") != project:
            raise RuntimeError("manfred_candidate_container_project_mismatch")
        state = dict(row.get("State") or {})
        health = dict(state.get("Health") or {})
        attached_networks = dict(
            (row.get("NetworkSettings") or {}).get("Networks") or {}
        )
        networks = [
            {
                "name": str(name),
                "network_id": str(dict(value or {}).get("NetworkID") or ""),
            }
            for name, value in sorted(attached_networks.items())
        ]
        snapshot.append(
            {
                "container_id": str(row.get("Id") or ""),
                "name": str(row.get("Name") or "").lstrip("/"),
                "service": str(labels.get("com.docker.compose.service") or ""),
                "image_id": str(row.get("Image") or ""),
                "started_at": str(state.get("StartedAt") or ""),
                "running": bool(state.get("Running")),
                "status": str(state.get("Status") or ""),
                "health": str(health.get("Status") or ""),
                "networks": networks,
            }
        )
    return sorted(snapshot, key=lambda item: (str(item["service"]), str(item["name"])))


def _project_network_snapshot(project: str) -> list[dict[str, object]]:
    identifiers = _listed_values(
        [
            "docker",
            "network",
            "ls",
            "--quiet",
            "--filter",
            f"label=com.docker.compose.project={project}",
        ]
    )
    if not identifiers:
        return []
    rows = _json_rows(
        _run(["docker", "network", "inspect", *identifiers], timeout=30),
        error="manfred_candidate_network_snapshot_invalid",
    )
    snapshot: list[dict[str, object]] = []
    for row in rows:
        labels = dict(row.get("Labels") or {})
        if str(labels.get("com.docker.compose.project") or "") != project:
            raise RuntimeError("manfred_candidate_network_project_mismatch")
        snapshot.append(
            {
                "network_id": str(row.get("Id") or ""),
                "name": str(row.get("Name") or ""),
                "driver": str(row.get("Driver") or ""),
                "internal": bool(row.get("Internal")),
                "compose_network": str(labels.get("com.docker.compose.network") or ""),
            }
        )
    return sorted(snapshot, key=lambda item: str(item["name"]))


def _project_volume_snapshot(project: str) -> list[dict[str, object]]:
    names = _listed_values(
        [
            "docker",
            "volume",
            "ls",
            "--quiet",
            "--filter",
            f"label=com.docker.compose.project={project}",
        ]
    )
    if not names:
        return []
    rows = _json_rows(
        _run(["docker", "volume", "inspect", *names], timeout=30),
        error="manfred_candidate_volume_snapshot_invalid",
    )
    snapshot: list[dict[str, object]] = []
    for row in rows:
        labels = dict(row.get("Labels") or {})
        if str(labels.get("com.docker.compose.project") or "") != project:
            raise RuntimeError("manfred_candidate_volume_project_mismatch")
        snapshot.append(
            {
                "name": str(row.get("Name") or ""),
                "driver": str(row.get("Driver") or ""),
                "scope": str(row.get("Scope") or ""),
                "compose_volume": str(labels.get("com.docker.compose.volume") or ""),
            }
        )
    return sorted(snapshot, key=lambda item: str(item["name"]))


def _project_snapshot(project: str) -> dict[str, object]:
    return {
        "project": project,
        "containers": _project_container_snapshot(project),
        "networks": _project_network_snapshot(project),
        "volumes": _project_volume_snapshot(project),
    }


def _live_snapshot() -> dict[str, object]:
    return _project_snapshot(LIVE_COMPOSE_PROJECT)


def _main_api_snapshot(snapshot: dict[str, object]) -> dict[str, object]:
    rows = [
        dict(row)
        for row in list(snapshot.get("containers") or [])
        if isinstance(row, dict)
        and (
            str(row.get("service") or "") == "ea-api"
            or str(row.get("name") or "") == "ea-api"
        )
    ]
    if len(rows) != 1:
        raise RuntimeError("manfred_candidate_live_api_snapshot_invalid")
    return rows[0]


def _assert_live_healthy(snapshot: dict[str, object]) -> None:
    api = _main_api_snapshot(snapshot)
    if not api.get("running") or api.get("health") != "healthy":
        raise RuntimeError("manfred_candidate_live_runtime_unhealthy")


def _assert_live_unchanged(before: dict[str, object], after: dict[str, object]) -> None:
    if before != after:
        raise RuntimeError("manfred_candidate_live_project_changed")
    _assert_live_healthy(after)


def _assert_live_http() -> None:
    request = urllib.request.Request("http://127.0.0.1:8090/healthz", method="GET")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            if int(response.status) != 200:
                raise RuntimeError("manfred_candidate_live_health_unexpected")
    except (OSError, urllib.error.URLError) as exc:
        raise RuntimeError("manfred_candidate_live_health_unreachable") from exc


HTTP_METHODS = {"delete", "get", "head", "options", "patch", "post", "put", "trace"}
OPENAPI_RETIREMENT_POLICY_ID = "ea.openapi.safety-retirement.governed-spatial-routes.v1"
OPENAPI_RETIREMENT_ALLOWED_OPERATIONS = (
    "POST /v1/internal/governed-spatial-render/build",
    "POST /v1/internal/governed-spatial-render/compose",
)
OPENAPI_COMPATIBLE_EVOLUTION_POLICY_ID = (
    "ea.openapi.compatible-evolution.version-remote-reachability.v1"
)
OPENAPI_COMPATIBLE_EVOLUTION_ALLOWED_OPERATIONS = ("GET /version",)
MAX_OPENAPI_DOCUMENT_BYTES = 8 * 1024 * 1024
MAX_OPENAPI_SNAPSHOT_STDERR_BYTES = 1024 * 1024
CANDIDATE_OPENAPI_SNAPSHOT_SOURCE = "candidate_api_container_app.openapi"
LIVE_OPENAPI_SNAPSHOT_SOURCE = "live_api_container_app.openapi"
CANDIDATE_OPENAPI_RETIREMENT_SINGLETON_HEADERS = frozenset(
    {
        "content-security-policy",
        "content-type",
        "x-content-type-options",
        "x-correlation-id",
        "x-frame-options",
    }
)
CANDIDATE_OPENAPI_SNAPSHOT_SCRIPT = f"""
import json
import sys

from app.main import app

payload = {{
    "docs_url": app.docs_url,
    "document": app.openapi(),
    "openapi_url": app.openapi_url,
    "redoc_url": app.redoc_url,
}}
raw = json.dumps(
    payload,
    ensure_ascii=False,
    separators=(",", ":"),
    sort_keys=True,
).encode("utf-8")
if len(raw) > {MAX_OPENAPI_DOCUMENT_BYTES}:
    raise SystemExit(86)
sys.stdout.buffer.write(raw)
""".strip()

RUNTIME_PROJECTION_SCHEMA = "ea.manfred_candidate_runtime_projection.v1"
MAX_RUNTIME_PROJECTION_SNAPSHOT_BYTES = 4 * 1024 * 1024
RUNTIME_PROJECTION_SNAPSHOT_SCRIPT = r"""
import hashlib
import json
import os
import stat
import sys

ROOTS = (
    ("/data/memorial/public", "public_memorials"),
    ("/data/memorial/private", "private_memorial_profiles"),
    ("/data/memorial/archive", "memorial_archive"),
    ("/data/public_property_tours", "public_property_tours"),
    ("/data/release-authority", "release-authority"),
)

def identity(metadata):
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_nlink,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )

directory_flags = os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW
file_flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
rows = []

def walk(directory_descriptor, projected):
    before = os.fstat(directory_descriptor)
    if not stat.S_ISDIR(before.st_mode) or stat.S_IMODE(before.st_mode) != 0o550:
        raise RuntimeError("runtime_projection_directory_invalid")
    for name in sorted(os.listdir(directory_descriptor)):
        if name in {"", ".", ".."} or "/" in name:
            raise RuntimeError("runtime_projection_path_invalid")
        initial = os.stat(name, dir_fd=directory_descriptor, follow_symlinks=False)
        child_path = (*projected, name)
        if stat.S_ISDIR(initial.st_mode) and not stat.S_ISLNK(initial.st_mode):
            child = os.open(name, directory_flags, dir_fd=directory_descriptor)
            try:
                opened = os.fstat(child)
                if identity(initial) != identity(opened):
                    raise RuntimeError("runtime_projection_changed")
                walk(child, child_path)
                if identity(opened) != identity(os.fstat(child)):
                    raise RuntimeError("runtime_projection_changed")
            finally:
                os.close(child)
            final_path = os.stat(
                name,
                dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
            if identity(initial) != identity(final_path):
                raise RuntimeError("runtime_projection_changed")
            continue
        if (
            not stat.S_ISREG(initial.st_mode)
            or stat.S_ISLNK(initial.st_mode)
            or initial.st_nlink != 1
            or stat.S_IMODE(initial.st_mode) not in {0o440, 0o444}
        ):
            raise RuntimeError("runtime_projection_file_invalid")
        descriptor = os.open(name, file_flags, dir_fd=directory_descriptor)
        try:
            opened = os.fstat(descriptor)
            if identity(initial) != identity(opened):
                raise RuntimeError("runtime_projection_changed")
            digest = hashlib.sha256()
            size = 0
            while True:
                chunk = os.read(descriptor, 1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                size += len(chunk)
            if identity(opened) != identity(os.fstat(descriptor)) or size != opened.st_size:
                raise RuntimeError("runtime_projection_changed")
        finally:
            os.close(descriptor)
        final_path = os.stat(name, dir_fd=directory_descriptor, follow_symlinks=False)
        if identity(initial) != identity(final_path):
            raise RuntimeError("runtime_projection_changed")
        rows.append(
            {
                "path": "/".join(child_path),
                "sha256": digest.hexdigest(),
                "size_bytes": size,
                "mode": format(stat.S_IMODE(initial.st_mode), "03o"),
            }
        )
    if identity(before) != identity(os.fstat(directory_descriptor)):
        raise RuntimeError("runtime_projection_changed")

for source, prefix in ROOTS:
    root = os.open(source, directory_flags)
    try:
        walk(root, (prefix,))
    finally:
        os.close(root)
rows.sort(key=lambda row: row["path"])
encoded = json.dumps(rows, separators=(",", ":"), sort_keys=True).encode("utf-8")
payload = {
    "projection_sha256": hashlib.sha256(encoded).hexdigest(),
    "rows": rows,
    "schema": "ea.manfred_candidate_runtime_projection.v1",
}
sys.stdout.buffer.write(
    json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
)
""".strip()


def _resolve_openapi_ref(document: dict[str, object], ref: str) -> object:
    if not ref.startswith("#/"):
        return None
    current: object = document
    for raw_part in ref[2:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, dict) or part not in current:
            raise RuntimeError("manfred_candidate_openapi_ref_invalid")
        current = current[part]
    return current


def _canonical_openapi_value(
    value: object,
    *,
    document: dict[str, object],
    seen_refs: frozenset[str] = frozenset(),
) -> object:
    if isinstance(value, dict):
        ref = str(value.get("$ref") or "")
        canonical: dict[str, object] = {}
        for key in sorted(value):
            if key == "$ref":
                continue
            canonical[str(key)] = _canonical_openapi_value(
                value[key],
                document=document,
                seen_refs=seen_refs,
            )
        if ref:
            canonical["$ref"] = ref
            if ref not in seen_refs:
                canonical["$resolved"] = _canonical_openapi_value(
                    _resolve_openapi_ref(document, ref),
                    document=document,
                    seen_refs=seen_refs.union({ref}),
                )
        return canonical
    if isinstance(value, list):
        return [
            _canonical_openapi_value(item, document=document, seen_refs=seen_refs)
            for item in value
        ]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    raise RuntimeError("manfred_candidate_openapi_value_invalid")


def _collect_referenced_schemas(
    value: object,
    *,
    document: dict[str, object],
    names: set[str],
    visited_refs: set[str],
) -> None:
    if isinstance(value, dict):
        ref = str(value.get("$ref") or "")
        if ref and ref not in visited_refs:
            visited_refs.add(ref)
            prefix = "#/components/schemas/"
            if ref.startswith(prefix):
                names.add(
                    ref.removeprefix(prefix).replace("~1", "/").replace("~0", "~")
                )
            _collect_referenced_schemas(
                _resolve_openapi_ref(document, ref),
                document=document,
                names=names,
                visited_refs=visited_refs,
            )
        for item in value.values():
            _collect_referenced_schemas(
                item,
                document=document,
                names=names,
                visited_refs=visited_refs,
            )
    elif isinstance(value, list):
        for item in value:
            _collect_referenced_schemas(
                item,
                document=document,
                names=names,
                visited_refs=visited_refs,
            )


def _canonical_openapi_contract(document: dict[str, object]) -> dict[str, object]:
    paths_payload = dict(document.get("paths") or {})
    components = dict(document.get("components") or {})
    schemas = dict(components.get("schemas") or {})
    security_schemes = dict(components.get("securitySchemes") or {})
    root_security = document.get("security", [])
    operations: dict[str, object] = {}
    referenced_schema_names: set[str] = set()
    referenced_security_names: set[str] = set()
    for path, raw_path_item in sorted(paths_payload.items()):
        if not str(path).startswith("/") or not isinstance(raw_path_item, dict):
            raise RuntimeError("manfred_candidate_openapi_paths_invalid")
        path_parameters = list(raw_path_item.get("parameters") or [])
        for method, raw_operation in sorted(raw_path_item.items()):
            normalized_method = str(method).lower()
            if normalized_method not in HTTP_METHODS:
                continue
            if not isinstance(raw_operation, dict):
                raise RuntimeError("manfred_candidate_openapi_operation_invalid")
            effective_security = (
                raw_operation["security"]
                if "security" in raw_operation
                else root_security
            )
            for requirement in list(effective_security or []):
                if not isinstance(requirement, dict):
                    raise RuntimeError("manfred_candidate_openapi_security_invalid")
                referenced_security_names.update(str(name) for name in requirement)
            parameters = path_parameters + list(raw_operation.get("parameters") or [])
            canonical_parameters = [
                _canonical_openapi_value(item, document=document) for item in parameters
            ]
            canonical_parameters.sort(
                key=lambda item: json.dumps(
                    item, ensure_ascii=False, separators=(",", ":"), sort_keys=True
                )
            )
            contract_fields = {
                "security": effective_security,
                "parameters": parameters,
                "requestBody": raw_operation.get("requestBody"),
                "responses": raw_operation.get("responses", {}),
            }
            _collect_referenced_schemas(
                contract_fields,
                document=document,
                names=referenced_schema_names,
                visited_refs=set(),
            )
            operations[f"{normalized_method.upper()} {path}"] = {
                "security": _canonical_openapi_value(
                    effective_security, document=document
                ),
                "parameters": canonical_parameters,
                "requestBody": _canonical_openapi_value(
                    raw_operation.get("requestBody"), document=document
                ),
                "responses": _canonical_openapi_value(
                    raw_operation.get("responses", {}), document=document
                ),
            }
    if not operations:
        raise RuntimeError("manfred_candidate_openapi_operations_missing")
    missing_schemas = sorted(referenced_schema_names - set(schemas))
    missing_security = sorted(referenced_security_names - set(security_schemes))
    if missing_schemas or missing_security:
        raise RuntimeError("manfred_candidate_openapi_component_missing")
    return {
        "operations": operations,
        "schemas": {
            name: _canonical_openapi_value(schemas[name], document=document)
            for name in sorted(referenced_schema_names)
        },
        "security_schemes": {
            name: _canonical_openapi_value(security_schemes[name], document=document)
            for name in sorted(referenced_security_names)
        },
    }


def _openapi_contract_evidence(contract: dict[str, object]) -> dict[str, object]:
    operations = dict(contract.get("operations") or {})
    schemas = dict(contract.get("schemas") or {})
    security_schemes = dict(contract.get("security_schemes") or {})
    paths = sorted({key.split(" ", 1)[1] for key in operations})
    path_bytes = (
        json.dumps(paths, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        + b"\n"
    )
    contract_bytes = (
        json.dumps(
            contract,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        + b"\n"
    )
    return {
        "path_count": len(paths),
        "operation_count": len(operations),
        "schema_count": len(schemas),
        "security_scheme_count": len(security_schemes),
        "path_digest_sha256": hashlib.sha256(path_bytes).hexdigest(),
        "contract_digest_sha256": hashlib.sha256(contract_bytes).hexdigest(),
    }


def _version_openapi_evolution_preserved(
    live_operation: object,
    candidate_operation: object,
) -> bool:
    if not isinstance(live_operation, dict) or not isinstance(
        candidate_operation, dict
    ):
        return False
    live = json.loads(json.dumps(live_operation))
    candidate = json.loads(json.dumps(candidate_operation))
    try:
        live_schema = live["responses"]["200"]["content"]["application/json"]["schema"]
        candidate_schema = candidate["responses"]["200"]["content"]["application/json"][
            "schema"
        ]
    except (KeyError, TypeError):
        return False
    if (
        not isinstance(live_schema, dict)
        or not isinstance(candidate_schema, dict)
        or live_schema.get("additionalProperties") != {"type": "string"}
    ):
        return False
    additional_properties = candidate_schema.get("additionalProperties")
    if not isinstance(additional_properties, dict) or set(additional_properties) != {
        "anyOf"
    }:
        return False
    variants = additional_properties.get("anyOf")
    if not isinstance(variants, list) or len(variants) != 2:
        return False
    canonical_variants = {
        json.dumps(value, separators=(",", ":"), sort_keys=True) for value in variants
    }
    if canonical_variants != {'{"type":"boolean"}', '{"type":"string"}'}:
        return False
    candidate_schema["additionalProperties"] = {"type": "string"}
    return candidate == live


def _assert_openapi_contract_preserved(
    live: dict[str, object], candidate: dict[str, object]
) -> dict[str, object]:
    allowed_retirements = list(OPENAPI_RETIREMENT_ALLOWED_OPERATIONS)
    allowed_evolutions = list(OPENAPI_COMPATIBLE_EVOLUTION_ALLOWED_OPERATIONS)
    candidate_operations = dict(candidate.get("operations") or {})
    if any(name in candidate_operations for name in allowed_retirements):
        raise RuntimeError("manfred_candidate_openapi_contract_regression")

    counts: dict[str, int] = {}
    evolved_operations: list[str] = []
    for category, count_key in (
        ("operations", "missing_or_changed_operation_count"),
        ("schemas", "missing_or_changed_schema_count"),
        ("security_schemes", "missing_or_changed_security_scheme_count"),
    ):
        live_rows = dict(live.get(category) or {})
        candidate_rows = dict(candidate.get(category) or {})
        changed = 0
        for name, value in live_rows.items():
            if (
                category == "operations"
                and name in OPENAPI_RETIREMENT_ALLOWED_OPERATIONS
            ):
                continue
            if name in candidate_rows and candidate_rows[name] == value:
                continue
            if (
                category == "operations"
                and name == "GET /version"
                and name in candidate_rows
                and _version_openapi_evolution_preserved(
                    value,
                    candidate_rows[name],
                )
            ):
                evolved_operations.append(name)
                continue
            changed += 1
        counts[count_key] = changed
    if any(int(value) for value in counts.values()):
        raise RuntimeError("manfred_candidate_openapi_contract_regression")
    return {
        **counts,
        "retirement_policy_id": OPENAPI_RETIREMENT_POLICY_ID,
        "retirement_allowed_operations": allowed_retirements,
        "retired_operations": list(allowed_retirements),
        "retired_operation_count": len(allowed_retirements),
        "retirement_policy_exact_match": True,
        "compatible_evolution_policy_id": OPENAPI_COMPATIBLE_EVOLUTION_POLICY_ID,
        "compatible_evolution_allowed_operations": allowed_evolutions,
        "compatible_evolved_operations": sorted(set(evolved_operations)),
        "compatible_evolved_operation_count": len(set(evolved_operations)),
        "compatible_evolution_policy_exact_match": True,
        "candidate_preserves_live_contract": True,
    }


def _openapi_document(
    body: bytes,
    *,
    invalid_error: str,
    too_large_error: str,
) -> dict[str, object]:
    if len(body) > MAX_OPENAPI_DOCUMENT_BYTES:
        raise RuntimeError(too_large_error)
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(invalid_error) from exc
    if not isinstance(payload, dict):
        raise RuntimeError(invalid_error)
    return payload


def _candidate_openapi_contract_snapshot(
    compose: list[str],
    environment: dict[str, str],
    *,
    vexp_authority: CandidateVexpMutationAuthority,
    vexp_mutation_evidence: list[dict[str, object]],
) -> tuple[dict[str, object], dict[str, object]]:
    snapshot_argv = [
        *compose,
        "exec",
        "-T",
        "api",
        "python",
        "-c",
        CANDIDATE_OPENAPI_SNAPSHOT_SCRIPT,
    ]
    try:
        with _candidate_exec_timeout(
            vexp_authority=vexp_authority,
            vexp_mutation_evidence=vexp_mutation_evidence,
            operation="candidate_openapi_snapshot",
            argv=snapshot_argv,
            target="api:openapi",
            timeout_seconds=120,
        ) as timeout:
            body = _run_bounded_output(
                snapshot_argv,
                timeout=timeout,
                environment=environment,
                stdout_limit=MAX_OPENAPI_DOCUMENT_BYTES,
                stderr_limit=MAX_OPENAPI_SNAPSHOT_STDERR_BYTES,
                output_limit_error=(
                    "manfred_candidate_internal_openapi_snapshot_output_too_large"
                ),
            )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(
            "manfred_candidate_internal_openapi_snapshot_unavailable"
        ) from exc
    envelope = _openapi_document(
        body,
        invalid_error="manfred_candidate_internal_openapi_snapshot_invalid",
        too_large_error="manfred_candidate_internal_openapi_snapshot_too_large",
    )
    if (
        envelope.get("docs_url") is not None
        or envelope.get("openapi_url") is not None
        or envelope.get("redoc_url") is not None
    ):
        raise RuntimeError("manfred_candidate_internal_openapi_docs_exposed")
    document = envelope.get("document")
    if not isinstance(document, dict):
        raise RuntimeError("manfred_candidate_internal_openapi_snapshot_invalid")
    contract = _canonical_openapi_contract(document)
    return contract, {
        **_openapi_contract_evidence(contract),
        "snapshot_source": CANDIDATE_OPENAPI_SNAPSHOT_SOURCE,
        "public_docs_config_retired": True,
    }


def _spatial_projection_evidence(
    env: dict[str, str],
    *,
    projection_receipt: dict[str, object],
    release_root: Path,
    release_id: str,
) -> dict[str, object]:
    spatial_root = Path(env["EA_MANFRED_SPATIAL_RELEASE_ROOT"]).resolve()
    expected_root = (release_root / "public_property_tours").resolve()
    expected_receipt_path = (
        release_root.parent.parent / "receipts" / f"{release_id}.spatial.json"
    )
    receipt_path = Path(str(projection_receipt.get("spatial_receipt_path") or ""))
    if (
        spatial_root != expected_root
        or str(projection_receipt.get("spatial_release_root") or "")
        != str(expected_root)
        or not receipt_path.is_absolute()
        or receipt_path != expected_receipt_path
    ):
        raise RuntimeError("manfred_candidate_spatial_projection_receipt_invalid")
    try:
        receipt_bytes = _read_private_output(
            receipt_path,
            maximum=PROJECTION_RECEIPT_MAX_BYTES,
        )
        if receipt_bytes is None:  # pragma: no cover - missing_ok is false
            raise ValueError("manfred_candidate_spatial_projection_receipt_invalid")
        receipt = json.loads(receipt_bytes)
    except (OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            "manfred_candidate_spatial_projection_receipt_invalid"
        ) from exc
    if (
        not isinstance(receipt, dict)
        or _receipt_bytes(receipt) != receipt_bytes
        or receipt.get("schema") != SPATIAL_PROJECTION_SCHEMA
        or receipt.get("status") != "pass"
        or receipt.get("release_id") != release_id
        or receipt.get("public_activation_authority") is not False
        or receipt.get("spatial_release_root") != str(spatial_root)
        or projection_receipt.get("spatial_receipt_sha256") != _sha256(receipt_bytes)
    ):
        raise RuntimeError("manfred_candidate_spatial_projection_receipt_mismatch")
    included = env["EA_MANFRED_SPATIAL_HANDOFF_INCLUDED"] == "1"
    slug = env["EA_MANFRED_SPATIAL_SLUG"]
    digest = env["EA_MANFRED_SPATIAL_SHA256"]
    if (
        receipt.get("spatial_handoff_included") is not included
        or projection_receipt.get("spatial_handoff_included") is not included
        or receipt.get("candidate_handoff_authorized") is not included
        or receipt.get("slug") != slug
        or projection_receipt.get("spatial_slug") != slug
        or receipt.get("spatial_projection_sha256") != digest
        or projection_receipt.get("spatial_projection_sha256") != digest
        or projection_receipt.get("spatial_ea_public_activation_authority") is not False
    ):
        raise RuntimeError("manfred_candidate_spatial_projection_receipt_mismatch")
    try:
        observed_digest, observed_files = _tree_digest(spatial_root)
    except (OSError, ValueError) as exc:
        raise RuntimeError(
            "manfred_candidate_spatial_projection_tree_unverifiable"
        ) from exc
    observed_bytes = sum(int(row["size_bytes"]) for row in observed_files)
    if (
        observed_digest != digest
        or receipt.get("files") != observed_files
        or receipt.get("file_count") != len(observed_files)
        or receipt.get("projection_bytes") != observed_bytes
        or projection_receipt.get("spatial_file_count") != len(observed_files)
        or projection_receipt.get("spatial_projection_bytes") != observed_bytes
    ):
        raise RuntimeError("manfred_candidate_spatial_projection_tree_digest_mismatch")
    evidence: dict[str, object] = {
        "included": included,
        "slug": slug,
        "release_root": str(spatial_root),
        "projection_sha256": digest,
        "file_count": len(observed_files),
        "projection_bytes": observed_bytes,
        "receipt_path": str(receipt_path),
        "receipt_sha256": _sha256(receipt_bytes),
        "projection_tree_revalidated": True,
        "ea_public_activation_authority": False,
    }
    if not included:
        raise RuntimeError("manfred_candidate_spatial_handoff_required")

    asset_paths = list(receipt.get("asset_paths") or [])
    viewer_relpath = str(receipt.get("viewer_relpath") or "")
    proof_relpath = str(receipt.get("proof_relpath") or "")
    upstream_authority = dict(receipt.get("upstream_publication_authority") or {})
    authority_bytes = _canonical_json_bytes(upstream_authority)
    authority_sha256 = receipt.get("upstream_publication_authority_sha256")
    upstream_package_sha256 = receipt.get("upstream_package_sha256")
    upstream_tour_sha256 = receipt.get("upstream_tour_manifest_sha256")
    pre_authority_sha256 = receipt.get("pre_authority_manifest_canonical_sha256")
    expected_paths = {f"{slug}/tour.json", *(f"{slug}/{path}" for path in asset_paths)}
    if (
        len(asset_paths) != 5
        or len(observed_files) != 6
        or any(
            type(value) is not str
            for value in (
                authority_sha256,
                upstream_package_sha256,
                upstream_tour_sha256,
                pre_authority_sha256,
            )
        )
        or {str(row.get("path") or "") for row in observed_files} != expected_paths
        or upstream_authority.get("schema") != PROPERTY_PUBLICATION_AUTHORITY_SCHEMA
        or upstream_authority.get("status") != "authorized"
        or upstream_authority.get("public_activation_authority") is not True
        or receipt.get("upstream_public_activation_authority") is not True
        or projection_receipt.get("spatial_upstream_public_activation_authority")
        is not True
        or _sha256(authority_bytes) != authority_sha256
        or authority_sha256 != PROPERTY_AUTHORITY_SHA256
    ):
        raise RuntimeError("manfred_candidate_spatial_projection_contract_invalid")
    bundle = spatial_root / slug
    review_evidence = receipt.get("review_evidence")
    if not isinstance(review_evidence, dict) or set(review_evidence) != {
        "exact_viewer_browser",
        "flagship_final",
    }:
        raise RuntimeError("manfred_candidate_spatial_review_evidence_invalid")
    review_paths: dict[str, Path] = {}
    for name in ("flagship_final", "exact_viewer_browser"):
        row = review_evidence.get(name)
        if not isinstance(row, dict) or type(row.get("source_path")) is not str:
            raise RuntimeError("manfred_candidate_spatial_review_evidence_invalid")
        raw_path = str(row["source_path"])
        normalized_path = Path(
            os.path.abspath(os.fspath(Path(raw_path).expanduser()))
        )
        if not Path(raw_path).is_absolute() or str(normalized_path) != raw_path:
            raise RuntimeError("manfred_candidate_spatial_review_evidence_invalid")
        review_paths[name] = normalized_path
    try:
        snapshot = _spatial_tree_snapshot(bundle, require_sanitized_modes=False)
        validated = _validated_property_publication(
            snapshot=snapshot,
            authority_bytes=authority_bytes,
            target_origin=env["EA_PUBLIC_APP_BASE_URL"],
            final_review_receipt_path=review_paths["flagship_final"],
            browser_review_receipt_path=review_paths["exact_viewer_browser"],
        )
    except (OSError, ValueError) as exc:
        raise RuntimeError(
            "manfred_candidate_spatial_authority_binding_invalid"
        ) from exc
    if (
        validated.get("slug") != slug
        or validated.get("asset_paths") != asset_paths
        or validated.get("viewer_relpath") != viewer_relpath
        or validated.get("proof_relpath") != proof_relpath
        or validated.get("route_labels") != list(receipt.get("route_labels") or [])
        or validated.get("upstream_publication_authority_sha256") != authority_sha256
        or validated.get("upstream_package_sha256") != upstream_package_sha256
        or validated.get("upstream_tour_manifest_sha256") != upstream_tour_sha256
        or validated.get("pre_authority_manifest_canonical_sha256")
        != pre_authority_sha256
        or validated.get("review_evidence") != receipt.get("review_evidence")
    ):
        raise RuntimeError("manfred_candidate_spatial_authority_binding_invalid")
    verifier_receipt = verify_spatial_bundle(bundle, slug=slug)
    if (
        verifier_receipt.get("pass") is not True
        or dict(verifier_receipt.get("checks") or {}).get("binding_count") != 5
    ):
        raise RuntimeError("manfred_candidate_spatial_release_verifier_blocked")
    evidence.update(
        {
            "asset_paths": asset_paths,
            "viewer_relpath": viewer_relpath,
            "proof_relpath": proof_relpath,
            "route_labels": validated["route_labels"],
            "upstream_publication_authority_sha256": authority_sha256,
            "upstream_package_sha256": upstream_package_sha256,
            "upstream_tour_manifest_sha256": upstream_tour_sha256,
            "pre_authority_manifest_canonical_sha256": pre_authority_sha256,
            "upstream_public_activation_authority": True,
            "local_release_verifier": verifier_receipt,
        }
    )
    return evidence


def _projection_evidence(env: dict[str, str]) -> dict[str, object]:
    release_root = Path(env["EA_MANFRED_RELEASE_ROOT"]).resolve()
    if release_root.is_symlink() or not release_root.is_dir():
        raise RuntimeError("manfred_candidate_release_root_invalid")
    release_id = release_root.name
    receipt_path = release_root.parent.parent / "receipts" / f"{release_id}.json"
    try:
        receipt_bytes = _read_private_output(
            receipt_path,
            maximum=PROJECTION_RECEIPT_MAX_BYTES,
        )
        if receipt_bytes is None:  # pragma: no cover - missing_ok is false
            raise ValueError("manfred_candidate_projection_receipt_invalid")
        payload = json.loads(receipt_bytes)
    except (OSError, ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RuntimeError("manfred_candidate_projection_receipt_invalid") from exc
    if not isinstance(payload, dict) or _receipt_bytes(payload) != receipt_bytes:
        raise RuntimeError("manfred_candidate_projection_receipt_mismatch")
    raw_digest = payload.get("projection_sha256")
    raw_commit = payload.get("commit")
    raw_image = payload.get("image")
    raw_image_id = payload.get("image_id")
    if any(
        type(value) is not str
        for value in (raw_digest, raw_commit, raw_image, raw_image_id)
    ):
        raise RuntimeError("manfred_candidate_projection_receipt_mismatch")
    digest = raw_digest
    commit = raw_commit
    image = raw_image
    image_id = raw_image_id
    try:
        image_build_authority_binding = validate_build_authority_binding(
            payload.get("image_build_authority_binding"),
            commit=commit,
            image_tag=image,
            image_id=image_id,
        )
        build_receipt_path = Path(
            str(image_build_authority_binding["receipt_path"])
        )
        build_receipt_bytes = _read_private_output(
            build_receipt_path,
            maximum=IMAGE_BUILD_RECEIPT_MAX_BYTES,
        )
        if (
            build_receipt_bytes is None
            or hashlib.sha256(build_receipt_bytes).hexdigest()
            != image_build_authority_binding["receipt_sha256"]
            or validated_build_receipt_binding(
                build_receipt_bytes,
                receipt_path=build_receipt_path,
                commit=commit,
                image_tag=image,
                image_id=image_id,
            )
            != image_build_authority_binding
        ):
            raise RuntimeError(
                "manfred_candidate_image_build_authority_binding_invalid"
            )
    except (OSError, RuntimeError, ValueError) as exc:
        raise RuntimeError(
            "manfred_candidate_image_build_authority_binding_invalid"
        ) from exc
    try:
        operator_gid = int(payload.get("projection_operator_gid"))
    except (TypeError, ValueError):
        operator_gid = -1
    if (
        payload.get("schema") != PROJECTION_RECEIPT_SCHEMA
        or payload.get("status") != "pass"
        or str(payload.get("release_id") or "") != release_id
        or str(payload.get("release_root") or "") != str(release_root)
        or image != env["EA_MANFRED_IMAGE"]
        or not image
        or any(character.isspace() for character in image)
        or len(commit) != 40
        or commit != commit.lower()
        or any(character not in "0123456789abcdef" for character in commit)
        or not image_id.startswith("sha256:")
        or len(image_id) != 71
        or any(character not in "0123456789abcdef" for character in image_id[7:])
        or str(payload.get("compose_project") or "")
        != env["EA_MANFRED_COMPOSE_PROJECT"]
        or operator_gid not in {os.getgid(), *os.getgroups()}
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
        or env["EA_MANFRED_COMMIT"] != commit
        or env["EA_MANFRED_DEPLOYMENT_ID"]
        != f"{env['EA_MANFRED_COMPOSE_PROJECT']}-{commit[:12]}"
        or env["EA_MANFRED_MEMORIAL_SURFACE"] != MEMORIAL_SURFACE
        or env["EA_MANFRED_SPATIAL_SCOPE"] != SPATIAL_SCOPE
        or payload.get("memorial_surface") != MEMORIAL_SURFACE
        or payload.get("spatial_scope") != SPATIAL_SCOPE
        or payload.get("public_property_tours_packaged") is not False
        or payload.get("memorial_spatial_receipt_generated") is not False
    ):
        raise RuntimeError("manfred_candidate_projection_receipt_mismatch")
    try:
        observed_digest, observed_files = _tree_digest(release_root)
    except (OSError, ValueError) as exc:
        raise RuntimeError("manfred_candidate_projection_tree_unverifiable") from exc
    if (
        observed_digest != digest
        or int(payload.get("file_count") or -1) != len(observed_files)
        or int(payload.get("projection_bytes") or -1)
        != sum(int(row["size_bytes"]) for row in observed_files)
    ):
        raise RuntimeError("manfred_candidate_projection_tree_digest_mismatch")
    if any(
        str(row.get("path") or "").startswith("public_property_tours/")
        for row in observed_files
    ) or (release_root / "public_property_tours").exists():
        raise RuntimeError("manfred_candidate_spatial_projection_forbidden")
    authority_root = (release_root / CANDIDATE_RELEASE_AUTHORITY_DIRNAME).resolve()
    if Path(env["EA_MANFRED_RELEASE_AUTHORITY_ROOT"]).resolve() != authority_root:
        raise RuntimeError("manfred_candidate_release_authority_root_mismatch")
    try:
        release_authority = _validate_candidate_release_authority_bundle(
            authority_root,
            expected_commit=commit,
            expected_image_id=image_id,
            expected_project_name=env["EA_MANFRED_COMPOSE_PROJECT"],
            expected_public_origin=env["EA_PUBLIC_APP_BASE_URL"],
        )
    except (OSError, ValueError) as exc:
        raise RuntimeError("manfred_candidate_release_authority_invalid") from exc
    return {
        "release_id": release_id,
        "release_root": str(release_root),
        "projection_sha256": digest,
        "projection_files": observed_files,
        "projection_file_count": len(observed_files),
        "projection_bytes": sum(int(row["size_bytes"]) for row in observed_files),
        "projection_commit": commit,
        "prepared_image_locator": image,
        "prepared_image_id": image_id,
        "image_build_authority_binding": image_build_authority_binding,
        "projection_tree_revalidated": True,
        "memorial_surface": MEMORIAL_SURFACE,
        "spatial_scope": SPATIAL_SCOPE,
        "public_property_tours_packaged": False,
        "memorial_spatial_receipt_generated": False,
        "release_authority": release_authority,
    }


def _inspect_image(identifier: str) -> dict[str, object]:
    rows = _json_rows(
        _run(["docker", "image", "inspect", identifier], timeout=30),
        error="manfred_candidate_image_inspection_invalid",
    )
    if len(rows) != 1:
        raise RuntimeError("manfred_candidate_image_inspection_invalid")
    row = rows[0]
    labels = dict((row.get("Config") or {}).get("Labels") or {})
    return {
        "image_id": str(row.get("Id") or ""),
        "revision_label": str(labels.get("org.opencontainers.image.revision") or ""),
    }


def _assert_prepared_image_locator(projection: dict[str, object]) -> dict[str, object]:
    locator = str(projection.get("prepared_image_locator") or "")
    expected_id = str(projection.get("prepared_image_id") or "")
    expected_commit = str(projection.get("projection_commit") or "")
    inspection = _inspect_image(locator)
    if inspection != {
        "image_id": expected_id,
        "revision_label": expected_commit,
    }:
        raise RuntimeError("manfred_candidate_image_locator_retargeted")
    return {
        "locator": locator,
        "resolved_image_id": expected_id,
        "revision_label": expected_commit,
        "used_for_attestation_only": True,
        "consumed_by_compose": False,
    }


def _compose_service_container_id(
    compose: list[str],
    environment: dict[str, str],
    service: str,
) -> str:
    values = [
        line.strip()
        for line in _run(
            [*compose, "ps", "-q", service],
            timeout=30,
            environment=environment,
        )
        .decode("ascii", errors="strict")
        .splitlines()
        if line.strip()
    ]
    if len(values) != 1:
        raise RuntimeError("manfred_candidate_service_container_invalid")
    return values[0]


def _candidate_container_image_evidence(
    *,
    compose: list[str],
    environment: dict[str, str],
    project: str,
    projection: dict[str, object],
) -> dict[str, object]:
    identifiers = {
        service: _compose_service_container_id(compose, environment, service)
        for service in ("api", "gateway")
    }
    rows = _json_rows(
        _run(
            ["docker", "container", "inspect", *identifiers.values()],
            timeout=30,
        ),
        error="manfred_candidate_runtime_container_inspection_invalid",
    )
    by_service: dict[str, dict[str, str]] = {}
    expected_id = str(projection.get("prepared_image_id") or "")
    for row in rows:
        labels = dict((row.get("Config") or {}).get("Labels") or {})
        service = str(labels.get("com.docker.compose.service") or "")
        if (
            service not in identifiers
            or str(labels.get("com.docker.compose.project") or "") != project
            or str(row.get("Id") or "") != identifiers[service]
            or str(row.get("Image") or "") != expected_id
        ):
            raise RuntimeError("manfred_candidate_runtime_container_image_mismatch")
        by_service[service] = {
            "container_id": identifiers[service],
            "image_id": str(row.get("Image") or ""),
        }
    if set(by_service) != {"api", "gateway"}:
        raise RuntimeError("manfred_candidate_runtime_container_image_mismatch")
    image_inspection = _inspect_image(expected_id)
    if image_inspection != {
        "image_id": expected_id,
        "revision_label": str(projection.get("projection_commit") or ""),
    }:
        raise RuntimeError("manfred_candidate_runtime_image_revision_mismatch")
    return {
        "api": by_service["api"],
        "gateway": by_service["gateway"],
        "prepared_image_id": expected_id,
        "revision_label": image_inspection["revision_label"],
        "all_match_prepared_image": True,
    }


def _docker_environment_map(value: object, *, error: str) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, list):
        raise RuntimeError(error)
    environment: dict[str, str] = {}
    for raw in value:
        if not isinstance(raw, str):
            raise RuntimeError(error)
        name, separator, content = raw.partition("=")
        if not separator or not name or name in environment:
            raise RuntimeError(error)
        environment[name] = content
    return environment


def _wait_for_candidate_api_healthy(
    *,
    compose: list[str],
    environment: dict[str, str],
    expected_container_id: str,
    wait_seconds: int,
) -> None:
    deadline = time.monotonic() + max(1, int(wait_seconds))
    while True:
        container_id = _compose_service_container_id(compose, environment, "api")
        if container_id != expected_container_id:
            raise RuntimeError("manfred_candidate_restart_recreated_container")
        rows = _json_rows(
            _run(
                ["docker", "container", "inspect", container_id],
                timeout=30,
            ),
            error="manfred_candidate_restart_health_inspection_invalid",
        )
        if len(rows) != 1 or str(rows[0].get("Id") or "") != container_id:
            raise RuntimeError("manfred_candidate_restart_health_inspection_invalid")
        state = dict(rows[0].get("State") or {})
        health = dict(state.get("Health") or {})
        health_status = str(health.get("Status") or "")
        if state.get("Running") is True and health_status == "healthy":
            return
        if state.get("Running") is not True or health_status not in {"starting"}:
            raise RuntimeError("manfred_candidate_restart_health_invalid")
        if time.monotonic() >= deadline:
            raise RuntimeError("manfred_candidate_restart_health_timeout")
        time.sleep(1)


def _candidate_api_runtime_posture(
    *,
    compose: list[str],
    environment: dict[str, str],
    candidate_env: dict[str, str],
    project: str,
    projection: dict[str, object],
    execution_environment_sha256: str,
) -> dict[str, object]:
    """Prove the exact post-launch API environment, mounts, and network."""

    container_id = _compose_service_container_id(compose, environment, "api")
    container_rows = _json_rows(
        _run(
            ["docker", "container", "inspect", container_id],
            timeout=30,
        ),
        error="manfred_candidate_runtime_posture_inspection_invalid",
    )
    image_id = str(projection.get("prepared_image_id") or "")
    image_rows = _json_rows(
        _run(["docker", "image", "inspect", image_id], timeout=30),
        error="manfred_candidate_runtime_posture_image_invalid",
    )
    if len(container_rows) != 1 or len(image_rows) != 1:
        raise RuntimeError("manfred_candidate_runtime_posture_inspection_invalid")
    row = container_rows[0]
    image_row = image_rows[0]
    config = dict(row.get("Config") or {})
    host_config = dict(row.get("HostConfig") or {})
    state = dict(row.get("State") or {})
    labels = dict(config.get("Labels") or {})
    health = dict(state.get("Health") or {})
    if (
        str(row.get("Id") or "") != container_id
        or str(row.get("Image") or "") != image_id
        or str(image_row.get("Id") or "") != image_id
        or labels.get("com.docker.compose.project") != project
        or labels.get("com.docker.compose.service") != "api"
        or config.get("User") != "10001:10001"
        or state.get("Running") is not True
        or health.get("Status") != "healthy"
        or host_config.get("ReadonlyRootfs") is not True
        or {str(value).upper() for value in list(host_config.get("CapDrop") or [])}
        != {"ALL"}
        or set(str(value) for value in list(host_config.get("SecurityOpt") or []))
        != {"no-new-privileges:true"}
    ):
        raise RuntimeError("manfred_candidate_runtime_posture_identity_invalid")

    image_environment = _docker_environment_map(
        dict(image_row.get("Config") or {}).get("Env"),
        error="manfred_candidate_runtime_posture_image_environment_invalid",
    )
    expected_environment = {
        **image_environment,
        **candidate_env,
        **_expected_candidate_api_environment(candidate_env),
    }
    actual_environment = _docker_environment_map(
        config.get("Env"),
        error="manfred_candidate_runtime_posture_environment_invalid",
    )
    provider_names = {
        name
        for name in actual_environment
        if name.endswith(
            (
                "_API_KEY",
                "_ACCESS_KEY_ID",
                "_SECRET_ACCESS_KEY",
                "_SERVICE_ACCOUNT_JSON",
            )
        )
        or name
        in {
            "AWS_SESSION_TOKEN",
            "AZURE_CLIENT_SECRET",
            "GOOGLE_APPLICATION_CREDENTIALS",
        }
    }
    if actual_environment != expected_environment or provider_names:
        raise RuntimeError("manfred_candidate_runtime_posture_environment_mismatch")

    release_root = Path(candidate_env["EA_MANFRED_RELEASE_ROOT"])
    runtime_root = Path(candidate_env["EA_MANFRED_RUNTIME_ROOT"])
    expected_mounts: dict[str, tuple[str, str, bool]] = {
        "/data/memorial/public": (
            "bind",
            str((release_root / "public_memorials").resolve()),
            False,
        ),
        "/data/memorial/private": (
            "bind",
            str((release_root / "private_memorial_profiles").resolve()),
            False,
        ),
        "/data/memorial/archive": (
            "bind",
            str((release_root / "memorial_archive").resolve()),
            False,
        ),
        "/data/memorial/public-contributions": (
            "bind",
            str((runtime_root / "public-contributions").resolve()),
            True,
        ),
        "/data/memorial/private-contributions": (
            "bind",
            str((runtime_root / "private-contributions").resolve()),
            True,
        ),
        "/data/memorial/state": (
            "bind",
            str((runtime_root / "state").resolve()),
            True,
        ),
        "/data/release-authority": (
            "bind",
            str(Path(candidate_env["EA_MANFRED_RELEASE_AUTHORITY_ROOT"]).resolve()),
            False,
        ),
        "/data/artifacts": ("volume", f"{project}_artifacts", True),
    }
    actual_mounts: dict[str, tuple[str, str, bool]] = {}
    mount_evidence: list[dict[str, object]] = []
    for raw_mount in list(row.get("Mounts") or []):
        if not isinstance(raw_mount, dict):
            raise RuntimeError("manfred_candidate_runtime_posture_mount_invalid")
        mount_type = str(raw_mount.get("Type") or "")
        destination = str(raw_mount.get("Destination") or "")
        if not destination or destination in actual_mounts:
            raise RuntimeError("manfred_candidate_runtime_posture_mount_invalid")
        identity = (
            str(raw_mount.get("Source") or "")
            if mount_type == "bind"
            else str(raw_mount.get("Name") or "")
        )
        writable = raw_mount.get("RW") is True
        actual_mounts[destination] = (mount_type, identity, writable)
        mount_evidence.append(
            {
                "destination": destination,
                "identity": identity,
                "read_only": not writable,
                "type": mount_type,
            }
        )
    if actual_mounts != expected_mounts:
        raise RuntimeError("manfred_candidate_runtime_posture_mount_mismatch")

    expected_tmpfs = {
        "/run": "rw,noexec,nosuid,nodev,mode=0755",
        "/tmp": "rw,noexec,nosuid,nodev,mode=1777",
    }
    if dict(host_config.get("Tmpfs") or {}) != expected_tmpfs:
        raise RuntimeError("manfred_candidate_runtime_posture_tmpfs_mismatch")

    networks = dict(dict(row.get("NetworkSettings") or {}).get("Networks") or {})
    expected_network = f"{project}_backend"
    if set(networks) != {expected_network}:
        raise RuntimeError("manfred_candidate_runtime_posture_network_mismatch")
    environment_bytes = json.dumps(
        actual_environment,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return {
        "schema": "ea.manfred_candidate_api_runtime_posture.v1",
        "api_container_id": container_id,
        "image_id": image_id,
        "environment_sha256": hashlib.sha256(environment_bytes).hexdigest(),
        "execution_environment_sha256": execution_environment_sha256,
        "environment_keys": sorted(actual_environment),
        "environment_exact": True,
        "provider_credentials_present": False,
        "mounts": sorted(mount_evidence, key=lambda item: str(item["destination"])),
        "mounts_exact": True,
        "tmpfs_exact": True,
        "networks": [expected_network],
        "network_exact": True,
        "ingress_attached": False,
        "read_only_rootfs": True,
        "all_capabilities_dropped": True,
        "no_new_privileges": True,
        "runtime_user": "10001:10001",
        "running_and_healthy": True,
    }


def _candidate_runtime_projection_evidence(
    *,
    compose: list[str],
    environment: dict[str, str],
    projection: dict[str, object],
    vexp_authority: CandidateVexpMutationAuthority,
    vexp_mutation_evidence: list[dict[str, object]],
) -> dict[str, object]:
    expected_files = projection.get("projection_files")
    if not isinstance(expected_files, list) or any(
        not isinstance(row, dict) for row in expected_files
    ):
        raise RuntimeError("manfred_candidate_runtime_projection_expected_invalid")
    snapshot_argv = [
        *compose,
        "exec",
        "-T",
        "api",
        "python",
        "-c",
        RUNTIME_PROJECTION_SNAPSHOT_SCRIPT,
    ]
    try:
        with _candidate_exec_timeout(
            vexp_authority=vexp_authority,
            vexp_mutation_evidence=vexp_mutation_evidence,
            operation="runtime_projection_snapshot",
            argv=snapshot_argv,
            target="api:runtime_projection",
            timeout_seconds=120,
        ) as timeout:
            raw = _run_bounded_output(
                snapshot_argv,
                timeout=timeout,
                environment=environment,
                stdout_limit=MAX_RUNTIME_PROJECTION_SNAPSHOT_BYTES,
                stderr_limit=1024 * 1024,
                output_limit_error=(
                    "manfred_candidate_runtime_projection_output_too_large"
                ),
            )
        payload = json.loads(raw)
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        subprocess.SubprocessError,
    ) as exc:
        raise RuntimeError(
            "manfred_candidate_runtime_projection_unavailable"
        ) from exc
    if not isinstance(payload, dict) or set(payload) != {
        "projection_sha256",
        "rows",
        "schema",
    }:
        raise RuntimeError("manfred_candidate_runtime_projection_invalid")
    rows = payload.get("rows")
    encoded = json.dumps(
        rows,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    projection_bytes = sum(
        int(dict(row).get("size_bytes") or 0)
        for row in rows
        if isinstance(row, dict)
    ) if isinstance(rows, list) else -1
    if (
        payload.get("schema") != RUNTIME_PROJECTION_SCHEMA
        or rows != expected_files
        or payload.get("projection_sha256") != digest
        or digest != projection.get("projection_sha256")
        or len(expected_files) != projection.get("projection_file_count")
        or projection_bytes != projection.get("projection_bytes")
    ):
        raise RuntimeError("manfred_candidate_runtime_projection_mismatch")
    return {
        "schema": RUNTIME_PROJECTION_SCHEMA,
        "projection_sha256": digest,
        "file_count": len(expected_files),
        "projection_bytes": projection_bytes,
        "mount_roots": [
            "/data/memorial/public",
            "/data/memorial/private",
            "/data/memorial/archive",
            "/data/release-authority",
        ],
        "runtime_bytes_match_prepared_projection": True,
    }


def _candidate_named_resources(project: str) -> dict[str, list[str]]:
    return {
        "containers": sorted(
            [f"{project}-{service}-1" for service in EXPECTED_CANDIDATE_SERVICES]
            + [f"{project}_{service}_1" for service in EXPECTED_CANDIDATE_SERVICES]
        ),
        "networks": [f"{project}_{name}" for name in EXPECTED_CANDIDATE_NETWORKS],
        "volumes": [f"{project}_{name}" for name in EXPECTED_CANDIDATE_VOLUMES],
    }


def _assert_loopback_port_free(port: int) -> None:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("127.0.0.1", port))
    except OSError as exc:
        raise RuntimeError("manfred_candidate_loopback_port_unavailable") from exc
    finally:
        probe.close()


def _host_tcp_listener_present(
    port: int,
    *,
    tables: tuple[Path, ...] | None = None,
) -> bool:
    selected = tables if tables is not None else HOST_TCP_LISTENER_TABLES
    if not selected:
        raise RuntimeError("manfred_candidate_listener_state_unavailable")
    expected_port = f"{int(port):04X}"
    for table in selected:
        try:
            lines = table.read_text(encoding="ascii").splitlines()
        except (OSError, UnicodeError) as exc:
            raise RuntimeError("manfred_candidate_listener_state_unavailable") from exc
        if not lines or "local_address" not in lines[0] or "st" not in lines[0]:
            raise RuntimeError("manfred_candidate_listener_state_invalid")
        for line in lines[1:]:
            if not line.strip():
                continue
            fields = line.split()
            if len(fields) < 4:
                raise RuntimeError("manfred_candidate_listener_state_invalid")
            local_address = fields[1]
            state = fields[3].upper()
            _address, separator, local_port = local_address.rpartition(":")
            if not separator or len(local_port) != 4:
                raise RuntimeError("manfred_candidate_listener_state_invalid")
            try:
                int(local_port, 16)
                int(state, 16)
            except ValueError as exc:
                raise RuntimeError("manfred_candidate_listener_state_invalid") from exc
            if state == "0A" and local_port.upper() == expected_port:
                return True
    return False


def _assert_loopback_port_not_listening(port: int) -> None:
    # Recovery proves that no service is accepting traffic. A bind probe is
    # intentionally stricter and can fail while closed candidate connections
    # remain in TCP TIME_WAIT even after every Compose resource is gone.
    if _host_tcp_listener_present(port):
        raise RuntimeError("manfred_candidate_loopback_port_still_listening")
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.settimeout(0.25)
        result = probe.connect_ex(("127.0.0.1", port))
        if result != errno.ECONNREFUSED:
            raise RuntimeError("manfred_candidate_loopback_port_still_listening")
    finally:
        probe.close()


def _wait_for_loopback_port_not_listening(
    port: int,
    *,
    timeout_seconds: float = PORT_RELEASE_WAIT_SECONDS,
    poll_seconds: float = PORT_RELEASE_POLL_SECONDS,
) -> None:
    deadline = time.monotonic() + max(0.0, float(timeout_seconds))
    interval = max(0.01, float(poll_seconds))
    while True:
        try:
            _assert_loopback_port_not_listening(port)
            return
        except RuntimeError:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise
            time.sleep(min(interval, remaining))


@contextlib.contextmanager
def _hold_host_lock(
    *,
    lock_path: Path,
    unavailable_error: str,
    invalid_error: str,
    held_error: str,
    evidence: dict[str, object],
):
    flags = os.O_CREAT | os.O_RDWR | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        raise RuntimeError(unavailable_error) from exc
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or stat.S_IMODE(metadata.st_mode) != 0o600
        ):
            raise RuntimeError(invalid_error)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(held_error) from exc
        yield evidence
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


@contextlib.contextmanager
def _hold_port_lock(port: int):
    with _hold_host_lock(
        lock_path=Path("/run/lock") / f"ea-manfred-candidate-port-{port}.lock",
        unavailable_error="manfred_candidate_port_lock_unavailable",
        invalid_error="manfred_candidate_port_lock_invalid",
        held_error="manfred_candidate_port_lock_held",
        evidence={
            "scope": "host_loopback_port",
            "port": port,
            "held_through_candidate_proof": True,
        },
    ) as evidence:
        yield evidence


@contextlib.contextmanager
def _hold_project_lock(project: str):
    safe_project = _validate_project_name(project)
    with _hold_host_lock(
        lock_path=Path("/run/lock")
        / f"ea-manfred-candidate-project-{safe_project}.lock",
        unavailable_error="manfred_candidate_project_lock_unavailable",
        invalid_error="manfred_candidate_project_lock_invalid",
        held_error="manfred_candidate_project_lock_held",
        evidence={
            "scope": "compose_project",
            "project": safe_project,
            "held_through_candidate_proof": True,
        },
    ) as evidence:
        yield evidence


@contextlib.contextmanager
def _hold_candidate_locks(project: str, port: int):
    with hold_candidate_fleet_lock() as fleet_evidence:
        if fleet_evidence is None:  # pragma: no cover - raising mode
            raise RuntimeError("manfred_candidate_fleet_lock_held")
        with _hold_project_lock(project) as project_evidence:
            with _hold_port_lock(port) as port_evidence:
                yield {
                    "project": project_evidence,
                    "port": port_evidence,
                    "fleet": {
                        **fleet_evidence,
                        "held_through_candidate_proof": True,
                    },
                }


def _assert_candidate_project_absent(project: str) -> dict[str, object]:
    snapshot = _project_snapshot(project)
    named = _candidate_named_resources(project)
    all_container_names = set(
        _listed_values(["docker", "container", "ls", "--all", "--format", "{{.Names}}"])
    )
    all_network_names = set(
        _listed_values(["docker", "network", "ls", "--format", "{{.Name}}"])
    )
    all_volume_names = set(
        _listed_values(["docker", "volume", "ls", "--format", "{{.Name}}"])
    )
    named_network_collisions = sorted(all_network_names.intersection(named["networks"]))
    named_volume_collisions = sorted(all_volume_names.intersection(named["volumes"]))
    named_container_collisions = sorted(
        all_container_names.intersection(named["containers"])
    )
    if (
        snapshot["containers"]
        or snapshot["networks"]
        or snapshot["volumes"]
        or named_container_collisions
        or named_network_collisions
        or named_volume_collisions
    ):
        raise RuntimeError("manfred_candidate_project_resources_already_exist")
    return {
        "project": project,
        "containers": 0,
        "networks": 0,
        "volumes": 0,
        "named_container_collisions": named_container_collisions,
        "named_network_collisions": named_network_collisions,
        "named_volume_collisions": named_volume_collisions,
    }


def _force_remove_candidate_project(
    project: str,
    *,
    vexp_authority: CandidateVexpMutationAuthority,
    vexp_mutation_evidence: list[dict[str, object]],
) -> None:
    safe_project = _validate_project_name(project)
    named = _candidate_named_resources(safe_project)
    snapshot = _project_snapshot(safe_project)
    containers = [dict(row) for row in list(snapshot.get("containers") or [])]
    networks = [dict(row) for row in list(snapshot.get("networks") or [])]
    volumes = [dict(row) for row in list(snapshot.get("volumes") or [])]
    expected_container_names = set(named["containers"])
    expected_network_names = set(named["networks"])
    expected_volume_names = set(named["volumes"])
    if (
        any(
            not str(row.get("container_id") or "")
            or str(row.get("name") or "") not in expected_container_names
            or str(row.get("service") or "") not in EXPECTED_CANDIDATE_SERVICES
            for row in containers
        )
        or any(
            not str(row.get("network_id") or "")
            or str(row.get("name") or "") not in expected_network_names
            or str(row.get("compose_network") or "") not in EXPECTED_CANDIDATE_NETWORKS
            for row in networks
        )
        or any(
            str(row.get("name") or "") not in expected_volume_names
            or str(row.get("compose_volume") or "") not in EXPECTED_CANDIDATE_VOLUMES
            for row in volumes
        )
    ):
        raise RuntimeError("manfred_candidate_forced_cleanup_scope_invalid")
    if containers:
        with vexp_authority.mutation(
            "before_candidate_cleanup",
            minimum_validity_seconds=60,
        ) as lease:
            vexp_mutation_evidence.append(dict(lease.authority_evidence))
            _run(
                [
                    "docker",
                    "container",
                    "rm",
                    "--force",
                    *[str(row["container_id"]) for row in containers],
                ],
                timeout=lease.command_timeout(60),
            )
    if networks:
        with vexp_authority.mutation(
            "before_candidate_cleanup",
            minimum_validity_seconds=60,
        ) as lease:
            vexp_mutation_evidence.append(dict(lease.authority_evidence))
            _run(
                [
                    "docker",
                    "network",
                    "rm",
                    *[str(row["network_id"]) for row in networks],
                ],
                timeout=lease.command_timeout(60),
            )
    if volumes:
        with vexp_authority.mutation(
            "before_candidate_cleanup",
            minimum_validity_seconds=60,
        ) as lease:
            vexp_mutation_evidence.append(dict(lease.authority_evidence))
            _run(
                [
                    "docker",
                    "volume",
                    "rm",
                    *[str(row["name"]) for row in volumes],
                ],
                timeout=lease.command_timeout(60),
            )


def _cleanup_candidate_project(
    *,
    compose: list[str],
    environment: dict[str, str],
    project: str,
    vexp_authority: CandidateVexpMutationAuthority,
    vexp_mutation_evidence: list[dict[str, object]],
) -> None:
    safe_project = _validate_project_name(project)
    if (
        compose[:2] != ["docker", "compose"]
        or compose.count("--project-name") != 1
        or any(
            value.startswith("-p") or value.startswith("--project-name=")
            for value in compose
        )
        or "COMPOSE_PROJECT_NAME" in environment
        or "COMPOSE_FILE" in environment
    ):
        raise RuntimeError("manfred_candidate_cleanup_scope_invalid")
    project_index = compose.index("--project-name")
    if project_index + 1 >= len(compose) or compose[project_index + 1] != safe_project:
        raise RuntimeError("manfred_candidate_cleanup_scope_invalid")
    down = [
        *compose,
        "down",
        "--volumes",
        "--remove-orphans",
        "--timeout",
        "30",
    ]
    for timeout in CANDIDATE_COMPOSE_DOWN_TIMEOUTS:
        try:
            with vexp_authority.mutation(
                "before_candidate_cleanup",
                minimum_validity_seconds=timeout,
            ) as lease:
                vexp_mutation_evidence.append(dict(lease.authority_evidence))
                _run(
                    down,
                    timeout=lease.command_timeout(timeout),
                    environment=environment,
                )
            _assert_candidate_project_absent(safe_project)
            return
        except CandidateAuthorityError:
            raise
        except BaseException:
            continue
    _force_remove_candidate_project(
        safe_project,
        vexp_authority=vexp_authority,
        vexp_mutation_evidence=vexp_mutation_evidence,
    )
    _assert_candidate_project_absent(safe_project)


def _candidate_preflight(project: str, port: int) -> dict[str, object]:
    evidence = _assert_candidate_project_absent(project)
    _assert_loopback_port_free(port)
    return {
        **evidence,
        "loopback_host": "127.0.0.1",
        "loopback_port": port,
        "loopback_port_free_before_start": True,
    }


def _candidate_runtime_version_identity(
    base_url: str,
    *,
    expected_commit: str,
    oci_image_revision: str,
) -> dict[str, object]:
    try:
        request = urllib.request.Request(
            f"{str(base_url or '').rstrip('/')}/version",
            method="GET",
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            if int(getattr(response, "status", 0) or 0) != 200:
                raise RuntimeError("manfred_candidate_runtime_version_status")
            body = response.read(64 * 1024 + 1)
            header_commit = str(
                response.headers.get("X-EA-Source-Revision") or ""
            ).strip()
            media_type = str(response.headers.get("Content-Type") or "").partition(
                ";"
            )[0].strip().lower()
        payload = json.loads(body)
    except (
        OSError,
        UnicodeError,
        ValueError,
        json.JSONDecodeError,
        urllib.error.URLError,
    ) as exc:
        raise RuntimeError(
            "manfred_candidate_runtime_version_identity_invalid"
        ) from exc
    if not isinstance(payload, dict):
        raise RuntimeError("manfred_candidate_runtime_version_identity_invalid")
    body_commit = str(payload.get("commit_sha") or "").strip()
    commits = {body_commit, header_commit, expected_commit, oci_image_revision}
    if (
        len(body) > 64 * 1024
        or media_type != "application/json"
        or len(commits) != 1
        or any(
            len(value) != 40
            or value != value.lower()
            or any(character not in "0123456789abcdef" for character in value)
            for value in commits
        )
        or payload.get("repository") != "EA"
        or payload.get("role") != "api"
        or payload.get("release_authority_state") != "clear"
        or payload.get("release_authority_posture") != "authoritative_runtime"
        or payload.get("release_authority_source") != "published_status_artifact"
    ):
        raise RuntimeError("manfred_candidate_runtime_version_identity_invalid")
    return {
        "path": "/version",
        "status": 200,
        "commit_sha": expected_commit,
        "body_commit_sha": body_commit,
        "source_revision_header": header_commit,
        "expected_commit_sha": expected_commit,
        "oci_image_revision": oci_image_revision,
        "repository": "EA",
        "role": "api",
        "release_authority_state": "clear",
        "release_authority_posture": "authoritative_runtime",
        "release_authority_source": "published_status_artifact",
        "commit_observed_over_http": True,
        "revision_agreement_verified": True,
    }


def _candidate_runtime_source_revision(base_url: str) -> str:
    """Compatibility probe for callers that only need the immutable revision."""
    request = urllib.request.Request(
        f"{str(base_url or '').rstrip('/')}/memorials/manfred.json",
        method="GET",
        headers={"Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            if int(getattr(response, "status", 0) or 0) != 200:
                raise RuntimeError("manfred_candidate_runtime_revision_probe_status")
            revision = str(response.headers.get("X-EA-Source-Revision") or "").strip()
    except (OSError, urllib.error.URLError) as exc:
        raise RuntimeError("manfred_candidate_runtime_revision_unreachable") from exc
    if (
        len(revision) != 40
        or revision != revision.lower()
        or any(character not in "0123456789abcdef" for character in revision)
    ):
        raise RuntimeError("manfred_candidate_runtime_revision_invalid")
    return revision


def _candidate_compose_source_snapshot(
    compose_file: Path,
    *,
    expected_commit: str,
) -> tuple[dict[str, object], bytes]:
    canonical_path = (ROOT / CANDIDATE_COMPOSE_RELATIVE_PATH).resolve()
    supplied_path = compose_file.expanduser()
    if supplied_path.is_symlink():
        raise RuntimeError("manfred_candidate_compose_source_invalid")
    try:
        resolved_path = supplied_path.resolve(strict=True)
    except OSError as exc:
        raise RuntimeError("manfred_candidate_compose_source_invalid") from exc
    if resolved_path != canonical_path or canonical_path.is_symlink():
        raise RuntimeError("manfred_candidate_compose_source_not_canonical")

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(canonical_path, flags)
    except OSError as exc:
        raise RuntimeError("manfred_candidate_compose_source_invalid") from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_size <= 0
            or before.st_size > CANDIDATE_COMPOSE_MAX_BYTES
        ):
            raise RuntimeError("manfred_candidate_compose_source_invalid")
        chunks: list[bytes] = []
        remaining = CANDIDATE_COMPOSE_MAX_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        source_bytes = b"".join(chunks)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    try:
        path_stat = canonical_path.stat()
    except OSError as exc:
        raise RuntimeError("manfred_candidate_compose_source_invalid") from exc
    stable_identity = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    )
    if (
        len(source_bytes) != before.st_size
        or stable_identity
        != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        or (path_stat.st_dev, path_stat.st_ino) != (before.st_dev, before.st_ino)
    ):
        raise RuntimeError("manfred_candidate_compose_source_changed_during_read")

    commit = str(expected_commit or "")
    if (
        len(commit) != 40
        or commit != commit.lower()
        or any(character not in "0123456789abcdef" for character in commit)
    ):
        raise RuntimeError("manfred_candidate_compose_commit_invalid")
    object_spec = f"{commit}:{CANDIDATE_COMPOSE_RELATIVE_PATH.as_posix()}"
    try:
        blob_oid = (
            _run(
                [
                    "git",
                    "-C",
                    str(ROOT),
                    "rev-parse",
                    "--verify",
                    object_spec,
                ],
                timeout=30,
            )
            .decode("ascii", errors="strict")
            .strip()
        )
        if (
            len(blob_oid) not in {40, 64}
            or blob_oid != blob_oid.lower()
            or any(character not in "0123456789abcdef" for character in blob_oid)
        ):
            raise RuntimeError("manfred_candidate_compose_blob_invalid")
        tracked_bytes = _run_bounded_output(
            ["git", "-C", str(ROOT), "cat-file", "blob", blob_oid],
            timeout=30,
            environment=_safe_subprocess_environment(),
            stdout_limit=CANDIDATE_COMPOSE_MAX_BYTES,
            stderr_limit=65536,
            output_limit_error="manfred_candidate_compose_blob_too_large",
        )
    except (
        OSError,
        UnicodeError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ) as exc:
        raise RuntimeError("manfred_candidate_compose_blob_unverifiable") from exc
    if tracked_bytes != source_bytes:
        raise RuntimeError("manfred_candidate_compose_source_not_tracked")
    digest = hashlib.sha256(source_bytes).hexdigest()
    return {
        "canonical_relative_path": CANDIDATE_COMPOSE_RELATIVE_PATH.as_posix(),
        "canonical_source_path": str(canonical_path),
        "candidate_commit": commit,
        "git_blob_oid": blob_oid,
        "sha256": digest,
        "size_bytes": len(source_bytes),
        "canonical_path_enforced": True,
        "tracked_blob_bytes_enforced": True,
    }, source_bytes


def _candidate_compose_attestation(
    compose_file: Path,
    *,
    expected_commit: str,
) -> dict[str, object]:
    attestation, _source_bytes = _candidate_compose_source_snapshot(
        compose_file,
        expected_commit=expected_commit,
    )
    return attestation


def _assert_candidate_compose_attestation_current(
    compose_file: Path,
    attestation: dict[str, object],
) -> None:
    observed = _candidate_compose_attestation(
        compose_file,
        expected_commit=str(attestation.get("candidate_commit") or ""),
    )
    if observed != attestation:
        raise RuntimeError("manfred_candidate_compose_attestation_changed")


def _sealed_memfd(name: str, content: bytes) -> tuple[int, int]:
    required_names = (
        "F_ADD_SEALS",
        "F_GET_SEALS",
        "F_SEAL_GROW",
        "F_SEAL_SEAL",
        "F_SEAL_SHRINK",
        "F_SEAL_WRITE",
    )
    if not hasattr(os, "memfd_create") or any(
        not hasattr(fcntl, constant) for constant in required_names
    ):
        raise RuntimeError("manfred_candidate_execution_input_sealing_unavailable")
    flags = getattr(os, "MFD_CLOEXEC", 0) | getattr(os, "MFD_ALLOW_SEALING", 0)
    descriptor = os.memfd_create(name, flags)
    seals = (
        fcntl.F_SEAL_GROW
        | fcntl.F_SEAL_SEAL
        | fcntl.F_SEAL_SHRINK
        | fcntl.F_SEAL_WRITE
    )
    try:
        view = memoryview(content)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise RuntimeError("manfred_candidate_execution_input_write_failed")
            view = view[written:]
        os.fchmod(descriptor, 0o400)
        os.fsync(descriptor)
        fcntl.fcntl(descriptor, fcntl.F_ADD_SEALS, seals)
        if fcntl.fcntl(descriptor, fcntl.F_GET_SEALS) != seals:
            raise RuntimeError("manfred_candidate_execution_input_sealing_failed")
        return descriptor, seals
    except BaseException:
        os.close(descriptor)
        raise


def _descriptor_bytes(descriptor: int, *, expected_size: int) -> bytes:
    chunks: list[bytes] = []
    offset = 0
    while offset < expected_size:
        chunk = os.pread(descriptor, min(65536, expected_size - offset), offset)
        if not chunk:
            raise RuntimeError("manfred_candidate_execution_input_changed")
        chunks.append(chunk)
        offset += len(chunk)
    if os.pread(descriptor, 1, expected_size):
        raise RuntimeError("manfred_candidate_execution_input_changed")
    return b"".join(chunks)


def _assert_sealed_execution_inputs_current(
    inputs: _SealedExecutionInputs,
) -> None:
    evidence = inputs.evidence
    expected_seals = (
        fcntl.F_SEAL_GROW
        | fcntl.F_SEAL_SEAL
        | fcntl.F_SEAL_SHRINK
        | fcntl.F_SEAL_WRITE
    )
    for descriptor, path, prefix in (
        (inputs.compose_descriptor, inputs.compose_path, "compose"),
        (inputs.environment_descriptor, inputs.environment_path, "environment"),
    ):
        metadata = os.fstat(descriptor)
        try:
            path_metadata = path.stat()
        except OSError as exc:
            raise RuntimeError("manfred_candidate_execution_input_path_invalid") from exc
        expected_size = evidence.get(f"{prefix}_size_bytes")
        expected_digest = evidence.get(f"{prefix}_sha256")
        if (
            type(expected_size) is not int
            or not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o400
            or metadata.st_size != expected_size
            or (path_metadata.st_dev, path_metadata.st_ino)
            != (metadata.st_dev, metadata.st_ino)
            or fcntl.fcntl(descriptor, fcntl.F_GET_SEALS) != expected_seals
            or hashlib.sha256(
                _descriptor_bytes(descriptor, expected_size=expected_size)
            ).hexdigest()
            != expected_digest
        ):
            raise RuntimeError("manfred_candidate_execution_input_changed")


@contextlib.contextmanager
def _sealed_candidate_execution_inputs(
    *,
    compose_bytes: bytes,
    environment_bytes: bytes,
    environment: dict[str, str],
    compose_attestation: dict[str, object],
    compose_image_id: str,
):
    if (
        hashlib.sha256(compose_bytes).hexdigest()
        != compose_attestation.get("sha256")
        or len(compose_bytes) != compose_attestation.get("size_bytes")
        or _parse_env_bytes(environment_bytes) != environment
        or not compose_image_id.startswith("sha256:")
        or len(compose_image_id) != 71
        or any(
            character not in "0123456789abcdef"
            for character in compose_image_id.removeprefix("sha256:")
        )
    ):
        raise RuntimeError("manfred_candidate_execution_input_attestation_invalid")
    compose_descriptor = -1
    environment_descriptor = -1
    try:
        compose_descriptor, _compose_seals = _sealed_memfd(
            "ea-manfred-candidate-compose",
            compose_bytes,
        )
        environment_descriptor, _environment_seals = _sealed_memfd(
            "ea-manfred-candidate-environment",
            environment_bytes,
        )
        process = os.getpid()
        evidence: dict[str, object] = {
            "schema": EXECUTION_INPUT_SCHEMA,
            "compose_sha256": hashlib.sha256(compose_bytes).hexdigest(),
            "compose_size_bytes": len(compose_bytes),
            "compose_git_blob_oid": str(compose_attestation["git_blob_oid"]),
            "environment_sha256": hashlib.sha256(environment_bytes).hexdigest(),
            "environment_size_bytes": len(environment_bytes),
            "environment_keys": sorted(environment),
            "compose_image_id": compose_image_id,
            "compose_image_reference_source": "prepared_image_id",
            "transport": "sealed_memfd",
            "required_seals": ["grow", "seal", "shrink", "write"],
            "all_compose_commands_use_sealed_inputs": True,
            "mutable_source_paths_consumed_by_compose": False,
            "mutable_image_locator_consumed_by_compose": False,
        }
        inputs = _SealedExecutionInputs(
            compose_descriptor=compose_descriptor,
            environment_descriptor=environment_descriptor,
            compose_path=Path(f"/proc/{process}/fd/{compose_descriptor}"),
            environment_path=Path(f"/proc/{process}/fd/{environment_descriptor}"),
            evidence=evidence,
        )
        _assert_sealed_execution_inputs_current(inputs)
        yield inputs
    finally:
        if environment_descriptor >= 0:
            os.close(environment_descriptor)
        if compose_descriptor >= 0:
            os.close(compose_descriptor)


def _expected_candidate_api_environment(env: dict[str, str]) -> dict[str, str]:
    # Keep EA_PUBLIC_MEMORIAL_ARCHIVE_PUBLISHED_SLUGS absent. Archive publication
    # remains fail-closed in candidates unless this exact attested contract is
    # deliberately revised alongside its release review.
    return {
        "EA_ROLE": "api",
        "EA_HOST": "0.0.0.0",
        "EA_PORT": "8090",
        "EA_RUNTIME_MODE": "prod",
        "EA_SOURCE_REVISION": env["EA_MANFRED_COMMIT"],
        "EA_RELEASE_AUTHORITY_STATUS_PATH": (
            "/data/release-authority/release_authority_status.generated.json"
        ),
        "EA_RELEASE_MANIFEST_PATH": (
            "/data/release-authority/release_manifest.generated.json"
        ),
        "EA_DEPLOY_CONTEXT_PATH": (
            "/data/release-authority/deploy_context.generated.json"
        ),
        "EA_PROJECT_MODES_MANIFEST_PATH": (
            "/data/release-authority/PROJECT_MODES.generated.json"
        ),
        "EA_DEPLOYMENT_ID": env["EA_MANFRED_DEPLOYMENT_ID"],
        "EA_DEPLOYMENT_ID_SOURCE": "explicit",
        "EA_DEPLOY_REPOSITORY": "EA",
        "EA_DEPLOY_BRANCH": "main",
        "EA_DEPLOY_TRACKING_BRANCH": "origin/main",
        "EA_DEPLOY_COMMIT_SHA": env["EA_MANFRED_COMMIT"],
        "EA_DEPLOY_PRIMARY_MODE": "MEMORIAL",
        "EA_DEPLOY_ENABLED_MODES": "MEMORIAL",
        "EA_DEPLOY_COMPOSE_FILES": CANDIDATE_COMPOSE_RELATIVE_PATH.as_posix(),
        "EA_DEPLOY_PUBLIC_ORIGIN": env["EA_PUBLIC_APP_BASE_URL"],
        "EA_RELEASE_LABEL": env["EA_MANFRED_DEPLOYMENT_ID"],
        "EA_STORAGE_BACKEND": "postgres",
        "EA_STORAGE_FALLBACK_ALLOWED": "0",
        "EA_ALLOW_LOOPBACK_NO_AUTH": "0",
        "EA_TRUST_PROXY_HEADERS": "1",
        "EA_TRUST_AUTHENTICATED_PRINCIPAL_HEADER": "0",
        "EA_ALLOW_AUTHENTICATED_PRINCIPAL_HEADER": "0",
        "EA_TRUST_API_TOKEN_PRINCIPAL_HEADER": "0",
        "EA_ENABLE_LEGACY_RUNTIME_SURFACES": "1",
        "PROPERTYQUARRY_ENABLE_LEGACY_RUNTIME_SURFACES": "1",
        "EA_ENABLE_PUBLIC_SIDE_SURFACES": "0",
        "EA_ENABLE_PUBLIC_RESULTS": "0",
        "EA_ENABLE_PUBLIC_TOURS": "0",
        "PROPERTYQUARRY_ENABLE_PUBLIC_TOURS": "0",
        "EA_ENABLE_PUBLIC_MEMORIALS": "1",
        "PROPERTYQUARRY_ENABLE_PUBLIC_MEMORIALS": "1",
        "EA_ENABLE_PUBLIC_MEMORIAL_OPERATOR_SURFACES": "0",
        "EA_HEALTHCHECK_MEMORIAL_SLUG": "manfred",
        "EA_PUBLIC_MEMORIAL_RATE_BACKEND": "redis",
        "EA_PUBLIC_MEMORIAL_REDIS_URL": "redis://redis:6379/0",
        "EA_PUBLIC_MEMORIAL_DIR": "/data/memorial/public",
        "EA_PRIVATE_MEMORIAL_PROFILE_DIR": "/data/memorial/private",
        "EA_PUBLIC_MEMORIAL_CONTRIBUTION_DIR": ("/data/memorial/public-contributions"),
        "EA_PRIVATE_MEMORIAL_CONTRIBUTION_DIR": (
            "/data/memorial/private-contributions"
        ),
        "EA_MEMORIAL_DATA_ROOT": "/data/memorial",
        "EA_MEMORIAL_ARCHIVE_DIR": "/data/memorial/archive",
        "EA_MEMORIAL_STATE_DIR": "/data/memorial/state",
        "EA_PUBLIC_MEMORIAL_ARTIFACT_DIR": "/data/artifacts",
        "EA_ARTIFACTS_DIR": "/data/artifacts",
        "EA_MEMORIAL_PAGE_PREWARM_ENABLED": "0",
        "EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED": "0",
        "EA_AUDIOBOOK_UNMIXR_AUTO_RENDER": "0",
        "EA_AUDIOBOOKSHELF_AUTO_IMPORT": "0",
        "HOME": "/home/ea",
        "PYTHONPATH": "/app",
        "TZ": "Europe/Vienna",
    }


def _rendered_compose(
    env_file: Path,
    compose_file: Path,
    *,
    project_name: str,
    environment: dict[str, str],
    resolve_env_files: bool,
) -> dict[str, object]:
    arguments = ["config"]
    if not resolve_env_files:
        arguments.append("--no-env-resolution")
    arguments.extend(["--format", "json"])
    raw = _run(
        _compose_argv(project_name, env_file, compose_file, *arguments),
        timeout=60,
        environment=environment,
    )
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise RuntimeError("manfred_candidate_compose_invalid")
    return payload


def _assert_compose_isolation(
    payload: dict[str, object],
    source_payload: dict[str, object],
    *,
    env: dict[str, str],
    env_file: Path,
    prepared_image_id: str | None = None,
) -> None:
    project = _validate_project_name(env.get("EA_MANFRED_COMPOSE_PROJECT"))
    if payload.get("name") != project or source_payload.get("name") != project:
        raise RuntimeError("manfred_candidate_compose_project_mismatch")
    services = dict(payload.get("services") or {})
    source_services = dict(source_payload.get("services") or {})
    if set(services) != set(EXPECTED_CANDIDATE_SERVICES) or set(source_services) != set(
        services
    ):
        raise RuntimeError("manfred_candidate_compose_services_invalid")
    api = dict(services.get("api") or {})
    source_api = dict(source_services.get("api") or {})
    gateway = dict(services.get("gateway") or {})
    if api.get("build") or api.get("container_name"):
        raise RuntimeError("manfred_candidate_compose_not_image_pure")
    expected_candidate_image = prepared_image_id or env["EA_MANFRED_IMAGE"]
    if str(api.get("image") or "") != expected_candidate_image:
        raise RuntimeError("manfred_candidate_compose_image_mismatch")
    if str(api.get("pull_policy") or "") != "never":
        raise RuntimeError("manfred_candidate_compose_pull_policy_invalid")
    if api.get("read_only") is not True or str(api.get("user") or "") != "10001:10001":
        raise RuntimeError("manfred_candidate_compose_runtime_hardening_invalid")
    networks = dict(payload.get("networks") or {})
    if set(networks) != {"backend", "ingress"}:
        raise RuntimeError("manfred_candidate_compose_network_invalid")
    backend = dict(networks.get("backend") or {})
    ingress = dict(networks.get("ingress") or {})
    if (
        str(backend.get("name") or "") != f"{project}_backend"
        or str(ingress.get("name") or "") != f"{project}_ingress"
    ):
        raise RuntimeError("manfred_candidate_compose_network_name_invalid")
    if backend.get("internal") is not True or backend.get("external") is True:
        raise RuntimeError("manfred_candidate_compose_network_not_isolated")
    if ingress.get("internal") is True or ingress.get("external") is True:
        raise RuntimeError("manfred_candidate_compose_ingress_invalid")

    def network_names(service: dict[str, object]) -> set[str]:
        configured = service.get("networks") or {}
        if isinstance(configured, dict):
            return {str(name) for name in configured}
        if isinstance(configured, list):
            return {str(name) for name in configured}
        return set()

    if network_names(api) != {"backend"}:
        raise RuntimeError("manfred_candidate_api_egress_not_isolated")
    if network_names(dict(services.get("postgres") or {})) != {"backend"}:
        raise RuntimeError("manfred_candidate_postgres_network_invalid")
    if network_names(dict(services.get("redis") or {})) != {"backend"}:
        raise RuntimeError("manfred_candidate_redis_network_invalid")
    if network_names(gateway) != {"backend", "ingress"}:
        raise RuntimeError("manfred_candidate_gateway_network_invalid")
    if str(gateway.get("image") or "") != expected_candidate_image:
        raise RuntimeError("manfred_candidate_gateway_image_mismatch")
    if gateway.get("env_file") or gateway.get("environment"):
        raise RuntimeError("manfred_candidate_gateway_secret_scope_invalid")

    source_env_files = list(source_api.get("env_file") or [])
    if len(source_env_files) != 1 or not isinstance(source_env_files[0], dict):
        raise RuntimeError("manfred_candidate_compose_env_file_invalid")
    if str(source_env_files[0].get("path") or "") != str(env_file):
        raise RuntimeError("manfred_candidate_compose_env_file_mismatch")
    resolved_environment = dict(api.get("environment") or {})
    declared_environment = dict(source_api.get("environment") or {})
    if str(declared_environment.get("EA_TRUST_PROXY_HEADERS") or "") != "1":
        raise RuntimeError("manfred_candidate_transport_probe_trust_invalid")
    expected_declared_environment = _expected_candidate_api_environment(env)
    normalized_declared_environment = {
        str(name): str(value or "") for name, value in declared_environment.items()
    }
    if normalized_declared_environment != expected_declared_environment:
        raise RuntimeError("manfred_candidate_compose_api_environment_not_allowlisted")
    expected_resolved_environment = {**env, **expected_declared_environment}
    normalized_resolved_environment = {
        str(name): str(value or "") for name, value in resolved_environment.items()
    }
    if normalized_resolved_environment != expected_resolved_environment:
        raise RuntimeError("manfred_candidate_compose_environment_scope_invalid")

    gateway_ports = list(gateway.get("ports") or [])
    if len(gateway_ports) != 1 or not isinstance(gateway_ports[0], dict):
        raise RuntimeError("manfred_candidate_gateway_port_invalid")
    gateway_port = gateway_ports[0]
    if (
        str(gateway_port.get("host_ip") or "") != "127.0.0.1"
        or int(gateway_port.get("target") or 0) != 18090
        or int(gateway_port.get("published") or 0) != int(env["EA_MANFRED_HOST_PORT"])
    ):
        raise RuntimeError("manfred_candidate_gateway_port_invalid")
    expected_binds = {
        "/data/memorial/public": (
            str((Path(env["EA_MANFRED_RELEASE_ROOT"]) / "public_memorials").resolve()),
            True,
        ),
        "/data/memorial/private": (
            str(
                (
                    Path(env["EA_MANFRED_RELEASE_ROOT"]) / "private_memorial_profiles"
                ).resolve()
            ),
            True,
        ),
        "/data/memorial/archive": (
            str((Path(env["EA_MANFRED_RELEASE_ROOT"]) / "memorial_archive").resolve()),
            True,
        ),
        "/data/memorial/public-contributions": (
            str(
                (
                    Path(env["EA_MANFRED_RUNTIME_ROOT"]) / "public-contributions"
                ).resolve()
            ),
            False,
        ),
        "/data/memorial/private-contributions": (
            str(
                (
                    Path(env["EA_MANFRED_RUNTIME_ROOT"]) / "private-contributions"
                ).resolve()
            ),
            False,
        ),
        "/data/memorial/state": (
            str((Path(env["EA_MANFRED_RUNTIME_ROOT"]) / "state").resolve()),
            False,
        ),
        "/data/release-authority": (
            str(Path(env["EA_MANFRED_RELEASE_AUTHORITY_ROOT"]).resolve()),
            True,
        ),
    }
    actual_binds: dict[str, tuple[str, bool]] = {}
    volume_mounts: list[dict[str, object]] = []
    for mount in list(api.get("volumes") or []):
        if not isinstance(mount, dict):
            raise RuntimeError("manfred_candidate_compose_mount_invalid")
        mount_type = str(mount.get("type") or "")
        if mount_type == "bind":
            target = str(mount.get("target") or "")
            if target in actual_binds:
                raise RuntimeError("manfred_candidate_compose_mount_duplicate")
            actual_binds[target] = (
                str(mount.get("source") or ""),
                bool(mount.get("read_only")),
            )
        elif mount_type == "volume":
            volume_mounts.append(dict(mount))
        else:
            raise RuntimeError("manfred_candidate_compose_mount_type_invalid")
    if actual_binds != expected_binds:
        raise RuntimeError("manfred_candidate_compose_mount_root_mismatch")
    if len(volume_mounts) != 1 or (
        str(volume_mounts[0].get("source") or "") != "artifacts"
        or str(volume_mounts[0].get("target") or "") != "/data/artifacts"
    ):
        raise RuntimeError("manfred_candidate_compose_volume_mount_invalid")

    volumes = dict(payload.get("volumes") or {})
    if set(volumes) != set(EXPECTED_CANDIDATE_VOLUMES):
        raise RuntimeError("manfred_candidate_compose_volumes_invalid")
    for name, value in volumes.items():
        if str(dict(value or {}).get("name") or "") != f"{project}_{name}":
            raise RuntimeError("manfred_candidate_compose_volume_name_invalid")

    for service_name, service in services.items():
        service_payload = dict(service or {})
        if service_payload.get("build") or service_payload.get("container_name"):
            raise RuntimeError("manfred_candidate_compose_service_not_isolated")
        for mount in list(service_payload.get("volumes") or []):
            if not isinstance(mount, dict):
                continue
            source = str(mount.get("source") or "")
            target = str(mount.get("target") or "")
            if source.startswith("/docker/EA") or source == "/var/run/docker.sock":
                raise RuntimeError("manfred_candidate_compose_live_bind_forbidden")
            if service_name != "api" and (
                target == "/data/release-authority"
                or source == env["EA_MANFRED_RELEASE_AUTHORITY_ROOT"]
            ):
                raise RuntimeError("manfred_candidate_release_compose_scope_invalid")
            if target == "/data/public_property_tours":
                raise RuntimeError("manfred_candidate_spatial_compose_scope_invalid")


def _assert_env_allowlist(
    env_file: Path,
    *,
    environment_bytes: bytes | None = None,
) -> dict[str, str]:
    env = (
        _parse_env(env_file)
        if environment_bytes is None
        else _parse_env_bytes(environment_bytes)
    )
    if set(env) != ALLOWED_ENV_KEYS:
        raise RuntimeError("manfred_candidate_env_allowlist_invalid")
    for name in ("EA_API_TOKEN", "EA_SIGNING_SECRET", "EA_MANFRED_POSTGRES_PASSWORD"):
        if len(env.get(name, "")) < 40:
            raise RuntimeError("manfred_candidate_env_secret_invalid")
    try:
        _validate_project_name(env["EA_MANFRED_COMPOSE_PROJECT"])
    except ValueError as exc:
        raise RuntimeError("manfred_candidate_project_name_invalid") from exc
    if env["EA_MANFRED_ENV_FILE"] != str(env_file.resolve()):
        raise RuntimeError("manfred_candidate_env_file_binding_invalid")
    for name in (
        "EA_MANFRED_RELEASE_ROOT",
        "EA_MANFRED_RELEASE_AUTHORITY_ROOT",
        "EA_MANFRED_RUNTIME_ROOT",
    ):
        path = Path(env[name]).expanduser()
        if (
            not path.is_absolute()
            or str(path.resolve()) != env[name]
            or path.is_symlink()
            or not path.is_dir()
        ):
            raise RuntimeError("manfred_candidate_env_path_invalid")
    release_root = Path(env["EA_MANFRED_RELEASE_ROOT"]).resolve()
    authority_root = Path(env["EA_MANFRED_RELEASE_AUTHORITY_ROOT"]).resolve()
    if authority_root != (release_root / CANDIDATE_RELEASE_AUTHORITY_DIRNAME).resolve():
        raise RuntimeError("manfred_candidate_release_authority_env_root_mismatch")
    commit = env["EA_MANFRED_COMMIT"]
    if (
        len(commit) != 40
        or commit != commit.lower()
        or any(character not in "0123456789abcdef" for character in commit)
        or env["EA_MANFRED_DEPLOYMENT_ID"]
        != f"{env['EA_MANFRED_COMPOSE_PROJECT']}-{commit[:12]}"
    ):
        raise RuntimeError("manfred_candidate_release_identity_invalid")
    if (
        env["EA_MANFRED_MEMORIAL_SURFACE"] != MEMORIAL_SURFACE
        or env["EA_MANFRED_SPATIAL_SCOPE"] != SPATIAL_SCOPE
        or (release_root / "public_property_tours").exists()
    ):
        raise RuntimeError("manfred_candidate_conversation_scope_invalid")
    try:
        port = int(env["EA_MANFRED_HOST_PORT"])
    except ValueError as exc:
        raise RuntimeError("manfred_candidate_host_port_invalid") from exc
    if not 1024 <= port <= 65535:
        raise RuntimeError("manfred_candidate_host_port_invalid")
    return env


def _assert_redis(
    compose: list[str],
    environment: dict[str, str],
    *,
    vexp_authority: CandidateVexpMutationAuthority,
    vexp_mutation_evidence: list[dict[str, object]],
) -> None:
    argv = [*compose, "exec", "-T", "redis", "redis-cli", "ping"]
    with _candidate_exec_timeout(
        vexp_authority=vexp_authority,
        vexp_mutation_evidence=vexp_mutation_evidence,
        operation="redis_ping",
        argv=argv,
        target="redis",
        timeout_seconds=30,
    ) as timeout:
        response = _run(argv, timeout=timeout, environment=environment)
    if response.decode("utf-8", errors="replace").strip() != "PONG":
        raise RuntimeError("manfred_candidate_redis_unavailable")


def _assert_contribution_modes(
    compose: list[str],
    environment: dict[str, str],
    *,
    vexp_authority: CandidateVexpMutationAuthority,
    vexp_mutation_evidence: list[dict[str, object]],
) -> dict[str, str]:
    command = (
        "private=/data/memorial/private-contributions/manfred/family_contributions.json; "
        "public=/data/memorial/public-contributions/manfred/family_contributions.public.json; "
        'test -f "$private"; test -f "$public"; '
        'printf \'%s %s\' "$(stat -c %a "$private")" "$(stat -c %a "$public")"'
    )
    argv = [*compose, "exec", "-T", "api", "/bin/sh", "-ec", command]
    with _candidate_exec_timeout(
        vexp_authority=vexp_authority,
        vexp_mutation_evidence=vexp_mutation_evidence,
        operation="contribution_mode_probe",
        argv=argv,
        target="api:/data/memorial/contributions",
        timeout_seconds=30,
    ) as timeout:
        raw = _run(argv, timeout=timeout, environment=environment)
    private_mode, public_mode = raw.decode("ascii").strip().split()
    if private_mode != "600" or public_mode != "644":
        raise RuntimeError("manfred_candidate_contribution_permissions_invalid")
    return {"private_ledger": private_mode, "public_projection": public_mode}


def _assert_conversation_state_mode(
    compose: list[str],
    environment: dict[str, str],
    *,
    vexp_authority: CandidateVexpMutationAuthority,
    vexp_mutation_evidence: list[dict[str, object]],
) -> dict[str, str]:
    """Prove the conversation-only candidate's writable state root is private."""

    command = (
        "state=/data/memorial/state; "
        'test -d "$state"; '
        'printf \'%s\' "$(stat -c %a "$state")"'
    )
    argv = [*compose, "exec", "-T", "api", "/bin/sh", "-ec", command]
    with _candidate_exec_timeout(
        vexp_authority=vexp_authority,
        vexp_mutation_evidence=vexp_mutation_evidence,
        operation="conversation_state_mode_probe",
        argv=argv,
        target="api:/data/memorial/state",
        timeout_seconds=30,
    ) as timeout:
        raw = _run(argv, timeout=timeout, environment=environment)
    mode = raw.decode("ascii").strip()
    if mode != "700":
        raise RuntimeError("manfred_candidate_conversation_state_permissions_invalid")
    return {"conversation_state_root": mode}


def _parse_internal_transport_headers(raw: bytes) -> tuple[int, dict[str, str]]:
    try:
        text = raw.decode("latin-1")
    except UnicodeDecodeError as exc:  # pragma: no cover - latin-1 is total
        raise RuntimeError(
            "manfred_candidate_internal_transport_probe_invalid"
        ) from exc
    marker = f"\n{INTERNAL_TRANSPORT_STATUS_MARKER}"
    header_text, separator, status_text = text.rpartition(marker)
    if not separator:
        raise RuntimeError("manfred_candidate_internal_transport_probe_invalid")
    if (
        len(status_text) != 4
        or not status_text.endswith("\n")
        or not status_text[:3].isascii()
        or not status_text[:3].isdigit()
    ):
        raise RuntimeError("manfred_candidate_internal_transport_probe_invalid")
    status = int(status_text[:3])
    if not header_text.endswith("\r\n\r\n"):
        raise RuntimeError("manfred_candidate_internal_transport_probe_invalid")
    without_crlf = header_text.replace("\r\n", "")
    if "\r" in without_crlf or "\n" in without_crlf:
        raise RuntimeError("manfred_candidate_internal_transport_probe_invalid")
    blocks = header_text[:-4].split("\r\n\r\n")
    if not blocks or any(not block for block in blocks):
        raise RuntimeError("manfred_candidate_internal_transport_probe_invalid")
    lines = blocks[-1].split("\r\n")
    if (
        not lines
        or lines[0].startswith((" ", "\t"))
        or any(ord(character) < 32 or ord(character) == 127 for character in lines[0])
    ):
        raise RuntimeError("manfred_candidate_internal_transport_probe_invalid")
    status_parts = lines[0].split(" ", 2)
    version = status_parts[0]
    if (
        len(status_parts) != 3
        or version not in {"HTTP/1.0", "HTTP/1.1"}
        or len(status_parts[1]) != 3
        or not status_parts[1].isascii()
        or not status_parts[1].isdigit()
        or not status_parts[2]
    ):
        raise RuntimeError("manfred_candidate_internal_transport_probe_invalid")
    header_status = int(status_parts[1])
    if header_status != status:
        raise RuntimeError("manfred_candidate_internal_transport_probe_invalid")
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if not line or line.startswith((" ", "\t")):
            raise RuntimeError("manfred_candidate_internal_transport_probe_invalid")
        name, delimiter, value = line.partition(":")
        normalized_name = name.lower()
        if (
            not delimiter
            or not name
            or name != name.strip()
            or any(character not in HTTP_HEADER_NAME_CHARACTERS for character in name)
            or normalized_name in headers
            or any(ord(character) < 32 and character != "\t" for character in value)
            or any(ord(character) == 127 for character in value)
        ):
            raise RuntimeError("manfred_candidate_internal_transport_probe_invalid")
        headers[normalized_name] = value.strip(" \t")
    return status, headers


def _candidate_api_loopback_request(
    compose: list[str],
    environment: dict[str, str],
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, object] | None = None,
    headers: dict[str, str] | None = None,
    expected: set[int] | None = None,
    follow_redirects: bool = True,
    vexp_authority: CandidateVexpMutationAuthority,
    vexp_mutation_evidence: list[dict[str, object]],
) -> tuple[int, bytes, dict[str, str]]:
    del base_url
    raw_path = str(path or "")
    try:
        parsed = urllib.parse.urlsplit(raw_path)
        raw_path.encode("ascii")
    except (UnicodeEncodeError, ValueError) as exc:
        raise RuntimeError(
            "manfred_candidate_internal_transport_request_invalid"
        ) from exc
    normalized_method = str(method or "").strip().upper()
    if (
        payload is not None
        or follow_redirects
        or normalized_method not in {"GET", "HEAD"}
        or raw_path not in INTERNAL_TRANSPORT_PATHS
        or parsed.scheme
        or parsed.netloc
        or any(ord(character) <= 32 or ord(character) == 127 for character in raw_path)
    ):
        raise RuntimeError("manfred_candidate_internal_transport_request_invalid")
    request_headers = dict(headers or {})
    request_headers.update(
        {
            "Accept": "application/json,text/html;q=0.9,*/*;q=0.1",
            "User-Agent": "EA-Memorial-Launch-Verifier/1.0",
        }
    )
    argv = [
        *compose,
        "exec",
        "-T",
        "api",
        "curl",
        "--disable",
        "--noproxy",
        "*",
        "--globoff",
        "--path-as-is",
        "--silent",
        "--show-error",
        "--max-time",
        "20",
    ]
    if normalized_method == "HEAD":
        argv.append("--head")
    else:
        argv.extend(["--request", normalized_method])
    argv.extend(
        [
            "--output",
            "/dev/null",
            "--dump-header",
            "-",
            "--write-out",
            f"\n{INTERNAL_TRANSPORT_STATUS_MARKER}%{{http_code}}\n",
        ]
    )
    outgoing_header_names: set[str] = set()
    for name, value in sorted(request_headers.items()):
        normalized_name = str(name or "")
        normalized_value = str(value or "")
        lower_name = normalized_name.lower()
        if (
            not normalized_name
            or normalized_name != normalized_name.strip()
            or any(
                character not in HTTP_HEADER_NAME_CHARACTERS
                for character in normalized_name
            )
            or lower_name in outgoing_header_names
            or any(
                ord(character) < 32 or ord(character) == 127
                for character in normalized_value
            )
        ):
            raise RuntimeError("manfred_candidate_internal_transport_request_invalid")
        outgoing_header_names.add(lower_name)
        argv.extend(["--header", f"{normalized_name}: {normalized_value}"])
    argv.append(f"http://127.0.0.1:8090{raw_path}")
    with _candidate_exec_timeout(
        vexp_authority=vexp_authority,
        vexp_mutation_evidence=vexp_mutation_evidence,
        operation="internal_transport_request",
        argv=argv,
        target=f"api:http://127.0.0.1:8090{raw_path}",
        timeout_seconds=30,
    ) as timeout:
        response = _run(argv, timeout=timeout, environment=environment)
    status, response_headers = _parse_internal_transport_headers(response)
    allowed = expected or {200}
    if status not in allowed:
        raise RuntimeError(f"candidate_http_status_unexpected:{path}:{status}")
    return status, b"", response_headers


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(  # type: ignore[override]
        self,
        req: urllib.request.Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> None:
        del req, fp, code, msg, headers, newurl
        return None


def _candidate_openapi_retirement_headers(
    response_headers: object,
) -> dict[str, str]:
    items = getattr(response_headers, "items", None)
    if not callable(items):
        raise RuntimeError("manfred_candidate_openapi_retirement_headers_invalid")
    normalized: dict[str, str] = {}
    singleton_seen: set[str] = set()
    try:
        rows = list(items())
    except Exception as exc:
        raise RuntimeError(
            "manfred_candidate_openapi_retirement_headers_invalid"
        ) from exc
    for raw_name, raw_value in rows:
        name = str(raw_name or "").strip().lower()
        value = str(raw_value or "").strip()
        if (
            not name
            or any(character not in HTTP_HEADER_NAME_CHARACTERS for character in name)
            or any(ord(character) < 32 or ord(character) == 127 for character in value)
        ):
            raise RuntimeError("manfred_candidate_openapi_retirement_headers_invalid")
        if name in CANDIDATE_OPENAPI_RETIREMENT_SINGLETON_HEADERS:
            if name in singleton_seen or "," in value:
                raise RuntimeError(
                    "manfred_candidate_openapi_retirement_headers_ambiguous"
                )
            singleton_seen.add(name)
            normalized[name] = value
        elif name in normalized:
            normalized[name] = f"{normalized[name]}, {value}"
        else:
            normalized[name] = value
    return normalized


def _candidate_openapi_csp_denies_framing(value: str) -> bool:
    directives: dict[str, tuple[str, ...]] = {}
    for raw_directive in str(value or "").split(";"):
        parts = raw_directive.strip().split()
        if not parts:
            continue
        name = parts[0].lower()
        if name in directives:
            return False
        directives[name] = tuple(parts[1:])
    return directives.get("frame-ancestors") == ("'none'",)


def _assert_candidate_openapi_retired(base_url: str) -> dict[str, object]:
    path = "/openapi.json"
    request = urllib.request.Request(
        f"{str(base_url or '').rstrip('/')}{path}",
        method="GET",
        headers={
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "User-Agent": "EA-Manfred-OpenAPI-Retirement-Verifier/1.0",
        },
    )
    opener = urllib.request.build_opener(_NoRedirectHandler())
    try:
        with opener.open(request, timeout=20) as response:
            status = int(response.status or 0)
            body = response.read(MAX_OPENAPI_DOCUMENT_BYTES + 1)
            headers = _candidate_openapi_retirement_headers(response.headers)
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        body = exc.read(MAX_OPENAPI_DOCUMENT_BYTES + 1)
        headers = _candidate_openapi_retirement_headers(exc.headers)
    except (OSError, urllib.error.URLError) as exc:
        raise RuntimeError("manfred_candidate_openapi_retirement_unreachable") from exc
    if status != 404:
        raise RuntimeError(
            f"manfred_candidate_openapi_retirement_status_invalid:{status}"
        )
    payload = _openapi_document(
        body,
        invalid_error="manfred_candidate_openapi_retirement_payload_invalid",
        too_large_error="manfred_candidate_openapi_retirement_payload_too_large",
    )
    error = payload.get("error")
    if not isinstance(error, dict):
        raise RuntimeError("manfred_candidate_openapi_retirement_payload_invalid")
    correlation_id = error.get("correlation_id")
    content_type = str(headers.get("content-type") or "")
    content_media_type = content_type.partition(";")[0].strip().lower()
    security_headers = {
        "content_security_policy": str(headers.get("content-security-policy") or ""),
        "x_content_type_options": str(headers.get("x-content-type-options") or ""),
        "x_frame_options": str(headers.get("x-frame-options") or ""),
    }
    if (
        set(error) != {"code", "message", "details", "correlation_id"}
        or error.get("code") != "not_found"
        or error.get("message") != "not_found"
        or error.get("details") != "not_found"
        or type(correlation_id) is not str
        or not correlation_id
        or str(headers.get("x-correlation-id") or "") != correlation_id
        or content_media_type != "application/json"
        or not _candidate_openapi_csp_denies_framing(
            security_headers["content_security_policy"]
        )
        or security_headers["x_content_type_options"].lower() != "nosniff"
        or security_headers["x_frame_options"].upper() != "DENY"
    ):
        raise RuntimeError("manfred_candidate_openapi_retirement_contract_invalid")
    return {
        "path": path,
        "status": 404,
        "error_code": "not_found",
        "content_type": content_type,
        "media_type": content_media_type,
        "correlation_header_matches_body": True,
        "security_headers": security_headers,
        "public_endpoint_retired": True,
    }


def _spatial_http_probe(
    base_url: str,
    path: str,
    *,
    method: str,
    expected_status: int,
    accept: str = "*/*",
) -> tuple[bytes, dict[str, str]]:
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        method=method,
        headers={
            "Accept": accept,
            "Accept-Encoding": "identity",
            "User-Agent": "EA-Manfred-Spatial-Handoff-Verifier/1.0",
        },
    )
    opener = urllib.request.build_opener(_NoRedirectHandler())
    try:
        with opener.open(request, timeout=20) as response:
            status = int(response.status or 0)
            body = response.read(8 * 1024 * 1024 + 1) if method == "GET" else b""
            headers = {
                str(name).lower(): str(value).strip()
                for name, value in response.headers.items()
            }
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        body = b""
        headers = {
            str(name).lower(): str(value).strip() for name, value in exc.headers.items()
        }
    except (OSError, urllib.error.URLError) as exc:
        raise RuntimeError("manfred_candidate_spatial_http_unreachable") from exc
    if status != expected_status or len(body) > 8 * 1024 * 1024:
        raise RuntimeError("manfred_candidate_spatial_http_status_invalid")
    return body, headers


def _spatial_handoff_runtime_proof(
    base_url: str,
    projection: dict[str, object],
    *,
    oci_image_id: str,
    serving_container_id: str,
) -> dict[str, object]:
    spatial = dict(projection.get("spatial_handoff") or {})
    if spatial.get("included") is not True:
        raise RuntimeError("manfred_candidate_spatial_handoff_required")
    slug = str(spatial.get("slug") or "")
    viewer_relpath = str(spatial.get("viewer_relpath") or "")
    proof_relpath = str(spatial.get("proof_relpath") or "")
    if not slug or not viewer_relpath or not proof_relpath:
        raise RuntimeError("manfred_candidate_spatial_runtime_contract_invalid")
    quoted_slug = urllib.parse.quote(slug, safe="")
    html_path = f"/tours/{quoted_slug}"
    json_path = f"/tours/{quoted_slug}.json"
    viewer_path = (
        f"/tours/viewer/{quoted_slug}/{urllib.parse.quote(viewer_relpath, safe='/')}"
    )
    proof_path = (
        f"/tours/viewer/{quoted_slug}/{urllib.parse.quote(proof_relpath, safe='/')}"
    )
    routes: dict[str, dict[str, object]] = {}
    for label, path, expected, accept in (
        ("html", html_path, 200, "text/html"),
        ("json", json_path, 200, "application/json"),
        ("viewer", viewer_path, 200, "text/html"),
        ("proof_only", proof_path, 404, "application/json"),
    ):
        for method in ("GET", "HEAD"):
            body, headers = _spatial_http_probe(
                base_url,
                path,
                method=method,
                expected_status=expected,
                accept=accept,
            )
            routes[f"{label}_{method.lower()}"] = {
                "path": path,
                "status": expected,
                "content_type": str(headers.get("content-type") or ""),
            }
            if label == "json" and method == "GET":
                try:
                    payload = json.loads(body)
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise RuntimeError(
                        "manfred_candidate_spatial_json_invalid"
                    ) from exc
                generated_viewer = (
                    dict(payload.get("generated_viewer") or {})
                    if isinstance(payload, dict)
                    else {}
                )
                if generated_viewer.get("url") != viewer_path:
                    raise RuntimeError("manfred_candidate_spatial_json_viewer_mismatch")
    bundle = Path(str(spatial.get("release_root") or "")) / slug
    verifier_receipt = verify_spatial_bundle(
        bundle,
        base_url=base_url,
        slug=slug,
    )
    if verifier_receipt.get("pass") is not True:
        raise RuntimeError("manfred_candidate_spatial_http_verifier_blocked")
    projection_commit = projection.get("projection_commit")
    package_digest = spatial.get("upstream_package_sha256")
    if type(projection_commit) is not str or type(package_digest) is not str:
        raise RuntimeError("manfred_candidate_spatial_runtime_contract_invalid")
    browser_receipt = audit_spatial_candidate_browser(
        base_url=base_url,
        slug=slug,
        viewer_relpath=viewer_relpath,
        route_labels=list(spatial.get("route_labels") or []),
        candidate_commit=projection_commit,
        oci_image_id=oci_image_id,
        serving_container_id=serving_container_id,
        package_sha256=package_digest,
        package_dir=bundle,
    )
    try:
        validate_spatial_candidate_browser_receipt(
            browser_receipt,
            base_url=base_url,
            slug=slug,
            viewer_relpath=viewer_relpath,
            route_labels=list(spatial.get("route_labels") or []),
            candidate_commit=projection_commit,
            oci_image_id=oci_image_id,
            serving_container_id=serving_container_id,
            package_sha256=package_digest,
        )
    except (RuntimeError, ValueError) as exc:
        raise RuntimeError("manfred_candidate_spatial_browser_gate_blocked") from exc
    if browser_receipt.get("secret_material_recorded") is not False:
        raise RuntimeError("manfred_candidate_spatial_browser_gate_blocked")
    return {
        "included": True,
        "routes_required": True,
        "slug": slug,
        "routes": routes,
        "generated_viewer_release_verifier": verifier_receipt,
        "candidate_browser_gate": browser_receipt,
        "html_json_viewer_200": True,
        "proof_only_404": True,
        "ea_public_activation_authority": False,
        "upstream_public_activation_authority": True,
    }


def _assert_logs_clean(compose: list[str], environment: dict[str, str]) -> None:
    logs = _run(
        [*compose, "logs", "--no-color", "--tail", "1000", "api", "gateway"],
        timeout=60,
        environment=environment,
    )
    text = logs.decode("utf-8", errors="replace")
    if any(marker in text for marker in FORBIDDEN_LOG_MARKERS):
        raise RuntimeError("manfred_candidate_import_failure_in_logs")


def _normalized_receipt_path(path: Path) -> Path:
    try:
        normalized = Path(os.path.abspath(os.fspath(path.expanduser())))
    except (OSError, RuntimeError, ValueError) as exc:
        raise RuntimeError(RECEIPT_PATH_INVALID) from exc
    if not normalized.is_absolute() or normalized.name in {"", ".", ".."}:
        raise RuntimeError(RECEIPT_PATH_INVALID)
    return normalized


def _open_trusted_receipt_parent(path: Path) -> tuple[Path, int]:
    normalized = _normalized_receipt_path(path)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = -1
    try:
        descriptor = os.open(os.sep, flags)
        for component in normalized.parent.parts[1:]:
            next_descriptor = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        metadata = os.fstat(descriptor)
    except (OSError, ValueError) as exc:
        if descriptor >= 0:
            os.close(descriptor)
        raise RuntimeError(RECEIPT_PARENT_INVALID) from exc
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) & 0o022
    ):
        os.close(descriptor)
        raise RuntimeError(RECEIPT_PARENT_INVALID)
    return normalized, descriptor


def _assert_new_receipt_path(path: Path) -> Path:
    normalized, directory_descriptor = _open_trusted_receipt_parent(path)
    try:
        try:
            metadata = os.stat(
                normalized.name,
                dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            return normalized
        if stat.S_ISLNK(metadata.st_mode):
            raise RuntimeError(RECEIPT_PATH_INVALID)
        raise RuntimeError(RECEIPT_OUTPUT_EXISTS)
    finally:
        os.close(directory_descriptor)


def _complete_interrupted_receipt_publication(path: Path) -> bool:
    """Finish the sole hard-link window used by ``_atomic_receipt``.

    A SIGKILL can land after the final no-replace link is created but before
    the private temporary name is unlinked.  Only that exact same-inode,
    same-directory publication shape is recoverable; every other hard link
    remains fail-closed.
    """

    normalized, directory_descriptor = _open_trusted_receipt_parent(path)
    try:
        try:
            final = os.stat(
                normalized.name,
                dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            return False
        if (
            not stat.S_ISREG(final.st_mode)
            or final.st_uid != os.getuid()
            or stat.S_IMODE(final.st_mode) != 0o600
            or final.st_nlink != 2
        ):
            return False
        matches: list[str] = []
        for name in os.listdir(directory_descriptor):
            parts = name.split(".")
            if (
                len(parts) != 5
                or parts[0] != ""
                or parts[1] != "ea-manfred-receipt"
                or not parts[2].isdigit()
                or len(parts[3]) != 24
                or any(character not in "0123456789abcdef" for character in parts[3])
                or parts[4] != "tmp"
            ):
                continue
            try:
                candidate = os.stat(
                    name,
                    dir_fd=directory_descriptor,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                continue
            if (
                stat.S_ISREG(candidate.st_mode)
                and candidate.st_uid == final.st_uid
                and candidate.st_dev == final.st_dev
                and candidate.st_ino == final.st_ino
                and candidate.st_nlink == 2
                and stat.S_IMODE(candidate.st_mode) == 0o600
            ):
                matches.append(name)
        if len(matches) != 1:
            return False
        os.unlink(matches[0], dir_fd=directory_descriptor)
        os.fsync(directory_descriptor)
        remaining = os.stat(
            normalized.name,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
        if (
            remaining.st_dev != final.st_dev
            or remaining.st_ino != final.st_ino
            or remaining.st_nlink != 1
            or stat.S_IMODE(remaining.st_mode) != 0o600
        ):
            raise RuntimeError(RECEIPT_ARTIFACT_INVALID)
        return True
    finally:
        os.close(directory_descriptor)


def _receipt_artifact_if_present(path: Path) -> _CreatedReceiptArtifact | None:
    normalized, directory_descriptor = _open_trusted_receipt_parent(path)
    try:
        try:
            metadata = os.stat(
                normalized.name,
                dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            return None
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or metadata.st_nlink != 1
            or stat.S_IMODE(metadata.st_mode) != 0o600
        ):
            raise RuntimeError(RECEIPT_ARTIFACT_INVALID)
        return _CreatedReceiptArtifact(
            path=normalized,
            device=metadata.st_dev,
            inode=metadata.st_ino,
            ctime_ns=metadata.st_ctime_ns,
            size=metadata.st_size,
        )
    finally:
        os.close(directory_descriptor)


def _withdraw_candidate_contribution_if_present(
    base_url: str,
    receipt_path: Path,
    *,
    expected_artifact: _CreatedReceiptArtifact | None = None,
) -> bool:
    """Withdraw a receipt-bound synthetic contribution without losing its token."""

    artifact = _receipt_artifact_if_present(receipt_path)
    if artifact is None:
        if expected_artifact is not None:
            raise RuntimeError("manfred_candidate_contribution_receipt_changed")
        return False
    if expected_artifact is not None and artifact != expected_artifact:
        raise RuntimeError("manfred_candidate_contribution_receipt_changed")
    _withdraw_contribution(base_url, artifact.path)
    if _receipt_artifact_if_present(artifact.path) is not None:
        raise RuntimeError("manfred_candidate_contribution_withdrawal_incomplete")
    return True


def _unlink_created_receipt_artifact(artifact: _CreatedReceiptArtifact) -> bool:
    normalized, directory_descriptor = _open_trusted_receipt_parent(artifact.path)
    try:
        if normalized != artifact.path:
            return False
        try:
            metadata = os.stat(
                normalized.name,
                dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            return True
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or metadata.st_nlink != 1
            or metadata.st_dev != artifact.device
            or metadata.st_ino != artifact.inode
            or metadata.st_ctime_ns != artifact.ctime_ns
            or metadata.st_size != artifact.size
        ):
            return False
        os.unlink(normalized.name, dir_fd=directory_descriptor)
        os.fsync(directory_descriptor)
        try:
            os.stat(
                normalized.name,
                dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            return True
        return False
    finally:
        os.close(directory_descriptor)


def _atomic_receipt(
    path: Path,
    payload: dict[str, object],
) -> _CreatedReceiptArtifact:
    normalized, directory_descriptor = _open_trusted_receipt_parent(path)
    descriptor = -1
    temporary_name = ""
    final_linked = False
    artifact: _CreatedReceiptArtifact | None = None
    try:
        try:
            existing = os.stat(
                normalized.name,
                dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            existing = None
        if existing is not None:
            if stat.S_ISLNK(existing.st_mode):
                raise RuntimeError(RECEIPT_PATH_INVALID)
            raise RuntimeError(RECEIPT_OUTPUT_EXISTS)

        temporary_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            temporary_flags |= os.O_NOFOLLOW
        for _attempt in range(32):
            temporary_name = (
                f".ea-manfred-receipt.{os.getpid()}.{secrets.token_hex(12)}.tmp"
            )
            try:
                descriptor = os.open(
                    temporary_name,
                    temporary_flags,
                    0o600,
                    dir_fd=directory_descriptor,
                )
                break
            except FileExistsError:
                continue
        if descriptor < 0:
            raise RuntimeError(RECEIPT_WRITE_FAILED)

        os.fchmod(descriptor, 0o600)
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or metadata.st_nlink != 1
            or stat.S_IMODE(metadata.st_mode) != 0o600
        ):
            raise RuntimeError(RECEIPT_WRITE_FAILED)
        encoded = (
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode(
                "utf-8"
            )
            + b"\n"
        )
        view = memoryview(encoded)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise RuntimeError(RECEIPT_WRITE_FAILED)
            view = view[written:]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1

        artifact = _CreatedReceiptArtifact(
            path=normalized,
            device=metadata.st_dev,
            inode=metadata.st_ino,
            ctime_ns=metadata.st_ctime_ns,
            size=metadata.st_size,
        )
        try:
            os.link(
                temporary_name,
                normalized.name,
                src_dir_fd=directory_descriptor,
                dst_dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
        except FileExistsError as exc:
            raise RuntimeError(RECEIPT_OUTPUT_EXISTS) from exc
        final_linked = True
        final_metadata = os.stat(
            normalized.name,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISREG(final_metadata.st_mode)
            or final_metadata.st_uid != os.getuid()
            or final_metadata.st_dev != metadata.st_dev
            or final_metadata.st_ino != metadata.st_ino
        ):
            raise RuntimeError(RECEIPT_WRITE_FAILED)
        os.unlink(temporary_name, dir_fd=directory_descriptor)
        temporary_name = ""
        remaining = os.stat(
            normalized.name,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
        if remaining.st_nlink != 1 or stat.S_IMODE(remaining.st_mode) != 0o600:
            raise RuntimeError(RECEIPT_WRITE_FAILED)
        artifact = _CreatedReceiptArtifact(
            path=normalized,
            device=remaining.st_dev,
            inode=remaining.st_ino,
            ctime_ns=remaining.st_ctime_ns,
            size=remaining.st_size,
        )
        os.fsync(directory_descriptor)
        return artifact
    except BaseException:
        if descriptor >= 0:
            with contextlib.suppress(OSError):
                os.close(descriptor)
        if final_linked and artifact is not None:
            with contextlib.suppress(OSError):
                current = os.stat(
                    normalized.name,
                    dir_fd=directory_descriptor,
                    follow_symlinks=False,
                )
                if (
                    current.st_dev == artifact.device
                    and current.st_ino == artifact.inode
                ):
                    os.unlink(normalized.name, dir_fd=directory_descriptor)
        if temporary_name:
            with contextlib.suppress(OSError):
                os.unlink(temporary_name, dir_fd=directory_descriptor)
        with contextlib.suppress(OSError):
            os.fsync(directory_descriptor)
        raise
    finally:
        os.close(directory_descriptor)


def _persist_runtime_receipt(
    path: Path,
    payload: dict[str, object],
    *,
    created_artifacts: dict[Path, _CreatedReceiptArtifact] | None = None,
) -> dict[str, object]:
    artifact = _atomic_receipt(path, payload)
    if created_artifacts is not None:
        created_artifacts[artifact.path] = artifact
    return register_candidate_receipt(artifact.path, require_pending=True)


def _embedded_spatial_browser_receipt(
    runtime_receipt: dict[str, object],
) -> dict[str, object]:
    spatial_handoff = runtime_receipt.get("spatial_handoff_runtime")
    if not isinstance(spatial_handoff, dict):
        raise RuntimeError(SPATIAL_BROWSER_RECEIPT_INVALID)
    browser_receipt = spatial_handoff.get("candidate_browser_gate")
    if (
        not isinstance(browser_receipt, dict)
        or browser_receipt.get("schema") != SPATIAL_BROWSER_RECEIPT_SCHEMA
        or browser_receipt.get("status") != "pass"
        or browser_receipt.get("secret_material_recorded") is not False
    ):
        raise RuntimeError(SPATIAL_BROWSER_RECEIPT_INVALID)
    return dict(browser_receipt)


def _persist_spatial_browser_receipt(
    path: Path,
    runtime_receipt: dict[str, object],
    *,
    created_artifacts: dict[Path, _CreatedReceiptArtifact] | None = None,
) -> _CreatedReceiptArtifact:
    artifact = _atomic_receipt(
        path,
        _embedded_spatial_browser_receipt(runtime_receipt),
    )
    if created_artifacts is not None:
        created_artifacts[artifact.path] = artifact
    return artifact


def _assert_recovered_candidate_runtime(
    *,
    receipt: dict[str, object],
    compose: list[str],
    environment: dict[str, str],
    project: str,
    base_url: str,
    projection: dict[str, object],
    candidate_env: dict[str, str],
    compose_attestation: dict[str, object],
    execution_inputs_evidence: dict[str, object],
    execution_environment_sha256: str,
    vexp_authority: CandidateVexpMutationAuthority,
    vexp_mutation_evidence: list[dict[str, object]],
) -> None:
    if any(receipt.get(name) != value for name, value in projection.items()):
        raise RuntimeError("manfred_candidate_recovered_projection_identity_invalid")
    if (
        receipt.get("compose_attestation") != compose_attestation
        or receipt.get("execution_inputs") != execution_inputs_evidence
    ):
        raise RuntimeError("manfred_candidate_recovered_execution_identity_invalid")
    runtime_projection = _candidate_runtime_projection_evidence(
        compose=compose,
        environment=environment,
        projection=projection,
        vexp_authority=vexp_authority,
        vexp_mutation_evidence=vexp_mutation_evidence,
    )
    if (
        receipt.get("runtime_projection_initial") != runtime_projection
        or receipt.get("runtime_projection_final") != runtime_projection
        or receipt.get("runtime_projection_identity_stable") is not True
    ):
        raise RuntimeError("manfred_candidate_recovered_projection_runtime_invalid")
    current_images = _candidate_container_image_evidence(
        compose=compose,
        environment=environment,
        project=project,
        projection=projection,
    )
    if (
        receipt.get("candidate_container_images") != current_images
        or receipt.get("candidate_container_images_initial") != current_images
        or receipt.get("candidate_container_images_final") != current_images
        or receipt.get("candidate_container_image_identity_stable") is not True
    ):
        raise RuntimeError("manfred_candidate_recovered_image_identity_invalid")
    runtime_identity = _candidate_runtime_version_identity(
        base_url,
        expected_commit=str(projection["projection_commit"]),
        oci_image_revision=str(current_images["revision_label"]),
    )
    if receipt.get("runtime_version_identity") != runtime_identity:
        raise RuntimeError("manfred_candidate_recovered_runtime_identity_invalid")
    runtime_posture = _candidate_api_runtime_posture(
        compose=compose,
        environment=environment,
        candidate_env=candidate_env,
        project=project,
        projection=projection,
        execution_environment_sha256=execution_environment_sha256,
    )
    if receipt.get("runtime_api_posture") != runtime_posture:
        raise RuntimeError("manfred_candidate_recovered_runtime_posture_invalid")
    _assert_redis(
        compose,
        environment,
        vexp_authority=vexp_authority,
        vexp_mutation_evidence=vexp_mutation_evidence,
    )
    _assert_logs_clean(compose, environment)


def _assert_live_recovery_unchanged(
    *,
    before: dict[str, object],
) -> None:
    after = _live_snapshot()
    _assert_live_unchanged(before, after)
    _assert_live_http()


def _prove_candidate_with_execution_inputs(
    *,
    receipt_path: Path,
    wait_seconds: int,
    env: dict[str, str],
    projection: dict[str, object],
    compose_attestation: dict[str, object],
    execution_inputs: _SealedExecutionInputs,
    vexp_authority: CandidateVexpMutationAuthority,
    vexp_entry_evidence: dict[str, object],
    spatial_browser_receipt_path: Path | None = None,
) -> dict[str, object]:
    if spatial_browser_receipt_path is not None:
        raise RuntimeError(
            "manfred_candidate_spatial_browser_receipt_forbidden_in_conversation_only"
        )
    env_file = execution_inputs.environment_path
    compose_file = execution_inputs.compose_path
    receipt_path = _normalized_receipt_path(receipt_path)
    contribution_receipt = receipt_path.parent / "candidate-contribution.private.json"
    if contribution_receipt == receipt_path:
        raise RuntimeError(RECEIPT_PATH_INVALID)
    contribution_receipt = _normalized_receipt_path(contribution_receipt)
    if spatial_browser_receipt_path is not None:
        spatial_browser_receipt_path = _normalized_receipt_path(
            spatial_browser_receipt_path
        )
        if spatial_browser_receipt_path in {receipt_path, contribution_receipt}:
            raise RuntimeError(RECEIPT_PATH_INVALID)
        spatial_browser_receipt_path = _assert_new_receipt_path(
            spatial_browser_receipt_path
        )
    project = _validate_project_name(env["EA_MANFRED_COMPOSE_PROJECT"])
    port = int(env["EA_MANFRED_HOST_PORT"])
    compose_environment = _compose_environment(
        env,
        execution_env_file=env_file,
    )
    compose_environment["EA_MANFRED_IMAGE"] = str(projection["prepared_image_id"])
    _assert_sealed_execution_inputs_current(execution_inputs)
    rendered = _rendered_compose(
        env_file,
        compose_file,
        project_name=project,
        environment=compose_environment,
        resolve_env_files=True,
    )
    source_rendered = _rendered_compose(
        env_file,
        compose_file,
        project_name=project,
        environment=compose_environment,
        resolve_env_files=False,
    )
    _assert_compose_isolation(
        rendered,
        source_rendered,
        env=env,
        env_file=env_file,
        prepared_image_id=str(projection["prepared_image_id"]),
    )
    _assert_sealed_execution_inputs_current(execution_inputs)
    compose = _compose_argv(project, env_file, compose_file)
    base_url = f"http://127.0.0.1:{port}"
    vexp_mutation_evidence: list[dict[str, object]] = []

    @contextlib.contextmanager
    def candidate_interaction_authority(
        *,
        operation: str,
        argv: list[str],
        target: str,
        minimum_validity_seconds: float,
    ):
        with vexp_authority.mutation(
            "before_candidate_interaction",
            minimum_validity_seconds=minimum_validity_seconds,
        ) as lease:
            record = _begin_candidate_operation(
                vexp_mutation_evidence,
                operation=operation,
                argv=argv,
                target=target,
                authority=dict(lease.authority_evidence),
            )
            try:
                yield lease
            except BaseException:
                raise
            else:
                record["runner_acknowledged"] = True

    def cleanup_candidate_project() -> None:
        _assert_sealed_execution_inputs_current(execution_inputs)
        _cleanup_candidate_project(
            compose=compose,
            environment=compose_environment,
            project=project,
            vexp_authority=vexp_authority,
            vexp_mutation_evidence=vexp_mutation_evidence,
        )

    def transport_request(
        request_base_url: str,
        path: str,
        *,
        method: str = "GET",
        payload: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
        expected: set[int] | None = None,
        follow_redirects: bool = True,
    ) -> tuple[int, bytes, dict[str, str]]:
        if str(request_base_url).rstrip("/") != base_url:
            raise RuntimeError("manfred_candidate_internal_transport_origin_invalid")
        return _candidate_api_loopback_request(
            compose,
            compose_environment,
            request_base_url,
            path,
            method=method,
            payload=payload,
            headers=headers,
            expected=expected,
            follow_redirects=follow_redirects,
            vexp_authority=vexp_authority,
            vexp_mutation_evidence=vexp_mutation_evidence,
        )

    with _hold_candidate_locks(project, port) as lock_evidence:
        image_locator_evidence = _assert_prepared_image_locator(projection)
        live_before = _live_snapshot()
        _assert_live_healthy(live_before)
        _assert_live_http()
        recovery = candidate_registry_recovery_state(
            project=project,
            port=port,
            receipt_path=receipt_path,
            image=str(projection["prepared_image_locator"]),
            image_id=str(projection["prepared_image_id"]),
            revision=str(projection["projection_commit"]),
        )
        recovery_state = str(recovery.get("state") or "")
        interrupted_publication_completed = False
        if recovery_state == "pending_receipt_unreadable":
            interrupted_publication_completed = (
                _complete_interrupted_receipt_publication(receipt_path)
            )
            if not interrupted_publication_completed:
                raise RuntimeError("manfred_candidate_pending_receipt_unrecoverable")
            recovery = candidate_registry_recovery_state(
                project=project,
                port=port,
                receipt_path=receipt_path,
                image=str(projection["prepared_image_locator"]),
                image_id=str(projection["prepared_image_id"]),
                revision=str(projection["projection_commit"]),
            )
            recovery_state = str(recovery.get("state") or "")
        launch_recovery_evidence: dict[str, object] = {
            "state_before_launch": recovery_state,
            "crash_intent_reconciled": False,
            "pending_contribution_reconciled": False,
            "existing_receipt_resumed": False,
            "interrupted_receipt_publication_completed": (
                interrupted_publication_completed
            ),
        }
        if recovery_state in {"pending_receipt", "registered_receipt"}:
            recovered_receipt = recovery.get("runtime_receipt")
            if not isinstance(recovered_receipt, dict):
                raise RuntimeError("manfred_candidate_registry_recovery_invalid")
            try:
                _assert_recovered_candidate_runtime(
                    receipt=dict(recovered_receipt),
                    compose=compose,
                    environment=compose_environment,
                    project=project,
                    base_url=base_url,
                    projection=projection,
                    candidate_env=env,
                    compose_attestation=compose_attestation,
                    execution_inputs_evidence=execution_inputs.evidence,
                    execution_environment_sha256=str(
                        execution_inputs.evidence["environment_sha256"]
                    ),
                    vexp_authority=vexp_authority,
                    vexp_mutation_evidence=vexp_mutation_evidence,
                )
                _assert_live_recovery_unchanged(
                    before=live_before,
                )
                if recovery_state == "pending_receipt":
                    registration = register_candidate_receipt(
                        receipt_path,
                        require_pending=True,
                    )
                    if registration.get("registered") is not True:
                        raise RuntimeError(
                            "manfred_candidate_registry_registration_failed"
                        )
            except BaseException as recovery_exc:
                if recovery_state == "registered_receipt":
                    raise RuntimeError(
                        "manfred_candidate_registered_runtime_unavailable"
                    ) from recovery_exc
                recovery_errors: list[str] = []
                with _shield_cleanup_interrupts():
                    try:
                        cleanup_candidate_project()
                        _assert_candidate_project_absent(project)
                    except BaseException:
                        recovery_errors.append("candidate_resources_remain")
                    try:
                        _wait_for_loopback_port_not_listening(port)
                    except BaseException:
                        recovery_errors.append("candidate_port_remains_bound")
                    try:
                        _assert_live_recovery_unchanged(
                            before=live_before,
                        )
                    except BaseException:
                        recovery_errors.append("live_ea_changed_or_unhealthy")
                    if not recovery_errors:
                        try:
                            cleared = clear_candidate_pending_exact(
                                project=project,
                                port=port,
                                receipt_path=receipt_path,
                                image=str(projection["prepared_image_locator"]),
                                image_id=str(projection["prepared_image_id"]),
                                revision=str(projection["projection_commit"]),
                                resources_absent=True,
                                expected_receipt_sha256=str(
                                    recovery.get("receipt_sha256") or ""
                                ),
                            )
                            if cleared.get("pending_cleared") is not True:
                                raise RuntimeError(
                                    "manfred_candidate_pending_registry_cleanup_failed"
                                )
                        except BaseException:
                            recovery_errors.append(
                                "candidate_pending_registry_cleanup_failed"
                            )
                if recovery_errors:
                    raise RuntimeError(
                        "manfred_candidate_crash_recovery_failed:"
                        + ",".join(recovery_errors)
                    ) from recovery_exc
                raise RuntimeError(
                    "manfred_candidate_recovered_receipt_runtime_invalid:"
                    "fresh_receipt_path_required"
                ) from recovery_exc
            if spatial_browser_receipt_path is not None:
                _persist_spatial_browser_receipt(
                    spatial_browser_receipt_path,
                    dict(recovered_receipt),
                )
            return dict(recovered_receipt)
        if recovery_state == "pending_only":
            recovery_errors = []
            with _shield_cleanup_interrupts():
                try:
                    contribution_artifact = _receipt_artifact_if_present(
                        contribution_receipt
                    )
                    if contribution_artifact is not None:
                        with candidate_interaction_authority(
                            operation="candidate_contribution_recovery",
                            argv=[
                                "withdraw_candidate_contribution",
                                "--base-url",
                                base_url,
                                "--receipt",
                                str(contribution_receipt),
                            ],
                            target=str(contribution_receipt),
                            minimum_validity_seconds=60
                        ):
                            launch_recovery_evidence[
                                "pending_contribution_reconciled"
                            ] = _withdraw_candidate_contribution_if_present(
                                base_url,
                                contribution_receipt,
                                expected_artifact=contribution_artifact,
                            )
                    else:
                        launch_recovery_evidence[
                            "pending_contribution_reconciled"
                        ] = False
                except BaseException as recovery_exc:
                    raise RuntimeError(
                        "manfred_candidate_pending_contribution_recovery_failed"
                    ) from recovery_exc
                try:
                    cleanup_candidate_project()
                    _assert_candidate_project_absent(project)
                except BaseException:
                    recovery_errors.append("candidate_resources_remain")
                try:
                    _wait_for_loopback_port_not_listening(port)
                except BaseException:
                    recovery_errors.append("candidate_port_remains_bound")
                try:
                    _assert_live_recovery_unchanged(
                        before=live_before,
                    )
                except BaseException:
                    recovery_errors.append("live_ea_changed_or_unhealthy")
                if not recovery_errors:
                    try:
                        cleared = clear_candidate_pending_exact(
                            project=project,
                            port=port,
                            receipt_path=receipt_path,
                            image=str(projection["prepared_image_locator"]),
                            image_id=str(projection["prepared_image_id"]),
                            revision=str(projection["projection_commit"]),
                            resources_absent=True,
                        )
                        if cleared.get("pending_cleared") is not True:
                            raise RuntimeError(
                                "manfred_candidate_pending_registry_cleanup_failed"
                            )
                    except BaseException:
                        recovery_errors.append(
                            "candidate_pending_registry_cleanup_failed"
                        )
            if recovery_errors:
                raise RuntimeError(
                    "manfred_candidate_crash_recovery_failed:"
                    + ",".join(recovery_errors)
                )
            launch_recovery_evidence["crash_intent_reconciled"] = True
            raise RuntimeError(
                "manfred_candidate_pending_recovery_completed:"
                "fresh_invocation_required"
            )
        elif recovery_state != "absent":
            raise RuntimeError("manfred_candidate_registry_recovery_invalid")

        receipt_path = _assert_new_receipt_path(receipt_path)
        contribution_receipt = _assert_new_receipt_path(contribution_receipt)
        preflight = _candidate_preflight(project, port)
        up_started = False
        pending_registered = False
        created_artifacts: dict[Path, _CreatedReceiptArtifact] = {}
        try:
            register_candidate_pending(
                project=project,
                port=port,
                receipt_path=receipt_path,
                image=str(projection["prepared_image_locator"]),
                image_id=str(projection["prepared_image_id"]),
                revision=str(projection["projection_commit"]),
            )
            pending_registered = True
            _assert_sealed_execution_inputs_current(execution_inputs)
            up_argv = [
                *compose,
                "up",
                "-d",
                "--wait",
                "--wait-timeout",
                str(wait_seconds),
            ]
            with vexp_authority.mutation(
                "before_candidate_up",
                minimum_validity_seconds=wait_seconds + 60,
            ) as lease:
                operation_record = _begin_candidate_operation(
                    vexp_mutation_evidence,
                    operation="compose_up",
                    argv=up_argv,
                    target=project,
                    authority=dict(lease.authority_evidence),
                )
                up_started = True
                _run(
                    up_argv,
                    timeout=lease.command_timeout(wait_seconds + 60),
                    environment=compose_environment,
                )
                operation_record["runner_acknowledged"] = True
            _assert_redis(
                compose,
                compose_environment,
                vexp_authority=vexp_authority,
                vexp_mutation_evidence=vexp_mutation_evidence,
            )
            runtime_projection_initial = _candidate_runtime_projection_evidence(
                compose=compose,
                environment=compose_environment,
                projection=projection,
                vexp_authority=vexp_authority,
                vexp_mutation_evidence=vexp_mutation_evidence,
            )

            _assert_new_receipt_path(contribution_receipt)
            try:
                with candidate_interaction_authority(
                    operation="candidate_smoke",
                    argv=[
                        "verify_candidate",
                        "--base-url",
                        base_url,
                        "--public-origin",
                        env["EA_PUBLIC_APP_BASE_URL"],
                        "--conversation-only",
                    ],
                    target=base_url,
                    minimum_validity_seconds=wait_seconds + 60
                ):
                    first_smoke = verify_candidate(
                        base_url=base_url,
                        public_origin=env["EA_PUBLIC_APP_BASE_URL"],
                        wait_seconds=wait_seconds,
                        submit_receipt=None,
                        withdraw_receipt=None,
                        transport_request=transport_request,
                        conversation_only=True,
                    )
            finally:
                contribution_artifact = _receipt_artifact_if_present(
                    contribution_receipt
                )
                if contribution_artifact is not None:
                    created_artifacts[contribution_artifact.path] = (
                        contribution_artifact
                    )
            api_before_restart = (
                _run(
                    [*compose, "ps", "-q", "api"],
                    timeout=30,
                    environment=compose_environment,
                )
                .decode()
                .strip()
            )
            if not api_before_restart:
                raise RuntimeError("manfred_candidate_api_missing")
            _assert_sealed_execution_inputs_current(execution_inputs)
            restart_argv = [*compose, "restart", "api"]
            with vexp_authority.mutation(
                "before_candidate_restart",
                minimum_validity_seconds=90,
            ) as lease:
                operation_record = _begin_candidate_operation(
                    vexp_mutation_evidence,
                    operation="compose_restart_api",
                    argv=restart_argv,
                    target=f"{project}:api",
                    authority=dict(lease.authority_evidence),
                )
                _run(
                    restart_argv,
                    timeout=lease.command_timeout(90),
                    environment=compose_environment,
                )
                operation_record["runner_acknowledged"] = True
            _wait_for_candidate_api_healthy(
                compose=compose,
                environment=compose_environment,
                expected_container_id=api_before_restart,
                wait_seconds=wait_seconds,
            )
            with candidate_interaction_authority(
                operation="candidate_smoke_after_restart",
                argv=[
                    "verify_candidate",
                    "--base-url",
                    base_url,
                    "--public-origin",
                    env["EA_PUBLIC_APP_BASE_URL"],
                    "--conversation-only",
                ],
                target=base_url,
                minimum_validity_seconds=wait_seconds + 60
            ):
                second_smoke = verify_candidate(
                    base_url=base_url,
                    public_origin=env["EA_PUBLIC_APP_BASE_URL"],
                    wait_seconds=wait_seconds,
                    submit_receipt=None,
                    withdraw_receipt=None,
                    transport_request=transport_request,
                    conversation_only=True,
                )
            api_after_restart = (
                _run(
                    [*compose, "ps", "-q", "api"],
                    timeout=30,
                    environment=compose_environment,
                )
                .decode()
                .strip()
            )
            if api_after_restart != api_before_restart:
                raise RuntimeError("manfred_candidate_restart_recreated_container")
            _assert_redis(
                compose,
                compose_environment,
                vexp_authority=vexp_authority,
                vexp_mutation_evidence=vexp_mutation_evidence,
            )
            conversation_state_mode = _assert_conversation_state_mode(
                compose,
                compose_environment,
                vexp_authority=vexp_authority,
                vexp_mutation_evidence=vexp_mutation_evidence,
            )
            runtime_api_posture = _candidate_api_runtime_posture(
                compose=compose,
                environment=compose_environment,
                candidate_env=env,
                project=project,
                projection=projection,
                execution_environment_sha256=str(
                    execution_inputs.evidence["environment_sha256"]
                ),
            )
            if runtime_api_posture["api_container_id"] != api_after_restart:
                raise RuntimeError("manfred_candidate_runtime_posture_identity_invalid")
            initial_container_images = _candidate_container_image_evidence(
                compose=compose,
                environment=compose_environment,
                project=project,
                projection=projection,
            )
            image_id = str(projection["prepared_image_id"])
            image_source_revision = str(projection["projection_commit"])
            with candidate_interaction_authority(
                operation="runtime_identity_probe",
                argv=[
                    "candidate_runtime_version_identity",
                    "--base-url",
                    base_url,
                    "--expected-commit",
                    image_source_revision,
                ],
                target=base_url,
                minimum_validity_seconds=60,
            ):
                runtime_version_identity = _candidate_runtime_version_identity(
                    base_url,
                    expected_commit=image_source_revision,
                    oci_image_revision=str(
                        initial_container_images["revision_label"]
                    ),
                )
            runtime_source_revision = str(
                runtime_version_identity["source_revision_header"]
            )
            runtime_authority_commit = str(runtime_version_identity["body_commit_sha"])
            with candidate_interaction_authority(
                operation="browser_surface_audit",
                argv=[
                    "audit_browser_surface",
                    "--base-url",
                    base_url,
                    "--public-origin",
                    env["EA_PUBLIC_APP_BASE_URL"],
                    "--conversation-only",
                ],
                target=base_url,
                minimum_validity_seconds=180,
            ):
                browser_surface = audit_browser_surface(
                    base_url,
                    public_origin=env["EA_PUBLIC_APP_BASE_URL"],
                    conversation_only=True,
                )
            _assert_logs_clean(compose, compose_environment)
            candidate_openapi_retirement = _assert_candidate_openapi_retired(base_url)
            candidate_openapi_contract, candidate_openapi = (
                _candidate_openapi_contract_snapshot(
                    compose,
                    compose_environment,
                    vexp_authority=vexp_authority,
                    vexp_mutation_evidence=vexp_mutation_evidence,
                )
            )
            del candidate_openapi_contract
            final_container_images = _candidate_container_image_evidence(
                compose=compose,
                environment=compose_environment,
                project=project,
                projection=projection,
            )
            if final_container_images != initial_container_images:
                raise RuntimeError("manfred_candidate_runtime_image_identity_changed")
            runtime_projection_final = _candidate_runtime_projection_evidence(
                compose=compose,
                environment=compose_environment,
                projection=projection,
                vexp_authority=vexp_authority,
                vexp_mutation_evidence=vexp_mutation_evidence,
            )
            if runtime_projection_final != runtime_projection_initial:
                raise RuntimeError("manfred_candidate_runtime_projection_changed")
            live_after = _live_snapshot()
            _assert_live_unchanged(live_before, live_after)
            _assert_live_http()
            receipt = {
                "schema": RECEIPT_SCHEMA,
                "status": "pass",
                "producer_sha256": _producer_sha256(),
                "observed_at": datetime.now(timezone.utc)
                .replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z"),
                "image": env["EA_MANFRED_IMAGE"],
                "image_id": image_id,
                "image_source_revision": image_source_revision,
                "image_locator_evidence": image_locator_evidence,
                "compose_uses_immutable_image_id": True,
                "candidate_container_images": final_container_images,
                "candidate_container_images_initial": initial_container_images,
                "candidate_container_images_final": final_container_images,
                "candidate_container_image_identity_stable": True,
                "runtime_projection_initial": runtime_projection_initial,
                "runtime_projection_final": runtime_projection_final,
                "runtime_projection_identity_stable": True,
                "runtime_version_identity": runtime_version_identity,
                "runtime_source_revision": runtime_source_revision,
                "runtime_authority_commit": runtime_authority_commit,
                "runtime_revision_matches_image": True,
                **projection,
                "compose_project": project,
                "compose_project_isolated": True,
                "compose_attestation": compose_attestation,
                "execution_inputs": execution_inputs.evidence,
                "compose_environment_bound_to_candidate_env": True,
                "candidate_named_resources": _candidate_named_resources(project),
                "candidate_preflight": preflight,
                "registry_recovery": launch_recovery_evidence,
                "locks": lock_evidence,
                "project_lock": lock_evidence["project"],
                "port_lock": lock_evidence["port"],
                "candidate_api_container_id": api_after_restart,
                "runtime_api_posture": runtime_api_posture,
                "candidate_port": port,
                "api_network_internal": True,
                "gateway_has_runtime_secrets": False,
                "provider_credentials_present": False,
                "provider_calls_performed": False,
                "redis_ping": "PONG",
                "conversation_state_mode": conversation_state_mode,
                "memorial_surface": MEMORIAL_SURFACE,
                "spatial_scope": SPATIAL_SCOPE,
                "public_property_tours_tested": False,
                "memorial_spatial_receipt_generated": False,
                "first_smoke_checks": first_smoke.get("checks", []),
                "second_smoke_checks": second_smoke.get("checks", []),
                "browser_surface": browser_surface,
                "openapi_contract": {
                    "candidate": candidate_openapi,
                    "candidate_public_endpoint": candidate_openapi_retirement,
                    "live_comparison_status": "deferred_to_governed_promotion",
                    "candidate_preserves_live_contract": False,
                    "candidate_live_contract_claim_allowed": False,
                },
                "live_ea_api_unchanged": True,
                "live_ea_api": _main_api_snapshot(live_after),
                "live_ea_project_before": live_before,
                "live_ea_project_after": live_after,
                "live_ea_project_unchanged": True,
                "candidate_left_running_for_soak": True,
                "promotion_authority": False,
            }
            with vexp_authority.finalization() as finalization_evidence:
                receipt["vexp_candidate_mutation_authority"] = {
                    "entry": dict(vexp_entry_evidence),
                    "mutations": [dict(row) for row in vexp_mutation_evidence],
                    "finalization": dict(finalization_evidence),
                    "cleanup_requires_positive_authority": True,
                    "retention_timer_only_authority_free_cleanup": True,
                }
                with _shield_cleanup_interrupts():
                    registration = _persist_runtime_receipt(
                        receipt_path,
                        receipt,
                        created_artifacts=created_artifacts,
                    )
                    if registration.get("registered") is not True:
                        raise RuntimeError(
                            "manfred_candidate_registry_registration_failed"
                        )
            pending_registered = False
            return receipt
        except BaseException as exc:
            if not up_started:
                if pending_registered:
                    cleared = clear_candidate_pending(project)
                    if cleared.get("pending_cleared") is not True:
                        raise RuntimeError(
                            "manfred_candidate_pending_registry_cleanup_failed"
                        ) from exc
                raise
            recovery_errors: list[str] = []
            with _shield_cleanup_interrupts():
                contribution_withdrawal_blocked = False
                try:
                    contribution_artifact = _receipt_artifact_if_present(
                        contribution_receipt
                    )
                    if contribution_artifact is not None:
                        with candidate_interaction_authority(
                            operation="candidate_contribution_recovery",
                            argv=[
                                "withdraw_candidate_contribution",
                                "--base-url",
                                base_url,
                                "--receipt",
                                str(contribution_receipt),
                            ],
                            target=str(contribution_receipt),
                            minimum_validity_seconds=60
                        ):
                            _withdraw_candidate_contribution_if_present(
                                base_url,
                                contribution_receipt,
                                expected_artifact=contribution_artifact,
                            )
                except BaseException:
                    contribution_withdrawal_blocked = True
                    recovery_errors.append("candidate_contribution_withdrawal_failed")
                try:
                    if not contribution_withdrawal_blocked:
                        cleanup_candidate_project()
                except BaseException:
                    recovery_errors.append("candidate_compose_down_failed")
                if not contribution_withdrawal_blocked:
                    try:
                        _assert_candidate_project_absent(project)
                    except BaseException:
                        recovery_errors.append("candidate_resources_remain")
                    try:
                        _wait_for_loopback_port_not_listening(port)
                    except BaseException:
                        recovery_errors.append("candidate_port_remains_bound")
                    try:
                        contribution_artifact = created_artifacts.get(
                            contribution_receipt
                        )
                        if (
                            contribution_artifact is not None
                            and not _unlink_created_receipt_artifact(
                                contribution_artifact
                            )
                        ):
                            raise RuntimeError(RECEIPT_ARTIFACT_INVALID)
                    except BaseException:
                        recovery_errors.append(
                            "candidate_private_receipt_cleanup_failed"
                        )
                try:
                    runtime_artifact = created_artifacts.get(receipt_path)
                    if (
                        runtime_artifact is not None
                        and not _unlink_created_receipt_artifact(runtime_artifact)
                    ):
                        raise RuntimeError(RECEIPT_ARTIFACT_INVALID)
                except BaseException:
                    recovery_errors.append("candidate_runtime_receipt_cleanup_failed")
                try:
                    recovered_live = _live_snapshot()
                    _assert_live_unchanged(live_before, recovered_live)
                    _assert_live_http()
                except BaseException:
                    recovery_errors.append("live_ea_changed_or_unhealthy")
                if pending_registered and not recovery_errors:
                    try:
                        cleared = clear_candidate_pending(project)
                        if cleared.get("pending_cleared") is not True:
                            raise RuntimeError(
                                "manfred_candidate_pending_registry_cleanup_failed"
                            )
                        pending_registered = False
                    except BaseException:
                        recovery_errors.append(
                            "candidate_pending_registry_cleanup_failed"
                        )
            if recovery_errors:
                if not isinstance(exc, Exception):
                    exc.add_note(
                        "manfred_candidate_recovery_failed:" + ",".join(recovery_errors)
                    )
                    raise
                original = str(exc).strip()[:120] or type(exc).__name__
                raise RuntimeError(
                    f"{original};manfred_candidate_recovery_failed:{','.join(recovery_errors)}"
                ) from exc
            raise


def prove_candidate(
    *,
    env_file: Path,
    compose_file: Path,
    receipt_path: Path,
    wait_seconds: int,
    spatial_browser_receipt_path: Path | None = None,
    vexp_state_path: Path = DEFAULT_SENTINEL_STATE_PATH,
    vexp_state_owner_uid: int | None = None,
    vexp_authority: CandidateVexpMutationAuthority | None = None,
) -> dict[str, object]:
    canonical_env_file = Path(
        os.path.abspath(os.fspath(env_file.expanduser()))
    )
    environment_bytes = _read_private_output(
        canonical_env_file,
        maximum=CANDIDATE_ENV_MAX_BYTES,
    )
    if environment_bytes is None:  # pragma: no cover - missing_ok is false
        raise RuntimeError("manfred_candidate_env_missing")
    env = _assert_env_allowlist(
        canonical_env_file,
        environment_bytes=environment_bytes,
    )
    compose_attestation, compose_bytes = _candidate_compose_source_snapshot(
        compose_file,
        expected_commit=env["EA_MANFRED_COMMIT"],
    )
    projection = _projection_evidence(env)
    authority = vexp_authority or candidate_vexp_authority(
        state_path=Path(vexp_state_path),
        state_owner_uid=(
            os.geteuid()
            if vexp_state_owner_uid is None
            else vexp_state_owner_uid
        ),
    )
    entry_evidence = authority.require_current()
    with _sealed_candidate_execution_inputs(
        compose_bytes=compose_bytes,
        environment_bytes=environment_bytes,
        environment=env,
        compose_attestation=compose_attestation,
        compose_image_id=str(projection["prepared_image_id"]),
    ) as execution_inputs:
        return _prove_candidate_with_execution_inputs(
            receipt_path=receipt_path,
            wait_seconds=wait_seconds,
            env=env,
            projection=projection,
            compose_attestation=compose_attestation,
            execution_inputs=execution_inputs,
            vexp_authority=authority,
            vexp_entry_evidence=entry_evidence,
            spatial_browser_receipt_path=spatial_browser_receipt_path,
        )


def build_parser() -> argparse.ArgumentParser:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Launch and prove the isolated provider-free Manfred candidate."
    )
    parser.add_argument("--env-file", required=True)
    parser.add_argument(
        "--compose-file",
        default=str(root / "deploy/manfred-memorial/docker-compose.candidate.yml"),
    )
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--wait-seconds", type=int, default=240)
    parser.add_argument("--vexp-state-path", required=True)
    parser.add_argument("--vexp-state-owner-uid", required=True, type=int)
    return parser


def _bounded_failure_diagnostics(exc: Exception) -> dict[str, object] | None:
    raw = getattr(exc, "diagnostics", None)
    if not isinstance(raw, dict):
        return None
    if raw.get("schema") != ROUTE_ACTIONABILITY_DIAGNOSTIC_SCHEMA:
        return None
    try:
        encoded = json.dumps(
            raw,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        return None
    if not encoded or len(encoded) > MAX_FAILURE_DIAGNOSTIC_BYTES:
        return None
    decoded = json.loads(encoded)
    return decoded if isinstance(decoded, dict) else None


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        with _governed_signal_handlers():
            receipt = prove_candidate(
                env_file=Path(args.env_file),
                compose_file=Path(args.compose_file),
                receipt_path=Path(args.receipt).expanduser().resolve(),
                wait_seconds=max(60, min(600, int(args.wait_seconds))),
                vexp_state_path=Path(args.vexp_state_path),
                vexp_state_owner_uid=args.vexp_state_owner_uid,
            )
    except GovernedSignalInterrupt as exc:
        print(
            json.dumps(
                {
                    "schema": RECEIPT_SCHEMA,
                    "status": "interrupted",
                    "signal": signal.Signals(exc.signum).name,
                    "live_ea_api_mutation_requested": False,
                },
                sort_keys=True,
            )
        )
        return 128 + exc.signum
    except KeyboardInterrupt:
        print(
            json.dumps(
                {
                    "schema": RECEIPT_SCHEMA,
                    "status": "interrupted",
                    "signal": "SIGINT",
                    "live_ea_api_mutation_requested": False,
                },
                sort_keys=True,
            )
        )
        return 130
    except Exception as exc:
        failure: dict[str, object] = {
            "schema": RECEIPT_SCHEMA,
            "status": "fail",
            "error": str(exc)[:200],
            "live_ea_api_mutation_requested": False,
        }
        diagnostics = _bounded_failure_diagnostics(exc)
        if diagnostics is not None:
            failure["diagnostics"] = diagnostics
        print(json.dumps(failure, sort_keys=True))
        return 1
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
