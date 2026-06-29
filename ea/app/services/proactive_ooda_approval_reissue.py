from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Callable, Mapping

from app.services.proactive_ooda_approval_capture import finalize_proactive_ooda_approval_outcome
from app.services.proactive_ooda_delivery import send_proactive_ooda_notification
from app.services.proactive_ooda_runtime_artifacts import load_runtime_artifact_bundle
from app.services.proactive_ooda_telegram_policy import approval_request_needs_telegram_user_action


def reissue_current_proactive_ooda_approval(
    *,
    principal_id: str,
    root: Path,
    state_path: str | Path,
    receipt_path: str | Path = "",
    stage_packet_dir: str | Path = "",
    safe_work_result_dir: str | Path = "",
    force: bool = False,
    reissue_after_seconds: int = 0,
    dry_run: bool = False,
    container: Any | None = None,
    container_factory: Callable[[], Any] | None = None,
    bundle_loader: Callable[..., Mapping[str, Any]] = load_runtime_artifact_bundle,
    sender: Callable[..., Any] = send_proactive_ooda_notification,
) -> dict[str, Any]:
    normalized_principal_id = str(principal_id or "").strip()
    if not normalized_principal_id:
        return {"status": "blocked", "reason": "principal_id_required"}
    bundle = dict(
        bundle_loader(
            root=root,
            state_path=state_path,
            receipt_path=receipt_path,
            stage_packet_dir=stage_packet_dir,
            safe_work_result_dir=safe_work_result_dir,
        )
    )
    approval_request = current_proactive_ooda_approval_request(bundle)
    if not approval_request.get("ready"):
        return {
            "status": "blocked",
            "reason": str(approval_request.get("reason") or "approval_request_unavailable"),
            "current_packet_live_pending_count": int(bundle.get("current_packet_live_pending_count") or 0),
        }
    if not approval_request_needs_telegram_user_action(approval_request):
        return {
            "status": "blocked",
            "reason": "approval_request_not_user_action_required",
            "current_packet_live_pending_count": int(bundle.get("current_packet_live_pending_count") or 0),
            **_redacted_request_summary(approval_request),
        }
    if _approval_outcome_matches_request(dict(bundle.get("approval_outcome") or {}), approval_request):
        return {
            "status": "already_decided",
            "reason": "current_packet_approval_outcome_already_recorded",
            "current_packet_live_pending_count": int(bundle.get("current_packet_live_pending_count") or 0),
            "approval_outcome_status": str(dict(bundle.get("approval_outcome") or {}).get("status") or "").strip(),
            **_redacted_request_summary(approval_request),
        }
    live_pending_count = int(bundle.get("current_packet_live_pending_count") or 0)
    live_pending_age_seconds = int(bundle.get("current_packet_callback_latest_age_seconds") or 0)
    reissue_threshold_seconds = max(int(reissue_after_seconds or 0), 0)
    reissue_eligible = bool(force) or (
        live_pending_count > 0
        and reissue_threshold_seconds > 0
        and live_pending_age_seconds >= reissue_threshold_seconds
    )
    reissue_context = {
        "current_packet_callback_latest_age_seconds": live_pending_age_seconds,
        "reissue_after_seconds": reissue_threshold_seconds,
        "reissue_eligible": reissue_eligible,
    }
    if live_pending_count > 0 and not force and not reissue_eligible:
        return {
            "status": "already_live_pending",
            "reason": "current_packet_approval_surface_already_live",
            "current_packet_live_pending_count": live_pending_count,
            **reissue_context,
            **_redacted_request_summary(approval_request),
        }
    if dry_run:
        return {
            "status": "dry_run",
            "reason": "approval_surface_ready_to_reissue",
            "current_packet_live_pending_count": live_pending_count,
            **reissue_context,
            **_redacted_request_summary(approval_request),
        }
    resolved_container = container
    if resolved_container is None:
        factory = container_factory or _default_container_factory
        resolved_container = factory()
    receipt = sender(
        principal_id=normalized_principal_id,
        text=str(approval_request.get("approval_prompt") or "").strip(),
        tool_runtime=getattr(resolved_container, "tool_runtime", None),
        channel_runtime=getattr(resolved_container, "channel_runtime", None),
        memory_runtime=getattr(resolved_container, "memory_runtime", None),
        approval_request={
            "packet_ref": str(approval_request.get("packet_ref") or "").strip(),
            "staged_artifact_ref": str(approval_request.get("staged_artifact_ref") or "").strip(),
            "approval_prompt": str(approval_request.get("approval_prompt") or "").strip(),
            "staged_action_url": str(approval_request.get("staged_action_url") or "").strip(),
            "approved_execution_mode": str(approval_request.get("approved_execution_mode") or "").strip(),
            "approved_action": str(approval_request.get("approved_action") or "").strip(),
        },
    )
    approval_surface = _approval_surface_from_receipt(receipt)
    message_ids = _message_ids_from_receipt(receipt)
    return {
        "status": "sent",
        "reason": "approval_surface_reissued",
        "current_packet_live_pending_count_before": live_pending_count,
        **reissue_context,
        "message_count": len(message_ids),
        "message_ids": message_ids,
        "delivery_channel": _receipt_text(receipt, "channel"),
        "delivery_transport": _receipt_text(receipt, "delivery_transport"),
        "approval_surface": _redacted_approval_surface(approval_surface),
        **_redacted_request_summary(approval_request),
    }


def record_current_proactive_ooda_approval_outcome(
    *,
    principal_id: str,
    outcome: str,
    evidence: str,
    actor: str,
    root: Path,
    state_path: str | Path,
    receipt_path: str | Path = "",
    stage_packet_dir: str | Path = "",
    safe_work_result_dir: str | Path = "",
    source_kind: str = "operator_manual",
    recorded_at: str | None = None,
    expected_packet_ref: str = "",
    expected_staged_artifact_ref: str = "",
    force: bool = False,
    dry_run: bool = False,
    bundle_loader: Callable[..., Mapping[str, Any]] = load_runtime_artifact_bundle,
    finalizer: Callable[..., Mapping[str, Any]] = finalize_proactive_ooda_approval_outcome,
) -> dict[str, Any]:
    normalized_principal_id = str(principal_id or "").strip()
    if not normalized_principal_id:
        return {"status": "blocked", "reason": "principal_id_required"}
    if not str(actor or "").strip():
        return {"status": "blocked", "reason": "actor_required"}
    if not str(evidence or "").strip():
        return {"status": "blocked", "reason": "evidence_required"}
    bundle = dict(
        bundle_loader(
            root=root,
            state_path=state_path,
            receipt_path=receipt_path,
            stage_packet_dir=stage_packet_dir,
            safe_work_result_dir=safe_work_result_dir,
        )
    )
    current_packet_live_pending_count = int(bundle.get("current_packet_live_pending_count") or 0)
    approval_request = current_proactive_ooda_approval_request(bundle)
    if not approval_request.get("ready"):
        return {
            "status": "blocked",
            "reason": str(approval_request.get("reason") or "approval_request_unavailable"),
            "current_packet_live_pending_count": current_packet_live_pending_count,
            **_redacted_request_summary(approval_request),
        }
    current_packet_ref = str(approval_request.get("packet_ref") or "").strip()
    current_staged_artifact_ref = str(approval_request.get("staged_artifact_ref") or "").strip()
    expected_packet_ref_text = str(expected_packet_ref or "").strip()
    if expected_packet_ref_text and expected_packet_ref_text != current_packet_ref:
        return {
            "status": "blocked",
            "reason": "current_packet_ref_mismatch",
            "current_packet_live_pending_count": current_packet_live_pending_count,
            "expected_packet_ref_sha256": _hash_value(expected_packet_ref_text),
            "current_packet_ref_sha256": _hash_value(current_packet_ref),
            **_redacted_request_summary(approval_request),
        }
    expected_staged_artifact_ref_text = str(expected_staged_artifact_ref or "").strip()
    if expected_staged_artifact_ref_text and expected_staged_artifact_ref_text != current_staged_artifact_ref:
        return {
            "status": "blocked",
            "reason": "current_staged_artifact_ref_mismatch",
            "current_packet_live_pending_count": current_packet_live_pending_count,
            "expected_staged_artifact_ref_sha256": _hash_value(expected_staged_artifact_ref_text),
            "current_staged_artifact_ref_sha256": _hash_value(current_staged_artifact_ref),
            **_redacted_request_summary(approval_request),
        }
    current_outcome = dict(bundle.get("approval_outcome") or {})
    if not force and _approval_outcome_matches_request(current_outcome, approval_request):
        return {
            "status": "already_decided",
            "reason": "current_packet_approval_outcome_already_recorded",
            "approval_outcome_status": str(current_outcome.get("status") or "").strip(),
            "current_packet_live_pending_count": current_packet_live_pending_count,
            **_redacted_request_summary(approval_request),
        }
    if dry_run:
        return {
            "status": "dry_run",
            "reason": "approval_outcome_ready_to_record",
            "requested_outcome": str(outcome or "").strip(),
            "source_kind": str(source_kind or "").strip() or "operator_manual",
            "current_packet_live_pending_count": current_packet_live_pending_count,
            **_redacted_request_summary(approval_request),
        }
    finalized = dict(
        finalizer(
            principal_id=normalized_principal_id,
            outcome=outcome,
            evidence=evidence,
            actor=actor,
            packet_ref=str(approval_request.get("packet_ref") or "").strip(),
            staged_artifact_ref=str(approval_request.get("staged_artifact_ref") or "").strip(),
            source_kind=str(source_kind or "").strip() or "operator_manual",
            recorded_at=recorded_at,
            root=root,
            state_path=state_path,
            receipt_path=receipt_path,
            stage_packet_dir=stage_packet_dir,
            safe_work_result_dir=safe_work_result_dir,
        )
    )
    approval_outcome = dict(finalized.get("approval_outcome") or {})
    return {
        "status": "recorded" if bool(approval_outcome.get("approval_outcome_recorded")) else "failed",
        "reason": "approval_outcome_recorded" if bool(approval_outcome.get("approval_outcome_recorded")) else "approval_outcome_not_recorded",
        "approval_outcome_id": str(approval_outcome.get("outcome_id") or "").strip(),
        "approval_outcome_status": str(approval_outcome.get("status") or "").strip(),
        "approval_outcome_accepted": bool(approval_outcome.get("accepted")),
        "source_kind": str(approval_outcome.get("source_kind") or source_kind or "").strip(),
        "recorded_at": str(approval_outcome.get("recorded_at") or recorded_at or "").strip(),
        "current_packet_live_pending_count": current_packet_live_pending_count,
        "approval_outcome_path": finalized.get("approval_outcome_path"),
        "operator_status_path": finalized.get("operator_status_path"),
        "gold_acceptance_path": finalized.get("gold_acceptance_path"),
        "operator_status_materialization": dict(finalized.get("operator_status_materialization") or {}),
        "gold_acceptance_materialization": dict(finalized.get("gold_acceptance_materialization") or {}),
        "teable_sync": dict(finalized.get("teable_sync") or {}),
        **_redacted_request_summary(approval_request),
    }


def current_proactive_ooda_approval_request(bundle: Mapping[str, Any]) -> dict[str, Any]:
    stage_packet = dict(bundle.get("stage_packet") or {})
    safe_work_result = dict(bundle.get("safe_work_result") or {})
    packet_ref = _stage_packet_ref(stage_packet)
    staged_artifact_ref = _safe_work_result_ref(safe_work_result)
    if not packet_ref or not staged_artifact_ref:
        return {"ready": False, "reason": "current_packet_refs_missing"}
    if str(safe_work_result.get("status") or "").strip() != "staged_for_user_decision":
        return {"ready": False, "reason": "safe_work_not_staged_for_user_decision"}
    stage_approval = dict(stage_packet.get("approval") or {})
    safe_work_approval = dict(safe_work_result.get("approval") or {})
    if not (bool(stage_approval.get("required")) or bool(safe_work_approval.get("required"))):
        return {"ready": False, "reason": "approval_not_required_for_current_packet"}
    approval_prompt = str(safe_work_result.get("approval_prompt") or "").strip()
    staged_action_url = str(safe_work_result.get("staged_action_url") or "").strip()
    if not approval_prompt and not staged_action_url:
        return {"ready": False, "reason": "approval_surface_content_missing"}
    stage_payload = dict(dict(stage_packet.get("stage") or {}).get("payload") or {})
    return {
        "ready": True,
        "packet_ref": packet_ref,
        "staged_artifact_ref": staged_artifact_ref,
        "approval_prompt": approval_prompt,
        "staged_action_url": staged_action_url,
        "approved_execution_mode": str(stage_payload.get("approved_execution_mode") or "").strip(),
        "approved_action": str(stage_payload.get("approved_action") or "").strip(),
        "stage_kind": str(dict(stage_packet.get("stage") or {}).get("kind") or "").strip(),
        "safe_work_status": str(safe_work_result.get("status") or "").strip(),
    }


def _default_container_factory() -> Any:
    from app.container import build_container

    return build_container()


def _stage_packet_ref(stage_packet: Mapping[str, Any]) -> str:
    return str(stage_packet.get("packet_ref") or stage_packet.get("packet_id") or "").strip()


def _safe_work_result_ref(safe_work_result: Mapping[str, Any]) -> str:
    result_ref = str(safe_work_result.get("result_ref") or "").strip()
    if result_ref:
        return result_ref
    result_id = str(safe_work_result.get("result_id") or "").strip()
    return f"safe_work_result:{result_id}" if result_id else ""


def _hash_value(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest() if value else ""


def _approval_outcome_matches_request(
    approval_outcome: Mapping[str, Any],
    approval_request: Mapping[str, Any],
) -> bool:
    if not bool(approval_outcome.get("approval_outcome_recorded")):
        return False
    expected_packet_hash = _hash_value(str(approval_request.get("packet_ref") or "").strip())
    expected_artifact_hash = _hash_value(str(approval_request.get("staged_artifact_ref") or "").strip())
    outcome_packet_hash = str(approval_outcome.get("packet_ref_sha256") or "").strip()
    outcome_artifact_hash = str(approval_outcome.get("staged_artifact_sha256") or "").strip()
    return bool(
        expected_packet_hash
        and expected_artifact_hash
        and outcome_packet_hash == expected_packet_hash
        and outcome_artifact_hash == expected_artifact_hash
    )


def _redacted_request_summary(approval_request: Mapping[str, Any]) -> dict[str, Any]:
    packet_ref = str(approval_request.get("packet_ref") or "").strip()
    staged_artifact_ref = str(approval_request.get("staged_artifact_ref") or "").strip()
    return {
        "packet_ref_sha256": _hash_value(packet_ref),
        "staged_artifact_ref_sha256": _hash_value(staged_artifact_ref),
        "approval_prompt_sha256": _hash_value(str(approval_request.get("approval_prompt") or "").strip()),
        "staged_action_url_sha256": _hash_value(str(approval_request.get("staged_action_url") or "").strip()),
        "stage_kind": str(approval_request.get("stage_kind") or "").strip(),
        "safe_work_status": str(approval_request.get("safe_work_status") or "").strip(),
        "has_staged_action_url": bool(str(approval_request.get("staged_action_url") or "").strip()),
    }


def _approval_surface_from_receipt(receipt: Any) -> dict[str, Any]:
    if isinstance(receipt, Mapping):
        value = receipt.get("approval_surface")
    else:
        value = getattr(receipt, "approval_surface", None)
    return dict(value or {}) if isinstance(value, Mapping) else {}


def _message_ids_from_receipt(receipt: Any) -> list[str]:
    if isinstance(receipt, Mapping):
        values = receipt.get("message_ids")
    else:
        values = getattr(receipt, "message_ids", ())
    return [str(item or "").strip() for item in list(values or []) if str(item or "").strip()]


def _receipt_text(receipt: Any, key: str) -> str:
    if isinstance(receipt, Mapping):
        return str(receipt.get(key) or "").strip()
    return str(getattr(receipt, key, "") or "").strip()


def _redacted_approval_surface(surface: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "present": bool(surface.get("present")),
        "channel": str(surface.get("channel") or "").strip(),
        "status": str(surface.get("status") or "").strip(),
        "callback_token_sha256": str(surface.get("callback_token_sha256") or "").strip(),
        "expires_at": str(surface.get("expires_at") or "").strip(),
        "packet_ref_sha256": str(surface.get("packet_ref_sha256") or "").strip(),
        "staged_artifact_sha256": str(surface.get("staged_artifact_sha256") or "").strip(),
        "approval_prompt_sha256": str(surface.get("approval_prompt_sha256") or "").strip(),
        "staged_action_url_sha256": str(surface.get("staged_action_url_sha256") or "").strip(),
        "inline_button_count": int(surface.get("inline_button_count") or 0),
        "url_button_count": int(surface.get("url_button_count") or 0),
        "message_count": int(surface.get("message_count") or 0),
        "message_ids": [
            str(item or "").strip()
            for item in list(surface.get("message_ids") or [])
            if str(item or "").strip()
        ],
        "delivery_error_code": str(surface.get("delivery_error_code") or "").strip(),
    }
