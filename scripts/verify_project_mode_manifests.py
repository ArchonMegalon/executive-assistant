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
    allowed = set(show.get("allowed_surfaces") or [])
    if "/modes" in allowed:
        raise SystemExit("operator_modes_surface_leaked_into_public_demo")
    operator_surfaces = set(show.get("operator_surfaces") or [])
    if "/modes" not in operator_surfaces:
        raise SystemExit("operator_modes_surface_missing")
    ea_gate = ROOT / str(by_key["EA_CORE"].get("hard_gate") or "")
    if not ea_gate.is_file():
        raise SystemExit("ea_core_hard_gate_path_missing")
    memorial_gate = ROOT / str(by_key["MEMORIAL"].get("hard_gate") or "")
    if not memorial_gate.is_file():
        raise SystemExit("memorial_hard_gate_receipt_missing")
    try:
        memorial_receipt = json.loads(memorial_gate.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SystemExit(f"memorial_hard_gate_receipt_invalid:{exc}") from exc
    memorial_status = str(memorial_receipt.get("status") or "").strip().lower()
    if by_key["MEMORIAL"].get("status") == "shipping_memorial" and memorial_status != "pass":
        raise SystemExit("shipping_memorial_gate_not_passing")
    if by_key["MEMORIAL"].get("status") == "separate_risk_zone" and memorial_status == "pass":
        raise SystemExit("memorial_pass_receipt_still_marked_risk_zone")
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
