#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROJECT_MODES = ROOT / ".codex-design/product/PROJECT_MODES.generated.json"
SHOW_SURFACE = ROOT / ".codex-design/product/SHOW_SURFACE_MANIFEST.generated.json"


def _load(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"invalid_json:{path}")
    return payload


def main() -> int:
    modes = _load(PROJECT_MODES)
    show = _load(SHOW_SURFACE)
    keys = {str(item.get("key") or "") for item in modes.get("modes", []) if isinstance(item, dict)}
    required = {"EA_CORE", "MEMORIAL", "PROVIDER_LAB", "CHUMMER_RELEASE_CONTROL", "PROPERTY"}
    missing = required - keys
    if missing:
        raise SystemExit(f"missing_project_modes:{','.join(sorted(missing))}")
    by_key = {str(item.get("key")): item for item in modes.get("modes", []) if isinstance(item, dict)}
    if by_key["EA_CORE"].get("status") != "shipping_core":
        raise SystemExit("ea_core_not_shipping_core")
    if by_key["MEMORIAL"].get("status") not in {"separate_risk_zone", "shipping_memorial"}:
        raise SystemExit("memorial_mode_status_invalid")
    if "tests/e2e/test_ea_first_value_journey.py" not in str(by_key["EA_CORE"].get("hard_gate") or ""):
        raise SystemExit("ea_core_first_value_gate_missing")
    if show.get("demo_mode") != "ea_core":
        raise SystemExit("show_surface_demo_mode_not_ea_core")
    forbidden = set(show.get("forbidden_surfaces") or [])
    for expected in {"/memorials/*", "/memorials/files/*", "/results/*", "/tours/*"}:
        if expected not in forbidden:
            raise SystemExit(f"show_surface_missing_forbidden:{expected}")
    forbidden_providers = set(show.get("forbidden_provider_names") or [])
    for provider in {"JoggAI", "MagicFit", "Poppy", "Unmixr", "VoiceWave"}:
        if provider not in forbidden_providers:
            raise SystemExit(f"show_surface_missing_provider:{provider}")
    print(json.dumps({"status": "pass", "message": "project mode manifests are bounded and explicit."}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
