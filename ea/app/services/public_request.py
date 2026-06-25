from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse


def _env_truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def trust_forwarded_host() -> bool:
    explicit = os.getenv("PROPERTYQUARRY_TRUST_X_FORWARDED_HOST")
    if explicit is not None:
        return _env_truthy(explicit)
    return _env_truthy(os.getenv("PROPERTYQUARRY_TRUST_X_FORWARDED_FOR"))


def trust_forwarded_ip() -> bool:
    return _env_truthy(os.getenv("PROPERTYQUARRY_TRUST_X_FORWARDED_FOR"))


def normalize_hostname(hostname: str | None) -> str:
    return str(hostname or "").strip().lower().rstrip(".")


def _header_first_token(value: str | None) -> str:
    return str(value or "").split(",", 1)[0].strip()


def request_host(request: Any) -> str:
    if request is None:
        return ""
    headers = getattr(request, "headers", {})
    header_host = _header_first_token(headers.get("host")).split(":", 1)[0].strip()
    if header_host:
        return normalize_hostname(header_host)
    url = getattr(request, "url", None)
    return normalize_hostname(getattr(url, "hostname", ""))


def forwarded_host(request: Any) -> str:
    if request is None or not trust_forwarded_host():
        return ""
    headers = getattr(request, "headers", {})
    raw = _header_first_token(headers.get("x-forwarded-host")).split(":", 1)[0].strip()
    return normalize_hostname(raw)


def forwarded_proto(request: Any) -> str:
    if request is None or not trust_forwarded_host():
        return ""
    headers = getattr(request, "headers", {})
    return _header_first_token(headers.get("x-forwarded-proto")).strip().lower()


def request_hostname(request: Any) -> str:
    return forwarded_host(request) or request_host(request)


def public_base_url(
    request: Any,
    *,
    explicit_base_url: str = "",
    redirect_uri: str = "",
    property_base_url: str = "",
    property_hosts: tuple[str, ...] = ("propertyquarry.com", "www.propertyquarry.com"),
) -> str:
    effective_host = request_hostname(request)
    if effective_host in property_hosts:
        if property_base_url:
            return str(property_base_url).strip().rstrip("/")
        proto = forwarded_proto(request) or "https"
        return f"{proto}://{effective_host}"
    explicit = str(explicit_base_url or "").strip().rstrip("/")
    if explicit:
        return explicit
    parsed = urlparse(str(redirect_uri or "").strip())
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    trusted_forwarded_host = forwarded_host(request)
    if trusted_forwarded_host:
        proto = forwarded_proto(request) or getattr(getattr(request, "url", None), "scheme", "https")
        return f"{proto}://{trusted_forwarded_host}"
    base_url = str(getattr(request, "base_url", "") or "").rstrip("/")
    if base_url:
        return base_url
    scheme = getattr(getattr(request, "url", None), "scheme", "https")
    host = request_host(request)
    return f"{scheme}://{host}" if host else ""
