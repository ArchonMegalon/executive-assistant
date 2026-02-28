from __future__ import annotations
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI

# Hardened boot logging
print("\n" + "!"*40, flush=True)
print("🚀 CHIEF OF STAFF SYSTEM BOOTING", flush=True)
print("!"*40 + "\n", flush=True)

from app.server import app
from app.poll_listener import poll_loop
from app.scheduler import scheduler_loop

@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    # This block executes when the server starts
    print("🤖 Background Threads: INITIALIZING...", flush=True)
    p_task = asyncio.create_task(poll_loop())
    s_task = asyncio.create_task(scheduler_loop())
    
    yield
    
    # Cleanup on shutdown
    print("🛑 Background Threads: TERMINATING...", flush=True)
    p_task.cancel()
    s_task.cancel()

# Attach lifespan to the existing FastAPI instance
app.router.lifespan_context = lifespan

from fastapi import Request, Header, HTTPException
import hashlib
import json

@app.post("/webhooks/apixdrive/{tenant}")
async def apixdrive_ingress(tenant: str, request: Request, authorization: str = Header(None)):
    from app.settings import settings
    from app.db import get_db
    
    # 1. Auth Boundary: P0 Security
    if not settings.apixdrive_shared_secret or authorization != f"Bearer {settings.apixdrive_shared_secret}":
        raise HTTPException(status_code=401, detail="Unauthorized: Invalid ApiX-Drive Secret")
        
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    source = payload.get("source", "apixdrive.generic")
    event_type = payload.get("event_type", "webhook_ingest")
    
    # 2. Derive dedupe_key (Idempotency)
    raw_dedupe = payload.get("id") or payload.get("message_id") or payload.get("file_id")
    if raw_dedupe:
        dedupe_key = str(raw_dedupe)
    else:
        dedupe_key = hashlib.md5(json.dumps(payload, sort_keys=True).encode('utf-8')).hexdigest()

    # 3. Fire & Forget Insertion
    db = get_db()
    try:
        db.execute(
            """
            INSERT INTO external_events (tenant, source, event_type, dedupe_key, payload_json)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (tenant, source, dedupe_key) DO NOTHING
            """, (tenant, source, event_type, dedupe_key, json.dumps(payload))
        )
        return {"status": "accepted", "tenant": tenant, "source": source, "dedupe_key": dedupe_key}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/webhooks/metasurvey/{tenant}")
async def metasurvey_webhook(tenant: str, request: Request):
    try: payload = await request.json()
    except: return {"error": "invalid json"}
    from app.db import get_db
    import json
    db = get_db()
    dedupe = payload.get("response_id", "unknown")
    db.execute("INSERT INTO external_events (tenant, source, event_type, dedupe_key, payload_json) VALUES (%s, 'metasurvey', 'submission', %s, %s) ON CONFLICT DO NOTHING", (tenant, dedupe, json.dumps(payload)))
    return {"status": "ok"}
