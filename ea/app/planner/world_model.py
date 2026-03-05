from __future__ import annotations

import json
from typing import Any


def _safe_json(value: Any) -> str:
    if value is None:
        return "{}"
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    if isinstance(value, str):
        return json.dumps({"value": value})
    return json.dumps({"value": str(value)})


def _get_db():
    from app.db import get_db

    return get_db()


def upsert_commitment(
    *,
    tenant_key: str,
    commitment_key: str,
    domain: str = "general",
    title: str = "",
    status: str = "open",
    metadata: dict[str, Any] | None = None,
) -> bool:
    tenant = str(tenant_key or "").strip()
    key = str(commitment_key or "").strip()
    if not tenant or not key:
        return False
    try:
        db = _get_db()
        db.execute(
            """
            INSERT INTO commitments (
                tenant_key,
                commitment_key,
                domain,
                title,
                status,
                metadata_json
            )
            VALUES (%s, %s, %s, %s, %s, %s::jsonb)
            ON CONFLICT (tenant_key, commitment_key)
            DO UPDATE SET
                domain = EXCLUDED.domain,
                title = EXCLUDED.title,
                status = EXCLUDED.status,
                metadata_json = EXCLUDED.metadata_json,
                updated_at = NOW()
            """,
            (
                tenant,
                key,
                str(domain or "general"),
                str(title or "")[:500],
                str(status or "open"),
                _safe_json(metadata or {}),
            ),
        )
        return True
    except Exception:
        return False


def create_artifact(
    *,
    tenant_key: str,
    artifact_type: str,
    summary: str = "",
    content: dict[str, Any] | None = None,
    session_id: str | None = None,
    commitment_key: str | None = None,
) -> str:
    tenant = str(tenant_key or "").strip()
    art_type = str(artifact_type or "").strip().lower()
    if not tenant or not art_type:
        return ""
    try:
        db = _get_db()
        row = db.fetchone(
            """
            INSERT INTO artifacts (
                tenant_key,
                session_id,
                commitment_key,
                artifact_type,
                summary,
                content_json
            )
            VALUES (%s, %s, %s, %s, %s, %s::jsonb)
            RETURNING artifact_id
            """,
            (
                tenant,
                str(session_id or "") if session_id else None,
                str(commitment_key or "") if commitment_key else None,
                art_type,
                str(summary or "")[:1000],
                _safe_json(content or {}),
            ),
        )
        return str((row or {}).get("artifact_id") or "")
    except Exception:
        return ""


def create_followup(
    *,
    tenant_key: str,
    commitment_key: str,
    notes: str = "",
    due_at: str | None = None,
    artifact_id: str | None = None,
) -> str:
    tenant = str(tenant_key or "").strip()
    commit_key = str(commitment_key or "").strip()
    if not tenant or not commit_key:
        return ""
    try:
        db = _get_db()
        row = db.fetchone(
            """
            INSERT INTO followups (
                tenant_key,
                commitment_key,
                artifact_id,
                due_at,
                status,
                notes
            )
            VALUES (%s, %s, %s, %s::timestamptz, 'open', %s)
            RETURNING followup_id
            """,
            (
                tenant,
                commit_key,
                str(artifact_id or "") if artifact_id else None,
                str(due_at or "") if due_at else None,
                str(notes or "")[:1500],
            ),
        )
        return str((row or {}).get("followup_id") or "")
    except Exception:
        return ""


def create_decision_window(
    *,
    tenant_key: str,
    commitment_key: str,
    window_label: str,
    opens_at: str | None = None,
    closes_at: str | None = None,
) -> str:
    tenant = str(tenant_key or "").strip()
    commit_key = str(commitment_key or "").strip()
    label = str(window_label or "").strip()
    if not tenant or not commit_key or not label:
        return ""
    try:
        db = _get_db()
        row = db.fetchone(
            """
            INSERT INTO decision_windows (
                tenant_key,
                commitment_key,
                window_label,
                opens_at,
                closes_at,
                status
            )
            VALUES (%s, %s, %s, %s::timestamptz, %s::timestamptz, 'open')
            RETURNING decision_window_id
            """,
            (
                tenant,
                commit_key,
                label[:200],
                str(opens_at or "") if opens_at else None,
                str(closes_at or "") if closes_at else None,
            ),
        )
        return str((row or {}).get("decision_window_id") or "")
    except Exception:
        return ""


__all__ = [
    "upsert_commitment",
    "create_artifact",
    "create_followup",
    "create_decision_window",
]
