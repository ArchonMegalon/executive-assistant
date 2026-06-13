#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PROJECT_MODES_OUTPUT = ROOT / ".codex-design/product/PROJECT_MODES.generated.json"
SHOW_SURFACE_OUTPUT = ROOT / ".codex-design/product/SHOW_SURFACE_MANIFEST.generated.json"
MEMORIAL_VOICE_GATE = ROOT / ".codex-studio/published/memorial_voice_roundtrip_exit_gate.generated.json"
MEMORIAL_PUBLIC_VOICE_GATE = ROOT / ".codex-studio/published/memorial_voice_roundtrip_public_origin.generated.json"
MEMORIAL_PUBLIC_BROWSER_GATE = ROOT / ".codex-studio/published/memorial_realtime_browser_public_origin.generated.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _git_head() -> str:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(ROOT),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=10,
        )
    except Exception:
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _memorial_mode_status() -> str:
    try:
        receipt = json.loads(MEMORIAL_VOICE_GATE.read_text(encoding="utf-8"))
    except Exception:
        return "separate_risk_zone"
    return "shipping_memorial" if str(receipt.get("status") or "").strip().lower() == "pass" else "separate_risk_zone"


def _receipt_passes(path: Path) -> bool:
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    return str(receipt.get("status") or "").strip().lower() == "pass"


def _memorial_public_gold_status() -> str:
    if _receipt_passes(MEMORIAL_PUBLIC_VOICE_GATE) and _receipt_passes(MEMORIAL_PUBLIC_BROWSER_GATE):
        return "public_origin_gold_candidate"
    return "public_origin_gold_blocked"


def project_modes() -> dict[str, Any]:
    return {
        "contract_name": "ea.project_modes",
        "generated_at": _utc_now(),
        "generated_by": "scripts/materialize_project_mode_manifests.py",
        "git_head": _git_head(),
        "modes": [
            {
                "key": "EA_CORE",
                "status": "shipping_core",
                "purpose": "Executive office product: morning memo, decisions, commitments, approvals, durable office memory.",
                "route_prefixes": ["/", "/product", "/integrations", "/security", "/pricing", "/docs", "/get-started", "/sign-in", "/app/", "/admin/"],
                "hard_gate": "tests/e2e/test_ea_first_value_journey.py",
                "design_language": "calm, direct, office-grade, decision-first",
            },
            {
                "key": "MEMORIAL",
                "status": _memorial_mode_status(),
                "public_gold_status": _memorial_public_gold_status(),
                "claim_labels": {
                    "local": "Memorial local release candidate",
                    "public": "Memorial public-origin gold",
                },
                "purpose": "Manfred memorial pages and realtime voice from local memories/conversation sources only. No internet search for Manfred.",
                "route_prefixes": ["/memorials/", "/memorials/files/"],
                "hard_gate": "make memorial-gold-gates",
                "hard_gates": [
                    ".codex-studio/published/memorial_voice_roundtrip_exit_gate.generated.json",
                    ".codex-studio/published/memorial_voice_roundtrip_public_origin.generated.json",
                    ".codex-studio/published/memorial_realtime_browser_public_origin.generated.json",
                ],
                "local_release_gate": ".codex-studio/published/memorial_voice_roundtrip_exit_gate.generated.json",
                "public_gold_gates": [
                    ".codex-studio/published/memorial_voice_roundtrip_public_origin.generated.json",
                    ".codex-studio/published/memorial_realtime_browser_public_origin.generated.json",
                ],
                "design_language": "quiet, source-bound, emotionally safe",
            },
            {
                "key": "PROVIDER_LAB",
                "status": "operator_lab",
                "purpose": "LTD/media/document/voice provider proof lanes and candidate render receipts.",
                "route_prefixes": [],
                "script_prefixes": ["scripts/verify_joggai_", "scripts/verify_memorial_joggai_", "scripts/materialize_poppy_", "scripts/materialize_magicfit_"],
                "hard_gate": "scripts/verify_ltd_provider_lanes.py",
                "design_language": "internal, receipt-oriented, not product truth",
            },
            {
                "key": "CHUMMER_RELEASE_CONTROL",
                "status": "release_control_projection",
                "purpose": "Chummer/Fleet/Black Ledger external receipt consumption and gold-map projection.",
                "route_prefixes": [],
                "hard_gate": ".codex-design/product/WHOLE_PROJECT_GOLD_MAP.generated.json",
                "design_language": "evidence ledger, not customer-facing EA copy",
            },
            {
                "key": "PROPERTY",
                "status": "separate_product_plane",
                "purpose": "PropertyQuarry/provider search, market evidence, and property-specific public surfaces.",
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
        "git_head": _git_head(),
        "demo_mode": "ea_core",
        "allowed_surfaces": ["/", "/product", "/get-started", "/sign-in", "/app/today", "/app/queue", "/app/commitments", "/app/settings"],
        "operator_surfaces": ["/modes", "/admin/*"],
        "forbidden_surfaces": ["/memorials/*", "/memorials/files/*", "/results/*", "/tours/*", "/properties*", "/property*"],
        "allowed_provider_names": ["Google", "Email"],
        "forbidden_provider_names": ["JoggAI", "MagicFit", "VidBoard", "Poppy", "Unmixr", "VoiceWave", "FlipLink"],
        "allowed_assets": [],
        "operator_notes": [
            "EA core demos must show the office loop first: morning memo, decision queue, commitments, approvals.",
            "Memorial, provider lab, Chummer release control, and property surfaces require explicit separate demo mode.",
            "Use separate labels: EA receipt-set gold, Memorial local release candidate, and Memorial public-origin gold.",
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
