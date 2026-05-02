#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
LOCAL_PRODUCT_ROOT = ROOT / ".codex-design" / "product"
DEFAULT_DESIGN_ROOT = Path("/docker/chummercomplete/chummer-design/products/chummer")
QUEUE_OVERLAY_PATH = ROOT / ".codex-studio" / "published" / "QUEUE.generated.yaml"
EXPECTED_QUEUE_PACKAGE_ID = "audit-task-4257456"
EXPECTED_QUEUE_SOURCE_REF = "audit_task_candidates[4257456]"
EXPECTED_QUEUE_AUDIT_FINDING_KEY = "project.design_mirror_missing_or_stale"
EXPECTED_QUEUE_AUDIT_SCOPE_ID = "ea"
EXPECTED_QUEUE_ALLOWED_PATHS = [".codex-design"]
EXPECTED_QUEUE_OWNED_SURFACES = ["design_mirror:ea"]
EXPECTED_QUEUE_TASK = (
    "Auto-detect and repair recurring `ea` mirror drift after 5837 repeated audit observations; "
    "keep one bounded queue slice for the affected local design mirror bundle instead of reopening one-off mirror refresh work."
)


@dataclass(frozen=True)
class MirrorBinding:
    key: str
    local_path: Path
    source_path: Path


def _bindings() -> list[MirrorBinding]:
    return [
        MirrorBinding(
            key="next_90_day_queue_staging",
            local_path=LOCAL_PRODUCT_ROOT / "NEXT_90_DAY_QUEUE_STAGING.generated.yaml",
            source_path=DEFAULT_DESIGN_ROOT / "NEXT_90_DAY_QUEUE_STAGING.generated.yaml",
        ),
    ]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _expected_queue_source_items() -> list[str]:
    return [binding.local_path.as_posix() for binding in _bindings()]


def _load_queue_overlay() -> dict[str, object]:
    payload = yaml.safe_load(QUEUE_OVERLAY_PATH.read_text(encoding="utf-8")) or {}
    return payload if isinstance(payload, dict) else {}


def _find_queue_item(items: list[object]) -> tuple[int, dict[str, object]] | tuple[None, None]:
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        if str(item.get("package_id") or "").strip() == EXPECTED_QUEUE_PACKAGE_ID:
            return index, item
        if str(item.get("audit_finding_key") or "").strip() == EXPECTED_QUEUE_AUDIT_FINDING_KEY:
            return index, item
    return None, None


def inspect_queue_overlay() -> dict[str, object]:
    row: dict[str, object] = {
        "key": "published_queue_overlay",
        "local_path": QUEUE_OVERLAY_PATH.as_posix(),
        "status": "ok",
    }
    if not QUEUE_OVERLAY_PATH.exists():
        row["status"] = "missing_local"
        return row

    payload = _load_queue_overlay()
    mode = str(payload.get("mode") or "").strip()
    items = payload.get("items") or []
    if not isinstance(items, list):
        row["status"] = "queue_drift"
        row["mismatches"] = ["items:not_a_list"]
        return row

    index, item = _find_queue_item(items)
    if item is None:
        row["status"] = "queue_drift"
        row["mismatches"] = ["mirror_item:missing"]
        return row

    mismatches: list[str] = []
    if mode != "append":
        mismatches.append(f"mode:{mode or '<missing>'}")
    if str(item.get("source_ref") or "").strip() != EXPECTED_QUEUE_SOURCE_REF:
        mismatches.append("source_ref")
    if str(item.get("audit_finding_key") or "").strip() != EXPECTED_QUEUE_AUDIT_FINDING_KEY:
        mismatches.append("audit_finding_key")
    if str(item.get("audit_scope_id") or "").strip() != EXPECTED_QUEUE_AUDIT_SCOPE_ID:
        mismatches.append("audit_scope_id")
    if list(item.get("allowed_paths") or []) != EXPECTED_QUEUE_ALLOWED_PATHS:
        mismatches.append("allowed_paths")
    if list(item.get("owned_surfaces") or []) != EXPECTED_QUEUE_OWNED_SURFACES:
        mismatches.append("owned_surfaces")
    if list(item.get("source_items") or []) != _expected_queue_source_items():
        mismatches.append("source_items")

    row["mode"] = mode
    row["mirror_item_index"] = index
    row["package_id"] = str(item.get("package_id") or "").strip()
    row["source_items"] = list(item.get("source_items") or [])
    if mismatches:
        row["status"] = "queue_drift"
        row["mismatches"] = mismatches
    return row


def inspect_bundle() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for binding in _bindings():
        local_exists = binding.local_path.exists()
        source_exists = binding.source_path.exists()
        row: dict[str, object] = {
            "key": binding.key,
            "local_path": binding.local_path.as_posix(),
            "source_path": binding.source_path.as_posix(),
            "local_exists": local_exists,
            "source_exists": source_exists,
            "status": "ok",
        }
        if not local_exists and not source_exists:
            row["status"] = "missing_local_and_source"
        elif not source_exists:
            row["status"] = "missing_source"
        elif not local_exists:
            row["status"] = "missing_local"
        else:
            local_sha = _sha256(binding.local_path)
            source_sha = _sha256(binding.source_path)
            row["local_sha256"] = local_sha
            row["source_sha256"] = source_sha
            if local_sha != source_sha:
                row["status"] = "drift"
        rows.append(row)
    rows.append(inspect_queue_overlay())
    return rows


def repair_bundle() -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for binding in _bindings():
        row = next(item for item in inspect_bundle() if item["key"] == binding.key)
        status = str(row["status"])
        result = dict(row)
        if status in {"ok"}:
            result["action"] = "unchanged"
        elif status in {"missing_source", "missing_local_and_source"}:
            result["action"] = "blocked_missing_source"
        else:
            binding.local_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(binding.source_path, binding.local_path)
            result["action"] = "copied"
            result["status"] = "ok"
            result["local_sha256"] = _sha256(binding.local_path)
            result["source_sha256"] = _sha256(binding.source_path)
        results.append(result)
    queue_row = inspect_queue_overlay()
    queue_result = dict(queue_row)
    if str(queue_row["status"]) == "ok":
        queue_result["action"] = "unchanged"
    else:
        payload = _load_queue_overlay() if QUEUE_OVERLAY_PATH.exists() else {}
        payload["mode"] = "append"
        items = payload.get("items") or []
        if not isinstance(items, list):
            items = []
        index, item = _find_queue_item(items)
        if item is None:
            item = {
                "title": EXPECTED_QUEUE_TASK,
                "task": EXPECTED_QUEUE_TASK,
                "package_id": EXPECTED_QUEUE_PACKAGE_ID,
            }
            items.append(item)
        item["source_ref"] = EXPECTED_QUEUE_SOURCE_REF
        item["audit_finding_key"] = EXPECTED_QUEUE_AUDIT_FINDING_KEY
        item["audit_scope_id"] = EXPECTED_QUEUE_AUDIT_SCOPE_ID
        item["allowed_paths"] = EXPECTED_QUEUE_ALLOWED_PATHS
        item["owned_surfaces"] = EXPECTED_QUEUE_OWNED_SURFACES
        item["source_items"] = _expected_queue_source_items()
        payload["items"] = items
        QUEUE_OVERLAY_PATH.parent.mkdir(parents=True, exist_ok=True)
        QUEUE_OVERLAY_PATH.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
        queue_result = inspect_queue_overlay()
        queue_result["action"] = "repaired"
    results.append(queue_result)
    return results


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify or repair the bounded EA design-mirror bundle audited for recurring drift."
    )
    parser.add_argument(
        "--repair",
        action="store_true",
        help="Copy only drifted or missing local mirror files from their canonical sources.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the inspection or repair result as JSON.",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    rows = repair_bundle() if args.repair else inspect_bundle()
    if args.json:
        print(json.dumps(rows, indent=2, sort_keys=True))
    else:
        for row in rows:
            status = str(row["status"])
            action = str(row.get("action") or "").strip()
            source_path = str(row.get("source_path") or "").strip()
            if source_path:
                line = f"{status}: {row['key']} ({row['local_path']} <- {source_path})"
            else:
                line = f"{status}: {row['key']} ({row['local_path']})"
            if action:
                line = f"{line} [{action}]"
            print(line)
    failures = [row for row in rows if str(row["status"]) != "ok"]
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
