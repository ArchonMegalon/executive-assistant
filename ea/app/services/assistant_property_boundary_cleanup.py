from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from app.services.proactive_ooda_flat_search_policy import material_mentions_flat_property_search
from app.services.proactive_ooda_runtime_artifacts import resolve_runtime_artifact_paths


def default_assistant_property_boundary_roots() -> tuple[Path, ...]:
    repo_root = Path(__file__).resolve().parents[2]
    ordered: list[Path] = []
    for candidate in (repo_root, repo_root.parent):
        resolved = candidate.resolve()
        if resolved not in ordered:
            ordered.append(resolved)
    return tuple(ordered)


def cleanup_hidden_property_runtime_state(
    *,
    root_candidates: Iterable[Path] | None = None,
    state_path: str | Path = "state/proactive_ooda_notified.json",
    archive_label: str = "",
) -> dict[str, Any]:
    roots = tuple(root_candidates or default_assistant_property_boundary_roots())
    normalized_archive_label = str(archive_label or _archive_label()).strip() or _archive_label()
    stage_packet_total = 0
    safe_work_result_total = 0
    approval_callback_total = 0
    archived_total = 0
    archive_dirs: list[str] = []
    archived_stage_packets: list[str] = []
    archived_safe_work_results: list[str] = []
    archived_approval_callbacks: list[str] = []

    for root in roots:
        paths = resolve_runtime_artifact_paths(root=root, state_path=state_path)
        archive_root = _archive_root_for_paths(paths=paths, root=root, archive_label=normalized_archive_label)
        stage_packet_refs: set[str] = set()
        safe_work_result_refs: set[str] = set()

        for path in sorted(paths["stage_packet_dir"].glob("*.json")):
            payload = _read_json(path)
            if not _payload_mentions_hidden_property(payload):
                continue
            destination = archive_root / "stage_packets" / path.name
            _archive_file(path, destination)
            archive_dirs.append(str(destination.parent))
            archived_stage_packets.append(str(destination))
            archived_total += 1
            stage_packet_total += 1
            packet_ref = str(payload.get("packet_ref") or "").strip()
            if packet_ref:
                stage_packet_refs.add(packet_ref)

        for path in sorted(paths["safe_work_result_dir"].glob("*.json")):
            payload = _read_json(path)
            if not _payload_mentions_hidden_property(payload):
                continue
            destination = archive_root / "safe_work_results" / path.name
            _archive_file(path, destination)
            archive_dirs.append(str(destination.parent))
            archived_safe_work_results.append(str(destination))
            archived_total += 1
            safe_work_result_total += 1
            result_ref = str(payload.get("result_ref") or "").strip()
            if result_ref:
                safe_work_result_refs.add(result_ref)

        for path in sorted(paths["approval_callback_dir"].glob("*.json")):
            payload = _read_json(path)
            packet_ref = str(payload.get("packet_ref") or "").strip()
            staged_artifact_ref = str(payload.get("staged_artifact_ref") or "").strip()
            if (
                packet_ref not in stage_packet_refs
                and staged_artifact_ref not in safe_work_result_refs
                and not _payload_mentions_hidden_property(payload)
            ):
                continue
            destination = archive_root / "approval_callbacks" / path.name
            _archive_file(path, destination)
            archive_dirs.append(str(destination.parent))
            archived_approval_callbacks.append(str(destination))
            archived_total += 1
            approval_callback_total += 1

    return {
        "status": "ok",
        "roots": [str(root) for root in roots],
        "archive_label": normalized_archive_label,
        "archive_dirs": sorted(dict.fromkeys(archive_dirs)),
        "archived_total": archived_total,
        "stage_packet_total": stage_packet_total,
        "safe_work_result_total": safe_work_result_total,
        "approval_callback_total": approval_callback_total,
        "archived_stage_packets": archived_stage_packets,
        "archived_safe_work_results": archived_safe_work_results,
        "archived_approval_callbacks": archived_approval_callbacks,
    }


def _payload_mentions_hidden_property(payload: dict[str, Any]) -> bool:
    if not payload:
        return False
    return material_mentions_flat_property_search(payload)


def _archive_root_for_paths(*, paths: dict[str, Path], root: Path, archive_label: str) -> Path:
    artifact_root = paths.get("run_receipt_dir")
    if isinstance(artifact_root, Path):
        artifact_root = artifact_root.parent
    if not isinstance(artifact_root, Path):
        artifact_root = paths.get("stage_packet_dir")
        if isinstance(artifact_root, Path):
            artifact_root = artifact_root.parent
    if not isinstance(artifact_root, Path):
        artifact_root = root / "state"
    return artifact_root / "assistant_property_boundary_archive" / archive_label


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _archive_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    final_destination = _unique_destination(destination)
    source.replace(final_destination)


def _unique_destination(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    index = 2
    while True:
        candidate = parent / f"{stem}-{index}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def _archive_label() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
