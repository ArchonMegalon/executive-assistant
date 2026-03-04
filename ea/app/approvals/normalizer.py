import json, logging
from app.db import get_db

async def process_approvethis_event(event_id: str):
    db = get_db()
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

        if not isinstance(payload, dict): 
            db.execute(
                """
                UPDATE external_events
                SET status='discarded', updated_at=NOW()
                WHERE COALESCE(to_jsonb(external_events)->>'id', to_jsonb(external_events)->>'event_id')=%s
                """,
                (str(event_id),),
            )
            if hasattr(db, 'commit'): db.commit()
            return
            
        ref = payload.get("metadata", {}).get("internal_ref_id")
        if not ref: 
            db.execute(
                """
                UPDATE external_events
                SET status='discarded', updated_at=NOW()
                WHERE COALESCE(to_jsonb(external_events)->>'id', to_jsonb(external_events)->>'event_id')=%s
                """,
                (str(event_id),),
            )
            if hasattr(db, 'commit'): db.commit()
            return

        res = db.fetchone("UPDATE external_approvals SET status=%s, decision_payload_json=%s::jsonb, updated_at=NOW() WHERE tenant=%s AND internal_ref_id=%s AND provider='approvethis' RETURNING approval_id", (payload.get("status", "unknown"), json.dumps(payload), tenant, ref))
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
        if hasattr(db, 'commit'): db.commit()
