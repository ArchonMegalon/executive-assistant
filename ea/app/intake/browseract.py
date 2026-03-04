import json, logging
from app.db import get_db
from app.integrations.avomap.finalize import finalize_avomap_render_event
from app.settings import settings


def _parse_chat_id_from_tenant(tenant: str) -> int | None:
    raw = str(tenant or "")
    if not raw.startswith("chat_"):
        return None
    try:
        return int(raw.split("_", 1)[1])
    except Exception:
        return None


def _claim_active_briefing_session(db, *, chat_id: int) -> int | None:
    try:
        row = db.fetchone(
            """
            SELECT session_id
            FROM delivery_sessions
            WHERE chat_id=%s
              AND mode='briefing'
              AND status='active'
              AND enhancement_deadline_ts >= NOW()
            ORDER BY enhancement_deadline_ts DESC
            LIMIT 1
            FOR UPDATE SKIP LOCKED
            """,
            (str(chat_id),),
        ) or {}
    except Exception:
        return None
    sid = row.get("session_id")
    return int(sid) if sid is not None else None


def _maybe_enqueue_late_attach_followup(db, *, tenant: str, spec_id: str) -> None:
    chat_id = _parse_chat_id_from_tenant(tenant)
    if not chat_id:
        return
    session_id = _claim_active_briefing_session(db, chat_id=chat_id)
    if not session_id:
        return

    asset = db.fetchone(
        """
        SELECT object_ref
        FROM avomap_assets
        WHERE spec_id=%s
          AND status='ready'
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        (spec_id,),
    ) or {}
    object_ref = str((asset or {}).get("object_ref") or "").strip()
    if not object_ref:
        return

    claimed = db.fetchone(
        """
        UPDATE avomap_jobs
        SET status='delivered', updated_at=NOW()
        WHERE job_id = (
            SELECT job_id
            FROM avomap_jobs
            WHERE spec_id=%s
              AND status='completed'
              AND updated_at >= NOW() - (%s * INTERVAL '1 second')
            ORDER BY updated_at DESC
            LIMIT 1
            FOR UPDATE SKIP LOCKED
        )
        RETURNING job_id::text AS job_id
        """,
        (spec_id, int(settings.avomap_late_attach_window_sec)),
    )
    if not claimed:
        return

    payload = {
        "text": f"🎬 <b>Travel video ready</b>\n<a href=\"{object_ref}\">▶ Open video</a>",
        "parse_mode": "HTML",
    }
    idem = f"avomap_late_attach:{spec_id}:{str((claimed or {}).get('job_id') or '')}"
    db.execute(
        """
        INSERT INTO tg_outbox (tenant, chat_id, payload_json, status, idempotency_key)
        VALUES (%s, %s, %s::jsonb, 'queued', %s)
        ON CONFLICT (tenant, idempotency_key) DO NOTHING
        """,
        (tenant, int(chat_id), json.dumps(payload), idem),
    )
    db.execute(
        """
        UPDATE delivery_sessions
        SET status='enhanced'
        WHERE session_id=%s
          AND status='active'
        """,
        (int(session_id),),
    )


async def process_browseract_event(event_id: str):
    db = get_db()
    try:
        row = db.fetchone(
            """
            UPDATE external_events
            SET status='processing', updated_at=NOW()
            WHERE COALESCE(to_jsonb(external_events)->>'id', to_jsonb(external_events)->>'event_id')=%s
              AND (
                  status IN ('new', 'queued', 'retry', 'failed')
                  OR (status='processing' AND updated_at < NOW() - INTERVAL '15 minutes')
              )
            RETURNING tenant, event_type, payload_json
            """,
            (str(event_id),),
        )
        if not row: 
            if hasattr(db, 'commit'): db.commit()
            return
            
        tenant = row['tenant'] if hasattr(row, 'keys') else row[0]
        workflow = row['event_type'] if hasattr(row, 'keys') else row[1]
        p_raw = row['payload_json'] if hasattr(row, 'keys') else row[2]
        payload = json.loads(p_raw) if isinstance(p_raw, str) else p_raw
        if not isinstance(payload, dict): payload = {}

        if str(workflow or "").startswith("avomap.") or str(workflow or "") == settings.avomap_browseract_workflow:
            result = finalize_avomap_render_event(
                event_id=str(event_id),
                tenant=str(tenant),
                workflow=str(workflow),
                payload=payload,
                db=db,
            )
            ext_status = "processed" if bool(result.get("ok")) else "failed"
            db.execute(
                """
                UPDATE external_events
                SET status=%s, updated_at=NOW(), last_error=CASE WHEN %s='processed' THEN NULL ELSE %s END
                WHERE COALESCE(to_jsonb(external_events)->>'id', to_jsonb(external_events)->>'event_id')=%s
                """,
                (ext_status, ext_status, str(result)[:500], str(event_id)),
            )
            if ext_status == "processed" and str(result.get("status") or "") == "completed":
                _maybe_enqueue_late_attach_followup(
                    db,
                    tenant=str(tenant),
                    spec_id=str(result.get("spec_id") or ""),
                )
            if hasattr(db, 'commit'): db.commit()
            return

        # Autonome Extraktion der ID
        template_id = payload.get("template_id") or payload.get("data", {}).get("template_id") or payload.get("output", {}).get("template_id") or payload.get("id")
        
        if template_id:
            logging.info(f"🤖 AUTO-HEALING: Speichere Template-ID '{template_id}' für {tenant} in Registry...")
            db.execute("INSERT INTO template_registry (tenant, key, provider, template_id) VALUES (%s, 'briefing.image', 'markupgo', %s) ON CONFLICT (tenant, key, provider) DO UPDATE SET template_id = EXCLUDED.template_id", (tenant, str(template_id)))
            
            # Für Generic EA Bot ebenfalls heilen
            db.execute("INSERT INTO template_registry (tenant, key, provider, template_id) VALUES ('ea_bot', 'briefing.image', 'markupgo', %s) ON CONFLICT (tenant, key, provider) DO UPDATE SET template_id = EXCLUDED.template_id", (str(template_id),))

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
            logging.warning("🤖 AUTO-HEALING ABORTED: Kein template_id gefunden.")

        if hasattr(db, 'commit'): db.commit()
        
    except Exception as e:
        logging.error(f"BrowserAct Normalizer Error: {e}")
        db.execute(
            """
            UPDATE external_events
            SET status='failed', updated_at=NOW()
            WHERE COALESCE(to_jsonb(external_events)->>'id', to_jsonb(external_events)->>'event_id')=%s
            """,
            (str(event_id),),
        )
        if hasattr(db, 'commit'): db.commit()
