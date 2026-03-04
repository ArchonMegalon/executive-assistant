from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from app.db import get_db
from app.execution import (
    append_execution_event,
    compile_intent_spec,
    create_execution_session,
    finalize_execution_session,
    mark_execution_session_running,
    mark_execution_step_status,
)
from app.personalization.engine import PersonalizationEngine


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_chat_id_from_tenant(tenant: str) -> int | None:
    raw = str(tenant or "")
    if not raw.startswith("chat_"):
        return None
    try:
        return int(raw.split("_", 1)[1])
    except Exception:
        return None


def _coerce_payload(payload_raw):
    if isinstance(payload_raw, dict):
        return payload_raw
    if isinstance(payload_raw, str):
        try:
            return json.loads(payload_raw)
        except Exception:
            return {}
    return {}


def _tokenize_topics(v) -> list[str]:
    if v is None:
        return []
    if isinstance(v, list):
        vals = [str(x).strip().lower() for x in v if str(x).strip()]
    else:
        vals = [x.strip().lower() for x in re.split(r"[,\n;/|]+", str(v)) if x.strip()]
    return [re.sub(r"\s+", "_", x)[:80] for x in vals][:30]


async def process_metasurvey_submission(event_id: str):
    db = get_db()
    session_id = None
    current_step = "compile_intent"
    try:
        row = db.fetchone(
            """
            UPDATE external_events
            SET status='processing', updated_at=NOW()
            WHERE COALESCE(to_jsonb(external_events)->>'id', to_jsonb(external_events)->>'event_id')=%s
              AND (status IN ('queued', 'retry', 'failed') OR (status='processing' AND updated_at < NOW() - INTERVAL '15 minutes'))
            RETURNING tenant, payload_json
            """,
            (str(event_id),),
        )
        if not row:
            return

        tenant = str(row.get("tenant") or "")
        payload = _coerce_payload(row.get("payload_json"))
        intent_spec = compile_intent_spec(
            text="Process MetaSurvey submission webhook",
            tenant=tenant,
            chat_id=_parse_chat_id_from_tenant(tenant),
            has_url=False,
        )
        intent_spec["source"] = "metasurvey"
        intent_spec["event_id"] = str(event_id)
        session_id = create_execution_session(
            tenant=tenant,
            chat_id=_parse_chat_id_from_tenant(tenant),
            intent_spec=intent_spec,
            plan_steps=[
                {"step_key": "compile_intent", "step_title": "Compile Event Intent"},
                {"step_key": "execute_intent", "step_title": "Apply Feedback Signals"},
                {"step_key": "persist_result", "step_title": "Persist Event Result"},
            ],
            source="external_event_metasurvey",
            correlation_id=f"metasurvey:{tenant}:{event_id}",
        )
        if session_id:
            mark_execution_session_running(session_id)
            mark_execution_step_status(session_id, "compile_intent", "completed", result=intent_spec)
            append_execution_event(
                session_id,
                event_type="external_event_claimed",
                message="MetaSurvey event claimed for processing.",
                payload={"event_id": str(event_id)},
            )

        hidden = payload.get("hidden_fields") or payload.get("hidden") or {}
        answers = payload.get("answers") or payload.get("response") or payload.get("data") or {}
        if not isinstance(hidden, dict):
            hidden = {}
        if not isinstance(answers, dict):
            answers = {}

        principal = str(hidden.get("principal") or payload.get("principal") or payload.get("principal_id") or "unknown")
        tenant_key = str(hidden.get("tenant") or tenant or "unknown")
        pe = PersonalizationEngine()

        prioritize_topics = _tokenize_topics(
            answers.get("prioritize_topics")
            or answers.get("topics_to_prioritize")
            or answers.get("preferred_topics")
            or answers.get("q1")
            or ""
        )
        suppress_topics = _tokenize_topics(
            answers.get("suppress_topics")
            or answers.get("topics_to_suppress")
            or answers.get("avoid_topics")
            or answers.get("q2")
            or ""
        )
        publisher_topics = _tokenize_topics(answers.get("publishers") or answers.get("useful_publishers") or answers.get("q3") or "")
        depth_raw = str(answers.get("depth") or answers.get("detail_depth") or answers.get("q4") or "").strip().lower()

        current_step = "execute_intent"
        if session_id:
            mark_execution_step_status(
                session_id,
                "execute_intent",
                "running",
                evidence={
                    "prioritize_count": len(prioritize_topics),
                    "suppress_count": len(suppress_topics),
                    "publisher_count": len(publisher_topics),
                },
            )

        for topic in prioritize_topics:
            pe.record_feedback(
                tenant_key=tenant_key,
                principal_id=principal,
                concept_key=f"topic:{topic}",
                feedback_type="like",
                raw_reason_code="metasurvey_prioritize",
                item_ref=f"metasurvey:{event_id}",
            )
        for topic in suppress_topics:
            pe.record_feedback(
                tenant_key=tenant_key,
                principal_id=principal,
                concept_key=f"topic:{topic}",
                feedback_type="hard_dislike",
                raw_reason_code="metasurvey_suppress",
                item_ref=f"metasurvey:{event_id}",
            )
        for pub in publisher_topics:
            pe.record_feedback(
                tenant_key=tenant_key,
                principal_id=principal,
                concept_key=f"publisher:{pub}",
                feedback_type="like",
                raw_reason_code="metasurvey_publishers",
                item_ref=f"metasurvey:{event_id}",
            )
        if session_id:
            mark_execution_step_status(
                session_id,
                "execute_intent",
                "completed",
                result={
                    "prioritize_count": len(prioritize_topics),
                    "suppress_count": len(suppress_topics),
                    "publisher_count": len(publisher_topics),
                },
            )

        current_step = "persist_result"
        if session_id:
            mark_execution_step_status(session_id, "persist_result", "running")
        if depth_raw in {"short", "medium", "full"}:
            db.execute(
                """
                INSERT INTO intake_insights (insight_id, tenant, source_type, source_id, insight_json, confidence, created_at)
                VALUES (gen_random_uuid(), %s, 'metasurvey', %s, %s::jsonb, 0.80, %s)
                """,
                (
                    tenant_key,
                    str(event_id),
                    json.dumps({"principal": principal, "preferred_depth": depth_raw}),
                    _utcnow(),
                ),
            )

        db.execute(
            """
            UPDATE external_events
            SET status='processed', updated_at=NOW()
            WHERE COALESCE(to_jsonb(external_events)->>'id', to_jsonb(external_events)->>'event_id')=%s
            """,
            (str(event_id),),
        )
        if session_id:
            mark_execution_step_status(
                session_id,
                "persist_result",
                "completed",
                result={"external_event_status": "processed"},
            )
            finalize_execution_session(
                session_id,
                status="completed",
                outcome={"external_event_status": "processed", "depth": depth_raw},
            )
    except Exception as exc:
        db.execute(
            """
            UPDATE external_events
            SET status='failed', updated_at=NOW()
            WHERE COALESCE(to_jsonb(external_events)->>'id', to_jsonb(external_events)->>'event_id')=%s
            """,
            (str(event_id),),
        )
        if session_id:
            mark_execution_step_status(
                session_id,
                current_step,
                "failed",
                error_text=str(exc)[:400],
            )
            append_execution_event(
                session_id,
                level="error",
                event_type="external_event_failed",
                message="MetaSurvey event processing failed.",
                payload={"event_id": str(event_id), "step": current_step},
            )
            finalize_execution_session(
                session_id,
                status="failed",
                last_error=str(exc)[:400],
                outcome={"event_id": str(event_id), "failed_step": current_step},
            )
