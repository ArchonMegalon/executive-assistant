from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import stat

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.api.routes import public_tours
from scripts import prepare_manfred_memorial_candidate as prepare
from scripts import run_manfred_memorial_candidate as runner
from scripts import verify_public_tour_generated_viewer_release as verifier


SLUG = "generated-viewer-tour"
TARGET_ORIGIN = "https://myexternalbrain.com"
ARTIFACT_COMMIT = "a" * 40
PACKAGER_COMMIT = "c" * 40
USER_INSTRUCTION_SHA256 = "b" * 64
RAW_RECONSTRUCTION_SHA256 = "d" * 64
ROUTE_LABELS = [f"Stop {index}" for index in range(1, 10)]
DISCLOSURE = (
    "Generated interactive reconstruction from the supplied floor plan. "
    "It is not a captured or provider-verified 3D scan."
)


def _request(path: str) -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "https",
            "path": path,
            "raw_path": path.encode("utf-8"),
            "query_string": b"",
            "headers": [(b"host", b"myexternalbrain.com")],
            "client": ("127.0.0.1", 49152),
            "server": ("myexternalbrain.com", 443),
        }
    )


def _surface(*, fallback: bool = False) -> dict[str, object]:
    return {
        "http_status": 200,
        "viewerStatus": "not-ready" if fallback else "ready",
        "page_errors": [],
        "console_errors": [],
        "horizontalOverflowPx": 0,
        "undersizedTargets": [],
        "alertRole": "alert",
        "alertVisible": fallback,
        "enabledInteractiveControlCount": 0 if fallback else 19,
    }


def _write_private_json(path: Path, payload: dict[str, object]) -> bytes:
    content = (
        json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    path.chmod(0o600)
    return content


def _build_property_package(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path, dict[str, bytes]]:
    browser_receipt = {
        "schema": "propertyquarry.exact_viewer_browser_audit.v3",
        "slug": SLUG,
        "status": "pass",
        "failures": [],
        "viewer_sha256": "",
        "reconstruction_sha256": RAW_RECONSTRUCTION_SHA256,
        "surfaces": {
            "desktop": _surface(),
            "mobile": _surface(),
            "reduced-motion": _surface(),
            "webgl-fallback": _surface(fallback=True),
        },
    }
    viewer = b"<!doctype html><canvas aria-label='Layout'></canvas>"
    floorplan = b"floorplan-png"
    browser_receipt["viewer_sha256"] = hashlib.sha256(viewer).hexdigest()
    browser_path = tmp_path / "evidence" / "browser.json"
    browser_bytes = _write_private_json(browser_path, browser_receipt)
    browser_sha256 = hashlib.sha256(browser_bytes).hexdigest()

    final_receipt = {
        "schema": "propertyquarry.flagship_3d_review_receipt.v1",
        "slug": SLUG,
        "status": "polished_review_candidate_pass_guarded_not_published",
        "source": {"commit": ARTIFACT_COMMIT, "worktree_clean": True},
        "review_bundle": {
            "viewer_sha256": hashlib.sha256(viewer).hexdigest(),
            "reconstruction_sha256": RAW_RECONSTRUCTION_SHA256,
            "floorplan_sha256": hashlib.sha256(floorplan).hexdigest(),
            "runtime_publish_required": False,
            "runtime_publish_ok": True,
            "verified_provider_capture": False,
            "satisfies_verified_tour_gate": False,
        },
        "visual_verification": {
            "browser_receipt_sha256": browser_sha256,
            "browser_status": "pass",
            "browser_failures": [],
            "route_status": "pass",
            "route_failures": [],
            "route_stop_count": 9,
            "surfaces": [
                "desktop",
                "mobile",
                "reduced-motion",
                "webgl-fallback",
            ],
        },
        "verification": {
            "property_generated_reconstruction": {"result": "pass"},
            "property_tour_control_and_importers": {"result": "pass"},
            "independent_camera_geometry_accessibility_review": {
                "result": "approved"
            },
            "independent_runtime_publish_safety_review": {"result": "approved"},
        },
        "live_guard": {
            "runtime_mutation_detected": False,
            "all_observed_product_routes_guarded_404": True,
        },
    }
    final_path = tmp_path / "evidence" / "final.json"
    final_bytes = _write_private_json(final_path, final_receipt)
    final_sha256 = hashlib.sha256(final_bytes).hexdigest()

    proof = {
        "schema": prepare.PROPERTY_RECONSTRUCTION_SCHEMA,
        "slug": SLUG,
        "source_commit": ARTIFACT_COMMIT,
        "synthetic": True,
        "capture_mode": False,
        "verified_provider_capture": False,
        "satisfies_verified_tour_gate": False,
        "route_labels": ROUTE_LABELS,
        "floorplan": {
            "source_path": (
                f"property://{prepare.PROPERTY_REPOSITORY}/{ARTIFACT_COMMIT}/"
                "floorplan-apartment-crop.png"
            ),
            "sha256": hashlib.sha256(floorplan).hexdigest(),
        },
        "viewer": {"sha256": hashlib.sha256(viewer).hexdigest()},
    }
    assets = {
        "generated-reconstruction/viewer.html": viewer,
        "generated-reconstruction/reconstruction.json": prepare._canonical_json_bytes(
            proof
        ),
        "generated-reconstruction/source-floorplan.png": floorplan,
        "generated-reconstruction/vendor/three.module.js": (
            b"export const Scene = class {};"
        ),
        "generated-reconstruction/vendor/examples/jsm/controls/OrbitControls.js": (
            b"export class OrbitControls {}"
        ),
    }
    specs = (
        ("generated-reconstruction/viewer.html", "text/html", "viewer_document"),
        (
            "generated-reconstruction/reconstruction.json",
            "application/json",
            "reconstruction_manifest",
        ),
        (
            "generated-reconstruction/source-floorplan.png",
            "image/png",
            "floorplan_texture",
        ),
        (
            "generated-reconstruction/vendor/three.module.js",
            "text/javascript",
            "viewer_module",
        ),
        (
            "generated-reconstruction/vendor/examples/jsm/controls/OrbitControls.js",
            "text/javascript",
            "viewer_module",
        ),
    )
    bindings = [
        {
            "path": path,
            "sha256": hashlib.sha256(assets[path]).hexdigest(),
            "size_bytes": len(assets[path]),
            "mime_type": mime_type,
            "role": role,
        }
        for path, mime_type, role in specs
    ]
    generated = {
        "provider": "propertyquarry_generated_reconstruction",
        "synthetic": True,
        "capture_mode": False,
        "verified_provider_capture": False,
        "satisfies_verified_tour_gate": False,
        "viewer_version": "propertyquarry_3d_tour_viewer_v3",
        "viewer_relpath": "generated-reconstruction/viewer.html",
        "manifest_relpath": "generated-reconstruction/reconstruction.json",
        "floorplan_relpath": "generated-reconstruction/source-floorplan.png",
        "photo_relpaths": [],
        "photo_reference_panel_count": 0,
        "route_labels": ROUTE_LABELS,
        "room_stop_count": 9,
        "disclosure": DISCLOSURE,
    }
    release = {
        "contract": "ea.public-tour-generated-viewer-release.v1",
        "status": "ready",
        "provider": "propertyquarry_generated_reconstruction",
        "viewer_relpath": "generated-reconstruction/viewer.html",
        "asset_bindings": bindings,
        "browser_receipt_sha256": browser_sha256,
        "source_provenance_receipt_sha256": final_sha256,
        "publication_authority_receipt_sha256": None,
        "security_review_receipt_sha256": final_sha256,
        "accessibility_review_receipt_sha256": final_sha256,
        "browser_interaction_verified": True,
        "visual_quality_review_passed": True,
        "security_review_passed": True,
        "accessibility_review_passed": True,
        "source_provenance_verified": True,
        "publication_authority_verified": True,
        "public_activation_authority": True,
        "release_revision": "property-test-release-v1",
        "disclosure": DISCLOSURE,
        "synthetic": True,
        "capture_mode": False,
        "verified_provider_capture": False,
        "satisfies_verified_tour_gate": False,
        "revoked": False,
        "disqualified": False,
    }
    tour = {
        "schema": prepare.PROPERTY_PUBLIC_TOUR_PACKAGE_SCHEMA,
        "slug": SLUG,
        "source_commit": ARTIFACT_COMMIT,
        "synthetic": True,
        "scene_strategy": "generated_layout_reconstruction",
        "creation_mode": "propertyquarry_governed_publication",
        "generated_reconstruction": generated,
        "generated_viewer_release": release,
        "route_labels": ROUTE_LABELS,
    }
    pre_authority_sha256 = hashlib.sha256(
        prepare._canonical_json_bytes_without_lf(tour)
    ).hexdigest()
    expected_paths = sorted({"tour.json", *assets})
    review_rows = {
        "flagship_final": {
            "schema": final_receipt["schema"],
            "status": final_receipt["status"],
            "sha256": final_sha256,
        },
        "exact_viewer_browser": {
            "schema": browser_receipt["schema"],
            "status": browser_receipt["status"],
            "sha256": browser_sha256,
        },
    }
    authority = {
        "schema": prepare.PROPERTY_PUBLICATION_AUTHORITY_SCHEMA,
        "status": "authorized",
        "owner": prepare.PROPERTY_AUTHORITY_OWNER,
        "repository": prepare.PROPERTY_REPOSITORY,
        "slug": SLUG,
        "public_activation_authority": True,
        "publication_authority_verified": True,
        "user_instruction_sha256": USER_INSTRUCTION_SHA256,
        "allowed_public_origins": sorted(prepare.PROPERTY_ALLOWED_PUBLIC_ORIGINS),
        "source": {
            "artifact_commit": ARTIFACT_COMMIT,
            "packager_commit": PACKAGER_COMMIT,
            "worktree_clean": True,
        },
        "classification": {
            "synthetic": True,
            "capture_mode": False,
            "verified_provider_capture": False,
            "satisfies_verified_tour_gate": False,
            "disclosure": DISCLOSURE,
        },
        "review_receipts": review_rows,
        "package": {
            "public_bundle_relpath": f"public_property_tours/{SLUG}",
            "public_file_relpaths": expected_paths,
            "public_file_count": 6,
            "pre_authority_manifest_canonicalization": (
                prepare.PROPERTY_PRE_AUTHORITY_CANONICALIZATION
            ),
            "pre_authority_manifest_canonical_sha256": pre_authority_sha256,
            "asset_bindings": bindings,
        },
    }
    authority_bytes = prepare._canonical_json_bytes(authority)
    authority_sha256 = hashlib.sha256(authority_bytes).hexdigest()
    release["publication_authority_receipt_sha256"] = authority_sha256
    tour_bytes = prepare._canonical_json_bytes(tour)
    snapshot = {"tour.json": tour_bytes, **assets}

    bundle = tmp_path / "property" / "public_property_tours" / SLUG
    bundle.mkdir(parents=True)
    for relpath, content in snapshot.items():
        target = bundle / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        target.chmod(0o644)
    for path in [bundle, *bundle.rglob("*")]:
        if path.is_dir():
            path.chmod(0o755)
    authority_path = tmp_path / "property" / "publication-authority" / f"{SLUG}.json"
    authority_path.parent.mkdir(parents=True)
    authority_path.write_bytes(authority_bytes)
    authority_path.chmod(0o600)

    patched = {
        "PROPERTY_AUTHORIZED_SLUG": SLUG,
        "PROPERTY_ARTIFACT_COMMIT": ARTIFACT_COMMIT,
        "PROPERTY_PACKAGER_COMMIT": PACKAGER_COMMIT,
        "PROPERTY_USER_INSTRUCTION_SHA256": USER_INSTRUCTION_SHA256,
        "PROPERTY_FINAL_REVIEW_SHA256": final_sha256,
        "PROPERTY_BROWSER_REVIEW_SHA256": browser_sha256,
        "PROPERTY_AUTHORITY_SHA256": authority_sha256,
        "PROPERTY_TOUR_SHA256": hashlib.sha256(tour_bytes).hexdigest(),
        "PROPERTY_PRE_AUTHORITY_SHA256": pre_authority_sha256,
        "PROPERTY_FINAL_REVIEW_RECEIPT": final_path,
        "PROPERTY_BROWSER_REVIEW_RECEIPT": browser_path,
    }
    for name, value in patched.items():
        monkeypatch.setattr(prepare, name, value)
    monkeypatch.setattr(runner, "PROPERTY_AUTHORITY_SHA256", authority_sha256)
    return bundle, authority_path, snapshot


def _materialize(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path, Path, dict[str, object], dict[str, bytes]]:
    source, authority, snapshot = _build_property_package(tmp_path, monkeypatch)
    handoff_bundle = tmp_path / "handoff" / "public_property_tours" / SLUG
    handoff_receipt = tmp_path / "handoff" / "receipts" / "handoff.json"
    receipt = prepare.materialize_spatial_handoff(
        source_bundle_dir=source,
        upstream_authority_receipt_path=authority,
        handoff_bundle_dir=handoff_bundle,
        handoff_receipt_path=handoff_receipt,
        target_origin=TARGET_ORIGIN,
    )
    return handoff_bundle, handoff_receipt, authority, receipt, snapshot


def test_materializer_preserves_property_bytes_and_separates_ea_handoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, handoff, authority, receipt, source_snapshot = _materialize(
        tmp_path, monkeypatch
    )

    assert stat.S_IMODE(handoff.stat().st_mode) == 0o600
    assert receipt["candidate_handoff_authorized"] is True
    assert receipt["public_activation_authority"] is False
    assert receipt["upstream_public_activation_authority"] is True
    assert receipt["upstream_publication_authority_sha256"] == hashlib.sha256(
        authority.read_bytes()
    ).hexdigest()
    handoff_sha256 = hashlib.sha256(handoff.read_bytes()).hexdigest()
    assert handoff_sha256 == receipt["handoff_receipt_sha256"]
    assert handoff_sha256 != receipt["upstream_publication_authority_sha256"]
    copied = prepare._spatial_tree_snapshot(
        bundle, require_sanitized_modes=True
    )
    assert copied == source_snapshot
    tour = json.loads(copied["tour.json"])
    assert (
        tour["generated_viewer_release"][
            "publication_authority_receipt_sha256"
        ]
        == receipt["upstream_publication_authority_sha256"]
    )
    assert handoff_sha256 not in copied["tour.json"].decode("utf-8")
    assert verifier.verify_bundle(bundle, slug=SLUG)["pass"] is True


def test_validator_requires_actual_pinned_review_and_authority_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, authority, _snapshot = _build_property_package(tmp_path, monkeypatch)
    assert (
        prepare._validated_spatial_handoff_input(
            bundle_dir=bundle,
            authority_receipt_path=authority,
            target_origin=TARGET_ORIGIN,
        )["upstream_public_activation_authority"]
        is True
    )

    fake_review = Path(prepare.PROPERTY_FINAL_REVIEW_RECEIPT)
    fake_review.write_bytes(b'{}\n')
    fake_review.chmod(0o600)
    with pytest.raises(ValueError, match="review_evidence_invalid"):
        prepare._validated_spatial_handoff_input(
            bundle_dir=bundle,
            authority_receipt_path=authority,
            target_origin=TARGET_ORIGIN,
        )


def test_validator_rejects_tour_or_upstream_authority_tamper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, authority, _snapshot = _build_property_package(tmp_path, monkeypatch)
    payload = json.loads((bundle / "tour.json").read_bytes())
    payload["creation_mode"] = "retargeted"
    (bundle / "tour.json").write_bytes(prepare._canonical_json_bytes(payload))
    (bundle / "tour.json").chmod(0o644)
    with pytest.raises(ValueError, match="authority|digest"):
        prepare._validated_spatial_handoff_input(
            bundle_dir=bundle,
            authority_receipt_path=authority,
            target_origin=TARGET_ORIGIN,
        )

    bundle, authority, _snapshot = _build_property_package(
        tmp_path / "authority", monkeypatch
    )
    authority.write_bytes(authority.read_bytes() + b" ")
    authority.chmod(0o600)
    with pytest.raises(ValueError, match="canonical|mismatch"):
        prepare._validated_spatial_handoff_input(
            bundle_dir=bundle,
            authority_receipt_path=authority,
            target_origin=TARGET_ORIGIN,
        )


@pytest.mark.parametrize(
    "case",
    ["extra", "symlink", "root_symlink", "unsafe_mode", "hardlink", "oversize"],
)
def test_spatial_intake_rejects_extras_links_modes_and_oversize(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    bundle, authority, _snapshot = _build_property_package(tmp_path, monkeypatch)
    if case == "extra":
        extra = bundle / "generated-reconstruction" / "debug.json"
        extra.write_text("{}", encoding="utf-8")
        extra.chmod(0o644)
    elif case == "symlink":
        (bundle / "linked-viewer.html").symlink_to(
            bundle / "generated-reconstruction" / "viewer.html"
        )
    elif case == "root_symlink":
        linked_root = tmp_path / "linked-root"
        linked_root.symlink_to(bundle, target_is_directory=True)
        bundle = linked_root
    elif case == "unsafe_mode":
        (bundle / "generated-reconstruction" / "viewer.html").chmod(0o666)
    elif case == "hardlink":
        viewer = bundle / "generated-reconstruction" / "viewer.html"
        os.link(viewer, tmp_path / "viewer-hardlink.html")
    else:
        monkeypatch.setattr(prepare, "MAX_SPATIAL_FILE_BYTES", 8)
    with pytest.raises(ValueError, match="spatial_"):
        prepare._validated_spatial_handoff_input(
            bundle_dir=bundle,
            authority_receipt_path=authority,
            target_origin=TARGET_ORIGIN,
        )


def test_materializer_never_overwrites_bundle_or_receipt_race_targets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, authority, _snapshot = _build_property_package(tmp_path, monkeypatch)
    bundle_target = tmp_path / "out" / "public_property_tours" / SLUG
    receipt_target = tmp_path / "out" / "receipts" / "handoff.json"
    bundle_target.mkdir(parents=True)
    marker = bundle_target / "attacker"
    marker.write_text("keep", encoding="utf-8")
    with pytest.raises(ValueError, match="output_exists"):
        prepare.materialize_spatial_handoff(
            source_bundle_dir=source,
            upstream_authority_receipt_path=authority,
            handoff_bundle_dir=bundle_target,
            handoff_receipt_path=receipt_target,
            target_origin=TARGET_ORIGIN,
        )
    assert marker.read_text(encoding="utf-8") == "keep"
    assert not receipt_target.exists()

    shutil.rmtree(bundle_target)
    receipt_target.parent.mkdir(parents=True, exist_ok=True)
    receipt_target.write_text("attacker", encoding="utf-8")
    receipt_target.chmod(0o600)
    with pytest.raises(ValueError, match="output_exists"):
        prepare.materialize_spatial_handoff(
            source_bundle_dir=source,
            upstream_authority_receipt_path=authority,
            handoff_bundle_dir=bundle_target,
            handoff_receipt_path=receipt_target,
            target_origin=TARGET_ORIGIN,
        )
    assert receipt_target.read_text(encoding="utf-8") == "attacker"
    assert not bundle_target.exists()
    quarantined = tuple(bundle_target.parent.iterdir())
    assert len(quarantined) == 2
    assert all(path.name.startswith(".") for path in quarantined)
    assert all(
        stat.S_IMODE(path.stat().st_mode) == 0o000
        for path in quarantined
    )
    for path in quarantined:
        path.chmod(0o755)
        prepare._make_tree_removable(path)
        shutil.rmtree(path)


def test_materializer_rejects_stage_path_replacement_between_snapshot_and_rename(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, authority, source_snapshot = _build_property_package(
        tmp_path, monkeypatch
    )
    authority_bytes = authority.read_bytes()
    authority_mode = stat.S_IMODE(authority.stat().st_mode)
    bundle_target = tmp_path / "out" / "public_property_tours" / SLUG
    receipt_target = tmp_path / "out" / "receipts" / "handoff.json"
    original_rename = prepare._rename_noreplace
    preserved_name = ".verified-stage-preserved"
    swapped = False
    attacker_root_mode: int | None = None
    attacker_file_mode: int | None = None

    def racing_rename(  # type: ignore[no-untyped-def]
        source_parent_descriptor,
        source_name,
        destination_parent_descriptor,
        destination_name,
    ):
        nonlocal attacker_file_mode, attacker_root_mode, swapped
        if not swapped and destination_name == SLUG:
            os.rename(
                source_name,
                preserved_name,
                src_dir_fd=source_parent_descriptor,
                dst_dir_fd=source_parent_descriptor,
            )
            os.mkdir(source_name, 0o755, dir_fd=source_parent_descriptor)
            attacker_descriptor = os.open(
                source_name,
                os.O_RDONLY | os.O_DIRECTORY,
                dir_fd=source_parent_descriptor,
            )
            try:
                marker_descriptor = os.open(
                    "attacker.txt",
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o644,
                    dir_fd=attacker_descriptor,
                )
                try:
                    os.write(marker_descriptor, b"must-not-install")
                    attacker_file_mode = stat.S_IMODE(
                        os.fstat(marker_descriptor).st_mode
                    )
                finally:
                    os.close(marker_descriptor)
                attacker_root_mode = stat.S_IMODE(
                    os.fstat(attacker_descriptor).st_mode
                )
            finally:
                os.close(attacker_descriptor)
            swapped = True
        return original_rename(
            source_parent_descriptor,
            source_name,
            destination_parent_descriptor,
            destination_name,
        )

    monkeypatch.setattr(prepare, "_rename_noreplace", racing_rename)
    with pytest.raises(ValueError, match="output_install_drift"):
        prepare.materialize_spatial_handoff(
            source_bundle_dir=source,
            upstream_authority_receipt_path=authority,
            handoff_bundle_dir=bundle_target,
            handoff_receipt_path=receipt_target,
            target_origin=TARGET_ORIGIN,
        )

    assert swapped is True
    assert not os.path.lexists(bundle_target)
    assert not receipt_target.exists()
    preserved = bundle_target.parent / preserved_name
    attacker_quarantines = tuple(
        path
        for path in bundle_target.parent.iterdir()
        if path != preserved and path.name.startswith(f".{SLUG}.")
    )
    assert len(attacker_quarantines) == 1
    assert (attacker_quarantines[0] / "attacker.txt").read_bytes() == (
        b"must-not-install"
    )
    assert stat.S_IMODE(attacker_quarantines[0].stat().st_mode) == (
        attacker_root_mode
    )
    assert stat.S_IMODE(
        (attacker_quarantines[0] / "attacker.txt").stat().st_mode
    ) == attacker_file_mode
    assert preserved.is_dir()
    assert stat.S_IMODE(preserved.stat().st_mode) == 0o000
    preserved.chmod(0o755)
    preserved_files = tuple(
        child for child in preserved.rglob("*") if child.is_file()
    )
    assert {
        child.relative_to(preserved).as_posix() for child in preserved_files
    } == set(source_snapshot)
    assert all(child.stat().st_size == 0 for child in preserved_files)
    assert all(
        stat.S_IMODE(child.stat().st_mode) == 0o000
        for child in preserved_files
    )
    assert prepare._spatial_tree_snapshot(
        source,
        require_sanitized_modes=True,
    ) == source_snapshot
    assert authority.read_bytes() == authority_bytes
    assert stat.S_IMODE(authority.stat().st_mode) == authority_mode
    for child in preserved.rglob("*"):
        child.chmod(0o755 if child.is_dir() else 0o644)


def test_materializer_scrubs_original_receipt_and_quarantines_path_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, authority, source_snapshot = _build_property_package(
        tmp_path, monkeypatch
    )
    authority_bytes = authority.read_bytes()
    authority_mode = stat.S_IMODE(authority.stat().st_mode)
    bundle_target = tmp_path / "out" / "public_property_tours" / SLUG
    receipt_target = tmp_path / "out" / "receipts" / "handoff.json"
    preserved_name = ".verified-receipt-preserved"
    original_read = prepare._read_file_at_identity
    swapped = False

    def racing_read(  # type: ignore[no-untyped-def]
        parent_descriptor,
        name,
        identity,
        *,
        maximum,
    ):
        nonlocal swapped
        original_read(
            parent_descriptor,
            name,
            identity,
            maximum=maximum,
        )
        os.rename(
            name,
            preserved_name,
            src_dir_fd=parent_descriptor,
            dst_dir_fd=parent_descriptor,
        )
        attacker_descriptor = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
            dir_fd=parent_descriptor,
        )
        try:
            os.write(attacker_descriptor, b"attacker-receipt")
        finally:
            os.close(attacker_descriptor)
        swapped = True
        raise ValueError("injected_post_receipt_swap")

    monkeypatch.setattr(prepare, "_read_file_at_identity", racing_read)
    with pytest.raises(ValueError, match="injected_post_receipt_swap"):
        prepare.materialize_spatial_handoff(
            source_bundle_dir=source,
            upstream_authority_receipt_path=authority,
            handoff_bundle_dir=bundle_target,
            handoff_receipt_path=receipt_target,
            target_origin=TARGET_ORIGIN,
        )

    assert swapped is True
    assert not os.path.lexists(bundle_target)
    assert not os.path.lexists(receipt_target)
    preserved_receipt = receipt_target.parent / preserved_name
    assert preserved_receipt.stat().st_size == 0
    assert stat.S_IMODE(preserved_receipt.stat().st_mode) == 0o000
    receipt_quarantines = tuple(
        path
        for path in receipt_target.parent.iterdir()
        if path != preserved_receipt
        and path.name.startswith(f".{receipt_target.name}.")
    )
    assert len(receipt_quarantines) == 1
    assert receipt_quarantines[0].read_bytes() == b"attacker-receipt"
    assert stat.S_IMODE(receipt_quarantines[0].stat().st_mode) == 0o600
    assert prepare._spatial_tree_snapshot(
        source,
        require_sanitized_modes=True,
    ) == source_snapshot
    assert authority.read_bytes() == authority_bytes
    assert stat.S_IMODE(authority.stat().st_mode) == authority_mode

    preserved_receipt.chmod(0o600)
    bundle_quarantines = tuple(bundle_target.parent.iterdir())
    assert len(bundle_quarantines) == 1
    for path in bundle_quarantines:
        path.chmod(0o755)
        prepare._make_tree_removable(path)
        shutil.rmtree(path)


def test_bundle_rollback_quarantines_by_identity_before_deleting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = tmp_path / "rollback"
    target = parent / "bundle"
    victim = parent / "victim"
    moved_original = parent / "moved-original"
    target.mkdir(parents=True)
    victim.mkdir()
    (target / "original.txt").write_text("original", encoding="utf-8")
    (victim / "victim.txt").write_text("victim", encoding="utf-8")
    target_metadata = target.stat()
    identity = (target_metadata.st_dev, target_metadata.st_ino)
    parent_descriptor = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
    original_rename = prepare._rename_noreplace
    swapped = False

    def racing_rename(  # type: ignore[no-untyped-def]
        source_parent_descriptor,
        source_name,
        destination_parent_descriptor,
        destination_name,
    ):
        nonlocal swapped
        if not swapped and source_name == "bundle":
            os.rename(
                "bundle",
                "moved-original",
                src_dir_fd=source_parent_descriptor,
                dst_dir_fd=source_parent_descriptor,
            )
            os.rename(
                "victim",
                "bundle",
                src_dir_fd=source_parent_descriptor,
                dst_dir_fd=source_parent_descriptor,
            )
            swapped = True
        return original_rename(
            source_parent_descriptor,
            source_name,
            destination_parent_descriptor,
            destination_name,
        )

    monkeypatch.setattr(prepare, "_rename_noreplace", racing_rename)
    try:
        removed = prepare._remove_bundle_if_identity(
            parent_descriptor,
            "bundle",
            identity,
        )
    finally:
        os.close(parent_descriptor)

    assert swapped is True
    assert removed is False
    assert (target / "victim.txt").read_text(encoding="utf-8") == "victim"
    assert (moved_original / "original.txt").read_text(
        encoding="utf-8"
    ) == "original"


@pytest.mark.parametrize("failure", ["write", "fsync"])
def test_exclusive_receipt_write_quarantines_partial_final_inode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    parent = tmp_path / "receipts"
    parent.mkdir()
    parent_descriptor = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
    if failure == "write":
        original_write = prepare.os.write
        failed = False

        def failing_write(descriptor, content):  # type: ignore[no-untyped-def]
            nonlocal failed
            if not failed:
                failed = True
                original_write(descriptor, content[:3])
                raise OSError("injected write failure")
            return original_write(descriptor, content)

        monkeypatch.setattr(prepare.os, "write", failing_write)
    else:
        original_fsync = prepare.os.fsync
        failed = False

        def failing_fsync(descriptor):  # type: ignore[no-untyped-def]
            nonlocal failed
            if not failed:
                failed = True
                raise OSError("injected fsync failure")
            return original_fsync(descriptor)

        monkeypatch.setattr(prepare.os, "fsync", failing_fsync)
    try:
        with pytest.raises(OSError, match="injected"):
            prepare._exclusive_write_at(
                parent_descriptor,
                "handoff.json",
                b'{"status":"pass"}\n',
                mode=0o600,
            )
    finally:
        os.close(parent_descriptor)

    assert not (parent / "handoff.json").exists()
    quarantined = list(parent.iterdir())
    assert len(quarantined) == 1
    assert quarantined[0].name.startswith(".handoff.json.")
    assert quarantined[0].stat().st_size == 0
    assert stat.S_IMODE(quarantined[0].stat().st_mode) == 0o000


def test_exclusive_write_quarantines_substitute_after_partial_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = tmp_path / "receipts"
    parent.mkdir()
    parent_descriptor = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
    original_write = prepare.os.write
    preserved_name = ".partial-original-preserved"
    failed = False

    def substituted_write(descriptor, content):  # type: ignore[no-untyped-def]
        nonlocal failed
        if not failed:
            failed = True
            original_write(descriptor, content[:3])
            os.rename(
                "handoff.json",
                preserved_name,
                src_dir_fd=parent_descriptor,
                dst_dir_fd=parent_descriptor,
            )
            attacker_descriptor = os.open(
                "handoff.json",
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=parent_descriptor,
            )
            try:
                original_write(attacker_descriptor, b"attacker-partial")
            finally:
                os.close(attacker_descriptor)
            raise OSError("injected substituted partial write")
        return original_write(descriptor, content)

    monkeypatch.setattr(prepare.os, "write", substituted_write)
    try:
        with pytest.raises(OSError, match="injected substituted"):
            prepare._exclusive_write_at(
                parent_descriptor,
                "handoff.json",
                b'{"status":"pass"}\n',
                mode=0o600,
            )
    finally:
        os.close(parent_descriptor)

    assert not os.path.lexists(parent / "handoff.json")
    preserved = parent / preserved_name
    assert preserved.stat().st_size == 0
    assert stat.S_IMODE(preserved.stat().st_mode) == 0o000
    attacker_quarantines = tuple(
        path
        for path in parent.iterdir()
        if path != preserved and path.name.startswith(".handoff.json.")
    )
    assert len(attacker_quarantines) == 1
    assert attacker_quarantines[0].read_bytes() == b"attacker-partial"
    assert stat.S_IMODE(attacker_quarantines[0].stat().st_mode) == 0o600
    preserved.chmod(0o600)


def test_exclusive_write_retries_until_all_short_writes_complete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = tmp_path / "receipts"
    parent.mkdir()
    parent_descriptor = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
    original_write = prepare.os.write
    calls = 0

    def short_write(descriptor, content):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        return original_write(descriptor, content[: max(1, len(content) // 2)])

    monkeypatch.setattr(prepare.os, "write", short_write)
    content = b'{"status":"pass","complete":true}\n'
    try:
        prepare._exclusive_write_at(
            parent_descriptor,
            "handoff.json",
            content,
            mode=0o600,
        )
    finally:
        os.close(parent_descriptor)

    assert calls > 1
    assert (parent / "handoff.json").read_bytes() == content


@pytest.mark.parametrize(
    "case",
    [
        "bundle_under_source",
        "receipt_under_source",
        "bundle_equal_authority",
        "receipt_equal_authority",
        "bundle_under_authority",
        "receipt_under_authority",
    ],
)
def test_materializer_never_places_ea_outputs_in_property_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    source, authority, source_snapshot = _build_property_package(
        tmp_path, monkeypatch
    )
    bundle_target = tmp_path / "handoff" / SLUG
    receipt_target = tmp_path / "handoff" / "handoff.json"
    if case == "bundle_under_source":
        bundle_target = source / "ea-output" / SLUG
    elif case == "receipt_under_source":
        receipt_target = source / "ea-output.json"
    elif case == "bundle_equal_authority":
        bundle_target = authority
    elif case == "receipt_equal_authority":
        receipt_target = authority
    elif case == "bundle_under_authority":
        bundle_target = authority / SLUG
    else:
        receipt_target = authority / "ea-output.json"

    authority_bytes = authority.read_bytes()
    with pytest.raises(ValueError, match="materialization_target_invalid"):
        prepare.materialize_spatial_handoff(
            source_bundle_dir=source,
            upstream_authority_receipt_path=authority,
            handoff_bundle_dir=bundle_target,
            handoff_receipt_path=receipt_target,
            target_origin=TARGET_ORIGIN,
        )
    assert prepare._spatial_tree_snapshot(
        source,
        require_sanitized_modes=True,
    ) == source_snapshot
    assert authority.read_bytes() == authority_bytes


def test_spatial_tree_snapshot_rejects_root_swap_to_symlink_race(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, _authority, _snapshot = _build_property_package(tmp_path, monkeypatch)
    moved = bundle.with_name(f"{bundle.name}-opened")
    original_stat = prepare.os.stat
    swapped = False

    def racing_stat(path, *args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal swapped
        if (
            not swapped
            and kwargs.get("dir_fd") is None
            and kwargs.get("follow_symlinks") is False
            and os.path.abspath(os.fspath(path)) == os.path.abspath(os.fspath(bundle))
        ):
            bundle.rename(moved)
            bundle.symlink_to(moved, target_is_directory=True)
            swapped = True
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(prepare.os, "stat", racing_stat)
    with pytest.raises(ValueError, match="spatial_root_invalid"):
        prepare._spatial_tree_snapshot(bundle, require_sanitized_modes=True)
    assert swapped is True


@pytest.mark.parametrize("swap_point", ["before_open", "after_walk"])
def test_spatial_tree_snapshot_rejects_nested_directory_swap_to_symlink_race(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    swap_point: str,
) -> None:
    bundle, _authority, _snapshot = _build_property_package(tmp_path, monkeypatch)
    nested = bundle / "generated-reconstruction"
    moved = bundle / "generated-reconstruction-opened"
    attacker = tmp_path / "attacker"
    attacker.mkdir()
    swapped = False

    def swap() -> None:
        nonlocal swapped
        nested.rename(moved)
        nested.symlink_to(attacker, target_is_directory=True)
        swapped = True

    if swap_point == "before_open":
        original_open = prepare.os.open

        def racing_open(path, flags, *args, **kwargs):  # type: ignore[no-untyped-def]
            if (
                not swapped
                and kwargs.get("dir_fd") is not None
                and os.fspath(path) == "generated-reconstruction"
            ):
                swap()
            return original_open(path, flags, *args, **kwargs)

        monkeypatch.setattr(prepare.os, "open", racing_open)
    else:
        original_stat = prepare.os.stat
        nested_stat_calls = 0

        def racing_stat(path, *args, **kwargs):  # type: ignore[no-untyped-def]
            nonlocal nested_stat_calls
            if (
                kwargs.get("dir_fd") is not None
                and kwargs.get("follow_symlinks") is False
                and os.fspath(path) == "generated-reconstruction"
            ):
                nested_stat_calls += 1
                if nested_stat_calls == 2:
                    swap()
            return original_stat(path, *args, **kwargs)

        monkeypatch.setattr(prepare.os, "stat", racing_stat)
    with pytest.raises(ValueError, match="spatial_source_changed"):
        prepare._spatial_tree_snapshot(bundle, require_sanitized_modes=True)
    assert swapped is True


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("commit", int("1" * 40)),
        ("projection_sha256", int("1" * 64)),
    ],
)
def test_projection_receipt_rejects_non_string_commit_and_digest(
    tmp_path: Path,
    field: str,
    invalid_value: object,
) -> None:
    release_root = tmp_path / "deploy" / "releases" / "release-test"
    release_root.mkdir(parents=True)
    release_root.chmod(0o550)
    receipt_path = tmp_path / "deploy" / "receipts" / "release-test.json"
    projection_sha256, projection_files = runner._tree_digest(release_root)
    payload: dict[str, object] = {
        "schema": "ea.manfred_memorial_candidate_projection.v2",
        "status": "pass",
        "release_id": release_root.name,
        "release_root": str(release_root.resolve()),
        "projection_sha256": projection_sha256,
        "commit": "b" * 40,
        "image": "ea:test",
        "image_id": f"sha256:{'c' * 64}",
        "compose_project": "ea-test",
        "projection_operator_gid": os.getgid(),
        "file_count": len(projection_files),
        "projection_bytes": 0,
    }
    payload[field] = invalid_value
    _write_private_json(receipt_path, payload)

    with pytest.raises(RuntimeError, match="projection_receipt_mismatch"):
        runner._projection_evidence(
            {
                "EA_MANFRED_RELEASE_ROOT": str(release_root),
                "EA_MANFRED_IMAGE": "ea:test",
                "EA_MANFRED_COMPOSE_PROJECT": "ea-test",
            }
        )


def test_projection_verifier_distinguishes_property_authority_from_ea_handoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, authority, _snapshot = _build_property_package(tmp_path, monkeypatch)
    validated = prepare._validated_spatial_handoff_input(
        bundle_dir=source,
        authority_receipt_path=authority,
        target_origin=TARGET_ORIGIN,
    )
    release_id = "release-test"
    release_root = tmp_path / "deploy" / "releases" / release_id
    spatial_root = release_root / "public_property_tours"
    shutil.copytree(source, spatial_root / SLUG)
    prepare._set_modes(release_root)
    spatial_digest, spatial_files = prepare._tree_digest(spatial_root)
    receipt_path = tmp_path / "deploy" / "receipts" / f"{release_id}.spatial.json"
    receipt = {
        "schema": prepare.SPATIAL_PROJECTION_SCHEMA,
        "status": "pass",
        "release_id": release_id,
        "spatial_handoff_included": True,
        "candidate_handoff_authorized": True,
        "public_activation_authority": False,
        "slug": SLUG,
        "spatial_release_root": str(spatial_root.resolve()),
        "spatial_projection_sha256": spatial_digest,
        "file_count": len(spatial_files),
        "projection_bytes": sum(int(row["size_bytes"]) for row in spatial_files),
        "files": spatial_files,
        "asset_paths": validated["asset_paths"],
        "viewer_relpath": validated["viewer_relpath"],
        "proof_relpath": validated["proof_relpath"],
        "route_labels": validated["route_labels"],
        "upstream_publication_authority": validated[
            "upstream_publication_authority"
        ],
        "upstream_publication_authority_sha256": validated[
            "upstream_publication_authority_sha256"
        ],
        "upstream_public_activation_authority": True,
        "upstream_package_sha256": validated["upstream_package_sha256"],
        "upstream_tour_manifest_sha256": validated[
            "upstream_tour_manifest_sha256"
        ],
        "pre_authority_manifest_canonical_sha256": validated[
            "pre_authority_manifest_canonical_sha256"
        ],
        "review_evidence": validated["review_evidence"],
        "source_verifier": validated["verifier_receipt"],
    }
    receipt_path.parent.mkdir(parents=True)
    receipt_bytes = prepare._receipt_bytes(receipt)
    receipt_path.write_bytes(receipt_bytes)
    receipt_path.chmod(0o600)
    projection_receipt = {
        "spatial_receipt_path": str(receipt_path.resolve()),
        "spatial_receipt_sha256": hashlib.sha256(receipt_bytes).hexdigest(),
        "spatial_release_root": str(spatial_root.resolve()),
        "spatial_handoff_included": True,
        "spatial_slug": SLUG,
        "spatial_projection_sha256": spatial_digest,
        "spatial_file_count": len(spatial_files),
        "spatial_projection_bytes": sum(
            int(row["size_bytes"]) for row in spatial_files
        ),
        "spatial_upstream_public_activation_authority": True,
        "spatial_ea_public_activation_authority": False,
    }
    evidence = runner._spatial_projection_evidence(
        {
            "EA_MANFRED_SPATIAL_RELEASE_ROOT": str(spatial_root.resolve()),
            "EA_MANFRED_SPATIAL_HANDOFF_INCLUDED": "1",
            "EA_MANFRED_SPATIAL_SLUG": SLUG,
            "EA_MANFRED_SPATIAL_SHA256": spatial_digest,
            "EA_PUBLIC_APP_BASE_URL": TARGET_ORIGIN,
        },
        projection_receipt=projection_receipt,
        release_root=release_root.resolve(),
        release_id=release_id,
    )
    assert evidence["upstream_public_activation_authority"] is True
    assert evidence["ea_public_activation_authority"] is False
    assert evidence["upstream_package_sha256"] == validated[
        "upstream_package_sha256"
    ]


def test_property_bundle_serves_html_json_viewer_and_hides_proof_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, _authority, _snapshot = _build_property_package(tmp_path, monkeypatch)
    monkeypatch.setattr(public_tours, "_tour_dir", lambda: bundle.parent)
    page = public_tours.public_tour_page(
        SLUG, _request(f"/tours/{SLUG}"), container=object()
    )
    payload = public_tours.public_tour_payload(SLUG)
    viewer = public_tours.public_tour_generated_viewer_file(
        SLUG, "generated-reconstruction/viewer.html"
    )
    assert page.status_code == 200
    assert payload.status_code == 200
    assert viewer.status_code == 200
    assert (
        json.loads(payload.body)["generated_viewer"]["url"]
        == f"/tours/viewer/{SLUG}/generated-reconstruction/viewer.html"
    )
    with pytest.raises(HTTPException) as blocked:
        public_tours.public_tour_generated_viewer_file(
            SLUG, "generated-reconstruction/reconstruction.json"
        )
    assert blocked.value.status_code == 404


def test_spatial_runtime_smoke_requires_html_json_viewer_and_proof_only_404(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, _authority, _snapshot = _build_property_package(tmp_path, monkeypatch)
    paths: list[tuple[str, str, int]] = []

    def probe(  # type: ignore[no-untyped-def]
        _base_url, path, *, method, expected_status, accept="*/*"
    ):
        del accept
        paths.append((method, path, expected_status))
        if path.endswith(".json") and "/viewer/" not in path and method == "GET":
            return (
                json.dumps(
                    {
                        "generated_viewer": {
                            "url": (
                                f"/tours/viewer/{SLUG}/"
                                "generated-reconstruction/viewer.html"
                            )
                        }
                    }
                ).encode(),
                {"content-type": "application/json"},
            )
        return b"", {"content-type": "text/html"}

    monkeypatch.setattr(runner, "_spatial_http_probe", probe)
    monkeypatch.setattr(
        runner,
        "verify_spatial_bundle",
        lambda *_args, **_kwargs: {"pass": True, "status": "pass"},
    )
    monkeypatch.setattr(
        runner,
        "audit_spatial_candidate_browser",
        lambda **_kwargs: {
            "status": "pass",
            "all_route_stops_interacted": True,
            "camera_state_changes_verified": True,
            "required_asset_requests_verified": True,
            "secret_material_recorded": False,
        },
    )
    validated: list[dict[str, object]] = []

    def validate_receipt(receipt, **kwargs):  # type: ignore[no-untyped-def]
        validated.append(dict(kwargs))
        assert receipt["secret_material_recorded"] is False
        return receipt

    monkeypatch.setattr(
        runner,
        "validate_spatial_candidate_browser_receipt",
        validate_receipt,
    )
    projection: dict[str, object] = {
        "projection_commit": "e" * 40,
        "spatial_handoff": {
            "included": True,
            "slug": SLUG,
            "release_root": str(bundle.parent),
            "viewer_relpath": "generated-reconstruction/viewer.html",
            "proof_relpath": "generated-reconstruction/reconstruction.json",
            "route_labels": ROUTE_LABELS,
            "upstream_package_sha256": "f" * 64,
        },
    }
    proof = runner._spatial_handoff_runtime_proof(
        "http://127.0.0.1:18090",
        projection,
    )
    assert proof["html_json_viewer_200"] is True
    assert proof["proof_only_404"] is True
    assert proof["candidate_browser_gate"]["secret_material_recorded"] is False
    assert proof["ea_public_activation_authority"] is False
    assert proof["upstream_public_activation_authority"] is True
    assert validated == [
        {
            "base_url": "http://127.0.0.1:18090",
            "slug": SLUG,
            "viewer_relpath": "generated-reconstruction/viewer.html",
            "route_labels": ROUTE_LABELS,
            "candidate_commit": "e" * 40,
            "package_sha256": "f" * 64,
        }
    ]
    assert len(paths) == 8
    assert {
        status
        for _method, path, status in paths
        if path.endswith("reconstruction.json")
    } == {404}
    for field, invalid_value in (
        ("projection_commit", int("1" * 40)),
        ("upstream_package_sha256", int("1" * 64)),
    ):
        invalid_projection = dict(projection)
        invalid_spatial = dict(projection["spatial_handoff"])
        if field == "projection_commit":
            invalid_projection[field] = invalid_value
        else:
            invalid_spatial[field] = invalid_value
        invalid_projection["spatial_handoff"] = invalid_spatial
        with pytest.raises(RuntimeError, match="spatial_runtime_contract_invalid"):
            runner._spatial_handoff_runtime_proof(
                "http://127.0.0.1:18090",
                invalid_projection,
            )


def test_spatial_runtime_rejects_boolean_only_browser_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, _authority, _snapshot = _build_property_package(
        tmp_path, monkeypatch
    )

    def probe(  # type: ignore[no-untyped-def]
        _base_url, path, *, method, expected_status, accept="*/*"
    ):
        del method, expected_status, accept
        if path.endswith(".json") and "/viewer/" not in path:
            return (
                json.dumps(
                    {
                        "generated_viewer": {
                            "url": (
                                f"/tours/viewer/{SLUG}/"
                                "generated-reconstruction/viewer.html"
                            )
                        }
                    }
                ).encode("utf-8"),
                {"content-type": "application/json"},
            )
        return b"", {"content-type": "text/html"}

    monkeypatch.setattr(runner, "_spatial_http_probe", probe)
    monkeypatch.setattr(
        runner,
        "verify_spatial_bundle",
        lambda *_args, **_kwargs: {"pass": True, "status": "pass"},
    )
    monkeypatch.setattr(
        runner,
        "audit_spatial_candidate_browser",
        lambda **_kwargs: {
            "status": "pass",
            "all_route_stops_interacted": True,
            "camera_state_changes_verified": True,
            "required_asset_requests_verified": True,
            "secret_material_recorded": False,
        },
    )

    with pytest.raises(RuntimeError, match="browser_gate_blocked"):
        runner._spatial_handoff_runtime_proof(
            "http://127.0.0.1:18090",
            {
                "projection_commit": "e" * 40,
                "spatial_handoff": {
                    "included": True,
                    "slug": SLUG,
                    "release_root": str(bundle.parent),
                    "viewer_relpath": (
                        "generated-reconstruction/viewer.html"
                    ),
                    "proof_relpath": (
                        "generated-reconstruction/reconstruction.json"
                    ),
                    "route_labels": ROUTE_LABELS,
                    "upstream_package_sha256": "f" * 64,
                },
            },
        )
