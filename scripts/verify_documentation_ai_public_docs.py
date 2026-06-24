#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PACKAGE_DIR = ROOT / "docs-public" / "executive-assistant"
REQUIRED_DOC_PAGES = {
    "getting-started",
    "workspaces-and-identity",
    "gmail-and-calendar",
    "telegram-and-whatsapp",
    "briefs-signals-and-actions",
    "approvals-and-permissions",
    "privacy-and-data-retention",
    "troubleshooting",
    "public-api",
    "changelog",
}
FORBIDDEN_PUBLIC_PATH_FRAGMENTS = (
    "/admin",
    "/app/actions",
    "/v1/codex",
    "/v1/responses",
    "/v1/providers/onemin",
    "/v1/ltds",
    "/v1/memory",
    "/v1/human",
    "/v1/tasks",
    "/v1/tools",
    "/v1/rewrite",
    "/v1/plans",
    "/v1/runtime",
)
SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{12,}"),
    re.compile(r"api[_-]?key\s*[:=]\s*[A-Za-z0-9_-]{8,}", re.IGNORECASE),
    re.compile(r"password\s*[:=]\s*[^\\s`'\"]{6,}", re.IGNORECASE),
    re.compile(r"rangersofB5", re.IGNORECASE),
)
FORBIDDEN_DOC_MARKERS = (
    "/v1/codex",
    "/v1/responses",
    "operator prompt",
    "customer dossier",
    "private property packet",
)


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} does not contain a JSON object")
    return data


def _page_paths(documentation: dict[str, Any]) -> set[str]:
    paths: set[str] = set()
    navigation = documentation.get("navigation")
    groups = navigation.get("groups") if isinstance(navigation, dict) else []
    if not isinstance(groups, list):
        return paths
    for group in groups:
        if not isinstance(group, dict):
            continue
        for page in group.get("pages") or []:
            if isinstance(page, str):
                paths.add(page)
            elif isinstance(page, dict):
                page_path = page.get("path")
                if isinstance(page_path, str):
                    paths.add(page_path)
    return paths


def _api_groups(documentation: dict[str, Any]) -> list[dict[str, Any]]:
    navigation = documentation.get("navigation")
    groups = navigation.get("groups") if isinstance(navigation, dict) else []
    if not isinstance(groups, list):
        return []
    return [group for group in groups if isinstance(group, dict) and group.get("openapi")]


def _iter_text_files(package_dir: Path) -> list[Path]:
    patterns = ("*.md", "*.mdx", "*.txt", "*.json")
    files: list[Path] = []
    for pattern in patterns:
        files.extend(sorted(package_dir.rglob(pattern)))
    return files


def _secret_failures(package_dir: Path) -> list[str]:
    failures: list[str] = []
    for path in _iter_text_files(package_dir):
        rel = path.relative_to(package_dir)
        text = path.read_text(encoding="utf-8")
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                failures.append(f"{rel}: secret-like marker matched {pattern.pattern}")
        lowered = text.lower()
        if path.suffix in {".md", ".mdx", ".txt"}:
            for marker in FORBIDDEN_DOC_MARKERS:
                if marker in lowered:
                    failures.append(f"{rel}: forbidden private docs marker {marker}")
    return failures


def _openapi_failures(package_dir: Path, documentation: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    api_groups = _api_groups(documentation)
    if len(api_groups) != 1:
        return [f"documentation.json: expected exactly one OpenAPI group, found {len(api_groups)}"]
    api_group = api_groups[0]
    openapi_rel = str(api_group.get("openapi") or "")
    if openapi_rel != "api-reference/openapi.public.json":
        failures.append(f"documentation.json: OpenAPI must be api-reference/openapi.public.json, got {openapi_rel!r}")
        return failures
    hidden_apis = api_group.get("hidden-apis", [])
    if not isinstance(hidden_apis, list):
        failures.append("documentation.json: hidden-apis must be a list")
    else:
        bad_hidden = [item for item in hidden_apis if not isinstance(item, str) or not re.match(r"^[A-Z]+ /", item)]
        if bad_hidden:
            failures.append(f"documentation.json: hidden-apis entries must use METHOD /path format: {bad_hidden!r}")

    openapi = _load_json(package_dir / openapi_rel)
    paths = openapi.get("paths")
    if not isinstance(paths, dict) or not paths:
        failures.append(f"{openapi_rel}: paths object is missing or empty")
        return failures
    for path, path_item in paths.items():
        if not isinstance(path, str):
            failures.append(f"{openapi_rel}: path key is not a string")
            continue
        lowered_path = path.lower()
        for fragment in FORBIDDEN_PUBLIC_PATH_FRAGMENTS:
            if lowered_path.startswith(fragment.lower()):
                failures.append(f"{openapi_rel}: forbidden internal path exposed: {path}")
        if not isinstance(path_item, dict):
            failures.append(f"{openapi_rel}: {path} must be an object")
            continue
        for method in path_item:
            if method.lower() not in {"get", "post", "put", "patch", "delete", "options", "head"}:
                failures.append(f"{openapi_rel}: {method} {path} is not an HTTP operation")
    return failures


def verify_public_docs(package_dir: Path = DEFAULT_PACKAGE_DIR) -> list[str]:
    failures: list[str] = []
    required_files = [
        package_dir / "README.md",
        package_dir / "documentation.json",
        package_dir / "llms.txt",
        package_dir / "api-reference" / "openapi.public.json",
    ]
    for path in required_files:
        if not path.exists():
            failures.append(f"missing required file: {path}")
    if failures:
        return failures

    documentation = _load_json(package_dir / "documentation.json")
    page_paths = _page_paths(documentation)
    missing_pages = sorted(REQUIRED_DOC_PAGES - page_paths)
    if missing_pages:
        failures.append(f"documentation.json: missing required pages: {', '.join(missing_pages)}")
    for page in REQUIRED_DOC_PAGES:
        if not (package_dir / f"{page}.mdx").exists():
            failures.append(f"missing required MDX page: {page}.mdx")

    llms_text = (package_dir / "llms.txt").read_text(encoding="utf-8").strip()
    if "Executive Assistant" not in llms_text or "Private runtime" not in llms_text:
        failures.append("llms.txt: expected public scope and private runtime boundary")

    failures.extend(_openapi_failures(package_dir, documentation))
    failures.extend(_secret_failures(package_dir))
    return failures


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify the EA Documentation.AI public docs package.")
    parser.add_argument("--package-dir", type=Path, default=DEFAULT_PACKAGE_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    failures = verify_public_docs(args.package_dir)
    if failures:
        print("Documentation.AI public docs verification failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print(f"ok: Documentation.AI public docs package verified at {args.package_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
