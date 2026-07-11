#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import textwrap
import urllib.parse
from html import escape
from pathlib import Path
from typing import Any

EA_APP_ROOT = Path(__file__).resolve().parents[1]
if str(EA_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(EA_APP_ROOT))

from app.services.memorial_archive_registry import (  # noqa: E402
    archive_slug_root,
    normalize_manifest,
    public_registry_path,
    public_registry_payload,
    registry_from_manifests,
    sha256_bytes,
    utc_now_iso,
)


DEFAULT_TEMPLATE = "templates/memorial_document.css"
DISCLOSURE = (
    "Dieses Dokument gehört zu einem kuratierten Gedenkarchiv. Es kann Originalquellen, "
    "Familienerinnerungen und KI-unterstützte Formatierung enthalten. KI-formulierter Text ist keine direkte "
    "Rede von Manfred, sofern er nicht ausdrücklich als wörtliche Quelle gekennzeichnet ist. "
    "Sensible oder unsichere Inhalte sind entsprechend markiert."
)
_ROUTE_SEGMENT_RE = re.compile(r"[a-z0-9](?:[a-z0-9_-]{0,126}[a-z0-9])?")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build memorial archive documents and sync the public archive registry")
    parser.add_argument("slug", help="memorial slug")
    parser.add_argument("--require-pdf", action="store_true", help="fail if no PDF artifact is produced")
    return parser.parse_args()


def _contained_path(root: Path, candidate: Path, *, error: str) -> Path:
    resolved_root = root.resolve()
    resolved_candidate = candidate.resolve()
    if not resolved_candidate.is_relative_to(resolved_root):
        raise ValueError(f"{error}:{candidate}")
    return resolved_candidate


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _atomic_write_text(path: Path, text: str) -> None:
    _atomic_write(path, text.encode("utf-8"))


def _is_publishable_url(value: object) -> bool:
    try:
        parsed = urllib.parse.urlparse(str(value or "").strip())
        hostname = str(parsed.hostname or "").strip().lower().rstrip(".")
    except ValueError:
        return False
    if parsed.scheme.lower() != "https" or not hostname:
        return False
    if hostname in {"example.test", "localhost"} or hostname.endswith(".example.test"):
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


def _public_registry_from_manifests(
    *, slug: str, slug_root: Path, manifests: list[dict[str, Any]]
) -> dict[str, Any]:
    eligible = [
        projected
        for manifest in manifests
        if (projected := _public_registry_manifest(slug=slug, slug_root=slug_root, manifest=manifest)) is not None
    ]
    registry = registry_from_manifests(slug=slug, manifests=eligible, include_nonpublic=False)
    return public_registry_payload(registry)


def _write_public_registry(*, slug: str, slug_root: Path, manifests: list[dict[str, Any]]) -> None:
    public_registry = _public_registry_from_manifests(slug=slug, slug_root=slug_root, manifests=manifests)
    serialized = json.dumps(public_registry, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    for generated in (False, True):
        _atomic_write_text(public_registry_path(slug, generated=generated), serialized)


def list_documents(slug_root: Path) -> list[Path]:
    resolved_root = slug_root.resolve()
    manifests: list[Path] = []
    for section in ("public", "family", "review"):
        section_root = _contained_path(resolved_root, resolved_root / section, error="archive_section_path_escape")
        if not section_root.is_dir():
            continue
        for manifest_path in sorted(section_root.glob("*/manifest.json")):
            manifests.append(_contained_path(resolved_root, manifest_path, error="manifest_path_escape"))
    return manifests


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"invalid_manifest:{path}")
    return payload


def simple_markdown_to_html(text: str) -> str:
    lines = text.splitlines()
    blocks: list[str] = []
    in_list = False
    for raw in lines:
        line = raw.strip()
        if not line:
            if in_list:
                blocks.append("</ul>")
                in_list = False
            continue
        if line.startswith("# "):
            if in_list:
                blocks.append("</ul>")
                in_list = False
            blocks.append(f"<h1>{escape(line[2:].strip())}</h1>")
            continue
        if line.startswith("## "):
            if in_list:
                blocks.append("</ul>")
                in_list = False
            blocks.append(f"<h2>{escape(line[3:].strip())}</h2>")
            continue
        if line.startswith("- "):
            if not in_list:
                blocks.append("<ul>")
                in_list = True
            blocks.append(f"<li>{escape(line[2:].strip())}</li>")
            continue
        if in_list:
            blocks.append("</ul>")
            in_list = False
        blocks.append(f"<p>{escape(line)}</p>")
    if in_list:
        blocks.append("</ul>")
    return "\n".join(blocks)


def load_css(slug_root: Path) -> str:
    css_path = _contained_path(slug_root, slug_root / DEFAULT_TEMPLATE, error="archive_template_path_escape")
    return css_path.read_text(encoding="utf-8") if css_path.is_file() else ""


def wrap_h2_sections(body_html: str) -> str:
    text = str(body_html or "").strip()
    if not text:
        return ""
    parts = re.split(r"(<h2>.*?</h2>)", text, flags=re.DOTALL)
    if len(parts) == 1:
        return text
    rendered: list[str] = []
    if parts[0].strip():
        rendered.append(parts[0].strip())
    index = 1
    while index < len(parts):
        heading = parts[index].strip()
        content = parts[index + 1].strip() if index + 1 < len(parts) else ""
        if heading:
            rendered.append(f'<section class="doc-section">{heading}\n{content}</section>'.strip())
        elif content:
            rendered.append(content)
        index += 2
    return "\n".join(item for item in rendered if item)


def render_html(*, manifest: dict[str, Any], markdown: str, css: str) -> str:
    body_html = wrap_h2_sections(simple_markdown_to_html(markdown))
    return f"""<!doctype html>
<html lang="de">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{escape(str(manifest.get("title") or ""))}</title>
    <style>{css}</style>
  </head>
  <body>
    <main>
      <header>
        <div class="kicker">Manfred Gedenkarchiv</div>
        <h1>{escape(str(manifest.get("title") or ""))}</h1>
        <div class="meta">
          <div><strong>Publikum</strong><br>{escape(str(manifest.get("audience") or ""))}</div>
          <div><strong>Version</strong><br>{escape(str(manifest.get("version") or ""))}</div>
          <div><strong>Veröffentlicht</strong><br>{escape(str(manifest.get("published_date") or manifest.get("version") or ""))}</div>
          <div><strong>Quellenverantwortung</strong><br>{escape(str(manifest.get("source_owner") or ""))}</div>
          <div><strong>Prüfstatus</strong><br>{escape(str(manifest.get("review_status") or ""))}</div>
          <div><strong>Sensibilität</strong><br>{escape(str(manifest.get("sensitivity") or ""))}</div>
          <div><strong>KI-Hinweis</strong><br>{escape(str(manifest.get("ai_disclosure") or ""))}</div>
          <div><strong>Korrekturen</strong><br>{escape(str(manifest.get("contact_or_correction_path") or ""))}</div>
        </div>
      </header>
      <div class="callout">{escape(DISCLOSURE)}</div>
      {body_html}
      <footer>Manfred Gedenkarchiv · Version {escape(str(manifest.get("version") or ""))} · Quellenstatus: {escape(str(manifest.get("review_status") or ""))}</footer>
    </main>
  </body>
</html>
"""


def _pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def write_simple_pdf(*, path: Path, title: str, body_text: str) -> None:
    width = 595
    height = 842
    left = 54
    top = 786
    line_height = 16
    max_chars = 92
    max_lines_per_page = 44
    paragraphs = [segment.strip() for segment in body_text.splitlines()]
    wrapped_lines: list[str] = []
    for paragraph in paragraphs:
        if not paragraph:
            wrapped_lines.append("")
            continue
        wrapped_lines.extend(
            textwrap.wrap(paragraph, width=max_chars, break_long_words=False, break_on_hyphens=False) or [paragraph]
        )
    pages: list[list[str]] = []
    current: list[str] = []
    for line in [title, "", *wrapped_lines]:
        current.append(line)
        if len(current) >= max_lines_per_page:
            pages.append(current)
            current = []
    if current:
        pages.append(current)
    if not pages:
        pages = [[title]]
    objects: list[bytes] = []
    page_object_ids: list[int] = []
    catalog_id, pages_id, font_id, next_id = 1, 2, 3, 4
    for page_lines in pages:
        commands = ["BT", "/F1 12 Tf"]
        y = top
        for index, line in enumerate(page_lines):
            if index == 0:
                commands.append("/F1 18 Tf")
            commands.append(f"1 0 0 1 {left} {y} Tm ({_pdf_escape(line)}) Tj")
            if index == 0:
                commands.append("/F1 12 Tf")
            y -= line_height if line else line_height // 2
        commands.append("ET")
        stream = "\n".join(commands).encode("latin-1", errors="replace")
        content_id = next_id
        next_id += 1
        page_id = next_id
        next_id += 1
        page_object_ids.append(page_id)
        objects.append(
            f"{content_id} 0 obj\n<< /Length {len(stream)} >>\nstream\n".encode("ascii")
            + stream
            + b"\nendstream\nendobj\n"
        )
        objects.append(
            f"{page_id} 0 obj\n<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 {width} {height}] "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {content_id} 0 R >>\nendobj\n".encode(
                "ascii"
            )
        )
    header = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
    base_objects = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        (
            f"2 0 obj\n<< /Type /Pages /Count {len(page_object_ids)} "
            f"/Kids [{' '.join(f'{page_id} 0 R' for page_id in page_object_ids)}] >>\nendobj\n"
        ).encode("ascii"),
        b"3 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n",
    ]
    xref_offsets = [0]
    output = bytearray(header)
    for item in base_objects + objects:
        xref_offsets.append(len(output))
        output.extend(item)
    xref_start = len(output)
    output.extend(f"xref\n0 {len(xref_offsets)}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in xref_offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        f"trailer\n<< /Size {len(xref_offsets)} /Root {catalog_id} 0 R >>\nstartxref\n{xref_start}\n%%EOF\n".encode(
            "ascii"
        )
    )
    _atomic_write(path, bytes(output))


def build_document(manifest_path: Path, slug_root: Path, require_pdf: bool) -> dict[str, Any]:
    resolved_root = slug_root.resolve()
    resolved_manifest = _contained_path(resolved_root, manifest_path, error="manifest_path_escape")
    manifest = normalize_manifest(load_json(resolved_manifest), manifest_path=resolved_manifest)
    document_root = resolved_manifest.parent
    source_path = _contained_path(document_root, document_root / "source.md", error="memorial_source_path_escape")
    if not source_path.is_file():
        raise ValueError(f"missing_source_markdown:{resolved_manifest}")
    css = load_css(resolved_root)
    markdown = source_path.read_text(encoding="utf-8")
    html_text = render_html(manifest=manifest, markdown=markdown, css=css)
    build_dir = _contained_path(document_root, document_root / "build", error="memorial_build_path_escape")
    build_dir.mkdir(parents=True, exist_ok=True)
    html_path = _contained_path(document_root, build_dir / "index.html", error="memorial_html_path_escape")
    pdf_path = _contained_path(document_root, build_dir / "output.pdf", error="memorial_pdf_path_escape")
    _atomic_write_text(html_path, html_text)
    write_simple_pdf(
        path=pdf_path,
        title=str(manifest.get("title") or "Memorial document"),
        body_text="\n".join(line.rstrip() for line in markdown.splitlines()),
    )
    if require_pdf and not pdf_path.is_file():
        raise ValueError(f"pdf_generation_failed:{manifest.get('document_id')}")
    manifest["published_date"] = str(manifest.get("published_date") or manifest.get("version") or "")
    manifest["build_artifacts"] = {"html_path": "build/index.html", "pdf_path": "build/output.pdf"}
    manifest["source_files"] = list(manifest.get("source_files") or ["source.md"])
    manifest["sha256"] = sha256_bytes(html_text.encode("utf-8"))
    manifest["source_sha256"] = sha256_bytes(markdown.encode("utf-8"))
    manifest["built_at"] = utc_now_iso()
    manifest["_manifest_path"] = str(resolved_manifest)
    serialized = {key: value for key, value in manifest.items() if not str(key).startswith("_")}
    _atomic_write_text(resolved_manifest, json.dumps(serialized, ensure_ascii=True, indent=2) + "\n")
    return manifest


def main() -> int:
    args = parse_args()
    slug_root = archive_slug_root(args.slug)
    if not slug_root.is_dir():
        raise SystemExit(f"archive root not found: {slug_root}")
    manifests = [build_document(path, slug_root, args.require_pdf) for path in list_documents(slug_root)]
    _write_public_registry(slug=args.slug, slug_root=slug_root, manifests=manifests)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
