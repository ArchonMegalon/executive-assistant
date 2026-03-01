import asyncio, logging, os, sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from app.db import get_db

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] EVENT-WORKER: %(message)s')
logger = logging.getLogger("EventWorker")

async def poll_external_events():
    db = get_db()
    logger.info("🚀 EA Event Worker started. Polling for durable webhooks...")
    
    # Lazy import to avoid circular dependencies during boot
    from app.approvals.normalizer import process_approvethis_event
    
    while True:
        try:
            row = await db.fetchone("""
                UPDATE external_events SET status = 'processing', updated_at = NOW()
                WHERE event_id = (
                    SELECT event_id FROM external_events 
                    WHERE status = 'new' OR (status = 'processing' AND updated_at < NOW() - INTERVAL '15 minutes')
                    ORDER BY created_at ASC FOR UPDATE SKIP LOCKED LIMIT 1
                ) RETURNING event_id, source
            """)
            
            if not row:
                await asyncio.sleep(5)
                continue
                
            r = row if isinstance(row, dict) else {"event_id": row[0], "source": row[1]}
            event_id, source = str(r["event_id"]), r["source"]
            
            logger.info(f"📥 Claimed Event: {event_id} (Source: {source})")
            
            if source == 'approvethis':
                await process_approvethis_event(event_id)
            else:
                logger.warning(f"Unknown event source: {source}. Discarding.")
                await db.execute("UPDATE external_events SET status = 'discarded', updated_at = NOW() WHERE event_id = %s::uuid", (event_id,))
                
        except Exception as e:
            logger.error(f"Event Worker Loop Error: {e}")
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(poll_external_events())
