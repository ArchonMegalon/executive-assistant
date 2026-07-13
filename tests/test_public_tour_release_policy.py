from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

import pytest
from fastapi import HTTPException

from app.api.routes import public_tours
from app.services.public_tour_release_policy import (
    PUBLIC_TOUR_EMBED_RELEASE_CONTRACT,
    PUBLIC_TOUR_GENERATED_VIEWER_RELEASE_CONTRACT,
    PUBLIC_TOUR_VIDEO_RELEASE_CONTRACT,
    evaluate_public_tour_embed_release,
    evaluate_public_tour_generated_viewer_release,
    evaluate_public_tour_video_release,
    safe_public_navigation_url,
)


def _generated_video_source_manifest(
    *, source_path: str = "pcloud://propertyquarry/source/floorplan.jpg"
) -> bytes:
    return json.dumps(
        {
            "provider": "propertyquarry_generated_reconstruction",
            "floorplan": {"source_path": source_path},
            "photos": [
                {"source_path": "pcloud://propertyquarry/source/living-room.jpg"}
            ],
        },
        sort_keys=True,
    ).encode("utf-8")


def _generated_video_payload(
    video: bytes = b"reviewed-generated-video",
    source_manifest: bytes | None = None,
) -> dict[str, object]:
    source_manifest = source_manifest or _generated_video_source_manifest()
    disclosure = "Generated layout preview, not a captured provider tour."
    return {
        "slug": "generated-tour",
        "video_relpath": "generated-reconstruction/generated-walkthrough.mp4",
        "video_provider": "propertyquarry_generated_reconstruction",
        "generated_reconstruction": {
            "provider": "propertyquarry_generated_reconstruction",
            "verified_provider_capture": False,
            "satisfies_verified_tour_gate": False,
            "walkthrough_video_relpath": "generated-reconstruction/generated-walkthrough.mp4",
            "manifest_relpath": "generated-reconstruction/reconstruction.json",
            "walkthrough_route_labels": ["entry", "living room"],
            "disclosure": disclosure,
            "walkthrough_coverage_proof": {
                "status": "pass",
                "source": "propertyquarry_generated_reconstruction_viewer_capture",
                "segments_expected": ["entry", "living room"],
                "segments_visited": ["entry", "living room"],
            },
        },
        "video_release": {
            "contract": PUBLIC_TOUR_VIDEO_RELEASE_CONTRACT,
            "status": "ready",
            "provider": "propertyquarry_generated_reconstruction",
            "asset_relpath": "generated-reconstruction/generated-walkthrough.mp4",
            "asset_sha256": hashlib.sha256(video).hexdigest(),
            "asset_size_bytes": len(video),
            "review_receipt_sha256": "6" * 64,
            "publication_authority_receipt_sha256": "7" * 64,
            "source_manifest_sha256": hashlib.sha256(source_manifest).hexdigest(),
            "source_provenance_receipt_sha256": "8" * 64,
            "provider_output_verified": True,
            "quality_review_passed": True,
            "publication_authority_verified": True,
            "source_provenance_reviewed": True,
            "release_revision": "video-release-2026-07-13.1",
            "disclosure": disclosure,
            "synthetic": True,
            "verified_provider_capture": False,
            "satisfies_verified_tour_gate": False,
            "revoked": False,
            "disqualified": False,
        },
    }


def _released_magicfit_payload(video: bytes = b"reviewed-video") -> dict[str, object]:
    return {
        "slug": "magicfit-tour",
        "video_relpath": "tour.mp4",
        "video_provider": "magicfit",
        "video_release": {
            "contract": PUBLIC_TOUR_VIDEO_RELEASE_CONTRACT,
            "status": "ready",
            "provider": "magicfit",
            "asset_relpath": "tour.mp4",
            "asset_sha256": hashlib.sha256(video).hexdigest(),
            "asset_size_bytes": len(video),
            "review_receipt_sha256": "a" * 64,
            "publication_authority_receipt_sha256": "b" * 64,
            "provider_output_verified": True,
            "quality_review_passed": True,
            "publication_authority_verified": True,
            "release_revision": "video-release-2026-07-13.1",
            "revoked": False,
            "disqualified": False,
            "disclosure": "Reviewed synthetic MagicFit walkthrough.",
        },
    }


def _generated_viewer_assets() -> dict[str, bytes]:
    return {
        "generated-reconstruction/viewer.html": b"<!doctype html><canvas></canvas>",
        "generated-reconstruction/reconstruction.json": (
            b'{"viewer_version":"propertyquarry_3d_tour_viewer_v3",'
            b'"floorplan":{"source_path":"pcloud://propertyquarry/source/floorplan.jpg"}}'
        ),
        "generated-reconstruction/floorplan.png": b"floorplan-png",
        "generated-reconstruction/vendor/three.module.js": b"export const Scene = class {};",
        "generated-reconstruction/vendor/examples/jsm/controls/OrbitControls.js": b"export class OrbitControls {}",
        "generated-reconstruction/photos/living-room.jpg": b"living-room-jpeg",
    }


def _generated_viewer_payload() -> dict[str, object]:
    assets = _generated_viewer_assets()
    roles = {
        "generated-reconstruction/viewer.html": ("text/html", "viewer_document"),
        "generated-reconstruction/reconstruction.json": (
            "application/json",
            "reconstruction_manifest",
        ),
        "generated-reconstruction/floorplan.png": ("image/png", "floorplan_texture"),
        "generated-reconstruction/vendor/three.module.js": (
            "text/javascript",
            "viewer_module",
        ),
        "generated-reconstruction/vendor/examples/jsm/controls/OrbitControls.js": (
            "text/javascript",
            "viewer_module",
        ),
        "generated-reconstruction/photos/living-room.jpg": (
            "image/jpeg",
            "photo_texture",
        ),
    }
    return {
        "slug": "generated-viewer-tour",
        "generated_reconstruction": {
            "provider": "propertyquarry_generated_reconstruction",
            "verified_provider_capture": False,
            "satisfies_verified_tour_gate": False,
            "viewer_version": "propertyquarry_3d_tour_viewer_v3",
            "viewer_relpath": "generated-reconstruction/viewer.html",
            "manifest_relpath": "generated-reconstruction/reconstruction.json",
            "floorplan_relpath": "generated-reconstruction/floorplan.png",
            "photo_relpaths": ["generated-reconstruction/photos/living-room.jpg"],
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
            "publication_authority_receipt_sha256": "3" * 64,
            "security_review_receipt_sha256": "4" * 64,
            "accessibility_review_receipt_sha256": "5" * 64,
            "browser_interaction_verified": True,
            "visual_quality_review_passed": True,
            "security_review_passed": True,
            "accessibility_review_passed": True,
            "source_provenance_verified": True,
            "publication_authority_verified": True,
            "release_revision": "release-2026-07-13.1",
            "disclosure": "Generated interactive reconstruction; not a captured or provider-verified 3D scan.",
            "revoked": False,
            "disqualified": False,
        },
    }


def _write_generated_viewer_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, dict[str, object]]:
    root = tmp_path / "public-tours"
    bundle = root / "generated-viewer-tour"
    bundle.mkdir(parents=True)
    for relpath, content in _generated_viewer_assets().items():
        target = bundle / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    payload = _generated_viewer_payload()
    (bundle / "tour.json").write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(public_tours, "_tour_dir", lambda: root)
    public_tours._public_tour_cached_file_sha256.cache_clear()
    return bundle, payload


def test_generated_viewer_release_requires_every_bound_asset_and_review_receipt() -> (
    None
):
    payload = _generated_viewer_payload()

    decision = evaluate_public_tour_generated_viewer_release(payload)

    assert decision["released"] is True
    assert decision["viewer_relpath"] == "generated-reconstruction/viewer.html"
    assert set(decision["bindings"]) == set(_generated_viewer_assets())
    assert decision["synthetic"] is True
    assert decision["verified_provider_capture"] is False

    unbound = json.loads(json.dumps(payload))
    unbound["generated_viewer_release"]["asset_bindings"] = [
        row
        for row in unbound["generated_viewer_release"]["asset_bindings"]
        if row["path"] != "generated-reconstruction/vendor/three.module.js"
    ]
    assert evaluate_public_tour_generated_viewer_release(unbound) == {
        "released": False,
        "reason": "generated_viewer_release_unverified",
        "viewer_relpath": "",
        "bindings": {},
    }

    malformed_binding = json.loads(json.dumps(payload))
    malformed_binding["generated_viewer_release"]["asset_bindings"][0]["sha256"] = (
        "not-a-digest"
    )
    assert (
        evaluate_public_tour_generated_viewer_release(malformed_binding)["released"]
        is False
    )

    extra_binding = json.loads(json.dumps(payload))
    extra_binding["generated_viewer_release"]["asset_bindings"].append(
        {
            "path": "generated-reconstruction/photos/unrelated-private-export.jpg",
            "sha256": "9" * 64,
            "size_bytes": 99,
            "mime_type": "image/jpeg",
            "role": "photo_texture",
        }
    )
    assert (
        evaluate_public_tour_generated_viewer_release(extra_binding)["released"]
        is False
    )


@pytest.mark.parametrize(
    ("field", "missing_value"),
    [
        ("browser_interaction_verified", False),
        ("visual_quality_review_passed", False),
        ("security_review_passed", False),
        ("accessibility_review_passed", False),
        ("source_provenance_verified", False),
        ("publication_authority_verified", False),
        ("browser_receipt_sha256", ""),
        ("source_provenance_receipt_sha256", ""),
        ("publication_authority_receipt_sha256", ""),
        ("security_review_receipt_sha256", ""),
        ("accessibility_review_receipt_sha256", ""),
        ("release_revision", ""),
        ("disclosure", ""),
    ],
)
def test_generated_viewer_release_fails_closed_without_each_proof(
    field: str,
    missing_value: object,
) -> None:
    payload = _generated_viewer_payload()
    payload["generated_viewer_release"][field] = missing_value

    decision = evaluate_public_tour_generated_viewer_release(payload)

    assert decision == {
        "released": False,
        "reason": "generated_viewer_release_unverified",
        "viewer_relpath": "",
        "bindings": {},
    }


@pytest.mark.parametrize(
    ("section", "field", "tampered_value"),
    [
        ("generated_reconstruction", "verified_provider_capture", True),
        ("generated_reconstruction", "satisfies_verified_tour_gate", True),
        (
            "generated_reconstruction",
            "viewer_version",
            "propertyquarry_3d_tour_viewer_v2",
        ),
        ("generated_reconstruction", "photo_relpaths", []),
        (
            "generated_reconstruction",
            "photo_relpaths",
            ["generated-reconstruction/photos/living-room.jpg", "../unbound.jpg"],
        ),
        (
            "generated_viewer_release",
            "contract",
            "ea.public-tour-generated-viewer-release.v0",
        ),
        ("generated_viewer_release", "provider", "unreviewed_renderer"),
        (
            "generated_viewer_release",
            "viewer_relpath",
            "generated-reconstruction/other.html",
        ),
    ],
)
def test_generated_viewer_release_rejects_metadata_or_truth_claim_drift(
    section: str,
    field: str,
    tampered_value: object,
) -> None:
    payload = _generated_viewer_payload()
    payload[section][field] = tampered_value

    decision = evaluate_public_tour_generated_viewer_release(payload)

    assert decision["released"] is False
    assert decision["reason"] == "generated_viewer_release_unverified"


@pytest.mark.parametrize(
    ("terminal_field", "reason"),
    [
        ("revoked", "generated_viewer_revoked"),
        ("disqualified", "generated_viewer_disqualified"),
    ],
)
def test_generated_viewer_terminal_release_states_cannot_be_reactivated_by_valid_proof(
    terminal_field: str,
    reason: str,
) -> None:
    payload = _generated_viewer_payload()
    payload["generated_viewer_release"][terminal_field] = True

    decision = evaluate_public_tour_generated_viewer_release(payload)

    assert decision == {
        "released": False,
        "reason": reason,
        "viewer_relpath": "",
        "bindings": {},
        "terminal": True,
    }


def test_generated_viewer_route_serves_only_bound_assets_with_isolated_headers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, payload = _write_generated_viewer_bundle(tmp_path, monkeypatch)
    viewer_relpath = "generated-reconstruction/viewer.html"
    viewer_routes = [
        route
        for route in public_tours.router.routes
        if getattr(route, "path", "") == "/tours/viewer/{slug}/{asset_path:path}"
    ]

    assert {
        method for route in viewer_routes for method in (route.methods or set())
    } >= {"GET", "HEAD"}

    file_path, binding, decision = public_tours._generated_viewer_file(
        "generated-viewer-tour",
        viewer_relpath,
    )

    assert file_path == bundle / viewer_relpath
    assert binding["role"] == "viewer_document"
    assert decision["release_revision"] == "release-2026-07-13.1"

    response = public_tours.public_tour_generated_viewer_file(
        "generated-viewer-tour",
        viewer_relpath,
    )
    headers = response.headers
    csp = headers["content-security-policy"]

    assert headers["access-control-allow-origin"] == "*"
    assert headers["cache-control"] == "no-store"
    assert headers["cross-origin-resource-policy"] == "cross-origin"
    assert headers["x-content-type-options"] == "nosniff"
    assert (
        headers["x-propertyquarry-asset-sha256"]
        == hashlib.sha256(_generated_viewer_assets()[viewer_relpath]).hexdigest()
    )
    assert headers["x-propertyquarry-viewer-revision"] == "release-2026-07-13.1"
    assert headers["content-type"].startswith("text/html")
    assert "default-src 'none'" in csp
    assert "script-src 'unsafe-inline' 'self'" in csp
    assert "style-src 'unsafe-inline'" in csp
    assert "img-src 'self' data:" in csp
    assert "object-src 'none'" in csp
    assert "base-uri 'none'" in csp
    assert "form-action 'none'" in csp
    assert "frame-ancestors 'self'" in csp
    assert "https:" not in csp

    module_relpath = "generated-reconstruction/vendor/three.module.js"
    module_response = public_tours.public_tour_generated_viewer_file(
        "generated-viewer-tour",
        module_relpath,
    )
    assert module_response.headers["access-control-allow-origin"] == "*"
    assert (
        module_response.headers["cache-control"] == "public, max-age=86400, immutable"
    )
    assert "content-security-policy" not in module_response.headers
    assert module_response.headers["content-type"].startswith("text/javascript")

    photo_relpath = "generated-reconstruction/photos/living-room.jpg"
    photo_response = public_tours.public_tour_generated_viewer_file(
        "generated-viewer-tour",
        photo_relpath,
    )
    assert photo_response.headers["access-control-allow-origin"] == "*"
    assert photo_response.headers["cache-control"] == "public, max-age=86400, immutable"
    assert photo_response.headers["content-type"] == "image/jpeg"

    redacted = public_tours._redacted_public_tour_payload(payload)
    assert redacted["generated_viewer"] == {
        "url": "/tours/viewer/generated-viewer-tour/generated-reconstruction/viewer.html",
        "release_revision": "release-2026-07-13.1",
        "disclosure": "Generated interactive reconstruction; not a captured or provider-verified 3D scan.",
        "synthetic": True,
        "verified_provider_capture": False,
    }


def test_generated_viewer_file_fails_closed_for_unbound_proof_asset_and_digest_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, payload = _write_generated_viewer_bundle(tmp_path, monkeypatch)
    extra = bundle / "generated-reconstruction" / "unbound.js"
    extra.write_bytes(b"console.log('not released')")

    with pytest.raises(HTTPException) as unbound_error:
        public_tours._generated_viewer_file(
            "generated-viewer-tour",
            "generated-reconstruction/unbound.js",
        )
    assert unbound_error.value.status_code == 404

    with pytest.raises(HTTPException) as proof_error:
        public_tours._generated_viewer_file(
            "generated-viewer-tour",
            "generated-reconstruction/reconstruction.json",
        )
    assert proof_error.value.status_code == 404

    viewer_relpath = "generated-reconstruction/viewer.html"
    (bundle / viewer_relpath).write_bytes(b"<!doctype html><p>tampered viewer</p>")
    public_tours._public_tour_cached_file_sha256.cache_clear()
    with pytest.raises(HTTPException) as tamper_error:
        public_tours._generated_viewer_file("generated-viewer-tour", viewer_relpath)
    assert tamper_error.value.status_code == 410
    assert tamper_error.value.detail == "tour_viewer_integrity_failed"

    (bundle / viewer_relpath).write_bytes(_generated_viewer_assets()[viewer_relpath])
    payload["generated_viewer_release"]["asset_bindings"][0]["sha256"] = "f" * 64
    (bundle / "tour.json").write_text(json.dumps(payload), encoding="utf-8")
    public_tours._public_tour_cached_file_sha256.cache_clear()
    with pytest.raises(HTTPException) as digest_error:
        public_tours._generated_viewer_file("generated-viewer-tour", viewer_relpath)
    assert digest_error.value.status_code == 410
    assert digest_error.value.detail == "tour_viewer_integrity_failed"


def test_generated_viewer_route_rejects_tmp_or_test_source_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, payload = _write_generated_viewer_bundle(tmp_path, monkeypatch)
    manifest_relpath = "generated-reconstruction/reconstruction.json"
    unsafe_manifest = (
        b'{"viewer_version":"propertyquarry_3d_tour_viewer_v3",'
        b'"floorplan":{"source_path":"/tmp/pytest-of-user/test_viewer/floorplan.jpg"}}'
    )
    (bundle / manifest_relpath).write_bytes(unsafe_manifest)
    manifest_binding = next(
        row
        for row in payload["generated_viewer_release"]["asset_bindings"]
        if row["path"] == manifest_relpath
    )
    manifest_binding["sha256"] = hashlib.sha256(unsafe_manifest).hexdigest()
    manifest_binding["size_bytes"] = len(unsafe_manifest)
    (bundle / "tour.json").write_text(json.dumps(payload), encoding="utf-8")
    public_tours._public_tour_cached_file_sha256.cache_clear()

    assert evaluate_public_tour_generated_viewer_release(payload)["released"] is True
    with pytest.raises(HTTPException) as provenance_error:
        public_tours._generated_viewer_file(
            "generated-viewer-tour",
            "generated-reconstruction/viewer.html",
        )
    assert provenance_error.value.status_code == 410
    assert provenance_error.value.detail == "tour_viewer_integrity_failed"


def test_generated_viewer_revocation_is_terminal_at_the_file_route(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, payload = _write_generated_viewer_bundle(tmp_path, monkeypatch)
    payload["generated_viewer_release"]["revoked"] = True
    (bundle / "tour.json").write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(HTTPException) as revoked_error:
        public_tours.public_tour_generated_viewer_file(
            "generated-viewer-tour",
            "generated-reconstruction/viewer.html",
        )

    assert revoked_error.value.status_code == 410
    assert revoked_error.value.detail == "tour_viewer_no_longer_available"


def test_parent_tour_embeds_released_viewer_without_same_origin_authority() -> None:
    payload = {
        "slug": "generated-viewer-tour",
        "title": "Generated Viewer Tour",
        "brand_name": "PropertyQuarry",
        "facts": {},
        "brief": {},
        "scenes": [
            {
                "name": "Living room",
                "role": "photo",
                "asset_relpath": "generated-reconstruction/photos/living-room.jpg",
                "mime_type": "image/jpeg",
            }
        ],
        "_released_generated_viewer_url": (
            "/tours/viewer/generated-viewer-tour/generated-reconstruction/viewer.html"
        ),
        "_tour_media_disclosure": (
            "Generated interactive reconstruction; not a captured or provider-verified 3D scan."
        ),
    }

    rendered = public_tours._harden_public_tour_html(
        public_tours._tour_html(payload),
        payload,
    )
    iframe_match = re.search(
        r'<iframe\s+[^>]*id="generated-tour-viewer"[^>]*>',
        rendered,
        flags=re.DOTALL,
    )

    assert iframe_match is not None
    iframe = iframe_match.group(0)
    assert 'sandbox="allow-scripts"' in iframe
    assert "allow-same-origin" not in iframe
    assert 'aria-describedby="generated-viewer-disclosure"' in iframe
    assert (
        'src="/tours/viewer/generated-viewer-tour/generated-reconstruction/viewer.html"'
        in iframe
    )
    assert (
        'href="#generated-3d-viewer">Open interactive 3D reconstruction</a>' in rendered
    )
    assert "not a captured or provider-verified 3D scan" in rendered


def test_generated_reconstruction_video_requires_consistent_truthful_coverage() -> None:
    payload = _generated_video_payload()

    decision = evaluate_public_tour_video_release(payload)

    assert decision["released"] is True
    assert decision["synthetic"] is True
    assert decision["verified_provider_capture"] is False
    public_payload = public_tours._redacted_public_tour_payload(payload)
    assert public_payload["video_release"] == {
        "contract": PUBLIC_TOUR_VIDEO_RELEASE_CONTRACT,
        "status": "ready",
        "release_revision": "video-release-2026-07-13.1",
        "asset_sha256": hashlib.sha256(b"reviewed-generated-video").hexdigest(),
        "disclosure": "Generated layout preview, not a captured provider tour.",
        "synthetic": True,
        "verified_provider_capture": False,
    }

    tampered = json.loads(json.dumps(payload))
    tampered["generated_reconstruction"]["walkthrough_coverage_proof"][
        "segments_visited"
    ] = ["entry"]
    denied = evaluate_public_tour_video_release(tampered)
    assert denied == {
        "released": False,
        "reason": "generated_reconstruction_release_unverified",
        "relpath": "",
    }

    missing_release = json.loads(json.dumps(payload))
    missing_release.pop("video_release")
    assert evaluate_public_tour_video_release(missing_release) == {
        "released": False,
        "reason": "video_release_missing",
        "relpath": "",
    }

    misleading_disclosure = json.loads(json.dumps(payload))
    misleading_disclosure["video_release"]["disclosure"] = "Verified captured tour."
    assert (
        evaluate_public_tour_video_release(misleading_disclosure)["released"] is False
    )


@pytest.mark.parametrize(
    ("field", "blocked_value"),
    [
        ("asset_sha256", ""),
        ("asset_size_bytes", 0),
        ("review_receipt_sha256", ""),
        ("publication_authority_receipt_sha256", ""),
        ("source_manifest_sha256", ""),
        ("source_provenance_receipt_sha256", ""),
        ("provider_output_verified", False),
        ("quality_review_passed", False),
        ("publication_authority_verified", False),
        ("source_provenance_reviewed", False),
        ("release_revision", ""),
        ("synthetic", False),
        ("verified_provider_capture", True),
        ("satisfies_verified_tour_gate", True),
    ],
)
def test_generated_reconstruction_video_fails_closed_without_bound_release_evidence(
    field: str,
    blocked_value: object,
) -> None:
    payload = _generated_video_payload()
    payload["video_release"][field] = blocked_value

    decision = evaluate_public_tour_video_release(payload)

    assert decision == {
        "released": False,
        "reason": "generated_reconstruction_release_unverified",
        "relpath": "",
    }


def test_provider_video_requires_digest_bound_release_and_terminal_states_fail_closed() -> (
    None
):
    payload = _released_magicfit_payload()
    assert evaluate_public_tour_video_release(payload)["released"] is True
    public_payload = public_tours._redacted_public_tour_payload(payload)
    assert (
        public_payload["video_release"]["contract"]
        == PUBLIC_TOUR_VIDEO_RELEASE_CONTRACT
    )
    assert (
        public_payload["video_release"]["release_revision"]
        == "video-release-2026-07-13.1"
    )
    assert (
        public_payload["video_release"]["asset_sha256"]
        == hashlib.sha256(b"reviewed-video").hexdigest()
    )

    unbound = dict(payload)
    unbound.pop("video_release")
    assert (
        evaluate_public_tour_video_release(unbound)["reason"] == "video_release_missing"
    )

    revoked = json.loads(json.dumps(payload))
    revoked["video_release"]["revoked"] = True
    decision = evaluate_public_tour_video_release(revoked)
    assert decision["released"] is False
    assert decision["terminal"] is True
    assert decision["reason"] == "video_revoked"


def test_external_embed_requires_exact_reviewed_origin_and_url_digest() -> None:
    url = "https://my.matterport.com/show/?m=reviewed-model"
    payload = {
        "scene_strategy": "live_360_embed",
        "source_virtual_tour_url": url,
        "external_embed_release": {
            "contract": PUBLIC_TOUR_EMBED_RELEASE_CONTRACT,
            "status": "ready",
            "provider": "matterport",
            "final_origin": "https://my.matterport.com",
            "source_url_sha256": hashlib.sha256(url.encode("utf-8")).hexdigest(),
            "review_receipt_sha256": "b" * 64,
            "final_origin_verified": True,
            "revoked": False,
            "disqualified": False,
        },
    }

    decision = evaluate_public_tour_embed_release(payload)

    assert decision["released"] is True
    assert decision["origin"] == "https://my.matterport.com"

    redirected = json.loads(json.dumps(payload))
    redirected["external_embed_release"]["final_origin"] = "https://example.com"
    assert (
        evaluate_public_tour_embed_release(redirected)["reason"]
        == "embed_release_unverified"
    )

    hosted_cube = json.loads(json.dumps(payload))
    hosted_cube["scene_strategy"] = "pure_360_cube"
    assert (
        evaluate_public_tour_embed_release(hosted_cube)["reason"]
        == "hosted_cube_does_not_require_external_embed"
    )


@pytest.mark.parametrize(
    ("value", "production", "expected"),
    [
        ("javascript:alert(1)", True, ""),
        ("https://user:pass@example.com/path", True, ""),
        ("https://example.com:8443/path", True, ""),
        ("https://example.com:broken/path", True, ""),
        ("https://example.com/path", True, "https://example.com/path"),
        ("/tours/example", True, "/tours/example"),
        ("//evil.example/path", True, ""),
        (
            "http://127.0.0.1:8097/tours/example",
            False,
            "http://127.0.0.1:8097/tours/example",
        ),
    ],
)
def test_navigation_urls_reject_script_credentials_and_unapproved_ports(
    value: str,
    production: bool,
    expected: str,
) -> None:
    assert safe_public_navigation_url(value, production=production) == expected


def test_public_tour_html_hardening_adds_semantics_motion_and_selected_state_support() -> (
    None
):
    source = """<!doctype html><html lang="de"><head><style>:root{--accent:#123;}</style></head><body>
    <div class="shell"><iframe id="stage-frame" src="" title="Floorplan"></iframe>
    <button class="thumb active">Scene</button></div></body></html>"""

    hardened = public_tours._harden_public_tour_html(
        source,
        {
            "brand_name": "PropertyQuarry",
            "_tour_media_disclosure": "Generated reconstruction; not captured 3D.",
        },
    )

    assert '<html lang="en">' in hardened
    assert '<header class="tour-release-header">' in hardened
    assert '<nav aria-label="Tour navigation">' in hardened
    assert '<main id="main-content">' in hardened
    assert '<footer id="tour-release-notice"' in hardened
    assert ":focus-visible" in hardened
    assert "[hidden] { display: none !important; }" in hardened
    assert "prefers-reduced-motion: reduce" in hardened
    assert "aria-pressed" in hardened
    assert 'src="about:blank" sandbox=""' in hardened
    assert "not captured 3D" in hardened


def test_security_headers_bind_frames_to_exact_released_origin() -> None:
    headers = public_tours._public_tour_security_headers(
        frame_origins=("https://my.matterport.com", "https://invalid.example:broken"),
    )
    csp = headers["Content-Security-Policy"]

    assert "frame-src 'self' https://my.matterport.com;" in csp
    assert "frame-src 'self' https:;" not in csp
    assert "form-action 'self';" in csp
    assert "camera=()" in headers["Permissions-Policy"]


def test_public_asset_route_denies_undeclared_previews_and_unreleased_provider_video(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "public-tours"
    bundle = root / "magicfit-tour"
    bundle.mkdir(parents=True)
    (bundle / "tour.mp4").write_bytes(b"unreviewed")
    (bundle / "telegram-preview.png").write_bytes(b"preview")
    payload = {
        "slug": "magicfit-tour",
        "video_relpath": "tour.mp4",
        "video_provider": "magicfit",
        "scenes": [
            {
                "name": "Photo",
                "role": "photo",
                "asset_relpath": "photo.jpg",
                "mime_type": "image/jpeg",
            }
        ],
    }
    (bundle / "photo.jpg").write_bytes(b"photo")
    (bundle / "tour.json").write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(public_tours, "_tour_dir", lambda: root)

    with pytest.raises(HTTPException) as video_error:
        public_tours._asset_file("magicfit-tour", "tour.mp4")
    assert video_error.value.status_code == 404

    with pytest.raises(HTTPException) as preview_error:
        public_tours._asset_file("magicfit-tour", "telegram-preview.png")
    assert preview_error.value.status_code == 404


def test_released_provider_video_is_hash_verified_and_revocation_returns_410(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    video = b"reviewed-video"
    root = tmp_path / "public-tours"
    bundle = root / "magicfit-tour"
    bundle.mkdir(parents=True)
    (bundle / "tour.mp4").write_bytes(video)
    payload = _released_magicfit_payload(video)
    payload["scenes"] = [
        {
            "name": "Photo",
            "role": "photo",
            "asset_relpath": "photo.jpg",
            "mime_type": "image/jpeg",
        }
    ]
    (bundle / "photo.jpg").write_bytes(b"photo")
    (bundle / "tour.json").write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(public_tours, "_tour_dir", lambda: root)
    public_tours._public_tour_cached_file_sha256.cache_clear()

    assert public_tours._asset_file("magicfit-tour", "tour.mp4") == bundle / "tour.mp4"
    response = public_tours.public_tour_file("magicfit-tour", "tour.mp4")
    assert (
        response.headers["x-propertyquarry-asset-sha256"]
        == hashlib.sha256(video).hexdigest()
    )
    assert (
        response.headers["x-propertyquarry-media-revision"]
        == "video-release-2026-07-13.1"
    )

    (bundle / "tour.mp4").write_bytes(b"tampered-video")
    with pytest.raises(HTTPException) as tamper_error:
        public_tours._asset_file("magicfit-tour", "tour.mp4")
    assert tamper_error.value.status_code == 410

    payload["video_release"]["revoked"] = True
    (bundle / "tour.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(HTTPException) as revoked_error:
        public_tours._asset_file("magicfit-tour", "tour.mp4")
    assert revoked_error.value.status_code == 410


def test_released_generated_video_is_hash_verified_and_terminal_states_return_410(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    video = b"reviewed-generated-video"
    root = tmp_path / "public-tours"
    bundle = root / "generated-tour"
    generated_dir = bundle / "generated-reconstruction"
    generated_dir.mkdir(parents=True)
    video_path = generated_dir / "generated-walkthrough.mp4"
    video_path.write_bytes(video)
    source_manifest = _generated_video_source_manifest()
    (generated_dir / "reconstruction.json").write_bytes(source_manifest)
    payload = _generated_video_payload(video, source_manifest)
    (bundle / "tour.json").write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(public_tours, "_tour_dir", lambda: root)
    public_tours._public_tour_cached_file_sha256.cache_clear()

    assert (
        public_tours._asset_file(
            "generated-tour",
            "generated-reconstruction/generated-walkthrough.mp4",
        )
        == video_path
    )

    video_path.write_bytes(b"tampered-generated-video")
    with pytest.raises(HTTPException) as tamper_error:
        public_tours._asset_file(
            "generated-tour",
            "generated-reconstruction/generated-walkthrough.mp4",
        )
    assert tamper_error.value.status_code == 410

    payload["video_release"]["disqualified"] = True
    (bundle / "tour.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(HTTPException) as disqualified_error:
        public_tours._asset_file(
            "generated-tour",
            "generated-reconstruction/generated-walkthrough.mp4",
        )
    assert disqualified_error.value.status_code == 410


def test_released_generated_video_rejects_tmp_or_test_source_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    video = b"reviewed-generated-video"
    unsafe_manifest = _generated_video_source_manifest(
        source_path="/tmp/pytest-of-user/test_generated_reconstruction/floorplan.jpg"
    )
    root = tmp_path / "public-tours"
    bundle = root / "generated-tour"
    generated_dir = bundle / "generated-reconstruction"
    generated_dir.mkdir(parents=True)
    (generated_dir / "generated-walkthrough.mp4").write_bytes(video)
    (generated_dir / "reconstruction.json").write_bytes(unsafe_manifest)
    payload = _generated_video_payload(video, unsafe_manifest)
    (bundle / "tour.json").write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(public_tours, "_tour_dir", lambda: root)
    public_tours._public_tour_cached_file_sha256.cache_clear()

    assert evaluate_public_tour_video_release(payload)["released"] is True
    with pytest.raises(HTTPException) as provenance_error:
        public_tours._asset_file(
            "generated-tour",
            "generated-reconstruction/generated-walkthrough.mp4",
        )
    assert provenance_error.value.status_code == 410
