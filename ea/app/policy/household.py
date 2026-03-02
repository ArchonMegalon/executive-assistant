from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from app.db import get_db


def enforce_household_policy(document_id: str, user_id: str, confidence_score: float) -> dict[str, Any]:
    """
    v1.12.5 M5: Household Safety Middleware
    Guarantees fail-closed ownership for ambiguous documents.
    Callable from Primary, Repair, Replay, and Enhancement paths.
    """
    if confidence_score < 0.85:
        logging.warning(
            "🔒 [HOUSEHOLD POLICY] Document %s ownership ambiguous (Score: %.3f).",
            document_id,
            confidence_score,
        )
        logging.warning("🔒 [HOUSEHOLD POLICY] ACTION BLOCKED: Moving to Blind Triage Review Queue.")
        return {
            "action_allowed": False,
            "reason": "low_confidence_ownership",
            "safe_hint": "A new family document needs review.",
        }

    logging.info("🔓 [HOUSEHOLD POLICY] Document %s ownership confirmed for User %s.", document_id, user_id)
    return {"action_allowed": True}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def queue_blind_triage(
    *,
    document_id: str,
    safe_hint: str,
    raw_document_ref: str,
    correlation_id: str,
    confidence_score: float,
) -> bool:
    hint = {
        "document_id": document_id,
        "safe_hint": safe_hint,
        "reason": "low_confidence_ownership",
        "confidence_score": round(float(confidence_score), 4),
    }
    try:
        get_db().execute(
            """
            INSERT INTO review_queue_items
                (status, sanitised_hint_json, raw_document_ref, created_at, updated_at)
            VALUES
                (%s, %s, %s, %s, %s)
            """,
            ("pending", json.dumps(hint, ensure_ascii=False), raw_document_ref, _utc_now(), _utc_now()),
        )
        logging.warning(
            "🔒 [HOUSEHOLD POLICY] triage queued correlation_id=%s document_id=%s",
            correlation_id,
            document_id,
        )
        return True
    except Exception as exc:
        logging.warning("🔒 [HOUSEHOLD POLICY] triage queue write failed: %s", exc)
        return False


def record_replay_block(
    *,
    document_id: str,
    pipeline_stage: str,
    correlation_id: str,
    reason: str,
) -> bool:
    try:
        get_db().execute(
            """
            INSERT INTO replay_events
                (document_id, pipeline_stage, attempt_count, status, correlation_id, dead_letter_reason, last_error, created_at, updated_at)
            VALUES
                (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                document_id,
                pipeline_stage,
                0,
                "blocked_household_policy",
                correlation_id,
                reason,
                "household policy blocked action due to ambiguous ownership",
                _utc_now(),
                _utc_now(),
            ),
        )
        return True
    except Exception as exc:
        logging.warning("🔒 [HOUSEHOLD POLICY] replay write failed: %s", exc)
        return False


def gate_household_document_action(
    *,
    document_id: str,
    user_id: str,
    confidence_score: float,
    raw_document_ref: str,
    pipeline_stage: str,
    correlation_id: str,
) -> dict[str, Any]:
    decision = enforce_household_policy(document_id, user_id, confidence_score)
    if decision.get("action_allowed"):
        return {"action_allowed": True}

    reason = str(decision.get("reason") or "low_confidence_ownership")
    safe_hint = str(decision.get("safe_hint") or "A new family document needs review.")
    triage_ok = queue_blind_triage(
        document_id=document_id,
        safe_hint=safe_hint,
        raw_document_ref=raw_document_ref,
        correlation_id=correlation_id,
        confidence_score=confidence_score,
    )
    replay_ok = record_replay_block(
        document_id=document_id,
        pipeline_stage=pipeline_stage,
        correlation_id=correlation_id,
        reason=reason,
    )
    return {
        "action_allowed": False,
        "reason": reason,
        "safe_hint": safe_hint,
        "triage_queued": triage_ok,
        "replay_recorded": replay_ok,
    }
