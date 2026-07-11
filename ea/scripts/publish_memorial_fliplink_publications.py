#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import urllib.parse
from pathlib import Path
from typing import Any

EA_APP_ROOT = Path(__file__).resolve().parents[1]
if str(EA_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(EA_APP_ROOT))

from app.services.fliplink_client import FlipLinkClient, FlipLinkError  # noqa: E402
from app.services.memorial_archive_registry import (  # noqa: E402
    archive_slug_root,
    load_json,
    normalize_manifest,
    public_registry_path,
    public_registry_payload,
    registry_from_manifests,
)


DEFAULT_CREATE_PATH = str(os.getenv("FLIPLINK_CREATE_PATH") or "/publications").strip() or "/publications"
DEFAULT_CUSTOM_DOMAIN = str(os.getenv("FLIPLINK_CUSTOM_DOMAIN") or "archive.myexternalbrain.com").strip()
DEFAULT_BRANDING_PROFILE = str(os.getenv("FLIPLINK_BRANDING_PROFILE") or "manfred-memorial").strip()
_PLACEHOLDER_HOSTS = {"example.test", "localhost"}
_ROUTE_SEGMENT_RE = re.compile(r"[a-z0-9](?:[a-z0-9_-]{0,126}[a-z0-9])?")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Publish memorial PDFs to FlipLink")
    parser.add_argument("slug", help="memorial slug")
    parser.add_argument("--dry-run", action="store_true", help="print payloads without network calls or file writes")
    parser.add_argument("--replace", action="store_true", help="republish documents that already have a real FlipLink URL")
    parser.add_argument("--public-only", action="store_true", help="publish only public-audience manifests")
    parser.add_argument("--skip-registry-sync", action="store_true", help="do not rewrite public archive registry after publish")
    parser.add_argument("--custom-domain", default="", help="override FLIPLINK_CUSTOM_DOMAIN for this run")
    return parser.parse_args()


def _contained_path(root: Path, candidate: Path, *, error: str) -> Path:
    resolved_root = root.resolve()
    resolved_candidate = candidate.resolve()
    if not resolved_candidate.is_relative_to(resolved_root):
        raise ValueError(f"{error}:{candidate}")
    return resolved_candidate


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _is_publishable_url(value: object) -> bool:
    normalized = str(value or "").strip()
    if not normalized:
        return False
    try:
        parsed = urllib.parse.urlparse(normalized)
        hostname = str(parsed.hostname or "").strip().lower().rstrip(".")
    except ValueError:
        return False
    if parsed.scheme.lower() != "https" or not hostname:
        return False
    if hostname in _PLACEHOLDER_HOSTS or hostname.endswith(".example.test"):
        return False
    if hostname.endswith(".invalid") or hostname.endswith(".localhost"):
        return False
    return "placeholder" not in hostname


def _safe_route_segment(value: object) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if _ROUTE_SEGMENT_RE.fullmatch(normalized) else ""


def _public_registry_manifest(
    *, slug: str, slug_root: Path, manifest: dict[str, Any]
) -> dict[str, Any] | None:
    if not bool(manifest.get("approved")):
        return None
    if str(manifest.get("audience") or "").strip().lower() != "public":
        return None
    if str(manifest.get("review_status") or "").strip().lower() not in {"approved", "published"}:
        return None
    projected = dict(manifest)
    if _is_publishable_url(projected.get("fliplink_url")):
        projected["review_status"] = "published"
        return projected

    memorial_slug = _safe_route_segment(slug)
    publication_slug = _safe_route_segment(projected.get("fliplink_slug") or projected.get("document_id"))
    raw_manifest_path = str(projected.get("_manifest_path") or "").strip()
    if not memorial_slug or not publication_slug or not raw_manifest_path:
        return None
    resolved_root = slug_root.resolve()
    try:
        public_root = _contained_path(resolved_root, resolved_root / "public", error="archive_public_path_escape")
        manifest_path = _contained_path(public_root, Path(raw_manifest_path), error="manifest_path_escape")
        if manifest_path.name != "manifest.json":
            return None
        document_root = manifest_path.parent
        expected_html = _contained_path(
            document_root, document_root / "build" / "index.html", error="memorial_html_path_escape"
        )
        build_artifacts = (
            projected.get("build_artifacts") if isinstance(projected.get("build_artifacts"), dict) else {}
        )
        configured_html = Path(str(build_artifacts.get("html_path") or "build/index.html").strip())
        if not configured_html.is_absolute():
            configured_html = document_root / configured_html
        configured_html = _contained_path(document_root, configured_html, error="memorial_html_path_escape")
    except (OSError, RuntimeError, ValueError):
        return None
    if configured_html != expected_html or not expected_html.is_file():
        return None
    projected["fliplink_url"] = f"/memorials/{memorial_slug}/archive/{publication_slug}"
    projected["review_status"] = "published"
    projected["publication_provider"] = "internal"
    return projected


def _registry_from_publishable_public_manifests(
    *, slug: str, manifests: list[dict[str, Any]], slug_root: Path | None = None
) -> dict[str, Any]:
    resolved_root = (slug_root or archive_slug_root(slug)).resolve()
    eligible = [
        projected
        for manifest in manifests
        if (projected := _public_registry_manifest(slug=slug, slug_root=resolved_root, manifest=manifest)) is not None
    ]
    registry = registry_from_manifests(slug=slug, manifests=eligible, include_nonpublic=False)
    return public_registry_payload(registry)


def _write_public_registry(*, slug: str, registry: dict[str, Any]) -> None:
    serialized = json.dumps(public_registry_payload(registry), ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    for generated in (False, True):
        target = public_registry_path(slug, generated=generated)
        _atomic_write_text(target, serialized)


def iter_manifests(slug_root: Path) -> list[Path]:
    resolved_root = slug_root.resolve()
    manifests: list[Path] = []
    for section in ("public", "family", "review"):
        section_root = _contained_path(resolved_root, resolved_root / section, error="archive_section_path_escape")
        if not section_root.is_dir():
            continue
        for manifest_path in sorted(section_root.glob("*/manifest.json")):
            manifests.append(_contained_path(resolved_root, manifest_path, error="manifest_path_escape"))
    return manifests


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
    resolved_manifest = manifest_path.resolve()
    document_root = resolved_manifest.parent
    build_artifacts = manifest.get("build_artifacts") if isinstance(manifest.get("build_artifacts"), dict) else {}
    raw = str(
        build_artifacts.get("pdf_path")
        or manifest.get("pdf_path")
        or manifest.get("output_pdf")
        or "build/output.pdf"
    ).strip()
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = document_root / candidate
    return _contained_path(document_root, candidate, error="memorial_pdf_path_escape")


def publish_manifest(
    manifest_path: Path,
    *,
    dry_run: bool,
    replace: bool,
    custom_domain: str = "",
    public_only: bool = False,
    client: FlipLinkClient | None = None,
    archive_root: Path | None = None,
) -> dict[str, Any]:
    resolved_manifest = manifest_path.resolve()
    if archive_root is not None:
        resolved_manifest = _contained_path(archive_root, resolved_manifest, error="manifest_path_escape")
    manifest = normalize_manifest(load_json(resolved_manifest), manifest_path=resolved_manifest)
    manifest["_manifest_path"] = str(resolved_manifest)
    if not bool(manifest.get("approved")):
        if dry_run:
            print(json.dumps({"manifest": str(resolved_manifest), "action": "skip_draft"}, ensure_ascii=True))
        return manifest
    review_status = str(manifest.get("review_status") or "").strip().lower()
    if review_status not in {"approved", "published"}:
        if dry_run:
            print(
                json.dumps(
                    {"manifest": str(resolved_manifest), "action": "skip_review_status", "review_status": review_status},
                    ensure_ascii=True,
                )
            )
        return manifest
    if public_only and str(manifest.get("audience") or "").strip().lower() != "public":
        if dry_run:
            print(json.dumps({"manifest": str(resolved_manifest), "action": "skip_non_public"}, ensure_ascii=True))
        return manifest
    existing_url = str(manifest.get("fliplink_url") or "").strip()
    if _is_publishable_url(existing_url) and not replace:
        if dry_run:
            print(
                json.dumps(
                    {"manifest": str(resolved_manifest), "action": "skip_existing", "fliplink_url": existing_url},
                    ensure_ascii=True,
                )
            )
        return manifest
    pdf_path = pdf_path_for_manifest(manifest, resolved_manifest)
    if not pdf_path.is_file():
        if dry_run:
            print(
                json.dumps(
                    {"manifest": str(resolved_manifest), "action": "skip_missing_pdf", "pdf_path": str(pdf_path)},
                    ensure_ascii=True,
                )
            )
        return manifest
    metadata = payload_for_manifest(manifest, custom_domain=custom_domain)
    publication_id = str(manifest.get("fliplink_publication_id") or "").strip()
    path = DEFAULT_CREATE_PATH
    method = "POST"
    if publication_id:
        path = str(os.getenv("FLIPLINK_UPDATE_PATH_TEMPLATE") or "/publications/{publication_id}").replace(
            "{publication_id}", publication_id
        )
        method = "PUT"
    if dry_run:
        print(
            json.dumps(
                {"manifest": str(resolved_manifest), "action": "publish", "method": method, "path": path, "metadata": metadata},
                ensure_ascii=True,
            )
        )
        return manifest
    publisher = client or FlipLinkClient()
    try:
        payload = publisher.publish_pdf(pdf_path=pdf_path, metadata=metadata, publication_id=publication_id)
    except FlipLinkError as exc:
        raise SystemExit(f"FlipLink publish failed for {resolved_manifest}: {exc}") from exc
    published_url = str(payload.get("url") or "").strip()
    if not _is_publishable_url(published_url):
        raise SystemExit(f"FlipLink publish returned an unpublished URL for {resolved_manifest}")
    manifest["fliplink_publication_id"] = str(payload.get("publication_id") or publication_id or "").strip()
    manifest["fliplink_url"] = published_url
    manifest["fliplink_embed_code"] = str(payload.get("embed_code") or "").strip()
    manifest["fliplink_qr_url"] = str(payload.get("qr_url") or "").strip()
    manifest["published_at"] = str(payload.get("published_at") or "").strip()
    manifest["review_status"] = "published"
    serialized_manifest = {key: value for key, value in manifest.items() if not str(key).startswith("_")}
    _atomic_write_text(resolved_manifest, json.dumps(serialized_manifest, ensure_ascii=True, indent=2) + "\n")
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
            archive_root=slug_root,
        )
        for path in iter_manifests(slug_root)
    ]
    if not args.dry_run and not args.skip_registry_sync:
        registry = _registry_from_publishable_public_manifests(
            slug=args.slug, manifests=manifests, slug_root=slug_root
        )
        _write_public_registry(slug=args.slug, registry=registry)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
