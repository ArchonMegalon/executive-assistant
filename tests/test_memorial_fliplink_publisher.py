from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
from typing import Any

import pytest

from app.services import fliplink_client
from app.services import memorial_archive_registry
from app.services.fliplink_client import FlipLinkClient, FlipLinkSettings


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_fliplink_client_uploads_pdf_and_normalizes_response(monkeypatch, tmp_path: Path) -> None:
    pdf_path = tmp_path / "document.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n% test\n")
    seen: dict[str, Any] = {}

    def fake_urlopen(request, timeout: int = 0):
        seen["url"] = request.full_url
        seen["method"] = request.get_method()
        seen["timeout"] = timeout
        seen["content_type"] = request.get_header("Content-type")
        seen["authorization"] = request.get_header("Authorization")
        seen["body"] = request.data
        return _FakeResponse(
            {
                "data": {
                    "id": "pub_123",
                    "public_url": "https://archive.example/doc",
                    "embed": "<iframe></iframe>",
                    "qr_url": "https://archive.example/qr",
                    "slug": "doc",
                    "published_at": "2026-06-06T16:00:00Z",
                }
            }
        )

    monkeypatch.setattr(fliplink_client.urllib.request, "urlopen", fake_urlopen)

    client = FlipLinkClient(
        FlipLinkSettings(
            api_key="secret",
            base_url="https://fliplink.example",
            create_path="/publications",
            metadata_field="meta",
            file_field="upload",
        )
    )
    result = client.publish_pdf(pdf_path=pdf_path, metadata={"title": "Doc", "noindex": False})

    assert result["publication_id"] == "pub_123"
    assert result["url"] == "https://archive.example/doc"
    assert result["embed_code"] == "<iframe></iframe>"
    assert result["qr_url"] == "https://archive.example/qr"
    assert seen["url"] == "https://fliplink.example/publications"
    assert seen["method"] == "POST"
    assert seen["authorization"] == "Bearer secret"
    assert "multipart/form-data" in seen["content_type"]
    assert b'name="meta"' in seen["body"]
    assert b'name="upload"; filename="document.pdf"' in seen["body"]
    assert b'"title": "Doc"' in seen["body"]
    assert b"%PDF-1.4" in seen["body"]


def test_memorial_publisher_uses_build_artifact_pdf_and_writes_fliplink_fields(tmp_path: Path) -> None:
    publisher = importlib.import_module("scripts.publish_memorial_fliplink_publications")
    doc_dir = tmp_path / "doc"
    pdf_path = doc_dir / "build" / "output.pdf"
    pdf_path.parent.mkdir(parents=True)
    pdf_path.write_bytes(b"%PDF-1.4\n% test\n")
    manifest_path = doc_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "document_id": "doc",
                "title": "Doc",
                "approved": True,
                "review_status": "approved",
                "audience": "public",
                "build_artifacts": {"pdf_path": str(pdf_path)},
            }
        ),
        encoding="utf-8",
    )
    seen: dict[str, Any] = {}

    class FakeClient:
        def publish_pdf(self, *, pdf_path: Path, metadata: dict[str, Any], publication_id: str = "") -> dict[str, str]:
            seen["pdf_path"] = pdf_path
            seen["metadata"] = metadata
            seen["publication_id"] = publication_id
            return {
                "publication_id": "pub_doc",
                "url": "https://archive.example/doc",
                "embed_code": "<iframe></iframe>",
                "qr_url": "https://archive.example/qr",
                "published_at": "2026-06-06T16:00:00Z",
            }

    result = publisher.publish_manifest(
        manifest_path,
        dry_run=False,
        replace=False,
        custom_domain="archive.example",
        client=FakeClient(),
    )

    assert seen["pdf_path"] == pdf_path
    assert seen["metadata"]["custom_domain"] == "archive.example"
    assert seen["metadata"]["privacy"] == "public"
    assert result["fliplink_url"] == "https://archive.example/doc"
    written = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert written["fliplink_publication_id"] == "pub_doc"
    assert written["fliplink_qr_url"] == "https://archive.example/qr"
    assert written["review_status"] == "published"


def test_memorial_publisher_skips_existing_fliplink_url_without_replace(tmp_path: Path) -> None:
    publisher = importlib.import_module("scripts.publish_memorial_fliplink_publications")
    doc_dir = tmp_path / "doc"
    pdf_path = doc_dir / "build" / "output.pdf"
    pdf_path.parent.mkdir(parents=True)
    pdf_path.write_bytes(b"%PDF-1.4\n% test\n")
    manifest_path = doc_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "document_id": "doc",
                "title": "Doc",
                "approved": True,
                "review_status": "approved",
                "audience": "public",
                "fliplink_url": "https://archive.example/existing",
                "build_artifacts": {"pdf_path": str(pdf_path)},
            }
        ),
        encoding="utf-8",
    )

    class FailingClient:
        def publish_pdf(self, **_: object) -> dict[str, str]:
            raise AssertionError("publish_pdf should not be called")

    result = publisher.publish_manifest(
        manifest_path,
        dry_run=False,
        replace=False,
        client=FailingClient(),
    )

    assert result["fliplink_url"] == "https://archive.example/existing"
    written = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert written["fliplink_url"] == "https://archive.example/existing"


def test_memorial_publisher_rejects_pdf_path_outside_document(tmp_path: Path) -> None:
    publisher = importlib.import_module("scripts.publish_memorial_fliplink_publications")
    document_root = tmp_path / "doc"
    document_root.mkdir()
    outside_pdf = tmp_path / "outside.pdf"
    outside_pdf.write_bytes(b"%PDF-1.4\n% private\n")
    manifest_path = document_root / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "document_id": "doc",
                "title": "Doc",
                "approved": True,
                "review_status": "approved",
                "audience": "public",
                "build_artifacts": {"pdf_path": "../outside.pdf"},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="memorial_pdf_path_escape"):
        publisher.publish_manifest(manifest_path, dry_run=True, replace=False)


def test_memorial_publisher_treats_placeholder_url_as_unpublished(tmp_path: Path) -> None:
    publisher = importlib.import_module("scripts.publish_memorial_fliplink_publications")
    document_root = tmp_path / "doc"
    pdf_path = document_root / "build" / "output.pdf"
    pdf_path.parent.mkdir(parents=True)
    pdf_path.write_bytes(b"%PDF-1.4\n% test\n")
    manifest_path = document_root / "manifest.json"
    original = {
        "document_id": "doc",
        "title": "Doc",
        "approved": True,
        "review_status": "approved",
        "audience": "public",
        "fliplink_url": "https://archive.example.test/doc",
        "build_artifacts": {"pdf_path": "build/output.pdf"},
    }
    manifest_path.write_text(json.dumps(original), encoding="utf-8")
    calls = 0

    class PlaceholderClient:
        def publish_pdf(self, **_: object) -> dict[str, str]:
            nonlocal calls
            calls += 1
            return {"publication_id": "fake", "url": "https://placeholder.invalid/doc"}

    with pytest.raises(SystemExit, match="unpublished URL"):
        publisher.publish_manifest(
            manifest_path,
            dry_run=False,
            replace=False,
            client=PlaceholderClient(),
        )

    assert calls == 1
    assert json.loads(manifest_path.read_text(encoding="utf-8")) == original


def test_public_registry_projection_excludes_private_and_placeholder_entries() -> None:
    publisher = importlib.import_module("scripts.publish_memorial_fliplink_publications")
    common = {
        "approved": True,
        "review_status": "published",
        "sensitivity": "PUBLIC",
        "viewer_type": "smart_document",
    }
    registry = publisher._registry_from_publishable_public_manifests(
        slug="manfred",
        manifests=[
            {
                **common,
                "document_id": "public-real",
                "title": "Public real",
                "audience": "public",
                "fliplink_url": "https://archive.example/public-real",
                "private_notes": "must not leak",
            },
            {
                **common,
                "document_id": "family-real",
                "title": "Family real",
                "audience": "family",
                "fliplink_url": "https://archive.example/family-real",
            },
            {
                **common,
                "document_id": "public-placeholder",
                "title": "Public placeholder",
                "audience": "public",
                "fliplink_url": "https://archive.example.test/public-placeholder",
            },
        ],
    )

    assert [item["id"] for item in registry["fliplink_publications"]] == ["public-real"]
    assert registry["archive_sections"] == [
        {"title": "Oeffentliches Archiv", "audience": "public", "items": ["public-real"]}
    ]
    assert "private_notes" not in json.dumps(registry)


@pytest.mark.parametrize("audience", [None, "", "privtae", "unknown"])
def test_archive_registry_unknown_audience_fails_closed(
    audience: str | None,
) -> None:
    manifest = {
        "document_id": "private-letter",
        "title": "Private letter",
        "audience": audience,
        "sensitivity": "PUBLIC",
        "approved": True,
        "review_status": "published",
        "fliplink_url": "/memorials/manfred/archive/private-letter",
    }

    normalized = memorial_archive_registry.normalize_manifest(
        manifest,
        manifest_path=Path("/archive/private-letter/manifest.json"),
    )
    assert normalized["audience"] == ""
    assert normalized["public"] is False
    assert normalized["share_with_memorial_app"] is False
    for include_nonpublic in (False, True):
        registry = memorial_archive_registry.registry_from_manifests(
            slug="manfred",
            manifests=[manifest],
            include_nonpublic=include_nonpublic,
        )
        assert registry["archive_sections"] == []
        assert registry["fliplink_publications"] == []


def test_archive_registry_public_projection_requires_complete_release_boundary() -> None:
    valid = {
        "approved": True,
        "id": "public-valid",
        "title": "Public valid",
        "audience": "public",
        "sensitivity": "PUBLIC",
        "review_status": "published",
        "url": "/memorials/manfred/archive/public-valid",
    }
    invalid = [
        {**valid, "id": "missing-approval", "approved": None},
        {**valid, "id": "false-approval", "approved": False},
        {**valid, "id": "string-approval", "approved": "true"},
        {**valid, "id": "private-sensitivity", "sensitivity": "PRIVATE"},
        {**valid, "id": "not-published", "review_status": "approved"},
        {**valid, "id": "family-audience", "audience": "family"},
    ]
    item_ids = [valid["id"], *(item["id"] for item in invalid)]

    payload = memorial_archive_registry.public_registry_payload(
        {
            "slug": "manfred",
            "archive_sections": [
                {"title": "Public", "audience": "public", "items": item_ids}
            ],
            "fliplink_publications": [valid, *invalid],
        }
    )

    assert payload["archive_sections"] == [
        {"title": "Public", "audience": "public", "items": ["public-valid"]}
    ]
    assert payload["fliplink_publications"] == [valid]


def test_archive_registry_manifest_projection_preserves_explicit_approval_only() -> None:
    common = {
        "title": "Public archive item",
        "audience": "public",
        "review_status": "published",
        "fliplink_url": "/memorials/manfred/archive/item",
    }
    registry = memorial_archive_registry.registry_from_manifests(
        slug="manfred",
        manifests=[
            {
                **common,
                "document_id": "public-valid",
                "approved": True,
                "sensitivity": "PUBLIC",
            },
            {
                **common,
                "document_id": "private-sensitivity",
                "approved": True,
                "sensitivity": "PRIVATE",
            },
            {
                **common,
                "document_id": "implicit-approval",
                "sensitivity": "PUBLIC",
            },
            {
                **common,
                "document_id": "implicit-sensitivity",
                "approved": True,
            },
        ],
        include_nonpublic=False,
    )

    assert [item["id"] for item in registry["fliplink_publications"]] == [
        "public-valid"
    ]
    assert registry["fliplink_publications"][0]["approved"] is True


@pytest.mark.parametrize(
    ("module_name", "factory_name"),
    [
        ("scripts.build_memorial_archive_documents", "_public_registry_from_manifests"),
        ("scripts.publish_memorial_fliplink_publications", "_registry_from_publishable_public_manifests"),
    ],
)
def test_public_registry_uses_contained_internal_html_without_fliplink(
    module_name: str, factory_name: str, tmp_path: Path
) -> None:
    module = importlib.import_module(module_name)
    factory = getattr(module, factory_name)
    slug_root = tmp_path / "archive" / "manfred"
    public_document = slug_root / "public" / "public-doc"
    public_html = public_document / "build" / "index.html"
    public_html.parent.mkdir(parents=True)
    public_html.write_text("<!doctype html><title>Public</title>", encoding="utf-8")
    public_manifest_path = public_document / "manifest.json"
    public_manifest_path.write_text("{}", encoding="utf-8")

    family_document = slug_root / "family" / "family-doc"
    family_html = family_document / "build" / "index.html"
    family_html.parent.mkdir(parents=True)
    family_html.write_text("<!doctype html><title>Family</title>", encoding="utf-8")
    family_manifest_path = family_document / "manifest.json"
    family_manifest_path.write_text("{}", encoding="utf-8")

    escaped_document = slug_root / "public" / "escaped-doc"
    escaped_document.mkdir(parents=True)
    escaped_manifest_path = escaped_document / "manifest.json"
    escaped_manifest_path.write_text("{}", encoding="utf-8")

    common = {
        "approved": True,
        "review_status": "approved",
        "sensitivity": "PUBLIC",
        "viewer_type": "smart_document",
        "fliplink_url": "https://archive.example.test/not-published",
    }
    registry = factory(
        slug="manfred",
        slug_root=slug_root,
        manifests=[
            {
                **common,
                "document_id": "public-doc",
                "title": "Public doc",
                "audience": "public",
                "build_artifacts": {"html_path": "build/index.html"},
                "_manifest_path": str(public_manifest_path),
            },
            {
                **common,
                "document_id": "family-doc",
                "title": "Family doc",
                "audience": "family",
                "build_artifacts": {"html_path": "build/index.html"},
                "_manifest_path": str(family_manifest_path),
            },
            {
                **common,
                "document_id": "escaped-doc",
                "title": "Escaped doc",
                "audience": "public",
                "build_artifacts": {"html_path": "../public-doc/build/index.html"},
                "_manifest_path": str(escaped_manifest_path),
            },
            {
                **common,
                "document_id": "unsafe-slug",
                "fliplink_slug": "../family-doc",
                "title": "Unsafe slug",
                "audience": "public",
                "build_artifacts": {"html_path": "build/index.html"},
                "_manifest_path": str(public_manifest_path),
            },
        ],
    )

    assert registry["archive_sections"] == [
        {"title": "Oeffentliches Archiv", "audience": "public", "items": ["public-doc"]}
    ]
    assert len(registry["fliplink_publications"]) == 1
    publication = registry["fliplink_publications"][0]
    assert publication["id"] == "public-doc"
    assert publication["audience"] == "public"
    assert publication["url"] == "/memorials/manfred/archive/public-doc"
    assert publication["review_status"] == "published"


def test_fliplink_publisher_does_not_accept_internal_route_as_external_publication() -> None:
    publisher = importlib.import_module("scripts.publish_memorial_fliplink_publications")

    assert publisher._is_publishable_url("/memorials/manfred/archive/public-doc") is False


def test_archive_writes_replace_targets_atomically(monkeypatch, tmp_path: Path) -> None:
    publisher = importlib.import_module("scripts.publish_memorial_fliplink_publications")
    target = tmp_path / "registry.json"
    target.write_text("old", encoding="utf-8")
    real_replace = os.replace
    replacements: list[tuple[Path, Path]] = []

    def recording_replace(source: str | os.PathLike[str], destination: str | os.PathLike[str]) -> None:
        replacements.append((Path(source), Path(destination)))
        real_replace(source, destination)

    monkeypatch.setattr(publisher.os, "replace", recording_replace)
    publisher._atomic_write_text(target, "new\n")

    assert target.read_text(encoding="utf-8") == "new\n"
    assert replacements and replacements[-1][1] == target
    assert all(path == target or not path.name.endswith(".tmp") for path in tmp_path.iterdir())


def test_archive_builder_rejects_manifest_outside_slug_root(tmp_path: Path) -> None:
    builder = importlib.import_module("scripts.build_memorial_archive_documents")
    slug_root = tmp_path / "archive" / "manfred"
    slug_root.mkdir(parents=True)
    outside_manifest = tmp_path / "outside" / "manifest.json"
    outside_manifest.parent.mkdir()
    outside_manifest.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="manifest_path_escape"):
        builder.build_document(outside_manifest, slug_root, require_pdf=False)
