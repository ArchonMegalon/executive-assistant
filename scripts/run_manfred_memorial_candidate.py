#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
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
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.prepare_manfred_memorial_candidate import (  # noqa: E402
    SPATIAL_AUTHORITY_SCHEMA,
    SPATIAL_AUTHORITY_SCOPE,
    SPATIAL_MANIFEST_NORMALIZATION,
    SPATIAL_PROJECTION_SCHEMA,
    SPATIAL_SLUG_RE,
    _canonical_json_bytes,
    _parse_env,
    _receipt_bytes,
    _sanitized_spatial_manifest,
    _sha256,
    _spatial_pre_authority_manifest_bytes,
    _tree_digest,
    _validate_project_name,
)
from scripts.verify_public_tour_generated_viewer_release import (  # noqa: E402
    verify_bundle as verify_spatial_bundle,
)
from scripts.verify_manfred_memorial_candidate import (  # noqa: E402
    audit_browser_surface,
    verify_candidate,
)


RECEIPT_SCHEMA = "ea.manfred_memorial_candidate_runtime.v3"
ALLOWED_ENV_KEYS = {
    "DATABASE_URL",
    "EA_API_TOKEN",
    "EA_MANFRED_COMPOSE_PROJECT",
    "EA_MANFRED_ENV_FILE",
    "EA_MANFRED_HOST_PORT",
    "EA_MANFRED_IMAGE",
    "EA_MANFRED_POSTGRES_PASSWORD",
    "EA_MANFRED_RELEASE_ROOT",
    "EA_MANFRED_RUNTIME_ROOT",
    "EA_MANFRED_SPATIAL_HANDOFF_INCLUDED",
    "EA_MANFRED_SPATIAL_RELEASE_ROOT",
    "EA_MANFRED_SPATIAL_SHA256",
    "EA_MANFRED_SPATIAL_SLUG",
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
PORT_RELEASE_WAIT_SECONDS = 10.0
PORT_RELEASE_POLL_SECONDS = 0.1


class GovernedSignalInterrupt(BaseException):
    def __init__(self, signum: int) -> None:
        self.signum = int(signum)
        super().__init__(f"manfred_candidate_governed_signal:{self.signum}")


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


def _compose_environment(candidate_env: dict[str, str]) -> dict[str, str]:
    environment = _safe_subprocess_environment()
    environment.update(candidate_env)
    environment.pop("COMPOSE_PROJECT_NAME", None)
    environment.pop("COMPOSE_FILE", None)
    return environment


def _run(
    argv: list[str],
    *,
    timeout: int = 300,
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


def _assert_openapi_contract_preserved(
    live: dict[str, object], candidate: dict[str, object]
) -> dict[str, object]:
    allowed_retirements = list(OPENAPI_RETIREMENT_ALLOWED_OPERATIONS)
    live_operations = dict(live.get("operations") or {})
    candidate_operations = dict(candidate.get("operations") or {})
    if [
        name for name in allowed_retirements if name in live_operations
    ] != allowed_retirements or any(
        name in candidate_operations for name in allowed_retirements
    ):
        raise RuntimeError("manfred_candidate_openapi_contract_regression")

    counts: dict[str, int] = {}
    for category, count_key in (
        ("operations", "missing_or_changed_operation_count"),
        ("schemas", "missing_or_changed_schema_count"),
        ("security_schemes", "missing_or_changed_security_scheme_count"),
    ):
        live_rows = dict(live.get(category) or {})
        candidate_rows = dict(candidate.get(category) or {})
        changed = sum(
            1
            for name, value in live_rows.items()
            if (
                category != "operations"
                or name not in OPENAPI_RETIREMENT_ALLOWED_OPERATIONS
            )
            and (name not in candidate_rows or candidate_rows[name] != value)
        )
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
        "candidate_preserves_live_contract": True,
    }


def _openapi_contract_snapshot(
    base_url: str,
) -> tuple[dict[str, object], dict[str, object]]:
    request = urllib.request.Request(
        f"{str(base_url or '').rstrip('/')}/openapi.json",
        method="GET",
        headers={"Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            if int(response.status or 0) != 200:
                raise RuntimeError("manfred_candidate_openapi_status_invalid")
            body = response.read(8 * 1024 * 1024 + 1)
    except (OSError, urllib.error.URLError) as exc:
        raise RuntimeError("manfred_candidate_openapi_unreachable") from exc
    if len(body) > 8 * 1024 * 1024:
        raise RuntimeError("manfred_candidate_openapi_response_too_large")
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("manfred_candidate_openapi_invalid") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("manfred_candidate_openapi_invalid")
    contract = _canonical_openapi_contract(payload)
    return contract, _openapi_contract_evidence(contract)


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
        or not receipt_path.is_file()
        or receipt_path.is_symlink()
        or stat.S_IMODE(receipt_path.stat().st_mode) != 0o600
        or receipt_path.stat().st_nlink != 1
    ):
        raise RuntimeError("manfred_candidate_spatial_projection_receipt_invalid")
    try:
        receipt_bytes = receipt_path.read_bytes()
        receipt = json.loads(receipt_bytes)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            "manfred_candidate_spatial_projection_receipt_invalid"
        ) from exc
    if (
        not isinstance(receipt, dict)
        or _receipt_bytes(receipt) != receipt_bytes
        or receipt.get("schema") != SPATIAL_PROJECTION_SCHEMA
        or receipt.get("status") != "pass"
        or receipt.get("release_id") != release_id
        or receipt.get("candidate_handoff_only") is not True
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
        or receipt.get("slug") != slug
        or projection_receipt.get("spatial_slug") != slug
        or receipt.get("spatial_projection_sha256") != digest
        or projection_receipt.get("spatial_projection_sha256") != digest
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
        "public_activation_authority": False,
    }
    if not included:
        if slug or observed_files or receipt.get("asset_paths"):
            raise RuntimeError("manfred_candidate_spatial_empty_projection_invalid")
        return evidence

    asset_paths = list(receipt.get("asset_paths") or [])
    viewer_relpath = str(receipt.get("viewer_relpath") or "")
    proof_relpath = str(receipt.get("proof_relpath") or "")
    authority_sha256 = str(receipt.get("authority_receipt_sha256") or "")
    authority_receipt = dict(receipt.get("authority_receipt") or {})
    pre_authority_sha256 = str(
        receipt.get("transformed_manifest_pre_authority_sha256") or ""
    )
    expected_paths = {f"{slug}/tour.json", *(f"{slug}/{path}" for path in asset_paths)}
    if (
        len(asset_paths) != 5
        or len(observed_files) != 6
        or {str(row.get("path") or "") for row in observed_files} != expected_paths
        or receipt.get("normalization") != SPATIAL_MANIFEST_NORMALIZATION
        or authority_receipt.get("schema") != SPATIAL_AUTHORITY_SCHEMA
        or authority_receipt.get("status") != "pass"
        or authority_receipt.get("scope") != SPATIAL_AUTHORITY_SCOPE
        or authority_receipt.get("candidate_handoff_authorized") is not True
        or authority_receipt.get("public_activation_authority") is not False
        or authority_receipt.get("slug") != slug
        or authority_receipt.get("target_origin") != env["EA_PUBLIC_APP_BASE_URL"]
        or authority_receipt.get("normalization") != SPATIAL_MANIFEST_NORMALIZATION
        or authority_receipt.get("asset_paths") != asset_paths
        or authority_receipt.get("transformed_manifest_pre_authority_sha256")
        != pre_authority_sha256
        or _sha256(_receipt_bytes(authority_receipt)) != authority_sha256
        or len(authority_sha256) != 64
        or any(character not in "0123456789abcdef" for character in authority_sha256)
        or len(pre_authority_sha256) != 64
        or any(
            character not in "0123456789abcdef" for character in pre_authority_sha256
        )
    ):
        raise RuntimeError("manfred_candidate_spatial_projection_contract_invalid")
    bundle = spatial_root / slug
    try:
        manifest_bytes = (bundle / "tour.json").read_bytes()
        manifest = json.loads(manifest_bytes)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("manfred_candidate_spatial_manifest_invalid") from exc
    if not isinstance(manifest, dict):
        raise RuntimeError("manfred_candidate_spatial_manifest_invalid")
    release = dict(manifest.get("generated_viewer_release") or {})
    canonical_final = _canonical_json_bytes(
        _sanitized_spatial_manifest(
            manifest,
            authority_receipt_sha256=authority_sha256,
        )
    )
    if (
        manifest_bytes != canonical_final
        or release.get("publication_authority_receipt_sha256") != authority_sha256
        or _sha256(_spatial_pre_authority_manifest_bytes(manifest))
        != pre_authority_sha256
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
            "authority_receipt_sha256": authority_sha256,
            "transformed_manifest_pre_authority_sha256": pre_authority_sha256,
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
    if (
        not receipt_path.is_file()
        or receipt_path.is_symlink()
        or stat.S_IMODE(receipt_path.stat().st_mode) != 0o600
    ):
        raise RuntimeError("manfred_candidate_projection_receipt_invalid")
    try:
        payload = json.loads(receipt_path.read_bytes())
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RuntimeError("manfred_candidate_projection_receipt_invalid") from exc
    digest = (
        str(payload.get("projection_sha256") or "") if isinstance(payload, dict) else ""
    )
    commit = str(payload.get("commit") or "") if isinstance(payload, dict) else ""
    image = str(payload.get("image") or "") if isinstance(payload, dict) else ""
    image_id = str(payload.get("image_id") or "") if isinstance(payload, dict) else ""
    try:
        operator_gid = int(payload.get("projection_operator_gid"))
    except (TypeError, ValueError):
        operator_gid = -1
    if (
        not isinstance(payload, dict)
        or payload.get("schema") != "ea.manfred_memorial_candidate_projection.v2"
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
    spatial = _spatial_projection_evidence(
        env,
        projection_receipt=payload,
        release_root=release_root,
        release_id=release_id,
    )
    return {
        "release_id": release_id,
        "release_root": str(release_root),
        "projection_sha256": digest,
        "projection_commit": commit,
        "prepared_image_locator": image,
        "prepared_image_id": image_id,
        "projection_tree_revalidated": True,
        "spatial_handoff": spatial,
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
        "locator_only": True,
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


def _wait_for_loopback_port_free(
    port: int,
    *,
    timeout_seconds: float = PORT_RELEASE_WAIT_SECONDS,
    poll_seconds: float = PORT_RELEASE_POLL_SECONDS,
) -> None:
    deadline = time.monotonic() + max(0.0, float(timeout_seconds))
    interval = max(0.01, float(poll_seconds))
    while True:
        try:
            _assert_loopback_port_free(port)
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
    with _hold_project_lock(project) as project_evidence:
        with _hold_port_lock(port) as port_evidence:
            yield {"project": project_evidence, "port": port_evidence}


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


def _candidate_preflight(project: str, port: int) -> dict[str, object]:
    evidence = _assert_candidate_project_absent(project)
    _assert_loopback_port_free(port)
    return {
        **evidence,
        "loopback_host": "127.0.0.1",
        "loopback_port": port,
        "loopback_port_free_before_start": True,
    }


def _candidate_runtime_source_revision(base_url: str) -> str:
    request = urllib.request.Request(
        f"{str(base_url or '').rstrip('/')}/memorials/manfred.json",
        method="GET",
        headers={"Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            if int(response.status or 0) != 200:
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
    if str(api.get("image") or "") != env["EA_MANFRED_IMAGE"]:
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
    if str(gateway.get("image") or "") != env["EA_MANFRED_IMAGE"]:
        raise RuntimeError("manfred_candidate_gateway_image_mismatch")
    if gateway.get("env_file") or gateway.get("environment"):
        raise RuntimeError("manfred_candidate_gateway_secret_scope_invalid")

    source_env_files = list(source_api.get("env_file") or [])
    if len(source_env_files) != 1 or not isinstance(source_env_files[0], dict):
        raise RuntimeError("manfred_candidate_compose_env_file_invalid")
    if str(source_env_files[0].get("path") or "") != str(env_file.resolve()):
        raise RuntimeError("manfred_candidate_compose_env_file_mismatch")
    resolved_environment = dict(api.get("environment") or {})
    declared_environment = dict(source_api.get("environment") or {})
    if str(declared_environment.get("EA_PUBLIC_TOUR_DIR") or "") != (
        "/data/public_property_tours"
    ):
        raise RuntimeError("manfred_candidate_spatial_compose_environment_invalid")
    expected_environment_keys = set(env).union(declared_environment)
    if set(resolved_environment) != expected_environment_keys:
        raise RuntimeError("manfred_candidate_compose_environment_scope_invalid")
    for name, value in env.items():
        if str(resolved_environment.get(name) or "") != value:
            raise RuntimeError("manfred_candidate_compose_environment_mismatch")
    for name, value in declared_environment.items():
        if str(resolved_environment.get(name) or "") != str(value or ""):
            raise RuntimeError(
                "manfred_candidate_compose_declared_environment_mismatch"
            )

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
        "/data/public_property_tours": (
            str(Path(env["EA_MANFRED_SPATIAL_RELEASE_ROOT"]).resolve()),
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
                target == "/data/public_property_tours"
                or source == env["EA_MANFRED_SPATIAL_RELEASE_ROOT"]
            ):
                raise RuntimeError("manfred_candidate_spatial_compose_scope_invalid")


def _assert_env_allowlist(env_file: Path) -> dict[str, str]:
    env = _parse_env(env_file)
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
        "EA_MANFRED_RUNTIME_ROOT",
        "EA_MANFRED_SPATIAL_RELEASE_ROOT",
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
    spatial_root = Path(env["EA_MANFRED_SPATIAL_RELEASE_ROOT"]).resolve()
    if spatial_root != (release_root / "public_property_tours").resolve():
        raise RuntimeError("manfred_candidate_spatial_env_root_mismatch")
    included = env["EA_MANFRED_SPATIAL_HANDOFF_INCLUDED"]
    slug = env["EA_MANFRED_SPATIAL_SLUG"]
    digest = env["EA_MANFRED_SPATIAL_SHA256"]
    if (
        included not in {"0", "1"}
        or (included == "1") != bool(slug)
        or (slug and not SPATIAL_SLUG_RE.fullmatch(slug))
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise RuntimeError("manfred_candidate_spatial_env_invalid")
    try:
        port = int(env["EA_MANFRED_HOST_PORT"])
    except ValueError as exc:
        raise RuntimeError("manfred_candidate_host_port_invalid") from exc
    if not 1024 <= port <= 65535:
        raise RuntimeError("manfred_candidate_host_port_invalid")
    return env


def _assert_redis(compose: list[str], environment: dict[str, str]) -> None:
    response = _run(
        [*compose, "exec", "-T", "redis", "redis-cli", "ping"],
        timeout=30,
        environment=environment,
    )
    if response.decode("utf-8", errors="replace").strip() != "PONG":
        raise RuntimeError("manfred_candidate_redis_unavailable")


def _assert_contribution_modes(
    compose: list[str], environment: dict[str, str]
) -> dict[str, str]:
    command = (
        "private=/data/memorial/private-contributions/manfred/family_contributions.json; "
        "public=/data/memorial/public-contributions/manfred/family_contributions.public.json; "
        'test -f "$private"; test -f "$public"; '
        'printf \'%s %s\' "$(stat -c %a "$private")" "$(stat -c %a "$public")"'
    )
    raw = _run(
        [*compose, "exec", "-T", "api", "/bin/sh", "-ec", command],
        timeout=30,
        environment=environment,
    )
    private_mode, public_mode = raw.decode("ascii").strip().split()
    if private_mode != "600" or public_mode != "644":
        raise RuntimeError("manfred_candidate_contribution_permissions_invalid")
    return {"private_ledger": private_mode, "public_projection": public_mode}


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
    base_url: str, projection: dict[str, object]
) -> dict[str, object]:
    spatial = dict(projection.get("spatial_handoff") or {})
    if spatial.get("included") is not True:
        return {
            "included": False,
            "routes_required": False,
            "public_activation_authority": False,
        }
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
    return {
        "included": True,
        "routes_required": True,
        "slug": slug,
        "routes": routes,
        "generated_viewer_release_verifier": verifier_receipt,
        "html_json_viewer_200": True,
        "proof_only_404": True,
        "public_activation_authority": False,
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


def _atomic_receipt(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=str(path.parent)
    )
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        Path(temporary).unlink(missing_ok=True)


def prove_candidate(
    *,
    env_file: Path,
    compose_file: Path,
    receipt_path: Path,
    wait_seconds: int,
) -> dict[str, object]:
    env_file = env_file.expanduser().resolve()
    compose_file = compose_file.expanduser().resolve()
    receipt_path = receipt_path.expanduser().resolve()
    env = _assert_env_allowlist(env_file)
    projection = _projection_evidence(env)
    project = _validate_project_name(env["EA_MANFRED_COMPOSE_PROJECT"])
    port = int(env["EA_MANFRED_HOST_PORT"])
    compose_environment = _compose_environment(env)
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
    )
    compose = _compose_argv(project, env_file, compose_file)
    base_url = f"http://127.0.0.1:{port}"
    contribution_receipt = receipt_path.parent / "candidate-contribution.private.json"

    with _hold_candidate_locks(project, port) as lock_evidence:
        image_locator_evidence = _assert_prepared_image_locator(projection)
        live_before = _live_snapshot()
        _assert_live_healthy(live_before)
        _assert_live_http()
        live_openapi_contract, live_openapi_before = _openapi_contract_snapshot(
            "http://127.0.0.1:8090"
        )
        preflight = _candidate_preflight(project, port)
        up_started = False
        try:
            receipt_path.unlink(missing_ok=True)
            up_started = True
            _run(
                [*compose, "up", "-d", "--wait", "--wait-timeout", str(wait_seconds)],
                timeout=wait_seconds + 60,
                environment=compose_environment,
            )
            _assert_redis(compose, compose_environment)

            first_smoke = verify_candidate(
                base_url=base_url,
                public_origin=env["EA_PUBLIC_APP_BASE_URL"],
                wait_seconds=wait_seconds,
                submit_receipt=contribution_receipt,
                withdraw_receipt=None,
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
            _run(
                [*compose, "restart", "api"],
                timeout=90,
                environment=compose_environment,
            )
            second_smoke = verify_candidate(
                base_url=base_url,
                public_origin=env["EA_PUBLIC_APP_BASE_URL"],
                wait_seconds=wait_seconds,
                submit_receipt=None,
                withdraw_receipt=contribution_receipt,
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
            _assert_redis(compose, compose_environment)
            contribution_modes = _assert_contribution_modes(
                compose, compose_environment
            )
            spatial_handoff = _spatial_handoff_runtime_proof(base_url, projection)
            browser_surface = audit_browser_surface(base_url)
            _assert_logs_clean(compose, compose_environment)
            candidate_openapi_contract, candidate_openapi = _openapi_contract_snapshot(
                base_url
            )
            openapi_preservation = _assert_openapi_contract_preserved(
                live_openapi_contract, candidate_openapi_contract
            )
            container_images = _candidate_container_image_evidence(
                compose=compose,
                environment=compose_environment,
                project=project,
                projection=projection,
            )
            image_id = str(projection["prepared_image_id"])
            image_source_revision = str(projection["projection_commit"])
            runtime_source_revision = _candidate_runtime_source_revision(base_url)
            if runtime_source_revision != str(projection["projection_commit"]):
                raise RuntimeError("manfred_candidate_runtime_revision_image_mismatch")
            live_after = _live_snapshot()
            _assert_live_unchanged(live_before, live_after)
            _assert_live_http()
            live_openapi_after_contract, live_openapi_after = (
                _openapi_contract_snapshot("http://127.0.0.1:8090")
            )
            if live_openapi_after_contract != live_openapi_contract:
                raise RuntimeError("manfred_candidate_live_openapi_changed")
            receipt = {
                "schema": RECEIPT_SCHEMA,
                "status": "pass",
                "observed_at": datetime.now(timezone.utc)
                .replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z"),
                "image": env["EA_MANFRED_IMAGE"],
                "image_id": image_id,
                "image_source_revision": image_source_revision,
                "image_locator_evidence": image_locator_evidence,
                "image_locator_only": True,
                "candidate_container_images": container_images,
                "runtime_source_revision": runtime_source_revision,
                "runtime_revision_matches_image": True,
                **projection,
                "compose_project": project,
                "compose_project_isolated": True,
                "compose_environment_bound_to_candidate_env": True,
                "candidate_named_resources": _candidate_named_resources(project),
                "candidate_preflight": preflight,
                "locks": lock_evidence,
                "project_lock": lock_evidence["project"],
                "port_lock": lock_evidence["port"],
                "candidate_api_container_id": api_after_restart,
                "candidate_port": port,
                "api_network_internal": True,
                "gateway_has_runtime_secrets": False,
                "provider_credentials_present": False,
                "provider_calls_performed": False,
                "redis_ping": "PONG",
                "contribution_modes": contribution_modes,
                "spatial_handoff_runtime": spatial_handoff,
                "contribution_survived_restart": bool(
                    second_smoke.get("contribution", {}).get(
                        "survived_candidate_restart"
                    )
                ),
                "first_smoke_checks": first_smoke.get("checks", []),
                "second_smoke_checks": second_smoke.get("checks", []),
                "browser_surface": browser_surface,
                "openapi_contract": {
                    "live_before": live_openapi_before,
                    "candidate": candidate_openapi,
                    "live_after": live_openapi_after,
                    **openapi_preservation,
                },
                "live_ea_api_unchanged": True,
                "live_ea_api": _main_api_snapshot(live_after),
                "live_ea_project_before": live_before,
                "live_ea_project_after": live_after,
                "live_ea_project_unchanged": True,
                "candidate_left_running_for_soak": True,
                "promotion_authority": False,
            }
            _atomic_receipt(receipt_path, receipt)
            return receipt
        except BaseException as exc:
            if not up_started:
                raise
            recovery_errors: list[str] = []
            with _shield_cleanup_interrupts():
                try:
                    _run(
                        [
                            *compose,
                            "down",
                            "--volumes",
                            "--remove-orphans",
                            "--timeout",
                            "30",
                        ],
                        timeout=120,
                        environment=compose_environment,
                    )
                except BaseException:
                    recovery_errors.append("candidate_compose_down_failed")
                try:
                    _assert_candidate_project_absent(project)
                except BaseException:
                    recovery_errors.append("candidate_resources_remain")
                try:
                    _wait_for_loopback_port_free(port)
                except BaseException:
                    recovery_errors.append("candidate_port_remains_bound")
                try:
                    contribution_receipt.unlink(missing_ok=True)
                except BaseException:
                    recovery_errors.append("candidate_private_receipt_cleanup_failed")
                try:
                    receipt_path.unlink(missing_ok=True)
                except BaseException:
                    recovery_errors.append("candidate_runtime_receipt_cleanup_failed")
                try:
                    recovered_live = _live_snapshot()
                    _assert_live_unchanged(live_before, recovered_live)
                    _assert_live_http()
                    recovered_openapi_contract, _recovered_openapi = (
                        _openapi_contract_snapshot("http://127.0.0.1:8090")
                    )
                    if recovered_openapi_contract != live_openapi_contract:
                        raise RuntimeError("manfred_candidate_live_openapi_changed")
                except BaseException:
                    recovery_errors.append("live_ea_changed_or_unhealthy")
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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        with _governed_signal_handlers():
            receipt = prove_candidate(
                env_file=Path(args.env_file),
                compose_file=Path(args.compose_file),
                receipt_path=Path(args.receipt).expanduser().resolve(),
                wait_seconds=max(60, min(600, int(args.wait_seconds))),
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
        print(
            json.dumps(
                {
                    "schema": RECEIPT_SCHEMA,
                    "status": "fail",
                    "error": str(exc)[:200],
                    "live_ea_api_mutation_requested": False,
                },
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
