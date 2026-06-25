#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from scripts.materialize_memorial_operator_status import _source_dirty_summary
    from scripts.source_state_head import source_worktree_metadata
except ModuleNotFoundError:  # pragma: no cover - direct script execution path
    from materialize_memorial_operator_status import _source_dirty_summary
    from source_state_head import source_worktree_metadata

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIRTY_PATH_LIMIT = 240
FULL_DIRTY_SCAN_LIMIT = 10000
PRIORITY_CATEGORY_REASONS = {
    "api_routes": "runtime and public-route behavior can invalidate public receipts",
    "services": "provider, audio, and runtime services can invalidate latency or speech receipts",
    "app_core": "application wiring can invalidate deployment/runtime proof",
    "templates": "user-facing templates can invalidate UX and memorial dignity proof",
    "scripts": "materializers and verifiers can invalidate operator evidence",
    "deploy_runtime": "compose, Docker, and deploy scripts can invalidate public-origin proof",
}


def build_report(
    *,
    root: Path = ROOT,
    dirty_path_limit: int = DEFAULT_DIRTY_PATH_LIMIT,
    category: str = "",
) -> dict[str, Any]:
    source_worktree = dict(source_worktree_metadata(root, dirty_path_limit=FULL_DIRTY_SCAN_LIMIT))
    summary = _trim_summary_samples(dict(_source_dirty_summary(source_worktree)), sample_limit=dirty_path_limit)
    normalized_category = str(category or "").strip()
    if normalized_category:
        summary = _filter_summary_category(summary, category=normalized_category)
    status = "dirty" if bool(source_worktree.get("source_worktree_dirty")) else "clean"
    category_drilldown_commands = _category_drilldown_commands(summary)
    priority_groups = _priority_groups(summary)
    return {
        "contract_name": "ea.source_dirty_groups.v1",
        "status": status,
        "category_filter": normalized_category,
        "source_worktree": source_worktree,
        "source_dirty_summary": summary,
        "priority_groups": priority_groups,
        "recommended_commands": _recommended_commands(status=status),
        "category_drilldown_commands": category_drilldown_commands,
    }


def _trim_summary_samples(summary: dict[str, Any], *, sample_limit: int) -> dict[str, Any]:
    bounded_limit = max(sample_limit, 0)
    categories = []
    for item in list(summary.get("categories") or []):
        if not isinstance(item, dict):
            continue
        row = dict(item)
        samples = [str(path).strip() for path in list(row.get("sample_files") or []) if str(path).strip()]
        row["sample_files"] = samples[:bounded_limit]
        row["sample_omitted_count"] = max(len(samples) - bounded_limit, 0)
        category = str(row.get("category") or "").strip()
        if category:
            row["drilldown_command"] = _category_drilldown_command(category)
        categories.append(row)
    summary["categories"] = categories
    summary["sample_limit_per_category"] = bounded_limit
    return summary


def _filter_summary_category(summary: dict[str, Any], *, category: str) -> dict[str, Any]:
    categories = [dict(item) for item in list(summary.get("categories") or []) if isinstance(item, dict)]
    filtered = [item for item in categories if str(item.get("category") or "").strip() == category]
    visible_count = sum(int(item.get("visible_count") or 0) for item in filtered)
    return {
        **summary,
        "categories": filtered,
        "category_filter": category,
        "category_count": len(filtered),
        "visible_count": visible_count,
    }


def _category_drilldown_command(category: str) -> str:
    normalized = str(category or "").strip()
    if not normalized:
        return ""
    return f"scripts/inspect_source_dirty_groups.py --category {normalized} --limit 20"


def _category_drilldown_commands(summary: dict[str, Any]) -> list[str]:
    commands: list[str] = []
    for row in list(summary.get("categories") or []):
        if not isinstance(row, dict):
            continue
        command = str(row.get("drilldown_command") or _category_drilldown_command(str(row.get("category") or ""))).strip()
        if command and command not in commands:
            commands.append(command)
    return commands


def _priority_groups(summary: dict[str, Any]) -> list[dict[str, Any]]:
    priority: list[dict[str, Any]] = []
    for row in list(summary.get("categories") or []):
        if not isinstance(row, dict):
            continue
        category = str(row.get("category") or "").strip()
        if category not in PRIORITY_CATEGORY_REASONS:
            continue
        visible_count = int(row.get("visible_count") or 0)
        if visible_count <= 0:
            continue
        priority.append(
            {
                "category": category,
                "visible_count": visible_count,
                "reason": PRIORITY_CATEGORY_REASONS[category],
                "drilldown_command": str(row.get("drilldown_command") or _category_drilldown_command(category)).strip(),
            }
        )
    return priority


def format_text(report: dict[str, Any]) -> str:
    source_worktree = dict(report.get("source_worktree") or {})
    summary = dict(report.get("source_dirty_summary") or {})
    categories = [dict(item) for item in list(summary.get("categories") or []) if isinstance(item, dict)]
    priority_groups = [dict(item) for item in list(report.get("priority_groups") or []) if isinstance(item, dict)]
    lines = [
        f"source worktree: {report.get('status') or 'missing'}",
        f"category filter: {report.get('category_filter') or 'none'}",
        f"dirty total:     {int(summary.get('total_count') or source_worktree.get('source_dirty_count') or 0)}",
        f"dirty visible:   {int(summary.get('visible_count') or 0)}",
        f"dirty omitted:   {int(summary.get('omitted_count') or source_worktree.get('source_dirty_omitted_count') or 0)}",
        f"dirty sha256:    {source_worktree.get('source_dirty_status_sha256') or 'none'}",
        f"operator hint:   {summary.get('operator_hint') or 'Source worktree is clean.'}",
        "",
        "priority groups:",
    ]
    if not priority_groups:
        lines.append("- none")
    for row in priority_groups:
        command = str(row.get("drilldown_command") or "").strip()
        suffix = f" -> {command}" if command else ""
        lines.append(
            f"- {row.get('category')}: {int(row.get('visible_count') or 0)} "
            f"({row.get('reason') or 'review before clean receipts'}){suffix}"
        )
    lines.extend([
        "",
        "groups:",
    ])
    if not categories:
        lines.append("- none")
    for row in categories:
        samples = [str(item).strip() for item in list(row.get("sample_files") or []) if str(item).strip()]
        sample_text = ", ".join(samples[:5]) if samples else "no samples"
        sample_omitted_count = int(row.get("sample_omitted_count") or 0)
        if len(samples) > 5 or sample_omitted_count:
            sample_text += ", ..."
        command = str(row.get("drilldown_command") or "").strip()
        suffix = f" ({command})" if command else ""
        lines.append(f"- {row.get('category')}: {int(row.get('visible_count') or 0)} -> {sample_text}{suffix}")
    lines.extend(["", "recommended commands:"])
    for command in list(report.get("recommended_commands") or []):
        lines.append(f"- {command}")
    return "\n".join(lines)


def format_category_list(report: dict[str, Any]) -> str:
    summary = dict(report.get("source_dirty_summary") or {})
    categories = [dict(item) for item in list(summary.get("categories") or []) if isinstance(item, dict)]
    priority_groups = [dict(item) for item in list(report.get("priority_groups") or []) if isinstance(item, dict)]
    lines = [
        f"source worktree: {report.get('status') or 'missing'}",
        f"dirty total:     {int(summary.get('total_count') or 0)}",
        "categories:",
    ]
    if priority_groups:
        priority_text = ", ".join(str(item.get("category") or "").strip() for item in priority_groups if str(item.get("category") or "").strip())
        lines.append(f"priority groups: {priority_text}")
    if not categories:
        lines.append("- none")
    for row in categories:
        category = str(row.get("category") or "").strip() or "unknown"
        command = str(row.get("drilldown_command") or _category_drilldown_command(category)).strip()
        lines.append(f"- {category}: {int(row.get('visible_count') or 0)} -> {command}")
    lines.extend(
        [
            "",
            "drilldown:",
            "- scripts/inspect_source_dirty_groups.py --category <category> --limit 20",
        ]
    )
    return "\n".join(lines)


def _recommended_commands(*, status: str) -> list[str]:
    if status == "dirty":
        return [
            "git status --short",
            "scripts/inspect_source_dirty_groups.py --list-categories",
            "scripts/inspect_source_dirty_groups.py --category <category> --limit 20",
            "make inspect-source-dirty-groups",
            "commit or stash source groups before clean receipt refresh",
            "make materialize-memorial-public-auto-receipts-clean",
        ]
    return [
        "make materialize-memorial-public-auto-receipts-clean",
        "make materialize-memorial-public-gold",
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect source-dirty groups blocking clean memorial receipt refresh.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON instead of text.")
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_DIRTY_PATH_LIMIT,
        help=f"Maximum sample files to show per dirty source group. Default: {DEFAULT_DIRTY_PATH_LIMIT}.",
    )
    parser.add_argument("--category", default="", help="Show only one source-dirty category, for example api_routes or services.")
    parser.add_argument("--list-categories", action="store_true", help="Print only dirty source category names and counts.")
    args = parser.parse_args()
    report = build_report(dirty_path_limit=max(args.limit, 0), category=args.category)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    elif args.list_categories:
        print(format_category_list(report))
    else:
        print(format_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
