#!/usr/bin/env python3
"""Secret-free, stable identity projections for Memorial Docker state.

The functions in this module are deliberately pure.  Callers must collect
Docker inspection payloads themselves; this module only validates and projects
those JSON values for exact before/after comparison.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from typing import Any


IDENTITY_SCHEMA = "ea.memorial_container_runtime_identity.v2"
PUBLIC_NETWORK_SCHEMA = "ea.memorial_public_network_identity.v1"
COMPOSE_CONFIG_HASH_LABEL = "com.docker.compose.config-hash"
COMPOSE_PROJECT_LABEL = "com.docker.compose.project"
COMPOSE_SERVICE_LABEL = "com.docker.compose.service"
PUBLIC_NETWORK_NAME = "ea_public_ingress"
TOPOLOGY_LABELS = frozenset(
    {
        "com.docker.compose.project.working_dir",
        "com.docker.compose.project.config_files",
        "com.docker.compose.project.environment_file",
    }
)

_IMAGE_ID_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_CONFIG_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_DOCKER_PORT_PATTERN = re.compile(
    r"^(?P<first>[1-9][0-9]{0,4})(?:-(?P<last>[1-9][0-9]{0,4}))?/(?P<protocol>tcp|udp|sctp)$"
)
_API_PROJECTION_KIND = "memorial_api"
_CLOUDFLARED_PROJECTION_KIND = "cloudflared"
_RUNTIME_ROLES = {
    _API_PROJECTION_KIND: {
        "container_name": "/ea-api",
        "compose_project": "ea",
        "compose_service": "ea-api",
    },
    _CLOUDFLARED_PROJECTION_KIND: {
        "container_name": "/externalbrain-cloudflared",
        "compose_project": "ea",
        "compose_service": "ea-cloudflared",
    },
}
_IDENTITY_DOMAINS = (
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

_RESOURCE_DEFAULTS: dict[str, object] = {
    "CpuShares": 0,
    "Memory": 0,
    "NanoCpus": 0,
    "CgroupParent": "",
    "BlkioWeight": 0,
    "BlkioWeightDevice": [],
    "BlkioDeviceReadBps": [],
    "BlkioDeviceWriteBps": [],
    "BlkioDeviceReadIOps": [],
    "BlkioDeviceWriteIOps": [],
    "CpuPeriod": 0,
    "CpuQuota": 0,
    "CpuRealtimePeriod": 0,
    "CpuRealtimeRuntime": 0,
    "CpusetCpus": "",
    "CpusetMems": "",
    "Devices": [],
    "DeviceCgroupRules": None,
    "DeviceRequests": None,
    "MemoryReservation": 0,
    "MemorySwap": 0,
    "MemorySwappiness": None,
    "OomKillDisable": None,
    "OomScoreAdj": 0,
    "PidsLimit": None,
    "Ulimits": [],
    "CpuCount": 0,
    "CpuPercent": 0,
    "IOMaximumIOps": 0,
    "IOMaximumBandwidth": 0,
    "ShmSize": 0,
}
_RESOURCE_COLLECTION_FIELDS = frozenset(
    {
        "BlkioWeightDevice",
        "BlkioDeviceReadBps",
        "BlkioDeviceWriteBps",
        "BlkioDeviceReadIOps",
        "BlkioDeviceWriteIOps",
        "Devices",
        "DeviceCgroupRules",
        "DeviceRequests",
        "Ulimits",
    }
)


class RuntimeIdentityError(ValueError):
    """A Docker inspection payload cannot establish a safe identity."""


def _invalid(path: str) -> RuntimeIdentityError:
    return RuntimeIdentityError(f"runtime_identity_invalid:{path}")


def _mapping(value: object, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(
        not isinstance(key, str) or "\x00" in key for key in value
    ):
        raise _invalid(path)
    return value


def _list(value: object, path: str) -> list[object]:
    if not isinstance(value, list):
        raise _invalid(path)
    return value


def _none_or_list(value: object, path: str) -> list[object]:
    if value is None:
        return []
    return _list(value, path)


def _none_or_mapping(value: object, path: str) -> Mapping[str, Any]:
    if value is None:
        return {}
    return _mapping(value, path)


def _string(value: object, path: str, *, allow_empty: bool = True) -> str:
    if not isinstance(value, str) or "\x00" in value:
        raise _invalid(path)
    if not allow_empty and not value:
        raise _invalid(path)
    return value


def _boolean(value: object, path: str) -> bool:
    if type(value) is not bool:
        raise _invalid(path)
    return value


def _integer(value: object, path: str) -> int:
    if type(value) is not int:
        raise _invalid(path)
    return value


def _nullable_boolean(value: object, path: str) -> bool | None:
    if value is None:
        return None
    return _boolean(value, path)


def _nullable_integer(value: object, path: str) -> int | None:
    if value is None:
        return None
    return _integer(value, path)


def _nonnegative_integer(value: object, path: str) -> int:
    result = _integer(value, path)
    if result < 0:
        raise _invalid(path)
    return result


def _sha256(value: object, path: str) -> str:
    result = _string(value, path)
    if not _SHA256_PATTERN.fullmatch(result):
        raise _invalid(path)
    return result


def _docker_port(value: object, path: str) -> str:
    result = _string(value, path, allow_empty=False)
    matched = _DOCKER_PORT_PATTERN.fullmatch(result)
    if matched is None:
        raise _invalid(path)
    first = int(matched.group("first"))
    last = int(matched.group("last") or matched.group("first"))
    if first > 65_535 or last > 65_535 or first > last:
        raise _invalid(path)
    return result


def _console_size(value: object, path: str) -> list[int]:
    dimensions = _list(value, path)
    if len(dimensions) != 2:
        raise _invalid(path)
    return [
        _nonnegative_integer(dimensions[0], f"{path}[0]"),
        _nonnegative_integer(dimensions[1], f"{path}[1]"),
    ]


def _exact_mapping(
    value: object, path: str, keys: frozenset[str]
) -> Mapping[str, Any]:
    result = _mapping(value, path)
    if set(result) != keys:
        raise _invalid(path)
    return result


def _json_safe(value: object, path: str) -> object:
    if value is None or isinstance(value, (str, bool)):
        if isinstance(value, str) and "\x00" in value:
            raise _invalid(path)
        return value
    if type(value) is int:
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise _invalid(path)
        return value
    if isinstance(value, list):
        return [_json_safe(item, f"{path}[]") for item in value]
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) or "\x00" in key for key in value):
            raise _invalid(path)
        return {key: _json_safe(value[key], f"{path}.{key}") for key in sorted(value)}
    raise _invalid(path)


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _secret_free_mapping_identity(value: object, path: str) -> dict[str, object]:
    normalized = _json_safe(_mapping(value, path), path)
    assert isinstance(normalized, dict)
    return {
        "entry_count": len(normalized),
        "sha256": _canonical_sha256(normalized),
    }


def _secret_free_string_identity(value: object, path: str) -> dict[str, object]:
    normalized = _string(value, path)
    encoded = normalized.encode("utf-8")
    return {
        "value_bytes": len(encoded),
        "value_sha256": hashlib.sha256(encoded).hexdigest(),
    }


def _nullable_secret_free_string_mapping_identity(
    value: object, path: str
) -> dict[str, object]:
    if value is None:
        normalized: dict[str, str] = {}
        present = False
    else:
        source = _mapping(value, path)
        normalized = {
            key: _string(source[key], f"{path}.{key}") for key in sorted(source)
        }
        present = True
    return {
        "present": present,
        "entry_count": len(normalized),
        "sha256": _canonical_sha256(normalized),
    }


def _string_list(
    value: object,
    path: str,
    *,
    ordered: bool,
) -> list[str]:
    items = [_string(item, f"{path}[]") for item in _list(value, path)]
    return items if ordered else sorted(items)


def _command_identity(value: object, path: str) -> dict[str, object]:
    arguments = _string_list(_none_or_list(value, path), path, ordered=True)
    return {
        "argument_count": len(arguments),
        "arguments_sha256": _canonical_sha256(arguments),
    }


def _environment(value: object) -> dict[str, object]:
    entries: dict[str, str] = {}
    for raw in _list(value, "Config.Env"):
        entry = _string(raw, "Config.Env[]")
        if "=" not in entry:
            raise _invalid("Config.Env")
        name, content = entry.split("=", 1)
        if not name or name in entries:
            raise _invalid("Config.Env")
        entries[name] = content
    canonical = [f"{name}={entries[name]}" for name in sorted(entries)]
    return {
        "environment_count": len(canonical),
        "environment_sha256": _canonical_sha256(canonical),
    }


def _normalized_string_mapping(value: object, path: str) -> dict[str, str]:
    source = _mapping(value, path)
    return {
        key: _string(source[key], f"{path}.{key}") for key in sorted(source)
    }


def _nullable_normalized_string_list(
    value: object, path: str, *, ordered: bool
) -> list[str] | None:
    if value is None:
        return None
    return _string_list(value, path, ordered=ordered)


def _resource_collection_item(
    field: str, value: object, path: str
) -> object:
    if field == "DeviceCgroupRules":
        return _string(value, path, allow_empty=False)

    if field == "BlkioWeightDevice":
        item = _exact_mapping(value, path, frozenset({"Path", "Weight"}))
        return {
            "path": _string(item["Path"], f"{path}.Path", allow_empty=False),
            "weight": _integer(item["Weight"], f"{path}.Weight"),
        }

    if field in {
        "BlkioDeviceReadBps",
        "BlkioDeviceWriteBps",
        "BlkioDeviceReadIOps",
        "BlkioDeviceWriteIOps",
    }:
        item = _exact_mapping(value, path, frozenset({"Path", "Rate"}))
        return {
            "path": _string(item["Path"], f"{path}.Path", allow_empty=False),
            "rate": _nonnegative_integer(item["Rate"], f"{path}.Rate"),
        }

    if field == "Devices":
        item = _exact_mapping(
            value,
            path,
            frozenset({"PathOnHost", "PathInContainer", "CgroupPermissions"}),
        )
        return {
            "path_on_host": _string(
                item["PathOnHost"], f"{path}.PathOnHost", allow_empty=False
            ),
            "path_in_container": _string(
                item["PathInContainer"],
                f"{path}.PathInContainer",
                allow_empty=False,
            ),
            "cgroup_permissions": _string(
                item["CgroupPermissions"],
                f"{path}.CgroupPermissions",
                allow_empty=False,
            ),
        }

    if field == "DeviceRequests":
        item = _exact_mapping(
            value,
            path,
            frozenset(
                {"Driver", "Count", "DeviceIDs", "Capabilities", "Options"}
            ),
        )
        capabilities_value = item["Capabilities"]
        capabilities: list[list[str]] | None
        if capabilities_value is None:
            capabilities = None
        else:
            capabilities = [
                _string_list(row, f"{path}.Capabilities[]", ordered=False)
                for row in _list(capabilities_value, f"{path}.Capabilities")
            ]
            capabilities.sort()
        options_value = item["Options"]
        options = (
            None
            if options_value is None
            else _normalized_string_mapping(options_value, f"{path}.Options")
        )
        return {
            "driver": _string(item["Driver"], f"{path}.Driver"),
            "count": _integer(item["Count"], f"{path}.Count"),
            "device_ids": _nullable_normalized_string_list(
                item["DeviceIDs"], f"{path}.DeviceIDs", ordered=False
            ),
            "capabilities": capabilities,
            "options": options,
        }

    if field == "Ulimits":
        item = _exact_mapping(
            value, path, frozenset({"Name", "Hard", "Soft"})
        )
        return {
            "name": _string(item["Name"], f"{path}.Name", allow_empty=False),
            "hard": _integer(item["Hard"], f"{path}.Hard"),
            "soft": _integer(item["Soft"], f"{path}.Soft"),
        }

    raise _invalid(path)


def _resource_collection_identity(
    field: str, value: object, path: str
) -> dict[str, object]:
    if value is None:
        normalized: list[object] = []
        present = False
    else:
        normalized = [
            _resource_collection_item(field, item, f"{path}[]")
            for item in _list(value, path)
        ]
        normalized.sort(key=_canonical_sha256)
        present = True
    return {
        "present": present,
        "item_count": len(normalized),
        "items_sha256": _canonical_sha256(normalized),
    }


def _resources(host: Mapping[str, Any]) -> dict[str, object]:
    projected: dict[str, object] = {}
    for key, default in _RESOURCE_DEFAULTS.items():
        value = host.get(key, default)
        if key in _RESOURCE_COLLECTION_FIELDS:
            projected[key] = _resource_collection_identity(
                key, value, f"HostConfig.{key}"
            )
        else:
            projected[key] = _json_safe(value, f"HostConfig.{key}")
    return projected


def _healthcheck(value: object) -> dict[str, object]:
    if value is None:
        health: Mapping[str, Any] = {}
    else:
        health = _mapping(value, "Config.Healthcheck")
    return {
        "test": _command_identity(health.get("Test"), "Config.Healthcheck.Test"),
        "interval_ns": _integer(
            health.get("Interval", 0), "Config.Healthcheck.Interval"
        ),
        "timeout_ns": _integer(health.get("Timeout", 0), "Config.Healthcheck.Timeout"),
        "retries": _integer(health.get("Retries", 0), "Config.Healthcheck.Retries"),
        "start_period_ns": _integer(
            health.get("StartPeriod", 0), "Config.Healthcheck.StartPeriod"
        ),
        "start_interval_ns": _integer(
            health.get("StartInterval", 0),
            "Config.Healthcheck.StartInterval",
        ),
    }


def _ports(
    config: Mapping[str, Any], host: Mapping[str, Any], network: Mapping[str, Any]
) -> dict[str, object]:
    exposed = _mapping(config.get("ExposedPorts", {}), "Config.ExposedPorts")
    bindings = _mapping(host.get("PortBindings", {}), "HostConfig.PortBindings")
    actual = _mapping(network.get("Ports", {}), "NetworkSettings.Ports")

    def normalize(raw: Mapping[str, Any], path: str) -> dict[str, object]:
        result: dict[str, object] = {}
        for port in sorted(raw):
            _docker_port(port, f"{path}.key")
            rows = raw[port]
            if rows is None:
                result[port] = None
                continue
            normalized_rows = []
            for row in _list(rows, f"{path}.{port}"):
                item = _exact_mapping(
                    row,
                    f"{path}.{port}[]",
                    frozenset({"HostIp", "HostPort"}),
                )
                normalized_rows.append(
                    {
                        "host_ip": _string(
                            item.get("HostIp", ""), f"{path}.{port}.HostIp"
                        ),
                        "host_port": _string(
                            item.get("HostPort", ""),
                            f"{path}.{port}.HostPort",
                        ),
                    }
                )
            result[port] = sorted(
                normalized_rows,
                key=lambda row: (row["host_ip"], row["host_port"]),
            )
        return result

    exposed_ports: list[str] = []
    for port in sorted(exposed):
        exposed_ports.append(_docker_port(port, "Config.ExposedPorts.key"))
        _exact_mapping(
            exposed[port],
            f"Config.ExposedPorts.{port}",
            frozenset(),
        )

    return {
        "exposed": exposed_ports,
        "configured_bindings": normalize(bindings, "HostConfig.PortBindings"),
        "runtime_bindings": normalize(actual, "NetworkSettings.Ports"),
        "publish_all": _boolean(
            host.get("PublishAllPorts", False), "HostConfig.PublishAllPorts"
        ),
    }


def _mounts(value: object) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for raw in _list(value, "Mounts"):
        mount = _mapping(raw, "Mounts[]")
        mount_type = _string(mount.get("Type"), "Mounts.Type", allow_empty=False)
        source_key = "Name" if mount_type == "volume" else "Source"
        result.append(
            {
                "type": mount_type,
                "source": _string(mount.get(source_key, ""), f"Mounts.{source_key}"),
                "destination": _string(
                    mount.get("Destination"),
                    "Mounts.Destination",
                    allow_empty=False,
                ),
                "driver": _string(mount.get("Driver", ""), "Mounts.Driver"),
                "mode": _string(mount.get("Mode", ""), "Mounts.Mode"),
                "read_write": _boolean(mount.get("RW", False), "Mounts.RW"),
                "propagation": _string(
                    mount.get("Propagation", ""), "Mounts.Propagation"
                ),
            }
        )
    return sorted(
        result,
        key=lambda row: (
            row["destination"],
            row["type"],
            row["source"],
        ),
    )


def _networks(host: Mapping[str, Any], value: object) -> dict[str, object]:
    networks = _mapping(value, "NetworkSettings.Networks")
    projected: dict[str, object] = {}
    for name in sorted(networks):
        item = _mapping(networks[name], f"NetworkSettings.Networks.{name}")
        ipam = item.get("IPAMConfig")
        ipam_mapping = {} if ipam is None else _mapping(ipam, f"{name}.IPAMConfig")
        driver_opts = item.get("DriverOpts")
        driver_opts = {} if driver_opts is None else driver_opts
        projected[name] = {
            "ipam": {
                "ipv4_address": _string(
                    ipam_mapping.get("IPv4Address", ""),
                    f"{name}.IPAMConfig.IPv4Address",
                ),
                "ipv6_address": _string(
                    ipam_mapping.get("IPv6Address", ""),
                    f"{name}.IPAMConfig.IPv6Address",
                ),
                "link_local_ips": _string_list(
                    _none_or_list(
                        ipam_mapping.get("LinkLocalIPs"),
                        f"{name}.IPAMConfig.LinkLocalIPs",
                    ),
                    f"{name}.IPAMConfig.LinkLocalIPs",
                    ordered=False,
                ),
            },
            "aliases": _string_list(
                _none_or_list(item.get("Aliases"), f"{name}.Aliases"),
                f"{name}.Aliases",
                ordered=False,
            ),
            "links": _string_list(
                _none_or_list(item.get("Links"), f"{name}.Links"),
                f"{name}.Links",
                ordered=False,
            ),
            "driver_options": _secret_free_mapping_identity(
                driver_opts, f"{name}.DriverOpts"
            ),
            "mac_address": _string(item.get("MacAddress", ""), f"{name}.MacAddress"),
            "gateway": _string(item.get("Gateway", ""), f"{name}.Gateway"),
            "ip_address": _string(item.get("IPAddress", ""), f"{name}.IPAddress"),
            "ip_prefix_length": _integer(
                item.get("IPPrefixLen", 0), f"{name}.IPPrefixLen"
            ),
            "ipv6_gateway": _string(item.get("IPv6Gateway", ""), f"{name}.IPv6Gateway"),
            "global_ipv6_address": _string(
                item.get("GlobalIPv6Address", ""), f"{name}.GlobalIPv6Address"
            ),
            "global_ipv6_prefix_length": _integer(
                item.get("GlobalIPv6PrefixLen", 0), f"{name}.GlobalIPv6PrefixLen"
            ),
            "gateway_priority": _integer(
                item.get("GwPriority", 0), f"{name}.GwPriority"
            ),
        }
    return {
        "network_mode": _string(host.get("NetworkMode", ""), "HostConfig.NetworkMode"),
        "dns": _string_list(
            _none_or_list(host.get("Dns"), "HostConfig.Dns"),
            "HostConfig.Dns",
            ordered=False,
        ),
        "dns_options": _string_list(
            _none_or_list(host.get("DnsOptions"), "HostConfig.DnsOptions"),
            "HostConfig.DnsOptions",
            ordered=False,
        ),
        "dns_search": _string_list(
            _none_or_list(host.get("DnsSearch"), "HostConfig.DnsSearch"),
            "HostConfig.DnsSearch",
            ordered=False,
        ),
        "extra_hosts": _string_list(
            _none_or_list(host.get("ExtraHosts"), "HostConfig.ExtraHosts"),
            "HostConfig.ExtraHosts",
            ordered=False,
        ),
        "links": _string_list(
            _none_or_list(host.get("Links"), "HostConfig.Links"),
            "HostConfig.Links",
            ordered=False,
        ),
        "networks": projected,
    }


def _labels(
    value: object,
    *,
    expected_project: str,
    expected_service: str,
    permitted_value_differences: frozenset[str],
) -> tuple[dict[str, object], dict[str, object]]:
    labels = _mapping(value, "Config.Labels")
    normalized: dict[str, str] = {}
    for key in sorted(labels):
        normalized[key] = _string(labels[key], f"Config.Labels.{key}")
    config_hash = normalized.get(COMPOSE_CONFIG_HASH_LABEL, "")
    if not _CONFIG_HASH_PATTERN.fullmatch(config_hash):
        raise _invalid("Config.Labels.compose_config_hash")
    if normalized.get(COMPOSE_PROJECT_LABEL) != expected_project:
        raise _invalid("Config.Labels.compose_project")
    if normalized.get(COMPOSE_SERVICE_LABEL) != expected_service:
        raise _invalid("Config.Labels.compose_service")
    if (
        permitted_value_differences
        and not permitted_value_differences <= normalized.keys()
    ):
        raise _invalid("Config.Labels.topology")
    stable = {
        key: value
        for key, value in normalized.items()
        if key not in permitted_value_differences
    }
    topology = {
        key: {
            "value_bytes": len(normalized[key].encode("utf-8")),
            "value_sha256": hashlib.sha256(normalized[key].encode("utf-8")).hexdigest(),
        }
        for key in sorted(permitted_value_differences)
    }
    return (
        {
            "config_hash": config_hash,
            "label_count": len(stable),
            "labels_sha256": _canonical_sha256(stable),
        },
        topology,
    )


def _container_projection(
    inspection: Mapping[str, Any],
    *,
    projection_kind: str,
    permitted_label_differences: frozenset[str],
) -> dict[str, object]:
    source = _mapping(inspection, "inspection")
    role = _RUNTIME_ROLES.get(projection_kind)
    if role is None:
        raise _invalid("projection_kind")
    container_name = _string(source.get("Name"), "Name", allow_empty=False)
    if container_name != role["container_name"]:
        raise _invalid("Name")
    config = _mapping(source.get("Config"), "Config")
    host = _mapping(source.get("HostConfig"), "HostConfig")
    network = _mapping(source.get("NetworkSettings"), "NetworkSettings")
    image_id = _string(source.get("Image"), "Image")
    if not _IMAGE_ID_PATTERN.fullmatch(image_id):
        raise _invalid("Image")
    image_reference = _string(config.get("Image"), "Config.Image", allow_empty=False)
    labels, topology = _labels(
        config.get("Labels"),
        expected_project=role["compose_project"],
        expected_service=role["compose_service"],
        permitted_value_differences=permitted_label_differences,
    )
    restart = _mapping(host.get("RestartPolicy", {}), "HostConfig.RestartPolicy")
    log = _mapping(host.get("LogConfig", {}), "HostConfig.LogConfig")
    projection: dict[str, object] = {
        "schema": IDENTITY_SCHEMA,
        "projection_kind": projection_kind,
        "source_role": {
            "container_name": container_name,
            "compose_project": role["compose_project"],
            "compose_service": role["compose_service"],
        },
        "image": {"id": image_id, "reference": image_reference},
        "environment": _environment(config.get("Env", [])),
        "process": {
            "command": _command_identity(config.get("Cmd"), "Config.Cmd"),
            "entrypoint": _command_identity(
                config.get("Entrypoint"), "Config.Entrypoint"
            ),
            "working_dir": _string(config.get("WorkingDir", ""), "Config.WorkingDir"),
            "domainname": _secret_free_string_identity(
                config.get("Domainname", ""), "Config.Domainname"
            ),
            "network_disabled": _boolean(
                config.get("NetworkDisabled", False), "Config.NetworkDisabled"
            ),
            "args_escaped": _boolean(
                config.get("ArgsEscaped", False), "Config.ArgsEscaped"
            ),
            "shell": _command_identity(config.get("Shell"), "Config.Shell"),
            "init": _nullable_boolean(host.get("Init"), "HostConfig.Init"),
            "stop_signal": _secret_free_string_identity(
                config.get("StopSignal", ""), "Config.StopSignal"
            ),
            "stop_timeout_seconds": _nullable_integer(
                config.get("StopTimeout"), "Config.StopTimeout"
            ),
            "io": {
                "attach_stdin": _boolean(
                    config.get("AttachStdin", False), "Config.AttachStdin"
                ),
                "attach_stdout": _boolean(
                    config.get("AttachStdout", False), "Config.AttachStdout"
                ),
                "attach_stderr": _boolean(
                    config.get("AttachStderr", False), "Config.AttachStderr"
                ),
                "tty": _boolean(config.get("Tty", False), "Config.Tty"),
                "open_stdin": _boolean(
                    config.get("OpenStdin", False), "Config.OpenStdin"
                ),
                "stdin_once": _boolean(
                    config.get("StdinOnce", False), "Config.StdinOnce"
                ),
                "console_size": _console_size(
                    host.get("ConsoleSize", [0, 0]), "HostConfig.ConsoleSize"
                ),
            },
        },
        "healthcheck": _healthcheck(config.get("Healthcheck")),
        "restart_policy": {
            "name": _string(restart.get("Name", ""), "HostConfig.RestartPolicy.Name"),
            "maximum_retry_count": _integer(
                restart.get("MaximumRetryCount", 0),
                "HostConfig.RestartPolicy.MaximumRetryCount",
            ),
            "auto_remove": _boolean(
                host.get("AutoRemove", False), "HostConfig.AutoRemove"
            ),
        },
        "user_and_groups": {
            "user": _string(config.get("User", ""), "Config.User"),
            "groups": _string_list(
                _none_or_list(host.get("GroupAdd"), "HostConfig.GroupAdd"),
                "HostConfig.GroupAdd",
                ordered=False,
            ),
        },
        "capabilities_and_security_options": {
            "cap_add": _string_list(
                _none_or_list(host.get("CapAdd"), "HostConfig.CapAdd"),
                "HostConfig.CapAdd",
                ordered=False,
            ),
            "cap_drop": _string_list(
                _none_or_list(host.get("CapDrop"), "HostConfig.CapDrop"),
                "HostConfig.CapDrop",
                ordered=False,
            ),
            "security_options": _string_list(
                _none_or_list(host.get("SecurityOpt"), "HostConfig.SecurityOpt"),
                "HostConfig.SecurityOpt",
                ordered=False,
            ),
            "runtime": _string(host.get("Runtime", ""), "HostConfig.Runtime"),
            "isolation": _string(host.get("Isolation", ""), "HostConfig.Isolation"),
            "namespaces": {
                key: _string(host.get(key, ""), f"HostConfig.{key}")
                for key in (
                    "CgroupnsMode",
                    "IpcMode",
                    "PidMode",
                    "UTSMode",
                    "UsernsMode",
                )
            },
            "masked_paths": _string_list(
                _none_or_list(host.get("MaskedPaths"), "HostConfig.MaskedPaths"),
                "HostConfig.MaskedPaths",
                ordered=False,
            ),
            "readonly_paths": _string_list(
                _none_or_list(host.get("ReadonlyPaths"), "HostConfig.ReadonlyPaths"),
                "HostConfig.ReadonlyPaths",
                ordered=False,
            ),
            "sysctls": _nullable_secret_free_string_mapping_identity(
                host.get("Sysctls"), "HostConfig.Sysctls"
            ),
        },
        "privileged_and_read_only_posture": {
            "privileged": _boolean(
                host.get("Privileged", False), "HostConfig.Privileged"
            ),
            "read_only_rootfs": _boolean(
                host.get("ReadonlyRootfs", False), "HostConfig.ReadonlyRootfs"
            ),
            "tmpfs": _nullable_secret_free_string_mapping_identity(
                host.get("Tmpfs"), "HostConfig.Tmpfs"
            ),
            "storage_options": _nullable_secret_free_string_mapping_identity(
                host.get("StorageOpt"), "HostConfig.StorageOpt"
            ),
        },
        "resource_limits": _resources(host),
        "ports": _ports(config, host, network),
        "logging": {
            "driver": _string(log.get("Type", ""), "HostConfig.LogConfig.Type"),
            "options": _secret_free_mapping_identity(
                log.get("Config", {}), "HostConfig.LogConfig.Config"
            ),
        },
        "mounts": _mounts(source.get("Mounts")),
        "networks_and_aliases": _networks(host, network.get("Networks")),
        "labels": labels,
        "topology_label_evidence": topology,
    }
    _validate_runtime_projection(projection)
    return projection


def memorial_api_runtime_projection(
    inspection: Mapping[str, Any],
) -> dict[str, object]:
    """Project API identity while permitting only the three topology labels."""

    return _container_projection(
        inspection,
        projection_kind=_API_PROJECTION_KIND,
        permitted_label_differences=TOPOLOGY_LABELS,
    )


def cloudflared_runtime_projection(
    inspection: Mapping[str, Any],
) -> dict[str, object]:
    """Project cloudflared identity with no permitted label differences."""

    return _container_projection(
        inspection,
        projection_kind=_CLOUDFLARED_PROJECTION_KIND,
        permitted_label_differences=frozenset(),
    )


def _validate_digest_summary(
    value: object,
    path: str,
    *,
    count_key: str = "entry_count",
    digest_key: str = "sha256",
) -> None:
    summary = _exact_mapping(value, path, frozenset({count_key, digest_key}))
    _nonnegative_integer(summary[count_key], f"{path}.{count_key}")
    _sha256(summary[digest_key], f"{path}.{digest_key}")


def _validate_string_summary(value: object, path: str) -> None:
    summary = _exact_mapping(
        value, path, frozenset({"value_bytes", "value_sha256"})
    )
    _nonnegative_integer(summary["value_bytes"], f"{path}.value_bytes")
    _sha256(summary["value_sha256"], f"{path}.value_sha256")


def _validate_nullable_mapping_summary(value: object, path: str) -> None:
    summary = _exact_mapping(
        value,
        path,
        frozenset({"present", "entry_count", "sha256"}),
    )
    present = _boolean(summary["present"], f"{path}.present")
    count = _nonnegative_integer(summary["entry_count"], f"{path}.entry_count")
    digest = _sha256(summary["sha256"], f"{path}.sha256")
    if not present and (count != 0 or digest != _canonical_sha256({})):
        raise _invalid(path)


def _validate_collection_summary(value: object, path: str) -> None:
    summary = _exact_mapping(
        value,
        path,
        frozenset({"present", "item_count", "items_sha256"}),
    )
    present = _boolean(summary["present"], f"{path}.present")
    count = _nonnegative_integer(summary["item_count"], f"{path}.item_count")
    digest = _sha256(summary["items_sha256"], f"{path}.items_sha256")
    if not present and (count != 0 or digest != _canonical_sha256([])):
        raise _invalid(path)


def _validate_command_summary(value: object, path: str) -> None:
    summary = _exact_mapping(
        value,
        path,
        frozenset({"argument_count", "arguments_sha256"}),
    )
    count = _nonnegative_integer(
        summary["argument_count"], f"{path}.argument_count"
    )
    digest = _sha256(
        summary["arguments_sha256"], f"{path}.arguments_sha256"
    )
    if count == 0 and digest != _canonical_sha256([]):
        raise _invalid(path)


def _validate_string_list_projection(
    value: object, path: str, *, ordered: bool
) -> None:
    items = [_string(item, f"{path}[]") for item in _list(value, path)]
    if not ordered and items != sorted(items):
        raise _invalid(path)


def _validate_resources(value: object) -> None:
    resources = _exact_mapping(
        value, "projection.resource_limits", frozenset(_RESOURCE_DEFAULTS)
    )
    integer_fields = {
        key
        for key, default in _RESOURCE_DEFAULTS.items()
        if type(default) is int and key not in _RESOURCE_COLLECTION_FIELDS
    }
    string_fields = {
        key
        for key, default in _RESOURCE_DEFAULTS.items()
        if isinstance(default, str) and key not in _RESOURCE_COLLECTION_FIELDS
    }
    for key in integer_fields:
        _integer(resources[key], f"projection.resource_limits.{key}")
    for key in string_fields:
        _string(resources[key], f"projection.resource_limits.{key}")
    for key in _RESOURCE_COLLECTION_FIELDS:
        _validate_collection_summary(
            resources[key], f"projection.resource_limits.{key}"
        )
    _nullable_integer(
        resources["MemorySwappiness"],
        "projection.resource_limits.MemorySwappiness",
    )
    _nullable_boolean(
        resources["OomKillDisable"],
        "projection.resource_limits.OomKillDisable",
    )
    _nullable_integer(
        resources["PidsLimit"], "projection.resource_limits.PidsLimit"
    )


def _validate_port_bindings(value: object, path: str) -> None:
    bindings = _mapping(value, path)
    for port in bindings:
        _docker_port(port, f"{path}.key")
        rows = bindings[port]
        if rows is None:
            continue
        for index, raw in enumerate(_list(rows, f"{path}.{port}")):
            row_path = f"{path}.{port}[{index}]"
            row = _exact_mapping(
                raw, row_path, frozenset({"host_ip", "host_port"})
            )
            _string(row["host_ip"], f"{row_path}.host_ip")
            _string(row["host_port"], f"{row_path}.host_port")


def _validate_mounts(value: object) -> None:
    for index, raw in enumerate(_list(value, "projection.mounts")):
        path = f"projection.mounts[{index}]"
        mount = _exact_mapping(
            raw,
            path,
            frozenset(
                {
                    "type",
                    "source",
                    "destination",
                    "driver",
                    "mode",
                    "read_write",
                    "propagation",
                }
            ),
        )
        _string(mount["type"], f"{path}.type", allow_empty=False)
        _string(mount["source"], f"{path}.source")
        _string(mount["destination"], f"{path}.destination", allow_empty=False)
        _string(mount["driver"], f"{path}.driver")
        _string(mount["mode"], f"{path}.mode")
        _boolean(mount["read_write"], f"{path}.read_write")
        _string(mount["propagation"], f"{path}.propagation")


def _validate_networks(value: object) -> None:
    path = "projection.networks_and_aliases"
    projected = _exact_mapping(
        value,
        path,
        frozenset(
            {
                "network_mode",
                "dns",
                "dns_options",
                "dns_search",
                "extra_hosts",
                "links",
                "networks",
            }
        ),
    )
    _string(projected["network_mode"], f"{path}.network_mode")
    for key in ("dns", "dns_options", "dns_search", "extra_hosts", "links"):
        _validate_string_list_projection(
            projected[key], f"{path}.{key}", ordered=False
        )
    networks = _mapping(projected["networks"], f"{path}.networks")
    for name in networks:
        _string(name, f"{path}.networks.key", allow_empty=False)
        item_path = f"{path}.networks.{name}"
        item = _exact_mapping(
            networks[name],
            item_path,
            frozenset(
                {
                    "ipam",
                    "aliases",
                    "links",
                    "driver_options",
                    "mac_address",
                    "gateway",
                    "ip_address",
                    "ip_prefix_length",
                    "ipv6_gateway",
                    "global_ipv6_address",
                    "global_ipv6_prefix_length",
                    "gateway_priority",
                }
            ),
        )
        ipam = _exact_mapping(
            item["ipam"],
            f"{item_path}.ipam",
            frozenset({"ipv4_address", "ipv6_address", "link_local_ips"}),
        )
        _string(ipam["ipv4_address"], f"{item_path}.ipam.ipv4_address")
        _string(ipam["ipv6_address"], f"{item_path}.ipam.ipv6_address")
        _validate_string_list_projection(
            ipam["link_local_ips"],
            f"{item_path}.ipam.link_local_ips",
            ordered=False,
        )
        for key in ("aliases", "links"):
            _validate_string_list_projection(
                item[key], f"{item_path}.{key}", ordered=False
            )
        _validate_digest_summary(
            item["driver_options"], f"{item_path}.driver_options"
        )
        for key in (
            "mac_address",
            "gateway",
            "ip_address",
            "ipv6_gateway",
            "global_ipv6_address",
        ):
            _string(item[key], f"{item_path}.{key}")
        for key in (
            "ip_prefix_length",
            "global_ipv6_prefix_length",
            "gateway_priority",
        ):
            _integer(item[key], f"{item_path}.{key}")


def _validate_topology_label_evidence(
    value: object, projection_kind: str
) -> dict[str, dict[str, object]]:
    path = "projection.topology_label_evidence"
    evidence = _mapping(value, path)
    expected_keys = (
        TOPOLOGY_LABELS
        if projection_kind == _API_PROJECTION_KIND
        else frozenset()
    )
    if set(evidence) != expected_keys:
        raise _invalid(path)
    validated: dict[str, dict[str, object]] = {}
    for key in sorted(evidence):
        item_path = f"{path}.{key}"
        item = _exact_mapping(
            evidence[key],
            item_path,
            frozenset({"value_bytes", "value_sha256"}),
        )
        byte_count = _nonnegative_integer(
            item["value_bytes"], f"{item_path}.value_bytes"
        )
        digest = _sha256(item["value_sha256"], f"{item_path}.value_sha256")
        validated[key] = {
            "value_bytes": byte_count,
            "value_sha256": digest,
        }
    return validated


def _validate_runtime_projection(
    projection: Mapping[str, object],
) -> tuple[Mapping[str, Any], dict[str, dict[str, object]]]:
    source = _exact_mapping(
        projection,
        "projection",
        frozenset(
            {
                "schema",
                "projection_kind",
                "topology_label_evidence",
                *_IDENTITY_DOMAINS,
            }
        ),
    )
    if source["schema"] != IDENTITY_SCHEMA:
        raise _invalid("projection.schema")
    projection_kind = _string(
        source["projection_kind"], "projection.projection_kind"
    )
    if projection_kind not in {_API_PROJECTION_KIND, _CLOUDFLARED_PROJECTION_KIND}:
        raise _invalid("projection.projection_kind")
    role = _exact_mapping(
        source["source_role"],
        "projection.source_role",
        frozenset({"container_name", "compose_project", "compose_service"}),
    )
    expected_role = _RUNTIME_ROLES[projection_kind]
    for key, expected in expected_role.items():
        if _string(role[key], f"projection.source_role.{key}") != expected:
            raise _invalid(f"projection.source_role.{key}")

    image = _exact_mapping(
        source["image"], "projection.image", frozenset({"id", "reference"})
    )
    image_id = _string(image["id"], "projection.image.id")
    if not _IMAGE_ID_PATTERN.fullmatch(image_id):
        raise _invalid("projection.image.id")
    _string(image["reference"], "projection.image.reference", allow_empty=False)

    environment = _exact_mapping(
        source["environment"],
        "projection.environment",
        frozenset({"environment_count", "environment_sha256"}),
    )
    environment_count = _nonnegative_integer(
        environment["environment_count"],
        "projection.environment.environment_count",
    )
    environment_digest = _sha256(
        environment["environment_sha256"],
        "projection.environment.environment_sha256",
    )
    if environment_count == 0 and environment_digest != _canonical_sha256([]):
        raise _invalid("projection.environment")

    process = _exact_mapping(
        source["process"],
        "projection.process",
        frozenset(
            {
                "command",
                "entrypoint",
                "working_dir",
                "domainname",
                "network_disabled",
                "args_escaped",
                "shell",
                "init",
                "stop_signal",
                "stop_timeout_seconds",
                "io",
            }
        ),
    )
    _validate_command_summary(process["command"], "projection.process.command")
    _validate_command_summary(
        process["entrypoint"], "projection.process.entrypoint"
    )
    _string(process["working_dir"], "projection.process.working_dir")
    _validate_string_summary(process["domainname"], "projection.process.domainname")
    _boolean(process["network_disabled"], "projection.process.network_disabled")
    _boolean(process["args_escaped"], "projection.process.args_escaped")
    _validate_command_summary(process["shell"], "projection.process.shell")
    _nullable_boolean(process["init"], "projection.process.init")
    _validate_string_summary(
        process["stop_signal"], "projection.process.stop_signal"
    )
    stop_timeout = _nullable_integer(
        process["stop_timeout_seconds"],
        "projection.process.stop_timeout_seconds",
    )
    if stop_timeout is not None and stop_timeout < 0:
        raise _invalid("projection.process.stop_timeout_seconds")
    io_path = "projection.process.io"
    io = _exact_mapping(
        process["io"],
        io_path,
        frozenset(
            {
                "attach_stdin",
                "attach_stdout",
                "attach_stderr",
                "tty",
                "open_stdin",
                "stdin_once",
                "console_size",
            }
        ),
    )
    for key in (
        "attach_stdin",
        "attach_stdout",
        "attach_stderr",
        "tty",
        "open_stdin",
        "stdin_once",
    ):
        _boolean(io[key], f"{io_path}.{key}")
    _console_size(io["console_size"], f"{io_path}.console_size")

    healthcheck = _exact_mapping(
        source["healthcheck"],
        "projection.healthcheck",
        frozenset(
            {
                "test",
                "interval_ns",
                "timeout_ns",
                "retries",
                "start_period_ns",
                "start_interval_ns",
            }
        ),
    )
    _validate_command_summary(
        healthcheck["test"], "projection.healthcheck.test"
    )
    for key in (
        "interval_ns",
        "timeout_ns",
        "retries",
        "start_period_ns",
        "start_interval_ns",
    ):
        _nonnegative_integer(healthcheck[key], f"projection.healthcheck.{key}")

    restart = _exact_mapping(
        source["restart_policy"],
        "projection.restart_policy",
        frozenset({"name", "maximum_retry_count", "auto_remove"}),
    )
    _string(restart["name"], "projection.restart_policy.name")
    _nonnegative_integer(
        restart["maximum_retry_count"],
        "projection.restart_policy.maximum_retry_count",
    )
    _boolean(restart["auto_remove"], "projection.restart_policy.auto_remove")

    users = _exact_mapping(
        source["user_and_groups"],
        "projection.user_and_groups",
        frozenset({"user", "groups"}),
    )
    _string(users["user"], "projection.user_and_groups.user")
    _validate_string_list_projection(
        users["groups"], "projection.user_and_groups.groups", ordered=False
    )

    security_path = "projection.capabilities_and_security_options"
    security = _exact_mapping(
        source["capabilities_and_security_options"],
        security_path,
        frozenset(
            {
                "cap_add",
                "cap_drop",
                "security_options",
                "runtime",
                "isolation",
                "namespaces",
                "masked_paths",
                "readonly_paths",
                "sysctls",
            }
        ),
    )
    for key in (
        "cap_add",
        "cap_drop",
        "security_options",
        "masked_paths",
        "readonly_paths",
    ):
        _validate_string_list_projection(
            security[key], f"{security_path}.{key}", ordered=False
        )
    for key in ("runtime", "isolation"):
        _string(security[key], f"{security_path}.{key}")
    namespaces = _exact_mapping(
        security["namespaces"],
        f"{security_path}.namespaces",
        frozenset(
            {"CgroupnsMode", "IpcMode", "PidMode", "UTSMode", "UsernsMode"}
        ),
    )
    for key in namespaces:
        _string(namespaces[key], f"{security_path}.namespaces.{key}")
    _validate_nullable_mapping_summary(
        security["sysctls"], f"{security_path}.sysctls"
    )

    posture_path = "projection.privileged_and_read_only_posture"
    posture = _exact_mapping(
        source["privileged_and_read_only_posture"],
        posture_path,
        frozenset(
            {"privileged", "read_only_rootfs", "tmpfs", "storage_options"}
        ),
    )
    _boolean(posture["privileged"], f"{posture_path}.privileged")
    _boolean(posture["read_only_rootfs"], f"{posture_path}.read_only_rootfs")
    _validate_nullable_mapping_summary(posture["tmpfs"], f"{posture_path}.tmpfs")
    _validate_nullable_mapping_summary(
        posture["storage_options"], f"{posture_path}.storage_options"
    )

    _validate_resources(source["resource_limits"])

    ports = _exact_mapping(
        source["ports"],
        "projection.ports",
        frozenset(
            {
                "exposed",
                "configured_bindings",
                "runtime_bindings",
                "publish_all",
            }
        ),
    )
    exposed = _list(ports["exposed"], "projection.ports.exposed")
    normalized_exposed = [
        _docker_port(port, "projection.ports.exposed[]") for port in exposed
    ]
    if normalized_exposed != sorted(normalized_exposed):
        raise _invalid("projection.ports.exposed")
    _validate_port_bindings(
        ports["configured_bindings"], "projection.ports.configured_bindings"
    )
    _validate_port_bindings(
        ports["runtime_bindings"], "projection.ports.runtime_bindings"
    )
    _boolean(ports["publish_all"], "projection.ports.publish_all")

    logging = _exact_mapping(
        source["logging"],
        "projection.logging",
        frozenset({"driver", "options"}),
    )
    _string(logging["driver"], "projection.logging.driver")
    _validate_digest_summary(logging["options"], "projection.logging.options")

    _validate_mounts(source["mounts"])
    _validate_networks(source["networks_and_aliases"])

    labels = _exact_mapping(
        source["labels"],
        "projection.labels",
        frozenset({"config_hash", "label_count", "labels_sha256"}),
    )
    config_hash = _string(labels["config_hash"], "projection.labels.config_hash")
    if not _CONFIG_HASH_PATTERN.fullmatch(config_hash):
        raise _invalid("projection.labels.config_hash")
    _nonnegative_integer(labels["label_count"], "projection.labels.label_count")
    _sha256(labels["labels_sha256"], "projection.labels.labels_sha256")

    topology_values = _validate_topology_label_evidence(
        source["topology_label_evidence"], projection_kind
    )
    return source, topology_values


def runtime_identity_digests(
    projection: Mapping[str, object],
) -> dict[str, str]:
    source, _ = _validate_runtime_projection(projection)
    return {
        domain: _canonical_sha256(
            _json_safe(source[domain], f"projection.{domain}")
        )
        for domain in _IDENTITY_DOMAINS
    }


def runtime_mismatch_domains(
    expected: Mapping[str, object], observed: Mapping[str, object]
) -> list[str]:
    expected_source, _ = _validate_runtime_projection(expected)
    observed_source, _ = _validate_runtime_projection(observed)
    if expected_source["projection_kind"] != observed_source["projection_kind"]:
        raise _invalid("projection.projection_kind")
    expected_digests = runtime_identity_digests(expected)
    observed_digests = runtime_identity_digests(observed)
    return [
        domain
        for domain in _IDENTITY_DOMAINS
        if expected_digests[domain] != observed_digests[domain]
    ]


def runtime_comparison_report(
    expected: Mapping[str, object], observed: Mapping[str, object]
) -> dict[str, object]:
    expected_source, expected_topology = _validate_runtime_projection(expected)
    observed_source, observed_topology = _validate_runtime_projection(observed)
    if expected_source["projection_kind"] != observed_source["projection_kind"]:
        raise _invalid("projection.projection_kind")
    expected_digests = runtime_identity_digests(expected)
    observed_digests = runtime_identity_digests(observed)
    mismatches = [
        domain
        for domain in _IDENTITY_DOMAINS
        if expected_digests[domain] != observed_digests[domain]
    ]
    return {
        "projection_kind": expected_source["projection_kind"],
        "match": not mismatches,
        "mismatch_domains": mismatches,
        "expected_domain_sha256": expected_digests,
        "observed_domain_sha256": observed_digests,
        "expected_topology_label_evidence": expected_topology,
        "observed_topology_label_evidence": observed_topology,
    }


def _public_ipam_config(value: object) -> list[dict[str, object]]:
    projected: list[dict[str, object]] = []
    for index, raw in enumerate(_none_or_list(value, "IPAM.Config")):
        path = f"IPAM.Config[{index}]"
        item = _mapping(raw, path)
        allowed = frozenset(
            {"Subnet", "IPRange", "Gateway", "AuxiliaryAddresses"}
        )
        if not set(item) <= allowed:
            raise _invalid(path)
        projected.append(
            {
                "subnet": _string(item.get("Subnet", ""), f"{path}.Subnet"),
                "ip_range": _string(item.get("IPRange", ""), f"{path}.IPRange"),
                "gateway": _string(item.get("Gateway", ""), f"{path}.Gateway"),
                "auxiliary_addresses": (
                    _nullable_secret_free_string_mapping_identity(
                        item.get("AuxiliaryAddresses"),
                        f"{path}.AuxiliaryAddresses",
                    )
                ),
            }
        )
    projected.sort(key=_canonical_sha256)
    return projected


def validate_public_network_semantic_projection(
    projection: Mapping[str, object],
) -> dict[str, object]:
    """Validate and canonicalize a complete public-network projection."""

    path = "public_network_projection"
    source = _exact_mapping(
        projection,
        path,
        frozenset(
            {
                "schema",
                "name",
                "driver",
                "scope",
                "enable_ipv4",
                "enable_ipv6",
                "internal",
                "attachable",
                "ingress",
                "config_only",
                "config_from",
                "ipam",
                "options",
                "labels",
                "members",
            }
        ),
    )
    if source["schema"] != PUBLIC_NETWORK_SCHEMA:
        raise _invalid(f"{path}.schema")
    if _string(source["name"], f"{path}.name") != PUBLIC_NETWORK_NAME:
        raise _invalid(f"{path}.name")
    _string(source["driver"], f"{path}.driver", allow_empty=False)
    _string(source["scope"], f"{path}.scope", allow_empty=False)
    for key in (
        "enable_ipv4",
        "enable_ipv6",
        "internal",
        "attachable",
        "ingress",
        "config_only",
    ):
        _boolean(source[key], f"{path}.{key}")

    config_from = _exact_mapping(
        source["config_from"], f"{path}.config_from", frozenset({"network"})
    )
    _string(config_from["network"], f"{path}.config_from.network")

    ipam_path = f"{path}.ipam"
    ipam = _exact_mapping(
        source["ipam"],
        ipam_path,
        frozenset({"driver", "options", "config"}),
    )
    _string(ipam["driver"], f"{ipam_path}.driver", allow_empty=False)
    _validate_digest_summary(ipam["options"], f"{ipam_path}.options")
    ipam_config = _list(ipam["config"], f"{ipam_path}.config")
    canonical_config: list[dict[str, object]] = []
    for index, raw in enumerate(ipam_config):
        item_path = f"{ipam_path}.config[{index}]"
        item = _exact_mapping(
            raw,
            item_path,
            frozenset(
                {"subnet", "ip_range", "gateway", "auxiliary_addresses"}
            ),
        )
        for key in ("subnet", "ip_range", "gateway"):
            _string(item[key], f"{item_path}.{key}")
        _validate_nullable_mapping_summary(
            item["auxiliary_addresses"], f"{item_path}.auxiliary_addresses"
        )
        normalized_item = _json_safe(item, item_path)
        assert isinstance(normalized_item, dict)
        canonical_config.append(normalized_item)
    if canonical_config != sorted(canonical_config, key=_canonical_sha256):
        raise _invalid(f"{ipam_path}.config")

    _validate_digest_summary(source["options"], f"{path}.options")
    _validate_digest_summary(source["labels"], f"{path}.labels")

    members = _list(source["members"], f"{path}.members")
    member_names: list[str] = []
    for index, raw in enumerate(members):
        item_path = f"{path}.members[{index}]"
        member = _exact_mapping(
            raw,
            item_path,
            frozenset({"name", "ipv4_address", "ipv6_address", "mac_address"}),
        )
        member_names.append(
            _string(member["name"], f"{item_path}.name", allow_empty=False)
        )
        for key in ("ipv4_address", "ipv6_address", "mac_address"):
            _string(member[key], f"{item_path}.{key}")
    if member_names != sorted(member_names) or len(member_names) != len(
        set(member_names)
    ):
        raise _invalid(f"{path}.members")

    normalized = _json_safe(source, path)
    assert isinstance(normalized, dict)
    return normalized


def public_network_semantic_projection(
    inspection: Mapping[str, Any],
) -> dict[str, object]:
    """Project the exact EA public network without opaque Docker IDs."""

    source = _mapping(inspection, "network_inspection")
    name = _string(source.get("Name"), "Name", allow_empty=False)
    if name != PUBLIC_NETWORK_NAME:
        raise _invalid("Name")
    ipam = _mapping(source.get("IPAM"), "IPAM")
    members = _mapping(source.get("Containers"), "Containers")
    projected_members: list[dict[str, str]] = []
    seen_names: set[str] = set()
    for member_id in sorted(members):
        member = _mapping(members[member_id], "Containers[]")
        member_name = _string(
            member.get("Name"), "Containers.Name", allow_empty=False
        )
        if member_name in seen_names:
            raise _invalid("Containers.Name")
        seen_names.add(member_name)
        projected_members.append(
            {
                "name": member_name,
                "ipv4_address": _string(
                    member.get("IPv4Address", ""), "Containers.IPv4Address"
                ),
                "ipv6_address": _string(
                    member.get("IPv6Address", ""), "Containers.IPv6Address"
                ),
                "mac_address": _string(
                    member.get("MacAddress", ""), "Containers.MacAddress"
                ),
            }
        )
    projected_members.sort(key=lambda row: row["name"])
    config_from = _exact_mapping(
        source.get("ConfigFrom"), "ConfigFrom", frozenset({"Network"})
    )
    projection: dict[str, object] = {
        "schema": PUBLIC_NETWORK_SCHEMA,
        "name": name,
        "driver": _string(source.get("Driver"), "Driver", allow_empty=False),
        "scope": _string(source.get("Scope"), "Scope", allow_empty=False),
        "enable_ipv4": _boolean(source.get("EnableIPv4", True), "EnableIPv4"),
        "enable_ipv6": _boolean(source.get("EnableIPv6", False), "EnableIPv6"),
        "internal": _boolean(source.get("Internal", False), "Internal"),
        "attachable": _boolean(source.get("Attachable", False), "Attachable"),
        "ingress": _boolean(source.get("Ingress", False), "Ingress"),
        "config_only": _boolean(source.get("ConfigOnly", False), "ConfigOnly"),
        "config_from": {
            "network": _string(config_from["Network"], "ConfigFrom.Network")
        },
        "ipam": {
            "driver": _string(
                ipam.get("Driver"), "IPAM.Driver", allow_empty=False
            ),
            "options": _secret_free_mapping_identity(
                _normalized_string_mapping(
                    _none_or_mapping(ipam.get("Options"), "IPAM.Options"),
                    "IPAM.Options",
                ),
                "IPAM.Options",
            ),
            "config": _public_ipam_config(ipam.get("Config")),
        },
        "options": _secret_free_mapping_identity(
            _normalized_string_mapping(
                _none_or_mapping(source.get("Options"), "Options"), "Options"
            ),
            "Options",
        ),
        "labels": _secret_free_mapping_identity(
            _normalized_string_mapping(
                _none_or_mapping(source.get("Labels"), "Labels"), "Labels"
            ),
            "Labels",
        ),
        "members": projected_members,
    }
    return validate_public_network_semantic_projection(projection)
