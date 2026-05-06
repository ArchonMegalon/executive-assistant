from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml


_HYBRID_QUEUE_SPLIT_RE = re.compile(r"^mode:\s+", re.MULTILINE)
_QUEUE_KEY_LINE_RE = re.compile(r"^\s*[A-Za-z0-9_][A-Za-z0-9_\-]*:\s*")
_FLEET_SUCCESSOR_QUEUE_PATH = "/docker/fleet/.codex-studio/published/NEXT_90_DAY_QUEUE_STAGING.generated.yaml"
_DESIGN_SUCCESSOR_QUEUE_PATH = "/docker/chummercomplete/chummer-design/products/chummer/NEXT_90_DAY_QUEUE_STAGING.generated.yaml"


def _queue_item_identity(item: object) -> tuple[str, ...]:
    if isinstance(item, dict):
        package_id = str(item.get("package_id") or "").strip()
        if package_id:
            return ("package_id", package_id)
        work_task_id = str(item.get("work_task_id") or "").strip()
        title = str(item.get("title") or "").strip()
        if work_task_id and title:
            return ("work_task_id", work_task_id, title)
    return ("fallback", json.dumps(item, sort_keys=True, default=str))


def _merge_hybrid_queue_prefix_items(
    payload: dict[str, Any],
    prefix_items: list[object],
) -> dict[str, Any]:
    merged = dict(payload)
    items = merged.get("items") or []
    if not isinstance(items, list):
        items = []
    normalized_items = list(items)
    seen = {_queue_item_identity(item) for item in normalized_items}
    for item in prefix_items:
        identity = _queue_item_identity(item)
        if identity in seen:
            continue
        normalized_items.append(item)
        seen.add(identity)
    merged["items"] = normalized_items
    return merged


def _normalize_wrapped_queue_lines(text: str) -> str:
    lines = text.splitlines()
    normalized_lines: list[str] = []
    sequence_indent: int | None = None
    for line in lines:
        stripped = line.lstrip(" ")
        indent = len(line) - len(stripped)
        if not stripped:
            normalized_lines.append(line)
            continue
        is_key_line = bool(_QUEUE_KEY_LINE_RE.match(line))
        if stripped.startswith("- "):
            normalized_lines.append(line)
            sequence_indent = indent
            continue
        if sequence_indent is not None and indent <= sequence_indent and not is_key_line:
            normalized_lines.append(" " * (sequence_indent + 2) + stripped)
            continue
        normalized_lines.append(line)
        if sequence_indent is not None and is_key_line and indent <= sequence_indent:
            sequence_indent = None
    normalized = "\n".join(normalized_lines)
    if text.endswith("\n"):
        normalized += "\n"
    return normalized


def _load_hybrid_queue_payload(text: str) -> object | None:
    normalized_text = _normalize_wrapped_queue_lines(str(text or ""))
    stripped = normalized_text.lstrip()
    if not stripped.startswith("- "):
        return None
    match = _HYBRID_QUEUE_SPLIT_RE.search(normalized_text)
    if match is None:
        return None
    prefix_text = normalized_text[: match.start()].strip()
    suffix_text = normalized_text[match.start() :].strip()
    if not prefix_text or not suffix_text:
        return None
    try:
        prefix_payload = yaml.safe_load(prefix_text) or []
        suffix_payload = yaml.safe_load(suffix_text) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(prefix_payload, list) or not isinstance(suffix_payload, dict):
        return None
    return _merge_hybrid_queue_prefix_items(suffix_payload, prefix_payload)


def load_yaml_payload(path: Path) -> object | None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError:
        return _load_hybrid_queue_payload(text)


def load_yaml_dict(path: Path) -> dict[str, Any]:
    payload = load_yaml_payload(path)
    if not isinstance(payload, dict):
        return {}
    normalized = dict(payload)
    if path.as_posix() == _FLEET_SUCCESSOR_QUEUE_PATH and not str(normalized.get("source_design_queue_path") or "").strip():
        normalized["source_design_queue_path"] = _DESIGN_SUCCESSOR_QUEUE_PATH
    return normalized
