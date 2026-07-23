#!/usr/bin/env python3
"""Governed, API-only deployment lane for the public Manfred memorial.

The general EA deploy script intentionally manages the complete legacy runtime.
This lane is narrower: it may start ``ea-redis`` and may recreate only
``ea-api``. A failed post-change check restores the previous API image through
the exact Compose files and working directory recorded on the prior container.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import ipaddress
import json
import math
import os
import re
import stat
import subprocess  # nosec B404 - commands are fixed below
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Protocol, Sequence

try:
    from scripts.source_state_head import source_worktree_metadata
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from source_state_head import source_worktree_metadata

try:
    from scripts.prepare_ea_runtime_env import (
        RUNTIME_DIRECTORY as EA_RUNTIME_ENV_DIRECTORY,
        SanitizerError as RuntimeEnvSanitizerError,
        prepare_runtime_env,
        sanitize_env_bytes,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from prepare_ea_runtime_env import (  # type: ignore[no-redef]
        RUNTIME_DIRECTORY as EA_RUNTIME_ENV_DIRECTORY,
        SanitizerError as RuntimeEnvSanitizerError,
        prepare_runtime_env,
        sanitize_env_bytes,
    )

try:
    from scripts.ea_memorial_recovery_interlock import (
        MemorialRecoveryInterlockError,
        default_joint_recovery_journal_path,
        default_normalization_recovery_journal_path,
        require_joint_recovery_absent,
        require_normalization_recovery_absent,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from ea_memorial_recovery_interlock import (  # type: ignore[no-redef]
        MemorialRecoveryInterlockError,
        default_joint_recovery_journal_path,
        default_normalization_recovery_journal_path,
        require_joint_recovery_absent,
        require_normalization_recovery_absent,
    )

try:
    from scripts.memorial_bind_source_guard import (
        BindSourceGuardError,
        validate_memorial_bind_sources,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from memorial_bind_source_guard import (  # type: ignore[no-redef]
        BindSourceGuardError,
        validate_memorial_bind_sources,
    )

try:
    from scripts.prepare_manfred_memorial_candidate import (
        PROPERTY_ARTIFACT_COMMIT,
        PROPERTY_AUTHORITY_SHA256,
        PROPERTY_PRE_AUTHORITY_SHA256,
        PROPERTY_TOUR_SHA256,
        _spatial_package_sha256,
        _spatial_tree_snapshot,
        _tree_digest as _candidate_projection_tree_digest,
    )
except ModuleNotFoundError as exc:  # pragma: no cover - direct script execution
    if exc.name not in {"scripts", "scripts.prepare_manfred_memorial_candidate"}:
        raise
    from prepare_manfred_memorial_candidate import (  # type: ignore[no-redef]
        PROPERTY_ARTIFACT_COMMIT,
        PROPERTY_AUTHORITY_SHA256,
        PROPERTY_PRE_AUTHORITY_SHA256,
        PROPERTY_TOUR_SHA256,
        _spatial_package_sha256,
        _spatial_tree_snapshot,
        _tree_digest as _candidate_projection_tree_digest,
    )

try:
    from scripts.verify_manfred_spatial_candidate_browser import (
        validate_spatial_candidate_browser_receipt,
    )
except ModuleNotFoundError as exc:  # pragma: no cover - direct script execution
    if exc.name not in {
        "scripts",
        "scripts.verify_manfred_spatial_candidate_browser",
    }:
        raise
    from verify_manfred_spatial_candidate_browser import (  # type: ignore[no-redef]
        validate_spatial_candidate_browser_receipt,
    )


ROOT = Path(__file__).resolve().parents[1]
EA_RUNTIME_ENV_FILE = "ea_runtime.env"
EA_RUNTIME_LOCAL_ENV_FILE = "ea_runtime.local.env"
MEMORIAL_COMPOSE_FILE = "docker-compose.memorial.yml"
API_BASELINE_NORMALIZATION_COMPOSE_FILE = (
    "docker-compose.api-baseline-normalization.yml"
)
PROJECT_NAME = "ea"
API_SERVICE = "ea-api"
REDIS_SERVICE = "ea-redis"
MEMORIAL_SLUG = "manfred"
REQUIRED_CONTROL_TOUR_SLUG = (
    "360-tour-balkon-wohnung-in-neustift-layout-first-0146e6f9c6"
)
CONTROL_TOUR_COMPATIBLE_EVOLUTION_POLICY_ID = (
    "ea.control-tour.compatible-evolution.generated-viewer.v1"
)
CONTROL_TOUR_GENERATED_VIEWER_DISCLOSURE = (
    "Generated interactive reconstruction from the supplied floor plan. "
    "It is a layout aid, not a captured or provider-verified 3D scan."
)
PUBLIC_SPATIAL_VIEWER_RELPATH = "generated-reconstruction/viewer.html"
PUBLIC_SPATIAL_PROOF_RELPATH = "generated-reconstruction/reconstruction.json"
PUBLIC_SPATIAL_FLOORPLAN_RELPATH = "generated-reconstruction/source-floorplan.png"
PUBLIC_SPATIAL_JAVASCRIPT_RELPATHS = (
    "generated-reconstruction/vendor/three.module.js",
    "generated-reconstruction/vendor/examples/jsm/controls/OrbitControls.js",
)
PUBLIC_SPATIAL_DIGEST_ONLY_LABELS = frozenset(
    {"floorplan", "three_module", "orbit_controls"}
)
PUBLIC_SPATIAL_ALLOWED_FILE_RELPATHS = (
    "tour.json",
    PUBLIC_SPATIAL_VIEWER_RELPATH,
    PUBLIC_SPATIAL_PROOF_RELPATH,
    PUBLIC_SPATIAL_FLOORPLAN_RELPATH,
    *PUBLIC_SPATIAL_JAVASCRIPT_RELPATHS,
)
CONTROL_TOUR_SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,127}$")
DEPLOYMENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
IMAGE_ID_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
SHA256_HEX_PATTERN = re.compile(r"^[0-9a-f]{64}$")
SOURCE_REVISION_PATTERN = re.compile(r"^[0-9a-f]{40}$")
IMAGE_TAG_PATTERN = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$")
IMAGE_REPOSITORY_PATTERN = re.compile(
    r"^[a-z0-9]+(?:[._-][a-z0-9]+)*(?::[0-9]+)?"
    r"(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)*$"
)
DEFAULT_PUBLIC_HOSTS = ("myexternalbrain.com", "www.myexternalbrain.com")
BROWSER_ZERO_COUNT_FIELDS = (
    "automatic_provider_requests",
    "automatic_websockets",
    "external_requests",
    "failed_requests",
    "page_errors",
    "http_errors",
)
OPENAPI_EVIDENCE_FIELDS = frozenset(
    {
        "path_count",
        "operation_count",
        "schema_count",
        "security_scheme_count",
        "path_digest_sha256",
        "contract_digest_sha256",
    }
)
OPENAPI_HTTP_METHODS = frozenset(
    {"delete", "get", "head", "options", "patch", "post", "put", "trace"}
)
OPENAPI_RETIREMENT_POLICY_ID = "ea.openapi.safety-retirement.governed-spatial-routes.v1"
OPENAPI_RETIREMENT_ALLOWED_OPERATIONS = (
    "POST /v1/internal/governed-spatial-render/build",
    "POST /v1/internal/governed-spatial-render/compose",
)
OPENAPI_COMPATIBLE_EVOLUTION_POLICY_ID = (
    "ea.openapi.compatible-evolution.version-remote-reachability.v1"
)
OPENAPI_COMPATIBLE_EVOLUTION_ALLOWED_OPERATIONS = ("GET /version",)
FORWARD_ONLY_ENV_KEYS = {
    "EA_MEMORIAL_IMAGE",
    "EA_SOURCE_REVISION",
    "EA_DEPLOYMENT_ID",
    "EA_DEPLOYMENT_ID_SOURCE",
    "EA_DEPLOY_PRIMARY_MODE",
    "EA_DEPLOY_ENABLED_MODES",
    "EA_DEPLOY_COMPOSE_FILES",
    "EA_DEPLOY_COMPOSE_OVERRIDES",
    "COMPOSE_PROJECT_NAME",
}
ROLLBACK_ENV_PASSTHROUGH = {
    "DOCKER_CONFIG",
    "DOCKER_CONTEXT",
    "DOCKER_HOST",
    "HOME",
    "LANG",
    "LC_ALL",
    "PATH",
    "SSH_AUTH_SOCK",
    "TMPDIR",
    "USER",
    "XDG_RUNTIME_DIR",
}
ROLLBACK_MEMORIAL_CONTAINER_ENV_MAP = {
    "EA_SOURCE_REVISION": "EA_SOURCE_REVISION",
    "EA_ENABLE_PUBLIC_MEMORIALS": "EA_ENABLE_PUBLIC_MEMORIALS",
    "EA_HEALTHCHECK_MEMORIAL_SLUG": "EA_HEALTHCHECK_MEMORIAL_SLUG",
    "EA_PUBLIC_MEMORIAL_RATE_BACKEND": "EA_PUBLIC_MEMORIAL_RATE_BACKEND",
    "EA_PUBLIC_MEMORIAL_REDIS_URL": "EA_PUBLIC_MEMORIAL_REDIS_URL",
    "EA_PUBLIC_MEMORIAL_DIR": "EA_PUBLIC_MEMORIAL_DIR",
    "EA_PRIVATE_MEMORIAL_PROFILE_DIR": "EA_PRIVATE_MEMORIAL_PROFILE_DIR",
    "EA_MEMORIAL_LIVE_TTS_PLUGIN": "EA_MEMORIAL_LIVE_TTS_PLUGIN",
    "EA_MEMORIAL_TRUSTED_PROXY_CIDRS": "EA_TRUSTED_PROXY_CIDRS",
    "EA_MEMORIAL_TRUSTED_PUBLIC_ORIGIN_ALIASES": ("EA_TRUSTED_PUBLIC_ORIGIN_ALIASES"),
    "EA_MEMORIAL_ALLOWED_PUBLIC_HOSTS": "EA_ALLOWED_PUBLIC_HOSTS",
}
ROLLBACK_MEMORIAL_RENDER_ENV_KEYS = frozenset(
    {
        *ROLLBACK_MEMORIAL_CONTAINER_ENV_MAP,
        "EA_MEMORIAL_IMAGE",
        "EA_MEMORIAL_DATA_HOST_PATH",
        "EA_MEMORIAL_RUNTIME_HOST_PATH",
    }
)
ROLLBACK_CAPSULE_CONTRACT_NAME = "ea.memorial_api_rollback_capsule.v2"
ROLLBACK_CAPSULE_VERSION = 2
ROLLBACK_CAPSULE_FILE_SUFFIX = ".rollback-capsule.compose.json"
ROLLBACK_CAPSULE_ALLOWED_RUNTIME_DIFFERENCES = (
    "compose_managed_labels",
    "container_and_start_timestamps",
    "container_id",
    "engine_assigned_endpoint_identity_for_dynamic_network_attachments",
)
ROLLBACK_RECOVERY_CONTRACT_NAME = "ea.memorial_api_active_recovery.v2"
ROLLBACK_RECOVERY_VERSION = 2
TRUSTED_EXTERNAL_COMPOSE_LAYER_ORDER = (
    "docker-compose.yml",
    "docker-compose.prod.yml",
    MEMORIAL_COMPOSE_FILE,
    "docker-compose.whatsapp-web-session.yml",
    "docker-compose.cloudflared.yml",
)
TRUSTED_EXTERNAL_BRIDGE_ONLY_LAYERS = frozenset(
    {
        "docker-compose.whatsapp-web-session.yml",
        "docker-compose.cloudflared.yml",
    }
)
TRUSTED_EXTERNAL_BRIDGE_REPLACEABLE_LAYERS = frozenset({MEMORIAL_COMPOSE_FILE})
ROLLBACK_CAPSULE_ALLOWED_EXTERNAL_LAYERS = frozenset(
    TRUSTED_EXTERNAL_COMPOSE_LAYER_ORDER
)
ROLLBACK_CAPSULE_COMPOSE_LABEL_PREFIX = "com.docker.compose."
ROLLBACK_CAPSULE_CONFIG_MAPPED_KEYS = frozenset(
    {
        "Cmd",
        "Entrypoint",
        "Env",
        "ExposedPorts",
        "Healthcheck",
        "Hostname",
        "Image",
        "Labels",
        "StopSignal",
        "StopTimeout",
        "User",
        "WorkingDir",
    }
)
ROLLBACK_CAPSULE_CONFIG_ENGINE_DEFAULTS = {
    "AttachStderr": True,
    "AttachStdout": True,
}
ROLLBACK_CAPSULE_HOST_MAPPED_KEYS = frozenset(
    {
        "Binds",
        "CapDrop",
        "CgroupnsMode",
        "CpuShares",
        "ExtraHosts",
        "GroupAdd",
        "IpcMode",
        "LogConfig",
        "Memory",
        "MemoryReservation",
        "MemorySwap",
        "NanoCpus",
        "NetworkMode",
        "PidsLimit",
        "PortBindings",
        "ReadonlyRootfs",
        "RestartPolicy",
        "Runtime",
        "SecurityOpt",
        "ShmSize",
        "Tmpfs",
    }
)
ROLLBACK_CAPSULE_ENGINE_SECURITY_KEYS = frozenset({"MaskedPaths", "ReadonlyPaths"})
ROLLBACK_CAPSULE_ENGINE_SECURITY_DEFAULTS = {
    "MaskedPaths": [
        "/proc/acpi",
        "/proc/asound",
        "/proc/interrupts",
        "/proc/kcore",
        "/proc/keys",
        "/proc/latency_stats",
        "/proc/sched_debug",
        "/proc/scsi",
        "/proc/timer_list",
        "/proc/timer_stats",
        "/sys/devices/virtual/powercap",
        "/sys/firmware",
    ],
    "ReadonlyPaths": [
        "/proc/bus",
        "/proc/fs",
        "/proc/irq",
        "/proc/sys",
        "/proc/sysrq-trigger",
    ],
}
ROLLBACK_CAPSULE_NETWORK_DYNAMIC_KEYS = frozenset(
    {
        "DNSNames",
        "EndpointID",
        "Gateway",
        "GlobalIPv6Address",
        "GlobalIPv6PrefixLen",
        "IPAddress",
        "IPPrefixLen",
        "IPv6Gateway",
        "MacAddress",
    }
)
ROLLBACK_CAPSULE_NETWORK_SETTINGS_KEYS = frozenset(
    {
        "Bridge",
        "EndpointID",
        "Gateway",
        "GlobalIPv6Address",
        "GlobalIPv6PrefixLen",
        "HairpinMode",
        "IPAddress",
        "IPPrefixLen",
        "IPv6Gateway",
        "LinkLocalIPv6Address",
        "LinkLocalIPv6PrefixLen",
        "MacAddress",
        "Networks",
        "Ports",
        "SandboxID",
        "SandboxKey",
        "SecondaryIPAddresses",
        "SecondaryIPv6Addresses",
    }
)
ROLLBACK_CAPSULE_MOUNT_KEYS = frozenset(
    {
        "Destination",
        "Driver",
        "Mode",
        "Name",
        "Propagation",
        "RW",
        "Source",
        "Type",
    }
)
ROLLBACK_CAPSULE_RENDER_TOP_LEVEL_KEYS = frozenset(
    {
        "name",
        "networks",
        "services",
        "version",
        "volumes",
        "x-ea-rollback-capsule",
    }
)
ROLLBACK_CAPSULE_RENDER_SERVICE_KEYS = frozenset(
    {
        "build",
        "cap_drop",
        "cgroup",
        "command",
        "container_name",
        "cpu_shares",
        "cpus",
        "entrypoint",
        "environment",
        "expose",
        "extra_hosts",
        "group_add",
        "healthcheck",
        "hostname",
        "image",
        "ipc",
        "labels",
        "logging",
        "mem_limit",
        "mem_reservation",
        "memswap_limit",
        "networks",
        "pids_limit",
        "ports",
        "pull_policy",
        "read_only",
        "restart",
        "runtime",
        "security_opt",
        "shm_size",
        "stop_grace_period",
        "stop_signal",
        "tmpfs",
        "user",
        "volumes",
        "working_dir",
    }
)
ROLLBACK_CAPSULE_RENDER_NETWORK_KEYS = frozenset(
    {
        "attachable",
        "driver",
        "driver_opts",
        "enable_ipv4",
        "enable_ipv6",
        "external",
        "internal",
        "ipam",
        "labels",
        "name",
    }
)
ROLLBACK_CAPSULE_RENDER_VOLUME_KEYS = frozenset(
    {"driver", "driver_opts", "external", "labels", "name"}
)
ROLLBACK_CAPSULE_RENDER_SERVICE_NETWORK_KEYS = frozenset(
    {
        "aliases",
        "driver_opts",
        "gw_priority",
        "interface_name",
        "ipv4_address",
        "ipv6_address",
        "link_local_ips",
        "mac_address",
        "priority",
    }
)
ROLLBACK_CAPSULE_RENDER_MOUNT_KEYS = frozenset(
    {"bind", "consistency", "read_only", "source", "target", "tmpfs", "type", "volume"}
)
ROLLBACK_CAPSULE_RENDER_BIND_KEYS = frozenset(
    {"create_host_path", "propagation", "selinux"}
)
ROLLBACK_CAPSULE_RENDER_VOLUME_OPTION_KEYS = frozenset({"nocopy", "subpath"})
ROLLBACK_CAPSULE_RENDER_PORT_KEYS = frozenset(
    {"app_protocol", "host_ip", "mode", "name", "protocol", "published", "target"}
)
ROLLBACK_RECOVERY_ARMED_STATUS = "armed"
ROLLBACK_RECOVERY_CLEANUP_STATUS = "cleanup_capsule_pending"
ROLLBACK_RECOVERY_ALLOWED_STATUSES = frozenset(
    {ROLLBACK_RECOVERY_ARMED_STATUS, ROLLBACK_RECOVERY_CLEANUP_STATUS}
)
MAX_HTTP_BODY_BYTES = 2 * 1024 * 1024
MAX_INTERNAL_OPENAPI_BYTES = 8 * 1024 * 1024
MAX_FIXED_JSON_SCRIPT_OUTPUT_BYTES = 64 * 1024
MAX_PRIVATE_RELEASE_EVIDENCE_BYTES = 2 * 1024 * 1024
MAX_DEPLOYMENT_INPUT_BYTES = 8 * 1024 * 1024
MAX_GIT_INDEX_LIST_BYTES = 16 * 1024 * 1024
MAX_RECEIPT_CONTENT_TYPE_CHARS = 160
MAX_MUTATION_ACTION_SECONDS = 180.0
CONTAINER_OPENAPI_SNAPSHOT_SCRIPT = f"""
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
if len(raw) > {MAX_INTERNAL_OPENAPI_BYTES}:
    raise SystemExit(86)
sys.stdout.buffer.write(raw)
""".strip()
RELEASE_EVIDENCE_ENV_ALLOWLIST = frozenset(
    {
        "EA_DEPLOY_BRANCH",
        "EA_DEPLOY_COMMIT_SHA",
        "EA_DEPLOY_COMPOSE_FILES",
        "EA_DEPLOY_COMPOSE_OVERRIDES",
        "EA_DEPLOY_ENABLED_MODES",
        "EA_DEPLOY_ENABLED_PROJECT_MODES",
        "EA_DEPLOY_PRIMARY_MODE",
        "EA_DEPLOY_PROJECT_MODE",
        "EA_DEPLOY_PUBLIC_ORIGIN",
        "EA_DEPLOY_PUBLIC_ORIGIN_SOURCE",
        "EA_DEPLOY_REPOSITORY",
        "EA_DEPLOY_TRACKING_BRANCH",
        "EA_DEPLOYMENT_ID",
        "EA_DEPLOYMENT_ID_SOURCE",
        "EA_HOST_PORT",
        "EA_PUBLIC_APP_BASE_URL",
        "EA_PUBLIC_ORIGIN",
        "HOME",
        "LANG",
        "LC_ALL",
        "PATH",
        "PUBLIC_ORIGIN",
        "PROPERTYQUARRY_PUBLIC_BASE_URL",
        "RELEASE_LABEL",
        "TZ",
    }
)
FIXED_JSON_SCRIPT_LABELS = {
    "scripts/verify_release_authority.py": "release_authority",
    "scripts/verify_memorial_deploy_readiness.py": "memorial_deploy_readiness",
    "scripts/verify_manfred_memorial_candidate.py": "manfred_candidate_verifier",
}
SAFE_SCRIPT_ORIGIN_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
SAFE_CANDIDATE_ERROR_CODES = frozenset(
    {
        "candidate_browser_accessibility_contract_failed",
        "candidate_browser_automatic_provider_work_detected",
        "candidate_browser_automatic_websocket_detected",
        "candidate_browser_desktop_layout_contract_failed",
        "candidate_browser_executable_invalid",
        "candidate_browser_executable_unavailable",
        "candidate_browser_external_request_detected",
        "candidate_browser_page_unavailable",
        "candidate_browser_performance_contract_failed",
        "candidate_browser_provider_boundary_invalid",
        "candidate_browser_runtime_error",
        "candidate_browser_runtime_unavailable",
        "candidate_browser_same_origin_http_error",
        "candidate_contribution_mode_conflict",
        "candidate_contribution_receipt_invalid",
        "candidate_contribution_receipt_missing",
        "candidate_contribution_receipt_permissions_invalid",
        "candidate_contribution_withdrawal_invalid",
        "candidate_health_timeout",
        "candidate_http_json_invalid",
        "candidate_http_response_too_large",
        "candidate_http_status_unexpected",
        "candidate_memorial_slug_mismatch",
        "candidate_memorial_alias_invalid",
        "candidate_narrator_boundary_invalid",
        "candidate_public_headers_incomplete",
        "candidate_public_manifest_private_data_exposed",
        "candidate_share_packet_private_data_exposed",
        "candidate_voice_release_boundary_invalid",
    }
)
SAFE_CANDIDATE_HTTP_STATUS_PATHS = frozenset({"/memorials/manfred"})
SAFE_CANDIDATE_HTTP_STATUS_ERROR_PATTERN = re.compile(
    r"^candidate_http_status_unexpected:([^:\x00-\x20\x7f]{1,160}):([1-5][0-9]{2})$"
)
CONTAINER_PROJECTION_DIGEST_SCRIPT = r"""
import hashlib
import json
import os
import signal
import stat
import sys
from pathlib import Path, PurePosixPath

def directory_identity(metadata):
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )

def file_identity(metadata):
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_nlink,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )

root = Path(sys.argv[1])
expected_file_count = int(sys.argv[2])
expected_projection_bytes = int(sys.argv[3])
if expected_file_count < 0 or expected_projection_bytes < 0:
    raise SystemExit(17)
maximum_entry_count = max(expected_file_count * 4 + 32, 64)
budget = {"entries": 0, "files": 0, "bytes": 0}
signal.signal(signal.SIGALRM, lambda _signum, _frame: (_ for _ in ()).throw(SystemExit(18)))
signal.alarm(20)
directory_flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_DIRECTORY", 0)
file_flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NONBLOCK", 0)
if hasattr(os, "O_NOFOLLOW"):
    directory_flags |= os.O_NOFOLLOW
    file_flags |= os.O_NOFOLLOW
try:
    root_descriptor = os.open(root, directory_flags)
except OSError:
    raise SystemExit(10)
rows = []
try:
    root_metadata = os.fstat(root_descriptor)
    root_path_metadata = os.stat(root, follow_symlinks=False)
    if (
        not stat.S_ISDIR(root_metadata.st_mode)
        or stat.S_ISLNK(root_path_metadata.st_mode)
        or stat.S_IMODE(root_metadata.st_mode) != 0o550
        or (root_metadata.st_dev, root_metadata.st_ino)
        != (root_path_metadata.st_dev, root_path_metadata.st_ino)
    ):
        raise SystemExit(10)

    def walk(directory_descriptor, relative):
        before = os.fstat(directory_descriptor)
        if (
            not stat.S_ISDIR(before.st_mode)
            or stat.S_IMODE(before.st_mode) != 0o550
        ):
            raise SystemExit(11)
        with os.scandir(directory_descriptor) as iterator:
            entries = []
            for entry in iterator:
                budget["entries"] += 1
                if budget["entries"] > maximum_entry_count:
                    raise SystemExit(16)
                entries.append(entry)
            entries.sort(key=lambda row: row.name)
        for entry in entries:
            name = entry.name
            try:
                initial = os.stat(
                    name,
                    dir_fd=directory_descriptor,
                    follow_symlinks=False,
                )
            except OSError:
                raise SystemExit(14)
            projected = (*relative, name)
            if stat.S_ISDIR(initial.st_mode) and not stat.S_ISLNK(initial.st_mode):
                try:
                    child_descriptor = os.open(
                        name,
                        directory_flags,
                        dir_fd=directory_descriptor,
                    )
                except OSError:
                    raise SystemExit(14)
                try:
                    opened = os.fstat(child_descriptor)
                    if (
                        directory_identity(initial) != directory_identity(opened)
                        or stat.S_IMODE(opened.st_mode) != 0o550
                    ):
                        raise SystemExit(14)
                    walk(child_descriptor, projected)
                    if directory_identity(opened) != directory_identity(
                        os.fstat(child_descriptor)
                    ):
                        raise SystemExit(14)
                finally:
                    os.close(child_descriptor)
                continue
            if not stat.S_ISREG(initial.st_mode) or stat.S_ISLNK(initial.st_mode):
                raise SystemExit(12)
            if initial.st_nlink != 1:
                raise SystemExit(15)
            budget["files"] += 1
            budget["bytes"] += int(initial.st_size)
            if (
                budget["files"] > expected_file_count
                or budget["bytes"] > expected_projection_bytes
            ):
                raise SystemExit(16)
            mode = stat.S_IMODE(initial.st_mode)
            if mode not in {0o440, 0o444}:
                raise SystemExit(13)
            try:
                file_descriptor = os.open(
                    name,
                    file_flags,
                    dir_fd=directory_descriptor,
                )
            except OSError:
                raise SystemExit(14)
            try:
                opened = os.fstat(file_descriptor)
                if (
                    file_identity(initial) != file_identity(opened)
                    or not stat.S_ISREG(opened.st_mode)
                    or opened.st_nlink != 1
                ):
                    raise SystemExit(14)
                digest = hashlib.sha256()
                size = 0
                while True:
                    chunk = os.read(file_descriptor, 1024 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
                    size += len(chunk)
                    if size > int(opened.st_size):
                        raise SystemExit(14)
                    if file_identity(opened) != file_identity(
                        os.fstat(file_descriptor)
                    ):
                        raise SystemExit(14)
                if (
                    file_identity(opened) != file_identity(os.fstat(file_descriptor))
                    or size != int(opened.st_size)
                ):
                    raise SystemExit(14)
            finally:
                os.close(file_descriptor)
            rows.append(
                {
                    "path": PurePosixPath(*projected).as_posix(),
                    "sha256": digest.hexdigest(),
                    "size_bytes": size,
                    "mode": format(mode, "03o"),
                }
            )
        if directory_identity(before) != directory_identity(
            os.fstat(directory_descriptor)
        ):
            raise SystemExit(14)

    walk(root_descriptor, ())
    final_root_metadata = os.fstat(root_descriptor)
    final_root_path_metadata = os.stat(root, follow_symlinks=False)
    if (
        directory_identity(root_metadata) != directory_identity(final_root_metadata)
        or (final_root_metadata.st_dev, final_root_metadata.st_ino)
        != (final_root_path_metadata.st_dev, final_root_path_metadata.st_ino)
    ):
        raise SystemExit(14)
finally:
    os.close(root_descriptor)
signal.alarm(0)
if (
    budget["files"] != expected_file_count
    or budget["bytes"] != expected_projection_bytes
):
    raise SystemExit(17)
encoded = json.dumps(rows, separators=(",", ":"), sort_keys=True).encode("utf-8")
print(
    json.dumps(
        {
            "projection_sha256": hashlib.sha256(encoded).hexdigest(),
            "file_count": len(rows),
            "projection_bytes": sum(int(item["size_bytes"]) for item in rows),
        },
        separators=(",", ":"),
        sort_keys=True,
    )
)
""".strip()


class DeployError(RuntimeError):
    """A fail-closed deployment or verification error."""


@dataclass(frozen=True)
class HttpResponse:
    status: int
    content_type: str
    body: bytes
    source_revision: str = ""
    headers: Mapping[str, str] | None = None


class Runner(Protocol):
    def run(
        self,
        args: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]: ...


class SubprocessRunner:
    def run(
        self,
        args: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        check: bool = True,
        timeout_seconds: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        executable = Path(str(args[0] or "command")).name or "command"
        if executable.startswith("python") and len(args) > 1:
            executable = f"{executable}:{Path(str(args[1])).name}"
        try:
            completed = subprocess.run(  # nosec B603 - fixed executable/arguments
                list(args),
                cwd=cwd,
                env=dict(env),
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            raise DeployError(f"command_timeout:{executable}") from None
        if check and completed.returncode != 0:
            raise DeployError(f"command_failed:{completed.returncode}:{executable}")
        return completed


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _trusted_file_identity(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_nlink,
        metadata.st_uid,
        metadata.st_gid,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _trusted_directory_identity(metadata: os.stat_result) -> tuple[int, ...]:
    """Bind a directory descriptor without treating child churn as replacement."""

    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_uid,
        metadata.st_gid,
    )


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        normalized_key = key.strip()
        normalized_value = value.strip()
        if (
            len(normalized_value) >= 2
            and normalized_value[0] == normalized_value[-1]
            and normalized_value[0] in {"'", '"'}
        ):
            normalized_value = normalized_value[1:-1]
        if normalized_key:
            values[normalized_key] = normalized_value
    return values


def _prepare_ea_runtime_environment(root: Path) -> dict[str, Any]:
    """Materialize and validate the secret-safe Compose env projection."""

    try:
        receipt = prepare_runtime_env(root)
    except RuntimeEnvSanitizerError as exc:
        raise DeployError("runtime_environment_projection_failed") from exc
    outputs = receipt.get("outputs") if isinstance(receipt, Mapping) else None
    if not isinstance(outputs, list) or any(
        not isinstance(item, Mapping) for item in outputs
    ):
        raise DeployError("runtime_environment_projection_invalid")
    expected_outputs = {
        f"{EA_RUNTIME_ENV_DIRECTORY}/{EA_RUNTIME_ENV_FILE}": ".env",
    }
    if (root / ".env.local").is_file():
        expected_outputs[f"{EA_RUNTIME_ENV_DIRECTORY}/{EA_RUNTIME_LOCAL_ENV_FILE}"] = (
            ".env.local"
        )
    observed_outputs = {str(item.get("destination") or ""): item for item in outputs}
    expected_local_state = "present" if len(expected_outputs) == 2 else "absent"
    if (
        receipt.get("status") != "prepared"
        or receipt.get("output_count") != len(expected_outputs)
        or len(outputs) != len(expected_outputs)
        or len(observed_outputs) != len(expected_outputs)
        or set(observed_outputs) != set(expected_outputs)
        or receipt.get("optional_local_source") != expected_local_state
        or not isinstance(receipt.get("stale_local_output_removed"), bool)
    ):
        raise DeployError("runtime_environment_projection_invalid")
    removed_total = 0
    for destination, source in expected_outputs.items():
        item = observed_outputs[destination]
        byte_count = item.get("byte_count")
        removed_count = item.get("removed_key_count")
        if (
            item.get("source") != source
            or not isinstance(byte_count, int)
            or isinstance(byte_count, bool)
            or byte_count < 0
            or not isinstance(removed_count, int)
            or isinstance(removed_count, bool)
            or removed_count < 0
            or not SHA256_HEX_PATTERN.fullmatch(str(item.get("sha256") or ""))
        ):
            raise DeployError("runtime_environment_projection_invalid")
        removed_total += removed_count
    if receipt.get("removed_key_count") != removed_total:
        raise DeployError("runtime_environment_projection_invalid")
    return dict(receipt)


def _first_nonempty(*values: object) -> str:
    for value in values:
        normalized = str(value or "").strip()
        if normalized:
            return normalized
    return ""


def _safe_deployment_id(env: Mapping[str, str]) -> str:
    deployment_id = _first_nonempty(
        env.get("EA_DEPLOYMENT_ID"),
        env.get("DEPLOYMENT_ID"),
        env.get("RENDER_GIT_COMMIT"),
    )
    if not deployment_id:
        raise DeployError("explicit_deployment_id_required")
    if deployment_id.startswith("local-") or not DEPLOYMENT_ID_PATTERN.fullmatch(
        deployment_id
    ):
        raise DeployError("explicit_deployment_id_invalid")
    return deployment_id


def _safe_rollback_tag(deployment_id: str) -> str:
    normalized = re.sub(r"[^a-z0-9_.-]+", "-", deployment_id.lower()).strip("-.")
    normalized = normalized[:96] or "unknown"
    return f"ea-runtime:memorial-rollback-{normalized}"


def _safe_tagged_image_reference(value: str, *, reason: str) -> str:
    reference = str(value or "").strip()
    if (
        not reference
        or len(reference) > 255
        or any(character.isspace() or ord(character) < 32 for character in reference)
        or "://" in reference
        or "@" in reference
        or reference.startswith("sha256:")
        or ":" not in reference.rsplit("/", 1)[-1]
    ):
        raise DeployError(reason)
    repository, tag = reference.rsplit(":", 1)
    if (
        not IMAGE_REPOSITORY_PATTERN.fullmatch(repository)
        or not IMAGE_TAG_PATTERN.fullmatch(tag)
        or ".." in repository
        or "//" in repository
    ):
        raise DeployError(reason)
    return reference


def _safe_candidate_image_reference(value: str, *, source_revision: str) -> str:
    reference = str(value or "").strip()
    digest_match = re.fullmatch(
        r"([a-z0-9]+(?:[._-][a-z0-9]+)*(?::[0-9]+)?"
        r"(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)*)"
        r"@sha256:([0-9a-f]{64})",
        reference,
    )
    if digest_match:
        return reference
    tagged = _safe_tagged_image_reference(
        reference, reason="memorial_image_reference_invalid"
    )
    tag = tagged.rsplit(":", 1)[1]
    if source_revision not in tag and source_revision[:12] not in tag:
        raise DeployError("memorial_image_not_revision_bound")
    return tagged


def _require_durable_release_root(root: Path) -> None:
    resolved = root.resolve()
    if not resolved.is_dir():
        raise DeployError("release_root_missing")
    for temporary_root in (Path("/tmp"), Path("/var/tmp"), Path("/dev/shm")):
        if resolved == temporary_root or temporary_root in resolved.parents:
            raise DeployError("release_root_not_durable")


def _mount_identities(inspection: Mapping[str, Any]) -> list[dict[str, object]]:
    identities: list[dict[str, object]] = []
    for raw_mount in list(inspection.get("Mounts") or []):
        if not isinstance(raw_mount, dict):
            continue
        mount_type = str(raw_mount.get("Type") or "")
        source = str(
            (
                raw_mount.get("Name")
                if mount_type == "volume"
                else raw_mount.get("Source")
            )
            or ""
        )
        identities.append(
            {
                "type": mount_type,
                "source": source,
                "destination": str(raw_mount.get("Destination") or ""),
                "read_write": bool(raw_mount.get("RW")),
            }
        )
    return sorted(
        identities,
        key=lambda item: (
            str(item["destination"]),
            str(item["type"]),
            str(item["source"]),
            bool(item["read_write"]),
        ),
    )


def _identity_digest(identities: Sequence[Mapping[str, object]]) -> str:
    encoded = json.dumps(
        list(identities), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _normalized_environment(entries: Sequence[object]) -> list[str]:
    environment: dict[str, str] = {}
    for raw_entry in entries:
        if (
            not isinstance(raw_entry, str)
            or "\x00" in raw_entry
            or "=" not in raw_entry
        ):
            raise DeployError("container_environment_invalid")
        name, value = raw_entry.split("=", 1)
        if not name or "\x00" in name:
            raise DeployError("container_environment_invalid")
        environment[name] = value
    return [f"{name}={environment[name]}" for name in sorted(environment)]


def _environment_identity(entries: Sequence[object]) -> dict[str, object]:
    normalized = _normalized_environment(entries)
    return {
        "environment_sha256": hashlib.sha256(
            json.dumps(
                normalized,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
        "environment_count": len(normalized),
    }


def _normalized_command(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return list(value)
    raise DeployError("container_process_config_invalid")


def _compose_runtime_command(value: object) -> list[str]:
    """Normalize Compose-rendered process fields to Docker runtime values."""

    return [item.replace("$$", "$") for item in _normalized_command(value)]


def _process_config_identity(config: Mapping[str, Any]) -> str:
    process = {
        "command": _normalized_command(config.get("Cmd")),
        "entrypoint": _normalized_command(config.get("Entrypoint")),
        "user": str(config.get("User") or ""),
    }
    return hashlib.sha256(
        json.dumps(process, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _container_runtime_config_digests(
    inspection: Mapping[str, Any],
) -> dict[str, object]:
    config = dict(inspection.get("Config") or {})
    return {
        **_environment_identity(list(config.get("Env") or [])),
        "process_config_sha256": _process_config_identity(config),
    }


def _docker_value_is_neutral(value: object) -> bool:
    if value is None or value is False or value == 0 or value == "":
        return True
    if isinstance(value, (list, tuple)):
        return all(_docker_value_is_neutral(item) for item in value)
    if isinstance(value, dict):
        return all(_docker_value_is_neutral(item) for item in value.values())
    return False


def _validated_ipv4_address(value: object, *, reason: str) -> str:
    if not isinstance(value, str):
        raise DeployError(reason)
    try:
        parsed = ipaddress.IPv4Address(value)
    except ipaddress.AddressValueError as exc:
        raise DeployError(reason) from exc
    if str(parsed) != value:
        raise DeployError(reason)
    return value


def _rollback_capsule_compose_literal(value: str) -> str:
    if "\x00" in value:
        raise DeployError("rollback_capsule_string_invalid")
    return value.replace("$", "$$")


def _rollback_capsule_decode_rendered_literals(value: object) -> object:
    if isinstance(value, str):
        result: list[str] = []
        position = 0
        while position < len(value):
            if value[position] != "$":
                result.append(value[position])
                position += 1
                continue
            end = position
            while end < len(value) and value[end] == "$":
                end += 1
            count = end - position
            if count % 2:
                raise DeployError("rollback_capsule_render_unescaped_interpolation")
            result.append("$" * (count // 2))
            position = end
        return "".join(result)
    if isinstance(value, list):
        return [_rollback_capsule_decode_rendered_literals(item) for item in value]
    if isinstance(value, dict):
        return {
            str(name): _rollback_capsule_decode_rendered_literals(item)
            for name, item in value.items()
        }
    return value


def _rollback_capsule_unknown_non_neutral(
    value: Mapping[str, Any],
    allowed: frozenset[str],
    *,
    reason_prefix: str,
) -> None:
    for raw_key, raw_value in value.items():
        key = str(raw_key)
        if key not in allowed and not _docker_value_is_neutral(raw_value):
            raise DeployError(f"{reason_prefix}:{key}")


def _rollback_capsule_duration_ns(value: object, *, reason: str) -> int:
    if type(value) is int:
        if value < 0:
            raise DeployError(reason)
        return value
    if not isinstance(value, str) or not value or "\x00" in value:
        raise DeployError(reason)
    if value == "0":
        return 0
    units = {
        "ns": Decimal(1),
        "us": Decimal(1_000),
        "µs": Decimal(1_000),
        "ms": Decimal(1_000_000),
        "s": Decimal(1_000_000_000),
        "m": Decimal(60_000_000_000),
        "h": Decimal(3_600_000_000_000),
    }
    position = 0
    total = Decimal(0)
    pattern = re.compile(r"([0-9]+(?:\.[0-9]+)?)(ns|us|µs|ms|s|m|h)")
    while position < len(value):
        match = pattern.match(value, position)
        if match is None:
            raise DeployError(reason)
        try:
            total += Decimal(match.group(1)) * units[match.group(2)]
        except InvalidOperation as exc:
            raise DeployError(reason) from exc
        position = match.end()
    integral = total.to_integral_value()
    if total != integral or integral < 0:
        raise DeployError(reason)
    return int(integral)


def _rollback_capsule_byte_quantity(value: object, *, reason: str) -> int:
    if type(value) is int:
        return value
    if not isinstance(value, str) or not value or "\x00" in value:
        raise DeployError(reason)
    match = re.fullmatch(
        r"([+-]?[0-9]+(?:\.[0-9]+)?)\s*([kmgtpe]?i?b?|bytes?)?",
        value.strip().casefold(),
    )
    if match is None:
        raise DeployError(reason)
    unit = (match.group(2) or "b").casefold()
    aliases = {
        "byte": "b",
        "bytes": "b",
        "k": "kb",
        "ki": "kib",
        "m": "mb",
        "mi": "mib",
        "g": "gb",
        "gi": "gib",
        "t": "tb",
        "ti": "tib",
        "p": "pb",
        "pi": "pib",
        "e": "eb",
        "ei": "eib",
    }
    unit = aliases.get(unit, unit)
    powers = {
        "b": 0,
        "kb": 1,
        "kib": 1,
        "mb": 2,
        "mib": 2,
        "gb": 3,
        "gib": 3,
        "tb": 4,
        "tib": 4,
        "pb": 5,
        "pib": 5,
        "eb": 6,
        "eib": 6,
    }
    if unit not in powers:
        raise DeployError(reason)
    try:
        total = Decimal(match.group(1)) * (Decimal(1024) ** powers[unit])
    except InvalidOperation as exc:
        raise DeployError(reason) from exc
    integral = total.to_integral_value()
    if total != integral:
        raise DeployError(reason)
    return int(integral)


def _rollback_capsule_nano_cpus(value: object, *, reason: str) -> int:
    if type(value) not in {int, float, str} or isinstance(value, bool):
        raise DeployError(reason)
    try:
        cpu_value = Decimal(str(value))
    except InvalidOperation as exc:
        raise DeployError(reason) from exc
    nano_cpus = cpu_value * Decimal(1_000_000_000)
    integral = nano_cpus.to_integral_value()
    if nano_cpus != integral or integral < 0:
        raise DeployError(reason)
    return int(integral)


def _rollback_capsule_extra_hosts(value: object) -> list[str]:
    items: list[str]
    if value is None:
        return []
    if isinstance(value, dict):
        items = [f"{key}={item}" for key, item in value.items()]
    elif isinstance(value, list) and all(isinstance(item, str) for item in value):
        items = list(value)
    else:
        raise DeployError("rollback_capsule_extra_hosts_invalid")
    normalized: set[str] = set()
    for item in items:
        delimiter = "=" if "=" in item else ":"
        host, found, address = item.partition(delimiter)
        if (
            not found
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,254}", host) is None
            or not address
            or "\x00" in address
            or "\n" in address
            or "\r" in address
        ):
            raise DeployError("rollback_capsule_extra_hosts_invalid")
        normalized.add(f"{host}:{address}")
    return sorted(normalized)


def _rollback_capsule_group_add(value: object) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(
        isinstance(item, str)
        and item
        and "\x00" not in item
        and "\n" not in item
        and "\r" not in item
        for item in value
    ):
        raise DeployError("rollback_capsule_group_add_invalid")
    return sorted(set(value))


def _rollback_capsule_healthcheck_identity(value: object) -> dict[str, object]:
    if value in (None, {}):
        return {}
    if not isinstance(value, dict):
        raise DeployError("rollback_capsule_healthcheck_invalid")
    allowed = {
        "Interval",
        "Retries",
        "StartInterval",
        "StartPeriod",
        "Test",
        "Timeout",
    }
    _rollback_capsule_unknown_non_neutral(
        value,
        frozenset(allowed),
        reason_prefix="rollback_capsule_healthcheck_field_unsupported",
    )
    result: dict[str, object] = {}
    test = value.get("Test")
    if not _docker_value_is_neutral(test):
        if not isinstance(test, list) or not all(
            isinstance(item, str) and "\x00" not in item for item in test
        ):
            raise DeployError("rollback_capsule_healthcheck_invalid")
        result["Test"] = list(test)
    for key in ("Interval", "StartInterval", "StartPeriod", "Timeout"):
        duration = value.get(key)
        if not _docker_value_is_neutral(duration):
            if type(duration) is not int or duration < 0:
                raise DeployError("rollback_capsule_healthcheck_invalid")
            result[key] = duration
    retries = value.get("Retries")
    if not _docker_value_is_neutral(retries):
        if type(retries) is not int or retries < 0:
            raise DeployError("rollback_capsule_healthcheck_invalid")
        result["Retries"] = retries
    return result


def _rollback_capsule_port_identity(
    config: Mapping[str, Any], host: Mapping[str, Any]
) -> list[dict[str, object]]:
    exposed = config.get("ExposedPorts") or {}
    bindings = host.get("PortBindings") or {}
    if not isinstance(exposed, dict) or not isinstance(bindings, dict):
        raise DeployError("rollback_capsule_ports_invalid")
    pattern = re.compile(r"^([1-9][0-9]{0,4})/(tcp|udp|sctp)$")
    rows: list[dict[str, object]] = []
    for raw_port in sorted({*exposed, *bindings}):
        port = str(raw_port)
        match = pattern.fullmatch(port)
        if match is None or not 1 <= int(match.group(1)) <= 65535:
            raise DeployError("rollback_capsule_ports_invalid")
        if raw_port in exposed and exposed[raw_port] not in ({}, None):
            raise DeployError("rollback_capsule_ports_invalid")
        raw_bindings = bindings.get(raw_port) or []
        if not isinstance(raw_bindings, list):
            raise DeployError("rollback_capsule_ports_invalid")
        normalized_bindings: list[dict[str, str]] = []
        for raw_binding in raw_bindings:
            if not isinstance(raw_binding, dict):
                raise DeployError("rollback_capsule_ports_invalid")
            _rollback_capsule_unknown_non_neutral(
                raw_binding,
                frozenset({"HostIp", "HostPort"}),
                reason_prefix="rollback_capsule_port_binding_field_unsupported",
            )
            host_ip = str(raw_binding.get("HostIp") or "")
            host_port = str(raw_binding.get("HostPort") or "")
            if (
                not host_port.isdigit()
                or not 1 <= int(host_port) <= 65535
                or "\x00" in host_ip
            ):
                raise DeployError("rollback_capsule_ports_invalid")
            normalized_bindings.append(
                {"host_ip": host_ip, "host_port": str(int(host_port))}
            )
        rows.append(
            {
                "container_port": int(match.group(1)),
                "protocol": match.group(2),
                "exposed": raw_port in exposed,
                "bindings": sorted(
                    normalized_bindings,
                    key=lambda item: (item["host_ip"], item["host_port"]),
                ),
            }
        )
    return rows


def _rollback_capsule_host_identity(host: Mapping[str, Any]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key in sorted(
        {*ROLLBACK_CAPSULE_HOST_MAPPED_KEYS, *ROLLBACK_CAPSULE_ENGINE_SECURITY_KEYS}
    ):
        if key in {"Binds", "PortBindings"}:
            continue
        value = host.get(key)
        if _docker_value_is_neutral(value):
            continue
        if key in {"CapDrop", "SecurityOpt"}:
            if not isinstance(value, list) or not all(
                isinstance(item, str) and item and "\x00" not in item for item in value
            ):
                raise DeployError("rollback_capsule_security_config_invalid")
            result[key] = sorted(set(value))
        elif key == "ExtraHosts":
            result[key] = _rollback_capsule_extra_hosts(value)
        elif key == "GroupAdd":
            result[key] = _rollback_capsule_group_add(value)
        elif key == "Tmpfs":
            if not isinstance(value, dict) or not all(
                isinstance(path, str)
                and path.startswith("/")
                and os.path.normpath(path) == path
                and isinstance(options, str)
                and "\x00" not in path
                and "\x00" not in options
                for path, options in value.items()
            ):
                raise DeployError("rollback_capsule_tmpfs_invalid")
            result[key] = {path: value[path] for path in sorted(value)}
        elif key == "LogConfig":
            if not isinstance(value, dict):
                raise DeployError("rollback_capsule_logging_invalid")
            _rollback_capsule_unknown_non_neutral(
                value,
                frozenset({"Config", "Type"}),
                reason_prefix="rollback_capsule_logging_field_unsupported",
            )
            options = value.get("Config") or {}
            if not isinstance(options, dict) or not all(
                isinstance(name, str) and isinstance(item, str)
                for name, item in options.items()
            ):
                raise DeployError("rollback_capsule_logging_invalid")
            result[key] = {
                "Type": str(value.get("Type") or ""),
                "Config": {name: options[name] for name in sorted(options)},
            }
        elif key == "RestartPolicy":
            if not isinstance(value, dict):
                raise DeployError("rollback_capsule_restart_policy_invalid")
            _rollback_capsule_unknown_non_neutral(
                value,
                frozenset({"MaximumRetryCount", "Name"}),
                reason_prefix="rollback_capsule_restart_policy_field_unsupported",
            )
            result[key] = {
                "Name": str(value.get("Name") or ""),
                "MaximumRetryCount": int(value.get("MaximumRetryCount") or 0),
            }
        else:
            result[key] = value
    return result


def _rollback_capsule_noncompose_labels(
    config: Mapping[str, Any],
) -> dict[str, str]:
    raw_labels = config.get("Labels") or {}
    if not isinstance(raw_labels, dict):
        raise DeployError("rollback_capsule_labels_invalid")
    labels: dict[str, str] = {}
    for raw_name, raw_value in raw_labels.items():
        if not isinstance(raw_name, str) or not isinstance(raw_value, str):
            raise DeployError("rollback_capsule_labels_invalid")
        if (
            not raw_name
            or "\x00" in raw_name
            or "\x00" in raw_value
            or "\n" in raw_name
            or "\r" in raw_name
        ):
            raise DeployError("rollback_capsule_labels_invalid")
        if not raw_name.startswith(ROLLBACK_CAPSULE_COMPOSE_LABEL_PREFIX):
            labels[raw_name] = raw_value
    return {name: labels[name] for name in sorted(labels)}


def _rollback_capsule_mount_identities(
    inspection: Mapping[str, Any],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    destinations: set[str] = set()
    for raw_mount in list(inspection.get("Mounts") or []):
        if not isinstance(raw_mount, dict):
            raise DeployError("rollback_capsule_mount_invalid")
        _rollback_capsule_unknown_non_neutral(
            raw_mount,
            ROLLBACK_CAPSULE_MOUNT_KEYS,
            reason_prefix="rollback_capsule_mount_field_unsupported",
        )
        mount_type = str(raw_mount.get("Type") or "")
        destination = str(raw_mount.get("Destination") or "")
        propagation = str(raw_mount.get("Propagation") or "")
        if (
            mount_type not in {"bind", "volume"}
            or not destination.startswith("/")
            or os.path.normpath(destination) != destination
            or "\x00" in destination
            or destination in destinations
        ):
            raise DeployError("rollback_capsule_mount_invalid")
        destinations.add(destination)
        read_write = bool(raw_mount.get("RW"))
        mode = str(raw_mount.get("Mode") or ("rw" if read_write else "ro"))
        if mode not in {"ro", "rw"} or (mode == "rw") is not read_write:
            raise DeployError("rollback_capsule_mount_mode_unsupported")
        if mount_type == "bind":
            raw_source = str(raw_mount.get("Source") or "")
            source_path = Path(raw_source)
            if (
                not source_path.is_absolute()
                or ".." in source_path.parts
                or "\x00" in raw_source
                or os.path.normpath(raw_source) != raw_source
            ):
                raise DeployError("rollback_capsule_bind_mount_invalid")
            source = raw_source
            driver = ""
            if not _docker_value_is_neutral(raw_mount.get("Driver")) or not (
                _docker_value_is_neutral(raw_mount.get("Name"))
            ):
                raise DeployError("rollback_capsule_bind_mount_invalid")
            if propagation not in {"", "private", "rprivate"}:
                raise DeployError("rollback_capsule_bind_propagation_unsupported")
        else:
            source = str(raw_mount.get("Name") or "")
            driver = str(raw_mount.get("Driver") or "local")
            if (
                not source
                or len(source) > 255
                or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", source) is None
                or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", driver) is None
                or propagation
            ):
                raise DeployError("rollback_capsule_volume_mount_invalid")
        rows.append(
            {
                "type": mount_type,
                "source": source,
                "destination": destination,
                "read_write": read_write,
                "propagation": propagation,
                "mode": mode,
                "driver": driver,
            }
        )
    return sorted(
        rows,
        key=lambda item: (
            str(item["destination"]),
            str(item["type"]),
            str(item["source"]),
            bool(item["read_write"]),
            str(item["propagation"]),
            str(item["mode"]),
            str(item["driver"]),
        ),
    )


def _rollback_capsule_network_identities(
    inspection: Mapping[str, Any],
) -> list[dict[str, object]]:
    network_settings = inspection.get("NetworkSettings") or {}
    if not isinstance(network_settings, dict):
        raise DeployError("rollback_capsule_networks_invalid")
    _rollback_capsule_unknown_non_neutral(
        network_settings,
        ROLLBACK_CAPSULE_NETWORK_SETTINGS_KEYS,
        reason_prefix="rollback_capsule_network_settings_field_unsupported",
    )
    raw_networks = network_settings.get("Networks") or {}
    if not isinstance(raw_networks, dict):
        raise DeployError("rollback_capsule_networks_invalid")
    container_id = str(inspection.get("Id") or "")
    rows: list[dict[str, object]] = []
    for raw_name, raw_endpoint in sorted(raw_networks.items()):
        name = str(raw_name or "")
        if re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.-]{0,254}", name
        ) is None or not isinstance(raw_endpoint, dict):
            raise DeployError("rollback_capsule_networks_invalid")
        network_id = str(raw_endpoint.get("NetworkID") or "")
        if re.fullmatch(r"[0-9a-f]{64}", network_id) is None:
            raise DeployError("rollback_capsule_network_id_invalid")
        ipv4_address = ""
        if "IPAMConfig" in raw_endpoint and raw_endpoint["IPAMConfig"] is not None:
            ipam_config = raw_endpoint["IPAMConfig"]
            if not isinstance(ipam_config, dict):
                raise DeployError("rollback_capsule_network_ipam_config_unsupported")
            if ipam_config:
                if set(ipam_config) != {"IPv4Address"}:
                    raise DeployError(
                        "rollback_capsule_network_ipam_config_unsupported"
                    )
                ipv4_address = _validated_ipv4_address(
                    ipam_config["IPv4Address"],
                    reason="rollback_capsule_static_ipv4_invalid",
                )
        for key, value in raw_endpoint.items():
            if key in {
                "Aliases",
                "DriverOpts",
                "GwPriority",
                "IPAMConfig",
                "Links",
                "NetworkID",
                *ROLLBACK_CAPSULE_NETWORK_DYNAMIC_KEYS,
            }:
                if key in {"DriverOpts", "GwPriority", "Links"} and not (
                    _docker_value_is_neutral(value)
                ):
                    raise DeployError(
                        f"rollback_capsule_network_field_unsupported:{key}"
                    )
                continue
            if not _docker_value_is_neutral(value):
                raise DeployError(f"rollback_capsule_network_field_unsupported:{key}")
        raw_aliases = raw_endpoint.get("Aliases") or []
        if not isinstance(raw_aliases, list) or not all(
            isinstance(item, str) and item and "\x00" not in item
            for item in raw_aliases
        ):
            raise DeployError("rollback_capsule_network_alias_invalid")
        aliases = sorted(
            {
                item
                for item in raw_aliases
                if item not in {container_id, container_id[:12]}
            }
        )
        if any(
            re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,254}", item) is None
            for item in aliases
        ):
            raise DeployError("rollback_capsule_network_alias_invalid")
        row: dict[str, object] = {
            "name": name,
            "network_id": network_id,
            "aliases": aliases,
        }
        if ipv4_address:
            row["ipv4_address"] = ipv4_address
        rows.append(row)
    return rows


def _require_rollback_capsule_supported_inspection(
    inspection: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    config_value = inspection.get("Config")
    host_value = inspection.get("HostConfig")
    config = dict(config_value) if isinstance(config_value, dict) else {}
    host = dict(host_value) if isinstance(host_value, dict) else {}
    if not config:
        raise DeployError("rollback_capsule_container_config_missing")
    for key, value in config.items():
        if key in ROLLBACK_CAPSULE_CONFIG_MAPPED_KEYS:
            continue
        expected_default = ROLLBACK_CAPSULE_CONFIG_ENGINE_DEFAULTS.get(key)
        if expected_default is not None and value == expected_default:
            continue
        if not _docker_value_is_neutral(value):
            raise DeployError(f"rollback_capsule_config_field_unsupported:{key}")
    for key, value in host.items():
        if key in ROLLBACK_CAPSULE_HOST_MAPPED_KEYS:
            continue
        if key in ROLLBACK_CAPSULE_ENGINE_SECURITY_KEYS:
            if value != ROLLBACK_CAPSULE_ENGINE_SECURITY_DEFAULTS[key]:
                raise DeployError(f"rollback_capsule_host_field_unsupported:{key}")
            continue
        if not _docker_value_is_neutral(value):
            raise DeployError(f"rollback_capsule_host_field_unsupported:{key}")
    _normalized_environment(list(config.get("Env") or []))
    _normalized_command(config.get("Cmd"))
    _normalized_command(config.get("Entrypoint"))
    _rollback_capsule_noncompose_labels(config)
    _rollback_capsule_mount_identities(inspection)
    _rollback_capsule_network_identities(inspection)
    return config, host


def _container_functional_identity(
    inspection: Mapping[str, Any],
) -> dict[str, object]:
    config, host = _require_rollback_capsule_supported_inspection(inspection)
    environment = _normalized_environment(list(config.get("Env") or []))
    mounts = _rollback_capsule_mount_identities(inspection)
    networks = _rollback_capsule_network_identities(inspection)
    noncompose_labels = _rollback_capsule_noncompose_labels(config)
    runtime_path = str(inspection.get("Path") or "")
    runtime_args = inspection.get("Args") or []
    if (
        "\x00" in runtime_path
        or not isinstance(runtime_args, list)
        or not all(
            isinstance(item, str) and "\x00" not in item for item in runtime_args
        )
    ):
        raise DeployError("rollback_capsule_runtime_process_invalid")
    host_mapped = _rollback_capsule_host_identity(host)
    port_identity = _rollback_capsule_port_identity(config, host)
    domains: dict[str, object] = {
        "image": {
            "image_id": str(inspection.get("Image") or ""),
            "image_reference": str(config.get("Image") or ""),
        },
        "environment": {
            "sha256": _canonical_json_sha256(environment),
            "count": len(environment),
        },
        "process": {
            "sha256": _canonical_json_sha256(
                {
                    "command": _normalized_command(config.get("Cmd")),
                    "entrypoint": _normalized_command(config.get("Entrypoint")),
                    "hostname": str(config.get("Hostname") or ""),
                    "runtime_args": list(runtime_args),
                    "runtime_path": runtime_path,
                    "user": str(config.get("User") or ""),
                    "working_dir": str(config.get("WorkingDir") or ""),
                }
            )
        },
        "healthcheck": {
            "sha256": _canonical_json_sha256(
                _rollback_capsule_healthcheck_identity(config.get("Healthcheck"))
            )
        },
        "host_config": {"sha256": _canonical_json_sha256(host_mapped)},
        "ports": {
            "sha256": _canonical_json_sha256(port_identity),
            "count": len(port_identity),
        },
        "mounts": {
            "sha256": _canonical_json_sha256(mounts),
            "count": len(mounts),
        },
        "networks": {
            "sha256": _canonical_json_sha256(networks),
            "count": len(networks),
        },
        "noncompose_labels": {
            "sha256": _canonical_json_sha256(noncompose_labels),
            "count": len(noncompose_labels),
        },
        "stop_config": {
            "sha256": _canonical_json_sha256(
                {
                    "stop_signal": str(config.get("StopSignal") or ""),
                    "stop_timeout": config.get("StopTimeout"),
                }
            )
        },
    }
    return {
        "contract_name": "ea.memorial_api_functional_identity.v2",
        "version": 2,
        "domains": domains,
        "functional_identity_sha256": _canonical_json_sha256(domains),
    }


def _memorial_rollback_environment(
    *,
    config: Mapping[str, Any],
    mount_identities: Sequence[Mapping[str, object]],
    image_reference: str,
) -> dict[str, str]:
    container_environment = {
        entry.split("=", 1)[0]: entry.split("=", 1)[1]
        for entry in _normalized_environment(list(config.get("Env") or []))
    }
    environment: dict[str, str] = {}
    for host_name, container_name in ROLLBACK_MEMORIAL_CONTAINER_ENV_MAP.items():
        value = container_environment.get(container_name)
        if value is None or "\n" in value or "\r" in value:
            raise DeployError("rollback_memorial_environment_invalid")
        environment[host_name] = value
    if not re.fullmatch(r"[0-9a-f]{40}", environment["EA_SOURCE_REVISION"]):
        raise DeployError("rollback_memorial_environment_invalid")
    if not image_reference or "\n" in image_reference or "\r" in image_reference:
        raise DeployError("rollback_memorial_environment_invalid")
    environment["EA_MEMORIAL_IMAGE"] = image_reference

    by_destination: dict[str, Mapping[str, object]] = {}
    for item in mount_identities:
        destination = str(item.get("destination") or "")
        if destination in by_destination:
            raise DeployError("rollback_memorial_mount_identity_invalid")
        by_destination[destination] = item
    data_mount = by_destination.get("/data/memorial_data")
    if (
        not isinstance(data_mount, Mapping)
        or str(data_mount.get("type") or "") != "bind"
        or data_mount.get("read_write") is not False
    ):
        raise DeployError("rollback_memorial_mount_identity_invalid")
    data_root = Path(str(data_mount.get("source") or "")).expanduser()
    if not data_root.is_absolute():
        raise DeployError("rollback_memorial_mount_identity_invalid")
    environment["EA_MEMORIAL_DATA_HOST_PATH"] = str(data_root.resolve())

    runtime_root: Path | None = None
    for leaf in ("public-contributions", "private-contributions", "state"):
        mount = by_destination.get(f"/data/memorial-writable/{leaf}")
        if (
            not isinstance(mount, Mapping)
            or str(mount.get("type") or "") != "bind"
            or mount.get("read_write") is not True
        ):
            raise DeployError("rollback_memorial_mount_identity_invalid")
        source = Path(str(mount.get("source") or "")).expanduser()
        if not source.is_absolute() or source.name != leaf:
            raise DeployError("rollback_memorial_mount_identity_invalid")
        parent = source.resolve().parent
        if runtime_root is None:
            runtime_root = parent
        elif parent != runtime_root:
            raise DeployError("rollback_memorial_mount_identity_invalid")
    if runtime_root is None:
        raise DeployError("rollback_memorial_mount_identity_invalid")
    environment["EA_MEMORIAL_RUNTIME_HOST_PATH"] = str(runtime_root)
    if set(environment) != ROLLBACK_MEMORIAL_RENDER_ENV_KEYS:
        raise DeployError("rollback_memorial_environment_invalid")
    return environment


def _has_exact_zero_browser_counts(payload: Mapping[str, Any]) -> bool:
    return all(
        type(payload.get(field)) is int and payload[field] == 0
        for field in BROWSER_ZERO_COUNT_FIELDS
    )


def _canonical_json_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _fixed_json_script_failure_evidence(
    *,
    script: str,
    origin: str,
    completed: subprocess.CompletedProcess[str],
) -> dict[str, object]:
    script_label = FIXED_JSON_SCRIPT_LABELS.get(script)
    if not script_label:
        raise DeployError("fixed_json_script_not_allowlisted")
    normalized_origin = str(origin or "").strip().lower()
    if not SAFE_SCRIPT_ORIGIN_PATTERN.fullmatch(normalized_origin):
        raise DeployError("fixed_json_script_origin_invalid")

    raw_stdout = completed.stdout if isinstance(completed.stdout, str) else ""
    encoded_stdout: bytes | None = (
        raw_stdout.encode("utf-8", errors="replace")
        if len(raw_stdout) <= MAX_FIXED_JSON_SCRIPT_OUTPUT_BYTES
        else None
    )
    stdout_within_parse_limit = encoded_stdout is not None and (
        len(encoded_stdout) <= MAX_FIXED_JSON_SCRIPT_OUTPUT_BYTES
    )
    error_code = "fixed_json_script_failed"
    safe_http_status_evidence: dict[str, object] = {}
    if stdout_within_parse_limit:
        try:
            payload = json.loads(raw_stdout)
        except (TypeError, ValueError):
            payload = None
        if isinstance(payload, dict) and script_label == "manfred_candidate_verifier":
            raw_candidate_error = payload.get("error")
            candidate = str(raw_candidate_error or "").split(":", 1)[0].strip()
            if candidate in SAFE_CANDIDATE_ERROR_CODES:
                error_code = candidate
            status_match = (
                SAFE_CANDIDATE_HTTP_STATUS_ERROR_PATTERN.fullmatch(raw_candidate_error)
                if type(raw_candidate_error) is str
                else None
            )
            if (
                error_code == "candidate_http_status_unexpected"
                and status_match is not None
                and status_match.group(1) in SAFE_CANDIDATE_HTTP_STATUS_PATHS
            ):
                safe_http_status_evidence = {
                    "error_path": status_match.group(1),
                    "http_status": int(status_match.group(2)),
                }

    return_code = int(completed.returncode)
    return {
        "script": script_label,
        "origin": normalized_origin,
        "return_code": (return_code if -255 <= return_code <= 255 else 256),
        "error_code": error_code,
        "stdout_bytes": (
            len(encoded_stdout or b"")
            if stdout_within_parse_limit
            else MAX_FIXED_JSON_SCRIPT_OUTPUT_BYTES + 1
        ),
        "stdout_size_capped": not stdout_within_parse_limit,
        **safe_http_status_evidence,
    }


def _default_http_get(
    url: str,
    timeout_seconds: float,
    public_authority: str = "",
) -> HttpResponse:
    headers = {
        "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
        "User-Agent": "EA-Memorial-Scoped-Deploy/1.0",
    }
    if public_authority:
        # A host-side verifier is not the trusted production proxy.  Supplying
        # forwarded headers here would either be ignored by the strict proxy
        # CIDR policy or, under a regressed policy, let the verifier impersonate
        # the public TLS hop.  The approved Host is enough to prove canonical
        # HTTP-to-HTTPS routing without weakening that boundary.
        headers["Host"] = public_authority
    request = urllib.request.Request(
        url,
        method="GET",
        headers=headers,
    )
    try:
        opener = (
            urllib.request.build_opener(_NoRedirectHandler())
            if public_authority
            else urllib.request.build_opener()
        )
        with opener.open(request, timeout=timeout_seconds) as response:
            body = response.read(MAX_HTTP_BODY_BYTES + 1)
            if len(body) > MAX_HTTP_BODY_BYTES:
                raise DeployError(f"http_body_too_large:{url}")
            return HttpResponse(
                status=int(getattr(response, "status", 200) or 200),
                content_type=str(response.headers.get("Content-Type") or ""),
                body=body,
                source_revision=str(
                    response.headers.get("X-EA-Source-Revision") or ""
                ).strip(),
                headers={
                    name: str(response.headers.get(name) or "").strip()
                    for name in (
                        "Location",
                        "Cache-Control",
                        "Referrer-Policy",
                        "X-Content-Type-Options",
                        "X-Robots-Tag",
                    )
                },
            )
    except urllib.error.HTTPError as exc:
        raise DeployError(f"http_status_invalid:{url}:{int(exc.code or 0)}") from exc
    except (OSError, urllib.error.URLError) as exc:
        raise DeployError(f"http_probe_failed:{url}:{type(exc).__name__}") from exc


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(  # type: ignore[no-untyped-def]
        self,
        req,
        fp,
        code,
        msg,
        headers,
        newurl,
    ):
        del req, fp, code, msg, headers, newurl
        return None


def _default_http_no_redirect(
    url: str,
    timeout_seconds: float,
    method: str,
    public_authority: str = "",
) -> HttpResponse:
    if method not in {"GET", "HEAD"}:
        raise DeployError("http_no_redirect_method_invalid")
    headers = {
        "Accept": "text/html,*/*;q=0.1",
        "User-Agent": "EA-Memorial-Scoped-Deploy/1.0",
    }
    if public_authority:
        headers["Host"] = public_authority
    request = urllib.request.Request(
        url,
        method=method,
        headers=headers,
    )
    response: Any
    try:
        response = urllib.request.build_opener(_NoRedirectHandler()).open(
            request,
            timeout=timeout_seconds,
        )
    except urllib.error.HTTPError as exc:
        if int(exc.code or 0) not in {301, 302, 303, 307, 308, 404}:
            raise DeployError(
                f"http_status_invalid:{url}:{int(exc.code or 0)}"
            ) from exc
        response = exc
    except (OSError, urllib.error.URLError) as exc:
        raise DeployError(f"http_probe_failed:{url}:{type(exc).__name__}") from exc
    try:
        body = response.read(MAX_HTTP_BODY_BYTES + 1)
        if len(body) > MAX_HTTP_BODY_BYTES:
            raise DeployError(f"http_body_too_large:{url}")
        return HttpResponse(
            status=int(getattr(response, "status", 0) or response.getcode() or 0),
            content_type=str(response.headers.get("Content-Type") or ""),
            body=body,
            source_revision=str(
                response.headers.get("X-EA-Source-Revision") or ""
            ).strip(),
            headers={
                name: str(response.headers.get(name) or "").strip()
                for name in (
                    "Location",
                    "Cache-Control",
                    "Referrer-Policy",
                    "X-Content-Type-Options",
                    "X-Robots-Tag",
                )
            },
        )
    finally:
        response.close()


def _validate_public_origin(value: str, *, allowed_hosts: Sequence[str]) -> str:
    origin = str(value or "").strip().rstrip("/")
    try:
        parsed = urllib.parse.urlsplit(origin)
        port = parsed.port
    except ValueError as exc:
        raise DeployError("public_origin_invalid") from exc
    if parsed.scheme != "https" or not parsed.hostname:
        raise DeployError("public_origin_invalid")
    if (
        parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
        or port not in {None, 443}
    ):
        raise DeployError("public_origin_invalid")
    hostname = parsed.hostname.lower()
    normalized_hosts = {
        str(item or "").strip().lower().rstrip(".")
        for item in allowed_hosts
        if str(item or "").strip()
    }
    if not normalized_hosts or hostname.rstrip(".") not in normalized_hosts:
        raise DeployError("public_origin_host_not_approved")
    return origin


def _json_object(raw: str, *, reason: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except Exception as exc:
        raise DeployError(reason) from exc
    if not isinstance(payload, dict):
        raise DeployError(reason)
    return payload


def _resolve_openapi_ref(document: Mapping[str, Any], ref: str) -> object:
    if not ref.startswith("#/"):
        return None
    current: object = document
    for raw_part in ref[2:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, dict) or part not in current:
            raise DeployError("openapi_ref_invalid")
        current = current[part]
    return current


def _canonical_openapi_value(
    value: object,
    *,
    document: Mapping[str, Any],
    seen_refs: frozenset[str] = frozenset(),
) -> object:
    if isinstance(value, dict):
        ref = str(value.get("$ref") or "")
        canonical: dict[str, object] = {}
        for key in sorted(value):
            if key == "$ref":
                continue
            canonical[str(key)] = _canonical_openapi_value(
                value[key], document=document, seen_refs=seen_refs
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
    raise DeployError("openapi_value_invalid")


def _collect_referenced_openapi_schemas(
    value: object,
    *,
    document: Mapping[str, Any],
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
            _collect_referenced_openapi_schemas(
                _resolve_openapi_ref(document, ref),
                document=document,
                names=names,
                visited_refs=visited_refs,
            )
        for item in value.values():
            _collect_referenced_openapi_schemas(
                item,
                document=document,
                names=names,
                visited_refs=visited_refs,
            )
    elif isinstance(value, list):
        for item in value:
            _collect_referenced_openapi_schemas(
                item,
                document=document,
                names=names,
                visited_refs=visited_refs,
            )


def _canonical_openapi_contract(document: Mapping[str, Any]) -> dict[str, Any]:
    paths_value = document.get("paths")
    paths_payload = dict(paths_value) if isinstance(paths_value, dict) else {}
    components_value = document.get("components")
    components = dict(components_value) if isinstance(components_value, dict) else {}
    schemas_value = components.get("schemas")
    schemas = dict(schemas_value) if isinstance(schemas_value, dict) else {}
    security_value = components.get("securitySchemes")
    security_schemes = dict(security_value) if isinstance(security_value, dict) else {}
    root_security = document.get("security", [])
    operations: dict[str, object] = {}
    referenced_schema_names: set[str] = set()
    referenced_security_names: set[str] = set()
    for path, raw_path_item in sorted(paths_payload.items()):
        if not str(path).startswith("/") or not isinstance(raw_path_item, dict):
            raise DeployError("openapi_paths_invalid")
        path_parameters = list(raw_path_item.get("parameters") or [])
        for method, raw_operation in sorted(raw_path_item.items()):
            normalized_method = str(method).lower()
            if normalized_method not in OPENAPI_HTTP_METHODS:
                continue
            if not isinstance(raw_operation, dict):
                raise DeployError("openapi_operation_invalid")
            effective_security = (
                raw_operation["security"]
                if "security" in raw_operation
                else root_security
            )
            for requirement in list(effective_security or []):
                if not isinstance(requirement, dict):
                    raise DeployError("openapi_security_invalid")
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
            _collect_referenced_openapi_schemas(
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
        raise DeployError("openapi_operations_missing")
    if referenced_schema_names - set(schemas) or referenced_security_names - set(
        security_schemes
    ):
        raise DeployError("openapi_component_missing")
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


def _version_openapi_evolution_preserved(
    live_operation: object,
    candidate_operation: object,
) -> bool:
    """Accept only the reviewed string-to-string-or-boolean /version evolution."""
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


def _control_tour_generated_viewer_evolution_preserved(
    live_payload: object,
    candidate_payload: object,
    *,
    slug: str,
) -> bool:
    """Accept only the pinned generated-viewer addition to the control tour."""
    if not isinstance(live_payload, dict) or not isinstance(candidate_payload, dict):
        return False
    if "generated_viewer" in live_payload:
        return False
    live = json.loads(json.dumps(live_payload))
    candidate = json.loads(json.dumps(candidate_payload))
    generated_viewer = candidate.pop("generated_viewer", None)
    if candidate != live:
        return False
    expected_viewer_path = (
        f"/tours/viewer/{urllib.parse.quote(slug, safe='')}/"
        "generated-reconstruction/viewer.html"
    )
    return generated_viewer == {
        "disclosure": CONTROL_TOUR_GENERATED_VIEWER_DISCLOSURE,
        "release_revision": f"property-3d-{PROPERTY_ARTIFACT_COMMIT[:12]}",
        "synthetic": True,
        "url": expected_viewer_path,
        "verified_provider_capture": False,
    }


def _openapi_control_evidence(
    *, contract: Mapping[str, Any], probe: Mapping[str, Any]
) -> dict[str, Any]:
    operations = dict(contract.get("operations") or {})
    schemas = dict(contract.get("schemas") or {})
    security_schemes = dict(contract.get("security_schemes") or {})
    paths = sorted({key.split(" ", 1)[1] for key in operations})
    encoded_paths = json.dumps(paths, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )
    encoded_contract = json.dumps(
        contract,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return {
        "paths": paths,
        "path_count": len(paths),
        "operation_count": len(operations),
        "schema_count": len(schemas),
        "security_scheme_count": len(security_schemes),
        "path_set_sha256": hashlib.sha256(encoded_paths).hexdigest(),
        "contract_sha256": hashlib.sha256(encoded_contract).hexdigest(),
        "probe": dict(probe),
    }


class MemorialDeployLane:
    def __init__(
        self,
        *,
        root: Path = ROOT,
        env: Mapping[str, str] | None = None,
        load_release_env_file: bool = True,
        runner: Runner | None = None,
        http_get: Callable[[str, float, str], HttpResponse] = _default_http_get,
        http_no_redirect: Callable[
            [str, float, str, str], HttpResponse
        ] = _default_http_no_redirect,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        wait_seconds: float = 90.0,
        poll_seconds: float = 2.0,
        request_timeout_seconds: float = 10.0,
        internal_openapi_snapshot: Callable[[], Mapping[str, Any]] | None = None,
        receipt_dir: Path | None = None,
        global_lock_path: Path | None = None,
        durable_root_check: Callable[[Path], None] = _require_durable_release_root,
        bind_source_validator: Callable[..., dict[str, object]] = (
            validate_memorial_bind_sources
        ),
    ) -> None:
        if not isinstance(load_release_env_file, bool):
            raise TypeError("load_release_env_file_must_be_bool")
        self.root = root.resolve()
        self.env = dict(os.environ if env is None else env)
        self.runner = runner or SubprocessRunner()
        self.http_get = http_get
        self.http_no_redirect = http_no_redirect
        self.sleep = sleep
        self.monotonic = monotonic
        self.wait_seconds = max(float(wait_seconds), 0.0)
        self.poll_seconds = max(float(poll_seconds), 0.05)
        self.request_timeout_seconds = max(float(request_timeout_seconds), 0.1)
        self.internal_openapi_snapshot = internal_openapi_snapshot
        self.durable_root_check = durable_root_check
        self.bind_source_validator = bind_source_validator
        self.env_file_values = (
            _parse_env_file(self.root / ".env") if load_release_env_file else {}
        )
        self.deployment_id = _safe_deployment_id(self.env)
        self.memorial_image_reference = str(
            self.env.get("EA_MEMORIAL_IMAGE") or ""
        ).strip()
        self.candidate_receipt_value = str(
            self.env.get("EA_MEMORIAL_CANDIDATE_RECEIPT") or ""
        ).strip()
        self.control_tour_slug = str(
            self.env.get("EA_MEMORIAL_CONTROL_TOUR_SLUG") or ""
        ).strip()
        if self.control_tour_slug and not CONTROL_TOUR_SLUG_PATTERN.fullmatch(
            self.control_tour_slug
        ):
            raise DeployError("memorial_control_tour_slug_invalid")
        configured_hosts = _first_nonempty(
            self.env.get("EA_MEMORIAL_PUBLIC_HOST_ALLOWLIST"),
            self.env_file_values.get("EA_MEMORIAL_PUBLIC_HOST_ALLOWLIST"),
            ",".join(DEFAULT_PUBLIC_HOSTS),
        )
        self.allowed_public_hosts = tuple(
            item.strip().lower().rstrip(".")
            for item in configured_hosts.split(",")
            if item.strip()
        )
        configured_receipt_dir = _first_nonempty(
            self.env.get("EA_MEMORIAL_DEPLOY_RECEIPT_DIR"),
            self.env_file_values.get("EA_MEMORIAL_DEPLOY_RECEIPT_DIR"),
        )
        self.receipt_dir = (
            receipt_dir.resolve()
            if receipt_dir is not None
            else (
                Path(configured_receipt_dir).expanduser()
                if configured_receipt_dir
                else self.root / ".runtime" / "deployments" / "memorial"
            )
        )
        if not self.receipt_dir.is_absolute():
            self.receipt_dir = self.root / self.receipt_dir
        self.receipt_dir = self.receipt_dir.resolve()
        self.receipt_path = self.receipt_dir / f"{self.deployment_id}.json"
        self.lock_path = self.receipt_dir / f"{self.deployment_id}.lock"
        self.rollback_capsule_path = (
            self.receipt_dir / f"{self.deployment_id}.rollback-capsule.compose.json"
        )
        self._rollback_capsule_project_directory = self.receipt_dir
        self.global_lock_path = (
            global_lock_path.resolve()
            if global_lock_path is not None
            else Path("/run/lock/ea-memorial-ea-api.lock")
        )
        if not self.global_lock_path.is_absolute():
            raise DeployError("global_lock_path_not_absolute")
        try:
            self.normalization_recovery_journal_path = (
                default_normalization_recovery_journal_path(operator_anchor=self.root)
            )
            self.joint_recovery_journal_path = default_joint_recovery_journal_path(
                operator_anchor=self.root
            )
        except MemorialRecoveryInterlockError as exc:
            raise DeployError(str(exc)) from exc
        self._mutation_action_deadline: float | None = None
        self._lock_handle: Any | None = None
        self._global_lock_handle: Any | None = None
        self.compose_bin: tuple[str, ...] = ()
        self.target_compose_files: tuple[str, ...] = ()
        self.target_compose_environment_files: tuple[str, ...] = ()
        self.bind_source_snapshot_sha256 = ""
        self._rollback_capsule_seal: dict[str, object] | None = None
        self._rollback_recovery_seal: dict[str, object] | None = None
        self._rollback_capsule_document: dict[str, Any] | None = None
        self._rollback_recovery_document: dict[str, Any] | None = None
        self._forward_recovery_capsule_path: Path | None = None
        self._forward_recovery_capsule_seal: dict[str, object] | None = None
        self._forward_recovery_capsule_directory_seal: dict[str, object] | None = None
        self._prior_compose_environment_files: tuple[str, ...] = ()
        self._prior_compose_environment_file_label = ""
        self.release_env = self._release_env()
        self.receipt: dict[str, Any] = {
            "contract_name": "ea.memorial_scoped_deploy_receipt.v2",
            "deployment_id": self.deployment_id,
            "project_name": PROJECT_NAME,
            "service_scope": [API_SERVICE, REDIS_SERVICE],
            "api_mutation_scope": [API_SERVICE],
            "target_compose_files": [],
            "rollback_compose_files": [],
            "started_at": _utc_now(),
            "status": "preflight",
            "rollback": {"status": "not_required"},
            "preparation": {
                "status": "not_started",
                "attempted_actions": [],
                "completed_actions": [],
                "pending_action": None,
                "active_action": None,
                "preparation_side_effects_possible": False,
                "api_mutation_started": False,
                "api_runtime_state": "unchanged",
            },
            "checks": [],
        }

    def _release_env(self) -> dict[str, str]:
        env = dict(self.env)
        env.update(
            {
                "COMPOSE_PROJECT_NAME": PROJECT_NAME,
                "EA_DEPLOYMENT_ID": self.deployment_id,
                "EA_DEPLOYMENT_ID_SOURCE": env.get(
                    "EA_DEPLOYMENT_ID_SOURCE", "ea_deploy_id_env"
                ),
                "EA_DEPLOY_PRIMARY_MODE": "MEMORIAL",
                "EA_DEPLOY_ENABLED_MODES": "MEMORIAL",
                "EA_DEPLOY_COMPOSE_FILES": "",
                "EA_DEPLOY_COMPOSE_OVERRIDES": MEMORIAL_COMPOSE_FILE,
            }
        )
        return env

    def _write_receipt(self) -> None:
        self.receipt_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            self.receipt_dir.chmod(0o700)
        except OSError as exc:
            raise DeployError("deployment_receipt_directory_unavailable") from exc
        if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
            raise DeployError("deployment_receipt_nofollow_unavailable")

        payload = (json.dumps(self.receipt, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        )
        temporary_name = f".{self.receipt_path.name}.tmp.{os.getpid()}"
        directory_flags = os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW
        file_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW
        directory_descriptor = -1
        descriptor = -1
        temporary_created = False
        try:
            directory_path_metadata = self.receipt_dir.lstat()
            directory_descriptor = os.open(self.receipt_dir, directory_flags)
            directory_metadata = os.fstat(directory_descriptor)
            if (
                not stat.S_ISDIR(directory_metadata.st_mode)
                or stat.S_ISLNK(directory_path_metadata.st_mode)
                or directory_metadata.st_uid != os.geteuid()
                or stat.S_IMODE(directory_metadata.st_mode) != 0o700
                or (directory_metadata.st_dev, directory_metadata.st_ino)
                != (directory_path_metadata.st_dev, directory_path_metadata.st_ino)
            ):
                raise DeployError("deployment_receipt_directory_invalid")

            descriptor = os.open(
                temporary_name,
                file_flags,
                0o600,
                dir_fd=directory_descriptor,
            )
            temporary_created = True
            os.fchmod(descriptor, 0o600)
            created_metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(created_metadata.st_mode)
                or created_metadata.st_nlink != 1
                or created_metadata.st_uid != os.geteuid()
                or stat.S_IMODE(created_metadata.st_mode) != 0o600
            ):
                raise DeployError("deployment_receipt_temporary_invalid")

            remaining = memoryview(payload)
            while remaining:
                written = os.write(descriptor, remaining)
                if written <= 0:
                    raise DeployError("deployment_receipt_write_failed")
                remaining = remaining[written:]
            os.fsync(descriptor)

            written_metadata = os.fstat(descriptor)
            temporary_metadata = os.stat(
                temporary_name,
                dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
            if (
                not stat.S_ISREG(written_metadata.st_mode)
                or written_metadata.st_nlink != 1
                or written_metadata.st_uid != os.geteuid()
                or stat.S_IMODE(written_metadata.st_mode) != 0o600
                or written_metadata.st_size != len(payload)
                or (written_metadata.st_dev, written_metadata.st_ino)
                != (created_metadata.st_dev, created_metadata.st_ino)
                or (temporary_metadata.st_dev, temporary_metadata.st_ino)
                != (created_metadata.st_dev, created_metadata.st_ino)
            ):
                raise DeployError("deployment_receipt_temporary_changed")

            os.close(descriptor)
            descriptor = -1
            os.replace(
                temporary_name,
                self.receipt_path.name,
                src_dir_fd=directory_descriptor,
                dst_dir_fd=directory_descriptor,
            )
            temporary_created = False
            receipt_metadata = os.stat(
                self.receipt_path.name,
                dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
            if (
                not stat.S_ISREG(receipt_metadata.st_mode)
                or receipt_metadata.st_nlink != 1
                or receipt_metadata.st_uid != os.geteuid()
                or stat.S_IMODE(receipt_metadata.st_mode) != 0o600
                or receipt_metadata.st_size != len(payload)
                or (receipt_metadata.st_dev, receipt_metadata.st_ino)
                != (created_metadata.st_dev, created_metadata.st_ino)
            ):
                raise DeployError("deployment_receipt_replacement_invalid")
            os.fsync(directory_descriptor)
            final_directory_metadata = self.receipt_dir.lstat()
            if stat.S_ISLNK(final_directory_metadata.st_mode) or (
                final_directory_metadata.st_dev,
                final_directory_metadata.st_ino,
            ) != (directory_metadata.st_dev, directory_metadata.st_ino):
                raise DeployError("deployment_receipt_directory_changed")
        except DeployError:
            raise
        except OSError as exc:
            raise DeployError("deployment_receipt_write_unavailable") from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            if temporary_created and directory_descriptor >= 0:
                try:
                    os.unlink(temporary_name, dir_fd=directory_descriptor)
                except OSError:
                    pass
            if directory_descriptor >= 0:
                os.close(directory_descriptor)

    @staticmethod
    def _open_private_parent_descriptor(
        path: Path, *, create_final: bool, reason_prefix: str
    ) -> int:
        selected = path.expanduser()
        if (
            not selected.is_absolute()
            or ".." in selected.parts
            or os.path.normpath(str(selected)) != str(selected)
            or selected.parent == Path("/")
        ):
            raise DeployError(f"{reason_prefix}_path_invalid")
        required = ("O_CLOEXEC", "O_DIRECTORY", "O_NOFOLLOW")
        if any(not hasattr(os, name) for name in required):
            raise DeployError(f"{reason_prefix}_nofollow_unavailable")
        flags = os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW
        try:
            current = os.open("/", flags)
        except OSError as exc:
            raise DeployError(f"{reason_prefix}_directory_unavailable") from exc
        try:
            parts = selected.parent.parts[1:]
            for index, component in enumerate(parts):
                final = index == len(parts) - 1
                try:
                    path_metadata = os.stat(
                        component,
                        dir_fd=current,
                        follow_symlinks=False,
                    )
                    child = os.open(component, flags, dir_fd=current)
                except FileNotFoundError as exc:
                    if not final or not create_final:
                        raise DeployError(
                            f"{reason_prefix}_directory_unavailable"
                        ) from exc
                    try:
                        os.mkdir(component, 0o700, dir_fd=current)
                        child = os.open(component, flags, dir_fd=current)
                        path_metadata = os.stat(
                            component,
                            dir_fd=current,
                            follow_symlinks=False,
                        )
                    except OSError as create_exc:
                        raise DeployError(
                            f"{reason_prefix}_directory_unavailable"
                        ) from create_exc
                except OSError as exc:
                    raise DeployError(f"{reason_prefix}_directory_unavailable") from exc
                child_metadata = os.fstat(child)
                if (
                    not stat.S_ISDIR(path_metadata.st_mode)
                    or stat.S_ISLNK(path_metadata.st_mode)
                    or not stat.S_ISDIR(child_metadata.st_mode)
                    or _trusted_directory_identity(path_metadata)
                    != _trusted_directory_identity(child_metadata)
                ):
                    os.close(child)
                    raise DeployError(f"{reason_prefix}_directory_invalid")
                os.close(current)
                current = child
            final_metadata = os.fstat(current)
            if final_metadata.st_uid != os.geteuid():
                raise DeployError(f"{reason_prefix}_directory_invalid")
            try:
                os.fchmod(current, 0o700)
                os.fsync(current)
            except OSError as exc:
                raise DeployError(f"{reason_prefix}_directory_invalid") from exc
            final_metadata = os.fstat(current)
            if stat.S_IMODE(final_metadata.st_mode) != 0o700:
                raise DeployError(f"{reason_prefix}_directory_invalid")
            descriptor = current
            current = -1
            return descriptor
        finally:
            if current >= 0:
                os.close(current)

    @staticmethod
    def _write_private_artifact_once(
        path: Path, payload: bytes, *, reason_prefix: str
    ) -> dict[str, object]:
        selected = path.expanduser()
        if (
            not selected.is_absolute()
            or ".." in selected.parts
            or not selected.name
            or len(payload) > MAX_DEPLOYMENT_INPUT_BYTES
        ):
            raise DeployError(f"{reason_prefix}_path_invalid")
        file_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW
        directory_descriptor = -1
        descriptor = -1
        created = False
        completed = False
        try:
            directory_descriptor = MemorialDeployLane._open_private_parent_descriptor(
                selected,
                create_final=True,
                reason_prefix=reason_prefix,
            )
            parent_metadata = os.fstat(directory_descriptor)
            if (
                not stat.S_ISDIR(parent_metadata.st_mode)
                or parent_metadata.st_uid != os.geteuid()
                or stat.S_IMODE(parent_metadata.st_mode) != 0o700
            ):
                raise DeployError(f"{reason_prefix}_directory_invalid")
            descriptor = os.open(
                selected.name,
                file_flags,
                0o600,
                dir_fd=directory_descriptor,
            )
            created = True
            os.fchmod(descriptor, 0o600)
            remaining = memoryview(payload)
            while remaining:
                written = os.write(descriptor, remaining)
                if written <= 0:
                    raise DeployError(f"{reason_prefix}_write_failed")
                remaining = remaining[written:]
            os.fsync(descriptor)
            metadata = os.fstat(descriptor)
            path_metadata = os.stat(
                selected.name,
                dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_nlink != 1
                or metadata.st_uid != os.geteuid()
                or stat.S_IMODE(metadata.st_mode) != 0o600
                or metadata.st_size != len(payload)
                or _trusted_file_identity(metadata)
                != _trusted_file_identity(path_metadata)
            ):
                raise DeployError(f"{reason_prefix}_file_invalid")
            os.fsync(directory_descriptor)
            completed = True
        except FileExistsError as exc:
            raise DeployError(f"{reason_prefix}_already_exists") from exc
        except DeployError:
            raise
        except OSError as exc:
            raise DeployError(f"{reason_prefix}_write_unavailable") from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            if directory_descriptor >= 0:
                if created and not completed:
                    try:
                        os.unlink(selected.name, dir_fd=directory_descriptor)
                    except OSError:
                        pass
                os.close(directory_descriptor)
        seal = MemorialDeployLane._deployment_input_file_seal(selected)
        if seal.get("mode") != "0600":
            raise DeployError(f"{reason_prefix}_mode_invalid")
        return seal

    @staticmethod
    def _remove_private_artifact(
        path: Path,
        expected_seal: Mapping[str, object],
        *,
        reason_prefix: str,
        allow_absent: bool = False,
    ) -> None:
        try:
            current = MemorialDeployLane._deployment_input_file_seal(path)
        except DeployError as exc:
            if allow_absent and str(exc) == (
                f"deployment_input_file_unavailable:{path.name}"
            ):
                return
            raise
        if current != dict(expected_seal) or current.get("mode") != "0600":
            raise DeployError(f"{reason_prefix}_changed")
        directory_descriptor = -1
        try:
            directory_descriptor = MemorialDeployLane._open_private_parent_descriptor(
                path,
                create_final=False,
                reason_prefix=reason_prefix,
            )
            path_metadata = os.stat(
                path.name,
                dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
            if int(path_metadata.st_dev) != int(current["device"]) or int(
                path_metadata.st_ino
            ) != int(current["inode"]):
                raise DeployError(f"{reason_prefix}_changed")
            os.unlink(path.name, dir_fd=directory_descriptor)
            os.fsync(directory_descriptor)
        except DeployError:
            raise
        except OSError as exc:
            raise DeployError(f"{reason_prefix}_cleanup_failed") from exc
        finally:
            if directory_descriptor >= 0:
                os.close(directory_descriptor)

    @staticmethod
    def _read_private_artifact(
        path: Path,
        *,
        reason_prefix: str,
        allow_absent: bool = False,
    ) -> tuple[bytes, dict[str, object]] | None:
        selected = path.expanduser()
        directory_descriptor = -1
        descriptor = -1
        try:
            directory_descriptor = MemorialDeployLane._open_private_parent_descriptor(
                selected,
                create_final=False,
                reason_prefix=reason_prefix,
            )
            try:
                path_metadata = os.stat(
                    selected.name,
                    dir_fd=directory_descriptor,
                    follow_symlinks=False,
                )
                descriptor = os.open(
                    selected.name,
                    os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK,
                    dir_fd=directory_descriptor,
                )
            except FileNotFoundError:
                if allow_absent:
                    return None
                raise DeployError(f"{reason_prefix}_unavailable")
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or stat.S_ISLNK(path_metadata.st_mode)
                or metadata.st_nlink != 1
                or metadata.st_uid != os.geteuid()
                or stat.S_IMODE(metadata.st_mode) != 0o600
                or _trusted_file_identity(metadata)
                != _trusted_file_identity(path_metadata)
                or not 0 < metadata.st_size <= MAX_DEPLOYMENT_INPUT_BYTES
            ):
                raise DeployError(f"{reason_prefix}_untrusted")
            identity = (
                metadata.st_dev,
                metadata.st_ino,
                metadata.st_mode,
                metadata.st_uid,
                metadata.st_gid,
                metadata.st_nlink,
                metadata.st_size,
                metadata.st_mtime_ns,
                metadata.st_ctime_ns,
            )
            raw = bytearray()
            digest = hashlib.sha256()
            while True:
                chunk = os.read(descriptor, 1024 * 1024)
                if not chunk:
                    break
                raw.extend(chunk)
                digest.update(chunk)
                if len(raw) > MAX_DEPLOYMENT_INPUT_BYTES:
                    raise DeployError(f"{reason_prefix}_too_large")
                current = os.fstat(descriptor)
                if (
                    current.st_dev,
                    current.st_ino,
                    current.st_mode,
                    current.st_uid,
                    current.st_gid,
                    current.st_nlink,
                    current.st_size,
                    current.st_mtime_ns,
                    current.st_ctime_ns,
                ) != identity:
                    raise DeployError(f"{reason_prefix}_changed_during_read")
            final = os.fstat(descriptor)
            final_path = os.stat(
                selected.name,
                dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
            if (
                len(raw) != final.st_size
                or _trusted_file_identity(final) != _trusted_file_identity(metadata)
                or _trusted_file_identity(final_path)
                != _trusted_file_identity(metadata)
            ):
                raise DeployError(f"{reason_prefix}_changed_during_read")
            return bytes(raw), {
                "path": selected.as_posix(),
                "sha256": digest.hexdigest(),
                "size_bytes": len(raw),
                "mode": "0600",
                "device": int(final.st_dev),
                "inode": int(final.st_ino),
                "uid": int(final.st_uid),
                "gid": int(final.st_gid),
                "link_count": int(final.st_nlink),
                "mtime_ns": int(final.st_mtime_ns),
                "ctime_ns": int(final.st_ctime_ns),
            }
        except DeployError:
            raise
        except OSError as exc:
            raise DeployError(f"{reason_prefix}_unavailable") from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            if directory_descriptor >= 0:
                os.close(directory_descriptor)

    @staticmethod
    def _replace_private_artifact(
        path: Path,
        payload: bytes,
        expected_seal: Mapping[str, object],
        *,
        reason_prefix: str,
    ) -> dict[str, object]:
        selected = path.expanduser()
        current = MemorialDeployLane._read_private_artifact(
            selected, reason_prefix=reason_prefix
        )
        if current is None or current[1] != dict(expected_seal):
            raise DeployError(f"{reason_prefix}_changed")
        if not payload or len(payload) > MAX_DEPLOYMENT_INPUT_BYTES:
            raise DeployError(f"{reason_prefix}_size_invalid")
        directory_descriptor = -1
        descriptor = -1
        temporary_created = False
        temporary_name = f".{selected.name}.tmp.{os.getpid()}.{time.monotonic_ns()}"
        try:
            directory_descriptor = MemorialDeployLane._open_private_parent_descriptor(
                selected,
                create_final=False,
                reason_prefix=reason_prefix,
            )
            path_metadata = os.stat(
                selected.name,
                dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
            if int(path_metadata.st_dev) != int(expected_seal["device"]) or int(
                path_metadata.st_ino
            ) != int(expected_seal["inode"]):
                raise DeployError(f"{reason_prefix}_changed")
            descriptor = os.open(
                temporary_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
                0o600,
                dir_fd=directory_descriptor,
            )
            temporary_created = True
            os.fchmod(descriptor, 0o600)
            remaining = memoryview(payload)
            while remaining:
                written = os.write(descriptor, remaining)
                if written <= 0:
                    raise DeployError(f"{reason_prefix}_write_failed")
                remaining = remaining[written:]
            os.fsync(descriptor)
            created_metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(created_metadata.st_mode)
                or created_metadata.st_nlink != 1
                or created_metadata.st_uid != os.geteuid()
                or stat.S_IMODE(created_metadata.st_mode) != 0o600
                or created_metadata.st_size != len(payload)
            ):
                raise DeployError(f"{reason_prefix}_replacement_invalid")
            os.close(descriptor)
            descriptor = -1
            os.replace(
                temporary_name,
                selected.name,
                src_dir_fd=directory_descriptor,
                dst_dir_fd=directory_descriptor,
            )
            temporary_created = False
            os.fsync(directory_descriptor)
        except DeployError:
            raise
        except OSError as exc:
            raise DeployError(f"{reason_prefix}_replace_failed") from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            if temporary_created and directory_descriptor >= 0:
                try:
                    os.unlink(temporary_name, dir_fd=directory_descriptor)
                except OSError:
                    pass
            if directory_descriptor >= 0:
                os.close(directory_descriptor)
        seal = MemorialDeployLane._deployment_input_file_seal(selected)
        if (
            seal.get("mode") != "0600"
            or seal.get("sha256") != hashlib.sha256(payload).hexdigest()
        ):
            raise DeployError(f"{reason_prefix}_replacement_invalid")
        return seal

    def _open_lock(self, path: Path, *, busy_reason: str) -> Any:
        selected_path = path.expanduser()
        if not selected_path.is_absolute() or ".." in selected_path.parts:
            raise DeployError("lock_file_path_invalid")
        selected_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_NONBLOCK"):
            raise DeployError("lock_file_nofollow_unavailable")
        flags = os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
        descriptor = -1
        handle: Any | None = None
        created = False
        try:
            descriptor = os.open(selected_path, flags | os.O_CREAT | os.O_EXCL, 0o600)
            created = True
        except FileExistsError:
            try:
                descriptor = os.open(selected_path, flags)
            except OSError as exc:
                raise DeployError(
                    f"lock_file_unavailable:{selected_path.name}"
                ) from exc
        except OSError as exc:
            raise DeployError(f"lock_file_unavailable:{selected_path.name}") from exc
        try:
            if created:
                os.fchmod(descriptor, 0o600)
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_nlink != 1
                or metadata.st_uid != os.geteuid()
                or stat.S_IMODE(metadata.st_mode) != 0o600
            ):
                raise DeployError(f"lock_file_untrusted:{selected_path.name}")
            handle = os.fdopen(descriptor, "a+", encoding="utf-8")
            descriptor = -1
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise DeployError(busy_reason) from exc
            try:
                path_metadata = os.stat(selected_path, follow_symlinks=False)
            except OSError as exc:
                raise DeployError(f"lock_file_changed:{selected_path.name}") from exc
            if _trusted_file_identity(path_metadata) != _trusted_file_identity(
                metadata
            ):
                raise DeployError(f"lock_file_changed:{selected_path.name}")
            handle.seek(0)
            handle.truncate()
            handle.write(f"pid={os.getpid()}\n")
            handle.flush()
            os.fsync(handle.fileno())
            final_metadata = os.fstat(handle.fileno())
            final_path_metadata = os.stat(selected_path, follow_symlinks=False)
            if _trusted_file_identity(final_path_metadata) != _trusted_file_identity(
                final_metadata
            ):
                raise DeployError(f"lock_file_changed:{selected_path.name}")
            return handle
        except BaseException as exc:
            if descriptor >= 0:
                os.close(descriptor)
            elif handle is not None:
                try:
                    handle.close()
                except OSError:
                    pass
            if isinstance(exc, OSError):
                raise DeployError(
                    f"lock_file_unavailable:{selected_path.name}"
                ) from exc
            raise

    def _acquire_lock(self) -> None:
        self.receipt_dir.mkdir(parents=True, exist_ok=True)
        if self.receipt_path.exists():
            raise DeployError("deployment_receipt_already_exists")
        self._global_lock_handle = self._open_lock(
            self.global_lock_path,
            busy_reason="memorial_api_deployment_already_running",
        )
        try:
            self._lock_handle = self._open_lock(
                self.lock_path, busy_reason="deployment_already_running"
            )
        except Exception:
            self._release_lock()
            raise

    def _release_lock(self) -> None:
        handles = (self._lock_handle, self._global_lock_handle)
        self._lock_handle = None
        self._global_lock_handle = None
        for handle in handles:
            if handle is None:
                continue
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()

    def _require_normalization_recovery_absent(self) -> None:
        try:
            require_normalization_recovery_absent(
                self.normalization_recovery_journal_path
            )
        except MemorialRecoveryInterlockError as exc:
            raise DeployError(str(exc)) from exc

    def _require_joint_recovery_absent(self) -> None:
        try:
            require_joint_recovery_absent(self.joint_recovery_journal_path)
        except MemorialRecoveryInterlockError as exc:
            raise DeployError(str(exc)) from exc

    def _record_check(self, name: str, status: str, **detail: object) -> None:
        checks = list(self.receipt.get("checks") or [])
        checks.append({"name": name, "status": status, **detail})
        self.receipt["checks"] = checks
        self._write_receipt()

    def _read_trusted_guard_file(
        self,
        path: Path,
        *,
        expected_mode: int,
        expected_uid: int,
        max_bytes: int,
        reason_prefix: str,
    ) -> bytes:
        if not hasattr(os, "O_NOFOLLOW"):
            raise DeployError(f"{reason_prefix}_nofollow_unavailable")
        if not hasattr(os, "O_NONBLOCK"):
            raise DeployError(f"{reason_prefix}_nonblock_unavailable")
        flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
        descriptor = -1
        try:
            descriptor = os.open(path, flags)
        except OSError as exc:
            raise DeployError(f"{reason_prefix}_unavailable") from exc
        try:
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_nlink != 1
                or stat.S_IMODE(metadata.st_mode) != expected_mode
                or metadata.st_uid != expected_uid
            ):
                raise DeployError(f"{reason_prefix}_untrusted")
            if not 0 < metadata.st_size <= max_bytes:
                raise DeployError(f"{reason_prefix}_size_invalid")
            with os.fdopen(descriptor, "rb") as handle:
                descriptor = -1
                raw = handle.read(max_bytes + 1)
                final_metadata = os.fstat(handle.fileno())
        except OSError as exc:
            raise DeployError(f"{reason_prefix}_unreadable") from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        try:
            final_path_metadata = os.stat(path, follow_symlinks=False)
        except OSError as exc:
            raise DeployError(f"{reason_prefix}_changed_during_read") from exc
        if (
            len(raw) != metadata.st_size
            or len(raw) > max_bytes
            or _trusted_file_identity(final_metadata)
            != _trusted_file_identity(metadata)
            or _trusted_file_identity(final_path_metadata)
            != _trusted_file_identity(metadata)
        ):
            raise DeployError(f"{reason_prefix}_changed_during_read")
        return raw

    def _monotonic_now(self) -> float:
        try:
            monotonic_now = self.monotonic()
        except Exception as exc:
            raise DeployError("mutation_action_clock_invalid") from exc
        if (
            isinstance(monotonic_now, bool)
            or not isinstance(monotonic_now, (int, float))
            or not math.isfinite(monotonic_now)
        ):
            raise DeployError("mutation_action_clock_invalid")
        return float(monotonic_now)

    def _remaining_mutation_action_seconds(self) -> float | None:
        deadline = self._mutation_action_deadline
        if deadline is None:
            return None
        remaining = deadline - self._monotonic_now()
        if not math.isfinite(remaining) or remaining <= 0:
            raise DeployError("mutation_action_deadline_exceeded")
        return remaining

    @contextmanager
    def _bounded_mutation_action(self) -> Iterator[None]:
        if self._mutation_action_deadline is not None:
            raise DeployError("mutation_action_deadline_nested")
        monotonic_now = self._monotonic_now()
        deadline = monotonic_now + MAX_MUTATION_ACTION_SECONDS
        if not math.isfinite(deadline) or deadline <= monotonic_now:
            raise DeployError("mutation_action_clock_invalid")
        self._mutation_action_deadline = deadline
        try:
            yield
            self._remaining_mutation_action_seconds()
        finally:
            self._mutation_action_deadline = None

    def _run(
        self,
        args: Sequence[str],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        remaining_seconds = self._remaining_mutation_action_seconds()
        run_kwargs = {
            "cwd": (cwd or self.root),
            "env": (self.release_env if env is None else env),
            "check": check,
        }
        if isinstance(self.runner, SubprocessRunner):
            return self.runner.run(
                list(args),
                **run_kwargs,
                timeout_seconds=remaining_seconds,
            )
        return self.runner.run(list(args), **run_kwargs)

    def _detect_compose(self) -> None:
        docker_compose = self._run(["docker", "compose", "version"], check=False)
        if docker_compose.returncode == 0:
            self.compose_bin = ("docker", "compose")
            return
        legacy = self._run(["docker-compose", "version"], check=False)
        if legacy.returncode == 0:
            self.compose_bin = ("docker-compose",)
            return
        raise DeployError("docker_compose_unavailable")

    def _compose_args(
        self,
        *,
        root: Path,
        files: Sequence[str],
        environment_files: Sequence[str] | None = None,
    ) -> list[str]:
        if not self.compose_bin:
            raise DeployError("docker_compose_unavailable")
        selected_root = root.expanduser()
        if not selected_root.is_absolute() or ".." in selected_root.parts:
            raise DeployError("compose_root_invalid")
        selected_environment_files = (
            tuple(environment_files) if environment_files is not None else (".env",)
        )
        if not selected_environment_files:
            raise DeployError("compose_environment_files_missing")
        args = [
            *self.compose_bin,
            "--project-name",
            PROJECT_NAME,
            "--project-directory",
            str(selected_root),
        ]
        for filename in selected_environment_files:
            candidate = Path(str(filename)).expanduser()
            env_file = (
                candidate if candidate.is_absolute() else selected_root / candidate
            )
            if not env_file.is_absolute() or ".." in env_file.parts:
                raise DeployError("compose_environment_file_path_invalid")
            try:
                self._deployment_input_file_seal(env_file)
            except DeployError as exc:
                if str(exc) == (f"deployment_input_file_unavailable:{env_file.name}"):
                    raise DeployError(f"env_file_missing:{env_file}") from exc
                raise
            args.extend(["--env-file", str(env_file)])
        for filename in files:
            candidate = Path(str(filename)).expanduser()
            path = candidate if candidate.is_absolute() else selected_root / candidate
            if not path.is_absolute() or ".." in path.parts:
                raise DeployError(f"compose_file_path_invalid:{path.name}")
            try:
                self._deployment_input_file_seal(path)
            except DeployError as exc:
                if str(exc) == f"deployment_input_file_unavailable:{path.name}":
                    raise DeployError(f"compose_file_missing:{path}") from exc
                raise
            args.extend(["-f", str(path)])
        return args

    def _target_compose(self, *args: str) -> list[str]:
        if not self.target_compose_files:
            raise DeployError("forward_compose_topology_unresolved")
        return [
            *self._compose_args(
                root=self.root,
                files=self.target_compose_files,
                environment_files=(self.target_compose_environment_files or None),
            ),
            *args,
        ]

    def _release_head_blob_identity(self, path: Path, *, source_revision: str) -> str:
        try:
            relative = path.relative_to(self.root).as_posix()
        except ValueError as exc:
            raise DeployError("forward_external_bridge_release_path_invalid") from exc
        if (
            not relative
            or relative.startswith("../")
            or SOURCE_REVISION_PATTERN.fullmatch(source_revision) is None
        ):
            raise DeployError("forward_external_bridge_release_path_invalid")
        worktree = self._run(
            ["git", "hash-object", "--no-filters", "--", relative],
            check=False,
        )
        committed = self._run(
            ["git", "rev-parse", f"{source_revision}:{relative}"],
            check=False,
        )
        worktree_blob = (worktree.stdout or "").strip()
        committed_blob = (committed.stdout or "").strip()
        object_pattern = re.compile(r"^[0-9a-f]{40,64}$")
        if (
            worktree.returncode != 0
            or committed.returncode != 0
            or object_pattern.fullmatch(worktree_blob) is None
            or object_pattern.fullmatch(committed_blob) is None
            or worktree_blob != committed_blob
        ):
            raise DeployError(
                f"forward_external_bridge_release_head_blob_mismatch:{path.name}"
            )
        return committed_blob

    def _validate_trusted_external_topology_bridge(
        self,
        *,
        previous: Mapping[str, Any],
        prior_root: Path,
        prior_files: Sequence[Path],
    ) -> dict[str, Any]:
        expected_names = TRUSTED_EXTERNAL_COMPOSE_LAYER_ORDER
        observed_names = tuple(path.name for path in prior_files)
        if observed_names != expected_names:
            raise DeployError("forward_external_bridge_layer_order_invalid")
        try:
            first_prior_root = self._deployment_input_directory_seal(prior_root)
        except DeployError as exc:
            raise DeployError("forward_external_bridge_working_dir_invalid") from exc
        prior_git_root = self._run(
            ["git", "-C", str(prior_root), "rev-parse", "--show-toplevel"],
            check=False,
        )
        if prior_git_root.returncode != 0 or (
            prior_git_root.stdout or ""
        ).strip() != str(prior_root):
            raise DeployError("forward_external_bridge_working_dir_untrusted")
        if any(
            not path.is_absolute()
            or ".." in path.parts
            or os.path.normpath(str(path)) != str(path)
            for path in prior_files
        ):
            raise DeployError("forward_external_bridge_compose_path_invalid")
        common_roots = {path.parent for path in prior_files}
        if len(common_roots) != 1:
            raise DeployError("forward_external_bridge_common_root_invalid")
        common_root = next(iter(common_roots))
        if common_root == prior_root or any(
            path != common_root / basename
            for path, basename in zip(prior_files, expected_names, strict=True)
        ):
            raise DeployError("forward_external_bridge_common_root_invalid")
        try:
            first_common_root = self._deployment_input_directory_seal(common_root)
        except DeployError as exc:
            raise DeployError("forward_external_bridge_common_root_invalid") from exc
        if first_common_root.get("mode") != "0700":
            raise DeployError("forward_external_bridge_common_root_mode_invalid")

        release_paths = tuple(self.root / basename for basename in expected_names)

        def compose_seals(paths: Sequence[Path]) -> list[dict[str, object]]:
            seals: list[dict[str, object]] = []
            for selected in paths:
                try:
                    seal = self._deployment_input_file_seal(selected)
                except DeployError as exc:
                    raise DeployError(
                        f"forward_external_bridge_compose_invalid:{selected.name}"
                    ) from exc
                seals.append(seal)
            return seals

        first_external_compose = compose_seals(prior_files)
        if any(seal.get("mode") != "0600" for seal in first_external_compose):
            raise DeployError("forward_external_bridge_compose_mode_invalid")
        first_release_compose = compose_seals(release_paths)
        source_revision = str(
            dict(self.receipt.get("release_source") or {}).get("source_revision") or ""
        )
        head_blobs = [
            self._release_head_blob_identity(
                release_path, source_revision=source_revision
            )
            for release_path in release_paths
        ]
        for basename, external_seal, release_seal in zip(
            expected_names,
            first_external_compose,
            first_release_compose,
            strict=True,
        ):
            blobs_match = external_seal.get("sha256") == release_seal.get(
                "sha256"
            ) and external_seal.get("size_bytes") == release_seal.get("size_bytes")
            if (
                basename not in TRUSTED_EXTERNAL_BRIDGE_REPLACEABLE_LAYERS
                and not blobs_match
            ):
                raise DeployError(
                    f"forward_external_bridge_compose_blob_mismatch:{basename}"
                )

        prior_runtime_root = prior_root / EA_RUNTIME_ENV_DIRECTORY
        prior_environment_files = (
            prior_runtime_root / EA_RUNTIME_ENV_FILE,
            prior_runtime_root / EA_RUNTIME_LOCAL_ENV_FILE,
        )
        expected_environment_label = ",".join(
            path.as_posix() for path in prior_environment_files
        )
        if (
            self._prior_compose_environment_file_label != expected_environment_label
            or self._prior_compose_environment_files
            != tuple(path.as_posix() for path in prior_environment_files)
        ):
            raise DeployError("forward_external_bridge_environment_label_invalid")
        try:
            first_prior_runtime_root = self._deployment_input_directory_seal(
                prior_runtime_root
            )
        except DeployError as exc:
            raise DeployError(
                "forward_external_bridge_environment_root_invalid"
            ) from exc
        if first_prior_runtime_root.get("mode") != "0700":
            raise DeployError("forward_external_bridge_environment_root_mode_invalid")

        def private_environment_bytes(
            paths: Sequence[Path], *, reason: str
        ) -> tuple[list[bytes], list[dict[str, object]]]:
            payloads: list[bytes] = []
            seals: list[dict[str, object]] = []
            for selected in paths:
                try:
                    payload, seal = self._deployment_input_file_bytes(selected)
                except DeployError as exc:
                    raise DeployError(reason) from exc
                if seal.get("mode") != "0600":
                    raise DeployError(f"{reason}_mode_invalid")
                payloads.append(payload)
                seals.append(seal)
            return payloads, seals

        prior_source_files = (prior_root / ".env", prior_root / ".env.local")
        prior_source_bytes, first_prior_sources = private_environment_bytes(
            prior_source_files,
            reason="forward_external_bridge_environment_source_invalid",
        )
        prior_projection_bytes, first_prior_environment = private_environment_bytes(
            prior_environment_files,
            reason="forward_external_bridge_environment_file_invalid",
        )
        if any(b"\x00" in payload for payload in prior_source_bytes):
            raise DeployError("forward_external_bridge_environment_source_invalid")
        expected_prior_projection = [
            sanitize_env_bytes(payload)[0] for payload in prior_source_bytes
        ]
        if prior_projection_bytes != expected_prior_projection:
            raise DeployError("forward_external_bridge_environment_projection_invalid")

        release_runtime_root = self.root / EA_RUNTIME_ENV_DIRECTORY
        release_environment_files = (
            release_runtime_root / EA_RUNTIME_ENV_FILE,
            release_runtime_root / EA_RUNTIME_LOCAL_ENV_FILE,
        )
        try:
            first_release_runtime_root = self._deployment_input_directory_seal(
                release_runtime_root
            )
        except DeployError as exc:
            raise DeployError(
                "forward_external_bridge_release_environment_root_invalid"
            ) from exc
        if first_release_runtime_root.get("mode") != "0700":
            raise DeployError(
                "forward_external_bridge_release_environment_root_mode_invalid"
            )
        release_environment_bytes, first_release_environment = (
            private_environment_bytes(
                release_environment_files,
                reason="forward_external_bridge_release_environment_file_invalid",
            )
        )
        if prior_projection_bytes != release_environment_bytes:
            raise DeployError("forward_external_bridge_environment_projection_mismatch")

        runtime_projection = self.receipt.get("runtime_environment_projection")
        outputs = (
            runtime_projection.get("outputs")
            if isinstance(runtime_projection, Mapping)
            else None
        )
        if not isinstance(outputs, list) or len(outputs) != 2:
            raise DeployError("forward_external_bridge_environment_projection_invalid")
        output_by_destination = {
            str(item.get("destination") or ""): item
            for item in outputs
            if isinstance(item, Mapping)
        }
        expected_projection_sources = {
            f"{EA_RUNTIME_ENV_DIRECTORY}/{EA_RUNTIME_ENV_FILE}": ".env",
            f"{EA_RUNTIME_ENV_DIRECTORY}/{EA_RUNTIME_LOCAL_ENV_FILE}": ".env.local",
        }
        if set(output_by_destination) != set(expected_projection_sources):
            raise DeployError("forward_external_bridge_environment_projection_invalid")

        for seal, (destination, source) in zip(
            first_release_environment,
            expected_projection_sources.items(),
            strict=True,
        ):
            output = output_by_destination[destination]
            if (
                output.get("source") != source
                or output.get("sha256") != seal.get("sha256")
                or output.get("byte_count") != seal.get("size_bytes")
            ):
                raise DeployError(
                    "forward_external_bridge_environment_projection_invalid"
                )

        second = {
            "prior_root": self._deployment_input_directory_seal(prior_root),
            "common_root": self._deployment_input_directory_seal(common_root),
            "external_compose": compose_seals(prior_files),
            "release_compose": compose_seals(release_paths),
            "prior_runtime_root": self._deployment_input_directory_seal(
                prior_runtime_root
            ),
            "prior_sources": [
                self._deployment_input_file_seal(path) for path in prior_source_files
            ],
            "prior_environment": [
                self._deployment_input_file_seal(path)
                for path in prior_environment_files
            ],
            "release_runtime_root": self._deployment_input_directory_seal(
                release_runtime_root
            ),
            "release_environment": [
                self._deployment_input_file_seal(path)
                for path in release_environment_files
            ],
        }
        first = {
            "prior_root": first_prior_root,
            "common_root": first_common_root,
            "external_compose": first_external_compose,
            "release_compose": first_release_compose,
            "prior_runtime_root": first_prior_runtime_root,
            "prior_sources": first_prior_sources,
            "prior_environment": first_prior_environment,
            "release_runtime_root": first_release_runtime_root,
            "release_environment": first_release_environment,
        }
        if first != second:
            raise DeployError("forward_external_bridge_seal_unstable")
        return {
            "status": "pass",
            "bridge": "direct_joint_without_baseline_normalization",
            "working_dir": prior_root.as_posix(),
            "common_external_root": common_root.as_posix(),
            "ordered_layer_basenames": list(expected_names),
            "replaceable_layer_basenames": sorted(
                TRUSTED_EXTERNAL_BRIDGE_REPLACEABLE_LAYERS
            ),
            "environment_files": [path.as_posix() for path in prior_environment_files],
            "trusted_prior_root_seal": first_prior_root,
            "common_external_root_seal": first_common_root,
            "runtime_environment_root_seal": first_prior_runtime_root,
            "compose_file_seals": [
                {
                    "basename": basename,
                    "external": external_seal,
                    "release": release_seal,
                    "release_head_blob": head_blob,
                    "external_matches_release": (
                        external_seal.get("sha256") == release_seal.get("sha256")
                        and external_seal.get("size_bytes")
                        == release_seal.get("size_bytes")
                    ),
                    "forward_policy": (
                        "replace_with_release_head"
                        if basename in TRUSTED_EXTERNAL_BRIDGE_REPLACEABLE_LAYERS
                        else "require_exact_external_release_blob"
                    ),
                }
                for basename, external_seal, release_seal, head_blob in zip(
                    expected_names,
                    first_external_compose,
                    first_release_compose,
                    head_blobs,
                    strict=True,
                )
            ],
            "environment_source_seals": first_prior_sources,
            "environment_file_seals": first_prior_environment,
            "release_environment_file_seals": first_release_environment,
            "rollback_capsule_source_environment_sha256": str(
                previous.get("environment_sha256") or ""
            ),
            "original_topology_retained_in_receipt": True,
            "two_sample_seal_verified": True,
        }

    def _validate_recovered_capsule_topology_bridge(
        self,
        *,
        previous: Mapping[str, Any],
        prior_root: Path,
        prior_files: Sequence[Path],
    ) -> dict[str, Any]:
        if len(prior_files) != 1:
            raise DeployError("forward_recovery_capsule_topology_invalid")
        capsule_path = prior_files[0]
        if (
            prior_root != self.receipt_dir
            or not capsule_path.is_absolute()
            or ".." in capsule_path.parts
            or os.path.normpath(str(capsule_path)) != str(capsule_path)
            or capsule_path.parent != prior_root
            or not capsule_path.name.endswith(ROLLBACK_CAPSULE_FILE_SUFFIX)
        ):
            raise DeployError("forward_recovery_capsule_path_invalid")
        if (
            self._prior_compose_environment_file_label
            or self._prior_compose_environment_files
        ):
            raise DeployError("forward_recovery_capsule_environment_label_invalid")

        try:
            first_prior_root = self._deployment_input_directory_seal(prior_root)
        except DeployError as exc:
            raise DeployError("forward_recovery_capsule_directory_invalid") from exc
        if (
            first_prior_root.get("mode") != "0700"
            or first_prior_root.get("uid") != os.geteuid()
            or first_prior_root.get("gid") != os.getegid()
        ):
            raise DeployError("forward_recovery_capsule_directory_mode_invalid")
        try:
            capsule_payload, first_capsule_seal = self._deployment_input_file_bytes(
                capsule_path
            )
        except DeployError as exc:
            raise DeployError("forward_recovery_capsule_file_invalid") from exc
        if (
            first_capsule_seal.get("mode") != "0600"
            or first_capsule_seal.get("uid") != os.geteuid()
            or first_capsule_seal.get("gid") != os.getegid()
            or first_capsule_seal.get("link_count") != 1
        ):
            raise DeployError("forward_recovery_capsule_file_mode_invalid")

        def unique_object(
            pairs: list[tuple[str, object]],
        ) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("duplicate_json_key")
                result[key] = value
            return result

        def reject_nonfinite_json_constant(_value: str) -> object:
            raise ValueError("nonfinite_json_number")

        try:
            decoded = json.loads(
                capsule_payload.decode("utf-8"),
                object_pairs_hook=unique_object,
                parse_constant=reject_nonfinite_json_constant,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise DeployError("forward_recovery_capsule_json_invalid") from exc
        if not isinstance(decoded, dict):
            raise DeployError("forward_recovery_capsule_json_invalid")
        document = dict(decoded)
        canonical_payload = (
            json.dumps(
                document,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
        if capsule_payload != canonical_payload:
            raise DeployError("forward_recovery_capsule_json_noncanonical")

        expected_value = previous.get("rollback_capsule_document")
        if not isinstance(expected_value, dict):
            raise DeployError("forward_recovery_capsule_live_projection_invalid")
        expected_document = dict(expected_value)
        try:
            bindings = self._rollback_capsule_external_bindings(
                document, reason_prefix="forward_recovery_capsule"
            )
            expected_bindings = self._rollback_capsule_external_bindings(
                expected_document, reason_prefix="forward_recovery_capsule_live"
            )
        except DeployError as exc:
            raise DeployError("forward_recovery_capsule_extension_invalid") from exc
        extension_value = document.get("x-ea-rollback-capsule")
        expected_extension_value = expected_document.get("x-ea-rollback-capsule")
        extension = dict(extension_value) if isinstance(extension_value, dict) else {}
        expected_extension = (
            dict(expected_extension_value)
            if isinstance(expected_extension_value, dict)
            else {}
        )
        historical_deployment_id = str(extension.get("deployment_id") or "")
        if capsule_path.name != (
            f"{historical_deployment_id}{ROLLBACK_CAPSULE_FILE_SUFFIX}"
        ):
            raise DeployError("forward_recovery_capsule_deployment_path_mismatch")
        captured_at = extension.get("captured_at")
        if (
            not isinstance(captured_at, str)
            or len(captured_at) > 64
            or re.fullmatch(
                r"[0-9]{4}-[0-9]{2}-[0-9]{2}T"
                r"[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z",
                captured_at,
            )
            is None
        ):
            raise DeployError("forward_recovery_capsule_captured_at_invalid")
        try:
            parsed_captured_at = datetime.fromisoformat(captured_at[:-1] + "+00:00")
        except ValueError as exc:
            raise DeployError("forward_recovery_capsule_captured_at_invalid") from exc
        if (
            parsed_captured_at.utcoffset() is None
            or parsed_captured_at.utcoffset().total_seconds() != 0
            or parsed_captured_at.isoformat().replace("+00:00", "Z") != captured_at
        ):
            raise DeployError("forward_recovery_capsule_captured_at_invalid")
        allowed_differences = extension.get("allowed_runtime_differences")
        if (
            not isinstance(allowed_differences, list)
            or tuple(allowed_differences)
            != ROLLBACK_CAPSULE_ALLOWED_RUNTIME_DIFFERENCES
        ):
            raise DeployError("forward_recovery_capsule_allowed_differences_invalid")
        if extension.get("source_image_id") != previous.get(
            "image_id"
        ) or extension.get("source_image_reference") != previous.get("image_reference"):
            raise DeployError("forward_recovery_capsule_image_mismatch")
        functional_identity = self._validated_functional_identity(
            extension.get("functional_identity"),
            reason_prefix="forward_recovery_capsule",
        )
        if functional_identity != previous.get("functional_identity"):
            raise DeployError("forward_recovery_capsule_functional_identity_mismatch")
        if bindings != expected_bindings:
            raise DeployError("forward_recovery_capsule_external_resources_mismatch")

        volatile_extension_keys = {
            "captured_at",
            "deployment_id",
            "source_container_id_sha256",
        }
        stable_extension_keys = set(extension) - volatile_extension_keys
        if stable_extension_keys != set(expected_extension) - volatile_extension_keys:
            raise DeployError("forward_recovery_capsule_extension_projection_mismatch")
        if any(
            extension.get(key) != expected_extension.get(key)
            for key in stable_extension_keys
        ):
            raise DeployError("forward_recovery_capsule_extension_projection_mismatch")
        if set(document) != set(expected_document) or any(
            document.get(key) != expected_document.get(key)
            for key in set(document) - {"x-ea-rollback-capsule"}
        ):
            raise DeployError("forward_recovery_capsule_runtime_projection_mismatch")

        release_paths = tuple(
            self.root / basename for basename in TRUSTED_EXTERNAL_COMPOSE_LAYER_ORDER
        )

        def compose_seals(paths: Sequence[Path]) -> list[dict[str, object]]:
            seals: list[dict[str, object]] = []
            for selected in paths:
                try:
                    seal = self._deployment_input_file_seal(selected)
                except DeployError as exc:
                    raise DeployError(
                        f"forward_recovery_capsule_release_compose_invalid:"
                        f"{selected.name}"
                    ) from exc
                seals.append(seal)
            return seals

        first_release_compose = compose_seals(release_paths)
        source_revision = str(
            dict(self.receipt.get("release_source") or {}).get("source_revision") or ""
        )
        head_blobs = [
            self._release_head_blob_identity(path, source_revision=source_revision)
            for path in release_paths
        ]

        runtime_projection = self.receipt.get("runtime_environment_projection")
        outputs = (
            runtime_projection.get("outputs")
            if isinstance(runtime_projection, Mapping)
            else None
        )
        if (
            not isinstance(outputs, list)
            or not outputs
            or any(not isinstance(item, Mapping) for item in outputs)
        ):
            raise DeployError("forward_recovery_capsule_environment_projection_invalid")
        output_by_destination = {
            str(item.get("destination") or ""): item for item in outputs
        }
        primary_destination = f"{EA_RUNTIME_ENV_DIRECTORY}/{EA_RUNTIME_ENV_FILE}"
        local_destination = f"{EA_RUNTIME_ENV_DIRECTORY}/{EA_RUNTIME_LOCAL_ENV_FILE}"
        if (
            len(output_by_destination) != len(outputs)
            or primary_destination not in output_by_destination
            or set(output_by_destination)
            not in ({primary_destination}, {primary_destination, local_destination})
        ):
            raise DeployError("forward_recovery_capsule_environment_projection_invalid")
        environment_filenames = [EA_RUNTIME_ENV_FILE]
        if local_destination in output_by_destination:
            environment_filenames.append(EA_RUNTIME_LOCAL_ENV_FILE)
        runtime_root = self.root / EA_RUNTIME_ENV_DIRECTORY
        try:
            first_runtime_root = self._deployment_input_directory_seal(runtime_root)
        except DeployError as exc:
            raise DeployError(
                "forward_recovery_capsule_environment_root_invalid"
            ) from exc
        if (
            first_runtime_root.get("mode") != "0700"
            or first_runtime_root.get("uid") != os.geteuid()
            or first_runtime_root.get("gid") != os.getegid()
        ):
            raise DeployError("forward_recovery_capsule_environment_root_mode_invalid")
        environment_paths = tuple(
            runtime_root / filename for filename in environment_filenames
        )
        first_environment: list[dict[str, object]] = []
        expected_environment_rows = [(primary_destination, ".env")]
        if local_destination in output_by_destination:
            expected_environment_rows.append((local_destination, ".env.local"))
        for path, (destination, source) in zip(
            environment_paths, expected_environment_rows, strict=True
        ):
            try:
                seal = self._deployment_input_file_seal(path)
            except DeployError as exc:
                raise DeployError(
                    "forward_recovery_capsule_environment_file_invalid"
                ) from exc
            output = output_by_destination[destination]
            if (
                seal.get("mode") != "0600"
                or seal.get("uid") != os.geteuid()
                or seal.get("gid") != os.getegid()
                or seal.get("link_count") != 1
                or output.get("source") != source
                or output.get("sha256") != seal.get("sha256")
                or output.get("byte_count") != seal.get("size_bytes")
            ):
                raise DeployError(
                    "forward_recovery_capsule_environment_projection_invalid"
                )
            first_environment.append(seal)

        second_prior_root = self._deployment_input_directory_seal(prior_root)
        second_capsule_seal = self._deployment_input_file_seal(capsule_path)
        second_release_compose = compose_seals(release_paths)
        second_runtime_root = self._deployment_input_directory_seal(runtime_root)
        second_environment = [
            self._deployment_input_file_seal(path) for path in environment_paths
        ]
        if (
            first_prior_root != second_prior_root
            or first_capsule_seal != second_capsule_seal
            or first_release_compose != second_release_compose
            or first_runtime_root != second_runtime_root
            or first_environment != second_environment
        ):
            raise DeployError("forward_recovery_capsule_seal_unstable")

        self._forward_recovery_capsule_path = capsule_path
        self._forward_recovery_capsule_seal = dict(first_capsule_seal)
        self._forward_recovery_capsule_directory_seal = {
            key: first_prior_root[key]
            for key in ("path", "mode", "device", "inode", "uid", "gid")
        }
        return {
            "status": "pass",
            "bridge": "verified_recovery_capsule_to_canonical_release",
            "capsule_basename": capsule_path.name,
            "capsule_seal": first_capsule_seal,
            "historical_deployment_id": historical_deployment_id,
            "captured_at": captured_at,
            "functional_identity_sha256": str(
                functional_identity.get("functional_identity_sha256") or ""
            ),
            "external_resource_binding_sha256": _canonical_json_sha256(bindings),
            "ordered_layer_basenames": list(TRUSTED_EXTERNAL_COMPOSE_LAYER_ORDER),
            "release_compose_file_seals": [
                {
                    "basename": basename,
                    "release": seal,
                    "release_head_blob": head_blob,
                }
                for basename, seal, head_blob in zip(
                    TRUSTED_EXTERNAL_COMPOSE_LAYER_ORDER,
                    first_release_compose,
                    head_blobs,
                    strict=True,
                )
            ],
            "release_environment_files": [
                path.as_posix() for path in environment_paths
            ],
            "release_environment_root_seal": first_runtime_root,
            "release_environment_file_seals": first_environment,
            "capsule_bytes_used_as_forward_input": False,
            "current_live_projection_exact": True,
            "two_sample_seal_verified": True,
        }

    def _require_forward_recovery_capsule_bridge_unchanged(self) -> None:
        capsule_path = self._forward_recovery_capsule_path
        capsule_seal = self._forward_recovery_capsule_seal
        directory_seal = self._forward_recovery_capsule_directory_seal
        if capsule_path is None:
            return
        if capsule_seal is None or directory_seal is None:
            raise DeployError("forward_recovery_capsule_bridge_state_invalid")
        current_directory = self._deployment_input_directory_seal(capsule_path.parent)
        trusted_directory = {
            key: current_directory[key]
            for key in ("path", "mode", "device", "inode", "uid", "gid")
        }
        if (
            trusted_directory != directory_seal
            or self._deployment_input_file_seal(capsule_path) != capsule_seal
        ):
            raise DeployError("forward_recovery_capsule_changed_before_mutation")

    def _configure_forward_topology(self, previous: Mapping[str, Any]) -> None:
        prior_root = Path(str(previous.get("working_dir") or "")).expanduser()
        if not prior_root.is_absolute() or ".." in prior_root.parts:
            raise DeployError("forward_baseline_working_dir_invalid")
        prior_files = [
            Path(str(item)).expanduser()
            for item in list(previous.get("compose_config_files") or [])
            if str(item).strip()
        ]
        if not prior_files:
            raise DeployError("forward_baseline_compose_files_missing")

        if len(prior_files) == 1 and prior_files[0].name.endswith(
            ROLLBACK_CAPSULE_FILE_SUFFIX
        ):
            bridge = self._validate_recovered_capsule_topology_bridge(
                previous=previous,
                prior_root=prior_root,
                prior_files=prior_files,
            )
            release_files = list(TRUSTED_EXTERNAL_COMPOSE_LAYER_ORDER)
            self.target_compose_files = tuple(release_files)
            self.target_compose_environment_files = tuple(
                str(item) for item in bridge["release_environment_files"]
            )
            self.release_env["EA_DEPLOY_COMPOSE_FILES"] = ",".join(release_files)
            self.receipt["target_compose_files"] = release_files
            self.receipt["forward_topology_source"] = {
                "working_dir": str(prior_root),
                "compose_config_files": [str(path) for path in prior_files],
                "compose_environment_files": [],
                "mapping": (
                    "verified_recovery_capsule_rebased_to_canonical_release_layers"
                ),
                "prior_memorial_layer_replaced": True,
                "prior_normalization_layer_dropped": False,
                "external_layer_basenames": [],
                "verified_recovery_capsule_bridge": bridge,
            }
            self._write_receipt()
            return

        external_layer_names: list[str] = []
        for prior_file in prior_files:
            try:
                prior_file.relative_to(prior_root)
            except ValueError:
                if prior_file.name not in ROLLBACK_CAPSULE_ALLOWED_EXTERNAL_LAYERS:
                    raise DeployError(
                        f"forward_baseline_compose_file_unmappable:{prior_file.name}"
                    )
                external_layer_names.append(prior_file.name)
        if TRUSTED_EXTERNAL_BRIDGE_ONLY_LAYERS.intersection(
            path.name for path in prior_files
        ):
            bridge = self._validate_trusted_external_topology_bridge(
                previous=previous,
                prior_root=prior_root,
                prior_files=prior_files,
            )
            release_files = list(TRUSTED_EXTERNAL_COMPOSE_LAYER_ORDER)
            self.target_compose_files = tuple(release_files)
            self.target_compose_environment_files = tuple(
                str(self.root / EA_RUNTIME_ENV_DIRECTORY / filename)
                for filename in (EA_RUNTIME_ENV_FILE, EA_RUNTIME_LOCAL_ENV_FILE)
            )
            self.release_env["EA_DEPLOY_COMPOSE_FILES"] = ",".join(release_files)
            self.receipt["target_compose_files"] = release_files
            self.receipt["forward_topology_source"] = {
                "working_dir": str(prior_root),
                "compose_config_files": [str(path) for path in prior_files],
                "compose_environment_files": list(
                    self._prior_compose_environment_files
                ),
                "mapping": (
                    "exact_trusted_external_five_layer_topology_rebased_"
                    "in_place_to_release_root"
                ),
                "prior_memorial_layer_replaced": True,
                "prior_normalization_layer_dropped": False,
                "external_layer_basenames": external_layer_names,
                "trusted_external_bridge": bridge,
            }
            self._write_receipt()
            return

        release_files: list[str] = []
        seen: set[str] = set()
        prior_memorial_layer_replaced = False
        prior_normalization_layer_dropped = False
        external_layer_names = []
        for prior_file in prior_files:
            try:
                relative = prior_file.relative_to(prior_root)
                relative_name = relative.as_posix()
            except ValueError:
                relative_name = prior_file.name
                if relative_name not in ROLLBACK_CAPSULE_ALLOWED_EXTERNAL_LAYERS:
                    raise DeployError(
                        f"forward_baseline_compose_file_unmappable:{prior_file.name}"
                    )
                external_layer_names.append(relative_name)
            if relative_name in seen:
                raise DeployError("forward_baseline_compose_file_duplicate")
            seen.add(relative_name)
            if Path(relative_name).name == API_BASELINE_NORMALIZATION_COMPOSE_FILE:
                if relative_name != API_BASELINE_NORMALIZATION_COMPOSE_FILE:
                    raise DeployError("forward_baseline_normalization_path_invalid")
                prior_normalization_layer_dropped = True
                continue
            if Path(relative_name).name == MEMORIAL_COMPOSE_FILE:
                if relative_name != MEMORIAL_COMPOSE_FILE:
                    raise DeployError("forward_baseline_memorial_path_invalid")
                prior_memorial_layer_replaced = True
                continue
            release_file = self.root / Path(relative_name)
            try:
                release_file.relative_to(self.root)
            except ValueError as exc:
                raise DeployError(
                    f"forward_release_compose_file_escapes_root:{release_file}"
                ) from exc
            try:
                self._deployment_input_file_seal(release_file)
            except DeployError as exc:
                raise DeployError(
                    f"forward_release_compose_file_invalid:{release_file.name}"
                ) from exc
            release_files.append(relative_name)

        memorial_path = self.root / MEMORIAL_COMPOSE_FILE
        try:
            self._deployment_input_file_seal(memorial_path)
        except DeployError as exc:
            raise DeployError(
                f"forward_memorial_compose_file_invalid:{memorial_path.name}"
            ) from exc
        release_files.append(MEMORIAL_COMPOSE_FILE)
        self.target_compose_files = tuple(release_files)
        self.release_env["EA_DEPLOY_COMPOSE_FILES"] = ",".join(release_files)
        self.receipt["target_compose_files"] = release_files
        self.receipt["forward_topology_source"] = {
            "working_dir": str(prior_root),
            "compose_config_files": [str(path) for path in prior_files],
            "mapping": (
                "recognized_layers_rebased_to_release_root_"
                "with_current_memorial_layer_without_external_byte_reads"
            ),
            "prior_memorial_layer_replaced": prior_memorial_layer_replaced,
            "prior_normalization_layer_dropped": (prior_normalization_layer_dropped),
            "external_layer_basenames": external_layer_names,
        }
        self._write_receipt()

    def _rollback_compose(
        self, root: Path, files: Sequence[str], *args: str
    ) -> list[str]:
        return [*self._compose_args(root=root, files=files), *args]

    def _rollback_capsule_compose(self, capsule_path: Path, *args: str) -> list[str]:
        if not self.compose_bin:
            raise DeployError("docker_compose_unavailable")
        capsule = capsule_path.expanduser()
        project_directory = self._rollback_capsule_project_directory.expanduser()
        if (
            not capsule.is_absolute()
            or ".." in capsule.parts
            or not project_directory.is_absolute()
            or ".." in project_directory.parts
            or capsule.parent != project_directory
        ):
            raise DeployError("rollback_capsule_path_invalid")
        self._deployment_input_file_seal(capsule)
        return [
            *self.compose_bin,
            "--project-name",
            PROJECT_NAME,
            "--project-directory",
            str(project_directory),
            "-f",
            str(capsule),
            *args,
        ]

    def _build_rollback_capsule(
        self, inspection: Mapping[str, Any]
    ) -> tuple[dict[str, Any], dict[str, object]]:
        config, host = _require_rollback_capsule_supported_inspection(inspection)
        image_id = str(inspection.get("Image") or "")
        if IMAGE_ID_PATTERN.fullmatch(image_id) is None:
            raise DeployError("rollback_capsule_image_id_invalid")
        image_reference = _safe_tagged_image_reference(
            str(config.get("Image") or ""),
            reason="rollback_capsule_image_reference_invalid",
        )
        identity = _container_functional_identity(inspection)
        service: dict[str, Any] = {
            "container_name": API_SERVICE,
            "image": image_reference,
            "pull_policy": "never",
        }

        normalized_environment = _normalized_environment(list(config.get("Env") or []))
        raw_environment_names = [
            str(item).split("=", 1)[0] for item in list(config.get("Env") or [])
        ]
        if len(raw_environment_names) != len(set(raw_environment_names)) or any(
            re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) is None
            for name in raw_environment_names
        ):
            raise DeployError("rollback_capsule_environment_name_invalid_or_duplicate")
        service["environment"] = {
            item.split("=", 1)[0]: item.split("=", 1)[1].replace("$", "$$")
            for item in normalized_environment
        }

        for source_key, compose_key in (
            ("Cmd", "command"),
            ("Entrypoint", "entrypoint"),
        ):
            value = _normalized_command(config.get(source_key))
            if value:
                service[compose_key] = [
                    _rollback_capsule_compose_literal(item) for item in value
                ]
        for source_key, compose_key in (
            ("User", "user"),
            ("WorkingDir", "working_dir"),
            ("Hostname", "hostname"),
            ("StopSignal", "stop_signal"),
        ):
            value = str(config.get(source_key) or "")
            if value:
                if "\x00" in value or "\n" in value or "\r" in value:
                    raise DeployError("rollback_capsule_process_config_invalid")
                service[compose_key] = _rollback_capsule_compose_literal(value)
        stop_timeout = config.get("StopTimeout")
        if not _docker_value_is_neutral(stop_timeout):
            if type(stop_timeout) is not int or int(stop_timeout) < 0:
                raise DeployError("rollback_capsule_stop_timeout_invalid")
            service["stop_grace_period"] = f"{int(stop_timeout)}s"

        raw_healthcheck = config.get("Healthcheck") or {}
        if not isinstance(raw_healthcheck, dict):
            raise DeployError("rollback_capsule_healthcheck_invalid")
        allowed_healthcheck = {
            "Interval",
            "Retries",
            "StartInterval",
            "StartPeriod",
            "Test",
            "Timeout",
        }
        if any(
            key not in allowed_healthcheck and not _docker_value_is_neutral(value)
            for key, value in raw_healthcheck.items()
        ):
            raise DeployError("rollback_capsule_healthcheck_field_unsupported")
        if raw_healthcheck:
            test = raw_healthcheck.get("Test") or []
            if not isinstance(test, list) or not all(
                isinstance(item, str) and "\x00" not in item for item in test
            ):
                raise DeployError("rollback_capsule_healthcheck_invalid")
            healthcheck: dict[str, object] = {
                "test": [_rollback_capsule_compose_literal(item) for item in test]
            }
            for source_key, compose_key in (
                ("Interval", "interval"),
                ("Timeout", "timeout"),
                ("StartPeriod", "start_period"),
                ("StartInterval", "start_interval"),
            ):
                value = raw_healthcheck.get(source_key)
                if not _docker_value_is_neutral(value):
                    if type(value) is not int or int(value) < 0:
                        raise DeployError("rollback_capsule_healthcheck_invalid")
                    healthcheck[compose_key] = f"{int(value)}ns"
            retries = raw_healthcheck.get("Retries")
            if not _docker_value_is_neutral(retries):
                if type(retries) is not int or int(retries) < 0:
                    raise DeployError("rollback_capsule_healthcheck_invalid")
                healthcheck["retries"] = int(retries)
            service["healthcheck"] = healthcheck

        labels = _rollback_capsule_noncompose_labels(config)
        if labels:
            service["labels"] = {
                name: _rollback_capsule_compose_literal(value)
                for name, value in labels.items()
            }

        raw_exposed = config.get("ExposedPorts") or {}
        raw_bindings = host.get("PortBindings") or {}
        if not isinstance(raw_exposed, dict) or not isinstance(raw_bindings, dict):
            raise DeployError("rollback_capsule_ports_invalid")
        port_pattern = re.compile(r"^([1-9][0-9]{0,4})/(tcp|udp|sctp)$")
        ports: list[dict[str, object]] = []
        expose: list[str] = []
        for raw_port in sorted({*raw_exposed, *raw_bindings}):
            match = port_pattern.fullmatch(str(raw_port))
            if match is None or not 1 <= int(match.group(1)) <= 65535:
                raise DeployError("rollback_capsule_ports_invalid")
            if raw_port in raw_exposed and raw_exposed[raw_port] not in ({}, None):
                raise DeployError("rollback_capsule_ports_invalid")
            bindings = raw_bindings.get(raw_port) or []
            if not isinstance(bindings, list):
                raise DeployError("rollback_capsule_ports_invalid")
            if not bindings:
                expose.append(str(raw_port))
                continue
            for raw_binding in bindings:
                if not isinstance(raw_binding, dict):
                    raise DeployError("rollback_capsule_ports_invalid")
                if any(
                    key not in {"HostIp", "HostPort"}
                    and not _docker_value_is_neutral(value)
                    for key, value in raw_binding.items()
                ):
                    raise DeployError("rollback_capsule_ports_invalid")
                host_ip = str(raw_binding.get("HostIp") or "")
                host_port = str(raw_binding.get("HostPort") or "")
                if (
                    not host_port.isdigit()
                    or not 1 <= int(host_port) <= 65535
                    or "\x00" in host_ip
                ):
                    raise DeployError("rollback_capsule_ports_invalid")
                row: dict[str, object] = {
                    "target": int(match.group(1)),
                    "published": host_port,
                    "protocol": match.group(2),
                }
                if host_ip:
                    row["host_ip"] = host_ip
                ports.append(row)
        if ports:
            service["ports"] = ports
        if expose:
            service["expose"] = expose

        restart_policy = host.get("RestartPolicy") or {}
        if not isinstance(restart_policy, dict) or any(
            key not in {"MaximumRetryCount", "Name"}
            and not _docker_value_is_neutral(value)
            for key, value in restart_policy.items()
        ):
            raise DeployError("rollback_capsule_restart_policy_invalid")
        restart_name = str(restart_policy.get("Name") or "")
        retry_count = restart_policy.get("MaximumRetryCount") or 0
        if restart_name:
            if restart_name not in {"always", "no", "on-failure", "unless-stopped"}:
                raise DeployError("rollback_capsule_restart_policy_invalid")
            restart = restart_name
            if restart_name == "on-failure" and retry_count:
                if type(retry_count) is not int or int(retry_count) < 0:
                    raise DeployError("rollback_capsule_restart_policy_invalid")
                restart = f"on-failure:{int(retry_count)}"
            elif retry_count:
                raise DeployError("rollback_capsule_restart_policy_invalid")
            service["restart"] = restart

        for host_key, compose_key in (
            ("Memory", "mem_limit"),
            ("MemoryReservation", "mem_reservation"),
            ("MemorySwap", "memswap_limit"),
            ("CpuShares", "cpu_shares"),
            ("PidsLimit", "pids_limit"),
            ("ShmSize", "shm_size"),
        ):
            value = host.get(host_key)
            if not _docker_value_is_neutral(value):
                if type(value) is not int:
                    raise DeployError("rollback_capsule_resource_invalid")
                if host_key == "MemorySwap":
                    if int(value) < -1 or int(value) == 0:
                        raise DeployError("rollback_capsule_resource_invalid")
                elif int(value) <= 0:
                    raise DeployError("rollback_capsule_resource_invalid")
                service[compose_key] = int(value)
        nano_cpus = host.get("NanoCpus")
        if not _docker_value_is_neutral(nano_cpus):
            if type(nano_cpus) is not int or int(nano_cpus) <= 0:
                raise DeployError("rollback_capsule_resource_invalid")
            whole, remainder = divmod(int(nano_cpus), 1_000_000_000)
            service["cpus"] = f"{whole}.{remainder:09d}".rstrip("0").rstrip(".")

        service["read_only"] = bool(host.get("ReadonlyRootfs"))
        group_add = _rollback_capsule_group_add(host.get("GroupAdd"))
        if group_add:
            service["group_add"] = [
                _rollback_capsule_compose_literal(item) for item in group_add
            ]
        for host_key, compose_key in (
            ("CapDrop", "cap_drop"),
            ("ExtraHosts", "extra_hosts"),
            ("SecurityOpt", "security_opt"),
        ):
            raw_items = host.get(host_key) or []
            if not isinstance(raw_items, list) or not all(
                isinstance(item, str) and item and "\x00" not in item
                for item in raw_items
            ):
                raise DeployError("rollback_capsule_security_config_invalid")
            if raw_items:
                service[compose_key] = [
                    _rollback_capsule_compose_literal(item) for item in raw_items
                ]
        for host_key, compose_key, supported in (
            ("CgroupnsMode", "cgroup", {"private"}),
            ("IpcMode", "ipc", {"private"}),
            ("Runtime", "runtime", {"runc"}),
        ):
            value = str(host.get(host_key) or "")
            if value:
                if value not in supported:
                    raise DeployError(
                        f"rollback_capsule_host_field_unsupported:{host_key}"
                    )
                service[compose_key] = value

        raw_tmpfs = host.get("Tmpfs") or {}
        if not isinstance(raw_tmpfs, dict) or not all(
            isinstance(path, str)
            and path.startswith("/")
            and isinstance(options, str)
            and "\x00" not in path
            and "\x00" not in options
            for path, options in raw_tmpfs.items()
        ):
            raise DeployError("rollback_capsule_tmpfs_invalid")
        if raw_tmpfs:
            service["tmpfs"] = [
                _rollback_capsule_compose_literal(
                    f"{path}:{options}" if options else path
                )
                for path, options in sorted(raw_tmpfs.items())
            ]

        raw_logging = host.get("LogConfig") or {}
        if not isinstance(raw_logging, dict) or any(
            key not in {"Config", "Type"} and not _docker_value_is_neutral(value)
            for key, value in raw_logging.items()
        ):
            raise DeployError("rollback_capsule_logging_invalid")
        log_driver = str(raw_logging.get("Type") or "")
        log_options = raw_logging.get("Config") or {}
        if not isinstance(log_options, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in log_options.items()
        ):
            raise DeployError("rollback_capsule_logging_invalid")
        if log_driver:
            service["logging"] = {
                "driver": log_driver,
                **(
                    {
                        "options": {
                            name: _rollback_capsule_compose_literal(value)
                            for name, value in log_options.items()
                        }
                    }
                    if log_options
                    else {}
                ),
            }

        mounts = _rollback_capsule_mount_identities(inspection)
        raw_binds = host.get("Binds") or []
        if not isinstance(raw_binds, list) or not all(
            isinstance(item, str) and item for item in raw_binds
        ):
            raise DeployError("rollback_capsule_binds_invalid")
        if raw_binds:
            bind_identities: list[tuple[str, str, str, bool]] = []
            for raw_bind in raw_binds:
                parts = raw_bind.split(":")
                if len(parts) not in {2, 3}:
                    raise DeployError("rollback_capsule_binds_invalid")
                source, destination = parts[:2]
                options = set(parts[2].split(",")) if len(parts) == 3 else set()
                if (
                    not source
                    or not destination.startswith("/")
                    or "\x00" in source
                    or "\x00" in destination
                    or any(
                        option not in {"", "ro", "rw", "private", "rprivate"}
                        for option in options
                    )
                ):
                    raise DeployError("rollback_capsule_binds_invalid")
                mount_type = "bind" if source.startswith("/") else "volume"
                if mount_type == "bind" and os.path.normpath(source) != source:
                    raise DeployError("rollback_capsule_binds_invalid")
                normalized_source = source
                bind_identities.append(
                    (
                        mount_type,
                        normalized_source,
                        destination,
                        "ro" not in options,
                    )
                )
            expected_bind_identities = [
                (
                    str(item["type"]),
                    str(item["source"]),
                    str(item["destination"]),
                    bool(item["read_write"]),
                )
                for item in mounts
            ]
            if sorted(bind_identities) != sorted(expected_bind_identities):
                raise DeployError("rollback_capsule_binds_mismatch")
        volumes: dict[str, object] = {}
        service_volumes: list[dict[str, object]] = []
        for index, mount in enumerate(mounts):
            source = str(mount["source"])
            source_key = source
            if mount["type"] == "volume":
                source_key = f"rollback_volume_{index}"
                volumes[source_key] = {"external": True, "name": source}
            row: dict[str, object] = {
                "type": mount["type"],
                "source": _rollback_capsule_compose_literal(source_key),
                "target": _rollback_capsule_compose_literal(str(mount["destination"])),
                "read_only": not bool(mount["read_write"]),
            }
            propagation = str(mount.get("propagation") or "")
            if mount["type"] == "bind" and propagation not in {"", "rprivate"}:
                row["bind"] = {"propagation": propagation}
            service_volumes.append(row)
        if service_volumes:
            service["volumes"] = service_volumes

        network_rows = _rollback_capsule_network_identities(inspection)
        raw_network_mode = str(host.get("NetworkMode") or "")
        network_names = {str(row["name"]) for row in network_rows}
        if raw_network_mode and raw_network_mode not in network_names:
            raise DeployError("rollback_capsule_network_mode_unsupported")
        networks: dict[str, object] = {}
        service_networks: dict[str, object] = {}
        for index, network in enumerate(network_rows):
            key = f"rollback_network_{index}"
            networks[key] = {"external": True, "name": network["name"]}
            aliases = list(network.get("aliases") or [])
            service_network: dict[str, object] = {}
            if aliases:
                service_network["aliases"] = aliases
            if network.get("ipv4_address"):
                service_network["ipv4_address"] = str(network["ipv4_address"])
            service_networks[key] = service_network
        if service_networks:
            service["networks"] = service_networks

        extension = {
            "contract_name": ROLLBACK_CAPSULE_CONTRACT_NAME,
            "version": ROLLBACK_CAPSULE_VERSION,
            "deployment_id": self.deployment_id,
            "service": API_SERVICE,
            "captured_at": _utc_now(),
            "source_container_id_sha256": hashlib.sha256(
                str(inspection.get("Id") or "").encode("utf-8")
            ).hexdigest(),
            "source_image_id": image_id,
            "source_image_reference": image_reference,
            "functional_identity": identity,
            "external_resources": {
                "networks": [
                    {
                        "name": str(item["name"]),
                        "network_id": str(item["network_id"]),
                    }
                    for item in network_rows
                ],
                "volumes": [
                    {
                        "name": str(item["source"]),
                        "driver": str(item["driver"]),
                    }
                    for item in mounts
                    if item["type"] == "volume"
                ],
            },
            "allowed_runtime_differences": list(
                ROLLBACK_CAPSULE_ALLOWED_RUNTIME_DIFFERENCES
            ),
        }
        document: dict[str, Any] = {
            "name": PROJECT_NAME,
            "x-ea-rollback-capsule": extension,
            "services": {API_SERVICE: service},
        }
        if networks:
            document["networks"] = networks
        if volumes:
            document["volumes"] = volumes
        return document, identity

    def _rollback_environment(self, previous: Mapping[str, Any]) -> dict[str, str]:
        environment = {
            key: value
            for key, value in self.env.items()
            if key in ROLLBACK_ENV_PASSTHROUGH and key not in FORWARD_ONLY_ENV_KEYS
        }
        memorial_environment = previous.get("rollback_environment") or {}
        if not isinstance(memorial_environment, dict) or (
            memorial_environment
            and set(memorial_environment) != ROLLBACK_MEMORIAL_RENDER_ENV_KEYS
        ):
            raise DeployError("rollback_memorial_environment_invalid")
        environment.update(
            {str(key): str(value) for key, value in memorial_environment.items()}
        )
        return environment

    @staticmethod
    def _deployment_input_directory_seal(path: Path) -> dict[str, object]:
        candidate = path.expanduser()
        if (
            not candidate.is_absolute()
            or candidate == Path("/")
            or ".." in candidate.parts
            or os.path.normpath(str(candidate)) != str(candidate)
            or not hasattr(os, "O_DIRECTORY")
            or not hasattr(os, "O_NOFOLLOW")
        ):
            raise DeployError("deployment_input_directory_path_invalid")
        flags = os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW
        try:
            descriptor = os.open("/", flags)
        except OSError as exc:  # pragma: no cover - host invariant
            raise DeployError("deployment_input_root_unavailable") from exc
        try:
            for component in candidate.parts[1:]:
                try:
                    path_metadata = os.stat(
                        component,
                        dir_fd=descriptor,
                        follow_symlinks=False,
                    )
                    child = os.open(component, flags, dir_fd=descriptor)
                except OSError as exc:
                    raise DeployError(
                        f"deployment_input_directory_invalid:{candidate.name}"
                    ) from exc
                try:
                    opened_metadata = os.fstat(child)
                    if (
                        not stat.S_ISDIR(path_metadata.st_mode)
                        or stat.S_ISLNK(path_metadata.st_mode)
                        or not stat.S_ISDIR(opened_metadata.st_mode)
                        or _trusted_file_identity(path_metadata)
                        != _trusted_file_identity(opened_metadata)
                    ):
                        raise DeployError(
                            f"deployment_input_directory_invalid:{candidate.name}"
                        )
                except BaseException:
                    os.close(child)
                    raise
                os.close(descriptor)
                descriptor = child
            metadata = os.fstat(descriptor)
            if metadata.st_uid != os.geteuid():
                raise DeployError(
                    f"deployment_input_directory_invalid:{candidate.name}"
                )
            return {
                "path": candidate.as_posix(),
                "mode": format(stat.S_IMODE(metadata.st_mode), "04o"),
                "device": int(metadata.st_dev),
                "inode": int(metadata.st_ino),
                "uid": int(metadata.st_uid),
                "gid": int(metadata.st_gid),
                "link_count": int(metadata.st_nlink),
                "mtime_ns": int(metadata.st_mtime_ns),
                "ctime_ns": int(metadata.st_ctime_ns),
            }
        finally:
            os.close(descriptor)

    @staticmethod
    def _deployment_input_file_seal(path: Path) -> dict[str, object]:
        candidate = path.expanduser()
        if not candidate.is_absolute() or ".." in candidate.parts:
            raise DeployError("deployment_input_path_invalid")
        directory_flags = os.O_RDONLY | os.O_CLOEXEC
        if hasattr(os, "O_DIRECTORY"):
            directory_flags |= os.O_DIRECTORY
        if hasattr(os, "O_NOFOLLOW"):
            directory_flags |= os.O_NOFOLLOW
        file_flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK
        if hasattr(os, "O_NOFOLLOW"):
            file_flags |= os.O_NOFOLLOW

        try:
            directory_descriptor = os.open("/", directory_flags)
        except OSError as exc:  # pragma: no cover - host invariant
            raise DeployError("deployment_input_root_unavailable") from exc
        try:
            for component in candidate.parts[1:-1]:
                try:
                    next_descriptor = os.open(
                        component,
                        directory_flags,
                        dir_fd=directory_descriptor,
                    )
                except OSError as exc:
                    raise DeployError(
                        f"deployment_input_ancestor_invalid:{candidate.name}"
                    ) from exc
                try:
                    metadata = os.fstat(next_descriptor)
                    if not stat.S_ISDIR(metadata.st_mode):
                        raise DeployError(
                            f"deployment_input_ancestor_invalid:{candidate.name}"
                        )
                except BaseException:
                    os.close(next_descriptor)
                    raise
                os.close(directory_descriptor)
                directory_descriptor = next_descriptor

            name = candidate.name
            try:
                path_metadata = os.stat(
                    name,
                    dir_fd=directory_descriptor,
                    follow_symlinks=False,
                )
                file_descriptor = os.open(
                    name,
                    file_flags,
                    dir_fd=directory_descriptor,
                )
            except OSError as exc:
                raise DeployError(
                    f"deployment_input_file_unavailable:{candidate.name}"
                ) from exc
        finally:
            os.close(directory_descriptor)

        try:
            before = os.fstat(file_descriptor)
            if (
                not stat.S_ISREG(before.st_mode)
                or stat.S_ISLNK(path_metadata.st_mode)
                or before.st_nlink != 1
                or before.st_uid != os.geteuid()
                or (before.st_dev, before.st_ino)
                != (path_metadata.st_dev, path_metadata.st_ino)
            ):
                raise DeployError(f"deployment_input_file_invalid:{candidate.name}")
            if before.st_size > MAX_DEPLOYMENT_INPUT_BYTES:
                raise DeployError(f"deployment_input_file_too_large:{candidate.name}")
            identity = (
                before.st_dev,
                before.st_ino,
                before.st_mode,
                before.st_uid,
                before.st_gid,
                before.st_nlink,
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
            )
            digest = hashlib.sha256()
            total = 0
            while True:
                chunk = os.read(file_descriptor, 1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_DEPLOYMENT_INPUT_BYTES:
                    raise DeployError(
                        f"deployment_input_file_too_large:{candidate.name}"
                    )
                digest.update(chunk)
                current = os.fstat(file_descriptor)
                if (
                    current.st_dev,
                    current.st_ino,
                    current.st_mode,
                    current.st_uid,
                    current.st_gid,
                    current.st_nlink,
                    current.st_size,
                    current.st_mtime_ns,
                    current.st_ctime_ns,
                ) != identity:
                    raise DeployError(f"deployment_input_file_changed:{candidate.name}")
            after = os.fstat(file_descriptor)
            after_identity = (
                after.st_dev,
                after.st_ino,
                after.st_mode,
                after.st_uid,
                after.st_gid,
                after.st_nlink,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            )
            if after_identity != identity or total != after.st_size:
                raise DeployError(f"deployment_input_file_changed:{candidate.name}")
            return {
                "path": candidate.as_posix(),
                "sha256": digest.hexdigest(),
                "size_bytes": total,
                "mode": format(stat.S_IMODE(after.st_mode), "04o"),
                "device": int(after.st_dev),
                "inode": int(after.st_ino),
                "uid": int(after.st_uid),
                "gid": int(after.st_gid),
                "link_count": int(after.st_nlink),
                "mtime_ns": int(after.st_mtime_ns),
                "ctime_ns": int(after.st_ctime_ns),
            }
        finally:
            os.close(file_descriptor)

    @classmethod
    def _deployment_input_file_bytes(
        cls, path: Path
    ) -> tuple[bytes, dict[str, object]]:
        candidate = path.expanduser()
        first = cls._deployment_input_file_seal(candidate)
        if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
            raise DeployError("deployment_input_nofollow_unavailable")
        directory_flags = os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW
        file_flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK | os.O_NOFOLLOW
        directory_descriptor = os.open("/", directory_flags)
        file_descriptor = -1
        try:
            for component in candidate.parts[1:-1]:
                child = os.open(component, directory_flags, dir_fd=directory_descriptor)
                metadata = os.fstat(child)
                if not stat.S_ISDIR(metadata.st_mode):
                    os.close(child)
                    raise DeployError(
                        f"deployment_input_ancestor_invalid:{candidate.name}"
                    )
                os.close(directory_descriptor)
                directory_descriptor = child
            file_descriptor = os.open(
                candidate.name,
                file_flags,
                dir_fd=directory_descriptor,
            )
            metadata = os.fstat(file_descriptor)
            if (
                int(first["device"]) != metadata.st_dev
                or int(first["inode"]) != metadata.st_ino
                or int(first["uid"]) != metadata.st_uid
                or int(first["link_count"]) != metadata.st_nlink
                or int(first["size_bytes"]) != metadata.st_size
                or first["mode"] != format(stat.S_IMODE(metadata.st_mode), "04o")
            ):
                raise DeployError(f"deployment_input_file_changed:{candidate.name}")
            payload = bytearray()
            while True:
                chunk = os.read(file_descriptor, 1024 * 1024)
                if not chunk:
                    break
                payload.extend(chunk)
                if len(payload) > MAX_DEPLOYMENT_INPUT_BYTES:
                    raise DeployError(
                        f"deployment_input_file_too_large:{candidate.name}"
                    )
            after = os.fstat(file_descriptor)
            second = cls._deployment_input_file_seal(candidate)
            if (
                first != second
                or after.st_dev != metadata.st_dev
                or after.st_ino != metadata.st_ino
                or after.st_size != len(payload)
                or hashlib.sha256(payload).hexdigest() != first["sha256"]
            ):
                raise DeployError(f"deployment_input_file_changed:{candidate.name}")
            return bytes(payload), first
        except DeployError:
            raise
        except OSError as exc:
            raise DeployError(
                f"deployment_input_file_unavailable:{candidate.name}"
            ) from exc
        finally:
            if file_descriptor >= 0:
                os.close(file_descriptor)
            os.close(directory_descriptor)

    @staticmethod
    def _deployment_input_absence_seal(path: Path) -> dict[str, object]:
        candidate = path.expanduser()
        if not candidate.is_absolute() or ".." in candidate.parts:
            raise DeployError("deployment_input_path_invalid")
        directory_flags = os.O_RDONLY | os.O_CLOEXEC
        if hasattr(os, "O_DIRECTORY"):
            directory_flags |= os.O_DIRECTORY
        if hasattr(os, "O_NOFOLLOW"):
            directory_flags |= os.O_NOFOLLOW
        directory_descriptor = os.open("/", directory_flags)
        try:
            for component in candidate.parts[1:-1]:
                try:
                    next_descriptor = os.open(
                        component,
                        directory_flags,
                        dir_fd=directory_descriptor,
                    )
                except OSError as exc:
                    raise DeployError(
                        f"deployment_input_ancestor_invalid:{candidate.name}"
                    ) from exc
                metadata = os.fstat(next_descriptor)
                if not stat.S_ISDIR(metadata.st_mode):
                    os.close(next_descriptor)
                    raise DeployError(
                        f"deployment_input_ancestor_invalid:{candidate.name}"
                    )
                os.close(directory_descriptor)
                directory_descriptor = next_descriptor
            try:
                os.stat(
                    candidate.name,
                    dir_fd=directory_descriptor,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                return {"path": candidate.as_posix(), "present": False}
            except OSError as exc:
                raise DeployError(
                    f"deployment_input_optional_state_invalid:{candidate.name}"
                ) from exc
            raise DeployError(
                f"deployment_input_optional_presence_race:{candidate.name}"
            )
        finally:
            os.close(directory_descriptor)

    @classmethod
    def _deployment_optional_input_seal(cls, path: Path) -> dict[str, object]:
        try:
            return {"present": True, **cls._deployment_input_file_seal(path)}
        except DeployError as exc:
            if str(exc) != f"deployment_input_file_unavailable:{path.name}":
                raise
        return cls._deployment_input_absence_seal(path)

    def _capture_deployment_input_seal(
        self, previous: Mapping[str, Any]
    ) -> dict[str, list[dict[str, object]]]:
        del previous
        forward_required_paths = [
            self.root / ".env",
            self.root / EA_RUNTIME_ENV_DIRECTORY / EA_RUNTIME_ENV_FILE,
            *(self.root / item for item in self.target_compose_files),
        ]
        forward_optional_paths = [
            self.root / ".env.local",
            self.root / EA_RUNTIME_ENV_DIRECTORY / EA_RUNTIME_LOCAL_ENV_FILE,
        ]
        rollback_required_paths = [self.rollback_capsule_path]

        def capture(paths: Sequence[Path]) -> list[dict[str, object]]:
            return [self._deployment_input_file_seal(path) for path in paths]

        def capture_optional(paths: Sequence[Path]) -> list[dict[str, object]]:
            return [self._deployment_optional_input_seal(path) for path in paths]

        first = {
            "forward": [
                *capture(forward_required_paths),
                *capture_optional(forward_optional_paths),
            ],
            "rollback": [
                *capture(rollback_required_paths),
            ],
        }
        second = {
            "forward": [
                *capture(forward_required_paths),
                *capture_optional(forward_optional_paths),
            ],
            "rollback": [
                *capture(rollback_required_paths),
            ],
        }
        if first != second:
            raise DeployError("deployment_input_seal_unstable")
        return first

    def _require_deployment_input_seal(
        self,
        expected: Mapping[str, Sequence[Mapping[str, object]]],
        *,
        scope: str | None = None,
    ) -> None:
        scopes = (scope,) if scope is not None else ("forward", "rollback")
        for current_scope in scopes:
            if current_scope not in {"forward", "rollback"}:
                raise DeployError("deployment_input_seal_scope_invalid")
            expected_rows = [dict(item) for item in expected.get(current_scope, ())]
            if not expected_rows:
                raise DeployError(f"deployment_input_seal_missing:{current_scope}")
            current_rows = [
                (
                    self._deployment_optional_input_seal(
                        Path(str(item.get("path") or ""))
                    )
                    if "present" in item
                    else self._deployment_input_file_seal(
                        Path(str(item.get("path") or ""))
                    )
                )
                for item in expected_rows
            ]
            if current_rows != expected_rows:
                raise DeployError(f"deployment_input_seal_changed:{current_scope}")

    def _run_json_script(
        self,
        script: str,
        *args: str,
        origin: str,
        expected_source_seal: Mapping[str, str] | None = None,
        env: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        command = [sys.executable, str(self.root / script), *args]
        completed = (
            self._run_release_evidence_command(
                command,
                expected_source_seal=expected_source_seal,
                label=origin,
                env=env,
            )
            if expected_source_seal is not None
            else self._run(command, env=env, check=False)
        )
        if completed.returncode != 0:
            evidence = _fixed_json_script_failure_evidence(
                script=script,
                origin=origin,
                completed=completed,
            )
            self._record_check("fixed_json_script", "fail", **evidence)
            raise DeployError(
                "fixed_json_script_failed:"
                f"{evidence['script']}:{evidence['origin']}:"
                f"{evidence['error_code']}:{evidence['return_code']}"
            )
        return _json_object(completed.stdout, reason=f"script_json_invalid:{script}")

    def _release_evidence_environment(self) -> dict[str, str]:
        environment = {
            key: str(value)
            for key, value in self.release_env.items()
            if key in RELEASE_EVIDENCE_ENV_ALLOWLIST and str(value)
        }
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        environment["PYTHONNOUSERSITE"] = "1"
        return environment

    def _release_evidence_source_seal(self) -> dict[str, str]:
        evidence_env = self._release_evidence_environment()

        def git_value(args: list[str], *, reason: str) -> str:
            completed = self._run(args, env=evidence_env, check=False)
            if completed.returncode != 0:
                raise DeployError(reason)
            value = (completed.stdout or "").strip()
            if not re.fullmatch(r"[0-9a-f]{40,64}", value):
                raise DeployError(reason)
            return value

        head = git_value(
            ["git", "rev-parse", "HEAD"], reason="release_evidence_head_unavailable"
        )
        head_tree = git_value(
            ["git", "rev-parse", "HEAD^{tree}"],
            reason="release_evidence_head_tree_unavailable",
        )
        index_tree = git_value(
            ["git", "write-tree"], reason="release_evidence_index_tree_unavailable"
        )
        index_list_result = self._run(
            ["git", "ls-files", "-v", "-z"],
            env=evidence_env,
            check=False,
        )
        if index_list_result.returncode != 0:
            raise DeployError("release_evidence_index_flags_unavailable")
        raw_index_list = index_list_result.stdout or ""
        if len(raw_index_list.encode("utf-8")) > MAX_GIT_INDEX_LIST_BYTES:
            raise DeployError("release_evidence_index_flags_too_large")
        index_records = [item for item in raw_index_list.split("\0") if item]
        if not index_records or any(
            len(item) < 3 or item[:2] != "H " for item in index_records
        ):
            raise DeployError("release_evidence_nondefault_index_flags")
        status_result = self._run(
            [
                "git",
                "-c",
                "core.fileMode=true",
                "status",
                "--porcelain=v2",
                "-z",
                "--untracked-files=all",
                "--ignore-submodules=none",
            ],
            env=evidence_env,
            check=False,
        )
        if status_result.returncode != 0:
            raise DeployError("release_evidence_source_status_unavailable")
        raw_status = status_result.stdout or ""
        if len(raw_status.encode("utf-8")) > MAX_PRIVATE_RELEASE_EVIDENCE_BYTES:
            raise DeployError("release_evidence_source_status_too_large")
        if raw_status or index_tree != head_tree:
            raise DeployError("release_evidence_source_worktree_dirty")
        bound_revision = str(self.receipt.get("source_revision") or "").strip()
        if bound_revision and head != bound_revision:
            raise DeployError("release_evidence_source_revision_mismatch")
        return {
            "head": head,
            "head_tree": head_tree,
            "index_tree": index_tree,
            "index_flags_sha256": hashlib.sha256(
                raw_index_list.encode("utf-8")
            ).hexdigest(),
            "status_sha256": hashlib.sha256(raw_status.encode("utf-8")).hexdigest(),
        }

    def _require_release_evidence_source_seal(
        self, expected: Mapping[str, str]
    ) -> None:
        try:
            current = self._release_evidence_source_seal()
        except DeployError as exc:
            raise DeployError("release_evidence_mutated_tracked_worktree") from exc
        if current != dict(expected):
            raise DeployError("release_evidence_mutated_tracked_worktree")

    def _run_release_evidence_command(
        self,
        args: Sequence[str],
        *,
        expected_source_seal: Mapping[str, str],
        label: str,
        env: Mapping[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        if not SAFE_SCRIPT_ORIGIN_PATTERN.fullmatch(label):
            raise DeployError("release_evidence_command_label_invalid")
        self._require_release_evidence_source_seal(expected_source_seal)
        command_error: BaseException | None = None
        completed: subprocess.CompletedProcess[str] | None = None
        try:
            completed = self._run(
                args,
                env=(env or self._release_evidence_environment()),
                check=False,
            )
        except BaseException as exc:  # preserve interrupts after the source audit
            command_error = exc
        try:
            self._require_release_evidence_source_seal(expected_source_seal)
        except DeployError as seal_error:
            if command_error is not None:
                raise DeployError(
                    f"release_evidence_command_failed_source_seal_changed:{label}"
                ) from command_error
            raise seal_error
        if command_error is not None:
            raise command_error
        if completed is None:  # pragma: no cover - defensive type narrowing
            raise DeployError(f"release_evidence_command_missing_result:{label}")
        return completed

    def _run_release_evidence_materializer(
        self,
        script: str,
        *args: str,
        expected_source_seal: Mapping[str, str],
        label: str,
        env: Mapping[str, str] | None = None,
    ) -> None:
        completed = self._run_release_evidence_command(
            [sys.executable, str(self.root / script), *args],
            expected_source_seal=expected_source_seal,
            label=label,
            env=env,
        )
        if completed.returncode != 0:
            raise DeployError(
                f"release_evidence_materializer_failed:{label}:{completed.returncode}"
            )

    def _private_evidence_directory(self, phase: str) -> Path:
        if phase not in {"predeploy", "postdeploy"}:
            raise DeployError("release_evidence_phase_invalid")
        try:
            relative_receipt_dir = self.receipt_dir.relative_to(self.root)
        except ValueError:
            relative_receipt_dir = None
        if relative_receipt_dir is not None and (
            not relative_receipt_dir.parts
            or relative_receipt_dir.parts[0] != ".runtime"
        ):
            raise DeployError("release_evidence_receipt_directory_not_private")
        try:
            receipt_metadata = self.receipt_dir.lstat()
        except OSError as exc:
            raise DeployError("release_evidence_receipt_directory_missing") from exc
        if (
            not stat.S_ISDIR(receipt_metadata.st_mode)
            or stat.S_ISLNK(receipt_metadata.st_mode)
            or receipt_metadata.st_uid != os.geteuid()
            or stat.S_IMODE(receipt_metadata.st_mode) != 0o700
        ):
            raise DeployError("release_evidence_receipt_directory_invalid")
        evidence_root = self.receipt_dir / f"{self.deployment_id}.evidence"
        if phase == "predeploy":
            if os.path.lexists(evidence_root):
                raise DeployError("release_evidence_directory_already_exists")
            evidence_root.mkdir(mode=0o700)
        else:
            try:
                root_metadata = evidence_root.lstat()
            except OSError as exc:
                raise DeployError("release_evidence_directory_missing") from exc
            if (
                not stat.S_ISDIR(root_metadata.st_mode)
                or stat.S_ISLNK(root_metadata.st_mode)
                or root_metadata.st_uid != os.geteuid()
            ):
                raise DeployError("release_evidence_directory_invalid")
        try:
            evidence_root.chmod(0o700)
        except OSError as exc:
            raise DeployError("release_evidence_directory_permissions_invalid") from exc
        root_metadata = evidence_root.lstat()
        if (
            not stat.S_ISDIR(root_metadata.st_mode)
            or stat.S_ISLNK(root_metadata.st_mode)
            or root_metadata.st_uid != os.geteuid()
            or stat.S_IMODE(root_metadata.st_mode) != 0o700
        ):
            raise DeployError("release_evidence_directory_invalid")

        phase_directory = evidence_root / phase
        if os.path.lexists(phase_directory):
            raise DeployError("release_evidence_phase_directory_already_exists")
        phase_directory.mkdir(mode=0o700)
        phase_directory.chmod(0o700)
        phase_metadata = phase_directory.lstat()
        if (
            not stat.S_ISDIR(phase_metadata.st_mode)
            or stat.S_ISLNK(phase_metadata.st_mode)
            or phase_metadata.st_uid != os.geteuid()
            or stat.S_IMODE(phase_metadata.st_mode) != 0o700
        ):
            raise DeployError("release_evidence_phase_directory_invalid")
        return phase_directory

    @staticmethod
    def _private_evidence_metadata(path: Path) -> dict[str, object]:
        flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(path, flags)
        except OSError as exc:
            raise DeployError(f"release_evidence_file_unavailable:{path.name}") from exc
        try:
            before = os.fstat(descriptor)
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_nlink != 1
                or before.st_uid != os.geteuid()
            ):
                raise DeployError(f"release_evidence_file_invalid:{path.name}")
            if before.st_size > MAX_PRIVATE_RELEASE_EVIDENCE_BYTES:
                raise DeployError(f"release_evidence_file_too_large:{path.name}")
            os.fchmod(descriptor, 0o600)
            os.fsync(descriptor)
            before = os.fstat(descriptor)
            identity = (
                before.st_dev,
                before.st_ino,
                before.st_mode,
                before.st_size,
                before.st_nlink,
                before.st_mtime_ns,
                before.st_ctime_ns,
            )
            digest = hashlib.sha256()
            total = 0
            while True:
                chunk = os.read(descriptor, 1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_PRIVATE_RELEASE_EVIDENCE_BYTES:
                    raise DeployError(f"release_evidence_file_too_large:{path.name}")
                digest.update(chunk)
            after = os.fstat(descriptor)
            after_identity = (
                after.st_dev,
                after.st_ino,
                after.st_mode,
                after.st_size,
                after.st_nlink,
                after.st_mtime_ns,
                after.st_ctime_ns,
            )
            if identity != after_identity or total != after.st_size:
                raise DeployError(f"release_evidence_file_changed:{path.name}")
            return {
                "sha256": digest.hexdigest(),
                "size_bytes": total,
                "mode": "0600",
            }
        finally:
            os.close(descriptor)

    @staticmethod
    def _write_private_evidence_json(path: Path, payload: Mapping[str, object]) -> None:
        encoded = (
            json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
        ).encode("utf-8")
        if len(encoded) > MAX_PRIVATE_RELEASE_EVIDENCE_BYTES:
            raise DeployError("release_evidence_phase_manifest_too_large")
        temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(temporary, flags, 0o600)
        except OSError as exc:
            raise DeployError("release_evidence_phase_manifest_unavailable") from exc
        try:
            view = memoryview(encoded)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise DeployError("release_evidence_phase_manifest_write_failed")
                view = view[written:]
            os.fchmod(descriptor, 0o600)
            os.fsync(descriptor)
        except BaseException:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise
        finally:
            os.close(descriptor)
        if os.path.lexists(path):
            temporary.unlink(missing_ok=True)
            raise DeployError("release_evidence_phase_manifest_already_exists")
        os.replace(temporary, path)
        directory_flags = os.O_RDONLY | os.O_CLOEXEC
        if hasattr(os, "O_DIRECTORY"):
            directory_flags |= os.O_DIRECTORY
        directory_descriptor = os.open(path.parent, directory_flags)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)

    def _materialize_and_verify_release_evidence(
        self,
        *,
        phase: str = "predeploy",
        deployment_input_seal: Mapping[str, Sequence[Mapping[str, object]]],
        expected_public_origin: str | None = None,
        expected_authority_posture: str | None = None,
    ) -> dict[str, Any]:
        source_seal = self._release_evidence_source_seal()
        authority: dict[str, Any] = {}
        readiness: dict[str, Any] = {}
        phase_error: BaseException | None = None
        try:
            self._require_deployment_input_seal(deployment_input_seal)
            evidence_directory = self._private_evidence_directory(phase)
            paths = {
                "deploy_context": evidence_directory / "deploy-context.json",
                "release_manifest": evidence_directory / "release-manifest.json",
                "release_authority_status": evidence_directory
                / "release-authority-status.json",
                "memorial_operator_status": evidence_directory
                / "memorial-operator-status.json",
                "phase_manifest": evidence_directory / "phase-manifest.json",
            }
            evidence_files: dict[str, dict[str, object]] = {}
            evidence_env = self._release_evidence_environment()

            self._run_release_evidence_materializer(
                "scripts/materialize_deploy_context.py",
                "--output",
                str(paths["deploy_context"]),
                expected_source_seal=source_seal,
                label=f"{phase}_deploy_context",
                env=evidence_env,
            )
            evidence_files["deploy_context"] = self._private_evidence_metadata(
                paths["deploy_context"]
            )
            self._require_deployment_input_seal(deployment_input_seal)

            manifest_env = dict(evidence_env)
            manifest_env["EA_DEPLOY_CONTEXT_PATH"] = str(paths["deploy_context"])
            self._run_release_evidence_materializer(
                "scripts/materialize_release_manifest.py",
                "--output",
                str(paths["release_manifest"]),
                expected_source_seal=source_seal,
                label=f"{phase}_release_manifest",
                env=manifest_env,
            )
            evidence_files["release_manifest"] = self._private_evidence_metadata(
                paths["release_manifest"]
            )
            self._require_deployment_input_seal(deployment_input_seal)

            self._run_release_evidence_materializer(
                "scripts/materialize_release_authority_status.py",
                "--output",
                str(paths["release_authority_status"]),
                "--release-manifest",
                str(paths["release_manifest"]),
                "--deploy-context",
                str(paths["deploy_context"]),
                expected_source_seal=source_seal,
                label=f"{phase}_authority_status",
                env=evidence_env,
            )
            evidence_files["release_authority_status"] = (
                self._private_evidence_metadata(paths["release_authority_status"])
            )
            self._require_deployment_input_seal(deployment_input_seal)

            self._run_release_evidence_materializer(
                "scripts/materialize_memorial_operator_status.py",
                "--output",
                str(paths["memorial_operator_status"]),
                "--deploy-context",
                str(paths["deploy_context"]),
                "--release-manifest",
                str(paths["release_manifest"]),
                "--release-authority-status",
                str(paths["release_authority_status"]),
                expected_source_seal=source_seal,
                label=f"{phase}_operator_status",
                env=evidence_env,
            )
            evidence_files["memorial_operator_status"] = (
                self._private_evidence_metadata(paths["memorial_operator_status"])
            )
            self._require_deployment_input_seal(deployment_input_seal)

            authority = self._run_json_script(
                "scripts/verify_release_authority.py",
                "--release-manifest",
                str(paths["release_manifest"]),
                "--pretty",
                origin=f"{phase}_release_authority",
                expected_source_seal=source_seal,
                env=evidence_env,
            )
            self._require_deployment_input_seal(deployment_input_seal)
            readiness = self._run_json_script(
                "scripts/verify_memorial_deploy_readiness.py",
                "--memorial-status",
                str(paths["memorial_operator_status"]),
                "--release-authority-status",
                str(paths["release_authority_status"]),
                "--pretty",
                origin=f"{phase}_memorial_readiness",
                expected_source_seal=source_seal,
                env=evidence_env,
            )
            self._require_deployment_input_seal(deployment_input_seal)

            if (
                str(authority.get("contract_name") or "")
                != "ea.release_authority_gate.v1"
            ):
                raise DeployError("release_authority_contract_invalid")
            if str(authority.get("status") or "").lower() != "pass":
                raise DeployError("release_authority_not_pass")
            if bool(authority.get("source_worktree_dirty")):
                raise DeployError("release_authority_source_worktree_dirty")
            if str(authority.get("deployment_id") or "") != self.deployment_id:
                raise DeployError("release_authority_deployment_id_mismatch")
            if str(authority.get("commit_sha") or "") != source_seal["head"]:
                raise DeployError("release_authority_commit_mismatch")
            if str(authority.get("project_mode") or "").upper() != "MEMORIAL":
                raise DeployError("release_authority_project_mode_mismatch")
            authority_public_origin = _validate_public_origin(
                str(authority.get("public_origin") or ""),
                allowed_hosts=self.allowed_public_hosts,
            )
            if (
                expected_public_origin is not None
                and authority_public_origin != expected_public_origin
            ):
                raise DeployError("release_authority_public_origin_mismatch")
            authority_posture = str(authority.get("authority_posture") or "").strip()
            if not authority_posture:
                raise DeployError("release_authority_posture_missing")
            if (
                expected_authority_posture is not None
                and authority_posture != expected_authority_posture
            ):
                raise DeployError("release_authority_posture_mismatch")
            if (
                str(readiness.get("contract_name") or "")
                != "ea.memorial_deploy_readiness.v1"
            ):
                raise DeployError("memorial_deploy_readiness_contract_invalid")
            if str(readiness.get("status") or "").lower() != "pass":
                raise DeployError("memorial_deploy_readiness_not_pass")

            for name, path in paths.items():
                if name == "phase_manifest":
                    continue
                if self._private_evidence_metadata(path) != evidence_files[name]:
                    raise DeployError(f"release_evidence_file_rehashed_mismatch:{name}")

            relative_directory = Path(f"{self.deployment_id}.evidence") / phase
            receipt_files = {
                name: {
                    "path": (relative_directory / paths[name].name).as_posix(),
                    **metadata,
                }
                for name, metadata in evidence_files.items()
            }
            authority_projection = {
                "contract_name": str(authority.get("contract_name") or ""),
                "status": str(authority.get("status") or ""),
                "authority_posture": str(authority.get("authority_posture") or ""),
                "deployment_id": str(authority.get("deployment_id") or ""),
                "commit_sha": str(authority.get("commit_sha") or ""),
                "project_mode": str(authority.get("project_mode") or ""),
                "public_origin": str(authority.get("public_origin") or ""),
                "source_worktree_dirty": bool(authority.get("source_worktree_dirty")),
            }
            readiness_projection = {
                "contract_name": str(readiness.get("contract_name") or ""),
                "status": str(readiness.get("status") or ""),
                "issues": [
                    str(item)
                    for item in list(readiness.get("issues") or [])
                    if str(item)
                ],
            }
            candidate_image = dict(self.receipt.get("candidate_image") or {})
            candidate_promotion = dict(
                self.receipt.get("candidate_promotion_evidence") or {}
            )
            projection = dict(candidate_promotion.get("projection") or {})
            phase_payload: dict[str, object] = {
                "contract_name": "ea.memorial_release_evidence_phase.v1",
                "generated_at": _utc_now(),
                "phase": phase,
                "deployment_id": self.deployment_id,
                "source_revision": source_seal["head"],
                "source_tree": source_seal["head_tree"],
                "index_tree": source_seal["index_tree"],
                "source_index_flags_sha256": source_seal["index_flags_sha256"],
                "source_status_sha256": source_seal["status_sha256"],
                "deployment_input_seal": {
                    key: [dict(item) for item in value]
                    for key, value in deployment_input_seal.items()
                },
                "candidate_image": {
                    "reference": str(candidate_image.get("reference") or ""),
                    "image_id": str(candidate_image.get("image_id") or ""),
                },
                "projection_sha256": str(projection.get("projection_sha256") or ""),
                "evidence_files": receipt_files,
                "authority": authority_projection,
                "readiness": readiness_projection,
            }
            self._write_private_evidence_json(paths["phase_manifest"], phase_payload)
            phase_metadata = self._private_evidence_metadata(paths["phase_manifest"])
            receipt_files["phase_manifest"] = {
                "path": (relative_directory / paths["phase_manifest"].name).as_posix(),
                **phase_metadata,
            }
            self._require_release_evidence_source_seal(source_seal)
            self._require_deployment_input_seal(deployment_input_seal)

            release_evidence = dict(self.receipt.get("release_evidence") or {})
            deployment_input_sha256 = hashlib.sha256(
                json.dumps(
                    deployment_input_seal,
                    ensure_ascii=True,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest()
            release_evidence[phase] = {
                "directory": relative_directory.as_posix(),
                "directory_mode": "0700",
                "source_seal": source_seal,
                "deployment_input_sha256": deployment_input_sha256,
                "files": receipt_files,
                "authority": authority_projection,
                "readiness": readiness_projection,
            }
            self.receipt["release_evidence"] = release_evidence
            self._write_receipt()
            self._record_check(f"release_authority_{phase}", "pass")
            self._record_check(f"memorial_deploy_readiness_{phase}", "pass")
        except BaseException as exc:
            phase_error = exc

        final_seal_error: DeployError | None = None
        try:
            self._require_release_evidence_source_seal(source_seal)
            self._require_deployment_input_seal(deployment_input_seal)
        except DeployError as exc:
            final_seal_error = exc
        if phase_error is not None:
            if final_seal_error is not None:
                if isinstance(phase_error, DeployError) and (
                    str(phase_error) == "release_evidence_mutated_tracked_worktree"
                    or str(phase_error).startswith("deployment_input_seal_changed:")
                ):
                    raise phase_error
                raise DeployError(
                    f"release_evidence_phase_failed_integrity_changed:{phase}"
                ) from phase_error
            raise phase_error
        if final_seal_error is not None:
            raise final_seal_error
        return authority

    def _bind_source_access(
        self,
        rendered: Mapping[str, object],
        *,
        expected_snapshot_sha256: str = "",
    ) -> dict[str, object]:
        try:
            return self.bind_source_validator(
                rendered,
                service=API_SERVICE,
                release_root=self._configured_memorial_data_root(),
                expected_snapshot_sha256=expected_snapshot_sha256,
            )
        except BindSourceGuardError as exc:
            raise DeployError(f"memorial_bind_source_access_denied:{exc}") from exc

    def _revalidate_bind_source_access(self, *, boundary: str) -> None:
        if not self.bind_source_snapshot_sha256:
            raise DeployError("memorial_bind_source_snapshot_missing")
        rendered = _json_object(
            self._run(self._target_compose("config", "--format", "json")).stdout,
            reason="memorial_compose_rendered_json_invalid",
        )
        evidence = self._bind_source_access(
            rendered,
            expected_snapshot_sha256=self.bind_source_snapshot_sha256,
        )
        self._record_check(
            "memorial_bind_source_revalidation",
            "pass",
            boundary=boundary,
            bind_mount_count=int(evidence["bind_mount_count"]),
            snapshot_sha256=str(evidence["snapshot_sha256"]),
        )

    def _validate_compose(
        self, *, candidate: Mapping[str, Any]
    ) -> list[dict[str, object]]:
        self._run(self._target_compose("config", "--quiet"))
        rendered = _json_object(
            self._run(self._target_compose("config", "--format", "json")).stdout,
            reason="memorial_compose_rendered_json_invalid",
        )
        services_payload = rendered.get("services")
        services_config = (
            dict(services_payload) if isinstance(services_payload, dict) else {}
        )
        api_payload = services_config.get(API_SERVICE)
        api_config = dict(api_payload) if isinstance(api_payload, dict) else {}
        if str(api_config.get("image") or "") != str(candidate.get("reference") or ""):
            raise DeployError("memorial_compose_candidate_image_mismatch")
        if str(api_config.get("pull_policy") or "").lower() != "never":
            raise DeployError("memorial_compose_pull_policy_invalid")
        if str(api_config.get("user") or "").strip() != "10001:10001":
            raise DeployError("memorial_compose_runtime_user_invalid")
        if api_config.get("group_add") not in (None, []):
            raise DeployError("memorial_compose_supplemental_groups_forbidden")
        target_mounts = self._rendered_mount_identities(
            rendered, api_config, root=self.root
        )
        data_root = self._configured_memorial_data_root()
        runtime_root = self._configured_memorial_runtime_root()
        expected_bind_mounts = {
            "/data/memorial_data": {
                "type": "bind",
                "source": str(data_root),
                "destination": "/data/memorial_data",
                "read_write": False,
            },
            "/data/memorial-writable/public-contributions": {
                "type": "bind",
                "source": str(runtime_root / "public-contributions"),
                "destination": "/data/memorial-writable/public-contributions",
                "read_write": True,
            },
            "/data/memorial-writable/private-contributions": {
                "type": "bind",
                "source": str(runtime_root / "private-contributions"),
                "destination": "/data/memorial-writable/private-contributions",
                "read_write": True,
            },
            "/data/memorial-writable/state": {
                "type": "bind",
                "source": str(runtime_root / "state"),
                "destination": "/data/memorial-writable/state",
                "read_write": True,
            },
        }
        mounts_by_destination = {
            str(item.get("destination") or ""): dict(item) for item in target_mounts
        }
        if len(mounts_by_destination) != len(target_mounts):
            raise DeployError("memorial_compose_mount_destination_duplicate")
        if set(mounts_by_destination) != {
            *expected_bind_mounts,
            "/data/artifacts",
        }:
            raise DeployError("memorial_compose_mount_scope_invalid")
        for destination, expected in expected_bind_mounts.items():
            if mounts_by_destination.get(destination) != expected:
                raise DeployError("memorial_compose_data_mount_mismatch")
        artifacts_mount = mounts_by_destination["/data/artifacts"]
        if (
            artifacts_mount.get("type") != "volume"
            or not str(artifacts_mount.get("source") or "")
            or artifacts_mount.get("read_write") is not True
        ):
            raise DeployError("memorial_compose_artifacts_mount_invalid")
        bind_source_access = self._bind_source_access(rendered)
        self.bind_source_snapshot_sha256 = str(bind_source_access["snapshot_sha256"])
        self.receipt["bind_source_access"] = bind_source_access
        services = self._run(
            self._target_compose("config", "--services")
        ).stdout.splitlines()
        normalized = {item.strip() for item in services if item.strip()}
        if not {API_SERVICE, REDIS_SERVICE} <= normalized:
            raise DeployError("memorial_compose_services_missing")
        self._record_check(
            "compose_config",
            "pass",
            services=[API_SERVICE, REDIS_SERVICE],
            candidate_image=str(candidate.get("reference") or ""),
            pull_policy="never",
            mount_identity_count=len(target_mounts),
            mount_identity_sha256=_identity_digest(target_mounts),
            bind_source_snapshot_sha256=self.bind_source_snapshot_sha256,
        )
        return target_mounts

    def _inspect_container_optional(self, name: str) -> dict[str, Any] | None:
        completed = self._run(["docker", "inspect", name], check=False)
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            normalized = detail.casefold()
            if "no such object" in normalized or "no such container" in normalized:
                return None
            raise DeployError(f"container_inspect_failed:{name}")
        try:
            payload = json.loads(completed.stdout)
        except Exception as exc:
            raise DeployError(f"container_inspect_invalid:{name}") from exc
        if (
            not isinstance(payload, list)
            or len(payload) != 1
            or not isinstance(payload[0], dict)
        ):
            raise DeployError(f"container_inspect_invalid:{name}")
        return dict(payload[0])

    def _inspect_container(self, name: str) -> dict[str, Any]:
        inspection = self._inspect_container_optional(name)
        if inspection is None:
            raise DeployError(f"container_missing:{name}")
        return inspection

    @staticmethod
    def _require_compose_identity(
        inspection: Mapping[str, Any], *, service: str, reason_prefix: str
    ) -> None:
        labels = dict(dict(inspection.get("Config") or {}).get("Labels") or {})
        if labels.get("com.docker.compose.project") != PROJECT_NAME:
            raise DeployError(f"{reason_prefix}_project_mismatch")
        if labels.get("com.docker.compose.service") != service:
            raise DeployError(f"{reason_prefix}_service_mismatch")

    @staticmethod
    def _compose_topology(
        inspection: Mapping[str, Any], *, reason_prefix: str, trust_inputs: bool = True
    ) -> dict[str, Any]:
        labels = dict(dict(inspection.get("Config") or {}).get("Labels") or {})
        raw_working_dir = str(
            labels.get("com.docker.compose.project.working_dir") or ""
        ).strip()
        if not raw_working_dir:
            raise DeployError(f"{reason_prefix}_compose_working_dir_missing")
        working_dir = Path(raw_working_dir).expanduser()
        if not working_dir.is_absolute() or ".." in working_dir.parts:
            raise DeployError(f"{reason_prefix}_working_dir_invalid")
        raw_config_files = str(
            labels.get("com.docker.compose.project.config_files") or ""
        ).strip()
        if not raw_config_files:
            raise DeployError(f"{reason_prefix}_compose_config_files_missing")
        compose_files: list[str] = []
        for raw_path in raw_config_files.split(","):
            normalized_path = raw_path.strip()
            if not normalized_path:
                raise DeployError(f"{reason_prefix}_rollback_input_missing")
            candidate = Path(normalized_path).expanduser()
            if not candidate.is_absolute():
                candidate = working_dir / candidate
            if not candidate.is_absolute() or ".." in candidate.parts:
                raise DeployError(f"{reason_prefix}_rollback_input_invalid")
            if trust_inputs:
                try:
                    MemorialDeployLane._deployment_input_file_seal(candidate)
                except DeployError as exc:
                    raise DeployError(
                        f"{reason_prefix}_rollback_input_invalid"
                    ) from exc
            compose_files.append(str(candidate))
        if not compose_files:
            raise DeployError(f"{reason_prefix}_compose_config_files_missing")
        return {
            "working_dir": str(working_dir),
            "compose_config_files": compose_files,
        }

    def _inspect_image(self, reference: str) -> dict[str, Any]:
        completed = self._run(["docker", "image", "inspect", reference])
        try:
            payload = json.loads(completed.stdout)
        except Exception as exc:
            raise DeployError("memorial_image_inspect_invalid") from exc
        if (
            not isinstance(payload, list)
            or len(payload) != 1
            or not isinstance(payload[0], dict)
        ):
            raise DeployError("memorial_image_inspect_invalid")
        image_id = str(payload[0].get("Id") or "").strip()
        if not IMAGE_ID_PATTERN.fullmatch(image_id):
            raise DeployError("memorial_image_id_invalid")
        return {"reference": reference, "image_id": image_id}

    def _inspect_image_config(self, reference: str) -> dict[str, Any]:
        completed = self._run(["docker", "image", "inspect", reference])
        try:
            payload = json.loads(completed.stdout)
        except Exception as exc:
            raise DeployError("rollback_image_config_inspect_invalid") from exc
        if (
            not isinstance(payload, list)
            or len(payload) != 1
            or not isinstance(payload[0], dict)
        ):
            raise DeployError("rollback_image_config_inspect_invalid")
        image_id = str(payload[0].get("Id") or "").strip()
        config = payload[0].get("Config")
        if not IMAGE_ID_PATTERN.fullmatch(image_id) or not isinstance(config, dict):
            raise DeployError("rollback_image_config_inspect_invalid")
        return {"image_id": image_id, "config": dict(config)}

    @staticmethod
    def _rendered_environment_entries(
        service: Mapping[str, Any], image_config: Mapping[str, Any]
    ) -> list[str]:
        defaults = _normalized_environment(list(image_config.get("Env") or []))
        merged = {item.split("=", 1)[0]: item.split("=", 1)[1] for item in defaults}
        environment = service.get("environment")
        if environment is None:
            return [f"{name}={merged[name]}" for name in sorted(merged)]
        if isinstance(environment, list):
            overrides = _normalized_environment(environment)
            for item in overrides:
                name, value = item.split("=", 1)
                merged[name] = value
        elif isinstance(environment, dict):
            for raw_name, raw_value in environment.items():
                name = str(raw_name or "")
                if not name or "\x00" in name:
                    raise DeployError("rollback_render_environment_invalid")
                if raw_value is None:
                    merged.pop(name, None)
                elif isinstance(raw_value, str) and "\x00" not in raw_value:
                    merged[name] = raw_value
                else:
                    raise DeployError("rollback_render_environment_invalid")
        else:
            raise DeployError("rollback_render_environment_invalid")
        return [f"{name}={merged[name]}" for name in sorted(merged)]

    @staticmethod
    def _rendered_process_config(
        service: Mapping[str, Any], image_config: Mapping[str, Any]
    ) -> dict[str, Any]:
        command_from_compose = (
            "command" in service and service.get("command") is not None
        )
        command = (
            service.get("command") if command_from_compose else image_config.get("Cmd")
        )
        entrypoint_from_compose = (
            "entrypoint" in service and service.get("entrypoint") is not None
        )
        entrypoint = (
            service.get("entrypoint")
            if entrypoint_from_compose
            else image_config.get("Entrypoint")
        )
        user = (
            service.get("user")
            if "user" in service and service.get("user") is not None
            else image_config.get("User")
        )
        return {
            "Cmd": (
                _compose_runtime_command(command)
                if command_from_compose
                else _normalized_command(command)
            ),
            "Entrypoint": (
                _compose_runtime_command(entrypoint)
                if entrypoint_from_compose
                else _normalized_command(entrypoint)
            ),
            "User": str(user or ""),
        }

    @staticmethod
    def _rendered_mount_identities(
        rendered: Mapping[str, Any], service: Mapping[str, Any], *, root: Path
    ) -> list[dict[str, object]]:
        raw_mounts = service.get("volumes") or []
        if not isinstance(raw_mounts, list):
            raise DeployError("rollback_render_mounts_invalid")
        top_level_value = rendered.get("volumes")
        top_level = dict(top_level_value) if isinstance(top_level_value, dict) else {}
        identities: list[dict[str, object]] = []
        for raw_mount in raw_mounts:
            if not isinstance(raw_mount, dict):
                raise DeployError("rollback_render_mounts_invalid")
            mount_type = str(raw_mount.get("type") or "")
            destination = str(raw_mount.get("target") or "")
            source = str(raw_mount.get("source") or "")
            if mount_type == "bind":
                source_path = Path(source).expanduser()
                if not source_path.is_absolute():
                    source_path = root / source_path
                source = str(source_path.resolve())
            elif mount_type == "volume":
                if not source:
                    raise DeployError("rollback_render_mount_unverifiable")
                volume_value = top_level.get(source)
                volume = dict(volume_value) if isinstance(volume_value, dict) else {}
                source = str(volume.get("name") or f"{PROJECT_NAME}_{source}")
            else:
                raise DeployError("rollback_render_mount_unverifiable")
            if not destination or not source:
                raise DeployError("rollback_render_mounts_invalid")
            identities.append(
                {
                    "type": mount_type,
                    "source": source,
                    "destination": destination,
                    "read_write": not bool(raw_mount.get("read_only")),
                }
            )
        return sorted(
            identities,
            key=lambda item: (
                str(item["destination"]),
                str(item["type"]),
                str(item["source"]),
                bool(item["read_write"]),
            ),
        )

    @staticmethod
    def _validated_functional_identity(
        value: object, *, reason_prefix: str
    ) -> dict[str, Any]:
        identity = dict(value) if isinstance(value, dict) else {}
        domains_value = identity.get("domains")
        domains = dict(domains_value) if isinstance(domains_value, dict) else {}
        expected_domains = {
            "environment",
            "healthcheck",
            "host_config",
            "image",
            "mounts",
            "networks",
            "noncompose_labels",
            "ports",
            "process",
            "stop_config",
        }
        if (
            set(identity)
            != {
                "contract_name",
                "version",
                "domains",
                "functional_identity_sha256",
            }
            or identity.get("contract_name") != "ea.memorial_api_functional_identity.v2"
            or identity.get("version") != 2
            or set(domains) != expected_domains
            or SHA256_HEX_PATTERN.fullmatch(
                str(identity.get("functional_identity_sha256") or "")
            )
            is None
            or identity.get("functional_identity_sha256")
            != _canonical_json_sha256(domains)
        ):
            raise DeployError(f"{reason_prefix}_functional_identity_invalid")
        for name, raw_domain in domains.items():
            if not isinstance(raw_domain, dict):
                raise DeployError(f"{reason_prefix}_functional_identity_invalid")
            domain = dict(raw_domain)
            if name == "image":
                if (
                    set(domain) != {"image_id", "image_reference"}
                    or IMAGE_ID_PATTERN.fullmatch(str(domain.get("image_id") or ""))
                    is None
                ):
                    raise DeployError(f"{reason_prefix}_functional_identity_invalid")
                _safe_tagged_image_reference(
                    str(domain.get("image_reference") or ""),
                    reason=f"{reason_prefix}_functional_identity_invalid",
                )
                continue
            allowed = {"sha256"}
            if name in {
                "environment",
                "mounts",
                "networks",
                "noncompose_labels",
                "ports",
            }:
                allowed.add("count")
            if (
                set(domain) != allowed
                or SHA256_HEX_PATTERN.fullmatch(str(domain.get("sha256") or "")) is None
                or (
                    "count" in allowed
                    and (
                        type(domain.get("count")) is not int or int(domain["count"]) < 0
                    )
                )
            ):
                raise DeployError(f"{reason_prefix}_functional_identity_invalid")
        return identity

    @staticmethod
    def _rollback_capsule_external_bindings(
        document: Mapping[str, Any], *, reason_prefix: str
    ) -> dict[str, list[dict[str, str]]]:
        extension_value = document.get("x-ea-rollback-capsule")
        extension = dict(extension_value) if isinstance(extension_value, dict) else {}
        expected_extension_keys = {
            "allowed_runtime_differences",
            "captured_at",
            "contract_name",
            "deployment_id",
            "external_resources",
            "functional_identity",
            "service",
            "source_container_id_sha256",
            "source_image_id",
            "source_image_reference",
            "version",
        }
        if (
            set(extension) != expected_extension_keys
            or extension.get("contract_name") != ROLLBACK_CAPSULE_CONTRACT_NAME
            or extension.get("version") != ROLLBACK_CAPSULE_VERSION
            or extension.get("service") != API_SERVICE
            or DEPLOYMENT_ID_PATTERN.fullmatch(
                str(extension.get("deployment_id") or "")
            )
            is None
            or SHA256_HEX_PATTERN.fullmatch(
                str(extension.get("source_container_id_sha256") or "")
            )
            is None
            or IMAGE_ID_PATTERN.fullmatch(str(extension.get("source_image_id") or ""))
            is None
        ):
            raise DeployError(f"{reason_prefix}_extension_invalid")
        _safe_tagged_image_reference(
            str(extension.get("source_image_reference") or ""),
            reason=f"{reason_prefix}_extension_invalid",
        )
        MemorialDeployLane._validated_functional_identity(
            extension.get("functional_identity"), reason_prefix=reason_prefix
        )
        resources_value = extension.get("external_resources")
        resources = dict(resources_value) if isinstance(resources_value, dict) else {}
        if set(resources) != {"networks", "volumes"}:
            raise DeployError(f"{reason_prefix}_external_resources_invalid")
        networks: list[dict[str, str]] = []
        seen_networks: set[str] = set()
        for raw in list(resources.get("networks") or []):
            if not isinstance(raw, dict) or set(raw) != {"name", "network_id"}:
                raise DeployError(f"{reason_prefix}_external_network_invalid")
            name = str(raw.get("name") or "")
            network_id = str(raw.get("network_id") or "")
            if (
                re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,254}", name) is None
                or SHA256_HEX_PATTERN.fullmatch(network_id) is None
                or name in seen_networks
            ):
                raise DeployError(f"{reason_prefix}_external_network_invalid")
            seen_networks.add(name)
            networks.append({"name": name, "network_id": network_id})
        volumes: list[dict[str, str]] = []
        seen_volumes: set[str] = set()
        for raw in list(resources.get("volumes") or []):
            if not isinstance(raw, dict) or set(raw) != {"driver", "name"}:
                raise DeployError(f"{reason_prefix}_external_volume_invalid")
            name = str(raw.get("name") or "")
            driver = str(raw.get("driver") or "")
            if (
                re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,254}", name) is None
                or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,254}", driver) is None
                or name in seen_volumes
            ):
                raise DeployError(f"{reason_prefix}_external_volume_invalid")
            seen_volumes.add(name)
            volumes.append({"name": name, "driver": driver})
        return {
            "networks": sorted(networks, key=lambda item: item["name"]),
            "volumes": sorted(volumes, key=lambda item: item["name"]),
        }

    def _revalidate_rollback_external_resources(
        self, document: Mapping[str, Any], *, boundary: str
    ) -> dict[str, object]:
        if not SAFE_SCRIPT_ORIGIN_PATTERN.fullmatch(boundary):
            raise DeployError("rollback_external_resource_boundary_invalid")
        bindings = self._rollback_capsule_external_bindings(
            document, reason_prefix="rollback_capsule"
        )
        for expected in bindings["networks"]:
            completed = self._run(["docker", "network", "inspect", expected["name"]])
            try:
                payload = json.loads(completed.stdout)
            except Exception as exc:
                raise DeployError("rollback_external_network_inspect_invalid") from exc
            if (
                not isinstance(payload, list)
                or len(payload) != 1
                or not isinstance(payload[0], dict)
                or str(payload[0].get("Name") or "") != expected["name"]
                or str(payload[0].get("Id") or "") != expected["network_id"]
            ):
                raise DeployError("rollback_external_network_identity_changed")
        for expected in bindings["volumes"]:
            completed = self._run(["docker", "volume", "inspect", expected["name"]])
            try:
                payload = json.loads(completed.stdout)
            except Exception as exc:
                raise DeployError("rollback_external_volume_inspect_invalid") from exc
            if (
                not isinstance(payload, list)
                or len(payload) != 1
                or not isinstance(payload[0], dict)
                or str(payload[0].get("Name") or "") != expected["name"]
                or str(payload[0].get("Driver") or "") != expected["driver"]
            ):
                raise DeployError("rollback_external_volume_identity_changed")
        evidence = {
            "boundary": boundary,
            "network_count": len(bindings["networks"]),
            "volume_count": len(bindings["volumes"]),
            "binding_sha256": _canonical_json_sha256(bindings),
        }
        return evidence

    @staticmethod
    def _rollback_render_healthcheck(value: object) -> dict[str, object]:
        if value in (None, {}):
            return {}
        if not isinstance(value, dict):
            raise DeployError("rollback_capsule_render_healthcheck_invalid")
        allowed = frozenset(
            {
                "disable",
                "interval",
                "retries",
                "start_interval",
                "start_period",
                "test",
                "timeout",
            }
        )
        _rollback_capsule_unknown_non_neutral(
            value,
            allowed,
            reason_prefix="rollback_capsule_render_healthcheck_field_unsupported",
        )
        if value.get("disable") not in (None, False):
            if value.get("disable") is not True:
                raise DeployError("rollback_capsule_render_healthcheck_invalid")
            return {"Test": ["NONE"]}
        result: dict[str, object] = {}
        test = value.get("test")
        if not _docker_value_is_neutral(test):
            if not isinstance(test, list) or not all(
                isinstance(item, str) and "\x00" not in item for item in test
            ):
                raise DeployError("rollback_capsule_render_healthcheck_invalid")
            result["Test"] = list(test)
        for compose_key, runtime_key in (
            ("interval", "Interval"),
            ("start_interval", "StartInterval"),
            ("start_period", "StartPeriod"),
            ("timeout", "Timeout"),
        ):
            raw = value.get(compose_key)
            if not _docker_value_is_neutral(raw):
                result[runtime_key] = _rollback_capsule_duration_ns(
                    raw, reason="rollback_capsule_render_healthcheck_invalid"
                )
        retries = value.get("retries")
        if not _docker_value_is_neutral(retries):
            if type(retries) is not int or retries < 0:
                raise DeployError("rollback_capsule_render_healthcheck_invalid")
            result["Retries"] = retries
        return result

    @staticmethod
    def _rollback_render_tmpfs(value: object) -> dict[str, str]:
        if value is None:
            return {}
        rows: list[str]
        if isinstance(value, list) and all(isinstance(item, str) for item in value):
            rows = list(value)
        elif isinstance(value, dict):
            rows = [
                f"{path}:{options}" if str(options) else str(path)
                for path, options in value.items()
            ]
        else:
            raise DeployError("rollback_capsule_render_tmpfs_invalid")
        result: dict[str, str] = {}
        for row in rows:
            path, separator, options = row.partition(":")
            if (
                not path.startswith("/")
                or os.path.normpath(path) != path
                or "\x00" in row
                or path in result
            ):
                raise DeployError("rollback_capsule_render_tmpfs_invalid")
            result[path] = options if separator else ""
        return {path: result[path] for path in sorted(result)}

    def _rollback_render_mounts(
        self,
        rendered: Mapping[str, Any],
        service: Mapping[str, Any],
        bindings: Mapping[str, list[dict[str, str]]],
    ) -> tuple[list[dict[str, object]], list[str]]:
        top_value = rendered.get("volumes")
        top = dict(top_value) if isinstance(top_value, dict) else {}
        bound_volumes = {item["name"]: item for item in bindings["volumes"]}
        resolved_top: dict[str, dict[str, str]] = {}
        for raw_key, raw_value in top.items():
            key = str(raw_key)
            value = dict(raw_value) if isinstance(raw_value, dict) else {}
            _rollback_capsule_unknown_non_neutral(
                value,
                ROLLBACK_CAPSULE_RENDER_VOLUME_KEYS,
                reason_prefix="rollback_capsule_render_volume_field_unsupported",
            )
            name = str(value.get("name") or f"{PROJECT_NAME}_{key}")
            if value.get("external") is not True or name not in bound_volumes:
                raise DeployError("rollback_capsule_render_external_volume_invalid")
            for field in ("driver", "driver_opts", "labels"):
                if not _docker_value_is_neutral(value.get(field)):
                    raise DeployError(
                        f"rollback_capsule_render_external_volume_field_unsupported:{field}"
                    )
            resolved_top[key] = bound_volumes[name]
        if set(item["name"] for item in resolved_top.values()) != set(bound_volumes):
            raise DeployError("rollback_capsule_render_external_volume_scope_invalid")

        raw_mounts = service.get("volumes") or []
        if not isinstance(raw_mounts, list):
            raise DeployError("rollback_capsule_render_mounts_invalid")
        mounts: list[dict[str, object]] = []
        binds: list[str] = []
        destinations: set[str] = set()
        for raw_mount in raw_mounts:
            if not isinstance(raw_mount, dict):
                raise DeployError("rollback_capsule_render_mounts_invalid")
            _rollback_capsule_unknown_non_neutral(
                raw_mount,
                ROLLBACK_CAPSULE_RENDER_MOUNT_KEYS,
                reason_prefix="rollback_capsule_render_mount_field_unsupported",
            )
            mount_type = str(raw_mount.get("type") or "")
            source_key = str(raw_mount.get("source") or "")
            destination = str(raw_mount.get("target") or "")
            read_write = not bool(raw_mount.get("read_only"))
            if (
                mount_type not in {"bind", "volume"}
                or not destination.startswith("/")
                or os.path.normpath(destination) != destination
                or destination in destinations
                or "\x00" in destination
            ):
                raise DeployError("rollback_capsule_render_mounts_invalid")
            destinations.add(destination)
            if mount_type == "bind":
                source = source_key
                source_path = Path(source)
                if (
                    not source_path.is_absolute()
                    or ".." in source_path.parts
                    or os.path.normpath(source) != source
                    or "\x00" in source
                ):
                    raise DeployError("rollback_capsule_render_bind_invalid")
                bind_value = raw_mount.get("bind") or {}
                bind = dict(bind_value) if isinstance(bind_value, dict) else {}
                _rollback_capsule_unknown_non_neutral(
                    bind,
                    ROLLBACK_CAPSULE_RENDER_BIND_KEYS,
                    reason_prefix="rollback_capsule_render_bind_field_unsupported",
                )
                if bind.get("create_host_path") not in (None, True):
                    raise DeployError("rollback_capsule_render_bind_invalid")
                if not _docker_value_is_neutral(bind.get("selinux")):
                    raise DeployError(
                        "rollback_capsule_render_bind_selinux_unsupported"
                    )
                propagation = str(bind.get("propagation") or "rprivate")
                if propagation not in {"private", "rprivate"}:
                    raise DeployError(
                        "rollback_capsule_render_bind_propagation_unsupported"
                    )
                driver = ""
            else:
                if source_key not in resolved_top:
                    raise DeployError("rollback_capsule_render_volume_unbound")
                binding = resolved_top[source_key]
                source = binding["name"]
                driver = binding["driver"]
                propagation = ""
                volume_value = raw_mount.get("volume") or {}
                volume = dict(volume_value) if isinstance(volume_value, dict) else {}
                _rollback_capsule_unknown_non_neutral(
                    volume,
                    ROLLBACK_CAPSULE_RENDER_VOLUME_OPTION_KEYS,
                    reason_prefix="rollback_capsule_render_volume_option_unsupported",
                )
                if volume.get("nocopy") not in (None, False) or not (
                    _docker_value_is_neutral(volume.get("subpath"))
                ):
                    raise DeployError(
                        "rollback_capsule_render_volume_option_unsupported"
                    )
            for field in ("consistency", "tmpfs"):
                if not _docker_value_is_neutral(raw_mount.get(field)):
                    raise DeployError(
                        f"rollback_capsule_render_mount_field_unsupported:{field}"
                    )
            mode = "rw" if read_write else "ro"
            mounts.append(
                {
                    "Type": mount_type,
                    "Source": source if mount_type == "bind" else "",
                    "Name": source if mount_type == "volume" else "",
                    "Driver": driver,
                    "Destination": destination,
                    "Mode": mode,
                    "RW": read_write,
                    "Propagation": propagation,
                }
            )
            options = [mode]
            if mount_type == "bind" and propagation not in {"", "rprivate"}:
                options.append(propagation)
            binds.append(f"{source}:{destination}:{','.join(options)}")
        return mounts, sorted(binds)

    def _rollback_render_networks(
        self,
        rendered: Mapping[str, Any],
        service: Mapping[str, Any],
        bindings: Mapping[str, list[dict[str, str]]],
    ) -> tuple[dict[str, dict[str, object]], str]:
        top_value = rendered.get("networks")
        top = dict(top_value) if isinstance(top_value, dict) else {}
        bound = {item["name"]: item for item in bindings["networks"]}
        resolved: dict[str, dict[str, str]] = {}
        for raw_key, raw_value in top.items():
            key = str(raw_key)
            value = dict(raw_value) if isinstance(raw_value, dict) else {}
            _rollback_capsule_unknown_non_neutral(
                value,
                ROLLBACK_CAPSULE_RENDER_NETWORK_KEYS,
                reason_prefix="rollback_capsule_render_network_field_unsupported",
            )
            name = str(value.get("name") or f"{PROJECT_NAME}_{key}")
            if value.get("external") is not True or name not in bound:
                raise DeployError("rollback_capsule_render_external_network_invalid")
            for field in (
                "attachable",
                "driver",
                "driver_opts",
                "enable_ipv6",
                "internal",
                "ipam",
                "labels",
            ):
                if not _docker_value_is_neutral(value.get(field)):
                    raise DeployError(
                        f"rollback_capsule_render_external_network_field_unsupported:{field}"
                    )
            if value.get("enable_ipv4") not in (None, True):
                raise DeployError(
                    "rollback_capsule_render_external_network_field_unsupported:enable_ipv4"
                )
            resolved[key] = bound[name]
        if set(item["name"] for item in resolved.values()) != set(bound):
            raise DeployError("rollback_capsule_render_external_network_scope_invalid")

        service_value = service.get("networks") or {}
        if isinstance(service_value, list):
            service_networks = {str(item): {} for item in service_value}
        elif isinstance(service_value, dict):
            service_networks = dict(service_value)
        else:
            raise DeployError("rollback_capsule_render_service_networks_invalid")
        if set(service_networks) != set(resolved):
            raise DeployError("rollback_capsule_render_service_network_scope_invalid")
        endpoints: dict[str, dict[str, object]] = {}
        ordered_names: list[str] = []
        for raw_key, raw_options in service_networks.items():
            key = str(raw_key)
            options = dict(raw_options) if isinstance(raw_options, dict) else {}
            _rollback_capsule_unknown_non_neutral(
                options,
                ROLLBACK_CAPSULE_RENDER_SERVICE_NETWORK_KEYS,
                reason_prefix="rollback_capsule_render_service_network_field_unsupported",
            )
            aliases_value = options.get("aliases") or []
            if not isinstance(aliases_value, list) or not all(
                isinstance(item, str)
                and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,254}", item) is not None
                for item in aliases_value
            ):
                raise DeployError("rollback_capsule_render_network_alias_invalid")
            for field in (
                "driver_opts",
                "gw_priority",
                "interface_name",
                "link_local_ips",
                "mac_address",
                "priority",
            ):
                if not _docker_value_is_neutral(options.get(field)):
                    raise DeployError(
                        f"rollback_capsule_render_service_network_field_unsupported:{field}"
                    )
            if "ipv6_address" in options and options.get("ipv6_address") is not None:
                raise DeployError(
                    "rollback_capsule_render_service_network_field_unsupported:"
                    "ipv6_address"
                )
            ipv4_address = ""
            if "ipv4_address" in options and options.get("ipv4_address") is not None:
                ipv4_address = _validated_ipv4_address(
                    options.get("ipv4_address"),
                    reason="rollback_capsule_render_static_ipv4_invalid",
                )
            binding = resolved[key]
            ordered_names.append(binding["name"])
            endpoint: dict[str, object] = {
                "NetworkID": binding["network_id"],
                "Aliases": sorted(set(aliases_value)),
            }
            if ipv4_address:
                endpoint["IPAMConfig"] = {"IPv4Address": ipv4_address}
            endpoints[binding["name"]] = endpoint
        return endpoints, ordered_names[0] if ordered_names else ""

    def _rollback_render_runtime_projection(
        self,
        rendered: Mapping[str, Any],
        document: Mapping[str, Any],
        *,
        image_id: str,
        image_config: Mapping[str, Any],
    ) -> dict[str, Any]:
        decoded_rendered = _rollback_capsule_decode_rendered_literals(dict(rendered))
        if not isinstance(decoded_rendered, dict):  # pragma: no cover - mapping input
            raise DeployError("rollback_capsule_render_json_invalid")
        rendered = decoded_rendered
        _rollback_capsule_unknown_non_neutral(
            rendered,
            ROLLBACK_CAPSULE_RENDER_TOP_LEVEL_KEYS,
            reason_prefix="rollback_capsule_render_top_level_field_unsupported",
        )
        if rendered.get("name") not in (None, PROJECT_NAME):
            raise DeployError("rollback_capsule_render_project_mismatch")
        if rendered.get("version") not in (None, "", "3", "3.0", "3.8", "3.9"):
            raise DeployError("rollback_capsule_render_version_unsupported")
        expected_extension = document.get("x-ea-rollback-capsule")
        if rendered.get("x-ea-rollback-capsule") != expected_extension:
            raise DeployError("rollback_capsule_render_extension_mismatch")
        bindings = self._rollback_capsule_external_bindings(
            document, reason_prefix="rollback_capsule"
        )
        services_value = rendered.get("services")
        services = dict(services_value) if isinstance(services_value, dict) else {}
        if set(services) != {API_SERVICE} or not isinstance(
            services.get(API_SERVICE), dict
        ):
            raise DeployError("rollback_capsule_render_service_scope_invalid")
        service = dict(services[API_SERVICE])
        _rollback_capsule_unknown_non_neutral(
            service,
            ROLLBACK_CAPSULE_RENDER_SERVICE_KEYS,
            reason_prefix="rollback_capsule_render_service_field_unsupported",
        )
        if not _docker_value_is_neutral(service.get("build")):
            raise DeployError("rollback_capsule_render_build_forbidden")
        extension = (
            dict(expected_extension) if isinstance(expected_extension, dict) else {}
        )
        image_reference = str(extension.get("source_image_reference") or "")
        if (
            str(service.get("image") or "") != image_reference
            or str(service.get("pull_policy") or "").casefold() != "never"
            or str(service.get("container_name") or "") != API_SERVICE
            or image_id != str(extension.get("source_image_id") or "")
        ):
            raise DeployError("rollback_capsule_render_image_mismatch")

        environment = self._rendered_environment_entries(service, image_config)
        process = self._rendered_process_config(service, image_config)
        command = list(process["Cmd"])
        entrypoint = list(process["Entrypoint"])
        runtime_vector = [*entrypoint, *command] if entrypoint else command
        runtime_path = runtime_vector[0] if runtime_vector else ""
        runtime_args = runtime_vector[1:] if runtime_vector else []
        config: dict[str, Any] = {
            "Image": image_reference,
            "Env": environment,
            "Cmd": command,
            "Entrypoint": entrypoint,
            "User": str(process["User"]),
            "WorkingDir": str(service.get("working_dir") or ""),
            "Hostname": str(service.get("hostname") or ""),
            "StopSignal": str(service.get("stop_signal") or ""),
            "Healthcheck": self._rollback_render_healthcheck(
                service.get("healthcheck")
            ),
        }
        stop_grace = service.get("stop_grace_period")
        if not _docker_value_is_neutral(stop_grace):
            stop_ns = _rollback_capsule_duration_ns(
                stop_grace, reason="rollback_capsule_render_stop_grace_invalid"
            )
            if stop_ns % 1_000_000_000:
                raise DeployError("rollback_capsule_render_stop_grace_invalid")
            config["StopTimeout"] = stop_ns // 1_000_000_000
        labels = service.get("labels") or {}
        if not isinstance(labels, dict) or not all(
            isinstance(name, str) and isinstance(value, str)
            for name, value in labels.items()
        ):
            raise DeployError("rollback_capsule_render_labels_invalid")
        config["Labels"] = dict(labels)

        exposed: dict[str, dict[str, object]] = {}
        port_bindings: dict[str, list[dict[str, str]]] = {}
        expose_value = service.get("expose") or []
        if not isinstance(expose_value, list):
            raise DeployError("rollback_capsule_render_ports_invalid")
        for raw in expose_value:
            text = str(raw)
            if "/" not in text:
                text = f"{text}/tcp"
            if re.fullmatch(r"[1-9][0-9]{0,4}/(?:tcp|udp|sctp)", text) is None:
                raise DeployError("rollback_capsule_render_ports_invalid")
            exposed[text] = {}
        ports_value = service.get("ports") or []
        if not isinstance(ports_value, list):
            raise DeployError("rollback_capsule_render_ports_invalid")
        for raw_port in ports_value:
            if not isinstance(raw_port, dict):
                raise DeployError("rollback_capsule_render_ports_invalid")
            _rollback_capsule_unknown_non_neutral(
                raw_port,
                ROLLBACK_CAPSULE_RENDER_PORT_KEYS,
                reason_prefix="rollback_capsule_render_port_field_unsupported",
            )
            target = raw_port.get("target")
            protocol = str(raw_port.get("protocol") or "tcp").casefold()
            published = raw_port.get("published")
            host_ip = str(raw_port.get("host_ip") or "")
            mode = str(raw_port.get("mode") or "ingress").casefold()
            if (
                type(target) is not int
                or not 1 <= target <= 65535
                or protocol not in {"tcp", "udp", "sctp"}
                or mode != "ingress"
                or not _docker_value_is_neutral(raw_port.get("name"))
                or not _docker_value_is_neutral(raw_port.get("app_protocol"))
            ):
                raise DeployError("rollback_capsule_render_ports_invalid")
            port_key = f"{target}/{protocol}"
            exposed[port_key] = {}
            if published is not None:
                published_text = str(published)
                if (
                    not published_text.isdigit()
                    or not 1 <= int(published_text) <= 65535
                    or "\x00" in host_ip
                ):
                    raise DeployError("rollback_capsule_render_ports_invalid")
                port_bindings.setdefault(port_key, []).append(
                    {"HostIp": host_ip, "HostPort": str(int(published_text))}
                )
        config["ExposedPorts"] = exposed

        host: dict[str, Any] = {
            "PortBindings": port_bindings,
            "ReadonlyRootfs": bool(service.get("read_only")),
            **ROLLBACK_CAPSULE_ENGINE_SECURITY_DEFAULTS,
        }
        for compose_key, runtime_key in (
            ("mem_limit", "Memory"),
            ("mem_reservation", "MemoryReservation"),
            ("memswap_limit", "MemorySwap"),
            ("shm_size", "ShmSize"),
        ):
            raw = service.get(compose_key)
            if not _docker_value_is_neutral(raw):
                host[runtime_key] = _rollback_capsule_byte_quantity(
                    raw, reason="rollback_capsule_render_resource_invalid"
                )
        for compose_key, runtime_key in (
            ("cpu_shares", "CpuShares"),
            ("pids_limit", "PidsLimit"),
        ):
            raw = service.get(compose_key)
            if not _docker_value_is_neutral(raw):
                if type(raw) is not int:
                    raise DeployError("rollback_capsule_render_resource_invalid")
                host[runtime_key] = raw
        cpus = service.get("cpus")
        if not _docker_value_is_neutral(cpus):
            host["NanoCpus"] = _rollback_capsule_nano_cpus(
                cpus, reason="rollback_capsule_render_resource_invalid"
            )
        for compose_key, runtime_key in (
            ("cap_drop", "CapDrop"),
            ("security_opt", "SecurityOpt"),
        ):
            raw = service.get(compose_key) or []
            if not isinstance(raw, list) or not all(
                isinstance(item, str) and item and "\x00" not in item for item in raw
            ):
                raise DeployError("rollback_capsule_render_security_invalid")
            if raw:
                host[runtime_key] = list(raw)
        extra_hosts = _rollback_capsule_extra_hosts(service.get("extra_hosts"))
        if extra_hosts:
            host["ExtraHosts"] = extra_hosts
        group_add = _rollback_capsule_group_add(service.get("group_add"))
        if group_add:
            host["GroupAdd"] = group_add
        for compose_key, runtime_key, allowed in (
            ("cgroup", "CgroupnsMode", {"private"}),
            ("ipc", "IpcMode", {"private"}),
            ("runtime", "Runtime", {"runc"}),
        ):
            raw = str(service.get(compose_key) or "")
            if raw:
                if raw not in allowed:
                    raise DeployError(
                        f"rollback_capsule_render_posture_unsupported:{compose_key}"
                    )
                host[runtime_key] = raw
        restart = str(service.get("restart") or "")
        if restart:
            name, separator, count_text = restart.partition(":")
            if name not in {"always", "no", "on-failure", "unless-stopped"}:
                raise DeployError("rollback_capsule_render_restart_invalid")
            count = 0
            if separator:
                if name != "on-failure" or not count_text.isdigit():
                    raise DeployError("rollback_capsule_render_restart_invalid")
                count = int(count_text)
            host["RestartPolicy"] = {"Name": name, "MaximumRetryCount": count}
        logging_value = service.get("logging") or {}
        if not isinstance(logging_value, dict):
            raise DeployError("rollback_capsule_render_logging_invalid")
        _rollback_capsule_unknown_non_neutral(
            logging_value,
            frozenset({"driver", "options"}),
            reason_prefix="rollback_capsule_render_logging_field_unsupported",
        )
        if logging_value:
            options = logging_value.get("options") or {}
            if not isinstance(options, dict) or not all(
                isinstance(name, str)
                and isinstance(item, (str, int, float, bool))
                and not isinstance(item, (dict, list))
                for name, item in options.items()
            ):
                raise DeployError("rollback_capsule_render_logging_invalid")
            host["LogConfig"] = {
                "Type": str(logging_value.get("driver") or ""),
                "Config": {name: str(options[name]) for name in sorted(options)},
            }
        tmpfs = self._rollback_render_tmpfs(service.get("tmpfs"))
        if tmpfs:
            host["Tmpfs"] = tmpfs

        mounts, binds = self._rollback_render_mounts(rendered, service, bindings)
        host["Binds"] = binds
        networks, network_mode = self._rollback_render_networks(
            rendered, service, bindings
        )
        if network_mode:
            host["NetworkMode"] = network_mode
        return {
            "Id": "",
            "Image": image_id,
            "Path": runtime_path,
            "Args": runtime_args,
            "Config": config,
            "HostConfig": host,
            "Mounts": mounts,
            "NetworkSettings": {
                "Networks": networks,
                "Ports": port_bindings,
                "SandboxID": "",
                "SandboxKey": "",
            },
        }

    def _verify_rollback_renderability(
        self, previous: Mapping[str, Any]
    ) -> dict[str, Any]:
        return self._verify_rollback_capsule_renderability(previous)

    def _materialize_rollback_capsule(
        self,
        document: Mapping[str, Any],
        identity: Mapping[str, object],
    ) -> dict[str, object]:
        payload = (
            json.dumps(
                dict(document),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
        seal = self._write_private_artifact_once(
            self.rollback_capsule_path,
            payload,
            reason_prefix="rollback_capsule",
        )
        self._rollback_capsule_seal = dict(seal)
        self._rollback_capsule_document = dict(document)
        self.receipt["rollback_capsule"] = {
            "contract_name": ROLLBACK_CAPSULE_CONTRACT_NAME,
            "version": ROLLBACK_CAPSULE_VERSION,
            "path_basename": self.rollback_capsule_path.name,
            "sha256": str(seal["sha256"]),
            "size_bytes": int(seal["size_bytes"]),
            "mode": str(seal["mode"]),
            "functional_identity_sha256": str(
                identity.get("functional_identity_sha256") or ""
            ),
            "status": "sealed",
        }
        self._write_receipt()
        return seal

    def _verify_rollback_capsule_renderability(
        self, previous: Mapping[str, Any], *, record: bool = True
    ) -> dict[str, Any]:
        seal = self._rollback_capsule_seal
        document = self._rollback_capsule_document
        if seal is None or document is None:
            raise DeployError("rollback_capsule_missing")
        if self._deployment_input_file_seal(self.rollback_capsule_path) != seal:
            raise DeployError("rollback_capsule_changed")
        completed = self._run(
            self._rollback_capsule_compose(
                self.rollback_capsule_path,
                "config",
                "--format",
                "json",
            ),
            cwd=self._rollback_capsule_project_directory,
            env=self._rollback_environment(previous),
        )
        rendered = _json_object(
            completed.stdout,
            reason="rollback_capsule_render_json_invalid",
        )
        image = self._inspect_image_config(
            str(
                previous.get("image_lookup_reference")
                or previous.get("image_reference")
                or ""
            )
        )
        if image["image_id"] != str(previous.get("image_id") or ""):
            raise DeployError("rollback_capsule_render_image_identity_mismatch")
        external_resources = self._revalidate_rollback_external_resources(
            document, boundary="rollback_render_preflight"
        )
        projected_inspection = self._rollback_render_runtime_projection(
            rendered,
            document,
            image_id=str(image["image_id"]),
            image_config=dict(image["config"]),
        )
        rendered_identity = _container_functional_identity(projected_inspection)
        expected_identity = self._validated_functional_identity(
            previous.get("functional_identity"), reason_prefix="rollback_capsule"
        )
        if rendered_identity != expected_identity:
            expected_domains = dict(expected_identity.get("domains") or {})
            rendered_domains = dict(rendered_identity.get("domains") or {})
            differing = sorted(
                name
                for name in {*expected_domains, *rendered_domains}
                if expected_domains.get(name) != rendered_domains.get(name)
            )
            raise DeployError(
                "rollback_capsule_render_functional_identity_mismatch:"
                + (differing[0] if differing else "overall")
            )
        runtime_environment = list(
            dict(projected_inspection["Config"]).get("Env") or []
        )
        environment_identity = _environment_identity(runtime_environment)
        rendered_process = {
            key: dict(projected_inspection["Config"]).get(key)
            for key in ("Cmd", "Entrypoint", "User")
        }
        process_digest = _process_config_identity(rendered_process)
        rendered_mounts = _rollback_capsule_mount_identities(projected_inspection)
        mount_digest = _identity_digest(
            [
                {
                    "type": item["type"],
                    "source": item["source"],
                    "destination": item["destination"],
                    "read_write": item["read_write"],
                }
                for item in rendered_mounts
            ]
        )
        evidence = {
            "status": "pass",
            "contract_name": ROLLBACK_CAPSULE_CONTRACT_NAME,
            "capsule_sha256": str(seal["sha256"]),
            "image_id": str(previous.get("image_id") or ""),
            "image_reference": str(previous.get("image_reference") or ""),
            **environment_identity,
            "process_config_sha256": process_digest,
            "mount_identity_sha256": mount_digest,
            "mount_identity_count": len(rendered_mounts),
            "functional_identity_sha256": str(
                rendered_identity.get("functional_identity_sha256") or ""
            ),
            "network_count": int(
                dict(rendered_identity["domains"])["networks"]["count"]
            ),
            "external_resources": external_resources,
        }
        if record:
            self.receipt["rollback_render_preflight"] = evidence
            self._record_check("rollback_capsule_render_preflight", "pass")
        return evidence

    def _arm_rollback_recovery(
        self,
        *,
        previous: Mapping[str, Any],
        rollback_tag: str,
        non_memorial_controls: Mapping[str, Any],
        public_origin: str,
    ) -> None:
        capsule_seal = self._rollback_capsule_seal
        capsule_document = self._rollback_capsule_document
        if capsule_seal is None or capsule_document is None:
            raise DeployError("rollback_capsule_missing")
        self._require_joint_recovery_absent()
        functional_identity = self._validated_functional_identity(
            previous.get("functional_identity"), reason_prefix="rollback_recovery"
        )
        openapi = dict(non_memorial_controls.get("openapi") or {})
        contract_sha256 = str(openapi.get("contract_sha256") or "")
        source_revision = str(previous.get("source_revision") or "")
        validated_origin = _validate_public_origin(
            public_origin, allowed_hosts=self.allowed_public_hosts
        )
        if (
            SHA256_HEX_PATTERN.fullmatch(contract_sha256) is None
            or SOURCE_REVISION_PATTERN.fullmatch(source_revision) is None
        ):
            raise DeployError("rollback_recovery_baseline_invalid")
        journal = {
            "contract_name": ROLLBACK_RECOVERY_CONTRACT_NAME,
            "version": ROLLBACK_RECOVERY_VERSION,
            "status": ROLLBACK_RECOVERY_ARMED_STATUS,
            "deployment_id": self.deployment_id,
            "service": API_SERVICE,
            "armed_at": _utc_now(),
            "capsule_seal": dict(capsule_seal),
            "source_image_id": str(previous.get("image_id") or ""),
            "source_image_reference": str(previous.get("image_reference") or ""),
            "source_container_id_sha256": str(
                dict(capsule_document.get("x-ea-rollback-capsule") or {}).get(
                    "source_container_id_sha256"
                )
                or ""
            ),
            "protected_image_tag": rollback_tag,
            "baseline": {
                "functional_identity": functional_identity,
                "internal_openapi_contract_sha256": contract_sha256,
                "public_origin": validated_origin,
                "source_revision": source_revision,
            },
            "external_resources": self._rollback_capsule_external_bindings(
                capsule_document, reason_prefix="rollback_recovery"
            ),
            "recovery_policy": "emergency_rollback",
        }
        payload = self._rollback_recovery_payload(journal)
        self._rollback_recovery_seal = self._write_private_artifact_once(
            self.joint_recovery_journal_path,
            payload,
            reason_prefix="rollback_recovery_journal",
        )
        self._rollback_recovery_document = journal
        self.receipt["rollback_recovery"] = {
            "contract_name": ROLLBACK_RECOVERY_CONTRACT_NAME,
            "version": ROLLBACK_RECOVERY_VERSION,
            "status": "armed",
            "journal_sha256": str(self._rollback_recovery_seal["sha256"]),
        }
        self._write_receipt()

    @staticmethod
    def _rollback_recovery_payload(document: Mapping[str, Any]) -> bytes:
        payload = (
            json.dumps(
                dict(document),
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
        if not payload or len(payload) > MAX_DEPLOYMENT_INPUT_BYTES:
            raise DeployError("rollback_recovery_journal_size_invalid")
        return payload

    def _validate_recovery_capsule_seal(
        self, value: object, *, deployment_id: str
    ) -> dict[str, object]:
        seal = dict(value) if isinstance(value, dict) else {}
        expected_keys = {
            "ctime_ns",
            "device",
            "gid",
            "inode",
            "link_count",
            "mode",
            "mtime_ns",
            "path",
            "sha256",
            "size_bytes",
            "uid",
        }
        expected_path = (
            self.receipt_dir / f"{deployment_id}.rollback-capsule.compose.json"
        )
        if (
            set(seal) != expected_keys
            or seal.get("path") != str(expected_path)
            or SHA256_HEX_PATTERN.fullmatch(str(seal.get("sha256") or "")) is None
            or type(seal.get("size_bytes")) is not int
            or not 0 < int(seal["size_bytes"]) <= MAX_DEPLOYMENT_INPUT_BYTES
            or seal.get("mode") != "0600"
            or seal.get("uid") != os.geteuid()
            or seal.get("link_count") != 1
            or any(
                type(seal.get(key)) is not int or int(seal[key]) < 0
                for key in (
                    "ctime_ns",
                    "device",
                    "gid",
                    "inode",
                    "mtime_ns",
                )
            )
        ):
            raise DeployError("rollback_recovery_capsule_seal_invalid")
        return seal

    def _validated_rollback_recovery_document(self, value: object) -> dict[str, Any]:
        journal = dict(value) if isinstance(value, dict) else {}
        common = {
            "armed_at",
            "capsule_seal",
            "contract_name",
            "deployment_id",
            "recovery_policy",
            "service",
            "status",
            "version",
        }
        armed_only = {
            "baseline",
            "external_resources",
            "protected_image_tag",
            "source_container_id_sha256",
            "source_image_id",
            "source_image_reference",
        }
        cleanup = {"cleanup_started_at", "terminal_status"}
        status = str(journal.get("status") or "")
        if (
            journal.get("contract_name") != ROLLBACK_RECOVERY_CONTRACT_NAME
            or journal.get("version") != ROLLBACK_RECOVERY_VERSION
            or status not in ROLLBACK_RECOVERY_ALLOWED_STATUSES
            or journal.get("service") != API_SERVICE
            or DEPLOYMENT_ID_PATTERN.fullmatch(str(journal.get("deployment_id") or ""))
            is None
            or not isinstance(journal.get("armed_at"), str)
            or not str(journal["armed_at"]).strip()
            or len(str(journal["armed_at"])) > 128
        ):
            raise DeployError("rollback_recovery_journal_contract_invalid")
        deployment_id = str(journal["deployment_id"])
        journal["capsule_seal"] = self._validate_recovery_capsule_seal(
            journal.get("capsule_seal"), deployment_id=deployment_id
        )
        if status == ROLLBACK_RECOVERY_ARMED_STATUS:
            if (
                set(journal) != common | armed_only
                or journal.get("recovery_policy") != "emergency_rollback"
            ):
                raise DeployError("rollback_recovery_journal_schema_invalid")
        else:
            full_cleanup = common | armed_only | cleanup
            cleanup_only = common | cleanup
            if frozenset(journal) not in {
                frozenset(full_cleanup),
                frozenset(cleanup_only),
            }:
                raise DeployError("rollback_recovery_journal_schema_invalid")
            if journal.get("recovery_policy") not in {
                "emergency_rollback",
                "cleanup_only",
            }:
                raise DeployError("rollback_recovery_policy_invalid")
            if (
                not isinstance(journal.get("cleanup_started_at"), str)
                or not str(journal["cleanup_started_at"]).strip()
                or re.fullmatch(
                    r"[A-Za-z0-9][A-Za-z0-9._-]{2,127}",
                    str(journal.get("terminal_status") or ""),
                )
                is None
            ):
                raise DeployError("rollback_recovery_cleanup_state_invalid")
        if armed_only <= set(journal):
            source_image_id = str(journal.get("source_image_id") or "")
            source_image_reference = str(journal.get("source_image_reference") or "")
            if (
                IMAGE_ID_PATTERN.fullmatch(source_image_id) is None
                or SHA256_HEX_PATTERN.fullmatch(
                    str(journal.get("source_container_id_sha256") or "")
                )
                is None
            ):
                raise DeployError("rollback_recovery_source_identity_invalid")
            _safe_tagged_image_reference(
                source_image_reference,
                reason="rollback_recovery_source_identity_invalid",
            )
            _safe_tagged_image_reference(
                str(journal.get("protected_image_tag") or ""),
                reason="rollback_recovery_protected_image_tag_invalid",
            )
            baseline_value = journal.get("baseline")
            baseline = dict(baseline_value) if isinstance(baseline_value, dict) else {}
            if set(baseline) != {
                "functional_identity",
                "internal_openapi_contract_sha256",
                "public_origin",
                "source_revision",
            }:
                raise DeployError("rollback_recovery_baseline_invalid")
            functional_identity = self._validated_functional_identity(
                baseline.get("functional_identity"),
                reason_prefix="rollback_recovery",
            )
            image_domain = dict(
                dict(functional_identity.get("domains") or {}).get("image") or {}
            )
            if (
                image_domain.get("image_id") != source_image_id
                or image_domain.get("image_reference") != source_image_reference
                or SHA256_HEX_PATTERN.fullmatch(
                    str(baseline.get("internal_openapi_contract_sha256") or "")
                )
                is None
                or SOURCE_REVISION_PATTERN.fullmatch(
                    str(baseline.get("source_revision") or "")
                )
                is None
            ):
                raise DeployError("rollback_recovery_baseline_invalid")
            baseline["public_origin"] = _validate_public_origin(
                str(baseline.get("public_origin") or ""),
                allowed_hosts=self.allowed_public_hosts,
            )
            baseline["functional_identity"] = functional_identity
            journal["baseline"] = baseline
            resources = journal.get("external_resources")
            resource_wrapper = {
                "x-ea-rollback-capsule": {
                    "allowed_runtime_differences": [
                        "compose_managed_labels",
                        "container_and_start_timestamps",
                        "container_id",
                        "dynamic_network_endpoint_identity",
                    ],
                    "captured_at": str(journal["armed_at"]),
                    "contract_name": ROLLBACK_CAPSULE_CONTRACT_NAME,
                    "deployment_id": deployment_id,
                    "external_resources": resources,
                    "functional_identity": functional_identity,
                    "service": API_SERVICE,
                    "source_container_id_sha256": str(
                        journal["source_container_id_sha256"]
                    ),
                    "source_image_id": source_image_id,
                    "source_image_reference": source_image_reference,
                    "version": ROLLBACK_CAPSULE_VERSION,
                }
            }
            self._rollback_capsule_external_bindings(
                resource_wrapper, reason_prefix="rollback_recovery"
            )
        return journal

    def _load_active_rollback_recovery(
        self,
    ) -> tuple[dict[str, Any], dict[str, object], bool] | None:
        try:
            self._require_joint_recovery_absent()
        except DeployError:
            pass
        else:
            return None
        loaded = self._read_private_artifact(
            self.joint_recovery_journal_path,
            reason_prefix="rollback_recovery_journal",
        )
        if loaded is None:  # pragma: no cover - non-optional read
            raise DeployError("rollback_recovery_journal_unavailable")
        raw, seal = loaded
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DeployError("rollback_recovery_journal_json_invalid") from exc
        journal = self._validated_rollback_recovery_document(decoded)
        capsule_seal = dict(journal["capsule_seal"])
        capsule_path = Path(str(capsule_seal["path"]))
        capsule_loaded = self._read_private_artifact(
            capsule_path,
            reason_prefix="rollback_capsule",
            allow_absent=(journal["status"] == ROLLBACK_RECOVERY_CLEANUP_STATUS),
        )
        capsule_present = capsule_loaded is not None
        capsule_document: dict[str, Any] | None = None
        if capsule_loaded is not None:
            capsule_raw, observed_capsule_seal = capsule_loaded
            if observed_capsule_seal != capsule_seal:
                raise DeployError("rollback_recovery_capsule_seal_mismatch")
            try:
                decoded_capsule = json.loads(capsule_raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise DeployError("rollback_recovery_capsule_json_invalid") from exc
            if not isinstance(decoded_capsule, dict):
                raise DeployError("rollback_recovery_capsule_json_invalid")
            capsule_document = dict(decoded_capsule)
            extension = dict(capsule_document.get("x-ea-rollback-capsule") or {})
            if extension.get("deployment_id") != journal["deployment_id"]:
                raise DeployError("rollback_recovery_capsule_deployment_mismatch")
            capsule_bindings = self._rollback_capsule_external_bindings(
                capsule_document, reason_prefix="rollback_recovery"
            )
            if "external_resources" in journal and capsule_bindings != journal.get(
                "external_resources"
            ):
                raise DeployError("rollback_recovery_resource_binding_mismatch")
            if (
                "baseline" in journal
                and extension.get("functional_identity")
                != dict(journal["baseline"])["functional_identity"]
            ):
                raise DeployError("rollback_recovery_functional_identity_mismatch")
        elif journal["status"] == ROLLBACK_RECOVERY_ARMED_STATUS:
            raise DeployError("rollback_recovery_capsule_missing")
        self._rollback_recovery_seal = dict(seal)
        self._rollback_recovery_document = journal
        self._rollback_capsule_seal = capsule_seal
        self._rollback_capsule_document = capsule_document
        self.rollback_capsule_path = capsule_path
        self._rollback_capsule_project_directory = capsule_path.parent
        return journal, seal, capsule_present

    def _require_loaded_active_recovery(
        self, *, previous: Mapping[str, Any], rollback_tag: str
    ) -> None:
        loaded = self._load_active_rollback_recovery()
        if loaded is None:
            raise DeployError("rollback_recovery_journal_missing")
        journal = loaded[0]
        baseline = dict(journal.get("baseline") or {})
        if (
            journal.get("status") != ROLLBACK_RECOVERY_ARMED_STATUS
            or journal.get("protected_image_tag") != rollback_tag
            or journal.get("source_image_id") != previous.get("image_id")
            or journal.get("source_image_reference") != previous.get("image_reference")
            or baseline.get("functional_identity")
            != previous.get("functional_identity")
        ):
            raise DeployError("rollback_recovery_binding_mismatch")

    def _arm_cleanup_only_recovery(self, *, terminal_status: str) -> None:
        capsule_seal = self._rollback_capsule_seal
        if capsule_seal is None:
            return
        self._require_joint_recovery_absent()
        document = {
            "contract_name": ROLLBACK_RECOVERY_CONTRACT_NAME,
            "version": ROLLBACK_RECOVERY_VERSION,
            "status": ROLLBACK_RECOVERY_CLEANUP_STATUS,
            "deployment_id": self.deployment_id,
            "service": API_SERVICE,
            "armed_at": _utc_now(),
            "capsule_seal": dict(capsule_seal),
            "recovery_policy": "cleanup_only",
            "terminal_status": terminal_status,
            "cleanup_started_at": _utc_now(),
        }
        self._rollback_recovery_seal = self._write_private_artifact_once(
            self.joint_recovery_journal_path,
            self._rollback_recovery_payload(document),
            reason_prefix="rollback_recovery_journal",
        )
        self._rollback_recovery_document = document

    def _clear_rollback_artifacts(self, *, terminal_status: str) -> None:
        if self._rollback_capsule_seal is not None and (
            self._rollback_recovery_seal is None
        ):
            self._arm_cleanup_only_recovery(terminal_status=terminal_status)
        if self._rollback_recovery_seal is not None:
            journal = dict(self._rollback_recovery_document or {})
            if journal.get("status") != ROLLBACK_RECOVERY_CLEANUP_STATUS:
                journal["status"] = ROLLBACK_RECOVERY_CLEANUP_STATUS
                journal["terminal_status"] = terminal_status
                journal["cleanup_started_at"] = _utc_now()
                self._rollback_recovery_seal = self._replace_private_artifact(
                    self.joint_recovery_journal_path,
                    self._rollback_recovery_payload(journal),
                    self._rollback_recovery_seal,
                    reason_prefix="rollback_recovery_journal",
                )
                self._rollback_recovery_document = journal
        if self._rollback_capsule_seal is not None:
            self._remove_private_artifact(
                self.rollback_capsule_path,
                self._rollback_capsule_seal,
                reason_prefix="rollback_capsule",
                allow_absent=(
                    dict(self._rollback_recovery_document or {}).get("status")
                    == ROLLBACK_RECOVERY_CLEANUP_STATUS
                ),
            )
            self._rollback_capsule_seal = None
            self._rollback_capsule_document = None
            capsule = dict(self.receipt.get("rollback_capsule") or {})
            capsule["status"] = terminal_status
            self.receipt["rollback_capsule"] = capsule
        if self._rollback_recovery_seal is not None:
            self._remove_private_artifact(
                self.joint_recovery_journal_path,
                self._rollback_recovery_seal,
                reason_prefix="rollback_recovery_journal",
            )
            self._rollback_recovery_seal = None
            self._rollback_recovery_document = None
            self.receipt["rollback_recovery"] = {"status": terminal_status}
        rollback = dict(self.receipt.get("rollback") or {})
        rollback["availability"] = "retired"
        rollback["capsule_available"] = False
        if rollback.get("status") == "available":
            rollback["status"] = terminal_status
        self.receipt["rollback"] = rollback

    def _verify_active_recovery_baseline(
        self,
        journal: Mapping[str, Any],
        *,
        mismatch_returns_none: bool,
    ) -> dict[str, Any] | None:
        baseline = dict(journal.get("baseline") or {})
        expected_identity = self._validated_functional_identity(
            baseline.get("functional_identity"),
            reason_prefix="rollback_recovery",
        )
        current = self._inspect_container_optional(API_SERVICE)
        if current is None:
            return None
        try:
            current_identity = _container_functional_identity(current)
        except DeployError:
            return None
        if current_identity != expected_identity:
            return None
        state = dict(current.get("State") or {})
        health = str(dict(state.get("Health") or {}).get("Status") or "")
        if (
            state.get("Running") is not True
            or state.get("Restarting") is True
            or health != "healthy"
        ):
            return None
        try:
            health_probe = self._wait_http(
                f"{self._local_origin()}/health", kind="recovery_health"
            )
            openapi = self._capture_internal_openapi_control()
            if openapi.get("contract_sha256") != baseline.get(
                "internal_openapi_contract_sha256"
            ):
                raise DeployError("rollback_recovery_openapi_contract_mismatch")
            public_endpoint = self._capture_public_openapi_retirement(
                str(baseline.get("public_origin") or ""),
                expected_source_revision=str(baseline.get("source_revision") or ""),
            )
        except DeployError:
            if mismatch_returns_none:
                return None
            raise
        container_id = str(current.get("Id") or "")
        return {
            "status": "verified",
            "functional_identity_sha256": str(
                current_identity["functional_identity_sha256"]
            ),
            "container_id_sha256": hashlib.sha256(
                container_id.encode("utf-8")
            ).hexdigest(),
            "health": health_probe,
            "internal_openapi_contract_sha256": str(openapi["contract_sha256"]),
            "public_openapi": public_endpoint,
        }

    def _execute_active_recovery_rollback(
        self, journal: Mapping[str, Any]
    ) -> dict[str, Any]:
        capsule_document = self._rollback_capsule_document
        capsule_seal = self._rollback_capsule_seal
        if capsule_document is None or capsule_seal is None:
            raise DeployError("rollback_recovery_capsule_missing")
        source_image_id = str(journal.get("source_image_id") or "")
        source_reference = _safe_tagged_image_reference(
            str(journal.get("source_image_reference") or ""),
            reason="rollback_recovery_source_image_reference_invalid",
        )
        protected_tag = str(journal.get("protected_image_tag") or "")
        protected = self._inspect_image(protected_tag)
        if protected["image_id"] != source_image_id:
            raise DeployError("rollback_recovery_protected_image_mismatch")
        previous = {
            "image_id": source_image_id,
            "image_reference": source_reference,
            "image_lookup_reference": protected_tag,
            "functional_identity": dict(journal["baseline"])["functional_identity"],
        }
        self._verify_rollback_capsule_renderability(previous, record=False)
        self._revalidate_rollback_external_resources(
            capsule_document,
            boundary="before_recover_active_rollback",
        )
        rollback_env = self._rollback_environment(previous)
        self._run(
            ["docker", "image", "tag", source_image_id, source_reference],
            env=rollback_env,
        )
        self._run(
            self._rollback_capsule_compose(
                self.rollback_capsule_path,
                "up",
                "-d",
                "--no-build",
                "--no-deps",
                "--force-recreate",
                API_SERVICE,
            ),
            cwd=self._rollback_capsule_project_directory,
            env=rollback_env,
        )
        current = self._inspect_container(API_SERVICE)
        self._require_compose_identity(
            current, service=API_SERVICE, reason_prefix="rollback_recovery_api"
        )
        labels = dict(dict(current.get("Config") or {}).get("Labels") or {})
        if (
            labels.get("com.docker.compose.container-number") != "1"
            or labels.get("com.docker.compose.oneoff") != "False"
            or labels.get("com.docker.compose.image") != source_image_id
        ):
            raise DeployError("rollback_recovery_compose_identity_mismatch")
        topology = self._compose_topology(
            current, reason_prefix="rollback_recovery_api"
        )
        if topology.get("working_dir") != str(self.receipt_dir) or topology.get(
            "compose_config_files"
        ) != [str(self.rollback_capsule_path)]:
            raise DeployError("rollback_recovery_compose_topology_mismatch")
        verified = self._verify_active_recovery_baseline(
            journal, mismatch_returns_none=False
        )
        if verified is None:
            raise DeployError("rollback_recovery_baseline_not_restored")
        return verified

    def recover_active(self) -> dict[str, Any]:
        if self._global_lock_handle is not None or self._lock_handle is not None:
            raise DeployError("rollback_recovery_lock_state_invalid")
        self._global_lock_handle = self._open_lock(
            self.global_lock_path,
            busy_reason="memorial_api_deployment_already_running",
        )
        try:
            self._require_normalization_recovery_absent()
            loaded = self._load_active_rollback_recovery()
            if loaded is None:
                return {
                    "contract_name": "ea.memorial_api_recovery_result.v1",
                    "status": "no_active_recovery",
                    "api_mutation_count": 0,
                }
            journal, _journal_seal, capsule_present = loaded
            if journal["status"] == ROLLBACK_RECOVERY_CLEANUP_STATUS:
                terminal_status = str(
                    journal.get("terminal_status") or "cleanup_replayed"
                )
                self._clear_rollback_artifacts(terminal_status=terminal_status)
                return {
                    "contract_name": "ea.memorial_api_recovery_result.v1",
                    "status": "cleanup_replayed",
                    "terminal_status": terminal_status,
                    "capsule_was_present": capsule_present,
                    "api_mutation_count": 0,
                }
            self._detect_compose()
            protected = self._inspect_image(str(journal["protected_image_tag"]))
            if protected["image_id"] != journal["source_image_id"]:
                raise DeployError("rollback_recovery_protected_image_mismatch")
            existing = self._verify_active_recovery_baseline(
                journal, mismatch_returns_none=True
            )
            mutation_count = 0
            if existing is None:
                existing = self._execute_active_recovery_rollback(journal)
                mutation_count = 1
                result_status = "rollback_verified"
            else:
                result_status = "baseline_already_exact"
            self._clear_rollback_artifacts(
                terminal_status=f"retired_after_{result_status}"
            )
            return {
                "contract_name": "ea.memorial_api_recovery_result.v1",
                "status": result_status,
                "api_mutation_count": mutation_count,
                "verification": existing,
            }
        finally:
            self._release_lock()

    def _resolve_candidate_image(self, source_revision: str) -> dict[str, Any]:
        if not self.memorial_image_reference:
            raise DeployError("explicit_memorial_image_required")
        reference = _safe_candidate_image_reference(
            self.memorial_image_reference,
            source_revision=source_revision,
        )
        candidate = self._inspect_image(reference)
        self.release_env["EA_MEMORIAL_IMAGE"] = reference
        self.receipt["candidate_image"] = candidate
        self._write_receipt()
        return candidate

    def _configured_memorial_data_root(self) -> Path:
        configured_data_root = _first_nonempty(
            self.env.get("EA_MEMORIAL_DATA_HOST_PATH"),
            self.env_file_values.get("EA_MEMORIAL_DATA_HOST_PATH"),
        )
        if not configured_data_root:
            raise DeployError("explicit_memorial_data_host_path_required")
        expected_data_root = Path(configured_data_root).expanduser()
        if not expected_data_root.is_absolute():
            expected_data_root = self.root / expected_data_root
        return expected_data_root.resolve()

    def _configured_memorial_runtime_root(self) -> Path:
        configured_runtime_root = _first_nonempty(
            self.env.get("EA_MEMORIAL_RUNTIME_HOST_PATH"),
            self.env_file_values.get("EA_MEMORIAL_RUNTIME_HOST_PATH"),
        )
        if not configured_runtime_root:
            raise DeployError("explicit_memorial_runtime_host_path_required")
        runtime_root = Path(configured_runtime_root).expanduser()
        if not runtime_root.is_absolute():
            runtime_root = self.root / runtime_root
        return runtime_root.resolve()

    def _validate_candidate_promotion_receipt(
        self,
        *,
        candidate: Mapping[str, Any],
        source_revision: str,
    ) -> dict[str, Any]:
        if not self.candidate_receipt_value:
            raise DeployError("explicit_memorial_candidate_receipt_required")
        raw_path = Path(self.candidate_receipt_value).expanduser()
        if not raw_path.is_absolute() or raw_path.is_symlink():
            raise DeployError("memorial_candidate_receipt_path_invalid")
        path = raw_path.resolve()
        flags = os.O_RDONLY | os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(raw_path, flags)
        except OSError as exc:
            raise DeployError("memorial_candidate_receipt_missing") from exc
        try:
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_nlink != 1
                or stat.S_IMODE(metadata.st_mode) != 0o600
            ):
                raise DeployError("memorial_candidate_receipt_permissions_invalid")
            with os.fdopen(descriptor, "rb") as handle:
                descriptor = -1
                raw = handle.read(MAX_HTTP_BODY_BYTES + 1)
        except OSError as exc:
            raise DeployError("memorial_candidate_receipt_unreadable") from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        if not raw or len(raw) > MAX_HTTP_BODY_BYTES:
            raise DeployError("memorial_candidate_receipt_size_invalid")
        try:
            payload = json.loads(raw)
        except Exception as exc:
            raise DeployError("memorial_candidate_receipt_json_invalid") from exc
        if not isinstance(payload, dict):
            raise DeployError("memorial_candidate_receipt_json_invalid")

        expected_data_root = self._configured_memorial_data_root()
        self.durable_root_check(expected_data_root)
        candidate_release_root = Path(
            str(payload.get("release_root") or "")
        ).expanduser()
        if not candidate_release_root.is_absolute():
            raise DeployError("memorial_candidate_release_root_invalid")
        candidate_release_root = candidate_release_root.resolve()

        browser_value = payload.get("browser_surface")
        browser = dict(browser_value) if isinstance(browser_value, dict) else {}
        candidate_project = str(payload.get("compose_project") or "")
        candidate_project_suffix = candidate_project.removeprefix(
            "ea-manfred-candidate-"
        )
        candidate_port = payload.get("candidate_port")
        candidate_preflight_value = payload.get("candidate_preflight")
        candidate_preflight = (
            dict(candidate_preflight_value)
            if isinstance(candidate_preflight_value, dict)
            else {}
        )
        locks_value = payload.get("locks")
        locks = dict(locks_value) if isinstance(locks_value, dict) else {}
        project_lock_value = locks.get("project")
        project_lock = (
            dict(project_lock_value) if isinstance(project_lock_value, dict) else {}
        )
        port_lock_value = locks.get("port")
        port_lock = dict(port_lock_value) if isinstance(port_lock_value, dict) else {}
        top_project_lock_value = payload.get("project_lock")
        top_project_lock = (
            dict(top_project_lock_value)
            if isinstance(top_project_lock_value, dict)
            else {}
        )
        top_port_lock_value = payload.get("port_lock")
        top_port_lock = (
            dict(top_port_lock_value) if isinstance(top_port_lock_value, dict) else {}
        )
        locator_value = payload.get("image_locator_evidence")
        locator = dict(locator_value) if isinstance(locator_value, dict) else {}
        container_images_value = payload.get("candidate_container_images")
        container_images = (
            dict(container_images_value)
            if isinstance(container_images_value, dict)
            else {}
        )
        candidate_api_image_value = container_images.get("api")
        candidate_api_image = (
            dict(candidate_api_image_value)
            if isinstance(candidate_api_image_value, dict)
            else {}
        )
        candidate_gateway_image_value = container_images.get("gateway")
        candidate_gateway_image = (
            dict(candidate_gateway_image_value)
            if isinstance(candidate_gateway_image_value, dict)
            else {}
        )
        named_resources_value = payload.get("candidate_named_resources")
        named_resources = (
            dict(named_resources_value)
            if isinstance(named_resources_value, dict)
            else {}
        )
        openapi_value = payload.get("openapi_contract")
        openapi = dict(openapi_value) if isinstance(openapi_value, dict) else {}
        live_before_value = payload.get("live_ea_project_before")
        live_after_value = payload.get("live_ea_project_after")
        live_before = (
            dict(live_before_value) if isinstance(live_before_value, dict) else {}
        )
        live_after = (
            dict(live_after_value) if isinstance(live_after_value, dict) else {}
        )

        def receipt_mapping(name: str) -> dict[str, Any]:
            value = payload.get(name)
            return dict(value) if isinstance(value, dict) else {}

        initial_container_images = receipt_mapping("candidate_container_images_initial")
        final_container_images = receipt_mapping("candidate_container_images_final")
        runtime_projection_initial = receipt_mapping("runtime_projection_initial")
        runtime_projection_final = receipt_mapping("runtime_projection_final")
        runtime_version = receipt_mapping("runtime_version_identity")
        compose_attestation = receipt_mapping("compose_attestation")
        execution_inputs = receipt_mapping("execution_inputs")
        runtime_api_posture = receipt_mapping("runtime_api_posture")
        registry_recovery = receipt_mapping("registry_recovery")
        spatial_projection = receipt_mapping("spatial_handoff")
        spatial_runtime = receipt_mapping("spatial_handoff_runtime")
        spatial_browser_value = spatial_runtime.get("candidate_browser_gate")
        spatial_browser = (
            dict(spatial_browser_value)
            if isinstance(spatial_browser_value, dict)
            else {}
        )
        spatial_browser_package_value = spatial_browser.get("package_binding")
        spatial_browser_package = (
            dict(spatial_browser_package_value)
            if isinstance(spatial_browser_package_value, dict)
            else {}
        )
        candidate_public_tour_manifest_value = spatial_browser_package.get(
            "public_tour_manifest"
        )
        candidate_public_tour_manifest = (
            dict(candidate_public_tour_manifest_value)
            if isinstance(candidate_public_tour_manifest_value, dict)
            else {}
        )
        candidate_public_tour_canonical_sha256 = str(
            candidate_public_tour_manifest.get("canonical_json_sha256") or ""
        )
        fleet_lock_value = locks.get("fleet")
        fleet_lock = (
            dict(fleet_lock_value) if isinstance(fleet_lock_value, dict) else {}
        )

        def openapi_snapshot(name: str) -> dict[str, Any]:
            value = openapi.get(name)
            return dict(value) if isinstance(value, dict) else {}

        live_openapi_before = openapi_snapshot("live_before")
        candidate_openapi = openapi_snapshot("candidate")
        candidate_openapi_public_endpoint = openapi_snapshot(
            "candidate_public_endpoint"
        )
        live_openapi_after = openapi_snapshot("live_after")

        def valid_openapi_snapshot(
            value: Mapping[str, Any],
            *,
            candidate_snapshot: bool = False,
            live_snapshot: bool = False,
        ) -> bool:
            if candidate_snapshot and live_snapshot:
                return False
            expected_fields = set(OPENAPI_EVIDENCE_FIELDS)
            if candidate_snapshot:
                expected_fields.update(
                    {"snapshot_source", "public_docs_config_retired"}
                )
            if live_snapshot:
                expected_fields.update(
                    {
                        "snapshot_source",
                        "public_docs_config_retired",
                        "container_id",
                        "image_id",
                        "started_at",
                        "service",
                        "container_name",
                        "running",
                        "health",
                    }
                )
            return (
                set(value) == expected_fields
                and type(value.get("path_count")) is int
                and int(value["path_count"]) > 0
                and type(value.get("operation_count")) is int
                and int(value["operation_count"]) > 0
                and type(value.get("schema_count")) is int
                and int(value["schema_count"]) >= 0
                and type(value.get("security_scheme_count")) is int
                and int(value["security_scheme_count"]) >= 0
                and SHA256_HEX_PATTERN.fullmatch(
                    str(value.get("path_digest_sha256") or "")
                )
                is not None
                and SHA256_HEX_PATTERN.fullmatch(
                    str(value.get("contract_digest_sha256") or "")
                )
                is not None
                and (
                    not candidate_snapshot
                    or (
                        value.get("snapshot_source")
                        == "candidate_api_container_app.openapi"
                        and value.get("public_docs_config_retired") is True
                    )
                )
                and (
                    not live_snapshot
                    or (
                        value.get("snapshot_source") == "live_api_container_app.openapi"
                        and value.get("public_docs_config_retired") is True
                        and re.fullmatch(
                            r"[0-9a-f]{64}",
                            str(value.get("container_id") or ""),
                        )
                        is not None
                        and IMAGE_ID_PATTERN.fullmatch(str(value.get("image_id") or ""))
                        is not None
                        and bool(str(value.get("started_at") or "").strip())
                        and value.get("service") == API_SERVICE
                        and value.get("container_name") == API_SERVICE
                        and value.get("running") is True
                        and value.get("health") == "healthy"
                    )
                )
            )

        def valid_candidate_openapi_public_endpoint(
            value: Mapping[str, Any],
        ) -> bool:
            security_headers = value.get("security_headers")
            if not isinstance(security_headers, dict) or set(security_headers) != {
                "content_security_policy",
                "x_content_type_options",
                "x_frame_options",
            }:
                return False
            directives: dict[str, tuple[str, ...]] = {}
            for raw_directive in str(
                security_headers.get("content_security_policy") or ""
            ).split(";"):
                parts = raw_directive.strip().split()
                if not parts:
                    continue
                name = parts[0].lower()
                if name in directives:
                    return False
                directives[name] = tuple(parts[1:])
            content_type = value.get("content_type")
            return (
                set(value)
                == {
                    "path",
                    "status",
                    "error_code",
                    "content_type",
                    "media_type",
                    "correlation_header_matches_body",
                    "security_headers",
                    "public_endpoint_retired",
                }
                and value.get("path") == "/openapi.json"
                and type(value.get("status")) is int
                and value.get("status") == 404
                and value.get("error_code") == "not_found"
                and type(content_type) is str
                and 0 < len(content_type) <= MAX_RECEIPT_CONTENT_TYPE_CHARS
                and str(content_type).partition(";")[0].strip().lower()
                == "application/json"
                and value.get("media_type") == "application/json"
                and value.get("correlation_header_matches_body") is True
                and directives.get("frame-ancestors") == ("'none'",)
                and str(security_headers.get("x_content_type_options") or "").lower()
                == "nosniff"
                and str(security_headers.get("x_frame_options") or "").upper() == "DENY"
                and value.get("public_endpoint_retired") is True
            )

        live_containers = live_before.get("containers")
        live_networks = live_before.get("networks")
        live_volumes = live_before.get("volumes")
        live_api_rows = (
            [
                dict(row)
                for row in live_containers
                if isinstance(row, dict)
                and (
                    str(row.get("service") or "") == API_SERVICE
                    or str(row.get("name") or "") == API_SERVICE
                )
            ]
            if isinstance(live_containers, list)
            else []
        )
        expected_named_resources = {
            "containers": sorted(
                [
                    f"{candidate_project}-{service}-1"
                    for service in ("api", "gateway", "postgres", "redis")
                ]
                + [
                    f"{candidate_project}_{service}_1"
                    for service in ("api", "gateway", "postgres", "redis")
                ]
            ),
            "networks": [
                f"{candidate_project}_backend",
                f"{candidate_project}_ingress",
            ],
            "volumes": [
                f"{candidate_project}_artifacts",
                f"{candidate_project}_postgres_data",
                f"{candidate_project}_redis_data",
            ],
        }
        required_smoke_checks = {
            "archive_publication_gate",
            "singular_memorial_alias",
            "source_grounded_narrator_boundary",
            "voice_provider_boundary_blocked",
        }
        first_checks = {
            str(item).strip()
            for item in list(payload.get("first_smoke_checks") or [])
            if str(item).strip()
        }
        second_checks = {
            str(item).strip()
            for item in list(payload.get("second_smoke_checks") or [])
            if str(item).strip()
        }

        image_reference = str(candidate.get("reference") or "")
        image_id = str(candidate.get("image_id") or "")
        container_id_pattern = re.compile(r"^[0-9a-f]{64}$")
        expected_projection_count = payload.get("projection_file_count")
        expected_projection_bytes = payload.get("projection_bytes")
        expected_runtime_mount_roots = [
            "/data/memorial/public",
            "/data/memorial/private",
            "/data/memorial/archive",
            "/data/public_property_tours",
            "/data/release-authority",
        ]
        expected_candidate_env_keys = sorted(
            {
                "DATABASE_URL",
                "EA_API_TOKEN",
                "EA_MANFRED_COMPOSE_PROJECT",
                "EA_MANFRED_COMMIT",
                "EA_MANFRED_DEPLOYMENT_ID",
                "EA_MANFRED_ENV_FILE",
                "EA_MANFRED_HOST_PORT",
                "EA_MANFRED_IMAGE",
                "EA_MANFRED_POSTGRES_PASSWORD",
                "EA_MANFRED_RELEASE_AUTHORITY_ROOT",
                "EA_MANFRED_RELEASE_ROOT",
                "EA_MANFRED_RUNTIME_ROOT",
                "EA_MANFRED_SPATIAL_HANDOFF_INCLUDED",
                "EA_MANFRED_SPATIAL_RELEASE_ROOT",
                "EA_MANFRED_SPATIAL_SHA256",
                "EA_MANFRED_SPATIAL_SLUG",
                "EA_PUBLIC_APP_BASE_URL",
                "EA_SIGNING_SECRET",
            }
        )

        def valid_container_images(value: Mapping[str, Any]) -> bool:
            if set(value) != {
                "api",
                "gateway",
                "prepared_image_id",
                "revision_label",
                "all_match_prepared_image",
            }:
                return False
            api = value.get("api")
            gateway = value.get("gateway")
            if not isinstance(api, dict) or not isinstance(gateway, dict):
                return False
            if set(api) != {"container_id", "image_id"} or set(gateway) != {
                "container_id",
                "image_id",
            }:
                return False
            api_id = str(api.get("container_id") or "")
            gateway_id = str(gateway.get("container_id") or "")
            return (
                container_id_pattern.fullmatch(api_id) is not None
                and container_id_pattern.fullmatch(gateway_id) is not None
                and api_id != gateway_id
                and api.get("image_id") == image_id
                and gateway.get("image_id") == image_id
                and value.get("prepared_image_id") == image_id
                and value.get("revision_label") == source_revision
                and value.get("all_match_prepared_image") is True
            )

        def valid_runtime_projection(value: Mapping[str, Any]) -> bool:
            return (
                set(value)
                == {
                    "schema",
                    "projection_sha256",
                    "file_count",
                    "projection_bytes",
                    "mount_roots",
                    "runtime_bytes_match_prepared_projection",
                }
                and value.get("schema") == "ea.manfred_candidate_runtime_projection.v1"
                and value.get("projection_sha256") == payload.get("projection_sha256")
                and type(value.get("file_count")) is int
                and value.get("file_count") == expected_projection_count
                and type(value.get("projection_bytes")) is int
                and value.get("projection_bytes") == expected_projection_bytes
                and value.get("mount_roots") == expected_runtime_mount_roots
                and value.get("runtime_bytes_match_prepared_projection") is True
            )

        expected_runtime_version = {
            "path": "/version",
            "status": 200,
            "commit_sha": source_revision,
            "body_commit_sha": source_revision,
            "source_revision_header": source_revision,
            "expected_commit_sha": source_revision,
            "oci_image_revision": source_revision,
            "repository": "EA",
            "role": "api",
            "release_authority_state": "clear",
            "release_authority_posture": "authoritative_runtime",
            "release_authority_source": "published_status_artifact",
            "commit_observed_over_http": True,
            "revision_agreement_verified": True,
        }
        compose_relative_path = "deploy/manfred-memorial/docker-compose.candidate.yml"
        expected_compose_path = str((self.root / compose_relative_path).resolve())
        try:
            expected_compose_bytes = Path(expected_compose_path).read_bytes()
        except OSError:
            expected_compose_bytes = None

        def git_blob_oid(content: bytes, *, digest_chars: int) -> str:
            framed = f"blob {len(content)}\0".encode("ascii") + content
            if digest_chars == 40:
                return hashlib.sha1(  # noqa: S324 - Git object identity is SHA-1
                    framed,
                    usedforsecurity=False,
                ).hexdigest()
            if digest_chars == 64:
                return hashlib.sha256(framed).hexdigest()
            return ""

        def valid_compose_attestation(value: Mapping[str, Any]) -> bool:
            blob_oid = str(value.get("git_blob_oid") or "")
            producer_source = Path(str(value.get("canonical_source_path") or ""))
            relative_parts = Path(compose_relative_path).parts
            return (
                set(value)
                == {
                    "canonical_relative_path",
                    "canonical_source_path",
                    "candidate_commit",
                    "git_blob_oid",
                    "sha256",
                    "size_bytes",
                    "canonical_path_enforced",
                    "tracked_blob_bytes_enforced",
                }
                and value.get("canonical_relative_path") == compose_relative_path
                and producer_source.is_absolute()
                and producer_source.parts[-len(relative_parts) :] == relative_parts
                and value.get("candidate_commit") == source_revision
                and len(blob_oid) in {40, 64}
                and blob_oid == blob_oid.lower()
                and all(character in "0123456789abcdef" for character in blob_oid)
                and expected_compose_bytes is not None
                and blob_oid
                == git_blob_oid(expected_compose_bytes, digest_chars=len(blob_oid))
                and SHA256_HEX_PATTERN.fullmatch(str(value.get("sha256") or ""))
                is not None
                and value.get("sha256")
                == hashlib.sha256(expected_compose_bytes).hexdigest()
                and type(value.get("size_bytes")) is int
                and value.get("size_bytes") == len(expected_compose_bytes)
                and len(expected_compose_bytes) > 0
                and value.get("canonical_path_enforced") is True
                and value.get("tracked_blob_bytes_enforced") is True
            )

        def valid_execution_inputs(value: Mapping[str, Any]) -> bool:
            environment_keys = value.get("environment_keys")
            return (
                set(value)
                == {
                    "schema",
                    "compose_sha256",
                    "compose_size_bytes",
                    "compose_git_blob_oid",
                    "environment_sha256",
                    "environment_size_bytes",
                    "environment_keys",
                    "compose_image_id",
                    "compose_image_reference_source",
                    "transport",
                    "required_seals",
                    "all_compose_commands_use_sealed_inputs",
                    "mutable_source_paths_consumed_by_compose",
                    "mutable_image_locator_consumed_by_compose",
                }
                and value.get("schema") == "ea.manfred_candidate_execution_inputs.v1"
                and value.get("compose_sha256") == compose_attestation.get("sha256")
                and value.get("compose_size_bytes")
                == compose_attestation.get("size_bytes")
                and value.get("compose_git_blob_oid")
                == compose_attestation.get("git_blob_oid")
                and SHA256_HEX_PATTERN.fullmatch(
                    str(value.get("environment_sha256") or "")
                )
                is not None
                and type(value.get("environment_size_bytes")) is int
                and int(value.get("environment_size_bytes") or 0) > 0
                and environment_keys == expected_candidate_env_keys
                and value.get("compose_image_id") == image_id
                and value.get("compose_image_reference_source") == "prepared_image_id"
                and value.get("transport") == "sealed_memfd"
                and value.get("required_seals") == ["grow", "seal", "shrink", "write"]
                and value.get("all_compose_commands_use_sealed_inputs") is True
                and value.get("mutable_source_paths_consumed_by_compose") is False
                and value.get("mutable_image_locator_consumed_by_compose") is False
            )

        def valid_runtime_mounts(value: object) -> bool:
            if not isinstance(value, list) or len(value) != 9:
                return False
            rows: dict[str, dict[str, Any]] = {}
            for raw_row in value:
                if not isinstance(raw_row, dict) or set(raw_row) != {
                    "destination",
                    "identity",
                    "read_only",
                    "type",
                }:
                    return False
                destination = str(raw_row.get("destination") or "")
                if not destination or destination in rows:
                    return False
                rows[destination] = dict(raw_row)
            expected_read_only = {
                "/data/memorial/public": expected_data_root / "public_memorials",
                "/data/memorial/private": expected_data_root
                / "private_memorial_profiles",
                "/data/memorial/archive": expected_data_root / "memorial_archive",
                "/data/public_property_tours": expected_data_root
                / "public_property_tours",
                "/data/release-authority": expected_data_root / "release-authority",
            }
            for destination, source in expected_read_only.items():
                if rows.get(destination) != {
                    "destination": destination,
                    "identity": str(source.resolve()),
                    "read_only": True,
                    "type": "bind",
                }:
                    return False
            mutable_names = {
                "/data/memorial/public-contributions": "public-contributions",
                "/data/memorial/private-contributions": "private-contributions",
                "/data/memorial/state": "state",
            }
            mutable_parents: set[str] = set()
            for destination, basename in mutable_names.items():
                row = rows.get(destination, {})
                identity = Path(str(row.get("identity") or ""))
                if (
                    row.get("destination") != destination
                    or row.get("type") != "bind"
                    or row.get("read_only") is not False
                    or not identity.is_absolute()
                    or identity.name != basename
                ):
                    return False
                mutable_parents.add(str(identity.parent))
            return len(mutable_parents) == 1 and rows.get("/data/artifacts") == {
                "destination": "/data/artifacts",
                "identity": f"{candidate_project}_artifacts",
                "read_only": False,
                "type": "volume",
            }

        def valid_runtime_posture(value: Mapping[str, Any]) -> bool:
            environment_keys = value.get("environment_keys")
            required_keys = {
                *expected_candidate_env_keys,
                "EA_ALLOW_LOOPBACK_NO_AUTH",
                "EA_DEPLOY_COMMIT_SHA",
                "EA_DEPLOY_PUBLIC_ORIGIN",
                "EA_ENABLE_PUBLIC_MEMORIALS",
                "EA_ENABLE_PUBLIC_MEMORIAL_OPERATOR_SURFACES",
                "EA_ENABLE_PUBLIC_TOURS",
                "EA_PUBLIC_MEMORIAL_RATE_BACKEND",
                "EA_PUBLIC_MEMORIAL_REDIS_URL",
                "EA_RELEASE_AUTHORITY_STATUS_PATH",
                "EA_SOURCE_REVISION",
                "EA_STORAGE_BACKEND",
                "EA_STORAGE_FALLBACK_ALLOWED",
                "EA_TRUST_PROXY_HEADERS",
            }
            return (
                set(value)
                == {
                    "schema",
                    "api_container_id",
                    "image_id",
                    "environment_sha256",
                    "execution_environment_sha256",
                    "environment_keys",
                    "environment_exact",
                    "provider_credentials_present",
                    "mounts",
                    "mounts_exact",
                    "tmpfs_exact",
                    "networks",
                    "network_exact",
                    "ingress_attached",
                    "read_only_rootfs",
                    "all_capabilities_dropped",
                    "no_new_privileges",
                    "runtime_user",
                    "running_and_healthy",
                }
                and value.get("schema") == "ea.manfred_candidate_api_runtime_posture.v1"
                and value.get("api_container_id")
                == dict(container_images.get("api") or {}).get("container_id")
                and value.get("image_id") == image_id
                and SHA256_HEX_PATTERN.fullmatch(
                    str(value.get("environment_sha256") or "")
                )
                is not None
                and value.get("execution_environment_sha256")
                == execution_inputs.get("environment_sha256")
                and isinstance(environment_keys, list)
                and environment_keys == sorted(set(environment_keys))
                and required_keys <= set(environment_keys)
                and value.get("environment_exact") is True
                and value.get("provider_credentials_present") is False
                and valid_runtime_mounts(value.get("mounts"))
                and value.get("mounts_exact") is True
                and value.get("tmpfs_exact") is True
                and value.get("networks") == [f"{candidate_project}_backend"]
                and value.get("network_exact") is True
                and value.get("ingress_attached") is False
                and value.get("read_only_rootfs") is True
                and value.get("all_capabilities_dropped") is True
                and value.get("no_new_privileges") is True
                and value.get("runtime_user") == "10001:10001"
                and value.get("running_and_healthy") is True
            )

        def valid_registry_recovery(value: Mapping[str, Any]) -> bool:
            if set(value) != {
                "state_before_launch",
                "crash_intent_reconciled",
                "pending_contribution_reconciled",
                "existing_receipt_resumed",
                "interrupted_receipt_publication_completed",
            }:
                return False
            state = value.get("state_before_launch")
            return (
                state in {"absent", "pending_only"}
                and value.get("crash_intent_reconciled") is (state == "pending_only")
                and type(value.get("pending_contribution_reconciled")) is bool
                and (
                    state == "pending_only"
                    or value.get("pending_contribution_reconciled") is False
                )
                and value.get("existing_receipt_resumed") is False
                and value.get("interrupted_receipt_publication_completed") is False
            )

        spatial_slug = str(spatial_projection.get("slug") or "")
        spatial_viewer_relpath = str(spatial_projection.get("viewer_relpath") or "")
        spatial_proof_relpath = str(spatial_projection.get("proof_relpath") or "")
        spatial_package_sha256 = str(
            spatial_projection.get("upstream_package_sha256") or ""
        )
        spatial_route_labels = spatial_projection.get("route_labels")
        spatial_root = expected_data_root / "public_property_tours"
        spatial_bundle_root = spatial_root / REQUIRED_CONTROL_TOUR_SLUG
        try:
            (
                observed_spatial_projection_sha256,
                observed_spatial_projection_files,
            ) = _candidate_projection_tree_digest(spatial_root)
            observed_spatial_snapshot = _spatial_tree_snapshot(
                spatial_bundle_root,
                require_sanitized_modes=False,
            )
        except (OSError, ValueError):
            observed_spatial_projection_sha256 = ""
            observed_spatial_projection_files = []
            observed_spatial_snapshot = {}
        observed_spatial_projection_bytes = sum(
            int(row.get("size_bytes") or 0)
            for row in observed_spatial_projection_files
            if isinstance(row, dict)
        )
        observed_spatial_local_files = [
            {
                "path": relpath,
                "sha256": hashlib.sha256(content).hexdigest(),
                "size_bytes": len(content),
            }
            for relpath, content in sorted(observed_spatial_snapshot.items())
        ]
        observed_spatial_allowed_files = {
            str(row["path"]): {
                "sha256": str(row["sha256"]),
                "size_bytes": int(row["size_bytes"]),
            }
            for row in observed_spatial_local_files
        }
        observed_spatial_package_sha256 = (
            _spatial_package_sha256(observed_spatial_snapshot)
            if observed_spatial_snapshot
            else ""
        )
        observed_spatial_tour_sha256 = (
            hashlib.sha256(observed_spatial_snapshot["tour.json"]).hexdigest()
            if "tour.json" in observed_spatial_snapshot
            else ""
        )
        try:
            observed_spatial_tour_canonical_sha256 = _canonical_json_sha256(
                json.loads(observed_spatial_snapshot["tour.json"])
            )
        except (KeyError, TypeError, ValueError):
            observed_spatial_tour_canonical_sha256 = ""

        def passing_spatial_verifier(value: object) -> bool:
            return (
                isinstance(value, dict)
                and value.get("pass") is True
                and isinstance(value.get("checks"), dict)
                and dict(value["checks"]).get("binding_count") == 5
            )

        def valid_spatial_projection(value: Mapping[str, Any]) -> bool:
            asset_paths = value.get("asset_paths")
            expected_spatial_files = (
                {
                    f"{spatial_slug}/tour.json",
                    *(
                        f"{spatial_slug}/{asset_path}"
                        for asset_path in asset_paths
                        if isinstance(asset_path, str)
                    ),
                }
                if isinstance(asset_paths, list)
                else set()
            )
            return (
                set(value)
                == {
                    "included",
                    "slug",
                    "release_root",
                    "projection_sha256",
                    "file_count",
                    "projection_bytes",
                    "receipt_path",
                    "receipt_sha256",
                    "projection_tree_revalidated",
                    "ea_public_activation_authority",
                    "asset_paths",
                    "viewer_relpath",
                    "proof_relpath",
                    "route_labels",
                    "upstream_publication_authority_sha256",
                    "upstream_package_sha256",
                    "upstream_tour_manifest_sha256",
                    "pre_authority_manifest_canonical_sha256",
                    "upstream_public_activation_authority",
                    "local_release_verifier",
                }
                and value.get("included") is True
                and spatial_slug == REQUIRED_CONTROL_TOUR_SLUG
                and value.get("release_root")
                == str((expected_data_root / "public_property_tours").resolve())
                and value.get("projection_sha256") == observed_spatial_projection_sha256
                and value.get("file_count")
                == len(observed_spatial_projection_files)
                == 6
                and value.get("projection_bytes") == observed_spatial_projection_bytes
                and observed_spatial_projection_bytes > 0
                and type(value.get("receipt_path")) is str
                and Path(str(value["receipt_path"])).is_absolute()
                and value.get("projection_tree_revalidated") is True
                and value.get("ea_public_activation_authority") is False
                and isinstance(asset_paths, list)
                and len(asset_paths) == 5
                and all(isinstance(asset_path, str) for asset_path in asset_paths)
                and len(set(asset_paths)) == 5
                and set(asset_paths)
                == set(PUBLIC_SPATIAL_ALLOWED_FILE_RELPATHS) - {"tour.json"}
                and set(observed_spatial_snapshot) == {"tour.json", *asset_paths}
                and {
                    str(row.get("path") or "")
                    for row in observed_spatial_projection_files
                    if isinstance(row, dict)
                }
                == expected_spatial_files
                and spatial_viewer_relpath == "generated-reconstruction/viewer.html"
                and spatial_proof_relpath
                == "generated-reconstruction/reconstruction.json"
                and SHA256_HEX_PATTERN.fullmatch(observed_spatial_tour_canonical_sha256)
                is not None
                and isinstance(spatial_route_labels, list)
                and len(spatial_route_labels) == 9
                and all(
                    isinstance(route_label, str)
                    and route_label
                    and route_label == route_label.strip()
                    for route_label in spatial_route_labels
                )
                and len(set(spatial_route_labels)) == 9
                and all(
                    SHA256_HEX_PATTERN.fullmatch(str(value.get(name) or "")) is not None
                    for name in (
                        "receipt_sha256",
                        "upstream_publication_authority_sha256",
                        "upstream_package_sha256",
                        "upstream_tour_manifest_sha256",
                        "pre_authority_manifest_canonical_sha256",
                    )
                )
                and value.get("upstream_publication_authority_sha256")
                == PROPERTY_AUTHORITY_SHA256
                and value.get("upstream_package_sha256")
                == observed_spatial_package_sha256
                and value.get("upstream_tour_manifest_sha256")
                == observed_spatial_tour_sha256
                == PROPERTY_TOUR_SHA256
                and value.get("pre_authority_manifest_canonical_sha256")
                == PROPERTY_PRE_AUTHORITY_SHA256
                and value.get("upstream_public_activation_authority") is True
                and passing_spatial_verifier(value.get("local_release_verifier"))
            )

        def valid_spatial_browser(value: object) -> bool:
            if not isinstance(value, dict):
                return False
            gateway_id = dict(container_images.get("gateway") or {}).get("container_id")
            try:
                validate_spatial_candidate_browser_receipt(
                    value,
                    base_url=f"http://127.0.0.1:{candidate_port}",
                    slug=spatial_slug,
                    viewer_relpath=spatial_viewer_relpath,
                    route_labels=list(spatial_route_labels or []),
                    candidate_commit=source_revision,
                    oci_image_id=image_id,
                    serving_container_id=str(gateway_id or ""),
                    package_sha256=spatial_package_sha256,
                )
            except (RuntimeError, TypeError, ValueError):
                return False
            version = value.get("candidate_version")
            oci_image = value.get("candidate_oci_image")
            serving = value.get("serving_container")
            package = value.get("package_binding")
            public_tour_manifest = (
                package.get("public_tour_manifest")
                if isinstance(package, dict)
                else None
            )
            return (
                version == expected_runtime_version
                and isinstance(oci_image, dict)
                and oci_image
                == {
                    "image_id": image_id,
                    "oci_image_revision": source_revision,
                    "revision_source": "docker_image_inspect_by_immutable_id",
                    "immutable_image_id_verified": True,
                }
                and isinstance(serving, dict)
                and serving.get("container_id") == gateway_id
                and serving.get("image_id") == image_id
                and serving.get("compose_project") == candidate_project
                and serving.get("compose_service") == "gateway"
                and serving.get("running") is True
                and serving.get("container_port") == 18090
                and serving.get("host_ip") == "127.0.0.1"
                and serving.get("host_port") == candidate_port
                and serving.get("exact_loopback_publication_verified") is True
                and serving.get("inspection_source")
                == "docker_container_inspect_by_immutable_id"
                and value.get("package_sha256") == spatial_package_sha256
                and isinstance(package, dict)
                and package.get("package_sha256") == spatial_package_sha256
                and package.get("local_files") == observed_spatial_local_files
                and package.get("tour_manifest_sha256") == observed_spatial_tour_sha256
                and isinstance(public_tour_manifest, dict)
                and public_tour_manifest == candidate_public_tour_manifest
                and SHA256_HEX_PATTERN.fullmatch(candidate_public_tour_canonical_sha256)
                is not None
                and public_tour_manifest.get("source_revision") == source_revision
                and public_tour_manifest.get("source_revision_verified") is True
                and public_tour_manifest.get("slug") == spatial_slug
                and public_tour_manifest.get("generated_viewer_url")
                == (f"/tours/viewer/{spatial_slug}/{spatial_viewer_relpath}")
                and public_tour_manifest.get("public_projection_verified") is True
            )

        def valid_spatial_runtime(value: Mapping[str, Any]) -> bool:
            routes = value.get("routes")
            if not isinstance(routes, dict):
                return False
            quoted_slug = urllib.parse.quote(spatial_slug, safe="")
            expected_paths = {
                "html": f"/tours/{quoted_slug}",
                "json": f"/tours/{quoted_slug}.json",
                "viewer": (
                    f"/tours/viewer/{quoted_slug}/"
                    f"{urllib.parse.quote(spatial_viewer_relpath, safe='/')}"
                ),
                "proof_only": (
                    f"/tours/viewer/{quoted_slug}/"
                    f"{urllib.parse.quote(spatial_proof_relpath, safe='/')}"
                ),
            }
            if set(routes) != {
                f"{label}_{method}"
                for label in expected_paths
                for method in ("get", "head")
            }:
                return False
            for label, path in expected_paths.items():
                expected_status = 404 if label == "proof_only" else 200
                for method in ("get", "head"):
                    row = routes.get(f"{label}_{method}")
                    if (
                        not isinstance(row, dict)
                        or set(row) != {"path", "status", "content_type"}
                        or row.get("path") != path
                        or row.get("status") != expected_status
                        or not str(row.get("content_type") or "")
                    ):
                        return False
            return (
                set(value)
                == {
                    "included",
                    "routes_required",
                    "slug",
                    "routes",
                    "generated_viewer_release_verifier",
                    "candidate_browser_gate",
                    "html_json_viewer_200",
                    "proof_only_404",
                    "ea_public_activation_authority",
                    "upstream_public_activation_authority",
                }
                and value.get("included") is True
                and value.get("routes_required") is True
                and value.get("slug") == spatial_slug
                and passing_spatial_verifier(
                    value.get("generated_viewer_release_verifier")
                )
                and valid_spatial_browser(value.get("candidate_browser_gate"))
                and value.get("html_json_viewer_200") is True
                and value.get("proof_only_404") is True
                and value.get("ea_public_activation_authority") is False
                and value.get("upstream_public_activation_authority") is True
            )

        if (
            str(payload.get("schema") or "")
            != "ea.manfred_memorial_candidate_runtime.v5"
            or str(payload.get("status") or "").lower() != "pass"
            or str(payload.get("image") or "") != str(candidate.get("reference") or "")
            or str(payload.get("image_id") or "")
            != str(candidate.get("image_id") or "")
            or str(payload.get("image_source_revision") or "") != source_revision
            or locator
            != {
                "locator": image_reference,
                "resolved_image_id": image_id,
                "revision_label": source_revision,
                "used_for_attestation_only": True,
                "consumed_by_compose": False,
            }
            or payload.get("compose_uses_immutable_image_id") is not True
            or str(payload.get("runtime_source_revision") or "") != source_revision
            or payload.get("runtime_revision_matches_image") is not True
            or str(payload.get("projection_commit") or "") != source_revision
            or str(payload.get("prepared_image_locator") or "")
            != str(candidate.get("reference") or "")
            or str(payload.get("prepared_image_id") or "")
            != str(candidate.get("image_id") or "")
            or payload.get("projection_tree_revalidated") is not True
            or type(expected_projection_count) is not int
            or int(expected_projection_count) < 0
            or type(expected_projection_bytes) is not int
            or int(expected_projection_bytes) < 0
            or not isinstance(payload.get("projection_files"), list)
            or payload.get("live_ea_api_unchanged") is not True
            or payload.get("live_ea_project_unchanged") is not True
            or payload.get("provider_calls_performed") is not False
            or str(payload.get("release_id") or "") != expected_data_root.name
            or candidate_release_root != expected_data_root
            or SHA256_HEX_PATTERN.fullmatch(str(payload.get("projection_sha256") or ""))
            is None
            or not candidate_project.startswith("ea-manfred-candidate-")
            or len(candidate_project) > 63
            or len(candidate_project_suffix) < 8
            or re.fullmatch(r"[a-z0-9][a-z0-9-]*", candidate_project_suffix) is None
            or payload.get("compose_project_isolated") is not True
            or payload.get("compose_environment_bound_to_candidate_env") is not True
            or type(candidate_port) is not int
            or not 1024 <= int(candidate_port) <= 65535
            or candidate_preflight.get("project") != candidate_project
            or type(candidate_preflight.get("containers")) is not int
            or candidate_preflight["containers"] != 0
            or type(candidate_preflight.get("networks")) is not int
            or candidate_preflight["networks"] != 0
            or type(candidate_preflight.get("volumes")) is not int
            or candidate_preflight["volumes"] != 0
            or candidate_preflight.get("named_container_collisions") != []
            or candidate_preflight.get("named_network_collisions") != []
            or candidate_preflight.get("named_volume_collisions") != []
            or candidate_preflight.get("loopback_host") != "127.0.0.1"
            or candidate_preflight.get("loopback_port") != candidate_port
            or candidate_preflight.get("loopback_port_free_before_start") is not True
            or project_lock.get("scope") != "compose_project"
            or project_lock.get("project") != candidate_project
            or project_lock.get("held_through_candidate_proof") is not True
            or port_lock.get("scope") != "host_loopback_port"
            or port_lock.get("port") != candidate_port
            or port_lock.get("held_through_candidate_proof") is not True
            or top_project_lock != project_lock
            or top_port_lock != port_lock
            or fleet_lock
            != {
                "scope": "manfred_candidate_fleet",
                "lock_file": "ea-manfred-candidate-fleet.lock",
                "exclusive": True,
                "nonblocking": True,
                "held_through_candidate_proof": True,
            }
            or not valid_container_images(initial_container_images)
            or not valid_container_images(final_container_images)
            or not valid_container_images(container_images)
            or initial_container_images != final_container_images
            or container_images != final_container_images
            or payload.get("candidate_container_image_identity_stable") is not True
            or str(container_images.get("prepared_image_id") or "")
            != str(candidate.get("image_id") or "")
            or str(container_images.get("revision_label") or "") != source_revision
            or container_images.get("all_match_prepared_image") is not True
            or not str(candidate_api_image.get("container_id") or "").strip()
            or str(candidate_api_image.get("image_id") or "")
            != str(candidate.get("image_id") or "")
            or not str(candidate_gateway_image.get("container_id") or "").strip()
            or str(candidate_gateway_image.get("image_id") or "")
            != str(candidate.get("image_id") or "")
            or candidate_api_image.get("container_id")
            == candidate_gateway_image.get("container_id")
            or not valid_runtime_projection(runtime_projection_initial)
            or not valid_runtime_projection(runtime_projection_final)
            or runtime_projection_initial != runtime_projection_final
            or payload.get("runtime_projection_identity_stable") is not True
            or runtime_version != expected_runtime_version
            or str(payload.get("runtime_authority_commit") or "") != source_revision
            or not valid_compose_attestation(compose_attestation)
            or not valid_execution_inputs(execution_inputs)
            or not valid_runtime_posture(runtime_api_posture)
            or not valid_registry_recovery(registry_recovery)
            or not valid_spatial_projection(spatial_projection)
            or not valid_spatial_runtime(spatial_runtime)
            or named_resources != expected_named_resources
            or payload.get("api_network_internal") is not True
            or payload.get("gateway_has_runtime_secrets") is not False
            or payload.get("provider_credentials_present") is not False
            or not str(payload.get("candidate_api_container_id") or "").strip()
            or payload.get("candidate_api_container_id")
            != candidate_api_image.get("container_id")
            or payload.get("candidate_left_running") is not True
            or payload.get("promotion_authority") is not False
            or str(browser.get("status") or "").lower() != "pass"
            or not _has_exact_zero_browser_counts(browser)
            or not required_smoke_checks <= first_checks
            or not required_smoke_checks <= second_checks
            or openapi.get("retirement_policy_id") != OPENAPI_RETIREMENT_POLICY_ID
            or openapi.get("retirement_allowed_operations")
            != list(OPENAPI_RETIREMENT_ALLOWED_OPERATIONS)
            or openapi.get("retired_operations")
            != list(OPENAPI_RETIREMENT_ALLOWED_OPERATIONS)
            or type(openapi.get("retired_operation_count")) is not int
            or openapi["retired_operation_count"]
            != len(OPENAPI_RETIREMENT_ALLOWED_OPERATIONS)
            or openapi.get("retirement_policy_exact_match") is not True
            or openapi.get("compatible_evolution_policy_id")
            != OPENAPI_COMPATIBLE_EVOLUTION_POLICY_ID
            or openapi.get("compatible_evolution_allowed_operations")
            != list(OPENAPI_COMPATIBLE_EVOLUTION_ALLOWED_OPERATIONS)
            or not isinstance(openapi.get("compatible_evolved_operations"), list)
            or any(
                type(operation) is not str
                for operation in openapi["compatible_evolved_operations"]
            )
            or openapi.get("compatible_evolved_operations")
            != sorted(set(openapi["compatible_evolved_operations"]))
            or any(
                operation not in OPENAPI_COMPATIBLE_EVOLUTION_ALLOWED_OPERATIONS
                for operation in openapi["compatible_evolved_operations"]
            )
            or type(openapi.get("compatible_evolved_operation_count")) is not int
            or openapi.get("compatible_evolved_operation_count")
            != len(openapi["compatible_evolved_operations"])
            or openapi.get("compatible_evolution_policy_exact_match") is not True
            or openapi.get("candidate_preserves_live_contract") is not True
            or type(openapi.get("missing_or_changed_operation_count")) is not int
            or openapi["missing_or_changed_operation_count"] != 0
            or type(openapi.get("missing_or_changed_schema_count")) is not int
            or openapi["missing_or_changed_schema_count"] != 0
            or type(openapi.get("missing_or_changed_security_scheme_count")) is not int
            or openapi["missing_or_changed_security_scheme_count"] != 0
            or not valid_openapi_snapshot(live_openapi_before, live_snapshot=True)
            or not valid_openapi_snapshot(candidate_openapi, candidate_snapshot=True)
            or not valid_candidate_openapi_public_endpoint(
                candidate_openapi_public_endpoint
            )
            or not valid_openapi_snapshot(live_openapi_after, live_snapshot=True)
            or live_openapi_before != live_openapi_after
            or int(candidate_openapi.get("path_count") or 0)
            < max(
                0,
                int(live_openapi_before.get("path_count") or 0)
                - len(OPENAPI_RETIREMENT_ALLOWED_OPERATIONS),
            )
            or int(candidate_openapi.get("operation_count") or 0)
            < max(
                0,
                int(live_openapi_before.get("operation_count") or 0)
                - len(OPENAPI_RETIREMENT_ALLOWED_OPERATIONS),
            )
            or int(candidate_openapi.get("schema_count") or 0)
            < int(live_openapi_before.get("schema_count") or 0)
            or int(candidate_openapi.get("security_scheme_count") or 0)
            < int(live_openapi_before.get("security_scheme_count") or 0)
            or live_before.get("project") != PROJECT_NAME
            or live_before != live_after
            or not isinstance(live_containers, list)
            or not isinstance(live_networks, list)
            or not isinstance(live_volumes, list)
            or any(not isinstance(row, dict) for row in live_containers)
            or any(not isinstance(row, dict) for row in live_networks)
            or any(not isinstance(row, dict) for row in live_volumes)
            or len(live_api_rows) != 1
            or payload.get("live_ea_api") != live_api_rows[0]
            or live_api_rows[0].get("running") is not True
            or live_api_rows[0].get("health") != "healthy"
            or payload.get("live_ea_api_unchanged") is not True
            or payload.get("live_ea_project_unchanged") is not True
        ):
            raise DeployError("memorial_candidate_receipt_contract_invalid")
        try:
            projection_sha256, projection_files = _candidate_projection_tree_digest(
                expected_data_root
            )
        except (OSError, ValueError) as exc:
            raise DeployError("memorial_candidate_projection_unverifiable") from exc
        projection_bytes = sum(int(item["size_bytes"]) for item in projection_files)
        if (
            projection_sha256 != str(payload.get("projection_sha256") or "")
            or payload.get("projection_files") != projection_files
            or expected_projection_count != len(projection_files)
            or expected_projection_bytes != projection_bytes
        ):
            raise DeployError("memorial_candidate_projection_digest_mismatch")
        evidence = {
            "path": str(path),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "schema": "ea.manfred_memorial_candidate_runtime.v5",
            "status": "pass",
            "image": str(candidate.get("reference") or ""),
            "image_id": str(candidate.get("image_id") or ""),
            "source_revision": source_revision,
            "release_root": str(candidate_release_root),
            "runtime_revision_matches_image": True,
            "image_locator_revalidated": True,
            "live_ea_unchanged": True,
            "provider_calls_performed": False,
            "projection": {
                "release_id": expected_data_root.name,
                "release_root": str(expected_data_root),
                "commit": source_revision,
                "prepared_image_id": str(candidate.get("image_id") or ""),
                "projection_sha256": projection_sha256,
                "file_count": len(projection_files),
                "projection_bytes": projection_bytes,
                "tree_revalidated": True,
            },
            "compose_project": candidate_project,
            "candidate_port": candidate_port,
            "candidate_preflight_clean": True,
            "locks": {"project_held": True, "port_held": True},
            "candidate_container_images": {
                "api_image_id": str(candidate.get("image_id") or ""),
                "gateway_image_id": str(candidate.get("image_id") or ""),
                "all_match_prepared_image": True,
                "identity_stable": True,
            },
            "runtime_identity": {
                "source_revision": source_revision,
                "authority_commit": source_revision,
                "oci_image_revision": source_revision,
                "revision_agreement_verified": True,
            },
            "execution_inputs": {
                "schema": "ea.manfred_candidate_execution_inputs.v1",
                "compose_sha256": str(execution_inputs["compose_sha256"]),
                "compose_size_bytes": int(execution_inputs["compose_size_bytes"]),
                "environment_sha256": str(execution_inputs["environment_sha256"]),
                "environment_size_bytes": int(
                    execution_inputs["environment_size_bytes"]
                ),
                "compose_image_id": image_id,
                "sealed": True,
            },
            "runtime_posture": {
                "schema": "ea.manfred_candidate_api_runtime_posture.v1",
                "environment_sha256": str(runtime_api_posture["environment_sha256"]),
                "mount_count": len(list(runtime_api_posture["mounts"])),
                "network": f"{candidate_project}_backend",
                "hardened": True,
            },
            "registry_recovery": {
                "state_before_launch": str(registry_recovery["state_before_launch"]),
                "safe": True,
            },
            "spatial_handoff": {
                "slug": spatial_slug,
                "route_count": 8,
                "html_json_viewer_200": True,
                "proof_only_404": True,
                "release_verifier_pass": True,
                "browser_schema": "ea.manfred_spatial_candidate_browser.v5",
                "browser_pass": True,
                "identity_bound": True,
                "package_sha256": spatial_package_sha256,
                "allowed_files": observed_spatial_allowed_files,
                "viewer_relpath": spatial_viewer_relpath,
                "proof_relpath": spatial_proof_relpath,
                "tour_manifest_canonical_sha256": (
                    candidate_public_tour_canonical_sha256
                ),
                "property_artifact_commit": PROPERTY_ARTIFACT_COMMIT,
                "upstream_publication_authority_sha256": (PROPERTY_AUTHORITY_SHA256),
                "upstream_tour_manifest_sha256": PROPERTY_TOUR_SHA256,
                "pre_authority_manifest_canonical_sha256": (
                    PROPERTY_PRE_AUTHORITY_SHA256
                ),
                "upstream_public_activation_authority": True,
                "ea_public_activation_authority": False,
                "provider_calls_performed": False,
            },
            "live_ea": {
                "snapshot_sha256": _canonical_json_sha256(live_before),
                "api_sha256": _canonical_json_sha256(live_api_rows[0]),
                "container_count": len(live_containers),
                "network_count": len(live_networks),
                "volume_count": len(live_volumes),
                "unchanged": True,
            },
            "openapi": {
                "live": live_openapi_before,
                "candidate": candidate_openapi,
                "retirement_policy_id": OPENAPI_RETIREMENT_POLICY_ID,
                "retirement_allowed_operations": list(
                    OPENAPI_RETIREMENT_ALLOWED_OPERATIONS
                ),
                "retired_operations": list(OPENAPI_RETIREMENT_ALLOWED_OPERATIONS),
                "retired_operation_count": len(OPENAPI_RETIREMENT_ALLOWED_OPERATIONS),
                "retirement_policy_exact_match": True,
                "compatible_evolution_policy_id": (
                    OPENAPI_COMPATIBLE_EVOLUTION_POLICY_ID
                ),
                "compatible_evolution_allowed_operations": list(
                    OPENAPI_COMPATIBLE_EVOLUTION_ALLOWED_OPERATIONS
                ),
                "compatible_evolved_operations": list(
                    openapi["compatible_evolved_operations"]
                ),
                "compatible_evolved_operation_count": int(
                    openapi["compatible_evolved_operation_count"]
                ),
                "compatible_evolution_policy_exact_match": True,
                "candidate_public_openapi_retired": True,
                "candidate_preserves_live_contract": True,
                "missing_or_changed_operation_count": 0,
                "missing_or_changed_schema_count": 0,
                "missing_or_changed_security_scheme_count": 0,
            },
            "browser": {
                "status": "pass",
                "automatic_provider_requests": 0,
                "automatic_websockets": 0,
                "external_requests": 0,
                "failed_requests": 0,
                "page_errors": 0,
                "http_errors": 0,
            },
        }
        self.receipt["candidate_promotion_evidence"] = evidence
        self._record_check("candidate_promotion_evidence", "pass")
        return evidence

    def _release_source_metadata(self) -> dict[str, str]:
        self.durable_root_check(self.root)
        branch_result = self._run(
            ["git", "symbolic-ref", "--quiet", "--short", "HEAD"], check=False
        )
        branch = branch_result.stdout.strip()
        if branch_result.returncode != 0 or not branch or branch == "HEAD":
            raise DeployError("release_branch_detached")
        upstream_result = self._run(
            [
                "git",
                "rev-parse",
                "--abbrev-ref",
                "--symbolic-full-name",
                "@{u}",
            ],
            check=False,
        )
        upstream = upstream_result.stdout.strip()
        if upstream_result.returncode != 0 or not upstream or upstream == "HEAD":
            raise DeployError("release_branch_upstream_missing")
        source_revision = self._git_head()
        metadata = {
            "branch": branch,
            "upstream": upstream,
            "source_revision": source_revision,
            "release_root": str(self.root),
        }
        self.receipt["release_source"] = metadata
        self._write_receipt()
        return metadata

    @staticmethod
    def _sanitized_previous_api(previous: Mapping[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in previous.items()
            if key
            not in {
                "mount_identities",
                "noncompose_labels",
                "rollback_capsule_document",
                "rollback_environment",
            }
        }

    def _verify_forward_api(
        self,
        *,
        candidate: Mapping[str, Any],
        source_revision: str,
        expected_mounts: Sequence[Mapping[str, object]],
        expected_projection: Mapping[str, Any],
    ) -> dict[str, Any]:
        inspection = self._inspect_container(API_SERVICE)
        self._require_compose_identity(
            inspection, service=API_SERVICE, reason_prefix="deployed_api"
        )
        topology = self._compose_topology(inspection, reason_prefix="deployed_api")
        expected_files = [
            str((self.root / filename).resolve())
            for filename in self.target_compose_files
        ]
        if topology["working_dir"] != str(self.root):
            raise DeployError("deployed_api_working_dir_mismatch")
        if topology["compose_config_files"] != expected_files:
            raise DeployError("deployed_api_compose_topology_mismatch")
        if self.target_compose_environment_files:
            labels = dict(dict(inspection.get("Config") or {}).get("Labels") or {})
            expected_environment_label = ",".join(self.target_compose_environment_files)
            if (
                str(labels.get("com.docker.compose.project.environment_file") or "")
                != expected_environment_label
            ):
                raise DeployError("deployed_api_compose_environment_mismatch")
        image_id = str(inspection.get("Image") or "").strip()
        if image_id != str(candidate.get("image_id") or ""):
            raise DeployError("deployed_api_image_mismatch")
        config = dict(inspection.get("Config") or {})
        if str(config.get("Image") or "").strip() != str(
            candidate.get("reference") or ""
        ):
            raise DeployError("deployed_api_image_reference_mismatch")
        container_env = {
            str(item).split("=", 1)[0]: str(item).split("=", 1)[1]
            for item in list(config.get("Env") or [])
            if "=" in str(item)
        }
        if container_env.get("EA_SOURCE_REVISION") != source_revision:
            raise DeployError("deployed_api_source_revision_env_mismatch")
        mount_identities = _mount_identities(inspection)
        normalized_expected_mounts = [dict(item) for item in expected_mounts]
        if not normalized_expected_mounts:
            raise DeployError("deployed_api_expected_mounts_missing")
        if mount_identities != normalized_expected_mounts:
            raise DeployError("deployed_api_source_mounts_mismatch")
        memorial_data_root = self._configured_memorial_data_root()
        source_mount_destinations: list[str] = []
        for item in normalized_expected_mounts:
            if str(item["type"]) != "bind":
                continue
            source = Path(str(item["source"])).resolve()
            if (
                source == memorial_data_root
                or source == self.root
                or self.root in source.parents
            ):
                source_mount_destinations.append(str(item["destination"]))
        mounted_projection = self._mounted_projection_digest(expected_projection)
        if mounted_projection != {
            "projection_sha256": str(
                expected_projection.get("projection_sha256") or ""
            ),
            "file_count": expected_projection.get("file_count"),
            "projection_bytes": expected_projection.get("projection_bytes"),
        }:
            raise DeployError("deployed_api_projection_digest_mismatch")
        return {
            "image_id": image_id,
            "image_reference": str(candidate.get("reference") or ""),
            "working_dir": topology["working_dir"],
            "compose_config_files": topology["compose_config_files"],
            "mount_identity_sha256": _identity_digest(mount_identities),
            "mount_identity_count": len(mount_identities),
            "matches_rendered_compose_mounts": True,
            "source_mount_destinations": sorted(source_mount_destinations),
            "source_revision": source_revision,
            "mounted_projection": mounted_projection,
            **_container_runtime_config_digests(inspection),
        }

    def _mounted_projection_digest(
        self, expected_projection: Mapping[str, Any]
    ) -> dict[str, Any]:
        expected_file_count = expected_projection.get("file_count")
        expected_projection_bytes = expected_projection.get("projection_bytes")
        if (
            type(expected_file_count) is not int
            or int(expected_file_count) < 0
            or type(expected_projection_bytes) is not int
            or int(expected_projection_bytes) < 0
        ):
            raise DeployError("deployed_api_projection_expectation_invalid")
        completed = self._run(
            [
                "/usr/bin/timeout",
                "--signal=KILL",
                "30s",
                "docker",
                "exec",
                API_SERVICE,
                "python3",
                "-c",
                CONTAINER_PROJECTION_DIGEST_SCRIPT,
                "/data/memorial_data",
                str(expected_file_count),
                str(expected_projection_bytes),
            ],
            check=False,
        )
        if completed.returncode != 0:
            verifier_failures = {
                10: "root_invalid",
                11: "directory_mode_invalid",
                12: "entry_invalid",
                13: "file_mode_invalid",
                14: "tree_changed",
                15: "file_links_invalid",
                16: "budget_exceeded",
                17: "expectation_mismatch",
                18: "deadline_exceeded",
                124: "host_timeout",
                137: "host_timeout",
            }
            reason = verifier_failures.get(completed.returncode, "command_failed")
            raise DeployError(f"deployed_api_projection_verifier_failed:{reason}")
        payload = _json_object(
            completed.stdout,
            reason="deployed_api_projection_digest_invalid",
        )
        if (
            set(payload) != {"projection_sha256", "file_count", "projection_bytes"}
            or SHA256_HEX_PATTERN.fullmatch(str(payload.get("projection_sha256") or ""))
            is None
            or type(payload.get("file_count")) is not int
            or int(payload["file_count"]) < 0
            or type(payload.get("projection_bytes")) is not int
            or int(payload["projection_bytes"]) < 0
        ):
            raise DeployError("deployed_api_projection_digest_invalid")
        return payload

    def _previous_api(self) -> dict[str, Any]:
        inspection = self._inspect_container(API_SERVICE)
        config = dict(inspection.get("Config") or {})
        self._require_compose_identity(
            inspection, service=API_SERVICE, reason_prefix="prior_api"
        )
        image_id = str(inspection.get("Image") or "").strip()
        if not IMAGE_ID_PATTERN.fullmatch(image_id):
            raise DeployError("prior_api_image_missing")
        image_reference = _safe_tagged_image_reference(
            str(config.get("Image") or ""),
            reason="prior_api_image_reference_unrestorable",
        )
        image = self._inspect_image_config(image_reference)
        if image["image_id"] != image_id:
            raise DeployError("prior_api_image_reference_identity_mismatch")
        image_noncompose_labels = _rollback_capsule_noncompose_labels(
            dict(image["config"])
        )
        if image_noncompose_labels != _rollback_capsule_noncompose_labels(config):
            raise DeployError("prior_api_image_label_identity_mismatch")
        source_revision_values = [
            str(item).split("=", 1)[1]
            for item in list(config.get("Env") or [])
            if str(item).startswith("EA_SOURCE_REVISION=")
        ]
        if len(source_revision_values) != 1:
            raise DeployError("prior_api_source_revision_missing_or_ambiguous")
        source_revision = source_revision_values[0]
        if SOURCE_REVISION_PATTERN.fullmatch(source_revision) is None:
            raise DeployError("prior_api_source_revision_invalid")
        state = dict(inspection.get("State") or {})
        health = str(dict(state.get("Health") or {}).get("Status") or "")
        if (
            not bool(state.get("Running"))
            or bool(state.get("Restarting"))
            or health != "healthy"
        ):
            raise DeployError("prior_api_not_healthy")
        topology = self._compose_topology(
            inspection,
            reason_prefix="prior_api",
            trust_inputs=False,
        )
        compose_labels = dict(config.get("Labels") or {})
        environment_file_label = str(
            compose_labels.get("com.docker.compose.project.environment_file") or ""
        )
        self._prior_compose_environment_file_label = environment_file_label
        self._prior_compose_environment_files = tuple(
            environment_file_label.split(",") if environment_file_label else ()
        )
        working_dir = Path(str(topology["working_dir"]))
        mount_identities = _mount_identities(inspection)
        runtime_config = _container_runtime_config_digests(inspection)
        memorial_layers = [
            path
            for path in list(topology["compose_config_files"])
            if Path(str(path)).name == MEMORIAL_COMPOSE_FILE
        ]
        if len(memorial_layers) > 1:
            raise DeployError("prior_api_memorial_compose_duplicate")
        capsule_document, functional_identity = self._build_rollback_capsule(inspection)
        return {
            "container_id": str(inspection.get("Id") or ""),
            "created_at": str(inspection.get("Created") or ""),
            "image_id": image_id,
            "image_reference": image_reference,
            "source_revision": source_revision,
            "working_dir": str(working_dir),
            "compose_config_files": topology["compose_config_files"],
            "mount_identities": mount_identities,
            "mount_identity_sha256": _identity_digest(mount_identities),
            "mount_identity_count": len(mount_identities),
            "noncompose_labels": _rollback_capsule_noncompose_labels(config),
            "functional_identity": functional_identity,
            "rollback_capsule_document": capsule_document,
            **runtime_config,
            "state": {
                "running": bool(state.get("Running")),
                "restarting": bool(state.get("Restarting")),
                "started_at": str(state.get("StartedAt") or ""),
                "health": health,
            },
        }

    def _require_previous_api_unchanged(self, previous: Mapping[str, Any]) -> None:
        self._require_forward_recovery_capsule_bridge_unchanged()
        current = self._inspect_container(API_SERVICE)
        self._require_compose_identity(
            current,
            service=API_SERVICE,
            reason_prefix="prior_api_before_mutation",
        )
        state = dict(current.get("State") or {})
        if (
            str(current.get("Id") or "") != str(previous.get("container_id") or "")
            or not bool(state.get("Running"))
            or bool(state.get("Restarting"))
            or str(dict(state.get("Health") or {}).get("Status") or "") != "healthy"
            or _container_functional_identity(current)
            != previous.get("functional_identity")
        ):
            raise DeployError("prior_api_changed_before_mutation")
        topology = self._compose_topology(
            current,
            reason_prefix="prior_api_before_mutation",
            trust_inputs=False,
        )
        labels = dict(dict(current.get("Config") or {}).get("Labels") or {})
        environment_file_label = str(
            labels.get("com.docker.compose.project.environment_file") or ""
        )
        if (
            topology.get("working_dir") != previous.get("working_dir")
            or topology.get("compose_config_files")
            != previous.get("compose_config_files")
            or environment_file_label != self._prior_compose_environment_file_label
        ):
            raise DeployError("prior_api_topology_changed_before_mutation")
        self._require_forward_recovery_capsule_bridge_unchanged()

    def _container_ready(
        self, name: str, *, require_health: bool
    ) -> tuple[bool, dict[str, str]]:
        inspection = self._inspect_container(name)
        state = dict(inspection.get("State") or {})
        health = dict(state.get("Health") or {})
        detail = {
            "running": str(bool(state.get("Running"))).lower(),
            "restarting": str(bool(state.get("Restarting"))).lower(),
            "health": str(health.get("Status") or ""),
            "image_id": str(inspection.get("Image") or ""),
        }
        ready = bool(state.get("Running")) and not bool(state.get("Restarting"))
        if require_health:
            ready = ready and detail["health"] == "healthy"
        elif detail["health"]:
            ready = ready and detail["health"] == "healthy"
        return ready, detail

    def _wait_container(self, name: str, *, require_health: bool) -> dict[str, str]:
        deadline = self.monotonic() + self.wait_seconds
        last_detail: dict[str, str] = {}
        while True:
            try:
                ready, last_detail = self._container_ready(
                    name, require_health=require_health
                )
                if ready:
                    return last_detail
            except DeployError as exc:
                last_detail = {"error": str(exc)}
            monotonic_now = self.monotonic()
            if monotonic_now >= deadline:
                raise DeployError(
                    f"container_not_ready:{name}:{json.dumps(last_detail, sort_keys=True)}"
                )
            sleep_seconds = min(self.poll_seconds, deadline - monotonic_now)
            action_remaining = self._remaining_mutation_action_seconds()
            if action_remaining is not None:
                sleep_seconds = min(sleep_seconds, action_remaining)
            if sleep_seconds <= 0:
                raise DeployError("mutation_action_deadline_exceeded")
            self.sleep(sleep_seconds)

    def _ensure_redis(self) -> None:
        inspection = self._inspect_container_optional(REDIS_SERVICE)
        action = "already_healthy"
        if inspection is None:
            action = "created_missing"
            self._run(
                self._target_compose(
                    "up", "-d", "--no-build", "--no-deps", REDIS_SERVICE
                )
            )
        else:
            self._require_compose_identity(
                inspection, service=REDIS_SERVICE, reason_prefix="redis"
            )
            state = dict(inspection.get("State") or {})
            health = str(dict(state.get("Health") or {}).get("Status") or "")
            running = bool(state.get("Running"))
            restarting = bool(state.get("Restarting"))
            if running and not restarting and health == "healthy":
                self._record_check("redis", "pass", action=action, health=health)
                return
            if not running and not restarting:
                action = "started_existing"
                self._run(["docker", "start", REDIS_SERVICE])
            else:
                action = "waited_for_existing"
        detail = self._wait_container(REDIS_SERVICE, require_health=True)
        final_inspection = self._inspect_container(REDIS_SERVICE)
        self._require_compose_identity(
            final_inspection, service=REDIS_SERVICE, reason_prefix="redis"
        )
        self._record_check("redis", "pass", action=action, **detail)

    def _git_head(self) -> str:
        head = self._run(["git", "rev-parse", "HEAD"]).stdout.strip()
        if not re.fullmatch(r"[0-9a-f]{40}", head):
            raise DeployError("git_head_invalid")
        return head

    def _bind_source_revision(self, source_revision: str) -> str:
        if not re.fullmatch(r"[0-9a-f]{40}", source_revision):
            raise DeployError("git_head_invalid")
        self.release_env["EA_SOURCE_REVISION"] = source_revision
        self.receipt["source_revision"] = source_revision
        self._write_receipt()
        return source_revision

    def _protect_previous_image(self, previous: Mapping[str, Any]) -> str:
        rollback_tag = _safe_rollback_tag(self.deployment_id)
        self._run(["docker", "image", "tag", str(previous["image_id"]), rollback_tag])
        protected = self._inspect_image(rollback_tag)
        if protected["image_id"] != str(previous["image_id"]):
            raise DeployError("rollback_image_protection_mismatch")
        return rollback_tag

    def _recreate_api(self) -> None:
        self._run(
            self._target_compose(
                "up",
                "-d",
                "--no-build",
                "--no-deps",
                "--force-recreate",
                API_SERVICE,
            )
        )

    def _local_origin(self) -> str:
        host_port = _first_nonempty(
            self.env.get("EA_HOST_PORT"),
            self.env_file_values.get("EA_HOST_PORT"),
            "8090",
        )
        if not host_port.isdigit() or not 1 <= int(host_port) <= 65535:
            raise DeployError("ea_host_port_invalid")
        return f"http://127.0.0.1:{host_port}"

    def _wait_http(
        self,
        url: str,
        *,
        kind: str,
        expected_source_revision: str = "",
        public_authority: str = "",
    ) -> dict[str, Any]:
        deadline = self.monotonic() + self.wait_seconds
        last_error = ""
        while True:
            try:
                response = self.http_get(
                    url,
                    self.request_timeout_seconds,
                    public_authority,
                )
                if response.status != 200:
                    raise DeployError(f"http_status_invalid:{url}:{response.status}")
                if (
                    expected_source_revision
                    and response.source_revision != expected_source_revision
                ):
                    raise DeployError(f"source_revision_mismatch:{url}")
                if kind == "html":
                    lowered = response.body.lower()
                    decoded = response.body.decode("utf-8", errors="replace").casefold()
                    if b"manfred" not in lowered or not (
                        "text/html" in response.content_type.lower()
                        or b"<html" in lowered
                        or b"<!doctype html" in lowered
                    ):
                        raise DeployError(f"memorial_html_contract_invalid:{url}")
                    if (
                        "ist nicht manfred" not in decoded
                        or "spricht nicht für ihn" not in decoded
                    ):
                        raise DeployError(f"memorial_transparency_marker_missing:{url}")
                    if "ich bin manfred" in decoded:
                        raise DeployError(
                            f"memorial_impersonation_marker_present:{url}"
                        )
                elif kind == "control_html":
                    lowered = response.body.lower()
                    if not (
                        "text/html" in response.content_type.lower()
                        or b"<html" in lowered
                        or b"<!doctype html" in lowered
                    ):
                        raise DeployError(f"control_html_contract_invalid:{url}")
                elif kind == "json":
                    manifest = _json_object(
                        response.body.decode("utf-8"),
                        reason=f"memorial_json_invalid:{url}",
                    )
                    if str(manifest.get("slug") or "") != MEMORIAL_SLUG:
                        raise DeployError(f"memorial_json_slug_mismatch:{url}")
                    combined_disclosure = " ".join(
                        str(manifest.get(key) or "") for key in ("intro", "disclosure")
                    ).casefold()
                    if (
                        "ist nicht manfred" not in combined_disclosure
                        or "spricht nicht für ihn" not in combined_disclosure
                    ):
                        raise DeployError(f"memorial_transparency_marker_missing:{url}")
                    if "ich bin manfred" in combined_disclosure:
                        raise DeployError(
                            f"memorial_impersonation_marker_present:{url}"
                        )
                return {
                    "url": url,
                    "status_code": response.status,
                    "content_type": response.content_type,
                    "body_bytes": len(response.body),
                    "body_sha256": hashlib.sha256(response.body).hexdigest(),
                    "source_revision": response.source_revision,
                }
            except DeployError as exc:
                last_error = str(exc)
            if self.monotonic() >= deadline:
                raise DeployError(f"http_probe_exhausted:{url}:{last_error}")
            self.sleep(self.poll_seconds)

    def _verify_local_https_redirects(
        self,
        local_origin: str,
        public_origin: str,
    ) -> dict[str, Any]:
        validated_public_origin = _validate_public_origin(
            public_origin,
            allowed_hosts=self.allowed_public_hosts,
        )
        parsed_public_origin = urllib.parse.urlsplit(validated_public_origin)
        public_hostname = str(parsed_public_origin.hostname or "").lower().rstrip(".")
        public_authority = (
            f"[{public_hostname}]" if ":" in public_hostname else public_hostname
        )
        if not public_authority:
            raise DeployError("public_origin_invalid")

        expected_local_origin = self._local_origin()
        if local_origin != expected_local_origin:
            raise DeployError("local_transport_origin_mismatch")
        try:
            parsed_local_origin = urllib.parse.urlsplit(local_origin)
            local_port = parsed_local_origin.port
        except ValueError as exc:
            raise DeployError("local_transport_origin_invalid") from exc
        if (
            parsed_local_origin.scheme != "http"
            or parsed_local_origin.hostname != "127.0.0.1"
            or local_port is None
            or parsed_local_origin.username
            or parsed_local_origin.password
            or parsed_local_origin.path not in {"", "/"}
            or parsed_local_origin.query
            or parsed_local_origin.fragment
        ):
            raise DeployError("local_transport_origin_invalid")

        route_specs = (
            ("canonical_html", f"/memorials/{MEMORIAL_SLUG}"),
            ("canonical_json", f"/memorials/{MEMORIAL_SLUG}.json"),
            (
                "singular_alias",
                f"/memorial/{MEMORIAL_SLUG}?from=ea-launch-verifier",
            ),
        )
        routes: dict[str, dict[str, object]] = {}
        for label, path in route_specs:
            expected_location = f"{validated_public_origin}{path}"
            for method in ("GET", "HEAD"):
                response = self.http_no_redirect(
                    f"{local_origin}{path}",
                    self.request_timeout_seconds,
                    method,
                    public_authority,
                )
                headers = {
                    str(name).strip().casefold(): str(value).strip()
                    for name, value in dict(response.headers or {}).items()
                }
                if response.status != 308:
                    raise DeployError("local_https_redirect_status_invalid")
                if headers.get("location") != expected_location:
                    raise DeployError("local_https_redirect_location_invalid")
                if method == "HEAD" and response.body:
                    raise DeployError("local_https_redirect_head_body_invalid")
                routes[f"{label}_{method.lower()}"] = {
                    "method": method,
                    "path": path,
                    "status_code": response.status,
                    "location": expected_location,
                    "body_bytes": len(response.body),
                }
        return {
            "status": "pass",
            "local_origin": local_origin,
            "public_origin": validated_public_origin,
            "trusted_proxy_headers_sent": False,
            "route_count": len(routes),
            "routes": routes,
        }

    def _verify_singular_memorial_alias(
        self,
        origin: str,
        *,
        public_authority: str = "",
    ) -> dict[str, Any]:
        query = "from=ea-launch-verifier"
        url = f"{origin}/memorial/{MEMORIAL_SLUG}?{query}"
        expected_location = f"/memorials/{MEMORIAL_SLUG}?{query}"
        expected_headers = {
            "cache-control": "no-store",
            "referrer-policy": "no-referrer",
            "x-content-type-options": "nosniff",
            "x-robots-tag": "noindex, nofollow",
        }
        methods: list[dict[str, Any]] = []
        for method in ("GET", "HEAD"):
            response = self.http_no_redirect(
                url,
                self.request_timeout_seconds,
                method,
                public_authority,
            )
            headers = {
                str(name).strip().casefold(): str(value).strip()
                for name, value in dict(response.headers or {}).items()
            }
            if response.status != 308:
                raise DeployError("memorial_alias_status_invalid")
            if headers.get("location") != expected_location:
                raise DeployError("memorial_alias_location_invalid")
            if any(
                headers.get(name, "").casefold() != value
                for name, value in expected_headers.items()
            ):
                raise DeployError("memorial_alias_headers_invalid")
            if method == "HEAD" and response.body:
                raise DeployError("memorial_alias_head_body_invalid")
            methods.append(
                {
                    "method": method,
                    "status_code": response.status,
                    "location": expected_location,
                    "headers": dict(expected_headers),
                    "body_bytes": len(response.body),
                }
            )
        return {
            "origin": origin,
            "alias_path": f"/memorial/{MEMORIAL_SLUG}",
            "canonical_path": f"/memorials/{MEMORIAL_SLUG}",
            "query_preserved": True,
            "methods": methods,
        }

    def _wait_json_control(self, url: str) -> tuple[dict[str, Any], dict[str, Any]]:
        deadline = self.monotonic() + self.wait_seconds
        last_error = ""
        while True:
            try:
                response = self.http_get(url, self.request_timeout_seconds)
                if response.status != 200:
                    raise DeployError(f"http_status_invalid:{url}:{response.status}")
                if len(response.body) > MAX_HTTP_BODY_BYTES:
                    raise DeployError(f"http_body_too_large:{url}")
                payload = _json_object(
                    response.body.decode("utf-8"),
                    reason=f"control_json_invalid:{url}",
                )
                return payload, {
                    "url": url,
                    "status_code": 200,
                    "content_type": str(response.content_type or "")[
                        :MAX_RECEIPT_CONTENT_TYPE_CHARS
                    ],
                    "body_bytes": len(response.body),
                    "body_sha256": hashlib.sha256(response.body).hexdigest(),
                    "canonical_json_sha256": _canonical_json_sha256(payload),
                }
            except (DeployError, UnicodeDecodeError) as exc:
                last_error = str(exc)
            if self.monotonic() >= deadline:
                raise DeployError(f"http_probe_exhausted:{url}:{last_error}")
            self.sleep(self.poll_seconds)

    def _capture_openapi_control(self) -> dict[str, Any]:
        url = f"{self._local_origin()}/openapi.json"
        payload, probe = self._wait_json_control(url)
        contract = _canonical_openapi_contract(payload)
        return {
            **_openapi_control_evidence(contract=contract, probe=probe),
            "_contract": contract,
        }

    def _capture_internal_openapi_control(self) -> dict[str, Any]:
        if self.internal_openapi_snapshot is None:
            completed = self._run(
                [
                    "/usr/bin/timeout",
                    "--signal=KILL",
                    "30s",
                    "docker",
                    "exec",
                    API_SERVICE,
                    "python3",
                    "-c",
                    CONTAINER_OPENAPI_SNAPSHOT_SCRIPT,
                ],
                check=False,
            )
            if completed.returncode != 0:
                raise DeployError("deployed_api_internal_openapi_snapshot_failed")
            encoded = completed.stdout.encode("utf-8", errors="strict")
            if not encoded or len(encoded) > MAX_INTERNAL_OPENAPI_BYTES:
                raise DeployError("deployed_api_internal_openapi_snapshot_size_invalid")
            envelope = _json_object(
                completed.stdout,
                reason="deployed_api_internal_openapi_snapshot_invalid",
            )
        else:
            envelope = dict(self.internal_openapi_snapshot())

        if (
            set(envelope) != {"docs_url", "document", "openapi_url", "redoc_url"}
            or envelope.get("docs_url") is not None
            or envelope.get("openapi_url") is not None
            or envelope.get("redoc_url") is not None
            or not isinstance(envelope.get("document"), dict)
        ):
            raise DeployError("deployed_api_internal_openapi_snapshot_invalid")
        document = dict(envelope["document"])
        encoded_document = json.dumps(
            document,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        if not encoded_document or len(encoded_document) > MAX_INTERNAL_OPENAPI_BYTES:
            raise DeployError("deployed_api_internal_openapi_snapshot_size_invalid")
        contract = _canonical_openapi_contract(document)
        return {
            **_openapi_control_evidence(
                contract=contract,
                probe={
                    "source": "deployed_api_container_app.openapi",
                    "container": API_SERVICE,
                    "public_docs_config_retired": True,
                    "document_bytes": len(encoded_document),
                    "document_sha256": hashlib.sha256(encoded_document).hexdigest(),
                },
            ),
            "_contract": contract,
        }

    def _capture_public_openapi_retirement(
        self,
        public_origin: str,
        *,
        expected_source_revision: str,
    ) -> dict[str, Any]:
        if SOURCE_REVISION_PATTERN.fullmatch(expected_source_revision) is None:
            raise DeployError("public_openapi_expected_source_revision_invalid")
        validated_origin = _validate_public_origin(
            public_origin,
            allowed_hosts=self.allowed_public_hosts,
        )
        url = f"{validated_origin}/openapi.json"
        deadline = self.monotonic() + self.wait_seconds
        last_error = ""
        while True:
            try:
                response = self.http_no_redirect(
                    url,
                    self.request_timeout_seconds,
                    "GET",
                    "",
                )
                if response.status != 404:
                    raise DeployError("public_openapi_retirement_status_invalid")
                headers = {
                    str(name).strip().casefold(): str(value).strip()
                    for name, value in dict(response.headers or {}).items()
                }
                if headers.get("location"):
                    raise DeployError("public_openapi_retirement_redirect_invalid")
                if response.source_revision != expected_source_revision:
                    raise DeployError("public_openapi_retirement_revision_mismatch")
                content_type = str(response.content_type or "").strip()
                if (
                    not content_type
                    or len(content_type) > MAX_RECEIPT_CONTENT_TYPE_CHARS
                    or any(
                        ord(character) < 32 or ord(character) == 127
                        for character in content_type
                    )
                ):
                    raise DeployError("public_openapi_retirement_content_type_invalid")
                media_type = content_type.partition(";")[0].strip().casefold()
                if media_type != "application/json":
                    raise DeployError("public_openapi_retirement_content_type_invalid")
                if not response.body or len(response.body) > MAX_HTTP_BODY_BYTES:
                    raise DeployError("public_openapi_retirement_body_size_invalid")
                try:
                    payload = _json_object(
                        response.body.decode("utf-8"),
                        reason="public_openapi_retirement_json_invalid",
                    )
                except UnicodeDecodeError as exc:
                    raise DeployError("public_openapi_retirement_json_invalid") from exc
                error = payload.get("error")
                if not isinstance(error, dict) or error.get("code") != "not_found":
                    raise DeployError("public_openapi_retirement_error_code_invalid")
                return {
                    "path": "/openapi.json",
                    "method": "GET",
                    "status_code": 404,
                    "redirect_count": 0,
                    "content_type": content_type,
                    "media_type": media_type,
                    "error_code": "not_found",
                    "source_revision": expected_source_revision,
                    "body_bytes": len(response.body),
                    "body_sha256": hashlib.sha256(response.body).hexdigest(),
                    "canonical_json_sha256": _canonical_json_sha256(payload),
                }
            except DeployError as exc:
                last_error = str(exc)
            if self.monotonic() >= deadline:
                raise DeployError(
                    f"public_openapi_retirement_probe_exhausted:{last_error}"
                )
            self.sleep(self.poll_seconds)

    @staticmethod
    def _sanitized_openapi_control(control: Mapping[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in control.items() if key != "_contract"}

    @staticmethod
    def _sanitized_tour_control(control: Mapping[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in control.items() if key != "_json_payload"}

    def _capture_non_memorial_controls(
        self,
        *,
        public_origin: str,
        expected_source_revision: str,
    ) -> dict[str, Any]:
        controls: dict[str, Any] = {"openapi": self._capture_internal_openapi_control()}
        controls["openapi"]["public_endpoint"] = (
            self._capture_public_openapi_retirement(
                public_origin,
                expected_source_revision=expected_source_revision,
            )
        )
        predeploy_operations = dict(
            dict(controls["openapi"].get("_contract") or {}).get("operations") or {}
        )
        predeploy_retirement_operations = [
            operation
            for operation in OPENAPI_RETIREMENT_ALLOWED_OPERATIONS
            if operation in predeploy_operations
        ]
        if predeploy_retirement_operations not in (
            [],
            list(OPENAPI_RETIREMENT_ALLOWED_OPERATIONS),
        ):
            raise DeployError("predeploy_openapi_retirement_operations_missing")
        if self.control_tour_slug:
            base = f"{self._local_origin()}/tours/{self.control_tour_slug}"
            html = self._wait_http(base, kind="control_html")
            payload, tour_json = self._wait_json_control(f"{base}.json")
            controls["tour"] = {
                "slug": self.control_tour_slug,
                "html": html,
                "json": tour_json,
                "_json_payload": payload,
            }
        receipt_controls: dict[str, Any] = {
            "openapi": self._sanitized_openapi_control(controls["openapi"]),
        }
        if "tour" in controls:
            receipt_controls["tour"] = self._sanitized_tour_control(controls["tour"])
        receipt_controls["openapi"]["retirement_policy_id"] = (
            OPENAPI_RETIREMENT_POLICY_ID
        )
        receipt_controls["openapi"]["retirement_allowed_operations"] = list(
            OPENAPI_RETIREMENT_ALLOWED_OPERATIONS
        )
        receipt_controls["openapi"]["retirement_state"] = (
            "pending" if predeploy_retirement_operations else "applied"
        )
        receipt_controls["openapi"]["compatible_evolution_policy_id"] = (
            OPENAPI_COMPATIBLE_EVOLUTION_POLICY_ID
        )
        receipt_controls["openapi"]["compatible_evolution_allowed_operations"] = list(
            OPENAPI_COMPATIBLE_EVOLUTION_ALLOWED_OPERATIONS
        )
        self.receipt["predeploy_non_memorial_controls"] = receipt_controls
        self._record_check(
            "predeploy_non_memorial_controls",
            "pass",
            openapi_path_count=controls["openapi"]["path_count"],
            tour_slug=self.control_tour_slug or None,
        )
        return controls

    def _verify_non_memorial_controls(
        self,
        baseline: Mapping[str, Any],
        *,
        public_origin: str,
        expected_source_revision: str,
    ) -> None:
        prior_openapi = dict(baseline.get("openapi") or {})
        prior_contract_value = prior_openapi.get("_contract")
        prior_contract = (
            dict(prior_contract_value) if isinstance(prior_contract_value, dict) else {}
        )
        prior_operations = dict(prior_contract.get("operations") or {})
        prior_schemas = dict(prior_contract.get("schemas") or {})
        prior_security = dict(prior_contract.get("security_schemes") or {})
        if not prior_operations:
            raise DeployError("predeploy_openapi_contract_invalid")
        current_openapi = self._capture_internal_openapi_control()
        current_openapi["public_endpoint"] = self._capture_public_openapi_retirement(
            public_origin,
            expected_source_revision=expected_source_revision,
        )
        current_contract = dict(current_openapi.get("_contract") or {})
        current_operations = dict(current_contract.get("operations") or {})
        current_schemas = dict(current_contract.get("schemas") or {})
        current_security = dict(current_contract.get("security_schemes") or {})
        missing_operations = sorted(set(prior_operations) - set(current_operations))
        expected_retirements = sorted(
            operation
            for operation in OPENAPI_RETIREMENT_ALLOWED_OPERATIONS
            if operation in prior_operations
        )
        if missing_operations != expected_retirements or any(
            operation in current_operations
            for operation in OPENAPI_RETIREMENT_ALLOWED_OPERATIONS
        ):
            raise DeployError("postdeploy_openapi_operation_retirement_mismatch")
        missing_or_changed_schemas = sorted(
            name
            for name, value in prior_schemas.items()
            if name not in current_schemas or current_schemas[name] != value
        )
        if missing_or_changed_schemas:
            raise DeployError("postdeploy_openapi_schema_regression")
        missing_or_changed_security = sorted(
            name
            for name, value in prior_security.items()
            if name not in current_security or current_security[name] != value
        )
        if missing_or_changed_security:
            raise DeployError("postdeploy_openapi_security_regression")
        changed_operations: list[str] = []
        compatible_evolved_operations: list[str] = []
        for name, value in prior_operations.items():
            if name not in current_operations or current_operations[name] == value:
                continue
            if (
                name == "GET /version"
                and name in OPENAPI_COMPATIBLE_EVOLUTION_ALLOWED_OPERATIONS
                and _version_openapi_evolution_preserved(
                    value,
                    current_operations[name],
                )
            ):
                compatible_evolved_operations.append(name)
                continue
            changed_operations.append(name)
        changed_operations.sort()
        compatible_evolved_operations.sort()
        if changed_operations:
            raise DeployError("postdeploy_openapi_operation_changed")

        evidence: dict[str, Any] = {
            "openapi": {
                **self._sanitized_openapi_control(current_openapi),
                "baseline_path_count": int(prior_openapi.get("path_count") or 0),
                "baseline_operation_count": len(prior_operations),
                "added_path_count": len(
                    set(current_openapi.get("paths") or [])
                    - set(prior_openapi.get("paths") or [])
                ),
                "added_operation_count": len(
                    set(current_operations) - set(prior_operations)
                ),
                "retirement_policy_id": OPENAPI_RETIREMENT_POLICY_ID,
                "retirement_allowed_operations": list(
                    OPENAPI_RETIREMENT_ALLOWED_OPERATIONS
                ),
                "retired_operations": missing_operations,
                "retired_operation_count": len(missing_operations),
                "retirement_policy_exact_match": True,
                "changed_operation_count": 0,
                "compatible_evolution_policy_id": (
                    OPENAPI_COMPATIBLE_EVOLUTION_POLICY_ID
                ),
                "compatible_evolution_allowed_operations": list(
                    OPENAPI_COMPATIBLE_EVOLUTION_ALLOWED_OPERATIONS
                ),
                "compatible_evolved_operations": compatible_evolved_operations,
                "compatible_evolved_operation_count": len(
                    compatible_evolved_operations
                ),
                "compatible_evolution_policy_exact_match": True,
                "missing_or_changed_schema_count": 0,
                "missing_or_changed_security_scheme_count": 0,
            }
        }
        prior_tour = baseline.get("tour")
        if prior_tour is not None:
            prior_tour = dict(prior_tour)
            slug = str(prior_tour.get("slug") or "")
            if (
                slug != self.control_tour_slug
                or not CONTROL_TOUR_SLUG_PATTERN.fullmatch(slug)
            ):
                raise DeployError("predeploy_control_tour_invalid")
            base = f"{self._local_origin()}/tours/{slug}"
            html = self._wait_http(base, kind="control_html")
            payload, tour_json = self._wait_json_control(f"{base}.json")
            prior_json = dict(prior_tour.get("json") or {})
            prior_payload = prior_tour.get("_json_payload")
            if not isinstance(prior_payload, dict):
                raise DeployError("postdeploy_control_tour_json_changed")
            payload_unchanged = payload == prior_payload and tour_json[
                "canonical_json_sha256"
            ] == prior_json.get("canonical_json_sha256")
            compatible_evolution_applied = False
            if not payload_unchanged:
                if not _control_tour_generated_viewer_evolution_preserved(
                    prior_payload,
                    payload,
                    slug=slug,
                ):
                    raise DeployError("postdeploy_control_tour_json_changed")
                compatible_evolution_applied = True
            evidence["tour"] = {
                "slug": slug,
                "html": html,
                "json": tour_json,
                "compatible_evolution_policy_id": (
                    CONTROL_TOUR_COMPATIBLE_EVOLUTION_POLICY_ID
                ),
                "compatible_evolution_applied": compatible_evolution_applied,
                "compatible_evolution_policy_exact_match": True,
            }

        self.receipt["postdeploy_non_memorial_controls"] = evidence
        self._record_check(
            "postdeploy_non_memorial_controls",
            "pass",
            openapi_path_count=current_openapi["path_count"],
            tour_slug=self.control_tour_slug or None,
        )

    def _verify_public_spatial_tour(
        self,
        public_origin: str,
        source_revision: str,
        candidate_promotion_evidence: Mapping[str, Any],
    ) -> dict[str, Any]:
        validated_public_origin = _validate_public_origin(
            public_origin,
            allowed_hosts=self.allowed_public_hosts,
        )
        if SOURCE_REVISION_PATTERN.fullmatch(source_revision) is None:
            raise DeployError("public_spatial_source_revision_invalid")
        if candidate_promotion_evidence.get("provider_calls_performed") is not False:
            raise DeployError("public_spatial_provider_boundary_invalid")
        spatial_value = candidate_promotion_evidence.get("spatial_handoff")
        spatial = dict(spatial_value) if isinstance(spatial_value, dict) else {}
        expected_spatial_fields = {
            "slug",
            "route_count",
            "html_json_viewer_200",
            "proof_only_404",
            "release_verifier_pass",
            "browser_schema",
            "browser_pass",
            "identity_bound",
            "package_sha256",
            "allowed_files",
            "viewer_relpath",
            "proof_relpath",
            "tour_manifest_canonical_sha256",
            "property_artifact_commit",
            "upstream_publication_authority_sha256",
            "upstream_tour_manifest_sha256",
            "pre_authority_manifest_canonical_sha256",
            "upstream_public_activation_authority",
            "ea_public_activation_authority",
            "provider_calls_performed",
        }
        allowed_files_value = spatial.get("allowed_files")
        allowed_files = (
            dict(allowed_files_value) if isinstance(allowed_files_value, dict) else {}
        )
        slug = str(spatial.get("slug") or "")
        if (
            set(spatial) != expected_spatial_fields
            or slug != REQUIRED_CONTROL_TOUR_SLUG
            or CONTROL_TOUR_SLUG_PATTERN.fullmatch(slug) is None
            or spatial.get("route_count") != 8
            or spatial.get("html_json_viewer_200") is not True
            or spatial.get("proof_only_404") is not True
            or spatial.get("release_verifier_pass") is not True
            or spatial.get("browser_schema")
            != "ea.manfred_spatial_candidate_browser.v5"
            or spatial.get("browser_pass") is not True
            or spatial.get("identity_bound") is not True
            or SHA256_HEX_PATTERN.fullmatch(str(spatial.get("package_sha256") or ""))
            is None
            or spatial.get("viewer_relpath") != PUBLIC_SPATIAL_VIEWER_RELPATH
            or spatial.get("proof_relpath") != PUBLIC_SPATIAL_PROOF_RELPATH
            or SHA256_HEX_PATTERN.fullmatch(
                str(spatial.get("tour_manifest_canonical_sha256") or "")
            )
            is None
            or spatial.get("property_artifact_commit") != PROPERTY_ARTIFACT_COMMIT
            or spatial.get("upstream_publication_authority_sha256")
            != PROPERTY_AUTHORITY_SHA256
            or spatial.get("upstream_tour_manifest_sha256") != PROPERTY_TOUR_SHA256
            or spatial.get("pre_authority_manifest_canonical_sha256")
            != PROPERTY_PRE_AUTHORITY_SHA256
            or spatial.get("upstream_public_activation_authority") is not True
            or spatial.get("ea_public_activation_authority") is not False
            or spatial.get("provider_calls_performed") is not False
            or set(allowed_files) != set(PUBLIC_SPATIAL_ALLOWED_FILE_RELPATHS)
        ):
            raise DeployError("public_spatial_candidate_evidence_invalid")
        for relpath in PUBLIC_SPATIAL_ALLOWED_FILE_RELPATHS:
            file_value = allowed_files.get(relpath)
            file_evidence = dict(file_value) if isinstance(file_value, dict) else {}
            if (
                set(file_evidence) != {"sha256", "size_bytes"}
                or SHA256_HEX_PATTERN.fullmatch(str(file_evidence.get("sha256") or ""))
                is None
                or type(file_evidence.get("size_bytes")) is not int
                or int(file_evidence["size_bytes"]) <= 0
            ):
                raise DeployError("public_spatial_candidate_file_evidence_invalid")
        if dict(allowed_files["tour.json"]).get("sha256") != spatial.get(
            "upstream_tour_manifest_sha256"
        ):
            raise DeployError("public_spatial_candidate_authority_mismatch")

        quoted_slug = urllib.parse.quote(slug, safe="")
        viewer_root = f"/tours/viewer/{quoted_slug}"
        request_specs = (
            ("version", "/version", 200, ("application/json",), None),
            (
                "landing",
                f"/tours/{quoted_slug}",
                200,
                ("text/html",),
                None,
            ),
            (
                "tour_json",
                f"/tours/{quoted_slug}.json",
                200,
                ("application/json",),
                "tour.json",
            ),
            (
                "viewer",
                f"{viewer_root}/{PUBLIC_SPATIAL_VIEWER_RELPATH}",
                200,
                ("text/html",),
                PUBLIC_SPATIAL_VIEWER_RELPATH,
            ),
            (
                "floorplan",
                f"{viewer_root}/{PUBLIC_SPATIAL_FLOORPLAN_RELPATH}",
                200,
                ("image/png",),
                PUBLIC_SPATIAL_FLOORPLAN_RELPATH,
            ),
            (
                "three_module",
                f"{viewer_root}/{PUBLIC_SPATIAL_JAVASCRIPT_RELPATHS[0]}",
                200,
                ("application/javascript", "text/javascript"),
                PUBLIC_SPATIAL_JAVASCRIPT_RELPATHS[0],
            ),
            (
                "orbit_controls",
                f"{viewer_root}/{PUBLIC_SPATIAL_JAVASCRIPT_RELPATHS[1]}",
                200,
                ("application/javascript", "text/javascript"),
                PUBLIC_SPATIAL_JAVASCRIPT_RELPATHS[1],
            ),
            (
                "proof_only",
                f"{viewer_root}/{PUBLIC_SPATIAL_PROOF_RELPATH}",
                404,
                ("application/json",),
                PUBLIC_SPATIAL_PROOF_RELPATH,
            ),
        )
        expected_origin = urllib.parse.urlsplit(validated_public_origin)
        route_evidence: dict[str, dict[str, Any]] = {}
        for label, path, expected_status, media_types, relpath in request_specs:
            url = f"{validated_public_origin}{path}"
            parsed_url = urllib.parse.urlsplit(url)
            if (
                parsed_url.scheme != expected_origin.scheme
                or parsed_url.netloc != expected_origin.netloc
                or parsed_url.query
                or parsed_url.fragment
            ):
                raise DeployError("public_spatial_external_request_rejected")
            methods = ("GET",) if label == "version" else ("GET", "HEAD")
            for method in methods:
                response = self.http_no_redirect(
                    url,
                    self.request_timeout_seconds,
                    method,
                    "",
                )
                response_headers = {
                    str(name).lower(): str(value or "").strip()
                    for name, value in dict(response.headers or {}).items()
                }
                if response_headers.get("location"):
                    raise DeployError(f"public_spatial_redirect_rejected:{path}")
                if response.status != expected_status:
                    raise DeployError(f"public_spatial_status_invalid:{path}")
                if (
                    label not in PUBLIC_SPATIAL_DIGEST_ONLY_LABELS
                    and response.source_revision != source_revision
                ):
                    raise DeployError(f"public_spatial_source_revision_mismatch:{path}")
                media_type = response.content_type.partition(";")[0].strip().lower()
                if media_type not in media_types:
                    raise DeployError(f"public_spatial_content_type_invalid:{path}")
                if method == "HEAD" and response.body:
                    raise DeployError(f"public_spatial_head_body_invalid:{path}")

                row: dict[str, Any] = {
                    "path": path,
                    "method": method,
                    "status": response.status,
                    "content_type": response.content_type,
                    "source_revision": response.source_revision,
                    "body_bytes": len(response.body),
                    "body_sha256": hashlib.sha256(response.body).hexdigest(),
                }
                if method == "GET" and label == "version":
                    _json_object(
                        response.body.decode("utf-8"),
                        reason="public_spatial_version_json_invalid",
                    )
                    row["source_revision_header_verified"] = True
                elif method == "GET" and label == "tour_json":
                    try:
                        tour_manifest = json.loads(response.body)
                    except (TypeError, ValueError) as exc:
                        raise DeployError("public_spatial_tour_json_invalid") from exc
                    canonical_sha256 = _canonical_json_sha256(tour_manifest)
                    if canonical_sha256 != spatial.get(
                        "tour_manifest_canonical_sha256"
                    ):
                        raise DeployError("public_spatial_tour_json_digest_mismatch")
                    row["canonical_json_sha256"] = canonical_sha256
                elif method == "GET" and relpath and label != "proof_only":
                    expected_file = dict(allowed_files[relpath])
                    if (
                        len(response.body) != expected_file["size_bytes"]
                        or row["body_sha256"] != expected_file["sha256"]
                    ):
                        raise DeployError(
                            f"public_spatial_asset_digest_mismatch:{path}"
                        )
                    row["candidate_file_identity_verified"] = True
                elif method == "GET" and label == "proof_only":
                    proof_file = dict(allowed_files[PUBLIC_SPATIAL_PROOF_RELPATH])
                    if row["body_sha256"] == proof_file["sha256"]:
                        raise DeployError("public_spatial_proof_disclosed")
                    row["candidate_file_not_disclosed"] = True
                route_evidence[f"{label}_{method.lower()}"] = row

        evidence = {
            "status": "pass",
            "origin": validated_public_origin,
            "slug": slug,
            "source_revision": source_revision,
            "request_count": len(route_evidence),
            "get_count": sum(
                row.get("method") == "GET" for row in route_evidence.values()
            ),
            "head_count": sum(
                row.get("method") == "HEAD" for row in route_evidence.values()
            ),
            "routes": route_evidence,
            "exact_byte_file_count": 4,
            "canonical_json_file_count": 1,
            "proof_only_404": True,
            "redirect_count": 0,
            "external_request_count": 0,
            "provider_calls_performed": False,
            "property_authority": {
                "owner": "PropertyQuarry",
                "artifact_commit": PROPERTY_ARTIFACT_COMMIT,
                "publication_authority_sha256": PROPERTY_AUTHORITY_SHA256,
                "package_sha256": str(spatial["package_sha256"]),
                "upstream_public_activation_authority": True,
                "ea_public_activation_authority": False,
            },
        }
        return evidence

    def _verify_deployed_surface(
        self,
        public_origin: str,
        *,
        source_revision: str,
        candidate_promotion_evidence: Mapping[str, Any],
    ) -> None:
        validated_public_origin = _validate_public_origin(
            public_origin,
            allowed_hosts=self.allowed_public_hosts,
        )
        local = self._local_origin()
        probes = [
            self._wait_http(
                f"{local}/health",
                kind="health",
                expected_source_revision=source_revision,
            ),
            self._wait_http(
                f"{validated_public_origin}/memorials/{MEMORIAL_SLUG}",
                kind="html",
                expected_source_revision=source_revision,
            ),
            self._wait_http(
                f"{validated_public_origin}/memorials/{MEMORIAL_SLUG}.json",
                kind="json",
                expected_source_revision=source_revision,
            ),
        ]
        local_transport = self._verify_local_https_redirects(
            local,
            validated_public_origin,
        )
        alias_probes = [
            self._verify_singular_memorial_alias(validated_public_origin),
        ]
        spatial_probe = self._verify_public_spatial_tour(
            validated_public_origin,
            source_revision,
            candidate_promotion_evidence,
        )
        self.receipt["probes"] = probes
        self.receipt["local_https_redirects"] = local_transport
        self.receipt["alias_probes"] = alias_probes
        self.receipt["public_spatial_tour"] = spatial_probe
        self._record_check(
            "local_and_public_memorial",
            "pass",
            alias_method_probes=sum(
                len(list(item.get("methods") or [])) for item in alias_probes
            ),
            spatial_method_probes=int(spatial_probe["request_count"]),
        )

    def _verify_candidate_origin(
        self, *, label: str, base_url: str, public_origin: str
    ) -> dict[str, Any]:
        payload = self._run_json_script(
            "scripts/verify_manfred_memorial_candidate.py",
            "--base-url",
            base_url,
            "--public-origin",
            public_origin,
            "--wait-seconds",
            str(max(1, min(600, int(self.wait_seconds or 1)))),
            "--browser-audit",
            origin=label,
        )
        required_checks = {
            "archive_publication_gate",
            "singular_memorial_alias",
            "source_grounded_narrator_boundary",
            "voice_provider_boundary_blocked",
            "browser_provider_websocket_boundary",
        }
        checks = {
            str(item).strip()
            for item in list(payload.get("checks") or [])
            if str(item).strip()
        }
        browser = dict(payload.get("browser_audit") or {})
        if (
            str(payload.get("schema") or "") != "ea.manfred_memorial_candidate_smoke.v1"
            or str(payload.get("status") or "").lower() != "pass"
            or not required_checks <= checks
            or payload.get("provider_calls_performed") is not False
            or payload.get("page_get_performed") is not True
            or str(browser.get("status") or "").lower() != "pass"
            or not _has_exact_zero_browser_counts(browser)
        ):
            self._record_check(
                "candidate_verifier_origin",
                "fail",
                origin=label,
                error_code="candidate_verifier_contract_failed",
            )
            raise DeployError(f"candidate_verifier_contract_failed:{label}")
        return {
            "origin": label,
            "status": "pass",
            "checks": sorted(required_checks),
            "provider_calls_performed": False,
            "browser": {
                "automatic_provider_requests": 0,
                "automatic_websockets": 0,
                "external_requests": 0,
                "failed_requests": 0,
                "page_errors": 0,
                "http_errors": 0,
            },
        }

    def _verify_candidate_origins(self, public_origin: str) -> None:
        validated_public_origin = _validate_public_origin(
            public_origin,
            allowed_hosts=self.allowed_public_hosts,
        )
        evidence = [
            self._verify_candidate_origin(
                label="public",
                base_url=validated_public_origin,
                public_origin=validated_public_origin,
            )
        ]
        self.receipt["candidate_verifier"] = evidence
        self._record_check("candidate_verifier_origin", "pass", origin="public")
        self._record_check(
            "public_candidate_verifier",
            "pass",
            local_transport_proof="canonical_https_redirects",
        )

    def _rollback(
        self,
        previous: Mapping[str, Any],
        rollback_tag: str,
        baseline: Mapping[str, Any],
        deployment_input_seal: Mapping[str, Sequence[Mapping[str, object]]],
        public_origin: str,
    ) -> dict[str, Any]:
        self._require_deployment_input_seal(deployment_input_seal, scope="rollback")
        prior_openapi_value = baseline.get("openapi")
        prior_openapi = (
            dict(prior_openapi_value) if isinstance(prior_openapi_value, dict) else {}
        )
        prior_contract_value = prior_openapi.get("_contract")
        prior_contract = (
            dict(prior_contract_value) if isinstance(prior_contract_value, dict) else {}
        )
        prior_operations = dict(prior_contract.get("operations") or {})
        prior_retirement_operations = [
            operation
            for operation in OPENAPI_RETIREMENT_ALLOWED_OPERATIONS
            if operation in prior_operations
        ]
        if not prior_operations or prior_retirement_operations not in (
            [],
            list(OPENAPI_RETIREMENT_ALLOWED_OPERATIONS),
        ):
            raise DeployError("rollback_openapi_baseline_invalid")
        capsule_seal = self._rollback_capsule_seal
        if capsule_seal is None:
            raise DeployError("rollback_capsule_missing")
        if self._deployment_input_file_seal(self.rollback_capsule_path) != capsule_seal:
            raise DeployError("rollback_capsule_changed")
        protected = self._inspect_image(rollback_tag)
        if protected["image_id"] != str(previous["image_id"]):
            raise DeployError("rollback_protected_image_mismatch")
        self._require_loaded_active_recovery(
            previous=previous,
            rollback_tag=rollback_tag,
        )
        self._revalidate_rollback_external_resources(
            dict(previous["rollback_capsule_document"]),
            boundary="before_rollback",
        )
        prior_reference = _safe_tagged_image_reference(
            str(previous.get("image_reference") or ""),
            reason="rollback_image_reference_unrestorable",
        )
        rollback_env = self._rollback_environment(previous)
        self._run(
            ["docker", "image", "tag", str(previous["image_id"]), prior_reference],
            env=rollback_env,
        )
        self._require_deployment_input_seal(deployment_input_seal, scope="rollback")
        self._run(
            self._rollback_capsule_compose(
                self.rollback_capsule_path,
                "up",
                "-d",
                "--no-build",
                "--no-deps",
                "--force-recreate",
                API_SERVICE,
            ),
            cwd=self._rollback_capsule_project_directory,
            env=rollback_env,
        )
        ready = self._wait_container(API_SERVICE, require_health=True)
        current = self._inspect_container(API_SERVICE)
        self._require_compose_identity(
            current, service=API_SERVICE, reason_prefix="rollback_api"
        )
        rollback_labels = dict(dict(current.get("Config") or {}).get("Labels") or {})
        if (
            rollback_labels.get("com.docker.compose.container-number") != "1"
            or rollback_labels.get("com.docker.compose.oneoff") != "False"
            or rollback_labels.get("com.docker.compose.image")
            != str(previous.get("image_id") or "")
        ):
            raise DeployError("rollback_compose_managed_identity_mismatch")
        topology = self._compose_topology(current, reason_prefix="rollback_api")
        restored_image_id = str(current.get("Image") or "")
        if restored_image_id != str(previous["image_id"]):
            raise DeployError("rollback_image_mismatch")
        restored_reference = str(
            dict(current.get("Config") or {}).get("Image") or ""
        ).strip()
        if restored_reference != prior_reference:
            raise DeployError("rollback_image_reference_mismatch")
        if topology["working_dir"] != str(self._rollback_capsule_project_directory):
            raise DeployError("rollback_working_dir_mismatch")
        rollback_files = [str(self.rollback_capsule_path)]
        if topology["compose_config_files"] != rollback_files:
            raise DeployError("rollback_compose_topology_mismatch")
        restored_mounts = _mount_identities(current)
        restored_mount_digest = _identity_digest(restored_mounts)
        if restored_mount_digest != str(previous.get("mount_identity_sha256") or ""):
            raise DeployError("rollback_mount_identity_mismatch")
        restored_runtime_config = _container_runtime_config_digests(current)
        if restored_runtime_config["environment_sha256"] != previous.get(
            "environment_sha256"
        ):
            raise DeployError("rollback_environment_identity_mismatch")
        if restored_runtime_config["environment_count"] != previous.get(
            "environment_count"
        ):
            raise DeployError("rollback_environment_identity_mismatch")
        if restored_runtime_config["process_config_sha256"] != previous.get(
            "process_config_sha256"
        ):
            raise DeployError("rollback_process_config_identity_mismatch")
        restored_functional_identity = _container_functional_identity(current)
        if restored_functional_identity != previous.get("functional_identity"):
            expected_domains = dict(
                dict(previous.get("functional_identity") or {}).get("domains") or {}
            )
            restored_domains = dict(restored_functional_identity.get("domains") or {})
            differing_domains = sorted(
                key
                for key in {*expected_domains, *restored_domains}
                if expected_domains.get(key) != restored_domains.get(key)
            )
            safe_domain = differing_domains[0] if differing_domains else "overall"
            raise DeployError(f"rollback_functional_identity_mismatch:{safe_domain}")
        health_probe = self._wait_http(f"{self._local_origin()}/health", kind="health")
        restored_openapi = self._capture_internal_openapi_control()
        restored_openapi["public_endpoint"] = self._capture_public_openapi_retirement(
            public_origin,
            expected_source_revision=str(previous.get("source_revision") or ""),
        )
        restored_contract = dict(restored_openapi.get("_contract") or {})
        if restored_contract != prior_contract:
            raise DeployError("rollback_openapi_contract_mismatch")
        bounded_openapi_evidence = {
            key: restored_openapi[key]
            for key in (
                "path_count",
                "operation_count",
                "schema_count",
                "security_scheme_count",
                "path_set_sha256",
                "contract_sha256",
                "probe",
                "public_endpoint",
            )
        }
        return {
            "status": "pass",
            "completed_at": _utc_now(),
            "restored_image_id": restored_image_id,
            "working_dir": str(self._rollback_capsule_project_directory),
            "compose_config_files": rollback_files,
            "image_reference": restored_reference,
            "mount_identity_sha256": restored_mount_digest,
            "mount_identity_count": len(restored_mounts),
            **restored_runtime_config,
            "functional_identity_sha256": str(
                restored_functional_identity["functional_identity_sha256"]
            ),
            "container": ready,
            "health_probe": health_probe,
            "openapi": {
                **bounded_openapi_evidence,
                "matches_predeploy_contract": True,
                "retirement_policy_id": OPENAPI_RETIREMENT_POLICY_ID,
                "restored_retirement_operations": list(
                    OPENAPI_RETIREMENT_ALLOWED_OPERATIONS
                ),
            },
        }

    def preflight(self) -> dict[str, Any]:
        self._write_receipt()
        if not (self.root / ".env").is_file():
            raise DeployError("env_file_missing")
        runtime_environment_projection = _prepare_ea_runtime_environment(self.root)
        self.receipt["runtime_environment_projection"] = runtime_environment_projection
        self._write_receipt()
        if self.control_tour_slug != REQUIRED_CONTROL_TOUR_SLUG:
            raise DeployError("memorial_control_tour_slug_required")
        release_source = self._release_source_metadata()
        source_state = source_worktree_metadata(self.root, dirty_path_limit=10000)
        if bool(source_state.get("source_worktree_dirty")):
            raise DeployError("source_worktree_dirty")
        self.receipt["source_worktree"] = source_state
        self._write_receipt()
        self._detect_compose()
        previous = self._previous_api()
        self._configure_forward_topology(previous)
        self._materialize_rollback_capsule(
            dict(previous["rollback_capsule_document"]),
            dict(previous["functional_identity"]),
        )
        deployment_input_seal = self._capture_deployment_input_seal(previous)
        rollback_render = self._verify_rollback_capsule_renderability(previous)
        self._require_deployment_input_seal(deployment_input_seal)
        source_revision = self._bind_source_revision(
            str(release_source["source_revision"])
        )
        candidate = self._resolve_candidate_image(source_revision)
        candidate_promotion = self._validate_candidate_promotion_receipt(
            candidate=candidate,
            source_revision=source_revision,
        )
        authority = self._materialize_and_verify_release_evidence(
            deployment_input_seal=deployment_input_seal
        )
        self._require_deployment_input_seal(deployment_input_seal)
        target_mounts = self._validate_compose(candidate=candidate)
        self._require_deployment_input_seal(deployment_input_seal)
        public_origin = _validate_public_origin(
            str(authority.get("public_origin") or ""),
            allowed_hosts=self.allowed_public_hosts,
        )
        non_memorial_controls = self._capture_non_memorial_controls(
            public_origin=public_origin,
            expected_source_revision=str(previous["source_revision"]),
        )
        self.receipt.update(
            {
                "status": "preflight_pass",
                "source_revision": source_revision,
                "public_origin": public_origin,
                "previous_api": self._sanitized_previous_api(previous),
                "rollback_compose_files": [self.rollback_capsule_path.name],
                "rollback": {
                    "status": "available",
                    "capsule_sha256": str(
                        dict(self._rollback_capsule_seal or {}).get("sha256") or ""
                    ),
                    "image_id": previous["image_id"],
                },
            }
        )
        self._write_receipt()
        return {
            "authority": authority,
            "previous": previous,
            "rollback_render": rollback_render,
            "source_revision": source_revision,
            "public_origin": public_origin,
            "candidate": candidate,
            "candidate_promotion": candidate_promotion,
            "deployment_input_seal": deployment_input_seal,
            "non_memorial_controls": non_memorial_controls,
            "target_mounts": target_mounts,
        }

    def deploy(self, *, preflight_only: bool = False) -> dict[str, Any]:
        mutation_started = False
        rollback_tag = ""
        preparation_attempted: list[str] = []
        preparation_completed: list[str] = []
        pending_action: str | None = None
        active_action: str | None = None
        previous: dict[str, Any] = {}
        non_memorial_controls: dict[str, Any] = {}

        def persist_preparation(
            status: str,
            *,
            api_mutation_started: bool | None = None,
            api_runtime_state: str = "unchanged",
        ) -> None:
            self.receipt["preparation"] = {
                "status": status,
                "attempted_actions": list(preparation_attempted),
                "completed_actions": list(preparation_completed),
                "pending_action": pending_action,
                "active_action": active_action,
                "preparation_side_effects_possible": bool(preparation_attempted),
                "api_mutation_started": (
                    mutation_started
                    if api_mutation_started is None
                    else api_mutation_started
                ),
                "api_runtime_state": api_runtime_state,
            }
            self._write_receipt()

        self._acquire_lock()
        try:
            self._require_normalization_recovery_absent()
            self._require_joint_recovery_absent()
            context = self.preflight()
            previous = dict(context["previous"])
            non_memorial_controls = dict(context["non_memorial_controls"])
            if preflight_only:
                self.receipt["status"] = "preflight_only_pass"
                self.receipt["completed_at"] = _utc_now()
                self._clear_rollback_artifacts(
                    terminal_status="discarded_preflight_only"
                )
                self._write_receipt()
                return self.receipt

            self._require_deployment_input_seal(context["deployment_input_seal"])
            pending_action = "ensure_redis"
            persist_preparation("mutation_pending")
            with self._bounded_mutation_action():
                pending_action = None
                active_action = "ensure_redis"
                preparation_attempted.append("ensure_redis")
                persist_preparation("in_progress")
                self._ensure_redis()
            preparation_completed.append("ensure_redis")
            active_action = None
            persist_preparation("in_progress")
            pending_action = "protect_previous_image"
            persist_preparation("mutation_pending")
            with self._bounded_mutation_action():
                pending_action = None
                active_action = "protect_previous_image"
                preparation_attempted.append("protect_previous_image")
                persist_preparation("in_progress")
                rollback_tag = self._protect_previous_image(previous)
            preparation_completed.append("protect_previous_image")
            active_action = None
            self.receipt["rollback"] = {
                "status": "available",
                "capsule_sha256": str(
                    dict(self._rollback_capsule_seal or {}).get("sha256") or ""
                ),
                "image_id": previous["image_id"],
                "image_tag": rollback_tag,
            }
            self.receipt["status"] = "changing_api"
            persist_preparation("complete")

            self._require_deployment_input_seal(context["deployment_input_seal"])
            pending_action = "recreate_api"
            persist_preparation("api_mutation_pending")
            with self._bounded_mutation_action():
                self._revalidate_bind_source_access(boundary="before_recreate_api")
                self._require_deployment_input_seal(
                    context["deployment_input_seal"], scope="forward"
                )
                self._require_previous_api_unchanged(previous)
                self._require_deployment_input_seal(
                    context["deployment_input_seal"], scope="rollback"
                )
                self._arm_rollback_recovery(
                    previous=previous,
                    rollback_tag=rollback_tag,
                    non_memorial_controls=non_memorial_controls,
                    public_origin=str(context["public_origin"]),
                )
                pending_action = None
                persist_preparation(
                    "complete",
                    api_mutation_started=True,
                    api_runtime_state="mutation_possible",
                )
                self._revalidate_rollback_external_resources(
                    dict(previous["rollback_capsule_document"]),
                    boundary="before_recreate_api",
                )
                self._require_previous_api_unchanged(previous)
                self._require_deployment_input_seal(
                    context["deployment_input_seal"], scope="forward"
                )
                mutation_started = True
                self._recreate_api()
            persist_preparation(
                "complete",
                api_mutation_started=True,
                api_runtime_state="changed_pending_verification",
            )
            api_detail = self._wait_container(API_SERVICE, require_health=True)
            api_identity = self._verify_forward_api(
                candidate=dict(context["candidate"]),
                source_revision=str(context["source_revision"]),
                expected_mounts=list(context["target_mounts"]),
                expected_projection=dict(
                    dict(context["candidate_promotion"]).get("projection") or {}
                ),
            )
            self._record_check(
                "api_container", "pass", **api_detail, identity=api_identity
            )
            self._verify_deployed_surface(
                str(context["public_origin"]),
                source_revision=str(context["source_revision"]),
                candidate_promotion_evidence=dict(context["candidate_promotion"]),
            )
            self._verify_candidate_origins(str(context["public_origin"]))
            self._verify_non_memorial_controls(
                non_memorial_controls,
                public_origin=str(context["public_origin"]),
                expected_source_revision=str(context["source_revision"]),
            )

            # Rebuild the public-access projection in private release evidence only
            # after both edge probes pass. Any failure here enters rollback.
            self._materialize_and_verify_release_evidence(
                phase="postdeploy",
                deployment_input_seal=context["deployment_input_seal"],
                expected_public_origin=str(context["public_origin"]),
                expected_authority_posture=str(
                    dict(context["authority"]).get("authority_posture") or ""
                ),
            )

            self.receipt["status"] = "pass"
            self.receipt["completed_at"] = _utc_now()
            self.receipt["rollback"]["status"] = "available"
            self.receipt["preparation"].update(
                {
                    "status": "complete",
                    "api_mutation_started": True,
                    "api_runtime_state": "changed_verified",
                }
            )
            self._clear_rollback_artifacts(terminal_status="retired_after_pass")
            self._write_receipt()
            return self.receipt
        except (Exception, KeyboardInterrupt) as exc:
            original_error = str(exc) or type(exc).__name__
            self.receipt["failure"] = {
                "at": _utc_now(),
                "reason": original_error,
                "type": type(exc).__name__,
            }
            if mutation_started and previous and rollback_tag:
                try:
                    rollback = self._rollback(
                        previous,
                        rollback_tag,
                        non_memorial_controls,
                        context["deployment_input_seal"],
                        str(context["public_origin"]),
                    )
                    self.receipt["status"] = "failed_rolled_back"
                    self.receipt["rollback"] = rollback
                    self.receipt["preparation"].update(
                        {
                            "status": "api_mutation_failed_rolled_back",
                            "api_mutation_started": True,
                            "api_runtime_state": "restored_by_rollback",
                        }
                    )
                    self.receipt["completed_at"] = _utc_now()
                    self._clear_rollback_artifacts(
                        terminal_status="retired_after_verified_rollback"
                    )
                    self._write_receipt()
                    raise DeployError(
                        f"deployment_failed_rolled_back:{original_error}"
                    ) from exc
                except DeployError as rollback_exc:
                    if str(rollback_exc).startswith("deployment_failed_rolled_back:"):
                        raise
                    self.receipt["status"] = "rollback_failed"
                    self.receipt["rollback"] = {
                        "status": "fail",
                        "failed_at": _utc_now(),
                        "reason": str(rollback_exc),
                    }
                    self.receipt["preparation"].update(
                        {
                            "status": "api_mutation_rollback_failed",
                            "api_mutation_started": True,
                            "api_runtime_state": "unknown_after_failed_rollback",
                        }
                    )
                    self.receipt["completed_at"] = _utc_now()
                    self._write_receipt()
                    raise DeployError(
                        f"deployment_and_rollback_failed:{original_error}:{rollback_exc}"
                    ) from rollback_exc
            if preparation_attempted:
                failed_during_action = active_action is not None
                self.receipt["status"] = (
                    "failed_during_preparation"
                    if failed_during_action
                    else "failed_after_preparation"
                )
                self.receipt["preparation"] = {
                    "status": (
                        "failed_during_action"
                        if failed_during_action
                        else "failed_before_api_mutation"
                    ),
                    "attempted_actions": list(preparation_attempted),
                    "completed_actions": list(preparation_completed),
                    "pending_action": pending_action,
                    "active_action": active_action,
                    "preparation_side_effects_possible": True,
                    "api_mutation_started": False,
                    "api_runtime_state": "unchanged",
                    "rollback_required": False,
                }
                self.receipt["rollback"] = {
                    "status": "not_required",
                    "reason": "api_unchanged",
                    **({"protected_image_tag": rollback_tag} if rollback_tag else {}),
                }
            else:
                if pending_action is not None:
                    self.receipt["preparation"] = {
                        "status": "mutation_setup_failed",
                        "attempted_actions": [],
                        "completed_actions": [],
                        "pending_action": pending_action,
                        "active_action": None,
                        "preparation_side_effects_possible": False,
                        "api_mutation_started": False,
                        "api_runtime_state": "unchanged",
                    }
                self.receipt["status"] = "preflight_failed"
            if not mutation_started and self._rollback_capsule_seal is not None:
                safe_to_clear = self._rollback_recovery_seal is None
                if self._rollback_recovery_seal is not None and previous:
                    try:
                        current = self._inspect_container(API_SERVICE)
                        safe_to_clear = _container_functional_identity(
                            current
                        ) == previous.get("functional_identity")
                    except DeployError:
                        safe_to_clear = False
                if safe_to_clear:
                    self._clear_rollback_artifacts(
                        terminal_status="retired_before_api_mutation"
                    )
            self.receipt["completed_at"] = _utc_now()
            self._write_receipt()
            if isinstance(exc, DeployError):
                raise
            if isinstance(exc, KeyboardInterrupt):
                raise
            raise DeployError(original_error) from exc
        finally:
            self._release_lock()


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Deploy only ea-api for the governed public Manfred memorial lane."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--preflight-only",
        action="store_true",
        help="Run evidence, Compose, rollback-input, and origin checks without Docker mutations.",
    )
    mode.add_argument(
        "--recover-active",
        action="store_true",
        help="Recover or retire the single validated active API rollback transaction.",
    )
    parser.add_argument("--wait-seconds", type=float, default=90.0)
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--request-timeout-seconds", type=float, default=10.0)
    parser.add_argument("--receipt-dir", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        lane = MemorialDeployLane(
            wait_seconds=args.wait_seconds,
            poll_seconds=args.poll_seconds,
            request_timeout_seconds=args.request_timeout_seconds,
            receipt_dir=args.receipt_dir,
        )
        receipt = (
            lane.recover_active()
            if bool(args.recover_active)
            else lane.deploy(preflight_only=bool(args.preflight_only))
        )
    except KeyboardInterrupt:
        print("memorial deploy interrupted", file=sys.stderr)
        return 130
    except DeployError as exc:
        print(f"memorial deploy failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
