#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from scripts.memorial_spatial_public_origin_contract import (
        validate_memorial_spatial_public_origin_receipt,
    )
    from scripts.source_state_head import (
        resolve_source_state_head,
        resolve_source_worktree_fingerprint,
    )
except ModuleNotFoundError:  # pragma: no cover - script execution path
    from memorial_spatial_public_origin_contract import (
        validate_memorial_spatial_public_origin_receipt,
    )
    from source_state_head import (
        resolve_source_state_head,
        resolve_source_worktree_fingerprint,
    )


ROOT = Path(__file__).resolve().parents[1]
PROJECT_MODES_OUTPUT = ROOT / ".codex-design/product/PROJECT_MODES.generated.json"
SHOW_SURFACE_OUTPUT = ROOT / ".codex-design/product/SHOW_SURFACE_MANIFEST.generated.json"
MEMORIAL_VOICE_GATE = ROOT / ".codex-studio/published/memorial_voice_roundtrip_exit_gate.generated.json"
MEMORIAL_PUBLIC_VOICE_GATE = ROOT / ".codex-studio/published/memorial_voice_roundtrip_public_origin.generated.json"
MEMORIAL_PUBLIC_BROWSER_GATE = ROOT / ".codex-studio/published/memorial_realtime_browser_public_origin.generated.json"
MEMORIAL_PUBLIC_ROOM_GATE = ROOT / ".codex-studio/published/memorial_room_audio_public_origin.generated.json"
MEMORIAL_SPATIAL_PUBLIC_ORIGIN_GATE = ROOT / ".codex-studio/published/memorial_spatial_tour_public_origin.generated.json"
GENERATED_RECEIPT_PATHS = {
    ".codex-design/product/EA_FLAGSHIP_RELEASE_GATE.generated.json",
    ".codex-design/product/MEMORIAL_OPERATOR_STATUS.generated.json",
    ".codex-design/product/MEMORIAL_PHRASE_BANK.manfred.generated.json",
    ".codex-design/product/PROJECT_MODES.generated.json",
    ".codex-design/product/SHOW_SURFACE_MANIFEST.generated.json",
    ".codex-design/product/WEEKLY_PRODUCT_PULSE.generated.json",
    ".codex-design/product/WHOLE_PROJECT_GOLD_MAP.generated.json",
    ".codex-studio/published/EA_BROWSER_WORKFLOW_PROOF.generated.json",
    ".codex-studio/published/memorial_voice_roundtrip_exit_gate.generated.json",
    ".codex-studio/published/memorial_voice_roundtrip_public_origin.generated.json",
    ".codex-studio/published/memorial_realtime_browser_public_origin.generated.json",
    ".codex-studio/published/memorial_realtime_browser_meaningful_public_origin.generated.json",
    ".codex-studio/published/memorial_room_audio_public_origin.generated.json",
    ".codex-studio/published/memorial_spatial_tour_public_origin.generated.json",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _git_head() -> str:
    return resolve_source_state_head(ROOT)


def _source_fingerprint() -> str:
    return resolve_source_worktree_fingerprint(ROOT)


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
            ["git", "diff", "--name-only", f"{recorded}..{current_head}"],
            cwd=str(ROOT),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=10,
        )
    except Exception:
        return False
    if proc.returncode != 0:
        return False
    changed = {line.strip() for line in proc.stdout.splitlines() if line.strip()}
    return bool(changed) and changed <= GENERATED_RECEIPT_PATHS


def _memorial_mode_status(*, current_head: str) -> str:
    try:
        receipt = json.loads(MEMORIAL_VOICE_GATE.read_text(encoding="utf-8"))
    except Exception:
        return "separate_risk_zone"
    status = str(receipt.get("status") or "").strip().lower()
    if status != "pass":
        return "separate_risk_zone"
    if not _fresh_enough(_recorded_source_head(receipt), current_head=current_head):
        return "separate_risk_zone"
    return "shipping_memorial"


def _receipt_passes(path: Path, *, current_head: str) -> bool:
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    if str(receipt.get("status") or "").strip().lower() != "pass":
        return False
    return _fresh_enough(_recorded_source_head(receipt), current_head=current_head)


def _room_receipt_passes(path: Path, *, current_head: str) -> bool:
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    if str(receipt.get("status") or "").strip().lower() != "pass":
        return False
    attestation = dict(receipt.get("manual_attestation") or {})
    if (
        str(receipt.get("proof_type") or "").strip() != "manual_room_attestation"
        or not str(attestation.get("attestation_id") or "").strip()
        or not str(attestation.get("signed_at") or "").strip()
        or attestation.get("ci_must_not_auto_assert") is not True
    ):
        return False
    required_checks = {
        "actual_device_checked",
        "actual_speaker_checked",
        "first_syllable_not_clipped",
        "intelligibility_confirmed",
        "answer_text_fallback_visible",
        "no_internet_search_confirmed",
        "normal_spoken_turn_confirmed",
        "interruption_behavior_confirmed",
        "retry_path_confirmed",
    }
    checks = dict(receipt.get("checks") or {})
    if any(checks.get(key) is not True for key in required_checks):
        return False
    return _fresh_enough(_recorded_source_head(receipt), current_head=current_head)


def _spatial_receipt_passes(
    path: Path,
    *,
    current_head: str,
    current_fingerprint: str,
) -> bool:
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    return not validate_memorial_spatial_public_origin_receipt(
        receipt,
        current_head=current_head,
        current_fingerprint=current_fingerprint,
    )


def _memorial_public_gold_status(
    *,
    current_head: str,
    current_fingerprint: str,
) -> str:
    if (
        _receipt_passes(MEMORIAL_PUBLIC_VOICE_GATE, current_head=current_head)
        and _receipt_passes(MEMORIAL_PUBLIC_BROWSER_GATE, current_head=current_head)
        and _room_receipt_passes(MEMORIAL_PUBLIC_ROOM_GATE, current_head=current_head)
        and _spatial_receipt_passes(
            MEMORIAL_SPATIAL_PUBLIC_ORIGIN_GATE,
            current_head=current_head,
            current_fingerprint=current_fingerprint,
        )
    ):
        return "public_origin_gold_pass"
    return "public_origin_gold_blocked"


def project_modes() -> dict[str, Any]:
    source_git_head = _git_head()
    source_fingerprint = _source_fingerprint()
    return {
        "contract_name": "ea.project_modes",
        "generated_at": _utc_now(),
        "generated_by": "scripts/materialize_project_mode_manifests.py",
        "source_git_head": source_git_head,
        "head_semantics": "source_state",
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
                "status": _memorial_mode_status(current_head=source_git_head),
                "public_gold_status": _memorial_public_gold_status(
                    current_head=source_git_head,
                    current_fingerprint=source_fingerprint,
                ),
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
                    ".codex-studio/published/memorial_spatial_tour_public_origin.generated.json",
                ],
                "local_release_gate": ".codex-studio/published/memorial_voice_roundtrip_exit_gate.generated.json",
                "public_gold_gates": [
                    ".codex-studio/published/memorial_voice_roundtrip_public_origin.generated.json",
                    ".codex-studio/published/memorial_realtime_browser_public_origin.generated.json",
                    ".codex-studio/published/memorial_room_audio_public_origin.generated.json",
                    ".codex-studio/published/memorial_spatial_tour_public_origin.generated.json",
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
    source_git_head = _git_head()
    return {
        "contract_name": "ea.show_surface_manifest",
        "generated_at": _utc_now(),
        "generated_by": "scripts/materialize_project_mode_manifests.py",
        "source_git_head": source_git_head,
        "head_semantics": "source_state",
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
