from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import zipfile

import pytest

from app.services import ltd_provider_governance as governance


ROOT = Path(__file__).resolve().parents[1]
MATERIALIZER = ROOT / "scripts" / "materialize_aiwritebook_canary_fixture.py"
VERIFIER = ROOT / "scripts" / "verify_aiwritebook_export_roundtrip.py"


def _module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_exports(tmp_path: Path, marker: str) -> tuple[Path, Path, Path]:
    pdf = tmp_path / "canary.pdf"
    pdf.write_bytes(f"%PDF-1.7\n1 0 obj\n({marker})\nendobj\n%%EOF\n".encode())

    epub = tmp_path / "canary.epub"
    with zipfile.ZipFile(epub, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        archive.writestr(
            "META-INF/container.xml",
            '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
            '<rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
            "</rootfiles></container>",
        )
        archive.writestr("OEBPS/content.opf", '<package xmlns="http://www.idpf.org/2007/opf"/>')
        archive.writestr("OEBPS/chapter.xhtml", f"<html><body>{marker}</body></html>")

    docx = tmp_path / "canary.docx"
    with zipfile.ZipFile(docx, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("_rels/.rels", "<Relationships/>")
        archive.writestr("word/document.xml", f"<document><p>{marker}</p></document>")
    return pdf, epub, docx


def _approved_evidence(tmp_path: Path, manifest: dict[str, object]) -> tuple[Path, Path]:
    digest = manifest["manifest_sha256"]
    approval = tmp_path / "approval.json"
    _write_json(
        approval,
        {
            "contract": "ea.aiwritebook.canary_approval",
            "contract_version": 1,
            "status": "approved",
            "fixture_manifest_sha256": digest,
            "approved_by_ref": "operator-approval-receipt-1",
            "approved_at": "2026-08-11T11:55:00+00:00",
            "maximum_credits": 18,
            "approved_actions": {
                "provider_project_creation": True,
                "source_upload": True,
                "generation": True,
                "credit_spend": True,
                "export_download": True,
                "provider_project_deletion": True,
                "publication": False,
                "external_send": False,
            },
        },
    )
    observation = tmp_path / "observation.json"
    _write_json(
        observation,
        {
            "contract": "ea.aiwritebook.canary_operator_observation",
            "contract_version": 1,
            "fixture_manifest_sha256": digest,
            "provider_project_ref": "synthetic-project-123",
            "credits_before": 5100,
            "credits_after": 5082,
            "credits_spent": 18,
            "run_started_at": "2026-08-11T11:56:00+00:00",
            "run_finished_at": "2026-08-11T11:59:00+00:00",
            "automation": {
                "operator_run": True,
                "unattended_browser_automation_used": False,
            },
            "privacy_ui": {
                "project_private_during_run": True,
                "shared_with_other_users": False,
            },
            "cleanup": {
                "delete_requested": True,
                "project_inaccessible_after_delete": True,
            },
            "human_review": {
                "outline_reviewed": True,
                "exports_reviewed": True,
                "pdf_content_marker_reviewed": True,
            },
            "external_actions": {
                "publication_started": False,
                "external_send_performed": False,
            },
        },
    )
    return approval, observation


def test_aiwritebook_canary_fixture_is_deterministic_and_contains_no_user_data(tmp_path: Path) -> None:
    materializer = _module("materialize_aiwritebook_canary_fixture", MATERIALIZER)
    first_source = tmp_path / "first" / "source.md"
    first_manifest = tmp_path / "first" / "manifest.json"
    second_source = tmp_path / "second" / "source.md"
    second_manifest = tmp_path / "second" / "manifest.json"

    first = materializer.materialize(source_path=first_source, manifest_path=first_manifest)
    second = materializer.materialize(source_path=second_source, manifest_path=second_manifest)

    assert first == second
    assert first_source.read_bytes() == second_source.read_bytes()
    assert first_manifest.read_bytes() == second_manifest.read_bytes()
    assert first["contract"] == "ea.aiwritebook.synthetic_canary"
    assert first["data_classification"] == {
        "synthetic": True,
        "contains_personal_data": False,
        "contains_campaign_data": False,
        "contains_customer_data": False,
        "contains_copied_third_party_text": False,
    }
    assert first["execution_boundary"]["operator_required"] is True
    assert first["execution_boundary"]["unattended_browser_automation_allowed"] is False
    source_bytes = first_source.read_bytes()
    assert first["source"]["sha256"] == hashlib.sha256(source_bytes).hexdigest()
    serialized = source_bytes.decode() + first_manifest.read_text(encoding="utf-8")
    assert "@" not in serialized
    assert "password" not in serialized.lower()


def test_aiwritebook_roundtrip_verifier_requires_approval_and_validates_all_exports(tmp_path: Path) -> None:
    materializer = _module("materialize_aiwritebook_canary_fixture_for_verify", MATERIALIZER)
    verifier = _module("verify_aiwritebook_export_roundtrip", VERIFIER)
    source = tmp_path / "source.md"
    manifest_path = tmp_path / "manifest.json"
    manifest = materializer.materialize(source_path=source, manifest_path=manifest_path)
    approval, observation = _approved_evidence(tmp_path, manifest)
    pdf, epub, docx = _write_exports(tmp_path, str(manifest["content_marker"]))

    receipt = verifier.verify_roundtrip(
        manifest_path=manifest_path,
        approval_path=approval,
        observation_path=observation,
        pdf_path=pdf,
        epub_path=epub,
        docx_path=docx,
        generated_at="2026-08-11T12:00:00+00:00",
    )

    assert receipt["status"] == "pass"
    assert receipt["expected_formats"] == ["pdf", "epub", "docx"]
    assert receipt["provider_run"]["credits_spent"] == 18
    assert receipt["provider_run"]["project_inaccessible_after_delete"] is True
    assert all(row["structure_valid"] for row in receipt["exports"].values())
    assert all(row["content_marker_verified"] for row in receipt["exports"].values())
    assert governance._valid_aiwritebook_export_roundtrip_receipt(_receipt_root(tmp_path, receipt)) is True

    approval_payload = json.loads(approval.read_text(encoding="utf-8"))
    approval_payload["status"] = "pending"
    _write_json(approval, approval_payload)
    with pytest.raises(ValueError, match="approval_invalid"):
        verifier.verify_roundtrip(
            manifest_path=manifest_path,
            approval_path=approval,
            observation_path=observation,
            pdf_path=pdf,
            epub_path=epub,
            docx_path=docx,
        )


def test_aiwritebook_roundtrip_verifier_rejects_over_budget_or_markerless_exports(tmp_path: Path) -> None:
    materializer = _module("materialize_aiwritebook_canary_fixture_negative", MATERIALIZER)
    verifier = _module("verify_aiwritebook_export_roundtrip_negative", VERIFIER)
    manifest_path = tmp_path / "manifest.json"
    manifest = materializer.materialize(source_path=tmp_path / "source.md", manifest_path=manifest_path)
    approval, observation = _approved_evidence(tmp_path, manifest)
    pdf, epub, docx = _write_exports(tmp_path, str(manifest["content_marker"]))

    observation_payload = json.loads(observation.read_text(encoding="utf-8"))
    observation_payload.update({"credits_after": 5081, "credits_spent": 19})
    _write_json(observation, observation_payload)
    with pytest.raises(ValueError, match="operator_observation_invalid"):
        verifier.verify_roundtrip(
            manifest_path=manifest_path,
            approval_path=approval,
            observation_path=observation,
            pdf_path=pdf,
            epub_path=epub,
            docx_path=docx,
        )

    observation_payload.update({"credits_after": 5082, "credits_spent": 18})
    _write_json(observation, observation_payload)
    with zipfile.ZipFile(docx, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("_rels/.rels", "<Relationships/>")
        archive.writestr("word/document.xml", "<document><p>wrong marker</p></document>")
    with pytest.raises(ValueError, match="docx_content_marker_missing"):
        verifier.verify_roundtrip(
            manifest_path=manifest_path,
            approval_path=approval,
            observation_path=observation,
            pdf_path=pdf,
            epub_path=epub,
            docx_path=docx,
        )

    with zipfile.ZipFile(docx, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("_rels/.rels", "<Relationships/>")
        archive.writestr(
            "word/document.xml",
            '<!DOCTYPE document [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
            "<document><p>&xxe;</p></document>",
        )
    with pytest.raises(ValueError, match="invalid_docx_document_xml"):
        verifier.verify_roundtrip(
            manifest_path=manifest_path,
            approval_path=approval,
            observation_path=observation,
            pdf_path=pdf,
            epub_path=epub,
            docx_path=docx,
        )


def test_aiwritebook_canary_materializer_refuses_symlink_outputs(tmp_path: Path) -> None:
    materializer = _module("materialize_aiwritebook_canary_fixture_symlink", MATERIALIZER)
    target = tmp_path / "target.md"
    target.write_text("keep", encoding="utf-8")
    source = tmp_path / "source.md"
    source.symlink_to(target)

    with pytest.raises(RuntimeError, match="output_symlink_not_allowed"):
        materializer.materialize(source_path=source, manifest_path=tmp_path / "manifest.json")
    assert target.read_text(encoding="utf-8") == "keep"


def _receipt_root(tmp_path: Path, receipt: dict[str, object]) -> Path:
    root = tmp_path / "governance"
    target = root / "ea/_completion/aiwritebook"
    target.mkdir(parents=True)
    _write_json(target / "AIWRITEBOOK_EXPORT_ROUNDTRIP.generated.json", receipt)
    return root


def test_aiwritebook_governance_rejects_status_only_receipt(tmp_path: Path) -> None:
    target = tmp_path / "ea/_completion/aiwritebook"
    target.mkdir(parents=True)
    _write_json(target / "AIWRITEBOOK_EXPORT_ROUNDTRIP.generated.json", {"status": "pass"})
    assert governance._valid_aiwritebook_export_roundtrip_receipt(tmp_path) is False
