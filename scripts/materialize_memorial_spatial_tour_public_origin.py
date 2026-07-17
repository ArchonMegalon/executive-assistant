#!/usr/bin/env python3
"""Materialize sanitized public-origin proof for the governed Manfred spatial tour.

This lane performs no network, provider, Docker, or deployment action.  It only
reduces private, exact-revision deployment evidence into the tracked public gold
contract.  Missing inputs are normal before a deployment and deterministically
produce a private-mode blocked receipt with a zero exit status.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

if __package__:
    from scripts import memorial_spatial_public_origin_contract as contract
    from scripts.source_state_head import (
        resolve_source_state_head,
        resolve_source_worktree_fingerprint,
        source_worktree_metadata,
    )
    from scripts.verify_manfred_spatial_candidate_browser import (
        validate_spatial_candidate_browser_receipt,
    )
else:  # pragma: no cover - direct script execution
    import memorial_spatial_public_origin_contract as contract  # type: ignore[no-redef]
    from source_state_head import (  # type: ignore[no-redef]
        resolve_source_state_head,
        resolve_source_worktree_fingerprint,
        source_worktree_metadata,
    )
    from verify_manfred_spatial_candidate_browser import (  # type: ignore[no-redef]
        validate_spatial_candidate_browser_receipt,
    )


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = (
    ROOT
    / ".codex-studio/published/memorial_spatial_tour_public_origin.generated.json"
)
DEPLOY_RECEIPT_ENV = "EA_MEMORIAL_SPATIAL_DEPLOY_RECEIPT"
CANDIDATE_BROWSER_RECEIPT_ENV = "EA_MEMORIAL_SPATIAL_BROWSER_RECEIPT"
PUBLIC_ORIGIN_ENV = "EA_MEMORIAL_SPATIAL_PUBLIC_ORIGIN"
MAX_PRIVATE_RECEIPT_BYTES = 8 * 1024 * 1024
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
SPATIAL_PROJECTION_SCHEMA = "ea.manfred_memorial_spatial_projection.v2"
CANDIDATE_RUNTIME_SCHEMA = "ea.manfred_memorial_candidate_runtime.v4"
JOINT_DEPLOY_RECEIPT_CONTRACT = contract.JOINT_DEPLOY_RECEIPT_CONTRACT
JOINT_RECOVERY_JOURNAL_FILENAME = "joint-active-recovery.json"
JOINT_SERVICE_SCOPE = ["ea-api", "ea-redis", "ea-cloudflared"]
JOINT_ATOMICITY = {
    "api_rollback_baseline_verified": True,
    "ingress_rollback_baseline_verified": True,
    "network_rollback_baseline_captured": True,
    "public_edge_rollback_baseline_captured": True,
    "rollback_executed": False,
    "rollback_execution_status": "not_required",
    "transaction_status": "committed",
    "baseline_semantics": (
        "prechange-inputs-captured-and-rollback-renderability-validated"
    ),
}
AUTHORITY_STATUS = "authorized"
FILE_SPECS = {
    "tour.json": ("tour_manifest", "application/json"),
    contract.VIEWER_RELPATH: ("viewer_document", "text/html"),
    contract.PROOF_RELPATH: ("reconstruction_manifest", "application/json"),
    contract.FLOORPLAN_RELPATH: ("floorplan_texture", "image/png"),
    contract.THREE_RELPATH: ("viewer_module", "text/javascript"),
    contract.ORBIT_RELPATH: ("viewer_module", "text/javascript"),
}
CHECKS = {
    "candidate_browser": "pass",
    "deploy_binding": "pass",
    "package_binding": "pass",
    "provider_boundary": "pass",
    "public_spatial_tour": "pass",
    "publication_authority": "pass",
    "source_state": "pass",
}
ROUTE_LABELS = (
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


@dataclass(frozen=True)
class SourceState:
    head: str
    fingerprint: str
    dirty: bool


class EvidenceError(RuntimeError):
    """Stable fail-closed evidence error that never carries private details."""


BrowserValidator = Callable[..., dict[str, object]]


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise EvidenceError(code)


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical_receipt_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return _sha256(encoded)


def _strict_json_object(content: bytes, *, code: str) -> dict[str, Any]:
    def no_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise EvidenceError(code)
            result[key] = value
        return result

    try:
        value = json.loads(content, object_pairs_hook=no_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise EvidenceError(code) from exc
    if not isinstance(value, dict):
        raise EvidenceError(code)
    return value


def _private_json(path: Path, *, code: str) -> tuple[dict[str, Any], bytes]:
    candidate = path.expanduser()
    _require(candidate.is_absolute(), code)
    flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(candidate, flags)
    except OSError as exc:
        raise EvidenceError(code) from exc
    try:
        before = os.fstat(descriptor)
        _require(
            stat.S_ISREG(before.st_mode)
            and before.st_uid == os.geteuid()
            and before.st_nlink == 1
            and stat.S_IMODE(before.st_mode) == 0o600
            and 0 < before.st_size <= MAX_PRIVATE_RECEIPT_BYTES,
            code,
        )
        chunks: list[bytes] = []
        remaining = int(before.st_size)
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            _require(bool(chunk), code)
            chunks.append(chunk)
            remaining -= len(chunk)
        _require(not os.read(descriptor, 1), code)
        after = os.fstat(descriptor)
        _require(
            (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
            )
            == (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            ),
            code,
        )
    finally:
        os.close(descriptor)
    content = b"".join(chunks)
    return _strict_json_object(content, code=code), content


def _source_state(root: Path) -> SourceState:
    head = resolve_source_state_head(root)
    fingerprint = resolve_source_worktree_fingerprint(root)
    dirty = bool(source_worktree_metadata(root).get("source_worktree_dirty"))
    _require(COMMIT_RE.fullmatch(head) is not None, "source_state_unavailable")
    _require(SHA256_RE.fullmatch(fingerprint) is not None, "source_state_unavailable")
    return SourceState(head=head, fingerprint=fingerprint, dirty=dirty)


def _blocked(state: SourceState, *codes: str) -> dict[str, object]:
    return {
        "contract_name": contract.CONTRACT_NAME,
        "failed_codes": sorted(set(codes)) or ["spatial_public_origin_inputs_missing"],
        "generated_by": contract.GENERATED_BY,
        "gold_claim_allowed": False,
        "head_semantics": "source_state",
        "provider_calls_performed": False,
        "source_git_head": state.head,
        "source_state_fingerprint": state.fingerprint,
        "source_state_fingerprint_semantics": (
            contract.SOURCE_STATE_FINGERPRINT_SEMANTICS
        ),
        "source_worktree_dirty": state.dirty,
        "status": "blocked",
    }


def _mapping(value: object, code: str) -> dict[str, Any]:
    _require(isinstance(value, Mapping), code)
    return dict(value)


def _absolute_private_path(value: object, code: str) -> Path:
    _require(isinstance(value, str) and bool(value), code)
    path = Path(str(value))
    _require(path.is_absolute() and ".." not in path.parts, code)
    return path


def _state_directory_identity(
    path: Path,
    metadata: os.stat_result,
) -> dict[str, object]:
    return {
        "path": str(path),
        "dev": int(metadata.st_dev),
        "inode": int(metadata.st_ino),
        "uid": int(metadata.st_uid),
        "gid": int(metadata.st_gid),
        "mode": int(stat.S_IMODE(metadata.st_mode)),
        "mtime_ns": int(metadata.st_mtime_ns),
        "ctime_ns": int(metadata.st_ctime_ns),
    }


def _require_joint_cleanup_state(
    cleanup: Mapping[str, Any],
    cleanup_path: Path,
) -> None:
    code = "joint_recovery_journal_cleanup_state_invalid"
    raw_identity = cleanup.get("state_directory")
    _require(isinstance(raw_identity, Mapping), code)
    expected = dict(raw_identity)
    state_directory = cleanup_path.parent
    _require(
        cleanup_path.name == JOINT_RECOVERY_JOURNAL_FILENAME
        and state_directory.is_absolute()
        and ".." not in state_directory.parts
        and set(expected)
        == {
            "ctime_ns",
            "dev",
            "gid",
            "inode",
            "mode",
            "mtime_ns",
            "path",
            "uid",
        }
        and expected.get("path") == str(state_directory)
        and expected.get("uid") == os.geteuid()
        and expected.get("mode") == 0o700
        and all(
            type(expected.get(key)) is int and int(expected[key]) >= 0
            for key in (
                "ctime_ns",
                "dev",
                "gid",
                "inode",
                "mode",
                "mtime_ns",
                "uid",
            )
        ),
        code,
    )
    if not hasattr(os, "O_DIRECTORY") or not hasattr(os, "O_NOFOLLOW"):
        raise EvidenceError(code)
    descriptor = -1
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        path_before = state_directory.lstat()
        descriptor = os.open(state_directory, flags)
        descriptor_before = os.fstat(descriptor)
        _require(
            not stat.S_ISLNK(path_before.st_mode)
            and stat.S_ISDIR(descriptor_before.st_mode)
            and descriptor_before.st_uid == os.geteuid()
            and stat.S_IMODE(descriptor_before.st_mode) == 0o700
            and (path_before.st_dev, path_before.st_ino)
            == (descriptor_before.st_dev, descriptor_before.st_ino)
            and _state_directory_identity(
                state_directory,
                descriptor_before,
            )
            == expected,
            code,
        )
        try:
            os.stat(
                cleanup_path.name,
                dir_fd=descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            pass
        else:
            raise EvidenceError(code)
        descriptor_after = os.fstat(descriptor)
        path_after = state_directory.lstat()
        _require(
            not stat.S_ISLNK(path_after.st_mode)
            and (path_after.st_dev, path_after.st_ino)
            == (descriptor_after.st_dev, descriptor_after.st_ino)
            and _state_directory_identity(
                state_directory,
                descriptor_after,
            )
            == expected,
            code,
        )
    except EvidenceError:
        raise
    except OSError as exc:
        raise EvidenceError(code) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _deploy_contract(
    deploy: dict[str, Any],
    *,
    deploy_receipt_path: Path,
    candidate_browser_receipt_path: Path,
    candidate_browser_sha256: str,
    source_revision: str,
) -> str:
    contract_name = str(deploy.get("contract_name") or "")
    if contract_name == contract.DEPLOY_RECEIPT_CONTRACT:
        raise EvidenceError("joint_deploy_receipt_required")
    _require(
        contract_name == JOINT_DEPLOY_RECEIPT_CONTRACT,
        "deploy_receipt_contract_invalid",
    )
    _require(
        deploy.get("coordination_contract_name") == JOINT_DEPLOY_RECEIPT_CONTRACT
        and deploy.get("component_contracts")
        == {"memorial_deploy": contract.DEPLOY_RECEIPT_CONTRACT}
        and deploy.get("service_scope") == JOINT_SERVICE_SCOPE
        and deploy.get("api_mutation_scope") == ["ea-api"]
        and deploy.get("ingress_mutation_scope") == ["ea-cloudflared"]
        and deploy.get("joint_atomicity") == JOINT_ATOMICITY,
        "joint_deploy_atomicity_invalid",
    )
    cleanup = _mapping(
        deploy.get("recovery_journal_cleanup"),
        "joint_recovery_journal_cleanup_missing",
    )
    cleanup_path = _absolute_private_path(
        cleanup.get("path"),
        "joint_recovery_journal_cleanup_invalid",
    )
    _require(
        set(cleanup)
        == {
            "contains_secret_material",
            "path",
            "state_directory",
            "status",
        }
        and cleanup.get("status") == "removed"
        and cleanup.get("contains_secret_material") is True
        and str(cleanup_path) == cleanup.get("path"),
        "joint_recovery_journal_cleanup_invalid",
    )
    _require_joint_cleanup_state(cleanup, cleanup_path)
    edge = _mapping(deploy.get("joint_public_edge"), "joint_public_edge_missing")
    _require(
        set(edge) == {"request_count", "source_revision", "status"}
        and edge.get("status") == "pass"
        and edge.get("source_revision") == source_revision
        and type(edge.get("request_count")) is int
        and edge["request_count"] == 12,
        "joint_public_edge_invalid",
    )
    handoff = _mapping(
        deploy.get("spatial_materializer_handoff"),
        "joint_spatial_materializer_handoff_missing",
    )
    _require(
        set(handoff)
        == {
            "candidate_browser_receipt",
            "candidate_runtime_receipt",
            "deploy_receipt",
        },
        "joint_spatial_materializer_handoff_invalid",
    )
    deploy_handoff = _mapping(
        handoff.get("deploy_receipt"),
        "joint_spatial_materializer_handoff_invalid",
    )
    browser_handoff = _mapping(
        handoff.get("candidate_browser_receipt"),
        "joint_spatial_materializer_handoff_invalid",
    )
    runtime_handoff = _mapping(
        handoff.get("candidate_runtime_receipt"),
        "joint_spatial_materializer_handoff_invalid",
    )
    promotion = _mapping(
        deploy.get("candidate_promotion_evidence"),
        "candidate_promotion_evidence_missing",
    )
    browser_binding = _mapping(
        deploy.get("spatial_browser_binding"),
        "joint_spatial_browser_binding_missing",
    )
    _require(
        deploy_handoff
        == {
            "environment": DEPLOY_RECEIPT_ENV,
            "path": str(deploy_receipt_path),
            "contract_name": JOINT_DEPLOY_RECEIPT_CONTRACT,
        }
        and browser_handoff
        == {
            "environment": CANDIDATE_BROWSER_RECEIPT_ENV,
            "path": str(candidate_browser_receipt_path),
            "sha256": candidate_browser_sha256,
            "schema": contract.CANDIDATE_BROWSER_SCHEMA,
            "exact_binding": (
                "candidate_runtime.spatial_handoff_runtime."
                "candidate_browser_gate"
            ),
        }
        and runtime_handoff
        == {
            "path": promotion.get("path"),
            "sha256": promotion.get("sha256"),
            "schema": CANDIDATE_RUNTIME_SCHEMA,
        },
        "joint_spatial_materializer_handoff_invalid",
    )
    _require(
        browser_binding
        == {
            "status": "pass",
            "candidate_runtime_receipt_path": runtime_handoff["path"],
            "candidate_runtime_receipt_sha256": runtime_handoff["sha256"],
            "candidate_runtime_schema": CANDIDATE_RUNTIME_SCHEMA,
            "browser_receipt_path": browser_handoff["path"],
            "browser_receipt_sha256": browser_handoff["sha256"],
            "browser_schema": contract.CANDIDATE_BROWSER_SCHEMA,
            "secret_material_recorded": False,
            "exact_embedded_binding": True,
        },
        "joint_spatial_browser_binding_invalid",
    )
    return contract_name


def _candidate_chain(
    deploy: dict[str, Any],
    *,
    source_revision: str,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    evidence = _mapping(
        deploy.get("candidate_promotion_evidence"),
        "candidate_promotion_evidence_missing",
    )
    candidate_path = _absolute_private_path(
        evidence.get("path"), "candidate_receipt_path_invalid"
    )
    candidate, candidate_bytes = _private_json(
        candidate_path, code="candidate_receipt_invalid"
    )
    candidate_sha = _sha256(candidate_bytes)
    _require(
        evidence.get("sha256") == candidate_sha
        and evidence.get("status") == "pass"
        and evidence.get("source_revision") == source_revision,
        "candidate_deploy_binding_mismatch",
    )
    _require(
        candidate.get("schema") == CANDIDATE_RUNTIME_SCHEMA
        and candidate.get("status") == "pass"
        and candidate.get("projection_commit") == source_revision
        and candidate.get("image_source_revision") == source_revision
        and candidate.get("runtime_source_revision") == source_revision
        and candidate.get("runtime_authority_commit") == source_revision
        and candidate.get("runtime_revision_matches_image") is True
        and candidate.get("provider_calls_performed") is False
        and candidate.get("promotion_authority") is False,
        "candidate_receipt_contract_invalid",
    )
    spatial = _mapping(candidate.get("spatial_handoff"), "spatial_handoff_missing")
    spatial_path = _absolute_private_path(
        spatial.get("receipt_path"), "spatial_projection_receipt_path_invalid"
    )
    spatial_receipt, spatial_bytes = _private_json(
        spatial_path, code="spatial_projection_receipt_invalid"
    )
    _require(
        spatial.get("receipt_sha256") == _sha256(spatial_bytes)
        and spatial_receipt.get("schema") == SPATIAL_PROJECTION_SCHEMA
        and spatial_receipt.get("status") == "pass"
        and spatial_receipt.get("slug") == contract.PROPERTY_TOUR_SLUG
        and spatial_receipt.get("public_activation_authority") is False
        and spatial_receipt.get("upstream_public_activation_authority") is True,
        "spatial_projection_binding_invalid",
    )
    return candidate, spatial_receipt, candidate_sha


def _authority(
    spatial: dict[str, Any],
    *,
    package_sha256: str,
) -> dict[str, object]:
    upstream = _mapping(
        spatial.get("upstream_publication_authority"),
        "property_authority_missing",
    )
    source = _mapping(upstream.get("source"), "property_authority_source_invalid")
    reviews = _mapping(
        upstream.get("review_receipts"), "property_authority_reviews_invalid"
    )
    final_review = _mapping(
        reviews.get("flagship_final"), "property_authority_reviews_invalid"
    )
    browser_review = _mapping(
        reviews.get("exact_viewer_browser"), "property_authority_reviews_invalid"
    )
    authority_sha = _sha256(
        json.dumps(
            upstream,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        + b"\n"
    )
    _require(
        upstream.get("schema") == contract.PROPERTY_AUTHORITY_SCHEMA
        and upstream.get("status") == AUTHORITY_STATUS
        and upstream.get("owner") == contract.PROPERTY_AUTHORITY_OWNER
        and upstream.get("repository") == contract.PROPERTY_REPOSITORY
        and upstream.get("slug") == contract.PROPERTY_TOUR_SLUG
        and upstream.get("public_activation_authority") is True
        and upstream.get("publication_authority_verified") is True
        and source.get("artifact_commit") == contract.PROPERTY_ARTIFACT_COMMIT
        and source.get("packager_commit") == contract.PROPERTY_PACKAGER_COMMIT
        and source.get("worktree_clean") is True
        and final_review.get("sha256") == contract.PROPERTY_FINAL_REVIEW_SHA256
        and browser_review.get("sha256") == contract.PROPERTY_BROWSER_REVIEW_SHA256
        and authority_sha == contract.PROPERTY_AUTHORITY_SHA256
        and spatial.get("upstream_publication_authority_sha256") == authority_sha
        and spatial.get("upstream_package_sha256") == package_sha256
        and spatial.get("upstream_tour_manifest_sha256")
        == contract.PROPERTY_TOUR_SHA256
        and spatial.get("pre_authority_manifest_canonical_sha256")
        == contract.PROPERTY_PRE_AUTHORITY_SHA256,
        "property_authority_contract_invalid",
    )
    return {
        "artifact_commit": contract.PROPERTY_ARTIFACT_COMMIT,
        "browser_review_receipt_sha256": contract.PROPERTY_BROWSER_REVIEW_SHA256,
        "ea_public_activation_authority": False,
        "final_review_receipt_sha256": contract.PROPERTY_FINAL_REVIEW_SHA256,
        "owner": contract.PROPERTY_AUTHORITY_OWNER,
        "packager_commit": contract.PROPERTY_PACKAGER_COMMIT,
        "pre_authority_manifest_canonical_sha256": (
            contract.PROPERTY_PRE_AUTHORITY_SHA256
        ),
        "publication_authority_sha256": contract.PROPERTY_AUTHORITY_SHA256,
        "repository": contract.PROPERTY_REPOSITORY,
        "schema": contract.PROPERTY_AUTHORITY_SCHEMA,
        "status": "pass",
        "tour_manifest_sha256": contract.PROPERTY_TOUR_SHA256,
        "upstream_public_activation_authority": True,
    }


def _package(browser: dict[str, Any], public_spatial: dict[str, Any]) -> dict[str, object]:
    binding = _mapping(browser.get("package_binding"), "browser_package_missing")
    raw_files = binding.get("local_files")
    _require(isinstance(raw_files, list) and len(raw_files) == 6, "browser_package_invalid")
    rows: list[dict[str, object]] = []
    digest_rows: list[dict[str, object]] = []
    for raw in raw_files:
        row = _mapping(raw, "browser_package_file_invalid")
        path = row.get("path")
        _require(
            set(row) == {"path", "sha256", "size_bytes"}
            and isinstance(path, str)
            and path in FILE_SPECS
            and SHA256_RE.fullmatch(str(row.get("sha256") or "")) is not None
            and type(row.get("size_bytes")) is int
            and int(row.get("size_bytes") or 0) > 0,
            "browser_package_file_invalid",
        )
        role, mime_type = FILE_SPECS[str(path)]
        rows.append(
            {
                "mime_type": mime_type,
                "path": str(path),
                "role": role,
                "sha256": str(row["sha256"]),
                "size_bytes": int(row["size_bytes"]),
            }
        )
        digest_rows.append(
            {
                "path": str(path),
                "sha256": str(row["sha256"]),
                "size_bytes": int(row["size_bytes"]),
            }
        )
    rows.sort(key=lambda item: str(item["path"]))
    digest_rows.sort(key=lambda item: str(item["path"]))
    package_sha = contract.canonical_json_sha256(digest_rows)
    _require(
        len({str(row["path"]) for row in rows}) == 6
        and package_sha == browser.get("package_sha256")
        and package_sha == binding.get("package_sha256")
        and next(row for row in rows if row["path"] == "tour.json")["sha256"]
        == contract.PROPERTY_TOUR_SHA256,
        "browser_package_digest_mismatch",
    )
    routes = _mapping(public_spatial.get("routes"), "public_spatial_routes_missing")
    tour_get = _mapping(routes.get("tour_json_get"), "public_spatial_routes_missing")
    canonical_tour_sha = tour_get.get("canonical_json_sha256")
    browser_public_tour = _mapping(
        binding.get("public_tour_manifest"),
        "browser_public_tour_manifest_missing",
    )
    browser_canonical_tour_sha = browser_public_tour.get(
        "canonical_json_sha256"
    )
    _require(
        SHA256_RE.fullmatch(str(canonical_tour_sha or "")) is not None
        and SHA256_RE.fullmatch(str(browser_canonical_tour_sha or "")) is not None
        and canonical_tour_sha == browser_canonical_tour_sha,
        "browser_public_tour_digest_mismatch",
    )
    release_revision = binding.get("release_revision")
    _require(
        isinstance(release_revision, str) and bool(release_revision.strip()),
        "browser_release_revision_invalid",
    )
    return {
        "file_count": 6,
        "files": rows,
        "package_sha256": package_sha,
        "pre_authority_manifest_canonical_sha256": (
            contract.PROPERTY_PRE_AUTHORITY_SHA256
        ),
        "proof_relpath": contract.PROOF_RELPATH,
        "release_revision": release_revision,
        "schema": contract.PROPERTY_PACKAGE_SCHEMA,
        "slug": contract.PROPERTY_TOUR_SLUG,
        "status": "pass",
        "tour_manifest_canonical_sha256": canonical_tour_sha,
        "tour_manifest_sha256": contract.PROPERTY_TOUR_SHA256,
        "viewer_relpath": contract.VIEWER_RELPATH,
    }


def _browser_summary(browser: dict[str, Any], receipt_sha: str) -> dict[str, object]:
    surfaces = _mapping(browser.get("surfaces"), "browser_surfaces_missing")
    interactive: dict[str, object] = {}
    for name in ("desktop", "mobile", "reduced_motion"):
        surface = _mapping(surfaces.get(name), "browser_surfaces_missing")
        interactions = surface.get("route_interactions")
        _require(
            isinstance(interactions, list) and len(interactions) == 9,
            "browser_route_interactions_invalid",
        )
        labels: list[str] = []
        digests: list[str] = []
        for raw in interactions:
            interaction = _mapping(raw, "browser_route_interactions_invalid")
            label = interaction.get("label")
            digest = interaction.get("camera_canvas_screenshot_sha256")
            _require(
                isinstance(label, str)
                and bool(label.strip())
                and SHA256_RE.fullmatch(str(digest or "")) is not None,
                "browser_route_interactions_invalid",
            )
            labels.append(label)
            digests.append(str(digest))
        _require(len(set(labels)) == 9 and len(set(digests)) == 9, "browser_route_interactions_invalid")
        interactive[name] = {
            "camera_canvas_screenshot_sha256": digests,
            "route_interaction_count": 9,
            "route_labels": labels,
        }
    fallback_raw = _mapping(surfaces.get("webgl_fallback"), "browser_fallback_missing")
    fallback = {
        "enabled_button_count": fallback_raw.get("enabled_button_count"),
        "enabled_route_button_count": fallback_raw.get("enabled_route_button_count"),
        "fallback_visible": fallback_raw.get("fallback_visible"),
    }
    landing = _mapping(browser.get("landing"), "browser_landing_missing")
    image = _mapping(browser.get("candidate_oci_image"), "browser_image_missing")
    binding = _mapping(browser.get("package_binding"), "browser_package_missing")
    return {
        "candidate_commit": browser.get("candidate_commit"),
        "candidate_origin": browser.get("candidate_origin"),
        "external_request_count": landing.get("external_request_count"),
        "interactive_surfaces": interactive,
        "landing_surface_count": landing.get("surface_count"),
        "nested_viewer_ready_verified": landing.get("nested_viewer_ready_verified"),
        "oci_image_revision": image.get("oci_image_revision"),
        "package_sha256": browser.get("package_sha256"),
        "receipt_sha256": receipt_sha,
        "release_revision": binding.get("release_revision"),
        "responsive_iframe_verified": landing.get("responsive_iframe_verified"),
        "route_stop_count": browser.get("route_stop_count"),
        "schema": browser.get("schema"),
        "status": browser.get("status"),
        "surface_count": browser.get("surface_count"),
        "webgl_fallback": fallback,
    }


def materialize(
    *,
    repo_root: Path = ROOT,
    deploy_receipt_path: Path | None = None,
    candidate_browser_receipt_path: Path | None = None,
    expected_public_origin: str = "",
    source_state: SourceState | None = None,
    browser_validator: BrowserValidator = validate_spatial_candidate_browser_receipt,
) -> dict[str, object]:
    state = source_state or _source_state(repo_root)
    if deploy_receipt_path is None or candidate_browser_receipt_path is None:
        return _blocked(state, "spatial_public_origin_inputs_missing")
    if not os.path.lexists(deploy_receipt_path) or not os.path.lexists(
        candidate_browser_receipt_path
    ):
        return _blocked(state, "spatial_public_origin_inputs_missing")
    try:
        _require(not state.dirty, "source_worktree_dirty")
        deploy, deploy_bytes = _private_json(
            deploy_receipt_path, code="deploy_receipt_invalid"
        )
        browser, browser_bytes = _private_json(
            candidate_browser_receipt_path,
            code="candidate_browser_receipt_invalid",
        )
        deploy_contract_name = _deploy_contract(
            deploy,
            deploy_receipt_path=deploy_receipt_path,
            candidate_browser_receipt_path=candidate_browser_receipt_path,
            candidate_browser_sha256=_sha256(browser_bytes),
            source_revision=state.head,
        )
        _require(
            deploy.get("status") == "pass"
            and deploy.get("source_revision") == state.head
            and _mapping(deploy.get("source_worktree"), "deploy_source_state_missing").get(
                "source_worktree_dirty"
            )
            is False,
            "deploy_receipt_contract_invalid",
        )
        public_origin = str(deploy.get("public_origin") or "")
        _require(
            not expected_public_origin or public_origin == expected_public_origin,
            "public_origin_override_mismatch",
        )
        public_spatial = _mapping(
            deploy.get("public_spatial_tour"), "public_spatial_tour_missing"
        )
        public_routes = _mapping(
            public_spatial.get("routes"), "public_spatial_routes_missing"
        )
        _require(set(public_routes) == set(ROUTE_LABELS), "public_spatial_routes_invalid")
        public_spatial["routes"] = {
            label: public_routes[label] for label in ROUTE_LABELS
        }
        candidate, spatial, candidate_sha = _candidate_chain(
            deploy, source_revision=state.head
        )
        embedded = _mapping(
            _mapping(
                candidate.get("spatial_handoff_runtime"),
                "candidate_spatial_runtime_missing",
            ).get("candidate_browser_gate"),
            "candidate_browser_gate_missing",
        )
        _require(embedded == browser, "candidate_browser_receipt_binding_mismatch")
        package = _package(browser, public_spatial)
        authority = _authority(
            spatial, package_sha256=str(package["package_sha256"])
        )
        candidate_image = _mapping(
            browser.get("candidate_oci_image"), "candidate_browser_image_missing"
        )
        serving = _mapping(
            browser.get("serving_container"), "candidate_browser_container_missing"
        )
        browser_validator(
            browser,
            base_url=str(browser.get("candidate_origin") or ""),
            slug=contract.PROPERTY_TOUR_SLUG,
            viewer_relpath=contract.VIEWER_RELPATH,
            route_labels=list(spatial.get("route_labels") or []),
            candidate_commit=state.head,
            oci_image_id=str(candidate_image.get("image_id") or ""),
            serving_container_id=str(serving.get("container_id") or ""),
            package_sha256=str(package["package_sha256"]),
        )
        receipt = {
            "candidate_browser": _browser_summary(browser, _sha256(browser_bytes)),
            "checks": dict(CHECKS),
            "contract_name": contract.CONTRACT_NAME,
            "deploy_binding": {
                "candidate_promotion_evidence_sha256": candidate_sha,
                "contract_name": deploy_contract_name,
                "deployment_id": deploy.get("deployment_id"),
                "public_origin": public_origin,
                "public_spatial_tour_sha256": contract.canonical_json_sha256(
                    public_spatial
                ),
                "receipt_sha256": _sha256(deploy_bytes),
                "source_revision": state.head,
                "status": "pass",
            },
            "external_requests": 0,
            "failed_codes": [],
            "generated_at": deploy.get("completed_at"),
            "generated_by": contract.GENERATED_BY,
            "gold_claim_allowed": True,
            "head_semantics": "source_state",
            "package_binding": package,
            "provider_calls_performed": False,
            "public_base_url": public_origin,
            "public_spatial_tour": public_spatial,
            "publication_authority": authority,
            "runtime_revision": state.head,
            "slug": "manfred",
            "source_git_head": state.head,
            "source_state_fingerprint": state.fingerprint,
            "source_state_fingerprint_semantics": (
                contract.SOURCE_STATE_FINGERPRINT_SEMANTICS
            ),
            "source_worktree_dirty": False,
            "status": "pass",
            "tour_slug": contract.PROPERTY_TOUR_SLUG,
        }
        issues = contract.validate_memorial_spatial_public_origin_receipt(
            receipt,
            current_head=state.head,
            current_fingerprint=state.fingerprint,
        )
        _require(not issues, issues[0] if issues else "receipt_validation_failed")
        return receipt
    except (RuntimeError, TypeError, ValueError, OSError) as exc:
        code = str(exc) if isinstance(exc, EvidenceError) else "spatial_public_origin_evidence_invalid"
        return _blocked(state, code)


def _write_receipt(path: Path, payload: Mapping[str, object]) -> None:
    target = path.expanduser()
    if not target.is_absolute():
        target = ROOT / target
    target.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=False) + "\n"
    ).encode("utf-8")
    temporary = target.with_name(f".{target.name}.tmp.{os.getpid()}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(temporary, flags, 0o600)
    try:
        view = memoryview(encoded)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("receipt_write_failed")
            view = view[written:]
        os.fchmod(descriptor, 0o600)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, target)
    target.chmod(0o600)


def _optional_path(cli_value: Path | None, env_name: str) -> Path | None:
    if cli_value is not None:
        return cli_value.expanduser()
    raw = str(os.getenv(env_name) or "").strip()
    return Path(raw).expanduser() if raw else None


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Materialize governed Manfred spatial public-origin proof."
    )
    parser.add_argument("--deploy-receipt", type=Path)
    parser.add_argument("--candidate-browser-receipt", type=Path)
    parser.add_argument("--public-base-url", default="")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    receipt = materialize(
        deploy_receipt_path=_optional_path(args.deploy_receipt, DEPLOY_RECEIPT_ENV),
        candidate_browser_receipt_path=_optional_path(
            args.candidate_browser_receipt,
            CANDIDATE_BROWSER_RECEIPT_ENV,
        ),
        expected_public_origin=(
            str(args.public_base_url or os.getenv(PUBLIC_ORIGIN_ENV) or "").strip()
        ),
    )
    _write_receipt(args.output, receipt)
    print(json.dumps(receipt, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
