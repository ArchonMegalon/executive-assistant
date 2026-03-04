from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from app.db import get_db
from app.personalization.engine import PersonalizationEngine


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


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
    hidden = payload.get("hidden_fields") or payload.get("hidden") or {}
    answers = payload.get("answers") or payload.get("response") or payload.get("data") or {}
    if not isinstance(hidden, dict):
        hidden = {}
    if not isinstance(answers, dict):
        answers = {}

    principal = str(hidden.get("principal") or payload.get("principal") or payload.get("principal_id") or "unknown")
    tenant_key = str(hidden.get("tenant") or tenant or "unknown")

    pe = PersonalizationEngine()

    prioritize_raw = (
        answers.get("prioritize_topics")
        or answers.get("topics_to_prioritize")
        or answers.get("preferred_topics")
        or answers.get("q1")
        or ""
    )
    suppress_raw = (
        answers.get("suppress_topics")
        or answers.get("topics_to_suppress")
        or answers.get("avoid_topics")
        or answers.get("q2")
        or ""
    )
    publishers_raw = answers.get("publishers") or answers.get("useful_publishers") or answers.get("q3") or ""
    depth_raw = str(answers.get("depth") or answers.get("detail_depth") or answers.get("q4") or "").strip().lower()

    for topic in _tokenize_topics(prioritize_raw):
        pe.record_feedback(
            tenant_key=tenant_key,
            principal_id=principal,
            concept_key=f"topic:{topic}",
            feedback_type="like",
            raw_reason_code="metasurvey_prioritize",
            item_ref=f"metasurvey:{event_id}",
        )
    for topic in _tokenize_topics(suppress_raw):
        pe.record_feedback(
            tenant_key=tenant_key,
            principal_id=principal,
            concept_key=f"topic:{topic}",
            feedback_type="hard_dislike",
            raw_reason_code="metasurvey_suppress",
            item_ref=f"metasurvey:{event_id}",
        )
    for pub in _tokenize_topics(publishers_raw):
        pe.record_feedback(
            tenant_key=tenant_key,
            principal_id=principal,
            concept_key=f"publisher:{pub}",
            feedback_type="like",
            raw_reason_code="metasurvey_publishers",
            item_ref=f"metasurvey:{event_id}",
        )

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
