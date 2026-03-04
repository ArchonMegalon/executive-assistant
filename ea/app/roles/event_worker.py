import asyncio
import json
import traceback
from app.db import get_db


def _chat_id_from_tenant(tenant: str) -> int | None:
    raw = str(tenant or "")
    if not raw.startswith("chat_"):
        return None
    try:
        return int(raw.split("_", 1)[1])
    except Exception:
        return None


async def run_event_worker():
    print("==================================================", flush=True)
    print("📥 EA OS EVENT WORKER: External Events Ingress Online", flush=True)
    print("==================================================", flush=True)
    db = get_db()
    
    while True:
        try:
            row = await asyncio.to_thread(
                db.fetchone,
                """
                WITH picked AS (
                    SELECT COALESCE(to_jsonb(e)->>'id', to_jsonb(e)->>'event_id') AS event_pk
                    FROM external_events e
                    WHERE status IN ('new', 'queued')
                       OR (status IN ('retry', 'failed') AND next_attempt_at <= NOW())
                       OR (status='processing' AND updated_at < NOW() - INTERVAL '15 minutes')
                    ORDER BY created_at ASC
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                UPDATE external_events e
                SET status = 'processing', updated_at = NOW()
                FROM picked
                WHERE COALESCE(to_jsonb(e)->>'id', to_jsonb(e)->>'event_id') = picked.event_pk
                RETURNING
                    COALESCE(to_jsonb(e)->>'id', to_jsonb(e)->>'event_id') AS event_pk,
                    e.source,
                    e.tenant,
                    e.payload_json
                """,
            )
            
            if not row:
                await asyncio.sleep(2)
                continue
                
            event_id, source, tenant, payload = row['event_pk'], row['source'], row['tenant'], row['payload_json']
            print(f"⚙️ Processing {source} for {tenant} (ID: {event_id})", flush=True)
            outbox_chat_id = _chat_id_from_tenant(str(tenant))
            
            # Y3. Inbound adapters rule: 
            # "Gmail/Drive ingest creates an artifact-ingest job, not a direct payment execution."
            if source in ["apixdrive.gmail_invoice_ingest", "apixdrive.drive_invoice_ingest"]:
                print(f"📄 Delegating {source} to artifact-ingest action...", flush=True)
                
                # Insert a typed action for the core worker to pick up
                action_payload = {"source": source, "event_id": str(event_id), "payload": payload}
                await asyncio.to_thread(db.execute, """
                    INSERT INTO typed_actions (id, tenant, action_type, payload_json, expires_at)
                    VALUES (gen_random_uuid(), %s, 'artifact.ingest', %s, NOW() + interval '7 days')
                """, (tenant, json.dumps(action_payload)))
                
                # Notify operator
                if outbox_chat_id is not None:
                    await asyncio.to_thread(
                        db.execute,
                        """
                        INSERT INTO tg_outbox (tenant, chat_id, payload_json, status)
                        VALUES (%s, %s, %s::jsonb, 'queued')
                        """,
                        (
                            tenant,
                            int(outbox_chat_id),
                            json.dumps(
                                {
                                    "text": f"🔔 <b>New Document Ingested ({source})</b>\nArtifact ingest job successfully queued.",
                                    "parse_mode": "HTML",
                                }
                            ),
                        ),
                    )
                
            else:
                print(f"🌐 Processing generic webhook...", flush=True)
                if outbox_chat_id is not None:
                    await asyncio.to_thread(
                        db.execute,
                        """
                        INSERT INTO tg_outbox (tenant, chat_id, payload_json, status)
                        VALUES (%s, %s, %s::jsonb, 'queued')
                        """,
                        (
                            tenant,
                            int(outbox_chat_id),
                            json.dumps(
                                {"text": f"🔔 <b>Generic Webhook Received</b>\nSource: {source}", "parse_mode": "HTML"}
                            ),
                        ),
                    )
                
            await asyncio.to_thread(
                db.execute,
                """
                UPDATE external_events
                SET status = 'processed', updated_at = NOW()
                WHERE COALESCE(to_jsonb(external_events)->>'id', to_jsonb(external_events)->>'event_id') = %s
                """,
                (str(event_id),),
            )
            print(f"✅ Event {event_id} successfully processed.", flush=True)
            
        except Exception as e:
            print(f"🚨 Event Worker Error: {e}", flush=True)
            traceback.print_exc()
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(run_event_worker())
