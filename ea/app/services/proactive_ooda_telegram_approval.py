from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.services import google_oauth as google_oauth_service
from app.services.proactive_ooda_approval_capture import (
    default_proactive_ooda_root,
    finalize_proactive_ooda_approval_outcome,
)
from app.services.proactive_ooda_approval_outcomes import default_proactive_ooda_approval_outcome_path
from app.services.proactive_ooda_operator_actions import proactive_next_action_surface
from app.services.proactive_ooda_runtime_artifacts import (
    latest_payloads,
    load_runtime_artifact_bundle,
    resolve_runtime_artifact_paths,
)
from app.services.proactive_ooda_safe_work import SAFE_WORK_RESULT_SCHEMA
from app.services.proactive_ooda_stage_packets import STAGE_PACKET_SCHEMA
from app.services.telegram_delivery import send_telegram_message_for_principal

if TYPE_CHECKING:
    from app.container import AppContainer


PROACTIVE_OODA_TELEGRAM_APPROVAL_CALLBACK_SCHEMA = "ea.proactive_ooda_telegram_approval_callback.v1"
CALLBACK_PREFIX = "po"
_EMAIL_RE = re.compile(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", re.IGNORECASE)
CALLBACK_DECISION_STATUSES = {"approved", "rejected", "deferred", "dismissed"}
CALLBACK_TERMINAL_STATUSES = {*CALLBACK_DECISION_STATUSES, "expired", "superseded"}


def default_proactive_ooda_telegram_approval_callback_dir(
    *,
    root: Path,
    state_path: str | Path,
    receipt_path: str | Path = "",
) -> Path:
    approval_outcome_path = default_proactive_ooda_approval_outcome_path(
        root=root,
        state_path=state_path,
        receipt_path=receipt_path,
    )
    return approval_outcome_path.parent / "proactive_ooda_approval_callbacks"


def prepare_proactive_ooda_telegram_approval(
    *,
    principal_id: str,
    packet_ref: str,
    staged_artifact_ref: str,
    approval_prompt: str,
    chat_id: str,
    bot_token: str = "",
    staged_action_url: str = "",
    root: Path | None = None,
    state_path: str | Path = "state/proactive_ooda_notified.json",
    receipt_path: str | Path = "",
    callback_dir: str | Path = "",
    created_at: str | None = None,
    approved_execution_mode: str = "",
    approved_action: str = "",
) -> dict[str, Any]:
    resolved_root = root or default_proactive_ooda_root()
    directory = _resolve_callback_dir(
        root=resolved_root,
        state_path=state_path,
        receipt_path=receipt_path,
        callback_dir=callback_dir,
    )
    normalized_packet_ref = str(packet_ref or "").strip()
    normalized_artifact_ref = str(staged_artifact_ref or "").strip()
    normalized_chat_id = str(chat_id or "").strip()
    if not normalized_packet_ref or not normalized_artifact_ref or not normalized_chat_id:
        return {"inline_buttons": [], "url_buttons": [], "callback_token": "", "record_path": ""}
    created = str(created_at or _now_iso()).strip()
    normalized_execution_mode = _normalize_approved_execution_mode(approved_execution_mode)
    normalized_approved_action = str(approved_action or "").strip().lower()
    callback_token = _callback_token(
        principal_id=principal_id,
        packet_ref=normalized_packet_ref,
        staged_artifact_ref=normalized_artifact_ref,
        chat_id=normalized_chat_id,
        created_at=created,
    )
    record = {
        "schema": PROACTIVE_OODA_TELEGRAM_APPROVAL_CALLBACK_SCHEMA,
        "callback_token": callback_token,
        "status": "pending",
        "created_at": created,
        "expires_at": _expires_at_iso(),
        "principal_id_hash": _hash_value(principal_id),
        "chat_id_hash": _hash_value(normalized_chat_id),
        "packet_ref": normalized_packet_ref,
        "packet_ref_sha256": _hash_value(normalized_packet_ref),
        "staged_artifact_ref": normalized_artifact_ref,
        "staged_artifact_ref_sha256": _hash_value(normalized_artifact_ref),
        "approved_execution_mode": normalized_execution_mode,
        "approved_action": normalized_approved_action,
        "approval_prompt_sha256": _hash_value(approval_prompt),
        "staged_action_url_sha256": _hash_value(staged_action_url),
        "privacy": {
            "raw_principal_id_stored": False,
            "raw_chat_id_stored": False,
            "raw_approval_prompt_stored": False,
        },
    }
    record_path = directory / f"{callback_token}.json"
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    inline_buttons = [[
        ("Approve", encode_proactive_ooda_telegram_callback(action="approved", callback_token=callback_token, chat_id=normalized_chat_id, bot_token=bot_token)),
        ("Reject", encode_proactive_ooda_telegram_callback(action="rejected", callback_token=callback_token, chat_id=normalized_chat_id, bot_token=bot_token)),
        ("Later", encode_proactive_ooda_telegram_callback(action="deferred", callback_token=callback_token, chat_id=normalized_chat_id, bot_token=bot_token)),
    ]]
    inline_buttons = [[(label, data) for label, data in row if data] for row in inline_buttons]
    inline_buttons = [row for row in inline_buttons if row]
    url_buttons = [[("Open candidate", staged_action_url)]] if str(staged_action_url or "").strip() else []
    return {
        "callback_token": callback_token,
        "callback_token_sha256": _hash_value(callback_token),
        "record_path": record_path,
        "inline_buttons": inline_buttons,
        "url_buttons": url_buttons,
        "status": record["status"],
        "expires_at": record["expires_at"],
        "packet_ref_sha256": record["packet_ref_sha256"],
        "staged_artifact_ref_sha256": record["staged_artifact_ref_sha256"],
        "approval_prompt_sha256": record["approval_prompt_sha256"],
        "staged_action_url_sha256": record["staged_action_url_sha256"],
    }


def record_proactive_ooda_telegram_approval_delivery(
    *,
    record_path: str | Path,
    message_ids: tuple[str, ...] | list[str] = (),
    status: str = "pending",
    delivery_error_code: str = "",
    delivered_at: str | None = None,
) -> dict[str, Any]:
    path = Path(record_path)
    record = _load_json(path)
    if not record:
        raise RuntimeError("proactive_ooda_approval_callback_record_not_found")
    normalized_status = _normalize_delivery_status(status)
    ids = tuple(str(item or "").strip() for item in message_ids if str(item or "").strip())
    record["status"] = normalized_status
    record["prompt_message_ids"] = list(ids)
    record["prompt_message_count"] = len(ids)
    record["delivery_error_code"] = str(delivery_error_code or "").strip()
    if ids and normalized_status == "pending":
        record["delivered_at"] = str(delivered_at or _now_iso()).strip()
    elif normalized_status == "delivery_failed":
        record["delivery_failed_at"] = str(delivered_at or _now_iso()).strip()
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return record


def expire_stale_proactive_ooda_telegram_approval_callbacks(
    *,
    root: Path | None = None,
    state_path: str | Path = "state/proactive_ooda_notified.json",
    receipt_path: str | Path = "",
    callback_dir: str | Path = "",
    now: datetime | None = None,
    supersede_noncurrent: bool = False,
    active_packet_ref: str = "",
    active_staged_artifact_ref: str = "",
) -> dict[str, Any]:
    resolved_root = root or default_proactive_ooda_root()
    directory = _resolve_callback_dir(
        root=resolved_root,
        state_path=state_path,
        receipt_path=receipt_path,
        callback_dir=callback_dir,
    )
    if not directory.is_dir():
        return {
            "status": "no_callback_dir",
            "callback_dir": directory.as_posix(),
            "inspected_count": 0,
            "expired_count": 0,
            "superseded_count": 0,
            "skipped_count": 0,
            "error_count": 0,
            "errors": [],
            "active_packet_ref_sha256": "",
            "active_staged_artifact_ref_sha256": "",
        }
    observed_at = _datetime_or_now(now)
    inspected_count = 0
    expired_count = 0
    superseded_count = 0
    skipped_count = 0
    errors: list[dict[str, str]] = []
    normalized_active_packet_ref = str(active_packet_ref or "").strip()
    normalized_active_artifact_ref = str(active_staged_artifact_ref or "").strip()
    if supersede_noncurrent and (not normalized_active_packet_ref or not normalized_active_artifact_ref):
        normalized_active_packet_ref, normalized_active_artifact_ref = _current_runtime_packet_refs(
            root=resolved_root,
            state_path=state_path,
            receipt_path=receipt_path,
            stage_packet_dir="",
            safe_work_result_dir="",
        )
    for candidate in sorted(directory.glob("*.json")):
        try:
            record = _load_json(candidate)
            if not record:
                skipped_count += 1
                continue
            inspected_count += 1
            if _callback_record_status(record) != "pending":
                skipped_count += 1
                continue
            if not _callback_record_expired(record, now=observed_at):
                if (
                    supersede_noncurrent
                    and normalized_active_packet_ref
                    and normalized_active_artifact_ref
                    and not _callback_record_matches_refs(
                        record,
                        packet_ref=normalized_active_packet_ref,
                        staged_artifact_ref=normalized_active_artifact_ref,
                    )
                ):
                    _mark_callback_record_superseded(candidate, record, superseded_at=observed_at)
                    superseded_count += 1
                    continue
                skipped_count += 1
                continue
            _mark_callback_record_expired(candidate, record, expired_at=observed_at)
            expired_count += 1
        except Exception as exc:
            errors.append({"path": candidate.name, "error": exc.__class__.__name__})
    return {
        "status": "ok" if not errors else "partial",
        "callback_dir": directory.as_posix(),
        "inspected_count": inspected_count,
        "expired_count": expired_count,
        "superseded_count": superseded_count,
        "skipped_count": skipped_count,
        "error_count": len(errors),
        "errors": errors,
        "active_packet_ref_sha256": _hash_value(normalized_active_packet_ref),
        "active_staged_artifact_ref_sha256": _hash_value(normalized_active_artifact_ref),
    }


def encode_proactive_ooda_telegram_callback(
    *,
    action: str,
    callback_token: str,
    chat_id: str,
    bot_token: str = "",
    expires_at: int | None = None,
) -> str:
    normalized_action = _normalize_callback_action(action)
    normalized_token = str(callback_token or "").strip()
    normalized_chat_id = str(chat_id or "").strip()
    secret = _callback_secret(bot_token=bot_token)
    if not normalized_action or not normalized_token or not normalized_chat_id or not secret:
        return ""
    expiry = int(expires_at or (time.time() + _callback_ttl_seconds()))
    signature = _callback_signature(
        secret=secret,
        action=normalized_action,
        callback_token=normalized_token,
        chat_id=normalized_chat_id,
        expires_at=expiry,
    )
    return f"{CALLBACK_PREFIX}|{normalized_action}|{normalized_token}|{_base36_encode(expiry)}|{signature}"


def decode_proactive_ooda_telegram_callback(
    *,
    callback_data: str,
    chat_id: str,
    bot_token: str = "",
) -> dict[str, Any]:
    parts = str(callback_data or "").strip().split("|")
    if len(parts) != 5 or parts[0] != CALLBACK_PREFIX:
        return {"ok": False, "reason": "invalid_format"}
    _prefix, action, callback_token, expires_raw, signature = parts
    normalized_action = str(action or "").strip().lower()
    if normalized_action not in {"a", "r", "d"}:
        return {"ok": False, "reason": "invalid_action"}
    try:
        expires_at = _base36_decode(expires_raw)
    except Exception:
        return {"ok": False, "reason": "invalid_expiry"}
    if expires_at < int(time.time()):
        return {"ok": False, "reason": "expired"}
    normalized_chat_id = str(chat_id or "").strip()
    secret = _callback_secret(bot_token=bot_token)
    if not secret:
        return {"ok": False, "reason": "missing_secret"}
    expected = _callback_signature(
        secret=secret,
        action=normalized_action,
        callback_token=str(callback_token or "").strip(),
        chat_id=normalized_chat_id,
        expires_at=expires_at,
    )
    if not hmac.compare_digest(str(signature or "").strip(), expected):
        return {"ok": False, "reason": "invalid_signature"}
    return {
        "ok": True,
        "action": _action_label(normalized_action),
        "callback_token": str(callback_token or "").strip(),
        "expires_at": expires_at,
    }


def _proactive_ooda_script_materialization_blocked() -> None:
    raise ModuleNotFoundError("scripts.materialize_proactive_ooda_materialization_unavailable")


def _is_proactive_ooda_materialization_import_error(exc: ModuleNotFoundError) -> bool:
    reason = str(exc).lower()
    missing_name = str(getattr(exc, "name", "") or "").lower()
    return (
        "materialize_proactive_ooda" in reason
        or "materialize_proactive_ooda" in missing_name
        or missing_name == "scripts"
        or missing_name.startswith("scripts.")
    )


def _safe_finalize_proactive_ooda_approval_outcome(
    *,
    principal_id: str,
    outcome: str,
    evidence: str,
    actor: str,
    packet_ref: str,
    staged_artifact_ref: str,
    source_kind: str,
    root: Path,
    state_path: str | Path,
    receipt_path: str | Path,
    stage_packet_dir: str | Path,
    safe_work_result_dir: str | Path,
    database_url: str | None,
) -> dict[str, Any]:
    try:
        return finalize_proactive_ooda_approval_outcome(
            principal_id=principal_id,
            outcome=outcome,
            evidence=evidence,
            actor=actor,
            packet_ref=packet_ref,
            staged_artifact_ref=staged_artifact_ref,
            source_kind=source_kind,
            root=root,
            state_path=state_path,
            receipt_path=receipt_path,
            stage_packet_dir=stage_packet_dir,
            safe_work_result_dir=safe_work_result_dir,
            database_url=database_url,
        )
    except ModuleNotFoundError as exc:
        if not _is_proactive_ooda_materialization_import_error(exc):
            raise
        return finalize_proactive_ooda_approval_outcome(
            principal_id=principal_id,
            outcome=outcome,
            evidence=evidence,
            actor=actor,
            packet_ref=packet_ref,
            staged_artifact_ref=staged_artifact_ref,
            source_kind=source_kind,
            root=root,
            state_path=state_path,
            receipt_path=receipt_path,
            stage_packet_dir=stage_packet_dir,
            safe_work_result_dir=safe_work_result_dir,
            database_url=database_url,
            operator_status_materializer=_proactive_ooda_script_materialization_blocked,
            gold_materializer=_proactive_ooda_script_materialization_blocked,
            teable_sync_decider=lambda: False,
        )


def _approval_callback_principal_candidates(
    *,
    container: AppContainer | None,
    principal_id: str,
) -> tuple[str, ...]:
    normalized_principal_id = str(principal_id or "").strip()
    if not normalized_principal_id:
        return ()
    if container is None:
        return (normalized_principal_id,)
    try:
        aliases = tuple(
            google_oauth_service._principal_alias_candidates(
                container=container,
                principal_ids=(normalized_principal_id,),
                include_local_user=False,
            )
        )
    except Exception:
        aliases = ()
    ordered: list[str] = []
    for candidate in (normalized_principal_id, *aliases):
        normalized = str(candidate or "").strip()
        if normalized and normalized not in ordered:
            ordered.append(normalized)
    return tuple(ordered)


def _approval_callback_principal_matches(
    *,
    record: dict[str, Any],
    principal_id: str,
    container: AppContainer | None,
) -> bool:
    record_principal_hash = str(record.get("principal_id_hash") or "").strip()
    if not record_principal_hash:
        return False
    for candidate_principal_id in _approval_callback_principal_candidates(
        container=container,
        principal_id=principal_id,
    ):
        if record_principal_hash == _hash_value(candidate_principal_id):
            return True
    return False


def apply_proactive_ooda_telegram_approval_callback(
    *,
    callback_token: str,
    outcome: str,
    principal_id: str,
    actor: str,
    message_id: str = "",
    container: AppContainer | None = None,
    root: Path | None = None,
    state_path: str | Path = "state/proactive_ooda_notified.json",
    receipt_path: str | Path = "",
    stage_packet_dir: str | Path = "",
    safe_work_result_dir: str | Path = "",
    callback_dir: str | Path = "",
    database_url: str | None = None,
) -> dict[str, Any]:
    resolved_root = root or default_proactive_ooda_root()
    record_path = _resolve_callback_dir(
        root=resolved_root,
        state_path=state_path,
        receipt_path=receipt_path,
        callback_dir=callback_dir,
    ) / f"{str(callback_token or '').strip()}.json"
    if not record_path.is_file():
        raise RuntimeError("proactive_ooda_approval_callback_token_not_found")
    record = _load_json(record_path)
    if not _approval_callback_principal_matches(
        record=record,
        principal_id=principal_id,
        container=container,
    ):
        raise RuntimeError("proactive_ooda_approval_callback_principal_mismatch")
    existing_status = str(record.get("status") or "").strip().lower()
    normalized_outcome = _normalize_outcome(outcome)
    if existing_status == "pending" and _callback_record_expired(record):
        expired_record = _mark_callback_record_expired(record_path, record)
        return {
            "status": "expired",
            "outcome": "expired",
            "approval_outcome_id": str(expired_record.get("approval_outcome_id") or "").strip(),
            "record_path": record_path,
        }
    if existing_status == "pending" and _callback_record_superseded_by_current_runtime(
        record=record,
        root=resolved_root,
        state_path=state_path,
        receipt_path=receipt_path,
        stage_packet_dir=stage_packet_dir,
        safe_work_result_dir=safe_work_result_dir,
    ):
        superseded_record = _mark_callback_record_superseded(record_path, record)
        return {
            "status": "superseded",
            "outcome": "superseded",
            "approval_outcome_id": str(superseded_record.get("approval_outcome_id") or "").strip(),
            "record_path": record_path,
        }
    if existing_status in CALLBACK_TERMINAL_STATUSES:
        return {
            "status": "already_recorded",
            "outcome": existing_status,
            "approval_outcome_id": str(record.get("approval_outcome_id") or "").strip(),
            "record_path": record_path,
        }
    approved_execution_mode = _normalize_approved_execution_mode(record.get("approved_execution_mode"))
    approved_action = str(record.get("approved_action") or "").strip().lower()
    finalized = _safe_finalize_proactive_ooda_approval_outcome(
        principal_id=principal_id,
        outcome=normalized_outcome,
        evidence=f"Recorded from Telegram proactive OODA approval button: {normalized_outcome}.",
        actor=actor,
        packet_ref=str(record.get("packet_ref") or "").strip(),
        staged_artifact_ref=str(record.get("staged_artifact_ref") or "").strip(),
        source_kind="telegram_button",
        root=resolved_root,
        state_path=state_path,
        receipt_path=receipt_path,
        stage_packet_dir=stage_packet_dir,
        safe_work_result_dir=safe_work_result_dir,
        database_url=database_url,
    )
    approval_outcome = dict(finalized.get("approval_outcome") or {})
    execution: dict[str, Any] = {}
    if normalized_outcome == "approved":
        if approved_execution_mode == "record_outcome_only":
            execution = {
                "status": "already_executed",
                "action": approved_action,
                "work_type": "",
                "reason": "approved_action_already_executed_reversible",
            }
        elif container is not None:
            try:
                execution = _execute_approved_proactive_ooda_action(
                    container=container,
                    principal_id=principal_id,
                    packet_ref=str(record.get("packet_ref") or "").strip(),
                    staged_artifact_ref=str(record.get("staged_artifact_ref") or "").strip(),
                    root=resolved_root,
                    state_path=state_path,
                    receipt_path=receipt_path,
                    stage_packet_dir=stage_packet_dir,
                    safe_work_result_dir=safe_work_result_dir,
                    execution_mode="approved",
                )
            except Exception as exc:
                execution = {
                    "status": "failed",
                    "action": "",
                    "work_type": "",
                    "reason": f"approved_action_execution_failed:{exc.__class__.__name__}",
                }
    record["status"] = normalized_outcome
    record["decided_at"] = _now_iso()
    record["message_id_sha256"] = _hash_value(message_id)
    record["actor_sha256"] = _hash_value(actor)
    record["approval_outcome_id"] = str(approval_outcome.get("outcome_id") or "").strip()
    if execution:
        record["execution"] = _redacted_execution_result(execution)
        if str(execution.get("status") or "").strip().lower() != "already_executed":
            _record_execution_observation(
                container=container,
                principal_id=principal_id,
                packet_ref=str(record.get("packet_ref") or "").strip(),
                staged_artifact_ref=str(record.get("staged_artifact_ref") or "").strip(),
                execution=execution,
            )
    record_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "status": "recorded",
        "outcome": normalized_outcome,
        "approval_outcome": approval_outcome,
        "execution": execution,
        "record_path": record_path,
        "gold_acceptance_path": finalized.get("gold_acceptance_path"),
    }


def execute_proactive_ooda_action(
    *,
    container: AppContainer,
    principal_id: str,
    packet_ref: str,
    staged_artifact_ref: str,
    root: Path,
    state_path: str | Path,
    receipt_path: str | Path,
    stage_packet_dir: str | Path,
    safe_work_result_dir: str | Path,
) -> dict[str, Any]:
    execution = _execute_approved_proactive_ooda_action(
        container=container,
        principal_id=principal_id,
        packet_ref=packet_ref,
        staged_artifact_ref=staged_artifact_ref,
        root=root,
        state_path=state_path,
        receipt_path=receipt_path,
        stage_packet_dir=stage_packet_dir,
        safe_work_result_dir=safe_work_result_dir,
        execution_mode="auto",
    )
    _record_execution_observation(
        container=container,
        principal_id=principal_id,
        packet_ref=packet_ref,
        staged_artifact_ref=staged_artifact_ref,
        execution=execution,
    )
    return execution


def resume_latest_telegram_gmail_draft_after_google_connect(
    *,
    container: AppContainer,
    principal_id: str,
    root: Path | None = None,
    state_path: str | Path = "state/proactive_ooda_notified.json",
    receipt_path: str | Path = "",
    stage_packet_dir: str | Path = "",
    safe_work_result_dir: str | Path = "",
) -> dict[str, Any]:
    resumed_root = root or default_proactive_ooda_root()
    effective_state_path = _default_proactive_ooda_state_path(state_path)
    effective_receipt_path = _default_proactive_ooda_receipt_path(receipt_path)
    effective_stage_packet_dir = _default_proactive_ooda_stage_packet_dir(stage_packet_dir)
    effective_safe_work_result_dir = _default_proactive_ooda_safe_work_result_dir(safe_work_result_dir)
    staged = _latest_resumable_telegram_draft_observation(
        container=container,
        principal_id=principal_id,
    )
    if staged is None:
        return {"status": "no_pending_draft"}
    staged_payload = dict(staged.payload or {})
    staged_principal_id = str(staged.principal_id or principal_id or "").strip()
    packet_ref = str(staged_payload.get("stage_packet_ref") or "").strip()
    staged_artifact_ref = str(staged_payload.get("safe_work_result_ref") or "").strip()
    if not packet_ref or not staged_artifact_ref:
        return {"status": "staged_refs_missing"}
    if _approved_action_execution_recorded(
        container=container,
        principal_id=staged_principal_id,
        packet_ref=packet_ref,
        staged_artifact_ref=staged_artifact_ref,
        status="executed",
    ):
        return {
            "status": "already_executed",
            "principal_id": staged_principal_id,
            "packet_ref": packet_ref,
            "staged_artifact_ref": staged_artifact_ref,
            "source_observation_id": str(staged.observation_id or "").strip(),
        }
    execution = execute_proactive_ooda_action(
        container=container,
        principal_id=staged_principal_id,
        packet_ref=packet_ref,
        staged_artifact_ref=staged_artifact_ref,
        root=resumed_root,
        state_path=effective_state_path,
        receipt_path=effective_receipt_path,
        stage_packet_dir=effective_stage_packet_dir,
        safe_work_result_dir=effective_safe_work_result_dir,
    )
    notification: dict[str, Any] = {"status": "skipped"}
    notification_text = _telegram_gmail_draft_resume_reply_text(
        execution=execution,
        principal_id=staged_principal_id,
    )
    if notification_text:
        try:
            receipt = send_telegram_message_for_principal(
                container.tool_runtime,
                principal_id=staged_principal_id,
                text=notification_text,
            )
            notification = {
                "status": "sent",
                "message_ids": tuple(str(value or "").strip() for value in receipt.message_ids if str(value or "").strip()),
            }
        except Exception as exc:
            notification = {
                "status": "failed",
                "reason": f"telegram_resume_delivery_failed:{exc.__class__.__name__}",
            }
    return {
        "status": str(execution.get("status") or "").strip() or "unknown",
        "principal_id": staged_principal_id,
        "packet_ref": packet_ref,
        "staged_artifact_ref": staged_artifact_ref,
        "source_observation_id": str(staged.observation_id or "").strip(),
        "execution": execution,
        "notification": notification,
    }


def inspect_latest_telegram_gmail_draft_followthrough(
    *,
    container: AppContainer,
    principal_id: str,
    root: Path | None = None,
    state_path: str | Path = "state/proactive_ooda_notified.json",
    receipt_path: str | Path = "",
    stage_packet_dir: str | Path = "",
    safe_work_result_dir: str | Path = "",
) -> dict[str, Any]:
    inspection_root = root or default_proactive_ooda_root()
    effective_state_path = _default_proactive_ooda_state_path(state_path)
    effective_receipt_path = _default_proactive_ooda_receipt_path(receipt_path)
    effective_stage_packet_dir = _default_proactive_ooda_stage_packet_dir(stage_packet_dir)
    effective_safe_work_result_dir = _default_proactive_ooda_safe_work_result_dir(safe_work_result_dir)
    staged = _latest_resumable_telegram_draft_observation(
        container=container,
        principal_id=principal_id,
    )
    if staged is None:
        return {"status": "no_pending_draft"}
    staged_payload = dict(staged.payload or {})
    staged_principal_id = str(staged.principal_id or principal_id or "").strip()
    packet_ref = str(staged_payload.get("stage_packet_ref") or "").strip()
    staged_artifact_ref = str(staged_payload.get("safe_work_result_ref") or "").strip()
    inspection: dict[str, Any] = {
        "status": "pending",
        "principal_id": staged_principal_id,
        "packet_ref": packet_ref,
        "staged_artifact_ref": staged_artifact_ref,
        "source_observation_id": str(staged.observation_id or "").strip(),
        "source_created_at": str(staged.created_at or "").strip(),
    }
    if not packet_ref or not staged_artifact_ref:
        inspection["status"] = "staged_refs_missing"
        return inspection
    if _approved_action_execution_recorded(
        container=container,
        principal_id=staged_principal_id,
        packet_ref=packet_ref,
        staged_artifact_ref=staged_artifact_ref,
        status="executed",
    ):
        inspection["status"] = "already_executed"
        return inspection

    artifacts = _load_matching_artifacts(
        root=inspection_root,
        state_path=effective_state_path,
        receipt_path=effective_receipt_path,
        stage_packet_dir=effective_stage_packet_dir,
        safe_work_result_dir=effective_safe_work_result_dir,
        packet_ref=packet_ref,
        staged_artifact_ref=staged_artifact_ref,
    )
    stage_packet = dict(artifacts.get("stage_packet") or {})
    safe_work_result = dict(artifacts.get("safe_work_result") or {})
    if not stage_packet:
        inspection.update({"status": "blocked", "reason": "approved_stage_packet_missing"})
        return inspection
    if not safe_work_result:
        inspection.update({"status": "blocked", "reason": "approved_safe_work_result_missing"})
        return inspection
    work_type = str(
        safe_work_result.get("work_type")
        or dict(stage_packet.get("safe_work_order") or {}).get("work_type")
        or ""
    ).strip()
    stage_payload = dict(dict(stage_packet.get("stage") or {}).get("payload") or {})
    input_contract = dict(dict(stage_packet.get("safe_work_order") or {}).get("input_contract") or {})
    action = _approved_action_name(work_type=work_type, stage_payload=stage_payload)
    recipient_email = _approved_draft_recipient_email(
        stage_payload=stage_payload,
        input_contract=input_contract,
        safe_work_result=safe_work_result,
    )
    body_text = _approved_draft_body(stage_payload=stage_payload, safe_work_result=safe_work_result)
    if not recipient_email and body_text:
        recipient_email = _first_email(body_text)
    subject = _approved_draft_subject(
        stage_payload=stage_payload,
        input_contract=input_contract,
        body_text=body_text,
    )
    google_binding_id = _approved_google_binding_id(stage_payload=stage_payload, input_contract=input_contract)
    explicit_google_account_email = _approved_google_account_email(stage_payload=stage_payload, input_contract=input_contract)
    expected_google_account_email = explicit_google_account_email or _principal_email_hint(staged_principal_id)
    inspection.update(
        {
            "action": action,
            "work_type": work_type,
            "recipient_email": recipient_email,
            "subject": subject,
            "draft_body_present": bool(body_text),
            "google_binding_id": google_binding_id,
            "expected_google_account_email": expected_google_account_email,
        }
    )
    if action != "save_gmail_draft":
        inspection.update({"status": "staged_only", "reason": "approved_action_kept_staged"})
        return inspection
    audit_block = _draft_auto_execution_audit_block(
        work_type=work_type,
        stage_payload=stage_payload,
        safe_work_result=safe_work_result,
        execution_mode="auto",
    )
    if audit_block:
        inspection.update(
            {
                "status": "blocked",
                **audit_block,
            }
        )
        return inspection
    if not body_text:
        inspection.update({"status": "blocked", "reason": "approved_draft_body_missing"})
        return inspection
    google_account, google_accounts = _matching_google_accounts(
        container=container,
        principal_id=staged_principal_id,
        google_binding_id=google_binding_id,
        expected_google_account_email=expected_google_account_email,
    )
    inspection["google_account_count"] = len(google_accounts)
    if google_account is None:
        reason = "google_oauth_binding_not_found"
        inspection.update(
            {
                "status": "blocked",
                "reason": reason,
                "next_action_surface": _approved_action_surface_for_reason(
                    reason,
                    expected_google_email=expected_google_account_email,
                ),
            }
        )
        return inspection
    granted_scopes = tuple(str(scope or "").strip() for scope in getattr(google_account, "granted_scopes", ()) if str(scope or "").strip())
    google_account_email = _google_account_email(google_account)
    google_token_status = str(getattr(google_account, "token_status", "") or "").strip().lower()
    google_reauth_required_reason = str(getattr(google_account, "reauth_required_reason", "") or "").strip()
    inspection.update(
        {
            "google_binding_id": google_binding_id or _google_account_binding_id(google_account),
            "google_account_email": google_account_email,
            "google_binding_principal_id": str(getattr(getattr(google_account, "binding", None), "principal_id", "") or "").strip(),
            "google_token_status": google_token_status,
            "google_reauth_required_reason": google_reauth_required_reason,
            "google_gmail_draft_scope_present": google_oauth_service.GOOGLE_SCOPE_GMAIL_MODIFY in granted_scopes,
            "google_granted_scopes": granted_scopes,
        }
    )
    reason = ""
    if explicit_google_account_email and google_account_email and google_account_email != explicit_google_account_email:
        reason = "google_oauth_account_mismatch"
    elif (
        not explicit_google_account_email
        and google_account_email
        and expected_google_account_email
        and google_account_email != expected_google_account_email
    ):
        reason = "google_oauth_account_mismatch"
    elif google_token_status == "reauth_required":
        reason = google_reauth_required_reason or "google_oauth_refresh_failed"
    elif google_oauth_service.GOOGLE_SCOPE_GMAIL_MODIFY not in granted_scopes:
        reason = "google_gmail_draft_scope_missing"
    if reason:
        inspection.update(
            {
                "status": "blocked",
                "reason": reason,
                "next_action_surface": _approved_action_surface_for_reason(
                    reason,
                    expected_google_email=expected_google_account_email,
                ),
            }
        )
        return inspection
    inspection["status"] = "ready"
    return inspection


def _execute_approved_proactive_ooda_action(
    *,
    container: AppContainer,
    principal_id: str,
    packet_ref: str,
    staged_artifact_ref: str,
    root: Path,
    state_path: str | Path,
    receipt_path: str | Path,
    stage_packet_dir: str | Path,
    safe_work_result_dir: str | Path,
    execution_mode: str = "approved",
) -> dict[str, Any]:
    artifacts = _load_matching_artifacts(
        root=root,
        state_path=state_path,
        receipt_path=receipt_path,
        stage_packet_dir=stage_packet_dir,
        safe_work_result_dir=safe_work_result_dir,
        packet_ref=packet_ref,
        staged_artifact_ref=staged_artifact_ref,
    )
    stage_packet = dict(artifacts.get("stage_packet") or {})
    safe_work_result = dict(artifacts.get("safe_work_result") or {})
    if not stage_packet:
        return {
            "status": "blocked",
            "action": "",
            "work_type": "",
            "reason": "approved_stage_packet_missing",
        }
    if not safe_work_result:
        return {
            "status": "blocked",
            "action": "",
            "work_type": "",
            "reason": "approved_safe_work_result_missing",
        }
    work_type = str(
        safe_work_result.get("work_type")
        or dict(stage_packet.get("safe_work_order") or {}).get("work_type")
        or ""
    ).strip()
    stage_payload = dict(dict(stage_packet.get("stage") or {}).get("payload") or {})
    input_contract = dict(dict(stage_packet.get("safe_work_order") or {}).get("input_contract") or {})
    action = _approved_action_name(work_type=work_type, stage_payload=stage_payload)
    if action != "save_gmail_draft":
        return {
            "status": "staged_only",
            "action": action,
            "work_type": work_type,
            "reason": "approved_action_kept_staged",
            "staged_action_url": str(safe_work_result.get("staged_action_url") or "").strip(),
        }
    audit_block = _draft_auto_execution_audit_block(
        work_type=work_type,
        stage_payload=stage_payload,
        safe_work_result=safe_work_result,
        execution_mode=execution_mode,
    )
    if audit_block:
        return {
            "status": "blocked",
            "action": action,
            "work_type": work_type,
            **audit_block,
        }

    recipient_email = _approved_draft_recipient_email(
        stage_payload=stage_payload,
        input_contract=input_contract,
        safe_work_result=safe_work_result,
    )
    body_text = _approved_draft_body(stage_payload=stage_payload, safe_work_result=safe_work_result)
    if not recipient_email and body_text:
        recipient_email = _first_email(body_text)
    if not body_text:
        return {
            "status": "blocked",
            "action": action,
            "work_type": work_type,
            "reason": "approved_draft_body_missing",
            "recipient_email": recipient_email,
        }

    subject = _approved_draft_subject(
        stage_payload=stage_payload,
        input_contract=input_contract,
        body_text=body_text,
    )
    google_binding_id = _approved_google_binding_id(stage_payload=stage_payload, input_contract=input_contract)
    explicit_google_account_email = _approved_google_account_email(stage_payload=stage_payload, input_contract=input_contract)
    principal_email_hint = _principal_email_hint(principal_id)
    expected_google_account_email = explicit_google_account_email or principal_email_hint
    google_account, _google_accounts = _matching_google_accounts(
        container=container,
        principal_id=principal_id,
        google_binding_id=google_binding_id,
        expected_google_account_email=expected_google_account_email,
    )
    resolved_google_binding_id = google_binding_id or _google_account_binding_id(google_account)
    google_account_email = explicit_google_account_email
    if not explicit_google_account_email:
        google_account_email = _resolved_google_account_email(
            container=container,
            principal_id=principal_id,
            google_binding_id=resolved_google_binding_id,
            expected_google_account_email=expected_google_account_email,
        )
    if (
        not explicit_google_account_email
        and google_account_email
        and principal_email_hint
        and google_account_email != principal_email_hint
    ):
        return {
            "status": "blocked",
            "action": action,
            "work_type": work_type,
            "reason": "google_oauth_account_mismatch",
            "recipient_email": recipient_email,
            "subject": subject,
            "next_action_surface": _approved_action_surface_for_reason(
                "google_oauth_account_mismatch",
                expected_google_email=principal_email_hint,
            ),
            "google_binding_id": resolved_google_binding_id,
            "google_account_email": google_account_email,
            "expected_google_account_email": principal_email_hint,
        }
    try:
        receipt = google_oauth_service.create_google_gmail_draft(
            container=container,
            principal_id=principal_id,
            recipient_email=recipient_email,
            subject=subject,
            body_text=body_text,
            thread_id=_approved_gmail_value(stage_payload=stage_payload, input_contract=input_contract, keys=("gmail_thread_id", "thread_id")),
            reply_to_message_id=_approved_gmail_value(
                stage_payload=stage_payload,
                input_contract=input_contract,
                keys=("gmail_rfc822_message_id", "in_reply_to", "message_id"),
            ),
            references=_approved_gmail_value(stage_payload=stage_payload, input_contract=input_contract, keys=("gmail_references", "references")),
            binding_id=resolved_google_binding_id,
        )
    except RuntimeError as exc:
        reason = str(exc or "approved_draft_creation_failed").strip() or "approved_draft_creation_failed"
        return {
            "status": "blocked",
            "action": action,
            "work_type": work_type,
            "reason": reason,
            "recipient_email": recipient_email,
            "subject": subject,
            "next_action_surface": _approved_action_surface_for_reason(
                reason,
                expected_google_email=principal_email_hint,
            ),
            "google_binding_id": resolved_google_binding_id,
            "google_account_email": google_account_email,
        }
    return {
        "status": "executed",
        "action": action,
        "work_type": work_type,
        "recipient_email": receipt.recipient_email,
        "subject": receipt.subject,
        "sender_email": receipt.sender_email,
        "gmail_draft_id": receipt.gmail_draft_id,
        "gmail_message_id": receipt.gmail_message_id,
        "draft_folder_url": receipt.draft_folder_url,
        "saved_at": receipt.saved_at,
        "google_binding_id": resolved_google_binding_id,
        "google_account_email": google_account_email or receipt.sender_email,
    }


def _latest_resumable_telegram_draft_observation(
    *,
    container: AppContainer,
    principal_id: str,
):
    candidates = _principal_candidates_for_resume(container=container, principal_id=principal_id)
    rows: list[Any] = []
    for candidate_principal_id in candidates:
        rows.extend(container.channel_runtime.list_recent_observations(limit=200, principal_id=candidate_principal_id))
    rows.sort(key=lambda row: (str(row.created_at or ""), str(row.observation_id or "")), reverse=True)
    for row in rows:
        if str(row.event_type or "").strip().lower() != "telegram.proactive_ooda_task_staged":
            continue
        payload = dict(row.payload or {})
        if str(payload.get("work_type") or "").strip().lower() != "draft":
            continue
        if _boolish(payload.get("approval_required")):
            continue
        if not str(payload.get("stage_packet_ref") or "").strip():
            continue
        if not str(payload.get("safe_work_result_ref") or "").strip():
            continue
        return row
    return None


def _principal_candidates_for_resume(*, container: AppContainer, principal_id: str) -> tuple[str, ...]:
    try:
        candidates = tuple(google_oauth_service._google_binding_principal_ids(container=container, principal_id=principal_id))
    except Exception:
        candidates = ()
    ordered: list[str] = []
    for candidate in (str(principal_id or "").strip(), *candidates):
        normalized = str(candidate or "").strip()
        if normalized and normalized not in ordered:
            ordered.append(normalized)
    return tuple(ordered)


def _provider_ledger_dir() -> str:
    return str(os.getenv("EA_RESPONSES_PROVIDER_LEDGER_DIR") or "").strip()


def _default_proactive_ooda_state_path(value: str | Path) -> str | Path:
    normalized = str(value or "").strip()
    if normalized and normalized != "state/proactive_ooda_notified.json":
        return value
    explicit = str(os.getenv("EA_PROACTIVE_OODA_STATE_PATH") or "").strip()
    if explicit:
        return explicit
    ledger_dir = _provider_ledger_dir()
    if ledger_dir:
        return str(Path(ledger_dir) / "proactive_ooda_notified.json")
    return value


def _default_proactive_ooda_receipt_path(value: str | Path) -> str | Path:
    normalized = str(value or "").strip()
    if normalized:
        return value
    explicit = str(os.getenv("EA_PROACTIVE_OODA_RECEIPT_PATH") or "").strip()
    if explicit:
        return explicit
    ledger_dir = _provider_ledger_dir()
    if ledger_dir:
        return str(Path(ledger_dir) / "proactive_ooda_latest_run.generated.json")
    return value


def _default_proactive_ooda_stage_packet_dir(value: str | Path) -> str | Path:
    normalized = str(value or "").strip()
    if normalized:
        return value
    explicit = str(os.getenv("EA_PROACTIVE_OODA_STAGE_PACKET_DIR") or "").strip()
    if explicit:
        return explicit
    ledger_dir = _provider_ledger_dir()
    if ledger_dir:
        return str(Path(ledger_dir) / "proactive_ooda_stage_packets")
    return value


def _default_proactive_ooda_safe_work_result_dir(value: str | Path) -> str | Path:
    normalized = str(value or "").strip()
    if normalized:
        return value
    explicit = str(os.getenv("EA_PROACTIVE_OODA_SAFE_WORK_RESULT_DIR") or "").strip()
    if explicit:
        return explicit
    ledger_dir = _provider_ledger_dir()
    if ledger_dir:
        return str(Path(ledger_dir) / "proactive_ooda_safe_work_results")
    return value


def _approved_action_execution_recorded(
    *,
    container: AppContainer,
    principal_id: str,
    packet_ref: str,
    staged_artifact_ref: str,
    status: str = "",
) -> bool:
    packet_hash = _hash_value(packet_ref)
    artifact_hash = _hash_value(staged_artifact_ref)
    normalized_status = str(status or "").strip().lower()
    for candidate_principal_id in _principal_candidates_for_resume(container=container, principal_id=principal_id):
        rows = container.channel_runtime.list_recent_observations(limit=200, principal_id=candidate_principal_id)
        for row in rows:
            if str(row.event_type or "").strip().lower() != "proactive_ooda.approved_action_execution":
                continue
            payload = dict(row.payload or {})
            if str(payload.get("packet_ref_sha256") or "").strip() != packet_hash:
                continue
            if str(payload.get("staged_artifact_ref_sha256") or "").strip() != artifact_hash:
                continue
            row_status = str(payload.get("status") or "").strip().lower()
            if normalized_status and row_status != normalized_status:
                continue
            return True
    return False


def _load_matching_artifacts(
    *,
    root: Path,
    state_path: str | Path,
    receipt_path: str | Path,
    stage_packet_dir: str | Path,
    safe_work_result_dir: str | Path,
    packet_ref: str,
    staged_artifact_ref: str,
) -> dict[str, Any]:
    paths = resolve_runtime_artifact_paths(
        root=root,
        state_path=state_path,
        receipt_path=receipt_path,
        stage_packet_dir=stage_packet_dir,
        safe_work_result_dir=safe_work_result_dir,
    )
    stage_match: dict[str, Any] = {}
    for _path, payload, _mtime in latest_payloads(paths["stage_packet_dir"], schema=STAGE_PACKET_SCHEMA):
        if str(payload.get("packet_ref") or payload.get("packet_id") or "").strip() == str(packet_ref or "").strip():
            stage_match = payload
            break
    safe_match: dict[str, Any] = {}
    expected_packet_hash = _hash_value(str(packet_ref or "").strip())
    for _path, payload, _mtime in latest_payloads(paths["safe_work_result_dir"], schema=SAFE_WORK_RESULT_SCHEMA):
        result_ref = str(payload.get("result_ref") or "").strip()
        if not result_ref:
            result_id = str(payload.get("result_id") or "").strip()
            result_ref = f"safe_work_result:{result_id}" if result_id else ""
        if result_ref != str(staged_artifact_ref or "").strip():
            continue
        source_packet_ref_hash = str(payload.get("source_packet_ref_hash") or "").strip()
        if expected_packet_hash and source_packet_ref_hash and source_packet_ref_hash != expected_packet_hash:
            continue
        safe_match = payload
        break
    return {"stage_packet": stage_match, "safe_work_result": safe_match}


def _approved_action_name(*, work_type: str, stage_payload: dict[str, Any]) -> str:
    explicit = str(
        stage_payload.get("post_approval_action")
        or stage_payload.get("approved_action")
        or ""
    ).strip().lower()
    if explicit:
        return explicit
    return "save_gmail_draft" if str(work_type or "").strip() == "draft" else "keep_staged"


def build_reversible_execution_approval_prompt(*, action: str) -> str:
    normalized_action = str(action or "").strip().lower()
    if normalized_action == "save_gmail_draft":
        return (
            "Approve whether EA should keep this saved Gmail draft as the chosen next step. "
            "The draft is already saved in Gmail for review. "
            "No external send will happen without explicit approval."
        )
    return (
        "Approve whether EA should keep this reversible next step. "
        "The reversible work is already prepared. "
        "No irreversible action will happen without explicit approval."
    )


def _approved_draft_body(*, stage_payload: dict[str, Any], safe_work_result: dict[str, Any]) -> str:
    recommended = dict(safe_work_result.get("recommended_option_or_draft") or {})
    raw = str(
        recommended.get("value")
        or stage_payload.get("draft_text")
        or stage_payload.get("draft")
        or ""
    ).strip()
    if raw.lower().startswith("draft to review:"):
        raw = raw.split(":", 1)[1].strip()
    return raw


def _approved_draft_subject(
    *,
    stage_payload: dict[str, Any],
    input_contract: dict[str, Any],
    body_text: str,
) -> str:
    subject = str(
        stage_payload.get("subject")
        or stage_payload.get("subject_hint")
        or input_contract.get("subject")
        or input_contract.get("subject_hint")
        or ""
    ).strip()
    if subject:
        return subject
    first_line = body_text.splitlines()[0].strip() if body_text.splitlines() else ""
    if first_line:
        return first_line[:120]
    return "EA draft"


def _approved_draft_recipient_email(
    *,
    stage_payload: dict[str, Any],
    input_contract: dict[str, Any],
    safe_work_result: dict[str, Any],
) -> str:
    recommended = dict(safe_work_result.get("recommended_option_or_draft") or {})
    for value in (
        recommended.get("recipient_email"),
        dict(recommended.get("candidate") or {}) if isinstance(recommended.get("candidate"), dict) else {},
    ):
        text = _first_email(value)
        if text:
            return text
    for candidate in list(safe_work_result.get("shortlist") or []):
        if not isinstance(candidate, dict):
            continue
        for value in (
            candidate.get("contact_email"),
            candidate.get("email"),
            candidate.get("contact_emails"),
        ):
            text = _first_email(value)
            if text:
                return text
    for value in (
        stage_payload.get("recipient_email"),
        stage_payload.get("recipient"),
        stage_payload.get("delivery_recipient_email"),
        stage_payload.get("counterparty_email"),
        input_contract.get("recipient_email"),
        input_contract.get("recipient"),
    ):
        text = _first_email(value)
        if text:
            return text
    recipient_context = stage_payload.get("recipient_context")
    if not isinstance(recipient_context, dict):
        recipient_context = input_contract.get("recipient_context")
    if isinstance(recipient_context, dict):
        for value in (
            recipient_context.get("recipient_email"),
            recipient_context.get("email"),
            recipient_context.get("channel_ref"),
            recipient_context.get("account_email"),
        ):
            text = _first_email(value)
            if text:
                return text
        for candidate in list(recipient_context.get("stakeholders") or []):
            if not isinstance(candidate, dict):
                continue
            for value in (
                candidate.get("recipient_email"),
                candidate.get("email"),
                candidate.get("channel_ref"),
                candidate.get("account_email"),
            ):
                text = _first_email(value)
                if text:
                    return text
    for value in (
        stage_payload.get("notes"),
        input_contract.get("notes"),
    ):
        text = _first_email(value)
        if text:
            return text
    return ""


def _approved_google_binding_id(*, stage_payload: dict[str, Any], input_contract: dict[str, Any]) -> str:
    return str(
        stage_payload.get("google_binding_id")
        or input_contract.get("google_binding_id")
        or ""
    ).strip()


def _approved_google_account_email(*, stage_payload: dict[str, Any], input_contract: dict[str, Any]) -> str:
    return str(
        stage_payload.get("google_account_email")
        or stage_payload.get("account_email")
        or input_contract.get("google_account_email")
        or input_contract.get("account_email")
        or ""
    ).strip().lower()


def _resolved_google_account_email(
    *,
    container: AppContainer,
    principal_id: str,
    google_binding_id: str,
    expected_google_account_email: str = "",
) -> str:
    account, _accounts = _matching_google_accounts(
        container=container,
        principal_id=principal_id,
        google_binding_id=google_binding_id,
        expected_google_account_email=expected_google_account_email,
    )
    return _google_account_email(account)


def _matching_google_accounts(
    *,
    container: AppContainer,
    principal_id: str,
    google_binding_id: str,
    expected_google_account_email: str = "",
) -> tuple[Any | None, tuple[Any, ...]]:
    try:
        accounts = tuple(google_oauth_service.list_google_accounts(container=container, principal_id=principal_id))
    except Exception:
        return None, tuple()
    binding_id = str(google_binding_id or "").strip()
    expected_email = str(expected_google_account_email or "").strip().lower()
    matches: list[Any] = []
    for account in accounts:
        account_binding_id = _google_account_binding_id(account)
        if binding_id and binding_id != account_binding_id:
            continue
        matches.append(account)
    if expected_email:
        for account in matches:
            if _google_account_email(account) == expected_email:
                return account, tuple(matches)
    return (matches[0] if matches else None), tuple(matches)


def _google_account_binding_id(account: Any | None) -> str:
    return str(getattr(getattr(account, "binding", None), "binding_id", "") or "").strip()


def _google_account_email(account: Any | None) -> str:
    return str(getattr(account, "google_email", "") or "").strip().lower()


def _principal_email_hint(principal_id: str) -> str:
    normalized = str(principal_id or "").strip().lower()
    if normalized.startswith("cf-email:"):
        return normalized.split(":", 1)[1].strip().lower()
    return ""


def _approved_gmail_value(
    *,
    stage_payload: dict[str, Any],
    input_contract: dict[str, Any],
    keys: tuple[str, ...],
) -> str | None:
    for key in keys:
        value = str(stage_payload.get(key) or input_contract.get(key) or "").strip()
        if value:
            return value
    return None


def _approved_action_surface_for_reason(reason: str, *, expected_google_email: str = "") -> dict[str, str]:
    normalized = str(reason or "").strip().lower()
    if normalized == "audit_review_required":
        return proactive_next_action_surface("review_proactive_draft_queue")
    if normalized in {
        "google_oauth_account_mismatch",
        "google_oauth_binding_not_found",
        "google_oauth_invalid_grant",
        "google_oauth_refresh_failed",
        "google_gmail_draft_scope_missing",
        "google_gmail_refresh_token_missing",
        "google_gmail_access_token_missing",
        "google_gmail_sender_missing",
    }:
        surface = proactive_next_action_surface("reauthorize_google_workspace_binding")
        href = str(surface.get("href") or "").strip()
        normalized_expected_google_email = str(expected_google_email or "").strip().lower()
        if href and "@" in normalized_expected_google_email:
            separator = "&" if "?" in href else "?"
            surface["href"] = f"{href}{separator}" + urllib.parse.urlencode(
                {"expected_google_email": normalized_expected_google_email}
            )
        return surface
    return {"href": "", "label": "", "method": ""}


def _draft_auto_execution_audit_block(
    *,
    work_type: str,
    stage_payload: dict[str, Any],
    safe_work_result: dict[str, Any],
    execution_mode: str,
) -> dict[str, Any]:
    if str(execution_mode or "").strip().lower() != "auto":
        return {}
    if str(work_type or "").strip().lower() != "draft":
        return {}
    draft_mode = str(stage_payload.get("draft_mode") or "").strip().lower()
    if draft_mode != "research_backed_inquiry":
        return {}
    audit = dict(safe_work_result.get("audit") or {})
    if str(audit.get("status") or "").strip().lower() != "review":
        return {}
    issues = [dict(item) for item in list(audit.get("issues") or []) if isinstance(item, dict)]
    issue_codes = [str(item.get("code") or "").strip() for item in issues if str(item.get("code") or "").strip()]
    return {
        "reason": "audit_review_required",
        "audit_status": "review",
        "audit_issue_codes": issue_codes,
        "next_action_surface": _approved_action_surface_for_reason("audit_review_required"),
    }


def _telegram_gmail_draft_resume_reply_text(*, execution: dict[str, Any], principal_id: str) -> str:
    status = str(execution.get("status") or "").strip().lower()
    action = str(execution.get("action") or "").strip().lower()
    if status == "executed" and action == "save_gmail_draft":
        lines = ["Saved. I created the Gmail draft."]
        draft_folder_url = str(execution.get("draft_folder_url") or "").strip()
        if draft_folder_url:
            lines.append(f"Open Drafts: {draft_folder_url}")
        gmail_draft_id = str(execution.get("gmail_draft_id") or "").strip()
        if gmail_draft_id:
            lines.append(f"Draft ID: {gmail_draft_id}")
        return "\n".join(lines)
    if status == "blocked":
        lines = ["I reconnected Google, but the pending draft still could not be saved."]
        reason = _telegram_gmail_draft_execution_reason(execution=execution)
        if reason:
            lines.append(f"Current blocker: {reason}.")
        connected_google_email = str(execution.get("google_account_email") or "").strip().lower()
        expected_google_email = str(
            execution.get("expected_google_account_email") or _principal_email_hint(principal_id)
        ).strip().lower()
        if connected_google_email and expected_google_email and connected_google_email != expected_google_email:
            lines.append(f"Connected Google account: {connected_google_email}")
            lines.append(f"Expected inbox account: {expected_google_email}")
        elif connected_google_email:
            lines.append(f"Connected Google account: {connected_google_email}")
        next_action = dict(execution.get("next_action_surface") or {})
        href = str(next_action.get("href") or "").strip()
        if href:
            lines.append(f"Next action: {href}")
        return "\n".join(lines)
    return ""


def _telegram_gmail_draft_execution_reason(*, execution: dict[str, Any]) -> str:
    reason = str(execution.get("reason") or "").strip().lower()
    if reason == "audit_review_required":
        return "the staged draft needs review before EA auto-saves it"
    if reason == "approved_draft_recipient_missing":
        return "I could not resolve a recipient from the request context"
    if reason == "approved_draft_body_missing":
        return "the draft body is still empty"
    if reason == "google_oauth_binding_not_found":
        return "no Google workspace is connected for this tenant"
    if reason in {"google_oauth_invalid_grant", "google_oauth_refresh_failed"}:
        return "the connected Google account needs reauthorization"
    if reason == "google_oauth_account_mismatch":
        return "the connected Google account does not match the tenant inbox"
    if reason == "google_gmail_draft_scope_missing":
        return "the connected Google account does not have Gmail draft scope"
    return str(reason or "").replace("_", " ").strip()


def _redacted_execution_result(execution: dict[str, Any]) -> dict[str, Any]:
    next_action = dict(execution.get("next_action_surface") or {})
    return {
        "status": str(execution.get("status") or "").strip(),
        "action": str(execution.get("action") or "").strip(),
        "work_type": str(execution.get("work_type") or "").strip(),
        "reason": str(execution.get("reason") or "").strip(),
        "saved_at": str(execution.get("saved_at") or "").strip(),
        "recipient_email_sha256": _hash_value(str(execution.get("recipient_email") or "").strip().lower()),
        "gmail_draft_id_sha256": _hash_value(str(execution.get("gmail_draft_id") or "").strip()),
        "gmail_message_id_sha256": _hash_value(str(execution.get("gmail_message_id") or "").strip()),
        "draft_folder_url_sha256": _hash_value(str(execution.get("draft_folder_url") or "").strip()),
        "next_action_surface": {
            "href_sha256": _hash_value(str(next_action.get("href") or "").strip()),
            "label": str(next_action.get("label") or "").strip(),
            "method": str(next_action.get("method") or "").strip(),
        },
        "raw_execution_payload_exposed": False,
    }


def _record_execution_observation(
    *,
    container: AppContainer | None,
    principal_id: str,
    packet_ref: str,
    staged_artifact_ref: str,
    execution: dict[str, Any],
) -> None:
    if container is None:
        return
    try:
        container.channel_runtime.ingest_observation(
            principal_id=principal_id,
            channel="system",
            event_type="proactive_ooda.approved_action_execution",
            payload={
                "packet_ref_sha256": _hash_value(packet_ref),
                "staged_artifact_ref_sha256": _hash_value(staged_artifact_ref),
                **_redacted_execution_result(execution),
            },
            source_id="ea-proactive-ooda",
            external_id=str(execution.get("gmail_draft_id") or execution.get("reason") or packet_ref).strip(),
            dedupe_key=(
                f"proactive_ooda.approved_action_execution:{_hash_value(packet_ref)}:"
                f"{_hash_value(staged_artifact_ref)}:{_hash_value(str(execution.get('status') or ''))}"
            ),
        )
    except Exception:
        return


def _first_email(value: Any) -> str:
    if isinstance(value, dict):
        for nested in value.values():
            email = _first_email(nested)
            if email:
                return email
        return ""
    if isinstance(value, (list, tuple)):
        for item in value:
            email = _first_email(item)
            if email:
                return email
        return ""
    match = _EMAIL_RE.search(str(value or ""))
    return match.group(0).strip().lower() if match else ""


def _boolish(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    normalized = str(value or "").strip().lower()
    return normalized in {"1", "true", "yes", "on"}


def _resolve_callback_dir(
    *,
    root: Path,
    state_path: str | Path,
    receipt_path: str | Path,
    callback_dir: str | Path,
) -> Path:
    normalized = str(callback_dir or "").strip()
    if normalized:
        path = Path(normalized)
        return path if path.is_absolute() else root / path
    return default_proactive_ooda_telegram_approval_callback_dir(
        root=root,
        state_path=state_path,
        receipt_path=receipt_path,
    )


def _callback_secret(*, bot_token: str) -> str:
    return (
        str(os.getenv("EA_PROACTIVE_OODA_TELEGRAM_CALLBACK_SECRET") or "").strip()
        or str(os.getenv("EA_TELEGRAM_CALLBACK_SECRET") or "").strip()
        or str(bot_token or "").strip()
    )


def _callback_ttl_seconds() -> int:
    raw = str(os.getenv("EA_PROACTIVE_OODA_APPROVAL_CALLBACK_TTL_SECONDS") or "604800").strip()
    try:
        value = int(raw or "604800")
    except Exception:
        value = 604800
    return min(max(value, 300), 2592000)


def _callback_signature(
    *,
    secret: str,
    action: str,
    callback_token: str,
    chat_id: str,
    expires_at: int,
) -> str:
    payload = "|".join(
        (
            CALLBACK_PREFIX,
            str(action or "").strip().lower(),
            str(callback_token or "").strip(),
            str(chat_id or "").strip(),
            str(int(expires_at)),
        )
    )
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()[:10]


def _callback_token(
    *,
    principal_id: str,
    packet_ref: str,
    staged_artifact_ref: str,
    chat_id: str,
    created_at: str,
) -> str:
    material = "\n".join((principal_id, packet_ref, staged_artifact_ref, chat_id, created_at))
    return _hash_value(material)[:14]


def _callback_record_status(record: dict[str, Any]) -> str:
    return str(record.get("status") or "").strip().lower()


def _callback_record_expired(record: dict[str, Any], *, now: datetime | None = None) -> bool:
    expires_at = _parse_callback_datetime(record.get("expires_at"))
    if expires_at is None:
        return False
    return expires_at <= _datetime_or_now(now)


def _mark_callback_record_expired(
    path: Path,
    record: dict[str, Any],
    *,
    expired_at: datetime | None = None,
) -> dict[str, Any]:
    previous_status = _callback_record_status(record)
    record["status"] = "expired"
    record["expired_at"] = _datetime_or_now(expired_at).isoformat().replace("+00:00", "Z")
    record["expiration_reason"] = "callback_ttl_elapsed"
    if previous_status and previous_status != "expired":
        record["previous_status"] = previous_status
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return record


def _mark_callback_record_superseded(
    path: Path,
    record: dict[str, Any],
    *,
    superseded_at: datetime | None = None,
) -> dict[str, Any]:
    previous_status = _callback_record_status(record)
    record["status"] = "superseded"
    record["superseded_at"] = _datetime_or_now(superseded_at).isoformat().replace("+00:00", "Z")
    record["superseded_reason"] = "not_current_proactive_ooda_packet"
    if previous_status and previous_status != "superseded":
        record["previous_status"] = previous_status
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return record


def _callback_record_superseded_by_current_runtime(
    *,
    record: dict[str, Any],
    root: Path,
    state_path: str | Path,
    receipt_path: str | Path,
    stage_packet_dir: str | Path,
    safe_work_result_dir: str | Path,
) -> bool:
    record_packet_ref = str(record.get("packet_ref") or "").strip()
    record_artifact_ref = str(record.get("staged_artifact_ref") or "").strip()
    if not record_packet_ref or not record_artifact_ref:
        return False
    current_packet_ref, current_artifact_ref = _current_runtime_packet_refs(
        root=root,
        state_path=state_path,
        receipt_path=receipt_path,
        stage_packet_dir=stage_packet_dir,
        safe_work_result_dir=safe_work_result_dir,
    )
    if not current_packet_ref or not current_artifact_ref:
        return False
    return not _callback_record_matches_refs(
        record,
        packet_ref=current_packet_ref,
        staged_artifact_ref=current_artifact_ref,
    )


def _current_runtime_packet_refs(
    *,
    root: Path,
    state_path: str | Path,
    receipt_path: str | Path,
    stage_packet_dir: str | Path,
    safe_work_result_dir: str | Path,
) -> tuple[str, str]:
    try:
        bundle = load_runtime_artifact_bundle(
            root=root,
            state_path=state_path,
            receipt_path=receipt_path,
            stage_packet_dir=stage_packet_dir,
            safe_work_result_dir=safe_work_result_dir,
        )
    except Exception:
        return "", ""
    stage_packet = dict(bundle.get("stage_packet") or {})
    safe_work_result = dict(bundle.get("safe_work_result") or {})
    current_packet_ref = str(stage_packet.get("packet_ref") or stage_packet.get("packet_id") or "").strip()
    current_artifact_ref = _safe_work_result_ref_from_payload(safe_work_result)
    return current_packet_ref, current_artifact_ref


def _callback_record_matches_refs(
    record: dict[str, Any],
    *,
    packet_ref: str,
    staged_artifact_ref: str,
) -> bool:
    return (
        str(record.get("packet_ref") or "").strip() == str(packet_ref or "").strip()
        and str(record.get("staged_artifact_ref") or "").strip() == str(staged_artifact_ref or "").strip()
    )


def _safe_work_result_ref_from_payload(safe_work_result: dict[str, Any]) -> str:
    result_ref = str(safe_work_result.get("result_ref") or "").strip()
    if result_ref:
        return result_ref
    result_id = str(safe_work_result.get("result_id") or "").strip()
    return f"safe_work_result:{result_id}" if result_id else ""


def _parse_callback_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _datetime_or_now(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _normalize_callback_action(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"approved", "approve", "accepted", "accept", "a"}:
        return "a"
    if normalized in {"rejected", "reject", "denied", "deny", "declined", "r"}:
        return "r"
    if normalized in {"deferred", "defer", "later", "d"}:
        return "d"
    return ""


def _normalize_approved_execution_mode(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"record_outcome_only", "already_executed_reversible"}:
        return "record_outcome_only"
    return "execute_if_approved"


def _action_label(value: str) -> str:
    return {"a": "approved", "r": "rejected", "d": "deferred"}.get(str(value or "").strip().lower(), "")


def _normalize_outcome(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"approved", "approve", "accepted", "accept", "a"}:
        return "approved"
    if normalized in {"rejected", "reject", "denied", "deny", "declined", "r"}:
        return "rejected"
    if normalized in {"deferred", "defer", "later", "d"}:
        return "deferred"
    if normalized in {"dismissed", "dismiss"}:
        return "dismissed"
    return normalized or "missing"


def _normalize_delivery_status(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"", "pending"}:
        return "pending"
    if normalized in {"delivery_failed", "failed", "prompt_delivery_failed"}:
        return "delivery_failed"
    if normalized in CALLBACK_TERMINAL_STATUSES:
        return normalized
    return normalized


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _base36_encode(value: int) -> str:
    alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"
    normalized = max(int(value), 0)
    if normalized == 0:
        return "0"
    chars: list[str] = []
    while normalized:
        normalized, remainder = divmod(normalized, 36)
        chars.append(alphabet[remainder])
    return "".join(reversed(chars))


def _base36_decode(value: str) -> int:
    return int(str(value or "0").strip().lower(), 36)


def _hash_value(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest() if str(value or "").strip() else ""


def _expires_at_iso() -> str:
    return datetime.fromtimestamp(int(time.time()) + _callback_ttl_seconds(), tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
