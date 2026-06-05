#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")


def _markdown_files() -> list[Path]:
    files = [ROOT / "README.md"]
    docs_dir = ROOT / "docs"
    if docs_dir.exists():
        files.extend(sorted(docs_dir.rglob("*.md")))
    return [path for path in files if path.exists()]


def _is_external_or_route(href: str) -> bool:
    normalized = href.strip()
    return (
        not normalized
        or normalized.startswith("#")
        or normalized.startswith("/")
        or "://" in normalized
        or normalized.startswith("mailto:")
        or normalized.startswith("tel:")
    )


def _target_path(markdown_path: Path, href: str) -> Path:
    without_anchor = href.split("#", 1)[0].strip()
    return (markdown_path.parent / without_anchor).resolve()


def main() -> int:
    failures: list[str] = []
    for markdown_path in _markdown_files():
        text = markdown_path.read_text(encoding="utf-8")
        for match in LINK_RE.finditer(text):
            href = match.group(1).strip()
            rel_markdown = markdown_path.relative_to(ROOT)
            if href.startswith("/docker/property"):
                failures.append(f"{rel_markdown}: stale absolute local link {href}")
                continue
            if _is_external_or_route(href):
                continue
            target = _target_path(markdown_path, href)
            if target != ROOT and ROOT not in target.parents:
                failures.append(f"{rel_markdown}: link escapes repo {href}")
                continue
            if not target.exists():
                failures.append(f"{rel_markdown}: missing link target {href}")
    if failures:
        print("documentation link check failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    print("ok: documentation links resolve")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
