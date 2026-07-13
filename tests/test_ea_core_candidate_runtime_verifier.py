from __future__ import annotations

import base64
import copy
import importlib.util
import json
import os
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PROJECT = "ea-core-candidate-c3955701-20260714"
IMAGE_REF = "ea-runtime:core-" + "a" * 40
IMAGE_ID = "sha256:" + "b" * 64
REVISION = "a" * 40
NETWORK_ID = "8" * 64
SERVICE_IDS = {
    service: str(index) * 64
    for index, service in enumerate(
        (
            "postgres",
            "redis",
            "api",
            "responses-proxy",
            "worker",
            "scheduler",
            "proactive",
        ),
        start=1,
    )
}
SECRET = "candidate-secret-that-must-never-be-emitted"


def _module():
    name = "verify_ea_core_candidate_runtime_test"
    path = ROOT / "scripts" / "verify_ea_core_candidate_runtime.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _completed(
    argv: list[str],
    *,
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        argv,
        returncode,
        stdout=stdout,
        stderr=stderr,
    )


def _container(module, service: str) -> dict[str, object]:
    core = service in module.CORE_SERVICES
    labels = {
        "com.docker.compose.project": PROJECT,
        "com.docker.compose.service": service,
    }
    environment: list[str] = []
    if core:
        labels[module.SOURCE_REVISION_LABEL] = REVISION
        environment = [
            f"EA_SOURCE_REVISION={REVISION}",
            *(f"{flag}=0" for flag in module.DISABLED_FLAGS),
            f"EA_API_TOKEN={SECRET}",
            f"EA_SIGNING_SECRET={SECRET}",
        ]
    elif service == "postgres":
        environment = [f"POSTGRES_PASSWORD={SECRET}"]
    mounts = (
        [
            {
                "Type": "volume",
                "Name": f"{PROJECT}_postgres_data",
                "Destination": "/var/lib/postgresql/data",
            }
        ]
        if service == "postgres"
        else []
    )
    return {
        "Id": SERVICE_IDS[service],
        "Image": IMAGE_ID if core else "sha256:" + "c" * 64,
        "RestartCount": 0,
        "State": {
            "Status": "running",
            "OOMKilled": False,
            "Health": {"Status": "healthy"},
        },
        "Config": {
            "Image": IMAGE_REF if core else f"fixture/{service}:pinned",
            "Labels": labels,
            "Env": environment,
        },
        "HostConfig": {
            "ReadonlyRootfs": True,
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges:true"],
            "Binds": None,
        },
        "Mounts": mounts,
        "NetworkSettings": {
            "Networks": {
                f"{PROJECT}_backend": {"NetworkID": NETWORK_ID},
            }
        },
    }


class FakeDocker:
    def __init__(self, module) -> None:
        self.module = module
        self.calls: list[list[str]] = []
        self.containers = {
            service: _container(module, service) for service in module.EXPECTED_SERVICES
        }
        self.extra_inventory: list[tuple[str, str]] = []
        self.fail_inventory = False
        self.release_posture = "authoritative_runtime"
        self.release_gate_status = "pass"
        self.deploy_gate_status = "pass"
        self.supply_gate_status = "pass"
        self.docs_location = "/docs"
        self.security_headers = {
            "content-security-policy": "frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
            "permissions-policy": "camera=(), microphone=(), geolocation=(), interest-cohort=()",
            "referrer-policy": "strict-origin-when-cross-origin",
            "strict-transport-security": "max-age=31536000",
            "x-content-type-options": "nosniff",
            "x-ea-source-revision": REVISION,
            "x-frame-options": "DENY",
        }
        self.outbound = {service: True for service in module.CORE_SERVICES}

    def _http_payload(
        self,
        *,
        container_id: str,
        port: int,
        path: str,
        headers: dict[str, str],
    ) -> dict[str, object]:
        status = 200
        body: object = {"status": "ok"}
        response_headers: dict[str, str] = {
            "x-ea-source-revision": REVISION,
        }
        if path == "/health/release-authority":
            body = {
                "release_authority": {
                    "authority_posture": self.release_posture,
                },
                "release_authority_gate": {"status": self.release_gate_status},
                "deploy_context_gate": {"status": self.deploy_gate_status},
                "runtime_supply_chain_gate": {"status": self.supply_gate_status},
            }
        elif path == "/app/api/outcomes":
            status = 401
            body = {"error": {"code": "authentication_required"}}
        elif path == "/openapi.json":
            status = 404
            body = {"detail": "Not Found"}
        elif path == "/docs/":
            status = 307
            response_headers["location"] = self.docs_location
            body = ""
        elif path == "/health/ready" and port == 8091:
            body = {"status": "ready"}
        if headers.get("X-Forwarded-Proto") == "https":
            response_headers.update(self.security_headers)
        encoded = json.dumps(body, sort_keys=True).encode("utf-8")
        return {
            "body": base64.b64encode(encoded).decode("ascii"),
            "body_too_large": False,
            "headers": response_headers,
            "status": status,
        }

    def __call__(
        self, argv: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        command = list(argv)
        self.calls.append(command)
        if command[:3] == ["docker", "ps", "-a"]:
            if self.fail_inventory:
                return _completed(
                    command,
                    returncode=1,
                    stderr=f"daemon rejected token={SECRET}",
                )
            rows = [
                f"{SERVICE_IDS[service]}\t{service}"
                for service in self.module.EXPECTED_SERVICES
            ]
            rows.extend(
                f"{container_id}\t{service}"
                for container_id, service in self.extra_inventory
            )
            return _completed(command, stdout="\n".join(rows) + "\n")
        if command[:2] == ["docker", "inspect"]:
            by_id = {
                SERVICE_IDS[service]: self.containers[service]
                for service in self.module.EXPECTED_SERVICES
            }
            return _completed(
                command,
                stdout=json.dumps(
                    [by_id[container_id] for container_id in command[2:]]
                ),
            )
        if command[:3] == ["docker", "image", "inspect"]:
            return _completed(
                command,
                stdout=json.dumps(
                    [
                        {
                            "Id": IMAGE_ID,
                            "Config": {
                                "Labels": {
                                    self.module.SOURCE_REVISION_LABEL: REVISION,
                                }
                            },
                        }
                    ]
                ),
            )
        if command[:3] == ["docker", "network", "inspect"]:
            return _completed(
                command,
                stdout=json.dumps(
                    [
                        {
                            "Id": NETWORK_ID,
                            "Internal": True,
                            "Labels": {
                                "com.docker.compose.project": PROJECT,
                                "com.docker.compose.network": "backend",
                            },
                        }
                    ]
                ),
            )
        if command[:2] == ["docker", "exec"]:
            container_id = command[2]
            if command[5] == self.module._HTTP_PROBE_PROGRAM:
                payload = self._http_payload(
                    container_id=container_id,
                    port=int(command[6]),
                    path=command[7],
                    headers=json.loads(command[8]),
                )
                return _completed(command, stdout=json.dumps(payload))
            if command[5] == self.module._OUTBOUND_PROBE_PROGRAM:
                service = next(
                    name
                    for name, candidate_id in SERVICE_IDS.items()
                    if candidate_id == container_id
                )
                return _completed(
                    command,
                    stdout=json.dumps({"blocked": self.outbound[service]}),
                )
        raise AssertionError(f"unexpected command shape: {command[:5]}")


def _receipt(module, fake: FakeDocker) -> dict[str, object]:
    return module.build_receipt(
        project=PROJECT,
        expected_image_ref=IMAGE_REF,
        expected_image_id=IMAGE_ID,
        expected_source_revision=REVISION,
        runner=module._default_runner,
        now=datetime(2026, 7, 14, 1, 2, 3, tzinfo=timezone.utc),
    )


def test_candidate_runtime_verifier_passes_exact_seven_service_contract(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _module()
    fake = FakeDocker(module)
    monkeypatch.setattr(module.subprocess, "run", fake)

    receipt = _receipt(module, fake)

    assert receipt["status"] == "pass"
    assert receipt["issues"] == []
    assert receipt["generated_at"] == "2026-07-14T01:02:03Z"
    observations = receipt["observations"]
    assert observations["inventory"] == {
        "expected_service_count": 7,
        "discovered_service_count": 7,
        "exact_service_set": True,
    }
    assert [row["service"] for row in observations["services"]] == list(
        module.EXPECTED_SERVICES
    )
    assert all(row["passed"] for row in observations["probes"].values())
    assert observations["backend_network"]["internal"] is True
    serialized = json.dumps(receipt, sort_keys=True)
    assert SECRET not in serialized
    assert "POSTGRES_PASSWORD" not in serialized
    assert "EA_API_TOKEN" not in serialized
    mutating_words = {
        "compose",
        "down",
        "kill",
        "remove",
        "restart",
        "rm",
        "stop",
        "up",
    }
    for command in fake.calls:
        assert not (set(command[1:]) & mutating_words), command

    output = tmp_path / "nested" / "receipt.json"
    module.write_receipt(output, receipt)
    assert json.loads(output.read_text(encoding="utf-8")) == receipt
    mode = stat.S_IMODE(output.stat().st_mode)
    assert mode == 0o600
    assert output.stat().st_uid == os.getuid()


def test_main_emits_atomic_receipt_and_safe_summary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _module()
    fake = FakeDocker(module)
    monkeypatch.setattr(module.subprocess, "run", fake)
    output = tmp_path / "candidate.json"

    result = module.main(
        [
            "--compose-project",
            PROJECT,
            "--expected-image-ref",
            IMAGE_REF,
            "--expected-image-id",
            IMAGE_ID,
            "--expected-source-revision",
            REVISION,
            "--output",
            str(output),
        ]
    )

    assert result == 0
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    summary = json.loads(capsys.readouterr().out)
    assert summary == {
        "contract_name": module.CONTRACT_NAME,
        "issue_count": 0,
        "status": "pass",
    }


@pytest.mark.parametrize(
    "project,image_ref,image_id,revision,issue",
    (
        ("ea", IMAGE_REF, IMAGE_ID, REVISION, "compose_project_invalid"),
        (
            "ea-manfred-candidate-deadbeef",
            IMAGE_REF,
            IMAGE_ID,
            REVISION,
            "compose_project_invalid",
        ),
        (
            PROJECT,
            "ea-runtime:latest",
            IMAGE_ID,
            REVISION,
            "expected_image_ref_invalid",
        ),
        (PROJECT, IMAGE_REF, "sha256:short", REVISION, "expected_image_id_invalid"),
        (PROJECT, IMAGE_REF, IMAGE_ID, "A" * 40, "expected_source_revision_invalid"),
    ),
)
def test_invalid_scope_fails_before_any_docker_access(
    monkeypatch: pytest.MonkeyPatch,
    project: str,
    image_ref: str,
    image_id: str,
    revision: str,
    issue: str,
) -> None:
    module = _module()
    fake = FakeDocker(module)
    monkeypatch.setattr(module.subprocess, "run", fake)

    receipt = module.build_receipt(
        project=project,
        expected_image_ref=image_ref,
        expected_image_id=image_id,
        expected_source_revision=revision,
        runner=module._default_runner,
    )

    assert receipt["status"] == "fail"
    assert issue in receipt["issues"]
    assert fake.calls == []


def test_inventory_with_extra_service_fails_before_container_inspection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    fake = FakeDocker(module)
    fake.extra_inventory.append(("9" * 64, "rogue"))
    monkeypatch.setattr(module.subprocess, "run", fake)

    receipt = _receipt(module, fake)

    assert receipt["status"] == "fail"
    assert receipt["issues"] == ["candidate_service_set_invalid"]
    assert receipt["observations"]["inventory"] == {
        "expected_service_count": 7,
        "discovered_service_count": 8,
        "exact_service_set": False,
    }
    assert len(fake.calls) == 1
    assert fake.calls[0][:3] == ["docker", "ps", "-a"]


def test_container_inspection_revalidates_compose_project_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    fake = FakeDocker(module)
    fake.containers["api"]["Config"]["Labels"]["com.docker.compose.project"] = "ea"
    monkeypatch.setattr(module.subprocess, "run", fake)

    receipt = _receipt(module, fake)

    assert receipt["status"] == "fail"
    assert receipt["issues"] == ["candidate_container_inspection_invalid"]
    assert not any(command[:2] == ["docker", "exec"] for command in fake.calls)


def test_service_hardening_and_disabled_flag_failures_are_exact_and_redacted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    fake = FakeDocker(module)
    worker = copy.deepcopy(fake.containers["worker"])
    worker["RestartCount"] = 2
    worker["State"]["Health"]["Status"] = "unhealthy"
    worker["State"]["OOMKilled"] = True
    worker["HostConfig"].update(
        {
            "ReadonlyRootfs": False,
            "CapDrop": [],
            "SecurityOpt": [],
            "Binds": [f"/tmp/{SECRET}:/app/source"],
        }
    )
    worker["Mounts"] = [{"Type": "bind", "Source": f"/tmp/{SECRET}"}]
    worker["Image"] = "sha256:" + "d" * 64
    worker["Config"]["Env"] = [
        "EA_ENABLE_PUBLIC_TOURS=1" if row == "EA_ENABLE_PUBLIC_TOURS=0" else row
        for row in worker["Config"]["Env"]
    ]
    fake.containers["worker"] = worker
    monkeypatch.setattr(module.subprocess, "run", fake)

    receipt = _receipt(module, fake)

    assert receipt["status"] == "fail"
    expected = {
        "service_worker_not_healthy",
        "service_worker_restart_count_nonzero",
        "service_worker_oom_state_invalid",
        "service_worker_rootfs_not_read_only",
        "service_worker_cap_drop_all_missing",
        "service_worker_no_new_privileges_missing",
        "service_worker_bind_mount_present",
        "service_worker_image_id_mismatch",
        "service_worker_ea_enable_public_tours_not_disabled",
    }
    assert expected <= set(receipt["issues"])
    serialized = json.dumps(receipt, sort_keys=True)
    assert SECRET not in serialized
    assert "/tmp/" not in serialized


def test_stateful_services_must_also_drop_all_capabilities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    fake = FakeDocker(module)
    fake.containers["postgres"]["HostConfig"]["CapDrop"] = None
    fake.containers["redis"]["HostConfig"]["CapDrop"] = []
    monkeypatch.setattr(module.subprocess, "run", fake)

    receipt = _receipt(module, fake)

    assert "service_postgres_cap_drop_all_missing" in receipt["issues"]
    assert "service_redis_cap_drop_all_missing" in receipt["issues"]


def test_runtime_probe_failures_do_not_project_raw_bodies_or_subprocess_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    fake = FakeDocker(module)
    fake.release_posture = "watch"
    fake.release_gate_status = "fail"
    fake.docs_location = "http://origin.internal/docs"
    fake.security_headers.pop("x-frame-options")
    fake.outbound["scheduler"] = False
    monkeypatch.setattr(module.subprocess, "run", fake)

    receipt = _receipt(module, fake)

    assert receipt["status"] == "fail"
    assert {
        "release_authority_probe_failed",
        "docs_slash_redirect_probe_failed",
        "trusted_proxy_security_headers_probe_failed",
        "outbound_network_probe_failed",
    } <= set(receipt["issues"])
    serialized = json.dumps(receipt, sort_keys=True)
    assert "origin.internal" not in serialized
    assert "authority_posture" not in serialized
    assert receipt["privacy"] == {
        "environment_values_emitted": False,
        "secret_values_emitted": False,
        "raw_http_bodies_emitted": False,
        "raw_subprocess_output_emitted": False,
    }


def test_docker_failure_emits_only_bounded_error_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    fake = FakeDocker(module)
    fake.fail_inventory = True
    monkeypatch.setattr(module.subprocess, "run", fake)

    receipt = _receipt(module, fake)

    assert receipt["status"] == "fail"
    assert receipt["issues"] == ["candidate_inventory_command_failed"]
    assert SECRET not in json.dumps(receipt, sort_keys=True)
