from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Callable

import pytest

from scripts import ea_memorial_runtime_identity as identity


CONFIG_HASH = "a" * 64
IMAGE_ID = "sha256:" + "b" * 64
RUNTIME_DOMAINS = (
    "source_role",
    "image",
    "environment",
    "process",
    "healthcheck",
    "restart_policy",
    "user_and_groups",
    "capabilities_and_security_options",
    "privileged_and_read_only_posture",
    "resource_limits",
    "ports",
    "logging",
    "mounts",
    "networks_and_aliases",
    "labels",
)


def _inspection() -> dict[str, object]:
    return {
        "Id": "old-container-id",
        "Created": "2026-07-21T00:00:00Z",
        "Name": "/ea-api",
        "Image": IMAGE_ID,
        "Config": {
            "Image": "ea-runtime:memorial-main",
            "Env": ["TOKEN=supersecret", "EA_SOURCE_REVISION=abc"],
            "Cmd": ["python", "-m", "app"],
            "Entrypoint": ["/entrypoint"],
            "WorkingDir": "/app",
            "Domainname": "ea.internal",
            "NetworkDisabled": False,
            "ArgsEscaped": False,
            "Shell": ["/bin/sh", "-c"],
            "AttachStdin": False,
            "AttachStdout": True,
            "AttachStderr": True,
            "Tty": False,
            "OpenStdin": False,
            "StdinOnce": False,
            "User": "1000:1000",
            "Healthcheck": {
                "Test": ["CMD", "curl", "-f", "http://localhost/health"],
                "Interval": 30_000_000_000,
                "Timeout": 5_000_000_000,
                "Retries": 3,
                "StartPeriod": 1_000_000_000,
            },
            "StopSignal": "SIGTERM",
            "StopTimeout": 10,
            "ExposedPorts": {"8000/tcp": {}},
            "Labels": {
                identity.COMPOSE_CONFIG_HASH_LABEL: CONFIG_HASH,
                identity.COMPOSE_PROJECT_LABEL: "ea",
                identity.COMPOSE_SERVICE_LABEL: "ea-api",
                "com.docker.compose.project.working_dir": "/old/root",
                "com.docker.compose.project.config_files": "/old/compose.yml",
                "com.docker.compose.project.environment_file": "/old/.env",
                "org.opencontainers.image.revision": "revision",
                "private.label": "label-secret",
            },
        },
        "HostConfig": {
            "RestartPolicy": {"Name": "unless-stopped", "MaximumRetryCount": 0},
            "AutoRemove": False,
            "GroupAdd": ["44", "109"],
            "CapAdd": ["NET_BIND_SERVICE"],
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges:true"],
            "Runtime": "runc",
            "Init": True,
            "ConsoleSize": [0, 0],
            "Isolation": "",
            "CgroupnsMode": "private",
            "IpcMode": "private",
            "PidMode": "",
            "UTSMode": "",
            "UsernsMode": "",
            "MaskedPaths": ["/proc/kcore"],
            "ReadonlyPaths": ["/proc/bus"],
            "Sysctls": {"net.ipv4.ip_unprivileged_port_start": "0"},
            "Privileged": False,
            "ReadonlyRootfs": True,
            "Tmpfs": {"/run": "rw,noexec,nosuid,size=65536k"},
            "StorageOpt": {"size": "10G"},
            "Memory": 512_000_000,
            "NanoCpus": 1_000_000_000,
            "ShmSize": 64_000_000,
            "PortBindings": {
                "8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "18000"}]
            },
            "PublishAllPorts": False,
            "LogConfig": {"Type": "json-file", "Config": {"token": "log-secret"}},
            "NetworkMode": "ea_default",
            "Dns": [],
            "DnsOptions": [],
            "DnsSearch": [],
            "ExtraHosts": [],
            "Links": [],
        },
        "Mounts": [
            {
                "Type": "bind",
                "Source": "/srv/data",
                "Destination": "/data",
                "Driver": "",
                "Mode": "ro",
                "RW": False,
                "Propagation": "rprivate",
            }
        ],
        "NetworkSettings": {
            "EndpointID": "old-endpoint-id",
            "Ports": {"8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "18000"}]},
            "Networks": {
                "ea_default": {
                    "NetworkID": "opaque-network-id",
                    "EndpointID": "opaque-endpoint-id",
                    "IPAMConfig": None,
                    "Links": [],
                    "Aliases": ["ea-api", "api"],
                    "DriverOpts": {"private": "driver-secret"},
                    "MacAddress": "02:42:ac:12:00:02",
                    "Gateway": "172.18.0.1",
                    "IPAddress": "172.18.0.2",
                    "IPPrefixLen": 16,
                    "IPv6Gateway": "",
                    "GlobalIPv6Address": "",
                    "GlobalIPv6PrefixLen": 0,
                }
            },
        },
    }


def _cloudflared_inspection() -> dict[str, object]:
    payload = _inspection()
    payload["Name"] = "/externalbrain-cloudflared"
    payload["Config"]["Image"] = "cloudflare/cloudflared:stable"  # type: ignore[index]
    payload["Config"]["Labels"][identity.COMPOSE_SERVICE_LABEL] = (  # type: ignore[index]
        "ea-cloudflared"
    )
    return payload


def _set(
    path: tuple[object, ...], value: object
) -> Callable[[dict[str, object]], None]:
    def mutate(payload: dict[str, object]) -> None:
        target: object = payload
        for key in path[:-1]:
            target = target[key]  # type: ignore[index]
        target[path[-1]] = value  # type: ignore[index]

    return mutate


@pytest.mark.parametrize(
    ("domain", "mutate"),
    [
        ("image", _set(("Config", "Image"), "ea-runtime:other")),
        ("environment", _set(("Config", "Env"), ["TOKEN=changed"])),
        ("process", _set(("Config", "Cmd"), ["python", "other.py"])),
        ("process", _set(("Config", "StopSignal"), "SIGINT")),
        ("process", _set(("Config", "StopTimeout"), 20)),
        ("process", _set(("HostConfig", "Init"), False)),
        ("process", _set(("Config", "Domainname"), "other.internal")),
        ("process", _set(("Config", "NetworkDisabled"), True)),
        ("process", _set(("Config", "ArgsEscaped"), True)),
        ("process", _set(("Config", "Shell"), ["/bin/bash", "-c"])),
        ("process", _set(("Config", "AttachStdout"), False)),
        ("process", _set(("Config", "Tty"), True)),
        ("process", _set(("HostConfig", "ConsoleSize"), [24, 80])),
        ("healthcheck", _set(("Config", "Healthcheck", "Retries"), 9)),
        ("restart_policy", _set(("HostConfig", "RestartPolicy", "Name"), "always")),
        ("user_and_groups", _set(("Config", "User"), "2000:2000")),
        (
            "capabilities_and_security_options",
            _set(("HostConfig", "CapAdd"), ["SYS_ADMIN"]),
        ),
        (
            "capabilities_and_security_options",
            _set(("HostConfig", "Sysctls"), {"kernel.shm_rmid_forced": "1"}),
        ),
        ("privileged_and_read_only_posture", _set(("HostConfig", "Privileged"), True)),
        (
            "privileged_and_read_only_posture",
            _set(("HostConfig", "Tmpfs"), {"/run": "rw,size=32768k"}),
        ),
        (
            "privileged_and_read_only_posture",
            _set(("HostConfig", "StorageOpt"), {"size": "20G"}),
        ),
        ("resource_limits", _set(("HostConfig", "Memory"), 256_000_000)),
        (
            "resource_limits",
            _set(
                ("HostConfig", "DeviceRequests"),
                [
                    {
                        "Driver": "nvidia",
                        "Count": 1,
                        "DeviceIDs": ["gpu-1"],
                        "Capabilities": [["gpu"]],
                        "Options": {},
                    }
                ],
            ),
        ),
        ("ports", _set(("HostConfig", "PublishAllPorts"), True)),
        ("logging", _set(("HostConfig", "LogConfig", "Type"), "local")),
        ("mounts", _set(("Mounts", 0, "Propagation"), "rshared")),
        (
            "networks_and_aliases",
            _set(("NetworkSettings", "Networks", "ea_default", "Aliases"), ["other"]),
        ),
        (
            "labels",
            _set(("Config", "Labels", "org.opencontainers.image.revision"), "other"),
        ),
    ],
)
def test_each_runtime_drift_reports_its_exact_domain(
    domain: str, mutate: Callable[[dict[str, object]], None]
) -> None:
    before = _inspection()
    after = copy.deepcopy(before)
    mutate(after)

    expected = identity.memorial_api_runtime_projection(before)
    observed = identity.memorial_api_runtime_projection(after)

    assert identity.runtime_mismatch_domains(expected, observed) == [domain]
    report = identity.runtime_comparison_report(expected, observed)
    assert report["match"] is False
    assert report["mismatch_domains"] == [domain]


def test_api_projection_is_secret_free_and_environment_order_is_canonical() -> None:
    before = _inspection()
    before["Config"]["Cmd"] = [  # type: ignore[index]
        "sh",
        "-c",
        "client --token=cmd-token-value",
    ]
    before["Config"]["Entrypoint"] = [  # type: ignore[index]
        "/entrypoint",
        "--password=entrypoint-password-value",
    ]
    before["Config"]["Healthcheck"]["Test"] = [  # type: ignore[index]
        "CMD-SHELL",
        "curl -H 'Authorization: Bearer healthcheck-token-value' localhost/health",
    ]
    before["Config"]["Shell"] = [  # type: ignore[index]
        "/bin/sh",
        "shell-token-value",
    ]
    before["Config"]["Domainname"] = "domainname-password-value"  # type: ignore[index]
    before["Config"]["StopSignal"] = "stop-signal-token-value"  # type: ignore[index]
    before["HostConfig"]["Sysctls"] = {  # type: ignore[index]
        "private.key": "sysctl-token-value"
    }
    before["HostConfig"]["Tmpfs"] = {  # type: ignore[index]
        "/run": "password=tmpfs-password-value"
    }
    before["HostConfig"]["StorageOpt"] = {  # type: ignore[index]
        "private": "storage-token-value"
    }
    before["HostConfig"]["DeviceRequests"] = [  # type: ignore[index]
        {
            "Driver": "resource-driver-token-value",
            "Count": 1,
            "DeviceIDs": ["resource-device-token-value"],
            "Capabilities": [["gpu", "resource-capability-token-value"]],
            "Options": {"password": "resource-password-value"},
        }
    ]
    before["HostConfig"]["Devices"] = [  # type: ignore[index]
        {
            "PathOnHost": "/dev/resource-path-token-value",
            "PathInContainer": "/dev/gpu",
            "CgroupPermissions": "rwm",
        }
    ]
    reordered = copy.deepcopy(before)
    reordered["Config"]["Env"].reverse()  # type: ignore[index]

    projected = identity.memorial_api_runtime_projection(before)
    encoded = json.dumps(projected, sort_keys=True)

    assert projected["schema"] == "ea.memorial_container_runtime_identity.v2"
    assert "supersecret" not in encoded
    assert "label-secret" not in encoded
    assert "log-secret" not in encoded
    assert "driver-secret" not in encoded
    assert "cmd-token-value" not in encoded
    assert "entrypoint-password-value" not in encoded
    assert "healthcheck-token-value" not in encoded
    assert "sysctl-token-value" not in encoded
    assert "tmpfs-password-value" not in encoded
    assert "storage-token-value" not in encoded
    assert "shell-token-value" not in encoded
    assert "domainname-password-value" not in encoded
    assert "stop-signal-token-value" not in encoded
    assert "resource-driver-token-value" not in encoded
    assert "resource-device-token-value" not in encoded
    assert "resource-capability-token-value" not in encoded
    assert "resource-password-value" not in encoded
    assert "resource-path-token-value" not in encoded
    assert "/old/root" not in encoded
    assert "/old/compose.yml" not in encoded
    assert "/old/.env" not in encoded
    assert projected["process"]["command"]["argument_count"] == 3  # type: ignore[index]
    assert projected["process"]["entrypoint"]["argument_count"] == 2  # type: ignore[index]
    assert projected["healthcheck"]["test"]["argument_count"] == 2  # type: ignore[index]
    assert projected["process"]["shell"]["argument_count"] == 2  # type: ignore[index]
    expected_environment = ["EA_SOURCE_REVISION=abc", "TOKEN=supersecret"]
    expected_environment_digest = hashlib.sha256(
        json.dumps(
            expected_environment,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    assert projected["environment"] == {  # type: ignore[index]
        "environment_count": 2,
        "environment_sha256": expected_environment_digest,
    }
    assert projected == identity.memorial_api_runtime_projection(reordered)


def test_api_allows_only_topology_label_value_changes() -> None:
    before = _inspection()
    after = copy.deepcopy(before)
    for key in identity.TOPOLOGY_LABELS:
        after["Config"]["Labels"][key] = (  # type: ignore[index]
            "f" * 64
            if key == identity.COMPOSE_CONFIG_HASH_LABEL
            else f"new:{key}"
        )

    expected = identity.memorial_api_runtime_projection(before)
    observed = identity.memorial_api_runtime_projection(after)

    assert identity.runtime_mismatch_domains(expected, observed) == []
    assert expected["topology_label_evidence"] != observed["topology_label_evidence"]
    for key in identity.TOPOLOGY_LABELS:
        before_value = before["Config"]["Labels"][key]  # type: ignore[index]
        after_value = after["Config"]["Labels"][key]  # type: ignore[index]
        assert expected["topology_label_evidence"][key] == {  # type: ignore[index]
            "value_bytes": len(before_value.encode("utf-8")),
            "value_sha256": hashlib.sha256(before_value.encode("utf-8")).hexdigest(),
        }
        assert observed["topology_label_evidence"][key] == {  # type: ignore[index]
            "value_bytes": len(after_value.encode("utf-8")),
            "value_sha256": hashlib.sha256(after_value.encode("utf-8")).hexdigest(),
        }
    report = identity.runtime_comparison_report(expected, observed)
    assert report["expected_topology_label_evidence"] == expected[
        "topology_label_evidence"
    ]
    assert report["observed_topology_label_evidence"] == observed[
        "topology_label_evidence"
    ]
    assert "expected_topology_label_values" not in report
    assert "observed_topology_label_values" not in report
    encoded_report = json.dumps(report, sort_keys=True)
    assert "/old/root" not in encoded_report
    assert "/old/compose.yml" not in encoded_report
    assert "/old/.env" not in encoded_report

    cloudflared_before_inspection = _cloudflared_inspection()
    cloudflared_after_inspection = copy.deepcopy(cloudflared_before_inspection)
    for key in identity.TOPOLOGY_LABELS:
        cloudflared_after_inspection["Config"]["Labels"][key] = (  # type: ignore[index]
            "f" * 64
            if key == identity.COMPOSE_CONFIG_HASH_LABEL
            else f"new:{key}"
        )
    cloudflared_before = identity.cloudflared_runtime_projection(
        cloudflared_before_inspection
    )
    cloudflared_after = identity.cloudflared_runtime_projection(
        cloudflared_after_inspection
    )
    assert identity.runtime_mismatch_domains(cloudflared_before, cloudflared_after) == [
        "labels"
    ]


def test_container_and_endpoint_evidence_is_not_runtime_identity() -> None:
    before = _inspection()
    after = copy.deepcopy(before)
    after["Id"] = "new-container-id"
    after["Created"] = "2026-07-22T00:00:00Z"
    after["NetworkSettings"]["EndpointID"] = "new"  # type: ignore[index]
    network = after["NetworkSettings"]["Networks"]["ea_default"]  # type: ignore[index]
    network["EndpointID"] = "new"
    network["NetworkID"] = "new"

    assert identity.memorial_api_runtime_projection(
        before
    ) == identity.memorial_api_runtime_projection(after)


@pytest.mark.parametrize(
    "mutate",
    [
        _set(("Image",), "not-an-image-id"),
        _set(("Config", "Env"), ["missing-equals"]),
        _set(("Config", "Env"), ["A=1", "A=2"]),
        _set(("Config", "Labels", identity.COMPOSE_CONFIG_HASH_LABEL), "short"),
        _set(("Config", "Labels", "com.docker.compose.project.working_dir"), None),
        _set(("HostConfig", "Privileged"), "false"),
        _set(("Config", "Cmd"), "python app.py"),
        _set(("Config", "Entrypoint"), 1),
        _set(("Config", "Healthcheck", "Test"), "curl localhost/health"),
        _set(("Config", "Shell"), "/bin/sh"),
        _set(("Config", "AttachStdin"), None),
        _set(("Config", "AttachStdout"), "true"),
        _set(("Config", "AttachStderr"), 1),
        _set(("Config", "Tty"), 0),
        _set(("Config", "OpenStdin"), []),
        _set(("Config", "StdinOnce"), {}),
        _set(("Config", "Domainname"), None),
        _set(("Config", "NetworkDisabled"), None),
        _set(("Config", "ArgsEscaped"), 0),
        _set(("HostConfig", "ConsoleSize"), [0]),
        _set(("HostConfig", "ConsoleSize"), [0, "0"]),
        _set(("HostConfig", "Init"), "true"),
        _set(("HostConfig", "Sysctls"), {"net.ipv4.ip_forward": 1}),
        _set(("HostConfig", "Tmpfs"), {"/run": 1}),
        _set(("HostConfig", "StorageOpt"), {"size": 10}),
        _set(("Config", "StopSignal"), None),
        _set(("Config", "StopTimeout"), True),
        _set(("HostConfig", "GroupAdd"), {}),
        _set(("HostConfig", "CapAdd"), ""),
        _set(("HostConfig", "CapDrop"), {}),
        _set(("HostConfig", "SecurityOpt"), ""),
        _set(("HostConfig", "MaskedPaths"), {}),
        _set(("HostConfig", "ReadonlyPaths"), ""),
        _set(("HostConfig", "Dns"), {}),
        _set(("HostConfig", "DnsOptions"), ""),
        _set(("HostConfig", "DnsSearch"), {}),
        _set(("HostConfig", "ExtraHosts"), ""),
        _set(("HostConfig", "Links"), {}),
        _set(("NetworkSettings", "Networks", "ea_default", "Aliases"), {}),
        _set(("NetworkSettings", "Networks", "ea_default", "Links"), ""),
        _set(
            ("NetworkSettings", "Networks", "ea_default", "IPAMConfig"),
            {"LinkLocalIPs": {}},
        ),
        _set(("Config", "ExposedPorts"), {"not-a-port": {}}),
        _set(("Config", "ExposedPorts"), {"8000/tcp": {"extra": True}}),
        _set(("Config", "ExposedPorts"), {"8000/tcp": None}),
        _set(
            ("HostConfig", "PortBindings"),
            {"8000/tcp": [{"HostIp": "", "HostPort": "8000", "Extra": "x"}]},
        ),
        _set(("Mounts",), {}),
        _set(("NetworkSettings", "Networks"), []),
    ],
)
def test_malformed_inspection_is_rejected(
    mutate: Callable[[dict[str, object]], None],
) -> None:
    payload = _inspection()
    mutate(payload)

    with pytest.raises(identity.RuntimeIdentityError, match="runtime_identity_invalid"):
        identity.memorial_api_runtime_projection(payload)


@pytest.mark.parametrize("domain", RUNTIME_DOMAINS)
def test_runtime_digest_rejects_null_mandatory_domain(domain: str) -> None:
    projected = identity.memorial_api_runtime_projection(_inspection())
    projected[domain] = None

    with pytest.raises(identity.RuntimeIdentityError, match=f"projection.{domain}"):
        identity.runtime_identity_digests(projected)


@pytest.mark.parametrize("domain", RUNTIME_DOMAINS)
def test_runtime_digest_rejects_absent_mandatory_domain(domain: str) -> None:
    projected = identity.memorial_api_runtime_projection(_inspection())
    del projected[domain]

    with pytest.raises(identity.RuntimeIdentityError, match="projection"):
        identity.runtime_identity_digests(projected)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value["environment"].pop("environment_sha256"),
        lambda value: value["process"].pop("command"),
        lambda value: value["healthcheck"].pop("test"),
        lambda value: value["capabilities_and_security_options"].pop("sysctls"),
        lambda value: value["privileged_and_read_only_posture"].pop("tmpfs"),
        lambda value: value["labels"].update({"unexpected": "value"}),
        lambda value: value.update({"unexpected": "value"}),
    ],
)
def test_runtime_digest_rejects_incomplete_or_extended_nested_schema(
    mutate: Callable[[dict[str, object]], None],
) -> None:
    projected = identity.memorial_api_runtime_projection(_inspection())
    mutate(projected)

    with pytest.raises(identity.RuntimeIdentityError, match="runtime_identity_invalid"):
        identity.runtime_identity_digests(projected)


@pytest.mark.parametrize(
    "mutate",
    [
        _set(("schema",), "ea.memorial_container_runtime_identity.v1"),
        _set(("schema",), "ea.memorial_container_runtime_identity.unknown"),
        _set(("projection_kind",), None),
        _set(("source_role", "compose_service"), "other"),
        _set(("environment", "environment_count"), True),
        _set(("environment", "environment_sha256"), "short"),
        _set(("process", "command", "argument_count"), "3"),
        _set(("process", "command", "arguments_sha256"), "short"),
        _set(("process", "domainname"), "plaintext.invalid"),
        _set(("process", "stop_signal", "value_sha256"), "short"),
        _set(("process", "stop_timeout_seconds"), -1),
        _set(("process", "io", "console_size"), [0]),
        _set(("capabilities_and_security_options", "sysctls", "present"), 1),
        _set(("resource_limits", "DeviceRequests", "items_sha256"), "short"),
    ],
)
def test_runtime_digest_rejects_malformed_projection_values(
    mutate: Callable[[dict[str, object]], None],
) -> None:
    projected = identity.memorial_api_runtime_projection(_inspection())
    mutate(projected)

    with pytest.raises(identity.RuntimeIdentityError, match="runtime_identity_invalid"):
        identity.runtime_identity_digests(projected)


def test_runtime_digest_rejects_swapped_domains_and_projection_roles() -> None:
    projected = identity.memorial_api_runtime_projection(_inspection())
    projected["image"], projected["environment"] = (
        projected["environment"],
        projected["image"],
    )
    with pytest.raises(identity.RuntimeIdentityError, match="projection.image"):
        identity.runtime_identity_digests(projected)

    api = identity.memorial_api_runtime_projection(_inspection())
    cloudflared = identity.cloudflared_runtime_projection(_cloudflared_inspection())
    with pytest.raises(
        identity.RuntimeIdentityError, match="projection.projection_kind"
    ):
        identity.runtime_mismatch_domains(api, cloudflared)


@pytest.mark.parametrize(
    "mutate",
    [
        _set(("Name",), "/renamed-api"),
        _set(("Config", "Labels", identity.COMPOSE_PROJECT_LABEL), "other"),
        _set(("Config", "Labels", identity.COMPOSE_SERVICE_LABEL), "other"),
    ],
)
def test_container_source_role_binding_is_exact(
    mutate: Callable[[dict[str, object]], None],
) -> None:
    api = _inspection()
    mutate(api)
    with pytest.raises(identity.RuntimeIdentityError, match="runtime_identity_invalid"):
        identity.memorial_api_runtime_projection(api)

    edge = _cloudflared_inspection()
    mutate(edge)
    with pytest.raises(identity.RuntimeIdentityError, match="runtime_identity_invalid"):
        identity.cloudflared_runtime_projection(edge)


def test_cross_role_inspection_is_rejected_before_projection() -> None:
    with pytest.raises(identity.RuntimeIdentityError, match="runtime_identity_invalid"):
        identity.memorial_api_runtime_projection(_cloudflared_inspection())
    with pytest.raises(identity.RuntimeIdentityError, match="runtime_identity_invalid"):
        identity.cloudflared_runtime_projection(_inspection())


def test_runtime_digest_rejects_missing_or_tampered_topology_evidence() -> None:
    projected = identity.memorial_api_runtime_projection(_inspection())
    missing = copy.deepcopy(projected)
    missing["topology_label_evidence"].pop(  # type: ignore[union-attr]
        "com.docker.compose.project.working_dir"
    )
    with pytest.raises(
        identity.RuntimeIdentityError, match="projection.topology_label_evidence"
    ):
        identity.runtime_identity_digests(missing)

    tampered = copy.deepcopy(projected)
    evidence = tampered["topology_label_evidence"][  # type: ignore[index]
        "com.docker.compose.project.working_dir"
    ]
    evidence["value_sha256"] = "short"
    with pytest.raises(
        identity.RuntimeIdentityError, match="projection.topology_label_evidence"
    ):
        identity.runtime_identity_digests(tampered)


def test_nullable_docker_resource_lists_are_preserved_and_type_checked() -> None:
    payload = _inspection()
    for key in (
        "BlkioWeightDevice",
        "BlkioDeviceReadBps",
        "BlkioDeviceWriteBps",
        "BlkioDeviceReadIOps",
        "BlkioDeviceWriteIOps",
        "Devices",
        "Ulimits",
    ):
        payload["HostConfig"][key] = None  # type: ignore[index]

    projected = identity.memorial_api_runtime_projection(payload)
    assert all(
        projected["resource_limits"][key]  # type: ignore[index]
        == {
            "present": False,
            "item_count": 0,
            "items_sha256": hashlib.sha256(b"[]").hexdigest(),
        }
        for key in (
            "BlkioWeightDevice",
            "BlkioDeviceReadBps",
            "BlkioDeviceWriteBps",
            "BlkioDeviceReadIOps",
            "BlkioDeviceWriteIOps",
            "Devices",
            "Ulimits",
        )
    )

    malformed = copy.deepcopy(payload)
    malformed["HostConfig"]["Devices"] = "not-a-list"  # type: ignore[index]
    with pytest.raises(
        identity.RuntimeIdentityError,
        match="HostConfig.Devices",
    ):
        identity.memorial_api_runtime_projection(malformed)


def test_all_nested_resource_collections_are_digest_only() -> None:
    payload = _inspection()
    resources = {
        "BlkioWeightDevice": [
            {"Path": "/dev/resource-weight-secret", "Weight": 100}
        ],
        "BlkioDeviceReadBps": [
            {"Path": "/dev/resource-read-bps-secret", "Rate": 1}
        ],
        "BlkioDeviceWriteBps": [
            {"Path": "/dev/resource-write-bps-secret", "Rate": 2}
        ],
        "BlkioDeviceReadIOps": [
            {"Path": "/dev/resource-read-iops-secret", "Rate": 3}
        ],
        "BlkioDeviceWriteIOps": [
            {"Path": "/dev/resource-write-iops-secret", "Rate": 4}
        ],
        "Devices": [
            {
                "PathOnHost": "/dev/resource-device-secret",
                "PathInContainer": "/dev/gpu",
                "CgroupPermissions": "rwm",
            }
        ],
        "DeviceCgroupRules": ["c resource-cgroup-secret:* rwm"],
        "DeviceRequests": [
            {
                "Driver": "resource-request-secret",
                "Count": 1,
                "DeviceIDs": ["resource-device-id-secret"],
                "Capabilities": [["resource-capability-secret"]],
                "Options": {"token": "resource-option-secret"},
            }
        ],
        "Ulimits": [
            {"Name": "resource-ulimit-secret", "Hard": 100, "Soft": 50}
        ],
    }
    payload["HostConfig"].update(resources)  # type: ignore[union-attr]

    projected = identity.memorial_api_runtime_projection(payload)
    encoded = json.dumps(projected, sort_keys=True)
    for key in resources:
        assert set(projected["resource_limits"][key]) == {  # type: ignore[index]
            "present",
            "item_count",
            "items_sha256",
        }
    assert "resource-" not in encoded


@pytest.mark.parametrize(
    "device_request",
    [
        {},
        {
            "Driver": "nvidia",
            "Count": True,
            "DeviceIDs": None,
            "Capabilities": None,
            "Options": {},
        },
        {
            "Driver": "nvidia",
            "Count": 1,
            "DeviceIDs": {},
            "Capabilities": None,
            "Options": {},
        },
        {
            "Driver": "nvidia",
            "Count": 1,
            "DeviceIDs": None,
            "Capabilities": ["gpu"],
            "Options": {},
        },
        {
            "Driver": "nvidia",
            "Count": 1,
            "DeviceIDs": None,
            "Capabilities": None,
            "Options": {"token": 1},
        },
    ],
)
def test_device_requests_require_exact_docker_types(device_request: object) -> None:
    payload = _inspection()
    payload["HostConfig"]["DeviceRequests"] = [  # type: ignore[index]
        device_request
    ]

    with pytest.raises(
        identity.RuntimeIdentityError, match="HostConfig.DeviceRequests"
    ):
        identity.memorial_api_runtime_projection(payload)


def _public_network() -> dict[str, object]:
    return {
        "Id": "old-network-id",
        "Created": "2026-07-21T00:00:00Z",
        "Name": identity.PUBLIC_NETWORK_NAME,
        "Driver": "bridge",
        "Scope": "local",
        "EnableIPv6": False,
        "Internal": False,
        "Attachable": True,
        "Ingress": False,
        "ConfigOnly": False,
        "ConfigFrom": {"Network": ""},
        "IPAM": {
            "Driver": "default",
            "Options": {},
            "Config": [{"Subnet": "172.20.0.0/16", "Gateway": "172.20.0.1"}],
        },
        "Options": {"com.docker.network.bridge.enable_icc": "true"},
        "Labels": {"com.docker.compose.network": "public_ingress"},
        "Containers": {
            "old-api-id": {
                "Name": "ea-api",
                "IPv4Address": "172.20.0.2/16",
                "IPv6Address": "",
                "MacAddress": "02:42:ac:14:00:02",
                "EndpointID": "endpoint-a",
            },
            "old-edge-id": {
                "Name": "externalbrain-cloudflared",
                "IPv4Address": "172.20.0.3/16",
                "IPv6Address": "",
                "MacAddress": "02:42:ac:14:00:03",
                "EndpointID": "endpoint-b",
            },
        },
    }


def test_public_network_projection_uses_stable_semantics_not_ids() -> None:
    before = _public_network()
    after = copy.deepcopy(before)
    after["Id"] = "new-network-id"
    after["Created"] = "later"
    after["Containers"] = {  # type: ignore[assignment]
        "new-api-id": before["Containers"]["old-api-id"],  # type: ignore[index]
        "new-edge-id": before["Containers"]["old-edge-id"],  # type: ignore[index]
    }

    expected = identity.public_network_semantic_projection(before)
    assert expected == identity.public_network_semantic_projection(after)

    after["Containers"]["new-api-id"]["IPv4Address"] = "172.20.0.9/16"  # type: ignore[index]
    assert expected != identity.public_network_semantic_projection(after)


def test_public_network_projection_is_name_bound_and_secret_free() -> None:
    payload = _public_network()
    payload["IPAM"]["Options"] = {"token": "ipam-option-secret"}  # type: ignore[index]
    payload["IPAM"]["Config"][0]["AuxiliaryAddresses"] = {  # type: ignore[index]
        "private": "auxiliary-address-secret"
    }
    payload["Options"] = {"token": "network-option-secret"}
    payload["Labels"] = {"private": "network-label-secret"}

    projected = identity.public_network_semantic_projection(payload)
    encoded = json.dumps(projected, sort_keys=True)
    assert "ipam-option-secret" not in encoded
    assert "auxiliary-address-secret" not in encoded
    assert "network-option-secret" not in encoded
    assert "network-label-secret" not in encoded
    assert identity.validate_public_network_semantic_projection(projected) == projected

    payload["Name"] = "ea-public-ingress"
    with pytest.raises(identity.RuntimeIdentityError, match="runtime_identity_invalid:Name"):
        identity.public_network_semantic_projection(payload)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.pop("members"),
        lambda value: value.update({"unexpected": True}),
        lambda value: value["ipam"].pop("driver"),
        lambda value: value["members"][0].update({"unexpected": True}),
        lambda value: value["options"].update({"sha256": "short"}),
        lambda value: value.update({"name": "ea-public-ingress"}),
    ],
)
def test_exported_public_network_validator_rejects_incomplete_or_malformed_shape(
    mutate: Callable[[dict[str, object]], None],
) -> None:
    projected = identity.public_network_semantic_projection(_public_network())
    mutate(projected)

    with pytest.raises(identity.RuntimeIdentityError, match="runtime_identity_invalid"):
        identity.validate_public_network_semantic_projection(projected)


@pytest.mark.parametrize(
    "mutate",
    [
        _set(("ConfigFrom",), {}),
        _set(("ConfigFrom",), {"Network": "", "Extra": "x"}),
        _set(("IPAM", "Options"), []),
        _set(("Options",), ""),
        _set(("Labels",), []),
        _set(("IPAM", "Config"), {}),
        _set(("IPAM", "Config"), [{"Unknown": "value"}]),
    ],
)
def test_public_network_raw_docker_types_are_fail_closed(
    mutate: Callable[[dict[str, object]], None],
) -> None:
    payload = _public_network()
    mutate(payload)

    with pytest.raises(identity.RuntimeIdentityError, match="runtime_identity_invalid"):
        identity.public_network_semantic_projection(payload)
