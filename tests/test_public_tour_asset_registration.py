from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.api.routes import public_tours
from app.product import service
from app.services.public_tour_release_policy import (
    PUBLIC_TOUR_VIDEO_RELEASE_CONTRACT,
    evaluate_public_tour_video_release,
)


def _write_manifest(bundle: Path, payload: dict[str, object]) -> None:
    bundle.mkdir(parents=True, exist_ok=True)
    (bundle / "tour.json").write_text(json.dumps(payload), encoding="utf-8")


def test_generated_preview_registration_is_digest_bound_and_deduplicated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "public-tours"
    bundle = root / "sample-tour"
    _write_manifest(
        bundle,
        {
            "slug": "sample-tour",
            "title": "Preserved title",
            "public_assets": [
                {
                    "path": "existing.jpg",
                    "sha256": "a" * 64,
                    "size_bytes": 12,
                    "mime_type": "image/jpeg",
                    "privacy_class": "public",
                    "role": "photo",
                    "purpose": "tour_scene",
                }
            ],
        },
    )
    preview = bundle / "telegram-preview.png"
    preview.write_bytes(b"first-preview")
    monkeypatch.setattr(service, "public_tour_dir", lambda: root)

    registration = service._register_hosted_public_tour_asset(
        bundle_dir=bundle,
        relpath="telegram-preview.png",
        role="preview",
        purpose="telegram_delivery_preview",
    )

    assert registration == {
        "path": "telegram-preview.png",
        "relpath": "telegram-preview.png",
        "sha256": hashlib.sha256(b"first-preview").hexdigest(),
        "size_bytes": len(b"first-preview"),
        "byte_size": len(b"first-preview"),
        "mime_type": "image/png",
        "content_type": "image/png",
        "privacy_class": "public",
        "role": "preview",
        "purpose": "telegram_delivery_preview",
    }
    payload = json.loads((bundle / "tour.json").read_text(encoding="utf-8"))
    assert payload["title"] == "Preserved title"
    assert [row["path"] for row in payload["public_assets"]] == [
        "existing.jpg",
        "telegram-preview.png",
    ]

    preview.write_bytes(b"replacement-preview")
    service._register_hosted_public_tour_asset(
        bundle_dir=bundle,
        relpath="telegram-preview.png",
        role="preview",
        purpose="telegram_delivery_preview",
    )
    payload = json.loads((bundle / "tour.json").read_text(encoding="utf-8"))
    preview_rows = [
        row for row in payload["public_assets"] if row["path"] == "telegram-preview.png"
    ]
    assert len(preview_rows) == 1
    assert (
        preview_rows[0]["sha256"] == hashlib.sha256(b"replacement-preview").hexdigest()
    )


def test_generated_asset_registration_rejects_escape_symlink_and_unsupported_type(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "public-tours"
    bundle = root / "sample-tour"
    _write_manifest(bundle, {"slug": "sample-tour"})
    (bundle / "preview.txt").write_text("not a public media type", encoding="utf-8")
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"outside")
    (bundle / "linked.png").symlink_to(outside)
    monkeypatch.setattr(service, "public_tour_dir", lambda: root)

    with pytest.raises(RuntimeError, match="relpath_invalid"):
        service._register_hosted_public_tour_asset(
            bundle_dir=bundle,
            relpath="../outside.png",
            role="preview",
            purpose="telegram_delivery_preview",
        )
    with pytest.raises(RuntimeError, match="symlink_forbidden"):
        service._register_hosted_public_tour_asset(
            bundle_dir=bundle,
            relpath="linked.png",
            role="preview",
            purpose="telegram_delivery_preview",
        )
    with pytest.raises(RuntimeError, match="content_type_unsupported"):
        service._register_hosted_public_tour_asset(
            bundle_dir=bundle,
            relpath="preview.txt",
            role="preview",
            purpose="telegram_delivery_preview",
        )


def test_magicfit_manifest_registration_resets_attestation_to_pending_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    video = b"synthetic-magicfit-video"
    sidecar = b'{"provider":"magicfit","status":"rendered"}'
    root = tmp_path / "public-tours"
    bundle = root / "magicfit-tour"
    _write_manifest(
        bundle,
        {
            "slug": "magicfit-tour",
            "title": "Keep this title",
            "public_assets": [],
            "video_release": {
                "status": "ready",
                "review_receipt_sha256": "b" * 64,
                "quality_review_passed": True,
                "revoked": True,
            },
        },
    )
    (bundle / "tour.mp4").write_bytes(video)
    (bundle / "tour.magicfit.json").write_bytes(sidecar)
    monkeypatch.setattr(service, "public_tour_dir", lambda: root)

    updated = service._update_hosted_property_tour_magicfit_video_manifest(
        tour_url="https://property.example/tours/magicfit-tour",
        video_relpath="tour.mp4",
        sidecar_relpath="tour.magicfit.json",
    )

    assert updated["title"] == "Keep this title"
    registrations = {row["path"]: row for row in updated["public_assets"]}
    assert registrations["tour.mp4"]["sha256"] == hashlib.sha256(video).hexdigest()
    assert registrations["tour.mp4"]["size_bytes"] == len(video)
    assert registrations["tour.mp4"]["mime_type"] == "video/mp4"
    assert (
        registrations["tour.magicfit.json"]["sha256"]
        == hashlib.sha256(sidecar).hexdigest()
    )
    assert registrations["tour.magicfit.json"]["mime_type"] == "application/json"
    assert registrations["tour.magicfit.json"]["privacy_class"] == "internal"

    release = updated["video_release"]
    assert release["contract"] == PUBLIC_TOUR_VIDEO_RELEASE_CONTRACT
    assert release["status"] == "pending_quality_review"
    assert release["asset_sha256"] == hashlib.sha256(video).hexdigest()
    assert release["asset_size_bytes"] == len(video)
    assert release["source_sidecar_sha256"] == hashlib.sha256(sidecar).hexdigest()
    assert release["source_sidecar_size_bytes"] == len(sidecar)
    assert release["captured_provider_source"] is False
    assert release["satisfies_verified_tour_gate"] is False
    assert release["provider_output_verified"] is False
    assert release["quality_review_passed"] is False
    assert release["revoked"] is True
    assert "review_receipt_sha256" not in release
    assert "publication_authority_receipt_sha256" not in release
    assert "release_revision" not in release
    assert evaluate_public_tour_video_release(updated)["released"] is False
    monkeypatch.setattr(public_tours, "_tour_dir", lambda: root)
    assert "tour.mp4" not in public_tours._public_tour_allowed_asset_paths(updated)
    assert "tour.magicfit.json" not in public_tours._public_tour_allowed_asset_paths(
        updated
    )

    pending_only = json.loads(json.dumps(updated))
    pending_only["video_release"]["revoked"] = False
    assert evaluate_public_tour_video_release(pending_only)["released"] is False

    reviewed = json.loads(json.dumps(pending_only))
    reviewed["video_release"].update(
        {
            "status": "ready",
            "review_receipt_sha256": "c" * 64,
            "publication_authority_receipt_sha256": "d" * 64,
            "provider_output_verified": True,
            "quality_review_passed": True,
            "publication_authority_verified": True,
            "release_revision": "video-release-2026-07-13.1",
        }
    )
    assert "tour.mp4" in public_tours._public_tour_allowed_asset_paths(reviewed)
    assert "tour.magicfit.json" not in public_tours._public_tour_allowed_asset_paths(
        reviewed
    )


def test_magicfit_missing_sidecar_fails_before_manifest_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "public-tours"
    bundle = root / "magicfit-tour"
    original = {"slug": "magicfit-tour", "title": "Unchanged", "public_assets": []}
    _write_manifest(bundle, original)
    (bundle / "tour.mp4").write_bytes(b"video")
    monkeypatch.setattr(service, "public_tour_dir", lambda: root)

    with pytest.raises(RuntimeError, match="asset_missing"):
        service._update_hosted_property_tour_magicfit_video_manifest(
            tour_url="https://property.example/tours/magicfit-tour",
            video_relpath="tour.mp4",
            sidecar_relpath="missing.magicfit.json",
        )

    assert json.loads((bundle / "tour.json").read_text(encoding="utf-8")) == original
