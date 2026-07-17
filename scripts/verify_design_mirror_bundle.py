#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "ea") not in sys.path:
    sys.path.insert(0, str(ROOT / "ea"))

from app.yaml_inputs import load_yaml_dict  # noqa: E402

LOCAL_PRODUCT_ROOT = ROOT / ".codex-design" / "product"
MIRROR_MANIFEST_PATH = ROOT / ".codex-design" / "repo" / "DESIGN_MIRROR_MANIFEST.yaml"
QUEUE_BINDING_KEY = "next_90_day_queue_staging"
QUEUE_LOCAL_PATH = ".codex-design/product/NEXT_90_DAY_QUEUE_STAGING.generated.yaml"


def _canonical_product_root_from_manifest() -> Path:
    payload = load_yaml_dict(MIRROR_MANIFEST_PATH)
    bindings = payload.get("bindings") or []
    matches = [
        binding
        for binding in bindings
        if isinstance(binding, dict) and str(binding.get("key") or "").strip() == QUEUE_BINDING_KEY
    ]
    if len(matches) != 1:
        raise RuntimeError(f"design mirror manifest must define exactly one {QUEUE_BINDING_KEY!r} binding")
    binding = matches[0]
    if (
        str(binding.get("kind") or "").strip() != "file"
        or binding.get("required") is not True
        or str(binding.get("local_path") or "").strip() != QUEUE_LOCAL_PATH
    ):
        raise RuntimeError(f"design mirror manifest has an invalid {QUEUE_BINDING_KEY!r} binding")
    source_path = Path(str(binding.get("source_path") or "").strip()).expanduser()
    if not source_path.is_absolute() or source_path.name != Path(QUEUE_LOCAL_PATH).name:
        raise RuntimeError(f"design mirror manifest has an invalid {QUEUE_BINDING_KEY!r} source_path")
    return source_path.parent


def _design_root() -> Path:
    for env_name in (
        "EA_DESIGN_ROOT",
        "EA_MIRROR_FIXTURE_ROOT",
        "CHUMMER6_DESIGN_PRODUCT_ROOT",
    ):
        value = str(os.environ.get(env_name) or "").strip()
        if value:
            return Path(value).expanduser()
    workspace_root = str(os.environ.get("EA_WORKSPACE_ROOT") or "").strip()
    if workspace_root:
        return (
            Path(workspace_root).expanduser()
            / "chummercomplete"
            / "chummer-design"
            / "products"
            / "chummer"
        )
    return _canonical_product_root_from_manifest()


_CANONICAL_EA_ROOT_VALUE = str(os.environ.get("EA_CANONICAL_ROOT") or "").strip()
CANONICAL_EA_ROOT = (
    Path(_CANONICAL_EA_ROOT_VALUE).expanduser()
    if _CANONICAL_EA_ROOT_VALUE
    else None
)
DEFAULT_DESIGN_ROOT = _design_root()
QUEUE_OVERLAY_PATH = ROOT / ".codex-studio" / "published" / "QUEUE.generated.yaml"
EXPECTED_QUEUE_PACKAGE_ID = "audit-task-4257456"
EXPECTED_QUEUE_SOURCE_REF = "audit_task_candidates[4257456]"
EXPECTED_QUEUE_AUDIT_FINDING_KEY = "project.design_mirror_missing_or_stale"
EXPECTED_QUEUE_AUDIT_SCOPE_ID = "ea"
EXPECTED_QUEUE_ALLOWED_PATHS = [".codex-design"]
EXPECTED_QUEUE_OWNED_SURFACES = ["design_mirror:ea"]
EXPECTED_QUEUE_TASK = (
    "Auto-detect and repair recurring `ea` mirror drift; "
    "keep one bounded queue slice for the affected local design mirror bundle instead of reopening one-off mirror refresh work."
)


def _normalize_queue_task_text(value: object) -> str:
    normalized = " ".join(str(value or "").split()).strip()
    if not normalized:
        return ""
    normalized = re.sub(
        r" after \d+ repeated audit observations;",
        ";",
        normalized,
        flags=re.IGNORECASE,
    )
    return normalized


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


def _source_is_external(path: Path) -> bool:
    source = path.resolve(strict=False)
    repo = ROOT.resolve(strict=False)
    try:
        source.relative_to(repo)
    except ValueError:
        return True
    return False


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _expected_queue_source_items() -> list[str]:
    if CANONICAL_EA_ROOT is None:
        return [
            binding.local_path.relative_to(ROOT).as_posix()
            for binding in _bindings()
        ]
    return [
        (CANONICAL_EA_ROOT / binding.local_path.relative_to(ROOT)).as_posix()
        for binding in _bindings()
    ]


def _acceptable_queue_source_items() -> tuple[list[str], ...]:
    return (
        _expected_queue_source_items(),
        [binding.local_path.as_posix() for binding in _bindings()],
        [binding.local_path.relative_to(ROOT).as_posix() for binding in _bindings()],
    )


def _queue_source_items_are_acceptable(items: list[object]) -> bool:
    normalized = [str(item or "").strip() for item in items]
    if normalized in _acceptable_queue_source_items():
        return True
    bindings = _bindings()
    if len(normalized) != len(bindings):
        return False
    for value, binding in zip(normalized, bindings, strict=True):
        candidate = Path(value)
        suffix = binding.local_path.relative_to(ROOT).parts
        if not candidate.is_absolute() or tuple(candidate.parts[-len(suffix) :]) != suffix:
            return False
    return True


def _load_successor_queue(path: Path) -> dict[str, object]:
    payload = load_yaml_dict(path)
    return payload if isinstance(payload, dict) else {}


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
    if _normalize_queue_task_text(item.get("title")) != EXPECTED_QUEUE_TASK:
        mismatches.append("title")
    if _normalize_queue_task_text(item.get("task")) != EXPECTED_QUEUE_TASK:
        mismatches.append("task")
    if list(item.get("allowed_paths") or []) != EXPECTED_QUEUE_ALLOWED_PATHS:
        mismatches.append("allowed_paths")
    if list(item.get("owned_surfaces") or []) != EXPECTED_QUEUE_OWNED_SURFACES:
        mismatches.append("owned_surfaces")
    if not _queue_source_items_are_acceptable(list(item.get("source_items") or [])):
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
        source_is_external = _source_is_external(binding.source_path)
        row: dict[str, object] = {
            "key": binding.key,
            "local_path": binding.local_path.as_posix(),
            "source_path": binding.source_path.as_posix(),
            "local_exists": local_exists,
            "source_exists": source_exists,
            "source_is_external": source_is_external,
            "status": "ok",
        }
        if not source_is_external:
            row["status"] = "source_not_external"
        elif not local_exists and not source_exists:
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
            local_payload = _load_successor_queue(binding.local_path)
            source_payload = _load_successor_queue(binding.source_path)
            local_items = local_payload.get("items") or []
            source_items = source_payload.get("items") or []
            row["local_item_count"] = len(local_items) if isinstance(local_items, list) else 0
            row["source_item_count"] = len(source_items) if isinstance(source_items, list) else 0
            if not isinstance(source_items, list) or not source_items:
                row["status"] = "invalid_source_payload"
            elif not isinstance(local_items, list) or not local_items:
                row["status"] = "invalid_local_payload"
            elif local_sha != source_sha:
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
        elif status == "source_not_external":
            result["action"] = "blocked_non_external_source"
        elif status in {
            "missing_source",
            "missing_local_and_source",
            "invalid_source_payload",
        }:
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
        item["title"] = EXPECTED_QUEUE_TASK
        item["task"] = EXPECTED_QUEUE_TASK
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
