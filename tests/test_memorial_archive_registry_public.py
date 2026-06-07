from __future__ import annotations

from pathlib import Path


def test_public_registry_filters_non_public_publications() -> None:
    from app.services.memorial_archive_registry import public_registry_payload

    registry = {
        "slug": "manfred",
        "generated_at": "2026-06-06T00:00:00Z",
        "archive_sections": [
            {"title": "Public", "audience": "public", "items": ["pub", "family"]},
            {"title": "Family", "audience": "family", "items": ["family"]},
        ],
        "fliplink_publications": [
            {
                "id": "pub",
                "title": "Public Doc",
                "audience": "public",
                "review_status": "published",
                "url": "https://archive.example/pub",
                "secret": "must-not-export",
            },
            {
                "id": "family",
                "title": "Family Doc",
                "audience": "family",
                "review_status": "published",
                "url": "https://archive.example/family",
            },
        ],
    }

    public = public_registry_payload(registry)

    assert [item["id"] for item in public["fliplink_publications"]] == ["pub"]
    assert public["archive_sections"] == [{"title": "Public", "audience": "public", "items": ["pub"]}]
    assert "secret" not in public["fliplink_publications"][0]


def test_fliplink_manifest_normalization_sets_safe_defaults(tmp_path: Path) -> None:
    from app.services.memorial_archive_registry import normalize_manifest, publication_from_manifest

    manifest_path = tmp_path / "manfred-life-overview" / "manifest.json"
    manifest_path.parent.mkdir()
    manifest = normalize_manifest(
        {
            "title": "Life Overview",
            "audience": "public",
            "approved": True,
            "review_status": "approved",
            "fliplink_url": "https://archive.example/manfred-life-overview",
        },
        manifest_path=manifest_path,
    )

    assert manifest["document_id"] == "manfred-life-overview"
    assert manifest["noindex"] is False
    publication = publication_from_manifest(manifest)
    assert publication["id"] == "manfred-life-overview"
    assert publication["url"] == "https://archive.example/manfred-life-overview"
