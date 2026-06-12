from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_module():
    script = Path("/docker/EA/scripts/materialize_fliplink_publication_receipt.py")
    spec = importlib.util.spec_from_file_location("materialize_fliplink_publication_receipt", script)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_manifest(tmp_path: Path, *, source_text: str = "Public memorial disclosure.") -> Path:
    source = tmp_path / "source.md"
    source.write_text(source_text, encoding="utf-8")
    pdf = tmp_path / "build" / "output.pdf"
    pdf.parent.mkdir()
    pdf.write_bytes(b"%PDF-1.4\npublic approved memorial guide\n%%EOF\n")
    manifest = {
        "document_id": "manfred-how-this-memorial-works",
        "title": "How this memorial works",
        "audience": "public",
        "approved": True,
        "review_status": "approved",
        "fliplink_url": "https://archive.myexternalbrain.com/manfred-how-this-memorial-works",
        "source_files": ["source.md"],
        "build_artifacts": {"pdf_path": "build/output.pdf"},
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path


def test_fliplink_publication_receipt_passes_for_public_approved_pdf(tmp_path: Path) -> None:
    module = _load_module()
    output = tmp_path / "receipt.json"
    payload = module.build_receipt(
        manifest_path=_write_manifest(tmp_path),
        output_path=output,
        live_check=False,
        generated_at="2026-06-12T00:00:00Z",
    )

    assert payload["status"] == "pass"
    assert payload["pdf_sha256"]
    assert payload["privacy"]["contains_sourcebook_pdf"] is False
    assert output.is_file()
    persisted = json.loads(output.read_text(encoding="utf-8"))
    assert persisted["contract_name"] == "executive_assistant.fliplink_publication_receipt.v1"


def test_fliplink_publication_receipt_fails_on_forbidden_source_terms(tmp_path: Path) -> None:
    module = _load_module()
    payload = module.build_receipt(
        manifest_path=_write_manifest(tmp_path, source_text="This copied sourcebook text includes a runner sheet."),
        output_path=tmp_path / "receipt.json",
        live_check=False,
        generated_at="2026-06-12T00:00:00Z",
    )

    checks = {item["code"]: item for item in payload["checks"]}
    assert payload["status"] == "fail"
    assert checks["forbidden_source_terms_absent"]["status"] == "fail"
    assert "sourcebook" in checks["forbidden_source_terms_absent"]["hits"]
