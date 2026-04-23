#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
LOCAL_PRODUCT_ROOT = ROOT / ".codex-design" / "product"
DEFAULT_DESIGN_ROOT = Path("/docker/chummercomplete/chummer-design/products/chummer")
DEFAULT_SYNC_MANIFEST = DEFAULT_DESIGN_ROOT / "sync" / "sync-manifest.yaml"
QUEUE_OVERLAY_PATH = ROOT / ".codex-studio" / "published" / "QUEUE.generated.yaml"
FEEDBACK_ROOT = ROOT / "feedback"
APPLIED_FEEDBACK_LOG_PATH = FEEDBACK_ROOT / ".applied.log"
TARGET_REPO_ID = "executive-assistant"
EXPECTED_QUEUE_PACKAGE_ID = "audit-task-4257456"
EXPECTED_QUEUE_SOURCE_REF = "audit_task_candidates[4257456]"
EXPECTED_QUEUE_AUDIT_FINDING_KEY = "project.design_mirror_missing_or_stale"
EXPECTED_QUEUE_AUDIT_SCOPE_ID = "ea"
EXPECTED_QUEUE_ALLOWED_PATHS = [".codex-design"]
EXPECTED_QUEUE_OWNED_SURFACES = ["design_mirror:ea"]
EXPECTED_QUEUE_MODE = "append"
EXPECTED_QUEUE_TASK = (
    "Auto-detect and repair recurring `ea` mirror drift; "
    "keep one bounded queue slice for the affected local design mirror bundle instead of reopening one-off mirror refresh work."
)
LOCAL_PRODUCT_EXCEPTIONS = {
}

@dataclass(frozen=True)
class MirrorBinding:
    key: str
    local_path: Path
    source_path: Path


def _load_yaml(path: Path) -> dict[str, object]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return payload if isinstance(payload, dict) else {}


def _relative_product_target(source_rel: str, duplicate_basenames: set[str], product_target: str) -> Path:
    source_path = Path(source_rel)
    parts = list(source_path.parts)
    if len(parts) >= 2 and parts[0] == "products" and parts[1] == "chummer":
        relative_source = Path(*parts[2:])
    elif source_path.name in duplicate_basenames:
        relative_source = source_path
    else:
        relative_source = Path(source_path.name)
    return Path(product_target) / relative_source


def _load_target_mirror() -> tuple[dict[str, object], dict[str, object]]:
    manifest = _load_yaml(DEFAULT_SYNC_MANIFEST)
    mirrors = manifest.get("mirrors") or []
    if not isinstance(mirrors, list):
        raise ValueError("sync_manifest_mirrors_not_list")
    for mirror in mirrors:
        if isinstance(mirror, dict) and str(mirror.get("repo") or "").strip() == TARGET_REPO_ID:
            return manifest, mirror
    raise ValueError(f"sync_manifest_missing_repo:{TARGET_REPO_ID}")


def _expand_product_sources(manifest: dict[str, object], mirror: dict[str, object]) -> list[str]:
    group_table = manifest.get("product_source_groups") or {}
    if group_table and not isinstance(group_table, dict):
        raise ValueError("sync_manifest_product_source_groups_not_object")

    expanded: list[str] = []
    for group_name in mirror.get("product_groups") or []:
        group_items = group_table.get(group_name) if isinstance(group_table, dict) else None
        if not isinstance(group_items, list):
            raise ValueError(f"sync_manifest_product_group_not_list:{group_name}")
        expanded.extend(str(item or "").strip() for item in group_items)

    explicit_sources = mirror.get("product_sources") or mirror.get("sources") or []
    if explicit_sources and not isinstance(explicit_sources, list):
        raise ValueError("sync_manifest_product_sources_not_list")
    expanded.extend(str(item or "").strip() for item in explicit_sources)

    ordered_sources: list[str] = []
    seen: set[str] = set()
    for source in expanded:
        if not source or source in seen:
            continue
        seen.add(source)
        ordered_sources.append(source)
    return ordered_sources


def _bindings() -> list[MirrorBinding]:
    manifest, mirror = _load_target_mirror()
    product_target = str(mirror.get("product_target") or mirror.get("target") or ".codex-design/product").strip()
    product_sources = _expand_product_sources(manifest, mirror)
    duplicate_basenames = {
        name for name, count in Counter(Path(source).name for source in product_sources).items() if count > 1
    }

    bindings: list[MirrorBinding] = []
    for source_rel in product_sources:
        source_path = DEFAULT_DESIGN_ROOT.parents[1] / source_rel
        target_rel = _relative_product_target(source_rel, duplicate_basenames, product_target)
        bindings.append(
            MirrorBinding(
                key=f"product:{target_rel.relative_to(product_target).as_posix()}",
                local_path=ROOT / target_rel,
                source_path=source_path,
            )
        )

    repo_source = str(mirror.get("repo_source") or "").strip()
    if repo_source:
        repo_target = str(mirror.get("repo_target") or ".codex-design/repo/IMPLEMENTATION_SCOPE.md").strip()
        bindings.append(
            MirrorBinding(
                key="repo:implementation_scope",
                local_path=ROOT / repo_target,
                source_path=DEFAULT_DESIGN_ROOT.parents[1] / repo_source,
            )
        )

    review_source = str(mirror.get("review_source") or "").strip()
    if review_source:
        review_target = str(mirror.get("review_target") or ".codex-design/review/REVIEW_CONTEXT.md").strip()
        bindings.append(
            MirrorBinding(
                key="review:review_context",
                local_path=ROOT / review_target,
                source_path=DEFAULT_DESIGN_ROOT.parents[1] / review_source,
            )
        )

    return bindings


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _expected_queue_source_items() -> list[str]:
    expected = []
    for binding in _bindings():
        if binding.local_path == LOCAL_PRODUCT_ROOT / "NEXT_90_DAY_PRODUCT_ADVANCE_REGISTRY.yaml":
            expected.append(binding.local_path.as_posix())
        if binding.local_path == LOCAL_PRODUCT_ROOT / "NEXT_90_DAY_QUEUE_STAGING.generated.yaml":
            expected.append(binding.local_path.as_posix())
    return expected


def _load_queue_overlay() -> dict[str, object]:
    return _load_yaml(QUEUE_OVERLAY_PATH)


def _mirror_feedback_filenames() -> list[str]:
    return sorted(path.name for path in FEEDBACK_ROOT.glob(f"*{EXPECTED_QUEUE_PACKAGE_ID}.md"))


def _normalize_applied_feedback_entry(entry: str) -> str:
    return Path(str(entry).strip()).name


def _applied_feedback_lines() -> list[str]:
    if not APPLIED_FEEDBACK_LOG_PATH.exists():
        return []
    return [line.strip() for line in APPLIED_FEEDBACK_LOG_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]


def _applied_feedback_entries() -> list[str]:
    return [
        normalized
        for normalized in (_normalize_applied_feedback_entry(line) for line in _applied_feedback_lines())
        if normalized
    ]


def inspect_feedback_log() -> dict[str, object]:
    row: dict[str, object] = {
        "key": "feedback:applied_log",
        "local_path": APPLIED_FEEDBACK_LOG_PATH.as_posix(),
        "status": "ok",
    }
    if not APPLIED_FEEDBACK_LOG_PATH.exists():
        row["status"] = "missing_local"
        return row

    expected_entries = _mirror_feedback_filenames()
    applied_entries = _applied_feedback_entries()
    applied_set = set(applied_entries)
    missing_entries = [entry for entry in expected_entries if entry not in applied_set]
    duplicate_entries = sorted({entry for entry, count in Counter(applied_entries).items() if count > 1})
    row["expected_entry_count"] = len(expected_entries)
    row["missing_entry_count"] = len(missing_entries)
    row["missing_entries"] = missing_entries
    row["duplicate_entries"] = duplicate_entries
    if missing_entries or duplicate_entries:
        row["status"] = "feedback_reopen_risk"
    return row


def _find_queue_item(items: list[object]) -> tuple[int, dict[str, object]] | tuple[None, None]:
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        if str(item.get("package_id") or "").strip() == EXPECTED_QUEUE_PACKAGE_ID:
            return index, item
        if str(item.get("audit_finding_key") or "").strip() == EXPECTED_QUEUE_AUDIT_FINDING_KEY:
            return index, item
    return None, None


def _matching_queue_item(item: object) -> bool:
    if not isinstance(item, dict):
        return False
    package_id = str(item.get("package_id") or "").strip()
    finding_key = str(item.get("audit_finding_key") or "").strip()
    return package_id == EXPECTED_QUEUE_PACKAGE_ID or finding_key == EXPECTED_QUEUE_AUDIT_FINDING_KEY


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
    if mode != EXPECTED_QUEUE_MODE:
        mismatches.append(f"mode:{mode or '<missing>'}")
    if str(item.get("source_ref") or "").strip() != EXPECTED_QUEUE_SOURCE_REF:
        mismatches.append("source_ref")
    if str(item.get("audit_finding_key") or "").strip() != EXPECTED_QUEUE_AUDIT_FINDING_KEY:
        mismatches.append("audit_finding_key")
    if str(item.get("audit_scope_id") or "").strip() != EXPECTED_QUEUE_AUDIT_SCOPE_ID:
        mismatches.append("audit_scope_id")
    if str(item.get("title") or "").strip() != EXPECTED_QUEUE_TASK:
        mismatches.append("title")
    if str(item.get("task") or "").strip() != EXPECTED_QUEUE_TASK:
        mismatches.append("task")
    if list(item.get("allowed_paths") or []) != EXPECTED_QUEUE_ALLOWED_PATHS:
        mismatches.append("allowed_paths")
    if list(item.get("owned_surfaces") or []) != EXPECTED_QUEUE_OWNED_SURFACES:
        mismatches.append("owned_surfaces")
    if list(item.get("source_items") or []) != _expected_queue_source_items():
        mismatches.append("source_items")
    matching_count = sum(1 for candidate in items if _matching_queue_item(candidate))
    if matching_count != 1:
        mismatches.append(f"mirror_item_count:{matching_count}")

    row["mode"] = mode
    row["mirror_item_index"] = index
    row["mirror_item_count"] = matching_count
    row["package_id"] = str(item.get("package_id") or "").strip()
    row["source_items"] = list(item.get("source_items") or [])
    if mismatches:
        row["status"] = "queue_drift"
        row["mismatches"] = mismatches
    return row


def inspect_bundle() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    expected_product_rel_paths: set[Path] = set()
    for binding in _bindings():
        local_exists = binding.local_path.exists()
        source_exists = binding.source_path.exists()
        if binding.local_path.is_relative_to(LOCAL_PRODUCT_ROOT):
            expected_product_rel_paths.add(binding.local_path.relative_to(LOCAL_PRODUCT_ROOT))
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
    stale_product_files: list[str] = []
    if LOCAL_PRODUCT_ROOT.exists():
        for path in sorted(item for item in LOCAL_PRODUCT_ROOT.rglob("*") if item.is_file()):
            rel_path = path.relative_to(LOCAL_PRODUCT_ROOT)
            if rel_path not in expected_product_rel_paths and rel_path not in LOCAL_PRODUCT_EXCEPTIONS:
                stale_product_files.append(rel_path.as_posix())
    rows.append(
        {
            "key": "product:stale_local_files",
            "local_path": LOCAL_PRODUCT_ROOT.as_posix(),
            "status": "ok" if not stale_product_files else "stale_local_files",
            "stale_files": stale_product_files,
        }
    )
    rows.append(inspect_queue_overlay())
    rows.append(inspect_feedback_log())
    return rows


def repair_bundle() -> list[dict[str, object]]:
    inspection_rows = inspect_bundle()
    inspection_index = {str(row["key"]): row for row in inspection_rows}
    results: list[dict[str, object]] = []
    for binding in _bindings():
        row = inspection_index[binding.key]
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
    stale_row = dict(inspection_index["product:stale_local_files"])
    stale_files = [LOCAL_PRODUCT_ROOT / rel for rel in stale_row.get("stale_files") or []]
    if stale_files:
        for stale_path in stale_files:
            stale_path.unlink()
        for directory in sorted((item for item in LOCAL_PRODUCT_ROOT.rglob("*") if item.is_dir()), reverse=True):
            try:
                directory.rmdir()
            except OSError:
                continue
        stale_row["status"] = "ok"
        stale_row["action"] = "pruned"
        stale_row["stale_files"] = []
    else:
        stale_row["action"] = "unchanged"
    results.append(stale_row)

    queue_row = inspection_index["published_queue_overlay"]
    queue_result = dict(queue_row)
    if str(queue_row["status"]) == "ok":
        queue_result["action"] = "unchanged"
    else:
        payload = _load_queue_overlay() if QUEUE_OVERLAY_PATH.exists() else {}
        payload["mode"] = EXPECTED_QUEUE_MODE
        items = payload.get("items") or []
        if not isinstance(items, list):
            items = []
        preserved_items = [item for item in items if not _matching_queue_item(item)]
        item = {
            "title": EXPECTED_QUEUE_TASK,
            "task": EXPECTED_QUEUE_TASK,
            "package_id": EXPECTED_QUEUE_PACKAGE_ID,
        }
        item["source_ref"] = EXPECTED_QUEUE_SOURCE_REF
        item["audit_finding_key"] = EXPECTED_QUEUE_AUDIT_FINDING_KEY
        item["audit_scope_id"] = EXPECTED_QUEUE_AUDIT_SCOPE_ID
        item["allowed_paths"] = EXPECTED_QUEUE_ALLOWED_PATHS
        item["owned_surfaces"] = EXPECTED_QUEUE_OWNED_SURFACES
        item["source_items"] = _expected_queue_source_items()
        payload["items"] = [item, *preserved_items]
        QUEUE_OVERLAY_PATH.parent.mkdir(parents=True, exist_ok=True)
        QUEUE_OVERLAY_PATH.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
        queue_result = inspect_queue_overlay()
        queue_result["action"] = "repaired"
    results.append(queue_result)

    feedback_row = inspection_index["feedback:applied_log"]
    feedback_result = dict(feedback_row)
    if str(feedback_row["status"]) == "ok":
        feedback_result["action"] = "unchanged"
    else:
        expected_entries = set(_mirror_feedback_filenames())
        applied_lines = _applied_feedback_lines()
        final_lines: list[str] = []
        seen_target_entries: set[str] = set()
        removed_duplicates = 0
        for line in applied_lines:
            entry = _normalize_applied_feedback_entry(line)
            if entry in expected_entries:
                if entry in seen_target_entries:
                    removed_duplicates += 1
                    continue
                seen_target_entries.add(entry)
            final_lines.append(line)
        missing_entries = [entry for entry in _mirror_feedback_filenames() if entry not in seen_target_entries]
        APPLIED_FEEDBACK_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        final_lines.extend(f"feedback/{entry}" for entry in missing_entries)
        with APPLIED_FEEDBACK_LOG_PATH.open("w", encoding="utf-8") as handle:
            if final_lines:
                handle.write("\n".join(final_lines) + "\n")
        feedback_result = inspect_feedback_log()
        feedback_result["action"] = "repaired"
        feedback_result["appended_entries"] = missing_entries
        feedback_result["deduped_entries_removed"] = removed_duplicates
    results.append(feedback_result)
    return results


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify or repair the full EA design-mirror bundle audited for recurring drift."
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
