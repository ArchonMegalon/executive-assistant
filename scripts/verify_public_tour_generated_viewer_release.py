#!/usr/bin/env python3
"""Read-only verifier for a released generated public-tour viewer bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
from typing import Any
import urllib.error
import urllib.parse
import urllib.request


_REPO_ROOT = Path(__file__).resolve().parents[1]
_APP_IMPORT_ROOTS = (_REPO_ROOT / "ea", _REPO_ROOT)
for _app_import_root in _APP_IMPORT_ROOTS:
    if (_app_import_root / "app").is_dir() and str(_app_import_root) not in sys.path:
        sys.path.insert(0, str(_app_import_root))
        break

from app.services.public_tour_release_policy import (  # noqa: E402
    evaluate_public_tour_generated_viewer_release,
)


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REVISION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
_GENERATED_PREFIX = "generated-reconstruction/"
_EXPECTED_FILE_MODE = 0o644
_EXPECTED_DIRECTORY_MODE = 0o755
_MAX_TOUR_JSON_BYTES = 4 * 1024 * 1024
_HTTP_TIMEOUT_SECONDS = 15.0

_SERVEABLE_ROLE_MIME_SUFFIXES: dict[str, dict[str, tuple[str, ...]]] = {
    "viewer_document": {"text/html": (".html",)},
    "viewer_module": {
        "application/javascript": (".js",),
        "text/javascript": (".js",),
    },
    "floorplan_texture": {
        "image/jpeg": (".jpg", ".jpeg"),
        "image/png": (".png",),
        "image/webp": (".webp",),
    },
    "photo_texture": {
        "image/jpeg": (".jpg", ".jpeg"),
        "image/png": (".png",),
        "image/webp": (".webp",),
    },
}
_PROOF_ROLE_MIME_SUFFIXES: dict[str, dict[str, tuple[str, ...]]] = {
    "reconstruction_manifest": {"application/json": (".json",)},
}
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


def _block(code: str, **context: object) -> dict[str, object]:
    row: dict[str, object] = {"code": code}
    for key in sorted(context):
        value = context[key]
        if value not in {None, ""}:
            row[key] = value
    return row


def _safe_relpath(value: object) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    if (
        not raw
        or raw.startswith("/")
        or "://" in raw
        or "\x00" in raw
        or any(character in raw for character in "\"'`<>&")
    ):
        return ""
    raw_parts = raw.split("/")
    if not raw_parts or any(part in {"", ".", ".."} for part in raw_parts):
        return ""
    return "/".join(raw_parts)


def _source_reference_is_unsafe(value: object) -> bool:
    normalized = str(value or "").strip().replace("\\", "/").lower()
    if not normalized:
        return True
    if normalized.startswith(("/tmp/", "/var/tmp/")) or "/tmp/" in normalized:
        return True
    return bool(
        re.search(r"(?:^|[/._-])(?:pytest(?:-of)?|debug|probe)(?:[/._-]|$)", normalized)
    )


def _source_references(value: object) -> list[str]:
    references: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            normalized_key = str(key or "").strip().lower().replace("-", "_")
            if normalized_key in {
                "source_path",
                "source_uri",
                "source_asset_ref",
                "source_asset_id",
            }:
                references.append(str(child or "").strip())
            else:
                references.extend(_source_references(child))
    elif isinstance(value, list):
        for child in value:
            references.extend(_source_references(child))
    return references


def _proof_manifest_provenance_blockers(
    content: bytes, *, path: str
) -> list[dict[str, object]]:
    try:
        decoded = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return [_block("source_provenance_manifest_invalid", path=path)]
    if not isinstance(decoded, dict):
        return [_block("source_provenance_manifest_invalid", path=path)]
    references = _source_references(decoded)
    if not references:
        return [_block("source_provenance_missing", path=path)]
    unsafe_count = sum(
        _source_reference_is_unsafe(reference) for reference in references
    )
    if unsafe_count:
        return [
            _block(
                "source_provenance_unsafe",
                path=path,
                unsafe_reference_count=unsafe_count,
            )
        ]
    return []


def _mode_string(mode: int) -> str:
    return f"0o{stat.S_IMODE(mode):04o}"


def _lstat(path: Path) -> os.stat_result | None:
    try:
        return os.lstat(path)
    except OSError:
        return None


def _read_open_regular_file(descriptor: int, *, max_bytes: int | None = None) -> bytes:
    file_stat = os.fstat(descriptor)
    if not stat.S_ISREG(file_stat.st_mode):
        raise OSError("not_regular_file")
    if max_bytes is not None and file_stat.st_size > max_bytes:
        raise OSError("file_too_large")
    chunks: list[bytes] = []
    remaining = file_stat.st_size
    while remaining > 0:
        chunk = os.read(descriptor, min(1024 * 1024, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    if remaining != 0:
        raise OSError("short_read")
    return b"".join(chunks)


def _read_bundle_file_no_follow(
    bundle_dir: Path,
    relpath: str,
    *,
    max_bytes: int | None = None,
) -> bytes:
    parts = PurePosixPath(relpath).parts
    if not parts:
        raise OSError("empty_path")
    common_flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        common_flags |= os.O_CLOEXEC
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory_flags = common_flags | getattr(os, "O_DIRECTORY", 0) | nofollow
    descriptor = os.open(bundle_dir, directory_flags)
    try:
        for part in parts[:-1]:
            child_descriptor = os.open(part, directory_flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child_descriptor
        file_flags = common_flags | nofollow
        file_descriptor = os.open(parts[-1], file_flags, dir_fd=descriptor)
        try:
            return _read_open_regular_file(file_descriptor, max_bytes=max_bytes)
        finally:
            os.close(file_descriptor)
    finally:
        os.close(descriptor)


def _path_component_blockers(bundle_dir: Path, relpath: str) -> list[dict[str, object]]:
    blockers: list[dict[str, object]] = []
    cursor = bundle_dir
    parts = PurePosixPath(relpath).parts
    for index, part in enumerate(parts):
        cursor = cursor / part
        path_stat = _lstat(cursor)
        display_path = "/".join(parts[: index + 1])
        if path_stat is None:
            blockers.append(_block("asset_missing", path=display_path))
            break
        if stat.S_ISLNK(path_stat.st_mode):
            blockers.append(_block("symlink_forbidden", path=display_path))
            break
        is_final = index == len(parts) - 1
        expected_type = stat.S_ISREG if is_final else stat.S_ISDIR
        if not expected_type(path_stat.st_mode):
            blockers.append(
                _block(
                    "asset_type_invalid" if is_final else "directory_type_invalid",
                    path=display_path,
                )
            )
            break
        expected_mode = _EXPECTED_FILE_MODE if is_final else _EXPECTED_DIRECTORY_MODE
        actual_mode = stat.S_IMODE(path_stat.st_mode)
        if actual_mode != expected_mode:
            blockers.append(
                _block(
                    "unsafe_file_mode" if is_final else "unsafe_directory_mode",
                    path=display_path,
                    expected=_mode_string(expected_mode),
                    actual=_mode_string(actual_mode),
                )
            )
    return blockers


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


def _normalized_content_type(value: str) -> str:
    return value.split(";", 1)[0].strip().lower()


def _normalized_base_url(value: str) -> str:
    normalized = str(value or "").strip().rstrip("/")
    parsed = urllib.parse.urlsplit(normalized)
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        return ""
    try:
        parsed.port
    except ValueError:
        return ""
    return urllib.parse.urlunsplit(
        (parsed.scheme.lower(), parsed.netloc, parsed.path.rstrip("/"), "", "")
    )


def _http_fetch(url: str, *, method: str, max_body_bytes: int) -> dict[str, object]:
    request = urllib.request.Request(
        url,
        method=method,
        headers={
            "Accept": "*/*",
            "Accept-Encoding": "identity",
            "User-Agent": "EA-generated-viewer-release-verifier/1.0",
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
                "error": "",
            }
    except urllib.error.HTTPError as exc:
        return {
            "status": int(exc.code),
            "headers": {
                key.lower(): value.strip() for key, value in exc.headers.items()
            },
            "body": b"",
            "error": "http_error",
        }
    except (urllib.error.URLError, TimeoutError, OSError):
        return {"status": 0, "headers": {}, "body": b"", "error": "transport_error"}


def _binding_contract_blockers(
    *,
    binding: dict[str, object],
    viewer_relpath: str,
    reconstruction_manifest_relpath: str,
) -> tuple[list[dict[str, object]], bool]:
    path = _safe_relpath(binding.get("path"))
    role = str(binding.get("role") or "").strip().lower()
    mime_type = str(binding.get("mime_type") or "").strip().lower()
    blockers: list[dict[str, object]] = []
    serveable = role in _SERVEABLE_ROLE_MIME_SUFFIXES
    role_contract = (
        _SERVEABLE_ROLE_MIME_SUFFIXES.get(role)
        if serveable
        else _PROOF_ROLE_MIME_SUFFIXES.get(role)
    )
    if not path or not path.startswith(_GENERATED_PREFIX):
        blockers.append(
            _block("binding_path_invalid", path=path or str(binding.get("path") or ""))
        )
    if role_contract is None:
        blockers.append(_block("binding_role_invalid", path=path, role=role))
        return blockers, False
    allowed_suffixes = role_contract.get(mime_type)
    if not allowed_suffixes or Path(path).suffix.lower() not in allowed_suffixes:
        blockers.append(
            _block(
                "binding_mime_path_invalid", path=path, mime_type=mime_type, role=role
            )
        )
    if role == "viewer_document" and path != viewer_relpath:
        blockers.append(_block("viewer_document_path_mismatch", path=path))
    if role == "reconstruction_manifest" and path != reconstruction_manifest_relpath:
        blockers.append(_block("proof_manifest_path_mismatch", path=path))
    return blockers, serveable


def _http_binding_blockers(
    *,
    base_url: str,
    slug: str,
    path: str,
    binding: dict[str, object],
    release_revision: str,
) -> list[dict[str, object]]:
    blockers: list[dict[str, object]] = []
    role = str(binding.get("role") or "").strip().lower()
    expected_mime = str(binding.get("mime_type") or "").strip().lower()
    expected_sha256 = str(binding.get("sha256") or "").strip().lower()
    expected_size = int(binding.get("size_bytes") or 0)
    quoted_slug = urllib.parse.quote(slug, safe="")
    quoted_path = urllib.parse.quote(path, safe="/")
    url = f"{base_url}/tours/viewer/{quoted_slug}/{quoted_path}"
    for method in ("HEAD", "GET"):
        receipt = _http_fetch(url, method=method, max_body_bytes=expected_size)
        status_code = int(receipt.get("status") or 0)
        headers = dict(receipt.get("headers") or {})
        if status_code != 200:
            blockers.append(
                _block(
                    "http_status_invalid",
                    path=path,
                    method=method,
                    expected=200,
                    actual=status_code,
                )
            )
            continue
        actual_mime = _normalized_content_type(str(headers.get("content-type") or ""))
        if actual_mime != expected_mime:
            blockers.append(
                _block(
                    "http_content_type_invalid",
                    path=path,
                    method=method,
                    expected=expected_mime,
                    actual=actual_mime,
                )
            )
        if str(headers.get("access-control-allow-origin") or "") != "*":
            blockers.append(_block("http_acao_invalid", path=path, method=method))
        if (
            str(headers.get("cross-origin-resource-policy") or "").lower()
            != "cross-origin"
        ):
            blockers.append(_block("http_corp_invalid", path=path, method=method))
        if str(headers.get("x-content-type-options") or "").lower() != "nosniff":
            blockers.append(_block("http_nosniff_missing", path=path, method=method))
        if (
            str(headers.get("x-propertyquarry-asset-sha256") or "").lower()
            != expected_sha256
        ):
            blockers.append(
                _block("http_digest_header_invalid", path=path, method=method)
            )
        if (
            str(headers.get("x-propertyquarry-viewer-revision") or "")
            != release_revision
        ):
            blockers.append(
                _block("http_revision_header_invalid", path=path, method=method)
            )

        cache_control = str(headers.get("cache-control") or "").lower()
        if role == "viewer_document":
            if cache_control != "no-store":
                blockers.append(
                    _block("http_document_cache_invalid", path=path, method=method)
                )
            csp = _parse_csp(str(headers.get("content-security-policy") or ""))
            if csp != _EXPECTED_VIEWER_CSP:
                blockers.append(
                    _block("http_document_csp_invalid", path=path, method=method)
                )
        else:
            cache_tokens = {
                token.strip() for token in cache_control.split(",") if token.strip()
            }
            if not {"public", "immutable"}.issubset(cache_tokens) or not any(
                token.startswith("max-age=")
                and token.removeprefix("max-age=").isdigit()
                and int(token.removeprefix("max-age=")) > 0
                for token in cache_tokens
            ):
                blockers.append(
                    _block("http_asset_cache_invalid", path=path, method=method)
                )

        content_length = str(headers.get("content-length") or "").strip()
        if not content_length.isdigit() or int(content_length) != expected_size:
            blockers.append(
                _block(
                    "http_content_length_invalid",
                    path=path,
                    method=method,
                    expected=expected_size,
                    actual=content_length,
                )
            )
        if method == "GET":
            body = bytes(receipt.get("body") or b"")
            if (
                len(body) != expected_size
                or hashlib.sha256(body).hexdigest() != expected_sha256
            ):
                blockers.append(
                    _block("http_body_integrity_failed", path=path, method=method)
                )
    return blockers


def _deduplicated_sorted(blockers: list[dict[str, object]]) -> list[dict[str, object]]:
    by_key: dict[str, dict[str, object]] = {}
    for blocker in blockers:
        key = json.dumps(
            blocker, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )
        by_key[key] = blocker
    return [by_key[key] for key in sorted(by_key)]


def verify_bundle(
    bundle_dir: str | os.PathLike[str],
    *,
    base_url: str = "",
    slug: str = "",
) -> dict[str, object]:
    """Verify one bundle and return a deterministic, JSON-serializable receipt."""

    bundle = Path(os.path.abspath(os.path.expanduser(os.fspath(bundle_dir))))
    blockers: list[dict[str, object]] = []
    policy_released = False
    bindings: dict[str, dict[str, object]] = {}
    serveable_paths: list[str] = []
    proof_only_paths: list[str] = []
    payload: dict[str, object] = {}
    release: dict[str, object] = {}

    bundle_stat = _lstat(bundle)
    if bundle_stat is None:
        blockers.append(_block("bundle_missing"))
    elif stat.S_ISLNK(bundle_stat.st_mode):
        blockers.append(_block("bundle_symlink_forbidden"))
    elif not stat.S_ISDIR(bundle_stat.st_mode):
        blockers.append(_block("bundle_not_directory"))
    elif stat.S_IMODE(bundle_stat.st_mode) != _EXPECTED_DIRECTORY_MODE:
        blockers.append(
            _block(
                "unsafe_directory_mode",
                path=".",
                expected=_mode_string(_EXPECTED_DIRECTORY_MODE),
                actual=_mode_string(bundle_stat.st_mode),
            )
        )

    if (
        bundle_stat is not None
        and stat.S_ISDIR(bundle_stat.st_mode)
        and not stat.S_ISLNK(bundle_stat.st_mode)
    ):
        blockers.extend(_path_component_blockers(bundle, "tour.json"))
        if not any(
            row["code"] in {"asset_missing", "symlink_forbidden", "asset_type_invalid"}
            and row.get("path") == "tour.json"
            for row in blockers
        ):
            try:
                tour_bytes = _read_bundle_file_no_follow(
                    bundle,
                    "tour.json",
                    max_bytes=_MAX_TOUR_JSON_BYTES,
                )
                decoded = json.loads(tour_bytes.decode("utf-8"))
                if not isinstance(decoded, dict):
                    blockers.append(_block("tour_json_not_object"))
                else:
                    payload = decoded
            except UnicodeDecodeError:
                blockers.append(_block("tour_json_encoding_invalid"))
            except json.JSONDecodeError:
                blockers.append(_block("tour_json_invalid"))
            except OSError:
                blockers.append(_block("tour_json_read_failed"))

    if payload:
        release = evaluate_public_tour_generated_viewer_release(payload)
        policy_released = bool(release.get("released"))
        if not policy_released:
            blockers.append(
                _block(
                    "release_policy_blocked",
                    reason=str(release.get("reason") or "unknown"),
                )
            )

    manifest_slug = str(payload.get("slug") or "").strip()
    selected_slug = str(slug or manifest_slug or bundle.name).strip()
    if not _SLUG_RE.fullmatch(selected_slug) or selected_slug in {".", ".."}:
        blockers.append(_block("slug_invalid"))
    if slug and manifest_slug and selected_slug != manifest_slug:
        blockers.append(
            _block("slug_mismatch", expected=manifest_slug, actual=selected_slug)
        )

    release_revision = str(release.get("release_revision") or "").strip()
    disclosure = str(release.get("disclosure") or "").strip()
    raw_release = payload.get("generated_viewer_release")
    raw_generated = payload.get("generated_reconstruction")
    release_payload = dict(raw_release) if isinstance(raw_release, dict) else {}
    generated_payload = dict(raw_generated) if isinstance(raw_generated, dict) else {}
    if policy_released:
        if (
            not _REVISION_RE.fullmatch(release_revision)
            or release_revision
            != str(release_payload.get("release_revision") or "").strip()
        ):
            blockers.append(_block("release_revision_invalid"))
        disclosure_lower = disclosure.lower()
        if (
            not disclosure
            or len(disclosure) > 1000
            or any(
                ord(character) < 32 and character not in {"\t"}
                for character in disclosure
            )
            or disclosure != str(release_payload.get("disclosure") or "").strip()
            or not any(
                word in disclosure_lower for word in ("generated", "reconstruction")
            )
            or "not" not in disclosure_lower
            or not any(word in disclosure_lower for word in ("captured", "provider"))
        ):
            blockers.append(_block("release_disclosure_invalid"))

        raw_bindings = release_payload.get("asset_bindings")
        bindings = {
            str(path): dict(binding)
            for path, binding in dict(release.get("bindings") or {}).items()
            if isinstance(binding, dict)
        }
        if (
            not isinstance(raw_bindings, list)
            or len(raw_bindings) != len(bindings)
            or any(
                not isinstance(row, dict)
                or _safe_relpath(row.get("path")) not in bindings
                for row in (raw_bindings if isinstance(raw_bindings, list) else [])
            )
        ):
            blockers.append(_block("asset_bindings_invalid"))

        viewer_relpath = _safe_relpath(release.get("viewer_relpath"))
        reconstruction_manifest_relpath = _safe_relpath(
            generated_payload.get("manifest_relpath")
        )
        for path in sorted(bindings):
            binding = bindings[path]
            contract_blockers, serveable = _binding_contract_blockers(
                binding=binding,
                viewer_relpath=viewer_relpath,
                reconstruction_manifest_relpath=reconstruction_manifest_relpath,
            )
            blockers.extend(contract_blockers)
            if serveable:
                serveable_paths.append(path)
            elif (
                str(binding.get("role") or "").strip().lower()
                == "reconstruction_manifest"
            ):
                proof_only_paths.append(path)

            path_blockers = _path_component_blockers(bundle, path)
            blockers.extend(path_blockers)
            path_has_fatal_blocker = any(
                (
                    row.get("path") == path
                    or path.startswith(f"{str(row.get('path') or '')}/")
                )
                and row["code"]
                in {
                    "asset_missing",
                    "symlink_forbidden",
                    "asset_type_invalid",
                    "directory_type_invalid",
                }
                for row in path_blockers
            )
            if path_has_fatal_blocker:
                continue
            try:
                content = _read_bundle_file_no_follow(bundle, path)
            except OSError:
                blockers.append(_block("asset_read_failed", path=path))
                continue
            expected_size = binding.get("size_bytes")
            expected_sha256 = str(binding.get("sha256") or "").strip().lower()
            if not isinstance(expected_size, int) or len(content) != expected_size:
                blockers.append(
                    _block(
                        "asset_size_mismatch",
                        path=path,
                        expected=expected_size,
                        actual=len(content),
                    )
                )
            actual_sha256 = hashlib.sha256(content).hexdigest()
            if (
                not _SHA256_RE.fullmatch(expected_sha256)
                or actual_sha256 != expected_sha256
            ):
                blockers.append(
                    _block(
                        "asset_digest_mismatch",
                        path=path,
                        expected=expected_sha256,
                        actual=actual_sha256,
                    )
                )
            if (
                str(binding.get("role") or "").strip().lower()
                == "reconstruction_manifest"
            ):
                blockers.extend(_proof_manifest_provenance_blockers(content, path=path))

        if proof_only_paths != [reconstruction_manifest_relpath]:
            blockers.append(
                _block(
                    "proof_manifest_contract_invalid",
                    expected=reconstruction_manifest_relpath,
                    actual=",".join(proof_only_paths),
                )
            )

    normalized_base_url = ""
    if base_url:
        normalized_base_url = _normalized_base_url(base_url)
        if not normalized_base_url:
            blockers.append(_block("base_url_invalid"))
        elif policy_released and _SLUG_RE.fullmatch(selected_slug):
            for path in sorted(serveable_paths):
                binding = bindings[path]
                blockers.extend(
                    _http_binding_blockers(
                        base_url=normalized_base_url,
                        slug=selected_slug,
                        path=path,
                        binding=binding,
                        release_revision=release_revision,
                    )
                )

    blockers = _deduplicated_sorted(blockers)
    passed = not blockers
    return {
        "status": "pass" if passed else "blocked",
        "pass": passed,
        "blockers": blockers,
        "bundle_dir": str(bundle),
        "slug": selected_slug,
        "checks": {
            "policy_released": policy_released,
            "binding_count": len(bindings),
            "serveable_binding_count": len(serveable_paths),
            "proof_only_binding_count": len(proof_only_paths),
            "http_verified": bool(
                normalized_base_url and policy_released and serveable_paths
            ),
        },
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify a generated public-tour viewer release without modifying it."
    )
    parser.add_argument(
        "--bundle-dir", required=True, help="Path to the public tour bundle directory."
    )
    parser.add_argument(
        "--base-url", default="", help="Optional EA origin to verify with GET and HEAD."
    )
    parser.add_argument(
        "--slug", default="", help="Optional explicit public route slug."
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        receipt = verify_bundle(args.bundle_dir, base_url=args.base_url, slug=args.slug)
    except Exception as exc:  # pragma: no cover - final fail-closed CLI guard
        receipt = {
            "status": "blocked",
            "pass": False,
            "blockers": [_block("verification_error", error_type=type(exc).__name__)],
            "bundle_dir": str(
                Path(os.path.abspath(os.path.expanduser(args.bundle_dir)))
            ),
            "slug": str(args.slug or ""),
            "checks": {
                "policy_released": False,
                "binding_count": 0,
                "serveable_binding_count": 0,
                "proof_only_binding_count": 0,
                "http_verified": False,
            },
        }
    print(json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=True))
    return 0 if receipt["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
