#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    from scripts.source_state_head import resolve_source_state_head
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from source_state_head import resolve_source_state_head


ROOT = Path(__file__).resolve().parents[1]
EA_PATH = ROOT / "ea"
for candidate in (ROOT, EA_PATH):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

DEFAULT_OUTPUT = ROOT / ".codex-design/product/WHOLE_PROJECT_GOLD_MAP.generated.json"
DEFAULT_FLAGSHIP_RECEIPT = ROOT / ".codex-design/product/EA_FLAGSHIP_RELEASE_GATE.generated.json"
DEFAULT_WEEKLY_PULSE = ROOT / ".codex-design/product/WEEKLY_PRODUCT_PULSE.generated.json"
DEFAULT_BROWSER_PROOF = ROOT / ".codex-studio/published/EA_BROWSER_WORKFLOW_PROOF.generated.json"
DEFAULT_MIRROR_BOUNDARY = ROOT / ".codex-design/repo/MIRROR_SCOPE_BOUNDARY.md"
CHUMMER_COMPLETION_ROOT = Path(
    os.environ.get("EA_CHUMMER_CROSS_REPO_COMPLETION_ROOT")
    or ROOT / "ea" / "_completion" / "chummer_cross_repo"
)
FLEET_COMPLETION_ROOT = Path(
    os.environ.get("EA_FLEET_COMPLETION_ROOT") or ROOT / "ea" / "_completion" / "fleet"
)
DEFAULT_FLEET_JOURNEY_GATES = FLEET_COMPLETION_ROOT / "JOURNEY_GATES.generated.json"
DEFAULT_TELEGRAM_VIDEO_DELIVERY_RECEIPT = ROOT / ".codex-studio/published/telegram_video_delivery_operator.generated.json"
DEFAULT_TELEGRAM_VIDEO_DELIVERY_LIVE_RECEIPT = ROOT / ".codex-studio/published/telegram_video_delivery_live.generated.json"
DEFAULT_CORE_RULE_RECEIPTS = (
    CHUMMER_COMPLETION_ROOT / "chummer-core-engine" / "OPERATOR_PROMOTED_RULE_AUTHORITY_GOLD.generated.json",
    CHUMMER_COMPLETION_ROOT / "chummer-core-engine" / "FULL_PRODUCT_RULE_AUTHORITY_COMPLETION.generated.json",
)
DEFAULT_DESKTOP_UI_RECEIPTS = (
    CHUMMER_COMPLETION_ROOT / "chummer-presentation" / "DESKTOP_EXECUTABLE_EXIT_GATE.generated.json",
    CHUMMER_COMPLETION_ROOT / "chummer-presentation" / "DESKTOP_VISUAL_FAMILIARITY_EXIT_GATE.generated.json",
    CHUMMER_COMPLETION_ROOT / "chummer-presentation" / "CHUMMER5A_LAYOUT_HARD_GATE.generated.json",
)
DEFAULT_HUB_PUBLIC_WEB_RECEIPTS = (
    CHUMMER_COMPLETION_ROOT / "chummer.run-services" / "FLAGSHIP_PRODUCT_READINESS.generated.json",
    CHUMMER_COMPLETION_ROOT / "chummer.run-services" / "PUBLIC_ORIGIN_REACHABILITY_GATE.generated.json",
    CHUMMER_COMPLETION_ROOT / "chummer.run-services" / "PUBLIC_SHELL_CLICKABILITY_GATE.generated.json",
)
DEFAULT_MOBILE_RECEIPTS = (
    CHUMMER_COMPLETION_ROOT / "chummer-play" / "MOBILE_LOCAL_RELEASE_PROOF.generated.json",
)
DEFAULT_MEDIA_RECEIPTS = (
    CHUMMER_COMPLETION_ROOT / "chummer.run-services" / "BLACK_LEDGER_LIVE_MEDIA_PROOF.generated.json",
)

BLOCKING_STATUSES = {
    "unknown_missing_receipt",
    "blocked",
    "fail",
    "bounded_pass",
    "mixed",
    "draft_operator",
    "candidate_only",
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
    return resolve_source_state_head(path)


def _display_path(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


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
    status = str(payload.get("status") or payload.get("overall_status") or "").strip().lower()
    release_health = payload.get("release_health")
    flagship_readiness = payload.get("flagship_readiness")
    if not status and isinstance(release_health, dict) and isinstance(flagship_readiness, dict):
        if {
            str(release_health.get("state") or "").strip().lower(),
            str(flagship_readiness.get("state") or "").strip().lower(),
        } <= allowed:
            status = "pass"
    return "pass" if status in allowed else "unknown_missing_receipt"


def _weekly_pulse_blockers(path: Path) -> list[str]:
    payload = _json(path)
    if not payload:
        return [f"{_display_path(path)} missing_or_invalid"]
    blockers: list[str] = []
    for key in ("release_health", "flagship_readiness"):
        row = payload.get(key)
        if not isinstance(row, dict):
            blockers.append(f"weekly {key}=missing")
            continue
        state = str(row.get("state") or "").strip().lower()
        if state not in {"ready", "clear", "pass"}:
            reason = str(row.get("reason") or "").strip()
            blockers.append(f"weekly {key}={state or 'missing'}" + (f": {reason}" if reason else ""))
    return blockers


def _receipt_group_status(
    paths: tuple[Path, ...], *, allowed: set[str] = {"pass", "passed"}
) -> tuple[str, list[str], list[str]]:
    evidence: list[str] = []
    missing: list[str] = []
    for path in paths:
        payload = _json(path)
        status = str(payload.get("status") or payload.get("overall_status") or payload.get("verdict") or "").strip().lower()
        if payload and status in allowed:
            evidence.append(_display_path(path))
        else:
            missing.append(f"{_display_path(path)} status={status or 'missing'}")
    return ("pass" if not missing else "unknown_missing_receipt", evidence, missing)


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


def _telegram_video_delivery_status(
    operator_path: Path, live_path: Path
) -> tuple[str, list[str], list[str]]:
    operator = _json(operator_path)
    live = _json(live_path)
    if not operator:
        return "unknown_missing_receipt", [], [_display_path(operator_path)]
    evidence = [_display_path(operator_path)]
    if live:
        evidence.append(_display_path(live_path))
    operator_status = str(operator.get("status") or "").strip().lower()
    blocking = [str(item) for item in list(operator.get("blocking_checks") or []) if str(item).strip()]
    if operator_status not in {"pass", "bounded_pass"} or blocking:
        return "blocked", evidence, [f"{_display_path(operator_path)} status={operator_status or 'missing'}", *blocking]
    if str(live.get("status") or "").strip().lower() == "pass":
        return "pass", evidence, []
    return "bounded_pass", evidence, [
        "live Telegram video delivery receipt with operator message ID and delivery observation",
        _display_path(live_path),
    ]


def _load_ltd_summary() -> dict[str, Any]:
    from app.services.ltd_provider_governance import build_ltd_provider_governance_receipt

    receipt = build_ltd_provider_governance_receipt()
    lanes = list(receipt.get("lanes") or [])
    runtime = [lane for lane in lanes if bool(lane.get("runtime_enabled"))]
    draft = [lane for lane in lanes if not bool(lane.get("runtime_enabled"))]
    missing_lane_checks: list[str] = []
    for lane in lanes:
        lane_key = str(lane.get("lane_key") or "").strip()
        for check in list(lane.get("missing_checks") or []):
            if lane_key and str(check).strip():
                missing_lane_checks.append(f"{lane_key}:{str(check).strip()}")
    poppy = next((lane for lane in lanes if lane.get("lane_key") == "poppy_draft_workbench"), {})
    return {
        "contract_name": receipt.get("contract_name"),
        "status": receipt.get("status"),
        "lane_count": receipt.get("lane_count"),
        "runtime_lane_count": len(runtime),
        "draft_or_operator_lane_count": len(draft),
        "poppy_runtime_enabled": bool(poppy.get("runtime_enabled")) if poppy else None,
        "poppy_lane_state": poppy.get("lane_state") if poppy else None,
        "missing_lane_checks": missing_lane_checks,
        "provider_contracts": receipt.get("provider_contracts") if isinstance(receipt.get("provider_contracts"), dict) else {},
        "contract_backed_check_count": receipt.get("contract_backed_check_count"),
    }


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
    telegram_video_delivery_receipt: Path = DEFAULT_TELEGRAM_VIDEO_DELIVERY_RECEIPT,
    telegram_video_delivery_live_receipt: Path = DEFAULT_TELEGRAM_VIDEO_DELIVERY_LIVE_RECEIPT,
    generated_at: str | None = None,
) -> dict[str, Any]:
    source_git_head = _git_head()
    flagship_status = _status_from_receipt(flagship_receipt_path, {"pass"})
    weekly_status = _status_from_receipt(weekly_pulse_path, {"ready", "clear", "pass"})
    browser_status = _status_from_receipt(browser_proof_path, {"pass"})
    ea_status = "pass" if {flagship_status, weekly_status, browser_status} == {"pass"} else "blocked"
    ea_missing: list[str] = []
    if flagship_status != "pass":
        ea_missing.append(f"{_display_path(flagship_receipt_path)} is not pass")
    if weekly_status != "pass":
        ea_missing.extend(_weekly_pulse_blockers(weekly_pulse_path))
    if browser_status != "pass":
        ea_missing.append(f"{_display_path(browser_proof_path)} is not pass")

    fleet_status, fleet_evidence, fleet_missing = _fleet_status(fleet_journey_gates_path)
    core_status, core_evidence, core_missing = _receipt_group_status(core_rule_receipts)
    desktop_status, desktop_evidence, desktop_missing = _receipt_group_status(desktop_ui_receipts)
    hub_status, hub_evidence, hub_missing = _receipt_group_status(hub_public_web_receipts)
    mobile_status, mobile_evidence, mobile_missing = _receipt_group_status(mobile_receipts)
    media_raw, media_evidence, media_missing = _receipt_group_status(media_receipts)
    media_status = "bounded_pass" if media_raw == "pass" else media_raw
    telegram_status, telegram_evidence, telegram_missing = _telegram_video_delivery_status(
        telegram_video_delivery_receipt, telegram_video_delivery_live_receipt
    )
    ltd_summary = _load_ltd_summary()
    ltd_missing = [
        f"LTD provider lane check pending: {item}"
        for item in list(ltd_summary.get("missing_lane_checks") or [])
    ]

    planes = [
        _plane(
            key="ea_release_control",
            title="Executive Assistant Release Control",
            owner_repo="EA",
            status=ea_status,
            claim="EA core is green only when its release, weekly pulse, and browser workflow receipts pass.",
            evidence=[_display_path(flagship_receipt_path), _display_path(weekly_pulse_path), _display_path(browser_proof_path)],
            missing_evidence=ea_missing,
        ),
        _plane(key="fleet_journey_gates", title="Fleet Journey Gates", owner_repo="fleet", status=fleet_status, claim="EA consumes Fleet's generated journey summary without owning it.", evidence=fleet_evidence, missing_evidence=fleet_missing),
        _plane(
            key="design_surface",
            title="Design Surface And Mirror Boundary",
            owner_repo="design-front-door / EA mirror",
            status="bounded_pass" if mirror_boundary_path.exists() else "unknown_missing_receipt",
            claim="EA owns a bounded mirror and cannot infer product-wide design readiness from it.",
            evidence=[_display_path(mirror_boundary_path)] if mirror_boundary_path.exists() else [],
            missing_evidence=["canonical Chummer product/UI design review receipt from the owning design repo", "public-facing Chummer documentation humanization review receipt"],
        ),
        _plane(key="chummer_core_rules", title="Chummer Core Rules And Data Correctness", owner_repo="chummer6-core", status=core_status, claim="Core rules require owning-repository authority receipts.", evidence=core_evidence, missing_evidence=core_missing),
        _plane(key="chummer_desktop_ui", title="Chummer Desktop/UI Product Surface", owner_repo="chummer6-ui", status=desktop_status, claim="Desktop readiness requires executable and visual acceptance receipts.", evidence=desktop_evidence, missing_evidence=desktop_missing),
        _plane(key="chummer_hub_public_web", title="Chummer Hub And Public Web", owner_repo="chummer6-hub", status=hub_status, claim="Public-web readiness requires owning-repository reachability and clickability receipts.", evidence=hub_evidence, missing_evidence=hub_missing),
        _plane(key="mobile_and_second_device", title="Mobile And Second-Device Continuation", owner_repo="mobile / hub", status=mobile_status, claim="Mobile readiness requires the owning mobile release proof.", evidence=mobile_evidence, missing_evidence=mobile_missing),
        _plane(
            key="media_factory_publication",
            title="Media Factory And Video Publication",
            owner_repo="EA / Chummer media factory",
            status=media_status,
            claim="Published media requires asset-specific publication and human approval receipts.",
            evidence=media_evidence,
            missing_evidence=[*media_missing, "asset-specific media factory publication receipt", "human publication approval receipt"],
        ),
        _plane(key="telegram_video_delivery", title="Telegram Video Delivery", owner_repo="EA", status=telegram_status, claim="Telegram video delivery requires durable and live message-ID proof.", evidence=telegram_evidence, missing_evidence=telegram_missing),
        _plane(
            key="ltd_provider_lanes",
            title="LTD Provider Lanes",
            owner_repo="EA",
            status="mixed",
            claim="Provider lanes are runtime, operator-draft, or parked inventory; they are not product truth.",
            evidence=["scripts/verify_ltd_provider_lanes.py"],
            missing_evidence=ltd_missing,
            design_notes=[f"provider_contract_status={dict(ltd_summary.get('provider_contracts') or {}).get('status')}", f"contract_backed_check_count={ltd_summary.get('contract_backed_check_count')}"],
        ),
    ]

    blocking_planes = [
        str(plane["key"])
        for plane in planes
        if str(plane.get("status") or "").strip().lower() in BLOCKING_STATUSES
    ]
    gold_claim_allowed = not blocking_planes and ea_status == "pass"
    required_next_receipts: list[str] = []
    for plane in planes:
        if str(plane.get("key")) not in blocking_planes:
            continue
        missing = [str(item) for item in list(plane.get("missing_evidence") or []) if str(item).strip()]
        required_next_receipts.extend(missing or [f"{plane['key']} requires an owning-plane pass receipt"])

    return {
        "contract_name": "ea.whole_project_gold_map",
        "generated_at": generated_at or _utc_now(),
        "generated_by": "scripts/materialize_whole_project_gold_map.py",
        "source_git_head": source_git_head,
        "head_semantics": "source_state",
        "output_path": _display_path(output_path),
        "overall_status": "gold" if gold_claim_allowed else "not_gold",
        "gold_claim_allowed": gold_claim_allowed,
        "claim_scope": "whole_project_plane_set",
        "claim_scope_label": "Whole-project gold is allowed only when every listed EA and Chummer plane is proven by its owning repository.",
        "rules": [
            "EA flagship readiness does not imply whole Chummer project readiness.",
            "Unknown external planes block whole-project gold claims.",
            "Whole-project gold requires every listed plane to pass.",
            "Telegram video delivery requires a dedicated live delivery receipt.",
            "A product removed from EA must be released and verified in its owning repository.",
        ],
        "blocking_planes": blocking_planes,
        "planes": planes,
        "ltd_provider_lane_summary": ltd_summary,
        "required_next_receipts": list(dict.fromkeys(required_next_receipts)),
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
    parser = argparse.ArgumentParser(description="Materialize the conservative whole-project gold map.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--fleet-journey-gates", type=Path, default=DEFAULT_FLEET_JOURNEY_GATES)
    args = parser.parse_args()
    output_path = args.output if args.output.is_absolute() else ROOT / args.output
    receipt = build_gold_map(output_path=output_path, fleet_journey_gates_path=args.fleet_journey_gates)
    write_json_stable(output_path, receipt)
    print(json.dumps({"status": "pass", "output": output_path.as_posix(), "overall_status": receipt["overall_status"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
