#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CONTRACT_NAME = "ea.core_candidate_runtime_verification.v1"
EXPECTED_SERVICES = (
    "postgres",
    "redis",
    "api",
    "responses-proxy",
    "worker",
    "scheduler",
    "proactive",
)
CORE_SERVICES = (
    "api",
    "responses-proxy",
    "worker",
    "scheduler",
    "proactive",
)
DISABLED_FLAGS = (
    "EA_SCHEDULER_SIDE_EFFECTS_ENABLED",
    "EA_PROACTIVE_OODA_ENABLED",
    "EA_ENABLE_PUBLIC_SIDE_SURFACES",
    "EA_ENABLE_PUBLIC_RESULTS",
    "EA_ENABLE_PUBLIC_TOURS",
    "EA_ENABLE_PUBLIC_MEMORIALS",
    "EA_ENABLE_LEGACY_RUNTIME_SURFACES",
    "EA_ENABLE_API_DOCS",
)
SOURCE_REVISION_LABEL = "org.opencontainers.image.revision"
SOURCE_REVISION_HEADER = "x-ea-source-revision"
DISABLED_VALUES = {"0", "false", "no", "off"}
PROJECT_RE = re.compile(r"^ea-core-candidate-[a-z0-9][a-z0-9-]{2,79}$")
IMAGE_ID_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
TAGGED_IMAGE_RE = re.compile(
    r"^[a-z0-9][a-z0-9._/-]*:[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$"
)
DIGEST_IMAGE_RE = re.compile(r"^[a-z0-9][a-z0-9._:/-]*@sha256:[0-9a-f]{64}$")
CONTAINER_ID_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_INVENTORY_BYTES = 32 * 1024
MAX_INSPECT_BYTES = 2 * 1024 * 1024
MAX_EXEC_BYTES = 512 * 1024
HTTP_BODY_LIMIT = 256 * 1024
DOCKER_TIMEOUT_SECONDS = 12.0
EXEC_TIMEOUT_SECONDS = 10.0

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


_HTTP_PROBE_PROGRAM = r"""
import base64
import http.client
import json
import sys

port = int(sys.argv[1])
path = sys.argv[2]
headers = json.loads(sys.argv[3])
limit = int(sys.argv[4])
allowed_headers = {
    "content-security-policy",
    "location",
    "permissions-policy",
    "referrer-policy",
    "strict-transport-security",
    "x-content-type-options",
    "x-ea-source-revision",
    "x-frame-options",
}
connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
connection.request("GET", path, headers=headers)
response = connection.getresponse()
body = response.read(limit + 1)
selected = {
    key.lower(): value
    for key, value in response.getheaders()
    if key.lower() in allowed_headers
}
connection.close()
print(json.dumps({
    "body": base64.b64encode(body).decode("ascii"),
    "body_too_large": len(body) > limit,
    "headers": selected,
    "status": response.status,
}, separators=(",", ":"), sort_keys=True))
""".strip()


_OUTBOUND_PROBE_PROGRAM = r"""
import json
import socket

blocked = False
connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
connection.settimeout(2.0)
try:
    connection.connect(("1.1.1.1", 443))
except OSError:
    blocked = True
finally:
    connection.close()
print(json.dumps({"blocked": blocked}, separators=(",", ":"), sort_keys=True))
""".strip()


class VerificationCommandError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _default_runner(
    argv: Sequence[str],
    *,
    timeout: float,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(argv),
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
        close_fds=True,
    )


def _run_text(
    argv: Sequence[str],
    *,
    runner: CommandRunner,
    timeout: float,
    output_limit: int,
    error_code: str,
) -> str:
    try:
        result = runner(list(argv), timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        raise VerificationCommandError(error_code) from None
    stdout = result.stdout if isinstance(result.stdout, str) else ""
    if (
        result.returncode != 0
        or len(stdout.encode("utf-8", errors="replace")) > output_limit
    ):
        raise VerificationCommandError(error_code)
    return stdout


def _run_json(
    argv: Sequence[str],
    *,
    runner: CommandRunner,
    timeout: float,
    output_limit: int,
    error_code: str,
) -> object:
    rendered = _run_text(
        argv,
        runner=runner,
        timeout=timeout,
        output_limit=output_limit,
        error_code=error_code,
    )
    try:
        return json.loads(rendered)
    except (TypeError, json.JSONDecodeError):
        raise VerificationCommandError(error_code) from None


def _safe_image_ref(value: object) -> str | None:
    candidate = str(value or "")
    if (
        not candidate
        or candidate != candidate.strip()
        or len(candidate) > 255
        or candidate.lower() == "latest"
        or candidate.lower().endswith(":latest")
    ):
        return None
    if "@" in candidate:
        return candidate if DIGEST_IMAGE_RE.fullmatch(candidate) else None
    return candidate if TAGGED_IMAGE_RE.fullmatch(candidate) else None


def _safe_project(value: object) -> str | None:
    candidate = str(value or "")
    return candidate if PROJECT_RE.fullmatch(candidate) else None


def _safe_image_id(value: object) -> str | None:
    candidate = str(value or "")
    return candidate if IMAGE_ID_RE.fullmatch(candidate) else None


def _safe_revision(value: object) -> str | None:
    candidate = str(value or "")
    return candidate if REVISION_RE.fullmatch(candidate) else None


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _sequence(value: object) -> list[object]:
    return list(value) if isinstance(value, (list, tuple)) else []


def _exact_env_value(rows: object, key: str, expected: str) -> bool:
    values: list[str] = []
    for row in _sequence(rows):
        text = str(row)
        name, separator, value = text.partition("=")
        if separator and name == key:
            values.append(value)
    return values == [expected]


def _disabled_env_value(rows: object, key: str) -> bool:
    values: list[str] = []
    for row in _sequence(rows):
        text = str(row)
        name, separator, value = text.partition("=")
        if separator and name == key:
            values.append(value.strip().lower())
    return len(values) == 1 and values[0] in DISABLED_VALUES


def _append_issue(issues: list[str], code: str) -> None:
    if code not in issues:
        issues.append(code)


def _inventory(
    *,
    project: str,
    runner: CommandRunner,
) -> tuple[dict[str, str], int, bool]:
    output = _run_text(
        [
            "docker",
            "ps",
            "-a",
            "--no-trunc",
            "--filter",
            f"label=com.docker.compose.project={project}",
            "--format",
            '{{.ID}}\t{{.Label "com.docker.compose.service"}}',
        ],
        runner=runner,
        timeout=DOCKER_TIMEOUT_SECONDS,
        output_limit=MAX_INVENTORY_BYTES,
        error_code="candidate_inventory_command_failed",
    )
    rows = [line for line in output.splitlines() if line]
    services: dict[str, str] = {}
    valid = True
    for row in rows:
        container_id, separator, service = row.partition("\t")
        if (
            separator != "\t"
            or not CONTAINER_ID_RE.fullmatch(container_id)
            or service not in EXPECTED_SERVICES
            or service in services
        ):
            valid = False
            continue
        services[service] = container_id
    exact_service_set = not (
        not valid
        or len(rows) != len(EXPECTED_SERVICES)
        or set(services) != set(EXPECTED_SERVICES)
    )
    return services, len(rows), exact_service_set


def _container_inspections(
    *,
    project: str,
    service_ids: Mapping[str, str],
    runner: CommandRunner,
) -> dict[str, dict[str, Any]]:
    ordered_ids = [service_ids[name] for name in EXPECTED_SERVICES]
    payload = _run_json(
        ["docker", "inspect", *ordered_ids],
        runner=runner,
        timeout=DOCKER_TIMEOUT_SECONDS,
        output_limit=MAX_INSPECT_BYTES,
        error_code="candidate_container_inspection_failed",
    )
    if not isinstance(payload, list) or len(payload) != len(EXPECTED_SERVICES):
        raise VerificationCommandError("candidate_container_inspection_invalid")
    by_service: dict[str, dict[str, Any]] = {}
    expected_ids = set(ordered_ids)
    for raw in payload:
        inspection = _mapping(raw)
        container_id = str(inspection.get("Id") or "")
        labels = _mapping(_mapping(inspection.get("Config")).get("Labels"))
        service = str(labels.get("com.docker.compose.service") or "")
        if (
            container_id not in expected_ids
            or service not in EXPECTED_SERVICES
            or service in by_service
            or service_ids.get(service) != container_id
            or labels.get("com.docker.compose.project") != project
        ):
            raise VerificationCommandError("candidate_container_inspection_invalid")
        by_service[service] = inspection
    if set(by_service) != set(EXPECTED_SERVICES):
        raise VerificationCommandError("candidate_container_inspection_invalid")
    return by_service


def _image_inspection(
    *,
    image_ref: str,
    runner: CommandRunner,
) -> dict[str, Any]:
    payload = _run_json(
        ["docker", "image", "inspect", image_ref],
        runner=runner,
        timeout=DOCKER_TIMEOUT_SECONDS,
        output_limit=MAX_INSPECT_BYTES,
        error_code="expected_image_inspection_failed",
    )
    if not isinstance(payload, list) or len(payload) != 1:
        raise VerificationCommandError("expected_image_inspection_invalid")
    inspection = _mapping(payload[0])
    if not inspection:
        raise VerificationCommandError("expected_image_inspection_invalid")
    return inspection


def _network_inspection(
    *,
    network_id: str,
    runner: CommandRunner,
) -> dict[str, Any]:
    payload = _run_json(
        ["docker", "network", "inspect", network_id],
        runner=runner,
        timeout=DOCKER_TIMEOUT_SECONDS,
        output_limit=MAX_INSPECT_BYTES,
        error_code="candidate_network_inspection_failed",
    )
    if not isinstance(payload, list) or len(payload) != 1:
        raise VerificationCommandError("candidate_network_inspection_invalid")
    inspection = _mapping(payload[0])
    if not inspection:
        raise VerificationCommandError("candidate_network_inspection_invalid")
    return inspection


def _http_probe(
    *,
    container_id: str,
    port: int,
    path: str,
    headers: Mapping[str, str] | None,
    runner: CommandRunner,
) -> dict[str, Any]:
    payload = _run_json(
        [
            "docker",
            "exec",
            container_id,
            "python",
            "-c",
            _HTTP_PROBE_PROGRAM,
            str(port),
            path,
            json.dumps(dict(headers or {}), separators=(",", ":"), sort_keys=True),
            str(HTTP_BODY_LIMIT),
        ],
        runner=runner,
        timeout=EXEC_TIMEOUT_SECONDS,
        output_limit=MAX_EXEC_BYTES,
        error_code="candidate_http_probe_command_failed",
    )
    result = _mapping(payload)
    status = result.get("status")
    encoded_body = result.get("body")
    headers_payload = result.get("headers")
    if (
        type(status) is not int
        or not isinstance(encoded_body, str)
        or not isinstance(headers_payload, Mapping)
        or result.get("body_too_large") is not False
    ):
        raise VerificationCommandError("candidate_http_probe_output_invalid")
    try:
        body = base64.b64decode(encoded_body, validate=True)
    except (ValueError, TypeError):
        raise VerificationCommandError("candidate_http_probe_output_invalid") from None
    if len(body) > HTTP_BODY_LIMIT:
        raise VerificationCommandError("candidate_http_probe_output_invalid")
    return {
        "status": status,
        "headers": {
            str(key).lower(): str(value) for key, value in headers_payload.items()
        },
        "body": body,
    }


def _outbound_probe(
    *,
    container_id: str,
    runner: CommandRunner,
) -> bool:
    payload = _run_json(
        ["docker", "exec", container_id, "python", "-c", _OUTBOUND_PROBE_PROGRAM],
        runner=runner,
        timeout=EXEC_TIMEOUT_SECONDS,
        output_limit=MAX_EXEC_BYTES,
        error_code="candidate_outbound_probe_command_failed",
    )
    result = _mapping(payload)
    if type(result.get("blocked")) is not bool:
        raise VerificationCommandError("candidate_outbound_probe_output_invalid")
    return bool(result["blocked"])


def _empty_observations() -> dict[str, object]:
    probe_names = (
        "healthz",
        "responses_ready",
        "release_authority",
        "protected_endpoint",
        "production_openapi",
        "docs_slash_redirect",
        "trusted_proxy_security_headers",
        "outbound_network",
    )
    return {
        "inventory": {
            "expected_service_count": len(EXPECTED_SERVICES),
            "discovered_service_count": 0,
            "exact_service_set": False,
        },
        "image": {
            "reference_resolves_expected_id": False,
            "revision_label_matches": False,
        },
        "services": [],
        "backend_network": {
            "all_services_backend_only": False,
            "compose_network_label_matches": False,
            "internal": False,
            "project_label_matches": False,
        },
        "probes": {name: {"executed": False, "passed": False} for name in probe_names},
    }


def _record_http_probe(
    observations: dict[str, object],
    *,
    name: str,
    result: dict[str, Any],
    passed: bool,
    details: Mapping[str, object] | None = None,
) -> None:
    probes = _mapping(observations.get("probes"))
    probes[name] = {
        "executed": True,
        "passed": passed,
        "http_status": int(result["status"]),
        **dict(details or {}),
    }
    observations["probes"] = probes


def _probe_error(
    observations: dict[str, object],
    issues: list[str],
    *,
    name: str,
    code: str,
) -> None:
    probes = _mapping(observations.get("probes"))
    probes[name] = {"executed": True, "passed": False}
    observations["probes"] = probes
    _append_issue(issues, code)


def _run_runtime_probes(
    *,
    service_ids: Mapping[str, str],
    revision: str,
    runner: CommandRunner,
    observations: dict[str, object],
    issues: list[str],
) -> None:
    api_id = service_ids["api"]
    proxy_id = service_ids["responses-proxy"]

    try:
        result = _http_probe(
            container_id=api_id,
            port=8090,
            path="/healthz",
            headers=None,
            runner=runner,
        )
        passed = (
            result["status"] == 200
            and _mapping(result["headers"]).get(SOURCE_REVISION_HEADER) == revision
        )
        _record_http_probe(
            observations,
            name="healthz",
            result=result,
            passed=passed,
            details={"source_revision_header_matches": passed},
        )
        if not passed:
            _append_issue(issues, "healthz_probe_failed")
    except VerificationCommandError:
        _probe_error(observations, issues, name="healthz", code="healthz_probe_failed")

    try:
        result = _http_probe(
            container_id=proxy_id,
            port=8091,
            path="/health/ready",
            headers=None,
            runner=runner,
        )
        passed = result["status"] == 200
        _record_http_probe(
            observations,
            name="responses_ready",
            result=result,
            passed=passed,
        )
        if not passed:
            _append_issue(issues, "responses_ready_probe_failed")
    except VerificationCommandError:
        _probe_error(
            observations,
            issues,
            name="responses_ready",
            code="responses_ready_probe_failed",
        )

    try:
        result = _http_probe(
            container_id=api_id,
            port=8090,
            path="/health/release-authority",
            headers=None,
            runner=runner,
        )
        try:
            body = json.loads(bytes(result["body"]))
        except (TypeError, json.JSONDecodeError, UnicodeDecodeError):
            body = {}
        payload = _mapping(body)
        release_summary = _mapping(payload.get("release_authority"))
        release_gate = _mapping(payload.get("release_authority_gate"))
        deploy_gate = _mapping(payload.get("deploy_context_gate"))
        supply_gate = _mapping(payload.get("runtime_supply_chain_gate"))
        details = {
            "authoritative_runtime": release_summary.get("authority_posture")
            == "authoritative_runtime",
            "deploy_context_gate_passed": deploy_gate.get("status") == "pass",
            "release_authority_gate_passed": release_gate.get("status") == "pass",
            "runtime_supply_chain_gate_passed": supply_gate.get("status") == "pass",
        }
        passed = result["status"] == 200 and all(details.values())
        _record_http_probe(
            observations,
            name="release_authority",
            result=result,
            passed=passed,
            details=details,
        )
        if not passed:
            _append_issue(issues, "release_authority_probe_failed")
    except VerificationCommandError:
        _probe_error(
            observations,
            issues,
            name="release_authority",
            code="release_authority_probe_failed",
        )

    for name, path, expected_status, issue_code in (
        (
            "protected_endpoint",
            "/app/api/outcomes",
            401,
            "protected_endpoint_probe_failed",
        ),
        ("production_openapi", "/openapi.json", 404, "production_openapi_probe_failed"),
    ):
        try:
            result = _http_probe(
                container_id=api_id,
                port=8090,
                path=path,
                headers=None,
                runner=runner,
            )
            passed = result["status"] == expected_status
            _record_http_probe(
                observations,
                name=name,
                result=result,
                passed=passed,
            )
            if not passed:
                _append_issue(issues, issue_code)
        except VerificationCommandError:
            _probe_error(observations, issues, name=name, code=issue_code)

    try:
        result = _http_probe(
            container_id=api_id,
            port=8090,
            path="/docs/",
            headers=None,
            runner=runner,
        )
        location = str(_mapping(result["headers"]).get("location") or "")
        passed = result["status"] in {307, 308} and location == "/docs"
        _record_http_probe(
            observations,
            name="docs_slash_redirect",
            result=result,
            passed=passed,
            details={"location_is_relative_docs": location == "/docs"},
        )
        if not passed:
            _append_issue(issues, "docs_slash_redirect_probe_failed")
    except VerificationCommandError:
        _probe_error(
            observations,
            issues,
            name="docs_slash_redirect",
            code="docs_slash_redirect_probe_failed",
        )

    expected_headers = {
        "content-security-policy": "frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
        "permissions-policy": "camera=(), microphone=(), geolocation=(), interest-cohort=()",
        "referrer-policy": "strict-origin-when-cross-origin",
        "strict-transport-security": "max-age=31536000",
        "x-content-type-options": "nosniff",
        "x-ea-source-revision": revision,
        "x-frame-options": "DENY",
    }
    try:
        result = _http_probe(
            container_id=api_id,
            port=8090,
            path="/healthz",
            headers={
                "Host": "myexternalbrain.com",
                "X-Forwarded-Host": "myexternalbrain.com",
                "X-Forwarded-Proto": "https",
            },
            runner=runner,
        )
        response_headers = _mapping(result["headers"])
        matches = {
            name: response_headers.get(name) == value
            for name, value in expected_headers.items()
        }
        passed = result["status"] == 200 and all(matches.values())
        _record_http_probe(
            observations,
            name="trusted_proxy_security_headers",
            result=result,
            passed=passed,
            details={"required_headers_match": matches},
        )
        if not passed:
            _append_issue(issues, "trusted_proxy_security_headers_probe_failed")
    except VerificationCommandError:
        _probe_error(
            observations,
            issues,
            name="trusted_proxy_security_headers",
            code="trusted_proxy_security_headers_probe_failed",
        )

    outbound_by_service: dict[str, bool] = {}
    outbound_command_failed = False
    for service in CORE_SERVICES:
        try:
            outbound_by_service[service] = _outbound_probe(
                container_id=service_ids[service],
                runner=runner,
            )
        except VerificationCommandError:
            outbound_by_service[service] = False
            outbound_command_failed = True
    outbound_passed = (
        not outbound_command_failed
        and set(outbound_by_service) == set(CORE_SERVICES)
        and all(outbound_by_service.values())
    )
    probes = _mapping(observations.get("probes"))
    probes["outbound_network"] = {
        "executed": True,
        "passed": outbound_passed,
        "blocked_by_service": outbound_by_service,
    }
    observations["probes"] = probes
    if not outbound_passed:
        _append_issue(issues, "outbound_network_probe_failed")


def build_receipt(
    *,
    project: str,
    expected_image_ref: str,
    expected_image_id: str,
    expected_source_revision: str,
    runner: CommandRunner = _default_runner,
    now: datetime | None = None,
) -> dict[str, object]:
    issues: list[str] = []
    observations = _empty_observations()
    safe_project = _safe_project(project)
    safe_image_ref = _safe_image_ref(expected_image_ref)
    safe_image_id = _safe_image_id(expected_image_id)
    safe_revision = _safe_revision(expected_source_revision)
    if safe_project is None:
        _append_issue(issues, "compose_project_invalid")
    if safe_image_ref is None:
        _append_issue(issues, "expected_image_ref_invalid")
    if safe_image_id is None:
        _append_issue(issues, "expected_image_id_invalid")
    if safe_revision is None:
        _append_issue(issues, "expected_source_revision_invalid")

    service_ids: dict[str, str] = {}
    inspections: dict[str, dict[str, Any]] = {}
    runtime_probe_ready = False
    if not issues:
        assert safe_project is not None
        try:
            service_ids, discovered_count, exact_service_set = _inventory(
                project=safe_project,
                runner=runner,
            )
            observations["inventory"] = {
                "expected_service_count": len(EXPECTED_SERVICES),
                "discovered_service_count": discovered_count,
                "exact_service_set": exact_service_set,
            }
            if not exact_service_set:
                service_ids = {}
                _append_issue(issues, "candidate_service_set_invalid")
            else:
                inspections = _container_inspections(
                    project=safe_project,
                    service_ids=service_ids,
                    runner=runner,
                )
        except VerificationCommandError as exc:
            _append_issue(issues, exc.code)

    if (
        inspections
        and safe_project
        and safe_image_ref
        and safe_image_id
        and safe_revision
    ):
        try:
            image = _image_inspection(image_ref=safe_image_ref, runner=runner)
            image_config = _mapping(image.get("Config"))
            image_labels = _mapping(image_config.get("Labels"))
            ref_matches = image.get("Id") == safe_image_id
            label_matches = image_labels.get(SOURCE_REVISION_LABEL) == safe_revision
            observations["image"] = {
                "reference_resolves_expected_id": ref_matches,
                "revision_label_matches": label_matches,
            }
            if not ref_matches:
                _append_issue(issues, "expected_image_id_mismatch")
            if not label_matches:
                _append_issue(issues, "expected_image_revision_label_mismatch")
        except VerificationCommandError as exc:
            _append_issue(issues, exc.code)

        service_observations: list[dict[str, object]] = []
        all_network_ids: list[str] = []
        all_running = True
        for service in EXPECTED_SERVICES:
            inspection = inspections[service]
            state = _mapping(inspection.get("State"))
            health = _mapping(state.get("Health"))
            host_config = _mapping(inspection.get("HostConfig"))
            config = _mapping(inspection.get("Config"))
            labels = _mapping(config.get("Labels"))
            environment = config.get("Env")
            mounts = _sequence(inspection.get("Mounts"))
            networks = _mapping(
                _mapping(inspection.get("NetworkSettings")).get("Networks")
            )
            network_ids = {
                str(_mapping(value).get("NetworkID") or "")
                for value in networks.values()
                if str(_mapping(value).get("NetworkID") or "")
            }
            backend_only = len(networks) == 1 and len(network_ids) == 1
            if backend_only:
                all_network_ids.extend(network_ids)
            running = state.get("Status") == "running"
            healthy = health.get("Status") == "healthy"
            restart_count = inspection.get("RestartCount")
            zero_restarts = type(restart_count) is int and restart_count == 0
            oom_clear = state.get("OOMKilled") is False
            read_only = host_config.get("ReadonlyRootfs") is True
            cap_drop_all = "ALL" in {
                str(value).upper() for value in _sequence(host_config.get("CapDrop"))
            }
            security_options = {
                str(value).strip().lower()
                for value in _sequence(host_config.get("SecurityOpt"))
            }
            no_new_privileges = bool(
                {"no-new-privileges", "no-new-privileges:true"} & security_options
            )
            no_bind_mounts = not _sequence(host_config.get("Binds")) and all(
                _mapping(mount).get("Type") != "bind" for mount in mounts
            )
            observation: dict[str, object] = {
                "service": service,
                "running": running,
                "healthy": healthy,
                "zero_restarts": zero_restarts,
                "oom_killed_false": oom_clear,
                "read_only_rootfs": read_only,
                "cap_drop_all": cap_drop_all,
                "no_new_privileges": no_new_privileges,
                "no_bind_mounts": no_bind_mounts,
                "backend_network_only": backend_only,
            }
            if not running:
                _append_issue(issues, f"service_{service}_not_running")
            if not healthy:
                _append_issue(issues, f"service_{service}_not_healthy")
            if not zero_restarts:
                _append_issue(issues, f"service_{service}_restart_count_nonzero")
            if not oom_clear:
                _append_issue(issues, f"service_{service}_oom_state_invalid")
            if not read_only:
                _append_issue(issues, f"service_{service}_rootfs_not_read_only")
            if not cap_drop_all:
                _append_issue(issues, f"service_{service}_cap_drop_all_missing")
            if not no_new_privileges:
                _append_issue(issues, f"service_{service}_no_new_privileges_missing")
            if not no_bind_mounts:
                _append_issue(issues, f"service_{service}_bind_mount_present")
            if not backend_only:
                _append_issue(issues, f"service_{service}_network_scope_invalid")
            all_running = all_running and running

            if service in CORE_SERVICES:
                image_ref_matches = config.get("Image") == safe_image_ref
                image_id_matches = inspection.get("Image") == safe_image_id
                revision_label_matches = (
                    labels.get(SOURCE_REVISION_LABEL) == safe_revision
                )
                revision_env_matches = _exact_env_value(
                    environment,
                    "EA_SOURCE_REVISION",
                    safe_revision,
                )
                disabled_flags = {
                    flag: _disabled_env_value(environment, flag)
                    for flag in DISABLED_FLAGS
                }
                observation.update(
                    {
                        "expected_image_ref": image_ref_matches,
                        "expected_image_id": image_id_matches,
                        "source_revision_label": revision_label_matches,
                        "source_revision_environment": revision_env_matches,
                        "disabled_flags": disabled_flags,
                    }
                )
                if not image_ref_matches:
                    _append_issue(issues, f"service_{service}_image_ref_mismatch")
                if not image_id_matches:
                    _append_issue(issues, f"service_{service}_image_id_mismatch")
                if not revision_label_matches:
                    _append_issue(issues, f"service_{service}_revision_label_mismatch")
                if not revision_env_matches:
                    _append_issue(
                        issues, f"service_{service}_revision_environment_mismatch"
                    )
                for flag, disabled in disabled_flags.items():
                    if not disabled:
                        _append_issue(
                            issues, f"service_{service}_{flag.lower()}_not_disabled"
                        )
            service_observations.append(observation)
        observations["services"] = service_observations

        common_network_ids = set(all_network_ids)
        all_services_backend_only = (
            len(all_network_ids) == len(EXPECTED_SERVICES)
            and len(common_network_ids) == 1
        )
        network_observation = {
            "all_services_backend_only": all_services_backend_only,
            "compose_network_label_matches": False,
            "internal": False,
            "project_label_matches": False,
        }
        if not all_services_backend_only:
            _append_issue(issues, "candidate_backend_network_membership_invalid")
        else:
            try:
                network = _network_inspection(
                    network_id=next(iter(common_network_ids)),
                    runner=runner,
                )
                labels = _mapping(network.get("Labels"))
                internal = network.get("Internal") is True
                project_matches = (
                    labels.get("com.docker.compose.project") == safe_project
                )
                compose_network_matches = (
                    labels.get("com.docker.compose.network") == "backend"
                )
                network_observation.update(
                    {
                        "compose_network_label_matches": compose_network_matches,
                        "internal": internal,
                        "project_label_matches": project_matches,
                    }
                )
                if not internal:
                    _append_issue(issues, "candidate_backend_network_not_internal")
                if not project_matches:
                    _append_issue(issues, "candidate_backend_network_project_mismatch")
                if not compose_network_matches:
                    _append_issue(issues, "candidate_backend_network_label_mismatch")
            except VerificationCommandError as exc:
                _append_issue(issues, exc.code)
        observations["backend_network"] = network_observation
        runtime_probe_ready = all_running

    if runtime_probe_ready and safe_revision:
        _run_runtime_probes(
            service_ids=service_ids,
            revision=safe_revision,
            runner=runner,
            observations=observations,
            issues=issues,
        )
    elif inspections:
        _append_issue(issues, "runtime_probes_skipped_candidate_not_running")

    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return {
        "contract_name": CONTRACT_NAME,
        "generated_at": current.isoformat().replace("+00:00", "Z"),
        "status": "pass" if not issues else "fail",
        "issues": issues,
        "request": {
            "compose_project": safe_project or "invalid",
            "expected_image_ref": safe_image_ref or "invalid",
            "expected_image_id": safe_image_id or "invalid",
            "expected_source_revision": safe_revision or "invalid",
        },
        "scope": {
            "expected_services": list(EXPECTED_SERVICES),
            "core_image_services": list(CORE_SERVICES),
            "inspection_only": True,
            "runtime_mutations": False,
            "probe_transport": "docker_exec_private_loopback",
        },
        "observations": observations,
        "privacy": {
            "environment_values_emitted": False,
            "secret_values_emitted": False,
            "raw_http_bodies_emitted": False,
            "raw_subprocess_output_emitted": False,
        },
    }


def write_receipt(path: Path, payload: Mapping[str, object]) -> None:
    destination = path.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, ensure_ascii=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
        os.chmod(destination, 0o600)
        directory_fd = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temporary.unlink(missing_ok=True)
        raise


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fail-closed, read-only verification of an isolated EA Core candidate.",
    )
    parser.add_argument("--compose-project", required=True)
    parser.add_argument("--expected-image-ref", required=True)
    parser.add_argument("--expected-image-id", required=True)
    parser.add_argument("--expected-source-revision", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    receipt = build_receipt(
        project=args.compose_project,
        expected_image_ref=args.expected_image_ref,
        expected_image_id=args.expected_image_id,
        expected_source_revision=args.expected_source_revision,
    )
    write_receipt(args.output, receipt)
    print(
        json.dumps(
            {
                "contract_name": CONTRACT_NAME,
                "issue_count": len(_sequence(receipt.get("issues"))),
                "status": receipt["status"],
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0 if receipt["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
