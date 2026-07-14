from __future__ import annotations

import hashlib
import json
from pathlib import Path
import stat

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.api.routes import public_tours
from app.services.public_tour_release_policy import (
    PUBLIC_TOUR_GENERATED_VIEWER_RELEASE_CONTRACT,
)
from scripts import prepare_manfred_memorial_candidate as prepare
from scripts import run_manfred_memorial_candidate as runner
from scripts import verify_public_tour_generated_viewer_release as verifier


SLUG = "generated-viewer-tour"
TARGET_ORIGIN = "https://myexternalbrain.com"
SOURCE_COMMIT = "a" * 40
USER_INSTRUCTION_SHA256 = "b" * 64


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


def _assets() -> dict[str, bytes]:
    return {
        "generated-reconstruction/viewer.html": (
            b"<!doctype html><canvas aria-label='Layout'></canvas>"
        ),
        "generated-reconstruction/reconstruction.json": (
            b'{"viewer_version":"propertyquarry_3d_tour_viewer_v3",'
            b'"floorplan":{"source_path":"pcloud://property/source/floorplan.png"}}'
        ),
        "generated-reconstruction/source-floorplan.png": b"floorplan-png",
        "generated-reconstruction/vendor/three.module.js": (
            b"export const Scene = class {};"
        ),
        "generated-reconstruction/vendor/examples/jsm/controls/OrbitControls.js": (
            b"export class OrbitControls {}"
        ),
    }


def _raw_payload() -> dict[str, object]:
    assets = _assets()
    roles = {
        "generated-reconstruction/viewer.html": ("text/html", "viewer_document"),
        "generated-reconstruction/reconstruction.json": (
            "application/json",
            "reconstruction_manifest",
        ),
        "generated-reconstruction/source-floorplan.png": (
            "image/png",
            "floorplan_texture",
        ),
        "generated-reconstruction/vendor/three.module.js": (
            "text/javascript",
            "viewer_module",
        ),
        "generated-reconstruction/vendor/examples/jsm/controls/OrbitControls.js": (
            "text/javascript",
            "viewer_module",
        ),
    }
    return {
        "slug": SLUG,
        "title": "Flagship layout tour",
        "display_title": "Flagship layout tour",
        "creation_mode": "generated_3d_reconstruction",
        "scene_strategy": "layout_first_generated_reconstruction",
        "principal_id": "must-not-survive-sanitization",
        "recipient_email": "must-not-survive@example.test",
        "facts": {"exact_address": "must-not-survive", "rooms": 3},
        "scenes": [{"asset_relpath": "private/raw-photo.jpg"}],
        "generated_reconstruction": {
            "provider": "propertyquarry_generated_reconstruction",
            "verified_provider_capture": False,
            "satisfies_verified_tour_gate": False,
            "viewer_version": "propertyquarry_3d_tour_viewer_v3",
            "viewer_relpath": "generated-reconstruction/viewer.html",
            "manifest_relpath": "generated-reconstruction/reconstruction.json",
            "floorplan_relpath": "generated-reconstruction/source-floorplan.png",
            "photo_reference_panel_count": 0,
        },
        "generated_viewer_release": {
            "contract": PUBLIC_TOUR_GENERATED_VIEWER_RELEASE_CONTRACT,
            "status": "ready",
            "provider": "propertyquarry_generated_reconstruction",
            "viewer_relpath": "generated-reconstruction/viewer.html",
            "asset_bindings": [
                {
                    "path": path,
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "size_bytes": len(content),
                    "mime_type": roles[path][0],
                    "role": roles[path][1],
                }
                for path, content in assets.items()
            ],
            "browser_receipt_sha256": "1" * 64,
            "source_provenance_receipt_sha256": "2" * 64,
            "publication_authority_receipt_sha256": None,
            "security_review_receipt_sha256": "4" * 64,
            "accessibility_review_receipt_sha256": "5" * 64,
            "browser_interaction_verified": True,
            "visual_quality_review_passed": True,
            "security_review_passed": True,
            "accessibility_review_passed": True,
            "source_provenance_verified": True,
            "publication_authority_verified": True,
            "release_revision": "release-2026-07-14.1",
            "disclosure": (
                "Generated interactive reconstruction; not a captured or "
                "provider-verified 3D scan."
            ),
            "revoked": False,
            "disqualified": False,
        },
    }


def _write_raw_bundle(tmp_path: Path) -> Path:
    bundle = tmp_path / "raw" / SLUG
    bundle.mkdir(parents=True, mode=0o700)
    for relpath, content in _assets().items():
        target = bundle / relpath
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        target.write_bytes(content)
        target.chmod(0o600)
    (bundle / "tour.json").write_text(json.dumps(_raw_payload()), encoding="utf-8")
    (bundle / "tour.json").chmod(0o600)
    extra = bundle / "generated-reconstruction" / "model.obj"
    extra.write_bytes(b"safe raw input ignored by the positive allowlist")
    extra.chmod(0o600)
    return bundle


def _materialize(tmp_path: Path) -> tuple[Path, Path, dict[str, object]]:
    raw = _write_raw_bundle(tmp_path)
    sanitized = tmp_path / "sanitized" / SLUG
    authority = tmp_path / "receipts" / "spatial-authority.json"
    receipt = prepare.materialize_spatial_handoff_authority(
        source_bundle_dir=raw,
        sanitized_bundle_dir=sanitized,
        authority_receipt_path=authority,
        slug=SLUG,
        source_commit=SOURCE_COMMIT,
        target_origin=TARGET_ORIGIN,
        user_instruction_sha256=USER_INSTRUCTION_SHA256,
    )
    return sanitized, authority, receipt


def test_materializer_emits_exact_sanitized_bundle_and_bound_private_receipt(
    tmp_path: Path,
) -> None:
    sanitized, authority, receipt = _materialize(tmp_path)

    assert stat.S_IMODE(authority.stat().st_mode) == 0o600
    assert receipt["public_activation_authority"] is False
    assert receipt["scope"] == prepare.SPATIAL_AUTHORITY_SCOPE
    assert receipt["sanitized_file_count"] == 6
    assert (
        receipt["authority_receipt_sha256"]
        == hashlib.sha256(authority.read_bytes()).hexdigest()
    )
    files = {
        path.relative_to(sanitized).as_posix()
        for path in sanitized.rglob("*")
        if path.is_file()
    }
    assert files == {"tour.json", *_assets().keys()}
    assert all(
        stat.S_IMODE(path.stat().st_mode) == 0o644
        for path in sanitized.rglob("*")
        if path.is_file()
    )
    final_manifest = json.loads((sanitized / "tour.json").read_bytes())
    assert "principal_id" not in final_manifest
    assert "recipient_email" not in final_manifest
    assert final_manifest["facts"] == {}
    assert final_manifest["scenes"] == []
    assert (
        final_manifest["generated_viewer_release"][
            "publication_authority_receipt_sha256"
        ]
        == receipt["authority_receipt_sha256"]
    )
    assert verifier.verify_bundle(sanitized, slug=SLUG)["pass"] is True
    validated = prepare._validated_spatial_handoff_input(
        bundle_dir=sanitized,
        authority_receipt_path=authority,
        target_origin=TARGET_ORIGIN,
    )
    assert validated["slug"] == SLUG
    assert validated["authority_receipt_sha256"] == receipt["authority_receipt_sha256"]


def test_materializer_is_deterministic_for_identical_inputs(tmp_path: Path) -> None:
    first_bundle, first_authority, _first = _materialize(tmp_path / "first")
    second_bundle, second_authority, _second = _materialize(tmp_path / "second")

    assert first_authority.read_bytes() == second_authority.read_bytes()
    assert {
        path.relative_to(first_bundle).as_posix(): path.read_bytes()
        for path in first_bundle.rglob("*")
        if path.is_file()
    } == {
        path.relative_to(second_bundle).as_posix(): path.read_bytes()
        for path in second_bundle.rglob("*")
        if path.is_file()
    }


def test_immutable_0550_0444_projection_remains_verifiable(tmp_path: Path) -> None:
    sanitized, _authority, _receipt = _materialize(tmp_path)
    prepare._set_modes(sanitized)

    result = verifier.verify_bundle(sanitized, slug=SLUG)

    assert stat.S_IMODE(sanitized.stat().st_mode) == 0o550
    assert result["pass"] is True


def test_sanitized_bundle_serves_html_json_viewer_and_hides_proof_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sanitized, _authority, _receipt = _materialize(tmp_path)
    monkeypatch.setattr(public_tours, "_tour_dir", lambda: sanitized.parent)

    page = public_tours.public_tour_page(
        SLUG,
        _request(f"/tours/{SLUG}"),
        container=object(),
    )
    payload = public_tours.public_tour_payload(SLUG)
    viewer = public_tours.public_tour_generated_viewer_file(
        SLUG,
        "generated-reconstruction/viewer.html",
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
            SLUG,
            "generated-reconstruction/reconstruction.json",
        )
    assert blocked.value.status_code == 404


def test_authority_normalization_and_exact_bundle_tamper_fail_closed(
    tmp_path: Path,
) -> None:
    sanitized, authority, _receipt = _materialize(tmp_path)
    payload = json.loads((sanitized / "tour.json").read_bytes())
    payload["title"] = "retargeted after authority"
    (sanitized / "tour.json").write_bytes(prepare._canonical_json_bytes(payload))

    with pytest.raises(
        ValueError,
        match="spatial_authority_receipt_mismatch",
    ):
        prepare._validated_spatial_handoff_input(
            bundle_dir=sanitized,
            authority_receipt_path=authority,
            target_origin=TARGET_ORIGIN,
        )


@pytest.mark.parametrize(
    "case",
    ["private_path", "symlink", "root_symlink", "unsafe_mode", "oversize"],
)
def test_spatial_intake_rejects_private_paths_links_modes_and_oversize(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    if case in {"private_path", "symlink", "root_symlink"}:
        raw = _write_raw_bundle(tmp_path)
        if case == "private_path":
            forbidden = raw / "private" / "raw-export.json"
            forbidden.parent.mkdir()
            forbidden.write_text("{}", encoding="utf-8")
            forbidden.chmod(0o600)
        elif case == "symlink":
            (raw / "linked-viewer.html").symlink_to(
                raw / "generated-reconstruction" / "viewer.html"
            )
        else:
            linked_root = tmp_path / "linked-root"
            linked_root.symlink_to(raw, target_is_directory=True)
            raw = linked_root
        with pytest.raises(ValueError, match="spatial_"):
            prepare.materialize_spatial_handoff_authority(
                source_bundle_dir=raw,
                sanitized_bundle_dir=tmp_path / "sanitized" / SLUG,
                authority_receipt_path=tmp_path / "authority.json",
                slug=SLUG,
                source_commit=SOURCE_COMMIT,
                target_origin=TARGET_ORIGIN,
                user_instruction_sha256=USER_INSTRUCTION_SHA256,
            )
        return

    sanitized, authority, _receipt = _materialize(tmp_path)
    viewer = sanitized / "generated-reconstruction" / "viewer.html"
    if case == "unsafe_mode":
        viewer.chmod(0o666)
    else:
        monkeypatch.setattr(prepare, "MAX_SPATIAL_FILE_BYTES", 8)
    with pytest.raises(ValueError, match="spatial_"):
        prepare._validated_spatial_handoff_input(
            bundle_dir=sanitized,
            authority_receipt_path=authority,
            target_origin=TARGET_ORIGIN,
        )


def test_spatial_runtime_smoke_requires_html_json_viewer_and_proof_only_404(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sanitized, _authority, _receipt = _materialize(tmp_path)
    paths: list[tuple[str, str, int]] = []

    def probe(  # type: ignore[no-untyped-def]
        _base_url,
        path,
        *,
        method,
        expected_status,
        accept="*/*",
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
    proof = runner._spatial_handoff_runtime_proof(
        "http://127.0.0.1:18090",
        {
            "spatial_handoff": {
                "included": True,
                "slug": SLUG,
                "release_root": str(sanitized.parent),
                "viewer_relpath": "generated-reconstruction/viewer.html",
                "proof_relpath": "generated-reconstruction/reconstruction.json",
            }
        },
    )

    assert proof["html_json_viewer_200"] is True
    assert proof["proof_only_404"] is True
    assert proof["public_activation_authority"] is False
    assert len(paths) == 8
    assert {
        status
        for _method, path, status in paths
        if path.endswith("reconstruction.json")
    } == {404}
