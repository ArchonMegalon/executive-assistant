#!/usr/bin/env python3
"""Materialize a fail-closed paused production-stage audiobook projection.

The verifier is read-only. It never builds, pulls, creates, starts, scales,
stops, recreates, activates, promotes, or sends anything. A prepared projection
is non-transferable validation input. Only a distinct governed one-shot consumer
may authorize a paused-stage mutation.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import subprocess  # nosec B404 - fixed read-only Git commands
from typing import Any, Mapping, Sequence

try:
    from scripts.vexp_schema_v6_authority import (
        QualificationEvidence,
        SchemaV6AuthorityError,
        _open_absolute_nofollow,
        load_schema_v6_qualification,
        read_trusted_json,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from vexp_schema_v6_authority import (  # type: ignore[no-redef]
        QualificationEvidence,
        SchemaV6AuthorityError,
        _open_absolute_nofollow,
        load_schema_v6_qualification,
        read_trusted_json,
    )


UTC = timezone.utc
ROOT = Path(__file__).resolve().parents[1]
OVERLAY_RELATIVE_PATH = Path(
    "deploy/audiobook-runtime-production/docker-compose.production-stage.yml"
)
BASE_COMPOSE_SOURCE_PATHS = (
    Path("docker-compose.yml"),
    Path("docker-compose.memorial.yml"),
    Path("docker-compose.whatsapp-web-session.yml"),
)
COMPOSE_SOURCE_PATHS = (*BASE_COMPOSE_SOURCE_PATHS, OVERLAY_RELATIVE_PATH)
ROOT_CONTRACT = "ea.audiobook_runtime_production_preflight.v1"
PROJECTION_CONTRACT = "ea.audiobook_runtime_production_projection.v1"
OVERLAY_CONTRACT = "ea.audiobook_runtime_production_stage_overlay.v1"
REQUIRED_OWNER_PERMIT_CONTRACT = "ea.audiobook_runtime_stage_owner_permit.v1"
MEMORIAL_BASELINE_CONTRACT = "ea.memorial_runtime_baseline.v1"
MEMORIAL_BASELINE_VERSION = 1
MEMORIAL_BASELINE_ISSUER = "ea-memorial-runtime-owner"
PROVENANCE_CONTRACT = "ea.audiobook_runtime_image_provenance.v1"
PROVENANCE_VERSION = 1
SBOM_CONTRACT = "ea.audiobook_runtime_image_sbom.v1"
SBOM_VERSION = 1
SBOM_SUBJECT_NAME = "ea-runtime"
DEPLOYMENT_SCOPE = "paused_stage_only"
LIVE_API_OWNER = "memorial"
TARGET_SERVICES = (
    "ea-api",
    "ea-worker",
    "ea-scheduler",
    "ea-whatsapp-web-action-processor",
)
STAGE_MUTATION_SERVICES = (
    "ea-worker",
    "ea-scheduler",
    "ea-whatsapp-web-action-processor",
)
PRESERVED_SERVICES = ("ea-api",)
EXPECTED_SERVICE_NAMES = frozenset(
    {
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
    }
)
EXPECTED_BASE_DOCUMENT_KEYS = frozenset({"name", "networks", "services", "volumes"})
EXPECTED_STAGE_DOCUMENT_KEYS = frozenset(
    {
        *EXPECTED_BASE_DOCUMENT_KEYS,
        "x-audiobook-production-stage",
        "x-audiobook-production-stage-service",
    }
)
REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
IMAGE_ID_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
IMAGE_RE = re.compile(r"^[^\s@:/]+(?::[0-9]+)?/[^\s@]+@sha256:[0-9a-f]{64}$")
URN_RE = re.compile(r"^urn:[A-Za-z0-9][A-Za-z0-9:._/-]{2,255}$")
COMPOSE_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$")
UTC_TIMESTAMP_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$"
)
COMPOSE_MINIMUM_VERSION = (2, 24, 4)
MAX_PRIVATE_INPUT_BYTES = 16 * 1024 * 1024
MAX_MEMORIAL_BASELINE_BYTES = 256 * 1024
MAX_MEMORIAL_BASELINE_LIFETIME = timedelta(hours=1)
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

VOCALLAB_STAGE_ENVIRONMENT = {
    "VOCALLAB_API_KEY": "",
    "VOCALLAB_API_KEY_FILE": "config/vocallab_api_key",
    "EA_AUDIOBOOK_VOCALLAB_ENABLED": "0",
    "EA_AUDIOBOOK_VOCALLAB_AUTO_RENDER": "0",
    "EA_AUDIOBOOK_VOCALLAB_CREDENTIAL_ROTATION_REQUIRED": "1",
    "EA_AUDIOBOOK_VOCALLAB_CREDENTIAL_PRODUCTION_ELIGIBLE": "0",
    "EA_AUDIOBOOK_VOCALLAB_BASE_URL": "https://api.vocallab.ai",
    "EA_AUDIOBOOK_VOCALLAB_MODEL": "v-pro",
    "EA_AUDIOBOOK_VOCALLAB_EXPRESSIVE_MODEL": "v-studio",
    "EA_AUDIOBOOK_VOCALLAB_DRAFT_MODEL": "v-lite",
    "EA_AUDIOBOOK_VOCALLAB_MAX_CHARS_PER_REQUEST": "1800",
    "EA_AUDIOBOOK_VOCALLAB_REQUESTS_PER_MINUTE": "30",
    "EA_AUDIOBOOK_VOCALLAB_MAX_IN_FLIGHT": "1",
    "EA_AUDIOBOOK_VOCALLAB_MAX_SEGMENTS_PER_RUN": "10",
    "EA_AUDIOBOOK_VOCALLAB_TIMEOUT_SECONDS": "120",
    "EA_AUDIOBOOK_VOCALLAB_POLL_INTERVAL_SECONDS": "2",
    "EA_AUDIOBOOK_VOCALLAB_POLL_TIMEOUT_SECONDS": "180",
    "EA_AUDIOBOOK_VOCALLAB_OUTPUT_FORMAT": "WAV",
    "EA_AUDIOBOOK_VOCALLAB_SAMPLE_RATE": "44100",
    "EA_AUDIOBOOK_VOCALLAB_MAX_AUDIO_BYTES": "33554432",
    "EA_AUDIOBOOK_VOCALLAB_MIN_REMAINING_POINTS": "3000",
    "EA_AUDIOBOOK_VOCALLAB_MAX_POINTS_PER_JOB": "6000",
    "EA_AUDIOBOOK_VOCALLAB_ALLOW_TOPUP_POINTS": "0",
    "EA_AUDIOBOOK_VOCALLAB_ALLOWED_VOICE_CLASSES": "professional,consented_clone",
    "EA_AUDIOBOOK_VOCALLAB_ALLOW_COMMUNITY_VOICES": "0",
    "EA_AUDIOBOOK_VOCALLAB_ALLOW_CLONES": "0",
    "EA_AUDIOBOOK_VOCALLAB_ALLOW_MEMORIAL": "0",
    "EA_AUDIOBOOK_VOCALLAB_VOICE_CATALOG_FILE": (
        "config/vocallab_voice_catalog.local.json"
    ),
    "EA_AUDIOBOOK_TTS_PROVIDER_ORDER": "unmixr,vocallab,piper_local",
    "EA_AUDIOBOOK_TTS_ALLOW_CROSS_PROVIDER_FALLBACK": "0",
}

COMMON_STAGE_ENVIRONMENT = {
    "EA_AUDIOBOOK_RUNTIME_STAGE_ONLY": "1",
    "EA_AUDIOBOOK_RUNTIME_ACTIVATION_AUTHORITY": "0",
    "EA_AUDIOBOOK_RUNTIME_QUEUE_MUTATION_AUTHORITY": "0",
    "EA_AUDIOBOOK_RUNTIME_PROVIDER_WORK_AUTHORITY": "0",
    "EA_AUDIOBOOK_RUNTIME_OUTBOUND_SEND_AUTHORITY": "0",
    "EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED": "0",
    "EA_AUDIOBOOK_UNMIXR_AUTO_RENDER": "0",
    **VOCALLAB_STAGE_ENVIRONMENT,
    "EA_AUDIOBOOK_CINEMATIC_NARRATION": "0",
    "EA_AUDIOBOOKSHELF_AUTO_IMPORT": "0",
    "EA_AUDIOBOOKSHELF_PUBLIC_SHARE_ENABLED": "0",
}
EXPECTED_STAGE_ENVIRONMENT = {
    "ea-worker": {
        **COMMON_STAGE_ENVIRONMENT,
        "EA_TELEGRAM_AUDIOBOOK_EPUB_ENABLED": "0",
        "EA_ANSWERLY_AUTO_IMPORT_GMAIL_PDFS": "0",
    },
    "ea-scheduler": {
        **COMMON_STAGE_ENVIRONMENT,
        "EA_TELEGRAM_AUDIOBOOK_EPUB_ENABLED": "0",
        "EA_ANSWERLY_AUTO_IMPORT_GMAIL_PDFS": "0",
    },
    "ea-whatsapp-web-action-processor": {
        **COMMON_STAGE_ENVIRONMENT,
        "EA_WHATSAPP_WEB_ACTION_PROCESSOR_ENABLED": "0",
        "EA_WHATSAPP_AUDIOBOOK_RESUME_DUE": "0",
        "EA_WHATSAPP_AUDIOBOOK_FOLLOWUP_ENABLED": "0",
        "EA_WHATSAPP_WEB_TG_SUMMARY_ENABLED": "0",
    },
}
EXPECTED_STAGE_LABELS = {
    "com.archonmegalon.ea.audiobook-runtime.contract": OVERLAY_CONTRACT,
    "com.archonmegalon.ea.audiobook-runtime.deployment-scope": DEPLOYMENT_SCOPE,
    "com.archonmegalon.ea.audiobook-runtime.activation-authority": "denied",
    "com.archonmegalon.ea.audiobook-runtime.live-api-owner": LIVE_API_OWNER,
}
EXPECTED_EXTENSION = {
    "contract_name": OVERLAY_CONTRACT,
    "deployment_scope": DEPLOYMENT_SCOPE,
    "live_api_owner": LIVE_API_OWNER,
    "live_api_mutation_authority": "denied",
    "runtime_activation_authority": "denied",
    "queue_mutation_authority": "denied",
    "provider_work_authority": "denied",
    "outbound_send_authority": "denied",
}
IDLE_COMMAND = [
    "/bin/sh",
    "-ec",
    "echo '{\"contract\":\"ea.audiobook_runtime_production_stage_overlay.v1\","
    "\"event\":\"paused_stage_idle\",\"ok\":true}'; "
    "while :; do sleep 3600; done",
]
COMMON_STAGE_SERVICE_KEYS = frozenset(
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
EXPECTED_STAGE_SERVICE_KEYS = {
    "ea-worker": COMMON_STAGE_SERVICE_KEYS | {"pids_limit"},
    "ea-scheduler": COMMON_STAGE_SERVICE_KEYS | {"pids_limit"},
    "ea-whatsapp-web-action-processor": COMMON_STAGE_SERVICE_KEYS,
}
EXPECTED_STAGE_RESOURCES = {
    "ea-worker": {"cpu_shares": 128, "cpus": 0.75, "pids_limit": 512},
    "ea-scheduler": {"cpu_shares": 128, "cpus": 0.75, "pids_limit": 512},
    "ea-whatsapp-web-action-processor": {"cpu_shares": 32, "cpus": 0.5},
}
SOURCE_INVENTORY_ENTRY_KEYS = frozenset(
    {"path", "blob_sha256", "working_sha256"}
)
MEMORIAL_BASELINE_KEYS = frozenset(
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
PROVENANCE_KEYS = frozenset(
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
SBOM_KEYS = frozenset(
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


class ProductionStageError(RuntimeError):
    """Stable, content-free production-stage denial."""


@dataclass(frozen=True)
class GitRepositoryBinding:
    work_tree: Path
    git_dir: Path
    common_dir: Path
    head_commit: str
    work_tree_identity: tuple[int, int, int, int, int]
    git_dir_identity: tuple[int, int, int, int, int]
    common_dir_identity: tuple[int, int, int, int, int]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_utc(value: object, *, reason: str) -> datetime:
    if not isinstance(value, str) or not UTC_TIMESTAMP_RE.fullmatch(value):
        raise ProductionStageError(reason)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProductionStageError(reason) from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ProductionStageError(reason)
    return parsed.astimezone(UTC)


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _parse_compose_version(value: str) -> tuple[int, int, int] | None:
    match = COMPOSE_VERSION_RE.fullmatch(str(value or "").strip())
    if not match:
        return None
    return tuple(int(part) for part in match.groups())


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _string_mapping(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): str(item) for key, item in value.items()}


def _validate_provenance(
    payload: Mapping[str, Any] | None,
    *,
    payload_sha256: str,
    source_revision: str,
    image_reference: str,
    image_id: str,
) -> tuple[dict[str, object], list[str]]:
    issues: list[str] = []
    if not isinstance(payload, Mapping):
        return {}, ["evidence:provenance:missing_or_invalid"]
    if set(payload) != PROVENANCE_KEYS:
        issues.append("evidence:provenance:schema_invalid")
    expected = {
        "contract_name": PROVENANCE_CONTRACT,
        "version": PROVENANCE_VERSION,
        "status": "pass",
        "source_revision": source_revision,
        "image_reference": image_reference,
        "image_id": image_id,
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            issues.append(f"evidence:provenance:{key}_mismatch")
    if not SHA256_RE.fullmatch(payload_sha256):
        issues.append("evidence:provenance:digest_invalid")
    summary = {
        "contract_name": PROVENANCE_CONTRACT,
        "sha256": payload_sha256 if SHA256_RE.fullmatch(payload_sha256) else "",
        "source_revision": source_revision if REVISION_RE.fullmatch(source_revision) else "",
        "image_reference": image_reference if IMAGE_RE.fullmatch(image_reference) else "",
        "image_id": image_id if IMAGE_ID_RE.fullmatch(image_id) else "",
    }
    return summary, issues


def _validate_sbom(
    payload: Mapping[str, Any] | None,
    *,
    payload_sha256: str,
    source_revision: str,
    image_reference: str,
    image_id: str,
) -> tuple[dict[str, object], list[str]]:
    issues: list[str] = []
    if not isinstance(payload, Mapping):
        return {}, ["evidence:sbom:missing_or_invalid"]
    if set(payload) != SBOM_KEYS:
        issues.append("evidence:sbom:schema_invalid")
    expected = {
        "contract_name": SBOM_CONTRACT,
        "version": SBOM_VERSION,
        "status": "pass",
        "subject_name": SBOM_SUBJECT_NAME,
        "subject_image_reference": image_reference,
        "subject_image_id": image_id,
        "subject_source_revision": source_revision,
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            issues.append(f"evidence:sbom:{key}_mismatch")
    namespace = payload.get("document_namespace")
    serial_number = payload.get("serial_number")
    if not isinstance(namespace, str) or not URN_RE.fullmatch(namespace):
        issues.append("evidence:sbom:document_namespace_invalid")
    if not isinstance(serial_number, str) or not URN_RE.fullmatch(serial_number):
        issues.append("evidence:sbom:serial_number_invalid")
    if not SHA256_RE.fullmatch(payload_sha256):
        issues.append("evidence:sbom:digest_invalid")

    bom = payload.get("bom")
    if not isinstance(bom, Mapping):
        issues.append("evidence:sbom:document_invalid")
    else:
        if (
            bom.get("bomFormat") != "CycloneDX"
            or not isinstance(bom.get("specVersion"), str)
            or type(bom.get("version")) is not int
            or int(bom.get("version", 0)) < 1
            or bom.get("serialNumber") != serial_number
        ):
            issues.append("evidence:sbom:document_header_invalid")
        components = bom.get("components")
        if not isinstance(components, list) or not components:
            issues.append("evidence:sbom:components_invalid")
        metadata = bom.get("metadata")
        component = metadata.get("component") if isinstance(metadata, Mapping) else None
        if not isinstance(component, Mapping) or component.get("name") != SBOM_SUBJECT_NAME:
            issues.append("evidence:sbom:subject_component_invalid")
            properties: object = None
        else:
            properties = component.get("properties")
        linked_properties: dict[str, str] = {}
        if isinstance(properties, list):
            duplicate_property = False
            for item in properties:
                if not isinstance(item, Mapping):
                    duplicate_property = True
                    continue
                name = item.get("name")
                value = item.get("value")
                if not isinstance(name, str) or not isinstance(value, str):
                    duplicate_property = True
                    continue
                if name in linked_properties:
                    duplicate_property = True
                linked_properties[name] = value
            if duplicate_property:
                issues.append("evidence:sbom:subject_properties_invalid")
        else:
            issues.append("evidence:sbom:subject_properties_invalid")
        required_properties = {
            "ea:document-namespace": namespace,
            "ea:image-reference": image_reference,
            "ea:image-id": image_id,
            "ea:source-revision": source_revision,
        }
        if any(
            linked_properties.get(key) != value
            for key, value in required_properties.items()
        ):
            issues.append("evidence:sbom:subject_linkage_invalid")
    summary = {
        "contract_name": SBOM_CONTRACT,
        "sha256": payload_sha256 if SHA256_RE.fullmatch(payload_sha256) else "",
        "document_namespace": (
            namespace
            if isinstance(namespace, str) and URN_RE.fullmatch(namespace)
            else ""
        ),
        "serial_number": (
            serial_number
            if isinstance(serial_number, str) and URN_RE.fullmatch(serial_number)
            else ""
        ),
        "subject_name": SBOM_SUBJECT_NAME,
        "subject_image_reference": (
            image_reference if IMAGE_RE.fullmatch(image_reference) else ""
        ),
        "subject_image_id": image_id if IMAGE_ID_RE.fullmatch(image_id) else "",
        "subject_source_revision": (
            source_revision if REVISION_RE.fullmatch(source_revision) else ""
        ),
    }
    return summary, issues


def _validate_source_inventory(
    inventory: object,
    *,
    expected_paths: Sequence[Path],
    inventory_sha256: object,
    reason: str,
) -> list[str]:
    if not isinstance(inventory, list) or len(inventory) != len(expected_paths):
        return [f"{reason}:inventory_invalid"]
    issues: list[str] = []
    for index, expected_path in enumerate(expected_paths):
        entry = inventory[index]
        if not isinstance(entry, Mapping) or set(entry) != SOURCE_INVENTORY_ENTRY_KEYS:
            issues.append(f"{reason}:entry_{index}_schema_invalid")
            continue
        if entry.get("path") != expected_path.as_posix():
            issues.append(f"{reason}:entry_{index}_path_invalid")
        blob_sha256 = entry.get("blob_sha256")
        working_sha256 = entry.get("working_sha256")
        if (
            not isinstance(blob_sha256, str)
            or not SHA256_RE.fullmatch(blob_sha256)
            or working_sha256 != blob_sha256
        ):
            issues.append(f"{reason}:entry_{index}_digest_invalid")
    if (
        not isinstance(inventory_sha256, str)
        or not SHA256_RE.fullmatch(inventory_sha256)
        or _canonical_sha256(inventory) != inventory_sha256
    ):
        issues.append(f"{reason}:inventory_digest_invalid")
    return issues


def _validate_memorial_baseline(
    receipt: Mapping[str, Any] | None,
    *,
    receipt_sha256: str,
    baseline_compose: Mapping[str, Any],
    now: datetime,
) -> tuple[dict[str, object], list[str]]:
    issues: list[str] = []
    if not isinstance(receipt, Mapping):
        return {}, ["authority:memorial_baseline:missing_or_invalid"]
    if set(receipt) != MEMORIAL_BASELINE_KEYS:
        issues.append("authority:memorial_baseline:schema_invalid")
    expected = {
        "contract_name": MEMORIAL_BASELINE_CONTRACT,
        "version": MEMORIAL_BASELINE_VERSION,
        "status": "pass",
        "issuer": MEMORIAL_BASELINE_ISSUER,
    }
    for key, value in expected.items():
        if receipt.get(key) != value:
            issues.append(f"authority:memorial_baseline:{key}_mismatch")
    source_revision = receipt.get("source_revision")
    if not isinstance(source_revision, str) or not REVISION_RE.fullmatch(source_revision):
        issues.append("authority:memorial_baseline:source_revision_invalid")
    issues.extend(
        _validate_source_inventory(
            receipt.get("compose_source_inventory"),
            expected_paths=BASE_COMPOSE_SOURCE_PATHS,
            inventory_sha256=receipt.get("compose_source_inventory_sha256"),
            reason="authority:memorial_baseline",
        )
    )
    baseline_sha256 = _canonical_sha256(baseline_compose)
    services = _mapping(baseline_compose.get("services"))
    baseline_api = services.get("ea-api")
    api_sha256 = (
        _canonical_sha256(baseline_api) if isinstance(baseline_api, Mapping) else ""
    )
    if receipt.get("rendered_compose_sha256") != baseline_sha256:
        issues.append("authority:memorial_baseline:render_digest_mismatch")
    if receipt.get("ea_api_sha256") != api_sha256 or not api_sha256:
        issues.append("authority:memorial_baseline:ea_api_digest_mismatch")
    if not SHA256_RE.fullmatch(receipt_sha256):
        issues.append("authority:memorial_baseline:receipt_digest_invalid")
    try:
        issued_at = _parse_utc(
            receipt.get("issued_at"),
            reason="authority:memorial_baseline:issued_at_invalid",
        )
        expires_at = _parse_utc(
            receipt.get("expires_at"),
            reason="authority:memorial_baseline:expires_at_invalid",
        )
        if (
            expires_at <= issued_at
            or expires_at - issued_at > MAX_MEMORIAL_BASELINE_LIFETIME
            or now < issued_at
            or now >= expires_at
        ):
            issues.append("authority:memorial_baseline:not_current")
    except ProductionStageError as exc:
        issues.append(str(exc))
    summary = {
        "contract_name": MEMORIAL_BASELINE_CONTRACT,
        "receipt_sha256": (
            receipt_sha256 if SHA256_RE.fullmatch(receipt_sha256) else ""
        ),
        "source_revision": (
            source_revision
            if isinstance(source_revision, str) and REVISION_RE.fullmatch(source_revision)
            else ""
        ),
        "compose_inventory_sha256": (
            str(receipt.get("compose_source_inventory_sha256"))
            if isinstance(receipt.get("compose_source_inventory_sha256"), str)
            and SHA256_RE.fullmatch(
                str(receipt.get("compose_source_inventory_sha256"))
            )
            else ""
        ),
        "rendered_compose_sha256": baseline_sha256,
        "ea_api_sha256": api_sha256,
    }
    return summary, issues


def _expected_environment(service: str, revision: str) -> dict[str, str]:
    return {
        "EA_SOURCE_REVISION": revision,
        "EA_DEPLOY_COMMIT_SHA": revision,
        **EXPECTED_STAGE_ENVIRONMENT[service],
    }


def _expected_labels(revision: str) -> dict[str, str]:
    return {
        "org.opencontainers.image.revision": revision,
        **EXPECTED_STAGE_LABELS,
    }


def _check_stage_service(
    payload: Mapping[str, Any],
    *,
    service: str,
    revision: str,
    image_reference: str,
) -> list[str]:
    issues: list[str] = []
    prefix = f"compose:{service}"
    if set(payload) != EXPECTED_STAGE_SERVICE_KEYS[service]:
        issues.append(f"{prefix}:field_set_invalid")
    if str(payload.get("image") or "") != image_reference:
        issues.append(f"{prefix}:image_mismatch")
    if payload.get("pull_policy") != "never":
        issues.append(f"{prefix}:pull_policy_not_never")
    if payload.get("deploy") != {
        "placement": {},
        "replicas": 0,
        "resources": {},
    }:
        issues.append(f"{prefix}:replicas_not_exact_zero")
    if payload.get("restart") != "no":
        issues.append(f"{prefix}:restart_not_disabled")
    if _string_mapping(payload.get("environment")) != _expected_environment(service, revision):
        issues.append(f"{prefix}:environment_not_exact_paused_allowlist")
    if _string_mapping(payload.get("labels")) != _expected_labels(revision):
        issues.append(f"{prefix}:labels_not_exact_allowlist")
    if payload.get("command") != IDLE_COMMAND:
        issues.append(f"{prefix}:idle_command_invalid")
    exact_values = {
        "entrypoint": ["/usr/local/bin/docker-entrypoint.sh"],
        "working_dir": "/app",
        "user": "10001:10001",
        "cap_drop": ["ALL"],
        "read_only": True,
        "security_opt": ["no-new-privileges:true"],
        "tmpfs": ["/tmp", "/run"],
        "healthcheck": {"disable": True},
        "networks": {"default": None},
        **EXPECTED_STAGE_RESOURCES[service],
    }
    for field, expected in exact_values.items():
        if payload.get(field) != expected:
            issues.append(f"{prefix}:{field}_mismatch")
    if str(payload.get("container_name") or "") != service:
        issues.append(f"{prefix}:container_name_mismatch")
    return issues


def _expected_stage_anchor(revision: str, image_reference: str) -> dict[str, object]:
    return {
        "image": image_reference,
        "pull_policy": "never",
        "deploy": {"replicas": 0},
        "restart": "no",
        "environment": _expected_environment("ea-worker", revision),
        "labels": _expected_labels(revision),
        "command": IDLE_COMMAND,
        "entrypoint": ["/usr/local/bin/docker-entrypoint.sh"],
        "working_dir": "/app",
        "user": "10001:10001",
        "privileged": False,
        "cap_drop": ["ALL"],
        "read_only": True,
        "security_opt": ["no-new-privileges:true"],
        "tmpfs": ["/tmp", "/run"],
        "healthcheck": {"disable": True},
    }


def _projection_core(
    *,
    source_revision: str,
    image_reference: str,
    image_id: str,
    compose_source_inventory: Sequence[Mapping[str, Any]],
    compose_source_inventory_sha256: str,
    rendered_compose_sha256: str,
    memorial_baseline: Mapping[str, object],
    qualification: QualificationEvidence,
    provenance: Mapping[str, object],
    sbom: Mapping[str, object],
) -> dict[str, object]:
    overlay_entry = dict(compose_source_inventory[-1])
    return {
        "contract_name": PROJECTION_CONTRACT,
        "deployment_scope": DEPLOYMENT_SCOPE,
        "target_services": list(TARGET_SERVICES),
        "stage_mutation_services": list(STAGE_MUTATION_SERVICES),
        "preserved_services": list(PRESERVED_SERVICES),
        "source_revision": source_revision,
        "candidate_image_reference": image_reference,
        "candidate_image_id": image_id,
        "compose_source_inventory": [dict(entry) for entry in compose_source_inventory],
        "compose_source_inventory_sha256": compose_source_inventory_sha256,
        "overlay_path": OVERLAY_RELATIVE_PATH.as_posix(),
        "overlay_blob_sha256": overlay_entry["blob_sha256"],
        "overlay_working_sha256": overlay_entry["working_sha256"],
        "rendered_compose_sha256": rendered_compose_sha256,
        "memorial_baseline": dict(memorial_baseline),
        "schema_v6_terminal_identity_sha256": qualification.terminal_identity_sha256,
        "provenance": dict(provenance),
        "sbom": dict(sbom),
        "live_api_owner": LIVE_API_OWNER,
        "live_api_mutation_authority": False,
        "runtime_activation_authority": False,
        "queue_mutation_authority": False,
        "provider_work_authority": False,
        "outbound_send_authority": False,
        "build_authority": False,
        "pull_authority": False,
    }


def verify_audiobook_runtime_production_stage(
    baseline_compose: Mapping[str, Any],
    staged_compose: Mapping[str, Any],
    *,
    expected_revision: str,
    expected_image: str,
    expected_image_id: str,
    source_commit: str,
    compose_source_inventory: Sequence[Mapping[str, Any]] | None,
    compose_source_inventory_sha256: str,
    compose_version: str,
    memorial_baseline_receipt: Mapping[str, Any] | None,
    memorial_baseline_receipt_sha256: str,
    provenance: Mapping[str, Any] | None,
    provenance_sha256: str,
    sbom: Mapping[str, Any] | None,
    sbom_sha256: str,
    qualification: QualificationEvidence | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Prepare an exact, non-transferable paused-stage projection."""

    checked_now = now or _utc_now()
    if checked_now.tzinfo is None or checked_now.utcoffset() != timedelta(0):
        raise ProductionStageError("preflight_clock_invalid")
    checked_now = checked_now.astimezone(UTC)
    issues: list[str] = []
    revision = str(expected_revision or "").strip()
    image = str(expected_image or "").strip()
    image_id = str(expected_image_id or "").strip()
    if not REVISION_RE.fullmatch(revision):
        issues.append("preflight:source_revision_invalid")
    if not IMAGE_RE.fullmatch(image) or image.count("@") != 1:
        issues.append("preflight:image_reference_invalid")
    if not IMAGE_ID_RE.fullmatch(image_id):
        issues.append("preflight:image_id_invalid")
    if source_commit != revision or not REVISION_RE.fullmatch(source_commit):
        issues.append("preflight:source_commit_mismatch")
    parsed_compose_version = _parse_compose_version(compose_version)
    if parsed_compose_version is None or parsed_compose_version < COMPOSE_MINIMUM_VERSION:
        issues.append("preflight:compose_version_invalid_or_too_old")
    inventory = list(compose_source_inventory or [])
    inventory_issues = _validate_source_inventory(
        inventory,
        expected_paths=COMPOSE_SOURCE_PATHS,
        inventory_sha256=compose_source_inventory_sha256,
        reason="preflight:compose_source",
    )
    issues.extend(inventory_issues)

    sbom_summary, sbom_issues = _validate_sbom(
        sbom,
        payload_sha256=sbom_sha256,
        source_revision=revision,
        image_reference=image,
        image_id=image_id,
    )
    issues.extend(sbom_issues)
    provenance_summary, provenance_issues = _validate_provenance(
        provenance,
        payload_sha256=provenance_sha256,
        source_revision=revision,
        image_reference=image,
        image_id=image_id,
    )
    if not isinstance(provenance, Mapping) or provenance.get("sbom_sha256") != sbom_sha256:
        provenance_issues.append("evidence:provenance:sbom_digest_mismatch")
    issues.extend(provenance_issues)

    memorial_summary, memorial_issues = _validate_memorial_baseline(
        memorial_baseline_receipt,
        receipt_sha256=memorial_baseline_receipt_sha256,
        baseline_compose=baseline_compose,
        now=checked_now,
    )
    issues.extend(memorial_issues)

    baseline_services = _mapping(baseline_compose.get("services"))
    staged_services = _mapping(staged_compose.get("services"))
    if set(baseline_compose) != EXPECTED_BASE_DOCUMENT_KEYS:
        issues.append("compose:baseline_document_field_set_invalid")
    if set(staged_compose) != EXPECTED_STAGE_DOCUMENT_KEYS:
        issues.append("compose:staged_document_field_set_invalid")
    if baseline_compose.get("name") != "ea" or staged_compose.get("name") != "ea":
        issues.append("compose:project_name_mismatch")
    if (
        set(baseline_services) != EXPECTED_SERVICE_NAMES
        or set(staged_services) != EXPECTED_SERVICE_NAMES
    ):
        issues.append("compose:service_inventory_invalid")
    for field in ("name", "networks"):
        if baseline_compose.get(field) != staged_compose.get(field):
            issues.append(f"compose:{field}_changed")
    expected_stage_volumes = _mapping(baseline_compose.get("volumes"))
    expected_stage_volumes.pop("ea_whatsapp_web_actions", None)
    if _mapping(staged_compose.get("volumes")) != expected_stage_volumes:
        issues.append("compose:top_level_volume_projection_invalid")
    if staged_compose.get("x-audiobook-production-stage") != EXPECTED_EXTENSION:
        issues.append("compose:stage_extension_mismatch")
    if staged_compose.get("x-audiobook-production-stage-service") != (
        _expected_stage_anchor(revision, image)
    ):
        issues.append("compose:stage_service_extension_mismatch")

    baseline_api = baseline_services.get("ea-api")
    staged_api = staged_services.get("ea-api")
    api_preserved = (
        isinstance(baseline_api, Mapping)
        and isinstance(staged_api, Mapping)
        and json.dumps(
            baseline_api,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        == json.dumps(
            staged_api,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        and memorial_summary.get("ea_api_sha256") == _canonical_sha256(staged_api)
    )
    if not api_preserved:
        issues.append("compose:ea-api:not_canonical_byte_equivalent_to_memorial_baseline")
    for service in sorted(EXPECTED_SERVICE_NAMES - set(STAGE_MUTATION_SERVICES)):
        if baseline_services.get(service) != staged_services.get(service):
            issues.append("compose:preserved_service_changed")
    for service in STAGE_MUTATION_SERVICES:
        payload = staged_services.get(service)
        if not isinstance(payload, Mapping):
            issues.append(f"compose:{service}:missing_or_invalid")
            continue
        issues.extend(
            _check_stage_service(
                payload,
                service=service,
                revision=revision,
                image_reference=image,
            )
        )

    rendered_compose_sha256 = _canonical_sha256(staged_compose)
    qualification_valid = (
        isinstance(qualification, QualificationEvidence)
        and qualification.permit_contract_name
        == "ea.vexp_memorial_mutation_permit.v1"
        and SHA256_RE.fullmatch(qualification.state_sha256) is not None
        and SHA256_RE.fullmatch(qualification.terminal_identity_sha256) is not None
        and SHA256_RE.fullmatch(qualification.permit_sha256) is not None
        and qualification.mutation_authority_transferred is False
    )
    if qualification_valid:
        try:
            qualified_at = _parse_utc(
                qualification.qualified_at,
                reason="authority:schema_v6_qualified_at_invalid",
            )
            schema_permit_expires_at = _parse_utc(
                qualification.permit_expires_at,
                reason="authority:schema_v6_permit_expiry_invalid",
            )
            qualification_valid = (
                qualified_at <= checked_now < schema_permit_expires_at
            )
        except ProductionStageError:
            qualification_valid = False
    if not qualification_valid:
        issues.append("authority:schema_v6_qualification_missing")
    prepared = not issues
    projection_core: dict[str, object] = {}
    stage_projection_sha256 = ""
    if prepared and qualification_valid:
        projection_core = _projection_core(
            source_revision=revision,
            image_reference=image,
            image_id=image_id,
            compose_source_inventory=inventory,
            compose_source_inventory_sha256=compose_source_inventory_sha256,
            rendered_compose_sha256=rendered_compose_sha256,
            memorial_baseline=memorial_summary,
            qualification=qualification,
            provenance=provenance_summary,
            sbom=sbom_summary,
        )
        stage_projection_sha256 = _canonical_sha256(projection_core)

    rendered_pause_invariants_valid = not any(
        issue.startswith("compose:") for issue in issues
    )
    qualification_projection = (
        qualification.projection()
        if qualification_valid
        else {
            "state_version": 6,
            "evidence_scope": "schema_v6_terminal_qualification_only",
            "mutation_authority_transferred": False,
            "validated": False,
        }
    )
    if qualification_valid:
        qualification_projection["validated"] = True

    overlay_entry = inventory[-1] if not inventory_issues and inventory else {}

    projection = {
        "contract_name": PROJECTION_CONTRACT,
        "version": 1,
        "status": "prepared" if prepared else "blocked",
        "configuration_only": True,
        "configuration_valid": prepared,
        "preparation_valid": prepared,
        "non_transferable": True,
        "deploy_ready": False,
        "deployment_scope": DEPLOYMENT_SCOPE,
        "stage_deploy_eligible": False,
        "stage_mutation_authority": False,
        "deployment_authority": False,
        "group_deploy_eligible": False,
        "runtime_activation_authority": False,
        "queue_mutation_authority": False,
        "provider_work_authority": False,
        "outbound_send_authority": False,
        "build_authority": False,
        "pull_authority": False,
        "target_services": list(TARGET_SERVICES),
        "stage_mutation_services": list(STAGE_MUTATION_SERVICES),
        "preserved_services": list(PRESERVED_SERVICES),
        "source_revision": revision if REVISION_RE.fullmatch(revision) else "",
        "candidate_image_reference": image if IMAGE_RE.fullmatch(image) else "",
        "candidate_image_id": image_id if IMAGE_ID_RE.fullmatch(image_id) else "",
        "compose_source_inventory": inventory if not inventory_issues else [],
        "compose_source_inventory_sha256": (
            compose_source_inventory_sha256 if not inventory_issues else ""
        ),
        "overlay_path": OVERLAY_RELATIVE_PATH.as_posix(),
        "overlay_blob_sha256": str(overlay_entry.get("blob_sha256") or ""),
        "overlay_working_sha256": str(overlay_entry.get("working_sha256") or ""),
        "rendered_compose_sha256": rendered_compose_sha256,
        "memorial_baseline": memorial_summary,
        "stage_projection_sha256": stage_projection_sha256,
        "provenance": provenance_summary,
        "sbom": sbom_summary,
        "live_api_owner": LIVE_API_OWNER,
        "live_api_mutation_authority": False,
        "owner_handoff_required": True,
        "owner_handoff_performed": False,
        "owner_preservation_permit_required": True,
        "required_owner_permit_contract": REQUIRED_OWNER_PERMIT_CONTRACT,
        "silent_takeover_allowed": False,
        "memorial_compatible": api_preserved,
        "schema_v6_qualification": qualification_projection,
        "side_effect_posture": {
            "deployment_hold": True,
            "replicas_zero": (
                {service: 0 for service in STAGE_MUTATION_SERVICES}
                if rendered_pause_invariants_valid
                else {}
            ),
            "idle_command_bound": rendered_pause_invariants_valid,
            "queue_mutation_authority": False,
            "provider_work_authority": False,
            "outbound_send_authority": False,
            "runtime_activation_authority": False,
        },
    }
    return {
        "contract_name": ROOT_CONTRACT,
        "version": 1,
        "status": "prepared" if prepared else "blocked",
        "verification_mode": "prepare",
        "verified_at": _utc_text(checked_now),
        "mutations_performed": 0,
        "preparation_valid": prepared,
        "non_transferable": True,
        "deploy_ready": False,
        "deployment_scope": DEPLOYMENT_SCOPE,
        "stage_deploy_eligible": False,
        "stage_mutation_authority": False,
        "deployment_authority": False,
        "group_deploy_eligible": False,
        "runtime_activation_authority": False,
        "queue_mutation_authority": False,
        "provider_work_authority": False,
        "outbound_send_authority": False,
        "build_authority": False,
        "pull_authority": False,
        "issues": sorted(set(issues)),
        "production_projection": projection,
        "next_action": (
            "governed_consumer_must_issue_and_atomically_consume_a_distinct_root_one_shot_permit"
            if prepared
            else "repair_preparation_inputs_without_mutating_runtime"
        ),
    }


def _trusted_identity(metadata: os.stat_result) -> tuple[int, ...]:
    return (
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


def _read_private_bytes(path: Path, *, max_bytes: int, reason: str) -> tuple[bytes, str]:
    if not path.is_absolute():
        raise ProductionStageError(f"{reason}_path_invalid")
    descriptor = -1
    try:
        descriptor = _open_absolute_nofollow(
            path,
            flags=os.O_RDONLY,
            reason=reason,
            require_root_parents=False,
        )
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.getuid()
            or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) != 0o600
            or not 0 < before.st_size <= max_bytes
        ):
            raise ProductionStageError(f"{reason}_untrusted")
        chunks: list[bytes] = []
        remaining = int(before.st_size)
        while remaining:
            chunk = os.read(descriptor, min(65_536, remaining))
            if not chunk:
                raise ProductionStageError(f"{reason}_changed_during_read")
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
        current_descriptor = _open_absolute_nofollow(
            path,
            flags=os.O_RDONLY,
            reason=reason,
            require_root_parents=False,
        )
        try:
            current = os.fstat(current_descriptor)
        finally:
            os.close(current_descriptor)
        if (
            _trusted_identity(before) != _trusted_identity(after)
            or _trusted_identity(before) != _trusted_identity(current)
        ):
            raise ProductionStageError(f"{reason}_changed_during_read")
    except ProductionStageError:
        raise
    except SchemaV6AuthorityError as exc:
        raise ProductionStageError(str(exc)) from exc
    except OSError as exc:
        raise ProductionStageError(f"{reason}_unavailable") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    raw = b"".join(chunks)
    return raw, hashlib.sha256(raw).hexdigest()


def _read_private_json(path: Path, *, max_bytes: int, reason: str) -> tuple[dict[str, Any], str]:
    raw, digest = _read_private_bytes(path, max_bytes=max_bytes, reason=reason)
    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for key, value in pairs:
            if key in payload:
                raise ValueError("duplicate_json_key")
            payload[key] = value
        return payload

    def reject_constant(_value: str) -> None:
        raise ValueError("non_finite_json_constant")

    try:
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=unique_object,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, ValueError) as exc:
        raise ProductionStageError(f"{reason}_json_invalid") from exc
    if not isinstance(payload, dict):
        raise ProductionStageError(f"{reason}_json_invalid")
    return payload, digest


def _read_repository_file(path: Path) -> bytes:
    descriptor = -1
    try:
        descriptor = _open_absolute_nofollow(
            path,
            flags=os.O_RDONLY,
            reason="compose_source",
            require_root_parents=False,
        )
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid not in {0, os.getuid()}
            or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) & 0o022
            or not 0 < before.st_size <= MAX_PRIVATE_INPUT_BYTES
        ):
            raise ProductionStageError("compose_source_untrusted")
        chunks: list[bytes] = []
        remaining = int(before.st_size)
        while remaining:
            chunk = os.read(descriptor, min(65_536, remaining))
            if not chunk:
                raise ProductionStageError("compose_source_changed_during_read")
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
        current_descriptor = _open_absolute_nofollow(
            path,
            flags=os.O_RDONLY,
            reason="compose_source",
            require_root_parents=False,
        )
        try:
            current = os.fstat(current_descriptor)
        finally:
            os.close(current_descriptor)
        if (
            _trusted_identity(before) != _trusted_identity(after)
            or _trusted_identity(before) != _trusted_identity(current)
        ):
            raise ProductionStageError("compose_source_changed_during_read")
    except ProductionStageError:
        raise
    except SchemaV6AuthorityError as exc:
        raise ProductionStageError(str(exc)) from exc
    except OSError as exc:
        raise ProductionStageError("compose_source_unavailable") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    return b"".join(chunks)


def _trusted_git_executable() -> Path:
    candidate = shutil.which("git", path=GIT_SAFE_PATH)
    if not candidate:
        raise ProductionStageError("compose_source_git_unavailable")
    candidate_path = Path(candidate)
    if not candidate_path.is_absolute():
        raise ProductionStageError("compose_source_git_untrusted")
    descriptor = -1
    try:
        descriptor = _open_absolute_nofollow(
            candidate_path,
            flags=os.O_RDONLY,
            reason="compose_source_git",
            require_root_parents=True,
        )
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != ROOT_AUTHORITY_UID
            or stat.S_IMODE(metadata.st_mode) & 0o022
        ):
            raise ProductionStageError("compose_source_git_untrusted")
    except SchemaV6AuthorityError as exc:
        raise ProductionStageError(str(exc)) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    return candidate_path


def _git_environment() -> dict[str, str]:
    """Return a fixed environment containing no inherited Git control input."""

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
    arguments: Sequence[str],
    *,
    binding: GitRepositoryBinding | None,
) -> list[str]:
    command = [str(_trusted_git_executable())]
    for key, value in GIT_FIXED_CONFIG:
        command.extend(("-c", f"{key}={value}"))
    if binding is None:
        command.extend(("-C", str(ROOT)))
    else:
        command.extend(
            (
                f"--git-dir={binding.git_dir}",
                f"--work-tree={binding.work_tree}",
            )
        )
    command.extend(arguments)
    return command


def _git_run(
    arguments: Sequence[str],
    *,
    reason: str,
    binding: GitRepositoryBinding | None = None,
) -> subprocess.CompletedProcess[bytes]:
    try:
        completed = subprocess.run(
            _git_command(arguments, binding=binding),
            check=False,
            capture_output=True,
            cwd="/",
            env=_git_environment(),
            stdin=subprocess.DEVNULL,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProductionStageError(reason) from exc
    return completed


def _git_output(
    arguments: Sequence[str],
    *,
    reason: str,
    binding: GitRepositoryBinding | None = None,
) -> bytes:
    completed = _git_run(arguments, reason=reason, binding=binding)
    if completed.returncode != 0:
        raise ProductionStageError(reason)
    return completed.stdout


def _decode_git_path(value: bytes, *, reason: str) -> Path:
    try:
        text = value.decode("utf-8", errors="strict").strip()
    except UnicodeDecodeError as exc:
        raise ProductionStageError(reason) from exc
    if not text or "\x00" in text or "\n" in text or "\r" in text:
        raise ProductionStageError(reason)
    candidate = Path(text)
    if not candidate.is_absolute():
        raise ProductionStageError(reason)
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise ProductionStageError(reason) from exc
    if resolved != candidate:
        raise ProductionStageError(reason)
    return candidate


def _repository_directory_identity(path: Path) -> tuple[int, int, int, int, int]:
    descriptor = -1
    try:
        descriptor = _open_absolute_nofollow(
            path,
            flags=os.O_RDONLY | os.O_DIRECTORY,
            reason="compose_source_repository",
            require_root_parents=False,
        )
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) & 0o002
        ):
            raise ProductionStageError("compose_source_repository_untrusted")
        return (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_mode,
            metadata.st_uid,
            metadata.st_gid,
        )
    except SchemaV6AuthorityError as exc:
        raise ProductionStageError(str(exc)) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _binding_value(
    arguments: Sequence[str],
    *,
    reason: str,
    binding: GitRepositoryBinding | None = None,
) -> str:
    raw = _git_output(arguments, reason=reason, binding=binding)
    try:
        value = raw.decode("ascii", errors="strict").strip()
    except UnicodeDecodeError as exc:
        raise ProductionStageError(reason) from exc
    if not value or "\n" in value or "\r" in value or "\x00" in value:
        raise ProductionStageError(reason)
    return value


def _assert_repository_binding(binding: GitRepositoryBinding) -> None:
    work_tree = _decode_git_path(
        _git_output(
            ["rev-parse", "--path-format=absolute", "--show-toplevel"],
            reason="compose_source_worktree_unavailable",
            binding=binding,
        ),
        reason="compose_source_worktree_unavailable",
    )
    git_dir = _decode_git_path(
        _git_output(
            ["rev-parse", "--path-format=absolute", "--git-dir"],
            reason="compose_source_git_dir_unavailable",
            binding=binding,
        ),
        reason="compose_source_git_dir_unavailable",
    )
    common_dir = _decode_git_path(
        _git_output(
            ["rev-parse", "--path-format=absolute", "--git-common-dir"],
            reason="compose_source_common_dir_unavailable",
            binding=binding,
        ),
        reason="compose_source_common_dir_unavailable",
    )
    head = _binding_value(
        ["rev-parse", "--verify", "HEAD^{commit}"],
        reason="compose_source_commit_unavailable",
        binding=binding,
    )
    if (
        work_tree != binding.work_tree
        or git_dir != binding.git_dir
        or common_dir != binding.common_dir
        or head != binding.head_commit
        or _repository_directory_identity(work_tree) != binding.work_tree_identity
        or _repository_directory_identity(git_dir) != binding.git_dir_identity
        or _repository_directory_identity(common_dir) != binding.common_dir_identity
    ):
        raise ProductionStageError("compose_source_repository_binding_changed")


def _require_no_repository_overrides(binding: GitRepositoryBinding) -> None:
    replacement_refs = _git_output(
        ["for-each-ref", "--format=%(refname)", "refs/replace"],
        reason="compose_source_replace_ref_check_failed",
        binding=binding,
    )
    if replacement_refs.strip():
        raise ProductionStageError("compose_source_replace_refs_present")
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
                raise ProductionStageError(
                    "compose_source_alternates_check_failed"
                ) from exc
            raise ProductionStageError("compose_source_alternates_present")


def _discover_repository_binding() -> GitRepositoryBinding:
    work_tree = _decode_git_path(
        _git_output(
            ["rev-parse", "--path-format=absolute", "--show-toplevel"],
            reason="compose_source_worktree_unavailable",
        ),
        reason="compose_source_worktree_unavailable",
    )
    git_dir = _decode_git_path(
        _git_output(
            ["rev-parse", "--path-format=absolute", "--git-dir"],
            reason="compose_source_git_dir_unavailable",
        ),
        reason="compose_source_git_dir_unavailable",
    )
    common_dir = _decode_git_path(
        _git_output(
            ["rev-parse", "--path-format=absolute", "--git-common-dir"],
            reason="compose_source_common_dir_unavailable",
        ),
        reason="compose_source_common_dir_unavailable",
    )
    head = _binding_value(
        ["rev-parse", "--verify", "HEAD^{commit}"],
        reason="compose_source_commit_unavailable",
    )
    if work_tree != ROOT or not REVISION_RE.fullmatch(head):
        raise ProductionStageError("compose_source_repository_binding_invalid")
    if common_dir != git_dir and common_dir not in git_dir.parents:
        raise ProductionStageError("compose_source_repository_binding_invalid")
    binding = GitRepositoryBinding(
        work_tree=work_tree,
        git_dir=git_dir,
        common_dir=common_dir,
        head_commit=head,
        work_tree_identity=_repository_directory_identity(work_tree),
        git_dir_identity=_repository_directory_identity(git_dir),
        common_dir_identity=_repository_directory_identity(common_dir),
    )
    _assert_repository_binding(binding)
    _require_no_repository_overrides(binding)
    return binding


def _require_clean_source_revision(
    expected_revision: str,
    *,
    binding: GitRepositoryBinding,
) -> None:
    _assert_repository_binding(binding)
    if binding.head_commit != expected_revision:
        raise ProductionStageError("compose_source_commit_mismatch")
    for arguments in (
        [
            "diff",
            "--quiet",
            "--no-ext-diff",
            "--no-textconv",
            expected_revision,
            "--",
        ],
        [
            "diff",
            "--cached",
            "--quiet",
            "--no-ext-diff",
            "--no-textconv",
            expected_revision,
            "--",
        ],
    ):
        completed = _git_run(
            arguments,
            reason="compose_source_cleanliness_unavailable",
            binding=binding,
        )
        if completed.returncode != 0:
            raise ProductionStageError("compose_source_worktree_not_clean")


def _committed_blob(
    binding: GitRepositoryBinding,
    expected_revision: str,
    relative_path: Path,
) -> bytes:
    return _git_output(
        ["cat-file", "blob", f"{expected_revision}:{relative_path.as_posix()}"],
        reason="compose_source_blob_unavailable",
        binding=binding,
    )


def _discover_compose_source_inventory(
    expected_revision: str,
) -> tuple[list[dict[str, str]], str]:
    if not REVISION_RE.fullmatch(expected_revision):
        raise ProductionStageError("compose_source_revision_invalid")
    binding = _discover_repository_binding()
    _require_clean_source_revision(expected_revision, binding=binding)
    inventory: list[dict[str, str]] = []
    for relative_path in COMPOSE_SOURCE_PATHS:
        blob = _committed_blob(binding, expected_revision, relative_path)
        working = _read_repository_file(ROOT / relative_path)
        blob_sha256 = hashlib.sha256(blob).hexdigest()
        working_sha256 = hashlib.sha256(working).hexdigest()
        if working_sha256 != blob_sha256:
            raise ProductionStageError("compose_source_working_blob_mismatch")
        inventory.append(
            {
                "path": relative_path.as_posix(),
                "blob_sha256": blob_sha256,
                "working_sha256": working_sha256,
            }
        )
    final_binding = _discover_repository_binding()
    if final_binding != binding:
        raise ProductionStageError("compose_source_repository_binding_changed")
    _require_clean_source_revision(expected_revision, binding=final_binding)
    for relative_path, entry in zip(COMPOSE_SOURCE_PATHS, inventory):
        final_blob_sha256 = hashlib.sha256(
            _committed_blob(final_binding, expected_revision, relative_path)
        ).hexdigest()
        final_working_sha256 = hashlib.sha256(
            _read_repository_file(ROOT / relative_path)
        ).hexdigest()
        if (
            final_blob_sha256 != entry["blob_sha256"]
            or final_working_sha256 != entry["working_sha256"]
            or final_blob_sha256 != final_working_sha256
        ):
            raise ProductionStageError("compose_source_changed_during_snapshot")
    return inventory, _canonical_sha256(inventory)


def _revalidate_compose_source_inventory(
    expected_revision: str,
    inventory: Sequence[Mapping[str, Any]],
    inventory_sha256: str,
) -> None:
    issues = _validate_source_inventory(
        list(inventory),
        expected_paths=COMPOSE_SOURCE_PATHS,
        inventory_sha256=inventory_sha256,
        reason="preflight:compose_source",
    )
    if issues:
        raise ProductionStageError("compose_source_inventory_revalidation_failed")
    binding = _discover_repository_binding()
    _require_clean_source_revision(expected_revision, binding=binding)
    for relative_path, entry in zip(COMPOSE_SOURCE_PATHS, inventory):
        blob_sha256 = hashlib.sha256(
            _committed_blob(binding, expected_revision, relative_path)
        ).hexdigest()
        working_sha256 = hashlib.sha256(
            _read_repository_file(ROOT / relative_path)
        ).hexdigest()
        if (
            blob_sha256 != entry.get("blob_sha256")
            or working_sha256 != entry.get("working_sha256")
            or blob_sha256 != working_sha256
        ):
            raise ProductionStageError("compose_source_inventory_revalidation_failed")
    final_binding = _discover_repository_binding()
    if final_binding != binding:
        raise ProductionStageError("compose_source_repository_binding_changed")
    _require_clean_source_revision(expected_revision, binding=final_binding)


def _write_receipt(path: Path, payload: Mapping[str, Any]) -> None:
    if not path.is_absolute() or path.name in {"", ".", ".."}:
        raise ProductionStageError("receipt_path_invalid")
    serialized = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    parent_descriptor = -1
    output_descriptor = -1
    temporary_name = f".{path.name}.{secrets.token_hex(16)}.tmp"
    try:
        parent_descriptor = _open_absolute_nofollow(
            path.parent,
            flags=os.O_RDONLY | os.O_DIRECTORY,
            reason="receipt_parent",
            require_root_parents=False,
        )
        parent_metadata = os.fstat(parent_descriptor)
        if (
            not stat.S_ISDIR(parent_metadata.st_mode)
            or parent_metadata.st_uid != os.getuid()
            or stat.S_IMODE(parent_metadata.st_mode) != 0o700
        ):
            raise ProductionStageError("receipt_parent_untrusted")
        output_descriptor = os.open(
            temporary_name,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | os.O_CLOEXEC
            | os.O_NOFOLLOW,
            0o600,
            dir_fd=parent_descriptor,
        )
        handle = os.fdopen(output_descriptor, "w", encoding="utf-8")
        output_descriptor = -1
        with handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(
            temporary_name,
            path.name,
            src_dir_fd=parent_descriptor,
            dst_dir_fd=parent_descriptor,
        )
        os.fsync(parent_descriptor)
    except ProductionStageError:
        raise
    except SchemaV6AuthorityError as exc:
        raise ProductionStageError(str(exc)) from exc
    except OSError as exc:
        raise ProductionStageError("receipt_write_failed") from exc
    finally:
        if output_descriptor >= 0:
            os.close(output_descriptor)
        try:
            if parent_descriptor >= 0:
                os.unlink(temporary_name, dir_fd=parent_descriptor)
        except OSError:
            pass
        if parent_descriptor >= 0:
            os.close(parent_descriptor)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-compose-json", required=True)
    parser.add_argument("--staged-compose-json", required=True)
    parser.add_argument("--expected-revision", required=True)
    parser.add_argument("--expected-image", required=True)
    parser.add_argument("--expected-image-id", required=True)
    parser.add_argument("--compose-version", required=True)
    parser.add_argument("--memorial-baseline-receipt", required=True)
    parser.add_argument("--provenance", required=True)
    parser.add_argument("--sbom", required=True)
    parser.add_argument("--sentinel-state", required=True)
    parser.add_argument("--sentinel-owner-uid", type=int, required=True)
    parser.add_argument("--schema-v6-permit", required=True)
    parser.add_argument("--receipt", default="")
    args = parser.parse_args(argv)
    try:
        now = _utc_now()
        baseline, _ = _read_private_json(
            Path(args.baseline_compose_json),
            max_bytes=MAX_PRIVATE_INPUT_BYTES,
            reason="baseline_compose",
        )
        staged, _ = _read_private_json(
            Path(args.staged_compose_json),
            max_bytes=MAX_PRIVATE_INPUT_BYTES,
            reason="staged_compose",
        )
        memorial_baseline, memorial_baseline_sha256 = read_trusted_json(
            Path(args.memorial_baseline_receipt),
            expected_uid=ROOT_AUTHORITY_UID,
            expected_mode=0o644,
            max_bytes=MAX_MEMORIAL_BASELINE_BYTES,
            reason="memorial_baseline_receipt",
        )
        provenance, provenance_sha256 = _read_private_json(
            Path(args.provenance),
            max_bytes=MAX_PRIVATE_INPUT_BYTES,
            reason="provenance",
        )
        sbom, sbom_sha256 = _read_private_json(
            Path(args.sbom), max_bytes=MAX_PRIVATE_INPUT_BYTES, reason="sbom"
        )
        qualification = load_schema_v6_qualification(
            state_path=Path(args.sentinel_state),
            state_owner_uid=int(args.sentinel_owner_uid),
            permit_path=Path(args.schema_v6_permit),
            now=now,
        )
        source_inventory, source_inventory_sha256 = (
            _discover_compose_source_inventory(str(args.expected_revision))
        )
        result = verify_audiobook_runtime_production_stage(
            baseline,
            staged,
            expected_revision=str(args.expected_revision),
            expected_image=str(args.expected_image),
            expected_image_id=str(args.expected_image_id),
            source_commit=str(args.expected_revision),
            compose_source_inventory=source_inventory,
            compose_source_inventory_sha256=source_inventory_sha256,
            compose_version=str(args.compose_version),
            memorial_baseline_receipt=memorial_baseline,
            memorial_baseline_receipt_sha256=memorial_baseline_sha256,
            provenance=provenance,
            provenance_sha256=provenance_sha256,
            sbom=sbom,
            sbom_sha256=sbom_sha256,
            qualification=qualification,
            now=now,
        )
        if result.get("status") == "prepared":
            _revalidate_compose_source_inventory(
                str(args.expected_revision),
                source_inventory,
                source_inventory_sha256,
            )
        if args.receipt:
            _write_receipt(Path(args.receipt), result)
    except (ProductionStageError, SchemaV6AuthorityError, ValueError) as exc:
        safe_reason = (
            str(exc)
            if isinstance(exc, (ProductionStageError, SchemaV6AuthorityError))
            else type(exc).__name__
        )
        result = {
            "contract_name": ROOT_CONTRACT,
            "version": 1,
            "status": "blocked",
            "verification_mode": "prepare",
            "verified_at": _utc_text(_utc_now()),
            "mutations_performed": 0,
            "preparation_valid": False,
            "non_transferable": True,
            "deploy_ready": False,
            "deployment_scope": DEPLOYMENT_SCOPE,
            "stage_deploy_eligible": False,
            "stage_mutation_authority": False,
            "deployment_authority": False,
            "group_deploy_eligible": False,
            "runtime_activation_authority": False,
            "queue_mutation_authority": False,
            "provider_work_authority": False,
            "outbound_send_authority": False,
            "build_authority": False,
            "pull_authority": False,
            "issues": [f"preflight_input:{safe_reason}"],
            "next_action": "repair_preflight_input_without_mutating_runtime",
        }
        if args.receipt:
            try:
                _write_receipt(Path(args.receipt), result)
            except ProductionStageError:
                pass
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") == "prepared" else 1


if __name__ == "__main__":
    raise SystemExit(main())
