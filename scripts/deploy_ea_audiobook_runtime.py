#!/usr/bin/env python3
"""Governed, fail-closed deployment lane for the EA audiobook runtime.

This lane deliberately does not inherit from the memorial deployment lane and
does not call the legacy general deployer. It validates a proposed paused worker
stage while preserving the memorial-owned ``ea-api`` exactly.

The default command is preflight-only. ``--execute`` can create only the exact
stopped worker stage after atomically consuming a distinct root-owned one-shot
permit; it never starts or activates that stage. No reachable command builds,
pulls, uploads, sends a message, calls a provider, or changes ingress/webhooks.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import math
import os
import re
import shutil
import stat
import subprocess  # nosec B404 - all mutable command vectors are fixed below
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Protocol, Sequence

try:
    from scripts.vexp_schema_v6_authority import (
        QualificationEvidence,
        SchemaV6AuthorityError,
        load_schema_v6_qualification,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from vexp_schema_v6_authority import (  # type: ignore[no-redef]
        QualificationEvidence,
        SchemaV6AuthorityError,
        load_schema_v6_qualification,
    )


ROOT = Path(__file__).resolve().parents[1]
UTC = timezone.utc
PROJECT_NAME = "ea"
API_SERVICE = "ea-api"
WORKER_SERVICES = (
    "ea-worker",
    "ea-scheduler",
    "ea-whatsapp-web-action-processor",
)
TARGET_SERVICES = (API_SERVICE, *WORKER_SERVICES)
EXPECTED_RUNTIME_SERVICES = (
    "ea-api",
    "ea-db",
    "ea-proactive-ooda",
    "ea-redis",
    "ea-responses-proxy",
    "ea-scheduler",
    "ea-teable-relay",
    "ea-telegram-teable-sync",
    "ea-whatsapp-web-action-processor",
    "ea-whatsapp-web-activator",
    "ea-whatsapp-web-session",
    "ea-whatsapp-web-teable-sync",
    "ea-worker",
)
PRESERVED_RUNTIME_SERVICES = tuple(
    service for service in EXPECTED_RUNTIME_SERVICES if service not in WORKER_SERVICES
)
PRODUCTION_BASE_COMPOSE_FILES = (
    "docker-compose.yml",
    "docker-compose.memorial.yml",
    "docker-compose.whatsapp-web-session.yml",
)
INERT_CANDIDATE_OVERLAY = Path(
    "deploy/audiobook-runtime-candidate/docker-compose.candidate.yml"
)
PRODUCTION_OVERLAY_ENV = "EA_AUDIOBOOK_RUNTIME_PRODUCTION_OVERLAY"
PRODUCTION_OVERLAY = Path(
    "deploy/audiobook-runtime-production/docker-compose.production-stage.yml"
)
PRODUCTION_COMPOSE_SOURCE_PATHS = tuple(
    Path(value) for value in (*PRODUCTION_BASE_COMPOSE_FILES, str(PRODUCTION_OVERLAY))
)

DEPLOY_RECEIPT_CONTRACT = "ea.audiobook_runtime_governed_deploy.v1"
CANDIDATE_PREFLIGHT_CONTRACT = "ea.audiobook_runtime_candidate_preflight.v1"
CANDIDATE_CONFIGURATION_CONTRACT = "ea.audiobook_runtime_candidate_configuration.v1"
CANDIDATE_PROVENANCE_CONTRACT = "ea.audiobook_runtime_candidate_provenance.v1"
PRODUCTION_PREFLIGHT_CONTRACT = "ea.audiobook_runtime_production_preflight.v1"
PRODUCTION_PROJECTION_CONTRACT = "ea.audiobook_runtime_production_projection.v1"
STAGE_OWNER_PERMIT_CONTRACT = "ea.audiobook_runtime_stage_owner_permit.v1"
ACTIVE_TOPOLOGY_CONTRACT = "ea.audiobook_runtime_active_topology.v1"
MEMORIAL_BASELINE_CONTRACT = "ea.memorial_runtime_baseline.v1"
PRODUCTION_PROVENANCE_CONTRACT = "ea.audiobook_runtime_image_provenance.v1"
PRODUCTION_SBOM_CONTRACT = "ea.audiobook_runtime_image_sbom.v1"

DEFAULT_SCHEMA_V6_PERMIT_PATH = Path("/run/ea/memorial-vexp-mutation-permit.json")
DEFAULT_STAGE_OWNER_PERMIT_PATH = Path(
    "/run/ea/audiobook-runtime-stage-owner-permit.json"
)
DEFAULT_SCHEMA_V6_PERMIT_LOCK_PATH = Path("/run/ea/memorial-vexp-mutation-permit.lock")
DEFAULT_STAGE_OWNER_PERMIT_LOCK_PATH = Path(
    "/run/ea/audiobook-runtime-stage-owner-permit.lock"
)
DEFAULT_GLOBAL_LOCK_PATH = Path("/run/lock/ea-audiobook-runtime.lock")
DEFAULT_MEMORIAL_API_LOCK_PATH = Path("/run/lock/ea-memorial-ea-api.lock")

DEPLOYMENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
IMAGE_ID_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
SOURCE_REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
MAC_ADDRESS_RE = re.compile(r"^(?:[0-9a-f]{2}:){5}[0-9a-f]{2}$")
URN_RE = re.compile(r"^urn:[A-Za-z0-9][A-Za-z0-9:._/-]{2,255}$")
DIGEST_IMAGE_RE = re.compile(
    r"^[a-z0-9]+(?:[._-][a-z0-9]+)*(?::[0-9]+)?"
    r"(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)*@sha256:[0-9a-f]{64}$"
)
TAGGED_IMAGE_RE = re.compile(
    r"^[a-z0-9]+(?:[._-][a-z0-9]+)*(?::[0-9]+)?"
    r"(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)*:"
    r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$"
)
UTC_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$")

MAX_AUTHORITY_BYTES = 64 * 1024
MAX_EVIDENCE_BYTES = 2 * 1024 * 1024
MAX_HTTP_BYTES = 2 * 1024 * 1024
MAX_COMPOSE_INPUT_BYTES = 8 * 1024 * 1024
DEFAULT_DOCKER_SHM_SIZE = 64 * 1024 * 1024
MAX_CLOCK_SKEW = timedelta(seconds=30)
MAX_SENTINEL_AGE = timedelta(minutes=5)
EXPECTED_VEXP_VERSION = 6
MINIMUM_VEXP_QUALIFICATION_AT = datetime(2026, 7, 20, 9, 43, 56, 206_000, tzinfo=UTC)
MINIMUM_VEXP_SOAK = timedelta(days=7)
MAX_VEXP_MUTATION_ACTION_SECONDS = 180.0
ROOT_AUTHORITY_UID = 0
GIT_SAFE_PATH = "/usr/bin:/bin"
GIT_FIXED_CONFIG = (
    ("core.fsmonitor", "false"),
    ("core.untrackedCache", "false"),
    ("core.hooksPath", "/dev/null"),
    ("core.attributesFile", "/dev/null"),
    ("core.excludesFile", "/dev/null"),
    ("diff.external", ""),
)
PAUSED_STAGE_MUTATION_ACTIONS = (
    "protect_exact_prior_images",
    "apply_exact_paused_stage",
    "verify_exact_paused_stage",
    "rollback_exact_pre_state_on_any_failure",
)

PAUSED_STAGE_COMMON_ENV = {
    "EA_AUDIOBOOK_RUNTIME_STAGE_ONLY": "1",
    "EA_AUDIOBOOK_RUNTIME_ACTIVATION_AUTHORITY": "0",
    "EA_AUDIOBOOK_RUNTIME_QUEUE_MUTATION_AUTHORITY": "0",
    "EA_AUDIOBOOK_RUNTIME_PROVIDER_WORK_AUTHORITY": "0",
    "EA_AUDIOBOOK_RUNTIME_OUTBOUND_SEND_AUTHORITY": "0",
    "EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED": "0",
    "EA_AUDIOBOOK_UNMIXR_AUTO_RENDER": "0",
    "EA_AUDIOBOOK_CINEMATIC_NARRATION": "0",
    "EA_AUDIOBOOKSHELF_AUTO_IMPORT": "0",
    "EA_AUDIOBOOKSHELF_PUBLIC_SHARE_ENABLED": "0",
}
PAUSED_STAGE_SERVICE_ENV: Mapping[str, Mapping[str, str]] = {
    "ea-worker": {
        **PAUSED_STAGE_COMMON_ENV,
        "EA_TELEGRAM_AUDIOBOOK_EPUB_ENABLED": "0",
        "EA_ANSWERLY_AUTO_IMPORT_GMAIL_PDFS": "0",
    },
    "ea-scheduler": {
        **PAUSED_STAGE_COMMON_ENV,
        "EA_TELEGRAM_AUDIOBOOK_EPUB_ENABLED": "0",
        "EA_ANSWERLY_AUTO_IMPORT_GMAIL_PDFS": "0",
    },
    "ea-whatsapp-web-action-processor": {
        **PAUSED_STAGE_COMMON_ENV,
        "EA_WHATSAPP_WEB_ACTION_PROCESSOR_ENABLED": "0",
        "EA_WHATSAPP_AUDIOBOOK_RESUME_DUE": "0",
        "EA_WHATSAPP_AUDIOBOOK_FOLLOWUP_ENABLED": "0",
        "EA_WHATSAPP_WEB_TG_SUMMARY_ENABLED": "0",
    },
}
PAUSED_STAGE_LABELS = {
    "com.archonmegalon.ea.audiobook-runtime.contract": (
        "ea.audiobook_runtime_production_stage_overlay.v1"
    ),
    "com.archonmegalon.ea.audiobook-runtime.deployment-scope": ("paused_stage_only"),
    "com.archonmegalon.ea.audiobook-runtime.activation-authority": "denied",
    "com.archonmegalon.ea.audiobook-runtime.live-api-owner": "memorial",
}
PAUSED_STAGE_IDLE_COMMAND = [
    "/bin/sh",
    "-ec",
    'echo \'{"contract":"ea.audiobook_runtime_production_stage_overlay.v1",'
    '"event":"paused_stage_idle","ok":true}\'; '
    "while :; do sleep 3600; done",
]
COMMON_PAUSED_STAGE_SERVICE_KEYS = frozenset(
    {
        "cap_drop",
        "command",
        "container_name",
        "cpu_shares",
        "cpus",
        "deploy",
        "entrypoint",
        "environment",
        "healthcheck",
        "image",
        "labels",
        "networks",
        "pull_policy",
        "read_only",
        "restart",
        "security_opt",
        "tmpfs",
        "user",
        "working_dir",
    }
)
PAUSED_STAGE_SERVICE_KEYS = {
    "ea-worker": COMMON_PAUSED_STAGE_SERVICE_KEYS | {"pids_limit"},
    "ea-scheduler": COMMON_PAUSED_STAGE_SERVICE_KEYS | {"pids_limit"},
    "ea-whatsapp-web-action-processor": COMMON_PAUSED_STAGE_SERVICE_KEYS,
}
PAUSED_STAGE_RESOURCES: Mapping[str, Mapping[str, object]] = {
    "ea-worker": {"cpu_shares": 128, "cpus": 0.75, "pids_limit": 512},
    "ea-scheduler": {"cpu_shares": 128, "cpus": 0.75, "pids_limit": 512},
    "ea-whatsapp-web-action-processor": {"cpu_shares": 32, "cpus": 0.5},
}

# Docker inspect is an authority input for exact rollback. Unknown mutable
# fields must stop preflight instead of being silently omitted from the digest.
RESTORABLE_HOST_CONFIG_KEYS = frozenset(
    {
        "Annotations",
        "AutoRemove",
        "Binds",
        "BlkioDeviceReadBps",
        "BlkioDeviceReadIOps",
        "BlkioDeviceWriteBps",
        "BlkioDeviceWriteIOps",
        "BlkioWeight",
        "BlkioWeightDevice",
        "CapAdd",
        "CapDrop",
        "Cgroup",
        "CgroupParent",
        "CgroupnsMode",
        "ConsoleSize",
        "ContainerIDFile",
        "CpuCount",
        "CpuPercent",
        "CpuPeriod",
        "CpuQuota",
        "CpuRealtimePeriod",
        "CpuRealtimeRuntime",
        "CpuShares",
        "CpusetCpus",
        "CpusetMems",
        "DeviceCgroupRules",
        "DeviceRequests",
        "Devices",
        "Dns",
        "DnsOptions",
        "DnsSearch",
        "ExtraHosts",
        "GroupAdd",
        "IOMaximumBandwidth",
        "IOMaximumIOps",
        "Init",
        "IpcMode",
        "Isolation",
        "Links",
        "LogConfig",
        "MaskedPaths",
        "Memory",
        "MemoryReservation",
        "MemorySwap",
        "MemorySwappiness",
        "Mounts",
        "NanoCpus",
        "NetworkMode",
        "OomKillDisable",
        "OomScoreAdj",
        "PidMode",
        "PidsLimit",
        "PortBindings",
        "Privileged",
        "PublishAllPorts",
        "ReadonlyPaths",
        "ReadonlyRootfs",
        "RestartPolicy",
        "Runtime",
        "SecurityOpt",
        "ShmSize",
        "StorageOpt",
        "Sysctls",
        "Tmpfs",
        "Ulimits",
        "UTSMode",
        "UsernsMode",
        "VolumeDriver",
        "VolumesFrom",
    }
)
RESTORABLE_CONFIG_KEYS = frozenset(
    {
        "ArgsEscaped",
        "AttachStderr",
        "AttachStdin",
        "AttachStdout",
        "Cmd",
        "Domainname",
        "Entrypoint",
        "Env",
        "ExposedPorts",
        "Healthcheck",
        "Hostname",
        "Image",
        "Labels",
        "MacAddress",
        "NetworkDisabled",
        "OnBuild",
        "OpenStdin",
        "Shell",
        "StdinOnce",
        "StopSignal",
        "StopTimeout",
        "Tty",
        "User",
        "Volumes",
        "WorkingDir",
    }
)
RESTORABLE_NETWORK_ENDPOINT_KEYS = frozenset(
    {
        "Aliases",
        "DNSNames",
        "DriverOpts",
        "EndpointID",
        "Gateway",
        "GlobalIPv6Address",
        "GlobalIPv6PrefixLen",
        "GwPriority",
        "IPAMConfig",
        "IPAddress",
        "IPPrefixLen",
        "IPv6Gateway",
        "Links",
        "MacAddress",
        "NetworkID",
    }
)
RESTORABLE_NETWORK_IPAM_KEYS = frozenset({"IPv4Address", "IPv6Address", "LinkLocalIPs"})
RESTORABLE_RENDERED_NETWORK_ENDPOINT_KEYS = frozenset(
    {
        "aliases",
        "driver_opts",
        "gw_priority",
        "ipv4_address",
        "ipv6_address",
        "link_local_ips",
        "mac_address",
        "priority",
    }
)
RESTORABLE_INSPECTION_MOUNT_KEYS = frozenset(
    {
        "Destination",
        "Driver",
        "Mode",
        "Name",
        "Propagation",
        "RW",
        "Source",
        "SubPath",
        "Type",
    }
)

INERT_CONFIGURATION_AUTHORITY_FIELDS = (
    "configuration_authority",
    "deployment_authority",
    "promotion_authority",
    "live_mutation_authority",
    "runtime_execution_authority",
    "queue_mutation_authority",
    "provider_work_authority",
    "outbound_send_authority",
    "build_authority",
    "pull_authority",
)

PRODUCTION_ROOT_KEYS = frozenset(
    {
        "contract_name",
        "version",
        "status",
        "verification_mode",
        "verified_at",
        "mutations_performed",
        "preparation_valid",
        "non_transferable",
        "deploy_ready",
        "deployment_scope",
        "stage_deploy_eligible",
        "stage_mutation_authority",
        "deployment_authority",
        "group_deploy_eligible",
        "runtime_activation_authority",
        "queue_mutation_authority",
        "provider_work_authority",
        "outbound_send_authority",
        "build_authority",
        "pull_authority",
        "issues",
        "production_projection",
        "next_action",
    }
)
PRODUCTION_PROJECTION_KEYS = frozenset(
    {
        "contract_name",
        "version",
        "status",
        "configuration_only",
        "configuration_valid",
        "preparation_valid",
        "non_transferable",
        "deploy_ready",
        "deployment_scope",
        "stage_deploy_eligible",
        "stage_mutation_authority",
        "deployment_authority",
        "group_deploy_eligible",
        "runtime_activation_authority",
        "queue_mutation_authority",
        "provider_work_authority",
        "outbound_send_authority",
        "build_authority",
        "pull_authority",
        "target_services",
        "stage_mutation_services",
        "preserved_services",
        "source_revision",
        "candidate_image_reference",
        "candidate_image_id",
        "compose_source_inventory",
        "compose_source_inventory_sha256",
        "overlay_path",
        "overlay_blob_sha256",
        "overlay_working_sha256",
        "rendered_compose_sha256",
        "memorial_baseline",
        "stage_projection_sha256",
        "provenance",
        "sbom",
        "live_api_owner",
        "live_api_mutation_authority",
        "owner_handoff_required",
        "owner_handoff_performed",
        "owner_preservation_permit_required",
        "required_owner_permit_contract",
        "silent_takeover_allowed",
        "memorial_compatible",
        "schema_v6_qualification",
        "side_effect_posture",
    }
)
QUALIFICATION_PROJECTION_KEYS = frozenset(
    {
        "state_version",
        "state_sha256",
        "terminal_identity_sha256",
        "qualified_at",
        "permit_contract_name",
        "permit_sha256",
        "permit_expires_at",
        "evidence_scope",
        "mutation_authority_transferred",
        "validated",
    }
)
MEMORIAL_BASELINE_SUMMARY_KEYS = frozenset(
    {
        "contract_name",
        "receipt_sha256",
        "source_revision",
        "compose_inventory_sha256",
        "rendered_compose_sha256",
        "ea_api_sha256",
    }
)
PROVENANCE_SUMMARY_KEYS = frozenset(
    {
        "contract_name",
        "sha256",
        "source_revision",
        "image_reference",
        "image_id",
    }
)
SBOM_SUMMARY_KEYS = frozenset(
    {
        "contract_name",
        "sha256",
        "document_namespace",
        "serial_number",
        "subject_name",
        "subject_image_reference",
        "subject_image_id",
        "subject_source_revision",
    }
)
MEMORIAL_BASELINE_RECEIPT_KEYS = frozenset(
    {
        "contract_name",
        "version",
        "status",
        "issuer",
        "source_revision",
        "compose_source_inventory",
        "compose_source_inventory_sha256",
        "rendered_compose_sha256",
        "ea_api_sha256",
        "issued_at",
        "expires_at",
    }
)
PROVENANCE_RECEIPT_KEYS = frozenset(
    {
        "contract_name",
        "version",
        "status",
        "source_revision",
        "image_reference",
        "image_id",
        "sbom_sha256",
    }
)
SBOM_RECEIPT_KEYS = frozenset(
    {
        "contract_name",
        "version",
        "status",
        "document_namespace",
        "serial_number",
        "subject_name",
        "subject_image_reference",
        "subject_image_id",
        "subject_source_revision",
        "bom",
    }
)
SIDE_EFFECT_POSTURE_KEYS = frozenset(
    {
        "deployment_hold",
        "replicas_zero",
        "idle_command_bound",
        "queue_mutation_authority",
        "provider_work_authority",
        "outbound_send_authority",
        "runtime_activation_authority",
    }
)
STAGE_OWNER_PERMIT_KEYS = frozenset(
    {
        "contract_name",
        "version",
        "status",
        "issuer",
        "permit_id",
        "nonce",
        "deployment_id",
        "single_use",
        "scope",
        "live_api_owner",
        "owner_decision",
        "stage_projection_sha256",
        "production_preflight_sha256",
        "consumer_preflight_receipt_sha256",
        "source_revision",
        "candidate_image_reference",
        "candidate_image_id",
        "compose_source_inventory_sha256",
        "overlay_blob_sha256",
        "rendered_compose_sha256",
        "memorial_baseline_receipt_sha256",
        "memorial_ea_api_sha256",
        "stage_mutation_services",
        "preserved_services",
        "pre_state_sha256",
        "target_compose_sha256",
        "target_compose_config_sha256",
        "rollback_plan_sha256",
        "forward_input_plan_sha256",
        "schema_v6_terminal_identity_sha256",
        "schema_v6_permit_sha256",
        "provenance_sha256",
        "sbom_sha256",
        "allowed_actions",
        "issued_at",
        "expires_at",
        "stage_mutation_authority",
        "deployment_authority",
        "group_deploy_eligible",
        "live_api_mutation_authority",
        "runtime_activation_authority",
        "queue_mutation_authority",
        "provider_work_authority",
        "outbound_send_authority",
        "build_authority",
        "pull_authority",
    }
)
PROJECTION_CORE_KEYS = (
    "contract_name",
    "deployment_scope",
    "target_services",
    "stage_mutation_services",
    "preserved_services",
    "source_revision",
    "candidate_image_reference",
    "candidate_image_id",
    "compose_source_inventory",
    "compose_source_inventory_sha256",
    "overlay_path",
    "overlay_blob_sha256",
    "overlay_working_sha256",
    "rendered_compose_sha256",
    "memorial_baseline",
    "schema_v6_terminal_identity_sha256",
    "provenance",
    "sbom",
    "live_api_owner",
    "live_api_mutation_authority",
    "runtime_activation_authority",
    "queue_mutation_authority",
    "provider_work_authority",
    "outbound_send_authority",
    "build_authority",
    "pull_authority",
)


class DeployError(RuntimeError):
    """A stable, non-secret deployment failure."""


class Runner(Protocol):
    def run(
        self,
        args: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]: ...

    def run_bytes(
        self,
        args: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        check: bool = True,
    ) -> subprocess.CompletedProcess[bytes]: ...


class SubprocessRunner:
    def run(
        self,
        args: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        completed = subprocess.run(  # nosec B603 - fixed vectors, no shell
            list(args),
            cwd=cwd,
            env=dict(env),
            capture_output=True,
            text=True,
            check=False,
        )
        if check and completed.returncode != 0:
            executable = Path(str(args[0] or "command")).name or "command"
            raise DeployError(f"command_failed:{completed.returncode}:{executable}")
        return completed

    def run_bytes(
        self,
        args: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        check: bool = True,
    ) -> subprocess.CompletedProcess[bytes]:
        completed = subprocess.run(  # nosec B603 - fixed vectors, no shell
            list(args),
            cwd=cwd,
            env=dict(env),
            capture_output=True,
            text=False,
            check=False,
        )
        if check and completed.returncode != 0:
            executable = Path(str(args[0] or "command")).name or "command"
            raise DeployError(f"command_failed:{completed.returncode}:{executable}")
        return completed


@dataclass(frozen=True)
class TrustedDocument:
    path: Path
    payload: dict[str, Any]
    sha256: str
    device: int
    inode: int
    size: int
    mtime_ns: int
    ctime_ns: int
    mode: int
    uid: int


@dataclass(frozen=True)
class GitRepositoryBinding:
    work_tree: Path
    git_dir: Path
    common_dir: Path
    head_commit: str
    work_tree_identity: tuple[int, int, int, int, int]
    git_dir_identity: tuple[int, int, int, int, int]
    common_dir_identity: tuple[int, int, int, int, int]


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def _parse_time(value: object, reason: str) -> datetime:
    if not isinstance(value, str) or not UTC_TIMESTAMP_RE.fullmatch(value):
        raise DeployError(reason)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DeployError(reason) from exc
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise DeployError(reason)
    return parsed.astimezone(UTC)


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _datetime_epoch_ms(value: datetime) -> int:
    delta = value - datetime(1970, 1, 1, tzinfo=UTC)
    return delta.days * 86_400_000 + delta.seconds * 1_000 + delta.microseconds // 1_000


def _vexp_terminal_identity(state: Mapping[str, Any]) -> dict[str, object]:
    return {
        "epoch_started_at": state.get("epoch_started_at"),
        "epoch_started_ms": state.get("epoch_started_ms"),
        "qualification_earliest_completion_at": state.get(
            "qualification_earliest_completion_at"
        ),
        "qualified_at": state.get("qualified_at"),
    }


def _vexp_terminal_identity_sha256(state: Mapping[str, Any]) -> str:
    return _canonical_sha256(_vexp_terminal_identity(state))


def _root_authority_anchor_is_trusted(
    opened: os.stat_result,
    current: os.stat_result,
) -> bool:
    """Require the descriptor and path views to identify one safe root."""

    return (
        stat.S_ISDIR(opened.st_mode)
        and stat.S_ISDIR(current.st_mode)
        and opened.st_uid == ROOT_AUTHORITY_UID
        and current.st_uid == ROOT_AUTHORITY_UID
        and stat.S_IMODE(opened.st_mode) & 0o022 == 0
        and stat.S_IMODE(current.st_mode) & 0o022 == 0
        and opened.st_dev == current.st_dev
        and opened.st_ino == current.st_ino
    )


def _open_absolute_nofollow(
    path: Path,
    *,
    flags: int,
    reason: str,
    require_root_parents: bool,
) -> int:
    if not path.is_absolute() or path.name in {"", ".", ".."}:
        raise DeployError(f"{reason}_location_invalid")
    required = ("O_NOFOLLOW", "O_NONBLOCK", "O_DIRECTORY")
    if any(not hasattr(os, name) for name in required):
        raise DeployError(f"{reason}_safe_open_unavailable")
    components = path.parts[1:]
    if not components or any(component in {"", ".", ".."} for component in components):
        raise DeployError(f"{reason}_location_invalid")
    directory_fd = -1
    try:
        directory_fd = os.open(
            "/",
            os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW,
        )
        root_metadata = os.fstat(directory_fd)
        if require_root_parents:
            current_root = os.stat("/", follow_symlinks=False)
            if not _root_authority_anchor_is_trusted(root_metadata, current_root):
                raise DeployError(f"{reason}_root_anchor_untrusted")
        elif not stat.S_ISDIR(root_metadata.st_mode):
            raise DeployError(f"{reason}_parent_untrusted")
        for component in components[:-1]:
            next_fd = os.open(
                component,
                os.O_RDONLY
                | os.O_CLOEXEC
                | os.O_DIRECTORY
                | os.O_NOFOLLOW
                | os.O_NONBLOCK,
                dir_fd=directory_fd,
            )
            os.close(directory_fd)
            directory_fd = next_fd
            metadata = os.fstat(directory_fd)
            if not stat.S_ISDIR(metadata.st_mode) or (
                require_root_parents
                and (metadata.st_uid != 0 or stat.S_IMODE(metadata.st_mode) & 0o022)
            ):
                raise DeployError(f"{reason}_parent_untrusted")
        return os.open(
            components[-1],
            flags | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=directory_fd,
        )
    except DeployError:
        raise
    except OSError as exc:
        raise DeployError(f"{reason}_unavailable") from exc
    finally:
        if directory_fd >= 0:
            os.close(directory_fd)


def _read_trusted_json(
    path: Path,
    *,
    expected_uid: int,
    expected_mode: int = 0o600,
    maximum_bytes: int,
    reason_prefix: str,
) -> TrustedDocument:
    descriptor = -1
    try:
        descriptor = _open_absolute_nofollow(
            path,
            flags=os.O_RDONLY,
            reason=reason_prefix,
            require_root_parents=expected_uid == 0,
        )
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != expected_uid
            or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) != expected_mode
        ):
            raise DeployError(f"{reason_prefix}_untrusted")
        if not 0 < before.st_size <= maximum_bytes:
            raise DeployError(f"{reason_prefix}_size_invalid")
        chunks: list[bytes] = []
        remaining = maximum_bytes + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(remaining, 64 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(descriptor)
    except OSError as exc:
        raise DeployError(f"{reason_prefix}_unreadable") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    final_descriptor = -1
    try:
        final_descriptor = _open_absolute_nofollow(
            path,
            flags=os.O_RDONLY,
            reason=reason_prefix,
            require_root_parents=expected_uid == 0,
        )
        final_path = os.fstat(final_descriptor)
    finally:
        if final_descriptor >= 0:
            os.close(final_descriptor)
    identity_fields = (
        "st_dev",
        "st_ino",
        "st_mode",
        "st_uid",
        "st_gid",
        "st_nlink",
        "st_size",
        "st_mtime_ns",
        "st_ctime_ns",
    )
    if (
        len(raw) != before.st_size
        or len(raw) > maximum_bytes
        or any(
            getattr(before, field) != getattr(after, field)
            or getattr(before, field) != getattr(final_path, field)
            for field in identity_fields
        )
    ):
        raise DeployError(f"{reason_prefix}_changed")
    try:

        def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("duplicate_json_key")
                result[key] = value
            return result

        def reject_constant(_value: str) -> None:
            raise ValueError("non_finite_json_constant")

        payload = json.loads(
            raw,
            object_pairs_hook=unique_object,
            parse_constant=reject_constant,
        )
    except Exception as exc:
        raise DeployError(f"{reason_prefix}_json_invalid") from exc
    if not isinstance(payload, dict):
        raise DeployError(f"{reason_prefix}_json_invalid")
    return TrustedDocument(
        path=path,
        payload=dict(payload),
        sha256=hashlib.sha256(raw).hexdigest(),
        device=before.st_dev,
        inode=before.st_ino,
        size=before.st_size,
        mtime_ns=before.st_mtime_ns,
        ctime_ns=before.st_ctime_ns,
        mode=before.st_mode,
        uid=before.st_uid,
    )


def _document_unchanged(
    expected: TrustedDocument,
    *,
    expected_uid: int,
    expected_mode: int = 0o600,
    maximum_bytes: int,
    reason: str,
) -> TrustedDocument:
    current = _read_trusted_json(
        expected.path,
        expected_uid=expected_uid,
        expected_mode=expected_mode,
        maximum_bytes=maximum_bytes,
        reason_prefix=reason,
    )
    if (
        current.sha256 != expected.sha256
        or current.device != expected.device
        or current.inode != expected.inode
        or current.size != expected.size
        or current.mtime_ns != expected.mtime_ns
        or current.ctime_ns != expected.ctime_ns
        or current.mode != expected.mode
        or current.uid != expected.uid
    ):
        raise DeployError(f"{reason}_changed")
    return current


def _contract_name(payload: Mapping[str, Any]) -> str:
    return str(payload.get("contract_name") or payload.get("schema") or "")


def _environment_map(entries: Sequence[object]) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in entries:
        if not isinstance(raw, str) or "=" not in raw or "\x00" in raw:
            raise DeployError("container_environment_invalid")
        name, value = raw.split("=", 1)
        if not name:
            raise DeployError("container_environment_invalid")
        result[name] = value
    return result


def _rendered_environment(service: Mapping[str, Any]) -> dict[str, str]:
    value = service.get("environment")
    if isinstance(value, dict):
        return {str(key): str(raw) for key, raw in value.items() if raw is not None}
    if isinstance(value, list):
        return _environment_map(value)
    if value is None:
        return {}
    raise DeployError("rendered_environment_invalid")


def _mounts_from_inspection(inspection: Mapping[str, Any]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for raw in list(inspection.get("Mounts") or []):
        if not isinstance(raw, dict):
            raise DeployError("container_mount_invalid")
        if not set(raw).issubset(RESTORABLE_INSPECTION_MOUNT_KEYS):
            raise DeployError("container_mount_field_unsupported")
        source = str(
            raw.get("Name")
            if str(raw.get("Type") or "") == "volume" and raw.get("Name")
            else (raw.get("Source") or "")
        )
        rows.append(
            {
                "type": str(raw.get("Type") or ""),
                "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
                "destination": str(raw.get("Destination") or ""),
                "read_write": bool(raw.get("RW")),
                "driver": str(raw.get("Driver") or ""),
                "mode": str(raw.get("Mode") or ""),
                "propagation": str(raw.get("Propagation") or ""),
                "subpath": str(raw.get("SubPath") or ""),
            }
        )
    return sorted(rows, key=lambda row: str(row["destination"]))


def _rendered_mounts(service: Mapping[str, Any]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for raw in list(service.get("volumes") or []):
        if not isinstance(raw, dict):
            raise DeployError("rendered_mount_invalid")
        source = str(raw.get("source") or "")
        target = str(raw.get("target") or raw.get("destination") or "")
        bind = dict(raw.get("bind") or {})
        volume = dict(raw.get("volume") or {})
        raw_mode = str(raw.get("consistency") or "")
        rows.append(
            {
                "type": str(raw.get("type") or ""),
                "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
                "destination": target,
                "read_write": not bool(raw.get("read_only")),
                "driver": str(volume.get("driver") or ""),
                "mode": raw_mode,
                "propagation": str(bind.get("propagation") or ""),
                "subpath": str(volume.get("subpath") or ""),
            }
        )
    return sorted(rows, key=lambda row: str(row["destination"]))


def _safe_error(exc: BaseException) -> str:
    value = str(exc)
    if re.fullmatch(r"[a-z0-9_.:-]{1,200}", value):
        return value
    return "audiobook_runtime_deployment_failed"


def _ensure_private_directory(path: Path) -> None:
    absolute = path.absolute()
    if os.path.lexists(absolute) and absolute.is_symlink():
        raise DeployError("receipt_directory_untrusted")
    absolute.mkdir(parents=True, exist_ok=True, mode=0o700)
    if absolute.resolve() != absolute:
        raise DeployError("receipt_directory_untrusted")
    flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(absolute, flags)
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) != 0o700
        ):
            raise DeployError("receipt_directory_untrusted")
    finally:
        os.close(descriptor)


def _fsync_directory(path: Path, *, reason: str) -> None:
    flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = -1
    try:
        descriptor = os.open(path, flags)
        metadata = os.fstat(descriptor)
        if not stat.S_ISDIR(metadata.st_mode):
            raise DeployError(f"{reason}_untrusted")
        os.fsync(descriptor)
    except OSError as exc:
        raise DeployError(f"{reason}_fsync_failed") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _trusted_input_sha256(path: Path, *, allowed_uids: set[int], reason: str) -> str:
    if not hasattr(os, "O_NOFOLLOW"):
        raise DeployError(f"{reason}_nofollow_unavailable")
    descriptor = -1
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    except OSError as exc:
        raise DeployError(f"{reason}_unavailable") from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid not in allowed_uids
            or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) & 0o022
            or not 0 < before.st_size <= MAX_COMPOSE_INPUT_BYTES
        ):
            raise DeployError(f"{reason}_untrusted")
        digest = hashlib.sha256()
        total = 0
        while True:
            chunk = os.read(descriptor, 64 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_COMPOSE_INPUT_BYTES:
                raise DeployError(f"{reason}_size_invalid")
            digest.update(chunk)
        after = os.fstat(descriptor)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if total != before.st_size or (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    ) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise DeployError(f"{reason}_changed")
    return digest.hexdigest()


def _copy_trusted_input(
    source: Path,
    destination: Path,
    *,
    expected_sha256: str,
    allowed_uids: set[int],
    reason: str,
) -> str:
    if not hasattr(os, "O_NOFOLLOW"):
        raise DeployError(f"{reason}_nofollow_unavailable")
    source_fd = -1
    destination_fd = -1
    digest = hashlib.sha256()
    try:
        source_fd = os.open(source, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
        before = os.fstat(source_fd)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid not in allowed_uids
            or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) & 0o022
            or not 0 < before.st_size <= MAX_COMPOSE_INPUT_BYTES
        ):
            raise DeployError(f"{reason}_untrusted")
        destination_fd = os.open(
            destination,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
            0o600,
        )
        os.fchmod(destination_fd, 0o600)
        total = 0
        while True:
            chunk = os.read(source_fd, 64 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_COMPOSE_INPUT_BYTES:
                raise DeployError(f"{reason}_size_invalid")
            digest.update(chunk)
            written = 0
            while written < len(chunk):
                written += os.write(destination_fd, chunk[written:])
        after = os.fstat(source_fd)
        os.fsync(destination_fd)
    except OSError as exc:
        raise DeployError(f"{reason}_copy_failed") from exc
    finally:
        if source_fd >= 0:
            os.close(source_fd)
        if destination_fd >= 0:
            os.close(destination_fd)
    observed = digest.hexdigest()
    if (
        total != before.st_size
        or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        or observed != expected_sha256
    ):
        destination.unlink(missing_ok=True)
        raise DeployError(f"{reason}_changed")
    return observed


class AudiobookRuntimeDeployLane:
    def __init__(
        self,
        *,
        root: Path = ROOT,
        env: Mapping[str, str] | None = None,
        runner: Runner | None = None,
        utc_now: Callable[[], datetime] = lambda: datetime.now(UTC),
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        wait_seconds: float = 90.0,
        receipt_dir: Path | None = None,
        global_lock_path: Path = DEFAULT_GLOBAL_LOCK_PATH,
        memorial_api_lock_path: Path = DEFAULT_MEMORIAL_API_LOCK_PATH,
        sentinel_path: Path | None = None,
        sentinel_owner_uid: int | None = None,
        evidence_owner_uid: int | None = None,
        capture_memorial_controls: Callable[[], Mapping[str, Any]] | None = None,
        verify_memorial_controls: Callable[[Mapping[str, Any]], None] | None = None,
    ) -> None:
        self.root = root.resolve()
        self.release_source_uid = self.root.stat().st_uid
        self.env = dict(os.environ if env is None else env)
        self.runner = runner or SubprocessRunner()
        self.utc_now = utc_now
        self.sleep = sleep
        self.monotonic = monotonic
        self.wait_seconds = max(0.0, float(wait_seconds))
        deployment_id = str(self.env.get("EA_DEPLOYMENT_ID") or "").strip()
        if not DEPLOYMENT_ID_RE.fullmatch(deployment_id):
            raise DeployError("explicit_deployment_id_required")
        self.deployment_id = deployment_id
        self.candidate_reference = str(
            self.env.get("EA_AUDIOBOOK_RUNTIME_IMAGE") or ""
        ).strip()
        self.configuration_receipt_value = str(
            self.env.get("EA_AUDIOBOOK_RUNTIME_CANDIDATE_CONFIGURATION_RECEIPT") or ""
        ).strip()
        self.provenance_receipt_value = str(
            self.env.get("EA_AUDIOBOOK_RUNTIME_PROVENANCE_RECEIPT") or ""
        ).strip()
        self.sbom_receipt_value = str(
            self.env.get("EA_AUDIOBOOK_RUNTIME_SBOM") or ""
        ).strip()
        self.memorial_baseline_receipt_value = str(
            self.env.get("EA_AUDIOBOOK_RUNTIME_MEMORIAL_BASELINE_RECEIPT") or ""
        ).strip()
        self.production_overlay_value = str(
            self.env.get(PRODUCTION_OVERLAY_ENV) or ""
        ).strip()
        self.configuration_receipt_path = Path(
            self.configuration_receipt_value or "."
        ).expanduser()
        self.provenance_receipt_path = Path(
            self.provenance_receipt_value or "."
        ).expanduser()
        self.sbom_receipt_path = Path(self.sbom_receipt_value or ".").expanduser()
        self.memorial_baseline_receipt_path = Path(
            self.memorial_baseline_receipt_value or "."
        ).expanduser()
        if (
            self.configuration_receipt_value
            and not self.configuration_receipt_path.is_absolute()
        ):
            raise DeployError("candidate_configuration_receipt_path_not_absolute")
        if (
            self.provenance_receipt_value
            and not self.provenance_receipt_path.is_absolute()
        ):
            raise DeployError("candidate_provenance_receipt_path_not_absolute")
        if self.sbom_receipt_value and not self.sbom_receipt_path.is_absolute():
            raise DeployError("candidate_sbom_receipt_path_not_absolute")
        if (
            self.memorial_baseline_receipt_value
            and not self.memorial_baseline_receipt_path.is_absolute()
        ):
            raise DeployError("memorial_baseline_receipt_path_not_absolute")
        sentinel_value = str(
            sentinel_path
            if sentinel_path is not None
            else (self.env.get("EA_VEXP_SENTINEL_STATE_PATH") or "")
        ).strip()
        if not sentinel_value:
            raise DeployError("explicit_vexp_sentinel_state_path_required")
        self.sentinel_path = Path(sentinel_value).expanduser()
        for path in (self.sentinel_path,):
            if not path.is_absolute():
                raise DeployError("authority_path_not_absolute")
        sentinel_uid_value = str(
            self.env.get("EA_VEXP_SENTINEL_OWNER_UID") or ""
        ).strip()
        evidence_uid_value = str(
            self.env.get("EA_AUDIOBOOK_RUNTIME_EVIDENCE_OWNER_UID") or ""
        ).strip()
        if sentinel_owner_uid is None and not sentinel_uid_value:
            raise DeployError("explicit_sentinel_owner_uid_required")
        if sentinel_owner_uid is None and not sentinel_uid_value.isdigit():
            raise DeployError("sentinel_owner_uid_invalid")
        if evidence_owner_uid is None and not evidence_uid_value:
            raise DeployError("explicit_evidence_owner_uid_required")
        if evidence_owner_uid is None and not evidence_uid_value.isdigit():
            raise DeployError("evidence_owner_uid_invalid")
        self.sentinel_owner_uid = int(
            sentinel_owner_uid if sentinel_owner_uid is not None else sentinel_uid_value
        )
        self.evidence_owner_uid = int(
            evidence_owner_uid if evidence_owner_uid is not None else evidence_uid_value
        )
        if self.sentinel_owner_uid < 0:
            raise DeployError("sentinel_owner_uid_invalid")
        if self.evidence_owner_uid < 0:
            raise DeployError("evidence_owner_uid_invalid")
        self.receipt_dir = (
            receipt_dir.absolute()
            if receipt_dir is not None
            else self.root / ".runtime" / "deployments" / "audiobook-runtime"
        )
        self.receipt_path = self.receipt_dir / f"{deployment_id}.json"
        self.lock_path = self.receipt_dir / f"{deployment_id}.lock"
        self.rollback_snapshot_dir = self.receipt_dir / (
            f"{deployment_id}.active-topology"
        )
        self.global_lock_path = Path(global_lock_path)
        self.memorial_api_lock_path = Path(memorial_api_lock_path)
        if (
            not self.global_lock_path.is_absolute()
            or not self.memorial_api_lock_path.is_absolute()
        ):
            raise DeployError("global_lock_path_not_absolute")
        self._locks: list[Any] = []
        self.compose_bin: tuple[str, ...] = ()
        self.release_env = dict(self.env)
        self.release_env.update(
            {
                "COMPOSE_PROJECT_NAME": PROJECT_NAME,
                "EA_AUDIOBOOK_RUNTIME_IMAGE": self.candidate_reference,
                "EA_SOURCE_REVISION": "",
                "EA_DEPLOYMENT_ID": deployment_id,
            }
        )
        self.pre_state: dict[str, Any] = {}
        self.candidate: dict[str, str] = {}
        self.source_revision = ""
        self.configuration_document: TrustedDocument | None = None
        self.configuration_projection: dict[str, Any] = {}
        self.provenance_document: TrustedDocument | None = None
        self.sbom_document: TrustedDocument | None = None
        self.memorial_baseline_document: TrustedDocument | None = None
        self.compose_source_inventory: list[dict[str, str]] = []
        self.compose_source_inventory_sha256 = ""
        self.git_repository_binding: GitRepositoryBinding | None = None
        self.schema_v6_qualification: QualificationEvidence | None = None
        self.stage_owner_permit_document: TrustedDocument | None = None
        self.stage_owner_permit_consumed = False
        self.consumed_stage_owner_permit_path: Path | None = None
        self.prior_preflight_receipt: TrustedDocument | None = None
        self.target_compose_sha256 = ""
        self.target_compose_files: tuple[str, ...] = ()
        self.target_compose_config_sha256: dict[str, str] = {}
        self.target_requested_network_endpoints: dict[
            str, dict[str, dict[str, Any]]
        ] = {}
        self.forward_input_plan_sha256 = ""
        self.forward_env_sha256 = ""
        self.forward_compose_files: tuple[str, ...] = ()
        self.forward_env_path: Path | None = None
        self.forward_topology_manifest_path: Path | None = None
        self.forward_topology_manifest_sha256 = ""
        self.staged_worker_identities: dict[str, str] = {}
        self.production_overlay_sha256 = ""
        self.production_overlay_snapshot_path: Path | None = None
        self.rollback_plan_sha256 = ""
        self.rollback_plans: dict[str, dict[str, Any]] = {}
        self.rollback_snapshot_paths: list[Path] = []
        self.protected_prior_images: dict[str, str] = {}
        self.retain_recovery_assets = False
        self.retain_active_topology_inputs = False
        self.active_topology_manifests: dict[str, str] = {}
        self.memorial_controls: dict[str, Any] = {}
        self._capture_controls = (
            capture_memorial_controls or self._capture_local_controls
        )
        self._verify_controls = verify_memorial_controls or self._verify_local_controls
        self.receipt: dict[str, Any] = {
            "contract_name": DEPLOY_RECEIPT_CONTRACT,
            "deployment_id": deployment_id,
            "project_name": PROJECT_NAME,
            "service_scope": list(EXPECTED_RUNTIME_SERVICES),
            "preserved_services": list(PRESERVED_RUNTIME_SERVICES),
            "paused_stage_services": list(WORKER_SERVICES),
            "runtime_activation_authority": False,
            "live_mutation_default": False,
            "build_allowed": False,
            "pull_allowed": False,
            "runtime_side_effect_posture": {
                "status": "not_validated",
                "queue_processing": "unverified",
                "provider_work": "unverified",
                "outbound_send": "unverified",
            },
            "started_at": _utc_text(self.utc_now()),
            "status": "preflight",
            "checks": [],
            "rollback": {"status": "not_required"},
        }

    @property
    def root_authority_uid(self) -> int:
        """Fixed production owner for issuer-controlled authority files."""

        return 0

    @property
    def schema_v6_permit_path(self) -> Path:
        return DEFAULT_SCHEMA_V6_PERMIT_PATH

    @property
    def stage_owner_permit_path(self) -> Path:
        return DEFAULT_STAGE_OWNER_PERMIT_PATH

    @property
    def authority_lock_paths(self) -> tuple[Path, Path]:
        return (
            DEFAULT_SCHEMA_V6_PERMIT_LOCK_PATH,
            DEFAULT_STAGE_OWNER_PERMIT_LOCK_PATH,
        )

    @property
    def active_stage_owner_permit_path(self) -> Path:
        return self.consumed_stage_owner_permit_path or self.stage_owner_permit_path

    def _write_receipt(self) -> None:
        _ensure_private_directory(self.receipt_dir)
        temporary = self.receipt_path.with_name(
            f".{self.receipt_path.name}.{os.getpid()}.tmp"
        )
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = -1
        try:
            descriptor = os.open(temporary, flags, 0o600)
            os.fchmod(descriptor, 0o600)
            raw = (json.dumps(self.receipt, indent=2, sort_keys=True) + "\n").encode()
            written = 0
            while written < len(raw):
                written += os.write(descriptor, raw[written:])
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = -1
            os.replace(temporary, self.receipt_path)
            directory_flags = os.O_RDONLY | os.O_CLOEXEC
            if hasattr(os, "O_DIRECTORY"):
                directory_flags |= os.O_DIRECTORY
            directory_fd = os.open(self.receipt_dir, directory_flags)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            temporary.unlink(missing_ok=True)

    def _record(self, name: str, status: str, **detail: object) -> None:
        self.receipt["checks"] = [
            *list(self.receipt.get("checks") or []),
            {"name": name, "status": status, **detail},
        ]
        self._write_receipt()

    def _open_lock(self, path: Path, reason: str) -> Any:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        flags = os.O_RDWR | os.O_CREAT | os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(path, flags, 0o600)
        except OSError as exc:
            raise DeployError(f"deployment_lock_unavailable:{path.name}") from exc
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_nlink != 1
        ):
            os.close(descriptor)
            raise DeployError("deployment_lock_untrusted")
        handle = os.fdopen(descriptor, "a+", encoding="utf-8")
        os.fchmod(handle.fileno(), 0o600)
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            handle.close()
            raise DeployError(reason) from exc
        return handle

    def _acquire_locks(self, *, allow_prepared_receipt: bool = False) -> None:
        _ensure_private_directory(self.receipt_dir)
        try:
            self._locks.append(
                self._open_lock(
                    self.memorial_api_lock_path,
                    "memorial_api_deployment_already_running",
                )
            )
            self._locks.append(
                self._open_lock(
                    self.global_lock_path,
                    "audiobook_runtime_deployment_already_running",
                )
            )
            self._locks.append(
                self._open_lock(self.lock_path, "deployment_already_running")
            )
            if os.path.lexists(self.receipt_path):
                if not allow_prepared_receipt:
                    raise DeployError("deployment_receipt_already_exists")
                prior = _read_trusted_json(
                    self.receipt_path,
                    expected_uid=os.geteuid(),
                    maximum_bytes=MAX_EVIDENCE_BYTES,
                    reason_prefix="prior_consumer_preflight_receipt",
                )
                payload = prior.payload
                if (
                    payload.get("contract_name") != DEPLOY_RECEIPT_CONTRACT
                    or payload.get("deployment_id") != self.deployment_id
                    or payload.get("status") != "preflight_only_owner_permit_required"
                    or not isinstance(payload.get("permit_request"), dict)
                    or dict(payload.get("cleanup") or {}).get("status") != "pass"
                ):
                    raise DeployError("prior_consumer_preflight_receipt_invalid")
                self.prior_preflight_receipt = prior
        except Exception:
            self._release_locks()
            raise

    def _release_locks(self) -> None:
        for handle in reversed(self._locks):
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()
        self._locks.clear()

    def _guard_now(self) -> datetime:
        try:
            now = self.utc_now()
        except Exception as exc:
            raise DeployError("vexp_guard_clock_invalid") from exc
        if (
            not isinstance(now, datetime)
            or now.tzinfo is None
            or now.utcoffset() != UTC.utcoffset(now)
        ):
            raise DeployError("vexp_guard_clock_invalid")
        return now.astimezone(UTC)

    def _monotonic_now(self) -> float:
        try:
            value = self.monotonic()
        except Exception as exc:
            raise DeployError("vexp_mutation_action_clock_invalid") from exc
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise DeployError("vexp_mutation_action_clock_invalid")
        return float(value)

    def _require_mutation_deadline(self, started: float) -> None:
        elapsed = self._monotonic_now() - started
        if (
            not math.isfinite(elapsed)
            or elapsed < 0
            or elapsed > MAX_VEXP_MUTATION_ACTION_SECONDS
        ):
            raise DeployError("vexp_mutation_action_deadline_exceeded")

    @contextmanager
    def _issuer_file_locks(self) -> Iterator[None]:
        descriptors: list[int] = []
        try:
            for path in sorted(self.authority_lock_paths, key=str):
                if not path.is_absolute():
                    raise DeployError("authority_lock_path_invalid")
                descriptor = _open_absolute_nofollow(
                    path,
                    flags=os.O_RDONLY,
                    reason="authority_lock",
                    require_root_parents=self.root_authority_uid == 0,
                )
                descriptors.append(descriptor)
                before = os.fstat(descriptor)
                if (
                    not stat.S_ISREG(before.st_mode)
                    or before.st_uid != self.root_authority_uid
                    or before.st_nlink != 1
                    or stat.S_IMODE(before.st_mode) != 0o644
                ):
                    raise DeployError("authority_lock_untrusted")
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
                except BlockingIOError as exc:
                    raise DeployError("authority_lock_busy") from exc
                current_descriptor = _open_absolute_nofollow(
                    path,
                    flags=os.O_RDONLY,
                    reason="authority_lock",
                    require_root_parents=self.root_authority_uid == 0,
                )
                try:
                    current = os.fstat(current_descriptor)
                finally:
                    os.close(current_descriptor)
                identity_fields = (
                    "st_dev",
                    "st_ino",
                    "st_mode",
                    "st_uid",
                    "st_gid",
                    "st_nlink",
                    "st_size",
                    "st_mtime_ns",
                    "st_ctime_ns",
                )
                if any(
                    getattr(before, field) != getattr(current, field)
                    for field in identity_fields
                ):
                    raise DeployError("authority_lock_changed")
            yield
        except DeployError:
            raise
        except OSError as exc:
            raise DeployError("authority_lock_unavailable") from exc
        finally:
            for descriptor in reversed(descriptors):
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
                except OSError:
                    pass
                os.close(descriptor)

    @contextmanager
    def _issuer_authority_lease(self, boundary: str) -> Iterator[None]:
        with self._issuer_file_locks():
            started = self._monotonic_now()
            self._revalidate_authority(f"immediately_before:{boundary}")
            yield
            self._require_mutation_deadline(started)
            self._revalidate_authority(f"immediately_after:{boundary}")

    def _run(
        self,
        args: Sequence[str],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        return self.runner.run(
            list(args),
            cwd=cwd or self.root,
            env=self.release_env if env is None else env,
            check=check,
        )

    def _run_bytes(
        self,
        args: Sequence[str],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[bytes]:
        return self.runner.run_bytes(
            list(args),
            cwd=cwd or self.root,
            env=self.release_env if env is None else env,
            check=check,
        )

    def _trusted_git_executable(self) -> Path:
        candidate = shutil.which("git", path=GIT_SAFE_PATH)
        if not candidate:
            raise DeployError("release_source_git_unavailable")
        candidate_path = Path(candidate)
        if not candidate_path.is_absolute():
            raise DeployError("release_source_git_untrusted")
        descriptor = -1
        try:
            descriptor = _open_absolute_nofollow(
                candidate_path,
                flags=os.O_RDONLY,
                reason="release_source_git",
                require_root_parents=True,
            )
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != ROOT_AUTHORITY_UID
                or stat.S_IMODE(metadata.st_mode) & 0o022
            ):
                raise DeployError("release_source_git_untrusted")
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        return candidate_path

    @staticmethod
    def _git_environment() -> dict[str, str]:
        """Return a fixed environment containing no inherited Git controls."""

        return {
            "PATH": GIT_SAFE_PATH,
            "HOME": "/nonexistent",
            "XDG_CONFIG_HOME": "/nonexistent",
            "LANG": "C",
            "LC_ALL": "C",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_SYSTEM": "/dev/null",
            "GIT_CONFIG_COUNT": "0",
            "GIT_ATTR_NOSYSTEM": "1",
            "GIT_NO_LAZY_FETCH": "1",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_ALLOW_PROTOCOL": "",
            "GIT_PROTOCOL_FROM_USER": "0",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_ASKPASS": "/bin/false",
            "SSH_ASKPASS": "/bin/false",
            "GIT_SSH_COMMAND": "/bin/false",
            "GIT_PAGER": "cat",
            "GIT_EDITOR": "false",
        }

    def _git_command(
        self,
        *args: str,
        binding: GitRepositoryBinding | None = None,
    ) -> list[str]:
        command = [str(self._trusted_git_executable())]
        for key, value in GIT_FIXED_CONFIG:
            command.extend(("-c", f"{key}={value}"))
        if binding is None:
            command.extend(("-C", str(self.root)))
        else:
            command.extend(
                (
                    f"--git-dir={binding.git_dir}",
                    f"--work-tree={binding.work_tree}",
                )
            )
        command.extend(args)
        return command

    def _git_text(
        self,
        *args: str,
        binding: GitRepositoryBinding | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        return self._run(
            self._git_command(*args, binding=binding),
            env=self._git_environment(),
            check=check,
        )

    def _git_bytes(
        self,
        *args: str,
        binding: GitRepositoryBinding,
    ) -> bytes:
        return self._run_bytes(
            self._git_command(*args, binding=binding),
            env=self._git_environment(),
        ).stdout

    @staticmethod
    def _decode_git_path(value: str, reason: str) -> Path:
        text = value.strip()
        if not text or "\x00" in text or "\n" in text or "\r" in text:
            raise DeployError(reason)
        candidate = Path(text)
        if not candidate.is_absolute():
            raise DeployError(reason)
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as exc:
            raise DeployError(reason) from exc
        if resolved != candidate:
            raise DeployError(reason)
        return candidate

    def _repository_directory_identity(
        self, path: Path
    ) -> tuple[int, int, int, int, int]:
        descriptor = -1
        try:
            descriptor = _open_absolute_nofollow(
                path,
                flags=os.O_RDONLY | os.O_DIRECTORY,
                reason="release_source_repository",
                require_root_parents=False,
            )
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISDIR(metadata.st_mode)
                or metadata.st_uid != self.release_source_uid
                or stat.S_IMODE(metadata.st_mode) & 0o002
            ):
                raise DeployError("release_source_repository_untrusted")
            return (
                metadata.st_dev,
                metadata.st_ino,
                metadata.st_mode,
                metadata.st_uid,
                metadata.st_gid,
            )
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    def _git_binding_value(
        self,
        *args: str,
        binding: GitRepositoryBinding | None = None,
        reason: str,
    ) -> str:
        result = self._git_text(*args, binding=binding)
        value = result.stdout.strip()
        if not value or "\x00" in value or "\n" in value or "\r" in value:
            raise DeployError(reason)
        return value

    def _assert_repository_binding(self, binding: GitRepositoryBinding) -> None:
        work_tree = self._decode_git_path(
            self._git_text(
                "rev-parse",
                "--path-format=absolute",
                "--show-toplevel",
                binding=binding,
            ).stdout,
            "release_source_worktree_unavailable",
        )
        git_dir = self._decode_git_path(
            self._git_text(
                "rev-parse",
                "--path-format=absolute",
                "--git-dir",
                binding=binding,
            ).stdout,
            "release_source_git_dir_unavailable",
        )
        common_dir = self._decode_git_path(
            self._git_text(
                "rev-parse",
                "--path-format=absolute",
                "--git-common-dir",
                binding=binding,
            ).stdout,
            "release_source_common_dir_unavailable",
        )
        head = self._git_binding_value(
            "rev-parse",
            "--verify",
            "HEAD^{commit}",
            binding=binding,
            reason="release_source_revision_unavailable",
        )
        if (
            work_tree != binding.work_tree
            or git_dir != binding.git_dir
            or common_dir != binding.common_dir
            or head != binding.head_commit
            or self._repository_directory_identity(work_tree)
            != binding.work_tree_identity
            or self._repository_directory_identity(git_dir) != binding.git_dir_identity
            or self._repository_directory_identity(common_dir)
            != binding.common_dir_identity
        ):
            raise DeployError("release_source_repository_binding_changed")

    def _require_no_repository_overrides(self, binding: GitRepositoryBinding) -> None:
        replacement_refs = self._git_text(
            "for-each-ref",
            "--format=%(refname)",
            "refs/replace",
            binding=binding,
        )
        if replacement_refs.stdout.strip():
            raise DeployError("release_source_replace_refs_present")
        checked: set[Path] = set()
        for repository_dir in (binding.git_dir, binding.common_dir):
            for relative in (
                Path("objects/info/alternates"),
                Path("objects/info/http-alternates"),
            ):
                candidate = repository_dir / relative
                if candidate in checked:
                    continue
                checked.add(candidate)
                try:
                    os.lstat(candidate)
                except FileNotFoundError:
                    continue
                except OSError as exc:
                    raise DeployError("release_source_alternates_check_failed") from exc
                raise DeployError("release_source_alternates_present")

    def _discover_repository_binding(self) -> GitRepositoryBinding:
        work_tree = self._decode_git_path(
            self._git_text(
                "rev-parse", "--path-format=absolute", "--show-toplevel"
            ).stdout,
            "release_source_worktree_unavailable",
        )
        git_dir = self._decode_git_path(
            self._git_text("rev-parse", "--path-format=absolute", "--git-dir").stdout,
            "release_source_git_dir_unavailable",
        )
        common_dir = self._decode_git_path(
            self._git_text(
                "rev-parse", "--path-format=absolute", "--git-common-dir"
            ).stdout,
            "release_source_common_dir_unavailable",
        )
        head = self._git_binding_value(
            "rev-parse",
            "--verify",
            "HEAD^{commit}",
            reason="release_source_revision_unavailable",
        )
        if work_tree != self.root or not SOURCE_REVISION_RE.fullmatch(head):
            raise DeployError("release_source_repository_binding_invalid")
        if common_dir != git_dir and common_dir not in git_dir.parents:
            raise DeployError("release_source_repository_binding_invalid")
        binding = GitRepositoryBinding(
            work_tree=work_tree,
            git_dir=git_dir,
            common_dir=common_dir,
            head_commit=head,
            work_tree_identity=self._repository_directory_identity(work_tree),
            git_dir_identity=self._repository_directory_identity(git_dir),
            common_dir_identity=self._repository_directory_identity(common_dir),
        )
        self._assert_repository_binding(binding)
        self._require_no_repository_overrides(binding)
        return binding

    def _require_clean_source_revision(
        self, expected_revision: str, binding: GitRepositoryBinding
    ) -> None:
        self._assert_repository_binding(binding)
        self._require_no_repository_overrides(binding)
        if binding.head_commit != expected_revision:
            raise DeployError("release_source_revision_changed")
        for args in (
            (
                "diff",
                "--quiet",
                "--no-ext-diff",
                "--no-textconv",
                expected_revision,
                "--",
            ),
            (
                "diff",
                "--cached",
                "--quiet",
                "--no-ext-diff",
                "--no-textconv",
                expected_revision,
                "--",
            ),
        ):
            result = self._git_text(*args, binding=binding, check=False)
            if result.returncode != 0:
                raise DeployError("release_source_worktree_dirty")
        untracked = self._git_text(
            "ls-files",
            "--others",
            "--exclude-standard",
            binding=binding,
        )
        if untracked.stdout.strip():
            raise DeployError("release_source_worktree_dirty")

    def _detect_compose(self) -> None:
        current = self._run(["docker", "compose", "version"], check=False)
        if current.returncode == 0:
            self.compose_bin = ("docker", "compose")
            return
        raise DeployError("docker_compose_v2_required")

    def _source_metadata(self) -> dict[str, str]:
        binding = self._discover_repository_binding()
        branch = self._git_text(
            "symbolic-ref",
            "--quiet",
            "--short",
            "HEAD",
            binding=binding,
            check=False,
        )
        upstream = self._git_text(
            "rev-parse",
            "--abbrev-ref",
            "--symbolic-full-name",
            "@{u}",
            binding=binding,
            check=False,
        )
        upstream_head = self._git_text(
            "rev-parse",
            "--verify",
            "@{u}^{commit}",
            binding=binding,
            check=False,
        )
        source_revision = binding.head_commit
        if (
            branch.returncode != 0
            or not branch.stdout.strip()
            or upstream.returncode != 0
            or not upstream.stdout.strip()
            or upstream_head.returncode != 0
        ):
            raise DeployError("release_source_not_attached_and_tracked")
        if not SOURCE_REVISION_RE.fullmatch(source_revision):
            raise DeployError("release_source_revision_invalid")
        if upstream_head.stdout.strip() != source_revision:
            raise DeployError("release_source_not_at_tracked_revision")
        self._require_clean_source_revision(source_revision, binding)
        final_binding = self._discover_repository_binding()
        if final_binding != binding:
            raise DeployError("release_source_repository_binding_changed")
        self.git_repository_binding = binding
        return {
            "branch": branch.stdout.strip(),
            "upstream": upstream.stdout.strip(),
            "source_revision": source_revision,
        }

    def _capture_compose_source_inventory(self) -> None:
        binding = self.git_repository_binding
        if binding is None:
            raise DeployError("release_source_repository_binding_missing")
        self._require_clean_source_revision(self.source_revision, binding)
        inventory: list[dict[str, str]] = []
        for relative in PRODUCTION_COMPOSE_SOURCE_PATHS:
            working = self.root / relative
            working_sha256_before = _trusted_input_sha256(
                working,
                allowed_uids={0, os.geteuid(), self.release_source_uid},
                reason="compose_source_input",
            )
            object_name = f"{self.source_revision}:{relative.as_posix()}"
            blob = self._git_bytes("cat-file", "blob", object_name, binding=binding)
            if not 0 < len(blob) <= MAX_COMPOSE_INPUT_BYTES:
                raise DeployError("compose_source_blob_size_invalid")
            blob_sha256 = hashlib.sha256(blob).hexdigest()
            working_sha256_after = _trusted_input_sha256(
                working,
                allowed_uids={0, os.geteuid(), self.release_source_uid},
                reason="compose_source_input",
            )
            if (
                working_sha256_before != working_sha256_after
                or working_sha256_after != blob_sha256
            ):
                raise DeployError("compose_source_blob_mismatch")
            inventory.append(
                {
                    "path": relative.as_posix(),
                    "blob_sha256": blob_sha256,
                    "working_sha256": working_sha256_after,
                }
            )
        final_binding = self._discover_repository_binding()
        if final_binding != binding:
            raise DeployError("release_source_repository_binding_changed")
        self._require_clean_source_revision(self.source_revision, final_binding)
        for relative, expected in zip(
            PRODUCTION_COMPOSE_SOURCE_PATHS, inventory, strict=True
        ):
            object_name = f"{self.source_revision}:{relative.as_posix()}"
            final_blob = self._git_bytes(
                "cat-file", "blob", object_name, binding=final_binding
            )
            final_working_sha256 = _trusted_input_sha256(
                self.root / relative,
                allowed_uids={0, os.geteuid(), self.release_source_uid},
                reason="compose_source_input",
            )
            if (
                hashlib.sha256(final_blob).hexdigest() != expected["blob_sha256"]
                or final_working_sha256 != expected["working_sha256"]
            ):
                raise DeployError("compose_source_changed_during_snapshot")
        self.compose_source_inventory = inventory
        self.compose_source_inventory_sha256 = _canonical_sha256(inventory)

    def _inspect_image(self, reference: str) -> dict[str, str]:
        if not DIGEST_IMAGE_RE.fullmatch(reference):
            raise DeployError("candidate_image_digest_reference_required")
        result = self._run(["docker", "image", "inspect", reference])
        try:
            rows = json.loads(result.stdout)
        except Exception as exc:
            raise DeployError("candidate_image_inspection_invalid") from exc
        if (
            not isinstance(rows, list)
            or len(rows) != 1
            or not isinstance(rows[0], dict)
        ):
            raise DeployError("candidate_image_inspection_invalid")
        row = rows[0]
        image_id = str(row.get("Id") or "")
        repo_digests = {str(item) for item in list(row.get("RepoDigests") or [])}
        labels = dict(dict(row.get("Config") or {}).get("Labels") or {})
        if not IMAGE_ID_RE.fullmatch(image_id) or reference not in repo_digests:
            raise DeployError("candidate_image_identity_mismatch")
        if labels.get("org.opencontainers.image.revision") != self.source_revision:
            raise DeployError("candidate_image_source_revision_mismatch")
        return {"reference": reference, "image_id": image_id}

    def _load_schema_v6_qualification(self) -> QualificationEvidence:
        try:
            return load_schema_v6_qualification(
                state_path=self.sentinel_path,
                state_owner_uid=self.sentinel_owner_uid,
                permit_path=self.schema_v6_permit_path,
                now=self._guard_now(),
            )
        except SchemaV6AuthorityError as exc:
            raise DeployError("schema_v6_qualification_invalid") from exc

    def _validate_provenance_and_sbom(self) -> None:
        if self.provenance_document is None or self.sbom_document is None:
            raise DeployError("candidate_supply_chain_evidence_missing")
        provenance = self.provenance_document.payload
        expected_provenance = {
            "contract_name": PRODUCTION_PROVENANCE_CONTRACT,
            "version": 1,
            "status": "pass",
            "source_revision": self.source_revision,
            "image_reference": self.candidate_reference,
            "image_id": self.candidate["image_id"],
            "sbom_sha256": self.sbom_document.sha256,
        }
        if set(provenance) != PROVENANCE_RECEIPT_KEYS or any(
            provenance.get(key) != value for key, value in expected_provenance.items()
        ):
            raise DeployError("candidate_provenance_contract_invalid")
        sbom = self.sbom_document.payload
        if set(sbom) != SBOM_RECEIPT_KEYS:
            raise DeployError("candidate_sbom_contract_invalid")
        namespace = sbom.get("document_namespace")
        serial_number = sbom.get("serial_number")
        expected_sbom = {
            "contract_name": PRODUCTION_SBOM_CONTRACT,
            "version": 1,
            "status": "pass",
            "subject_name": "ea-runtime",
            "subject_image_reference": self.candidate_reference,
            "subject_image_id": self.candidate["image_id"],
            "subject_source_revision": self.source_revision,
        }
        if (
            any(sbom.get(key) != value for key, value in expected_sbom.items())
            or not isinstance(namespace, str)
            or not URN_RE.fullmatch(namespace)
            or not isinstance(serial_number, str)
            or not URN_RE.fullmatch(serial_number)
        ):
            raise DeployError("candidate_sbom_contract_invalid")
        bom = sbom.get("bom")
        if not isinstance(bom, dict):
            raise DeployError("candidate_sbom_contract_invalid")
        metadata = bom.get("metadata")
        component = metadata.get("component") if isinstance(metadata, dict) else None
        components = bom.get("components")
        if (
            bom.get("bomFormat") != "CycloneDX"
            or not isinstance(bom.get("specVersion"), str)
            or type(bom.get("version")) is not int
            or bom["version"] < 1
            or bom.get("serialNumber") != serial_number
            or not isinstance(components, list)
            or not components
            or not isinstance(component, dict)
            or component.get("name") != "ea-runtime"
        ):
            raise DeployError("candidate_sbom_contract_invalid")
        properties = component.get("properties")
        if not isinstance(properties, list):
            raise DeployError("candidate_sbom_contract_invalid")
        linked: dict[str, str] = {}
        for raw in properties:
            if not isinstance(raw, dict):
                raise DeployError("candidate_sbom_contract_invalid")
            name = raw.get("name")
            value = raw.get("value")
            if (
                not isinstance(name, str)
                or not isinstance(value, str)
                or name in linked
            ):
                raise DeployError("candidate_sbom_contract_invalid")
            linked[name] = value
        required = {
            "ea:document-namespace": namespace,
            "ea:image-reference": self.candidate_reference,
            "ea:image-id": self.candidate["image_id"],
            "ea:source-revision": self.source_revision,
        }
        if any(linked.get(key) != value for key, value in required.items()):
            raise DeployError("candidate_sbom_contract_invalid")

    @staticmethod
    def _validate_source_inventory_shape(
        value: object, expected_paths: Sequence[Path]
    ) -> tuple[list[dict[str, str]], str]:
        if not isinstance(value, list) or len(value) != len(expected_paths):
            raise DeployError("compose_source_inventory_invalid")
        inventory: list[dict[str, str]] = []
        for expected_path, raw in zip(expected_paths, value, strict=True):
            if not isinstance(raw, dict) or set(raw) != {
                "path",
                "blob_sha256",
                "working_sha256",
            }:
                raise DeployError("compose_source_inventory_invalid")
            entry = {str(key): str(item) for key, item in raw.items()}
            if (
                entry["path"] != expected_path.as_posix()
                or not SHA256_RE.fullmatch(entry["blob_sha256"])
                or entry["working_sha256"] != entry["blob_sha256"]
            ):
                raise DeployError("compose_source_inventory_invalid")
            inventory.append(entry)
        return inventory, _canonical_sha256(inventory)

    def _memorial_baseline_summary(self) -> dict[str, str]:
        if self.memorial_baseline_document is None:
            raise DeployError("memorial_baseline_receipt_missing")
        receipt = self.memorial_baseline_document.payload
        if set(receipt) != MEMORIAL_BASELINE_RECEIPT_KEYS:
            raise DeployError("memorial_baseline_receipt_invalid")
        if (
            receipt.get("contract_name") != MEMORIAL_BASELINE_CONTRACT
            or receipt.get("version") != 1
            or receipt.get("status") != "pass"
            or receipt.get("issuer") != "ea-memorial-runtime-owner"
            or not SOURCE_REVISION_RE.fullmatch(
                str(receipt.get("source_revision") or "")
            )
        ):
            raise DeployError("memorial_baseline_receipt_invalid")
        inventory, inventory_sha = self._validate_source_inventory_shape(
            receipt.get("compose_source_inventory"),
            PRODUCTION_COMPOSE_SOURCE_PATHS[:-1],
        )
        del inventory
        if (
            receipt.get("compose_source_inventory_sha256") != inventory_sha
            or not SHA256_RE.fullmatch(
                str(receipt.get("rendered_compose_sha256") or "")
            )
            or not SHA256_RE.fullmatch(str(receipt.get("ea_api_sha256") or ""))
        ):
            raise DeployError("memorial_baseline_receipt_invalid")
        issued = _parse_time(
            receipt.get("issued_at"), "memorial_baseline_issued_at_invalid"
        )
        expires = _parse_time(
            receipt.get("expires_at"), "memorial_baseline_expires_at_invalid"
        )
        now = self._guard_now()
        if (
            expires <= issued
            or expires - issued > timedelta(hours=1)
            or not issued <= now < expires
        ):
            raise DeployError("memorial_baseline_not_current")
        return {
            "contract_name": MEMORIAL_BASELINE_CONTRACT,
            "receipt_sha256": self.memorial_baseline_document.sha256,
            "source_revision": str(receipt["source_revision"]),
            "compose_inventory_sha256": str(receipt["compose_source_inventory_sha256"]),
            "rendered_compose_sha256": str(receipt["rendered_compose_sha256"]),
            "ea_api_sha256": str(receipt["ea_api_sha256"]),
        }

    @staticmethod
    def _require_false_authorities(
        payload: Mapping[str, Any], fields: Sequence[str], reason: str
    ) -> None:
        if any(payload.get(field) is not False for field in fields):
            raise DeployError(reason)

    def _validate_stage_owner_permit(
        self,
        document: TrustedDocument,
        projection: Mapping[str, Any],
        qualification: QualificationEvidence,
    ) -> None:
        permit = document.payload
        if self.prior_preflight_receipt is None:
            raise DeployError("prior_consumer_preflight_receipt_required")
        if set(permit) != STAGE_OWNER_PERMIT_KEYS:
            raise DeployError("stage_owner_permit_fields_invalid")
        now = self._guard_now()
        issued = _parse_time(
            permit.get("issued_at"), "stage_owner_permit_issued_at_invalid"
        )
        expires = _parse_time(
            permit.get("expires_at"), "stage_owner_permit_expires_at_invalid"
        )
        qualified = _parse_time(
            qualification.qualified_at,
            "stage_owner_permit_qualification_time_invalid",
        )
        schema_expires = _parse_time(
            qualification.permit_expires_at,
            "stage_owner_permit_schema_expiry_invalid",
        )
        if (
            issued < qualified
            or issued
            < _parse_time(
                self.configuration_document.payload["verified_at"],
                "production_preflight_time_invalid",
            )
            or issued > now + MAX_CLOCK_SKEW
            or not issued <= now < expires
            or expires <= issued
            or expires - issued > timedelta(hours=1)
            or expires > schema_expires
        ):
            raise DeployError("stage_owner_permit_not_current")
        qualification_projection = projection["schema_v6_qualification"]
        memorial = projection["memorial_baseline"]
        provenance = projection["provenance"]
        sbom = projection["sbom"]
        expected = {
            "contract_name": STAGE_OWNER_PERMIT_CONTRACT,
            "version": 1,
            "status": "allow",
            "issuer": "ea-memorial-runtime-owner",
            "deployment_id": self.deployment_id,
            "single_use": True,
            "scope": "paused_stage_only",
            "live_api_owner": "memorial",
            "owner_decision": ("preserve_memorial_api_and_allow_paused_stage"),
            "stage_projection_sha256": projection["stage_projection_sha256"],
            "production_preflight_sha256": self.configuration_document.sha256,
            "consumer_preflight_receipt_sha256": (self.prior_preflight_receipt.sha256),
            "source_revision": self.source_revision,
            "candidate_image_reference": self.candidate_reference,
            "candidate_image_id": self.candidate["image_id"],
            "compose_source_inventory_sha256": projection[
                "compose_source_inventory_sha256"
            ],
            "overlay_blob_sha256": projection["overlay_blob_sha256"],
            "rendered_compose_sha256": projection["rendered_compose_sha256"],
            "memorial_baseline_receipt_sha256": memorial["receipt_sha256"],
            "memorial_ea_api_sha256": memorial["ea_api_sha256"],
            "stage_mutation_services": list(WORKER_SERVICES),
            "preserved_services": list(PRESERVED_RUNTIME_SERVICES),
            "pre_state_sha256": self.pre_state["sha256"],
            "target_compose_sha256": self.target_compose_sha256,
            "target_compose_config_sha256": dict(self.target_compose_config_sha256),
            "rollback_plan_sha256": self.rollback_plan_sha256,
            "forward_input_plan_sha256": self.forward_input_plan_sha256,
            "schema_v6_terminal_identity_sha256": qualification_projection[
                "terminal_identity_sha256"
            ],
            "schema_v6_permit_sha256": qualification.permit_sha256,
            "provenance_sha256": provenance["sha256"],
            "sbom_sha256": sbom["sha256"],
            "allowed_actions": list(PAUSED_STAGE_MUTATION_ACTIONS),
            "stage_mutation_authority": True,
            "deployment_authority": False,
            "group_deploy_eligible": False,
            "live_api_mutation_authority": False,
            "runtime_activation_authority": False,
            "queue_mutation_authority": False,
            "provider_work_authority": False,
            "outbound_send_authority": False,
            "build_authority": False,
            "pull_authority": False,
        }
        if any(permit.get(field) != value for field, value in expected.items()):
            raise DeployError("stage_owner_permit_binding_mismatch")
        if not DEPLOYMENT_ID_RE.fullmatch(
            str(permit.get("permit_id") or "")
        ) or not SHA256_RE.fullmatch(str(permit.get("nonce") or "")):
            raise DeployError("stage_owner_permit_identity_invalid")

    def _validate_production_projection(
        self,
        configuration: Mapping[str, Any],
        qualification: QualificationEvidence,
    ) -> dict[str, Any]:
        if set(configuration) != PRODUCTION_ROOT_KEYS:
            raise DeployError("production_preflight_fields_invalid")
        denied = (
            "deployment_authority",
            "group_deploy_eligible",
            "runtime_activation_authority",
            "queue_mutation_authority",
            "provider_work_authority",
            "outbound_send_authority",
            "build_authority",
            "pull_authority",
        )
        if (
            _contract_name(configuration) != PRODUCTION_PREFLIGHT_CONTRACT
            or configuration.get("version") != 1
            or configuration.get("status") != "prepared"
            or configuration.get("verification_mode") != "prepare"
            or configuration.get("mutations_performed") != 0
            or configuration.get("preparation_valid") is not True
            or configuration.get("non_transferable") is not True
            or configuration.get("deployment_scope") != "paused_stage_only"
            or configuration.get("deploy_ready") is not False
            or configuration.get("stage_deploy_eligible") is not False
            or configuration.get("stage_mutation_authority") is not False
            or configuration.get("issues") != []
            or configuration.get("next_action")
            != (
                "governed_consumer_must_issue_and_atomically_consume_a_"
                "distinct_root_one_shot_permit"
            )
        ):
            raise DeployError("production_preflight_not_prepared")
        self._require_false_authorities(
            configuration, denied, "production_preflight_authority_ambiguous"
        )
        verified_at = _parse_time(
            configuration.get("verified_at"), "production_preflight_time_invalid"
        )
        if verified_at > self._guard_now() + MAX_CLOCK_SKEW:
            raise DeployError("production_preflight_time_invalid")

        raw_projection = configuration.get("production_projection")
        if not isinstance(raw_projection, dict):
            raise DeployError("production_projection_invalid")
        projection = dict(raw_projection)
        if set(projection) != PRODUCTION_PROJECTION_KEYS:
            raise DeployError("production_projection_fields_invalid")
        if (
            _contract_name(projection) != PRODUCTION_PROJECTION_CONTRACT
            or projection.get("version") != 1
            or projection.get("status") != "prepared"
            or projection.get("configuration_only") is not True
            or projection.get("configuration_valid") is not True
            or projection.get("preparation_valid") is not True
            or projection.get("non_transferable") is not True
            or projection.get("deploy_ready") is not False
            or projection.get("deployment_scope") != "paused_stage_only"
            or projection.get("stage_deploy_eligible") is not False
            or projection.get("stage_mutation_authority") is not False
            or list(projection.get("target_services") or []) != list(TARGET_SERVICES)
            or list(projection.get("stage_mutation_services") or [])
            != list(WORKER_SERVICES)
            or list(projection.get("preserved_services") or []) != [API_SERVICE]
            or projection.get("source_revision") != self.source_revision
            or projection.get("candidate_image_reference") != self.candidate_reference
            or projection.get("candidate_image_id") != self.candidate["image_id"]
            or projection.get("live_api_owner") != "memorial"
            or projection.get("live_api_mutation_authority") is not False
            or projection.get("owner_handoff_required") is not True
            or projection.get("owner_handoff_performed") is not False
            or projection.get("owner_preservation_permit_required") is not True
            or projection.get("required_owner_permit_contract")
            != STAGE_OWNER_PERMIT_CONTRACT
            or projection.get("silent_takeover_allowed") is not False
            or projection.get("memorial_compatible") is not True
        ):
            raise DeployError("production_projection_invalid")
        self._require_false_authorities(
            projection, denied, "production_projection_authority_ambiguous"
        )
        for field in ("rendered_compose_sha256", "stage_projection_sha256"):
            if not SHA256_RE.fullmatch(str(projection.get(field) or "")):
                raise DeployError("production_projection_digest_invalid")
        inventory, inventory_sha = self._validate_source_inventory_shape(
            projection.get("compose_source_inventory"),
            PRODUCTION_COMPOSE_SOURCE_PATHS,
        )
        overlay_entry = inventory[-1]
        if (
            projection.get("compose_source_inventory_sha256") != inventory_sha
            or projection.get("overlay_path") != PRODUCTION_OVERLAY.as_posix()
            or projection.get("overlay_blob_sha256") != overlay_entry["blob_sha256"]
            or projection.get("overlay_working_sha256")
            != overlay_entry["working_sha256"]
        ):
            raise DeployError("production_projection_source_inventory_mismatch")

        memorial_summary = projection.get("memorial_baseline")
        expected_memorial_summary = self._memorial_baseline_summary()
        if (
            not isinstance(memorial_summary, dict)
            or set(memorial_summary) != MEMORIAL_BASELINE_SUMMARY_KEYS
            or memorial_summary != expected_memorial_summary
        ):
            raise DeployError("production_memorial_baseline_mismatch")
        provenance_summary = projection.get("provenance")
        expected_provenance_summary = {
            "contract_name": PRODUCTION_PROVENANCE_CONTRACT,
            "sha256": self.provenance_document.sha256,
            "source_revision": self.source_revision,
            "image_reference": self.candidate_reference,
            "image_id": self.candidate["image_id"],
        }
        if (
            not isinstance(provenance_summary, dict)
            or set(provenance_summary) != PROVENANCE_SUMMARY_KEYS
            or provenance_summary != expected_provenance_summary
        ):
            raise DeployError("production_provenance_summary_mismatch")
        sbom_payload = self.sbom_document.payload
        sbom_summary = projection.get("sbom")
        expected_sbom_summary = {
            "contract_name": PRODUCTION_SBOM_CONTRACT,
            "sha256": self.sbom_document.sha256,
            "document_namespace": sbom_payload["document_namespace"],
            "serial_number": sbom_payload["serial_number"],
            "subject_name": "ea-runtime",
            "subject_image_reference": self.candidate_reference,
            "subject_image_id": self.candidate["image_id"],
            "subject_source_revision": self.source_revision,
        }
        if (
            not isinstance(sbom_summary, dict)
            or set(sbom_summary) != SBOM_SUMMARY_KEYS
            or sbom_summary != expected_sbom_summary
        ):
            raise DeployError("production_sbom_summary_mismatch")

        raw_qualification = projection.get("schema_v6_qualification")
        if (
            not isinstance(raw_qualification, dict)
            or set(raw_qualification) != QUALIFICATION_PROJECTION_KEYS
        ):
            raise DeployError("production_qualification_projection_invalid")
        qualification_projection = dict(raw_qualification)
        if (
            qualification_projection.get("state_version") != 6
            or not SHA256_RE.fullmatch(
                str(qualification_projection.get("state_sha256") or "")
            )
            or qualification_projection.get("terminal_identity_sha256")
            != qualification.terminal_identity_sha256
            or qualification_projection.get("qualified_at")
            != qualification.qualified_at
            or qualification_projection.get("permit_contract_name")
            != qualification.permit_contract_name
            or qualification_projection.get("permit_sha256")
            != qualification.permit_sha256
            or qualification_projection.get("permit_expires_at")
            != qualification.permit_expires_at
            or qualification_projection.get("evidence_scope")
            != "schema_v6_terminal_qualification_only"
            or qualification_projection.get("mutation_authority_transferred")
            is not False
            or qualification_projection.get("validated") is not True
        ):
            raise DeployError("production_qualification_projection_invalid")

        side_effect = projection.get("side_effect_posture")
        if (
            not isinstance(side_effect, dict)
            or set(side_effect) != SIDE_EFFECT_POSTURE_KEYS
        ):
            raise DeployError("production_side_effect_posture_invalid")
        if (
            side_effect.get("deployment_hold") is not True
            or side_effect.get("idle_command_bound") is not True
            or side_effect.get("replicas_zero")
            != {service: 0 for service in WORKER_SERVICES}
            or any(
                side_effect.get(field) is not False
                for field in (
                    "queue_mutation_authority",
                    "provider_work_authority",
                    "outbound_send_authority",
                    "runtime_activation_authority",
                )
            )
        ):
            raise DeployError("production_side_effect_posture_invalid")

        core = {
            "contract_name": PRODUCTION_PROJECTION_CONTRACT,
            "deployment_scope": projection["deployment_scope"],
            "target_services": projection["target_services"],
            "stage_mutation_services": projection["stage_mutation_services"],
            "preserved_services": projection["preserved_services"],
            "source_revision": projection["source_revision"],
            "candidate_image_reference": projection["candidate_image_reference"],
            "candidate_image_id": projection["candidate_image_id"],
            "compose_source_inventory": projection["compose_source_inventory"],
            "compose_source_inventory_sha256": projection[
                "compose_source_inventory_sha256"
            ],
            "overlay_path": projection["overlay_path"],
            "overlay_blob_sha256": projection["overlay_blob_sha256"],
            "overlay_working_sha256": projection["overlay_working_sha256"],
            "rendered_compose_sha256": projection["rendered_compose_sha256"],
            "memorial_baseline": memorial_summary,
            "schema_v6_terminal_identity_sha256": qualification_projection[
                "terminal_identity_sha256"
            ],
            "provenance": provenance_summary,
            "sbom": sbom_summary,
            "live_api_owner": projection["live_api_owner"],
            "live_api_mutation_authority": False,
            "runtime_activation_authority": False,
            "queue_mutation_authority": False,
            "provider_work_authority": False,
            "outbound_send_authority": False,
            "build_authority": False,
            "pull_authority": False,
        }
        if (
            set(core) != set(PROJECTION_CORE_KEYS)
            or _canonical_sha256(core) != projection["stage_projection_sha256"]
        ):
            raise DeployError("production_stage_projection_digest_mismatch")
        return projection

    def _read_evidence(self) -> None:
        if not self.configuration_receipt_value:
            raise DeployError("candidate_configuration_receipt_required")
        if not self.provenance_receipt_value:
            raise DeployError("candidate_provenance_receipt_required")
        if not self.sbom_receipt_value:
            raise DeployError("candidate_sbom_receipt_required")
        self.configuration_document = _read_trusted_json(
            self.configuration_receipt_path,
            expected_uid=self.evidence_owner_uid,
            maximum_bytes=MAX_EVIDENCE_BYTES,
            reason_prefix="candidate_configuration_receipt",
        )
        self.provenance_document = _read_trusted_json(
            self.provenance_receipt_path,
            expected_uid=self.evidence_owner_uid,
            maximum_bytes=MAX_EVIDENCE_BYTES,
            reason_prefix="candidate_provenance_receipt",
        )
        self.sbom_document = _read_trusted_json(
            self.sbom_receipt_path,
            expected_uid=self.evidence_owner_uid,
            maximum_bytes=MAX_EVIDENCE_BYTES,
            reason_prefix="candidate_sbom_receipt",
        )
        configuration = self.configuration_document.payload
        if _contract_name(configuration) == CANDIDATE_PREFLIGHT_CONTRACT:
            projection = configuration.get("configuration_projection")
            if not isinstance(projection, dict):
                raise DeployError("candidate_configuration_projection_invalid")
            self.configuration_projection = dict(projection)
            overlay_sha = str(projection.get("overlay_sha256") or "")
            rendered_sha = str(projection.get("rendered_contract_sha256") or "")
            if (
                _contract_name(projection) != CANDIDATE_CONFIGURATION_CONTRACT
                or str(projection.get("status") or "").lower() != "pass"
                or projection.get("configuration_only") is not True
                or projection.get("deploy_ready") is not False
                or list(projection.get("target_services") or [])
                != list(TARGET_SERVICES)
                or projection.get("source_revision") != self.source_revision
                or projection.get("candidate_image_reference")
                != self.candidate_reference
                or projection.get("execution_scope")
                != "isolated_candidate_configuration"
                or projection.get("live_api_owner") != "memorial"
                or projection.get("owner_handoff_required") is not True
                or projection.get("silent_takeover_allowed") is not False
                or not SHA256_RE.fullmatch(overlay_sha)
                or not SHA256_RE.fullmatch(rendered_sha)
                or any(
                    projection.get(field) is not False
                    for field in INERT_CONFIGURATION_AUTHORITY_FIELDS
                )
            ):
                raise DeployError("candidate_configuration_projection_invalid")
            if (
                projection.get("group_deploy_eligible") is not True
                or projection.get("memorial_compatible") is not True
            ):
                raise DeployError("inert_candidate_configuration_forbidden")
            raise DeployError("candidate_configuration_has_no_live_authority")

        if _contract_name(configuration) != PRODUCTION_PREFLIGHT_CONTRACT:
            raise DeployError("approved_production_configuration_contract_required")
        if not self.memorial_baseline_receipt_value:
            raise DeployError("memorial_baseline_receipt_required")
        self.memorial_baseline_document = _read_trusted_json(
            self.memorial_baseline_receipt_path,
            expected_uid=self.root_authority_uid,
            expected_mode=0o644,
            maximum_bytes=MAX_EVIDENCE_BYTES,
            reason_prefix="memorial_baseline_receipt",
        )
        self._validate_provenance_and_sbom()
        qualification = self._load_schema_v6_qualification()
        self.configuration_projection = self._validate_production_projection(
            configuration,
            qualification,
        )
        self.schema_v6_qualification = qualification

    def _production_overlay(self) -> Path:
        if not self.production_overlay_value:
            raise DeployError("verified_production_overlay_required")
        relative = Path(self.production_overlay_value)
        if relative.is_absolute() or relative != PRODUCTION_OVERLAY:
            raise DeployError("production_overlay_path_invalid")
        requested = (self.root / relative).absolute()
        resolved = requested.resolve()
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise DeployError("production_overlay_path_invalid") from exc
        if resolved != requested or not resolved.is_file():
            raise DeployError("verified_production_overlay_required")
        observed = _trusted_input_sha256(
            resolved,
            allowed_uids={0, os.geteuid(), self.release_source_uid},
            reason="production_overlay",
        )
        expected = str(
            self.configuration_projection.get("overlay_working_sha256") or ""
        )
        if not SHA256_RE.fullmatch(expected) or observed != expected:
            raise DeployError("production_overlay_projection_mismatch")
        self.production_overlay_sha256 = observed
        if self.production_overlay_snapshot_path is None:
            if not self.rollback_snapshot_dir.is_dir():
                raise DeployError("production_overlay_snapshot_directory_missing")
            snapshot = self.rollback_snapshot_dir / "production-overlay.yml"
            try:
                copied = _copy_trusted_input(
                    resolved,
                    snapshot,
                    expected_sha256=expected,
                    allowed_uids={0, os.geteuid(), self.release_source_uid},
                    reason="production_overlay_snapshot",
                )
            except Exception:
                snapshot.unlink(missing_ok=True)
                raise
            if copied != expected:
                snapshot.unlink(missing_ok=True)
                raise DeployError("production_overlay_snapshot_changed")
            self.rollback_snapshot_paths.append(snapshot)
            self.production_overlay_snapshot_path = snapshot
            _fsync_directory(
                self.rollback_snapshot_dir,
                reason="production_overlay_snapshot_directory",
            )
        snapshot_digest = _trusted_input_sha256(
            self.production_overlay_snapshot_path,
            allowed_uids={os.geteuid()},
            reason="production_overlay_snapshot",
        )
        if snapshot_digest != expected:
            raise DeployError("production_overlay_snapshot_changed")
        return self.production_overlay_snapshot_path

    def _production_target_compose_files(self) -> tuple[str, ...]:
        overlay = self._production_overlay()
        return (*PRODUCTION_BASE_COMPOSE_FILES, str(overlay))

    def _inspect_container(
        self, service: str, *, allow_absent: bool = False
    ) -> dict[str, Any] | None:
        result = self._run(
            ["docker", "inspect", service],
            check=not allow_absent,
        )
        if allow_absent and result.returncode == 1:
            if result.stdout.strip() != "[]":
                raise DeployError(f"container_inspection_invalid:{service}")
            return None
        if result.returncode != 0:
            raise DeployError(f"container_inspection_failed:{service}")
        try:
            rows = json.loads(result.stdout)
        except Exception as exc:
            raise DeployError(f"container_inspection_invalid:{service}") from exc
        if (
            not isinstance(rows, list)
            or len(rows) != 1
            or not isinstance(rows[0], dict)
        ):
            raise DeployError(f"container_inspection_invalid:{service}")
        return dict(rows[0])

    def _topology(self, inspection: Mapping[str, Any], service: str) -> dict[str, Any]:
        config = dict(inspection.get("Config") or {})
        labels = dict(config.get("Labels") or {})
        if labels.get("com.docker.compose.project") != PROJECT_NAME:
            raise DeployError(f"live_owner_project_mismatch:{service}")
        if labels.get("com.docker.compose.service") != service:
            raise DeployError(f"live_owner_service_mismatch:{service}")
        working = Path(
            str(labels.get("com.docker.compose.project.working_dir") or "")
        ).expanduser()
        if not working.is_absolute() or not working.is_dir():
            raise DeployError(f"rollback_working_directory_invalid:{service}")
        raw_files = str(labels.get("com.docker.compose.project.config_files") or "")
        if not raw_files:
            raise DeployError(f"rollback_compose_files_missing:{service}")
        compose_config_sha256 = str(labels.get("com.docker.compose.config-hash") or "")
        if not SHA256_RE.fullmatch(compose_config_sha256):
            raise DeployError(f"rollback_compose_config_hash_missing:{service}")
        files: list[str] = []
        inputs: list[dict[str, str]] = []
        for raw in raw_files.split(","):
            path = Path(raw.strip())
            if not path.is_absolute():
                path = working / path
            path = path.resolve()
            if not path.is_file():
                raise DeployError(f"rollback_compose_input_missing:{service}")
            files.append(str(path))
            inputs.append(
                {
                    "name": path.name,
                    "sha256": _trusted_input_sha256(
                        path,
                        allowed_uids={0, os.geteuid(), self.release_source_uid},
                        reason=f"rollback_compose_input:{service}",
                    ),
                }
            )
        active_topology = self._load_active_topology_manifest(
            files=files,
            working_dir=working,
            service=service,
        )
        if (
            active_topology is not None
            and active_topology["compose_config_sha256"] != compose_config_sha256
        ):
            raise DeployError(f"active_topology_config_hash_changed:{service}")
        env_file = (
            Path(active_topology["env_file"])
            if active_topology is not None
            else working / ".env"
        )
        if not env_file.is_file():
            raise DeployError(f"rollback_env_file_missing:{service}")
        env_sha256 = (
            str(active_topology["env_sha256"])
            if active_topology is not None
            else _trusted_input_sha256(
                env_file,
                allowed_uids={0, os.geteuid(), self.release_source_uid},
                reason=f"rollback_env_file:{service}",
            )
        )
        return {
            "working_dir": str(working.resolve()),
            "working_dir_sha256": hashlib.sha256(
                str(working.resolve()).encode()
            ).hexdigest(),
            "compose_files": files,
            "compose_inputs": inputs,
            "compose_config_sha256": compose_config_sha256,
            "env_file": str(env_file.resolve()),
            "env_sha256": env_sha256,
            "topology_manifest_sha256": (
                str(active_topology["sha256"]) if active_topology is not None else ""
            ),
        }

    @staticmethod
    def _owner_class(
        service: str, topology: Mapping[str, Any], env: Mapping[str, str]
    ) -> str:
        basenames = {Path(str(path)).name for path in topology["compose_files"]}
        if service == API_SERVICE and (
            env.get("EA_DEPLOY_PRIMARY_MODE") == "MEMORIAL"
            or "docker-compose.memorial.yml" in basenames
        ):
            return "memorial"
        if service == "ea-whatsapp-web-action-processor":
            return "whatsapp-action-runtime"
        return "ea-core-runtime"

    @staticmethod
    def _restart_name(value: object) -> str:
        if isinstance(value, dict):
            value = value.get("Name")
        name = str(value or "").strip().lower()
        return "" if name in {"", "no", "none"} else name

    @staticmethod
    def _non_compose_labels(value: object) -> dict[str, str]:
        if not isinstance(value, dict):
            return {}
        return {
            str(key): str(item)
            for key, item in value.items()
            if not str(key).startswith("com.docker.compose.")
        }

    @staticmethod
    def _compose_service_labels(value: object) -> dict[str, str]:
        return {
            key: item
            for key, item in AudiobookRuntimeDeployLane._non_compose_labels(
                value
            ).items()
            if not key.startswith("org.opencontainers.image.")
        }

    @staticmethod
    def _tmpfs_projection(value: object) -> list[str]:
        if isinstance(value, dict):
            return sorted(f"{key}:{item}".rstrip(":") for key, item in value.items())
        if isinstance(value, list):
            return sorted(str(item).rstrip(":") for item in value)
        return []

    @staticmethod
    def _device_projection(value: object) -> list[dict[str, str]]:
        result: list[dict[str, str]] = []
        for raw in list(value or []) if isinstance(value, list) else []:
            if isinstance(raw, dict):
                result.append(
                    {
                        "source": str(raw.get("source") or raw.get("PathOnHost") or ""),
                        "target": str(
                            raw.get("target") or raw.get("PathInContainer") or ""
                        ),
                        "permissions": str(
                            raw.get("permissions") or raw.get("CgroupPermissions") or ""
                        ),
                    }
                )
            else:
                parts = str(raw).split(":")
                result.append(
                    {
                        "source": parts[0] if parts else "",
                        "target": parts[1] if len(parts) > 1 else "",
                        "permissions": parts[2] if len(parts) > 2 else "",
                    }
                )
        return sorted(result, key=lambda row: json.dumps(row, sort_keys=True))

    @staticmethod
    def _ulimit_projection(value: object) -> list[dict[str, object]]:
        result: list[dict[str, object]] = []
        if isinstance(value, dict):
            iterable = []
            for name, raw in value.items():
                if isinstance(raw, dict):
                    iterable.append(
                        {
                            "Name": name,
                            "Soft": raw.get("soft"),
                            "Hard": raw.get("hard"),
                        }
                    )
                else:
                    iterable.append({"Name": name, "Soft": raw, "Hard": raw})
        elif isinstance(value, list):
            iterable = value
        else:
            iterable = []
        for raw in iterable:
            if isinstance(raw, dict):
                result.append(
                    {
                        "name": str(raw.get("Name") or raw.get("name") or ""),
                        "soft": raw.get("Soft", raw.get("soft")),
                        "hard": raw.get("Hard", raw.get("hard")),
                    }
                )
        return sorted(result, key=lambda row: str(row["name"]))

    @staticmethod
    def _port_projection(value: object) -> list[dict[str, str]]:
        result: list[dict[str, str]] = []
        if isinstance(value, dict):
            for container, bindings in value.items():
                target, _, protocol = str(container).partition("/")
                for raw in list(bindings or []):
                    binding = dict(raw) if isinstance(raw, dict) else {}
                    result.append(
                        {
                            "target": target,
                            "protocol": protocol or "tcp",
                            "published": str(binding.get("HostPort") or ""),
                            "host_ip": str(binding.get("HostIp") or ""),
                        }
                    )
        elif isinstance(value, list):
            for raw in value:
                if isinstance(raw, dict):
                    result.append(
                        {
                            "target": str(raw.get("target") or ""),
                            "protocol": str(raw.get("protocol") or "tcp"),
                            "published": str(raw.get("published") or ""),
                            "host_ip": str(raw.get("host_ip") or ""),
                        }
                    )
        return sorted(result, key=lambda row: json.dumps(row, sort_keys=True))

    @staticmethod
    def _resource_device_projection(
        value: object, amount_names: Sequence[str]
    ) -> list[dict[str, object]]:
        result: list[dict[str, object]] = []
        for raw in list(value or []) if isinstance(value, list) else []:
            if not isinstance(raw, dict):
                raise DeployError("rollback_resource_device_invalid")
            path = str(raw.get("Path") or raw.get("path") or "")
            amount: object = None
            for name in amount_names:
                if name in raw:
                    amount = raw[name]
                    break
            result.append(
                {
                    "path_sha256": hashlib.sha256(path.encode()).hexdigest(),
                    "amount": amount,
                }
            )
        return sorted(result, key=lambda row: str(row["path_sha256"]))

    @staticmethod
    def _normalized_pids_limit(value: object) -> object:
        return None if value in {None, 0, -1} else value

    def _inspection_resource_projection(
        self, host: Mapping[str, Any]
    ) -> dict[str, object]:
        return {
            "blkio_weight": int(host.get("BlkioWeight") or 0),
            "blkio_weight_device": self._resource_device_projection(
                host.get("BlkioWeightDevice"), ("Weight", "weight")
            ),
            "device_read_bps": self._resource_device_projection(
                host.get("BlkioDeviceReadBps"), ("Rate", "rate")
            ),
            "device_read_iops": self._resource_device_projection(
                host.get("BlkioDeviceReadIOps"), ("Rate", "rate")
            ),
            "device_write_bps": self._resource_device_projection(
                host.get("BlkioDeviceWriteBps"), ("Rate", "rate")
            ),
            "device_write_iops": self._resource_device_projection(
                host.get("BlkioDeviceWriteIOps"), ("Rate", "rate")
            ),
            "cpu_count": int(host.get("CpuCount") or 0),
            "cpu_percent": int(host.get("CpuPercent") or 0),
            "cpu_period": int(host.get("CpuPeriod") or 0),
            "cpu_quota": int(host.get("CpuQuota") or 0),
            "cpu_rt_period": int(host.get("CpuRealtimePeriod") or 0),
            "cpu_rt_runtime": int(host.get("CpuRealtimeRuntime") or 0),
            "cpu_shares": int(host.get("CpuShares") or 0),
            "nano_cpus": int(host.get("NanoCpus") or 0),
            "cpuset": str(host.get("CpusetCpus") or ""),
            "cpuset_mems": str(host.get("CpusetMems") or ""),
            "io_maximum_bandwidth": int(host.get("IOMaximumBandwidth") or 0),
            "io_maximum_iops": int(host.get("IOMaximumIOps") or 0),
            "memory": int(host.get("Memory") or 0),
            "memory_reservation": int(host.get("MemoryReservation") or 0),
            "memory_swap": int(host.get("MemorySwap") or 0),
            "memory_swappiness": host.get("MemorySwappiness"),
            "oom_kill_disable": bool(host.get("OomKillDisable")),
            "oom_score_adj": int(host.get("OomScoreAdj") or 0),
            "pids_limit": self._normalized_pids_limit(host.get("PidsLimit")),
            "shm_size": int(host.get("ShmSize") or DEFAULT_DOCKER_SHM_SIZE),
            "cgroup_parent": str(host.get("CgroupParent") or ""),
            "storage_opt": dict(host.get("StorageOpt") or {}),
        }

    def _rendered_resource_projection(
        self, service: Mapping[str, Any]
    ) -> dict[str, object]:
        blkio = dict(service.get("blkio_config") or {})
        cpus = service.get("cpus")
        nano_cpus = int(float(cpus) * 1_000_000_000) if cpus else 0
        return {
            "blkio_weight": int(blkio.get("weight") or 0),
            "blkio_weight_device": self._resource_device_projection(
                blkio.get("weight_device"), ("weight", "Weight")
            ),
            "device_read_bps": self._resource_device_projection(
                blkio.get("device_read_bps"), ("rate", "Rate")
            ),
            "device_read_iops": self._resource_device_projection(
                blkio.get("device_read_iops"), ("rate", "Rate")
            ),
            "device_write_bps": self._resource_device_projection(
                blkio.get("device_write_bps"), ("rate", "Rate")
            ),
            "device_write_iops": self._resource_device_projection(
                blkio.get("device_write_iops"), ("rate", "Rate")
            ),
            "cpu_count": int(service.get("cpu_count") or 0),
            "cpu_percent": int(service.get("cpu_percent") or 0),
            "cpu_period": int(service.get("cpu_period") or 0),
            "cpu_quota": int(service.get("cpu_quota") or 0),
            "cpu_rt_period": int(service.get("cpu_rt_period") or 0),
            "cpu_rt_runtime": int(service.get("cpu_rt_runtime") or 0),
            "cpu_shares": int(service.get("cpu_shares") or 0),
            "nano_cpus": nano_cpus,
            "cpuset": str(service.get("cpuset") or ""),
            "cpuset_mems": str(service.get("cpuset_mems") or ""),
            "io_maximum_bandwidth": int(service.get("io_maximum_bandwidth") or 0),
            "io_maximum_iops": int(service.get("io_maximum_iops") or 0),
            "memory": int(service.get("mem_limit") or 0),
            "memory_reservation": int(service.get("mem_reservation") or 0),
            "memory_swap": int(service.get("memswap_limit") or 0),
            "memory_swappiness": service.get("mem_swappiness"),
            "oom_kill_disable": bool(service.get("oom_kill_disable")),
            "oom_score_adj": int(service.get("oom_score_adj") or 0),
            "pids_limit": self._normalized_pids_limit(service.get("pids_limit")),
            "shm_size": int(service.get("shm_size") or DEFAULT_DOCKER_SHM_SIZE),
            "cgroup_parent": str(service.get("cgroup_parent") or ""),
            "storage_opt": dict(service.get("storage_opt") or {}),
        }

    @staticmethod
    def _normalized_network_name(raw_name: object) -> str:
        if not isinstance(raw_name, str) or not raw_name:
            raise DeployError("prior_network_endpoint_field_unsupported")
        prefix = f"{PROJECT_NAME}_"
        return raw_name[len(prefix) :] if raw_name.startswith(prefix) else raw_name

    @staticmethod
    def _network_string_list(raw: object, *, reason: str) -> list[str]:
        if raw is None:
            return []
        if not isinstance(raw, list) or any(
            not isinstance(value, str) for value in raw
        ):
            raise DeployError(reason)
        return sorted(raw)

    @staticmethod
    def _normalized_mac_address(raw: object, *, reason: str) -> str:
        if raw is None or raw == "":
            return ""
        if not isinstance(raw, str):
            raise DeployError(reason)
        normalized = raw.strip().lower()
        if not MAC_ADDRESS_RE.fullmatch(normalized):
            raise DeployError(reason)
        return normalized

    def _runtime_network_aliases(self, inspection: Mapping[str, Any]) -> frozenset[str]:
        config = dict(inspection.get("Config") or {})
        labels = dict(config.get("Labels") or {})
        container_id = str(inspection.get("Id") or "")
        candidates = {
            str(inspection.get("Name") or "").lstrip("/"),
            str(config.get("Hostname") or ""),
            str(labels.get("com.docker.compose.service") or ""),
            container_id,
            container_id[:12],
        }
        return frozenset(value for value in candidates if value)

    def _network_endpoint_contract(
        self,
        inspection: Mapping[str, Any],
        requested_network_endpoints: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> dict[str, dict[str, Any]]:
        configured_mac_address = self._normalized_mac_address(
            dict(inspection.get("Config") or {}).get("MacAddress"),
            reason="prior_network_global_mac_invalid",
        )
        network_settings = inspection.get("NetworkSettings")
        if not isinstance(network_settings, dict):
            raise DeployError("prior_network_settings_invalid")
        raw_networks = network_settings.get("Networks")
        if not isinstance(raw_networks, dict) or not raw_networks:
            raise DeployError("prior_network_endpoints_invalid")
        if requested_network_endpoints is not None and not isinstance(
            requested_network_endpoints, Mapping
        ):
            raise DeployError("prior_network_render_contract_invalid")
        if (
            requested_network_endpoints is not None
            and configured_mac_address
            and len(raw_networks) != 1
        ):
            raise DeployError("prior_network_global_mac_ambiguous")
        runtime_aliases = self._runtime_network_aliases(inspection)
        result: dict[str, dict[str, Any]] = {}
        for raw_name, raw in raw_networks.items():
            if not isinstance(raw, dict) or not set(raw).issubset(
                RESTORABLE_NETWORK_ENDPOINT_KEYS
            ):
                raise DeployError("prior_network_endpoint_field_unsupported")
            name = self._normalized_network_name(raw_name)
            if name in result:
                raise DeployError("prior_network_name_collision")
            raw_ipam = raw.get("IPAMConfig")
            if raw_ipam is None:
                ipam: dict[str, Any] = {}
            elif isinstance(raw_ipam, dict) and set(raw_ipam).issubset(
                RESTORABLE_NETWORK_IPAM_KEYS
            ):
                ipam = {
                    "IPv4Address": str(raw_ipam.get("IPv4Address") or ""),
                    "IPv6Address": str(raw_ipam.get("IPv6Address") or ""),
                    "LinkLocalIPs": self._network_string_list(
                        raw_ipam.get("LinkLocalIPs"),
                        reason="prior_network_ipam_link_local_invalid",
                    ),
                }
            else:
                raise DeployError("prior_network_ipam_field_unsupported")
            driver_opts = raw.get("DriverOpts")
            if driver_opts is None:
                normalized_driver_opts: dict[str, str] = {}
            elif isinstance(driver_opts, dict):
                normalized_driver_opts = {
                    str(key): str(value) for key, value in sorted(driver_opts.items())
                }
            else:
                raise DeployError("prior_network_driver_opts_invalid")
            observed_endpoint_mac = self._normalized_mac_address(
                raw.get("MacAddress"), reason="prior_network_endpoint_mac_invalid"
            )
            requested_mac_address = ""
            requested_mac_source = ""
            if requested_network_endpoints is not None:
                requested = requested_network_endpoints.get(name)
                if not isinstance(requested, Mapping):
                    raise DeployError("prior_network_render_contract_missing")
                requested_mac_address = self._normalized_mac_address(
                    requested.get("MacAddress"),
                    reason="prior_network_render_mac_invalid",
                )
                requested_mac_source = str(requested.get("MacAddressSource") or "")
                if requested_mac_source not in {"", "global", "network"} or bool(
                    requested_mac_address
                ) != bool(requested_mac_source):
                    raise DeployError("prior_network_render_mac_invalid")
                if not requested_mac_address:
                    if configured_mac_address:
                        raise DeployError("prior_network_mac_render_conflict")
                else:
                    if configured_mac_address and len(raw_networks) != 1:
                        raise DeployError("prior_network_global_mac_ambiguous")
                    if (
                        configured_mac_address
                        and configured_mac_address != requested_mac_address
                    ):
                        raise DeployError("prior_network_mac_render_conflict")
                    if (
                        observed_endpoint_mac
                        and observed_endpoint_mac != requested_mac_address
                    ):
                        raise DeployError("prior_network_mac_render_conflict")
                    if (
                        requested_mac_source == "network"
                        and not observed_endpoint_mac
                        and not configured_mac_address
                    ):
                        raise DeployError("prior_network_requested_mac_missing")
                    if (
                        requested_mac_source == "global"
                        and not observed_endpoint_mac
                        and not configured_mac_address
                    ):
                        raise DeployError("prior_network_requested_mac_missing")
            result[name] = {
                "Aliases": [
                    value
                    for value in self._network_string_list(
                        raw.get("Aliases"), reason="prior_network_aliases_invalid"
                    )
                    if value not in runtime_aliases
                ],
                "DriverOpts": normalized_driver_opts,
                "GwPriority": int(raw.get("GwPriority") or 0),
                "IPAMConfig": ipam,
                "Links": self._network_string_list(
                    raw.get("Links"), reason="prior_network_links_invalid"
                ),
                "MacAddress": requested_mac_address,
                "MacAddressSource": requested_mac_source,
            }
        if requested_network_endpoints is not None and set(result) != set(
            requested_network_endpoints
        ):
            raise DeployError("prior_network_render_contract_mismatch")
        return {name: result[name] for name in sorted(result)}

    def _rendered_network_endpoint_contract(
        self, service: Mapping[str, Any]
    ) -> dict[str, dict[str, Any]]:
        networks_value = service.get("networks")
        if isinstance(networks_value, dict):
            entries = list(networks_value.items())
        elif isinstance(networks_value, list) and all(
            isinstance(value, str) and value for value in networks_value
        ):
            entries = [(value, None) for value in networks_value]
        elif networks_value is None:
            entries = [("default", None)]
        else:
            raise DeployError("rollback_rendered_networks_invalid")
        if not entries:
            raise DeployError("rollback_rendered_networks_invalid")

        top_level_links = self._network_string_list(
            service.get("links"), reason="rollback_rendered_network_links_invalid"
        )
        top_level_mac = self._normalized_mac_address(
            service.get("mac_address"),
            reason="rollback_rendered_network_mac_invalid",
        )
        if len(entries) != 1 and top_level_links:
            raise DeployError("rollback_rendered_network_links_ambiguous")
        if len(entries) != 1 and top_level_mac:
            raise DeployError("rollback_rendered_network_mac_ambiguous")

        result: dict[str, dict[str, Any]] = {}
        for raw_name, raw_config in entries:
            name = self._normalized_network_name(raw_name)
            if name in result:
                raise DeployError("rollback_rendered_network_name_collision")
            if raw_config is None:
                config: dict[str, Any] = {}
            elif isinstance(raw_config, dict):
                config = raw_config
            else:
                raise DeployError("rollback_rendered_network_endpoint_invalid")
            if not set(config).issubset(RESTORABLE_RENDERED_NETWORK_ENDPOINT_KEYS):
                raise DeployError("rollback_rendered_network_field_unsupported")
            if int(config.get("priority") or 0) != 0:
                raise DeployError("rollback_rendered_network_priority_unrepresentable")

            driver_opts = config.get("driver_opts")
            if driver_opts is None:
                normalized_driver_opts: dict[str, str] = {}
            elif isinstance(driver_opts, dict):
                normalized_driver_opts = {
                    str(key): str(value) for key, value in sorted(driver_opts.items())
                }
            else:
                raise DeployError("rollback_rendered_network_driver_opts_invalid")

            ipam_keys = ("ipv4_address", "ipv6_address", "link_local_ips")
            if any(key in config for key in ipam_keys):
                ipam = {
                    "IPv4Address": str(config.get("ipv4_address") or ""),
                    "IPv6Address": str(config.get("ipv6_address") or ""),
                    "LinkLocalIPs": self._network_string_list(
                        config.get("link_local_ips"),
                        reason="rollback_rendered_network_link_local_invalid",
                    ),
                }
            else:
                ipam = {}

            endpoint_mac = self._normalized_mac_address(
                config.get("mac_address"),
                reason="rollback_rendered_network_mac_invalid",
            )
            if top_level_mac and endpoint_mac and top_level_mac != endpoint_mac:
                raise DeployError("rollback_rendered_network_mac_conflict")
            result[name] = {
                "Aliases": self._network_string_list(
                    config.get("aliases"),
                    reason="rollback_rendered_network_aliases_invalid",
                ),
                "DriverOpts": normalized_driver_opts,
                "GwPriority": int(config.get("gw_priority") or 0),
                "IPAMConfig": ipam,
                "Links": top_level_links if len(entries) == 1 else [],
                "MacAddress": endpoint_mac or top_level_mac,
                "MacAddressSource": (
                    "network" if endpoint_mac else "global" if top_level_mac else ""
                ),
            }
        return {name: result[name] for name in sorted(result)}

    def _inspection_restorable_contract(
        self,
        inspection: Mapping[str, Any],
        requested_network_endpoints: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        config = dict(inspection.get("Config") or {})
        host = dict(inspection.get("HostConfig") or {})
        if not set(config).issubset(RESTORABLE_CONFIG_KEYS):
            raise DeployError("prior_config_field_unsupported")
        unsupported_host_fields = set(host) - RESTORABLE_HOST_CONFIG_KEYS
        if unsupported_host_fields:
            raise DeployError("prior_host_config_field_unsupported")
        network_endpoints = self._network_endpoint_contract(
            inspection, requested_network_endpoints
        )
        normalized_config = {
            field: config.get(field) for field in sorted(RESTORABLE_CONFIG_KEYS)
        }
        normalized_config["Env"] = sorted(
            str(item) for item in list(config.get("Env") or [])
        )
        normalized_config["Labels"] = self._non_compose_labels(config.get("Labels"))
        return {
            "config": normalized_config,
            "host_config": {field: host[field] for field in sorted(host)},
            "mounts": _mounts_from_inspection(inspection),
            "mount_contract_sha256": _canonical_sha256(
                list(inspection.get("Mounts") or [])
            ),
            "network_endpoints": network_endpoints,
        }

    def _inspection_rollback_projection(
        self,
        inspection: Mapping[str, Any],
        requested_network_endpoints: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        config = dict(inspection.get("Config") or {})
        host = dict(inspection.get("HostConfig") or {})
        return {
            "image_reference": str(config.get("Image") or ""),
            "process": {
                "command": config.get("Cmd"),
                "entrypoint": config.get("Entrypoint"),
                "user": config.get("User"),
                "working_dir": config.get("WorkingDir"),
            },
            "environment": _environment_map(
                [str(item) for item in list(config.get("Env") or [])]
            ),
            "labels": self._compose_service_labels(config.get("Labels")),
            "mounts": _mounts_from_inspection(inspection),
            "resources": self._inspection_resource_projection(host),
            "security": {
                "read_only": bool(host.get("ReadonlyRootfs")),
                "privileged": bool(host.get("Privileged")),
                "cap_add": sorted(str(item) for item in list(host.get("CapAdd") or [])),
                "cap_drop": sorted(
                    str(item) for item in list(host.get("CapDrop") or [])
                ),
                "security_opt": sorted(
                    str(item) for item in list(host.get("SecurityOpt") or [])
                ),
                "restart": self._restart_name(host.get("RestartPolicy")),
                "network_endpoints": self._network_endpoint_contract(
                    inspection, requested_network_endpoints
                ),
                "tmpfs": self._tmpfs_projection(host.get("Tmpfs")),
                "devices": self._device_projection(host.get("Devices")),
                "sysctls": host.get("Sysctls") or {},
                "ulimits": self._ulimit_projection(host.get("Ulimits")),
                "port_bindings": self._port_projection(host.get("PortBindings")),
                "init": bool(host.get("Init")),
                "ipc": ""
                if str(host.get("IpcMode") or "") in {"", "private"}
                else str(host.get("IpcMode")),
                "pid": host.get("PidMode") or "",
            },
        }

    def _rendered_rollback_projection(
        self, service: Mapping[str, Any]
    ) -> dict[str, Any]:
        return {
            "image_reference": str(service.get("image") or ""),
            "process": {
                "command": service.get("command"),
                "entrypoint": service.get("entrypoint"),
                "user": service.get("user"),
                "working_dir": service.get("working_dir") or "",
            },
            "environment": _rendered_environment(service),
            "labels": self._compose_service_labels(service.get("labels")),
            "mounts": _rendered_mounts(service),
            "resources": self._rendered_resource_projection(service),
            "security": {
                "read_only": bool(service.get("read_only")),
                "privileged": bool(service.get("privileged")),
                "cap_add": sorted(
                    str(item) for item in list(service.get("cap_add") or [])
                ),
                "cap_drop": sorted(
                    str(item) for item in list(service.get("cap_drop") or [])
                ),
                "security_opt": sorted(
                    str(item) for item in list(service.get("security_opt") or [])
                ),
                "restart": self._restart_name(service.get("restart")),
                "network_endpoints": self._rendered_network_endpoint_contract(service),
                "tmpfs": self._tmpfs_projection(service.get("tmpfs")),
                "devices": self._device_projection(service.get("devices")),
                "sysctls": service.get("sysctls") or {},
                "ulimits": self._ulimit_projection(service.get("ulimits")),
                "port_bindings": self._port_projection(service.get("ports")),
                "init": bool(service.get("init")),
                "ipc": service.get("ipc") or "",
                "pid": service.get("pid") or "",
            },
        }

    @staticmethod
    def _rendered_rollback_matches_live(
        rendered: Mapping[str, Any], live: Mapping[str, Any]
    ) -> bool:
        if (
            rendered.get("image_reference") != live.get("image_reference")
            or rendered.get("mounts") != live.get("mounts")
            or rendered.get("resources") != live.get("resources")
            or rendered.get("security") != live.get("security")
        ):
            return False
        rendered_process = dict(rendered.get("process") or {})
        live_process = dict(live.get("process") or {})
        for key, value in rendered_process.items():
            if value not in (None, "", []) and live_process.get(key) != value:
                return False
        rendered_environment = dict(rendered.get("environment") or {})
        live_environment = dict(live.get("environment") or {})
        if any(
            live_environment.get(key) != value
            for key, value in rendered_environment.items()
        ):
            return False
        rendered_labels = dict(rendered.get("labels") or {})
        live_labels = dict(live.get("labels") or {})
        return not any(
            live_labels.get(key) != value for key, value in rendered_labels.items()
        )

    def _container_identity(
        self,
        inspection: Mapping[str, Any],
        service: str,
        requested_network_endpoints: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        config = dict(inspection.get("Config") or {})
        host = dict(inspection.get("HostConfig") or {})
        state = dict(inspection.get("State") or {})
        image_id = str(inspection.get("Image") or "")
        image_reference = str(config.get("Image") or "")
        if not IMAGE_ID_RE.fullmatch(image_id):
            raise DeployError(f"prior_image_id_invalid:{service}")
        if not (
            TAGGED_IMAGE_RE.fullmatch(image_reference)
            or DIGEST_IMAGE_RE.fullmatch(image_reference)
        ):
            raise DeployError(f"prior_image_reference_unrestorable:{service}")
        if bool(state.get("Running")) and not bool(state.get("Restarting")):
            health = str(dict(state.get("Health") or {}).get("Status") or "")
            if health and health != "healthy":
                raise DeployError(f"prior_container_not_ready:{service}")
            lifecycle = "running"
        elif service in WORKER_SERVICES:
            self._paused_worker_contract(
                inspection,
                service,
                expected_files=None,
                requested_network_endpoints=requested_network_endpoints,
            )
            lifecycle = "non_running"
        else:
            raise DeployError(f"prior_container_not_ready:{service}")
        env_entries = sorted(str(item) for item in list(config.get("Env") or []))
        env = _environment_map(env_entries)
        topology = self._topology(inspection, service)
        rollback_projection = self._inspection_rollback_projection(
            inspection, requested_network_endpoints
        )
        restorable_contract = self._inspection_restorable_contract(
            inspection, requested_network_endpoints
        )
        runtime = {
            "lifecycle": lifecycle,
            "image_id": image_id,
            "image_reference": image_reference,
            "environment_sha256": _canonical_sha256(env_entries),
            "process_sha256": _canonical_sha256(
                {
                    "command": config.get("Cmd"),
                    "entrypoint": config.get("Entrypoint"),
                    "user": config.get("User"),
                }
            ),
            "mounts": _mounts_from_inspection(inspection),
            "security_sha256": _canonical_sha256(
                {
                    "read_only": bool(host.get("ReadonlyRootfs")),
                    "cap_drop": sorted(
                        str(item) for item in list(host.get("CapDrop") or [])
                    ),
                    "security_opt": sorted(
                        str(item) for item in list(host.get("SecurityOpt") or [])
                    ),
                    "restart": dict(host.get("RestartPolicy") or {}),
                    "networks": sorted(
                        dict(
                            dict(inspection.get("NetworkSettings") or {}).get(
                                "Networks"
                            )
                            or {}
                        )
                    ),
                }
            ),
            "topology_sha256": _canonical_sha256(
                {
                    "working_dir_sha256": topology["working_dir_sha256"],
                    "compose_files_sha256": _canonical_sha256(
                        topology["compose_files"]
                    ),
                    "compose_inputs": topology["compose_inputs"],
                    "compose_config_sha256": topology["compose_config_sha256"],
                    "env_file_sha256": hashlib.sha256(
                        topology["env_file"].encode()
                    ).hexdigest(),
                    "env_sha256": topology["env_sha256"],
                    "topology_manifest_sha256": topology["topology_manifest_sha256"],
                }
            ),
            "rollback_projection_sha256": _canonical_sha256(rollback_projection),
            "restorable_contract_sha256": _canonical_sha256(restorable_contract),
        }
        return {
            "service": service,
            "container_id": str(inspection.get("Id") or ""),
            "owner": self._owner_class(service, topology, env),
            "safe_source_revision": env.get("EA_SOURCE_REVISION", ""),
            "topology": topology,
            "runtime": runtime,
            "rollback_projection": rollback_projection,
            "requested_network_endpoints": (
                {
                    name: dict(endpoint)
                    for name, endpoint in requested_network_endpoints.items()
                }
                if requested_network_endpoints is not None
                else None
            ),
            "_inspection": inspection,
            "identity_sha256": _canonical_sha256(runtime),
        }

    def _capture_pre_state(self) -> None:
        services: dict[str, Any] = {}
        for service in EXPECTED_RUNTIME_SERVICES:
            inspection = self._inspect_container(
                service,
                allow_absent=service in WORKER_SERVICES,
            )
            if inspection is None:
                services[service] = {
                    "service": service,
                    "container_id": "",
                    "owner": "absent",
                    "safe_source_revision": "",
                    "topology": {},
                    "runtime": {"lifecycle": "absent"},
                    "rollback_projection": {},
                    "identity_sha256": _canonical_sha256(
                        {"service": service, "lifecycle": "absent"}
                    ),
                }
            else:
                services[service] = self._container_identity(inspection, service)
        if services[API_SERVICE]["owner"] != "memorial":
            raise DeployError("memorial_api_owner_required")
        self.pre_state = {
            "services": services,
            "owners": {
                service: services[service]["owner"]
                for service in EXPECTED_RUNTIME_SERVICES
            },
        }
        if set(self.pre_state.get("services") or {}) == set(
            EXPECTED_RUNTIME_SERVICES
        ) and all(
            "owner" in self.pre_state["services"][service]
            for service in EXPECTED_RUNTIME_SERVICES
        ):
            self._refresh_pre_state_receipt()

    def _refresh_pre_state_receipt(self) -> None:
        services = self.pre_state["services"]
        self.pre_state["sha256"] = _canonical_sha256(
            {
                service: {
                    "owner": services[service]["owner"],
                    "identity_sha256": services[service]["identity_sha256"],
                }
                for service in EXPECTED_RUNTIME_SERVICES
            }
        )
        self.receipt["pre_state"] = {
            "sha256": self.pre_state["sha256"],
            "services": {},
        }
        for service in EXPECTED_RUNTIME_SERVICES:
            identity = services[service]
            runtime = identity["runtime"]
            if runtime["lifecycle"] == "absent":
                self.receipt["pre_state"]["services"][service] = {
                    "container_id": "",
                    "owner": "absent",
                    "lifecycle": "absent",
                    "identity_sha256": identity["identity_sha256"],
                }
                continue
            self.receipt["pre_state"]["services"][service] = {
                "container_id": identity["container_id"][:12],
                "owner": identity["owner"],
                "lifecycle": runtime["lifecycle"],
                "identity_sha256": identity["identity_sha256"],
                "image_id": runtime["image_id"],
                "image_reference": runtime["image_reference"],
                "environment_sha256": runtime["environment_sha256"],
                "process_sha256": runtime["process_sha256"],
                "mounts": runtime["mounts"],
                "security_sha256": runtime["security_sha256"],
                "topology_sha256": runtime["topology_sha256"],
                "compose_config_sha256": identity["topology"]["compose_config_sha256"],
                "rollback_projection_sha256": runtime["rollback_projection_sha256"],
                "restorable_contract_sha256": runtime["restorable_contract_sha256"],
            }

    def _bind_pre_state_network_request(
        self,
        service: str,
        rendered_service: Mapping[str, Any],
    ) -> dict[str, dict[str, Any]]:
        requested = self._rendered_network_endpoint_contract(rendered_service)
        prior = self.pre_state["services"][service]
        inspection = prior.get("_inspection")
        if not isinstance(inspection, Mapping):
            return requested
        rebound = self._container_identity(
            inspection,
            service,
            requested_network_endpoints=requested,
        )
        if (
            rebound["container_id"] != prior["container_id"]
            or rebound["owner"] != prior["owner"]
            or rebound["topology"] != prior["topology"]
        ):
            raise DeployError(f"pre_state_network_rebind_changed:{service}")
        self.pre_state["services"][service] = rebound
        return requested

    def _rollback_environment(self) -> dict[str, str]:
        return {
            key: value
            for key, value in self.env.items()
            if key
            in {
                "DOCKER_CONFIG",
                "DOCKER_CONTEXT",
                "DOCKER_HOST",
                "HOME",
                "LANG",
                "LC_ALL",
                "PATH",
                "TMPDIR",
                "USER",
                "XDG_RUNTIME_DIR",
            }
        }

    def _prepare_rollback_snapshot_directory(self) -> None:
        _ensure_private_directory(self.receipt_dir)
        if os.path.lexists(self.rollback_snapshot_dir):
            raise DeployError("rollback_snapshot_already_exists")
        os.mkdir(self.rollback_snapshot_dir, 0o700)
        metadata = self.rollback_snapshot_dir.lstat()
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o700
            or metadata.st_uid != os.geteuid()
        ):
            raise DeployError("rollback_snapshot_directory_untrusted")

    def _write_private_snapshot(self, path: Path, raw: bytes) -> str:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path, flags, 0o600)
        self.rollback_snapshot_paths.append(path)
        try:
            os.fchmod(descriptor, 0o600)
            written = 0
            while written < len(raw):
                written += os.write(descriptor, raw[written:])
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return hashlib.sha256(raw).hexdigest()

    @staticmethod
    def _topology_manifest_path(files: Sequence[str]) -> Path:
        if not files:
            raise DeployError("active_topology_compose_files_missing")
        paths = [Path(value).resolve() for value in files]
        parent = paths[0].parent
        if any(path.parent != parent for path in paths):
            raise DeployError("active_topology_compose_parent_mismatch")
        return parent / f".{paths[0].name}.topology.json"

    def _write_topology_manifest(
        self,
        *,
        files: Sequence[str],
        env_file: Path,
        working_dir: Path,
        services: Sequence[str],
        compose_config_sha256: Mapping[str, str],
        role: str,
    ) -> tuple[Path, str]:
        manifest_path = self._topology_manifest_path(files)
        compose_inputs = [
            {
                "name": Path(value).name,
                "sha256": _trusted_input_sha256(
                    Path(value),
                    allowed_uids={os.geteuid()},
                    reason="active_topology_compose_input",
                ),
            }
            for value in files
        ]
        env_sha256 = _trusted_input_sha256(
            env_file,
            allowed_uids={os.geteuid()},
            reason="active_topology_env_input",
        )
        payload = {
            "contract_name": ACTIVE_TOPOLOGY_CONTRACT,
            "version": 1,
            "deployment_id": self.deployment_id,
            "role": role,
            "working_dir_sha256": hashlib.sha256(
                str(working_dir.resolve()).encode()
            ).hexdigest(),
            "compose_inputs": compose_inputs,
            "env_input": {
                "name": env_file.name,
                "sha256": env_sha256,
            },
            "services": list(services),
            "compose_config_sha256": dict(compose_config_sha256),
        }
        raw = (json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n").encode(
            "utf-8"
        )
        manifest_sha256 = self._write_private_snapshot(manifest_path, raw)
        _fsync_directory(
            manifest_path.parent,
            reason="active_topology_manifest_directory",
        )
        return manifest_path, manifest_sha256

    def _load_active_topology_manifest(
        self,
        *,
        files: Sequence[str],
        working_dir: Path,
        service: str,
    ) -> dict[str, Any] | None:
        paths = [Path(value).resolve() for value in files]
        if not paths or any(path.parent != paths[0].parent for path in paths):
            return None
        try:
            paths[0].parent.relative_to(self.receipt_dir.resolve())
        except ValueError:
            return None
        parent_metadata = paths[0].parent.lstat()
        if (
            not stat.S_ISDIR(parent_metadata.st_mode)
            or parent_metadata.st_uid != os.geteuid()
            or stat.S_IMODE(parent_metadata.st_mode) != 0o700
        ):
            raise DeployError(f"active_topology_parent_untrusted:{service}")
        manifest_path = self._topology_manifest_path(files)
        if not manifest_path.is_file():
            raise DeployError(f"active_topology_manifest_missing:{service}")
        document = _read_trusted_json(
            manifest_path,
            expected_uid=os.geteuid(),
            expected_mode=0o600,
            maximum_bytes=MAX_EVIDENCE_BYTES,
            reason_prefix="active_topology_manifest",
        )
        payload = document.payload
        if set(payload) != {
            "contract_name",
            "version",
            "deployment_id",
            "role",
            "working_dir_sha256",
            "compose_inputs",
            "env_input",
            "services",
            "compose_config_sha256",
        }:
            raise DeployError(f"active_topology_manifest_invalid:{service}")
        compose_inputs = payload.get("compose_inputs")
        env_input = payload.get("env_input")
        services = payload.get("services")
        compose_config_sha256 = payload.get("compose_config_sha256")
        if (
            payload.get("contract_name") != ACTIVE_TOPOLOGY_CONTRACT
            or payload.get("version") != 1
            or not DEPLOYMENT_ID_RE.fullmatch(str(payload.get("deployment_id") or ""))
            or payload.get("role") not in {"forward", "rollback"}
            or payload.get("working_dir_sha256")
            != hashlib.sha256(str(working_dir.resolve()).encode()).hexdigest()
            or not isinstance(compose_inputs, list)
            or len(compose_inputs) != len(paths)
            or not isinstance(env_input, dict)
            or set(env_input) != {"name", "sha256"}
            or not isinstance(services, list)
            or service not in services
            or not isinstance(compose_config_sha256, dict)
            or set(compose_config_sha256) != set(services)
            or any(
                not isinstance(name, str) or not SHA256_RE.fullmatch(str(value))
                for name, value in compose_config_sha256.items()
            )
        ):
            raise DeployError(f"active_topology_manifest_invalid:{service}")
        for path, raw in zip(paths, compose_inputs, strict=True):
            if (
                not isinstance(raw, dict)
                or set(raw) != {"name", "sha256"}
                or raw.get("name") != path.name
                or not SHA256_RE.fullmatch(str(raw.get("sha256") or ""))
                or _trusted_input_sha256(
                    path,
                    allowed_uids={os.geteuid()},
                    reason="active_topology_compose_reentry",
                )
                != raw["sha256"]
            ):
                raise DeployError(f"active_topology_compose_changed:{service}")
        env_name = str(env_input.get("name") or "")
        if Path(env_name).name != env_name:
            raise DeployError(f"active_topology_env_invalid:{service}")
        env_path = paths[0].parent / env_name
        if (
            not SHA256_RE.fullmatch(str(env_input.get("sha256") or ""))
            or _trusted_input_sha256(
                env_path,
                allowed_uids={os.geteuid()},
                reason="active_topology_env_reentry",
            )
            != env_input["sha256"]
        ):
            raise DeployError(f"active_topology_env_changed:{service}")
        return {
            "path": manifest_path,
            "sha256": document.sha256,
            "env_file": env_path,
            "env_sha256": str(env_input["sha256"]),
            "role": str(payload["role"]),
            "compose_config_sha256": str(compose_config_sha256[service]),
        }

    def _snapshot_and_validate_rollback_inputs(self) -> None:
        self._prepare_rollback_snapshot_directory()
        partitions: dict[tuple[str, tuple[str, ...], str], list[str]] = {}
        absent_services: list[str] = []
        for service in WORKER_SERVICES:
            if (
                self.pre_state["services"][service]["runtime"].get(
                    "lifecycle", "running"
                )
                == "absent"
            ):
                absent_services.append(service)
                continue
            topology = self.pre_state["services"][service]["topology"]
            key = (
                topology["working_dir"],
                tuple(topology["compose_files"]),
                topology["env_file"],
            )
            partitions.setdefault(key, []).append(service)
        plan_receipts: dict[str, Any] = {}
        allowed_uids = {0, os.geteuid(), self.release_source_uid}
        for plan_index, (
            (working, files, source_env_file),
            services,
        ) in enumerate(partitions.items()):
            topology = self.pre_state["services"][services[0]]["topology"]
            copied_files: list[str] = []
            copied_input_sha256: list[str] = []
            for file_index, (raw_path, input_receipt) in enumerate(
                zip(files, topology["compose_inputs"], strict=True)
            ):
                destination = self.rollback_snapshot_dir / (
                    f"plan-{plan_index:02d}-compose-{file_index:02d}.yml"
                )
                self.rollback_snapshot_paths.append(destination)
                observed = _copy_trusted_input(
                    Path(raw_path),
                    destination,
                    expected_sha256=str(input_receipt["sha256"]),
                    allowed_uids=allowed_uids,
                    reason="rollback_compose_snapshot",
                )
                copied_files.append(str(destination))
                copied_input_sha256.append(observed)
            env_snapshot = self.rollback_snapshot_dir / f"plan-{plan_index:02d}.env"
            self.rollback_snapshot_paths.append(env_snapshot)
            observed_env = _copy_trusted_input(
                Path(source_env_file),
                env_snapshot,
                expected_sha256=str(topology["env_sha256"]),
                allowed_uids=allowed_uids,
                reason="rollback_env_snapshot",
            )
            compose_config_sha256: dict[str, str] = {}
            for service in services:
                hash_result = self._run(
                    self._compose_command(
                        Path(working),
                        copied_files,
                        "config",
                        "--hash",
                        service,
                        env_file=env_snapshot,
                    ),
                    cwd=Path(working),
                    env=self._rollback_environment(),
                )
                fields = hash_result.stdout.strip().split()
                if (
                    len(fields) != 2
                    or fields[0] != service
                    or not SHA256_RE.fullmatch(fields[1])
                ):
                    raise DeployError(f"rollback_compose_config_hash_invalid:{service}")
                observed_config_sha256 = fields[1]
                expected_config_sha256 = str(
                    self.pre_state["services"][service]["topology"].get(
                        "compose_config_sha256"
                    )
                    or ""
                )
                if observed_config_sha256 != expected_config_sha256:
                    raise DeployError(
                        f"rollback_compose_config_hash_mismatch:{service}"
                    )
                compose_config_sha256[service] = observed_config_sha256
            rendered_result = self._run(
                self._compose_command(
                    Path(working),
                    copied_files,
                    "config",
                    "--format",
                    "json",
                    env_file=env_snapshot,
                ),
                cwd=Path(working),
                env=self._rollback_environment(),
            )
            try:
                rendered = json.loads(rendered_result.stdout)
            except Exception as exc:
                raise DeployError("rollback_rendered_compose_invalid") from exc
            if not isinstance(rendered, dict):
                raise DeployError("rollback_rendered_compose_invalid")
            rendered_services = dict(rendered.get("services") or {})
            projection_sha256: dict[str, str] = {}
            restorable_contract_sha256: dict[str, str] = {}
            for service in services:
                payload = rendered_services.get(service)
                if not isinstance(payload, dict):
                    raise DeployError(f"rollback_rendered_service_missing:{service}")
                self._bind_pre_state_network_request(service, payload)
                projection = self._rendered_rollback_projection(payload)
                observed_projection = _canonical_sha256(projection)
                live_projection = self.pre_state["services"][service][
                    "rollback_projection"
                ]
                if not self._rendered_rollback_matches_live(
                    projection, live_projection
                ):
                    raise DeployError(f"rollback_projection_mismatch:{service}")
                projection_sha256[service] = observed_projection
                restorable_contract_sha256[service] = self.pre_state["services"][
                    service
                ]["runtime"]["restorable_contract_sha256"]
                payload.pop("build", None)
                payload.pop("depends_on", None)
                payload.pop("env_file", None)
                payload["pull_policy"] = "never"
            rendered_path = self.rollback_snapshot_dir / (
                f"plan-{plan_index:02d}.rendered.json"
            )
            rendered_raw = (
                json.dumps(rendered, ensure_ascii=False, sort_keys=True) + "\n"
            ).encode("utf-8")
            rendered_sha = self._write_private_snapshot(rendered_path, rendered_raw)
            round_trip_result = self._run(
                self._compose_command(
                    Path(working),
                    (str(rendered_path),),
                    "config",
                    "--format",
                    "json",
                    env_file=env_snapshot,
                ),
                cwd=Path(working),
                env=self._rollback_environment(),
            )
            try:
                round_trip = json.loads(round_trip_result.stdout)
            except Exception as exc:
                raise DeployError("rollback_rendered_round_trip_invalid") from exc
            if not isinstance(round_trip, dict):
                raise DeployError("rollback_rendered_round_trip_invalid")
            round_trip_services = dict(round_trip.get("services") or {})
            for service in services:
                payload = round_trip_services.get(service)
                if not isinstance(
                    payload, dict
                ) or not self._rendered_rollback_matches_live(
                    self._rendered_rollback_projection(payload),
                    self.pre_state["services"][service]["rollback_projection"],
                ):
                    raise DeployError(
                        f"rollback_rendered_round_trip_mismatch:{service}"
                    )
            round_trip_sha256 = _canonical_sha256(round_trip)
            topology_manifest_path, topology_manifest_sha256 = (
                self._write_topology_manifest(
                    files=(str(rendered_path),),
                    env_file=env_snapshot,
                    working_dir=Path(working),
                    services=services,
                    compose_config_sha256=compose_config_sha256,
                    role="rollback",
                )
            )
            plan_digest = _canonical_sha256(
                {
                    "services": services,
                    "compose_input_sha256": copied_input_sha256,
                    "env_sha256": observed_env,
                    "compose_config_sha256": compose_config_sha256,
                    "rendered_sha256": rendered_sha,
                    "round_trip_sha256": round_trip_sha256,
                    "projection_sha256": projection_sha256,
                    "restorable_contract_sha256": (restorable_contract_sha256),
                    "topology_manifest_sha256": topology_manifest_sha256,
                }
            )
            for service in services:
                self.rollback_plans[service] = {
                    "working_dir": working,
                    "rendered_file": str(rendered_path),
                    "rendered_sha256": rendered_sha,
                    "env_file": str(env_snapshot),
                    "env_sha256": observed_env,
                    "topology_manifest_file": str(topology_manifest_path),
                    "topology_manifest_sha256": topology_manifest_sha256,
                    "compose_config_sha256": dict(compose_config_sha256),
                    "sha256": plan_digest,
                }
            plan_receipts[f"plan-{plan_index:02d}"] = {
                "services": list(services),
                "sha256": plan_digest,
                "rendered_sha256": rendered_sha,
                "round_trip_sha256": round_trip_sha256,
                "compose_config_sha256": compose_config_sha256,
                "restorable_contract_sha256": (restorable_contract_sha256),
                "topology_manifest_sha256": topology_manifest_sha256,
            }
        self.rollback_plan_sha256 = _canonical_sha256(
            {
                "plans": plan_receipts,
                "absent_services": absent_services,
            }
        )
        self.receipt["rollback_plan"] = {
            "status": "private_snapshot_validated",
            "sha256": self.rollback_plan_sha256,
            "plans": plan_receipts,
            "absent_services": absent_services,
            "cleanup_required": True,
        }
        if set(self.pre_state.get("services") or {}) == set(
            EXPECTED_RUNTIME_SERVICES
        ) and all(
            "owner" in self.pre_state["services"][service]
            for service in EXPECTED_RUNTIME_SERVICES
        ):
            self._refresh_pre_state_receipt()
        _fsync_directory(
            self.rollback_snapshot_dir,
            reason="rollback_snapshot_directory",
        )

    def _cleanup_rollback_snapshots(self) -> None:
        failures: list[str] = []
        for path in reversed(self.rollback_snapshot_paths):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                failures.append(path.name)
        self.rollback_snapshot_paths.clear()
        self.production_overlay_snapshot_path = None
        if self.rollback_snapshot_dir.exists():
            try:
                self.rollback_snapshot_dir.rmdir()
            except OSError:
                failures.append(self.rollback_snapshot_dir.name)
        self.rollback_plans.clear()
        if failures:
            raise DeployError("rollback_snapshot_cleanup_failed")
        if "rollback_plan" in self.receipt:
            self.receipt["rollback_plan"]["cleanup_status"] = "pass"

    def _compose_command(
        self,
        root: Path,
        files: Sequence[str],
        *args: str,
        env_file: Path | None = None,
    ) -> list[str]:
        if not self.compose_bin:
            raise DeployError("docker_compose_unavailable")
        env_file = env_file or (root / ".env")
        if not env_file.is_file():
            raise DeployError("compose_env_file_missing")
        command = [
            *self.compose_bin,
            "--project-name",
            PROJECT_NAME,
            "--project-directory",
            str(root),
            "--env-file",
            str(env_file),
        ]
        for raw in files:
            path = Path(raw)
            if not path.is_absolute():
                path = root / path
            if not path.is_file():
                raise DeployError("compose_file_missing")
            command.extend(["-f", str(path.resolve())])
        return [*command, *args]

    def _render_target(
        self, files: Sequence[str], *, env_file: Path | None = None
    ) -> dict[str, Any]:
        result = self._run(
            self._compose_command(
                self.root,
                files,
                "config",
                "--format",
                "json",
                env_file=env_file,
            )
        )
        try:
            payload = json.loads(result.stdout)
        except Exception as exc:
            raise DeployError("target_compose_json_invalid") from exc
        if not isinstance(payload, dict):
            raise DeployError("target_compose_json_invalid")
        return dict(payload)

    def _validate_rendered_service(
        self,
        service_name: str,
        service: Mapping[str, Any],
    ) -> None:
        if set(service) != PAUSED_STAGE_SERVICE_KEYS[service_name]:
            raise DeployError(f"target_service_field_set_invalid:{service_name}")
        expected_environment = {
            "EA_SOURCE_REVISION": self.source_revision,
            "EA_DEPLOY_COMMIT_SHA": self.source_revision,
            **PAUSED_STAGE_SERVICE_ENV[service_name],
        }
        if _rendered_environment(service) != expected_environment:
            raise DeployError(
                f"target_runtime_side_effect_not_quiescent:{service_name}"
            )
        expected_labels = {
            "org.opencontainers.image.revision": self.source_revision,
            **PAUSED_STAGE_LABELS,
        }
        labels = service.get("labels")
        if (
            not isinstance(labels, dict)
            or {str(key): str(value) for key, value in labels.items()}
            != expected_labels
        ):
            raise DeployError(f"target_labels_invalid:{service_name}")
        exact = {
            "image": self.candidate_reference,
            "pull_policy": "never",
            "deploy": {"placement": {}, "replicas": 0, "resources": {}},
            "command": PAUSED_STAGE_IDLE_COMMAND,
            "entrypoint": ["/usr/local/bin/docker-entrypoint.sh"],
            "working_dir": "/app",
            "user": "10001:10001",
            "restart": "no",
            "cap_drop": ["ALL"],
            "read_only": True,
            "security_opt": ["no-new-privileges:true"],
            "tmpfs": ["/tmp", "/run"],
            "healthcheck": {"disable": True},
            "container_name": service_name,
            "networks": {"default": None},
            **PAUSED_STAGE_RESOURCES[service_name],
        }
        if any(service.get(field) != value for field, value in exact.items()):
            raise DeployError(f"target_paused_stage_contract_invalid:{service_name}")

    def _validate_target_compose(self) -> None:
        target_files = self._production_target_compose_files()
        baseline = self._render_target(PRODUCTION_BASE_COMPOSE_FILES)
        staged = self._render_target(target_files)
        baseline_services = dict(baseline.get("services") or {})
        staged_services = dict(staged.get("services") or {})
        if (
            set(baseline) != {"name", "networks", "services", "volumes"}
            or set(staged)
            != {
                "name",
                "networks",
                "services",
                "volumes",
                "x-audiobook-production-stage",
                "x-audiobook-production-stage-service",
            }
            or baseline.get("name") != "ea"
            or staged.get("name") != "ea"
            or set(baseline_services) != set(staged_services)
            or set(staged_services) != set(EXPECTED_RUNTIME_SERVICES)
            or any(
                baseline.get(field) != staged.get(field)
                for field in ("name", "networks", "volumes")
            )
        ):
            raise DeployError("target_compose_document_shape_invalid")
        if any(service not in staged_services for service in TARGET_SERVICES):
            raise DeployError("target_services_missing")
        if any(
            baseline_services[service] != staged_services[service]
            for service in baseline_services
            if service not in WORKER_SERVICES
        ):
            raise DeployError("target_preserved_service_changed")
        if not isinstance(
            baseline_services.get(API_SERVICE), dict
        ) or _canonical_sha256(baseline_services[API_SERVICE]) != _canonical_sha256(
            staged_services[API_SERVICE]
        ):
            raise DeployError("target_memorial_api_render_changed")
        api_service = dict(staged_services[API_SERVICE])
        self._bind_pre_state_network_request(API_SERVICE, api_service)
        api_projection = self._rendered_rollback_projection(api_service)
        if (
            _canonical_sha256(api_projection)
            != self.pre_state["services"][API_SERVICE]["runtime"][
                "rollback_projection_sha256"
            ]
        ):
            raise DeployError("target_memorial_api_not_exactly_preserved")
        for service in WORKER_SERVICES:
            worker = dict(staged_services[service])
            self._validate_rendered_service(service, worker)
            self.target_requested_network_endpoints[service] = (
                self._rendered_network_endpoint_contract(worker)
            )
            deploy_section = worker.get("deploy")
            if (
                not isinstance(deploy_section, dict)
                or type(deploy_section.get("replicas")) is not int
                or deploy_section["replicas"] != 0
            ):
                raise DeployError(f"target_paused_stage_replicas_invalid:{service}")
        if set(self.pre_state.get("services") or {}) == set(
            EXPECTED_RUNTIME_SERVICES
        ) and all(
            "owner" in self.pre_state["services"][service]
            for service in EXPECTED_RUNTIME_SERVICES
        ):
            self._refresh_pre_state_receipt()
        self.target_compose_sha256 = _canonical_sha256(staged)
        self.target_compose_files = tuple(target_files)
        projection = self.configuration_projection
        memorial = projection["memorial_baseline"]
        receipt_inventory = self.memorial_baseline_document.payload[
            "compose_source_inventory"
        ]
        if (
            self.production_overlay_sha256 != projection.get("overlay_working_sha256")
            or self.compose_source_inventory
            != projection.get("compose_source_inventory")
            or self.compose_source_inventory_sha256
            != projection.get("compose_source_inventory_sha256")
            or receipt_inventory != self.compose_source_inventory[:-1]
            or self.target_compose_sha256 != projection.get("rendered_compose_sha256")
            or _canonical_sha256(baseline) != memorial.get("rendered_compose_sha256")
            or _canonical_sha256(baseline_services[API_SERVICE])
            != memorial.get("ea_api_sha256")
        ):
            raise DeployError("target_compose_production_projection_mismatch")
        self.receipt["target_compose"] = {
            "sha256": self.target_compose_sha256,
            "baseline_files": [
                Path(value).name for value in PRODUCTION_BASE_COMPOSE_FILES
            ],
            "target_files": [Path(value).name for value in target_files],
        }
        self.receipt["runtime_side_effect_posture"] = {
            "status": "quiescent_configuration_validated",
            "queue_processing": "disabled",
            "provider_work": "disabled",
            "outbound_send": "disabled",
            "runtime_activation": "disabled",
            "replicas_zero": {service: 0 for service in WORKER_SERVICES},
        }

    def _config_hashes_for(
        self, files: Sequence[str], *, env_file: Path | None = None
    ) -> dict[str, str]:
        if not files:
            raise DeployError("target_compose_files_missing")
        observed: dict[str, str] = {}
        for service in WORKER_SERVICES:
            result = self._run(
                self._compose_command(
                    self.root,
                    files,
                    "config",
                    "--hash",
                    service,
                    env_file=env_file,
                )
            )
            fields = result.stdout.strip().split()
            if (
                len(fields) != 2
                or fields[0] != service
                or not SHA256_RE.fullmatch(fields[1])
            ):
                raise DeployError(f"target_compose_config_hash_invalid:{service}")
            observed[service] = fields[1]
        return observed

    def _capture_target_config_hashes(self) -> None:
        observed = self._config_hashes_for(self.target_compose_files)
        self.target_compose_config_sha256 = observed
        self.receipt["target_compose"]["config_sha256"] = dict(observed)

    def _prepare_forward_input_plan(self) -> None:
        env_path = self.root / ".env"
        self.forward_env_sha256 = _trusted_input_sha256(
            env_path,
            allowed_uids={0, os.geteuid(), self.release_source_uid},
            reason="forward_env_input",
        )
        plan = {
            "compose_inputs": [
                {
                    "name": Path(entry["path"]).name,
                    "sha256": entry["working_sha256"],
                }
                for entry in self.compose_source_inventory
            ],
            "env_sha256": self.forward_env_sha256,
            "rendered_compose_sha256": self.target_compose_sha256,
            "compose_config_sha256": dict(self.target_compose_config_sha256),
            "services": list(WORKER_SERVICES),
        }
        self.forward_input_plan_sha256 = _canonical_sha256(plan)
        self.receipt["forward_input_plan"] = {
            "status": "source_inputs_digest_bound",
            "sha256": self.forward_input_plan_sha256,
            "compose_inputs": list(plan["compose_inputs"]),
            "env_sha256": self.forward_env_sha256,
            "rendered_compose_sha256": self.target_compose_sha256,
            "compose_config_sha256": dict(self.target_compose_config_sha256),
        }

    def _capture_forward_topology_inputs(self) -> None:
        if not self.rollback_snapshot_dir.is_dir():
            raise DeployError("forward_snapshot_directory_missing")
        if self.forward_compose_files or self.forward_env_path is not None:
            raise DeployError("forward_snapshot_already_captured")
        allowed_uids = {0, os.geteuid(), self.release_source_uid}
        copied_files: list[str] = []
        copied_inputs: list[dict[str, str]] = []
        for relative, entry in zip(
            PRODUCTION_COMPOSE_SOURCE_PATHS,
            self.compose_source_inventory,
            strict=True,
        ):
            destination = self.rollback_snapshot_dir / relative.name
            self.rollback_snapshot_paths.append(destination)
            observed = _copy_trusted_input(
                self.root / relative,
                destination,
                expected_sha256=entry["working_sha256"],
                allowed_uids=allowed_uids,
                reason="forward_compose_snapshot",
            )
            copied_files.append(str(destination))
            copied_inputs.append({"name": destination.name, "sha256": observed})
        env_snapshot = self.rollback_snapshot_dir / "forward.env"
        self.rollback_snapshot_paths.append(env_snapshot)
        observed_env = _copy_trusted_input(
            self.root / ".env",
            env_snapshot,
            expected_sha256=self.forward_env_sha256,
            allowed_uids=allowed_uids,
            reason="forward_env_snapshot",
        )
        rendered = self._render_target(copied_files, env_file=env_snapshot)
        observed_rendered_sha256 = _canonical_sha256(rendered)
        observed_config_sha256 = self._config_hashes_for(
            copied_files, env_file=env_snapshot
        )
        actual_plan_sha256 = _canonical_sha256(
            {
                "compose_inputs": copied_inputs,
                "env_sha256": observed_env,
                "rendered_compose_sha256": observed_rendered_sha256,
                "compose_config_sha256": observed_config_sha256,
                "services": list(WORKER_SERVICES),
            }
        )
        if (
            actual_plan_sha256 != self.forward_input_plan_sha256
            or observed_rendered_sha256 != self.target_compose_sha256
            or observed_config_sha256 != self.target_compose_config_sha256
        ):
            raise DeployError("forward_snapshot_projection_mismatch")
        manifest_path, manifest_sha256 = self._write_topology_manifest(
            files=copied_files,
            env_file=env_snapshot,
            working_dir=self.root,
            services=WORKER_SERVICES,
            compose_config_sha256=self.target_compose_config_sha256,
            role="forward",
        )
        self.forward_compose_files = tuple(copied_files)
        self.forward_env_path = env_snapshot
        self.forward_topology_manifest_path = manifest_path
        self.forward_topology_manifest_sha256 = manifest_sha256
        self.receipt["forward_input_plan"] = {
            **dict(self.receipt["forward_input_plan"]),
            "status": "immutable_private_snapshot_validated",
            "topology_manifest_sha256": manifest_sha256,
        }
        _fsync_directory(
            self.rollback_snapshot_dir,
            reason="forward_snapshot_directory",
        )

    def _revalidate_forward_topology_inputs(self) -> None:
        if (
            not self.forward_compose_files
            or self.forward_env_path is None
            or self.forward_topology_manifest_path is None
            or not self.forward_topology_manifest_sha256
        ):
            raise DeployError("forward_snapshot_missing")
        topology = self._load_active_topology_manifest(
            files=self.forward_compose_files,
            working_dir=self.root,
            service=WORKER_SERVICES[0],
        )
        if (
            topology is None
            or topology["sha256"] != self.forward_topology_manifest_sha256
            or Path(topology["env_file"]) != self.forward_env_path
            or _canonical_sha256(
                self._render_target(
                    self.forward_compose_files,
                    env_file=self.forward_env_path,
                )
            )
            != self.target_compose_sha256
            or self._config_hashes_for(
                self.forward_compose_files,
                env_file=self.forward_env_path,
            )
            != self.target_compose_config_sha256
        ):
            raise DeployError("forward_snapshot_changed")

    def _activate_forward_topology_inputs(self) -> None:
        self._revalidate_forward_topology_inputs()
        for service in WORKER_SERVICES:
            current = self._topology(self._inspect_container(service), service)
            if (
                current["compose_files"]
                != [str(Path(value).resolve()) for value in self.forward_compose_files]
                or current["env_file"] != str(self.forward_env_path.resolve())
                or current["topology_manifest_sha256"]
                != self.forward_topology_manifest_sha256
                or current["compose_config_sha256"]
                != self.target_compose_config_sha256[service]
            ):
                raise DeployError(f"forward_active_topology_mismatch:{service}")
        self._revalidate_forward_topology_inputs()
        self.retain_active_topology_inputs = True
        self.active_topology_manifests["forward"] = (
            self.forward_topology_manifest_sha256
        )
        self.receipt["active_topology"] = {
            "status": "retained_live_input",
            "role": "forward",
            "manifest_sha256": self.forward_topology_manifest_sha256,
            "compose_input_count": len(self.forward_compose_files),
            "env_sha256": self.forward_env_sha256,
            "services": list(WORKER_SERVICES),
        }

    def _revalidate_target_configuration(self) -> None:
        expected_sha256 = self.target_compose_sha256
        expected_files = self.target_compose_files
        expected_config_sha256 = dict(self.target_compose_config_sha256)
        expected_forward_input_plan_sha256 = self.forward_input_plan_sha256
        expected_forward_env_sha256 = self.forward_env_sha256
        self._validate_target_compose()
        self._capture_target_config_hashes()
        self._prepare_forward_input_plan()
        if (
            self.target_compose_sha256 != expected_sha256
            or self.target_compose_files != expected_files
            or self.target_compose_config_sha256 != expected_config_sha256
            or self.forward_input_plan_sha256 != expected_forward_input_plan_sha256
            or self.forward_env_sha256 != expected_forward_env_sha256
        ):
            raise DeployError("target_compose_changed")

    def _revalidate_candidate_image(self) -> None:
        if self._inspect_image(self.candidate_reference) != self.candidate:
            raise DeployError("candidate_image_changed")

    def _capture_local_controls(self) -> Mapping[str, Any]:
        origin = str(
            self.env.get("EA_AUDIOBOOK_RUNTIME_LOCAL_API_ORIGIN")
            or "http://127.0.0.1:8090"
        ).rstrip("/")
        parsed = urllib.parse.urlsplit(origin)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise DeployError("local_control_origin_invalid")
        controls: dict[str, Any] = {}
        for label, path in (
            ("health", "/health"),
            ("memorial_html", "/memorials/manfred"),
            ("memorial_json", "/memorials/manfred.json"),
            ("openapi", "/openapi.json"),
        ):
            request = urllib.request.Request(f"{origin}{path}", method="GET")
            try:
                with urllib.request.urlopen(request, timeout=10) as response:
                    raw = response.read(MAX_HTTP_BYTES + 1)
                    status_code = int(getattr(response, "status", 200) or 200)
                    content_type = str(response.headers.get("Content-Type") or "")
            except (OSError, urllib.error.URLError) as exc:
                raise DeployError(f"local_control_probe_failed:{label}") from exc
            if status_code != 200 or len(raw) > MAX_HTTP_BYTES:
                raise DeployError(f"local_control_probe_invalid:{label}")
            controls[label] = {
                "body_sha256": hashlib.sha256(raw).hexdigest(),
                "content_type": content_type.split(";", 1)[0].lower(),
            }
            if label == "openapi":
                try:
                    document = json.loads(raw)
                except Exception as exc:
                    raise DeployError("local_openapi_invalid") from exc
                controls[label]["paths"] = sorted(dict(document.get("paths") or {}))
        return controls

    def _verify_local_controls(self, baseline: Mapping[str, Any]) -> None:
        current = dict(self._capture_local_controls())
        if (
            current["memorial_json"]["body_sha256"]
            != baseline["memorial_json"]["body_sha256"]
        ):
            raise DeployError("memorial_manifest_regression")
        if (
            current["memorial_html"]["body_sha256"]
            != baseline["memorial_html"]["body_sha256"]
        ):
            raise DeployError("memorial_surface_regression")
        missing = set(baseline["openapi"]["paths"]) - set(current["openapi"]["paths"])
        if missing:
            raise DeployError("openapi_path_regression")

    def _read_and_validate_state(self) -> TrustedDocument:
        document = _read_trusted_json(
            self.sentinel_path,
            expected_uid=self.sentinel_owner_uid,
            maximum_bytes=MAX_EVIDENCE_BYTES,
            reason_prefix="vexp_sentinel_state",
        )
        state = document.payload
        if (
            state.get("version") != EXPECTED_VEXP_VERSION
            or state.get("qualification_phase") != "qualified"
            or state.get("qualified_at") is None
            or type(state.get("epoch_started_ms")) is not int
        ):
            raise DeployError("vexp_sentinel_not_terminal")
        now = self._guard_now()
        qualified = _parse_time(state.get("qualified_at"), "vexp_qualified_at_invalid")
        epoch_started = _parse_time(
            state.get("epoch_started_at"), "vexp_epoch_started_at_invalid"
        )
        earliest = _parse_time(
            state.get("qualification_earliest_completion_at"),
            "vexp_earliest_completion_invalid",
        )
        updated = _parse_time(state.get("updated_at"), "vexp_updated_at_invalid")
        if epoch_started.microsecond % 1_000 != 0 or _datetime_epoch_ms(
            epoch_started
        ) != state.get("epoch_started_ms"):
            raise DeployError("vexp_sentinel_state_epoch_invalid")
        required_completion = max(
            MINIMUM_VEXP_QUALIFICATION_AT,
            epoch_started + MINIMUM_VEXP_SOAK,
            earliest,
        )
        if earliest < epoch_started + MINIMUM_VEXP_SOAK:
            raise DeployError("vexp_earliest_completion_invalid")
        if qualified < required_completion or qualified > now + MAX_CLOCK_SKEW:
            raise DeployError("vexp_qualification_not_elapsed")
        if updated > now + MAX_CLOCK_SKEW or now - updated > MAX_SENTINEL_AGE:
            raise DeployError("vexp_sentinel_state_stale")
        blockers = state.get("certification_blockers")
        if (
            state.get("current_resources_healthy") is not True
            or not isinstance(blockers, list)
            or blockers
        ):
            raise DeployError("vexp_sentinel_resources_not_healthy")
        return document

    def _load_authorities(self) -> None:
        if not all(
            (
                self.configuration_document,
                self.provenance_document,
                self.sbom_document,
                self.memorial_baseline_document,
                self.schema_v6_qualification,
                self.prior_preflight_receipt,
            )
        ):
            raise DeployError("paused_stage_authority_missing")
        owner_permit = _read_trusted_json(
            self.stage_owner_permit_path,
            expected_uid=self.root_authority_uid,
            expected_mode=0o644,
            maximum_bytes=MAX_AUTHORITY_BYTES,
            reason_prefix="stage_owner_permit",
        )
        self._validate_stage_owner_permit(
            owner_permit,
            self.configuration_projection,
            self.schema_v6_qualification,
        )
        self.stage_owner_permit_document = owner_permit
        self.receipt["authority"] = {
            "status": "paused_stage_authority_validated_not_consumed",
            "schema_v6_terminal_identity_sha256": (
                self.schema_v6_qualification.terminal_identity_sha256
            ),
            "schema_v6_permit_sha256": (self.schema_v6_qualification.permit_sha256),
            "stage_owner_permit_sha256": (owner_permit.sha256),
            "production_preflight_sha256": self.configuration_document.sha256,
            "stage_owner_permit_consumed": False,
        }
        with self._issuer_authority_lease("preflight_authority_validation"):
            pass

    def _consume_stage_owner_permit(self) -> None:
        if self.stage_owner_permit_document is None:
            raise DeployError("stage_owner_permit_not_loaded")
        if (
            self.stage_owner_permit_consumed
            or ".consumed." in self.active_stage_owner_permit_path.name
        ):
            raise DeployError("stage_owner_permit_already_consumed")
        source = self.stage_owner_permit_path
        nonce = str(self.stage_owner_permit_document.payload.get("nonce") or "")
        if not SHA256_RE.fullmatch(nonce):
            raise DeployError("stage_owner_permit_identity_invalid")
        consumed = source.with_name(
            f"{source.name}.consumed.{self.deployment_id}.{nonce}"
        )
        linked = False
        source_unlinked = False
        parent_descriptor = -1
        try:
            parent_descriptor = _open_absolute_nofollow(
                source.parent,
                flags=os.O_RDONLY | os.O_DIRECTORY,
                reason="stage_owner_permit_parent",
                require_root_parents=self.root_authority_uid == 0,
            )
            parent_metadata = os.fstat(parent_descriptor)
            if (
                not stat.S_ISDIR(parent_metadata.st_mode)
                or parent_metadata.st_uid != self.root_authority_uid
                or stat.S_IMODE(parent_metadata.st_mode) & 0o022
            ):
                raise DeployError("stage_owner_permit_parent_untrusted")
            os.link(
                source.name,
                consumed.name,
                src_dir_fd=parent_descriptor,
                dst_dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
            linked = True
            os.unlink(source.name, dir_fd=parent_descriptor)
            source_unlinked = True
            os.fsync(parent_descriptor)
        except DeployError:
            if linked and not source_unlinked and parent_descriptor >= 0:
                try:
                    os.unlink(consumed.name, dir_fd=parent_descriptor)
                except OSError:
                    pass
            raise
        except OSError as exc:
            if linked and not source_unlinked and parent_descriptor >= 0:
                try:
                    os.unlink(consumed.name, dir_fd=parent_descriptor)
                except OSError:
                    pass
            raise DeployError("stage_owner_permit_consumption_failed") from exc
        finally:
            if parent_descriptor >= 0:
                os.close(parent_descriptor)
        self.consumed_stage_owner_permit_path = consumed
        current = _read_trusted_json(
            consumed,
            expected_uid=self.root_authority_uid,
            expected_mode=0o644,
            maximum_bytes=MAX_AUTHORITY_BYTES,
            reason_prefix="consumed_stage_owner_permit",
        )
        if current.sha256 != self.stage_owner_permit_document.sha256:
            raise DeployError("stage_owner_permit_changed_during_consumption")
        self.stage_owner_permit_document = current
        self.stage_owner_permit_consumed = True
        self.receipt["authority"]["status"] = "paused_stage_authority_consumed"
        self.receipt["authority"]["stage_owner_permit_consumed"] = True
        self._write_receipt()

    def _revalidate_authority(self, boundary: str) -> None:
        if not all(
            (
                self.configuration_document,
                self.provenance_document,
                self.sbom_document,
                self.memorial_baseline_document,
                self.schema_v6_qualification,
                self.stage_owner_permit_document,
            )
        ):
            raise DeployError("deployment_authority_missing")
        qualification = self._load_schema_v6_qualification()
        original = self.schema_v6_qualification
        if any(
            getattr(qualification, field) != getattr(original, field)
            for field in (
                "terminal_identity_sha256",
                "qualified_at",
                "permit_contract_name",
                "permit_sha256",
                "permit_expires_at",
                "mutation_authority_transferred",
            )
        ):
            raise DeployError("schema_v6_qualification_changed")
        configuration = _document_unchanged(
            self.configuration_document,
            expected_uid=self.evidence_owner_uid,
            maximum_bytes=MAX_EVIDENCE_BYTES,
            reason="production_preflight",
        )
        _document_unchanged(
            self.provenance_document,
            expected_uid=self.evidence_owner_uid,
            maximum_bytes=MAX_EVIDENCE_BYTES,
            reason="candidate_provenance_receipt",
        )
        _document_unchanged(
            self.sbom_document,
            expected_uid=self.evidence_owner_uid,
            maximum_bytes=MAX_EVIDENCE_BYTES,
            reason="candidate_sbom_receipt",
        )
        _document_unchanged(
            self.memorial_baseline_document,
            expected_uid=self.root_authority_uid,
            expected_mode=0o644,
            maximum_bytes=MAX_EVIDENCE_BYTES,
            reason="memorial_baseline_receipt",
        )
        owner_permit = _document_unchanged(
            self.stage_owner_permit_document,
            expected_uid=self.root_authority_uid,
            expected_mode=0o644,
            maximum_bytes=MAX_AUTHORITY_BYTES,
            reason="stage_owner_permit",
        )
        current_projection = self._validate_production_projection(
            configuration.payload,
            qualification,
        )
        self._validate_stage_owner_permit(
            owner_permit, current_projection, qualification
        )
        if _canonical_sha256(current_projection) != _canonical_sha256(
            self.configuration_projection
        ):
            raise DeployError("production_projection_changed")
        previous_inventory = list(self.compose_source_inventory)
        previous_inventory_sha256 = self.compose_source_inventory_sha256
        self._capture_compose_source_inventory()
        if (
            self.compose_source_inventory != previous_inventory
            or self.compose_source_inventory_sha256 != previous_inventory_sha256
        ):
            raise DeployError("compose_source_inventory_changed")
        self._production_overlay()
        self.receipt["checks"] = [
            *list(self.receipt.get("checks") or []),
            {"name": "authority_revalidation", "status": "pass", "boundary": boundary},
        ]

    def _revalidate_pre_state(
        self, services: Sequence[str] = EXPECTED_RUNTIME_SERVICES
    ) -> None:
        for service in services:
            prior = self.pre_state["services"][service]
            prior_lifecycle = prior["runtime"].get("lifecycle", "running")
            inspection = self._inspect_container(
                service,
                allow_absent=prior_lifecycle == "absent",
            )
            if inspection is None:
                if prior_lifecycle != "absent":
                    raise DeployError(f"pre_state_changed:{service}")
                continue
            requested_network_endpoints = prior.get("requested_network_endpoints")
            current = (
                self._container_identity(
                    inspection,
                    service,
                    requested_network_endpoints=requested_network_endpoints,
                )
                if requested_network_endpoints is not None
                else self._container_identity(inspection, service)
            )
            if (
                current["container_id"] != prior["container_id"]
                or current["identity_sha256"] != prior["identity_sha256"]
            ):
                raise DeployError(f"pre_state_changed:{service}")

    def _protect_previous_images(
        self, services: Sequence[str] = WORKER_SERVICES
    ) -> dict[str, str]:
        if self.stage_owner_permit_document is None:
            raise DeployError("stage_owner_permit_not_loaded")
        nonce = str(self.stage_owner_permit_document.payload.get("nonce") or "")
        if not SHA256_RE.fullmatch(nonce):
            raise DeployError("stage_owner_permit_identity_invalid")
        for service in services:
            if (
                self.pre_state["services"][service]["runtime"].get(
                    "lifecycle", "running"
                )
                == "absent"
            ):
                continue
            image_id = self.pre_state["services"][service]["runtime"]["image_id"]
            if image_id in self.protected_prior_images:
                continue
            tag = (
                "ea-runtime:audiobook-rollback-"
                f"{self.deployment_id[:32]}-{nonce[:12]}-{image_id[-12:]}"
            )
            existing = self._run(["docker", "image", "inspect", tag], check=False)
            if existing.returncode == 0:
                raise DeployError("rollback_image_protection_tag_exists")
            if existing.returncode != 1:
                raise DeployError("rollback_image_protection_tag_probe_failed")
            self._run(["docker", "image", "tag", image_id, tag])
            self.protected_prior_images[image_id] = tag
            self.receipt["protected_prior_images"] = dict(self.protected_prior_images)
            self._write_receipt()
            inspected = self._run(["docker", "image", "inspect", tag])
            try:
                rows = json.loads(inspected.stdout)
            except Exception as exc:
                raise DeployError("rollback_image_protection_mismatch") from exc
            if (
                not isinstance(rows, list)
                or len(rows) != 1
                or not isinstance(rows[0], dict)
                or str(rows[0].get("Id") or "") != image_id
            ):
                raise DeployError("rollback_image_protection_mismatch")
        return dict(self.protected_prior_images)

    def _remove_protected_image_tags(self) -> None:
        failures: list[str] = []
        for image_id, tag in reversed(tuple(self.protected_prior_images.items())):
            try:
                inspected = self._run(["docker", "image", "inspect", tag])
                rows = json.loads(inspected.stdout)
                if (
                    not isinstance(rows, list)
                    or len(rows) != 1
                    or not isinstance(rows[0], dict)
                    or str(rows[0].get("Id") or "") != image_id
                ):
                    raise DeployError("protected_image_tag_identity_mismatch")
                self._run(["docker", "image", "rm", tag])
                self.protected_prior_images.pop(image_id, None)
            except Exception:
                failures.append(image_id)
        self.receipt["protected_prior_images"] = dict(self.protected_prior_images)
        if failures:
            self.receipt["protected_image_cleanup"] = {
                "status": "fail",
                "image_ids": failures,
            }
            self._write_receipt()
            raise DeployError("protected_image_tag_cleanup_failed")
        self.receipt["protected_image_cleanup"] = {"status": "pass"}
        self._write_receipt()

    def _target_create_paused(
        self,
        files: Sequence[str],
        services: Sequence[str],
        *,
        env_file: Path,
    ) -> None:
        if tuple(services) != WORKER_SERVICES:
            raise DeployError("paused_stage_service_scope_invalid")
        scale: list[str] = []
        for service in services:
            scale.extend(("--scale", f"{service}=1"))
        self._run(
            self._compose_command(
                self.root,
                files,
                "create",
                "--no-deps",
                "--pull",
                "never",
                "--no-build",
                "--force-recreate",
                *scale,
                *services,
                env_file=env_file,
            )
        )

    def _paused_worker_contract(
        self,
        inspection: Mapping[str, Any],
        service: str,
        *,
        expected_files: Sequence[str] | None,
        requested_network_endpoints: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if service not in WORKER_SERVICES:
            raise DeployError(f"paused_stage_service_scope_invalid:{service}")
        config = dict(inspection.get("Config") or {})
        host = dict(inspection.get("HostConfig") or {})
        state = dict(inspection.get("State") or {})
        labels = dict(config.get("Labels") or {})
        if (
            bool(state.get("Running"))
            or bool(state.get("Restarting"))
            or bool(state.get("Paused"))
            or bool(state.get("Dead"))
            or str(state.get("Status") or "") not in {"created", "exited", "stopped"}
        ):
            raise DeployError(f"paused_stage_not_inert:{service}")
        observed_config_sha256 = str(labels.get("com.docker.compose.config-hash") or "")
        expected_config_sha256 = self.target_compose_config_sha256.get(service)
        if (
            str(inspection.get("Image") or "") != self.candidate.get("image_id")
            or config.get("Image") != self.candidate_reference
            or labels.get("com.docker.compose.project") != PROJECT_NAME
            or labels.get("com.docker.compose.service") != service
            or not SHA256_RE.fullmatch(observed_config_sha256)
            or (
                expected_config_sha256 is not None
                and observed_config_sha256 != expected_config_sha256
            )
        ):
            raise DeployError(f"paused_stage_identity_mismatch:{service}")
        topology = self._topology(inspection, service)
        if topology["working_dir"] != str(self.root):
            raise DeployError(f"paused_stage_topology_mismatch:{service}")
        if expected_files is None:
            if not SHA256_RE.fullmatch(topology["topology_manifest_sha256"]):
                raise DeployError(f"paused_stage_topology_mismatch:{service}")
        elif topology["compose_files"] != [
            str(
                (self.root / raw).resolve()
                if not Path(raw).is_absolute()
                else Path(raw).resolve()
            )
            for raw in expected_files
        ]:
            raise DeployError(f"paused_stage_topology_mismatch:{service}")
        environment = _environment_map(
            [str(item) for item in list(config.get("Env") or [])]
        )
        expected_environment = {
            "EA_SOURCE_REVISION": self.source_revision,
            "EA_DEPLOY_COMMIT_SHA": self.source_revision,
            **PAUSED_STAGE_SERVICE_ENV[service],
        }
        expected_labels = {
            "org.opencontainers.image.revision": self.source_revision,
            **PAUSED_STAGE_LABELS,
        }
        if any(
            environment.get(key) != value for key, value in expected_environment.items()
        ) or any(
            str(labels.get(key) or "") != value
            for key, value in expected_labels.items()
        ):
            raise DeployError(f"paused_stage_side_effect_posture_invalid:{service}")
        expected_resources = PAUSED_STAGE_RESOURCES[service]
        expected_pids = expected_resources.get("pids_limit")
        observed_pids = host.get("PidsLimit")
        if (
            config.get("Cmd") != PAUSED_STAGE_IDLE_COMMAND
            or config.get("Entrypoint") != ["/usr/local/bin/docker-entrypoint.sh"]
            or config.get("WorkingDir") != "/app"
            or config.get("User") != "10001:10001"
            or dict(config.get("Healthcheck") or {}).get("Test") != ["NONE"]
            or not bool(host.get("ReadonlyRootfs"))
            or bool(host.get("Privileged"))
            or sorted(str(item) for item in list(host.get("CapAdd") or [])) != []
            or sorted(str(item) for item in list(host.get("CapDrop") or [])) != ["ALL"]
            or sorted(str(item) for item in list(host.get("SecurityOpt") or []))
            != ["no-new-privileges:true"]
            or self._restart_name(host.get("RestartPolicy")) != ""
            or self._tmpfs_projection(host.get("Tmpfs")) != ["/run", "/tmp"]
            or int(host.get("CpuShares") or 0) != int(expected_resources["cpu_shares"])
            or int(host.get("NanoCpus") or 0)
            != int(float(expected_resources["cpus"]) * 1_000_000_000)
            or (expected_pids is not None and observed_pids != expected_pids)
            or (expected_pids is None and observed_pids not in {None, 0, -1})
            or _mounts_from_inspection(inspection)
            or list(host.get("Binds") or [])
            or bool(host.get("PublishAllPorts"))
            or bool(host.get("PortBindings"))
        ):
            raise DeployError(f"paused_stage_runtime_contract_invalid:{service}")
        return {
            "identity_sha256": _canonical_sha256(
                self._inspection_restorable_contract(
                    inspection, requested_network_endpoints
                )
            ),
            "topology": topology,
            "compose_config_sha256": observed_config_sha256,
        }

    def _verify_paused_stage(
        self, services: Sequence[str], files: Sequence[str]
    ) -> None:
        if tuple(services) != WORKER_SERVICES:
            raise DeployError("paused_stage_service_scope_invalid")
        expected_files = [
            str(
                (self.root / raw).resolve()
                if not Path(raw).is_absolute()
                else Path(raw).resolve()
            )
            for raw in files
        ]
        identities: dict[str, str] = {}
        receipt_services: dict[str, dict[str, str]] = {}
        for service in services:
            inspection = self._inspect_container(service)
            config = dict(inspection.get("Config") or {})
            host = dict(inspection.get("HostConfig") or {})
            state = dict(inspection.get("State") or {})
            labels = dict(config.get("Labels") or {})
            if (
                bool(state.get("Running"))
                or bool(state.get("Restarting"))
                or bool(state.get("Paused"))
                or bool(state.get("Dead"))
                or str(state.get("Status") or "") != "created"
            ):
                raise DeployError(f"paused_stage_not_inert:{service}")
            if (
                str(inspection.get("Image") or "") != self.candidate["image_id"]
                or config.get("Image") != self.candidate_reference
                or labels.get("com.docker.compose.project") != PROJECT_NAME
                or labels.get("com.docker.compose.service") != service
                or labels.get("com.docker.compose.config-hash")
                != self.target_compose_config_sha256.get(service)
            ):
                raise DeployError(f"paused_stage_identity_mismatch:{service}")
            topology = self._topology(inspection, service)
            if (
                topology["working_dir"] != str(self.root)
                or topology["compose_files"] != expected_files
            ):
                raise DeployError(f"paused_stage_topology_mismatch:{service}")
            environment = _environment_map(
                [str(item) for item in list(config.get("Env") or [])]
            )
            expected_environment = {
                "EA_SOURCE_REVISION": self.source_revision,
                "EA_DEPLOY_COMMIT_SHA": self.source_revision,
                **PAUSED_STAGE_SERVICE_ENV[service],
            }
            expected_labels = {
                "org.opencontainers.image.revision": self.source_revision,
                **PAUSED_STAGE_LABELS,
            }
            if any(
                environment.get(key) != value
                for key, value in expected_environment.items()
            ) or any(
                str(labels.get(key) or "") != value
                for key, value in expected_labels.items()
            ):
                raise DeployError(f"paused_stage_side_effect_posture_invalid:{service}")
            expected_resources = PAUSED_STAGE_RESOURCES[service]
            expected_pids = expected_resources.get("pids_limit")
            observed_pids = host.get("PidsLimit")
            if (
                config.get("Cmd") != PAUSED_STAGE_IDLE_COMMAND
                or config.get("Entrypoint") != ["/usr/local/bin/docker-entrypoint.sh"]
                or config.get("WorkingDir") != "/app"
                or config.get("User") != "10001:10001"
                or dict(config.get("Healthcheck") or {}).get("Test") != ["NONE"]
                or not bool(host.get("ReadonlyRootfs"))
                or bool(host.get("Privileged"))
                or sorted(str(item) for item in list(host.get("CapAdd") or [])) != []
                or sorted(str(item) for item in list(host.get("CapDrop") or []))
                != ["ALL"]
                or sorted(str(item) for item in list(host.get("SecurityOpt") or []))
                != ["no-new-privileges:true"]
                or self._restart_name(host.get("RestartPolicy")) != ""
                or self._tmpfs_projection(host.get("Tmpfs")) != ["/run", "/tmp"]
                or int(host.get("CpuShares") or 0)
                != int(expected_resources["cpu_shares"])
                or int(host.get("NanoCpus") or 0)
                != int(float(expected_resources["cpus"]) * 1_000_000_000)
                or (expected_pids is not None and observed_pids != expected_pids)
                or (expected_pids is None and observed_pids not in {None, 0, -1})
                or _mounts_from_inspection(inspection)
                or list(host.get("Binds") or [])
                or bool(host.get("PublishAllPorts"))
                or bool(host.get("PortBindings"))
            ):
                raise DeployError(f"paused_stage_runtime_contract_invalid:{service}")
            staged_identity = _canonical_sha256(
                self._inspection_restorable_contract(
                    inspection,
                    self.target_requested_network_endpoints.get(service),
                )
            )
            identities[service] = staged_identity
            receipt_services[service] = {
                "container_id": str(inspection.get("Id") or "")[:12],
                "identity_sha256": staged_identity,
                "compose_config_sha256": self.target_compose_config_sha256[service],
            }
        self.staged_worker_identities = identities
        self.receipt["paused_stage"] = {
            "status": "created_not_started",
            "runtime_activation_authority": False,
            "services": receipt_services,
        }

    def _container_ready(self, service: str) -> bool:
        inspection = self._inspect_container(service)
        state = dict(inspection.get("State") or {})
        if not bool(state.get("Running")) or bool(state.get("Restarting")):
            return False
        health = str(dict(state.get("Health") or {}).get("Status") or "")
        return not health or health == "healthy"

    def _wait_ready(self, services: Sequence[str]) -> None:
        deadline = self.monotonic() + self.wait_seconds
        while True:
            if all(self._container_ready(service) for service in services):
                return
            if self.monotonic() >= deadline:
                raise DeployError("target_services_not_ready")
            self.sleep(0.25)

    def _verify_forward(self, services: Sequence[str], files: Sequence[str]) -> None:
        expected_files = [str((self.root / raw).resolve()) for raw in files]
        for service in services:
            inspection = self._inspect_container(service)
            config = dict(inspection.get("Config") or {})
            labels = dict(config.get("Labels") or {})
            if (
                str(inspection.get("Image") or "") != self.candidate["image_id"]
                or config.get("Image") != self.candidate_reference
                or labels.get("com.docker.compose.project") != PROJECT_NAME
                or labels.get("com.docker.compose.service") != service
            ):
                raise DeployError(f"forward_identity_mismatch:{service}")
            topology = self._topology(inspection, service)
            if (
                topology["working_dir"] != str(self.root)
                or topology["compose_files"] != expected_files
            ):
                raise DeployError(f"forward_topology_mismatch:{service}")
            env = _environment_map(list(config.get("Env") or []))
            expected_environment = {
                "EA_SOURCE_REVISION": self.source_revision,
                "EA_DEPLOY_COMMIT_SHA": self.source_revision,
                **PAUSED_STAGE_SERVICE_ENV[service],
            }
            if any(
                env.get(key) != value for key, value in expected_environment.items()
            ):
                raise DeployError(f"forward_source_revision_mismatch:{service}")
            mounts = _mounts_from_inspection(inspection)
            if any(row["type"] in {"bind", "volume"} for row in mounts):
                raise DeployError(f"forward_persistent_mount_present:{service}")

    def _retag_prior_reference(self, service: str) -> None:
        runtime = self.pre_state["services"][service]["runtime"]
        image_id = str(runtime["image_id"])
        image_reference = str(runtime["image_reference"])
        protected_tag = self.protected_prior_images.get(image_id)
        if not protected_tag:
            raise DeployError(f"rollback_protected_image_missing:{service}")
        protected = self._run(["docker", "image", "inspect", protected_tag])
        try:
            protected_rows = json.loads(protected.stdout)
        except Exception as exc:
            raise DeployError(f"rollback_protected_image_invalid:{service}") from exc
        if (
            not isinstance(protected_rows, list)
            or len(protected_rows) != 1
            or not isinstance(protected_rows[0], dict)
            or str(protected_rows[0].get("Id") or "") != image_id
        ):
            raise DeployError(f"rollback_protected_image_invalid:{service}")
        if not DIGEST_IMAGE_RE.fullmatch(image_reference):
            self._run(["docker", "image", "tag", image_id, image_reference])
        restored = self._run(["docker", "image", "inspect", image_reference])
        try:
            restored_rows = json.loads(restored.stdout)
        except Exception as exc:
            raise DeployError(f"rollback_image_reference_invalid:{service}") from exc
        if (
            not isinstance(restored_rows, list)
            or len(restored_rows) != 1
            or not isinstance(restored_rows[0], dict)
            or str(restored_rows[0].get("Id") or "") != image_id
        ):
            raise DeployError(f"rollback_image_reference_invalid:{service}")

    def _verify_rollback_active_topology(
        self,
        *,
        service: str,
        plan: Mapping[str, Any],
        current: Mapping[str, Any],
    ) -> None:
        rendered_file = Path(str(plan["rendered_file"])).resolve()
        env_file = Path(str(plan["env_file"])).resolve()
        expected_manifest_sha256 = str(plan.get("topology_manifest_sha256") or "")
        topology = dict(current.get("topology") or {})
        if (
            topology.get("compose_files") != [str(rendered_file)]
            or topology.get("env_file") != str(env_file)
            or topology.get("topology_manifest_sha256") != expected_manifest_sha256
            or topology.get("compose_config_sha256")
            != dict(plan.get("compose_config_sha256") or {}).get(service)
        ):
            raise DeployError(f"rollback_active_topology_mismatch:{service}")
        manifest = self._load_active_topology_manifest(
            files=(str(rendered_file),),
            working_dir=Path(str(plan["working_dir"])),
            service=service,
        )
        if (
            manifest is None
            or manifest["sha256"] != expected_manifest_sha256
            or Path(manifest["env_file"]) != env_file
        ):
            raise DeployError(f"rollback_active_topology_mismatch:{service}")
        hash_result = self._run(
            self._compose_command(
                Path(str(plan["working_dir"])),
                (str(rendered_file),),
                "config",
                "--hash",
                service,
                env_file=env_file,
            ),
            cwd=Path(str(plan["working_dir"])),
            env=self._rollback_environment(),
        )
        fields = hash_result.stdout.strip().split()
        if (
            len(fields) != 2
            or fields[0] != service
            or fields[1] != topology["compose_config_sha256"]
        ):
            raise DeployError(f"rollback_topology_reentry_failed:{service}")
        self.active_topology_manifests[f"rollback:{expected_manifest_sha256}"] = (
            expected_manifest_sha256
        )

    def _restore_absent_worker(self, service: str) -> None:
        inspection = self._inspect_container(service, allow_absent=True)
        if inspection is None:
            return
        config = dict(inspection.get("Config") or {})
        labels = dict(config.get("Labels") or {})
        if (
            service not in WORKER_SERVICES
            or labels.get("com.docker.compose.project") != PROJECT_NAME
            or labels.get("com.docker.compose.service") != service
            or str(inspection.get("Image") or "") != self.candidate["image_id"]
            or config.get("Image") != self.candidate_reference
        ):
            raise DeployError(f"rollback_absent_worker_identity_mismatch:{service}")
        self._run(["docker", "rm", "--force", service])
        if self._inspect_container(service, allow_absent=True) is not None:
            raise DeployError(f"rollback_absent_worker_still_present:{service}")

    def _rollback_services(self, services: Sequence[str]) -> None:
        failures: list[str] = []
        restored_services: list[str] = []
        for service in reversed(tuple(services)):
            prior_lifecycle = self.pre_state["services"][service]["runtime"].get(
                "lifecycle", "running"
            )
            if prior_lifecycle == "absent":
                try:
                    self._restore_absent_worker(service)
                except Exception:
                    failures.append(f"rollback_remove_absent_failed:{service}")
                continue
            plan = self.rollback_plans.get(service)
            if not isinstance(plan, dict):
                failures.append(f"rollback_plan_missing:{service}")
                continue
            try:
                working = Path(str(plan["working_dir"]))
                rendered_file = str(plan["rendered_file"])
                env_file = Path(str(plan["env_file"]))
                topology_manifest_file = Path(str(plan["topology_manifest_file"]))
                expected_rendered_sha256 = str(plan.get("rendered_sha256") or "")
                expected_env_sha256 = str(plan.get("env_sha256") or "")
                expected_manifest_sha256 = str(
                    plan.get("topology_manifest_sha256") or ""
                )
                if (
                    not SHA256_RE.fullmatch(expected_rendered_sha256)
                    or not SHA256_RE.fullmatch(expected_env_sha256)
                    or not SHA256_RE.fullmatch(expected_manifest_sha256)
                    or _trusted_input_sha256(
                        Path(rendered_file),
                        allowed_uids={os.geteuid()},
                        reason="rollback_rendered_snapshot",
                    )
                    != expected_rendered_sha256
                    or _trusted_input_sha256(
                        env_file,
                        allowed_uids={os.geteuid()},
                        reason="rollback_env_snapshot",
                    )
                    != expected_env_sha256
                    or _trusted_input_sha256(
                        topology_manifest_file,
                        allowed_uids={os.geteuid()},
                        reason="rollback_topology_manifest",
                    )
                    != expected_manifest_sha256
                ):
                    raise DeployError(f"rollback_private_snapshot_changed:{service}")
            except Exception:
                failures.append(f"rollback_snapshot_invalid:{service}")
                continue
            try:
                self._retag_prior_reference(service)
            except Exception:
                failures.append(f"rollback_retag_failed:{service}")
                continue
            try:
                compose_action = (
                    ("up", "-d") if prior_lifecycle == "running" else ("create",)
                )
                self._run(
                    self._compose_command(
                        working,
                        (rendered_file,),
                        *compose_action,
                        "--pull",
                        "never",
                        "--no-build",
                        "--no-deps",
                        "--force-recreate",
                        service,
                        env_file=env_file,
                    ),
                    cwd=working,
                    env=self._rollback_environment(),
                )
                if prior_lifecycle == "running":
                    self._wait_ready((service,))
                requested_network_endpoints = self.pre_state["services"][service].get(
                    "requested_network_endpoints"
                )
                inspection = self._inspect_container(service)
                current = (
                    self._container_identity(
                        inspection,
                        service,
                        requested_network_endpoints=requested_network_endpoints,
                    )
                    if requested_network_endpoints is not None
                    else self._container_identity(inspection, service)
                )
                if (
                    current["runtime"]["restorable_contract_sha256"]
                    != self.pre_state["services"][service]["runtime"][
                        "restorable_contract_sha256"
                    ]
                    or current["runtime"].get("lifecycle", "running") != prior_lifecycle
                ):
                    raise DeployError(f"rollback_identity_mismatch:{service}")
                self._verify_rollback_active_topology(
                    service=service,
                    plan=plan,
                    current=current,
                )
                restored_services.append(service)
            except Exception:
                failures.append(f"rollback_recreate_failed:{service}")
        if failures:
            self.receipt["rollback_service_failures"] = failures
            raise DeployError("rollback_service_recovery_incomplete")
        if restored_services:
            self.retain_active_topology_inputs = True
            self.receipt["active_topology"] = {
                "status": "retained_live_input",
                "role": "rollback",
                "manifest_sha256": sorted(set(self.active_topology_manifests.values())),
                "services": sorted(restored_services),
            }

    def _execute_paused_stage_transaction(self) -> None:
        if (
            self.stage_owner_permit_document is None
            or not self.target_compose_files
            or set(self.target_compose_config_sha256) != set(WORKER_SERVICES)
            or not SHA256_RE.fullmatch(self.forward_input_plan_sha256)
        ):
            raise DeployError("paused_stage_execution_precondition_missing")
        mutation_started = False
        with self._issuer_file_locks():
            started = self._monotonic_now()
            self._revalidate_authority("immediately_before:paused_stage_transaction")
            self._revalidate_candidate_image()
            self._revalidate_target_configuration()
            self._revalidate_pre_state(EXPECTED_RUNTIME_SERVICES)
            self._verify_controls(self.memorial_controls)
            self._require_mutation_deadline(started)
            self._capture_forward_topology_inputs()
            self._require_mutation_deadline(started)
            self._consume_stage_owner_permit()
            self._protect_previous_images(WORKER_SERVICES)
            self._revalidate_authority("before:paused_stage_create")
            self._revalidate_candidate_image()
            self._revalidate_target_configuration()
            self._revalidate_pre_state(EXPECTED_RUNTIME_SERVICES)
            self._verify_controls(self.memorial_controls)
            self._revalidate_forward_topology_inputs()
            self._require_mutation_deadline(started)
            self.receipt["status"] = "creating_paused_stage"
            self._write_receipt()
            mutation_started = True
            try:
                self._target_create_paused(
                    self.forward_compose_files,
                    WORKER_SERVICES,
                    env_file=self.forward_env_path,
                )
                self._verify_paused_stage(WORKER_SERVICES, self.forward_compose_files)
                self._revalidate_pre_state(PRESERVED_RUNTIME_SERVICES)
                self._verify_controls(self.memorial_controls)
                self._revalidate_authority("immediately_after:paused_stage_create")
                self._verify_paused_stage(WORKER_SERVICES, self.forward_compose_files)
                self._revalidate_pre_state(PRESERVED_RUNTIME_SERVICES)
                self._verify_controls(self.memorial_controls)
                self._activate_forward_topology_inputs()
                self._require_mutation_deadline(started)
                self.receipt["status"] = "pass_paused_stage"
                self.receipt["runtime_side_effect_posture"] = {
                    **dict(self.receipt["runtime_side_effect_posture"]),
                    "status": "paused_stage_created_not_started",
                    "runtime_activation": "denied",
                }
                self.receipt["completed_at"] = _utc_text(self.utc_now())
                self._write_receipt()
            except Exception as primary:
                rollback_failures: list[str] = []
                if mutation_started:
                    try:
                        self._rollback_services(WORKER_SERVICES)
                    except Exception as rollback_exc:
                        rollback_failures.append(_safe_error(rollback_exc))
                    try:
                        self._revalidate_pre_state(PRESERVED_RUNTIME_SERVICES)
                    except Exception as preserved_exc:
                        rollback_failures.append(_safe_error(preserved_exc))
                    try:
                        self._verify_controls(self.memorial_controls)
                    except Exception as control_exc:
                        rollback_failures.append(_safe_error(control_exc))
                if rollback_failures:
                    self.retain_recovery_assets = True
                    self.receipt["status"] = "rollback_failed"
                    self.receipt["rollback"] = {
                        "status": "fail",
                        "reasons": rollback_failures,
                        "recovery_assets": "retained",
                    }
                    self._write_receipt()
                    raise DeployError("deployment_and_rollback_failed") from primary
                self.receipt["status"] = "failed_rolled_back"
                self.receipt["rollback"] = {
                    "status": "pass",
                    "order": list(reversed(WORKER_SERVICES)),
                }
                self._write_receipt()
                raise DeployError("deployment_failed_rolled_back") from primary

    def preflight(self) -> None:
        if not (self.root / ".env").is_file():
            raise DeployError("env_file_missing")
        if not self.candidate_reference:
            raise DeployError("candidate_image_required")
        source = self._source_metadata()
        self.source_revision = source["source_revision"]
        self.release_env["EA_SOURCE_REVISION"] = self.source_revision
        self.candidate = self._inspect_image(self.candidate_reference)
        self._read_evidence()
        self._capture_compose_source_inventory()
        self._detect_compose()
        self._capture_pre_state()
        self._snapshot_and_validate_rollback_inputs()
        self.memorial_controls = dict(self._capture_controls())
        self.receipt["memorial_control_baseline_sha256"] = _canonical_sha256(
            self.memorial_controls
        )
        self._validate_target_compose()
        self._capture_target_config_hashes()
        self._prepare_forward_input_plan()
        self.receipt["source_revision"] = self.source_revision
        self.receipt["candidate"] = self.candidate
        self.receipt["candidate_configuration_sha256"] = (
            self.configuration_document.sha256
        )
        self.receipt["candidate_provenance_sha256"] = self.provenance_document.sha256
        self.receipt["candidate_sbom_sha256"] = self.sbom_document.sha256
        self.receipt["production_stage_projection_sha256"] = (
            self.configuration_projection["stage_projection_sha256"]
        )
        self.receipt["permit_request"] = {
            "contract_name": STAGE_OWNER_PERMIT_CONTRACT,
            "deployment_id": self.deployment_id,
            "scope": "paused_stage_only",
            "stage_projection_sha256": self.configuration_projection[
                "stage_projection_sha256"
            ],
            "production_preflight_sha256": self.configuration_document.sha256,
            "source_revision": self.source_revision,
            "candidate_image_reference": self.candidate_reference,
            "candidate_image_id": self.candidate["image_id"],
            "compose_source_inventory_sha256": self.configuration_projection[
                "compose_source_inventory_sha256"
            ],
            "overlay_blob_sha256": self.configuration_projection["overlay_blob_sha256"],
            "rendered_compose_sha256": self.target_compose_sha256,
            "memorial_baseline_receipt_sha256": (
                self.memorial_baseline_document.sha256
            ),
            "memorial_ea_api_sha256": self.configuration_projection[
                "memorial_baseline"
            ]["ea_api_sha256"],
            "schema_v6_terminal_identity_sha256": (
                self.schema_v6_qualification.terminal_identity_sha256
            ),
            "schema_v6_permit_sha256": (self.schema_v6_qualification.permit_sha256),
            "provenance_sha256": self.provenance_document.sha256,
            "sbom_sha256": self.sbom_document.sha256,
            "pre_state_sha256": self.pre_state["sha256"],
            "target_compose_sha256": self.target_compose_sha256,
            "target_compose_config_sha256": dict(self.target_compose_config_sha256),
            "rollback_plan_sha256": self.rollback_plan_sha256,
            "forward_input_plan_sha256": self.forward_input_plan_sha256,
            "stage_mutation_services": list(WORKER_SERVICES),
            "preserved_services": list(PRESERVED_RUNTIME_SERVICES),
            "allowed_actions": list(PAUSED_STAGE_MUTATION_ACTIONS),
            "stage_mutation_authority_requested": True,
            "runtime_activation_authority_requested": False,
        }
        self._record("static_preflight", "pass")

    def deploy(self, *, execute: bool = False) -> dict[str, Any]:
        self._acquire_locks(allow_prepared_receipt=execute)
        try:
            self._write_receipt()
            self.preflight()
            if not execute:
                self.receipt["status"] = "preflight_only_owner_permit_required"
                self.receipt["completed_at"] = _utc_text(self.utc_now())
                self._write_receipt()
                return self.receipt
            try:
                self._load_authorities()
            except DeployError as exc:
                self.receipt["status"] = "blocked_authority"
                self.receipt["blocking_reason"] = _safe_error(exc)
                self.receipt["completed_at"] = _utc_text(self.utc_now())
                self._write_receipt()
                if execute:
                    raise
                return self.receipt
            self._execute_paused_stage_transaction()
            return self.receipt
        except Exception as exc:
            primary = _safe_error(exc)
            self.receipt["failure"] = {"reason": primary}
            if self.receipt.get("status") not in {
                "blocked_authority",
                "failed_rolled_back",
                "rollback_failed",
            }:
                self.receipt["status"] = (
                    "execution_failed_no_runtime_mutation"
                    if self.stage_owner_permit_consumed
                    else "preflight_failed"
                )
            self._write_receipt()
            raise
        finally:
            active_exception = sys.exc_info()[0] is not None
            cleanup_failures: list[str] = []
            if self.retain_recovery_assets:
                self.receipt["cleanup"] = {
                    "status": "recovery_assets_retained",
                    "protected_image_count": len(self.protected_prior_images),
                    "rollback_snapshot_count": len(self.rollback_snapshot_paths),
                }
                self._release_locks()
                self._write_receipt()
            else:
                try:
                    if self.protected_prior_images:
                        self._remove_protected_image_tags()
                except Exception:
                    cleanup_failures.append("protected_image_tags")
                try:
                    if not self.retain_active_topology_inputs:
                        self._cleanup_rollback_snapshots()
                except Exception:
                    cleanup_failures.append("rollback_snapshots")
                    self.receipt["rollback_snapshot_cleanup"] = {"status": "fail"}
                finally:
                    self._release_locks()
            if cleanup_failures:
                self.receipt["cleanup"] = {
                    "status": "fail",
                    "failed": cleanup_failures,
                }
                self.receipt["status"] = "deployment_cleanup_failed"
                self._write_receipt()
                if not active_exception:
                    raise DeployError("deployment_cleanup_failed")
            elif self.retain_active_topology_inputs:
                self.receipt["cleanup"] = {
                    "status": "active_topology_inputs_retained",
                    "retained_input_count": len(self.rollback_snapshot_paths),
                    "manifest_sha256": sorted(
                        set(self.active_topology_manifests.values())
                    ),
                    "scratch_cleanup": "not_claimed_for_retained_root",
                }
                if "rollback_plan" in self.receipt:
                    self.receipt["rollback_plan"]["cleanup_status"] = (
                        "retained_as_active_topology"
                    )
                self._write_receipt()
            elif not self.retain_recovery_assets and "rollback_plan" in self.receipt:
                self.receipt["cleanup"] = {"status": "pass"}
                self._write_receipt()


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--execute",
        action="store_true",
        help=(
            "Consume the fixed root-owned one-shot paused-stage permit and create "
            "the exact worker stage without starting it. Without this flag the "
            "command is preflight-only."
        ),
    )
    parser.add_argument(
        "--sentinel-state",
        type=Path,
        default=None,
        help=(
            "Absolute schema-v6 sentinel state path. Required explicitly here or "
            "through EA_VEXP_SENTINEL_STATE_PATH."
        ),
    )
    parser.add_argument(
        "--sentinel-owner-uid",
        type=int,
        default=None,
        help=(
            "Expected sentinel owner UID. Required explicitly here or through "
            "EA_VEXP_SENTINEL_OWNER_UID."
        ),
    )
    parser.add_argument(
        "--evidence-owner-uid",
        type=int,
        default=None,
        help=(
            "Expected configuration/provenance owner UID. Required explicitly "
            "here or through EA_AUDIOBOOK_RUNTIME_EVIDENCE_OWNER_UID."
        ),
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        receipt = AudiobookRuntimeDeployLane(
            sentinel_path=args.sentinel_state,
            sentinel_owner_uid=args.sentinel_owner_uid,
            evidence_owner_uid=args.evidence_owner_uid,
        ).deploy(execute=bool(args.execute))
    except DeployError as exc:
        print(json.dumps({"status": "fail", "reason": _safe_error(exc)}))
        return 1
    print(json.dumps(receipt, sort_keys=True))
    return 0 if receipt.get("status") == "pass_paused_stage" else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
