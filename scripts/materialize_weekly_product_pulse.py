#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
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
_RELEASE_TRUTH_HEAD_KEYS = {
    "release_truth_provenance.git_head",
    "supporting_signals.flagship_release_receipt_git_head",
}
_PROVENANCE_REFRESH_ALLOWED_PREFIXES = (
    ".codex-design/product/",
    ".codex-studio/published/",
    ".codex-design/repo/",
)
_PROVENANCE_REFRESH_ALLOWED_EXACT = {
    "README.md",
    "RUNBOOK.md",
    "RELEASE_CHECKLIST.md",
    "PRODUCT_RELEASE_CHECKLIST.md",
    "Makefile",
    "CHANGELOG.md",
    "LTDs.md",
    ".github/workflows/smoke-runtime.yml",
    "ea/app/api/routes/plans.py",
    "ea/app/services/execution_approval_pause_service.py",
    "scripts/materialize_ea_browser_workflow_proof.py",
    "scripts/materialize_weekly_product_pulse.py",
    "scripts/operator_summary.sh",
    "scripts/smoke_api.sh",
    "scripts/smoke_postgres.sh",
    "scripts/test_postgres_contracts.sh",
    "scripts/verify_generated_release_artifacts_clean.py",
    "scripts/verify_flagship_release_readiness.py",
    "scripts/verify_release_assets.sh",
    "tests/e2e/visual_baselines/admin-community-page.png",
    "tests/test_chummer5a_parity_lab_pack.py",
    "tests/test_ea_browser_workflow_proof_materializer.py",
    "tests/e2e/test_product_workflows.py",
    "tests/test_execution_runtime_services.py",
    "tests/test_flagship_release_readiness_gate.py",
    "tests/test_migration_contracts.py",
    "tests/test_operator_contracts.py",
    "tests/test_providers_api_contracts.py",
    "tests/test_skills.py",
    "tests/smoke_runtime_api_suite_3.py",
    "tests/test_weekly_product_pulse_materializer.py",
}


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


def _normalize_release_value(value: Any) -> Any:
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if key in {
                "generated_at",
                "as_of",
                "created_at",
                "mtime_utc",
                "size_bytes",
                "sha256",
                "duration_seconds",
                "git_branch",
                "git_head",
                "source_path",
                "resolved_path",
                "git_repo_root",
            }:
                continue
            if key.endswith("_git_head"):
                continue
            if key == "review_due":
                continue
            normalized[key] = _normalize_release_value(item)
        return normalized
    if isinstance(value, list):
        return [_normalize_release_value(item) for item in value]
    return value


def _provenance_heads(value: Any, *, prefix: str = "") -> dict[str, str]:
    if isinstance(value, dict):
        heads: dict[str, str] = {}
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if key == "git_head" or str(key).endswith("_git_head"):
                heads[path] = str(item or "").strip()
                continue
            heads.update(_provenance_heads(item, prefix=path))
        return heads
    if isinstance(value, list):
        heads: dict[str, str] = {}
        for index, item in enumerate(value):
            heads.update(_provenance_heads(item, prefix=f"{prefix}[{index}]"))
        return heads
    return {}


def _changed_paths_between_heads(old_head: str, new_head: str, *, repo_root: Path = DEFAULT_ROOT) -> list[str] | None:
    try:
        output = subprocess.run(
            ["git", "-C", str(repo_root), "diff", "--name-only", f"{old_head}..{new_head}"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except Exception:
        return None
    return [line.strip() for line in output.splitlines() if line.strip()]


def _allowed_provenance_refresh_path(path: str) -> bool:
    return path in _PROVENANCE_REFRESH_ALLOWED_EXACT or any(
        path.startswith(prefix) for prefix in _PROVENANCE_REFRESH_ALLOWED_PREFIXES
    )


def _provenance_refresh_required(existing_heads: dict[str, str], payload_heads: dict[str, str]) -> bool:
    if existing_heads == payload_heads:
        return False

    differing_keys = {
        key
        for key in set(existing_heads) | set(payload_heads)
        if existing_heads.get(key) != payload_heads.get(key)
    }
    if not differing_keys <= _RELEASE_TRUTH_HEAD_KEYS:
        return True

    old_head = existing_heads.get("release_truth_provenance.git_head") or existing_heads.get(
        "supporting_signals.flagship_release_receipt_git_head"
    )
    new_head = payload_heads.get("release_truth_provenance.git_head") or payload_heads.get(
        "supporting_signals.flagship_release_receipt_git_head"
    )
    if not old_head or not new_head:
        return True

    changed_paths = _changed_paths_between_heads(old_head, new_head)
    if changed_paths is None:
        return True
    return any(not _allowed_provenance_refresh_path(path) for path in changed_paths)


def _write_json_stable(path: Path, payload: dict[str, Any]) -> None:
    serialized = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            existing = None
        if (
            isinstance(existing, dict)
            and _normalize_release_value(existing) == _normalize_release_value(payload)
            and not _provenance_refresh_required(_provenance_heads(existing), _provenance_heads(payload))
        ):
            return
    path.write_text(serialized, encoding="utf-8")


def _compact(value: object, *, fallback: str = "", limit: int = 220) -> str:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        text = fallback
    if len(text) > limit:
        return text[: max(limit - 1, 0)].rstrip() + "…"
    return text


def _existing_cited_signal_int(existing: dict[str, Any], signal_name: str, *, fallback: int = 0) -> int:
    prefix = f"{signal_name}="
    signal_sources = [
        existing.get("governor_decisions") or [],
        dict(existing.get("snapshot") or {}).get("governor_decisions") or [],
    ]
    for decisions in signal_sources:
        for decision in decisions:
            if not isinstance(decision, dict):
                continue
            for signal in decision.get("cited_signals") or []:
                signal_text = str(signal or "")
                if not signal_text.startswith(prefix):
                    continue
                try:
                    return int(signal_text[len(prefix) :])
                except ValueError:
                    continue
    return fallback


def _resolve_for_read(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_metadata_for_path(path: Path) -> dict[str, str]:
    candidate = path if path.is_dir() else path.parent
    try:
        repo_root = subprocess.run(
            ["git", "-C", str(candidate), "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        git_head = subprocess.run(
            ["git", "-C", repo_root, "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        git_branch = subprocess.run(
            ["git", "-C", repo_root, "rev-parse", "--abbrev-ref", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except Exception:
        return {}

    metadata: dict[str, str] = {
        "git_repo_root": repo_root,
        "git_head": git_head,
        "git_branch": git_branch,
    }
    try:
        metadata["repo_relative_path"] = str(path.resolve().relative_to(Path(repo_root).resolve()))
    except Exception:
        pass
    return metadata


def _source_provenance(path: Path) -> dict[str, Any]:
    resolved = path.resolve() if path.exists() else path
    payload: dict[str, Any] = {
        "source_path": path.as_posix(),
        "resolved_path": resolved.as_posix(),
        "present": path.exists(),
    }
    if not path.exists():
        return payload
    try:
        stat = path.stat()
        payload["size_bytes"] = stat.st_size
        payload["mtime_utc"] = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        payload["sha256"] = _sha256_file(path)
    except Exception:
        pass
    payload.update(_git_metadata_for_path(path))
    return payload


def _journey_gate_source(root: Path, journey_path: Path) -> dict[str, Any]:
    resolved = _resolve_for_read(root, journey_path)
    if not resolved.exists():
        existing = _load_json(root / DEFAULT_OUTPUT) or {}
        existing_health = dict(existing.get("journey_gate_health") or {})
        existing_provenance = dict(existing.get("journey_gate_provenance") or {})
        if existing_health or existing_provenance:
            existing_signals = dict(existing.get("supporting_signals") or {})
            blocked = int(existing_health.get("blocked_count") or 0)
            warning = int(existing_health.get("warning_count") or 0)
            state = str(existing_health.get("state") or "missing").strip() or "missing"
            recommended_action = _compact(
                existing_health.get("recommended_action") or existing_health.get("reason") or "",
                fallback="Journey-gate posture is preserved from the last committed external snapshot.",
            )
            total = int(
                existing_health.get("total_count")
                or _existing_cited_signal_int(existing, "journey_gate_total_count")
                or blocked
            )
            ready = int(
                existing_health.get("ready_count")
                or _existing_cited_signal_int(existing, "journey_gate_ready_count")
                or max(total - blocked - warning, 0)
            )
            ready_share = int(
                existing_signals.get("overall_progress_percent")
                or _existing_cited_signal_int(existing, "ready_share")
                or 0
            )
            preserved_path = Path(str(existing.get("journey_gate_source") or journey_path.as_posix()))
            provenance = existing_provenance or _source_provenance(resolved)
            provenance.setdefault("present", False)
            return {
                "journey": {},
                "summary": {},
                "journeys": [],
                "path": preserved_path,
                "state": state,
                "recommended_action": recommended_action,
                "blocked": blocked,
                "ready": ready,
                "warning": warning,
                "total": total,
                "ready_share": int(round((ready / total) * 100)) if total else ready_share,
                "provenance": provenance,
            }
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
        "provenance": _source_provenance(resolved),
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
        "provenance": _source_provenance(resolved),
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
    journey_source_path = Path(str(journey_info.get("path") or journey_gates_path.as_posix()))
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

    if release_truth_state == "pass" and journey_state == "blocked":
        summary = (
            "Executive Assistant has a green flagship receipt, but the fleet journey gate is "
            f"{journey_state}, and {blocked_count} journey(s) still block wider claims."
        )
    elif release_truth_state == "pass":
        summary = (
            "Executive Assistant has a green flagship receipt, the fleet journey gate is "
            f"{journey_state}, and no journeys block wider release claims."
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
        if release_truth_state != "pass"
        else "Hold launch expansion pending cross-host journey coverage."
        if journey_state == "blocked"
        else "Release truth is clear enough to widen claims."
    )
    canary_status = (
        "Browser execution proof is still missing; cross-host journey coverage remains blocked."
        if release_truth_state != "pass"
        else "Browser execution proof is published, but cross-host journey coverage remains blocked."
        if journey_state == "blocked"
        else "Browser execution proof is published and routes are aligned to local truth surfaces."
    )
    next_decision = (
        "Publish browser execution proof, then re-materialize the weekly pulse and release receipt."
        if release_truth_state != "pass"
        else "Ingest the remaining cross-host journey receipts, then re-materialize the weekly pulse and release receipt."
        if journey_state == "blocked"
        else "Re-materialize the weekly pulse after the next meaningful release or journey-truth change."
    )
    provider_route_stewardship = {
        "default_status": "EA routes are governed by local truth surfaces.",
        "canary_status": canary_status,
        "review_due": review_due,
        "next_decision": next_decision,
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
            "action": (
                "freeze_launch"
                if release_truth_state != "pass" or journey_state == "blocked"
                else "hold_truth_line"
            ),
            "reason": (
                "Freeze launch expansion until browser execution proof is published and the blocked journey tuples are cleared."
                if release_truth_state != "pass"
                else "Freeze launch expansion until the blocked journey tuples are cleared."
                if journey_state == "blocked"
                else "Launch expansion can proceed because browser proof is published and blocked journey tuples are cleared."
            ),
            "cited_signals": [
                f"flagship_receipt_status={release_truth_state}",
                f"browser_execution_receipt_present={receipt_info['browser_present']}",
                f"journey_gate_blocked_count={blocked_count}",
                (
                    "cross_host_tuple_coverage=blocked"
                    if journey_state == "blocked"
                    else "cross_host_tuple_coverage=ready"
                ),
            ],
        },
    ]

    fleet_cluster_summary = (
        "Fleet journey gates still block the install/claim/restore/continue story on cross-host coverage, "
        "so wider publish claims should stay constrained."
        if journey_state == "blocked"
        else "Fleet journey gates are ready across the install/claim/restore/continue story, "
        "so wider publish claims can follow the current release truth."
    )

    blocked_reason = journey_info["recommended_action"] or "Resolve the blocking journey gaps before widening publish claims."
    pulse: dict[str, Any] = {
        "contract_name": "ea.weekly_product_pulse",
        "contract_version": 1,
        "generated_at": generated_at,
        "as_of": generated_at[:10],
        "scorecard_source": scorecard_path.as_posix(),
        "release_truth_source": flagship_receipt_path.as_posix(),
        "release_truth_provenance": receipt_info["provenance"],
        "journey_gate_source": journey_source_path.as_posix(),
        "journey_gate_provenance": journey_info["provenance"],
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
                "summary": fleet_cluster_summary,
                "source_paths": [
                    journey_source_path.as_posix(),
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
            "journey_gate_source": journey_source_path.as_posix(),
            "journey_gate_git_head": str(journey_info["provenance"].get("git_head") or "").strip(),
            "flagship_release_receipt_source": flagship_receipt_path.as_posix(),
            "flagship_release_receipt_git_head": str(receipt_info["provenance"].get("git_head") or "").strip(),
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
                    "summary": fleet_cluster_summary,
                    "source_paths": [
                        journey_source_path.as_posix(),
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
                "What is the next meaningful release or journey-truth change that should trigger pulse re-materialization?"
                if release_truth_state == "pass" and journey_state != "blocked"
                else "What is the smallest cross-host coverage slice that can clear the remaining blocked journey tuples?"
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
    _write_json_stable(output_path, pulse)
    if args.stdout:
        print(json.dumps(pulse, indent=2, ensure_ascii=False))
    else:
        print(json.dumps({"status": "ok", "output": output_path.as_posix(), "contract_name": pulse["contract_name"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
