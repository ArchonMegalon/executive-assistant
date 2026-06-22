from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable


def ui_service_worker_cleanup_enabled() -> bool:
    return str(os.environ.get("EA_UI_SERVICE_WORKER_CLEANUP_ENABLED") or "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _resolved(path: Path) -> Path:
    return path.expanduser().resolve()


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def cleanup_ui_service_run_dir(
    *,
    run_dir: Path,
    asset_path: Path | None = None,
    preserve_paths: Iterable[Path | str] = (),
) -> dict[str, object]:
    root = _resolved(run_dir)
    keep: set[Path] = set()
    for candidate in (asset_path, *preserve_paths):
        if not candidate:
            continue
        resolved = _resolved(Path(candidate))
        if _within(resolved, root):
            keep.add(resolved)

    removed_paths: list[str] = []
    removed_bytes = 0

    for path in sorted(root.rglob("*"), key=lambda item: (len(item.relative_to(root).parts), str(item)), reverse=True):
        resolved = _resolved(path)
        if resolved in keep:
            continue
        if path.is_dir():
            try:
                path.rmdir()
            except OSError:
                pass
            continue
        if path.exists():
            removed_bytes += int(path.stat().st_size or 0)
            path.unlink(missing_ok=True)
            removed_paths.append(str(path.relative_to(root)))

    for path in sorted(root.rglob("*"), key=lambda item: (len(item.relative_to(root).parts), str(item)), reverse=True):
        if path.is_dir():
            try:
                path.rmdir()
            except OSError:
                pass

    return {
        "status": "cleaned" if removed_paths else "not_needed",
        "removed_bytes": removed_bytes,
        "removed_paths": removed_paths,
        "preserved_paths": [str(path.relative_to(root)) for path in sorted(keep)],
        "run_dir": str(root),
    }
