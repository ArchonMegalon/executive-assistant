from __future__ import annotations

from typing import Any


def _get_db():
    from app.db import get_db

    return get_db()


def fetch_session_plan_steps(session_id: str) -> list[dict[str, Any]]:
    sid = str(session_id or "").strip()
    if not sid:
        return []
    try:
        db = _get_db()
        rows = list(
            db.fetchall(
                """
                SELECT step_order, step_key, step_title, step_kind, status,
                       preconditions_json, evidence_json, result_json,
                       provider_key, input_refs_json, output_refs_json,
                       attempt_count, deadline_at, approval_gate_id
                FROM execution_steps
                WHERE session_id = %s
                ORDER BY step_order ASC
                """,
                (sid,),
            )
            or []
        )
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "step_order": int((row or {}).get("step_order") or 0),
                "step_key": str((row or {}).get("step_key") or ""),
                "step_title": str((row or {}).get("step_title") or ""),
                "step_kind": str((row or {}).get("step_kind") or "generic"),
                "status": str((row or {}).get("status") or ""),
                "preconditions_json": dict((row or {}).get("preconditions_json") or {}),
                "evidence_json": dict((row or {}).get("evidence_json") or {}),
                "result_json": dict((row or {}).get("result_json") or {}),
                "provider_key": str((row or {}).get("provider_key") or ""),
                "input_refs_json": list((row or {}).get("input_refs_json") or []),
                "output_refs_json": list((row or {}).get("output_refs_json") or []),
                "attempt_count": int((row or {}).get("attempt_count") or 0),
                "deadline_at": (row or {}).get("deadline_at"),
                "approval_gate_id": str((row or {}).get("approval_gate_id") or ""),
            }
        )
    return out


def resolve_execute_step_metadata(
    session_id: str,
    *,
    fallback: dict[str, Any] | None = None,
) -> dict[str, Any]:
    fallback = dict(fallback or {})
    defaults = {
        "task_type": str(fallback.get("task_type") or "free_text_response"),
        "output_artifact_type": str(fallback.get("output_artifact_type") or "chat_response"),
        "provider_candidates": list(fallback.get("provider_candidates") or []),
        "metadata_source": str(fallback.get("metadata_source") or "fallback_default"),
        "metadata_provenance": [str(x) for x in list(fallback.get("metadata_provenance") or []) if str(x or "").strip()],
    }
    sid = str(session_id or "").strip()
    if not sid:
        return defaults
    try:
        db = _get_db()
        row = db.fetchone(
            """
            SELECT evidence_json, provider_key
            FROM execution_steps
            WHERE session_id = %s AND step_key = 'execute_intent'
            ORDER BY step_order ASC
            LIMIT 1
            """,
            (sid,),
        )
    except Exception:
        return defaults
    if not row:
        return defaults
    evidence = dict((row or {}).get("evidence_json") or {})
    task_type = str(evidence.get("task_type") or defaults["task_type"]).strip().lower() or defaults["task_type"]
    artifact_type = (
        str(evidence.get("output_artifact_type") or defaults["output_artifact_type"]).strip().lower()
        or defaults["output_artifact_type"]
    )
    providers = [str(x) for x in list(evidence.get("provider_candidates") or []) if str(x or "").strip()]
    provider_key = str((row or {}).get("provider_key") or "").strip().lower()
    provenance: list[str] = []
    if evidence:
        provenance.append("ledger_evidence")
    if not providers and provider_key:
        providers = [provider_key]
        provenance.append("ledger_provider_key")
    if not providers:
        providers = [str(x) for x in list(defaults["provider_candidates"] or []) if str(x or "").strip()]
    if not provenance:
        provenance = list(defaults["metadata_provenance"] or ["fallback_default"])
    return {
        "task_type": task_type,
        "output_artifact_type": artifact_type,
        "provider_candidates": providers,
        "metadata_source": "ledger_execute_step",
        "metadata_provenance": provenance,
    }


__all__ = ["fetch_session_plan_steps", "resolve_execute_step_metadata"]
