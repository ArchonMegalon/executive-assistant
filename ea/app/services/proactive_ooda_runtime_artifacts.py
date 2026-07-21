from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from app.services.proactive_ooda_approval_outcomes import default_proactive_ooda_approval_outcome_path
from app.services.proactive_ooda_flat_search_policy import (
    material_mentions_flat_property_search,
    proactive_ooda_flat_search_enabled,
)
from app.services.proactive_ooda_safe_work import (
    default_safe_work_result_dir,
    safe_work_decision_materiality_issue,
)
from app.services.proactive_ooda_stage_packets import default_stage_packet_dir
from app.services.proactive_ooda_telegram_policy import approval_request_needs_telegram_user_action


RUN_RECEIPT_FILENAME = "proactive_ooda_latest_run.generated.json"
RUN_RECEIPT_DIRNAME = "proactive_ooda_run_receipts"
LEGACY_RUN_RECEIPT_FILENAMES = (
    "proactive_ooda_live_sent_receipt.json",
    "proactive_ooda_live_proof_receipt.json",
    "proactive_ooda_dry_receipt.json",
)
STAGE_PACKET_SCHEMA = "proactive_ooda.stage_packet.v1"
SAFE_WORK_RESULT_SCHEMA = "proactive_ooda.safe_work_result.v1"
_APPROVAL_CALLBACK_DECISION_STATUSES = {"approved", "rejected", "deferred", "dismissed"}
_APPROVAL_CALLBACK_TERMINAL_STATUSES = {*_APPROVAL_CALLBACK_DECISION_STATUSES, "expired", "superseded"}
_ASSISTANT_GRADE_BLOCKING_WORK_TYPES = {"record_internal_action", "internal_action", "operator_action"}


def default_proactive_ooda_runtime_root() -> Path:
    configured = str(os.getenv("EA_PROACTIVE_OODA_RUNTIME_ROOT") or "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path(__file__).resolve().parents[3]


def default_run_receipt_path(*, root: Path, state_path: str | Path) -> Path:
    path = Path(state_path)
    if not path.is_absolute():
        path = root / path
    return path.parent / RUN_RECEIPT_FILENAME


def default_run_receipt_dir(*, root: Path, state_path: str | Path, receipt_path: str | Path = "") -> Path:
    resolved_receipt_path = _path_from_value(
        root,
        receipt_path,
        default=default_run_receipt_path(root=root, state_path=state_path),
    )
    assert resolved_receipt_path is not None
    artifact_root = _artifact_root_from_run_receipt_path(resolved_receipt_path)
    return artifact_root / RUN_RECEIPT_DIRNAME


def resolve_runtime_artifact_paths(
    *,
    root: Path,
    state_path: str | Path,
    receipt_path: str | Path = "",
    stage_packet_dir: str | Path = "",
    safe_work_result_dir: str | Path = "",
) -> dict[str, Path]:
    resolved_stage_dir = _path_from_value(
        root,
        stage_packet_dir,
        default=default_stage_packet_dir(root=root, state_path=state_path),
    )
    resolved_safe_dir = _path_from_value(
        root,
        safe_work_result_dir,
        default=default_safe_work_result_dir(resolved_stage_dir),
    )
    resolved_receipt_path = _path_from_value(
        root,
        receipt_path,
        default=default_run_receipt_path(root=root, state_path=state_path),
    )
    resolved_run_receipt_dir = default_run_receipt_dir(
        root=root,
        state_path=state_path,
        receipt_path=resolved_receipt_path,
    )
    resolved_approval_outcome_path = default_proactive_ooda_approval_outcome_path(
        root=root,
        state_path=state_path,
        receipt_path=resolved_receipt_path,
    )
    resolved_approval_callback_dir = resolved_approval_outcome_path.parent / "proactive_ooda_approval_callbacks"
    return {
        "run_receipt_path": resolved_receipt_path,
        "run_receipt_dir": resolved_run_receipt_dir,
        "stage_packet_dir": resolved_stage_dir,
        "safe_work_result_dir": resolved_safe_dir,
        "approval_outcome_path": resolved_approval_outcome_path,
        "approval_callback_dir": resolved_approval_callback_dir,
    }


def _artifact_root_from_run_receipt_path(path: Path) -> Path:
    if path.parent.name == RUN_RECEIPT_DIRNAME:
        return path.parent.parent
    return path.parent


def _receipt_generated_at_timestamp(payload: Mapping[str, Any]) -> float:
    text = str(payload.get("generated_at") or "").strip()
    if not text:
        return 0.0
    normalized = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized).timestamp()
    except ValueError:
        return 0.0


def _overlay_current_source_health(
    *,
    primary_run_receipt_path: Path | None,
    primary_run_receipt: dict[str, Any],
    run_receipt_path: Path | None,
    run_receipt: dict[str, Any],
) -> dict[str, Any]:
    if not primary_run_receipt or primary_run_receipt_path is None:
        return run_receipt
    if run_receipt_path == primary_run_receipt_path:
        return run_receipt
    if "source_health" not in primary_run_receipt:
        return run_receipt
    if _receipt_generated_at_timestamp(primary_run_receipt) <= _receipt_generated_at_timestamp(run_receipt):
        return run_receipt
    merged = dict(run_receipt)
    merged["source_health"] = dict(primary_run_receipt.get("source_health") or {})
    return merged


def load_runtime_artifact_bundle(
    *,
    root: Path,
    state_path: str | Path,
    receipt_path: str | Path = "",
    stage_packet_dir: str | Path = "",
    safe_work_result_dir: str | Path = "",
    prefer_browse_backed_delivery: bool = False,
) -> dict[str, Any]:
    paths = resolve_runtime_artifact_paths(
        root=root,
        state_path=state_path,
        receipt_path=receipt_path,
        stage_packet_dir=stage_packet_dir,
        safe_work_result_dir=safe_work_result_dir,
    )
    primary_run_receipt_path = paths["run_receipt_path"]
    primary_run_receipt = _load_json(primary_run_receipt_path)
    run_receipt_dir = paths["run_receipt_dir"]
    resolved_stage_dir = paths["stage_packet_dir"]
    resolved_safe_dir = paths["safe_work_result_dir"]
    approval_outcome_path = paths["approval_outcome_path"]
    approval_callback_dir = paths["approval_callback_dir"]
    approval_outcome = _load_json(approval_outcome_path)
    selected_artifact_candidate = None
    if prefer_browse_backed_delivery:
        selected_artifact_candidate = choose_best_run_receipt_artifact_candidate(
            root=root,
            primary_run_receipt_path=primary_run_receipt_path,
            primary_run_receipt=primary_run_receipt,
            run_receipt_dir=run_receipt_dir,
            default_stage_packet_dir=resolved_stage_dir,
            default_safe_work_result_dir=resolved_safe_dir,
            explicit_stage_packet_dir=bool(stage_packet_dir),
            explicit_safe_work_result_dir=bool(safe_work_result_dir),
        )

    if selected_artifact_candidate is not None:
        (
            _run_receipt_path_for_artifacts,
            run_receipt_for_artifacts,
            resolved_stage_dir,
            resolved_safe_dir,
            stage_packet_path,
            stage_packet,
            safe_work_result_path,
            safe_work_result,
        ) = selected_artifact_candidate
    else:
        _, run_receipt_for_artifacts = choose_best_run_receipt_for_artifact_selection(
            primary_run_receipt_path=primary_run_receipt_path,
            primary_run_receipt=primary_run_receipt,
            run_receipt_dir=run_receipt_dir,
        )
        run_stage_dir = _path_from_value(
            root,
            str(
                run_receipt_for_artifacts.get("stage_packet_output_dir")
                or primary_run_receipt.get("stage_packet_output_dir")
                or ""
            ),
        )
        run_safe_dir = _path_from_value(
            root,
            str(
                run_receipt_for_artifacts.get("safe_work_result_output_dir")
                or primary_run_receipt.get("safe_work_result_output_dir")
                or ""
            ),
        )
        if run_stage_dir is not None and not stage_packet_dir:
            resolved_stage_dir = run_stage_dir
        if run_safe_dir is not None and not safe_work_result_dir:
            resolved_safe_dir = run_safe_dir
        preferred_pair = choose_stage_and_safe_work_for_run_receipt(
            stage_packet_dir=resolved_stage_dir,
            safe_work_result_dir=resolved_safe_dir,
            run_receipt=run_receipt_for_artifacts,
        )
        if preferred_pair is None:
            stage_packet_path, stage_packet, safe_work_result_path, safe_work_result = choose_stage_and_safe_work(
                stage_packet_dir=resolved_stage_dir,
                safe_work_result_dir=resolved_safe_dir,
            )
        else:
            stage_packet_path, stage_packet, safe_work_result_path, safe_work_result = preferred_pair
    artifact_filter_reason = ""
    if _artifacts_are_disabled_flat_search(stage_packet=stage_packet, safe_work_result=safe_work_result):
        artifact_filter_reason = "flat_search_disabled_property_scout"
        stage_packet_path, stage_packet, safe_work_result_path, safe_work_result = None, {}, None, {}
    else:
        materiality_issue = _artifact_materiality_filter_reason(
            stage_packet=stage_packet,
            safe_work_result=safe_work_result,
        )
        if materiality_issue:
            artifact_filter_reason = materiality_issue
            stage_packet_path, stage_packet, safe_work_result_path, safe_work_result = None, {}, None, {}
    selected_approval = select_current_approval_outcome_for_bundle(
        {
            "stage_packet": stage_packet,
            "safe_work_result": safe_work_result,
            "approval_outcome": approval_outcome,
        }
    )
    if not current_packet_user_approval_surface(stage_packet=stage_packet, safe_work_result=safe_work_result) and not dict(
        selected_approval.get("approval_outcome") or {}
    ):
        pending_candidate = choose_best_pending_approval_artifact_candidate(
            root=root,
            primary_run_receipt_path=primary_run_receipt_path,
            primary_run_receipt=primary_run_receipt,
            run_receipt_dir=run_receipt_dir,
            default_stage_packet_dir=resolved_stage_dir,
            default_safe_work_result_dir=resolved_safe_dir,
            explicit_stage_packet_dir=bool(stage_packet_dir),
            explicit_safe_work_result_dir=bool(safe_work_result_dir),
            approval_outcome=approval_outcome,
            approval_callback_dir=approval_callback_dir,
        )
        if pending_candidate is not None:
            (
                _run_receipt_path_for_artifacts,
                _run_receipt_for_artifacts,
                resolved_stage_dir,
                resolved_safe_dir,
                stage_packet_path,
                stage_packet,
                safe_work_result_path,
                safe_work_result,
            ) = pending_candidate
            artifact_filter_reason = ""
    run_receipt_path, run_receipt = choose_run_receipt(
        primary_run_receipt_path=primary_run_receipt_path,
        primary_run_receipt=primary_run_receipt,
        run_receipt_dir=run_receipt_dir,
        stage_packet=stage_packet,
        safe_work_result=safe_work_result,
    )
    run_receipt = _overlay_current_source_health(
        primary_run_receipt_path=primary_run_receipt_path,
        primary_run_receipt=primary_run_receipt,
        run_receipt_path=run_receipt_path,
        run_receipt=run_receipt,
    )
    callback_summary = approval_callback_runtime_summary(
        approval_callback_dir=approval_callback_dir,
        stage_packet=stage_packet,
        safe_work_result=safe_work_result,
        stage_packet_dir=resolved_stage_dir,
        safe_work_result_dir=resolved_safe_dir,
    )
    quiet_receipt_path, quiet_receipt = choose_action_required_only_quiet_receipt(
        primary_run_receipt_path=primary_run_receipt_path,
        primary_run_receipt=primary_run_receipt,
        run_receipt_dir=run_receipt_dir,
        stage_packet_dir=resolved_stage_dir,
        safe_work_result_dir=resolved_safe_dir,
    )
    return {
        "state_path": _path_from_value(root, state_path),
        "run_receipt_path": run_receipt_path,
        "run_receipt_dir": run_receipt_dir,
        "run_receipt": run_receipt,
        "action_required_only_quiet_receipt_path": quiet_receipt_path,
        "action_required_only_quiet_receipt": quiet_receipt,
        "stage_packet_dir": resolved_stage_dir,
        "safe_work_result_dir": resolved_safe_dir,
        "stage_packet_path": stage_packet_path,
        "stage_packet": stage_packet,
        "safe_work_result_path": safe_work_result_path,
        "safe_work_result": safe_work_result,
        "artifact_filter_reason": artifact_filter_reason,
        "flat_search_enabled": _flat_search_enabled(),
        "approval_outcome_path": approval_outcome_path,
        "approval_outcome": approval_outcome,
        "approval_callback_dir": approval_callback_dir,
        **callback_summary,
    }


def choose_best_run_receipt_for_artifact_selection(
    *,
    primary_run_receipt_path: Path | None,
    primary_run_receipt: dict[str, Any],
    run_receipt_dir: Path,
) -> tuple[Path | None, dict[str, Any]]:
    best = _best_run_receipt_candidate(
        _run_receipt_candidates(
            primary_run_receipt_path=primary_run_receipt_path,
            primary_run_receipt=primary_run_receipt,
            run_receipt_dir=run_receipt_dir,
        )
    )
    if best is None:
        return primary_run_receipt_path, primary_run_receipt
    return best[0], best[1]


def choose_best_run_receipt_artifact_candidate(
    *,
    root: Path,
    primary_run_receipt_path: Path | None,
    primary_run_receipt: dict[str, Any],
    run_receipt_dir: Path,
    default_stage_packet_dir: Path,
    default_safe_work_result_dir: Path,
    explicit_stage_packet_dir: bool,
    explicit_safe_work_result_dir: bool,
) -> tuple[Path | None, dict[str, Any], Path, Path, Path | None, dict[str, Any], Path | None, dict[str, Any]] | None:
    best: tuple[
        Path | None,
        dict[str, Any],
        Path,
        Path,
        Path | None,
        dict[str, Any],
        Path | None,
        dict[str, Any],
    ] | None = None
    best_score: tuple[int, int, int, int, int, int, int, float, int, int] | None = None
    for path, payload, mtime in _run_receipt_candidates(
        primary_run_receipt_path=primary_run_receipt_path,
        primary_run_receipt=primary_run_receipt,
        run_receipt_dir=run_receipt_dir,
    ):
        stage_dir = default_stage_packet_dir
        safe_dir = default_safe_work_result_dir
        if not explicit_stage_packet_dir:
            stage_dir = (
                _path_from_value(root, str(payload.get("stage_packet_output_dir") or ""))
                or default_stage_packet_dir
            )
        if not explicit_safe_work_result_dir:
            safe_dir = (
                _path_from_value(root, str(payload.get("safe_work_result_output_dir") or ""))
                or default_safe_work_result_dir
            )
        preferred_pair = choose_stage_and_safe_work_for_run_receipt(
            stage_packet_dir=stage_dir,
            safe_work_result_dir=safe_dir,
            run_receipt=payload,
        )
        if preferred_pair is None:
            continue
        stage_path, stage_packet, safe_path, safe_work_result = preferred_pair
        if _artifacts_are_disabled_flat_search(stage_packet=stage_packet, safe_work_result=safe_work_result):
            continue
        if _artifact_materiality_filter_reason(stage_packet=stage_packet, safe_work_result=safe_work_result):
            continue

        notification_status = str(payload.get("notification_status") or "").strip().lower()
        message_count = _message_id_count(payload)
        item_count = int(payload.get("item_count") or 0)
        operator_safe_mirror = _receipt_proves_operator_safe_mirror(payload)
        delivery_proof = (
            notification_status == "sent" and item_count > 0 and message_count > 0
        ) or operator_safe_mirror
        teable_sync = dict(payload.get("teable_sync") or {})
        artifact_score = _stage_safe_pair_score(stage_packet, safe_work_result, mtime)
        assistant_grade_score = _assistant_grade_pair_score(stage_packet, safe_work_result)
        score = (
            assistant_grade_score,
            1 if delivery_proof else 0,
            artifact_score[0],
            artifact_score[1],
            artifact_score[2],
            1 if item_count > 0 else 0,
            1 if str(teable_sync.get("status") or "").strip() in {"synced", "partial"} else 0,
            1 if operator_safe_mirror else 0,
            mtime,
            1 if notification_status == "sent" else 0,
            message_count,
        )
        if best_score is None or score > best_score:
            best = (path, payload, stage_dir, safe_dir, stage_path, stage_packet, safe_path, safe_work_result)
            best_score = score
    return best


def choose_best_pending_approval_artifact_candidate(
    *,
    root: Path,
    primary_run_receipt_path: Path | None,
    primary_run_receipt: dict[str, Any],
    run_receipt_dir: Path,
    default_stage_packet_dir: Path,
    default_safe_work_result_dir: Path,
    explicit_stage_packet_dir: bool,
    explicit_safe_work_result_dir: bool,
    approval_outcome: Mapping[str, Any],
    approval_callback_dir: Path,
) -> tuple[Path | None, dict[str, Any], Path, Path, Path | None, dict[str, Any], Path | None, dict[str, Any]] | None:
    best: tuple[
        Path | None,
        dict[str, Any],
        Path,
        Path,
        Path | None,
        dict[str, Any],
        Path | None,
        dict[str, Any],
    ] | None = None
    best_score: tuple[int, int, int, int, int, int, int, float, int, int] | None = None
    for path, payload, mtime in _run_receipt_candidates(
        primary_run_receipt_path=primary_run_receipt_path,
        primary_run_receipt=primary_run_receipt,
        run_receipt_dir=run_receipt_dir,
    ):
        stage_dir = default_stage_packet_dir
        safe_dir = default_safe_work_result_dir
        if not explicit_stage_packet_dir:
            stage_dir = _path_from_value(root, str(payload.get("stage_packet_output_dir") or "")) or default_stage_packet_dir
        if not explicit_safe_work_result_dir:
            safe_dir = _path_from_value(root, str(payload.get("safe_work_result_output_dir") or "")) or default_safe_work_result_dir
        preferred_pair = choose_stage_and_safe_work_for_run_receipt(
            stage_packet_dir=stage_dir,
            safe_work_result_dir=safe_dir,
            run_receipt=payload,
        )
        if preferred_pair is None:
            continue
        stage_path, stage_packet, safe_path, safe_work_result = preferred_pair
        if _artifacts_are_disabled_flat_search(stage_packet=stage_packet, safe_work_result=safe_work_result):
            continue
        if _artifact_materiality_filter_reason(stage_packet=stage_packet, safe_work_result=safe_work_result):
            continue
        if not current_packet_user_approval_surface(stage_packet=stage_packet, safe_work_result=safe_work_result):
            continue
        callback_summary = approval_callback_runtime_summary(
            approval_callback_dir=approval_callback_dir,
            stage_packet=stage_packet,
            safe_work_result=safe_work_result,
            stage_packet_dir=stage_dir,
            safe_work_result_dir=safe_dir,
        )
        selected_approval = select_current_approval_outcome_for_bundle(
            {
                "stage_packet": stage_packet,
                "safe_work_result": safe_work_result,
                "approval_outcome": dict(approval_outcome or {}),
                "current_packet_callback_outcome": dict(callback_summary.get("current_packet_callback_outcome") or {}),
            }
        )
        if dict(selected_approval.get("approval_outcome") or {}):
            continue
        notification_status = str(payload.get("notification_status") or "").strip().lower()
        message_count = _message_id_count(payload)
        item_count = int(payload.get("item_count") or 0)
        operator_safe_mirror = _receipt_proves_operator_safe_mirror(payload)
        delivery_proof = (
            notification_status == "sent" and item_count > 0 and message_count > 0
        ) or operator_safe_mirror
        teable_sync = dict(payload.get("teable_sync") or {})
        artifact_score = _stage_safe_pair_score(stage_packet, safe_work_result, mtime)
        assistant_grade_score = _assistant_grade_pair_score(stage_packet, safe_work_result)
        live_pending_count = int(callback_summary.get("current_packet_live_pending_count") or 0)
        score = (
            1 if live_pending_count > 0 else 0,
            assistant_grade_score,
            1 if delivery_proof else 0,
            artifact_score[0],
            artifact_score[1],
            artifact_score[2],
            1 if item_count > 0 else 0,
            1 if str(teable_sync.get("status") or "").strip() in {"synced", "partial"} else 0,
            mtime,
            1 if notification_status == "sent" else 0,
            message_count,
        )
        if best_score is None or score > best_score:
            best = (path, payload, stage_dir, safe_dir, stage_path, stage_packet, safe_path, safe_work_result)
            best_score = score
    return best


def choose_action_required_only_quiet_receipt(
    *,
    primary_run_receipt_path: Path | None,
    primary_run_receipt: dict[str, Any],
    run_receipt_dir: Path,
    stage_packet_dir: Path,
    safe_work_result_dir: Path,
) -> tuple[Path | None, dict[str, Any]]:
    best: tuple[Path | None, dict[str, Any], float] | None = None
    best_score: tuple[int, int, float] | None = None
    for path, payload, mtime in _run_receipt_candidates(
        primary_run_receipt_path=primary_run_receipt_path,
        primary_run_receipt=primary_run_receipt,
        run_receipt_dir=run_receipt_dir,
    ):
        if not _receipt_proves_action_required_only_quiet_delivery(payload):
            continue
        if _quiet_receipt_is_property_scoped(
            payload,
            stage_packet_dir=stage_packet_dir,
            safe_work_result_dir=safe_work_result_dir,
        ):
            continue
        stage_hash_count = len(_run_receipt_ref_hash_sets(payload)[0])
        score = (
            1 if stage_hash_count > 0 else 0,
            int(payload.get("item_count") or 0),
            mtime,
        )
        if best_score is None or score > best_score:
            best = (path, payload, mtime)
            best_score = score
    if best is None:
        return None, {}
    return best[0], best[1]


def _quiet_receipt_is_property_scoped(
    payload: Mapping[str, Any],
    *,
    stage_packet_dir: Path,
    safe_work_result_dir: Path,
) -> bool:
    preferred_pair = choose_stage_and_safe_work_for_run_receipt(
        stage_packet_dir=stage_packet_dir,
        safe_work_result_dir=safe_work_result_dir,
        run_receipt=payload,
    )
    if preferred_pair is not None:
        _stage_path, stage_packet, _safe_path, safe_work_result = preferred_pair
        if _artifacts_are_disabled_flat_search(
            stage_packet=stage_packet,
            safe_work_result=safe_work_result,
        ):
            return True

    projection_summary = dict(dict(payload.get("teable_sync") or {}).get("projection_summary") or {})
    reasons = {
        str(item or "").strip()
        for item in list(projection_summary.get("suppressed_projection_reasons") or [])
        if str(item or "").strip()
    }
    issue_codes = {
        str(item or "").strip()
        for item in list(projection_summary.get("suppressed_safe_work_issue_codes") or [])
        if str(item or "").strip()
    }
    property_reasons = {"flat_search_disabled", "flat_search_disabled_property_scout"}
    return bool((reasons | issue_codes) & property_reasons)


def _receipt_proves_action_required_only_quiet_delivery(payload: Mapping[str, Any]) -> bool:
    if not payload:
        return False
    if bool(payload.get("dry_run")):
        return False
    if str(payload.get("notification_status") or "").strip().lower() != "deferred":
        return False
    if str(payload.get("error_code") or "").strip() != "no_user_action_required":
        return False
    if int(payload.get("item_count") or 0) <= 0:
        return False
    return _message_id_count(dict(payload)) == 0


def _flat_search_enabled() -> bool:
    return proactive_ooda_flat_search_enabled()


def _artifacts_are_disabled_flat_search(
    *,
    stage_packet: Mapping[str, Any],
    safe_work_result: Mapping[str, Any],
) -> bool:
    return material_mentions_flat_property_search(
        {
            "stage_packet": dict(stage_packet or {}),
            "safe_work_result": dict(safe_work_result or {}),
        }
    )


def _artifact_materiality_filter_reason(
    *,
    stage_packet: Mapping[str, Any],
    safe_work_result: Mapping[str, Any],
) -> str:
    return safe_work_decision_materiality_issue(
        stage_packet=stage_packet,
        safe_work_result=safe_work_result,
    )


def approval_outcome_matches_current_artifacts(
    approval_outcome: Mapping[str, Any],
    *,
    stage_packet: Mapping[str, Any],
    safe_work_result: Mapping[str, Any],
) -> bool:
    outcome = dict(approval_outcome or {})
    if not bool(outcome.get("approval_outcome_recorded")):
        return False
    packet_hash = str(outcome.get("packet_ref_sha256") or "").strip()
    staged_artifact_hash = str(
        outcome.get("staged_artifact_sha256")
        or outcome.get("staged_artifact_ref_sha256")
        or ""
    ).strip()
    return bool(
        packet_hash
        and staged_artifact_hash
        and packet_hash == _packet_ref_hash(dict(stage_packet or {}))
        and staged_artifact_hash == _safe_work_result_ref_hash(dict(safe_work_result or {}))
    )


def select_current_approval_outcome_for_bundle(bundle: Mapping[str, Any]) -> dict[str, Any]:
    runtime_bundle = dict(bundle or {})
    stage_packet = dict(runtime_bundle.get("stage_packet") or {})
    safe_work_result = dict(runtime_bundle.get("safe_work_result") or {})
    callback_outcome = dict(runtime_bundle.get("current_packet_callback_outcome") or {})
    file_outcome = dict(runtime_bundle.get("approval_outcome") or {})
    if approval_outcome_matches_current_artifacts(
        callback_outcome,
        stage_packet=stage_packet,
        safe_work_result=safe_work_result,
    ):
        return {
            "approval_outcome": callback_outcome,
            "source": "current_packet_callback",
            "stale_saved_approval_outcome_present": False,
        }
    if approval_outcome_matches_current_artifacts(
        file_outcome,
        stage_packet=stage_packet,
        safe_work_result=safe_work_result,
    ):
        return {
            "approval_outcome": file_outcome,
            "source": "approval_outcome_artifact",
            "stale_saved_approval_outcome_present": False,
        }
    return {
        "approval_outcome": {},
        "source": "",
        "stale_saved_approval_outcome_present": bool(file_outcome.get("approval_outcome_recorded")),
    }


def approval_callback_runtime_summary(
    *,
    approval_callback_dir: Path,
    stage_packet: Mapping[str, Any],
    safe_work_result: Mapping[str, Any],
    stage_packet_dir: Path | None = None,
    safe_work_result_dir: Path | None = None,
) -> dict[str, Any]:
    callback_rows = _approval_callback_rows(approval_callback_dir)
    callback_artifact_refs = _approval_callback_artifact_ref_index(
        callback_rows,
        stage_packet_dir=stage_packet_dir,
        safe_work_result_dir=safe_work_result_dir,
    )
    current_packet_rows = _matching_approval_callback_rows(
        callback_rows,
        stage_packet=stage_packet,
        safe_work_result=safe_work_result,
    )
    latest_current_packet = current_packet_rows[-1] if current_packet_rows else {}
    pending_rows = [row for row in callback_rows if _approval_callback_status(row) == "pending"]
    expired_pending_rows = [row for row in pending_rows if _approval_callback_expired(row)]
    unexpired_pending_rows = [row for row in pending_rows if not _approval_callback_expired(row)]
    recorded_rows = [row for row in callback_rows if _approval_callback_status(row) in _APPROVAL_CALLBACK_DECISION_STATUSES]
    expired_rows = [row for row in callback_rows if _approval_callback_status(row) == "expired"]
    superseded_rows = [row for row in callback_rows if _approval_callback_status(row) == "superseded"]
    terminal_rows = [row for row in callback_rows if _approval_callback_status(row) in _APPROVAL_CALLBACK_TERMINAL_STATUSES]
    current_pending_rows = [row for row in current_packet_rows if _approval_callback_status(row) == "pending"]
    current_expired_pending_rows = [row for row in current_pending_rows if _approval_callback_expired(row)]
    current_expired_rows = [row for row in current_packet_rows if _approval_callback_status(row) == "expired"]
    current_superseded_rows = [row for row in current_packet_rows if _approval_callback_status(row) == "superseded"]
    current_decision_rows = [
        row for row in current_packet_rows if _approval_callback_status(row) in _APPROVAL_CALLBACK_DECISION_STATUSES
    ]
    noncurrent_pending_rows = [row for row in pending_rows if not _approval_callback_matches_current(row, current_packet_rows)]
    live_current_packet_rows = [row for row in current_packet_rows if not _approval_callback_expired(row)]
    live_pending_current_packet_rows = [
        row
        for row in current_packet_rows
        if _approval_callback_status(row) == "pending" and not _approval_callback_expired(row)
    ]
    property_scoped_pending_rows = [
        row
        for row in pending_rows
        if _approval_callback_is_property_scoped(
            row,
            callback_artifact_refs=callback_artifact_refs,
        )
    ]
    latest_created_at = str(latest_current_packet.get("created_at") or "").strip()
    latest_expires_at = str(latest_current_packet.get("expires_at") or "").strip()
    stale_pending_rows = [
        row
        for row in pending_rows
        if _approval_callback_expired(row) or not _approval_callback_matches_current(row, current_packet_rows)
    ]
    stale_property_scoped_pending_rows = [
        row
        for row in property_scoped_pending_rows
        if _approval_callback_expired(row) or not _approval_callback_matches_current(row, current_packet_rows)
    ]
    return {
        "approval_callback_dir_exists": _safe_is_dir(approval_callback_dir),
        "approval_callback_dir_writable": _dir_writable(approval_callback_dir),
        "approval_callback_record_count": len(callback_rows),
        "approval_callback_pending_count": len(live_pending_current_packet_rows),
        "approval_callback_raw_pending_count": len(pending_rows),
        "approval_callback_live_pending_count": len(live_pending_current_packet_rows),
        "approval_callback_unexpired_pending_count": len(unexpired_pending_rows),
        "approval_callback_noncurrent_pending_count": len(noncurrent_pending_rows),
        "approval_callback_expired_pending_count": len(expired_pending_rows),
        "approval_callback_stale_pending_count": len(stale_pending_rows),
        "approval_callback_property_scoped_pending_count": len(property_scoped_pending_rows),
        "approval_callback_stale_property_pending_count": len(stale_property_scoped_pending_rows),
        "approval_callback_recorded_count": len(recorded_rows),
        "approval_callback_expired_count": len(expired_rows),
        "approval_callback_superseded_count": len(superseded_rows),
        "approval_callback_terminal_count": len(terminal_rows),
        "current_packet_callback_record_count": len(current_packet_rows),
        "current_packet_callback_pending_count": len(current_pending_rows),
        "current_packet_callback_raw_pending_count": len(current_pending_rows),
        "current_packet_callback_expired_pending_count": len(current_expired_pending_rows),
        "current_packet_callback_stale_pending_count": len(current_expired_pending_rows),
        "current_packet_callback_recorded_count": len(current_decision_rows),
        "current_packet_callback_expired_count": len(current_expired_rows),
        "current_packet_callback_superseded_count": len(current_superseded_rows),
        "current_packet_live_callback_record_count": len(live_current_packet_rows),
        "current_packet_live_pending_count": len(live_pending_current_packet_rows),
        "current_packet_callback_latest_status": str(latest_current_packet.get("status") or "").strip(),
        "current_packet_callback_latest_expired": bool(latest_current_packet) and _approval_callback_expired(latest_current_packet),
        "current_packet_callback_latest_created_at": latest_created_at,
        "current_packet_callback_latest_expires_at": latest_expires_at,
        "current_packet_callback_latest_age_seconds": _age_seconds(latest_created_at),
        "current_packet_callback_latest_seconds_until_expiry": _seconds_until(latest_expires_at),
        "current_packet_callback_outcome": _approval_callback_outcome_row(
            current_decision_rows[-1] if current_decision_rows else {},
        ),
    }


def current_packet_user_approval_surface(
    *,
    stage_packet: Mapping[str, Any],
    safe_work_result: Mapping[str, Any],
) -> bool:
    packet_ref = _stage_packet_ref(stage_packet)
    staged_artifact_ref = _safe_work_result_ref(safe_work_result)
    if not packet_ref or not staged_artifact_ref:
        return False
    if str(safe_work_result.get("status") or "").strip() != "staged_for_user_decision":
        return False
    stage_approval = dict(stage_packet.get("approval") or {})
    safe_work_approval = dict(safe_work_result.get("approval") or {})
    if not (bool(stage_approval.get("required")) or bool(safe_work_approval.get("required"))):
        return False
    stage = dict(stage_packet.get("stage") or {})
    payload = dict(stage.get("payload") or {})
    approval_request = {
        "packet_ref": packet_ref,
        "staged_artifact_ref": staged_artifact_ref,
        "approval_prompt": str(safe_work_result.get("approval_prompt") or "").strip(),
        "staged_action_url": str(safe_work_result.get("staged_action_url") or "").strip(),
        "approved_execution_mode": str(payload.get("approved_execution_mode") or "").strip(),
        "approved_action": str(payload.get("approved_action") or "").strip(),
        "work_type": _approval_request_work_type(stage_packet=stage_packet, safe_work_result=safe_work_result),
    }
    return approval_request_needs_telegram_user_action(approval_request)


def _approval_request_work_type(
    *,
    stage_packet: Mapping[str, Any],
    safe_work_result: Mapping[str, Any],
) -> str:
    stage = dict(stage_packet.get("stage") or {})
    payload = dict(stage.get("payload") or {})
    safe_work_order = dict(stage_packet.get("safe_work_order") or {})
    for value in (
        safe_work_result.get("work_type"),
        safe_work_order.get("work_type"),
        payload.get("work_type"),
    ):
        text = str(value or "").strip().lower()
        if text:
            return text
    return ""


def _approval_callback_artifact_ref_index(
    rows: list[dict[str, Any]],
    *,
    stage_packet_dir: Path | None,
    safe_work_result_dir: Path | None,
) -> dict[str, dict[str, Any]]:
    requested_refs: set[str] = set()
    for row in rows:
        packet_ref = str(row.get("packet_ref") or "").strip()
        if packet_ref:
            requested_refs.add(packet_ref)
        staged_artifact_ref = str(row.get("staged_artifact_ref") or "").strip()
        if staged_artifact_ref:
            requested_refs.add(staged_artifact_ref)
    if not requested_refs:
        return {}

    artifact_payloads: dict[str, dict[str, Any]] = {}
    if stage_packet_dir is not None and _safe_is_dir(stage_packet_dir):
        for _, payload, _ in latest_payloads(stage_packet_dir, schema=STAGE_PACKET_SCHEMA):
            payload_packet_ref = str(payload.get("packet_ref") or "").strip()
            if payload_packet_ref and payload_packet_ref in requested_refs:
                artifact_payloads[payload_packet_ref] = payload
            payload_packet_id = str(payload.get("packet_id") or "").strip()
            if payload_packet_id and f"stage_packet:{payload_packet_id}" in requested_refs:
                artifact_payloads[f"stage_packet:{payload_packet_id}"] = payload

    if safe_work_result_dir is not None and _safe_is_dir(safe_work_result_dir):
        for _, payload, _ in latest_payloads(safe_work_result_dir, schema=SAFE_WORK_RESULT_SCHEMA):
            payload_artifact_ref = str(payload.get("result_ref") or "").strip()
            if payload_artifact_ref and payload_artifact_ref in requested_refs:
                artifact_payloads[payload_artifact_ref] = payload
            payload_result_id = str(payload.get("result_id") or "").strip()
            if payload_result_id and f"safe_work_result:{payload_result_id}" in requested_refs:
                artifact_payloads[f"safe_work_result:{payload_result_id}"] = payload

    return artifact_payloads


def _approval_callback_is_property_scoped(
    row: Mapping[str, Any],
    *,
    callback_artifact_refs: Mapping[str, Mapping[str, Any]],
) -> bool:
    if material_mentions_flat_property_search(row):
        return True
    packet_ref = str(row.get("packet_ref") or "").strip()
    if packet_ref and packet_ref in callback_artifact_refs:
        if material_mentions_flat_property_search(callback_artifact_refs[packet_ref]):
            return True
    staged_artifact_ref = str(row.get("staged_artifact_ref") or "").strip()
    if staged_artifact_ref and staged_artifact_ref in callback_artifact_refs:
        if material_mentions_flat_property_search(callback_artifact_refs[staged_artifact_ref]):
            return True
    return False


def choose_stage_and_safe_work(
    *,
    stage_packet_dir: Path,
    safe_work_result_dir: Path,
) -> tuple[Path | None, dict[str, Any], Path | None, dict[str, Any]]:
    stage_packets = latest_payloads(stage_packet_dir, schema=STAGE_PACKET_SCHEMA)
    safe_work_results = latest_payloads(safe_work_result_dir, schema=SAFE_WORK_RESULT_SCHEMA)
    stage_by_hash = {_packet_ref_hash(payload): (path, payload) for path, payload, _mtime in stage_packets}

    best_score: tuple[int, int, int, float] | None = None
    best_pair: tuple[Path | None, dict[str, Any], Path | None, dict[str, Any]] | None = None
    for safe_path, safe_payload, safe_mtime in safe_work_results:
        stage_path: Path | None = None
        stage_payload: dict[str, Any] = {}
        packet_hash = str(safe_payload.get("source_packet_ref_hash") or "").strip()
        if packet_hash and packet_hash in stage_by_hash:
            stage_path, stage_payload = stage_by_hash[packet_hash]
        score = _stage_safe_pair_score(stage_payload, safe_payload, safe_mtime)
        if best_score is None or score > best_score:
            best_score = score
            best_pair = (stage_path, stage_payload, safe_path, safe_payload)
    if best_pair is not None:
        return best_pair
    if stage_packets:
        stage_path, stage_payload, _mtime = stage_packets[0]
        return stage_path, stage_payload, None, {}
    return None, {}, None, {}


def choose_stage_and_safe_work_for_run_receipt(
    *,
    stage_packet_dir: Path,
    safe_work_result_dir: Path,
    run_receipt: Mapping[str, Any],
) -> tuple[Path | None, dict[str, Any], Path | None, dict[str, Any]] | None:
    stage_hashes, safe_hashes = _run_receipt_ref_hash_sets(run_receipt)
    if not stage_hashes or not safe_hashes:
        return None

    stage_packets = latest_payloads(stage_packet_dir, schema=STAGE_PACKET_SCHEMA)
    safe_work_results = latest_payloads(safe_work_result_dir, schema=SAFE_WORK_RESULT_SCHEMA)
    stage_by_hash = {_packet_ref_hash(payload): (path, payload) for path, payload, _mtime in stage_packets}

    best_score: tuple[int, int, int, float] | None = None
    best_pair: tuple[Path | None, dict[str, Any], Path | None, dict[str, Any]] | None = None
    for safe_path, safe_payload, safe_mtime in safe_work_results:
        packet_hash = str(safe_payload.get("source_packet_ref_hash") or "").strip()
        safe_hash = _safe_work_result_ref_hash(safe_payload)
        if not packet_hash or packet_hash not in stage_hashes or safe_hash not in safe_hashes:
            continue
        if packet_hash not in stage_by_hash:
            continue
        stage_path, stage_payload = stage_by_hash[packet_hash]
        score = _stage_safe_pair_score(stage_payload, safe_payload, safe_mtime)
        if best_score is None or score > best_score:
            best_score = score
            best_pair = (stage_path, stage_payload, safe_path, safe_payload)
    return best_pair


def choose_run_receipt(
    *,
    primary_run_receipt_path: Path | None,
    primary_run_receipt: dict[str, Any],
    run_receipt_dir: Path,
    stage_packet: dict[str, Any],
    safe_work_result: dict[str, Any],
) -> tuple[Path | None, dict[str, Any]]:
    if not stage_packet and not safe_work_result:
        if primary_run_receipt:
            return primary_run_receipt_path, primary_run_receipt
        fallback = _best_run_receipt_candidate(
            _run_receipt_candidates(
                primary_run_receipt_path=primary_run_receipt_path,
                primary_run_receipt=primary_run_receipt,
                run_receipt_dir=run_receipt_dir,
            )
        )
        return (fallback[0], fallback[1]) if fallback is not None else (primary_run_receipt_path, primary_run_receipt)

    stage_hash = _packet_ref_hash(stage_packet)
    safe_hash = _safe_work_result_ref_hash(safe_work_result)
    best_match = _best_run_receipt_candidate(
        _run_receipt_candidates(
            primary_run_receipt_path=primary_run_receipt_path,
            primary_run_receipt=primary_run_receipt,
            run_receipt_dir=run_receipt_dir,
        ),
        stage_packet_ref_hash=stage_hash,
        safe_work_result_ref_hash=safe_hash,
    )
    if best_match is not None:
        return best_match[0], best_match[1]
    return primary_run_receipt_path, primary_run_receipt


def display_path(root: Path, path: Path | None) -> str:
    if path is None:
        return ""
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def latest_payloads(path: Path, *, schema: str) -> list[tuple[Path, dict[str, Any], float]]:
    try:
        if not path.is_dir():
            return []
        candidates = list(path.glob("*.json"))
    except OSError:
        return []
    rows: list[tuple[Path, dict[str, Any], float]] = []
    for candidate in candidates:
        payload = _load_json(candidate)
        if not payload or str(payload.get("schema") or "").strip() != schema:
            continue
        try:
            mtime = candidate.stat().st_mtime
        except OSError:
            mtime = 0.0
        rows.append((candidate, payload, mtime))
    rows.sort(key=lambda item: (item[2], item[0].name), reverse=True)
    return rows


def latest_run_receipts(path: Path) -> list[tuple[Path, dict[str, Any], float]]:
    try:
        if not path.is_dir():
            return []
        candidates = list(path.glob("*.json"))
    except OSError:
        return []
    rows: list[tuple[Path, dict[str, Any], float]] = []
    for candidate in candidates:
        payload = _load_json(candidate)
        if not payload:
            continue
        try:
            mtime = candidate.stat().st_mtime
        except OSError:
            mtime = 0.0
        rows.append((candidate, payload, mtime))
    rows.sort(key=lambda item: (item[2], item[0].name), reverse=True)
    return rows


def _path_from_value(root: Path, value: str | Path, *, default: Path | None = None) -> Path | None:
    normalized = str(value or "").strip()
    if not normalized:
        return default
    path = Path(normalized)
    return path if path.is_absolute() else root / path


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _packet_ref_hash(packet: dict[str, Any]) -> str:
    packet_ref = str(packet.get("packet_ref") or packet.get("packet_id") or "").strip()
    return hashlib.sha256(packet_ref.encode("utf-8")).hexdigest() if packet_ref else ""


def _safe_work_result_ref_hash(safe_work_result: dict[str, Any]) -> str:
    result_ref = str(safe_work_result.get("result_ref") or "").strip()
    if not result_ref:
        result_id = str(safe_work_result.get("result_id") or "").strip()
        result_ref = f"safe_work_result:{result_id}" if result_id else ""
    return hashlib.sha256(result_ref.encode("utf-8")).hexdigest() if result_ref else ""


def _run_receipt_candidates(
    *,
    primary_run_receipt_path: Path | None,
    primary_run_receipt: dict[str, Any],
    run_receipt_dir: Path,
) -> list[tuple[Path | None, dict[str, Any], float]]:
    rows: list[tuple[Path | None, dict[str, Any], float]] = []
    seen_paths: set[str] = set()

    def _add(path: Path | None, payload: dict[str, Any], *, mtime: float = 0.0) -> None:
        key = "" if path is None else path.as_posix()
        if key in seen_paths or not payload:
            return
        seen_paths.add(key)
        rows.append((path, payload, mtime))

    if primary_run_receipt_path is not None:
        mtime = 0.0
        try:
            if _safe_exists(primary_run_receipt_path):
                mtime = primary_run_receipt_path.stat().st_mtime
        except OSError:
            mtime = 0.0
        _add(primary_run_receipt_path, primary_run_receipt, mtime=mtime)

    for candidate_path, payload, mtime in latest_run_receipts(run_receipt_dir):
        _add(candidate_path, payload, mtime=mtime)

    state_dir = run_receipt_dir.parent
    for filename in LEGACY_RUN_RECEIPT_FILENAMES:
        candidate_path = state_dir / filename
        try:
            exists = candidate_path.exists()
        except OSError:
            exists = False
        if not exists:
            continue
        _add(candidate_path, _load_json(candidate_path), mtime=_safe_mtime(candidate_path))

    return rows


def _best_run_receipt_candidate(
    candidates: list[tuple[Path | None, dict[str, Any], float]],
    *,
    stage_packet_ref_hash: str = "",
    safe_work_result_ref_hash: str = "",
) -> tuple[Path | None, dict[str, Any], float] | None:
    best: tuple[Path | None, dict[str, Any], float] | None = None
    best_score: tuple[int, int, int, int, float, int, int] | None = None
    require_packet_match = bool(stage_packet_ref_hash and safe_work_result_ref_hash)
    for path, payload, mtime in candidates:
        packet_match = _run_receipt_matches_artifacts(
            payload,
            stage_packet_ref_hash=stage_packet_ref_hash,
            safe_work_result_ref_hash=safe_work_result_ref_hash,
        )
        if require_packet_match and not packet_match:
            continue
        message_count = _message_id_count(payload)
        notification_status = str(payload.get("notification_status") or "").strip().lower()
        item_count = int(payload.get("item_count") or 0)
        teable_sync = dict(payload.get("teable_sync") or {})
        operator_safe_mirror = _receipt_proves_operator_safe_mirror(payload)
        delivery_proof = (
            notification_status == "sent" and item_count > 0 and message_count > 0
        ) or operator_safe_mirror
        score = (
            1 if packet_match else 0,
            1 if delivery_proof else 0,
            1 if item_count > 0 else 0,
            1 if str(teable_sync.get("status") or "").strip() in {"synced", "partial"} else 0,
            mtime,
            1 if operator_safe_mirror else 0,
            1 if notification_status == "sent" else 0,
        )
        if best_score is None or score > best_score:
            best = (path, payload, mtime)
            best_score = score
    return best


def _receipt_proves_operator_safe_mirror(payload: Mapping[str, Any]) -> bool:
    if str(payload.get("notification_status") or "").strip().lower() != "deferred":
        return False
    if str(payload.get("error_code") or "").strip() != "mirrored_delivery_proof":
        return False
    if int(payload.get("item_count") or 0) <= 0:
        return False
    mirror = dict(payload.get("delivery_mirror") or {})
    return bool(
        mirror.get("enabled")
        and str(mirror.get("mode") or "").strip() == "operator_safe_mirror"
        and mirror.get("user_notification_suppressed") is True
        and mirror.get("approval_request_requires_user_action") is True
    )


def _run_receipt_matches_artifacts(
    payload: dict[str, Any],
    *,
    stage_packet_ref_hash: str,
    safe_work_result_ref_hash: str,
) -> bool:
    if not stage_packet_ref_hash or not safe_work_result_ref_hash:
        return False
    stage_hashes, safe_hashes = _run_receipt_ref_hash_sets(payload)
    return stage_packet_ref_hash in stage_hashes and safe_work_result_ref_hash in safe_hashes


def _run_receipt_ref_hash_sets(payload: Mapping[str, Any]) -> tuple[set[str], set[str]]:
    stage_hashes = {str(item or "").strip() for item in list(payload.get("stage_packet_ref_hashes") or []) if str(item or "").strip()}
    safe_hashes = {
        str(item or "").strip()
        for item in list(payload.get("safe_work_result_ref_hashes") or [])
        if str(item or "").strip()
    }
    return stage_hashes, safe_hashes


def _message_id_count(payload: dict[str, Any]) -> int:
    values = payload.get("delivery_message_ids")
    if not isinstance(values, list) or not values:
        values = payload.get("telegram_message_ids")
    if not isinstance(values, list):
        return 0
    return len([item for item in values if str(item or "").strip()])


def _safe_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _approval_callback_rows(path: Path) -> list[dict[str, Any]]:
    if not _safe_is_dir(path):
        return []
    rows: list[dict[str, Any]] = []
    for candidate in sorted(_safe_glob(path, "*.json")):
        payload = _load_json(candidate)
        if payload:
            rows.append(payload)
    rows.sort(key=lambda row: str(row.get("created_at") or ""))
    return rows


def _approval_callback_status(row: Mapping[str, Any]) -> str:
    return str(row.get("status") or "").strip().lower()


def _approval_callback_outcome_row(row: Mapping[str, Any]) -> dict[str, Any]:
    status = _approval_callback_status(row)
    if status not in _APPROVAL_CALLBACK_DECISION_STATUSES:
        return {}
    packet_hash = str(row.get("packet_ref_sha256") or "").strip()
    staged_artifact_hash = str(row.get("staged_artifact_ref_sha256") or row.get("staged_artifact_sha256") or "").strip()
    actor_hash = str(row.get("actor_sha256") or "").strip()
    evidence_hash = str(
        row.get("evidence_sha256")
        or row.get("approval_prompt_sha256")
        or row.get("message_id_sha256")
        or row.get("callback_token_sha256")
        or ""
    ).strip()
    recorded = bool(packet_hash and staged_artifact_hash and actor_hash and evidence_hash)
    accepted = recorded and status == "approved"
    return {
        "present": recorded,
        "accepted": accepted,
        "approval_outcome_recorded": recorded,
        "status": "accepted_redacted" if accepted else "recorded_not_accepted" if recorded else "missing_or_invalid",
        "outcome": "approved" if status == "approved" else status,
        "source_kind": "telegram_button",
        "recorded_at": str(row.get("decided_at") or row.get("updated_at") or row.get("created_at") or "").strip(),
        "evidence_sha256": evidence_hash,
        "actor_sha256": actor_hash,
        "packet_ref_sha256": packet_hash,
        "staged_artifact_sha256": staged_artifact_hash,
        "approval_outcome_id": str(row.get("approval_outcome_id") or "").strip(),
        "raw_evidence_exposed": False,
        "raw_actor_exposed": False,
        "raw_packet_ref_exposed": False,
        "raw_staged_artifact_exposed": False,
    }


def _approval_callback_matches_current(row: Mapping[str, Any], current_packet_rows: list[dict[str, Any]]) -> bool:
    return any(row is current or row == current for current in current_packet_rows)


def _matching_approval_callback_rows(
    rows: list[dict[str, Any]],
    *,
    stage_packet: Mapping[str, Any],
    safe_work_result: Mapping[str, Any],
) -> list[dict[str, Any]]:
    packet_ref = _stage_packet_ref(stage_packet)
    staged_artifact_ref = _safe_work_result_ref(safe_work_result)
    if not packet_ref or not staged_artifact_ref:
        return []
    return [
        row
        for row in rows
        if str(row.get("packet_ref") or "").strip() == packet_ref
        and str(row.get("staged_artifact_ref") or "").strip() == staged_artifact_ref
    ]


def _stage_packet_ref(stage_packet: Mapping[str, Any]) -> str:
    return str(stage_packet.get("packet_ref") or stage_packet.get("packet_id") or "").strip()


def _safe_work_result_ref(safe_work_result: Mapping[str, Any]) -> str:
    result_ref = str(safe_work_result.get("result_ref") or "").strip()
    if result_ref:
        return result_ref
    result_id = str(safe_work_result.get("result_id") or "").strip()
    return f"safe_work_result:{result_id}" if result_id else ""


def _approval_callback_expired(row: Mapping[str, Any]) -> bool:
    text = str(row.get("expires_at") or "").strip()
    if not text:
        return False
    expires_at = _parse_callback_datetime(text)
    if expires_at is None:
        return False
    return expires_at <= datetime.now(UTC)


def _age_seconds(value: str) -> int:
    parsed = _parse_callback_datetime(value)
    if parsed is None:
        return 0
    return max(int((datetime.now(UTC) - parsed).total_seconds()), 0)


def _seconds_until(value: str) -> int:
    parsed = _parse_callback_datetime(value)
    if parsed is None:
        return 0
    return max(int((parsed - datetime.now(UTC)).total_seconds()), 0)


def _parse_callback_datetime(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _dir_writable(path: Path) -> bool:
    try:
        probe = path if _safe_exists(path) else path.parent
    except OSError:
        return False
    while probe != probe.parent and not _safe_exists(probe):
        probe = probe.parent
    try:
        return _safe_exists(probe) and _safe_is_dir(probe) and __import__("os").access(probe, __import__("os").W_OK)
    except Exception:
        return False


def _safe_exists(path: Path) -> bool:
    try:
        return path.exists()
    except OSError:
        return False


def _safe_is_dir(path: Path) -> bool:
    try:
        return path.is_dir()
    except OSError:
        return False


def _safe_glob(path: Path, pattern: str) -> list[Path]:
    if not _safe_is_dir(path):
        return []
    try:
        return list(path.glob(pattern))
    except OSError:
        return []


def _browse_score(safe_work_result: dict[str, Any]) -> int:
    execution_receipt = dict(safe_work_result.get("execution_receipt") or {})
    network_fetch_success_count = int(execution_receipt.get("network_fetch_success_count") or 0)
    reachable_page_count = sum(
        1
        for row in list(execution_receipt.get("page_checks") or [])
        if isinstance(row, dict) and row.get("reachable") is True
    )
    return 1 if network_fetch_success_count > 0 and reachable_page_count > 0 else 0


def _chosen_candidate_present(safe_work_result: dict[str, Any]) -> bool:
    recommended = dict(safe_work_result.get("recommended_option_or_draft") or {})
    if not str(recommended.get("kind") or "").strip():
        return False
    value = recommended.get("value")
    if isinstance(value, dict):
        return bool(str(value.get("label") or value.get("title") or value.get("url") or value.get("href") or "").strip())
    return bool(str(value or "").strip())


def _staged_for_decision(safe_work_result: dict[str, Any], stage_packet: dict[str, Any]) -> bool:
    if str(safe_work_result.get("status") or "").strip() != "staged_for_user_decision":
        return False
    stage_approval = dict(stage_packet.get("approval") or {})
    safe_approval = dict(safe_work_result.get("approval") or {})
    return bool(stage_approval.get("required")) or bool(safe_approval.get("required"))


def _assistant_grade_pair_score(stage_packet: dict[str, Any], safe_work_result: dict[str, Any]) -> int:
    stage = dict(stage_packet.get("stage") or {})
    stage_payload = dict(stage.get("payload") or {})
    safe_work_order = dict(stage_packet.get("safe_work_order") or {})
    stage_kind = str(stage.get("kind") or "").strip().lower()
    work_type = str(
        stage_payload.get("work_type")
        or safe_work_order.get("work_type")
        or safe_work_result.get("work_type")
        or ""
    ).strip().lower()
    return 0 if stage_kind in _ASSISTANT_GRADE_BLOCKING_WORK_TYPES or work_type in _ASSISTANT_GRADE_BLOCKING_WORK_TYPES else 1


def _stage_safe_pair_score(
    stage_packet: dict[str, Any],
    safe_work_result: dict[str, Any],
    mtime: float,
) -> tuple[int, int, int, float]:
    browse_score = _browse_score(safe_work_result)
    chosen_score = 1 if _chosen_candidate_present(safe_work_result) else 0
    staged_score = 1 if _staged_for_decision(safe_work_result, stage_packet) else 0
    return (browse_score, chosen_score, staged_score, mtime)
