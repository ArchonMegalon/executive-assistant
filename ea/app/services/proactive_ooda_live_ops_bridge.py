from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from functools import lru_cache
import sys
from typing import Any, Callable, Mapping

from app.services.proactive_ooda_runtime_artifacts import (
    load_runtime_artifact_bundle,
    select_current_approval_outcome_for_bundle,
)


def proactive_ooda_live_ops_timeout_seconds() -> float:
    raw = str(os.getenv("EA_PROACTIVE_OODA_ADMIN_LIVE_TIMEOUT_SECONDS") or "").strip()
    if not raw:
        return 30.0
    try:
        value = float(raw)
    except ValueError:
        return 30.0
    return min(max(value, 1.0), 120.0)


@lru_cache(maxsize=1)
def _ea_live_ops_module() -> Any:
    script_path = _ea_live_ops_script_path()
    repo_root = script_path.parent.parent
    for candidate in (repo_root / "ea", repo_root, repo_root / "scripts"):
        candidate_text = candidate.as_posix()
        if candidate.exists() and candidate_text not in sys.path:
            sys.path.insert(0, candidate_text)
    spec = importlib.util.spec_from_file_location("ea_live_ops_bridge_module", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("ea_live_ops_script_unloadable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ea_live_ops_script_path(*, service_file: Path | None = None) -> Path:
    source = (service_file or Path(__file__)).resolve()
    roots: list[Path] = []
    env_root = str(os.getenv("EA_LIVE_OPS_ROOT") or "").strip()
    if env_root:
        roots.append(Path(env_root).expanduser())
    for index in (2, 3):
        try:
            root = source.parents[index]
        except IndexError:
            continue
        roots.append(root)
    roots.extend((Path("/app"), Path.cwd()))
    seen: set[str] = set()
    for root in roots:
        root_text = root.as_posix()
        if root_text in seen:
            continue
        seen.add(root_text)
        candidate = root / "scripts" / "ea_live_ops.py"
        if candidate.is_file():
            return candidate
    raise RuntimeError("ea_live_ops_script_missing")


def probe_live_proactive_artifacts(
    *,
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    module = _ea_live_ops_module()
    report = module.probe_proactive_artifacts(
        timeout_seconds=timeout_seconds or proactive_ooda_live_ops_timeout_seconds(),
        output_format="json",
    )
    return dict(report) if isinstance(report, dict) else {}


def resolve_proactive_ooda_capture_bundle(
    *,
    root: Path,
    state_path: str | Path,
    receipt_path: str | Path = "",
    stage_packet_dir: str | Path = "",
    safe_work_result_dir: str | Path = "",
    timeout_seconds: float | None = None,
    live_probe: Callable[..., Mapping[str, Any]] = probe_live_proactive_artifacts,
    bundle_loader: Callable[..., Mapping[str, Any]] = load_runtime_artifact_bundle,
) -> dict[str, Any]:
    try:
        live_report = dict(live_probe(timeout_seconds=timeout_seconds))
    except Exception as exc:
        live_report = {
            "probe_ok": False,
            "status": "probe_failed",
            "reason": type(exc).__name__,
            "blocking_reason": type(exc).__name__,
        }
    if bool(live_report.get("probe_ok")):
        bundle = _bundle_from_live_artifact_probe(live_report)
        return {
            "bundle": bundle,
            "bundle_source": "live_runtime",
            "host_fallback_used": False,
            "fallback_reason": "",
            "live_report": live_report,
            "approval_selection": select_current_approval_outcome_for_bundle(bundle),
        }
    bundle = dict(
        bundle_loader(
            root=root,
            state_path=state_path,
            receipt_path=receipt_path,
            stage_packet_dir=stage_packet_dir,
            safe_work_result_dir=safe_work_result_dir,
        )
    )
    fallback_reason = str(
        live_report.get("blocking_reason")
        or live_report.get("reason")
        or live_report.get("status")
        or "live_runtime_probe_failed"
    ).strip()
    return {
        "bundle": bundle,
        "bundle_source": "host_runtime_fallback",
        "host_fallback_used": True,
        "fallback_reason": fallback_reason,
        "live_report": live_report,
        "approval_selection": select_current_approval_outcome_for_bundle(bundle),
    }


def record_live_proactive_ooda_approval_outcome(
    *,
    principal_id: str,
    outcome: str,
    evidence: str,
    actor: str,
    source_kind: str = "operator",
    packet_ref: str = "",
    staged_artifact_ref: str = "",
    dry_run: bool = False,
    timeout_seconds: float | None = None,
    recorder: Callable[..., Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    record = recorder or _record_live_proactive_approval_outcome
    try:
        report = dict(
            record(
                principal_id=principal_id,
                outcome=outcome,
                evidence=evidence,
                actor=actor,
                source_kind=source_kind,
                packet_ref=packet_ref,
                staged_artifact_ref=staged_artifact_ref,
                dry_run=dry_run,
                timeout_seconds=timeout_seconds or proactive_ooda_live_ops_timeout_seconds(),
            )
        )
    except Exception as exc:
        report = {
            "recorded": False,
            "reason": "record_failed:bridge_exception",
            "blocking_reason": type(exc).__name__,
        }
    approval_outcome = dict(report.get("approval_outcome") or {})
    reason = str(report.get("reason") or "").strip()
    outcome_status = str(approval_outcome.get("status") or "").strip()
    if bool(report.get("recorded")):
        status = "already_decided" if reason == "already_decided" else "recorded"
    elif reason == "artifact_probe_failed":
        status = "probe_failed"
    elif reason.startswith("record_failed:"):
        status = "record_failed"
    else:
        status = outcome_status or reason or "failed"
    error = ""
    if status not in {"recorded", "already_decided"}:
        error = str(
            approval_outcome.get("reason")
            or report.get("blocking_reason")
            or reason
            or status
        ).strip()
    return {
        **report,
        "status": status,
        "error": error,
    }


def _record_live_proactive_approval_outcome(
    *,
    principal_id: str,
    outcome: str,
    evidence: str,
    actor: str,
    source_kind: str = "operator",
    packet_ref: str = "",
    staged_artifact_ref: str = "",
    dry_run: bool = False,
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    module = _ea_live_ops_module()
    report = module.record_proactive_approval(
        principal_id=principal_id,
        outcome=outcome,
        evidence=evidence,
        actor=actor,
        source_kind=source_kind,
        packet_ref=packet_ref,
        staged_artifact_ref=staged_artifact_ref,
        dry_run=dry_run,
        timeout_seconds=timeout_seconds or proactive_ooda_live_ops_timeout_seconds(),
        output_format="json",
    )
    return dict(report) if isinstance(report, dict) else {}


def _bundle_from_live_artifact_probe(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "state_path": str(report.get("state_path") or "").strip(),
        "run_receipt_path": str(report.get("run_receipt_path") or "").strip(),
        "action_required_only_quiet_receipt_path": str(report.get("action_required_only_quiet_receipt_path") or "").strip(),
        "stage_packet_dir": str(report.get("stage_packet_dir") or "").strip(),
        "safe_work_result_dir": str(report.get("safe_work_result_dir") or "").strip(),
        "approval_outcome_path": str(report.get("approval_outcome_path") or "").strip(),
        "approval_callback_dir": str(report.get("approval_callback_dir") or "").strip(),
        "stage_packet_path": str(report.get("stage_packet_path") or "").strip(),
        "safe_work_result_path": str(report.get("safe_work_result_path") or "").strip(),
        "run_receipt": dict(report.get("run_receipt") or {}),
        "action_required_only_quiet_receipt": dict(report.get("action_required_only_quiet_receipt") or {}),
        "stage_packet": dict(report.get("stage_packet") or {}),
        "safe_work_result": dict(report.get("safe_work_result") or {}),
        "approval_outcome": dict(report.get("approval_outcome") or {}),
        "current_packet_callback_outcome": dict(report.get("current_packet_callback_outcome") or {}),
        "approval_callback_dir_exists": bool(report.get("approval_callback_dir_exists")),
        "approval_callback_dir_writable": bool(report.get("approval_callback_dir_writable")),
        "approval_callback_record_count": int(report.get("approval_callback_record_count") or 0),
        "approval_callback_pending_count": int(report.get("approval_callback_pending_count") or 0),
        "approval_callback_raw_pending_count": int(report.get("approval_callback_raw_pending_count") or 0),
        "approval_callback_live_pending_count": int(report.get("approval_callback_live_pending_count") or 0),
        "approval_callback_unexpired_pending_count": int(report.get("approval_callback_unexpired_pending_count") or 0),
        "approval_callback_noncurrent_pending_count": int(report.get("approval_callback_noncurrent_pending_count") or 0),
        "approval_callback_expired_pending_count": int(report.get("approval_callback_expired_pending_count") or 0),
        "approval_callback_stale_pending_count": int(report.get("approval_callback_stale_pending_count") or 0),
        "approval_callback_recorded_count": int(report.get("approval_callback_recorded_count") or 0),
        "approval_callback_expired_count": int(report.get("approval_callback_expired_count") or 0),
        "approval_callback_superseded_count": int(report.get("approval_callback_superseded_count") or 0),
        "approval_callback_terminal_count": int(report.get("approval_callback_terminal_count") or 0),
        "current_packet_callback_record_count": int(report.get("current_packet_callback_record_count") or 0),
        "current_packet_callback_pending_count": int(report.get("current_packet_callback_pending_count") or 0),
        "current_packet_callback_raw_pending_count": int(report.get("current_packet_callback_raw_pending_count") or 0),
        "current_packet_callback_expired_pending_count": int(report.get("current_packet_callback_expired_pending_count") or 0),
        "current_packet_callback_stale_pending_count": int(report.get("current_packet_callback_stale_pending_count") or 0),
        "current_packet_callback_recorded_count": int(report.get("current_packet_callback_recorded_count") or 0),
        "current_packet_callback_expired_count": int(report.get("current_packet_callback_expired_count") or 0),
        "current_packet_callback_superseded_count": int(report.get("current_packet_callback_superseded_count") or 0),
        "current_packet_live_callback_record_count": int(report.get("current_packet_live_callback_record_count") or 0),
        "current_packet_live_pending_count": int(report.get("current_packet_live_pending_count") or 0),
        "current_packet_callback_latest_status": str(report.get("current_packet_callback_latest_status") or "").strip(),
        "current_packet_callback_latest_expired": bool(report.get("current_packet_callback_latest_expired")),
        "current_packet_callback_latest_created_at": str(report.get("current_packet_callback_latest_created_at") or "").strip(),
        "current_packet_callback_latest_expires_at": str(report.get("current_packet_callback_latest_expires_at") or "").strip(),
        "current_packet_callback_latest_age_seconds": int(report.get("current_packet_callback_latest_age_seconds") or 0),
        "current_packet_callback_latest_seconds_until_expiry": int(
            report.get("current_packet_callback_latest_seconds_until_expiry") or 0
        ),
    }
