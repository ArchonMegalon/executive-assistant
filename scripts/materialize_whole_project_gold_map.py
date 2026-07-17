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
EA_PATH = ROOT / "ea"
for candidate in (ROOT, EA_PATH):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))


DEFAULT_OUTPUT = ROOT / ".codex-design/product/WHOLE_PROJECT_GOLD_MAP.generated.json"
DEFAULT_FLAGSHIP_RECEIPT = ROOT / ".codex-design/product/EA_FLAGSHIP_RELEASE_GATE.generated.json"
DEFAULT_WEEKLY_PULSE = ROOT / ".codex-design/product/WEEKLY_PRODUCT_PULSE.generated.json"
DEFAULT_BROWSER_PROOF = ROOT / ".codex-studio/published/EA_BROWSER_WORKFLOW_PROOF.generated.json"
DEFAULT_MIRROR_BOUNDARY = ROOT / ".codex-design/repo/MIRROR_SCOPE_BOUNDARY.md"
CHUMMER_COMPLETION_ROOT = Path(os.environ.get("EA_CHUMMER_CROSS_REPO_COMPLETION_ROOT") or ROOT / "ea" / "_completion" / "chummer_cross_repo")
FLEET_COMPLETION_ROOT = Path(os.environ.get("EA_FLEET_COMPLETION_ROOT") or ROOT / "ea" / "_completion" / "fleet")
DEFAULT_FLEET_JOURNEY_GATES = FLEET_COMPLETION_ROOT / "JOURNEY_GATES.generated.json"
DEFAULT_MEMORIAL_VOICE_ROUNDTRIP_RECEIPT = ROOT / ".codex-studio/published/memorial_voice_roundtrip_exit_gate.generated.json"
DEFAULT_MEMORIAL_PUBLIC_VOICE_RECEIPT = ROOT / ".codex-studio/published/memorial_voice_roundtrip_public_origin.generated.json"
DEFAULT_MEMORIAL_PUBLIC_BROWSER_RECEIPT = ROOT / ".codex-studio/published/memorial_realtime_browser_public_origin.generated.json"
DEFAULT_MEMORIAL_PUBLIC_ROOM_RECEIPT = ROOT / ".codex-studio/published/memorial_room_audio_public_origin.generated.json"
DEFAULT_MEMORIAL_SPATIAL_PUBLIC_ORIGIN_RECEIPT = ROOT / ".codex-studio/published/memorial_spatial_tour_public_origin.generated.json"
DEFAULT_MEMORIAL_OPERATOR_STATUS = ROOT / ".codex-design/product/MEMORIAL_OPERATOR_STATUS.generated.json"
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
    return resolve_source_state_head(path)


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
    from app.services.ltd_provider_governance import build_ltd_provider_governance_receipt  # noqa: E402

    receipt = build_ltd_provider_governance_receipt()
    lanes = list(receipt.get("lanes") or [])
    runtime = [lane for lane in lanes if bool(lane.get("runtime_enabled"))]
    draft = [lane for lane in lanes if not bool(lane.get("runtime_enabled"))]
    lanes_with_missing = [
        lane
        for lane in lanes
        if [str(item).strip() for item in list(lane.get("missing_checks") or []) if str(item).strip()]
    ]
    excluded_draft = [
        lane
        for lane in draft
        if not [str(item).strip() for item in list(lane.get("missing_checks") or []) if str(item).strip()]
    ]
    poppy = next((lane for lane in lanes if lane.get("lane_key") == "poppy_draft_workbench"), {})
    missing_lane_checks: list[str] = []
    for lane in lanes:
        lane_key = str(lane.get("lane_key") or "").strip()
        for check in list(lane.get("missing_checks") or []):
            check_key = str(check or "").strip()
            if lane_key and check_key:
                missing_lane_checks.append(f"{lane_key}:{check_key}")
    return {
        "contract_name": receipt.get("contract_name"),
        "status": receipt.get("status"),
        "lane_count": receipt.get("lane_count"),
        "runtime_lane_count": len(runtime),
        "draft_or_operator_lane_count": len(draft),
        "poppy_runtime_enabled": bool(poppy.get("runtime_enabled")) if poppy else None,
        "poppy_lane_state": poppy.get("lane_state") if poppy else None,
        "draft_or_operator_lanes": [str(lane.get("lane_key")) for lane in draft],
        "whole_project_pending_lanes": [str(lane.get("lane_key")) for lane in lanes_with_missing],
        "whole_project_excluded_lanes": [str(lane.get("lane_key")) for lane in excluded_draft],
        "missing_lane_checks": missing_lane_checks,
        "provider_contracts": receipt.get("provider_contracts") if isinstance(receipt.get("provider_contracts"), dict) else {},
        "contract_backed_check_count": receipt.get("contract_backed_check_count"),
    }


def _ltd_provider_missing_evidence(summary: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for item in list(summary.get("missing_lane_checks") or []):
        normalized = str(item or "").strip()
        if normalized:
            missing.append(f"LTD provider lane check pending: {normalized}")
    return list(dict.fromkeys(missing))


DESIGN_SURFACE_MISSING_EVIDENCE = [
    "canonical Chummer product/UI design review receipt from the owning design repo",
    "public/human-facing Chummer documentation humanization review receipt",
    "desktop/public surface visual polish acceptance receipt from the owning UI repo",
]

MEDIA_FACTORY_MISSING_EVIDENCE = [
    "asset-specific media factory publication receipt for each promoted video/horizon asset",
    "provider candidate promotion receipt before MagicFit, JoggAI, Poppy, or avatar lanes can count as publication proof",
    "human publication approval receipt for generated media leaving the operator lab",
]


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


def _telegram_video_delivery_status(operator_path: Path, live_path: Path) -> tuple[str, list[str], list[str]]:
    operator_payload = _json(operator_path)
    live_payload = _json(live_path)
    evidence: list[str] = []
    missing: list[str] = []
    if operator_payload:
        evidence.append(_display_path(operator_path))
    else:
        return "unknown_missing_receipt", [], [_display_path(operator_path)]
    if live_payload:
        evidence.append(_display_path(live_path))

    operator_status = str(operator_payload.get("status") or "").strip().lower()
    live_status = str(live_payload.get("status") or "").strip().lower()
    operator_blocking = [str(item) for item in list(operator_payload.get("blocking_checks") or []) if str(item).strip()]
    operator_policy_ok = operator_status in {"pass", "bounded_pass"} and not operator_blocking

    if not operator_policy_ok:
        missing.append(f"{_display_path(operator_path)} status={operator_status or 'missing'}")
        missing.extend(operator_blocking)
        return "blocked", evidence, missing

    if live_status == "pass":
        return "pass", evidence, []

    if not live_payload:
        missing.append("live Telegram video delivery receipt with operator message ID and delivery observation")
        missing.append(_display_path(live_path))
    else:
        reason = str(live_payload.get("blocking_reason") or "").strip()
        missing.append(f"{_display_path(live_path)} status={live_status or 'missing'}" + (f": {reason}" if reason else ""))
        missing.extend(str(item) for item in list(live_payload.get("failed_codes") or []) if str(item).strip())
    return "bounded_pass", evidence, list(dict.fromkeys(missing))


def _room_receipt_status(path: Path) -> str:
    payload = _json(path)
    status = str(payload.get("status") or "").strip().lower()
    if status not in {"pass", "passed"}:
        return "unknown_missing_receipt"
    attestation = dict(payload.get("manual_attestation") or {})
    if (
        str(payload.get("proof_type") or "").strip() != "manual_room_attestation"
        or not str(attestation.get("attestation_id") or "").strip()
        or not str(attestation.get("signed_at") or "").strip()
        or attestation.get("ci_must_not_auto_assert") is not True
    ):
        return "blocked"
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
    checks = dict(payload.get("checks") or {})
    if any(checks.get(key) is not True for key in required_checks):
        return "blocked"
    return "pass"


def _weekly_pulse_blockers(path: Path) -> list[str]:
    payload = _json(path)
    if not payload:
        return [f"{_display_path(path)} missing_or_invalid"]
    blockers: list[str] = []
    release_health = payload.get("release_health")
    if isinstance(release_health, dict):
        state = str(release_health.get("state") or "").strip().lower()
        if state not in {"ready", "clear", "pass"}:
            reason = str(release_health.get("reason") or "").strip()
            blockers.append(f"weekly release_health={state or 'missing'}" + (f": {reason}" if reason else ""))
    flagship_readiness = payload.get("flagship_readiness")
    if isinstance(flagship_readiness, dict):
        state = str(flagship_readiness.get("state") or "").strip().lower()
        if state not in {"ready", "clear", "pass"}:
            reason = str(flagship_readiness.get("reason") or "").strip()
            blockers.append(f"weekly flagship_readiness={state or 'missing'}" + (f": {reason}" if reason else ""))
    supporting = payload.get("supporting_signals")
    if isinstance(supporting, dict):
        launch_readiness = str(supporting.get("launch_readiness") or "").strip()
        if launch_readiness.lower().startswith("hold") or "freeze" in launch_readiness.lower():
            blockers.append(f"weekly launch_readiness: {launch_readiness}")
    return list(dict.fromkeys(blockers))


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
    memorial_spatial_public_origin_receipt: Path = DEFAULT_MEMORIAL_SPATIAL_PUBLIC_ORIGIN_RECEIPT,
    memorial_operator_status_path: Path = DEFAULT_MEMORIAL_OPERATOR_STATUS,
    telegram_video_delivery_receipt: Path = DEFAULT_TELEGRAM_VIDEO_DELIVERY_RECEIPT,
    telegram_video_delivery_live_receipt: Path = DEFAULT_TELEGRAM_VIDEO_DELIVERY_LIVE_RECEIPT,
    generated_at: str | None = None,
) -> dict[str, Any]:
    source_git_head = _git_head()
    source_fingerprint = resolve_source_worktree_fingerprint(ROOT)
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
    media_status_raw, media_evidence, media_missing = _receipt_group_status(media_receipts)
    media_status = "bounded_pass" if media_status_raw == "pass" else media_status_raw
    telegram_video_status, telegram_video_evidence, telegram_video_missing = _telegram_video_delivery_status(
        telegram_video_delivery_receipt,
        telegram_video_delivery_live_receipt,
    )
    memorial_voice_status_raw = _status_from_receipt(memorial_voice_roundtrip_receipt, {"pass"})
    memorial_voice_status = "pass" if memorial_voice_status_raw == "pass" else "separate_risk_zone"
    memorial_voice_evidence = [_display_path(memorial_voice_roundtrip_receipt)] if memorial_voice_roundtrip_receipt.is_file() else []
    memorial_public_voice_status = _status_from_receipt(memorial_public_voice_receipt, {"pass"})
    memorial_public_browser_status = _status_from_receipt(memorial_public_browser_receipt, {"pass"})
    memorial_public_room_status = _room_receipt_status(memorial_public_room_receipt)
    memorial_spatial_payload = _json(memorial_spatial_public_origin_receipt)
    memorial_spatial_issues = validate_memorial_spatial_public_origin_receipt(
        memorial_spatial_payload,
        current_head=source_git_head,
        current_fingerprint=source_fingerprint,
    )
    memorial_spatial_status = "pass" if not memorial_spatial_issues else "blocked"
    memorial_operator_status = _json(memorial_operator_status_path)
    memorial_public_runtime_status = str(memorial_operator_status.get("public_runtime_mode") or "").strip().lower()
    memorial_public_runtime_reason = str(
        dict(memorial_operator_status.get("public_runtime_mode_detail") or {}).get("reason") or ""
    ).strip()
    memorial_public_runtime_next_action = str(
        dict(memorial_operator_status.get("public_runtime_mode_detail") or {}).get("next_action") or ""
    ).strip()
    memorial_public_access_status = str(memorial_operator_status.get("public_origin_access") or "").strip().lower()
    memorial_public_access_reason = str(
        dict(memorial_operator_status.get("public_origin_access_detail") or {}).get("reason") or ""
    ).strip()
    memorial_public_access_next_action = str(
        dict(memorial_operator_status.get("public_origin_access_detail") or {}).get("next_action") or ""
    ).strip()
    memorial_public_gold_status = (
        "pass"
        if memorial_public_voice_status == "pass"
        and memorial_public_browser_status == "pass"
        and memorial_public_room_status == "pass"
        and memorial_spatial_status == "pass"
        and memorial_public_access_status not in {"access_blocked", "blocked", "missing"}
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
        memorial_public_missing.append("public-origin room/device audio intelligibility receipt with manual attestation")
    if memorial_spatial_status != "pass":
        memorial_public_missing.append(
            "public-origin polished 3D-tour receipt with pinned PropertyQuarry authority, v5 browser interactions, deploy binding, and exact public bytes"
        )
        memorial_public_missing.extend(
            f"public spatial-tour receipt: {issue}" for issue in memorial_spatial_issues
        )
    if memorial_public_runtime_status in {"blocked", "missing"}:
        if memorial_public_runtime_reason == "public_origin_not_deployed_in_memorial_mode":
            memorial_public_missing.append("public origin is still deployed in EA_CORE mode instead of MEMORIAL mode")
        else:
            memorial_public_missing.append("public memorial runtime mode is not proven for the configured public origin")
    suppress_access_symptom = (
        memorial_public_runtime_status == "blocked"
        and memorial_public_runtime_reason == "public_origin_not_deployed_in_memorial_mode"
    )
    if memorial_public_access_status in {"access_blocked", "blocked"} and not suppress_access_symptom:
        if memorial_public_access_reason == "public_origin_memorial_not_found":
            memorial_public_missing.append("public memorial page or manifest not found at configured public origin")
        else:
            memorial_public_missing.append(
                f"public memorial origin access blocked at configured edge ({memorial_public_access_status})"
            )
    elif memorial_public_access_status == "missing":
        memorial_public_missing.append("public memorial origin access status from memorial operator snapshot")
    memorial_public_design_notes = (
        [
            "Use: Memorial public-origin gold: pass.",
            "Do not collapse this memorial-specific proof into generic whole-project authority.",
        ]
        if memorial_public_gold_status == "pass"
        else [
            "Guest-facing copy must never say simply gold while this plane is blocked.",
            "Use: Memorial public-origin gold: blocked.",
            *( [f"public_runtime_mode={memorial_public_runtime_status}"] if memorial_public_runtime_status else [] ),
            *( [f"public_runtime_reason={memorial_public_runtime_reason}"] if memorial_public_runtime_reason else [] ),
            *( [f"public_runtime_next_action={memorial_public_runtime_next_action}"] if memorial_public_runtime_next_action else [] ),
            *( [f"public_origin_access={memorial_public_access_status}"] if memorial_public_access_status and not suppress_access_symptom else [] ),
            *( [f"public_origin_access_reason={memorial_public_access_reason}"] if memorial_public_access_reason and not suppress_access_symptom else [] ),
            *( [f"public_origin_access_next_action={memorial_public_access_next_action}"] if memorial_public_access_next_action and not suppress_access_symptom else [] ),
        ]
    )
    ltd_summary = _load_ltd_summary()
    ltd_missing = _ltd_provider_missing_evidence(ltd_summary)
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
            missing_evidence=[] if ea_status == "pass" else ea_missing or ["EA flagship receipt, weekly pulse, or browser proof is not pass"],
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
            missing_evidence=DESIGN_SURFACE_MISSING_EVIDENCE
            if mirror_boundary_present
            else [_display_path(mirror_boundary_path), *DESIGN_SURFACE_MISSING_EVIDENCE],
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
            missing_evidence=media_missing + MEDIA_FACTORY_MISSING_EVIDENCE,
            design_notes=[
                "This is a bounded publication pass for current Black Ledger live media, not a blanket promotion of MagicFit, JoggAI, Poppy, or avatar candidate lanes.",
            ],
        ),
        _plane(
            key="telegram_video_delivery",
            title="Telegram Video Delivery",
            owner_repo="EA",
            status=telegram_video_status,
            claim="Telegram video replies are accepted only when source-video download safety, governed render lanes, durable delivery receipts, and live operator message-ID proof are present.",
            evidence=telegram_video_evidence,
            missing_evidence=telegram_video_missing,
            design_notes=[
                "Local source-video edits can be a bounded operator lane.",
                "MagicFit remains disabled unless the runtime lane is explicitly approved and the Docker image is digest pinned.",
                "Generated bounded proof is not the same as a live Telegram delivery receipt.",
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
            claim="The public memorial experience is gold only when the deployed public origin proves voice, realtime playback, room/device intelligibility, latency, and the polished generated 3D tour through exact-byte public-origin and browser-interaction evidence. Local or candidate-only receipts do not satisfy this plane.",
            evidence=[
                _display_path(path)
                for path in (
                    memorial_public_voice_receipt,
                    memorial_public_browser_receipt,
                    memorial_public_room_receipt,
                    memorial_spatial_public_origin_receipt,
                    memorial_operator_status_path,
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
            missing_evidence=ltd_missing,
            design_notes=[
                f"lane_count={ltd_summary.get('lane_count')}",
                f"runtime_lane_count={ltd_summary.get('runtime_lane_count')}",
                f"draft_or_operator_lane_count={ltd_summary.get('draft_or_operator_lane_count')}",
                f"provider_contract_status={dict(ltd_summary.get('provider_contracts') or {}).get('status')}",
                f"provider_contract_proof_scope={dict(ltd_summary.get('provider_contracts') or {}).get('proof_scope')}",
                f"provider_contract_live_verified={dict(ltd_summary.get('provider_contracts') or {}).get('live_provider_runtime_verified')}",
                f"contract_backed_check_count={ltd_summary.get('contract_backed_check_count')}",
                f"whole_project_pending_lane_count={len(ltd_summary.get('whole_project_pending_lanes') or [])}",
                f"whole_project_excluded_lane_count={len(ltd_summary.get('whole_project_excluded_lanes') or [])}",
                f"missing_lane_check_count={len(ltd_summary.get('missing_lane_checks') or [])}",
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
    required_next_receipts: list[str] = []
    if not gold_claim_allowed:
        for plane in planes:
            if str(plane.get("status") or "").strip().lower() not in BLOCKING_STATUSES:
                continue
            missing = [str(item) for item in list(plane.get("missing_evidence") or []) if str(item).strip()]
            if missing:
                required_next_receipts.extend(missing)
            else:
                required_next_receipts.append(f"{plane['key']} requires an owning-plane pass receipt")
        if memorial_public_runtime_status in {"blocked", "missing"} and memorial_public_runtime_next_action:
            required_next_receipts.insert(
                0,
                "memorial public-origin deploy next action: " + memorial_public_runtime_next_action,
            )
        elif memorial_public_access_status in {"access_blocked", "blocked"} and memorial_public_access_next_action and not suppress_access_symptom:
            required_next_receipts.insert(
                0,
                "memorial public-origin access next action: " + memorial_public_access_next_action,
            )
        required_next_receipts = list(dict.fromkeys(required_next_receipts))

    return {
        "contract_name": "ea.whole_project_gold_map",
        "generated_at": generated_at or _utc_now(),
        "generated_by": "scripts/materialize_whole_project_gold_map.py",
        "source_git_head": source_git_head,
        "head_semantics": "source_state",
        "head_semantics_note": "source_git_head records the proved source state. Generated-only artifact commits may advance repository HEAD without changing the source state that the receipts prove.",
        "output_path": _display_path(output_path),
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
            "Telegram video delivery requires a dedicated live delivery receipt before it can support whole-project gold.",
            "Design mirror parity is bounded; canonical product/UI proof must come from owning repos.",
            "Memorial voice/realtime readiness requires its own browser, STT, TTS, and latency receipts.",
            "Memorial public-origin gold requires the public voice roundtrip receipt, public browser realtime receipt, public room-audio receipt, and strict public spatial-tour receipt.",
            "The spatial-tour receipt must bind the pinned PropertyQuarry authority and package to polished v5 candidate-browser proof, the governed deploy receipt, and all exact public-origin GET/HEAD observations; status-only or candidate-only evidence is insufficient.",
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

    output_path = args.output if args.output.is_absolute() else ROOT / args.output
    receipt = build_gold_map(output_path=output_path, fleet_journey_gates_path=args.fleet_journey_gates)
    write_json_stable(output_path, receipt)
    print(json.dumps({"status": "pass", "output": output_path.as_posix(), "overall_status": receipt["overall_status"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
