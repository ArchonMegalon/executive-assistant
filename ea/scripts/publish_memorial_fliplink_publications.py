#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any
from urllib import request

ARCHIVE_ROOT = Path(os.getenv("EA_MEMORIAL_ARCHIVE_ROOT", "/docker/EA/memorial_archive"))
API_BASE = str(os.getenv("FLIPLINK_API_BASE_URL") or "").rstrip("/")
CREATE_PATH = str(os.getenv("FLIPLINK_CREATE_PATH") or "/publications")
API_KEY = str(os.getenv("FLIPLINK_API_KEY") or "").strip()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Publish memorial PDFs to FlipLink")
    parser.add_argument("slug", help="memorial slug")
    parser.add_argument("--dry-run", action="store_true", help="print payloads without network calls")
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"invalid manifest: {path}")
    return payload


def iter_manifests(slug_root: Path) -> list[Path]:
    return sorted(slug_root.glob("**/manifest.json"))


def payload_for_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    privacy = "public" if str(manifest.get("audience") or "public").strip().lower() == "public" else "restricted"
    return {
        "title": manifest.get("title"),
        "slug": manifest.get("fliplink_slug") or manifest.get("document_id"),
        "viewer_type": manifest.get("viewer_type") or "document",
        "privacy": privacy,
        "custom_domain": os.getenv("FLIPLINK_CUSTOM_DOMAIN", "archive.myexternalbrain.com"),
        "noindex": privacy != "public",
        "branding_profile": os.getenv("FLIPLINK_BRANDING_PROFILE", "manfred-memorial"),
        "audience": manifest.get("audience"),
        "sensitivity": manifest.get("sensitivity"),
        "review_status": manifest.get("review_status"),
        "version": manifest.get("version"),
    }


def publish_manifest(manifest_path: Path, dry_run: bool) -> dict[str, Any]:
    manifest = load_json(manifest_path)
    if not bool(manifest.get("approved")):
        return manifest
    pdf_path = Path(str((manifest.get("build_artifacts") or {}).get("pdf_path") or ""))
    if not pdf_path.is_file():
        return manifest
    meta = payload_for_manifest(manifest)
    if dry_run:
        print(json.dumps({"manifest": str(manifest_path), "metadata": meta}, ensure_ascii=True))
        return manifest
    if not API_BASE or not API_KEY:
        raise SystemExit("FlipLink API configuration missing")
    boundary = "----ea-fliplink-boundary"
    file_bytes = pdf_path.read_bytes()
    parts: list[bytes] = []
    parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"metadata\"\r\n\r\n".encode())
    parts.append(json.dumps(meta).encode())
    parts.append(b"\r\n")
    parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{pdf_path.name}\"\r\nContent-Type: application/pdf\r\n\r\n".encode())
    parts.append(file_bytes)
    parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(parts)
    req = request.Request(
        API_BASE + CREATE_PATH,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Accept": "application/json",
        },
    )
    with request.urlopen(req, timeout=60) as response:
        payload = json.loads(response.read().decode("utf-8"))
    manifest["fliplink_publication_id"] = str(payload.get("publication_id") or payload.get("id") or "").strip()
    manifest["fliplink_url"] = str(payload.get("url") or manifest.get("fliplink_url") or "").strip()
    manifest["published_at"] = str(payload.get("published_at") or "").strip()
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    args = parse_args()
    slug_root = ARCHIVE_ROOT / args.slug
    if not slug_root.is_dir():
        raise SystemExit(f"archive root not found: {slug_root}")
    for manifest_path in iter_manifests(slug_root):
        publish_manifest(manifest_path, args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
