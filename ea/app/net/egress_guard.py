from __future__ import annotations

import ipaddress
import socket
import urllib.parse
from dataclasses import dataclass

_LOCAL_HOSTS = {"localhost", "localhost.localdomain"}
_METADATA_HOSTS = {
    "169.254.169.254",
    "169.254.170.2",
    "metadata.google.internal",
    "metadata",
}


@dataclass(frozen=True)
class EgressDecision:
    allowed: bool
    reason: str
    resolved_ips: tuple[str, ...]


def _is_ip_private_or_local(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
    )


def _resolve_host(host: str) -> tuple[str, ...]:
    out: list[str] = []
    seen: set[str] = set()
    for family, _socktype, _proto, _canonname, sockaddr in socket.getaddrinfo(host, None):
        ip = sockaddr[0]
        if family in (socket.AF_INET, socket.AF_INET6) and ip not in seen:
            seen.add(ip)
            out.append(ip)
    return tuple(out)


def evaluate_connector_url(
    url: str,
    *,
    network_mode: str = "hosted",
    allow_private_targets: bool = False,
    allow_metadata_targets: bool = False,
) -> EgressDecision:
    parsed = urllib.parse.urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        return EgressDecision(False, "scheme_not_allowed", ())
    if parsed.username or parsed.password:
        return EgressDecision(False, "userinfo_not_allowed", ())
    if not parsed.hostname:
        return EgressDecision(False, "missing_hostname", ())

    host = parsed.hostname.strip().lower()
    if host in _LOCAL_HOSTS:
        return EgressDecision(False, "localhost_blocked", ())
    if host in _METADATA_HOSTS and not allow_metadata_targets:
        return EgressDecision(False, "metadata_host_blocked", ())

    try:
        ips = _resolve_host(host)
    except Exception:
        return EgressDecision(False, "dns_resolution_failed", ())
    if not ips:
        return EgressDecision(False, "dns_empty_result", ())

    if network_mode == "hosted":
        for ip in ips:
            if ip in _METADATA_HOSTS and not allow_metadata_targets:
                return EgressDecision(False, "metadata_ip_blocked", ips)
            if _is_ip_private_or_local(ip) and not allow_private_targets:
                return EgressDecision(False, "private_or_local_ip_blocked", ips)
        return EgressDecision(True, "hosted_safe", ips)

    if network_mode in ("connector_agent", "self_host"):
        if not allow_metadata_targets:
            for ip in ips:
                if ip in _METADATA_HOSTS:
                    return EgressDecision(False, "metadata_ip_blocked", ips)
        return EgressDecision(True, "trusted_mode_allowed", ips)

    return EgressDecision(False, "unknown_network_mode", ips)


def assert_safe_connector_url(
    url: str,
    *,
    network_mode: str = "hosted",
    allow_private_targets: bool = False,
    allow_metadata_targets: bool = False,
) -> tuple[str, ...]:
    decision = evaluate_connector_url(
        url,
        network_mode=network_mode,
        allow_private_targets=allow_private_targets,
        allow_metadata_targets=allow_metadata_targets,
    )
    if not decision.allowed:
        raise ValueError(f"EgressGuardDenied:{decision.reason}")
    return decision.resolved_ips
