from __future__ import annotations

import hashlib
import re
import urllib.parse
from typing import Any


PUBLIC_TOUR_VIDEO_RELEASE_CONTRACT = "ea.public-tour-video-release.v1"
PUBLIC_TOUR_EMBED_RELEASE_CONTRACT = "ea.public-tour-embed-release.v1"
PUBLIC_TOUR_GENERATED_VIEWER_RELEASE_CONTRACT = (
    "ea.public-tour-generated-viewer-release.v1"
)
GENERATED_RECONSTRUCTION_PROVIDER = "propertyquarry_generated_reconstruction"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_EMBED_PROVIDER_HOST_SUFFIXES = {
    "3dvista": ("3dvista.com",),
    "feelestate": ("feelestate.com", "360.kalandra.at"),
    "matterport": ("matterport.com",),
}


def _text(value: object) -> str:
    return str(value or "").strip()


def _normalized_provider(value: object) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", _text(value).lower()).strip("_")


def _safe_relpath(value: object) -> str:
    raw = _text(value).replace("\\", "/")
    if (
        not raw
        or raw.startswith("/")
        or "://" in raw
        or "\x00" in raw
        or any(character in raw for character in "\"'`<>&")
    ):
        return ""
    parts = raw.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        return ""
    return "/".join(parts)


def safe_public_navigation_url(value: object, *, production: bool) -> str:
    normalized = _text(value)
    if not normalized or any(character in normalized for character in "\x00\r\n\"'`<>"):
        return ""
    if normalized.startswith("/") and not normalized.startswith("//"):
        return normalized
    parsed = urllib.parse.urlparse(normalized)
    if parsed.username or parsed.password or not parsed.hostname:
        return ""
    try:
        port = parsed.port
    except ValueError:
        return ""
    scheme = parsed.scheme.lower()
    if scheme == "https":
        if port not in {None, 443}:
            return ""
        return normalized
    if not production and scheme == "http" and port in {None, 80, 8090, 8097, 18097}:
        return normalized
    return ""


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _origin(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        return ""
    try:
        port = parsed.port
    except ValueError:
        return ""
    if port not in {None, 443}:
        return ""
    return f"https://{parsed.hostname.lower().rstrip('.')}"


def _hostname_matches(hostname: str, suffix: str) -> bool:
    normalized = hostname.lower().rstrip(".")
    expected = suffix.lower().rstrip(".")
    return normalized == expected or normalized.endswith(f".{expected}")


def evaluate_public_tour_embed_release(payload: dict[str, object]) -> dict[str, object]:
    if _text(payload.get("scene_strategy")).lower() == "pure_360_cube":
        return {
            "released": False,
            "reason": "hosted_cube_does_not_require_external_embed",
            "url": "",
            "origin": "",
        }
    url = _text(
        payload.get("source_virtual_tour_url")
        or payload.get("source_virtual_tour_origin")
    )
    origin = _origin(url)
    release = payload.get("external_embed_release")
    if not isinstance(release, dict):
        return {
            "released": False,
            "reason": "embed_release_missing",
            "url": "",
            "origin": "",
        }
    if bool(release.get("revoked")):
        return {
            "released": False,
            "reason": "embed_revoked",
            "url": "",
            "origin": "",
            "terminal": True,
        }
    if bool(release.get("disqualified")):
        return {
            "released": False,
            "reason": "embed_disqualified",
            "url": "",
            "origin": "",
            "terminal": True,
        }
    provider = _normalized_provider(release.get("provider"))
    hostname = urllib.parse.urlparse(url).hostname or ""
    required_suffixes = _EMBED_PROVIDER_HOST_SUFFIXES.get(provider, ())
    checks = (
        release.get("contract") == PUBLIC_TOUR_EMBED_RELEASE_CONTRACT,
        _text(release.get("status")).lower() == "ready",
        bool(url and origin),
        bool(
            required_suffixes
            and any(_hostname_matches(hostname, suffix) for suffix in required_suffixes)
        ),
        _text(release.get("final_origin")).lower().rstrip("/") == origin,
        _text(release.get("source_url_sha256")).lower() == _sha256(url),
        bool(_SHA256_RE.fullmatch(_text(release.get("review_receipt_sha256")).lower())),
        release.get("final_origin_verified") is True,
    )
    if not all(checks):
        return {
            "released": False,
            "reason": "embed_release_unverified",
            "url": "",
            "origin": "",
        }
    return {
        "released": True,
        "reason": "embed_release_verified",
        "url": url,
        "origin": origin,
        "provider": provider,
    }


def _verified_video_release_fields(
    release: dict[str, object],
    *,
    relpath: str,
    provider: str,
) -> dict[str, object] | None:
    expected_sha256 = _text(release.get("asset_sha256")).lower()
    expected_size = release.get("asset_size_bytes")
    disclosure = _text(release.get("disclosure"))
    checks = (
        release.get("contract") == PUBLIC_TOUR_VIDEO_RELEASE_CONTRACT,
        _text(release.get("status")).lower() == "ready",
        _normalized_provider(release.get("provider")) == provider,
        _safe_relpath(release.get("asset_relpath")) == relpath,
        bool(_SHA256_RE.fullmatch(expected_sha256)),
        isinstance(expected_size, int) and expected_size > 0,
        bool(_SHA256_RE.fullmatch(_text(release.get("review_receipt_sha256")).lower())),
        bool(
            _SHA256_RE.fullmatch(
                _text(release.get("publication_authority_receipt_sha256")).lower()
            )
        ),
        release.get("provider_output_verified") is True,
        release.get("quality_review_passed") is True,
        release.get("publication_authority_verified") is True,
        bool(_text(release.get("release_revision"))),
        bool(disclosure),
    )
    if not all(checks):
        return None
    return {
        "expected_sha256": expected_sha256,
        "expected_size_bytes": int(expected_size),
        "disclosure": disclosure,
        "release_revision": _text(release.get("release_revision")),
    }


def _generated_reconstruction_video_release(
    payload: dict[str, object],
    *,
    relpath: str,
    provider: str,
    release: dict[str, object],
) -> dict[str, object]:
    generated = payload.get("generated_reconstruction")
    if not isinstance(generated, dict):
        return {
            "released": False,
            "reason": "generated_reconstruction_metadata_missing",
            "relpath": "",
        }
    proof = generated.get("walkthrough_coverage_proof")
    if not isinstance(proof, dict):
        return {
            "released": False,
            "reason": "generated_reconstruction_coverage_missing",
            "relpath": "",
        }
    expected = [
        _text(value)
        for value in list(proof.get("segments_expected") or [])
        if _text(value)
    ]
    visited = [
        _text(value)
        for value in list(proof.get("segments_visited") or [])
        if _text(value)
    ]
    route_labels = [
        _text(value)
        for value in list(generated.get("walkthrough_route_labels") or [])
        if _text(value)
    ]
    disclosure = _text(generated.get("disclosure"))
    source_manifest_relpath = _safe_relpath(generated.get("manifest_relpath"))
    source_manifest_sha256 = _text(release.get("source_manifest_sha256")).lower()
    verified_release = _verified_video_release_fields(
        release, relpath=relpath, provider=provider
    )
    checks = (
        bool(verified_release),
        provider == GENERATED_RECONSTRUCTION_PROVIDER,
        _normalized_provider(generated.get("provider"))
        == GENERATED_RECONSTRUCTION_PROVIDER,
        generated.get("verified_provider_capture") is False,
        generated.get("satisfies_verified_tour_gate") is False,
        _safe_relpath(generated.get("walkthrough_video_relpath")) == relpath,
        _text(proof.get("status")).lower() == "pass",
        _text(proof.get("source")).lower()
        == "propertyquarry_generated_reconstruction_viewer_capture",
        bool(expected and expected == visited and expected == route_labels),
        bool(disclosure),
        bool(verified_release and verified_release.get("disclosure") == disclosure),
        release.get("synthetic") is True,
        release.get("verified_provider_capture") is False,
        release.get("satisfies_verified_tour_gate") is False,
        bool(source_manifest_relpath),
        bool(_SHA256_RE.fullmatch(source_manifest_sha256)),
        bool(
            _SHA256_RE.fullmatch(
                _text(release.get("source_provenance_receipt_sha256")).lower()
            )
        ),
        release.get("source_provenance_reviewed") is True,
    )
    if not all(checks):
        return {
            "released": False,
            "reason": "generated_reconstruction_release_unverified",
            "relpath": "",
        }
    return {
        "released": True,
        "reason": "generated_reconstruction_release_verified",
        "relpath": relpath,
        "provider": provider,
        **dict(verified_release or {}),
        "source_manifest_relpath": source_manifest_relpath,
        "source_manifest_sha256": source_manifest_sha256,
        "synthetic": True,
        "verified_provider_capture": False,
    }


def evaluate_public_tour_video_release(payload: dict[str, object]) -> dict[str, Any]:
    relpath = _safe_relpath(payload.get("video_relpath"))
    if not relpath:
        return {"released": False, "reason": "video_not_configured", "relpath": ""}
    provider = _normalized_provider(
        payload.get("video_provider")
        or payload.get("video_provider_key")
        or payload.get("video_render_provider")
        or payload.get("video_source")
    )
    release = payload.get("video_release")
    if not isinstance(release, dict):
        return {"released": False, "reason": "video_release_missing", "relpath": ""}
    if bool(release.get("revoked")):
        return {
            "released": False,
            "reason": "video_revoked",
            "relpath": "",
            "terminal": True,
        }
    if bool(release.get("disqualified")):
        return {
            "released": False,
            "reason": "video_disqualified",
            "relpath": "",
            "terminal": True,
        }
    if provider == GENERATED_RECONSTRUCTION_PROVIDER:
        return _generated_reconstruction_video_release(
            payload,
            relpath=relpath,
            provider=provider,
            release=release,
        )

    verified_release = _verified_video_release_fields(
        release, relpath=relpath, provider=provider
    )
    if not provider or verified_release is None:
        return {"released": False, "reason": "video_release_unverified", "relpath": ""}
    return {
        "released": True,
        "reason": "video_release_verified",
        "relpath": relpath,
        "provider": provider,
        **verified_release,
    }


def evaluate_public_tour_generated_viewer_release(
    payload: dict[str, object],
) -> dict[str, Any]:
    generated = payload.get("generated_reconstruction")
    release = payload.get("generated_viewer_release")
    if not isinstance(generated, dict) or not isinstance(release, dict):
        return {
            "released": False,
            "reason": "generated_viewer_release_missing",
            "viewer_relpath": "",
            "bindings": {},
        }
    if bool(release.get("revoked")):
        return {
            "released": False,
            "reason": "generated_viewer_revoked",
            "viewer_relpath": "",
            "bindings": {},
            "terminal": True,
        }
    if bool(release.get("disqualified")):
        return {
            "released": False,
            "reason": "generated_viewer_disqualified",
            "viewer_relpath": "",
            "bindings": {},
            "terminal": True,
        }

    viewer_relpath = _safe_relpath(generated.get("viewer_relpath"))
    manifest_relpath = _safe_relpath(generated.get("manifest_relpath"))
    floorplan_relpath = _safe_relpath(generated.get("floorplan_relpath"))
    raw_photo_relpaths = list(generated.get("photo_relpaths") or [])
    photo_relpaths = [_safe_relpath(value) for value in raw_photo_relpaths]
    photo_relpaths = [value for value in photo_relpaths if value]
    photo_paths_valid = len(raw_photo_relpaths) == len(photo_relpaths) and len(
        set(photo_relpaths)
    ) == len(photo_relpaths)
    photo_reference_panel_count = generated.get("photo_reference_panel_count")
    layout_only = (
        not raw_photo_relpaths
        and type(photo_reference_panel_count) is int
        and photo_reference_panel_count == 0
    )
    required_assets = [
        (viewer_relpath, "viewer_document", {"text/html"}),
        (manifest_relpath, "reconstruction_manifest", {"application/json"}),
        (
            floorplan_relpath,
            "floorplan_texture",
            {"image/jpeg", "image/png", "image/webp"},
        ),
        (
            "generated-reconstruction/vendor/three.module.js",
            "viewer_module",
            {"application/javascript", "text/javascript"},
        ),
        (
            "generated-reconstruction/vendor/examples/jsm/controls/OrbitControls.js",
            "viewer_module",
            {"application/javascript", "text/javascript"},
        ),
        *[
            (relpath, "photo_texture", {"image/jpeg", "image/png", "image/webp"})
            for relpath in photo_relpaths
        ],
    ]
    required_paths = {path for path, _role, _mime_types in required_assets if path}

    raw_bindings = release.get("asset_bindings")
    bindings: dict[str, dict[str, object]] = {}
    duplicate_binding = False
    if isinstance(raw_bindings, list):
        for row in raw_bindings:
            if not isinstance(row, dict):
                continue
            path = _safe_relpath(row.get("path"))
            sha256 = _text(row.get("sha256")).lower()
            size_bytes = row.get("size_bytes")
            mime_type = _text(row.get("mime_type")).lower()
            role = _text(row.get("role")).lower()
            if (
                path
                and _SHA256_RE.fullmatch(sha256)
                and isinstance(size_bytes, int)
                and size_bytes > 0
                and mime_type
                and role
            ):
                if path in bindings:
                    duplicate_binding = True
                bindings[path] = {
                    "path": path,
                    "sha256": sha256,
                    "size_bytes": size_bytes,
                    "mime_type": mime_type,
                    "role": role,
                }

    disclosure = _text(release.get("disclosure"))
    receipt_hash_fields = (
        "browser_receipt_sha256",
        "source_provenance_receipt_sha256",
        "publication_authority_receipt_sha256",
        "security_review_receipt_sha256",
        "accessibility_review_receipt_sha256",
    )
    checks = (
        release.get("contract") == PUBLIC_TOUR_GENERATED_VIEWER_RELEASE_CONTRACT,
        _text(release.get("status")).lower() == "ready",
        _normalized_provider(release.get("provider"))
        == GENERATED_RECONSTRUCTION_PROVIDER,
        _normalized_provider(generated.get("provider"))
        == GENERATED_RECONSTRUCTION_PROVIDER,
        generated.get("verified_provider_capture") is False,
        generated.get("satisfies_verified_tour_gate") is False,
        _text(generated.get("viewer_version")) == "propertyquarry_3d_tour_viewer_v3",
        viewer_relpath == _safe_relpath(release.get("viewer_relpath")),
        bool(
            viewer_relpath
            and manifest_relpath
            and floorplan_relpath
            and (photo_relpaths or layout_only)
        ),
        photo_paths_valid,
        len(required_paths) == len(required_assets),
        not duplicate_binding,
        set(bindings) == required_paths,
        all(
            bindings.get(path, {}).get("role") == role
            and bindings.get(path, {}).get("mime_type") in mime_types
            for path, role, mime_types in required_assets
        ),
        all(
            _SHA256_RE.fullmatch(_text(release.get(field)).lower())
            for field in receipt_hash_fields
        ),
        release.get("browser_interaction_verified") is True,
        release.get("visual_quality_review_passed") is True,
        release.get("security_review_passed") is True,
        release.get("accessibility_review_passed") is True,
        release.get("source_provenance_verified") is True,
        release.get("publication_authority_verified") is True,
        bool(_text(release.get("release_revision"))),
        bool(disclosure),
    )
    if not all(checks):
        return {
            "released": False,
            "reason": "generated_viewer_release_unverified",
            "viewer_relpath": "",
            "bindings": {},
        }
    return {
        "released": True,
        "reason": "generated_viewer_release_verified",
        "viewer_relpath": viewer_relpath,
        "bindings": bindings,
        "provider": GENERATED_RECONSTRUCTION_PROVIDER,
        "disclosure": disclosure,
        "release_revision": _text(release.get("release_revision")),
        "synthetic": True,
        "verified_provider_capture": False,
    }
