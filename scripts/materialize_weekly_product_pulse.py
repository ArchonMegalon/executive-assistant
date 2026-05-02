#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml


DEFAULT_OUTPUT = Path(".codex-design/product/WEEKLY_PRODUCT_PULSE.generated.json")
DEFAULT_SCORECARD = Path(".codex-design/product/PRODUCT_HEALTH_SCORECARD.yaml")
DEFAULT_JOURNEY_GATES = Path("/docker/fleet/.codex-studio/published/JOURNEY_GATES.generated.json")
DEFAULT_FLAGSHIP_RECEIPT = Path(".codex-design/product/EA_FLAGSHIP_RELEASE_GATE.generated.json")
DEFAULT_GOVERNOR_LOOP = Path(".codex-design/product/PRODUCT_GOVERNOR_AND_AUTOPILOT_LOOP.md")
DEFAULT_CONTROL_LOOP = Path(".codex-design/product/PRODUCT_CONTROL_AND_GOVERNOR_LOOP.md")
DEFAULT_RELEASE_PIPELINE = Path(".codex-design/product/RELEASE_PIPELINE.md")
DEFAULT_RELEASE_CHECKLIST = Path("RELEASE_CHECKLIST.md")
DEFAULT_ROOT = Path(__file__).resolve().parents[1]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _format_utc(value: datetime) -> str:
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload or {}) if isinstance(payload, dict) else {}


def _compact(value: object, *, fallback: str = "", limit: int = 220) -> str:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        text = fallback
    if len(text) > limit:
        return text[: max(limit - 1, 0)].rstrip() + "…"
    return text


def _resolve_for_read(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _journey_gate_source(root: Path, journey_path: Path) -> dict[str, Any]:
    resolved = _resolve_for_read(root, journey_path)
    journey = _load_json(resolved) or {}
    summary = dict(journey.get("summary") or {})
    journeys = [dict(row) for row in list(journey.get("journeys") or []) if isinstance(row, dict)]
    blocked = int(summary.get("blocked_count") or 0)
    ready = int(summary.get("ready_count") or 0)
    total = int(summary.get("total_journey_count") or len(journeys) or (blocked + ready))
    warning = int(summary.get("warning_count") or 0)
    journey_state = str(summary.get("overall_state") or "missing").strip() or "missing"
    recommended_action = _compact(summary.get("recommended_action") or "", fallback="Journey-gate posture is not available.")
    return {
        "journey": journey,
        "summary": summary,
        "journeys": journeys,
        "path": journey_path,
        "state": journey_state,
        "recommended_action": recommended_action,
        "blocked": blocked,
        "ready": ready,
        "warning": warning,
        "total": total,
        "ready_share": int(round((ready / total) * 100)) if total else 0,
    }


def _flagship_receipt_source(root: Path, receipt_path: Path) -> dict[str, Any]:
    resolved = _resolve_for_read(root, receipt_path)
    receipt = _load_json(resolved) or {}
    status = str(receipt.get("status") or "missing").strip() or "missing"
    truth_plane = dict(receipt.get("truth_plane") or {})
    browser = dict(receipt.get("browser_workflow_proof") or {})
    return {
        "receipt": receipt,
        "path": receipt_path,
        "status": status,
        "truth_plane": truth_plane,
        "browser_present": bool(browser.get("published_receipt_present")),
        "browser_receipt": str(browser.get("published_receipt") or "").strip(),
        "limitations": [str(item) for item in list(receipt.get("current_limitations") or []) if str(item).strip()],
    }


def build_pulse(
    root: Path,
    *,
    scorecard_path: Path = DEFAULT_SCORECARD,
    journey_gates_path: Path = DEFAULT_JOURNEY_GATES,
    flagship_receipt_path: Path = DEFAULT_FLAGSHIP_RECEIPT,
    governor_loop_path: Path = DEFAULT_GOVERNOR_LOOP,
    control_loop_path: Path = DEFAULT_CONTROL_LOOP,
    release_pipeline_path: Path = DEFAULT_RELEASE_PIPELINE,
    release_checklist_path: Path = DEFAULT_RELEASE_CHECKLIST,
) -> dict[str, Any]:
    scorecard = _load_yaml(root / scorecard_path)
    cadence = dict(scorecard.get("cadence") or {})
    journey_info = _journey_gate_source(root, journey_gates_path)
    receipt_info = _flagship_receipt_source(root, flagship_receipt_path)
    now = _utcnow()
    generated_at = _format_utc(now)
    review_due = _format_utc(now + timedelta(days=7))

    scorecard_metrics = list(scorecard.get("scorecards") or [])
    scorecard_metric_count = sum(len(list(dict(row).get("metrics") or [])) for row in scorecard_metrics if isinstance(row, dict))
    release_truth_state = receipt_info["status"]
    journey_state = journey_info["state"]
    blocked_count = int(journey_info["blocked"])
    ready_count = int(journey_info["ready"])
    total_count = int(journey_info["total"])
    readiness_share = int(journey_info["ready_share"])
    release_health_state = "blocked" if journey_state == "blocked" or release_truth_state != "pass" else "clear"

    if release_truth_state == "pass":
        summary = (
            "Executive Assistant has a green flagship receipt, but the fleet journey gate is "
            f"{journey_state}, and {blocked_count} journey(s) still block wider claims."
        )
    elif release_truth_state == "preview_only":
        summary = (
            "Executive Assistant remains in preview-only flagship posture: the machine-readable flagship receipt is "
            f"{release_truth_state}, the fleet journey gate is {journey_state}, and {blocked_count} journey(s) still block wider claims."
        )
    else:
        summary = (
            "Executive Assistant is blocked on flagship release truth: the machine-readable flagship receipt is "
            f"{release_truth_state}, the fleet journey gate is {journey_state}, and {blocked_count} journey(s) still block wider claims."
        )

    launch_readiness = (
        "Hold launch expansion pending browser execution proof and cross-host journey coverage."
        if release_truth_state != "pass" or journey_state == "blocked"
        else "Release truth is clear enough to widen claims."
    )
    provider_route_stewardship = {
        "default_status": "EA routes are governed by local truth surfaces.",
        "canary_status": "Browser execution proof is still missing; cross-host journey coverage remains blocked.",
        "review_due": review_due,
        "next_decision": "Publish browser execution proof, then re-materialize the weekly pulse and release receipt.",
    }

    governor_decisions = [
        {
            "decision_id": "2026-04-10-focus-ea-flagship-receipt-closeout",
            "action": "focus_shift",
            "reason": (
                "Keep the weekly pulse anchored to the EA flagship receipt and fleet journey truth. "
                f"The receipt is {release_truth_state}, journey gates are {journey_state}, and the ready share is {readiness_share}%."
            ),
            "cited_signals": [
                f"flagship_receipt_status={release_truth_state}",
                f"journey_gate_state={journey_state}",
                f"journey_gate_blocked_count={blocked_count}",
                f"journey_gate_ready_count={ready_count}",
                f"journey_gate_total_count={total_count}",
                f"ready_share={readiness_share}",
            ],
        },
        {
            "decision_id": "2026-04-10-freeze-launch-expansion",
            "action": "freeze_launch",
            "reason": (
                "Freeze launch expansion until the blocked journey tuples are cleared."
                if release_truth_state == "pass"
                else "Freeze launch expansion until browser execution proof is published and the blocked journey tuples are cleared."
            ),
            "cited_signals": [
                f"flagship_receipt_status={release_truth_state}",
                f"browser_execution_receipt_present={receipt_info['browser_present']}",
                f"journey_gate_blocked_count={blocked_count}",
                "cross_host_tuple_coverage=blocked",
            ],
        },
    ]

    blocked_reason = journey_info["recommended_action"] or "Resolve the blocking journey gaps before widening publish claims."
    pulse: dict[str, Any] = {
        "contract_name": "ea.weekly_product_pulse",
        "contract_version": 1,
        "generated_at": generated_at,
        "as_of": generated_at[:10],
        "scorecard_source": scorecard_path.as_posix(),
        "release_truth_source": flagship_receipt_path.as_posix(),
        "journey_gate_source": journey_gates_path.as_posix(),
        "summary": summary,
        "active_wave": "EA flagship receipt closeout",
        "active_wave_status": "active",
        "release_health": {
            "state": release_health_state,
            "reason": (
                "The EA flagship receipt is published and current."
                if release_truth_state == "pass"
                else "The EA flagship receipt is materialized, but it is still preview_only until browser execution proof is published."
                if release_truth_state == "preview_only"
                else "The EA flagship receipt is blocked by the current browser workflow proof or release evidence."
            ),
            "flagship_receipt_status": release_truth_state,
        },
        "flagship_readiness": {
            "state": "clear" if release_truth_state == "pass" else "watch" if release_truth_state == "preview_only" else "blocked",
            "reason": (
                "Flagship receipt and browser proof are aligned."
                if release_truth_state == "pass"
                else "Browser execution proof is missing or incomplete, so the flagship receipt cannot yet claim pass status."
                if release_truth_state == "preview_only"
                else "Browser workflow proof is currently blocked, so the flagship receipt cannot support wider release claims."
            ),
        },
        "rule_environment_trust": {
            "state": "watch" if journey_state == "blocked" else "monitor",
            "reason": "Install/update trust still depends on the blocked cross-host journey set."
            if journey_state == "blocked"
            else "Rule-environment trust is governed by the current release receipt.",
        },
        "edition_authorship_and_import_confidence": {
            "state": "monitor",
            "reason": "The weekly pulse now uses EA-local release truth rather than a Chummer mirror.",
        },
        "journey_gate_health": {
            "state": journey_state,
            "reason": _compact(blocked_reason, fallback="Journey-gate posture is not available."),
            "blocked_count": blocked_count,
            "warning_count": int(journey_info["warning"]),
            "recommended_action": _compact(blocked_reason, fallback="Journey-gate posture is not available."),
        },
        "top_support_or_feedback_clusters": [
            {
                "cluster_id": "ea_flagship_receipt_closeout",
                "summary": (
                    "The weekly pulse now anchors to the EA flagship receipt generated from local truth surfaces, "
                    + (
                        "and the browser execution proof is published."
                        if release_truth_state == "pass"
                        else "but browser execution proof is still pending."
                    )
                ),
                "source_paths": [
                    flagship_receipt_path.as_posix(),
                    "README.md",
                    "RUNBOOK.md",
                ],
            },
            {
                "cluster_id": "fleet_journey_coverage",
                "summary": (
                    "Fleet journey gates still block the install/claim/restore/continue story on cross-host coverage, "
                    "so wider publish claims should stay constrained."
                ),
                "source_paths": [
                    journey_gates_path.as_posix(),
                    "scripts/verify_release_assets.sh",
                ],
            },
            {
                "cluster_id": "governor_truth_alignment",
                "summary": (
                    "Product governor and support surfaces should keep quoting the same release truth instead of drifting "
                    "back to a mirrored Chummer pulse."
                ),
                "source_paths": [
                    "PRODUCT_GOVERNOR_AND_AUTOPILOT_LOOP.md",
                    "PRODUCT_CONTROL_AND_GOVERNOR_LOOP.md",
                    "PRODUCT_HEALTH_SCORECARD.yaml",
                ],
            },
        ],
        "oldest_blocker_days": 0,
        "design_drift_count": 0,
        "public_promise_drift_count": 0,
        "governor_decisions": governor_decisions,
        "next_checkpoint_question": (
            "What is the smallest cross-host coverage slice that can clear the remaining blocked journey tuples?"
            if release_truth_state == "pass"
            else "What is the smallest browser-execution receipt and cross-host coverage slice that can promote the EA flagship receipt from preview_only to pass?"
        ),
        "supporting_signals": {
            "current_recommended_wave": "EA flagship receipt closeout",
            "overall_progress_percent": readiness_share,
            "phase_label": "Journey coverage closeout" if release_truth_state == "pass" else "Preview-only flagship closeout",
            "history_snapshot_count": 1,
            "longest_pole": "cross-host journey coverage" if release_truth_state == "pass" else "browser execution proof",
            "launch_readiness": launch_readiness,
            "provider_route_stewardship": provider_route_stewardship,
            "journey_gate_source": journey_gates_path.as_posix(),
            "flagship_release_receipt_source": flagship_receipt_path.as_posix(),
            "scorecard_source": scorecard_path.as_posix(),
            "release_pipeline_source": release_pipeline_path.as_posix(),
            "governor_loop_source": governor_loop_path.as_posix(),
            "control_loop_source": control_loop_path.as_posix(),
            "release_checklist_source": release_checklist_path.as_posix(),
            "scorecard_metric_count": scorecard_metric_count,
        },
        "snapshot": {
            "release_health": {
                "state": release_health_state,
                "reason": (
                    "The EA flagship receipt is materialized, but it is still preview_only until browser execution proof is published."
                    if release_truth_state != "pass"
                    else "The EA flagship receipt is published and current."
                ),
                "flagship_receipt_status": release_truth_state,
            },
            "flagship_readiness": {
                "state": "watch" if release_truth_state != "pass" else "clear",
                "reason": (
                    "Browser execution proof is missing or incomplete, so the flagship receipt cannot yet claim pass status."
                    if release_truth_state != "pass"
                    else "Flagship receipt and browser proof are aligned."
                ),
            },
            "rule_environment_trust": {
                "state": "watch" if journey_state == "blocked" else "monitor",
                "reason": "Install/update trust still depends on the blocked cross-host journey set."
                if journey_state == "blocked"
                else "Rule-environment trust is governed by the current release receipt.",
            },
            "edition_authorship_and_import_confidence": {
                "state": "monitor",
                "reason": "The weekly pulse now uses EA-local release truth rather than a Chummer mirror.",
            },
            "journey_gate_health": {
                "state": journey_state,
                "reason": _compact(blocked_reason, fallback="Journey-gate posture is not available."),
                "blocked_count": blocked_count,
                "warning_count": int(journey_info["warning"]),
                "recommended_action": _compact(blocked_reason, fallback="Journey-gate posture is not available."),
            },
            "top_support_or_feedback_clusters": [
                {
                    "cluster_id": "ea_flagship_receipt_closeout",
                    "summary": (
                        "The weekly pulse now anchors to the EA flagship receipt generated from local truth surfaces, "
                        + (
                            "and the browser execution proof is published."
                            if release_truth_state == "pass"
                            else "but browser execution proof is still pending."
                        )
                    ),
                    "source_paths": [
                        flagship_receipt_path.as_posix(),
                        "README.md",
                        "RUNBOOK.md",
                    ],
                },
                {
                    "cluster_id": "fleet_journey_coverage",
                    "summary": (
                        "Fleet journey gates still block the install/claim/restore/continue story on cross-host coverage, "
                        "so wider publish claims should stay constrained."
                    ),
                    "source_paths": [
                        journey_gates_path.as_posix(),
                        "scripts/verify_release_assets.sh",
                    ],
                },
                {
                    "cluster_id": "governor_truth_alignment",
                    "summary": (
                        "Product governor and support surfaces should keep quoting the same release truth instead of drifting "
                        "back to a mirrored pulse."
                    ),
                    "source_paths": [
                        "PRODUCT_GOVERNOR_AND_AUTOPILOT_LOOP.md",
                        "PRODUCT_CONTROL_AND_GOVERNOR_LOOP.md",
                        "PRODUCT_HEALTH_SCORECARD.yaml",
                    ],
                },
            ],
            "oldest_blocker_days": 0,
            "design_drift_count": 0,
            "public_promise_drift_count": 0,
            "governor_decisions": governor_decisions,
            "next_checkpoint_question": (
                "What is the smallest cross-host coverage slice that can clear the remaining blocked journey tuples?"
                if release_truth_state == "pass"
                else "What is the smallest browser-execution receipt and cross-host coverage slice that can promote the EA flagship receipt from preview_only to pass?"
            ),
        },
        "release_wave": {
            "current_recommended_wave": "EA flagship receipt closeout",
            "active_wave_registry": scorecard_path.as_posix(),
        },
        "review_cadence": {
            "review": str(cadence.get("review") or "weekly").strip() or "weekly",
            "snapshot_owner": str(cadence.get("snapshot_owner") or "product_governor").strip() or "product_governor",
            "publication": str(cadence.get("publication") or "internal_canon_first").strip() or "internal_canon_first",
        },
    }
    return pulse


def main() -> int:
    parser = argparse.ArgumentParser(description="Materialize the EA weekly product pulse.")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="EA repository root.")
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD, help="Path to the EA product health scorecard.")
    parser.add_argument(
        "--journey-gates",
        type=Path,
        default=DEFAULT_JOURNEY_GATES,
        help="Path to the fleet published journey-gates receipt.",
    )
    parser.add_argument(
        "--flagship-receipt",
        type=Path,
        default=DEFAULT_FLAGSHIP_RECEIPT,
        help="Path to the EA flagship release receipt.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Path to write the weekly pulse receipt.",
    )
    parser.add_argument("--stdout", action="store_true", help="Print the generated pulse to stdout.")
    args = parser.parse_args()

    root = args.root.resolve()
    pulse = build_pulse(
        root,
        scorecard_path=args.scorecard,
        journey_gates_path=args.journey_gates,
        flagship_receipt_path=args.flagship_receipt,
    )

    output_path = root / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(pulse, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.stdout:
        print(json.dumps(pulse, indent=2, ensure_ascii=False))
    else:
        print(json.dumps({"status": "ok", "output": output_path.as_posix(), "contract_name": pulse["contract_name"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
