from __future__ import annotations

import hashlib
import importlib.util
import os
from pathlib import Path
from functools import lru_cache
import sys
from typing import Any, Callable, Mapping

from app.services.proactive_ooda_runtime_artifacts import (
    current_packet_user_approval_surface,
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


def _path_text(value: Any) -> str:
    if isinstance(value, Path):
        return value.as_posix().strip()
    return str(value or "").strip()


def _hash_value(value: str) -> str:
    normalized = str(value or "").strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest() if normalized else ""


def _stage_packet_ref(stage_packet: Mapping[str, Any]) -> str:
    return str(stage_packet.get("packet_ref") or stage_packet.get("packet_id") or "").strip()


def _safe_work_result_ref(safe_work_result: Mapping[str, Any]) -> str:
    result_ref = str(safe_work_result.get("result_ref") or "").strip()
    if result_ref:
        return result_ref
    result_id = str(safe_work_result.get("result_id") or "").strip()
    return f"safe_work_result:{result_id}" if result_id else ""


def _bundle_has_runtime_artifacts(bundle: Mapping[str, Any]) -> bool:
    normalized = dict(bundle or {})
    for key in (
        "run_receipt",
        "stage_packet",
        "safe_work_result",
        "approval_outcome",
        "current_packet_callback_outcome",
    ):
        if dict(normalized.get(key) or {}):
            return True
    for key in (
        "approval_callback_record_count",
        "approval_callback_pending_count",
        "approval_callback_recorded_count",
        "current_packet_callback_record_count",
        "current_packet_callback_pending_count",
        "current_packet_live_pending_count",
    ):
        if int(normalized.get(key) or 0) > 0:
            return True
    return False


def _bundle_has_current_packet_evidence(bundle: Mapping[str, Any]) -> bool:
    normalized = dict(bundle or {})
    if _stage_packet_ref(dict(normalized.get("stage_packet") or {})) and _safe_work_result_ref(
        dict(normalized.get("safe_work_result") or {})
    ):
        return True
    if int(normalized.get("current_packet_live_pending_count") or 0) > 0:
        return True
    if int(normalized.get("current_packet_callback_pending_count") or 0) > 0:
        return True
    if dict(select_current_approval_outcome_for_bundle(normalized).get("approval_outcome") or {}):
        return True
    return False


def _bundle_has_coherent_run_receipt(bundle: Mapping[str, Any]) -> bool:
    run_receipt = dict(dict(bundle or {}).get("run_receipt") or {})
    if not run_receipt:
        return False
    if str(run_receipt.get("notification_status") or "").strip():
        return True
    if int(run_receipt.get("item_count") or 0) > 0:
        return True
    stage_hashes = [str(item or "").strip() for item in list(run_receipt.get("stage_packet_ref_hashes") or []) if str(item or "").strip()]
    safe_hashes = [str(item or "").strip() for item in list(run_receipt.get("safe_work_result_ref_hashes") or []) if str(item or "").strip()]
    return bool(stage_hashes and safe_hashes)


def _runtime_artifact_drift_summary(
    *,
    live_bundle: Mapping[str, Any],
    host_bundle: Mapping[str, Any],
    host_compare_error: str = "",
) -> dict[str, Any]:
    if not _bundle_has_current_packet_evidence(live_bundle):
        return {
            "checked": False,
            "present": False,
            "status": "current_packet_not_present",
            "requires_recovery": False,
            "blocking_reason": "",
            "next_action": "",
            "mismatch_count": 0,
            "material_mismatch_count": 0,
            "mismatch_fields": [],
            "material_mismatch_fields": [],
            "host_artifacts_present": _bundle_has_runtime_artifacts(host_bundle),
            "privacy": {
                "raw_packet_ref_exposed": False,
                "raw_staged_artifact_ref_exposed": False,
                "raw_private_paths_exposed": False,
            },
        }
    error = str(host_compare_error or "").strip()
    if error:
        return {
            "checked": False,
            "present": True,
            "status": "host_compare_failed",
            "requires_recovery": False,
            "blocking_reason": f"host_compare_failed:{error}",
            "next_action": "",
            "mismatch_count": 0,
            "material_mismatch_count": 0,
            "mismatch_fields": [],
            "material_mismatch_fields": [],
            "host_artifacts_present": False,
            "privacy": {
                "raw_packet_ref_exposed": False,
                "raw_staged_artifact_ref_exposed": False,
                "raw_private_paths_exposed": False,
            },
        }
    if not _bundle_has_coherent_run_receipt(host_bundle):
        return {
            "checked": False,
            "present": False,
            "status": "host_bundle_not_checked",
            "requires_recovery": False,
            "blocking_reason": "",
            "next_action": "",
            "mismatch_count": 0,
            "material_mismatch_count": 0,
            "mismatch_fields": [],
            "material_mismatch_fields": [],
            "host_artifacts_present": _bundle_has_runtime_artifacts(host_bundle),
            "privacy": {
                "raw_packet_ref_exposed": False,
                "raw_staged_artifact_ref_exposed": False,
                "raw_private_paths_exposed": False,
            },
        }
    if not _bundle_has_current_packet_evidence(host_bundle):
        return {
            "checked": False,
            "present": False,
            "status": "host_bundle_not_checked",
            "requires_recovery": False,
            "blocking_reason": "",
            "next_action": "",
            "mismatch_count": 0,
            "material_mismatch_count": 0,
            "mismatch_fields": [],
            "material_mismatch_fields": [],
            "host_artifacts_present": False,
            "privacy": {
                "raw_packet_ref_exposed": False,
                "raw_staged_artifact_ref_exposed": False,
                "raw_private_paths_exposed": False,
            },
        }

    live = dict(live_bundle or {})
    host = dict(host_bundle or {})
    live_selection = select_current_approval_outcome_for_bundle(live)
    host_selection = select_current_approval_outcome_for_bundle(host)
    live_selected_outcome = dict(live_selection.get("approval_outcome") or {})
    host_selected_outcome = dict(host_selection.get("approval_outcome") or {})
    rows = (
        ("stage_packet_ref_sha256", _hash_value(_stage_packet_ref(dict(live.get("stage_packet") or {}))), _hash_value(_stage_packet_ref(dict(host.get("stage_packet") or {})))),
        ("safe_work_result_ref_sha256", _hash_value(_safe_work_result_ref(dict(live.get("safe_work_result") or {}))), _hash_value(_safe_work_result_ref(dict(host.get("safe_work_result") or {})))),
        ("safe_work_result_status", str(dict(live.get("safe_work_result") or {}).get("status") or "").strip(), str(dict(host.get("safe_work_result") or {}).get("status") or "").strip()),
        ("artifact_filter_reason", str(live.get("artifact_filter_reason") or "").strip(), str(host.get("artifact_filter_reason") or "").strip()),
        ("run_receipt_notification_status", str(dict(live.get("run_receipt") or {}).get("notification_status") or "").strip(), str(dict(host.get("run_receipt") or {}).get("notification_status") or "").strip()),
        ("approval_selection_source", str(live_selection.get("source") or "").strip(), str(host_selection.get("source") or "").strip()),
        ("approval_outcome_recorded", bool(live_selected_outcome.get("approval_outcome_recorded")), bool(host_selected_outcome.get("approval_outcome_recorded"))),
        ("approval_outcome_status", str(live_selected_outcome.get("status") or "").strip(), str(host_selected_outcome.get("status") or "").strip()),
        ("current_packet_live_pending_count", int(live.get("current_packet_live_pending_count") or 0), int(host.get("current_packet_live_pending_count") or 0)),
        ("current_packet_callback_pending_count", int(live.get("current_packet_callback_pending_count") or 0), int(host.get("current_packet_callback_pending_count") or 0)),
    )
    mismatches: list[dict[str, Any]] = []
    for field, live_value, host_value in rows:
        if live_value == host_value:
            continue
        mismatches.append(
            {
                "field": field,
                "live": live_value,
                "host": host_value,
                "material": True,
            }
        )
    mismatch_fields = [str(row.get("field") or "").strip() for row in mismatches if str(row.get("field") or "").strip()]
    requires_recovery = bool(mismatch_fields)
    return {
        "checked": True,
        "present": requires_recovery,
        "status": "drift_detected" if requires_recovery else "aligned",
        "requires_recovery": requires_recovery,
        "blocking_reason": f"runtime_artifact_drift:{mismatch_fields[0]}" if mismatch_fields else "",
        "next_action": "repair_proactive_runtime_artifact_drift" if requires_recovery else "",
        "mismatch_count": len(mismatch_fields),
        "material_mismatch_count": len(mismatch_fields),
        "mismatch_fields": mismatch_fields,
        "material_mismatch_fields": list(mismatch_fields),
        "host_artifacts_present": True,
        "privacy": {
            "raw_packet_ref_exposed": False,
            "raw_staged_artifact_ref_exposed": False,
            "raw_private_paths_exposed": False,
        },
    }


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
        host_bundle: dict[str, Any] = {}
        host_compare_error = ""
        try:
            host_bundle = dict(
                bundle_loader(
                    root=root,
                    state_path=state_path,
                    receipt_path=receipt_path,
                    stage_packet_dir=stage_packet_dir,
                    safe_work_result_dir=safe_work_result_dir,
                )
            )
        except Exception as exc:
            host_compare_error = type(exc).__name__
        return {
            "bundle": bundle,
            "bundle_source": "live_runtime",
            "host_fallback_used": False,
            "fallback_reason": "",
            "live_report": live_report,
            "runtime_artifact_drift": _runtime_artifact_drift_summary(
                live_bundle=bundle,
                host_bundle=host_bundle,
                host_compare_error=host_compare_error,
            ),
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
        "runtime_artifact_drift": {
            "checked": False,
            "present": False,
            "status": "host_runtime_fallback_active",
            "requires_recovery": False,
            "blocking_reason": "",
            "next_action": "",
            "mismatch_count": 0,
            "material_mismatch_count": 0,
            "mismatch_fields": [],
            "material_mismatch_fields": [],
            "host_artifacts_present": _bundle_has_runtime_artifacts(bundle),
            "privacy": {
                "raw_packet_ref_exposed": False,
                "raw_staged_artifact_ref_exposed": False,
                "raw_private_paths_exposed": False,
            },
        },
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


def reissue_live_proactive_ooda_approval(
    *,
    principal_id: str,
    dry_run: bool = False,
    force: bool = False,
    reissue_after_seconds: int = 0,
    timeout_seconds: float | None = None,
    reissuer: Callable[..., Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    run = reissuer or _reissue_live_proactive_approval
    try:
        report = dict(
            run(
                principal_id=principal_id,
                dry_run=dry_run,
                force=force,
                reissue_after_seconds=reissue_after_seconds,
                timeout_seconds=timeout_seconds or proactive_ooda_live_ops_timeout_seconds(),
            )
        )
    except Exception as exc:
        report = {
            "sent": False,
            "status": "bridge_exception",
            "reason": "reissue_failed:bridge_exception",
            "blocking_reason": type(exc).__name__,
        }
    status = str(report.get("status") or "").strip()
    if not status:
        status = "sent" if bool(report.get("sent")) else str(report.get("reason") or "failed").strip() or "failed"
    error = ""
    if status not in {"sent", "already_live_pending", "already_decided", "dry_run"}:
        error = str(
            report.get("blocking_reason")
            or report.get("reason")
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


def _reissue_live_proactive_approval(
    *,
    principal_id: str,
    dry_run: bool = False,
    force: bool = False,
    reissue_after_seconds: int = 0,
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    module = _ea_live_ops_module()
    report = module.reissue_proactive_approval(
        principal_id=principal_id,
        dry_run=dry_run,
        force=force,
        reissue_after_seconds=reissue_after_seconds,
        timeout_seconds=timeout_seconds or proactive_ooda_live_ops_timeout_seconds(),
        output_format="json",
    )
    return dict(report) if isinstance(report, dict) else {}


def _bundle_from_live_artifact_probe(report: Mapping[str, Any]) -> dict[str, Any]:
    stage_packet = dict(report.get("stage_packet") or {})
    safe_work_result = dict(report.get("safe_work_result") or {})
    current_packet_requires_user_approval = current_packet_user_approval_surface(
        stage_packet=stage_packet,
        safe_work_result=safe_work_result,
    )
    current_packet_live_pending_count = int(report.get("current_packet_live_pending_count") or 0)
    current_packet_callback_pending_count = int(report.get("current_packet_callback_pending_count") or 0)
    current_packet_callback_raw_pending_count = int(report.get("current_packet_callback_raw_pending_count") or 0)
    approval_callback_pending_count = int(report.get("approval_callback_pending_count") or 0)
    approval_callback_live_pending_count = int(report.get("approval_callback_live_pending_count") or 0)
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
        "artifact_filter_reason": str(report.get("artifact_filter_reason") or "").strip(),
        "run_receipt": dict(report.get("run_receipt") or {}),
        "action_required_only_quiet_receipt": dict(report.get("action_required_only_quiet_receipt") or {}),
        "stage_packet": stage_packet,
        "safe_work_result": safe_work_result,
        "approval_outcome": dict(report.get("approval_outcome") or {}),
        "current_packet_callback_outcome": dict(report.get("current_packet_callback_outcome") or {}),
        "approval_callback_dir_exists": bool(report.get("approval_callback_dir_exists")),
        "approval_callback_dir_writable": bool(report.get("approval_callback_dir_writable")),
        "approval_callback_record_count": int(report.get("approval_callback_record_count") or 0),
        "approval_callback_pending_count": approval_callback_pending_count,
        "approval_callback_raw_pending_count": int(report.get("approval_callback_raw_pending_count") or 0),
        "approval_callback_live_pending_count": approval_callback_live_pending_count,
        "approval_callback_unexpired_pending_count": int(report.get("approval_callback_unexpired_pending_count") or 0),
        "approval_callback_noncurrent_pending_count": int(report.get("approval_callback_noncurrent_pending_count") or 0),
        "approval_callback_expired_pending_count": int(report.get("approval_callback_expired_pending_count") or 0),
        "approval_callback_stale_pending_count": int(report.get("approval_callback_stale_pending_count") or 0),
        "approval_callback_recorded_count": int(report.get("approval_callback_recorded_count") or 0),
        "approval_callback_expired_count": int(report.get("approval_callback_expired_count") or 0),
        "approval_callback_superseded_count": int(report.get("approval_callback_superseded_count") or 0),
        "approval_callback_terminal_count": int(report.get("approval_callback_terminal_count") or 0),
        "current_packet_callback_record_count": int(report.get("current_packet_callback_record_count") or 0),
        "current_packet_callback_pending_count": current_packet_callback_pending_count,
        "current_packet_callback_raw_pending_count": current_packet_callback_raw_pending_count,
        "current_packet_callback_expired_pending_count": int(report.get("current_packet_callback_expired_pending_count") or 0),
        "current_packet_callback_stale_pending_count": int(report.get("current_packet_callback_stale_pending_count") or 0),
        "current_packet_callback_recorded_count": int(report.get("current_packet_callback_recorded_count") or 0),
        "current_packet_callback_expired_count": int(report.get("current_packet_callback_expired_count") or 0),
        "current_packet_callback_superseded_count": int(report.get("current_packet_callback_superseded_count") or 0),
        "current_packet_live_callback_record_count": int(report.get("current_packet_live_callback_record_count") or 0),
        "current_packet_live_pending_count": current_packet_live_pending_count,
        "current_packet_callback_latest_status": str(report.get("current_packet_callback_latest_status") or "").strip(),
        "current_packet_callback_latest_expired": bool(report.get("current_packet_callback_latest_expired")),
        "current_packet_callback_latest_created_at": str(report.get("current_packet_callback_latest_created_at") or "").strip(),
        "current_packet_callback_latest_expires_at": str(report.get("current_packet_callback_latest_expires_at") or "").strip(),
        "current_packet_callback_latest_age_seconds": int(report.get("current_packet_callback_latest_age_seconds") or 0),
        "current_packet_callback_latest_seconds_until_expiry": int(
            report.get("current_packet_callback_latest_seconds_until_expiry") or 0
        ),
    }
