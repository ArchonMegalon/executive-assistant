#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import urllib.parse
from collections.abc import Mapping
from datetime import datetime
from typing import Any


CONTRACT_NAME = "ea.memorial_spatial_tour_public_origin.v1"
GENERATED_BY = "scripts/materialize_memorial_spatial_tour_public_origin.py"
SOURCE_STATE_FINGERPRINT_SEMANTICS = (
    "worktree_source_files_sha256_excluding_generated_only_paths"
)
PROPERTY_AUTHORITY_SCHEMA = (
    "propertyquarry.generated-viewer-publication-authority.v1"
)
PROPERTY_PACKAGE_SCHEMA = "propertyquarry.public-tour-generated-viewer-package.v1"
PROPERTY_AUTHORITY_OWNER = "PropertyQuarry"
PROPERTY_REPOSITORY = "ArchonMegalon/property"
PROPERTY_TOUR_SLUG = (
    "360-tour-balkon-wohnung-in-neustift-layout-first-0146e6f9c6"
)
PROPERTY_ARTIFACT_COMMIT = "dd81d16421339d1ac4ca9f01d65f5ebcf607258f"
PROPERTY_PACKAGER_COMMIT = "b5eb627267dadb8dd5115dde7643cd8bdbad3317"
PROPERTY_FINAL_REVIEW_SHA256 = (
    "08b79e6b69cdb6559339919bd9c9f414aa11cf747848e6a98565e3b59cef0c8d"
)
PROPERTY_BROWSER_REVIEW_SHA256 = (
    "866bc0c59952d1000a34d0685d31b539cde96beea3ab6598604f371e47c894c3"
)
PROPERTY_AUTHORITY_SHA256 = (
    "d4c45dcf5e9d09eb092934e3b2b586a8dda14ab5e320e0ae19b62c1ed2e4d9f1"
)
PROPERTY_TOUR_SHA256 = (
    "c5aa916d54bd7c549042c4e856c411a4a0f9f573e0354f6c27e555145489642c"
)
PROPERTY_PRE_AUTHORITY_SHA256 = (
    "0e35c90d5f7c66324e386a1e92643d5c3c07c668bcd35f984d297e4825568da0"
)
CANDIDATE_BROWSER_SCHEMA = "ea.manfred_spatial_candidate_browser.v5"
DEPLOY_RECEIPT_CONTRACT = "ea.memorial_scoped_deploy_receipt.v1"
JOINT_DEPLOY_RECEIPT_CONTRACT = "ea.memorial_joint_api_ingress_deploy.v1"
DEPLOY_RECEIPT_CONTRACTS = {
    DEPLOY_RECEIPT_CONTRACT,
    JOINT_DEPLOY_RECEIPT_CONTRACT,
}
VIEWER_RELPATH = "generated-reconstruction/viewer.html"
PROOF_RELPATH = "generated-reconstruction/reconstruction.json"
FLOORPLAN_RELPATH = "generated-reconstruction/source-floorplan.png"
THREE_RELPATH = "generated-reconstruction/vendor/three.module.js"
ORBIT_RELPATH = (
    "generated-reconstruction/vendor/examples/jsm/controls/OrbitControls.js"
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_DEPLOYMENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
_RESERVED_HOST_SUFFIXES = frozenset(
    {
        "alt",
        "arpa",
        "example",
        "example.com",
        "example.net",
        "example.org",
        "home.arpa",
        "internal",
        "invalid",
        "lan",
        "local",
        "localdomain",
        "localhost",
        "onion",
        "test",
    }
)
_TOP_LEVEL_KEYS = {
    "candidate_browser",
    "checks",
    "contract_name",
    "deploy_binding",
    "external_requests",
    "failed_codes",
    "generated_at",
    "generated_by",
    "gold_claim_allowed",
    "head_semantics",
    "package_binding",
    "provider_calls_performed",
    "public_base_url",
    "public_spatial_tour",
    "publication_authority",
    "runtime_revision",
    "slug",
    "source_git_head",
    "source_state_fingerprint",
    "source_state_fingerprint_semantics",
    "source_worktree_dirty",
    "status",
    "tour_slug",
}
_AUTHORITY_KEYS = {
    "artifact_commit",
    "browser_review_receipt_sha256",
    "ea_public_activation_authority",
    "final_review_receipt_sha256",
    "owner",
    "packager_commit",
    "pre_authority_manifest_canonical_sha256",
    "publication_authority_sha256",
    "repository",
    "schema",
    "status",
    "tour_manifest_sha256",
    "upstream_public_activation_authority",
}
_PACKAGE_KEYS = {
    "file_count",
    "files",
    "package_sha256",
    "pre_authority_manifest_canonical_sha256",
    "proof_relpath",
    "release_revision",
    "schema",
    "slug",
    "status",
    "tour_manifest_canonical_sha256",
    "tour_manifest_sha256",
    "viewer_relpath",
}
_BROWSER_KEYS = {
    "candidate_commit",
    "candidate_origin",
    "external_request_count",
    "interactive_surfaces",
    "landing_surface_count",
    "nested_viewer_ready_verified",
    "oci_image_revision",
    "package_sha256",
    "receipt_sha256",
    "release_revision",
    "responsive_iframe_verified",
    "route_stop_count",
    "schema",
    "status",
    "surface_count",
    "webgl_fallback",
}
_PUBLIC_SPATIAL_KEYS = {
    "canonical_json_file_count",
    "exact_byte_file_count",
    "external_request_count",
    "get_count",
    "head_count",
    "origin",
    "proof_only_404",
    "property_authority",
    "provider_calls_performed",
    "redirect_count",
    "request_count",
    "routes",
    "slug",
    "source_revision",
    "status",
}
_DEPLOY_BINDING_KEYS = {
    "candidate_promotion_evidence_sha256",
    "contract_name",
    "deployment_id",
    "public_origin",
    "public_spatial_tour_sha256",
    "receipt_sha256",
    "source_revision",
    "status",
}
_CHECK_KEYS = {
    "candidate_browser",
    "deploy_binding",
    "package_binding",
    "provider_boundary",
    "public_spatial_tour",
    "publication_authority",
    "source_state",
}
_FILE_SPECS = {
    "tour.json": ("tour_manifest", "application/json"),
    VIEWER_RELPATH: ("viewer_document", "text/html"),
    PROOF_RELPATH: ("reconstruction_manifest", "application/json"),
    FLOORPLAN_RELPATH: ("floorplan_texture", "image/png"),
    THREE_RELPATH: ("viewer_module", "text/javascript"),
    ORBIT_RELPATH: ("viewer_module", "text/javascript"),
}
_ROUTE_LABELS = (
    "version_get",
    "version_head",
    "landing_get",
    "landing_head",
    "tour_json_get",
    "tour_json_head",
    "viewer_get",
    "viewer_head",
    "floorplan_get",
    "floorplan_head",
    "three_module_get",
    "three_module_head",
    "orbit_controls_get",
    "orbit_controls_head",
    "proof_only_get",
    "proof_only_head",
)
_EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


def canonical_json_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _exact_int(value: object, expected: int | None = None) -> bool:
    return type(value) is int and (expected is None or value == expected)


def _sha256(value: object) -> bool:
    return type(value) is str and _SHA256_RE.fullmatch(value) is not None


def _commit(value: object) -> bool:
    return type(value) is str and _COMMIT_RE.fullmatch(value) is not None


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _public_https_origin(value: object) -> str:
    if not isinstance(value, str) or value != value.strip():
        return ""
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except (TypeError, ValueError):
        return ""
    hostname = str(parsed.hostname or "").rstrip(".").lower()
    if (
        parsed.scheme != "https"
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
        or port not in {None, 443}
        or any(
            hostname == suffix or hostname.endswith(f".{suffix}")
            for suffix in _RESERVED_HOST_SUFFIXES
        )
    ):
        return ""
    try:
        if not ipaddress.ip_address(hostname).is_global:
            return ""
    except ValueError:
        if "." not in hostname:
            return ""
    rendered_host = f"[{hostname}]" if ":" in hostname else hostname
    return f"https://{rendered_host}"


def _timestamp(value: object) -> bool:
    if not isinstance(value, str) or not value.endswith("Z"):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _contains_private_host_path(value: object) -> bool:
    if isinstance(value, Mapping):
        return any(_contains_private_host_path(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_private_host_path(item) for item in value)
    if not isinstance(value, str):
        return False
    lowered = value.strip().replace("\\", "/").lower()
    return (
        lowered.startswith(("/home/", "/tmp/", "/var/tmp/", "file://", "pcloud://"))
        or "/home/" in lowered
        or "/tmp/" in lowered
        or "/var/tmp/" in lowered
    )


def _package_files_issues(package: dict[str, Any]) -> tuple[list[str], dict[str, dict[str, Any]]]:
    issues: list[str] = []
    raw_files = package.get("files")
    if not isinstance(raw_files, list) or len(raw_files) != len(_FILE_SPECS):
        return ["spatial_package_files_invalid"], {}
    rows: dict[str, dict[str, Any]] = {}
    for raw_row in raw_files:
        if not isinstance(raw_row, Mapping):
            issues.append("spatial_package_file_row_invalid")
            continue
        row = dict(raw_row)
        path = row.get("path")
        if (
            set(row) != {"mime_type", "path", "role", "sha256", "size_bytes"}
            or not isinstance(path, str)
            or path not in _FILE_SPECS
            or path in rows
            or (row.get("role"), row.get("mime_type")) != _FILE_SPECS.get(path)
            or not _sha256(row.get("sha256"))
            or not _exact_int(row.get("size_bytes"))
            or int(row.get("size_bytes") or 0) <= 0
        ):
            issues.append("spatial_package_file_row_invalid")
            continue
        rows[path] = row
    if set(rows) != set(_FILE_SPECS):
        issues.append("spatial_package_file_set_invalid")
        return issues, rows
    if [str(row.get("path")) for row in raw_files if isinstance(row, Mapping)] != sorted(
        _FILE_SPECS
    ):
        issues.append("spatial_package_files_not_canonical")
    digest_rows = [
        {
            "path": path,
            "sha256": str(rows[path]["sha256"]),
            "size_bytes": int(rows[path]["size_bytes"]),
        }
        for path in sorted(rows)
    ]
    if canonical_json_sha256(digest_rows) != package.get("package_sha256"):
        issues.append("spatial_package_digest_mismatch")
    return issues, rows


def _browser_issues(
    browser: dict[str, Any],
    *,
    runtime_revision: str,
    package: dict[str, Any],
) -> list[str]:
    issues: list[str] = []
    if set(browser) != _BROWSER_KEYS:
        issues.append("spatial_candidate_browser_schema_invalid")
        return issues
    if (
        browser.get("schema") != CANDIDATE_BROWSER_SCHEMA
        or browser.get("status") != "pass"
        or not _sha256(browser.get("receipt_sha256"))
        or browser.get("candidate_commit") != runtime_revision
        or browser.get("oci_image_revision") != runtime_revision
        or browser.get("package_sha256") != package.get("package_sha256")
        or browser.get("release_revision") != package.get("release_revision")
        or not _exact_int(browser.get("surface_count"), 4)
        or not _exact_int(browser.get("landing_surface_count"), 2)
        or not _exact_int(browser.get("route_stop_count"), 9)
        or browser.get("responsive_iframe_verified") is not True
        or browser.get("nested_viewer_ready_verified") is not True
        or not _exact_int(browser.get("external_request_count"), 0)
    ):
        issues.append("spatial_candidate_browser_contract_invalid")
    candidate_origin = browser.get("candidate_origin")
    try:
        parsed_candidate = urllib.parse.urlsplit(str(candidate_origin or ""))
    except ValueError:
        parsed_candidate = urllib.parse.SplitResult("", "", "", "", "")
    if (
        parsed_candidate.scheme not in {"http", "https"}
        or not parsed_candidate.hostname
        or parsed_candidate.username is not None
        or parsed_candidate.password is not None
        or parsed_candidate.path not in {"", "/"}
        or parsed_candidate.query
        or parsed_candidate.fragment
    ):
        issues.append("spatial_candidate_origin_invalid")
    surfaces = _mapping(browser.get("interactive_surfaces"))
    if set(surfaces) != {"desktop", "mobile", "reduced_motion"}:
        issues.append("spatial_candidate_interactive_surfaces_invalid")
    expected_labels: list[str] | None = None
    for name in ("desktop", "mobile", "reduced_motion"):
        surface = _mapping(surfaces.get(name))
        labels = surface.get("route_labels")
        digests = surface.get("camera_canvas_screenshot_sha256")
        if (
            set(surface)
            != {
                "camera_canvas_screenshot_sha256",
                "route_interaction_count",
                "route_labels",
            }
            or not _exact_int(surface.get("route_interaction_count"), 9)
            or not isinstance(labels, list)
            or len(labels) != 9
            or any(not isinstance(label, str) or not label.strip() for label in labels)
            or len(set(labels)) != 9
            or not isinstance(digests, list)
            or len(digests) != 9
            or any(not _sha256(digest) for digest in digests)
            or len(set(digests)) != 9
        ):
            issues.append(f"spatial_candidate_{name}_interactions_invalid")
        elif expected_labels is None:
            expected_labels = list(labels)
        elif labels != expected_labels:
            issues.append("spatial_candidate_route_labels_mismatch")
    fallback = _mapping(browser.get("webgl_fallback"))
    if (
        set(fallback)
        != {"enabled_button_count", "enabled_route_button_count", "fallback_visible"}
        or fallback.get("fallback_visible") is not True
        or not _exact_int(fallback.get("enabled_route_button_count"), 0)
        or not _exact_int(fallback.get("enabled_button_count"), 0)
    ):
        issues.append("spatial_candidate_webgl_fallback_invalid")
    return issues


def _public_spatial_issues(
    spatial: dict[str, Any],
    *,
    origin: str,
    runtime_revision: str,
    package: dict[str, Any],
    package_files: dict[str, dict[str, Any]],
) -> list[str]:
    issues: list[str] = []
    if set(spatial) != _PUBLIC_SPATIAL_KEYS:
        issues.append("public_spatial_tour_schema_invalid")
        return issues
    if (
        spatial.get("status") != "pass"
        or spatial.get("origin") != origin
        or spatial.get("slug") != PROPERTY_TOUR_SLUG
        or spatial.get("source_revision") != runtime_revision
        or not _exact_int(spatial.get("request_count"), 16)
        or not _exact_int(spatial.get("get_count"), 8)
        or not _exact_int(spatial.get("head_count"), 8)
        or not _exact_int(spatial.get("exact_byte_file_count"), 4)
        or not _exact_int(spatial.get("canonical_json_file_count"), 1)
        or spatial.get("proof_only_404") is not True
        or not _exact_int(spatial.get("redirect_count"), 0)
        or not _exact_int(spatial.get("external_request_count"), 0)
        or spatial.get("provider_calls_performed") is not False
    ):
        issues.append("public_spatial_tour_contract_invalid")
    property_authority = _mapping(spatial.get("property_authority"))
    if (
        set(property_authority)
        != {
            "artifact_commit",
            "ea_public_activation_authority",
            "owner",
            "package_sha256",
            "publication_authority_sha256",
            "upstream_public_activation_authority",
        }
        or property_authority.get("owner") != PROPERTY_AUTHORITY_OWNER
        or property_authority.get("artifact_commit") != PROPERTY_ARTIFACT_COMMIT
        or property_authority.get("publication_authority_sha256")
        != PROPERTY_AUTHORITY_SHA256
        or property_authority.get("package_sha256") != package.get("package_sha256")
        or property_authority.get("upstream_public_activation_authority") is not True
        or property_authority.get("ea_public_activation_authority") is not False
    ):
        issues.append("public_spatial_tour_authority_invalid")
    quoted_slug = urllib.parse.quote(PROPERTY_TOUR_SLUG, safe="")
    viewer_root = f"/tours/viewer/{quoted_slug}"
    route_specs = {
        "version": ("/version", 200, "application/json", None),
        "landing": (f"/tours/{quoted_slug}", 200, "text/html", None),
        "tour_json": (
            f"/tours/{quoted_slug}.json",
            200,
            "application/json",
            "tour.json",
        ),
        "viewer": (
            f"{viewer_root}/{VIEWER_RELPATH}",
            200,
            "text/html",
            VIEWER_RELPATH,
        ),
        "floorplan": (
            f"{viewer_root}/{FLOORPLAN_RELPATH}",
            200,
            "image/png",
            FLOORPLAN_RELPATH,
        ),
        "three_module": (
            f"{viewer_root}/{THREE_RELPATH}",
            200,
            "javascript",
            THREE_RELPATH,
        ),
        "orbit_controls": (
            f"{viewer_root}/{ORBIT_RELPATH}",
            200,
            "javascript",
            ORBIT_RELPATH,
        ),
        "proof_only": (
            f"{viewer_root}/{PROOF_RELPATH}",
            404,
            "application/json",
            PROOF_RELPATH,
        ),
    }
    routes = _mapping(spatial.get("routes"))
    if set(routes) != set(_ROUTE_LABELS):
        issues.append("public_spatial_tour_routes_invalid")
        return issues
    for route_label in _ROUTE_LABELS:
        label, method_lower = route_label.rsplit("_", 1)
        method = method_lower.upper()
        expected_path, expected_status, expected_media, relpath = route_specs[label]
        row = _mapping(routes.get(route_label))
        expected_keys = {
            "body_bytes",
            "body_sha256",
            "content_type",
            "method",
            "path",
            "source_revision",
            "status",
        }
        if route_label == "version_get":
            expected_keys.add("commit_sha")
        elif route_label == "tour_json_get":
            expected_keys.add("canonical_json_sha256")
        elif method == "GET" and label in {
            "viewer",
            "floorplan",
            "three_module",
            "orbit_controls",
        }:
            expected_keys.add("candidate_file_identity_verified")
        elif route_label == "proof_only_get":
            expected_keys.add("candidate_file_not_disclosed")
        content_type = str(row.get("content_type") or "").partition(";")[0].strip().lower()
        media_ok = (
            content_type in {"application/javascript", "text/javascript"}
            if expected_media == "javascript"
            else content_type == expected_media
        )
        if (
            set(row) != expected_keys
            or row.get("path") != expected_path
            or row.get("method") != method
            or not _exact_int(row.get("status"), expected_status)
            or not media_ok
            or row.get("source_revision") != runtime_revision
            or not _exact_int(row.get("body_bytes"))
            or int(row.get("body_bytes") or 0) < 0
            or not _sha256(row.get("body_sha256"))
        ):
            issues.append(f"public_spatial_tour_route_invalid:{route_label}")
            continue
        if method == "HEAD":
            if row.get("body_bytes") != 0 or row.get("body_sha256") != _EMPTY_SHA256:
                issues.append(f"public_spatial_tour_head_body_invalid:{route_label}")
            continue
        if label not in {"proof_only"} and int(row.get("body_bytes") or 0) <= 0:
            issues.append(f"public_spatial_tour_get_body_invalid:{route_label}")
        if label == "version" and row.get("commit_sha") != runtime_revision:
            issues.append("public_spatial_tour_version_binding_invalid")
        elif label == "tour_json":
            if row.get("canonical_json_sha256") != package.get(
                "tour_manifest_canonical_sha256"
            ):
                issues.append("public_spatial_tour_json_binding_invalid")
        elif label in {"viewer", "floorplan", "three_module", "orbit_controls"}:
            file_row = package_files.get(str(relpath), {})
            if (
                row.get("candidate_file_identity_verified") is not True
                or row.get("body_sha256") != file_row.get("sha256")
                or row.get("body_bytes") != file_row.get("size_bytes")
            ):
                issues.append(f"public_spatial_tour_byte_binding_invalid:{route_label}")
        elif label == "proof_only":
            proof_file = package_files.get(PROOF_RELPATH, {})
            if (
                row.get("candidate_file_not_disclosed") is not True
                or row.get("body_sha256") == proof_file.get("sha256")
            ):
                issues.append("public_spatial_tour_proof_disclosure_invalid")
    return issues


def validate_memorial_spatial_public_origin_receipt(
    receipt: object,
    *,
    current_head: str,
    current_fingerprint: str,
) -> list[str]:
    if not isinstance(receipt, Mapping) or not receipt:
        return ["spatial_public_origin_receipt_missing_or_invalid"]
    payload = dict(receipt)
    issues: list[str] = []
    if set(payload) != _TOP_LEVEL_KEYS:
        issues.append("spatial_public_origin_schema_invalid")
    if payload.get("contract_name") != CONTRACT_NAME:
        issues.append("spatial_public_origin_contract_invalid")
    if payload.get("status") != "pass":
        issues.append("spatial_public_origin_status_not_pass")
    if not _timestamp(payload.get("generated_at")):
        issues.append("spatial_public_origin_generated_at_invalid")
    if payload.get("generated_by") != GENERATED_BY:
        issues.append("spatial_public_origin_generator_invalid")
    if (
        not _commit(current_head)
        or payload.get("source_git_head") != current_head
        or payload.get("head_semantics") != "source_state"
    ):
        issues.append("spatial_public_origin_source_head_mismatch")
    if (
        not _sha256(current_fingerprint)
        or payload.get("source_state_fingerprint") != current_fingerprint
        or payload.get("source_state_fingerprint_semantics")
        != SOURCE_STATE_FINGERPRINT_SEMANTICS
    ):
        issues.append("spatial_public_origin_source_fingerprint_mismatch")
    if payload.get("source_worktree_dirty") is not False:
        issues.append("spatial_public_origin_source_worktree_dirty")
    origin = _public_https_origin(payload.get("public_base_url"))
    if not origin or payload.get("public_base_url") != origin:
        issues.append("spatial_public_origin_https_origin_invalid")
    runtime_revision = str(payload.get("runtime_revision") or "")
    if runtime_revision != current_head:
        issues.append("spatial_public_origin_runtime_revision_mismatch")
    if payload.get("slug") != "manfred" or payload.get("tour_slug") != PROPERTY_TOUR_SLUG:
        issues.append("spatial_public_origin_slug_invalid")
    if payload.get("provider_calls_performed") is not False or not _exact_int(
        payload.get("external_requests"), 0
    ):
        issues.append("spatial_public_origin_provider_boundary_invalid")
    if payload.get("failed_codes") != [] or payload.get("gold_claim_allowed") is not True:
        issues.append("spatial_public_origin_gold_claim_invalid")
    checks = _mapping(payload.get("checks"))
    if set(checks) != _CHECK_KEYS or any(checks.get(key) != "pass" for key in _CHECK_KEYS):
        issues.append("spatial_public_origin_checks_invalid")

    authority = _mapping(payload.get("publication_authority"))
    if (
        set(authority) != _AUTHORITY_KEYS
        or authority.get("schema") != PROPERTY_AUTHORITY_SCHEMA
        or authority.get("status") != "pass"
        or authority.get("owner") != PROPERTY_AUTHORITY_OWNER
        or authority.get("repository") != PROPERTY_REPOSITORY
        or authority.get("artifact_commit") != PROPERTY_ARTIFACT_COMMIT
        or authority.get("packager_commit") != PROPERTY_PACKAGER_COMMIT
        or authority.get("final_review_receipt_sha256")
        != PROPERTY_FINAL_REVIEW_SHA256
        or authority.get("browser_review_receipt_sha256")
        != PROPERTY_BROWSER_REVIEW_SHA256
        or authority.get("publication_authority_sha256")
        != PROPERTY_AUTHORITY_SHA256
        or authority.get("tour_manifest_sha256") != PROPERTY_TOUR_SHA256
        or authority.get("pre_authority_manifest_canonical_sha256")
        != PROPERTY_PRE_AUTHORITY_SHA256
        or authority.get("upstream_public_activation_authority") is not True
        or authority.get("ea_public_activation_authority") is not False
    ):
        issues.append("spatial_public_origin_authority_invalid")

    package = _mapping(payload.get("package_binding"))
    if (
        set(package) != _PACKAGE_KEYS
        or package.get("schema") != PROPERTY_PACKAGE_SCHEMA
        or package.get("status") != "pass"
        or package.get("slug") != PROPERTY_TOUR_SLUG
        or not isinstance(package.get("release_revision"), str)
        or not str(package.get("release_revision") or "").strip()
        or not _sha256(package.get("package_sha256"))
        or not _exact_int(package.get("file_count"), 6)
        or package.get("viewer_relpath") != VIEWER_RELPATH
        or package.get("proof_relpath") != PROOF_RELPATH
        or package.get("tour_manifest_sha256") != PROPERTY_TOUR_SHA256
        or not _sha256(package.get("tour_manifest_canonical_sha256"))
        or package.get("pre_authority_manifest_canonical_sha256")
        != PROPERTY_PRE_AUTHORITY_SHA256
    ):
        issues.append("spatial_public_origin_package_invalid")
    file_issues, package_files = _package_files_issues(package)
    issues.extend(file_issues)
    if package_files.get("tour.json", {}).get("sha256") != PROPERTY_TOUR_SHA256:
        issues.append("spatial_public_origin_tour_manifest_mismatch")

    browser = _mapping(payload.get("candidate_browser"))
    issues.extend(
        _browser_issues(
            browser,
            runtime_revision=runtime_revision,
            package=package,
        )
    )
    spatial = _mapping(payload.get("public_spatial_tour"))
    issues.extend(
        _public_spatial_issues(
            spatial,
            origin=origin,
            runtime_revision=runtime_revision,
            package=package,
            package_files=package_files,
        )
    )
    deploy = _mapping(payload.get("deploy_binding"))
    deployment_id = deploy.get("deployment_id")
    if (
        set(deploy) != _DEPLOY_BINDING_KEYS
        or deploy.get("contract_name") not in DEPLOY_RECEIPT_CONTRACTS
        or deploy.get("status") != "pass"
        or not isinstance(deployment_id, str)
        or _DEPLOYMENT_ID_RE.fullmatch(deployment_id) is None
        or deployment_id.lower().startswith("local-")
        or not _sha256(deploy.get("receipt_sha256"))
        or deploy.get("source_revision") != runtime_revision
        or deploy.get("public_origin") != origin
        or not _sha256(deploy.get("candidate_promotion_evidence_sha256"))
        or deploy.get("public_spatial_tour_sha256")
        != canonical_json_sha256(spatial)
    ):
        issues.append("spatial_public_origin_deploy_binding_invalid")
    if _contains_private_host_path(payload):
        issues.append("spatial_public_origin_private_host_path_forbidden")
    return list(dict.fromkeys(issues))


__all__ = [
    "CONTRACT_NAME",
    "SOURCE_STATE_FINGERPRINT_SEMANTICS",
    "canonical_json_sha256",
    "validate_memorial_spatial_public_origin_receipt",
]
