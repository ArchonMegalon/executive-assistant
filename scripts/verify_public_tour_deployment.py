#!/usr/bin/env python3
"""Read-only public-origin verifier for an EA public tour deployment."""

from __future__ import annotations

import argparse
import hashlib
import html
from html.parser import HTMLParser
import json
import re
from typing import Any
import urllib.error
import urllib.parse
import urllib.request


_VIDEO_RELEASE_CONTRACT = "ea.public-tour-video-release.v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REVISION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
_JSON_HTML_MAX_BYTES = 8 * 1024 * 1024
_VIEWER_MAX_BYTES = 16 * 1024 * 1024
_VIDEO_MAX_BYTES = 128 * 1024 * 1024
_HTTP_TIMEOUT_SECONDS = 20.0

_VIDEO_RELEASE_KEYS = frozenset(
    {
        "contract",
        "status",
        "release_revision",
        "asset_sha256",
        "disclosure",
        "synthetic",
        "verified_provider_capture",
    }
)
_GENERATED_VIEWER_KEYS = frozenset(
    {
        "url",
        "release_revision",
        "disclosure",
        "synthetic",
        "verified_provider_capture",
    }
)
_EXPECTED_VIEWER_CSP: dict[str, tuple[str, ...]] = {
    "default-src": ("'none'",),
    "script-src": ("'unsafe-inline'", "'self'"),
    "style-src": ("'unsafe-inline'",),
    "img-src": ("'self'", "data:"),
    "object-src": ("'none'",),
    "base-uri": ("'none'",),
    "form-action": ("'none'",),
    "frame-ancestors": ("'self'",),
}
_SENSITIVE_KEY_TOKENS = frozenset(
    {
        "authorization",
        "cookie",
        "cookies",
        "credential",
        "credentials",
        "debug",
        "email",
        "internal",
        "oauth",
        "owner",
        "password",
        "person",
        "phone",
        "principal",
        "private",
        "probe",
        "recipient",
        "secret",
        "session",
        "token",
    }
)
_SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "audit_rows",
        "auth_header",
        "raw_signal_json",
        "runtime_inputs_json",
        "source_asset_id",
        "source_asset_ref",
        "source_path",
        "source_uri",
    }
)


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(  # type: ignore[override]
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        del req, fp, code, msg, headers, newurl
        return None


class _VisibleTextParser(HTMLParser):
    _HIDDEN_CONTENT_TAGS = frozenset({"head", "script", "style", "template"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._hidden_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag.lower() in self._HIDDEN_CONTENT_TAGS:
            self._hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self._HIDDEN_CONTENT_TAGS and self._hidden_depth:
            self._hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._hidden_depth and data.strip():
            self.parts.append(data)


def _block(code: str, **context: object) -> dict[str, object]:
    row: dict[str, object] = {"code": code}
    for key in sorted(context):
        value = context[key]
        if value not in {None, ""}:
            row[key] = value
    return row


def _deduplicated_sorted(blockers: list[dict[str, object]]) -> list[dict[str, object]]:
    by_key: dict[str, dict[str, object]] = {}
    for blocker in blockers:
        key = json.dumps(
            blocker, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )
        by_key[key] = blocker
    return [by_key[key] for key in sorted(by_key)]


def _normalized_base_url(value: str) -> str:
    normalized = str(value or "").strip().rstrip("/")
    if not normalized or any(
        character in normalized for character in "\x00\r\n\\\"'`<>"
    ):
        return ""
    try:
        parsed = urllib.parse.urlsplit(normalized)
        port = parsed.port
    except ValueError:
        return ""
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        return ""
    path_parts = urllib.parse.unquote(parsed.path).split("/")
    if any(part in {".", ".."} for part in path_parts):
        return ""
    hostname = parsed.hostname.lower().rstrip(".")
    if not hostname or any(character.isspace() for character in hostname):
        return ""
    if ":" in hostname and not hostname.startswith("["):
        host = f"[{hostname}]"
    else:
        host = hostname
    default_port = 443 if parsed.scheme.lower() == "https" else 80
    netloc = host if port in {None, default_port} else f"{host}:{port}"
    return urllib.parse.urlunsplit(
        (parsed.scheme.lower(), netloc, parsed.path.rstrip("/"), "", "")
    )


def _origin_tuple(url: str) -> tuple[str, str, int] | None:
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        return None
    effective_port = port or (443 if parsed.scheme.lower() == "https" else 80)
    return parsed.scheme.lower(), parsed.hostname.lower().rstrip("."), effective_port


def _safe_same_origin_media_url(
    value: object,
    *,
    base_url: str,
    slug: str,
    route_kind: str,
) -> str:
    raw = str(value or "").strip()
    if not raw or any(character in raw for character in "\x00\r\n\\\"'`<>"):
        return ""
    if raw.startswith("//"):
        return ""
    try:
        parsed_raw = urllib.parse.urlsplit(raw)
        parsed_raw.port
    except ValueError:
        return ""
    if (
        parsed_raw.username
        or parsed_raw.password
        or parsed_raw.query
        or parsed_raw.fragment
    ):
        return ""
    if parsed_raw.scheme and parsed_raw.scheme.lower() not in {"http", "https"}:
        return ""
    if not parsed_raw.scheme and not raw.startswith("/"):
        return ""
    absolute = urllib.parse.urljoin(f"{base_url}/", raw)
    if _origin_tuple(absolute) != _origin_tuple(base_url):
        return ""
    parsed = urllib.parse.urlsplit(absolute)
    decoded_path = urllib.parse.unquote(parsed.path)
    parts = decoded_path.split("/")
    if any(part in {"", ".", ".."} for part in parts[1:]):
        return ""
    expected_prefix = f"/tours/{route_kind}/{slug}/"
    if not decoded_path.startswith(expected_prefix) or decoded_path == expected_prefix:
        return ""
    return absolute


def _http_fetch(url: str, *, method: str, max_body_bytes: int) -> dict[str, object]:
    request = urllib.request.Request(
        url,
        method=method,
        headers={
            "Accept": "*/*",
            "Accept-Encoding": "identity",
            "User-Agent": "EA-public-tour-deployment-verifier/1.0",
        },
    )
    opener = urllib.request.build_opener(_NoRedirectHandler())
    try:
        with opener.open(request, timeout=_HTTP_TIMEOUT_SECONDS) as response:
            body = response.read(max_body_bytes + 1) if method == "GET" else b""
            return {
                "status": int(response.status),
                "headers": {
                    key.lower(): value.strip()
                    for key, value in response.headers.items()
                },
                "body": body,
                "body_exceeded_cap": len(body) > max_body_bytes,
                "error": "",
            }
    except urllib.error.HTTPError as exc:
        return {
            "status": int(exc.code),
            "headers": {
                key.lower(): value.strip() for key, value in exc.headers.items()
            },
            "body": b"",
            "body_exceeded_cap": False,
            "error": "http_error",
        }
    except (urllib.error.URLError, TimeoutError, OSError):
        return {
            "status": 0,
            "headers": {},
            "body": b"",
            "body_exceeded_cap": False,
            "error": "transport_error",
        }


def _headers(receipt: dict[str, object]) -> dict[str, str]:
    return {
        str(key).lower(): str(value).strip()
        for key, value in dict(receipt.get("headers") or {}).items()
    }


def _normalized_content_type(value: str) -> str:
    return value.split(";", 1)[0].strip().lower()


def _parse_csp(value: str) -> dict[str, tuple[str, ...]] | None:
    directives: dict[str, tuple[str, ...]] = {}
    for raw_directive in value.split(";"):
        tokens = raw_directive.strip().split()
        if not tokens:
            continue
        name = tokens[0].lower()
        if name in directives:
            return None
        directives[name] = tuple(tokens[1:])
    return directives


def _immutable_cache(value: str) -> bool:
    tokens = {token.strip().lower() for token in value.split(",") if token.strip()}
    if "no-store" in tokens or not {"public", "immutable"}.issubset(tokens):
        return False
    for token in tokens:
        if token.startswith("max-age="):
            seconds = token.removeprefix("max-age=")
            return seconds.isdigit() and int(seconds) > 0
    return False


def _safe_revision(value: object) -> str:
    normalized = str(value or "").strip()
    return normalized if _REVISION_RE.fullmatch(normalized) else ""


def _provenance_category(value: str) -> str:
    normalized = str(value or "").strip().replace("\\", "/").lower()
    if not normalized:
        return ""
    if normalized.startswith(("/tmp/", "/var/tmp/")) or "/tmp/" in normalized:
        return "temporary_path"
    if "pytest" in normalized:
        return "pytest"
    if normalized.startswith("file://") or normalized.startswith(
        ("/docker/", "/workspace/", "/app/", "/home/")
    ):
        return "local_filesystem"
    for category in ("internal", "debug", "probe"):
        if re.search(rf"(?:^|[^a-z0-9]){category}(?:[^a-z0-9]|$)", normalized):
            return category
    if re.search(
        r"https?://(?:localhost|127(?:\.[0-9]{1,3}){3}|\[?::1\]?)(?::|/|$)", normalized
    ):
        return "loopback"
    return ""


def _normalized_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")


def _sensitive_key(value: object) -> bool:
    normalized = _normalized_key(value)
    if normalized in _SENSITIVE_KEYS:
        return True
    return bool(set(normalized.split("_")) & _SENSITIVE_KEY_TOKENS)


def _json_path_key(parent: str, key: object) -> str:
    normalized = str(key)
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", normalized):
        return f"{parent}.{normalized}"
    return f"{parent}[{json.dumps(normalized, ensure_ascii=True)}]"


def _public_payload_blockers(
    value: object, *, path: str = "$"
) -> list[dict[str, object]]:
    blockers: list[dict[str, object]] = []
    if isinstance(value, dict):
        for key in sorted(value, key=lambda candidate: str(candidate)):
            child_path = _json_path_key(path, key)
            if _sensitive_key(key):
                blockers.append(
                    _block(
                        "sensitive_key_exposed",
                        path=child_path,
                        key=_normalized_key(key),
                    )
                )
            blockers.extend(_public_payload_blockers(value[key], path=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            blockers.extend(_public_payload_blockers(child, path=f"{path}[{index}]"))
    elif isinstance(value, str):
        category = _provenance_category(value)
        if category:
            blockers.append(
                _block(
                    "provenance_string_forbidden",
                    path=path,
                    category=category,
                )
            )
    return blockers


def _key_occurrences(value: object, target: str, *, path: str = "$") -> list[str]:
    occurrences: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = _json_path_key(path, key)
            if str(key) == target:
                occurrences.append(child_path)
            occurrences.extend(_key_occurrences(child, target, path=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            occurrences.extend(_key_occurrences(child, target, path=f"{path}[{index}]"))
    return sorted(occurrences)


def _truthful_disclosure(
    value: object,
    *,
    synthetic: bool,
    verified_provider_capture: bool,
) -> str:
    disclosure = " ".join(str(value or "").strip().split())
    if (
        not disclosure
        or len(disclosure) > 1000
        or any(ord(character) < 32 for character in disclosure)
        or _provenance_category(disclosure)
        or synthetic
        and verified_provider_capture
    ):
        return ""
    lowered = disclosure.lower()
    if synthetic:
        if not any(
            token in lowered for token in ("generated", "synthetic", "reconstruction")
        ):
            return ""
        if "not" not in lowered or not any(
            token in lowered for token in ("captured", "provider-verified", "scan")
        ):
            return ""
    elif verified_provider_capture:
        if "provider" not in lowered or not any(
            token in lowered for token in ("captured", "verified", "reviewed")
        ):
            return ""
    elif not (
        "not" in lowered
        and any(token in lowered for token in ("captured", "provider-verified", "scan"))
    ):
        return ""
    return disclosure


def _video_projection(
    payload: dict[str, object],
    *,
    base_url: str,
    slug: str,
) -> tuple[dict[str, object], str, list[dict[str, object]]]:
    blockers: list[dict[str, object]] = []
    video_occurrences = _key_occurrences(payload, "video_url")
    raw_release = payload.get("video_release")
    if video_occurrences and video_occurrences != ["$.video_url"]:
        blockers.append(
            _block("video_url_projection_invalid", paths=",".join(video_occurrences))
        )
    if not video_occurrences:
        if raw_release is not None:
            blockers.append(_block("video_release_without_url"))
        return {}, "", blockers
    if not isinstance(raw_release, dict):
        blockers.append(_block("video_url_without_release"))
        return {}, "", blockers
    release = dict(raw_release)
    if set(release) != _VIDEO_RELEASE_KEYS:
        blockers.append(_block("video_release_projection_keys_invalid"))
    revision = _safe_revision(release.get("release_revision"))
    digest = str(release.get("asset_sha256") or "").strip().lower()
    synthetic = release.get("synthetic")
    verified_capture = release.get("verified_provider_capture")
    if (
        release.get("contract") != _VIDEO_RELEASE_CONTRACT
        or release.get("status") != "ready"
    ):
        blockers.append(_block("video_release_contract_invalid"))
    if not revision:
        blockers.append(_block("video_release_revision_invalid"))
    if not _SHA256_RE.fullmatch(digest):
        blockers.append(_block("video_release_digest_invalid"))
    if type(synthetic) is not bool or type(verified_capture) is not bool:
        blockers.append(_block("video_release_truth_flags_invalid"))
        disclosure = ""
    else:
        disclosure = _truthful_disclosure(
            release.get("disclosure"),
            synthetic=synthetic,
            verified_provider_capture=verified_capture,
        )
        if not disclosure:
            blockers.append(_block("video_release_disclosure_invalid"))
    media_url = _safe_same_origin_media_url(
        payload.get("video_url"),
        base_url=base_url,
        slug=slug,
        route_kind="files",
    )
    if not media_url:
        blockers.append(_block("video_url_invalid"))
    return release, media_url, blockers


def _viewer_projection(
    payload: dict[str, object],
    *,
    base_url: str,
    slug: str,
) -> tuple[dict[str, object], str, list[dict[str, object]]]:
    blockers: list[dict[str, object]] = []
    occurrences = _key_occurrences(payload, "generated_viewer")
    if occurrences and occurrences != ["$.generated_viewer"]:
        blockers.append(
            _block("generated_viewer_projection_invalid", paths=",".join(occurrences))
        )
    if not occurrences:
        viewer_urls = [
            path for path in _string_paths_matching(payload, needle="/tours/viewer/")
        ]
        if viewer_urls:
            blockers.append(
                _block("viewer_url_without_projection", paths=",".join(viewer_urls))
            )
        return {}, "", blockers
    raw_projection = payload.get("generated_viewer")
    if not isinstance(raw_projection, dict):
        blockers.append(_block("generated_viewer_invalid"))
        return {}, "", blockers
    projection = dict(raw_projection)
    if set(projection) != _GENERATED_VIEWER_KEYS:
        blockers.append(_block("generated_viewer_projection_keys_invalid"))
    if not _safe_revision(projection.get("release_revision")):
        blockers.append(_block("generated_viewer_revision_invalid"))
    if (
        projection.get("synthetic") is not True
        or projection.get("verified_provider_capture") is not False
    ):
        blockers.append(_block("generated_viewer_truth_flags_invalid"))
    disclosure = _truthful_disclosure(
        projection.get("disclosure"),
        synthetic=True,
        verified_provider_capture=False,
    )
    if not disclosure:
        blockers.append(_block("generated_viewer_disclosure_invalid"))
    viewer_url = _safe_same_origin_media_url(
        projection.get("url"),
        base_url=base_url,
        slug=slug,
        route_kind="viewer",
    )
    if not viewer_url:
        blockers.append(_block("generated_viewer_url_invalid"))
    return projection, viewer_url, blockers


def _string_paths_matching(value: object, *, needle: str, path: str = "$") -> list[str]:
    matches: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            matches.extend(
                _string_paths_matching(
                    child, needle=needle, path=_json_path_key(path, key)
                )
            )
    elif isinstance(value, list):
        for index, child in enumerate(value):
            matches.extend(
                _string_paths_matching(child, needle=needle, path=f"{path}[{index}]")
            )
    elif isinstance(value, str) and needle in value:
        matches.append(path)
    return sorted(matches)


def _response_basics(
    receipt: dict[str, object],
    *,
    endpoint: str,
    method: str,
    expected_content_type: str,
) -> list[dict[str, object]]:
    blockers: list[dict[str, object]] = []
    status_code = int(receipt.get("status") or 0)
    headers = _headers(receipt)
    if status_code != 200:
        blockers.append(
            _block(
                "http_status_invalid",
                endpoint=endpoint,
                method=method,
                expected=200,
                actual=status_code,
            )
        )
        return blockers
    actual_content_type = _normalized_content_type(headers.get("content-type", ""))
    if actual_content_type != expected_content_type:
        blockers.append(
            _block(
                "http_content_type_invalid",
                endpoint=endpoint,
                method=method,
                expected=expected_content_type,
                actual=actual_content_type,
            )
        )
    if bool(receipt.get("body_exceeded_cap")):
        blockers.append(
            _block("http_body_size_cap_exceeded", endpoint=endpoint, method=method)
        )
    return blockers


def _content_length_blockers(
    *,
    headers: dict[str, str],
    actual_size: int,
    endpoint: str,
    method: str,
) -> list[dict[str, object]]:
    raw_length = headers.get("content-length", "").strip()
    if not raw_length.isdigit() or int(raw_length) != actual_size:
        return [
            _block(
                "http_content_length_invalid",
                endpoint=endpoint,
                method=method,
                expected=actual_size,
                actual=raw_length,
            )
        ]
    return []


def _verify_video_origin(
    *,
    url: str,
    release: dict[str, object],
) -> tuple[list[dict[str, object]], int]:
    blockers: list[dict[str, object]] = []
    expected_digest = str(release.get("asset_sha256") or "").lower()
    expected_revision = str(release.get("release_revision") or "")
    get_body = b""
    get_headers: dict[str, str] = {}
    get_size = 0
    head_headers: dict[str, str] = {}
    for method in ("HEAD", "GET"):
        receipt = _http_fetch(url, method=method, max_body_bytes=_VIDEO_MAX_BYTES)
        blockers.extend(
            _response_basics(
                receipt,
                endpoint="video",
                method=method,
                expected_content_type="video/mp4",
            )
        )
        if int(receipt.get("status") or 0) != 200:
            continue
        headers = _headers(receipt)
        if not _immutable_cache(headers.get("cache-control", "")):
            blockers.append(_block("video_cache_invalid", method=method))
        if headers.get("x-propertyquarry-asset-sha256", "").lower() != expected_digest:
            blockers.append(_block("video_digest_header_invalid", method=method))
        if headers.get("x-propertyquarry-media-revision", "") != expected_revision:
            blockers.append(_block("video_revision_header_invalid", method=method))
        if headers.get("x-content-type-options", "").lower() != "nosniff":
            blockers.append(_block("video_nosniff_missing", method=method))
        if headers.get("content-encoding", "").lower() not in {"", "identity"}:
            blockers.append(_block("video_content_encoding_invalid", method=method))
        if method == "GET":
            get_body = bytes(receipt.get("body") or b"")
            get_headers = headers
            get_size = len(get_body)
            if not get_body or get_size > _VIDEO_MAX_BYTES:
                blockers.append(_block("video_body_size_invalid", actual=get_size))
            elif hashlib.sha256(get_body).hexdigest() != expected_digest:
                blockers.append(_block("video_body_digest_mismatch"))
            blockers.extend(
                _content_length_blockers(
                    headers=headers,
                    actual_size=get_size,
                    endpoint="video",
                    method=method,
                )
            )
        else:
            head_headers = headers
            raw_length = headers.get("content-length", "")
            if not raw_length.isdigit() or not (
                0 < int(raw_length) <= _VIDEO_MAX_BYTES
            ):
                blockers.append(_block("video_head_size_invalid", actual=raw_length))
    if get_headers and head_headers:
        if head_headers.get("content-length", "") != str(get_size):
            blockers.append(_block("video_head_get_size_mismatch"))
    return blockers, get_size


def _verify_viewer_origin(
    *,
    url: str,
    projection: dict[str, object],
) -> tuple[list[dict[str, object]], int]:
    blockers: list[dict[str, object]] = []
    expected_revision = str(projection.get("release_revision") or "")
    method_headers: dict[str, dict[str, str]] = {}
    get_body = b""
    for method in ("HEAD", "GET"):
        receipt = _http_fetch(url, method=method, max_body_bytes=_VIEWER_MAX_BYTES)
        blockers.extend(
            _response_basics(
                receipt,
                endpoint="generated_viewer",
                method=method,
                expected_content_type="text/html",
            )
        )
        if int(receipt.get("status") or 0) != 200:
            continue
        headers = _headers(receipt)
        method_headers[method] = headers
        if headers.get("cache-control", "").lower() != "no-store":
            blockers.append(_block("viewer_cache_invalid", method=method))
        if headers.get("access-control-allow-origin", "") != "*":
            blockers.append(_block("viewer_acao_invalid", method=method))
        if headers.get("cross-origin-resource-policy", "").lower() != "cross-origin":
            blockers.append(_block("viewer_corp_invalid", method=method))
        if headers.get("x-content-type-options", "").lower() != "nosniff":
            blockers.append(_block("viewer_nosniff_missing", method=method))
        if headers.get("x-propertyquarry-viewer-revision", "") != expected_revision:
            blockers.append(_block("viewer_revision_header_invalid", method=method))
        digest_header = headers.get("x-propertyquarry-asset-sha256", "").lower()
        if not _SHA256_RE.fullmatch(digest_header):
            blockers.append(_block("viewer_digest_header_invalid", method=method))
        if (
            _parse_csp(headers.get("content-security-policy", ""))
            != _EXPECTED_VIEWER_CSP
        ):
            blockers.append(_block("viewer_csp_invalid", method=method))
        if method == "GET":
            get_body = bytes(receipt.get("body") or b"")
            if not get_body or len(get_body) > _VIEWER_MAX_BYTES:
                blockers.append(
                    _block("viewer_body_size_invalid", actual=len(get_body))
                )
            blockers.extend(
                _content_length_blockers(
                    headers=headers,
                    actual_size=len(get_body),
                    endpoint="generated_viewer",
                    method=method,
                )
            )
            if (
                _SHA256_RE.fullmatch(digest_header)
                and hashlib.sha256(get_body).hexdigest() != digest_header
            ):
                blockers.append(_block("viewer_body_digest_mismatch"))
        else:
            raw_length = headers.get("content-length", "")
            if not raw_length.isdigit() or not (
                0 < int(raw_length) <= _VIEWER_MAX_BYTES
            ):
                blockers.append(_block("viewer_head_size_invalid", actual=raw_length))
    if {"GET", "HEAD"}.issubset(method_headers):
        if (
            method_headers["GET"].get("x-propertyquarry-asset-sha256", "").lower()
            != method_headers["HEAD"].get("x-propertyquarry-asset-sha256", "").lower()
        ):
            blockers.append(_block("viewer_digest_headers_mismatch"))
        if method_headers["HEAD"].get("content-length", "") != str(len(get_body)):
            blockers.append(_block("viewer_head_get_size_mismatch"))
    return blockers, len(get_body)


def _visible_text(source: bytes) -> str:
    try:
        decoded = source.decode("utf-8")
    except UnicodeDecodeError:
        return ""
    parser = _VisibleTextParser()
    try:
        parser.feed(decoded)
        parser.close()
    except Exception:
        return ""
    return " ".join(html.unescape(" ".join(parser.parts)).split())


def _fallback_disclosure_present(visible_text: str) -> bool:
    lowered = visible_text.lower()
    return any(
        marker in lowered
        for marker in (
            "does not claim a captured",
            "not a captured",
            "verified external",
            "hosted panorama",
        )
    )


def verify_deployment(*, base_url: str, slug: str) -> dict[str, object]:
    normalized_base = _normalized_base_url(base_url)
    normalized_slug = str(slug or "").strip()
    blockers: list[dict[str, object]] = []
    payload: dict[str, object] = {}
    html_body = b""
    video_present = False
    viewer_present = False
    video_verified = False
    viewer_verified = False
    video_size = 0
    viewer_size = 0

    if not normalized_base:
        blockers.append(_block("base_url_invalid"))
    if not _SLUG_RE.fullmatch(normalized_slug) or normalized_slug in {".", ".."}:
        blockers.append(_block("slug_invalid"))
    if normalized_base and _SLUG_RE.fullmatch(normalized_slug):
        quoted_slug = urllib.parse.quote(normalized_slug, safe="")
        json_url = f"{normalized_base}/tours/{quoted_slug}.json"
        html_url = f"{normalized_base}/tours/{quoted_slug}"
        json_receipt = _http_fetch(
            json_url, method="GET", max_body_bytes=_JSON_HTML_MAX_BYTES
        )
        html_receipt = _http_fetch(
            html_url, method="GET", max_body_bytes=_JSON_HTML_MAX_BYTES
        )
        blockers.extend(
            _response_basics(
                json_receipt,
                endpoint="tour_json",
                method="GET",
                expected_content_type="application/json",
            )
        )
        blockers.extend(
            _response_basics(
                html_receipt,
                endpoint="tour_html",
                method="GET",
                expected_content_type="text/html",
            )
        )
        json_headers = _headers(json_receipt)
        json_response_valid = (
            int(json_receipt.get("status") or 0) == 200
            and not json_receipt.get("body_exceeded_cap")
            and _normalized_content_type(json_headers.get("content-type", ""))
            == "application/json"
        )
        html_headers = _headers(html_receipt)
        html_response_valid = (
            int(html_receipt.get("status") or 0) == 200
            and not html_receipt.get("body_exceeded_cap")
            and _normalized_content_type(html_headers.get("content-type", ""))
            == "text/html"
        )
        if json_response_valid:
            try:
                decoded = json.loads(
                    bytes(json_receipt.get("body") or b"").decode("utf-8")
                )
                if isinstance(decoded, dict):
                    payload = decoded
                else:
                    blockers.append(_block("tour_json_not_object"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                blockers.append(_block("tour_json_invalid"))
        if html_response_valid:
            html_body = bytes(html_receipt.get("body") or b"")

    release: dict[str, object] = {}
    video_url = ""
    viewer: dict[str, object] = {}
    viewer_url = ""
    if payload:
        if str(payload.get("slug") or "").strip() != normalized_slug:
            blockers.append(_block("payload_slug_mismatch"))
        blockers.extend(_public_payload_blockers(payload))
        release, video_url, video_blockers = _video_projection(
            payload,
            base_url=normalized_base,
            slug=normalized_slug,
        )
        blockers.extend(video_blockers)
        viewer, viewer_url, viewer_blockers = _viewer_projection(
            payload,
            base_url=normalized_base,
            slug=normalized_slug,
        )
        blockers.extend(viewer_blockers)
        video_present = "video_url" in payload
        viewer_present = "generated_viewer" in payload
        if video_url and release and not video_blockers:
            media_blockers, video_size = _verify_video_origin(
                url=video_url, release=release
            )
            blockers.extend(media_blockers)
            video_verified = not media_blockers
        if viewer_url and viewer and not viewer_blockers:
            viewer_origin_blockers, viewer_size = _verify_viewer_origin(
                url=viewer_url,
                projection=viewer,
            )
            blockers.extend(viewer_origin_blockers)
            viewer_verified = not viewer_origin_blockers

    visible_text = _visible_text(html_body) if html_body else ""
    active_disclosure = ""
    if viewer:
        active_disclosure = str(viewer.get("disclosure") or "").strip()
    elif release:
        active_disclosure = str(release.get("disclosure") or "").strip()
    if html_body:
        normalized_visible = " ".join(visible_text.lower().split())
        normalized_disclosure = " ".join(active_disclosure.lower().split())
        if active_disclosure:
            if (
                not normalized_disclosure
                or normalized_disclosure not in normalized_visible
            ):
                blockers.append(_block("html_release_disclosure_missing"))
        elif not _fallback_disclosure_present(visible_text):
            blockers.append(_block("html_truthful_disclosure_missing"))

    blockers = _deduplicated_sorted(blockers)
    passed = not blockers
    return {
        "status": "pass" if passed else "blocked",
        "pass": passed,
        "blockers": blockers,
        "base_url": normalized_base or str(base_url or "").strip(),
        "slug": normalized_slug,
        "checks": {
            "json_verified": bool(payload),
            "html_verified": bool(html_body),
            "video_present": video_present,
            "video_verified": video_verified,
            "video_size_bytes": video_size,
            "generated_viewer_present": viewer_present,
            "generated_viewer_verified": viewer_verified,
            "generated_viewer_size_bytes": viewer_size,
        },
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify an EA public-tour origin without modifying it."
    )
    parser.add_argument(
        "--base-url",
        required=True,
        help="EA public origin, optionally with a path prefix.",
    )
    parser.add_argument("--slug", required=True, help="Public tour slug.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        receipt = verify_deployment(base_url=args.base_url, slug=args.slug)
    except Exception as exc:  # pragma: no cover - final fail-closed CLI guard
        receipt = {
            "status": "blocked",
            "pass": False,
            "blockers": [_block("verification_error", error_type=type(exc).__name__)],
            "base_url": str(args.base_url or "").strip(),
            "slug": str(args.slug or "").strip(),
            "checks": {
                "json_verified": False,
                "html_verified": False,
                "video_present": False,
                "video_verified": False,
                "video_size_bytes": 0,
                "generated_viewer_present": False,
                "generated_viewer_verified": False,
                "generated_viewer_size_bytes": 0,
            },
        }
    print(json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=True))
    return 0 if receipt["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
