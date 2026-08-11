#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any
import zipfile

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "ea/_completion/aiwritebook/AIWRITEBOOK_EXPORT_ROUNDTRIP.generated.json"
RECEIPT_CONTRACT = "ea.aiwritebook.export_roundtrip"
APPROVAL_CONTRACT = "ea.aiwritebook.canary_approval"
OBSERVATION_CONTRACT = "ea.aiwritebook.canary_operator_observation"
EXPECTED_FORMATS = ("pdf", "epub", "docx")
EXPECTED_FIXTURE_ID = "aiwritebook-chronicle-export-canary-v1"
EXPECTED_MARKER = "EA-AIWRITEBOOK-CANARY-2026-08-11-7F3C"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
SAFE_REF_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
MAX_ARTIFACT_BYTES = 100 * 1024 * 1024
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 200 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 2048


def _load_object(path: Path, error: str) -> dict[str, Any]:
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise ValueError(error)
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(error)
    return payload


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _timestamp(value: object, error: str) -> datetime:
    raw = str(value or "").strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(error) from exc
    if parsed.tzinfo is None:
        raise ValueError(error)
    return parsed.astimezone(UTC)


def _validate_manifest(payload: dict[str, Any]) -> None:
    recorded_digest = str(payload.get("manifest_sha256") or "")
    unsigned = dict(payload)
    unsigned.pop("manifest_sha256", None)
    computed = _sha256((json.dumps(unsigned, ensure_ascii=True, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    classification = payload.get("data_classification")
    boundary = payload.get("execution_boundary")
    source = payload.get("source")
    rights = payload.get("rights")
    requested_run = payload.get("requested_run")
    credit_budget = payload.get("credit_budget")
    if (
        payload.get("contract") != "ea.aiwritebook.synthetic_canary"
        or payload.get("contract_version") != 1
        or payload.get("fixture_id") != EXPECTED_FIXTURE_ID
        or payload.get("content_marker") != EXPECTED_MARKER
        or not SHA256_PATTERN.fullmatch(recorded_digest)
        or recorded_digest != computed
        or not isinstance(source, dict)
        or not str(source.get("filename") or "")
        or Path(str(source.get("filename") or "")).name != str(source.get("filename") or "")
        or not SHA256_PATTERN.fullmatch(str(source.get("sha256") or ""))
        or not isinstance(source.get("size_bytes"), int)
        or isinstance(source.get("size_bytes"), bool)
        or source.get("size_bytes") <= 0
        or not isinstance(classification, dict)
        or classification.get("synthetic") is not True
        or any(classification.get(key) is not False for key in (
            "contains_personal_data",
            "contains_campaign_data",
            "contains_customer_data",
            "contains_copied_third_party_text",
        ))
        or not isinstance(boundary, dict)
        or boundary.get("operator_required") is not True
        or boundary.get("unattended_browser_automation_allowed") is not False
        or boundary.get("publication_allowed") is not False
        or boundary.get("external_send_allowed") is not False
        or rights != {
            "basis": "original_synthetic_repository_canary_text",
            "spdx_license_expression": "CC0-1.0",
        }
        or not isinstance(requested_run, dict)
        or set(requested_run.get("expected_exports") or ()) != set(EXPECTED_FORMATS)
        or requested_run.get("chapter_count") != 1
        or requested_run.get("writing_model") != "gemini"
        or any(requested_run.get(key) is not False for key in ("cover", "translation", "audiobook"))
        or not isinstance(credit_budget, dict)
        or credit_budget.get("expected_total_credits") != 18
        or credit_budget.get("maximum_approved_credits") != 18
    ):
        raise ValueError("aiwritebook_canary_manifest_invalid")


def _validate_approval(payload: dict[str, Any], manifest: dict[str, Any]) -> int:
    actions = payload.get("approved_actions")
    approved_by_ref = str(payload.get("approved_by_ref") or "")
    maximum = payload.get("maximum_credits")
    expected_maximum = manifest["credit_budget"]["maximum_approved_credits"]
    if (
        payload.get("contract") != APPROVAL_CONTRACT
        or payload.get("contract_version") != 1
        or payload.get("status") != "approved"
        or payload.get("fixture_manifest_sha256") != manifest.get("manifest_sha256")
        or not SAFE_REF_PATTERN.fullmatch(approved_by_ref)
        or not isinstance(actions, dict)
        or any(actions.get(key) is not True for key in (
            "provider_project_creation",
            "source_upload",
            "generation",
            "credit_spend",
            "export_download",
            "provider_project_deletion",
        ))
        or actions.get("publication") is not False
        or actions.get("external_send") is not False
        or not isinstance(maximum, int)
        or isinstance(maximum, bool)
        or maximum <= 0
        or maximum != expected_maximum
    ):
        raise ValueError("aiwritebook_canary_approval_invalid")
    _timestamp(payload.get("approved_at"), "aiwritebook_canary_approval_invalid")
    return maximum


def _validate_observation(payload: dict[str, Any], manifest: dict[str, Any], maximum: int) -> dict[str, Any]:
    automation = payload.get("automation")
    privacy = payload.get("privacy_ui")
    cleanup = payload.get("cleanup")
    review = payload.get("human_review")
    external = payload.get("external_actions")
    project_ref = str(payload.get("provider_project_ref") or "")
    before = payload.get("credits_before")
    after = payload.get("credits_after")
    spent = payload.get("credits_spent")
    if (
        payload.get("contract") != OBSERVATION_CONTRACT
        or payload.get("contract_version") != 1
        or payload.get("fixture_manifest_sha256") != manifest.get("manifest_sha256")
        or not SAFE_REF_PATTERN.fullmatch(project_ref)
        or not all(isinstance(value, int) and not isinstance(value, bool) for value in (before, after, spent))
        or before < after
        or spent != before - after
        or spent <= 0
        or spent > maximum
        or not isinstance(automation, dict)
        or automation.get("operator_run") is not True
        or automation.get("unattended_browser_automation_used") is not False
        or not isinstance(privacy, dict)
        or privacy.get("project_private_during_run") is not True
        or privacy.get("shared_with_other_users") is not False
        or not isinstance(cleanup, dict)
        or cleanup.get("delete_requested") is not True
        or cleanup.get("project_inaccessible_after_delete") is not True
        or not isinstance(review, dict)
        or review.get("outline_reviewed") is not True
        or review.get("exports_reviewed") is not True
        or review.get("pdf_content_marker_reviewed") is not True
        or not isinstance(external, dict)
        or external.get("publication_started") is not False
        or external.get("external_send_performed") is not False
    ):
        raise ValueError("aiwritebook_canary_operator_observation_invalid")
    started_at = _timestamp(payload.get("run_started_at"), "aiwritebook_canary_operator_observation_invalid")
    finished_at = _timestamp(payload.get("run_finished_at"), "aiwritebook_canary_operator_observation_invalid")
    if finished_at < started_at:
        raise ValueError("aiwritebook_canary_operator_observation_invalid")
    return {
        "provider_project_ref": project_ref,
        "credits_before": before,
        "credits_after": after,
        "credits_spent": spent,
        "operator_run": True,
        "unattended_browser_automation_used": False,
        "project_private_during_run": True,
        "shared_with_other_users": False,
        "delete_requested": True,
        "project_inaccessible_after_delete": True,
        "outline_reviewed": True,
        "exports_reviewed": True,
        "pdf_content_marker_reviewed": True,
        "publication_started": False,
        "external_send_performed": False,
        "run_started_at": started_at.isoformat(),
        "run_finished_at": finished_at.isoformat(),
    }


def _safe_zip_members(path: Path) -> tuple[zipfile.ZipFile, tuple[str, ...]]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"invalid_export_path:{path.name}")
    if path.stat().st_size <= 0 or path.stat().st_size > MAX_ARTIFACT_BYTES:
        raise ValueError(f"invalid_export_size:{path.name}")
    archive = zipfile.ZipFile(path)
    members = tuple(archive.infolist())
    names = tuple(member.filename for member in members)
    if (
        not names
        or len(names) > MAX_ARCHIVE_MEMBERS
        or len(set(names)) != len(names)
        or sum(member.file_size for member in members) > MAX_ARCHIVE_UNCOMPRESSED_BYTES
    ):
        archive.close()
        raise ValueError(f"invalid_zip_export:{path.name}")
    for member in members:
        name = member.filename
        member = Path(name.replace("\\", "/"))
        if member.is_absolute() or ".." in member.parts:
            archive.close()
            raise ValueError(f"unsafe_zip_member:{path.name}")
    if archive.testzip() is not None:
        archive.close()
        raise ValueError(f"invalid_zip_export:{path.name}")
    return archive, names


def _xml_text(payload: bytes, error: str) -> str:
    try:
        root = ElementTree.fromstring(payload)
    except (ElementTree.ParseError, DefusedXmlException) as exc:
        raise ValueError(error) from exc
    return "".join(root.itertext())


def _inspect_pdf(path: Path, marker: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("invalid_pdf_export_path")
    if path.stat().st_size <= 0 or path.stat().st_size > MAX_ARTIFACT_BYTES:
        raise ValueError("invalid_pdf_export_size")
    payload = path.read_bytes()
    structure_valid = payload.startswith(b"%PDF-") and b"%%EOF" in payload[-2048:]
    if not structure_valid:
        raise ValueError("invalid_pdf_export")
    marker_embedded = marker.encode("utf-8") in payload
    return {"filename": path.name, "sha256": _sha256(payload), "size_bytes": len(payload), "structure_valid": True,
            "content_marker_verified": True, "content_marker_verification": "embedded" if marker_embedded else "human_review"}


def _inspect_docx(path: Path, marker: str) -> dict[str, Any]:
    with _safe_zip_members(path)[0] as archive:
        names = set(archive.namelist())
        required = {"[Content_Types].xml", "_rels/.rels", "word/document.xml"}
        if not required <= names:
            raise ValueError("invalid_docx_export")
        document = _xml_text(archive.read("word/document.xml"), "invalid_docx_document_xml")
        if marker not in document:
            raise ValueError("docx_content_marker_missing")
    payload = path.read_bytes()
    return {"filename": path.name, "sha256": _sha256(payload), "size_bytes": len(payload), "structure_valid": True,
            "content_marker_verified": True, "content_marker_verification": "embedded"}


def _inspect_epub(path: Path, marker: str) -> dict[str, Any]:
    with _safe_zip_members(path)[0] as archive:
        members = archive.infolist()
        names = set(archive.namelist())
        if "mimetype" not in names or "META-INF/container.xml" not in names:
            raise ValueError("invalid_epub_export")
        if (
            members[0].filename != "mimetype"
            or members[0].compress_type != zipfile.ZIP_STORED
            or archive.read("mimetype") != b"application/epub+zip"
        ):
            raise ValueError("invalid_epub_mimetype")
        try:
            container = ElementTree.fromstring(archive.read("META-INF/container.xml"))
        except (ElementTree.ParseError, DefusedXmlException) as exc:
            raise ValueError("invalid_epub_container") from exc
        rootfiles = [node.get("full-path") for node in container.findall(".//{*}rootfile")]
        if len(rootfiles) != 1 or not rootfiles[0] or rootfiles[0] not in names:
            raise ValueError("invalid_epub_rootfile")
        _xml_text(archive.read(rootfiles[0]), "invalid_epub_package")
        searchable = "\n".join(
            _xml_text(archive.read(name), f"invalid_epub_content:{name}")
            for name in sorted(names)
            if name.lower().endswith((".xhtml", ".html", ".htm"))
        )
        if marker not in searchable:
            raise ValueError("epub_content_marker_missing")
    payload = path.read_bytes()
    return {"filename": path.name, "sha256": _sha256(payload), "size_bytes": len(payload), "structure_valid": True,
            "content_marker_verified": True, "content_marker_verification": "embedded"}


def verify_roundtrip(
    *,
    manifest_path: Path,
    approval_path: Path,
    observation_path: Path,
    pdf_path: Path,
    epub_path: Path,
    docx_path: Path,
    generated_at: str | None = None,
) -> dict[str, Any]:
    manifest = _load_object(manifest_path, "aiwritebook_canary_manifest_must_be_an_object")
    _validate_manifest(manifest)
    approval = _load_object(approval_path, "aiwritebook_canary_approval_must_be_an_object")
    maximum = _validate_approval(approval, manifest)
    observation = _load_object(observation_path, "aiwritebook_canary_observation_must_be_an_object")
    run = _validate_observation(observation, manifest, maximum)
    marker = str(manifest.get("content_marker") or "")
    artifacts = {
        "pdf": _inspect_pdf(Path(pdf_path), marker),
        "epub": _inspect_epub(Path(epub_path), marker),
        "docx": _inspect_docx(Path(docx_path), marker),
    }
    return {
        "contract": RECEIPT_CONTRACT,
        "contract_version": 1,
        "status": "pass",
        "generated_at": generated_at or datetime.now(UTC).isoformat(),
        "fixture": {
            "fixture_id": manifest.get("fixture_id"),
            "manifest_sha256": manifest.get("manifest_sha256"),
            "source_sha256": manifest.get("source", {}).get("sha256"),
            "data_classification": "synthetic_no_personal_or_campaign_data",
            "rights": "CC0-1.0",
        },
        "authorization": {
            "approval_contract": APPROVAL_CONTRACT,
            "approved_by_ref": approval.get("approved_by_ref"),
            "approved_at": _timestamp(approval.get("approved_at"), "aiwritebook_canary_approval_invalid").isoformat(),
            "maximum_credits": maximum,
            "provider_project_creation_approved": True,
            "source_upload_approved": True,
            "generation_approved": True,
            "credit_spend_approved": True,
            "export_download_approved": True,
            "provider_project_deletion_approved": True,
            "publication_approved": False,
            "external_send_approved": False,
        },
        "provider_run": run,
        "exports": artifacts,
        "expected_formats": list(EXPECTED_FORMATS),
        "secret_material_in_receipt": False,  # nosec B105
    }


def _write_receipt(path: Path, payload: dict[str, Any], *, replace: bool) -> None:
    for parent in (path.parent, *path.parent.parents):
        if parent.is_symlink():
            raise RuntimeError("output_parent_symlink_not_allowed")
    if path.is_symlink():
        raise RuntimeError("output_symlink_not_allowed")
    if path.exists():
        if not path.is_file():
            raise RuntimeError("output_not_regular_file")
        if not replace:
            raise FileExistsError("output_exists_use_replace")
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = (json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n").encode("utf-8")
    descriptor, raw_temp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    temp = Path(raw_temp)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
        if replace:
            if path.is_symlink() or (path.exists() and not path.is_file()):
                raise RuntimeError("output_target_changed")
            os.replace(temp, path)
        else:
            os.link(temp, path, follow_symlinks=False)
            temp.unlink()
        os.chmod(path, 0o600, follow_symlinks=False)
    finally:
        temp.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify an approved AIWriteBook PDF/EPUB/DOCX canary round trip offline.")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--approval", type=Path, required=True)
    parser.add_argument("--observation", type=Path, required=True)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--epub", type=Path, required=True)
    parser.add_argument("--docx", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    receipt = verify_roundtrip(
        manifest_path=args.manifest,
        approval_path=args.approval,
        observation_path=args.observation,
        pdf_path=args.pdf,
        epub_path=args.epub,
        docx_path=args.docx,
    )
    _write_receipt(args.output, receipt, replace=args.replace)
    print(json.dumps({"status": "pass", "output": str(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
