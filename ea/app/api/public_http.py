from __future__ import annotations

import ipaddress
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import SplitResult, urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from app.settings import is_prod_mode


_AUTHORITY_PROXY_HEADER_NAMES = {b"forwarded", b"x-forwarded-host", b"x-forwarded-proto"}
_CLIENT_PROXY_HEADER_NAMES = {b"cf-connecting-ip", b"cf-ray", b"x-forwarded-for"}
_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient", "testserver"}
_DEFAULT_TRUSTED_PROXY_CIDRS = "127.0.0.0/8,::1/128"
_SECURITY_HEADERS = {
    "Content-Security-Policy": "frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), interest-cohort=()",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}


@dataclass(frozen=True)
class _Authority:
    host: str
    port: int | None = None

    @property
    def netloc(self) -> str:
        bracketed = f"[{self.host}]" if ":" in self.host else self.host
        return f"{bracketed}:{self.port}" if self.port is not None else bracketed


@dataclass(frozen=True)
class _PublicOrigin:
    scheme: str
    authority: _Authority


@dataclass(frozen=True)
class _ProxyMetadata:
    host: _Authority | None
    proto: str


class _ProxyMetadataError(ValueError):
    pass


def _env_truthy(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _header_values(scope: dict[str, Any], name: bytes) -> tuple[str, ...]:
    values: list[str] = []
    for raw_name, raw_value in scope.get("headers") or []:
        if bytes(raw_name).lower() != name:
            continue
        try:
            values.append(bytes(raw_value).decode("latin-1").strip())
        except Exception as exc:  # pragma: no cover - ASGI headers are latin-1 bytes
            raise _ProxyMetadataError("header_encoding_invalid") from exc
    return tuple(values)


def _single_header_value(scope: dict[str, Any], name: bytes) -> str:
    values = _header_values(scope, name)
    if not values:
        return ""
    if len(values) != 1 or not values[0] or "," in values[0]:
        raise _ProxyMetadataError("proxy_header_multiple_values")
    return values[0]


def _authority(value: object) -> _Authority | None:
    raw = str(value or "").strip()
    if not raw or any(char in raw for char in ("/", "\\", "@", "#", "?", ",")):
        return None
    try:
        raw.encode("ascii")
    except UnicodeEncodeError:
        return None
    if any(char.isspace() for char in raw):
        return None
    try:
        parsed = urlsplit(f"//{raw}")
        host = str(parsed.hostname or "").strip().lower().rstrip(".")
        port = parsed.port
    except ValueError:
        return None
    if not host or parsed.username is not None or parsed.password is not None:
        return None
    return _Authority(host=host, port=port)


def _public_origin() -> _PublicOrigin | None:
    raw = str(os.getenv("EA_PUBLIC_APP_BASE_URL") or "").strip().rstrip("/")
    if not raw:
        return None
    try:
        parsed = urlsplit(raw)
        authority = _authority(parsed.netloc)
    except ValueError:
        return None
    scheme = str(parsed.scheme or "").lower()
    if scheme not in {"http", "https"} or authority is None or parsed.path not in {"", "/"}:
        return None
    return _PublicOrigin(scheme=scheme, authority=authority)


def _configured_hosts() -> set[str]:
    hosts: set[str] = set(_LOCAL_HOSTS)
    origin = _public_origin()
    if origin is not None:
        hosts.add(origin.authority.host)
    property_base = str(os.getenv("PROPERTYQUARRY_PUBLIC_BASE_URL") or "").strip()
    if property_base:
        try:
            parsed = urlsplit(property_base)
            if parsed.hostname:
                hosts.add(str(parsed.hostname).lower().rstrip("."))
        except ValueError:
            pass
    for key in ("EA_ALLOWED_PUBLIC_HOSTS", "PROPERTYQUARRY_PUBLIC_HOSTS"):
        for value in str(os.getenv(key) or "").split(","):
            parsed = _authority(value)
            if parsed is not None:
                hosts.add(parsed.host)
    return hosts


def _proxy_headers_enabled() -> bool:
    return any(
        _env_truthy(os.getenv(key))
        for key in (
            "EA_TRUST_PROXY_HEADERS",
            "PROPERTYQUARRY_TRUST_X_FORWARDED_HOST",
            "PROPERTYQUARRY_TRUST_X_FORWARDED_FOR",
        )
    )


def _trusted_proxy_networks() -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    raw = str(
        os.getenv("EA_TRUSTED_PROXY_CIDRS")
        or os.getenv("PROPERTYQUARRY_TRUSTED_PROXY_CIDRS")
        or _DEFAULT_TRUSTED_PROXY_CIDRS
    )
    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for value in raw.split(","):
        candidate = value.strip()
        if not candidate:
            continue
        try:
            networks.append(ipaddress.ip_network(candidate, strict=False))
        except ValueError:
            continue
    return tuple(networks)


def _request_from_trusted_proxy(request: Request) -> bool:
    if not _proxy_headers_enabled():
        return False
    client = getattr(request, "client", None)
    raw_host = str(getattr(client, "host", "") or "").strip()
    try:
        address = ipaddress.ip_address(raw_host)
    except ValueError:
        return False
    return any(address in network for network in _trusted_proxy_networks())


def _parse_forwarded(value: str) -> tuple[_Authority | None, str]:
    if not value:
        return None, ""
    if "," in value:
        raise _ProxyMetadataError("forwarded_multiple_hops")
    fields: dict[str, str] = {}
    for part in value.split(";"):
        if not part.strip():
            continue
        key, separator, raw_value = part.partition("=")
        normalized_key = key.strip().lower()
        if not separator or not normalized_key or normalized_key in fields:
            raise _ProxyMetadataError("forwarded_field_invalid")
        normalized_value = raw_value.strip()
        if normalized_value.startswith('"') or normalized_value.endswith('"'):
            if len(normalized_value) < 2 or not (
                normalized_value.startswith('"') and normalized_value.endswith('"')
            ):
                raise _ProxyMetadataError("forwarded_quote_invalid")
            normalized_value = normalized_value[1:-1]
        fields[normalized_key] = normalized_value
    host = None
    if "host" in fields:
        host = _authority(fields["host"])
        if host is None:
            raise _ProxyMetadataError("forwarded_host_invalid")
    proto = fields.get("proto", "").lower()
    if proto and proto not in {"http", "https"}:
        raise _ProxyMetadataError("forwarded_proto_invalid")
    return host, proto


def _proxy_metadata(scope: dict[str, Any]) -> _ProxyMetadata:
    forwarded = _single_header_value(scope, b"forwarded")
    forwarded_host, forwarded_proto = _parse_forwarded(forwarded)

    x_host_value = _single_header_value(scope, b"x-forwarded-host")
    x_host = _authority(x_host_value) if x_host_value else None
    if x_host_value and x_host is None:
        raise _ProxyMetadataError("x_forwarded_host_invalid")
    x_proto = _single_header_value(scope, b"x-forwarded-proto").lower()
    if x_proto and x_proto not in {"http", "https"}:
        raise _ProxyMetadataError("x_forwarded_proto_invalid")

    if forwarded_host is not None and x_host is not None and forwarded_host != x_host:
        raise _ProxyMetadataError("forwarded_host_mismatch")
    if forwarded_proto and x_proto and forwarded_proto != x_proto:
        raise _ProxyMetadataError("forwarded_proto_mismatch")
    return _ProxyMetadata(host=forwarded_host or x_host, proto=forwarded_proto or x_proto)


def _replace_scope_headers(
    scope: dict[str, Any],
    *,
    host: _Authority | None,
    proto: str,
    keep_proxy_headers: bool,
    strip_client_proxy_headers: bool = False,
) -> None:
    headers: list[tuple[bytes, bytes]] = []
    for raw_name, raw_value in scope.get("headers") or []:
        normalized_name = bytes(raw_name).lower()
        if normalized_name == b"host" or normalized_name in _AUTHORITY_PROXY_HEADER_NAMES:
            continue
        if strip_client_proxy_headers and normalized_name in _CLIENT_PROXY_HEADER_NAMES:
            continue
        headers.append((bytes(raw_name), bytes(raw_value)))
    if host is not None:
        headers.append((b"host", host.netloc.encode("ascii")))
    if keep_proxy_headers and host is not None:
        headers.append((b"x-forwarded-host", host.netloc.encode("ascii")))
    if keep_proxy_headers and proto:
        headers.append((b"x-forwarded-proto", proto.encode("ascii")))
    scope["headers"] = headers


def _rewrite_request_authority(request: Request, *, host: _Authority, proto: str) -> None:
    _replace_scope_headers(request.scope, host=host, proto=proto, keep_proxy_headers=True)
    request.scope["scheme"] = proto
    request.scope["server"] = (host.host, host.port or (443 if proto == "https" else 80))
    request.__dict__.pop("_headers", None)
    request.__dict__.pop("_url", None)


def _strip_untrusted_proxy_headers(request: Request, *, raw_host: _Authority | None) -> None:
    _replace_scope_headers(
        request.scope,
        host=raw_host,
        proto="",
        keep_proxy_headers=False,
        strip_client_proxy_headers=True,
    )
    request.__dict__.pop("_headers", None)
    request.__dict__.pop("_url", None)


def _security_headers(response: Response, *, scheme: str) -> Response:
    for name, value in _SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    if scheme == "https":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    return response


def _error_response(*, status_code: int, code: str, scheme: str) -> Response:
    response = JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": "request authority rejected"}},
    )
    response.headers["Cache-Control"] = "no-store"
    return _security_headers(response, scheme=scheme)


def _canonical_https_url(request: Request, *, host: _Authority) -> str:
    query = str(request.scope.get("query_string") or b"", "latin-1")
    path = str(request.scope.get("raw_path") or b"", "latin-1") or str(request.url.path or "/")
    target = f"https://{host.netloc}{path}"
    return f"{target}?{query}" if query else target


def _relativize_slash_redirect(request: Request, response: Response) -> None:
    if response.status_code not in {307, 308}:
        return
    location = str(response.headers.get("location") or "").strip()
    if not location:
        return
    parsed: SplitResult = urlsplit(location)
    if not parsed.scheme or not parsed.netloc:
        return
    request_path = str(request.scope.get("path") or "/")
    target_path = str(parsed.path or "/")
    if request_path == "/" or target_path == "/":
        return
    slash_variant = (
        request_path.endswith("/") and target_path == request_path.rstrip("/")
    ) or (
        not request_path.endswith("/") and target_path == f"{request_path}/"
    )
    if not slash_variant:
        return
    relative = target_path
    if parsed.query:
        relative = f"{relative}?{parsed.query}"
    response.headers["Location"] = relative


def _host_header(scope: dict[str, Any]) -> _Authority | None:
    values = _header_values(scope, b"host")
    if len(values) != 1:
        return None
    return _authority(values[0])


def install_public_http_hardening(app: FastAPI, *, settings: Any) -> None:
    production = is_prod_mode(str(getattr(settings, "runtime_mode", "") or ""))

    @app.middleware("http")
    async def public_http_hardening_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        raw_host_values = _header_values(request.scope, b"host")
        raw_host = _host_header(request.scope)
        initial_scheme = str(request.scope.get("scheme") or "http").lower()
        if len(raw_host_values) != 1 or raw_host is None:
            return _error_response(status_code=400, code="host_header_invalid", scheme=initial_scheme)

        trusted_proxy = _request_from_trusted_proxy(request)
        metadata = _ProxyMetadata(host=None, proto="")
        if trusted_proxy:
            try:
                metadata = _proxy_metadata(request.scope)
            except _ProxyMetadataError:
                return _error_response(status_code=400, code="proxy_header_invalid", scheme=initial_scheme)
        else:
            _strip_untrusted_proxy_headers(request, raw_host=raw_host)

        effective_host = metadata.host or raw_host
        origin = _public_origin()
        effective_proto = metadata.proto or initial_scheme
        if (
            trusted_proxy
            and metadata.host is None
            and origin is not None
            and raw_host.host not in _configured_hosts()
        ):
            effective_host = origin.authority
            effective_proto = metadata.proto or origin.scheme
            _rewrite_request_authority(request, host=effective_host, proto=effective_proto)
        if trusted_proxy and metadata.host is not None:
            if production and metadata.host.host not in _configured_hosts():
                return _error_response(status_code=421, code="forwarded_host_not_allowed", scheme=effective_proto)
            if not effective_proto and origin is not None and metadata.host.host == origin.authority.host:
                effective_proto = origin.scheme
            _rewrite_request_authority(request, host=metadata.host, proto=effective_proto or "https")

        local_request = effective_host.host in _LOCAL_HOSTS
        if production and not local_request and effective_host.host not in _configured_hosts():
            return _error_response(status_code=421, code="host_not_allowed", scheme=effective_proto)

        if production and not local_request and origin is not None and origin.scheme == "https" and effective_proto != "https":
            redirect_host = origin.authority if effective_host.host == origin.authority.host else effective_host
            response = RedirectResponse(_canonical_https_url(request, host=redirect_host), status_code=308)
            return _security_headers(response, scheme="https")

        response = await call_next(request)
        _relativize_slash_redirect(request, response)
        return _security_headers(response, scheme=effective_proto)


def api_docs_enabled(*, runtime_mode: str) -> bool:
    explicit = os.getenv("EA_ENABLE_API_DOCS")
    if explicit is not None:
        return _env_truthy(explicit)
    return not is_prod_mode(runtime_mode)


__all__ = ["api_docs_enabled", "install_public_http_hardening"]
