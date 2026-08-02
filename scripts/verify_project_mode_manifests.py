#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

try:
    from scripts.materialize_project_mode_manifests import (
        _fresh_enough,
        _recorded_source_head,
    )
    from scripts.source_state_head import resolve_source_state_head
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from materialize_project_mode_manifests import _fresh_enough, _recorded_source_head
    from source_state_head import resolve_source_state_head


ROOT = Path(__file__).resolve().parents[1]
PROJECT_MODES = ROOT / ".codex-design/product/PROJECT_MODES.generated.json"
SHOW_SURFACE = ROOT / ".codex-design/product/SHOW_SURFACE_MANIFEST.generated.json"
REQUIRED_MODES = {"EA_CORE", "PROVIDER_LAB", "CHUMMER_RELEASE_CONTROL", "PROPERTY"}


def _load(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"invalid_json:{path}")
    return payload


def main() -> int:
    modes = _load(PROJECT_MODES)
    show = _load(SHOW_SURFACE)
    current_head = resolve_source_state_head(ROOT)
    for label, payload in (("project_modes_manifest", modes), ("show_surface_manifest", show)):
        if current_head and not _fresh_enough(
            _recorded_source_head(payload), current_head=current_head
        ):
            raise SystemExit(f"{label}_stale")

    rows = [row for row in list(modes.get("modes") or []) if isinstance(row, dict)]
    keys = {str(row.get("key") or "") for row in rows}
    if keys != REQUIRED_MODES:
        raise SystemExit("project_mode_set_invalid")
    by_key = {str(row.get("key")): row for row in rows}
    if by_key["EA_CORE"].get("status") != "shipping_core":
        raise SystemExit("ea_core_status_invalid")
    if show.get("demo_mode") != "ea_core":
        raise SystemExit("show_surface_demo_mode_invalid")
    if "/app/today" not in list(show.get("allowed_surfaces") or []):
        raise SystemExit("show_surface_first_value_missing")
    print(json.dumps({"status": "pass", "modes": sorted(keys)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
