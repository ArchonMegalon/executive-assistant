from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.services.public_tour_release_policy import (
    PUBLIC_TOUR_GENERATED_VIEWER_RELEASE_CONTRACT,
)
from scripts import verify_public_tour_generated_viewer_release as verifier


def _assets() -> dict[str, bytes]:
    return {
        "generated-reconstruction/viewer.html": b"<!doctype html><canvas></canvas>",
        "generated-reconstruction/reconstruction.json": (
            b'{"viewer_version":"propertyquarry_3d_tour_viewer_v3",'
            b'"floorplan":{"source_path":"pcloud://propertyquarry/source/floorplan.jpg"}}'
        ),
        "generated-reconstruction/floorplan.png": b"floorplan-png",
        "generated-reconstruction/vendor/three.module.js": b"export const Scene = class {};",
        "generated-reconstruction/vendor/examples/jsm/controls/OrbitControls.js": (
            b"export class OrbitControls {}"
        ),
        "generated-reconstruction/photos/living-room.jpg": b"living-room-jpeg",
    }


def _payload() -> dict[str, object]:
    assets = _assets()
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
            "disclosure": (
                "Generated interactive reconstruction; not a captured or provider-verified 3D scan."
            ),
            "revoked": False,
            "disqualified": False,
        },
    }


def _write_bundle(tmp_path: Path) -> Path:
    bundle = tmp_path / "generated-viewer-tour"
    bundle.mkdir(mode=0o755)
    for relpath, content in _assets().items():
        target = bundle / relpath
        target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        cursor = target.parent
        while cursor != bundle:
            cursor.chmod(0o755)
            cursor = cursor.parent
        target.write_bytes(content)
        target.chmod(0o644)
    (bundle / "tour.json").write_text(json.dumps(_payload()), encoding="utf-8")
    (bundle / "tour.json").chmod(0o644)
    bundle.chmod(0o755)
    return bundle


def _remote_headers(path: str, size_bytes: int, digest: str) -> dict[str, str]:
    binding = next(
        row
        for row in _payload()["generated_viewer_release"]["asset_bindings"]
        if row["path"] == path
    )
    headers = {
        "content-type": str(binding["mime_type"]),
        "content-length": str(size_bytes),
        "access-control-allow-origin": "*",
        "cross-origin-resource-policy": "cross-origin",
        "x-content-type-options": "nosniff",
        "x-propertyquarry-asset-sha256": digest,
        "x-propertyquarry-viewer-revision": "release-2026-07-13.1",
        "cache-control": "public, max-age=86400, immutable",
    }
    if binding["role"] == "viewer_document":
        headers["cache-control"] = "no-store"
        headers["content-security-policy"] = (
            "default-src 'none'; script-src 'unsafe-inline' 'self'; "
            "style-src 'unsafe-inline'; img-src 'self' data:; object-src 'none'; "
            "base-uri 'none'; form-action 'none'; frame-ancestors 'self'"
        )
    return headers


def test_verifier_passes_complete_local_release_with_stable_receipt(
    tmp_path: Path,
) -> None:
    bundle = _write_bundle(tmp_path)

    first = verifier.verify_bundle(bundle)
    second = verifier.verify_bundle(bundle)

    assert first == second
    assert first["status"] == "pass"
    assert first["pass"] is True
    assert first["blockers"] == []
    assert first["slug"] == "generated-viewer-tour"
    assert first["checks"] == {
        "policy_released": True,
        "binding_count": 6,
        "serveable_binding_count": 5,
        "proof_only_binding_count": 1,
        "http_verified": False,
    }


def test_verifier_passes_explicit_layout_only_release(tmp_path: Path) -> None:
    bundle = _write_bundle(tmp_path)
    photo_relpath = "generated-reconstruction/photos/living-room.jpg"
    (bundle / photo_relpath).unlink()
    payload = json.loads((bundle / "tour.json").read_text(encoding="utf-8"))
    generated = payload["generated_reconstruction"]
    generated.pop("photo_relpaths")
    generated["photo_reference_panel_count"] = 0
    payload["generated_viewer_release"]["asset_bindings"] = [
        row
        for row in payload["generated_viewer_release"]["asset_bindings"]
        if row["path"] != photo_relpath
    ]
    (bundle / "tour.json").write_text(json.dumps(payload), encoding="utf-8")

    receipt = verifier.verify_bundle(bundle)

    assert receipt["status"] == "pass"
    assert receipt["pass"] is True
    assert receipt["blockers"] == []
    assert receipt["checks"] == {
        "policy_released": True,
        "binding_count": 5,
        "serveable_binding_count": 4,
        "proof_only_binding_count": 1,
        "http_verified": False,
    }


def test_verifier_fails_closed_for_mode_digest_and_symlink_drift(
    tmp_path: Path,
) -> None:
    bundle = _write_bundle(tmp_path)
    viewer = bundle / "generated-reconstruction/viewer.html"
    viewer.chmod(0o664)
    (bundle / "generated-reconstruction/floorplan.png").write_bytes(b"tampered")
    photo = bundle / "generated-reconstruction/photos/living-room.jpg"
    photo.unlink()
    photo.symlink_to(bundle / "generated-reconstruction/floorplan.png")

    receipt = verifier.verify_bundle(bundle)
    blocker_codes = {row["code"] for row in receipt["blockers"]}

    assert receipt["pass"] is False
    assert receipt["status"] == "blocked"
    assert "unsafe_file_mode" in blocker_codes
    assert "asset_digest_mismatch" in blocker_codes
    assert "asset_size_mismatch" in blocker_codes
    assert "symlink_forbidden" in blocker_codes


def test_verifier_rejects_tmp_or_test_source_provenance_even_when_digest_bound(
    tmp_path: Path,
) -> None:
    bundle = _write_bundle(tmp_path)
    relpath = "generated-reconstruction/reconstruction.json"
    unsafe_manifest = (
        b'{"viewer_version":"propertyquarry_3d_tour_viewer_v3",'
        b'"floorplan":{"source_path":"/tmp/pytest-of-user/test_viewer/floorplan.jpg"}}'
    )
    (bundle / relpath).write_bytes(unsafe_manifest)
    payload = json.loads((bundle / "tour.json").read_text(encoding="utf-8"))
    binding = next(
        row
        for row in payload["generated_viewer_release"]["asset_bindings"]
        if row["path"] == relpath
    )
    binding["sha256"] = hashlib.sha256(unsafe_manifest).hexdigest()
    binding["size_bytes"] = len(unsafe_manifest)
    (bundle / "tour.json").write_text(json.dumps(payload), encoding="utf-8")

    receipt = verifier.verify_bundle(bundle)

    assert receipt["pass"] is False
    assert any(
        blocker["code"] == "source_provenance_unsafe"
        and blocker["unsafe_reference_count"] == 1
        for blocker in receipt["blockers"]
    )


def test_verifier_checks_get_and_head_but_never_fetches_proof_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _write_bundle(tmp_path)
    requested: list[tuple[str, str]] = []

    def _fake_fetch(url: str, *, method: str, max_body_bytes: int) -> dict[str, object]:
        del max_body_bytes
        path = urllib_path(url)
        requested.append((method, path))
        content = _assets()[path]
        digest = hashlib.sha256(content).hexdigest()
        return {
            "status": 200,
            "headers": _remote_headers(path, len(content), digest),
            "body": content if method == "GET" else b"",
            "error": "",
        }

    monkeypatch.setattr(verifier, "_http_fetch", _fake_fetch)

    receipt = verifier.verify_bundle(bundle, base_url="https://ea.example")

    assert receipt["pass"] is True
    assert receipt["checks"]["http_verified"] is True
    assert len(requested) == 10
    assert {method for method, _path in requested} == {"GET", "HEAD"}
    assert all(
        path != "generated-reconstruction/reconstruction.json"
        for _method, path in requested
    )


def test_verifier_blocks_remote_header_and_body_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _write_bundle(tmp_path)

    def _fake_fetch(url: str, *, method: str, max_body_bytes: int) -> dict[str, object]:
        del max_body_bytes
        path = urllib_path(url)
        content = _assets()[path]
        digest = hashlib.sha256(content).hexdigest()
        headers = _remote_headers(path, len(content), digest)
        if path.endswith("viewer.html"):
            headers["content-security-policy"] = "default-src https:"
        if path.endswith("three.module.js"):
            headers["access-control-allow-origin"] = "https://ea.example"
        body = content if method == "GET" else b""
        if method == "GET" and path.endswith("living-room.jpg"):
            body = b"remote-tamper"
        return {"status": 200, "headers": headers, "body": body, "error": ""}

    monkeypatch.setattr(verifier, "_http_fetch", _fake_fetch)

    receipt = verifier.verify_bundle(bundle, base_url="https://ea.example")
    blocker_codes = {row["code"] for row in receipt["blockers"]}

    assert receipt["pass"] is False
    assert "http_document_csp_invalid" in blocker_codes
    assert "http_acao_invalid" in blocker_codes
    assert "http_body_integrity_failed" in blocker_codes


def test_cli_emits_one_json_receipt_and_returns_nonzero_for_blocker(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bundle = _write_bundle(tmp_path)
    (bundle / "tour.json").chmod(0o666)

    exit_code = verifier.main(["--bundle-dir", str(bundle)])
    stdout = capsys.readouterr().out
    receipt = json.loads(stdout)

    assert exit_code == 1
    assert stdout.count("\n") == 1
    assert receipt["pass"] is False
    assert any(row["code"] == "unsafe_file_mode" for row in receipt["blockers"])


def urllib_path(url: str) -> str:
    marker = "/tours/viewer/generated-viewer-tour/"
    assert marker in url
    return url.split(marker, 1)[1]
