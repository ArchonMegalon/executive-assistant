from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


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


def _repo_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / ".git").is_dir() or (parent / ".codex-design").is_dir():
            return parent
    return current.parents[3]


def _public_registry_root() -> Path:
    configured = str(os.getenv("EA_ARCHIVE_PUBLIC_REGISTRY_ROOT") or "").strip()
    if configured:
        return Path(configured).expanduser()
    return _repo_root() / "archive_data" / "public"


def safe_slug(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized or normalized in {".", ".."} or "/" in normalized or "\\" in normalized:
        raise ValueError("archive_slug_invalid")
    return normalized


def public_registry_path(slug: str, *, generated: bool = False) -> Path:
    filename = "archive_registry.generated.json" if generated else "archive_registry.json"
    return (_public_registry_root() / safe_slug(slug) / filename).resolve()


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("archive_registry_invalid")
    return payload


def _publication_is_publicly_releasable(publication: dict[str, Any]) -> bool:
    return (
        publication.get("approved") is True
        and str(publication.get("audience") or "").strip().lower() == "public"
        and str(publication.get("sensitivity") or "").strip().upper() == "PUBLIC"
        and str(publication.get("review_status") or "").strip().lower() == "published"
        and bool(str(publication.get("id") or "").strip())
        and bool(str(publication.get("title") or "").strip())
        and bool(str(publication.get("url") or "").strip())
    )


def public_registry_payload(registry: dict[str, Any]) -> dict[str, Any]:
    publications: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    for item in list(registry.get("fliplink_publications") or []):
        if not isinstance(item, dict) or not _publication_is_publicly_releasable(item):
            continue
        sanitized = {key: item.get(key) for key in SAFE_PUBLICATION_KEYS if key in item}
        publications.append(sanitized)
        by_id[str(sanitized.get("id") or "")] = sanitized
    sections: list[dict[str, Any]] = []
    for item in list(registry.get("archive_sections") or []):
        if not isinstance(item, dict) or str(item.get("audience") or "").strip().lower() != "public":
            continue
        item_ids = [
            str(entry).strip()
            for entry in list(item.get("items") or [])
            if str(entry).strip() in by_id
        ]
        if item_ids:
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
