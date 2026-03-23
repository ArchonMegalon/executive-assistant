#!/usr/bin/env python3
from __future__ import annotations

import os
import re
from pathlib import Path

import yaml


DEFAULT_DESIGN_ROOT = Path("/docker/chummercomplete/chummer-design/products/chummer")
TITLE_RE = re.compile(r"^#\s+(.+?)\s*$")
SECTION_RE = re.compile(r"^##\s+(.+?)\s*$")


def design_root() -> Path:
    raw = str(os.environ.get("CHUMMER6_DESIGN_PRODUCT_ROOT") or "").strip()
    return Path(raw) if raw else DEFAULT_DESIGN_ROOT


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _read_yaml(path: Path) -> dict[str, object]:
    loaded = yaml.safe_load(_read_text(path))
    return dict(loaded or {})


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


def load_page_registry() -> dict[str, object]:
    return _read_yaml(_source_path("page_registry", "PUBLIC_GUIDE_PAGE_REGISTRY.yaml"))


def load_media_briefs() -> dict[str, object]:
    return _read_yaml(_source_path("public_media_briefs", "PUBLIC_MEDIA_BRIEFS.yaml"))


def load_export_manifest() -> dict[str, object]:
    return _read_yaml(design_root() / "PUBLIC_GUIDE_EXPORT_MANIFEST.yaml")


def _source_path(key: str, fallback: str) -> Path:
    manifest = load_export_manifest()
    sources = manifest.get("sources") or {}
    raw = str((sources.get(key) if isinstance(sources, dict) else "") or "").strip()
    if raw.startswith("products/chummer/"):
        raw = raw[len("products/chummer/") :]
    return design_root() / (raw or fallback)


def load_public_feature_registry() -> dict[str, object]:
    return _read_yaml(_source_path("public_feature_registry", "PUBLIC_FEATURE_REGISTRY.yaml"))


def load_public_guide_policy_text() -> str:
    return _read_text(_source_path("public_guide_policy", "PUBLIC_GUIDE_POLICY.md"))


def _part_rows() -> list[dict[str, object]]:
    data = _read_yaml(_source_path("part_registry", "PUBLIC_PART_REGISTRY.yaml"))
    rows = data.get("parts") or []
    return [dict(row or {}) for row in rows if isinstance(row, dict)]


def _public_horizon_rows() -> list[dict[str, object]]:
    data = _read_yaml(_source_path("horizon_registry", "HORIZON_REGISTRY.yaml"))
    rows = [dict(row or {}) for row in (data.get("horizons") or []) if isinstance(row, dict)]
    enabled = [row for row in rows if bool((row.get("public_guide") or {}).get("enabled"))]
    return sorted(enabled, key=lambda row: int((row.get("public_guide") or {}).get("order") or 0))


def canonical_part_slugs() -> list[str]:
    return [str(row.get("id") or "").strip() for row in _part_rows() if str(row.get("id") or "").strip()]


def canonical_horizon_slugs() -> list[str]:
    return [str(row.get("id") or "").strip() for row in _public_horizon_rows() if str(row.get("id") or "").strip()]


def assert_public_horizon_catalog(expected_slugs: list[str], rendered_slugs: list[str]) -> None:
    expected = [str(item or "").strip() for item in expected_slugs if str(item or "").strip()]
    rendered = [str(item or "").strip() for item in rendered_slugs if str(item or "").strip()]
    if rendered != expected:
        raise RuntimeError(f"public_horizon_catalog_mismatch: expected={expected!r} rendered={rendered!r}")


def assert_slug_in_canon(slug: str, catalog: dict[str, dict[str, object]], *, kind: str) -> None:
    normalized = str(slug or "").strip()
    if not normalized or normalized not in catalog:
        raise RuntimeError(f"missing_{kind}_canon:{normalized}")


def load_part_canon() -> dict[str, dict[str, object]]:
    catalog: dict[str, dict[str, object]] = {}
    for row in _part_rows():
        slug = str(row.get("id") or "").strip()
        if not slug:
            continue
        title = str(row.get("title") or slug.replace("-", " ").title()).strip()
        tagline = str(row.get("public_tagline") or "").strip()
        when = str(row.get("you_touch_this_when") or "").strip()
        why = str(row.get("why_you_care") or "").strip()
        notice = [str(value).strip() for value in (row.get("what_you_notice") or []) if str(value).strip()]
        limits = [str(value).strip() for value in (row.get("public_noteworthy_limits") or []) if str(value).strip()]
        now = str(row.get("current_truth") or "").strip()
        links = [str(value).strip() for value in (row.get("go_deeper_links") or []) if str(value).strip()]
        catalog[slug] = {
            "title": title,
            "tagline": tagline,
            "when": when,
            "why": why,
            "notice": notice,
            "limits": limits,
            "now": now,
            "go_deeper_links": links,
            # Compatibility for older callers that still expect the pre-registry shape.
            "intro": why,
            "owns": notice,
            "not_owns": limits,
        }
    return catalog


def load_horizon_canon() -> dict[str, dict[str, object]]:
    root = design_root()
    catalog: dict[str, dict[str, object]] = {}
    for row in _public_horizon_rows():
        slug = str(row.get("id") or "").strip()
        if not slug:
            continue
        canon_doc = root / str(row.get("canon_doc") or "").replace("products/chummer/", "", 1)
        title = str(row.get("title") or slug.replace("-", " ").title()).strip()
        sections: dict[str, str] = {}
        if canon_doc.exists():
            doc_title, sections = _markdown_sections(canon_doc)
            if doc_title:
                title = doc_title
        problem = str(row.get("pain_label") or "").strip() or _paragraph(sections.get("table pain", ""))
        use_case = _paragraph(sections.get("bounded product move", "")) or str(row.get("wow_promise") or "").strip()
        not_now = _paragraph(sections.get("why still a horizon", "")) or str((row.get("build_path") or {}).get("current_state") or "").strip()
        foundations = [str(value).strip() for value in (row.get("foundations") or []) if str(value).strip()]
        repos = [str(value).strip() for value in (row.get("owning_repos") or []) if str(value).strip()]
        catalog[slug] = {
            "title": title,
            "hook": _first_sentence(str(row.get("wow_promise") or "").strip() or use_case or problem),
            "problem": problem,
            "brutal_truth": problem,
            "use_case": use_case,
            "foundations": foundations,
            "repos": repos,
            "not_now": not_now,
            "access_posture": str(row.get("access_posture") or "").strip(),
            "resource_burden": str(row.get("resource_burden") or "").strip(),
            "booster_nudge": str(row.get("booster_nudge") or "").strip(),
            "free_later_intent": str(row.get("free_later_intent") or "").strip(),
            "recognition_eligible": bool(row.get("recognition_eligible")),
        }
    return catalog


def load_faq_canon() -> dict[str, dict[str, object]]:
    data = _read_yaml(_source_path("faq_registry", "PUBLIC_FAQ_REGISTRY.yaml"))
    catalog: dict[str, dict[str, object]] = {}
    for row in data.get("sections") or []:
        if not isinstance(row, dict):
            continue
        section_id = str(row.get("id") or "").strip()
        if not section_id:
            continue
        entries = [
            {
                "question": str(entry.get("question") or "").strip(),
                "answer": str(entry.get("answer") or "").strip(),
                "required": bool(entry.get("required")),
            }
            for entry in (row.get("entries") or [])
            if isinstance(entry, dict) and str(entry.get("question") or "").strip()
        ]
        catalog[section_id] = {
            "title": str(row.get("title") or section_id.replace("_", " ").title()).strip(),
            "entries": entries,
        }
    return catalog


def load_help_canon() -> dict[str, object]:
    title, sections = _markdown_sections(_source_path("help_copy", "PUBLIC_HELP_COPY.md"))
    return {
        "title": title,
        "public_feedback_lane": sections.get("public feedback lane", "").strip(),
        "booster_lane": sections.get("booster lane", "").strip(),
        "privacy_and_review_safety": _bullet_lines(sections.get("privacy and review safety", "")),
        "free_later_note": sections.get("free later note", "").strip(),
        "primary_ctas": _bullet_lines(sections.get("primary ctas", "")),
    }


def merge_part_canon(defaults: dict[str, dict[str, object]]) -> dict[str, dict[str, object]]:
    merged: dict[str, dict[str, object]] = {}
    for slug, parsed in load_part_canon().items():
        row = dict(defaults.get(slug) or {})
        row["title"] = str(parsed.get("title") or row.get("title") or "").strip()
        row["tagline"] = str(parsed.get("tagline") or row.get("tagline") or "").strip()
        row["when"] = str(parsed.get("when") or row.get("when") or "").strip()
        row["why"] = str(parsed.get("why") or row.get("why") or "").strip()
        row["notice"] = list(parsed.get("notice") or row.get("notice") or [])
        row["limits"] = list(parsed.get("limits") or row.get("limits") or [])
        row["now"] = str(parsed.get("now") or row.get("now") or "").strip()
        row["go_deeper_links"] = list(parsed.get("go_deeper_links") or row.get("go_deeper_links") or [])
        row["intro"] = str(parsed.get("intro") or row.get("intro") or row.get("why") or "").strip()
        row["owns"] = list(parsed.get("owns") or row.get("owns") or row.get("notice") or [])
        row["not_owns"] = list(parsed.get("not_owns") or row.get("not_owns") or row.get("limits") or [])
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
        row["hook"] = str(parsed.get("hook") or row.get("hook") or "").strip()
        row["brutal_truth"] = str(parsed.get("brutal_truth") or row.get("brutal_truth") or "").strip()
        row["access_posture"] = str(parsed.get("access_posture") or row.get("access_posture") or "").strip()
        row["resource_burden"] = str(parsed.get("resource_burden") or row.get("resource_burden") or "").strip()
        row["booster_nudge"] = str(parsed.get("booster_nudge") or row.get("booster_nudge") or "").strip()
        row["free_later_intent"] = str(parsed.get("free_later_intent") or row.get("free_later_intent") or "").strip()
        row["recognition_eligible"] = bool(parsed.get("recognition_eligible") if "recognition_eligible" in parsed else row.get("recognition_eligible"))
        merged[slug] = row
    return merged
