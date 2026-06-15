#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EA_PATH = ROOT / "ea"
for candidate in (ROOT, EA_PATH):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from app.services.ltd_provider_governance import build_ltd_provider_governance_receipt  # noqa: E402


DEFAULT_OUTPUT = ROOT / ".codex-design/product/WHOLE_PROJECT_GOLD_MAP.generated.json"
DEFAULT_FLAGSHIP_RECEIPT = ROOT / ".codex-design/product/EA_FLAGSHIP_RELEASE_GATE.generated.json"
DEFAULT_WEEKLY_PULSE = ROOT / ".codex-design/product/WEEKLY_PRODUCT_PULSE.generated.json"
DEFAULT_BROWSER_PROOF = ROOT / ".codex-studio/published/EA_BROWSER_WORKFLOW_PROOF.generated.json"
DEFAULT_MIRROR_BOUNDARY = ROOT / ".codex-design/repo/MIRROR_SCOPE_BOUNDARY.md"
DEFAULT_FLEET_JOURNEY_GATES = Path("/docker/fleet/.codex-studio/published/JOURNEY_GATES.generated.json")
DEFAULT_MEMORIAL_VOICE_ROUNDTRIP_RECEIPT = ROOT / ".codex-studio/published/memorial_voice_roundtrip_exit_gate.generated.json"
DEFAULT_MEMORIAL_PUBLIC_VOICE_RECEIPT = ROOT / ".codex-studio/published/memorial_voice_roundtrip_public_origin.generated.json"
DEFAULT_MEMORIAL_PUBLIC_BROWSER_RECEIPT = ROOT / ".codex-studio/published/memorial_realtime_browser_public_origin.generated.json"
DEFAULT_MEMORIAL_PUBLIC_ROOM_RECEIPT = ROOT / ".codex-studio/published/memorial_room_audio_public_origin.generated.json"
DEFAULT_CORE_RULE_RECEIPTS = (
    Path("/docker/chummercomplete/chummer-core-engine/.codex-studio/published/OPERATOR_PROMOTED_RULE_AUTHORITY_GOLD.generated.json"),
    Path("/docker/chummercomplete/chummer-core-engine/.codex-studio/published/FULL_PRODUCT_RULE_AUTHORITY_COMPLETION.generated.json"),
)
DEFAULT_DESKTOP_UI_RECEIPTS = (
    Path("/docker/chummercomplete/chummer-presentation/.codex-studio/published/DESKTOP_EXECUTABLE_EXIT_GATE.generated.json"),
    Path("/docker/chummercomplete/chummer-presentation/.codex-studio/published/DESKTOP_VISUAL_FAMILIARITY_EXIT_GATE.generated.json"),
    Path("/docker/chummercomplete/chummer-presentation/.codex-studio/published/CHUMMER5A_LAYOUT_HARD_GATE.generated.json"),
)
DEFAULT_HUB_PUBLIC_WEB_RECEIPTS = (
    Path("/docker/chummercomplete/chummer.run-services/.codex-studio/published/FLAGSHIP_PRODUCT_READINESS.generated.json"),
    Path("/docker/chummercomplete/chummer.run-services/.codex-studio/published/PUBLIC_ORIGIN_REACHABILITY_GATE.generated.json"),
    Path("/docker/chummercomplete/chummer.run-services/.codex-studio/published/PUBLIC_SHELL_CLICKABILITY_GATE.generated.json"),
)
DEFAULT_MOBILE_RECEIPTS = (
    Path("/docker/chummercomplete/chummer-play/.codex-studio/published/MOBILE_LOCAL_RELEASE_PROOF.generated.json"),
)
DEFAULT_MEDIA_RECEIPTS = (
    Path("/docker/chummercomplete/chummer.run-services/.codex-studio/published/BLACK_LEDGER_LIVE_MEDIA_PROOF.generated.json"),
)

BLOCKING_STATUSES = {
    "unknown_missing_receipt",
    "blocked",
    "fail",
    "draft_operator",
    "candidate_only",
    "separate_risk_zone",
}


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _git_head(path: Path = ROOT) -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except Exception:
        return ""


def _exists(path: Path) -> bool:
    try:
        return path.exists()
    except Exception:
        return False


def _display_path(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _load_ltd_summary() -> dict[str, Any]:
    receipt = build_ltd_provider_governance_receipt()
    lanes = list(receipt.get("lanes") or [])
    runtime = [lane for lane in lanes if bool(lane.get("runtime_enabled"))]
    draft = [lane for lane in lanes if not bool(lane.get("runtime_enabled"))]
    poppy = next((lane for lane in lanes if lane.get("lane_key") == "poppy_draft_workbench"), {})
    return {
        "contract_name": receipt.get("contract_name"),
        "status": receipt.get("status"),
        "lane_count": receipt.get("lane_count"),
        "runtime_lane_count": len(runtime),
        "draft_or_operator_lane_count": len(draft),
        "poppy_runtime_enabled": bool(poppy.get("runtime_enabled")) if poppy else None,
        "poppy_lane_state": poppy.get("lane_state") if poppy else None,
        "draft_or_operator_lanes": [str(lane.get("lane_key")) for lane in draft],
    }


def _plane(
    *,
    key: str,
    title: str,
    owner_repo: str,
    status: str,
    claim: str,
    evidence: list[str] | None = None,
    missing_evidence: list[str] | None = None,
    design_notes: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "key": key,
        "title": title,
        "owner_repo": owner_repo,
        "status": status,
        "claim": claim,
        "evidence": evidence or [],
        "missing_evidence": missing_evidence or [],
        "design_notes": design_notes or [],
    }


def _status_from_receipt(path: Path, allowed: set[str]) -> str:
    payload = _json(path)
    release_health = payload.get("release_health")
    flagship_readiness = payload.get("flagship_readiness")
    status = str(payload.get("status") or payload.get("overall_status") or "").strip().lower()
    if not status and isinstance(release_health, dict) and isinstance(flagship_readiness, dict):
        release_state = str(release_health.get("state") or "").strip().lower()
        flagship_state = str(flagship_readiness.get("state") or "").strip().lower()
        if release_state in allowed and flagship_state in allowed:
            status = "pass"
    return "pass" if status in allowed else "unknown_missing_receipt"


def _receipt_group_status(
    paths: tuple[Path, ...], *, allowed: set[str] = {"pass", "passed"}
) -> tuple[str, list[str], list[str]]:
    evidence: list[str] = []
    missing_or_blocked: list[str] = []
    for path in paths:
        payload = _json(path)
        if not payload:
            missing_or_blocked.append(_display_path(path))
            continue
        status = str(payload.get("status") or payload.get("overall_status") or payload.get("verdict") or "").strip().lower()
        if status in allowed:
            evidence.append(_display_path(path))
        else:
            missing_or_blocked.append(f"{_display_path(path)} status={status or 'missing'}")
    return ("pass" if not missing_or_blocked else "unknown_missing_receipt", evidence, missing_or_blocked)


def _fleet_status(path: Path) -> tuple[str, list[str], list[str]]:
    payload = _json(path)
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        return "unknown_missing_receipt", [], [_display_path(path)]
    state = str(summary.get("overall_state") or "").strip().lower()
    blocked_count = int(summary.get("blocked_count") or 0)
    if state == "ready" and blocked_count == 0:
        return "pass", [_display_path(path)], []
    return "blocked", [_display_path(path)], [f"fleet journey state={state or 'missing'} blocked_count={blocked_count}"]


def build_gold_map(
    *,
    output_path: Path = DEFAULT_OUTPUT,
    flagship_receipt_path: Path = DEFAULT_FLAGSHIP_RECEIPT,
    weekly_pulse_path: Path = DEFAULT_WEEKLY_PULSE,
    browser_proof_path: Path = DEFAULT_BROWSER_PROOF,
    mirror_boundary_path: Path = DEFAULT_MIRROR_BOUNDARY,
    fleet_journey_gates_path: Path = DEFAULT_FLEET_JOURNEY_GATES,
    core_rule_receipts: tuple[Path, ...] = DEFAULT_CORE_RULE_RECEIPTS,
    desktop_ui_receipts: tuple[Path, ...] = DEFAULT_DESKTOP_UI_RECEIPTS,
    hub_public_web_receipts: tuple[Path, ...] = DEFAULT_HUB_PUBLIC_WEB_RECEIPTS,
    mobile_receipts: tuple[Path, ...] = DEFAULT_MOBILE_RECEIPTS,
    media_receipts: tuple[Path, ...] = DEFAULT_MEDIA_RECEIPTS,
    memorial_voice_roundtrip_receipt: Path = DEFAULT_MEMORIAL_VOICE_ROUNDTRIP_RECEIPT,
    memorial_public_voice_receipt: Path = DEFAULT_MEMORIAL_PUBLIC_VOICE_RECEIPT,
    memorial_public_browser_receipt: Path = DEFAULT_MEMORIAL_PUBLIC_BROWSER_RECEIPT,
    memorial_public_room_receipt: Path = DEFAULT_MEMORIAL_PUBLIC_ROOM_RECEIPT,
    generated_at: str | None = None,
) -> dict[str, Any]:
    source_git_head = _git_head()
    flagship_status = _status_from_receipt(flagship_receipt_path, {"pass"})
    weekly_status = _status_from_receipt(weekly_pulse_path, {"ready", "clear", "pass"})
    browser_status = _status_from_receipt(browser_proof_path, {"pass"})
    ea_status = "pass" if {flagship_status, weekly_status, browser_status} == {"pass"} else "blocked"
    fleet_status, fleet_evidence, fleet_missing = _fleet_status(fleet_journey_gates_path)
    core_status, core_evidence, core_missing = _receipt_group_status(core_rule_receipts)
    desktop_status, desktop_evidence, desktop_missing = _receipt_group_status(desktop_ui_receipts)
    hub_status, hub_evidence, hub_missing = _receipt_group_status(hub_public_web_receipts)
    mobile_status, mobile_evidence, mobile_missing = _receipt_group_status(mobile_receipts)
    media_status_raw, media_evidence, media_missing = _receipt_group_status(media_receipts)
    media_status = "bounded_pass" if media_status_raw == "pass" else media_status_raw
    memorial_voice_status_raw = _status_from_receipt(memorial_voice_roundtrip_receipt, {"pass"})
    memorial_voice_status = "pass" if memorial_voice_status_raw == "pass" else "separate_risk_zone"
    memorial_voice_evidence = [_display_path(memorial_voice_roundtrip_receipt)] if memorial_voice_roundtrip_receipt.is_file() else []
    memorial_public_voice_status = _status_from_receipt(memorial_public_voice_receipt, {"pass"})
    memorial_public_browser_status = _status_from_receipt(memorial_public_browser_receipt, {"pass"})
    memorial_public_room_status = _status_from_receipt(memorial_public_room_receipt, {"pass"})
    memorial_public_gold_status = (
        "pass"
        if memorial_public_voice_status == "pass"
        and memorial_public_browser_status == "pass"
        and memorial_public_room_status == "pass"
        else "blocked"
    )
    memorial_voice_missing = (
        []
        if memorial_voice_status == "pass"
        else ["live memorial roundtrip transcript receipt", "voice intelligibility receipt", "latency p50/p95 receipt"]
    )
    memorial_public_missing = []
    if memorial_public_voice_status != "pass":
        memorial_public_missing.append("public-origin memorial voice+STT+TTS gold receipt")
    if memorial_public_browser_status != "pass":
        memorial_public_missing.append("public-origin browser realtime/audio playback gold receipt")
    if memorial_public_room_status != "pass":
        memorial_public_missing.append("public-origin room/device audio intelligibility receipt")
    memorial_public_design_notes = (
        [
            "Use: Memorial public-origin gold: pass.",
            "Do not collapse this memorial-specific proof into generic whole-project authority.",
        ]
        if memorial_public_gold_status == "pass"
        else [
            "Guest-facing copy must never say simply gold while this plane is blocked.",
            "Use: Memorial public-origin gold: blocked.",
        ]
    )
    ltd_summary = _load_ltd_summary()
    mirror_boundary_present = _exists(mirror_boundary_path)

    planes = [
        _plane(
            key="ea_release_control",
            title="Executive Assistant Release Control",
            owner_repo="EA",
            status=ea_status,
            claim="EA core workspace and release-control proof are green only when the EA receipt, weekly pulse, and browser workflow proof are green.",
            evidence=[
                _display_path(flagship_receipt_path),
                _display_path(weekly_pulse_path),
                _display_path(browser_proof_path),
            ],
            missing_evidence=[] if ea_status == "pass" else ["EA flagship receipt, weekly pulse, or browser proof is not pass"],
        ),
        _plane(
            key="fleet_journey_gates",
            title="Fleet Journey Gates",
            owner_repo="fleet",
            status=fleet_status,
            claim="Fleet journey gates are separate evidence; EA only consumes their generated summary.",
            evidence=fleet_evidence,
            missing_evidence=fleet_missing,
        ),
        _plane(
            key="design_surface",
            title="Design Surface And Mirror Boundary",
            owner_repo="design-front-door / EA mirror",
            status="bounded_pass" if mirror_boundary_present else "unknown_missing_receipt",
            claim="EA owns a bounded mirror and cannot infer all Chummer product design readiness from mirrored docs alone.",
            evidence=[_display_path(mirror_boundary_path)] if mirror_boundary_present else [],
            missing_evidence=[] if mirror_boundary_present else [_display_path(mirror_boundary_path)],
            design_notes=[
                "Whole-project design gold requires canonical product/UI review receipts outside the EA mirror.",
                "The EA mirror may be green while product-wide visual polish remains unproven.",
            ],
        ),
        _plane(
            key="chummer_core_rules",
            title="Chummer Core Rules And Data Correctness",
            owner_repo="chummer6-core",
            status=core_status,
            claim="Chummer core rules/data correctness is accepted only when the external rule-authority gold and completion receipts pass.",
            evidence=core_evidence,
            missing_evidence=core_missing,
        ),
        _plane(
            key="chummer_desktop_ui",
            title="Chummer Desktop/UI Product Surface",
            owner_repo="chummer6-ui",
            status=desktop_status,
            claim="Desktop/UI readiness is accepted only when executable, visual familiarity, and layout hard-gate receipts pass.",
            evidence=desktop_evidence,
            missing_evidence=desktop_missing,
        ),
        _plane(
            key="chummer_hub_public_web",
            title="Chummer Hub And Public Web",
            owner_repo="chummer6-hub",
            status=hub_status,
            claim="Hub/public web readiness is accepted only when flagship readiness, public origin reachability, and shell clickability receipts pass.",
            evidence=hub_evidence,
            missing_evidence=hub_missing,
        ),
        _plane(
            key="mobile_and_second_device",
            title="Mobile And Second-Device Continuation",
            owner_repo="mobile / hub",
            status=mobile_status,
            claim="Mobile readiness is accepted only when the Chummer play/mobile local release proof passes.",
            evidence=mobile_evidence,
            missing_evidence=mobile_missing,
        ),
        _plane(
            key="media_factory_publication",
            title="Media Factory And Video Publication",
            owner_repo="EA / Chummer media factory",
            status=media_status,
            claim="Published Black Ledger live media is accepted when its live media proof passes; future provider candidates remain draft/operator until asset-specific receipts exist.",
            evidence=media_evidence + ["scripts/verify_ltd_provider_lanes.py", ".codex-design/ea/POPPY_DRAFT_WORKFLOW.md"],
            missing_evidence=media_missing,
            design_notes=[
                "This is a bounded publication pass for current Black Ledger live media, not a blanket promotion of MagicFit, JoggAI, Poppy, or avatar candidate lanes.",
            ],
        ),
        _plane(
            key="memorial_voice_demo",
            title="Memorial Voice / Realtime Demo",
            owner_repo="memorial runtime",
            status=memorial_voice_status,
            claim="Memorial local voice release can pass separately from Memorial public-origin gold. Manfred remains local memories/conversation only, with no internet search.",
            evidence=memorial_voice_evidence,
            missing_evidence=memorial_voice_missing,
            design_notes=[
                "Public copy must not collapse this into a generic gold claim.",
                f"public_origin_gold_status={memorial_public_gold_status}",
                *memorial_public_missing,
            ],
        ),
        _plane(
            key="memorial_public_origin_gold",
            title="Memorial Public-Origin Experience Gold",
            owner_repo="memorial runtime",
            status=memorial_public_gold_status,
            claim="The public memorial experience is gold only when the deployed public origin proves the voice roundtrip receipt, browser realtime playback with live STT, room/device intelligibility, and latency. Local release receipts do not satisfy this plane.",
            evidence=[
                _display_path(path)
                for path in (
                    memorial_public_voice_receipt,
                    memorial_public_browser_receipt,
                    memorial_public_room_receipt,
                )
                if path.is_file()
            ],
            missing_evidence=memorial_public_missing,
            design_notes=memorial_public_design_notes,
        ),
        _plane(
            key="ltd_provider_lanes",
            title="LTD Provider Lanes",
            owner_repo="EA",
            status="mixed",
            claim="Provider lanes may be verified runtime, draft/operator, or parked inventory; they are not product truth.",
            evidence=["scripts/verify_ltd_provider_lanes.py"],
            design_notes=[
                f"lane_count={ltd_summary.get('lane_count')}",
                f"runtime_lane_count={ltd_summary.get('runtime_lane_count')}",
                f"draft_or_operator_lane_count={ltd_summary.get('draft_or_operator_lane_count')}",
            ],
        ),
    ]

    blocking_planes = [
        str(plane["key"])
        for plane in planes
        if str(plane.get("status") or "").strip().lower() in BLOCKING_STATUSES
    ]
    gold_claim_allowed = not blocking_planes and ea_status == "pass"
    overall_status = "gold" if gold_claim_allowed else "not_gold"
    claim_scope = "whole_project_plane_set"
    claim_scope_label = (
        "Whole-project gold is permitted only for the listed plane set, including memorial public-origin experience, proved by the current receipts."
        if gold_claim_allowed
        else "Whole-project gold is blocked unless every listed plane, including memorial public-origin experience, is proven."
    )
    required_next_receipts = (
        []
        if gold_claim_allowed
        else [
            "memorial_voice_roundtrip_public_origin.generated.json",
            "memorial_realtime_browser_public_origin.generated.json",
            "memorial_room_audio_public_origin.generated.json",
        ]
    )

    return {
        "contract_name": "ea.whole_project_gold_map",
        "generated_at": generated_at or _utc_now(),
        "generated_by": "scripts/materialize_whole_project_gold_map.py",
        "source_git_head": source_git_head,
        "head_semantics": "source_state",
        "head_semantics_note": "source_git_head records the proved source state. Generated-only artifact commits may advance repository HEAD without changing the source state that the receipts prove.",
        "output_path": output_path.relative_to(ROOT).as_posix(),
        "overall_status": overall_status,
        "gold_claim_allowed": gold_claim_allowed,
        "claim_scope": claim_scope,
        "claim_scope_label": claim_scope_label,
        "operator_summary": (
            "EA release control is green, but whole-project gold is blocked by unproven external or public-origin planes."
            if not gold_claim_allowed and ea_status == "pass"
            else "Whole-project gold is permitted by the current receipts. Owning repos remain authoritative for their planes."
            if gold_claim_allowed
            else "EA release control or required supporting receipts are blocked."
        ),
        "rules": [
            "EA flagship readiness does not imply whole Chummer project readiness.",
            "Unknown external planes block whole-project gold claims.",
            "Whole-project gold requires every listed plane to pass; EA receipt-set gold is only a narrower local label.",
            "External Chummer receipts may promote their own plane from unknown to pass when they are present and passing.",
            "Draft/operator LTD lanes cannot be treated as runtime or publication truth.",
            "Design mirror parity is bounded; canonical product/UI proof must come from owning repos.",
            "Memorial voice/realtime readiness requires its own browser, STT, TTS, and latency receipts.",
            "Memorial public-origin gold requires the public voice roundtrip receipt, public browser realtime receipt, and public room-audio receipt.",
        ],
        "blocking_planes": blocking_planes,
        "planes": planes,
        "ltd_provider_lane_summary": ltd_summary,
        "required_next_receipts": required_next_receipts,
    }


VOLATILE_KEYS = {"generated_at"}


def _normalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _normalize(item) for key, item in value.items() if key not in VOLATILE_KEYS}
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    return value


def write_json_stable(path: Path, payload: dict[str, Any]) -> None:
    serialized = json.dumps(payload, indent=2, ensure_ascii=True) + "\n"
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            existing = None
        if isinstance(existing, dict) and _normalize(existing) == _normalize(payload):
            return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialized, encoding="utf-8")


def main() -> int:
    if any(arg in {"--help", "-h"} for arg in sys.argv[1:]):
        print(
            "Usage:\n"
            "  python3 scripts/materialize_whole_project_gold_map.py [--output PATH]\n\n"
            "Materialize the conservative whole-project gold map. The receipt passes only as an honest map;\n"
            "it does not allow a whole-project gold claim while external planes are unproven."
        )
        return 0
    parser = argparse.ArgumentParser(description="Materialize the conservative whole-project gold map.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--fleet-journey-gates", type=Path, default=DEFAULT_FLEET_JOURNEY_GATES)
    args = parser.parse_args()

    receipt = build_gold_map(output_path=args.output, fleet_journey_gates_path=args.fleet_journey_gates)
    write_json_stable(args.output, receipt)
    print(json.dumps({"status": "pass", "output": args.output.as_posix(), "overall_status": receipt["overall_status"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
