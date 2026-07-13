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
import json
import os
import re
import stat
import subprocess  # nosec B404 - commands are fixed below
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence

try:
    from scripts.source_state_head import source_worktree_metadata
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from source_state_head import source_worktree_metadata


ROOT = Path(__file__).resolve().parents[1]
MEMORIAL_COMPOSE_FILE = "docker-compose.memorial.yml"
PROJECT_NAME = "ea"
API_SERVICE = "ea-api"
REDIS_SERVICE = "ea-redis"
MEMORIAL_SLUG = "manfred"
CONTROL_TOUR_SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,127}$")
DEPLOYMENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
IMAGE_ID_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
SHA256_HEX_PATTERN = re.compile(r"^[0-9a-f]{64}$")
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
MAX_HTTP_BODY_BYTES = 2 * 1024 * 1024


class DeployError(RuntimeError):
    """A fail-closed deployment or verification error."""


@dataclass(frozen=True)
class HttpResponse:
    status: int
    content_type: str
    body: bytes
    source_revision: str = ""


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
    ) -> subprocess.CompletedProcess[str]:
        completed = subprocess.run(  # nosec B603 - fixed executable/arguments
            list(args),
            cwd=cwd,
            env=dict(env),
            check=False,
            capture_output=True,
            text=True,
        )
        if check and completed.returncode != 0:
            executable = Path(str(args[0] or "command")).name or "command"
            if executable.startswith("python") and len(args) > 1:
                executable = f"{executable}:{Path(str(args[1])).name}"
            raise DeployError(f"command_failed:{completed.returncode}:{executable}")
        return completed


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


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
        identities.append(
            {
                "type": str(raw_mount.get("Type") or ""),
                "source": str(raw_mount.get("Source") or ""),
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


def _default_http_get(url: str, timeout_seconds: float) -> HttpResponse:
    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
            "User-Agent": "EA-Memorial-Scoped-Deploy/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
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
            )
    except urllib.error.HTTPError as exc:
        raise DeployError(f"http_status_invalid:{url}:{int(exc.code or 0)}") from exc
    except (OSError, urllib.error.URLError) as exc:
        raise DeployError(f"http_probe_failed:{url}:{type(exc).__name__}") from exc


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
        runner: Runner | None = None,
        http_get: Callable[[str, float], HttpResponse] = _default_http_get,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        wait_seconds: float = 90.0,
        poll_seconds: float = 2.0,
        request_timeout_seconds: float = 10.0,
        receipt_dir: Path | None = None,
        global_lock_path: Path | None = None,
        durable_root_check: Callable[[Path], None] = _require_durable_release_root,
    ) -> None:
        self.root = root.resolve()
        self.env = dict(os.environ if env is None else env)
        self.runner = runner or SubprocessRunner()
        self.http_get = http_get
        self.sleep = sleep
        self.monotonic = monotonic
        self.wait_seconds = max(float(wait_seconds), 0.0)
        self.poll_seconds = max(float(poll_seconds), 0.05)
        self.request_timeout_seconds = max(float(request_timeout_seconds), 0.1)
        self.durable_root_check = durable_root_check
        self.env_file_values = _parse_env_file(self.root / ".env")
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
        self.receipt_path = self.receipt_dir / f"{self.deployment_id}.json"
        self.lock_path = self.receipt_dir / f"{self.deployment_id}.lock"
        self.global_lock_path = (
            global_lock_path.resolve()
            if global_lock_path is not None
            else Path("/run/lock/ea-memorial-ea-api.lock")
        )
        if not self.global_lock_path.is_absolute():
            raise DeployError("global_lock_path_not_absolute")
        self._lock_handle: Any | None = None
        self._global_lock_handle: Any | None = None
        self.compose_bin: tuple[str, ...] = ()
        self.target_compose_files: tuple[str, ...] = ()
        self.release_env = self._release_env()
        self.receipt: dict[str, Any] = {
            "contract_name": "ea.memorial_scoped_deploy_receipt.v1",
            "deployment_id": self.deployment_id,
            "project_name": PROJECT_NAME,
            "service_scope": [API_SERVICE, REDIS_SERVICE],
            "api_mutation_scope": [API_SERVICE],
            "target_compose_files": [],
            "rollback_compose_files": [],
            "started_at": _utc_now(),
            "status": "preflight",
            "rollback": {"status": "not_required"},
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
        self.receipt_dir.mkdir(parents=True, exist_ok=True)
        try:
            self.receipt_dir.chmod(0o700)
        except OSError:
            pass
        payload = json.dumps(self.receipt, indent=2, sort_keys=True) + "\n"
        temporary = self.receipt_path.with_name(
            f".{self.receipt_path.name}.tmp.{os.getpid()}"
        )
        temporary.write_text(payload, encoding="utf-8")
        temporary.chmod(0o600)
        os.replace(temporary, self.receipt_path)

    def _open_lock(self, path: Path, *, busy_reason: str) -> Any:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        flags = os.O_RDWR | os.O_CREAT | os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(path, flags, 0o600)
        except OSError as exc:
            raise DeployError(f"lock_file_unavailable:{path.name}") from exc
        handle = os.fdopen(descriptor, "a+", encoding="utf-8")
        os.fchmod(handle.fileno(), 0o600)
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            handle.close()
            raise DeployError(busy_reason) from exc
        handle.seek(0)
        handle.truncate()
        handle.write(f"pid={os.getpid()}\n")
        handle.flush()
        return handle

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

    def _record_check(self, name: str, status: str, **detail: object) -> None:
        checks = list(self.receipt.get("checks") or [])
        checks.append({"name": name, "status": status, **detail})
        self.receipt["checks"] = checks
        self._write_receipt()

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
            cwd=(cwd or self.root),
            env=(self.release_env if env is None else env),
            check=check,
        )

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

    def _compose_args(self, *, root: Path, files: Sequence[str]) -> list[str]:
        if not self.compose_bin:
            raise DeployError("docker_compose_unavailable")
        env_file = root / ".env"
        if not env_file.is_file():
            raise DeployError(f"env_file_missing:{env_file}")
        args = [
            *self.compose_bin,
            "--project-name",
            PROJECT_NAME,
            "--project-directory",
            str(root),
            "--env-file",
            str(env_file),
        ]
        for filename in files:
            path = root / filename
            if not path.is_file():
                raise DeployError(f"compose_file_missing:{path}")
            args.extend(["-f", str(path)])
        return args

    def _target_compose(self, *args: str) -> list[str]:
        if not self.target_compose_files:
            raise DeployError("forward_compose_topology_unresolved")
        return [
            *self._compose_args(root=self.root, files=self.target_compose_files),
            *args,
        ]

    def _configure_forward_topology(self, previous: Mapping[str, Any]) -> None:
        prior_root = Path(str(previous.get("working_dir") or "")).resolve()
        prior_files = [
            Path(str(item)).resolve()
            for item in list(previous.get("compose_config_files") or [])
            if str(item).strip()
        ]
        if not prior_files:
            raise DeployError("forward_baseline_compose_files_missing")

        release_files: list[str] = []
        seen: set[str] = set()
        for prior_file in prior_files:
            try:
                relative = prior_file.relative_to(prior_root)
            except ValueError as exc:
                raise DeployError(
                    f"forward_baseline_compose_file_unmappable:{prior_file}"
                ) from exc
            relative_name = relative.as_posix()
            if relative.name == MEMORIAL_COMPOSE_FILE:
                raise DeployError("forward_baseline_already_contains_memorial")
            if relative_name in seen:
                raise DeployError("forward_baseline_compose_file_duplicate")
            release_file = (self.root / relative).resolve()
            try:
                release_file.relative_to(self.root)
            except ValueError as exc:
                raise DeployError(
                    f"forward_release_compose_file_escapes_root:{release_file}"
                ) from exc
            if not release_file.is_file():
                raise DeployError(
                    f"forward_release_compose_file_missing:{release_file}"
                )
            seen.add(relative_name)
            release_files.append(relative_name)

        memorial_path = (self.root / MEMORIAL_COMPOSE_FILE).resolve()
        if not memorial_path.is_file():
            raise DeployError(f"forward_memorial_compose_file_missing:{memorial_path}")
        release_files.append(MEMORIAL_COMPOSE_FILE)
        self.target_compose_files = tuple(release_files)
        self.release_env["EA_DEPLOY_COMPOSE_FILES"] = ",".join(release_files)
        self.receipt["target_compose_files"] = release_files
        self.receipt["forward_topology_source"] = {
            "working_dir": str(prior_root),
            "compose_config_files": [str(path) for path in prior_files],
            "mapping": "baseline_relative_paths_rebased_to_release_root_plus_memorial",
        }
        self._write_receipt()

    def _rollback_compose(
        self, root: Path, files: Sequence[str], *args: str
    ) -> list[str]:
        return [*self._compose_args(root=root, files=files), *args]

    def _rollback_environment(self) -> dict[str, str]:
        return {
            key: value
            for key, value in self.env.items()
            if key in ROLLBACK_ENV_PASSTHROUGH and key not in FORWARD_ONLY_ENV_KEYS
        }

    def _run_json_script(self, script: str, *args: str) -> dict[str, Any]:
        completed = self._run([sys.executable, str(self.root / script), *args])
        return _json_object(completed.stdout, reason=f"script_json_invalid:{script}")

    def _materialize_and_verify_release_evidence(self) -> dict[str, Any]:
        for script in (
            "scripts/materialize_deploy_context.py",
            "scripts/materialize_release_manifest.py",
            "scripts/materialize_release_authority_status.py",
            "scripts/materialize_memorial_operator_status.py",
        ):
            self._run([sys.executable, str(self.root / script)])

        authority = self._run_json_script(
            "scripts/verify_release_authority.py", "--pretty"
        )
        if str(authority.get("contract_name") or "") != "ea.release_authority_gate.v1":
            raise DeployError("release_authority_contract_invalid")
        if str(authority.get("status") or "").lower() != "pass":
            raise DeployError("release_authority_not_pass")
        if bool(authority.get("source_worktree_dirty")):
            raise DeployError("release_authority_source_worktree_dirty")
        if str(authority.get("deployment_id") or "") != self.deployment_id:
            raise DeployError("release_authority_deployment_id_mismatch")
        if str(authority.get("project_mode") or "").upper() != "MEMORIAL":
            raise DeployError("release_authority_project_mode_mismatch")

        readiness = self._run_json_script(
            "scripts/verify_memorial_deploy_readiness.py", "--pretty"
        )
        if (
            str(readiness.get("contract_name") or "")
            != "ea.memorial_deploy_readiness.v1"
        ):
            raise DeployError("memorial_deploy_readiness_contract_invalid")
        if str(readiness.get("status") or "").lower() != "pass":
            raise DeployError("memorial_deploy_readiness_not_pass")
        self._record_check("release_authority", "pass")
        self._record_check("memorial_deploy_readiness", "pass")
        return authority

    def _validate_compose(self, *, candidate: Mapping[str, Any]) -> None:
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
        )

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
        inspection: Mapping[str, Any], *, reason_prefix: str
    ) -> dict[str, Any]:
        labels = dict(dict(inspection.get("Config") or {}).get("Labels") or {})
        raw_working_dir = str(
            labels.get("com.docker.compose.project.working_dir") or ""
        ).strip()
        if not raw_working_dir:
            raise DeployError(f"{reason_prefix}_compose_working_dir_missing")
        working_dir = Path(raw_working_dir).expanduser()
        if not working_dir.is_absolute():
            raise DeployError(f"{reason_prefix}_working_dir_invalid")
        working_dir = working_dir.resolve()
        raw_config_files = str(
            labels.get("com.docker.compose.project.config_files") or ""
        ).strip()
        if not raw_config_files:
            raise DeployError(f"{reason_prefix}_compose_config_files_missing")
        compose_files: list[str] = []
        for raw_path in raw_config_files.split(","):
            candidate = Path(raw_path.strip()).expanduser()
            if not candidate.is_absolute():
                candidate = working_dir / candidate
            candidate = candidate.resolve()
            if not candidate.is_file():
                raise DeployError(f"{reason_prefix}_rollback_input_missing")
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

    def _verify_rollback_renderability(
        self, previous: Mapping[str, Any]
    ) -> dict[str, Any]:
        rollback_root = Path(str(previous.get("working_dir") or "")).resolve()
        rollback_files = [
            str(item)
            for item in list(previous.get("compose_config_files") or [])
            if str(item).strip()
        ]
        rollback_env = self._rollback_environment()
        rendered = _json_object(
            self._run(
                self._rollback_compose(
                    rollback_root,
                    rollback_files,
                    "config",
                    "--format",
                    "json",
                ),
                cwd=rollback_root,
                env=rollback_env,
            ).stdout,
            reason="rollback_render_json_invalid",
        )
        if rendered.get("name") not in {None, PROJECT_NAME}:
            raise DeployError("rollback_render_project_mismatch")
        services_value = rendered.get("services")
        services = dict(services_value) if isinstance(services_value, dict) else {}
        service_value = services.get(API_SERVICE)
        service = dict(service_value) if isinstance(service_value, dict) else {}
        if not service:
            raise DeployError("rollback_render_api_missing")
        if str(service.get("image") or "") != str(
            previous.get("image_reference") or ""
        ):
            raise DeployError("rollback_render_image_reference_mismatch")
        image = self._inspect_image_config(str(previous.get("image_reference") or ""))
        if image["image_id"] != str(previous.get("image_id") or ""):
            raise DeployError("rollback_render_image_id_mismatch")
        image_config = dict(image["config"])
        expected_environment = _environment_identity(
            self._rendered_environment_entries(service, image_config)
        )
        if expected_environment["environment_sha256"] != previous.get(
            "environment_sha256"
        ) or expected_environment["environment_count"] != previous.get(
            "environment_count"
        ):
            raise DeployError("rollback_render_environment_identity_mismatch")
        process_digest = _process_config_identity(
            self._rendered_process_config(service, image_config)
        )
        if process_digest != previous.get("process_config_sha256"):
            raise DeployError("rollback_render_process_config_identity_mismatch")
        mounts = self._rendered_mount_identities(rendered, service, root=rollback_root)
        mount_digest = _identity_digest(mounts)
        if mount_digest != previous.get("mount_identity_sha256"):
            raise DeployError("rollback_render_mount_identity_mismatch")
        evidence = {
            "status": "pass",
            "working_dir": str(rollback_root),
            "compose_config_files": rollback_files,
            "image_id": str(previous.get("image_id") or ""),
            "image_reference": str(previous.get("image_reference") or ""),
            **expected_environment,
            "process_config_sha256": process_digest,
            "mount_identity_sha256": mount_digest,
            "mount_identity_count": len(mounts),
        }
        self.receipt["rollback_render_preflight"] = evidence
        self._record_check("rollback_render_preflight", "pass")
        return evidence

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
            "./memorial_data",
        )
        expected_data_root = Path(configured_data_root).expanduser()
        if not expected_data_root.is_absolute():
            expected_data_root = self.root / expected_data_root
        return expected_data_root.resolve()

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

        def openapi_snapshot(name: str) -> dict[str, Any]:
            value = openapi.get(name)
            return dict(value) if isinstance(value, dict) else {}

        live_openapi_before = openapi_snapshot("live_before")
        candidate_openapi = openapi_snapshot("candidate")
        live_openapi_after = openapi_snapshot("live_after")

        def valid_openapi_snapshot(value: Mapping[str, Any]) -> bool:
            return (
                set(value) == OPENAPI_EVIDENCE_FIELDS
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
        if (
            str(payload.get("schema") or "")
            != "ea.manfred_memorial_candidate_runtime.v3"
            or str(payload.get("status") or "").lower() != "pass"
            or str(payload.get("image") or "") != str(candidate.get("reference") or "")
            or str(payload.get("image_id") or "")
            != str(candidate.get("image_id") or "")
            or str(payload.get("image_source_revision") or "") != source_revision
            or payload.get("image_locator_only") is not True
            or locator
            != {
                "locator": str(candidate.get("reference") or ""),
                "resolved_image_id": str(candidate.get("image_id") or ""),
                "revision_label": source_revision,
                "locator_only": True,
            }
            or str(payload.get("runtime_source_revision") or "") != source_revision
            or payload.get("runtime_revision_matches_image") is not True
            or str(payload.get("projection_commit") or "") != source_revision
            or str(payload.get("prepared_image_locator") or "")
            != str(candidate.get("reference") or "")
            or str(payload.get("prepared_image_id") or "")
            != str(candidate.get("image_id") or "")
            or payload.get("projection_tree_revalidated") is not True
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
            or named_resources != expected_named_resources
            or payload.get("api_network_internal") is not True
            or payload.get("gateway_has_runtime_secrets") is not False
            or payload.get("provider_credentials_present") is not False
            or not str(payload.get("candidate_api_container_id") or "").strip()
            or payload.get("candidate_api_container_id")
            != candidate_api_image.get("container_id")
            or payload.get("candidate_left_running_for_soak") is not True
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
            or openapi.get("candidate_preserves_live_contract") is not True
            or type(openapi.get("missing_or_changed_operation_count")) is not int
            or openapi["missing_or_changed_operation_count"] != 0
            or type(openapi.get("missing_or_changed_schema_count")) is not int
            or openapi["missing_or_changed_schema_count"] != 0
            or type(openapi.get("missing_or_changed_security_scheme_count")) is not int
            or openapi["missing_or_changed_security_scheme_count"] != 0
            or not valid_openapi_snapshot(live_openapi_before)
            or not valid_openapi_snapshot(candidate_openapi)
            or not valid_openapi_snapshot(live_openapi_after)
            or live_openapi_before != live_openapi_after
            or int(candidate_openapi.get("path_count") or 0)
            < int(live_openapi_before.get("path_count") or 0)
            or int(candidate_openapi.get("operation_count") or 0)
            < int(live_openapi_before.get("operation_count") or 0)
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
        evidence = {
            "path": str(path),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "schema": "ea.manfred_memorial_candidate_runtime.v3",
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
                "projection_sha256": str(payload.get("projection_sha256") or ""),
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
            key: value for key, value in previous.items() if key != "mount_identities"
        }

    def _verify_forward_api(
        self,
        *,
        candidate: Mapping[str, Any],
        source_revision: str,
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
        actual_mounts = {
            (
                str(item["type"]),
                str(Path(str(item["source"])).resolve()),
                str(item["destination"]),
                bool(item["read_write"]),
            )
            for item in mount_identities
        }
        expected_mounts = {
            ("bind", str((self.root / "ea" / "app").resolve()), "/app/app", False),
            ("bind", str((self.root / "scripts").resolve()), "/app/scripts", False),
            (
                "bind",
                str(self._configured_memorial_data_root()),
                "/data/memorial_data",
                False,
            ),
        }
        if not expected_mounts <= actual_mounts:
            raise DeployError("deployed_api_source_mounts_mismatch")
        return {
            "image_id": image_id,
            "image_reference": str(candidate.get("reference") or ""),
            "working_dir": topology["working_dir"],
            "compose_config_files": topology["compose_config_files"],
            "mount_identity_sha256": _identity_digest(mount_identities),
            "mount_identity_count": len(mount_identities),
            "source_mount_destinations": sorted(item[2] for item in expected_mounts),
            "source_revision": source_revision,
            **_container_runtime_config_digests(inspection),
        }

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
        state = dict(inspection.get("State") or {})
        health = str(dict(state.get("Health") or {}).get("Status") or "")
        if (
            not bool(state.get("Running"))
            or bool(state.get("Restarting"))
            or health != "healthy"
        ):
            raise DeployError("prior_api_not_healthy")
        topology = self._compose_topology(inspection, reason_prefix="prior_api")
        working_dir = Path(str(topology["working_dir"]))
        env_path = working_dir / ".env"
        if not env_path.is_file():
            raise DeployError(f"prior_api_rollback_input_missing:{env_path}")
        mount_identities = _mount_identities(inspection)
        runtime_config = _container_runtime_config_digests(inspection)
        return {
            "container_id": str(inspection.get("Id") or ""),
            "created_at": str(inspection.get("Created") or ""),
            "image_id": image_id,
            "image_reference": image_reference,
            "working_dir": str(working_dir),
            "compose_config_files": topology["compose_config_files"],
            "mount_identities": mount_identities,
            "mount_identity_sha256": _identity_digest(mount_identities),
            "mount_identity_count": len(mount_identities),
            **runtime_config,
            "state": {
                "running": bool(state.get("Running")),
                "restarting": bool(state.get("Restarting")),
                "started_at": str(state.get("StartedAt") or ""),
                "health": health,
            },
        }

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
            if self.monotonic() >= deadline:
                raise DeployError(
                    f"container_not_ready:{name}:{json.dumps(last_detail, sort_keys=True)}"
                )
            self.sleep(self.poll_seconds)

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
        self, url: str, *, kind: str, expected_source_revision: str = ""
    ) -> dict[str, Any]:
        deadline = self.monotonic() + self.wait_seconds
        last_error = ""
        while True:
            try:
                response = self.http_get(url, self.request_timeout_seconds)
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
                    "content_type": response.content_type,
                    "body_bytes": len(response.body),
                    "body_sha256": hashlib.sha256(response.body).hexdigest(),
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

    @staticmethod
    def _sanitized_openapi_control(control: Mapping[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in control.items() if key != "_contract"}

    def _capture_non_memorial_controls(self) -> dict[str, Any]:
        controls: dict[str, Any] = {"openapi": self._capture_openapi_control()}
        predeploy_operations = dict(
            dict(controls["openapi"].get("_contract") or {}).get("operations") or {}
        )
        if not set(OPENAPI_RETIREMENT_ALLOWED_OPERATIONS) <= set(predeploy_operations):
            raise DeployError("predeploy_openapi_retirement_operations_missing")
        if self.control_tour_slug:
            base = f"{self._local_origin()}/tours/{self.control_tour_slug}"
            html = self._wait_http(base, kind="control_html")
            _payload, tour_json = self._wait_json_control(f"{base}.json")
            controls["tour"] = {
                "slug": self.control_tour_slug,
                "html": html,
                "json": tour_json,
            }
        receipt_controls = {
            **controls,
            "openapi": self._sanitized_openapi_control(controls["openapi"]),
        }
        receipt_controls["openapi"]["retirement_policy_id"] = (
            OPENAPI_RETIREMENT_POLICY_ID
        )
        receipt_controls["openapi"]["retirement_allowed_operations"] = list(
            OPENAPI_RETIREMENT_ALLOWED_OPERATIONS
        )
        self.receipt["predeploy_non_memorial_controls"] = receipt_controls
        self._record_check(
            "predeploy_non_memorial_controls",
            "pass",
            openapi_path_count=controls["openapi"]["path_count"],
            tour_slug=self.control_tour_slug or None,
        )
        return controls

    def _verify_non_memorial_controls(self, baseline: Mapping[str, Any]) -> None:
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
        current_openapi = self._capture_openapi_control()
        current_contract = dict(current_openapi.get("_contract") or {})
        current_operations = dict(current_contract.get("operations") or {})
        current_schemas = dict(current_contract.get("schemas") or {})
        current_security = dict(current_contract.get("security_schemes") or {})
        missing_operations = sorted(set(prior_operations) - set(current_operations))
        if missing_operations != list(OPENAPI_RETIREMENT_ALLOWED_OPERATIONS):
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
        changed_operations = sorted(
            name
            for name, value in prior_operations.items()
            if name in current_operations and current_operations[name] != value
        )
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
            _payload, tour_json = self._wait_json_control(f"{base}.json")
            prior_json = dict(prior_tour.get("json") or {})
            if tour_json["body_sha256"] != prior_json.get("body_sha256"):
                raise DeployError("postdeploy_control_tour_json_changed")
            evidence["tour"] = {"slug": slug, "html": html, "json": tour_json}

        self.receipt["postdeploy_non_memorial_controls"] = evidence
        self._record_check(
            "postdeploy_non_memorial_controls",
            "pass",
            openapi_path_count=current_openapi["path_count"],
            tour_slug=self.control_tour_slug or None,
        )

    def _verify_deployed_surface(
        self, public_origin: str, *, source_revision: str
    ) -> None:
        local = self._local_origin()
        probes = [
            self._wait_http(f"{local}/health", kind="health"),
            self._wait_http(
                f"{local}/memorials/{MEMORIAL_SLUG}",
                kind="html",
                expected_source_revision=source_revision,
            ),
            self._wait_http(
                f"{local}/memorials/{MEMORIAL_SLUG}.json",
                kind="json",
                expected_source_revision=source_revision,
            ),
            self._wait_http(
                f"{public_origin}/memorials/{MEMORIAL_SLUG}",
                kind="html",
                expected_source_revision=source_revision,
            ),
            self._wait_http(
                f"{public_origin}/memorials/{MEMORIAL_SLUG}.json",
                kind="json",
                expected_source_revision=source_revision,
            ),
        ]
        if probes[2]["body_sha256"] != probes[4]["body_sha256"]:
            raise DeployError("public_memorial_manifest_differs_from_local")
        self.receipt["probes"] = probes
        self._record_check("local_and_public_memorial", "pass")

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
        )
        required_checks = {
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
        evidence = [
            self._verify_candidate_origin(
                label="local",
                base_url=self._local_origin(),
                public_origin=public_origin,
            ),
            self._verify_candidate_origin(
                label="public",
                base_url=public_origin,
                public_origin=public_origin,
            ),
        ]
        self.receipt["candidate_verifier"] = evidence
        self._record_check("local_and_public_candidate_verifier", "pass")

    def _rollback(
        self,
        previous: Mapping[str, Any],
        rollback_tag: str,
        baseline: Mapping[str, Any],
    ) -> dict[str, Any]:
        prior_openapi_value = baseline.get("openapi")
        prior_openapi = (
            dict(prior_openapi_value) if isinstance(prior_openapi_value, dict) else {}
        )
        prior_contract_value = prior_openapi.get("_contract")
        prior_contract = (
            dict(prior_contract_value) if isinstance(prior_contract_value, dict) else {}
        )
        prior_operations = dict(prior_contract.get("operations") or {})
        if not prior_operations or not set(
            OPENAPI_RETIREMENT_ALLOWED_OPERATIONS
        ) <= set(prior_operations):
            raise DeployError("rollback_openapi_baseline_invalid")
        rollback_root = Path(str(previous["working_dir"])).resolve()
        rollback_files = [
            str(item).strip()
            for item in list(previous.get("compose_config_files") or [])
            if str(item).strip()
        ]
        if not rollback_files:
            raise DeployError("rollback_compose_config_files_missing")
        protected = self._inspect_image(rollback_tag)
        if protected["image_id"] != str(previous["image_id"]):
            raise DeployError("rollback_protected_image_mismatch")
        prior_reference = _safe_tagged_image_reference(
            str(previous.get("image_reference") or ""),
            reason="rollback_image_reference_unrestorable",
        )
        rollback_env = self._rollback_environment()
        self._run(
            ["docker", "image", "tag", str(previous["image_id"]), prior_reference],
            env=rollback_env,
        )
        self._run(
            self._rollback_compose(
                rollback_root,
                rollback_files,
                "up",
                "-d",
                "--no-build",
                "--no-deps",
                "--force-recreate",
                API_SERVICE,
            ),
            cwd=rollback_root,
            env=rollback_env,
        )
        ready = self._wait_container(API_SERVICE, require_health=True)
        current = self._inspect_container(API_SERVICE)
        self._require_compose_identity(
            current, service=API_SERVICE, reason_prefix="rollback_api"
        )
        topology = self._compose_topology(current, reason_prefix="rollback_api")
        restored_image_id = str(current.get("Image") or "")
        if restored_image_id != str(previous["image_id"]):
            raise DeployError("rollback_image_mismatch")
        restored_reference = str(
            dict(current.get("Config") or {}).get("Image") or ""
        ).strip()
        if restored_reference != prior_reference:
            raise DeployError("rollback_image_reference_mismatch")
        if topology["working_dir"] != str(rollback_root):
            raise DeployError("rollback_working_dir_mismatch")
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
        health_probe = self._wait_http(f"{self._local_origin()}/health", kind="health")
        restored_openapi = self._capture_openapi_control()
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
            )
        }
        return {
            "status": "pass",
            "completed_at": _utc_now(),
            "restored_image_id": restored_image_id,
            "working_dir": str(rollback_root),
            "compose_config_files": rollback_files,
            "image_reference": restored_reference,
            "mount_identity_sha256": restored_mount_digest,
            "mount_identity_count": len(restored_mounts),
            **restored_runtime_config,
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
        release_source = self._release_source_metadata()
        source_state = source_worktree_metadata(self.root, dirty_path_limit=10000)
        if bool(source_state.get("source_worktree_dirty")):
            raise DeployError("source_worktree_dirty")
        self.receipt["source_worktree"] = source_state
        self._write_receipt()
        self._detect_compose()
        previous = self._previous_api()
        self._configure_forward_topology(previous)
        rollback_render = self._verify_rollback_renderability(previous)
        source_revision = self._bind_source_revision(
            str(release_source["source_revision"])
        )
        candidate = self._resolve_candidate_image(source_revision)
        candidate_promotion = self._validate_candidate_promotion_receipt(
            candidate=candidate,
            source_revision=source_revision,
        )
        authority = self._materialize_and_verify_release_evidence()
        self._validate_compose(candidate=candidate)
        public_origin = _validate_public_origin(
            str(authority.get("public_origin") or ""),
            allowed_hosts=self.allowed_public_hosts,
        )
        non_memorial_controls = self._capture_non_memorial_controls()
        self.receipt.update(
            {
                "status": "preflight_pass",
                "source_revision": source_revision,
                "public_origin": public_origin,
                "previous_api": self._sanitized_previous_api(previous),
                "rollback_compose_files": previous["compose_config_files"],
                "rollback": {
                    "status": "available",
                    "working_dir": previous["working_dir"],
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
            "non_memorial_controls": non_memorial_controls,
        }

    def deploy(self, *, preflight_only: bool = False) -> dict[str, Any]:
        mutation_started = False
        rollback_tag = ""
        previous: dict[str, Any] = {}
        non_memorial_controls: dict[str, Any] = {}
        self._acquire_lock()
        try:
            context = self.preflight()
            previous = dict(context["previous"])
            non_memorial_controls = dict(context["non_memorial_controls"])
            if preflight_only:
                self.receipt["status"] = "preflight_only_pass"
                self.receipt["completed_at"] = _utc_now()
                self._write_receipt()
                return self.receipt

            self._ensure_redis()
            rollback_tag = self._protect_previous_image(previous)
            self.receipt["rollback"] = {
                "status": "available",
                "working_dir": previous["working_dir"],
                "image_id": previous["image_id"],
                "image_tag": rollback_tag,
            }
            self.receipt["status"] = "changing_api"
            self._write_receipt()
            mutation_started = True

            self._recreate_api()
            api_detail = self._wait_container(API_SERVICE, require_health=True)
            api_identity = self._verify_forward_api(
                candidate=dict(context["candidate"]),
                source_revision=str(context["source_revision"]),
            )
            self._record_check(
                "api_container", "pass", **api_detail, identity=api_identity
            )
            self._verify_deployed_surface(
                str(context["public_origin"]),
                source_revision=str(context["source_revision"]),
            )
            self._verify_candidate_origins(str(context["public_origin"]))
            self._verify_non_memorial_controls(non_memorial_controls)

            # Refresh the public-access projection only after both edge probes pass.
            self._run(
                [
                    sys.executable,
                    str(self.root / "scripts/materialize_memorial_operator_status.py"),
                ]
            )
            final_authority = self._run_json_script(
                "scripts/verify_release_authority.py", "--pretty"
            )
            if str(final_authority.get("status") or "").lower() != "pass":
                raise DeployError("postdeploy_release_authority_not_pass")
            final_readiness = self._run_json_script(
                "scripts/verify_memorial_deploy_readiness.py", "--pretty"
            )
            if str(final_readiness.get("status") or "").lower() != "pass":
                raise DeployError("postdeploy_memorial_readiness_not_pass")

            self.receipt["status"] = "pass"
            self.receipt["completed_at"] = _utc_now()
            self.receipt["rollback"]["status"] = "available"
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
                    )
                    self.receipt["status"] = "failed_rolled_back"
                    self.receipt["rollback"] = rollback
                    self.receipt["completed_at"] = _utc_now()
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
                    self.receipt["completed_at"] = _utc_now()
                    self._write_receipt()
                    raise DeployError(
                        f"deployment_and_rollback_failed:{original_error}:{rollback_exc}"
                    ) from rollback_exc
            self.receipt["status"] = "preflight_failed"
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
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="Run evidence, Compose, rollback-input, and origin checks without Docker mutations.",
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
        receipt = lane.deploy(preflight_only=bool(args.preflight_only))
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
