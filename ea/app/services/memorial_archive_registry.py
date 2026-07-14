from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / ".git").is_dir() or (parent / ".codex-design").is_dir():
            return parent
    return current.parents[3]


def _configured_or_existing_path(env_names: tuple[str, ...], candidates: tuple[str, ...]) -> Path:
    for env_name in env_names:
        value = str(os.getenv(env_name) or "").strip()
        if value:
            return Path(value)
    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            return path
    return Path(candidates[0])


ARCHIVE_ROOT = _configured_or_existing_path(
    ("EA_MEMORIAL_ARCHIVE_ROOT", "EA_MEMORIAL_ARCHIVE_DIR"),
    (
        str(_repo_root() / "memorial_archive"),
        "/data/memorial_archive",
    ),
)
PUBLIC_MEMORIAL_ROOT = _configured_or_existing_path(
    ("EA_PUBLIC_MEMORIAL_ROOT", "EA_PUBLIC_MEMORIAL_DIR"),
    (
        str(_repo_root() / "memorial_data" / "public_memorials"),
        "/data/memorial_data/public_memorials",
    ),
)
DEFAULT_CORRECTION_CONTACT = str(os.getenv("EA_MEMORIAL_ARCHIVE_CORRECTION_CONTACT") or "memorial@myexternalbrain.com").strip()
DEFAULT_PUBLIC_REGISTRY_FILENAME = "archive_registry.json"
DEFAULT_GENERATED_REGISTRY_FILENAME = "archive_registry.generated.json"
ALLOWED_AUDIENCES = {"public", "family", "reviewer", "private"}
ALLOWED_VIEWER_TYPES = {"smart_document", "flipbook", "flipbook_3d", "document"}
SAFE_PUBLICATION_KEYS = {
    "approved",
    "id",
    "title",
    "audience",
    "viewer_type",
    "type",
    "url",
    "thumbnail",
    "description",
    "sensitivity",
    "review_status",
    "version",
    "publication_id",
    "slug",
    "noindex",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def safe_slug(slug: str) -> str:
    normalized = str(slug or "").strip().replace("/", "_").replace("..", "_")
    if not normalized:
        raise ValueError("memorial_slug_missing")
    return normalized


def archive_slug_root(slug: str) -> Path:
    return (ARCHIVE_ROOT / safe_slug(slug)).resolve()


def public_registry_path(slug: str, *, generated: bool = False) -> Path:
    filename = DEFAULT_GENERATED_REGISTRY_FILENAME if generated else DEFAULT_PUBLIC_REGISTRY_FILENAME
    return (PUBLIC_MEMORIAL_ROOT / safe_slug(slug) / filename).resolve()


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"invalid_json_object:{path}")
    return payload


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def normalize_manifest(manifest: dict[str, Any], *, manifest_path: Path) -> dict[str, Any]:
    payload = dict(manifest)
    document_id = str(payload.get("document_id") or manifest_path.parent.name).strip()
    audience = str(payload.get("audience") or "").strip().lower()
    if audience not in ALLOWED_AUDIENCES:
        audience = ""
    sensitivity = str(payload.get("sensitivity") or "").strip().upper()
    viewer_type = str(payload.get("viewer_type") or "smart_document").strip().lower()
    if viewer_type not in ALLOWED_VIEWER_TYPES:
        viewer_type = "smart_document"
    review_status = str(payload.get("review_status") or "draft").strip().lower() or "draft"
    version = str(payload.get("version") or "").strip() or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    source_owner = str(payload.get("source_owner") or "Manfred Memorial Archive").strip()
    title = str(payload.get("title") or document_id).strip() or document_id
    correction_contact = str(payload.get("correction_contact") or DEFAULT_CORRECTION_CONTACT).strip()
    payload.update(
        {
            "document_id": document_id,
            "title": title,
            "audience": audience,
            "sensitivity": sensitivity,
            "viewer_type": viewer_type,
            "review_status": review_status,
            "version": version,
            "source_owner": source_owner,
            "correction_contact": correction_contact,
            "approved": payload.get("approved") is True,
            "archive_section_title": str(payload.get("archive_section_title") or {
                "public": "Oeffentliches Archiv",
                "family": "Familienarchiv",
                "reviewer": "Review und Governance",
                "private": "Privat",
            }.get(audience, "Archiv")).strip(),
            "ai_disclosure": str(
                payload.get("ai_disclosure")
                or "AI-assisted formatting, no direct speech claim unless explicitly marked as verbatim source."
            ).strip(),
            "contact_or_correction_path": correction_contact,
            "fliplink_slug": str(payload.get("fliplink_slug") or document_id).strip() or document_id,
            "noindex": bool(payload.get("noindex")) if "noindex" in payload else audience != "public",
            "share_with_memorial_app": audience == "public"
            and bool(payload.get("share_with_memorial_app", True)),
            "public": audience == "public" and bool(payload.get("public", True)),
            "source_files": [str(item).strip() for item in list(payload.get("source_files") or []) if str(item).strip()],
        }
    )
    if not payload["source_files"]:
        payload["source_files"] = ["source.md"]
    return payload


def publication_from_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    publication = {
        "approved": manifest.get("approved") is True,
        "id": str(manifest.get("document_id") or "").strip(),
        "title": str(manifest.get("title") or "").strip(),
        "audience": str(manifest.get("audience") or "").strip().lower(),
        "viewer_type": str(manifest.get("viewer_type") or "smart_document").strip().lower(),
        "type": str(manifest.get("viewer_type") or "smart_document").strip().lower(),
        "url": str(manifest.get("fliplink_url") or "").strip(),
        "thumbnail": str(manifest.get("thumbnail") or "").strip(),
        "description": str(manifest.get("description") or manifest.get("title") or "").strip(),
        "sensitivity": str(manifest.get("sensitivity") or "").strip().upper(),
        "review_status": str(manifest.get("review_status") or "draft").strip().lower(),
        "version": str(manifest.get("version") or "").strip(),
        "publication_id": str(manifest.get("fliplink_publication_id") or "").strip(),
        "slug": str(manifest.get("fliplink_slug") or manifest.get("document_id") or "").strip(),
        "noindex": bool(manifest.get("noindex")),
    }
    return publication


def _publication_is_publicly_releasable(publication: dict[str, Any]) -> bool:
    return (
        publication.get("approved") is True
        and str(publication.get("audience") or "").strip().lower() == "public"
        and str(publication.get("sensitivity") or "").strip().upper() == "PUBLIC"
        and str(publication.get("review_status") or "").strip().lower()
        == "published"
        and bool(str(publication.get("id") or "").strip())
        and bool(str(publication.get("title") or "").strip())
        and bool(str(publication.get("url") or "").strip())
    )


def registry_from_manifests(*, slug: str, manifests: list[dict[str, Any]], include_nonpublic: bool = True) -> dict[str, Any]:
    publications: list[dict[str, Any]] = []
    section_map: dict[str, dict[str, Any]] = {}
    for raw_manifest in manifests:
        manifest = normalize_manifest(raw_manifest, manifest_path=Path(str(raw_manifest.get("_manifest_path") or ".")))
        if not bool(manifest.get("approved")):
            continue
        if str(manifest.get("review_status") or "").strip().lower() not in {"approved", "published"}:
            continue
        publication = publication_from_manifest(manifest)
        if not publication["id"] or not publication["title"] or not publication["url"]:
            continue
        if publication["audience"] not in ALLOWED_AUDIENCES:
            continue
        if publication["audience"] == "public" and publication["sensitivity"] != "PUBLIC":
            continue
        if not include_nonpublic and not _publication_is_publicly_releasable(publication):
            continue
        publications.append(publication)
        section_title = str(manifest.get("archive_section_title") or publication["audience"] or "Archiv").strip()
        section = section_map.setdefault(
            section_title,
            {
                "title": section_title,
                "audience": publication["audience"],
                "items": [],
            },
        )
        if publication["id"] not in section["items"]:
            section["items"].append(publication["id"])
    return {
        "slug": safe_slug(slug),
        "generated_at": utc_now_iso(),
        "archive_sections": list(section_map.values()),
        "fliplink_publications": publications,
    }


def write_registry(*, slug: str, registry: dict[str, Any]) -> None:
    target_dir = (PUBLIC_MEMORIAL_ROOT / safe_slug(slug)).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    for generated in (False, True):
        target = public_registry_path(slug, generated=generated)
        target.write_text(json.dumps(registry, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def public_registry_payload(registry: dict[str, Any]) -> dict[str, Any]:
    publications = []
    by_id: dict[str, dict[str, Any]] = {}
    for item in list(registry.get("fliplink_publications") or []):
        if not isinstance(item, dict):
            continue
        if not _publication_is_publicly_releasable(item):
            continue
        sanitized = {key: item.get(key) for key in SAFE_PUBLICATION_KEYS if key in item}
        publications.append(sanitized)
        by_id[str(sanitized.get("id") or "")] = sanitized
    sections: list[dict[str, Any]] = []
    for item in list(registry.get("archive_sections") or []):
        if not isinstance(item, dict):
            continue
        if str(item.get("audience") or "").strip().lower() != "public":
            continue
        item_ids = [str(entry).strip() for entry in list(item.get("items") or []) if str(entry).strip() in by_id]
        if not item_ids:
            continue
        sections.append(
            {
                "title": str(item.get("title") or "Oeffentliches Archiv").strip(),
                "audience": "public",
                "items": item_ids,
            }
        )
    return {
        "slug": str(registry.get("slug") or "").strip(),
        "generated_at": str(registry.get("generated_at") or "").strip(),
        "archive_sections": sections,
        "fliplink_publications": publications,
    }
