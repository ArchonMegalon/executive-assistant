#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from app.services.fliplink_client import FlipLinkClient, FlipLinkError
from app.services.memorial_archive_registry import archive_slug_root, load_json, normalize_manifest, registry_from_manifests, write_registry


DEFAULT_CREATE_PATH = str(os.getenv("FLIPLINK_CREATE_PATH") or "/publications").strip() or "/publications"
DEFAULT_CUSTOM_DOMAIN = str(os.getenv("FLIPLINK_CUSTOM_DOMAIN") or "archive.myexternalbrain.com").strip()
DEFAULT_BRANDING_PROFILE = str(os.getenv("FLIPLINK_BRANDING_PROFILE") or "manfred-memorial").strip()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Publish memorial PDFs to FlipLink")
    parser.add_argument("slug", help="memorial slug")
    parser.add_argument("--dry-run", action="store_true", help="print payloads without network calls")
    parser.add_argument("--replace", action="store_true", help="republish documents that already have a FlipLink URL")
    parser.add_argument("--public-only", action="store_true", help="publish only public-audience manifests")
    parser.add_argument("--skip-registry-sync", action="store_true", help="do not rewrite public archive registry after publish")
    parser.add_argument("--custom-domain", default="", help="override FLIPLINK_CUSTOM_DOMAIN for this run")
    return parser.parse_args()


def iter_manifests(slug_root: Path) -> list[Path]:
    return sorted(slug_root.glob("**/manifest.json"))


def payload_for_manifest(manifest: dict[str, Any], *, custom_domain: str = "") -> dict[str, Any]:
    audience = str(manifest.get("audience") or "public").strip().lower()
    privacy = "public" if audience == "public" else "restricted"
    return {
        "title": manifest.get("title"),
        "slug": manifest.get("fliplink_slug") or manifest.get("document_id"),
        "viewer_type": manifest.get("viewer_type") or "document",
        "privacy": privacy,
        "custom_domain": custom_domain or DEFAULT_CUSTOM_DOMAIN,
        "noindex": bool(manifest.get("noindex", audience != "public")),
        "branding_profile": DEFAULT_BRANDING_PROFILE,
        "audience": audience,
        "sensitivity": manifest.get("sensitivity"),
        "review_status": manifest.get("review_status"),
        "version": manifest.get("version"),
        "description": manifest.get("description"),
    }


def pdf_path_for_manifest(manifest: dict[str, Any], manifest_path: Path) -> Path:
    build_artifacts = manifest.get("build_artifacts") if isinstance(manifest.get("build_artifacts"), dict) else {}
    raw = str(
        build_artifacts.get("pdf_path")
        or manifest.get("pdf_path")
        or manifest.get("output_pdf")
        or "build/output.pdf"
    ).strip()
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = manifest_path.parent / candidate
    return candidate.resolve()


def publish_manifest(
    manifest_path: Path,
    *,
    dry_run: bool,
    replace: bool,
    custom_domain: str = "",
    public_only: bool = False,
    client: FlipLinkClient | None = None,
) -> dict[str, Any]:
    manifest = normalize_manifest(load_json(manifest_path), manifest_path=manifest_path)
    if not bool(manifest.get("approved")):
        if dry_run:
            print(json.dumps({"manifest": str(manifest_path), "action": "skip_draft"}, ensure_ascii=True))
        return manifest
    review_status = str(manifest.get("review_status") or "").strip().lower()
    if review_status not in {"approved", "published"}:
        if dry_run:
            print(json.dumps({"manifest": str(manifest_path), "action": "skip_review_status", "review_status": review_status}, ensure_ascii=True))
        return manifest
    if public_only and str(manifest.get("audience") or "").strip().lower() != "public":
        if dry_run:
            print(json.dumps({"manifest": str(manifest_path), "action": "skip_non_public"}, ensure_ascii=True))
        return manifest
    if str(manifest.get("fliplink_url") or "").strip() and not replace:
        if dry_run:
            print(
                json.dumps(
                    {
                        "manifest": str(manifest_path),
                        "action": "skip_existing",
                        "fliplink_url": str(manifest.get("fliplink_url") or "").strip(),
                    },
                    ensure_ascii=True,
                )
            )
        return manifest
    pdf_path = pdf_path_for_manifest(manifest, manifest_path)
    if not pdf_path.is_file():
        if dry_run:
            print(json.dumps({"manifest": str(manifest_path), "action": "skip_missing_pdf", "pdf_path": str(pdf_path)}, ensure_ascii=True))
        return manifest
    metadata = payload_for_manifest(manifest, custom_domain=custom_domain)
    publication_id = str(manifest.get("fliplink_publication_id") or "").strip()
    path = DEFAULT_CREATE_PATH
    method = "POST"
    if publication_id:
        path = str(os.getenv("FLIPLINK_UPDATE_PATH_TEMPLATE") or "/publications/{publication_id}").replace("{publication_id}", publication_id)
        method = "PUT"
    if dry_run:
        print(json.dumps({"manifest": str(manifest_path), "action": "publish", "method": method, "path": path, "metadata": metadata}, ensure_ascii=True))
        return manifest
    publisher = client or FlipLinkClient()
    try:
        payload = publisher.publish_pdf(pdf_path=pdf_path, metadata=metadata, publication_id=publication_id)
    except FlipLinkError as exc:
        raise SystemExit(f"FlipLink publish failed for {manifest_path}: {exc}") from exc
    manifest["fliplink_publication_id"] = str(payload.get("publication_id") or publication_id or "").strip()
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
    client = None if args.dry_run else FlipLinkClient()
    manifests = [
        publish_manifest(
            path,
            dry_run=args.dry_run,
            replace=args.replace,
            custom_domain=args.custom_domain,
            public_only=args.public_only,
            client=client,
        )
        for path in iter_manifests(slug_root)
    ]
    if not args.skip_registry_sync:
        registry = registry_from_manifests(slug=args.slug, manifests=manifests, include_nonpublic=True)
        write_registry(slug=args.slug, registry=registry)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
