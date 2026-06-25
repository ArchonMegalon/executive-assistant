#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    from scripts.inspect_source_dirty_groups import build_report
except ModuleNotFoundError:  # pragma: no cover - direct script execution path
    from inspect_source_dirty_groups import build_report


ROOT = Path(__file__).resolve().parents[1]
VERIFY_CONTRACT_NAME = "ea.source_dirty_groups_verifier.v1"


def _int_value(value: object) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _validate_report(report: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    if report.get("contract_name") != "ea.source_dirty_groups.v1":
        issues.append("contract_name_mismatch")

    status = str(report.get("status") or "").strip()
    if status not in {"clean", "dirty"}:
        issues.append("status_invalid")

    source_worktree = report.get("source_worktree")
    if not isinstance(source_worktree, dict):
        issues.append("source_worktree_missing")
        source_worktree = {}

    summary = report.get("source_dirty_summary")
    if not isinstance(summary, dict):
        issues.append("source_dirty_summary_missing")
        summary = {}

    recommended_commands = report.get("recommended_commands")
    if not isinstance(recommended_commands, list):
        issues.append("recommended_commands_missing")
        recommended_commands = []

    categories = summary.get("categories")
    if not isinstance(categories, list):
        issues.append("summary_categories_missing")
        categories = []

    summary_status = str(summary.get("status") or "").strip()
    if summary_status and summary_status != status:
        issues.append("summary_status_mismatch")

    dirty_total = _int_value(summary.get("total_count"))
    worktree_dirty_total = _int_value(source_worktree.get("source_dirty_count"))
    if dirty_total != worktree_dirty_total:
        issues.append("dirty_total_mismatch")

    visible_total = _int_value(summary.get("visible_count"))
    category_visible_total = 0
    seen_categories: set[str] = set()
    drilldown_commands = report.get("category_drilldown_commands")
    if not isinstance(drilldown_commands, list):
        issues.append("category_drilldown_commands_missing")
        drilldown_commands = []
    priority_groups = report.get("priority_groups")
    if not isinstance(priority_groups, list):
        issues.append("priority_groups_missing")
        priority_groups = []

    for raw_row in categories:
        if not isinstance(raw_row, dict):
            issues.append("category_row_invalid")
            continue
        category = str(raw_row.get("category") or "").strip()
        if not category:
            issues.append("category_name_missing")
            continue
        if category in seen_categories:
            issues.append(f"category_duplicate:{category}")
        seen_categories.add(category)
        visible_count = _int_value(raw_row.get("visible_count"))
        if visible_count <= 0 and status == "dirty":
            issues.append(f"category_visible_count_invalid:{category}")
        category_visible_total += visible_count
        expected_command = f"scripts/inspect_source_dirty_groups.py --category {category} --limit 20"
        if raw_row.get("drilldown_command") != expected_command:
            issues.append(f"category_drilldown_command_mismatch:{category}")
        if expected_command not in drilldown_commands:
            issues.append(f"category_drilldown_command_missing:{category}")

    seen_priority_categories: set[str] = set()
    for raw_row in priority_groups:
        if not isinstance(raw_row, dict):
            issues.append("priority_group_row_invalid")
            continue
        category = str(raw_row.get("category") or "").strip()
        if not category:
            issues.append("priority_group_category_missing")
            continue
        if category in seen_priority_categories:
            issues.append(f"priority_group_duplicate:{category}")
        seen_priority_categories.add(category)
        if category not in seen_categories:
            issues.append(f"priority_group_category_unknown:{category}")
        expected_command = f"scripts/inspect_source_dirty_groups.py --category {category} --limit 20"
        if str(raw_row.get("drilldown_command") or "").strip() != expected_command:
            issues.append(f"priority_group_drilldown_command_mismatch:{category}")
        if not str(raw_row.get("reason") or "").strip():
            issues.append(f"priority_group_reason_missing:{category}")

    if visible_total != category_visible_total:
        issues.append("visible_category_total_mismatch")

    if status == "dirty":
        if dirty_total <= 0:
            issues.append("dirty_status_without_dirty_files")
        if "scripts/inspect_source_dirty_groups.py --list-categories" not in recommended_commands:
            issues.append("list_categories_recommendation_missing")
        if "scripts/inspect_source_dirty_groups.py --category <category> --limit 20" not in recommended_commands:
            issues.append("category_drilldown_recommendation_missing")
    elif categories:
        issues.append("clean_status_has_categories")

    return issues


def build_verification_payload(*, root: Path = ROOT) -> dict[str, Any]:
    report = build_report(root=root, dirty_path_limit=20)
    issues = _validate_report(dict(report))
    source_worktree = dict(report.get("source_worktree") or {})
    summary = dict(report.get("source_dirty_summary") or {})
    categories = [dict(item) for item in list(summary.get("categories") or []) if isinstance(item, dict)]
    return {
        "contract_name": VERIFY_CONTRACT_NAME,
        "status": "pass" if not issues else "blocked",
        "issues": issues,
        "source_dirty_status": report.get("status") or "",
        "source_dirty_count": _int_value(summary.get("total_count") or source_worktree.get("source_dirty_count")),
        "category_count": len(categories),
        "priority_group_count": len(list(report.get("priority_groups") or [])),
        "category_drilldown_commands": list(report.get("category_drilldown_commands") or []),
    }


def main() -> int:
    payload = build_verification_payload()
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
