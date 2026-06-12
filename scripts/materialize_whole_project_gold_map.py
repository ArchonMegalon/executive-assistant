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


def _fleet_status(path: Path) -> tuple[str, list[str], list[str]]:
    payload = _json(path)
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        return "unknown_missing_receipt", [], [path.as_posix()]
    state = str(summary.get("overall_state") or "").strip().lower()
    blocked_count = int(summary.get("blocked_count") or 0)
    if state == "ready" and blocked_count == 0:
        return "pass", [path.as_posix()], []
    return "blocked", [path.as_posix()], [f"fleet journey state={state or 'missing'} blocked_count={blocked_count}"]


def build_gold_map(
    *,
    output_path: Path = DEFAULT_OUTPUT,
    flagship_receipt_path: Path = DEFAULT_FLAGSHIP_RECEIPT,
    weekly_pulse_path: Path = DEFAULT_WEEKLY_PULSE,
    browser_proof_path: Path = DEFAULT_BROWSER_PROOF,
    mirror_boundary_path: Path = DEFAULT_MIRROR_BOUNDARY,
    fleet_journey_gates_path: Path = DEFAULT_FLEET_JOURNEY_GATES,
    generated_at: str | None = None,
) -> dict[str, Any]:
    flagship_status = _status_from_receipt(flagship_receipt_path, {"pass"})
    weekly_status = _status_from_receipt(weekly_pulse_path, {"ready", "clear", "pass"})
    browser_status = _status_from_receipt(browser_proof_path, {"pass"})
    ea_status = "pass" if {flagship_status, weekly_status, browser_status} == {"pass"} else "blocked"
    fleet_status, fleet_evidence, fleet_missing = _fleet_status(fleet_journey_gates_path)
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
                flagship_receipt_path.relative_to(ROOT).as_posix(),
                weekly_pulse_path.relative_to(ROOT).as_posix(),
                browser_proof_path.relative_to(ROOT).as_posix(),
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
            evidence=[mirror_boundary_path.relative_to(ROOT).as_posix()] if mirror_boundary_present else [],
            missing_evidence=[] if mirror_boundary_present else [mirror_boundary_path.relative_to(ROOT).as_posix()],
            design_notes=[
                "Whole-project design gold requires canonical product/UI review receipts outside the EA mirror.",
                "The EA mirror may be green while product-wide visual polish remains unproven.",
            ],
        ),
        _plane(
            key="chummer_core_rules",
            title="Chummer Core Rules And Data Correctness",
            owner_repo="chummer6-core",
            status="unknown_missing_receipt",
            claim="No EA-local receipt proves complete Chummer rules/data correctness.",
            missing_evidence=["core rules parity receipt", "data migration receipt", "regression suite receipt"],
        ),
        _plane(
            key="chummer_desktop_ui",
            title="Chummer Desktop/UI Product Surface",
            owner_repo="chummer6-ui",
            status="unknown_missing_receipt",
            claim="No EA-local receipt proves desktop UI, visual polish, accessibility, or launcher flows end to end.",
            missing_evidence=["visual regression receipt", "accessibility receipt", "install/update journey receipt"],
        ),
        _plane(
            key="chummer_hub_public_web",
            title="Chummer Hub And Public Web",
            owner_repo="chummer6-hub",
            status="unknown_missing_receipt",
            claim="No EA-local receipt proves public hub, account, download, support, or landing surfaces are production-gold.",
            missing_evidence=["hub smoke receipt", "public web visual receipt", "support/contact receipt"],
        ),
        _plane(
            key="mobile_and_second_device",
            title="Mobile And Second-Device Continuation",
            owner_repo="mobile / hub",
            status="unknown_missing_receipt",
            claim="No EA-local receipt proves mobile, tablet, or second-device continuation journeys.",
            missing_evidence=["mobile viewport receipt", "second-device auth receipt", "session handoff receipt"],
        ),
        _plane(
            key="media_factory_publication",
            title="Media Factory And Video Publication",
            owner_repo="EA / Chummer media factory",
            status="draft_operator",
            claim="MagicFit, JoggAI, Poppy, and video/avatar lanes are governed draft/operator or candidate lanes unless separate publish receipts exist.",
            evidence=["scripts/verify_ltd_provider_lanes.py", ".codex-design/ea/POPPY_DRAFT_WORKFLOW.md"],
            missing_evidence=["approved render receipts for each published asset", "human review receipts", "source-of-truth publication receipts"],
        ),
        _plane(
            key="memorial_voice_demo",
            title="Memorial Voice / Realtime Demo",
            owner_repo="memorial runtime",
            status="separate_risk_zone",
            claim="Memorial voice quality and realtime conversation readiness must be proven by its own browser+STT+TTS exit gate, not by EA release readiness.",
            missing_evidence=["live memorial roundtrip transcript receipt", "voice intelligibility receipt", "latency p50/p95 receipt"],
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

    return {
        "contract_name": "ea.whole_project_gold_map",
        "generated_at": generated_at or _utc_now(),
        "generated_by": "scripts/materialize_whole_project_gold_map.py",
        "git_head": _git_head(),
        "output_path": output_path.relative_to(ROOT).as_posix(),
        "overall_status": overall_status,
        "gold_claim_allowed": gold_claim_allowed,
        "operator_summary": (
            "EA release control is green, but whole-project gold is blocked by unproven external planes."
            if not gold_claim_allowed and ea_status == "pass"
            else "Whole-project gold is permitted by the current receipt set."
            if gold_claim_allowed
            else "EA release control or required supporting receipts are blocked."
        ),
        "rules": [
            "EA flagship readiness does not imply whole Chummer project readiness.",
            "Unknown external planes block whole-project gold claims.",
            "Draft/operator LTD lanes cannot be treated as runtime or publication truth.",
            "Design mirror parity is bounded; canonical product/UI proof must come from owning repos.",
            "Memorial voice/realtime readiness requires its own browser, STT, TTS, and latency receipts.",
        ],
        "blocking_planes": blocking_planes,
        "planes": planes,
        "ltd_provider_lane_summary": ltd_summary,
        "required_next_receipts": [
            "chummer_core_rules_parity.generated.json",
            "chummer_desktop_ui_visual_accessibility.generated.json",
            "chummer_hub_public_web_smoke.generated.json",
            "mobile_second_device_continuation.generated.json",
            "media_factory_publication_approval.generated.json",
            "memorial_voice_roundtrip_exit_gate.generated.json",
        ],
    }


VOLATILE_KEYS = {"generated_at", "git_head"}


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
