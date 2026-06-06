#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import textwrap
from html import escape
from pathlib import Path
from typing import Any

from app.services.memorial_archive_registry import (
    archive_slug_root,
    normalize_manifest,
    registry_from_manifests,
    sha256_bytes,
    utc_now_iso,
    write_registry,
)


DEFAULT_TEMPLATE = "templates/memorial_document.css"
DISCLOSURE = (
    "This document is part of a memorial archive. It may include original sources, family recollections, "
    "and AI-assisted formatting. AI-generated text is not direct speech from Manfred unless explicitly marked "
    "as a verbatim source. Sensitive or uncertain material is labeled accordingly."
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build memorial archive documents and sync archive registry")
    parser.add_argument("slug", help="memorial slug")
    parser.add_argument("--require-pdf", action="store_true", help="fail if no PDF backend is available")
    return parser.parse_args()


def list_documents(slug_root: Path) -> list[Path]:
    manifests: list[Path] = []
    for section in ("public", "family", "review"):
        section_root = slug_root / section
        if section_root.is_dir():
            manifests.extend(sorted(section_root.glob("*/manifest.json")))
    return manifests


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"invalid manifest: {path}")
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
    css_path = slug_root / DEFAULT_TEMPLATE
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
        <div class="kicker">Manfred Memorial Archive</div>
        <h1>{escape(str(manifest.get("title") or ""))}</h1>
        <div class="meta">
          <div><strong>Audience</strong><br>{escape(str(manifest.get("audience") or ""))}</div>
          <div><strong>Version</strong><br>{escape(str(manifest.get("version") or ""))}</div>
          <div><strong>Published</strong><br>{escape(str(manifest.get("published_date") or manifest.get("version") or ""))}</div>
          <div><strong>Source owner</strong><br>{escape(str(manifest.get("source_owner") or ""))}</div>
          <div><strong>Review status</strong><br>{escape(str(manifest.get("review_status") or ""))}</div>
          <div><strong>Sensitivity</strong><br>{escape(str(manifest.get("sensitivity") or ""))}</div>
          <div><strong>AI disclosure</strong><br>{escape(str(manifest.get("ai_disclosure") or ""))}</div>
          <div><strong>Corrections</strong><br>{escape(str(manifest.get("contact_or_correction_path") or ""))}</div>
        </div>
      </header>
      <div class="callout">{escape(DISCLOSURE)}</div>
      {body_html}
      <footer>Manfred Memorial Archive · Version {escape(str(manifest.get("version") or ""))} · Source status: {escape(str(manifest.get("review_status") or ""))}</footer>
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
        wrapped_lines.extend(textwrap.wrap(paragraph, width=max_chars, break_long_words=False, break_on_hyphens=False) or [paragraph])
    pages: list[list[str]] = []
    current: list[str] = []
    for line in [title, ""] + wrapped_lines:
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
        for idx, line in enumerate(page_lines):
            size = 18 if idx == 0 else 12
            if idx == 0:
                commands.append(f"/F1 {size} Tf")
            commands.append(f"1 0 0 1 {left} {y} Tm ({_pdf_escape(line)}) Tj")
            if idx == 0:
                commands.append("/F1 12 Tf")
            y -= line_height if line else line_height // 2
        commands.append("ET")
        stream = "\n".join(commands).encode("latin-1", errors="replace")
        content_id = next_id
        next_id += 1
        page_id = next_id
        next_id += 1
        page_object_ids.append(page_id)
        objects.append(f"{content_id} 0 obj\n<< /Length {len(stream)} >>\nstream\n".encode("ascii") + stream + b"\nendstream\nendobj\n")
        objects.append(
            f"{page_id} 0 obj\n<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 {width} {height}] "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {content_id} 0 R >>\nendobj\n".encode("ascii")
        )
    header = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
    base_objects = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        f"2 0 obj\n<< /Type /Pages /Count {len(page_object_ids)} /Kids [{' '.join(f'{page_id} 0 R' for page_id in page_object_ids)}] >>\nendobj\n".encode("ascii"),
        b"3 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n",
    ]
    xref_offsets = [0]
    output = bytearray(header)
    for obj in base_objects + objects:
        xref_offsets.append(len(output))
        output.extend(obj)
    xref_start = len(output)
    output.extend(f"xref\n0 {len(xref_offsets)}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in xref_offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(f"trailer\n<< /Size {len(xref_offsets)} /Root {catalog_id} 0 R >>\nstartxref\n{xref_start}\n%%EOF\n".encode("ascii"))
    path.write_bytes(bytes(output))


def build_document(manifest_path: Path, slug_root: Path, require_pdf: bool) -> dict[str, Any]:
    manifest = normalize_manifest(load_json(manifest_path), manifest_path=manifest_path)
    doc_dir = manifest_path.parent
    source_path = doc_dir / "source.md"
    if not source_path.is_file():
        raise SystemExit(f"missing source.md for {manifest_path}")
    css = load_css(slug_root)
    markdown = source_path.read_text(encoding="utf-8")
    html_text = render_html(manifest=manifest, markdown=markdown, css=css)
    build_dir = doc_dir / "build"
    build_dir.mkdir(parents=True, exist_ok=True)
    html_path = build_dir / "index.html"
    html_path.write_text(html_text, encoding="utf-8")
    pdf_path = build_dir / "output.pdf"
    write_simple_pdf(path=pdf_path, title=str(manifest.get("title") or "Memorial document"), body_text="\n".join(line.rstrip() for line in markdown.splitlines()))
    if require_pdf and not pdf_path.is_file():
        raise SystemExit(f"pdf_generation_failed for {manifest.get('document_id')}")
    manifest["published_date"] = str(manifest.get("published_date") or manifest.get("version") or "")
    manifest["build_artifacts"] = {"html_path": str(html_path), "pdf_path": str(pdf_path)}
    manifest["source_files"] = list(manifest.get("source_files") or ["source.md"])
    manifest["sha256"] = sha256_bytes(html_text.encode("utf-8"))
    manifest["source_sha256"] = sha256_bytes(markdown.encode("utf-8"))
    manifest["built_at"] = utc_now_iso()
    manifest["_manifest_path"] = str(manifest_path)
    manifest_path.write_text(json.dumps({k: v for k, v in manifest.items() if not str(k).startswith("_")}, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    args = parse_args()
    slug_root = archive_slug_root(args.slug)
    if not slug_root.is_dir():
        raise SystemExit(f"archive root not found: {slug_root}")
    manifests = [build_document(path, slug_root, args.require_pdf) for path in list_documents(slug_root)]
    registry = registry_from_manifests(slug=args.slug, manifests=manifests, include_nonpublic=True)
    write_registry(slug=args.slug, registry=registry)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
