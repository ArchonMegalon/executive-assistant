import json, logging
from app.db import get_db
from app.execution import (
    append_execution_event,
    compile_intent_spec,
    create_execution_session,
    finalize_execution_session,
    mark_execution_session_running,
    mark_execution_step_status,
)


def _parse_chat_id_from_tenant(tenant: str) -> int | None:
    raw = str(tenant or "")
    if not raw.startswith("chat_"):
        return None
    try:
        return int(raw.split("_", 1)[1])
    except Exception:
        return None

async def process_approvethis_event(event_id: str):
    db = get_db()
    session_id = None
    current_step = "compile_intent"
    try:
        row = db.fetchone(
            """
            UPDATE external_events
            SET status='processing', updated_at=NOW()
            WHERE COALESCE(to_jsonb(external_events)->>'id', to_jsonb(external_events)->>'event_id')=%s
              AND (
                  status IN ('queued', 'retry', 'failed')
                  OR (status='processing' AND updated_at < NOW() - INTERVAL '15 minutes')
              )
            RETURNING tenant, payload_json
            """,
            (str(event_id),),
        )
        if not row: 
            if hasattr(db, 'commit'): db.commit()
            return
        
        tenant = row['tenant'] if hasattr(row, 'keys') else row[0]
        p_raw = row['payload_json'] if hasattr(row, 'keys') else row[1]
        payload = json.loads(p_raw) if isinstance(p_raw, str) else p_raw
        intent_spec = compile_intent_spec(
            text="Process ApproveThis webhook event",
            tenant=str(tenant),
            chat_id=_parse_chat_id_from_tenant(str(tenant)),
            has_url=False,
        )
        intent_spec["source"] = "approvethis"
        intent_spec["event_id"] = str(event_id)
        session_id = create_execution_session(
            tenant=str(tenant),
            chat_id=_parse_chat_id_from_tenant(str(tenant)),
            intent_spec=intent_spec,
            plan_steps=[
                {"step_key": "compile_intent", "step_title": "Compile Event Intent"},
                {"step_key": "execute_intent", "step_title": "Normalize Approval Event"},
                {"step_key": "persist_result", "step_title": "Persist Event Result"},
            ],
            source="external_event_approvethis",
            correlation_id=f"approvethis:{tenant}:{event_id}",
        )
        if session_id:
            mark_execution_session_running(session_id)
            mark_execution_step_status(session_id, "compile_intent", "completed", result=intent_spec)
            append_execution_event(
                session_id,
                event_type="external_event_claimed",
                message="ApproveThis event claimed for processing.",
                payload={"event_id": str(event_id)},
            )

        current_step = "execute_intent"
        if session_id:
            mark_execution_step_status(
                session_id,
                "execute_intent",
                "running",
                evidence={"event_id": str(event_id)},
            )
        if not isinstance(payload, dict): 
            if session_id:
                mark_execution_step_status(
                    session_id,
                    "execute_intent",
                    "completed",
                    result={"payload_valid": False},
                )
                mark_execution_step_status(session_id, "persist_result", "running")
            db.execute(
                """
                UPDATE external_events
                SET status='discarded', updated_at=NOW()
                WHERE COALESCE(to_jsonb(external_events)->>'id', to_jsonb(external_events)->>'event_id')=%s
                """,
                (str(event_id),),
            )
            if session_id:
                mark_execution_step_status(
                    session_id,
                    "persist_result",
                    "completed",
                    result={"external_event_status": "discarded"},
                )
                finalize_execution_session(
                    session_id,
                    status="completed",
                    outcome={"external_event_status": "discarded", "reason": "invalid_payload"},
                )
            if hasattr(db, 'commit'): db.commit()
            return
            
        ref = payload.get("metadata", {}).get("internal_ref_id")
        if not ref: 
            if session_id:
                mark_execution_step_status(
                    session_id,
                    "execute_intent",
                    "completed",
                    result={"payload_valid": True, "has_internal_ref": False},
                )
                mark_execution_step_status(session_id, "persist_result", "running")
            db.execute(
                """
                UPDATE external_events
                SET status='discarded', updated_at=NOW()
                WHERE COALESCE(to_jsonb(external_events)->>'id', to_jsonb(external_events)->>'event_id')=%s
                """,
                (str(event_id),),
            )
            if session_id:
                mark_execution_step_status(
                    session_id,
                    "persist_result",
                    "completed",
                    result={"external_event_status": "discarded"},
                )
                finalize_execution_session(
                    session_id,
                    status="completed",
                    outcome={"external_event_status": "discarded", "reason": "missing_internal_ref"},
                )
            if hasattr(db, 'commit'): db.commit()
            return

        res = db.fetchone("UPDATE external_approvals SET status=%s, decision_payload_json=%s::jsonb, updated_at=NOW() WHERE tenant=%s AND internal_ref_id=%s AND provider='approvethis' RETURNING approval_id", (payload.get("status", "unknown"), json.dumps(payload), tenant, ref))
        if session_id:
            mark_execution_step_status(
                session_id,
                "execute_intent",
                "completed",
                result={"payload_valid": True, "has_internal_ref": True, "approval_row_updated": bool(res)},
            )
            mark_execution_step_status(session_id, "persist_result", "running")
        if res:
            db.execute(
                """
                UPDATE external_events
                SET status='processed', updated_at=NOW()
                WHERE COALESCE(to_jsonb(external_events)->>'id', to_jsonb(external_events)->>'event_id')=%s
                """,
                (str(event_id),),
            )
        else:
            db.execute(
                """
                UPDATE external_events
                SET status='discarded', updated_at=NOW()
                WHERE COALESCE(to_jsonb(external_events)->>'id', to_jsonb(external_events)->>'event_id')=%s
                """,
                (str(event_id),),
            )
        if session_id:
            ext_status = "processed" if res else "discarded"
            mark_execution_step_status(
                session_id,
                "persist_result",
                "completed",
                result={"external_event_status": ext_status},
            )
            finalize_execution_session(
                session_id,
                status="completed",
                outcome={"external_event_status": ext_status, "approval_row_updated": bool(res)},
            )
        if hasattr(db, 'commit'): db.commit()
    except Exception as e:
        logging.error(f"Normalizer Error: {e}")
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
                error_text=str(e)[:400],
            )
            append_execution_event(
                session_id,
                level="error",
                event_type="external_event_failed",
                message="ApproveThis event processing failed.",
                payload={"event_id": str(event_id), "step": current_step},
            )
            finalize_execution_session(
                session_id,
                status="failed",
                last_error=str(e)[:400],
                outcome={"event_id": str(event_id), "failed_step": current_step},
            )
        if hasattr(db, 'commit'): db.commit()
