#!/usr/bin/env python3
from __future__ import annotations

import os
import re
from pathlib import Path


DEFAULT_DESIGN_ROOT = Path("/docker/chummercomplete/chummer-design/products/chummer")
ACTIVE_REPO_HEADER = "## Active Chummer repos"
STOP_HEADERS = {"## Reference-only repo", "## Adjacent repos", "## Current program priorities"}
REPO_HEADING_RE = re.compile(r"^###\s+`([^`]+)`\s*$")
REGISTRY_ENTRY_RE = re.compile(r"`horizons/([a-z0-9-]+)\.md`")
TITLE_RE = re.compile(r"^#\s+(.+?)\s*$")
SECTION_RE = re.compile(r"^##\s+(.+?)\s*$")

PART_METADATA: dict[str, dict[str, str]] = {
    "design": {"title": "Design", "tagline": "The long-range plan and ownership map."},
    "core": {"title": "Core", "tagline": "The deterministic rules engine."},
    "ui": {"title": "UI", "tagline": "The workbench and big-screen UX."},
    "mobile": {"title": "Mobile", "tagline": "The part you feel at the table."},
    "hub": {"title": "Hub", "tagline": "The hosted API and orchestration layer."},
    "ui-kit": {"title": "UI Kit", "tagline": "Shared chrome, themes, and visual primitives."},
    "hub-registry": {"title": "Hub Registry", "tagline": "Artifacts, publication, installs, compatibility."},
    "media-factory": {"title": "Media Factory", "tagline": "Render-only asset lifecycle."},
}


def design_root() -> Path:
    raw = str(os.environ.get("CHUMMER6_DESIGN_PRODUCT_ROOT") or "").strip()
    return Path(raw) if raw else DEFAULT_DESIGN_ROOT


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _first_sentence(text: str) -> str:
    compact = " ".join(str(text or "").split()).strip()
    if not compact:
        return ""
    match = re.search(r"(?<=[.!?])\s", compact)
    if match:
        return compact[: match.start()].strip()
    return compact


def _markdown_sections(path: Path) -> tuple[str, dict[str, str]]:
    title = ""
    current = ""
    sections: dict[str, list[str]] = {}
    for raw in _read_text(path).splitlines():
        if not title:
            title_match = TITLE_RE.match(raw.strip())
            if title_match:
                title = title_match.group(1).strip()
                continue
        section_match = SECTION_RE.match(raw.strip())
        if section_match:
            current = section_match.group(1).strip().lower()
            sections.setdefault(current, [])
            continue
        if current:
            sections.setdefault(current, []).append(raw.rstrip())
    joined = {name: "\n".join(lines).strip() for name, lines in sections.items()}
    return title, joined


def _bullet_lines(text: str) -> list[str]:
    items: list[str] = []
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if line.startswith("* "):
            value = line[2:].strip()
            if value:
                items.append(value.strip("`"))
    return items


def _paragraph(text: str) -> str:
    parts: list[str] = []
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line:
            if parts:
                break
            continue
        if line.startswith("* "):
            continue
        parts.append(line)
    return " ".join(parts).strip()


def _part_slug(repo_name: str) -> str:
    clean = str(repo_name or "").strip()
    if clean == "chummer6-design":
        return "design"
    if clean.startswith("chummer6-"):
        return clean[len("chummer6-") :]
    return clean


def canonical_part_slugs() -> list[str]:
    readme = design_root() / "README.md"
    lines = _read_text(readme).splitlines()
    inside = False
    slugs: list[str] = []
    for raw in lines:
        line = raw.rstrip()
        if line.strip() == ACTIVE_REPO_HEADER:
            inside = True
            continue
        if inside and line.strip() in STOP_HEADERS:
            break
        if not inside:
            continue
        match = REPO_HEADING_RE.match(line.strip())
        if not match:
            continue
        repo_name = match.group(1).strip()
        if not repo_name.startswith("chummer6-"):
            continue
        slug = _part_slug(repo_name)
        if slug not in slugs:
            slugs.append(slug)
    return slugs


def canonical_horizon_slugs() -> list[str]:
    registry_doc = design_root() / "HORIZONS.md"
    slugs: list[str] = []
    if registry_doc.exists():
        for raw in _read_text(registry_doc).splitlines():
            match = REGISTRY_ENTRY_RE.search(raw)
            if match:
                slug = match.group(1).strip()
                if slug and slug not in slugs:
                    slugs.append(slug)
    if slugs:
        return slugs
    horizon_dir = design_root() / "horizons"
    for path in sorted(horizon_dir.glob("*.md")):
        if path.name == "README.md":
            continue
        slugs.append(path.stem)
    return slugs


def load_part_canon() -> dict[str, dict[str, object]]:
    project_root = design_root() / "projects"
    catalog: dict[str, dict[str, object]] = {}
    for slug in canonical_part_slugs():
        path = project_root / f"{slug}.md"
        if not path.exists():
            continue
        _, sections = _markdown_sections(path)
        mission = _paragraph(sections.get("mission", ""))
        owns = _bullet_lines(sections.get("owns", ""))
        not_owns = _bullet_lines(sections.get("must not own", ""))
        now = (
            _paragraph(sections.get("current reality", ""))
            or _paragraph(sections.get("current focus", ""))
            or _paragraph(sections.get("immediate work", ""))
        )
        metadata = PART_METADATA.get(slug, {"title": slug.replace("-", " ").title(), "tagline": mission})
        catalog[slug] = {
            "title": metadata["title"],
            "tagline": metadata["tagline"],
            "intro": mission,
            "why": mission,
            "owns": owns,
            "not_owns": not_owns,
            "now": now or mission,
        }
    return catalog


def load_horizon_canon() -> dict[str, dict[str, object]]:
    horizon_root = design_root() / "horizons"
    catalog: dict[str, dict[str, object]] = {}
    for slug in canonical_horizon_slugs():
        path = horizon_root / f"{slug}.md"
        if not path.exists():
            continue
        title, sections = _markdown_sections(path)
        problem = _paragraph(sections.get("table pain", ""))
        move = _paragraph(sections.get("bounded product move", ""))
        owners = _bullet_lines(sections.get("likely owners", ""))
        foundations = _bullet_lines(sections.get("foundations", ""))
        why_still = _paragraph(sections.get("why still a horizon", ""))
        catalog[slug] = {
            "title": title or slug.replace("-", " ").title(),
            "hook": _first_sentence(move) or _first_sentence(problem),
            "problem": problem,
            "brutal_truth": problem,
            "use_case": move,
            "foundations": foundations,
            "repos": owners,
            "not_now": why_still,
        }
    return catalog


def merge_part_canon(defaults: dict[str, dict[str, object]]) -> dict[str, dict[str, object]]:
    merged: dict[str, dict[str, object]] = {}
    for slug, parsed in load_part_canon().items():
        row = dict(defaults.get(slug) or {})
        row.setdefault("title", parsed.get("title", ""))
        row.setdefault("tagline", parsed.get("tagline", ""))
        row.setdefault("intro", parsed.get("intro", ""))
        row.setdefault("why", parsed.get("why", ""))
        row.setdefault("now", parsed.get("now", ""))
        row["title"] = str(parsed.get("title") or row.get("title") or "").strip()
        row["owns"] = list(parsed.get("owns") or row.get("owns") or [])
        row["not_owns"] = list(parsed.get("not_owns") or row.get("not_owns") or [])
        if not str(row.get("intro") or "").strip():
            row["intro"] = str(parsed.get("intro") or "").strip()
        if not str(row.get("why") or "").strip():
            row["why"] = str(parsed.get("why") or "").strip()
        if not str(row.get("now") or "").strip():
            row["now"] = str(parsed.get("now") or "").strip()
        merged[slug] = row
    return merged


def merge_horizon_canon(defaults: dict[str, dict[str, object]]) -> dict[str, dict[str, object]]:
    merged: dict[str, dict[str, object]] = {}
    for slug, parsed in load_horizon_canon().items():
        row = dict(defaults.get(slug) or {})
        row["title"] = str(parsed.get("title") or row.get("title") or "").strip()
        row["problem"] = str(parsed.get("problem") or row.get("problem") or "").strip()
        row["use_case"] = str(parsed.get("use_case") or row.get("use_case") or "").strip()
        row["foundations"] = list(parsed.get("foundations") or row.get("foundations") or [])
        row["repos"] = list(parsed.get("repos") or row.get("repos") or [])
        row["not_now"] = str(parsed.get("not_now") or row.get("not_now") or "").strip()
        if not str(row.get("hook") or "").strip():
            row["hook"] = str(parsed.get("hook") or "").strip()
        if not str(row.get("brutal_truth") or "").strip():
            row["brutal_truth"] = str(parsed.get("brutal_truth") or "").strip()
        merged[slug] = row
    return merged
