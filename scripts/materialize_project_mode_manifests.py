#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from scripts.source_state_head import resolve_source_state_head
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from source_state_head import resolve_source_state_head


ROOT = Path(__file__).resolve().parents[1]
PROJECT_MODES_OUTPUT = ROOT / ".codex-design/product/PROJECT_MODES.generated.json"
SHOW_SURFACE_OUTPUT = ROOT / ".codex-design/product/SHOW_SURFACE_MANIFEST.generated.json"
GENERATED_RECEIPT_PATHS = {
    ".codex-design/product/EA_FLAGSHIP_RELEASE_GATE.generated.json",
    ".codex-design/product/PROJECT_MODES.generated.json",
    ".codex-design/product/SHOW_SURFACE_MANIFEST.generated.json",
    ".codex-design/product/WEEKLY_PRODUCT_PULSE.generated.json",
    ".codex-design/product/WHOLE_PROJECT_GOLD_MAP.generated.json",
    ".codex-studio/published/EA_BROWSER_WORKFLOW_PROOF.generated.json",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _git_head() -> str:
    return resolve_source_state_head(ROOT)


def _recorded_source_head(payload: dict[str, Any]) -> str:
    return str(payload.get("source_git_head") or payload.get("git_head") or "").strip()


def _fresh_enough(recorded_head: str, *, current_head: str) -> bool:
    recorded = str(recorded_head or "").strip()
    if not recorded or not current_head:
        return False
    if recorded == current_head:
        return True
    try:
        proc = subprocess.run(
            ["git", "-C", str(ROOT), "diff", "--name-only", f"{recorded}..{current_head}"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return False
    if proc.returncode != 0:
        return False
    changed = {line.strip() for line in proc.stdout.splitlines() if line.strip()}
    return bool(changed) and changed <= GENERATED_RECEIPT_PATHS


def project_modes() -> dict[str, Any]:
    return {
        "contract_name": "ea.project_modes",
        "generated_at": _utc_now(),
        "generated_by": "scripts/materialize_project_mode_manifests.py",
        "source_git_head": _git_head(),
        "head_semantics": "source_state",
        "modes": [
            {
                "key": "EA_CORE",
                "status": "shipping_core",
                "purpose": "Executive office product: morning memo, decisions, commitments, approvals, and durable office memory.",
                "route_prefixes": ["/", "/product", "/integrations", "/security", "/pricing", "/docs", "/get-started", "/sign-in", "/app/", "/admin/"],
                "hard_gate": "tests/e2e/test_ea_first_value_journey.py",
                "design_language": "calm, direct, office-grade, decision-first",
            },
            {
                "key": "PROVIDER_LAB",
                "status": "operator_lab",
                "purpose": "LTD, media, document, and voice-provider proof lanes with candidate receipts.",
                "route_prefixes": [],
                "hard_gate": "scripts/verify_ltd_provider_lanes.py",
                "design_language": "internal, receipt-oriented, not product truth",
            },
            {
                "key": "CHUMMER_RELEASE_CONTROL",
                "status": "release_control_projection",
                "purpose": "Chummer, Fleet, and Black Ledger external receipt consumption and gold-map projection.",
                "route_prefixes": [],
                "hard_gate": ".codex-design/product/WHOLE_PROJECT_GOLD_MAP.generated.json",
                "design_language": "evidence ledger, not customer-facing EA copy",
            },
            {
                "key": "PROPERTY",
                "status": "separate_product_plane",
                "purpose": "PropertyQuarry provider search, market evidence, and property-specific public surfaces.",
                "route_prefixes": ["/properties", "/property"],
                "hard_gate": "property-release-gates",
                "design_language": "trust, accuracy, market evidence",
            },
        ],
    }


def show_surface_manifest() -> dict[str, Any]:
    return {
        "contract_name": "ea.show_surface_manifest",
        "generated_at": _utc_now(),
        "generated_by": "scripts/materialize_project_mode_manifests.py",
        "source_git_head": _git_head(),
        "head_semantics": "source_state",
        "demo_mode": "ea_core",
        "allowed_surfaces": ["/", "/product", "/get-started", "/sign-in", "/app/today", "/app/queue", "/app/commitments", "/app/settings"],
        "operator_surfaces": ["/modes", "/admin/*"],
        "forbidden_surfaces": ["/results/*", "/tours/*", "/properties*", "/property*"],
        "allowed_provider_names": ["Google", "Email"],
        "forbidden_provider_names": ["JoggAI", "MagicFit", "VidBoard", "Poppy", "Unmixr", "VoiceWave", "FlipLink"],
        "allowed_assets": [],
        "operator_notes": [
            "EA core demos show the office loop first: morning memo, decision queue, commitments, and approvals.",
            "Provider lab, Chummer release control, and property surfaces require an explicit separate demo mode.",
            "A pass in one repository or product plane must not be projected as another product's release claim.",
        ],
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    write_json(PROJECT_MODES_OUTPUT, project_modes())
    write_json(SHOW_SURFACE_OUTPUT, show_surface_manifest())
    print(json.dumps({"status": "pass", "outputs": [str(PROJECT_MODES_OUTPUT), str(SHOW_SURFACE_OUTPUT)]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
