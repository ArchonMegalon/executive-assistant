from __future__ import annotations

import json
import os
import uuid
from typing import Any, Sequence

from app.db import get_db
from app.planner.intent_compiler import compile_intent_spec_v2
from app.planner.plan_builder import build_task_plan_steps

_STATUS_VALUES = {"queued", "running", "completed", "failed", "skipped"}


def _safe_json(value: Any) -> str:
    if value is None:
        return "{}"
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    if isinstance(value, str):
        return json.dumps({"value": value})
    return json.dumps({"value": str(value)})


def _normalize_status(status: str, *, default: str = "queued") -> str:
    raw = str(status or "").strip().lower()
    if raw in _STATUS_VALUES:
        return raw
    return default


def _normalize_approval_state(value: str) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"none", "pending", "approved", "rejected", "cancelled", "expired", "staging_failed"}:
        return raw
    return "none"


def _infer_step_kind(step_key: str) -> str:
    key = str(step_key or "").strip().lower()
    if key in {"compile_intent"}:
        return "compile"
    if key in {"gather_evidence", "collect_intake_context", "collect_feedback_context", "gather_project_context", "review_health_context", "gather_research_context", "analyze_trip_commitment", "compare_travel_options", "verify_payment_context", "ingest_external_event", "prepare_external_action", "prepare_route_render_context", "prepare_multimodal_context", "prepare_draft_context"}:
        return "context"
    if key in {"safety_gate", "build_approval_context"}:
        return "approval"
    if key in {"execute_intent"}:
        return "execution"
    if key in {"render_reply"}:
        return "render"
    return "generic"


def _coerce_json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            loaded = json.loads(value)
        except Exception:
            return {}
        if isinstance(loaded, dict):
            return dict(loaded)
    return {}


def _normalize_memory_text(text: str, *, limit: int = 1400) -> str:
    cleaned = " ".join(str(text or "").replace("\n", " ").split())
    return cleaned[:limit].strip()


def _looks_runtime_like(text: str) -> bool:
    sample = str(text or "").lower()
    if not sample:
        return True
    markers = (
        "traceback",
        "fatal event loop deadlock",
        "tool_call",
        '"role":',
        "[options:",
        "llm gateway",
    )
    return sum(1 for marker in markers if marker in sample) >= 2


def _build_memory_candidate_fact(
    *,
    objective: str,
    final_status: str,
    outcome: dict[str, Any],
) -> str:
    objective_text = _normalize_memory_text(objective, limit=700)
    if not objective_text:
        return ""
    result = _normalize_memory_text(str(outcome.get("result") or ""), limit=120)
    if final_status == "completed":
        tail = f" Outcome: {result}." if result else " Outcome: completed."
        return f"{objective_text}.{tail}"
    if final_status == "partial":
        blocked = _normalize_memory_text(str(outcome.get("blocked_reason") or ""), limit=120)
        if blocked:
            return f"{objective_text}. Pending gate: {blocked}."
        return f"{objective_text}. Pending approval or follow-up."
    return ""


def _load_session_context(session_id: str) -> dict[str, Any]:
    try:
        db = get_db()
        if not hasattr(db, "fetchone"):
            return {}
        row = db.fetchone(
            """
            SELECT tenant, intent_type, objective, intent_spec_json
            FROM execution_sessions
            WHERE session_id = %s
            LIMIT 1
            """,
            (str(session_id),),
        )
        return dict(row or {})
    except Exception:
        return {}


def _emit_finalize_memory_candidate(
    *,
    session_id: str,
    final_status: str,
    outcome: dict[str, Any] | None = None,
    last_error: str | None = None,
) -> None:
    if final_status not in {"completed", "partial"}:
        return
    if last_error:
        return
    session_row = _load_session_context(session_id)
    tenant = str((session_row or {}).get("tenant") or "").strip()
    if not tenant:
        return
    intent_type = str((session_row or {}).get("intent_type") or "").strip().lower() or "free_text"
    objective = str((session_row or {}).get("objective") or "")
    intent_spec = _coerce_json_dict((session_row or {}).get("intent_spec_json"))
    task_type = str(intent_spec.get("task_type") or "").strip().lower()
    domain = str(intent_spec.get("domain") or "").strip().lower()
    concept = task_type or domain or intent_type or "general"
    outcome_dict = dict(outcome or {})
    fact = _build_memory_candidate_fact(objective=objective, final_status=final_status, outcome=outcome_dict)
    fact = _normalize_memory_text(fact, limit=1600)
    if not fact or _looks_runtime_like(fact):
        return
    payload = {
        "source": "session_finalize",
        "status": final_status,
        "intent_type": intent_type,
        "task_type": task_type,
        "domain": domain,
        "result": str(outcome_dict.get("result") or "")[:120],
    }
    try:
        from app.planner.memory_candidates import emit_memory_candidate

        candidate_id = str(
            emit_memory_candidate(
                tenant_key=tenant,
                source_session_id=session_id,
                concept=concept[:120],
                candidate_fact=fact,
                confidence=0.72 if final_status == "completed" else 0.62,
                sensitivity="internal",
                sharing_policy="private",
                payload=payload,
            )
            or ""
        )
    except Exception:
        candidate_id = ""
    if candidate_id:
        append_execution_event(
            session_id,
            event_type="memory_candidate_emitted",
            message="Memory candidate emitted from finalized session.",
            payload={"memory_candidate_id": candidate_id, "concept": concept[:120]},
        )


def compile_intent_spec(
    *,
    text: str,
    tenant: str = "",
    chat_id: int | None = None,
    has_url: bool | None = None,
) -> dict[str, Any]:
    return compile_intent_spec_v2(
        text=str(text or ""),
        tenant=str(tenant or ""),
        chat_id=int(chat_id) if chat_id is not None else None,
        has_url=bool(has_url),
    )


def build_plan_steps(*, intent_spec: dict[str, Any]) -> list[dict[str, Any]]:
    return build_task_plan_steps(intent_spec=dict(intent_spec or {}))


def append_execution_event(
    session_id: str,
    *,
    event_type: str,
    message: str = "",
    level: str = "info",
    payload: dict[str, Any] | None = None,
) -> None:
    if not session_id:
        return
    try:
        db = get_db()
        db.execute(
            """
            INSERT INTO execution_events (session_id, level, event_type, message, payload_json)
            VALUES (%s, %s, %s, %s, %s::jsonb)
            """,
            (
                str(session_id),
                str(level or "info"),
                str(event_type or "event"),
                str(message or ""),
                _safe_json(payload or {}),
            ),
        )
    except Exception:
        return


def create_approval_gate(
    *,
    session_id: str,
    tenant: str,
    chat_id: int | None,
    approval_class: str = "explicit_callback_required",
    action_id: str | None = None,
    decision_payload: dict[str, Any] | None = None,
    ttl_sec: int | None = None,
) -> str | None:
    if not session_id:
        return None
    try:
        db = get_db()
        gate_id = str(uuid.uuid4())
        ttl_raw = int(ttl_sec) if ttl_sec is not None else int(os.environ.get("EA_APPROVAL_GATE_TTL_SEC") or 86400)
        ttl = max(60, min(int(ttl_raw), 7 * 24 * 3600))
        db.execute(
            """
            INSERT INTO approval_gates (
                approval_gate_id,
                session_id,
                tenant,
                chat_id,
                approval_class,
                decision_status,
                action_id,
                decision_payload_json,
                expires_at,
                decision_source
            )
            VALUES (%s, %s, %s, %s, %s, 'pending', %s, %s::jsonb, NOW() + (%s * INTERVAL '1 second'), %s)
            """,
            (
                gate_id,
                str(session_id),
                str(tenant or ""),
                int(chat_id) if chat_id is not None else None,
                str(approval_class or "explicit_callback_required"),
                str(action_id or "") if action_id else None,
                _safe_json(decision_payload or {}),
                ttl,
                "runtime_create",
            ),
        )
        return gate_id
    except Exception:
        return None


def attach_approval_gate_action(approval_gate_id: str, action_id: str) -> None:
    if not approval_gate_id or not action_id:
        return
    try:
        db = get_db()
        db.execute(
            """
            UPDATE approval_gates
            SET action_id = %s,
                updated_at = NOW()
            WHERE approval_gate_id = %s
            """,
            (str(action_id), str(approval_gate_id)),
        )
    except Exception:
        return


def mark_approval_gate_decision(
    approval_gate_id: str,
    *,
    decision_status: str,
    decision_payload: dict[str, Any] | None = None,
    decision_source: str = "",
    decision_actor: str = "",
    decision_ref: str = "",
) -> None:
    if not approval_gate_id:
        return
    status = str(decision_status or "").strip().lower() or "pending"
    try:
        db = get_db()
        db.execute(
            """
            UPDATE approval_gates
            SET decision_status = %s,
                decision_payload_json = CASE
                    WHEN %s::jsonb = '{}'::jsonb THEN decision_payload_json
                    ELSE %s::jsonb
                END,
                decided_at = CASE
                    WHEN %s IN ('approved','rejected','cancelled','expired','staging_failed') THEN COALESCE(decided_at, NOW())
                    ELSE decided_at
                END,
                decision_source = CASE
                    WHEN %s <> '' THEN %s
                    ELSE decision_source
                END,
                decision_actor = CASE
                    WHEN %s <> '' THEN %s
                    ELSE decision_actor
                END,
                decision_ref = CASE
                    WHEN %s <> '' THEN %s
                    ELSE decision_ref
                END,
                updated_at = NOW()
            WHERE approval_gate_id = %s
              AND decision_status = 'pending'
            """,
            (
                status,
                _safe_json(decision_payload or {}),
                _safe_json(decision_payload or {}),
                status,
                str(decision_source or ""),
                str(decision_source or ""),
                str(decision_actor or ""),
                str(decision_actor or ""),
                str(decision_ref or ""),
                str(decision_ref or ""),
                str(approval_gate_id),
            ),
        )
        if status in {"approved", "rejected", "cancelled", "expired", "staging_failed"}:
            db.execute(
                """
                UPDATE execution_sessions
                SET approval_state = %s,
                    updated_at = NOW()
                WHERE session_id IN (
                    SELECT session_id FROM approval_gates WHERE approval_gate_id = %s
                )
                """,
                (status, str(approval_gate_id)),
            )
    except Exception:
        return


def get_approval_gate(approval_gate_id: str) -> dict[str, Any] | None:
    if not approval_gate_id:
        return None
    try:
        db = get_db()
        if not hasattr(db, "fetchone"):
            return None
        row = db.fetchone(
            """
            SELECT approval_gate_id, session_id, tenant, chat_id, approval_class,
                   decision_status, action_id, decision_payload_json, expires_at,
                   decision_source, decision_actor, decision_ref, decided_at,
                   (expires_at IS NULL OR expires_at > NOW()) AS not_expired
            FROM approval_gates
            WHERE approval_gate_id = %s
            LIMIT 1
            """,
            (str(approval_gate_id),),
        )
        return dict(row or {}) if row else None
    except Exception:
        return None


def evaluate_approval_gate(approval_gate_id: str) -> tuple[bool, str]:
    row = get_approval_gate(approval_gate_id)
    if not row:
        return False, "missing"
    status = str((row or {}).get("decision_status") or "").strip().lower() or "pending"
    if status != "pending":
        return False, f"already_{status}"
    not_expired = bool((row or {}).get("not_expired"))
    if not not_expired:
        mark_approval_gate_decision(
            approval_gate_id,
            decision_status="expired",
            decision_payload={"reason": "approval_gate_expired"},
            decision_source="runtime_expiry_check",
            decision_ref=str(approval_gate_id),
        )
        return False, "expired"
    return True, "ok"


def create_execution_session(
    *,
    tenant: str,
    chat_id: int | None,
    intent_spec: dict[str, Any],
    plan_steps: Sequence[dict[str, Any]],
    source: str = "telegram_free_text",
    correlation_id: str | None = None,
) -> str | None:
    try:
        db = get_db()
        session_id = str(uuid.uuid4())
        spec = dict(intent_spec or {})
        objective = str(spec.get("objective") or "")[:1200]
        intent_type = str(spec.get("intent_type") or "free_text")
        task_type = str(spec.get("task_type") or "").strip().lower()
        task_contract_key = task_type if task_type else ""
        approval_state = _normalize_approval_state(
            "pending" if str(spec.get("approval_class") or "").strip().lower() == "explicit_callback_required" else "none"
        )
        risk_class = str(spec.get("risk_class") or "").strip().lower()
        budget_json = {
            "budget_class": str(spec.get("budget_class") or "").strip().lower(),
            "deadline_hint": str(spec.get("deadline_hint") or "").strip().lower(),
        }
        session_class = str(spec.get("session_class") or "primary").strip().lower() or "primary"
        parent_session_id = str(spec.get("parent_session_id") or "").strip() or None
        commitment_key = str(spec.get("commitment_key") or "").strip() or None
        db.execute(
            """
            INSERT INTO execution_sessions (
                session_id,
                tenant,
                source,
                chat_id,
                intent_type,
                objective,
                intent_spec_json,
                task_type,
                task_contract_key,
                approval_state,
                risk_class,
                budget_json,
                parent_session_id,
                session_class,
                commitment_key,
                status,
                correlation_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, 'queued', %s)
            """,
            (
                session_id,
                str(tenant or ""),
                str(source or "telegram_free_text"),
                int(chat_id) if chat_id is not None else None,
                intent_type,
                objective,
                _safe_json(spec),
                task_type,
                task_contract_key,
                approval_state,
                risk_class,
                _safe_json(budget_json),
                parent_session_id,
                session_class,
                commitment_key,
                str(correlation_id or ""),
            ),
        )
        for idx, step in enumerate(plan_steps or [], start=1):
            step_key = str((step or {}).get("step_key") or f"step_{idx}")
            step_title = str((step or {}).get("step_title") or step_key)
            step_kind = _infer_step_kind(step_key)
            preconditions = (step or {}).get("preconditions_json") if isinstance(step, dict) else {}
            evidence = (step or {}).get("evidence_json") if isinstance(step, dict) else {}
            provider_key: str | None = None
            input_refs: list[str] = []
            output_refs: list[str] = []
            approval_gate_id: str | None = None
            deadline_at = None
            if isinstance(step, dict):
                meta_preconditions = dict(preconditions or {})
                meta_evidence = dict(evidence or {})
                if (step or {}).get("budget_policy"):
                    meta_preconditions["budget_policy"] = str((step or {}).get("budget_policy"))
                if (step or {}).get("approval_default"):
                    meta_preconditions["approval_default"] = str((step or {}).get("approval_default"))
                if (step or {}).get("task_type"):
                    meta_evidence["task_type"] = str((step or {}).get("task_type"))
                provider_candidates = list((step or {}).get("provider_candidates") or [])
                if provider_candidates:
                    meta_evidence["provider_candidates"] = [str(x) for x in provider_candidates if str(x or "").strip()]
                    provider_key = str(meta_evidence["provider_candidates"][0] or "").strip().lower() or None
                if (step or {}).get("output_artifact_type"):
                    meta_evidence["output_artifact_type"] = str((step or {}).get("output_artifact_type"))
                    output_refs.append(str((step or {}).get("output_artifact_type")))
                preconditions = meta_preconditions
                evidence = meta_evidence
            db.execute(
                """
                INSERT INTO execution_steps (
                    step_id,
                    session_id,
                    step_order,
                    step_key,
                    step_title,
                    step_kind,
                    provider_key,
                    input_refs_json,
                    output_refs_json,
                    attempt_count,
                    deadline_at,
                    approval_gate_id,
                    status,
                    preconditions_json,
                    evidence_json
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, 0, %s, %s, 'queued', %s::jsonb, %s::jsonb)
                """,
                (
                    str(uuid.uuid4()),
                    session_id,
                    int(idx),
                    step_key,
                    step_title,
                    step_kind,
                    provider_key,
                    _safe_json(input_refs),
                    _safe_json(output_refs),
                    deadline_at,
                    approval_gate_id,
                    _safe_json(preconditions),
                    _safe_json(evidence),
                ),
            )
        append_execution_event(
            session_id,
            event_type="session_created",
            message="Execution session created.",
            payload={"step_count": len(list(plan_steps or []))},
        )
        return session_id
    except Exception:
        return None


def mark_execution_session_running(session_id: str) -> None:
    if not session_id:
        return
    try:
        db = get_db()
        db.execute(
            """
            UPDATE execution_sessions
            SET status = 'running',
                started_at = COALESCE(started_at, NOW()),
                updated_at = NOW()
            WHERE session_id = %s
            """,
            (str(session_id),),
        )
        append_execution_event(
            session_id,
            event_type="session_running",
            message="Execution session marked running.",
        )
    except Exception:
        return


def mark_execution_step_status(
    session_id: str,
    step_key: str,
    status: str,
    *,
    result: dict[str, Any] | None = None,
    evidence: dict[str, Any] | None = None,
    error_text: str | None = None,
    input_refs: list[str] | None = None,
    output_refs: list[str] | None = None,
    provider_key: str | None = None,
    step_kind: str | None = None,
) -> None:
    if not session_id or not step_key:
        return
    st = _normalize_status(status)
    try:
        db = get_db()
        result_json = _safe_json(result or {})
        evidence_json = _safe_json(evidence or {})
        input_refs_json = _safe_json([str(x) for x in list(input_refs or []) if str(x or "").strip()])
        output_refs_json = _safe_json([str(x) for x in list(output_refs or []) if str(x or "").strip()])
        has_input_refs = bool(input_refs)
        has_output_refs = bool(output_refs)
        provider_val = str(provider_key or "").strip().lower()
        has_provider = bool(provider_val)
        step_kind_val = str(step_kind or "").strip().lower()
        has_step_kind = bool(step_kind_val)
        db.execute(
            """
            UPDATE execution_steps
            SET status = %s,
                result_json = CASE WHEN %s::jsonb = '{}'::jsonb THEN result_json ELSE %s::jsonb END,
                evidence_json = CASE WHEN %s::jsonb = '{}'::jsonb THEN evidence_json ELSE %s::jsonb END,
                input_refs_json = CASE WHEN %s THEN %s::jsonb ELSE input_refs_json END,
                output_refs_json = CASE WHEN %s THEN %s::jsonb ELSE output_refs_json END,
                provider_key = CASE WHEN %s THEN %s ELSE provider_key END,
                step_kind = CASE WHEN %s THEN %s ELSE step_kind END,
                error_text = %s,
                started_at = CASE WHEN %s = 'running' AND started_at IS NULL THEN NOW() ELSE started_at END,
                finished_at = CASE WHEN %s IN ('completed','failed','skipped') THEN NOW() ELSE finished_at END,
                updated_at = NOW()
            WHERE session_id = %s AND step_key = %s
            """,
            (
                st,
                result_json,
                result_json,
                evidence_json,
                evidence_json,
                has_input_refs,
                input_refs_json,
                has_output_refs,
                output_refs_json,
                has_provider,
                provider_val,
                has_step_kind,
                step_kind_val,
                str(error_text or "") if error_text else None,
                st,
                st,
                str(session_id),
                str(step_key),
            ),
        )
    except Exception:
        return


def finalize_execution_session(
    session_id: str,
    *,
    status: str,
    outcome: dict[str, Any] | None = None,
    last_error: str | None = None,
) -> None:
    if not session_id:
        return
    final_status = str(status or "").strip().lower()
    if final_status not in {"completed", "failed", "cancelled", "partial"}:
        final_status = "failed" if last_error else "completed"
    try:
        db = get_db()
        db.execute(
            """
            UPDATE execution_sessions
            SET status = %s,
                outcome_json = %s::jsonb,
                last_error = %s,
                finished_at = NOW(),
                updated_at = NOW()
            WHERE session_id = %s
            """,
            (
                final_status,
                _safe_json(outcome or {}),
                str(last_error or "") if last_error else None,
                str(session_id),
            ),
        )
        append_execution_event(
            session_id,
            level="error" if final_status == "failed" else "info",
            event_type="session_finalized",
            message="Execution session finalized.",
            payload={"status": final_status, "has_error": bool(last_error)},
        )
        _emit_finalize_memory_candidate(
            session_id=session_id,
            final_status=final_status,
            outcome=dict(outcome or {}),
            last_error=last_error,
        )
    except Exception:
        return


__all__ = [
    "append_execution_event",
    "attach_approval_gate_action",
    "build_plan_steps",
    "compile_intent_spec",
    "create_approval_gate",
    "create_execution_session",
    "evaluate_approval_gate",
    "finalize_execution_session",
    "get_approval_gate",
    "mark_approval_gate_decision",
    "mark_execution_session_running",
    "mark_execution_step_status",
]
