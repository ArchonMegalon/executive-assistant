from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

from app.services import fliplink_client
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
