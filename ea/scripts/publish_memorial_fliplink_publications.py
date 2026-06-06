#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any
from urllib import error, request

from app.services.memorial_archive_registry import archive_slug_root, load_json, normalize_manifest, registry_from_manifests, write_registry


API_BASE = str(os.getenv("FLIPLINK_API_BASE_URL") or "").rstrip("/")
API_KEY = str(os.getenv("FLIPLINK_API_KEY") or "").strip()
CREATE_PATH = str(os.getenv("FLIPLINK_CREATE_PATH") or "/publications").strip() or "/publications"
UPDATE_PATH_TEMPLATE = str(os.getenv("FLIPLINK_UPDATE_PATH_TEMPLATE") or "/publications/{publication_id}").strip()
API_AUTH_HEADER = str(os.getenv("FLIPLINK_API_AUTH_HEADER") or "Authorization").strip() or "Authorization"
API_AUTH_PREFIX = str(os.getenv("FLIPLINK_API_AUTH_PREFIX") or "Bearer ").strip()
METADATA_FIELD = str(os.getenv("FLIPLINK_METADATA_FIELD") or "metadata").strip() or "metadata"
FILE_FIELD = str(os.getenv("FLIPLINK_FILE_FIELD") or "file").strip() or "file"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Publish memorial PDFs to FlipLink")
    parser.add_argument("slug", help="memorial slug")
    parser.add_argument("--dry-run", action="store_true", help="print payloads without network calls")
    parser.add_argument("--skip-registry-sync", action="store_true", help="do not rewrite public archive registry after publish")
    return parser.parse_args()


def iter_manifests(slug_root: Path) -> list[Path]:
    return sorted(slug_root.glob("**/manifest.json"))


def payload_for_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    audience = str(manifest.get("audience") or "public").strip().lower()
    privacy = "public" if audience == "public" else "restricted"
    return {
        "title": manifest.get("title"),
        "slug": manifest.get("fliplink_slug") or manifest.get("document_id"),
        "viewer_type": manifest.get("viewer_type") or "document",
        "privacy": privacy,
        "custom_domain": os.getenv("FLIPLINK_CUSTOM_DOMAIN", "archive.myexternalbrain.com"),
        "noindex": bool(manifest.get("noindex", audience != "public")),
        "branding_profile": os.getenv("FLIPLINK_BRANDING_PROFILE", "manfred-memorial"),
        "audience": audience,
        "sensitivity": manifest.get("sensitivity"),
        "review_status": manifest.get("review_status"),
        "version": manifest.get("version"),
        "description": manifest.get("description"),
    }


def multipart_body(*, metadata: dict[str, Any], pdf_path: Path) -> tuple[bytes, str]:
    boundary = "----ea-fliplink-boundary"
    file_bytes = pdf_path.read_bytes()
    parts: list[bytes] = []
    parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{METADATA_FIELD}\"\r\n\r\n".encode())
    parts.append(json.dumps(metadata).encode())
    parts.append(b"\r\n")
    parts.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"{FILE_FIELD}\"; filename=\"{pdf_path.name}\"\r\nContent-Type: application/pdf\r\n\r\n".encode()
    )
    parts.append(file_bytes)
    parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), boundary


def api_request(*, method: str, path: str, metadata: dict[str, Any], pdf_path: Path) -> dict[str, Any]:
    if not API_BASE or not API_KEY:
        raise SystemExit("FlipLink API configuration missing")
    body, boundary = multipart_body(metadata=metadata, pdf_path=pdf_path)
    headers = {
        API_AUTH_HEADER: f"{API_AUTH_PREFIX}{API_KEY}".strip(),
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Accept": "application/json",
    }
    req = request.Request(API_BASE + path, data=body, method=method.upper(), headers=headers)
    try:
        with request.urlopen(req, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"FlipLink HTTP {exc.code}: {text[:400]}") from exc
    if not isinstance(payload, dict):
        raise SystemExit("FlipLink invalid response payload")
    return payload


def publish_manifest(manifest_path: Path, dry_run: bool) -> dict[str, Any]:
    manifest = normalize_manifest(load_json(manifest_path), manifest_path=manifest_path)
    if not bool(manifest.get("approved")):
        return manifest
    pdf_path = Path(str((manifest.get("build_artifacts") or {}).get("pdf_path") or ""))
    if not pdf_path.is_file():
        return manifest
    metadata = payload_for_manifest(manifest)
    publication_id = str(manifest.get("fliplink_publication_id") or "").strip()
    path = CREATE_PATH
    method = "POST"
    if publication_id and UPDATE_PATH_TEMPLATE:
        path = UPDATE_PATH_TEMPLATE.replace("{publication_id}", publication_id)
        method = "PUT"
    if dry_run:
        print(json.dumps({"manifest": str(manifest_path), "method": method, "path": path, "metadata": metadata}, ensure_ascii=True))
        return manifest
    payload = api_request(method=method, path=path, metadata=metadata, pdf_path=pdf_path)
    manifest["fliplink_publication_id"] = str(payload.get("publication_id") or payload.get("id") or publication_id or "").strip()
    manifest["fliplink_url"] = str(payload.get("url") or manifest.get("fliplink_url") or "").strip()
    manifest["fliplink_embed_code"] = str(payload.get("embed_code") or manifest.get("fliplink_embed_code") or "").strip()
    manifest["fliplink_qr_url"] = str(payload.get("qr_url") or manifest.get("fliplink_qr_url") or "").strip()
    manifest["published_at"] = str(payload.get("published_at") or manifest.get("published_at") or "").strip()
    manifest["review_status"] = "published" if manifest.get("fliplink_url") else manifest.get("review_status")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    args = parse_args()
    slug_root = archive_slug_root(args.slug)
    if not slug_root.is_dir():
        raise SystemExit(f"archive root not found: {slug_root}")
    manifests = [publish_manifest(path, args.dry_run) for path in iter_manifests(slug_root)]
    if not args.skip_registry_sync:
        registry = registry_from_manifests(slug=args.slug, manifests=manifests, include_nonpublic=True)
        write_registry(slug=args.slug, registry=registry)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
